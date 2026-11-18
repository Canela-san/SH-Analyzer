"""A seção Rotinas da Aquisição (a F4.6; docs/gui-plan.md, 11.5): os modos do ``coletar.sh`` (``sh_placa/rotinas.py``)
num formulário, a linha de comando pronta e o "Rodar no terminal".

* **A lista** à esquerda: os modos, na ordem da ajuda do script, com "pede a bancada" nos que param ("ligue o gerador
  e tecle Enter").
* **O formulário** do modo escolhido: as opções principais. Vazio é o padrão do script (o de uma boa análise). Na
  primeira vez, o que é a bancada (os canais, o canal da sonda, a grandeza, a sonda, a taxa, a faixa, o SPI) vem do
  pedido da Capturar; "Do pedido" refaz isso. Cada modo guarda os valores dele enquanto o aplicativo está aberto.
* **As outras opções:** o texto vai como o shell o lê; a ajuda do modo (lida da placa, a do script que vai rodar)
  mostra todas.
* **Rodar:** uma aba nova do terminal, com o nome do modo, roda a linha (``cd ~/firmware && ./coletar.sh ...``). As
  pausas, o ``sudo`` e as respostas ficam na aba, gravadas no arquivo do dia dela; o caderno ganha uma entrada.
  "Simular" acrescenta o ``--simular`` (o plano, o tempo e o espaço, sem capturar) e "Continuar a última", o
  ``--continuar``. A placa simulada não tem terminal: a linha fica pronta para copiar.
"""

from __future__ import annotations

import functools
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from sh_placa import rotinas as rt
from sh_placa.agente import PASTA_DO_FIRMWARE
from sh_placa.pedido import ErroDeUso, PedidoDeCaptura
from shiboken6 import isValid

from ...componentes.basicos import Botao
from ...servicos.conexao_da_placa import ConexaoDaPlaca
from ...tema.fontes import fonte_mono
from ...tema.tokens import TAMANHOS
from .pecas import BlocoDeComando, Painel, Selo, fonte
from .textos import frase, traduzir

LARGURA_DA_LISTA = 260
LARGURA_MAXIMA = 760


class FormularioDaRotina(QWidget):
    """Os campos de um modo: um por opção da tabela (o texto, a escolha com o "padrão do script" primeiro, a marca),
    com a ajuda embaixo, e as outras opções. ``mudou`` a cada tecla."""

    mudou = Signal()

    def __init__(self, rotina: rt.Rotina, parent: QWidget | None = None):
        super().__init__(parent)
        self.rotina = rotina
        self.campos: dict[str, QWidget] = {}
        grade = QGridLayout(self)
        grade.setContentsMargins(14, 4, 14, 14)
        grade.setHorizontalSpacing(12)
        grade.setVerticalSpacing(2)
        grade.setColumnStretch(1, 1)
        linha = 0
        for o in rotina.opcoes:
            campo = self._criar(o)
            campo.setObjectName(f"opcao{o.flag}")
            campo.setToolTip(f"{o.flag}: {o.ajuda}")
            self.campos[o.flag] = campo
            if o.tipo != "marca":
                rotulo = QLabel(o.rotulo)
                rotulo.setBuddy(campo)
                grade.addWidget(rotulo, linha, 0)
            grade.addWidget(campo, linha, 1)
            ajuda = QLabel(f"{o.flag} · {o.ajuda}")
            ajuda.setObjectName("ajuda_da_opcao")
            ajuda.setFont(fonte("legenda"))
            ajuda.setWordWrap(True)
            grade.addWidget(ajuda, linha + 1, 1)
            grade.setRowMinimumHeight(linha + 2, 8)
            linha += 3
        self.outras = QLineEdit()
        self.outras.setObjectName("outras_opcoes")
        self.outras.setPlaceholderText(traduzir("ex.: --espiras 3 (a ajuda do modo tem todas)"))
        self.outras.textChanged.connect(self.mudou)
        grade.addWidget(QLabel(traduzir("Outras opções")), linha, 0)
        grade.addWidget(self.outras, linha, 1)

    def _criar(self, o: rt.Opcao) -> QWidget:
        if o.tipo == "marca":
            campo = QCheckBox(o.rotulo)
            campo.toggled.connect(self.mudou)
        elif o.tipo == "escolha":
            campo = QComboBox()
            campo.addItem(traduzir("padrão do script"), "")
            for escolha in o.escolhas:
                campo.addItem(escolha, escolha)
            campo.currentIndexChanged.connect(self.mudou)
        else:
            campo = QLineEdit()
            campo.setPlaceholderText(traduzir("padrão do script"))
            campo.textChanged.connect(self.mudou)
        return campo

    def valores(self) -> dict[str, str]:
        valores = {}
        for flag, campo in self.campos.items():
            if isinstance(campo, QCheckBox):
                valores[flag] = "sim" if campo.isChecked() else ""
            elif isinstance(campo, QComboBox):
                valores[flag] = campo.currentData() or ""
            else:
                valores[flag] = campo.text().strip()
        return valores

    def definir(self, valores: dict[str, str]) -> None:
        """Põe ``valores`` nos campos que eles nomeiam (os outros ficam como estão)."""
        for flag, valor in valores.items():
            campo = self.campos.get(flag)
            if isinstance(campo, QCheckBox):
                campo.setChecked(bool(valor))
            elif isinstance(campo, QComboBox):
                i = campo.findData(valor)
                campo.setCurrentIndex(max(0, i))
            elif isinstance(campo, QLineEdit):
                campo.setText(valor)


