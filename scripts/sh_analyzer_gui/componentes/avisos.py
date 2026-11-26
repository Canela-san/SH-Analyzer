"""A lista de avisos do painel de baixo: os da ``api`` ao abrir uma captura (sonda, faixa, integridade) e os do
projeto (uma captura não achada). Cada aviso tem o nível (ícone e cor) e a origem (o arquivo), e os de uma origem
saem juntos quando ela é fechada.

**O contador da aba conta os avisos não vistos:** abrir a aba (ou o painel, com ela na frente) os dá por vistos, e o
contador some; ele volta só com avisos novos, e conta só eles. Um aviso que chega com a lista à vista já entra visto.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStackedWidget, QWidget

from ..dados.avisos import para_a_tela
from ..dados.captura import Aviso
from ..tema.aplicar import aparencia
from ..tema.icones import icone
from ..tema.tokens import Tema
from .numeros import separador_decimal
from .painel import EstadoVazio

ICONES = {"info": ("ok", "acento"), "aviso": ("alerta", "aviso"), "erro": ("alerta", "erro")}
ORDEM = ("info", "aviso", "erro")


class ListaDeAvisos(QStackedWidget):
    """``contagemMudou(n, nivel)`` dá quantos avisos não foram vistos e o mais grave deles (o contador da aba)."""

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
        self._avisos: list[tuple[Aviso, str, int]] = []       # o aviso, a origem e a ordem de chegada
        self._rotulos: dict[str, str] = {}
        self._chegados = 0                # quantos avisos já chegaram (a ordem do próximo)
        self._vistos_ate = 0              # os de ordem menor já foram vistos
        aparencia().mudou.connect(self._tema_mudou)

    @property
    def avisos(self) -> list[tuple[Aviso, str]]:
        """Os avisos, com a origem de cada um, na ordem em que chegaram."""
        return [(a, o) for a, o, _ in self._avisos]

    @property
    def nao_vistos(self) -> int:
        return sum(1 for *_, ordem in self._avisos if ordem >= self._vistos_ate)

    def marcar_como_vistos(self) -> None:
        """Todos os avisos de agora vistos: o contador da aba some."""
        if self._vistos_ate != self._chegados:
            self._vistos_ate = self._chegados
            self._contar()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        self.marcar_como_vistos()           # a aba (ou o painel) abriu: o usuário está vendo a lista

    def adicionar(self, avisos, origem: str = "", rotulo: str = "") -> None:
        """``origem`` agrupa os avisos (para tirá-los juntos); ``rotulo`` (o nome do arquivo) vai na frente do
        texto."""
        avisos = list(avisos)
        for aviso in avisos:
            if aviso.nivel not in ICONES:
                raise ValueError(f"nível de aviso desconhecido: {aviso.nivel!r}")
        if rotulo:
            self._rotulos[origem] = rotulo
        for aviso in avisos:
            self._avisos.append((aviso, origem, self._chegados))
            self._chegados += 1
        if self.isVisible():
            self._vistos_ate = self._chegados
        self._redesenhar()

    def remover_origem(self, origem: str) -> None:
        antes = len(self._avisos)
        self._avisos = [(a, o, n) for a, o, n in self._avisos if o != origem]
        self._rotulos.pop(origem, None)
        if len(self._avisos) != antes:
            self._redesenhar()

    def limpar(self) -> None:
        self._avisos = []
        self._redesenhar()

    def _tema_mudou(self, _tema: Tema) -> None:
        self._redesenhar()

    def _redesenhar(self) -> None:
        tema = aparencia().tema
        self.lista.clear()
        for aviso, origem, _ in self._avisos:
            nome_icone, papel = ICONES[aviso.nivel]
            rotulo = self._rotulos.get(origem, "")
            frase = para_a_tela(aviso, separador_decimal()).texto     # as palavras da interface, não as da CLI
            texto = f"{rotulo}: {frase}" if rotulo else frase
            item = QListWidgetItem(icone(nome_icone, getattr(tema, papel)), texto)
            item.setToolTip(texto)
            self.lista.addItem(item)
        self.setCurrentWidget(self.lista if self._avisos else self.vazio)
        self._contar()

    def _contar(self) -> None:
        novos = [a for a, _, ordem in self._avisos if ordem >= self._vistos_ate]
        pior = max((ORDEM.index(a.nivel) for a in novos), default=0)
        self.contagemMudou.emit(len(novos), ORDEM[pior])
