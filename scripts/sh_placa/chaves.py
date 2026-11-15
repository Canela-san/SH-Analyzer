"""As chaves e as senhas da conexão com a placa (docs/gui-plan.md, 4.3 e 11.3).

* :class:`ChaveDoAplicativo` -- a chave ``ed25519`` do aplicativo, gerada na primeira vez numa pasta que só o dono
  lê, e instalada na placa na primeira conexão (o equivalente do ``ssh-copy-id``). Depois dela, a senha não é mais
  pedida;
* :class:`HostsConhecidos` -- a chave de host de cada placa, confirmada pelo usuário na primeira vez (TOFU) e fixada.
  O arquivo tem o formato do ``known_hosts`` do OpenSSH: o terminal do sistema (F3.8) usa o mesmo, com
  ``-o UserKnownHostsFile``, e ninguém confia numa placa duas vezes;
* :class:`CofreDeSenhas` -- as senhas, só no cofre do sistema (o ``keyring``: o Secret Service no Linux, o Credential
  Manager no Windows), nunca num arquivo, num log ou numa linha de comando.

As chamadas ao cofre podem esperar (o cofre trancado pede a senha do usuário): rode-as fora da thread da interface.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

import asyncssh
import keyring
import keyring.errors

from .agente import ErroDaPlaca

NOME_DA_CHAVE = "id_ed25519"


def _gravar_so_para_o_dono(caminho: Path, dados: bytes) -> None:
    """Grava ``dados`` com a permissão 0600 desde o primeiro byte (o arquivo temporário já nasce assim) e troca o
    arquivo de uma vez: nunca há um instante em que outro usuário leia, nem um arquivo pela metade. No Windows, a
    permissão é a da pasta do usuário, que já é só dele."""
    caminho.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporario = caminho.with_name(f".{caminho.name}.{os.getpid()}.tmp")
    descritor = os.open(temporario, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descritor, "wb") as arquivo:
            arquivo.write(dados)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, caminho)
    except BaseException:
        temporario.unlink(missing_ok=True)
        raise


class ChaveDoAplicativo:
    """A chave em ``pasta/id_ed25519`` (e o ``.pub`` ao lado). :meth:`carregar` a gera se ainda não existe."""

    def __init__(self, pasta: Path):
        self.pasta = Path(pasta)
        self._chave: asyncssh.SSHKey | None = None

    @property
    def caminho(self) -> Path:
        return self.pasta / NOME_DA_CHAVE

    def carregar(self) -> asyncssh.SSHKey:
        if self._chave is not None:
            return self._chave
        if self.caminho.exists():
            try:
                self._chave = asyncssh.read_private_key(self.caminho)
            except (OSError, asyncssh.KeyImportError) as e:
                raise ErroDaPlaca(f"não deu para ler a chave do aplicativo em {self.caminho}: {e}") from e
        else:
            chave = asyncssh.generate_private_key("ssh-ed25519", comment=f"sh-analyzer@{socket.gethostname()}")
            _gravar_so_para_o_dono(self.caminho, chave.export_private_key("openssh"))
            _gravar_so_para_o_dono(self.caminho.with_suffix(".pub"), chave.export_public_key("openssh"))
            self._chave = chave
        return self._chave

    @property
    def linha_publica(self) -> str:
        """A linha do ``authorized_keys``: ``ssh-ed25519 AAAA… sh-analyzer@máquina``."""
        return self.carregar().export_public_key("openssh").decode("ascii").strip()

    @property
    def impressao(self) -> str:
        return self.carregar().get_fingerprint()


def nome_no_known_hosts(host: str, porta: int) -> str:
    """Como o OpenSSH escreve o host: ``192.168.6.2``, ou ``[192.168.6.2]:2222`` fora da porta 22."""
    return host if porta == 22 else f"[{host}]:{porta}"


class HostsConhecidos:
    """As chaves de host fixadas, uma linha por host (``host tipo base64``). Só as linhas deste aplicativo: um
    ``known_hosts`` à parte do do usuário."""

    def __init__(self, arquivo: Path):
        self.arquivo = Path(arquivo)

    def _linhas(self) -> list[str]:
        try:
            return self.arquivo.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []

    def chave_de(self, host: str, porta: int = 22) -> asyncssh.SSHKey | None:
        nome = nome_no_known_hosts(host, porta)
        for linha in self._linhas():
            campos = linha.split()
            if len(campos) >= 3 and not linha.startswith("#") and nome in campos[0].split(","):
                try:
                    return asyncssh.import_public_key(f"{campos[1]} {campos[2]}")
                except asyncssh.KeyImportError as e:
                    raise ErroDaPlaca(f"a chave de host de {nome} em {self.arquivo} está estragada: {e}") from e
        return None

    def fixar(self, host: str, porta: int, chave: asyncssh.SSHKey) -> None:
        """Fixa ``chave`` para o host (no lugar de uma anterior, que só sai pelo :meth:`esquecer` explícito do
        usuário: quem chama confere antes)."""
        nome = nome_no_known_hosts(host, porta)
        publica = chave.export_public_key("openssh").decode("ascii").split()
        linhas = [linha for linha in self._linhas() if not self._e_do_host(linha, nome)]
        linhas.append(f"{nome} {publica[0]} {publica[1]}")
        _gravar_so_para_o_dono(self.arquivo, ("\n".join(linhas) + "\n").encode("utf-8"))

    def esquecer(self, host: str, porta: int = 22) -> bool:
        """Tira a chave do host (a placa regravada, com outra chave): ``True`` se havia uma."""
        nome = nome_no_known_hosts(host, porta)
        linhas = self._linhas()
        ficam = [linha for linha in linhas if not self._e_do_host(linha, nome)]
        if len(ficam) == len(linhas):
            return False
        _gravar_so_para_o_dono(self.arquivo, ("\n".join(ficam) + "\n" if ficam else "").encode("utf-8"))
        return True

    @staticmethod
    def _e_do_host(linha: str, nome: str) -> bool:
        campos = linha.split()
        return bool(campos) and not linha.startswith("#") and nome in campos[0].split(",")


class CofreDeSenhas:
    """As senhas por conta (``debian@192.168.6.2``), no cofre do sistema. Sem cofre (um sistema sem o Secret Service,
    ou trancado), :meth:`senha` devolve ``None`` e :meth:`guardar` explica por que não guardou."""

    SERVICO = "SH-Analyzer (placa)"

    def __init__(self, servico: str = SERVICO):
        self.servico = servico

    def senha(self, conta: str) -> str | None:
        try:
            return keyring.get_password(self.servico, conta)
        except keyring.errors.KeyringError:
            return None

    def guardar(self, conta: str, senha: str) -> None:
        try:
            keyring.set_password(self.servico, conta, senha)
        except keyring.errors.KeyringError as e:
            raise ErroDaPlaca(f"o cofre de senhas do sistema não guardou a senha de {conta} ({type(e).__name__}): ela "
                              "vale só para esta conexão") from e

    def esquecer(self, conta: str) -> None:
        try:
            keyring.delete_password(self.servico, conta)
        except keyring.errors.PasswordDeleteError:
            pass                                 # não havia
        except keyring.errors.KeyringError as e:
            raise ErroDaPlaca(f"o cofre de senhas do sistema não apagou a senha de {conta} ({type(e).__name__})") from e
