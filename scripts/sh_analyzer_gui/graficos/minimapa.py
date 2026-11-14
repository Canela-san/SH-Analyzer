"""O minimapa da vista de tempo (docs/gui-plan.md, 9.1): a captura inteira de um traço, num pixmap desenhado uma vez,
e a janela visível por cima, que se arrasta.

Um widget leve, pintado com ``QPainter``: a cada quadro do zoom, ele só copia o pixmap e desenha um retângulo. O
``PlotWidget`` do PyQtGraph que ele substitui custava ~2,5 ms por atualização (os picos do p95 do G1).

A banda vem da pirâmide (``dados.consulta``), uma coluna por pixel, como o ``TracoLOD``: o pico de uma amostra
aparece também aqui.
"""

from __future__ import annotations

import math

import numpy as np
from pyqtgraph import functions as fn
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..dados.consulta import Envoltoria, aplicar_afim, consultar
from ..dados.piramide import Piramide
from ..tema.aplicar import aparencia
from ..tema.tokens import Tema

ALTURA = 44
MARGEM = 4                 # px acima e abaixo da banda
LARGURA_MINIMA_DA_JANELA = 3


class Minimapa(QWidget):
    """``janelaPedida(inicio, fim)``: o usuário arrastou a janela, ou clicou fora dela (a janela vai para lá, com a
    mesma largura)."""

    janelaPedida = Signal(float, float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("minimapa")
        self.setFixedHeight(ALTURA)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dados: tuple | None = None          # (pirâmide, amostras, taxa, t0, escala, deslocamento)
        self._pixmap: QPixmap | None = None
        self.inicio_total, self.fim_total = 0.0, 1.0
        self.janela: tuple[float, float] = (0.0, 1.0)
        self._arrasto: float | None = None          # onde o arrasto pegou a janela (s, relativo ao início dela)
        aparencia().mudou.connect(self._tema_mudou)

    # ------------------------------------------------------------------ dados

    def definir_traco(self, piramide: Piramide | None, amostras=None, taxa_hz: float = 1.0, *, t0: float = 0.0,
                      escala: float = 1.0, deslocamento: float = 0.0) -> None:
        """O traço do fundo (``None`` esvazia o minimapa)."""
        if piramide is None:
            self._dados = None
        else:
            self._dados = (piramide, amostras, float(taxa_hz), float(t0), float(escala), float(deslocamento))
            self.inicio_total = t0
            self.fim_total = t0 + max(piramide.n_amostras - 1, 1) / taxa_hz
        self._pixmap = None
        self.update()

    def definir_janela(self, inicio: float, fim: float) -> None:
        if (inicio, fim) != self.janela:
            self.janela = (inicio, fim)
            self.update()

    def _tema_mudou(self, _tema: Tema) -> None:
        self._pixmap = None
        self.update()

    def resizeEvent(self, evento) -> None:
        self._pixmap = None
        super().resizeEvent(evento)

    # ------------------------------------------------------------------ coordenadas

    def _x_do_tempo(self, t: float) -> float:
        largura = self.inicio_total != self.fim_total and (self.fim_total - self.inicio_total) or 1.0
        return (t - self.inicio_total) / largura * self.width()

    def _tempo_do_x(self, x: float) -> float:
        return self.inicio_total + x / max(self.width(), 1) * (self.fim_total - self.inicio_total)

    # ------------------------------------------------------------------ desenho

    def _desenhar_fundo(self, t: Tema) -> QPixmap:
        dpr = self.devicePixelRatioF() or 1.0
        mapa = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
        mapa.setDevicePixelRatio(dpr)
        mapa.fill(QColor(t.fundo))
        if self._dados is None:
            return mapa
        piramide, amostras, taxa, t0, escala, deslocamento = self._dados
        colunas = max(1, int(self.width() * dpr))
        consulta = aplicar_afim(consultar(piramide, amostras, 0, piramide.n_amostras, colunas), escala, deslocamento)
        if not isinstance(consulta, Envoltoria) or not len(consulta):
            return mapa
        minimos, maximos = consulta.minimos.astype(float), consulta.maximos.astype(float)
        finitos = np.isfinite(minimos) & np.isfinite(maximos)
        if not finitos.any():
            return mapa
        y0, y1 = float(np.min(minimos[finitos])), float(np.max(maximos[finitos]))
        altura = self.height() - 2 * MARGEM
        escala_y = altura / (y1 - y0) if y1 > y0 else 0.0
        bordas = consulta.bordas
        centros = t0 + (bordas[:-1] + bordas[1:] - 1) / (2 * taxa)
        largura_total = (self.fim_total - self.inicio_total) or 1.0
        x = ((centros - self.inicio_total) / largura_total * self.width())[finitos]
        topo = MARGEM + (y1 - maximos[finitos]) * escala_y
        base = np.maximum(MARGEM + (y1 - minimos[finitos]) * escala_y, topo + 1.0 / dpr)
        p = QPainter(mapa)
        caneta = QPen(QColor(t.borda_forte), 1.0 / dpr)
        caneta.setCosmetic(True)
        p.setPen(caneta)
        p.drawPath(fn.arrayToQPath(np.repeat(x, 2), np.column_stack([topo, base]).ravel(), connect="pairs"))
        p.end()
        return mapa

    def paintEvent(self, evento) -> None:
        t = aparencia().tema
        if self._pixmap is None:
            self._pixmap = self._desenhar_fundo(t)
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pixmap)
        if self._dados is not None:
            x0, x1 = self._x_do_tempo(self.janela[0]), self._x_do_tempo(self.janela[1])
            if x1 - x0 < LARGURA_MINIMA_DA_JANELA:            # numa captura longa, a janela some: um mínimo visível
                meio = (x0 + x1) / 2
                x0, x1 = meio - LARGURA_MINIMA_DA_JANELA / 2, meio + LARGURA_MINIMA_DA_JANELA / 2
            destaque = QColor(t.destaque)
            destaque.setAlphaF(0.3)
            caixa = QRectF(x0, 0.5, x1 - x0, self.height() - 1.0)
            p.fillRect(caixa, destaque)
            p.setPen(QPen(QColor(t.destaque), 2.0))
            p.drawLine(QPointF(x0, 0), QPointF(x0, self.height()))
            p.drawLine(QPointF(x1, 0), QPointF(x1, self.height()))
        p.end()

    # ------------------------------------------------------------------ mouse

    def mousePressEvent(self, evento) -> None:
        if evento.button() != Qt.MouseButton.LeftButton or self._dados is None:
            return
        t = self._tempo_do_x(evento.position().x())
        inicio, fim = self.janela
        if not inicio <= t <= fim:                # fora: a janela vai para lá, centrada
            largura = fim - inicio
            inicio, fim = t - largura / 2, t + largura / 2
            self.janelaPedida.emit(inicio, fim)
        self._arrasto = t - inicio

    def mouseMoveEvent(self, evento) -> None:
        if self._arrasto is None:
            return
        largura = self.janela[1] - self.janela[0]
        inicio = self._tempo_do_x(evento.position().x()) - self._arrasto
        if math.isfinite(inicio):
            self.janelaPedida.emit(inicio, inicio + largura)

    def mouseReleaseEvent(self, evento) -> None:
        self._arrasto = None
