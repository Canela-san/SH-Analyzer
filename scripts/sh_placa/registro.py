"""O registro de atividade (docs/gui-plan.md, 11.1, "Transparente"; AQ-18): cada comando rodado na placa, com a
hora, a duração e o código de saída, e os fatos da conexão (conectou, caiu, a chave do host fixada). A visão geral e
o diagnóstico da interface o mostram, e o relatório de diagnóstico o anexa.

**Nada secreto entra aqui:** a senha só vai na autenticação do SSH, nunca num comando; o que vai pelo stdin (o
código do agente, a chave pública) aparece pela descrição, não pelo conteúdo.

**Entre as threads:** o laço da placa escreve e a interface lê. As entradas são imutáveis, a lista tem uma trava, e
os ouvintes (:meth:`RegistroDeAtividade.ouvir`) rodam na thread de quem registrou (o laço): a ponte da interface os
leva para a thread dela.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

LIMITE = 2000
"""As entradas guardadas (as mais antigas saem): horas de uso, sem crescer sem fim."""


@dataclass(frozen=True)
class Entrada:
    """Um comando (``tipo="comando"``) ou um fato da conexão (``tipo="conexao"``, sem ``comando``)."""

    inicio: float                 # time.time()
    destino: str                  # "debian@192.168.6.2"
    tipo: str
    descricao: str                # para pessoas: "agente: estado"
    comando: str = ""             # exatamente o que rodou na placa
    duracao_s: float = 0.0
    codigo: int | None = None     # None: não terminou (caiu, tempo esgotado, cancelado) ou não é um comando
    falha: str = ""               # por que não terminou

    @property
    def hora(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.inicio))

    def em_texto(self) -> str:
        """Uma linha (e a do comando, se houver), para copiar ou anexar ao relatório."""
        if self.tipo != "comando":
            return f"{self.hora}  {self.destino}  {self.descricao}"
        fim = self.falha if self.codigo is None else f"código {self.codigo}"
        duracao = f"{self.duracao_s:.2f}".replace(".", ",")
        return f"{self.hora}  {self.destino}  {self.descricao} ({duracao} s, {fim})\n    $ {self.comando}"


class RegistroDeAtividade:
    def __init__(self, limite: int = LIMITE):
        self._entradas: deque[Entrada] = deque(maxlen=limite)
        self._ouvintes: list[Callable[[Entrada], object]] = []
        self._trava = threading.Lock()

    @property
    def entradas(self) -> tuple[Entrada, ...]:
        with self._trava:
            return tuple(self._entradas)

    def registrar(self, entrada: Entrada) -> None:
        with self._trava:
            self._entradas.append(entrada)
            ouvintes = tuple(self._ouvintes)
        log.info("placa: %s", entrada.em_texto().replace("\n    ", " | "))
        for ouvinte in ouvintes:
            try:
                ouvinte(entrada)
            except Exception:                    # um ouvinte com defeito não impede o registro nem os outros
                log.exception("um ouvinte do registro de atividade falhou")

    def ouvir(self, ouvinte: Callable[[Entrada], object]) -> Callable[[], None]:
        """Chama ``ouvinte(entrada)`` a cada entrada nova; devolve a função que para de ouvir."""
        with self._trava:
            self._ouvintes.append(ouvinte)

        def parar() -> None:
            with self._trava:
                if ouvinte in self._ouvintes:
                    self._ouvintes.remove(ouvinte)
        return parar

    def em_texto(self) -> str:
        return "\n".join(e.em_texto() for e in self.entradas)
