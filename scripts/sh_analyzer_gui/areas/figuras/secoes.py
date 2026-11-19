"""As peças das seções das propriedades da figura (``propriedades.py``, ``estilo.py``, ``elementos.py``,
``anotacoes.py``): a seção com o título e as linhas de rótulo e campo, os campos de número com o separador decimal do
aplicativo, o campo de um limite que pode ficar automático e o campo de um texto da figura, que confere a matemática
antes de aceitá-lo.

Cada seção recebe ``tentar(criar, texto, juntar)`` das propriedades: ``criar()`` monta a figura nova, que vira um
passo de desfazer com ``texto`` (``juntar``: os passos seguidos do mesmo campo viram um só).
"""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QLocale, Signal
from PySide6.QtWidgets import QDoubleSpinBox, QFrame, QGridLayout, QLabel, QLineEdit, QWidget

from ...componentes.basicos import CampoComUnidade
from ...componentes.numeros import formatar_si, separador_decimal
from ...dados.desenho_da_figura import erro_no_texto
from ...dados.figura import Figura

Tentar = Callable[[Callable[[], Figura], str, bool], None]


def local() -> QLocale:
    """Os números dos campos com o separador decimal do aplicativo."""
    loc = QLocale(QLocale.Language.Portuguese, QLocale.Country.Brazil) if separador_decimal() == "," \
        else QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
    loc.setNumberOptions(QLocale.NumberOption.OmitGroupSeparator)
    return loc


def campo_decimal(sufixo: str, minimo: float, maximo: float, passo: float, casas: int = 1) -> QDoubleSpinBox:
    campo = QDoubleSpinBox()
    campo.setLocale(local())
    campo.setDecimals(casas)
    campo.setRange(minimo, maximo)
    campo.setSingleStep(passo)
    campo.setSuffix(f" {sufixo}")
    campo.setKeyboardTracking(False)
    return campo


def secao(titulo: str | QLabel, linhas) -> QFrame:
    """A seção: o título e as linhas ``(rótulo, campo ou layout)``; um rótulo vazio deixa o campo sozinho."""
    quadro = QFrame()
    quadro.setObjectName("secao_da_figura")
    grade = QGridLayout(quadro)
    grade.setContentsMargins(0, 8, 0, 10)
    grade.setHorizontalSpacing(10)
    grade.setVerticalSpacing(6)
    rotulo_do_titulo = titulo if isinstance(titulo, QLabel) else QLabel(titulo)
    rotulo_do_titulo.setObjectName("titulo_da_secao_da_figura")
    grade.addWidget(rotulo_do_titulo, 0, 0, 1, 2)
    for i, (nome, campo) in enumerate(linhas, start=1):
        rotulo = QLabel(nome)
        rotulo.setObjectName("rotulo_da_propriedade")
        grade.addWidget(rotulo, i, 0)
        if isinstance(campo, QWidget):
            grade.addWidget(campo, i, 1)
        else:
            grade.addLayout(campo, i, 1)
    grade.setColumnStretch(1, 1)
    return quadro


class CampoDoLimite(CampoComUnidade):
    """Um limite de eixo: um número com a unidade, ou vazio (o automático, que fica escrito apagado).
    ``limiteMudou(valor ou None)`` sai quando o usuário confirma um valor diferente."""

    limiteMudou = Signal(object)

    def __init__(self, unidade: str = "", parent: QWidget | None = None):
        super().__init__(unidade, parent=parent)
        self._limite: float | None = None
        self.valorMudou.connect(self._numero)
        self.definir_limite(None)

    @property
    def limite(self) -> float | None:
        return self._limite

    def definir_limite(self, valor: float | None, automatico: float | None = None) -> None:
        """O valor (``None``: o automático, com ``automatico`` escrito apagado). Um campo sendo editado fica."""
        if self.hasFocus() and self.isModified():
            return
        self._limite = valor
        if valor is None:
            self.definir_varios(formatar_si(automatico, self.unidade) if automatico is not None
                                and math.isfinite(automatico) else self.tr("automático"))
        else:
            self.definir_valor(valor)

    def _confirmar(self) -> None:
        if not self.text().strip():                     # apagado: volta ao automático
            if self._limite is not None:
                self._limite = None
                self.definir_varios(self.tr("automático"))
                self.limiteMudou.emit(None)
            return
        super()._confirmar()

    def _numero(self, valor: float) -> None:
        if valor != self._limite:
            self._limite = valor
            self.limiteMudou.emit(valor)


class CampoDeTexto(QLineEdit):
    """Um texto que vai para a figura (aceita a matemática do mathtext, ``$\\Delta t$``). ``textoMudou(texto ou
    None)`` sai ao confirmar um texto que se desenha (``None``: o campo vazio, o automático); um que o mathtext não
    entende fica marcado, com a razão na dica, e não sai."""

    textoMudou = Signal(object)

    def __init__(self, parent: QWidget | None = None, *, vazio_e_automatico: bool = True):
        super().__init__(parent)
        self.vazio_e_automatico = vazio_e_automatico
        self._valor: str | None = None
        self.editingFinished.connect(self._confirmar)

    def definir(self, valor: str | None, automatico: str = "") -> None:
        if self.hasFocus() and self.isModified():           # o usuário está escrevendo nele
            return
        self._valor = valor
        self.setText(valor or "")
        self.setPlaceholderText(automatico)
        self._marcar("")

    def _marcar(self, erro: str) -> None:
        self.setToolTip(erro)
        if bool(self.property("invalido")) != bool(erro):
            self.setProperty("invalido", bool(erro))
            self.style().unpolish(self)
            self.style().polish(self)

    def _confirmar(self) -> None:
        texto = self.text().strip()
        valor = (texto or None) if self.vazio_e_automatico else texto
        if (erro := erro_no_texto(texto)) is not None:
            self._marcar(self.tr("A matemática não se desenha: {}").format(erro))
            return
        self._marcar("")
        if valor != self._valor:
            self._valor = valor
            self.textoMudou.emit(valor)

