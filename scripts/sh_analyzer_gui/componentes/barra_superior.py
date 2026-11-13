"""A barra superior da janela (docs/gui-plan.md, 9.1; o mockup A1): a marca e o projeto à esquerda, as três áreas no
meio, e à direita o campo da paleta de comandos, o estado da placa, desfazer e refazer, o tema e os ajustes.

A barra só monta e mostra: quem a usa (a janela) liga os botões às ações (``QAction``), e as ações trazem o atalho,
a dica e o habilitado.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton, QWidget

from ..tema.icones import IconeDoTema
from ..tema.tokens import TAMANHOS
from .basicos import Segmentado

ALTURA = 44
LADO_DA_MARCA = 22
LARGURA_DA_BUSCA = 300
LARGURA_COMPACTA = 1200
"""Abaixo desta largura (px), a barra encolhe: o chip da placa fica só com o ícone, a busca encurta e o rótulo
"Projeto" sai. O seletor das áreas nunca encolhe."""
AREAS = ("Análise", "Figuras", "Aquisição")
ICONES_DAS_AREAS = ("onda", "pagina", "chip")


class CampoDaPaleta(QPushButton):
    """Parece um campo de busca, mas é um botão: abre a paleta de comandos. Mostra o atalho à direita."""

    def __init__(self, atalho: QKeySequence, parent: QWidget | None = None):
        super().__init__(parent)
        self._textos = (self.tr("Buscar comando ou dado…"), self.tr("Buscar…"))
        self.setText(self._textos[0])
        self.setObjectName("campo_paleta")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(15, 15))
        IconeDoTema(self, "busca", "mudo", tamanho=15)
        self.setFixedHeight(28)
        self.setMinimumWidth(150)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.kbd = QLabel(atalho.toString(QKeySequence.SequenceFormat.NativeText))
        self.kbd.setObjectName("kbd")
        self.kbd.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        fonte = QFont()
        fonte.setPixelSize(TAMANHOS["legenda"])
        self.kbd.setFont(fonte)
        self.kbd.setFixedHeight(18)
        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 0, 6, 0)
        linha.addStretch(1)
        linha.addWidget(self.kbd, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setToolTip(self.tr("Paleta de comandos ({})").format(self.kbd.text()))

    def sizeHint(self) -> QSize:
        return QSize(LARGURA_DA_BUSCA, 28)

    def resizeEvent(self, evento) -> None:
        # Estreito, o texto encurta e o atalho sai (fica na dica), em vez de um passar por cima do outro.
        largo = self.width() >= 240
        self.setText(self._textos[0 if largo else 1])
        self.kbd.setVisible(largo)
        super().resizeEvent(evento)


class ChipDaPlaca(QToolButton):
    """O estado da BeagleBone, sempre à vista: sem placa, conectada, com atenção ou com erro. A cor vem do QSS pela
    propriedade ``estado``; o ícone, do tema."""

    ESTADOS = {"sem_placa": ("usb", "mudo"), "conectada": ("usb", "ok"), "atencao": ("alerta", "aviso"),
               "erro": ("alerta", "erro")}

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("chip_placa")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(14, 14))
        self.setFixedHeight(26)
        fonte = QFont()
        fonte.setPixelSize(TAMANHOS["secundario"])
        self.setFont(fonte)
        self._icone = IconeDoTema(self, "usb", "mudo", tamanho=14)
        self.estado = ""
        self.definir("sem_placa", self.tr("Sem placa"))

    def definir(self, estado: str, texto: str, dica: str = "") -> None:
        if estado not in self.ESTADOS:
            raise ValueError(f"estado desconhecido: {estado!r} (use {', '.join(self.ESTADOS)})")
        self.estado = estado
        self.setText(texto)
        self.setToolTip(f"{texto}: {dica}" if dica else texto)
        self.setProperty("estado", estado)
        self._icone.trocar(*self.ESTADOS[estado])
        self.style().unpolish(self)
        self.style().polish(self)


class BarraSuperior(QWidget):
    """A barra do topo. ``areaMudou(int)`` sai quando outra área é escolhida."""

    areaMudou = Signal(int)

    def __init__(self, atalho_da_paleta: QKeySequence, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("barra_superior")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(ALTURA)

        app = QApplication.instance()
        self.marca = QLabel()
        self.marca.setObjectName("marca_barra")
        self.marca.setPixmap(app.windowIcon().pixmap(LADO_DA_MARCA, LADO_DA_MARCA))
        self.nome = QLabel(app.applicationName() or "SH-Analyzer")
        self.nome.setObjectName("nome_marca")
        fonte = QFont()
        fonte.setWeight(QFont.Weight.DemiBold)
        self.nome.setFont(fonte)

        self.rotulo_projeto = QLabel(self.tr("Projeto"))
        self.rotulo_projeto.setObjectName("rotulo_projeto")
        self.botao_projeto = QToolButton()
        self.botao_projeto.setObjectName("botao_projeto")
        self.botao_projeto.setProperty("variante", "fantasma")
        self.botao_projeto.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.botao_projeto.setLayoutDirection(Qt.LayoutDirection.RightToLeft)     # a seta depois do nome
        self.botao_projeto.setIconSize(QSize(14, 14))
        self.botao_projeto.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        IconeDoTema(self.botao_projeto, "baixo", "texto2", tamanho=14)
        self.definir_projeto(self.tr("sem título"))

        self.areas = Segmentado(list(AREAS), 0, icones=list(ICONES_DAS_AREAS))
        self.areas.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.areas.escolhaMudou.connect(self.areaMudou)

        self.campo_paleta = CampoDaPaleta(atalho_da_paleta)
        self.chip_placa = ChipDaPlaca()
        self.botao_desfazer = self._botao("botao_desfazer")
        self.botao_refazer = self._botao("botao_refazer")
        self.botao_tema = self._botao("botao_tema")
        self.botao_ajustes = self._botao("botao_ajustes")
        self.botao_ajustes.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        linha = QHBoxLayout(self)
        linha.setContentsMargins(12, 0, 8, 0)
        linha.setSpacing(4)
        linha.addWidget(self.marca)
        linha.addSpacing(4)
        linha.addWidget(self.nome)
        linha.addSpacing(14)
        linha.addWidget(self.rotulo_projeto)
        linha.addWidget(self.botao_projeto)
        linha.addStretch(1)
        linha.addWidget(self.areas)
        linha.addStretch(1)
        linha.addWidget(self.campo_paleta)
        linha.addSpacing(10)
        linha.addWidget(self.chip_placa)
        linha.addSpacing(10)
        for b in (self.botao_desfazer, self.botao_refazer, self.botao_tema, self.botao_ajustes):
            linha.addWidget(b)

    @property
    def compacta(self) -> bool:
        return self.width() < LARGURA_COMPACTA

    def resizeEvent(self, evento) -> None:
        compacta = evento.size().width() < LARGURA_COMPACTA
        self.rotulo_projeto.setVisible(not compacta)
        self.chip_placa.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly if compacta
                                           else Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        super().resizeEvent(evento)

    @staticmethod
    def _botao(nome: str) -> QToolButton:
        b = QToolButton()
        b.setObjectName(nome)
        b.setProperty("variante", "fantasma")
        b.setIconSize(QSize(16, 16))
        b.setAutoRaise(True)
        b.setFixedSize(QSize(30, 30))
        return b

    def definir_projeto(self, nome: str, modificado: bool = False) -> None:
        """O nome do projeto na barra; ``modificado`` acrescenta o ponto das mudanças não salvas."""
        self.botao_projeto.setText(f"{nome} •" if modificado else nome)
        self.botao_projeto.setToolTip(self.tr("Projeto: {}{}").format(
            nome, self.tr(" (com mudanças não salvas)") if modificado else ""))
