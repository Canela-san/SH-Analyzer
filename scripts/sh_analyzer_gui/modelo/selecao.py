"""A seleção: os traços em que o usuário clicou (no gráfico, na legenda ou na árvore). O inspetor mostra o que está
selecionado; ``Del`` remove os selecionados.

Não entra no desfazer (selecionar não muda o projeto), mas segue o projeto: um traço que sai de uma vista, ou cuja
vista sai do projeto, sai da seleção.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QObject, Signal

from .objetos import Projeto, Traco, Vista


class Selecao(QObject):
    """``mudou(tracos)`` sai a cada mudança, com a tupla dos selecionados na ordem em que entraram."""

    mudou = Signal(object)

    def __init__(self, projeto: Projeto, parent: QObject | None = None):
        super().__init__(parent)
        self._tracos: list[Traco] = []
        projeto.tracoSaiu.connect(self._traco_saiu)
        projeto.vistaSaiu.connect(self._vista_saiu)

    @property
    def tracos(self) -> tuple[Traco, ...]:
        return tuple(self._tracos)

    def __contains__(self, traco: Traco) -> bool:
        return traco in self._tracos

    def definir(self, tracos: Iterable[Traco]) -> None:
        """Seleciona só ``tracos`` (sem repetir)."""
        novos = list(dict.fromkeys(tracos))
        if novos != self._tracos:
            self._tracos = novos
            self.mudou.emit(self.tracos)

    def somar(self, traco: Traco) -> None:
        """Ctrl + clique: soma à seleção."""
        if traco not in self._tracos:
            self.definir([*self._tracos, traco])

    def alternar(self, traco: Traco) -> None:
        self.definir([t for t in self._tracos if t is not traco] if traco in self._tracos else [*self._tracos, traco])

    def limpar(self) -> None:
        self.definir([])

    def _traco_saiu(self, _vista: Vista, traco: Traco, _indice: int) -> None:
        if traco in self._tracos:
            self.definir([t for t in self._tracos if t is not traco])

    def _vista_saiu(self, vista: Vista, _indice: int) -> None:
        dela = set(vista.tracos)
        if any(t in dela for t in self._tracos):
            self.definir([t for t in self._tracos if t not in dela])
