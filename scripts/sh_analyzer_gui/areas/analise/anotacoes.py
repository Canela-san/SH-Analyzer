"""As anotações de uma vista nos gráficos da Análise (a F5.8; AN-11): o texto, a seta, a região e a cota de Δt (Δf
no espectro), desenhadas sobre os traços de cada caixa e postas, mudadas e tiradas pelo clique direito.

* **O desenho** (:meth:`AnotacoesDaVista.refazer`, a cada mudança das anotações, das faixas ou do tema): itens do
  PyQtGraph na caixa da faixa da anotação, por cima dos traços e sem entrar no ajuste automático. A seta é a linha e
  a ponta, que acompanha a direção dela na tela (o zoom muda o ângulo); a região é a faixa entre dois x, que se arrasta
  pelas bordas (um passo de desfazer a cada arrasto); a cota é a linha com as duas pontas e o Δ em cima.
* **O menu** (:meth:`AnotacoesDaVista.acoes`, o clique direito numa caixa): pôr um texto ali, uma seta que aponta
  ali, uma região e uma cota (entre os cursores, se ligados; senão, em volta do clique); e, perto de uma anotação,
  mudar o texto dela ou tirá-la. Cada um é um passo de desfazer (``MudarAnotacoes``).
* **As coordenadas** são as dos dados (``dados/anotacoes.py``); ``para_eixo`` e ``do_eixo`` levam o x à posição na
  caixa (o log10 da frequência logarítmica do espectro).
"""

from __future__ import annotations

import math
from collections.abc import Callable

import pyqtgraph as pg
from PySide6.QtCore import QObject, QPointF
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QInputDialog, QLineEdit, QMenu, QWidget
from shiboken6 import isValid

from ...dados.anotacoes import TIPOS, Anotacao, texto_da_cota
from ...modelo.comandos import MudarAnotacoes
from ...modelo.objetos import Projeto, Vista, novo_id
from ...tema.aplicar import aparencia

Z_DAS_ANOTACOES = 30
PERTO_PX = 12.0                  # o clique a até isto de uma anotação é nela
FOLGA_DA_REGIAO = 0.05           # sem os cursores, a região e a cota têm 2 × isto da janela, em volta do clique


def _identidade(v: float) -> float:
    return v


