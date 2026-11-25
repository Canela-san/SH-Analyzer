"""O repositório apt do SH-Analyzer: os ``.deb`` das últimas versões, assinados, na forma que o ``apt`` lê.

    python3 empacotamento/repositorio_apt.py PASTA_DOS_DEBS SAIDA [--chave IMPRESSAO]

grava em SAIDA:

- ``pool/main/s/sh-analyzer/*.deb`` e ``dists/stable/main/binary-amd64/Packages`` (e ``.gz``, ``.xz``);
- ``dists/stable/Release``, assinado em ``InRelease`` e ``Release.gpg`` com a chave do GnuPG (``--chave``, ou a
  única chave secreta do ``GNUPGHOME``);
- ``sh-analyzer.gpg`` (a chave pública, no formato do ``Signed-By``) e ``sh-analyzer.sources`` (a fonte): os mesmos
  arquivos que o pacote instala (``empacotamento/deb.py``), então baixá-los antes de instalar não cria conflito;
- ``index.html``: como instalar.

O ``.github/workflows/apt.yml`` o roda a cada release publicada, com os ``.deb`` das últimas releases, e publica a
SAIDA no GitHub Pages (``deb.URL_DO_REPOSITORIO``). Só o ``apt-ftparchive`` (do pacote ``apt-utils``) e o ``gpg``.
"""

from __future__ import annotations

import argparse
import gzip
import html
import lzma
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deb  # noqa: E402

SUITE = "stable"
COMPONENTE = "main"


def _rodar(*argumentos: str, **opcoes) -> subprocess.CompletedProcess:
    return subprocess.run(argumentos, check=True, capture_output=True, **opcoes)


def instrucoes() -> list[str]:
    """Os comandos de instalação (os do README e os da página)."""
    url = deb.URL_DO_REPOSITORIO
    return [
        f"sudo wget -qO {deb.ARQUIVO_DA_CHAVE} {url}/sh-analyzer.gpg",
        f"sudo wget -qO {deb.ARQUIVO_DA_FONTE} {url}/sh-analyzer.sources",
        "sudo apt update",
        f"sudo apt install {deb.PACOTE}",
    ]


def pagina() -> str:
    comandos = "\n".join(html.escape(c) for c in instrucoes())
    return f"""<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SH-Analyzer: repositório apt</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;color:#1d2433;
background:#fff}}pre{{background:#f2f4f8;padding:1rem;overflow-x:auto;border-radius:6px}}
@media (prefers-color-scheme:dark){{body{{color:#e6e9ef;background:#151821}}pre{{background:#232733}}}}</style>
</head>
<body>
<h1>SH-Analyzer no Ubuntu, Pop!_OS e Debian</h1>
<p>Para instalar (uma vez), num terminal:</p>
<pre>{comandos}</pre>
<p>Depois, o SH-Analyzer fica no menu de aplicativos, e as versões novas chegam pelo Atualizador de Programas do
sistema (ou por <code>sudo apt upgrade</code>).</p>
<p>No Windows, use o instalador da <a href="{deb.URL_DO_PROJETO}/releases/latest">última versão</a>.
O código e o guia estão em <a href="{deb.URL_DO_PROJETO}">{deb.URL_DO_PROJETO}</a>.</p>
</body>
</html>
"""


def montar(debs: list[Path], saida: Path, chave: str | None = None, *, do_gnupg: bool = False) -> Path:
    """O repositório em ``saida`` (apagada antes), assinado; devolve o ``InRelease``. ``do_gnupg``: publica a chave
    pública do GnuPG que assina (uma chave de teste), e não a do projeto."""
    if not debs:
        raise SystemExit("nenhum .deb para o repositório")
    if saida.exists():
        shutil.rmtree(saida)
    pool = saida / "pool" / COMPONENTE / deb.PACOTE[0] / deb.PACOTE
    pool.mkdir(parents=True)
    for arquivo in debs:
        shutil.copy2(arquivo, pool / arquivo.name)
    lista = saida / "dists" / SUITE / COMPONENTE / "binary-amd64"
    lista.mkdir(parents=True)
    pacotes = _rodar("apt-ftparchive", "packages", "pool", cwd=saida).stdout
    (lista / "Packages").write_bytes(pacotes)
    (lista / "Packages.gz").write_bytes(gzip.compress(pacotes, 9, mtime=0))
    (lista / "Packages.xz").write_bytes(lzma.compress(pacotes))
    opcoes = [f"-oAPT::FTPArchive::Release::{campo}={valor}" for campo, valor in (
        ("Origin", "SH-Analyzer"), ("Label", "SH-Analyzer"), ("Suite", SUITE), ("Codename", SUITE),
        ("Architectures", "amd64"), ("Components", COMPONENTE),
        ("Description", "O SH-Analyzer, analisador de supraharmônicos"))]
    dists = saida / "dists" / SUITE
    release = _rodar("apt-ftparchive", *opcoes, "release", ".", cwd=dists).stdout
    (dists / "Release").write_bytes(release)
    assinar = ["gpg", "--batch", "--yes", "--pinentry-mode", "loopback", "--digest-algo", "SHA512"]
    if chave:
        assinar += ["--local-user", chave]
    _rodar(*assinar, "--clearsign", "-o", str(dists / "InRelease"), str(dists / "Release"))
    _rodar(*assinar, "--detach-sign", "--armor", "-o", str(dists / "Release.gpg"), str(dists / "Release"))
    # A chave pública do projeto (a mesma do pacote), conferida contra a assinatura: uma chave trocada no segredo da
    # CI não chega publicada.
    publica = None if do_gnupg else deb.chave_binaria()
    publica = publica or _rodar("gpg", "--batch", "--export", *([chave] if chave else [])).stdout
    if not publica:
        raise SystemExit("sem a chave pública no GnuPG")
    (saida / "sh-analyzer.gpg").write_bytes(publica)
    _rodar("gpgv", "--keyring", str(saida / "sh-analyzer.gpg"), str(dists / "InRelease"))
    (saida / "sh-analyzer.sources").write_text(deb.fonte_do_apt(), encoding="utf-8")
    (saida / "index.html").write_text(pagina(), encoding="utf-8")
    (saida / ".nojekyll").write_text("")                     # o Pages serve os arquivos como estão
    return dists / "InRelease"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Monta e assina o repositório apt do SH-Analyzer.")
    p.add_argument("pasta_dos_debs", type=Path)
    p.add_argument("saida", type=Path)
    p.add_argument("--chave", help="a impressão digital da chave que assina (padrão: a do GNUPGHOME)")
    p.add_argument("--chave-de-teste", action="store_true",
                   help="publica a chave pública do GnuPG que assina, e não a do projeto (os testes da CI)")
    a = p.parse_args(argv)
    debs = sorted(a.pasta_dos_debs.glob(f"{deb.PACOTE}_*.deb"))
    sys.stdout.write(f"{montar(debs, a.saida.resolve(), a.chave, do_gnupg=a.chave_de_teste)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
