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
  PRU ou pelo disco aparece como um salto de ~1 amostra -- e, à parte, o salto
  em cada troca de buffer da PRU comparado com o dos outros segmentos (um atraso
  fixo a cada troca, como os 6,97 µs do firmware antigo, fica abaixo de 1 amostra
  com vários canais e só aparece nessa comparação);
* acoplamento entre canais: diafonia e atraso de amostragem (o ADS8688
  multiplexa: o canal na posição ``j`` do ciclo é amostrado ``j/fs_total``
  depois do primeiro);
* grade de tempo (22/10/2026): o jitter da amostragem (a parte do ruído que
  cresce com a inclinação do tom) e o degrau de tempo, em ns, em posições
  escolhidas (trocas de buffer, rebases do contador da PRU).

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
RAZAO_TROCA_DESTOA = 10.0       # o salto numa troca de buffer destoa acima de 10x o típico dos outros segmentos...
LIMITE_TROCA_US = 0.05          # ... e de 0,05 µs (capturas saudáveis de 19/10: 0,01 a 0,04 µs; o defeito antigo: 6,97 µs)
CICLOS_MINIMOS_POR_SEGMENTO = 10
AMOSTRAS_POR_BLOCO_JITTER = 2000   # curto: a deriva lenta de fase do gerador fica no ajuste (ver estimar_jitter)
HARMONICOS_JITTER = 5
JANELA_DEGRAU = 4000            # amostras de cada lado de um evento para medir o degrau de tempo nele
SNR_MINIMO_GRADE_DB = 30.0      # jitter e degraus só com o tom bem acima do ruído (a diafonia de -97 dB num canal
                                # em curto passa como "tom" numa FFT longa, e daria microssegundos de jitter)
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
    passos_amostras: tuple[float, ...] = ()   # avanço de fase entre segmentos vizinhos, em amostras (com a deriva); o
                                              # i-ésimo é o da fronteira na amostra (i+1)·amostras_por_segmento


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
        passos_amostras=tuple(float(x) for x in passos / omega),
    )


def posicoes_das_trocas(amostras_por_buffer: int, num_canais: int, inicio: int, n_amostras: int) -> list[float]:
    """Onde caem as trocas de buffer da PRU dentro de um trecho, em amostras DO CANAL contadas do início do trecho.

    A PRU troca de buffer a cada ``amostras_por_buffer`` amostras brutas (todos os canais) desde a 1ª amostra do
    arquivo; o trecho começa na amostra ``inicio`` do canal e tem ``n_amostras``. Com um nº de canais que não divide o
    buffer, a troca cai no meio de um ciclo, e a posição sai fracionária."""
    if amostras_por_buffer <= 0 or num_canais <= 0:
        return []
    por_canal = amostras_por_buffer / num_canais
    primeira = math.floor(inicio / por_canal) + 1
    posicoes = []
    m = primeira
    while m * por_canal - inicio < n_amostras:
        posicoes.append(m * por_canal - inicio)
        m += 1
    return posicoes


@dataclass(frozen=True)
class TrocasBuffer:
    trocas: int                        # trocas de buffer dentro do trecho analisado
    salto_mediano_amostras: float      # mediana, entre as trocas, do salto medido em cada uma (nan sem trocas)
    salto_max_amostras: float          # o maior deles (nan sem trocas)
    salto_tipico_amostras: float       # mediana dos saltos nas fronteiras longe das trocas (nan se sobram menos de 3)
    destoam: bool                      # as trocas saltam mais que o resto (ver comparar_trocas_de_buffer)


