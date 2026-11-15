"""Um servidor SSH do próprio asyncssh para os testes da conexão com a placa (F3.2; cresce até o simulador por SSH da
F3.9): uma BeagleBone vista pela rede, sem placa.

O servidor escuta em 127.0.0.1 (ou em mais endereços do loopback, na mesma porta), numa porta livre, com a senha e as
chaves do ``~/.ssh/authorized_keys`` do home falso (o do simulador: ``montar_sistema_falso``). Cada comando roda num
shell de verdade, com esse home, a raiz falsa em ``SHAN_RAIZ`` e um ``python3`` que é o Python dos testes: o agente
que chega pelo stdin lê a placa simulada, e a instalação da chave escreve no ``authorized_keys`` dela, como numa placa.

Para os testes: os comandos rodados (:attr:`ServidorSSH.comandos`), as tentativas de autenticação
(:attr:`ServidorSSH.autenticacoes`), a troca da chave de host (:meth:`ServidorSSH.trocar_chave_do_host`, a placa
regravada), a queda de todas as conexões (:meth:`ServidorSSH.derrubar`, o cabo que solta) e o salto
(``permitir_tunel``: ele abre as conexões *direct-tcpip* para outro servidor).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
import sys
from pathlib import Path

import asyncssh
from sh_placa.simulador import montar_sistema_falso

SENHA_PADRAO = "temppwd-do-teste"


class ServidorSSH:
    def __init__(self, pasta: Path, *, cenario: str = "normal", usuario: str = "debian", senha: str = SENHA_PADRAO,
                 permitir_tunel: bool = False, tambem_rsa: bool = False,
                 enderecos: tuple[str, ...] = ("127.0.0.1",)):
        self.pasta, self.cenario = Path(pasta), cenario
        self.usuario, self.senha, self.permitir_tunel = usuario, senha, permitir_tunel
        self.enderecos = enderecos           # vários, como a placa nos dois IPs do USB (127.0.0.1 e 127.0.0.2)
        self.raiz, firmware = montar_sistema_falso(self.pasta, cenario)
        self.home = firmware.parent
        self.comandos: list[str] = []
        self.autenticacoes: list[tuple[str, object]] = []    # ("inicio", usuário), ("senha", certa?)
        self.conexoes: set[asyncssh.SSHServerConnection] = set()
        self._rodando: set[asyncio.Task] = set()            # os comandos ainda rodando (o _rodar de cada um)
        self.porta = 0
        self.chave_do_host = asyncssh.generate_private_key("ssh-ed25519")
        # Como a imagem da placa, que tem as chaves RSA, ECDSA e ED25519 (o asyncssh, sozinho, escolheria a RSA).
        self.chave_rsa = asyncssh.generate_private_key("ssh-rsa", key_size=2048) if tambem_rsa else None
        self._servidores: list[asyncssh.SSHAcceptor] = []
        binarios = self.pasta / "bin"
        binarios.mkdir(exist_ok=True)
        (binarios / "python3").symlink_to(sys.executable)
        self.ambiente = {"HOME": str(self.home), "PATH": f"{binarios}{os.pathsep}{os.environ.get('PATH', '')}",
                         "SHAN_RAIZ": str(self.raiz), "LANG": "C.UTF-8"}

    @property
    def authorized_keys(self) -> Path:
        return self.home / ".ssh" / "authorized_keys"

    @property
    def impressao(self) -> str:
        return self.chave_do_host.get_fingerprint()

    async def iniciar(self) -> ServidorSSH:
        """Escuta em cada endereço, na porta que o primeiro ganhou (a porta 0 daria uma a cada endereço) ou na já
        escolhida (a de antes de :meth:`trocar_chave_do_host`, ou a de outro servidor, em outro endereço)."""
        for endereco in self.enderecos:
            servidor = await asyncssh.create_server(
                lambda: _Servidor(self), endereco, self.porta,
                server_host_keys=[k for k in (self.chave_rsa, self.chave_do_host) if k is not None],
                process_factory=self._rodar, encoding=None, reuse_address=True)
            self._servidores.append(servidor)
            self.porta = servidor.sockets[0].getsockname()[1]
        return self

    async def parar(self) -> None:
        """Derruba as conexões e para de escutar; volta com todo comando morto e colhido (com o canal fechado, o
        vigia de cada um mata o grupo dele), para nenhum processo sobreviver ao teste."""
        self.derrubar()
        for servidor in self._servidores:
            servidor.close()
            await servidor.wait_closed()
        self._servidores = []
        await asyncio.gather(*self._rodando, return_exceptions=True)

    async def trocar_chave_do_host(self) -> None:
        """A placa regravada: outra chave de host, na mesma porta."""
        await self.parar()
        self.chave_do_host = asyncssh.generate_private_key("ssh-ed25519")
        await self.iniciar()

    def derrubar(self) -> None:
        """Todas as conexões caem de uma vez, sem despedida (o cabo que solta)."""
        for conexao in list(self.conexoes):
            conexao.abort()

    async def __aenter__(self) -> ServidorSSH:
        return await self.iniciar()

    async def __aexit__(self, *_excecao) -> None:
        await self.parar()

    async def _rodar(self, processo: asyncssh.SSHServerProcess) -> None:
        """Um comando num shell de verdade, num grupo de processos só dele, com o stdin, o stdout e o stderr ligados
        ao canal. Se o canal fecha antes (o cliente desistiu, a conexão caiu), o grupo inteiro é morto: o ``dash`` não
        faz ``exec`` do último comando, e um ``sleep 30`` sobreviveria ao shell, com os pipes abertos."""
        tarefa = asyncio.current_task()
        self._rodando.add(tarefa)
        comando = processo.command or ""
        self.comandos.append(comando)
        try:
            shell = await asyncio.create_subprocess_exec(
                "/bin/sh", "-c", comando, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=self.home, env=self.ambiente, start_new_session=True)
            entrada = asyncio.create_task(_bombear_entrada(processo, shell))
            vigia = asyncio.create_task(_matar_quando_o_canal_fechar(processo, shell))
            try:
                await asyncio.gather(_copiar(shell.stdout, processo.stdout), _copiar(shell.stderr, processo.stderr))
                processo.exit(await shell.wait())
            except (asyncssh.Error, OSError):
                pass
            finally:
                entrada.cancel()
                vigia.cancel()
                _matar(shell)
                await shell.wait()
        finally:
            self._rodando.discard(tarefa)


class _Servidor(asyncssh.SSHServer):
    def __init__(self, dono: ServidorSSH):
        self.dono = dono
        self.conexao: asyncssh.SSHServerConnection | None = None

    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
        self.conexao = conn
        self.dono.conexoes.add(conn)

    def connection_lost(self, exc: Exception | None) -> None:
        self.dono.conexoes.discard(self.conexao)

    def begin_auth(self, username: str) -> bool:
        self.dono.autenticacoes.append(("inicio", username))
        if self.dono.authorized_keys.exists():
            self.conexao.set_authorized_keys(str(self.dono.authorized_keys))   # lido de novo a cada conexão
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        certa = username == self.dono.usuario and password == self.dono.senha
        self.dono.autenticacoes.append(("senha", certa))
        return certa

    def connection_requested(self, dest_host: str, dest_port: int, orig_host: str, orig_port: int) -> bool:
        return self.dono.permitir_tunel


def porta_livre() -> int:
    """Uma porta do loopback que ninguém escuta agora: a de uma placa que não responde."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _bombear_entrada(processo: asyncssh.SSHServerProcess, shell: asyncio.subprocess.Process) -> None:
    try:
        while dados := await processo.stdin.read(65536):
            shell.stdin.write(dados)
            await shell.stdin.drain()
    except (asyncssh.Error, OSError):
        pass
    finally:
        shell.stdin.close()


async def _copiar(origem: asyncio.StreamReader, destino) -> None:
    while dados := await origem.read(65536):
        destino.write(dados)


async def _matar_quando_o_canal_fechar(processo: asyncssh.SSHServerProcess, shell: asyncio.subprocess.Process) -> None:
    await processo.channel.wait_closed()
    _matar(shell)


def _matar(shell: asyncio.subprocess.Process) -> None:
    """O shell e o que ele rodou (o grupo dele), se ainda está de pé."""
    if shell.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(shell.pid, signal.SIGKILL)
