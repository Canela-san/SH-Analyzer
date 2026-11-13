"""Protótipo: navegar uma captura inteira pelo ``TracoLOD`` (F0.5 em docs/gui-progress.md).

Abre um ``.bin`` (ou gera um sinal sintético de N minutos), constrói as pirâmides em segundo plano (com o cache em
disco: a segunda abertura é instantânea) e mostra cada canal numa faixa, com o tempo ligado entre as faixas. Roda do
mouse = zoom, arrastar = pan, botão direito = menu do PyQtGraph. A barra de status mostra os quadros por segundo.

Uso (da raiz do repositório)::

    uv run --extra gui python -m sh_analyzer_gui.prototipos.navegar CAPTURA.bin
    uv run --extra gui python -m sh_analyzer_gui.prototipos.navegar --sintetico 60 --canais 2
    uv run --extra gui python -m sh_analyzer_gui.prototipos.navegar --sintetico 60 --medir     # portões G1/G2

``--medir`` percorre um zoom da captura inteira até poucas amostras e de volta (pan incluso), pintando cada quadro
de forma síncrona, e escreve a mediana e o p95 do tempo por quadro: o portão G1 do plano (p95 <= 16 ms) numa tela de
verdade, e o G2 se a tela for 4K com escala de 200 %.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

CORES = ["#7dd3fc", "#fbbf24", "#fb7185", "#818cf8", "#34d399", "#e879f9"]   # a paleta do plano, seção 12.3
FUNDO, EIXO = "#0c1526", "#9fb0c8"


@dataclass
class CanalProto:
    nome: str
    amostras: np.ndarray
    taxa_hz: float
    escala: float = 1.0
    deslocamento: float = 0.0


@dataclass
class FonteProto:
    nome: str
    amostras: np.ndarray       # todas, intercaladas
    n_canais: int
    canais: list[CanalProto]
    chave: str


def gerar_sintetico(minutos: float, n_canais: int, taxa_total: int = 400_000) -> FonteProto:
    """Um .bin sem cabeçalho na pasta temporária (reaproveitado): 60 Hz com supraharmônicos na metade negativa, um
    afundamento, degraus de carga e ruído, em ``int16``. Gerado em blocos (cabe em qualquer memória)."""
    taxa = taxa_total / n_canais
    n = int(minutos * 60 * taxa)
    caminho = Path(tempfile.gettempdir()) / f"sh-analyzer-sintetico-{minutos:g}min-{n_canais}c.i16"
    if not (caminho.exists() and caminho.stat().st_size == 2 * n * n_canais):
        sys.stderr.write(f"gerando {caminho} ({2 * n * n_canais / 1e9:.2f} GB)...\n")
        rng = np.random.default_rng(1)
        with open(caminho, "wb") as f:
            for i in range(0, n, 4_000_000):
                t = np.arange(i, min(i + 4_000_000, n)) / taxa
                fase = np.sin(2 * np.pi * 60 * t)
                quadros = np.empty((len(t), n_canais), np.int16)
                for c in range(n_canais):
                    amp = 20_000 * (1 + 0.05 * np.sin(2 * np.pi * t / 300) - 0.3 * ((t % 600) > 590)) / (1 + 0.3 * c)
                    y = amp * np.sin(2 * np.pi * 60 * t - 0.4 * c) + 500 * np.sin(2 * np.pi * 20_000 * t) * (fase < 0)
                    quadros[:, c] = np.clip(y + rng.normal(0, 40, len(t)), -32768, 32767)
                f.write(quadros.tobytes())
    amostras = np.memmap(caminho, dtype=np.int16, mode="r")
    canais = [CanalProto(f"canal {c}", amostras[c::n_canais] if n_canais > 1 else amostras, taxa, 20.48 / 65536)
              for c in range(n_canais)]
    return FonteProto(caminho.name, amostras, n_canais, canais, f"sintetico-{minutos:g}-{n_canais}")


def abrir(caminho: Path) -> FonteProto:
    from ..dados.captura import abrir_fonte
    fonte = abrir_fonte(caminho)
    canais = [CanalProto(f"canal {c.numero} · {c.nome_grandeza}", c.amostras, c.taxa_hz, c.escala, c.deslocamento)
              for c in fonte.canais]
    return FonteProto(fonte.nome, fonte.captura.amostras, len(canais), canais, fonte.chave)


def montar_faixas(layout, fonte: FonteProto, piramides) -> list:
    """Uma faixa (``PlotItem``) por canal no ``pg.GraphicsLayoutWidget``, com o tempo ligado e um ``TracoLOD`` em cada."""
    from ..graficos.traco_lod import TracoLOD

    tracos, primeiro = [], None
    for i, (canal, piramide) in enumerate(zip(fonte.canais, piramides)):
        item = layout.addPlot(row=i, col=0)
        # Sem a grade do PyQtGraph: semitransparente, ela custava ~17 ms por quadro. A grade própria, opaca, vem com o
        # tema (F0.8) e as vistas (Fase 1). Rótulos sem "units" e sem prefixo automático: com eles, o PyQtGraph
        # refaz o HTML do rótulo a cada quadro.
        for lado in ("left", "bottom"):
            item.getAxis(lado).enableAutoSIPrefix(False)
        item.setLabel("left", f"{canal.nome} (V)")
        if i == len(fonte.canais) - 1:
            item.setLabel("bottom", "tempo (s)")
        else:
            item.hideAxis("bottom")        # o tempo é um só (as faixas estão ligadas): o eixo fica só na última
        traco = TracoLOD(piramide, canal.amostras, canal.taxa_hz, escala=canal.escala,
                         deslocamento=canal.deslocamento, cor=CORES[i % len(CORES)], nome=canal.nome)
        item.addItem(traco)
        if primeiro is None:
            primeiro = item
        else:
            item.setXLink(primeiro)
        tracos.append(traco)
    return tracos


def percorrer_zoom(app, widget, traco, n_amostras: int, taxa_hz: float) -> list[float]:
    """O percurso dos portões G1/G2: zoom da captura inteira até ~50 amostras e de volta, com pan junto, pintando cada
    quadro de forma síncrona. Devolve o tempo de cada quadro (s): as consultas agendadas + a pintura inteira."""
    vb = traco.getViewBox()
    janelas = [n_amostras / 1.35 ** k for k in range(0, 60) if n_amostras / 1.35 ** k > 50]
    janelas += janelas[::-1]
    tempos = []
    for k, largura in enumerate(janelas):
        centro = n_amostras * (0.3 + 0.4 * k / len(janelas))
        t = time.perf_counter()
        vb.setXRange((centro - largura / 2) / taxa_hz, (centro + largura / 2) / taxa_hz, padding=0)
        app.processEvents()                                 # as consultas agendadas
        widget.repaint()                                    # a pintura, síncrona
        tempos.append(time.perf_counter() - t)
    return tempos


def resumo_dos_quadros(tempos: list[float]) -> tuple[float, float]:
    """A mediana e o p95 do tempo por quadro (s)."""
    ordenados = sorted(tempos)
    return statistics.median(ordenados), ordenados[int(0.95 * (len(ordenados) - 1))]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("arquivo", nargs="?", type=Path, help="uma captura .bin com cabeçalho")
    p.add_argument("--sintetico", type=float, metavar="MINUTOS", help="gera um sinal sintético desta duração")
    p.add_argument("--canais", type=int, default=2, help="canais do sinal sintético (padrão 2)")
    p.add_argument("--medir", action="store_true", help="mede o tempo por quadro num zoom automático e sai")
    a = p.parse_args(argv)
    if (a.arquivo is None) == (a.sintetico is None):
        p.error("informe uma captura ou --sintetico MINUTOS")
    fonte = abrir(a.arquivo) if a.arquivo else gerar_sintetico(a.sintetico, a.canais)

    import pyqtgraph as pg
    from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QProgressBar

    from ..dados.cache import CacheDePiramides
    from ..dados.piramide import Cancelado

    app = QApplication.instance() or QApplication(sys.argv[:1])
    pg.setConfigOptions(background=FUNDO, foreground=EIXO)

    class Sinais(QObject):
        progresso = Signal(float)
        pronto = Signal(object)
        erro = Signal(str)

    class Construcao(QRunnable):
        def __init__(self):
            super().__init__()
            self.sinais = Sinais()
            self.cancelar = threading.Event()

        def run(self):
            try:
                piramides = CacheDePiramides().obter(fonte.chave, fonte.amostras, fonte.n_canais,
                                                     progresso=self.sinais.progresso.emit,
                                                     cancelado=self.cancelar.is_set)
                self.sinais.pronto.emit(piramides)
            except Cancelado:
                pass
            except Exception as e:      # o protótipo mostra qualquer erro na barra de status
                self.sinais.erro.emit(f"{type(e).__name__}: {e}")

    janela = QMainWindow()
    janela.setWindowTitle(f"Protótipo · navegar · {fonte.nome}")
    janela.resize(1400, 820)
    layout = pg.GraphicsLayoutWidget()
    janela.setCentralWidget(layout)
    barra = janela.statusBar()
    progresso = QProgressBar()
    progresso.setMaximumWidth(220)
    rotulo = QLabel(f"{fonte.nome}: construindo as pirâmides…")
    barra.addWidget(rotulo, 1)
    barra.addPermanentWidget(progresso)
    tracos: list = []

    def montar(piramides):
        progresso.hide()
        tracos.extend(montar_faixas(layout, fonte, piramides))
        duracao = len(fonte.canais[0].amostras) / fonte.canais[0].taxa_hz
        rotulo.setText(f"{fonte.nome}: {fonte.n_canais} canais, {duracao / 60:.1f} min, "
                       f"{len(fonte.amostras) / 1e6:.0f} M amostras")
        if a.medir:
            QTimer.singleShot(200, medir)

    construcao = Construcao()
    construcao.sinais.progresso.connect(lambda f: progresso.setValue(int(100 * f)))
    construcao.sinais.pronto.connect(montar)
    construcao.sinais.erro.connect(rotulo.setText)
    QThreadPool.globalInstance().start(construcao)
    app.aboutToQuit.connect(construcao.cancelar.set)

    ultimo = {"pinturas": 0, "t": time.perf_counter()}

    def medir_quadros():
        if not tracos:
            return
        agora = time.perf_counter()
        pinturas = tracos[0].pinturas
        qps = (pinturas - ultimo["pinturas"]) / (agora - ultimo["t"])
        ultimo.update(pinturas=pinturas, t=agora)
        barra.showMessage(f"{qps:4.0f} q/s", 1100)

    contador = QTimer()
    contador.timeout.connect(medir_quadros)
    contador.start(1000)

    def medir():
        canal = fonte.canais[0]
        mediana, p95 = resumo_dos_quadros(percorrer_zoom(app, layout, tracos[0], len(canal.amostras), canal.taxa_hz))
        dpr = layout.devicePixelRatioF()
        sys.stdout.write(f"{fonte.n_canais} traços, área de {layout.width()} x {layout.height()} px (escala {dpr:g}): "
                         f"mediana {mediana * 1e3:.1f} ms, p95 {p95 * 1e3:.1f} ms -> "
                         f"G1 {'aprovado' if p95 <= 0.016 else 'REPROVADO'}\n")
        app.quit()

    janela.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
