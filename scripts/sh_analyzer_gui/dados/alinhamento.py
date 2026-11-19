"""O alinhamento de traços no tempo (TR-07, docs/gui-plan.md, 9.6), sem Qt: o atraso de um traço em relação a uma
referência, medido nas amostras (nunca no desenho), para o deslocamento no tempo do traço desfazer.

Os dois métodos olham o trecho ``[a, b]`` da referência (os cursores, ou a janela visível) e procuram o traço até
``busca`` segundos para cada lado (o traço é lido em ``[a − busca, b + busca]``):

* **Correlação cruzada:** o coeficiente de Pearson entre a referência e cada pedaço do traço do mesmo tamanho (em
  todo deslocamento, com a sobreposição inteira: nenhum deslocamento leva vantagem por cobrir mais amostras), pela
  FFT, e o pico refinado abaixo de uma amostra pela interpolação de banda limitada do coeficiente (:func:`_refinar`).
  Num sinal periódico, os picos de um período a outro empatam (só o ruído os separa): vale o menor deslocamento entre
  os que chegam perto do maior (:data:`EMPATE` do que falta a ele para 1, nunca menos que :data:`EMPATE_MINIMO`), e o
  resultado diz que o sinal se repete.
* **Cruzamento por zero:** os cruzamentos de subida pelo meio da excursão, com histerese de :data:`HISTERESE` da
  amplitude (o ruído perto do zero não conta como cruzamento), cada um no zero da reta ajustada às amostras da
  subida; cada um da referência casa com o do traço mais perto, e o atraso é a média dos casados (o desvio deles diz
  a precisão).

O tempo de cada amostra é o da vista: ``t0`` (o tempo da primeira amostra lida, com o deslocamento de agora) mais
``n / taxa``. **O atraso** ``τ`` é quanto o traço está atrasado: o traço é a referência ``τ`` segundos depois, e o
deslocamento que alinha é o de agora menos ``τ``. Com taxas diferentes, o traço é interpolado (linear) nos instantes
da referência, e o resultado avisa.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

METODOS = ("correlacao", "zero")
EMPATE = 0.1                  # do que falta ao maior coeficiente para 1: os picos assim perto dele empatam
EMPATE_MINIMO = 1e-4          # (um sinal periódico: os períodos só diferem pelo ruído; a ondulação de uma harmônica
                              # em volta do pico perde mais que isso, e não empata)
HISTERESE = 0.1               # do RMS: o cruzamento por zero só conta depois de sair dessa faixa em volta do zero
MINIMO_DE_AMOSTRAS = 16
NOS_DO_REFINO = 13           # os nós de Chebyshev da correlação entre as amostras, em volta do pico
MAXIMO_DE_AMOSTRAS = 1 << 23  # por traço: 8 Mi amostras (~64 MB em float64), a conta cabe e não prende a tela


class AlinhamentoImpossivel(ValueError):
    """O trecho não dá um atraso: curto, constante, sem cruzamentos, o traço sem dados ali..."""


@dataclass(frozen=True)
class Trecho:
    """Os valores de um traço (na unidade dele, com a cadeia, o ganho e o offset), o tempo da primeira amostra na
    vista (s) e a taxa (Hz)."""
    valores: np.ndarray
    t0: float
    taxa: float

    def tempos(self) -> np.ndarray:
        return self.t0 + np.arange(len(self.valores)) / self.taxa


@dataclass(frozen=True)
class Alinhamento:
    metodo: str
    atraso_s: float            # τ: o traço é a referência τ segundos depois (o deslocamento que alinha: −τ)
    qualidade: float           # o coeficiente de correlação no pico, ou o desvio dos cruzamentos casados (s)
    amostras: int              # da referência usadas
    aviso: str = ""
    casados: int = 0           # os cruzamentos casados (no cruzamento por zero)


def alinhar(metodo: str, referencia: Trecho, traco: Trecho) -> Alinhamento:
    if metodo not in METODOS:
        raise ValueError(f"método de alinhamento desconhecido: {metodo!r}")
    for nome, t in (("a referência", referencia), ("o traço", traco)):
        if len(t.valores) < MINIMO_DE_AMOSTRAS:
            raise AlinhamentoImpossivel(f"{nome} tem poucas amostras no trecho ({len(t.valores)})")
        if len(t.valores) > MAXIMO_DE_AMOSTRAS:
            raise AlinhamentoImpossivel(f"trecho grande demais ({len(t.valores)} amostras em {nome}): aproxime o "
                                        "zoom ou use os cursores")
        if not np.all(np.isfinite(t.valores)):
            raise AlinhamentoImpossivel(f"{nome} tem valores não finitos no trecho")
    aviso = ""
    if not math.isclose(referencia.taxa, traco.taxa, rel_tol=1e-12):
        traco = _na_taxa_da_referencia(referencia, traco)
        aviso = "taxas diferentes: o traço foi interpolado nos instantes da referência"
    feito = _por_correlacao(referencia, traco) if metodo == "correlacao" else _por_zero(referencia, traco)
    if aviso:
        feito = Alinhamento(feito.metodo, feito.atraso_s, feito.qualidade, feito.amostras,
                            "; ".join(a for a in (feito.aviso, aviso) if a))
    return feito


def _na_taxa_da_referencia(referencia: Trecho, traco: Trecho) -> Trecho:
    t = traco.tempos()
    passo = 1.0 / referencia.taxa
    # Os instantes da grade da referência que caem dentro do traço (a mesma fase da grade dela).
    k0 = math.ceil((t[0] - referencia.t0) / passo)
    k1 = math.floor((t[-1] - referencia.t0) / passo)
    if k1 - k0 + 1 < MINIMO_DE_AMOSTRAS:
        raise AlinhamentoImpossivel("o traço tem poucas amostras no trecho")
    instantes = referencia.t0 + np.arange(k0, k1 + 1) * passo
    return Trecho(np.interp(instantes, t, traco.valores), float(instantes[0]), referencia.taxa)


def _por_correlacao(referencia: Trecho, traco: Trecho) -> Alinhamento:
    from scipy.fft import irfft, next_fast_len, rfft

    r = referencia.valores - referencia.valores.mean()
    s = traco.valores - traco.valores.mean()
    n = len(r)
    if len(s) < n:
        raise AlinhamentoImpossivel("o traço não cobre o trecho da referência: escolha um trecho onde os dois têm "
                                    "dados")
    energia_r = float(np.dot(r, r))
    if energia_r <= 0.0:
        raise AlinhamentoImpossivel("a referência é constante no trecho")
    # O espectro cruzado, com o zero que tira a volta da FFT: c[k] = Σ s[n+k]·r[n] para k = 0 .. len(s) − n (a
    # sobreposição inteira) são os primeiros pontos da correlação circular.
    tamanho = next_fast_len(len(s) + n - 1, real=True)
    cruzado = rfft(s, tamanho) * np.conj(rfft(r, tamanho))
    c = irfft(cruzado, tamanho)[:len(s) - n + 1]
    soma = np.concatenate(([0.0], np.cumsum(s)))
    soma2 = np.concatenate(([0.0], np.cumsum(s * s)))
    janela, janela2 = soma[n:] - soma[:-n], soma2[n:] - soma2[:-n]
    variancia = np.maximum(janela2 - janela * janela / n, 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        rho = np.where(variancia > 1e-300, c / np.sqrt(variancia * energia_r), 0.0)
    melhor = float(rho.max())
    if not math.isfinite(melhor) or melhor <= 0.0:
        raise AlinhamentoImpossivel("o traço não se parece com a referência em nenhum deslocamento do trecho")
    # Os empates: cada trecho contínuo acima de (maior − tolerância) é um casamento (num sinal periódico, um por
    # período), e o pico de cada um é o máximo dele. Vale o de menor deslocamento.
    tolerancia = max(EMPATE_MINIMO, EMPATE * (1.0 - melhor))
    acima = np.concatenate(([0], (rho >= melhor - tolerancia).astype(np.int8), [0]))
    bordas = np.diff(acima)
    picos = np.array([c_ + int(np.argmax(rho[c_:f]))
                      for c_, f in zip(np.nonzero(bordas == 1)[0], np.nonzero(bordas == -1)[0])])
    base = traco.t0 - referencia.t0
    deslocamentos = base + picos / referencia.taxa
    k = int(picos[np.argmin(np.abs(deslocamentos))])
    fracao, pico = _refinar(cruzado, tamanho, variancia, energia_r, k, float(rho[k]))
    aviso = ""
    if len(picos) > 1:
        outros = sorted({round(float(x) * 1e3, 3) for x in np.delete(deslocamentos, np.where(picos == k)[0])},
                        key=abs)
        aviso = (f"o sinal se repete no trecho: valeu o menor atraso que alinha (outros: "
                 f"{', '.join(f'{x:g} ms' for x in outros[:3])})")
    return Alinhamento("correlacao", base + (k + fracao) / referencia.taxa, pico, n, aviso)


def _refinar(cruzado: np.ndarray, tamanho: int, variancia: np.ndarray, energia_r: float, k: int,
             no_pico: float) -> tuple[float, float]:
    """A fração de amostra (−1 a 1) do pico do coeficiente perto de ``k``, e o coeficiente lá.

    A correlação entre as amostras é a de banda limitada, exata: a soma de Fourier do espectro cruzado no instante
    fracionário (os sinais amostrados acima de Nyquist), avaliada em :data:`NOS_DO_REFINO` nós de Chebyshev em
    ``[k − 1, k + 1]`` e aproximada lá por um polinômio (a função é inteira: o erro fica muito abaixo do ruído). A
    energia do pedaço do traço muda devagar (na escala do período), e vai linear entre as amostras. A parábola nos
    três pontos do pico erra até ~0,15 amostra num sinal de banda larga, e o sinc truncado erra na escala do valor
    do pico, não na da curvatura dele."""
    from scipy.optimize import minimize_scalar

    if not 0 < k < len(variancia) - 1:
        return 0.0, no_pico                     # o pico na ponta da busca: sem vizinhos, fica a amostra
    f = np.arange(len(cruzado), dtype=np.float64)
    peso = np.full(len(cruzado), 2.0)
    peso[0] = 1.0
    if tamanho % 2 == 0:
        peso[-1] = 1.0
    base = peso * cruzado * np.exp(2j * np.pi * f * (k / tamanho)) / tamanho
    nos = np.cos(np.pi * (np.arange(NOS_DO_REFINO) + 0.5) / NOS_DO_REFINO)
    no_no = [float(np.real(np.dot(base, np.exp(2j * np.pi * f * (d / tamanho))))) for d in nos]
    polinomio = np.polynomial.Chebyshev.fit(nos, no_no, NOS_DO_REFINO - 1, domain=[-1.0, 1.0])
    v = variancia[k - 1:k + 2]

    def menos_rho(d: float) -> float:
        energia = v[1] + d * ((v[2] - v[1]) if d >= 0 else (v[1] - v[0]))
        return -polinomio(d) / math.sqrt(max(energia, 1e-300) * energia_r)

    feito = minimize_scalar(menos_rho, bounds=(-1.0, 1.0), method="bounded", options={"xatol": 1e-7})
    return float(feito.x), float(-feito.fun)


def nivel_e_amplitude(valores: np.ndarray) -> tuple[float, float]:
    """O zero do cruzamento e a amplitude (a metade da excursão). O zero é a média num número inteiro de períodos
    (entre o primeiro e o último cruzamento de subida achados com o meio da excursão): num atraso puro, o mesmo na
    referência e no traço. A média do trecho inteiro, que não tem um número inteiro de períodos, não é; o meio entre
    o máximo e o mínimo anda com o ruído dos picos (alguns milésimos da amplitude andam o zero por várias amostras
    num 60 Hz)."""
    alto, baixo = float(valores.max()), float(valores.min())
    nivel, amplitude = (alto + baixo) / 2, (alto - baixo) / 2
    if amplitude > 0.0:
        grossos = _subidas(valores - nivel, HISTERESE * amplitude, refinar=False)
        if len(grossos) >= 2:
            a, b = math.ceil(grossos[0]), math.floor(grossos[-1])
            if b - a >= MINIMO_DE_AMOSTRAS:
                nivel = float(valores[a:b].mean())
    return nivel, amplitude


def cruzamentos_de_subida(trecho: Trecho, histerese: float = HISTERESE) -> np.ndarray:
    """Os instantes (s, na vista) em que o sinal sobe pelo zero (:func:`nivel_e_amplitude`), com histerese: cada
    subida vai da última amostra abaixo de −h à primeira acima de +h (h = ``histerese`` × a amplitude), e o instante é
    o zero da reta ajustada (mínimos quadrados) às amostras em volta dele, com pesos que vão a zero nas pontas. A reta
    tira o ruído e a ondulação das harmônicas em volta do zero, que fariam o último zero das amostras pular de uma
    oscilação para outra; num atraso puro, a mesma subida dá a mesma reta, deslocada."""
    nivel, amplitude = nivel_e_amplitude(trecho.valores)
    if amplitude <= 0.0:
        return np.empty(0)
    return trecho.t0 + _subidas(trecho.valores - nivel, histerese * amplitude) / trecho.taxa


def _subidas(x: np.ndarray, h: float, refinar: bool = True) -> np.ndarray:
    """As subidas de ``x`` pelo zero, em amostras (fracionárias): ver :func:`cruzamentos_de_subida`."""
    estado = np.where(x > h, 1, np.where(x < -h, -1, 0))
    # O estado de cada amostra é o do último marcado antes dela (o "segurar" da histerese).
    ultimo = np.maximum.accumulate(np.where(estado != 0, np.arange(len(x)), -1))
    seguro = np.where(ultimo >= 0, estado[np.maximum(ultimo, 0)], 0)
    subidas = np.nonzero((seguro[:-1] == -1) & (seguro[1:] == 1))[0] + 1      # a primeira acima de +h
    baixas = np.nonzero(estado == -1)[0]
    grossos, larguras = [], []
    for u in subidas:
        d = int(baixas[np.searchsorted(baixas, u) - 1])                         # a última abaixo de −h
        n = np.arange(d - u, 1, dtype=np.float64)                              # em volta de u: a conta não perde
        inclinacao, corte = np.polyfit(n, x[d:u + 1], 1)                        # dígitos no índice grande
        if inclinacao > 0:
            grossos.append(u - corte / inclinacao)
            larguras.append(u - d)
    if not grossos or not refinar:
        return np.asarray(grossos, dtype=np.float64)
    # O refino: a reta com os pesos de Hann numa largura fixa (a mediana das subidas) em volta do cruzamento, de novo
    # no zero achado, três vezes. Os pesos vão a zero nas pontas: uma amostra a mais ou a menos não muda a reta (a
    # reta entre −h e +h pula quando a amostra da ponta troca).
    meia = max(2.0, float(np.median(larguras)))
    instantes = []
    for t in grossos:
        for _ in range(3):
            n = np.arange(math.ceil(t - meia), math.floor(t + meia) + 1)
            n = n[(n >= 0) & (n < len(x))]
            if len(n) < 3:
                break
            perto = n - t
            peso = np.cos(np.pi * perto / (2 * meia)) ** 2
            inclinacao, corte = np.polyfit(perto, x[n], 1, w=np.sqrt(peso))
            if inclinacao <= 0:
                break
            t = t - corte / inclinacao
        else:
            instantes.append(t)
    return np.asarray(instantes, dtype=np.float64)


def _por_zero(referencia: Trecho, traco: Trecho) -> Alinhamento:
    da_referencia = cruzamentos_de_subida(referencia)
    do_traco = cruzamentos_de_subida(traco)
    if len(da_referencia) == 0:
        raise AlinhamentoImpossivel("a referência não cruza o zero subindo no trecho")
    if len(do_traco) == 0:
        raise AlinhamentoImpossivel("o traço não cruza o zero subindo no trecho")
    j = np.clip(np.searchsorted(do_traco, da_referencia), 1, max(len(do_traco) - 1, 1))
    candidatos = np.stack([do_traco[np.maximum(j - 1, 0)], do_traco[np.minimum(j, len(do_traco) - 1)]])
    mais_perto = candidatos[np.argmin(np.abs(candidatos - da_referencia), axis=0), np.arange(len(da_referencia))]
    atrasos = mais_perto - da_referencia
    # Os casados de um mesmo atraso (um cruzamento perdido no ruído casaria com o vizinho): os perto da mediana.
    mediana = float(np.median(atrasos))
    periodo = float(np.median(np.diff(da_referencia))) if len(da_referencia) > 1 else math.inf
    bons = atrasos[np.abs(atrasos - mediana) <= 0.25 * periodo] if math.isfinite(periodo) else atrasos
    desvio = float(np.std(bons)) if len(bons) > 1 else 0.0
    aviso = ""
    if math.isfinite(periodo):
        aviso = (f"o sinal se repete a cada {periodo * 1e3:.4g} ms: valeu o cruzamento mais perto (o atraso fica "
                 "dentro de meio período)")
    return Alinhamento("zero", float(np.mean(bons)), desvio, len(referencia.valores), aviso, len(bons))
