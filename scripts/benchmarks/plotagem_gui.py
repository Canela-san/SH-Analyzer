"""As medidas que decidiram o motor de gráficos da interface (docs/gui-plan.md, seção 6.2).

Mede, sem tela (``QT_QPA_PLATFORM=offscreen``, o QPainter raster de uma janela normal), numa área de 1600 x 900 px:

* ``piramide``    a pirâmide mín/máx: construção e consulta de uma janela qualquer em 1600 colunas;
* ``matplotlib``  o Matplotlib (Agg) redesenhando 1 M e 10 M pontos, e 8 traços já reduzidos;
* ``pyqtgraph``   o PyQtGraph com 1 M pontos crus e com 10 M pontos pela redução dele (``peak``);
* ``banda``       8 traços pela pirâmide: a banda mín/máx como linha em zigue-zague x como polígono preenchido;
* ``espessura``   o custo do antialiasing e da linha de 1,5 px, de longe (banda cheia) e de perto (ciclos visíveis).

Uso (da raiz do repositório)::

    uv run --extra gui python scripts/benchmarks/plotagem_gui.py              # tudo, menos o caso de ~100 s
    uv run --extra gui python scripts/benchmarks/plotagem_gui.py banda espessura --lento

O sinal sintético (100 M amostras int16, 200 MB: 60 Hz com supraharmônicos na metade negativa e ruído) é gerado
uma vez na pasta temporária do sistema e reaproveitado.
"""

import argparse
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

FS = 400_000
N = 100_000_000
LARGURA, ALTURA = 1600, 900
ARQ = Path(tempfile.gettempdir()) / "sh-analyzer-benchmark-sinal.i16"
FATOR0, FATOR = 32, 8
CORES = ["#7dd3fc", "#fbbf24", "#fb7185", "#818cf8", "#34d399", "#e879f9", "#7dd3fc", "#fbbf24"]


def escrever(texto=""):
    sys.stdout.write(texto + "\n")
    sys.stdout.flush()


def cronometrar(f, repeticoes=5, limite_s=5.0):
    """Mediana de ``repeticoes`` chamadas; para antes se uma chamada passar de ``limite_s``."""
    tempos = []
    for _ in range(repeticoes):
        t = time.perf_counter()
        f()
        tempos.append(time.perf_counter() - t)
        if tempos[-1] > limite_s:
            break
    return statistics.median(tempos)


def sinal():
    if not (ARQ.exists() and ARQ.stat().st_size == 2 * N):
        escrever(f"gerando o sinal sintético em {ARQ} ({2 * N / 1e6:.0f} MB)...")
        rng = np.random.default_rng(1)
        with open(ARQ, "wb") as f:
            for i in range(0, N, 10_000_000):
                t = np.arange(i, i + 10_000_000) / FS
                fase = np.sin(2 * np.pi * 60 * t)
                y = 20000 * fase + 600 * np.sin(2 * np.pi * 20_000 * t) * (fase < 0) + rng.normal(0, 40, len(t))
                f.write(y.astype(np.int16).tobytes())
    return np.memmap(ARQ, dtype=np.int16, mode="r")


def construir_piramide(x):
    """Níveis (bloco, mín, máx): o 0 com blocos de 32 amostras, cada seguinte agrupando 8 do anterior."""
    n0 = len(x) // FATOR0
    mn, mx = np.empty(n0, np.int16), np.empty(n0, np.int16)
    passo = FATOR0 * 1_000_000
    for i in range(0, n0 * FATOR0, passo):
        trecho = np.asarray(x[i:min(i + passo, n0 * FATOR0)]).reshape(-1, FATOR0)
        j = i // FATOR0
        mn[j:j + len(trecho)], mx[j:j + len(trecho)] = trecho.min(axis=1), trecho.max(axis=1)
    niveis = [(FATOR0, mn, mx)]
    while len(mn) >= 2 * FATOR:
        n = len(mn) // FATOR
        mn = mn[:n * FATOR].reshape(-1, FATOR).min(axis=1)
        mx = mx[:n * FATOR].reshape(-1, FATOR).max(axis=1)
        niveis.append((niveis[-1][0] * FATOR, mn, mx))
    return niveis


