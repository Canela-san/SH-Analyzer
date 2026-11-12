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
    assert janela.windowTitle() == NOME
    assert (janela.minimumWidth(), janela.minimumHeight()) == TAMANHO_MINIMO
    assert versao() in janela.findChild(QLabel, "versao").text()
    assert not janela.findChild(QLabel, "marca").pixmap().isNull()
