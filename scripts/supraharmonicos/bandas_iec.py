"""Bandas de supraharmônicos no tempo, pelo método da IEC 61000-4-7, anexo B (``--bandas-iec``).

É o método normalizado para 2 a 9 kHz, e o que a IEC 61000-4-30 (anexo C) estende até 150 kHz:

1. o sinal é cortado em janelas de 200 ms **sem lacunas** (10 ciclos a 50 Hz, 12 a 60 Hz), com janela retangular;
2. a FFT de cada janela tem bins de 5 Hz, em valor RMS;
3. cada banda de 200 Hz de centro ``b`` (2100, 2300, ... Hz) soma os bins de ``b − 95`` a ``b + 100`` Hz:
   ``Y_b = sqrt(Σ Y_f²)`` -- a banda é o intervalo (b − 100, b + 100];
4. cada banda vira uma série no tempo (um valor por janela), resumida por estatísticas: o valor RMS das janelas, o
   máximo, o percentil 95 (o "CP95" usado em limites de emissão) e o mínimo.

Por padrão a janela tem 200 ms fixos e as estatísticas são sobre as janelas de 200 ms. Duas opções EXTRAS chegam
mais perto da IEC 61000-4-30 (classe A), sem mudar esse padrão:

* **janelas sincronizadas** (``limites`` em :func:`calcular_bandas_iec`, montados por quem chama a partir dos
  cruzamentos por zero da fundamental): cada janela tem exatamente 10 ciclos (50 Hz) ou 12 ciclos (60 Hz) da rede,
  e os bins têm f0/12 Hz em vez de 5 Hz. Com a janela fixa, a rede a 60 Hz ± 0,1 Hz desalinha a janela em até
  0,2 %, e a norma admite ±0,03 %;
* **agregação** (:func:`agregar_iec`): séries de 150/180 ciclos (15 janelas, ~3 s) e de 10 min (as janelas de cada
  intervalo de 600 s a partir do início do trecho), cada valor sendo o RMS das janelas que ele reúne, como na norma.
  Os intervalos incompletos no fim são descartados. Diferença que resta: os intervalos de 10 min não são alinhados
  ao relógio UTC (00:00, 00:10...), como na classe A; contam a partir do início da captura.

Depende de: ``erros``. Só numpy (sem SciPy)."""

import math
from dataclasses import dataclass, field, replace

import numpy as np

from .erros import ErroSHAN

DURACAO_JANELA_IEC_S = 0.2
LARGURA_BANDA_IEC_HZ = 200.0
FREQ_MIN_IEC_HZ = 2000.0
_JANELAS_POR_LOTE = 64


def _estatisticas(niveis: np.ndarray) -> dict[str, np.ndarray]:
    return {
        "rms": np.sqrt(np.mean(niveis ** 2, axis=0)),
        "maximo": niveis.max(axis=0),
        "p95": np.percentile(niveis, 95, axis=0),
        "minimo": niveis.min(axis=0),
    }


@dataclass(frozen=True)
class SerieBandas:
    """Uma série agregada (3 s ou 10 min): o início de cada intervalo e o nível RMS de cada banda nele."""
    tempos_s: np.ndarray          # (n_intervalos,)
    niveis: np.ndarray            # (n_intervalos, n_bandas)
    descricao: str

    def estatisticas(self) -> dict[str, np.ndarray]:
        return _estatisticas(self.niveis)


