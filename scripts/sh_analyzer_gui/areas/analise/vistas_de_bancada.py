"""As métricas de bancada e o assistente de aliasing (F7.8; docs/gui-progress.md, 4h). As contas são as de
``dados/bancada.py`` (as do ``medir_captura`` e do ``aliasing``).

* **A vista Métricas de bancada** (``VistaDeMetricas``): os cartões (o tom, a amplitude, o THD, o SINAD, o SNR, o
  ENOB, o SFDR, o ruído, a densidade, o jitter, o salto de fase, a saturação), cada um com o que quer dizer na dica;
  o gráfico dos harmônicos em dBc (os dobrados pela Nyquist vazados); a tabela de tudo, que copia para a planilha.
* **O assistente de aliasing** (``DialogoDeAliasing``): de duas a quatro fontes abertas do mesmo sinal em taxas
  diferentes, o canal e os parâmetros da CLI; a tabela dos componentes (real, imagem com a entrada, ambíguo).
"""

from __future__ import annotations

import math
import re

import pyqtgraph as pg
import supraharmonicos.api as api
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from ...ajuda import botao_de_ajuda
from ...componentes.basicos import CampoComUnidade, CartaoDeMedida
from ...componentes.fluxo import LayoutDeFluxo
from ...componentes.numeros import decimal, formatar_si
from ...dados import bancada as bc
from ...graficos.faixa import EixoDoTema
from ...tema.aplicar import aparencia
from ...tema.tokens import cor_do_traco
from .medidas import MedidasDaVista
from .vistas_de_analise import _numero, _preencher, _tabela, texto_da_tabela
from .vistas_de_mapa import VistaLigada

CARTOES = (
    ("tom", "Tom", "A frequência da fundamental: o maior pico da FFT (Kaiser β = 14), interpolado"),
    ("amplitude", "Amplitude", "A amplitude de pico do tom"),
    ("thd", "THD", "A distorção harmônica total: a soma dos harmônicos sobre a fundamental (dBc)"),
    ("sinad", "SINAD", "O tom sobre tudo o mais (o ruído e os harmônicos), em dB"),
    ("snr", "SNR", "O tom sobre o ruído, sem os harmônicos, em dB"),
    ("enob", "ENOB", "Os bits efetivos, (SINAD − 1,76) ÷ 6,02, corrigidos pela amplitude do tom em relação ao fundo "
                     "de escala do ADC"),
    ("sfdr", "SFDR", "A faixa dinâmica livre de espúrios: o tom sobre o maior espúrio (dBc)"),
    ("ruido", "Ruído", "O ruído RMS sem o tom e os harmônicos, em LSB do ADC (o de quantização ideal é 0,29 LSB)"),
    ("densidade", "Densidade do ruído", "A densidade espectral do ruído (a mediana do espectro), por √Hz"),
    ("jitter", "Jitter", "O jitter da amostragem: a parte do ruído que cresce com a inclinação do tom (precisa do tom "
                         "30 dB acima do ruído)"),
    ("salto", "Salto de fase", "O maior salto de fase do tom entre segmentos, em amostras: perto de 1, uma amostra "
                               "perdida ou duplicada pela PRU ou pelo disco"),
    ("saturacao", "Saturação", "A fração das amostras no código mínimo ou máximo do ADC (só sem cadeia)"),
)


