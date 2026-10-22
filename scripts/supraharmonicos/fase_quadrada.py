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
SIGMA_LN_MINIMO = 2e-4          # piso da incerteza da magnitude (0,002 dB) e da fase (0,01°)
SIGMA_FASE_MINIMO = 2e-4
AMOSTRAS_POR_BLOCO = 1 << 20    # ~3,4 s a 312,5 kS/s: a média coerente entre blocos dá a incerteza medida
BLOCOS_MINIMOS = 4              # captura curta: dividida em 4 blocos (a dispersão entre eles é a incerteza)
# Piso sistemático por harmônico, em LSB: o INL do ADC (até ±0,75 LSB no datasheet) faz, a cada borda da quadrada que
# atravessa a escala, um erro que espalha uns centésimos de LSB por harmônico. Um harmônico fraco (o 567º de uma
# quadrada de 256 Hz, a 145 kHz, tem ~0,4 LSB) ganha incerteza de alguns graus que o ruído não mostra; as quadradas de
# f₁ alta, com harmônicos de dezenas de LSB ali, ficam com o peso. Ajustável no medir_fase.py (--piso-sistematico).
PISO_SISTEMATICO_LSB = 0.02
PARES_PARA_O_DUTY = 4           # o duty sai dos harmônicos 2, 4, 6 e 8


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
    duty_desvio: float                  # |ε| (D = 0,5 ± ε), estimado pelos harmônicos pares
    sigma_duty: float
    blocos: int                         # quantos blocos entraram na média coerente
    n: np.ndarray                       # ordens ímpares medidas (todas, usadas ou não)
    freq_hz: np.ndarray
    ganho_rel: np.ndarray               # |H(n f₁)| / |H(f₁)|, corrigido do duty
    sigma_ln_ganho: np.ndarray          # incerteza de ln(ganho_rel)
    fase_rel_rad: np.ndarray            # M_n − θ_n, desenrolada pelo modelo de partida
    sigma_fase_rad: np.ndarray
    amplitude: np.ndarray               # amplitude de pico do harmônico, na unidade do sinal (LSB na CLI)
    nivel_medio: float                  # o nível médio da captura (o offset): as variantes de offset mudam os códigos
    snr_db: np.ndarray                  # o harmônico sobre o ruído (a dispersão entre os blocos)
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


def _harmonicos_do_bloco(xw: np.ndarray, fs: float, f1: float, m_impares: int, m_pares: int,
                         soma: float) -> tuple[np.ndarray, np.ndarray]:
    """Amplitudes complexas (de pico) dos harmônicos ímpares 1, 3, 5... e pares 2, 4... de um bloco janelado, pela
    transformada chirp-z: todos de uma vez, em O(N log N) (conferida contra o DTFT direto: 1e-7 de erro relativo)."""
    from scipy.signal import czt

    passo = np.exp(-2j * np.pi * 2 * f1 / fs)
    impares = czt(xw, m=m_impares, w=passo, a=np.exp(2j * np.pi * f1 / fs)) * (2.0 / soma)
    pares = czt(xw, m=m_pares, w=passo, a=np.exp(2j * np.pi * 2 * f1 / fs)) * (2.0 / soma)
    return impares, pares


