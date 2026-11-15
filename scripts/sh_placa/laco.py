"""O laço ``asyncio`` do ``sh_placa`` numa thread só dele (docs/gui-plan.md, 8.3).

Toda a rede da placa (o SSH, o SFTP, a saída contínua do ``ler_adc``, o mDNS) é ``async`` e roda aqui, fora da
thread de quem chama: a interface não espera a rede, e o ``sh_placa`` não sabe do Qt. O ``QtAsyncio`` do PySide6
ainda é prévia técnica, e o ``qasync`` acopla os dois laços; uma thread dedicada é o desenho mais simples.

**O contrato:** :meth:`LacoAsyncio.submeter` agenda ``funcao(*args)`` (uma função ``async``) no laço e devolve uma
:class:`Execucao`. Ela é como um ``concurrent.futures.Future``, com uma diferença que importa para a placa: **o fim
só chega quando a corrotina parou de fato.** Um :meth:`Execucao.cancelar` entrega o ``CancelledError`` à corrotina
no ``await`` em que ela estiver; ela fecha o canal, apaga o arquivo pela metade, e só então a execução fica
cancelada. (O futuro do ``asyncio.run_coroutine_threadsafe`` se dá por cancelado na hora do pedido, com a limpeza
ainda rodando: uma transferência nova do mesmo arquivo começaria em cima da antiga.) ``ao_terminar(execucao)``, ligado
no :meth:`~LacoAsyncio.submeter` (antes de a corrotina começar, para nenhum fim escapar), roda na thread do laço, uma
vez, em qualquer fim.

**Ao parar,** :meth:`LacoAsyncio.parar` cancela o que ainda roda, espera as corrotinas tratarem o cancelamento,
fecha os geradores assíncronos e o executor padrão, e só então a thread termina: nenhuma fica viva. A thread é
``daemon`` só como rede de segurança (um processo que sai sem parar o laço não fica preso nela); quem inicia, para.
Uma falha no laço fora de uma execução (um *callback*, uma tarefa interna que ninguém espera) vai para o log.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger(__name__)

NOME_DA_THREAD = "sh_placa-asyncio"
ESPERA_AO_PARAR_S = 5.0


class Execucao:
    """Uma corrotina agendada no laço (:meth:`LacoAsyncio.submeter`). :meth:`cancelar` vale de qualquer thread;
    :meth:`resultado` espera o fim e devolve o resultado (ou levanta a exceção da corrotina, ou o
    ``concurrent.futures.CancelledError``)."""

    def __init__(self, laco: asyncio.AbstractEventLoop, ao_terminar: Callable[[Execucao], Any] | None):
        self._laco = laco
        self._ao_terminar = ao_terminar
        self._futuro: concurrent.futures.Future = concurrent.futures.Future()
        self._tarefa: asyncio.Task | None = None

    def cancelar(self) -> None:
        """Pede o cancelamento; o fim (``cancelada``) chega quando a corrotina terminar de tratá-lo. Depois do fim,
        não faz nada."""
        try:
            self._laco.call_soon_threadsafe(self._cancelar_no_laco)
        except RuntimeError:                 # o laço já fechou: o parar cancelou e esperou tudo
            pass

    def feita(self) -> bool:
        return self._futuro.done()

    def cancelada(self) -> bool:
        return self._futuro.cancelled()

    def excecao(self) -> BaseException | None:
        """A exceção da corrotina (``None`` se ela devolveu um valor); só depois do fim, e não numa cancelada."""
        return self._futuro.exception(timeout=0)

    def resultado(self, timeout: float | None = None) -> Any:
        return self._futuro.result(timeout)

    # -------------------------------------------------------------- na thread do laço

    def _comecar(self, corrotina) -> None:
        self._tarefa = self._laco.create_task(corrotina)
        self._tarefa.add_done_callback(self._acabou)

    def _cancelar_no_laco(self) -> None:
        if self._tarefa is not None:
            self._tarefa.cancel()

    def _acabou(self, tarefa: asyncio.Task) -> None:
        if tarefa.cancelled():
            self._futuro.cancel()
        elif tarefa.exception() is not None:
            self._futuro.set_exception(tarefa.exception())
        else:
            self._futuro.set_result(tarefa.result())
        if self._ao_terminar is not None:
            try:
                self._ao_terminar(self)
            except Exception as e:           # o ouvinte falhou: o laço segue, e o defeito vai para o log
                self._laco.call_exception_handler({"message": "o ao_terminar de uma execução falhou",
                                                   "exception": e})


class LacoAsyncio:
    """A thread com o laço. :meth:`iniciar` a sobe (chamar de novo, rodando, não faz nada); :meth:`parar` a
    derruba, e um :meth:`iniciar` depois sobe um laço novo. Também é um gerenciador de contexto."""

    def __init__(self, nome: str = NOME_DA_THREAD):
        self.nome = nome
        self._laco: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        # A trava ordena os agendamentos e o pedido de parar: um _comecar agendado antes do stop roda antes dele, e a
        # tarefa que ele cria é cancelada e esperada no fim do laço (nenhuma execução fica sem fim).
        self._trava = threading.Lock()

    @property
    def rodando(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def iniciar(self) -> None:
        with self._trava:
            if self.rodando:
                return
            laco = asyncio.new_event_loop()
            laco.set_exception_handler(_registrar_no_log)
            pronto = threading.Event()
            self._laco = laco
            self._thread = threading.Thread(target=_principal, args=(laco, pronto), name=self.nome, daemon=True)
            self._thread.start()
        pronto.wait()

    def submeter(self, funcao: Callable[..., Awaitable], *args,
                 ao_terminar: Callable[[Execucao], Any] | None = None) -> Execucao:
        """Agenda ``funcao(*args)`` no laço. A corrotina nasce já na thread dele; ``RuntimeError`` se o laço não
        está rodando."""
        with self._trava:
            if not self.rodando:
                raise RuntimeError("o laço da placa não está rodando (LacoAsyncio.iniciar)")
            execucao = Execucao(self._laco, ao_terminar)
            self._laco.call_soon_threadsafe(_criar, execucao, funcao, args)
        return execucao

    def parar(self, espera_s: float = ESPERA_AO_PARAR_S) -> bool:
        """Cancela o que roda, espera, fecha o laço e a thread. ``False`` se ela não terminou em ``espera_s`` (uma
        corrotina que demora a tratar o cancelamento); ela segue até terminar, sem o laço aceitar nada novo."""
        with self._trava:
            thread, laco = self._thread, self._laco
            if thread is None:
                return True
            if thread is threading.current_thread():
                raise RuntimeError("o laço da placa não pode parar a si mesmo: pare-o de outra thread")
            self._thread = self._laco = None
            laco.call_soon_threadsafe(laco.stop)
        thread.join(espera_s)
        if thread.is_alive():
            log.warning("o laço da placa não parou em %g s: uma corrotina ainda trata o cancelamento", espera_s)
            return False
        return True

    def __enter__(self) -> LacoAsyncio:
        self.iniciar()
        return self

    def __exit__(self, *_excecao) -> None:
        self.parar()


def _criar(execucao: Execucao, funcao: Callable[..., Awaitable], args: tuple) -> None:
    """Na thread do laço: a tarefa, que chama ``funcao(*args)`` já dentro dela. Uma ``funcao`` que falha antes de
    devolver a corrotina (um argumento errado) é o fim da execução, com a exceção, como uma que falha depois."""
    execucao._comecar(_aguardar(funcao, args))


async def _aguardar(funcao: Callable[..., Awaitable], args: tuple):
    return await funcao(*args)


def _principal(laco: asyncio.AbstractEventLoop, pronto: threading.Event) -> None:
    asyncio.set_event_loop(laco)
    laco.call_soon(pronto.set)
    try:
        laco.run_forever()
    finally:
        try:
            _cancelar_e_esperar(laco)
            laco.run_until_complete(laco.shutdown_asyncgens())
            laco.run_until_complete(laco.shutdown_default_executor())
        finally:
            asyncio.set_event_loop(None)
            laco.close()


def _cancelar_e_esperar(laco: asyncio.AbstractEventLoop) -> None:
    """As tarefas que sobraram, canceladas e esperadas (como no fim do ``asyncio.run``)."""
    pendentes = asyncio.all_tasks(laco)
    if not pendentes:
        return
    for tarefa in pendentes:
        tarefa.cancel()
    laco.run_until_complete(asyncio.gather(*pendentes, return_exceptions=True))
    for tarefa in pendentes:
        if not tarefa.cancelled() and tarefa.exception() is not None:
            laco.call_exception_handler({"message": "uma tarefa falhou ao ser cancelada no fim do laço",
                                         "exception": tarefa.exception(), "task": tarefa})


def _registrar_no_log(_laco: asyncio.AbstractEventLoop, contexto: dict) -> None:
    excecao = contexto.get("exception")
    log.error("no laço da placa: %s", contexto.get("message", "erro sem mensagem"),
              exc_info=(type(excecao), excecao, excecao.__traceback__) if excecao is not None else None)
