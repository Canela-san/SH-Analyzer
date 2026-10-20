"""Bandas de supraharmônicos no tempo, pelo método da IEC 61000-4-7, anexo B (``--bandas-iec``).

É o método normalizado para 2 a 9 kHz, e o que a IEC 61000-4-30 (anexo C) estende até 150 kHz:

1. o sinal é cortado em janelas de 200 ms **sem lacunas** (10 ciclos a 50 Hz, 12 a 60 Hz), com janela retangular;
2. a FFT de cada janela tem bins de 5 Hz, em valor RMS;
3. cada banda de 200 Hz de centro ``b`` (2100, 2300, ... Hz) soma os bins de ``b − 95`` a ``b + 100`` Hz:
   ``Y_b = sqrt(Σ Y_f²)`` -- a banda é o intervalo (b − 100, b + 100];
4. cada banda vira uma série no tempo (um valor por janela), resumida por estatísticas: o valor RMS das janelas, o
   máximo, o percentil 95 (o "CP95" usado em limites de emissão) e o mínimo.

Diferenças em relação à norma, a declarar num relatório: a janela tem 200 ms fixos, não sincronizada à fundamental
(a norma admite ±0,03 % de erro de sincronismo; com a rede a 60 Hz ± 0,1 Hz, a diferença é de até 0,2 %), e a
agregação em 3 s/10 min da IEC 61000-4-30 não é feita (as estatísticas são sobre a captura inteira; a série completa
sai em ``--exportar``).

Depende de: ``erros``. Só numpy (sem SciPy)."""

import math
from dataclasses import dataclass

import numpy as np

from .erros import ErroSHAN

DURACAO_JANELA_IEC_S = 0.2
LARGURA_BANDA_IEC_HZ = 200.0
FREQ_MIN_IEC_HZ = 2000.0
_JANELAS_POR_LOTE = 64


@dataclass(frozen=True)
class BandasIEC:
    centros_hz: np.ndarray        # (n_bandas,)
    tempos_s: np.ndarray          # (n_janelas,): início de cada janela, desde o início do trecho analisado
    niveis: np.ndarray            # (n_janelas, n_bandas): RMS de cada banda em cada janela, na unidade do canal
    largura_hz: float
    duracao_janela_s: float

    def estatisticas(self) -> dict[str, np.ndarray]:
        """Por banda: ``rms`` (raiz da média dos quadrados das janelas), ``maximo``, ``p95`` e ``minimo``."""
        return {
            "rms": np.sqrt(np.mean(self.niveis ** 2, axis=0)),
            "maximo": self.niveis.max(axis=0),
            "p95": np.percentile(self.niveis, 95, axis=0),
            "minimo": self.niveis.min(axis=0),
        }

    def linhas(self, unidade: str, quantas: int = 10) -> list[str]:
        """As ``quantas`` bandas de maior P95, para o console (a tabela inteira vai para --exportar)."""
        est = self.estatisticas()
        ordem = np.argsort(est["p95"])[::-1][:quantas]
        saida = [f"Bandas IEC 61000-4-7 (anexo B): {len(self.centros_hz)} bandas de {self.largura_hz:g} Hz "
                 f"({self.centros_hz[0]:g} a {self.centros_hz[-1]:g} Hz), {len(self.tempos_s)} janelas de "
                 f"{self.duracao_janela_s * 1000:g} ms; as {len(ordem)} de maior P95:",
                 f"  {'banda (Hz)':>10} {'P95':>12} {'máximo':>12} {'RMS':>12} {'mínimo':>12}  ({unidade}, RMS por banda)"]
        for i in ordem:
            saida.append(f"  {self.centros_hz[i]:>10g} {est['p95'][i]:>12.5g} {est['maximo'][i]:>12.5g} "
                         f"{est['rms'][i]:>12.5g} {est['minimo'][i]:>12.5g}")
        return saida


def centros_das_bandas(freq_min: float, freq_max: float, largura: float) -> np.ndarray:
    """Centros ``freq_min + largura/2 + k·largura`` cuja banda inteira cabe até ``freq_max``."""
    if largura <= 0 or freq_max - freq_min < largura:
        return np.array([])
    n = int(math.floor((freq_max - freq_min) / largura + 1e-9))
    return freq_min + largura / 2.0 + largura * np.arange(n)


def calcular_bandas_iec(sinal: np.ndarray, fs: float, freq_min: float = FREQ_MIN_IEC_HZ,
                        freq_max: float | None = None, largura: float = LARGURA_BANDA_IEC_HZ,
                        duracao_janela_s: float = DURACAO_JANELA_IEC_S) -> BandasIEC:
    """Níveis por banda em janelas consecutivas de ``duracao_janela_s`` (ver o topo do módulo)."""
    n_janela = int(round(fs * duracao_janela_s))
    n_janelas = len(sinal) // n_janela if n_janela > 0 else 0
    if n_janelas < 1:
        raise ErroSHAN(f"--bandas-iec precisa de pelo menos uma janela de {duracao_janela_s * 1000:g} ms "
                       f"({n_janela} amostras por canal); o trecho tem {len(sinal)}.")
    nyquist = fs / 2.0
    freq_max = nyquist if freq_max is None else min(freq_max, nyquist)
    centros = centros_das_bandas(freq_min, freq_max, largura)
    if len(centros) == 0:
        raise ErroSHAN(f"nenhuma banda de {largura:g} Hz cabe entre {freq_min:g} e {freq_max:g} Hz "
                       f"(Nyquist do canal: {nyquist:g} Hz).")
    freqs = np.fft.rfftfreq(n_janela, 1.0 / fs)
    # Bins de cada banda: (centro − largura/2, centro + largura/2]. Com somas acumuladas, cada banda é uma diferença.
    tolerancia = 1e-9 * fs
    inicio = np.searchsorted(freqs, centros - largura / 2.0 + tolerancia, side="left")
    fim = np.searchsorted(freqs, centros + largura / 2.0 + tolerancia, side="left")
    ultimo_bin = len(freqs) - 1 if n_janela % 2 else len(freqs) - 2
    fim = np.minimum(fim, ultimo_bin + 1)

    niveis = np.empty((n_janelas, len(centros)))
    blocos = np.asarray(sinal[: n_janelas * n_janela], dtype=np.float64).reshape(n_janelas, n_janela)
    for a in range(0, n_janelas, _JANELAS_POR_LOTE):
        lote = blocos[a:a + _JANELAS_POR_LOTE]
        espectro = np.fft.rfft(lote - lote.mean(axis=1, keepdims=True), axis=1)
        potencia = (np.abs(espectro) ** 2) * (2.0 / n_janela ** 2)          # RMS² de cada bin
        acumulada = np.concatenate([np.zeros((len(lote), 1)), np.cumsum(potencia, axis=1)], axis=1)
        niveis[a:a + len(lote)] = np.sqrt(np.maximum(acumulada[:, fim] - acumulada[:, inicio], 0.0))
    tempos = np.arange(n_janelas) * (n_janela / fs)
    return BandasIEC(centros, tempos, niveis, largura, n_janela / fs)
