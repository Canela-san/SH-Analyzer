"""A interface gráfica do SH-Analyzer (PyQt6): a análise do ``adc_tool`` numa janela.

A janela não tem análise própria. Os controles do painel da esquerda viram uma linha de comando do ``adc_tool``
(:meth:`PainelParametros.argv`), que passa pelo MESMO parser da CLI (``opcoes_analise.montar_parser``) e pelo mesmo
pipeline (``modos.analisar_captura``), numa thread à parte para a janela não travar. O resultado é desenhado nas
mesmas funções da CLI (``plotagem.desenhar_*``), em figuras do matplotlib embutidas, e as tabelas (harmônicos,
picos, bandas IEC) mostram o que o console da CLI imprimiria. O comando equivalente fica sempre à vista e pode ser
copiado: o que a janela mostra é reproduzível no terminal, flag por flag.

O que o pacote registra pelo ``logging`` (progresso, avisos) aparece na aba "Console" -- um handler liga o logger
``supraharmonicos`` a um sinal do Qt, que atravessa a thread da análise.

Camada de aplicação, acima de ``modos``. A borda (``QApplication``, argumentos, código de saída) é ``cli_gui``.

Depende de: ``cabecalho``, ``constantes``, ``contexto``, ``erros``, ``modos``, ``opcoes_analise``, ``plotagem``.
"""

from __future__ import annotations

import argparse
import logging
import shlex
import traceback
from collections.abc import Callable
from pathlib import Path

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PyQt6.QtCore import QObject, QSettings, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QGuiApplication, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from . import plotagem
from .cabecalho import CABECALHO_TAMANHO_TOTAL, CabecalhoArquivo, contar_amostras_arquivo_bin, ler_cabecalho
from .constantes import (
    CORTE_SUPRAHARMONICOS_PADRAO,
    DISTANCIA_MINIMA_PICOS_PADRAO,
    NOMES_GRANDEZA,
    ORDEM_FILTRO_MAXIMA,
    ORDEM_FILTRO_MINIMA,
    ORDEM_FILTRO_PADRAO,
    RESOLUCAO_WELCH_PADRAO,
    SOBREPOSICAO_WELCH_PADRAO,
)
from .contexto import anunciar_cabecalho, resolver_contexto
from .erros import ErroSHAN
from .modos import ResultadoAnalise, analisar_captura, executar_exportacao_hdf5, exportar_resultados
from .opcoes_analise import montar_parser, validar_flags_numericas

log = logging.getLogger(__name__)

NOME_APLICATIVO = "SH-Analyzer"
ICONE = Path(__file__).resolve().parents[2] / "docs" / "images" / "app-icon.svg"     # só existe no repositório
COMANDO_CLI = ("uv", "run", "scripts/adc_tool.py")
JANELAS = [("padrão de cada método", ""), ("retangular", "retangular"), ("Hann", "hann"),
           ("Blackman-Harris", "blackmanharris"), ("flat top", "flattop"), ("Kaiser", "kaiser")]
ANALISE_AUTOMATICA_ATE = 2 * 1_048_576     # amostras brutas: até 2 blocos, a captura aberta já é analisada
ALTURA_POR_CANAL_PX = 320                  # os gráficos de vários canais crescem e a aba rola
FILTROS_IMAGEM = "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)"


def _num(valor: float) -> str:
    return f"{valor:g}"


# ---------------------------------------------------------------------------
# O logging do pacote numa aba, atravessando a thread da análise
# ---------------------------------------------------------------------------

class _SinalLog(QObject):
    mensagem = pyqtSignal(int, str)


class _HandlerPainel(logging.Handler):
    """Cada registro vira um sinal do Qt: emitido da thread da análise, ele chega ao painel na thread da janela."""

    def __init__(self, sinal: _SinalLog):
        super().__init__(logging.INFO)
        self._sinal = sinal

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._sinal.mensagem.emit(record.levelno, record.getMessage())
        except Exception:  # noqa: BLE001 -- padrão do logging: nunca derrubar o programa por falha de log
            self.handleError(record)


class _Trabalhador(QThread):
    """Roda uma função fora da thread da janela e avisa o resultado (ou o erro) por sinal."""

    concluido = pyqtSignal(object)
    falhou = pyqtSignal(str)

    def __init__(self, funcao: Callable[[], object], parent=None):
        super().__init__(parent)
        self._funcao = funcao

    def run(self) -> None:
        try:
            self.concluido.emit(self._funcao())
        except ErroSHAN as e:
            self.falhou.emit(str(e))
        except Exception:  # noqa: BLE001 -- um bug não pode matar a janela em silêncio: vai ao console, com o traceback
            self.falhou.emit("erro inesperado (um bug: copie o texto abaixo ao relatar)\n\n" + traceback.format_exc())


# ---------------------------------------------------------------------------
# Peças da janela
# ---------------------------------------------------------------------------

class PainelFigura(QWidget):
    """Uma figura do matplotlib com a barra de navegação (zoom, arrasto, salvar), numa área que rola quando a figura
    pede mais altura do que a aba tem (vários canais separados)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.figura = Figure()
        self.tela = FigureCanvasQTAgg(self.figura)
        self._area = QScrollArea()
        self._area.setWidgetResizable(True)
        self._area.setWidget(self.tela)
        leiaute = QVBoxLayout(self)
        leiaute.setContentsMargins(0, 0, 0, 0)
        leiaute.addWidget(NavigationToolbar2QT(self.tela, self))
        leiaute.addWidget(self._area)
        self.limpar()

    def limpar(self) -> None:
        self.figura.clear()
        self.tela.setMinimumHeight(0)
        self.tela.draw_idle()

    def desenhar(self, altura_minima_px: int, desenho: Callable[[Figure], None]) -> None:
        """Limpa a figura, chama ``desenho(figura)`` e redesenha. O ``tight`` do matplotlib fica ligado para a figura
        se reorganizar quando a janela muda de tamanho."""
        self.figura.clear()
        self.tela.setMinimumHeight(altura_minima_px)
        desenho(self.figura)
        self.figura.set_layout_engine("tight")
        self.tela.draw_idle()


class Tabela(QTableWidget):
    """Uma tabela só de leitura, com as colunas numéricas alinhadas à direita."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.verticalHeader().setVisible(False)

    def preencher(self, colunas: list[str], linhas: list[list[object]]) -> None:
        self.clear()
        self.setColumnCount(len(colunas))
        self.setHorizontalHeaderLabels(colunas)
        self.setRowCount(len(linhas))
        for i, linha in enumerate(linhas):
            for j, valor in enumerate(linha):
                item = QTableWidgetItem(f"{valor:.6g}" if isinstance(valor, float) else str(valor))
                if isinstance(valor, (int, float)):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.setItem(i, j, item)


