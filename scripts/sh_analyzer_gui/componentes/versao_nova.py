"""O cartão de versão nova (``servicos/versao_nova.py`` faz a consulta e o download; a janela liga os dois).

O cartão mora no canto de cima à direita da área central, por cima das vistas, e não bloqueia nada. Ele diz qual é a
versão nova e a instalada e oferece o que cabe à instalação (:func:`servicos.versao_nova.como_foi_instalado`):

- ``windows``: **Atualizar agora** (baixa com a barra de progresso; no fim, a janela fecha, oferecendo salvar o
  projeto, e o instalador calado reabre o aplicativo atualizado);
- ``apt``: o texto de que a versão chega pelo Atualizador de Programas do sistema;
- ``pasta``: **Baixar**, que abre a página da release.

E sempre **Novidades** (a página da release), **Pular esta versão** (não avisa mais desta) e **Fechar** (avisa de novo
na consulta do dia seguinte).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ..servicos.versao_nova import Lancamento
from ..tema.aplicar import aparencia
from .basicos import Botao

MARGEM = 16


class CartaoDeVersaoNova(QFrame):
    """``atualizarPedido`` (o Atualizar agora, só no Windows) e ``pularPedido`` (o Pular esta versão) vão para a
    janela; ``abrir_url`` abre a página da release (o ``QDesktopServices``; os testes passam outro)."""

    atualizarPedido = Signal()
    pularPedido = Signal()

    def __init__(self, parent: QWidget, abrir_url=QDesktopServices.openUrl):
        super().__init__(parent)
        self.setObjectName("versao_nova")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.abrir_url = abrir_url
        self.lancamento: Lancamento | None = None
        self.titulo = QLabel()
        self.titulo.setObjectName("titulo_versao_nova")
        fechar = QPushButton(self.tr("Fechar"))
        fechar.setObjectName("fechar_versao_nova")
        fechar.setFlat(True)
        fechar.clicked.connect(self.hide)
        cabecalho = QHBoxLayout()
        cabecalho.addWidget(self.titulo, 1)
        cabecalho.addWidget(fechar)
        self.texto = QLabel()
        self.texto.setObjectName("texto_versao_nova")
        self.texto.setWordWrap(True)
        self.texto.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.barra = QProgressBar()
        self.barra.setObjectName("progresso_versao_nova")
        self.barra.setRange(0, 1000)
        self.barra.setTextVisible(False)
        self.barra.hide()
        self.novidades = Botao(self.tr("Novidades"), "fantasma")
        self.novidades.setObjectName("novidades_versao_nova")
        self.novidades.clicked.connect(self._abrir_pagina)
        self.pular = Botao(self.tr("Pular esta versão"), "fantasma")
        self.pular.setObjectName("pular_versao_nova")
        self.pular.clicked.connect(self._pular)
        self.agir = Botao("", "primario")
        self.agir.setObjectName("agir_versao_nova")
        self.agir.clicked.connect(self._agir)
        botoes = QHBoxLayout()
        botoes.addWidget(self.novidades)
        botoes.addWidget(self.pular)
        botoes.addStretch(1)
        botoes.addWidget(self.agir)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(14, 10, 14, 12)
        coluna.setSpacing(8)
        coluna.addLayout(cabecalho)
        coluna.addWidget(self.texto)
        coluna.addWidget(self.barra)
        coluna.addLayout(botoes)
        self.setFixedWidth(400)
        self.modo = "pasta"
        parent.installEventFilter(self)
        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou(aparencia().tema)
        self.hide()

    def _tema_mudou(self, t) -> None:
        self.setStyleSheet(f"#versao_nova {{ background: {t.elevada}; border: 1px solid {t.borda_forte}; "
                           f"border-radius: 8px; }} #versao_nova QLabel {{ background: transparent; }}")

    # ------------------------------------------------------------------ o que mostra

    def mostrar(self, lancamento: Lancamento, versao_local: str, modo: str) -> None:
        """Mostra a versão nova; ``modo`` é o de :func:`servicos.versao_nova.como_foi_instalado`."""
        self.lancamento, self.modo = lancamento, modo
        self.titulo.setText(self.tr("<b>SH-Analyzer {0} disponível</b>").format(lancamento.versao))
        if modo == "windows":
            texto = self.tr("Você tem a {0}. Atualizar baixa a versão nova, fecha o SH-Analyzer (oferecendo salvar o "
                            "projeto) e o abre de novo já atualizado.")
            self.agir.setText(self.tr("Atualizar agora"))
        elif modo == "apt":
            texto = self.tr("Você tem a {0}. A versão nova chega pelo Atualizador de Programas do sistema (ou com "
                            "<code>sudo apt upgrade</code> num terminal).")
        else:
            texto = self.tr("Você tem a {0}. Baixe a versão nova pela página dela.")
            self.agir.setText(self.tr("Baixar"))
        self.texto.setText(texto.format(versao_local))
        self.agir.setVisible(modo != "apt")
        self.agir.setEnabled(True)
        self.pular.setEnabled(True)
        self.barra.hide()
        self.adjustSize()
        self._posicionar()
        self.show()
        self.raise_()

    def baixando(self, fracao: float) -> None:
        """O download em andamento (só no Windows)."""
        self.agir.setEnabled(False)
        self.pular.setEnabled(False)
        self.agir.setText(self.tr("Baixando…"))
        self.barra.show()
        self.barra.setValue(round(max(0.0, min(fracao, 1.0)) * 1000))
        self.adjustSize()

    def falhou(self, motivo: str) -> None:
        """O download falhou: o motivo, e o botão volta para tentar de novo."""
        self.barra.hide()
        self.texto.setText(self.tr("A atualização não deu certo: {0}").format(motivo))
        self.agir.setText(self.tr("Tentar de novo"))
        self.agir.setEnabled(True)
        self.pular.setEnabled(True)
        self.adjustSize()

    def esperando_fechar(self) -> None:
        """O instalador está baixado, mas a janela não fechou (o usuário cancelou ao salvar o projeto)."""
        self.barra.hide()
        self.texto.setText(self.tr("A versão nova está baixada. Ela é instalada quando o SH-Analyzer fechar."))
        self.agir.setText(self.tr("Fechar e instalar"))
        self.agir.setEnabled(True)
        self.adjustSize()

    # ------------------------------------------------------------------ os botões

    def _abrir_pagina(self) -> None:
        if self.lancamento is not None and self.lancamento.pagina:
            self.abrir_url(QUrl(self.lancamento.pagina))

    def _agir(self) -> None:
        if self.modo == "windows":
            self.atualizarPedido.emit()
        else:
            self._abrir_pagina()

    def _pular(self) -> None:
        self.pularPedido.emit()
        self.hide()

    # ------------------------------------------------------------------ o lugar

    def _posicionar(self) -> None:
        pai = self.parentWidget()
        if pai is not None:
            self.move(max(MARGEM, pai.width() - self.width() - MARGEM), MARGEM)

    def eventFilter(self, objeto: QObject, evento: QEvent) -> bool:
        if objeto is self.parentWidget() and evento.type() == QEvent.Type.Resize and self.isVisible():
            self._posicionar()
        return False