@dataclass(frozen=True)
class BandasIEC:
    centros_hz: np.ndarray        # (n_bandas,)
    tempos_s: np.ndarray          # (n_janelas,): início de cada janela, desde o início do trecho analisado
    niveis: np.ndarray            # (n_janelas, n_bandas): RMS de cada banda em cada janela, na unidade do canal
    largura_hz: float
    duracao_janela_s: float       # duração média das janelas (exata com as fixas)
    ciclos_por_janela: int | None = None    # com as janelas sincronizadas: 10 (50 Hz) ou 12 (60 Hz)
    f0_hz: float | None = None              # a fundamental que sincronizou as janelas
    agregados: dict[str, SerieBandas] = field(default_factory=dict)   # "3s", "10min" (agregar_iec)

    @property
    def sincronizada(self) -> bool:
        return self.ciclos_por_janela is not None

    def estatisticas(self, nivel: str | None = None) -> dict[str, np.ndarray]:
        """Por banda: ``rms`` (raiz da média dos quadrados), ``maximo``, ``p95`` e ``minimo``. ``nivel``: None = as
        janelas; "3s" ou "10min" = a série agregada (se :func:`agregar_iec` a calculou)."""
        return _estatisticas(self.niveis) if nivel is None else self.agregados[nivel].estatisticas()

    def descricao_janelas(self) -> str:
        if self.sincronizada:
            return (f"{len(self.tempos_s)} janelas de {self.ciclos_por_janela} ciclos sincronizadas à fundamental "
                    f"({self.f0_hz:.4f} Hz; {self.duracao_janela_s * 1000:.3f} ms em média)")
        return f"{len(self.tempos_s)} janelas de {self.duracao_janela_s * 1000:g} ms"

    def linhas(self, unidade: str, quantas: int = 10) -> list[str]:
        """As ``quantas`` bandas de maior P95, para o console (a tabela inteira vai para --exportar)."""
        est = self.estatisticas()
        ordem = np.argsort(est["p95"])[::-1][:quantas]
        extras = [(nome, self.estatisticas(nome)) for nome in ("3s", "10min") if nome in self.agregados]
        saida = [f"Bandas IEC 61000-4-7 (anexo B): {len(self.centros_hz)} bandas de {self.largura_hz:g} Hz "
                 f"({self.centros_hz[0]:g} a {self.centros_hz[-1]:g} Hz), {self.descricao_janelas()}; "
                 f"as {len(ordem)} de maior P95:"]
        saida += [f"  agregação {nome}: {serie.descricao}" for nome, serie in self.agregados.items()]
        saida.append(f"  {'banda (Hz)':>10} {'P95':>12} {'máximo':>12} {'RMS':>12} {'mínimo':>12}"
                     + "".join(f" {'P95 ' + nome:>12}" for nome, _ in extras) + f"  ({unidade}, RMS por banda)")
        for i in ordem:
            saida.append(f"  {self.centros_hz[i]:>10g} {est['p95'][i]:>12.5g} {est['maximo'][i]:>12.5g} "
                         f"{est['rms'][i]:>12.5g} {est['minimo'][i]:>12.5g}"
                         + "".join(f" {e['p95'][i]:>12.5g}" for _, e in extras))
        return saida


def centros_das_bandas(freq_min: float, freq_max: float, largura: float) -> np.ndarray:
    """Centros ``freq_min + largura/2 + k·largura`` cuja banda inteira cabe até ``freq_max``."""
    if largura <= 0 or freq_max - freq_min < largura:
        return np.array([])
    n = int(math.floor((freq_max - freq_min) / largura + 1e-9))
    return freq_min + largura / 2.0 + largura * np.arange(n)


def calcular_bandas_iec(sinal: np.ndarray, fs: float, freq_min: float = FREQ_MIN_IEC_HZ,
                        freq_max: float | None = None, largura: float = LARGURA_BANDA_IEC_HZ,
                        duracao_janela_s: float = DURACAO_JANELA_IEC_S, limites: np.ndarray | None = None,
                        ciclos_por_janela: int | None = None, f0_hz: float | None = None) -> BandasIEC:
    """Níveis por banda em janelas consecutivas de ``duracao_janela_s`` (ver o topo do módulo).

    ``limites`` (opcional): as janelas, em amostras, como pares ``[início, fim)`` (forma ``(n_janelas, 2)``, inícios
    crescentes) -- as janelas sincronizadas à fundamental, cada uma com o seu comprimento (ver
    :func:`janelas_dos_cruzamentos`). ``ciclos_por_janela`` e ``f0_hz`` só vão para o resultado, para descrevê-lo."""
    if limites is not None:
        return _bandas_janelas_variaveis(sinal, fs, freq_min, freq_max, largura,
                                         np.asarray(limites, dtype=np.int64).reshape(-1, 2), ciclos_por_janela, f0_hz)
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


def _centros_validados(fs: float, freq_min: float, freq_max: float | None, largura: float) -> np.ndarray:
    nyquist = fs / 2.0
    freq_max = nyquist if freq_max is None else min(freq_max, nyquist)
    centros = centros_das_bandas(freq_min, freq_max, largura)
    if len(centros) == 0:
        raise ErroSHAN(f"nenhuma banda de {largura:g} Hz cabe entre {freq_min:g} e {freq_max:g} Hz "
                       f"(Nyquist do canal: {nyquist:g} Hz).")
    return centros


