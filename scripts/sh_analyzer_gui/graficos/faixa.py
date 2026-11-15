"""As peças de uma faixa da vista de tempo (docs/gui-plan.md, 6.6 e 9.2), com o tema:

* :class:`EixoDoTema`: o eixo do PyQtGraph com as cores e a fonte do tema e os números com vírgula; ele mostra os
  números do traço de referência, pela escala própria dele (``graficos/escalas.py``), com o prefixo do SI que a
  faixa visível pede ("tensão (mV)": :meth:`EixoDoTema.definir_rotulo`);
* :class:`GradeDoTema`: a grade nas marcas principais dos eixos, **opaca** e sem antialiasing (a semitransparente do
  PyQtGraph custava ~17 ms por quadro no protótipo);
* :class:`CaixaDaFaixa`: a ``ViewBox`` (com as escalas dos traços: ``graficos/escalas.py``) com os gestos do plano: a roda dá zoom no tempo, centrado no cursor; Ctrl +
  roda, no eixo Y da faixa; Alt + roda, nos dois juntos (o mesmo fator: a forma do sinal não muda); Shift + roda anda
  no tempo; arrastar anda no tempo; o duplo clique não mexe no zoom (o primeiro clique dele é um clique).
  **O zoom em caixa** (armado com ``Z``: o
  ``zoom_em_caixa``): arrastar desenha a caixa, e a faixa passa a mostrar o que estava nela (uma caixa de poucos
  pixels de altura é zoom só no tempo; de poucos de largura, só no Y). Um clique
  avisa onde foi (``clicada``), para a vista selecionar o traço mais perto. **Em cima de um eixo,** a roda e o
  arrasto mexem só naquele eixo (a roda nos números do Y dá o zoom no Y sem o Ctrl).
* **O botão do meio** (a roda apertada): arrastar move a vista nas duas direções, sem mudar as escalas, em cima de
  um traço ou não (os traços não mudam). Um clique rápido com ele pede o 0 no meio da faixa (``centroPedido``).
"""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from pyqtgraph import Point
from PySide6.QtCore import QLineF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen

from ..componentes.numeros import PREFIXO_DO_EXPOENTE, decimal, expoente_de_engenharia
from ..dados.unidades import aceita_prefixos
from ..tema.aplicar import aparencia
from ..tema.fontes import fonte_mono
from ..tema.tokens import TAMANHOS, Tema
from .escalas import CaixaComEscalas

FATOR_DA_RODA = 1.2          # cada passo da roda: 20 % de zoom
MINIMO_DA_CAIXA_PX = 4       # um lado menor que isto na tela não muda o zoom daquele eixo
_VALIDO = object()           # o eixo está com as posições e os textos em dia (no lugar da QPicture do PyQtGraph)
_prefixos_nos_eixos = True


def prefixos_nos_eixos() -> bool:
    """Se os eixos escolhem o prefixo do SI pela faixa visível (as configurações; ligado por padrão)."""
    return _prefixos_nos_eixos


