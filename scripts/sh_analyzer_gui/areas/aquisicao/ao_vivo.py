"""O cockpit da captura (o B2 durante a captura; docs/gui-plan.md, 11.5; a F4.4): no centro da seção Capturar,
enquanto a captura roda e depois dela.

* **A barra** (:class:`BarraDaCaptura`): o estado, o tempo (o decorrido e o pedido), a barra, o recebido (no cartão,
  o gravado), a vazão, as amostras atrasadas e os buffers sobrescritos do último bloco, e o Parar.
* **O sinal ao vivo** (:class:`SinalAoVivo`): um gráfico por canal, os últimos 50 ms do bloco mais recente, na
  unidade de cada um e na cor da posição dele (as do formulário).
* **O espectro ao vivo** (:class:`EspectroAoVivo`): um canal por vez, a média dos últimos blocos, com a faixa de
  2 a 150 kHz (ou até a Nyquist) marcada.
* **No cartão**, as amostras ficam na placa: no lugar dos gráficos, o que cada bloco diz (:class:`BlocosNoCartao`).
* **A saída do** ``ler_adc`` (:class:`SaidaDoLerAdc`), as últimas linhas.
* **O fim** (:class:`PainelDoFim`): o resumo (o CRC conferido, a integridade, o que parou a captura) e as ações.

Os eixos e a grade são os da Análise (``graficos/faixa.py``): os números com a vírgula e os prefixos do SI.
"""

from __future__ import annotations

import html
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)
from sh_placa import pedido as pd
from shiboken6 import isValid

from ...componentes.basicos import Botao
from ...componentes.numeros import formatar_bytes, formatar_duracao, formatar_si
from ...graficos.faixa import EixoDoTema, GradeDoTema
from ...servicos.ao_vivo import QuadroAoVivo
from ...servicos.captura_da_placa import CapturaDaPlaca, FimDaCaptura
from ...tema.aplicar import aparencia
from ...tema.fontes import fonte_mono
from ...tema.tokens import TAMANHOS, Tema, cor_do_traco
from .formulario_de_captura import ListaDeProblemas
from .pecas import Painel, fonte, repolir
from .textos import traduzir

INTERVALO_DO_RELOGIO_MS = 250
ALTURA_DA_SAIDA = 112
ALTURA_POR_CANAL = 120
ALTURA_MINIMA_DO_SINAL, ALTURA_MAXIMA_DO_SINAL = 170, 330
ALTURA_DO_ESPECTRO = 230
"""O cockpit cabe numa janela de 1 280 × 900 com 2 canais: a barra, o sinal, o espectro e a saída do ler_adc."""


def relogio(segundos: float | None) -> str:
    """"03:12", "1:02:05": o tempo da captura."""
    if segundos is None or segundos != segundos:
        return "—"
    s = max(0, int(segundos))
    h, m = divmod(s, 3600)
    m, s = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _nome_da_grandeza(grandeza: str) -> str:
    return {"tensao": traduzir("tensão"), "corrente": traduzir("corrente"),
            "temperatura": traduzir("temperatura")}.get(grandeza, grandeza)


