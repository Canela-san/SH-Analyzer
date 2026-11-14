"""A paleta de comandos (Ctrl+K; docs/gui-plan.md, 9.2) e a lista dos atalhos.

**A paleta** busca pelo nome em todas as ações da janela (e nas da vista aberta), sem diferenciar maiúsculas nem
acentos ("salv" acha "Salvar o projeto"; "cursor" acha "Cursores"). Os resultados vêm na ordem: o nome que começa com
a busca, depois o que tem uma palavra que começa com ela, depois o que a contém, depois o que tem as letras dela em
ordem. Enter roda a ação escolhida; Esc fecha. Uma ação desabilitada aparece, apagada, e não roda.

**A lista dos atalhos** mostra o atalho de cada ação e os gestos do mouse (9.2).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..tema.aplicar import aparencia
from ..tema.tokens import TAMANHOS

LARGURA = 560
MAXIMO_DE_LINHAS = 10
PAPEL_ACAO = Qt.ItemDataRole.UserRole + 1
PAPEL_ATALHO = Qt.ItemDataRole.UserRole + 2

GESTOS = (
    ("Zoom no tempo, centrado no cursor", "Roda"),
    ("Zoom no eixo Y da faixa", "Ctrl + roda, ou roda em cima dos números do Y"),
    ("Andar no tempo", "Shift + roda, ou arrastar"),
    ("Mover a vista em qualquer direção, sem mudar as escalas", "Arrastar com o botão do meio (a roda apertada)"),
    ("Mover só um traço (offset e tempo)", "Arrastar com o botão do meio em cima dele"),
    ("O 0 do eixo Y no meio da faixa", "Clique rápido com o botão do meio (em cima de um traço: tira o offset dele)"),
    ("Ajustar tudo", "Duplo clique no gráfico, ou F"),
    ("Voltar ao zoom anterior", "Backspace"),
    ("Selecionar um traço", "Clique perto dele, ou no chip"),
    ("Somar à seleção", "Ctrl + clique"),
    ("Ligar os cursores; mover o ativo", "C; setas (Shift: 10 amostras)"),
    ("Plotar um canal", "Duplo clique no canal, no painel do projeto"),
)


def normalizar(texto: str) -> str:
    """Sem acentos, sem ``&`` de atalho e em minúsculas: a busca não diferencia "Ação" de "acao"."""
    decomposto = unicodedata.normalize("NFKD", texto.replace("&", ""))
    return "".join(c for c in decomposto if not unicodedata.combining(c)).casefold()


def _em_ordem(busca: str, texto: str) -> bool:
    posicao = 0
    for letra in busca:
        posicao = texto.find(letra, posicao)
        if posicao < 0:
            return False
        posicao += 1
    return True


def pontuar(busca: str, texto: str) -> int | None:
    """Quanto ``texto`` casa com ``busca`` (maior é melhor), ou ``None`` se não casa. Os dois já normalizados."""
    if not busca:
        return 1
    if texto.startswith(busca):
        return 4
    if any(palavra.startswith(busca) for palavra in texto.split()):
        return 3
    if busca in texto:
        return 2
    if _em_ordem(busca.replace(" ", ""), texto):
        return 1
    return None


@dataclass(frozen=True)
class Resultado:
    acao: QAction
    texto: str
    pontos: int


def buscar(acoes, busca: str) -> list[Resultado]:
    """As ações com texto que casam com ``busca``, das melhores para as piores (e, empatadas, em ordem alfabética)."""
    alvo = normalizar(busca.strip())
    resultados = []
    vistas = set()
    for acao in acoes:
        texto = acao.text().replace("&", "").strip()
        if not texto or id(acao) in vistas:
            continue
        vistas.add(id(acao))
        pontos = pontuar(alvo, normalizar(texto))
        if pontos is not None:
            resultados.append(Resultado(acao, texto, pontos))
    return sorted(resultados, key=lambda r: (-r.pontos, normalizar(r.texto)))


def atalho_de(acao: QAction) -> str:
    return acao.shortcut().toString(QKeySequence.SequenceFormat.NativeText)


class _DelegadoDaPaleta(QStyledItemDelegate):
    """O nome à esquerda e o atalho à direita, discreto."""

    def paint(self, p: QPainter, opcao: QStyleOptionViewItem, indice) -> None:
        super().paint(p, opcao, indice)
        atalho = indice.data(PAPEL_ATALHO)
        if not atalho:
            return
        p.save()
        t = aparencia().tema
        p.setPen(QColor(t.mudo if opcao.state & QStyle.StateFlag.State_Enabled else t.borda_forte))
        caixa = QRect(opcao.rect).adjusted(0, 0, -12, 0)
        p.drawText(caixa, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, atalho)
        p.restore()


class PaletaDeComandos(QFrame):
    """A janelinha flutuante da paleta. ``executada(acao)`` sai quando uma ação roda por ela."""

    executada = Signal(object)

    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("paleta")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(LARGURA)
        self.campo = QLineEdit()
        self.campo.setObjectName("busca_paleta")
        self.campo.setPlaceholderText(self.tr("Buscar um comando…"))
        fonte = QFont()
        fonte.setPixelSize(TAMANHOS["titulo_painel"])
        self.campo.setFont(fonte)
        self.lista = QListWidget()
        self.lista.setObjectName("resultados_paleta")
        self.lista.setUniformItemSizes(True)
        self.lista.setItemDelegate(_DelegadoDaPaleta(self.lista))
        self.lista.itemActivated.connect(lambda _item: self.executar())
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(8, 8, 8, 8)
        coluna.setSpacing(6)
        coluna.addWidget(self.campo)
        coluna.addWidget(self.lista)
        self.campo.textChanged.connect(self._filtrar)
        self.campo.installEventFilter(self)
        self._acoes: list[QAction] = []

    def abrir(self, acoes) -> None:
        """Mostra a paleta no alto da janela, com o campo vazio e todas as ações."""
        self._acoes = list(acoes)
        self.campo.clear()
        self._filtrar("")
        pai = self.parentWidget()
        topo = pai.mapToGlobal(QPoint((pai.width() - LARGURA) // 2, 56))
        self.move(topo)
        self.show()
        self.campo.setFocus()

    def _filtrar(self, busca: str) -> None:
        self.lista.clear()
        for r in buscar(self._acoes, busca):
            item = QListWidgetItem(r.texto)
            item.setData(PAPEL_ACAO, r.acao)
            item.setData(PAPEL_ATALHO, atalho_de(r.acao))
            item.setToolTip(r.acao.toolTip())
            if not r.acao.isEnabled():
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.lista.addItem(item)
        primeira = next((i for i in range(self.lista.count())
                         if self.lista.item(i).flags() & Qt.ItemFlag.ItemIsEnabled), None)
        if primeira is not None:
            self.lista.setCurrentRow(primeira)
        altura = self.lista.sizeHintForRow(0) if self.lista.count() else 24
        self.lista.setFixedHeight(altura * min(max(self.lista.count(), 1), MAXIMO_DE_LINHAS) + 6)
        self.adjustSize()

    def acao_escolhida(self) -> QAction | None:
        item = self.lista.currentItem()
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            return None
        return item.data(PAPEL_ACAO)

    def executar(self) -> bool:
        """Roda a ação escolhida (fechando a paleta antes, para a ação abrir os seus diálogos por cima)."""
        acao = self.acao_escolhida()
        if acao is None or not acao.isEnabled():
            return False
        self.hide()
        acao.trigger()
        self.executada.emit(acao)
        return True

    def eventFilter(self, objeto, evento) -> bool:
        if objeto is self.campo and evento.type() == QEvent.Type.KeyPress:
            tecla = evento.key()
            if tecla in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
                self.lista.keyPressEvent(evento)          # as setas andam na lista sem tirar o foco do campo
                return True
            if tecla in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.executar()
                return True
            if tecla == Qt.Key.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(objeto, evento)


class DialogoDeAtalhos(QDialog):
    """Os atalhos de cada ação e os gestos do mouse, numa tabela."""

    def __init__(self, acoes, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Atalhos do teclado e do mouse"))
        self.resize(560, 520)
        linhas = sorted(((r.texto, atalho_de(r.acao)) for r in buscar(acoes, "") if atalho_de(r.acao)),
                        key=lambda par: normalizar(par[0]))
        linhas += [(self.tr(a), self.tr(g)) for a, g in GESTOS]
        self.tabela = QTableWidget(len(linhas), 2)
        self.tabela.setObjectName("tabela_de_atalhos")
        self.tabela.setHorizontalHeaderLabels([self.tr("Comando"), self.tr("Atalho")])
        self.tabela.verticalHeader().hide()
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tabela.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for i, (nome, atalho) in enumerate(linhas):
            self.tabela.setItem(i, 0, QTableWidgetItem(nome))
            self.tabela.setItem(i, 1, QTableWidgetItem(atalho))
        coluna = QVBoxLayout(self)
        coluna.addWidget(self.tabela)

    @property
    def linhas(self) -> list[tuple[str, str]]:
        return [(self.tabela.item(i, 0).text(), self.tabela.item(i, 1).text()) for i in range(self.tabela.rowCount())]
