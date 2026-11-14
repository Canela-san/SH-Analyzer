"""A vista de espectro (docs/gui-plan.md, 9.5; ES-01 e ES-02): FFT e Welch dos traços de uma vista de tempo.

* **Os traços** são os visíveis da vista de tempo ligada (``OpcoesDoEspectro.vista_de_tempo``; sem ela, a primeira do
  projeto), cada um com a sua cadeia: mudar a cadeia, o ganho ou a visibilidade lá muda o espectro aqui. Os números
  são os da ``api`` (``dados/espectros.py``).
* **O trecho:** a região dos cursores da vista de tempo (o padrão; sem eles, a janela visível), a janela visível ou
  a captura inteira. A conta refaz a cada parada do zoom ou dos cursores de lá, se o trecho mudou.
* **A escala:** dB (a amplitude de pico, a convenção do ``adc_tool``: dBV na tensão), o valor RMS de cada tom ou dBc
  (relativa à fundamental, ou ao bin mais alto); a frequência linear ou logarítmica. A faixa dos supraharmônicos (2 a
  150 kHz) fica sombreada; a faixa válida do perfil de cada traço corrigido pela sonda, também, na cor do traço.
* **As marcas:** os picos mais altos acima do piso + 10 dB (o número da frequência só nos do primeiro traço), o piso de
  ruído (tracejado) e, com a FFT sincronizada, os harmônicos de f₁.
* **O cursor de frequência** (arrastar a linha): a frequência e o nível de cada traço ali.
* **As contas em segundo plano:** cada pedido cancela o anterior, e vale o mais recente. Um trecho grande de um traço
  com cadeia espera a materialização (o chip mostra o progresso), e a conta refaz quando ela fica pronta.
* **Sem custo por quadro** (uma FFT de 60 s tem 6 milhões de bins): o espectro de um trecho já calculado não é
  refeito (mover os cursores com o trecho na janela, trocar a escala); os níveis na escala, a pirâmide e as marcas
  são preparados na thread de trabalho (``esp.preparar_desenho``); na frequência linear, o traço é desenhado pela
  pirâmide, como a vista de tempo (``TracoLOD``: a consulta de cada quadro lê só a pirâmide, e um pico de um bin
  aparece em qualquer zoom); na log, pela envoltória por coluna de pixel, refeita quando o zoom para; o cursor lê o
  bin pela grade uniforme, sem procurar. O zoom do usuário fica quando um resultado novo chega (o duplo clique
  ajusta).

Cada mudança das opções é um comando de desfazer (``MudarOpcoesDaVista``) e vai para o projeto.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pyqtgraph as pg
import supraharmonicos.api as api
from PySide6.QtCore import QLineF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QCheckBox, QGraphicsItem, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from shiboken6 import isValid

from ...componentes.basicos import CampoComUnidade, Segmentado
from ...componentes.chip import ChipDeTraco
from ...componentes.fluxo import LayoutDeFluxo
from ...componentes.numeros import formatar_si
from ...dados import espectros as esp
from ...dados.cadeia import CorrecaoSonda
from ...graficos.faixa import EixoDoTema, GradeDoTema
from ...graficos.traco_lod import TracoLOD
from ...modelo.comandos import MudarOpcoesDaVista
from ...modelo.objetos import Projeto, Traco, Vista
from ...modelo.selecao import Selecao
from ...tema.aplicar import aparencia
from ...tema.tokens import Tema, cor_do_traco

FAIXA_DOS_SUPRAHARMONICOS = (2_000.0, 150_000.0)
ESPERA_MS = 40
METODOS, ESCALAS, TRECHOS = ("welch", "fft"), ("db", "rms", "dbc"), ("janela", "cursores", "captura")
AMOSTRAS_PARA_MOSTRAR_A_TAREFA = 20_000_000
ESPERA_DA_ENVOLTORIA_MS = 30
OPCOES_QUE_PEDEM_AJUSTE = ("metodo", "escala", "frequencia_log", "trecho", "modo", "resolucao_hz")


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
        self._tempo = None
        self._tarefa = None
        self._marcas_desenhadas: list = []
        self._espectros: dict[tuple, api.Espectro] = {}      # a conta de cada trecho, para não refazer
        self._desenhos: dict[tuple, esp.Desenho] = {}        # e o desenho de cada escala
        self._itens: list = []
        self._ajustar = True                                  # o próximo desenho ajusta a vista
        self._opcoes_vistas = None
        self._montar()
        self._espera_da_envoltoria = QTimer(self)
        self._espera_da_envoltoria.setSingleShot(True)
        self._espera_da_envoltoria.setInterval(ESPERA_DA_ENVOLTORIA_MS)
        self._espera_da_envoltoria.timeout.connect(self._atualizar_envoltorias)
        self.grafico.getViewBox().sigXRangeChanged.connect(self._zoom_mudou)
        self.grafico.scene().sigMouseClicked.connect(self._clique_no_grafico)
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
        barra = QWidget()
        barra.setObjectName("barra_vista")
        linha = QHBoxLayout(barra)
        linha.setContentsMargins(8, 4, 8, 4)
        linha.setSpacing(8)
        self.metodo = Segmentado(["Welch", "FFT"])
        self.metodo.setToolTip(self.tr("Welch: a média de segmentos (o ruído e os supraharmônicos). FFT: um segmento "
                                       "só, sincronizado aos ciclos da fundamental (os harmônicos)"))
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
        for w in (self.metodo, self.resolucao, self.escala, self.trecho, self.log, self.harmonicos):
            linha.addWidget(w)
        linha.addStretch(1)

        self._legenda = QWidget()
        self._fluxo = LayoutDeFluxo(self._legenda)
        self._fluxo.setContentsMargins(10, 4, 10, 2)
        self.info = QLabel()
        self.info.setObjectName("info_espectro")
        self.info.setWordWrap(True)
        self.info.setContentsMargins(10, 0, 10, 4)

        self.eixo_x, self.eixo_y = EixoDoTema("bottom"), EixoDoTema("left")
        self.grafico = pg.PlotWidget(axisItems={"bottom": self.eixo_x, "left": self.eixo_y})
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
        self.supra = pg.LinearRegionItem(FAIXA_DOS_SUPRAHARMONICOS, movable=False)
        self.supra.setZValue(-20)
        self.supra.setToolTip(self.tr("A faixa dos supraharmônicos (2 a 150 kHz)"))
        self.grafico.addItem(self.supra, ignoreBounds=True)
        self.frequencia_do_cursor = 50_000.0     # em Hz (a posição da linha, no eixo log, é o log10 dela)
        self.cursor = pg.InfiniteLine(pos=self.frequencia_do_cursor, angle=90, movable=True)
        self.cursor.setZValue(30)
        self.cursor.sigPositionChanged.connect(self._cursor_movido)
        self.grafico.addItem(self.cursor, ignoreBounds=True)

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

    def _vista_mudou(self, _vista, campos) -> None:
        if "opcoes" in campos and isValid(self):
            antes, self._opcoes_vistas = self._opcoes_vistas, self.opcoes
            if antes is None or any(getattr(antes, n) != getattr(self.opcoes, n) for n in OPCOES_QUE_PEDEM_AJUSTE):
                self._ajustar = True
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
        if campos & {"cadeia", "ganho", "visivel", "cor", "nome", "deslocamento_s"}:
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
                a = int(min(max(round((regiao[0] - r.deslocamento_s) * canal.taxa_hz), 0), n))
                b = int(min(max(round((regiao[1] - r.deslocamento_s) * canal.taxa_hz), 0), n))
            estado = self.materializacoes.estado_de(traco)
            pronta = estado.pronta.amostras if estado is not None and estado.pronta is not None else None
            contexto = self.materializacoes.contexto(fonte, r.canal)
            pedidos.append((traco, canal.unidade, esp.TrechoDoTraco(fonte.fonte.captura, r.canal, r.cadeia, contexto,
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
            itens.append((traco, unidade, trecho, chave, (chave, o.escala, o.picos, o.harmonicos)))
        faltam = [item for item in itens if item[4] not in self._desenhos]
        if not faltam:
            self._mostrar_resultados(o, itens, {}, {}, {})
            return
        prontos = dict(self._espectros)

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
                desenhos[chave_do_desenho] = esp.preparar_desenho(espectro, o.escala, o.picos, o.harmonicos)
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
        if {r.traco for r in resultados} != {r.traco for r in self.resultados}:
            self._ajustar = True
        self.opcoes_calculadas, self.resultados = opcoes, resultados
        self._desenhar()
        self.calculado.emit()

    def soltar(self) -> None:
        """A vista vai sair: a conta em andamento é cancelada."""
        if self._tarefa is not None and self._tarefa.ativa:
            self._tarefa.cancelar()
        self._espera.stop()

    def emitir_regiao(self) -> None:
        self.semRegiao.emit()

    # ------------------------------------------------------------------ o desenho

    def niveis(self, resultado: ResultadoDoTraco) -> np.ndarray:
        """Os níveis de um traço na escala da vista (todos os bins)."""
        return resultado.desenho.niveis

    def _rotulo_y(self) -> str:
        unidade = next((r.unidade for r in self.resultados if r.espectro is not None), "V")
        escala = self.opcoes.escala
        if escala == "rms":
            return self.tr("valor RMS ({})").format(unidade)
        if escala == "dbc":
            return "dBc"
        primeiro = next((r.espectro for r in self.resultados if r.espectro is not None), None)
        return primeiro.rotulo(unidade) if primeiro is not None else ""

    def _x(self, f: float) -> float:
        """A posição de ``f`` no eixo (log10 na frequência logarítmica: é como o PyQtGraph posiciona os itens)."""
        return math.log10(max(f, 1e-12)) if self.opcoes.frequencia_log else f

    def _desenhar(self) -> None:
        t = aparencia().tema
        o = self.opcoes
        for item in self._marcas_desenhadas:
            self.grafico.removeItem(item)
        self._marcas_desenhadas = []
        prontos = [r for r in self.resultados if r.desenho is not None]
        for traco in [tr for tr in self.curvas if tr not in {r.traco for r in prontos}]:
            self.grafico.removeItem(self.curvas.pop(traco))
        self.grafico.setLogMode(x=o.frequencia_log, y=False)
        self.supra.setRegion([self._x(f) for f in FAIXA_DOS_SUPRAHARMONICOS])
        self.cursor.blockSignals(True)
        self.cursor.setValue(self._x(self.frequencia_do_cursor))
        self.cursor.blockSignals(False)
        for k, r in enumerate(prontos):
            cor = QColor(cor_do_traco(r.traco.receita.cor, t)[0])
            self._curva(r, cor)
            self._desenhar_marcas(r, cor, k == 0, t)
        self.grafico.setLabel("left", self._rotulo_y())
        if o.frequencia_log:
            self._atualizar_envoltorias(inteira=True)
        if self._ajustar and prontos:
            self._ajustar = False
            self.grafico.getViewBox().autoRange(padding=0.02)
        self._refazer_legenda()
        self._mostrar_info()
        self._mostrar_cursor()

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

    def _zoom_mudou(self, *_) -> None:
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
        if evento.double():
            self.grafico.getViewBox().autoRange(padding=0.02)

    def _desenhar_marcas(self, r: ResultadoDoTraco, cor: QColor, primeiro: bool, t: Tema) -> None:
        e, m, o, d = r.espectro, r.marcas, self.opcoes, r.desenho
        nivel = d.nivel_em

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
            linha = pg.InfiniteLine(pos=piso, angle=0, movable=False,
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
            chip.setToolTip(r.erro)
            chip.definir(selecionado=r.traco in self.selecao.tracos)
            chip.clicado.connect(lambda t=r.traco: self.tracoClicado.emit(t, Qt.KeyboardModifier.NoModifier))
            self._fluxo.addWidget(chip)
            self.chips[r.traco] = chip
        self._mostrar_progresso()

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
                partes.append(self.tr("Welch · {} · {} · {} segmentos").format(
                    e.rotulo_janela, formatar_si(e.resolucao_hz, "Hz", 3), e.n_segmentos))
            else:
                sinc = (self.tr(" · f₁ = {} · {} ciclos").format(formatar_si(e.f0_hz, "Hz", 6), e.n_ciclos)
                        if e.f0_hz else "")
                partes.append(self.tr("FFT · {} · {}{}").format(e.rotulo_janela, formatar_si(e.resolucao_hz, "Hz", 3),
                                                                sinc))
            partes.append(self.tr("{} de trecho").format(formatar_si(e.n_amostras / e.taxa_hz, "s", 4)))
        if any(r.aguardando for r in self.resultados):
            partes.append(self.tr("aguardando a transformação da captura inteira"))
        partes += [f"{r.traco.nome}: {r.erro}" for r in self.resultados if r.erro]
        self.info.setText(" · ".join(partes))

    def _cursor_movido(self, *_) -> None:
        x = float(self.cursor.value())
        if self.opcoes.frequencia_log:
            x = 10 ** min(max(x, -3.0), 9.0)
        self.frequencia_do_cursor = x
        self._mostrar_cursor()

    def _mostrar_cursor(self) -> None:
        prontos = [r for r in self.resultados if r.desenho is not None]
        if not prontos:
            return
        f = self.frequencia_do_cursor
        textos = [formatar_si(f, "Hz", 5)]
        for r in prontos:
            nivel = r.desenho.nivel_em(f)
            unidade = r.unidade if self.opcoes.escala == "rms" else ("dBc" if self.opcoes.escala == "dbc" else "dB")
            textos.append(f"{r.traco.nome}: {nivel:.4g} {unidade}".replace(".", ","))
        self.cursor.setToolTip("\n".join(textos))
        self.leitura_do_cursor = textos

    def _tema_mudou(self, t: Tema) -> None:
        if not isValid(self):
            return
        self.grafico.setBackground(QColor(t.afundada))
        for eixo in (self.eixo_x, self.eixo_y):
            eixo.aplicar_tema(t)
        self.grade.aplicar_tema(t)
        fundo = QColor(t.destaque)
        fundo.setAlpha(18)
        self.supra.setBrush(fundo)
        for linha in self.supra.lines:
            linha.setPen(pg.mkPen(None))
        self.cursor.setPen(pg.mkPen(QColor(t.texto2), width=1))
        if self.resultados:
            self._desenhar()
