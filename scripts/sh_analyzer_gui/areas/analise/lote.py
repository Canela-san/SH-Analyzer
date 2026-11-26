"""A análise em lote ("Análise em lote…", ``dados/lote.py``): uma pasta de capturas (com as subpastas: as sessões
de vários dias), os mesmos índices em cada captura e canal, a tabela, a tendência no tempo e o CSV. As contas numa
tarefa que se cancela; um duplo clique numa linha abre a captura no projeto.
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...componentes.basicos import Botao
from ...componentes.numeros import formatar_duracao, formatar_si, separador_decimal
from ...dados import lote
from ...graficos.faixa import EixoDoTema
from ...tema.aplicar import aparencia
from ...tema.tokens import cor_do_traco

TRECHOS = ((None, "A captura inteira"), (60.0, "Os primeiros 60 s"), (600.0, "Os primeiros 10 min"))
COLUNAS = ("Início", "Arquivo", "Canal", "Duração", "Integridade", "Frequência", "RMS", "THD (P95)",
           "2 a 9 kHz (P95)", "9 a 150 kHz (P95)", "Maior banda", "Eventos", "Marcadas")


class DialogoDoLote(QDialog):
    """``abrirCaptura(Path)``: o duplo clique numa linha (a janela abre a captura no projeto)."""

    abrirCaptura = Signal(object)

    def __init__(self, tarefas, dialogos, parent: QWidget | None = None, *, pasta: Path | None = None):
        super().__init__(parent)
        self.setObjectName("dialogo_do_lote")
        self.setWindowTitle(self.tr("Análise em lote"))
        self.resize(1080, 680)
        self.tarefas, self.dialogos = tarefas, dialogos
        self.linhas: list[lote.LinhaDoLote] = []
        self._tarefa = None

        explicacao = QLabel(self.tr("Os mesmos índices em cada captura de uma pasta (e das subpastas: as sessões de "
                                    "vários dias), no canal sem transformações: a qualidade da IEC 61000-4-30, a maior "
                                    "banda da IEC 61000-4-7 e os eventos. Um duplo clique abre a captura."))
        explicacao.setWordWrap(True)
        explicacao.setObjectName("subtitulo_inspetor")
        self.pasta = QLineEdit(str(pasta) if pasta else "")
        self.pasta.setObjectName("pasta_do_lote")
        self.pasta.setPlaceholderText(self.tr("Nenhuma pasta escolhida"))
        escolher = Botao(self.tr("Escolher…"), "secundario", "pasta")
        escolher.clicked.connect(self._escolher)
        self.subpastas = QCheckBox(self.tr("Subpastas"))
        self.subpastas.setChecked(True)
        self.trecho = QComboBox()
        self.trecho.setObjectName("trecho_do_lote")
        for limite, texto in TRECHOS:
            self.trecho.addItem(self.tr(texto), limite)
        self.trecho.setToolTip(self.tr("Os primeiros segundos de cada captura fazem um lote longo andar rápido"))
        self.calcular_botao = Botao(self.tr("Calcular"), "primario", "play")
        self.calcular_botao.setObjectName("calcular_lote")
        self.calcular_botao.clicked.connect(lambda: self.calcular())
        linha = QHBoxLayout()
        linha.addWidget(self.pasta, 1)
        for w in (escolher, self.subpastas, self.trecho, self.calcular_botao):
            linha.addWidget(w)

        self.tabela = QTableWidget(0, len(COLUNAS))
        self.tabela.setObjectName("tabela_do_lote")
        self.tabela.setHorizontalHeaderLabels([self.tr(c) for c in COLUNAS])
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.verticalHeader().hide()
        self.tabela.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tabela.horizontalHeader().setStretchLastSection(True)
        self.tabela.cellDoubleClicked.connect(self._abrir_linha)

        self.coluna = QComboBox()
        self.coluna.setObjectName("tendencia_do_lote")
        for chave, (nome, _unidade) in lote.COLUNAS_NUMERICAS.items():
            self.coluna.addItem(self.tr(nome), chave)
        self.coluna.setCurrentIndex(self.coluna.findData("thd_p95"))
        self.coluna.currentIndexChanged.connect(lambda _i: self._desenhar())
        self.grafico = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom"),
                                                "left": EixoDoTema("left")})
        self.grafico.setObjectName("grafico_do_lote")
        self.grafico.setMenuEnabled(False)
        self.grafico.hideButtons()
        self.grafico.addLegend(offset=(-10, 10))
        tendencia = QWidget()
        coluna_da_tendencia = QVBoxLayout(tendencia)
        coluna_da_tendencia.setContentsMargins(0, 0, 0, 0)
        linha_da_tendencia = QHBoxLayout()
        linha_da_tendencia.addWidget(QLabel(self.tr("Tendência de")))
        linha_da_tendencia.addWidget(self.coluna)
        linha_da_tendencia.addStretch(1)
        coluna_da_tendencia.addLayout(linha_da_tendencia)
        coluna_da_tendencia.addWidget(self.grafico, 1)

        divisor = QSplitter(Qt.Orientation.Vertical)
        divisor.addWidget(self.tabela)
        divisor.addWidget(tendencia)
        divisor.setSizes([330, 260])

        self.estado = QLabel()
        self.estado.setObjectName("estado_do_lote")
        self.andamento = QProgressBar()
        self.andamento.setRange(0, 1000)
        self.andamento.setMaximumWidth(220)
        self.andamento.hide()
        self.exportar_botao = Botao(self.tr("Exportar CSV…"), "secundario", "baixar")
        self.exportar_botao.setEnabled(False)
        self.exportar_botao.clicked.connect(lambda: self.exportar())
        fechar = Botao(self.tr("Fechar"), "secundario")
        fechar.clicked.connect(self.close)
        rodape = QHBoxLayout()
        rodape.addWidget(self.estado, 1)
        rodape.addWidget(self.andamento)
        rodape.addWidget(self.exportar_botao)
        rodape.addWidget(fechar)

        coluna = QVBoxLayout(self)
        coluna.addWidget(explicacao)
        coluna.addLayout(linha)
        coluna.addWidget(divisor, 1)
        coluna.addLayout(rodape)
        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou(aparencia().tema)

    # ------------------------------------------------------------------ as contas

    def _escolher(self) -> None:
        pasta = self.dialogos.escolher_pasta(self.tr("A pasta das capturas"), self.pasta.text())
        if pasta is not None:
            self.pasta.setText(str(pasta))

    def calcular(self):
        """Começa (ou cancela) o lote; devolve a tarefa."""
        if self._tarefa is not None and self._tarefa.ativa:
            self._tarefa.cancelar()
            return None
        pasta = Path(self.pasta.text().strip()) if self.pasta.text().strip() else None
        if pasta is None or not pasta.is_dir():
            self.estado.setText(self.tr("Escolha uma pasta com capturas."))
            return None
        caminhos = lote.capturas_da_pasta(pasta, recursivo=self.subpastas.isChecked())
        if not caminhos:
            self.estado.setText(self.tr("Nenhuma captura (.bin ou .h5) em {}.").format(pasta))
            return None
        limite = self.trecho.currentData()

        def trabalho(progresso, cancelado):
            return lote.calcular(caminhos, limite_s=limite, progresso=progresso, cancelado=cancelado)

        self.estado.setText(self.tr("Calculando {} capturas…").format(len(caminhos)))
        self.calcular_botao.setText(self.tr("Cancelar"))
        self.andamento.setValue(0)
        self.andamento.show()
        self._tarefa = self.tarefas.iniciar(
            self.tr("Análise em lote de {}").format(pasta.name), trabalho, "lote", pesada=True,
            ao_terminar=self._terminou, ao_progredir=lambda _t, f: self.andamento.setValue(int(1000 * f)))
        return self._tarefa

    def _terminou(self, tarefa) -> None:
        self._tarefa = None
        self.calcular_botao.setText(self.tr("Calcular"))
        self.andamento.hide()
        if tarefa.estado == "falhou":
            self.estado.setText(self.tr("O lote parou: {}").format(tarefa.erro))
            return
        if tarefa.estado != "concluida":
            self.estado.setText(self.tr("Cancelado."))
            return
        self.mostrar(tarefa.resultado)

    def mostrar(self, linhas) -> None:
        self.linhas = lote.em_ordem_de_tempo(linhas)
        self._preencher()
        self._desenhar()
        capturas = len({linha.caminho for linha in self.linhas})
        erros = sum(1 for linha in self.linhas if linha.erro)
        texto = self.tr("{} capturas, {} linhas").format(capturas, len(self.linhas))
        if erros:
            texto += self.tr(" · {} com erro (passe o mouse na linha)").format(erros)
        self.estado.setText(texto)
        self.exportar_botao.setEnabled(bool(self.linhas))

    # ------------------------------------------------------------------ a tabela e a tendência

    def _preencher(self) -> None:
        self.tabela.setRowCount(len(self.linhas))
        erro = QColor(aparencia().tema.erro)
        for k, linha in enumerate(self.linhas):
            u = linha.unidade
            valores = [
                linha.inicio.astimezone().strftime("%d/%m/%Y %H:%M:%S") if linha.inicio else "—", self._nome(linha),
                f"{linha.canal} ({linha.grandeza})" if linha.canal >= 0 else "—",
                formatar_duracao(linha.duracao_s) if math.isfinite(linha.duracao_s) else "—", linha.integridade,
                _si(linha.frequencia_hz, "Hz", 6), _si(linha.rms, u, 4), _si(100 * linha.thd_p95, "%", 3),
                _si(linha.supra_2_9k_p95, u, 3), _si(linha.supra_9_150k_p95, u, 3),
                "—" if math.isnan(linha.banda_maior_hz) else
                f"{formatar_si(linha.banda_maior_hz, 'Hz', 4)}: {formatar_si(linha.banda_maior_p95, u, 3)}",
                str(linha.eventos), str(linha.marcadas)]
            for c, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                if c >= 5:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if linha.erro:
                    item.setToolTip(linha.erro)
                    if c == 1:
                        item.setForeground(erro)
                if c == 4 and linha.integridade == "não confere":
                    item.setForeground(erro)
                self.tabela.setItem(k, c, item)

    def _nome(self, linha: lote.LinhaDoLote) -> str:
        """O caminho da captura a partir da pasta escolhida (as sessões repetem o nome do arquivo)."""
        try:
            return Path(linha.caminho).relative_to(Path(self.pasta.text().strip())).as_posix()
        except ValueError:
            return linha.arquivo

    def series(self, chave: str) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        """A tendência de ``chave`` por canal: (os instantes em s desde 1970, os valores), em ordem de tempo."""
        fator = 100.0 if chave == "thd_p95" else 1.0
        series: dict[str, tuple[list, list]] = {}
        for linha in self.linhas:
            valor = float(getattr(linha, chave))
            if linha.inicio is None or not math.isfinite(valor) or linha.canal < 0:
                continue
            nome = self.tr("canal {} ({})").format(linha.canal, linha.grandeza)
            xs, ys = series.setdefault(nome, ([], []))
            xs.append(linha.inicio.timestamp())
            ys.append(fator * valor)
        return {nome: (np.array(xs), np.array(ys)) for nome, (xs, ys) in series.items()}

    def _desenhar(self) -> None:
        self.grafico.clear()
        chave = self.coluna.currentData()
        nome, unidade = lote.COLUNAS_NUMERICAS[chave]
        if unidade is None:
            unidades = {linha.unidade for linha in self.linhas if linha.canal >= 0}
            unidade = unidades.pop() if len(unidades) == 1 else ""
        self.grafico.setLabel("left", self.tr(nome), units=unidade or None)
        t = aparencia().tema
        for k, (serie, (x, y)) in enumerate(self.series(chave).items()):
            cor = QColor(cor_do_traco(k, t)[0])
            self.grafico.plot(x, y, name=serie, pen=pg.mkPen(cor, width=1.5), symbol="o", symbolSize=6,
                              symbolBrush=cor, symbolPen=None)

    def _abrir_linha(self, linha: int, _coluna: int) -> None:
        if 0 <= linha < len(self.linhas) and Path(self.linhas[linha].caminho).exists():
            self.abrirCaptura.emit(Path(self.linhas[linha].caminho))

    def exportar(self, caminho: Path | None = None) -> Path | None:
        if not self.linhas:
            return None
        if caminho is None:
            pasta = self.pasta.text().strip() or str(Path.home())
            caminho = self.dialogos.salvar_arquivo(self.tr("Exportar o lote"), "CSV (*.csv)",
                                                   str(Path(pasta) / f"lote-{datetime.date.today():%Y%m%d}.csv"))
            if caminho is None:
                return None
        caminho = Path(caminho)
        decimal = separador_decimal()
        caminho.write_text(lote.em_csv(self.linhas, separador=";" if decimal == "," else ",", decimal=decimal),
                           encoding="utf-8")
        self.estado.setText(self.tr("Exportado: {}").format(caminho.name))
        return caminho

    def _tema_mudou(self, t) -> None:
        self.grafico.setBackground(QColor(t.afundada))
        for eixo in ("bottom", "left"):
            self.grafico.getAxis(eixo).setTextPen(QColor(t.texto2))
            self.grafico.getAxis(eixo).setPen(QColor(t.eixo))
        if self.linhas:
            self._desenhar()

    def closeEvent(self, evento) -> None:
        if self._tarefa is not None and self._tarefa.ativa:
            self._tarefa.cancelar()
        super().closeEvent(evento)


def _si(valor: float, unidade: str, digitos: int) -> str:
    return "—" if not math.isfinite(valor) else formatar_si(valor, unidade, digitos)
