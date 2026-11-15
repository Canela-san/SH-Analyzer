"""Gestos do mouse de verdade para os testes da interface, pela fila de eventos do Qt (o PyQtGraph os recebe pela
cena, como os de um mouse)."""

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget


def _evento(porta: QWidget, tipo, ponto: QPoint, botao, botoes) -> None:
    QApplication.sendEvent(porta, QMouseEvent(tipo, QPointF(ponto), QPointF(porta.mapToGlobal(ponto)), botao, botoes,
                                              Qt.KeyboardModifier.NoModifier))


def duplo_clique(porta: QWidget, ponto: QPoint, botao=Qt.MouseButton.LeftButton) -> None:
    """Um duplo clique em ``ponto`` do ``porta`` (o viewport do gráfico), na sequência que o sistema manda: apertar,
    soltar, o duplo e soltar. O ``QTest.mouseDClick`` não chega à cena do PyQtGraph como um duplo clique."""
    for tipo, botoes in ((QEvent.Type.MouseButtonPress, botao), (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
                         (QEvent.Type.MouseButtonDblClick, botao), (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
        _evento(porta, tipo, ponto, botao, botoes)


def arrastar(porta: QWidget, de: QPoint, ate: QPoint, botao=Qt.MouseButton.LeftButton) -> None:
    """Aperta em ``de``, arrasta em passos e solta em ``ate`` (pixels do ``porta``).

    Com uma pausa entre os passos, como um mouse de verdade: o PyQtGraph ignora movimentos a mais de 100 por segundo
    (``mouseRateLimit``), e um arrasto inteiro dentro disso vira um clique."""
    _evento(porta, QEvent.Type.MouseButtonPress, de, botao, botao)
    for k in range(1, 6):
        QTest.qWait(12)
        _evento(porta, QEvent.Type.MouseMove, de + (ate - de) * k / 5, Qt.MouseButton.NoButton, botao)
    _evento(porta, QEvent.Type.MouseButtonRelease, ate, botao, Qt.MouseButton.NoButton)
