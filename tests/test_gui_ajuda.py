"""A ajuda (F7.11): o guia separado em seções, cada "?" da janela abrindo a seção certa no leitor, o F1 na vista à
frente, e os primeiros passos levando do nada à primeira medida com a captura de exemplo."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtWidgets import QToolButton  # noqa: E402
from sh_analyzer_gui import ajuda, preferencias  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.configuracao import gravar  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402

ESPERA_MS = 30_000


def test_o_guia_tem_as_secoes_que_a_janela_pede():
    secoes = {s.id: s for s in ajuda.ler_guia()}
    pedidas = set(ajuda.SECAO_DO_TIPO.values()) | {"primeiros-passos", "janela", "abrir", "projeto", "inspetor",
                                                  "medidas", "transformacoes", "aliasing", "alinhar", "figuras",
                                                  "aquisicao", "configuracoes", "anotacoes", "caderno"}
    assert pedidas <= set(secoes), pedidas - set(secoes)
    assert all("{#" not in s.texto for s in secoes.values() if s.id != "guia")       # a introdução explica a sintaxe
    assert secoes["espectro"].texto.startswith("## O espectro") and "intervalo de confiança" in secoes["espectro"].texto


def _janela(qtbot, tmp_path):
    criar_aplicacao([], tema="escuro")
    preferencias.mudar_pasta("cache", tmp_path / "cache")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.resize(1400, 900)
    j.show()
    return j


@pytest.fixture
def janela(qapp, config_limpa, qtbot, tmp_path):
    j = _janela(qtbot, tmp_path)
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def _botoes(janela):
    return [b for b in janela.findChildren(QToolButton) if b.property("ajuda")]


def test_cada_interrogacao_abre_a_secao_dela(janela, qtbot):
    janela.primeiros_passos.passos[0].fazer()                        # o exemplo, para as vistas terem traços
    qtbot.waitUntil(lambda: bool(janela.projeto.fontes), timeout=ESPERA_MS)
    janela.primeiros_passos.passos[1].fazer()
    for nome in ("espectro", "xy", "qualidade", "instrumento"):
        janela.acoes[nome].trigger()
        janela.area.ativar_vista(next(v for v in janela.projeto.vistas if v.tipo == "tempo"))
    secoes = {s.id for s in ajuda.ler_guia()}
    assert janela.figuras is not None and janela.aquisicao is not None  # as áreas montadas depois da partida
    botoes = _botoes(janela)
    vistos = set()
    for botao in botoes:
        secao = botao.property("ajuda")
        if secao == "medidas":
            continue                                                  # o do painel de baixo segue a aba
        botao.click()
        leitor = janela.leitor_do_guia
        assert leitor.secao_atual == secao and secao in secoes
        assert leitor.texto.toMarkdown().strip()
        vistos.add(secao)
    assert {"projeto", "inspetor", "tempo", "espectro", "xy", "qualidade", "instrumento", "aquisicao",
            "figuras"} <= vistos, vistos
    janela.leitor_do_guia.busca.setText("coerência")                 # a busca filtra as seções
    visiveis = [janela.leitor_do_guia.lista.item(i).text() for i in range(janela.leitor_do_guia.lista.count())
                if not janela.leitor_do_guia.lista.item(i).isHidden()]
    assert "A transferência" in visiveis and "O projeto" not in visiveis


def test_o_f1_abre_a_secao_da_vista_a_frente(janela, qtbot):
    assert janela.secao_da_ajuda() == "primeiros-passos"
    janela.acoes["ajuda"].trigger()
    assert janela.leitor_do_guia.secao_atual == "primeiros-passos"
    janela.primeiros_passos.passos[0].fazer()
    qtbot.waitUntil(lambda: bool(janela.projeto.fontes), timeout=ESPERA_MS)
    janela.primeiros_passos.passos[1].fazer()
    janela.acoes["espectro"].trigger()
    janela.acoes["ajuda"].trigger()
    assert janela.leitor_do_guia.secao_atual == "espectro"
    janela.mostrar_area(2)
    assert janela.secao_da_ajuda() == "aquisicao"


@pytest.fixture
def primeira_vez(qapp, config_limpa, qtbot, tmp_path):
    gravar("ajuda/primeiros_passos", "")                              # a configuração de quem nunca abriu
    j = _janela(qtbot, tmp_path)
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def test_os_primeiros_passos_levam_a_primeira_medida(primeira_vez, qtbot):
    janela = primeira_vez
    cartao = janela.primeiros_passos
    qtbot.waitUntil(cartao.isVisible, timeout=ESPERA_MS)
    # No canto de baixo à direita da janela inteira (por cima do inspetor), acima da barra de status.
    assert cartao.parentWidget() is janela
    canto = cartao.geometry().bottomRight()
    assert janela.width() - canto.x() <= 24 and janela.statusBar().geometry().top() - canto.y() <= 24
    cartao.definir_recolhido(True)                                    # recolhido: o título com o progresso, no canto
    assert not cartao.corpo.isVisible() and "0 de 4" in cartao.titulo.text()
    assert janela.width() - cartao.geometry().right() <= 24
    cartao.definir_recolhido(False)
    assert cartao.botoes["abrir"].isEnabled() and not cartao.botoes["plotar"].isEnabled()
    cartao.botoes["abrir"].click()
    qtbot.waitUntil(lambda: cartao.feitos()["abrir"], timeout=ESPERA_MS)
    fonte = janela.projeto.fontes[0]
    assert fonte.nome == "exemplo-rede-60Hz.bin" and fonte.caminho.is_relative_to(preferencias.pasta("cache"))
    # O exemplo não abre com um aviso para quem está começando (só informações).
    assert {a.nivel for a, _ in janela.avisos.avisos} <= {"info"}
    cartao.conferir()
    cartao.botoes["plotar"].click()
    qtbot.waitUntil(lambda: cartao.feitos()["plotar"], timeout=ESPERA_MS)
    cartao.conferir()
    cartao.botoes["medir"].click()
    qtbot.waitUntil(lambda: cartao.feitos()["medir"], timeout=ESPERA_MS)
    cartao.conferir()
    cartao.botoes["espectro"].click()
    qtbot.waitUntil(lambda: cartao.feitos()["espectro"], timeout=ESPERA_MS)
    cartao.conferir()
    assert cartao.concluido.isVisible()                              # o opcional (a aquisição) não segura o fim
    cartao.encerrar()
    assert not cartao.isVisible()
    outra = _janela(qtbot, preferencias.pasta("cache").parent)       # não volta sozinho
    qtbot.wait(50)
    assert not outra.primeiros_passos.isVisible()
    outra.close()
    outra.deleteLater()


def test_o_exemplo_pelo_estado_vazio(janela, qtbot):
    from PySide6.QtWidgets import QPushButton

    botao = janela.vazio_central.findChild(QPushButton, "botao_exemplo_central")
    assert botao is not None and janela.centro.currentWidget() is janela.vazio_central
    botao.click()
    qtbot.waitUntil(lambda: bool(janela.projeto.fontes), timeout=ESPERA_MS)
    assert janela.projeto.fontes[0].nome == "exemplo-rede-60Hz.bin"
