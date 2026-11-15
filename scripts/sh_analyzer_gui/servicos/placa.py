"""A ponte entre a interface e o ``sh_placa`` (docs/gui-plan.md, 8.3): as chamadas à placa rodam no laço
``asyncio`` da thread própria (``sh_placa/laco.py``), e o resultado volta na thread da interface, por um sinal.

**Uma chamada** (:meth:`ServicoDaPlaca.chamar`) é uma função ``async`` do ``sh_placa`` com os argumentos dela. A
:class:`Chamada` diz o estado (``rodando``, ``concluida``, ``cancelada``, ``falhou``), e ``terminou(chamada)`` sai
uma vez, no fim. **O estado só muda na thread da interface,** quando o aviso do laço chega pela fila de eventos, e
logo antes do ``terminou``: quem olha a chamada nunca a vê terminada sem o sinal ter saído (a corrida que o teste da
fila das pesadas mostrou nas tarefas). :meth:`Chamada.cancelar` entrega o ``CancelledError`` à corrotina no
``await`` em que ela estiver; a chamada fica ``cancelada`` quando a corrotina terminou a limpeza.

**Uma chamada que falha** fica ``falhou``, com o motivo em ``erro``. O motivo esperado (um ``ErroDaPlaca``, um
``OSError`` da rede, um tempo esgotado) fica só aí, para quem pediu mostrar no lugar certo; outra exceção é um
defeito (``inesperado``): vai também para o log e para o diálogo de erro inesperado (``servicos/erros.py``), como
nas tarefas.

**A thread do laço nasce na primeira chamada** (quem não usa a Aquisição não a tem) e **morre no**
:meth:`ServicoDaPlaca.encerrar`, ao fechar a janela: o que ainda roda é cancelado e esperado, e nenhuma thread fica.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from PySide6.QtCore import QObject, Signal
from sh_placa.agente import ErroDaPlaca
from sh_placa.laco import ESPERA_AO_PARAR_S, Execucao, LacoAsyncio
from shiboken6 import isValid

from .erros import relatar

log = logging.getLogger(__name__)

ESTADOS = ("rodando", "concluida", "cancelada", "falhou")
ERROS_ESPERADOS = (ErroDaPlaca, OSError, asyncio.TimeoutError)
"""Os motivos de uma chamada falhar que não são defeito: a placa, a rede, o tempo (``asyncio.TimeoutError`` é o
``TimeoutError`` a partir do Python 3.11, e uma classe à parte no 3.10)."""


class Chamada(QObject):
    """Uma chamada à placa: o nome (para o registro e as mensagens), o estado, o resultado ou o erro."""

    terminou = Signal(object)
    _acabou = Signal()                       # do laço para a thread da interface (a chamada mora nela)

    def __init__(self, nome: str):
        super().__init__()
        self.nome = nome
        self.estado = "rodando"
        self.resultado = None
        self.erro = ""
        self.inesperado = False              # falhou por um defeito, e não pela placa, pela rede ou pelo tempo
        self._execucao: Execucao | None = None
        self._acabou.connect(self._ao_acabar)

    @property
    def ativa(self) -> bool:
        return self.estado == "rodando"

    def cancelar(self) -> None:
        if self._execucao is not None and self.ativa:
            self._execucao.cancelar()

    def _no_laco(self, _execucao: Execucao) -> None:
        """Na thread do laço, no fim da corrotina: só avisa (o estado muda na thread da interface). Uma chamada já
        apagada (a janela fechou) não tem a quem avisar."""
        if isValid(self):
            try:
                self._acabou.emit()
            except RuntimeError:             # apagada entre o isValid e o emit
                pass

    def _ao_acabar(self) -> None:
        execucao = self._execucao
        if execucao is None or not self.ativa:
            return
        if execucao.cancelada():
            self.estado = "cancelada"
        elif (excecao := execucao.excecao()) is None:
            self.resultado, self.estado = execucao.resultado(), "concluida"
        elif isinstance(excecao, ERROS_ESPERADOS):
            log.warning("a chamada %r à placa falhou: %s", self.nome, excecao)
            self.erro, self.estado = str(excecao) or type(excecao).__name__, "falhou"
        else:
            relatar(excecao, f"na chamada {self.nome!r} à placa")
            self.erro = f"erro inesperado ({type(excecao).__name__}: {excecao})" if str(excecao) \
                else f"erro inesperado ({type(excecao).__name__})"
            self.estado, self.inesperado = "falhou", True
        self.terminou.emit(self)

    def __repr__(self) -> str:
        return f"Chamada({self.nome!r}, {self.estado})"


class ServicoDaPlaca(QObject):
    """As chamadas à placa do aplicativo, num laço só. ``chamadaEntrou`` e ``chamadaSaiu`` (no fim, em qualquer
    estado) alimentam quem mostra a atividade da placa."""

    chamadaEntrou = Signal(object)
    chamadaSaiu = Signal(object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.laco = LacoAsyncio()
        self._ativas: list[Chamada] = []
        self.encerrado = False

    @property
    def ativas(self) -> tuple[Chamada, ...]:
        return tuple(self._ativas)

    def chamar(self, nome: str, funcao: Callable[..., Awaitable], *args,
               ao_terminar: Callable[[Chamada], object] | None = None) -> Chamada:
        """Roda ``funcao(*args)`` no laço e devolve a :class:`Chamada`. **O ouvinte vai aqui** (``ao_terminar``),
        ligado antes de a corrotina começar, e depois do serviço: quando ele roda, a chamada já saiu de
        :attr:`ativas`. Depois do :meth:`encerrar`, nada roda: a chamada volta ``cancelada``, sem sinal."""
        chamada = Chamada(nome)
        if self.encerrado:
            chamada.estado = "cancelada"
            return chamada
        chamada.terminou.connect(self._terminou)
        if ao_terminar is not None:
            chamada.terminou.connect(ao_terminar)
        self.laco.iniciar()
        self._ativas.append(chamada)
        self.chamadaEntrou.emit(chamada)
        chamada._execucao = self.laco.submeter(funcao, *args, ao_terminar=chamada._no_laco)
        return chamada

    def encerrar(self, espera_s: float = ESPERA_AO_PARAR_S) -> bool:
        """Cancela as chamadas, espera as corrotinas pararem e derruba a thread do laço; ``False`` se ela não parou a
        tempo. Depois disso, nenhuma chamada nova roda."""
        self.encerrado = True
        return self.laco.parar(espera_s)

    def _terminou(self, chamada: Chamada) -> None:
        if chamada in self._ativas:
            self._ativas.remove(chamada)
            self.chamadaSaiu.emit(chamada)