def medir_quadrada(sinal: np.ndarray, fs: float, f_dica: float | None = None, f0: float = F0_PADRAO_HZ,
                   q: float = Q_PADRAO, freq_max_hz: float | None = None, amostras_por_bloco: int = AMOSTRAS_POR_BLOCO,
                   piso_sistematico: float = PISO_SISTEMATICO_LSB) -> RespostaQuadrada:
    """Mede os harmônicos ímpares de uma captura de quadrada e devolve a resposta da cadeia relativa a f₁.

    A captura é dividida em blocos (``amostras_por_bloco``; em capturas curtas, 4 blocos). Em cada bloco, o invariante
    ``Z_n = X_n·e^{−j n arg X_1}`` (fase M_n, módulo |X_n|) não depende do instante do bloco; a média coerente dos Z
    dá a medida, e a dispersão entre os blocos, a incerteza (ruído, deriva do gerador). ``piso_sistematico`` (na
    unidade do sinal) entra somado em quadratura, dividido pela amplitude de cada harmônico.

    ``f0``/``q``: o modelo de partida -- para desenrolar a fase, prever o aliasing e tirar o filtro da razão entre os
    harmônicos pares e a fundamental (não entram na medida)."""
    x = np.asarray(sinal, dtype=np.float64)
    nivel_medio = float(np.mean(x))
    x = x - nivel_medio
    f1 = estimar_f1(x[: 1 << 22], fs, f_dica)
    limite = FRACAO_DA_NYQUIST * fs / 2 if freq_max_hz is None else min(freq_max_hz, FRACAO_DA_NYQUIST * fs / 2)
    n = np.arange(1, int(limite / f1) + 1, 2)
    if len(n) < 3:
        raise ErroSHAN(f"f₁ = {f1:.1f} Hz deixa só {len(n)} harmônico(s) ímpar(es) abaixo de {limite:.0f} Hz: use uma "
                       "quadrada mais lenta.")
    pares_k = np.arange(1, PARES_PARA_O_DUTY + 1)
    pares_k = pares_k[2 * pares_k * f1 < limite] if np.any(2 * pares_k * f1 < limite) else pares_k[:1]

    comprimento = amostras_por_bloco if len(x) >= BLOCOS_MINIMOS * amostras_por_bloco else len(x) // BLOCOS_MINIMOS
    if comprimento < 4096:
        raise ErroSHAN(f"captura curta demais ({len(x)} amostras): são precisos {BLOCOS_MINIMOS} blocos de 4096.")
    n_blocos = len(x) // comprimento
    w = _janela_bh(comprimento)
    soma = float(np.sum(w))
    z = np.empty((n_blocos, len(n)), dtype=complex)
    zp = np.empty((n_blocos, len(pares_k)), dtype=complex)
    for b in range(n_blocos):
        bloco = x[b * comprimento:(b + 1) * comprimento]
        impares, pares = _harmonicos_do_bloco((bloco - bloco.mean()) * w, fs, f1, len(n), len(pares_k), soma)
        rotacao = np.exp(-1j * np.angle(impares[0]))
        z[b] = impares * rotacao ** n
        zp[b] = pares * rotacao ** (2 * pares_k)
    zm = z.mean(axis=0)
    a1 = abs(zm[0])
    if a1 == 0:
        raise ErroSHAN("a fundamental tem amplitude zero: não é uma quadrada.")
    # dispersão (complexa) entre os blocos, por componente: o desvio da média
    sigma_z = np.std(z, axis=0, ddof=1) / math.sqrt(2 * n_blocos)
    rel_ruido = sigma_z / np.maximum(np.abs(zm), 1e-300)
    snr_db = -20 * np.log10(np.maximum(rel_ruido * math.sqrt(2), 1e-15))

    # Duty pelos pares: com D = 0,5 + ε, |c_2k|/|c_1| = |sin(2πkε)| / (2k cos(πε)); o filtro entre f₁ e 2k·f₁, do modelo
    h1 = h_segunda_ordem(f1, f0, q)
    r = np.abs(zp.mean(axis=0)) / a1 / np.abs(h_segunda_ordem(2 * pares_k * f1, f0, q) / h1)
    eps_k = np.arcsin(np.minimum(1.0, 2 * pares_k * r)) / (2 * np.pi * pares_k)
    eps = float(np.median(eps_k))
    sigma_r = np.std(zp, axis=0, ddof=1) / math.sqrt(2 * n_blocos) / a1 / np.abs(h_segunda_ordem(2 * pares_k * f1, f0, q) / h1)
    sigma_eps = float(max(np.std(eps_k) / math.sqrt(len(eps_k)) if len(eps_k) > 1 else 0.0,
                          float(np.min(sigma_r / (np.pi * np.maximum(np.cos(2 * np.pi * pares_k * eps), 0.1)))), 1e-7))

    fator_duty = np.cos(np.pi * n * eps)                     # sin(π n D) / sin(π n/2), para n ímpar
    ganho_rel = np.abs(zm) / a1 * n * abs(fator_duty[0]) / np.maximum(np.abs(fator_duty), 1e-12)
    teta = np.where(np.sin(np.pi * n / 2) * np.sign(fator_duty) * np.sign(fator_duty[0]) > 0, 0.0, np.pi)
    m_bruta = np.angle(zm) - teta
    previsto = fase_relativa_modelo(n * f1, f1, f0, q)
    fase_rel = previsto + np.angle(np.exp(1j * (m_bruta - previsto)))      # desenrola pelo modelo de partida

    amplitude = np.abs(zm)
    sistematico = piso_sistematico / np.maximum(amplitude, 1e-300)
    duty_ln = np.abs(np.pi * n * np.tan(np.pi * n * eps)) * sigma_eps
    sigma_fase = np.sqrt(rel_ruido ** 2 + sistematico ** 2 + SIGMA_FASE_MINIMO ** 2)
    sigma_ln = np.sqrt(rel_ruido ** 2 + rel_ruido[0] ** 2 + sistematico ** 2 + duty_ln ** 2 + SIGMA_LN_MINIMO ** 2)

    resolucao = 4.0 * fs / comprimento                       # ~2 lóbulos da Blackman-Harris
    contam = contaminacao_por_aliasing(f1, fs, n, eps, f0, q, resolucao)

    motivos = []
    for i in range(len(n)):
        if i == 0:
            motivos.append("")                               # a fundamental: a referência (R = 1, M = 0)
        elif abs(fator_duty[i]) < FATOR_DUTY_MINIMO:
            motivos.append(f"perto de um nulo do duty (cos(πnε) = {fator_duty[i]:.2f})")
        elif contam[i] > CONTAMINACAO_MAX_DB:
            motivos.append(f"aliasing a {contam[i]:.0f} dB")
        elif snr_db[i] < SNR_MINIMO_DB:
            motivos.append(f"SNR de {snr_db[i]:.0f} dB")
        else:
            motivos.append("")
    usado = np.array([m == "" for m in motivos])
    log.debug(f"f₁ = {f1:.4f} Hz, ε = {eps:.5f}, {n_blocos} blocos, {usado.sum()} de {len(n)} harmônicos usados")
    return RespostaQuadrada(f1, fs, eps, sigma_eps, n_blocos, n, n * f1, ganho_rel, sigma_ln, fase_rel, sigma_fase,
                            amplitude, nivel_medio, snr_db, contam, usado, motivos)


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


