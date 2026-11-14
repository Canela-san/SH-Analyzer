"""A seção Processamento do inspetor do traço (docs/gui-plan.md, 9.4 e 7.2): a cadeia de transformações.

Cada etapa é um cartão: a chave liga e desliga, o resumo (clicar nele abre os parâmetros), as setas para subir e
descer na ordem e o ×. "Adicionar etapa" abre o menu das etapas; as mesmas ações estão na paleta de comandos
(Ctrl+K: "Adicionar etapa: passa-altas"). **Cada mudança é um comando de desfazer** (``MudarTracos`` com a cadeia
nova). Com vários traços selecionados e a mesma cadeia, a mudança vale para todos; com cadeias diferentes, a seção
pede para selecionar um só.

**Os padrões pensam na precisão:** a correção de sonda entra no começo da cadeia (a sonda age sobre o sinal antes de
qualquer filtro, e é a ordem da CLI); o passa-altas começa em 2 kHz (o início da faixa dos supraharmônicos); o
passa-baixas, abaixo da Nyquist do canal. Um corte que não serve para o canal (acima da Nyquist) não entra: o campo
fica vermelho, com o motivo.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import supraharmonicos.api as api
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...componentes.basicos import CampoComUnidade
from ...dados.cadeia import Cadeia, CorrecaoSonda, Etapa, EtapaInvalida, Filtro, RemoverDC
from ...modelo.comandos import MudarTracos
from ...modelo.objetos import Projeto, Traco

NOMES_DOS_FILTROS = {"passa_altas": "Passa-altas", "passa_baixas": "Passa-baixas", "passa_faixa": "Passa-faixa",
                     "rejeita_faixa": "Rejeita-faixa"}
CORTE_DOS_SUPRAHARMONICOS = 2000.0
TETO_DOS_SUPRAHARMONICOS = 150_000.0


def _abaixo_da_nyquist(taxa_hz: float) -> float:
    """O corte superior padrão: 150 kHz (o fim da faixa dos supraharmônicos) ou 80 % da Nyquist, o menor, em kHz
    redondo."""
    return float(min(TETO_DOS_SUPRAHARMONICOS, max(1000.0, round(0.4 * taxa_hz / 1000.0) * 1000.0)))


def nova_etapa(chave: str, taxa_hz: float) -> Etapa:
    """A etapa nova de ``chave``, com os padrões para um canal a ``taxa_hz``."""
    if chave == "passa_altas":
        return Filtro("passa_altas", (CORTE_DOS_SUPRAHARMONICOS,))
    if chave == "passa_baixas":
        return Filtro("passa_baixas", (_abaixo_da_nyquist(taxa_hz),))
    if chave == "passa_faixa":
        return Filtro("passa_faixa", (CORTE_DOS_SUPRAHARMONICOS, _abaixo_da_nyquist(taxa_hz)))
    if chave == "rejeita_faixa":
        return Filtro("rejeita_faixa", (45.0, 65.0), 2)            # a fundamental da rede
    if chave == "correcao_sonda":
        return CorrecaoSonda()
    if chave == "remover_dc":
        return RemoverDC()
    raise KeyError(chave)


ETAPAS_NOVAS = (("passa_altas", "Passa-altas"), ("passa_baixas", "Passa-baixas"), ("passa_faixa", "Passa-faixa"),
                ("rejeita_faixa", "Rejeita-faixa"), ("correcao_sonda", "Correção de sonda"),
                ("remover_dc", "Remover o DC"))


def inserir(cadeia: Cadeia, etapa: Etapa) -> Cadeia:
    """A cadeia com ``etapa``: a correção de sonda no começo (antes de qualquer filtro, como a sonda age), as outras
    no fim."""
    if isinstance(etapa, CorrecaoSonda):
        return Cadeia((etapa, *cadeia.etapas))
    return Cadeia((*cadeia.etapas, etapa))


def nome_da_etapa(etapa: Etapa) -> str:
    if isinstance(etapa, Filtro):
        return NOMES_DOS_FILTROS[etapa.filtro]
    if isinstance(etapa, CorrecaoSonda):
        return "Correção de sonda"
    return "Remover o DC"


class CartaoDeEtapa(QFrame):
    """Um cartão da cadeia. ``etapaMudou(etapa_nova, texto)``: os parâmetros (ou a chave) mudaram; ``mover(passo)``,
    ``remover()`` e ``abrir()``: os botões."""

    etapaMudou = Signal(object, str)
    mover = Signal(int)
    remover = Signal()
    abrir = Signal()

    def __init__(self, etapa: Etapa, indice: int, total: int, aberto: bool, taxas: list[float],
                 escolher_perfil: Callable[[], str | None], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("cartao_etapa")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.etapa, self.taxas, self._escolher_perfil = etapa, taxas, escolher_perfil
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(8, 6, 6, 6)
        coluna.setSpacing(6)
        topo = QHBoxLayout()
        topo.setSpacing(4)
        self.chave = QCheckBox()
        self.chave.setObjectName("chave_etapa")
        self.chave.setChecked(etapa.ligada)
        self.chave.setToolTip(self.tr("Ligar ou desligar a etapa (desligada, ela fica na cadeia sem ser aplicada)"))
        self.chave.clicked.connect(lambda marcada: self.etapaMudou.emit(replace(etapa, ligada=bool(marcada)),
                                                                   self.tr("Ligar") if marcada else self.tr("Desligar")))
        self.resumo = QToolButton()
        self.resumo.setObjectName("resumo_etapa")
        self.resumo.setText(f"{nome_da_etapa(etapa)} · {etapa.resumo()}" if not isinstance(etapa, RemoverDC)
                            else nome_da_etapa(etapa))
        self.resumo.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.resumo.setAutoRaise(True)
        self.resumo.setCheckable(True)
        self.resumo.setChecked(aberto)
        self.resumo.setToolTip(self.tr("Abrir os parâmetros"))
        self.resumo.clicked.connect(lambda _=False: self.abrir.emit())
        topo.addWidget(self.chave)
        topo.addWidget(self.resumo, 1)
        for texto, dica, passo, habilitado in (("▲", self.tr("Subir na cadeia"), -1, indice > 0),
                                               ("▼", self.tr("Descer na cadeia"), 1, indice < total - 1)):
            b = QToolButton()
            b.setObjectName("subir_etapa" if passo < 0 else "descer_etapa")
            b.setText(texto)
            b.setToolTip(dica)
            b.setAutoRaise(True)
            b.setEnabled(habilitado)
            b.clicked.connect(lambda _=False, p=passo: self.mover.emit(p))
            topo.addWidget(b)
        tirar = QToolButton()
        tirar.setObjectName("remover_etapa")
        tirar.setText("×")
        tirar.setToolTip(self.tr("Tirar a etapa da cadeia"))
        tirar.setAutoRaise(True)
        tirar.clicked.connect(lambda _=False: self.remover.emit())
        topo.addWidget(tirar)
        coluna.addLayout(topo)
        self.parametros = QWidget()
        self.parametros.setObjectName("parametros_etapa")
        self._montar_parametros()
        self.parametros.setVisible(aberto)
        coluna.addWidget(self.parametros)

    # ------------------------------------------------------------------ os parâmetros de cada tipo

    def _montar_parametros(self) -> None:
        grade = QGridLayout(self.parametros)
        grade.setContentsMargins(22, 0, 0, 0)
        grade.setHorizontalSpacing(8)
        grade.setVerticalSpacing(4)
        etapa = self.etapa
        if isinstance(etapa, Filtro):
            self.tipo = QComboBox()
            self.tipo.setObjectName("tipo_filtro")
            for chave, nome in NOMES_DOS_FILTROS.items():
                self.tipo.addItem(nome, chave)
            self.tipo.setCurrentIndex(list(NOMES_DOS_FILTROS).index(etapa.filtro))
            self.tipo.activated.connect(self._tipo_escolhido)
            grade.addWidget(QLabel(self.tr("Tipo")), 0, 0)
            grade.addWidget(self.tipo, 0, 1)
            self.cortes = []
            rotulos = ([self.tr("Corte")] if len(etapa.cortes) == 1
                       else [self.tr("Corte inferior"), self.tr("Corte superior")])
            for i, (rotulo, corte) in enumerate(zip(rotulos, etapa.cortes)):
                campo = CampoComUnidade("Hz", corte, minimo=0.0, digitos=5)
                campo.setObjectName(f"corte_{i}")
                campo.valorMudou.connect(lambda v, k=i: self._corte_mudou(k, v))
                self.cortes.append(campo)
                grade.addWidget(QLabel(rotulo), 1 + i, 0)
                grade.addWidget(campo, 1 + i, 1)
            self.ordem = QSpinBox()
            self.ordem.setObjectName("ordem_filtro")
            self.ordem.setRange(1, api.ORDEM_MAXIMA_DO_FILTRO)
            self.ordem.setValue(etapa.ordem)
            self.ordem.setKeyboardTracking(False)
            self.ordem.setToolTip(self.tr("Butterworth de fase zero: o filtro passa duas vezes (ida e volta), e a "
                                          "atenuação fora da banda é o dobro da desta ordem"))
            self.ordem.valueChanged.connect(lambda v: self._propor(replace(etapa, ordem=int(v)), self.ordem))
            grade.addWidget(QLabel(self.tr("Ordem")), 1 + len(etapa.cortes), 0)
            grade.addWidget(self.ordem, 1 + len(etapa.cortes), 1)
        elif isinstance(etapa, CorrecaoSonda):
            self.perfil = QComboBox()
            self.perfil.setObjectName("perfil_sonda")
            self.perfil.addItem(self.tr("Automático (o da captura)"), None)
            if etapa.perfil is not None:
                self.perfil.addItem(etapa.perfil, etapa.perfil)
                self.perfil.setCurrentIndex(1)
            self.perfil.addItem(self.tr("Escolher um arquivo…"), "escolher")
            self.perfil.activated.connect(self._perfil_escolhido)
            grade.addWidget(QLabel(self.tr("Perfil")), 0, 0)
            grade.addWidget(self.perfil, 0, 1)
            self.problema = QLabel()
            self.problema.setObjectName("problema_etapa")
            self.problema.setWordWrap(True)
            self.problema.hide()
            grade.addWidget(self.problema, 1, 0, 1, 2)
        else:
            texto = QLabel(self.tr("Tira a média do canal inteiro (calculada uma vez, das amostras), passada pelas "
                                   "etapas de antes. O traço não muda de altura a cada pan."))
            texto.setWordWrap(True)
            grade.addWidget(texto, 0, 0, 1, 2)
        grade.setColumnStretch(1, 1)

    def _propor(self, etapa: Etapa, campo=None, texto: str = "") -> bool:
        """Manda a etapa nova se ela vale para todos os canais selecionados; senão, marca o campo."""
        try:
            if isinstance(etapa, Filtro):
                for taxa in self.taxas:
                    api.validar_filtro(etapa.filtro, etapa.cortes, etapa.ordem, taxa)
        except api.ErroSHAN as e:
            if isinstance(campo, CampoComUnidade):
                campo.marcar_invalido(str(e))
            elif campo is not None:
                campo.setToolTip(str(e))
            return False
        if etapa != self.etapa:
            self.etapaMudou.emit(etapa, texto or self.tr("Mudar"))
        return True

    def _tipo_escolhido(self, _indice: int) -> None:
        etapa = self.etapa
        novo = self.tipo.currentData()
        if novo == etapa.filtro:
            return
        dois = novo in ("passa_faixa", "rejeita_faixa")
        if dois and len(etapa.cortes) == 1:
            cortes = ((etapa.cortes[0], _abaixo_da_nyquist(min(self.taxas)))
                      if etapa.cortes[0] < _abaixo_da_nyquist(min(self.taxas)) else (45.0, 65.0))
        elif not dois and len(etapa.cortes) == 2:
            cortes = (etapa.cortes[0] if novo == "passa_altas" else etapa.cortes[1],)
        else:
            cortes = etapa.cortes
        try:
            nova = Filtro(novo, cortes, etapa.ordem, ligada=etapa.ligada)
        except EtapaInvalida as e:
            self.tipo.setToolTip(str(e))
            return
        if not self._propor(nova, self.tipo):
            self.tipo.setCurrentIndex(list(NOMES_DOS_FILTROS).index(etapa.filtro))

    def _corte_mudou(self, indice: int, valor: float) -> None:
        cortes = list(self.etapa.cortes)
        cortes[indice] = valor
        try:
            nova = replace(self.etapa, cortes=tuple(cortes))
        except EtapaInvalida as e:
            self.cortes[indice].marcar_invalido(str(e))
            return
        self._propor(nova, self.cortes[indice])

    def _perfil_escolhido(self, _indice: int) -> None:
        dado = self.perfil.currentData()
        if dado == "escolher":
            caminho = self._escolher_perfil()
            if not caminho:
                self.perfil.setCurrentIndex(0 if self.etapa.perfil is None else 1)
                return
            try:
                api.carregar_perfil(caminho)
            except api.ErroSHAN as e:
                self.problema.setText(str(e))
                self.problema.show()
                self.perfil.setCurrentIndex(0 if self.etapa.perfil is None else 1)
                return
            dado = str(caminho)
        self._propor(replace(self.etapa, perfil=dado), self.perfil)


class SecaoDeProcessamento(QWidget):
    """A cadeia dos traços selecionados, editável (ver o começo do módulo)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("secao_processamento")
        self.projeto: Projeto | None = None
        self.tracos: tuple[Traco, ...] = ()
        self.taxas: list[float] = []
        self.cartoes: list[CartaoDeEtapa] = []
        self._aberta: int | None = None
        self._mostrada: tuple | None = None
        self.dialogos_de: Callable[[], object] | None = None      # a janela liga: os diálogos do controle
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(6)
        self.aviso = QLabel()
        self.aviso.setObjectName("aviso_processamento")
        self.aviso.setWordWrap(True)
        coluna.addWidget(self.aviso)
        self._lista = QVBoxLayout()
        self._lista.setSpacing(4)
        coluna.addLayout(self._lista)
        self.menu = QMenu(self)
        self.acoes: list[QAction] = []
        for chave, nome in ETAPAS_NOVAS:
            acao = QAction(self.tr("Adicionar etapa: {}").format(nome.lower()), self)
            acao.setData(chave)
            acao.triggered.connect(lambda _=False, c=chave: self.adicionar(c))
            self.acoes.append(acao)
            self.menu.addAction(acao)
        self.botao_adicionar = QToolButton()
        self.botao_adicionar.setObjectName("adicionar_etapa")
        self.botao_adicionar.setText(self.tr("Adicionar etapa"))
        self.botao_adicionar.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.botao_adicionar.setMenu(self.menu)
        coluna.addWidget(self.botao_adicionar, 0, Qt.AlignmentFlag.AlignLeft)

    # ------------------------------------------------------------------ mostrar

    @property
    def cadeia(self) -> Cadeia | None:
        """A cadeia que a seção edita (a dos traços selecionados, se for a mesma); None se diferem."""
        cadeias = {t.receita.cadeia for t in self.tracos}
        return next(iter(cadeias)) if len(cadeias) == 1 else None

    def mostrar(self, projeto: Projeto, tracos, taxas: list[float]) -> None:
        """Mostra a cadeia dos traços. Só refaz os cartões se a seleção, a cadeia ou as taxas mudaram: arrastar o
        ganho no inspetor muda o traço a cada passo, e os cartões ficam como estão."""
        mudou_a_selecao = tuple(tracos) != self.tracos
        self.projeto, self.tracos, self.taxas = projeto, tuple(tracos), list(taxas) or [1.0]
        if mudou_a_selecao:
            self._aberta = None
        if (self.tracos, self.cadeia, tuple(self.taxas)) != self._mostrada:
            self.atualizar()

    def _guardar_o_mostrado(self) -> None:
        self._mostrada = (self.tracos, self.cadeia, tuple(self.taxas))

    def atualizar(self) -> None:
        self._guardar_o_mostrado()
        for cartao in self.cartoes:
            self._lista.removeWidget(cartao)
            cartao.deleteLater()
        self.cartoes = []
        cadeia = self.cadeia
        editavel = bool(self.tracos) and cadeia is not None
        for acao in self.acoes:
            acao.setEnabled(editavel)
        self.botao_adicionar.setEnabled(editavel)
        if not self.tracos:
            self.aviso.setText("")
            return
        if cadeia is None:
            self.aviso.setText(self.tr("Os traços selecionados têm cadeias diferentes: selecione um só para editar a "
                                       "dele."))
            return
        self.aviso.setText("" if cadeia.etapas else self.tr("Nenhuma etapa: o traço é o canal como ele é."))
        if self._aberta is not None and self._aberta >= len(cadeia.etapas):
            self._aberta = None
        for i, etapa in enumerate(cadeia.etapas):
            cartao = CartaoDeEtapa(etapa, i, len(cadeia.etapas), i == self._aberta, self.taxas, self._escolher_perfil)
            cartao.etapaMudou.connect(lambda nova, texto, k=i: self._substituir(k, nova, texto))
            cartao.mover.connect(lambda passo, k=i: self.mover(k, passo))
            cartao.remover.connect(lambda k=i: self.remover(k))
            cartao.abrir.connect(lambda k=i: self._abrir(k))
            self._lista.addWidget(cartao)
            self.cartoes.append(cartao)

    # ------------------------------------------------------------------ mudar (sempre pela pilha)

    def _trocar(self, nova: Cadeia, texto: str) -> bool:
        if not self.tracos or self.projeto is None or nova == self.cadeia:
            return False
        nomes = self.tracos[0].nome if len(self.tracos) == 1 else self.tr("{} traços").format(len(self.tracos))
        self.projeto.pilha.push(MudarTracos(self.tracos, cadeia=nova, texto=f"{texto} ({nomes})"))
        return True

    def adicionar(self, chave: str) -> bool:
        cadeia = self.cadeia
        if cadeia is None:
            return False
        etapa = nova_etapa(chave, min(self.taxas))
        nova = inserir(cadeia, etapa)
        self._aberta = nova.etapas.index(etapa) if not isinstance(etapa, RemoverDC) else None
        return self._trocar(nova, self.tr("Adicionar {}").format(nome_da_etapa(etapa).lower()))

    def remover(self, indice: int) -> bool:
        cadeia = self.cadeia
        if cadeia is None or not 0 <= indice < len(cadeia.etapas):
            return False
        etapas = list(cadeia.etapas)
        tirada = etapas.pop(indice)
        self._aberta = None
        return self._trocar(Cadeia(tuple(etapas)), self.tr("Tirar {}").format(nome_da_etapa(tirada).lower()))

    def mover(self, indice: int, passo: int) -> bool:
        cadeia = self.cadeia
        destino = indice + passo
        if cadeia is None or not (0 <= indice < len(cadeia.etapas) and 0 <= destino < len(cadeia.etapas)):
            return False
        etapas = list(cadeia.etapas)
        etapas[indice], etapas[destino] = etapas[destino], etapas[indice]
        if self._aberta == indice:
            self._aberta = destino
        return self._trocar(Cadeia(tuple(etapas)), self.tr("Reordenar a cadeia"))

    def _substituir(self, indice: int, etapa: Etapa, texto: str) -> None:
        cadeia = self.cadeia
        if cadeia is None:
            return
        etapas = list(cadeia.etapas)
        etapas[indice] = etapa
        self._trocar(Cadeia(tuple(etapas)), f"{texto}: {nome_da_etapa(etapa).lower()}")

    def _abrir(self, indice: int) -> None:
        self._aberta = None if self._aberta == indice else indice
        self.atualizar()

    def _escolher_perfil(self) -> str | None:
        dialogos = self.dialogos_de() if self.dialogos_de is not None else None
        if dialogos is None:
            return None
        caminho = dialogos.abrir_arquivo(self.tr("Escolher o perfil de sonda"), self.tr("Perfis de sonda (*.json)"))
        return str(caminho) if caminho else None
