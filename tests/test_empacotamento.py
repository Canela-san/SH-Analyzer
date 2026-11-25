"""O que a receita do PyInstaller junta ao aplicativo (``empacotamento/receita.py``; F7.12), sem o PyInstaller: o
firmware com a versão, os commits com o mesmo firmware e os executáveis; os módulos do agente e da placa simulada; as
distribuições com as licenças; o ícone do Windows; e os dados que a receita e o instalador do Windows nomeiam. O
pacote construído é conferido por dentro pelo ``empacotamento/construir.sh`` (e na CI dos instaladores)."""

from __future__ import annotations

import importlib.util
import struct
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "empacotamento"))

import receita  # noqa: E402
from sh_placa.versao import ARQUIVO_DOS_COMMITS, ARQUIVO_DOS_EXECUTAVEIS, CAMINHOS_DO_FIRMWARE  # noqa: E402


def _git(*argumentos: str) -> str:
    return subprocess.run(["git", "-C", str(RAIZ), *argumentos], capture_output=True, text=True, check=True).stdout


def test_o_firmware_vai_com_a_versao_os_commits_e_os_executaveis(tmp_path):
    datas = receita.preparar_firmware(tmp_path)
    destinos = {Path(origem).relative_to(RAIZ).as_posix() if Path(origem).is_relative_to(RAIZ) else Path(origem).name:
                destino for origem, destino in datas}
    for nome in ("ler_adc.c", "pru_main.c", "Makefile", "coletar.sh", "coleta/comum.sh"):
        assert destinos[f"firmware/{nome}"] == str(Path("firmware", nome).parent)
    assert destinos["firmware/agente/shan_agente.py"] == str(Path("firmware", "agente"))
    assert destinos["VERSAO"] == "firmware" and destinos[ARQUIVO_DOS_COMMITS] == "."
    versao = (tmp_path / "VERSAO").read_text().strip()
    assert versao.split("-dirty")[0] == _git("describe", "--always").strip()
    executaveis = (tmp_path / ARQUIVO_DOS_EXECUTAVEIS).read_text().split()
    assert "coletar.sh" in executaveis and "agente/shan_agente.py" in executaveis
    assert executaveis == receita.executaveis()


def test_os_commits_com_o_mesmo_firmware():
    """O HEAD está na lista (com o firmware sem mudanças), e cada commit dela tem o mesmo firmware."""
    if _git("status", "--porcelain", "--", *CAMINHOS_DO_FIRMWARE).strip():
        assert receita.commits_com_o_mesmo_firmware() == []
        return
    commits = receita.commits_com_o_mesmo_firmware()
    assert _git("rev-parse", "HEAD").strip() in commits
    for commit in commits[:5]:
        assert subprocess.run(["git", "-C", str(RAIZ), "diff", "--quiet", commit, "HEAD", "--",
                               *CAMINHOS_DO_FIRMWARE]).returncode == 0


def test_os_modulos_do_agente_e_da_placa_simulada():
    """Os imports do agente (também os de dentro das funções) e dos programas Python da placa simulada: todos da
    biblioteca padrão, e o PyInstaller não os acharia sozinho."""
    modulos = receita.modulos_dos_programas()
    for nome in ("json", "zlib", "struct", "csv", "pwd", "hashlib", "subprocess", "socket"):
        assert nome in modulos
    for nome in modulos:
        assert importlib.util.find_spec(nome) is not None, nome


def test_as_distribuicoes_com_as_licencas():
    nomes = {n.lower() for n in receita.distribuicoes()}
    assert {"numpy", "scipy", "matplotlib", "h5py"} <= nomes
    assert {"asyncssh", "zeroconf", "pyte", "keyring"} <= nomes            # o extra placa
    assert not {"pytest", "ruff", "pytest-qt"} & nomes                     # o dev não vai
    if importlib.util.find_spec("PySide6") is not None:
        assert {"pyside6", "shiboken6", "pyqtgraph", "platformdirs"} <= nomes


def test_o_icone_do_windows(tmp_path, request):
    """Com a aplicação dos testes (a ``qapp``): o ``gerar_ico`` só cria a dele sem nenhuma, e um ``QGuiApplication``
    no processo dos testes derrubava os da interface que viessem depois."""
    pytest.importorskip("PySide6.QtSvg")
    pytest.importorskip("pytestqt")
    request.getfixturevalue("qapp")
    icone = receita.gerar_ico(tmp_path / "x.ico").read_bytes()
    reservado, tipo, quantos = struct.unpack("<HHH", icone[:6])
    lados = [lado for _, lados in receita.LADOS_DO_ICONE for lado in lados]
    assert (reservado, tipo, quantos) == (0, 1, len(lados))
    for i, lado in enumerate(lados):
        largura, altura, _, _, planos, bits, tamanho, inicio = struct.unpack("<BBBBHHII", icone[6 + 16 * i:22 + 16 * i])
        assert (largura, altura) == (lado % 256, lado % 256) and (planos, bits) == (1, 32)
        assert icone[inicio:inicio + 8] == b"\x89PNG\r\n\x1a\n" and inicio + tamanho <= len(icone)


def test_os_dados_que_a_receita_e_o_instalador_nomeiam():
    receita_do_pyinstaller = (RAIZ / "empacotamento" / "sh-analyzer-gui.spec").read_text()
    assert (RAIZ / "docs" / "gui-guide.md").is_file() and '"gui-guide.md"), "ajuda"' in receita_do_pyinstaller
    assert (RAIZ / "scripts" / "sondas" / "cadeia_tensao.json").is_file()
    assert (RAIZ / "empacotamento" / "AVISOS.txt").is_file() and (RAIZ / "LICENSE").is_file()
    assert {p.name for p in (RAIZ / "empacotamento" / "licencas").glob("*.txt")} == {"LGPL-3.0.txt", "GPL-3.0.txt"}
    instalador = (RAIZ / "empacotamento" / "sh-analyzer-gui.iss").read_text()
    assert r"{app}\_internal\AVISOS.txt" in instalador                      # o atalho dos avisos e das licenças
    assert "SHAnalyzer.Projeto" in instalador and ".shproj" in instalador
    # Para leigos: o atalho na área de trabalho vem marcado, e a atualização calada reabre o aplicativo.
    assert 'Name: "atalho"' in instalador and "unchecked" not in instalador
    assert "{param:REABRIR|0}" in instalador and "CloseApplications=yes" in instalador
