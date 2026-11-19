"""A placa simulada servida por SSH (docs/gui-plan.md, 11.11; a F3.9): :class:`ServidorDoSimulador`, em 127.0.0.1, numa
porta livre, com o mesmo protocolo da de verdade, sobre a árvore do ``simulador.py``. Cada comando roda num shell deste
computador, com o home e a raiz da placa simulada; o ``sudo``, o ``config-pin`` e o ``pgrep`` são os dela. O SFTP
passa na vazão do USB (as transferências levam o tempo que levariam), e no cenário ``conexao_instavel`` a conexão cai.
Precisa do asyncssh (o extra ``placa``).

**A segurança:** o servidor só escuta no 127.0.0.1 e só aceita a chave gerada para ele (:meth:`ServidorDoSimulador.
acesso`, na pasta dele, que só o dono lê); sem a ``senha`` (a dos testes), ninguém entra com senha. Os comandos
rodam neste computador, como o usuário do aplicativo: por isso a interface não abre um terminal no simulador. O shell
é o POSIX (``/bin/sh``): no Windows, não há simulador.

**A placa que para leva as capturas junto** (:meth:`ServidorDoSimulador.parar`): cada comando morre com o canal dele,
menos a captura no cartão, que o ``setsid`` solta da conexão de propósito (``captura_no_cartao.py``). Como a placa de
verdade desligada, o simulador que para mata as que ainda rodam: senão, uma captura "até parar" na placa simulada
seguiria neste computador depois do aplicativo fechar.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

import asyncssh

from .destino import SENHA_PADRAO_DA_IMAGEM, Destino
from .simulador import aplicar_o_boot, montar_sistema_falso, programas_da_placa
from .tarefas import PASTA_DAS_TAREFAS

if TYPE_CHECKING:
    from .chaves import ChaveDoAplicativo, HostsConhecidos

VAZAO_DO_USB_BYTES_S = 5_200_000
"""O SFTP da placa de verdade pelo USB (docs/gui-progress.md, seção 5): as transferências do simulador levam o mesmo
tempo."""
QUEDA_A_CADA_S = 45.0
FRACAO_DA_QUEDA = 0.4
"""No cenário ``conexao_instavel``: cada conexão cai depois de :data:`QUEDA_A_CADA_S`, e cada arquivo, na primeira vez
que é lido além desta fração dele (a retomada continua do ponto em que parou)."""


TEMPO_DO_BOOT_S = 6.0
"""Quanto a placa simulada leva para voltar de um reinício (a de verdade, ~40 s até o SSH)."""
INTERVALO_DOS_PEDIDOS_S = 0.2
SENHA_TROCADA = ".senha-da-placa"
"""No home da placa simulada: a senha que o ``chpasswd`` dela pôs (a do sudo e a do SSH, daí em diante)."""

PASTA_EM_CURSO = ".em_curso"
"""A pasta das capturas no cartão em curso, na pasta do firmware (a ``PASTA_EM_CURSO`` do ``captura_no_cartao.py``)."""

SUDO = r"""#!/bin/sh
# O sudo da placa simulada: -A (a senha pelo SUDO_ASKPASS), -v (só validar), -n (sem perguntar), -k (esquecer).
# Sem terminal, a credencial do sudo é do processo pai (o shell que validou), conferido na hora: o sudo de verdade
# leva uns décimos para começar na BeagleBone, e um "sudo -n ... &" cujo shell saiu nesse meio-tempo já é do init.
pai() { set -- $(sed 's/^.*) //' "/proc/$$/stat" 2>/dev/null); echo "${2:-$PPID}"; }
[ "$1" = "-k" ] && { rm -f "$HOME/.sudo-validado.$(pai)"; exit 0; }
validar=0
while [ $# -gt 0 ]; do
    case "$1" in
        -v) validar=1 ;;
        -p) shift ;;
        --) shift; break ;;
        -*) ;;
        *) break ;;
    esac
    shift