class BarraDaCaptura(QFrame):
    """A barra do topo do cockpit."""

    pararPedido = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("barra_da_captura")
        self.ponto = QLabel("●")
        self.ponto.setObjectName("ponto_da_captura")
        self.estado = QLabel()
        self.estado.setObjectName("estado_da_captura")
        self.estado.setFont(fonte("corpo", QFont.Weight.DemiBold))
        self.tempo = QLabel("00:00")
        self.tempo.setObjectName("tempo_da_captura")
        self.tempo.setFont(fonte_mono(TAMANHOS["secao"]))
        self.total = QLabel()
        self.total.setObjectName("texto_mudo")
        self.barra = QProgressBar()
        self.barra.setObjectName("barra_da_captura_progresso")
        self.barra.setRange(0, 1000)
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(6)
        self.barra.setMinimumWidth(80)
        self.recebido, self.fluxo = self._numero(), self._numero()
        self.atrasadas, self.sobrescritos = self._numero(), self._numero()
        self.parar = Botao(traduzir("Parar"), "perigo", "stop")
        self.parar.setObjectName("parar_captura")
        self.parar.clicked.connect(self.pararPedido.emit)
        # Duas linhas: o estado, o tempo, a barra e o Parar; embaixo, os números (numa linha só, a barra passaria da
        # largura do centro numa janela de 1 280 px).
        cima = QHBoxLayout()
        cima.setSpacing(10)
        cima.addWidget(self.ponto)
        cima.addWidget(self.estado)
        cima.addSpacing(6)
        cima.addWidget(self.tempo)
        cima.addWidget(self.total)
        cima.addWidget(self.barra, 1)
        cima.addWidget(self.parar)
        baixo = QHBoxLayout()
        baixo.setSpacing(16)
        for rotulo in (self.recebido, self.fluxo, self.atrasadas, self.sobrescritos):
            baixo.addWidget(rotulo)
        baixo.addStretch(1)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(14, 8, 10, 8)
        coluna.setSpacing(4)
        coluna.addLayout(cima)
        coluna.addLayout(baixo)

    @staticmethod
    def _numero() -> QLabel:
        rotulo = QLabel()
        rotulo.setObjectName("numero_da_captura")
        rotulo.setFont(fonte("secundario"))
        rotulo.setTextFormat(Qt.TextFormat.RichText)
        return rotulo

    def definir_estado(self, texto: str, nivel: str) -> None:
        """``nivel``: "gravando" (o ponto vermelho), "aviso", "ok" ou "erro"."""
        self.estado.setText(texto)
        for w in (self.ponto, self.estado):
            w.setProperty("nivel", nivel)
            repolir(w)

    @staticmethod
    def _par(rotulo: str, valor: str, nivel: str = "") -> str:
        cor = {"erro": aparencia().tema.erro, "aviso": aparencia().tema.aviso}.get(nivel, aparencia().tema.texto)
        return f"{rotulo} <b style='color:{cor}'>{valor}</b>"

    def definir_numeros(self, recebido: str, fluxo: str, atrasadas: int | None, sobrescritos: int | None) -> None:
        self.recebido.setText(self._par(traduzir("recebido"), recebido))
        self.fluxo.setText(self._par(traduzir("fluxo"), fluxo))
        self.atrasadas.setText(self._par(traduzir("atrasadas"), "—" if atrasadas is None else str(atrasadas),
                                         "aviso" if atrasadas else ""))
        self.sobrescritos.setText(self._par(traduzir("sobrescritos"), "—" if sobrescritos is None else
                                            str(sobrescritos), "erro" if sobrescritos else ""))


