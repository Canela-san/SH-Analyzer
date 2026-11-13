"""O tema na aplicação: a ``QPalette`` e a folha QSS geradas dos tokens, e a troca de tema sem reiniciar
(docs/gui-plan.md, 12.9).

* o estilo ``Fusion`` de base (igual no Windows e no Linux), com a ``QPalette`` dos tokens;
* o QSS para o que a paleta não alcança (cantos, bordas, estados, variantes de botão por ``setProperty``);
* :func:`aparencia` devolve o objeto que avisa (``mudou``) quem desenha com as cores do tema por conta própria --
  os gráficos, os componentes pintados com ``QPainter``.

``"sistema"`` segue o tema claro ou escuro do sistema operacional (``QStyleHints.colorScheme``); quando o sistema não
informa, vale o escuro, o da marca.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from .tokens import TEMAS, Tema

MODOS = ("sistema", "escuro", "claro")


class Aparencia(QObject):
    """O tema em uso. ``mudou(Tema)`` sai a cada troca."""

    mudou = Signal(object)

    def __init__(self, app: QApplication):
        super().__init__(app)
        self._app = app
        self.modo = "sistema"
        self.tema: Tema = TEMAS["escuro"]

    def aplicar(self, modo: str = "sistema") -> Tema:
        """Aplica ``modo`` (``"sistema"``, ``"escuro"`` ou ``"claro"``) e devolve o tema em uso."""
        if modo not in MODOS:
            raise ValueError(f"modo de tema desconhecido: {modo!r} (use {', '.join(MODOS)})")
        self.modo = modo
        self.tema = TEMAS[modo] if modo != "sistema" else tema_do_sistema()
        self._app.setStyle("Fusion")
        self._app.setPalette(gerar_paleta(self.tema))
        self._app.setStyleSheet(gerar_qss(self.tema))
        self.mudou.emit(self.tema)
        return self.tema

    def alternar(self) -> Tema:
        """Troca entre o escuro e o claro (o atalho da barra de status)."""
        return self.aplicar("claro" if self.tema.escuro else "escuro")


def aparencia(app: QApplication | None = None) -> Aparencia:
    """O objeto de aparência da aplicação (criado na primeira chamada)."""
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError("crie a QApplication antes de aplicar o tema")
    existente = app.findChild(Aparencia)
    return existente if existente is not None else Aparencia(app)


def tema_do_sistema() -> Tema:
    """O tema que o sistema operacional pede; o escuro quando ele não informa."""
    esquema = QGuiApplication.styleHints().colorScheme()
    return TEMAS["claro"] if esquema == Qt.ColorScheme.Light else TEMAS["escuro"]


def gerar_paleta(t: Tema) -> QPalette:
    p = QPalette()
    papeis = {
        QPalette.ColorRole.Window: t.fundo, QPalette.ColorRole.WindowText: t.texto,
        QPalette.ColorRole.Base: t.afundada, QPalette.ColorRole.AlternateBase: t.superficie,
        QPalette.ColorRole.ToolTipBase: t.elevada, QPalette.ColorRole.ToolTipText: t.texto,
        QPalette.ColorRole.PlaceholderText: t.mudo, QPalette.ColorRole.Text: t.texto,
        QPalette.ColorRole.Button: t.elevada, QPalette.ColorRole.ButtonText: t.texto,
        QPalette.ColorRole.BrightText: t.erro, QPalette.ColorRole.Highlight: t.acento,
        QPalette.ColorRole.HighlightedText: t.acento_texto, QPalette.ColorRole.Link: t.acento,
        QPalette.ColorRole.LinkVisited: t.acento, QPalette.ColorRole.Light: t.borda_forte,
        QPalette.ColorRole.Midlight: t.borda, QPalette.ColorRole.Mid: t.borda,
        QPalette.ColorRole.Dark: t.afundada, QPalette.ColorRole.Shadow: "#000000",
    }
    for papel, cor in papeis.items():
        p.setColor(papel, QColor(cor))
    for papel in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, papel, QColor(t.mudo))
    return p


def _rgba(cor: str, alfa: float) -> str:
    """``#rrggbb`` com transparência, no formato do QSS."""
    return f"rgba({int(cor[1:3], 16)}, {int(cor[3:5], 16)}, {int(cor[5:7], 16)}, {alfa:g})"


