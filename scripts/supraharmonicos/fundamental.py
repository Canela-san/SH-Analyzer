"""Fundamental da rede: estimativa, corte em ciclos inteiros e refino de pico.

Depende de: ``filtros``, ``erros``."""

import logging

import numpy as np

from .erros import ErroSHAN

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 5. Fundamental: estimativa, corte em ciclos inteiros, interpolação de pico
# ---------------------------------------------------------------------------

def refinar_pico_parabolico(espectro_db: np.ndarray, indice_pico: int) -> tuple[float, float]:
    """Interpolação parabólica (log-magnitude) ao redor de um pico já
    localizado por argmax -- corrige o erro de quantização do bin
    (scalloping loss) sem precisar de uma FFT maior. Retorna (delta_bins em
    [-0.5, 0.5], amplitude_db estimada no vértice da parábola)."""
    n = len(espectro_db)
    if indice_pico <= 0 or indice_pico >= n - 1:
        return 0.0, float(espectro_db[indice_pico])

    y_menos, y_pico, y_mais = espectro_db[indice_pico - 1:indice_pico + 2]
    denominador = y_menos - 2.0 * y_pico + y_mais
    if denominador == 0:
        return 0.0, float(y_pico)

    delta = float(np.clip(0.5 * (y_menos - y_mais) / denominador, -0.5, 0.5))
    amplitude_vertice = y_pico - 0.25 * (y_menos - y_mais) * delta
    return delta, float(amplitude_vertice)


def estimar_frequencia_fundamental(sinal: np.ndarray, fs: float,
                                    freq_min: float, freq_max: float) -> float:
    """Estimativa grosseira via FFT + Hann fixa (independente de --janela --
    só uma ferramenta de triagem para o corte do passa-baixa que segue; a
    precisão real vem do refinamento por cruzamento de zero). O pico é
    refinado por interpolação parabólica para reduzir o erro de quantização
    do bin sem precisar de uma FFT maior."""
    n = len(sinal)
    if n < 16:
        raise ErroSHAN("poucos dados para estimar a frequência fundamental.")

    from scipy.fft import rfft, rfftfreq  # sob demanda: só quem calcula paga o SciPy
    janela = np.hanning(n)
    espectro_db = 20 * np.log10(np.maximum(np.abs(rfft((sinal - np.mean(sinal)) * janela)), 1e-12))
    freqs = rfftfreq(n, 1.0 / fs)

    banda = (freqs >= freq_min) & (freqs <= freq_max)
    if not np.any(banda):
        raise ErroSHAN(
            f"nenhuma componente de frequência entre {freq_min} Hz e "
            f"{freq_max} Hz. Ajuste --freq-min/--freq-max ou -f."
        )

    indices_banda = np.where(banda)[0]
    idx_pico = indices_banda[np.argmax(espectro_db[indices_banda])]
    delta, _ = refinar_pico_parabolico(espectro_db, idx_pico)
    resolucao_bin = freqs[1] - freqs[0]
    return float(freqs[idx_pico] + delta * resolucao_bin)


def detectar_cruzamentos_por_zero(sinal_filtrado: np.ndarray) -> np.ndarray:
    """Cruzamentos ascendentes com posição FRACIONÁRIA (interpolação linear
    entre a amostra negativa e a positiva) -- mais preciso que o índice
    inteiro mais próximo, principalmente em fs baixa relativa à fundamental."""
    indices = np.where((sinal_filtrado[:-1] < 0) & (sinal_filtrado[1:] >= 0))[0]
    if len(indices) == 0:
        return np.array([])

    y0 = sinal_filtrado[indices]
    y1 = sinal_filtrado[indices + 1]
    fracao = -y0 / (y1 - y0)
    return indices + fracao


def refinar_periodo_fundamental(posicoes_cruzamento: np.ndarray, fs: float):
    """periodo = (último - primeiro) / n_ciclos -- dilui o erro de detecção
    de cada cruzamento por todos os ciclos observados, em vez de concentrá-lo
    num único intervalo."""
    n_ciclos_disponiveis = len(posicoes_cruzamento) - 1
    if n_ciclos_disponiveis < 1:
        raise ErroSHAN(
            "cruzamentos por zero insuficientes para estimar o período "
            "da fundamental (janela curta demais, ou sinal sem componente "
            "periódica clara nessa faixa)."
        )
    periodo_amostras = (posicoes_cruzamento[-1] - posicoes_cruzamento[0]) / n_ciclos_disponiveis
    return periodo_amostras / fs, n_ciclos_disponiveis


def estimar_amostras_para_n_ciclos(n_ciclos: int, fs: float, freq_min: float,
                                    margem_ciclos: int = 5) -> int:
    """Estima quantas amostras bastam para conter N ciclos completos, usando
    freq_min (período mais longo da faixa de busca) mais uma margem -- evita
    filtrar/varrer uma captura inteira quando --fft N (análise de distúrbios
    momentâneos) só precisa dos primeiros N ciclos."""
    amostras_por_ciclo_pior_caso = fs / freq_min
    return int(np.ceil((n_ciclos + margem_ciclos) * amostras_por_ciclo_pior_caso))


