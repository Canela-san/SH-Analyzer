"""As peças de uma faixa da vista de tempo (docs/gui-plan.md, 6.6 e 9.2), com o tema:

* :class:`EixoDoTema`: o eixo do PyQtGraph com as cores e a fonte do tema e os números com vírgula;
* :class:`GradeDoTema`: a grade nas marcas principais dos eixos, **opaca** e sem antialiasing (a semitransparente do
  PyQtGraph custava ~17 ms por quadro no protótipo);
* :class:`CaixaDaFaixa`: a ``ViewBox`` com os gestos do plano: a roda dá zoom no tempo, centrado no cursor; Ctrl +
  roda, no eixo Y da faixa; Shift + roda anda no tempo; arrastar anda no tempo; o duplo clique ajusta tudo. Um clique
  avisa onde foi (``clicada``), para a vista selecionar o traço mais perto. **Em cima de um eixo,** a roda e o
  arrasto mexem só naquele eixo (a roda nos números do Y dá o zoom no Y sem o Ctrl).
* **O botão do meio** (a roda apertada): arrastar move, sem mudar as escalas. Começando em cima de um traço, a vista
  pede o modo ``"traco"`` (``arrasteDoMeioComecou``) e só aquele traço anda (``tracoArrastado``, com o deslocamento
  total desde o começo); em qualquer outro lugar, anda a vista inteira, nas duas direções. Um clique rápido com ele
  pede o 0 no meio da faixa (``centroPedido``).
"""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QLineF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen

from ..tema.aplicar import aparencia
from ..tema.fontes import fonte_mono
from ..tema.tokens import TAMANHOS, Tema

FATOR_DA_RODA = 1.2          # cada passo da roda: 20 % de zoom
_VALIDO = object()           # o eixo está com as posições e os textos em dia (no lugar da QPicture do PyQtGraph)
LARGURA_DO_EIXO_Y = 64       # px: fixa, para as faixas ficarem alinhadas no tempo


class MedidorDeTexto:
    """O que o ``generateDrawSpecs`` do PyQtGraph usa do pintor (``setFont`` e ``boundingRect``), com a medida de
    cada texto guardada: o eixo do tempo mede os mesmos ~50 textos a cada quadro do zoom (~0,4 ms)."""

    LIMITE = 4000

    def __init__(self):
        self._fonte = QFont()
        self._chave = self._fonte.key()
        self._medidas: dict[tuple, QRectF] = {}

    def setFont(self, fonte: QFont) -> None:
        self._fonte = QFont(fonte)
        self._chave = self._fonte.key()

    def boundingRect(self, retangulo: QRectF, opcoes, texto: str) -> QRectF:
        chave = (self._chave, int(opcoes), texto, retangulo.width(), retangulo.height())
        medida = self._medidas.get(chave)
        if medida is None:
            if len(self._medidas) > self.LIMITE:
                self._medidas.clear()
            medida = QFontMetricsF(self._fonte).boundingRect(retangulo, int(opcoes), texto)
            self._medidas[chave] = medida
        return QRectF(medida)


