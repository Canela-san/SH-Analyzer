"""O que a receita do PyInstaller (``sh-analyzer-gui.spec``) junta ao aplicativo, fora do código (F7.12 em
docs/gui-progress.md, 4h). Separado da receita para os testes conferirem sem o PyInstaller (tests/test_empacotamento.py).

- **O firmware** desta versão (``firmware/``, para atualizar a placa sem o repositório, e o agente que vai a cada
  chamada), com a ``VERSAO`` do ``git describe``, os commits com o mesmo firmware (``firmware.commits``: a placa
  enviada de outro commit com o mesmo código não é "outra versão") e os arquivos executáveis pelo Git
  (``firmware.executaveis``: no Windows, os arquivos não têm o bit de execução);
- **os módulos** que o agente e os programas da placa simulada importam (o executável faz de Python para eles:
  ``sh_placa.como_python``), que o PyInstaller não acha sozinho;
- **o guia** (``docs/gui-guide.md``, em ``ajuda/``), **as sondas** (``scripts/sondas/*.json``, em ``sondas/``, onde o
  motor as procura) e **os avisos** das licenças;
- **o ícone** do Windows (um ``.ico`` com os PNGs da marca em cada tamanho).
"""

from __future__ import annotations

import ast
import struct
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MAXIMO_DE_COMMITS = 400
"""Quantos commits, do último que mudou o firmware para cá, a lista confere (os mais antigos ficam de fora: a placa
deles é tratada como de outra versão, e a interface oferece a atualização, o que é seguro)."""
LADOS_DO_ICONE = (("app-icon-small.svg", (16, 24, 32)), ("app-icon.svg", (48, 64, 128, 256)))


def _git(*argumentos: str, raiz: Path = RAIZ) -> str:
    return subprocess.run(["git", "-C", str(raiz), *argumentos], capture_output=True, text=True, check=True,
                          timeout=60).stdout


def firmware(raiz: Path = RAIZ):
    """O ``firmware/`` desta versão, como o aplicativo o enviaria rodando do repositório."""
    from sh_placa.atualizacao import firmware_do_aplicativo

    fw = firmware_do_aplicativo(raiz)
    if fw is None:
        raise SystemExit("sem o firmware: a receita precisa do repositório com o git")
    return fw


def executaveis(raiz: Path = RAIZ) -> list[str]:
    """Os arquivos do ``firmware/`` com o modo 100755 no Git, relativos a ele."""
    saida = _git("ls-files", "-s", "--", "firmware", raiz=raiz)
    return sorted(linha.split("\t", 1)[1].removeprefix("firmware/") for linha in saida.splitlines()
                  if linha.startswith("100755 "))


def commits_com_o_mesmo_firmware(raiz: Path = RAIZ) -> list[str]:
    """Os commits (o hash inteiro) com o firmware igual ao de agora, do último que o mudou para cá; vazio se o
    ``firmware/`` tem mudanças não commitadas."""
    from sh_placa.versao import CAMINHOS_DO_FIRMWARE

    if _git("status", "--porcelain", "--", *CAMINHOS_DO_FIRMWARE, raiz=raiz).strip():
        return []
    ultimo = _git("log", "-1", "--format=%H", "--", *CAMINHOS_DO_FIRMWARE, raiz=raiz).strip()
    if not ultimo:
        return []
    candidatos = [ultimo, *_git("rev-list", f"--max-count={MAXIMO_DE_COMMITS}", f"{ultimo}..HEAD",
                                raiz=raiz).split()]
    iguais = []
    for commit in candidatos:
        diferenca = subprocess.run(["git", "-C", str(raiz), "diff", "--quiet", commit, "HEAD", "--",
                                    *CAMINHOS_DO_FIRMWARE], capture_output=True, timeout=60)
        if diferenca.returncode == 0:
            iguais.append(commit)
    return iguais


def preparar_firmware(destino: Path, raiz: Path = RAIZ) -> list[tuple[str, str]]:
    """Grava a ``VERSAO``, o ``firmware.commits`` e o ``firmware.executaveis`` em ``destino`` e devolve os
    ``datas`` do PyInstaller: os arquivos do firmware (do repositório) e esses três."""
    from sh_placa.versao import ARQUIVO_DOS_COMMITS, ARQUIVO_DOS_EXECUTAVEIS

    fw = firmware(raiz)
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "VERSAO").write_text(fw.versao + "\n", encoding="utf-8")
    (destino / ARQUIVO_DOS_COMMITS).write_text("".join(c + "\n" for c in commits_com_o_mesmo_firmware(raiz)),
                                               encoding="utf-8")
    (destino / ARQUIVO_DOS_EXECUTAVEIS).write_text("".join(c + "\n" for c in executaveis(raiz)), encoding="utf-8")
    datas = [(str(raiz / "firmware" / a.caminho), str(Path("firmware", a.caminho).parent)) for a in fw.arquivos]
    return datas + [(str(destino / "VERSAO"), "firmware"), (str(destino / ARQUIVO_DOS_COMMITS), "."),
                    (str(destino / ARQUIVO_DOS_EXECUTAVEIS), ".")]



