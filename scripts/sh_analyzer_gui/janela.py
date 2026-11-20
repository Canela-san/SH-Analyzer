"""A janela do aplicativo (docs/gui-plan.md, 9.1): a barra superior, as áreas e a barra de status.

* a **barra superior** (``componentes.barra_superior``), no lugar da barra de menus, com as áreas e o chip da placa
  (um clique nele leva à Aquisição);
* **as áreas**, uma página cada (``self.paginas``; :meth:`mostrar_area`):

  * a **Análise**, o Estúdio (o mockup A1 em ``docs/gui-mockups/a1-estudio.html``), numa ``QMainWindow`` própria
    (``self.estudio``) com os painéis dela: o **Projeto** à esquerda e o **Inspetor** à direita, docks de altura
    inteira; as **vistas** no centro, em abas (sem vista aberta, o estado vazio diz como começar); o **painel de
    baixo** (medidas, tarefas, avisos), só embaixo das vistas. Os painéis são da Análise: as outras áreas ocupam a
    janela inteira, e voltar à Análise os traz como estavam;
  * a **Aquisição** (``areas/aquisicao``, o B1), com a placa conectada (``self.conexao_da_placa``);
  * as **Figuras** (``areas/figuras``, o F1): as figuras do projeto, a página no tamanho real e as propriedades; o
    botão de imagem ao lado das abas da Análise faz da vista aberta uma figura (``figura_da_vista_ativa``);

* a **barra de status**: a parte de cada área (a fonte e a integridade na Análise; a figura escolhida nas Figuras; a
  conexão e o enlace na Aquisição), a tarefa em andamento e a versão.

**Os atalhos de uma área valem só com ela à vista:** as ações da Análise (as vistas, os painéis, remover traços com
Delete) moram no Estúdio, e o Qt só as dispara com ele visível; a paleta também só as oferece ali. Abrir uma captura ou
um projeto, de qualquer área, leva à Análise.

**As ações** (``self.acoes``, pelo nome) são o ponto único de cada comando: o botão, o atalho e, depois, a paleta de
comandos (F1.8) disparam a mesma ``QAction``.

**O projeto** (``self.projeto``, ``modelo.objetos.Projeto``) tem a sua pilha de desfazer; a janela a liga a um
``QUndoGroup``, e o desfazer da barra segue o projeto aberto (:meth:`trocar_projeto`). A seleção
(``self.selecao``) é da janela e segue o projeto.

**O layout** (o tamanho da janela e dos painéis, e quais estão abertos) é salvo ao fechar e restaurado ao abrir
(``configuracao.py``). Ctrl+B, Ctrl+I e Ctrl+J recolhem o Projeto, o Inspetor e o painel de baixo; a seta de cada
painel também, e o painel recolhido deixa a aba dele na borda da área central, para abri-lo de novo
(``componentes.painel.TrilhoDoPainel``).
"""

from __future__ import annotations

import logging
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
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QStackedWidget,
    QToolButton,
    QWidget,
)
from shiboken6 import isValid

from . import preferencias
from .areas.analise.area import AreaDeAnalise
from .areas.analise.arvore import PainelDoProjeto
from .areas.analise.inspetor import Inspetor
from .areas.analise.medidas import TabelaDeMedidas
from .areas.aquisicao.area import AreaDeAquisicao
from .areas.aquisicao.barra_de_status import StatusDaPlaca
from .areas.aquisicao.textos import resumo
from .areas.configuracoes import DialogoDeConfiguracoes
from .areas.figuras.area import AreaDeFiguras
from .componentes.avisos import ListaDeAvisos
from .componentes.barra_superior import BarraSuperior
from .componentes.basicos import Botao
from .componentes.dialogo_de_erro import DialogoDeErro
from .componentes.grade_de_vistas import DISPOSICOES, AbasEmGrade, nome_da_disposicao
from .componentes.painel import EstadoVazio, PainelComAbas, TituloDoPainel, TrilhoDoPainel, botao_de_icone
from .componentes.paleta import DialogoDeAtalhos, PaletaDeComandos
from .componentes.tarefas import ListaDeTarefas
from .configuracao import gravar, ler_bytes
from .controle_do_projeto import ControleDoProjeto
from .dados.cache import CacheDePiramides
from .dados.materializacao import CacheDeMaterializacoes
from .modelo.objetos import Projeto, Vista
from .modelo.selecao import Selecao
from .registro import caminho_do_log
from .servicos.conexao_da_placa import ConexaoDaPlaca
from .servicos.erros import ErroInesperado, relator
from .servicos.fontes import ServicoDeFontes
from .servicos.materializar import ServicoDeMaterializacao
from .servicos.placa import ServicoDaPlaca
from .servicos.saude_da_placa import SaudeDaPlaca
from .servicos.tarefas import GerenciadorDeTarefas
from .servicos.transferencias import TransferenciasDaPlaca
from .tema.aplicar import aparencia
from .tema.icones import IconeDoTema
from .tema.tokens import Tema

