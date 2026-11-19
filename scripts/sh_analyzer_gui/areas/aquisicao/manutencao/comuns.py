"""As peças das páginas da Manutenção (docs/gui-plan.md, 11.10; a Fase 6): o texto selecionável, o texto mono
longo (o log, o roteiro, o diff), o cartão e a coluna central, como os do diagnóstico."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget

from ....tema.fontes import fonte_mono
from ....tema.tokens import TAMANHOS
from ..pecas import fonte

LARGURA_MAXIMA = 920
LARGURA_DO_DIALOGO = 560


def texto(texto: str = "", nome: str = "texto_do_dialogo", selecionavel: bool = True) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName(nome)
    rotulo.setWordWrap(True)
    if selecionavel:
        rotulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return rotulo


class TextoMono(QPlainTextEdit):
    """Um texto longo na fonte mono, só de leitura (o log de uma tarefa, um roteiro)."""

    def __init__(self, linhas_visiveis: int = 12, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("texto_mono_longo")
        self.setReadOnly(True)
        self.setFont(fonte_mono(TAMANHOS["secundario"]))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setMaximumBlockCount(5000)
        altura = self.fontMetrics().lineSpacing() * linhas_visiveis + 16
        self.setFixedHeight(altura)

    def acrescentar(self, texto: str) -> None:
        barra = self.verticalScrollBar()
        no_fim = barra.value() >= barra.maximum() - 2
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(texto)
        if no_fim:
            barra.setValue(barra.maximum())


def coluna_central(conteudo: QWidget, nome: str) -> QScrollArea:
    """A coluna de no máximo :data:`LARGURA_MAXIMA` no meio, rolando (como o diagnóstico)."""
    conteudo.setMaximumWidth(LARGURA_MAXIMA)
    centro = QWidget()
    centro.setObjectName("conteudo_do_diagnostico")
    linha = QHBoxLayout(centro)
    linha.setContentsMargins(0, 0, 0, 0)
    linha.addStretch(1)
    linha.addWidget(conteudo, 100)
    linha.addStretch(1)
    rolagem = QScrollArea()
    rolagem.setObjectName(nome)
    rolagem.setWidgetResizable(True)
    rolagem.setFrameShape(QFrame.Shape.NoFrame)
    rolagem.setWidget(centro)
    return rolagem


def cartao(titulo: str = "", nome: str = "item_do_diagnostico") -> tuple[QFrame, QVBoxLayout]:
    """Um cartão (o do diagnóstico), com o título em negrito, se houver."""
    quadro = QFrame()
    quadro.setObjectName(nome)
    coluna = QVBoxLayout(quadro)
    coluna.setContentsMargins(14, 12, 14, 12)
    coluna.setSpacing(6)
    if titulo:
        rotulo = QLabel(titulo)
        rotulo.setFont(fonte("corpo", QFont.Weight.DemiBold))
        coluna.addWidget(rotulo)
    return quadro, coluna