def cruzamentos_da_fundamental(sinal: np.ndarray, fs: float, freq_min: float,
                               freq_max: float) -> tuple[np.ndarray, float]:
    """Instantes (em amostras, com fração) dos cruzamentos por zero ascendentes da FUNDAMENTAL de ``sinal``, e a
    frequência média medida por eles. O sinal é centrado e passa por um passa-baixa abaixo do 3º harmônico antes da
    detecção, para que ruído e supraharmônicos não criem cruzamentos falsos. Erro se não há uma fundamental em
    [freq_min, freq_max] (um --filtro-passa-alta acima dela, um sinal de teste sem a rede).

    É a base de :func:`recortar_ciclos_inteiros` (``--fft``) e das janelas sincronizadas do ``--bandas-iec``."""
    freq_estimada = estimar_frequencia_fundamental(sinal, fs, freq_min, freq_max)

    # Remove nível DC antes de filtrar/detectar cruzamentos: sem isso, um
    # sinal com offset residual poderia nunca cruzar o zero literal.
    sinal_centrado = sinal - np.mean(sinal)

    # Corte do passa-baixa: acima o bastante da fundamental para não
    # atenuá-la, abaixo do 3º harmônico para eliminar ruído/supraharmônicos
    # que atrapalhariam a detecção de cruzamento por zero. SOS em vez de
    # (b, a): fs/f0 é extremo aqui (dezenas de milhares para 1) e a forma
    # polinomial clássica perde precisão numérica nesse regime.
    corte = min(freq_estimada * 2.5, 0.45 * fs)
    from scipy.signal import butter, sosfiltfilt  # sob demanda: só quem calcula paga o SciPy
    sos = butter(4, corte / (fs / 2.0), btype="low", output="sos")
    sinal_filtrado = sosfiltfilt(sos, sinal_centrado)

    posicoes_cruzamento = detectar_cruzamentos_por_zero(sinal_filtrado)
    if len(posicoes_cruzamento) < 2:
        raise ErroSHAN(
            "não foi possível encontrar ciclos completos na janela "
            "selecionada. Tente aumentar --inicio/--fim."
        )

    periodo_s, _ = refinar_periodo_fundamental(posicoes_cruzamento, fs)
    f0 = 1.0 / periodo_s
    # Os cruzamentos por zero só medem a fundamental se ela existe no trecho. Sem ela (um --filtro-passa-alta acima
    # dela, um tom de teste sem 60 Hz), sobram cruzamentos de ruído e o "período" sai qualquer coisa: antes, a
    # análise seguia com f0 = 0,3 Hz e uma tabela de harmônicos sem sentido.
    if not (0.9 * freq_min <= f0 <= 1.1 * freq_max):
        raise ErroSHAN(
            f"a fundamental medida pelos cruzamentos por zero ({f0:.4g} Hz) está fora da busca "
            f"({freq_min:g} a {freq_max:g} Hz): o trecho não tem uma fundamental nesse intervalo (um "
            f"--filtro-passa-alta acima dela? um sinal de teste sem a rede?). Ajuste --freq-min/--freq-max, ou use "
            f"--welch, que não precisa de fundamental."
        )
    return posicoes_cruzamento, f0


def recortar_ciclos_inteiros(sinal: np.ndarray, fs: float, freq_min: float,
                              freq_max: float, n_ciclos_pedido: int | None):
    """Recorta 'sinal' para um número inteiro de ciclos da fundamental,
    alinhado ao primeiro cruzamento por zero ascendente. Eficaz para a
    fundamental e seus harmônicos (fase travada ao ciclo de rede); NÃO
    elimina vazamento de supraharmônicos, cuja fase é independente do ciclo
    de rede -- para esses, ver calcular_espectro_welch.

    n_ciclos_pedido: None -> todos os ciclos completos da janela; int N ->
    só os N primeiros (análise de distúrbios momentâneos), pré-truncando o
    sinal a uma estimativa generosa de amostras necessárias antes de
    filtrar/buscar cruzamentos, para não processar uma captura inteira só
    para olhar os primeiros milissegundos.

    Retorna (sinal_recortado, idx_inicio, idx_fim, f0_estimada, n_ciclos_usados).
    """
    sinal_analise = sinal
    if n_ciclos_pedido is not None and n_ciclos_pedido > 0:
        limite = estimar_amostras_para_n_ciclos(n_ciclos_pedido, fs, freq_min)
        if limite < len(sinal_analise):
            sinal_analise = sinal_analise[:limite]

    posicoes_cruzamento, f0 = cruzamentos_da_fundamental(sinal_analise, fs, freq_min, freq_max)
    n_ciclos_disponiveis = len(posicoes_cruzamento) - 1

    if n_ciclos_pedido is None or n_ciclos_pedido <= 0:
        n_ciclos_usados = n_ciclos_disponiveis
    else:
        n_ciclos_usados = min(n_ciclos_pedido, n_ciclos_disponiveis)
        if n_ciclos_pedido > n_ciclos_disponiveis:
            log.warning(
                f"--fft pediu {n_ciclos_pedido} ciclos, mas só "
                f"{n_ciclos_disponiveis} completos estão disponíveis na "
                f"janela processada. Usando {n_ciclos_usados}."
            )

    idx_inicio = int(round(posicoes_cruzamento[0]))
    idx_fim = int(round(posicoes_cruzamento[n_ciclos_usados]))
    return sinal[idx_inicio:idx_fim], idx_inicio, idx_fim, f0, n_ciclos_usados
