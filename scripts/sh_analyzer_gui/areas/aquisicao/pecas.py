"""As peças da visão geral e do diagnóstico (o B1): o indicador da faixa, o painel com título, o ícone e o selo de
um nível (ok, info, aviso, erro) e o bloco de um comando para conferir ou copiar."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QToolButton, QVBoxLayout, QWidget

from ...componentes.basicos import RotuloDeIcone
from ...componentes.toast import Toast
from ...tema.fontes import fonte_mono
from ...tema.icones import IconeDoTema
from ...tema.tokens import TAMANHOS
from .textos import traduzir

ICONES_DOS_NIVEIS = {"ok": ("ok", "ok"), "info": ("ok", "acento"), "aviso": ("alerta", "aviso"),
                     "erro": ("alerta", "erro")}
ROTULOS_DOS_NIVEIS = {"ok": "ok", "info": "info", "aviso": "aviso", "erro": "erro"}


def fonte(tamanho: str, peso: QFont.Weight | None = None) -> QFont:
    f = QFont()
    f.setPixelSize(TAMANHOS[tamanho])
    if peso is not None:
        f.setWeight(peso)
    return f


def repolir(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class Indicador(QFrame):
    """Um cartão da faixa de indicadores do B1: o rótulo com o ícone, o valor grande, uma linha do que ele quer dizer
    e, se pedir, a barra de uso (o cartão)."""

    def __init__(self, rotulo: str, nome_do_icone: str, *, com_barra: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("indicador")
        self.icone = RotuloDeIcone(nome_do_icone)
        self.rotulo = QLabel(rotulo)
        self.rotulo.setObjectName("rotulo_do_indicador")
        self.rotulo.setFont(fonte("secundario"))
        self.valor = QLabel("—")
        self.valor.setObjectName("valor_do_indicador")
        self.valor.setFont(fonte("secao", QFont.Weight.DemiBold))
        self.valor.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detalhe = QLabel()
        self.detalhe.setObjectName("detalhe_do_indicador")
        self.detalhe.setFont(fonte("secundario"))
        self.detalhe.setWordWrap(True)
        self.barra = QProgressBar()
        self.barra.setObjectName("barra_de_uso")
        self.barra.setRange(0, 1000)
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(6)
        self.barra.setVisible(com_barra)
        topo = QHBoxLayout()
        topo.setSpacing(6)
        topo.addWidget(self.icone)
        topo.addWidget(self.rotulo)
        topo.addStretch(1)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(14, 12, 14, 12)
        coluna.setSpacing(2)
        coluna.addLayout(topo)
        coluna.addWidget(self.valor)
        coluna.addWidget(self.detalhe)
        coluna.addStretch(1)
        coluna.addWidget(self.barra)

    def definir(self, valor: str, detalhe: str = "", nivel: str = "", uso: float | None = None) -> None:
        """``nivel``: "ok", "aviso" ou "erro" (a cor do valor), ou vazio. ``uso``: a fração da barra (0 a 1)."""
        self.valor.setText(valor)
        self.valor.setProperty("nivel", nivel)
        repolir(self.valor)
        self.detalhe.setText(detalhe)
        self.detalhe.setVisible(bool(detalhe))
        if uso is not None:
            self.barra.setValue(round(max(0.0, min(1.0, uso)) * 1000))
            self.barra.setProperty("nivel", nivel)
            repolir(self.barra)


class Painel(QFrame):
    """Um painel do B1: o título à esquerda, um texto ou um botão à direita, e o corpo (``corpo``, um layout)."""

    def __init__(self, titulo: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("painel_da_placa")
        self.titulo = QLabel(titulo)
        self.titulo.setObjectName("titulo_do_painel_da_placa")
        self.titulo.setFont(fonte("corpo", QFont.Weight.DemiBold))
        self.lado = QHBoxLayout()
        self.lado.setSpacing(6)
        topo = QHBoxLayout()
        topo.setContentsMargins(14, 10, 10, 6)
        topo.addWidget(self.titulo)
        topo.addStretch(1)
        topo.addLayout(self.lado)
        self.corpo = QVBoxLayout()
        self.corpo.setContentsMargins(0, 0, 0, 0)
        self.corpo.setSpacing(0)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(0)
        coluna.addLayout(topo)
        coluna.addLayout(self.corpo, 1)


class IconeDoNivel(RotuloDeIcone):
    """O ícone de um nível, num quadrado da cor dele (o B1: o visto verde, o alerta laranja ou vermelho)."""

    def __init__(self, nivel: str = "ok", parent: QWidget | None = None):
        super().__init__(*ICONES_DOS_NIVEIS[nivel], 14, parent)
        self.setObjectName("icone_do_nivel")
        self.setFixedSize(26, 26)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.definir(nivel)

    def definir(self, nivel: str) -> None:
        self.trocar(*ICONES_DOS_NIVEIS[nivel])
        self.setProperty("nivel", nivel)
        repolir(self)


class Selo(QLabel):
    """O selo de um nível ("ok", "aviso"…), com a cor dele (o ``#badge`` do tema)."""

    def __init__(self, nivel: str = "ok", texto: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("badge")
        self.setFont(fonte("legenda"))
        self.definir(nivel, texto)

    def definir(self, nivel: str, texto: str | None = None) -> None:
        self.setText(texto if texto is not None else traduzir(ROTULOS_DOS_NIVEIS.get(nivel, nivel)))
        self.setProperty("nivel", {"info": "acento"}.get(nivel, nivel))
        repolir(self)


class BlocoDeComando(QFrame):
    """Um comando (ou uma impressão digital) para conferir ou copiar, na fonte mono, com o botão de copiar."""

    def __init__(self, texto: str = "", parent: QWidget | None = None, *, tamanho: str = "secundario"):
        super().__init__(parent)
        self.setObjectName("bloco_mono")
        self.rotulo = QLabel(texto)
        self.rotulo.setObjectName("texto_mono")
        self.rotulo.setFont(fonte_mono(TAMANHOS[tamanho]))
        self.rotulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.rotulo.setWordWrap(True)
        self.copiar = QToolButton()
        self.copiar.setObjectName("copiar")
        self.copiar.setProperty("variante", "fantasma")
        self.copiar.setAutoRaise(True)
        self.copiar.setToolTip(traduzir("Copiar"))
        IconeDoTema(self.copiar, "copiar", "texto2", tamanho=14)
        self.copiar.clicked.connect(self._copiar)
        linha = QHBoxLayout(self)
        linha.setContentsMargins(10, 6, 6, 6)
        linha.addWidget(self.rotulo, 1)
        linha.addWidget(self.copiar, 0, Qt.AlignmentFlag.AlignTop)

    def definir(self, texto: str) -> None:
        self.rotulo.setText(texto)

    def _copiar(self) -> None:
        QGuiApplication.clipboard().setText(self.rotulo.text())
        Toast.mostrar(self.window(), traduzir("Copiado."), "sucesso", 2000)