def gerar_qss(t: Tema) -> str:
    """A folha de estilos do tema. Os botões aceitam ``setProperty("variante", "primario" | "fantasma" |
    "perigo")``. Sem ``font-size``: o tamanho base vem da fonte da aplicação (``fontes.fonte_da_interface``), e um
    ``font-size`` no QSS passaria por cima do ``setFont`` de cada widget."""
    return f"""
QWidget {{ color: {t.texto}; }}
QMainWindow, QDialog {{ background: {t.fundo}; }}
QToolTip {{ background: {t.elevada}; color: {t.texto}; border: 1px solid {t.borda_forte}; padding: 4px 8px;
            border-radius: 6px; }}
QStatusBar {{ background: {t.fundo}; color: {t.texto2}; border-top: 1px solid {t.borda}; }}
QStatusBar QLabel {{ color: {t.texto2}; }}
QStatusBar::item {{ border: none; }}
QMenuBar {{ background: {t.fundo}; }}
QMenu {{ background: {t.elevada}; border: 1px solid {t.borda_forte}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 16px; border-radius: 5px; }}
QMenu::item:selected {{ background: {t.superficie}; }}
QMenu::separator {{ height: 1px; background: {t.borda}; margin: 4px 8px; }}
QPushButton, QToolButton {{ background: {t.elevada}; color: {t.texto}; border: 1px solid {t.borda};
                            border-radius: 6px; padding: 5px 12px; }}
QToolButton {{ padding: 4px; }}
QPushButton:hover, QToolButton:hover {{ border-color: {t.borda_forte}; }}
QPushButton:pressed, QToolButton:pressed, QToolButton:checked {{ background: {t.superficie}; }}
QPushButton:focus, QToolButton:focus {{ border-color: {t.acento}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {t.mudo}; }}
QPushButton[variante="primario"] {{ background: {t.acento}; color: {t.acento_texto}; border-color: {t.acento};
                                    font-weight: 600; }}
QPushButton[variante="fantasma"], QToolButton[variante="fantasma"] {{ background: transparent;
                                    border-color: transparent; color: {t.texto2}; }}
QPushButton[variante="fantasma"]:hover, QToolButton[variante="fantasma"]:hover {{ background: {t.superficie}; }}
QPushButton[variante="perigo"] {{ color: {t.erro}; border-color: {t.erro}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {t.afundada}; color: {t.texto}; border: 1px solid {t.borda}; border-radius: 6px; padding: 4px 8px;
    selection-background-color: {t.acento}; selection-color: {t.acento_texto}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {t.acento}; }}
QComboBox QAbstractItemView {{ background: {t.elevada}; border: 1px solid {t.borda_forte};
                               selection-background-color: {t.superficie}; selection-color: {t.texto}; }}
QTabBar::tab {{ background: transparent; color: {t.texto2}; padding: 6px 12px; border: none;
               border-top-left-radius: 7px; border-top-right-radius: 7px; }}
QTabBar::tab:selected {{ background: {t.afundada}; color: {t.texto}; border-top: 2px solid {t.acento}; }}
QTabBar::tab:hover:!selected {{ color: {t.texto}; }}
QTabWidget::pane {{ border: 1px solid {t.borda}; top: -1px; }}
QSplitter::handle {{ background: {t.borda}; }}
QProgressBar {{ background: {t.afundada}; border: 1px solid {t.borda}; border-radius: 4px; text-align: center;
               color: {t.texto2}; }}
QProgressBar::chunk {{ background: {t.acento}; border-radius: 3px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {t.borda_forte}; border-radius: 5px; min-height: 24px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; width: 0; height: 0; }}
QLineEdit[invalido="true"] {{ border-color: {t.erro}; }}
QWidget#segmentado {{ background: {t.superficie}; border: 1px solid {t.borda}; border-radius: 8px; }}
QWidget#segmentado QToolButton {{ background: transparent; border: none; border-radius: 6px; color: {t.texto2};
                                  padding: 4px 12px; }}
QWidget#segmentado QToolButton:checked {{ background: {_rgba(t.acento, 0.13)}; color: {t.acento}; font-weight: 600; }}
QWidget#segmentado QToolButton:hover:!checked {{ color: {t.texto}; }}
QFrame#cartao {{ background: {t.afundada}; border: 1px solid {t.borda}; border-radius: 8px; }}
QFrame#cartao QLabel#rotulo {{ color: {t.mudo}; }}
QFrame#cartao QLabel#unidade {{ color: {t.texto2}; }}
QFrame#toast {{ background: {t.elevada}; border: 1px solid {t.borda_forte}; border-radius: 10px; }}
QFrame#toast QLabel {{ color: {t.texto}; }}
QHeaderView::section {{ background: {t.superficie}; color: {t.mudo}; border: none;
                        border-bottom: 1px solid {t.borda}; padding: 6px 10px; font-weight: 600; }}
QTableView, QTreeView, QListView {{ background: {t.superficie}; alternate-background-color: {t.fundo};
    border: 1px solid {t.borda}; selection-background-color: {t.superficie}; selection-color: {t.texto}; }}
QTreeView::item:selected, QListView::item:selected, QTableView::item:selected {{
    background: {t.elevada}; color: {t.texto}; }}
"""