ANALISES_DO_MENU = (("espectro", "bandas", "espectrograma", "harmonicos"),
                    ("xy", "histograma", "eventos", "qualidade", "transferencia", "metricas", "instrumento"),
                    ("perfis_de_sonda", "aliasing", "alinhar"))
"""O menu "Análises" do canto das abas, em grupos (a frequência; as análises da Fase 7; as ferramentas)."""

log = logging.getLogger(__name__)

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
AREA_ANALISE, AREA_FIGURAS, AREA_AQUISICAO = range(3)


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
        # A Análise numa QMainWindow própria, com os painéis dela: as outras áreas ocupam a janela inteira.
        self.estudio = QMainWindow()
        self.estudio.setObjectName("estudio")
        self.estudio.setWindowFlags(Qt.WindowType.Widget)
        self.estudio.setDockNestingEnabled(False)
        # O Projeto e o Inspetor ocupam a altura inteira; o painel de baixo fica só embaixo das vistas.
        self.estudio.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.estudio.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)

        self.grupo_desfazer = QUndoGroup(self)
        # Três threads: a pirâmide de uma captura, a materialização de um traço e as medidas não esperam uma pela
        # outra (a prévia dos traços transformados tem a sua, no serviço de materialização).
        self.tarefas = GerenciadorDeTarefas(threads=3, parent=self)
        # Os caches nas pastas e nos limites das configurações (a tela de configurações os troca na hora).
        self.servico_de_fontes = ServicoDeFontes(self.tarefas, parent=self, cache=CacheDePiramides(
            preferencias.pasta_do_cache("piramides"), preferencias.limite("piramides")))
        self.materializacoes = ServicoDeMaterializacao(self.tarefas, parent=self, cache=CacheDeMaterializacoes(
            preferencias.pasta_do_cache("materializacoes"), preferencias.limite("materializacoes")))
        # A placa: as chamadas no laço asyncio da thread própria, que nasce na primeira chamada (a Aquisição).
        self.placa = ServicoDaPlaca(parent=self)
        self.conexao_da_placa = ConexaoDaPlaca(self.placa, parent=self)
        self.saude_da_placa = SaudeDaPlaca(self.conexao_da_placa, parent=self)
        self.transferencias_da_placa = TransferenciasDaPlaca(self.conexao_da_placa, self.saude_da_placa, parent=self)
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
        self.barra.botao_ajustes.setDefaultAction(self.acoes["configuracoes"])
        self.barra.definir_menu_do_projeto(self._menu_do_projeto())
        self.barra.areaMudou.connect(self.mostrar_area)
        self.barra.chip_placa.clicked.connect(lambda: self.mostrar_area(AREA_AQUISICAO))

        self.estudio.setCentralWidget(self._criar_centro())
        self.dock_projeto = self._criar_dock("projeto", self.tr("Projeto"), self._criar_projeto(),
                                             Qt.DockWidgetArea.LeftDockWidgetArea, "painel_projeto")
        self.dock_projeto.titulo.adicionar_botao(self.acoes["abrir"])
        self.dock_inspetor = self._criar_dock("inspetor", self.tr("Inspetor"), self._criar_inspetor(),
                                              Qt.DockWidgetArea.RightDockWidgetArea, "painel_inspetor")
        self.painel_inferior = self._criar_painel_inferior()
        self.dock_inferior = self._criar_dock("inferior", self.tr("Painel de baixo"), self.painel_inferior,
                                              Qt.DockWidgetArea.BottomDockWidgetArea, "painel_inferior",
                                              com_titulo=False)
        self._criar_recolher_e_trilhos()
        self._criar_barra_de_status()
        self.area = AreaDeAnalise(self, self.painel_projeto, self.inspetor, self.avisos, self.status_fonte,
                                  self.status_integridade, self.vistas, self.tabela_de_medidas)
        self.aquisicao = AreaDeAquisicao(
            self.conexao_da_placa, self.saude_da_placa, lambda: self.controle.dialogos, self.transferencias_da_placa,
            abrir_na_analise=lambda caminhos: self._na_analise(self.controle.abrir_capturas(caminhos)),
            abrir_no_projeto=lambda caminhos: self.controle.abrir_capturas(caminhos),
            mostrar_na_analise=self._mostrar_na_analise)
        self.aquisicao.caderno.mudou.connect(self.area.cadernos_mudaram)
        self.figuras = AreaDeFiguras(self.area, self.tarefas, self.materializacoes, vista_ativa=self.vista_ativa,
                                     dialogos_de=lambda: self.controle.dialogos)
        self.figuras.resumoMudou.connect(self.status_da_figura.setText)
        self.paginas = QStackedWidget()
        self.paginas.setObjectName("paginas_das_areas")
        self._paginas_das_areas = {AREA_ANALISE: self.estudio, AREA_FIGURAS: self.figuras,
                                   AREA_AQUISICAO: self.aquisicao}
        for pagina in self._paginas_das_areas.values():
            self.paginas.addWidget(pagina)
        self.setCentralWidget(self.paginas)
        self.conexao_da_placa.mudou.connect(self._placa_mudou)
        self.saude_da_placa.mudou.connect(self._placa_mudou)
        self._placa_mudou()
        self.setAcceptDrops(True)

        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou(aparencia().tema)
        self.trocar_projeto(Projeto())
        self._layout_restaurado = self.restaurar_layout()
        self._primeira_exibicao = True
        # Os erros inesperados de qualquer thread (servicos/erros.py). Pela fila sempre: um erro num paintEvent não
        # abre uma janela no meio da pintura.
        self.dialogo_de_erro: DialogoDeErro | None = None
        relator().erroInesperado.connect(self._erro_inesperado, Qt.ConnectionType.QueuedConnection)

    # ------------------------------------------------------------------ ações

    def _acao(self, nome: str, texto: str, *, atalho: QKeySequence | str | None = None, icone: str | None = None,
              dica: str | None = None, acao: QAction | None = None, da_analise: bool = False) -> QAction:
        """Registra uma ação pelo nome (``self.acoes``) e a liga à janela, para o atalho valer em qualquer região.
        ``da_analise``: a ação mora no Estúdio, e o atalho vale só com a Análise à vista (o Qt não dispara o atalho de
        uma ação cujos widgets estão escondidos)."""
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
        (self.estudio if da_analise else self).addAction(a)
        if da_analise:
            self._acoes_da_analise.add(nome)
        self.acoes[nome] = a
        return a

    def _criar_acoes(self) -> None:
        self._acoes_da_analise: set[str] = set()
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
        self._acao("configuracoes", self.tr("Configurações…"), atalho="Ctrl+,",
                   icone="ajustes").triggered.connect(lambda: self.abrir_configuracoes())
        controle = self.controle
        self._acao("abrir", self.tr("Abrir captura…"), atalho=QKeySequence.StandardKey.Open,
                   icone="pasta").triggered.connect(lambda: self._na_analise(controle.abrir_arquivos()))
        self._acao("novo_projeto", self.tr("Novo projeto"), atalho=QKeySequence.StandardKey.New,
                   icone="arquivo").triggered.connect(controle.novo)
        self._acao("abrir_projeto", self.tr("Abrir projeto…"), atalho="Ctrl+Shift+O",
                   icone="pasta").triggered.connect(lambda: self._na_analise(controle.abrir()))
        self._acao("salvar", self.tr("Salvar o projeto"), atalho=QKeySequence.StandardKey.Save,
                   icone="baixar").triggered.connect(controle.salvar)
        self._acao("salvar_como", self.tr("Salvar o projeto como…"),
                   atalho="Ctrl+Shift+S").triggered.connect(lambda: controle.salvar_como())
        self._acao("nova_vista", self.tr("Nova vista"), icone="mais",
                   da_analise=True).triggered.connect(lambda: self.area.nova_vista())
        self._acao("figura_da_vista", self.tr("Fazer uma figura com a vista"), icone="imagem",
                   dica=self.tr("Fazer uma figura com a vista (a área Figuras)"),
                   da_analise=True).triggered.connect(self.figura_da_vista_ativa)
        self._acao("exportar_dados", self.tr("Exportar os dados da vista…"), icone="baixar",
                   dica=self.tr("Exportar os dados da vista (CSV, HDF5, MAT ou NPZ)"),
                   da_analise=True).triggered.connect(lambda: self.area.exportar_dados())
        self._acao("fechar_vista", self.tr("Fechar a vista"), atalho="Ctrl+W", icone="x",
                   da_analise=True).triggered.connect(lambda: self.area.fechar_vista_ativa())
        self._acao("espectro", self.tr("Abrir o espectro da vista"), atalho="Ctrl+E", icone="espectro",
                   da_analise=True).triggered.connect(lambda: self.area.abrir_espectro())
        self._acao("bandas", self.tr("Abrir as bandas IEC da vista"), atalho="Ctrl+Shift+B", icone="grade",
                   da_analise=True).triggered.connect(lambda: self.area.abrir_analise("bandas"))
        self._acao("espectrograma", self.tr("Abrir o espectrograma da vista"), atalho="Ctrl+Shift+E",
                   icone="camadas", da_analise=True).triggered.connect(lambda: self.area.abrir_analise("espectrograma"))
        self._acao("harmonicos", self.tr("Abrir os harmônicos da vista"), atalho="Ctrl+Shift+H", icone="pulso",
                   da_analise=True).triggered.connect(lambda: self.area.abrir_analise("harmonicos"))
        self._acao("xy", self.tr("Abrir o XY e a potência da vista"), icone="mira",
                   dica=self.tr("Um traço contra outro (o laço V × I) e a potência pela IEEE 1459"),
                   da_analise=True).triggered.connect(lambda: self.area.abrir_analise("xy"))
        self._acao("histograma", self.tr("Abrir o histograma e as estatísticas da vista"), icone="regua",
                   dica=self.tr("A distribuição do traço, a saturação do ADC e as estatísticas do trecho"),
                   da_analise=True).triggered.connect(lambda: self.area.abrir_analise("histograma"))
        self._acao("perfis_de_sonda", self.tr("Abrir os perfis de sonda"), icone="sonda",
                   dica=self.tr("Os perfis de sonda: o Bode de cada um e qual perfil cada canal usa (ES-07)"),
                   da_analise=True).triggered.connect(lambda: self.area.abrir_perfis())
        self._acao("alinhar", self.tr("Alinhar o traço selecionado a outro…"), icone="relogio",
                   dica=self.tr("O deslocamento no tempo que alinha o traço a outro da vista (TR-07)"),
                   da_analise=True).triggered.connect(lambda: self.area.alinhar())
        # A grade das vistas (AN-09): as disposições, uma de cada vez, e os eixos ligados entre as células.
        self.grupo_das_disposicoes = QActionGroup(self)
        for d in DISPOSICOES:
            a = self._acao(f"disposicao_{d}", self.tr("Vistas: {}").format(nome_da_disposicao(d).lower()),
                           icone="disposicao", da_analise=True)
            a.setCheckable(True)
            a.setChecked(d == "uma")
            self.grupo_das_disposicoes.addAction(a)
            a.triggered.connect(lambda _=False, d=d: self.area.definir_disposicao(d))
        a = self._acao("ligar_eixos", self.tr("Ligar os eixos das vistas da grade"), icone="link",
                       dica=self.tr("As vistas de tempo da grade andam juntas no tempo, e as de espectro na "
                                    "frequência"), da_analise=True)
        a.setCheckable(True)
        a.setChecked(True)
        a.toggled.connect(lambda ligar: self.area.ligar_os_eixos(ligar))
        a = self._acao("remover_selecionados", self.tr("Remover os traços selecionados"),
                       atalho=QKeySequence.StandardKey.Delete, da_analise=True)
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
        self.aquisicao.acompanhar(projeto)
        self.figuras.acompanhar(projeto)

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
        acoes = [a for nome, a in self.acoes.items()
                 if nome not in self._acoes_da_analise or self.area_atual == AREA_ANALISE]
        if self.area_atual != AREA_ANALISE:
            return acoes
        vista = self.vistas.currentWidget()
        if vista is not None:
            acoes += [a for a in vista.actions() if a.text()]
        if self.inspetor.currentWidget() is self.inspetor.do_traco:
            acoes += self.inspetor.do_traco.processamento.acoes      # "Adicionar etapa: passa-altas"...
        ativa = self.inspetor.vista_ativa
        if ativa is not None and ativa.tipo == "espectro":
            acoes += self.inspetor.da_vista.espectro.acoes           # "Aplicar o preset IEC 61000-4-7"
        return acoes

    def abrir_paleta(self) -> None:
        if not hasattr(self, "paleta"):
            self.paleta = PaletaDeComandos(self)
        self.paleta.abrir(self.acoes_da_paleta())

    def abrir_configuracoes(self, secao: str | None = None) -> DialogoDeConfiguracoes:
        """A tela de configurações (uma só por janela, não modal), na ``secao`` pedida (ou onde estava)."""
        dialogo = getattr(self, "dialogo_de_configuracoes", None)
        if dialogo is None or not isValid(dialogo):
            dialogo = self.dialogo_de_configuracoes = DialogoDeConfiguracoes(self)
        if secao is not None:
            dialogo.mostrar_secao(secao)
        dialogo.show()
        dialogo.raise_()
        dialogo.activateWindow()
        return dialogo

    def aplicar_cache(self) -> None:
        """A pasta e os limites do cache das configurações, nos dois serviços (o limite menor apaga na hora os
        menos usados, nunca o que está aberto)."""
        self.servico_de_fontes.definir_cache(preferencias.pasta_do_cache("piramides"), preferencias.limite("piramides"))
        self.materializacoes.definir_cache(preferencias.pasta_do_cache("materializacoes"),
                                           preferencias.limite("materializacoes"))

    def mostrar_atalhos(self) -> DialogoDeAtalhos:
        self.dialogo_de_atalhos = DialogoDeAtalhos(self.acoes_da_paleta(), self)
        self.dialogo_de_atalhos.show()
        return self.dialogo_de_atalhos

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
                a.triggered.connect(lambda _=False, c=caminho, f=abrir: self._na_analise(f(c)))
            menu.setEnabled(bool(existentes))

    # ------------------------------------------------------------------ regiões

    def _criar_centro(self) -> QWidget:
        """As abas das vistas e, sem nenhuma, o estado vazio no lugar delas."""
        self.vistas = AbasEmGrade()
        self.vistas.setObjectName("vistas")
        self.vistas.setDocumentMode(True)
        self.vistas.setTabsClosable(False)    # o botão de fechar de cada aba é nosso (areas.analise.area)
        self.vistas.setMovable(False)         # a ordem das abas é a das vistas no projeto
        canto = QWidget()
        botoes_do_canto = QHBoxLayout(canto)
        botoes_do_canto.setContentsMargins(0, 0, 0, 0)
        botoes_do_canto.setSpacing(0)
        self.botao_figura_da_vista = botao_de_icone(self.acoes["figura_da_vista"])
        self.botao_figura_da_vista.setObjectName("figura_da_vista")
        botoes_do_canto.addWidget(self.botao_figura_da_vista)
        self.botao_exportar_dados = botao_de_icone(self.acoes["exportar_dados"])
        self.botao_exportar_dados.setObjectName("exportar_dados_da_vista")
        botoes_do_canto.addWidget(self.botao_exportar_dados)
        self.botao_disposicao = QToolButton()
        self.botao_disposicao.setObjectName("disposicao_das_vistas")
        self.botao_disposicao.setProperty("variante", "fantasma")
        self.botao_disposicao.setAutoRaise(True)
        self.botao_disposicao.setIconSize(QSize(16, 16))
        self.botao_disposicao.setFixedSize(QSize(28, 28))
        self.botao_disposicao.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.botao_disposicao.setToolTip(self.tr("A disposição das vistas: uma, duas, três ou quatro de cada vez"))
        IconeDoTema(self.botao_disposicao, "disposicao", "texto2")
        menu = QMenu(self.botao_disposicao)
        for d in DISPOSICOES:
            menu.addAction(self.acoes[f"disposicao_{d}"])
        menu.addSeparator()
        menu.addAction(self.acoes["ligar_eixos"])
        self.botao_disposicao.setMenu(menu)
        botoes_do_canto.addWidget(self.botao_disposicao)
        self.botao_analises = QToolButton()
        self.botao_analises.setObjectName("analises_da_vista")
        self.botao_analises.setProperty("variante", "fantasma")
        self.botao_analises.setAutoRaise(True)
        self.botao_analises.setIconSize(QSize(16, 16))
        self.botao_analises.setFixedSize(QSize(28, 28))
        self.botao_analises.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.botao_analises.setToolTip(self.tr("As análises da vista de tempo: o espectro, as bandas, os harmônicos, "
                                               "o XY, o histograma…"))
        IconeDoTema(self.botao_analises, "pulso", "texto2")
        self.menu_de_analises = QMenu(self.botao_analises)
        for grupo in ANALISES_DO_MENU:
            for nome in grupo:
                if nome in self.acoes:
                    self.menu_de_analises.addAction(self.acoes[nome])
            self.menu_de_analises.addSeparator()
        self.botao_analises.setMenu(self.menu_de_analises)
        botoes_do_canto.addWidget(self.botao_analises)
        botoes_do_canto.addWidget(botao_de_icone(self.acoes["nova_vista"]))
        self.vistas.celulasMudaram.connect(
            lambda: self.acoes[f"disposicao_{self.vistas.disposicao}"].setChecked(True))
        self.vistas.setCornerWidget(canto, Qt.Corner.TopRightCorner)
        self.vistas.currentChanged.connect(self._acoes_da_vista)
        self.acoes["figura_da_vista"].setEnabled(False)
        self.acoes["exportar_dados"].setEnabled(False)

        abrir = Botao(self.tr("Abrir captura…"), "primario", "pasta")
        abrir.setObjectName("botao_abrir_central")
        abrir.clicked.connect(self.acoes["abrir"].trigger)
        abrir.setEnabled(self.acoes["abrir"].isEnabled())
        self.acoes["abrir"].enabledChanged.connect(abrir.setEnabled)
        app = QApplication.instance()
        self.vazio_central = EstadoVazio(
            self.tr("Abra uma captura para começar"),
            self.tr("Escolha uma captura (.bin, ou o .csv e o .h5 do adc_tool) ou arraste-a para esta janela. As "
                    "capturas abertas aparecem no painel do projeto, com os canais prontos para plotar."),
            imagem=app.windowIcon().pixmap(LADO_DA_MARCA, LADO_DA_MARCA), botao=abrir, largura_do_texto=440)
        self.vazio_central.simbolo.setObjectName("marca")

        self.centro = QStackedWidget()
        self.centro.setObjectName("area_central")
        self.centro.addWidget(self.vazio_central)
        self.centro.addWidget(self.vistas)
        self.vistas.currentChanged.connect(self._atualizar_centro)
        self._atualizar_centro()
        # Em volta, os trilhos dos painéis recolhidos (postos depois dos painéis: _criar_recolher_e_trilhos).
        conteiner = QWidget()
        conteiner.setObjectName("centro_com_trilhos")
        conteiner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._grade_central = QGridLayout(conteiner)
        self._grade_central.setContentsMargins(0, 0, 0, 0)
        self._grade_central.setSpacing(0)
        self._grade_central.addWidget(self.centro, 0, 1)
        self._grade_central.setRowStretch(0, 1)
        self._grade_central.setColumnStretch(1, 1)
        return conteiner

    def _criar_recolher_e_trilhos(self) -> None:
        """Recolher e abrir os painéis (componentes/painel.py): a seta de cada um e o trilho que ele deixa na borda da
        área central quando recolhido. Tudo passa pela ação de mostrar ou recolher do painel (Ctrl+B, Ctrl+I, Ctrl+J),
        e o trilho aparece e some com ela (também quando o layout salvo é restaurado)."""
        self.trilhos: dict[str, TrilhoDoPainel] = {}
        for dock, lado, recolhe, abre in ((self.dock_projeto, "esquerda", "esquerda", "direita"),
                                          (self.dock_inspetor, "direita", "direita", "esquerda")):
            alternar = dock.toggleViewAction()
            atalho = alternar.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            recolher = QAction(self.tr("Recolher o painel"), dock)
            recolher.setObjectName(f"recolher_{dock.objectName()}")
            recolher.setToolTip(self.tr("Recolher o painel ({})").format(atalho))
            recolher.triggered.connect(dock.hide)
            IconeDoTema(recolher, recolhe)
            dock.titulo.adicionar_botao(recolher)
            trilho = TrilhoDoPainel(lado)
            trilho.adicionar_aba_vertical(dock.windowTitle(), abre, dock.show,
                                          self.tr("Abrir o painel: {} ({})").format(dock.windowTitle(), atalho))
            self.trilhos[lado] = trilho
        painel, dock = self.painel_inferior, self.dock_inferior
        atalho = dock.toggleViewAction().shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        recolher = QAction(self.tr("Recolher o painel de baixo"), painel)
        recolher.setObjectName("recolher_inferior")
        recolher.setToolTip(self.tr("Recolher o painel de baixo ({})").format(atalho))
        recolher.triggered.connect(dock.hide)
        painel.setCornerWidget(botao_de_icone(recolher, "baixo"), Qt.Corner.TopRightCorner)
        trilho = TrilhoDoPainel("baixo")
        for i in range(painel.count()):
            trilho.adicionar_aba(painel.tabText(i), lambda _=False, i=i: self.abrir_painel_de_baixo(i),
                                 self.tr("Abrir o painel de baixo em {}").format(painel.tabText(i)))
            n, nivel = painel.contagens.get(i, (0, "neutro"))
            trilho.definir_contagem(i, n, nivel)
        painel.contagemMudou.connect(trilho.definir_contagem)
        abrir = QAction(self.tr("Abrir o painel de baixo"), trilho)
        abrir.setToolTip(self.tr("Abrir o painel de baixo ({})").format(atalho))
        abrir.triggered.connect(dock.show)
        trilho.adicionar_botao(abrir, "cima")
        self.trilhos["baixo"] = trilho
        self._grade_central.addWidget(self.trilhos["esquerda"], 0, 0, 2, 1)
        self._grade_central.addWidget(self.trilhos["direita"], 0, 2, 2, 1)
        self._grade_central.addWidget(self.trilhos["baixo"], 1, 1)
        for dock, lado in ((self.dock_projeto, "esquerda"), (self.dock_inspetor, "direita"),
                           (self.dock_inferior, "baixo")):
            alternar = dock.toggleViewAction()
            self.trilhos[lado].setVisible(not alternar.isChecked())
            alternar.toggled.connect(lambda aberto, t=self.trilhos[lado]: t.setVisible(not aberto))

    def abrir_painel_de_baixo(self, indice: int) -> None:
        """Abre o painel de baixo na página ``indice`` (a aba do trilho)."""
        self.dock_inferior.show()
        self.painel_inferior.setCurrentIndex(indice)

    def _acoes_da_vista(self, _indice: int = -1) -> None:
        """A figura e a exportação dos dados valem para as vistas de dados (a dos perfis de sonda não tem os dois)."""
        from .areas.figuras.area import TIPOS_COM_FIGURA

        vista = self.vista_ativa() if getattr(self, "area", None) is not None else None
        self.acoes["figura_da_vista"].setEnabled(vista is not None and vista.tipo in TIPOS_COM_FIGURA)
        self.acoes["exportar_dados"].setEnabled(vista is not None and vista.tipo != "sonda")

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
        dock = QDockWidget(titulo, self.estudio)
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
        self.estudio.addDockWidget(area, dock)
        atalhos = {"painel_projeto": "Ctrl+B", "painel_inspetor": "Ctrl+I", "painel_inferior": "Ctrl+J"}
        acao = self._acao(nome_da_acao, self.tr("Mostrar ou recolher o painel: {}").format(titulo),
                          atalho=atalhos[nome_da_acao], acao=dock.toggleViewAction(), da_analise=True)
        acao.setText(self.tr("Mostrar ou recolher o painel: {}").format(titulo))
        return dock

    def _criar_barra_de_status(self) -> None:
        barra = self.statusBar()
        barra.setSizeGripEnabled(False)
        # A parte de cada área: a fonte e a integridade na Análise; a placa na Aquisição.
        self.status_fonte = QLabel(self.tr("Nenhuma captura aberta"))
        self.status_fonte.setObjectName("status_fonte")
        self.status_integridade = QLabel()
        self.status_integridade.setObjectName("status_integridade")
        da_analise = QWidget()
        linha = QHBoxLayout(da_analise)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(0)
        linha.addWidget(self.status_fonte)
        linha.addWidget(self.status_integridade, 1)
        self.status_da_placa = StatusDaPlaca(self.conexao_da_placa)
        self.status_por_area = QStackedWidget()
        self.status_por_area.setObjectName("status_por_area")
        self.status_da_figura = QLabel()
        self.status_da_figura.setObjectName("status_da_figura")
        self.status_por_area.addWidget(da_analise)
        self.status_por_area.addWidget(self.status_da_placa)
        self.status_por_area.addWidget(self.status_da_figura)
        barra.addWidget(self.status_por_area, 1)
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
        """O estado dos painéis da Análise (quais abertos, os tamanhos), para guardar no projeto."""
        return self.estudio.saveState(VERSAO_DO_LAYOUT)

    def restaurar_estado(self, estado: QByteArray) -> bool:
        return self.estudio.restoreState(estado, VERSAO_DO_LAYOUT)

    def salvar_layout(self) -> None:
        gravar(CHAVE_DA_GEOMETRIA, self.saveGeometry())
        gravar(CHAVE_DO_ESTADO, self.estudio.saveState(VERSAO_DO_LAYOUT))

    def restaurar_layout(self) -> bool:
        """Restaura o layout salvo; ``False`` (e o padrão) se não houver um, ou se for de outra versão ou inválido."""
        geometria, estado = ler_bytes(CHAVE_DA_GEOMETRIA), ler_bytes(CHAVE_DO_ESTADO)
        if geometria is not None:
            self.restoreGeometry(geometria)
        return estado is not None and self.estudio.restoreState(estado, VERSAO_DO_LAYOUT)

    def layout_padrao(self) -> None:
        """Os três painéis da Análise abertos, nas larguras do mockup."""
        for dock in (self.dock_projeto, self.dock_inspetor, self.dock_inferior):
            dock.show()
        self.estudio.resizeDocks([self.dock_projeto, self.dock_inspetor], [LARGURA_DO_PROJETO, LARGURA_DO_INSPETOR],
                                 Qt.Orientation.Horizontal)
        self.estudio.resizeDocks([self.dock_inferior], [ALTURA_DO_PAINEL_INFERIOR], Qt.Orientation.Vertical)

    # ------------------------------------------------------------------ as áreas

    @property
    def area_atual(self) -> int:
        pagina = self.paginas.currentWidget()
        return next(i for i, p in self._paginas_das_areas.items() if p is pagina)

    def mostrar_area(self, indice: int) -> None:
        """Mostra a área ``indice`` (``AREA_ANALISE``, ``AREA_FIGURAS``, ``AREA_AQUISICAO``): a página dela, a parte
        dela na barra de status e o seletor da barra superior."""
        pagina = self._paginas_das_areas.get(indice)
        if pagina is None:
            return
        if self.barra.areas.escolhida != indice:
            self.barra.areas.blockSignals(True)
            self.barra.areas.escolher(indice)
            self.barra.areas.blockSignals(False)
        self.paginas.setCurrentWidget(pagina)
        self.status_por_area.setCurrentIndex({AREA_ANALISE: 0, AREA_AQUISICAO: 1, AREA_FIGURAS: 2}[indice])

    def figura_da_vista_ativa(self) -> bool:
        """FG-01: a vista aberta na Análise vira uma figura, e a janela vai para as Figuras com ela escolhida."""
        from .areas.figuras.area import TIPOS_COM_FIGURA

        vista = self.vista_ativa()
        if vista is None or vista.tipo not in TIPOS_COM_FIGURA:
            return False
        self.figuras.figura_da_vista(vista)
        self.mostrar_area(AREA_FIGURAS)
        return True

    def _mostrar_na_analise(self, caminhos) -> None:
        """As capturas na Análise: as que ainda não estão no projeto entram, e a área troca."""
        no_projeto = {f.caminho.resolve() for f in self.projeto.fontes if not f.esta_ausente}
        faltam = [c for c in map(Path, caminhos) if c.resolve() not in no_projeto]
        if faltam:
            self.controle.abrir_capturas(faltam)
        self.mostrar_area(AREA_ANALISE)

    def _na_analise(self, abriu: object) -> None:
        """Depois de abrir uma captura ou um projeto (de qualquer área), a Análise, onde ele aparece."""
        if abriu:
            self.mostrar_area(AREA_ANALISE)

    def _placa_mudou(self) -> None:
        """O chip da barra superior: o estado da placa, sempre à vista. Conectada e não pronta para capturar (um erro
        no diagnóstico), ele fica em atenção, com o motivo na dica."""
        r = resumo(self.conexao_da_placa)
        nivel, detalhe = r.nivel, r.detalhe
        saude = self.saude_da_placa.saude
        if nivel == "conectada" and saude is not None and saude.tem_diagnostico:
            erros = [p for p in saude.diagnostico(self.saude_da_placa.firmware_do_aplicativo) if p.nivel == "erro"]
            if erros:
                nivel = "atencao"
                detalhe = self.tr("{} Não está pronta para capturar: {}").format(detalhe, erros[0].texto)
        self.barra.chip_placa.definir(nivel, r.titulo, detalhe)

    def showEvent(self, evento: QShowEvent) -> None:
        super().showEvent(evento)
        if self._primeira_exibicao:
            self._primeira_exibicao = False
            if not self._layout_restaurado:
                self.layout_padrao()

    # ------------------------------------------------------------------ o erro inesperado

    def _erro_inesperado(self, erro: ErroInesperado) -> None:
        """O diálogo, sem parar o trabalho (não é modal); com ele aberto, o erro entra na lista dele. Um erro aqui
        dentro vai só para o log: voltar ao relator faria um laço."""
        try:
            if self.dialogo_de_erro is None:
                self.dialogo_de_erro = DialogoDeErro(caminho_do_log(), self)
                self.dialogo_de_erro.finished.connect(self._dialogo_de_erro_fechou)
            self.dialogo_de_erro.adicionar(erro)
            if not self.dialogo_de_erro.isVisible():
                self.dialogo_de_erro.show()
        except Exception:
            log.exception("o diálogo de erro inesperado falhou")

    def _dialogo_de_erro_fechou(self, _resultado: int) -> None:
        if self.dialogo_de_erro is not None:
            self.dialogo_de_erro.deleteLater()
            self.dialogo_de_erro = None

    def closeEvent(self, evento: QCloseEvent) -> None:
        if not self.aquisicao.pode_fechar() or not self.controle.pode_descartar():
            evento.ignore()
            return
        self.salvar_layout()
        self.tarefas.encerrar()          # nenhuma thread rodando depois da janela
        self.materializacoes.encerrar()
        self.conexao_da_placa.encerrar()  # a conexão fechada (e a pasta do simulador apagada) antes do laço parar
        self.placa.encerrar()            # nem a thread do laço da placa
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
            self._na_analise(self.controle.abrir_arquivos(caminhos))

    def sizeHint(self) -> QSize:
        return QSize(*TAMANHO_INICIAL)
