"""O inspetor (docs/gui-plan.md, 9.4): as propriedades do que está selecionado. Por enquanto, a captura: o
cabeçalho em seções (``api.descrever_cabecalho``), a integridade (o CRC das amostras, conferido em segundo plano) e
a pirâmide. O do traço entra na F1.6."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from supraharmonicos.api import descrever_cabecalho

from ...componentes.painel import EstadoVazio
from ...modelo.objetos import FonteDoProjeto, Projeto
from ...tema.aplicar import aparencia
from ...tema.icones import icone
from ...tema.tokens import TAMANHOS, Tema
from .inspetor_traco import InspetorDoTraco

TEXTOS_DA_INTEGRIDADE = {
    "pendente": ("relogio", "mudo", "CRC das amostras: a conferir"),
    "conferindo": ("relogio", "mudo", "Conferindo o CRC das amostras…"),
    "confere": ("ok", "ok", "CRC das amostras conferido: o arquivo é o que a captura gravou"),
    "nao_confere": ("alerta", "erro", "O CRC das amostras NÃO confere: o arquivo foi alterado depois da captura"),
    "sem_crc": ("alerta", "mudo", "Sem o CRC das amostras (cabeçalho anterior ao v9)"),
    "erro": ("alerta", "aviso", "Não foi possível conferir o CRC das amostras"),
}


def _fonte(px: int, peso: QFont.Weight | None = None) -> QFont:
    f = QFont()
    f.setPixelSize(px)
    if peso is not None:
        f.setWeight(peso)
    return f


class InspetorDaFonte(QScrollArea):
    """O cabeçalho e o estado de uma captura aberta."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("inspetor_da_fonte")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.fonte: FonteDoProjeto | None = None
        self.valores: dict[str, str] = {}
        aparencia().mudou.connect(self._tema_mudou)

    def mostrar(self, fonte: FonteDoProjeto) -> None:
        if self.fonte is not None and self.fonte is not fonte:
            self.fonte.estadoMudou.disconnect(self._estado_mudou)
        if self.fonte is not fonte:
            fonte.estadoMudou.connect(self._estado_mudou)
        self.fonte = fonte
        self._montar()

    def soltar(self) -> None:
        if self.fonte is not None:
            self.fonte.estadoMudou.disconnect(self._estado_mudou)
            self.fonte = None

    def _tema_mudou(self, _tema: Tema) -> None:
        if self.fonte is not None:
            self._montar()

    def _estado_mudou(self, _fonte: FonteDoProjeto) -> None:
        self._atualizar_estado()

    def _montar(self) -> None:
        fonte, t = self.fonte, aparencia().tema
        conteudo = QWidget()
        conteudo.setObjectName("painel")
        conteudo.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        coluna = QVBoxLayout(conteudo)
        coluna.setContentsMargins(12, 4, 12, 12)
        coluna.setSpacing(10)

        topo = QHBoxLayout()
        simbolo = QLabel()
        simbolo.setPixmap(icone("arquivo", t.erro if fonte.esta_ausente else t.texto2, 18).pixmap(18, 18))
        topo.addWidget(simbolo, 0, Qt.AlignmentFlag.AlignTop)
        nomes = QVBoxLayout()
        nomes.setSpacing(1)
        self.titulo = QLabel(fonte.nome)
        self.titulo.setObjectName("titulo_inspetor")
        self.titulo.setFont(_fonte(TAMANHOS["titulo_painel"], QFont.Weight.DemiBold))
        self.titulo.setWordWrap(True)
        caminho = QLabel(str(fonte.caminho.parent))
        caminho.setObjectName("subtitulo_inspetor")
        caminho.setFont(_fonte(TAMANHOS["secundario"]))
        caminho.setWordWrap(True)
        caminho.setToolTip(str(fonte.caminho))
        nomes.addWidget(self.titulo)
        nomes.addWidget(caminho)
        topo.addLayout(nomes, 1)
        coluna.addLayout(topo)

        self.valores = {}
        if fonte.esta_ausente:
            aviso = QLabel(self.tr("A captura não foi encontrada (nem pelo CRC das amostras). Os traços dela continuam "
                                   "no projeto e voltam quando ela for localizada."))
            aviso.setObjectName("aviso_inspetor")
            aviso.setWordWrap(True)
            coluna.addWidget(aviso)
        else:
            self.estado_integridade = QLabel()
            self.estado_integridade.setObjectName("estado_integridade")
            self.estado_integridade.setWordWrap(True)
            self.icone_integridade = QLabel()
            linha = QHBoxLayout()
            linha.addWidget(self.icone_integridade, 0, Qt.AlignmentFlag.AlignTop)
            linha.addWidget(self.estado_integridade, 1)
            coluna.addLayout(linha)
            self.estado_piramide = QLabel()
            self.estado_piramide.setObjectName("estado_piramide")
            self.barra_piramide = QProgressBar()
            self.barra_piramide.setTextVisible(False)
            self.barra_piramide.setFixedHeight(6)
            coluna.addWidget(self.estado_piramide)
            coluna.addWidget(self.barra_piramide)
            for titulo, linhas in descrever_cabecalho(fonte.fonte.captura):
                if linhas:
                    coluna.addWidget(self._secao(titulo, linhas))
            self._atualizar_estado()
        coluna.addStretch(1)
        self.setWidget(conteudo)

    def _secao(self, titulo: str, linhas: list[tuple[str, str]]) -> QWidget:
        secao = QWidget()
        coluna = QVBoxLayout(secao)
        coluna.setContentsMargins(0, 6, 0, 0)
        coluna.setSpacing(6)
        linha_divisoria = QFrame()
        linha_divisoria.setObjectName("divisoria")
        linha_divisoria.setFixedHeight(1)
        coluna.addWidget(linha_divisoria)
        rotulo = QLabel(titulo)
        rotulo.setFont(_fonte(TAMANHOS["corpo"], QFont.Weight.DemiBold))
        coluna.addWidget(rotulo)
        # O rótulo em cima do valor: o painel é estreito, e um valor sem espaços (o identificador, o comando) não
        # caberia ao lado de um rótulo.
        grade = QGridLayout()
        grade.setHorizontalSpacing(0)
        grade.setVerticalSpacing(0)
        for i, (nome, valor) in enumerate(linhas):
            r = QLabel(nome)
            r.setObjectName("rotulo_campo")
            r.setFont(_fonte(TAMANHOS["legenda"]))
            v = QLabel(valor)
            v.setObjectName("valor_campo")
            v.setFont(_fonte(TAMANHOS["secundario"]))
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            v.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            v.setContentsMargins(0, 0, 0, 6)
            grade.addWidget(r, 2 * i, 0)
            grade.addWidget(v, 2 * i + 1, 0)
            self.valores[f"{titulo}/{nome}"] = valor
        coluna.addLayout(grade)
        return secao

    def _atualizar_estado(self) -> None:
        fonte, t = self.fonte, aparencia().tema
        if fonte is None or fonte.esta_ausente:
            return
        nome_icone, papel, texto = TEXTOS_DA_INTEGRIDADE[fonte.integridade]
        self.icone_integridade.setPixmap(icone(nome_icone, getattr(t, papel), 14).pixmap(14, 14))
        self.estado_integridade.setText(texto)
        if fonte.progresso_da_piramide is not None:
            self.estado_piramide.setText(self.tr("Construindo a pirâmide: {:.0%}").format(fonte.progresso_da_piramide))
            self.barra_piramide.setValue(int(100 * fonte.progresso_da_piramide))
            self.barra_piramide.show()
        else:
            self.barra_piramide.hide()
            if fonte.piramides:
                niveis = len(fonte.piramides[0].niveis)
                self.estado_piramide.setText(self.tr("Pirâmide pronta: {} níveis").format(niveis))
            else:
                self.estado_piramide.setText(self.tr("Pirâmide ainda não construída"))


