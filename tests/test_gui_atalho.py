"""O atalho do Linux (``sh_analyzer_gui.atalho``): o ``.desktop`` com o nome do ``app_id`` da janela e o ícone, para
o painel do Wayland mostrar o ícone do aplicativo em vez da engrenagem genérica. Sem Qt."""

import shutil
import subprocess
from importlib import resources

import pytest
from sh_analyzer_gui import atalho


def ler(desktop):
    linhas = desktop.read_text(encoding="utf-8").splitlines()
    assert linhas[0] == "[Desktop Entry]"
    return dict(linha.split("=", 1) for linha in linhas[1:] if linha)


def test_instalar_grava_o_desktop_com_o_nome_do_app_id_e_o_icone(tmp_path):
    desktop, icone = atalho.instalar(tmp_path, ["/opt/sh/python", "-m", "sh_analyzer_gui"])
    assert desktop == tmp_path / "applications" / f"{atalho.ID_DO_APLICATIVO}.desktop"
    assert icone == tmp_path / "icons" / "hicolor" / "scalable" / "apps" / f"{atalho.ID_DO_APLICATIVO}.svg"
    original = (resources.files("sh_analyzer_gui") / "recursos" / "app-icon.svg").read_bytes()
    assert icone.read_bytes() == original
    campos = ler(desktop)
    assert campos["Type"] == "Application" and campos["Name"] == "SH-Analyzer"
    assert campos["Icon"] == str(icone)                                  # o caminho completo: vale em qualquer painel
    assert campos["Exec"] == "/opt/sh/python -m sh_analyzer_gui %f"
    assert not list(desktop.parent.glob("*.tmp"))


def test_a_classe_da_janela_e_o_nome_do_aplicativo(tmp_path):
    """O ``StartupWMClass`` é a classe que o Qt dá à janela no X11: o nome do aplicativo da configuração, que precisa
    do Qt (o ``QSettings``). Só este teste depende dele."""
    pytest.importorskip("PySide6")
    from sh_analyzer_gui.configuracao import APLICATIVO
    desktop, _icone = atalho.instalar(tmp_path, ["/opt/sh/python", "-m", "sh_analyzer_gui"])
    assert ler(desktop)["StartupWMClass"] == APLICATIVO


@pytest.mark.skipif(shutil.which("desktop-file-validate") is None, reason="sem o desktop-file-validate")
def test_o_desktop_passa_no_validador(tmp_path):
    desktop, _ = atalho.instalar(tmp_path, ["/caminho com espaço/uv", "run", "--directory", "/x/y", "python"])
    r = subprocess.run(["desktop-file-validate", str(desktop)], capture_output=True, text=True)
    assert r.returncode == 0 and not r.stdout.strip(), r.stdout + r.stderr


def test_os_argumentos_do_exec_seguem_a_especificacao():
    assert atalho._argumento("/usr/bin/uv") == "/usr/bin/uv"
    assert atalho._argumento("/caminho com espaço/uv") == '"/caminho com espaço/uv"'
    assert atalho._argumento('a"b$c') == '"a\\\\"b\\\\$c"'                # escapado nas aspas, e de novo no arquivo
    assert atalho._argumento("100%") == "100%%"                          # % é o começo de um código de campo


def test_o_comando_desta_copia_abre_pelo_uv_com_a_interface(monkeypatch):
    monkeypatch.setattr(atalho.shutil, "which", lambda nome: "/home/u/.local/bin/uv")
    comando = atalho.comando_para_abrir()
    assert comando[:3] == ["/home/u/.local/bin/uv", "run", "--directory"]
    assert comando[-5:] == ["--extra", "gui", "python", "-m", "sh_analyzer_gui"]
    monkeypatch.setattr(atalho.shutil, "which", lambda nome: None)
    assert atalho.comando_para_abrir()[1:] == ["-m", "sh_analyzer_gui"]


def test_remover_apaga_o_que_instalar_gravou(tmp_path):
    desktop, icone = atalho.instalar(tmp_path, ["sh-analyzer-gui"])
    assert atalho.remover(tmp_path) == [desktop, icone]
    assert not desktop.exists() and not icone.exists()
    assert atalho.remover(tmp_path) == []


def test_a_pasta_padrao_segue_o_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert atalho.caminhos()[0] == tmp_path / "applications" / f"{atalho.ID_DO_APLICATIVO}.desktop"
    monkeypatch.delenv("XDG_DATA_HOME")
    assert atalho.pasta_de_dados().parts[-2:] == (".local", "share")
