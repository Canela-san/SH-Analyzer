"""A escala própria de cada traço num gráfico com vários (docs/gui-plan.md, 9.2): uma faixa da vista de tempo, o
gráfico do espectro.

* **Por padrão os traços dividem o eixo Y:** o zoom e o pan do Y mexem em todos juntos.
* **O cadeado:** um traço destravado ganha a sua escala. Os gestos do Y com ele selecionado mexem só nele (a corrente
  de 2 A ampliada ao lado da tensão de 220 V), e os gestos dos outros não o tiram do lugar na tela. Travado de novo,
  ele volta a andar com os outros, na escala que ganhou; **"Mesma escala"** o põe de volta na escala comum.
* **Só o desenho muda:** a escala é a transformação do item na caixa (``y na vista = k·valor + c``). Os valores do
  traço (a consulta, as medidas, os cursores, os limites) ficam na unidade dele.
* **O eixo Y mostra o traço de referência:** o último selecionado nesta caixa ou, sem seleção, o primeiro travado.
  Os números (pela escala dele) e a unidade (a vista põe o rótulo) são os desse traço.
* **Quem um gesto do Y mexe:** os traços selecionados nesta caixa. Se todos estão destravados, só eles mudam (a
  caixa fica). Se algum está travado, ou nada está selecionado, o gesto é da caixa: os travados andam, os
  destravados selecionados andam junto e os outros destravados ficam onde estão na tela.
* **O tempo (e a frequência) é um só:** a escala própria é só do Y. O eixo x é o mesmo para todos os traços, porque é
  nele que os cursores e as medidas se alinham.

:class:`CaixaComEscalas` é a ``ViewBox`` que passa os gestos do Y (``scaleBy`` e ``translateBy``, que todos os gestos
do PyQtGraph e os da faixa usam) por :class:`EscalasDaCaixa`. Uma mudança da faixa feita pelo programa (``setRange``:
o ajuste, a vista que fica) não é um gesto: ela vale para a caixa.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

import pyqtgraph as pg
from pyqtgraph import Point
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QTransform


@dataclass(frozen=True)
class Escala:
    """Onde um traço é desenhado na caixa: ``y na vista = k·valor + c`` (``k`` > 0)."""

    k: float = 1.0
    c: float = 0.0

    @property
    def comum(self) -> bool:
        return self.k == 1.0 and self.c == 0.0

    def na_vista(self, valor: float) -> float:
        return self.k * valor + self.c

    def no_traco(self, y: float) -> float:
        return (y - self.c) / self.k

    def transformacao(self) -> QTransform:
        return QTransform(1.0, 0.0, 0.0, self.k, 0.0, self.c)

    def ampliada(self, fator: float, centro: float) -> Escala:
        """O zoom do Y como o ``scaleBy`` da caixa: a faixa visível ``fator`` vezes maior (``fator`` > 1 afasta), em
        volta de ``centro`` (na vista). O traço muda, e a caixa fica."""
        return Escala(self.k / fator, centro + (self.c - centro) / fator)

    def deslocada(self, dy: float) -> Escala:
        """O pan do Y como o ``translateBy`` da caixa: a vista anda ``dy`` (o traço desce ``dy``)."""
        return Escala(self.k, self.c - dy)

    def acompanhando(self, antes: tuple[float, float], depois: tuple[float, float]) -> Escala:
        """A escala que deixa o traço no mesmo lugar da tela quando a faixa da caixa vai de ``antes`` para
        ``depois``."""
        largura = antes[1] - antes[0]
        if largura == 0 or not math.isfinite(largura):
            return self
        r = (depois[1] - depois[0]) / largura
        return Escala(self.k * r, depois[0] + (self.c - antes[0]) * r)

    @classmethod
    def enquadrando(cls, limites: tuple[float, float], faixa: tuple[float, float], folga: float) -> Escala:
        """A escala que põe os valores de ``limites`` na faixa ``faixa`` da vista, com a ``folga`` de cada lado (a
        fração da altura dos dados, como o ``padding`` do PyQtGraph)."""
        a, b = sorted(limites)
        altura = b - a
        if altura <= 0:
            altura = max(abs(a), 1.0) * 1e-3          # um traço constante: no meio, com uma altura qualquer
            a -= altura / 2
        a -= folga * altura
        altura *= 1 + 2 * folga
        k = (faixa[1] - faixa[0]) / altura
        return cls(k, faixa[0] - k * a)


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
    do traço de referência.

    ``mudou(traco)``: a escala de um traço mudou (o espectro redesenha as marcas dele). ``cadeadoMudou()``: algum
    traço foi travado ou destravado. ``referenciaMudou()``: o traço de referência é outro (a vista refaz o rótulo
    do eixo, com a unidade dele)."""

    mudou = Signal(object)
    cadeadoMudou = Signal()
    referenciaMudou = Signal()

    def __init__(self, caixa: CaixaComEscalas, eixo=None, parent: QObject | None = None):
        super().__init__(parent)
        self.caixa, self.eixo = caixa, eixo
        self._itens: dict = {}                 # traço -> item, na ordem da vista
        self._escalas: dict = {}
        self._soltos: set = set()              # os destravados
        self._selecao: tuple = ()
        self._junto: frozenset = frozenset()   # durante um gesto da caixa: os destravados que andam com ele
        self._referencia = None
        self._y = tuple(caixa.viewRange()[1])
        caixa.escalas = self
        caixa.sigYRangeChanged.connect(self._y_mudou)

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
        """"Mesma escala": os ``tracos`` desta caixa voltam à escala comum (o cadeado de cada um fica). Devolve se algum
        mudou."""
        mudaram = [t for t in tracos if t in self._itens and not self._escalas[t].comum]
        for traco in mudaram:
            self._definir(traco, COMUM)
        return bool(mudaram)

    def na_vista(self, traco, limites: tuple[float, float]) -> tuple[float, float]:
        """Os ``limites`` (na unidade do traço) na unidade da vista."""
        e = self.escala(traco)
        return e.na_vista(limites[0]), e.na_vista(limites[1])

    def _definir(self, traco, escala: Escala) -> None:
        if self._escalas.get(traco) == escala:
            return
        self._escalas[traco] = escala
        _aplicar(self._itens[traco], escala)
        if traco is self._referencia:
            self._conversao_do_eixo()
        self.mudou.emit(traco)

    # ------------------------------------------------------------------ a referência do eixo

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
            e = self.escala(self._referencia)
            self.eixo.definir_conversao(e.k, e.c)

    # ------------------------------------------------------------------ os gestos

    def gesto(self, transformar: Callable[[Escala], Escala]) -> bool:
        """Um gesto do Y (ver o começo do arquivo). Devolve True se ele vai para a caixa; senão, ``transformar`` já
        mudou a escala de cada selecionado (todos destravados), e a caixa fica."""
        meus = self.selecionados
        if meus and all(t in self._soltos for t in meus):
            for traco in meus:
                self._definir(traco, transformar(self._escalas[traco]))
            return False
        self._junto = frozenset(t for t in meus if t in self._soltos)
        return True

    def fim_do_gesto(self) -> None:
        self._junto = frozenset()

    def _y_mudou(self, _caixa, faixa) -> None:
        """A faixa da caixa mudou: os destravados (menos os que andam com o gesto) ficam no mesmo lugar da tela."""
        antes, self._y = self._y, (float(faixa[0]), float(faixa[1]))
        if antes == self._y:
            return
        for traco in [t for t in self._itens if t in self._soltos and t not in self._junto]:
            self._definir(traco, self._escalas[traco].acompanhando(antes, self._y))

    # ------------------------------------------------------------------ o ajuste e a vista que fica

    def ajustar(self, folga: float = 0.02) -> None:
        """O "ajustar tudo" (F, o duplo clique): o tempo de todos os traços visíveis e o Y dos travados na caixa;
        cada destravado na altura inteira dela, pela escala dele."""
        visiveis = {t: i for t, i in self._itens.items() if i.isVisible()}
        travados = [i for t, i in visiveis.items() if t not in self._soltos]
        if not visiveis:
            self.caixa.autoRange(padding=folga)
            return
        x = self.caixa.childrenBounds(items=list(visiveis.values()))[0]
        y = self.caixa.childrenBounds(items=travados)[1] if travados else None
        if x is not None or y is not None:
            self.caixa.setRange(xRange=x, yRange=y, padding=folga)
        faixa = tuple(self.caixa.viewRange()[1])
        for traco, item in visiveis.items():
            limites = item.dataBounds(1) if traco in self._soltos else None
            if limites is not None and all(v is not None and math.isfinite(v) for v in limites):
                self._definir(traco, Escala.enquadrando(limites, faixa, folga))

    def manter(self, limites: Mapping) -> None:
        """Depois de uma mudança nos dados: ``limites`` (traço -> mínimo e máximo no trecho visível, na unidade
        dele). Os travados juntos (:func:`manter_o_y`: a caixa anda se nenhum aparece); cada destravado sozinho (a
        escala dele anda, com a mesma altura, se ele sumiu)."""
        travados = [self.na_vista(t, lim) for t, lim in limites.items() if t in self._itens and t not in self._soltos]
        if travados:
            manter_o_y(self.caixa, travados)
        _, (y0, y1) = self.caixa.viewRange()
        for traco, lim in limites.items():
            if traco not in self._soltos or traco not in self._itens:
                continue
            a, b = sorted(self.na_vista(traco, lim))
            if math.isfinite(a) and math.isfinite(b) and (b < y0 or a > y1):
                self._definir(traco, self._escalas[traco].deslocada((a + b) / 2 - (y0 + y1) / 2))


