"""O esqueleto da interface gráfica (``sh_analyzer_gui``): a aplicação com o nome, a versão e o ícone da marca, e a
janela principal, sem tela (``QT_QPA_PLATFORM=offscreen``, em ``conftest.py``).

Precisa do extra ``gui-dev`` (o PySide6 e o pytest-qt): ``scripts/ci.sh interface``. Sem ele, o módulo é pulado.
"""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QLabel  # noqa: E402
from sh_analyzer_gui.app import NOME, criar_aplicacao, icone_do_aplicativo, versao  # noqa: E402
from sh_analyzer_gui.janela import TAMANHO_MINIMO, JanelaPrincipal  # noqa: E402


def test_a_aplicacao_tem_o_nome_a_versao_e_o_icone(qapp):
    app = criar_aplicacao([])
    assert app is qapp, "criar_aplicacao tem de reaproveitar a QApplication que já existe"
    assert app.applicationName() == NOME
    assert app.applicationVersion() == versao() != ""
    assert not app.windowIcon().isNull()


def test_o_icone_e_desenhado_em_cada_tamanho(qapp):
    """O SVG depende do plugin de imagem do Qt: sem ele, o ícone sairia transparente, sem erro nenhum."""
    icone = icone_do_aplicativo()
    for lado in (16, 32, 48, 256):
        imagem = icone.pixmap(lado, lado).toImage()
        assert (imagem.width(), imagem.height()) == (lado, lado)
        assert imagem.pixelColor(lado // 2, lado // 2).alpha() > 0, f"o ícone de {lado} px saiu transparente"


def test_a_janela_abre_com_o_nome_a_versao_e_a_marca(qtbot):
    criar_aplicacao([])
    janela = JanelaPrincipal()
    qtbot.addWidget(janela)
    janela.show()
    qtbot.waitExposed(janela)
    assert janela.windowTitle().endswith(f"— {NOME}") and not janela.isWindowModified()
    assert (janela.minimumWidth(), janela.minimumHeight()) == TAMANHO_MINIMO
    assert versao() in janela.findChild(QLabel, "versao").text()
    assert not janela.findChild(QLabel, "marca").pixmap().isNull()


def test_main_com_sair_ao_abrir_abre_e_sai_com_zero():
    """O teste de partida do instalador (F0.11), num processo à parte: a janela abre, o primeiro quadro é pintado e o
    aplicativo sai com 0. Não roda no processo do pytest: depois de um ``quit()``, o Qt devolve na hora qualquer laço
    de eventos novo, e os testes seguintes deixariam de processar os temporizadores."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    scripts = Path(__file__).resolve().parents[1] / "scripts"
    ambiente = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(scripts)}
    r = subprocess.run([sys.executable, "-m", "sh_analyzer_gui", "--sair-ao-abrir", "--tema", "claro"],
                       capture_output=True, text=True, env=ambiente, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]


def test_opcoes_da_linha_de_comando(capsys):
    from sh_analyzer_gui import app as modulo

    assert modulo.main(["sh-analyzer-gui", "--versao"]) == 0
    assert capsys.readouterr().out.strip() == f"{NOME} {versao()}"
    with pytest.raises(SystemExit) as e:
        modulo.main(["sh-analyzer-gui", "--help"])
    assert e.value.code == 0 and "--sair-ao-abrir" in capsys.readouterr().out
    opcoes, resto = modulo.ler_opcoes(["prog", "--tema", "claro", "-platform", "offscreen"])
    assert opcoes.tema == "claro" and resto == ["prog", "-platform", "offscreen"]
