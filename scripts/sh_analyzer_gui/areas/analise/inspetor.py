"""O inspetor (docs/gui-plan.md, 9.4): as propriedades do que está selecionado. Da captura: o cabeçalho em seções
(``api.descrever_cabecalho``), a integridade (o CRC das amostras, conferido em segundo plano), a pirâmide e o
cabeçalho copiado como texto (as seções daqui) ou como JSON (``api.cabecalho_em_dict``: todos os campos, sem
arredondar; PD-07). O do traço fica em ``inspetor_traco.py``."""

from __future__ import annotations

import html
import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from supraharmonicos.api import cabecalho_em_dict, descrever_cabecalho

from ...componentes.basicos import Botao
from ...componentes.caderno import ListaDoCaderno
from ...componentes.numeros import formatar_campo
from ...componentes.painel import EstadoVazio
from ...componentes.toast import Toast
from ...dados import caderno
from ...modelo.objetos import FonteDoProjeto, Projeto
from ...tema.aplicar import aparencia
from ...tema.icones import icone
from ...tema.tokens import TAMANHOS, Tema
from .inspetor_traco import LARGURA_DO_ROTULO, InspetorDoTraco
from .secao_do_espectro import SecaoDoEspectro

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
            copiar = QHBoxLayout()
            copiar.setSpacing(4)
            self.copiar_texto = Botao(self.tr("Copiar texto"), "fantasma", "copiar")
            self.copiar_texto.setObjectName("copiar_cabecalho_texto")
            self.copiar_texto.setToolTip(self.tr("O cabeçalho como aparece aqui, seção a seção"))
            self.copiar_texto.clicked.connect(lambda: self.copiar_cabecalho("texto"))
            self.copiar_json = Botao(self.tr("Copiar JSON"), "fantasma", "copiar")
            self.copiar_json.setObjectName("copiar_cabecalho_json")
            self.copiar_json.setToolTip(self.tr("Todos os campos do cabeçalho, sem arredondar"))
            self.copiar_json.clicked.connect(lambda: self.copiar_cabecalho("json"))
            copiar.addWidget(self.copiar_texto)
            copiar.addWidget(self.copiar_json)
            copiar.addStretch(1)
            coluna.addLayout(copiar)
            for titulo, linhas in descrever_cabecalho(fonte.fonte.captura, formatar_campo):
                if linhas:
                    coluna.addWidget(self._secao(titulo, linhas))
            self._atualizar_estado()
        coluna.addStretch(1)
        self.setWidget(conteudo)

    def texto_do_cabecalho(self) -> str:
        """O cabeçalho em texto, seção a seção, como aparece aqui ("Captura", "  Arquivo: c.bin", ...)."""
        linhas = []
        for titulo, campos in descrever_cabecalho(self.fonte.fonte.captura, formatar_campo):
            if campos:
                linhas.append(titulo)
                linhas += [f"  {nome}: {valor}" for nome, valor in campos]
        return "\n".join(linhas)

    def json_do_cabecalho(self) -> str:
        """Todos os campos do cabeçalho em JSON (``api.cabecalho_em_dict``), sem arredondar."""
        return json.dumps(cabecalho_em_dict(self.fonte.fonte.captura), ensure_ascii=False, indent=2, allow_nan=False)

    def copiar_cabecalho(self, como: str) -> None:
        """Põe o cabeçalho da captura na área de transferência: ``como`` é ``"texto"`` ou ``"json"``."""
        if self.fonte is None or self.fonte.esta_ausente:
            return
        QGuiApplication.clipboard().setText(self.json_do_cabecalho() if como == "json" else self.texto_do_cabecalho())
        Toast.mostrar(self.window(), self.tr("Cabeçalho copiado em JSON") if como == "json"
                      else self.tr("Cabeçalho copiado em texto"), "sucesso")

    def _secao(self, titulo: str, linhas: list[tuple[str, str]]) -> QWidget:
        """Uma seção do cabeçalho: o título e os campos, **num rótulo só, em texto rico** (o rótulo de cada campo em
        cima do valor: o painel é estreito, e um valor sem espaços não caberia ao lado). Dois ``QLabel`` por campo
        eram ~45 widgets por captura e travavam a tela por ~40 ms a cada seleção."""
        t = aparencia().tema
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
        partes = []
        for nome, valor in linhas:
            partes.append(f'<div style="color:{t.texto2}; font-size:{TAMANHOS["legenda"]}px">{html.escape(nome)}</div>'
                          f'<div style="margin-bottom:6px">{html.escape(valor)}</div>')
            self.valores[f"{titulo}/{nome}"] = valor
        campos = QLabel("".join(partes))
        campos.setObjectName("campos_do_cabecalho")
        campos.setTextFormat(Qt.TextFormat.RichText)
        campos.setFont(_fonte(TAMANHOS["secundario"]))
        campos.setWordWrap(True)
        campos.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        campos.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        coluna.addWidget(campos)
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