class EixoDoTema(pg.AxisItem):
    """O eixo com as cores do tema e os números no formato brasileiro (vírgula decimal, menos tipográfico)."""

    def __init__(self, orientacao: str):
        super().__init__(orientacao)
        self._medidor = MedidorDeTexto()
        self.enableAutoSIPrefix(False)
        self.setTickFont(fonte_mono(TAMANHOS["legenda"]))
        self.aplicar_tema(aparencia().tema)

    def aplicar_tema(self, t: Tema) -> None:
        self.setPen(pg.mkPen(t.borda_forte))
        self.setTextPen(pg.mkPen(t.eixo))

    def paint(self, p: QPainter, opcao, widget) -> None:
        """Desenha direto, sem a ``QPicture`` do PyQtGraph: o eixo do tempo muda a cada quadro do zoom, e gravar a
        figura para tocá-la em seguida dobrava o trabalho. As posições e os textos (``generateDrawSpecs``) ficam
        guardados até o PyQtGraph invalidar o eixo (``self.picture = None``, a cada mudança da faixa)."""
        if self.picture is None:
            if self.style["tickFont"]:
                self._medidor.setFont(self.style["tickFont"])
            self._especificacoes = self.generateDrawSpecs(self._medidor)
            self.picture = _VALIDO
        especificacoes = getattr(self, "_especificacoes", None)
        if especificacoes is not None:
            p.save()
            if self.style["tickFont"]:
                p.setFont(self.style["tickFont"])
            self.drawPicture(p, *especificacoes)
            p.restore()

    def tickValues(self, inicio: float, fim: float, pixels: float):
        """As marcas de cada nível, como as do PyQtGraph, sem o ``np.isclose`` de uma matriz (marcas × marcas) que
        ele usa para tirar as repetidas: uma marca repete a de um nível acima quando cai num múltiplo do espaçamento
        dele. O mesmo resultado, em uma fração do tempo (o eixo do tempo refaz as marcas a cada quadro)."""
        if self.logMode or self.scale != 1.0:
            return super().tickValues(inicio, fim, pixels)
        inicio, fim = sorted((inicio, fim))
        niveis = []
        for espacamento, deslocamento in self.tickSpacing(inicio, fim, pixels):
            primeiro = math.ceil((inicio - deslocamento) / espacamento) * espacamento + deslocamento
            n = int((fim - primeiro) / espacamento) + 1
            valores = primeiro + espacamento * np.arange(max(n, 0))
            repetida = np.zeros(len(valores), dtype=bool)
            for maior, desl_maior in ((e, d) for e, d, _ in niveis):
                fracao = (valores - desl_maior) / maior
                repetida |= np.abs(fracao - np.round(fracao)) * maior < espacamento * 0.01
            niveis.append((espacamento, deslocamento, valores[~repetida]))
        return [(e, v.tolist()) for e, _, v in niveis]

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
    arrasteDoMeioComecou = Signal(float, float)     # onde começou (unidades da vista); a vista diz o modo
    tracoArrastado = Signal(float, float, bool)     # dx, dy desde o começo; se o arrasto terminou
    centroPedido = Signal(float, float)             # o clique rápido do meio: onde foi

    def __init__(self):
        super().__init__(enableMenu=False)
        self.setMouseEnabled(x=True, y=False)          # arrastar anda no tempo; o Y fica onde está
        self.modo_do_meio = "vista"                    # "vista" (anda tudo) ou "traco" (a vista move um traço)
        self.aplicar_tema(aparencia().tema)

    def aplicar_tema(self, t: Tema) -> None:
        self.setBackgroundColor(QColor(t.afundada))

    # Os eventos que vêm de um eixo (a roda ou o arrasto em cima dos números) chegam aqui repassados pelo PyQtGraph,
    # com ``axis`` (o nome dele) = 0 para o tempo ou 1 para o Y, e com ``pos()`` nas coordenadas do eixo, não da
    # caixa. Por isso as posições saem sempre da cena (``scenePos``), que vale para os dois casos.

    def wheelEvent(self, evento, axis=None):
        """A roda na caixa (ver o começo do arquivo) ou em cima de um eixo: no do tempo, o zoom (ou, com Shift, o
        passo) é só no tempo; no do Y, o zoom é só no Y da faixa, sem precisar do Ctrl."""
        modificadores = evento.modifiers()
        passo = evento.delta() / 120.0
        fator = FATOR_DA_RODA ** -passo
        centro = self.mapSceneToView(evento.scenePos())
        if axis == 1 or (axis is None and modificadores & Qt.KeyboardModifier.ControlModifier):
            self.scaleBy(y=fator, center=centro)
        elif modificadores & Qt.KeyboardModifier.ShiftModifier:
            (x0, x1), _ = self.viewRange()
            self.translateBy(x=-(x1 - x0) * 0.1 * passo)
        else:
            self.scaleBy(x=fator, center=centro)
        evento.accept()

    def mouseClickEvent(self, evento):
        ponto = self.mapSceneToView(evento.scenePos())
        if evento.button() == Qt.MouseButton.LeftButton:
            if evento.double():
                self.ajustarPedido.emit()
            elif self.sceneBoundingRect().contains(evento.scenePos()):
                # Um clique em cima de um eixo não seleciona nada (nem tira a seleção).
                self.clicada.emit(ponto.x(), ponto.y(), evento.modifiers())
            evento.accept()
        elif evento.button() == Qt.MouseButton.MiddleButton:
            self.centroPedido.emit(ponto.x(), ponto.y())
            evento.accept()
        else:
            super().mouseClickEvent(evento)

    def centralizar_no_zero(self) -> None:
        """O 0 do eixo Y no meio da faixa, com a mesma escala (a mesma altura em Y); o tempo fica onde está."""
        _, (y0, y1) = self.viewRange()
        meia = (y1 - y0) / 2
        self.setYRange(-meia, meia, padding=0)

    def mouseDragEvent(self, evento, axis=None):
        if evento.button() == Qt.MouseButton.MiddleButton:
            evento.accept()
            inicio = self.mapSceneToView(evento.buttonDownScenePos())
            if evento.isStart():
                self.modo_do_meio = "vista"
                if axis is None:          # em cima de um eixo não há traço: anda a vista, só naquele eixo
                    self.arrasteDoMeioComecou.emit(inicio.x(), inicio.y())     # a vista pode trocar para "traco"
            if self.modo_do_meio == "traco":
                # A vista não anda neste modo: o deslocamento desde o começo vale nas unidades de agora.
                atual = self.mapSceneToView(evento.scenePos())
                self.tracoArrastado.emit(atual.x() - inicio.x(), atual.y() - inicio.y(), evento.isFinish())
            else:
                # Anda a vista nas duas direções (ou só na do eixo arrastado), sem mudar a escala: os dados seguem o
                # mouse.
                anterior = self.mapSceneToView(evento.lastScenePos())
                atual = self.mapSceneToView(evento.scenePos())
                dx, dy = anterior.x() - atual.x(), anterior.y() - atual.y()
                self.translateBy(x=0.0 if axis == 1 else dx, y=0.0 if axis == 0 else dy)
            if evento.isFinish():
                self.modo_do_meio = "vista"
            return
        super().mouseDragEvent(evento, axis)
