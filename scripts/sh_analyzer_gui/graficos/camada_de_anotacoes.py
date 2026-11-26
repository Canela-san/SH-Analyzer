"""A camada das anotações de uma caixa (a F5.8 refeita: o gráfico como caderno): **um item só** por caixa, que
desenha todas as anotações dela, as escolhe, as move, estica e gira pelas alças, e onde as ferramentas da barra de
anotação criam as novas (as formas, os textos e o desenho à mão livre, do mouse ou da mesa digitalizadora).

**Por que um item só:** cada anotação como itens do PyQtGraph (o ``TextItem``, o ``ArrowItem``...) custava vários
itens na cena, e a cena do Qt refaz o índice e a ordem deles a cada quadro do zoom. Aqui, a cada pintura, as
coordenadas das anotações vão para pixels da tela no NumPy (como no ``TracoLOD``) e o QPainter desenha sem a
transformação da vista: as espessuras e os textos ficam do mesmo tamanho em qualquer zoom, e nada pinta um bloco
cheio na escala enorme do tempo bem de perto. O retângulo do item é o da vista (o dos dados, bem de perto, passava
de 2³¹ pixels: ver ``traco_lod.py``).

**Os gestos** (a camada fica por cima dos traços e dos cursores; o que ela não quer passa para a caixa):

* com a ferramenta **Selecionar** (a de sempre), o clique numa anotação a escolhe (Shift: soma ou tira da escolha)
  e o arrasto a move; as alças da escolhida mudam a forma (as pontas da seta, da linha e da cota; as bordas da
  região; os cantos e os lados do retângulo, da elipse e do desenho, que se esticam; o canto do texto, que muda o
  tamanho da fonte); o duplo clique muda o texto. Fora das anotações, nada muda: a caixa anda no tempo, os cursores
  se arrastam e o clique escolhe o traço;
* com uma ferramenta de **forma**, o arrasto desenha a forma de um ponto ao outro (o clique sem arrastar a põe com
  um tamanho padrão); o texto, o marcador e o nível vão no clique;
* com a **caneta** ou o **marca-texto**, o arrasto desenha à mão livre; da mesa digitalizadora, a pressão afina e
  engrossa a linha (:class:`Mesa`), e a ponta de borracha da caneta apaga;
* com a **borracha**, o arrasto apaga os desenhos que ela toca.

Cada gesto é um passo de desfazer, dado ao terminar: quem segura a pilha é o dono (``areas/analise/anotacoes.py``).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pyqtgraph as pg
from pyqtgraph import functions as fn
from PySide6.QtCore import QEvent, QLineF, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QPolygonF, QTransform

from ..dados.anotacoes import FORMAS, Anotacao
from ..tema.fontes import fonte_da_interface
from ..tema.tokens import TAMANHOS

Z_DA_CAMADA = 30                 # por cima dos traços (0 e 10) e dos cursores (20)
PERTO_PX = 7.0                   # o clique a até isto de uma linha é nela
LADO_DA_ALCA = 9.0
MINIMO_DO_ARRASTO_PX = 5.0       # um arrasto menor que isto, com uma ferramenta de forma, é um clique
PASSO_DO_DESENHO_PX = 1.5        # o desenho guarda um ponto a cada isto da tela
RAIO_DA_BORRACHA_PX = 9.0
TAMANHO_PADRAO_PX = (110.0, 70.0)  # a forma posta com um clique (a seta e a linha: na diagonal)
FONTE_PADRAO_PX = TAMANHOS["corpo"]
_PONTO_POR_PIXEL = 4.0 / 3.0     # a fonte em pt na tela (96 dpi)

FERRAMENTAS_DE_FORMA = ("texto", "seta", "linha", "regiao", "cota", "retangulo", "elipse", "nivel", "marcador")
FERRAMENTAS_DE_DESENHO = ("caneta", "marca_texto")
FERRAMENTAS = ("selecionar",) + FERRAMENTAS_DE_FORMA + FERRAMENTAS_DE_DESENHO + ("borracha",)
NO_CLIQUE = ("texto", "marcador", "nivel")

_TRACOS_DO_QT = {"solido": Qt.PenStyle.SolidLine, "tracejado": Qt.PenStyle.DashLine,
                 "pontilhado": Qt.PenStyle.DotLine, "traco_ponto": Qt.PenStyle.DashDotLine}
ESPESSURA_DO_TIPO = {"texto": 1.5, "seta": 1.6, "linha": 1.6, "regiao": 1.0, "cota": 1.3, "retangulo": 1.6,
                     "elipse": 1.6, "nivel": 1.4, "marcador": 2.0, "desenho": 2.4}
"""A espessura (px) de cada tipo quando a da anotação é 0."""

CURSORES_DAS_ALCAS = {"p0": Qt.CursorShape.CrossCursor, "p1": Qt.CursorShape.CrossCursor,
                      "x0": Qt.CursorShape.SizeHorCursor, "x1": Qt.CursorShape.SizeHorCursor,
                      "e": Qt.CursorShape.SizeHorCursor, "d": Qt.CursorShape.SizeHorCursor,
                      "c": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
                      "ce": Qt.CursorShape.SizeFDiagCursor, "bd": Qt.CursorShape.SizeFDiagCursor,
                      "cd": Qt.CursorShape.SizeBDiagCursor, "be": Qt.CursorShape.SizeBDiagCursor,
                      "fonte": Qt.CursorShape.SizeFDiagCursor, "nivel": Qt.CursorShape.SizeAllCursor}


def espessura(a: Anotacao) -> float:
    return a.espessura or ESPESSURA_DO_TIPO[a.tipo]


def tamanho_da_fonte_px(a: Anotacao) -> float:
    return a.fonte * _PONTO_POR_PIXEL if a.fonte else float(FONTE_PADRAO_PX)


_FONTES: dict[tuple, QFont] = {}


def fonte_da_anotacao(a: Anotacao) -> QFont:
    chave = (round(tamanho_da_fonte_px(a), 2), a.negrito, a.italico)
    fonte = _FONTES.get(chave)
    if fonte is None:
        if len(_FONTES) > 64:
            _FONTES.clear()
        fonte = fonte_da_interface(max(1, round(chave[0])))
        fonte.setBold(a.negrito)
        fonte.setItalic(a.italico)
        _FONTES[chave] = fonte
    return fonte


# ---------------------------------------------------------------------- a mesa digitalizadora


class Mesa(QObject):
    """A pressão da caneta da mesa digitalizadora, para a camada que recebe o mouse que o Qt sintetiza dela. Um filtro
    nos ``viewport`` dos gráficos (:meth:`ouvir`): o evento da mesa segue sem ser aceito, e o Qt o entrega de novo
    como mouse; a camada lê aqui a pressão (``None``: o mouse, sem mesa há :data:`VALIDADE_S`) e se a ponta é a de
    borracha."""

    VALIDADE_S = 0.25
    _TIPOS = (QEvent.Type.TabletPress, QEvent.Type.TabletMove, QEvent.Type.TabletRelease)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._pressao = 1.0
        self._quando = 0.0
        self.borracha = False

    def ouvir(self, widget) -> None:
        widget.installEventFilter(self)

    def eventFilter(self, _objeto, evento) -> bool:
        if evento.type() in self._TIPOS:
            self._pressao = float(evento.pressure())
            self._quando = time.monotonic()
            try:
                from PySide6.QtGui import QPointingDevice
                self.borracha = evento.pointerType() == QPointingDevice.PointerType.Eraser
            except (AttributeError, ImportError):            # pragma: no cover - Qt sem o tipo
                self.borracha = False
        return False

    def pressao(self) -> float | None:
        """A pressão da última leitura da mesa (de 0 a 1), ou ``None`` com o mouse."""
        return self._pressao if time.monotonic() - self._quando < self.VALIDADE_S else None

    def com_borracha(self) -> bool:
        return self.borracha and self.pressao() is not None


_mesa: Mesa | None = None


def mesa() -> Mesa:
    """A mesa do aplicativo (uma só: a pressão é a da caneta, onde quer que ela esteja)."""
    global _mesa
    if _mesa is None:
        _mesa = Mesa()
    return _mesa


# ---------------------------------------------------------------------- a geometria na tela


def _mapear(t: QTransform, xs, ys) -> tuple[np.ndarray, np.ndarray]:
    xs, ys = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    return xs * t.m11() + ys * t.m21() + t.dx(), xs * t.m12() + ys * t.m22() + t.dy()


def _poligono(x: np.ndarray, y: np.ndarray) -> QPolygonF:
    if not len(x):
        return QPolygonF()
    poligono = fn.create_qpolygonf(len(x))
    pontos = fn.ndarray_from_qpolygonf(poligono)
    pontos[:, 0] = x
    pontos[:, 1] = y
    return poligono


def distancia_a_segmentos(px: float, py: float, xs: np.ndarray, ys: np.ndarray) -> float:
    """A menor distância do ponto à linha que passa por ``(xs, ys)``, em pixels (no NumPy)."""
    if len(xs) == 0:
        return math.inf
    if len(xs) == 1:
        return math.hypot(px - xs[0], py - ys[0])
    ax, ay, bx, by = xs[:-1], ys[:-1], xs[1:], ys[1:]
    dx, dy = bx - ax, by - ay
    comprimento2 = dx * dx + dy * dy
    with np.errstate(invalid="ignore", divide="ignore"):
        u = np.where(comprimento2 > 0, ((px - ax) * dx + (py - ay) * dy) / comprimento2, 0.0)
    u = np.clip(u, 0.0, 1.0)
    cx, cy = ax + u * dx, ay + u * dy
    return float(np.sqrt(np.min((px - cx) ** 2 + (py - cy) ** 2)))


@dataclass
class Geometria:
    """Uma anotação em pixels da tela: os pontos de referência, o retângulo do texto, o caminho do contorno (para o
    clique), o retângulo que ela ocupa e as alças."""

    p0: QPointF
    p1: QPointF | None = None
    texto: str = ""
    retangulo_do_texto: QRectF | None = None
    linha_x: np.ndarray | None = None        # a linha para o clique (seta, linha, cota, desenho, contornos)
    linha_y: np.ndarray | None = None
    area: QRectF | None = None               # o que conta como dentro (as formas cheias, o texto)
    ocupa: QRectF = field(default_factory=QRectF)
    alcas: list[tuple[str, QPointF]] = field(default_factory=list)


def _retangulo_do_texto(texto: str, fonte: QFont, ancora: QPointF, onde: str, folga: float = 0.0) -> QRectF:
    """O retângulo do texto (várias linhas) ancorado: ``onde`` = "be" (o canto de baixo, à esquerda, no ponto), "m"
    (o meio), "c" (em cima do ponto, centrado), "ce" (o canto de cima, à esquerda) ou "d" (à direita, no meio)."""
    medida = QFontMetricsF(fonte).boundingRect(QRectF(0, 0, 4000, 4000), int(Qt.AlignmentFlag.AlignLeft), texto)
    w, h = medida.width() + 2 * folga, medida.height() + 2 * folga
    x, y = ancora.x(), ancora.y()
    if onde == "be":
        return QRectF(x, y - h, w, h)
    if onde == "m":
        return QRectF(x - w / 2, y - h / 2, w, h)
    if onde == "c":
        return QRectF(x - w / 2, y - h - 3, w, h)
    if onde == "ce":
        return QRectF(x, y, w, h)
    return QRectF(x + 8, y - h / 2, w, h)


def _caixa_das_alcas(r: QRectF) -> list[tuple[str, QPointF]]:
    cx, cy = r.center().x(), r.center().y()
    return [("ce", r.topLeft()), ("c", QPointF(cx, r.top())), ("cd", r.topRight()), ("d", QPointF(r.right(), cy)),
            ("bd", r.bottomRight()), ("b", QPointF(cx, r.bottom())), ("be", r.bottomLeft()),
            ("e", QPointF(r.left(), cy))]


def geometria(a: Anotacao, t: QTransform, para_eixo: Callable, tela: QRectF, texto: str) -> Geometria:
    """A anotação ``a`` em pixels: ``t`` leva as coordenadas do eixo à tela, ``para_eixo`` leva o x dos dados ao eixo
    (vetorial), ``tela`` é o retângulo da caixa na tela e ``texto`` o que a anotação escreve (o da cota e o do nível
    já feitos)."""
    fonte = fonte_da_anotacao(a)
    folga = 4.0 if a.caixa else 0.0
    if a.tipo == "desenho":
        pontos = np.asarray(a.pontos, dtype=float)
        xs, ys = _mapear(t, para_eixo(pontos[:, 0]), pontos[:, 1])
        ocupa = QRectF(QPointF(xs.min(), ys.min()), QPointF(xs.max(), ys.max()))
        g = Geometria(QPointF(xs[0], ys[0]), linha_x=xs, linha_y=ys, ocupa=ocupa)
        g.alcas = _caixa_das_alcas(ocupa.adjusted(-3, -3, 3, 3))
        return g
    x = para_eixo(np.array([a.x0] + ([a.x1] if a.x1 is not None else [])))
    y = np.array([a.y0] + ([a.y1 if a.y1 is not None else a.y0] if a.x1 is not None else []))
    xs, ys = _mapear(t, x, y)
    p0 = QPointF(xs[0], ys[0])
    p1 = QPointF(xs[1], ys[1]) if len(xs) > 1 else None
    g = Geometria(p0, p1, texto=texto)
    if a.tipo == "texto":
        r = _retangulo_do_texto(texto, fonte, p0, "be", folga)
        g.retangulo_do_texto = g.area = r
        g.ocupa = QRectF(r)
        g.alcas = [("fonte", r.topRight())]
    elif a.tipo in ("seta", "linha"):
        g.linha_x, g.linha_y = np.array([p1.x(), p0.x()]), np.array([p1.y(), p0.y()])
        g.ocupa = QRectF(p0, p1).normalized()
        if texto:
            centro = p1 if a.tipo == "seta" else QPointF((p0.x() + p1.x()) / 2, (p0.y() + p1.y()) / 2)
            g.retangulo_do_texto = _retangulo_do_texto(texto, fonte, centro, "m" if a.tipo == "seta" else "c", folga)
            g.ocupa = g.ocupa.united(g.retangulo_do_texto)
        g.alcas = [("p0", p0), ("p1", p1)]
    elif a.tipo == "regiao":
        r = QRectF(QPointF(min(p0.x(), p1.x()), tela.top()), QPointF(max(p0.x(), p1.x()), tela.bottom()))
        g.ocupa = r
        g.linha_x = np.array([r.left(), r.left(), np.nan, r.right(), r.right()])
        g.linha_y = np.array([r.top(), r.bottom(), np.nan, r.top(), r.bottom()])
        if texto:
            g.retangulo_do_texto = _retangulo_do_texto(texto, fonte, QPointF(r.left() + 4, r.top() + 4), "ce", folga)
        meio = r.center().y()
        g.alcas = [("x0", QPointF(r.left(), meio)), ("x1", QPointF(r.right(), meio))]
    elif a.tipo == "cota":
        g.linha_x, g.linha_y = np.array([p0.x(), p1.x()]), np.array([p0.y(), p0.y()])
        g.retangulo_do_texto = _retangulo_do_texto(texto, fonte, QPointF((p0.x() + p1.x()) / 2, p0.y()), "c", folga)
        g.ocupa = QRectF(QPointF(min(p0.x(), p1.x()), p0.y() - 7), QPointF(max(p0.x(), p1.x()), p0.y() + 7))
        g.ocupa = g.ocupa.united(g.retangulo_do_texto)
        g.alcas = [("p0", p0), ("p1", QPointF(p1.x(), p0.y()))]
    elif a.tipo in FORMAS:
        r = QRectF(p0, p1).normalized()
        g.ocupa = QRectF(r)
        if a.tipo == "retangulo":
            g.linha_x = np.array([r.left(), r.right(), r.right(), r.left(), r.left()])
            g.linha_y = np.array([r.top(), r.top(), r.bottom(), r.bottom(), r.top()])
        else:
            angulos = np.linspace(0, 2 * np.pi, 65)
            g.linha_x = r.center().x() + r.width() / 2 * np.cos(angulos)
            g.linha_y = r.center().y() + r.height() / 2 * np.sin(angulos)
        if a.preenchimento:
            g.area = r
        if texto:
            g.retangulo_do_texto = _retangulo_do_texto(texto, fonte, r.center(), "m", folga)
        g.alcas = _caixa_das_alcas(r)
    elif a.tipo == "nivel":
        g.linha_x = np.array([tela.left(), tela.right()])
        g.linha_y = np.array([p0.y(), p0.y()])
        g.ocupa = QRectF(QPointF(tela.left(), p0.y() - 3), QPointF(tela.right(), p0.y() + 3))
        if texto:
            g.retangulo_do_texto = _retangulo_do_texto(texto, fonte, QPointF(p0.x() + 4, p0.y() - 2), "be", folga)
            g.ocupa = g.ocupa.united(g.retangulo_do_texto)
        g.alcas = [("nivel", p0)]
    else:                                                       # o marcador
        raio = 4.0 + espessura(a)
        g.area = QRectF(p0.x() - raio, p0.y() - raio, 2 * raio, 2 * raio)
        g.ocupa = QRectF(g.area)
        if texto:
            g.retangulo_do_texto = _retangulo_do_texto(texto, fonte, QPointF(p0.x() + raio - 4, p0.y()), "d", folga)
            g.ocupa = g.ocupa.united(g.retangulo_do_texto)
    return g


def distancia(a: Anotacao, g: Geometria, ponto: QPointF, escolhida: bool) -> float:
    """Quantos pixels separam o ponto da anotação (0 dentro dela). Uma forma vazia só conta no contorno, e a região
    nas bordas e no texto (dentro dela, só quando já está escolhida: o arrasto no meio dela continua andando no
    tempo)."""
    if g.retangulo_do_texto is not None and g.retangulo_do_texto.adjusted(-3, -3, 3, 3).contains(ponto):
        return 0.0
    if g.area is not None and g.area.contains(ponto):
        return 0.0
    if escolhida and a.tipo in ("regiao",) + FORMAS and g.ocupa.contains(ponto):
        return 0.0
    if a.tipo == "marcador":
        return max(0.0, math.hypot(ponto.x() - g.p0.x(), ponto.y() - g.p0.y()) - g.area.width() / 2)
    if g.linha_x is not None:
        xs, ys = g.linha_x, g.linha_y
        if np.isnan(xs).any():                      # trechos separados (as bordas da região)
            partes = np.split(np.arange(len(xs)), np.flatnonzero(np.isnan(xs)))
            return min(distancia_a_segmentos(ponto.x(), ponto.y(), xs[i[~np.isnan(xs[i])]], ys[i[~np.isnan(xs[i])]])
                       for i in partes if (~np.isnan(xs[i])).any())
        d = distancia_a_segmentos(ponto.x(), ponto.y(), xs, ys)
        return max(0.0, d - espessura(a) / 2)
    return math.inf


def mover(a: Anotacao, dx_no_eixo: float, dy: float, para_eixo: Callable, do_eixo: Callable) -> Anotacao:
    """A anotação andada de ``dx_no_eixo`` no eixo x e de ``dy`` no y; com o x dos dados igual ao do eixo, é o
    :meth:`Anotacao.movida`; no espectro em log, cada x anda pela mesma razão."""
    if dx_no_eixo == 0.0 and dy == 0.0:
        return a

    def x(v):
        return do_eixo(para_eixo(np.asarray(v, dtype=float)) + dx_no_eixo)

    if a.tipo == "desenho":
        pontos = np.asarray(a.pontos, dtype=float)
        novos = np.column_stack([x(pontos[:, 0]), pontos[:, 1] + dy])
        return a.com(pontos=tuple(map(tuple, novos.tolist())))
    novos_x = x([a.x0] + ([a.x1] if a.x1 is not None else []))
    return a.com(x0=float(novos_x[0]), y0=a.y0 + dy, x1=float(novos_x[1]) if a.x1 is not None else None,
                 y1=None if a.y1 is None else a.y1 + dy)


# ---------------------------------------------------------------------- o desenho


@dataclass
class Cores:
    """As cores do tema que as anotações usam sem cor própria."""

    texto: str = "#e6e6e6"
    acento: str = "#4ea1ff"
    fundo: str = "#20242c"
    escolha: str = "#4ea1ff"
    marca_texto: str = "#facc15"


def _qcor(cor: str, alfa: float = 1.0) -> QColor:
    c = QColor(cor)
    c.setAlphaF(max(0.0, min(1.0, alfa)))
    return c


def _ponta(p: QPainter, ponta: QPointF, de: QPointF, tamanho: float, estilo: str, cor: QColor, w: float) -> QPointF:
    """A cabeça da seta em ``ponta`` (vindo de ``de``); devolve onde a linha deve parar (para não furar a cabeça)."""
    dx, dy = ponta.x() - de.x(), ponta.y() - de.y()
    comprimento = math.hypot(dx, dy)
    if comprimento < 1e-9 or estilo == "nenhuma":
        return ponta
    ux, uy = dx / comprimento, dy / comprimento
    if estilo == "circulo":
        raio = 2.5 + w
        p.setBrush(cor)
        p.drawEllipse(ponta, raio, raio)
        return ponta
    largura = tamanho * 0.42
    base = QPointF(ponta.x() - ux * tamanho, ponta.y() - uy * tamanho)
    a = QPointF(base.x() - uy * largura, base.y() + ux * largura)
    b = QPointF(base.x() + uy * largura, base.y() - ux * largura)
    if estilo == "aberta":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(QPolygonF([a, ponta, b]))
        return ponta
    p.setBrush(cor)
    p.drawPolygon(QPolygonF([ponta, a, b]))
    return QPointF(ponta.x() - ux * tamanho * 0.7, ponta.y() - uy * tamanho * 0.7)


def _escrever(p: QPainter, a: Anotacao, r: QRectF, texto: str, cor: QColor, cores: Cores,
              alinhar=Qt.AlignmentFlag.AlignLeft) -> None:
    if a.caixa:
        fundo = _qcor(a.preenchimento or cores.fundo, a.opacidade_do_fundo if a.preenchimento else 0.92)
        p.setPen(QPen(cor, 1.0))
        p.setBrush(fundo)
        p.drawRoundedRect(r, 4, 4)
        r = r.adjusted(4, 4, -4, -4)
    p.setFont(fonte_da_anotacao(a))
    p.setPen(cor)
    p.drawText(r, int(alinhar | Qt.AlignmentFlag.AlignVCenter), texto)


def _desenho_com_pressao(p: QPainter, xs, ys, pressoes, w: float, cor: QColor) -> None:
    """A linha à mão livre com a espessura de cada trecho pela pressão: os trechos em 6 grupos de espessura, cada
    grupo um caminho só (um ``drawPath`` por grupo, não um por trecho)."""
    pr = np.asarray(pressoes, dtype=float)
    media = (pr[:-1] + pr[1:]) / 2
    larguras = w * (0.25 + 1.5 * media)
    grupos = np.clip(np.round(larguras / max(w, 1e-6) * 3), 0, 6).astype(int)
    for grupo in np.unique(grupos):
        i = np.flatnonzero(grupos == grupo)
        x = np.empty(2 * len(i))
        y = np.empty(2 * len(i))
        x[0::2], x[1::2] = xs[i], xs[i + 1]
        y[0::2], y[1::2] = ys[i], ys[i + 1]
        caneta = QPen(cor, max(0.5, w * grupo / 3), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin)
        p.setPen(caneta)
        p.drawPath(fn.arrayToQPath(x, y, connect="pairs", finiteCheck=False))


def pintar(p: QPainter, a: Anotacao, g: Geometria, tela: QRectF, cores: Cores) -> None:
    """Desenha a anotação (já em pixels: ``g``) no pintor sem transformação."""
    w = espessura(a)
    cor = _qcor(a.cor or (cores.marca_texto if a.tipo == "desenho" and a.espessura >= 10 and not a.cor
                          else cores.texto), 1.0)
    p.setOpacity(a.opacidade)
    caneta = QPen(cor, w, _TRACOS_DO_QT[a.traco], Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(caneta)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if a.tipo == "texto":
        _escrever(p, a, g.retangulo_do_texto, g.texto, cor, cores)
    elif a.tipo in ("seta", "linha"):
        fim, comeco = g.p0, g.p1
        tamanho = 9.0 + 2.6 * w
        if a.tipo == "seta":
            p.setPen(QPen(cor, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin))
            fim = _ponta(p, g.p0, g.p1, tamanho, a.ponta, cor, w)
            if a.ponta == "dupla":
                comeco = _ponta(p, g.p1, g.p0, tamanho, "cheia", cor, w)
            p.setPen(caneta)
        p.drawLine(QLineF(comeco, fim))
        if g.retangulo_do_texto is not None:
            _escrever(p, a, g.retangulo_do_texto, g.texto, cor, cores, Qt.AlignmentFlag.AlignHCenter)
    elif a.tipo == "regiao":
        r = g.ocupa
        p.fillRect(r, _qcor(a.preenchimento or a.cor or cores.acento, a.opacidade_do_fundo * 0.7))
        borda = QPen(_qcor(a.cor or cores.acento), w, _TRACOS_DO_QT[a.traco])
        p.setPen(borda)
        p.drawLine(QLineF(r.left(), r.top(), r.left(), r.bottom()))
        p.drawLine(QLineF(r.right(), r.top(), r.right(), r.bottom()))
        if g.retangulo_do_texto is not None:
            _escrever(p, a, g.retangulo_do_texto, g.texto, cor, cores)
    elif a.tipo == "cota":
        y = g.p0.y()
        e, d = QPointF(min(g.p0.x(), g.p1.x()), y), QPointF(max(g.p0.x(), g.p1.x()), y)
        p.drawLine(QLineF(e.x(), y - 6, e.x(), y + 6))
        p.drawLine(QLineF(d.x(), y - 6, d.x(), y + 6))
        tamanho = 7.0 + 2.0 * w
        if d.x() - e.x() > 2.2 * tamanho:
            p.setPen(QPen(cor, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.MiterJoin))
            e2 = _ponta(p, e, d, tamanho, "cheia", cor, w)
            d2 = _ponta(p, d, e, tamanho, "cheia", cor, w)
            p.setPen(caneta)
            p.drawLine(QLineF(e2, d2))
        else:
            p.drawLine(QLineF(e, d))
        _escrever(p, a, g.retangulo_do_texto, g.texto, cor, cores, Qt.AlignmentFlag.AlignHCenter)
    elif a.tipo in FORMAS:
        r = g.ocupa
        if a.preenchimento:
            p.setBrush(_qcor(a.preenchimento, a.opacidade_do_fundo))
        if a.tipo == "retangulo":
            p.drawRect(r)
        else:
            p.drawEllipse(r)
        if g.retangulo_do_texto is not None:
            _escrever(p, a, g.retangulo_do_texto, g.texto, cor, cores, Qt.AlignmentFlag.AlignHCenter)
    elif a.tipo == "nivel":
        p.drawLine(QLineF(tela.left(), g.p0.y(), tela.right(), g.p0.y()))
        if g.retangulo_do_texto is not None:
            _escrever(p, a, g.retangulo_do_texto, g.texto, cor, cores)
    elif a.tipo == "marcador":
        _marcador(p, a, g.p0, g.area.width() / 2, cor, w)
        if g.retangulo_do_texto is not None:
            _escrever(p, a, g.retangulo_do_texto, g.texto, cor, cores)
    else:                                                       # o desenho
        xs, ys = g.linha_x, g.linha_y
        if len(xs) == 1:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(cor)
            p.drawEllipse(g.p0, w / 2, w / 2)
        elif a.pressoes:
            _desenho_com_pressao(p, xs, ys, a.pressoes, w, cor)
        else:
            p.drawPolyline(_poligono(xs, ys))
    p.setOpacity(1.0)


def _marcador(p: QPainter, a: Anotacao, c: QPointF, raio: float, cor: QColor, w: float) -> None:
    p.setPen(QPen(cor, max(1.2, w * 0.6), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    cheio = _qcor(a.preenchimento or (a.cor or cor.name()), a.opacidade_do_fundo if a.preenchimento else 1.0)
    x, y, r = c.x(), c.y(), raio
    if a.forma in ("x", "mais"):
        if a.forma == "x":
            p.drawLine(QLineF(x - r, y - r, x + r, y + r))
            p.drawLine(QLineF(x - r, y + r, x + r, y - r))
        else:
            p.drawLine(QLineF(x - r, y, x + r, y))
            p.drawLine(QLineF(x, y - r, x, y + r))
        return
    p.setBrush(cheio)
    if a.forma == "circulo":
        p.drawEllipse(c, r, r)
    elif a.forma == "quadrado":
        p.drawRect(QRectF(x - r * 0.85, y - r * 0.85, 1.7 * r, 1.7 * r))
    elif a.forma == "losango":
        p.drawPolygon(QPolygonF([QPointF(x, y - r), QPointF(x + r, y), QPointF(x, y + r), QPointF(x - r, y)]))
    elif a.forma == "triangulo":
        p.drawPolygon(QPolygonF([QPointF(x, y - r), QPointF(x + r * 0.95, y + r * 0.7),
                                 QPointF(x - r * 0.95, y + r * 0.7)]))
    else:                                                        # a estrela
        pontos = []
        for k in range(10):
            raio = r if k % 2 == 0 else r * 0.45
            angulo = -math.pi / 2 + k * math.pi / 5
            pontos.append(QPointF(x + raio * math.cos(angulo), y + raio * math.sin(angulo)))
        p.drawPolygon(QPolygonF(pontos))


# ---------------------------------------------------------------------- a camada


class CamadaDeAnotacoes(pg.GraphicsObject):
    """As anotações de uma caixa (``dono``: ``areas/analise/anotacoes.py``, que dá as anotações, a ferramenta, o
    estilo das novas, a escolha e recebe as mudanças). ``faixa``: o número que as novas levam."""

    def __init__(self, dono, caixa: pg.ViewBox, faixa: int):
        super().__init__()
        self.dono, self.caixa, self.faixa = dono, caixa, faixa
        self.anotacoes: tuple[Anotacao, ...] = ()
        self.cores = Cores()
        self.setZValue(Z_DA_CAMADA)
        self._na_vista = QRectF()
        self._previas: dict[str, Anotacao] = {}      # o id -> a anotação como está no meio de um arrasto
        self._escondidas: set[str] = set()           # as que a borracha está apagando
        self._nova: Anotacao | None = None           # a que uma ferramenta está criando
        self._gesto: dict | None = None
        self.pinturas = 0

    # ------------------------------------------------------------------ o que mostrar

    def definir(self, anotacoes, cores: Cores) -> None:
        self.anotacoes = tuple(anotacoes)
        self.cores = cores
        ids = {a.id for a in self.anotacoes}
        self._previas = {k: v for k, v in self._previas.items() if k in ids}
        self.update()

    def ids(self) -> list[str]:
        return [a.id for a in self.anotacoes]

    def boundingRect(self) -> QRectF:
        return QRectF(self._na_vista)

    def viewRangeChanged(self) -> None:
        caixa = self.getViewBox()
        retangulo = caixa.viewRect() if caixa is not None else QRectF()
        if retangulo != self._na_vista:
            self.prepareGeometryChange()
            self._na_vista = QRectF(retangulo)
        self.update()

    def viewChanged(self, view, oldView) -> None:
        self.viewRangeChanged()

    def _tela(self, t: QTransform) -> QRectF:
        caixa = self.getViewBox()
        if caixa is None:
            return QRectF()
        return t.mapRect(caixa.viewRect())

    def _visiveis(self) -> list[Anotacao]:
        lista = [self._previas.get(a.id, a) for a in self.anotacoes if a.id not in self._escondidas]
        if self._nova is not None:
            lista.append(self._nova)
        return lista

    def _geometria(self, a: Anotacao, t: QTransform, tela: QRectF) -> Geometria:
        return geometria(a, t, self.dono.para_eixo_np, tela, self.dono.texto_de(a))

    # ------------------------------------------------------------------ a pintura

    def paint(self, p: QPainter, *args) -> None:
        self.pinturas += 1
        visiveis = self._visiveis()
        if not visiveis:
            return
        t = p.transform()
        tela = self._tela(t)
        escolhidas = self.dono.selecionadas
        p.save()
        p.resetTransform()
        p.setClipRect(tela)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        marcar = []
        for a in visiveis:
            try:
                g = self._geometria(a, t, tela)
            except (ValueError, FloatingPointError, OverflowError):
                continue
            if not g.ocupa.adjusted(-60, -60, 60, 60).intersects(tela):
                continue
            pintar(p, a, g, tela, self.cores)
            if a.id in escolhidas:
                marcar.append((a, g))
        for a, g in marcar:
            self._pintar_a_escolha(p, a, g, sozinha=len(escolhidas) == 1)
        p.restore()

    def _pintar_a_escolha(self, p: QPainter, a: Anotacao, g: Geometria, sozinha: bool) -> None:
        cor = QColor(self.cores.escolha)
        contorno = QPen(cor, 1.0, Qt.PenStyle.DashLine)
        contorno.setCosmetic(True)
        p.setPen(contorno)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(g.ocupa.adjusted(-4, -4, 4, 4))
        if not sozinha or a.travada:
            if a.travada:                                       # um cadeado pequeno no canto
                canto = g.ocupa.topRight() + QPointF(6, -12)
                p.setPen(QPen(cor, 1.2))
                p.setBrush(cor)
                p.drawRect(QRectF(canto.x(), canto.y() + 4, 8, 6))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawArc(QRectF(canto.x() + 1.5, canto.y(), 5, 8), 0, 180 * 16)
            return
        p.setPen(QPen(cor, 1.2))
        p.setBrush(QColor(self.cores.fundo))
        meio = LADO_DA_ALCA / 2
        for _nome, ponto in g.alcas:
            p.drawRect(QRectF(ponto.x() - meio, ponto.y() - meio, LADO_DA_ALCA, LADO_DA_ALCA))

    # ------------------------------------------------------------------ o que está no ponto

    def _transformacao(self) -> QTransform:
        """O item na cena (os eventos chegam na cena; a pintura usa a do pintor, a mesma a menos de um deslocamento)."""
        return self.sceneTransform()

    def em(self, ponto_na_cena: QPointF) -> tuple[Anotacao | None, str | None]:
        """A anotação no ponto da cena (a de cima; a escolhida primeiro) e a alça dela ali (ou ``None``)."""
        t = self._transformacao()
        tela = self._tela(t)
        escolhidas = self.dono.selecionadas
        visiveis = [a for a in self._visiveis() if a is not self._nova]
        if len(escolhidas) == 1:
            for a in visiveis:
                if a.id in escolhidas and not a.travada:
                    g = self._geometria(a, t, tela)
                    for nome, centro in g.alcas:
                        if abs(centro.x() - ponto_na_cena.x()) <= LADO_DA_ALCA * 0.75 and \
                                abs(centro.y() - ponto_na_cena.y()) <= LADO_DA_ALCA * 0.75:
                            return a, nome
        ordem = sorted(reversed(visiveis), key=lambda a: a.id not in escolhidas)
        for a in ordem:
            try:
                g = self._geometria(a, t, tela)
            except (ValueError, FloatingPointError, OverflowError):
                continue
            if distancia(a, g, ponto_na_cena, a.id in escolhidas) <= PERTO_PX:
                return a, None
        return None, None

    def _dados(self, ponto_na_cena: QPointF) -> tuple[float, float]:
        """O ponto da cena nas coordenadas dos dados (o x do eixo levado de volta: o log10 do espectro)."""
        v = self.mapFromScene(ponto_na_cena)
        return float(self.dono.do_eixo_np(np.array([v.x()]))[0]), float(v.y())

    # ------------------------------------------------------------------ os eventos do PyQtGraph

    def hoverEvent(self, evento) -> None:
        if evento.isExit():
            self.unsetCursor()
            return
        ferramenta = self.dono.ferramenta
        if ferramenta != "selecionar":
            evento.acceptDrags(Qt.MouseButton.LeftButton)
            evento.acceptClicks(Qt.MouseButton.LeftButton)
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        a, alca = self.em(evento.scenePos())
        if a is None:
            self.unsetCursor()
            return
        evento.acceptClicks(Qt.MouseButton.LeftButton)
        if a.travada:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            return
        evento.acceptDrags(Qt.MouseButton.LeftButton)
        self.setCursor(CURSORES_DAS_ALCAS.get(alca, Qt.CursorShape.SizeAllCursor) if alca
                       else Qt.CursorShape.SizeAllCursor)

    def mouseClickEvent(self, evento) -> None:
        botao, ferramenta = evento.button(), self.dono.ferramenta
        if botao == Qt.MouseButton.LeftButton and ferramenta != "selecionar":
            evento.accept()
            x, y = self._dados(evento.scenePos())
            if ferramenta in FERRAMENTAS_DE_DESENHO:
                self._comecar_desenho(evento.scenePos())
                self._terminar_desenho()
            elif ferramenta in FERRAMENTAS_DE_FORMA:
                self.dono.criar(self._padrao(ferramenta, x, y, evento.scenePos()), self, evento.scenePos())
            return
        a, _alca = self.em(evento.scenePos())
        if botao == Qt.MouseButton.LeftButton:
            if a is None:
                if self.dono.selecionadas and not evento.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.dono.escolher(())
                evento.ignore()
                return
            evento.accept()
            if evento.double():
                self.dono.editar_texto(a, self, evento.scenePos())
                return
            somar = bool(evento.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.dono.escolher((a.id,), somar=somar)
            return
        if botao == Qt.MouseButton.RightButton and a is not None and a.id not in self.dono.selecionadas:
            self.dono.escolher((a.id,))
        evento.ignore()                                # o menu é o da caixa

    def mouseDragEvent(self, evento) -> None:
        if evento.button() != Qt.MouseButton.LeftButton:
            evento.ignore()
            return
        if evento.isStart():
            if not self._comecar(evento):
                evento.ignore()
                return
        elif self._gesto is None:
            evento.ignore()
            return
        evento.accept()
        self._continuar(evento.scenePos(), evento.modifiers())
        if evento.isFinish():
            self._terminar()

    # ------------------------------------------------------------------ os gestos

    def _comecar(self, evento) -> bool:
        ferramenta = self.dono.ferramenta
        comeco = evento.buttonDownScenePos()
        if ferramenta in FERRAMENTAS_DE_DESENHO and not mesa().com_borracha():
            self._comecar_desenho(comeco)
            return True
        if ferramenta == "borracha" or (ferramenta in FERRAMENTAS_DE_DESENHO and mesa().com_borracha()):
            self._gesto = {"modo": "borracha", "anterior": comeco}
            self._apagar_perto(comeco, comeco)
            return True
        if ferramenta in FERRAMENTAS_DE_FORMA:
            x, y = self._dados(comeco)
            self._nova = self._padrao(ferramenta, x, y, comeco, arrastando=True)
            self._gesto = {"modo": "criar", "comeco": comeco, "ultima": comeco, "x": x, "y": y}
            return True
        a, alca = self.em(comeco)
        if a is None or a.travada:
            return False
        if a.id not in self.dono.selecionadas:
            somar = bool(evento.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.dono.escolher((a.id,), somar=somar)
        movidas = [b for b in self.anotacoes if b.id in self.dono.selecionadas and not b.travada] if alca is None \
            else [a]
        self._gesto = {"modo": "alca" if alca else "mover", "alca": alca, "comeco": comeco,
                       "originais": {b.id: b for b in movidas}, "alvo": a.id}
        return True

    def _continuar(self, agora: QPointF, modificadores) -> None:
        g = self._gesto
        if g is None:
            return
        modo = g["modo"]
        if modo == "desenho":
            self._seguir_desenho(agora)
        elif modo == "borracha":
            self._apagar_perto(g["anterior"], agora)
            g["anterior"] = agora
        elif modo == "criar":
            self._esticar_a_nova(agora, modificadores)
        elif modo == "mover":
            v0, v = self.mapFromScene(g["comeco"]), self.mapFromScene(agora)
            dx, dy = v.x() - v0.x(), v.y() - v0.y()          # no eixo (o x do espectro em log: o log10)
            if modificadores & Qt.KeyboardModifier.ShiftModifier:         # só na direção maior
                tela = agora - g["comeco"]
                if abs(tela.x()) >= abs(tela.y()):
                    dy = 0.0
                else:
                    dx = 0.0
            self._previas = {i: self._mover(b, dx, dy) for i, b in g["originais"].items()}
        else:
            original = g["originais"][g["alvo"]]
            nova = self._pela_alca(original, g["alca"], agora, modificadores)
            if nova is not None:
                self._previas = {original.id: nova}
        self.update()

    def _terminar(self) -> None:
        g, self._gesto = self._gesto, None
        if g is None:
            return
        modo = g["modo"]
        if modo == "desenho":
            self._terminar_desenho()
        elif modo == "borracha":
            ids, self._escondidas = tuple(self._escondidas), set()
            if ids:
                self.dono.apagar(ids, self.dono.tr("Apagar {} desenho(s)").format(len(ids)))
        elif modo == "criar":
            nova, self._nova = self._nova, None
            tela = QLineF(g["comeco"], g["ultima"]).length()
            if nova is not None:
                if tela < MINIMO_DO_ARRASTO_PX:
                    nova = self._padrao(nova.tipo, g["x"], g["y"], g["comeco"])
                self.dono.criar(nova, self, g["comeco"])
        else:
            previas, self._previas = self._previas, {}
            mudadas = [b for i, b in previas.items() if b != g["originais"].get(i)]
            if mudadas:
                texto = self.dono.tr("Mover a anotação") if modo == "mover" else self.dono.tr("Mudar a forma da anotação")
                if modo == "mover" and len(mudadas) > 1:
                    texto = self.dono.tr("Mover {} anotações").format(len(mudadas))
                self.dono.mudar(mudadas, texto)
        self.update()

    def _mover(self, a: Anotacao, dx_no_eixo: float, dy: float) -> Anotacao:
        """A anotação andada de ``dx_no_eixo`` no eixo x (no espectro em log, cada x anda pela mesma razão) e ``dy``."""
        return mover(a, dx_no_eixo, 0.0 if a.tipo == "regiao" else dy, self.dono.para_eixo_np, self.dono.do_eixo_np)

    # -- as alças

    def _pela_alca(self, a: Anotacao, alca: str, agora: QPointF, modificadores) -> Anotacao | None:
        x, y = self._dados(agora)
        try:
            if alca == "p0":
                return a.com(x0=x, y0=y)
            if alca == "p1":
                if a.tipo == "cota":
                    return a.com(x1=x, y0=y)
                return a.com(x1=x, y1=y)
            if alca in ("x0", "x1"):
                outra = a.x1 if alca == "x0" else a.x0
                if x == outra:
                    return None
                return a.com(x0=min(x, outra), x1=max(x, outra))
            if alca == "nivel":
                return a.com(x0=x, y0=y)
            if alca == "fonte":
                return self._fonte_pela_alca(a, agora)
            return self._esticar(a, alca, x, y, modificadores)
        except ValueError:
            return None

    def _fonte_pela_alca(self, a: Anotacao, agora: QPointF) -> Anotacao:
        t = self._transformacao()
        g = self._geometria(self._gesto["originais"][a.id], t, self._tela(t))
        altura_antes = max(g.retangulo_do_texto.height(), 1.0)
        canto = g.retangulo_do_texto.bottomLeft()
        altura = max(6.0, canto.y() - agora.y())
        pt = tamanho_da_fonte_px(a) / _PONTO_POR_PIXEL * altura / altura_antes
        return a.com(fonte=round(min(96.0, max(4.0, pt)), 1))

    def _esticar(self, a: Anotacao, alca: str, x: float, y: float, modificadores) -> Anotacao | None:
        x0, x1, y0, y1 = a.limites()
        if a.tipo in FORMAS or a.tipo == "desenho":
            # Os cantos na tela: "c" é o de cima (o y maior nos dados), "e" o da esquerda.
            nx0, nx1, ny0, ny1 = x0, x1, y0, y1
            if "e" in alca:
                nx0 = x
            if "d" in alca:
                nx1 = x
            if "c" in alca:
                ny1 = y
            if "b" in alca:
                ny0 = y
            if modificadores & Qt.KeyboardModifier.ShiftModifier and len(alca) == 2 and x1 != x0 and y1 != y0:
                fx, fy = (nx1 - nx0) / (x1 - x0), (ny1 - ny0) / (y1 - y0)
                f = max(abs(fx), abs(fy))
                fx, fy = math.copysign(f, fx), math.copysign(f, fy)
                if "e" in alca:
                    nx0 = x1 - fx * (x1 - x0)
                else:
                    nx1 = x0 + fx * (x1 - x0)
                if "b" in alca:
                    ny0 = y1 - fy * (y1 - y0)
                else:
                    ny1 = y0 + fy * (y1 - y0)
            if a.tipo == "desenho":
                if nx0 == nx1 and x0 != x1 or ny0 == ny1 and y0 != y1:
                    return None
                return a.esticada((x0, x1, y0, y1), (nx0, nx1, ny0, ny1))
            if nx0 == nx1 or ny0 == ny1:
                return None
            return a.com(x0=nx0, x1=nx1, y0=ny0, y1=ny1)
        return None

    # -- a criação

    def _padrao(self, tipo: str, x: float, y: float, na_cena: QPointF, arrastando: bool = False) -> Anotacao:
        """A anotação ``tipo`` posta em ``(x, y)``: no arrasto, do tamanho zero (o arrasto a estica); no clique, com o
        tamanho padrão na tela."""
        estilo = self.dono.estilo_novo(tipo)
        largura, altura = TAMANHO_PADRAO_PX
        if arrastando:
            fim = na_cena + QPointF(1e-3, -1e-3)
        else:
            fim = na_cena + QPointF(largura, -altura) if tipo not in ("seta",) else na_cena + QPointF(-largura * 0.7,
                                                                                                      -altura * 0.8)
        x1, y1 = self._dados(fim)
        if tipo in ("texto", "marcador", "nivel"):
            return Anotacao(self.dono.novo_id(), tipo, x, y, faixa=self.faixa, **estilo)
        if tipo in ("seta", "linha"):
            return Anotacao(self.dono.novo_id(), tipo, x, y, x1, y1, faixa=self.faixa, **estilo)
        if tipo == "regiao":
            return Anotacao(self.dono.novo_id(), tipo, x, 0.0, x1 if x1 != x else x + 1e-12, faixa=self.faixa, **estilo)
        if tipo == "cota":
            return Anotacao(self.dono.novo_id(), tipo, x, y, x1 if x1 != x else x + 1e-12, faixa=self.faixa, **estilo)
        y1 = y1 if y1 != y else y + 1e-12
        x1 = x1 if x1 != x else x + 1e-12
        return Anotacao(self.dono.novo_id(), tipo, x, y, x1, y1, faixa=self.faixa, **estilo)

    def _esticar_a_nova(self, agora: QPointF, modificadores) -> None:
        a, g = self._nova, self._gesto
        if a is None:
            return
        g["ultima"] = agora
        x, y = self._dados(agora)
        try:
            if a.tipo in ("texto", "marcador", "nivel"):
                self._nova = a.com(x0=x, y0=y)
            elif a.tipo in ("seta", "linha"):
                if modificadores & Qt.KeyboardModifier.ShiftModifier:       # na horizontal ou na vertical
                    tela = agora - g["comeco"]
                    x, y = (x, g["y"]) if abs(tela.x()) >= abs(tela.y()) else (g["x"], y)
                if a.tipo == "seta":       # a seta aponta para onde o arrasto começou: o alvo é o primeiro clique
                    self._nova = a.com(x0=g["x"], y0=g["y"], x1=x, y1=y)
                else:
                    self._nova = a.com(x1=x, y1=y)
            elif a.tipo in ("regiao", "cota"):
                if x != g["x"]:
                    self._nova = a.com(x0=g["x"], x1=x)
            elif x != g["x"] and y != g["y"]:
                if modificadores & Qt.KeyboardModifier.ShiftModifier:       # o quadrado e o círculo, na tela
                    tela = agora - g["comeco"]
                    lado = max(abs(tela.x()), abs(tela.y()))
                    canto = g["comeco"] + QPointF(math.copysign(lado, tela.x() or 1), math.copysign(lado, tela.y() or 1))
                    x, y = self._dados(canto)
                self._nova = a.com(x0=g["x"], y0=g["y"], x1=x, y1=y)
        except ValueError:
            pass

    # -- o desenho à mão livre

    def _comecar_desenho(self, comeco: QPointF) -> None:
        x, y = self._dados(comeco)
        estilo = self.dono.estilo_novo(self.dono.ferramenta)
        pressao = mesa().pressao()
        self._gesto = {"modo": "desenho", "pontos": [(x, y)], "tela": comeco,
                       "pressoes": [pressao] if pressao is not None else None}
        self._nova = Anotacao(self.dono.novo_id(), "desenho", x, y, faixa=self.faixa, pontos=((x, y),), **estilo)

    def _seguir_desenho(self, agora: QPointF) -> None:
        g = self._gesto
        if QLineF(g["tela"], agora).length() < PASSO_DO_DESENHO_PX:
            return
        g["tela"] = agora
        g["pontos"].append(self._dados(agora))
        if g["pressoes"] is not None:
            pressao = mesa().pressao()
            g["pressoes"].append(pressao if pressao is not None else g["pressoes"][-1])
        self._nova = self._nova.com(pontos=tuple(g["pontos"]),
                                    pressoes=tuple(g["pressoes"]) if g["pressoes"] is not None else ())

    def _terminar_desenho(self) -> None:
        nova, self._nova, self._gesto = self._nova, None, None
        if nova is not None:
            self.dono.criar(nova, self, None)
        self.update()

    # -- a borracha

    def _apagar_perto(self, de: QPointF, para: QPointF) -> None:
        t = self._transformacao()
        tela = self._tela(t)
        xs, ys = np.array([de.x(), para.x()]), np.array([de.y(), para.y()])
        for a in self.anotacoes:
            if a.tipo != "desenho" or a.travada or a.id in self._escondidas:
                continue
            g = self._geometria(a, t, tela)
            if not g.ocupa.adjusted(-RAIO_DA_BORRACHA_PX, -RAIO_DA_BORRACHA_PX, RAIO_DA_BORRACHA_PX,
                                    RAIO_DA_BORRACHA_PX).intersects(QRectF(de, para).normalized()
                                                                     .adjusted(-1, -1, 1, 1)):
                continue
            # A distância entre o trecho da borracha e a linha: dos pontos de uma até a outra, nos dois sentidos.
            perto = min(distancia_a_segmentos(de.x(), de.y(), g.linha_x, g.linha_y),
                        distancia_a_segmentos(para.x(), para.y(), g.linha_x, g.linha_y),
                        min((distancia_a_segmentos(px, py, xs, ys) for px, py in zip(g.linha_x, g.linha_y)),
                            default=math.inf))
            if perto <= RAIO_DA_BORRACHA_PX + espessura(a) / 2:
                self._escondidas.add(a.id)
        self.update()

    def cancelar(self) -> None:
        """Larga o gesto do meio (o Esc, a ferramenta trocada): nada muda."""
        self._gesto, self._nova, self._previas, self._escondidas = None, None, {}, set()
        self.update()


__all__ = ["FERRAMENTAS", "FERRAMENTAS_DE_DESENHO", "FERRAMENTAS_DE_FORMA", "CamadaDeAnotacoes", "Cores",
           "Geometria", "Mesa", "distancia", "geometria", "mesa", "mover", "pintar"]