class ItemDaRotina(QWidget):
    """Uma linha da lista: o título, o modo e "pede a bancada"."""

    def __init__(self, rotina: rt.Rotina, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        titulo = QLabel(traduzir(rotina.titulo))
        titulo.setObjectName("titulo_da_rotina")
        titulo.setFont(fonte("corpo", QFont.Weight.DemiBold))
        modo = QLabel(f"coletar.sh {rotina.modo}")
        modo.setObjectName("modo_da_rotina")
        modo.setFont(fonte_mono(TAMANHOS["legenda"]))
        linha = QHBoxLayout()
        linha.setSpacing(6)
        linha.addWidget(modo)
        linha.addStretch(1)
        if rotina.pausas:
            linha.addWidget(Selo("info", traduzir("pede a bancada")))
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(10, 7, 8, 7)
        coluna.setSpacing(2)
        coluna.addWidget(titulo)
        coluna.addLayout(linha)


class Rotinas(QWidget):
    """A seção "Rotinas". ``pedido_atual()`` dá o pedido da Capturar; ``rodar_no_terminal(comando, rotulo)`` abre a
    aba (``False``: não abriu). ``rotinaIniciada(rotina, comando)`` vai para o caderno."""

    rotinaIniciada = Signal(object, str)

    def __init__(self, conexao: ConexaoDaPlaca, *, pedido_atual: Callable[[], PedidoDeCaptura] | None = None,
                 rodar_no_terminal: Callable[[str, str], bool] | None = None,
                 pasta_firmware: str = PASTA_DO_FIRMWARE, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("rotinas")
        self.conexao, self.pasta_firmware = conexao, pasta_firmware
        self.pedido_atual = pedido_atual or PedidoDeCaptura
        self.rodar_no_terminal = rodar_no_terminal
        self.formularios: dict[str, FormularioDaRotina] = {}
        self._ajudas: dict[tuple[int, str], str] = {}        # (a conexão, o modo) -> a ajuda lida da placa
        self._lendo: set[tuple[int, str]] = set()

        self.lista = QListWidget()
        self.lista.setObjectName("lista_de_rotinas")
        self.lista.setFixedWidth(LARGURA_DA_LISTA)
        for r in rt.ROTINAS:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, r.modo)
            item.setToolTip(traduzir(r.resumo))
            widget = ItemDaRotina(r)
            item.setSizeHint(widget.sizeHint())
            self.lista.addItem(item)
            self.lista.setItemWidget(item, widget)
        self.lista.currentRowChanged.connect(self._escolhida)

        self.titulo = QLabel()
        self.titulo.setFont(fonte("tela", QFont.Weight.DemiBold))
        self.resumo = QLabel()
        self.resumo.setObjectName("subtitulo_da_secao")
        self.resumo.setWordWrap(True)
        self.do_pedido = Botao(traduzir("Do pedido"), "secundario", "desfazer")
        self.do_pedido.setObjectName("rotina_do_pedido")
        self.do_pedido.setToolTip(traduzir("Os canais, a grandeza, a sonda, a taxa e a faixa de novo pelo pedido da "
                                           "Capturar"))
        self.do_pedido.clicked.connect(self.preencher_do_pedido)
        cabecalho = QHBoxLayout()
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(self.titulo)
        textos.addWidget(self.resumo)
        cabecalho.addLayout(textos, 1)
        cabecalho.addWidget(self.do_pedido, 0, Qt.AlignmentFlag.AlignTop)

        self.opcoes = Painel(traduzir("Opções"))      # só o formulário do modo escolhido (a altura é a dele)
        self._visivel: FormularioDaRotina | None = None

        self.linha = BlocoDeComando()
        self.erro = QLabel()
        self.erro.setObjectName("problema_erro")
        self.erro.setWordWrap(True)
        self.estado = QLabel()
        self.estado.setObjectName("subtitulo_da_secao")
        self.estado.setWordWrap(True)
        self.rodar = Botao(traduzir("Rodar no terminal"), "primario", "terminal")
        self.rodar.setObjectName("rodar_rotina")
        self.rodar.clicked.connect(lambda: self.iniciar())
        self.simular = Botao(traduzir("Simular"), "secundario", "olho")
        self.simular.setObjectName("simular_rotina")
        self.simular.setToolTip(traduzir("Com --simular: o plano, o tempo e o espaço, sem capturar"))
        self.simular.clicked.connect(lambda: self.iniciar(simular=True))
        self.continuar = Botao(traduzir("Continuar a última"), "secundario", "play")
        self.continuar.setObjectName("continuar_rotina")
        self.continuar.setToolTip(traduzir("Com --continuar: a última coleta deste modo, de onde parou"))
        self.continuar.clicked.connect(lambda: self.iniciar(continuar=True))
        self.ver_ajuda = Botao(traduzir("Ajuda do modo"), "secundario", "livro")
        self.ver_ajuda.setObjectName("ajuda_da_rotina")
        self.ver_ajuda.setCheckable(True)
        self.ver_ajuda.setToolTip(traduzir("A ajuda do coletar.sh da placa: todas as opções do modo"))
        self.ver_ajuda.toggled.connect(self._ajuda_pedida)
        botoes = QHBoxLayout()
        botoes.setSpacing(8)
        for b in (self.rodar, self.simular, self.continuar):
            botoes.addWidget(b)
        botoes.addStretch(1)
        botoes.addWidget(self.ver_ajuda)
        self.ajuda = QPlainTextEdit()
        self.ajuda.setObjectName("ajuda_do_modo")
        self.ajuda.setReadOnly(True)
        self.ajuda.setFont(fonte_mono(TAMANHOS["secundario"]))
        self.ajuda.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.ajuda.setMinimumHeight(260)
        self.ajuda.hide()

        conteudo = QWidget()
        conteudo.setObjectName("conteudo_das_rotinas")
        conteudo.setMaximumWidth(LARGURA_MAXIMA)
        coluna = QVBoxLayout(conteudo)
        coluna.setContentsMargins(24, 20, 24, 20)
        coluna.setSpacing(12)
        coluna.addLayout(cabecalho)
        coluna.addWidget(self.opcoes)
        coluna.addWidget(self.linha)
        coluna.addWidget(self.erro)
        coluna.addLayout(botoes)
        coluna.addWidget(self.estado)
        coluna.addWidget(self.ajuda)
        coluna.addStretch(1)
        centro = QWidget()
        centro.setObjectName("conteudo_das_rotinas")
        meio = QHBoxLayout(centro)
        meio.setContentsMargins(0, 0, 0, 0)
        meio.addWidget(conteudo, 1)
        meio.addStretch(0)
        rolagem = QScrollArea()
        rolagem.setObjectName("rolagem_das_rotinas")
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        rolagem.setWidget(centro)
        esquerda = QVBoxLayout()
        esquerda.setContentsMargins(12, 20, 0, 12)
        esquerda.addWidget(self.lista)
        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(0)
        linha.addLayout(esquerda)
        linha.addWidget(rolagem, 1)
        conexao.mudou.connect(self.atualizar)
        self.lista.setCurrentRow(0)

    # ------------------------------------------------------------------ o modo e os valores

    @property
    def rotina(self) -> rt.Rotina:
        return rt.ROTINAS[max(0, self.lista.currentRow())]

    @property
    def formulario(self) -> FormularioDaRotina:
        return self.formularios[self.rotina.modo]

    def escolher(self, modo: str) -> None:
        self.lista.setCurrentRow([r.modo for r in rt.ROTINAS].index(modo))

    def _escolhida(self, _linha: int) -> None:
        r = self.rotina
        if r.modo not in self.formularios:              # a primeira vez: a bancada vem do pedido da Capturar
            formulario = FormularioDaRotina(r, self.opcoes)
            formulario.hide()
            formulario.definir(rt.valores_do_pedido(r, self.pedido_atual()))
            formulario.mudou.connect(self.atualizar)
            self.formularios[r.modo] = formulario
        if self._visivel is not None:
            self.opcoes.corpo.removeWidget(self._visivel)
            self._visivel.hide()
        self._visivel = self.formulario
        self.opcoes.corpo.addWidget(self._visivel)
        self._visivel.show()
        self.titulo.setText(traduzir(r.titulo))
        self.resumo.setText(traduzir(r.resumo))
        self.simular.setVisible(r.simulavel)
        self.continuar.setVisible(r.retomavel)
        if self.ver_ajuda.isChecked():
            self._mostrar_ajuda()
        self.atualizar()

    def preencher_do_pedido(self) -> None:
        self.formulario.definir(rt.valores_do_pedido(self.rotina, self.pedido_atual()))

    def comando(self, *, simular: bool = False, continuar: bool = False) -> str:
        """A linha do terminal do modo escolhido (:class:`ErroDeUso` se um valor não serve)."""
        f = self.formulario
        return rt.comando(self.rotina, f.valores(), outras=f.outras.text(), simular=simular, continuar=continuar,
                          pasta_firmware=self.pasta_firmware)

    # ------------------------------------------------------------------ o estado e o rodar

    def _pode_rodar(self) -> bool:
        c = self.conexao
        return (c.estado == "conectada" and c.conexao_ssh is not None and not c.simulada
                and self.rodar_no_terminal is not None)

    def atualizar(self) -> None:
        if not isValid(self) or not self.formularios:
            return
        try:
            linha, erro = self.comando(), ""
        except ErroDeUso as e:
            linha, erro = "", str(e)
        self.linha.definir(linha or "—")
        self.erro.setText(erro)
        self.erro.setVisible(bool(erro))
        c = self.conexao
        pode = self._pode_rodar() and not erro
        for botao in (self.rodar, self.simular, self.continuar):
            botao.setEnabled(pode)
        self.ver_ajuda.setEnabled(c.estado == "conectada" and c.conexao_ssh is not None)
        if c.estado != "conectada":
            texto = traduzir("Conecte uma placa para rodar a rotina: a linha fica pronta para copiar.")
        elif c.simulada:
            texto = traduzir("A placa simulada não tem terminal: a linha fica pronta para copiar.")
        elif self.rotina.pausas:
            texto = traduzir("Roda numa aba nova do Terminal. O script para e pede a bancada: o Enter é seu, lá.")
        else:
            texto = traduzir("Roda numa aba nova do Terminal, com a saída gravada no arquivo do dia.")
        self.estado.setText(texto)

    def iniciar(self, *, simular: bool = False, continuar: bool = False) -> bool:
        """Roda o modo escolhido numa aba nova do terminal (``False``: um valor não serve, ou a aba não abriu)."""
        if not self._pode_rodar():
            return False
        try:
            linha = self.comando(simular=simular, continuar=continuar)
        except ErroDeUso as e:
            self.erro.setText(str(e))
            self.erro.show()
            return False
        if not self.rodar_no_terminal(linha, self.rotina.modo):
            return False
        self.rotinaIniciada.emit(self.rotina, linha)
        return True

    # ------------------------------------------------------------------ a ajuda do modo, a da placa

    def _ajuda_pedida(self, ligada: bool) -> None:
        self.ajuda.setVisible(ligada)
        if ligada:
            self._mostrar_ajuda()

    def _mostrar_ajuda(self) -> None:
        ssh = self.conexao.conexao_ssh
        if ssh is None:
            self.ajuda.setPlainText(traduzir("Sem placa conectada."))
            return
        chave = (id(ssh), self.rotina.modo)
        if chave in self._ajudas:
            self.ajuda.setPlainText(self._ajudas[chave])
            return
        self.ajuda.setPlainText(traduzir("Lendo a ajuda do coletar.sh da placa…"))
        if chave in self._lendo:
            return
        self._lendo.add(chave)
        linha = rt.ajuda(self.rotina, self.pasta_firmware)
        self.conexao.servico.chamar(traduzir("ler a ajuda do coletar.sh"),
                                    functools.partial(ssh.executar, linha, descricao="a ajuda do coletar.sh"),
                                    ao_terminar=lambda chamada, k=chave: self._ajuda_chegou(k, chamada))

    def _ajuda_chegou(self, chave: tuple[int, str], chamada) -> None:
        self._lendo.discard(chave)
        if not isValid(self):
            return
        r = chamada.resultado if chamada.estado == "concluida" else None
        if r is not None and r.codigo == 0:
            texto = self._ajudas[chave] = r.saida
        elif r is not None:
            texto = traduzir("A ajuda não veio (código {}): {}").format(r.codigo, r.erro.strip() or "—")
        else:
            texto = traduzir("A ajuda não veio: {}").format(frase(chamada.erro or traduzir("a conexão caiu")))
        if chave == (id(self.conexao.conexao_ssh), self.rotina.modo):
            self.ajuda.setPlainText(texto)
