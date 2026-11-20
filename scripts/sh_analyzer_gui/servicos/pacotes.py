"""O serviço dos pacotes ``.zpaq.tar`` (F7.10, PD-04): a extração para o cache numa tarefa (com o progresso e o
cancelamento da barra de tarefas), e o cache que as Configurações mostram e limpam. As contas são as de
``dados/pacotes.py``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import supraharmonicos.api as api
from PySide6.QtCore import QObject

from ..dados.pacotes import CacheDePacotes
from .tarefas import GerenciadorDeTarefas, Tarefa


class ServicoDePacotes(QObject):
    def __init__(self, tarefas: GerenciadorDeTarefas, cache: CacheDePacotes | None = None,
                 abertas: Callable[[], set[Path]] | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.tarefas = tarefas
        self.cache = cache or CacheDePacotes()
        self._abertas = abertas or (lambda: set())

    def definir_cache(self, pasta: Path, limite_bytes: int) -> None:
        if Path(pasta) != self.cache.pasta:
            self.cache = CacheDePacotes(pasta, limite_bytes)
        else:
            self.cache.limite_bytes = limite_bytes
        self.cache.aparar(manter=self._abertas())

    def limpar_cache(self) -> int:
        """Apaga as capturas extraídas, menos as abertas no projeto; devolve os bytes liberados."""
        return self.cache.limpar(manter=self._abertas())

    def abrir(self, caminho: Path, ao_terminar: Callable[[list[Path] | None, str], None]) -> Tarefa:
        """Extrai (ou acha no cache) as capturas do pacote numa tarefa; ``ao_terminar(capturas, erro)`` vem na
        thread da interface (``capturas`` None num erro ou num cancelamento; ``erro`` vazio no cancelamento)."""
        cache = self.cache

        def trabalho(progresso, cancelado):
            try:
                return cache.extrair(caminho, progresso=progresso, cancelado=cancelado), ""
            except api.ErroSHAN as e:
                return None, str(e)
            except OSError as e:
                return None, f"{e.strerror or e}"

        def terminou(tarefa: Tarefa) -> None:
            if tarefa.estado == "concluida":
                ao_terminar(*tarefa.resultado)
            elif tarefa.estado == "falhou":
                ao_terminar(None, tarefa.erro)
            else:
                ao_terminar(None, "")

        return self.tarefas.iniciar(self.tr("Extraindo {}").format(Path(caminho).name), trabalho,
                                    f"pacote-{Path(caminho).name}", pesada=True, ao_terminar=terminou)