class AnotacoesDaVista(QObject):
    """As anotações de ``vista`` nas caixas que ``caixa_da_faixa(numero)`` dá (``None``: a faixa não está na
    tela). ``separador()``: o separador decimal dos números da cota; ``frequencia``: o Δf do espectro."""

    def __init__(self, vista: Vista, projeto: Projeto, caixa_da_faixa: Callable[[int], pg.ViewBox | None], *,
                 frequencia: bool = False, para_eixo: Callable[[float], float] = _identidade,
                 do_eixo: Callable[[float], float] = _identidade, separador: Callable[[], str] = lambda: ",",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.vista, self.projeto, self.caixa_da_faixa = vista, projeto, caixa_da_faixa
        self.frequencia, self.para_eixo, self.do_eixo, self.separador = frequencia, para_eixo, do_eixo, separador
        self.pedir_texto = self._pedir_texto              # os testes trocam (o diálogo do sistema)
        self.itens: dict[str, list] = {}                  # o id da anotação -> os itens dela
        self._caixa_dos_itens: dict[str, pg.ViewBox] = {}
        self._setas: list[tuple] = []                     # (ponta, caixa, de, para): o ângulo segue a tela
        self._caixas_ouvidas: set[int] = set()
        vista.mudou.connect(self._vista_mudou)

    def _vista_mudou(self, _vista, campos) -> None:
        if "anotacoes" in campos:
            self.refazer()

    # ------------------------------------------------------------------ o desenho

    def limpar(self) -> None:
        for id_, itens in self.itens.items():
            caixa = self._caixa_dos_itens[id_]
            if not isValid(caixa):                      # a faixa foi apagada, e os itens com ela
                continue
            for item in itens:
                if isValid(item) and item.scene() is not None:
                    caixa.removeItem(item)
        self.itens, self._caixa_dos_itens, self._setas = {}, {}, []

    def refazer(self) -> None:
        self.limpar()
        t = aparencia().tema
        for a in self.vista.anotacoes:
            caixa = self.caixa_da_faixa(a.faixa)
            if caixa is not None:
                self.itens[a.id] = self._desenhar(caixa, a, t)
                self._caixa_dos_itens[a.id] = caixa
                if id(caixa) not in self._caixas_ouvidas:
                    self._caixas_ouvidas.add(id(caixa))
                    caixa.sigTransformChanged.connect(self._girar_as_setas)
        self._girar_as_setas()

    def _por(self, caixa, item) -> None:
        item.setZValue(Z_DAS_ANOTACOES)
        caixa.addItem(item, ignoreBounds=True)

    def _texto(self, caixa, texto: str, x: float, y: float, ancora, cor: QColor):
        item = pg.TextItem(texto, color=cor, anchor=ancora)
        item.setPos(x, y)
        self._por(caixa, item)
        return item

    def _desenhar(self, caixa, a: Anotacao, t) -> list:
        cor, caneta = QColor(t.texto), pg.mkPen(QColor(t.texto2), width=1.5)
        x0 = self.para_eixo(a.x0)
        itens = []
        if a.tipo == "texto":
            itens.append(self._texto(caixa, a.texto or TIPOS["texto"], x0, a.y0, (0, 1), cor))
        elif a.tipo == "seta":
            x1 = self.para_eixo(a.x1)
            linha = pg.PlotCurveItem([x1, x0], [a.y1, a.y0], pen=caneta)
            ponta = pg.ArrowItem(pos=(x0, a.y0), angle=0, headLen=11, tipAngle=32, tailLen=0, pen=caneta,
                                 brush=QColor(t.texto2))
            self._por(caixa, linha)
            self._por(caixa, ponta)
            self._setas.append((ponta, caixa, (x1, a.y1), (x0, a.y0)))
            itens += [linha, ponta]
            if a.texto:
                itens.append(self._texto(caixa, a.texto, x1, a.y1, (0.5, 0.5), cor))
        elif a.tipo == "regiao":
            fundo = QColor(t.acento)
            fundo.setAlphaF(0.14)
            regiao = pg.LinearRegionItem((x0, self.para_eixo(a.x1)), brush=pg.mkBrush(fundo), movable=True,
                                         pen=pg.mkPen(QColor(t.acento), width=1))
            regiao.sigRegionChangeFinished.connect(lambda r, id_=a.id: self._regiao_arrastada(id_, r))
            self._por(caixa, regiao)
            itens.append(regiao)
            if a.texto:
                pg.InfLineLabel(regiao.lines[0], a.texto, position=0.96, anchors=[(0, 0), (0, 0)], color=cor)
        else:
            x1 = self.para_eixo(a.x1)
            linha = pg.PlotCurveItem([x0, x1], [a.y0, a.y0], pen=caneta)
            self._por(caixa, linha)
            itens.append(linha)
            for x, angulo in ((x0, 0), (x1, 180)):
                ponta = pg.ArrowItem(pos=(x, a.y0), angle=angulo, headLen=9, tipAngle=34, tailLen=0, pen=caneta,
                                     brush=QColor(t.texto2))
                self._por(caixa, ponta)
                itens.append(ponta)
            rotulo = texto_da_cota(a, frequencia=self.frequencia, separador=self.separador())
            itens.append(self._texto(caixa, rotulo, (x0 + x1) / 2, a.y0, (0.5, 1), cor))
        return itens

    def _girar_as_setas(self, *_a) -> None:
        """A ponta de cada seta na direção da linha, na tela (``ArrowItem``: 0° aponta para a esquerda)."""
        for ponta, caixa, de, para in self._setas:
            if not isValid(ponta) or not isValid(caixa):
                continue
            a, b = caixa.mapViewToScene(QPointF(*de)), caixa.mapViewToScene(QPointF(*para))
            dx, dy = b.x() - a.x(), b.y() - a.y()
            if dx or dy:
                ponta.setStyle(angle=math.degrees(math.atan2(-dy, -dx)))

    # ------------------------------------------------------------------ mudar

    def _empilhar(self, anotacoes, texto: str) -> None:
        self.projeto.pilha.push(MudarAnotacoes(self.vista, anotacoes, texto=texto))

    def por(self, anotacao: Anotacao) -> None:
        self._empilhar(self.vista.anotacoes + (anotacao,),
                       self.tr("Pôr uma anotação ({})").format(TIPOS[anotacao.tipo].lower()))

    def trocar(self, anotacao: Anotacao, texto: str) -> None:
        self._empilhar(tuple(anotacao if a.id == anotacao.id else a for a in self.vista.anotacoes), texto)

    def tirar(self, id_: str) -> None:
        self._empilhar(tuple(a for a in self.vista.anotacoes if a.id != id_), self.tr("Tirar uma anotação"))

    def _regiao_arrastada(self, id_: str, regiao) -> None:
        a = next((a for a in self.vista.anotacoes if a.id == id_), None)
        if a is None:
            return
        x0, x1 = (self.do_eixo(v) for v in regiao.getRegion())
        if (x0, x1) != (a.x0, a.x1) and x0 != x1:
            self.trocar(a.com(x0=min(x0, x1), x1=max(x0, x1)), self.tr("Mover uma região"))

    # ------------------------------------------------------------------ o menu

    def perto(self, caixa, x: float, y: float) -> Anotacao | None:
        """A anotação desta caixa em que o ponto (nas unidades dos dados) cai, ou a mais perto até :data:`PERTO_PX`."""
        clique = caixa.mapViewToScene(QPointF(self.para_eixo(x), y))
        melhor, distancia = None, PERTO_PX
        for a in self.vista.anotacoes:
            if self.caixa_da_faixa(a.faixa) is not caixa:
                continue
            if a.tipo == "regiao" and a.x0 <= x <= a.x1:
                return a
            pontos = [(a.x0, a.y0)] + ([(a.x1, a.y1 if a.y1 is not None else a.y0)] if a.x1 is not None else [])
            if a.tipo == "cota":
                pontos.append(((a.x0 + a.x1) / 2, a.y0))
            for px, py in pontos:
                p = caixa.mapViewToScene(QPointF(self.para_eixo(px), py))
                d = math.hypot(p.x() - clique.x(), p.y() - clique.y())
                if d < distancia:
                    melhor, distancia = a, d
        return melhor

    def acoes(self, caixa, faixa: int, x: float, y: float, regiao: tuple[float, float] | None,
              parent: QObject | None = None) -> list[QAction]:
        """As ações do clique direito em ``(x, y)`` (nas unidades dos dados) na caixa da ``faixa``; ``regiao``: os
        cursores ligados."""
        (v0, v1), (w0, w1) = caixa.viewRange()
        largura = self.do_eixo(v1) - self.do_eixo(v0)
        em_volta = regiao or (x - FOLGA_DA_REGIAO * largura, x + FOLGA_DA_REGIAO * largura)
        delta = "Δf" if self.frequencia else "Δt"
        entre = self.tr(" entre os cursores") if regiao else ""
        acoes = []

        def acao(texto: str, funcao) -> None:
            a = QAction(texto, parent or self)
            a.triggered.connect(funcao)
            acoes.append(a)

        acao(self.tr("Pôr um texto aqui…"), lambda: self._com_texto(Anotacao(novo_id(), "texto", x, y, faixa=faixa)))
        acao(self.tr("Pôr uma seta que aponta aqui…"), lambda: self._com_texto(Anotacao(
            novo_id(), "seta", x, y, self.do_eixo(self.para_eixo(x) - 0.1 * (v1 - v0)), y + 0.15 * (w1 - w0),
            faixa=faixa), vazio=True))
        acao(self.tr("Marcar uma região{}").format(entre), lambda: self.por(Anotacao(
            novo_id(), "regiao", em_volta[0], 0.0, em_volta[1], faixa=faixa)))
        acao(self.tr("Pôr uma cota de {}{}").format(delta, entre), lambda: self.por(Anotacao(
            novo_id(), "cota", em_volta[0], y, em_volta[1], faixa=faixa)))
        alvo = self.perto(caixa, x, y)
        if alvo is not None:
            nome = alvo.texto or TIPOS[alvo.tipo].lower()
            separador = QAction(parent or self)
            separador.setSeparator(True)
            acoes.append(separador)
            acao(self.tr("Mudar o texto de “{}”…").format(nome), lambda: self._mudar_o_texto(alvo))
            acao(self.tr("Tirar “{}”").format(nome), lambda: self.tirar(alvo.id))
        return acoes

    def menu(self, caixa, faixa: int, x: float, y: float, regiao, posicao_na_tela) -> None:
        menu = QMenu(self.parent())
        for a in self.acoes(caixa, faixa, x, y, regiao, menu):
            menu.addAction(a)
        menu.exec(posicao_na_tela)

    def _com_texto(self, a: Anotacao, *, vazio: bool = False) -> None:
        texto = self.pedir_texto(self.tr("Anotar"), self.tr("O texto (vazio: sem texto):") if vazio
                                 else self.tr("O texto:"), "")
        if texto is None or (not vazio and not texto.strip()):
            return
        self.por(a.com(texto=texto.strip()))

    def _mudar_o_texto(self, a: Anotacao) -> None:
        texto = self.pedir_texto(self.tr("Mudar o texto"), self.tr("O texto:"), a.texto)
        if texto is not None and texto.strip() != a.texto and (texto.strip() or a.tipo != "texto"):
            self.trocar(a.com(texto=texto.strip()), self.tr("Mudar o texto de uma anotação"))

    def _pedir_texto(self, titulo: str, rotulo: str, texto: str) -> str | None:
        janela = self.parent().window() if isinstance(self.parent(), QWidget) else None
        valor, ok = QInputDialog.getText(janela, titulo, rotulo, QLineEdit.EchoMode.Normal, texto)
        return valor if ok else None