def consultar(x, niveis, i0, i1, colunas=LARGURA):
    """Mín e máx por coluna de pixel das amostras [i0, i1): (xs, ys), 2 pontos por coluna (mín, máx)."""
    if (i1 - i0) / colunas <= 2:
        return np.arange(i0, i1), np.asarray(x[i0:i1], dtype=np.float32)
    bloco, mnv, mxv = 1, np.asarray(x[i0:i1]), np.asarray(x[i0:i1])
    for b, mn, mx in niveis:
        if b <= (i1 - i0) / colunas / 2:
            bloco, mnv, mxv = b, mn[i0 // b:i1 // b], mx[i0 // b:i1 // b]
    bordas = np.linspace(0, len(mnv), colunas + 1).astype(np.int64)[:-1]
    ys = np.empty(2 * colunas, np.float32)
    ys[0::2], ys[1::2] = np.minimum.reduceat(mnv, bordas), np.maximum.reduceat(mxv, bordas)
    return np.repeat(i0 + bordas * bloco, 2), ys


def parte_piramide(x, niveis, t_construcao):
    extra = sum(mn.nbytes + mx.nbytes for _, mn, mx in niveis)
    escrever(f"\n[pirâmide] construção: {t_construcao:.2f} s ({len(x) / t_construcao / 1e6:.0f} M amostras/s), "
             f"{len(niveis)} níveis, +{extra / 1e6:.1f} MB ({100 * extra / x.nbytes:.1f} %)")
    for span in (len(x), 10_000_000, 1_000_000, 100_000, 5_000):
        i0 = (len(x) - span) // 2
        t = cronometrar(lambda i0=i0, span=span: consultar(x, niveis, i0, i0 + span), 20)
        escrever(f"  consulta de {span:>11,} amostras -> {LARGURA} colunas: {t * 1e3:7.2f} ms")


def parte_matplotlib(x, niveis):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    escrever("\n[matplotlib Agg] redesenhar a figura (path.simplify ligado)")
    for n in (1_000_000, 10_000_000):
        fig, ax = plt.subplots(figsize=(LARGURA / 100, ALTURA / 100), dpi=100)
        ax.plot(np.arange(n), np.asarray(x[:n], dtype=np.float32), lw=1)
        fig.canvas.draw()
        t = cronometrar(fig.canvas.draw, 3 if n <= 1_000_000 else 1)
        escrever(f"  1 traço de {n:>11,} pontos: {t * 1e3:8.1f} ms ({1 / t:5.1f} q/s)")
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(LARGURA / 100, ALTURA / 100), dpi=100)
    for k in range(8):
        xs, ys = consultar(x, niveis, 0, len(x))
        ax.plot(xs, ys + k * 5000, lw=1)
    fig.canvas.draw()
    t = cronometrar(fig.canvas.draw, 3)
    escrever(f"  8 traços x {2 * LARGURA} pontos (pela pirâmide, banda cheia): {t * 1e3:.1f} ms")
    plt.close(fig)


def janela(app, antialias):
    import pyqtgraph as pg
    pg.setConfigOptions(antialias=antialias, background="#0c1526", foreground="#9fb0c8")
    w = pg.PlotWidget()
    w.resize(LARGURA, ALTURA)
    w.show()
    app.processEvents()
    return w