class VistaDeMetricas(VistaLigada):
    """As métricas de bancada de um traço (ME-05), ligadas à vista de tempo como as outras análises."""

    nome_da_conta = "Métricas de bancada"
    unidade_x = ""

    def _montar_conteudo(self, coluna: QVBoxLayout) -> None:
        self.setObjectName("vista_metricas")
        rotulo = QLabel(self.tr("Harmônicos"))
        self.harmonicos = QSpinBox()
        self.harmonicos.setObjectName("harmonicos_das_metricas")
        self.harmonicos.setRange(2, 50)
        self.harmonicos.setKeyboardTracking(False)
        self.harmonicos.setToolTip(self.tr("Quantos harmônicos entram no THD (o --harmonicos do medir_captura)"))
        self.harmonicos.valueChanged.connect(lambda v: self._mudar(harmonicos=int(v)))
        self._linha.addWidget(rotulo)
        self._linha.addWidget(self.harmonicos)
        painel = QWidget()
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        rolagem.setWidget(painel)
        self._fluxo = LayoutDeFluxo(painel, espaco=8)
        self._fluxo.setContentsMargins(8, 6, 8, 6)
        self.cartoes: dict[str, CartaoDeMedida] = {}
        for chave, nome, dica in CARTOES:
            cartao = CartaoDeMedida(self.tr(nome), digitos=7 if chave == "tom" else 4)
            cartao.setObjectName(f"cartao_{chave}")
            cartao.setToolTip(self.tr(dica))
            cartao.setMinimumWidth(130)
            self.cartoes[chave] = cartao
            self._fluxo.addWidget(cartao)
        self.grafico = pg.PlotWidget(axisItems={"bottom": EixoDoTema("bottom"), "left": EixoDoTema("left")})
        self.grafico.setObjectName("grafico_harmonicos_da_bancada")
        self.grafico.setMenuEnabled(False)
        self.grafico.hideButtons()
        self.grafico.showGrid(x=False, y=True, alpha=0.15)
        self.grafico.setLabel("bottom", self.tr("ordem do harmônico"))
        self.grafico.setLabel("left", self.tr("nível (dBc)"))
        self._barras: list = []
        self.tabela = _tabela("tabela_metricas", 3)
        baixo = QSplitter(Qt.Orientation.Horizontal)
        baixo.addWidget(self.grafico)
        baixo.addWidget(self.tabela)
        baixo.setSizes([520, 420])
        divisor = QSplitter(Qt.Orientation.Vertical)
        divisor.addWidget(rolagem)
        divisor.addWidget(baixo)
        divisor.setSizes([210, 400])
        coluna.addWidget(divisor, 1)

    def _mostrar_opcoes_proprias(self) -> None:
        self.harmonicos.blockSignals(True)
        self.harmonicos.setValue(self.opcoes.harmonicos)
        self.harmonicos.blockSignals(False)

    def _conta(self, trecho, progresso, cancelado):
        return bc.medir(trecho, harmonicos=self.opcoes.harmonicos, cancelado=cancelado)

    def _desenhar(self) -> None:
        for item in self._barras:
            self.grafico.removeItem(item)
        self._barras = []
        m = self.resultado
        if m is None:
            for cartao in self.cartoes.values():
                cartao.definir(math.nan)
            self.tabela.setRowCount(0)
            return
        unidade = self.traco_unidade()
        e = m.espectro
        valores = {
            "tom": (e.freq_tom_hz if e.tem_tom else math.nan, "Hz"),
            "amplitude": (e.amplitude_pico if e.tem_tom else math.nan, unidade),
            "thd": (e.thd_db if e.tem_tom and math.isfinite(e.thd_db) else math.nan, "dB"),
            "sinad": (e.sinad_db, "dB"), "snr": (e.snr_db, "dB"), "enob": (e.enob_bits, "bits"),
            "sfdr": (e.sfdr_dbc, "dBc"), "ruido": (e.ruido_rms / m.lsb if m.lsb > 0 else math.nan, "LSB"),
            "densidade": (e.densidade_ruido, f"{unidade}/√Hz"),
            "jitter": (m.jitter.rms_ns * 1e-9 if m.jitter is not None else math.nan, "s"),
            "salto": (m.continuidade.salto_max_amostras if m.continuidade is not None else math.nan,
                      self.tr("amostra")),
            "saturacao": (100 * m.saturacao, "%"),
        }
        for chave, (valor, u) in valores.items():
            self.cartoes[chave].definir(valor, u, com_prefixo=chave in ("tom", "amplitude", "densidade", "jitter"))
        t = aparencia().tema
        cor = QColor(cor_do_traco(self.traco.receita.cor, t)[0])
        self._desenhar_os_harmonicos(e, cor)
        self.tabela.setHorizontalHeaderLabels([self.tr("Grandeza"), self.tr("Valor"), self.tr("O que é")])
        _preencher(self.tabela, self._linhas(m, unidade))

    def _desenhar_os_harmonicos(self, e, cor: QColor) -> None:
        """Os harmônicos de 2 até o pedido, em dBc: as barras cheias; os dobrados pela Nyquist, vazadas; os abaixo do
        piso do ruído, um traço no piso (estão lá, mas não se medem)."""
        separaveis = [h for h in e.harmonicos if h.nivel_dbc is not None and math.isfinite(h.nivel_dbc)]
        niveis = [h.nivel_dbc for h in separaveis]
        piso = (min(niveis) if niveis else -100.0) - 20.0
        for dobrados in (False, True):
            grupo = [h for h in separaveis if h.aliasado == dobrados]
            if grupo:
                barras = pg.BarGraphItem(x=[h.ordem for h in grupo], height=[h.nivel_dbc - piso for h in grupo],
                                         y0=piso, width=0.6, brush=None if dobrados else pg.mkBrush(cor),
                                         pen=pg.mkPen(cor, width=1.5))
                self.grafico.addItem(barras)
                self._barras.append(barras)
        abaixo = [h.ordem for h in e.harmonicos if h.nivel_dbc is not None and not math.isfinite(h.nivel_dbc)]
        if abaixo:
            marcas = pg.ScatterPlotItem(abaixo, [piso] * len(abaixo), symbol="_", size=14,
                                        pen=pg.mkPen(QColor(aparencia().tema.mudo), width=2))
            self.grafico.addItem(marcas)
            self._barras.append(marcas)
        ordens = [h.ordem for h in e.harmonicos] or [2]
        self.grafico.getAxis("bottom").setTicks([[(k, str(k)) for k in ordens]])
        self.grafico.setXRange(min(ordens) - 0.6, max(ordens) + 0.6, padding=0)
        self.grafico.setYRange(piso, max(niveis) + 10.0 if niveis else piso + 40.0, padding=0)

    def _linhas(self, m: bc.MetricasDeBancada, unidade: str) -> list[tuple[str, str, str]]:
        e, b = m.espectro, m.basicas
        linhas = [
            (self.tr("Amostras"), str(m.n_amostras), self.tr("a partir da amostra {} ({})").format(
                m.inicio, formatar_si(m.n_amostras / m.taxa_hz, "s", 4))),
            (self.tr("Média (DC)"), formatar_si(b.media, unidade, 6), ""),
            (self.tr("RMS CA"), formatar_si(b.rms_ac, unidade, 6), self.tr("{} LSB").format(_numero(b.rms_ac_lsb, 2))),
            (self.tr("Pico a pico"), formatar_si(b.pico_a_pico, unidade, 6), ""),
            ("LSB", formatar_si(m.lsb, unidade, 4), self.tr("o fundo de escala de {} ÷ 65 536").format(
                formatar_si(m.fundo_de_escala, unidade, 4))),
            (self.tr("Resolução da FFT"), formatar_si(e.resolucao_hz, "Hz", 4), self.tr("Kaiser β = 14, uma FFT")),
        ]
        dicas = {chave: self.tr(dica) for chave, _nome, dica in CARTOES}
        for chave, nome, _dica in CARTOES:
            cartao = self.cartoes[chave]
            linhas.append((self.tr(nome), cartao.texto, dicas[chave]))
        if e.tem_tom and math.isfinite(e.freq_espurio_hz):
            ordem = self.tr(" (o harmônico {})").format(e.ordem_espurio) if e.ordem_espurio else ""
            linhas.append((self.tr("Maior espúrio"), formatar_si(e.freq_espurio_hz, "Hz", 6),
                           self.tr("{} dB acima do piso{}").format(_numero(e.espurio_sobre_piso_db, 1), ordem)))
        for h in e.harmonicos:
            if h.nivel_dbc is None:
                valor = self.tr("não separável")
            elif not math.isfinite(h.nivel_dbc):
                valor = self.tr("abaixo do piso")
            else:
                valor = _numero(h.nivel_dbc, 1) + " dBc"
            onde = formatar_si(h.freq_hz, "Hz", 5)
            linhas.append((f"H{h.ordem}", valor, self.tr("em {} (dobrado pela Nyquist)").format(onde) if h.aliasado
                           else self.tr("em {}").format(onde)))
        c = m.continuidade
        if c is not None:
            linhas.append((self.tr("Saltos acima do limite"), str(c.saltos_acima_do_limite),
                           self.tr("{} segmentos de {} amostras; a amplitude varia {} %").format(
                               c.segmentos, c.amostras_por_segmento, _numero(c.variacao_amplitude_pct, 3))))
        if m.trocas is not None and m.trocas.trocas:
            linhas.append((self.tr("Salto nas trocas de buffer"), _numero(m.trocas.salto_mediano_amostras, 3) + " " +
                           self.tr("amostra"), self.tr("a mediana em {} trocas").format(m.trocas.trocas)))
        for nome, d in ((self.tr("Degrau nas trocas"), m.degraus_trocas),
                        (self.tr("Degrau nos rebases"), m.degraus_rebases)):
            if d is not None and d.eventos_ns:
                linhas.append((nome, formatar_si(d.mediana_ns * 1e-9, "s", 3),
                               self.tr("o maior {} em {} posições").format(formatar_si(d.maior_ns * 1e-9, "s", 3),
                                                                            len(d.eventos_ns))))
        if m.jitter is not None:
            linhas.append((self.tr("Ruído onde o tom é plano"), formatar_si(m.jitter.ruido_plano, unidade, 4),
                           self.tr("o do ADC, sem o do jitter ({} LSB)").format(
                               _numero(m.jitter.ruido_plano / m.lsb, 2) if m.lsb > 0 else "—")))
        return linhas

    def texto(self) -> str:
        return texto_da_tabela(self.tabela)

    def _descricao(self) -> list[str]:
        m = self.resultado
        if m is None:
            return []
        partes = [self.tr("{} amostras ({}) · as contas do medir_captura").format(
            m.n_amostras, formatar_si(m.n_amostras / m.taxa_hz, "s", 4))]
        if not m.espectro.tem_tom:
            partes.append(self.tr("sem um tom: só o piso de ruído"))
        partes += [self.tr("⚠ {}").format(a) for a in m.avisos]
        return partes

    def medidas(self) -> MedidasDaVista | None:
        return None


