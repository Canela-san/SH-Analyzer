"""A razão entre dois canais capturados JUNTOS: a mesma onda periódica nos dois, ao mesmo tempo, e H_a(f) / H_b(f)
em cada harmônico, com a fase absoluta.

Por que dois canais ao mesmo tempo
    Numa captura de um canal só, a fase de um harmônico só diz em que instante a captura começou; o método das
    quadradas (``fase_quadrada``) contorna isso com ``arg Xₙ − n·arg X₁``, e paga com duas hipóteses: a forma da
    entrada (a quadrada ideal, ou a medida no osciloscópio) e a fase mínima para ancorar o atraso. Com dois canais
    amostrados na mesma grade, o instante é o mesmo nos dois: ``X_a(n f₁) / X_b(n f₁)`` é H_a / H_b, qualquer que seja
    a forma da entrada (a corrente que o gerador limita, a borda arredondada, o duty), sem modelo e sem fase mínima.
    É o método de um analisador de rede com canal de referência. Na sonda de corrente: o TC no canal a, a tensão num
    resistor do mesmo laço, pelo divisor, no canal b. Para a potência entre tensão e corrente, é tudo o que a fase
    precisa: a fase do perfil de tensão se cancela em V·I*.

O atraso entre os canais
    O ADS8688 converte os canais da varredura um depois do outro, em ordem crescente, 1/(taxa total) entre eles: o
    canal na posição p da lista é amostrado p/(taxa total) depois do primeiro. Um atraso τ_c soma 2π f τ_c à fase
    medida, então ``X_a / X_b = H_a / H_b · e^{j2πf(τ_a − τ_b)}``: ``medir_razao`` desconta ``atraso_s = τ_a − τ_b``.
    O que o filtro de cada canal atrasa a mais (no T6b, 46 ns entre os canais 1 e 2) é resposta, e fica na razão.

A média coerente
    Como em ``medir_quadrada``: a captura em blocos, os harmônicos de cada bloco pela transformada chirp-z, girados
    pela fase da fundamental do canal b no bloco (o mesmo giro nos dois canais: a razão não muda, e as médias ficam
    coerentes). A razão das médias é a medida; a dispersão das razões bloco a bloco, a incerteza.

Acima da Nyquist de dois canais: capturas separadas
    Com dois canais, cada um vai à metade da taxa (até ~95 kHz a 400 kS/s). Um canal sozinho vai ao dobro, mas duas
    capturas separadas não têm instante em comum. ``medir_razao_separada`` usa o que não depende dele: em cada captura,
    cada harmônico girado por n vezes a fase da própria fundamental. A razão disso entre as duas capturas da mesma
    quadrada (o gerador parado nela) é ``(H_a/H_b)(n f₁) · e^{−jnθ₁}``, com θ₁ = arg(H_a/H_b)(f₁), e o módulo exato,
    se a amplitude não mudou entre as duas. ``ancorar_na_dupla`` devolve o que falta pela captura de dois canais da
    mesma quadrada: θ₁ (cada harmônico ganha n·θ₁) e o módulo da fundamental (o que corrige uma mudança de amplitude
    do gerador entre as duas capturas separadas). Num canal sozinho não há diafonia do outro.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from .erros import ErroSHAN
from .fase_quadrada import (
    AMOSTRAS_POR_BLOCO,
    CONTAMINACAO_MAX_DB,
    F0_PADRAO_HZ,
    FRACAO_DA_NYQUIST,
    Q_PADRAO,
    SIGMA_FASE_MINIMO,
    SIGMA_LN_MINIMO,
    SNR_MINIMO_DB,
    TOLERANCIA_F1_ENTRADA,
    _harmonicos_do_bloco,
    _janela_bh,
    comprimento_do_bloco,
    contaminacao_por_aliasing,
    estimar_f1,
    h_segunda_ordem,
)

MODELO_PADRAO = (F0_PADRAO_HZ, Q_PADRAO, math.inf)


@dataclass
class RazaoQuadrada:
    """Os harmônicos ímpares de uma captura de dois canais, como H_a / H_b (complexo, sem o atraso entre os canais)."""

    f1_hz: float
    fs_hz: float                    # por canal
    atraso_s: float                 # τ_a − τ_b, descontado da razão
    blocos: int
    n: np.ndarray
    freq_hz: np.ndarray
    razao: np.ndarray               # H_a / H_b em cada harmônico (complexo), na unidade dos sinais (LSB / LSB na CLI)
    sigma_ln: np.ndarray            # incerteza de ln|razão|
    sigma_fase: np.ndarray          # incerteza de arg(razão), em rad
    amplitude_a: np.ndarray         # amplitude de pico de cada harmônico em cada canal
    amplitude_b: np.ndarray
    snr_a_db: np.ndarray
    snr_b_db: np.ndarray
    contaminacao_db: np.ndarray     # o maior aliasing previsto dos dois canais, relativo ao harmônico
    usado: np.ndarray
    motivo: list[str]
    diafonia: np.ndarray | None = None      # o vazamento do canal b no a, subtraído (complexo), se foi
    fase_relativa: bool = False             # capturas separadas ainda não ancoradas: a fase é a menos de n·θ₁

    def __len__(self) -> int:
        return len(self.n)


@dataclass
class PontosCurva:
    """Uma curva de resposta em pontos (ln|H|, ψ e as σ): o que ``combinar_em_grade`` lê."""

    freq_hz: np.ndarray
    ln_ganho: np.ndarray
    sigma_ln: np.ndarray
    fase_rad: np.ndarray
    sigma_fase: np.ndarray


def medir_razao(a: np.ndarray, b: np.ndarray, fs: float, f_dica: float | None = None, atraso_s: float = 0.0,
                freq_max_hz: float | None = None, amostras_por_bloco: int = AMOSTRAS_POR_BLOCO, piso_a: float = 0.0,
                piso_b: float = 0.0, modelo_a: tuple[float, float, float] = MODELO_PADRAO,
                modelo_b: tuple[float, float, float] = MODELO_PADRAO, prever_aliasing: bool = True) -> RazaoQuadrada:
    """H_a / H_b em cada harmônico ímpar de uma onda periódica capturada nos dois canais ao mesmo tempo (``a`` e
    ``b``, na mesma grade, com o canal a amostrado ``atraso_s`` depois do b). f₁ sai do canal b (a referência, o de
    mais sinal). ``piso_a``/``piso_b``: o piso sistemático por harmônico (o INL), na unidade de cada sinal.
    ``modelo_a``/``modelo_b``: (f0, Q, polo) de cada cadeia, só para prever o aliasing. Todo harmônico é um ponto
    absoluto, a fundamental inclusive: não há costura a fazer entre capturas de f₁ diferentes."""
    n_amostras = min(len(a), len(b))
    xa = np.asarray(a[:n_amostras], dtype=np.float64)
    xb = np.asarray(b[:n_amostras], dtype=np.float64)
    xa = xa - float(np.mean(xa))
    xb = xb - float(np.mean(xb))
    f1 = estimar_f1(xb[: 1 << 22], fs, f_dica)
    limite = FRACAO_DA_NYQUIST * fs / 2 if freq_max_hz is None else min(freq_max_hz, FRACAO_DA_NYQUIST * fs / 2)
    if f1 > limite:
        raise ErroSHAN(f"f₁ = {f1:.1f} Hz passa do limite de {limite:.0f} Hz (95 % da Nyquist).")
    n = np.arange(1, int(limite / f1) + 1, 2)
    comprimento = comprimento_do_bloco(n_amostras, fs, f1, amostras_por_bloco)
    n_blocos = n_amostras // comprimento
    w = _janela_bh(comprimento)
    soma = float(np.sum(w))
    za = np.empty((n_blocos, len(n)), dtype=complex)
    zb = np.empty((n_blocos, len(n)), dtype=complex)
    par_b = np.empty(n_blocos, dtype=complex)
    for k in range(n_blocos):
        trecho = slice(k * comprimento, (k + 1) * comprimento)
        ia, _ = _harmonicos_do_bloco((xa[trecho] - xa[trecho].mean()) * w, fs, f1, len(n), 1, soma)
        ib, pb = _harmonicos_do_bloco((xb[trecho] - xb[trecho].mean()) * w, fs, f1, len(n), 1, soma)
        giro = np.exp(-1j * np.angle(ib[0]))
        za[k] = ia * giro ** n
        zb[k] = ib * giro ** n
        par_b[k] = pb[0] * giro ** 2
    zam, zbm = za.mean(axis=0), zb.mean(axis=0)
    if abs(zbm[0]) == 0:
        raise ErroSHAN("o canal de referência não tem a fundamental: não há onda periódica nele.")
    razao = zam / np.where(np.abs(zbm) > 0, zbm, 1e-300)
    # a dispersão das razões bloco a bloco: o ruído dos dois canais, com a correlação que houver entre eles
    q = za / np.where(np.abs(zb) > 0, zb, 1e-300)
    rel = np.std(q, axis=0, ddof=1) / math.sqrt(2 * n_blocos) / np.maximum(np.abs(razao), 1e-300)
    rel_a = np.std(za, axis=0, ddof=1) / math.sqrt(2 * n_blocos) / np.maximum(np.abs(zam), 1e-300)
    rel_b = np.std(zb, axis=0, ddof=1) / math.sqrt(2 * n_blocos) / np.maximum(np.abs(zbm), 1e-300)
    snr_a = -20 * np.log10(np.maximum(rel_a * math.sqrt(2), 1e-15))
    snr_b = -20 * np.log10(np.maximum(rel_b * math.sqrt(2), 1e-15))
    sistematico = np.hypot(piso_a / np.maximum(np.abs(zam), 1e-300), piso_b / np.maximum(np.abs(zbm), 1e-300))
    sigma_ln = np.sqrt(rel ** 2 + sistematico ** 2 + SIGMA_LN_MINIMO ** 2)
    sigma_fase = np.sqrt(rel ** 2 + sistematico ** 2 + SIGMA_FASE_MINIMO ** 2)
    razao = razao * np.exp(-2j * np.pi * n * f1 * atraso_s)

    if prever_aliasing:
        resolucao = 4.0 * fs / comprimento
        eps = _desvio_do_duty(par_b.mean(), zbm[0], f1, modelo_b)
        contam = np.maximum(contaminacao_por_aliasing(f1, fs, n, eps, *modelo_a[:2], resolucao, polo=modelo_a[2]),
                            contaminacao_por_aliasing(f1, fs, n, eps, *modelo_b[:2], resolucao, polo=modelo_b[2]))
    else:
        contam = np.full(len(n), -np.inf)
    motivos = _motivos(contam, snr_a, snr_b)
    return RazaoQuadrada(f1, fs, atraso_s, n_blocos, n, n * f1, razao, sigma_ln, sigma_fase, np.abs(zam), np.abs(zbm),
                         snr_a, snr_b, contam, np.array([m == "" for m in motivos]), motivos)


def _desvio_do_duty(segundo: complex, fundamental: complex, f1: float, modelo: tuple[float, float, float]) -> float:
    """O desvio do duty pelo 2º harmônico: |c₂|/|c₁| = |sin(2πε)| / (2 cos(πε)), com o filtro do modelo da cadeia."""
    f0, q, polo = modelo
    r2 = abs(segundo) / abs(fundamental) / abs(h_segunda_ordem(2 * f1, f0, q, polo) / h_segunda_ordem(f1, f0, q, polo))
    return float(np.arcsin(min(1.0, 2 * r2)) / (2 * np.pi))


def _motivos(contam: np.ndarray, snr_a: np.ndarray, snr_b: np.ndarray) -> list[str]:
    motivos = []
    for i in range(len(contam)):
        if contam[i] > CONTAMINACAO_MAX_DB:
            motivos.append(f"aliasing a {contam[i]:.0f} dB")
        elif snr_b[i] < SNR_MINIMO_DB:
            motivos.append(f"SNR de {snr_b[i]:.0f} dB na referência")
        elif snr_a[i] < SNR_MINIMO_DB:
            motivos.append(f"SNR de {snr_a[i]:.0f} dB")
        else:
            motivos.append("")
    return motivos


@dataclass
class _Normalizados:
    media: np.ndarray               # média dos blocos de Xₙ·e^{−jn·arg X₁} (a fundamental real e positiva)
    rel: np.ndarray                 # incerteza relativa de cada um
    segundo: complex                # o 2º harmônico, girado do mesmo jeito (o duty)
    blocos: int
    comprimento: int


def _normalizados(x: np.ndarray, fs: float, f1: float, m: int, amostras_por_bloco: int) -> _Normalizados:
    """Os ``m`` primeiros harmônicos ímpares de uma captura de um canal, cada bloco girado por n vezes a fase da
    própria fundamental: o que não depende do instante em que a captura começou."""
    x = np.asarray(x, dtype=np.float64)
    x = x - float(np.mean(x))
    n = np.arange(1, 2 * m, 2)
    comprimento = comprimento_do_bloco(len(x), fs, f1, amostras_por_bloco)
    n_blocos = len(x) // comprimento
    w = _janela_bh(comprimento)
    soma = float(np.sum(w))
    z = np.empty((n_blocos, m), dtype=complex)
    par = np.empty(n_blocos, dtype=complex)
    for k in range(n_blocos):
        trecho = x[k * comprimento:(k + 1) * comprimento]
        h, p = _harmonicos_do_bloco((trecho - trecho.mean()) * w, fs, f1, m, 1, soma)
        giro = np.exp(-1j * np.angle(h[0]))
        z[k] = h * giro ** n
        par[k] = p[0] * giro ** 2
    media = z.mean(axis=0)
    if abs(media[0]) == 0:
        raise ErroSHAN("a captura não tem a fundamental: não há onda periódica nela.")
    rel = np.std(z, axis=0, ddof=1) / math.sqrt(2 * n_blocos) / np.maximum(np.abs(media), 1e-300)
    return _Normalizados(media, rel, complex(par.mean()), n_blocos, comprimento)


def medir_razao_separada(a: np.ndarray, b: np.ndarray, fs: float, f_dica: float | None = None,
                         freq_max_hz: float | None = None, amostras_por_bloco: int = AMOSTRAS_POR_BLOCO,
                         piso_a: float = 0.0, piso_b: float = 0.0, modelo_a: tuple[float, float, float] = MODELO_PADRAO,
                         modelo_b: tuple[float, float, float] = MODELO_PADRAO,
                         prever_aliasing: bool = True) -> RazaoQuadrada:
    """H_a / H_b em cada harmônico ímpar de uma quadrada capturada em DUAS capturas de um canal só (a no canal medido,
    b no de referência, as duas à taxa ``fs``, o gerador parado na mesma quadrada). Cada harmônico vem girado por n
    vezes a fase da fundamental da própria captura: a razão sai com a fase a menos de n·θ₁ (θ₁ = arg(H_a/H_b)(f₁)) e a
    fundamental real, com ``fase_relativa``. ``ancorar_na_dupla`` completa a medida. f₁ sai de cada captura; elas
    precisam concordar (a mesma quadrada)."""
    xa = np.asarray(a, dtype=np.float64)
    xb = np.asarray(b, dtype=np.float64)
    f1 = estimar_f1(xb[: 1 << 22] - float(np.mean(xb[: 1 << 22])), fs, f_dica)
    f1a = estimar_f1(xa[: 1 << 22] - float(np.mean(xa[: 1 << 22])), fs, f1)
    if abs(f1a / f1 - 1) > TOLERANCIA_F1_ENTRADA:
        raise ErroSHAN(f"as duas capturas não são da mesma quadrada: f₁ = {f1a:.3f} Hz na do canal medido e "
                       f"{f1:.3f} Hz na de referência.")
    limite = FRACAO_DA_NYQUIST * fs / 2 if freq_max_hz is None else min(freq_max_hz, FRACAO_DA_NYQUIST * fs / 2)
    if f1 > limite:
        raise ErroSHAN(f"f₁ = {f1:.1f} Hz passa do limite de {limite:.0f} Hz (95 % da Nyquist).")
    n = np.arange(1, int(limite / f1) + 1, 2)
    na = _normalizados(xa, fs, f1a, len(n), amostras_por_bloco)
    nb = _normalizados(xb, fs, f1, len(n), amostras_por_bloco)
    razao = na.media / np.where(np.abs(nb.media) > 0, nb.media, 1e-300)
    rel = np.hypot(na.rel, nb.rel)                  # capturas diferentes: ruídos independentes
    snr_a = -20 * np.log10(np.maximum(na.rel * math.sqrt(2), 1e-15))
    snr_b = -20 * np.log10(np.maximum(nb.rel * math.sqrt(2), 1e-15))
    sistematico = np.hypot(piso_a / np.maximum(np.abs(na.media), 1e-300), piso_b / np.maximum(np.abs(nb.media), 1e-300))
    sigma_ln = np.sqrt(rel ** 2 + sistematico ** 2 + SIGMA_LN_MINIMO ** 2)
    sigma_fase = np.sqrt(rel ** 2 + sistematico ** 2 + SIGMA_FASE_MINIMO ** 2)
    if prever_aliasing:
        resolucao = 4.0 * fs / min(na.comprimento, nb.comprimento)
        contam = np.maximum(
            contaminacao_por_aliasing(f1, fs, n, _desvio_do_duty(na.segundo, na.media[0], f1, modelo_a), *modelo_a[:2],
                                      resolucao, polo=modelo_a[2]),
            contaminacao_por_aliasing(f1, fs, n, _desvio_do_duty(nb.segundo, nb.media[0], f1, modelo_b), *modelo_b[:2],
                                      resolucao, polo=modelo_b[2]))
    else:
        contam = np.full(len(n), -np.inf)
    motivos = _motivos(contam, snr_a, snr_b)
    return RazaoQuadrada(f1, fs, 0.0, min(na.blocos, nb.blocos), n, n * f1, razao, sigma_ln, sigma_fase,
                         np.abs(na.media), np.abs(nb.media), snr_a, snr_b, contam,
                         np.array([m == "" for m in motivos]), motivos, fase_relativa=True)


def ancorar_na_dupla(separada: RazaoQuadrada, dupla: RazaoQuadrada) -> tuple[RazaoQuadrada, float]:
    """Completa a razão de capturas separadas (``medir_razao_separada``) pela captura de dois canais da MESMA quadrada:
    a razão das fundamentais nela, X_a/X_b em f₁, dá θ₁ e o módulo. Cada harmônico ganha n·θ₁, e o módulo de todos é
    multiplicado por |razão dupla(f₁)| ÷ |razão separada(f₁)|: se o gerador mudou de amplitude entre as duas capturas
    separadas, isso desfaz a mudança. Devolve a razão ancorada e o ln dessa correção (a mudança de amplitude)."""
    if not separada.fase_relativa:
        raise ErroSHAN("a razão já está ancorada (ou não é de capturas separadas).")
    if abs(separada.f1_hz / dupla.f1_hz - 1) > TOLERANCIA_F1_ENTRADA:
        raise ErroSHAN(f"a captura de dois canais não é da mesma quadrada: f₁ = {dupla.f1_hz:.3f} Hz, e a das "
                       f"separadas, {separada.f1_hz:.3f} Hz.")
    if dupla.n[0] != 1 or not dupla.usado[0]:
        raise ErroSHAN(f"a fundamental da captura de dois canais ({dupla.f1_hz:.1f} Hz) não passou nos critérios: ela "
                       "não serve de âncora.")
    r1 = complex(dupla.razao[0])
    mudanca = math.log(abs(separada.razao[0]) / abs(r1))
    razao = separada.razao * math.exp(-mudanca) * np.exp(1j * separada.n * np.angle(r1))
    sigma_ln = np.sqrt(separada.sigma_ln ** 2 + dupla.sigma_ln[0] ** 2 + separada.sigma_ln[0] ** 2)
    sigma_fase = np.sqrt(separada.sigma_fase ** 2 + (separada.n * dupla.sigma_fase[0]) ** 2)
    return replace(separada, razao=razao, sigma_ln=sigma_ln, sigma_fase=sigma_fase, fase_relativa=False), mudanca


def subtrair_diafonia(r: RazaoQuadrada, diafonias: list[RazaoQuadrada]) -> RazaoQuadrada:
    """A razão sem o vazamento do canal b no a: ``X_a = H_a·S + D·X_b`` dá ``X_a / X_b = H_a / H_b + D``, e D sai das
    capturas de diafonia (a mesma montagem, com o canal a sem sinal próprio: o condutor fora da garra do TC). D é
    interpolado em log f (as partes real e imaginária) entre os harmônicos delas com a referência acima do ruído; fora
    da faixa delas, vale o da borda. A incerteza de D soma em quadratura."""
    f, d, s = [], [], []
    for c in diafonias:
        bom = c.snr_b_db >= SNR_MINIMO_DB
        f.append(c.freq_hz[bom])
        d.append(c.razao[bom])
        s.append(np.abs(c.razao[bom]) * c.sigma_ln[bom])
    if not f or not np.concatenate(f).size:
        raise ErroSHAN("as capturas de diafonia não têm harmônico com a referência acima do ruído.")
    f, d, s = np.concatenate(f), np.concatenate(d), np.concatenate(s)
    ordem = np.argsort(f)
    lf, d, s = np.log(f[ordem]), d[ordem], s[ordem]
    alvo = np.log(r.freq_hz)
    vaz = np.interp(alvo, lf, d.real) + 1j * np.interp(alvo, lf, d.imag)
    s_vaz = np.interp(alvo, lf, s)
    nova = r.razao - vaz
    modulo = np.maximum(np.abs(nova), 1e-300)
    sigma_abs = np.hypot(np.abs(r.razao) * r.sigma_ln, s_vaz)
    return replace(r, razao=nova, sigma_ln=np.hypot(sigma_abs / modulo, SIGMA_LN_MINIMO),
                   sigma_fase=np.hypot(sigma_abs / modulo, SIGMA_FASE_MINIMO), diafonia=vaz)


def pontos_da_razao(r: RazaoQuadrada, escala: complex | np.ndarray = 1.0, fase_extra: np.ndarray | float = 0.0,
                    sigma_ln_extra: np.ndarray | float = 0.0, sigma_fase_extra: np.ndarray | float = 0.0) -> PontosCurva:
    """Os harmônicos usados como pontos de uma curva: ``razão·escala`` (|.| e arg), mais ``fase_extra`` (uma fase
    contínua, como a de um perfil, que não se quer reduzir a ±π) e as incertezas extras em quadratura."""
    u = r.usado
    valor = (r.razao * escala)[u]
    fase = np.angle(valor) + np.broadcast_to(np.asarray(fase_extra, dtype=float), r.razao.shape)[u]
    return PontosCurva(r.freq_hz[u], np.log(np.abs(valor)),
                       np.hypot(r.sigma_ln[u], np.broadcast_to(np.asarray(sigma_ln_extra, dtype=float), r.razao.shape)[u]),
                       fase,
                       np.hypot(r.sigma_fase[u], np.broadcast_to(np.asarray(sigma_fase_extra, dtype=float), r.razao.shape)[u]))
