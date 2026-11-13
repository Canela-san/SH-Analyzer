"""O toast: uma mensagem curta que aparece embaixo, no centro da janela, e some sozinha (docs/gui-plan.md, 12.7:
entra em 200 ms, fica 4 s). Com o movimento reduzido, aparece e some sem animação."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget

from ..tema.aplicar import aparencia
from ..tema.icones import icone

DURACAO_MS = 4000
ENTRADA_MS = 200
MARGEM_INFERIOR = 24
NIVEIS = {"info": ("ok", "acento"), "sucesso": ("ok", "ok"), "aviso": ("alerta", "aviso"), "erro": ("alerta", "erro")}

movimento_reduzido = False
"""Com ``True`` (a configuração "reduzir movimento"), os toasts aparecem e somem sem animação."""


class Toast(QFrame):
    """Use :meth:`mostrar`: ``Toast.mostrar(janela, "Figura exportada", "sucesso")``."""

    def __init__(self, pai: QWidget, texto: str, nivel: str = "info", duracao_ms: int = DURACAO_MS):
        super().__init__(pai)
        if nivel not in NIVEIS:
            raise ValueError(f"nível desconhecido: {nivel!r} (use {', '.join(NIVEIS)})")
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.nivel = nivel
        nome_icone, papel = NIVEIS[nivel]
        simbolo = QLabel()
        simbolo.setPixmap(icone(nome_icone, getattr(aparencia().tema, papel)).pixmap(16, 16))
        self.rotulo = QLabel(texto)
        linha = QHBoxLayout(self)
        linha.setContentsMargins(12, 8, 14, 8)
        linha.setSpacing(8)
        linha.addWidget(simbolo)
        linha.addWidget(self.rotulo)
        self._opacidade = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacidade)
        self._animacao = QPropertyAnimation(self._opacidade, b"opacity", self)
        self._relogio = QTimer(self)
        self._relogio.setSingleShot(True)
        self._relogio.setInterval(duracao_ms)
        self._relogio.timeout.connect(self.esconder)

    @classmethod
    def mostrar(cls, pai: QWidget, texto: str, nivel: str = "info", duracao_ms: int = DURACAO_MS) -> Toast:
        toast = cls(pai, texto, nivel, duracao_ms)
        toast.adjustSize()
        toast.move((pai.width() - toast.width()) // 2, pai.height() - toast.height() - MARGEM_INFERIOR)
        toast.show()
        toast.raise_()
        toast._animar(0.0, 1.0, QEasingCurve.Type.OutCubic)
        toast._relogio.start()
        return toast

    def esconder(self) -> None:
        if movimento_reduzido:
            self.deleteLater()
            return
        self._animar(1.0, 0.0, QEasingCurve.Type.InCubic)
        self._animacao.finished.connect(self.deleteLater)

    def _animar(self, de: float, ate: float, curva: QEasingCurve.Type) -> None:
        if movimento_reduzido:
            self._opacidade.setOpacity(ate)
            return
        self._animacao.stop()
        self._animacao.setDuration(ENTRADA_MS)
        self._animacao.setStartValue(de)
        self._animacao.setEndValue(ate)
        self._animacao.setEasingCurve(curva)
        self._animacao.start()
