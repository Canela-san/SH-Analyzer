"""O "Alinhar…" do inspetor (TR-07, docs/gui-plan.md, 9.4 e 9.6): o atraso de um traço em relação a outro da mesma
vista, medido nas amostras (``dados/alinhamento.py``), no trecho dos cursores ou na janela visível. O diálogo mede
sozinho a cada mudança (a referência, o método, o alcance da busca, o trecho), em segundo plano, e mostra o atraso, a
qualidade e o deslocamento que alinha; o "Aplicar" muda o deslocamento do traço, num passo de desfazer.

Não bloqueia: com ele aberto, os cursores e o zoom continuam andando, e a medida acompanha.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QGridLayout, QLabel, QVBoxLayout, QWidget
from shiboken6 import isValid

from ...ajuda import botao_de_ajuda
from ...componentes.basicos import CampoComUnidade, Segmentado
from ...componentes.numeros import formatar_si
from ...dados.alinhamento import METODOS, Alinhamento
from ...modelo.objetos import Traco

ESPERA_MS = 150                    # depois da última mudança: digitar o alcance não mede a cada tecla
FRACAO_DA_BUSCA = 0.1              # do trecho: a busca padrão, para cada lado (um atraso maior pede mais)


class DialogoDeAlinhar(QDialog):
    """``medir(metodo, referencia, busca_s, ao_terminar)`` põe a conta numa tarefa e a devolve (o resultado: um
    :class:`Alinhamento`, ou o motivo, em texto, de não haver um); ``trecho()`` diz o trecho de agora
    ``(inicio, fim, dos_cursores)``."""

    def __init__(self, traco: Traco, candidatos: list[Traco], trecho: Callable[[], tuple[float, float, bool] | None],
                 medir: Callable, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dialogo_alinhar")
        self.setWindowTitle(self.tr("Alinhar no tempo"))
        self.traco, self._trecho, self._medir = traco, trecho, medir
        self.alinhamento: Alinhamento | None = None
        self._tarefa = None

        titulo = QLabel(self.tr("Alinhar <b>{}</b> a outro traço da vista: o deslocamento no tempo dele passa a "
                                "desfazer o atraso medido.").format(traco.nome.replace("<", "&lt;")))
        titulo.setWordWrap(True)
        self.referencia = QComboBox()
        self.referencia.setObjectName("referencia_do_alinhamento")
        for t in candidatos:
            self.referencia.addItem(t.nome, t)
        self.metodo = Segmentado([self.tr("Correlação cruzada"), self.tr("Cruzamento por zero")])
        self.metodo.setObjectName("metodo_do_alinhamento")
        self.metodo.setToolTip(self.tr("A correlação usa o trecho inteiro (o mais preciso, e serve a qualquer sinal); "
                                       "o cruzamento por zero, as subidas pelo zero (um sinal periódico, como a rede)"))
        self.trecho = QLabel()
        self.trecho.setObjectName("trecho_do_alinhamento")
        self.trecho.setWordWrap(True)
        inicio_fim = trecho()
        largura = (inicio_fim[1] - inicio_fim[0]) if inicio_fim is not None else 0.0
        self.busca = CampoComUnidade("s", max(largura * FRACAO_DA_BUSCA, 0.0), minimo=0.0, digitos=4)
        self.busca.setObjectName("busca_do_alinhamento")
        self.busca.setToolTip(self.tr("Até quanto o traço é procurado para cada lado do trecho da referência"))
        grade = QGridLayout()
        grade.setHorizontalSpacing(8)
        grade.setVerticalSpacing(6)
        for i, (nome, campo) in enumerate(((self.tr("Referência"), self.referencia), (self.tr("Pelo"), self.metodo),
                                           (self.tr("Trecho"), self.trecho), (self.tr("Procurar até ±"), self.busca))):
            grade.addWidget(QLabel(nome), i, 0, Qt.AlignmentFlag.AlignVCenter)
            grade.addWidget(campo, i, 1)
        self.resultado = QLabel()
        self.resultado.setObjectName("resultado_do_alinhamento")
        self.resultado.setWordWrap(True)
        self.resultado.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.aviso = QLabel()
        self.aviso.setObjectName("aviso_do_alinhamento")
        self.aviso.setWordWrap(True)
        botoes = QDialogButtonBox()
        self.aplicar = botoes.addButton(self.tr("Aplicar"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.aplicar.setObjectName("aplicar_alinhamento")
        self.aplicar.setDefault(True)
        botoes.addButton(self.tr("Fechar"), QDialogButtonBox.ButtonRole.RejectRole)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        botoes.addButton(botao_de_ajuda("alinhar"), QDialogButtonBox.ButtonRole.HelpRole)
        coluna = QVBoxLayout(self)
        coluna.addWidget(titulo)
        coluna.addLayout(grade)
        coluna.addWidget(self.resultado)
        coluna.addWidget(self.aviso)
        coluna.addWidget(botoes)
        self.setMinimumWidth(460)

        self._espera = QTimer(self)
        self._espera.setSingleShot(True)
        self._espera.setInterval(ESPERA_MS)
        self._espera.timeout.connect(self.medir)
        self.referencia.currentIndexChanged.connect(lambda _i: self.pedir())
        self.metodo.escolhaMudou.connect(lambda _i: self.pedir())
        self.busca.valorMudou.connect(lambda _v: self.pedir())
        self.finished.connect(lambda _r: self._cancelar())
        self._mostrar(None, "")
        self.pedir()

    @property
    def metodo_escolhido(self) -> str:
        return METODOS[self.metodo.escolhida]

    def referencia_escolhida(self) -> Traco | None:
        return self.referencia.currentData()

    def novo_deslocamento(self) -> float | None:
        """O deslocamento que alinha (o de agora menos o atraso medido), ou ``None`` sem medida."""
        if self.alinhamento is None:
            return None
        return self.traco.receita.deslocamento_s - self.alinhamento.atraso_s

    def pedir(self) -> None:
        """Uma mudança (no diálogo, nos cursores ou no zoom): mede de novo daqui a pouco."""
        self._espera.start()

    def medir(self):
        self._espera.stop()
        self._cancelar()
        trecho, referencia = self._trecho(), self.referencia_escolhida()
        self._escrever_o_trecho(trecho)
        if referencia is None:
            self._mostrar(None, self.tr("Não há outro traço nesta vista para servir de referência."))
            return None
        if trecho is None:
            self._mostrar(None, self.tr("A vista ainda não tem um trecho desenhado."))
            return None
        self.resultado.setText(self.tr("Medindo…"))
        self.aplicar.setEnabled(False)
        self._tarefa = self._medir(self.metodo_escolhido, referencia, self.busca.valor, self._terminou)
        return self._tarefa

    def _cancelar(self) -> None:
        if self._tarefa is not None and self._tarefa.estado in ("esperando", "rodando"):
            self._tarefa.cancelar()
        self._tarefa = None

    def _terminou(self, tarefa) -> None:
        if tarefa is not self._tarefa or not isValid(self):
            return                              # uma medida antiga: a mais recente vale
        self._tarefa = None
        if tarefa.estado == "concluida" and isinstance(tarefa.resultado, Alinhamento):
            self._mostrar(tarefa.resultado, "")
        elif tarefa.estado == "concluida" and isinstance(tarefa.resultado, str):
            self._mostrar(None, tarefa.resultado[:1].upper() + tarefa.resultado[1:] + ".")
        elif tarefa.estado != "cancelada":
            self._mostrar(None, tarefa.erro or self.tr("a medida não terminou"))

    def _escrever_o_trecho(self, trecho) -> None:
        if trecho is None:
            self.trecho.setText("—")
            return
        a, b, dos_cursores = trecho
        onde = self.tr("entre os cursores") if dos_cursores else self.tr("a janela visível")
        self.trecho.setText(f"{onde}: {formatar_si(a, 's', 6)} – {formatar_si(b, 's', 6)}".replace("-", "−")
                            .replace(" − ", " – "))

    def _mostrar(self, alinhamento: Alinhamento | None, erro: str) -> None:
        self.alinhamento = alinhamento
        self.aplicar.setEnabled(alinhamento is not None)
        if alinhamento is None:
            self.resultado.setText(erro)
            self.aviso.setText("")
            return
        atraso = formatar_si(alinhamento.atraso_s, "s", 6).replace("-", "−")
        de, para = (formatar_si(x, "s", 6).replace("-", "−")
                    for x in (self.traco.receita.deslocamento_s, self.novo_deslocamento()))
        if alinhamento.metodo == "correlacao":
            qualidade = self.tr("coeficiente de correlação {}").format(
                formatar_si(alinhamento.qualidade, "", 5))
        else:
            qualidade = self.tr("{} cruzamentos, desvio de {}").format(
                alinhamento.casados, formatar_si(alinhamento.qualidade, "s", 3))
        self.resultado.setText(self.tr("Atraso medido: <b>{}</b> ({}). O deslocamento vai de {} para {}.").format(
            atraso, qualidade, de, para))
        self.aviso.setText(alinhamento.aviso[:1].upper() + alinhamento.aviso[1:] + "." if alinhamento.aviso else "")
