"""A lista de tarefas do painel de baixo: cada tarefa em segundo plano com o nome, o progresso (ou "na fila", enquanto
espera a vez: as pesadas rodam uma de cada vez) e o botão de cancelar. Some da lista quando termina."""

from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..servicos.tarefas import GerenciadorDeTarefas, Tarefa
from ..tema.icones import IconeDoTema
from .painel import EstadoVazio


class _LinhaDaTarefa(QWidget):
    def __init__(self, tarefa: Tarefa):
        super().__init__()
        self.tarefa = tarefa
        self.nome = QLabel(tarefa.nome)
        self.barra = QProgressBar()
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(6)
        self.barra.setMaximumWidth(220)
        self.na_fila = QLabel(self.tr("na fila"))
        self.na_fila.setObjectName("tarefa_na_fila")
        self.na_fila.setToolTip(self.tr("Espera a vez: as contas pesadas rodam uma de cada vez, para a interface não "
                                        "engasgar."))
        self.cancelar = QToolButton()
        self.cancelar.setProperty("variante", "fantasma")
        self.cancelar.setToolTip(self.tr("Cancelar"))
        self.cancelar.setIconSize(QSize(14, 14))
        IconeDoTema(self.cancelar, "x", tamanho=14)
        self.cancelar.clicked.connect(tarefa.cancelar)
        linha = QHBoxLayout(self)
        linha.setContentsMargins(12, 4, 8, 4)
        linha.addWidget(self.nome, 1)
        linha.addWidget(self.barra, 1)
        linha.addWidget(self.na_fila, 1)
        linha.addWidget(self.cancelar)
        self.mostrar_o_estado()

    def mostrar_o_estado(self) -> None:
        esperando = self.tarefa.estado == "esperando"
        self.barra.setVisible(not esperando)
        self.na_fila.setVisible(esperando)


class ListaDeTarefas(QStackedWidget):
    """``contagemMudou(n)``: quantas tarefas estão rodando (o contador da aba)."""

    contagemMudou = Signal(int)

    def __init__(self, tarefas: GerenciadorDeTarefas, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("lista_de_tarefas")
        self.vazio = EstadoVazio(self.tr("Nenhuma tarefa em andamento"),
                                 self.tr("As contas longas (pirâmides, conferências, espectros) aparecem aqui, com o "
                                         "progresso."), icone_nome="relogio", compacto=True)
        self._conteudo = QWidget()
        self._coluna = QVBoxLayout(self._conteudo)
        self._coluna.setContentsMargins(0, 4, 0, 4)
        self._coluna.setSpacing(0)
        self._coluna.addStretch(1)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(self._conteudo)
        self.addWidget(self.vazio)
        self.addWidget(rolagem)
        self._linhas: dict[Tarefa, _LinhaDaTarefa] = {}
        tarefas.tarefaEntrou.connect(self._entrou)
        tarefas.tarefaSaiu.connect(self._saiu)

    @property
    def linhas(self) -> tuple[_LinhaDaTarefa, ...]:
        return tuple(self._linhas.values())

    def _entrou(self, tarefa: Tarefa) -> None:
        linha = _LinhaDaTarefa(tarefa)
        tarefa.comecou.connect(self._comecou)
        tarefa.progressoMudou.connect(self._progresso)
        self._linhas[tarefa] = linha
        self._coluna.insertWidget(self._coluna.count() - 1, linha)
        self._atualizar()

    def _saiu(self, tarefa: Tarefa) -> None:
        linha = self._linhas.pop(tarefa, None)
        if linha is not None:
            linha.deleteLater()
        self._atualizar()

    def _comecou(self, tarefa: Tarefa) -> None:
        linha = self._linhas.get(tarefa)
        if linha is not None:
            linha.mostrar_o_estado()

    def _progresso(self, tarefa: Tarefa, fracao: float) -> None:
        linha = self._linhas.get(tarefa)
        if linha is not None:
            linha.barra.setValue(int(100 * fracao))

    def _atualizar(self) -> None:
        self.setCurrentIndex(1 if self._linhas else 0)
        self.contagemMudou.emit(len(self._linhas))
