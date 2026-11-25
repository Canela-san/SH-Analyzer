"""O pacote ``.deb`` do Linux: a pasta do PyInstaller (``empacotamento/construir.sh``) instalada pelo apt.

    python3 empacotamento/deb.py PASTA_DO_APP SAIDA        grava SAIDA/sh-analyzer_<versão>_amd64.deb

O que ele instala:

- ``/opt/sh-analyzer/``: o aplicativo (a pasta inteira, como saiu do PyInstaller);
- ``/usr/bin/sh-analyzer``: o comando (um script que chama o executável da pasta);
- ``/usr/share/applications/sh-analyzer.desktop``: o atalho do menu, o mesmo do ``--instalar-atalho``
  (``sh_analyzer_gui.atalho``), com o nome do ``app_id`` da janela (o ícone na barra do Wayland);
- o ícone no tema ``hicolor``, o tipo dos projetos ``.shproj`` (``shared-mime-info``) e a página do AppStream;
- a chave e a fonte do repositório apt (``/usr/share/keyrings``, ``/etc/apt/sources.list.d``): quem instalar só o
  ``.deb`` baixado também recebe as versões novas pelo Atualizador do sistema. Os arquivos são os mesmos que o README
  manda baixar do repositório (``empacotamento/repositorio_apt.sh`` os publica), então instalar depois de adicionar o
  repositório não pergunta nada.

Os caches do menu, dos ícones e dos tipos são refeitos pelos gatilhos do dpkg (``desktop-file-utils``,
``shared-mime-info``, ``hicolor-icon-theme``): o pacote não tem scripts de instalação.

As dependências são as bibliotecas que o PyInstaller deixa de fora de propósito (as do OpenGL, do xcb e do Wayland,
que precisam ser as do sistema) e o fontconfig (a configuração das fontes, que a biblioteca do pacote lê do sistema):
conferidas instalando o pacote em contêineres limpos (a CI dos instaladores).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

from sh_analyzer_gui import atalho  # noqa: E402 (sem Qt)

PACOTE = "sh-analyzer"
PASTA_INSTALADA = Path("/opt/sh-analyzer")
EXECUTAVEL = "sh-analyzer-gui"
URL_DO_PROJETO = "https://github.com/Canela-san/SH-Analyzer"
URL_DO_REPOSITORIO = "https://canela-san.github.io/SH-Analyzer"
"""O repositório apt (o GitHub Pages do projeto, publicado pelo ``.github/workflows/apt.yml``)."""
CHAVE_PUBLICA = RAIZ / "empacotamento" / "apt" / "sh-analyzer.asc"
ARQUIVO_DA_CHAVE = Path("/usr/share/keyrings/sh-analyzer.gpg")
ARQUIVO_DA_FONTE = Path("/etc/apt/sources.list.d/sh-analyzer.sources")

DEPENDENCIAS = (
    "libgl1", "libegl1", "libdrm2", "fontconfig",
    # o xcb (o X11) do Qt: as que o plugin dele pede e o PyInstaller não leva
    "libxcb1", "libxcb-cursor0", "libxcb-icccm4", "libxcb-image0", "libxcb-keysyms1", "libxcb-render-util0",
    "libxcb-shape0", "libxcb-xkb1", "libxkbcommon-x11-0",
    # o Wayland
    "libwayland-client0", "libwayland-cursor0", "libwayland-egl1",
)
RECOMENDADOS = ("zpaq", "fonts-dejavu-core")
"""O zpaq: os pacotes ``.zpaq.tar`` (sem ele, o aplicativo avisa); as fontes: a interface num sistema sem nenhuma."""

DESCRICAO = """\
Analisador de supraharmônicos (2 a 150 kHz) da rede elétrica
 O SH-Analyzer abre, analisa e exporta as capturas da placa SH-Analyzer
 (BeagleBone com o ADC de 16 bits): o espectro, o espectrograma, os eventos,
 os índices de qualidade de energia da IEC 61000-4-30, a função de
 transferência com o intervalo de confiança, o modo Instrumento, as figuras
 prontas para artigo com o pacote que as refaz, e a manutenção da placa."""


def versao_do_pacote(raiz: Path = RAIZ) -> str:
    """A versão do ``pyproject.toml``; fora de uma tag dela, com o que veio depois (``0.9.0+git3.gabc1234``), que o
    apt ordena depois da versão e antes da seguinte."""
    texto = (raiz / "pyproject.toml").read_text(encoding="utf-8")
    versao = re.search(r'^version\s*=\s*"([^"]+)"', texto, re.MULTILINE).group(1)
    descricao = subprocess.run(["git", "-C", str(raiz), "describe", "--tags", "--long", "--match", "v*"],
                               capture_output=True, text=True).stdout.strip()
    achado = re.fullmatch(r"v(.+)-(\d+)-g([0-9a-f]+)", descricao)
    if achado is None or (achado.group(2) == "0" and mesma_versao(achado.group(1), versao)):
        return versao
    return f"{versao}+git{achado.group(2)}.g{achado.group(3)}"


def mesma_versao(a: str, b: str) -> bool:
    """``0.9`` e ``0.9.0`` são a mesma versão (a tag e o ``pyproject.toml``)."""
    def partes(v: str) -> list[int]:
        numeros = [int(p) for p in v.split(".")]
        while numeros and numeros[-1] == 0:
            numeros.pop()
        return numeros
    try:
        return partes(a) == partes(b)
    except ValueError:
        return a == b


def controle(versao: str, tamanho_kib: int) -> str:
    return "\n".join([
        f"Package: {PACOTE}",
        f"Version: {versao}",
        "Architecture: amd64",
        "Maintainer: Gabriel Canela <https://github.com/Canela-san/SH-Analyzer/issues>",
        f"Installed-Size: {tamanho_kib}",
        f"Depends: {', '.join(DEPENDENCIAS)}",
        f"Recommends: {', '.join(RECOMENDADOS)}",
        "Section: science",
        "Priority: optional",
        f"Homepage: {URL_DO_PROJETO}",
        f"Description: {DESCRICAO}",
        "",
    ])


def comando() -> str:
    """O ``/usr/bin/sh-analyzer``: um script, e não um link, para o PyInstaller achar a pasta pelo caminho de
    verdade do executável."""
    return f'#!/bin/sh\nexec {PASTA_INSTALADA / EXECUTAVEL} "$@"\n'


def fonte_do_apt() -> str:
    """A fonte do repositório no formato deb822 (a do apt 2.x)."""
    return "\n".join([
        "Types: deb",
        f"URIs: {URL_DO_REPOSITORIO}",
        "Suites: stable",
        "Components: main",
        "Architectures: amd64",
        f"Signed-By: {ARQUIVO_DA_CHAVE}",
        "",
    ])


def metainfo(versao: str, data: dt.date) -> str:
    """A página do AppStream: o que a loja de aplicativos mostra do pacote instalado."""
    resumo = DESCRICAO.splitlines()[0]
    corpo = " ".join(linha.strip() for linha in DESCRICAO.splitlines()[1:])
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<component type="desktop-application">',
        f"  <id>{atalho.ID_DO_APLICATIVO}</id>",
        "  <metadata_license>MIT</metadata_license>",
        "  <project_license>MIT</project_license>",
        "  <name>SH-Analyzer</name>",
        f"  <summary>{resumo}</summary>",
        f"  <description><p>{corpo}</p></description>",
        f'  <launchable type="desktop-id">{atalho.ID_DO_APLICATIVO}.desktop</launchable>',
        f'  <url type="homepage">{URL_DO_PROJETO}</url>',
        f"  <provides><binary>{PACOTE}</binary></provides>",
        f'  <releases><release version="{versao.split("+")[0]}" date="{data.isoformat()}"/></releases>',
        "</component>",
        "",
    ])


def direitos() -> str:
    """O ``copyright`` no formato da Debian: o SH-Analyzer é MIT; o que vai junto, com as licenças de cada um."""
    return "\n".join([
        "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/",
        "Upstream-Name: SH-Analyzer",
        f"Source: {URL_DO_PROJETO}",
        "",
        "Files: *",
        "Copyright: Gabriel Canela",
        "License: MIT",
        f" O texto está em {PASTA_INSTALADA}/_internal/LICENSE. As bibliotecas que vão junto (Python, Qt/PySide6,",
        f" NumPy, SciPy, Matplotlib e outras) seguem as próprias licenças: {PASTA_INSTALADA}/_internal/AVISOS.txt.",
        "",
    ])


def chave_binaria(asc: Path = CHAVE_PUBLICA) -> bytes | None:
    """A chave pública do repositório no formato do ``Signed-By`` (binário), ou ``None`` sem a chave."""
    if not asc.is_file():
        return None
    return subprocess.run(["gpg", "--dearmor"], input=asc.read_bytes(), capture_output=True, check=True).stdout


def _gravar(caminho: Path, conteudo: str | bytes, modo: int = 0o644) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(conteudo, str):
        caminho.write_text(conteudo, encoding="utf-8")
    else:
        caminho.write_bytes(conteudo)
    caminho.chmod(modo)


def montar(pasta_do_app: Path, raiz: Path, versao: str, chave: bytes | None) -> None:
    """A árvore do pacote em ``raiz`` (o que o ``dpkg-deb --build`` empacota)."""
    destino = raiz / PASTA_INSTALADA.relative_to("/")
    shutil.copytree(pasta_do_app, destino, symlinks=True)
    _gravar(raiz / "usr/bin" / PACOTE, comando(), 0o755)
    _gravar(raiz / "usr/share/applications" / f"{atalho.ID_DO_APLICATIVO}.desktop",
            atalho.conteudo([f"/usr/bin/{PACOTE}"], atalho.ID_DO_APLICATIVO))
    icones = RAIZ / "scripts" / "sh_analyzer_gui" / "recursos"
    _gravar(raiz / "usr/share/icons/hicolor/scalable/apps" / f"{atalho.ID_DO_APLICATIVO}.svg",
            (icones / "app-icon.svg").read_bytes())
    _gravar(raiz / "usr/share/mime/packages" / f"{PACOTE}.xml", atalho.tipo_mime())
    _gravar(raiz / "usr/share/metainfo" / f"{atalho.ID_DO_APLICATIVO}.metainfo.xml",
            metainfo(versao, dt.date.today()))
    _gravar(raiz / "usr/share/doc" / PACOTE / "copyright", direitos())
    conffiles = []
    if chave is not None:
        _gravar(raiz / ARQUIVO_DA_CHAVE.relative_to("/"), chave)
        _gravar(raiz / ARQUIVO_DA_FONTE.relative_to("/"), fonte_do_apt())
        conffiles.append(str(ARQUIVO_DA_FONTE))
    tamanho = sum(c.lstat().st_size for c in raiz.rglob("*") if not c.is_dir()) // 1024
    _gravar(raiz / "DEBIAN" / "control", controle(versao, tamanho))
    if conffiles:
        _gravar(raiz / "DEBIAN" / "conffiles", "\n".join(conffiles) + "\n")
    for caminho in [raiz, *raiz.rglob("*")]:                   # o dono é o root; ninguém mais escreve
        if not caminho.is_symlink():
            caminho.chmod(caminho.stat().st_mode & ~0o022 | (0o755 if caminho.is_dir() else 0o444))


def construir(pasta_do_app: Path, saida: Path, versao: str | None = None, chave: bytes | None = None) -> Path:
    """Grava ``saida/sh-analyzer_<versão>_amd64.deb`` e devolve o caminho."""
    if not (pasta_do_app / EXECUTAVEL).is_file():
        raise SystemExit(f"{pasta_do_app} não é a pasta do PyInstaller (sem o {EXECUTAVEL})")
    versao = versao or versao_do_pacote()
    chave = chave if chave is not None else chave_binaria()
    saida.mkdir(parents=True, exist_ok=True)
    deb = saida / f"{PACOTE}_{versao}_amd64.deb"
    with tempfile.TemporaryDirectory(prefix="deb-", dir=saida) as temporaria:
        raiz = Path(temporaria) / "raiz"
        raiz.mkdir()
        montar(pasta_do_app, raiz, versao, chave)
        # O xz no nível 6: o máximo leva minutos a mais por ~2 % a menos.
        subprocess.run(["dpkg-deb", "--root-owner-group", "-Zxz", "-z6", "--build", str(raiz),
                        str(deb)], check=True, env={**os.environ, "SOURCE_DATE_EPOCH": _data_do_commit()})
    return deb


def _data_do_commit() -> str:
    data = subprocess.run(["git", "-C", str(RAIZ), "log", "-1", "--format=%ct"], capture_output=True, text=True)
    return data.stdout.strip() or "0"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Monta o .deb do SH-Analyzer a partir da pasta do PyInstaller.")
    p.add_argument("pasta_do_app", type=Path, help="a pasta construída (PASTA/dist/sh-analyzer-gui)")
    p.add_argument("saida", type=Path, help="onde o .deb fica")
    p.add_argument("--versao", help="a versão do pacote (padrão: a do pyproject.toml, com o git describe)")
    a = p.parse_args(argv)
    sys.stdout.write(f"{construir(a.pasta_do_app.resolve(), a.saida.resolve(), a.versao)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
