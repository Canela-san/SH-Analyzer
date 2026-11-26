"""Importar dados de fora (PD-03, PD-10; ``supraharmonicos.importacao`` pela ``api``): o osciloscópio, o CSV
genérico, o WAV e o COMTRADE viram uma captura (um ``.h5`` ao lado do arquivo, ou na pasta dos dados) que abre no
projeto como qualquer outra.

O diálogo:

* **O arquivo** é lido numa tarefa (um registro de osciloscópio pode ter milhões de pontos): o que ele tem aparece
  na tabela dos canais, com os avisos da leitura.
* **O CSV e o TXT** mostram o assistente das colunas: as primeiras linhas, o separador e o decimal achados, a
  coluna de tempo e as colunas de valores (marcadas na tabela). "Automático" usa o leitor do osciloscópio.
* **Cada canal** tem a grandeza (tensão ou corrente: a unidade dos eixos e das contas) e a escala (o valor do
  arquivo vezes ela: a razão de uma ponta de prova, o fundo de escala de um WAV).
* **A taxa** vem do arquivo e pode ser corrigida; sem ela, o botão fica desligado.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from supraharmonicos.api import ErroSHAN
from supraharmonicos.api import importacao as imp

from ...componentes.basicos import Botao, CampoComUnidade
from ...componentes.numeros import NumeroInvalido, formatar_duracao, formatar_si, ler_numero

FILTRO_DE_IMPORTAR = ("Dados de fora (*.csv *.txt *.m *.mat *.wav *.cfg);;Osciloscópio (*.csv *.txt *.m *.mat);;"
                      "WAV (*.wav);;COMTRADE (*.cfg);;Todos os arquivos (*)")
GRANDEZAS = (("Tensão", "V"), ("Corrente", "A"))


def destino_da_importacao(origem: Path, pasta_dos_dados: Path | None = None) -> Path:
    """Onde a captura importada fica: ao lado do arquivo (``rede.csv`` → ``rede.importado.h5``), ou, numa pasta em
    que não se escreve, na pasta dos dados (``importados/``). Um nome que já existe ganha um número."""
    origem = Path(origem)
    pasta = origem.parent
    if pasta_dos_dados is not None and not _da_para_escrever(pasta):
        pasta = Path(pasta_dos_dados) / "importados"
    destino, n = pasta / f"{origem.stem}.importado.h5", 2
    while destino.exists():
        destino, n = pasta / f"{origem.stem}.importado-{n}.h5", n + 1
    return destino


def _da_para_escrever(pasta: Path) -> bool:
    import os

    return pasta.is_dir() and os.access(pasta, os.W_OK)


class DialogoDeImportacao(QDialog):
    """``importadaPronta(Path)`` sai com a captura gravada (a janela a abre no projeto). ``tarefas`` é o
    gerenciador da janela; ``pasta_dos_dados``, o lugar das importadas quando o do arquivo não se escreve."""

    importadaPronta = Signal(object)

    def __init__(self, tarefas, pasta_dos_dados: Path | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dialogo_de_importacao")
        self.setWindowTitle(self.tr("Importar dados de fora"))
        self.setMinimumWidth(640)
        self.tarefas, self.pasta_dos_dados = tarefas, pasta_dos_dados
        self.caminho: Path | None = None
        self.lido: imp.Importado | None = None
        self.previa: imp.PreviaDoCsv | None = None
        self._tarefa = None

        explicacao = QLabel(self.tr("Um registro de osciloscópio (.csv, .txt, .m, .mat), um CSV qualquer, um WAV ou um "
                                    "COMTRADE (.cfg com o .dat) vira uma captura do projeto: o espectro, as bandas, a "
                                    "qualidade e as figuras valem para ela."))
        explicacao.setWordWrap(True)
        explicacao.setObjectName("subtitulo_inspetor")
        self.arquivo = QLineEdit()
        self.arquivo.setObjectName("arquivo_importado")
        self.arquivo.setReadOnly(True)
        self.arquivo.setPlaceholderText(self.tr("Nenhum arquivo escolhido"))
        escolher = Botao(self.tr("Escolher…"), "secundario", "pasta")
        escolher.clicked.connect(self._escolher)
        linha = QHBoxLayout()
        linha.addWidget(self.arquivo, 1)
        linha.addWidget(escolher)

        # O assistente das colunas (só no CSV e no TXT).
        self.assistente = QWidget()
        self.assistente.setObjectName("assistente_das_colunas")
        self.modo = QComboBox()
        self.modo.addItem(self.tr("Automático (o leitor do osciloscópio)"), "auto")
        self.modo.addItem(self.tr("Escolher as colunas"), "colunas")
        self.modo.currentIndexChanged.connect(lambda _i: self._ler())
        self.tempo = QComboBox()
        self.tempo.setObjectName("coluna_de_tempo")
        self.tempo.currentIndexChanged.connect(lambda _i: self._ler() if self._modo() == "colunas" else None)
        self.tabela_previa = QTableWidget(0, 0)
        self.tabela_previa.setObjectName("previa_do_csv")
        self.tabela_previa.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela_previa.setMaximumHeight(170)
        self.tabela_previa.horizontalHeader().sectionClicked.connect(self._alternar_coluna)
        self.sobre_a_previa = QLabel()
        self.sobre_a_previa.setObjectName("subtitulo_inspetor")
        self.sobre_a_previa.setWordWrap(True)
        self.colunas_marcadas: list[int] = []
        forma = QFormLayout()
        forma.addRow(self.tr("Leitura"), self.modo)
        forma.addRow(self.tr("Coluna de tempo"), self.tempo)
        coluna_do_assistente = QVBoxLayout(self.assistente)
        coluna_do_assistente.setContentsMargins(0, 0, 0, 0)
        coluna_do_assistente.addLayout(forma)
        coluna_do_assistente.addWidget(self.tabela_previa)
        coluna_do_assistente.addWidget(self.sobre_a_previa)
        self.assistente.hide()

        self.taxa = CampoComUnidade("Hz", 0.0, minimo=0.0, digitos=7)
        self.taxa.setObjectName("taxa_importada")
        self.taxa.clear()
        self.taxa.setPlaceholderText(self.tr("a taxa de cada canal, ex.: 1M"))
        self.taxa.editingFinished.connect(self._conferir)
        self.canais = QTableWidget(0, 4)
        self.canais.setObjectName("canais_importados")
        self.canais.setHorizontalHeaderLabels([self.tr("Usar"), self.tr("Canal"), self.tr("Grandeza"),
                                               self.tr("Escala (×)")])
        self.canais.verticalHeader().hide()
        self.canais.horizontalHeader().setStretchLastSection(True)
        self.resumo = QLabel()
        self.resumo.setObjectName("resumo_da_importacao")
        self.resumo.setWordWrap(True)
        self.botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.importar_botao = self.botoes.addButton(self.tr("Importar"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.importar_botao.setObjectName("importar")
        self.importar_botao.setProperty("variante", "primario")
        self.importar_botao.setEnabled(False)
        self.importar_botao.clicked.connect(self.importar)
        self.botoes.rejected.connect(self.reject)

        coluna = QVBoxLayout(self)
        coluna.addWidget(explicacao)
        coluna.addLayout(linha)
        coluna.addWidget(self.assistente)
        taxa = QFormLayout()
        taxa.addRow(self.tr("Taxa de cada canal"), self.taxa)
        coluna.addLayout(taxa)
        coluna.addWidget(self.canais, 1)
        coluna.addWidget(self.resumo)
        coluna.addWidget(self.botoes)

    # ------------------------------------------------------------------ o arquivo

    def _escolher(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(self, self.tr("Importar dados de fora"), "",
                                                 self.tr(FILTRO_DE_IMPORTAR))
        if caminho:
            self.carregar(Path(caminho))

    def carregar(self, caminho: Path):
        """Lê ``caminho`` numa tarefa (devolvida); no CSV e no TXT, mostra antes a prévia das colunas."""
        self.caminho = Path(caminho)
        self.arquivo.setText(str(self.caminho))
        self.previa = None
        e_texto = self.caminho.suffix.lower() in (".csv", ".txt")
        self.assistente.setVisible(e_texto)
        if e_texto:
            try:
                self.previa = imp.previa_do_csv(self.caminho)
            except (ErroSHAN, OSError) as e:
                self._falhou(str(e))
                return None
            self._mostrar_previa()
        return self._ler()

    def _modo(self) -> str:
        return self.modo.currentData() if self.previa is not None else "auto"

    def _mostrar_previa(self) -> None:
        p = self.previa
        assert p is not None
        self.tabela_previa.blockSignals(True)
        self.tabela_previa.setColumnCount(len(p.colunas))
        self.tabela_previa.setRowCount(len(p.linhas))
        self.tabela_previa.setHorizontalHeaderLabels(list(p.colunas))
        for i, linha in enumerate(p.linhas):
            for j, valor in enumerate(linha):
                self.tabela_previa.setItem(i, j, QTableWidgetItem(valor))
        self.tabela_previa.blockSignals(False)
        self.tempo.blockSignals(True)
        self.tempo.clear()
        self.tempo.addItem(self.tr("Nenhuma (diga a taxa)"), None)
        for j, nome in enumerate(p.colunas):
            self.tempo.addItem(nome, j)
        self.tempo.setCurrentIndex(0 if p.coluna_de_tempo is None else p.coluna_de_tempo + 1)
        self.tempo.blockSignals(False)
        self.colunas_marcadas = [j for j in range(len(p.colunas)) if j != p.coluna_de_tempo][:imp.MAX_CANAIS]
        separador = {";": "ponto e vírgula", "\t": "tabulação", ",": "vírgula", " ": "espaço"}[p.separador]
        self.sobre_a_previa.setText(self.tr("Separador: {}; decimal: \"{}\"; {} linha(s) de texto antes dos números. "
                                            "No modo das colunas, clique no título de uma coluna para usá-la ou "
                                            "não.").format(separador, p.decimal, p.pular))
        self._pintar_colunas()

    def _alternar_coluna(self, j: int) -> None:
        if self._modo() != "colunas" or j == self.tempo.currentData():
            return
        if j in self.colunas_marcadas:
            self.colunas_marcadas.remove(j)
        elif len(self.colunas_marcadas) < imp.MAX_CANAIS:
            self.colunas_marcadas.append(j)
            self.colunas_marcadas.sort()
        self._pintar_colunas()
        self._ler()

    def _pintar_colunas(self) -> None:
        for j in range(self.tabela_previa.columnCount()):
            item = self.tabela_previa.horizontalHeaderItem(j)
            if item is not None:
                marcada = j in self.colunas_marcadas and self._modo() == "colunas"
                fonte = item.font()
                fonte.setBold(marcada)
                item.setFont(fonte)

    def _ler(self):
        """A leitura numa tarefa (o resultado vai para a tabela dos canais)."""
        if self.caminho is None:
            return None
        caminho, previa, modo = self.caminho, self.previa, self._modo()
        colunas, tempo = list(self.colunas_marcadas), self.tempo.currentData()
        taxa = self._taxa_dita()

        def trabalho(_progresso, _cancelado):
            try:
                if modo == "colunas" and previa is not None:
                    return imp.ler_csv(caminho, colunas, coluna_de_tempo=tempo, taxa_hz=taxa if tempo is None else None,
                                       separador=previa.separador, decimal=previa.decimal, pular=previa.pular), ""
                return imp.ler(caminho, taxa_hz=taxa), ""
            except ErroSHAN as e:
                return None, str(e)
            except OSError as e:
                return None, e.strerror or str(e)

        def terminou(tarefa) -> None:
            if tarefa.estado != "concluida":
                self._falhou(tarefa.erro if tarefa.estado == "falhou" else "")
                return
            lido, erro = tarefa.resultado
            if lido is None:
                self._falhou(erro)
            else:
                self._mostrar(lido)

        self.importar_botao.setEnabled(False)
        self.resumo.setText(self.tr("Lendo {}…").format(caminho.name))
        self._tarefa = self.tarefas.iniciar(self.tr("Ler {}").format(caminho.name), trabalho, "importar",
                                            ao_terminar=terminou)
        return self._tarefa

    def _taxa_dita(self) -> float | None:
        texto = self.taxa.text().strip()
        if not texto:
            return None
        try:
            valor = ler_numero(texto, "Hz")
        except NumeroInvalido:
            return None
        return valor if valor > 0 else None

    def _falhou(self, motivo: str) -> None:
        self.lido = None
        self.canais.setRowCount(0)
        self.resumo.setText(motivo)
        self.importar_botao.setEnabled(False)

    def _mostrar(self, lido: imp.Importado) -> None:
        self.lido = lido
        if self._taxa_dita() is None:
            self.taxa.definir_valor(lido.taxa_hz)
        self.canais.setRowCount(len(lido.canais))
        for i, canal in enumerate(lido.canais):
            usar = QCheckBox()
            usar.setChecked(True)
            usar.toggled.connect(lambda _m: self._conferir())
            self.canais.setCellWidget(i, 0, usar)
            nome = QTableWidgetItem(canal.nome)
            nome.setFlags(nome.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.canais.setItem(i, 1, nome)
            grandeza = QComboBox()
            for rotulo, unidade in GRANDEZAS:
                grandeza.addItem(self.tr(rotulo), unidade)
            grandeza.setCurrentIndex(1 if canal.unidade == "A" else 0)
            self.canais.setCellWidget(i, 2, grandeza)
            escala = CampoComUnidade("", 1.0, digitos=6)
            escala.setToolTip(self.tr("O valor do arquivo vezes este número: a razão de uma ponta de prova (×10, "
                                      "×100), ou o fundo de escala de um WAV"))
            self.canais.setCellWidget(i, 3, escala)
        self.canais.resizeColumnsToContents()
        self._conferir()

    def _conferir(self) -> None:
        """O resumo (os canais, a duração) e o botão: ligado com um canal ao menos e a taxa."""
        if self.lido is None:
            return
        usados = self.usados()
        taxa = self._taxa_dita()
        if taxa is None:
            self.resumo.setText(self.tr("Diga a taxa de amostragem de cada canal."))
            self.importar_botao.setEnabled(False)
            return
        partes = [self.tr("{} canal(is) de {} amostras a {}: {}").format(
            len(usados), self.lido.n_amostras, formatar_si(taxa, "S/s", 4),
            formatar_duracao(self.lido.n_amostras / taxa))]
        partes += list(self.lido.avisos)
        self.resumo.setText(". ".join(partes) + ".")
        self.importar_botao.setEnabled(bool(usados))

    def usados(self) -> list[int]:
        return [i for i in range(self.canais.rowCount()) if self.canais.cellWidget(i, 0).isChecked()]

    def definir_canal(self, i: int, *, unidade: str | None = None, escala: float | None = None,
                      usar: bool | None = None) -> None:
        """Muda a linha ``i`` da tabela dos canais (os testes e a paleta)."""
        if unidade is not None:
            caixa = self.canais.cellWidget(i, 2)
            caixa.setCurrentIndex(caixa.findData(unidade))
        if escala is not None:
            self.canais.cellWidget(i, 3).definir_valor(escala)
        if usar is not None:
            self.canais.cellWidget(i, 0).setChecked(usar)
        self._conferir()

    # ------------------------------------------------------------------ importar

    def pedido(self) -> imp.Importado | None:
        """O que vai ser gravado: os canais usados, com a grandeza, a escala e a taxa da tela."""
        if self.lido is None or self._taxa_dita() is None or not self.usados():
            return None
        usados = self.usados()
        return self.lido.com(taxa_hz=self._taxa_dita(), canais=usados,
                             unidades=[self.canais.cellWidget(i, 2).currentData() for i in usados],
                             escalas=[self.canais.cellWidget(i, 3).valor for i in usados])

    def importar(self):
        """Grava a captura numa tarefa e avisa ``importadaPronta``; devolve a tarefa (ou None)."""
        pedido = self.pedido()
        if pedido is None or self.caminho is None:
            return None
        destino = destino_da_importacao(self.caminho, self.pasta_dos_dados)
        from ...app import versao

        assinatura = f"SH-Analyzer {versao()}"

        def trabalho(_progresso, _cancelado):
            return imp.gravar_como_captura(pedido, destino, versao_codigo=assinatura)

        def terminou(tarefa) -> None:
            if tarefa.estado == "concluida":
                self.importadaPronta.emit(tarefa.resultado)
                self.accept()
            else:
                self._falhou(self.tr("Não foi possível gravar {}: {}").format(destino.name, tarefa.erro))

        self.importar_botao.setEnabled(False)
        self.resumo.setText(self.tr("Gravando {}…").format(destino.name))
        return self.tarefas.iniciar(self.tr("Importar {}").format(self.caminho.name), trabalho, "importar",
                                    ao_terminar=terminou)
