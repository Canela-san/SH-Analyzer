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
import os
import time
from functools import partial
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer
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
from .ajuda import SECAO_DO_TIPO, abrir_ajuda, botao_de_ajuda
from .areas.analise.area import AreaDeAnalise
from .areas.analise.arvore import PainelDoProjeto
from .areas.analise.inspetor import Inspetor
from .areas.analise.medidas import TabelaDeMedidas
from .areas.aquisicao.barra_de_status import StatusDaPlaca
from .areas.aquisicao.textos import resumo
from .areas.configuracoes import DialogoDeConfiguracoes
from .componentes.avisos import ListaDeAvisos
from .componentes.barra_superior import BarraSuperior
from .componentes.basicos import Botao
from .componentes.caderno_de_notas import CadernoDeNotas
from .componentes.dialogo_de_erro import DialogoDeErro
from .componentes.grade_de_vistas import DISPOSICOES, AbasEmGrade, nome_da_disposicao
from .componentes.painel import EstadoVazio, PainelComAbas, TituloDoPainel, TrilhoDoPainel, botao_de_icone
from .componentes.paleta import DialogoDeAtalhos, PaletaDeComandos
from .componentes.primeiros_passos import NOME_DO_EXEMPLO, Passo, PrimeirosPassos, gerar_exemplo
from .componentes.primeiros_passos import ja_vistos as primeiros_passos_vistos
from .componentes.tarefas import ListaDeTarefas
from .componentes.toast import Toast
from .componentes.versao_nova import CartaoDeVersaoNova
from .configuracao import gravar, ler_bytes
from .controle_do_projeto import ControleDoProjeto
from .dados.cache import CacheDePiramides
from .dados.materializacao import CacheDeMaterializacoes
from .dados.notas import Referencia
from .dados.pacotes import CacheDePacotes
from .dados.piramide import Cancelado
from .modelo.objetos import Projeto, Vista
from .modelo.selecao import Selecao
from .registro import caminho_do_log
from .servicos import versao_nova
from .servicos.conexao_da_placa import ConexaoDaPlaca
from .servicos.erros import ErroInesperado, relator
from .servicos.fontes import ServicoDeFontes
from .servicos.materializar import ServicoDeMaterializacao
from .servicos.notas import central
from .servicos.pacotes import ServicoDePacotes
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
ATRASO_DA_CONSULTA_DE_VERSAO_MS = 4000
"""A consulta de versão nova espera a janela assentar: a partida fica só com o que o usuário pediu."""
ESPERA_PARA_MONTAR_MS = 150
"""Depois da primeira pintura, as Figuras e (o dobro) a Aquisição montam: a janela aparece antes delas."""
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
        self.pacotes = ServicoDePacotes(self.tarefas, parent=self, abertas=self._capturas_abertas,
                                        cache=CacheDePacotes(preferencias.pasta_do_cache("pacotes"),
                                                             preferencias.limite("pacotes")))
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
        self._criar_caderno()

        self.barra = BarraSuperior(self.acoes["paleta"].shortcut())
        self.setMenuWidget(self.barra)
        self.barra.campo_paleta.clicked.connect(self.acoes["paleta"].trigger)
        self.barra.botao_desfazer.setDefaultAction(self.acoes["desfazer"])
        self.barra.botao_refazer.setDefaultAction(self.acoes["refazer"])
        self.barra.botao_tema.setDefaultAction(self.acoes["alternar_tema"])
        self.barra.botao_ajuda.setDefaultAction(self.acoes["ajuda"])
        self.barra.botao_ajustes.setDefaultAction(self.acoes["configuracoes"])
        self.barra.botao_caderno.setDefaultAction(self.acoes["caderno"])
        self.barra.definir_menu_do_projeto(self._menu_do_projeto())
        self.barra.areaMudou.connect(self.mostrar_area)
        self.barra.chip_placa.clicked.connect(lambda: self.mostrar_area(AREA_AQUISICAO))

        self.estudio.setCentralWidget(self._criar_centro())
        self.dock_projeto = self._criar_dock("projeto", self.tr("Projeto"), self._criar_projeto(),
                                             Qt.DockWidgetArea.LeftDockWidgetArea, "painel_projeto")
        self.dock_projeto.titulo.adicionar_botao(self.acoes["abrir"])
        self.dock_projeto.titulo.adicionar_ajuda("projeto")
        self.dock_inspetor = self._criar_dock("inspetor", self.tr("Inspetor"), self._criar_inspetor(),
                                              Qt.DockWidgetArea.RightDockWidgetArea, "painel_inspetor")
        self.dock_inspetor.titulo.adicionar_ajuda("inspetor")
        self.painel_inferior = self._criar_painel_inferior()
        self.dock_inferior = self._criar_dock("inferior", self.tr("Painel de baixo"), self.painel_inferior,
                                              Qt.DockWidgetArea.BottomDockWidgetArea, "painel_inferior",
                                              com_titulo=False)
        self._criar_recolher_e_trilhos()
        self._criar_barra_de_status()
        self.area = AreaDeAnalise(self, self.painel_projeto, self.inspetor, self.avisos, self.status_fonte,
                                  self.status_integridade, self.vistas, self.tabela_de_medidas)
        # As Figuras e a Aquisição montam depois da primeira pintura (ou no primeiro uso): juntas, ~1,5 s da partida,
        # com o Matplotlib que só as figuras usam. Até lá, a página delas é um lugar vazio na pilha.
        self._aquisicao = self._figuras = None
        self.paginas = QStackedWidget()
        self.paginas.setObjectName("paginas_das_areas")
        self._paginas_das_areas = {AREA_ANALISE: self.estudio, AREA_FIGURAS: QWidget(), AREA_AQUISICAO: QWidget()}
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
        self._visitou_a_aquisicao = False
        self.primeiros_passos = PrimeirosPassos(self._passos_iniciais(), self)   # no canto da janela inteira
        self.primeiros_passos.hide()
        if not primeiros_passos_vistos():
            QTimer.singleShot(0, self.primeiros_passos.mostrar)
        # O aviso de versão nova (servicos/versao_nova.py): consultado depois de a janela abrir.
        self.versao_nova = CartaoDeVersaoNova(self._centro_com_trilhos)
        self.versao_nova.atualizarPedido.connect(self._atualizar_o_aplicativo)
        self.versao_nova.pularPedido.connect(self._pular_versao)
        self.modo_de_instalacao = versao_nova.como_foi_instalado()
        self.instalador_ao_fechar: Path | None = None
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
        self._acao("ajuda", self.tr("Guia do SH-Analyzer"), atalho="F1", icone="livro",
                   dica=self.tr("O guia: o que cada painel e cada vista faz, e como ler os números (a seção da vista "
                                "à frente)")).triggered.connect(self.abrir_ajuda)
        self._acao("primeiros_passos", self.tr("Primeiros passos"),
                   dica=self.tr("Do nada à primeira medida, com uma captura de exemplo")).triggered.connect(
                       lambda: self.primeiros_passos.mostrar())
        self._acao("alternar_tema", self.tr("Alternar o tema claro e escuro"),
                   icone="sol").triggered.connect(preferencias.alternar_tema)
        self._acao("configuracoes", self.tr("Configurações…"), atalho="Ctrl+,",
                   icone="ajustes").triggered.connect(lambda: self.abrir_configuracoes())
        controle = self.controle
        self._acao("abrir", self.tr("Abrir captura…"), atalho=QKeySequence.StandardKey.Open,
                   icone="pasta").triggered.connect(lambda: self._na_analise(controle.abrir_arquivos()))
        self._acao("importar", self.tr("Importar dados de fora…"), atalho="Ctrl+Shift+I", icone="baixar",
                   dica=self.tr("Um registro de osciloscópio, um CSV qualquer, um WAV ou um COMTRADE como captura "
                                "do projeto")).triggered.connect(lambda: self.importar_dados())
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
                   dica=self.tr("Exportar os dados da vista (CSV, HDF5, MAT, NPZ, WAV, COMTRADE ou uma captura derivada)"),
                   da_analise=True).triggered.connect(lambda: self.area.exportar_dados())
        self._acao("relatorio", self.tr("Relatório da captura…"), atalho="Ctrl+Shift+R", icone="pagina",
                   dica=self.tr("Um relatório (HTML ou PDF) dos traços da vista de tempo: o cabeçalho, a integridade, "
                                "os índices de qualidade, as bandas, os eventos e as figuras"),
                   da_analise=True).triggered.connect(lambda: self.area.gerar_relatorio())
        self._acao("lote", self.tr("Análise em lote…"), icone="camadas",
                   dica=self.tr("Os mesmos índices em cada captura de uma pasta: a tabela, a tendência no tempo e o "
                                "CSV")).triggered.connect(lambda: self.analise_em_lote())
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
        self._acao("eventos", self.tr("Abrir os eventos da vista"), icone="alerta",
                   dica=self.tr("Os afundamentos, as elevações e as interrupções da tensão, os picos de "
                                "supraharmônicos, a saturação do ADC e os saltos; um clique mostra o evento no tempo"),
                   da_analise=True).triggered.connect(lambda: self.area.abrir_analise("eventos"))
        self._acao("qualidade", self.tr("Abrir a qualidade de energia da vista"), icone="raio",
                   dica=self.tr("A frequência, o RMS, o THD, o fator K, os fatores de crista e de forma e os "
                                "supraharmônicos em janelas de 10/12 ciclos (IEC 61000-4-30), com as estatísticas"),
                   da_analise=True).triggered.connect(lambda: self.area.abrir_analise("qualidade"))
        self._acao("transferencia", self.tr("Abrir a transferência entre dois traços"), icone="link",
                   dica=self.tr("A função de transferência H₁ de um traço para outro (o ganho e a fase com o "
                                "intervalo de confiança) e a coerência"),
                   da_analise=True).triggered.connect(lambda: self.area.abrir_analise("transferencia"))
        self._acao("metricas", self.tr("Abrir as métricas de bancada da vista"), icone="chip",
                   dica=self.tr("O tom, o THD, o SINAD, o SNR, o ENOB, o SFDR, o ruído, o jitter e os saltos de fase: "
                                "as contas do medir_captura (ME-05)"),
                   da_analise=True).triggered.connect(lambda: self.area.abrir_analise("metricas"))
        self._acao("instrumento", self.tr("Abrir o Instrumento da vista"), icone="onda",
                   dica=self.tr("Os traços sobrepostos no disparo de um deles, como num osciloscópio: a escala por "
                                "divisão, a persistência e o ciclo médio"),
                   da_analise=True).triggered.connect(lambda: self.area.abrir_analise("instrumento"))
        self._acao("aliasing", self.tr("Assistente de aliasing…"), icone="espectro",
                   dica=self.tr("Separa os picos reais das imagens com duas a quatro capturas em taxas diferentes "
                                "(ES-06)"),
                   da_analise=True).triggered.connect(lambda: self.area.abrir_aliasing())
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
        for montada in (self._aquisicao, self._figuras):
            if montada is not None:
                montada.acompanhar(projeto)

    # ------------------------------------------------------------------ as áreas montadas depois

    @property
    def aquisicao(self):
        """A área Aquisição (montada no primeiro uso, ou logo depois da primeira pintura)."""
        if self._aquisicao is None:
            from .areas.aquisicao.area import AreaDeAquisicao

            area = AreaDeAquisicao(
                self.conexao_da_placa, self.saude_da_placa, lambda: self.controle.dialogos,
                self.transferencias_da_placa,
                abrir_na_analise=lambda caminhos: self._na_analise(self.controle.abrir_capturas(caminhos)),
                abrir_no_projeto=lambda caminhos: self.controle.abrir_capturas(caminhos),
                mostrar_na_analise=self._mostrar_na_analise)
            area.caderno.mudou.connect(self.area.cadernos_mudaram)
            self._aquisicao = area
            self._trocar_a_pagina(AREA_AQUISICAO, area)
            area.acompanhar(self.projeto)
        return self._aquisicao

    @property
    def figuras(self):
        """A área Figuras (montada no primeiro uso, ou logo depois da primeira pintura)."""
        if self._figuras is None:
            from .areas.figuras.area import AreaDeFiguras

            area = AreaDeFiguras(self.area, self.tarefas, self.materializacoes, vista_ativa=self.vista_ativa,
                                 dialogos_de=lambda: self.controle.dialogos)
            area.resumoMudou.connect(self.status_da_figura.setText)
            self._figuras = area
            self._trocar_a_pagina(AREA_FIGURAS, area)
            area.acompanhar(self.projeto)
        return self._figuras

    def _trocar_a_pagina(self, indice: int, pagina: QWidget) -> None:
        vazia = self._paginas_das_areas[indice]
        posicao = self.paginas.indexOf(vazia)
        atual = self.paginas.currentWidget() is vazia
        self.paginas.insertWidget(posicao, pagina)
        self.paginas.removeWidget(vazia)
        vazia.deleteLater()
        self._paginas_das_areas[indice] = pagina
        if atual:
            self.paginas.setCurrentWidget(pagina)

    def montar_as_areas(self) -> None:
        """As duas áreas que faltam, uma por vez, com a janela já na tela (com ``SH_ANALYZER_AREAS_SO_NO_USO``, como
        nos testes, só no primeiro uso)."""
        if os.environ.get("SH_ANALYZER_AREAS_SO_NO_USO"):
            return
        QTimer.singleShot(ESPERA_PARA_MONTAR_MS, lambda: isValid(self) and self.figuras)
        QTimer.singleShot(2 * ESPERA_PARA_MONTAR_MS, lambda: isValid(self) and self.aquisicao)

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
        """A pasta e os limites do cache das configurações, nos três serviços (o limite menor apaga na hora os
        menos usados, nunca o que está aberto)."""
        self.servico_de_fontes.definir_cache(preferencias.pasta_do_cache("piramides"), preferencias.limite("piramides"))
        self.materializacoes.definir_cache(preferencias.pasta_do_cache("materializacoes"),
                                           preferencias.limite("materializacoes"))
        self.pacotes.definir_cache(preferencias.pasta_do_cache("pacotes"), preferencias.limite("pacotes"))

    def _capturas_abertas(self) -> set[Path]:
        """Os arquivos das capturas abertas no projeto (o cache dos pacotes não apaga as pastas deles)."""
        if self.projeto is None:
            return set()
        return {f.caminho for f in self.projeto.fontes if not f.esta_ausente}

    def mostrar_atalhos(self) -> DialogoDeAtalhos:
        self.dialogo_de_atalhos = DialogoDeAtalhos(self.acoes_da_paleta(), self)
        self.dialogo_de_atalhos.show()
        return self.dialogo_de_atalhos

    def _menu_do_projeto(self) -> QMenu:
        menu = QMenu(self)
        menu.setObjectName("menu_projeto")
        menu.addAction(self.acoes["novo_projeto"])
        menu.addAction(self.acoes["abrir_projeto"])
        menu.addAction(self.acoes["importar"])
        menu.addAction(self.acoes["relatorio"])
        menu.addAction(self.acoes["lote"])
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
                 lambda c: self.controle.abrir_arquivos([c]), lambda c: c.name)):
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
        exemplo = Botao(self.tr("Abrir o exemplo"), "secundario")
        exemplo.setObjectName("botao_exemplo_central")
        exemplo.setToolTip(self.tr("Uma captura da placa simulada: a rede de 60 Hz com supraharmônicos de 16, 40 e "
                                   "72 kHz (gerada na pasta do cache)"))
        exemplo.clicked.connect(self.abrir_o_exemplo)
        botoes = QWidget()
        linha = QHBoxLayout(botoes)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.addStretch(1)
        linha.addWidget(abrir)
        linha.addWidget(exemplo)
        linha.addStretch(1)
        app = QApplication.instance()
        self.vazio_central = EstadoVazio(
            self.tr("Abra uma captura para começar"),
            self.tr("Escolha uma captura (.bin, ou o .csv e o .h5 do adc_tool) ou um pacote .zpaq.tar, ou arraste-os "
                    "para esta janela. As capturas abertas aparecem no painel do projeto, com os canais prontos para "
                    "plotar. Primeira vez? Abra o exemplo, e o F1 abre o guia."),
            imagem=app.windowIcon().pixmap(LADO_DA_MARCA, LADO_DA_MARCA), botao=botoes, largura_do_texto=440)
        self.vazio_central.simbolo.setObjectName("marca")

        self.centro = QStackedWidget()
        self.centro.setObjectName("area_central")
        self.centro.addWidget(self.vazio_central)
        self.centro.addWidget(self.vistas)
        self.vistas.currentChanged.connect(self._atualizar_centro)
        self._atualizar_centro()
        # Em volta, os trilhos dos painéis recolhidos (postos depois dos painéis: _criar_recolher_e_trilhos).
        conteiner = QWidget()
        self._centro_com_trilhos = conteiner
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
        canto = QWidget()
        linha_do_canto = QHBoxLayout(canto)
        linha_do_canto.setContentsMargins(0, 0, 0, 0)
        linha_do_canto.setSpacing(0)
        linha_do_canto.addWidget(botao_de_ajuda("medidas", qual=lambda: ("medidas", "janela", "janela")[
            max(painel.currentIndex(), 0)]))
        linha_do_canto.addWidget(botao_de_icone(recolher, "baixo"))
        painel.setCornerWidget(canto, Qt.Corner.TopRightCorner)
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
        self.inspetor.da_vista.ajudaPedida.connect(lambda: self.abrir_ajuda())
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
        if indice == AREA_FIGURAS:
            self.figuras                       # noqa: B018 -- monta, se ainda não montou
        elif indice == AREA_AQUISICAO:
            self.aquisicao                     # noqa: B018
        pagina = self._paginas_das_areas.get(indice)
        if pagina is None:
            return
        if self.barra.areas.escolhida != indice:
            self.barra.areas.blockSignals(True)
            self.barra.areas.escolher(indice)
            self.barra.areas.blockSignals(False)
        self.paginas.setCurrentWidget(pagina)
        self.status_por_area.setCurrentIndex({AREA_ANALISE: 0, AREA_AQUISICAO: 1, AREA_FIGURAS: 2}[indice])
        if indice == AREA_AQUISICAO:
            self._visitou_a_aquisicao = True

    # ------------------------------------------------------------------ a ajuda e os primeiros passos

    def secao_da_ajuda(self) -> str:
        """A seção do guia do que está à frente: a da área, ou a da vista aberta na Análise."""
        area = self.area_atual
        if area == AREA_FIGURAS:
            return "figuras"
        if area == AREA_AQUISICAO:
            return "aquisicao"
        vista = self.vista_ativa()
        if vista is not None:
            return SECAO_DO_TIPO.get(vista.tipo, "janela")
        return "primeiros-passos" if self.projeto is None or not self.projeto.fontes else "janela"

    def abrir_ajuda(self, secao: str | None = None):
        """O guia (F1) na seção pedida, ou na do que está à frente."""
        return abrir_ajuda(self, secao or self.secao_da_ajuda())

    def importar_dados(self, caminho: Path | None = None):
        """O diálogo "Importar dados de fora" (não bloqueia a janela); com ``caminho``, já lendo o arquivo. A
        captura gravada entra no projeto. Devolve o diálogo."""
        from .areas.analise.importar import DialogoDeImportacao

        self.mostrar_area(AREA_ANALISE)
        dialogo = DialogoDeImportacao(self.tarefas, preferencias.pasta("dados"), self)
        dialogo.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialogo.importadaPronta.connect(lambda destino: self.controle.abrir_capturas([destino]))
        dialogo.show()
        if caminho is not None:
            dialogo.carregar(Path(caminho))
        self.dialogo_de_importacao = dialogo
        return dialogo

    def analise_em_lote(self, pasta: Path | None = None):
        """O diálogo da análise em lote (não bloqueia a janela); o duplo clique numa linha abre a captura aqui.
        Devolve o diálogo."""
        from .areas.analise.lote import DialogoDoLote

        dialogo = DialogoDoLote(self.tarefas, self.controle.dialogos, self,
                                pasta=pasta or preferencias.pasta("dados"))
        dialogo.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialogo.abrirCaptura.connect(lambda caminho: self._na_analise(self.controle.abrir_capturas([caminho])))
        dialogo.show()
        self.dialogo_do_lote = dialogo
        return dialogo

    def abrir_o_exemplo(self) -> None:
        """A captura de exemplo (gerada uma vez na pasta do cache) no projeto, na Análise."""
        self.mostrar_area(AREA_ANALISE)
        self.controle.abrir_capturas([gerar_exemplo(preferencias.pasta("cache"))])

    def _passos_iniciais(self) -> list[Passo]:
        """Os passos do cartão, com o estado e as ações desta janela."""

        def tempo_ativo():
            vista = self.vista_ativa()
            if vista is None or vista.tipo != "tempo":
                vista = next((v for v in self.projeto.vistas if v.tipo == "tempo" and v.tracos), None)
            return self.area.widget_da_vista(vista) if vista is not None else None

        def plotar():
            self.mostrar_area(AREA_ANALISE)
            fontes = [f for f in self.projeto.fontes if not f.esta_ausente]
            if not fontes:
                return
            fonte = next((f for f in fontes if f.nome == NOME_DO_EXEMPLO), fontes[0])
            numeros = [c.numero for c in fonte.canais]
            self.area.plotar_canal(fonte, 1 if 1 in numeros else numeros[0])

        def ligar_os_cursores():
            widget = tempo_ativo()
            if widget is not None:
                self.area.ativar_vista(widget.vista)
                widget.acao_cursores.setChecked(True)

        def cursores_ligados() -> bool:
            widget = tempo_ativo()
            return widget is not None and getattr(widget, "cursores", None) is not None

        return [
            Passo("abrir", self.tr("Abrir uma captura"),
                  self.tr("A de exemplo é a bancada do projeto: a rede de 60 Hz com supraharmônicos."),
                  self.tr("Abrir o exemplo"), lambda: bool(self.projeto.fontes), self.abrir_o_exemplo),
            Passo("plotar", self.tr("Plotar um canal"),
                  self.tr("Duplo clique num canal do painel do projeto, ou o botão."),
                  self.tr("Plotar a tensão"),
                  lambda: any(v.tipo == "tempo" and v.tracos for v in self.projeto.vistas), plotar),
            Passo("medir", self.tr("Medir com os cursores"),
                  self.tr("C liga os cursores; a tabela de Medidas, embaixo, traz o RMS e a frequência."),
                  self.tr("Ligar os cursores"), cursores_ligados, ligar_os_cursores),
            Passo("espectro", self.tr("Ver o espectro"),
                  self.tr("Ctrl+E: os supraharmônicos de 16, 40 e 72 kHz do exemplo."),
                  self.tr("Abrir o espectro"), lambda: any(v.tipo == "espectro" for v in self.projeto.vistas),
                  lambda: self.acoes["espectro"].trigger()),
            Passo("aquisicao", self.tr("Experimentar a aquisição"),
                  self.tr("Na área Aquisição, conecte a placa simulada e faça uma captura."),
                  self.tr("Ir para a Aquisição"), lambda: self._visitou_a_aquisicao,
                  lambda: self.mostrar_area(AREA_AQUISICAO), opcional=True),
        ]

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
        if self.conexao_da_placa.estado != "desconectada" and self._aquisicao is None:
            self.aquisicao                     # noqa: B018 -- a placa em uso: a área (o caderno, a conferência) já ouve
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
            self.montar_as_areas()
            QTimer.singleShot(ATRASO_DA_CONSULTA_DE_VERSAO_MS, self.consultar_versao_nova)

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
        if (self._aquisicao is not None and not self._aquisicao.pode_fechar()) or not self.controle.pode_descartar():
            evento.ignore()
            return
        self.caderno.gravar()
        self.salvar_layout()
        self.tarefas.encerrar()          # nenhuma thread rodando depois da janela
        self.materializacoes.encerrar()
        self.conexao_da_placa.encerrar()  # a conexão fechada (e a pasta do simulador apagada) antes do laço parar
        self.placa.encerrar()            # nem a thread do laço da placa
        if self.instalador_ao_fechar is not None:
            # A atualização pedida no aviso: o instalador calado fecha o que restar e reabre o aplicativo.
            versao_nova.iniciar_instalador(self.instalador_ao_fechar)
        super().closeEvent(evento)

    # ------------------------------------------------------------------ o caderno de notas

    def _criar_caderno(self) -> None:
        """O caderno de notas (``componentes/caderno_de_notas.py``) no lado direito da janela, por cima de qualquer
        área: Ctrl+Shift+N (ou o botão da barra) o mostra e o recolhe."""
        self.caderno = CadernoDeNotas(preferencias.pasta_do_caderno)
        self.caderno.referencia_da_vista = self._referencia_da_vista_ativa
        self.caderno.imagem_da_vista = self._imagem_da_vista_ativa
        self.dock_caderno = QDockWidget(self.tr("Caderno"), self)
        self.dock_caderno.setObjectName("caderno")
        self.dock_caderno.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.dock_caderno.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.dock_caderno.titulo = TituloDoPainel(self.tr("Caderno"))
        self.dock_caderno.setTitleBarWidget(self.dock_caderno.titulo)
        self.dock_caderno.setWidget(self.caderno)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_caderno)
        self.dock_caderno.hide()
        acao = self._acao("caderno", self.tr("Caderno de notas"), atalho="Ctrl+Shift+N", icone="caderno",
                          dica=self.tr("O caderno de notas: páginas em Markdown, com referências aos gráficos"),
                          acao=self.dock_caderno.toggleViewAction())
        acao.setText(self.tr("Caderno de notas"))
        self.dock_caderno.titulo.adicionar_ajuda("caderno")
        self.dock_caderno.visibilityChanged.connect(self._caderno_visivel)
        central().referenciaPedida.connect(self._referencia_pedida)
        central().irPedido.connect(self.ir_para_referencia)

    def _caderno_visivel(self, visivel: bool) -> None:
        if visivel:
            self.caderno.editor.setFocus()
        else:
            self.caderno.gravar()

    def mostrar_caderno(self) -> None:
        self.dock_caderno.show()
        self.dock_caderno.raise_()

    def _referencia_pedida(self, referencia: Referencia) -> None:
        self.mostrar_caderno()
        self.caderno.inserir_referencia(referencia)

    def _widget_ativo(self):
        vista = self.area.vista_ativa() if self.projeto is not None else None
        return (vista, self.area.widget_da_vista(vista)) if vista is not None else (None, None)

    def _referencia_da_vista_ativa(self) -> Referencia | None:
        """A referência ao que a vista à frente da Análise mostra (o tempo ou a frequência)."""
        vista, w = self._widget_ativo()
        anotacoes = getattr(w, "anotacoes", None)
        if anotacoes is None:
            return None
        caixas = anotacoes.caixas()
        if not caixas:
            return None
        faixa, caixa = caixas[0]
        v0, v1 = caixa.viewRange()[0]
        caminho = self.projeto.caminho
        return Referencia(vista=vista.id, nome=vista.nome, x0=anotacoes.do_eixo(v0), x1=anotacoes.do_eixo(v1),
                          faixa=faixa, dominio="f" if anotacoes.frequencia else "t",
                          projeto=str(caminho) if caminho else "")

    def _imagem_da_vista_ativa(self):
        vista, w = self._widget_ativo()
        if w is None:
            return None
        grafico = getattr(w, "grafico", w)
        return grafico.grab(), f"{vista.nome}, {time.strftime('%H:%M')}"

    def ir_para_referencia(self, referencia: Referencia) -> bool:
        """Leva a Análise até a referência: abre o projeto dela (perguntando), a vista e o trecho (com uma folga), e
        destaca o ponto ou o trecho por um instante."""
        if referencia.projeto and (self.projeto.caminho is None
                                   or Path(referencia.projeto) != Path(self.projeto.caminho)):
            caminho = Path(referencia.projeto)
            if not caminho.exists():
                Toast.mostrar(self, self.tr("A referência é do projeto {}, que não está mais lá.").format(caminho.name),
                              "aviso")
                return False
            resposta = self.controle.dialogos.perguntar(
                self.tr("Ir à referência"),
                self.tr("A referência é do projeto “{}”. Abrir esse projeto?").format(caminho.stem),
                {"abrir": self.tr("Abrir o projeto")}, "abrir")
            if resposta != "abrir" or not self.controle.abrir(caminho):
                return False
        vista = next((v for v in self.projeto.vistas if v.id == referencia.vista), None)
        if vista is None:
            Toast.mostrar(self, self.tr("A vista da referência não está neste projeto."), "aviso")
            return False
        self.mostrar_area(AREA_ANALISE)
        self.area.ativar_vista(vista)
        w = self.area.widget_da_vista(vista)
        if w is None:
            return False
        x0, x1 = referencia.x0, referencia.x1
        if referencia.tipo == "intervalo" or x1 <= x0:
            largura = (x1 - x0) or abs(x0) * 0.1 or 1e-3
            x0, x1 = x0 - 0.15 * largura, x1 + 0.15 * largura
        if referencia.dominio == "f" and hasattr(w, "mostrar_frequencias"):
            w.mostrar_frequencias(x0, x1)
        elif hasattr(w, "mostrar_tempo"):
            w.mostrar_tempo(x0, x1)
        anotacoes = getattr(w, "anotacoes", None)
        if anotacoes is not None:
            caixa = anotacoes.caixa_da_faixa(referencia.faixa)
            if caixa is None and anotacoes.caixas():
                caixa = anotacoes.caixas()[0][1]
            if referencia.tipo == "ponto":
                QTimer.singleShot(60, lambda: anotacoes.destacar(caixa, referencia.px, y=referencia.py))
            else:
                QTimer.singleShot(60, lambda: anotacoes.destacar(caixa, referencia.x0, referencia.x1))
        return True

    # ------------------------------------------------------------------ o aviso de versão nova

    def _versao_local(self) -> str:
        return QApplication.applicationVersion() or "0"

    def consultar_versao_nova(self, *, forcar: bool = False):
        """Procura uma versão nova numa tarefa sem painel (uma vez por dia, se ligado nas configurações e fora do
        código; ``forcar``: agora, pelo botão das configurações, avisando também quando não há). Devolve a tarefa, ou
        ``None`` se não procurou."""
        if not forcar and (self.modo_de_instalacao == "dev" or not preferencias.procurar_versoes_novas()
                           or not versao_nova.deve_consultar(preferencias.ultima_consulta(), time.time())):
            return None
        preferencias.marcar_consulta(time.time())
        local = self._versao_local()

        def consultar(_progresso, _cancelado):
            try:
                return versao_nova.consultar(local)
            except Exception as erro:         # sem rede, o GitHub fora, uma resposta estranha: fica para amanhã
                log.info("a consulta de versão nova falhou: %s", erro)
                return erro

        return self.tarefas.iniciar(self.tr("Procurar versão nova"), consultar, "versao_nova", mostrar=False,
                                    ao_terminar=partial(self._versao_consultada, forcar))

    def _versao_consultada(self, forcar: bool, tarefa) -> None:
        if not isValid(self) or tarefa.estado != "concluida":
            return
        resultado = tarefa.resultado
        if isinstance(resultado, versao_nova.Lancamento):
            if forcar or resultado.versao != preferencias.versao_pulada():
                self.versao_nova.mostrar(resultado, self._versao_local(), self.modo_de_instalacao)
        elif forcar:
            texto = (self.tr("Não deu para procurar agora (sem internet?).") if isinstance(resultado, Exception)
                     else self.tr("Você já tem a versão mais nova ({0}).").format(self._versao_local()))
            Toast.mostrar(self, texto)

    def _pular_versao(self) -> None:
        if self.versao_nova.lancamento is not None:
            preferencias.pular_versao(self.versao_nova.lancamento.versao)

    def _atualizar_o_aplicativo(self) -> None:
        """O Atualizar agora (só no Windows): baixa e confere o instalador numa tarefa do painel; no fim, fecha a
        janela (que oferece salvar o projeto) e o instalador roda no closeEvent."""
        if self.instalador_ao_fechar is not None:       # já baixado; o fechar tinha sido cancelado
            self._fechar_para_instalar()
            return
        lancamento, local = self.versao_nova.lancamento, self._versao_local()
        if lancamento is None:
            return

        def baixar(progresso, cancelado):
            try:
                return versao_nova.baixar_instalador(lancamento, local, progresso, cancelado)
            except InterruptedError:
                raise Cancelado from None
            except (versao_nova.ErroDeAtualizacao, OSError, ValueError) as erro:
                return erro

        self.versao_nova.baixando(0.0)
        self.tarefas.iniciar(self.tr("Baixar o SH-Analyzer {0}").format(lancamento.versao), baixar, "versao_nova",
                             ao_progredir=lambda _t, fracao: self.versao_nova.baixando(fracao),
                             ao_terminar=self._instalador_baixado)

    def _instalador_baixado(self, tarefa) -> None:
        if not isValid(self):
            return
        if tarefa.estado == "cancelada":
            self.versao_nova.falhou(self.tr("o download foi cancelado"))
            return
        if tarefa.estado != "concluida" or not isinstance(tarefa.resultado, Path):
            motivo = tarefa.erro if tarefa.estado == "falhou" else tarefa.resultado
            self.versao_nova.falhou(str(motivo))
            return
        self.instalador_ao_fechar = tarefa.resultado
        self._fechar_para_instalar()

    def _fechar_para_instalar(self) -> None:
        if not self.close():                            # o usuário cancelou (o projeto não salvo)
            self.versao_nova.esperando_fechar()

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
