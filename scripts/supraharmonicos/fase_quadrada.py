"""Resposta em frequência (magnitude e FASE) de uma cadeia a partir de UMA captura de onda quadrada.

Por que uma quadrada (S2, 22/10/2026)
    Sem uma referência de tempo de fora (o osciloscópio no CS do ADC), a fase de um tom sozinho numa captura só diz
    em que instante a captura começou. Uma quadrada simétrica traz a referência dentro dela: no centro do pulso, todo
    harmônico é um cosseno real, ``c_n ∝ sin(π n D) / n``, qualquer que seja o duty ``D``. Numa captura que começou
    num instante qualquer, ``arg X_n − n·arg X_1`` não depende desse instante e vale

        M_n = θ_n + ψ(n f₁) − n·ψ(f₁),         θ_n = 0 ou π (o sinal de sin(π n D) / sin(π D))

    onde ψ é a fase da cadeia. Um atraso puro τ (a conversão do ADC, o instante da amostra) soma −2π f τ a ψ e some
    de M_n: o que sobra é a fase do filtro analógico menos a reta da fase dele em f₁ (o atraso de grupo em baixa
    frequência). A magnitude ``|X_n| / |X_1| · n · |sin(π D)| / |sin(π n D)|`` é ``|H(n f₁)| / |H(f₁)|``. Nenhuma
    das duas depende da amplitude do gerador nem de um instrumento de referência.

Cuidados que este módulo cobre
    * O duty: não muda a fase dos harmônicos ímpares, mas muda a magnitude (``cos(π n ε)``, com ``D = 0,5 + ε``).
      ``ε`` sai do 2º harmônico; harmônicos perto de um nulo (|cos(π n ε)| pequeno) ficam de fora.
    * O aliasing: os harmônicos acima da Nyquist dobram. Para cada harmônico medido, a contaminação prevista (a
      quadrada pelo modelo da cadeia) que cai sobre ele é calculada; acima de ``CONTAMINACAO_MAX_DB``, ele fica de
      fora. Escolha f₁ com taxa/f₁ longe de um inteiro (ou meio-inteiro): 1280, 6400 e 256 Hz servem a 312,5 e a
      400 kS/s.
    * Os relógios do gerador e da BeagleBone diferem (~40 ppm): f₁ é medida na própria captura, e um erro dela some
      de M_n (a janela é simétrica).

O modelo da cadeia é o passa-baixa de 2ª ordem do T3: ``H(s) = K ω0² / (s² + (ω0/Q) s + ω0²)``.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np

from .erros import ErroSHAN

log = logging.getLogger(__name__)

F0_PADRAO_HZ = 24165.0          # o 2ª ordem do T3 de 22/10/2026 (cadeia_tensao_312k): só o ponto de partida
Q_PADRAO = 0.5288
FRACAO_DA_NYQUIST = 0.95        # harmônicos até 95 % da Nyquist
CONTAMINACAO_MAX_DB = -60.0     # aliasing previsto acima disso, relativo ao harmônico: fora (~0,06° de erro)
SNR_MINIMO_DB = 30.0            # harmônico menos de 30 dB acima do ruído vizinho: fora
FATOR_DUTY_MINIMO = 0.3         # |cos(π n ε)| abaixo disso (perto de um nulo do duty): fora
SIGMA_LN_MINIMO = 1e-3          # piso da incerteza da magnitude (0,009 dB) e da fase (0,06°): o resto do sistema
SIGMA_FASE_MINIMO = 1e-3


def h_segunda_ordem(f, f0: float, q: float) -> np.ndarray:
    """H(j2πf) do passa-baixa de 2ª ordem com K = 1."""
    s = 1j * np.asarray(f, dtype=np.float64) / f0
    return 1.0 / (s * s + s / q + 1.0)


def fase_relativa_modelo(f, f1: float, f0: float, q: float) -> np.ndarray:
    """ψ(f) − (f/f₁)·ψ(f₁) do 2ª ordem, com ψ contínua (desenrolada a partir de 0 Hz)."""
    f = np.asarray(f, dtype=np.float64)
    return _fase_continua(f, f0, q) - (f / f1) * _fase_continua(np.array([f1]), f0, q)[0]


def _fase_continua(f: np.ndarray, f0: float, q: float) -> np.ndarray:
    # arg de 1 / (1 − x² + j x/Q): vai de 0 a −π sem salto (o denominador nunca cruza o semieixo real negativo)
    x = f / f0
    return -np.arctan2(x / q, 1.0 - x * x)


# ---------------------------------------------------------------------------------------------------------------
# A medida numa captura
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class RespostaQuadrada:
    """Os harmônicos ímpares de uma captura de quadrada, já como resposta da cadeia relativa a f₁."""

    f1_hz: float
    fs_hz: float
    duty_desvio: float                  # |ε| (D = 0,5 ± ε), estimado pelo 2º harmônico
    n: np.ndarray                       # ordens ímpares medidas (todas, usadas ou não)
    freq_hz: np.ndarray
    ganho_rel: np.ndarray               # |H(n f₁)| / |H(f₁)|, corrigido do duty
    sigma_ln_ganho: np.ndarray          # incerteza de ln(ganho_rel)
    fase_rel_rad: np.ndarray            # M_n − θ_n, desenrolada pelo modelo de partida
    sigma_fase_rad: np.ndarray
    snr_db: np.ndarray                  # o harmônico sobre o ruído vizinho
    contaminacao_db: np.ndarray         # o aliasing previsto sobre ele, relativo a ele
    usado: np.ndarray                   # passou nos critérios
    motivo: list[str] = field(default_factory=list)   # vazio = usado

    def __len__(self) -> int:
        return len(self.n)


def _janela_bh(n: int) -> np.ndarray:
    from scipy.signal.windows import blackmanharris
    return blackmanharris(n)


def _dtft(xw: np.ndarray, f: float, fs: float, soma_janela: float) -> complex:
    """Amplitude complexa (de pico) em f de um sinal já janelado (tempo a partir da 1ª amostra)."""
    k = np.arange(len(xw))
    return complex(2.0 * np.dot(xw, np.exp(-2j * np.pi * f / fs * k)) / soma_janela)


def estimar_f1(sinal: np.ndarray, fs: float, f_dica: float | None = None) -> float:
    """A frequência da fundamental: o maior pico do espectro (ou o perto de ``f_dica``), refinado no DTFT."""
    from scipy.optimize import minimize_scalar

    x = np.asarray(sinal, dtype=np.float64) - float(np.mean(sinal))
    w = _janela_bh(len(x))
    xw = x * w
    espectro = np.abs(np.fft.rfft(xw))
    freqs = np.fft.rfftfreq(len(x), 1.0 / fs)
    if f_dica is not None:
        busca = (freqs > f_dica * 0.97) & (freqs < f_dica * 1.03)
    else:
        busca = freqs > 20.0
    if not np.any(busca):
        raise ErroSHAN("nenhuma frequência na faixa de busca da fundamental.")
    k = int(np.flatnonzero(busca)[np.argmax(espectro[busca])])
    passo = fs / len(x)
    soma = float(np.sum(w))
    resultado = minimize_scalar(lambda f: -abs(_dtft(xw, f, fs, soma)), bounds=(freqs[k] - passo, freqs[k] + passo),
                                method="bounded", options={"xatol": passo * 1e-5})
    return float(resultado.x)


def _ruido_por_harmonico(xw: np.ndarray, fs: float, soma_janela: float, freqs_alvo: np.ndarray, f1: float) -> np.ndarray:
    """Amplitude típica de ruído (mesma escala de ``_dtft``) entre 0,2 e 0,8 f₁ acima de cada harmônico: a mediana dos
    bins da FFT janelada ali (longe dos harmônicos, do lóbulo deles e das posições de meio-harmônico)."""
    espectro = np.abs(np.fft.rfft(xw)) * 2.0 / soma_janela
    freqs = np.fft.rfftfreq(len(xw), 1.0 / fs)
    ruido = np.empty(len(freqs_alvo))
    for i, f in enumerate(freqs_alvo):
        trecho = ((freqs > f + 0.15 * f1) & (freqs < f + 0.4 * f1)) | ((freqs > f + 0.6 * f1) & (freqs < f + 0.85 * f1))
        if not np.any(trecho):
            trecho = (freqs > f - 0.4 * f1) & (freqs < f - 0.15 * f1)
        ruido[i] = float(np.median(espectro[trecho])) if np.any(trecho) else 0.0
    return ruido


def _dobrada(f: np.ndarray, fs: float) -> np.ndarray:
    return np.abs((f + fs / 2) % fs - fs / 2)


def contaminacao_por_aliasing(f1: float, fs: float, n_alvo: np.ndarray, duty_desvio: float, f0: float, q: float,
                              resolucao_hz: float, ate_vezes_fs: float = 8.0) -> np.ndarray:
    """Para cada harmônico ímpar ``n_alvo``, a soma (em amplitude) dos componentes da quadrada, filtrados pelo modelo,
    que dobram para menos de ``resolucao_hz`` dele, relativa a ele mesmo (dB; −inf = nenhum)."""
    k = np.arange(1, int(ate_vezes_fs * fs / f1) + 1)
    amp = np.abs(np.sin(np.pi * k * (0.5 + duty_desvio))) / k * np.abs(h_segunda_ordem(k * f1, f0, q))
    dobradas = _dobrada(k * f1, fs)
    saida = np.full(len(n_alvo), -np.inf)
    for i, n in enumerate(n_alvo):
        f = n * f1
        perto = (np.abs(dobradas - f) < resolucao_hz) & (k != n)
        if np.any(perto):
            alvo = abs(np.sin(np.pi * n * (0.5 + duty_desvio))) / n * abs(h_segunda_ordem(f, f0, q))
            saida[i] = 20 * math.log10(max(float(np.sum(amp[perto])), 1e-300) / max(alvo, 1e-300))
    return saida


def medir_quadrada(sinal: np.ndarray, fs: float, f_dica: float | None = None, f0: float = F0_PADRAO_HZ,
                   q: float = Q_PADRAO, freq_max_hz: float | None = None) -> RespostaQuadrada:
    """Mede os harmônicos ímpares de uma captura de quadrada e devolve a resposta da cadeia relativa a f₁.

    ``f0``/``q``: o modelo de partida -- só para desenrolar a fase e prever o aliasing (não entram na medida)."""
    x = np.asarray(sinal, dtype=np.float64)
    x = x - float(np.mean(x))
    f1 = estimar_f1(x, fs, f_dica)
    limite = FRACAO_DA_NYQUIST * fs / 2 if freq_max_hz is None else min(freq_max_hz, FRACAO_DA_NYQUIST * fs / 2)
    n = np.arange(1, int(limite / f1) + 1, 2)
    if len(n) < 3:
        raise ErroSHAN(f"f₁ = {f1:.1f} Hz deixa só {len(n)} harmônico(s) ímpar(es) abaixo de {limite:.0f} Hz: use uma "
                       "quadrada mais lenta.")
    w = _janela_bh(len(x))
    xw = x * w
    soma = float(np.sum(w))

    # Os harmônicos ímpares pela recorrência do núcleo (e^{-j2π f₁ k/fs})^n: 1 multiplicação por harmônico em vez de
    # um exp() inteiro (a captura de 10 s tem 3 milhões de amostras).
    base = np.exp(-2j * np.pi * f1 / fs * np.arange(len(x)))
    passo = base * base
    nucleo = base.copy()
    coefs = np.empty(len(n), dtype=complex)
    for i in range(len(n)):
        coefs[i] = 2.0 * np.dot(xw, nucleo) / soma
        nucleo *= passo
    x2 = _dtft(xw, 2 * f1, fs, soma)
    if abs(coefs[0]) == 0:
        raise ErroSHAN("a fundamental tem amplitude zero: não é uma quadrada.")

    # Duty pelo 2º harmônico: com D = 0,5 + ε, |c₂|/|c₁| = sin(2π|ε|) / (2 cos(πε)) = sin(π|ε|). O filtro entre f₁
    # e 2f₁ vem do modelo (perto de f₁ ele quase não atenua; a 2ª passada do medir_fase usa o modelo já ajustado).
    h21 = abs(h_segunda_ordem(2 * f1, f0, q) / h_segunda_ordem(f1, f0, q))
    eps = _duty_pelo_segundo_harmonico(abs(x2) / abs(coefs[0]) / h21)

    fator_duty = np.cos(np.pi * n * eps)                     # sin(π n D) / sin(π n/2), para n ímpar
    ganho_rel = np.abs(coefs) / abs(coefs[0]) * n * abs(fator_duty[0]) / np.maximum(np.abs(fator_duty), 1e-12)
    teta = np.where(np.sin(np.pi * n / 2) * np.sign(fator_duty) * np.sign(fator_duty[0]) > 0, 0.0, np.pi)
    m_bruta = np.angle(coefs) - n * np.angle(coefs[0]) - teta
    previsto = fase_relativa_modelo(n * f1, f1, f0, q)
    fase_rel = previsto + np.angle(np.exp(1j * (m_bruta - previsto)))      # desenrola pelo modelo de partida

    ruido = _ruido_por_harmonico(xw, fs, soma, n * f1, f1)
    rel_ruido = ruido / np.maximum(np.abs(coefs), 1e-300)
    snr_db = -20 * np.log10(np.maximum(rel_ruido, 1e-15))
    sigma = np.hypot(rel_ruido / math.sqrt(2), n * rel_ruido[0] / math.sqrt(2))    # o harmônico e n vezes a fundamental
    sigma_fase = np.maximum(sigma, SIGMA_FASE_MINIMO)
    sigma_ln = np.maximum(np.hypot(rel_ruido / math.sqrt(2), rel_ruido[0] / math.sqrt(2)), SIGMA_LN_MINIMO)

    resolucao = 4.0 * fs / len(x)                       # ~2 lóbulos da Blackman-Harris
    contam = contaminacao_por_aliasing(f1, fs, n, eps, f0, q, resolucao)

    motivos = []
    for i in range(len(n)):
        if i == 0:
            motivos.append("")                          # a fundamental: a referência (R = 1, M = 0)
        elif snr_db[i] < SNR_MINIMO_DB:
            motivos.append(f"SNR de {snr_db[i]:.0f} dB")
        elif contam[i] > CONTAMINACAO_MAX_DB:
            motivos.append(f"aliasing a {contam[i]:.0f} dB")
        elif abs(fator_duty[i]) < FATOR_DUTY_MINIMO:
            motivos.append(f"perto de um nulo do duty (cos(πnε) = {fator_duty[i]:.2f})")
        else:
            motivos.append("")
    usado = np.array([m == "" for m in motivos])
    log.debug(f"f₁ = {f1:.4f} Hz, ε = {eps:.5f}, {usado.sum()} de {len(n)} harmônicos ímpares usados")
    return RespostaQuadrada(f1, fs, eps, n, n * f1, ganho_rel, sigma_ln, fase_rel, sigma_fase, snr_db, contam, usado,
                            motivos)


def _duty_pelo_segundo_harmonico(razao: float) -> float:
    """|ε| a partir de r = |c₂|/|c₁| (já sem o filtro): r = sin(π|ε|). O sinal de ε não importa: os harmônicos
    ímpares dependem só de cos(π n ε)."""
    return math.asin(min(1.0, max(0.0, razao))) / math.pi


# ---------------------------------------------------------------------------------------------------------------
# O ajuste do 2ª ordem (várias capturas juntas)
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class AjusteFase:
    nome: str                   # "conjunto", "só magnitude", "só fase"
    f0_hz: float
    q: float
    sigma_f0_hz: float
    sigma_q: float
    residuo_db: float           # rms dos resíduos de magnitude (dB)
    residuo_graus: float        # rms dos resíduos de fase (°)
    chi2_reduzido: float
    n_pontos: int


def _residuos(p, medidas: list[RespostaQuadrada], usar_mag: bool, usar_fase: bool) -> np.ndarray:
    f0, q = p
    saida = []
    for r in medidas:
        u = r.usado
        if usar_mag:
            modelo = np.abs(h_segunda_ordem(r.freq_hz[u], f0, q)) / abs(h_segunda_ordem(r.f1_hz, f0, q))
            saida.append((np.log(r.ganho_rel[u]) - np.log(modelo)) / r.sigma_ln_ganho[u])
        if usar_fase:
            modelo = fase_relativa_modelo(r.freq_hz[u], r.f1_hz, f0, q)
            saida.append(np.angle(np.exp(1j * (r.fase_rel_rad[u] - modelo))) / r.sigma_fase_rad[u])
    return np.concatenate(saida)


def ajustar_segunda_ordem(medidas: list[RespostaQuadrada], usar_mag: bool = True, usar_fase: bool = True,
                          f0_inicial: float = F0_PADRAO_HZ, q_inicial: float = Q_PADRAO) -> AjusteFase:
    """Mínimos quadrados ponderados de (f0, Q) aos pontos usados. As incertezas vêm do jacobiano, escaladas por
    sqrt(χ²_red) quando ele passa de 1 (o modelo ou as incertezas não explicam tudo)."""
    from scipy.optimize import least_squares

    if not (usar_mag or usar_fase):
        raise ErroSHAN("o ajuste precisa da magnitude, da fase ou das duas.")
    res = least_squares(_residuos, [f0_inicial, q_inicial], args=(medidas, usar_mag, usar_fase),
                        bounds=([100.0, 0.05], [1e7, 20.0]), x_scale=[f0_inicial, q_inicial])
    n_res = len(res.fun)
    gl = max(n_res - 2, 1)
    chi2 = float(np.sum(res.fun ** 2) / gl)
    try:
        cov = np.linalg.inv(res.jac.T @ res.jac) * max(chi2, 1.0)
        sigmas = np.sqrt(np.diag(cov))
    except np.linalg.LinAlgError:
        sigmas = np.array([math.nan, math.nan])
    f0, q = res.x
    mag_db, fase_g = [], []
    for r in medidas:
        u = r.usado
        modelo = np.abs(h_segunda_ordem(r.freq_hz[u], f0, q)) / abs(h_segunda_ordem(r.f1_hz, f0, q))
        mag_db.append(20 * np.log10(r.ganho_rel[u] / modelo))
        fase_g.append(np.degrees(np.angle(np.exp(1j * (r.fase_rel_rad[u] - fase_relativa_modelo(r.freq_hz[u], r.f1_hz,
                                                                                                    f0, q))))))
    nome = "conjunto" if usar_mag and usar_fase else ("só magnitude" if usar_mag else "só fase")
    return AjusteFase(nome, float(f0), float(q), float(sigmas[0]), float(sigmas[1]),
                      float(np.sqrt(np.mean(np.concatenate(mag_db) ** 2))),
                      float(np.sqrt(np.mean(np.concatenate(fase_g) ** 2))), chi2, n_res)


def fase_absoluta(r: RespostaQuadrada, f0: float, q: float) -> np.ndarray:
    """ψ(n f₁) supondo FASE MÍNIMA (nenhum atraso puro na cadeia analógica): M_n + n·ψ_modelo(f₁). É o que se mede
    menos um atraso puro qualquer, que nenhuma medida sem referência de tempo externa separa."""
    return r.fase_rel_rad + r.n * _fase_continua(np.array([r.f1_hz]), f0, q)[0]
