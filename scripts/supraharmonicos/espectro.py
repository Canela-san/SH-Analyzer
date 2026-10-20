"""Janelas espectrais e cálculo de espectro: FFT única, Welch, bandas e picos.

Depende de: ``constantes``, ``fundamental``, ``erros``."""

import unicodedata
from functools import lru_cache

import numpy as np
from scipy.fft import rfft, rfftfreq
from scipy.signal import find_peaks, get_window

from .constantes import ALIASES_JANELA, NOMES_EXIBICAO_JANELA, TAMANHO_LOTE_WELCH_PADRAO
from .erros import ErroSHAN
from .fundamental import refinar_pico_parabolico

# ---------------------------------------------------------------------------
# 6. Janelas espectrais
# ---------------------------------------------------------------------------

def _normalizar_nome_janela(nome: str) -> str:
    """Remove acentos, hifens, espaços e underscores, e converte para
    minúsculas -- 'Blackman-Harris', 'blackmanharris' e 'BLACKMAN_HARRIS'
    resolvem todos para a mesma chave."""
    sem_acento = unicodedata.normalize("NFKD", nome)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    chave = sem_acento.strip().lower()
    for caractere in ("-", "_", " "):
        chave = chave.replace(caractere, "")
    return chave


def resolver_nome_janela(nome: str) -> str:
    """Validado antes de carregar qualquer arquivo, para dar erro rápido em
    caso de nome digitado errado."""
    chave = _normalizar_nome_janela(nome)
    if chave not in ALIASES_JANELA:
        raise ErroSHAN(
            f"janela '{nome}' não reconhecida em --janela. Aceitos: "
            f"retangular/boxcar, hann/hanning, blackmanharris/blackman-harris, "
            f"flattop/flat-top, kaiser."
        )
    return ALIASES_JANELA[chave]


_JANELA_MAX_EM_CACHE = 1 << 23    # 8 Mi pontos (64 MB): acima disso a janela é refeita, para não prender memória


def obter_janela(nome_canonico: str, n: int, kaiser_beta: float) -> np.ndarray:
    """fftbins=True (variante periódica) -- a recomendada para análise
    espectral por FFT, evita a amostra final redundante da variante
    simétrica (mais apropriada para filtragem no tempo).

    Só leitura e em cache: o Welch, a ENBW e cada canal pedem a mesma janela de novo, e a Kaiser (uma função de
    Bessel por ponto) é cara."""
    if n <= _JANELA_MAX_EM_CACHE:
        return _janela_em_cache(nome_canonico, n, kaiser_beta if nome_canonico == "kaiser" else 0.0)
    return _calcular_janela(nome_canonico, n, kaiser_beta)


def _calcular_janela(nome_canonico: str, n: int, kaiser_beta: float) -> np.ndarray:
    if nome_canonico == "kaiser":
        return get_window(("kaiser", kaiser_beta), n, fftbins=True)
    return get_window(nome_canonico, n, fftbins=True)


@lru_cache(maxsize=8)
def _janela_em_cache(nome_canonico: str, n: int, kaiser_beta: float) -> np.ndarray:
    janela = _calcular_janela(nome_canonico, n, kaiser_beta)
    janela.setflags(write=False)
    return janela


def enbw_bins(nome_canonico: str, n: int, kaiser_beta: float) -> float:
    """Largura de banda equivalente de ruído da janela, em bins: ``N·Σw² / (Σw)²`` (1 para a retangular,
    ~1,5 para a Hann, ~3,8 para a flat-top). Um tom espalha a sua potência por ~ENBW bins de um espectro
    normalizado como 'tom' -- quem SOMA bins (bandas) precisa dividir por ela."""
    janela = obter_janela(nome_canonico, n, kaiser_beta)
    return float(n * np.sum(janela ** 2) / np.sum(janela) ** 2)


def tamanho_segmento_welch(fs: float, resolucao_hz: float) -> int:
    """Amostras por segmento do Welch para a resolução pedida (mínimo de 16)."""
    return max(16, int(round(fs / resolucao_hz)))


def rotulo_janela_completo(nome_canonico: str, kaiser_beta: float) -> str:
    rotulo = NOMES_EXIBICAO_JANELA[nome_canonico]
    if nome_canonico == "kaiser":
        rotulo += f" (beta={kaiser_beta:g})"
    return rotulo


# ---------------------------------------------------------------------------
# 7. Cálculo de espectro: FFT única, Welch, bandas e picos
# ---------------------------------------------------------------------------