def parte_pyqtgraph(app, x):
    import pyqtgraph as pg
    escrever(f"\n[pyqtgraph {pg.__version__}] pintar a janela (grab)")
    for n, reduzir in ((1_000_000, False), (10_000_000, True)):
        w = janela(app, False)
        item = w.plot(np.arange(n, dtype=np.float64), np.asarray(x[:n], dtype=np.float32), pen=pg.mkPen(CORES[0], width=1))
        if reduzir:
            item.setDownsampling(auto=True, method="peak")
            item.setClipToView(True)
        w.grab()
        t = cronometrar(w.grab, 3)
        escrever(f"  1 traço de {n:>11,} pontos ({'redução peak + clipToView' if reduzir else 'crus'}): {t * 1e3:8.1f} ms")
        w.close()


def montar_bandas(app, x, niveis, span, modo, antialias, espessura):
    import pyqtgraph as pg
    w = janela(app, antialias)
    colunas = np.arange(LARGURA, dtype=np.float64)
    for k in range(8):
        i0 = (len(x) - span) // 2
        _, ys = consultar(x, niveis, i0, i0 + span)
        mn, mx = ys[0::2] + k * 5000, ys[1::2] + k * 5000
        caneta = pg.mkPen(CORES[k], width=espessura)
        if modo == "poligono":
            c1, c2 = pg.PlotCurveItem(colunas, mn, pen=caneta), pg.PlotCurveItem(colunas, mx, pen=caneta)
            for item in (c1, c2, pg.FillBetweenItem(c1, c2, brush=pg.mkBrush(CORES[k]))):
                w.addItem(item)
        else:
            zz = np.empty(2 * LARGURA)
            zz[0::2], zz[1::2] = mn, mx
            w.plot(np.repeat(colunas, 2), zz, pen=caneta)
    w.grab()
    return w


def parte_bandas(app, x, niveis, casos):
    for span, nome in ((len(x), "banda cheia (a captura inteira)"), (40_000, "ciclos visíveis (100 ms)")):
        escrever(f"\n[{nome}] 8 traços, {span:,} amostras em {LARGURA} colunas")
        for rotulo, modo, aa, esp in casos:
            w = montar_bandas(app, x, niveis, span, modo, aa, esp)
            t = cronometrar(w.grab, 5, limite_s=2.0)
            escrever(f"  {rotulo:48} {t * 1e3:10.1f} ms por quadro")
            w.close()


def main(argv=None):
    partes = ("piramide", "matplotlib", "pyqtgraph", "banda", "espessura")
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("partes", nargs="*", choices=partes, help="o que medir (padrão: tudo)")
    p.add_argument("--lento", action="store_true", help="inclui a linha de 1,5 px com antialiasing na banda cheia (~100 s)")
    a = p.parse_args(argv)
    pedidas = a.partes or partes
    x = sinal()
    escrever(f"sinal: {len(x) / 1e6:.0f} M amostras ({len(x) / FS:.0f} s a 400 kS/s); área de {LARGURA} x {ALTURA} px")
    t = time.perf_counter()
    niveis = construir_piramide(x)
    t_construcao = time.perf_counter() - t
    if "piramide" in pedidas:
        parte_piramide(x, niveis, t_construcao)
    if "matplotlib" in pedidas:
        parte_matplotlib(x, niveis)
    if not {"pyqtgraph", "banda", "espessura"} & set(pedidas):
        return 0
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    if "pyqtgraph" in pedidas:
        parte_pyqtgraph(app, x)
    if "banda" in pedidas:
        parte_bandas(app, x, niveis, [("linha em zigue-zague, 1 px, sem antialiasing", "linha", False, 1),
                                      ("polígono preenchido, contorno de 1 px", "poligono", False, 1)])
    if "espessura" in pedidas:
        casos = [("polígono, antialiasing, contorno de 1 px", "poligono", True, 1),
                 ("linha de 1 px, antialiasing", "linha", True, 1),
                 ("linha de 1,5 px, sem antialiasing", "linha", False, 1.5)]
        if a.lento:
            casos.append(("linha de 1,5 px, antialiasing (lento)", "linha", True, 1.5))
        parte_bandas(app, x, niveis, casos)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
