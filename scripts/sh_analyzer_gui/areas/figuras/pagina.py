"""A página da figura na tela (o centro do F1): a imagem que o Matplotlib desenhou (a prévia, ``area.py``), no
**tamanho real** (os milímetros da página na tela, pelo dpi físico dela) ou do tamanho que cabe; o painel escolhido
com a moldura do acento; o clique num painel o escolhe.

A imagem chega desenhada no dpi que :meth:`PaginaDaFigura.dpi_do_desenho` pede (o da tela, vezes o zoom e a escala
do monitor): ela aparece pixel a pixel, sem reamostrar.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QToolButton, QVBoxLayout, QWidget

from ...componentes.painel import EstadoVazio
from ...tema.aplicar import aparencia
from ...tema.icones import IconeDoTema

MARGEM = 32                      # px em volta da página
DPI_SEM_TELA = 96.0              # sem o tamanho físico da tela (offscreen, um monitor que não diz)


def pixels_por_polegada() -> float:
    """Quantos pixels lógicos a tela tem numa polegada de verdade (o "tamanho real")."""
    tela = QGuiApplication.primaryScreen()
    if tela is None:
        return DPI_SEM_TELA
    fisico, razao = tela.physicalDotsPerInch(), tela.devicePixelRatio() or 1.0
    logico = fisico / razao if fisico > 0 else 0.0
    return logico if 48.0 <= logico <= 400.0 else DPI_SEM_TELA


class _Folha(QWidget):
    """A página desenhada, com a moldura do painel escolhido. Clicar num painel emite ``clicado(id)``."""

    clicado = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("folha_da_figura")
        self.imagem: QImage | None = None
        self.caixas: dict[str, tuple[float, float, float, float]] = {}   # em pixels da imagem
        self.escolhido: str | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mostrar(self, imagem: QImage, caixas: dict) -> None:
        self.imagem, self.caixas = imagem, dict(caixas)
        razao = imagem.devicePixelRatio() or 1.0
        self.setFixedSize(QSize(round(imagem.width() / razao), round(imagem.height() / razao)))
        self.update()

    def _fator(self) -> float:
        """De pixel da imagem para pixel lógico do widget."""
        return 1.0 / (self.imagem.devicePixelRatio() or 1.0) if self.imagem is not None else 1.0

    def caixa(self, id_: str) -> QRectF | None:
        """A caixa do painel ``id_`` no widget (pixels lógicos)."""
        c = self.caixas.get(id_)
        if c is None:
            return None
        f = self._fator()
        return QRectF(QPointF(c[0] * f, c[1] * f), QPointF(c[2] * f, c[3] * f))

    def painel_em(self, x: float, y: float) -> str | None:
        return next((id_ for id_ in self.caixas if self.caixa(id_).contains(QPointF(x, y))), None)

    def paintEvent(self, _evento) -> None:
        if self.imagem is None:
            return
        p = QPainter(self)
        p.drawImage(QRectF(0, 0, self.width(), self.height()), self.imagem)
        caixa = self.caixa(self.escolhido) if self.escolhido else None
        if caixa is not None:
            caneta = QPen(QColor(aparencia().tema.acento), 1.5)
            p.setPen(caneta)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(caixa.adjusted(-3, -3, 3, 3))
        p.end()

    def mousePressEvent(self, evento) -> None:
        id_ = self.painel_em(evento.position().x(), evento.position().y())
        if id_ is not None and evento.button() == Qt.MouseButton.LeftButton:
            self.clicado.emit(id_)
        super().mousePressEvent(evento)


class PaginaDaFigura(QWidget):
    """A página no centro, com o zoom embaixo: "tamanho real" ou "caber"."""

    painelClicado = Signal(str)
    zoomMudou = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("pagina_da_figura")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.caber = False                         # False: o tamanho real
        self._tamanho_mm: tuple[float, float] | None = None

        self.folha = _Folha()
        self.folha.clicado.connect(self.painelClicado)
        self.rolagem = QScrollArea()
        self.rolagem.setObjectName("rolagem_da_pagina")
        self.rolagem.setWidgetResizable(False)
        self.rolagem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        suporte = QWidget()
        suporte.setObjectName("suporte_da_folha")
        dentro = QVBoxLayout(suporte)
        dentro.setContentsMargins(MARGEM, MARGEM, MARGEM, MARGEM)
        dentro.addWidget(self.folha, 0, Qt.AlignmentFlag.AlignCenter)
        self.rolagem.setWidget(suporte)
        self.vazio = EstadoVazio(self.tr("Nenhuma figura"), self.tr(
            "Uma vista da Análise vira figura com um clique (o botão de imagem ao lado das abas), ou comece uma "
            "aqui pelo +."), icone_nome="imagem")

        self.zoom = QLabel()
        self.zoom.setObjectName("zoom_da_pagina")
        self.real = QToolButton()
        self.real.setObjectName("tamanho_real")
        self.real.setToolTip(self.tr("Tamanho real"))
        IconeDoTema(self.real, "zoom")
        self.real.clicked.connect(lambda: self.definir_caber(False))
        self.ajustar = QToolButton()
        self.ajustar.setObjectName("caber_na_tela")
        self.ajustar.setToolTip(self.tr("Caber na tela"))
        IconeDoTema(self.ajustar, "expandir")
        self.ajustar.clicked.connect(lambda: self.definir_caber(True))
        barra = QWidget()
        barra.setObjectName("barra_do_zoom")
        linha_do_zoom = QHBoxLayout(barra)
        linha_do_zoom.setContentsMargins(10, 4, 4, 4)
        linha_do_zoom.addWidget(self.zoom)
        linha_do_zoom.addWidget(self.real)
        linha_do_zoom.addWidget(self.ajustar)

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(0)
        coluna.addWidget(self.rolagem, 1)
        coluna.addWidget(self.vazio, 1)
        rodape = QHBoxLayout()
        rodape.setContentsMargins(12, 8, 12, 12)
        rodape.addStretch(1)
        rodape.addWidget(barra)
        coluna.addLayout(rodape)
        self.mostrar_vazio(True)

    def mostrar_vazio(self, vazio: bool) -> None:
        self.rolagem.setVisible(not vazio)
        self.vazio.setVisible(vazio)
        self.zoom.parentWidget().setVisible(not vazio)

    # ------------------------------------------------------------------ o zoom

    def definir_tamanho(self, largura_mm: float, altura_mm: float) -> None:
        self._tamanho_mm = (largura_mm, altura_mm)

    def fator_de_zoom(self) -> float:
        """1 no tamanho real; no "caber", o que deixa a página inteira na área (sem passar do tamanho real × 2)."""
        if not self.caber or self._tamanho_mm is None:
            return 1.0
        ppp = pixels_por_polegada()
        largura = self._tamanho_mm[0] / 25.4 * ppp
        altura = self._tamanho_mm[1] / 25.4 * ppp
        area = self.rolagem.viewport().size()
        livre_x, livre_y = max(area.width() - 2 * MARGEM, 50), max(area.height() - 2 * MARGEM, 50)
        return max(0.1, min(livre_x / largura, livre_y / altura, 2.0))

    def dpi_do_desenho(self) -> float:
        """O dpi em que a prévia é desenhada: a página aparece no tamanho pedido, pixel a pixel."""
        razao = self.devicePixelRatioF() or 1.0
        return pixels_por_polegada() * self.fator_de_zoom() * razao

    def definir_caber(self, caber: bool) -> None:
        if caber != self.caber:
            self.caber = caber
            self.zoomMudou.emit()

    def mostrar(self, pixels, caixas: dict, dpi: float) -> None:
        """A página desenhada: ``pixels`` RGBA (altura × largura × 4) em ``dpi``."""
        altura, largura = pixels.shape[:2]
        imagem = QImage(pixels.data, largura, altura, 4 * largura, QImage.Format.Format_RGBA8888).copy()
        imagem.setDevicePixelRatio(self.devicePixelRatioF() or 1.0)
        self.folha.mostrar(imagem, caixas)
        self.folha.parentWidget().adjustSize()
        zoom = round(self.fator_de_zoom() * 100)
        self.zoom.setText(self.tr("{} % · tamanho real").format(zoom) if not self.caber
                          else self.tr("{} % · cabe na tela").format(zoom))

    def escolher(self, id_: str | None) -> None:
        self.folha.escolhido = id_
        self.folha.update()

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        if self.caber:
            self.zoomMudou.emit()
