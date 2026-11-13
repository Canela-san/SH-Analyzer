"""A vista de tempo (docs/gui-plan.md, 9.2 e 9.5; o mockup A1): os traços de uma ``Vista`` em faixas, com o tempo
ligado entre elas.

* **As faixas:** uma por valor de ``receita.faixa`` (o plotar põe os canais da mesma unidade na mesma faixa). O eixo
  Y de cada uma ajusta ao traço inteiro e fica parado no zoom do tempo (como num osciloscópio); Ctrl + roda o muda.
* **Os traços** são ``TracoLOD`` sobre a pirâmide de cada canal: chegam quando a pirâmide fica pronta. A cor, o
  ganho, o offset, o deslocamento no tempo e a visibilidade mudam no lugar; só a mudança de faixa refaz as faixas.
* **A legenda** são os chips dos traços (clicar seleciona; o selecionado fica à frente das outras linhas).
* **O histórico do zoom:** cada parada do zoom ou do pan (400 ms sem mexer) entra no histórico; Backspace volta.
  ``F`` (ou o duplo clique) ajusta a captura inteira.
* **O minimapa** mostra a captura inteira do primeiro traço e a janela visível; arrastar a janela anda no tempo.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget
from shiboken6 import isValid

from ...componentes.chip import ChipDeTraco
from ...componentes.fluxo import LayoutDeFluxo
from ...componentes.numeros import formatar_si
from ...graficos.faixa import LARGURA_DO_EIXO_Y, CaixaDaFaixa, EixoDoTema, GradeDoTema
from ...graficos.traco_lod import TracoLOD
from ...modelo.objetos import FonteDoProjeto, Projeto, Traco, Vista
from ...modelo.selecao import Selecao
from ...tema.aplicar import aparencia
from ...tema.icones import IconeDoTema
from ...tema.tokens import Tema, cor_do_traco

PARADA_DO_HISTORICO_MS = 400
ALCANCE_DO_CLIQUE_PX = 6.0
ALTURA_DO_MINIMAPA = 44
MAXIMO_DO_HISTORICO = 100


class VistaDeTempo(QWidget):
    """O conteúdo de uma aba de vista de tempo. ``tracoClicado(traco | None, modificadores)``: um clique no
    gráfico (perto de um traço, ou no vazio) ou num chip."""

    tracoClicado = Signal(object, object)

    def __init__(self, vista: Vista, projeto: Projeto, selecao: Selecao, parent: QWidget | None = None):
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
        self.minimapa = pg.PlotWidget()
        self.minimapa.setObjectName("minimapa")
        self.minimapa.setFixedHeight(ALTURA_DO_MINIMAPA)
        self._preparar_minimapa()
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
        for acao in (self.acao_ajustar, self.acao_voltar):
            acao.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.addAction(acao)
        IconeDoTema(self.acao_ajustar, "expandir")
        IconeDoTema(self.acao_voltar, "desfazer")
        self.info = QLabel()
        self.info.setObjectName("info_da_vista")
        linha = QHBoxLayout(self._barra)
        linha.setContentsMargins(10, 4, 10, 4)
        linha.setSpacing(4)
        for acao in (self.acao_voltar, self.acao_ajustar):
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
        """Refaz as faixas e os traços (quando um traço entra, sai ou muda de faixa, ou uma pirâmide fica pronta),
        mantendo a janela de tempo."""
        janela_de_tempo = None if ajustar or not self.faixas else self._faixa_principal().getViewBox().viewRange()[0]
        for item in self.itens.values():
            item.setParentItem(None)
        self.grafico.clear()
        self.faixas, self.itens = {}, {}
        tracos = self.vista.tracos
        ordem = sorted({t.receita.faixa for t in tracos})
        for linha, numero in enumerate(ordem):
            self.faixas[numero] = self._nova_faixa(linha, ultima=linha == len(ordem) - 1)
        for traco in tracos:
            self._desenhar(traco)
        for numero, faixa in self.faixas.items():
            primeiro = next((t for t in tracos if t.receita.faixa == numero), None)
            fonte = self._fonte_do(primeiro) if primeiro is not None else None
            if fonte is not None and not fonte.esta_ausente:
                canal = fonte.canal(primeiro.receita.canal)
                faixa.setLabel("left", f"{canal.nome_grandeza} ({canal.unidade})")
        self._refazer_legenda()
        self._refazer_minimapa()
        tem = bool(tracos)
        self.grafico.setVisible(tem)
        self.vazio.setVisible(not tem)
        principal = self._faixa_principal()
        if principal is not None:
            vb = principal.getViewBox()
            vb.sigXRangeChanged.connect(self._tempo_mudou)
            if janela_de_tempo is not None:
                vb.setXRange(*janela_de_tempo, padding=0)
            else:
                self.ajustar()
        self._atualizar_info()
        self._selecao_mudou(self.selecao.tracos)

    def _nova_faixa(self, linha: int, ultima: bool) -> pg.PlotItem:
        eixo_x, eixo_y = EixoDoTema("bottom"), EixoDoTema("left")
        caixa = CaixaDaFaixa()
        faixa = self.grafico.addPlot(row=linha, col=0, viewBox=caixa, axisItems={"bottom": eixo_x, "left": eixo_y})
        faixa.hideButtons()
        faixa.setMenuEnabled(False)
        # Os eixos de cima e da direita (escondidos) vêm com o prefixo SI automático, que refaz o HTML do rótulo a
        # cada mudança do tempo: 8 por quadro com 8 faixas, para nada.
        for lado in ("top", "right"):
            faixa.getAxis(lado).enableAutoSIPrefix(False)
        eixo_y.setWidth(LARGURA_DO_EIXO_Y)
        if ultima:
            faixa.setLabel("bottom", self.tr("tempo (s)"))
        else:
            faixa.hideAxis("bottom")
        grade = GradeDoTema(eixo_x, eixo_y)
        caixa.addItem(grade, ignoreBounds=True)
        faixa.grade = grade
        caixa.clicada.connect(self._clicou)
        caixa.ajustarPedido.connect(self.ajustar)
        principal = self._faixa_principal()
        if principal is not None:
            faixa.setXLink(principal)
        return faixa

    def _desenhar(self, traco: Traco) -> None:
        fonte = self._fonte_do(traco)
        faixa = self.faixas.get(traco.receita.faixa)
        if fonte is None or fonte.esta_ausente or faixa is None:
            return
        if fonte.piramides is None:
            if fonte not in self._fontes_esperadas:
                self._fontes_esperadas.add(fonte)
                fonte.piramidesProntas.connect(self._piramide_chegou)
                fonte.estadoMudou.connect(self._progresso_da_fonte)
            return
        r = traco.receita
        canal = fonte.canal(r.canal)
        escala, deslocamento = r.afim(canal.escala, canal.deslocamento)
        item = TracoLOD(fonte.piramides[fonte.posicao_do_canal(r.canal)], canal.amostras, canal.taxa_hz,
                        t0=r.deslocamento_s, escala=escala, deslocamento=deslocamento,
                        cor=cor_do_traco(r.cor, aparencia().tema)[0], nome=r.nome)
        item.setVisible(r.visivel)
        faixa.addItem(item)
        self.itens[traco] = item

    def _piramide_chegou(self, fonte: FonteDoProjeto) -> None:
        if isValid(self):
            self.reconstruir(ajustar=not self.itens)

    def _progresso_da_fonte(self, fonte: FonteDoProjeto) -> None:
        if not isValid(self):
            return
        for traco, chip in self.chips.items():
            if traco.receita.fonte == fonte.id:
                chip.definir(progresso=fonte.progresso_da_piramide)

    # ------------------------------------------------------------------ o modelo mudou

    def _estrutura_mudou(self, *_) -> None:
        self.reconstruir(ajustar=not self.itens)

    def _traco_mudou(self, traco: Traco, campos) -> None:
        if "faixa" in campos:
            self.reconstruir()
            return
        item, chip, r = self.itens.get(traco), self.chips.get(traco), traco.receita
        if item is not None:
            if "cor" in campos:
                item.definir_cor(cor_do_traco(r.cor, aparencia().tema)[0])
            if campos & {"ganho", "offset"}:
                canal = self._fonte_do(traco).canal(r.canal)
                item.definir_afim(*r.afim(canal.escala, canal.deslocamento))
            if "deslocamento_s" in campos:
                item.definir_t0(r.deslocamento_s)
            if "visivel" in campos:
                item.setVisible(r.visivel)
        if chip is not None:
            self._refazer_legenda()
        if "visivel" in campos or "cor" in campos:
            self._refazer_minimapa()

    def _selecao_mudou(self, selecionados) -> None:
        for traco, chip in self.chips.items():
            chip.definir(selecionado=traco in selecionados)
        for traco, item in self.itens.items():
            item.setZValue(10 if traco in selecionados else 0)

    # ------------------------------------------------------------------ a legenda

    def _refazer_legenda(self) -> None:
        self._fluxo_da_legenda.limpar()
        self.chips = {}
        for traco in self.vista.tracos:
            r = traco.receita
            fonte = self._fonte_do(traco)
            resumo = []
            if fonte is not None and fonte.esta_ausente:
                resumo.append(self.tr("ausente"))
            if r.ganho != 1:
                resumo.append(f"×{r.ganho:g}".replace(".", ",").replace("-", "−"))
            if r.deslocamento_s:
                resumo.append(f"{formatar_si(r.deslocamento_s, 's', 3)}".replace("-", "−"))
            chip = ChipDeTraco(r.nome, r.cor, " · ".join(resumo))
            chip.definir(visivel=r.visivel, selecionado=traco in self.selecao.tracos,
                         progresso=fonte.progresso_da_piramide if fonte is not None else None)
            chip.clicado.connect(lambda t=traco: self.tracoClicado.emit(t, Qt.KeyboardModifier.NoModifier))
            self._fluxo_da_legenda.addWidget(chip)
            self.chips[traco] = chip
        self._legenda.setVisible(bool(self.chips))
        self._legenda.updateGeometry()

    # ------------------------------------------------------------------ o minimapa

    def _preparar_minimapa(self) -> None:
        item = self.minimapa.getPlotItem()
        item.hideAxis("left")
        item.hideAxis("bottom")
        item.hideButtons()
        item.setMenuEnabled(False)
        item.getViewBox().setMouseEnabled(x=False, y=False)
        item.getViewBox().setDefaultPadding(0.02)
        self._regiao = pg.LinearRegionItem(values=(0, 1))
        self._regiao.setZValue(10)
        self._regiao.sigRegionChanged.connect(self._regiao_mudou)
        self._item_do_minimapa: TracoLOD | None = None

    def _refazer_minimapa(self) -> None:
        vb = self.minimapa.getPlotItem().getViewBox()
        if self._item_do_minimapa is not None:
            vb.removeItem(self._item_do_minimapa)
            self._item_do_minimapa = None
        if self._regiao.scene() is None:
            vb.addItem(self._regiao, ignoreBounds=True)
        modelo = next((self.itens[t] for t in self.vista.tracos if t in self.itens and t.receita.visivel), None)
        self.minimapa.setVisible(modelo is not None)
        if modelo is None:
            return
        copia = TracoLOD(modelo._piramide, modelo._amostras, modelo._taxa, t0=modelo._t0, escala=modelo._escala,
                         deslocamento=modelo._deslocamento, cor=aparencia().tema.borda_forte, nome=modelo.nome)
        vb.addItem(copia)
        self._item_do_minimapa = copia
        vb.autoRange(padding=0.02)

    def _regiao_mudou(self) -> None:
        principal = self._faixa_principal()
        if principal is None or self._navegando:
            return
        x0, x1 = self._regiao.getRegion()
        self._navegando = True
        try:
            principal.getViewBox().setXRange(x0, x1, padding=0)
        finally:
            self._navegando = False

    # ------------------------------------------------------------------ navegar

    def janela_de_tempo(self) -> tuple[float, float] | None:
        principal = self._faixa_principal()
        return tuple(principal.getViewBox().viewRange()[0]) if principal is not None else None

    def ajustar(self) -> None:
        """A captura inteira no tempo, e cada faixa ajustada no Y."""
        for faixa in self.faixas.values():
            faixa.getViewBox().autoRange(padding=0.02)

    def _tempo_mudou(self, *_) -> None:
        if not isValid(self):
            return
        self._atualizar_info()
        janela = self.janela_de_tempo()
        if janela is not None and not self._navegando:
            self._navegando = True
            try:
                self._regiao.setRegion(janela)
            finally:
                self._navegando = False
        self._parada.start()

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
        janela = self.janela_de_tempo()
        primeiro = next(iter(self.itens.values()), None)
        if janela is None or primeiro is None:
            self.info.setText("")
            return
        x0, x1 = janela
        amostras = (x1 - x0) * primeiro._taxa
        self.info.setText(f"{formatar_si(x0, '', 6)} – {formatar_si(x1, 's', 6)} · {formatar_si(x1 - x0, 's', 3)} · "
                          f"{formatar_si(amostras, '', 3)} amostras".replace("-", "−").replace(" − ", " – "))

    # ------------------------------------------------------------------ selecionar

    def _clicou(self, x: float, y: float, modificadores) -> None:
        caixa = self.sender()
        candidatos = [(item.distancia_em_pixels(x, y), traco) for traco, item in self.itens.items()
                      if item.isVisible() and item.getViewBox() is caixa]
        perto = min(candidatos, key=lambda par: par[0], default=(float("inf"), None))
        self.tracoClicado.emit(perto[1] if perto[0] <= ALCANCE_DO_CLIQUE_PX else None, modificadores)

    # ------------------------------------------------------------------ tema

    def _tema_mudou(self, t: Tema) -> None:
        self.grafico.setBackground(QColor(t.afundada))
        self.minimapa.setBackground(QColor(t.fundo))
        # A janela visível em destaque, com as bordas grossas: numa captura longa, ela tem poucos pixels.
        destaque = QColor(t.destaque)
        destaque.setAlphaF(0.3)
        self._regiao.setBrush(destaque)
        for linha in self._regiao.lines:
            linha.setPen(pg.mkPen(t.destaque, width=2))
        for faixa in self.faixas.values():
            faixa.getViewBox().aplicar_tema(t)
            faixa.grade.aplicar_tema(t)
            for lado in ("left", "bottom"):
                faixa.getAxis(lado).aplicar_tema(t)
        for traco, item in self.itens.items():
            item.definir_cor(cor_do_traco(traco.receita.cor, t)[0])
        if self._item_do_minimapa is not None:
            self._refazer_minimapa()