# ------------------------------------------------------------------ o assistente de aliasing


class DialogoDeAliasing(QDialog):
    """O assistente de aliasing (ES-06): as fontes abertas, o canal e os parâmetros; o resultado numa tabela.

    ``fontes``: os ``FonteDoProjeto`` abertos; ``tarefas``: o serviço de tarefas da janela (a conta em segundo
    plano)."""

    def __init__(self, fontes, tarefas, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dialogo_aliasing")
        self.setWindowTitle(self.tr("Assistente de aliasing"))
        self.resize(860, 620)
        self.fontes, self.tarefas = [f for f in fontes if not f.esta_ausente], tarefas
        self.resultado: bc.ResultadoDoAliasing | None = None
        self._tarefa = None
        explicacao = QLabel(self.tr(
            "O único anti-aliasing da cadeia é o passa-baixa do ADS8688 (~15 kHz, 2ª ordem): um pico perto da Nyquist "
            "pode ser a imagem de uma entrada acima dela. Escolha <b>de duas a quatro capturas do mesmo sinal em taxas "
            "diferentes</b> (ex.: 400, 390,625 e 320 kS/s): um componente real fica no mesmo lugar em todas; uma "
            "imagem muda de lugar, e as posições dizem de onde ela veio."))
        explicacao.setWordWrap(True)
        self.lista = QListWidget()
        self.lista.setObjectName("capturas_do_aliasing")
        for fonte in self.fontes:
            canal = fonte.canais[0] if fonte.canais else None
            taxa = formatar_si(canal.taxa_hz, "S/s", 5) if canal is not None else "—"
            item = QListWidgetItem(f"{fonte.nome} · {taxa}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.lista.addItem(item)
        self.lista.itemChanged.connect(lambda _: self._refazer_os_canais())
        self.lista.setMaximumHeight(140)
        self.canal = QComboBox()
        self.canal.setObjectName("canal_do_aliasing")
        p = bc.ParametrosDoAliasing()
        self.campos = {
            "freq_min_hz": CampoComUnidade("Hz", p.freq_min_hz, minimo=0.0, maximo=1e7),
            "acima_do_piso_db": CampoComUnidade("dB", p.acima_do_piso_db, minimo=0.0, maximo=200.0),
            "resolucao_hz": CampoComUnidade("Hz", p.resolucao_hz, minimo=0.1, maximo=1e5),
            "tolerancia_hz": CampoComUnidade("Hz", p.tolerancia_hz, minimo=0.0, maximo=1e5),
            "tolerancia_db": CampoComUnidade("dB", p.tolerancia_db, minimo=0.0, maximo=100.0),
        }
        for nome, campo in self.campos.items():
            campo.setObjectName(f"aliasing_{nome}")
        formulario = QFormLayout()
        formulario.addRow(self.tr("Canal"), self.canal)
        formulario.addRow(self.tr("A partir de"), self.campos["freq_min_hz"])
        formulario.addRow(self.tr("Picos acima do piso"), self.campos["acima_do_piso_db"])
        formulario.addRow(self.tr("Resolução do Welch"), self.campos["resolucao_hz"])
        formulario.addRow(self.tr("Tolerância em frequência"), self.campos["tolerancia_hz"])
        formulario.addRow(self.tr("Tolerância em amplitude"), self.campos["tolerancia_db"])
        self.analisar = QPushButton(self.tr("Analisar"))
        self.analisar.setObjectName("analisar_aliasing")
        self.analisar.setDefault(True)
        self.analisar.clicked.connect(self.medir)
        self.resumo = QLabel()
        self.resumo.setObjectName("resumo_do_aliasing")
        self.resumo.setWordWrap(True)
        self.resumo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.tabela = _tabela("tabela_aliasing", 2)
        self.tabela.horizontalHeader().setStretchLastSection(True)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botoes.rejected.connect(self.reject)
        botoes.addButton(botao_de_ajuda("aliasing"), QDialogButtonBox.ButtonRole.HelpRole)
        coluna = QVBoxLayout(self)
        coluna.addWidget(explicacao)
        coluna.addWidget(self.lista)
        coluna.addLayout(formulario)
        coluna.addWidget(self.analisar, 0, Qt.AlignmentFlag.AlignLeft)
        coluna.addWidget(self.resumo)
        coluna.addWidget(self.tabela, 1)
        coluna.addWidget(botoes)
        self._refazer_os_canais()

    def escolhidas(self) -> list:
        return [f for i, f in enumerate(self.fontes) if self.lista.item(i).checkState() == Qt.CheckState.Checked]

    def _refazer_os_canais(self) -> None:
        escolhidas = self.escolhidas() or self.fontes
        comuns = sorted(set.intersection(*(set(c.numero for c in f.canais) for f in escolhidas))) if escolhidas else []
        atual = self.canal.currentData()
        self.canal.clear()
        for n in comuns:
            self.canal.addItem(self.tr("canal {}").format(n), n)
        if atual in comuns:
            self.canal.setCurrentIndex(comuns.index(atual))
        n = len(self.escolhidas())
        self.analisar.setEnabled(2 <= n <= 4 and bool(comuns))
        self.analisar.setToolTip("" if self.analisar.isEnabled() else
                                 self.tr("Marque de duas a quatro capturas com um canal em comum"))

    def parametros(self) -> bc.ParametrosDoAliasing:
        return bc.ParametrosDoAliasing(**{nome: campo.valor for nome, campo in self.campos.items()})

    def medir(self):
        """A conta numa tarefa; devolve a tarefa."""
        if self._tarefa is not None and self._tarefa.ativa:
            self._tarefa.cancelar()
        canal = self.canal.currentData()
        capturas = [(f.fonte.captura, canal) for f in self.escolhidas()]
        parametros = self.parametros()
        self.resumo.setText(self.tr("Analisando…"))

        def trabalho(progresso, cancelado):
            try:
                return bc.aliasing(capturas, parametros, progresso=progresso, cancelado=cancelado)
            except api.ErroSHAN as e:
                return str(e)

        self._tarefa = self.tarefas.iniciar(self.tr("Aliasing"), trabalho, "aliasing", mostrar=True,
                                            ao_terminar=self._terminou)
        return self._tarefa

    def _terminou(self, tarefa) -> None:
        if tarefa is not self._tarefa or not isValid(self):
            return
        self._tarefa = None
        if tarefa.estado != "concluida":
            self.resumo.setText(tarefa.erro if tarefa.estado == "falhou" else "")
            return
        if isinstance(tarefa.resultado, str):
            self.resultado = None
            self.resumo.setText(tarefa.resultado)
            self.tabela.setRowCount(0)
            return
        self.resultado = tarefa.resultado
        self._mostrar(tarefa.resultado)

    def _mostrar(self, r: bc.ResultadoDoAliasing) -> None:
        n = len(r.taxas_hz)
        letras = [chr(ord("A") + k) for k in range(n)]
        colunas = [self.tr("Entrada")]
        for letra in letras:
            colunas += [self.tr("Em {}").format(letra), self.tr("{} ({})").format(letra, r.unidade)]
        colunas.append(self.tr("Diagnóstico"))
        self.tabela.setColumnCount(len(colunas))
        self.tabela.setHorizontalHeaderLabels(colunas)
        linhas = []
        for c in r.componentes:
            linha = [formatar_si(c.frequencia_entrada_hz, "Hz", 6) if c.frequencia_entrada_hz is not None else "—"]
            for pico in c.picos:
                linha += [formatar_si(pico.frequencia_hz, "Hz", 6) if pico is not None else "—",
                          _numero(pico.amplitude_db, 1) if pico is not None else "—"]
            linha.append(decimal_no_texto(c.diagnostico))
            linhas.append(tuple(linha))
        _preencher(self.tabela, linhas)
        partes = [self.tr("{} componente(s): {} real(is), {} com imagem em ao menos uma captura, {} sem par").format(
            len(r.componentes), r.reais, len(r.componentes) - r.reais - r.sem_par, r.sem_par)]
        partes.append(" · ".join(f"{letra}: {formatar_si(fs, 'S/s', 5)}, {k} pico(s), piso {_numero(piso, 1)}"
                                 for letra, fs, k, piso in zip(letras, r.taxas_hz, r.n_picos, r.pisos_db)))
        if r.ambiguas:
            partes.append(self.tr("Uma imagem cai no mesmo lugar em todas as taxas em: {}. Ali, uma taxa a mais "
                                  "decide.").format(", ".join(self.tr("{} (de {})").format(
                                      formatar_si(x, "Hz", 4), formatar_si(e, "Hz", 4)) for x, e in r.ambiguas)))
        self.resumo.setText("\n".join(partes))


def decimal_no_texto(texto: str) -> str:
    """O diagnóstico do motor (com números "12.34 kHz") com o separador decimal das configurações."""
    return re.sub(r"\d+\.\d+", lambda m: decimal(m.group(0)), texto)

