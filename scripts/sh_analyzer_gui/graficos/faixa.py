"""As peças de uma faixa da vista de tempo (docs/gui-plan.md, 6.6 e 9.2), com o tema:

* :class:`EixoDoTema`: o eixo do PyQtGraph com as cores e a fonte do tema e os números com vírgula;
* :class:`GradeDoTema`: a grade nas marcas principais dos eixos, **opaca** e sem antialiasing (a semitransparente do
  PyQtGraph custava ~17 ms por quadro no protótipo);
* :class:`CaixaDaFaixa`: a ``ViewBox`` com os gestos do plano: a roda dá zoom no tempo, centrado no cursor; Ctrl +
  roda, no eixo Y da faixa; Shift + roda anda no tempo; arrastar anda no tempo; o duplo clique ajusta tudo. Um clique
  avisa onde foi (``clicada``), para a vista selecionar o traço mais perto.
"""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QLineF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen

from ..tema.aplicar import aparencia
from ..tema.fontes import fonte_mono
from ..tema.tokens import TAMANHOS, Tema

FATOR_DA_RODA = 1.2          # cada passo da roda: 20 % de zoom
LARGURA_DO_EIXO_Y = 64       # px: fixa, para as faixas ficarem alinhadas no tempo


class EixoDoTema(pg.AxisItem):
    """O eixo com as cores do tema e os números no formato brasileiro (vírgula decimal, menos tipográfico)."""

    def __init__(self, orientacao: str):
        super().__init__(orientacao)
        self.enableAutoSIPrefix(False)
        self.setTickFont(fonte_mono(TAMANHOS["legenda"]))
        self.aplicar_tema(aparencia().tema)

    def aplicar_tema(self, t: Tema) -> None:
        self.setPen(pg.mkPen(t.borda_forte))
        self.setTextPen(pg.mkPen(t.eixo))

    def tickStrings(self, valores, escala, espacamento):
        return [s.replace(".", ",").replace("-", "−") for s in super().tickStrings(valores, escala, espacamento)]


def marcas_principais(eixo: pg.AxisItem, inicio: float, fim: float, pixels: float) -> np.ndarray:
    """As posições das marcas principais do eixo (as que têm número), sem o ``tickValues`` do PyQtGraph: ele tira
    as repetidas entre os níveis com ``np.isclose`` e custava ~13 ms por quadro com 8 faixas. O espaçamento vem do
    próprio eixo (``tickSpacing``), e as linhas caem exatamente nas marcas dele."""
    if not (math.isfinite(inicio) and math.isfinite(fim)) or fim <= inicio:
        return np.empty(0)
    niveis = eixo.tickSpacing(inicio, fim, max(pixels, 1.0))
    if not niveis:
        return np.empty(0)
    espacamento, deslocamento = niveis[0]
    primeiro = math.ceil((inicio - deslocamento) / espacamento) * espacamento + deslocamento
    n = int((fim - primeiro) / espacamento) + 1
    return primeiro + espacamento * np.arange(max(0, min(n, 1000)))


class GradeDoTema(pg.GraphicsObject):
    """As linhas nas marcas principais dos dois eixos da faixa, atrás dos traços. As linhas são calculadas uma vez
    por mudança da vista, não a cada pintura."""

    def __init__(self, eixo_x: pg.AxisItem, eixo_y: pg.AxisItem):
        super().__init__()
        self._eixo_x, self._eixo_y = eixo_x, eixo_y
        self._cor = QColor(aparencia().tema.grade)
        self._chave = None
        self._linhas: list[QLineF] = []
        self.setZValue(-100)

    def aplicar_tema(self, t: Tema) -> None:
        self._cor = QColor(t.grade)
        self.update()

    def viewRangeChanged(self):
        self.prepareGeometryChange()
        self.update()

    def boundingRect(self) -> QRectF:
        vb = self.getViewBox()
        return vb.viewRect() if vb is not None else QRectF()

    def _calcular(self, vb) -> list[QLineF]:
        (x0, x1), (y0, y1) = vb.viewRange()
        chave = (x0, x1, y0, y1, vb.width(), vb.height())
        if chave != self._chave:
            self._chave = chave
            self._linhas = ([QLineF(x, y0, x, y1) for x in marcas_principais(self._eixo_x, x0, x1, vb.width())]
                            + [QLineF(x0, y, x1, y) for y in marcas_principais(self._eixo_y, y0, y1, vb.height())])
        return self._linhas

    def paint(self, p: QPainter, *args) -> None:
        vb = self.getViewBox()
        if vb is None:
            return
        linhas = self._calcular(vb)
        caneta = QPen(self._cor, 1.0)
        caneta.setCosmetic(True)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(caneta)
        p.drawLines(linhas)


class CaixaDaFaixa(pg.ViewBox):
    """``clicada(x, y, modificadores)``: um clique simples, nas unidades da vista. ``ajustarPedido``: o duplo
    clique (ajustar tudo)."""

    clicada = Signal(float, float, object)
    ajustarPedido = Signal()

    def __init__(self):
        super().__init__(enableMenu=False)
        self.setMouseEnabled(x=True, y=False)          # arrastar anda no tempo; o Y fica onde está
        self.aplicar_tema(aparencia().tema)

    def aplicar_tema(self, t: Tema) -> None:
        self.setBackgroundColor(QColor(t.afundada))

    def wheelEvent(self, evento, eixo=None):
        modificadores = evento.modifiers()
        passo = evento.delta() / 120.0
        if modificadores & Qt.KeyboardModifier.ShiftModifier:
            (x0, x1), _ = self.viewRange()
            self.translateBy(x=-(x1 - x0) * 0.1 * passo)
        else:
            fator = FATOR_DA_RODA ** -passo
            centro = self.mapToView(evento.pos())
            if modificadores & Qt.KeyboardModifier.ControlModifier:
                self.scaleBy(y=fator, center=centro)
            else:
                self.scaleBy(x=fator, center=centro)
        evento.accept()

    def mouseClickEvent(self, evento):
        if evento.button() == Qt.MouseButton.LeftButton:
            if evento.double():
                self.ajustarPedido.emit()
            else:
                ponto = self.mapToView(evento.pos())
                self.clicada.emit(ponto.x(), ponto.y(), evento.modifiers())
            evento.accept()
        else:
            super().mouseClickEvent(evento)

    def mouseDragEvent(self, evento, eixo=None):
        if evento.button() == Qt.MouseButton.MiddleButton:
            # O botão do meio também anda no tempo (o gesto dos osciloscópios), sem mexer no Y.
            evento.accept()
            anterior, atual = self.mapToView(evento.lastPos()), self.mapToView(evento.pos())
            self.translateBy(x=anterior.x() - atual.x())
            return
        super().mouseDragEvent(evento, eixo)
