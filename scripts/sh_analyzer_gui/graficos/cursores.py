"""Os cursores C1 e C2 de uma vista, os mesmos em todas (a de tempo, o espectro, as bandas, o espectrograma, os
harmônicos): a mesma lógica e a mesma cara.

* **Duas linhas verticais**, uma por caixa do gráfico (as faixas da vista de tempo; a caixa única do espectro), nas
  mesmas posições em todas: arrastar uma move as outras do mesmo cursor. Na cor de destaque do tema, com o rótulo
  "C1"/"C2" no alto, e mais grossas sob o mouse.
* **As setas** movem o cursor ativo (o último mexido) um passo (uma amostra no tempo, um bin no espectro; Shift: 10),
  por :meth:`CursoresDaVista.andar`.
* **As posições ficam na unidade dos dados** (s, Hz, ordem); a linha é posta no eixo por ``para_eixo`` (o log10 na
  frequência logarítmica): trocar a escala do eixo não perde os cursores.
* **A leitura não é daqui:** ``mudou()`` avisa a vista, que manda as medidas da região para a tabela de Medidas do
  painel de baixo (como a vista de tempo sempre fez), e não um texto em cima do gráfico.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import pyqtgraph as pg
from PySide6.QtCore import QObject, Signal
from shiboken6 import isValid

from ..tema.aplicar import aparencia
from ..tema.tokens import Tema


def _identidade(valor: float) -> float:
    return valor


class CursoresDaVista(QObject):
    """``mudou()`` sai a cada movimento de um cursor (arrastando, pelas setas, ao ligar e ao desligar)."""

    mudou = Signal()

    def __init__(self, *, para_eixo: Callable[[float], float] = _identidade,
                 do_eixo: Callable[[float], float] = _identidade, parent: QObject | None = None):
        super().__init__(parent)
        self.para_eixo, self.do_eixo = para_eixo, do_eixo
        self.posicoes: list[float] | None = None          # na unidade dos dados; None: desligados
        self.ativo = 1                                     # o último mexido (as setas movem ele)
        self.linhas: list[list[pg.InfiniteLine]] = []      # por cursor, uma linha por caixa
        self._caixas: list[pg.ViewBox] = []
        self._sincronizando = False

    @property
    def ligados(self) -> bool:
        return self.posicoes is not None

    def regiao(self) -> tuple[float, float] | None:
        """C1 e C2 em ordem crescente (ou None, desligados)."""
        return tuple(sorted(self.posicoes)) if self.posicoes is not None else None

    # ------------------------------------------------------------------ ligar, desligar, pôr nas caixas

    def ligar(self, janela: tuple[float, float]) -> None:
        """Liga os cursores; na primeira vez, a um terço e a dois terços de ``janela`` (na unidade dos dados)."""
        if self.posicoes is None:
            largura = janela[1] - janela[0]
            self.posicoes = [janela[0] + largura / 3, janela[0] + 2 * largura / 3]
        self.por_nas(self._caixas)
        self.mudou.emit()

    def desligar(self) -> None:
        self.posicoes = None
        self.por_nas(self._caixas)
        self.mudou.emit()

    def por_nas(self, caixas: Iterable[pg.ViewBox]) -> None:
        """Tira as linhas e, ligados, põe de novo, uma por cursor em cada caixa (as faixas mudaram, ou o eixo)."""
        for linhas in self.linhas:
            for linha in linhas:
                caixa = linha.getViewBox() if isValid(linha) else None     # numa faixa apagada, foi junto
                if caixa is not None:
                    caixa.removeItem(linha)
        self.linhas = []
        self._caixas = [c for c in caixas if c is not None]
        if self.posicoes is None:
            return
        t = aparencia().tema
        for k, posicao in enumerate(self.posicoes):
            linhas = []
            for caixa in self._caixas:
                linha = pg.InfiniteLine(self.para_eixo(posicao), angle=90, movable=True, label=f"C{k + 1}",
                                        labelOpts={"position": 0.96, "movable": False})
                linha.indice_do_cursor = k
                linha.setZValue(20)
                self._pintar(linha, t)
                linha.sigPositionChanged.connect(self._movida)
                caixa.addItem(linha, ignoreBounds=True)
                linhas.append(linha)
            self.linhas.append(linhas)

    def reposicionar(self) -> None:
        """As linhas nas posições guardadas (depois de trocar a escala do eixo)."""
        if self.posicoes is None:
            return
        self._sincronizando = True
        try:
            for k, linhas in enumerate(self.linhas):
                for linha in linhas:
                    linha.setValue(self.para_eixo(self.posicoes[k]))
        finally:
            self._sincronizando = False

    # ------------------------------------------------------------------ mover

    def mover(self, k: int, valor: float) -> None:
        """Põe o cursor ``k`` em ``valor`` (na unidade dos dados) e o torna o ativo."""
        if self.posicoes is None:
            return
        self.posicoes[k] = float(valor)
        self.ativo = k
        self.reposicionar()
        self.mudou.emit()

    def andar(self, passos: int, passo: float) -> bool:
        """As setas: o cursor ativo anda ``passos`` vezes ``passo`` (uma amostra, um bin)."""
        if self.posicoes is None or passo <= 0:
            return False
        self.mover(self.ativo, self.posicoes[self.ativo] + passos * passo)
        return True

    def _movida(self, linha: pg.InfiniteLine) -> None:
        if self._sincronizando or self.posicoes is None:
            return
        k = linha.indice_do_cursor
        self.posicoes[k] = float(self.do_eixo(linha.value()))
        self.ativo = k
        self._sincronizando = True
        try:
            for outra in self.linhas[k]:
                if outra is not linha:
                    outra.setValue(linha.value())
        finally:
            self._sincronizando = False
        self.mudou.emit()

    # ------------------------------------------------------------------ o tema

    @staticmethod
    def _pintar(linha: pg.InfiniteLine, t: Tema) -> None:
        linha.setPen(pg.mkPen(t.destaque, width=1))
        linha.setHoverPen(pg.mkPen(t.destaque, width=2))
        linha.label.setColor(t.destaque_texto)
        linha.label.fill = pg.mkBrush(t.destaque)
        linha.label.update()

    def aplicar_tema(self, t: Tema) -> None:
        for linhas in self.linhas:
            for linha in linhas:
                if isValid(linha):
                    self._pintar(linha, t)
