"""Os componentes simples (docs/gui-plan.md, 12.8): o botão com variante e ícone, o campo numérico com unidade, o
seletor segmentado e o cartão de medida. A aparência vem do QSS do tema (``tema.aplicar.gerar_qss``); os ícones
são recoloridos quando o tema muda."""

from __future__ import annotations

import math

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..tema.aplicar import aparencia
from ..tema.fontes import com_algarismos_tabulares
from ..tema.icones import IconeDoTema, icone
from ..tema.tokens import TAMANHOS, Tema
from .numeros import NumeroInvalido, formatar_si, ler_numero

VARIANTES = ("primario", "secundario", "fantasma", "perigo")


def _repolir(widget: QWidget) -> None:
    """Reaplica o QSS depois de mudar uma propriedade usada nos seletores (``[invalido="true"]``)."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class Botao(QPushButton):
    """Um botão com ``variante`` (primário, secundário, fantasma, perigo) e, se quiser, um ícone do tema."""

    def __init__(self, texto: str = "", variante: str = "secundario", icone_nome: str | None = None,
                 parent: QWidget | None = None):
        super().__init__(texto, parent)
        if variante not in VARIANTES:
            raise ValueError(f"variante desconhecida: {variante!r} (use {', '.join(VARIANTES)})")
        self.variante = variante
        self.icone_nome = icone_nome
        if variante != "secundario":
            self.setProperty("variante", variante)
        self.setIconSize(QSize(16, 16))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        aparencia().mudou.connect(self._recolorir)
        self._recolorir(aparencia().tema)

    def _recolorir(self, tema: Tema) -> None:
        if self.icone_nome:
            cor = {"primario": tema.acento_texto, "fantasma": tema.texto2, "perigo": tema.erro}.get(self.variante,
                                                                                                    tema.texto)
            self.setIcon(icone(self.icone_nome, cor))


class CampoComUnidade(QLineEdit):
    """O campo numérico: aceita "2,5k", "2500", "1,2 mV" (``componentes.numeros``), mostra o valor com o prefixo do
    SI e a unidade, e marca em vermelho o que não for número (sem perder o valor anterior).

    ``valorMudou(float)`` sai quando um valor novo e válido é confirmado (Enter ou saída do campo)."""

    valorMudou = Signal(float)

    def __init__(self, unidade: str = "", valor: float = 0.0, *, minimo: float = -math.inf,
                 maximo: float = math.inf, digitos: int = 4, parent: QWidget | None = None):
        super().__init__(parent)
        self.unidade, self.minimo, self.maximo, self.digitos = unidade, minimo, maximo, digitos
        self._valor = float(valor)
        self.setFont(com_algarismos_tabulares(self.font()))
        self.setText(formatar_si(self._valor, unidade, digitos))
        self.editingFinished.connect(self._confirmar)
        self.textEdited.connect(lambda _: self._marcar(False))

    @property
    def valor(self) -> float:
        return self._valor

    def definir_valor(self, valor: float) -> None:
        self._valor = float(valor)
        self.setText(formatar_si(self._valor, self.unidade, self.digitos))
        self._marcar(False)

    def _marcar(self, invalido: bool) -> None:
        if bool(self.property("invalido")) != invalido:
            self.setProperty("invalido", invalido)
            _repolir(self)

    def _confirmar(self) -> None:
        try:
            novo = ler_numero(self.text(), self.unidade)
        except NumeroInvalido as e:
            self.setToolTip(str(e))
            self._marcar(True)
            return
        if not self.minimo <= novo <= self.maximo:
            self.setToolTip(f"fora da faixa ({formatar_si(self.minimo, self.unidade)} a "
                            f"{formatar_si(self.maximo, self.unidade)})")
            self._marcar(True)
            return
        self.setToolTip("")
        mudou = novo != self._valor
        self.definir_valor(novo)
        if mudou:
            self.valorMudou.emit(novo)


class Segmentado(QWidget):
    """O seletor segmentado: opções exclusivas lado a lado, com ícone se quiser. ``escolhaMudou(int)`` dá o índice
    escolhido. Uma opção pode ser desabilitada (:meth:`habilitar`), com a dica do porquê."""

    escolhaMudou = Signal(int)

    def __init__(self, opcoes: list[str], escolhida: int = 0, parent: QWidget | None = None, *,
                 icones: list[str] | None = None):
        super().__init__(parent)
        if not opcoes:
            raise ValueError("o seletor precisa de pelo menos uma opção")
        if icones is not None and len(icones) != len(opcoes):
            raise ValueError("um ícone para cada opção")
        self.setObjectName("segmentado")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        linha = QHBoxLayout(self)
        linha.setContentsMargins(2, 2, 2, 2)
        linha.setSpacing(2)
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        for i, texto in enumerate(opcoes):
            b = QToolButton()
            b.setText(texto)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if icones is not None:
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                b.setIconSize(QSize(15, 15))
                IconeDoTema(b, icones[i], "texto2", papel_ligado="acento", tamanho=15)
            self._grupo.addButton(b, i)
            linha.addWidget(b)
        self._grupo.button(escolhida).setChecked(True)
        self._grupo.idToggled.connect(lambda i, marcado: marcado and self.escolhaMudou.emit(i))

    @property
    def escolhida(self) -> int:
        return self._grupo.checkedId()

    def escolher(self, indice: int) -> None:
        self._grupo.button(indice).setChecked(True)

    def botao(self, indice: int) -> QToolButton:
        return self._grupo.button(indice)

    def habilitar(self, indice: int, habilitado: bool = True, dica: str = "") -> None:
        b = self._grupo.button(indice)
        b.setEnabled(habilitado)
        b.setToolTip(dica)


class CartaoDeMedida(QFrame):
    """O cartão de uma medida: o rótulo, o valor (algarismos tabulares) e a unidade com o prefixo do SI."""

    def __init__(self, rotulo: str, valor: float = math.nan, unidade: str = "", digitos: int = 4,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("cartao")
        self.unidade, self.digitos = unidade, digitos
        self._rotulo = QLabel(rotulo)
        self._rotulo.setObjectName("rotulo")
        fonte = self._rotulo.font()
        fonte.setPixelSize(TAMANHOS["legenda"])
        self._rotulo.setFont(fonte)
        self._valor = QLabel()
        self._valor.setObjectName("valor")
        fonte = com_algarismos_tabulares(self._valor.font())
        fonte.setPixelSize(TAMANHOS["titulo_painel"])
        fonte.setWeight(fonte.Weight.DemiBold)
        self._valor.setFont(fonte)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(10, 6, 10, 8)
        coluna.setSpacing(1)
        coluna.addWidget(self._rotulo)
        coluna.addWidget(self._valor)
        self.definir(valor)

    def definir(self, valor: float, unidade: str | None = None) -> None:
        if unidade is not None:
            self.unidade = unidade
        self._valor.setText(formatar_si(valor, self.unidade, self.digitos))

    @property
    def texto(self) -> str:
        return self._valor.text()
