"""A vista de espectro (docs/gui-plan.md, 9.5; ES-01 e ES-02): FFT e Welch dos traços de uma vista de tempo.

* **Os traços** são os visíveis da vista de tempo ligada (``OpcoesDoEspectro.vista_de_tempo``; sem ela, a primeira do
  projeto), cada um com a sua cadeia: mudar a cadeia, o ganho ou a visibilidade lá muda o espectro aqui. Os números
  são os da ``api`` (``dados/espectros.py``).
* **O trecho:** a janela visível da vista de tempo, a região dos cursores dela ou a captura inteira. A conta refaz a
  cada parada do zoom ou dos cursores de lá.
* **A escala:** dB (a amplitude de pico, a convenção do ``adc_tool``: dBV na tensão), o valor RMS de cada tom ou dBc
  (relativa à fundamental, ou ao bin mais alto); a frequência linear ou logarítmica. A faixa dos supraharmônicos (2 a
  150 kHz) fica sombreada; a faixa válida do perfil de cada traço corrigido pela sonda, também, na cor do traço.
* **As marcas:** os picos mais altos acima do piso + 10 dB (o número da frequência só nos do primeiro traço), o piso de
  ruído (tracejado) e, com a FFT sincronizada, os harmônicos de f₁.
* **O cursor de frequência** (arrastar a linha): a frequência e o nível de cada traço ali.
* **As contas em segundo plano:** cada pedido cancela o anterior, e vale o mais recente. Um trecho grande de um traço
  com cadeia espera a materialização (o chip mostra o progresso), e a conta refaz quando ela fica pronta.

Cada mudança das opções é um comando de desfazer (``MudarOpcoesDaVista``) e vai para o projeto.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pyqtgraph as pg
import supraharmonicos.api as api
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from shiboken6 import isValid

from ...componentes.basicos import CampoComUnidade, Segmentado
from ...componentes.chip import ChipDeTraco
from ...componentes.fluxo import LayoutDeFluxo
from ...componentes.numeros import formatar_si
from ...dados import espectros as esp
from ...dados.cadeia import CorrecaoSonda
from ...graficos.faixa import EixoDoTema
from ...modelo.comandos import MudarOpcoesDaVista
from ...modelo.objetos import Projeto, Traco, Vista
from ...modelo.selecao import Selecao
from ...tema.aplicar import aparencia
from ...tema.tokens import Tema, cor_do_traco

FAIXA_DOS_SUPRAHARMONICOS = (2_000.0, 150_000.0)
ESPERA_MS = 40
METODOS, ESCALAS, TRECHOS = ("welch", "fft"), ("db", "rms", "dbc"), ("janela", "cursores", "captura")
AMOSTRAS_PARA_MOSTRAR_A_TAREFA = 20_000_000


class ResultadoDoTraco:
    """O espectro de um traço (ou por que não há um)."""

    def __init__(self, traco: Traco, espectro: api.Espectro | None = None, marcas: esp.Marcas | None = None,
                 erro: str = "", aguardando: bool = False, unidade: str = "V"):
        self.traco, self.espectro, self.marcas = traco, espectro, marcas
        self.erro, self.aguardando, self.unidade = erro, aguardando, unidade


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
        self.curvas: dict[Traco, pg.PlotDataItem] = {}
        self.chips: dict[Traco, ChipDeTraco] = {}
        self._tempo = None
        self._tarefa = None
        self._marcas_desenhadas: list = []
        self._montar()
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
                                       "cursores dela ou a captura inteira"))
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
        self.grafico.showGrid(x=True, y=True, alpha=0.15)
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
        if not isValid(self):
            return
        if self._tarefa is not None and self._tarefa.ativa:
            self._tarefa.cancelar()
        pedidos, nota = self._trechos()
        self._nota = nota
        if not pedidos:
            self.resultados = []
            self._desenhar()
            return
        o = self.opcoes
        parametros = o.parametros

        def calcular(progresso, cancelado):
            resultados = []
            for k, (traco, unidade, trecho) in enumerate(pedidos):
                if cancelado():
                    raise api.Cancelado()
                try:
                    espectro = esp.espectro_do_trecho(trecho, parametros, cancelado=cancelado,
                                                      progresso=lambda f, k=k: progresso((k + f) / len(pedidos)))
                    resultados.append(ResultadoDoTraco(traco, espectro, esp.marcas(espectro, o.picos, o.harmonicos),
                                                       unidade=unidade))
                except esp.AguardandoMaterializacao:
                    resultados.append(ResultadoDoTraco(traco, aguardando=True, unidade=unidade))
                except api.ErroSHAN as e:
                    resultados.append(ResultadoDoTraco(traco, erro=str(e), unidade=unidade))
            return resultados

        grande = sum(t.n_amostras for _, _, t in pedidos) > AMOSTRAS_PARA_MOSTRAR_A_TAREFA
        self._tarefa = self.tarefas.iniciar(self.tr("Espectro de {}").format(self.vista.nome), calcular,
                                            f"espectro-{self.vista.id}", mostrar=grande, ao_terminar=self._terminou)

    def _terminou(self, tarefa) -> None:
        if tarefa is not self._tarefa or not isValid(self):
            return
        self._tarefa = None
        if tarefa.estado == "concluida":
            self.resultados = tarefa.resultado
            self._desenhar()
            self.calculado.emit()
        elif tarefa.estado == "falhou":
            self.info.setText(tarefa.erro)

    def soltar(self) -> None:
        """A vista vai sair: a conta em andamento é cancelada."""
        if self._tarefa is not None and self._tarefa.ativa:
            self._tarefa.cancelar()
        self._espera.stop()

    def emitir_regiao(self) -> None:
        self.semRegiao.emit()

    # ------------------------------------------------------------------ o desenho

    def niveis(self, resultado: ResultadoDoTraco) -> tuple[np.ndarray, np.ndarray]:
        """As frequências e os níveis de um traço, na escala da vista (sem o DC na frequência log)."""
        e = resultado.espectro
        y = e.niveis(self.opcoes.escala)
        x = e.freqs_hz
        if self.opcoes.frequencia_log:
            x, y = x[1:], y[1:]
        return x, y

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
        for traco in [tr for tr in self.curvas if tr not in {r.traco for r in self.resultados if r.espectro}]:
            self.grafico.removeItem(self.curvas.pop(traco))
        self.grafico.setLogMode(x=o.frequencia_log, y=False)
        self.supra.setRegion([self._x(f) for f in FAIXA_DOS_SUPRAHARMONICOS])
        self.cursor.blockSignals(True)
        self.cursor.setValue(self._x(self.frequencia_do_cursor))
        self.cursor.blockSignals(False)
        primeiro = True
        for r in self.resultados:
            if r.espectro is None:
                continue
            cor = QColor(cor_do_traco(r.traco.receita.cor, t)[0])
            x, y = self.niveis(r)
            curva = self.curvas.get(r.traco)
            if curva is None:
                curva = pg.PlotDataItem()
                curva.setDownsampling(auto=True, method="peak")
                curva.setClipToView(True)
                self.grafico.addItem(curva)
                self.curvas[r.traco] = curva
            caneta = QPen(cor, 1.0)
            caneta.setCosmetic(True)
            curva.setPen(caneta)
            curva.setData(x, y)
            self._desenhar_marcas(r, cor, primeiro, t)
            primeiro = False
        self.grafico.setLabel("left", self._rotulo_y())
        self.grafico.enableAutoRange()
        self._refazer_legenda()
        self._mostrar_info()
        self._mostrar_cursor()

    def _desenhar_marcas(self, r: ResultadoDoTraco, cor: QColor, primeiro: bool, t: Tema) -> None:
        e, m, o = r.espectro, r.marcas, self.opcoes
        escala = e.niveis(o.escala)

        def nivel(f: float) -> float:
            return float(escala[int(np.argmin(np.abs(e.freqs_hz - f)))])

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
            piso = m.piso_db if o.escala == "db" else m.piso_db + float(escala[0] - e.db[0])
            linha = pg.InfiniteLine(pos=piso, angle=0, movable=False,
                                    pen=pg.mkPen(QColor(t.mudo), width=1, style=Qt.PenStyle.DashLine),
                                    label=self.tr("piso"), labelOpts={"position": 0.02, "color": t.mudo})
            self.grafico.addItem(linha, ignoreBounds=True)
            self._marcas_desenhadas.append(linha)
        if primeiro and o.harmonicos:
            for f in m.harmonicos_hz:
                linha = pg.InfiniteLine(pos=self._x(f), angle=90, movable=False,
                                        pen=pg.mkPen(QColor(t.borda_forte), width=1, style=Qt.PenStyle.DotLine))
                self.grafico.addItem(linha, ignoreBounds=True)
                self._marcas_desenhadas.append(linha)
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
        prontos = [r for r in self.resultados if r.espectro is not None]
        if not prontos:
            return
        f = self.frequencia_do_cursor
        textos = [formatar_si(f, "Hz", 5)]
        for r in prontos:
            freqs, niveis = r.espectro.freqs_hz, r.espectro.niveis(self.opcoes.escala)
            i = int(np.argmin(np.abs(freqs - f)))
            unidade = r.unidade if self.opcoes.escala == "rms" else ("dBc" if self.opcoes.escala == "dbc" else "dB")
            textos.append(f"{r.traco.nome}: {niveis[i]:.4g} {unidade}".replace(".", ","))
        self.cursor.setToolTip("\n".join(textos))
        self.leitura_do_cursor = textos

    def _tema_mudou(self, t: Tema) -> None:
        if not isValid(self):
            return
        self.grafico.setBackground(QColor(t.afundada))
        for eixo in (self.eixo_x, self.eixo_y):
            eixo.aplicar_tema(t)
        fundo = QColor(t.destaque)
        fundo.setAlpha(18)
        self.supra.setBrush(fundo)
        for linha in self.supra.lines:
            linha.setPen(pg.mkPen(None))
        self.cursor.setPen(pg.mkPen(QColor(t.texto2), width=1))
        if self.resultados:
            self._desenhar()
