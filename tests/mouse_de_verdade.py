"""Gestos do mouse de verdade para os testes da interface, pela fila de eventos do Qt (o PyQtGraph os recebe pela
cena, como os de um mouse)."""

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget


def duplo_clique(porta: QWidget, ponto: QPoint, botao=Qt.MouseButton.LeftButton) -> None:
    """Um duplo clique em ``ponto`` do ``porta`` (o viewport do gráfico), na sequência que o sistema manda: apertar,
    soltar, o duplo e soltar. O ``QTest.mouseDClick`` não chega à cena do PyQtGraph como um duplo clique."""
    for tipo, botoes in ((QEvent.Type.MouseButtonPress, botao), (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
                         (QEvent.Type.MouseButtonDblClick, botao), (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
        QApplication.sendEvent(porta, QMouseEvent(tipo, QPointF(ponto), QPointF(porta.mapToGlobal(ponto)), botao, botoes,
                                                  Qt.KeyboardModifier.NoModifier))
