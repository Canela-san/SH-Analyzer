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
    QVBoxLayout,
)

from ...componentes.basicos import Segmentado
from ...componentes.numeros import decimal, formatar_si
from ...dados import analises as an
from ...dados import espectros as esp
from ...graficos.faixa import EixoDoTema
from ...tema.aplicar import aparencia
from ...tema.tokens import cor_do_traco
from .medidas import MedidasDaVista
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


# ------------------------------------------------------------------ o XY e a potência (F7.3)


class VistaDeXY(VistaLigada):
    nome_da_conta = "XY"
    unidade_x = ""

    def _montar_conteudo(self, coluna: QVBoxLayout) -> None:
        self.setObjectName("vista_xy")
        self.seletor.setToolTip(self.tr("O traço do eixo horizontal (a tensão, na potência)"))
        self.seletor_y = QComboBox()
        self.seletor_y.setObjectName("traco_y_da_vista")
        self.seletor_y.setToolTip(self.tr("O traço do eixo vertical (a corrente, na potência)"))
        self.seletor_y.activated.connect(lambda i: self._mudar(traco_y=int(self.seletor_y.itemData(i))))
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
            return ("taxa", indice), self.tr("os dois traços têm taxas diferentes ({} e {}): o XY precisa das mesmas "
                                             "amostras no tempo").format(formatar_si(meu.taxa_hz, "S/s", 5),
                                                                         formatar_si(canal.taxa_hz, "S/s", 5))
        # o mesmo instante: o deslocamento no tempo de cada traço vale
        passo = round((traco.receita.deslocamento_s - r.deslocamento_s) * canal.taxa_hz)
        a, b = inicio + passo, fim + passo
        n = len(canal.amostras)
        if a < 0 or b > n:
            a, b = max(a, 0), min(b, n)
        estado = self.materializacoes.estado_de(outro)
        pronta = estado.pronta.amostras if estado is not None and estado.pronta is not None else None
        trecho = esp.TrechoDoTraco(fonte.fonte.captura, r.canal, r.cadeia, self.materializacoes.contexto(fonte, r.canal),
                                   a, b, r.ganho, pronta, r.offset)
        self._traco_y = outro
        return (id(outro), r.fonte, r.canal, r.cadeia, r.ganho, r.offset, a, b, pronta is not None), trecho

    def _conta_com(self, trecho, extra, progresso, cancelado):
        if extra is None:
            raise api.ErroSHAN("o traço do eixo vertical não está mais no projeto")
        if isinstance(extra, str):
            raise api.ErroSHAN(extra)
        vx = an.valores_do_trecho(trecho, cancelado=cancelado)
        vy = an.valores_do_trecho(extra, cancelado=cancelado)
        m = min(len(vx), len(vy))
        taxa = trecho.captura.canal(trecho.numero).taxa_hz
        return an.xy(vx[:m], vy[:m], taxa, com_potencia=self.opcoes.potencia)

    def _desenhar(self) -> None:
        r = self.resultado
        if r is None:
            self.curva.setData([], [])
            self.densidade.clear()
            self.tabela.setRowCount(0)
            return
        t = aparencia().tema
        ux = self.traco_unidade()
        uy = self._traco_y.receita.unidade_de(self.projeto.fonte(self._traco_y.receita.fonte).canal(
            self._traco_y.receita.canal).unidade) if getattr(self, "_traco_y", None) is not None else ""
        self.grafico.setLabel("bottom", self.traco.nome, units=ux)
        self.grafico.setLabel("left", self._traco_y.nome if getattr(self, "_traco_y", None) else "", units=uy)
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
