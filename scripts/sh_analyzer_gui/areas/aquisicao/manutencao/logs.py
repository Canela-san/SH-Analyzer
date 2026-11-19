"""A página Logs da Manutenção (a F6.6): o kernel e o diário do systemd da placa, "o que importa" (a PRU, os pinos, o
firmware, o ``ler_adc``, o USB, o cartão e os erros) ou tudo; o nível, a origem e a busca filtram aqui mesmo; "Ao
vivo" acrescenta cada linha nova que chega; "Salvar…" grava o que está à vista num arquivo de texto e "Para o
caderno" o põe no caderno da sessão (as últimas :data:`LINHAS_NO_CADERNO`).
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ....componentes.basicos import Botao, Segmentado
from ....servicos.monitor_da_placa import MonitorDaPlaca
from ....tema.aplicar import aparencia
from ..pecas import fonte
from ..textos import frase, traduzir
from .comuns import texto

LINHAS_GUARDADAS = 5000
LINHAS_NO_CADERNO = 60
NOMES_DOS_NIVEIS = {0: "emerg", 1: "alerta", 2: "crítico", 3: "erro", 4: "aviso", 5: "nota", 6: "info", 7: "debug"}
NIVEIS = (("todos", "Todos os níveis", 7), ("avisos", "Avisos e erros", 4), ("erros", "Só erros", 3))
ORIGENS = (("tudo", "Kernel e sistema"), ("kernel", "Só o kernel"), ("sistema", "Só o sistema"))


def hora(utc: float | None) -> str:
    return time.strftime("%d/%m %H:%M:%S", time.localtime(utc)) if utc else "—"


def linha_em_texto(linha) -> str:
    """Uma linha de log como texto (o arquivo salvo, o caderno)."""
    nivel = NOMES_DOS_NIVEIS.get(linha.nivel, "") if linha.nivel is not None else ""
    return f"{hora(linha.utc)}  {nivel:7s}  {linha.origem or '':14s}  {linha.texto}"


class PaginaDosLogs(QWidget):
    """A página Logs. ``paraOCaderno(texto)`` manda as linhas à vista para o caderno da sessão (a área o liga)."""

    paraOCaderno = Signal(str)

    def __init__(self, monitor: MonitorDaPlaca, dialogos_de=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("pagina_dos_logs")
        self.monitor, self.dialogos_de = monitor, dialogos_de
        self.linhas: list = []                    # as lidas e as que chegaram ao vivo, em ordem
        self.visiveis: list = []
        self.titulo = QLabel(traduzir("Logs"))
        self.titulo.setFont(fonte("tela", QFont.Weight.DemiBold))
        self.subtitulo = texto("", "subtitulo_da_secao")
        self.ler_de_novo = Botao(traduzir("Ler de novo"), "secundario", "girar")
        self.ler_de_novo.setObjectName("ler_os_logs_de_novo")
        self.ler_de_novo.clicked.connect(lambda: monitor.ler_logs())
        cabecalho = QHBoxLayout()
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(self.titulo)
        textos.addWidget(self.subtitulo)
        cabecalho.addLayout(textos, 1)
        cabecalho.addWidget(self.ler_de_novo, 0, Qt.AlignmentFlag.AlignTop)

        # os filtros
        self.escopo = Segmentado([traduzir("O que importa"), traduzir("Tudo")])
        self.escopo.setProperty("compacto", True)
        self.escopo.setToolTip(traduzir("O que importa: a PRU, os pinos, o firmware, o ler_adc, o USB, o cartão e os "
                                        "erros. Tudo: as últimas mil linhas do kernel e do sistema."))
        self.escopo.escolhaMudou.connect(lambda i: monitor.ler_logs(todos=i == 1))
        self.nivel = QComboBox()
        self.nivel.setObjectName("nivel_dos_logs")
        for _chave, titulo, _n in NIVEIS:
            self.nivel.addItem(traduzir(titulo))
        self.nivel.currentIndexChanged.connect(lambda _i: self.filtrar())
        self.origem = QComboBox()
        self.origem.setObjectName("origem_dos_logs")
        for _chave, titulo in ORIGENS:
            self.origem.addItem(traduzir(titulo))
        self.origem.currentIndexChanged.connect(lambda _i: self.filtrar())
        self.busca = QLineEdit()
        self.busca.setObjectName("busca_nos_logs")
        self.busca.setPlaceholderText(traduzir("Buscar (remoteproc, usb, mmc…)"))
        self.busca.setClearButtonEnabled(True)
        self.busca.textChanged.connect(lambda _t: self.filtrar())
        self.ao_vivo = Botao(traduzir("Ao vivo"), "secundario", "play")
        self.ao_vivo.setObjectName("logs_ao_vivo")
        self.ao_vivo.setCheckable(True)
        self.ao_vivo.toggled.connect(self._ao_vivo)
        filtros = QHBoxLayout()
        filtros.setSpacing(8)
        filtros.addWidget(self.escopo)
        filtros.addWidget(self.nivel)
        filtros.addWidget(self.origem)
        filtros.addWidget(self.busca, 1)
        filtros.addWidget(self.ao_vivo)

        # a tabela
        self.tabela = QTableWidget(0, 4)
        self.tabela.setObjectName("tabela_dos_logs")
        self.tabela.setHorizontalHeaderLabels([traduzir("Hora"), traduzir("Nível"), traduzir("Origem"),
                                               traduzir("Mensagem")])
        self.tabela.verticalHeader().hide()
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setShowGrid(False)
        self.tabela.setWordWrap(False)
        topo_da_tabela = self.tabela.horizontalHeader()
        for coluna in range(3):
            topo_da_tabela.setSectionResizeMode(coluna, QHeaderView.ResizeMode.ResizeToContents)
        topo_da_tabela.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        # o rodapé
        self.contagem = texto("", "texto_mudo")
        self.salvar = Botao(traduzir("Salvar…"), "secundario", "baixar")
        self.salvar.setObjectName("salvar_os_logs")
        self.salvar.clicked.connect(self._salvar)
        self.caderno = Botao(traduzir("Para o caderno"), "secundario", "livro")
        self.caderno.setObjectName("logs_para_o_caderno")
        self.caderno.setToolTip(traduzir("As últimas {} linhas à vista vão para o caderno da sessão.").format(
            LINHAS_NO_CADERNO))
        self.caderno.clicked.connect(self._para_o_caderno)
        rodape = QHBoxLayout()
        rodape.addWidget(self.contagem, 1)
        rodape.addWidget(self.salvar)
        rodape.addWidget(self.caderno)

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(24, 20, 24, 16)
        coluna.setSpacing(12)
        coluna.addLayout(cabecalho)
        coluna.addLayout(filtros)
        coluna.addWidget(self.tabela, 1)
        coluna.addLayout(rodape)
        monitor.logsMudaram.connect(self._logs_mudaram)
        monitor.linhaAoVivo.connect(self._linha_nova)
        monitor.aoVivoMudou.connect(self._ao_vivo_mudou)
        aparencia().mudou.connect(self._tema_mudou)
        self._logs_mudaram()

    # ------------------------------------------------------------------ à vista

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        if self.monitor.logs is None and not self.monitor.lendo_logs:
            self.monitor.ler_logs()
        if self.ao_vivo.isChecked():
            self.monitor.ligar_ao_vivo(True)

    def hideEvent(self, evento) -> None:
        super().hideEvent(evento)
        self.monitor.ligar_ao_vivo(False)          # o journalctl -f só roda com a página à vista

    def _ao_vivo(self, ligado: bool) -> None:
        if self.isVisible():
            self.monitor.ligar_ao_vivo(ligado)

    def _ao_vivo_mudou(self) -> None:
        m = self.monitor
        if m.erro_do_ao_vivo and self.ao_vivo.isChecked():
            self.ao_vivo.blockSignals(True)
            self.ao_vivo.setChecked(False)
            self.ao_vivo.blockSignals(False)
        self._subtitulo()

    def _subtitulo(self) -> None:
        m = self.monitor
        if m.lendo_logs:
            texto_ = traduzir("Lendo os logs da placa…")
        elif m.erro_dos_logs:
            texto_ = frase(m.erro_dos_logs)
        elif m.logs is None:
            texto_ = ""
        else:
            sem = [nome for nome, parte in ((traduzir("o kernel"), m.logs.kernel), (traduzir("o diário"), m.logs.diario))
                   if parte is None]
            texto_ = traduzir("O kernel e o diário do systemd deste boot.") + (
                " " + traduzir("A placa não deixou ler {}.").format(" nem ".join(sem)) if sem else "")
        if m.ao_vivo:
            texto_ += " " + traduzir("Ao vivo: as linhas novas entram no fim.")
        elif m.erro_do_ao_vivo:
            texto_ += " " + traduzir("O ao vivo parou: {}").format(frase(m.erro_do_ao_vivo))
        self.subtitulo.setText(texto_.strip())

    def _logs_mudaram(self) -> None:
        m = self.monitor
        self.ler_de_novo.setEnabled(not m.lendo_logs)
        self.escopo.blockSignals(True)
        self.escopo.escolher(1 if m.todos else 0)
        self.escopo.blockSignals(False)
        if m.logs is not None and not m.lendo_logs:
            self.linhas = m.logs.todas()
            self.filtrar()
        elif m.logs is None:
            self.linhas = []
            self.filtrar()
        self._subtitulo()

    def _linha_nova(self, linha) -> None:
        self.linhas.append(linha)
        if len(self.linhas) > LINHAS_GUARDADAS:
            del self.linhas[:len(self.linhas) - LINHAS_GUARDADAS]
            self.filtrar()
            return
        if self._passa(linha):
            barra = self.tabela.verticalScrollBar()
            no_fim = barra.value() >= barra.maximum() - 2
            self.visiveis.append(linha)
            self._acrescentar(linha)
            self._contar()
            if no_fim:
                self.tabela.scrollToBottom()

    # ------------------------------------------------------------------ os filtros

    def _passa(self, linha) -> bool:
        maximo = NIVEIS[self.nivel.currentIndex()][2]
        if maximo < 7 and (linha.nivel is None or linha.nivel > maximo):
            return False
        origem = ORIGENS[self.origem.currentIndex()][0]
        if origem == "kernel" and linha.origem != "kernel":
            return False
        if origem == "sistema" and linha.origem == "kernel":
            return False
        busca = self.busca.text().strip().lower()
        return not busca or busca in f"{linha.texto} {linha.origem or ''}".lower()

    def filtrar(self) -> None:
        self.visiveis = [linha for linha in self.linhas if self._passa(linha)]
        self.tabela.setRowCount(0)
        self.tabela.setUpdatesEnabled(False)
        for linha in self.visiveis:
            self._acrescentar(linha)
        self.tabela.setUpdatesEnabled(True)
        self.tabela.scrollToBottom()
        self._contar()

    def _acrescentar(self, linha) -> None:
        tema = aparencia().tema
        i = self.tabela.rowCount()
        self.tabela.insertRow(i)
        nivel = NOMES_DOS_NIVEIS.get(linha.nivel, "") if linha.nivel is not None else ""
        for j, valor in enumerate((hora(linha.utc), traduzir(nivel), linha.origem or "", linha.texto)):
            item = QTableWidgetItem(valor)
            if j == 1 and linha.nivel is not None and linha.nivel <= 4:
                item.setForeground(QColor(tema.erro if linha.nivel <= 3 else tema.aviso))
            if j == 3:
                item.setToolTip(linha.texto)
            self.tabela.setItem(i, j, item)

    def _tema_mudou(self, _tema) -> None:
        if self.visiveis:
            self.filtrar()

    def _contar(self) -> None:
        n, total = len(self.visiveis), len(self.linhas)
        self.contagem.setText(traduzir("{} linha(s)").format(n) + (traduzir(" de {}").format(total) if n != total
                                                                    else ""))
        self.salvar.setEnabled(bool(n))
        self.caderno.setEnabled(bool(n))

    # ------------------------------------------------------------------ salvar e o caderno

    def texto_a_vista(self, ultimas: int | None = None) -> str:
        linhas = self.visiveis if ultimas is None else self.visiveis[-ultimas:]
        return "\n".join(linha_em_texto(linha) for linha in linhas)

    def _salvar(self) -> Path | None:
        if self.dialogos_de is None or not self.visiveis:
            return None
        sugestao = time.strftime("logs-da-placa-%Y%m%d-%H%M%S.txt")
        caminho = self.dialogos_de().salvar_arquivo(traduzir("Salvar os logs da placa"),
                                                    traduzir("Texto (*.txt *.log)"), sugestao)
        if caminho is None:
            return None
        Path(caminho).write_text(self.texto_a_vista() + "\n", encoding="utf-8")
        self.contagem.setText(traduzir("{} linha(s) salvas em {}").format(len(self.visiveis), caminho))
        return Path(caminho)

    def _para_o_caderno(self) -> None:
        if not self.visiveis:
            return
        filtros = [traduzir("tudo") if self.monitor.todos else traduzir("o que importa"),
                   traduzir(NIVEIS[self.nivel.currentIndex()][1]).lower(),
                   traduzir(ORIGENS[self.origem.currentIndex()][1]).lower()]
        if self.busca.text().strip():
            filtros.append(traduzir("“{}”").format(self.busca.text().strip()))
        n = min(LINHAS_NO_CADERNO, len(self.visiveis))
        self.paraOCaderno.emit(traduzir("Logs da placa ({}; as últimas {} de {} linha(s)):").format(
            ", ".join(filtros), n, len(self.visiveis)) + "\n```\n" + self.texto_a_vista(n) + "\n```")
