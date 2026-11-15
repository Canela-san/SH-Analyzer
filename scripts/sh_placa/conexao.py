"""A conexão SSH com a placa (docs/gui-plan.md, 4.3, 11.2 e 11.3; AQ-02 e AQ-03), pelo asyncssh, no laço do
``sh_placa`` (``laco.py``).

**Uma conexão por placa, reaproveitada:** cada comando é um canal ``exec`` dela (barato), e o agente roda assim
(``agente.TransporteSSH``). Com um salto (*ProxyJump*, :attr:`Destino.salto`), a conexão com a placa passa por
dentro da do salto. Cada comando vai para o registro de atividade (``registro.py``), com a hora, a duração e o
código de saída, inclusive o que não terminou.

**A chave do host (TOFU):** na primeira vez, a impressão digital vai para ``confirmar_host`` (o diálogo da
interface), e só com o sim ela é fixada (``chaves.HostsConhecidos``); daí em diante, a placa tem de apresentar a
mesma. **Uma chave trocada bloqueia a conexão** antes de qualquer senha ou chave sair daqui
(:class:`ChaveDoHostTrocada`, com as duas impressões e o que fazer).

**A autenticação:** a chave do aplicativo primeiro; se a placa a recusa, a ``senha`` (a do cofre, ou a que o usuário
digitou: a interface pergunta e conecta de novo, sem segurar a conexão aberta enquanto ele digita).
:meth:`ConexaoSSH.instalar_chave` põe a chave do aplicativo na placa (o ``ssh-copy-id``), e a próxima conexão não
precisa de senha. Nada daqui lê o ``~/.ssh`` do usuário, o ``ssh-agent`` ou o ``~/.ssh/config``: a conexão é a que o
aplicativo mostra.

**Os erros** são todos ``ErroDaPlaca`` (a ponte da interface os mostra no lugar certo), com a mensagem pronta: a rede
(:class:`ErroDeConexao`: recusada, sem rota, o tempo e **a conexão que caiu**, o caso comum num cabo USB com mau
contato), a autenticação (:class:`ErroDeAutenticacao`) e a chave do host. Nenhum erro do asyncssh sai daqui. Uma
queda fora de um comando chega pelo ``ao_cair(motivo)``, na thread do laço.

**A cifra:** o ``aes128-ctr`` na frente das outras. Na placa, o limite da vazão é a cifra no único núcleo dela, e essa
é a mais rápida (5,9 MB/s, contra 5,2 da padrão do OpenSSH; docs/gui-progress.md, seção 6).
"""

from __future__ import annotations

import asyncio
import errno
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import asyncssh

from .agente import TEMPO_LIMITE_S, ErroDaPlaca
from .chaves import ChaveDoAplicativo, HostsConhecidos
from .registro import Entrada, RegistroDeAtividade

CIFRAS = "^aes128-ctr"                   # na frente das padrão do asyncssh, sem tirar nenhuma
CHAVES_DE_HOST = "^ssh-ed25519,ecdsa-sha2-nistp256"
"""A ordem do OpenSSH na primeira vez (a do asyncssh põe o RSA na frente): a impressão digital que o usuário confere
é a mesma que o ``ssh`` e o ``ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`` da placa mostram. Depois de fixada,
o asyncssh negocia o tipo da chave fixada."""
TEMPO_PARA_CONECTAR_S = 15.0
INTERVALO_DO_KEEPALIVE_S = 5.0
KEEPALIVES_SEM_RESPOSTA = 3              # ~15 s sem resposta: a conexão caiu

# O ssh-copy-id: o arquivo e a pasta só do dono, uma linha nova se o arquivo não termina numa, e a chave só uma vez.
# A linha vem pelo stdin.
INSTALAR_A_CHAVE = """umask 077
mkdir -p "$HOME/.ssh" || exit 1
arquivo="$HOME/.ssh/authorized_keys"
IFS= read -r linha || exit 2
if [ -f "$arquivo" ] && grep -qxF -- "$linha" "$arquivo"; then echo ja_estava; exit 0; fi
if [ -s "$arquivo" ] && [ -n "$(tail -c 1 "$arquivo")" ]; then echo >> "$arquivo" || exit 1; fi
printf '%s\\n' "$linha" >> "$arquivo" && echo instalada"""


@dataclass(frozen=True)
class Destino:
    """Onde está a placa: o host (ou IP), a porta, o usuário e, se for o caso, o salto."""

    host: str
    porta: int = 22
    usuario: str = "debian"
    salto: Destino | None = None

    @property
    def conta(self) -> str:
        """``debian@192.168.6.2`` (com a porta, fora da 22): a chave do cofre e o nome no registro."""
        return f"{self.usuario}@{self.host}" + ("" if self.porta == 22 else f":{self.porta}")

    def __str__(self) -> str:
        return self.conta if self.salto is None else f"{self.conta} (pelo salto {self.salto})"


