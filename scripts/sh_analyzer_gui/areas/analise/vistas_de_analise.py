"""As vistas de análise da Fase 7 (docs/gui-progress.md, 4h), ligadas à vista de tempo como as das bandas e dos
harmônicos (``VistaLigada``): o traço, o trecho e a conta em segundo plano. As contas são as de ``dados/analises.py``.

* **O XY** (``VistaDeXY``, F7.3): um traço contra outro (o laço V × I, a histerese); a curva, ou a densidade (a
  persistência) quando o trecho tem muitas amostras; e a tabela da potência pela IEEE 1459 (P, S, FP, P₁, Q₁, S₁,
  cos φ₁, φ₁, S_N, os THD), com a tensão no eixo horizontal e a corrente no vertical.
* **O histograma** (``VistaDeHistograma``, F7.4): a distribuição dos valores do traço (as colunas, em contagem linear
  ou logarítmica, e a curva acumulada), a saturação e a ocupação da faixa do ADC (sem cadeia), e a tabela das
  estatísticas (a média, o RMS, o desvio, a assimetria, a curtose, os percentis, o fator de crista).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
import pyqtgraph as pg
import supraharmonicos.api as api
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHeaderView,
    QLabel,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
)

from ...componentes.basicos import CampoComUnidade, Segmentado
from ...componentes.numeros import decimal, formatar_si
from ...dados import analises as an
from ...dados import espectros as esp
from ...dados import qualidade as q
from ...graficos.faixa import EixoDoTema
from ...tema.aplicar import aparencia
from ...tema.tokens import cor_do_traco
from .medidas import MedidasDaVista, numero_para_planilha
from .vistas_de_mapa import VistaLigada


def texto_da_tabela(tabela: QTableWidget, so_selecao: bool = False) -> str:
    """A tabela em texto com tabulações (o cabeçalho e as linhas), pronta para colar numa planilha."""
    linhas = sorted({i.row() for i in tabela.selectedIndexes()}) if so_selecao else range(tabela.rowCount())
    cabecalho = [tabela.horizontalHeaderItem(c).text() if tabela.horizontalHeaderItem(c) else ""
                 for c in range(tabela.columnCount())]
    corpo = ["\t".join(tabela.item(r, c).text() if tabela.item(r, c) else "" for c in range(tabela.columnCount()))
             for r in linhas]
    return "\n".join(["\t".join(cabecalho), *corpo]) + "\n"


def _tabela(nome: str, colunas: int) -> QTableWidget:
    """Uma tabela de resultados: só leitura, e o Ctrl+C (ou o menu) copia para a planilha (a seleção, ou tudo)."""
    from PySide6.QtGui import QAction, QGuiApplication, QKeySequence

    tabela = QTableWidget(0, colunas)
    tabela.setObjectName(nome)
    tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tabela.verticalHeader().hide()
    tabela.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    tabela.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
    for rotulo, so_selecao, atalho in (("Copiar a seleção", True, QKeySequence.StandardKey.Copy),
                                       ("Copiar a tabela inteira", False, None)):
        acao = QAction(tabela.tr(rotulo), tabela)
        if atalho is not None:
            acao.setShortcut(atalho)
            acao.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        acao.triggered.connect(lambda _=False, s=so_selecao: QGuiApplication.clipboard().setText(
            texto_da_tabela(tabela, s and bool(tabela.selectedIndexes()))))
        tabela.addAction(acao)
    return tabela


def _preencher(tabela: QTableWidget, linhas: list[tuple[str, ...]]) -> None:
    tabela.setRowCount(len(linhas))
    for k, linha in enumerate(linhas):
        for c, texto in enumerate(linha):
            tabela.setItem(k, c, QTableWidgetItem(texto))


def _numero(valor: float, casas: int = 4) -> str:
    if valor is None or not math.isfinite(valor):
        return "—"
    return decimal(f"{valor:.{casas}f}").replace("-", "−")


class _ComSegundoTraco:
    """O segundo traço da vista (o do eixo vertical do XY, a saída da transferência): o seletor, e o trecho dele no
    mesmo instante do primeiro (o deslocamento no tempo de cada traço vale; o que um não tem, sai dos dois)."""

    def _novo_seletor_y(self, dica: str) -> QComboBox:
        self.seletor_y = QComboBox()
        self.seletor_y.setObjectName("traco_y_da_vista")
        self.seletor_y.setToolTip(dica)
        self.seletor_y.activated.connect(lambda i: self._mudar(traco_y=int(self.seletor_y.itemData(i))))
        self._traco_y = None
        return self.seletor_y

    def _extras(self, tempo, tracos, traco, inicio, fim):
        self.seletor_y.blockSignals(True)
        self.seletor_y.clear()
        for i, t in enumerate(tracos):
            self.seletor_y.addItem(t.nome, i)
        indice = self.opcoes.traco_y if self.opcoes.traco_y < len(tracos) else min(1, len(tracos) - 1)
        self.seletor_y.setCurrentIndex(indice)
        self.seletor_y.blockSignals(False)
        outro = tracos[indice]
        r = outro.receita
        try:
            fonte = self.projeto.fonte(r.fonte)
        except KeyError:
            return None, None
        canal = fonte.canal(r.canal)
        meu = self.projeto.fonte(traco.receita.fonte).canal(traco.receita.canal)
        if canal.taxa_hz != meu.taxa_hz:
            return ("taxa", indice), self.tr("os dois traços têm taxas diferentes ({} e {}): a conta precisa das "
                                             "mesmas amostras no tempo").format(formatar_si(meu.taxa_hz, "S/s", 5),
                                                                                formatar_si(canal.taxa_hz, "S/s", 5))
        passo = round((traco.receita.deslocamento_s - r.deslocamento_s) * canal.taxa_hz)
        a, b = inicio + passo, fim + passo
        descarte = max(0, -a)                  # o começo do primeiro que o segundo não tem
        a, b = max(a, 0), min(b, len(canal.amostras))
        if b - a < 2:
            return ("fora", indice, a, b), self.tr("os dois traços não se sobrepõem no tempo")
        estado = self.materializacoes.estado_de(outro)
        pronta = estado.pronta.amostras if estado is not None and estado.pronta is not None else None
        trecho = esp.TrechoDoTraco(fonte.fonte.captura, r.canal, r.cadeia, self.materializacoes.contexto(fonte, r.canal),
                                   a, b, r.ganho, pronta, r.offset)
        self._traco_y = outro
        return (id(outro), r.fonte, r.canal, r.cadeia, r.ganho, r.offset, a, b, descarte, pronta is not None), \
            (trecho, descarte)

    def _os_dois(self, trecho: esp.TrechoDoTraco, extra) -> tuple[esp.TrechoDoTraco, esp.TrechoDoTraco]:
        """Os trechos dos dois traços, no mesmo instante e do mesmo tamanho."""
        if extra is None:
            raise api.ErroSHAN("o segundo traço não está mais no projeto")
        if isinstance(extra, str):
            raise api.ErroSHAN(extra)
        outro, descarte = extra
        x = replace(trecho, inicio=min(trecho.fim, trecho.inicio + descarte))
        m = min(x.n_amostras, outro.n_amostras)
        return replace(x, fim=x.inicio + m), replace(outro, fim=outro.inicio + m)

    def _unidade_y(self) -> str:
        t = self._traco_y
        if t is None:
            return ""
        try:
            return t.receita.unidade_de(self.projeto.fonte(t.receita.fonte).canal(t.receita.canal).unidade)
        except KeyError:
            return ""


def _botao_de_copiar(vista, nome: str, rotulo: str, dica: str, texto) -> QToolButton:
    """Um botão da barra da vista que copia ``texto()`` (a planilha, com tabulações) para a área de transferência."""
    from PySide6.QtGui import QGuiApplication

    botao = QToolButton()
    botao.setObjectName(nome)
    botao.setText(rotulo)
    botao.setAutoRaise(True)
    botao.setToolTip(dica)

    def copiar() -> None:
        conteudo = texto()
        if conteudo:
            QGuiApplication.clipboard().setText(conteudo)

    botao.clicked.connect(copiar)
    vista._linha.addWidget(botao)
    return botao


# ------------------------------------------------------------------ o XY e a potência (F7.3)


class VistaDeXY(_ComSegundoTraco, VistaLigada):
    nome_da_conta = "XY"
    unidade_x = ""

    def _montar_conteudo(self, coluna: QVBoxLayout) -> None:
        self.setObjectName("vista_xy")
        self.seletor.setToolTip(self.tr("O traço do eixo horizontal (a tensão, na potência)"))
        self._novo_seletor_y(self.tr("O traço do eixo vertical (a corrente, na potência)"))
        self.com_potencia = QCheckBox(self.tr("Potência"))
        self.com_potencia.setObjectName("com_potencia")
        self.com_potencia.setToolTip(self.tr("A potência pela IEEE 1459, com a tensão no eixo horizontal e a corrente "
                                             "no vertical"))
        self.com_potencia.toggled.connect(lambda v: self._mudar(potencia=bool(v)))
        for w in (QLabel(self.tr("contra")), self.seletor_y, self.com_potencia):
            self._linha.addWidget(w)
        self.grafico = pg.PlotWidget(axisItems={"bottom": EixoDoTema("bottom"), "left": EixoDoTema("left")})
        self.grafico.setObjectName("grafico_xy")
        self.grafico.setMenuEnabled(False)
        self.grafico.hideButtons()
        self.grafico.showGrid(x=True, y=True, alpha=0.15)
        self.curva = pg.PlotDataItem([], [])
        self.densidade = pg.ImageItem(axisOrder="col-major")
        self.densidade.setColorMap(pg.colormap.get("viridis"))
        self.grafico.addItem(self.densidade)
        self.grafico.addItem(self.curva)
        self.tabela = _tabela("tabela_potencia", 3)
        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.addWidget(self.grafico)
        divisor.addWidget(self.tabela)
        divisor.setSizes([620, 320])
        coluna.addWidget(divisor, 1)

    def _mostrar_opcoes_proprias(self) -> None:
        self.com_potencia.blockSignals(True)
        self.com_potencia.setChecked(self.opcoes.potencia)
        self.com_potencia.blockSignals(False)

    def _conta_com(self, trecho, extra, progresso, cancelado):
        x, y = self._os_dois(trecho, extra)
        vx = an.valores_do_trecho(x, cancelado=cancelado)
        vy = an.valores_do_trecho(y, cancelado=cancelado)
        taxa = trecho.captura.canal(trecho.numero).taxa_hz
        return an.xy(vx, vy, taxa, com_potencia=self.opcoes.potencia)

    def _desenhar(self) -> None:
        r = self.resultado
        if r is None:
            self.curva.setData([], [])
            self.densidade.clear()
            self.tabela.setRowCount(0)
            return
        t = aparencia().tema
        ux, uy = self.traco_unidade(), self._unidade_y()
        self.grafico.setLabel("bottom", self.traco.nome, units=ux)
        self.grafico.setLabel("left", self._traco_y.nome if self._traco_y is not None else "", units=uy)
        if r.densidade is not None:
            self.curva.setData([], [])
            x0, x1, y0, y1 = r.limites
            self.densidade.setImage(np.log1p(r.densidade), autoLevels=True)
            self.densidade.setRect(pg.QtCore.QRectF(x0, y0, (x1 - x0) or 1.0, (y1 - y0) or 1.0))
            self.densidade.show()
        else:
            self.densidade.hide()
            cor = QColor(cor_do_traco(self.traco.receita.cor, t)[0])
            self.curva.setData(r.x, r.y, pen=pg.mkPen(cor, width=1))
        self.grafico.getViewBox().autoRange(padding=0.04)
        self.tabela.setHorizontalHeaderLabels([self.tr("Grandeza"), self.tr("Valor"), self.tr("O que é")])
        p = r.potencia
        if p is None:
            _preencher(self.tabela, [(self.tr("Potência"), "—", r.problema_da_potencia or self.tr("desligada"))])
            return
        w = "W"
        linhas = [
            ("f₁", formatar_si(p.f1_hz, "Hz", 7), self.tr("{} ciclos inteiros").format(p.ciclos)),
            ("V", formatar_si(p.v_rms, ux, 6), self.tr("o RMS total da tensão")),
            ("I", formatar_si(p.i_rms, uy, 6), self.tr("o RMS total da corrente")),
            ("P", formatar_si(p.p, w, 6), self.tr("a potência ativa: a média de v·i")),
            ("S", formatar_si(p.s, "VA", 6), self.tr("a aparente: V·I")),
            (self.tr("FP"), _numero(p.fp), self.tr("o fator de potência: P/S")),
            ("P₁", formatar_si(p.p1, w, 6), self.tr("a ativa da fundamental")),
            ("Q₁", formatar_si(p.q1, "var", 6), self.tr("a reativa da fundamental (positiva: indutiva)")),
            ("S₁", formatar_si(p.s1, "VA", 6), self.tr("a aparente da fundamental")),
            ("cos φ₁", _numero(p.cos_fi1), self.tr("o fator de potência de deslocamento")),
            ("φ₁", _numero(p.fi1_graus, 3) + " °", self.tr("a fase da tensão menos a da corrente")),
            ("S_N", formatar_si(p.sn, "VA", 6), self.tr("a aparente não fundamental: √(S² − S₁²)")),
            ("THD V", _numero(100 * p.thd_v, 3) + " %", self.tr("V_H / V₁")),
            ("THD I", _numero(100 * p.thd_i, 3) + " %", self.tr("I_H / I₁")),
        ]
        _preencher(self.tabela, linhas)

    def _descricao(self) -> list[str]:
        r = self.resultado
        if r is None:
            return []
        partes = [self.tr("{} amostras").format(r.n)]
        if r.densidade is not None:
            partes.append(self.tr("a densidade (a persistência dos ciclos, em escala logarítmica)"))
        if r.potencia is not None:
            partes.append(self.tr("P {} · FP {} · cos φ₁ {}").format(formatar_si(r.potencia.p, "W", 5),
                                                                    _numero(r.potencia.fp), _numero(r.potencia.cos_fi1)))
        return partes

    def medidas(self) -> MedidasDaVista | None:
        return None


# ------------------------------------------------------------------ o histograma e as estatísticas (F7.4)


class VistaDeHistograma(VistaLigada):
    nome_da_conta = "Histograma"
    unidade_x = ""
    opcoes_do_desenho = ("escala", "acumulada")

    def _montar_conteudo(self, coluna: QVBoxLayout) -> None:
        self.setObjectName("vista_histograma")
        self.colunas = QSpinBox()
        self.colunas.setObjectName("colunas_do_histograma")
        self.colunas.setRange(2, 100_000)
        self.colunas.setKeyboardTracking(False)
        self.colunas.setToolTip(self.tr("Quantas colunas, do mínimo ao máximo do trecho (sem cadeia, cada coluna junta "
                                        "um número inteiro de códigos do ADC)"))
        self.colunas.valueChanged.connect(lambda v: self._mudar(colunas=int(v)))
        self.escala = Segmentado([self.tr("Linear"), self.tr("Log")])
        self.escala.setToolTip(self.tr("A escala das contagens (a logarítmica mostra as caudas)"))
        self.escala.escolhaMudou.connect(lambda i: self._mudar(escala=esp.ESCALAS_DO_HISTOGRAMA[i]))
        self.acumulada = QCheckBox(self.tr("Acumulada"))
        self.acumulada.setObjectName("histograma_acumulado")
        self.acumulada.setToolTip(self.tr("A curva acumulada (a CDF: a fração das amostras abaixo de cada valor)"))
        self.acumulada.toggled.connect(lambda v: self._mudar(acumulada=bool(v)))
        for w in (QLabel(self.tr("Colunas")), self.colunas, self.escala, self.acumulada):
            self._linha.addWidget(w)
        self.grafico = pg.PlotWidget(axisItems={"bottom": EixoDoTema("bottom"), "left": EixoDoTema("left")})
        self.grafico.setObjectName("grafico_histograma")
        self.grafico.setMenuEnabled(False)
        self.grafico.hideButtons()
        self.grafico.showGrid(x=False, y=True, alpha=0.15)
        self.barras = pg.PlotDataItem([], [], stepMode="center", fillLevel=0)
        self.curva_acumulada = pg.PlotDataItem([], [])
        self.grafico.addItem(self.barras)
        self.grafico.addItem(self.curva_acumulada)
        self.tabela = _tabela("tabela_estatisticas", 2)
        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.addWidget(self.grafico)
        divisor.addWidget(self.tabela)
        divisor.setSizes([640, 300])
        coluna.addWidget(divisor, 1)

    def _mostrar_opcoes_proprias(self) -> None:
        o = self.opcoes
        self.colunas.blockSignals(True)
        self.colunas.setValue(o.colunas)
        self.colunas.blockSignals(False)
        self.escala.blockSignals(True)
        self.escala.escolher(esp.ESCALAS_DO_HISTOGRAMA.index(o.escala))
        self.escala.blockSignals(False)
        self.acumulada.blockSignals(True)
        self.acumulada.setChecked(o.acumulada)
        self.acumulada.blockSignals(False)
        if self.resultado is not None and o.colunas == getattr(self.opcoes_calculadas, "colunas", None):
            self._desenhar()

    def _conta(self, trecho, progresso, cancelado):
        return an.histograma_e_estatisticas(trecho, self.opcoes.colunas, progresso=progresso, cancelado=cancelado)

    def _desenhar(self) -> None:
        r = self.resultado
        if r is None:
            self.barras.setData([], [])
            self.curva_acumulada.setData([], [])
            self.tabela.setRowCount(0)
            return
        t = aparencia().tema
        cor = QColor(cor_do_traco(self.traco.receita.cor, t)[0])
        preenchimento = QColor(cor)
        preenchimento.setAlpha(110)
        h, e = r.histograma, r.estatisticas
        unidade = self.traco_unidade()
        log = self.opcoes.escala == "log"
        alturas = h.contagens.astype(float)
        if log:
            alturas = np.log10(np.maximum(alturas, 0.5))
        self.barras.setData(h.bordas, alturas, stepMode="center", fillLevel=math.log10(0.5) if log else 0,
                            pen=pg.mkPen(cor, width=1), brush=preenchimento)
        if self.opcoes.acumulada and len(alturas):
            topo = float(np.max(alturas)) if len(alturas) else 1.0
            self.curva_acumulada.setData(h.bordas[1:], h.cdf() * topo,
                                         pen=pg.mkPen(QColor(t.texto2), width=1, style=Qt.PenStyle.DashLine))
        else:
            self.curva_acumulada.setData([], [])
        self.grafico.setLabel("bottom", self.traco.nome, units=unidade)
        self.grafico.setLabel("left", self.tr("log₁₀ da contagem") if log else self.tr("amostras"))
        self.grafico.getViewBox().autoRange(padding=0.02)
        self.tabela.setHorizontalHeaderLabels([self.tr("Estatística"), self.tr("Valor")])
        linhas = [(self.tr("Amostras"), str(e.n)), (self.tr("Média"), formatar_si(e.media, unidade, 6)),
                  (self.tr("RMS"), formatar_si(e.rms, unidade, 6)),
                  (self.tr("Desvio-padrão"), formatar_si(e.desvio, unidade, 6)),
                  (self.tr("Assimetria"), _numero(e.assimetria)), (self.tr("Curtose (excesso)"), _numero(e.curtose)),
                  (self.tr("Mínimo"), formatar_si(e.minimo, unidade, 6)),
                  (self.tr("Máximo"), formatar_si(e.maximo, unidade, 6)),
                  (self.tr("Pico a pico"), formatar_si(e.pico_a_pico, unidade, 6)),
                  (self.tr("Fator de crista"), _numero(e.fator_de_crista))]
        for p, v in e.percentis.items():
            linhas.append((self.tr("Percentil {}").format(decimal(f"{p:g}")), formatar_si(v, unidade, 6)))
        if h.codigos:
            linhas += [(self.tr("Saturadas embaixo"), str(h.saturadas_baixo)),
                       (self.tr("Saturadas em cima"), str(h.saturadas_alto)),
                       (self.tr("Ocupação da faixa do ADC"), _numero(100 * h.ocupacao, 2) + " %")]
        _preencher(self.tabela, linhas)

    def _descricao(self) -> list[str]:
        r = self.resultado
        if r is None:
            return []
        e, h = r.estatisticas, r.histograma
        partes = [self.tr("{} amostras · média {} · desvio {}").format(
            e.n, formatar_si(e.media, self.traco_unidade(), 5), formatar_si(e.desvio, self.traco_unidade(), 5))]
        if h.codigos and (h.saturadas_baixo or h.saturadas_alto):
            partes.append(self.tr("⚠ {} amostras saturadas").format(h.saturadas_baixo + h.saturadas_alto))
        if not e.percentis_exatos:
            partes.append(self.tr("os percentis vêm do histograma fino (± {})").format(
                formatar_si(e.resolucao_dos_percentis / 2, self.traco_unidade(), 3)))
        return partes

    def medidas(self) -> MedidasDaVista | None:
        return None


# ------------------------------------------------------------------ os eventos (F7.5)


MARGEM_DO_EVENTO_S = 0.05
"""Quanto a vista de tempo mostra antes e depois de um evento curto (três ciclos de 60 Hz)."""
LINHAS_DOS_EVENTOS = ("afundamento", "elevacao", "interrupcao", "supraharmonicos", "saturacao", "descontinuidade")
"""As linhas do gráfico dos eventos, de cima para baixo (os do cabeçalho não têm instante: só na tabela)."""
CONTAGENS = ("saturacao", "cabecalho")


@dataclass(frozen=True)
class ResultadoDosEventos:
    eventos: list
    indices: object | None          # os índices de qualidade, quando os picos de supraharmônicos foram procurados
    aviso: str = ""


class VistaDeEventos(VistaLigada):
    """A lista dos eventos do traço (``dados/qualidade.py``): o gráfico com uma linha por tipo, ligado ao tempo, e a
    tabela; um clique numa linha da tabela mostra o evento na vista de tempo."""

    nome_da_conta = "Eventos"

    def _montar_conteudo(self, coluna: QVBoxLayout) -> None:
        self.setObjectName("vista_eventos")
        self._linhas: list = []
        self.tensao = QCheckBox(self.tr("Tensão"))
        self.tensao.setObjectName("eventos_de_tensao")
        self.tensao.setToolTip(self.tr("O traço é uma tensão: procura os afundamentos (abaixo de 90 % da referência), "
                                       "as elevações (acima de 110 %) e as interrupções (abaixo de 5 %) no RMS de "
                                       "meio ciclo (IEC 61000-4-30)"))
        self.tensao.toggled.connect(lambda v: self._mudar(tensao=bool(v)))
        rotulo = QLabel(self.tr("Referência"))
        rotulo.setToolTip(self.tr("A tensão de referência (RMS) dos afundamentos e das elevações; vazio ou 0: a "
                                  "mediana do RMS de meio ciclo do trecho"))
        self.referencia = CampoComUnidade("", 0.0, minimo=0.0, maximo=1e12, digitos=5)
        self.referencia.setObjectName("referencia_dos_eventos")
        self.referencia.setMaximumWidth(110)
        self.referencia.valorMudou.connect(lambda v: self._mudar(referencia=float(v)))
        self.supra = QCheckBox(self.tr("Supraharmônicos"))
        self.supra.setObjectName("eventos_de_supraharmonicos")
        self.supra.setToolTip(self.tr("Os picos do RMS de 2 a 9 kHz e de 9 a 150 kHz acima de 10 vezes (20 dB) a "
                                      "mediana, nas janelas de 10/12 ciclos"))
        self.supra.toggled.connect(lambda v: self._mudar(supraharmonicos=bool(v)))
        self.filtro = QComboBox()
        self.filtro.setObjectName("filtro_dos_eventos")
        self.filtro.setToolTip(self.tr("Os tipos de evento na tabela e no gráfico"))
        self.filtro.addItem(self.tr("Todos os tipos"), None)
        for tipo, nome in q.TIPOS_DE_EVENTO.items():
            self.filtro.addItem(self.tr(nome), tipo)
        self.filtro.currentIndexChanged.connect(lambda _: self._desenhar() if self.resultado is not None else None)
        for w in (self.tensao, rotulo, self.referencia, self.supra, self.filtro):
            self._linha.addWidget(w)
        self.grafico = pg.PlotWidget(axisItems={"bottom": EixoDoTema("bottom"), "left": EixoDoTema("left")})
        self.grafico.setObjectName("grafico_eventos")
        self.grafico.setMenuEnabled(False)
        self.grafico.hideButtons()
        self.grafico.showGrid(x=True, y=False, alpha=0.15)
        self.grafico.getViewBox().setMouseEnabled(x=True, y=False)
        self.grafico.setLabel("bottom", self.tr("tempo"), units="s")
        self.grafico.getAxis("left").setTicks([[(k, self.tr(q.TIPOS_DE_EVENTO[t]))
                                                for k, t in enumerate(LINHAS_DOS_EVENTOS)]])
        self.grafico.setYRange(-0.6, len(LINHAS_DOS_EVENTOS) - 0.4, padding=0)
        self.grafico.getViewBox().invertY(True)
        self._itens: list = []
        self.tabela = _tabela("tabela_eventos", 5)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tabela.horizontalHeader().setStretchLastSection(True)
        self.tabela.itemSelectionChanged.connect(self._ir_ao_evento)
        divisor = QSplitter(Qt.Orientation.Vertical)
        divisor.addWidget(self.grafico)
        divisor.addWidget(self.tabela)
        divisor.setSizes([190, 330])
        coluna.addWidget(divisor, 1)

    def _mostrar_opcoes_proprias(self) -> None:
        o = self.opcoes
        for caixa, valor in ((self.tensao, o.tensao), (self.supra, o.supraharmonicos)):
            caixa.blockSignals(True)
            caixa.setChecked(valor)
            caixa.blockSignals(False)
        self.referencia.setEnabled(o.tensao)
        if o.referencia > 0:
            self.referencia.definir_valor(o.referencia)
        else:
            self.referencia.definir_varios(self.tr("a mediana"))

    def _conta(self, trecho, progresso, cancelado):
        o = self.opcoes
        indices, aviso = None, ""
        metade = (lambda f: progresso(0.5 * f)) if progresso is not None else None
        if o.supraharmonicos:
            try:
                indices = q.indices(trecho, progresso=metade, cancelado=cancelado)
            except api.ErroSHAN as e:
                aviso = self.tr("sem os picos de supraharmônicos: {}").format(e)
        resto = (lambda f: progresso(0.5 + 0.5 * f)) if progresso is not None and o.supraharmonicos else progresso
        lista = q.eventos(trecho, q.CriteriosDosEventos(o.referencia or None, o.tensao), indices_prontos=indices,
                          progresso=resto, cancelado=cancelado)
        return ResultadoDosEventos(lista, indices, aviso)

    def eventos_mostrados(self) -> list:
        """Os eventos da tabela, na ordem dela (o filtro de tipo vale)."""
        return list(self._linhas)

    def _desenhar(self) -> None:
        for item in self._itens:
            self.grafico.removeItem(item)
        self._itens = []
        r = self.resultado
        if r is None:
            self._linhas = []
            self.tabela.setRowCount(0)
            return
        unidade = self.traco_unidade()
        self.referencia.unidade = unidade
        tipo = self.filtro.currentData()
        self._linhas = [e for e in r.eventos if tipo is None or e.tipo == tipo]
        t0 = self.traco.receita.deslocamento_s
        cor = QColor(cor_do_traco(self.traco.receita.cor, aparencia().tema)[0])
        preenchimento = QColor(cor)
        preenchimento.setAlpha(150)
        for k, nome in enumerate(LINHAS_DOS_EVENTOS):
            daqui = [e for e in self._linhas if e.tipo == nome and math.isfinite(e.inicio_s)]
            if not daqui:
                continue
            inicios = np.array([t0 + e.inicio_s for e in daqui])
            duracoes = np.array([max(e.duracao_s, 0.0) for e in daqui])
            longos = duracoes > 0
            if longos.any():
                barras = pg.BarGraphItem(x0=inicios[longos], width=duracoes[longos], y=np.full(longos.sum(), k),
                                         height=0.6, brush=preenchimento, pen=pg.mkPen(cor, width=1))
                self.grafico.addItem(barras)
                self._itens.append(barras)
            marcas = pg.ScatterPlotItem(inicios, np.full(len(inicios), k), symbol="d", size=8,
                                        brush=pg.mkBrush(cor), pen=pg.mkPen(QColor(aparencia().tema.afundada), width=1))
            self.grafico.addItem(marcas)
            self._itens.append(marcas)
        self._ligar_o_tempo(self.grafico.getViewBox())
        self.tabela.blockSignals(True)
        self.tabela.setHorizontalHeaderLabels([self.tr("Tipo"), self.tr("Início"), self.tr("Duração"),
                                               self.tr("Valor"), self.tr("Detalhe")])
        linhas = []
        for e in self._linhas:
            inicio = formatar_si(t0 + e.inicio_s, "s", 7) if math.isfinite(e.inicio_s) else "—"
            duracao = formatar_si(e.duracao_s, "s", 4) if math.isfinite(e.duracao_s) and e.duracao_s > 0 else "—"
            valor = str(int(e.valor)) if e.tipo in CONTAGENS else formatar_si(e.valor, unidade, 5)
            linhas.append((self.tr(q.TIPOS_DE_EVENTO[e.tipo]), inicio, duracao, valor, e.detalhe))
        _preencher(self.tabela, linhas)
        self.tabela.blockSignals(False)

    def _ir_ao_evento(self) -> None:
        """O evento da linha escolhida na vista de tempo, com uma margem de cada lado."""
        linhas = sorted({i.row() for i in self.tabela.selectedIndexes()})
        if len(linhas) != 1 or linhas[0] >= len(self._linhas):
            return
        e = self._linhas[linhas[0]]
        tempo = self.vista_de_tempo()
        if tempo is None or self.traco is None or not math.isfinite(e.inicio_s):
            return
        inicio = self.traco.receita.deslocamento_s + e.inicio_s
        duracao = max(e.duracao_s, 0.0) if math.isfinite(e.duracao_s) else 0.0
        margem = max(0.5 * duracao, MARGEM_DO_EVENTO_S)
        tempo.mostrar_tempo(inicio - margem, inicio + duracao + margem)

    def _descricao(self) -> list[str]:
        r = self.resultado
        if r is None:
            return []
        if not r.eventos:
            partes = [self.tr("nenhum evento no trecho")]
        else:
            contagem: dict[str, int] = {}
            for e in r.eventos:
                contagem[e.tipo] = contagem.get(e.tipo, 0) + 1
            partes = [self.tr("{} evento(s): {}").format(len(r.eventos), ", ".join(
                f"{self.tr(q.TIPOS_DE_EVENTO[t])} {n}" for t, n in contagem.items()))]
        if r.aviso:
            partes.append(r.aviso)
        return partes


# ------------------------------------------------------------------ a qualidade de energia (F7.6)


class VistaDeQualidade(VistaLigada):
    """Os índices de qualidade em janelas de 10/12 ciclos (IEC 61000-4-30) ao longo do tempo, ligados à vista de
    tempo, os agregados de 150/180 ciclos e a tabela das estatísticas de todos os índices."""

    nome_da_conta = "Qualidade de energia"
    opcoes_do_desenho = ("indice", "agregados")

    def _montar_conteudo(self, coluna: QVBoxLayout) -> None:
        self.setObjectName("vista_qualidade")
        self.indice = QComboBox()
        self.indice.setObjectName("indice_da_qualidade")
        self.indice.setToolTip(self.tr("O índice no gráfico (a tabela traz todos)"))
        for nome in esp.INDICES_DE_QUALIDADE:
            self.indice.addItem(self.tr(q.NOMES_DOS_INDICES[nome]), nome)
        self.indice.activated.connect(lambda i: self._mudar(indice=self.indice.itemData(i)))
        self.agregados = QCheckBox(self.tr("Agregados de 150/180 ciclos"))
        self.agregados.setObjectName("agregados_da_qualidade")
        self.agregados.setToolTip(self.tr("Os agregados de ~3 s (15 janelas): o RMS dos índices de RMS, a média dos "
                                          "outros (IEC 61000-4-30)"))
        self.agregados.toggled.connect(lambda v: self._mudar(agregados=bool(v)))
        for w in (self.indice, self.agregados):
            self._linha.addWidget(w)
        _botao_de_copiar(self, "copiar_janelas_da_qualidade", self.tr("Copiar as janelas"),
                         self.tr("Copia todos os índices de cada janela (uma linha por janela) para a planilha"),
                         self.texto_das_janelas)
        self.grafico = pg.PlotWidget(axisItems={"bottom": EixoDoTema("bottom"), "left": EixoDoTema("left")})
        self.grafico.setObjectName("grafico_qualidade")
        self.grafico.setMenuEnabled(False)
        self.grafico.hideButtons()
        self.grafico.showGrid(x=True, y=True, alpha=0.15)
        self.grafico.setLabel("bottom", self.tr("tempo"), units="s")
        self.curva = pg.PlotDataItem([], [])
        self.curva_agregada = pg.PlotDataItem([], [])
        self.grafico.addItem(self.curva)
        self.grafico.addItem(self.curva_agregada)
        self.tabela = _tabela("tabela_qualidade", 6)
        divisor = QSplitter(Qt.Orientation.Vertical)
        divisor.addWidget(self.grafico)
        divisor.addWidget(self.tabela)
        divisor.setSizes([360, 250])
        coluna.addWidget(divisor, 1)

    def _mostrar_opcoes_proprias(self) -> None:
        o = self.opcoes
        self.indice.setCurrentIndex(esp.INDICES_DE_QUALIDADE.index(o.indice))
        self.agregados.blockSignals(True)
        self.agregados.setChecked(o.agregados)
        self.agregados.blockSignals(False)
        if self.resultado is not None:
            self._desenhar()

    def _conta(self, trecho, progresso, cancelado):
        return q.indices(trecho, progresso=progresso, cancelado=cancelado)

    def _escala(self, nome: str) -> tuple[float, str]:
        """O fator e a unidade de um índice na tela: o THD em %, a frequência em Hz, os RMS na unidade do traço."""
        if nome == "thd":
            return 100.0, "%"
        if nome == "frequencia":
            return 1.0, "Hz"
        if nome in q.INDICES_DE_RMS:
            return 1.0, self.traco_unidade()
        return 1.0, ""

    def _texto(self, nome: str, valor: float) -> str:
        fator, unidade = self._escala(nome)
        if unidade == "%":
            return _numero(fator * valor, 3) + " %"
        if unidade == "Hz":
            return _numero(valor, 4) + " Hz"
        return formatar_si(valor, unidade, 5) if unidade else _numero(valor, 4)

    def _desenhar(self) -> None:
        r = self.resultado
        if r is None:
            self.curva.setData([], [])
            self.curva_agregada.setData([], [])
            self.tabela.setRowCount(0)
            return
        t = aparencia().tema
        nome = self.opcoes.indice
        fator, unidade = self._escala(nome)
        t0 = self.traco.receita.deslocamento_s
        duracoes = r.ciclos_por_janela / r.valores["frequencia"]
        cor = QColor(cor_do_traco(self.traco.receita.cor, t)[0])
        simbolo = "o" if r.n_janelas <= 400 else None
        self.curva.setData(t0 + r.inicios_s + duracoes / 2, fator * r.valores[nome], pen=pg.mkPen(cor, width=1),
                           symbol=simbolo, symbolSize=4, symbolBrush=cor, symbolPen=None)
        n_ag = len(r.agregados_s)
        if self.opcoes.agregados and n_ag:
            ultimo = np.arange(n_ag) * q.JANELAS_DA_AGREGACAO + q.JANELAS_DA_AGREGACAO - 1
            centros = (r.agregados_s + r.inicios_s[ultimo] + duracoes[ultimo]) / 2
            self.curva_agregada.setData(t0 + centros, fator * r.agregados[nome], symbol="s", symbolSize=6,
                                        pen=pg.mkPen(QColor(t.texto1), width=2, style=Qt.PenStyle.DashLine),
                                        symbolBrush=QColor(t.texto1), symbolPen=None)
        else:
            self.curva_agregada.setData([], [])
        self.grafico.setLabel("left", self.tr(q.NOMES_DOS_INDICES[nome]), units=unidade)
        self.grafico.enableAutoRange(axis="y")
        self._ligar_o_tempo(self.grafico.getViewBox())
        self.tabela.setHorizontalHeaderLabels([self.tr("Índice"), self.tr("Mínimo"), self.tr("Média"), "P95", "P99",
                                               self.tr("Máximo")])
        linhas = []
        for indice in esp.INDICES_DE_QUALIDADE:
            e = r.estatisticas[indice]
            linhas.append((self.tr(q.NOMES_DOS_INDICES[indice]),
                           *(self._texto(indice, v) for v in (e.minimo, e.media, e.p95, e.p99, e.maximo))))
        _preencher(self.tabela, linhas)

    def texto_das_janelas(self) -> str:
        """Todos os índices de cada janela, com o começo dela no tempo da vista, para a planilha."""
        r = self.resultado
        if r is None:
            return ""
        cabecalho = [self.tr("Início (s)")]
        for nome in esp.INDICES_DE_QUALIDADE:
            _fator, unidade = self._escala(nome)
            cabecalho.append(f"{self.tr(q.NOMES_DOS_INDICES[nome])} ({unidade})" if unidade
                             else self.tr(q.NOMES_DOS_INDICES[nome]))
        t0 = self.traco.receita.deslocamento_s
        linhas = ["\t".join(cabecalho)]
        for k in range(r.n_janelas):
            linhas.append("\t".join([numero_para_planilha(t0 + float(r.inicios_s[k]))] + [
                numero_para_planilha(self._escala(nome)[0] * float(r.valores[nome][k]))
                for nome in esp.INDICES_DE_QUALIDADE]))
        return "\n".join(linhas) + "\n"

    def _descricao(self) -> list[str]:
        r = self.resultado
        if r is None:
            return []
        partes = [self.tr("{} janelas de {} ciclos (IEC 61000-4-30) · {} agregados de {} ciclos").format(
            r.n_janelas, r.ciclos_por_janela, len(r.agregados_s), q.JANELAS_DA_AGREGACAO * r.ciclos_por_janela)]
        if r.trechos_sem_fundamental:
            partes.append(self.tr("⚠ {} pedaço(s) sem a fundamental ficaram de fora").format(r.trechos_sem_fundamental))
        return partes


# ------------------------------------------------------------------ a transferência (F7.7)


CONFIANCA = 0.95


class VistaDeTransferencia(_ComSegundoTraco, VistaLigada):
    """A função de transferência H₁ da entrada (o traço da vista) para a saída (o segundo traço): o ganho e a fase com
    o intervalo de confiança de 95 %, e a coerência, contra a frequência em escala logarítmica."""

    nome_da_conta = "Transferência"
    unidade_x = "Hz"

    def _montar_conteudo(self, coluna: QVBoxLayout) -> None:
        self.setObjectName("vista_transferencia")
        self.seletor.setToolTip(self.tr("O traço da entrada (x)"))
        self._novo_seletor_y(self.tr("O traço da saída (y): H₁ = Pxy / Pxx, a saída sobre a entrada"))
        rotulo = QLabel(self.tr("Resolução"))
        self.resolucao = CampoComUnidade("Hz", 100.0, minimo=0.01, maximo=1e6, digitos=4)
        self.resolucao.setObjectName("resolucao_da_transferencia")
        self.resolucao.setMaximumWidth(100)
        rotulo.setToolTip(self.tr("A largura de cada bin do Welch (Hann, 50 % de sobreposição): mais fina, menos "
                                  "médias e um intervalo de confiança mais largo"))
        self.resolucao.valorMudou.connect(lambda v: self._mudar(resolucao_hz=float(v)))
        for w in (QLabel("→"), self.seletor_y, rotulo, self.resolucao):
            self._linha.addWidget(w)
        _botao_de_copiar(self, "copiar_transferencia", self.tr("Copiar os dados"),
                         self.tr("Copia a frequência, |H| e o intervalo dele, a fase, a coerência e as densidades "
                                 "para a planilha"), self.texto_dos_dados)
        self.graficos = []
        for nome in ("grafico_transferencia", "grafico_fase", "grafico_coerencia"):
            g = pg.PlotWidget(axisItems={"bottom": EixoDoTema("bottom"), "left": EixoDoTema("left")})
            g.setObjectName(nome)
            g.setMenuEnabled(False)
            g.hideButtons()
            g.showGrid(x=True, y=True, alpha=0.15)
            g.setLogMode(x=True, y=False)
            if self.graficos:
                g.setXLink(self.graficos[0])
            self.graficos.append(g)
        self.grafico, self.grafico_fase, self.grafico_coerencia = self.graficos
        self.grafico_fase.setLabel("left", self.tr("fase"), units="°")
        self.grafico_coerencia.setLabel("left", self.tr("coerência γ²"))
        self.grafico_coerencia.setLabel("bottom", self.tr("frequência"), units="Hz")
        self.grafico_coerencia.setYRange(0, 1.02, padding=0)
        self.curvas = {}
        for chave, g in (("mag", self.grafico), ("fase", self.grafico_fase)):
            baixo, alto = pg.PlotDataItem([], []), pg.PlotDataItem([], [])
            banda = pg.FillBetweenItem(baixo, alto)
            curva = pg.PlotDataItem([], [])
            for item in (baixo, alto, banda, curva):
                g.addItem(item)
            self.curvas[chave] = (curva, baixo, alto, banda)
        self.curva_coerencia = pg.PlotDataItem([], [])
        self.grafico_coerencia.addItem(self.curva_coerencia)
        divisor = QSplitter(Qt.Orientation.Vertical)
        for g in self.graficos:
            divisor.addWidget(g)
        divisor.setSizes([300, 200, 150])
        coluna.addWidget(divisor, 1)

    def _tema_mudou(self, t) -> None:
        super()._tema_mudou(t)
        for g in getattr(self, "graficos", ())[1:]:
            g.setBackground(QColor(t.afundada))

    def _mostrar_opcoes_proprias(self) -> None:
        self.resolucao.definir_valor(self.opcoes.resolucao_hz)

    def _conta_com(self, trecho, extra, progresso, cancelado):
        x, y = self._os_dois(trecho, extra)
        return q.transferencia_do_trecho(x, y, self.opcoes.resolucao_hz, progresso=progresso, cancelado=cancelado)

    def _dados(self):
        """As colunas do resultado sem o DC (o Welch tira a média de cada segmento): f, |H| (dB), o mínimo e o máximo
        dele, a fase, a meia largura dela e a coerência."""
        r = self.resultado
        baixo, alto, meia = r.intervalo(CONFIANCA)
        return (r.frequencias[1:], r.magnitude_db[1:], baixo[1:], alto[1:], r.fase_graus[1:], meia[1:],
                r.coerencia[1:])

    def _desenhar(self) -> None:
        r = self.resultado
        if r is None:
            for curva, baixo, alto, _banda in self.curvas.values():
                for item in (curva, baixo, alto):
                    item.setData([], [])
            self.curva_coerencia.setData([], [])
            return
        t = aparencia().tema
        cor = QColor(cor_do_traco(self.traco.receita.cor, t)[0])
        faixa = QColor(cor)
        faixa.setAlpha(60)
        f, mag, baixo, alto, fase, meia, coerencia = self._dados()
        finitos = mag[np.isfinite(mag)]
        piso = float(np.min(finitos)) - 20.0 if len(finitos) else -200.0
        baixo = np.where(np.isfinite(baixo), baixo, piso)            # o círculo passa pela origem: até o piso
        sem_traco = pg.mkPen(None)
        for chave, (y, y0, y1) in (("mag", (mag, baixo, alto)), ("fase", (fase, fase - meia, fase + meia))):
            curva, item_baixo, item_alto, banda = self.curvas[chave]
            item_baixo.setData(f, y0, pen=sem_traco)
            item_alto.setData(f, y1, pen=sem_traco)
            banda.setBrush(pg.mkBrush(faixa))
            curva.setData(f, y, pen=pg.mkPen(cor, width=1))
        self.curva_coerencia.setData(f, coerencia, pen=pg.mkPen(cor, width=1))
        ux, uy = self.traco_unidade(), self._unidade_y()
        referencia = f"{uy or '1'}/{ux or '1'}" if (ux or uy) and ux != uy else ""
        self.grafico.setLabel("left", self.tr("|H| (dB re 1 {})").format(referencia) if referencia
                              else self.tr("|H| (dB)"))
        for g in (self.grafico, self.grafico_fase):
            g.getViewBox().autoRange(padding=0.02)
        self.grafico_coerencia.setYRange(0, 1.02, padding=0)

    def texto_dos_dados(self) -> str:
        if self.resultado is None:
            return ""
        r = self.resultado
        colunas = self._dados() + (r.pxx[1:], r.pyy[1:])
        cabecalho = ["f (Hz)", "|H| (dB)", self.tr("|H| mínimo (dB)"), self.tr("|H| máximo (dB)"), self.tr("fase (°)"),
                     self.tr("± fase (°)"), self.tr("coerência"), "Pxx", "Pyy"]
        linhas = ["\t".join(cabecalho)]
        for k in range(len(colunas[0])):
            linhas.append("\t".join(numero_para_planilha(float(c[k])) for c in colunas))
        return "\n".join(linhas) + "\n"

    def _texto_x(self, valor: float) -> str:
        return formatar_si(10.0 ** valor, "Hz", 6)

    def medidas(self) -> MedidasDaVista | None:
        """Nos cursores: a frequência, |H|, a fase e a coerência de cada um, e a diferença de ganho entre eles."""
        if self.cursores.posicoes is None or self.resultado is None:
            return None
        f, mag, _b, _a, fase, _m, coerencia = self._dados()
        pontos = []
        for posicao in self.cursores.posicoes:
            fc = 10.0 ** posicao
            pontos.append((fc, float(np.interp(fc, f, mag)), float(np.interp(fc, f, fase)),
                           float(np.interp(fc, f, coerencia))))
        (f1, m1, p1, c1), (f2, m2, p2, c2) = pontos
        resumo = self.tr("Cursores: {} → {} · |H| {} → {} dB (Δ {} dB) · fase {}° → {}° · γ² {} → {}").format(
            formatar_si(f1, "Hz", 5), formatar_si(f2, "Hz", 5), _numero(m1, 2), _numero(m2, 2), _numero(m2 - m1, 2),
            _numero(p1, 1), _numero(p2, 1), _numero(c1, 3), _numero(c2, 3))
        planilha = "\t".join(["f (Hz)", "|H| (dB)", "fase (°)", "γ²"]) + "\n" + "".join(
            "\t".join(numero_para_planilha(v) for v in ponto) + "\n" for ponto in pontos)
        return MedidasDaVista(resumo, planilha=planilha)

    def _descricao(self) -> list[str]:
        r = self.resultado
        if r is None:
            return []
        coerencia = r.coerencia[1:]
        return [self.tr("{} médias de {} amostras (Hann, 50 %) · resolução {} · a faixa: o intervalo de confiança de "
                        "95 % de H₁ (Bendat e Piersol), com o ruído na saída").format(
                            r.medias, r.amostras_por_segmento, formatar_si(r.frequencias[1], "Hz", 4)),
                self.tr("coerência média {}").format(_numero(float(np.mean(coerencia)), 3) if len(coerencia) else "—")]
