"""A tabela de medidas do painel de baixo (docs/gui-plan.md, 3.4; o mockup A1): uma linha por traço visível, com a
região (os cursores ou a janela visível), a média, o RMS, o pico, o pico a pico, a fundamental e, com os cursores,
o Δy. Acima dela, o Δt e o 1/Δt dos cursores.

**As vistas de frequência** (o espectro, as bandas, o espectrograma, os harmônicos) mandam as medidas dos cursores
delas como uma :class:`MedidasDaVista` (o resumo, as colunas e uma linha por traço), mostrada pela mesma tabela
(:meth:`TabelaDeMedidas.mostrar_da_vista`): os cursores de todas as vistas leem do mesmo jeito, no mesmo lugar.

**Copiar** (o botão ou Ctrl+C na tabela) põe a tabela na área de transferência em texto separado por tabulação,
com os números completos e a vírgula decimal: cola direto numa planilha em português.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...componentes.basicos import Botao
from ...componentes.numeros import formatar_si
from ...componentes.painel import EstadoVazio
from ...servicos.medidas import MedidaDoTraco, PedidoDeMedida
from ...tema.aplicar import aparencia
from ...tema.icones import icone
from ...tema.tokens import cor_do_traco

COLUNAS = ("Traço", "Região", "Média", "RMS", "Pico", "Pico a pico", "f₁", "Δy")


@dataclass(frozen=True)
class LinhaDaTabela:
    """Uma linha das medidas de uma vista: o traço (o nome e a cor) e os textos das colunas."""

    traco: object
    textos: tuple[str, ...]


@dataclass(frozen=True)
class MedidasDaVista:
    """As medidas que uma vista manda para a tabela (as dos cursores de uma vista de frequência): o resumo de cima,
    as colunas depois de "Traço", uma linha por traço e o texto para a planilha (os números completos)."""

    resumo: str
    colunas: tuple[str, ...] = ()
    linhas: tuple[LinhaDaTabela, ...] = ()
    planilha: str = ""


def numero_para_planilha(valor: float | None) -> str:
    return _numero_para_planilha(valor)


def _numero_para_planilha(valor: float | None) -> str:
    """O número completo, com a vírgula decimal (a planilha em português o lê como número)."""
    if valor is None or not math.isfinite(valor):
        return ""
    return repr(float(valor)).replace(".", ",")


class TabelaDeMedidas(QStackedWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("tabela_de_medidas")
        self.vazio = EstadoVazio(self.tr("Sem medidas"),
                                 self.tr("Plote um canal: as medidas da janela visível aparecem aqui; ligue os "
                                         "cursores (C) para medir entre eles."),
                                 icone_nome="regua", compacto=True)
        conteudo = QWidget()
        coluna = QVBoxLayout(conteudo)
        coluna.setContentsMargins(10, 6, 10, 4)
        coluna.setSpacing(4)
        topo = QHBoxLayout()
        self.resumo = QLabel()
        self.resumo.setObjectName("resumo_medidas")
        topo.addWidget(self.resumo, 1)
        self.botao_copiar = Botao(self.tr("Copiar"), "fantasma", "copiar")
        self.botao_copiar.setToolTip(self.tr("Copiar a tabela para uma planilha (Ctrl+C)"))
        self.botao_copiar.clicked.connect(self.copiar)
        topo.addWidget(self.botao_copiar)
        coluna.addLayout(topo)
        self.tabela = QTableWidget(0, len(COLUNAS))
        self.tabela.setObjectName("medidas")
        self.tabela.setHorizontalHeaderLabels([self.tr(c) for c in COLUNAS])
        self.tabela.verticalHeader().hide()
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setShowGrid(False)
        # A primeira coluna estica; as outras são medidas uma vez, depois de preencher (``ResizeToContents`` mediria
        # a coluna inteira a cada célula: 36 ms para 8 traços, a cada medida).
        self.tabela.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        coluna.addWidget(self.tabela, 1)
        self.addWidget(self.vazio)
        self.addWidget(conteudo)
        self.medidas: list[MedidaDoTraco] = []
        self.pedido: PedidoDeMedida | None = None
        self.da_vista: MedidasDaVista | None = None

    def keyPressEvent(self, evento) -> None:
        if evento.matches(QKeySequence.StandardKey.Copy):
            self.copiar()
            return
        super().keyPressEvent(evento)

    def _colunas(self, colunas) -> None:
        if self.tabela.columnCount() != len(colunas) or \
                [self.tabela.horizontalHeaderItem(i).text() for i in range(len(colunas))] != list(colunas):
            self.tabela.setColumnCount(len(colunas))
            self.tabela.setHorizontalHeaderLabels(list(colunas))
            self.tabela.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

    def _celula_do_traco(self, traco) -> QTableWidgetItem:
        r = traco.receita
        return QTableWidgetItem(icone("pulso", cor_do_traco(r.cor, aparencia().tema)[0], 12), r.nome)

    def mostrar_da_vista(self, medidas: MedidasDaVista | None) -> None:
        """As medidas de uma vista de frequência (os cursores dela); None: nada a medir."""
        self.pedido, self.medidas, self.da_vista = None, [], medidas
        if medidas is None:
            self.setCurrentWidget(self.vazio)
            return
        self.setCurrentIndex(1)
        self.resumo.setText(medidas.resumo)
        self._colunas([self.tr("Traço"), *medidas.colunas])
        self.tabela.setUpdatesEnabled(False)
        self.tabela.setRowCount(len(medidas.linhas))
        for linha, m in enumerate(medidas.linhas):
            self.tabela.setItem(linha, 0, self._celula_do_traco(m.traco))
            for coluna, texto in enumerate(m.textos, start=1):
                item = QTableWidgetItem(texto)
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tabela.setItem(linha, coluna, item)
        for coluna in range(1, len(medidas.colunas) + 1):
            self.tabela.resizeColumnToContents(coluna)
        self.tabela.setUpdatesEnabled(True)

    def mostrar(self, pedido: PedidoDeMedida | None, medidas: list[MedidaDoTraco]) -> None:
        self.pedido, self.medidas, self.da_vista = pedido, list(medidas), None
        if not medidas or pedido is None:
            self.setCurrentWidget(self.vazio)
            return
        self.setCurrentIndex(1)
        self._colunas([self.tr(c) for c in COLUNAS])
        dt = pedido.fim_s - pedido.inicio_s
        if pedido.dos_cursores:
            inverso = formatar_si(1 / dt, "Hz", 5) if dt else "—"
            self.resumo.setText(self.tr("Cursores: {} → {} · Δt {} · 1/Δt {}").format(
                formatar_si(pedido.inicio_s, "s", 7), formatar_si(pedido.fim_s, "s", 7), formatar_si(dt, "s", 5),
                inverso))
        else:
            self.resumo.setText(self.tr("Janela visível: {} → {} · {}").format(
                formatar_si(pedido.inicio_s, "s", 7), formatar_si(pedido.fim_s, "s", 7), formatar_si(dt, "s", 5)))
        t = aparencia().tema
        self.tabela.setUpdatesEnabled(False)
        self.tabela.setRowCount(len(medidas))
        for linha, m in enumerate(medidas):
            self.tabela.setItem(linha, 0, self._celula_do_traco(m.traco))
            regiao = self.tr("cursores") if pedido.dos_cursores else self.tr("janela")
            valores = [regiao]
            if m.medidas is None:
                valores += ["—"] * 5
            else:
                x = m.medidas
                u = m.unidade
                valores += [formatar_si(x.media, u, 4), formatar_si(x.rms, u, 4), formatar_si(x.pico, u, 4),
                            formatar_si(x.pico_a_pico, u, 4),
                            formatar_si(x.f1_hz, "Hz", 6) if x.f1_hz is not None else "—"]
            valores.append(formatar_si(m.delta_y, m.unidade, 4) if m.delta_y is not None else "—")
            for coluna, texto in enumerate(valores, start=1):
                item = QTableWidgetItem(texto)
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if m.erro and coluna > 1:
                    item.setToolTip(m.erro)
                    item.setForeground(QColor(t.mudo))
                elif m.medidas is not None and coluna == 6 and m.medidas.problema_f1:
                    item.setToolTip(m.medidas.problema_f1)
                self.tabela.setItem(linha, coluna, item)
        for coluna in range(1, len(COLUNAS)):
            self.tabela.resizeColumnToContents(coluna)
        self.tabela.setUpdatesEnabled(True)

    def texto_para_planilha(self) -> str:
        """A tabela em texto separado por tabulação, com os números completos (vírgula decimal)."""
        if self.da_vista is not None:
            return self.da_vista.planilha
        cabecalho = ["Traço", "Unidade", "Início (s)", "Fim (s)", "Média", "RMS", "RMS sem DC", "Pico", "Pico a pico",
                     "Mínimo", "Máximo", "f1 (Hz)", "Δy", "Amostras"]
        linhas = ["\t".join(cabecalho)]
        for m in self.medidas:
            x = m.medidas
            campos = [m.traco.nome, m.unidade, _numero_para_planilha(m.inicio_s), _numero_para_planilha(m.fim_s)]
            if x is None:
                campos += [""] * 8
            else:
                campos += [_numero_para_planilha(v) for v in (x.media, x.rms, x.rms_ac, x.pico, x.pico_a_pico,
                                                               x.minimo, x.maximo, x.f1_hz)]
            campos += [_numero_para_planilha(m.delta_y), str(x.n_amostras) if x is not None else ""]
            linhas.append("\t".join(campos))
        return "\n".join(linhas) + "\n"

    def copiar(self) -> None:
        if self.medidas or self.da_vista is not None:
            QApplication.clipboard().setText(self.texto_para_planilha())