class _Grafico(pg.GraphicsLayoutWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("grafico_ao_vivo")
        self.ci.layout.setContentsMargins(4, 4, 8, 4)
        self.ci.layout.setVerticalSpacing(6)

    @staticmethod
    def novo_plot(rotulo_x: bool) -> tuple[pg.PlotItem, EixoDoTema, EixoDoTema, GradeDoTema]:
        eixo_x, eixo_y = EixoDoTema("bottom"), EixoDoTema("left")
        plot = pg.PlotItem(axisItems={"bottom": eixo_x, "left": eixo_y})
        plot.setMenuEnabled(False)
        plot.hideButtons()
        plot.setMouseEnabled(x=False, y=False)
        eixo_y.setWidth(56)
        if not rotulo_x:
            eixo_x.setStyle(showValues=False)
            eixo_x.setHeight(6)
        grade = GradeDoTema(eixo_x, eixo_y)
        plot.getViewBox().addItem(grade, ignoreBounds=True)
        return plot, eixo_x, eixo_y, grade


class SinalAoVivo(QWidget):
    """Um gráfico por canal: o fim do último bloco."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("sinal_ao_vivo")
        self.titulo = QLabel(traduzir("ao vivo · os últimos 50 ms do bloco mais recente"))
        self.titulo.setObjectName("texto_mudo")
        self.titulo.setFont(fonte("secundario"))
        self.grafico = _Grafico()
        self._plots: dict[int, tuple] = {}            # o número do canal: (plot, curva, eixo_x, eixo_y, grade)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(4)
        coluna.addWidget(self.titulo)
        coluna.addWidget(self.grafico, 1)
        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou(aparencia().tema)

    @property
    def canais(self) -> tuple[int, ...]:
        return tuple(self._plots)

    def preparar(self, canais: list[tuple[int, str, str]]) -> None:
        """Os gráficos dos canais (o número, a grandeza e a unidade), na ordem da captura; sem dados até o 1º
        bloco."""
        self.grafico.clear()
        self._plots.clear()
        self.grafico.setFixedHeight(min(ALTURA_MAXIMA_DO_SINAL, max(ALTURA_MINIMA_DO_SINAL,
                                                                     ALTURA_POR_CANAL * len(canais))))
        primeiro = None
        for i, (numero, grandeza, unidade) in enumerate(canais):
            plot, eixo_x, eixo_y, grade = _Grafico.novo_plot(rotulo_x=i == len(canais) - 1)
            curva = plot.plot()
            # O nome do canal numa etiqueta dentro do gráfico, e só a unidade no eixo: com vários canais, cada gráfico
            # é mais baixo que o nome em pé.
            eixo_y.definir_rotulo("", unidade)
            etiqueta = pg.TextItem(anchor=(0, 0))
            etiqueta.setParentItem(plot.getViewBox())
            etiqueta.setPos(4, 2)
            etiqueta.setZValue(20)
            etiqueta.setFont(fonte("secundario"))
            if i == len(canais) - 1:
                eixo_x.definir_rotulo(traduzir("tempo"), "s")
            if primeiro is None:
                primeiro = plot
            else:
                plot.setXLink(primeiro)
            self.grafico.addItem(plot, row=i, col=0)
            nome = traduzir("canal {} · {}").format(numero, _nome_da_grandeza(grandeza))
            self._plots[numero] = (plot, curva, eixo_x, eixo_y, grade, etiqueta, nome)
        self._tema_mudou(aparencia().tema)

    def etiqueta(self, numero: int) -> str:
        """O nome do canal ``numero`` como a etiqueta do gráfico dele o mostra."""
        return self._plots[numero][6]

    def mostrar(self, quadro: QuadroAoVivo) -> None:
        for canal in quadro.canais:
            itens = self._plots.get(canal.numero)
            if itens is None:
                continue
            plot, curva = itens[0], itens[1]
            curva.setData(canal.tempo_s, canal.sinal)
            plot.setXRange(float(canal.tempo_s[0]), 0.0, padding=0)
            pico = float(np.max(np.abs(canal.sinal))) if len(canal.sinal) else 1.0
            plot.setYRange(-pico * 1.1 if pico > 0 else -1.0, pico * 1.1 if pico > 0 else 1.0, padding=0)

    def curva(self, numero: int):
        return self._plots[numero][1]

    def _tema_mudou(self, t: Tema) -> None:
        if not isValid(self):
            return
        self.grafico.setBackground(QColor(t.afundada))
        fundo = QColor(t.afundada)
        fundo.setAlpha(215)
        for i, (_plot, curva, eixo_x, eixo_y, grade, etiqueta, nome) in enumerate(self._plots.values()):
            for eixo in (eixo_x, eixo_y):
                eixo.aplicar_tema(t)
            grade.aplicar_tema(t)
            cor = cor_do_traco(i, t)[0]
            curva.setPen(pg.mkPen(QColor(cor), width=1.4))
            eixo_y.definir_rotulo(eixo_y.labelText, eixo_y.labelUnits)
            # O traço na cor do canal leva a identidade; o nome fica na cor do texto (12.3).
            etiqueta.fill = pg.mkBrush(fundo)
            etiqueta.setHtml(f"<span style='color:{cor}'>&#9473;&#9473;</span>&nbsp;"
                             f"<span style='color:{t.texto2}'>{html.escape(nome)}</span>")


class EspectroAoVivo(QWidget):
    """O espectro de um canal: a média dos últimos blocos, com a faixa dos supraharmônicos marcada."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("espectro_ao_vivo")
        self.canal = QComboBox()
        self.canal.setObjectName("canal_do_espectro")
        self.canal.currentIndexChanged.connect(lambda _i: self._desenhar())
        self.media = QLabel()
        self.media.setObjectName("texto_mudo")
        self.media.setFont(fonte("secundario"))
        self.media.setWordWrap(True)                 # quebra no centro estreito, em vez de alargá-lo
        topo = QHBoxLayout()
        topo.setSpacing(8)
        rotulo = QLabel(traduzir("espectro ao vivo"))
        rotulo.setObjectName("texto_mudo")
        rotulo.setFont(fonte("secundario"))
        topo.addWidget(rotulo)
        topo.addWidget(self.canal)
        topo.addWidget(self.media, 1)
        self.eixo_x, self.eixo_y = EixoDoTema("bottom"), EixoDoTema("left")
        self.grafico = pg.PlotWidget(axisItems={"bottom": self.eixo_x, "left": self.eixo_y})
        self.grafico.setObjectName("grafico_espectro_ao_vivo")
        self.grafico.setFixedHeight(ALTURA_DO_ESPECTRO)
        self.grafico.setMenuEnabled(False)
        self.grafico.hideButtons()
        self.grafico.setMouseEnabled(x=False, y=False)
        self.eixo_y.setWidth(56)
        self.grade = GradeDoTema(self.eixo_x, self.eixo_y)
        self.grafico.getViewBox().addItem(self.grade, ignoreBounds=True)
        self.eixo_x.definir_rotulo(traduzir("frequência"), "Hz")
        self.eixo_y.definir_rotulo(traduzir("nível"), "dB")
        self.faixa = pg.LinearRegionItem([pd.BANDA_DOS_SUPRAHARMONICOS_HZ[0], pd.BANDA_DOS_SUPRAHARMONICOS_HZ[1]],
                                         movable=False)
        self.faixa.setZValue(-50)
        self.grafico.addItem(self.faixa)
        self.curva = self.grafico.plot()
        self._quadro: QuadroAoVivo | None = None
        self._cores: dict[int, str] = {}
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(4)
        coluna.addLayout(topo)
        coluna.addWidget(self.grafico, 1)
        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou(aparencia().tema)

    def preparar(self, canais: list[tuple[int, str, str]]) -> None:
        self.canal.blockSignals(True)
        self.canal.clear()
        self._cores = {}
        for i, (numero, grandeza, _unidade) in enumerate(canais):
            self.canal.addItem(traduzir("canal {} · {}").format(numero, _nome_da_grandeza(grandeza)), numero)
            self._cores[numero] = cor_do_traco(i, aparencia().tema)[0]
        self.canal.blockSignals(False)
        self._quadro = None
        self.curva.setData([], [])
        self.media.setText("")

    @property
    def numero(self) -> int | None:
        return self.canal.currentData()

    def mostrar(self, quadro: QuadroAoVivo) -> None:
        self._quadro = quadro
        self._desenhar()

    def _desenhar(self) -> None:
        quadro = self._quadro
        canal = quadro.canal(self.numero) if quadro is not None and self.numero is not None else None
        if canal is None:
            return
        cor = self._cores.get(canal.numero, aparencia().tema.tracos[0])
        self.curva.setData(canal.freqs_hz, canal.db, pen=pg.mkPen(QColor(cor), width=1.2))
        nyquist = canal.taxa_hz / 2
        self.faixa.setRegion((pd.BANDA_DOS_SUPRAHARMONICOS_HZ[0], min(pd.BANDA_DOS_SUPRAHARMONICOS_HZ[1], nyquist)))
        self.grafico.setXRange(0.0, nyquist, padding=0)
        validos = canal.db[np.isfinite(canal.db)]
        if len(validos):
            topo = float(np.max(validos))
            self.grafico.setYRange(max(float(np.percentile(validos, 2)) - 10, topo - 140), topo + 8, padding=0)
        self.eixo_y.definir_rotulo(traduzir("nível"), traduzir("dB re 1 {}").format(canal.unidade))
        self.media.setText(traduzir("média de {} bloco(s) · até {}").format(canal.na_media,
                                                                            formatar_si(nyquist, "Hz", 4)))

    def _tema_mudou(self, t: Tema) -> None:
        if not isValid(self):
            return
        self.grafico.setBackground(QColor(t.afundada))
        for eixo in (self.eixo_x, self.eixo_y):
            eixo.aplicar_tema(t)
        self.grade.aplicar_tema(t)
        fundo = QColor(t.acento)
        fundo.setAlpha(28)
        self.faixa.setBrush(pg.mkBrush(fundo))
        borda = QColor(t.acento)
        borda.setAlpha(110)
        for linha in self.faixa.lines:
            linha.setPen(pg.mkPen(borda, width=1, style=Qt.PenStyle.DashLine))
        self._desenhar()


class BlocosNoCartao(QFrame):
    """No cartão, o que cada bloco diz (as amostras ficam na placa até a transferência)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("blocos_no_cartao")
        self.nota = QLabel(traduzir("No cartão, as amostras ficam na placa até virem para o computador: aqui, o "
                                    "progresso e a integridade de cada bloco. A captura segue mesmo se a conexão "
                                    "cair; o aplicativo volta a acompanhá-la quando a placa volta."))
        self.nota.setObjectName("texto_mudo")
        self.nota.setWordWrap(True)
        self.ultimo = QLabel(traduzir("Esperando o primeiro bloco…"))
        self.ultimo.setObjectName("ultimo_bloco")
        self.ultimo.setWordWrap(True)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(14, 12, 14, 12)
        coluna.setSpacing(8)
        coluna.addWidget(self.nota)
        coluna.addWidget(self.ultimo)
        coluna.addStretch(1)

    def mostrar(self, bloco: dict | None) -> None:
        if not bloco:
            return
        saturadas = bloco.get("saturadas") or []
        partes = [traduzir("Bloco {} em {} (gravado em {} ms)").format(
            bloco.get("bloco"), relogio(bloco.get("t_s")), f"{float(bloco.get('gravacao_ms') or 0):.0f}")]
        if bloco.get("folga_minima_ciclos") is not None:
            partes.append(traduzir("folga mínima da PRU: {} ciclos").format(bloco["folga_minima_ciclos"]))
        if any(saturadas):
            partes.append(traduzir("saturadas por canal: {}").format(", ".join(str(s) for s in saturadas)))
        self.ultimo.setText(" · ".join(partes))


class SaidaDoLerAdc(QPlainTextEdit):
    """As últimas linhas do texto do ``ler_adc``."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("saida_do_ler_adc")
        self.setReadOnly(True)
        self.setMaximumBlockCount(300)
        self.setFont(fonte_mono(TAMANHOS["secundario"]))
        self.setFixedHeight(ALTURA_DA_SAIDA)
        # Quebrada na largura: o nome do arquivo e os avisos do ler_adc são linhas compridas.
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

    def acrescentar(self, linha: str) -> None:
        self.appendPlainText(linha)
        self.moveCursor(QTextCursor.MoveOperation.End)


class PainelDoFim(Painel):
    """O fim da captura: o título (concluída, parada, a queda), as linhas do resumo e as ações."""

    abrirPedido = Signal()
    pastaPedida = Signal()
    trazerPedido = Signal()
    novaPedida = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(traduzir("A captura"), parent)
        self.titulo.setWordWrap(True)                # o título comprido (a queda, o disco) quebra, ao lado do botão
        self.lista = ListaDeProblemas()
        self.abrir = Botao(traduzir("Abrir na Análise"), "primario", "onda")
        self.abrir.setObjectName("abrir_a_captura")
        self.pasta = Botao(traduzir("Mostrar na pasta"), "secundario", "pasta")
        self.pasta.setObjectName("mostrar_na_pasta")
        self.trazer = Botao(traduzir("Trazer para o computador"), "secundario", "baixar")
        self.trazer.setObjectName("trazer_a_captura")
        self.nova = Botao(traduzir("Nova captura"), "fantasma", "mais")
        self.nova.setObjectName("nova_captura")
        self.abrir.clicked.connect(self.abrirPedido.emit)
        self.pasta.clicked.connect(self.pastaPedida.emit)
        self.trazer.clicked.connect(self.trazerPedido.emit)
        self.nova.clicked.connect(self.novaPedida.emit)
        # "Nova captura" no topo do painel: a linha das ações cabe no centro estreito (com o caderno ao lado).
        self.lado.addWidget(self.nova)
        botoes = QHBoxLayout()
        botoes.setSpacing(8)
        for b in (self.abrir, self.trazer, self.pasta):
            botoes.addWidget(b)
        botoes.addStretch(1)
        corpo = QVBoxLayout()
        corpo.setContentsMargins(14, 0, 14, 12)
        corpo.setSpacing(10)
        corpo.addWidget(self.lista)
        corpo.addLayout(botoes)
        self.corpo.addLayout(corpo)


class Cockpit(QWidget):
    """O cockpit: a barra, os gráficos (ou os blocos do cartão), a saída do ``ler_adc`` e, no fim, o painel dele.
    Acompanha o serviço da captura e o ao vivo."""

    def __init__(self, captura: CapturaDaPlaca, ao_vivo, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("cockpit_da_captura")
        self.captura, self.ao_vivo = captura, ao_vivo
        self.fim = PainelDoFim()
        self.fim.setVisible(False)
        self.barra = BarraDaCaptura()
        self.barra.pararPedido.connect(captura.parar)
        self.sinal = SinalAoVivo()
        self.espectro = EspectroAoVivo()
        self.no_cartao = BlocosNoCartao()
        self.saida = SaidaDoLerAdc()
        self.aviso = QLabel()
        self.aviso.setObjectName("problema_erro")
        self.aviso.setWordWrap(True)
        self.aviso.setVisible(False)
        self.graficos = QWidget()
        g = QVBoxLayout(self.graficos)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(10)
        g.addWidget(self.sinal)
        g.addWidget(self.espectro)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(10)
        coluna.addWidget(self.fim)
        coluna.addWidget(self.barra)
        coluna.addWidget(self.aviso)
        coluna.addWidget(self.graficos)
        coluna.addWidget(self.no_cartao)
        rotulo = QLabel(traduzir("Saída do ler_adc"))
        rotulo.setObjectName("texto_mudo")
        rotulo.setFont(fonte("secundario"))
        coluna.addWidget(rotulo)
        coluna.addWidget(self.saida)
        coluna.addStretch(1)
        self._relogio = QTimer(self)
        self._relogio.setInterval(INTERVALO_DO_RELOGIO_MS)
        self._relogio.timeout.connect(self._mostrar_o_tempo)
        self._canais_preparados: tuple | None = None
        captura.mudou.connect(self._captura_mudou)
        captura.progrediu.connect(self._progrediu)
        captura.texto.connect(self.saida.acrescentar)
        ao_vivo.atualizou.connect(self._ao_vivo_atualizou)
        self._captura_mudou()

    # ------------------------------------------------------------------ o que vem do serviço

    def _canais(self) -> list[tuple[int, str, str]]:
        """Os canais da captura: os do pedido (a grandeza, a unidade do ganho) ou, numa captura retomada, os da linha
        ``inicio``."""
        c = self.captura
        if c.pedido is not None:
            return [(canal.numero, canal.grandeza, "A" if canal.grandeza == "corrente" and canal.ganho else
                     "°C" if canal.grandeza == "temperatura" and canal.ganho else
                     "V") for canal in c.pedido.canais]
        inicio = c.progresso.inicio if c.progresso is not None else None
        return [(int(n), "tensao", "V") for n in (inicio or {}).get("canais", [])]

    def _preparar(self) -> None:
        canais = tuple(self._canais())
        if canais == self._canais_preparados:
            return
        self._canais_preparados = canais
        self.sinal.preparar(list(canais))
        self.espectro.preparar(list(canais))

    def _captura_mudou(self) -> None:
        c = self.captura
        self.graficos.setVisible(not c.no_cartao)
        self.no_cartao.setVisible(c.no_cartao)
        if c.estado == "comecando":
            self._canais_preparados = None
            self.saida.clear()
            for linha in c.linhas:
                self.saida.acrescentar(linha)
            self._preparar()
            if not c.no_cartao and c.arquivo is not None:
                from sh_placa.captura import caminho_parcial
                self.ao_vivo.comecar(caminho_parcial(c.arquivo))
        if c.rodando:
            self._relogio.start()
        else:
            self._relogio.stop()
            f = c.fim
            if f is not None and f.arquivo is not None and f.gravou and f.arquivo.exists():
                self.ao_vivo.terminar(f.arquivo, f.blocos)       # o último bloco fica na tela
            else:
                self.ao_vivo.parar()
        textos = {"comecando": (traduzir("Começando: o sudo e a PRU…"), "aviso"),
                  "capturando": (traduzir("Gravando") if not c.retomada else traduzir("Gravando (retomada)"),
                                 "gravando"),
                  "parando": (traduzir("Parando: o ler_adc fecha o bloco em curso…"), "aviso"),
                  "sem_conexao": (traduzir("Sem conexão: a captura segue na placa"), "aviso"),
                  "feita": (traduzir("Terminada"), "ok"), "falhou": (traduzir("Não deu"), "erro")}
        texto, nivel = textos.get(c.estado, ("", "ok"))
        self.barra.definir_estado(texto, nivel)
        self.barra.parar.setEnabled(c.pode_parar)
        self.barra.parar.setVisible(c.rodando)
        self.barra.parar.setToolTip(traduzir("O ler_adc fecha a captura no último bloco inteiro, com o cabeçalho "
                                             "final certo.") if c.estado != "sem_conexao" else
                                    traduzir("Sem a conexão, o Parar não chega à placa: ele volta com ela."))
        erro = c.erro if c.estado in ("falhou", "capturando") else ""
        self.aviso.setText(erro)
        self.aviso.setVisible(bool(erro))
        self.mostrar_o_fim()
        self._progrediu()

    def _progrediu(self) -> None:
        c = self.captura
        p = c.progresso
        if p is not None and p.inicio is not None and c.pedido is None:
            self._preparar()                    # a captura retomada: os canais vieram com a linha inicio
        pedidos = p.blocos_pedidos if p is not None else (c.pedido.blocos_pedidos if c.pedido is not None else 0)
        segundos_por_bloco = float(p.inicio.get("segundos_por_bloco") or 0) if p is not None and p.inicio else 0.0
        if pedidos and segundos_por_bloco:
            self.barra.total.setText("/ " + relogio(pedidos * segundos_por_bloco))
            self.barra.barra.setValue(round(1000 * min(1.0, (p.blocos if p else 0) / pedidos)))
            self.barra.barra.setVisible(True)
        else:
            self.barra.total.setText(traduzir("/ até o Parar") if pedidos == 0 and p is not None else "")
            self.barra.barra.setVisible(False)
        ultimo = p.ultimo_bloco if p is not None else None
        self.barra.definir_numeros(formatar_bytes(p.bytes_recebidos) if p is not None else "—",
                                   (formatar_bytes(p.vazao_bytes_s) + "/s") if p is not None and p.vazao_bytes_s
                                   else "—",
                                   int(ultimo["amostras_atrasadas"]) if ultimo else None,
                                   int(ultimo["buffers_sobrescritos"]) if ultimo else None)
        if c.no_cartao:
            self.barra.recebido.setText(self.barra._par(traduzir("no cartão"), formatar_bytes(p.bytes_recebidos)
                                                        if p is not None else "—"))
            self.no_cartao.mostrar(ultimo)
        elif p is not None and p.blocos:
            self.ao_vivo.bloco(p.blocos)
        self.barra.parar.setEnabled(c.pode_parar)
        self._mostrar_o_tempo()

    def _mostrar_o_tempo(self) -> None:
        c = self.captura
        if c.rodando and c.comecou_em is not None and c.progresso is not None and c.progresso.inicio is not None:
            # O tempo da captura: o do último bloco e, entre os blocos, o relógio daqui (o bloco seguinte acerta).
            p = c.progresso
            desde = getattr(self, "_visto_em", None)
            if desde is None or desde[0] != p.blocos:
                self._visto_em = (p.blocos, time.monotonic(), p.segundos)
            _, quando, segundos = self._visto_em
            self.barra.tempo.setText(relogio(segundos + (time.monotonic() - quando if c.estado == "capturando"
                                                         else 0.0)))
        elif c.fim is not None:
            self.barra.tempo.setText(relogio(c.fim.duracao_s))
        elif not c.rodando:
            self.barra.tempo.setText("00:00")

    def _ao_vivo_atualizou(self, quadro: QuadroAoVivo) -> None:
        self.sinal.mostrar(quadro)
        self.espectro.mostrar(quadro)

    # ------------------------------------------------------------------ o fim

    def mostrar_o_fim(self) -> None:
        c = self.captura
        f = c.fim
        self.fim.setVisible(f is not None or c.estado == "falhou")
        if c.estado == "falhou":
            self.fim.titulo.setText(traduzir("A captura não deu"))
            self.fim.lista.definir([pd.Problema("captura", "erro", c.erro or traduzir("sem o motivo"))])
            for b in (self.fim.abrir, self.fim.pasta, self.fim.trazer):
                b.setVisible(False)
            return
        if f is None:
            return
        self.fim.titulo.setText(titulo_do_fim(f))
        self.fim.lista.definir(linhas_do_fim(f, c))
        local = c.local_do_fim()
        no_computador = local is not None and local.exists()
        self.fim.abrir.setVisible(no_computador)
        self.fim.pasta.setVisible(no_computador)
        self.fim.trazer.setVisible(f.destino == "cartao" and f.gravou and c.transferencias is not None
                                   and c.transferencia_do_fim() is None)


def titulo_do_fim(f: FimDaCaptura) -> str:
    if not f.gravou:
        return traduzir("A captura terminou sem nenhum bloco")
    if f.caiu:
        return traduzir("A captura parou: {}").format(traduzir("a conexão caiu") if f.motivo == "conexao_caiu" else
                                                      traduzir("o disco deste computador recusou a gravação"))
    if f.motivo == "adc_mudo":
        return traduzir("A captura parou: o ADC não está respondendo")
    if f.motivo == "sobrescrito":
        return traduzir("A captura parou: amostras perdidas na placa")
    if f.parada_pedida:
        return traduzir("Captura parada em {}").format(relogio(f.duracao_s))
    return traduzir("Captura concluída: {}").format(relogio(f.duracao_s))


def linhas_do_fim(f: FimDaCaptura, captura: CapturaDaPlaca) -> list[pd.Problema]:
    """O resumo do fim, como linhas (o ✓, o ! e o ✗)."""
    linhas: list[pd.Problema] = []
    tamanho = formatar_bytes(f.arquivo.stat().st_size) if f.arquivo is not None and f.arquivo.exists() else None
    onde = (traduzir("em {}").format(f.arquivo) if f.arquivo is not None else
            traduzir("no cartão da placa ({})").format(f.nome))
    linhas.append(pd.Problema("arquivo", "info", traduzir("{} bloco(s), {}{}, {}").format(
        f.blocos, formatar_duracao(f.duracao_s), f" · {tamanho}" if tamanho else "", onde)))
    if f.destino == "computador" and f.gravou:
        if f.crc_confere is True:
            linhas.append(pd.Problema("crc", "info", traduzir("o CRC das amostras confere com o do ler_adc")))
        elif f.crc_confere is False:
            linhas.append(pd.Problema("crc", "erro", traduzir("o CRC das amostras NÃO confere com o do ler_adc: algo "
                                                              "mudou no caminho")))
        elif f.caiu:
            linhas.append(pd.Problema("crc", "aviso", traduzir(
                "fechada aqui com os blocos inteiros que chegaram (o CRC é o deste computador): o que vinha depois "
                "se perdeu{}").format(f" ({f.falha})" if f.falha else "")))
    if f.integridade is not None:
        atrasadas, sobrescritos, sdo = f.integridade
        if not any(f.integridade):
            linhas.append(pd.Problema("integridade", "info", traduzir("integridade: nenhuma amostra atrasada, nenhum "
                                                                      "buffer sobrescrito, nenhum ruído no SDO")))
        else:
            linhas.append(pd.Problema("integridade", "erro" if sobrescritos else "aviso", traduzir(
                "integridade: {} amostras atrasadas, {} buffers sobrescritos, {} quadros com ruído no SDO").format(
                atrasadas, sobrescritos, sdo)))
    if f.motivo == "adc_mudo":
        linhas.append(pd.Problema("adc", "erro", traduzir("o ADC não está respondendo (amostras todas iguais): a "
                                                          "placa de aquisição sem alimentação ou os pinos da PRU sem "
                                                          "configuração")))
    if f.destino == "cartao" and f.gravou:
        item = captura.transferencia_do_fim()
        if item is not None:
            texto = {"na_fila": traduzir("na fila para vir para o computador"),
                     "esperando_a_captura": traduzir("esperando a placa ficar livre para vir"),
                     "baixando": traduzir("vindo para o computador: {} %").format(round(100 * item.fracao)),
                     "conferindo": traduzir("conferindo a cópia no computador"),
                     "conferida": traduzir("no computador, conferida: {}").format(item.local)}.get(
                item.estado, traduzir("a transferência: {}").format(item.erro or item.estado))
            nivel = "erro" if item.estado in ("corrompida", "falhou") else "info"
            linhas.append(pd.Problema("transferencia", nivel, texto))
        elif captura.pedido is not None and captura.pedido.trazer_no_fim and captura.transferencias is not None:
            linhas.append(pd.Problema("transferencia", "info", traduzir("procurando a captura na lista da placa para "
                                                                        "trazê-la")))
    return linhas
