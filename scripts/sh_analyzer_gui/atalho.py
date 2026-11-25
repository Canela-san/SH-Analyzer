"""O atalho do aplicativo no Linux: o arquivo ``.desktop`` e o ícone em ``~/.local/share``.

**Por que ele existe:** no Wayland, a barra de aplicativos abertos (o painel do COSMIC, o dock do GNOME) não usa o
ícone da janela. Ela acha o ícone pelo ``app_id`` da janela, procurando um ``<app_id>.desktop``. O aplicativo põe
:data:`ID_DO_APLICATIVO` como ``app_id`` (``QGuiApplication.setDesktopFileName``, em ``app.criar_aplicacao``);
sem o ``.desktop`` com esse nome, aparece o ícone genérico (a engrenagem). No X11, a correspondência é pela classe
da janela (``StartupWMClass``, o nome do aplicativo).

``sh-analyzer-gui --instalar-atalho`` grava os dois arquivos; ``--remover-atalho`` os apaga. O atalho abre o
aplicativo da pasta de onde foi instalado (pelo ``uv``, numa cópia do repositório). O pacote ``.deb``
(``empacotamento/deb.py``) traz o seu, em ``/usr/share/applications``, feito por :func:`conteudo` também; com ele
instalado, o ``--instalar-atalho`` não grava a cópia do usuário (seriam dois ícones iguais no menu).

Sem Qt: roda e se testa sem interface.
"""

from __future__ import annotations

import os
import shutil
import sys
from importlib import resources
from pathlib import Path

ID_DO_APLICATIVO = "sh-analyzer"
"""O ``app_id`` da janela no Wayland e o nome do ``.desktop`` (sem a extensão)."""

TIPO_DO_PROJETO = "application/x-sh-analyzer-projeto"
"""O tipo MIME dos projetos ``.shproj`` (registrado pelo pacote ``.deb``: :func:`tipo_mime`)."""

ATALHO_DO_SISTEMA = Path("/usr/share/applications") / f"{ID_DO_APLICATIVO}.desktop"
"""Onde o pacote ``.deb`` põe o atalho."""

_RESERVADOS = set(' \t\n"\'\\><~|&;$*?#()`')


def pasta_de_dados() -> Path:
    """``$XDG_DATA_HOME``, ou ``~/.local/share``."""
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def caminhos(dados: Path | None = None) -> tuple[Path, Path]:
    """Onde ficam o ``.desktop`` e o ícone."""
    dados = pasta_de_dados() if dados is None else Path(dados)
    return (dados / "applications" / f"{ID_DO_APLICATIVO}.desktop",
            dados / "icons" / "hicolor" / "scalable" / "apps" / f"{ID_DO_APLICATIVO}.svg")


def comando_para_abrir() -> list[str]:
    """O comando que abre o aplicativo desta instalação: o executável do pacote (PyInstaller); numa cópia do
    repositório, o ``uv`` com o extra ``gui`` (o ambiente do ``uv`` pode estar sem o PySide6, se outro comando o
    sincronizou sem o extra); senão, este Python."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    raiz = Path(__file__).resolve().parents[2]
    uv = shutil.which("uv")
    if uv and (raiz / "pyproject.toml").is_file():
        return [uv, "run", "--directory", str(raiz), "--extra", "gui", "python", "-m", "sh_analyzer_gui"]
    return [sys.executable, "-m", "sh_analyzer_gui"]


def _argumento(texto: str) -> str:
    """Um argumento da linha ``Exec`` (a especificação do ``.desktop``): entre aspas se tiver um caractere
    reservado, com ``"``, `````, ``$`` e ``\\`` escapados."""
    if not texto or _RESERVADOS & set(texto):
        for c in '\\"`$':
            texto = texto.replace(c, "\\" + c)
        texto = f'"{texto}"'
    # O próprio arquivo é lido com escapes: a barra invertida dobra mais uma vez, e o % vira %%.
    return texto.replace("\\", "\\\\").replace("%", "%%")


def conteudo(comando: list[str], icone: Path) -> str:
    """O texto do ``.desktop``. ``%f``: o projeto que o sistema mandar abrir."""
    exec_ = " ".join(_argumento(a) for a in comando) + " %f"
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.5",
        "Name=SH-Analyzer",
        "GenericName=Analisador de supraharmônicos",
        "Comment=Abre e analisa as capturas da placa SH-Analyzer",
        f"Exec={exec_}",
        f"Icon={icone}",
        "Terminal=false",
        "Categories=Science;Engineering;",
        "Keywords=supraharmônicos;osciloscópio;captura;espectro;",
        "StartupWMClass=SH-Analyzer",
        f"MimeType={TIPO_DO_PROJETO};",
        "",
    ])


def tipo_mime() -> str:
    """O ``shared-mime-info`` dos projetos: ``*.shproj`` é um :data:`TIPO_DO_PROJETO`, que o atalho abre."""
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">',
        f'  <mime-type type="{TIPO_DO_PROJETO}">',
        "    <comment>Projeto do SH-Analyzer</comment>",
        '    <glob pattern="*.shproj"/>',
        "  </mime-type>",
        "</mime-info>",
        "",
    ])


def do_sistema(caminho: Path = ATALHO_DO_SISTEMA) -> Path | None:
    """O atalho do pacote ``.deb``, se ele estiver instalado."""
    return caminho if caminho.is_file() else None


def instalar(dados: Path | None = None, comando: list[str] | None = None) -> tuple[Path, Path]:
    """Grava o ícone e o ``.desktop`` (substituindo os de antes) e devolve os dois caminhos. O ``Icon=`` leva o
    caminho completo do ícone copiado: vale em qualquer painel, sem depender do cache de ícones do tema."""
    desktop, icone = caminhos(dados)
    icone.parent.mkdir(parents=True, exist_ok=True)
    origem = resources.files("sh_analyzer_gui") / "recursos" / "app-icon.svg"
    icone.write_bytes(origem.read_bytes())
    desktop.parent.mkdir(parents=True, exist_ok=True)
    temporario = desktop.with_suffix(".desktop.tmp")
    temporario.write_text(conteudo(comando or comando_para_abrir(), icone), encoding="utf-8")
    temporario.replace(desktop)
    return desktop, icone


def remover(dados: Path | None = None) -> list[Path]:
    """Apaga o ``.desktop`` e o ícone que :func:`instalar` gravou; devolve os que existiam."""
    apagados = []
    for caminho in caminhos(dados):
        if caminho.exists():
            caminho.unlink()
            apagados.append(caminho)
    return apagados
