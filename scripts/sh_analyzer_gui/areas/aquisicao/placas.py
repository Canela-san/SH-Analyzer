"""A lista de placas da barra lateral (docs/gui-plan.md, 11.3; o B1): as placas que a busca achou (o USB, a rede, as
conhecidas que não responderam e o simulador), cada uma com o ponto do estado, o nome e, à direita, o caminho ou o
estado ("USB", "LAN", "conectada", "vista há 3 h", "demonstração").

**Um clique conecta** (Enter, no teclado); na conectada, leva à visão geral. O menu de contexto conecta por outro
caminho, desconecta e esquece uma placa conhecida. A dica de cada linha diz os caminhos, a latência, o nº de série e
a chave de host.

**A lista não pisca** a cada busca (a cada 5 s com a área à vista): o modelo só se refaz quando algo que se vê mudou.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPoint, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)
from sh_placa.cenarios import CENARIOS

from ... import preferencias
from ...servicos.conexao_da_placa import ConexaoDaPlaca
from ...tema.aplicar import aparencia
from ...tema.tokens import TAMANHOS, Tema
from .textos import CAMINHOS_CURTOS, ha_quanto, texto_da_latencia, traduzir

ALTURA_DA_LINHA = 32
LADO_DO_PONTO = 8

PAPEL_DA_PLACA = Qt.ItemDataRole.UserRole + 1
PAPEL_DO_LADO = Qt.ItemDataRole.UserRole + 2         # o texto da direita
PAPEL_DO_PONTO = Qt.ItemDataRole.UserRole + 3        # (papel da cor no tema, cheio?)
PAPEL_APAGADA = Qt.ItemDataRole.UserRole + 4         # o nome em cor de metadado (a ausente)

CONECTANDO = ("conectando", "confirmar_host", "pedir_senha")


def pintar_ponto(pintor: QPainter, centro: QPoint, cor: QColor, cheio: bool, lado: int = LADO_DO_PONTO) -> None:
    """O ponto de estado: cheio (conectada, conectando, com problema) ou só o contorno (ao alcance, ausente)."""
    pintor.save()
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    raio = lado / 2
    if cheio:
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(cor)
    else:
        pintor.setPen(QPen(cor, 1.5))
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        raio -= 0.75
    pintor.drawEllipse(QPointF(centro), raio, raio)
    pintor.restore()


class Ponto(QWidget):
    """O ponto de estado como widget (o cartão da placa): ``definir("ok", True)``; a cor segue o tema."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(LADO_DO_PONTO + 4, LADO_DO_PONTO + 4)
        self.papel, self.cheio = "mudo", False
        aparencia().mudou.connect(self.update)

    def definir(self, papel: str, cheio: bool) -> None:
        if (papel, cheio) != (self.papel, self.cheio):
            self.papel, self.cheio = papel, cheio
            self.update()

    def paintEvent(self, _evento) -> None:
        pintor = QPainter(self)
        pintar_ponto(pintor, self.rect().center(), QColor(getattr(aparencia().tema, self.papel)), self.cheio)


def lado_e_ponto(placa, conexao: ConexaoDaPlaca) -> tuple[str, str, bool]:
    """O texto da direita e o ponto (o papel da cor e se é cheio) de uma placa da lista."""
    if conexao.e_a_conectada(placa):
        if conexao.estado == "reconectando":
            return traduzir("reconectando…"), "aviso", True
        return traduzir("conectada"), "ok", True
    if conexao.placa is not None and conexao.placa.chave == placa.chave and conexao.estado != "desconectada":
        if conexao.estado in CONECTANDO:
            return traduzir("conectando…"), "acento", True
        if conexao.estado in ("falhou", "bloqueada"):
            return (traduzir("bloqueada") if conexao.estado == "bloqueada" else traduzir("sem conexão")), "erro", True
    if placa.estado == "simulador":
        return traduzir("demonstração"), "texto2", False
    if placa.estado == "so_serial":
        return traduzir("ligando…"), "aviso", False
    if placa.estado == "pelo_salto":
        return traduzir("pelo salto"), "mudo", False
    if placa.estado == "ausente":
        return ha_quanto(placa.vista_em), "mudo", False
    melhor = placa.melhor
    return (CAMINHOS_CURTOS.get(melhor.tipo, melhor.tipo) if melhor is not None else ""), "texto2", False