def comparar_trocas_de_buffer(cont: Continuidade, fs: float, posicoes: list[float],
                              limite_amostras: float = LIMITE_SALTO_AMOSTRAS) -> TrocasBuffer:
    """Compara o salto de fase nas trocas de buffer com o das outras fronteiras de segmento (P6).

    Uma troca em ``p`` só mexe no passo das fronteiras a menos de 1 segmento dela (os dois segmentos vizinhos da
    fronteira contêm ``p``); no meio de um segmento, ela se reparte entre as duas, e a soma das duas a recompõe. As
    outras fronteiras dão a deriva (mediana dos passos) e o salto típico (mediana do desvio). Com 8 canais o buffer
    tem só 2 segmentos, e é por isso que a conta é feita sobre os passos, e não sobre os saltos de
    ``verificar_continuidade`` (que somam vizinhos e espalhariam cada troca para as fronteiras limpas).

    As trocas destoam quando a MEDIANA delas passa de ``RAZAO_TROCA_DESTOA`` vezes o típico e de ``LIMITE_TROCA_US``:
    um defeito sistemático aparece em todas, um acaso em uma só. Sem 3 fronteiras limpas para comparar, destoam se a
    mediana passa de ``limite_amostras`` (o critério de amostra perdida)."""
    nan = math.nan
    passos = np.asarray(cont.passos_amostras, dtype=np.float64)
    if not posicoes or passos.size == 0:
        return TrocasBuffer(0, nan, nan, nan, False)
    fronteiras = (np.arange(passos.size) + 1.0) * cont.amostras_por_segmento
    distancias = np.abs(fronteiras[None, :] - np.asarray(posicoes, dtype=np.float64)[:, None])
    afetadas = distancias < cont.amostras_por_segmento                 # [troca, fronteira]
    limpas = ~np.any(afetadas, axis=0)
    deriva = float(np.median(passos[limpas])) if np.count_nonzero(limpas) >= 3 else float(np.median(passos))
    desvio = passos - deriva
    em_troca = [abs(float(np.sum(desvio[linha]))) for linha in afetadas if np.any(linha)]
    if not em_troca:
        return TrocasBuffer(0, nan, nan, nan, False)
    mediana = float(np.median(em_troca))
    if np.count_nonzero(limpas) >= 3:
        tipico = float(np.median(np.abs(desvio[limpas])))
        destoam = mediana > RAZAO_TROCA_DESTOA * tipico and mediana / fs * 1e6 > LIMITE_TROCA_US
    else:
        tipico, destoam = nan, mediana > limite_amostras
    return TrocasBuffer(len(em_troca), mediana, float(np.max(em_troca)), tipico, destoam)


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


# ---------------------------------------------------------------------------
# Grade de tempo: jitter e degraus (22/10/2026)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Jitter:
    rms_ns: float                      # jitter da amostragem estimado, em ns rms
    ruido_plano: float                 # ruído (unidade do sinal) onde o tom é plano: o do ADC, sem o do jitter
    blocos: int


def estimar_jitter(sinal: np.ndarray, fs: float, freq_hz: float,
                   amostras_por_bloco: int = AMOSTRAS_POR_BLOCO_JITTER) -> Jitter | None:
    """Jitter da amostragem, medido num tom estável.

    Uma amostra tomada ``δ`` fora do instante erra ``inclinação·δ``: o ruído cresce onde o tom é íngreme (nos
    cruzamentos por zero) e some onde ele é plano (nos picos). Em blocos curtos, ajusta-se o tom (DC, fundamental
    com deriva linear de fase e amplitude, harmônicos até o 5º) e regride-se o quadrado do resíduo contra o
    quadrado da inclinação: ``r² ≈ σ0² + (inclinação·σt)²``. ``σt`` (em amostras) vira ns com ``fs`` e ``σ0`` é o
    ruído do ADC. A mediana entre blocos ignora os poucos com um degrau ou um transitório.

    Blocos curtos importam: a deriva lenta de fase do gerador (espúrios a ±10-20 Hz do tom) não segue um tom de
    frequência fixa num bloco longo, e o resto dela vira "jitter" -- nas capturas de 21/10/2026, blocos de 20.000
    amostras davam até 3x mais que blocos de 2.000 a 100 kS/s, e estes davam ~8,4 ns em todas as taxas.

    O que este número não separa: jitter da PRU, do gerador e do relógio de amostragem do ADC somam-se. Com a
    grade exata da PRU (firmware de 22/10/2026), o que sobrar é do resto da cadeia. Devolve None sem 4 blocos."""
    bloco = int(amostras_por_bloco)
    n_blocos = len(sinal) // bloco if bloco > 0 else 0
    if n_blocos < 4 or not 0 < freq_hz < fs / 2:
        return None
    c0_todos, c1_todos = [], []
    for r2, d2 in _residuos_e_inclinacoes(sinal, 2.0 * math.pi * freq_hz / fs, bloco, n_blocos):
        media_d2, media_r2 = d2.mean(axis=1), r2.mean(axis=1)
        dd = d2 - media_d2[:, None]
        variancia = np.maximum((dd * dd).mean(axis=1), _TINY)
        c1 = (dd * (r2 - media_r2[:, None])).mean(axis=1) / variancia
        c1_todos.append(c1)
        c0_todos.append(media_r2 - c1 * media_d2)
    c1_mediano = float(np.median(np.concatenate(c1_todos)))
    c0_mediano = float(np.median(np.concatenate(c0_todos)))
    return Jitter(rms_ns=math.sqrt(max(c1_mediano, 0.0)) / fs * 1e9, ruido_plano=math.sqrt(max(c0_mediano, 0.0)),
                  blocos=n_blocos)


