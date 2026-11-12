"""A janela principal. Por enquanto, o esqueleto: o título, o tamanho, um estado vazio com a marca e a versão na
barra de status. As telas entram fase a fase (``docs/gui-plan.md``, seção 10).

Não depende de outros módulos do pacote: o nome e a versão vêm da ``QApplication`` (``app.criar_aplicacao``).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget

TAMANHO_INICIAL = (1280, 800)
TAMANHO_MINIMO = (960, 600)
LADO_DA_MARCA = 96          # px do ícone no estado vazio


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

    def _estado_vazio(self, nome: str) -> QWidget:
        """A marca, o nome e o que a interface ainda não faz, no centro da janela."""
        marca = QLabel()
        marca.setObjectName("marca")
        marca.setPixmap(self.windowIcon().pixmap(LADO_DA_MARCA, LADO_DA_MARCA))
        titulo = QLabel(nome)
        titulo.setObjectName("titulo")
        fonte = titulo.font()
        fonte.setPointSizeF(fonte.pointSizeF() * 1.8)
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
