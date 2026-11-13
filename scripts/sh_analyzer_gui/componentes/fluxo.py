"""Um layout que põe os widgets lado a lado e quebra a linha quando acaba a largura, como as palavras de um texto:
a legenda de chips de uma vista com muitos traços cresce para baixo, sem rolagem e sem cortar nenhum chip."""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget


class LayoutDeFluxo(QLayout):
    def __init__(self, parent: QWidget | None = None, espaco: int = 6):
        super().__init__(parent)
        self._itens: list[QLayoutItem] = []
        self._espaco = espaco

    # Os nomes em inglês são os que o Qt chama.
    def addItem(self, item: QLayoutItem) -> None:
        self._itens.append(item)

    def count(self) -> int:
        return len(self._itens)

    def itemAt(self, indice: int) -> QLayoutItem | None:
        return self._itens[indice] if 0 <= indice < len(self._itens) else None

    def takeAt(self, indice: int) -> QLayoutItem | None:
        return self._itens.pop(indice) if 0 <= indice < len(self._itens) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, largura: int) -> int:
        return self._arranjar(QRect(0, 0, largura, 0), so_medir=True)

    def setGeometry(self, retangulo: QRect) -> None:
        super().setGeometry(retangulo)
        self._arranjar(retangulo, so_medir=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        tamanho = QSize()
        for item in self._itens:
            tamanho = tamanho.expandedTo(item.minimumSize())
        m: QMargins = self.contentsMargins()
        return tamanho + QSize(m.left() + m.right(), m.top() + m.bottom())

    def limpar(self) -> None:
        """Tira e apaga todos os widgets (já: o ``deleteLater`` sozinho os deixaria na tela até o laço voltar)."""
        while self._itens:
            item = self._itens.pop()
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.invalidate()

    def _arranjar(self, retangulo: QRect, so_medir: bool) -> int:
        m = self.contentsMargins()
        area = retangulo.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, altura_da_linha = area.x(), area.y(), 0
        for item in self._itens:
            tamanho = item.sizeHint()
            proximo = x + tamanho.width() + self._espaco
            if proximo - self._espaco > area.right() + 1 and altura_da_linha > 0:
                x, y = area.x(), y + altura_da_linha + self._espaco
                proximo = x + tamanho.width() + self._espaco
                altura_da_linha = 0
            if not so_medir:
                item.setGeometry(QRect(QPoint(x, y), tamanho))
            x = proximo
            altura_da_linha = max(altura_da_linha, tamanho.height())
        return y + altura_da_linha - retangulo.y() + m.bottom()