def _residuos_e_inclinacoes(sinal: np.ndarray, omega: float, bloco: int, n_blocos: int):
    """Para cada lote de blocos: (resíduo², inclinação²) por amostra, com o tom ajustado bloco a bloco (DC,
    fundamental com deriva linear de fase e amplitude, harmônicos até o 5º). A inclinação é a da fundamental, na
    unidade do sinal por amostra. Lê o sinal em lotes (serve um memmap de horas)."""
    t = np.arange(bloco, dtype=np.float64) - (bloco - 1) / 2.0
    colunas = [np.ones(bloco)]
    for h in range(1, HARMONICOS_JITTER + 1):
        colunas += [np.cos(h * omega * t), np.sin(h * omega * t)]
    colunas += [t * np.cos(omega * t), t * np.sin(omega * t)]
    base = np.column_stack(colunas)
    projecao = np.linalg.pinv(base)
    cos1, sen1 = np.cos(omega * t), np.sin(omega * t)
    por_vez = max(1, (1 << 21) // bloco)
    for inicio in range(0, n_blocos, por_vez):
        fim = min(n_blocos, inicio + por_vez)
        x = np.asarray(sinal[inicio * bloco:fim * bloco], dtype=np.float64).reshape(fim - inicio, bloco)
        coef = x @ projecao.T
        r2 = (x - coef @ base.T) ** 2
        # derivada (por amostra) de a·cos(ωt) + b·sin(ωt)
        yield r2, (omega * (coef[:, 2:3] * cos1 - coef[:, 1:2] * sen1)) ** 2


def ruido_por_inclinacao(sinal: np.ndarray, fs: float, freq_hz: float, faixas: int = 12,
                         amostras_por_bloco: int = AMOSTRAS_POR_BLOCO_JITTER) -> tuple[np.ndarray, np.ndarray]:
    """O ruído RMS do resíduo em faixas de inclinação do tom: a "assinatura" do jitter (o ruído cresce com a
    inclinação) que :func:`estimar_jitter` resume num número. Devolve (inclinação no centro de cada faixa, em unidade
    do sinal por SEGUNDO; ruído RMS na faixa); faixas iguais de 0 à inclinação máxima."""
    bloco = int(amostras_por_bloco)
    n_blocos = len(sinal) // bloco
    soma = np.zeros(faixas)
    contagem = np.zeros(faixas)
    maximo = None
    for r2, d2 in _residuos_e_inclinacoes(sinal, 2.0 * math.pi * freq_hz / fs, bloco, n_blocos):
        d = np.sqrt(d2)
        if maximo is None:
            maximo = float(np.percentile(d, 99.9)) or 1.0
        indice = np.minimum((d / maximo * faixas).astype(int), faixas - 1)
        soma += np.bincount(indice.ravel(), weights=r2.ravel(), minlength=faixas)
        contagem += np.bincount(indice.ravel(), minlength=faixas)
    centros = (np.arange(faixas) + 0.5) / faixas * (maximo or 0.0) * fs
    return centros, np.sqrt(soma / np.maximum(contagem, 1))


def _fase_no_ponto(trecho: np.ndarray, omega: float, t: np.ndarray) -> float:
    """Fase em ``t = 0`` de ``A·cos(ωt + φ)`` ajustado a ``trecho`` (com deriva linear e H2/H3), em rad."""
    colunas = [np.ones_like(t), np.cos(omega * t), np.sin(omega * t), t * np.cos(omega * t), t * np.sin(omega * t)]
    for h in (2, 3):
        colunas += [np.cos(h * omega * t), np.sin(h * omega * t)]
    coef, *_ = np.linalg.lstsq(np.column_stack(colunas), np.asarray(trecho, dtype=np.float64), rcond=None)
    return math.atan2(-coef[2], coef[1])          # a·cos + b·sin = A·cos(ωt + φ) com a = A·cos φ, b = -A·sen φ


@dataclass(frozen=True)
class Degraus:
    eventos_ns: tuple[float, ...]      # degrau de tempo em cada posição pedida (> 0 = as amostras seguintes atrasaram)
    controle_ns: tuple[float, ...]     # o mesmo, a meio caminho entre eventos: a escala do "nada aconteceu"

    @property
    def mediana_ns(self) -> float:
        return float(np.median(self.eventos_ns)) if self.eventos_ns else math.nan

    @property
    def maior_ns(self) -> float:
        return float(max(self.eventos_ns, key=abs)) if self.eventos_ns else math.nan

    @property
    def dispersao_controle_ns(self) -> float:
        """Desvio-padrão robusto (1,4826·MAD) dos degraus de controle; nan com menos de 2."""
        if len(self.controle_ns) < 2:
            return math.nan
        c = np.asarray(self.controle_ns)
        return float(1.4826 * np.median(np.abs(c - np.median(c))))


def medir_degraus_de_tempo(sinal: np.ndarray, fs: float, freq_hz: float, posicoes: list[float],
                           janela: int = JANELA_DEGRAU) -> Degraus:
    """Degrau de tempo da amostragem em cada posição (em amostras do ``sinal``), em ns.

    A fase do tom é ajustada nas ``janela`` amostras antes e nas ``janela`` depois da posição, cada lado
    extrapolado até ela; a diferença, dividida por ``2π·f``, é quanto as amostras seguintes andaram no tempo. Com
    um tom de 10 kHz a ~1/6 do fundo de escala, o ruído do ADC dá ~0,3 ns por evento. Posições sem ``janela`` dos
    dois lados ficam de fora. O controle repete a conta a meio caminho entre eventos vizinhos."""
    n = len(sinal)
    omega = 2.0 * math.pi * freq_hz / fs
    antes = np.arange(-janela, 0, dtype=np.float64)
    depois = np.arange(0, janela, dtype=np.float64)

    def degrau(p: int) -> float | None:
        if p - janela < 0 or p + janela > n:
            return None
        dfase = _fase_no_ponto(sinal[p:p + janela], omega, depois) - _fase_no_ponto(sinal[p - janela:p], omega, antes)
        dfase = (dfase + math.pi) % (2.0 * math.pi) - math.pi
        return dfase / (2.0 * math.pi * freq_hz) * 1e9

    inteiras = sorted(int(round(p)) for p in posicoes)
    eventos = [d for d in (degrau(p) for p in inteiras) if d is not None]
    meios = [(a + b) // 2 for a, b in zip([0, *inteiras], [*inteiras, n]) if b - a > 4 * janela]
    controle = [d for d in (degrau(p) for p in meios) if d is not None]
    return Degraus(tuple(eventos), tuple(controle))


def posicoes_dos_rebases(clock_hz: float, periodo_ticks: int, num_canais: int, inicio: int, n_amostras: int) -> list[float]:
    """Onde caem os rebases do contador da PRU (a cada ~2^31 ciclos desde a 1ª amostra), em amostras DO CANAL
    contadas do início do trecho. Cada rebase espera a leitura passar de 2^31 desde o zero anterior, que veio um
    quadro depois: os seguintes escorregam ~1 amostra cada, o que não muda nada numa janela de milhares."""
    if clock_hz <= 0 or periodo_ticks <= 0 or num_canais <= 0:
        return []
    passo = (2**31 + periodo_ticks) / periodo_ticks       # amostras brutas entre rebases
    posicoes = []
    m = 1
    while True:
        p = m * passo / num_canais - inicio
        if p >= n_amostras:
            return posicoes
        if p > 0:
            posicoes.append(p)
        m += 1