def definir_prefixos_nos_eixos(ligados: bool) -> None:
    """Liga ou desliga os prefixos dos eixos de agora em diante; quem já desenhou refaz com o aviso da aparência
    (:meth:`EixoDoTema.aplicar_tema`)."""
    global _prefixos_nos_eixos
    _prefixos_nos_eixos = bool(ligados)
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
    """O eixo com as cores do tema e os números no formato brasileiro (vírgula decimal, menos tipográfico).

    **A conversão:** com um traço de escala própria como referência, os números são os dele, ``u = (v na vista - c)
    / k`` (``graficos/escalas.py``: o valor no eixo Y, o tempo no eixo do tempo); a grade segue as marcas
    (``conversaoMudou``).

    **O prefixo do SI:** com a unidade no rótulo (:meth:`definir_rotulo`), o eixo escolhe o prefixo pelo maior valor
    da faixa visível, como a escrita dos números (``numeros.formatar_si``): de 0 a 2 mV, "tensão (mV)" e os números
    em mV. Só numa unidade que aceita prefixo (°C, % e psi ficam como estão), fora da escala logarítmica, com os
    prefixos ligados nas configurações, e nunca acima de ``expoente_maximo`` (no tempo, 0: uma hora é 3600 s, não
    3,6 ks). As posições das marcas e a grade não mudam: só os números escritos."""

    conversaoMudou = Signal()
    expoente_maximo = 9

    def __init__(self, orientacao: str, *, expoente_maximo: int = 9):
        super().__init__(orientacao)
        self.conversao = (1.0, 0.0)             # (k, c): na vista = k·u + c
        self.expoente_maximo = expoente_maximo
        self._medidor = MedidorDeTexto()
        self.enableAutoSIPrefix(True)            # o setRange chama o updateAutoSIPrefix (o daqui)
        self.aplicar_tema(aparencia().tema)

    def aplicar_tema(self, t: Tema) -> None:
        """As cores e a fonte do tema; os números são escritos de novo (o separador decimal e os prefixos podem ter
        mudado). O rótulo volta à cor do eixo: quem o pinta com a cor de um traço o pinta de novo depois."""
        self.setPen(pg.mkPen(t.borda_forte))
        self.setTextPen(pg.mkPen(t.eixo))
        self.setTickFont(fonte_mono(TAMANHOS["legenda"]))
        self.updateAutoSIPrefix()

    def definir_rotulo(self, texto: str, unidade: str = "", cor: str | None = None) -> None:
        """O rótulo "texto (unidade)", com o prefixo que a faixa pedir; ``cor`` (``#rrggbb``) pinta o rótulo (um
        traço de unidade ou escala diferente das outras da faixa), ``None`` o deixa na cor do eixo."""
        self.setLabel(texto, unidade, color=cor or self.textPen().color().name())

    def setLabel(self, text=None, units=None, unitPrefix=None, siPrefixEnableRanges=None, unitPower=1, **kwargs):
        """O ``setLabel`` do PyQtGraph, e o prefixo refeito na hora: um rótulo sem unidade nunca fica com os números
        na escala do prefixo de antes."""
        super().setLabel(text, units, unitPrefix, siPrefixEnableRanges, unitPower, **kwargs)
        self.updateAutoSIPrefix()

    @property
    def rotulo(self) -> str:
        """O rótulo como aparece, em texto: "tensão (mV)"."""
        if not self.labelUnits:
            return self.labelText
        return f"{self.labelText} ({self.labelUnitPrefix}{self.labelUnits})"

    def updateAutoSIPrefix(self) -> None:
        """O prefixo do SI pela faixa visível (ver a classe). O rótulo só é refeito quando o prefixo muda: o eixo do
        tempo passa por aqui a cada quadro do zoom."""
        expoente = 0
        if self.labelUnits and _prefixos_nos_eixos and not self.logMode and aceita_prefixos(self.labelUnits):
            expoente = expoente_de_engenharia(max(abs(self.range[0]), abs(self.range[1])), self.expoente_maximo)
        prefixo = PREFIXO_DO_EXPOENTE[expoente]
        if prefixo != self.labelUnitPrefix or self.autoSIPrefixScale != 10.0 ** -expoente:
            self.autoSIPrefixScale = 10.0 ** -expoente
            self.labelUnitPrefix = prefixo
            self._updateLabel()

    def definir_conversao(self, k: float = 1.0, c: float = 0.0) -> None:
        if (k, c) == self.conversao:
            return
        self.conversao = (float(k), float(c))
        vista = self.linkedView()
        if vista is not None:
            self.linkedViewChanged(vista)
        self.conversaoMudou.emit()

    def linkedViewChanged(self, view, newRange=None):
        if self.conversao != (1.0, 0.0):
            k, c = self.conversao
            v0, v1 = view.viewRange()[1 if self.orientation in ("left", "right") else 0] if newRange is None \
                else newRange
            newRange = ((v0 - c) / k, (v1 - c) / k)
        super().linkedViewChanged(view, newRange)

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
        return [decimal(s).replace("-", "−") for s in super().tickStrings(valores, escala, espacamento)]


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
        for eixo in (eixo_x, eixo_y):
            if isinstance(eixo, EixoDoTema):
                eixo.conversaoMudou.connect(self.update)

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
        kx, cx = getattr(self._eixo_x, "conversao", (1.0, 0.0))
        ky, cy = getattr(self._eixo_y, "conversao", (1.0, 0.0))
        chave = (x0, x1, y0, y1, vb.width(), vb.height(), kx, cx, ky, cy)
        if chave != self._chave:
            self._chave = chave
            # As linhas nas marcas dos eixos, que podem ser as de um traço de escala própria.
            marcas_x = kx * marcas_principais(self._eixo_x, (x0 - cx) / kx, (x1 - cx) / kx, vb.width()) + cx
            marcas_y = ky * marcas_principais(self._eixo_y, (y0 - cy) / ky, (y1 - cy) / ky, vb.height()) + cy
            self._linhas = ([QLineF(x, y0, x, y1) for x in marcas_x] + [QLineF(x0, y, x1, y) for y in marcas_y])
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