def _spin(minimo: float, maximo: float, valor: float, passo: float = 1, decimais: int = 0, sufixo: str = ""):
    w = QDoubleSpinBox() if decimais else QSpinBox()
    w.setRange(minimo, maximo)
    w.setSingleStep(passo)
    if decimais:
        w.setDecimals(decimais)
    w.setValue(valor)
    if sufixo:
        w.setSuffix(sufixo)
    w.setMaximumWidth(140)
    return w


def _grupo(titulo: str, marcavel: bool = False) -> tuple[QGroupBox, QFormLayout]:
    grupo = QGroupBox(titulo)
    grupo.setCheckable(marcavel)
    if marcavel:
        grupo.setChecked(False)
    return grupo, QFormLayout(grupo)


def _linha(*widgets) -> QWidget:
    caixa = QWidget()
    leiaute = QHBoxLayout(caixa)
    leiaute.setContentsMargins(0, 0, 0, 0)
    for w in widgets:
        leiaute.addWidget(w)
    leiaute.addStretch()
    return caixa


class PainelParametros(QWidget):
    """Os controles da análise. :meth:`argv` traduz o estado deles na linha de comando do ``adc_tool``; ``mudou``
    avisa a cada mudança (a janela atualiza o comando equivalente)."""

    mudou = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.caminho: Path | None = None
        self.cabecalho: CabecalhoArquivo | None = None
        self._caixas_canais: dict[int, QCheckBox] = {}
        self._montar()
        self._ligar_mudancas(self)

    # --- construção -------------------------------------------------------

    def _montar(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(4, 4, 4, 4)

        # A captura: o resumo do cabeçalho e, sem cabeçalho, o que a CLI exigiria (-f e --canais).
        grupo, form = _grupo("Captura")
        self.resumo = QLabel("Abra uma captura (.bin ou .csv): Arquivo > Abrir, ou arraste-a para a janela.")
        self.resumo.setWordWrap(True)
        self.resumo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(self.resumo)
        self.grupo_sem_cabecalho = QGroupBox("Sem cabeçalho: informe como na CLI")
        form_sc = QFormLayout(self.grupo_sem_cabecalho)
        self.frequencia = _spin(1, 10_000_000, 400_000, 1000, 3, " Hz")
        self.canais_texto = QLineEdit("1")
        self.canais_texto.setPlaceholderText("ex.: 0,1,3 (a ordem impressa pelo ler_adc)")
        form_sc.addRow("Taxa total (-f)", self.frequencia)
        form_sc.addRow("Canais (--canais)", self.canais_texto)
        self.grupo_sem_cabecalho.setVisible(False)
        form.addRow(self.grupo_sem_cabecalho)
        self.fs_pedida = QCheckBox("Analisar com a taxa pedida, não a que a PRU gera (--fs-pedida)")
        form.addRow(self.fs_pedida)
        raiz.addWidget(grupo)

        grupo, form = _grupo("Canais e trecho")
        self.caixa_canais = QWidget()
        self._leiaute_canais = QHBoxLayout(self.caixa_canais)
        self._leiaute_canais.setContentsMargins(0, 0, 0, 0)
        self._leiaute_canais.addStretch()          # as caixas dos canais entram antes dele (configurar_captura)
        form.addRow("Exibir", self.caixa_canais)
        self.layout_canais = QComboBox()
        self.layout_canais.addItems(["separados", "sobrepostos"])
        form.addRow("Layout (> 1 canal)", self.layout_canais)
        self.inicio = _spin(0, 2**31 - 1, 0, 1000)
        self.ate_o_fim = QCheckBox("até o fim")
        self.ate_o_fim.setChecked(True)
        self.fim = _spin(1, 2**31 - 1, 1_000_000, 1000)
        self.fim.setEnabled(False)
        self.ate_o_fim.toggled.connect(lambda marcado: self.fim.setEnabled(not marcado))
        form.addRow("Início (amostra bruta)", self.inicio)
        form.addRow("Fim (exclusive)", _linha(self.fim, self.ate_o_fim))
        self.duracao = QLabel("")
        form.addRow(self.duracao)
        raiz.addWidget(grupo)

        grupo, form = _grupo("Calibração e sonda")
        self.ganho = QLineEdit("1.0")
        self.ganho.setToolTip("Ganho do sensor/PCB: um valor, ou um por canal (ex.: 19.357,0.1).")
        self.faixa = QLineEdit()
        self.faixa.setPlaceholderText("a do cabeçalho (20.48, 10.24 ou 5.12 V)")
        self.offset = QLineEdit()
        self.offset.setPlaceholderText("automático (faixa/2)")
        self.formato = QComboBox()
        self.formato.addItems(["uint16", "int16"])
        self.grandeza = QLineEdit()
        self.grandeza.setPlaceholderText("a do cabeçalho (ex.: 0:tensao,1:corrente)")
        self.sondas_dir = QLineEdit()
        self.sondas_dir.setPlaceholderText("scripts/sondas/")
        botao_sondas = QPushButton("…")
        botao_sondas.setMaximumWidth(32)
        botao_sondas.clicked.connect(self._escolher_pasta_sondas)
        self.sonda_perfil = QLineEdit()
        self.sonda_perfil.setPlaceholderText("ex.: 1:scripts/sondas/outra.json")
        self.sem_correcao_sonda = QCheckBox("Sem a correção de sonda (só o ganho escalar)")
        form.addRow("Ganho (--ganho)", self.ganho)
        form.addRow("Faixa (--faixa)", self.faixa)
        form.addRow("Offset (--offset)", self.offset)
        form.addRow("Formato", self.formato)
        form.addRow("Grandeza (--grandeza)", self.grandeza)
        form.addRow("Pasta de perfis", _linha(self.sondas_dir, botao_sondas))
        form.addRow("Perfil por canal", self.sonda_perfil)
        form.addRow(self.sem_correcao_sonda)
        raiz.addWidget(grupo)

        grupo, form = _grupo("Filtros Butterworth (fase zero)")
        self.passa_alta = QCheckBox("Passa-alta")
        self.passa_alta_hz = _spin(0.001, 10_000_000, CORTE_SUPRAHARMONICOS_PADRAO, 100, 3, " Hz")
        self.passa_baixa = QCheckBox("Passa-baixa")
        self.passa_baixa_hz = _spin(0.001, 10_000_000, 45_000, 1000, 3, " Hz")
        self.ordem_filtro = _spin(ORDEM_FILTRO_MINIMA, ORDEM_FILTRO_MAXIMA, ORDEM_FILTRO_PADRAO)
        form.addRow(self.passa_alta, self.passa_alta_hz)
        form.addRow(self.passa_baixa, self.passa_baixa_hz)
        form.addRow("Ordem", self.ordem_filtro)
        raiz.addWidget(grupo)

        self.grupo_fft, form = _grupo("FFT sincronizada (fundamental e harmônicos)", marcavel=True)
        self.fft_ciclos = _spin(0, 1_000_000, 0)
        self.fft_ciclos.setSpecialValueText("todos")
        self.freq_min = _spin(0.1, 100_000, 45.0, 1, 2, " Hz")
        self.freq_max = _spin(0.1, 100_000, 65.0, 1, 2, " Hz")
        self.harmonicos = QCheckBox("Tabela de harmônicos até a ordem")
        self.harmonicos_n = _spin(1, 10_000, 40)
        form.addRow("Ciclos", self.fft_ciclos)
        form.addRow("Busca da fundamental", _linha(self.freq_min, QLabel("a"), self.freq_max))
        form.addRow(self.harmonicos, self.harmonicos_n)
        raiz.addWidget(self.grupo_fft)

        self.grupo_welch, form = _grupo("Welch (supraharmônicos)", marcavel=True)
        self.resolucao_welch = _spin(0.001, 1_000_000, RESOLUCAO_WELCH_PADRAO, 10, 3, " Hz")
        self.sobreposicao_welch = _spin(0.0, 0.99, SOBREPOSICAO_WELCH_PADRAO, 0.05, 2)
        self.espectrograma = QCheckBox("Espectrograma (o espectro ao longo do tempo)")
        form.addRow("Resolução", self.resolucao_welch)
        form.addRow("Sobreposição", self.sobreposicao_welch)
        form.addRow(self.espectrograma)
        raiz.addWidget(self.grupo_welch)

        grupo, form = _grupo("Espectro")
        self.janela = QComboBox()
        for nome, _ in JANELAS:
            self.janela.addItem(nome)
        self.kaiser_beta = _spin(0.0, 50.0, 8.6, 0.5, 2)
        self.modo_espectro = QComboBox()
        self.modo_espectro.addItems(["tom", "ruido"])
        self.agrupar_bandas = QCheckBox("Agrupar em bandas de")
        self.agrupar_bandas_hz = _spin(0.001, 1_000_000, 200.0, 50, 3, " Hz")
        self.picos = QCheckBox("Listar os picos acima de")
        self.picos_db = _spin(-300.0, 100.0, -60.0, 5, 1, " dB")
        self.picos_min = _spin(0.0, 10_000_000, CORTE_SUPRAHARMONICOS_PADRAO, 100, 3, " Hz")
        self.picos_max = _spin(0.0, 10_000_000, 0.0, 1000, 3, " Hz")
        self.picos_max.setSpecialValueText("Nyquist")
        self.picos_distancia = _spin(0.001, 1_000_000, DISTANCIA_MINIMA_PICOS_PADRAO, 10, 3, " Hz")
        form.addRow("Janela", self.janela)
        form.addRow("Beta (Kaiser)", self.kaiser_beta)
        form.addRow("Modo", self.modo_espectro)
        form.addRow(self.agrupar_bandas, self.agrupar_bandas_hz)
        form.addRow(self.picos, self.picos_db)
        form.addRow("  entre", _linha(self.picos_min, QLabel("e"), self.picos_max))
        form.addRow("  distância mínima", self.picos_distancia)
        raiz.addWidget(grupo)

        self.grupo_iec, form = _grupo("Bandas IEC 61000-4-7 (200 Hz)", marcavel=True)
        self.iec_min = _spin(0.0, 10_000_000, 2000.0, 100, 3, " Hz")
        self.iec_max = _spin(0.0, 10_000_000, 0.0, 1000, 3, " Hz")
        self.iec_max.setSpecialValueText("Nyquist")
        self.iec_sincronizar = QCheckBox("Janelas de 10/12 ciclos da fundamental (IEC 61000-4-30)")
        self.iec_agregar = QCheckBox("Agregar em 3 s e 10 min (IEC 61000-4-30)")
        form.addRow("De", _linha(self.iec_min, QLabel("a"), self.iec_max))
        form.addRow(self.iec_sincronizar)
        form.addRow(self.iec_agregar)
        raiz.addWidget(self.grupo_iec)

        grupo, form = _grupo("Forma de onda")
        self.simplificar = QCheckBox("Envoltória mín/máx (capturas longas; o zoom mostra as amostras)")
        self.max_pontos = _spin(0, 10_000_000, 0, 1000)
        self.max_pontos.setSpecialValueText("padrão")
        form.addRow(self.simplificar)
        form.addRow("Pontos da envoltória", self.max_pontos)
        raiz.addWidget(grupo)
        raiz.addStretch()

    def _ligar_mudancas(self, raiz: QWidget) -> None:
        for w in raiz.findChildren(QWidget):
            if isinstance(w, QCheckBox):
                w.toggled.connect(self._avisar)
            elif isinstance(w, QGroupBox) and w.isCheckable():
                w.toggled.connect(self._avisar)
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                w.valueChanged.connect(self._avisar)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._avisar)
            elif isinstance(w, QLineEdit):
                w.textChanged.connect(self._avisar)
        self.canais_texto.textChanged.connect(self._canais_digitados)

    def _avisar(self, *_) -> None:
        self.mudou.emit()

    def _escolher_pasta_sondas(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Pasta dos perfis de sonda", self.sondas_dir.text())
        if pasta:
            self.sondas_dir.setText(pasta)

    # --- a captura aberta ---------------------------------------------------

    def configurar_captura(self, caminho: Path, cabecalho: CabecalhoArquivo | None, n_amostras: int) -> None:
        self.caminho, self.cabecalho = caminho, cabecalho
        self.grupo_sem_cabecalho.setVisible(cabecalho is None)
        if cabecalho is not None:
            canais = list(cabecalho.lista_canais)
            self.fim.setRange(1, max(n_amostras, 1))
            self.inicio.setRange(0, max(n_amostras - 1, 0))
        else:
            canais = self._canais_do_texto()
        self._montar_caixas_canais(canais)
        self.resumo.setText(resumo_html(caminho, cabecalho, n_amostras))
        self._atualizar_duracao(n_amostras)
        self.mudou.emit()

    def _canais_do_texto(self) -> list[int]:
        canais = []
        for parte in self.canais_texto.text().split(","):
            parte = parte.strip()
            if parte.isdigit() and int(parte) not in canais:
                canais.append(int(parte))
        return canais or [1]

    def _canais_digitados(self) -> None:
        if self.cabecalho is None:
            self._montar_caixas_canais(self._canais_do_texto())

    def _montar_caixas_canais(self, canais: list[int]) -> None:
        for caixa in self._caixas_canais.values():
            self._leiaute_canais.removeWidget(caixa)
            caixa.deleteLater()
        self._caixas_canais = {}
        for canal in canais:
            caixa = QCheckBox(str(canal))
            caixa.setChecked(True)
            caixa.toggled.connect(self._avisar)
            self._leiaute_canais.insertWidget(len(self._caixas_canais), caixa)
            self._caixas_canais[canal] = caixa
        self.layout_canais.setEnabled(len(canais) > 1)

    def _atualizar_duracao(self, n_amostras: int) -> None:
        cab = self.cabecalho
        fs = (cab.frequencia_pru_hz or cab.frequencia_hz) if cab is not None else self.frequencia.value()
        n_canais = len(self._caixas_canais) or 1
        if fs and n_amostras:
            self.duracao.setText(f"{n_amostras} amostras brutas = {n_amostras / fs:.3f} s "
                                 f"({n_amostras // n_canais} por canal a {fs / n_canais:g} S/s)")
        else:
            self.duracao.setText("")

    @property
    def canais(self) -> list[int]:
        return list(self._caixas_canais)

    @property
    def canais_exibir(self) -> list[int]:
        return [c for c, caixa in self._caixas_canais.items() if caixa.isChecked()]

    # --- a linha de comando -------------------------------------------------

    def argv_captura(self) -> list[str]:
        """O arquivo, a calibração, a sonda e o trecho: o que vale para a análise e para a exportação HDF5."""
        if self.caminho is None:
            raise ErroSHAN("nenhuma captura aberta.")
        argv = [str(self.caminho)]
        if self.cabecalho is None:
            argv += ["-f", _num(self.frequencia.value()), "--canais", ",".join(map(str, self.canais))]
        if self.fs_pedida.isChecked():
            argv.append("--fs-pedida")
        ganho = self.ganho.text().strip()
        if ganho and ganho not in ("1", "1.0"):
            argv += ["--ganho", ganho]
        for flag, campo in (("--faixa", self.faixa), ("--offset", self.offset), ("--grandeza", self.grandeza),
                            ("--sondas-dir", self.sondas_dir), ("--sonda-perfil", self.sonda_perfil)):
            if campo.text().strip():
                argv += [flag, campo.text().strip()]
        if self.formato.currentText() != "uint16":
            argv += ["--formato", self.formato.currentText()]
        if self.sem_correcao_sonda.isChecked():
            argv.append("--sem-correcao-sonda")
        if self.inicio.value() > 0:
            argv += ["--inicio", str(self.inicio.value())]
        if not self.ate_o_fim.isChecked():
            argv += ["--fim", str(self.fim.value())]
        return argv

    def argv(self) -> list[str]:
        """A linha de comando inteira da análise (sem ``-o``: a janela desenha)."""
        argv = self.argv_captura()
        if self.canais_exibir and self.canais_exibir != self.canais:
            argv += ["--canais-exibir", ",".join(map(str, self.canais_exibir))]
        if self.layout_canais.isEnabled() and self.layout_canais.currentText() != "separados":
            argv += ["--layout-canais", self.layout_canais.currentText()]
        if self.passa_alta.isChecked():
            argv += ["--filtro-passa-alta", _num(self.passa_alta_hz.value())]
        if self.passa_baixa.isChecked():
            argv += ["--filtro-passa-baixa", _num(self.passa_baixa_hz.value())]
        if (self.passa_alta.isChecked() or self.passa_baixa.isChecked()) and self.ordem_filtro.value() != ORDEM_FILTRO_PADRAO:
            argv += ["--ordem-filtro", str(self.ordem_filtro.value())]
        if self.grupo_fft.isChecked():
            argv += ["--fft"] + ([str(self.fft_ciclos.value())] if self.fft_ciclos.value() > 0 else [])
            if (self.freq_min.value(), self.freq_max.value()) != (45.0, 65.0):
                argv += ["--freq-min", _num(self.freq_min.value()), "--freq-max", _num(self.freq_max.value())]
            if self.harmonicos.isChecked():
                argv += ["--harmonicos", str(self.harmonicos_n.value())]
        if self.grupo_welch.isChecked():
            argv.append("--welch")
        if self.grupo_welch.isChecked() or self.espectrograma.isChecked():
            if self.resolucao_welch.value() != RESOLUCAO_WELCH_PADRAO:
                argv += ["--resolucao-welch", _num(self.resolucao_welch.value())]
            if self.sobreposicao_welch.value() != SOBREPOSICAO_WELCH_PADRAO:
                argv += ["--sobreposicao-welch", _num(self.sobreposicao_welch.value())]
        if self.espectrograma.isChecked():
            argv.append("--espectrograma")
        janela = JANELAS[self.janela.currentIndex()][1]
        if janela:
            argv += ["--janela", janela]
            if janela == "kaiser":
                argv += ["--kaiser-beta", _num(self.kaiser_beta.value())]
        if self.modo_espectro.currentText() != "tom":
            argv += ["--modo-espectro", self.modo_espectro.currentText()]
        if self.agrupar_bandas.isChecked():
            argv += ["--agrupar-bandas", _num(self.agrupar_bandas_hz.value())]
        if self.picos.isChecked():
            argv += ["--picos", _num(self.picos_db.value())]
            if self.picos_min.value() != CORTE_SUPRAHARMONICOS_PADRAO:
                argv += ["--freq-min-picos", _num(self.picos_min.value())]
            if self.picos_max.value() > 0:
                argv += ["--freq-max-picos", _num(self.picos_max.value())]
            if self.picos_distancia.value() != DISTANCIA_MINIMA_PICOS_PADRAO:
                argv += ["--distancia-minima-picos", _num(self.picos_distancia.value())]
        if self.grupo_iec.isChecked():
            argv.append("--bandas-iec")
            if self.iec_min.value() != 2000.0:
                argv += ["--bandas-iec-min", _num(self.iec_min.value())]
            if self.iec_max.value() > 0:
                argv += ["--bandas-iec-max", _num(self.iec_max.value())]
            if self.iec_sincronizar.isChecked():
                argv.append("--bandas-iec-sincronizar")
            if self.iec_agregar.isChecked():
                argv.append("--bandas-iec-agregar")
        if self.max_pontos.value() > 0:
            argv += ["--max-pontos", str(self.max_pontos.value())]
        elif self.simplificar.isChecked():
            argv.append("--simplificar")
        return argv

    # --- atalhos ------------------------------------------------------------

    def aplicar_preset(self, nome: str) -> None:
        """Os dois usos mais comuns, prontos: a rede (FFT + harmônicos) e os supraharmônicos (Welch + picos, com o
        passa-alta de 2 kHz que a CLI recomenda)."""
        if nome == "rede":
            self.grupo_fft.setChecked(True)
            self.harmonicos.setChecked(True)
            self.grupo_welch.setChecked(False)
            self.passa_alta.setChecked(False)
            self.picos.setChecked(False)
        elif nome == "supraharmonicos":
            self.grupo_fft.setChecked(False)
            self.grupo_welch.setChecked(True)
            self.passa_alta.setChecked(True)
            self.passa_alta_hz.setValue(CORTE_SUPRAHARMONICOS_PADRAO)
            self.picos.setChecked(True)
            self.grupo_iec.setChecked(True)
        elif nome == "forma_de_onda":
            self.grupo_fft.setChecked(False)
            self.grupo_welch.setChecked(False)
            self.grupo_iec.setChecked(False)
            self.espectrograma.setChecked(False)
            self.picos.setChecked(False)


def _html(texto: str) -> str:
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def resumo_html(caminho: Path, cab: CabecalhoArquivo | None, n_amostras: int) -> str:
    """O cabeçalho da captura em poucas linhas (o resumo inteiro vai ao console, por ``anunciar_cabecalho``).
    Os valores já são HTML: o texto que vem do arquivo passa por :func:`_html`."""
    linhas = [("Arquivo", _html(caminho.name))]
    if cab is None:
        linhas.append(("Cabeçalho", "nenhum (arquivo antigo ou .csv): informe a taxa e os canais abaixo"))
        return _tabela_html(linhas)
    fs_pru = cab.frequencia_pru_hz
    taxa = f"{cab.frequencia_hz} S/s total"
    if fs_pru is not None and fs_pru != cab.frequencia_hz:
        taxa += f" (a PRU gera {fs_pru:.2f})"
    canais = []
    for i, canal in enumerate(cab.lista_canais):
        partes = [NOMES_GRANDEZA.get(cab.grandeza_por_canal[i], "?")]
        if cab.faixa_adc_codigo_por_canal and cab.faixa_adc_total_v_por_canal[i] is not None:
            partes.append(f"±{cab.faixa_adc_total_v_por_canal[i] / 2:g} V")
        if cab.sonda_id_por_canal[i]:
            partes.append(f"sonda {_html(cab.sonda_id_por_canal[i])}")
        canais.append(f"{canal}: " + ", ".join(partes))
    if cab.titulo:
        linhas.append(("Título", _html(cab.titulo)))
    if cab.descricao:
        linhas.append(("Descrição", _html(cab.descricao)))
    linhas += [("Capturado em", cab.timestamp_iso_utc), ("Taxa", taxa), ("Canais", "<br>".join(canais))]
    if cab.versao_firmware:
        linhas.append(("Firmware", _html(cab.versao_firmware)))
    duracao = cab.duracao_real_segundos
    linhas.append(("Amostras", f"{n_amostras} brutas, {cab.blocos_gravados} bloco(s)"
                   + (f", {duracao:.3f} s" if duracao is not None else "")))
    problemas = cab.problemas_integridade
    integridade = "tudo certo" if not problemas else "<b>" + _html("; ".join(problemas)) + "</b>"
    if cab.amostras_atrasadas is None:
        integridade = "não registrada (cabeçalho anterior à v4)"
    linhas.append(("Integridade", integridade))
    linhas.append(("CRC-32", "confere" if cab.crc32_valido else "<b>NÃO confere</b>"))
    return _tabela_html(linhas)


def _tabela_html(linhas: list[tuple[str, str]]) -> str:
    celulas = "".join(f"<tr><td><b>{_html(k)}</b>&nbsp;&nbsp;</td><td>{v}</td></tr>" for k, v in linhas)
    return f"<table>{celulas}</table>"


# ---------------------------------------------------------------------------
# A janela
# ---------------------------------------------------------------------------

class JanelaPrincipal(QMainWindow):
    """A janela do SH-Analyzer: o painel de parâmetros à esquerda, as abas (gráficos, tabelas, console) à direita.

    ``silencioso=True`` (testes, scripts) troca as caixas de diálogo de erro por registros no console."""

    def __init__(self, silencioso: bool = False):
        super().__init__()
        self.silencioso = silencioso
        self.resultado: ResultadoAnalise | None = None
        self.ultimo_erro: str | None = None
        self._trabalhador: _Trabalhador | None = None
        self._configuracao = QSettings("SH-Analyzer", "adc_gui")
        self.setWindowTitle(NOME_APLICATIVO)
        if ICONE.exists():
            self.setWindowIcon(QIcon(str(ICONE)))
        self.setAcceptDrops(True)
        self._montar()
        self._ligar_logging()
        self._restaurar_configuracao()

    # --- construção -------------------------------------------------------

    def _montar(self) -> None:
        self.parametros = PainelParametros()
        self.parametros.mudou.connect(self._atualizar_comando)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(self.parametros)
        rolagem.setMinimumWidth(380)

        self.comando = QLineEdit()
        self.comando.setReadOnly(True)
        self.comando.setFont(QFont("monospace"))
        self.comando.setToolTip("O comando do adc_tool.py equivalente ao que a janela vai analisar.")
        botao_copiar = QPushButton("Copiar")
        botao_copiar.clicked.connect(self.copiar_comando)
        self.botao_analisar = QPushButton("Analisar  (F5)")
        self.botao_analisar.setDefault(True)
        self.botao_analisar.clicked.connect(self.analisar)
        rodape = QWidget()
        leiaute_rodape = QGridLayout(rodape)
        leiaute_rodape.setContentsMargins(4, 0, 4, 4)
        leiaute_rodape.addWidget(QLabel("Comando equivalente:"), 0, 0, 1, 2)
        leiaute_rodape.addWidget(self.comando, 1, 0)
        leiaute_rodape.addWidget(botao_copiar, 1, 1)
        leiaute_rodape.addWidget(self.botao_analisar, 2, 0, 1, 2)

        esquerda = QWidget()
        leiaute_esquerda = QVBoxLayout(esquerda)
        leiaute_esquerda.setContentsMargins(0, 0, 0, 0)
        leiaute_esquerda.addWidget(rolagem)
        leiaute_esquerda.addWidget(rodape)

        self.abas = QTabWidget()
        self.figura_principal = PainelFigura()
        self.figura_espectrograma = PainelFigura()
        self.figura_iec = PainelFigura()
        self.tabela_harmonicos = Tabela()
        self.tabela_picos = Tabela()
        self.tabela_iec = Tabela()
        self.canal_harmonicos = QComboBox()
        self.canal_iec = QComboBox()
        self.canal_harmonicos.currentIndexChanged.connect(self._preencher_harmonicos)
        self.canal_iec.currentIndexChanged.connect(self._preencher_tabela_iec)
        self.resumo_harmonicos = QLabel("")
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("monospace"))
        self.console.setMaximumBlockCount(5000)
        self.abas.addTab(self.figura_principal, "Forma de onda e espectro")
        self.abas.addTab(self.figura_espectrograma, "Espectrograma")
        self.abas.addTab(self.figura_iec, "Bandas IEC")
        self.abas.addTab(self._com_seletor(self.canal_harmonicos, self.resumo_harmonicos, self.tabela_harmonicos),
                         "Harmônicos")
        self.abas.addTab(self.tabela_picos, "Picos")
        self.abas.addTab(self._com_seletor(self.canal_iec, QLabel(""), self.tabela_iec), "Bandas IEC (tabela)")
        self.abas.addTab(self.console, "Console")
        self._abas_figuras = {0: self.figura_principal, 1: self.figura_espectrograma, 2: self.figura_iec}

        divisor = QSplitter()
        divisor.addWidget(esquerda)
        divisor.addWidget(self.abas)
        divisor.setStretchFactor(0, 0)
        divisor.setStretchFactor(1, 1)
        self.setCentralWidget(divisor)

        self.progresso = QProgressBar()
        self.progresso.setRange(0, 0)
        self.progresso.setMaximumWidth(160)
        self.progresso.setVisible(False)
        self.statusBar().addPermanentWidget(self.progresso)
        self._montar_menus()
        self._habilitar_resultado(False)
        self.resize(1400, 860)

    @staticmethod
    def _com_seletor(seletor: QComboBox, rotulo: QLabel, tabela: Tabela) -> QWidget:
        caixa = QWidget()
        leiaute = QVBoxLayout(caixa)
        leiaute.setContentsMargins(0, 0, 0, 0)
        leiaute.addWidget(_linha(QLabel("Canal"), seletor, rotulo))
        leiaute.addWidget(tabela)
        return caixa

    def _acao(self, texto: str, atalho: str | None, funcao: Callable[[], None], barra: QToolBar | None = None) -> QAction:
        acao = QAction(texto, self)
        if atalho:
            acao.setShortcut(QKeySequence(atalho))
        acao.triggered.connect(funcao)
        if barra is not None:
            barra.addAction(acao)
        return acao

    def _montar_menus(self) -> None:
        barra = QToolBar("Principal")
        barra.setMovable(False)
        self.addToolBar(barra)
        menu_arquivo = self.menuBar().addMenu("&Arquivo")
        menu_arquivo.addAction(self._acao("&Abrir captura…", "Ctrl+O", self.abrir_dialogo, barra))
        self.menu_recentes = menu_arquivo.addMenu("Abrir &recente")
        menu_arquivo.addSeparator()
        self.acoes_resultado = [
            self._acao("&Salvar a figura…", "Ctrl+S", self.salvar_figura_dialogo, barra),
            self._acao("Exportar &CSV e JSON…", None, self.exportar_csv_dialogo),
            self._acao("Exportar para o &MATLAB (.mat)…", None, self.exportar_mat_dialogo),
        ]
        for acao in self.acoes_resultado:
            menu_arquivo.addAction(acao)
        self.acao_hdf5 = self._acao("Exportar para &HDF5…", None, self.exportar_hdf5_dialogo)
        menu_arquivo.addAction(self.acao_hdf5)
        menu_arquivo.addSeparator()
        menu_arquivo.addAction(self._acao("Sai&r", "Ctrl+Q", self.close))

        menu_analise = self.menuBar().addMenu("A&nálise")
        barra.addSeparator()
        menu_analise.addAction(self._acao("&Analisar", "F5", self.analisar, barra))
        menu_analise.addAction(self._acao("&Copiar o comando equivalente", "Ctrl+Shift+C", self.copiar_comando, barra))
        menu_analise.addSeparator()
        for texto, nome in (("Só a forma de onda", "forma_de_onda"),
                            ("Rede: FFT e harmônicos", "rede"),
                            ("Supraharmônicos: Welch, picos e bandas IEC", "supraharmonicos")):
            menu_analise.addAction(self._acao(texto, None, lambda _=False, n=nome: self.parametros.aplicar_preset(n)))

        menu_ajuda = self.menuBar().addMenu("A&juda")
        menu_ajuda.addAction(self._acao("&Sobre", None, self.sobre))

    def _ligar_logging(self) -> None:
        self._sinal_log = _SinalLog(self)
        self._sinal_log.mensagem.connect(self._registrar)
        self._handler = _HandlerPainel(self._sinal_log)
        raiz = logging.getLogger("supraharmonicos")
        raiz.addHandler(self._handler)
        if raiz.level == logging.NOTSET or raiz.level > logging.INFO:
            raiz.setLevel(logging.INFO)

    def _registrar(self, nivel: int, mensagem: str) -> None:
        prefixo = "Aviso: " if nivel == logging.WARNING else "Erro: " if nivel >= logging.ERROR else ""
        self.console.appendPlainText(prefixo + mensagem)
        if nivel >= logging.WARNING:
            self.statusBar().showMessage(prefixo + mensagem.splitlines()[0], 15000)

    def closeEvent(self, evento) -> None:  # noqa: N802 -- nome do Qt
        if self._trabalhador is not None and self._trabalhador.isRunning():
            self._trabalhador.wait()
        logging.getLogger("supraharmonicos").removeHandler(self._handler)
        self._configuracao.setValue("geometria", self.saveGeometry())
        super().closeEvent(evento)

    # --- configuração que fica entre sessões ---------------------------------

    def _restaurar_configuracao(self) -> None:
        geometria = self._configuracao.value("geometria")
        if geometria is not None:
            self.restoreGeometry(geometria)
        self._montar_menu_recentes()

    def _recentes(self) -> list[str]:
        valor = self._configuracao.value("recentes", [])
        return [valor] if isinstance(valor, str) else list(valor or [])

    def _lembrar(self, caminho: Path) -> None:
        recentes = [str(caminho)] + [r for r in self._recentes() if r != str(caminho)]
        self._configuracao.setValue("recentes", recentes[:10])
        self._configuracao.setValue("pasta", str(caminho.parent))
        self._montar_menu_recentes()

    def _montar_menu_recentes(self) -> None:
        self.menu_recentes.clear()
        for caminho in self._recentes():
            self.menu_recentes.addAction(self._acao(caminho, None, lambda _=False, c=caminho: self.abrir(Path(c))))
        self.menu_recentes.setEnabled(bool(self._recentes()))

    # --- abrir -----------------------------------------------------------

    def dragEnterEvent(self, evento) -> None:  # noqa: N802
        if evento.mimeData().hasUrls():
            evento.acceptProposedAction()

    def dropEvent(self, evento) -> None:  # noqa: N802
        for url in evento.mimeData().urls():
            if url.isLocalFile():
                self.abrir(Path(url.toLocalFile()))
                break

    def abrir_dialogo(self) -> None:
        pasta = self._configuracao.value("pasta", "")
        caminho, _ = QFileDialog.getOpenFileName(self, "Abrir captura", pasta,
                                                 "Capturas (*.bin *.csv);;Todos os arquivos (*)")
        if caminho:
            self.abrir(Path(caminho))

    def abrir(self, caminho: Path) -> bool:
        """Lê o cabeçalho, preenche o painel e, numa captura curta, já a analisa. Devolve se abriu."""
        caminho = Path(caminho)
        try:
            if not caminho.is_file():
                raise ErroSHAN(f"arquivo '{caminho}' não encontrado.")
            cabecalho = ler_cabecalho(caminho) if caminho.suffix.lower() == ".bin" else None
            n_amostras = (contar_amostras_arquivo_bin(caminho, "uint16", CABECALHO_TAMANHO_TOTAL if cabecalho else 0)
                          if caminho.suffix.lower() == ".bin" else 0)
        except ErroSHAN as e:
            self._erro(str(e))
            return False
        self.console.clear()
        self.resultado = None
        self._habilitar_resultado(False)
        self.acao_hdf5.setEnabled(caminho.suffix.lower() == ".bin")
        self.parametros.configurar_captura(caminho, cabecalho, n_amostras)
        self.setWindowTitle(f"{caminho.name} — {NOME_APLICATIVO}")
        self._lembrar(caminho)
        if 0 < n_amostras <= ANALISE_AUTOMATICA_ATE:
            self.analisar()
        else:
            self.statusBar().showMessage("Captura aberta. Ajuste os parâmetros e clique em Analisar (F5).")
        return True

    # --- analisar ---------------------------------------------------------

    def _args(self, argv: list[str]) -> argparse.Namespace | None:
        """Os argumentos pelo parser da CLI; um erro de uso vira mensagem, não a saída do processo."""
        parser = montar_parser()
        try:
            args = parser.parse_args(argv)
            validar_flags_numericas(args)
        except SystemExit:
            self._erro("argumentos inválidos (o parser recusou o comando equivalente; veja o console).")
            return None
        except ErroSHAN as e:
            self._erro(str(e))
            return None
        return args

    def _atualizar_comando(self) -> None:
        try:
            self.comando.setText(shlex.join([*COMANDO_CLI, *self.parametros.argv()]))
        except ErroSHAN:
            self.comando.setText("")

    def copiar_comando(self) -> None:
        QGuiApplication.clipboard().setText(self.comando.text())
        self.statusBar().showMessage("Comando copiado.", 5000)

    def analisar(self) -> bool:
        """Dispara a análise com os parâmetros do painel (fora da thread da janela). Devolve se disparou."""
        if self._trabalhador is not None and self._trabalhador.isRunning():
            self.statusBar().showMessage("Já há uma análise em andamento.", 5000)
            return False
        try:
            argv = self.parametros.argv()
        except ErroSHAN as e:
            self._erro(str(e))
            return False
        args = self._args(argv)
        if args is None:
            return False
        self.console.appendPlainText("$ " + shlex.join([*COMANDO_CLI, *argv]))

        def trabalho() -> ResultadoAnalise:
            ctx = resolver_contexto(args)
            anunciar_cabecalho(ctx, args.formato)
            return analisar_captura(args, ctx)

        self._iniciar(trabalho, self._mostrar_resultado, "Analisando…")
        return True

    def _iniciar(self, funcao: Callable[[], object], ao_concluir: Callable[[object], None], mensagem: str) -> None:
        self.ultimo_erro = None
        self.botao_analisar.setEnabled(False)
        self.progresso.setVisible(True)
        self.statusBar().showMessage(mensagem)
        self._trabalhador = _Trabalhador(funcao, self)
        self._trabalhador.concluido.connect(ao_concluir)
        self._trabalhador.falhou.connect(self._falhou)
        self._trabalhador.finished.connect(self._terminou)
        self._trabalhador.start()

    def _terminou(self) -> None:
        self.progresso.setVisible(False)
        self.botao_analisar.setEnabled(True)

    def _falhou(self, mensagem: str) -> None:
        self._erro(mensagem)

    def aguardar(self, tempo_ms: int = 120_000) -> bool:
        """Espera a análise em andamento acabar e entrega o resultado à janela (scripts e testes, sem o laço de
        eventos rodando). Devolve se acabou a tempo."""
        if self._trabalhador is None:
            return True
        acabou = self._trabalhador.wait(tempo_ms)
        QGuiApplication.processEvents()
        return acabou

    def _erro(self, mensagem: str) -> None:
        self.ultimo_erro = mensagem
        self.console.appendPlainText("Erro: " + mensagem)
        self.statusBar().showMessage("Erro: " + mensagem.splitlines()[0], 15000)
        if not self.silencioso:
            QMessageBox.critical(self, NOME_APLICATIVO, mensagem)

    # --- mostrar o resultado ------------------------------------------------

    def _habilitar_resultado(self, ha: bool) -> None:
        for acao in self.acoes_resultado:
            acao.setEnabled(ha)

    def _mostrar_resultado(self, res: ResultadoAnalise) -> None:
        self.resultado = res
        resultados = res.resultados["canais"]
        n_canais = len(res.por_canal_tensao)
        separados = n_canais > 1 and res.args.layout_canais == "separados"
        self.figura_principal.desenhar(
            ALTURA_POR_CANAL_PX * n_canais if separados else 0,
            lambda fig: plotagem.desenhar_multicanal(
                fig, res.por_canal_tensao, res.fs_efetiva, res.sinal.idx_inicio, res.infos_espectro, res.titulo,
                res.args.layout_canais, res.rotulo_espectro_y, res.limite_inferior_db, res.grandeza_por_canal,
                idx_fim_arquivo=res.idx_fim_arquivo, max_pontos=res.max_pontos))

        tem_espectrograma = any("espectrograma" in r for r in resultados.values())
        if tem_espectrograma:
            self.figura_espectrograma.desenhar(
                ALTURA_POR_CANAL_PX * n_canais,
                lambda fig: plotagem.desenhar_espectrogramas(
                    fig, {c: r["espectrograma"] for c, r in resultados.items()}, res.titulo,
                    res.rotulo_nivel(bandas=False), res.params.rotulo_welch))
        else:
            self.figura_espectrograma.limpar()
        self.abas.setTabEnabled(1, tem_espectrograma)

        tem_iec = any("bandas_iec" in r for r in resultados.values())
        if tem_iec:
            self.figura_iec.desenhar(
                ALTURA_POR_CANAL_PX * n_canais,
                lambda fig: plotagem.desenhar_bandas_iec(
                    fig, {c: r["bandas_iec"] for c, r in resultados.items()},
                    {c: r["unidade"] for c, r in resultados.items()}, res.titulo))
        else:
            self.figura_iec.limpar()
        self.abas.setTabEnabled(2, tem_iec)
        self._preencher_seletor(self.canal_iec, [c for c, r in resultados.items() if "bandas_iec" in r])
        self.abas.setTabEnabled(5, tem_iec)

        canais_harmonicos = [c for c, r in resultados.items() if "harmonicos" in r]
        self._preencher_seletor(self.canal_harmonicos, canais_harmonicos)
        self.abas.setTabEnabled(3, bool(canais_harmonicos))
        self._preencher_picos(res)
        self.abas.setTabEnabled(4, res.args.picos is not None)

        self._habilitar_resultado(True)
        n_por_canal = len(next(iter(res.por_canal_tensao.values())))
        self.statusBar().showMessage(f"Análise concluída: {n_por_canal} amostras por canal a {res.fs_efetiva:g} S/s "
                                     f"({n_por_canal / res.fs_efetiva:.3f} s).")

    def _preencher_seletor(self, seletor: QComboBox, canais: list[int]) -> None:
        seletor.blockSignals(True)
        seletor.clear()
        for canal in canais:
            seletor.addItem(str(canal), canal)
        seletor.blockSignals(False)
        seletor.setCurrentIndex(0 if canais else -1)
        seletor.currentIndexChanged.emit(seletor.currentIndex())

    def _preencher_harmonicos(self, *_) -> None:
        canal = self.canal_harmonicos.currentData()
        if self.resultado is None or canal is None:
            self.tabela_harmonicos.preencher([], [])
            self.resumo_harmonicos.setText("")
            return
        r = self.resultado.resultados["canais"][canal]
        tabela, u = r["harmonicos"], r["unidade"]
        self.resumo_harmonicos.setText(
            f"f0 = {tabela.f0_hz:.4f} Hz, {tabela.n_ciclos} ciclos | THD = {tabela.thd_pct:.4f} % | "
            f"THDG (IEC 61000-4-7) = {tabela.thdg_pct:.4f} % | RMS total (sem DC) = {tabela.rms_total:.6g} {u}")
        self.tabela_harmonicos.preencher(
            ["h", "f (Hz)", f"RMS ({u})", f"grupo ({u})", "% da fundamental", "fase (°)"],
            [[h.ordem, h.frequencia_hz, h.rms, h.rms_grupo, h.pct_fundamental, h.fase_graus] for h in tabela.harmonicos])

    def _preencher_picos(self, res: ResultadoAnalise) -> None:
        picos = sorted(res.resultados["picos"], key=lambda p: (p["canal"], p["metodo"], -p["amplitude_db"]))
        self.tabela_picos.preencher(["canal", "método", "f (Hz)", "nível (dB)"],
                                    [[p["canal"], p["metodo"], p["frequencia_hz"], p["amplitude_db"]] for p in picos])

    def _preencher_tabela_iec(self, *_) -> None:
        canal = self.canal_iec.currentData()
        if self.resultado is None or canal is None:
            self.tabela_iec.preencher([], [])
            return
        r = self.resultado.resultados["canais"][canal]
        b, u = r["bandas_iec"], r["unidade"]
        est = b.estatisticas()
        extras = [(nome, b.estatisticas(nome)) for nome in ("3s", "10min") if nome in b.agregados]
        colunas = ["banda (Hz)", f"P95 ({u})", f"máximo ({u})", f"RMS ({u})", f"mínimo ({u})"]
        colunas += [f"P95 de {nome} ({u})" for nome, _ in extras]
        linhas = []
        for i, centro in enumerate(b.centros_hz):
            linha = [float(centro), float(est["p95"][i]), float(est["maximo"][i]), float(est["rms"][i]),
                     float(est["minimo"][i])]
            linha += [float(e["p95"][i]) for _, e in extras]
            linhas.append(linha)
        self.tabela_iec.preencher(colunas, linhas)

    # --- exportar ----------------------------------------------------------

    def _pasta_sugerida(self, sufixo: str) -> str:
        if self.parametros.caminho is None:
            return ""
        return str(self.parametros.caminho.with_suffix("")) + sufixo

    def figura_atual(self) -> Figure | None:
        painel = self._abas_figuras.get(self.abas.currentIndex(), self.figura_principal)
        return painel.figura if painel.figura.axes else None

    def salvar_figura_dialogo(self) -> None:
        if self.figura_atual() is None:
            self._erro("não há figura nesta aba: analise a captura, ou escolha a aba de um gráfico.")
            return
        caminho, _ = QFileDialog.getSaveFileName(self, "Salvar a figura", self._pasta_sugerida(".png"), FILTROS_IMAGEM)
        if caminho:
            self.salvar_figura(Path(caminho))

    def salvar_figura(self, caminho: Path) -> None:
        figura = self.figura_atual()
        if figura is None:
            raise ErroSHAN("não há figura para salvar.")
        figura.savefig(caminho, dpi=150)
        log.info(f"Gráfico salvo em '{caminho}'.")

    def exportar_csv_dialogo(self) -> None:
        caminho, _ = QFileDialog.getSaveFileName(self, "Prefixo dos CSVs e do JSON de metadados",
                                                 self._pasta_sugerida("_resultados"))
        if caminho:
            self._exportar(prefixo_csv=Path(caminho))

    def exportar_mat_dialogo(self) -> None:
        caminho, _ = QFileDialog.getSaveFileName(self, "Exportar para o MATLAB", self._pasta_sugerida(".mat"),
                                                 "MATLAB (*.mat)")
        if caminho:
            self._exportar(arquivo_mat=Path(caminho))

    def _exportar(self, prefixo_csv: Path | None = None, arquivo_mat: Path | None = None) -> list[Path]:
        if self.resultado is None:
            self._erro("nada para exportar: analise a captura antes.")
            return []
        try:
            escritos = exportar_resultados(self.resultado, prefixo_csv, arquivo_mat)
        except ErroSHAN as e:
            self._erro(str(e))
            return []
        self.statusBar().showMessage(f"{len(escritos)} arquivo(s) exportado(s).", 10000)
        return escritos

    def exportar_hdf5_dialogo(self) -> None:
        caminho, _ = QFileDialog.getSaveFileName(self, "Exportar para HDF5", self._pasta_sugerida(".h5"), "HDF5 (*.h5)")
        if not caminho:
            return
        resposta = QMessageBox.question(self, NOME_APLICATIVO, "Incluir também /tensao_v (as amostras em volts, além "
                                        "dos códigos brutos)?")
        self.exportar_hdf5(Path(caminho), incluir_tensao=resposta == QMessageBox.StandardButton.Yes)

    def exportar_hdf5(self, caminho: Path, incluir_tensao: bool = False) -> bool:
        """O ``--export-hdf5`` da CLI, com a calibração e o trecho do painel, fora da thread da janela."""
        try:
            argv = [*self.parametros.argv_captura(), "--export-hdf5", str(caminho)]
        except ErroSHAN as e:
            self._erro(str(e))
            return False
        if incluir_tensao:
            argv.append("--incluir-tensao")
        args = self._args(argv)
        if args is None:
            return False
        self.console.appendPlainText("$ " + shlex.join([*COMANDO_CLI, *argv]))

        def trabalho() -> Path:
            executar_exportacao_hdf5(args, resolver_contexto(args))
            return caminho

        self._iniciar(trabalho, lambda c: self.statusBar().showMessage(f"HDF5 gravado em '{c}'.", 10000),
                      "Exportando para HDF5…")
        return True

    def sobre(self) -> None:
        QMessageBox.about(self, f"Sobre o {NOME_APLICATIVO}",
                          f"<b>{NOME_APLICATIVO}</b>: a análise do <code>adc_tool.py</code> numa janela.<br><br>"
                          "Cada gráfico e tabela vem do mesmo código da linha de comando; o comando equivalente ao "
                          "que a janela mostra está no rodapé do painel e pode ser copiado.<br><br>"
                          "Guia de uso: <code>docs/user-guide.md</code>.")


def executar(arquivos: list[Path], argv_qt: list[str] | None = None) -> int:
    """Cria a aplicação, abre a janela (e a primeira captura, se dada) e roda até ela fechar."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(argv_qt if argv_qt is not None else [NOME_APLICATIVO])
    app.setApplicationName(NOME_APLICATIVO)
    if ICONE.exists():
        app.setWindowIcon(QIcon(str(ICONE)))
    janela = JanelaPrincipal()
    janela.show()
    for arquivo in arquivos[:1]:
        janela.abrir(arquivo)
    return app.exec()


__all__ = ["JanelaPrincipal", "PainelParametros", "PainelFigura", "Tabela", "resumo_html", "executar", "ICONE"]