def _normalizar_espectro(potencia: np.ndarray, fs: float, tamanho_fft: int,
                          janela: np.ndarray, modo: str) -> np.ndarray:
    """Converte um espectro de potência bruto |X(f)|^2 (de 1 segmento, ou já
    somado/mediado entre vários) para dB, em uma de duas convenções:

    'tom': amplitude linear corrigida pelo ganho coerente da janela (média de
        seus valores) -- sem essa correção a amplitude fica sistematicamente
        abaixo da real, porque a janela atenua energia do sinal antes da FFT.
        Correta para um tom discreto (fundamental, harmônico), cuja energia
        cai essencialmente num único bin.
    'ruido': densidade espectral de potência (PSD, V²/Hz), normalizada pelo
        ganho INCOERENTE da janela (soma de seus valores ao quadrado) --
        correta para conteúdo de banda larga, onde 'tom' daria uma leitura
        que muda artificialmente com o tamanho da FFT/segmento, mesmo para o
        MESMO ruído físico.
    """
    # Espectro de UM lado: cada bin soma o seu par de frequência negativa (fator 2), menos o DC e,
    # com N par, o de Nyquist, que não têm par. (Com N ímpar o último bin TEM par e também dobra.)
    um_lado = np.full(len(potencia), 2.0)
    um_lado[0] = 1.0
    if tamanho_fft % 2 == 0:
        um_lado[-1] = 1.0

    if modo == "tom":
        ganho_coerente = np.mean(janela)
        amplitude_linear = (um_lado / (tamanho_fft * ganho_coerente)) * np.sqrt(potencia)
        return 20 * np.log10(np.maximum(amplitude_linear, 1e-12))

    soma_quadrados_janela = np.sum(janela ** 2)
    psd = um_lado * potencia / (fs * soma_quadrados_janela)
    return 10 * np.log10(np.maximum(psd, 1e-20))


def calcular_espectro(sinal: np.ndarray, fs: float, nome_janela: str,
                       kaiser_beta: float, modo: str = "tom"):
    """FFT de um único segmento -- ver calcular_espectro_welch para o
    caminho com múltiplos segmentos médios. 'modo' escolhe a normalização
    (ver _normalizar_espectro)."""
    n = len(sinal)
    janela = obter_janela(nome_janela, n, kaiser_beta)
    sinal_janelado = (sinal - np.mean(sinal)) * janela
    espectro = rfft(sinal_janelado)
    freqs = rfftfreq(n, 1.0 / fs)
    potencia = np.abs(espectro) ** 2
    amplitude_db = _normalizar_espectro(potencia, fs, n, janela, modo)
    return freqs, amplitude_db


def calcular_espectro_welch(sinal: np.ndarray, fs: float, nome_janela: str,
                             kaiser_beta: float, resolucao_hz: float,
                             sobreposicao: float, modo: str = "ruido"):
    """Espectro médio por segmentação (Welch): reduz a variância da
    estimativa por segmentação + média de periodogramas, ao custo de
    resolução fixa em frequência (fs/resolucao_hz, não o comprimento total
    do sinal).

    Ao contrário do corte em ciclos inteiros (recortar_ciclos_inteiros), não
    tenta eliminar vazamento por sincronismo de ciclo -- ruído de conversores
    chaveados (supraharmônicos) não tem relação de fase com o ciclo da rede,
    então não existe corte "certo" para essa finalidade. Aqui o controle de
    vazamento é a janela espectral e a média entre segmentos, que também
    suaviza deriva de frequência de chaveamento (dithering) ao longo da
    captura.

    Processado em lotes (numpy.lib.stride_tricks.sliding_window_view) em vez
    de 1 segmento por vez em Python puro ou de todos de uma vez -- equilibra
    desempenho (FFT vetorizada por lote) e memória (uma captura longa com
    50% de sobreposição pode gerar centenas de milhares de segmentos).
    """
    tamanho_segmento = tamanho_segmento_welch(fs, resolucao_hz)
    passo = max(1, int(round(tamanho_segmento * (1.0 - sobreposicao))))
    n = len(sinal)

    if n < tamanho_segmento:
        raise ErroSHAN(
            f"sinal com {n} amostras insuficiente para 1 segmento de "
            f"Welch de {tamanho_segmento} amostras (--resolucao-welch "
            f"{resolucao_hz:g} Hz). Aumente a janela de captura ou "
            f"--resolucao-welch."
        )

    n_segmentos = (n - tamanho_segmento) // passo + 1
    janela = obter_janela(nome_janela, tamanho_segmento, kaiser_beta)
    freqs = rfftfreq(tamanho_segmento, 1.0 / fs)
    acumulador = np.zeros(len(freqs))
    janela_deslizante = np.lib.stride_tricks.sliding_window_view(sinal, tamanho_segmento)

    for inicio_lote in range(0, n_segmentos, TAMANHO_LOTE_WELCH_PADRAO):
        indices_lote = np.arange(inicio_lote, min(inicio_lote + TAMANHO_LOTE_WELCH_PADRAO, n_segmentos))
        lote = janela_deslizante[indices_lote * passo]
        lote_janelado = (lote - lote.mean(axis=1, keepdims=True)) * janela
        espectros = rfft(lote_janelado, axis=1)
        acumulador += np.sum(np.abs(espectros) ** 2, axis=0)

    potencia_media = acumulador / n_segmentos
    amplitude_db = _normalizar_espectro(potencia_media, fs, tamanho_segmento, janela, modo)
    return freqs, amplitude_db, n_segmentos


