"""A lista de avisos do painel de baixo: os da ``api`` ao abrir uma captura (sonda, faixa, integridade) e os do
projeto (uma captura não achada). Cada aviso tem o nível (ícone e cor) e a origem (o arquivo), e os de uma origem
saem juntos quando ela é fechada."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStackedWidget, QWidget

from ..dados.captura import Aviso
from ..tema.aplicar import aparencia
from ..tema.icones import icone
from ..tema.tokens import Tema
from .painel import EstadoVazio

ICONES = {"info": ("ok", "acento"), "aviso": ("alerta", "aviso"), "erro": ("alerta", "erro")}
ORDEM = ("info", "aviso", "erro")


class ListaDeAvisos(QStackedWidget):
    """``contagemMudou(n, nivel)`` dá quantos avisos há e o nível mais grave (para o contador da aba)."""

    contagemMudou = Signal(int, str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("lista_de_avisos")
        self.vazio = EstadoVazio(self.tr("Nenhum aviso"),
                                 self.tr("Os avisos das capturas abertas (sonda, faixa, integridade) aparecem aqui."),
                                 icone_nome="alerta", compacto=True)
        self.lista = QListWidget()
        self.lista.setObjectName("avisos")
        self.lista.setWordWrap(True)
        self.lista.setAlternatingRowColors(False)
        self.addWidget(self.vazio)
        self.addWidget(self.lista)
        self._avisos: list[tuple[Aviso, str]] = []
        aparencia().mudou.connect(self._tema_mudou)

    @property
    def avisos(self) -> list[tuple[Aviso, str]]:
        """Os avisos, com a origem de cada um, na ordem em que chegaram."""
        return list(self._avisos)

    def adicionar(self, avisos, origem: str = "") -> None:
        for aviso in avisos:
            if aviso.nivel not in ICONES:
                raise ValueError(f"nível de aviso desconhecido: {aviso.nivel!r}")
            self._avisos.append((aviso, origem))
        self._redesenhar()

    def remover_origem(self, origem: str) -> None:
        self._avisos = [(a, o) for a, o in self._avisos if o != origem]
        self._redesenhar()

    def limpar(self) -> None:
        self._avisos = []
        self._redesenhar()

    def _tema_mudou(self, _tema: Tema) -> None:
        self._redesenhar()

    def _redesenhar(self) -> None:
        tema = aparencia().tema
        self.lista.clear()
        for aviso, origem in self._avisos:
            nome_icone, papel = ICONES[aviso.nivel]
            item = QListWidgetItem(icone(nome_icone, getattr(tema, papel)), aviso.texto)
            item.setToolTip(f"{origem}: {aviso.texto}" if origem else aviso.texto)
            self.lista.addItem(item)
        self.setCurrentWidget(self.lista if self._avisos else self.vazio)
        pior = max((ORDEM.index(a.nivel) for a, _ in self._avisos), default=0)
        self.contagemMudou.emit(len(self._avisos), ORDEM[pior])
