"""A vista de tempo (docs/gui-plan.md, 9.2 e 9.5; o mockup A1): os traços de uma ``Vista`` em faixas, com o tempo
ligado entre elas.

* **As faixas:** uma por valor de ``receita.faixa`` (o plotar põe os canais da mesma unidade na mesma faixa). O eixo
  Y de cada uma ajusta ao traço inteiro e fica parado no zoom do tempo (como num osciloscópio); Ctrl + roda o muda.
* **A escala de cada traço** (``graficos/escalas.py``): os traços de uma faixa dividem o Y, e todos dividem o tempo;
  o cadeado da barra destrava o selecionado (o zoom e o pan do Y **e do tempo** passam a ser só dele) e "Mesma
  escala" o devolve à escala comum. O eixo Y mostra os números e a unidade do traço selecionado na faixa (sem
  seleção, do primeiro travado); o eixo do tempo, o tempo do último selecionado, se ele tem o seu. Com unidades,
  escalas ou tempos diferentes, o rótulo fica na cor do traço que o eixo mostra.
* **O tempo próprio de um traço** vale em tudo o que se mede nele: as medidas da região (os cursores, a janela) e o
  trecho do espectro são o trecho dele que aparece ali na tela (:meth:`VistaDeTempo.regiao_do_traco`), e a prévia
  de um traço transformado é a da janela dele.
* **Os traços** são ``TracoLOD`` sobre a pirâmide de cada canal: chegam quando a pirâmide fica pronta. A cor, o
  ganho, o offset, o deslocamento no tempo e a visibilidade mudam no lugar; só a mudança de faixa refaz as faixas.
* **Um traço com transformações** (a cadeia da receita) é desenhado da sua materialização
  (``servicos/materializar.py``). Enquanto ela roda, o traço mostra a prévia da janela visível (até 1 M amostras:
  calculada em ~0,1 s a cada parada do zoom ou do pan) ou o começo já materializado, que se preenche da esquerda para
  a direita; o chip mostra o progresso. Nunca o canal cru no lugar do transformado.
* **A legenda** são os chips dos traços (clicar seleciona; o selecionado fica à frente das outras linhas).
* **O histórico do zoom:** cada parada do zoom ou do pan (400 ms sem mexer) entra no histórico; Backspace volta.
  ``F`` (ou o duplo clique) ajusta a captura inteira.
* **O minimapa** mostra a captura inteira do primeiro traço e a janela visível; arrastar a janela anda no tempo.
* **O botão do meio:** arrastar move a vista nas duas direções, sem mudar as escalas, em cima de um traço ou não
  (os traços não mudam). Um clique rápido põe o 0 do eixo Y no meio da faixa e tira o deslocamento em Y do traço
  clicado (ou dos selecionados nela).
* **Os cursores** (``C``): duas linhas verticais, as mesmas em todas as faixas; arrastar uma a move, e as setas
  movem a última mexida amostra a amostra (Shift: 10 amostras). A região a medir (``regiaoMudou``) é a dos cursores
  ou, sem eles, a janela visível; ela sai 250 ms depois da última mudança.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import QGraphicsItem, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget
from shiboken6 import isValid

from ...componentes.chip import ChipDeTraco
from ...componentes.fluxo import LayoutDeFluxo
from ...componentes.numeros import decimal, formatar_si
from ...dados import unidades
from ...dados.piramide import Piramide
from ...graficos.clique import mais_perto
from ...graficos.cursores import CursoresDaVista
from ...graficos.escalas import Afim, EscalasDaCaixa
from ...graficos.faixa import LARGURA_DO_EIXO_Y, CaixaDaFaixa, EixoDoTema, GradeDoTema
from ...graficos.minimapa import Minimapa
from ...graficos.traco_lod import TracoLOD
from ...modelo.comandos import MudarTracos
from ...modelo.objetos import FonteDoProjeto, Projeto, Traco, Vista
from ...modelo.selecao import Selecao
from ...servicos.materializar import LIMITE_DA_PREVIA, EstadoDaMaterializacao, Previa, ServicoDeMaterializacao
from ...servicos.tarefas import GerenciadorDeTarefas
from ...tema.aplicar import aparencia
from ...tema.icones import IconeDoTema
from ...tema.tokens import Tema, cor_do_traco
from .acoes_da_escala import acoes_da_escala, atualizar_acoes_da_escala, estado_do_chip

PARADA_DO_HISTORICO_MS = 400
ESPERA_DA_MEDIDA_MS = 250
INTERVALO_DO_MINIMAPA_MS = 30      # o minimapa acompanha o zoom a ~30 q/s: ele é outro widget, pintado à parte
LARGURA_DA_INFO = 420
MAXIMO_DO_HISTORICO = 100
ESPERA_DA_PREVIA_MS = 60           # a prévia sai 60 ms depois da última mudança do zoom ou do pan
FOLGA_DA_PREVIA = 0.25             # a prévia cobre um quarto de janela a mais de cada lado: o pan curto não espera


class VistaDeTempo(QWidget):
    """O conteúdo de uma aba de vista de tempo. ``tracoClicado(traco | None, modificadores)``: um clique no
    gráfico (perto de um traço, ou no vazio) ou num chip."""

    tracoClicado = Signal(object, object)
    regiaoMudou = Signal(float, float, bool)      # início, fim (s), se é a dos cursores
    semRegiao = Signal()                          # nenhum traço desenhado: nada a medir

    def __init__(self, vista: Vista, projeto: Projeto, selecao: Selecao, parent: QWidget | None = None,
                 materializacoes: ServicoDeMaterializacao | None = None):
        super().__init__(parent)
        self.setObjectName("vista_tempo")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.vista, self.projeto, self.selecao = vista, projeto, selecao
        self.faixas: dict[int, pg.PlotItem] = {}
        self.itens: dict[Traco, TracoLOD] = {}
        self.chips: dict[Traco, ChipDeTraco] = {}
        self.historico: list[tuple[float, float]] = []
        self._navegando = False
        self._fontes_esperadas: set[FonteDoProjeto] = set()
        self._fontes_ouvidas: set[FonteDoProjeto] = set()
        self._cursores = CursoresDaVista(parent=self)       # os de todas as vistas (graficos/cursores.py)
        self._cursores.mudou.connect(self._cursores_mudaram)
        if materializacoes is None:          # sem a janela (os testes): um serviço só desta vista
            materializacoes = ServicoDeMaterializacao(GerenciadorDeTarefas(parent=self), parent=self)
        self.materializacoes = materializacoes
        self._previas: dict[Traco, Previa] = {}
        self._ajustar_y_de: set[Traco] = set()       # traços cuja faixa ajusta o Y quando os dados novos chegarem
        self._conferir_y_de: set[Traco] = set()      # e os que só conferem se ainda aparecem (graficos.escalas.manter)
        self._estados_da_escala: dict[Traco, tuple[bool, bool]] = {}   # (travado, na comum) mostrado de cada traço
        self._tempos_proprios: dict[Traco, Afim] = {}                   # o tempo de cada traço, da última vez
        self._modelo_do_minimapa: TracoLOD | None = None
        self._acompanhados: set[Traco] = set()
        materializacoes.mudou.connect(self._materializacao_mudou)
        acompanhados, servico = self._acompanhados, materializacoes
        self.destroyed.connect(lambda *_: [servico.largar(t) for t in list(acompanhados)])

        self._criar_barra()
        self._legenda = QWidget()
        self._legenda.setObjectName("legenda")
        self._legenda.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        politica = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        politica.setHeightForWidth(True)
        self._legenda.setSizePolicy(politica)
        self._fluxo_da_legenda = LayoutDeFluxo(self._legenda)
        self._fluxo_da_legenda.setContentsMargins(10, 6, 10, 4)
        self.grafico = pg.GraphicsLayoutWidget()
        self.grafico.setObjectName("grafico")
        self.grafico.ci.setSpacing(0)
        self.grafico.ci.setContentsMargins(0, 4, 8, 0)
        self.minimapa = Minimapa()
        self.minimapa.janelaPedida.connect(self._janela_do_minimapa)
        self.vazio = QLabel(self.tr("Nenhum traço nesta vista. Dê um duplo clique num canal do painel do projeto."))
        self.vazio.setObjectName("vazio_vista")
        self.vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(0)
        coluna.addWidget(self._barra)
        coluna.addWidget(self._legenda)
        coluna.addWidget(self.grafico, 1)
        coluna.addWidget(self.vazio, 1)
        coluna.addWidget(self.minimapa)

        self._parada = QTimer(self)
        self._parada.setSingleShot(True)
        self._parada.setInterval(PARADA_DO_HISTORICO_MS)
        self._parada.timeout.connect(self._registrar_no_historico)
        self._minimapa_atrasado = QTimer(self)
        self._minimapa_atrasado.setSingleShot(True)
        self._minimapa_atrasado.setInterval(INTERVALO_DO_MINIMAPA_MS)
        self._minimapa_atrasado.timeout.connect(self._acompanhar_no_minimapa)
        self._espera_da_medida = QTimer(self)
        self._espera_da_medida.setSingleShot(True)
        self._espera_da_medida.setInterval(ESPERA_DA_MEDIDA_MS)
        self._espera_da_medida.timeout.connect(self.emitir_regiao)
        self._espera_da_previa = QTimer(self)
        self._espera_da_previa.setSingleShot(True)
        self._espera_da_previa.setInterval(ESPERA_DA_PREVIA_MS)
        self._espera_da_previa.timeout.connect(self._pedir_previas)

        vista.tracoEntrou.connect(self._estrutura_mudou)
        vista.tracoSaiu.connect(self._estrutura_mudou)
        vista.tracoMudou.connect(self._traco_mudou)
        selecao.mudou.connect(self._selecao_mudou)
        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou(aparencia().tema)
        self.reconstruir(ajustar=True)

    # ------------------------------------------------------------------ a barra da vista

    def _criar_barra(self) -> None:
        self._barra = QWidget()
        self._barra.setObjectName("barra_da_vista")
        self._barra.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.acao_ajustar = QAction(self.tr("Ajustar tudo"), self)
        self.acao_ajustar.setShortcut(QKeySequence("F"))
        self.acao_ajustar.setToolTip(self.tr("Ajustar tudo (F, ou duplo clique no gráfico)"))
        self.acao_ajustar.triggered.connect(self.ajustar)
        self.acao_voltar = QAction(self.tr("Voltar o zoom"), self)
        self.acao_voltar.setShortcut(QKeySequence(Qt.Key.Key_Backspace))
        self.acao_voltar.setToolTip(self.tr("Voltar ao zoom anterior (Backspace)"))
        self.acao_voltar.triggered.connect(self.voltar)
        self.acao_cursores = QAction(self.tr("Cursores"), self)
        self.acao_cursores.setCheckable(True)
        self.acao_cursores.setShortcut(QKeySequence("C"))
        self.acao_cursores.setToolTip(self.tr("Ligar os cursores (C)"))
        self.acao_cursores.toggled.connect(self.ligar_cursores)
        mover = []
        for tecla, passos in (("Left", -1), ("Right", 1), ("Shift+Left", -10), ("Shift+Right", 10)):
            a = QAction(self)
            a.setShortcut(QKeySequence(tecla))
            a.triggered.connect(lambda _=False, n=passos: self.mover_cursor(n))
            mover.append(a)
        for acao in (self.acao_ajustar, self.acao_voltar, self.acao_cursores, *mover):
            acao.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.addAction(acao)
        IconeDoTema(self.acao_ajustar, "expandir")
        IconeDoTema(self.acao_voltar, "desfazer")
        IconeDoTema(self.acao_cursores, "cursores", papel_ligado="acento")
        self.acao_destravar, self.acao_igualar = acoes_da_escala(self, self.destravar_selecionados, self.igualar_escalas,
                                                                 com_tempo=True)
        self.info = QLabel()
        self.info.setObjectName("info_da_vista")
        # Tamanho fixo: o texto muda a cada quadro do zoom, e um rótulo que muda de largura refaz o layout da janela
        # inteira (medido: os títulos dos painéis eram medidos 20 vezes por quadro, e os chips repintados).
        self.info.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.info.setFixedSize(QSize(LARGURA_DA_INFO, self.info.sizeHint().height()))
        linha = QHBoxLayout(self._barra)
        linha.setContentsMargins(10, 4, 10, 4)
        linha.setSpacing(4)
        for acao in (self.acao_voltar, self.acao_ajustar, self.acao_cursores, self.acao_destravar, self.acao_igualar):
            b = QToolButton()
            b.setProperty("variante", "fantasma")
            b.setDefaultAction(acao)
            b.setIconSize(QSize(16, 16))
            b.setAutoRaise(True)
            linha.addWidget(b)
        linha.addStretch(1)
        linha.addWidget(self.info)

    # ------------------------------------------------------------------ montar as faixas

    def _fonte_do(self, traco: Traco) -> FonteDoProjeto | None:
        try:
            return self.projeto.fonte(traco.receita.fonte)
        except KeyError:
            return None

    def _faixa_principal(self) -> pg.PlotItem | None:
        return self.faixas[min(self.faixas)] if self.faixas else None

    def reconstruir(self, ajustar: bool = False) -> None:
        """Põe a vista em dia com o modelo (um traço entrou, saiu ou mudou de faixa; uma pirâmide ficou pronta),
        **mexendo só no que mudou**: as faixas que sobram e os traços que já estão desenhados ficam. Refazer tudo
        custava ~50 ms por faixa a cada duplo clique (medido: plotar 8 traços travava a tela por 0,8 s). A janela de
        tempo fica; com ``ajustar``, a captura inteira entra."""
        principal_antes = self._faixa_principal()
        janela_de_tempo = None if ajustar or principal_antes is None else principal_antes.getViewBox().viewRange()[0]
        tracos = self.vista.tracos
        desejadas = sorted({t.receita.faixa for t in tracos})

        # 1. Os traços que saíram (ou cuja captura sumiu) deixam a sua faixa.
        for traco in [t for t in self.itens if t not in tracos]:
            self._tirar_item(self.itens.pop(traco))
        for traco in [t for t in self._acompanhados if t not in tracos]:
            self._largar(traco)
        # 2. As faixas que sobraram saem (os traços delas já foram tirados ou serão movidos abaixo).
        sairam = [n for n in self.faixas if n not in desejadas]
        for numero in sairam:
            faixa = self.faixas.pop(numero)
            for item in list(self.itens.values()):
                if item.getViewBox() is faixa.getViewBox():
                    self._tirar_item(item)          # volta abaixo, na faixa nova
            if faixa is principal_antes:
                faixa.getViewBox().sigXRangeChanged.disconnect(self._tempo_mudou)
            self.grafico.removeItem(faixa)
            faixa.ligada_a = None
            faixa.deleteLater()                     # fora da cena, ela não teria quem a apagasse
        # 3. As que faltam entram; a ordem das linhas segue o número da faixa.
        ordem_antes = list(self.faixas)
        for numero in desejadas:
            if numero not in self.faixas:
                self.faixas[numero] = self._nova_faixa()
        self.faixas = {n: self.faixas[n] for n in desejadas}
        if list(self.faixas) != ordem_antes or sairam:
            self._ordenar_linhas(ordem_antes, compactar=bool(sairam))
        # 4. Cada traço na sua faixa: os novos são criados; os que mudaram de faixa, movidos.
        for traco in tracos:
            faixa = self.faixas[traco.receita.faixa]
            item = self.itens.get(traco)
            if item is None:
                self._desenhar(traco)
            elif item.getViewBox() is not faixa.getViewBox():
                self._tirar_item(item)
                faixa.addItem(item)
        # 5. O tempo ligado à faixa principal (a de menor número), o eixo do tempo só na última, os rótulos.
        principal = self._faixa_principal()
        if principal is not principal_antes:
            if principal_antes is not None and isValid(principal_antes) and principal_antes in self.faixas.values():
                principal_antes.getViewBox().sigXRangeChanged.disconnect(self._tempo_mudou)
            if principal is not None:
                principal.getViewBox().sigXRangeChanged.connect(self._tempo_mudou)
        for faixa in self.faixas.values():
            if faixa is not principal and getattr(faixa, "ligada_a", None) is not principal:
                faixa.setXLink(principal)
                faixa.ligada_a = principal
            elif faixa is principal and getattr(faixa, "ligada_a", None) is not None:
                faixa.setXLink(None)
                faixa.ligada_a = None
        ultima = self.faixas[desejadas[-1]] if desejadas else None
        for faixa in self.faixas.values():
            if faixa is ultima:
                faixa.showAxis("bottom")
            else:
                faixa.hideAxis("bottom")
                faixa.rotulo_x = None
        for numero, faixa in self.faixas.items():
            faixa.escalas.definir_itens({t: self.itens[t] for t in tracos if t.receita.faixa == numero and
                                         t in self.itens})
        self._rotular_faixas()
        self._converter_o_tempo()

        self._refazer_legenda()
        self._refazer_minimapa()
        tem = bool(tracos)
        self.grafico.setVisible(tem)
        self.vazio.setVisible(not tem)
        if principal is not None:
            if janela_de_tempo is not None:
                principal.getViewBox().setXRange(*janela_de_tempo, padding=0)
            elif ajustar or principal_antes is None:
                self.ajustar()
        self._atualizar_info()
        self._selecao_mudou(self.selecao.tracos)
        self._por_cursores()
        self._espera_da_medida.start()

    @staticmethod
    def _tirar_item(item: TracoLOD) -> None:
        """Tira o item da faixa dele pelo ``PlotItem`` (que guarda a lista dos seus itens), e não só pela caixa: senão
        a faixa ainda o teria na lista, e o traço que voltasse a ela (desfazer a mudança de faixa) seria recusado
        ("Item already added") e sumiria do gráfico."""
        caixa = item.getViewBox() if isValid(item) else None
        if caixa is None:
            return
        faixa = caixa.parentItem()
        if isinstance(faixa, pg.PlotItem):
            faixa.removeItem(item)
        else:
            caixa.removeItem(item)

    def _ordenar_linhas(self, ordem_antes: list[int], compactar: bool = False) -> None:
        """As faixas nas linhas do layout, na ordem do número. O caso comum (faixas novas depois das que já existem,
        nenhuma saiu) só acrescenta linhas; senão, tira e põe todas de volta, nas linhas 0, 1, 2... (as que ficam
        guardam a linha antiga, e uma nova cairia em cima de uma ocupada)."""
        ordem = list(self.faixas)
        layout = self.grafico.ci
        if not compactar and ordem[:len(ordem_antes)] == ordem_antes:
            for linha in range(len(ordem_antes), len(ordem)):
                layout.addItem(self.faixas[ordem[linha]], row=linha, col=0)
            return
        for faixa in self.faixas.values():
            if faixa in layout.items:
                layout.removeItem(faixa)
        for linha, faixa in enumerate(self.faixas.values()):
            layout.addItem(faixa, row=linha, col=0)

    def _nova_faixa(self) -> pg.PlotItem:
        eixo_x, eixo_y = EixoDoTema("bottom"), EixoDoTema("left")
        caixa = CaixaDaFaixa()
        faixa = pg.PlotItem(viewBox=caixa, axisItems={"bottom": eixo_x, "left": eixo_y})
        faixa.hideButtons()
        faixa.setMenuEnabled(False)
        # Os eixos de cima e da direita (escondidos) vêm com o prefixo SI automático, que refaz o HTML do rótulo a
        # cada mudança do tempo: 8 por quadro com 8 faixas, para nada.
        for lado in ("top", "right"):
            faixa.getAxis(lado).enableAutoSIPrefix(False)
        eixo_y.setWidth(LARGURA_DO_EIXO_Y)
        # O Y não muda no zoom do tempo: o eixo Y vira um pixmap e é só copiado a cada quadro (antes, 8 eixos
        # repintavam a mesma figura). Uma mudança do Y invalida o cache sozinha (o eixo chama update()).
        eixo_y.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        faixa.hideAxis("bottom")
        grade = GradeDoTema(eixo_x, eixo_y)
        caixa.addItem(grade, ignoreBounds=True)
        faixa.grade = grade
        faixa.ligada_a = None
        caixa.clicada.connect(self._clicou)
        caixa.centroPedido.connect(self._centro_pedido)
        caixa.ajustarPedido.connect(self.ajustar)
        caixa.aplicar_tema(aparencia().tema)
        faixa.rotulo_y = faixa.rotulo_x = None
        faixa.escalas = EscalasDaCaixa(caixa, eixo_y, parent=faixa, com_tempo=True)
        faixa.escalas.referenciaMudou.connect(self._rotular_faixas)
        faixa.escalas.cadeadoMudou.connect(self._escalas_mudaram)
        faixa.escalas.mudou.connect(self._escala_mudou)
        faixa.escalas.definir_selecao(self.selecao.tracos)
        return faixa

    def _rotular_faixas(self) -> None:
        """O rótulo do eixo Y de cada faixa: a grandeza e a unidade do traço que o eixo mostra (graficos/escalas.py).
        Com traços de unidades ou de escalas diferentes na faixa, o rótulo fica na cor desse traço."""
        if not isValid(self):
            return
        tema = aparencia().tema
        for numero, faixa in self.faixas.items():
            escalas = faixa.escalas
            dela = escalas.tracos or [t for t in self.vista.tracos if t.receita.faixa == numero]
            traco = escalas.referencia or (dela[0] if dela else None)
            if traco is None or self._canal_do(traco) is None:
                continue
            rotulo = unidades.rotulo(*self.grandeza_e_unidade(traco))
            mistura = (len({self.grandeza_e_unidade(t)[1] for t in dela if self._canal_do(t) is not None}) > 1
                       or any(not escalas.escala(t).comum for t in dela))
            cor = cor_do_traco(traco.receita.cor, tema)[0] if mistura else None
            if faixa.rotulo_y != (rotulo, cor):
                faixa.rotulo_y = (rotulo, cor)
                faixa.setLabel("left", rotulo, **({"color": cor} if cor else {}))

    def _canal_do(self, traco: Traco):
        fonte = self._fonte_do(traco)
        return fonte.canal(traco.receita.canal) if fonte is not None and not fonte.esta_ausente else None

    def grandeza_e_unidade(self, traco: Traco) -> tuple[str, str]:
        """A grandeza e a unidade dos valores do traço (a dele, ou a do canal: ``dados/unidades.py``)."""
        canal = self._canal_do(traco)
        if canal is None:
            return "", traco.receita.unidade
        return unidades.do_traco(traco.receita.unidade, canal.unidade, canal.nome_grandeza)

    # ------------------------------------------------------------------ as escalas dos traços

    def _tracos_selecionados_aqui(self) -> list[Traco]:
        return [t for t in self.selecao.tracos if t in self.itens]

    def destravar_selecionados(self, destravar: bool = True) -> None:
        """O cadeado: os traços selecionados nesta vista passam a ter a escala deles, no tempo e no Y (ou voltam a
        andar com os outros, na escala que ganharam)."""
        tracos = self._tracos_selecionados_aqui()
        for faixa in self.faixas.values():
            faixa.escalas.travar(tracos, travar=not destravar)
        self._escalas_mudaram()

    def igualar_escalas(self) -> None:
        """"Mesma escala": os selecionados (sem seleção, todos os traços) voltam à escala comum da faixa."""
        tracos = self._tracos_selecionados_aqui() or list(self.itens)
        for faixa in self.faixas.values():
            faixa.escalas.igualar(tracos)
        self._escalas_mudaram()

    def escala_de(self, traco: Traco):
        """(escala, travado) do traço na faixa dele."""
        faixa = self.faixas.get(traco.receita.faixa)
        if faixa is None:
            return None
        return faixa.escalas.escala(traco), faixa.escalas.travado(traco)

    def _tempo_de(self, traco: Traco | None) -> Afim:
        estado = self.escala_de(traco) if traco is not None else None
        return estado[0].x if estado is not None else Afim()

    def tem_tempo_proprio(self, traco: Traco) -> bool:
        return not self._tempo_de(traco).comum

    def regiao_do_traco(self, traco: Traco, inicio: float, fim: float) -> tuple[float, float]:
        """A região ``[inicio, fim]`` da vista (s) no tempo do traço: a mesma, sem tempo próprio; com ele, o trecho do
        traço que aparece entre ``inicio`` e ``fim`` na tela (o que as medidas e o espectro dele usam)."""
        x = self._tempo_de(traco)
        if x.comum:
            return inicio, fim
        a, b = x.no_traco(inicio), x.no_traco(fim)
        return min(a, b), max(a, b)

    def regioes_proprias(self, inicio: float, fim: float) -> dict[Traco, tuple[float, float]]:
        """A região de cada traço de tempo próprio (os outros medem a da vista)."""
        return {t: self.regiao_do_traco(t, inicio, fim) for t in self.vista.tracos if self.tem_tempo_proprio(t)}

    def _referencia_do_tempo(self) -> Traco | None:
        """O traço que o eixo do tempo mostra: o último selecionado nesta vista."""
        selecionados = self._tracos_selecionados_aqui()
        return selecionados[-1] if selecionados else None

    def _converter_o_tempo(self) -> None:
        """O eixo do tempo (e a grade de cada faixa) nos tempos do traço de referência, se ele tem o seu; o rótulo
        então na cor dele."""
        if not isValid(self) or not self.faixas:
            return
        referencia = self._referencia_do_tempo()
        x = self._tempo_de(referencia)
        for faixa in self.faixas.values():
            faixa.getAxis("bottom").definir_conversao(x.k, x.c)
        ultima = self.faixas[max(self.faixas)]
        cor = None if x.comum else cor_do_traco(referencia.receita.cor, aparencia().tema)[0]
        rotulo = (self.tr("tempo (s)"), cor)
        if ultima.rotulo_x != rotulo:
            ultima.rotulo_x = rotulo
            ultima.setLabel("bottom", rotulo[0], **({"color": cor} if cor else {}))

    def _travado_e_comum(self, traco: Traco) -> tuple[bool, bool]:
        estado = self.escala_de(traco)
        return (True, True) if estado is None else (estado[1], estado[0].comum)

    def _escala_mudou(self, traco: Traco) -> None:
        """A escala de um traço mudou (um gesto, o ajuste). Se o tempo dele mudou, o trecho dele na tela também: as
        medidas e a prévia, o eixo do tempo e o minimapa (se ele é o traço deles). Se ela passou da comum para a
        própria (ou voltou), o chip, os botões e os rótulos. A cada passo de um gesto, nada mais."""
        if not isValid(self):
            return
        x = self._tempo_de(traco)
        if x != self._tempos_proprios.get(traco, Afim()):
            self._tempos_proprios[traco] = x
            self._espera_da_medida.start()
            if traco in self._acompanhados:
                self._espera_da_previa.start()
            if traco is self._referencia_do_tempo():
                self._converter_o_tempo()
                self._atualizar_info()
            if self._modelo_do_minimapa is not None and self.itens.get(traco) is self._modelo_do_minimapa:
                self._acompanhar_no_minimapa()
        if self._estados_da_escala.get(traco) != self._travado_e_comum(traco):
            self._escalas_mudaram()

    def _escalas_mudaram(self) -> None:
        """Um traço foi destravado, travado ou igualado: os chips, os botões e os rótulos."""
        if not isValid(self):
            return
        self._estados_da_escala = {t: self._travado_e_comum(t) for t in self.itens}
        self._tempos_proprios = {t: self._tempo_de(t) for t in self.itens}
        for traco, chip in self.chips.items():
            chip.definir(escala=estado_do_chip(*self._travado_e_comum(traco)))
        selecionados = self._tracos_selecionados_aqui()
        atualizar_acoes_da_escala(self.acao_destravar, self.acao_igualar,
                                  [self._travado_e_comum(t) for t in selecionados],
                                  [self._travado_e_comum(t) for t in (selecionados or list(self.itens))],
                                  com_tempo=True)
        self._rotular_faixas()
        self._converter_o_tempo()
        self._atualizar_info()

    def _desenhar(self, traco: Traco) -> None:
        fonte = self._fonte_do(traco)
        faixa = self.faixas.get(traco.receita.faixa)
        if fonte is None or fonte.esta_ausente or faixa is None:
            return
        if fonte not in self._fontes_ouvidas:
            # O estado da fonte (a pirâmide andando, a integridade conferida) muda o chip dos traços dela.
            self._fontes_ouvidas.add(fonte)
            fonte.estadoMudou.connect(self._estado_da_fonte)
        if fonte.piramides is None:
            if fonte not in self._fontes_esperadas:
                self._fontes_esperadas.add(fonte)
                fonte.piramidesProntas.connect(self._piramide_chegou)
            return
        r = traco.receita
        canal = fonte.canal(r.canal)
        estado = self._acompanhar(traco)
        piramide, amostras, inicio = self._dados(traco, estado)
        escala, deslocamento = self._afim(traco)
        item = TracoLOD(piramide, amostras, canal.taxa_hz, t0=r.deslocamento_s, escala=escala,
                        deslocamento=deslocamento, cor=cor_do_traco(r.cor, aparencia().tema)[0], nome=r.nome,
                        inicio=inicio, n_total=len(canal.amostras))
        item.setVisible(r.visivel)
        com_dados = self._faixa_com_dados(faixa)
        faixa.addItem(item)
        self.itens[traco] = item
        if estado is not None and estado.pronta is None:
            # Os dados chegam depois: numa faixa nova, o Y se ajusta a eles; numa que já mostra outros traços, a vista
            # que o usuário escolheu fica.
            (self._conferir_y_de if com_dados else self._ajustar_y_de).add(traco)
            self._espera_da_previa.start()

    # ------------------------------------------------------------------ os traços com transformações

    def _acompanhar(self, traco: Traco) -> EstadoDaMaterializacao | None:
        """O estado da materialização do traço (None sem cadeia), acompanhado pelo serviço."""
        fonte, r = self._fonte_do(traco), traco.receita
        estado = self.materializacoes.acompanhar(traco, fonte, r.canal, r.cadeia)
        if estado is None:
            self._acompanhados.discard(traco)
        else:
            self._acompanhados.add(traco)
        return estado

    def _largar(self, traco: Traco) -> None:
        self.materializacoes.largar(traco)
        self._acompanhados.discard(traco)
        self._previas.pop(traco, None)
        self._ajustar_y_de.discard(traco)
        self._conferir_y_de.discard(traco)

    def soltar(self) -> None:
        """A vista vai sair: as materializações e as prévias que só ela usava são canceladas."""
        for traco in list(self._acompanhados):
            self._largar(traco)

    def _afim(self, traco: Traco) -> tuple[float, float]:
        """A conversão do eixo y: do código do ADC (o canal cru) ou da unidade física (o traço materializado)."""
        r = traco.receita
        if self.materializacoes.estado_de(traco) is not None:
            return r.afim(1.0, 0.0)
        canal = self._fonte_do(traco).canal(r.canal)
        return r.afim(canal.escala, canal.deslocamento)

    def _janela_do_traco(self, traco: Traco) -> tuple[int, int] | None:
        """A janela visível em amostras do canal do traço."""
        janela = self.janela_de_tempo()
        fonte = self._fonte_do(traco)
        if janela is None or fonte is None:
            return None
        r = traco.receita
        canal = fonte.canal(r.canal)
        n = len(canal.amostras)
        inicio, fim = self.regiao_do_traco(traco, *janela)
        i0 = int(max(0, (inicio - r.deslocamento_s) * canal.taxa_hz))
        i1 = int(min(n, (fim - r.deslocamento_s) * canal.taxa_hz + 2))
        return (i0, max(i0, i1))

    def _dados(self, traco: Traco, estado: EstadoDaMaterializacao | None):
        """O que desenhar do traço: o canal, a materialização pronta, o começo já feito ou a prévia (a que cobre a
        janela visível primeiro); nada, se ainda não há nada (nunca o canal cru no lugar do transformado)."""
        fonte, r = self._fonte_do(traco), traco.receita
        if estado is None:
            return fonte.piramides[fonte.posicao_do_canal(r.canal)], fonte.canal(r.canal).amostras, 0
        if estado.pronta is not None:
            return estado.pronta.piramide, estado.pronta.amostras, 0
        janela = self._janela_do_traco(traco)
        previa = self._previas.get(traco)
        parcial = None
        if estado.parcial is not None:
            amostras, piramide = estado.parcial
            parcial = (piramide, amostras[:piramide.n_amostras], 0)
        cobre_parcial = parcial is not None and janela is not None and parcial[0].n_amostras >= janela[1]
        cobre_previa = previa is not None and janela is not None and previa.inicio <= janela[0] and \
            previa.fim >= janela[1]
        if cobre_parcial:
            return parcial
        if cobre_previa:
            return previa.piramide, previa.amostras, previa.inicio
        if parcial is not None:
            return parcial
        if previa is not None:
            return previa.piramide, previa.amostras, previa.inicio
        return Piramide(0, np.dtype("<f4"), ()), np.empty(0, np.float32), 0

    def _atualizar_dados(self, traco: Traco) -> None:
        item = self.itens.get(traco)
        if item is None or not isValid(item):
            return
        dados = self._dados(traco, self.materializacoes.estado_de(traco))
        if dados[0] is not item.dados[0]:
            item.definir_dados(*dados)
            if traco in self._ajustar_y_de and dados[0].n_amostras:
                self._ajustar_y_de.discard(traco)
                self._ajustar_y(traco.receita.faixa)
            elif traco in self._conferir_y_de:
                self._conferir_y(traco, item)

    def _faixa_com_dados(self, faixa: pg.PlotItem) -> bool:
        caixa = faixa.getViewBox()
        return any(i.getViewBox() is caixa and i.dados[0].n_amostras for i in self.itens.values())

    def _conferir_y(self, traco: Traco, item: TracoLOD) -> None:
        """Os dados novos do traço (outra cadeia) chegaram: o Y da faixa fica, a não ser que o traço tenha saído
        inteiro da vista (``manter_o_y``). Sem dados no tempo visível ainda (o começo materializado de outra parte da
        captura), espera os próximos."""
        caixa = item.getViewBox()
        if caixa is None:
            self._conferir_y_de.discard(traco)
            return
        limites = item.limites_y_em(*item.janela_do_traco(*caixa.viewRange()[0]))
        faixa = self.faixas.get(traco.receita.faixa)
        if limites is not None and faixa is not None:
            self._conferir_y_de.discard(traco)
            faixa.escalas.manter({traco: limites})

    def _ajustar_y(self, numero_da_faixa: int) -> None:
        """O Y da faixa ajustado aos traços dela (o traço inteiro, ou o que dele já existe)."""
        faixa = self.faixas.get(numero_da_faixa)
        if faixa is None:
            return
        escalas = faixa.escalas
        limites = [escalas.limites_na_vista(traco, item.dataBounds(1)) for traco, item in self.itens.items()
                   if traco.receita.faixa == numero_da_faixa and item.dados[0].n_amostras and escalas.travado(traco)]
        if limites:
            y0, y1 = min(a for a, _ in limites), max(b for _, b in limites)
            faixa.getViewBox().setYRange(y0, y1 if y1 > y0 else y0 + 1e-12, padding=0.05)

    def _pedir_previas(self) -> None:
        """A prévia da janela visível (com folga) de cada traço que ainda não ficou pronto e que a prévia atual e o
        começo materializado não cobrem."""
        if not isValid(self):
            return
        for traco in list(self.itens):
            estado = self.materializacoes.estado_de(traco)
            janela = self._janela_do_traco(traco)
            if estado is None or estado.pronta is not None or janela is None or estado.erro:
                continue
            previa = self._previas.get(traco)
            if previa is not None and previa.inicio <= janela[0] and previa.fim >= janela[1]:
                continue
            if estado.parcial is not None and estado.parcial[1].n_amostras >= janela[1]:
                continue
            largura = janela[1] - janela[0]
            if largura > LIMITE_DA_PREVIA:
                continue
            folga = int(min(FOLGA_DA_PREVIA * largura, (LIMITE_DA_PREVIA - largura) / 2))
            r = traco.receita
            self.materializacoes.previa(traco, self._fonte_do(traco), r.canal, r.cadeia, janela[0] - folga,
                                        janela[1] + folga, lambda p, erro, t=traco: self._previa_chegou(t, p, erro))

    def _previa_chegou(self, traco: Traco, previa: Previa | None, erro: str) -> None:
        if not isValid(self) or traco not in self.itens:
            return
        estado = self.materializacoes.estado_de(traco)
        if estado is None or estado.pronta is not None:
            return
        if previa is None:
            chip = self.chips.get(traco)
            if chip is not None:
                chip.definir(avisos=self._avisos(traco, erro))
            return
        self._previas[traco] = previa
        self._atualizar_dados(traco)

    def _materializacao_mudou(self, estado: EstadoDaMaterializacao) -> None:
        if not isValid(self):
            return
        for traco in [t for t in self.itens if self.materializacoes.estado_de(t) is estado]:
            if estado.pronta is not None:
                self._previas.pop(traco, None)
            self._atualizar_dados(traco)
            chip = self.chips.get(traco)
            if chip is not None:
                chip.definir(progresso=estado.progresso, resumo=self._resumo(traco), avisos=self._avisos(traco))
            if estado.pronta is not None and traco is next(iter(self.vista.tracos), None):
                self._refazer_minimapa()

    def _piramide_chegou(self, fonte: FonteDoProjeto) -> None:
        if isValid(self):
            self.reconstruir(ajustar=not self.itens)

    def _estado_da_fonte(self, fonte: FonteDoProjeto) -> None:
        """A pirâmide andou, ou a integridade foi conferida."""
        if not isValid(self):
            return
        for traco, chip in self.chips.items():
            if traco.receita.fonte == fonte.id:
                progresso = fonte.progresso_da_piramide
                if progresso is None:
                    estado = self.materializacoes.estado_de(traco)
                    progresso = estado.progresso if estado is not None else None
                chip.definir(progresso=progresso, avisos=self._avisos(traco))

    # ------------------------------------------------------------------ o modelo mudou

    def _estrutura_mudou(self, *_) -> None:
        self.reconstruir(ajustar=not self.itens)

    # ------------------------------------------------------------------ os cursores

    @property
    def cursores(self) -> list[float] | None:
        """As posições de C1 e C2, em segundos (None: desligados)."""
        return self._cursores.posicoes

    @cursores.setter
    def cursores(self, posicoes) -> None:
        self._cursores.posicoes = None if posicoes is None else [float(p) for p in posicoes]

    @property
    def _linhas_dos_cursores(self) -> list[list[pg.InfiniteLine]]:
        return self._cursores.linhas

    def ligar_cursores(self, ligar: bool = True) -> None:
        if self.acao_cursores.isChecked() != ligar:
            self.acao_cursores.setChecked(ligar)            # volta aqui pelo toggled
            return
        if ligar:
            self._cursores.ligar(self.janela_de_tempo() or (0.0, 1.0))
        else:
            self._cursores.desligar()
        self._por_cursores()

    def _por_cursores(self) -> None:
        """Os cursores em cada faixa (as faixas mudaram)."""
        self._cursores.por_nas([faixa.getViewBox() for faixa in self.faixas.values()])

    def _cursores_mudaram(self) -> None:
        if isValid(self):
            self._espera_da_medida.start()

    def mover_cursor(self, passos: int) -> bool:
        """As setas: move o cursor ativo ``passos`` amostras (do primeiro traço)."""
        if self.cursores is None or not self.itens:
            return False
        taxa = next(iter(self.itens.values()))._taxa
        return self._cursores.andar(passos, 1.0 / taxa)

    def regiao(self) -> tuple[float, float, bool] | None:
        """A região a medir: entre os cursores, ou a janela visível."""
        if self.cursores is not None:
            a, b = sorted(self.cursores)
            return a, b, True
        janela = self.janela_de_tempo()
        return (janela[0], janela[1], False) if janela is not None else None

    def emitir_regiao(self) -> None:
        if not isValid(self):
            return
        regiao = self.regiao()
        if regiao is not None and self.itens:
            self.regiaoMudou.emit(*regiao)
        else:
            self.semRegiao.emit()

    def _traco_mudou(self, traco: Traco, campos) -> None:
        if "faixa" in campos:
            self.reconstruir()
            return
        item, chip, r = self.itens.get(traco), self.chips.get(traco), traco.receita
        if item is not None:
            if campos & {"cadeia", "ganho", "offset", "deslocamento_s"} and item.getViewBox() is not None:
                # Uma mudança no traço não mexe na vista: numa faixa em que o usuário só mexeu no tempo, o PyQtGraph
                # ainda ajustaria o Y sozinho aos dados novos (e, sem zoom nenhum, o tempo também).
                item.getViewBox().disableAutoRange()
            if "cor" in campos:
                item.definir_cor(cor_do_traco(r.cor, aparencia().tema)[0])
                self._rotular_faixas()
            if "cadeia" in campos:
                antes = self.materializacoes.estado_de(traco)
                if self._acompanhar(traco) is not antes:
                    self._previas.pop(traco, None)
                    self._ajustar_y_de.discard(traco)
                    self._conferir_y_de.add(traco)
                    item.definir_afim(*self._afim(traco))
                    self._atualizar_dados(traco)
                    self._espera_da_previa.start()
                    self._refazer_minimapa()
            if campos & {"ganho", "offset"}:
                item.definir_afim(*self._afim(traco))
            if "unidade" in campos:
                self._rotular_faixas()
            self._espera_da_medida.start()
            if "deslocamento_s" in campos:
                item.definir_t0(r.deslocamento_s)
            if "visivel" in campos:
                item.setVisible(r.visivel)
        if chip is not None:
            if campos & {"nome", "cor"}:
                self._refazer_legenda()
            elif campos & {"ganho", "deslocamento_s", "visivel", "cadeia", "unidade"}:
                # Só o chip deste traço muda (arrastar o ganho ou o deslocamento no inspetor muda o traço a cada
                # passo: refazer a legenda inteira a cada um pesaria).
                estado = self.materializacoes.estado_de(traco)
                chip.definir(resumo=self._resumo(traco), visivel=r.visivel,
                             progresso=estado.progresso if estado is not None else None,
                             avisos=self._avisos(traco) if "cadeia" in campos else None)
        if "visivel" in campos or "cor" in campos:
            self._refazer_minimapa()

    def _selecao_mudou(self, selecionados) -> None:
        for traco, chip in self.chips.items():
            chip.definir(selecionado=traco in selecionados)
        for traco, item in self.itens.items():
            item.setZValue(10 if traco in selecionados else 0)
        for faixa in self.faixas.values():
            faixa.escalas.definir_selecao(selecionados)
        self._escalas_mudaram()

    # ------------------------------------------------------------------ a legenda

    def _resumo(self, traco: Traco) -> str:
        """O que o chip diz além do nome: ausente, a unidade própria, o ganho e o deslocamento no tempo."""
        r = traco.receita
        fonte = self._fonte_do(traco)
        resumo = []
        if fonte is not None and fonte.esta_ausente:
            resumo.append(self.tr("ausente"))
        canal = self._canal_do(traco)
        if r.unidade and (canal is None or r.unidade != canal.unidade):
            resumo.append(r.unidade)
        if r.ganho != 1:
            resumo.append(decimal(f"×{r.ganho:g}").replace("-", "−"))
        if r.deslocamento_s:
            resumo.append(f"{formatar_si(r.deslocamento_s, 's', 3)}".replace("-", "−"))
        if not r.cadeia.vazia:
            resumo.append(r.cadeia.resumo())
            estado = self.materializacoes.estado_de(traco)
            if estado is not None and estado.erro:
                resumo.append(self.tr("erro na transformação"))
        return " · ".join(resumo)

    def _avisos(self, traco: Traco, erro: str = "") -> tuple:
        return self.materializacoes.avisos(traco, self._fonte_do(traco), erro)

    def _refazer_legenda(self) -> None:
        self._fluxo_da_legenda.limpar()
        self.chips = {}
        for traco in self.vista.tracos:
            r = traco.receita
            fonte = self._fonte_do(traco)
            chip = ChipDeTraco(r.nome, r.cor, self._resumo(traco))
            estado = self.materializacoes.estado_de(traco)
            progresso = fonte.progresso_da_piramide if fonte is not None else None
            if progresso is None and estado is not None:
                progresso = estado.progresso
            chip.definir(visivel=r.visivel, selecionado=traco in self.selecao.tracos, progresso=progresso,
                         avisos=self._avisos(traco), escala=estado_do_chip(*self._travado_e_comum(traco)))
            chip.clicado.connect(lambda t=traco: self.tracoClicado.emit(t, Qt.KeyboardModifier.NoModifier))
            self._fluxo_da_legenda.addWidget(chip)
            self.chips[traco] = chip
        self._legenda.setVisible(bool(self.chips))
        self._legenda.updateGeometry()

    # ------------------------------------------------------------------ o minimapa

    def _refazer_minimapa(self) -> None:
        """O fundo do minimapa: o primeiro traço visível, da captura inteira."""
        modelo = next((self.itens[t] for t in self.vista.tracos if t in self.itens and t.receita.visivel), None)
        self._modelo_do_minimapa = modelo
        self.minimapa.setVisible(modelo is not None)
        if modelo is None:
            self.minimapa.definir_traco(None)
            return
        self.minimapa.definir_traco(modelo._piramide, modelo._amostras, modelo._taxa, t0=modelo._origem,
                                    escala=modelo._escala, deslocamento=modelo._deslocamento)
        self._acompanhar_no_minimapa()

    def _janela_no_minimapa(self) -> tuple[float, float] | None:
        """A janela visível no tempo do traço do minimapa (que pode ter o seu)."""
        janela = self.janela_de_tempo()
        modelo = self._modelo_do_minimapa
        if janela is None or modelo is None or not isValid(modelo):
            return janela
        return modelo.janela_do_traco(*janela)

    def _janela_do_minimapa(self, inicio: float, fim: float) -> None:
        """Arrastar a janela no minimapa (no tempo do traço dele): a janela da vista vai junto, ou, com o traço
        destravado, só o tempo dele (:meth:`EscalasDaCaixa.mostrar_no_tempo`)."""
        modelo = self._modelo_do_minimapa
        traco = next((t for t, item in self.itens.items() if item is modelo), None) if modelo is not None else None
        faixa = self.faixas.get(traco.receita.faixa) if traco is not None else None
        if faixa is not None:
            faixa.escalas.mostrar_no_tempo(traco, inicio, fim)
            return
        principal = self._faixa_principal()
        if principal is not None:
            principal.getViewBox().setXRange(inicio, fim, padding=0)

    # ------------------------------------------------------------------ navegar

    def janela_de_tempo(self) -> tuple[float, float] | None:
        principal = self._faixa_principal()
        return tuple(principal.getViewBox().viewRange()[0]) if principal is not None else None

    def ajustar(self) -> None:
        """A captura inteira no tempo, e cada faixa ajustada no Y (os traços de escala própria, cada um na altura
        inteira da faixa)."""
        for faixa in self.faixas.values():
            faixa.escalas.ajustar(0.02)

    def _tempo_mudou(self, *_) -> None:
        if not isValid(self):
            return
        self._atualizar_info()
        if self.minimapa.isVisible() and not self._minimapa_atrasado.isActive():
            self._minimapa_atrasado.start()
        self._parada.start()
        if self._acompanhados:
            self._espera_da_previa.start()
        if self.cursores is None:
            self._espera_da_medida.start()

    def _acompanhar_no_minimapa(self) -> None:
        janela = self._janela_no_minimapa() if isValid(self) else None
        if janela is not None:
            self.minimapa.definir_janela(*janela)

    def _registrar_no_historico(self) -> None:
        janela = self.janela_de_tempo()
        if janela is None or (self.historico and self.historico[-1] == janela):
            return
        self.historico.append(janela)
        del self.historico[:-MAXIMO_DO_HISTORICO]

    def voltar(self) -> bool:
        """Volta ao zoom anterior do histórico (Backspace)."""
        self._parada.stop()
        self._registrar_no_historico()
        if len(self.historico) < 2:
            return False
        self.historico.pop()
        x0, x1 = self.historico[-1]
        self._faixa_principal().getViewBox().setXRange(x0, x1, padding=0)
        self._parada.stop()                     # a volta não entra no histórico
        return True

    def _atualizar_info(self) -> None:
        """A janela visível no tempo que o eixo do tempo mostra (o do último selecionado; sem seleção, o da vista), e
        as amostras dela no traço selecionado (sem seleção, no primeiro)."""
        janela = self.janela_de_tempo()
        referencia = self._referencia_do_tempo()
        item = self.itens.get(referencia) if referencia is not None else next(iter(self.itens.values()), None)
        if janela is None or item is None:
            self.info.setText("")
            return
        x0, x1 = self.regiao_do_traco(referencia, *janela) if referencia is not None else janela
        amostras = (x1 - x0) * item._taxa
        self.info.setText(f"{formatar_si(x0, '', 6)} – {formatar_si(x1, 's', 6)} · {formatar_si(x1 - x0, 's', 3)} · "
                          f"{formatar_si(amostras, '', 3)} amostras".replace("-", "−").replace(" − ", " – "))

    # ------------------------------------------------------------------ selecionar

    def traco_em(self, caixa, x: float, y: float) -> Traco | None:
        """O traço visível desta faixa mais perto do ponto ``(x, y)`` (nas unidades da vista), dentro do alcance do
        clique; empatados, o desenhado por cima (``graficos/clique.py``)."""
        return mais_perto((item.distancia_em_pixels(x, y), (item.zValue(), k), traco)
                          for k, (traco, item) in enumerate(self.itens.items())
                          if item.isVisible() and item.getViewBox() is caixa)

    def _clicou(self, x: float, y: float, modificadores) -> None:
        self.tracoClicado.emit(self.traco_em(self.sender(), x, y), modificadores)

    # ------------------------------------------------------------------ o botão do meio

    def _centro_pedido(self, x: float, y: float) -> None:
        """O clique rápido do meio: o traço clicado (ou os selecionados nesta faixa) perde o deslocamento em Y, e o 0
        do eixo Y vai para o meio da faixa. O tempo fica onde está."""
        caixa = self.sender()
        traco = self.traco_em(caixa, x, y)
        alvos = [traco] if traco is not None else [
            t for t in self.selecao.tracos if t in self.itens and self.itens[t].getViewBox() is caixa]
        alvos = [t for t in alvos if t.receita.offset != 0]
        if alvos:
            nome = alvos[0].nome if len(alvos) == 1 else self.tr("{} traços").format(len(alvos))
            self.projeto.pilha.push(MudarTracos(alvos, texto=self.tr("Centralizar {}").format(nome), offset=0.0))
        caixa.centralizar_no_zero()

    # ------------------------------------------------------------------ tema

    def _tema_mudou(self, t: Tema) -> None:
        self.grafico.setBackground(QColor(t.afundada))
        for faixa in self.faixas.values():
            faixa.getViewBox().aplicar_tema(t)
            faixa.grade.aplicar_tema(t)
            for lado in ("left", "bottom"):
                faixa.getAxis(lado).aplicar_tema(t)
        for traco, item in self.itens.items():
            item.definir_cor(cor_do_traco(traco.receita.cor, t)[0])
        self._cursores.aplicar_tema(t)
        for faixa in self.faixas.values():
            faixa.rotulo_y = faixa.rotulo_x = None   # a cor do rótulo segue a do traço, que muda com o tema
        self._rotular_faixas()
        self._converter_o_tempo()
        # Os números escritos (o separador decimal pode ter mudado): a informação e o resumo dos chips.
        self._atualizar_info()
        for traco, chip in self.chips.items():
            chip.definir(resumo=self._resumo(traco))
