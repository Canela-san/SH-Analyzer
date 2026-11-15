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


def test_a_seta_das_caixas_de_escolha_e_a_do_tema():
    from sh_analyzer_gui.tema.svgs import arquivo_svg

    for tema in TEMAS.values():
        seta = arquivo_svg("baixo", tema.texto2)
        assert seta.as_posix() in gerar_qss(tema)
        assert f'stroke="{tema.texto2}"' in seta.read_text(encoding="utf-8")
    assert arquivo_svg("baixo", "#ABCDEF") == arquivo_svg("baixo", "#abcdef")       # o mesmo arquivo
    with pytest.raises(ValueError, match="cor"):
        arquivo_svg("baixo", "red")
    with pytest.raises(KeyError):
        arquivo_svg("nao_existe", "#000000")


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
    assert janela.barra.botao_tema.toolTip() == "Tema claro"
    janela.barra.botao_tema.click()
    assert ap.tema is TEMAS["claro"] and janela.barra.botao_tema.toolTip() == "Tema escuro"
    assert qapp.palette().color(QPalette.ColorRole.Window).name() == TEMAS["claro"].fundo


def test_nenhuma_lambda_ligada_a_troca_de_tema():
    """``aparencia().mudou.connect(lambda ...)`` não se desfaz quando o widget é destruído: a próxima troca de tema
    chamaria um objeto morto (o erro apareceu no chip de traço). Ligue a um método do próprio widget."""
    import re
    from pathlib import Path

    pacote = Path(__file__).resolve().parents[1] / "scripts" / "sh_analyzer_gui"
    for arquivo in pacote.rglob("*.py"):
        assert not re.search(r"mudou\.connect\(\s*lambda", arquivo.read_text(encoding="utf-8")), arquivo.name


def test_fontes_embutidas_registram_e_se_escolhem(qapp):
    from sh_analyzer_gui.tema import fontes

    familias = registrar_fontes()
    for familia in ("Inter", "JetBrains Mono", "IBM Plex Sans", "IBM Plex Mono", "Atkinson Hyperlegible Next"):
        assert familia in familias                                     # mesmo sem elas instaladas no sistema
    assert fontes.familias_disponiveis("interface") == ["Inter", "IBM Plex Sans", "Atkinson Hyperlegible Next"]
    assert fontes.familias_disponiveis("mono") == ["JetBrains Mono", "IBM Plex Mono"]
    for familia in ("IBM Plex Sans", "Atkinson Hyperlegible Next"):    # os quatro pesos que a interface usa
        assert {"Regular", "Medium", "SemiBold", "Bold"} <= set(fontes.QFontDatabase.styles(familia)), familia
    assert fonte_mono().family() == "JetBrains Mono" and fonte_da_interface().family() == "Inter"
    sistema = fontes.QFontDatabase.systemFont(fontes.QFontDatabase.SystemFont.GeneralFont).family()
    try:
        fontes.escolher_fonte("interface", sistema, qapp)
        assert qapp.font().family() == sistema and fontes.fonte_escolhida("interface") == sistema
    finally:
        fontes.escolher_fonte("interface", "Inter", qapp)
    assert qapp.font().family() == "Inter"
    with pytest.raises(ValueError):
        fontes.escolher_fonte("interface", "Fonte Que Não Existe")
    with pytest.raises(ValueError):
        fontes.familias_disponiveis("titulo")
