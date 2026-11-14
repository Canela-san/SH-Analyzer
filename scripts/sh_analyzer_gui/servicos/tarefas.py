"""As tarefas em segundo plano (docs/gui-plan.md, 8.3): a pirâmide de uma captura, a conferência do CRC e, depois,
os espectros e as exportações. Cada uma roda num ``QThreadPool`` (o NumPy e o zlib soltam o GIL), mostra o
progresso e pode ser cancelada.

**O contrato da função de uma tarefa:** ``funcao(progresso, cancelado) -> resultado``. Ela chama
``progresso(fração)`` de vez em quando e confere ``cancelado()`` entre os blocos; para parar, levanta
``Cancelado`` (o do motor, que a pirâmide e as contas da ``api`` usam) ou devolve o que tiver. A tarefa repassa o progresso no máximo a cada 50 ms, para não
inundar a interface.

**Os sinais saem da thread de trabalho** e chegam à interface pela fila de eventos do Qt (a ``Tarefa`` mora na
thread da interface). **Ao fechar,** :meth:`GerenciadorDeTarefas.encerrar` cancela todas e espera: nenhuma thread
fica rodando com o Python já saindo.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..dados.piramide import Cancelado

log = logging.getLogger(__name__)

INTERVALO_DO_PROGRESSO_S = 0.05
ESTADOS = ("esperando", "rodando", "concluida", "cancelada", "falhou")


class Tarefa(QObject):
    """Uma tarefa: o nome (para o painel), o estado, o progresso (0 a 1) e o resultado.

    ``terminou(tarefa)`` sai uma vez, no fim, em qualquer estado final (``concluida``, ``cancelada`` ou ``falhou``,
    com ``erro`` preenchido)."""

    progressoMudou = Signal(object, float)
    terminou = Signal(object)

    def __init__(self, nome: str, funcao: Callable, grupo: str = ""):
        super().__init__()
        self.nome, self.grupo = nome, grupo
        self.estado = "esperando"
        self.progresso = 0.0
        self.resultado = None
        self.erro = ""
        self.mostrar = True
        self._funcao = funcao
        self._cancelar = threading.Event()
        self._ultimo_aviso = 0.0

    @property
    def ativa(self) -> bool:
        return self.estado in ("esperando", "rodando")

    def cancelar(self) -> None:
        self._cancelar.set()

    def cancelada(self) -> bool:
        return self._cancelar.is_set()

    def _progresso(self, fracao: float) -> None:
        self.progresso = min(1.0, max(0.0, float(fracao)))
        agora = time.monotonic()
        if agora - self._ultimo_aviso >= INTERVALO_DO_PROGRESSO_S or self.progresso >= 1.0:
            self._ultimo_aviso = agora
            self.progressoMudou.emit(self, self.progresso)

    def _rodar(self) -> None:
        """Na thread de trabalho."""
        if self.cancelada():
            self.estado = "cancelada"
        else:
            self.estado = "rodando"
            try:
                self.resultado = self._funcao(self._progresso, self.cancelada)
                self.estado = "cancelada" if self.cancelada() else "concluida"
            except Cancelado:
                self.estado = "cancelada"
            except Exception as e:           # a tarefa falha sozinha; o aplicativo segue
                log.exception("a tarefa %r falhou", self.nome)
                self.erro, self.estado = str(e) or type(e).__name__, "falhou"
        self.terminou.emit(self)

    def __repr__(self) -> str:
        return f"Tarefa({self.nome!r}, {self.estado}, {self.progresso:.0%})"


class _Executor(QRunnable):
    def __init__(self, tarefa: Tarefa):
        super().__init__()
        self.tarefa = tarefa                 # segura a tarefa viva até o fim do run

    def run(self) -> None:
        self.tarefa._rodar()


class GerenciadorDeTarefas(QObject):
    """As tarefas do aplicativo. ``tarefaEntrou`` e ``tarefaSaiu`` (no fim, em qualquer estado) alimentam o painel
    de tarefas e a barra de status."""

    tarefaEntrou = Signal(object)
    tarefaSaiu = Signal(object)

    def __init__(self, threads: int = 2, parent: QObject | None = None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(threads)
        self._ativas: list[Tarefa] = []
        self.encerrado = False

    @property
    def ativas(self) -> tuple[Tarefa, ...]:
        return tuple(self._ativas)

    def iniciar(self, nome: str, funcao: Callable, grupo: str = "", *, mostrar: bool = True,
                ao_terminar: Callable | None = None, ao_progredir: Callable | None = None) -> Tarefa:
        """Põe a tarefa na fila e a devolve. **Os ouvintes vão aqui** (``ao_terminar(tarefa)``,
        ``ao_progredir(tarefa, fração)``), ligados antes de a tarefa começar: ligados depois do ``iniciar``, uma
        tarefa rápida pode terminar antes, e o sinal sai para ninguém (o erro apareceu num teste em paralelo: a
        conferência de uma captura sem CRC ficava "conferindo" para sempre). Com ``mostrar=False`` (uma conta
        rápida e frequente, como as medidas), ela não aparece no painel de tarefas."""
        tarefa = Tarefa(nome, funcao, grupo)
        tarefa.mostrar = mostrar
        if self.encerrado:
            # Depois de encerrar (a janela fechando), nada começa: um temporizador atrasado (a medida da vista)
            # não põe uma thread para rodar com a janela sendo apagada.
            tarefa.estado = "cancelada"
            return tarefa
        if ao_progredir is not None:
            tarefa.progressoMudou.connect(ao_progredir)
        if ao_terminar is not None:
            tarefa.terminou.connect(ao_terminar)
        tarefa.terminou.connect(self._terminou)
        self._ativas.append(tarefa)
        if mostrar:
            self.tarefaEntrou.emit(tarefa)
        self.pool.start(_Executor(tarefa))
        return tarefa

    def cancelar_grupo(self, grupo: str) -> None:
        for tarefa in self._ativas:
            if tarefa.grupo == grupo:
                tarefa.cancelar()

    def encerrar(self, espera_ms: int = 10_000) -> bool:
        """Cancela todas e espera elas pararem; ``False`` se alguma não parou a tempo. Depois disso, nenhuma tarefa
        nova começa."""
        self.encerrado = True
        for tarefa in self._ativas:
            tarefa.cancelar()
        return self.pool.waitForDone(espera_ms)

    @property
    def visiveis(self) -> tuple[Tarefa, ...]:
        """As ativas que aparecem no painel."""
        return tuple(t for t in self._ativas if t.mostrar)

    def _terminou(self, tarefa: Tarefa) -> None:
        if tarefa in self._ativas:
            self._ativas.remove(tarefa)
            if tarefa.mostrar:
                self.tarefaSaiu.emit(tarefa)
