"""Os erros inesperados (docs/gui-plan.md, GE-09): um defeito do aplicativo (uma exceção que ninguém esperava, numa
tarefa, num slot, num evento, noutra thread) vai para o log e para o diálogo de erro inesperado, e o aplicativo segue
aberto.

**Os erros esperados não passam por aqui.** Um ``ErroSHAN`` do motor (um arquivo sem cabeçalho, um corte acima da
Nyquist) e um ``OSError`` (um arquivo que sumiu, um disco cheio) dizem o motivo no lugar certo (o chip do traço, a
vista, o painel de avisos), sem janela no meio do trabalho (8.4).

* **De qualquer thread:** :func:`relatar` registra e avisa o :class:`RelatorDeErros`, que mora na thread da
  interface; quem mostra o diálogo o recebe pela fila de eventos.
* **Os ganchos:** :func:`instalar_ganchos` põe o ``sys.excepthook`` (o PySide6 o chama para uma exceção num slot ou
  num evento, e segue o laço de eventos) e o ``threading.excepthook``. Só no ``main``: nos testes, quem cuida das
  exceções dos slots é o pytest-qt (um erro num slot reprova o teste).
* **Um erro que se repete** (num ``paintEvent``, a cada quadro) não enche o log: a pilha vai inteira na primeira vez
  e, depois, uma linha na 2.ª, na 4.ª, na 8.ª vez... O diálogo conta as vezes.
"""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from types import TracebackType

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ErroInesperado:
    """Uma ocorrência: ``onde`` (a tarefa, a thread), o tipo e a mensagem da exceção e a pilha (o texto do
    ``traceback``). ``assinatura`` é o tipo e os quadros da pilha, sem a mensagem: o mesmo defeito com outros números
    na mensagem é o mesmo erro."""

    onde: str
    tipo: str
    mensagem: str
    pilha: str
    assinatura: tuple
    quando: datetime = field(default_factory=datetime.now)

    @property
    def resumo(self) -> str:
        return f"{self.tipo}: {self.mensagem}" if self.mensagem else self.tipo


def _descrever(excecao: BaseException, pilha: TracebackType | None, onde: str) -> ErroInesperado:
    quadros = tuple((q.filename, q.lineno, q.name) for q in traceback.extract_tb(pilha))
    tipo = type(excecao).__qualname__
    texto = "".join(traceback.format_exception(type(excecao), excecao, pilha))
    return ErroInesperado(onde, tipo, str(excecao), texto, (tipo, quadros))


class RelatorDeErros(QObject):
    """``erroInesperado(ErroInesperado)`` sai a cada ocorrência, na thread da interface (pela fila de eventos se o
    erro foi noutra thread)."""

    erroInesperado = Signal(object)


_relator: RelatorDeErros | None = None
_vezes: dict[tuple, int] = {}
_trava = threading.Lock()


def relator() -> RelatorDeErros:
    """O relator do processo. **Crie-o na thread da interface** (a janela e o ``main`` o pedem ao abrir): um
    ``QObject`` criado numa thread de trabalho moraria nela."""
    global _relator
    if _relator is None:
        _relator = RelatorDeErros()
    return _relator


def relatar(excecao: BaseException, onde: str = "", pilha: TracebackType | None = None) -> ErroInesperado:
    """Registra um erro inesperado e avisa o relator (se a interface já o criou). De qualquer thread."""
    pilha = pilha if pilha is not None else excecao.__traceback__
    erro = _descrever(excecao, pilha, onde)
    with _trava:
        vezes = _vezes[erro.assinatura] = _vezes.get(erro.assinatura, 0) + 1
    entre = f" ({onde})" if onde else ""
    if vezes == 1:
        log.error("erro inesperado%s", entre, exc_info=(type(excecao), excecao, pilha))
    elif vezes & (vezes - 1) == 0:                 # uma potência de 2
        log.error("o mesmo erro inesperado%s, %dª vez: %s", entre, vezes, erro.resumo)
    if _relator is not None:
        _relator.erroInesperado.emit(erro)
    return erro


def instalar_ganchos() -> Callable[[], None]:
    """Põe os ganchos do ``sys`` e do ``threading``; devolve o que os tira (voltam os de antes). Chame na thread da
    interface, depois de criar a ``QApplication``."""
    relator()
    sys_antes, thread_antes = sys.excepthook, threading.excepthook

    def gancho(tipo, valor, pilha) -> None:
        if issubclass(tipo, KeyboardInterrupt):        # o Ctrl+C no terminal sai como sempre
            sys_antes(tipo, valor, pilha)
            return
        relatar(valor, "na thread da interface", pilha)

    def gancho_da_thread(args) -> None:
        if args.exc_type is SystemExit:
            return
        nome = args.thread.name if args.thread is not None else "?"
        relatar(args.exc_value, f"na thread {nome}", args.exc_traceback)

    sys.excepthook, threading.excepthook = gancho, gancho_da_thread

    def tirar() -> None:
        sys.excepthook, threading.excepthook = sys_antes, thread_antes

    return tirar
