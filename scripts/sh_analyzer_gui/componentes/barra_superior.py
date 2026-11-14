"""A barra superior da janela (docs/gui-plan.md, 9.1; o mockup A1): a marca e o projeto à esquerda, as três áreas no
meio, e à direita o campo da paleta de comandos, o estado da placa, desfazer e refazer, o tema e as configurações.

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
MARGEM_DAS_AREAS = 12
LARGURA_DO_NOME = 220          # o nome do projeto na barra, no máximo (o resto vira "…")        # o mínimo entre as áreas e os vizinhos (o projeto, a busca)
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

    def _largura_do_texto(self, texto: str, com_atalho: bool) -> int:
        """A largura que o texto pede (o ícone, o texto, o atalho e as margens), na fonte de agora."""
        extra = self.kbd.sizeHint().width() + 12 if com_atalho else 0
        return self.fontMetrics().horizontalAdvance(texto) + self.iconSize().width() + 36 + extra

    def sizeHint(self) -> QSize:
        return QSize(max(LARGURA_DA_BUSCA, self._largura_do_texto(self._textos[0], True)), 28)

    def minimumSizeHint(self) -> QSize:
        """O texto curto ("Buscar…"), sem o atalho: a busca encolhe até ali."""
        return QSize(self._largura_do_texto(self._textos[1], False), 28)

    def resizeEvent(self, evento) -> None:
        # Estreito, o texto encurta e o atalho sai (fica na dica), em vez de um passar por cima do outro. O limite sai
        # da largura do texto (vale em qualquer fonte e língua), e não de um número fixo.
        largo = self.width() >= self._largura_do_texto(self._textos[0], True)
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

        # Três colunas: a da esquerda (a marca e o projeto) e a da direita (a busca e os botões) têm a mesma largura
        # (o mesmo fator e a política Ignored: cada uma recebe metade do que sobra), e as áreas ficam no meio, no
        # centro da JANELA, seja qual for o nome do projeto. Numa janela estreita, a busca encolhe primeiro; abaixo
        # do mínimo de uma coluna, ela empurra as áreas, e nada se sobrepõe.
        self.esquerda, self.direita = QWidget(), QWidget()
        lado_esquerdo = QHBoxLayout(self.esquerda)
        lado_esquerdo.setContentsMargins(0, 0, 0, 0)
        lado_esquerdo.setSpacing(4)
        lado_esquerdo.addWidget(self.marca)
        lado_esquerdo.addSpacing(4)
        lado_esquerdo.addWidget(self.nome)
        lado_esquerdo.addSpacing(14)
        lado_esquerdo.addWidget(self.rotulo_projeto)
        lado_esquerdo.addWidget(self.botao_projeto)
        lado_esquerdo.addStretch(1)
        lado_direito = QHBoxLayout(self.direita)
        lado_direito.setContentsMargins(0, 0, 0, 0)
        lado_direito.setSpacing(4)
        lado_direito.addStretch(1)
        lado_direito.addWidget(self.campo_paleta, 1)
        lado_direito.addSpacing(10)
        lado_direito.addWidget(self.chip_placa)
        lado_direito.addSpacing(10)
        for b in (self.botao_desfazer, self.botao_refazer, self.botao_tema, self.botao_ajustes):
            lado_direito.addWidget(b)
        for lado in (self.esquerda, self.direita):
            lado.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        linha = QHBoxLayout(self)
        linha.setContentsMargins(12, 0, 8, 0)
        linha.setSpacing(MARGEM_DAS_AREAS)
        linha.addWidget(self.esquerda, 1)
        linha.addWidget(self.areas, 0)
        linha.addWidget(self.direita, 1)
        self._ajustar_minimos()

    @property
    def compacta(self) -> bool:
        return self.width() < LARGURA_COMPACTA

    def resizeEvent(self, evento) -> None:
        compacta = evento.size().width() < LARGURA_COMPACTA
        self.rotulo_projeto.setVisible(not compacta)
        self.chip_placa.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly if compacta
                                           else Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        super().resizeEvent(evento)
        self._ajustar_minimos()

    def _ajustar_minimos(self) -> None:
        """O mínimo de cada coluna é o do conteúdo dela (com a política Ignored, o layout não o veria sozinho)."""
        if not hasattr(self, "direita"):          # um resize durante o __init__, antes das colunas
            return
        for lado in (self.esquerda, self.direita):
            lado.setMinimumWidth(lado.layout().minimumSize().width())

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
        """O nome do projeto na barra; ``modificado`` acrescenta o ponto das mudanças não salvas. Um nome longo é
        abreviado no meio (o nome inteiro fica na dica): ele não empurra as áreas para fora do centro."""
        texto = self.botao_projeto.fontMetrics().elidedText(nome, Qt.TextElideMode.ElideMiddle, LARGURA_DO_NOME)
        self.botao_projeto.setText(f"{texto} •" if modificado else texto)
        self.botao_projeto.setToolTip(self.tr("Projeto: {}{}").format(
            nome, self.tr(" (com mudanças não salvas)") if modificado else ""))
        self._ajustar_minimos()

    def definir_menu_do_projeto(self, menu) -> None:
        """O menu do botão do projeto, sempre da esquerda para a direita: o botão é da direita para a esquerda (a seta
        depois do nome), e o menu herdava isso (o atalho grudava no rótulo: "Ctrl+Shift+OAbrir projeto…")."""
        menu.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.botao_projeto.setMenu(menu)