def dica_da_placa(placa, conexao: ConexaoDaPlaca) -> str:
    """A dica de uma linha: o nome, o nº de série, cada caminho (com a latência), a chave de host e o que o clique faz."""
    linhas = [placa.nome]
    if placa.serie and placa.estado != "simulador":
        linhas.append(traduzir("nº {}").format(placa.serie))
    for c in placa.caminhos:
        partes = [c.detalhe]
        if c.destino is not None:
            partes.append(str(c.destino))
        if c.latencia_ms is not None and c.tipo != "simulador":
            partes.append(texto_da_latencia(c.latencia_ms))
        linhas.append(" · ".join(partes))
    if placa.impressao:
        linhas.append(traduzir("chave de host {}").format(placa.impressao))
    if placa.estado == "ausente":
        linhas.append(traduzir("Não respondeu agora (vista pela última vez {}). Clique para tentar assim mesmo.").format(
            ha_quanto(placa.vista_em)))
    elif placa.estado == "so_serial":
        linhas.append(traduzir("Está no USB, mas a rede dela ainda não respondeu: ligando? Espere uns segundos."))
    elif conexao.e_a_conectada(placa):
        linhas.append(traduzir("Conectada. Clique para ver a visão geral."))
    else:
        linhas.append(traduzir("Clique para conectar."))
    return "\n".join(linhas)


def conectavel(placa) -> bool:
    """Tem um caminho para conectar (a placa só na porta serial ainda não tem rede)."""
    return placa.estado == "simulador" or placa.melhor is not None


class ModeloDasPlacas(QAbstractListModel):
    def __init__(self, conexao: ConexaoDaPlaca, parent=None):
        super().__init__(parent)
        self.conexao = conexao
        self._placas: list = []
        self._assinatura: tuple = ()
        conexao.placasMudaram.connect(self.atualizar)
        conexao.mudou.connect(self.atualizar)
        self.atualizar()

    def _linha(self, placa) -> tuple:
        return (placa.chave, placa.nome, placa.estado, placa.caminhos, placa.impressao, placa.vista_em,
                *lado_e_ponto(placa, self.conexao))

    def atualizar(self) -> None:
        """Refaz o modelo só quando algo que se vê mudou (a busca de 5 em 5 s não pisca a lista)."""
        placas = list(self.conexao.placas)
        assinatura = tuple(self._linha(p) for p in placas)
        if assinatura == self._assinatura:
            return
        self.beginResetModel()
        self._placas, self._assinatura = placas, assinatura
        self.endResetModel()

    def placa(self, linha: int):
        return self._placas[linha]

    def rowCount(self, pai: QModelIndex | None = None) -> int:
        return 0 if pai is not None and pai.isValid() else len(self._placas)

    def flags(self, indice: QModelIndex) -> Qt.ItemFlag:
        if not indice.isValid():
            return Qt.ItemFlag.NoItemFlags
        placa = self._placas[indice.row()]
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if conectavel(placa) else Qt.ItemFlag.NoItemFlags

    def data(self, indice: QModelIndex, papel: int = Qt.ItemDataRole.DisplayRole):
        if not indice.isValid():
            return None
        placa = self._placas[indice.row()]
        if papel == Qt.ItemDataRole.DisplayRole:
            return placa.nome
        if papel == Qt.ItemDataRole.ToolTipRole:
            return dica_da_placa(placa, self.conexao)
        if papel == Qt.ItemDataRole.AccessibleDescriptionRole:
            return lado_e_ponto(placa, self.conexao)[0]
        if papel == PAPEL_DA_PLACA:
            return placa
        if papel == PAPEL_DO_LADO:
            return lado_e_ponto(placa, self.conexao)[0]
        if papel == PAPEL_DO_PONTO:
            return lado_e_ponto(placa, self.conexao)[1:]
        if papel == PAPEL_APAGADA:
            return placa.estado == "ausente" or not conectavel(placa)
        return None


