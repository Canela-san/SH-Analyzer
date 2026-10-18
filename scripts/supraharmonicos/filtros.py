"""Filtragem digital Butterworth (SOS + ``sosfiltfilt``, fase zero).

Depende de: ``erros``."""


import numpy as np
from scipy.signal import butter, sosfiltfilt

from .erros import ErroSHAN

# ---------------------------------------------------------------------------
# 3. Filtragem digital opcional (Butterworth, SOS + sosfiltfilt)
# ---------------------------------------------------------------------------

def validar_corte_filtro(corte: float, fs: float, nome_flag: str) -> None:
    """Valida contra a Nyquist EFETIVA do canal (fs já é por canal, não a
    frequência total de --frequencia). Chamada antes de carregar o arquivo,
    que pode ser grande."""
    nyquist = fs / 2.0
    if corte <= 0:
        raise ErroSHAN(f"{nome_flag} precisa ser positivo (recebido: {corte:g} Hz).")
    if corte >= nyquist:
        raise ErroSHAN(
            f"{nome_flag}={corte:g} Hz precisa ser menor que a Nyquist "
            f"efetiva ({nyquist:g} Hz = {fs:g} Hz / 2)."
        )


def aplicar_filtro_digital(sinal: np.ndarray, fs: float, tipo: str,
                            corte: float, ordem: int) -> np.ndarray:
    """Butterworth em SOS (não a forma clássica (b, a)): nas ordens mais
    altas aceitas aqui (4-8), (b, a) perde precisão numérica; SOS decompõe em
    seções de 2ª ordem bem condicionadas. sosfiltfilt filtra para frente e
    para trás (fase zero) -- um atraso de fase deslocaria os cruzamentos por
    zero usados no corte em ciclos inteiros e distorceria a forma de onda no
    tempo, ao custo de dobrar a ordem efetiva (magnitude ao quadrado)."""
    nyquist = fs / 2.0
    sos = butter(ordem, corte / nyquist, btype=tipo, output="sos")
    try:
        return sosfiltfilt(sos, sinal)
    except ValueError as e:
        rotulo = "passa-baixa" if tipo == "low" else "passa-alta"
        raise ErroSHAN(
            f"falha ao aplicar o filtro {rotulo} (corte {corte:g} Hz, ordem "
            f"{ordem}): {e}. A janela selecionada provavelmente tem poucas "
            f"amostras para essa ordem -- aumente a janela ou reduza "
            f"--ordem-filtro."
        ) from e