@dataclass(frozen=True)
class Resultado:
    codigo: int                  # -1: terminou por um sinal
    saida: str
    erro: str
    duracao_s: float


class ErroDeConexao(ErroDaPlaca):
    """A rede: a conexão recusada, sem rota, sem resposta, ou que caiu."""


class ErroDeAutenticacao(ErroDaPlaca):
    """A placa recusou a chave do aplicativo e a senha (ou não havia senha para tentar)."""


class HostNaoConfirmado(ErroDaPlaca):
    """A primeira conexão com uma placa, sem o sim para a impressão digital dela: nada foi fixado."""


class ChaveDoHostTrocada(ErroDaPlaca):
    """A placa apresentou outra chave de host: a conexão foi bloqueada."""

    def __init__(self, destino: Destino, conhecida: str, apresentada: str | None):
        self.destino, self.conhecida, self.apresentada = destino, conhecida, apresentada
        super().__init__(
            f"A placa em {destino.conta} apresentou uma chave de host diferente da conhecida (a conhecida é "
            f"{conhecida}; a de agora, {apresentada or 'não deu para ler'}). A conexão foi bloqueada antes de qualquer "
            "senha ou chave sair daqui. Se a placa foi regravada (a imagem reinstalada, outro cartão), a chave nova é "
            "esperada: confira a impressão digital na própria placa (ssh-keygen -lf "
            "/etc/ssh/ssh_host_ed25519_key.pub, pelo console), esqueça a chave antiga e conecte de novo. Se não foi, "
            "alguém pode estar no meio da conexão.")


ConfirmarHost = Callable[[Destino, str], Awaitable[bool]]
"""``(destino, impressão digital) -> confia?``: o diálogo da primeira conexão."""


def _motivo_da_rede(e: BaseException, destino: Destino, tempo_s: float) -> str:
    if isinstance(e, ConnectionRefusedError):
        return (f"a placa em {destino.conta} recusou a conexão na porta {destino.porta} (o SSH dela ainda não subiu? "
                "espere uns segundos e tente de novo)")
    if isinstance(e, asyncio.TimeoutError):          # o TimeoutError a partir do 3.11
        return f"a placa em {destino.conta} não respondeu em {tempo_s:g} s (o cabo, a rede ou o endereço)"
    if isinstance(e, socket.gaierror):
        return f"não deu para achar o endereço {destino.host} ({e.strerror or e})"
    if isinstance(e, OSError) and e.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EHOSTDOWN):
        return (f"sem caminho até {destino.host} ({e.strerror}): o cabo USB está ligado, e a rede dele subiu no "
                "computador?")
    if isinstance(e, OSError):
        return f"não deu para conectar a {destino.conta}: {e.strerror or e}"
    return f"não deu para conectar a {destino.conta}: {e}"


class _Cliente(asyncssh.SSHClient):
    """O lado do asyncssh: a senha (uma vez, depois da chave), a autenticação e a queda."""

    def __init__(self, conexao: ConexaoSSH, senha: str | None):
        self._conexao, self._senha = conexao, senha
        self.pediu_a_senha = False

    def password_auth_requested(self) -> str | None:
        if self._senha is None or self.pediu_a_senha:
            return None                          # uma tentativa só: a senha errada não vira um bloqueio na placa
        self.pediu_a_senha = True
        return self._senha

    def connection_lost(self, exc: Exception | None) -> None:
        self._conexao._caiu(exc)


