"""A vista Instrumento (F7.9, AN-08 e AN-06; docs/gui-progress.md, 4h): os traços da vista de tempo como num
osciloscópio, sobrepostos no disparo de um deles. As contas são as de ``dados/instrumento.py``.

* **A tela** tem 10 divisões de tempo e 8 de valor; cada traço tem a escala por divisão e o offset dele (a
  automática: a série 1-2-5 que põe os ciclos na tela), e o disparo fica em ``posicao_do_disparo`` da largura.
* **O disparo**: o traço, a borda (subindo ou descendo), o nível e a histerese (o gatilho de Schmitt).
* **A persistência** (o "fósforo"): cada traço na cor dele, mais forte onde mais amostras passaram (a contagem em
  escala logarítmica); **o ciclo médio** por cima, e a tabela das medidas dele e do disparo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
import supraharmonicos.api as api
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QSplitter, QVBoxLayout

from ...componentes.basicos import CampoComUnidade, Segmentado
from ...componentes.numeros import formatar_si
from ...dados import espectros as esp
from ...dados import instrumento as ins
from ...dados.qualidade import ler
from ...graficos.faixa import EixoDoTema
from ...tema.aplicar import aparencia
from ...tema.tokens import cor_do_traco
from .vistas_de_analise import _numero, _preencher, _tabela
from .vistas_de_mapa import VistaLigada

DIVISOES_DE_TEMPO = 10
DIVISOES_DE_VALOR = 8
COLUNAS_DA_PERSISTENCIA = 500
LINHAS_DA_PERSISTENCIA = 256
MAXIMO_DE_CICLOS = 2000
HISTERESE_AUTOMATICA = 0.02          # da faixa do traço de disparo
AMOSTRAS_DA_ESCALA = 1 << 20         # o começo do trecho: a faixa e o período para as escalas automáticas


@dataclass(frozen=True)
class CanalDoInstrumento:
    nome: str
    cor: object                 # a cor da receita do traço (a do tema sai na hora de desenhar)
    unidade: str
    por_divisao: float
    offset: float
    ciclo: ins.CicloMedio
    persistencia: ins.Densidade | None


@dataclass(frozen=True)
class ResultadoDoInstrumento:
    disparo: ins.Disparo
    tempo_por_divisao: float
    antes_s: float
    depois_s: float
    histerese: float
    canais: list[CanalDoInstrumento]


class VistaDeInstrumento(VistaLigada):
    nome_da_conta = "Instrumento"

    def _montar_conteudo(self, coluna: QVBoxLayout) -> None:
        self.setObjectName("vista_instrumento")
        self.seletor.setToolTip(self.tr("O traço de disparo"))
        self.borda = Segmentado([self.tr("↑ Subindo"), self.tr("↓ Descendo")])
        self.borda.setToolTip(self.tr("A borda do disparo"))
        self.borda.escolhaMudou.connect(lambda i: self._mudar(borda=esp.BORDAS_DO_DISPARO[i]))
        self.nivel = CampoComUnidade("", 0.0, digitos=5)
        self.nivel.setObjectName("nivel_do_disparo")
        self.nivel.setMaximumWidth(100)
        self.nivel.setToolTip(self.tr("O nível do disparo, na unidade do traço de disparo"))
        self.nivel.valorMudou.connect(lambda v: self._mudar(nivel=float(v)))
        self.tempo_por_divisao = CampoComUnidade("s/div", 0.0, minimo=0.0, maximo=3600.0, digitos=4)
        self.tempo_por_divisao.setObjectName("tempo_por_divisao")
        self.tempo_por_divisao.setMaximumWidth(110)
        self.tempo_por_divisao.setToolTip(self.tr("O tempo por divisão (10 na tela); vazio ou 0: dois ciclos do "
                                                  "disparo"))
        self.tempo_por_divisao.valorMudou.connect(lambda v: self._mudar(tempo_por_divisao=float(v)))
        self.persistencia = QCheckBox(self.tr("Persistência"))
        self.persistencia.setObjectName("persistencia")
        self.persistencia.setToolTip(self.tr("O \"fósforo\": cada traço mais forte onde mais amostras dos ciclos "
                                             "passaram (escala logarítmica)"))
        self.persistencia.toggled.connect(lambda v: self._mudar(persistencia=bool(v)))
        self.traco_da_escala = QComboBox()
        self.traco_da_escala.setObjectName("traco_da_escala")
        self.traco_da_escala.setToolTip(self.tr("O traço cuja escala por divisão e offset os campos ao lado mudam"))
        self.traco_da_escala.currentIndexChanged.connect(lambda _: self._mostrar_a_escala())
        self.por_divisao = CampoComUnidade("/div", 0.0, minimo=0.0, maximo=1e12, digitos=4)
        self.por_divisao.setObjectName("escala_por_divisao")
        self.por_divisao.setMaximumWidth(110)
        self.por_divisao.setToolTip(self.tr("A escala por divisão (8 na tela); vazio ou 0: a automática"))
        self.por_divisao.valorMudou.connect(lambda v: self._mudar_a_escala(por_divisao=float(v)))
        self.offset = CampoComUnidade("", 0.0, digitos=5)
        self.offset.setObjectName("offset_do_traco")
        self.offset.setMaximumWidth(100)
        self.offset.setToolTip(self.tr("O valor no centro da tela"))
        self.offset.valorMudou.connect(lambda v: self._mudar_a_escala(offset=float(v)))
        for w in (self.borda, QLabel(self.tr("Nível")), self.nivel, self.tempo_por_divisao, self.persistencia,
                  QLabel(self.tr("Escala de")), self.traco_da_escala, self.por_divisao, QLabel(self.tr("offset")),
                  self.offset):
            self._linha.addWidget(w)
        self.grafico = pg.PlotWidget(axisItems={"bottom": EixoDoTema("bottom"), "left": EixoDoTema("left")})
        self.grafico.setObjectName("tela_do_instrumento")
        self.grafico.setMenuEnabled(False)
        self.grafico.hideButtons()
        self.grafico.getViewBox().setMouseEnabled(x=False, y=False)
        self.grafico.setLabel("bottom", self.tr("tempo desde o disparo"), units="s")
        self.grafico.setLabel("left", self.tr("divisões"))
        self.grafico.getAxis("left").setTicks([[(k, str(k)) for k in range(-4, 5)]])
        self._itens: list = []
        self.tabela = _tabela("tabela_instrumento", 6)
        divisor = QSplitter(Qt.Orientation.Vertical)
        divisor.addWidget(self.grafico)
        divisor.addWidget(self.tabela)
        divisor.setSizes([460, 150])
        coluna.addWidget(divisor, 1)

    # ------------------------------------------------------------------ as opções

    def _mostrar_opcoes_proprias(self) -> None:
        o = self.opcoes
        self.borda.blockSignals(True)
        self.borda.escolher(esp.BORDAS_DO_DISPARO.index(o.borda))
        self.borda.blockSignals(False)
        self.nivel.definir_valor(o.nivel)
        if o.tempo_por_divisao > 0:
            self.tempo_por_divisao.definir_valor(o.tempo_por_divisao)
        else:
            self.tempo_por_divisao.definir_varios(self.tr("automático"))
        self.persistencia.blockSignals(True)
        self.persistencia.setChecked(o.persistencia)
        self.persistencia.blockSignals(False)
        self._mostrar_a_escala()

    def _mostrar_a_escala(self) -> None:
        posicao = max(self.traco_da_escala.currentIndex(), 0)
        unidades = getattr(self, "_unidades", [])
        unidade = unidades[posicao] if posicao < len(unidades) else ""
        self.por_divisao.unidade, self.offset.unidade = f"{unidade}/div", unidade
        if self.opcoes.traco < len(unidades):
            self.nivel.unidade = unidades[self.opcoes.traco]
        por_divisao, offset = self.opcoes.escala(posicao)
        if por_divisao > 0:
            self.por_divisao.definir_valor(por_divisao)
        else:
            self.por_divisao.definir_varios(self.tr("automática"))
        self.offset.definir_valor(offset)

    def _mudar_a_escala(self, **mudanca) -> None:
        posicao = max(self.traco_da_escala.currentIndex(), 0)
        por_divisao, offset = self.opcoes.escala(posicao)
        por_divisao, offset = mudanca.get("por_divisao", por_divisao), mudanca.get("offset", offset)
        self._mudar(escalas=self.opcoes.com_escala(posicao, por_divisao, offset).escalas)

    # ------------------------------------------------------------------ a conta

    def _extras(self, tempo, tracos, traco, inicio, fim):
        """Todos os traços da vista de tempo, cada um com o canal inteiro (as janelas são em volta dos disparos) e o
        deslocamento no tempo dele em relação ao de disparo."""
        atual = self.traco_da_escala.currentIndex()
        self.traco_da_escala.blockSignals(True)
        self.traco_da_escala.clear()
        for t in tracos:
            self.traco_da_escala.addItem(t.nome)
        self.traco_da_escala.setCurrentIndex(min(max(atual, 0), len(tracos) - 1))
        self.traco_da_escala.blockSignals(False)
        self._unidades = []
        for t in tracos:
            try:
                self._unidades.append(t.receita.unidade_de(
                    self.projeto.fonte(t.receita.fonte).canal(t.receita.canal).unidade))
            except KeyError:
                self._unidades.append("")
        self._mostrar_a_escala()
        self.nivel.definir_valor(self.opcoes.nivel)
        lista, chave = [], []
        for t in tracos:
            r = t.receita
            try:
                fonte = self.projeto.fonte(r.fonte)
            except KeyError:
                continue
            if fonte.esta_ausente:
                continue
            canal = fonte.canal(r.canal)
            estado = self.materializacoes.estado_de(t)
            pronta = estado.pronta.amostras if estado is not None and estado.pronta is not None else None
            trecho = esp.TrechoDoTraco(fonte.fonte.captura, r.canal, r.cadeia,
                                       self.materializacoes.contexto(fonte, r.canal), 0, len(canal.amostras),
                                       r.ganho, pronta, r.offset)
            unidade = r.unidade_de(canal.unidade)
            lista.append((t.nome, r.cor, unidade, trecho, traco.receita.deslocamento_s - r.deslocamento_s))
            chave.append((id(t), r.fonte, r.canal, r.cadeia, r.ganho, r.offset, r.deslocamento_s, pronta is not None))
        return tuple(chave), lista

    def _conta_com(self, trecho, extra, progresso, cancelado):
        o = self.opcoes
        taxa = trecho.captura.canal(trecho.numero).taxa_hz
        amostra = ler(trecho, trecho.inicio, min(trecho.fim, trecho.inicio + AMOSTRAS_DA_ESCALA))
        if len(amostra) < 4:
            raise api.ErroSHAN("o trecho é curto demais para o Instrumento")
        histerese = o.histerese or HISTERESE_AUTOMATICA * float(np.ptp(amostra))
        tempo_por_divisao = o.tempo_por_divisao
        if not tempo_por_divisao > 0:
            primeiros = ins.disparos(amostra, o.nivel, o.borda, histerese)
            periodo = float(np.median(np.diff(primeiros))) / taxa if len(primeiros) > 2 else len(amostra) / taxa / 2
            tempo_por_divisao = ins.passo_125(2 * periodo / DIVISOES_DE_TEMPO)
        largura = DIVISOES_DE_TEMPO * tempo_por_divisao
        antes, depois = o.posicao_do_disparo * largura, (1 - o.posicao_do_disparo) * largura
        disparo = ins.disparos_do_trecho(trecho, o.nivel, o.borda, histerese, antes, depois,
                                         maximo=MAXIMO_DE_CICLOS, cancelado=cancelado)
        if disparo.n == 0:
            raise api.ErroSHAN(f"nenhum disparo: o traço de disparo não cruza {o.nivel:g} na borda "
                               f"{o.borda} (com a histerese de {histerese:.3g}) com a janela inteira no trecho")
        canais = []
        for k, (nome, cor, unidade, trecho_k, deslocamento) in enumerate(extra):
            ciclo = ins.ciclo_medio(trecho_k, disparo, antes, depois, deslocamento_s=deslocamento,
                                    cancelado=cancelado)
            por_divisao, offset = o.escala(k)
            if not por_divisao > 0:
                alcance = max(abs(ciclo.maximo - offset), abs(ciclo.minimo - offset))
                por_divisao = ins.passo_125(alcance / (DIVISOES_DE_VALOR / 2)) if math.isfinite(alcance) else 1.0
            meia = DIVISOES_DE_VALOR / 2 * por_divisao
            persistencia = None
            if o.persistencia:
                persistencia = ins.densidade(trecho_k, disparo, antes, depois, (offset - meia, offset + meia),
                                             colunas=COLUNAS_DA_PERSISTENCIA, linhas=LINHAS_DA_PERSISTENCIA,
                                             deslocamento_s=deslocamento, cancelado=cancelado)
            canais.append(CanalDoInstrumento(nome, cor, unidade, por_divisao, offset, ciclo, persistencia))
            if progresso is not None:
                progresso((k + 1) / len(extra))
        return ResultadoDoInstrumento(disparo, tempo_por_divisao, antes, depois, histerese, canais)

    # ------------------------------------------------------------------ o desenho

    def _desenhar(self) -> None:
        for item in self._itens:
            self.grafico.removeItem(item)
        self._itens = []
        r = self.resultado
        if r is None:
            self.tabela.setRowCount(0)
            return
        t = aparencia().tema
        grade = pg.mkPen(QColor(t.borda_forte), width=1, style=Qt.PenStyle.DotLine)
        for k in range(1, DIVISOES_DE_TEMPO):
            linha = pg.InfiniteLine(-r.antes_s + k * r.tempo_por_divisao, angle=90, pen=grade)
            self._itens.append(linha)
        for k in range(-3, 4):
            self._itens.append(pg.InfiniteLine(k, angle=0, pen=grade))
        self._itens.append(pg.InfiniteLine(0.0, angle=90, pen=pg.mkPen(QColor(t.texto2), width=1,
                                                                        style=Qt.PenStyle.DashLine)))
        for canal in r.canais:
            cor = QColor(cor_do_traco(canal.cor, t)[0])
            if canal.persistencia is not None and canal.persistencia.amostras:
                self._itens.append(self._fosforo(canal, cor, r))
            y = (canal.ciclo.media - canal.offset) / canal.por_divisao
            self._itens.append(pg.PlotDataItem(canal.ciclo.tempos_s, np.clip(y, -6, 6),
                                               pen=pg.mkPen(cor, width=1.5)))
        for item in self._itens:
            self.grafico.addItem(item)
        self.grafico.setXRange(-r.antes_s, r.depois_s, padding=0)
        self.grafico.setYRange(-DIVISOES_DE_VALOR / 2, DIVISOES_DE_VALOR / 2, padding=0)
        self._preencher_a_tabela(r)

    def _fosforo(self, canal: CanalDoInstrumento, cor: QColor, r: ResultadoDoInstrumento) -> pg.ImageItem:
        """A persistência na cor do traço: a opacidade é o logaritmo da contagem (as células vazias, transparentes)."""
        contagens = canal.persistencia.contagens.astype(np.float64)
        alfa = np.log1p(contagens) / max(np.log1p(contagens.max()), 1e-12)
        rgba = np.zeros(contagens.shape + (4,), dtype=np.uint8)
        rgba[..., 0], rgba[..., 1], rgba[..., 2] = cor.red(), cor.green(), cor.blue()
        rgba[..., 3] = np.round(220 * alfa).astype(np.uint8)
        imagem = pg.ImageItem(rgba, axisOrder="col-major")
        imagem.setRect(QRectF(-r.antes_s, -DIVISOES_DE_VALOR / 2, r.antes_s + r.depois_s, DIVISOES_DE_VALOR))
        return imagem

    def _preencher_a_tabela(self, r: ResultadoDoInstrumento) -> None:
        self.tabela.setHorizontalHeaderLabels([self.tr("Traço"), self.tr("Escala"), "RMS", self.tr("Pico a pico"),
                                               self.tr("Média"), self.tr("Ciclos")])
        linhas = []
        for c in r.canais:
            u = c.unidade
            linhas.append((c.nome, formatar_si(c.por_divisao, f"{u}/div", 3), formatar_si(c.ciclo.rms, u, 5),
                           formatar_si(c.ciclo.pico_a_pico, u, 5), formatar_si(c.ciclo.valor_medio, u, 5),
                           str(c.ciclo.ciclos)))
        d = r.disparo
        periodo = d.periodo_s
        linhas.append((self.tr("Disparo"), formatar_si(r.tempo_por_divisao, "s/div", 3),
                       formatar_si(1 / periodo, "Hz", 7) if periodo > 0 else "—",
                       self.tr("período {}").format(formatar_si(periodo, "s", 6)),
                       self.tr("desvio {}").format(formatar_si(d.desvio_do_periodo_s, "s", 3)), str(d.n)))
        _preencher(self.tabela, linhas)

    def _descricao(self) -> list[str]:
        r = self.resultado
        if r is None:
            return []
        partes = [self.tr("{} disparos · {} · histerese {}").format(
            r.disparo.n, formatar_si(r.tempo_por_divisao, "s/div", 3), _numero(r.histerese, 4))]
        partes += [self.tr("{}: {}, offset {}").format(c.nome, formatar_si(c.por_divisao, f"{c.unidade}/div", 3),
                                                       formatar_si(c.offset, c.unidade, 4)) for c in r.canais]
        if r.disparo.n >= MAXIMO_DE_CICLOS:
            partes.append(self.tr("os primeiros {} ciclos").format(MAXIMO_DE_CICLOS))
        return partes