# ---------------------------------------------------------------------------------------------------------------
# Várias capturas numa curva só: a costura (cada f₁ medida por uma quadrada mais lenta) e a média numa grade
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class PontosAbsolutos:
    """Os harmônicos usados de uma captura, já como |H| e ψ (K = 1, fase mínima), com as incertezas da costura."""

    medida: RespostaQuadrada
    freq_hz: np.ndarray
    ln_ganho: np.ndarray
    sigma_ln: np.ndarray
    fase_rad: np.ndarray
    sigma_fase: np.ndarray
    ancora: str                         # "modelo" (a captura de f₁ mais baixa) ou "f₁ = ... Hz" (a que a mediu)


def _residuos_da_base_em(base: PontosAbsolutos, f: np.ndarray, f0: float, q: float):
    """(resíduo de ln|H|, σ, resíduo de ψ, σ) da base contra o modelo, em cada f (interpolados em log f; exatos onde f
    é um harmônico da base), e a máscara de onde a base cobre f."""
    lf = np.log(base.freq_hz)
    r_ln = base.ln_ganho - np.log(np.abs(h_segunda_ordem(base.freq_hz, f0, q)))
    r_f = base.fase_rad - _fase_continua(base.freq_hz, f0, q)
    alvo = np.log(f)
    dentro = (alvo >= lf[0] - 1e-9) & (alvo <= lf[-1] + 1e-9)
    k = np.clip(np.searchsorted(lf, alvo), 1, len(lf) - 1)
    a = np.clip((alvo - lf[k - 1]) / (lf[k] - lf[k - 1]), 0.0, 1.0)
    s_ln = np.where(a < 0.5, base.sigma_ln[k - 1], base.sigma_ln[k]) * np.where((a > 1e-6) & (a < 1 - 1e-6), 1.5, 1.0)
    s_f = np.where(a < 0.5, base.sigma_fase[k - 1], base.sigma_fase[k]) * np.where((a > 1e-6) & (a < 1 - 1e-6), 1.5, 1.0)
    return (1 - a) * r_ln[k - 1] + a * r_ln[k], s_ln, (1 - a) * r_f[k - 1] + a * r_f[k], s_f, dentro


