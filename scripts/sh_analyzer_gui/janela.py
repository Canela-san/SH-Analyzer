"""A janela do Estúdio (docs/gui-plan.md, 9.1; o mockup A1 em ``docs/gui-mockups/a1-estudio.html``).

As regiões:

* a **barra superior** (``componentes.barra_superior``), no lugar da barra de menus;
* o **Projeto** à esquerda e o **Inspetor** à direita, docks de altura inteira;
* as **vistas** no centro, em abas; sem vista aberta, o estado vazio diz como começar;
* o **painel de baixo** (medidas, tarefas, avisos), só embaixo das vistas;
* a **barra de status**.

**As ações** (``self.acoes``, pelo nome) são o ponto único de cada comando: o botão, o atalho e, depois, a paleta de
comandos (F1.8) disparam a mesma ``QAction``. **O desfazer** é a ``QUndoStack`` da janela (``self.pilha``): toda
edição do modelo entra nela como um comando (F1.2).

**O layout** (o tamanho da janela e dos painéis, e quais estão abertos) é salvo ao fechar e restaurado ao abrir
(``configuracao.py``). Ctrl+B, Ctrl+I e Ctrl+J recolhem o Projeto, o Inspetor e o painel de baixo.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence, QShowEvent, QUndoStack
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from . import preferencias
from .componentes.barra_superior import BarraSuperior
from .componentes.basicos import Botao
from .componentes.painel import EstadoVazio, PainelComAbas, TituloDoPainel, botao_de_icone
from .componentes.toast import Toast
from .configuracao import gravar, ler_bytes
from .tema.aplicar import aparencia
from .tema.fontes import familias_disponiveis, fonte_escolhida
from .tema.icones import IconeDoTema
from .tema.tokens import Tema

TAMANHO_INICIAL = (1440, 900)
TAMANHO_MINIMO = (960, 600)
LADO_DA_MARCA = 72              # px da marca no estado vazio
LARGURA_DO_PROJETO = 264
LARGURA_DO_INSPETOR = 312
ALTURA_DO_PAINEL_INFERIOR = 200

VERSAO_DO_LAYOUT = 1
"""Sobe quando os docks mudam: um layout salvo por outra versão é ignorado (o padrão vale), em vez de deixar um
painel novo escondido ou fora do lugar."""
CHAVE_DA_GEOMETRIA = "janela/geometria"
CHAVE_DO_ESTADO = "janela/estado"

ABA_MEDIDAS, ABA_TAREFAS, ABA_AVISOS = range(3)


def _dica_com_atalho(acao: QAction) -> None:
    """A dica = o texto da ação + o atalho. Confere se a ação ainda existe: ao destruir a janela, a pilha se limpa e
    muda o texto do desfazer quando a ação já pode ter sido apagada."""
    if isValid(acao):
        atalho = acao.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        dica = f"{acao.text()} ({atalho})" if atalho else acao.text()
        if acao.toolTip() != dica:
            acao.setToolTip(dica)


class JanelaPrincipal(QMainWindow):
    """A janela do aplicativo. As regiões ficam em atributos (``barra``, ``dock_projeto``, ``dock_inspetor``,
    ``dock_inferior``, ``vistas``, ``painel_inferior``) para as fases seguintes as preencherem."""

    def __init__(self) -> None:
        super().__init__()
        app = QApplication.instance()
        self.setWindowTitle(app.applicationName() or "SH-Analyzer")
        self.resize(*TAMANHO_INICIAL)
        self.setMinimumSize(*TAMANHO_MINIMO)
        self.setDockNestingEnabled(False)
        # O Projeto e o Inspetor ocupam a altura inteira; o painel de baixo fica só embaixo das vistas.
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)

        self.pilha = QUndoStack(self)
        self.acoes: dict[str, QAction] = {}
        self._criar_acoes()

        self.barra = BarraSuperior(self.acoes["paleta"].shortcut())
        self.setMenuWidget(self.barra)
        self.barra.campo_paleta.clicked.connect(self.acoes["paleta"].trigger)
        self.barra.botao_desfazer.setDefaultAction(self.acoes["desfazer"])
        self.barra.botao_refazer.setDefaultAction(self.acoes["refazer"])
        self.barra.botao_tema.setDefaultAction(self.acoes["alternar_tema"])
        self.barra.botao_ajustes.setMenu(self._menu_de_ajustes())
        self.barra.botao_ajustes.setToolTip(self.tr("Ajustes"))
        IconeDoTema(self.barra.botao_ajustes, "ajustes")
        for indice, versao in ((1, "v0.11"), (2, "v0.10")):
            self.barra.areas.habilitar(indice, False, self.tr("Chega na {}").format(versao))

        self.setCentralWidget(self._criar_centro())
        self.dock_projeto = self._criar_dock("projeto", self.tr("Projeto"), self._criar_projeto(),
                                             Qt.DockWidgetArea.LeftDockWidgetArea, "painel_projeto")
        self.dock_inspetor = self._criar_dock("inspetor", self.tr("Inspetor"), self._criar_inspetor(),
                                              Qt.DockWidgetArea.RightDockWidgetArea, "painel_inspetor")
        self.painel_inferior = self._criar_painel_inferior()
        self.dock_inferior = self._criar_dock("inferior", self.tr("Painel de baixo"), self.painel_inferior,
                                              Qt.DockWidgetArea.BottomDockWidgetArea, "painel_inferior",
                                              com_titulo=False)
        self._criar_barra_de_status()

        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou(aparencia().tema)
        self._layout_restaurado = self.restaurar_layout()
        self._primeira_exibicao = True

    # ------------------------------------------------------------------ ações

    def _acao(self, nome: str, texto: str, *, atalho: QKeySequence | str | None = None, icone: str | None = None,
              dica: str | None = None, acao: QAction | None = None) -> QAction:
        """Registra uma ação pelo nome (``self.acoes``) e a liga à janela, para o atalho valer em qualquer região."""
        a = acao or QAction(texto, self)
        a.setObjectName(nome)
        if atalho is not None:
            a.setShortcut(QKeySequence(atalho))
        if icone is not None:
            IconeDoTema(a, icone)
        rotulo = dica or texto
        if not a.shortcut().isEmpty():
            rotulo += f" ({a.shortcut().toString(QKeySequence.SequenceFormat.NativeText)})"
        a.setToolTip(rotulo)
        self.addAction(a)
        self.acoes[nome] = a
        return a

    def _criar_acoes(self) -> None:
        self._acao("desfazer", self.tr("Desfazer"), atalho=QKeySequence.StandardKey.Undo, icone="desfazer",
                   acao=self.pilha.createUndoAction(self, self.tr("Desfazer")))
        self._acao("refazer", self.tr("Refazer"), atalho=QKeySequence.StandardKey.Redo, icone="refazer",
                   acao=self.pilha.createRedoAction(self, self.tr("Refazer")))
        # A dica do desfazer diz o que vai ser desfeito ("Desfazer Remover o traço (Ctrl+Z)").
        for nome in ("desfazer", "refazer"):
            self.acoes[nome].changed.connect(partial(_dica_com_atalho, self.acoes[nome]))
        self._acao("paleta", self.tr("Paleta de comandos"), atalho="Ctrl+K").triggered.connect(self.abrir_paleta)
        self._acao("alternar_tema", self.tr("Alternar o tema claro e escuro"),
                   icone="sol").triggered.connect(preferencias.alternar_tema)
        a = self._acao("abrir", self.tr("Abrir captura…"), atalho=QKeySequence.StandardKey.Open, icone="pasta")
        a.setEnabled(False)            # a F1.4 liga
        a = self._acao("nova_vista", self.tr("Nova vista"), icone="mais")
        a.setEnabled(False)            # a F1.5 liga

    def abrir_paleta(self) -> None:
        """A paleta de comandos (F1.8). Por enquanto, avisa que ela ainda não existe."""
        Toast.mostrar(self, self.tr("A paleta de comandos ainda não está pronta."), "info")

    def _menu_de_ajustes(self) -> QMenu:
        """O tema e as fontes, gravados na configuração. A tela de configurações completa vem depois (GE-05)."""
        menu = QMenu(self)
        menu.setObjectName("menu_ajustes")
        sub = menu.addMenu(self.tr("Tema"))
        grupo = QActionGroup(sub)
        self._acoes_de_tema: dict[str, QAction] = {}
        for modo, texto in (("sistema", self.tr("O do sistema")), ("escuro", self.tr("Escuro")),
                            ("claro", self.tr("Claro"))):
            a = sub.addAction(texto)
            a.setCheckable(True)
            a.setActionGroup(grupo)
            a.triggered.connect(lambda _=False, m=modo: preferencias.mudar_tema(m))
            self._acoes_de_tema[modo] = a
        for papel, titulo in (("interface", self.tr("Fonte da interface")), ("mono", self.tr("Fonte dos números"))):
            sub = menu.addMenu(titulo)
            grupo = QActionGroup(sub)
            familias = familias_disponiveis(papel)
            for familia in familias:
                a = sub.addAction(familia)
                a.setCheckable(True)
                a.setActionGroup(grupo)
                a.setChecked(familia == fonte_escolhida(papel))
                a.triggered.connect(lambda _=False, p=papel, f=familia: preferencias.mudar_fonte(p, f))
            sub.setEnabled(bool(familias))
        menu.aboutToShow.connect(self._marcar_tema_no_menu)
        return menu

    def _marcar_tema_no_menu(self) -> None:
        self._acoes_de_tema[aparencia().modo].setChecked(True)

    # ------------------------------------------------------------------ regiões

    def _criar_centro(self) -> QWidget:
        """As abas das vistas e, sem nenhuma, o estado vazio no lugar delas."""
        self.vistas = QTabWidget()
        self.vistas.setObjectName("vistas")
        self.vistas.setDocumentMode(True)
        self.vistas.setTabsClosable(True)
        self.vistas.setMovable(True)
        self.vistas.setCornerWidget(botao_de_icone(self.acoes["nova_vista"]), Qt.Corner.TopRightCorner)

        abrir = Botao(self.tr("Abrir captura…"), "primario", "pasta")
        abrir.setObjectName("botao_abrir_central")
        abrir.clicked.connect(self.acoes["abrir"].trigger)
        abrir.setEnabled(self.acoes["abrir"].isEnabled())
        self.acoes["abrir"].enabledChanged.connect(abrir.setEnabled)
        app = QApplication.instance()
        self.vazio_central = EstadoVazio(
            self.tr("Abra uma captura para começar"),
            self.tr("Escolha um arquivo .bin com cabeçalho ou arraste-o para esta janela. As capturas abertas "
                    "aparecem no painel do projeto, com os canais prontos para plotar."),
            imagem=app.windowIcon().pixmap(LADO_DA_MARCA, LADO_DA_MARCA), botao=abrir, largura_do_texto=440)
        self.vazio_central.simbolo.setObjectName("marca")

        self.centro = QStackedWidget()
        self.centro.setObjectName("area_central")
        self.centro.addWidget(self.vazio_central)
        self.centro.addWidget(self.vistas)
        self.vistas.currentChanged.connect(self._atualizar_centro)
        self._atualizar_centro()
        return self.centro

    def _atualizar_centro(self, _indice: int = -1) -> None:
        """As abas, ou o estado vazio sem nenhuma (também chamado ao fechar a janela, quando as abas saem)."""
        if isValid(self.centro) and isValid(self.vistas):
            self.centro.setCurrentWidget(self.vistas if self.vistas.count() else self.vazio_central)

    def _criar_projeto(self) -> QWidget:
        corpo = QWidget()
        corpo.setObjectName("painel")
        corpo.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.filtro_do_projeto = QLineEdit()
        self.filtro_do_projeto.setObjectName("filtro_projeto")
        self.filtro_do_projeto.setPlaceholderText(self.tr("Filtrar"))
        self.filtro_do_projeto.setClearButtonEnabled(True)
        lupa = QAction(self.filtro_do_projeto)
        IconeDoTema(lupa, "busca", "mudo")
        self.filtro_do_projeto.addAction(lupa, QLineEdit.ActionPosition.LeadingPosition)
        self.vazio_projeto = EstadoVazio(self.tr("Nenhuma captura aberta"),
                                         self.tr("Abra uma captura para ver os canais aqui."),
                                         icone_nome="arquivo", compacto=True)
        coluna = QVBoxLayout(corpo)
        coluna.setContentsMargins(8, 0, 8, 8)
        coluna.setSpacing(6)
        coluna.addWidget(self.filtro_do_projeto)
        coluna.addWidget(self.vazio_projeto, 1)
        return corpo

    def _criar_inspetor(self) -> QWidget:
        corpo = QWidget()
        corpo.setObjectName("painel")
        corpo.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.vazio_inspetor = EstadoVazio(self.tr("Nada selecionado"),
                                          self.tr("Selecione um traço, uma vista ou um cursor para ver e mudar as "
                                                  "propriedades dele aqui."),
                                          icone_nome="ajustes", compacto=True)
        coluna = QVBoxLayout(corpo)
        coluna.setContentsMargins(8, 0, 8, 8)
        coluna.addWidget(self.vazio_inspetor, 1)
        return corpo

    def _criar_painel_inferior(self) -> PainelComAbas:
        painel = PainelComAbas("painel_inferior")
        for titulo, vazio, texto, nome_icone in (
            (self.tr("Medidas"), self.tr("Sem medidas"),
             self.tr("Ligue os cursores ou selecione uma região do gráfico para medir."), "regua"),
            (self.tr("Tarefas"), self.tr("Nenhuma tarefa em andamento"),
             self.tr("As contas longas (pirâmides, espectros, exportações) aparecem aqui, com o progresso."),
             "relogio"),
            (self.tr("Avisos"), self.tr("Nenhum aviso"),
             self.tr("Os avisos das capturas abertas (sonda, faixa, integridade) aparecem aqui."), "alerta"),
        ):
            painel.addTab(EstadoVazio(vazio, texto, icone_nome=nome_icone, compacto=True), titulo)
        return painel

    def _criar_dock(self, nome: str, titulo: str, corpo: QWidget, area: Qt.DockWidgetArea, nome_da_acao: str,
                    *, com_titulo: bool = True) -> QDockWidget:
        """Um painel fixo no seu lado: não flutua nem muda de lugar (o layout fica previsível), mas recolhe e muda
        de tamanho. A ação de recolher entra em ``self.acoes``."""
        dock = QDockWidget(titulo, self)
        dock.setObjectName(nome)             # o saveState identifica os docks pelo nome
        # Só "fechável" (a ação de recolher fica desabilitada sem isso); o botão de fechar não aparece, porque o
        # título é nosso.
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        dock.setAllowedAreas(area)
        if com_titulo:
            dock.titulo = TituloDoPainel(titulo)
            dock.setTitleBarWidget(dock.titulo)
        else:
            dock.setTitleBarWidget(QWidget())     # sem barra de título: as abas são o topo
        dock.setWidget(corpo)
        self.addDockWidget(area, dock)
        atalhos = {"painel_projeto": "Ctrl+B", "painel_inspetor": "Ctrl+I", "painel_inferior": "Ctrl+J"}
        self._acao(nome_da_acao, self.tr("Mostrar ou recolher: {}").format(titulo), atalho=atalhos[nome_da_acao],
                   acao=dock.toggleViewAction())
        return dock

    def _criar_barra_de_status(self) -> None:
        barra = self.statusBar()
        barra.setSizeGripEnabled(False)
        self.status_fonte = QLabel(self.tr("Nenhuma captura aberta"))
        self.status_fonte.setObjectName("status_fonte")
        barra.addWidget(self.status_fonte, 1)
        self.status_tarefa = QLabel()
        self.status_tarefa.setObjectName("status_tarefa")
        barra.addPermanentWidget(self.status_tarefa)
        app = QApplication.instance()
        versao = QLabel(self.tr("versão {}").format(app.applicationVersion() or "dev"))
        versao.setObjectName("versao")
        barra.addPermanentWidget(versao)

    def _tema_mudou(self, tema: Tema) -> None:
        """O botão do tema mostra para onde ele leva: o sol no escuro, a lua no claro."""
        acao = self.acoes["alternar_tema"]
        acao.findChild(IconeDoTema).trocar("sol" if tema.escuro else "lua")
        acao.setToolTip(self.tr("Tema claro") if tema.escuro else self.tr("Tema escuro"))

    # ------------------------------------------------------------------ layout

    def salvar_layout(self) -> None:
        gravar(CHAVE_DA_GEOMETRIA, self.saveGeometry())
        gravar(CHAVE_DO_ESTADO, self.saveState(VERSAO_DO_LAYOUT))

    def restaurar_layout(self) -> bool:
        """Restaura o layout salvo; ``False`` (e o padrão) se não houver um, ou se for de outra versão ou inválido."""
        geometria, estado = ler_bytes(CHAVE_DA_GEOMETRIA), ler_bytes(CHAVE_DO_ESTADO)
        if geometria is not None:
            self.restoreGeometry(geometria)
        return estado is not None and self.restoreState(estado, VERSAO_DO_LAYOUT)

    def layout_padrao(self) -> None:
        """Os três painéis abertos, nas larguras do mockup."""
        for dock in (self.dock_projeto, self.dock_inspetor, self.dock_inferior):
            dock.show()
        self.resizeDocks([self.dock_projeto, self.dock_inspetor], [LARGURA_DO_PROJETO, LARGURA_DO_INSPETOR],
                         Qt.Orientation.Horizontal)
        self.resizeDocks([self.dock_inferior], [ALTURA_DO_PAINEL_INFERIOR], Qt.Orientation.Vertical)

    def showEvent(self, evento: QShowEvent) -> None:
        super().showEvent(evento)
        if self._primeira_exibicao:
            self._primeira_exibicao = False
            if not self._layout_restaurado:
                self.layout_padrao()

    def closeEvent(self, evento: QCloseEvent) -> None:
        self.salvar_layout()
        super().closeEvent(evento)

    def sizeHint(self) -> QSize:
        return QSize(*TAMANHO_INICIAL)
