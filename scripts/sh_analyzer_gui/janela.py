"""A janela do Estúdio (docs/gui-plan.md, 9.1; o mockup A1 em ``docs/gui-mockups/a1-estudio.html``).

As regiões:

* a **barra superior** (``componentes.barra_superior``), no lugar da barra de menus;
* o **Projeto** à esquerda e o **Inspetor** à direita, docks de altura inteira;
* as **vistas** no centro, em abas; sem vista aberta, o estado vazio diz como começar;
* o **painel de baixo** (medidas, tarefas, avisos), só embaixo das vistas;
* a **barra de status**.

**As ações** (``self.acoes``, pelo nome) são o ponto único de cada comando: o botão, o atalho e, depois, a paleta de
comandos (F1.8) disparam a mesma ``QAction``.

**O projeto** (``self.projeto``, ``modelo.objetos.Projeto``) tem a sua pilha de desfazer; a janela a liga a um
``QUndoGroup``, e o desfazer da barra segue o projeto aberto (:meth:`trocar_projeto`). A seleção
(``self.selecao``) é da janela e segue o projeto.

**O layout** (o tamanho da janela e dos painéis, e quais estão abertos) é salvo ao fechar e restaurado ao abrir
(``configuracao.py``). Ctrl+B, Ctrl+I e Ctrl+J recolhem o Projeto, o Inspetor e o painel de baixo.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
    QShowEvent,
    QUndoGroup,
    QUndoStack,
)
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QLabel,
    QMainWindow,
    QMenu,
    QStackedWidget,
    QTabWidget,
    QWidget,
)
from shiboken6 import isValid

from . import preferencias
from .areas.analise.area import AreaDeAnalise
from .areas.analise.arvore import PainelDoProjeto
from .areas.analise.inspetor import Inspetor
from .areas.analise.medidas import TabelaDeMedidas
from .componentes.avisos import ListaDeAvisos
from .componentes.barra_superior import BarraSuperior
from .componentes.basicos import Botao
from .componentes.painel import EstadoVazio, PainelComAbas, TituloDoPainel, botao_de_icone
from .componentes.paleta import DialogoDeAtalhos, PaletaDeComandos
from .componentes.tarefas import ListaDeTarefas
from .configuracao import gravar, ler_bytes
from .controle_do_projeto import ControleDoProjeto
from .modelo.objetos import Projeto, Vista
from .modelo.selecao import Selecao
from .servicos.fontes import ServicoDeFontes
from .servicos.materializar import ServicoDeMaterializacao
from .servicos.tarefas import GerenciadorDeTarefas
from .tema.aplicar import aparencia
from .tema.fontes import familias_disponiveis, fonte_escolhida
from .tema.icones import IconeDoTema
from .tema.tokens import Tema

TAMANHO_INICIAL = (1440, 900)
TAMANHO_MINIMO = (960, 600)
LADO_DA_MARCA = 72              # px da marca no estado vazio
LARGURA_DO_PROJETO = 264
LARGURA_DO_INSPETOR = 380
ALTURA_DO_PAINEL_INFERIOR = 200

VERSAO_DO_LAYOUT = 2      # 2: o inspetor mais largo (um layout salvo da 1 tinha ele estreito demais)
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

        self.grupo_desfazer = QUndoGroup(self)
        # Três threads: a pirâmide de uma captura, a materialização de um traço e as medidas não esperam uma pela
        # outra (a prévia dos traços transformados tem a sua, no serviço de materialização).
        self.tarefas = GerenciadorDeTarefas(threads=3, parent=self)
        self.servico_de_fontes = ServicoDeFontes(self.tarefas, parent=self)
        self.materializacoes = ServicoDeMaterializacao(self.tarefas, parent=self)
        self.projeto: Projeto | None = None
        self.selecao: Selecao | None = None
        self.acoes: dict[str, QAction] = {}
        self.controle = ControleDoProjeto(self)
        self._criar_acoes()

        self.barra = BarraSuperior(self.acoes["paleta"].shortcut())
        self.setMenuWidget(self.barra)
        self.barra.campo_paleta.clicked.connect(self.acoes["paleta"].trigger)
        self.barra.botao_desfazer.setDefaultAction(self.acoes["desfazer"])
        self.barra.botao_refazer.setDefaultAction(self.acoes["refazer"])
        self.barra.botao_tema.setDefaultAction(self.acoes["alternar_tema"])
        self.barra.botao_ajustes.setMenu(self._menu_de_ajustes())
        self.barra.definir_menu_do_projeto(self._menu_do_projeto())
        self.barra.botao_ajustes.setToolTip(self.tr("Ajustes"))
        IconeDoTema(self.barra.botao_ajustes, "ajustes")
        for indice, versao in ((1, "v0.11"), (2, "v0.10")):
            self.barra.areas.habilitar(indice, False, self.tr("Chega na {}").format(versao))

        self.setCentralWidget(self._criar_centro())
        self.dock_projeto = self._criar_dock("projeto", self.tr("Projeto"), self._criar_projeto(),
                                             Qt.DockWidgetArea.LeftDockWidgetArea, "painel_projeto")
        self.dock_projeto.titulo.adicionar_botao(self.acoes["abrir"])
        self.dock_inspetor = self._criar_dock("inspetor", self.tr("Inspetor"), self._criar_inspetor(),
                                              Qt.DockWidgetArea.RightDockWidgetArea, "painel_inspetor")
        self.painel_inferior = self._criar_painel_inferior()
        self.dock_inferior = self._criar_dock("inferior", self.tr("Painel de baixo"), self.painel_inferior,
                                              Qt.DockWidgetArea.BottomDockWidgetArea, "painel_inferior",
                                              com_titulo=False)
        self._criar_barra_de_status()
        self.area = AreaDeAnalise(self, self.painel_projeto, self.inspetor, self.avisos, self.status_fonte,
                                  self.status_integridade, self.vistas, self.tabela_de_medidas)
        self.setAcceptDrops(True)

        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou(aparencia().tema)
        self.trocar_projeto(Projeto())
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
                   acao=self.grupo_desfazer.createUndoAction(self, self.tr("Desfazer")))
        self._acao("refazer", self.tr("Refazer"), atalho=QKeySequence.StandardKey.Redo, icone="refazer",
                   acao=self.grupo_desfazer.createRedoAction(self, self.tr("Refazer")))
        # A dica do desfazer diz o que vai ser desfeito ("Desfazer Remover o traço (Ctrl+Z)").
        for nome in ("desfazer", "refazer"):
            self.acoes[nome].changed.connect(partial(_dica_com_atalho, self.acoes[nome]))
        self._acao("paleta", self.tr("Paleta de comandos"), atalho="Ctrl+K").triggered.connect(self.abrir_paleta)
        self._acao("atalhos", self.tr("Atalhos do teclado e do mouse"), atalho="Ctrl+/",
                   icone="livro").triggered.connect(self.mostrar_atalhos)
        self._acao("alternar_tema", self.tr("Alternar o tema claro e escuro"),
                   icone="sol").triggered.connect(preferencias.alternar_tema)
        controle = self.controle
        self._acao("abrir", self.tr("Abrir captura…"), atalho=QKeySequence.StandardKey.Open,
                   icone="pasta").triggered.connect(lambda: controle.abrir_arquivos())
        self._acao("novo_projeto", self.tr("Novo projeto"), atalho=QKeySequence.StandardKey.New,
                   icone="arquivo").triggered.connect(controle.novo)
        self._acao("abrir_projeto", self.tr("Abrir projeto…"), atalho="Ctrl+Shift+O",
                   icone="pasta").triggered.connect(lambda: controle.abrir())
        self._acao("salvar", self.tr("Salvar o projeto"), atalho=QKeySequence.StandardKey.Save,
                   icone="baixar").triggered.connect(controle.salvar)
        self._acao("salvar_como", self.tr("Salvar o projeto como…"),
                   atalho="Ctrl+Shift+S").triggered.connect(lambda: controle.salvar_como())
        self._acao("nova_vista", self.tr("Nova vista"), icone="mais").triggered.connect(lambda: self.area.nova_vista())
        self._acao("espectro", self.tr("Abrir o espectro da vista"), atalho="Ctrl+E",
                   icone="espectro").triggered.connect(lambda: self.area.abrir_espectro())
        self._acao("bandas", self.tr("Abrir as bandas IEC da vista"), atalho="Ctrl+Shift+B",
                   icone="grade").triggered.connect(lambda: self.area.abrir_analise("bandas"))
        self._acao("espectrograma", self.tr("Abrir o espectrograma da vista"), atalho="Ctrl+Shift+E",
                   icone="camadas").triggered.connect(lambda: self.area.abrir_analise("espectrograma"))
        self._acao("harmonicos", self.tr("Abrir os harmônicos da vista"), atalho="Ctrl+Shift+H",
                   icone="pulso").triggered.connect(lambda: self.area.abrir_analise("harmonicos"))
        a = self._acao("remover_selecionados", self.tr("Remover os traços selecionados"),
                       atalho=QKeySequence.StandardKey.Delete)
        a.triggered.connect(lambda: self.area.remover_selecionados())

    # ------------------------------------------------------------------ projeto

    @property
    def pilha(self) -> QUndoStack:
        """A pilha de desfazer do projeto aberto."""
        return self.projeto.pilha

    def trocar_projeto(self, projeto: Projeto) -> None:
        """Passa a mostrar ``projeto``: o desfazer, o nome na barra e no título, e uma seleção nova."""
        anterior = self.projeto
        if anterior is not None:
            anterior.modificadoMudou.disconnect(self._projeto_mudou)
            anterior.nomeMudou.disconnect(self._projeto_mudou)
            self.grupo_desfazer.removeStack(anterior.pilha)
        self.projeto = projeto
        if self.selecao is not None:
            self.selecao.deleteLater()
        self.selecao = Selecao(projeto, self)
        self.grupo_desfazer.addStack(projeto.pilha)
        self.grupo_desfazer.setActiveStack(projeto.pilha)
        projeto.modificadoMudou.connect(self._projeto_mudou)
        projeto.nomeMudou.connect(self._projeto_mudou)
        self._projeto_mudou()
        self.servico_de_fontes.acompanhar(projeto)
        self.area.acompanhar(projeto)

    def vista_ativa(self) -> Vista | None:
        """A vista da aba aberta: onde um canal novo é plotado."""
        return self.area.vista_ativa()

    def _projeto_mudou(self, *_) -> None:
        """O nome do projeto e o ponto das mudanças não salvas, na barra e no título da janela."""
        if not isValid(self) or self.projeto is None:
            return
        nome, modificado = self.projeto.nome, self.projeto.modificado
        self.barra.definir_projeto(nome, modificado)
        app = QApplication.instance()
        self.setWindowTitle(f"{nome}[*] — {app.applicationName() or 'SH-Analyzer'}")
        self.setWindowModified(modificado)

    def acoes_da_paleta(self) -> list[QAction]:
        """As ações que a paleta busca: as da janela, as da vista aberta (ajustar, voltar, cursores) e, com um traço no
        inspetor, as de adicionar uma etapa à cadeia dele."""
        acoes = list(self.acoes.values())
        vista = self.vistas.currentWidget()
        if vista is not None:
            acoes += [a for a in vista.actions() if a.text()]
        if self.inspetor.currentWidget() is self.inspetor.do_traco:
            acoes += self.inspetor.do_traco.processamento.acoes      # "Adicionar etapa: passa-altas"...
        return acoes

    def abrir_paleta(self) -> None:
        if not hasattr(self, "paleta"):
            self.paleta = PaletaDeComandos(self)
        self.paleta.abrir(self.acoes_da_paleta())

    def mostrar_atalhos(self) -> DialogoDeAtalhos:
        self.dialogo_de_atalhos = DialogoDeAtalhos(self.acoes_da_paleta(), self)
        self.dialogo_de_atalhos.show()
        return self.dialogo_de_atalhos

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

    def _menu_do_projeto(self) -> QMenu:
        menu = QMenu(self)
        menu.setObjectName("menu_projeto")
        menu.addAction(self.acoes["novo_projeto"])
        menu.addAction(self.acoes["abrir_projeto"])
        self.menu_recentes = menu.addMenu(self.tr("Abrir recente"))
        self.menu_capturas_recentes = menu.addMenu(self.tr("Capturas recentes"))
        menu.addSeparator()
        menu.addAction(self.acoes["salvar"])
        menu.addAction(self.acoes["salvar_como"])
        menu.aboutToShow.connect(self._preencher_recentes)
        return menu

    def _preencher_recentes(self) -> None:
        """Os projetos e as capturas recentes que ainda existem; um menu sem nenhum fica desabilitado."""
        for menu, recentes, abrir, nome in (
                (self.menu_recentes, self.controle.recentes(), self.controle.abrir, lambda c: c.stem),
                (self.menu_capturas_recentes, self.controle.recentes_capturas(),
                 lambda c: self.controle.abrir_capturas([c]), lambda c: c.name)):
            menu.clear()
            existentes = [c for c in recentes if c.is_file()]
            for caminho in existentes:
                a = menu.addAction(nome(caminho))
                a.setToolTip(str(caminho))
                a.triggered.connect(lambda _=False, c=caminho, f=abrir: f(c))
            menu.setEnabled(bool(existentes))

    def _marcar_tema_no_menu(self) -> None:
        self._acoes_de_tema[aparencia().modo].setChecked(True)

    # ------------------------------------------------------------------ regiões

    def _criar_centro(self) -> QWidget:
        """As abas das vistas e, sem nenhuma, o estado vazio no lugar delas."""
        self.vistas = QTabWidget()
        self.vistas.setObjectName("vistas")
        self.vistas.setDocumentMode(True)
        self.vistas.setTabsClosable(False)    # o botão de fechar de cada aba é nosso (areas.analise.area)
        self.vistas.setMovable(False)         # a ordem das abas é a das vistas no projeto
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
        self.painel_projeto = PainelDoProjeto(self.acoes["abrir"])
        self.filtro_do_projeto = self.painel_projeto.filtro
        return self.painel_projeto

    def _criar_inspetor(self) -> QWidget:
        self.inspetor = Inspetor()
        self.inspetor.do_traco.processamento.dialogos_de = lambda: self.controle.dialogos
        return self.inspetor

    def _criar_painel_inferior(self) -> PainelComAbas:
        painel = PainelComAbas("painel_inferior")
        self.tabela_de_medidas = TabelaDeMedidas()
        painel.addTab(self.tabela_de_medidas, self.tr("Medidas"))
        self.lista_de_tarefas = ListaDeTarefas(self.tarefas)
        painel.addTab(self.lista_de_tarefas, self.tr("Tarefas"))
        self.lista_de_tarefas.contagemMudou.connect(self._contagem_de_tarefas)
        self.avisos = ListaDeAvisos()
        painel.addTab(self.avisos, self.tr("Avisos"))
        self.avisos.contagemMudou.connect(self._contagem_de_avisos)
        return painel

    def _contagem_de_tarefas(self, n: int) -> None:
        if isValid(self.painel_inferior):
            self.painel_inferior.definir_contagem(ABA_TAREFAS, n, "acento")
            ativas = self.tarefas.visiveis
            self.status_tarefa.setText(ativas[0].nome + (f" (+{len(ativas) - 1})" if len(ativas) > 1 else "")
                                       if ativas else "")

    def _contagem_de_avisos(self, n: int, nivel: str) -> None:
        if isValid(self.painel_inferior):
            self.painel_inferior.definir_contagem(ABA_AVISOS, n, {"info": "acento"}.get(nivel, nivel))

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
        acao = self._acao(nome_da_acao, self.tr("Mostrar ou recolher o painel: {}").format(titulo),
                          atalho=atalhos[nome_da_acao], acao=dock.toggleViewAction())
        acao.setText(self.tr("Mostrar ou recolher o painel: {}").format(titulo))
        return dock

    def _criar_barra_de_status(self) -> None:
        barra = self.statusBar()
        barra.setSizeGripEnabled(False)
        self.status_fonte = QLabel(self.tr("Nenhuma captura aberta"))
        self.status_fonte.setObjectName("status_fonte")
        barra.addWidget(self.status_fonte)
        self.status_integridade = QLabel()
        self.status_integridade.setObjectName("status_integridade")
        barra.addWidget(self.status_integridade, 1)
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

    def estado(self) -> QByteArray:
        """O estado dos painéis (quais abertos, os tamanhos), para guardar no projeto."""
        return self.saveState(VERSAO_DO_LAYOUT)

    def restaurar_estado(self, estado: QByteArray) -> bool:
        return self.restoreState(estado, VERSAO_DO_LAYOUT)

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
        if not self.controle.pode_descartar():
            evento.ignore()
            return
        self.salvar_layout()
        self.tarefas.encerrar()          # nenhuma thread rodando depois da janela
        self.materializacoes.encerrar()
        super().closeEvent(evento)

    # ------------------------------------------------------------------ arrastar e soltar

    @staticmethod
    def _arquivos_soltos(evento) -> list[Path]:
        dados = evento.mimeData()
        if not dados.hasUrls():
            return []
        return [Path(u.toLocalFile()) for u in dados.urls() if u.isLocalFile()]

    def dragEnterEvent(self, evento: QDragEnterEvent) -> None:
        if self._arquivos_soltos(evento):
            evento.acceptProposedAction()

    def dropEvent(self, evento: QDropEvent) -> None:
        caminhos = self._arquivos_soltos(evento)
        if caminhos:
            evento.acceptProposedAction()
            self.controle.abrir_arquivos(caminhos)

    def sizeHint(self) -> QSize:
        return QSize(*TAMANHO_INICIAL)
