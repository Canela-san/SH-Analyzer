"""A qualidade de energia e os eventos de um traço (F7.5 e F7.6; docs/gui-progress.md, 4h), sem Qt.

**Os índices** (:func:`indices`) seguem a IEC 61000-4-30 (classe A, onde dá): a janela de medição é de 10 ciclos numa
rede de 50 Hz e de 12 numa de 60 Hz (~200 ms), **sincronizada** com a fundamental (os cruzamentos por zero do motor,
``api.cruzamentos_da_fundamental``); em cada uma, a frequência (os ciclos ÷ o tempo deles), o RMS, a FFT retangular
dos ciclos inteiros (os harmônicos caem nos bins h·N), e daí o THD (até a 40ª, a IEC 61000-4-7), o fator K (o da
corrente: Σh²·I²ₕ ÷ ΣI²ₕ, até a 50ª), o fator de crista (o pico ÷ o RMS), o fator de forma (o RMS ÷ a média do módulo)
e o RMS das faixas de 2 a 9 kHz e de 9 a 150 kHz (os supraharmônicos, a soma da potência dos bins da faixa). **A
agregação** de 150/180 ciclos (~3 s) junta 15 janelas: o RMS das grandezas de RMS, a média das outras. **As
estatísticas** de cada índice: o mínimo, a média, o P95, o P99 e o máximo das janelas.

**Os eventos** (:func:`eventos`):

* **afundamentos, elevações e interrupções**: o RMS de um ciclo atualizado a cada meio ciclo (o U_rms(½) da norma)
  contra a tensão de referência (a dada, ou a mediana do trecho): abaixo de 90 % é um afundamento, abaixo de 5 % uma
  interrupção, acima de 110 % uma elevação; o fim, quando volta para dentro com a histerese de 2 %;
* **os picos de supraharmônicos**: as janelas de 200 ms em que o RMS de 2 a 150 kHz passa de 10× (20 dB) a mediana;
* **a saturação**: as sequências de amostras no menor ou no maior código do ADC (só no traço sem cadeia);
* **as descontinuidades**: os saltos de uma amostra para a outra maiores que 8 desvios robustos da diferença (o
  desvio pela mediana do módulo, que um salto não puxa) e que não seguem a forma de onda;
* **o cabeçalho**: os buffers sobrescritos e as amostras atrasadas que o ``ler_adc`` contou (sem o instante).

A captura inteira não vai para a memória: o trecho é lido em pedaços de :data:`PEDACO` amostras, com a sobreposição de
alguns ciclos (os cruzamentos de um pedaço não dependem da borda dele).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import supraharmonicos.api as api

from .espectros import LIMITE_DA_CADEIA, AguardandoMaterializacao, TrechoDoTraco
from .materializacao import leitor_do_canal

PEDACO = 1 << 21
"""As amostras de cada pedaço lido (~10 s a 200 kS/s)."""
SOBRA_EM_CICLOS = 3
PEDACO_MINIMO_S = (2 * 12 + 2 * SOBRA_EM_CICLOS) / 45.0
"""O menor pedaço: duas janelas e as sobras dos dois lados na menor fundamental (45 Hz)."""
ORDEM_DO_THD = 40
ORDEM_DO_FATOR_K = 50
JANELAS_DA_AGREGACAO = 15
FAIXAS_SUPRA = ((2_000.0, 9_000.0), (9_000.0, 150_000.0))
LIMIAR_DO_AFUNDAMENTO = 0.90
LIMIAR_DA_INTERRUPCAO = 0.05
LIMIAR_DA_ELEVACAO = 1.10
HISTERESE = 0.02
FATOR_DO_PICO_SUPRA = 10.0
DESVIOS_DO_SALTO = 8.0
INDICES = ("frequencia", "rms", "thd", "fator_k", "crista", "forma", "supra_2_9k", "supra_9_150k")
NOMES_DOS_INDICES = {"frequencia": "Frequência", "rms": "RMS", "thd": "THD", "fator_k": "Fator K",
                     "crista": "Fator de crista", "forma": "Fator de forma", "supra_2_9k": "RMS de 2 a 9 kHz",
                     "supra_9_150k": "RMS de 9 a 150 kHz"}
INDICES_DE_RMS = ("rms", "supra_2_9k", "supra_9_150k")


def ler(trecho: TrechoDoTraco, a: int, b: int) -> np.ndarray:
    """Os valores do traço nas amostras ``[a, b)`` do canal (``float64``, com o ganho e o offset)."""
    canal = trecho.captura.canal(trecho.numero)
    if trecho.cadeia.vazia:
        return np.asarray(canal.amostras[a:b], dtype=np.float64) * (canal.escala * trecho.ganho) + (
            canal.deslocamento * trecho.ganho + trecho.offset)
    if trecho.n_amostras <= LIMITE_DA_CADEIA:
        valores = trecho.cadeia.previa(leitor_do_canal(trecho.captura, trecho.numero), len(canal.amostras), a, b,
                                       trecho.contexto).valores
        return valores * trecho.ganho + trecho.offset
    if trecho.materializada is None:
        raise AguardandoMaterializacao()
    return np.asarray(trecho.materializada[a:b], dtype=np.float64) * trecho.ganho + trecho.offset


# ------------------------------------------------------------------ os índices (F7.6)


@dataclass(frozen=True)
class EstatisticaDoIndice:
    minimo: float
    media: float
    p95: float
    p99: float
    maximo: float


@dataclass(frozen=True)
class IndicesDeQualidade:
    """Os índices de cada janela de 10/12 ciclos (``inicios_s``: o começo de cada uma, no tempo do canal, em s, a
    partir do começo da captura) e os agregados de 150/180 ciclos; ``ciclos_por_janela``: 10 ou 12."""

    inicios_s: np.ndarray
    valores: dict[str, np.ndarray]
    agregados_s: np.ndarray
    agregados: dict[str, np.ndarray]
    ciclos_por_janela: int
    estatisticas: dict[str, EstatisticaDoIndice] = field(default_factory=dict)
    trechos_sem_fundamental: int = 0

    @property
    def n_janelas(self) -> int:
        return len(self.inicios_s)


def _estatistica(x: np.ndarray) -> EstatisticaDoIndice:
    x = x[np.isfinite(x)]
    if not len(x):
        return EstatisticaDoIndice(*(math.nan,) * 5)
    return EstatisticaDoIndice(float(np.min(x)), float(np.mean(x)), float(np.percentile(x, 95)),
                               float(np.percentile(x, 99)), float(np.max(x)))


def _indices_da_janela(x: np.ndarray, n_ciclos: int, duracao_s: float, taxa_hz: float) -> dict[str, float]:
    n = len(x)
    rms = math.sqrt(float(np.mean(x * x)))
    espectro = np.fft.rfft(x) / n
    potencia = np.abs(espectro) ** 2 * 2.0                     # o RMS² de cada componente (sem o DC)
    potencia[0] = abs(espectro[0]) ** 2
    harmonicos = np.array([potencia[h * n_ciclos] if h * n_ciclos < len(potencia) else 0.0
                           for h in range(1, ORDEM_DO_FATOR_K + 1)])
    h1 = harmonicos[0]
    thd = math.sqrt(float(np.sum(harmonicos[1:ORDEM_DO_THD]))) / math.sqrt(h1) if h1 > 0 else math.nan
    ordens = np.arange(1, ORDEM_DO_FATOR_K + 1)
    fator_k = float(np.sum(ordens ** 2 * harmonicos) / np.sum(harmonicos)) if np.sum(harmonicos) > 0 else math.nan
    media_abs = float(np.mean(np.abs(x)))
    resolucao = 1.0 / duracao_s
    faixas = []
    for f0, f1 in FAIXAS_SUPRA:
        i0, i1 = math.ceil(f0 / resolucao), math.floor(min(f1, taxa_hz / 2) / resolucao)
        faixas.append(math.sqrt(float(np.sum(potencia[i0:i1 + 1]))) if i1 >= i0 else math.nan)
    return {"frequencia": n_ciclos / duracao_s, "rms": rms, "thd": thd, "fator_k": fator_k,
            "crista": float(np.max(np.abs(x))) / rms if rms > 0 else math.nan,
            "forma": rms / media_abs if media_abs > 0 else math.nan,
            "supra_2_9k": faixas[0], "supra_9_150k": faixas[1]}


def _cruzamentos(x: np.ndarray, taxa_hz: float) -> tuple[np.ndarray, float]:
    return api.cruzamentos_da_fundamental(x, taxa_hz, api.FREQ_MIN_FUNDAMENTAL, api.FREQ_MAX_FUNDAMENTAL)


def indices(trecho: TrechoDoTraco, *, progresso: Callable[[float], None] | None = None,
            cancelado: Callable[[], bool] | None = None, pedaco: int | None = None) -> IndicesDeQualidade:
    """Os índices de qualidade do trecho (ver o começo do módulo). Levanta ``api.ErroSHAN`` sem a fundamental.

    Os pedaços: cada um começa uns ciclos antes do cruzamento em que a próxima janela começa (``alvo``), e as janelas
    seguem do cruzamento dele mais perto do alvo; as janelas ficam contíguas, como na norma."""
    taxa = trecho.captura.canal(trecho.numero).taxa_hz
    pedaco = max(pedaco or PEDACO, int(math.ceil(PEDACO_MINIMO_S * taxa)))
    a, fim = trecho.inicio, trecho.fim
    if fim - a < 4:
        raise api.ErroSHAN("o trecho é curto demais para os índices de qualidade")
    inicios, linhas = [], []
    sem_fundamental = 0
    n_ciclos = None
    pos, alvo, continua = a, float(a), False
    while pos < fim:
        if cancelado is not None and cancelado():
            raise api.Cancelado()
        b = min(fim, pos + pedaco)
        x = ler(trecho, pos, b)
        try:
            cruz, f1 = _cruzamentos(x, taxa)
        except api.ErroSHAN:
            sem_fundamental += 1
            pos, alvo, continua = b, float(b), False
            continue
        if n_ciclos is None:
            n_ciclos = 12 if f1 > 55.0 else 10
        if continua:
            k = int(np.argmin(np.abs(cruz - (alvo - pos))))
        else:
            k = int(np.searchsorted(cruz, alvo - pos))
        # O fim do pedaço tem o transitório do filtro dos cruzamentos (sosfiltfilt): as janelas param umas sobras
        # antes dele, e o pedaço seguinte as refaz desde o alvo.
        sobra = int(SOBRA_EM_CICLOS * taxa / max(f1, 1.0))
        limite = len(x) if b >= fim else len(x) - sobra
        usados = None
        while k + n_ciclos < len(cruz) and cruz[k + n_ciclos] <= limite:
            i0, i1 = int(round(cruz[k])), int(round(cruz[k + n_ciclos]))
            duracao = (cruz[k + n_ciclos] - cruz[k]) / taxa
            linhas.append(_indices_da_janela(x[i0:i1], n_ciclos, duracao, taxa))
            inicios.append((pos + cruz[k]) / taxa)
            usados = k + n_ciclos
            k += n_ciclos
        if b >= fim:
            break
        if usados is None:
            pos, alvo, continua = b, float(b), False
            continue
        alvo = pos + float(cruz[usados])
        pos, continua = max(pos + 1, int(math.floor(alvo)) - sobra), True
        if progresso is not None:
            progresso((pos - a) / (fim - a))
    if not linhas:
        raise api.ErroSHAN("o trecho não tem uma fundamental de 45 a 65 Hz: os índices de qualidade precisam dela")
    return _montar(np.array(inicios), linhas, n_ciclos, sem_fundamental)


def _montar(inicios: np.ndarray, linhas: list[dict], n_ciclos: int, sem_fundamental: int) -> IndicesDeQualidade:
    valores = {nome: np.array([linha[nome] for linha in linhas]) for nome in INDICES}
    n_ag = len(inicios) // JANELAS_DA_AGREGACAO
    agregados = {}
    for nome, v in valores.items():
        blocos = v[:n_ag * JANELAS_DA_AGREGACAO].reshape(n_ag, JANELAS_DA_AGREGACAO) if n_ag else np.zeros((0, 1))
        agregados[nome] = (np.sqrt(np.mean(blocos ** 2, axis=1)) if nome in INDICES_DE_RMS
                           else np.mean(blocos, axis=1))
    agregados_s = inicios[:n_ag * JANELAS_DA_AGREGACAO:JANELAS_DA_AGREGACAO] if n_ag else np.zeros(0)
    estatisticas = {nome: _estatistica(v) for nome, v in valores.items()}
    return IndicesDeQualidade(inicios, valores, agregados_s, agregados, n_ciclos, estatisticas, sem_fundamental)


# ------------------------------------------------------------------ os eventos (F7.5)


TIPOS_DE_EVENTO = {"afundamento": "Afundamento", "elevacao": "Elevação", "interrupcao": "Interrupção",
                   "supraharmonicos": "Pico de supraharmônicos", "saturacao": "Saturação",
                   "descontinuidade": "Descontinuidade", "cabecalho": "Registro do ler_adc"}


@dataclass(frozen=True)
class Evento:
    """Um evento: o tipo (:data:`TIPOS_DE_EVENTO`), o começo e a duração (s, no tempo do canal desde o começo da
    captura; NaN no do cabeçalho, sem instante), o valor que o caracteriza (a tensão residual de um afundamento, a de
    pico de uma elevação, o RMS da faixa, o salto) e o texto."""

    tipo: str
    inicio_s: float
    duracao_s: float
    valor: float
    detalhe: str = ""


@dataclass(frozen=True)
class OpcoesDosEventos:
    referencia: float | None = None       # a tensão de referência (None: a mediana do RMS de ½ ciclo do trecho)
    tensao: bool = True                    # procurar afundamentos, elevações e interrupções (o traço é uma tensão)


def _rms_de_meio_ciclo(x: np.ndarray, cruz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """O RMS de um ciclo, atualizado a cada meio ciclo (os meios ciclos entre os cruzamentos subindo): os instantes
    (o fim de cada janela, em amostras de ``x``) e os valores."""
    meios = np.sort(np.concatenate([cruz, (cruz[:-1] + cruz[1:]) / 2]))
    quadrados = np.concatenate([[0.0], np.cumsum(x * x)])
    idx = np.clip(np.round(meios).astype(np.int64), 0, len(x))
    fins, valores = [], []
    for k in range(2, len(idx)):
        a, b = idx[k - 2], idx[k]
        if b > a:
            fins.append(meios[k])
            valores.append(math.sqrt((quadrados[b] - quadrados[a]) / (b - a)))
    return np.array(fins), np.array(valores)


def _eventos_de_tensao(instantes_s: np.ndarray, rms: np.ndarray, referencia: float) -> list[Evento]:
    eventos = []
    estado, inicio, extremo = None, 0.0, 0.0
    for t, v in zip(instantes_s, rms):
        r = v / referencia
        if estado is None:
            if r < LIMIAR_DA_INTERRUPCAO:
                estado, inicio, extremo = "interrupcao", t, v
            elif r < LIMIAR_DO_AFUNDAMENTO:
                estado, inicio, extremo = "afundamento", t, v
            elif r > LIMIAR_DA_ELEVACAO:
                estado, inicio, extremo = "elevacao", t, v
            continue
        if estado == "afundamento" and r < LIMIAR_DA_INTERRUPCAO:
            estado = "interrupcao"
        if estado in ("afundamento", "interrupcao"):
            extremo = min(extremo, v)
            terminou = r >= LIMIAR_DO_AFUNDAMENTO + HISTERESE
        else:
            extremo = max(extremo, v)
            terminou = r <= LIMIAR_DA_ELEVACAO - HISTERESE
        if terminou:
            eventos.append(Evento(estado, inicio, t - inicio, extremo,
                                  f"{100 * extremo / referencia:.1f} % da referência"))
            estado = None
    if estado is not None:
        eventos.append(Evento(estado, inicio, float(instantes_s[-1]) - inicio, extremo,
                              f"{100 * extremo / referencia:.1f} % da referência (até o fim do trecho)"))
    return eventos


def _sequencias(mascara: np.ndarray) -> list[tuple[int, int]]:
    """As sequências de verdadeiros: ``(início, fim)`` em amostras."""
    if not mascara.any():
        return []
    d = np.diff(np.concatenate([[0], mascara.astype(np.int8), [0]]))
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]))


def eventos(trecho: TrechoDoTraco, opcoes: OpcoesDosEventos = OpcoesDosEventos(), *,
            indices_prontos: IndicesDeQualidade | None = None, progresso=None, cancelado=None,
            pedaco: int | None = None) -> list[Evento]:
    """Os eventos do trecho, em ordem de tempo (ver o começo do módulo)."""
    pedaco = pedaco or PEDACO
    canal = trecho.captura.canal(trecho.numero)
    taxa = canal.taxa_hz
    a, fim = trecho.inicio, trecho.fim
    lista: list[Evento] = []
    instantes, rms = [], []
    saltos = []
    codigos = None if not trecho.cadeia.vazia else canal.amostras
    baixo = alto = None
    if codigos is not None and np.issubdtype(codigos.dtype, np.integer):
        info = np.iinfo(codigos.dtype)
        baixo, alto = info.min, info.max
    ultimo_fim = None
    for pos in range(a, fim, pedaco):
        if cancelado is not None and cancelado():
            raise api.Cancelado()
        b = min(fim, pos + pedaco)
        sobra = int(SOBRA_EM_CICLOS * taxa / 45.0)
        p0 = max(a, pos - sobra)
        x = ler(trecho, p0, b)
        if opcoes.tensao:
            try:
                cruz, _f1 = _cruzamentos(x, taxa)
                fins, valores = _rms_de_meio_ciclo(x, cruz)
                novos = (p0 + fins) / taxa
                manter = novos > (ultimo_fim if ultimo_fim is not None else -math.inf)
                instantes.extend(novos[manter])
                rms.extend(valores[manter])
                if len(novos):
                    ultimo_fim = float(novos[-1])
            except api.ErroSHAN:
                pass
        if baixo is not None:
            parte = np.asarray(codigos[pos:b])
            for i0, i1 in _sequencias((parte == baixo) | (parte == alto)):
                lista.append(Evento("saturacao", (pos + i0) / taxa, (i1 - i0) / taxa,
                                    float(i1 - i0), f"{i1 - i0} amostra(s) no fundo de escala"))
        d = np.diff(x[pos - p0 - 1 if pos > a else 0:])
        if len(d) > 2:
            d2 = np.diff(d)                                        # o salto que não segue a forma de onda
            desvio = 1.4826 * float(np.median(np.abs(d2 - np.median(d2)))) or float(np.std(d2)) or 1e-30
            for j in np.nonzero(np.abs(d2) > DESVIOS_DO_SALTO * 3 * desvio)[0]:
                saltos.append(((pos if pos > a else p0) + j + 1, float(d[j + 1] if j + 1 < len(d) else d[j])))
        if progresso is not None:
            progresso((b - a) / (fim - a))
    if opcoes.tensao and len(rms):
        rms_arr, t_arr = np.array(rms), np.array(instantes)
        referencia = opcoes.referencia or float(np.median(rms_arr))
        if referencia > 0:
            lista.extend(_eventos_de_tensao(t_arr, rms_arr, referencia))
    # os saltos vizinhos (o mesmo degrau visto por duas diferenças) viram um só
    ultimo = -10
    for amostra, salto in sorted(saltos):
        if amostra - ultimo > 2:
            lista.append(Evento("descontinuidade", amostra / taxa, 0.0, salto, "um salto fora da forma de onda"))
        ultimo = amostra
    q = indices_prontos
    if q is not None and q.n_janelas:
        for nome in ("supra_9_150k", "supra_2_9k"):
            v = q.valores[nome]
            mediana = float(np.nanmedian(v)) if np.isfinite(v).any() else math.nan
            if not mediana > 0:
                continue
            for k in np.nonzero(v > FATOR_DO_PICO_SUPRA * mediana)[0]:
                lista.append(Evento("supraharmonicos", float(q.inicios_s[k]), q.ciclos_por_janela / q.valores[
                    "frequencia"][k], float(v[k]), f"{NOMES_DOS_INDICES[nome]}: {v[k] / mediana:.1f}× a mediana"))
    cab = trecho.captura.cabecalho
    for campo, texto in (("buffers_sobrescritos", "buffer(s) sobrescrito(s): amostras perdidas"),
                         ("amostras_atrasadas", "amostra(s) atrasada(s): a PRU não acompanhou a taxa")):
        n = getattr(cab, campo, None) if cab is not None else None
        if n:
            lista.append(Evento("cabecalho", math.nan, math.nan, float(n), f"{n} {texto}"))
    return sorted(lista, key=lambda e: (math.isnan(e.inicio_s), e.inicio_s))


# ------------------------------------------------------------------ a transferência (F7.7)


@dataclass(frozen=True)
class Transferencia:
    """A função de transferência H₁ = P_xy / P_xx (a saída ``y`` sobre a entrada ``x``), a coerência, a densidade
    espectral cruzada e as das duas, pelo Welch (Hann, 50 % de sobreposição), com ``medias`` segmentos."""

    frequencias: np.ndarray
    h: np.ndarray
    coerencia: np.ndarray
    pxy: np.ndarray
    pxx: np.ndarray
    pyy: np.ndarray
    medias: int

    @property
    def magnitude_db(self) -> np.ndarray:
        with np.errstate(divide="ignore"):
            return 20 * np.log10(np.abs(self.h))

    @property
    def fase_graus(self) -> np.ndarray:
        return np.degrees(np.angle(self.h))


def transferencia(x: np.ndarray, y: np.ndarray, taxa_hz: float, resolucao_hz: float) -> Transferencia:
    """H₁, a coerência e as densidades de ``x`` (a entrada) e ``y`` (a saída), com segmentos de ``taxa/resolução``
    amostras. Levanta ``api.ErroSHAN`` com menos de dois segmentos."""
    from scipy.signal import csd, welch

    if len(x) != len(y):
        raise api.ErroSHAN(f"a entrada e a saída têm tamanhos diferentes ({len(x)} e {len(y)} amostras)")
    n = int(round(taxa_hz / resolucao_hz))
    if n < 8:
        raise api.ErroSHAN("a resolução pedida é grossa demais para a taxa")
    if len(x) < 2 * n:
        raise api.ErroSHAN(f"o trecho tem {len(x)} amostras, e a resolução de {resolucao_hz:g} Hz pede pelo menos "
                           f"{2 * n} (dois segmentos)")
    opcoes = dict(fs=taxa_hz, window="hann", nperseg=n, noverlap=n // 2, detrend="constant")
    f, pxx = welch(x, **opcoes)
    _, pyy = welch(y, **opcoes)
    _, pxy = csd(x, y, **opcoes)
    with np.errstate(divide="ignore", invalid="ignore"):
        h = pxy / pxx
        coerencia = np.abs(pxy) ** 2 / (pxx * pyy)
    medias = 1 + (len(x) - n) // (n - n // 2)
    return Transferencia(f, h, np.clip(np.nan_to_num(coerencia), 0, 1), pxy, pxx, pyy, medias)


def intervalo_de_confianca_db(medias: int, confianca: float = 0.95) -> tuple[float, float]:
    """O intervalo de confiança de uma densidade do Welch, em dB em volta da estimativa: com ν graus de liberdade
    (Hann com 50 % de sobreposição: ν ≈ 2K / (1 + 2·0,167²), Welch 1967), o verdadeiro fica entre
    ν·P/χ²(ν, 1−α/2) e ν·P/χ²(ν, α/2)."""
    from scipy.stats import chi2

    nu = 2 * medias / (1 + 2 * 0.167 ** 2)
    alfa = 1 - confianca
    return (10 * math.log10(nu / chi2.ppf(1 - alfa / 2, nu)), 10 * math.log10(nu / chi2.ppf(alfa / 2, nu)))