DESCRICOES_DAS_VISTAS = {
    "bandas": "As bandas de 200 Hz de 2 a 150 kHz (IEC 61000-4-7, anexo B), em tabela e no tempo.",
    "espectrograma": "O espectro ao longo do tempo, num mapa de cores perceptual; clique para ir ao instante.",
    "harmonicos": "Os grupos e subgrupos harmônicos da IEC 61000-4-7, a THD, a THDG e a THDS, em barras e tabela.",
    "xy": "Um canal contra o outro (a tensão contra a corrente), com a potência ativa, o fator de potência e a "
          "defasagem.",
    "histograma": "A distribuição das amostras do trecho, com as estatísticas (média, desvio, assimetria, curtose).",
    "eventos": "Os afundamentos, as elevações, as interrupções, os picos de supraharmônicos, a saturação e as "
               "descontinuidades achados na captura; um clique leva até o evento no tempo.",
    "qualidade": "Os índices de 12 ciclos da IEC 61000-4-30 (frequência, RMS, THD, fatores, supraharmônicos), as "
                 "janelas com evento marcadas e fora das estatísticas, e os agregados de 150/180 ciclos.",
    "transferencia": "A função de transferência entre dois canais (o ganho e a fase), com a coerência e o intervalo "
                     "de confiança.",
    "metricas": "As métricas de bancada do medir_captura: o ruído, a SNR, o SINAD, o ENOB, o SFDR e o jitter.",
    "instrumento": "Os ciclos sobrepostos, como num osciloscópio, com o disparo no cruzamento por zero e a "
                   "persistência.",
}
"""O que cada vista derivada mostra, no inspetor (sem traço selecionado)."""


class InspetorDaVista(QScrollArea):
    """As propriedades da vista ativa, sem traço selecionado: num espectro, a análise dele; nas outras derivadas, o
    que a vista mostra, de qual vista de tempo ela segue os traços e a ajuda dela."""

    ajudaPedida = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("inspetor_da_vista")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        conteudo = QWidget()
        conteudo.setObjectName("painel")
        conteudo.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        coluna = QVBoxLayout(conteudo)
        coluna.setContentsMargins(12, 4, 12, 12)
        coluna.setSpacing(10)
        self.titulo = QLabel()
        self.titulo.setObjectName("titulo_inspetor")
        fonte = QFont()
        fonte.setPixelSize(TAMANHOS["titulo_painel"])
        fonte.setWeight(QFont.Weight.DemiBold)
        self.titulo.setFont(fonte)
        self.titulo.setWordWrap(True)
        dica = QLabel(self.tr("As opções valem para todos os traços da vista. Clique numa curva para ver o traço."))
        dica.setObjectName("subtitulo_inspetor")
        dica.setWordWrap(True)
        divisoria = QFrame()
        divisoria.setObjectName("divisoria")
        divisoria.setFixedHeight(1)
        rotulo = QLabel(self.tr("Análise do espectro"))
        fonte = QFont()
        fonte.setPixelSize(TAMANHOS["corpo"])
        fonte.setWeight(QFont.Weight.DemiBold)
        rotulo.setFont(fonte)
        self.espectro = SecaoDoEspectro(LARGURA_DO_ROTULO)
        self.dica, self.divisoria, self.rotulo_do_espectro = dica, divisoria, rotulo
        self.descricao = QLabel()
        self.descricao.setObjectName("descricao_da_vista")
        self.descricao.setWordWrap(True)
        self.origem = QLabel()
        self.origem.setObjectName("subtitulo_inspetor")
        self.origem.setWordWrap(True)
        self.ajuda = Botao(self.tr("A ajuda desta vista (F1)"), "secundario", "livro")
        self.ajuda.setObjectName("ajuda_da_vista")
        self.ajuda.clicked.connect(self.ajudaPedida)
        coluna.addWidget(self.titulo)
        coluna.addWidget(dica)
        coluna.addWidget(self.origem)
        coluna.addWidget(divisoria)
        coluna.addWidget(rotulo)
        coluna.addWidget(self.espectro)
        coluna.addWidget(self.descricao)
        coluna.addWidget(self.ajuda, 0, Qt.AlignmentFlag.AlignLeft)
        coluna.addStretch(1)
        self.setWidget(conteudo)

    def mostrar(self, projeto: Projeto | None, vista, f1=None) -> None:
        self.titulo.setText(vista.nome if vista is not None else "")
        espectro = vista is not None and vista.tipo == "espectro"
        self.espectro.mostrar(projeto, vista if espectro else None, f1)
        for w in (self.dica, self.rotulo_do_espectro, self.espectro):
            w.setVisible(espectro)
        descricao = DESCRICOES_DAS_VISTAS.get(getattr(vista, "tipo", ""), "")
        self.descricao.setText(self.tr(descricao) if descricao else "")
        self.descricao.setVisible(bool(descricao))
        self.ajuda.setVisible(vista is not None)
        alvo = getattr(getattr(vista, "opcoes", None), "vista_de_tempo", None)
        seguida = next((v for v in projeto.vistas if v.id == alvo), None) if projeto is not None and alvo else None
        self.origem.setText(self.tr("Segue os traços de \"{}\".").format(seguida.nome) if seguida is not None else "")
        self.origem.setVisible(seguida is not None)