class ConexaoSSH:
    """A conexão com uma placa. :meth:`conectar`, :meth:`executar` (um comando), :meth:`instalar_chave` e
    :meth:`fechar`; também é um gerenciador de contexto assíncrono. Depois de uma queda, :meth:`conectar` abre outra.
    """

    def __init__(self, destino: Destino, *, chave: ChaveDoAplicativo, hosts: HostsConhecidos,
                 registro: RegistroDeAtividade, senha: str | None = None, senha_do_salto: str | None = None,
                 confirmar_host: ConfirmarHost | None = None, ao_cair: Callable[[str], object] | None = None,
                 tempo_para_conectar_s: float = TEMPO_PARA_CONECTAR_S):
        self.destino = destino
        self.chave, self.hosts, self.registro = chave, hosts, registro
        self.senha, self.senha_do_salto = senha, senha_do_salto
        self.confirmar_host, self.ao_cair = confirmar_host, ao_cair
        self.tempo_para_conectar_s = tempo_para_conectar_s
        self.autenticada_com: str | None = None    # "chave" ou "senha", na última conexão
        self._ssh: asyncssh.SSHClientConnection | None = None
        self._salto: ConexaoSSH | None = None
        self._fechando = False

    @property
    def conectada(self) -> bool:
        return self._ssh is not None

    async def __aenter__(self) -> ConexaoSSH:
        await self.conectar()
        return self

    async def __aexit__(self, *_excecao) -> None:
        await self.fechar()

    # ------------------------------------------------------------------ conectar

    async def conectar(self) -> None:
        if self._ssh is not None:
            return
        self._fechando = False
        tunel = None
        if self.destino.salto is not None:
            self._salto = ConexaoSSH(self.destino.salto, chave=self.chave, hosts=self.hosts, registro=self.registro,
                                     senha=self.senha_do_salto, confirmar_host=self.confirmar_host,
                                     tempo_para_conectar_s=self.tempo_para_conectar_s)
            await self._salto.conectar()
            tunel = self._salto._ssh
        try:
            self._ssh, self.autenticada_com = await self._abrir(tunel)
        except BaseException:
            if self._salto is not None:
                await self._salto.fechar()
                self._salto = None
            raise
        como = "a chave do aplicativo" if self.autenticada_com == "chave" else "a senha"
        self._registrar_fato(f"conectado, com {como}" + (f", pelo salto {self.destino.salto}" if tunel else ""))

    async def _abrir(self, tunel: asyncssh.SSHClientConnection | None) -> tuple[asyncssh.SSHClientConnection, str]:
        d = self.destino
        conhecida = self.hosts.chave_de(d.host, d.porta)
        if conhecida is None:
            apresentada = await self._chave_apresentada(tunel)
            impressao = apresentada.get_fingerprint()
            if self.confirmar_host is None or not await self.confirmar_host(d, impressao):
                self._registrar_fato(f"a chave do host não foi confirmada ({impressao}): sem conexão")
                raise HostNaoConfirmado(f"a chave de host de {d.conta} ({impressao}) não foi confirmada: a conexão não "
                                        "foi feita")
            self.hosts.fixar(d.host, d.porta, apresentada)
            self._registrar_fato(f"a chave do host confirmada e fixada: {impressao}")
            conhecida = apresentada
        cliente = _Cliente(self, self.senha)
        try:
            ssh = await asyncssh.connect(
                d.host, d.porta, tunnel=tunel if tunel is not None else (), username=d.usuario,
                known_hosts=([conhecida], [], []), client_factory=lambda: cliente,
                client_keys=[self.chave.carregar()], agent_path=None, config=None, kbdint_auth=False,
                encryption_algs=CIFRAS, keepalive_interval=INTERVALO_DO_KEEPALIVE_S,
                keepalive_count_max=KEEPALIVES_SEM_RESPOSTA, connect_timeout=self.tempo_para_conectar_s)
        except asyncssh.HostKeyNotVerifiable as e:
            try:
                apresentada = (await self._chave_apresentada(tunel)).get_fingerprint()
            except ErroDaPlaca:
                apresentada = None
            self._registrar_fato(f"bloqueada: a chave do host mudou (a conhecida é {conhecida.get_fingerprint()})")
            raise ChaveDoHostTrocada(d, conhecida.get_fingerprint(), apresentada) from e
        except asyncssh.PermissionDenied as e:
            if cliente.pediu_a_senha:
                motivo = f"a placa recusou a senha de {d.conta}"
            elif self.senha is None:
                motivo = (f"a placa não aceitou a chave do aplicativo, e não há senha para tentar: informe a senha de "
                          f"{d.conta} (numa placa nova, a padrão da imagem Debian)")
            else:
                motivo = f"a placa em {d.conta} não aceita a chave do aplicativo nem senha (PasswordAuthentication)"
            raise ErroDeAutenticacao(motivo) from e
        except asyncssh.Error as e:
            raise ErroDeConexao(f"a placa em {d.conta} encerrou a conexão: {e.reason}") from e
        except (OSError, asyncio.TimeoutError) as e:
            raise ErroDeConexao(_motivo_da_rede(e, d, self.tempo_para_conectar_s)) from e
        return ssh, "senha" if cliente.pediu_a_senha else "chave"

    async def _chave_apresentada(self, tunel: asyncssh.SSHClientConnection | None) -> asyncssh.SSHKey:
        """A chave de host que a placa apresenta, por uma troca de chaves sem autenticação (nada sai daqui)."""
        d = self.destino
        try:
            chave = await asyncio.wait_for(asyncssh.get_server_host_key(
                d.host, d.porta, tunnel=tunel if tunel is not None else (), config=None,
                server_host_key_algs=CHAVES_DE_HOST), self.tempo_para_conectar_s)
        except asyncssh.Error as e:
            raise ErroDeConexao(f"a placa em {d.conta} encerrou a conexão: {e.reason}") from e
        except (OSError, asyncio.TimeoutError) as e:
            raise ErroDeConexao(_motivo_da_rede(e, d, self.tempo_para_conectar_s)) from e
        if chave is None:
            raise ErroDeConexao(f"a placa em {d.conta} não apresentou uma chave de host")
        return chave

    # ------------------------------------------------------------------ comandos

    async def executar(self, comando: str, *, entrada: str | None = None, tempo_limite: float = TEMPO_LIMITE_S,
                       descricao: str = "") -> Resultado:
        """Roda ``comando`` num canal novo, com ``entrada`` no stdin, e espera o fim (no máximo ``tempo_limite``).
        Um código de saída diferente de zero é um resultado, não um erro; a rede e o tempo são
        :class:`ErroDeConexao`. No tempo esgotado ou no cancelamento, o comando recebe o ``TERM`` na placa."""
        ssh = self._ssh
        if ssh is None:
            raise ErroDeConexao(f"sem conexão com a placa em {self.destino.conta}: conecte antes")
        inicio, t0 = time.time(), time.monotonic()
        codigo, falha = None, ""
        try:
            async with ssh.create_process(comando, encoding="utf-8", errors="replace") as processo:
                try:
                    saida, erro = await asyncio.wait_for(processo.communicate(entrada), tempo_limite)
                except asyncio.TimeoutError:
                    falha = f"sem resposta em {tempo_limite:g} s"
                    _encerrar(processo)
                    raise ErroDeConexao(f"a placa não respondeu em {tempo_limite:g} s ({descricao or comando})") \
                        from None
                except asyncio.CancelledError:
                    falha = "cancelado"
                    _encerrar(processo)
                    raise
                if processo.exit_status is not None:
                    codigo = processo.exit_status
                elif processo.exit_signal:
                    codigo, falha = -1, f"terminou pelo sinal {processo.exit_signal[0]}"
                else:
                    # O canal acabou sem o código nem o sinal: a conexão caiu (o communicate do asyncssh volta sem
                    # erro, com o que chegou até ali).
                    falha = "a conexão caiu"
                    raise ErroDeConexao(f"a conexão com a placa em {self.destino.conta} caiu durante "
                                        f"{descricao or 'o comando'}")
        except ErroDaPlaca:
            raise
        except (asyncssh.Error, OSError) as e:
            falha = falha or "a conexão caiu"
            raise ErroDeConexao(f"a conexão com a placa em {self.destino.conta} caiu durante "
                                f"{descricao or 'o comando'}") from e
        except BaseException as e:
            falha = falha or type(e).__name__
            raise
        finally:
            self.registro.registrar(Entrada(inicio, self.destino.conta, "comando", descricao or comando, comando,
                                            time.monotonic() - t0, codigo, falha))
        return Resultado(codigo, saida, erro, time.monotonic() - t0)

    async def instalar_chave(self) -> bool:
        """Instala a chave do aplicativo no ``~/.ssh/authorized_keys`` da placa: ``True`` se instalou, ``False`` se
        ela já estava lá (só uma linha, sempre)."""
        r = await self.executar(INSTALAR_A_CHAVE, entrada=self.chave.linha_publica + "\n",
                                descricao=f"instalar a chave do aplicativo ({self.chave.impressao}) no "
                                          "~/.ssh/authorized_keys")
        resposta = r.saida.strip()
        if r.codigo != 0 or resposta not in ("instalada", "ja_estava"):
            raise ErroDaPlaca(f"não deu para instalar a chave do aplicativo na placa (código {r.codigo}): "
                              f"{(r.erro or r.saida).strip()[:200]}")
        return resposta == "instalada"

    # ------------------------------------------------------------------ fechar e cair

    async def fechar(self) -> None:
        self._fechando = True
        ssh, self._ssh = self._ssh, None
        if ssh is not None:
            ssh.close()
            await ssh.wait_closed()
            self._registrar_fato("desconectado")
        if self._salto is not None:
            await self._salto.fechar()
            self._salto = None

    def _caiu(self, exc: Exception | None) -> None:
        """Na thread do laço, quando a conexão acaba. A que nós fechamos, ou que ainda nem abriu, não é uma queda."""
        if self._fechando or self._ssh is None:
            return
        self._ssh = None
        motivo = f"a conexão com a placa em {self.destino.conta} caiu" + (f" ({_texto_do_erro(exc)})" if exc else "")
        self._registrar_fato(motivo)
        if self.ao_cair is not None:
            self.ao_cair(motivo)

    def _registrar_fato(self, descricao: str) -> None:
        self.registro.registrar(Entrada(time.time(), self.destino.conta, "conexao", descricao))


def _encerrar(processo: asyncssh.SSHClientProcess) -> None:
    """O ``TERM`` ao comando na placa (o OpenSSH aceita sinais desde o 7.9; o da imagem Buster é ele)."""
    try:
        processo.terminate()
    except (asyncssh.Error, OSError):
        pass


def _texto_do_erro(exc: BaseException) -> str:
    return getattr(exc, "reason", None) or str(exc) or type(exc).__name__
