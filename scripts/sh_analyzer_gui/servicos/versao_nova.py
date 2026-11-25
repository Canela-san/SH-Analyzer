"""O aviso de versão nova (sem Qt): a consulta às releases do GitHub, a comparação com a versão instalada e, no
Windows, o download do instalador conferido pelo SHA-256.

**O que é consultado:** só ``GET`` em :data:`URL_DA_ULTIMA` (a última release publicada do projeto), com o
``User-Agent: SH-Analyzer/<versão>``; nada do usuário vai junto. A janela consulta no máximo uma vez a cada
:data:`INTERVALO_S`, depois de abrir, numa thread, e se o usuário não desligou nas configurações; um erro (sem rede, o
GitHub fora) é calado: a próxima consulta é no dia seguinte.

**O que o aviso oferece depende de como o aplicativo foi instalado** (:func:`como_foi_instalado`):

- ``windows`` (o instalador do Inno Setup): baixa o instalador da release, confere o SHA-256 com o ``SHA256SUMS`` dela,
  fecha o aplicativo e o roda calado (:func:`comando_do_instalador`), que reabre o aplicativo atualizado;
- ``apt`` (o pacote ``.deb``): a versão nova chega pelo Atualizador do sistema; o aviso só diz isso;
- ``pasta`` (a pasta do ``.tar.gz``, ou o executável fora do instalador): abre a página da release;
- ``dev`` (rodando do código, pelo ``uv``): não consulta nunca.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

PROJETO = "Canela-san/SH-Analyzer"
URL_DA_ULTIMA = f"https://api.github.com/repos/{PROJETO}/releases/latest"
INTERVALO_S = 24 * 3600
PRAZO_S = 5.0
"""O prazo da consulta: sem resposta nele, fica para o dia seguinte."""
PRAZO_DO_DOWNLOAD_S = 30.0
"""O prazo de cada leitura do download (não do download inteiro)."""
BLOCO = 256 * 1024
ARQUIVO_DAS_SOMAS = "SHA256SUMS"
SUFIXO_DO_WINDOWS = "-windows-x64.exe"
PASTA_DO_APT = Path("/opt/sh-analyzer")
LISTA_DO_DPKG = Path("/var/lib/dpkg/info/sh-analyzer.list")
DESINSTALADOR_DO_INNO = "unins000.exe"


class ErroDeAtualizacao(Exception):
    """O download ou a conferência do instalador falhou (a mensagem é para o usuário)."""


@dataclass(frozen=True)
class Arquivo:
    nome: str
    url: str
    tamanho: int


@dataclass(frozen=True)
class Lancamento:
    """Uma release publicada: a versão (sem o ``v``), a página, as notas e os arquivos que importam ao aviso."""

    versao: str
    pagina: str
    notas: str
    instalador_do_windows: Arquivo | None
    somas: Arquivo | None


def numeros(versao: str) -> tuple[int, ...] | None:
    """``v0.9``, ``0.9.0`` e ``0.9.0+git3.gabc`` → ``(0, 9)``: os números, sem os zeros do fim; ``None`` se não for
    uma versão."""
    achado = re.match(r"v?(\d+(?:\.\d+)*)", versao.strip())
    if achado is None:
        return None
    partes = [int(p) for p in achado.group(1).split(".")]
    while len(partes) > 1 and partes[-1] == 0:
        partes.pop()
    return tuple(partes)


def mais_nova(remota: str, local: str) -> bool:
    """Se ``remota`` é posterior a ``local``. Uma versão local de desenvolvimento (``0.9.0+git3``) conta como a
    versão em que se baseia: a release dela não é oferecida de novo."""
    r, l = numeros(remota), numeros(local)  # noqa: E741
    return r is not None and l is not None and r > l


def como_foi_instalado(*, congelado: bool | None = None, plataforma: str = sys.platform,
                       executavel: Path | None = None, lista_do_dpkg: Path = LISTA_DO_DPKG) -> str:
    """``windows``, ``apt``, ``pasta`` ou ``dev`` (ver o começo do módulo)."""
    congelado = getattr(sys, "frozen", False) if congelado is None else congelado
    if not congelado:
        return "dev"
    executavel = Path(sys.executable if executavel is None else executavel)
    if plataforma == "win32":
        return "windows" if (executavel.parent / DESINSTALADOR_DO_INNO).is_file() else "pasta"
    if plataforma.startswith("linux") and executavel.parent == PASTA_DO_APT and lista_do_dpkg.is_file():
        return "apt"
    return "pasta"


def _pedido(url: str, versao_local: str, aceita: str = "application/vnd.github+json") -> urllib.request.Request:
    return urllib.request.Request(url, headers={"Accept": aceita, "User-Agent": f"SH-Analyzer/{versao_local}"})


def ler_lancamento(dados: dict) -> Lancamento | None:
    """A release da resposta da API do GitHub (``None`` para um rascunho, uma pré-versão ou sem versão)."""
    if dados.get("draft") or dados.get("prerelease"):
        return None
    tag = str(dados.get("tag_name") or "")
    if numeros(tag) is None:
        return None
    arquivos = {a.get("name", ""): Arquivo(a.get("name", ""), a.get("browser_download_url", ""), int(a.get("size", 0)))
                for a in dados.get("assets") or []}
    instalador = next((a for nome, a in arquivos.items() if nome.endswith(SUFIXO_DO_WINDOWS)), None)
    return Lancamento(versao=tag.removeprefix("v"), pagina=str(dados.get("html_url") or ""),
                      notas=str(dados.get("body") or ""), instalador_do_windows=instalador,
                      somas=arquivos.get(ARQUIVO_DAS_SOMAS))


def consultar(versao_local: str, url: str = URL_DA_ULTIMA, prazo_s: float = PRAZO_S) -> Lancamento | None:
    """A última release, se for mais nova que ``versao_local``; ``None`` se não houver uma mais nova. Os erros de rede
    e de leitura sobem (``OSError``, ``ValueError``): quem chama decide calar."""
    with urllib.request.urlopen(_pedido(url, versao_local), timeout=prazo_s) as resposta:  # noqa: S310 (https fixo)
        dados = json.loads(resposta.read(2 * 1024 * 1024).decode("utf-8"))
    lancamento = ler_lancamento(dados) if isinstance(dados, dict) else None
    if lancamento is None or not mais_nova(lancamento.versao, versao_local):
        return None
    return lancamento


def soma_esperada(texto_das_somas: str, nome: str) -> str | None:
    """A soma de ``nome`` num ``SHA256SUMS`` (o formato do ``sha256sum``: ``<soma>  <nome>``)."""
    for linha in texto_das_somas.splitlines():
        partes = linha.strip().split(maxsplit=1)
        if len(partes) == 2 and partes[1].lstrip("*") == nome and re.fullmatch(r"[0-9a-fA-F]{64}", partes[0]):
            return partes[0].lower()
    return None


def baixar_instalador(lancamento: Lancamento, versao_local: str, progresso: Callable[[float], None],
                      cancelado: Callable[[], bool], pasta: Path | None = None) -> Path:
    """Baixa o instalador do Windows da release para uma pasta temporária e confere o SHA-256 com o do
    ``SHA256SUMS``. Levanta :class:`ErroDeAtualizacao` (sem o instalador, sem a soma, a soma diferente) e
    ``InterruptedError`` se ``cancelado()``."""
    instalador, somas = lancamento.instalador_do_windows, lancamento.somas
    if instalador is None or somas is None:
        raise ErroDeAtualizacao("a versão nova não tem o instalador do Windows conferível; baixe-o pela página dela")
    with urllib.request.urlopen(_pedido(somas.url, versao_local, "application/octet-stream"),  # noqa: S310
                                timeout=PRAZO_DO_DOWNLOAD_S) as resposta:
        esperada = soma_esperada(resposta.read(1024 * 1024).decode("utf-8", "replace"), instalador.nome)
    if esperada is None:
        raise ErroDeAtualizacao(f"o {ARQUIVO_DAS_SOMAS} da versão nova não tem a soma do {instalador.nome}")
    pasta = Path(tempfile.mkdtemp(prefix="sh-analyzer-atualizacao-")) if pasta is None else Path(pasta)
    destino = pasta / instalador.nome
    resumo = hashlib.sha256()
    lidos = 0
    with urllib.request.urlopen(_pedido(instalador.url, versao_local, "application/octet-stream"),  # noqa: S310
                                timeout=PRAZO_DO_DOWNLOAD_S) as resposta, destino.open("wb") as saida:
        total = int(resposta.headers.get("Content-Length") or instalador.tamanho or 0)
        while bloco := resposta.read(BLOCO):
            if cancelado():
                saida.close()
                destino.unlink(missing_ok=True)
                raise InterruptedError("download cancelado")
            saida.write(bloco)
            resumo.update(bloco)
            lidos += len(bloco)
            if total:
                progresso(min(lidos / total, 1.0))
    if resumo.hexdigest() != esperada:
        destino.unlink(missing_ok=True)
        raise ErroDeAtualizacao("o instalador baixado não confere com a soma publicada (download corrompido?); "
                                "tente de novo")
    return destino


def comando_do_instalador(instalador: Path) -> list[str]:
    """O instalador calado do Inno Setup (``empacotamento/sh-analyzer-gui.iss``): fecha o que estiver aberto, não
    pergunta nada e reabre o aplicativo no fim (``/REABRIR=1``)."""
    return [str(instalador), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/REABRIR=1"]


def iniciar_instalador(instalador: Path) -> subprocess.Popen:
    """Roda o instalador calado, desligado deste processo (ele continua depois que o aplicativo fecha)."""
    bandeiras = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(comando_do_instalador(instalador), creationflags=bandeiras, close_fds=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def deve_consultar(ultima: float | None, agora: float) -> bool:
    """Uma consulta a cada :data:`INTERVALO_S` (``ultima`` no futuro, um relógio que voltou, também consulta)."""
    return ultima is None or not 0 <= agora - ultima < INTERVALO_S