def costurar(medidas: list[RespostaQuadrada], f0: float, q: float) -> list[PontosAbsolutos]:
    """Cada captura em |H| e ψ absolutos (K = 1, fase mínima). A de f₁ mais baixa (a base) usa o modelo em f₁: lá ele é
    quase 0 dB e a fase, quase a reta do atraso de grupo (a convenção que fixa o atraso puro). Cada outra captura é
    posta na escala da base pelo que as duas medem em comum: o ganho em f₁ (ln|H(f₁)|, um deslocamento) e a fase em f₁
    (ψ(f₁), que entra multiplicada por n), ajustados por mínimos quadrados ponderados sobre TODOS os harmônicos que as
    duas medem (exatos quando f₁ é múltiplo ímpar da f₁ da base: 1280 = 5 x 256). Um ponto só da base (o da f₁) faria o
    erro dele crescer n vezes; a regressão o dilui. Sem sobreposição suficiente, o modelo."""
    if not medidas:
        return []
    ordem = sorted(range(len(medidas)), key=lambda i: medidas[i].f1_hz)
    saida: list[PontosAbsolutos | None] = [None] * len(medidas)
    base_i = ordem[0]
    r = medidas[base_i]
    u = r.usado
    base = PontosAbsolutos(r, r.freq_hz[u], np.log(r.ganho_rel[u]) + math.log(abs(h_segunda_ordem(r.f1_hz, f0, q))),
                           r.sigma_ln_ganho[u], fase_absoluta(r, f0, q)[u], r.sigma_fase_rad[u], "modelo")
    saida[base_i] = base
    for i in ordem[1:]:
        r = medidas[i]
        u = r.usado
        f = r.freq_hz[u]
        n = r.n[u].astype(float)
        b_ln, b_sln, b_f, b_sf, dentro = _residuos_da_base_em(base, f, f0, q)
        # o que a base diz, absoluto, em cada harmônico desta captura
        ref_ln = b_ln + np.log(np.abs(h_segunda_ordem(f, f0, q)))
        ref_f = b_f + _fase_continua(f, f0, q)
        ln_rel = np.log(r.ganho_rel[u])
        if int(np.sum(dentro)) >= 2:
            w = 1 / (b_sln[dentro] ** 2 + r.sigma_ln_ganho[u][dentro] ** 2)
            ln_f1 = float(np.sum(w * (ref_ln[dentro] - ln_rel[dentro])) / np.sum(w))
            s_ln = 1 / math.sqrt(float(np.sum(w)))
            wf = 1 / (b_sf[dentro] ** 2 + r.sigma_fase_rad[u][dentro] ** 2)
            nd = n[dentro]
            psi_f1 = float(np.sum(wf * nd * (ref_f[dentro] - r.fase_rel_rad[u][dentro])) / np.sum(wf * nd * nd))
            s_f = 1 / math.sqrt(float(np.sum(wf * nd * nd)))
            ancora = f"f₁ = {base.medida.f1_hz:.1f} Hz ({int(np.sum(dentro))} harmônicos em comum)"
        else:
            ln_f1 = math.log(abs(h_segunda_ordem(r.f1_hz, f0, q)))
            psi_f1 = float(_fase_continua(np.array([r.f1_hz]), f0, q)[0])
            s_ln = s_f = 0.0
            ancora = "modelo"
        fora_da_fundamental = n > 1                            # a fundamental é só a âncora (R = 1, M = 0)
        saida[i] = PontosAbsolutos(r, f[fora_da_fundamental], (ln_rel + ln_f1)[fora_da_fundamental],
                                   np.hypot(r.sigma_ln_ganho[u], s_ln)[fora_da_fundamental],
                                   (r.fase_rel_rad[u] + n * psi_f1)[fora_da_fundamental],
                                   np.hypot(r.sigma_fase_rad[u], n * s_f)[fora_da_fundamental], ancora)
    return [s for s in saida if s is not None]


