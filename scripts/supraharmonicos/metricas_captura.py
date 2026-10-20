"""Métricas quantitativas de uma captura -- os números que vão para o relatório.

O ``adc_tool`` mostra a captura (forma de onda, FFT/Welch, picos). Este módulo
a MEDE: devolve números com unidade, prontos para uma tabela, para caracterizar
a cadeia de medição (sonda + condicionamento + ADS8688 + PRU) com um sinal
conhecido injetado por um gerador:

* estatísticas básicas: média (DC), RMS CA, pico a pico, saturação do ADC;
* piso de ruído: densidade espectral (V/√Hz) e ruído RMS em LSB;
* tom: frequência e amplitude da fundamental (FFT com janela Kaiser (β = 14)
  sobre a captura inteira, interpolação parabólica do pico);
* distorção: harmônicos (com a frequência DOBRADA para dentro de 0..fs/2 quando
  caem acima de Nyquist), THD, SINAD, SNR, ENOB e SFDR;
* continuidade: salto de fase da fundamental entre segmentos consecutivos,
  convertido em "amostras equivalentes" -- uma amostra perdida/duplicada pelo
  PRU ou pelo disco aparece como um salto de ~1 amostra;
* acoplamento entre canais: diafonia e atraso de amostragem (o ADS8688
  multiplexa: o canal na posição ``j`` do ciclo é amostrado ``j/fs_total``
  depois do primeiro).

Todas as potências saem da MESMA FFT com janela: ``p[k] = 2|X[k]|²/(N·Σw²)`` é a
contribuição do bin ``k`` à variância do sinal (Parseval), então "potência do
tom" = soma de ``p`` no lóbulo do tom, "ruído" = o que sobra, e o balanço
``total = tom + harmônicos + ruído`` fecha por construção. O lóbulo principal da
Kaiser β=14 tem ±4,6 bins; somar ±6 captura o tom inteiro sem exigir que ele caia
exatamente num bin (não há necessidade de coerência de amostragem). Por que não
a Blackman-Harris: o vazamento dela (~-87 a -96 dBc somado) fica ACIMA do ruído
de quantização de um ADC de 16 bits (-98 dBc) e limitaria o SINAD/ENOB medido; o
da Kaiser β=14 fica em ~-112 dBc (medido com uma senoide ideal, ver
``tests/test_metricas_captura.py``). Mesmo assim, SINAD acima de ~105 dB não é
confiável por este método.

Funções puras sobre ``numpy.ndarray`` (sem I/O); quem lê o arquivo e formata a
saída é ``cli_medir_captura``. Depende de: ``fundamental``, ``erros``.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .erros import ErroSHAN
from .fundamental import refinar_pico_parabolico

log = logging.getLogger(__name__)

BETA_KAISER = 14.0              # lóbulo principal ≈ ±4,6 bins; vazamento a ≥ 10 bins < -125 dBc (a Blackman-Harris só chega a -90 dBc)
SEMILARGURA_LOBULO = 6          # bins de cada lado somados para obter a potência de um tom (capta o lóbulo principal inteiro)
GUARDA_DC = 7                   # bins a partir de 0 ignorados (leakage do DC + 1/f muito baixa)
SNR_PICO_MINIMO_DB = 20.0       # o maior bin precisa estar >= 20 dB acima da mediana do espectro para ser "um tom"
HARMONICOS_PADRAO = 9
AMOSTRAS_MINIMAS = 4096
AMOSTRAS_POR_SEGMENTO_PADRAO = 65536
LIMITE_SALTO_AMOSTRAS = 0.5     # salto de fase acima disso (em amostras equivalentes) = descontinuidade
CICLOS_MINIMOS_POR_SEGMENTO = 10
_CHUNK_PROJECAO = 1 << 20
_TINY = 1e-300


_JANELA_MAX_EM_CACHE = 1 << 23    # 8 Mi pontos (64 MB): acima disso a janela é refeita, para não prender memória


@lru_cache(maxsize=4)
def _janela_em_cache(n: int) -> np.ndarray:
    from scipy.signal.windows import kaiser  # sob demanda: só quem calcula paga o SciPy
    janela = kaiser(n, BETA_KAISER, sym=False)
    janela.setflags(write=False)
    return janela


def _janela(n: int) -> np.ndarray:
    """Kaiser β = 14 de ``n`` pontos, só leitura. A conta (uma função de Bessel por ponto) leva ~20 ms para 100 mil
    pontos, e gerar um perfil pede a MESMA janela dezenas de vezes (cada captura, cada canal): sem o cache, era
    quase metade do tempo do ``gerar_perfil_sonda.py``."""
    from scipy.signal.windows import kaiser  # sob demanda: só quem calcula paga o SciPy
    return _janela_em_cache(n) if n <= _JANELA_MAX_EM_CACHE else kaiser(n, BETA_KAISER, sym=False)


def _db(razao: float) -> float:
    """10·log10(razao); -inf para razão <= 0 (nada acima do piso)."""
    return 10.0 * math.log10(razao) if razao > 0.0 else -math.inf


# ---------------------------------------------------------------------------
# Estatísticas básicas
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Basicas:
    n_amostras: int
    duracao_s: float
    media: float                 # DC, na unidade do sinal (V ou A, já com --ganho)
    rms_ac: float                # desvio padrão (RMS sem o DC)
    rms_total: float             # RMS incluindo o DC
    pico_a_pico: float
    minimo: float
    maximo: float
    rms_ac_lsb: float            # rms_ac em LSB do ADC (0 se lsb desconhecido)


def calcular_basicas(sinal: np.ndarray, fs: float, lsb: float = 0.0) -> Basicas:
    """Média, RMS, pico a pico. ``lsb``: tamanho de 1 código na unidade do sinal (faixa·ganho/65536)."""
    if len(sinal) < 2:
        raise ErroSHAN("poucas amostras para calcular estatísticas.")
    media = float(np.mean(sinal))
    rms_ac = float(np.std(sinal))
    return Basicas(
        n_amostras=len(sinal), duracao_s=len(sinal) / fs, media=media, rms_ac=rms_ac,
        rms_total=math.sqrt(media * media + rms_ac * rms_ac),
        pico_a_pico=float(np.max(sinal) - np.min(sinal)), minimo=float(np.min(sinal)), maximo=float(np.max(sinal)),
        rms_ac_lsb=rms_ac / lsb if lsb > 0 else 0.0,
    )


def fracao_saturada(codigos: np.ndarray, formato: str) -> float:
    """Fração das amostras BRUTAS no código mínimo ou máximo (fundo de escala do ADC)."""
    inferior, superior = (0, 65535) if formato == "uint16" else (-32768, 32767)
    return float(np.count_nonzero((codigos <= inferior) | (codigos >= superior))) / max(1, len(codigos))


# ---------------------------------------------------------------------------
# Espectro: tom, harmônicos, THD, SINAD, SNR, ENOB, SFDR, piso de ruído
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Harmonico:
    ordem: int
    freq_hz: float                  # já dobrada para 0..fs/2 (o que o ADC realmente enxerga)
    aliasado: bool                  # ordem·f0 > fs/2: o harmônico real está acima de Nyquist
    amplitude: float | None         # pico, na unidade do sinal; None = não separável (cai na fundamental/DC)
    nivel_dbc: float | None         # relativo à fundamental; -inf = abaixo do piso de ruído; None = não separável


@dataclass(frozen=True)
class Espectro:
    n_usado: int
    resolucao_hz: float
    potencia_total: float                    # variância sem DC (unidade²)
    densidade_ruido: float                   # unidade/√Hz (mediana do espectro, corrigida para média)
    tem_tom: bool
    freq_tom_hz: float = 0.0
    amplitude_pico: float = 0.0
    amplitude_rms: float = 0.0
    harmonicos: tuple[Harmonico, ...] = ()
    thd_db: float = -math.inf                # soma dos harmônicos/fundamental (-inf = abaixo do piso)
    thd_pct: float = 0.0
    sinad_db: float = math.nan
    snr_db: float = math.nan
    enob_bits: float = math.nan
    ruido_rms: float = 0.0                   # sem o tom e sem os harmônicos
    sfdr_dbc: float = math.nan
    freq_espurio_hz: float = math.nan
    ordem_espurio: int | None = None         # se o maior espúrio coincide com um harmônico listado
    espurio_sobre_piso_db: float = math.nan  # quanto o maior espúrio está acima do piso de ruído (≈ 10 dB = só ruído)


def _frequencia_dobrada(freq_hz: float, fs: float) -> float:
    resto = freq_hz % fs
    return fs - resto if resto > fs / 2.0 else resto


def _lobulo(k: int, n_bins: int) -> slice:
    return slice(max(0, k - SEMILARGURA_LOBULO), min(n_bins, k + SEMILARGURA_LOBULO + 1))


def analisar_espectro(sinal: np.ndarray, fs: float, freq_dica: float | None = None,
                      num_harmonicos: int = HARMONICOS_PADRAO, fundo_escala_pp: float | None = None,
                      procurar_tom: bool = True) -> Espectro:
    """Espectro de potência (FFT única, janela Kaiser β=14) e métricas derivadas.

    ``freq_dica``: procura o tom só em ±10% dela (útil com vários tons ou
    interferência mais forte em outra frequência); sem ela, o maior pico.
    ``fundo_escala_pp``: fundo de escala pico a pico NA UNIDADE DO SINAL
    (faixa·ganho) -- corrige o ENOB para um tom abaixo do fundo de escala.
    ``procurar_tom=False`` só mede o piso de ruído (entrada em curto/aberta)."""
    from scipy.fft import prev_fast_len, rfft  # sob demanda: só quem calcula paga o SciPy
    n = prev_fast_len(len(sinal))
    if n < AMOSTRAS_MINIMAS:
        raise ErroSHAN(f"{len(sinal)} amostra(s) por canal: o mínimo para a análise espectral é {AMOSTRAS_MINIMAS}.")
    x = np.asarray(sinal[:n], dtype=np.float64)
    x = x - np.mean(x)
    janela = _janela(n)
    soma_w2 = float(np.sum(janela * janela))
    espectro = rfft(x * janela)
    p = espectro.real ** 2 + espectro.imag ** 2          # |X|²
    del espectro
    p *= 2.0 / (n * soma_w2)                             # variância por bin (Parseval)
    n_bins = len(p)
    p[:GUARDA_DC] = 0.0

    potencia_total = float(np.sum(p))
    mediana = float(np.median(p[GUARDA_DC:]))
    ruido_por_bin = mediana / math.log(2.0)              # mediana de uma exponencial = média·ln2
    resolucao = fs / n
    densidade = math.sqrt(max(ruido_por_bin * n / fs, 0.0))

    sem_tom = Espectro(n_usado=n, resolucao_hz=resolucao, potencia_total=potencia_total,
                       densidade_ruido=densidade, tem_tom=False, ruido_rms=math.sqrt(potencia_total))
    if not procurar_tom:
        return sem_tom

    inicio_busca, fim_busca = GUARDA_DC + SEMILARGURA_LOBULO, n_bins - 1
    if freq_dica is not None and freq_dica > 0:
        inicio_busca = max(inicio_busca, int(0.9 * freq_dica / resolucao))
        fim_busca = min(fim_busca, int(math.ceil(1.1 * freq_dica / resolucao)))
    if fim_busca <= inicio_busca:
        return sem_tom
    k0 = inicio_busca + int(np.argmax(p[inicio_busca:fim_busca + 1]))
    if _db(p[k0] / max(mediana, _TINY)) < SNR_PICO_MINIMO_DB:
        return sem_tom                                    # nenhum pico claramente acima do piso

    delta, _ = refinar_pico_parabolico(10.0 * np.log10(np.maximum(p[k0 - 1:k0 + 2], _TINY)), 1)
    freq_tom = (k0 + delta) * resolucao
    if k0 - SEMILARGURA_LOBULO < GUARDA_DC:
        log.warning(
            f"o tom ({freq_tom:g} Hz) está a menos de {GUARDA_DC + SEMILARGURA_LOBULO} bins do DC "
            f"(resolução {resolucao:g} Hz): amplitude/THD ficam imprecisos. Capture por mais tempo ou use um tom mais alto."
        )
    potencia_tom = float(np.sum(p[_lobulo(k0, n_bins)]))
    ocupado = np.zeros(n_bins, dtype=bool)
    ocupado[:GUARDA_DC] = True
    ocupado[_lobulo(k0, n_bins)] = True

    harmonicos: list[Harmonico] = []
    potencia_harmonicos = 0.0
    k_harmonicos: dict[int, int] = {}
    for ordem in range(2, num_harmonicos + 1):
        f_real = ordem * freq_tom
        f_vista = _frequencia_dobrada(f_real, fs)
        aliasado = f_real > fs / 2.0
        kh = int(round(f_vista / resolucao))
        faixa = _lobulo(kh, n_bins)
        if kh < 1 or kh >= n_bins or np.any(ocupado[faixa]):
            harmonicos.append(Harmonico(ordem, f_vista, aliasado, None, None))
            continue
        ocupado[faixa] = True
        k_harmonicos[ordem] = kh
        piso_lobulo = ruido_por_bin * (faixa.stop - faixa.start)
        potencia = float(np.sum(p[faixa])) - piso_lobulo
        if potencia < piso_lobulo:                        # menos de 3 dB acima do piso: indistinguível de ruído
            harmonicos.append(Harmonico(ordem, f_vista, aliasado, 0.0, -math.inf))
            continue
        potencia_harmonicos += potencia
        harmonicos.append(Harmonico(ordem, f_vista, aliasado, math.sqrt(2.0 * potencia), _db(potencia / potencia_tom)))

    sinad = _db(potencia_tom / max(potencia_total - potencia_tom, _TINY))
    potencia_ruido = max(potencia_total - potencia_tom - potencia_harmonicos, _TINY)
    amplitude = math.sqrt(2.0 * potencia_tom)
    enob = (sinad - 1.76) / 6.02
    if fundo_escala_pp and amplitude > 0:
        enob = (sinad - 1.76 + 20.0 * math.log10(fundo_escala_pp / (2.0 * amplitude))) / 6.02

    # SFDR: maior pico fora do DC e do lóbulo da fundamental. Os harmônicos NÃO são excluídos: o
    # maior espúrio costuma ser justamente o 2º ou o 3º harmônico (ver 'ordem_espurio').
    candidatos = np.ones(n_bins, dtype=bool)
    candidatos[:GUARDA_DC + SEMILARGURA_LOBULO] = False
    candidatos[max(0, k0 - 2 * SEMILARGURA_LOBULO):k0 + 2 * SEMILARGURA_LOBULO + 1] = False
    sfdr = freq_espurio = sobre_piso = math.nan
    ordem_espurio = None
    if np.any(candidatos):
        ks = int(np.argmax(np.where(candidatos, p, 0.0)))
        faixa_ks = _lobulo(ks, n_bins)
        potencia_bruta = float(np.sum(p[faixa_ks]))
        piso_lobulo = ruido_por_bin * (faixa_ks.stop - faixa_ks.start)
        potencia_espurio = max(potencia_bruta - piso_lobulo, _TINY)
        sfdr = _db(potencia_tom / potencia_espurio)
        freq_espurio = ks * resolucao
        sobre_piso = _db(potencia_bruta / max(piso_lobulo, _TINY))
        for ordem, kh in k_harmonicos.items():
            if abs(ks - kh) <= SEMILARGURA_LOBULO:
                ordem_espurio = ordem
                break

    return Espectro(
        n_usado=n, resolucao_hz=resolucao, potencia_total=potencia_total, densidade_ruido=densidade,
        tem_tom=True, freq_tom_hz=freq_tom, amplitude_pico=amplitude, amplitude_rms=math.sqrt(potencia_tom),
        harmonicos=tuple(harmonicos), thd_db=_db(potencia_harmonicos / potencia_tom),
        thd_pct=100.0 * math.sqrt(potencia_harmonicos / potencia_tom), sinad_db=sinad,
        snr_db=_db(potencia_tom / potencia_ruido), enob_bits=enob, ruido_rms=math.sqrt(potencia_ruido),
        sfdr_dbc=sfdr, freq_espurio_hz=freq_espurio, ordem_espurio=ordem_espurio, espurio_sobre_piso_db=sobre_piso,
    )


# ---------------------------------------------------------------------------
# Projeção num tom de frequência conhecida (amplitude + fase) e continuidade
# ---------------------------------------------------------------------------

def projetar_tom(sinal: np.ndarray, fs: float, freq_hz: float) -> tuple[float, float]:
    """(amplitude de pico, fase em rad) do tom de ``freq_hz`` dentro de ``sinal``.

    Projeção com a mesma janela Kaiser sobre a captura inteira, em blocos (memória
    limitada). A fase é a de ``cos(2π f n/fs + φ)`` com ``n`` = índice da amostra
    DENTRO do canal -- a diferença entre dois canais é comparável, pois a janela e
    ``n`` são os mesmos."""
    n = len(sinal)
    if n < 2:
        raise ErroSHAN("poucas amostras para projetar o tom.")
    janela = _janela(n)
    soma_w = float(np.sum(janela))
    centro = sinal - np.mean(sinal)
    acumulado = 0.0 + 0.0j
    passo = 2.0 * math.pi * freq_hz / fs
    for ini in range(0, n, _CHUNK_PROJECAO):
        fim = min(ini + _CHUNK_PROJECAO, n)
        indices = np.arange(ini, fim, dtype=np.float64)
        acumulado += complex(np.dot(centro[ini:fim] * janela[ini:fim], np.exp(-1j * passo * indices)))
    z = 2.0 * acumulado / soma_w
    return float(abs(z)), float(np.angle(z))


@dataclass(frozen=True)
class Continuidade:
    segmentos: int
    amostras_por_segmento: int
    salto_max_amostras: float          # maior salto de fase entre segmentos vizinhos, em amostras equivalentes
    indice_salto_max: int              # índice (por canal) do começo do segmento em que o salto aparece
    saltos_acima_do_limite: int        # eventos (passos vizinhos contam como um só)
    variacao_amplitude_pct: float      # (máx-mín)/média da amplitude por segmento


def verificar_continuidade(sinal: np.ndarray, fs: float, freq_hz: float,
                           amostras_por_segmento: int = AMOSTRAS_POR_SEGMENTO_PADRAO,
                           limite_amostras: float = LIMITE_SALTO_AMOSTRAS) -> Continuidade | None:
    """Procura descontinuidades (amostras perdidas/duplicadas, trocas de bloco)
    numa captura de um TOM estável.

    A fase do tom em segmentos consecutivos cresce linearmente (a deriva de um
    erro de frequência é constante); uma amostra perdida faz a fase saltar
    ``2π·f0/fs`` de uma vez. Compara-se a diferença de fase entre segmentos com a
    mediana dessas diferenças (a deriva) e converte-se o desvio em "amostras
    equivalentes" = Δφ·fs/(2π·f0). Devolve None se a captura é curta demais para
    ao menos 4 segmentos de ``CICLOS_MINIMOS_POR_SEGMENTO`` ciclos cada."""
    segmento = max(amostras_por_segmento, int(math.ceil(CICLOS_MINIMOS_POR_SEGMENTO * fs / freq_hz)))
    n_seg = len(sinal) // segmento
    if n_seg < 4:
        return None
    omega = 2.0 * math.pi * freq_hz / fs
    local = np.exp(-1j * omega * np.arange(segmento, dtype=np.float64))
    centro = np.asarray(sinal[:n_seg * segmento], dtype=np.float64)
    centro = centro - np.mean(centro)
    z = np.array([np.dot(centro[s * segmento:(s + 1) * segmento], local) for s in range(n_seg)])
    fases = np.unwrap(np.angle(z) - 2.0 * math.pi * ((freq_hz / fs * segmento * np.arange(n_seg)) % 1.0))
    passos = np.diff(fases)
    desvio = passos - np.median(passos)
    # Um salto que cai no MEIO de um segmento se reparte entre dois passos vizinhos; a soma dos dois o recompõe.
    soma_vizinhos = np.concatenate([np.abs(desvio[:-1] + desvio[1:]), [0.0]])
    saltos = np.maximum(np.abs(desvio), soma_vizinhos) / omega
    i_max = int(np.argmax(saltos))
    amplitudes = np.abs(z)
    acima = saltos > limite_amostras
    eventos = int(np.count_nonzero(acima[1:] & ~acima[:-1])) + int(acima[0])    # passos vizinhos = 1 só evento
    return Continuidade(
        segmentos=n_seg, amostras_por_segmento=segmento, salto_max_amostras=float(saltos[i_max]),
        indice_salto_max=(i_max + 1) * segmento, saltos_acima_do_limite=eventos,
        variacao_amplitude_pct=100.0 * float((np.max(amplitudes) - np.min(amplitudes)) / np.mean(amplitudes)),
    )


# ---------------------------------------------------------------------------
# Acoplamento entre canais
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Acoplamento:
    canal: int
    canal_agressor: int
    amplitude: float              # tom no canal, na frequência do agressor
    diafonia_db: float            # 20·log10(amplitude / amplitude do agressor)
    atraso_medido_us: float       # (fase_canal - fase_agressor)/(2π f), em µs
    atraso_esperado_us: float     # (posição_canal - posição_agressor)/fs_total, em µs


def calcular_acoplamento(tons: dict[int, tuple[float, float]], posicoes: dict[int, int],
                         freq_hz: float, fs_total: float) -> list[Acoplamento]:
    """Compara os canais num mesmo tom: o de maior amplitude é o "agressor".

    ``tons``: canal -> (amplitude, fase) de ``projetar_tom`` na MESMA ``freq_hz``;
    ``posicoes``: canal -> posição no ciclo round-robin do arquivo.
    Duas leituras diferentes do mesmo número:

    * injetando o tom num canal e deixando outro em curto: ``diafonia_db`` é o
      acoplamento (o atraso não tem significado -- o canal só tem ruído);
    * injetando o MESMO sinal nos dois: ``atraso_medido_us`` ≈ ``atraso_esperado_us``
      confere o intervalo de multiplexação do ADS8688 (diferença de posição/fs_total)."""
    if len(tons) < 2:
        return []
    agressor = max(tons, key=lambda c: tons[c][0])
    amp_agressor, fase_agressor = tons[agressor]
    resultado = []
    for canal in sorted(tons):
        if canal == agressor:
            continue
        amplitude, fase = tons[canal]
        dfase = (fase - fase_agressor + math.pi) % (2.0 * math.pi) - math.pi
        resultado.append(Acoplamento(
            canal=canal, canal_agressor=agressor, amplitude=amplitude,
            diafonia_db=20.0 * math.log10(max(amplitude, _TINY) / max(amp_agressor, _TINY)),
            atraso_medido_us=dfase / (2.0 * math.pi * freq_hz) * 1e6,
            atraso_esperado_us=(posicoes[canal] - posicoes[agressor]) / fs_total * 1e6,
        ))
    return resultado
