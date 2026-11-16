"""A seção Arquivos da Aquisição (docs/gui-plan.md, 11.7; a F3.7): as capturas na placa e o caminho delas até a
Análise.

* **A lista:** cada ``.bin`` da pasta do firmware (e das coletas), com o resumo do cabeçalho que o agente lê (o
  título, a taxa, os canais, a duração, a integridade) e onde ela está: só na placa, na fila, baixando, no computador
  (conferida) ou com a cópia corrompida. O título vai embaixo do nome do arquivo, na coluna que fica com a largura que
  sobra (:class:`DelegadoDoArquivo`).
* **As ações da seleção:** transferir (para a pasta da sessão do dia), abrir na Análise (a cópia local), mostrar a
  pasta e **apagar da placa, só o que já foi conferido**, depois de confirmar.
* **As coletas:** as pastas de coleta, com o ``resumo.csv`` de cada uma.
* **A fila:** cada transferência com o progresso, a vazão, o tempo que falta e o que está acontecendo ("esperando a
  captura terminar", "interrompida: retoma quando a placa voltar").
* **Abrir no gerenciador de arquivos:** no Linux, o ``sftp://`` (o Nautilus e o Dolphin falam SFTP); no Windows, o
  SSHFS-Win, se estiver instalado; sem eles, o aviso. No simulador, a pasta dele.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QEvent, QModelIndex, QRect, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QProgressBar,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...componentes.basicos import Botao
from ...componentes.numeros import formatar_bytes, formatar_duracao, formatar_si
from ...componentes.painel import EstadoVazio
from ...componentes.toast import Toast
from ...servicos.conexao_da_placa import ConexaoDaPlaca
from ...servicos.saude_da_placa import SaudeDaPlaca
from ...servicos.transferencias import ATIVOS, ItemDaFila, TransferenciasDaPlaca
from ...tema.aplicar import aparencia
from ...tema.tokens import TAMANHOS
from .pecas import Painel, Selo, fonte
from .textos import frase, texto_da_vazao, traduzir

COLUNAS = ("Arquivo", "Início", "Duração", "Taxa", "Canais", "Tamanho", "Integridade", "No computador")
PAPEL_DO_TITULO = Qt.ItemDataRole.UserRole + 1
ENTRE_AS_LINHAS = 2
"""Os pixels entre o nome do arquivo e o título, na coluna Arquivo."""
FOLGA_DAS_DUAS_LINHAS = 6
"""Os pixels a mais na altura das linhas com título (3 em cima, 3 embaixo)."""
SSHFS_WIN = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "SSHFS-Win" / "bin" / "sshfs.exe"


def estado_no_computador(transferencias: TransferenciasDaPlaca, captura) -> tuple[str, str]:
    """``(texto, nível do selo)`` de onde a captura está: "no computador", "baixando 62 %", "na fila"…"""
    item = transferencias.item_de(captura)
    if item is not None and item.estado in ATIVOS:
        if item.estado == "esperando_a_captura":
            return traduzir("esperando a captura"), "acento"
        if item.estado == "conferindo":
            return traduzir("conferindo"), "acento"
        return traduzir("baixando {} %").format(round(100 * item.fracao)), "acento"
    if item is not None and item.estado == "na_fila":
        return traduzir("na fila"), "acento"
    copia = transferencias.copia(captura)
    if copia is not None and copia.conferida:
        return traduzir("no computador"), "ok"
    if copia is not None and copia.conferida is False:
        return traduzir("cópia corrompida"), "erro"
    if item is not None and item.estado == "interrompida":
        return traduzir("interrompida"), "aviso"
    return traduzir("só na placa"), "aviso"


class DelegadoDoArquivo(QStyledItemDelegate):
    """A coluna Arquivo: o nome e, embaixo, o título da captura em cor de metadado, cortado com "…" na largura da
    coluna (que fica com a largura que as outras deixam, e nunca menos que a dos nomes:
    :meth:`Arquivos._ajustar_a_coluna_do_arquivo`). Numa coluna própria, o título ficava com o que as outras deixavam (40 px numa
    janela de 1 440 px, com o painel das transferências). ``duas_linhas``: alguma captura da tabela tem título, e
    todas as linhas ficam com a altura de duas (a tabela não fica com linhas de alturas diferentes)."""

    duas_linhas = False

    @staticmethod
    def fonte_do_titulo(base: QFont) -> QFont:
        f = QFont(base)
        f.setPixelSize(TAMANHOS["secundario"])
        return f

    def sizeHint(self, opcao: QStyleOptionViewItem, indice: QModelIndex) -> QSize:
        tamanho = super().sizeHint(opcao, indice)
        if not self.duas_linhas:
            return tamanho
        extra = QFontMetrics(self.fonte_do_titulo(opcao.font)).height() + ENTRE_AS_LINHAS + FOLGA_DAS_DUAS_LINHAS
        return QSize(tamanho.width(), tamanho.height() + extra)

    def paint(self, pintor: QPainter, opcao: QStyleOptionViewItem, indice: QModelIndex) -> None:
        titulo = indice.data(PAPEL_DO_TITULO) or ""
        if not titulo:
            super().paint(pintor, opcao, indice)
            return
        o = QStyleOptionViewItem(opcao)
        self.initStyleOption(o, indice)
        nome, o.text = o.text, ""
        estilo = o.widget.style() if o.widget is not None else QApplication.style()
        estilo.drawControl(QStyle.ControlElement.CE_ItemViewItem, o, pintor, o.widget)     # o fundo e a seleção
        r: QRect = estilo.subElementRect(QStyle.SubElement.SE_ItemViewItemText, o, o.widget)
        fonte_do_titulo = self.fonte_do_titulo(o.font)
        m_nome, m_titulo = QFontMetrics(o.font), QFontMetrics(fonte_do_titulo)
        topo = r.top() + (r.height() - m_nome.height() - ENTRE_AS_LINHAS - m_titulo.height()) // 2
        tema = aparencia().tema
        pintor.save()
        pintor.setFont(o.font)
        pintor.setPen(QColor(tema.texto))                   # também na seleção (o fundo dela é um tom do acento)
        pintor.drawText(QRect(r.left(), topo, r.width(), m_nome.height()), int(Qt.AlignmentFlag.AlignLeft),
                        m_nome.elidedText(nome, Qt.TextElideMode.ElideMiddle, r.width()))
        pintor.setFont(fonte_do_titulo)
        pintor.setPen(QColor(tema.mudo))
        pintor.drawText(QRect(r.left(), topo + m_nome.height() + ENTRE_AS_LINHAS, r.width(), m_titulo.height()),
                        int(Qt.AlignmentFlag.AlignLeft), m_titulo.elidedText(titulo, Qt.TextElideMode.ElideRight,
                                                                              r.width()))
        pintor.restore()


def texto_do_item(item: ItemDaFila) -> str:
    """O que a fila diz de um item: "62 % · 5,2 MB/s · faltam 12 s", "conferida (CRC das amostras)"…"""
    if item.estado == "baixando":
        partes = [f"{round(100 * item.fracao)} %", f"{formatar_bytes(item.transferidos)} de {formatar_bytes(item.total)}"]
        if item.vazao_bytes_s:
            partes.append(texto_da_vazao(item.vazao_bytes_s))
        if item.restante_s is not None:
            partes.append(traduzir("faltam {}").format(formatar_duracao(max(1, round(item.restante_s)))))
        return " · ".join(partes)
    textos = {
        "na_fila": traduzir("na fila"),
        "esperando_a_captura": traduzir("esperando a captura terminar: a medição tem prioridade"),
        "conferindo": traduzir("conferindo a cópia"),
        "conferida": traduzir("conferida ({})").format(traduzir("o CRC das amostras") if item.como == "crc32"
                                                       else traduzir("o SHA-256 dos dois lados")),
        "corrompida": frase(item.erro),
        "interrompida": traduzir("interrompida: continua de onde parou quando a placa voltar"),
        "falhou": frase(item.erro),
        "cancelada": traduzir("cancelada (o que já veio fica, para retomar)"),
    }
    return textos.get(item.estado, item.estado)


class LinhaDaFila(QFrame):
    """Um item da fila: o nome, a barra, o texto do estado e o botão que cabe (cancelar, tentar de novo, tirar)."""

    def __init__(self, item: ItemDaFila, transferencias: TransferenciasDaPlaca, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("linha_da_fila")
        self.item, self.transferencias = item, transferencias
        self.nome = QLabel(item.captura.arquivo)
        self.nome.setFont(fonte("corpo", QFont.Weight.DemiBold))
        self.barra = QProgressBar()
        self.barra.setObjectName("barra_de_uso")
        self.barra.setRange(0, 1000)
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(6)
        self.texto = QLabel()
        self.texto.setObjectName("texto_mudo")
        self.texto.setFont(fonte("secundario"))
        self.texto.setWordWrap(True)
        self.acao = Botao("", "fantasma")
        self.acao.setObjectName("acao_da_fila")
        self.acao.clicked.connect(self._agir)
        topo = QHBoxLayout()
        topo.addWidget(self.nome, 1)
        topo.addWidget(self.acao)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(14, 8, 10, 8)
        coluna.setSpacing(4)
        coluna.addLayout(topo)
        coluna.addWidget(self.barra)
        coluna.addWidget(self.texto)
        self.atualizar()

    def atualizar(self) -> None:
        item = self.item
        self.barra.setValue(round(1000 * item.fracao))
        self.barra.setProperty("nivel", "aviso" if item.estado in ("interrompida", "falhou", "corrompida") else "")
        self.barra.style().unpolish(self.barra)
        self.barra.style().polish(self.barra)
        self.barra.setVisible(item.estado not in ("conferida", "cancelada"))
        self.texto.setText(texto_do_item(item))
        if item.estado in ("na_fila", *ATIVOS):
            self.acao.setText(traduzir("Cancelar"))
        elif item.estado in ("interrompida", "falhou", "cancelada", "corrompida"):
            self.acao.setText(traduzir("Tentar de novo"))
        else:
            self.acao.setText(traduzir("Tirar da lista"))

    def _agir(self) -> None:
        item = self.item
        if item.estado in ("na_fila", *ATIVOS):
            self.transferencias.cancelar(item)
        elif item.estado in ("interrompida", "falhou", "cancelada", "corrompida"):
            self.transferencias.tentar_de_novo(item)
        else:
            self.transferencias.remover(item)


class Arquivos(QWidget):
    """A seção Arquivos. ``abrir_na_analise(caminhos)``, ``dialogos_de()`` (onde salvar, as perguntas) e
    ``abrir_url(url)`` (o gerenciador de arquivos; os testes passam um que não abre nada) vêm da janela."""

    def __init__(self, conexao: ConexaoDaPlaca, saude: SaudeDaPlaca, transferencias: TransferenciasDaPlaca, *,
                 abrir_na_analise: Callable[[list[Path]], object] | None = None, dialogos_de=None,
                 abrir_url: Callable[[QUrl], object] = QDesktopServices.openUrl, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("arquivos")
        self.conexao, self.saude, self.transferencias = conexao, saude, transferencias
        self.abrir_na_analise_de, self.dialogos_de, self.abrir_url = abrir_na_analise, dialogos_de, abrir_url
        self._capturas: list = []
        self._linhas_da_fila: dict[int, LinhaDaFila] = {}
        self.paginas = QStackedWidget()
        self.vazio = EstadoVazio(traduzir("Nenhuma placa conectada"),
                                 traduzir("Conecte uma placa para ver as capturas dela, trazê-las para o computador e "
                                          "abri-las na Análise."), icone_nome="pasta", largura_do_texto=440)
        self.paginas.addWidget(self.vazio)
        self.paginas.addWidget(self._criar_conectada())
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.addWidget(self.paginas)
        conexao.mudou.connect(self.atualizar)
        saude.mudou.connect(self.atualizar)
        transferencias.mudou.connect(self.atualizar)
        transferencias.progrediu.connect(self._progrediu)
        self.atualizar()

    # ------------------------------------------------------------------ montar

    def _criar_conectada(self) -> QWidget:
        titulo = QLabel(traduzir("Arquivos"))
        titulo.setFont(fonte("tela", QFont.Weight.DemiBold))
        self.subtitulo = QLabel()
        self.subtitulo.setObjectName("subtitulo_da_secao")
        self.subtitulo.setWordWrap(True)
        self.subtitulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.transferir_novas = Botao(traduzir("Transferir as novas"), "primario", "baixar")
        self.transferir_novas.setObjectName("transferir_novas")
        self.transferir_novas.clicked.connect(self._transferir_novas)
        self.gerenciador = Botao(traduzir("Abrir no gerenciador de arquivos"), "secundario", "pasta")
        self.gerenciador.setObjectName("abrir_no_gerenciador")
        self.gerenciador.clicked.connect(self.abrir_no_gerenciador)
        self.mudar_destino = Botao(traduzir("Mudar o destino…"), "fantasma")
        self.mudar_destino.setObjectName("mudar_destino")
        self.mudar_destino.clicked.connect(self._mudar_destino)
        cabecalho = QHBoxLayout()
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(titulo)
        textos.addWidget(self.subtitulo)
        cabecalho.addLayout(textos, 1)
        for botao in (self.mudar_destino, self.gerenciador, self.transferir_novas):
            cabecalho.addWidget(botao, 0, Qt.AlignmentFlag.AlignTop)

        self.tabela = QTableWidget(0, len(COLUNAS))
        self.tabela.setObjectName("arquivos_da_placa")
        self.tabela.setHorizontalHeaderLabels([traduzir(c) for c in COLUNAS])
        self.tabela.verticalHeader().hide()
        self.tabela.setShowGrid(False)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tabela.setAlternatingRowColors(True)
        cabeca = self.tabela.horizontalHeader()
        cabeca.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for coluna in range(len(COLUNAS)):
            cabeca.setSectionResizeMode(coluna, QHeaderView.ResizeMode.ResizeToContents)
        cabeca.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        cabeca.sectionResized.connect(lambda coluna, _antes, _agora: coluna != 0 and self._ajustar_a_coluna_do_arquivo())
        self.tabela.viewport().installEventFilter(self)
        self.delegado_do_arquivo = DelegadoDoArquivo(self.tabela)
        self.tabela.setItemDelegateForColumn(0, self.delegado_do_arquivo)
        self.tabela.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tabela.itemSelectionChanged.connect(self._selecao_mudou)
        self.tabela.cellDoubleClicked.connect(self._duplo_clique)

        self.transferir = Botao(traduzir("Transferir"), "secundario", "baixar")
        self.transferir.setObjectName("transferir_selecionadas")
        self.transferir.clicked.connect(lambda: self.transferencias.transferir(self.selecionadas()))
        self.abrir = Botao(traduzir("Abrir na Análise"), "secundario", "onda")
        self.abrir.setObjectName("abrir_na_analise")
        self.abrir.clicked.connect(self.abrir_selecionadas)
        self.mostrar = Botao(traduzir("Mostrar a pasta"), "fantasma", "pasta")
        self.mostrar.setObjectName("mostrar_a_pasta")
        self.mostrar.clicked.connect(self._mostrar_a_pasta)
        self.apagar = Botao(traduzir("Apagar da placa…"), "perigo")
        self.apagar.setObjectName("apagar_da_placa")
        self.apagar.clicked.connect(self.apagar_selecionadas)
        acoes = QHBoxLayout()
        acoes.setContentsMargins(0, 0, 0, 0)
        for botao in (self.transferir, self.abrir, self.mostrar):
            acoes.addWidget(botao)
        acoes.addStretch(1)
        acoes.addWidget(self.apagar)

        self.painel_das_coletas = Painel(traduzir("Coletas"))
        self.lista_de_coletas = QListWidget()
        self.lista_de_coletas.setObjectName("lista_de_coletas")
        self.lista_de_coletas.setMaximumWidth(220)
        self.lista_de_coletas.currentRowChanged.connect(self._coleta_escolhida)
        self.resumo_da_coleta = QTableWidget(0, 0)
        self.resumo_da_coleta.setObjectName("resumo_da_coleta")
        self.resumo_da_coleta.verticalHeader().hide()
        self.resumo_da_coleta.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        coletas = QHBoxLayout()
        coletas.setContentsMargins(10, 0, 10, 10)
        coletas.addWidget(self.lista_de_coletas)
        coletas.addWidget(self.resumo_da_coleta, 1)
        self.painel_das_coletas.corpo.addLayout(coletas)

        self.painel_da_fila = Painel(traduzir("Transferências"))
        self.limpar = Botao(traduzir("Limpar as terminadas"), "fantasma")
        self.limpar.setObjectName("limpar_terminadas")
        self.limpar.clicked.connect(self.transferencias.limpar_terminados)
        self.painel_da_fila.lado.addWidget(self.limpar)
        self.linhas_da_fila = QVBoxLayout()
        self.linhas_da_fila.setContentsMargins(0, 0, 0, 0)
        self.linhas_da_fila.setSpacing(0)
        self.sem_fila = QLabel(traduzir("Nada na fila. Com uma captura rodando na placa, a fila espera ela terminar."))
        self.sem_fila.setObjectName("texto_mudo")
        self.sem_fila.setWordWrap(True)
        self.sem_fila.setContentsMargins(14, 4, 14, 12)
        self.painel_da_fila.corpo.addLayout(self.linhas_da_fila)
        self.painel_da_fila.corpo.addWidget(self.sem_fila)
        self.painel_da_fila.corpo.addStretch(1)
        self.painel_da_fila.setMinimumWidth(320)

        esquerda = QWidget()
        coluna = QVBoxLayout(esquerda)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(10)
        coluna.addWidget(self.tabela, 3)
        coluna.addLayout(acoes)
        coluna.addWidget(self.painel_das_coletas, 1)
        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.setChildrenCollapsible(False)
        divisor.addWidget(esquerda)
        divisor.addWidget(self.painel_da_fila)
        divisor.setStretchFactor(0, 3)
        divisor.setStretchFactor(1, 1)
        pagina = QWidget()
        externa = QVBoxLayout(pagina)
        externa.setContentsMargins(24, 20, 24, 20)
        externa.setSpacing(16)
        externa.addLayout(cabecalho)
        externa.addWidget(divisor, 1)
        return pagina

    # ------------------------------------------------------------------ atualizar

    def atualizar(self) -> None:
        if self.conexao.estado not in ("conectada", "reconectando"):
            self.paginas.setCurrentIndex(0)
            return
        self.paginas.setCurrentIndex(1)
        capturas = self.saude.capturas
        self._capturas = sorted(capturas.capturas, key=lambda c: c.inicio, reverse=True) if capturas else []
        so_na_placa = [c for c in self._capturas if not self.transferencias.conferida(c)]
        if capturas is None:
            resumo = traduzir("lendo as capturas da placa…")
        else:
            resumo = traduzir("{} na placa ({}): {} captura(s), {}; {} ainda não no computador.").format(
                capturas.pasta, self.conexao.destino.conta if self.conexao.destino else traduzir("o simulador"),
                len(self._capturas), formatar_bytes(capturas.bytes), len(so_na_placa))
        self.subtitulo.setText(resumo + " " + traduzir("Destino: {}").format(self.transferencias.pasta_de_destino))
        self.transferir_novas.setEnabled(bool(so_na_placa))
        self._preencher_a_tabela()
        self._preencher_as_coletas()
        self._preencher_a_fila()
        self._selecao_mudou()

    def _preencher_a_tabela(self) -> None:
        selecionadas = {c.arquivo for c in self.selecionadas()}
        self.tabela.blockSignals(True)
        self.delegado_do_arquivo.duas_linhas = any(c.titulo for c in self._capturas)
        self.tabela.setRowCount(len(self._capturas))
        for linha, c in enumerate(self._capturas):
            integridade = "; ".join(c.problemas) if c.problemas else traduzir("íntegra")
            valores = [c.arquivo, time.strftime("%d/%m %H:%M", time.localtime(c.inicio)),
                       formatar_duracao(c.duracao_s) if c.duracao_s else "—",
                       formatar_si(c.taxa_hz, "S/s", 3) if c.taxa_hz else "—",
                       ", ".join(str(n) for n in c.canais) or "—", formatar_bytes(c.bytes), integridade]
            for coluna, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                item.setToolTip(valor if coluna != 6 else "\n".join(c.problemas) or integridade)
                if coluna == 0 and c.titulo:
                    item.setData(PAPEL_DO_TITULO, c.titulo)
                    item.setToolTip(f"{c.arquivo}\n{c.titulo}")
                if coluna in (2, 3, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tabela.setItem(linha, coluna, item)
            texto, nivel = estado_no_computador(self.transferencias, c)
            selo = Selo(nivel, texto)
            selo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            copia = self.transferencias.copia(c)
            selo.setToolTip(copia.local if copia is not None else texto)
            self.tabela.setCellWidget(linha, len(COLUNAS) - 1, selo)
        self.tabela.clearSelection()
        for linha, c in enumerate(self._capturas):
            if c.arquivo in selecionadas:
                self.tabela.selectRow(linha)
        self.tabela.blockSignals(False)
        self.tabela.resizeColumnToContents(len(COLUNAS) - 1)
        self._ajustar_a_coluna_do_arquivo()

    def eventFilter(self, objeto, evento) -> bool:
        if objeto is self.tabela.viewport() and evento.type() == QEvent.Type.Resize:
            self._ajustar_a_coluna_do_arquivo()
        return super().eventFilter(objeto, evento)

    def _ajustar_a_coluna_do_arquivo(self) -> None:
        """A coluna Arquivo fica com a largura que as outras deixam, e nunca menos que a dos nomes (a tabela rola de
        lado numa janela estreita, em vez de cortar o nome inteiro)."""
        cabeca = self.tabela.horizontalHeader()
        outras = sum(cabeca.sectionSize(coluna) for coluna in range(1, len(COLUNAS)))
        largura = max(self.tabela.sizeHintForColumn(0), self.tabela.viewport().width() - outras)
        if cabeca.sectionSize(0) != largura:
            cabeca.resizeSection(0, largura)

    def _preencher_as_coletas(self) -> None:
        coletas = self.saude.capturas.coletas if self.saude.capturas is not None else ()
        self.painel_das_coletas.setVisible(bool(coletas))
        atual = self.lista_de_coletas.currentRow()
        self.lista_de_coletas.blockSignals(True)
        self.lista_de_coletas.clear()
        for coleta in coletas:
            self.lista_de_coletas.addItem(coleta.pasta)
        self.lista_de_coletas.blockSignals(False)
        if coletas:
            self.lista_de_coletas.setCurrentRow(min(max(atual, 0), len(coletas) - 1))
            self._coleta_escolhida(self.lista_de_coletas.currentRow())

    def _coleta_escolhida(self, linha: int) -> None:
        coletas = self.saude.capturas.coletas if self.saude.capturas is not None else ()
        if not 0 <= linha < len(coletas):
            return
        dicionarios = coletas[linha].linhas_como_dicts()
        colunas = list(dicionarios[0]) if dicionarios else []
        self.resumo_da_coleta.setColumnCount(len(colunas))
        self.resumo_da_coleta.setHorizontalHeaderLabels(colunas)
        self.resumo_da_coleta.setRowCount(len(dicionarios))
        for i, d in enumerate(dicionarios):
            for j, coluna in enumerate(colunas):
                self.resumo_da_coleta.setItem(i, j, QTableWidgetItem(str(d.get(coluna, ""))))
        self.resumo_da_coleta.resizeColumnsToContents()

    def _preencher_a_fila(self) -> None:
        itens = self.transferencias.itens
        for chave in [k for k in self._linhas_da_fila if k not in {id(i) for i in itens}]:
            linha = self._linhas_da_fila.pop(chave)
            self.linhas_da_fila.removeWidget(linha)
            linha.hide()
            linha.deleteLater()
        for posicao, item in enumerate(itens):
            linha = self._linhas_da_fila.get(id(item))
            if linha is None:
                linha = self._linhas_da_fila[id(item)] = LinhaDaFila(item, self.transferencias)
                self.linhas_da_fila.insertWidget(posicao, linha)
            linha.atualizar()
        self.sem_fila.setVisible(not itens)
        self.limpar.setVisible(any(i.estado in ("conferida", "cancelada") for i in itens))

    def _progrediu(self, item: ItemDaFila) -> None:
        linha = self._linhas_da_fila.get(id(item))
        if linha is not None:
            linha.atualizar()
        for posicao, c in enumerate(self._capturas):
            if c.arquivo == item.captura.arquivo:
                selo = self.tabela.cellWidget(posicao, len(COLUNAS) - 1)
                if isinstance(selo, Selo):
                    texto, nivel = estado_no_computador(self.transferencias, c)
                    selo.definir(nivel, texto)

    # ------------------------------------------------------------------ a seleção

    def selecionadas(self) -> list:
        linhas = sorted({i.row() for i in self.tabela.selectedIndexes()})
        return [self._capturas[linha] for linha in linhas if linha < len(self._capturas)]

    def _selecao_mudou(self) -> None:
        selecionadas = self.selecionadas()
        conferidas = [c for c in selecionadas if self.transferencias.conferida(c)]
        conectada = self.conexao.estado == "conectada"
        self.transferir.setEnabled(conectada and len(conferidas) < len(selecionadas))
        self.abrir.setEnabled(bool(conferidas) and self.abrir_na_analise_de is not None)
        self.mostrar.setEnabled(bool(conferidas))
        self.apagar.setEnabled(conectada and bool(selecionadas) and len(conferidas) == len(selecionadas))
        self.apagar.setToolTip(traduzir("Só o que já está no computador, conferido, pode sair da placa.")
                               if len(conferidas) < len(selecionadas) else "")

    def _duplo_clique(self, linha: int, _coluna: int) -> None:
        captura = self._capturas[linha]
        if self.transferencias.conferida(captura):
            self.abrir_selecionadas([captura])
        else:
            self.transferencias.transferir([captura])

    def _transferir_novas(self) -> None:
        n = self.transferencias.transferir(self._capturas)
        if n:
            Toast.mostrar(self.window(), traduzir("{} captura(s) na fila, para {}.").format(
                n, self.transferencias.pasta_de_destino), "info")

    def abrir_selecionadas(self, capturas=None) -> None:
        caminhos = [Path(self.transferencias.copia(c).local) for c in (capturas or self.selecionadas())
                    if self.transferencias.conferida(c)]
        if caminhos and self.abrir_na_analise_de is not None:
            self.abrir_na_analise_de(caminhos)

    def _mostrar_a_pasta(self) -> None:
        conferidas = [c for c in self.selecionadas() if self.transferencias.conferida(c)]
        if conferidas:
            self.abrir_url(QUrl.fromLocalFile(str(Path(self.transferencias.copia(conferidas[0]).local).parent)))

    def apagar_selecionadas(self) -> None:
        """Apaga da placa as selecionadas, todas conferidas, depois de o usuário confirmar."""
        selecionadas = self.selecionadas()
        if not selecionadas or not all(self.transferencias.conferida(c) for c in selecionadas) \
                or self.dialogos_de is None:
            return
        nomes = ", ".join(c.arquivo for c in selecionadas[:5]) + ("…" if len(selecionadas) > 5 else "")
        texto = traduzir("{} captura(s) ({}) saem da placa: {}. As cópias no computador estão conferidas. Isto não se "
                         "desfaz.").format(len(selecionadas), formatar_bytes(sum(c.bytes for c in selecionadas)), nomes)
        resposta = self.dialogos_de().perguntar(traduzir("Apagar da placa"), texto,
                                                {"apagar": traduzir("Apagar da placa")}, "apagar")
        if resposta == "apagar":
            self.transferencias.apagar_da_placa(selecionadas)

    def _mudar_destino(self) -> None:
        if self.dialogos_de is None:
            return
        pasta = self.dialogos_de().escolher_pasta(traduzir("Para onde vêm as capturas"),
                                                  str(self.transferencias.pasta_de_destino))
        if pasta is not None:
            self.transferencias.destino = pasta
            self.atualizar()

    # ------------------------------------------------------------------ o gerenciador de arquivos

    def abrir_no_gerenciador(self) -> None:
        """A pasta do firmware da placa no gerenciador de arquivos do sistema (ver o módulo)."""
        capturas = self.saude.capturas
        if capturas is None:
            return
        if self.conexao.simulada:
            self.abrir_url(QUrl.fromLocalFile(capturas.pasta))
            return
        destino = self.conexao.destino
        if destino is None:
            return
        if destino.salto is not None:
            Toast.mostrar(self.window(), traduzir("Pelo salto, o gerenciador de arquivos não chega à placa: use a lista "
                                                  "daqui, ou o terminal."), "aviso")
            return
        if sys.platform == "win32":
            self._abrir_no_windows(destino, capturas.pasta)
            return
        if sys.platform == "darwin":
            Toast.mostrar(self.window(), traduzir("O Finder não fala SFTP: use a lista daqui."), "aviso")
            return
        url = QUrl()
        url.setScheme("sftp")
        url.setUserName(destino.usuario)
        url.setHost(destino.host)
        if destino.porta != 22:
            url.setPort(destino.porta)
        url.setPath(capturas.pasta)
        self.abrir_url(url)

    def _abrir_no_windows(self, destino, pasta: str) -> None:
        if not SSHFS_WIN.exists() and shutil.which("sshfs") is None:
            Toast.mostrar(self.window(), traduzir("O Explorer não fala SFTP. Com o SSHFS-Win (e o WinFsp) instalado, "
                                                  "este botão abre a pasta da placa nele."), "aviso")
            return
        relativo = str(PurePosixPath(pasta).relative_to(f"/home/{destino.usuario}")) \
            if pasta.startswith(f"/home/{destino.usuario}/") else ""
        unc = rf"\\sshfs\{destino.usuario}@{destino.host}!{destino.porta}" + (rf"\{relativo}" if relativo else "")
        self.abrir_url(QUrl.fromLocalFile(unc))
