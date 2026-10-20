"""Tabela de harmônicos de um trecho com número inteiro de ciclos da fundamental (``--harmonicos``).

Com o trecho recortado em ``n`` ciclos inteiros (``fundamental.recortar_ciclos_inteiros``), a FFT retangular põe a
fundamental exatamente no bin ``n`` e o harmônico ``h`` no bin ``h·n``: sem vazamento entre harmônicos, como na
IEC 61000-4-7 (que usa 10 ou 12 ciclos). Para cada ordem a tabela dá:

* a **componente** (o bin do harmônico), em valor RMS;
* o **grupo harmônico** da IEC 61000-4-7, que soma também o conteúdo entre harmônicos até a metade do caminho para
  os vizinhos (os bins das bordas, compartilhados por dois grupos, entram com metade da potência) -- é o que a norma
  manda usar quando há inter-harmônicos ou a frequência varia;
* a porcentagem da fundamental e a **fase relativa à fundamental**, no referencial seno usual em sistemas de
  potência: ``v(t) = Σ √2·V_h·sin(h·ω·t + θ_h)`` com ``θ_1 = 0``. É ``θ_h − h·θ_1``, que não depende de onde o
  trecho começa. (Um 3º harmônico "em fase" com a fundamental, ``sin(3ωt)`` junto de ``sin(ωt)``, dá 0°.)

THD (componentes) e THDG (grupos) usam as ordens 2 até a última calculada.

Depende de: ``erros``. Só numpy (sem SciPy)."""

import math
from dataclasses import dataclass

import numpy as np

from .erros import ErroSHAN


@dataclass(frozen=True)
class Harmonico:
    ordem: int
    frequencia_hz: float
    rms: float                 # componente: o bin do harmônico, em valor RMS (unidade do canal)
    rms_grupo: float           # grupo harmônico (IEC 61000-4-7)
    pct_fundamental: float     # componente ÷ componente da fundamental, em %
    fase_graus: float          # θh − h·θ1 no referencial seno, em (−180, 180]; a da fundamental é 0 por definição


@dataclass(frozen=True)
class TabelaHarmonicos:
    f0_hz: float
    n_ciclos: int
    harmonicos: list[Harmonico]   # ordem 1 até a última abaixo de Nyquist (ou a pedida)
    thd_pct: float
    thdg_pct: float
    rms_total: float              # RMS do trecho inteiro, sem DC (inclui tudo: harmônicos, inter-harmônicos, ruído)

    def linhas(self, unidade: str) -> list[str]:
        """A tabela pronta para o console."""
        saida = [f"Harmônicos (f0 = {self.f0_hz:.4f} Hz, {self.n_ciclos} ciclos, janela retangular síncrona):",
                 f"  {'h':>3} {'f (Hz)':>11} {'RMS (' + unidade + ')':>14} {'grupo (' + unidade + ')':>15} "
                 f"{'% h1':>9} {'fase (°)':>9}"]
        for h in self.harmonicos:
            saida.append(f"  {h.ordem:>3} {h.frequencia_hz:>11.3f} {h.rms:>14.6g} {h.rms_grupo:>15.6g} "
                         f"{h.pct_fundamental:>9.4f} {h.fase_graus:>9.2f}")
        saida.append(f"  THD (componentes) = {self.thd_pct:.4f} % | THDG (grupos, IEC 61000-4-7) = {self.thdg_pct:.4f} % "
                     f"| RMS total (sem DC) = {self.rms_total:.6g} {unidade}")
        return saida


def _fase_relativa(fase_h: float, fase_1: float, ordem: int) -> float:
    """``fase_h``/``fase_1``: ângulos da FFT (referencial cosseno). No referencial seno cada um soma 90°, então
    θh − h·θ1 = φh − h·φ1 − (h − 1)·90°."""
    graus = math.degrees(fase_h - ordem * fase_1) - (ordem - 1) * 90.0
    graus = (graus + 180.0) % 360.0 - 180.0
    return 180.0 if graus == -180.0 else graus


def calcular_harmonicos(trecho: np.ndarray, fs: float, f0_hz: float, n_ciclos: int,
                        ordem_maxima: int) -> TabelaHarmonicos:
    """Harmônicos 1..``ordem_maxima`` de ``trecho`` (``n_ciclos`` ciclos inteiros de ``f0_hz``, amostrado a ``fs``).
    Ordens acima de Nyquist são omitidas."""
    if n_ciclos < 1:
        raise ErroSHAN("a tabela de harmônicos precisa de pelo menos 1 ciclo completo da fundamental.")
    if ordem_maxima < 1:
        raise ErroSHAN("--harmonicos precisa ser >= 1.")
    n = len(trecho)
    x = np.asarray(trecho, dtype=np.float64)
    x = x - x.mean()
    espectro = np.fft.rfft(x)
    rms_bin = np.abs(espectro) * math.sqrt(2.0) / n       # RMS de um tom que cai exatamente no bin
    potencia = rms_bin ** 2
    ultimo_bin = len(espectro) - 1 if n % 2 else len(espectro) - 2     # o de Nyquist não tem par: fora

    meio = n_ciclos / 2.0
    harmonicos: list[Harmonico] = []
    fase_1 = float(np.angle(espectro[n_ciclos]))
    rms_1 = float(rms_bin[n_ciclos])
    if rms_1 <= 0.0:
        raise ErroSHAN("a fundamental tem amplitude zero no trecho: confira --freq-min/--freq-max.")
    for ordem in range(1, ordem_maxima + 1):
        k = ordem * n_ciclos
        if k > ultimo_bin:
            break
        # Grupo: bins a menos de meio espaçamento (n_ciclos/2 bins) do harmônico; os que ficam exatamente na metade
        # (n_ciclos par) pertencem a dois grupos e entram com metade da potência, como na IEC 61000-4-7.
        lo, hi = max(1, k - int(math.floor(meio))), min(ultimo_bin, k + int(math.floor(meio)))
        soma = float(np.sum(potencia[lo:hi + 1]))
        if n_ciclos % 2 == 0:
            for borda in (k - int(meio), k + int(meio)):
                if lo <= borda <= hi:
                    soma -= 0.5 * float(potencia[borda])
        rms = float(rms_bin[k])
        harmonicos.append(Harmonico(
            ordem=ordem, frequencia_hz=ordem * f0_hz, rms=rms, rms_grupo=math.sqrt(max(soma, 0.0)),
            pct_fundamental=100.0 * rms / rms_1,
            fase_graus=0.0 if ordem == 1 else _fase_relativa(float(np.angle(espectro[k])), fase_1, ordem),
        ))
    distorcao = [h for h in harmonicos if h.ordem >= 2]
    thd = 100.0 * math.sqrt(sum(h.rms ** 2 for h in distorcao)) / rms_1
    grupo_1 = harmonicos[0].rms_grupo
    thdg = 100.0 * math.sqrt(sum(h.rms_grupo ** 2 for h in distorcao)) / grupo_1 if grupo_1 > 0 else math.nan
    return TabelaHarmonicos(f0_hz=f0_hz, n_ciclos=n_ciclos, harmonicos=harmonicos, thd_pct=thd, thdg_pct=thdg,
                            rms_total=float(np.sqrt(np.mean(x ** 2))))