done
if [ "$validar" = 1 ]; then
    [ -x "$SUDO_ASKPASS" ] || { echo "sudo: no askpass program specified" >&2; exit 1; }
    senha=$(cat "$HOME/.senha-da-placa" 2>/dev/null || printf '%s' "$SHAN_SENHA_DO_SUDO")
    if [ "$("$SUDO_ASKPASS")" != "$senha" ]; then
        echo "Sorry, try again." >&2
        echo "sudo: 1 incorrect password attempt" >&2
        exit 1
    fi
    touch "$HOME/.sudo-validado.$(pai)"
    exit 0
fi
sleep 0.1
[ -f "$HOME/.sudo-validado.$(pai)" ] || { echo "sudo: a password is required" >&2; exit 1; }
printf '%s\0' "$*" >> "$HOME/.sudo-comandos"
exec env SHAN_COMO_ROOT=1 "$@"
"""
"""O sudo da placa simulada: faz o que o de verdade faz com ``-A``, ``-v``, ``-n`` e ``-k`` (a senha pelo
``SUDO_ASKPASS``, a credencial validada e esquecida; sem terminal, a credencial é do processo pai, conferido na hora,
como na placa de verdade: um ``sudo -n`` numa função chamada num pipe, num subshell, não a tem, nem o ``sudo -n ... &``
cujo shell já saiu) e roda o comando como o usuário deste computador (na raiz falsa:
o acerto do relógio escreve o desvio dela, e não mexe no relógio daqui), com ``SHAN_COMO_ROOT=1``: os programas dela
que só o root roda (o ``systemctl reboot``, o ``chpasswd``) recusam sem ele, como os de verdade."""

CONFIG_PIN = r"""#!/bin/sh
# O config-pin da placa simulada: o modo no pinmux da árvore falsa.
[ $# -eq 2 ] || { echo "Usage: config-pin <pin> <mode>" >&2; exit 1; }
estado="$SHAN_RAIZ/sys/devices/platform/ocp/ocp:$1_pinmux/state"
[ -f "$estado" ] || { echo "ERROR: open() for $estado failed, No such file or directory" >&2; exit 1; }
printf '%s
' "$2" > "$estado"
"""

PGREP = r"""#!{python}
# O pgrep da placa simulada: o de verdade, só com os processos desta placa (os de executável dentro da pasta dos
# processos dela, SHAN_PROCESSOS, ou os que os comandos dela lançaram, com o SHAN_PROCESSOS dela no ambiente): um
# programa deste computador com o mesmo nome não é uma captura na placa.
import os, subprocess, sys

raiz = os.path.realpath(os.environ["SHAN_PROCESSOS"]) + os.sep


def desta_placa(pid):
    try:
        if os.path.realpath(f"/proc/{{pid}}/exe").startswith(raiz):
            return True
        with open(f"/proc/{{pid}}/environ", "rb") as f:
            ambiente = f.read().split(b"\0")
    except OSError:
        return False
    for variavel in ambiente:
        if variavel.startswith(b"SHAN_PROCESSOS="):
            return os.path.realpath(variavel[15:].decode("utf-8", "replace")) + os.sep == raiz
    return False


r = subprocess.run([{pgrep!r}, *sys.argv[1:]], capture_output=True, text=True)
linhas = [linha for linha in r.stdout.splitlines() if desta_placa(linha.split()[0])]
sys.stdout.write("".join(linha + "\n" for linha in linhas))
sys.exit(0 if linhas else 1)
"""


class ServidorDoSimulador:
    """A placa simulada (:func:`montar_sistema_falso`) servida por SSH, neste computador. ``await iniciar()`` escuta;
    :meth:`acesso` dá a chave e o ``known_hosts`` com que o aplicativo entra (a :class:`~sh_placa.conexao.ConexaoSSH`
    de sempre, para :attr:`destino`); :meth:`fechar` para e apaga a pasta, se foi ele que a criou.

    ``pasta``: onde montar a placa (``None``: uma temporária); ``senha``: a do usuário pelo SSH (``None``: só a chave;
    os testes da primeira conexão dão uma); ``senha_do_sudo``: a que o sudo da placa pede (a padrão da imagem);
    ``enderecos``: onde escutar (vários, como a placa nos dois IPs do USB), na mesma porta; ``processos``: a pasta dos
    executáveis que o ``pgrep`` dela vê (a dela, por padrão); ``vazao_bytes_s``: a do SFTP (``None``: sem limite).
    Para o que roda nela: :attr:`comandos` e :attr:`comandos_de_root`; :meth:`derrubar` (o cabo que solta)."""

    def __init__(self, pasta: Path | None = None, cenario: str = "normal", *, usuario: str = "debian",
                 senha: str | None = None, senha_do_sudo: str = SENHA_PADRAO_DA_IMAGEM,
                 enderecos: tuple[str, ...] = ("127.0.0.1",), processos: Path | None = None,
                 amostras_por_bloco: int | None = None, vazao_bytes_s: float | None = VAZAO_DO_USB_BYTES_S,
                 tempo_do_boot_s: float = TEMPO_DO_BOOT_S):
        if sys.platform == "win32":
            raise RuntimeError("o simulador da placa precisa de um shell POSIX (/bin/sh): no Windows, não há")
        self._temporaria = pasta is None
        self.pasta = Path(tempfile.mkdtemp(prefix="sh-placa-simulada-")) if pasta is None else Path(pasta)
        try:
            self.raiz, firmware = montar_sistema_falso(self.pasta, cenario, amostras_por_bloco=amostras_por_bloco)
        except BaseException:
            if self._temporaria:
                shutil.rmtree(self.pasta, ignore_errors=True)
            raise
        self.cenario, self.usuario, self.senha = cenario, usuario, senha
        self.senha_do_sudo, self.enderecos, self.vazao_bytes_s = senha_do_sudo, enderecos, vazao_bytes_s
        self.home = firmware.parent
        self.comandos: list[str] = []
        self.conexoes: set[asyncssh.SSHServerConnection] = set()
        self._rodando: set[asyncio.Task] = set()            # os comandos ainda rodando (o _rodar de cada um)
        self._servidores: list[asyncssh.SSHAcceptor] = []
        self._livre_em = 0.0                               # quando o "cabo" fica livre de novo (a vazão do SFTP)
        self._ja_caiu: set[str] = set()                    # os arquivos que já cortaram uma transferência
        self.tempo_do_boot_s = tempo_do_boot_s
        self.desligada = False                             # o systemctl poweroff: só volta com ligar()
        self._cpu: list[int] | None = None                 # o /proc/stat que anda (_avancar_o_processador)
        self.reinicios = 0
        self._vigia: asyncio.Task | None = None            # o que atende os pedidos de reiniciar e desligar
        self._reiniciando: asyncio.Task | None = None
        self.porta = 0
        self.chave_do_host = asyncssh.generate_private_key("ssh-ed25519")
        binarios = self.pasta / "bin"
        binarios.mkdir(exist_ok=True)
        (binarios / "python3").symlink_to(sys.executable)
        pgrep = PGREP.format(python=sys.executable, pgrep=shutil.which("pgrep") or "/usr/bin/pgrep")
        programas = {"sudo": SUDO, "config-pin": CONFIG_PIN, "pgrep": pgrep, **programas_da_placa(SENHA_TROCADA)}
        for nome, roteiro in programas.items():
            (binarios / nome).write_text(roteiro)
            (binarios / nome).chmod(0o755)
        self.ram = self.pasta / "ram"                    # a /dev/shm da placa (o SHAN_RAM do sudo)
        self.ram.mkdir(exist_ok=True)
        self.ambiente = {"HOME": str(self.home), "PATH": f"{binarios}{os.pathsep}{os.environ.get('PATH', '')}",
                         "SHAN_RAIZ": str(self.raiz), "LANG": "C.UTF-8", "SHAN_SENHA_DO_SUDO": self.senha_do_sudo,
                         "SHAN_RAM": str(self.ram),
                         "SHAN_PROCESSOS": str(processos if processos is not None else self.pasta)}

    @property
    def destino(self) -> Destino:
        return Destino(self.enderecos[0], self.porta, self.usuario)

    @property
    def authorized_keys(self) -> Path:
        return self.home / ".ssh" / "authorized_keys"

    @property
    def comandos_de_root(self) -> list[str]:
        """O que o sudo rodou: os argumentos de cada comando, juntos (um comando de várias linhas é um só)."""
        arquivo = self.home / ".sudo-comandos"
        return arquivo.read_text().split("\0")[:-1] if arquivo.exists() else []

    @property
    def impressao(self) -> str:
        return self.chave_do_host.get_fingerprint()

    def acesso(self) -> tuple[ChaveDoAplicativo, HostsConhecidos]:
        """A chave e o ``known_hosts`` com que o aplicativo entra (gerados na primeira vez, numa pasta só do dono, dentro
        da do simulador): a chave fica no ``authorized_keys`` da placa, e a chave de host, fixada. Depois do
        :meth:`iniciar` (a porta faz parte do nome no ``known_hosts``)."""
        from .chaves import ChaveDoAplicativo, HostsConhecidos

        pasta = self.pasta / "cliente"
        chave = ChaveDoAplicativo(pasta)
        linha = chave.linha_publica
        self.authorized_keys.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        ja = self.authorized_keys.read_text().splitlines() if self.authorized_keys.exists() else []
        if linha not in ja:
            with open(self.authorized_keys, "a", encoding="ascii") as f:
                f.write(linha + "\n")
            self.authorized_keys.chmod(0o600)
        hosts = HostsConhecidos(pasta / "known_hosts")
        hosts.fixar(self.destino.host, self.porta, self.chave_do_host)
        return chave, hosts

    async def iniciar(self) -> ServidorDoSimulador:
        """Escuta em cada endereço, na porta que o primeiro ganhou (a porta 0 daria uma a cada endereço) ou na já
        escolhida."""
        for endereco in self.enderecos:
            servidor = await asyncssh.create_server(
                self._lado_do_servidor, endereco, self.porta, server_host_keys=self._chaves_do_host(),
                process_factory=self._rodar, encoding=None, reuse_address=True,
                sftp_factory=lambda canal: _SFTPDoSimulador(canal, self),
                line_editor=False)               # o PTY é o do sistema, como o sshd da placa
            self._servidores.append(servidor)
            self.porta = servidor.sockets[0].getsockname()[1]
        self.desligada = False
        if self._vigia is None:
            self._vigia = asyncio.create_task(self._vigiar_os_pedidos())
        return self

    # ------------------------------------------------------------------ reiniciar e desligar

    @property
    def pedido(self) -> Path:
        """O pedido do ``systemctl reboot`` ou ``poweroff`` da placa, que :meth:`_vigiar_os_pedidos` atende."""
        return self.raiz / "run" / "simulador" / "pedido"

    def _avancar_o_processador(self) -> None:
        """O ``/proc/stat`` da placa anda, como o de uma placa ligada: 100 jiffies por segundo (um núcleo), com uma
        ocupação plausível (de 8 a 20 %, numa onda lenta), para o monitor ter o que mostrar. Gravado de uma vez (o
        agente nunca lê um pela metade)."""
        arquivo = self.raiz / "proc" / "stat"
        if self._cpu is None:
            try:
                self._cpu = [int(x) for x in arquivo.read_text().splitlines()[0].split()[1:]]
            except (OSError, ValueError, IndexError):
                return
        jiffies = round(INTERVALO_DOS_PEDIDOS_S * 100)
        ocupados = round(jiffies * (0.14 + 0.06 * math.sin(time.monotonic() / 7.0)))
        self._cpu[0] += ocupados
        self._cpu[3] += jiffies - ocupados
        linha = " ".join(map(str, self._cpu))
        novo = arquivo.with_name("stat.novo")
        try:
            novo.write_text(f"cpu  {linha}\ncpu0 {linha}\n")
            os.replace(novo, arquivo)
        except OSError:
            pass

    async def _vigiar_os_pedidos(self) -> None:
        while True:
            await asyncio.sleep(INTERVALO_DOS_PEDIDOS_S)
            self._avancar_o_processador()
            try:
                pedido = self.pedido.read_text().strip()
            except OSError:
                continue
            self.pedido.unlink(missing_ok=True)
            if pedido == "reboot" and self._reiniciando is None:
                self._reiniciando = asyncio.create_task(self.reiniciar())
            elif pedido == "poweroff":
                await self.desligar()

    async def _cair(self) -> None:
        """A placa some da rede: as conexões caem, a escuta para, e tudo o que rodava nela morre."""
        self.derrubar()
        for servidor in self._servidores:
            servidor.close()
            await servidor.wait_closed()
        self._servidores = []
        await asyncio.gather(*self._rodando, return_exceptions=True)
        await asyncio.to_thread(self._parar_o_que_roda_destacado)

    async def reiniciar(self) -> None:
        """O reinício (o ``systemctl reboot`` da placa): cai, fica fora :attr:`tempo_do_boot_s` e volta pelo boot do
        ``uEnv.txt`` (``aplicar_o_boot``), escutando na mesma porta."""
        try:
            await self._cair()
            await asyncio.sleep(self.tempo_do_boot_s)
            await asyncio.to_thread(aplicar_o_boot, self.raiz, self.tempo_do_boot_s)
            await self.iniciar()
            self.reinicios += 1                            # só depois de escutar: quem espera por ele já conecta
        finally:
            self._reiniciando = None

    async def desligar(self) -> None:
        """O desligar (o ``systemctl poweroff``): cai e não volta, até :meth:`ligar`."""
        await self._cair()
        self.desligada = True

    async def ligar(self) -> ServidorDoSimulador:
        """A placa desligada ligada de novo (alguém na bancada): o boot e a escuta na mesma porta."""
        await asyncio.to_thread(aplicar_o_boot, self.raiz, 600.0)
        return await self.iniciar()

    async def parar(self) -> None:
        """Derruba as conexões e para de escutar; volta com todo comando morto e colhido (com o canal fechado, o
        vigia de cada um mata o grupo dele), para nenhum processo sobreviver à placa."""
        for tarefa in (self._vigia, self._reiniciando):
            if tarefa is not None:
                tarefa.cancel()
                await asyncio.gather(tarefa, return_exceptions=True)
        self._vigia = self._reiniciando = None
        await self._cair()

    def _parar_o_que_roda_destacado(self) -> None:
        self._parar_as_capturas_no_cartao()
        self._parar_as_tarefas()
        self._parar_os_processos_da_placa()

    def _parar_os_processos_da_placa(self) -> None:
        """O que ainda roda e foi lançado pelos comandos desta placa (o ``SHAN_RAIZ`` dela no ambiente: um ``ler_adc``
        destacado do terminal, que nem a captura nem as tarefas conhecem). A placa de verdade, desligada, não deixa
        nada rodando; a simulada, fechada, também não."""
        marca = f"SHAN_RAIZ={self.raiz}".encode()
        eu = os.getpid()
        for nome in os.listdir("/proc") if os.path.isdir("/proc") else ():
            if not nome.isdigit() or int(nome) == eu:
                continue
            try:
                with open(f"/proc/{nome}/environ", "rb") as f:
                    ambiente = f.read().split(b"\0")
            except OSError:
                continue
            if marca in ambiente:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.kill(int(nome), signal.SIGKILL)

    def _parar_as_tarefas(self) -> None:
        """As tarefas destacadas que ainda rodam (``sh_placa/tarefas.py``: o ``rodar.sh``, líder do grupo do
        ``setsid``), conferidas pelo ``ps`` antes."""
        for arquivo in self.home.glob(f"{PASTA_DAS_TAREFAS}/*/pid"):
            if (arquivo.parent / "codigo").exists():
                continue
            try:
                pid = int(arquivo.read_text().strip())
                saida = subprocess.run(["ps", "-o", "args=", "-p", str(pid)], capture_output=True, text=True,
                                       timeout=5).stdout
            except (OSError, ValueError, subprocess.SubprocessError):
                continue
            if "rodar.sh" in saida:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(pid, signal.SIGKILL)

    def _parar_as_capturas_no_cartao(self) -> None:
        """As capturas no cartão que ainda rodam na placa simulada (sem o ``codigo``): o grupo de cada uma (o shell
        do ``setsid`` e o ``ler_adc``), conferido pelo ``ps`` antes (um PID de uma captura antiga pode ser de outro
        processo agora)."""
        for arquivo in self.home.glob(f"*/{PASTA_EM_CURSO}/*/pid"):
            if (arquivo.parent / "codigo").exists():
                continue
            try:
                pid = int(arquivo.read_text().strip())
            except (OSError, ValueError):
                continue
            grupo = _grupo_do_ler_adc(pid)
            if grupo is not None:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(grupo, signal.SIGKILL)

    async def fechar(self) -> None:
        """Para e, se a pasta é dele (a temporária), a apaga."""
        await self.parar()
        if self._temporaria:
            await asyncio.to_thread(shutil.rmtree, self.pasta, True)

    def derrubar(self) -> None:
        """Todas as conexões caem de uma vez, sem despedida (o cabo que solta)."""
        for conexao in list(self.conexoes):
            conexao.abort()

    async def __aenter__(self) -> ServidorDoSimulador:
        return await self.iniciar()

    async def __aexit__(self, *_excecao) -> None:
        await self.parar()

    # ------------------------------------------------------------------ o que os testes trocam

    def _lado_do_servidor(self) -> asyncssh.SSHServer:
        return _LadoDoServidor(self)

    def _chaves_do_host(self) -> list[asyncssh.SSHKey]:
        return [self.chave_do_host]

    async def _sem_comando(self, processo: asyncssh.SSHServerProcess) -> None:
        """O ``ssh`` sem comando (um terminal): a placa simulada não tem, porque o shell seria o deste computador."""
        processo.stderr.write(b"o simulador da placa nao tem terminal: o shell seria o deste computador\n")
        processo.exit(1)

    # ------------------------------------------------------------------ os comandos

    async def _rodar(self, processo: asyncssh.SSHServerProcess) -> None:
        """Um comando num shell de verdade, num grupo de processos só dele, com o stdin, o stdout e o stderr ligados
        ao canal. Se o canal fecha antes (o cliente desistiu, a conexão caiu), o grupo inteiro é morto: o ``dash`` não
        faz ``exec`` do último comando, e um ``sleep 30`` sobreviveria ao shell, com os pipes abertos."""
        tarefa = asyncio.current_task()
        self._rodando.add(tarefa)
        try:
            if processo.command is None:
                await self._sem_comando(processo)
            else:
                await self._rodar_comando(processo)
        finally:
            self._rodando.discard(tarefa)

    async def _rodar_comando(self, processo: asyncssh.SSHServerProcess) -> None:
        comando = processo.command
        self.comandos.append(comando)
        shell = await asyncio.create_subprocess_exec(
            "/bin/sh", "-c", comando, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=self.home, env=self.ambiente, start_new_session=True)
        entrada = asyncio.create_task(_bombear_entrada(processo, shell))
        vigia = asyncio.create_task(matar_quando_o_canal_fechar(processo, shell))
        copias = [asyncio.create_task(_copiar(shell.stdout, processo.stdout)),
                  asyncio.create_task(_copiar(shell.stderr, processo.stderr))]
        try:
            await asyncio.gather(*copias)
            processo.exit(await shell.wait())
        except (asyncssh.Error, OSError):
            pass
        finally:
            for auxiliar in (entrada, vigia, *copias):
                auxiliar.cancel()
            matar(shell)
            shell.stdin.close()
            await asyncio.gather(entrada, vigia, *copias, return_exceptions=True)
            # O que sobrou nos pipes (um comando cortado no meio: o cliente fechou o canal e a cópia parou) é lido até
            # o fim, com o grupo já morto: os transportes do subprocesso fecham com o laço vivo, e não no coletor de
            # lixo, depois dele (um aviso no Python 3.10).
            await asyncio.gather(shell.stdout.read(), shell.stderr.read(), return_exceptions=True)
            await shell.wait()

    # ------------------------------------------------------------------ o SFTP

    async def _esperar_a_vazao(self, n: int) -> None:
        """Os ``n`` bytes passam pelo "cabo" na :attr:`vazao_bytes_s`, um bloco depois do outro (os pedidos em paralelo
        do SFTP dividem a vazão, como no USB)."""
        if not self.vazao_bytes_s or n <= 0:
            return
        agora = asyncio.get_running_loop().time()
        self._livre_em = max(agora, self._livre_em) + n / self.vazao_bytes_s
        await asyncio.sleep(self._livre_em - agora)

    def _leu(self, caminho: str, ate: int, tamanho: int) -> None:
        """No cenário da conexão que cai: a primeira leitura de um arquivo além de :data:`FRACAO_DA_QUEDA` dele derruba
        tudo (logo depois de a resposta sair)."""
        if self.cenario != "conexao_instavel" or not tamanho or caminho in self._ja_caiu:
            return
        if ate >= FRACAO_DA_QUEDA * tamanho:
            self._ja_caiu.add(caminho)
            asyncio.get_running_loop().call_soon(self.derrubar)


class _LadoDoServidor(asyncssh.SSHServer):
    """A autenticação (as chaves do ``authorized_keys`` da placa; a senha, se houver) e as conexões abertas."""

    def __init__(self, dono: ServidorDoSimulador):
        self.dono = dono
        self.conexao: asyncssh.SSHServerConnection | None = None
        self._queda: asyncio.TimerHandle | None = None

    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
        self.conexao = conn
        self.dono.conexoes.add(conn)
        if self.dono.cenario == "conexao_instavel":
            self._queda = asyncio.get_running_loop().call_later(QUEDA_A_CADA_S, conn.abort)

    def connection_lost(self, exc: Exception | None) -> None:
        self.dono.conexoes.discard(self.conexao)
        if self._queda is not None:
            self._queda.cancel()

    def begin_auth(self, username: str) -> bool:
        if self.dono.authorized_keys.exists():
            self.conexao.set_authorized_keys(str(self.dono.authorized_keys))   # lido de novo a cada conexão
        return True

    def password_auth_supported(self) -> bool:
        return self.dono.senha is not None

    def validate_password(self, username: str, password: str) -> bool:
        trocada = self.dono.home / SENHA_TROCADA          # a do chpasswd da placa, se ela trocou
        senha = trocada.read_text() if trocada.exists() else self.dono.senha
        return senha is not None and username == self.dono.usuario and password == senha


class _SFTPDoSimulador(asyncssh.SFTPServer):
    """O SFTP da placa: o do asyncssh, na vazão do USB, e com a queda no meio do cenário da conexão que cai."""

    def __init__(self, canal: asyncssh.SSHServerChannel, dono: ServidorDoSimulador):
        super().__init__(canal)
        self.dono = dono
        self._abertos: dict[object, tuple[str, int]] = {}

    def open(self, path: bytes, pflags: int, attrs: asyncssh.SFTPAttrs) -> object:
        arquivo = super().open(path, pflags, attrs)
        with contextlib.suppress(OSError, AttributeError):
            self._abertos[arquivo] = (os.fsdecode(path), os.fstat(arquivo.fileno()).st_size)
        return arquivo

    def close(self, file_obj: object) -> None:
        self._abertos.pop(file_obj, None)
        super().close(file_obj)

    async def read(self, file_obj: object, offset: int, size: int) -> bytes:
        dados = super().read(file_obj, offset, size)
        await self.dono._esperar_a_vazao(len(dados))
        caminho, tamanho = self._abertos.get(file_obj, ("", 0))
        self.dono._leu(caminho, offset + len(dados), tamanho)
        return dados


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


async def matar_quando_o_canal_fechar(processo: asyncssh.SSHServerProcess, shell: asyncio.subprocess.Process) -> None:
    await processo.channel.wait_closed()
    matar(shell)


def _grupo_do_ler_adc(pid: int) -> int | None:
    """O grupo do processo ``pid``, se ele é um ``ler_adc`` (o ``ps`` do POSIX: o Linux e o macOS)."""
    try:
        saida = subprocess.run(["ps", "-o", "pgid=,args=", "-p", str(pid)], capture_output=True, text=True,
                               timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    grupo, _, comando = saida.partition(" ")
    if not grupo.isdigit() or "ler_adc" not in comando:
        return None
    return int(grupo)


def matar(shell: asyncio.subprocess.Process) -> None:
    """O shell e o que ele rodou (o grupo dele), se ainda está de pé."""
    if shell.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(shell.pid, signal.SIGKILL)