@dataclass
class RespostaCombinada:
    """A resposta numa grade logarítmica: em cada faixa, a média ponderada (1/σ²) dos resíduos contra o modelo, somada
    ao modelo no centro da faixa. χ² ~ 1 = os pontos da faixa (de capturas diferentes) concordam dentro das σ."""

    freq_hz: np.ndarray
    ln_ganho: np.ndarray
    sigma_ln: np.ndarray
    fase_rad: np.ndarray
    sigma_fase: np.ndarray
    pontos: np.ndarray
    chi2_ln: np.ndarray
    chi2_fase: np.ndarray


def combinar_em_grade(absolutos: list[PontosAbsolutos], f0: float, q: float, por_decada: int = 20) -> RespostaCombinada:
    f = np.concatenate([a.freq_hz for a in absolutos])
    ln = np.concatenate([a.ln_ganho for a in absolutos])
    s_ln = np.concatenate([a.sigma_ln for a in absolutos])
    fa = np.concatenate([a.fase_rad for a in absolutos])
    s_fa = np.concatenate([a.sigma_fase for a in absolutos])
    r_ln = ln - np.log(np.abs(h_segunda_ordem(f, f0, q)))
    r_fa = fa - _fase_continua(f, f0, q)
    n_faixas = max(1, int(math.ceil(math.log10(f.max() / f.min()) * por_decada)))
    bordas = np.geomspace(f.min() / 1.0001, f.max() * 1.0001, n_faixas + 1)
    qual = np.digitize(f, bordas) - 1
    linhas = []
    for k in range(n_faixas):
        sel = qual == k
        if not np.any(sel):
            continue
        w_ln, w_fa = 1 / s_ln[sel] ** 2, 1 / s_fa[sel] ** 2
        centro = math.exp(float(np.sum(w_fa * np.log(f[sel])) / np.sum(w_fa)))
        m_ln = float(np.sum(w_ln * r_ln[sel]) / np.sum(w_ln))
        m_fa = float(np.sum(w_fa * r_fa[sel]) / np.sum(w_fa))
        npts = int(sel.sum())
        chi_ln = float(np.sum(w_ln * (r_ln[sel] - m_ln) ** 2) / (npts - 1)) if npts > 1 else math.nan
        chi_fa = float(np.sum(w_fa * (r_fa[sel] - m_fa) ** 2) / (npts - 1)) if npts > 1 else math.nan
        linhas.append((centro, math.log(abs(h_segunda_ordem(centro, f0, q))) + m_ln, 1 / math.sqrt(np.sum(w_ln)),
                       float(_fase_continua(np.array([centro]), f0, q)[0]) + m_fa, 1 / math.sqrt(np.sum(w_fa)), npts,
                       chi_ln, chi_fa))
    colunas = list(zip(*linhas))
    return RespostaCombinada(*(np.array(c) for c in colunas))

