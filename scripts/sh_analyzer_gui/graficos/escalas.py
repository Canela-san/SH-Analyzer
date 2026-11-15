"""A escala própria de cada traço num gráfico com vários (docs/gui-plan.md, 9.2): uma faixa da vista de tempo, o
gráfico do espectro.

* **Por padrão os traços dividem os eixos:** o zoom e o pan mexem em todos juntos.
* **O cadeado:** um traço destravado ganha a sua escala. Os gestos com ele selecionado mexem só nele (a corrente de
  2 A ampliada ao lado da tensão de 220 V), e os gestos dos outros não o tiram do lugar na tela. Travado de novo, ele
  volta a andar com os outros, na escala que ganhou; **"Mesma escala"** o põe de volta na escala comum.
* **O Y sempre; o tempo, onde a caixa o permite** (``com_tempo``): na vista de tempo, o destravado tem também o seu
  tempo (o zoom e o pan do tempo com ele selecionado são só dele). No espectro, a frequência é uma só.
* **Só o desenho muda:** a escala é a transformação do item na caixa (``na vista = k·u + c`` em cada eixo). Os
  valores e os tempos do traço (a consulta, as medidas, os limites) ficam na unidade dele; quem mede no tempo de um
  traço de tempo próprio (as medidas, o trecho do espectro) converte o tempo da vista para o dele
  (:meth:`Escala.x`, ``no_traco``).
* **Os eixos mostram o traço de referência:** no Y, o último selecionado nesta caixa ou, sem seleção, o primeiro
  travado (os números pela escala dele, e a vista põe o rótulo com a unidade); no tempo, a vista escolhe (o último
  selecionado nela).
* **Quem um gesto mexe:** os traços selecionados nesta caixa. Se todos estão destravados, só eles mudam (a caixa
  fica). Se algum está travado, ou nada está selecionado, o gesto é da caixa: os travados andam, os destravados
  selecionados andam junto e os outros destravados ficam onde estão na tela.

:class:`CaixaComEscalas` é a ``ViewBox`` que passa os gestos (``scaleBy`` e ``translateBy``, que todos os gestos do
PyQtGraph e os da faixa usam) por :class:`EscalasDaCaixa`. Uma mudança da faixa feita pelo programa (``setRange``: o
ajuste, a vista que fica, o tempo ligado de outra faixa) não é um gesto: ela vale para a caixa.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

import pyqtgraph as pg
from pyqtgraph import Point
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QTransform


@dataclass(frozen=True)
class Afim:
    """Um eixo da escala de um traço: ``na vista = k·u + c`` (``k`` > 0), com ``u`` o valor ou o tempo do traço."""

    k: float = 1.0
    c: float = 0.0

    @property
    def comum(self) -> bool:
        return self.k == 1.0 and self.c == 0.0

    def na_vista(self, u: float) -> float:
        return self.k * u + self.c

    def no_traco(self, v: float) -> float:
        return (v - self.c) / self.k

    def ampliada(self, fator: float, centro: float) -> Afim:
        """O zoom como o ``scaleBy`` da caixa: a faixa visível ``fator`` vezes maior (``fator`` > 1 afasta), em volta
        de ``centro`` (na vista). O traço muda, e a caixa fica."""
        return Afim(self.k / fator, centro + (self.c - centro) / fator)

    def deslocada(self, d: float) -> Afim:
        """O pan como o ``translateBy`` da caixa: a vista anda ``d`` (o traço anda ``-d``)."""
        return Afim(self.k, self.c - d)

    def acompanhando(self, antes: tuple[float, float], depois: tuple[float, float]) -> Afim:
        """O eixo que deixa o traço no mesmo lugar da tela quando a faixa da caixa vai de ``antes`` para ``depois``."""
        largura = antes[1] - antes[0]
        if largura == 0 or not math.isfinite(largura):
            return self
        r = (depois[1] - depois[0]) / largura
        return Afim(self.k * r, depois[0] + (self.c - antes[0]) * r)

    @classmethod
    def enquadrando(cls, limites: tuple[float, float], faixa: tuple[float, float], folga: float) -> Afim:
        """O eixo que põe ``limites`` (do traço) na faixa ``faixa`` da vista, com a ``folga`` de cada lado (a fração
        da largura dos dados, como o ``padding`` do PyQtGraph)."""
        a, b = sorted(limites)
        largura = b - a
        if largura <= 0:
            largura = max(abs(a), 1.0) * 1e-3          # um traço constante: no meio, com uma altura qualquer
            a -= largura / 2
        a -= folga * largura
        largura *= 1 + 2 * folga
        k = (faixa[1] - faixa[0]) / largura
        return cls(k, faixa[0] - k * a)


@dataclass(frozen=True)
class Escala:
    """Onde um traço é desenhado na caixa: o tempo (``x``) e o valor (``y``)."""

    x: Afim = field(default_factory=Afim)
    y: Afim = field(default_factory=Afim)

    @property
    def comum(self) -> bool:
        return self.x.comum and self.y.comum

    def transformacao(self) -> QTransform:
        return QTransform(self.x.k, 0.0, 0.0, self.y.k, self.x.c, self.y.c)

    def ampliada(self, fator_x: float | None, fator_y: float | None, centro: Point) -> Escala:
        return Escala(self.x if fator_x is None else self.x.ampliada(fator_x, centro.x()),
                      self.y if fator_y is None else self.y.ampliada(fator_y, centro.y()))

    def deslocada(self, dx: float | None, dy: float | None) -> Escala:
        return Escala(self.x if dx is None else self.x.deslocada(dx), self.y if dy is None else self.y.deslocada(dy))


COMUM = Escala()


def manter_o_y(caixa: pg.ViewBox, limites) -> bool:
    """Depois de uma mudança nos dados (uma etapa da cadeia, outro método do espectro), **o Y fica onde está**: a
    posição e a escala que o usuário escolheu valem mais do que um ajuste automático. A exceção é não sobrar nada à
    vista: se nenhum dos ``limites`` (o mínimo e o máximo de cada traço no trecho visível, na unidade do eixo) cruza
    a faixa visível, ela anda até o meio deles, **com a mesma altura** (tirar o DC de um sinal em 2,5 V leva o traço
    para o 0, e a vista vai junto, sem mudar o zoom). Devolve se andou."""
    limites = [(a, b) for a, b in limites if math.isfinite(a) and math.isfinite(b)]
    if not limites:
        return False
    baixo, alto = min(a for a, _ in limites), max(b for _, b in limites)
    _, (y0, y1) = caixa.viewRange()
    if alto >= y0 and baixo <= y1:
        return False
    meia = (y1 - y0) / 2
    centro = (baixo + alto) / 2
    caixa.setYRange(centro - meia, centro + meia, padding=0)
    return True


class EscalasDaCaixa(QObject):
    """As escalas dos traços de uma caixa (ver o começo do arquivo). ``eixo`` (um ``EixoDoTema``) mostra os números
    do Y do traço de referência; ``com_tempo``: os destravados têm também o seu tempo.

    ``mudou(traco)``: a escala de um traço mudou (o espectro redesenha as marcas dele; a vista de tempo refaz as
    medidas de um traço de tempo próprio). ``cadeadoMudou()``: algum traço foi travado ou destravado.
    ``referenciaMudou()``: o traço de referência do Y é outro (a vista refaz o rótulo do eixo, com a unidade dele)."""

    mudou = Signal(object)
    cadeadoMudou = Signal()
    referenciaMudou = Signal()

    def __init__(self, caixa: CaixaComEscalas, eixo=None, parent: QObject | None = None, *, com_tempo: bool = False):
        super().__init__(parent)
        self.caixa, self.eixo, self.com_tempo = caixa, eixo, com_tempo
        self._itens: dict = {}                 # traço -> item, na ordem da vista
        self._escalas: dict = {}
        self._soltos: set = set()              # os destravados
        self._selecao: tuple = ()
        self._junto: frozenset = frozenset()   # durante um gesto da caixa: os destravados que andam com ele
        self._referencia = None
        (x0, x1), (y0, y1) = caixa.viewRange()
        self._x, self._y = (x0, x1), (y0, y1)
        caixa.escalas = self
        caixa.sigYRangeChanged.connect(self._y_mudou)
        if com_tempo:
            caixa.sigXRangeChanged.connect(self._x_mudou)

    # ------------------------------------------------------------------ os traços

    def definir_itens(self, itens: Mapping) -> None:
        """Os traços da caixa (na ordem da vista) e o item de cada um. Os que ficam guardam a escala e o cadeado; os
        novos entram travados, na escala comum; um item novo de um traço que fica (o espectro troca o item ao mudar a
        escala da frequência) recebe a escala dele."""
        antes, self._itens = self._itens, dict(itens)
        for traco in [t for t in self._escalas if t not in self._itens]:
            del self._escalas[traco]
            self._soltos.discard(traco)
        for traco, item in self._itens.items():
            escala = self._escalas.setdefault(traco, COMUM)
            if antes.get(traco) is not item:
                _aplicar(item, escala)
        self._atualizar_referencia()

    @property
    def tracos(self) -> list:
        return list(self._itens)

    def escala(self, traco) -> Escala:
        return self._escalas.get(traco, COMUM)

    def travado(self, traco) -> bool:
        return traco not in self._soltos

    def travar(self, tracos: Iterable, travar: bool = True) -> bool:
        """Trava (ou destrava) os ``tracos`` desta caixa; devolve se algum mudou. A escala de cada um fica."""
        mudaram = [t for t in tracos if t in self._itens and (t in self._soltos) == travar]
        for traco in mudaram:
            (self._soltos.discard if travar else self._soltos.add)(traco)
        if mudaram:
            self._atualizar_referencia()
            self.cadeadoMudou.emit()
        return bool(mudaram)

    def igualar(self, tracos: Iterable) -> bool:
        """"Mesma escala": os ``tracos`` desta caixa voltam à escala comum, no tempo e no Y (o cadeado de cada um
        fica). Devolve se algum mudou."""
        mudaram = [t for t in tracos if t in self._itens and not self._escalas[t].comum]
        for traco in mudaram:
            self._definir(traco, COMUM)
        return bool(mudaram)

    def mostrar_no_tempo(self, traco, inicio: float, fim: float) -> bool:
        """Põe o trecho ``[inicio, fim]`` (no tempo do traço) na faixa visível: a caixa anda, se o traço é travado
        (os outros travados vão junto); se é destravado, só o tempo dele muda. Devolve False se o trecho é vazio."""
        if traco not in self._itens or not fim > inicio:
            return False
        e = self._escalas[traco]
        if traco in self._soltos and self.com_tempo:
            self._definir(traco, Escala(Afim.enquadrando((inicio, fim), self._x, 0.0), e.y))
        else:
            self.caixa.setXRange(e.x.na_vista(inicio), e.x.na_vista(fim), padding=0)
        return True

    def limites_na_vista(self, traco, limites: tuple[float, float]) -> tuple[float, float]:
        """Os ``limites`` do Y (na unidade do traço) na unidade da vista."""
        y = self.escala(traco).y
        return y.na_vista(limites[0]), y.na_vista(limites[1])

    def _definir(self, traco, escala: Escala) -> None:
        if self._escalas.get(traco) == escala:
            return
        self._escalas[traco] = escala
        _aplicar(self._itens[traco], escala)
        if traco is self._referencia:
            self._conversao_do_eixo()
        self.mudou.emit(traco)

    # ------------------------------------------------------------------ a referência do eixo Y

    def definir_selecao(self, selecionados: Iterable) -> None:
        """Os traços selecionados (de qualquer caixa, na ordem em que entraram)."""
        self._selecao = tuple(selecionados)
        self._atualizar_referencia()

    @property
    def selecionados(self) -> list:
        """Os selecionados que estão nesta caixa."""
        return [t for t in self._selecao if t in self._itens]

    @property
    def referencia(self):
        return self._referencia

    def _atualizar_referencia(self) -> None:
        meus = self.selecionados
        travados = [t for t in self._itens if t not in self._soltos]
        referencia = meus[-1] if meus else (travados[0] if travados else next(iter(self._itens), None))
        trocou = referencia is not self._referencia
        self._referencia = referencia
        self._conversao_do_eixo()
        if trocou:
            self.referenciaMudou.emit()

    def _conversao_do_eixo(self) -> None:
        if self.eixo is not None:
            y = self.escala(self._referencia).y
            self.eixo.definir_conversao(y.k, y.c)

    # ------------------------------------------------------------------ os gestos

    def gesto(self, transformar: Callable[[Escala], Escala]) -> bool:
        """Um gesto (ver o começo do arquivo). Devolve True se ele vai para a caixa; senão, ``transformar`` já mudou a
        escala de cada selecionado (todos destravados), e a caixa fica."""
        meus = self.selecionados
        if meus and all(t in self._soltos for t in meus):
            for traco in meus:
                self._definir(traco, transformar(self._escalas[traco]))
            return False
        self._junto = frozenset(t for t in meus if t in self._soltos)
        return True

    def fim_do_gesto(self) -> None:
        self._junto = frozenset()

    def _acompanhar(self, eixo: str, antes: tuple[float, float], depois: tuple[float, float]) -> None:
        """A faixa da caixa mudou: os destravados (menos os que andam com o gesto) ficam no mesmo lugar da tela."""
        if antes == depois:
            return
        for traco in [t for t in self._itens if t in self._soltos and t not in self._junto]:
            e = self._escalas[traco]
            if eixo == "x":
                self._definir(traco, Escala(e.x.acompanhando(antes, depois), e.y))
            else:
                self._definir(traco, Escala(e.x, e.y.acompanhando(antes, depois)))

    def _y_mudou(self, _caixa, faixa) -> None:
        antes, self._y = self._y, (float(faixa[0]), float(faixa[1]))
        self._acompanhar("y", antes, self._y)

    def _x_mudou(self, _caixa, faixa) -> None:
        antes, self._x = self._x, (float(faixa[0]), float(faixa[1]))
        self._acompanhar("x", antes, self._x)

    # ------------------------------------------------------------------ o ajuste e a vista que fica

    def ajustar(self, folga: float = 0.02) -> None:
        """O "ajustar tudo" (o F, ou o botão da barra): a caixa nos travados visíveis (o tempo de todos, se ninguém tem tempo
        próprio); cada destravado na caixa inteira, pela escala dele (no tempo também, com ``com_tempo``)."""
        visiveis = {t: i for t, i in self._itens.items() if i.isVisible()}
        travados = [i for t, i in visiveis.items() if t not in self._soltos]
        if not visiveis:
            self.caixa.autoRange(padding=folga)
            return
        x = self.caixa.childrenBounds(items=travados if self.com_tempo and travados else list(visiveis.values()))[0]
        y = self.caixa.childrenBounds(items=travados)[1] if travados else None
        if x is not None or y is not None:
            self.caixa.setRange(xRange=x, yRange=y, padding=folga)
        (x0, x1), (y0, y1) = self.caixa.viewRange()
        for traco, item in visiveis.items():
            if traco not in self._soltos:
                continue
            e = self._escalas[traco]
            limites_y, limites_x = item.dataBounds(1), item.dataBounds(0)
            if _finitos(limites_y):
                e = Escala(e.x, Afim.enquadrando(limites_y, (y0, y1), folga))
            if self.com_tempo and _finitos(limites_x):
                e = Escala(Afim.enquadrando(limites_x, (x0, x1), folga), e.y)
            self._definir(traco, e)

    def manter(self, limites: Mapping) -> None:
        """Depois de uma mudança nos dados: ``limites`` (traço -> mínimo e máximo no trecho visível, na unidade
        dele). Os travados juntos (:func:`manter_o_y`: a caixa anda se nenhum aparece); cada destravado sozinho (a
        escala dele anda, com a mesma altura, se ele sumiu)."""
        travados = [self.limites_na_vista(t, lim) for t, lim in limites.items()
                    if t in self._itens and t not in self._soltos]
        if travados:
            manter_o_y(self.caixa, travados)
        _, (y0, y1) = self.caixa.viewRange()
        for traco, lim in limites.items():
            if traco not in self._soltos or traco not in self._itens:
                continue
            a, b = sorted(self.limites_na_vista(traco, lim))
            if math.isfinite(a) and math.isfinite(b) and (b < y0 or a > y1):
                self._definir(traco, self._escalas[traco].deslocada(None, (a + b) / 2 - (y0 + y1) / 2))


def _finitos(limites) -> bool:
    return limites is not None and all(v is not None and math.isfinite(v) for v in limites)


def _aplicar(item, escala: Escala) -> None:
    item.setTransform(escala.transformacao())
    item.informViewBoundsChanged()          # o ajuste automático da caixa mede o item de novo


class CaixaComEscalas(pg.ViewBox):
    """A ``ViewBox`` em que os gestos passam pelas escalas dos traços (``escalas``, posta por
    :class:`EscalasDaCaixa`). Sem ``com_tempo``, o x de um gesto é sempre da caixa."""

    escalas: EscalasDaCaixa | None = None

    def scaleBy(self, s=None, center=None, x=None, y=None):
        if s is not None:
            x, y = s[0], s[1]
        escalas = self.escalas
        fator_x = x if escalas is not None and escalas.com_tempo else None     # a parte que um traço pode ter
        if escalas is None or (y is None and fator_x is None):
            super().scaleBy(x=x, y=y, center=center)
            return
        centro = Point(center if center is not None else self.targetRect().center())
        na_caixa = escalas.gesto(lambda e: e.ampliada(fator_x, y, centro))
        try:
            super().scaleBy(x=x if na_caixa or fator_x is None else None, y=y if na_caixa else None, center=center)
        finally:
            escalas.fim_do_gesto()

    def translateBy(self, t=None, x=None, y=None):
        if t is not None:
            x, y = Point(t).x(), Point(t).y()
        escalas = self.escalas
        dx = x if escalas is not None and escalas.com_tempo else None
        if escalas is None or (y is None and dx is None):
            super().translateBy(x=x, y=y)
            return
        na_caixa = escalas.gesto(lambda e: e.deslocada(dx, y))
        try:
            super().translateBy(x=x if na_caixa or dx is None else None, y=y if na_caixa else None)
        finally:
            escalas.fim_do_gesto()
