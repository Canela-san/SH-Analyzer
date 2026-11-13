"""O tema na aplicação (``sh_analyzer_gui.tema``): a paleta e o QSS dos tokens, a troca sem reiniciar, os ícones
recoloridos e as fontes. Sem tela (pytest-qt)."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtGui import QFont, QPalette  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.tema import icones  # noqa: E402
from sh_analyzer_gui.tema.aplicar import aparencia, gerar_qss  # noqa: E402
from sh_analyzer_gui.tema.fontes import com_algarismos_tabulares, fonte_da_interface, fonte_mono, registrar_fontes  # noqa: E402
from sh_analyzer_gui.tema.tokens import TEMAS  # noqa: E402


@pytest.fixture
def ap(qapp):
    a = aparencia(qapp)
    yield a
    a.aplicar("escuro")                      # a QApplication é a mesma em toda a sessão de testes


@pytest.mark.parametrize("nome", ["escuro", "claro"])
def test_aplicar_tema_muda_a_paleta_e_o_qss(qapp, ap, qtbot, nome):
    with qtbot.waitSignal(ap.mudou) as sinal:
        tema = ap.aplicar(nome)
    assert sinal.args == [tema] and tema is TEMAS[nome] and ap.modo == nome
    assert qapp.palette().color(QPalette.ColorRole.Window).name() == tema.fundo
    assert qapp.palette().color(QPalette.ColorRole.Highlight).name() == tema.acento
    assert tema.acento in qapp.styleSheet()


def test_sistema_alternar_e_modo_invalido(ap):
    assert ap.aplicar("sistema") in (TEMAS["escuro"], TEMAS["claro"]) and ap.modo == "sistema"
    ap.aplicar("escuro")
    assert ap.alternar() is TEMAS["claro"] and ap.alternar() is TEMAS["escuro"]
    with pytest.raises(ValueError):
        ap.aplicar("roxo")


def test_qss_dos_dois_temas_usa_so_os_tokens():
    for tema in TEMAS.values():
        qss = gerar_qss(tema)
        assert qss.count("{") == qss.count("}") and tema.superficie in qss and tema.borda in qss


@pytest.mark.parametrize("nome", sorted(icones.CAMINHOS))
def test_cada_icone_e_desenhado_na_cor_pedida(qapp, nome):
    icone = icones.icone(nome, "#ff0000", 24)
    imagem = icone.pixmap(24, 24).toImage()
    pintados = [imagem.pixelColor(x, y) for x in range(24) for y in range(24) if imagem.pixelColor(x, y).alpha() > 200]
    assert pintados, f"o ícone {nome} saiu transparente"
    assert all(c.red() > 200 and c.green() < 60 for c in pintados)
    assert icones.icone(nome, "#ff0000", 24) is icone          # do cache


def test_icone_desconhecido():
    with pytest.raises(KeyError):
        icones.svg("nao_existe", "#000000")


def test_fontes(qapp):
    assert isinstance(registrar_fontes(), list)
    assert fonte_da_interface(13).pixelSize() == 13 and fonte_mono(12).pixelSize() == 12
    assert isinstance(com_algarismos_tabulares(fonte_da_interface()), QFont)


def test_botao_da_janela_troca_o_tema(qapp, ap, qtbot):
    criar_aplicacao([], tema="escuro")
    janela = JanelaPrincipal()
    qtbot.addWidget(janela)
    janela.show()
    assert janela.botao_tema.toolTip() == "Tema claro"
    janela.botao_tema.click()
    assert ap.tema is TEMAS["claro"] and janela.botao_tema.toolTip() == "Tema escuro"
    assert qapp.palette().color(QPalette.ColorRole.Window).name() == TEMAS["claro"].fundo