class Inspetor(QStackedWidget):
    """O que o inspetor mostra, pelo que está selecionado; sem seleção, o estado vazio."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("inspetor")
        self.vazio = EstadoVazio(self.tr("Nada selecionado"),
                                 self.tr("Selecione uma captura, um traço ou uma vista para ver as propriedades aqui."),
                                 icone_nome="ajustes", compacto=True)
        self.da_fonte = InspetorDaFonte()
        self.do_traco = InspetorDoTraco()
        self.addWidget(self.vazio)
        self.addWidget(self.da_fonte)
        self.addWidget(self.do_traco)

    def mostrar_tracos(self, projeto: Projeto, tracos) -> None:
        """Os traços selecionados (um ou vários)."""
        self.da_fonte.soltar()
        self.do_traco.mostrar(projeto, tracos)
        self.setCurrentWidget(self.do_traco)

    def mostrar(self, tipo: str, objeto) -> None:
        if tipo == "fonte" and isinstance(objeto, FonteDoProjeto):
            self.da_fonte.mostrar(objeto)
            self.setCurrentWidget(self.da_fonte)
        elif tipo == "canal" and objeto is not None:
            self.da_fonte.mostrar(objeto[0])
            self.setCurrentWidget(self.da_fonte)
        else:
            self.da_fonte.soltar()
            self.setCurrentWidget(self.vazio)