def _aplicar(item, escala: Escala) -> None:
    item.setTransform(escala.transformacao())
    item.informViewBoundsChanged()          # o ajuste automático da caixa mede o item de novo


class CaixaComEscalas(pg.ViewBox):
    """A ``ViewBox`` em que os gestos do Y passam pelas escalas dos traços (``escalas``, posta por
    :class:`EscalasDaCaixa`). O x de um gesto é sempre da caixa."""

    escalas: EscalasDaCaixa | None = None

    def scaleBy(self, s=None, center=None, x=None, y=None):
        if s is not None:
            x, y = s[0], s[1]
        escalas = self.escalas
        if y is None or escalas is None:
            super().scaleBy(x=x, y=y, center=center)
            return
        centro = Point(center if center is not None else self.targetRect().center()).y()
        na_caixa = escalas.gesto(lambda e: e.ampliada(y, centro))
        try:
            super().scaleBy(x=x, y=y if na_caixa else None, center=center)
        finally:
            escalas.fim_do_gesto()

    def translateBy(self, t=None, x=None, y=None):
        if t is not None:
            x, y = Point(t).x(), Point(t).y()
        escalas = self.escalas
        if y is None or escalas is None:
            super().translateBy(x=x, y=y)
            return
        na_caixa = escalas.gesto(lambda e: e.deslocada(y))
        try:
            super().translateBy(x=x, y=y if na_caixa else None)
        finally:
            escalas.fim_do_gesto()
