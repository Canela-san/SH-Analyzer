"""A área de Aquisição na tela (F3.5): a lista de placas, conectar pelo clique, a primeira conexão inteira pelo diálogo
(a impressão, a senha, a chave instalada, a senha padrão, o relógio), a segunda sem diálogo nenhum, "Conectar por IP…"
e a chave de host trocada mostrada como bloqueio. Com o simulador e os servidores SSH do teste
(``placas_de_teste.py``), sem placa e sem tela."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("asyncssh")

from placas_de_teste import CofreFalso, Placas, fonte_que_acha  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QAbstractButton  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.area import AreaDeAquisicao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.placas import PAPEL_DO_LADO  # noqa: E402
from sh_analyzer_gui.servicos.conexao_da_placa import ConexaoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.placa import ServicoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.saude_da_placa import SaudeDaPlaca  # noqa: E402
from sh_placa.descoberta import Descoberta, FonteSimulador  # noqa: E402
from sh_placa.destino import SENHA_PADRAO_DA_IMAGEM  # noqa: E402

ESPERA_MS = 15_000


@pytest.fixture
def placas(tmp_path):
    p = Placas(tmp_path)
    yield p
    p.fechar()


@pytest.fixture
def abrir(qapp, config_limpa, qtbot, tmp_path):
    """A área sozinha, à vista, com as fontes da busca e o cofre do teste."""
    criar_aplicacao([], tema="escuro")
    abertas = []

    def _abrir(*fontes, cofre=None):
        servico = ServicoDaPlaca()
        conexao = ConexaoDaPlaca(servico, descoberta=Descoberta([*fontes, FonteSimulador()]),
                                 pasta=tmp_path / "aplicativo", cofre=cofre if cofre is not None else CofreFalso())
        saude = SaudeDaPlaca(conexao)
        area = AreaDeAquisicao(conexao, saude)
        area.resize(1200, 800)
        area.show()
        qtbot.waitExposed(area)
        qtbot.waitUntil(lambda: len(conexao.placas) == len(fontes) + 1, timeout=ESPERA_MS)   # a busca, ao aparecer
        abertas.append((area, conexao, servico))
        return area

    yield _abrir
    for area, conexao, servico in abertas:
        if area._dialogo is not None:
            area._dialogo.done(0)
        area.close()
        conexao.encerrar()
        assert servico.encerrar()
        area.deleteLater()


def linha(area, nome):
    lista = area.lateral.lista
    modelo = lista.modelo
    for i in range(modelo.rowCount()):
        if modelo.placa(i).nome == nome:
            return lista, modelo.index(i, 0)
    raise AssertionError(f"{nome!r} não está na lista: {[modelo.placa(i).nome for i in range(modelo.rowCount())]}")


def clicar_na_placa(qtbot, area, nome):
    lista, indice = linha(area, nome)
    qtbot.mouseClick(lista.viewport(), Qt.MouseButton.LeftButton, pos=lista.visualRect(indice).center())


def lado(area, nome):
    _lista, indice = linha(area, nome)
    return indice.data(PAPEL_DO_LADO)


def esperar_pagina(qtbot, area, pagina):
    qtbot.waitUntil(lambda: area._dialogo is not None and area._dialogo.isVisible()
                    and area._dialogo.pagina == pagina, timeout=ESPERA_MS)
    return area._dialogo


def espremidos(janela):
    """Os botões visíveis mais estreitos que o texto (a regra do ``test_gui_textos.py``)."""
    return [(b.text(), b.width(), b.minimumSizeHint().width()) for b in janela.findChildren(QAbstractButton)
            if b.isVisibleTo(janela) and b.text().strip() and b.width() < b.minimumSizeHint().width() - 1]


def test_a_lista_e_o_simulador(qtbot, abrir):
    area = abrir()
    c = area.conexao
    assert lado(area, "Simulador") == "demonstração" and area.visao_geral.paginas.currentWidget() is \
        area.visao_geral.vazia
    assert area.lateral.cartao.titulo.text() == "Nenhuma placa conectada" and not area.lateral.rodape.isVisible()
    clicar_na_placa(qtbot, area, "Simulador")
    qtbot.waitUntil(lambda: c.estado == "conectada", timeout=ESPERA_MS)
    assert area._dialogo is None                                  # nada a perguntar: nenhum diálogo
    assert area.lateral.cartao.titulo.text() == "Simulador" and lado(area, "Simulador") == "conectada"
    assert area.lateral.cartao.linhas[0].text() == "demonstração, neste computador"
    assert area.visao_geral.paginas.currentWidget() is area.visao_geral.conectada
    assert "kernel 4.19.94-ti-r42" in area.visao_geral.subtitulo.text()
    assert area.lateral.rodape.isVisible() and not espremidos(area)
    area.mostrar_secao("terminal")
    assert area.terminal.paginas.currentWidget() is area.terminal.simulador and not area.terminal.abas.count()
    area.mostrar_secao("capturar")
    assert area.secoes.currentWidget().titulo.text() == "Capturar: chega na v0.10"
    clicar_na_placa(qtbot, area, "Simulador")                     # a conectada leva à visão geral
    assert area.secao == "visao_geral" and c.estado == "conectada"
    area.lateral.desconectar.click()
    assert c.estado == "desconectada" and lado(area, "Simulador") == "demonstração"
    assert area.visao_geral.paginas.currentWidget() is area.visao_geral.vazia


def test_a_primeira_conexao_inteira_e_a_segunda_sem_dialogo(qtbot, placas, abrir):
    servidor = placas.nova(senha=SENHA_PADRAO_DA_IMAGEM)
    area = abrir(fonte_que_acha(servidor))
    c = area.conexao
    assert lado(area, "bbb-teste") == "LAN"
    clicar_na_placa(qtbot, area, "bbb-teste")

    dialogo = esperar_pagina(qtbot, area, "impressao")
    assert dialogo.impressao.rotulo.text() == servidor.impressao and not espremidos(dialogo)
    assert f"debian@127.0.0.1:{servidor.porta}" in dialogo.texto_da_impressao.text()
    assert lado(area, "bbb-teste") == "conectando…" and area.lateral.cartao.botao_principal.text() == "Responder"
    dialogo.findChild(QAbstractButton, "confiar").click()

    esperar_pagina(qtbot, area, "senha")
    assert dialogo.instalar_chave.isChecked() and not dialogo.guardar_senha.isChecked() and not espremidos(dialogo)
    assert SENHA_PADRAO_DA_IMAGEM in dialogo.dica_da_senha.text() and not dialogo.conectar_com_senha.isEnabled()
    qtbot.keyClicks(dialogo.campo_senha, SENHA_PADRAO_DA_IMAGEM)
    dialogo.conectar_com_senha.click()
    assert dialogo.campo_senha.text() == ""                       # a senha não fica no campo

    esperar_pagina(qtbot, area, "pronta")
    itens = [i.texto.text() for i in dialogo.itens if i.isVisibleTo(dialogo)]
    assert itens[0].startswith("A impressão digital da placa ficou guardada")
    assert itens[1].startswith("A chave do aplicativo foi instalada")
    assert itens[2].startswith("A placa usa a senha padrão da imagem (temppwd)") and "passwd" in itens[2]
    assert dialogo.pergunta.isVisibleTo(dialogo) and not dialogo.concluir.isVisibleTo(dialogo)
    assert not espremidos(dialogo)
    dialogo.acertar.click()
    assert not dialogo.isVisible() and c.estado == "conectada"
    assert preferencias.placas_conhecidas()[0].acertar_relogio is True

    cartao = area.lateral.cartao
    assert cartao.titulo.text() == "bbb-teste" and cartao.linhas[0].text() == "nº 3714BBBK1234 · LAN · 127.0.0.1"
    assert lado(area, "bbb-teste") == "conectada" and lado(area, "Simulador") == "demonstração"
    qtbot.waitUntil(lambda: "latência" in cartao.linhas[1].text(), timeout=ESPERA_MS)
    assert "MB/s" in cartao.linhas[1].text() or "kB/s" in cartao.linhas[1].text()
    qtbot.waitUntil(lambda: "latência" in area.visao_geral.linhas["conexao"].resumo.text(), timeout=ESPERA_MS)
    assert area.visao_geral.relogio.valor.text().endswith(" s")

    area.lateral.desconectar.click()
    qtbot.waitUntil(lambda: lado(area, "bbb-teste") == "LAN", timeout=ESPERA_MS)
    clicar_na_placa(qtbot, area, "bbb-teste")
    qtbot.waitUntil(lambda: c.estado == "conectada", timeout=ESPERA_MS)
    assert not dialogo.isVisible() and c.autenticada_com == "chave"   # a chave, sem diálogo nenhum


def test_conectar_por_ip_e_a_chave_trocada_como_bloqueio(qtbot, placas, abrir):
    servidor = placas.nova()
    area = abrir(cofre=CofreFalso(**{f"debian@127.0.0.1:{servidor.porta}": servidor.senha}))
    c = area.conexao
    area.lateral.por_ip.click()
    dialogo = esperar_pagina(qtbot, area, "destino")
    dialogo.usar_salto.setChecked(True)
    assert dialogo.caixa_do_salto.isVisibleTo(dialogo) and not espremidos(dialogo)
    dialogo.usar_salto.setChecked(False)
    qtbot.keyClicks(dialogo.campo_host, "placa da sala")
    dialogo.findChild(QAbstractButton, "conectar_ao_destino").click()
    assert dialogo.pagina == "destino" and "espaços" in dialogo.erro_do_destino.text()
    dialogo.campo_host.clear()
    qtbot.keyClicks(dialogo.campo_host, f"debian@127.0.0.1:{servidor.porta}")
    dialogo.findChild(QAbstractButton, "conectar_ao_destino").click()
    esperar_pagina(qtbot, area, "impressao").findChild(QAbstractButton, "confiar").click()
    esperar_pagina(qtbot, area, "pronta")                         # a senha do cofre: sem a página da senha
    assert [i.texto.text().split(":")[0] for i in dialogo.itens if i.isVisibleTo(dialogo)] == [
        "A impressão digital da placa ficou guardada", "A chave do aplicativo não foi instalada"]
    dialogo.nao_acertar.click()
    assert c.estado == "conectada" and preferencias.placas_conhecidas()[0].acertar_relogio is False
    area.lateral.desconectar.click()

    antiga = servidor.impressao
    placas.rodar(servidor.trocar_chave_do_host)                   # a placa regravada
    area.lateral.por_ip.click()
    esperar_pagina(qtbot, area, "destino")
    assert dialogo.campo_host.text() == "127.0.0.1" and dialogo.campo_porta.value() == servidor.porta
    dialogo.findChild(QAbstractButton, "conectar_ao_destino").click()
    esperar_pagina(qtbot, area, "bloqueada")
    assert (dialogo.conhecida.rotulo.text(), dialogo.apresentada.rotulo.text()) == (antiga, servidor.impressao)
    assert "Nada foi enviado" in dialogo.texto_do_bloqueio.text() and not dialogo.esquecer.isEnabled()
    assert not espremidos(dialogo)
    qtbot.keyClick(dialogo, Qt.Key.Key_Escape)                    # fechar não desbloqueia nada
    assert not dialogo.isVisible() and c.estado == "bloqueada"
    assert area.lateral.cartao.titulo.text() == "Conexão bloqueada"
    assert area.visao_geral.falha.titulo.text() == "Conexão bloqueada" and \
        area.visao_geral.botao_de_tentar.text() == "Ver o que fazer"
    area.visao_geral.botao_de_tentar.click()
    esperar_pagina(qtbot, area, "bloqueada")
    qtbot.keyClick(dialogo, Qt.Key.Key_Escape)
    area.lateral.cartao.botao_principal.click()                   # "Ver", no cartão
    esperar_pagina(qtbot, area, "bloqueada")
    dialogo.conferi.setChecked(True)
    dialogo.esquecer.click()
    esperar_pagina(qtbot, area, "impressao")
    assert dialogo.impressao.rotulo.text() == servidor.impressao  # a nova, para conferir
    dialogo.findChild(QAbstractButton, "confiar").click()
    esperar_pagina(qtbot, area, "pronta")
    assert not dialogo.pergunta.isVisibleTo(dialogo)              # o relógio já foi respondido
    dialogo.concluir.click()
    assert not dialogo.isVisible() and c.estado == "conectada"


def test_esc_e_a_resposta_segura(qtbot, placas, abrir):
    """Fechar a pergunta da impressão é não confiar (nada fixado); fechar a da senha cancela a conexão."""
    servidor = placas.nova()
    area = abrir(fonte_que_acha(servidor))
    c = area.conexao
    clicar_na_placa(qtbot, area, "bbb-teste")
    dialogo = esperar_pagina(qtbot, area, "impressao")
    qtbot.keyClick(dialogo, Qt.Key.Key_Escape)
    assert not dialogo.isVisible() and c.estado == "desconectada"
    clicar_na_placa(qtbot, area, "bbb-teste")
    esperar_pagina(qtbot, area, "impressao").findChild(QAbstractButton, "confiar").click()
    esperar_pagina(qtbot, area, "senha")
    qtbot.keyClick(dialogo, Qt.Key.Key_Escape)
    assert not dialogo.isVisible() and c.estado == "desconectada"
    assert lado(area, "bbb-teste") == "LAN" and area.lateral.cartao.titulo.text() == "Nenhuma placa conectada"
