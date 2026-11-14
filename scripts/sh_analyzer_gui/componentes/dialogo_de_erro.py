"""O diálogo de erro inesperado (docs/gui-plan.md, GE-09): o que deu errado, os detalhes para copiar e o caminho do
log, **sem fechar o aplicativo e sem parar o trabalho** (não é modal).

Um só por janela: os erros que chegam com ele aberto entram na mesma lista, e o mesmo erro repetido (a mesma
assinatura, ``servicos/erros.py``) conta as vezes em vez de aparecer de novo. Fechado, a próxima ocorrência abre um
novo, vazio.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..registro import descrever_o_ambiente
from ..servicos.erros import ErroInesperado
from ..tema.aplicar import aparencia
from ..tema.fontes import fonte_mono
from ..tema.icones import icone
from ..tema.tokens import TAMANHOS, Tema

LIMITE_DE_ERROS = 20
"""Quantos erros diferentes o diálogo guarda (os mais antigos saem; o log tem todos)."""


class DialogoDeErro(QDialog):
    def __init__(self, caminho_do_log: Path | None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dialogo_de_erro")
        self.setWindowTitle(self.tr("Erro inesperado"))
        self.setModal(False)
        self.caminho_do_log = caminho_do_log
        self.erros: list[ErroInesperado] = []           # o primeiro de cada assinatura, na ordem em que chegaram
        self.vezes: dict[tuple, int] = {}
        self.diferentes = 0
        self._descartados = 0                            # as ocorrências dos que saíram da lista

        self.simbolo = QLabel()
        titulo = QLabel(self.tr("O SH-Analyzer encontrou um erro inesperado"))
        titulo.setObjectName("titulo_do_erro")
        fonte = titulo.font()
        fonte.setPixelSize(TAMANHOS["titulo_painel"])
        fonte.setBold(True)
        titulo.setFont(fonte)
        titulo.setWordWrap(True)
        topo = QHBoxLayout()
        topo.setSpacing(8)
        topo.addWidget(self.simbolo)
        topo.addWidget(titulo, 1)
        explicacao = QLabel(self.tr("O aplicativo continua aberto, e o trabalho também: salve o projeto. Se o erro "
                                    "se repetir, copie os detalhes e mande-os junto com o log."))
        explicacao.setWordWrap(True)
        self.resumo = QLabel()
        self.resumo.setObjectName("resumo_do_erro")
        self.resumo.setWordWrap(True)
        self.resumo.setTextInteractionFlags(self.resumo.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detalhes = QPlainTextEdit()
        self.detalhes.setObjectName("detalhes_do_erro")
        self.detalhes.setReadOnly(True)
        self.detalhes.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.detalhes.setFont(fonte_mono())
        self.detalhes.setMinimumHeight(self.detalhes.fontMetrics().lineSpacing() * 10)

        self.log = QLabel()
        self.log.setObjectName("caminho_do_log")
        self.log.setWordWrap(True)
        self.log.setTextInteractionFlags(self.log.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse)
        self.abrir_pasta = QPushButton(self.tr("Abrir a pasta do log"))
        self.abrir_pasta.clicked.connect(self._abrir_a_pasta)
        linha_do_log = QHBoxLayout()
        linha_do_log.setSpacing(8)
        linha_do_log.addWidget(self.log, 1)
        linha_do_log.addWidget(self.abrir_pasta)
        if caminho_do_log is None:
            self.log.setText(self.tr("O log está desligado nesta sessão."))
            self.abrir_pasta.hide()
        else:
            self.log.setText(self.tr("Log: {}").format(caminho_do_log))

        botoes = QDialogButtonBox()
        self.copiar = botoes.addButton(self.tr("Copiar os detalhes"), QDialogButtonBox.ButtonRole.ActionRole)
        self.copiar.clicked.connect(self.copiar_os_detalhes)
        # Um botão próprio, e não o padrão "Close": o Qt não traz a tradução dos botões padrão para o português.
        botoes.addButton(self.tr("Fechar"), QDialogButtonBox.ButtonRole.RejectRole)
        botoes.rejected.connect(self.reject)

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(16, 16, 16, 16)
        coluna.setSpacing(12)
        coluna.addLayout(topo)
        coluna.addWidget(explicacao)
        coluna.addWidget(self.resumo)
        coluna.addWidget(self.detalhes, 1)
        coluna.addLayout(linha_do_log)
        coluna.addWidget(botoes)
        largura = self.fontMetrics().averageCharWidth() * 90
        self.resize(largura, int(largura * 0.7))
        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou(aparencia().tema)

    def _tema_mudou(self, t: Tema) -> None:
        self.simbolo.setPixmap(icone("alerta", t.erro, 20).pixmap(20, 20))

    # ------------------------------------------------------------------ os erros

    def adicionar(self, erro: ErroInesperado) -> None:
        if erro.assinatura not in self.vezes:
            self.diferentes += 1
            self.erros.append(erro)
            if len(self.erros) > LIMITE_DE_ERROS:
                antigo = self.erros.pop(0)
                self._descartados += self.vezes.pop(antigo.assinatura)
        self.vezes[erro.assinatura] = self.vezes.get(erro.assinatura, 0) + 1
        self._atualizar(erro)

    @property
    def ocorrencias(self) -> int:
        return sum(self.vezes.values()) + self._descartados

    def _atualizar(self, ultimo: ErroInesperado) -> None:
        onde = f" {ultimo.onde}" if ultimo.onde else ""
        linhas = [self.tr("{}{}, às {}.").format(ultimo.resumo, onde, ultimo.quando.strftime("%H:%M:%S"))]
        if self.diferentes > 1:
            linhas.append(self.tr("{} erros diferentes, {} ocorrências desde que este aviso abriu.").format(
                self.diferentes, self.ocorrencias))
        elif self.ocorrencias > 1:
            linhas.append(self.tr("O mesmo erro, {} vezes desde que este aviso abriu.").format(self.ocorrencias))
        self.resumo.setText("\n".join(linhas))
        # Quem lia os detalhes no meio não perde o lugar; quem estava no fim (a última linha da pilha diz a
        # exceção) continua no fim.
        rolagem = self.detalhes.verticalScrollBar()
        posicao, no_fim = rolagem.value(), rolagem.value() >= rolagem.maximum()
        self.detalhes.setPlainText(self.texto())
        rolagem.setValue(rolagem.maximum() if no_fim else posicao)

    def texto(self) -> str:
        """Os detalhes, como vão para a área de transferência: o ambiente, o log e cada erro com a pilha."""
        partes = [descrever_o_ambiente()]
        if self.caminho_do_log is not None:
            partes.append(f"Log: {self.caminho_do_log}")
        if self._descartados:
            partes.append(f"(mais {self._descartados} ocorrência(s) de erros mais antigos, no log)")
        for erro in self.erros:
            vezes = self.vezes[erro.assinatura]
            cabeca = f"--- {erro.quando:%Y-%m-%d %H:%M:%S}" + (f" {erro.onde}" if erro.onde else "")
            if vezes > 1:
                cabeca += f" ({vezes} vezes)"
            partes.append(f"{cabeca}\n{erro.pilha.rstrip()}")
        return "\n\n".join(partes) + "\n"

    def copiar_os_detalhes(self) -> None:
        QGuiApplication.clipboard().setText(self.texto())

    def _abrir_a_pasta(self) -> None:
        if self.caminho_do_log is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.caminho_do_log.parent)))

