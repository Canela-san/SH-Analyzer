"""Os cursores A e B de um gráfico (o espectro, as bandas, o espectrograma, os harmônicos): duas linhas verticais
arrastáveis e a leitura delas, para medir num relance a distância entre dois picos ou dois instantes.

As posições ficam **na unidade dos dados** (Hz, s, ordem), e a linha é posta no eixo por ``para_eixo`` (o log10 na
frequência logarítmica): trocar a escala do eixo não perde os cursores. **Ao soltar,** um cursor pode encostar no
máximo mais próximo (``encostar(valor) -> valor``, de quem sabe os dados): no espectro, o pico a até 4 pixels.
"""

from __future__ import annotations

from collections.abc import Callable

import pyqtgraph as pg
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor


class ParDeCursores(QObject):
    """``mudou()`` sai quando um cursor anda (arrastando) e quando é solto."""

    mudou = Signal()

    def __init__(self, grafico: pg.PlotItem, *, para_eixo: Callable[[float], float] = lambda v: v,
                 do_eixo: Callable[[float], float] = lambda x: x,
                 encostar: Callable[[float], float] | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.grafico, self.para_eixo, self.do_eixo, self.encostar = grafico, para_eixo, do_eixo, encostar
        self.valores: list[float] = [0.0, 0.0]
        self.linhas: list[pg.InfiniteLine] = []
        for k, nome in enumerate(("A", "B")):
            linha = pg.InfiniteLine(angle=90, movable=True, label=nome,
                                    labelOpts={"position": 0.96, "movable": False})
            linha.setZValue(40)
            linha.sigPositionChanged.connect(lambda _l, k=k: self._movida(k))
            linha.sigPositionChangeFinished.connect(lambda _l, k=k: self._solta(k))
            self.linhas.append(linha)
        self.ligados = False

    def ligar(self, ligar: bool) -> None:
        """Liga (a um terço e a dois terços da faixa visível, na primeira vez) ou desliga os cursores."""
        if ligar == self.ligados:
            return
        self.ligados = ligar
        if ligar:
            if self.valores == [0.0, 0.0]:
                x0, x1 = self.grafico.getViewBox().viewRange()[0]
                self.valores = [self.do_eixo(x0 + (x1 - x0) / 3), self.do_eixo(x0 + 2 * (x1 - x0) / 3)]
            for linha in self.linhas:
                self.grafico.addItem(linha, ignoreBounds=True)
            self.reposicionar()
        else:
            for linha in self.linhas:
                self.grafico.removeItem(linha)
        self.mudou.emit()

    def reposicionar(self) -> None:
        """Põe as linhas nos valores guardados (depois de trocar a escala do eixo)."""
        for linha, valor in zip(self.linhas, self.valores):
            linha.blockSignals(True)
            linha.setValue(self.para_eixo(valor))
            linha.blockSignals(False)

    def definir(self, a: float, b: float) -> None:
        self.valores = [float(a), float(b)]
        self.reposicionar()
        self.mudou.emit()

    def _movida(self, k: int) -> None:
        self.valores[k] = float(self.do_eixo(self.linhas[k].value()))
        self.mudou.emit()

    def _solta(self, k: int) -> None:
        if self.encostar is not None:
            self.valores[k] = float(self.encostar(self.valores[k]))
            self.reposicionar()
        self.mudou.emit()

    def aplicar_cor(self, cor: str) -> None:
        caneta = pg.mkPen(QColor(cor), width=1)
        for linha in self.linhas:
            linha.setPen(caneta)
            linha.label.setColor(QColor(cor))

    @property
    def a(self) -> float:
        return self.valores[0]

    @property
    def b(self) -> float:
        return self.valores[1]