class InspetorDoCaderno(QWidget):
    """Um caderno de bancada do projeto (a seção "Notas"): as entradas, a mais nova em cima, e "Abrir no editor"
    (``abrirPedido``). Só leitura: a nota nova é no caderno do dia, na Aquisição."""

    abrirPedido = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("inspetor_do_caderno")
        self.arquivo: Path | None = None
        self.titulo = QLabel()
        self.titulo.setObjectName("titulo_inspetor")
        self.titulo.setFont(_fonte(TAMANHOS["titulo_painel"], QFont.Weight.DemiBold))
        self.caminho = QLabel()
        self.caminho.setObjectName("subtitulo_inspetor")
        self.caminho.setFont(_fonte(TAMANHOS["secundario"]))
        self.caminho.setWordWrap(True)
        self.abrir = Botao(self.tr("Abrir no editor"), "secundario", "pagina")
        self.abrir.setObjectName("abrir_o_caderno_no_editor")
        self.abrir.clicked.connect(lambda: self.abrirPedido.emit(self.arquivo) if self.arquivo else None)
        self.lista = ListaDoCaderno(self.tr("Nenhuma entrada no formato do caderno (\"- **HH:MM:SS** · você · …\"): "
                                            "o arquivo inteiro abre no editor."))
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(12, 4, 12, 12)
        coluna.setSpacing(8)
        coluna.addWidget(self.titulo)
        coluna.addWidget(self.caminho)
        coluna.addWidget(self.abrir, 0, Qt.AlignmentFlag.AlignLeft)
        coluna.addWidget(self.lista, 1)

    def mostrar(self, arquivo: Path) -> None:
        self.arquivo = Path(arquivo)
        self.recarregar()

    def recarregar(self) -> None:
        """Lê o arquivo de novo (o caderno do dia mudou)."""
        if self.arquivo is None:
            return
        self.titulo.setText(self.tr("Caderno de {}").format(self.arquivo.parent.name))
        self.caminho.setText(str(self.arquivo))
        try:
            entradas = caderno.ler(self.arquivo)
        except OSError:
            entradas = []
        self.lista.definir(entradas)


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
        self.da_vista = InspetorDaVista()
        self.do_caderno = InspetorDoCaderno()
        self.addWidget(self.vazio)
        self.addWidget(self.da_fonte)
        self.addWidget(self.do_traco)
        self.addWidget(self.da_vista)
        self.addWidget(self.do_caderno)
        self.vista_ativa = None

    def definir_vista_ativa(self, projeto: Projeto | None, vista, f1=None) -> None:
        """A vista da aba ativa (as seções que dependem dela: a análise de um espectro)."""
        self.vista_ativa = vista
        self.do_traco.definir_vista(projeto, vista, f1)
        self.da_vista.mostrar(projeto, vista if vista is not None and vista.tipo not in ("tempo", "sonda") else None,
                              f1)

    def atualizar_vista(self) -> None:
        """Um espectro novo chegou (outra fundamental muda o que o preset põe)."""
        self.do_traco.espectro.atualizar()
        self.da_vista.espectro.atualizar()

    def mostrar_vista(self) -> None:
        self.da_fonte.soltar()
        self.setCurrentWidget(self.da_vista)

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
        elif tipo == "nota" and objeto is not None:
            self.da_fonte.soltar()
            self.do_caderno.mostrar(objeto)
            self.setCurrentWidget(self.do_caderno)
        else:
            self.da_fonte.soltar()
            self.setCurrentWidget(self.vazio)
