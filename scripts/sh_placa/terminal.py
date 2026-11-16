"""O terminal da placa (docs/gui-plan.md, 11.8; a F3.8): um shell interativo num PTY sobre a conexão SSH, em bytes,
gravado como o ``lab ssh`` grava (o ``script -a``: a saída do terminal, acrescentada ao ``$DIA/terminal_bbb.txt``).
Sem Qt: a interface pinta (``componentes/terminal.py``, com o ``pyte``) e manda as teclas.

**Na thread do laço:** :meth:`SessaoDeTerminal.rodar` lê a saída até o shell terminar (ou a conexão cair) e a entrega
a ``ao_receber(bytes)``, que roda no laço (a interface a leva para a thread dela por um sinal). :meth:`escrever` e
:meth:`redimensionar` também são do laço: a interface os agenda (``LacoAsyncio.agendar``).

**O registro de atividade** diz que um terminal abriu e fechou (e onde ficou gravado); os comandos que a pessoa
digita são dela, e ficam na gravação.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .registro import Entrada

if TYPE_CHECKING:
    from .conexao import ConexaoSSH

log = logging.getLogger(__name__)

TIPO_DO_TERMINAL = "xterm-256color"
BLOCO = 64 * 1024
ESPERA_DO_CODIGO_S = 5.0


def cabecalho_da_gravacao(conta: str, colunas: int, linhas: int, quando: float | None = None) -> bytes:
    """A linha que separa as sessões no arquivo da gravação (o ``script`` escreveria "Script started on …")."""
    quando = time.time() if quando is None else quando
    data = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(quando))
    return f"\n--- terminal da placa {conta}, aberto em {data} ({colunas}×{linhas}, SH-Analyzer) ---\n".encode()


class SessaoDeTerminal:
    """Um terminal na placa. ``ao_receber(bytes)`` a cada pedaço da saída; ``gravacao``: o arquivo em que a saída é
    acrescentada (``None``: sem gravar)."""

    def __init__(self, conexao: ConexaoSSH, colunas: int, linhas: int, *, ao_receber: Callable[[bytes], object],
                 gravacao: Path | None = None, tipo: str = TIPO_DO_TERMINAL):
        self.conexao, self.colunas, self.linhas, self.tipo = conexao, colunas, linhas, tipo
        self.ao_receber, self.gravacao = ao_receber, gravacao
        self._processo = None
        self._fechado_aqui = False
        self.codigo: int | None = None

    def _fato(self, descricao: str) -> None:
        self.conexao.registro.registrar(Entrada(time.time(), self.conexao.destino.conta, "conexao", descricao))

    async def rodar(self) -> int | None:
        """Abre o shell e lê até ele terminar; devolve o código de saída (``None``: a conexão caiu, ou o terminal foi
        fechado na interface)."""
        self._processo = await self.conexao.abrir_terminal(self.colunas, self.linhas, self.tipo)
        arquivo = None
        if self.gravacao is not None:
            try:
                self.gravacao.parent.mkdir(parents=True, exist_ok=True)
                arquivo = self.gravacao.open("ab")
                arquivo.write(cabecalho_da_gravacao(self.conexao.destino.conta, self.colunas, self.linhas))
            except OSError as e:
                log.warning("o terminal não vai ser gravado em %s: %s", self.gravacao, e)
                arquivo = None
        onde = f", gravado em {self.gravacao}" if arquivo is not None else ""
        self._fato(f"terminal aberto ({self.tipo}, {self.colunas}×{self.linhas}){onde}")
        try:
            import asyncssh

            while True:
                try:
                    dados = await self._processo.stdout.read(BLOCO)
                except (asyncssh.Error, OSError):
                    break                          # a conexão caiu: o fim do terminal
                if not dados:
                    break
                if arquivo is not None:
                    arquivo.write(dados)
                    arquivo.flush()
                self.ao_receber(dados)
            # O código chega depois do fim da saída no OpenSSH (o EOF, o exit-status e o close, nessa ordem).
            with contextlib.suppress(asyncio.TimeoutError, asyncssh.Error, OSError):
                await asyncio.wait_for(self._processo.wait_closed(), ESPERA_DO_CODIGO_S)
            self.codigo = self._processo.exit_status
        finally:
            if arquivo is not None:
                arquivo.close()
            self._fechar_processo()
            if self._fechado_aqui:
                fim = "na interface"
            elif self.codigo is not None:
                fim = f"(o shell saiu com o código {self.codigo})"
            else:
                fim = "(a conexão caiu antes do fim do shell)"
            self._fato(f"terminal fechado {fim}")
        return self.codigo

    def escrever(self, dados: bytes) -> None:
        """Na thread do laço: o que a pessoa digitou (ou colou)."""
        if self._processo is not None:
            with contextlib.suppress(Exception):    # o shell que acabou de sair: a tecla não tem para onde ir
                self._processo.stdin.write(dados)

    def redimensionar(self, colunas: int, linhas: int) -> None:
        """Na thread do laço: o tamanho novo do terminal chega ao PTY da placa (o ``SIGWINCH`` do shell)."""
        self.colunas, self.linhas = colunas, linhas
        if self._processo is not None:
            with contextlib.suppress(Exception):
                self._processo.change_terminal_size(colunas, linhas)

    def fechar(self) -> None:
        """Na thread do laço: fecha o canal (o shell recebe o fim; o :meth:`rodar` termina)."""
        self._fechado_aqui = True
        self._fechar_processo()

    def _fechar_processo(self) -> None:
        if self._processo is not None:
            with contextlib.suppress(Exception):
                self._processo.close()
