"""O aviso de versão nova na tela: o cartão (``componentes/versao_nova.py``) em cada instalação e a janela
(consultar uma vez por dia, pular, baixar e fechar para instalar, o download que falha, o "Procurar agora" das
configurações). A consulta e o download são trocados por falsos: nada vai à internet."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from sh_analyzer_gui.servicos import versao_nova as vn  # noqa: E402

# ------------------------------------------------------------------ o cartão e a janela

LANCAMENTO = vn.Lancamento("0.10", "https://exemplo/releases/v0.10", "As novidades.",
                           vn.Arquivo("sh-analyzer-v0.10-windows-x64.exe", "https://exemplo/x.exe", 10),
                           vn.Arquivo("SHA256SUMS", "https://exemplo/SHA256SUMS", 1))


@pytest.fixture
def qt(qapp, config_limpa):
    from sh_analyzer_gui.app import criar_aplicacao

    return criar_aplicacao([], tema="escuro")


def test_o_cartao_em_cada_instalacao(qt, qtbot):
    from PySide6.QtWidgets import QWidget
    from sh_analyzer_gui.componentes.versao_nova import CartaoDeVersaoNova

    pai = QWidget()
    qtbot.addWidget(pai)
    pai.resize(1000, 700)
    pai.show()
    qtbot.waitExposed(pai)
    abertas = []
    cartao = CartaoDeVersaoNova(pai, abrir_url=lambda url: abertas.append(url.toString()))
    cartao.mostrar(LANCAMENTO, "0.9.0", "windows")
    assert cartao.isVisible() and "0.10" in cartao.titulo.text() and "0.9.0" in cartao.texto.text()
    assert cartao.agir.text() == "Atualizar agora"
    with qtbot.waitSignal(cartao.atualizarPedido):
        cartao.agir.click()
    cartao.baixando(0.5)
    assert cartao.barra.isVisible() and cartao.barra.value() == 500 and not cartao.agir.isEnabled()
    cartao.falhou("sem rede")
    assert "sem rede" in cartao.texto.text() and cartao.agir.isEnabled() and not cartao.barra.isVisible()
    cartao.mostrar(LANCAMENTO, "0.9.0", "apt")
    assert not cartao.agir.isVisible() and "Atualizador de Programas" in cartao.texto.text()
    cartao.mostrar(LANCAMENTO, "0.9.0", "pasta")
    cartao.agir.click()
    cartao.novidades.click()
    assert abertas == [LANCAMENTO.pagina] * 2
    with qtbot.waitSignal(cartao.pularPedido):
        cartao.pular.click()
    assert not cartao.isVisible()
    assert cartao.x() + cartao.width() <= pai.width()                         # no canto de cima, à direita


@pytest.fixture
def janela(qt, qtbot, tmp_path):
    from sh_analyzer_gui import preferencias
    from sh_analyzer_gui.janela import JanelaPrincipal

    preferencias.mudar_pasta("cache", tmp_path / "cache")
    j = JanelaPrincipal()
    j.resize(1200, 800)
    j.show()
    qtbot.waitExposed(j)
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def test_a_janela_so_consulta_uma_vez_por_dia_e_fora_do_codigo(janela, monkeypatch):
    from sh_analyzer_gui import preferencias

    chamadas = []
    monkeypatch.setattr(vn, "consultar", lambda local, *a, **k: chamadas.append(local))
    assert janela.modo_de_instalacao == "dev" and janela.consultar_versao_nova() is None
    janela.modo_de_instalacao = "windows"
    preferencias.mudar_procurar_versoes_novas(False)
    assert janela.consultar_versao_nova() is None
    preferencias.mudar_procurar_versoes_novas(True)
    assert janela.consultar_versao_nova() is not None
    assert janela.consultar_versao_nova() is None                            # a de hoje já foi
    assert preferencias.ultima_consulta() is not None


def test_a_janela_avisa_pula_e_atualiza(janela, qtbot, monkeypatch, tmp_path):
    from sh_analyzer_gui import preferencias

    monkeypatch.setattr(vn, "consultar", lambda local, *a, **k: LANCAMENTO)
    janela.modo_de_instalacao = "windows"
    tarefa = janela.consultar_versao_nova(forcar=True)
    qtbot.waitUntil(lambda: janela.versao_nova.isVisible())
    assert tarefa.estado == "concluida"
    # Pulada, a versão não volta na consulta do dia seguinte.
    janela.versao_nova.pular.click()
    assert preferencias.versao_pulada() == "0.10"
    monkeypatch.setattr(preferencias, "ultima_consulta", lambda: None)
    tarefa = janela.consultar_versao_nova()
    qtbot.waitUntil(lambda: tarefa.estado == "concluida")
    assert not janela.versao_nova.isVisible()
    # O Atualizar agora: baixa (numa tarefa) e fecha a janela; o instalador roda no closeEvent.
    preferencias.pular_versao("")
    janela.consultar_versao_nova(forcar=True)
    qtbot.waitUntil(lambda: janela.versao_nova.isVisible())
    baixado = tmp_path / "sh-analyzer-v0.10-windows-x64.exe"
    baixado.write_bytes(b"MZ")
    monkeypatch.setattr(vn, "baixar_instalador", lambda *a, **k: baixado)
    rodados = []
    monkeypatch.setattr(vn, "iniciar_instalador", rodados.append)
    janela.versao_nova.agir.click()
    qtbot.waitUntil(lambda: rodados == [baixado])
    assert not janela.isVisible()


def test_o_download_que_falha_fica_no_cartao(janela, qtbot, monkeypatch):
    monkeypatch.setattr(vn, "consultar", lambda local, *a, **k: LANCAMENTO)

    def falhar(*_a, **_k):
        raise vn.ErroDeAtualizacao("a soma não confere")

    monkeypatch.setattr(vn, "baixar_instalador", falhar)
    janela.modo_de_instalacao = "windows"
    janela.consultar_versao_nova(forcar=True)
    qtbot.waitUntil(lambda: janela.versao_nova.isVisible())
    janela.versao_nova.agir.click()
    qtbot.waitUntil(lambda: "a soma não confere" in janela.versao_nova.texto.text())
    assert janela.isVisible() and janela.instalador_ao_fechar is None


def test_procurar_agora_nas_configuracoes(janela, qtbot, monkeypatch):
    from sh_analyzer_gui import preferencias
    from sh_analyzer_gui.areas.configuracoes import DialogoDeConfiguracoes

    monkeypatch.setattr(vn, "consultar", lambda local, *a, **k: None)
    dialogo = DialogoDeConfiguracoes(janela)
    qtbot.addWidget(dialogo)
    dialogo.mostrar_secao("atualizacoes")
    dialogo.procurar_versoes.setChecked(False)
    assert not preferencias.procurar_versoes_novas()
    dialogo.procurar_versoes.setChecked(True)
    pedidas = []
    original = janela.consultar_versao_nova
    monkeypatch.setattr(janela, "consultar_versao_nova", lambda **k: pedidas.append(k) or original(**k))
    from PySide6.QtWidgets import QPushButton

    dialogo.findChild(QPushButton, "procurar_versao_agora").click()
    assert pedidas == [{"forcar": True}]
