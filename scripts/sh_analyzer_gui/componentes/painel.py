"""As peças dos painéis da janela (docs/gui-plan.md, 9.1): o título de um painel lateral, com os botões dele, e o
estado vazio, que diz o que falta fazer em vez de mostrar uma área em branco."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QFont, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..tema.aplicar import aparencia
from ..tema.icones import IconeDoTema, icone
from ..tema.tokens import TAMANHOS, Tema

ALTURA_DO_TITULO = 36


class TituloDoPainel(QWidget):
    """O cabeçalho de um painel: o nome em versalete, discreto, e os botões de ícone à direita. Serve de barra de
    título dos ``QDockWidget`` (``setTitleBarWidget``)."""

    def __init__(self, titulo: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("titulo_painel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(ALTURA_DO_TITULO)
        self.rotulo = QLabel(titulo.upper())
        self.rotulo.setObjectName("titulo_painel_texto")
        fonte = QFont()
        fonte.setPixelSize(TAMANHOS["legenda"])
        fonte.setWeight(QFont.Weight.DemiBold)
        fonte.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        self.rotulo.setFont(fonte)
        self._linha = QHBoxLayout(self)
        self._linha.setContentsMargins(12, 0, 6, 0)
        self._linha.setSpacing(2)
        self._linha.addWidget(self.rotulo)
        self._linha.addStretch(1)

    def sizeHint(self) -> QSize:
        # O QDockWidget reserva para o título a altura do sizeHint (não a altura fixa).
        return QSize(super().sizeHint().width(), ALTURA_DO_TITULO)

    def minimumSizeHint(self) -> QSize:
        return QSize(super().minimumSizeHint().width(), ALTURA_DO_TITULO)

    def adicionar_botao(self, acao: QAction) -> QToolButton:
        """Um botão de ícone que dispara ``acao`` (o ícone, a dica e o habilitado vêm dela)."""
        b = botao_de_icone(acao)
        self._linha.addWidget(b)
        return b


class EstadoVazio(QWidget):
    """O que uma área mostra quando não há nada nela: um ícone (ou a marca), o título, uma frase do que fazer e,
    se houver, o botão da ação. Centralizado."""

    def __init__(self, titulo: str, texto: str = "", *, icone_nome: str | None = None,
                 imagem: QPixmap | None = None, botao: QWidget | None = None, compacto: bool = False,
                 largura_do_texto: int | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("estado_vazio")
        self._icone_nome = icone_nome
        self.simbolo = QLabel()
        self.simbolo.setObjectName("simbolo_vazio")
        self.simbolo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lado = 24 if compacto else 32
        self._lado = lado
        if imagem is not None:
            self.simbolo.setPixmap(imagem)
        elif icone_nome is None:
            self.simbolo.hide()
        self.titulo = QLabel(titulo)
        self.titulo.setObjectName("titulo_vazio")
        fonte = QFont()
        fonte.setPixelSize(TAMANHOS["corpo"] if compacto else TAMANHOS["titulo_painel"])
        fonte.setWeight(QFont.Weight.DemiBold)
        self.titulo.setFont(fonte)
        self.texto = QLabel(texto)
        self.texto.setObjectName("texto_vazio")
        self.texto.setWordWrap(True)
        self.texto.setVisible(bool(texto))
        fonte = QFont()
        fonte.setPixelSize(TAMANHOS["secundario"])
        self.texto.setFont(fonte)
        for rotulo in (self.titulo, self.texto):
            rotulo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            rotulo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        # O conteúdo numa coluna de largura limitada, centralizada: o texto quebra as linhas dentro dela.
        conteudo = QWidget()
        conteudo.setMaximumWidth(largura_do_texto or 16_777_215)
        conteudo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        coluna = QVBoxLayout(conteudo)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(6)
        coluna.addWidget(self.simbolo)
        coluna.addSpacing(4)
        coluna.addWidget(self.titulo)
        coluna.addWidget(self.texto)
        if botao is not None:
            coluna.addSpacing(10)
            coluna.addWidget(botao, 0, Qt.AlignmentFlag.AlignHCenter)
        linha = QHBoxLayout()
        linha.addStretch(1)
        linha.addWidget(conteudo, 100)
        linha.addStretch(1)
        externa = QVBoxLayout(self)
        externa.setContentsMargins(16, 16, 16, 16)
        externa.addStretch(1)
        externa.addLayout(linha)
        externa.addStretch(1)
        if icone_nome is not None:
            aparencia().mudou.connect(self._tema_mudou)
            self._tema_mudou(aparencia().tema)

    def _tema_mudou(self, tema: Tema) -> None:
        self.simbolo.setPixmap(icone(self._icone_nome, tema.mudo, self._lado).pixmap(self._lado, self._lado))


def botao_de_icone(acao: QAction, nome_icone: str | None = None, papel: str = "texto2") -> QToolButton:
    """Um botão de ícone, sem moldura até o mouse passar, que dispara ``acao``. Com ``nome_icone``, o ícone da
    ação passa a seguir o tema."""
    if nome_icone is not None:
        IconeDoTema(acao, nome_icone, papel)
    b = QToolButton()
    b.setProperty("variante", "fantasma")
    b.setDefaultAction(acao)
    b.setIconSize(QSize(16, 16))
    b.setAutoRaise(True)
    b.setFixedSize(QSize(28, 28))
    return b


class PainelComAbas(QTabWidget):
    """Abas no estilo dos painéis (o de baixo: medidas, tarefas, avisos), com um contador opcional em cada aba."""

    NIVEIS = ("neutro", "acento", "aviso", "erro")

    def __init__(self, nome: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(nome)
        self.setDocumentMode(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._contadores: dict[int, QLabel] = {}

    def contador(self, indice: int) -> QLabel:
        """O contador da aba ``indice`` (criado na primeira vez). Só fica na aba enquanto não for zero."""
        rotulo = self._contadores.get(indice)
        if rotulo is None:
            rotulo = QLabel()
            rotulo.setObjectName("badge")
            rotulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rotulo.setFixedHeight(16)
            rotulo.setMinimumWidth(18)
            fonte = QFont()
            fonte.setPixelSize(TAMANHOS["legenda"])
            rotulo.setFont(fonte)
            rotulo.hide()
            self._contadores[indice] = rotulo
        return rotulo

    def definir_contagem(self, indice: int, n: int, nivel: str = "neutro") -> None:
        if nivel not in self.NIVEIS:
            raise ValueError(f"nível desconhecido: {nivel!r} (use {', '.join(self.NIVEIS)})")
        rotulo = self.contador(indice)
        if rotulo.property("nivel") != nivel:
            rotulo.setProperty("nivel", nivel)
            rotulo.style().unpolish(rotulo)
            rotulo.style().polish(rotulo)
        rotulo.setText(str(n))
        rotulo.adjustSize()
        # A aba mede o botão ao recebê-lo (e esconde o anterior, mesmo que seja o mesmo): entregá-lo de novo refaz
        # a aba na largura do número novo; tirá-lo no zero não deixa um vão na aba.
        lado = QTabBar.ButtonPosition.RightSide
        self.tabBar().setTabButton(indice, lado, None)
        if n > 0:
            self.tabBar().setTabButton(indice, lado, rotulo)
            rotulo.show()
        else:
            rotulo.setParent(self)
            rotulo.hide()
