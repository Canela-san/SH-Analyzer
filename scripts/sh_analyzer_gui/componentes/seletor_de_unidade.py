"""O seletor de unidade (docs/gui-plan.md, 9.4): uma caixa editável com o catálogo (``dados/unidades.py``) — as
principais primeiro, depois as outras do catálogo, as próprias do usuário no fim — que aceita também qualquer símbolo
digitado. Na lista, cada unidade traz a grandeza dela à direita, em cinza.

``unidadeEscolhida(str)`` sai quando o usuário escolhe uma da lista ou confirma uma digitada (Enter ou saída da
caixa) diferente da mostrada, uma vez só (o QComboBox também escolhe o item igual ao digitado, antes). Um símbolo
inválido não sai: a caixa fica vermelha, com o motivo na dica no lugar da de sempre (:meth:`definir_dica`).

**Maiúsculas e minúsculas contam** (k e K, mPa e MPa): a busca e o completar diferenciam as duas, e o completar só
sugere (numa lista), nunca troca o que foi digitado.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from ..dados import unidades
from ..tema.aplicar import aparencia
from .basicos import _repolir

PAPEL_DA_GRANDEZA = Qt.ItemDataRole.UserRole + 1
_SEPARADOR = "separator"     # a marca que o QComboBox.insertSeparator põe na linha
_ESPACO_DA_GRANDEZA = 24     # entre o símbolo e a grandeza, na lista


class _ComAGrandeza(QStyledItemDelegate):
    """O símbolo, como sempre, e a grandeza à direita, na cor das dicas; a linha divisória entre os grupos."""

    @staticmethod
    def _separador(index: QModelIndex) -> bool:
        return index.data(Qt.ItemDataRole.AccessibleDescriptionRole) == _SEPARADOR

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        t = aparencia().tema
        if self._separador(index):
            painter.save()
            painter.setPen(QColor(t.borda))
            y = option.rect.center().y()
            painter.drawLine(option.rect.left() + 6, y, option.rect.right() - 6, y)
            painter.restore()
            return
        super().paint(painter, option, index)
        grandeza = index.data(PAPEL_DA_GRANDEZA)
        if grandeza:
            painter.save()
            selecionada = bool(option.state & QStyle.StateFlag.State_Selected)
            painter.setPen(QColor(t.texto2 if selecionada else t.mudo))
            painter.setFont(option.font)
            painter.drawText(option.rect.adjusted(0, 0, -8, 0),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, grandeza)
            painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        if self._separador(index):
            return QSize(0, 7)
        tamanho = super().sizeHint(option, index)
        grandeza = index.data(PAPEL_DA_GRANDEZA)
        if grandeza:
            tamanho.setWidth(tamanho.width() + _ESPACO_DA_GRANDEZA + option.fontMetrics.horizontalAdvance(grandeza))
        return tamanho


class SeletorDeUnidade(QComboBox):
    unidadeEscolhida = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("seletor_de_unidade")
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(6)
        self.lineEdit().setMaxLength(unidades.TAMANHO_MAXIMO)
        self.setItemDelegate(_ComAGrandeza(self))
        completar = QCompleter(self.model(), self)
        completar.setCaseSensitivity(Qt.CaseSensitivity.CaseSensitive)
        completar.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.setCompleter(completar)
        self._mostrada: str | None = ""
        self._dica = ""
        self.preencher()
        self.activated.connect(lambda i: self._escolher(self.itemText(i)))
        self.lineEdit().editingFinished.connect(self._digitada)
        self.lineEdit().textEdited.connect(lambda _: self._marcar(False))

    def preencher(self) -> None:
        """A lista de novo (as unidades próprias podem ter mudado), sem mexer no que está escrito. A lista também se
        refaz sozinha ao abrir, se as próprias mudaram desde a última vez."""
        self._versao = unidades.versao()
        texto = self.lineEdit().text()
        principais = [unidades.procurar(s) for s in unidades.PRINCIPAIS]
        grupos = (principais, [u for u in unidades.CATALOGO if u.simbolo not in unidades.PRINCIPAIS],
                  list(unidades.proprias()))
        self.blockSignals(True)
        self.clear()
        for grupo in (g for g in grupos if g):
            if self.count():
                self.insertSeparator(self.count())
            for u in grupo:
                self.addItem(u.simbolo)
                self.setItemData(self.count() - 1, u.grandeza, PAPEL_DA_GRANDEZA)
                self.setItemData(self.count() - 1, u.grandeza, Qt.ItemDataRole.ToolTipRole)
        self._mostrar(texto)
        self.blockSignals(False)

    @property
    def unidade(self) -> str | None:
        """A unidade mostrada; ``None`` com "vários"."""
        return self._mostrada

    def definir(self, unidade: str | None) -> None:
        """Mostra ``unidade`` (``None``: "vários", a seleção tem unidades diferentes), sem avisar."""
        self._mostrada = unidade
        self.blockSignals(True)
        self._mostrar(unidade or "")
        self.blockSignals(False)
        self.lineEdit().setPlaceholderText(self.tr("vários") if unidade is None else "")
        self._marcar(False)

    def definir_dica(self, texto: str) -> None:
        """A dica de sempre (a grandeza da unidade mostrada); a de um símbolo inválido fica por cima até ele sair."""
        self._dica = texto
        if not self.property("invalido"):
            self.setToolTip(texto)

    def marcar_invalido(self, motivo: str) -> None:
        """Marca a caixa em vermelho com o motivo na dica (quem recusou foi quem recebeu a unidade)."""
        self._marcar(True)
        self.setToolTip(motivo)

    def showPopup(self) -> None:
        """A lista na largura que cabe o símbolo e a grandeza (na fonte de agora), nunca mais estreita que a caixa."""
        if self._versao != unidades.versao():
            self.preencher()
        vista = self.view()
        vista.setMinimumWidth(vista.sizeHintForColumn(0) + vista.verticalScrollBar().sizeHint().width()
                              + 2 * vista.frameWidth())
        super().showPopup()

    def _mostrar(self, texto: str) -> None:
        self.setCurrentIndex(self.findText(texto, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchCaseSensitive)
                             if texto else -1)
        self.setEditText(texto)

    def _digitada(self) -> None:
        texto = self.lineEdit().text()
        if self._mostrada is None and not texto.strip():
            return                                  # "vários" e nada digitado: nada muda
        try:
            simbolo = unidades.validar_simbolo(texto)
        except unidades.UnidadeInvalida as e:
            self.marcar_invalido(str(e))
            return
        self._escolher(simbolo)

    def _escolher(self, simbolo: str) -> None:
        self._marcar(False)
        self.blockSignals(True)
        self._mostrar(simbolo)
        self.blockSignals(False)
        if simbolo != self._mostrada:
            self._mostrada = simbolo
            self.lineEdit().setPlaceholderText("")
            self.unidadeEscolhida.emit(simbolo)

    def _marcar(self, invalido: bool) -> None:
        if bool(self.property("invalido")) != invalido:
            self.setProperty("invalido", invalido)
            _repolir(self)
            if not invalido:
                self.setToolTip(self._dica)
