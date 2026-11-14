"""O painel do projeto (docs/gui-plan.md, 9.1; o mockup A1): a árvore das fontes com os seus canais e das vistas.

* **O modelo** (:class:`ArvoreDoProjeto`) espelha o projeto e segue os sinais dele com inserções e remoções de linha
  (``beginInsertRows``...): a árvore não fecha nem perde a seleção quando algo muda.
* **O ponto colorido** de cada canal mostra em que cor ele está plotado (um ponto por traço, em qualquer vista); um
  círculo vazado, que ainda não está.
* **O delegado** (:class:`DelegadoDaArvore`) desenha cada linha com o tema: o ícone, o nome e, à direita, o detalhe
  (a taxa e a duração da captura, a grandeza do canal) e o estado (a integridade conferida, a pirâmide em
  construção).
* **O painel** (:class:`PainelDoProjeto`) junta o filtro, a árvore e o estado vazio. Um duplo clique num canal pede
  para plotá-lo (``canalAtivado``); um clique numa vista abre a aba dela (``vistaAtivada``: outro jeito de trocar de
  vista).
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QRectF, QSize, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLineEdit,
    QMenu,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ...componentes.numeros import formatar_duracao, formatar_si
from ...componentes.painel import EstadoVazio
from ...modelo.objetos import FonteDoProjeto, Projeto, Traco, Vista
from ...tema.aplicar import aparencia
from ...tema.icones import IconeDoTema, icone
from ...tema.tokens import TAMANHOS, Tema, cor_do_traco

PAPEL_TIPO = Qt.ItemDataRole.UserRole + 1         # "grupo", "fonte", "canal" ou "vista"
PAPEL_OBJETO = Qt.ItemDataRole.UserRole + 2       # a FonteDoProjeto, a Vista ou (fonte, número do canal)
PAPEL_DETALHE = Qt.ItemDataRole.UserRole + 3      # o texto discreto à direita
PAPEL_CORES = Qt.ItemDataRole.UserRole + 4        # as posições na paleta dos traços do canal
ALTURA_DA_LINHA = 26
_RAIZ = QModelIndex()          # o índice inválido (a raiz), como padrão dos argumentos


class _No:
    __slots__ = ("tipo", "objeto", "pai", "filhos")

    def __init__(self, tipo: str, objeto, pai: _No | None):
        self.tipo, self.objeto, self.pai, self.filhos = tipo, objeto, pai, []

    def linha(self) -> int:
        return self.pai.filhos.index(self)


def _meta_da_fonte(fonte: FonteDoProjeto) -> str:
    if fonte.esta_ausente:
        return "ausente"
    canais = fonte.canais
    if not canais:
        return "sem canais"
    taxa = canais[0].taxa_hz * len(canais)
    return f"{formatar_si(taxa, 'S/s', 3)} · {len(canais)} {'canal' if len(canais) == 1 else 'canais'} · " \
           f"{formatar_duracao(canais[0].duracao_s)}"


class ArvoreDoProjeto(QAbstractItemModel):
    """As fontes (com os canais) e as vistas de ``projeto``, em dois grupos."""

    GRUPOS = ("Fontes", "Vistas")

    def __init__(self, projeto: Projeto, parent=None):
        super().__init__(parent)
        self.projeto = projeto
        self._raiz = _No("raiz", None, None)
        self._fontes = _No("grupo", "Fontes", self._raiz)
        self._vistas = _No("grupo", "Vistas", self._raiz)
        self._raiz.filhos = [self._fontes, self._vistas]
        for fonte in projeto.fontes:
            self._fontes.filhos.append(self._no_da_fonte(fonte))
        for vista in projeto.vistas:
            self._vistas.filhos.append(_No("vista", vista, self._vistas))
        projeto.fonteEntrou.connect(self._fonte_entrou)
        projeto.fonteSaiu.connect(self._fonte_saiu)
        projeto.vistaEntrou.connect(self._vista_entrou)
        projeto.vistaSaiu.connect(self._vista_saiu)
        projeto.vistaMudou.connect(self._vista_mudou)
        projeto.tracoEntrou.connect(self._traco_entrou_ou_saiu)
        projeto.tracoSaiu.connect(self._traco_entrou_ou_saiu)
        projeto.tracoMudou.connect(self._traco_mudou)

    # ------------------------------------------------------------------ estrutura

    def _no_da_fonte(self, fonte: FonteDoProjeto) -> _No:
        no = _No("fonte", fonte, self._fontes)
        no.filhos = [_No("canal", (fonte, c.numero), no) for c in fonte.canais]
        fonte.estadoMudou.connect(self._fonte_mudou)
        return no

    def index(self, linha: int, coluna: int, pai: QModelIndex = _RAIZ) -> QModelIndex:
        no_pai = pai.internalPointer() if pai.isValid() else self._raiz
        if coluna != 0 or not 0 <= linha < len(no_pai.filhos):
            return QModelIndex()
        return self.createIndex(linha, 0, no_pai.filhos[linha])

    def parent(self, indice: QModelIndex = _RAIZ) -> QModelIndex:
        if not indice.isValid():
            return QModelIndex()
        pai = indice.internalPointer().pai
        if pai is None or pai is self._raiz:
            return QModelIndex()
        return self.createIndex(pai.linha(), 0, pai)

    def rowCount(self, pai: QModelIndex = _RAIZ) -> int:
        if pai.isValid() and pai.column() != 0:
            return 0
        return len((pai.internalPointer() if pai.isValid() else self._raiz).filhos)

    def columnCount(self, pai: QModelIndex = _RAIZ) -> int:
        return 1

    def _indice(self, no: _No) -> QModelIndex:
        return self.createIndex(no.linha(), 0, no) if no.pai is not None else QModelIndex()

    def indice_da_fonte(self, fonte: FonteDoProjeto) -> QModelIndex:
        for no in self._fontes.filhos:
            if no.objeto is fonte:
                return self._indice(no)
        return QModelIndex()

    def indice_do_canal(self, fonte: FonteDoProjeto, numero: int) -> QModelIndex:
        pai = self.indice_da_fonte(fonte)
        if pai.isValid():
            for no in pai.internalPointer().filhos:
                if no.objeto[1] == numero:
                    return self._indice(no)
        return QModelIndex()

    def indice_da_vista(self, vista: Vista) -> QModelIndex:
        for no in self._vistas.filhos:
            if no.objeto is vista:
                return self._indice(no)
        return QModelIndex()

    # ------------------------------------------------------------------ dados

    def flags(self, indice: QModelIndex) -> Qt.ItemFlag:
        if not indice.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, indice: QModelIndex, papel: int = Qt.ItemDataRole.DisplayRole):
        if not indice.isValid():
            return None
        no: _No = indice.internalPointer()
        if papel == PAPEL_TIPO:
            return no.tipo
        if papel == PAPEL_OBJETO:
            return no.objeto
        if no.tipo == "grupo":
            return {Qt.ItemDataRole.DisplayRole: no.objeto,
                    PAPEL_DETALHE: str(len(no.filhos)) if no.filhos else ""}.get(papel)
        if no.tipo == "fonte":
            fonte: FonteDoProjeto = no.objeto
            if papel == Qt.ItemDataRole.DisplayRole:
                return fonte.nome
            if papel == PAPEL_DETALHE:
                return _meta_da_fonte(fonte)
            if papel == Qt.ItemDataRole.ToolTipRole:
                return f"{fonte.caminho}\n{_meta_da_fonte(fonte)}"
            return None
        if no.tipo == "canal":
            fonte, numero = no.objeto
            canal = fonte.canal(numero)
            if papel == Qt.ItemDataRole.DisplayRole:
                return f"canal {numero}"
            if papel == PAPEL_DETALHE:
                return canal.nome_grandeza + (f" · {canal.sonda_id}" if canal.sonda_id else "")
            if papel == PAPEL_CORES:
                return self.projeto.cores_do_canal(fonte.id, numero)
            if papel == Qt.ItemDataRole.ToolTipRole:
                return f"{fonte.nome}, canal {numero}: {canal.nome_grandeza}, {formatar_si(canal.taxa_hz, 'S/s')}. " \
                       f"Duplo clique plota na vista ativa."
            return None
        vista: Vista = no.objeto
        if papel == Qt.ItemDataRole.DisplayRole:
            return vista.nome
        if papel == PAPEL_DETALHE:
            n = len(vista.tracos)
            return f"{n} {'traço' if n == 1 else 'traços'}"
        if papel == Qt.ItemDataRole.ToolTipRole:
            return f"{vista.nome}: um clique abre a aba dela."
        return None

    # ------------------------------------------------------------------ o projeto mudou

    def _fonte_entrou(self, fonte: FonteDoProjeto, i: int) -> None:
        self.beginInsertRows(self._indice(self._fontes), i, i)
        self._fontes.filhos.insert(i, self._no_da_fonte(fonte))
        self.endInsertRows()
        self._mudou(self._fontes)

    def _fonte_saiu(self, fonte: FonteDoProjeto, i: int) -> None:
        self.beginRemoveRows(self._indice(self._fontes), i, i)
        del self._fontes.filhos[i]
        self.endRemoveRows()
        fonte.estadoMudou.disconnect(self._fonte_mudou)
        self._mudou(self._fontes)

    def _vista_entrou(self, vista: Vista, i: int) -> None:
        self.beginInsertRows(self._indice(self._vistas), i, i)
        self._vistas.filhos.insert(i, _No("vista", vista, self._vistas))
        self.endInsertRows()
        self._mudou(self._vistas)
        self._canais_mudaram()

    def _vista_saiu(self, vista: Vista, i: int) -> None:
        self.beginRemoveRows(self._indice(self._vistas), i, i)
        del self._vistas.filhos[i]
        self.endRemoveRows()
        self._mudou(self._vistas)
        self._canais_mudaram()

    def _vista_mudou(self, vista: Vista, _campos) -> None:
        indice = self.indice_da_vista(vista)
        if indice.isValid():
            self.dataChanged.emit(indice, indice)

    def _traco_entrou_ou_saiu(self, vista: Vista, traco: Traco, _i: int) -> None:
        self._vista_mudou(vista, None)
        self._canal_mudou(traco)

    def _traco_mudou(self, traco: Traco, campos) -> None:
        if "cor" in campos:
            self._canal_mudou(traco)

    def _canal_mudou(self, traco: Traco) -> None:
        for no in self._fontes.filhos:
            if no.objeto.id == traco.receita.fonte:
                indice = self.indice_do_canal(no.objeto, traco.receita.canal)
                if indice.isValid():
                    self.dataChanged.emit(indice, indice, [PAPEL_CORES])

    def _canais_mudaram(self) -> None:
        for no in self._fontes.filhos:
            if no.filhos:
                pai = self._indice(no)
                self.dataChanged.emit(self.index(0, 0, pai), self.index(len(no.filhos) - 1, 0, pai), [PAPEL_CORES])

    def _fonte_mudou(self, fonte: FonteDoProjeto) -> None:
        indice = self.indice_da_fonte(fonte)
        if indice.isValid():
            self.dataChanged.emit(indice, indice)

    def _mudou(self, no: _No) -> None:
        indice = self._indice(no)
        self.dataChanged.emit(indice, indice)


ICONES = {"fonte": "arquivo", "vista": "onda"}
INTEGRIDADE = {"confere": ("ok", "ok", "CRC das amostras conferido"),
               "nao_confere": ("alerta", "erro", "o CRC das amostras NÃO confere: o arquivo foi alterado"),
               "erro": ("alerta", "aviso", "não foi possível conferir o CRC"),
               "conferindo": ("relogio", "mudo", "conferindo o CRC das amostras…")}


class DelegadoDaArvore(QStyledItemDelegate):
    """Desenha cada linha da árvore com o tema (o mockup A1)."""

    def sizeHint(self, opcao: QStyleOptionViewItem, indice: QModelIndex) -> QSize:
        return QSize(super().sizeHint(opcao, indice).width(), ALTURA_DA_LINHA)

    def paint(self, p: QPainter, opcao: QStyleOptionViewItem, indice: QModelIndex) -> None:
        t = aparencia().tema
        tipo = indice.data(PAPEL_TIPO)
        caixa = QRectF(opcao.rect).adjusted(0, 1, -4, -1)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        selecionada = bool(opcao.state & QStyle.StateFlag.State_Selected)
        if selecionada or opcao.state & QStyle.StateFlag.State_MouseOver:
            fundo = QColor(t.acento if selecionada else t.texto)
            fundo.setAlphaF(0.13 if selecionada else 0.05)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fundo)
            p.drawRoundedRect(caixa, 5, 5)
            if selecionada:
                p.setBrush(QColor(t.acento))
                p.drawRect(QRectF(caixa.left(), caixa.top() + 3, 2, caixa.height() - 6))
        x = caixa.left() + 6
        meio = caixa.center().y()
        if tipo == "canal":
            x = self._pontos(p, t, indice.data(PAPEL_CORES) or [], x, meio)
        elif tipo in ICONES:
            fonte = indice.data(PAPEL_OBJETO) if tipo == "fonte" else None
            papel = "erro" if fonte is not None and fonte.esta_ausente else "texto2"
            p.drawPixmap(int(x), int(meio - 8), icone(ICONES[tipo], getattr(t, papel)).pixmap(16, 16))
            x += 16 + 7
        fonte_texto = QFont(opcao.font)
        if tipo == "grupo":
            fonte_texto.setWeight(QFont.Weight.DemiBold)
        p.setFont(fonte_texto)
        nome = indice.data(Qt.ItemDataRole.DisplayRole) or ""
        direita = caixa.right() - 6
        # O estado da fonte, à direita: a pirâmide em construção ou a integridade.
        if tipo == "fonte":
            direita = self._estado_da_fonte(p, t, indice.data(PAPEL_OBJETO), direita, meio)
        detalhe = indice.data(PAPEL_DETALHE) or ""
        menor = QFont(opcao.font)
        menor.setPixelSize(TAMANHOS["secundario"])
        metricas_menor = QFontMetrics(menor)
        metricas = QFontMetrics(fonte_texto)
        largura_nome = metricas.horizontalAdvance(nome)
        espaco = direita - x
        if detalhe and espaco > largura_nome + 40:
            detalhe = metricas_menor.elidedText(detalhe, Qt.TextElideMode.ElideRight, int(espaco - largura_nome - 12))
            p.setFont(menor)
            p.setPen(QColor(t.mudo))
            p.drawText(QRectF(x, caixa.top(), direita - x, caixa.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, detalhe)
            espaco -= metricas_menor.horizontalAdvance(detalhe) + 12
        p.setFont(fonte_texto)
        p.setPen(QColor(t.texto))
        p.drawText(QRectF(x, caixa.top(), max(0.0, espaco), caixa.height()), Qt.AlignmentFlag.AlignVCenter,
                   metricas.elidedText(nome, Qt.TextElideMode.ElideMiddle, int(max(0.0, espaco))))
        p.restore()

    @staticmethod
    def _pontos(p: QPainter, t: Tema, cores: list[int], x: float, meio: float) -> float:
        """Um ponto por traço do canal (até 4, sobrepostos); um círculo vazado se ele não está plotado."""
        lado = 9.0
        if not cores:
            p.setPen(QPen(QColor(t.borda_forte), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(x, meio - lado / 2, lado, lado))
            return x + lado + 8
        for k, cor in enumerate(cores[:4]):
            p.setPen(QPen(QColor(t.superficie), 1.5))
            p.setBrush(QColor(cor_do_traco(cor, t)[0]))
            p.drawEllipse(QRectF(x + 6 * k, meio - lado / 2, lado, lado))
        return x + lado + 6 * (min(len(cores), 4) - 1) + 8

    @staticmethod
    def _estado_da_fonte(p: QPainter, t: Tema, fonte: FonteDoProjeto, direita: float, meio: float) -> float:
        if fonte.progresso_da_piramide is not None:
            largura = 36.0
            trilho = QRectF(direita - largura, meio - 2, largura, 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t.borda))
            p.drawRoundedRect(trilho, 2, 2)
            p.setBrush(QColor(t.acento))
            p.drawRoundedRect(QRectF(trilho.left(), trilho.top(), largura * fonte.progresso_da_piramide, 4), 2, 2)
            return direita - largura - 8
        if fonte.integridade in INTEGRIDADE:
            nome, papel, _ = INTEGRIDADE[fonte.integridade]
            p.drawPixmap(int(direita - 14), int(meio - 7), icone(nome, getattr(t, papel), 14).pixmap(14, 14))
            return direita - 14 - 8
        return direita


class PainelDoProjeto(QWidget):
    """O filtro, a árvore e, sem nada aberto, o estado vazio.

    ``canalAtivado(fonte, numero)``: duplo clique num canal (plotar). ``vistaAtivada(vista)``: clique numa vista (abrir
    a aba dela). ``selecaoMudou(tipo, objeto)``: o que está
    selecionado na árvore (o inspetor mostra). ``fecharFontePedido(fonte)``: o menu de contexto."""

    canalAtivado = Signal(object, int)
    vistaAtivada = Signal(object)
    selecaoMudou = Signal(str, object)
    fecharFontePedido = Signal(object)

    def __init__(self, acao_abrir: QAction, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("painel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.filtro = QLineEdit()
        self.filtro.setObjectName("filtro_projeto")
        self.filtro.setPlaceholderText(self.tr("Filtrar"))
        self.filtro.setClearButtonEnabled(True)
        aparencia().mudou.connect(self._reescrever)
        lupa = QAction(self.filtro)
        IconeDoTema(lupa, "busca", "mudo")
        self.filtro.addAction(lupa, QLineEdit.ActionPosition.LeadingPosition)
        self.vazio = EstadoVazio(self.tr("Nenhuma captura aberta"),
                                 self.tr("Abra uma captura (Ctrl+O) ou arraste um arquivo .bin para a janela."),
                                 icone_nome="arquivo", compacto=True)
        self.arvore = QTreeView()
        self.arvore.setObjectName("arvore_projeto")
        self.arvore.setHeaderHidden(True)
        self.arvore.setUniformRowHeights(True)
        self.arvore.setMouseTracking(True)
        self.arvore.setIndentation(14)
        self.arvore.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.arvore.setItemDelegate(DelegadoDaArvore(self.arvore))
        self.arvore.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.arvore.customContextMenuRequested.connect(self._menu)
        self.arvore.doubleClicked.connect(self._duplo_clique)
        self.arvore.clicked.connect(self._clique)
        self.arvore.activated.connect(self._clique)          # o Enter (e, em alguns sistemas, o clique)
        self.pilha = QStackedWidget()
        self.pilha.addWidget(self.vazio)
        self.pilha.addWidget(self.arvore)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(8, 0, 8, 8)
        coluna.setSpacing(6)
        coluna.addWidget(self.filtro)
        coluna.addWidget(self.pilha, 1)
        self.filtro.textChanged.connect(self._filtrar)
        self.modelo: ArvoreDoProjeto | None = None
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setRecursiveFilteringEnabled(True)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.arvore.setModel(self.proxy)
        self.arvore.selectionModel().currentChanged.connect(self._atual_mudou)
        self.proxy.rowsInserted.connect(self._linhas_entraram)
        self.proxy.rowsRemoved.connect(self._atualizar_vazio)
        self._acao_abrir = acao_abrir

    def _reescrever(self, _tema=None) -> None:
        """A taxa e a duração de cada captura são escritas na pintura: pintar de novo (o separador decimal pode ter
        mudado)."""
        self.arvore.viewport().update()

    def mostrar(self, projeto: Projeto) -> None:
        """Passa a mostrar ``projeto`` (um modelo novo; o antigo some com o projeto antigo)."""
        antigo = self.modelo
        self.modelo = ArvoreDoProjeto(projeto, self)
        self.proxy.setSourceModel(self.modelo)
        if antigo is not None:
            antigo.deleteLater()
        self.arvore.expandAll()
        self._atualizar_vazio()

    def selecionar_fonte(self, fonte: FonteDoProjeto) -> None:
        indice = self.proxy.mapFromSource(self.modelo.indice_da_fonte(fonte))
        if indice.isValid():
            self.arvore.setCurrentIndex(indice)

    def _linhas_entraram(self, pai: QModelIndex, primeira: int, ultima: int) -> None:
        # Uma fonte nova (ou o grupo) aparece aberta, com os canais à vista.
        for linha in range(primeira, ultima + 1):
            self.arvore.expand(self.proxy.index(linha, 0, pai))
        if pai.isValid():
            self.arvore.expand(pai)
        self._atualizar_vazio()

    def _atualizar_vazio(self, *_) -> None:
        projeto = self.modelo.projeto if self.modelo is not None else None
        tem_algo = projeto is not None and bool(projeto.fontes or projeto.vistas)
        self.pilha.setCurrentWidget(self.arvore if tem_algo else self.vazio)

    def _filtrar(self, texto: str) -> None:
        self.proxy.setFilterFixedString(texto)
        self.arvore.expandAll()

    def _atual_mudou(self, atual: QModelIndex, _anterior: QModelIndex) -> None:
        self.selecaoMudou.emit(atual.data(PAPEL_TIPO) or "", atual.data(PAPEL_OBJETO))

    def _clique(self, indice: QModelIndex) -> None:
        if indice.data(PAPEL_TIPO) == "vista":
            self.vistaAtivada.emit(indice.data(PAPEL_OBJETO))

    def _duplo_clique(self, indice: QModelIndex) -> None:
        if indice.data(PAPEL_TIPO) == "canal":
            fonte, numero = indice.data(PAPEL_OBJETO)
            self.canalAtivado.emit(fonte, numero)

    def _menu(self, ponto) -> None:
        indice = self.arvore.indexAt(ponto)
        tipo, objeto = indice.data(PAPEL_TIPO), indice.data(PAPEL_OBJETO)
        menu = QMenu(self)
        if tipo == "canal":
            fonte, numero = objeto
            menu.addAction(self.tr("Plotar na vista ativa"), lambda: self.canalAtivado.emit(fonte, numero))
        elif tipo == "fonte":
            menu.addAction(self.tr("Fechar a captura"), lambda: self.fecharFontePedido.emit(objeto))
        else:
            menu.addAction(self._acao_abrir)
        menu.exec(self.arvore.viewport().mapToGlobal(ponto))

