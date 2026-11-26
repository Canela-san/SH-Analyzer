"""Os nomes acessíveis (``componentes/acessibilidade.py``): os botões só com ícone da janela inteira ganham o nome da
dica, para um leitor de tela; um nome dado à mão fica."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
from PySide6.QtWidgets import QAbstractButton, QToolButton  # noqa: E402
from sh_analyzer_gui.componentes.acessibilidade import nome_da_dica  # noqa: E402
from test_gui_vistas_de_analise import janela, tracos  # noqa: E402,F401


def test_o_nome_que_a_dica_da():
    assert nome_da_dica("Ajustar tudo (F)") == "Ajustar tudo (F)"            # só os atalhos com tecla de controle
    assert nome_da_dica("Copiar a tabela (Ctrl+C)") == "Copiar a tabela"
    assert nome_da_dica("<b>Cursores</b>\nLiga os dois cursores") == "Cursores"
    assert nome_da_dica("") == ""


def test_os_botoes_so_com_icone_tem_nome(janela, tracos, qtbot):  # noqa: F811
    qtbot.wait(50)
    mudos = [b for b in janela.findChildren(QAbstractButton)
             if b.isVisible() and not b.text().strip() and b.toolTip().strip() and not b.accessibleName()]
    assert not mudos, [b.toolTip() for b in mudos][:5]
    botao = QToolButton(janela)
    botao.setAccessibleName("Meu nome")
    botao.setToolTip("Outra coisa")
    botao.show()
    qtbot.wait(10)
    assert botao.accessibleName() == "Meu nome"
    botao.deleteLater()