def agrupar_em_bandas(freqs: np.ndarray, amplitude_db: np.ndarray,
                       largura_hz: float, modo: str, enbw: float = 1.0):
    """Resume um espectro fino em bandas de largura fixa (ex.: 200 Hz --
    convenção da literatura de supraharmônicos para tornar o resultado
    comparável entre capturas com resoluções em frequência diferentes, ao
    contrário do valor bin a bin, que muda de significado só porque o
    tamanho da FFT/segmento mudou).

    Cada banda reporta o nível RMS contido nela (dB re 1 unidade do sinal, V
    ou A): para 'ruido' (bins em densidade espectral de potência) é a integral
    da PSD sobre a banda; para 'tom' (bins em amplitude de PICO, corrigida
    pelo ganho coerente da janela) é a soma dos quadrados dos bins convertida
    em RMS (÷2, menos no DC) e dividida pela ``enbw`` da janela, em bins (ver
    :func:`enbw_bins`): com uma janela que não é a retangular, um tom ocupa
    vários bins e a soma sem essa divisão o contaria ENBW vezes (+1,8 dB na
    Hann, +5,8 dB na flat-top). Assim os dois modos dão o mesmo número para o
    mesmo sinal.
    """
    largura_bin = freqs[1] - freqs[0]
    bordas = np.arange(freqs[0], freqs[-1], largura_hz)
    if len(bordas) == 0:
        bordas = np.array([freqs[0]])

    if modo == "tom":
        potencia_linear = 10 ** (amplitude_db / 10.0)          # amplitude de pico² por bin
        potencia_linear[1:] /= 2.0                             # pico² -> RMS² (o DC já é o próprio nível)
        potencia_linear /= enbw
    else:
        potencia_linear = (10 ** (amplitude_db / 10.0)) * largura_bin  # PSD * Hz = RMS² por bin

    centros, valores_db = [], []
    for inicio_banda in bordas:
        mascara = (freqs >= inicio_banda) & (freqs < inicio_banda + largura_hz)
        if not np.any(mascara):
            continue
        energia = np.sum(potencia_linear[mascara])
        centros.append(inicio_banda + largura_hz / 2.0)
        valores_db.append(10 * np.log10(max(energia, 1e-24)))

    return np.array(centros), np.array(valores_db)


def encontrar_picos_espectro(freqs: np.ndarray, amplitude_db: np.ndarray,
                              freq_min: float, freq_max: float, limiar_db: float,
                              distancia_minima_hz: float) -> list[dict]:
    """Localiza picos locais dentro de [freq_min, freq_max] acima de
    'limiar_db' (scipy.signal.find_peaks) e refina cada um por interpolação
    parabólica (refinar_pico_parabolico) -- entrega frequência e amplitude de
    cada componente supraharmônica individual sem depender de aumentar N
    para "acertar" o bin exato."""
    mascara = (freqs >= freq_min) & (freqs <= freq_max)
    indices_banda = np.where(mascara)[0]
    if len(indices_banda) < 3:
        return []

    largura_bin = freqs[1] - freqs[0]
    distancia_bins = max(1, int(round(distancia_minima_hz / largura_bin)))

    sub_espectro = amplitude_db[indices_banda]
    indices_locais, _ = find_peaks(sub_espectro, height=limiar_db, distance=distancia_bins)

    picos = []
    for i_local in indices_locais:
        idx_global = indices_banda[i_local]
        delta, amplitude_vertice = refinar_pico_parabolico(amplitude_db, idx_global)
        freq_refinada = freqs[idx_global] + delta * largura_bin
        picos.append({"frequencia_hz": float(freq_refinada), "amplitude_db": float(amplitude_vertice)})
    return picos
