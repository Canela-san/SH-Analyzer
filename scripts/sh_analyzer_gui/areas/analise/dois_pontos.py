"""A calibração por dois pontos (docs/gui-plan.md, 9.4): dois valores conhecidos do sensor dão a escala do traço. Em
cada ponto, a entrada (o que o canal mede, já com o processamento: em V, em A) e o valor que ela representa na
unidade do traço (°C, bar, m/s²)::

    ganho = (y₂ − y₁) / (x₂ − x₁)        offset = y₁ − ganho · x₁

Um transmissor de 4 a 20 mA para 0 a 10 bar: as entradas 4 mA e 20 mA, os valores 0 bar e 10 bar.

O diálogo abre com a escala de agora (as entradas 0 e 1, e os valores que elas dão hoje): mudar um ponto só é
ajustar a escala que já existe. Trocar a unidade converte os valores digitados, quando as duas se convertem (°C e K),
e só troca o rótulo quando não. Um par que não dá uma reta (as entradas iguais) ou que dá o ganho zero (os valores
iguais) não se aplica: o motivo aparece embaixo, e o botão fica desligado.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ...componentes.basicos import CampoComUnidade
from ...componentes.numeros import NumeroInvalido, formatar_si, ler_numero
from ...componentes.seletor_de_unidade import SeletorDeUnidade
from ...dados import unidades

DIGITOS = 6


def escala_por_dois_pontos(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float]:
    """``(ganho, offset)`` da reta pelos dois pontos. Levanta ``ValueError`` (com o motivo para mostrar) se as
    entradas são iguais, se os valores são iguais (o ganho zero) ou se a conta não dá um número finito."""
    if x1 == x2:
        raise ValueError("as duas entradas são iguais: não dão uma reta")
    if y1 == y2:
        raise ValueError("os dois valores são iguais: o ganho seria zero")
    ganho = (y2 - y1) / (x2 - x1)
    offset = y1 - ganho * x1
    if not (math.isfinite(ganho) and math.isfinite(offset)) or ganho == 0:
        raise ValueError("a escala desses pontos não cabe num número finito")
    return ganho, offset


def unidade_do_ganho(unidade: str, unidade_do_canal: str) -> str:
    """A unidade do ganho de um traço: a razão das duas ("°C/V"), ou nenhuma quando o traço está na do canal."""
    return f"{unidade}/{unidade_do_canal}" if unidade and unidade_do_canal and unidade != unidade_do_canal else ""


class DialogoDeDoisPontos(QDialog):
    """Pergunta os dois pontos; ``escala()`` dá ``(unidade, ganho, offset)`` depois do ``accepted``."""

    def __init__(self, unidade_do_canal: str, unidade: str, ganho: float, offset: float,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dialogo_dois_pontos")
        self.setWindowTitle(self.tr("Calibrar por dois pontos"))
        self.unidade_do_canal = unidade_do_canal
        self._unidade = unidade or unidade_do_canal

        explicacao = QLabel(self.tr("Dois valores conhecidos do sensor: em cada ponto, a entrada (o que o canal mede, "
                                    "depois do processamento) e o valor que ela representa."))
        explicacao.setWordWrap(True)
        self.seletor = SeletorDeUnidade()
        self.seletor.definir(self._unidade)
        self.seletor.unidadeEscolhida.connect(self._unidade_mudou)

        self.entradas = [CampoComUnidade(unidade_do_canal, x, digitos=DIGITOS) for x in (0.0, 1.0)]
        self.valores = [CampoComUnidade(self._unidade, ganho * x + offset, digitos=DIGITOS) for x in (0.0, 1.0)]
        grade = QGridLayout()
        grade.setHorizontalSpacing(8)
        grade.setVerticalSpacing(6)
        grade.addWidget(QLabel(self.tr("Unidade")), 0, 0)
        grade.addWidget(self.seletor, 0, 1, 1, 2)
        self.titulo_entrada = QLabel(self.tr("Entrada"))
        self.titulo_valor = QLabel(self.tr("Valor"))
        grade.addWidget(self.titulo_entrada, 1, 1)
        grade.addWidget(self.titulo_valor, 1, 2)
        for i, (x, y) in enumerate(zip(self.entradas, self.valores)):
            x.setObjectName(f"entrada_{i + 1}")
            y.setObjectName(f"valor_{i + 1}")
            grade.addWidget(QLabel(self.tr("Ponto {}").format(i + 1)), 2 + i, 0)
            grade.addWidget(x, 2 + i, 1)
            grade.addWidget(y, 2 + i, 2)
            for campo in (x, y):
                campo.valorMudou.connect(lambda _v: self._calcular())
                campo.textEdited.connect(lambda _t: self._calcular())
        grade.setColumnStretch(1, 1)
        grade.setColumnStretch(2, 1)

        self.resultado = QLabel()
        self.resultado.setObjectName("resultado_dois_pontos")
        self.resultado.setWordWrap(True)
        self.resultado.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        botoes = QDialogButtonBox()
        # Botões próprios, e não os padrão: o Qt não traz a tradução deles para o português.
        self.aplicar = botoes.addButton(self.tr("Aplicar"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.aplicar.setDefault(True)
        botoes.addButton(self.tr("Cancelar"), QDialogButtonBox.ButtonRole.RejectRole)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(16, 16, 16, 16)
        coluna.setSpacing(12)
        coluna.addWidget(explicacao)
        coluna.addLayout(grade)
        coluna.addWidget(self.resultado)
        coluna.addWidget(botoes)
        self.setMinimumWidth(self.fontMetrics().averageCharWidth() * 60)
        self._calcular()

    @property
    def unidade(self) -> str:
        return self._unidade

    def escala(self) -> tuple[str, float, float]:
        """``(unidade, ganho, offset)`` dos números como estão escritos agora (um em edição também conta). Levanta
        ``ValueError`` com o motivo."""
        x1, y1, x2, y2 = (_escrito(c) for c in (self.entradas[0], self.valores[0], self.entradas[1], self.valores[1]))
        return (self._unidade, *escala_por_dois_pontos(x1, y1, x2, y2))

    def _calcular(self) -> None:
        try:
            _, ganho, offset = self.escala()
        except ValueError as e:
            self.resultado.setText(self.tr("Não dá para aplicar: {}.").format(e))
            self.aplicar.setEnabled(False)
            return
        self.resultado.setText(self.tr("Ganho {} · offset {}").format(
            formatar_si(ganho, unidade_do_ganho(self._unidade, self.unidade_do_canal), DIGITOS),
            formatar_si(offset, self._unidade, DIGITOS)))
        self.aplicar.setEnabled(True)

    def _unidade_mudou(self, nova: str) -> None:
        c, d = unidades.conversao(self._unidade, nova) or (1.0, 0.0)
        for campo in self.valores:
            try:
                valor = _escrito(campo)          # lido na unidade de antes (o digitado e não confirmado também)
            except ValueError:
                valor = campo.valor
            campo.unidade = nova
            campo.definir_valor(c * valor + d)
        self._unidade = nova
        self._calcular()

    def accept(self) -> None:
        try:
            self.escala()
        except ValueError:
            return                                  # o motivo já está embaixo; o diálogo fica
        super().accept()


def _escrito(campo: CampoComUnidade) -> float:
    """O número escrito no campo agora (o confirmado ou o em edição). Levanta ``ValueError`` com o motivo."""
    try:
        return ler_numero(campo.text(), campo.unidade)
    except NumeroInvalido as e:
        raise ValueError(str(e)) from None