class CaixaDaFaixa(CaixaComEscalas):
    """``clicada(x, y, modificadores)``: um clique simples, nas unidades da vista."""

    clicada = Signal(float, float, object)
    centroPedido = Signal(float, float)             # o clique rápido do meio: onde foi
    caixaUsada = Signal()                           # um zoom em caixa terminou (quem armou desarma)

    def __init__(self):
        super().__init__(enableMenu=False)
        self.setMouseEnabled(x=True, y=False)          # arrastar anda no tempo; o Y fica onde está
        self.zoom_em_caixa = False
        self.aplicar_tema(aparencia().tema)

    def aplicar_tema(self, t: Tema) -> None:
        self.setBackgroundColor(QColor(t.afundada))
        borda, fundo = QColor(t.acento), QColor(t.acento)
        fundo.setAlphaF(0.12)
        self.rbScaleBox.setPen(pg.mkPen(borda, width=1))
        self.rbScaleBox.setBrush(pg.mkBrush(fundo))

    def armar_zoom_em_caixa(self, armado: bool) -> None:
        """Arma (ou desarma) o zoom em caixa: o próximo arrasto com o botão esquerdo desenha a caixa."""
        self.zoom_em_caixa = armado
        if not armado:
            self.rbScaleBox.hide()

    def zoom_na_caixa(self, canto_a, canto_b) -> None:
        """A faixa passa a mostrar o retângulo entre os dois cantos (nas unidades da vista). Um lado que na tela tem
        menos de :data:`MINIMO_DA_CAIXA_PX` fica como está. Vai pelo ``scaleBy`` (com o ponto fixo que leva a caixa à
        vista inteira): com traços de escala própria selecionados, são eles que mudam, como na roda."""
        (x0, x1), (y0, y1) = self.viewRange()
        bx0, bx1 = sorted((canto_a.x(), canto_b.x()))
        by0, by1 = sorted((canto_a.y(), canto_b.y()))
        largura, altura = max(self.width(), 1.0), max(self.height(), 1.0)
        fx = (bx1 - bx0) / (x1 - x0) if (bx1 - bx0) / (x1 - x0) * largura >= MINIMO_DA_CAIXA_PX else 1.0
        fy = (by1 - by0) / (y1 - y0) if (by1 - by0) / (y1 - y0) * altura >= MINIMO_DA_CAIXA_PX else 1.0
        if fx == 1.0 and fy == 1.0:
            return
        # O ponto fixo c de cada eixo leva o começo da vista ao da caixa: b0 = c + (v0 - c)·f.
        cx = (bx0 - x0 * fx) / (1.0 - fx) if fx != 1.0 else x0
        cy = (by0 - y0 * fy) / (1.0 - fy) if fy != 1.0 else y0
        self.scaleBy(x=fx if fx != 1.0 else None, y=fy if fy != 1.0 else None, center=Point(cx, cy))

    # Os eventos que vêm de um eixo (a roda ou o arrasto em cima dos números) chegam aqui repassados pelo PyQtGraph,
    # com ``axis`` (o nome dele) = 0 para o tempo ou 1 para o Y, e com ``pos()`` nas coordenadas do eixo, não da
    # caixa. Por isso as posições saem sempre da cena (``scenePos``), que vale para os dois casos.

    def wheelEvent(self, evento, axis=None):
        """A roda na caixa (ver o começo do arquivo) ou em cima de um eixo: no do tempo, o zoom (ou, com Shift, o
        passo) é só no tempo; no do Y, o zoom é só no Y da faixa, sem precisar do Ctrl.

        Com o Alt, o sistema costuma virar a roda de lado (o ``delta`` vem na horizontal): o ``delta()`` da cena já
        traz o maior dos dois, e o zoom não depende da direção em que ele veio."""
        modificadores = evento.modifiers()
        passo = evento.delta() / 120.0
        fator = FATOR_DA_RODA ** -passo
        centro = self.mapSceneToView(evento.scenePos())
        if axis is None and modificadores & Qt.KeyboardModifier.AltModifier:
            self.scaleBy(x=fator, y=fator, center=centro)
        elif axis == 1 or (axis is None and modificadores & Qt.KeyboardModifier.ControlModifier):
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
            # O segundo clique de um duplo clique não faz nada: o primeiro já selecionou, e o zoom fica onde o usuário
            # o pôs (ajustar tudo é o F, ou o botão da barra).
            if not evento.double() and self.sceneBoundingRect().contains(evento.scenePos()):
                # Um clique em cima de um eixo não seleciona nada (nem tira a seleção).
                self.clicada.emit(ponto.x(), ponto.y(), evento.modifiers())
            evento.accept()
        elif evento.button() == Qt.MouseButton.MiddleButton:
            self.centroPedido.emit(ponto.x(), ponto.y())
            evento.accept()
        else:
            super().mouseClickEvent(evento)

    def centralizar_no_zero(self) -> None:
        """O 0 do eixo Y (o do traço de referência, se ele tem escala própria) no meio da faixa, com a mesma escala;
        o tempo fica onde está. É um pan do Y: com traços de escala própria selecionados, só eles andam."""
        _, (y0, y1) = self.viewRange()
        zero = self.escalas.escala(self.escalas.referencia).y.na_vista(0.0) if self.escalas is not None else 0.0
        self.translateBy(y=zero - (y0 + y1) / 2)

    def mouseDragEvent(self, evento, axis=None):
        if self.zoom_em_caixa and axis is None and evento.button() == Qt.MouseButton.LeftButton:
            evento.accept()
            if evento.isFinish():
                self.rbScaleBox.hide()
                self.zoom_na_caixa(self.mapSceneToView(evento.buttonDownScenePos()),
                                   self.mapSceneToView(evento.scenePos()))
                self.caixaUsada.emit()
            else:
                self.updateScaleBox(evento.buttonDownPos(), evento.pos())
            return
        if evento.button() == Qt.MouseButton.MiddleButton:
            # Anda a vista nas duas direções (ou só na do eixo arrastado), sem mudar a escala: os dados seguem o mouse.
            evento.accept()
            anterior = self.mapSceneToView(evento.lastScenePos())
            atual = self.mapSceneToView(evento.scenePos())
            dx, dy = anterior.x() - atual.x(), anterior.y() - atual.y()
            self.translateBy(x=0.0 if axis == 1 else dx, y=0.0 if axis == 0 else dy)
            return
        super().mouseDragEvent(evento, axis)
