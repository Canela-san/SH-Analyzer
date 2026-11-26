"""A vista de espectro (docs/gui-plan.md, 9.5; ES-01 e ES-02): FFT e Welch dos traços de uma vista de tempo.

* **Os traços** são os visíveis da vista de tempo ligada (``OpcoesDoEspectro.vista_de_tempo``; sem ela, a primeira do
  projeto), cada um com a sua cadeia: mudar a cadeia, o ganho ou a visibilidade lá muda o espectro aqui. Os números
  são os da ``api`` (``dados/espectros.py``).
* **As anotações** (F5.8; ``anotacoes.py``): o clique direito no gráfico põe um texto, uma seta, uma região ou uma
  cota de Δf (entre os cursores, se ligados), e muda ou tira a que está perto.
* **O trecho:** a região dos cursores da vista de tempo (o padrão; sem eles, a janela visível), a janela visível ou
  a captura inteira. A conta refaz a cada parada do zoom ou dos cursores de lá, se o trecho mudou.
* **A escala:** dB (a amplitude de pico, a convenção do ``adc_tool``: dBV na tensão), o valor RMS de cada tom ou dBc
  (relativa à fundamental, ou ao bin mais alto); a frequência linear ou logarítmica. A faixa válida do perfil de cada
  traço corrigido pela sonda fica sombreada, na cor do traço.
* **As marcas:** os picos mais altos acima do piso + 10 dB (o número da frequência só nos do primeiro traço), o piso de
  ruído (tracejado) e, com a FFT sincronizada, os harmônicos de f₁.
* **A FFT é o método padrão** (o Welch, a média de segmentos, fica como segundo). Sem a fundamental para sincronizar,
  a FFT é do trecho inteiro, com um aviso.
* **Os botões da barra** (todos desligados ao abrir): **Picos** marca os mais altos de cada traço (acima do piso + 20
  dB e com 10 dB de proeminência: o ruído não conta); **Valores** mostra, sob o mouse, a frequência e o nível do bin
  mais alto da coluna de pixel de cada traço; **Cursores** (C) liga os cursores C1 e C2, os mesmos da vista de tempo
  (``graficos/cursores.py``): as setas andam um bin (Shift: 10), e as medidas (a frequência de cada um, o nível de cada
  traço em C1 e em C2, Δf e Δ nível) vão para a tabela de Medidas do painel de baixo.
* **A escala de cada traço** (``graficos/escalas.py``): os traços dividem o eixo Y; o cadeado da barra destrava o
  selecionado (o zoom e o pan do Y passam a ser só dele, e as marcas dele o acompanham) e "Mesma escala" o devolve à
  escala comum. O eixo Y mostra os números e a unidade do traço selecionado (sem seleção, do primeiro travado); com
  unidades ou escalas diferentes, o rótulo fica na cor dele. Mudar o que o Y mede (dB, RMS, dBc) volta todos à escala
  comum.
* **As contas em segundo plano:** cada pedido cancela o anterior, e vale o mais recente. Um trecho grande de um traço
  com cadeia espera a materialização (o chip mostra o progresso), e a conta refaz quando ela fica pronta.
* **Sem custo por quadro** (uma FFT de 60 s tem 6 milhões de bins): o espectro de um trecho já calculado não é
  refeito (mover os cursores com o trecho na janela, trocar a escala); os níveis na escala, a pirâmide e as marcas
  são preparados na thread de trabalho (``esp.preparar_desenho``); na frequência linear, o traço é desenhado pela
  pirâmide, como a vista de tempo (``TracoLOD``: a consulta de cada quadro lê só a pirâmide, e um pico de um bin
  aparece em qualquer zoom); na log, pela envoltória por coluna de pixel, refeita quando o zoom para; o cursor lê o
  bin pela grade uniforme, sem procurar. O zoom do usuário fica quando um resultado novo chega (o ``F``, ou o botão
  da barra, ajusta; o duplo clique não mexe no zoom).

Cada mudança das opções é um comando de desfazer (``MudarOpcoesDaVista``) e vai para o projeto.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pyqtgraph as pg
import supraharmonicos.api as api
from PySide6.QtCore import QLineF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPen
from PySide6.QtWidgets import QCheckBox, QGraphicsItem, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget
from shiboken6 import isValid

from ...ajuda import botao_de_ajuda
from ...componentes.basicos import CampoComUnidade, Segmentado
from ...componentes.chip import ChipDeTraco
from ...componentes.fluxo import LayoutDeFluxo
from ...componentes.numeros import decimal, formatar_si, separador_decimal
from ...dados import espectros as esp
from ...dados.bancada import limite_das_imagens_hz
from ...dados.cadeia import CorrecaoSonda
from ...dados.limites import FAIXAS_CENELEC
from ...dados.qualidade import intervalo_do_welch
from ...graficos.clique import distancia_a_linha, mais_perto
from ...graficos.cursores import CursoresDaVista
from ...graficos.escalas import CaixaComEscalas, EscalasDaCaixa
from ...graficos.faixa import EixoDoTema, GradeDoTema
from ...graficos.traco_lod import TracoLOD
from ...modelo.comandos import MudarOpcoesDaVista
from ...modelo.objetos import Projeto, Traco, Vista
from ...modelo.selecao import Selecao
from ...tema.aplicar import aparencia
from ...tema.fontes import fonte_da_interface
from ...tema.icones import IconeDoTema
from ...tema.tokens import TAMANHOS, Tema, cor_do_traco
from .acoes_da_escala import acoes_da_escala, atualizar_acoes_da_escala, estado_do_chip
from .anotacoes import AnotacoesDaVista
from .medidas import LinhaDaTabela, MedidasDaVista, numero_para_planilha

ESPERA_MS = 40
METODOS, ESCALAS, TRECHOS = ("fft", "welch"), ("db", "rms", "dbc"), ("janela", "cursores", "captura")
AMOSTRAS_PARA_MOSTRAR_A_TAREFA = 20_000_000
ESPERA_DA_ENVOLTORIA_MS = 30
OPCOES_DA_UNIDADE_DO_Y = ("escala", "modo", "diferenca")
"""As opções que mudam o que o eixo Y mede (dB, valor RMS, dBc; amplitude ou densidade): com elas, o Y se ajusta de
novo. As outras (o método, o trecho, a janela, a resolução, os ciclos) deixam a vista onde o usuário a pôs."""


class LinhasVerticais(pg.GraphicsObject):
    """Várias linhas verticais (os harmônicos de f₁) num item só, de cima a baixo da vista: uma ``InfiniteLine`` por
    harmônico recalculava a sua caixa a cada quadro (49 delas pesavam mais que o próprio espectro)."""

    def __init__(self, posicoes, caneta: QPen):
        super().__init__()
        self._posicoes = np.asarray(posicoes, dtype=float)
        self._caneta = QPen(caneta)
        self._caneta.setCosmetic(True)

    def viewRangeChanged(self) -> None:
        self.prepareGeometryChange()
        self.update()

    def boundingRect(self) -> QRectF:
        r = self.viewRect()
        return QRectF() if r is None else r

    def paint(self, p, *args) -> None:
        r = self.viewRect()
        if r is None or not len(self._posicoes):
            return
        dentro = self._posicoes[(self._posicoes >= r.left()) & (self._posicoes <= r.right())]
        p.setPen(self._caneta)
        p.drawLines([QLineF(float(x), r.top(), float(x), r.bottom()) for x in dentro])


class ResultadoDoTraco:
    """O espectro de um traço (ou por que não há um)."""

    def __init__(self, traco: Traco, espectro: api.Espectro | None = None, desenho: esp.Desenho | None = None,
                 erro: str = "", aguardando: bool = False, unidade: str = "V", trecho=None):
        self.traco, self.espectro, self.desenho = traco, espectro, desenho
        self.marcas = desenho.marcas if desenho is not None else None
        self.erro, self.aguardando, self.unidade = erro, aguardando, unidade
        self.trecho = trecho              # o TrechoDoTraco que deu este resultado (a cadeia, o ganho, as amostras)


class VistaDeEspectro(QWidget):
    tracoClicado = Signal(object, object)
    regiaoMudou = Signal(float, float, bool)      # a vista de espectro não é medida pela tabela
    semRegiao = Signal()
    calculado = Signal()                          # um resultado novo chegou (os testes esperam por ele)
    medidasMudaram = Signal(object)               # MedidasDaVista dos cursores (ou None): a tabela de Medidas
    frequenciaMudou = Signal(float, float)        # a faixa de frequência visível (Hz), a cada passo (a grade)

    def __init__(self, vista: Vista, projeto: Projeto, selecao: Selecao, *, tarefas, materializacoes,
                 vista_de_tempo: Callable[[str | None], object], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("vista_espectro")
        self.vista, self.projeto, self.selecao = vista, projeto, selecao
        self.tarefas, self.materializacoes, self._achar_vista_de_tempo = tarefas, materializacoes, vista_de_tempo
        self.resultados: list[ResultadoDoTraco] = []
        self.opcoes_calculadas: esp.OpcoesDoEspectro | None = None     # as opções que deram os resultados mostrados
        self.curvas: dict[Traco, pg.PlotDataItem] = {}
        self.chips: dict[Traco, ChipDeTraco] = {}
        self._fontes_ouvidas: set = set()
        self._tempo = None
        self._tarefa = None
        self._marcas_desenhadas: list = []
        self._prontos_desenhados: list[ResultadoDoTraco] = []      # os que têm curva (para refazer as marcas)
        self._espectros: dict[tuple, api.Espectro] = {}      # a conta de cada trecho, para não refazer
        self._desenhos: dict[tuple, esp.Desenho] = {}        # e o desenho de cada escala
        self._itens: list = []
        self._ajustar = True                                  # o próximo desenho ajusta a vista (o primeiro)
        self._ajustar_y = False                               # só o Y (a unidade dele mudou)
        self._log_desenhado: bool | None = None               # a escala da frequência do último desenho
        self._opcoes_vistas = vista.opcoes                    # as da última mudança vista (para saber o que mudou)
        self._faixa_pedida: tuple[float, float] | None = None
        self._montar()
        self._espera_da_envoltoria = QTimer(self)
        self._espera_da_envoltoria.setSingleShot(True)
        self._espera_da_envoltoria.setInterval(ESPERA_DA_ENVOLTORIA_MS)
        self._espera_da_envoltoria.timeout.connect(self._atualizar_envoltorias)
        self._espera_das_marcas = QTimer(self)          # as marcas seguem a escala de um traço (um gesto: várias)
        self._espera_das_marcas.setSingleShot(True)
        self._espera_das_marcas.setInterval(0)
        self._espera_das_marcas.timeout.connect(self._redesenhar_marcas)
        self.grafico.getViewBox().sigXRangeChanged.connect(self._zoom_mudou)
        self.grafico.scene().sigMouseClicked.connect(self._clique_no_grafico)
        selecao.mudou.connect(self._selecao_mudou)
        self._espera = QTimer(self)
        self._espera.setSingleShot(True)
        self._espera.setInterval(ESPERA_MS)
        self._espera.timeout.connect(self._calcular)
        vista.mudou.connect(self._vista_mudou)
        projeto.vistaEntrou.connect(self._vistas_do_projeto)      # a vista de tempo ligada pode chegar depois
        projeto.vistaSaiu.connect(self._vistas_do_projeto)
        materializacoes.mudou.connect(self._materializacao_mudou)
        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou(aparencia().tema)
        self._mostrar_opcoes()
        self._pedir()

    # ------------------------------------------------------------------ montar

    def _montar(self) -> None:
        # A barra quebra em linhas quando não cabe (em vez de espremer os botões até cortar o texto: "W...h"), em
        # qualquer largura, fonte ou língua.
        barra = QWidget()
        barra.setObjectName("barra_vista")
        politica = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        politica.setHeightForWidth(True)
        barra.setSizePolicy(politica)
        linha = LayoutDeFluxo(barra, espaco=8)
        linha.setContentsMargins(8, 4, 8, 4)
        self.metodo = Segmentado(["FFT", "Welch"])
        self.metodo.setToolTip(self.tr("FFT: um segmento só, sincronizado aos ciclos da fundamental (sem ela, o trecho "
                                       "inteiro com a janela Hann). Welch: a média de segmentos (o ruído e os "
                                       "supraharmônicos)"))
        self.metodo.escolhaMudou.connect(lambda i: self._mudar(metodo=METODOS[i]))
        self.resolucao = CampoComUnidade("Hz", 200.0, minimo=1e-3, digitos=4)
        self.resolucao.setObjectName("resolucao_welch")
        self.resolucao.setToolTip(self.tr("A resolução do Welch (a largura de cada bin)"))
        self.resolucao.setMaximumWidth(90)
        self.resolucao.valorMudou.connect(lambda v: self._mudar(resolucao_hz=v))
        self.escala = Segmentado(["dB", "RMS", "dBc"])
        self.escala.setToolTip(self.tr("dB: a amplitude de pico (dBV na tensão, como no adc_tool). RMS: o valor RMS "
                                       "de cada tom. dBc: relativa à fundamental"))
        self.escala.escolhaMudou.connect(lambda i: self._mudar(escala=ESCALAS[i]))
        self.trecho = Segmentado([self.tr("Janela"), self.tr("Cursores"), self.tr("Captura")])
        self.trecho.setToolTip(self.tr("O trecho de cada traço: a janela visível da vista de tempo, a região dos "
                                       "cursores dela (sem eles, a janela visível) ou a captura inteira"))
        self.trecho.escolhaMudou.connect(lambda i: self._mudar(trecho=TRECHOS[i]))
        self.log = QCheckBox(self.tr("Frequência log"))
        self.log.setObjectName("frequencia_log")
        self.log.clicked.connect(lambda marcado: self._mudar(frequencia_log=bool(marcado)))
        self.harmonicos = QCheckBox(self.tr("Harmônicos"))
        self.harmonicos.setObjectName("harmonicos")
        self.harmonicos.setToolTip(self.tr("Marca os harmônicos de f₁ (com a FFT sincronizada)"))
        self.harmonicos.clicked.connect(lambda marcado: self._mudar(harmonicos=bool(marcado)))
        self.diferenca = QCheckBox(self.tr("Diferença"))
        self.diferenca.setObjectName("diferenca")
        self.diferenca.setToolTip(self.tr("Os outros traços menos o primeiro, em dB, bin a bin: ponha na vista de "
                                          "tempo o mesmo canal de duas capturas (antes e depois de ligar uma carga, "
                                          "dois dias) e veja o que mudou"))
        self.diferenca.clicked.connect(lambda marcado: self._mudar(diferenca=bool(marcado)))
        self.cenelec = QCheckBox(self.tr("CENELEC"))
        self.cenelec.setObjectName("faixas_cenelec")
        self.cenelec.setToolTip(self.tr("Marca as faixas A (3 a 95 kHz), B (95 a 125 kHz), C (125 a 140 kHz) e D (140 "
                                        "a 148,5 kHz) da comunicação pela rede elétrica (EN 50065-1)"))
        self.cenelec.clicked.connect(lambda marcado: self._mudar(faixas_cenelec=bool(marcado)))
        for w in (self.metodo, self.resolucao, self.escala, self.trecho, self.log, self.harmonicos, self.diferenca,
                  self.cenelec):
            linha.addWidget(w)
        self.acao_ajustar = QAction(self.tr("Ajustar tudo"), self)
        self.acao_ajustar.setShortcut(QKeySequence("F"))
        self.acao_ajustar.setToolTip(self.tr("Ajustar tudo (F)"))
        self.acao_ajustar.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.acao_ajustar.triggered.connect(lambda: self.escalas.ajustar(0.02))
        self.addAction(self.acao_ajustar)
        IconeDoTema(self.acao_ajustar, "expandir")
        botao = QToolButton()
        botao.setObjectName("botao_ajustar")
        botao.setDefaultAction(self.acao_ajustar)
        botao.setAutoRaise(True)
        botao.setIconSize(QSize(16, 16))
        linha.addWidget(botao)
        # Os botões das ajudas de leitura: desligados ao abrir (cada um custa algo a cada resultado ou movimento).
        self.acao_picos = QAction(self.tr("Picos"), self)
        self.acao_picos.setToolTip(self.tr("Marcar os picos de cada traço (acima do piso + 20 dB, com 10 dB de "
                                           "proeminência)"))
        self.acao_valores = QAction(self.tr("Valores"), self)
        self.acao_valores.setToolTip(self.tr("Mostrar a frequência e o nível sob o mouse"))
        self.acao_cursores = QAction(self.tr("Cursores"), self)
        self.acao_cursores.setShortcut(QKeySequence("C"))
        self.acao_cursores.setToolTip(self.tr("Os cursores A e B, com a distância entre eles (C)"))
        self.botoes_de_leitura = {}
        for acao, nome in ((self.acao_picos, "picos"), (self.acao_valores, "valores"),
                           (self.acao_cursores, "cursores")):
            acao.setCheckable(True)
            acao.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.addAction(acao)
            botao = QToolButton()
            botao.setObjectName(f"botao_{nome}")
            botao.setDefaultAction(acao)
            botao.setAutoRaise(True)
            linha.addWidget(botao)
            self.botoes_de_leitura[nome] = botao
        linha.addWidget(botao_de_ajuda("espectro"))
        self.acao_destravar, self.acao_igualar = acoes_da_escala(self, self.destravar_selecionados,
                                                                 self.igualar_escalas)
        for acao, nome in ((self.acao_destravar, "destravar"), (self.acao_igualar, "igualar")):
            botao = QToolButton()
            botao.setObjectName(f"botao_{nome}")
            botao.setDefaultAction(acao)
            botao.setAutoRaise(True)
            botao.setIconSize(QSize(16, 16))
            linha.addWidget(botao)
            self.botoes_de_leitura[nome] = botao
        self.acao_picos.toggled.connect(lambda _: self._pedir())
        for tecla, passos in (("Left", -1), ("Right", 1), ("Shift+Left", -10), ("Shift+Right", 10)):
            andar = QAction(self)
            andar.setShortcut(QKeySequence(tecla))
            andar.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            andar.triggered.connect(lambda _=False, n=passos: self.andar_cursor(n))
            self.addAction(andar)
        self.acao_valores.toggled.connect(self._ligar_valores)
        self.acao_cursores.toggled.connect(self._ligar_cursores)

        self._legenda = QWidget()
        self._fluxo = LayoutDeFluxo(self._legenda)
        self._fluxo.setContentsMargins(10, 4, 10, 2)
        self.info = QLabel()
        self.info.setObjectName("info_espectro")
        self.info.setWordWrap(True)
        self.info.setContentsMargins(10, 0, 10, 4)

        self.eixo_x, self.eixo_y = EixoDoTema("bottom"), EixoDoTema("left")
        self.grafico = pg.PlotWidget(viewBox=CaixaComEscalas(), axisItems={"bottom": self.eixo_x, "left": self.eixo_y})
        self.escalas = EscalasDaCaixa(self.grafico.getViewBox(), self.eixo_y, parent=self)
        self.escalas.referenciaMudou.connect(self._rotular_y)
        self.escalas.cadeadoMudou.connect(self._escalas_mudaram)
        self.escalas.mudou.connect(self._escala_mudou)
        self._rotulo_desenhado: tuple | None = None
        self._estados_da_escala: dict[Traco, tuple[bool, bool]] = {}   # (travado, na comum) mostrado de cada traço
        self.grafico.setObjectName("grafico_espectro")
        self.grafico.setMenuEnabled(False)
        self.grafico.hideButtons()
        # Como na vista de tempo: a grade do tema (o showGrid fazia cada eixo redesenhar as linhas pela vista inteira a
        # cada quadro, metade do custo do pan), o eixo Y em cache (o pan da frequência não muda o Y) e os eixos
        # escondidos sem o prefixo SI automático (que refaz o HTML do rótulo a cada mudança).
        self.grade = GradeDoTema(self.eixo_x, self.eixo_y)
        self.grafico.getViewBox().addItem(self.grade, ignoreBounds=True)
        self.eixo_y.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        for lado in ("top", "right"):
            self.grafico.getPlotItem().getAxis(lado).enableAutoSIPrefix(False)
        self.grafico.setLabel("bottom", self.tr("frequência"), units="Hz")
        self.cursores = CursoresDaVista(para_eixo=self._x, do_eixo=self._f, parent=self)
        self.cursores.por_nas([self.grafico.getViewBox()])
        self.cursores.mudou.connect(self.emitir_regiao)
        caixa = self.grafico.getViewBox()
        self.anotacoes = AnotacoesDaVista(self.vista, self.projeto, lambda _numero: caixa, frequencia=True,
                                          para_eixo=self._x,
                                          do_eixo=self._f, separador=separador_decimal, parent=self)
        caixa.menuPedido.connect(lambda x, y, posicao: self.anotacoes.menu(caixa, 0, self._f(x), y,
                                                                         self.cursores.regiao(), posicao))
        self.valor_no_mouse = pg.TextItem(anchor=(0, 1))
        self.valor_no_mouse.setZValue(50)
        self.ponto_no_mouse = pg.ScatterPlotItem(size=7, pen=pg.mkPen(None))
        self.ponto_no_mouse.setZValue(49)
        for item in (self.valor_no_mouse, self.ponto_no_mouse):
            item.hide()
            self.grafico.addItem(item, ignoreBounds=True)
        self.grafico.scene().sigMouseMoved.connect(self._mouse_movido)

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(0)
        coluna.addWidget(barra)
        coluna.addWidget(self._legenda)
        coluna.addWidget(self.grafico, 1)
        coluna.addWidget(self.info)

    # ------------------------------------------------------------------ as opções

    @property
    def opcoes(self) -> esp.OpcoesDoEspectro:
        return self.vista.opcoes

    def _mudar(self, **mudancas) -> bool:
        try:
            nova = self.opcoes.com(**mudancas)
        except esp.OpcoesInvalidas as e:
            self.info.setText(str(e))
            self._mostrar_opcoes()
            return False
        if nova == self.opcoes:
            return False
        self.projeto.pilha.push(MudarOpcoesDaVista(self.vista, nova, juntar="resolucao_hz" in mudancas))
        return True

    def _mostrar_opcoes(self) -> None:
        o = self.opcoes
        for seg, valor, valores in ((self.metodo, o.metodo, METODOS), (self.escala, o.escala, ESCALAS),
                                    (self.trecho, o.trecho, TRECHOS)):
            seg.blockSignals(True)
            seg.escolher(valores.index(valor))
            seg.blockSignals(False)
        self.escala.habilitar(1, o.modo == "tom", self.tr("O valor RMS por bin só existe no modo tom"))
        self.resolucao.definir_valor(o.resolucao_hz)
        self.resolucao.setEnabled(o.metodo == "welch")
        self.log.setChecked(o.frequencia_log)
        self.harmonicos.setChecked(o.harmonicos)
        self.diferenca.setChecked(o.diferenca)
        self.diferenca.setEnabled(o.escala != "rms")
        self.cenelec.setChecked(o.faixas_cenelec)
        if self._log_desenhado is not None:
            self._desenhar_faixas()

    def _vista_mudou(self, _vista, campos) -> None:
        if "opcoes" in campos and isValid(self):
            antes, self._opcoes_vistas = self._opcoes_vistas, self.opcoes
            if antes is None:
                self._ajustar = True
            elif any(getattr(antes, n) != getattr(self.opcoes, n) for n in OPCOES_DA_UNIDADE_DO_Y):
                self._ajustar_y = True
            self._mostrar_opcoes()
            self._pedir()

    # ------------------------------------------------------------------ a vista de tempo ligada

    def vista_de_tempo(self):
        """O widget da vista de tempo ligada (ou None, se ela fechou)."""
        widget = self._achar_vista_de_tempo(self.opcoes.vista_de_tempo)
        if widget is not self._tempo:
            if self._tempo is not None and isValid(self._tempo):
                for sinal, slot in self._ligacoes():
                    try:
                        sinal.disconnect(slot)
                    except (RuntimeError, TypeError):
                        pass
            self._tempo = widget
            if widget is not None:
                for sinal, slot in self._ligacoes():
                    sinal.connect(slot)
        return widget

    def _ligacoes(self):
        t = self._tempo
        return ((t.regiaoMudou, self._regiao_de_la), (t.vista.tracoEntrou, self._tracos_de_la),
                (t.vista.tracoSaiu, self._tracos_de_la), (t.vista.tracoMudou, self._traco_de_la))

    def _vistas_do_projeto(self, *_):
        if isValid(self):
            QTimer.singleShot(0, self._pedir)       # o widget da vista nova nasce depois do sinal

    def _regiao_de_la(self, *_):
        if self.opcoes.trecho != "captura":
            self._pedir()

    def _tracos_de_la(self, *_):
        self._pedir()

    def _traco_de_la(self, _traco, campos):
        if campos & {"cadeia", "ganho", "visivel", "cor", "nome", "deslocamento_s", "unidade", "fonte"}:
            self._pedir()

    def _materializacao_mudou(self, estado) -> None:
        if isValid(self) and estado.pronta is not None and any(r.aguardando for r in self.resultados):
            self._pedir()
        if isValid(self):
            self._mostrar_progresso()

    # ------------------------------------------------------------------ a conta

    def _pedir(self, *_) -> None:
        if isValid(self):
            self._espera.start()

    def _trechos(self) -> tuple[list, str]:
        """Os pedidos de cada traço visível da vista de tempo, e uma nota sobre o trecho."""
        tempo = self.vista_de_tempo()
        if tempo is None:
            return [], self.tr("Nenhuma vista de tempo para seguir: plote um canal.")
        o, nota = self.opcoes, ""
        janela = tempo.janela_de_tempo()
        regiao = janela
        if o.trecho == "cursores":
            if tempo.cursores is None:
                nota = self.tr("Sem os cursores na vista de tempo (C): a janela visível.")
            else:
                regiao = tuple(sorted(tempo.cursores))
        pedidos = []
        for traco in tempo.vista.tracos:
            r = traco.receita
            if not r.visivel:
                continue
            try:
                fonte = self.projeto.fonte(r.fonte)
            except KeyError:
                continue
            if fonte.esta_ausente:
                continue
            canal = fonte.canal(r.canal)
            n = len(canal.amostras)
            if o.trecho == "captura" or regiao is None:
                a, b = 0, n
            else:
                inicio, fim = tempo.regiao_do_traco(traco, *regiao)        # o trecho dele na tela (tempo próprio)
                a = int(min(max(round((inicio - r.deslocamento_s) * canal.taxa_hz), 0), n))
                b = int(min(max(round((fim - r.deslocamento_s) * canal.taxa_hz), 0), n))
            estado = self.materializacoes.estado_de(traco)
            pronta = estado.pronta.amostras if estado is not None and estado.pronta is not None else None
            contexto = self.materializacoes.contexto(fonte, r.canal)
            pedidos.append((traco, r.unidade_de(canal.unidade), esp.TrechoDoTraco(fonte.fonte.captura, r.canal, r.cadeia, contexto,
                                                                    a, b, r.ganho, pronta)))
        return pedidos, nota

    def _calcular(self) -> None:
        """Calcula o que falta (o espectro de um trecho novo, o desenho de uma escala nova) em segundo plano; o que
        já foi calculado é reaproveitado, e sem nada novo a vista só se redesenha."""
        if not isValid(self):
            return
        if self._tarefa is not None and self._tarefa.ativa:
            self._tarefa.cancelar()
        pedidos, nota = self._trechos()
        self._nota = nota
        o = self.opcoes
        parametros = o.parametros
        itens = []
        for traco, unidade, trecho in pedidos:
            r = traco.receita
            chave = (id(traco), r.fonte, r.canal, r.cadeia, r.ganho, trecho.inicio, trecho.fim, parametros)
            itens.append((traco, unidade, trecho, chave, (chave, o.escala, self._n_picos(), o.harmonicos)))
        faltam = [item for item in itens if item[4] not in self._desenhos]
        if not faltam:
            self._mostrar_resultados(o, itens, {}, {}, {})
            return
        prontos = dict(self._espectros)
        n_picos = self._n_picos()

        def calcular(progresso, cancelado):
            espectros, desenhos, falhas = {}, {}, {}
            for k, (_traco, _unidade, trecho, chave, chave_do_desenho) in enumerate(faltam):
                if cancelado():
                    raise api.Cancelado()
                espectro = prontos.get(chave)
                if espectro is None:
                    try:
                        espectro = esp.espectro_do_trecho(trecho, parametros, cancelado=cancelado,
                                                          progresso=lambda f, k=k: progresso((k + f) / len(faltam)))
                    except esp.AguardandoMaterializacao:
                        falhas[chave_do_desenho] = (True, "")
                        continue
                    except api.ErroSHAN as e:
                        falhas[chave_do_desenho] = (False, str(e))
                        continue
                    espectros[chave] = espectro
                desenhos[chave_do_desenho] = esp.preparar_desenho(espectro, o.escala, n_picos, o.harmonicos)
            return o, itens, espectros, desenhos, falhas

        grande = sum(item[2].n_amostras for item in faltam) > AMOSTRAS_PARA_MOSTRAR_A_TAREFA
        self._tarefa = self.tarefas.iniciar(self.tr("Espectro de {}").format(self.vista.nome), calcular,
                                            f"espectro-{self.vista.id}", mostrar=grande, ao_terminar=self._terminou)

    def _terminou(self, tarefa) -> None:
        if tarefa is not self._tarefa or not isValid(self):
            return
        self._tarefa = None
        if tarefa.estado == "concluida":
            self._mostrar_resultados(*tarefa.resultado)
        elif tarefa.estado == "falhou":
            self.info.setText(tarefa.erro)

    def _mostrar_resultados(self, opcoes, itens, espectros, desenhos, falhas) -> None:
        """Junta o que acabou de ser calculado ao que já estava, guarda só o que os trechos de agora usam (um
        espectro de 6 M bins tem ~100 MB) e desenha."""
        todos_os_espectros = {**self._espectros, **espectros}
        todos_os_desenhos = {**self._desenhos, **desenhos}
        self._espectros = {item[3]: todos_os_espectros[item[3]] for item in itens if item[3] in todos_os_espectros}
        self._desenhos = {item[4]: todos_os_desenhos[item[4]] for item in itens if item[4] in todos_os_desenhos}
        resultados = []
        for traco, unidade, trecho, chave, chave_do_desenho in itens:
            if chave_do_desenho in self._desenhos:
                resultados.append(ResultadoDoTraco(traco, self._espectros.get(chave), self._desenhos[chave_do_desenho],
                                                   unidade=unidade, trecho=trecho))
            else:
                aguardando, erro = falhas.get(chave_do_desenho, (False, ""))
                resultados.append(ResultadoDoTraco(traco, erro=erro, aguardando=aguardando, unidade=unidade,
                                                   trecho=trecho))
        if opcoes.diferenca and opcoes.escala != "rms" and sum(r.desenho is not None for r in resultados) > 1:
            # Comparar: os outros menos o primeiro (os espectros e os números da tabela continuam os de cada um).
            diferencas = esp.em_diferenca([r.desenho for r in resultados])
            resultados = [ResultadoDoTraco(r.traco, r.espectro, d, r.erro, r.aguardando, r.unidade, r.trecho)
                          for r, d in zip(resultados, diferencas)]
        self.opcoes_calculadas, self.resultados = opcoes, resultados
        self._desenhar()
        self.calculado.emit()

    def fundamental(self) -> float | None:
        """A fundamental que sincronizou o primeiro espectro mostrado (None: Welch, ou sem sincronismo)."""
        return next((r.espectro.f0_hz for r in self.resultados
                     if r.espectro is not None and r.espectro.f0_hz is not None), None)

    def soltar(self) -> None:
        """A vista vai sair: a conta em andamento é cancelada."""
        if self._tarefa is not None and self._tarefa.ativa:
            self._tarefa.cancelar()
        self._espera.stop()

    def emitir_regiao(self) -> None:
        """As medidas dos cursores para a tabela de Medidas (sem os cursores, nada a medir)."""
        if isValid(self):
            self.medidasMudaram.emit(self.medidas())

    # ------------------------------------------------------------------ o desenho

    def niveis(self, resultado: ResultadoDoTraco) -> np.ndarray:
        """Os níveis de um traço na escala da vista (todos os bins)."""
        return resultado.desenho.niveis

    def _resultado_da_referencia(self) -> ResultadoDoTraco | None:
        """O resultado do traço que o eixo Y mostra (graficos/escalas.py), ou o primeiro com espectro."""
        com_espectro = [r for r in self.resultados if r.espectro is not None]
        referencia = self.escalas.referencia
        return next((r for r in com_espectro if r.traco is referencia), com_espectro[0] if com_espectro else None)

    def _rotulo_y(self) -> str:
        r = self._resultado_da_referencia()
        unidade = r.unidade if r is not None else "V"
        escala = self.opcoes.escala
        if escala == "rms":
            return self.tr("valor RMS ({})").format(unidade)
        if self._em_diferenca():
            primeiro = next((x for x in self.resultados if x.desenho is not None), None)
            return self.tr("diferença para {} (dB)").format(primeiro.traco.receita.nome if primeiro else "")
        if escala == "dbc":
            return "dBc"
        return r.espectro.rotulo(unidade) if r is not None else ""

    def _em_diferenca(self) -> bool:
        o = self.opcoes_calculadas or self.opcoes
        return o.diferenca and o.escala != "rms" and sum(r.desenho is not None for r in self.resultados) > 1

    def _rotular_y(self) -> None:
        """O rótulo do eixo Y: o do traço de referência; com unidades ou escalas diferentes entre os traços, na cor
        dele."""
        if not isValid(self):
            return
        r = self._resultado_da_referencia()
        com_espectro = [x for x in self.resultados if x.espectro is not None]
        mistura = (len({x.unidade for x in com_espectro}) > 1 and self.opcoes.escala != "dbc") or \
            any(not self.escalas.escala(x.traco).comum for x in com_espectro)
        cor = cor_do_traco(r.traco.receita.cor, aparencia().tema)[0] if r is not None and mistura else None
        rotulo = (self._rotulo_y(), cor)
        if rotulo != self._rotulo_desenhado:
            self._rotulo_desenhado = rotulo
            self.eixo_y.definir_rotulo(rotulo[0], "", cor)

    # ------------------------------------------------------------------ as escalas dos traços

    def _selecionados_aqui(self) -> list[Traco]:
        return [t for t in self.selecao.tracos if t in self.curvas]

    def destravar_selecionados(self, destravar: bool = True) -> None:
        """O cadeado: os traços selecionados passam a ter a escala do Y deles (ou voltam a andar com os outros)."""
        self.escalas.travar(self._selecionados_aqui(), travar=not destravar)
        self._escalas_mudaram()

    def igualar_escalas(self) -> None:
        """"Mesma escala": os selecionados (sem seleção, todos os traços) voltam à escala comum."""
        self.escalas.igualar(self._selecionados_aqui() or list(self.curvas))
        self._escalas_mudaram()

    def _travado_e_comum(self, traco: Traco) -> tuple[bool, bool]:
        return self.escalas.travado(traco), self.escalas.escala(traco).comum

    def _escala_mudou(self, traco: Traco) -> None:
        """A escala de um traço mudou (um gesto, o ajuste): as marcas dele e, se ela passou da comum para a própria
        (ou voltou), o chip, os botões e o rótulo."""
        if not isValid(self):
            return
        self._espera_das_marcas.start()
        if self._estados_da_escala.get(traco) != self._travado_e_comum(traco):
            self._escalas_mudaram()

    def _escalas_mudaram(self) -> None:
        """Um traço foi destravado, travado ou igualado: os chips, os botões e o rótulo do eixo."""
        if not isValid(self):
            return
        self._estados_da_escala = {t: self._travado_e_comum(t) for t in self.curvas}
        for traco, chip in self.chips.items():
            chip.definir(escala=estado_do_chip(*self._travado_e_comum(traco)))
        selecionados = self._selecionados_aqui()
        atualizar_acoes_da_escala(self.acao_destravar, self.acao_igualar,
                                  [self._travado_e_comum(t) for t in selecionados],
                                  [self._travado_e_comum(t) for t in (selecionados or list(self.curvas))])
        self._rotular_y()

    def _desenhar_faixas(self) -> None:
        """As faixas A a D da EN 50065-1, atrás dos traços (fora do ajuste automático), com a letra no alto."""
        if not hasattr(self, "_faixas"):
            self._faixas = []
            for nome, _f0, _f1 in FAIXAS_CENELEC:
                regiao = pg.LinearRegionItem(movable=False)
                regiao.setZValue(-20)
                for linha in regiao.lines:
                    linha.setPen(pg.mkPen(None))
                rotulo = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(None), label=nome,
                                         labelOpts={"position": 0.96, "anchors": [(0.5, 0), (0.5, 0)]})
                rotulo.setZValue(-19)
                self.grafico.addItem(regiao, ignoreBounds=True)
                self.grafico.addItem(rotulo, ignoreBounds=True)
                self._faixas.append((regiao, rotulo))
            self._colorir_faixas(aparencia().tema)
        ligadas = self.opcoes.faixas_cenelec
        for (regiao, rotulo), (_nome, f0, f1) in zip(self._faixas, FAIXAS_CENELEC, strict=True):
            regiao.setVisible(ligadas)
            rotulo.setVisible(ligadas)
            if ligadas:
                regiao.setRegion((self._x(f0), self._x(f1)))
                rotulo.setValue(self._x(math.sqrt(f0 * f1)) if self.opcoes.frequencia_log else self._x((f0 + f1) / 2))

    def _colorir_faixas(self, t: Tema) -> None:
        for k, (regiao, rotulo) in enumerate(getattr(self, "_faixas", ())):
            cor = QColor(t.mudo)
            cor.setAlpha(30 if k % 2 == 0 else 16)
            regiao.setBrush(pg.mkBrush(cor))
            rotulo.label.setColor(QColor(t.mudo))
            rotulo.label.setFont(fonte_da_interface(TAMANHOS["secundario"]))

    def _x(self, f: float) -> float:
        """A posição de ``f`` no eixo (log10 na frequência logarítmica: é como o PyQtGraph posiciona os itens)."""
        return math.log10(max(f, 1e-12)) if self.opcoes.frequencia_log else f

    def _desenhar(self) -> None:
        t = aparencia().tema
        o = self.opcoes
        prontos = [r for r in self.resultados if r.desenho is not None]
        for traco in [tr for tr in self.curvas if tr not in {r.traco for r in prontos}]:
            self.grafico.removeItem(self.curvas.pop(traco))
        vb = self.grafico.getViewBox()
        trocou_o_log = self._log_desenhado is not None and self._log_desenhado != o.frequencia_log
        if trocou_o_log:
            x0, x1 = vb.viewRange()[0]
            faixa_hz = (10.0 ** x0, 10.0 ** x1) if self._log_desenhado else (x0, x1)
        self.grafico.setLogMode(x=o.frequencia_log, y=False)
        if trocou_o_log or self._log_desenhado is None:
            self.anotacoes.refazer()                  # as posições no eixo mudaram (o log10 da frequência)
        self._log_desenhado = o.frequencia_log
        if trocou_o_log:
            # O PyQtGraph liga o ajuste automático ao trocar a escala: a mesma faixa de frequências, na escala nova.
            vb.disableAutoRange()
            vb.setXRange(*self._faixa_no_eixo(faixa_hz, prontos), padding=0)
        self.cursores.reposicionar()
        self._desenhar_faixas()
        for r in prontos:
            self._curva(r, QColor(cor_do_traco(r.traco.receita.cor, t)[0]))
        self.escalas.definir_itens({r.traco: self.curvas[r.traco] for r in prontos})
        self.escalas.definir_selecao(self.selecao.tracos)
        self._prontos_desenhados = prontos
        self._redesenhar_marcas()
        if o.frequencia_log:
            self._atualizar_envoltorias(inteira=True)
        if self._ajustar and prontos:
            self._ajustar = self._ajustar_y = False
            vb.autoRange(padding=0.02)
            if self._faixa_pedida is not None:              # a do projeto: o x dela, o y do ajuste
                self.mostrar_frequencias(*self._faixa_pedida)
        elif self._ajustar_y and prontos:
            self._ajustar_y = False
            limites = list(self._limites_y_visiveis(prontos).values())
            if limites:
                vb.setYRange(min(a for a, _ in limites), max(b for _, b in limites), padding=0.05)
            # O Y mede outra coisa: a escala própria de antes não vale (depois do ajuste, que a acompanharia).
            self.escalas.igualar(self.escalas.tracos)
        elif prontos:
            self.escalas.manter(self._limites_y_visiveis(prontos))
        self._refazer_legenda()
        self._escalas_mudaram()
        self._mostrar_info()
        if self.cursores.ligados:
            self.emitir_regiao()              # os níveis nos cursores mudaram com o espectro

    def _faixa_no_eixo(self, faixa_hz: tuple[float, float], prontos) -> tuple[float, float]:
        """Uma faixa de frequências (Hz) no eixo x da escala atual; na log, a partir do primeiro bin acima de 0 Hz."""
        f0, f1 = faixa_hz
        if not self.opcoes.frequencia_log:
            return f0, f1
        menor = min((r.desenho.f0 + r.desenho.df for r in prontos), default=1.0)
        f0 = max(f0, menor)
        return math.log10(f0), math.log10(f1 if f1 > f0 else f0 * 10)      # vazia (toda abaixo de 0 Hz): uma década

    def _limites_y_visiveis(self, prontos) -> dict[Traco, tuple[float, float]]:
        """O mínimo e o máximo de cada espectro desenhado nas frequências visíveis (na unidade dele)."""
        x0, x1 = self.grafico.getViewBox().viewRange()[0]
        f0, f1 = (10.0 ** x0, 10.0 ** x1) if self.opcoes.frequencia_log else (x0, x1)
        limites = {}
        for r in prontos:
            d = r.desenho
            i0 = max(0, math.ceil((f0 - d.f0) / d.df))
            i1 = min(len(d.niveis), math.floor((f1 - d.f0) / d.df) + 1)
            trecho = d.niveis[i0:i1] if i1 > i0 else d.niveis[:0]
            trecho = trecho[np.isfinite(trecho)]
            if len(trecho):
                limites[r.traco] = (float(trecho.min()), float(trecho.max()))
        return limites

    def _curva(self, r: ResultadoDoTraco, cor: QColor) -> None:
        """O item do traço: o ``TracoLOD`` sobre a pirâmide do espectro na frequência linear (os bins são uniformes:
        o bin ``i`` em ``f0 + i·df``); na log, uma curva com a envoltória por coluna."""
        d, item = r.desenho, self.curvas.get(r.traco)
        if not self.opcoes.frequencia_log:
            if not isinstance(item, TracoLOD):
                if item is not None:
                    self.grafico.removeItem(item)
                item = TracoLOD(d.piramide, d.niveis, 1.0 / d.df, t0=d.f0, cor=cor, nome=r.traco.nome)
                self.grafico.addItem(item)
                self.curvas[r.traco] = item
            elif item.dados[0] is not d.piramide:
                # A grade inteira do espectro novo: o espaçamento dos bins e o número deles mudam com o trecho e o
                # método (sem isso, um pico de 130 kHz aparecia em 377 kHz, e o eixo passava da Nyquist).
                item.definir_dados(d.piramide, d.niveis, taxa_hz=1.0 / d.df, t0=d.f0, n_total=len(d.niveis))
            item.definir_cor(cor)
            item.setZValue(10 if r.traco in self.selecao.tracos else 0)
            return
        if not isinstance(item, pg.PlotDataItem):
            if item is not None:
                self.grafico.removeItem(item)
            item = pg.PlotDataItem()
            self.grafico.addItem(item)
            self.curvas[r.traco] = item
        caneta = QPen(cor, 1.0)
        caneta.setCosmetic(True)
        item.setPen(caneta)
        item.setZValue(10 if r.traco in self.selecao.tracos else 0)

    def _selecao_mudou(self, selecionados) -> None:
        """O traço selecionado (num chip, numa curva, em outra vista) acende o chip e vem para cima no desenho."""
        if not isValid(self):
            return
        for traco, chip in self.chips.items():
            chip.definir(selecionado=traco in selecionados)
        for traco, item in self.curvas.items():
            item.setZValue(10 if traco in selecionados else 0)
        self.escalas.definir_selecao(selecionados)
        self._escalas_mudaram()

    def faixa_de_frequencia(self) -> tuple[float, float]:
        """A frequência visível (Hz), na escala linear ou na log."""
        x0, x1 = self.grafico.getViewBox().viewRange()[0]
        return (10.0 ** x0, 10.0 ** x1) if self.opcoes.frequencia_log else (x0, x1)

    def mostrar_frequencias(self, f0: float, f1: float) -> None:
        """Mostra ``[f0, f1]`` (Hz) no eixo da frequência, sem mexer no Y (os eixos ligados da grade, a janela do
        projeto); na escala log, o que fica abaixo de 0 Hz não aparece. Sem espectro ainda, fica pedida: vale quando
        o primeiro chegar, no lugar do ajuste automático do x."""
        if not self.resultados:
            self._faixa_pedida = (f0, f1)
            return
        self._faixa_pedida = None
        if self.opcoes.frequencia_log:
            if f1 <= 0:
                return
            f0 = f0 if f0 > 0 else f1 / 1e3
            self.grafico.getViewBox().setXRange(math.log10(f0), math.log10(f1), padding=0)
        elif f1 > f0:
            self.grafico.getViewBox().setXRange(f0, f1, padding=0)

    @property
    def tem_dados(self) -> bool:
        return bool(self.resultados)

    def _zoom_mudou(self, *_) -> None:
        if isValid(self):
            self.frequenciaMudou.emit(*self.faixa_de_frequencia())
        if self.opcoes.frequencia_log:
            self._espera_da_envoltoria.start()

    def _atualizar_envoltorias(self, inteira: bool = False) -> None:
        """Na frequência log, a envoltória de cada traço para as colunas da faixa visível (com meia faixa de folga
        de cada lado: o pan curto não espera)."""
        if not isValid(self) or not self.opcoes.frequencia_log:
            return
        vb = self.grafico.getViewBox()
        tela = self.grafico.devicePixelRatioF() or 1.0
        colunas = max(64, int(vb.width() * tela))
        for r in self.resultados:
            item = self.curvas.get(r.traco)
            if r.desenho is None or not isinstance(item, pg.PlotDataItem):
                continue
            d = r.desenho
            if inteira:
                f_min, f_max = d.f0 + d.df, d.f0 + d.df * (len(d.niveis) - 1)
            else:
                x0, x1 = vb.viewRange()[0]
                largura = x1 - x0
                f_min, f_max = 10 ** (x0 - largura / 2), 10 ** (x1 + largura / 2)
            item.setData(*esp.envoltoria_log(d, f_min, f_max, 2 * colunas))

    def _clique_no_grafico(self, evento) -> None:
        """Um clique numa curva seleciona o traço dela (e o inspetor mostra o traço e a análise do espectro), e no
        vazio tira a seleção. Em cima dos eixos, nada. O segundo clique de um duplo clique também não faz nada: o
        primeiro já selecionou, e o zoom fica onde o usuário o pôs."""
        vb = self.grafico.getViewBox()
        if evento.button() != Qt.MouseButton.LeftButton or evento.double():
            return
        if not vb.sceneBoundingRect().contains(evento.scenePos()):
            return
        ponto = vb.mapSceneToView(evento.scenePos())
        self.tracoClicado.emit(self.traco_em(ponto.x(), ponto.y()), evento.modifiers())

    def traco_em(self, x: float, y: float) -> Traco | None:
        """O traço da curva mais perto de ``(x, y)`` (nas unidades da vista) dentro do alcance do clique; empatados,
        o desenhado por cima (``graficos/clique.py``)."""
        largura, altura = self.grafico.getViewBox().viewPixelSize()
        candidatos = []
        for k, (traco, item) in enumerate(self.curvas.items()):
            if not item.isVisible():
                continue
            if isinstance(item, TracoLOD):
                distancia = item.distancia_em_pixels(x, y)
            else:                                   # a envoltória da frequência log: a linha que está desenhada
                xs, ys = item.getData()
                e = self.escalas.escala(traco)
                distancia = math.inf if xs is None else distancia_a_linha(x, y, e.x.k * xs + e.x.c, e.y.k * ys + e.y.c,
                                                                          largura, altura)
            candidatos.append((distancia, (item.zValue(), k), traco))
        return mais_perto(candidatos)

    def _redesenhar_marcas(self) -> None:
        """As marcas de todos os traços desenhados, cada uma na escala do seu traço."""
        if not isValid(self):
            return
        for item in self._marcas_desenhadas:
            self.grafico.removeItem(item)
        self._marcas_desenhadas = []
        t = aparencia().tema
        for k, r in enumerate(self._prontos_desenhados):
            if r.traco in self.curvas:
                self._desenhar_marcas(r, QColor(cor_do_traco(r.traco.receita.cor, t)[0]), k == 0, t)

    def _desenhar_marcas(self, r: ResultadoDoTraco, cor: QColor, primeiro: bool, t: Tema) -> None:
        e, m, o, d = r.espectro, r.marcas, self.opcoes, r.desenho
        escala = self.escalas.escala(r.traco)

        def nivel(f: float) -> float:                  # na vista: pela escala do traço
            return escala.y.na_vista(d.nivel_em(f))

        if m.picos:
            pontos = pg.ScatterPlotItem([self._x(p.frequencia_hz) for p in m.picos], [nivel(p.frequencia_hz)
                                        for p in m.picos], symbol="t", size=9, brush=cor, pen=pg.mkPen(None))
            pontos.setZValue(20)
            self.grafico.addItem(pontos, ignoreBounds=True)
            self._marcas_desenhadas.append(pontos)
            if primeiro:
                for p in m.picos:
                    texto = pg.TextItem(formatar_si(p.frequencia_hz, "Hz", 4), color=t.texto2, anchor=(0.5, 1.6))
                    texto.setPos(self._x(p.frequencia_hz), nivel(p.frequencia_hz))
                    self.grafico.addItem(texto, ignoreBounds=True)
                    self._marcas_desenhadas.append(texto)
        if primeiro and math.isfinite(m.piso_db) and o.escala != "rms":
            piso = m.piso_db if o.escala == "db" else m.piso_db + float(d.niveis[0] - e.db[0])
            linha = pg.InfiniteLine(pos=escala.y.na_vista(piso), angle=0, movable=False,
                                    pen=pg.mkPen(QColor(t.mudo), width=1, style=Qt.PenStyle.DashLine),
                                    label=self.tr("piso"), labelOpts={"position": 0.02, "color": t.mudo})
            self.grafico.addItem(linha, ignoreBounds=True)
            self._marcas_desenhadas.append(linha)
        if primeiro and o.harmonicos and m.harmonicos_hz:
            linhas = LinhasVerticais([self._x(f) for f in m.harmonicos_hz],
                                     pg.mkPen(QColor(t.borda_forte), width=1, style=Qt.PenStyle.DotLine))
            linhas.setZValue(-10)
            self.grafico.addItem(linhas, ignoreBounds=True)
            self._marcas_desenhadas.append(linhas)
        # A faixa válida do perfil de sonda (na cor do traço), se a cadeia corrige a sonda.
        etapa = next((s for s in r.traco.receita.cadeia.ligadas if isinstance(s, CorrecaoSonda)), None)
        if etapa is not None:
            try:
                fonte = self.projeto.fonte(r.traco.receita.fonte)
                perfil = etapa.perfil_usado(self.materializacoes.contexto(fonte, r.traco.receita.canal))
            except (KeyError, api.ErroSHAN):
                perfil = None
            faixa = perfil.faixa_valida if perfil is not None else None
            if faixa is not None:
                fundo = QColor(cor)
                fundo.setAlpha(22)
                regiao = pg.LinearRegionItem([self._x(f) for f in faixa], movable=False, brush=fundo,
                                             pen=pg.mkPen(cor, width=1, style=Qt.PenStyle.DashLine))
                regiao.setZValue(-19)
                regiao.setToolTip(self.tr("A faixa válida do perfil {} ({} a {})").format(
                    perfil.id, formatar_si(faixa[0], "Hz", 3), formatar_si(faixa[1], "Hz", 3)))
                self.grafico.addItem(regiao, ignoreBounds=True)
                self._marcas_desenhadas.append(regiao)

    def _refazer_legenda(self) -> None:
        self._fluxo.limpar()
        self.chips = {}
        for r in self.resultados:
            receita = r.traco.receita
            resumo = receita.cadeia.resumo()
            if r.erro:
                resumo = (resumo + " · " if resumo else "") + self.tr("erro")
            chip = ChipDeTraco(receita.nome, receita.cor, resumo)
            try:
                fonte = self.projeto.fonte(receita.fonte)
            except KeyError:
                fonte = None
            if fonte is not None and fonte not in self._fontes_ouvidas:
                self._fontes_ouvidas.add(fonte)          # a integridade conferida muda o aviso do chip
                fonte.estadoMudou.connect(self._estado_da_fonte)
            chip.definir(selecionado=r.traco in self.selecao.tracos,
                         avisos=self.materializacoes.avisos(r.traco, fonte, r.erro),
                         escala=estado_do_chip(*self._travado_e_comum(r.traco)))
            chip.clicado.connect(lambda t=r.traco: self.tracoClicado.emit(t, Qt.KeyboardModifier.NoModifier))
            self._fluxo.addWidget(chip)
            self.chips[r.traco] = chip
        self._mostrar_progresso()

    def _estado_da_fonte(self, fonte) -> None:
        if not isValid(self):
            return
        for r in self.resultados:
            chip = self.chips.get(r.traco)
            if chip is not None and r.traco.receita.fonte == fonte.id:
                chip.definir(avisos=self.materializacoes.avisos(r.traco, fonte, r.erro))

    def _mostrar_progresso(self) -> None:
        for r in self.resultados:
            chip = self.chips.get(r.traco)
            if chip is None or not r.aguardando:
                continue
            estado = self.materializacoes.estado_de(r.traco)
            chip.definir(progresso=estado.progresso if estado is not None else None)

    def _mostrar_info(self) -> None:
        partes = [self._nota] if getattr(self, "_nota", "") else []
        prontos = [r for r in self.resultados if r.espectro is not None]
        if prontos:
            e = prontos[0].espectro
            if e.parametros.metodo == "welch":
                baixo, alto = intervalo_do_welch(e)
                partes.append(self.tr("Welch · {} · {} · {} segmentos · IC 95 % de cada bin: {} / +{} dB").format(
                    e.rotulo_janela, formatar_si(e.resolucao_hz, "Hz", 3), e.n_segmentos,
                    decimal(f"{baixo:.2f}").replace("-", "−"), decimal(f"{alto:.2f}")))
            else:
                sinc = (self.tr(" · f₁ = {} · {} ciclos").format(formatar_si(e.f0_hz, "Hz", 6), e.n_ciclos)
                        if e.f0_hz else "")
                partes.append(self.tr("FFT · {} · {}{}").format(e.rotulo_janela, formatar_si(e.resolucao_hz, "Hz", 3),
                                                                sinc))
            partes.append(self.tr("{} de trecho").format(formatar_si(e.n_amostras / e.taxa_hz, "s", 4)))
            partes += [a.texto for a in e.avisos if "sincronizar" in a.texto]
            limite = limite_das_imagens_hz(e.taxa_hz)
            suspeitos = {round(p.frequencia_hz) for r in prontos if r.marcas is not None for p in r.marcas.picos
                         if p.frequencia_hz >= limite}
            if suspeitos:
                partes.append(self.tr("⚠ {} pico(s) acima de {} podem ser imagens: uma entrada em fs − f chega menos "
                                      "de 20 dB abaixo, pelo filtro do ADC (o assistente de aliasing separa)").format(
                                          len(suspeitos), formatar_si(limite, "Hz", 3)))
        if any(r.aguardando for r in self.resultados):
            partes.append(self.tr("aguardando a transformação da captura inteira"))
        partes += [f"{r.traco.nome}: {r.erro}" for r in self.resultados if r.erro]
        self.info.setText(" · ".join(partes))

    # ------------------------------------------------------------------ as ajudas de leitura

    def _n_picos(self) -> int:
        return self.opcoes.picos if self.acao_picos.isChecked() else 0

    def _f(self, x: float) -> float:
        """A frequência de uma posição no eixo (o inverso de ``_x``)."""
        return 10 ** min(max(float(x), -3.0), 9.0) if self.opcoes.frequencia_log else float(x)

    def _pixel_em_hz(self, f: float) -> float:
        """Quantos Hz cabem num pixel perto de ``f`` (na log, depende da frequência)."""
        vb = self.grafico.getViewBox()
        x0, x1 = vb.viewRange()[0]
        por_pixel = (x1 - x0) / max(vb.width(), 1.0)
        if self.opcoes.frequencia_log:
            return f * (10 ** por_pixel - 1)
        return por_pixel

    def _mais_alto_perto(self, d: esp.Desenho, f: float, pixels: float) -> int:
        """O bin mais alto a até ``pixels`` pixels de ``f`` (de perto, o bin mais próximo)."""
        largura = pixels * self._pixel_em_hz(f)
        i0, i1 = d.indice(f - largura), d.indice(f + largura) + 1
        return i0 + int(np.argmax(d.niveis[i0:i1]))

    def _unidade_do_nivel(self, r: ResultadoDoTraco) -> str:
        return r.unidade if self.opcoes.escala == "rms" else ("dBc" if self.opcoes.escala == "dbc" else "dB")

    def _texto_do_nivel(self, valor: float, r: ResultadoDoTraco) -> str:
        if self.opcoes.escala == "rms":
            return formatar_si(valor, r.unidade, 5)
        return decimal(f"{valor:.2f} {self._unidade_do_nivel(r)}").replace("-", "−")

    def _ligar_cursores(self, ligar: bool) -> None:
        if ligar:
            x0, x1 = self.grafico.getViewBox().viewRange()[0]
            self.cursores.ligar((self._f(x0), self._f(x1)))
        else:
            self.cursores.desligar()

    def andar_cursor(self, passos: int) -> bool:
        """As setas: o cursor ativo anda ``passos`` bins (do primeiro traço)."""
        d = next((r.desenho for r in self.resultados if r.desenho is not None), None)
        return d is not None and self.cursores.andar(passos, d.df)

    def medidas(self) -> MedidasDaVista | None:
        """As medidas dos cursores: a frequência de C1 e de C2, Δf, e o nível de cada traço no bin de cada um e a
        diferença, na escala da vista (para a tabela de Medidas)."""
        regiao = self.cursores.posicoes
        prontos = [r for r in self.resultados if r.desenho is not None]
        if regiao is None:
            return None
        c1, c2 = regiao
        resumo = self.tr("Cursores: {} → {} · Δf {}").format(formatar_si(c1, "Hz", 7), formatar_si(c2, "Hz", 7),
                                                              formatar_si(c2 - c1, "Hz", 6))
        colunas = (self.tr("Nível em C1"), self.tr("Nível em C2"), self.tr("Δ nível"))
        linhas, planilha = [], ["\t".join(["Traço", "Unidade", "C1 (Hz)", "C2 (Hz)", "Nível em C1", "Nível em C2",
                                             "Δ nível"])]
        for r in prontos:
            d = r.desenho
            n1, n2 = d.nivel_em(c1), d.nivel_em(c2)
            delta = (formatar_si(n2 - n1, r.unidade, 5) if self.opcoes.escala == "rms"
                     else decimal(f"{n2 - n1:.2f} dB").replace("-", "−"))
            linhas.append(LinhaDaTabela(r.traco, (self._texto_do_nivel(n1, r), self._texto_do_nivel(n2, r), delta)))
            planilha.append("\t".join([r.traco.nome, self._unidade_do_nivel(r), numero_para_planilha(c1),
                                        numero_para_planilha(c2), numero_para_planilha(n1), numero_para_planilha(n2),
                                        numero_para_planilha(n2 - n1)]))
        return MedidasDaVista(resumo, colunas, tuple(linhas), "\n".join(planilha) + "\n")

    def _ligar_valores(self, ligar: bool) -> None:
        if not ligar:
            self.valor_no_mouse.hide()
            self.ponto_no_mouse.hide()

    def _mouse_movido(self, posicao) -> None:
        """Os valores sob o mouse: a frequência e o nível do bin mais alto da coluna de pixel de cada traço (de perto,
        o bin mais próximo)."""
        if not self.acao_valores.isChecked() or not isValid(self):
            return
        vb = self.grafico.getViewBox()
        prontos = [r for r in self.resultados if r.desenho is not None]
        if not prontos or not vb.sceneBoundingRect().contains(posicao):
            self.valor_no_mouse.hide()
            self.ponto_no_mouse.hide()
            return
        ponto = vb.mapSceneToView(posicao)
        f = self._f(ponto.x())
        linhas, xs, ys, cores = [], [], [], []
        t = aparencia().tema
        for r in prontos:
            d = r.desenho
            i = self._mais_alto_perto(d, f, 0.5)
            fi, nivel = d.f0 + i * d.df, float(d.niveis[i])
            linhas.append(f"{self._texto_do_nivel(nivel, r)} em {formatar_si(fi, 'Hz', 7)}")
            xs.append(self._x(max(fi, d.df) if self.opcoes.frequencia_log else fi))
            ys.append(self.escalas.escala(r.traco).y.na_vista(nivel))
            cores.append(pg.mkBrush(QColor(cor_do_traco(r.traco.receita.cor, t)[0])))
        self.valor_no_mouse.setText("\n".join(linhas))
        self.valor_no_mouse.setPos(ponto)
        self.valor_no_mouse.show()
        self.ponto_no_mouse.setData(xs, ys, brush=cores)
        self.ponto_no_mouse.show()

    def _tema_mudou(self, t: Tema) -> None:
        if not isValid(self):
            return
        self.grafico.setBackground(QColor(t.afundada))
        for eixo in (self.eixo_x, self.eixo_y):
            eixo.aplicar_tema(t)
        self.grade.aplicar_tema(t)
        self.cursores.aplicar_tema(t)
        self._colorir_faixas(t)
        self.anotacoes.refazer()
        self.valor_no_mouse.setColor(QColor(t.texto))
        self.valor_no_mouse.fill = pg.mkBrush(QColor(t.elevada))
        if self.resultados:
            self._desenhar()
        # Os números escritos (o separador decimal pode ter mudado): a informação e as medidas dos cursores.
        self._mostrar_info()
        self.emitir_regiao()
