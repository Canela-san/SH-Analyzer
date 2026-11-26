"""A exportação dos dados de uma vista de tempo (a F5.5; FG-07): o diálogo e a coleta dos traços. A gravação é a de
``dados/exportar_dados.py`` (sem Qt), numa tarefa pesada da área (``AreaDeAnalise.exportar_dados``).

* **Os traços:** os visíveis da vista, como a tela os mostra: o canal com a conversão do traço (a calibração, o
  ganho e o offset) ou, com transformações (a cadeia), a materialização pronta. A coleta acompanha as
  materializações enquanto vive (o serviço da janela já as calcula para a vista; uma que ainda não começou começa) e
  o diálogo espera por elas, com o andamento. "Sem as transformações" e os códigos do ADC vêm do canal.
* **A região:** a janela visível, entre os cursores (C1 e C2, ligados) ou a captura inteira. Um traço com tempo
  próprio (andado no tempo) entra com o trecho dele que aparece na região, como nas medidas.
* **O diálogo** mostra o tamanho do que vai sair (as linhas, o trecho, os bytes) e as recusas com a razão (as taxas
  diferentes, os crus de capturas de tipos diferentes, a materialização que ainda não ficou pronta), e lembra o que
  foi escolhido da última vez.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ...componentes.basicos import Segmentado
from ...componentes.numeros import formatar_bytes, formatar_si
from ...dados import exportar_dados as ed
from ...dados import unidades
from ...dados.exportar_dados import ColunaDeDados, DadosInvalidos, OpcoesDosDados, TrechoDeDados
from ...modelo.objetos import Projeto, Traco, Vista, novo_id

REGIOES = ("janela", "cursores", "inteira")
VALORES = ("tela", "sem_transformacoes", "crus")
NOMES_DAS_REGIOES = {"janela": "janela", "cursores": "cursores", "inteira": "captura inteira"}
VALORES_NO_CSV_GRANDE = 20_000_000
"""Acima disso (linhas × colunas), o diálogo lembra que um CSV é lento de gravar e de abrir."""


@dataclass(frozen=True)
class PedidoDeDados:
    opcoes: OpcoesDosDados = field(default_factory=OpcoesDosDados)
    regiao: str = "janela"
    transformacoes: bool = True          # False: os traços sem as transformações (os crus nunca as têm)

    @property
    def valores(self) -> str:
        return "crus" if self.opcoes.crus else "tela" if self.transformacoes else "sem_transformacoes"


class ColetaDaVista(QObject):
    """Os traços visíveis de uma vista de tempo como colunas. ``mudou`` sai quando uma materialização que eles
    esperam anda ou fica pronta; :meth:`soltar` larga as materializações (o diálogo fechado, a exportação feita)."""

    mudou = Signal()

    def __init__(self, vista: Vista, widget, projeto: Projeto, materializacoes, parent: QObject | None = None):
        super().__init__(parent)
        self.vista, self.widget, self.projeto, self.materializacoes = vista, widget, projeto, materializacoes
        self._usuario = ("exportar_dados", novo_id())
        self._estados: dict[Traco, object] = {}
        self._solta = False
        materializacoes.mudou.connect(self._materializacao_mudou)
        for traco in self.tracos:
            fonte = self._fonte(traco)
            if fonte is not None and not traco.receita.cadeia.vazia:
                r = traco.receita
                self._estados[traco] = materializacoes.acompanhar((*self._usuario, traco.id), fonte, r.canal,
                                                                  r.cadeia)

    @property
    def tracos(self) -> list[Traco]:
        return [t for t in self.vista.tracos if t.receita.visivel]

    @property
    def tem_transformacoes(self) -> bool:
        return bool(self._estados)

    def soltar(self) -> None:
        if self._solta:
            return
        self._solta = True
        self.materializacoes.mudou.disconnect(self._materializacao_mudou)
        for traco in self._estados:
            self.materializacoes.largar((*self._usuario, traco.id))
        self._estados.clear()

    def _materializacao_mudou(self, estado) -> None:
        if any(e is estado for e in self._estados.values()):
            self.mudou.emit()

    def _fonte(self, traco: Traco):
        fonte = next((f for f in self.projeto.fontes if f.id == traco.receita.fonte), None)
        return None if fonte is None or fonte.esta_ausente else fonte

    # ------------------------------------------------------------------ as colunas e o trecho

    def esperando(self, pedido: PedidoDeDados) -> list[str]:
        """O que falta para o pedido sair: as materializações ainda não prontas (o nome do traço e o andamento)."""
        if not pedido.transformacoes or pedido.opcoes.crus:
            return []
        faltam = []
        for traco, estado in self._estados.items():
            if estado.pronta is None:
                andamento = (f"erro: {estado.erro}" if estado.erro else "na fila" if estado.na_fila
                             else f"{round(100 * (estado.progresso or 0))} %")
                faltam.append(f"{traco.receita.nome} ({andamento})")
        return faltam

    def colunas(self, pedido: PedidoDeDados) -> list[ColunaDeDados]:
        transformadas = pedido.transformacoes and not pedido.opcoes.crus
        colunas = []
        for traco in self.tracos:
            r = traco.receita
            fonte = self._fonte(traco)
            if fonte is None:
                raise DadosInvalidos(f"a captura de {r.nome} não está aberta (o arquivo não foi achado)")
            canal = fonte.canal(r.canal)
            grandeza, unidade = unidades.do_traco(r.unidade, canal.unidade, canal.nome_grandeza)
            receita = r.para_dict()
            comum = {"t0_s": r.deslocamento_s, "unidade": unidade, "grandeza": grandeza, "fonte": fonte.id}
            estado = self._estados.get(traco)
            if estado is not None and transformadas:
                if estado.pronta is None:
                    raise DadosInvalidos("esperando as transformações de " + ", ".join(self.esperando(pedido)))
                escala, deslocamento = r.afim(1.0, 0.0)
                colunas.append(ColunaDeDados(r.nome, estado.pronta.amostras, canal.taxa_hz, escala=escala,
                                             deslocamento=deslocamento, codigos=False, receita=receita, **comum))
            else:
                if estado is not None:                  # a cadeia fica na proveniência, como não aplicada
                    receita = {**receita, "etapas": [], "etapas_nao_aplicadas": receita["etapas"]}
                escala, deslocamento = r.afim(canal.escala, canal.deslocamento)
                colunas.append(ColunaDeDados(r.nome, canal.amostras, canal.taxa_hz, escala=escala,
                                             deslocamento=deslocamento, receita=receita, **comum))
        return colunas

    def regioes(self, regiao: str) -> list[tuple[float, float]] | None:
        """O trecho de cada traço (no tempo dele), ou ``None`` na captura inteira."""
        if regiao == "inteira":
            return None
        if regiao == "cursores":
            posicoes = self.widget.cursores
            if posicoes is None:
                raise DadosInvalidos("os cursores estão desligados")
            a, b = sorted(posicoes)
        else:
            janela = self.widget.janela_de_tempo()
            if janela is None:
                raise DadosInvalidos("a vista ainda não mostra nada")
            a, b = janela
        return [self.widget.regiao_do_traco(t, a, b) for t in self.tracos]

    def trecho(self, pedido: PedidoDeDados) -> TrechoDeDados:
        """O trecho do pedido, conferido (``DadosInvalidos`` com a razão)."""
        trecho = ed.recortar(self.colunas(pedido), self.regioes(pedido.regiao))
        ed.conferir(trecho, pedido.opcoes)
        return trecho

    def fontes_usadas(self, trecho: TrechoDeDados):
        ids = dict.fromkeys(c.fonte for c in trecho.colunas)
        return [f for f in self.projeto.fontes if f.id in ids]


def tamanho_estimado(trecho: TrechoDeDados, opcoes: OpcoesDosDados) -> int:
    """Os bytes do arquivo, mais ou menos: os binários pelo tipo; o CSV pelos algarismos (o tempo e ~18 caracteres
    por valor em unidades, ~6 por código)."""
    k = len(trecho.colunas)
    if opcoes.formato == "csv":
        return trecho.n * (18 + k * (7 if opcoes.crus else 19))
    item = trecho.colunas[0].amostras.dtype.itemsize if opcoes.crus else 8
    return trecho.n * k * item


def _milhares(n: int) -> str:
    return f"{n:,}".replace(",", " ")


class DialogoDeExportarDados(QDialog):
    """O pedido: o formato, a região, os valores e, no CSV, o separador e o decimal. ``pedido()`` depois do
    ``accepted``."""

    def __init__(self, coleta: ColetaDaVista, anterior: PedidoDeDados | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dialogo_exportar_dados")
        self.setWindowTitle(self.tr("Exportar os dados da vista"))
        self.coleta = coleta
        anterior = anterior or PedidoDeDados()

        n = len(coleta.tracos)
        cabeca = QLabel(self.tr("{} · {} traço(s) visível(is)").format(coleta.vista.nome, n))
        cabeca.setObjectName("titulo_exportar_dados")
        self.formato = Segmentado([ed.FORMATOS[f].nome for f in ed.FORMATOS])
        self.descricao = QLabel()
        self.descricao.setObjectName("rotulo_da_propriedade")
        self.descricao.setWordWrap(True)
        self.regiao = Segmentado([self.tr("Janela"), self.tr("Cursores"), self.tr("Captura inteira")])
        self.valores = Segmentado([self.tr("Como na tela"), self.tr("Sem transformações"),
                                   self.tr("Códigos do ADC")])
        self.valores.botao(2).setToolTip(self.tr("Os códigos do ADC no tipo da captura, com a escala e o "
                                                 "deslocamento de cada coluna para chegar à unidade"))
        self.separador = QComboBox()
        self.separador.setObjectName("separador_do_csv")
        for sep, nome in ((";", self.tr("ponto e vírgula (;)")), (",", self.tr("vírgula (,)")),
                          ("\t", self.tr("tabulação"))):
            self.separador.addItem(nome, sep)
        self.decimal = QComboBox()
        self.decimal.setObjectName("decimal_do_csv")
        self.decimal.addItem(self.tr("vírgula (1,5)"), ",")
        self.decimal.addItem(self.tr("ponto (1.5)"), ".")
        self.resumo = QLabel()
        self.resumo.setObjectName("resumo_dos_dados")
        self.resumo.setWordWrap(True)
        self.aviso = QLabel()
        self.aviso.setObjectName("aviso_da_exportacao")
        self.aviso.setWordWrap(True)

        botoes = QDialogButtonBox()
        # Botões próprios, e não os padrão: o Qt não traz a tradução deles para o português.
        self.exportar = botoes.addButton(self.tr("Exportar…"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.exportar.setObjectName("exportar_dados")
        self.exportar.setDefault(True)
        botoes.addButton(self.tr("Cancelar"), QDialogButtonBox.ButtonRole.RejectRole)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        grade = QGridLayout()
        grade.setHorizontalSpacing(10)
        grade.setVerticalSpacing(8)
        linhas = [(self.tr("Formato"), self.formato), (None, self.descricao), (self.tr("Região"), self.regiao),
                  (self.tr("Valores"), self.valores)]
        self._rotulos_do_csv = []
        for i, (texto, campo) in enumerate(linhas):
            if texto:
                grade.addWidget(QLabel(texto), i, 0)
            grade.addWidget(campo, i, 1)
        for texto, campo in ((self.tr("Colunas separadas por"), self.separador), (self.tr("Decimal"), self.decimal)):
            rotulo = QLabel(texto)
            self._rotulos_do_csv.append(rotulo)
            linha = grade.rowCount()
            grade.addWidget(rotulo, linha, 0)
            grade.addWidget(campo, linha, 1)
        grade.setColumnStretch(1, 1)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(16, 16, 16, 16)
        coluna.setSpacing(12)
        coluna.addWidget(cabeca)
        coluna.addLayout(grade)
        coluna.addWidget(self.resumo)
        coluna.addWidget(self.aviso)
        coluna.addWidget(botoes)
        self.setMinimumWidth(self.fontMetrics().averageCharWidth() * 104)     # os 7 formatos sem cortar o nome

        if coleta.widget.cursores is None:
            self.regiao.habilitar(1, False, self.tr("Os cursores estão desligados (C na vista liga)"))
        if not coleta.tem_transformacoes:
            self.valores.habilitar(1, False, self.tr("Nenhum traço visível tem transformações"))
        self.formato.escolher(list(ed.FORMATOS).index(anterior.opcoes.formato))
        regiao = anterior.regiao if self.regiao.botao(REGIOES.index(anterior.regiao)).isEnabled() else "janela"
        self.regiao.escolher(REGIOES.index(regiao))
        valores = anterior.valores if self.valores.botao(VALORES.index(anterior.valores)).isEnabled() else "tela"
        self.valores.escolher(VALORES.index(valores))
        self.separador.setCurrentIndex(self.separador.findData(anterior.opcoes.separador))
        self.decimal.setCurrentIndex(self.decimal.findData(anterior.opcoes.decimal))
        for seletor in (self.formato, self.regiao, self.valores):
            seletor.escolhaMudou.connect(lambda _i: self._atualizar())
        for combo in (self.separador, self.decimal):
            combo.currentIndexChanged.connect(lambda _i: self._atualizar())
        coleta.mudou.connect(self._atualizar)
        self._atualizar()

    def pedido(self) -> PedidoDeDados:
        """O pedido como está escolhido (levanta ``DadosInvalidos``, se o separador e o decimal são o mesmo)."""
        valores = VALORES[self.valores.escolhida]
        opcoes = OpcoesDosDados(list(ed.FORMATOS)[self.formato.escolhida], crus=valores == "crus",
                                separador=self.separador.currentData(), decimal=self.decimal.currentData())
        return PedidoDeDados(opcoes, REGIOES[self.regiao.escolhida], transformacoes=valores == "tela")

    def _atualizar(self) -> None:
        formato = list(ed.FORMATOS)[self.formato.escolhida]
        self.descricao.setText(ed.FORMATOS[formato].descricao)
        for widget in (*self._rotulos_do_csv, self.separador, self.decimal):   # sempre ali: o diálogo não pula
            widget.setEnabled(formato == "csv")
            widget.setToolTip("" if formato == "csv" else self.tr("Só no CSV"))
        try:
            pedido = self.pedido()
            trecho = self.coleta.trecho(pedido)
        except DadosInvalidos as erro:
            faltam = self.coleta.esperando(self._pedido_sem_conferir())
            self.resumo.setText("")
            self._avisar(str(erro)[:1].upper() + str(erro)[1:] + ("…" if faltam else "."),
                         "aviso" if faltam else "erro")
            self.exportar.setEnabled(False)
            return
        t0 = trecho.t0_s
        ultima = t0 + (trecho.n - 1) / trecho.taxa_hz
        self.resumo.setText(self.tr("{} coluna(s) × {} linhas, de {} a {} ({}) · ~{}").format(
            len(trecho.colunas), _milhares(trecho.n), formatar_si(t0, "s", 6), formatar_si(ultima, "s", 6),
            formatar_si(trecho.n / trecho.taxa_hz, "s", 4), formatar_bytes(tamanho_estimado(trecho, pedido.opcoes))))
        if formato == "csv" and trecho.n * len(trecho.colunas) > VALORES_NO_CSV_GRANDE:
            self._avisar(self.tr("Um CSV deste tamanho é lento de gravar e de abrir; o HDF5, o MAT e o NPZ saem em "
                                 "segundos e menores."), "aviso")
        else:
            self._avisar("", "info")
        self.exportar.setEnabled(True)

    def _pedido_sem_conferir(self) -> PedidoDeDados:
        valores = VALORES[self.valores.escolhida]
        return PedidoDeDados(OpcoesDosDados(list(ed.FORMATOS)[self.formato.escolhida], crus=valores == "crus"),
                             REGIOES[self.regiao.escolhida], transformacoes=valores == "tela")

    def _avisar(self, texto: str, nivel: str) -> None:
        self.aviso.setText(texto)
        self.aviso.setVisible(bool(texto))
        self.aviso.setProperty("nivel", nivel)
        self.aviso.style().unpolish(self.aviso)
        self.aviso.style().polish(self.aviso)
