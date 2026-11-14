"""Filtragem digital Butterworth (SOS + ``sosfiltfilt``, fase zero).

Depende de: ``erros``."""


import numpy as np

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


ROTULOS_FILTRO = {"low": "passa-baixa", "high": "passa-alta", "bandpass": "passa-faixa", "bandstop": "rejeita-faixa"}


def projetar_filtro_sos(fs: float, tipo: str, corte, ordem: int) -> np.ndarray:
    """O Butterworth em seções de 2ª ordem: ``tipo`` 'low' ou 'high' com um corte, 'bandpass' ou 'bandstop' com dois
    (``(inferior, superior)``), em Hz. As faixas têm o dobro de polos: a ordem vale para cada borda."""
    from scipy.signal import butter  # sob demanda: só quem calcula paga o SciPy
    return butter(ordem, np.asarray(corte, dtype=float) / (fs / 2.0), btype=tipo, output="sos")


def _descrever_corte(corte) -> str:
    return " a ".join(f"{c:g}" for c in np.atleast_1d(np.asarray(corte, dtype=float))) + " Hz"


def aplicar_filtro_digital(sinal: np.ndarray, fs: float, tipo: str,
                            corte, ordem: int) -> np.ndarray:
    """Butterworth em SOS (não a forma clássica (b, a)): nas ordens mais
    altas aceitas aqui (4-8), (b, a) perde precisão numérica; SOS decompõe em
    seções de 2ª ordem bem condicionadas. sosfiltfilt filtra para frente e
    para trás (fase zero) -- um atraso de fase deslocaria os cruzamentos por
    zero usados no corte em ciclos inteiros e distorceria a forma de onda no
    tempo, ao custo de dobrar a ordem efetiva (magnitude ao quadrado).

    ``tipo`` e ``corte``: ver :func:`projetar_filtro_sos` (a CLI usa só 'low' e 'high')."""
    from scipy.signal import sosfiltfilt  # sob demanda: só quem calcula paga o SciPy
    sos = projetar_filtro_sos(fs, tipo, corte, ordem)
    try:
        return sosfiltfilt(sos, sinal)
    except ValueError as e:
        raise ErroSHAN(
            f"falha ao aplicar o filtro {ROTULOS_FILTRO.get(tipo, tipo)} (corte {_descrever_corte(corte)}, ordem "
            f"{ordem}): {e}. A janela selecionada provavelmente tem poucas "
            f"amostras para essa ordem -- aumente a janela ou reduza "
            f"--ordem-filtro."
        ) from e
