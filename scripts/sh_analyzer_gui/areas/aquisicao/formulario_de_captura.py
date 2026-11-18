"""O formulário de uma captura (docs/gui-plan.md, 11.5; a coluna esquerda do B2): o cabeçalho, os canais, a taxa e a
duração, o destino e o avançado, montando um ``PedidoDeCaptura`` (``sh_placa/pedido.py``) a cada mudança.

**Uma fonte só:** o pedido. Cada campo que muda refaz o pedido dos campos e, se ele mudou, sai em
``pedidoMudou(pedido)``; :meth:`FormularioDeCaptura.definir_pedido` (um modelo escolhido, o pedido da última vez)
põe o pedido nos campos. Quem valida é a seção (``capturar.py``), que devolve os problemas com
:meth:`~FormularioDeCaptura.mostrar_problemas`: cada um aparece na seção do campo, e o campo com um erro fica marcado.

**Os canais** ficam na ordem em que o ADC os varre (a crescente), um por linha, com a grandeza e a sonda; na linha de
baixo, a faixa (com o LSB ao lado), o ganho e, depois de uma conferência, a faixa sugerida. Um canal desligado guarda o
que tinha: ligado de novo, volta como estava. Escolher uma sonda cujo perfil diz o ganho com que foi gerado preenche
o ganho, se ele estava vazio.

**O que se calcula do pedido** fica ao lado dos campos: a taxa por canal e a Nyquist, o teto da PRU, os blocos
inteiros da duração, o tamanho do arquivo.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from sh_placa import pedido as pd
from sh_placa.pedido import Canal, PedidoDeCaptura, PerfilDisponivel, Problema

from ...componentes.basicos import CampoComUnidade, RotuloDeIcone, Segmentado
from ...componentes.numeros import (
    NumeroInvalido,
    formatar_bytes,
    formatar_duracao,
    formatar_si,
    ler_numero,
    separador_decimal,
)
from ...tema.aplicar import aparencia
from ...tema.icones import IconeDoTema
from .pecas import fonte, repolir
from .textos import traduzir

GRANDEZAS = (("tensao", "tensão"), ("corrente", "corrente"), ("temperatura", "temperatura"))
FAIXAS = ((20.48, "±10,24 V"), (10.24, "±5,12 V"), (5.12, "±2,56 V"))
MODOS_DO_SPI = (("rapido", "rápido, fase B (o padrão)"), ("rapido:a", "rápido, fase A"),
                ("rapido:c", "rápido, fase C"), ("lenta", "lento (o de antes de 22/10/2026)"))
UNIDADES_DA_DURACAO = (("s", 1.0), ("min", 60.0), ("h", 3600.0))
MODOS_DA_DURACAO = ("Tempo", "Blocos", "Até parar")
DESTINOS = ("computador", "cartao")
CAMPOS_DAS_SECOES = {"cabecalho": ("titulo", "descricao"), "canais": ("canais", "grandeza", "sonda", "faixa", "ganho"),
                     "taxa": ("taxa", "duracao"), "destino": ("destino", "arquivo"), "avancado": ("spi", "atrasos")}
LARGURA = 400


def texto_da_faixa(faixa_v: float) -> str:
    for valor, texto in FAIXAS:
        if abs(valor - faixa_v) < pd.TOLERANCIA_DA_FAIXA_V:
            return texto
    return f"{faixa_v:g} V"


def _numero(texto: str) -> float:
    """O número de um campo ("19,357", "1e-3"); ``nan`` no que não é número (a validação o mostra)."""
    try:
        return ler_numero(texto)
    except NumeroInvalido:
        return math.nan


def unidade_da_duracao(segundos: float) -> int:
    """A maior unidade de :data:`UNIDADES_DA_DURACAO` em que ``segundos`` dá um número inteiro (1 h, e não 60 min);
    os segundos, se nenhuma."""
    for i in range(len(UNIDADES_DA_DURACAO) - 1, 0, -1):
        multiplicador = UNIDADES_DA_DURACAO[i][1]
        if math.isfinite(segundos) and segundos >= multiplicador and segundos % multiplicador == 0:
            return i
    return 0


def texto_do_numero(valor: float) -> str:
    """O número como se digita, o mais curto que volta igual, com o separador decimal das configurações."""
    texto = repr(float(valor))
    texto = texto[:-2] if texto.endswith(".0") else texto
    return texto.replace(".", separador_decimal())


def _inteiro(texto: str) -> int:
    texto = texto.strip().replace(" ", "").replace(" ", "")
    return int(texto) if texto.isdigit() else -1


class _Secao(QFrame):
    """Uma seção do formulário: o título, um texto à direita e o corpo (``corpo``), com os problemas dela embaixo."""

    def __init__(self, titulo: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("secao_do_formulario")
        self.titulo = QLabel(titulo)
        self.titulo.setFont(fonte("corpo", QFont.Weight.DemiBold))
        self.lado = QLabel()
        self.lado.setObjectName("texto_mudo")
        self.lado.setFont(fonte("secundario"))
        topo = QHBoxLayout()
        topo.setContentsMargins(0, 0, 0, 0)
        topo.addWidget(self.titulo)
        topo.addStretch(1)
        topo.addWidget(self.lado)
        self.corpo = QVBoxLayout()
        self.corpo.setContentsMargins(0, 0, 0, 0)
        self.corpo.setSpacing(6)
        self.problemas = ListaDeProblemas()
        self.topo = topo
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(14, 12, 14, 12)
        coluna.setSpacing(8)
        coluna.addLayout(topo)
        coluna.addLayout(self.corpo)
        coluna.addWidget(self.problemas)


class ListaDeProblemas(QWidget):
    """Os problemas de uma parte do pedido, um por linha, com o ícone do nível."""

    ICONES = {"erro": ("alerta", "erro"), "aviso": ("alerta", "aviso"), "info": ("ok", "acento")}

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.coluna = QVBoxLayout(self)
        self.coluna.setContentsMargins(0, 0, 0, 0)
        self.coluna.setSpacing(4)
        self.textos: list[str] = []
        self.setVisible(False)

    def definir(self, problemas: Iterable[Problema]) -> None:
        while self.coluna.count():
            item = self.coluna.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.textos = []
        ordem = {"erro": 0, "aviso": 1, "info": 2}
        for p in sorted(problemas, key=lambda p: ordem.get(p.nivel, 3)):
            texto = (traduzir("Canal {}: ").format(p.canal) if p.canal is not None else "") + p.mensagem
            texto = texto[0].upper() + texto[1:] if texto else texto
            linha = QHBoxLayout()
            linha.setSpacing(6)
            icone = RotuloDeIcone(*self.ICONES.get(p.nivel, ("ok", "mudo")), 13)
            rotulo = QLabel(texto)
            rotulo.setObjectName(f"problema_{p.nivel}")
            rotulo.setFont(fonte("secundario"))
            rotulo.setWordWrap(True)
            rotulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            linha.addWidget(icone, 0, Qt.AlignmentFlag.AlignTop)
            linha.addWidget(rotulo, 1)
            caixa = QWidget()
            caixa.setLayout(linha)
            linha.setContentsMargins(0, 0, 0, 0)
            self.coluna.addWidget(caixa)
            self.textos.append(texto)
        self.setVisible(bool(self.textos))


def _ponto(cor: str | None, tamanho: int = 8) -> QPixmap:
    """O ponto colorido do canal (vazio, só o contorno, no desligado)."""
    escala = 2
    pixmap = QPixmap(tamanho * escala, tamanho * escala)
    pixmap.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(pixmap)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    if cor is None:
        pintor.setPen(QColor(aparencia().tema.mudo))
        pintor.setBrush(Qt.BrushStyle.NoBrush)
    else:
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(cor))
    pintor.drawEllipse(1, 1, tamanho * escala - 2, tamanho * escala - 2)
    pintor.end()
    pixmap.setDevicePixelRatio(escala)
    return pixmap


class LinhaDoCanal(QWidget):
    """Um canal do ADC no formulário: ligado ou não, a grandeza, a sonda, a faixa (com o LSB), o ganho e a faixa
    sugerida pela última conferência."""

    mudou = Signal()
    sondaMudou = Signal(str)

    def __init__(self, numero: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.numero = numero
        self.setObjectName(f"canal_{numero}")
        self.ligado = QCheckBox()
        self.ligado.setObjectName("ligar_canal")
        self.ligado.setToolTip(traduzir("Ligar o canal {}").format(numero))
        self.ponto = QLabel()
        self.rotulo = QLabel(str(numero))
        self.rotulo.setFont(fonte("corpo", QFont.Weight.DemiBold))
        self.rotulo.setMinimumWidth(12)
        self.grandeza = QComboBox()
        self.grandeza.setObjectName("grandeza")
        for valor, texto in GRANDEZAS:
            self.grandeza.addItem(traduzir(texto), valor)
        self.sonda = QComboBox()
        self.sonda.setObjectName("sonda")
        self.sonda.setEditable(True)
        self.sonda.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.sonda.lineEdit().setPlaceholderText(traduzir("sem sonda"))
        self.sonda.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sonda.setMinimumContentsLength(10)
        self.faixa = QComboBox()
        self.faixa.setObjectName("faixa")
        for valor, texto in FAIXAS:
            self.faixa.addItem(texto, valor)
        self.lsb = QLabel()
        self.lsb.setObjectName("texto_mudo")
        self.lsb.setFont(fonte("secundario"))
        self.ganho = QLineEdit()
        self.ganho.setObjectName("ganho")
        self.ganho.setPlaceholderText(traduzir("ganho 1"))
        self.ganho.setToolTip(traduzir("Unidades físicas por volt no pino (19,357 no divisor da tensão): vai para o "
                                       "cabeçalho e vira o ganho da análise. Vazio: 1."))
        self.ganho.setMaximumWidth(84)
        self.sugerir = QToolButton()
        self.sugerir.setObjectName("sugerir_faixa")
        self.sugerir.setProperty("variante", "fantasma")
        self.sugerir.setVisible(False)
        self._sugerida: float | None = None

        cima = QHBoxLayout()
        cima.setContentsMargins(0, 0, 0, 0)
        cima.setSpacing(6)
        cima.addWidget(self.ligado)
        cima.addWidget(self.ponto)
        cima.addWidget(self.rotulo)
        cima.addWidget(self.grandeza)
        cima.addWidget(self.sonda, 1)
        self.desligado = QLabel(traduzir("desligado"))
        self.desligado.setObjectName("texto_mudo")
        self.desligado.setFont(fonte("secundario"))
        cima.addWidget(self.desligado, 1)
        self.baixo = QWidget()
        linha = QHBoxLayout(self.baixo)
        linha.setContentsMargins(46, 0, 0, 0)
        linha.setSpacing(6)
        linha.addWidget(self.faixa)
        linha.addWidget(self.lsb)
        linha.addStretch(1)
        linha.addWidget(self.sugerir)
        linha.addWidget(self.ganho)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 2, 0, 4)
        coluna.setSpacing(4)
        coluna.addLayout(cima)
        coluna.addWidget(self.baixo)

        self.ligado.toggled.connect(self._ligado_mudou)
        self.grandeza.currentIndexChanged.connect(lambda _: self.mudou.emit())
        self.sonda.currentTextChanged.connect(self.sondaMudou.emit)
        self.faixa.currentIndexChanged.connect(lambda _: self.mudou.emit())
        self.ganho.textEdited.connect(lambda _: self.mudou.emit())
        self.sugerir.clicked.connect(self._usar_a_sugerida)
        self.definir(None, Canal(numero))

    # ------------------------------------------------------------------ campos <-> canal

    def canal(self) -> Canal | None:
        """O canal dos campos (``None`` desligado)."""
        if not self.ligado.isChecked():
            return None
        texto = self.ganho.text().strip()
        return Canal(self.numero, self.grandeza.currentData(), self.sonda.currentText().strip(),
                     self.faixa.currentData(), _numero(texto) if texto else None)

    def definir(self, ligado: Canal | None, guardado: Canal | None = None) -> None:
        """Põe ``ligado`` nos campos (ou, desligado, o que o canal tinha: ``guardado``), sem avisar."""
        canal = ligado or guardado or Canal(self.numero)
        for w in (self.ligado, self.grandeza, self.sonda, self.faixa, self.ganho):
            w.blockSignals(True)
        try:
            self.ligado.setChecked(ligado is not None)
            i = self.grandeza.findData(canal.grandeza)
            self.grandeza.setCurrentIndex(i if i >= 0 else 0)
            self.sonda.setEditText(canal.sonda)
            i = self.faixa.findData(pd.faixa_conhecida(canal.faixa_v))
            self.faixa.setCurrentIndex(i if i >= 0 else 0)
            self.ganho.setText("" if canal.ganho is None else texto_do_numero(canal.ganho))
        finally:
            for w in (self.ligado, self.grandeza, self.sonda, self.faixa, self.ganho):
                w.blockSignals(False)
        self._mostrar_ligado()

    def definir_perfis(self, ids: Iterable[str]) -> None:
        texto = self.sonda.currentText()
        self.sonda.blockSignals(True)
        try:
            self.sonda.clear()
            self.sonda.addItem("")
            self.sonda.addItems(list(ids))
            self.sonda.setEditText(texto)
        finally:
            self.sonda.blockSignals(False)

    def definir_cor(self, cor: str | None) -> None:
        self.ponto.setPixmap(_ponto(cor))

    def definir_lsb(self) -> None:
        lsb = self.faixa.currentData() / 65536
        self.lsb.setText(traduzir("LSB {}").format(formatar_si(lsb, "V", 4)))

    def sugerir_faixa(self, faixa_v: float | None) -> None:
        """A faixa que a última conferência sugere para o canal (``None``: nenhuma, ou a mesma)."""
        self._sugerida = faixa_v
        mostra = faixa_v is not None and self.ligado.isChecked() and \
            abs(faixa_v - self.faixa.currentData()) >= pd.TOLERANCIA_DA_FAIXA_V
        self.sugerir.setVisible(mostra)
        if faixa_v is not None:
            self.sugerir.setText(traduzir("usar {}").format(texto_da_faixa(faixa_v)))
            self.sugerir.setToolTip(traduzir("A faixa que a última conferência sugere para o sinal deste canal: a menor "
                                             "que o comporta, com 15 % de folga (mais resolução)."))

    def marcar(self, campos: set[str]) -> None:
        """Os campos com um erro ficam marcados."""
        for nome, widget in (("grandeza", self.grandeza), ("sonda", self.sonda), ("faixa", self.faixa),
                             ("ganho", self.ganho)):
            if bool(widget.property("invalido")) != (nome in campos):
                widget.setProperty("invalido", nome in campos)
                repolir(widget)

    def _ligado_mudou(self, _ligado: bool) -> None:
        self._mostrar_ligado()
        self.mudou.emit()

    def _mostrar_ligado(self) -> None:
        ligado = self.ligado.isChecked()
        for w in (self.grandeza, self.sonda):
            w.setVisible(ligado)
        self.desligado.setVisible(not ligado)
        self.baixo.setVisible(ligado)
        self.rotulo.setObjectName("" if ligado else "texto_mudo")
        repolir(self.rotulo)
        self.definir_lsb()
        self.sugerir_faixa(self._sugerida)

    def _usar_a_sugerida(self) -> None:
        if self._sugerida is not None:
            i = self.faixa.findData(pd.faixa_conhecida(self._sugerida))
            if i >= 0:
                self.faixa.setCurrentIndex(i)


class FormularioDeCaptura(QWidget):
    """A coluna "Nova captura" do B2. ``botao_do_modelo``: o seletor de modelos (o menu é da seção)."""

    pedidoMudou = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("formulario_da_captura")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._pedido = PedidoDeCaptura()
        self._perfis: Mapping[str, PerfilDisponivel] = {}
        self._guardados: dict[int, Canal] = {}            # o que cada canal desligado tinha
        self._carregando = False

        rotulo = QLabel(traduzir("NOVA CAPTURA"))
        rotulo.setObjectName("titulo_do_formulario")
        rotulo.setFont(fonte("legenda", QFont.Weight.DemiBold))
        self.botao_do_modelo = QToolButton()
        self.botao_do_modelo.setObjectName("modelo_da_captura")
        self.botao_do_modelo.setProperty("variante", "fantasma")
        self.botao_do_modelo.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.botao_do_modelo.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.botao_do_modelo.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        IconeDoTema(self.botao_do_modelo, "baixo", "texto2", tamanho=12)
        topo = QHBoxLayout()
        topo.setContentsMargins(14, 10, 8, 4)
        topo.addWidget(rotulo)
        topo.addStretch(1)
        topo.addWidget(self.botao_do_modelo)

        self.secoes = {"cabecalho": self._criar_cabecalho(), "canais": self._criar_canais(),
                       "taxa": self._criar_taxa(), "destino": self._criar_destino(),
                       "avancado": self._criar_avancado()}
        conteudo = QWidget()
        conteudo.setObjectName("conteudo_do_formulario")
        coluna = QVBoxLayout(conteudo)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(0)
        for secao in self.secoes.values():
            coluna.addWidget(secao)
        coluna.addStretch(1)
        rolagem = QScrollArea()
        rolagem.setObjectName("rolagem_do_formulario")
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolagem.setWidget(conteudo)
        tudo = QVBoxLayout(self)
        tudo.setContentsMargins(0, 0, 0, 0)
        tudo.setSpacing(0)
        tudo.addLayout(topo)
        tudo.addWidget(rolagem, 1)
        self.setFixedWidth(LARGURA)
        aparencia().mudou.connect(self._tema_mudou)
        self.definir_pedido(self._pedido)

    def _tema_mudou(self, _tema=None) -> None:
        self._mostrar_derivados()

    # ------------------------------------------------------------------ montar

    def _rotulo(self, texto: str) -> QLabel:
        r = QLabel(texto)
        r.setObjectName("rotulo_do_campo")
        r.setFont(fonte("secundario"))
        return r

    def _derivado(self) -> QLabel:
        r = QLabel()
        r.setObjectName("texto_mudo")
        r.setFont(fonte("secundario"))
        r.setWordWrap(True)
        return r

    def _criar_cabecalho(self) -> _Secao:
        secao = _Secao(traduzir("Cabeçalho"))
        self.titulo = QLineEdit()
        self.titulo.setObjectName("titulo")
        self.titulo.setPlaceholderText(traduzir("Rede do bloco E · tarde · V+I"))
        self.contador_do_titulo = self._derivado()
        self.descricao = QPlainTextEdit()
        self.descricao.setObjectName("descricao")
        self.descricao.setPlaceholderText(traduzir("O que está ligado, onde está cada sonda, o que mudou na bancada…"))
        self.descricao.setTabChangesFocus(True)
        self.descricao.setFixedHeight(64)
        self.contador_da_descricao = self._derivado()
        for nome, campo, contador in ((traduzir("Título"), self.titulo, self.contador_do_titulo),
                                      (traduzir("Descrição"), self.descricao, self.contador_da_descricao)):
            linha = QHBoxLayout()
            linha.addWidget(self._rotulo(nome))
            linha.addStretch(1)
            contador.setWordWrap(False)
            linha.addWidget(contador)
            secao.corpo.addLayout(linha)
            secao.corpo.addWidget(campo)
        self.titulo.textEdited.connect(lambda _: self._mudou())
        self.descricao.textChanged.connect(self._mudou)
        return secao

    def _criar_canais(self) -> _Secao:
        secao = _Secao(traduzir("Canais"))
        self.linhas = [LinhaDoCanal(n) for n in range(pd.NUM_CANAIS)]
        for linha in self.linhas:
            linha.mudou.connect(self._mudou)
            linha.sondaMudou.connect(lambda texto, linha=linha: self._sonda_mudou(linha, texto))
            secao.corpo.addWidget(linha)
        nota = self._derivado()
        nota.setText(traduzir("O ADC varre os canais em ordem crescente, e cada um recebe a taxa total dividida pelo "
                              "número de canais."))
        secao.corpo.addWidget(nota)
        return secao

    def _criar_taxa(self) -> _Secao:
        secao = _Secao(traduzir("Taxa e duração"))
        grade = QGridLayout()
        grade.setHorizontalSpacing(8)
        grade.setVerticalSpacing(6)
        self.taxa = CampoComUnidade("S/s", pd.FREQUENCIA_PADRAO_HZ, minimo=1, maximo=pd.FREQUENCIA_MAXIMA_HZ, digitos=6)
        self.taxa.setObjectName("taxa")
        self.taxa.setToolTip(traduzir("A taxa total, em amostras por segundo (400k, 250000)."))
        self.texto_da_taxa = self._derivado()
        grade.addWidget(self._rotulo(traduzir("Taxa total")), 0, 0)
        grade.addWidget(self.taxa, 0, 1)
        grade.addWidget(self.texto_da_taxa, 1, 1)

        self.modo_da_duracao = Segmentado([traduzir(m) for m in MODOS_DA_DURACAO])
        self.duracao = QLineEdit("10")
        self.duracao.setObjectName("duracao")
        self.unidade_da_duracao = QComboBox()
        self.unidade_da_duracao.setObjectName("unidade_da_duracao")
        for texto, multiplicador in UNIDADES_DA_DURACAO:
            self.unidade_da_duracao.addItem(texto, multiplicador)
        self.unidade_da_duracao.setCurrentIndex(1)
        self.blocos = QLineEdit("1")
        self.blocos.setObjectName("blocos")
        self.blocos.setToolTip(traduzir("Blocos de 1 048 576 amostras (2,6 s a 400 kS/s)."))
        campo = QHBoxLayout()
        campo.setSpacing(6)
        campo.addWidget(self.duracao, 1)
        campo.addWidget(self.unidade_da_duracao)
        campo.addWidget(self.blocos, 1)
        self.texto_da_duracao = self._derivado()
        grade.addWidget(self._rotulo(traduzir("Duração")), 2, 0)
        grade.addWidget(self.modo_da_duracao, 2, 1)
        grade.addLayout(campo, 3, 1)
        grade.addWidget(self.texto_da_duracao, 4, 1)
        grade.setColumnStretch(1, 1)
        secao.corpo.addLayout(grade)
        self.teto = self._derivado()
        secao.corpo.addWidget(self.teto)
        self.taxa.valorMudou.connect(lambda _: self._mudou())
        self.modo_da_duracao.escolhaMudou.connect(lambda _: self._mudou())
        self.duracao.textEdited.connect(lambda _: self._mudou())
        self.unidade_da_duracao.currentIndexChanged.connect(lambda _: self._mudou())
        self.blocos.textEdited.connect(lambda _: self._mudou())
        return secao

    def _criar_destino(self) -> _Secao:
        secao = _Secao(traduzir("Destino"))
        self.destino = Segmentado([traduzir("Direto no computador"), traduzir("No cartão da placa")],
                                  icones=["baixar", "disco"])
        self.texto_do_destino = self._derivado()
        self.texto_do_destino.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.arquivo_no_cartao = QLineEdit()
        self.arquivo_no_cartao.setObjectName("arquivo_no_cartao")
        self.arquivo_no_cartao.setPlaceholderText(traduzir("captura_AAAAMMDD_HHMMSS.bin (o nome do ler_adc)"))
        self.rotulo_do_arquivo = self._rotulo(traduzir("Nome no cartão"))
        secao.corpo.addWidget(self.destino)
        secao.corpo.addWidget(self.rotulo_do_arquivo)
        secao.corpo.addWidget(self.arquivo_no_cartao)
        secao.corpo.addWidget(self.texto_do_destino)
        self.destino.escolhaMudou.connect(lambda _: self._mudou())
        self.arquivo_no_cartao.textEdited.connect(lambda _: self._mudou())
        return secao

    def _criar_avancado(self) -> _Secao:
        secao = _Secao("")
        self.abrir_avancado = QToolButton()
        self.abrir_avancado.setObjectName("abrir_avancado")
        self.abrir_avancado.setProperty("variante", "fantasma")
        self.abrir_avancado.setText(traduzir("Avançado"))
        self.abrir_avancado.setCheckable(True)
        self.abrir_avancado.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.abrir_avancado.setFont(fonte("corpo", QFont.Weight.DemiBold))
        self._icone_do_avancado = IconeDoTema(self.abrir_avancado, "direita", "texto2", tamanho=12)
        secao.titulo.setVisible(False)
        secao.topo.insertWidget(0, self.abrir_avancado)
        self.corpo_do_avancado = QWidget()
        corpo = QVBoxLayout(self.corpo_do_avancado)
        corpo.setContentsMargins(0, 0, 0, 0)
        corpo.setSpacing(6)
        self.spi = QComboBox()
        self.spi.setObjectName("spi")
        for valor, texto in MODOS_DO_SPI:
            self.spi.addItem(traduzir(texto), valor)
        corpo.addWidget(self._rotulo(traduzir("SPI")))
        corpo.addWidget(self.spi)
        explicacao = self._derivado()
        explicacao.setText(traduzir("O rápido (~15,4 MHz) lê o bit na fase B, a mesma latência do lento; as fases A e C "
                                    "servem para conferir a janela do bit. O lento (~10,7 MHz) tem o teto mais baixo."))
        corpo.addWidget(explicacao)
        self.atrasos = [QLineEdit(str(a)) for a in pd.ATRASOS_CS_PADRAO]
        linha = QHBoxLayout()
        linha.setSpacing(6)
        for nome, campo in zip((traduzir("setup"), traduzir("hold"), traduzir("CS alto")), self.atrasos):
            campo.setObjectName("atraso_cs")
            campo.setMaximumWidth(64)
            linha.addWidget(self._rotulo(nome))
            linha.addWidget(campo)
            campo.textEdited.connect(lambda _: self._mudou())
        linha.addStretch(1)
        corpo.addWidget(self._rotulo(traduzir("Esperas do CS")))
        corpo.addLayout(linha)
        explicacao = self._derivado()
        explicacao.setText(traduzir("Em passos de 10 ns; o padrão (3, 1, 3) é o mínimo do ADC. Esperas maiores baixam o "
                                    "teto da PRU."))
        corpo.addWidget(explicacao)
        self.forcar_taxa = QCheckBox(traduzir("Aceitar uma taxa acima do teto da PRU"))
        self.forcar_taxa.setObjectName("forcar_taxa")
        self.forcar_taxa.setToolTip(traduzir("Só para varrer o teto: as amostras atrasam, e a taxa real sai menor que "
                                             "a do cabeçalho."))
        corpo.addWidget(self.forcar_taxa)
        secao.corpo.addWidget(self.corpo_do_avancado)
        self.corpo_do_avancado.setVisible(False)
        self.abrir_avancado.toggled.connect(self._abrir_o_avancado)
        self.spi.currentIndexChanged.connect(lambda _: self._mudou())
        self.forcar_taxa.toggled.connect(lambda _: self._mudou())
        return secao

    def _abrir_o_avancado(self, aberto: bool) -> None:
        self.corpo_do_avancado.setVisible(aberto)
        self._icone_do_avancado.trocar("baixo" if aberto else "direita")

    # ------------------------------------------------------------------ o pedido

    @property
    def pedido(self) -> PedidoDeCaptura:
        return self._pedido

    def pedido_dos_campos(self) -> PedidoDeCaptura:
        canais = tuple(c for c in (linha.canal() for linha in self.linhas) if c is not None)
        modo = self.modo_da_duracao.escolhida
        duracao, blocos = None, pd.BLOCOS_PADRAO
        if modo == 0:
            valor = _numero(self.duracao.text())
            duracao = valor * self.unidade_da_duracao.currentData()
        elif modo == 1:
            blocos = _inteiro(self.blocos.text())
        else:
            blocos = 0
        destino = DESTINOS[max(0, self.destino.escolhida)]
        return PedidoDeCaptura(
            canais=canais, taxa_hz=int(round(self.taxa.valor)), duracao_s=duracao, blocos=blocos,
            titulo=self.titulo.text(), descricao=self.descricao.toPlainText(), destino=destino,
            arquivo_no_cartao=self.arquivo_no_cartao.text().strip(), spi=self.spi.currentData(),
            atrasos_cs=tuple(_inteiro(a.text()) for a in self.atrasos), forcar_taxa=self.forcar_taxa.isChecked())

    def definir_pedido(self, pedido: PedidoDeCaptura) -> None:
        """Põe ``pedido`` nos campos (um modelo, o da última vez) e avisa (``pedidoMudou``)."""
        self._carregando = True
        try:
            self.titulo.setText(pedido.titulo)
            self.descricao.setPlainText(pedido.descricao)
            ligados = {c.numero: c for c in pedido.canais}
            for linha in self.linhas:
                linha.definir(ligados.get(linha.numero), self._guardados.get(linha.numero))
            self.taxa.definir_valor(pedido.taxa_hz)
            if pedido.duracao_s is not None:
                self.modo_da_duracao.escolher(0)
                i = unidade_da_duracao(pedido.duracao_s)
                self.unidade_da_duracao.setCurrentIndex(i)
                self.duracao.setText(texto_do_numero(pedido.duracao_s / UNIDADES_DA_DURACAO[i][1]))
            elif pedido.blocos == 0:
                self.modo_da_duracao.escolher(2)
            else:
                self.modo_da_duracao.escolher(1)
                self.blocos.setText(str(pedido.blocos))
            self.destino.escolher(DESTINOS.index(pedido.destino) if pedido.destino in DESTINOS else 0)
            self.arquivo_no_cartao.setText(pedido.arquivo_no_cartao)
            i = self.spi.findData(pedido.spi)
            self.spi.setCurrentIndex(i if i >= 0 else 0)
            for campo, valor in zip(self.atrasos, pedido.atrasos_cs):
                campo.setText(str(valor))
            self.forcar_taxa.setChecked(pedido.forcar_taxa)
        finally:
            self._carregando = False
        self._pedido = pedido
        self._mostrar_derivados()
        self.pedidoMudou.emit(pedido)

    def _mudou(self) -> None:
        if self._carregando:
            return
        for linha in self.linhas:                        # o que um canal desligado tinha
            if not linha.ligado.isChecked():
                continue
            canal = linha.canal()
            if canal is not None:
                self._guardados[linha.numero] = canal
        pedido = self.pedido_dos_campos()
        if pedido == self._pedido:
            self._mostrar_derivados()
            return
        self._pedido = pedido
        self._mostrar_derivados()
        self.pedidoMudou.emit(pedido)

    def _sonda_mudou(self, linha: LinhaDoCanal, texto: str) -> None:
        """Uma sonda escolhida cujo perfil diz o ganho com que foi gerado preenche o ganho vazio do canal."""
        perfil = self._perfis.get(texto.strip())
        if not self._carregando and perfil is not None and perfil.ganho is not None and \
                not linha.ganho.text().strip():
            linha.ganho.setText(texto_do_numero(perfil.ganho))
        self._mudou()

    # ------------------------------------------------------------------ o que vem da seção

    def definir_perfis(self, perfis: Mapping[str, PerfilDisponivel]) -> None:
        self._perfis = dict(perfis)
        for linha in self.linhas:
            linha.definir_perfis(sorted(self._perfis))

    def definir_sugestoes(self, faixas: Mapping[int, float]) -> None:
        """As faixas sugeridas pela última conferência, por canal."""
        for linha in self.linhas:
            linha.sugerir_faixa(faixas.get(linha.numero))

    def definir_texto_do_destino(self, texto: str) -> None:
        self.texto_do_destino.setText(texto)

    def mostrar_problemas(self, problemas: Iterable[Problema]) -> None:
        problemas = list(problemas)
        for nome, secao in self.secoes.items():
            secao.problemas.definir(p for p in problemas if p.campo in CAMPOS_DAS_SECOES[nome])
        erros = {p.campo for p in problemas if p.impede and p.canal is None}
        for linha in self.linhas:
            linha.marcar({p.campo for p in problemas if p.impede and p.canal == linha.numero})
        for campo, widget in (("titulo", self.titulo), ("descricao", self.descricao), ("taxa", self.taxa),
                              ("arquivo", self.arquivo_no_cartao), ("spi", self.spi)):
            if bool(widget.property("invalido")) != (campo in erros):
                widget.setProperty("invalido", campo in erros)
                repolir(widget)
        alvo = self.duracao if self.modo_da_duracao.escolhida == 0 else self.blocos
        for widget in (self.duracao, self.blocos):
            invalido = widget is alvo and "duracao" in erros
            if bool(widget.property("invalido")) != invalido:
                widget.setProperty("invalido", invalido)
                repolir(widget)
        for widget in self.atrasos:
            if bool(widget.property("invalido")) != ("atrasos" in erros):
                widget.setProperty("invalido", "atrasos" in erros)
                repolir(widget)

    # ------------------------------------------------------------------ o que se calcula do pedido

    def _mostrar_derivados(self) -> None:
        p = self._pedido
        for texto, contador, limite in ((p.titulo, self.contador_do_titulo, pd.LIMITE_DO_TITULO),
                                        (p.descricao, self.contador_da_descricao, pd.LIMITE_DA_DESCRICAO)):
            tamanho = len(texto.encode())
            contador.setText(traduzir("{} / {} bytes").format(tamanho, limite))
            contador.setObjectName("problema_erro" if tamanho > limite else "texto_mudo")
            repolir(contador)
        cores = aparencia().tema.tracos
        posicoes = {n: i for i, n in enumerate(p.numeros)}
        for linha in self.linhas:
            i = posicoes.get(linha.numero)
            linha.definir_cor(cores[i % len(cores)] if i is not None else None)
            linha.definir_lsb()
        self.secoes["canais"].lado.setText(traduzir("{} de {}").format(len(p.canais), pd.NUM_CANAIS))

        taxa_ok = 1 <= p.taxa_hz <= pd.FREQUENCIA_MAXIMA_HZ
        if taxa_ok and p.canais:
            self.texto_da_taxa.setText(traduzir("{} por canal · cada canal vai até {}").format(
                formatar_si(p.taxa_por_canal_hz, "S/s", 4), formatar_si(p.nyquist_por_canal_hz, "Hz", 4)))
        else:
            self.texto_da_taxa.setText("")
        modo = self.modo_da_duracao.escolhida
        self.duracao.setVisible(modo == 0)
        self.unidade_da_duracao.setVisible(modo == 0)
        self.blocos.setVisible(modo == 1)
        if taxa_ok and not (p.duracao_s is not None and not (math.isfinite(p.duracao_s) and p.duracao_s > 0)) \
                and p.blocos >= 0:
            if p.ate_parar:
                texto = traduzir("até o Parar · {} por segundo").format(formatar_bytes(p.bytes_por_segundo))
            else:
                texto = traduzir("{} blocos inteiros · {} · {}").format(
                    p.blocos_pedidos, formatar_duracao(p.duracao_real_s), formatar_bytes(p.bytes_do_arquivo))
            self.texto_da_duracao.setText(texto)
        else:
            self.texto_da_duracao.setText("")
        avancado_ok = p.spi in pd.MODOS_SPI and len(p.atrasos_cs) == 3 and \
            all(1 <= a <= pd.ATRASO_CS_MAXIMO for a in p.atrasos_cs)
        if avancado_ok:
            maxima = pd.taxa_maxima_hz(p.spi, p.atrasos_cs)
            spi = traduzir("lento") if p.spi == "lenta" else traduzir("rápido")
            acima = taxa_ok and p.ticks < pd.teto_ticks_da_pru(p.spi, p.atrasos_cs)
            self.teto.setText(traduzir("Teto da PRU: {} com o SPI {}{}").format(
                formatar_si(maxima, "S/s", 6), spi, "" if acima else " ✓"))
        else:
            self.teto.setText("")
        no_cartao = p.destino == "cartao"
        self.rotulo_do_arquivo.setVisible(no_cartao)
        self.arquivo_no_cartao.setVisible(no_cartao)
        spi = dict(MODOS_DO_SPI).get(p.spi, p.spi).split(" (")[0]
        self.secoes["avancado"].lado.setText(traduzir("SPI {} · CS {}").format(
            traduzir(spi), "/".join(str(a) for a in p.atrasos_cs)) + (traduzir(" · forçada") if p.forcar_taxa else ""))
