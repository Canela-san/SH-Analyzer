"""A janela principal. Por enquanto, o esqueleto: o título, o tamanho, um estado vazio com a marca e a versão na
barra de status. As telas entram fase a fase (``docs/gui-plan.md``, seção 10).

Depende de: ``tema`` (o botão da barra de status que troca entre o claro e o escuro). O nome e a versão vêm da
``QApplication`` (``app.criar_aplicacao``).
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QToolButton, QVBoxLayout, QWidget

from .tema.aplicar import aparencia
from .tema.icones import icone
from .tema.tokens import Tema

TAMANHO_INICIAL = (1280, 800)
TAMANHO_MINIMO = (960, 600)
LADO_DA_MARCA = 96          # px do ícone no estado vazio
TAMANHO_DO_TITULO = 26      # px do nome no estado vazio


class JanelaPrincipal(QMainWindow):
    """A janela do aplicativo: hoje, o estado vazio; depois, a barra lateral, as abas e os painéis."""

    def __init__(self) -> None:
        super().__init__()
        app = QApplication.instance()
        nome = app.applicationName() or "SH-Analyzer"
        self.setWindowTitle(nome)
        self.resize(*TAMANHO_INICIAL)
        self.setMinimumSize(*TAMANHO_MINIMO)
        self.setCentralWidget(self._estado_vazio(nome))

        versao = QLabel(self.tr("versão {}").format(app.applicationVersion() or "dev"))
        versao.setObjectName("versao")
        self.statusBar().addPermanentWidget(versao)

        self.botao_tema = QToolButton()
        self.botao_tema.setObjectName("botao_tema")
        self.botao_tema.setProperty("variante", "fantasma")
        self.botao_tema.setIconSize(QSize(16, 16))
        self.botao_tema.setAutoRaise(True)
        self.botao_tema.clicked.connect(lambda: aparencia().alternar())
        self.statusBar().addPermanentWidget(self.botao_tema)
        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou(aparencia().tema)

    def _tema_mudou(self, tema: Tema) -> None:
        """O botão mostra o tema para onde ele leva: o sol no escuro, a lua no claro."""
        self.botao_tema.setIcon(icone("sol" if tema.escuro else "lua", tema.texto2))
        self.botao_tema.setToolTip(self.tr("Tema claro") if tema.escuro else self.tr("Tema escuro"))

    def _estado_vazio(self, nome: str) -> QWidget:
        """A marca, o nome e o que a interface ainda não faz, no centro da janela."""
        marca = QLabel()
        marca.setObjectName("marca")
        marca.setPixmap(self.windowIcon().pixmap(LADO_DA_MARCA, LADO_DA_MARCA))
        titulo = QLabel(nome)
        titulo.setObjectName("titulo")
        fonte = titulo.font()
        fonte.setPixelSize(TAMANHO_DO_TITULO)
        fonte.setBold(True)
        titulo.setFont(fonte)
        aviso = QLabel(self.tr("A interface gráfica está em construção. Por enquanto, analise as capturas com o "
                               "adc_tool.py."))
        aviso.setObjectName("aviso")
        aviso.setWordWrap(True)

        central = QWidget()
        coluna = QVBoxLayout(central)
        coluna.addStretch(1)
        for rotulo in (marca, titulo, aviso):
            rotulo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            coluna.addWidget(rotulo)
        coluna.addStretch(1)
        return central