def _importados(texto: str) -> set[str]:
    nomes = set()
    for no in ast.walk(ast.parse(texto)):
        if isinstance(no, ast.Import):
            nomes |= {a.name for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
            nomes.add(no.module)
    return nomes


def modulos_dos_programas(raiz: Path = RAIZ) -> list[str]:
    """Os módulos que o agente e os programas da placa simulada importam (todos da biblioteca padrão)."""
    from sh_placa import correcoes, servidor_do_simulador, simulador

    textos = [(raiz / "firmware" / "agente" / "shan_agente.py").read_text(encoding="utf-8"),
              correcoes.CODIGO_DO_RELOGIO,
              servidor_do_simulador.PGREP.format(python="python3", pgrep="pgrep"),
              *(t for t in simulador.programas_da_placa().values() if t.startswith(f"#!{sys.executable}\n"))]
    nomes = set()
    for texto in textos:
        nomes |= _importados(texto)
    return sorted(nomes - {"__future__"})


def gerar_ico(destino: Path, pasta_das_svgs: Path | None = None) -> Path:
    """O ícone do Windows: um ``.ico`` com um PNG da marca em cada lado (o formato aceita PNGs desde o Vista)."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    if QGuiApplication.instance() is None:
        _app = QGuiApplication(["receita", "-platform", "offscreen"])     # noqa: F841 (o QPainter pede uma)
    pasta = pasta_das_svgs or RAIZ / "scripts" / "sh_analyzer_gui" / "recursos"
    imagens = []
    for nome, lados in LADOS_DO_ICONE:
        desenho = QSvgRenderer(str(pasta / nome))
        if not desenho.isValid():
            raise SystemExit(f"o SVG da marca não se lê: {pasta / nome}")
        for lado in lados:
            imagem = QImage(lado, lado, QImage.Format.Format_ARGB32)
            imagem.fill(Qt.GlobalColor.transparent)
            pintor = QPainter(imagem)
            desenho.render(pintor)
            pintor.end()
            dados = QByteArray()
            buffer = QBuffer(dados)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            imagem.save(buffer, "PNG")
            buffer.close()
            imagens.append((lado, bytes(dados.data())))
    cabecalho = struct.pack("<HHH", 0, 1, len(imagens))
    deslocamento = len(cabecalho) + 16 * len(imagens)
    entradas, corpo = b"", b""
    for lado, png in imagens:
        entradas += struct.pack("<BBBBHHII", lado % 256, lado % 256, 0, 0, 1, 32, len(png), deslocamento + len(corpo))
        corpo += png
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(cabecalho + entradas + corpo)
    return destino


EXTRAS_DO_APLICATIVO = ("gui", "placa")


def distribuicoes(raiz: Path = RAIZ) -> list[str]:
    """As distribuições do Python que vão no aplicativo (as dependências do projeto com os extras
    :data:`EXTRAS_DO_APLICATIVO`, e as delas), as instaladas: os metadados de cada uma, com o texto da licença, vão
    junto (o ``copy_metadata`` do PyInstaller)."""
    from importlib import metadata

    try:
        import tomllib
    except ImportError:                             # a Python 3.10 dos testes
        import tomli as tomllib
    from packaging.requirements import Requirement

    projeto = tomllib.loads((raiz / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    pedidos = list(projeto["dependencies"])
    for extra in EXTRAS_DO_APLICATIVO:
        pedidos += projeto["optional-dependencies"][extra]
    vistas: dict[str, str] = {}
    fila = [Requirement(p) for p in pedidos]
    while fila:
        pedido = fila.pop()
        if pedido.marker is not None and not pedido.marker.evaluate({"extra": ""}):
            continue
        chave = pedido.name.lower().replace("_", "-")
        if chave in vistas:
            continue
        try:
            dist = metadata.distribution(pedido.name)
        except metadata.PackageNotFoundError:
            continue                                # uma dependência de outra plataforma
        vistas[chave] = dist.metadata["Name"]
        fila += [Requirement(r) for r in dist.requires or ()]
    return sorted(vistas.values(), key=str.lower)
