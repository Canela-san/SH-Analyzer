"""O servidor SSH dos testes da conexão com a placa: o do simulador (``sh_placa.servidor_do_simulador``, o que a
interface usa), mais o que só os testes pedem.

* **a senha** (a primeira conexão: a impressão, a senha e a instalação da chave; o sudo pede a mesma, como na placa);
* **o terminal** (o ``ssh`` sem comando da F3.8): um ``sh -i`` num pseudoterminal deste computador, do tamanho que o
  cliente pediu e que muda quando ele avisa (a placa simulada da interface não tem terminal);
* **o salto** (``permitir_tunel``: as conexões *direct-tcpip* para outro servidor), **a chave RSA** (``tambem_rsa``,
  como a imagem da placa, que tem as três) e **a placa regravada** (:meth:`ServidorSSH.trocar_chave_do_host`);
* :attr:`ServidorSSH.autenticacoes`: as tentativas, para conferir o que foi enviado.

**O ``pgrep`` só vê os processos do teste** (``processos``: os de executável dentro dessa pasta; a do teste, por
padrão): o ``ler_adc`` falso que um teste roda é a captura na placa dele, e não na de um teste em paralelo. O SFTP não
tem o limite de vazão do USB, e as capturas da placa são curtas (``tests/conftest.py``).
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import socket
import struct
import termios
from pathlib import Path

import asyncssh
from sh_placa.servidor_do_simulador import (
    ServidorDoSimulador,
    _LadoDoServidor,
    matar,
    matar_quando_o_canal_fechar,
)

SENHA_PADRAO = "temppwd-do-teste"


class ServidorSSH(ServidorDoSimulador):
    def __init__(self, pasta: Path, *, cenario: str = "normal", usuario: str = "debian", senha: str = SENHA_PADRAO,
                 senha_do_sudo: str | None = None, permitir_tunel: bool = False, tambem_rsa: bool = False,
                 enderecos: tuple[str, ...] = ("127.0.0.1",), processos: Path | None = None):
        super().__init__(pasta, cenario, usuario=usuario, senha=senha,
                         senha_do_sudo=senha if senha_do_sudo is None else senha_do_sudo, enderecos=enderecos,
                         processos=processos if processos is not None else Path(pasta).parent, vazao_bytes_s=None)
        self.permitir_tunel = permitir_tunel
        self.autenticacoes: list[tuple[str, object]] = []    # ("inicio", usuário), ("senha", certa?)
        # Como a imagem da placa, que tem as chaves RSA, ECDSA e ED25519 (o asyncssh, sozinho, escolheria a RSA).
        self.chave_rsa = asyncssh.generate_private_key("ssh-rsa", key_size=2048) if tambem_rsa else None

    async def trocar_chave_do_host(self) -> None:
        """A placa regravada: outra chave de host, na mesma porta."""
        await self.parar()
        self.chave_do_host = asyncssh.generate_private_key("ssh-ed25519")
        await self.iniciar()

    def _lado_do_servidor(self) -> asyncssh.SSHServer:
        return _Servidor(self)

    def _chaves_do_host(self) -> list[asyncssh.SSHKey]:
        return [k for k in (self.chave_rsa, self.chave_do_host) if k is not None]

    async def _sem_comando(self, processo: asyncssh.SSHServerProcess) -> None:
        await self._terminal(processo)

    async def _terminal(self, processo: asyncssh.SSHServerProcess) -> None:
        """O shell interativo (``ssh`` sem comando, com PTY): um ``sh -i`` num pseudoterminal deste computador, do
        tamanho pedido, que muda quando o cliente avisa (o ``TerminalSizeChanged``, como o sshd faz com o
        ``window-change``). Sem PTY pedido, o shell lê o canal como um comando sem nada para rodar."""
        colunas, linhas, *_ = processo.get_terminal_size()
        mestre, escravo = pty.openpty()
        _tamanho_do_pty(mestre, colunas or 80, linhas or 24)
        ambiente = {**self.ambiente, "TERM": processo.get_terminal_type() or "dumb", "PS1": "placa$ "}
        # O setsid do util-linux: uma sessão nova, com o PTY como terminal de controle (o controle de tarefas e o
        # SIGWINCH do sh), sem código Python no filho depois do fork (o preexec_fn trava num processo com threads,
        # como o dos testes da interface). Ele vira o sh, com o mesmo pid: o grupo dele é o do matar.
        try:
            shell = await asyncio.create_subprocess_exec(
                "setsid", "--ctty", "/bin/sh", "-i", stdin=escravo, stdout=escravo, stderr=escravo, cwd=self.home,
                env=ambiente)
        finally:
            os.close(escravo)
        laco = asyncio.get_running_loop()
        saida: asyncio.Queue[bytes] = asyncio.Queue()

        def ler_do_pty() -> None:
            try:
                dados = os.read(mestre, 65536)
            except OSError:                         # EIO: o shell saiu e o escravo fechou
                dados = b""
            if not dados:
                laco.remove_reader(mestre)
            saida.put_nowait(dados)

        async def copiar_a_saida() -> None:
            while dados := await saida.get():
                processo.stdout.write(dados)

        async def copiar_a_entrada() -> None:
            while True:
                try:
                    dados = await processo.stdin.read(65536)
                except asyncssh.TerminalSizeChanged as mudou:
                    _tamanho_do_pty(mestre, mudou.width, mudou.height)
                    continue
                if not dados:
                    break
                os.write(mestre, dados)

        laco.add_reader(mestre, ler_do_pty)
        entrada = asyncio.create_task(copiar_a_entrada())
        vigia = asyncio.create_task(matar_quando_o_canal_fechar(processo, shell))
        try:
            await copiar_a_saida()
            processo.exit(await shell.wait())
        except (asyncssh.Error, OSError):
            pass
        finally:
            laco.remove_reader(mestre)
            for auxiliar in (entrada, vigia):
                auxiliar.cancel()
            matar(shell)
            await asyncio.gather(entrada, vigia, return_exceptions=True)
            await shell.wait()
            os.close(mestre)




class _Servidor(_LadoDoServidor):
    """O lado do servidor do simulador, anotando as tentativas de autenticação e com o salto, se o teste quer."""

    def begin_auth(self, username: str) -> bool:
        self.dono.autenticacoes.append(("inicio", username))
        return super().begin_auth(username)

    def validate_password(self, username: str, password: str) -> bool:
        certa = super().validate_password(username, password)
        self.dono.autenticacoes.append(("senha", certa))
        return certa

    def connection_requested(self, dest_host: str, dest_port: int, orig_host: str, orig_port: int) -> bool:
        return self.dono.permitir_tunel


def porta_livre() -> int:
    """Uma porta do loopback que ninguém escuta agora: a de uma placa que não responde."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _tamanho_do_pty(fd: int, colunas: int, linhas: int) -> None:
    """O ``TIOCSWINSZ``: o tamanho do pseudoterminal (o shell nele recebe o ``SIGWINCH``)."""
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", linhas, colunas, 0, 0))
