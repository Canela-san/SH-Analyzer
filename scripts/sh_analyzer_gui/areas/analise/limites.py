"""O editor das curvas de limite das bandas (``dados/limites.py``): a lista das curvas da pasta, os pontos de cada
uma (digitados ou colados de uma planilha), a grandeza, a fonte dos valores e a prévia em log f.

O programa não traz os valores das normas (são publicações pagas): o aviso no topo diz isso, e a fonte de cada
curva fica gravada com ela para quem lê o projeto saber de onde vêm os números.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...componentes.basicos import Botao
from ...componentes.numeros import NumeroInvalido, decimal, ler_numero
from ...dados import limites as lim
from ...graficos.faixa import EixoDoTema
from ...tema.aplicar import aparencia

NOME_NOVO = "Nova curva"


class DialogoDosLimites(QDialog):
    """``curvasMudaram`` sai a cada curva gravada ou apagada (a vista refaz a lista dela)."""

    curvasMudaram = Signal()

    def __init__(self, pasta: Path, parent: QWidget | None = None, *, escolhida: lim.CurvaLimite | None = None):
        super().__init__(parent)
        self.setObjectName("dialogo_dos_limites")
        self.setWindowTitle(self.tr("Curvas de limite"))
        self.resize(820, 520)
        self.pasta = Path(pasta)
        self._caminho: Path | None = None           # o arquivo da curva aberta (None: nova, ainda não gravada)

        aviso = QLabel(self.tr("O SH-Analyzer não traz os valores das normas (IEC 61000-2-2, IEC 61000-2-12, CISPR, "
                               "EN 50065-1): são publicações pagas. Digite os pontos da sua cópia, ou cole de uma "
                               "planilha (frequência e nível por linha), e diga na fonte a norma, a edição e a tabela."))
        aviso.setWordWrap(True)
        aviso.setObjectName("subtitulo_inspetor")

        self.lista = QListWidget()
        self.lista.setObjectName("lista_de_limites")
        self.lista.currentItemChanged.connect(self._escolhida_na_lista)
        nova = Botao(self.tr("Nova"), "secundario", "mais")
        nova.clicked.connect(self.nova)
        duplicar = Botao(self.tr("Duplicar"), "fantasma")
        duplicar.clicked.connect(self.duplicar)
        self.apagar_botao = Botao(self.tr("Apagar"), "perigo")
        self.apagar_botao.clicked.connect(lambda: self.apagar())
        botoes_da_lista = QHBoxLayout()
        for b in (nova, duplicar, self.apagar_botao):
            botoes_da_lista.addWidget(b)
        esquerda = QWidget()
        coluna_esquerda = QVBoxLayout(esquerda)
        coluna_esquerda.setContentsMargins(0, 0, 0, 0)
        coluna_esquerda.addWidget(self.lista, 1)
        coluna_esquerda.addLayout(botoes_da_lista)

        self.nome = QLineEdit()
        self.nome.setObjectName("nome_do_limite")
        self.grandeza = QComboBox()
        self.grandeza.setObjectName("grandeza_do_limite")
        self.grandeza.addItem(self.tr("Tensão (dBµV)"), "tensao")
        self.grandeza.addItem(self.tr("Corrente (dBµA)"), "corrente")
        self.fonte = QLineEdit()
        self.fonte.setObjectName("fonte_do_limite")
        self.fonte.setPlaceholderText(self.tr("a norma, a edição e a tabela de onde vêm os valores"))
        forma = QFormLayout()
        forma.addRow(self.tr("Nome"), self.nome)
        forma.addRow(self.tr("Grandeza"), self.grandeza)
        forma.addRow(self.tr("Fonte"), self.fonte)

        self.pontos = QTableWidget(0, 2)
        self.pontos.setObjectName("pontos_do_limite")
        self.pontos.setHorizontalHeaderLabels([self.tr("frequência (Hz)"), self.tr("nível (dB)")])
        self.pontos.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.pontos.verticalHeader().hide()
        self.pontos.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.pontos.itemChanged.connect(lambda _item: self._previa())
        mais = Botao(self.tr("Ponto"), "fantasma", "mais")
        mais.setToolTip(self.tr("Um ponto depois do selecionado"))
        mais.clicked.connect(self._mais_um_ponto)
        menos = Botao(self.tr("Tirar"), "fantasma")
        menos.setToolTip(self.tr("Tira os pontos selecionados"))
        menos.clicked.connect(self._tirar_pontos)
        colar = Botao(self.tr("Colar da planilha"), "fantasma", "copiar")
        colar.setObjectName("colar_pontos")
        colar.setToolTip(self.tr("Troca os pontos pelos da área de transferência: uma linha por ponto, a frequência e "
                                 "o nível separados por tabulação, ponto e vírgula ou espaço (9k vale 9000)"))
        colar.clicked.connect(lambda: self.colar())
        botoes_dos_pontos = QHBoxLayout()
        for b in (mais, menos, colar):
            botoes_dos_pontos.addWidget(b)
        botoes_dos_pontos.addStretch(1)

        self.grafico = pg.PlotWidget(axisItems={"bottom": EixoDoTema("bottom"), "left": EixoDoTema("left")})
        self.grafico.setObjectName("previa_do_limite")
        self.grafico.setMenuEnabled(False)
        self.grafico.hideButtons()
        self.grafico.setLogMode(x=True, y=False)
        self.grafico.setLabel("bottom", self.tr("frequência"), units="Hz")
        self.grafico.setLabel("left", self.tr("nível (dB)"))
        self.grafico.setMinimumHeight(150)
        self.curva = self.grafico.plot([], [])
        self.marcas = self.grafico.plot([], [], pen=None, symbol="o", symbolSize=6)   # o PlotDataItem segue o log

        self.estado = QLabel()
        self.estado.setObjectName("estado_do_limite")
        self.estado.setWordWrap(True)
        self.salvar_botao = Botao(self.tr("Salvar"), "primario")
        self.salvar_botao.setObjectName("salvar_limite")
        self.salvar_botao.clicked.connect(lambda: self.salvar())
        fechar = Botao(self.tr("Fechar"), "secundario")
        fechar.clicked.connect(self.accept)
        rodape = QHBoxLayout()
        rodape.addWidget(self.estado, 1)
        rodape.addWidget(self.salvar_botao)
        rodape.addWidget(fechar)

        direita = QWidget()
        coluna_direita = QVBoxLayout(direita)
        coluna_direita.setContentsMargins(0, 0, 0, 0)
        coluna_direita.addLayout(forma)
        coluna_direita.addWidget(self.pontos, 1)
        coluna_direita.addLayout(botoes_dos_pontos)
        coluna_direita.addWidget(self.grafico, 1)

        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.addWidget(esquerda)
        divisor.addWidget(direita)
        divisor.setSizes([240, 580])
        coluna = QVBoxLayout(self)
        coluna.addWidget(aviso)
        coluna.addWidget(divisor, 1)
        coluna.addLayout(rodape)

        aparencia().mudou.connect(self._tema_mudou)
        self._tema_mudou(aparencia().tema)
        self.recarregar(escolhida)
        if self.lista.count() == 0:
            self.nova()

    # ------------------------------------------------------------------ a lista

    def recarregar(self, escolher: lim.CurvaLimite | Path | None = None) -> None:
        self.lista.blockSignals(True)
        self.lista.clear()
        for caminho, curva in lim.curvas(self.pasta):
            item = QListWidgetItem(curva.nome)
            item.setData(Qt.ItemDataRole.UserRole, (caminho, curva))
            item.setToolTip(lim.resumo(curva) + (f"\n{curva.fonte}" if curva.fonte else ""))
            self.lista.addItem(item)
        self.lista.blockSignals(False)
        alvo = 0
        for k in range(self.lista.count()):
            caminho, curva = self.lista.item(k).data(Qt.ItemDataRole.UserRole)
            if escolher is not None and (caminho == escolher or curva == escolher or
                                         (isinstance(escolher, lim.CurvaLimite) and curva.nome == escolher.nome)):
                alvo = k
        if self.lista.count():
            self.lista.setCurrentRow(alvo)
            self._escolhida_na_lista(self.lista.currentItem(), None)
        self.apagar_botao.setEnabled(self.lista.count() > 0)

    def _escolhida_na_lista(self, item, _antes) -> None:
        if item is None:
            return
        caminho, curva = item.data(Qt.ItemDataRole.UserRole)
        self._caminho = caminho
        self.carregar(curva)

    def nova(self) -> None:
        self.lista.clearSelection()
        self._caminho = None
        self.nome.setText(self.tr(NOME_NOVO))
        self.fonte.clear()
        self.grandeza.setCurrentIndex(0)
        self._pontos_na_tabela(())
        self.estado.setText(self.tr("Digite ou cole os pontos e salve."))
        self.nome.setFocus()
        self.nome.selectAll()

    def duplicar(self) -> None:
        try:
            curva = self.curva_do_formulario()
        except lim.LimiteInvalido as e:
            self.estado.setText(str(e))
            return
        self._caminho = None
        self.lista.clearSelection()
        self.nome.setText(self.tr("{} (cópia)").format(curva.nome))
        self.estado.setText(self.tr("Uma cópia, ainda não salva."))

    def apagar(self, *, perguntar: bool = True) -> bool:
        if self._caminho is None:
            self.nova()
            return False
        if perguntar and QMessageBox.question(
                self, self.tr("Apagar a curva"),
                self.tr("Apagar a curva \"{}\" ({})? Os projetos que a usam guardam uma cópia dela.").format(
                    self.nome.text(), self._caminho.name)) != QMessageBox.StandardButton.Yes:
            return False
        self._caminho.unlink(missing_ok=True)
        self._caminho = None
        self.recarregar()
        if self.lista.count() == 0:
            self.nova()
        self.curvasMudaram.emit()
        return True

    # ------------------------------------------------------------------ a curva aberta

    def carregar(self, curva: lim.CurvaLimite) -> None:
        self.nome.setText(curva.nome)
        self.fonte.setText(curva.fonte)
        self.grandeza.setCurrentIndex(max(self.grandeza.findData(curva.grandeza), 0))
        self._pontos_na_tabela(curva.pontos)
        self.estado.setText(lim.resumo(curva) if curva.fonte else
                            self.tr("{} · sem a fonte dos valores").format(lim.resumo(curva)))

    def _pontos_na_tabela(self, pontos) -> None:
        self.pontos.blockSignals(True)
        self.pontos.setRowCount(len(pontos))
        for k, (f, n) in enumerate(pontos):
            self.pontos.setItem(k, 0, QTableWidgetItem(decimal(f"{f:g}")))
            self.pontos.setItem(k, 1, QTableWidgetItem(decimal(f"{n:g}")))
        self.pontos.blockSignals(False)
        self._previa()

    def pontos_da_tabela(self) -> tuple[tuple[float, float], ...]:
        pontos = []
        for k in range(self.pontos.rowCount()):
            textos = [(self.pontos.item(k, c).text().strip() if self.pontos.item(k, c) else "") for c in (0, 1)]
            if not any(textos):
                continue
            try:
                pontos.append((ler_numero(textos[0], "Hz"), ler_numero(textos[1])))
            except NumeroInvalido as e:
                raise lim.LimiteInvalido(self.tr("linha {}: {}").format(k + 1, e)) from None
        return tuple(pontos)

    def curva_do_formulario(self) -> lim.CurvaLimite:
        return lim.CurvaLimite(self.nome.text(), self.pontos_da_tabela(), self.grandeza.currentData(),
                               self.fonte.text())

    def _mais_um_ponto(self) -> None:
        linha = self.pontos.currentRow() + 1 if self.pontos.currentRow() >= 0 else self.pontos.rowCount()
        self.pontos.insertRow(linha)
        self.pontos.setCurrentCell(linha, 0)
        self.pontos.editItem(self.pontos.item(linha, 0) or self._item_novo(linha))

    def _item_novo(self, linha: int) -> QTableWidgetItem:
        item = QTableWidgetItem("")
        self.pontos.setItem(linha, 0, item)
        return item

    def _tirar_pontos(self) -> None:
        for linha in sorted({i.row() for i in self.pontos.selectedIndexes()}, reverse=True):
            self.pontos.removeRow(linha)
        self._previa()

    def colar(self, texto: str | None = None) -> int:
        """Troca os pontos pelos do texto (a área de transferência, sem ``texto``); devolve quantos entraram."""
        texto = QApplication.clipboard().text() if texto is None else texto
        pontos = lim.pontos_do_texto(texto)
        if not pontos:
            self.estado.setText(self.tr("Nada a colar: uma linha por ponto, a frequência e o nível."))
            return 0
        self._pontos_na_tabela(sorted(pontos, key=lambda p: p[0]))
        self.estado.setText(self.tr("{} pontos colados; confira e salve.").format(len(pontos)))
        return len(pontos)

    def _previa(self) -> None:
        try:
            curva = self.curva_do_formulario()
        except lim.LimiteInvalido as e:
            self.curva.setData([], [])
            self.marcas.setData([], [])
            if self.pontos.rowCount():
                self.estado.setText(str(e))
            return
        f0, f1 = curva.faixa_hz
        f = np.geomspace(f0, f1, 300) if f1 > f0 else np.array([f0])
        self.curva.setData(f, curva.em(f))
        self.marcas.setData([p[0] for p in curva.pontos], [p[1] for p in curva.pontos])
        self.salvar_botao.setEnabled(True)

    def salvar(self) -> Path | None:
        try:
            curva = self.curva_do_formulario()
        except lim.LimiteInvalido as e:
            self.estado.setText(str(e))
            return None
        try:
            destino = lim.salvar(curva, self.pasta, substituir=self._caminho)
        except OSError as e:
            self.estado.setText(self.tr("Não deu para gravar: {}").format(e))
            return None
        self._caminho = destino
        self.recarregar(destino)
        self.estado.setText(self.tr("Salva em {}").format(destino.name))
        self.curvasMudaram.emit()
        return destino

    def _tema_mudou(self, t) -> None:
        self.grafico.setBackground(QColor(t.afundada))
        self.curva.setPen(pg.mkPen(t.aviso, width=2))
        self.marcas.setSymbolBrush(QColor(t.aviso))
        self.marcas.setSymbolPen(pg.mkPen(t.afundada, width=1))