def _bandas_janelas_variaveis(sinal: np.ndarray, fs: float, freq_min: float, freq_max: float | None,
                              largura: float, limites: np.ndarray, ciclos_por_janela: int | None,
                              f0_hz: float | None) -> BandasIEC:
    """As janelas sincronizadas: cada uma com o seu comprimento, então cada uma tem a sua grade de bins (f0/ciclos)."""
    if (len(limites) < 1 or np.any(limites[:, 1] <= limites[:, 0]) or np.any(np.diff(limites[:, 0]) <= 0)
            or limites.min() < 0 or limites.max() > len(sinal)):
        raise ErroSHAN("janelas inválidas para as bandas IEC (precisam ter início < fim, inícios crescentes e caber "
                       "no trecho).")
    centros = _centros_validados(fs, freq_min, freq_max, largura)
    niveis = np.empty((len(limites), len(centros)))
    tolerancia = 1e-9 * fs
    for k, (a, b) in enumerate(limites):
        janela = np.asarray(sinal[a:b], dtype=np.float64)
        n = len(janela)
        freqs = np.fft.rfftfreq(n, 1.0 / fs)
        potencia = (np.abs(np.fft.rfft(janela - janela.mean())) ** 2) * (2.0 / n ** 2)
        ultimo_bin = len(freqs) - 1 if n % 2 else len(freqs) - 2
        acumulada = np.concatenate([[0.0], np.cumsum(potencia[: ultimo_bin + 1])])
        inicio = np.searchsorted(freqs[: ultimo_bin + 1], centros - largura / 2.0 + tolerancia, side="left")
        fim = np.searchsorted(freqs[: ultimo_bin + 1], centros + largura / 2.0 + tolerancia, side="left")
        niveis[k] = np.sqrt(np.maximum(acumulada[fim] - acumulada[inicio], 0.0))
    duracoes = (limites[:, 1] - limites[:, 0]) / fs
    return BandasIEC(centros, (limites[:, 0] - limites[0, 0]) / fs, niveis, largura, float(duracoes.mean()),
                     ciclos_por_janela=ciclos_por_janela, f0_hz=f0_hz)


TOLERANCIA_SINCRONISMO = 3e-4          # ±0,03 %: o erro de sincronismo que a IEC 61000-4-30 admite numa janela


def janelas_dos_cruzamentos(cruzamentos: np.ndarray, ciclos: int) -> tuple[np.ndarray, int]:
    """Janelas sem lacunas de ``ciclos`` ciclos a partir dos cruzamentos por zero da fundamental (em amostras, com
    fração), como pares ``[início, fim)`` arredondados à amostra. Descarta as janelas cujo comprimento difere em mais
    de ±0,03 % da mediana das vizinhas (até 3 de cada lado): é o que acontece na borda do trecho, onde o filtro que
    acha os cruzamentos distorce a fase, e num salto de fase ou falta de tensão, que a IEC 61000-4-30 manda sinalizar.
    Devolve ``(janelas, descartadas)``."""
    bordas = np.round(np.asarray(cruzamentos)[::ciclos]).astype(np.int64)
    if len(bordas) < 2:
        return np.empty((0, 2), dtype=np.int64), 0
    janelas = np.column_stack([bordas[:-1], bordas[1:]])
    comprimentos = (janelas[:, 1] - janelas[:, 0]).astype(float)
    boas = np.ones(len(janelas), dtype=bool)
    for k in range(len(janelas)):
        vizinhas = np.concatenate([comprimentos[max(0, k - 3):k], comprimentos[k + 1:k + 4]])
        if len(vizinhas) and abs(comprimentos[k] / np.median(vizinhas) - 1.0) > TOLERANCIA_SINCRONISMO:
            boas[k] = False
    return janelas[boas], int(np.count_nonzero(~boas))


JANELAS_POR_INTERVALO_3S = 15         # 150/180 ciclos = 15 janelas de 10/12 ciclos (IEC 61000-4-30)
INTERVALO_10MIN_S = 600.0


def ciclos_por_janela_iec(f0_hz: float) -> int:
    """10 ciclos numa rede de 50 Hz, 12 numa de 60 Hz (IEC 61000-4-30): os dois dão ~200 ms."""
    return 10 if f0_hz < 55.0 else 12


def agregar_iec(bandas: BandasIEC) -> BandasIEC:
    """Acrescenta as séries de 150/180 ciclos (~3 s) e de 10 min (IEC 61000-4-30): cada valor é o RMS das janelas
    que o intervalo reúne. Só intervalos completos; o de 10 min, só se o trecho tiver pelo menos 10 min."""
    agregados: dict[str, SerieBandas] = {}
    n = JANELAS_POR_INTERVALO_3S
    completos = len(bandas.tempos_s) // n
    if completos >= 1:
        blocos = bandas.niveis[: completos * n].reshape(completos, n, -1)
        agregados["3s"] = SerieBandas(
            bandas.tempos_s[: completos * n: n], np.sqrt(np.mean(blocos ** 2, axis=1)),
            f"{completos} intervalo(s) de {n} janelas (150/180 ciclos, ~{n * bandas.duracao_janela_s:.3g} s)")
    duracao = float(bandas.tempos_s[-1] + bandas.duracao_janela_s) if len(bandas.tempos_s) else 0.0
    intervalos = int(math.floor(duracao / INTERVALO_10MIN_S + 1e-9))
    if intervalos >= 1:
        indice = np.floor(bandas.tempos_s / INTERVALO_10MIN_S).astype(int)
        niveis = np.array([np.sqrt(np.mean(bandas.niveis[indice == i] ** 2, axis=0)) for i in range(intervalos)])
        agregados["10min"] = SerieBandas(np.arange(intervalos) * INTERVALO_10MIN_S, niveis,
                                         f"{intervalos} intervalo(s) de 10 min a partir do início do trecho")
    return replace(bandas, agregados=agregados)