class DelegadoDasPlacas(QStyledItemDelegate):
    """Cada linha como no B1: o ponto, o nome e o texto da direita, sem a moldura de seleção do estilo."""

    def sizeHint(self, opcao: QStyleOptionViewItem, indice: QModelIndex) -> QSize:
        return QSize(opcao.rect.width(), ALTURA_DA_LINHA)

    def paint(self, pintor: QPainter, opcao: QStyleOptionViewItem, indice: QModelIndex) -> None:
        tema: Tema = aparencia().tema
        r: QRect = opcao.rect.adjusted(8, 1, -8, -1)
        pintor.save()
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        foco = bool(opcao.state & QStyle.StateFlag.State_HasFocus) and opcao.widget is not None \
            and opcao.widget.hasFocus()
        if opcao.state & QStyle.StateFlag.State_MouseOver and indice.flags() & Qt.ItemFlag.ItemIsEnabled or foco:
            pintor.setPen(QPen(QColor(tema.acento), 1) if foco else Qt.PenStyle.NoPen)
            pintor.setBrush(QColor(tema.elevada))
            pintor.drawRoundedRect(r.adjusted(0, 0, -1, -1), 6, 6)
        papel, cheio = indice.data(PAPEL_DO_PONTO)
        x = r.left() + 10
        pintar_ponto(pintor, QPoint(x + LADO_DO_PONTO // 2, r.center().y() + 1), QColor(getattr(tema, papel)), cheio)
        x += LADO_DO_PONTO + 10
        lado = indice.data(PAPEL_DO_LADO) or ""
        fonte_lado = QFont(opcao.font)
        fonte_lado.setPixelSize(TAMANHOS["secundario"])
        largura_do_lado = QFontMetrics(fonte_lado).horizontalAdvance(lado)
        direita = r.right() - 10
        pintor.setFont(fonte_lado)
        pintor.setPen(QColor(tema.mudo if papel != "erro" else tema.erro))
        pintor.drawText(QRect(direita - largura_do_lado, r.top(), largura_do_lado, r.height()),
                        int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), lado)
        pintor.setFont(opcao.font)
        pintor.setPen(QColor(tema.mudo if indice.data(PAPEL_APAGADA) else tema.texto))
        espaco = max(0, direita - largura_do_lado - 10 - x)
        nome = QFontMetrics(opcao.font).elidedText(indice.data() or "", Qt.TextElideMode.ElideRight, espaco)
        pintor.drawText(QRect(x, r.top(), espaco, r.height()), int(Qt.AlignmentFlag.AlignVCenter), nome)
        pintor.restore()


class ListaDePlacas(QListView):
    """A lista. ``conectadaClicada`` sai no clique na placa já conectada (a área mostra a visão geral)."""

    conectadaClicada = Signal()

    def __init__(self, conexao: ConexaoDaPlaca, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("lista_de_placas")
        self.conexao = conexao
        self.modelo = ModeloDasPlacas(conexao, self)
        self.setModel(self.modelo)
        self.setItemDelegate(DelegadoDasPlacas(self))
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setUniformItemSizes(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.clicked.connect(self._escolher)
        self.modelo.modelReset.connect(self.updateGeometry)
        aparencia().mudou.connect(self.viewport().update)

    def sizeHint(self) -> QSize:
        """Da altura das linhas (poucas: a lista não rola com até 8 placas)."""
        linhas = max(1, min(8, self.modelo.rowCount()))
        return QSize(super().sizeHint().width(), linhas * ALTURA_DA_LINHA + 2 * self.frameWidth() + 4)

    def minimumSizeHint(self) -> QSize:
        return QSize(super().minimumSizeHint().width(), ALTURA_DA_LINHA + 2 * self.frameWidth() + 4)

    def keyPressEvent(self, evento: QKeyEvent) -> None:
        if evento.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self.currentIndex().isValid():
            self._escolher(self.currentIndex())
            return
        super().keyPressEvent(evento)

    def _escolher(self, indice: QModelIndex) -> None:
        if not indice.isValid() or not indice.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        placa = self.modelo.placa(indice.row())
        if self.conexao.e_a_conectada(placa):
            self.conectadaClicada.emit()
        else:
            self.conexao.conectar(placa)

    def _menu(self, ponto: QPoint) -> None:
        indice = self.indexAt(ponto)
        if not indice.isValid():
            return
        placa = self.modelo.placa(indice.row())
        menu = self.menu_da_placa(placa)
        if not menu.isEmpty():
            menu.exec(self.viewport().mapToGlobal(ponto))

    def menu_da_placa(self, placa) -> QMenu:
        """Conectar (ou desconectar), conectar por outro caminho, o cenário do simulador e esquecer a placa
        conhecida."""
        menu = QMenu(self)
        if self.conexao.e_a_conectada(placa):
            menu.addAction(traduzir("Desconectar"), self.conexao.desconectar)
        elif conectavel(placa):
            menu.addAction(traduzir("Conectar"), lambda: self.conexao.conectar(placa))
        if placa.estado == "simulador":
            atual = self.conexao.cenario if self.conexao.e_a_conectada(placa) else preferencias.cenario_do_simulador()
            cenarios = menu.addMenu(traduzir("Conectar no cenário"))
            for nome, c in CENARIOS.items():
                if c.grupo == "configuracao" and nome == next(n for n, x in CENARIOS.items() if x.grupo == c.grupo):
                    cenarios.addSeparator()
                acao = cenarios.addAction(traduzir(c.titulo),
                                          lambda _=False, n=nome: self.conexao.conectar(placa, cenario=n))
                acao.setCheckable(True)
                acao.setChecked(nome == atual)
                acao.setToolTip(traduzir(c.descricao))
            cenarios.setToolTipsVisible(True)
        caminhos = [c for c in placa.caminhos if c.destino is not None]
        if len(caminhos) > 1:
            por = menu.addMenu(traduzir("Conectar por"))
            for c in caminhos:
                por.addAction(f"{c.detalhe} · {c.destino}",
                              lambda _=False, d=c.destino: self.conexao.conectar(placa, destino=d))
        if placa.conhecida is not None:
            menu.addSeparator()
            menu.addAction(traduzir("Esquecer esta placa"), lambda: self.conexao.esquecer_placa(placa.serie))
        return menu
