"""A seção Capturar da Aquisição (F4.3, o B2): o formulário monta o pedido e o valida ao vivo, os modelos de captura
ficam no projeto (com o desfazer), o pedido da última vez volta, e o "Conferir antes" roda na placa simulada (por
SSH, neste computador), com a faixa sugerida de cada canal. Sem placa e sem tela."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("asyncssh")

from placas_de_teste import CofreFalso  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.area import AreaDeAquisicao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.capturar import Capturar, resumo_do_pedido  # noqa: E402
from sh_analyzer_gui.modelo.objetos import Projeto  # noqa: E402
from sh_analyzer_gui.servicos.conexao_da_placa import ConexaoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.conferencia_da_placa import ConferenciaDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.placa import ServicoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.saude_da_placa import SaudeDaPlaca  # noqa: E402
from sh_placa.descoberta import Descoberta, FonteSimulador  # noqa: E402
from sh_placa.pedido import Canal, PedidoDeCaptura  # noqa: E402

ESPERA_MS = 20_000
SONDAS = __import__("pathlib").Path(__file__).resolve().parents[1] / "scripts" / "sondas"


@pytest.fixture
def secao(qapp, config_limpa, qtbot, tmp_path):
    """A seção sem placa: ``secao(**opcoes)`` a monta (os perfis de ``scripts/sondas``, o destino numa pasta do
    teste, com 10 GB livres)."""
    criar_aplicacao([], tema="escuro")
    feitas = []

    def _secao(**opcoes):
        servico = ServicoDaPlaca()
        conexao = ConexaoDaPlaca(servico, descoberta=Descoberta([]), pasta=tmp_path / "aplicativo", cofre=CofreFalso())
        saude = SaudeDaPlaca(conexao)
        conferencia = ConferenciaDaPlaca(conexao, saude, pasta=tmp_path / "conferencias")
        opcoes = {"pasta_das_sondas": lambda: SONDAS, "pasta_do_destino": lambda: tmp_path / "dados",
                  "livre": lambda _pasta: 10 * 10**9, "lembrar": False, **opcoes}
        s = Capturar(conexao, saude, conferencia, **opcoes)
        s.resize(1280, 900)
        s.show()
        qtbot.waitExposed(s)
        feitas.append((s, conexao, servico))
        return s

    yield _secao
    for s, conexao, servico in feitas:
        s.close()
        conexao.encerrar()
        assert servico.encerrar()
        s.deleteLater()


def test_o_formulario_monta_o_pedido_e_o_comando(secao, qtbot):
    s = secao()
    f = s.formulario
    assert f.pedido == PedidoDeCaptura()                                         # o padrão do ler_adc
    assert s.comando.rotulo.text() == "sudo ./ler_adc 400000 1 --blocos 1 -o -"
    f.linhas[0].ligado.setChecked(True)
    f.linhas[0].grandeza.setCurrentIndex(f.linhas[0].grandeza.findData("corrente"))
    f.linhas[0].sonda.setEditText("sct013_100a_sn001")
    assert f.linhas[0].ganho.text() == "19,65"                                   # o ganho do perfil
    f.linhas[0].faixa.setCurrentIndex(f.linhas[0].faixa.findData(5.12))
    qtbot.keyClicks(f.titulo, "Rede de casa")
    f.modo_da_duracao.escolher(0)
    f.duracao.setText("10")
    f.duracao.textEdited.emit("10")
    assert f.pedido == PedidoDeCaptura((Canal(0, "corrente", "sct013_100a_sn001", 5.12, 19.65), Canal(1)),
                                       duracao_s=600.0, titulo="Rede de casa")
    assert s.comando.rotulo.text() == ("sudo ./ler_adc 400000 0,1 --duracao 10m -t 'Rede de casa' --grandeza "
                                       "0:corrente,1:tensao --sonda 0:sct013_100a_sn001 --ganho 0:19.65 "
                                       "--faixa-adc 0:5.12,1:20.48 -o -")
    assert f.contador_do_titulo.text() == "12 / 127 bytes"
    assert f.linhas[0].lsb.text() == "LSB 78,12 µV"
    assert "229 blocos inteiros" in f.texto_da_duracao.text()
    assert "100 kHz" in f.texto_da_taxa.text()
    assert f.secoes["canais"].lado.text() == "2 de 8"
    assert s.subtitulo.text() == resumo_do_pedido(f.pedido)
    # 2 canais a 400 kS/s: o aviso da Nyquist, no formulário e no centro; capturar segue possível.
    assert any("150 kHz" in t for t in f.secoes["taxa"].problemas.textos)
    assert s.estado.text() == "Pode capturar, com 1 aviso"


def test_os_erros_ficam_no_campo_e_impedem(secao, qtbot):
    s = secao()
    f = s.formulario
    f.titulo.setText("ç" * 64)                                                   # 128 bytes
    f.titulo.textEdited.emit(f.titulo.text())
    assert f.titulo.property("invalido") and f.contador_do_titulo.objectName() == "problema_erro"
    assert s.estado.text() == "1 problema impede a captura"
    assert not s.conferir.isEnabled()
    f.titulo.clear()
    f.titulo.textEdited.emit("")
    f.taxa.setText("420k")
    f.taxa.editingFinished.emit()
    assert f.pedido.taxa_hz == 420_000 and f.taxa.property("invalido")
    assert any("419287 S/s" in t for t in f.secoes["taxa"].problemas.textos)
    f.abrir_avancado.setChecked(True)
    f.forcar_taxa.setChecked(True)
    assert not f.taxa.property("invalido") and "forçada" in f.secoes["avancado"].lado.text()
    f.linhas[1].ligado.setChecked(False)
    assert s.estado.text() == "1 problema impede a captura" and f.pedido.canais == ()


def test_um_canal_desligado_volta_como_estava(secao):
    f = secao().formulario
    f.linhas[3].ligado.setChecked(True)
    f.linhas[3].grandeza.setCurrentIndex(f.linhas[3].grandeza.findData("temperatura"))
    f.linhas[3].ganho.setText("2,5")
    f.linhas[3].ganho.textEdited.emit("2,5")
    f.linhas[3].ligado.setChecked(False)
    assert 3 not in f.pedido.numeros and f.linhas[3].desligado.isVisible()
    f.definir_pedido(PedidoDeCaptura())
    f.linhas[3].ligado.setChecked(True)
    assert f.pedido.canal(3) == Canal(3, "temperatura", ganho=2.5)


@pytest.mark.parametrize("pedido", [
    PedidoDeCaptura(),
    PedidoDeCaptura((Canal(0, "corrente", "sct013_100a_sn001", 5.12, 19.65), Canal(5, faixa_v=10.24)), 250_000,
                    duracao_s=2.5, titulo="Rede", descricao="duas linhas\nde descrição", spi="rapido:c",
                    atrasos_cs=(4, 2, 12), forcar_taxa=True),
    PedidoDeCaptura((Canal(2, "temperatura"),), 50_000, blocos=0, destino="cartao", arquivo_no_cartao="noite.bin"),
    PedidoDeCaptura((Canal(7, ganho=1e-3),), 400_000, blocos=12, spi="lenta"),
    PedidoDeCaptura(duracao_s=7200.0),
])
def test_um_pedido_posto_no_formulario_volta_igual(secao, pedido):
    f = secao().formulario
    f.definir_pedido(pedido)
    assert f.pedido == pedido and f.pedido_dos_campos() == pedido


def test_o_destino_no_cartao_e_o_espaco(secao):
    s = secao(livre=lambda _pasta: 100 * 2**20)
    f = s.formulario
    assert "100 MiB livres aqui" in f.texto_do_destino.text() and not f.arquivo_no_cartao.isVisible()
    f.definir_pedido(PedidoDeCaptura(duracao_s=600.0))                           # 458 MiB
    assert s.estado.text() == "1 problema impede a captura"
    assert any("Não cabe no computador" in t for t in f.secoes["destino"].problemas.textos)
    f.destino.escolher(1)
    assert f.arquivo_no_cartao.isVisible() and "Conecte a placa" in f.texto_do_destino.text()
    assert s.estado.text() == "O pedido está certo para capturar"               # o cartão sem placa: não confere
    f.arquivo_no_cartao.setText("x/y.bin")
    f.arquivo_no_cartao.textEdited.emit("x/y.bin")
    assert f.arquivo_no_cartao.property("invalido")


def test_os_modelos_ficam_no_projeto_com_o_desfazer(secao):
    nomes = iter(["Rede V + I"])
    s = secao(pedir_nome=lambda _t, _r, _texto: next(nomes))
    f = s.formulario
    assert not f.botao_do_modelo.isEnabled()                                    # sem projeto
    projeto = Projeto()
    s.acompanhar(projeto)
    assert f.botao_do_modelo.text() == "Modelo: nenhum"
    rede = PedidoDeCaptura((Canal(0, "corrente"), Canal(1)), duracao_s=600.0, titulo="Rede")
    f.definir_pedido(rede)
    s.guardar_como_modelo()
    assert projeto.modelos_de_captura[0].pedido == rede and projeto.modificado
    assert f.botao_do_modelo.text() == "Modelo: Rede V + I"
    f.titulo.setText("Rede da tarde")
    f.titulo.textEdited.emit("Rede da tarde")
    assert f.botao_do_modelo.text() == "Modelo: Rede V + I · mudado"
    s._montar_o_menu()
    acoes = [a.text() for a in s.menu_dos_modelos.actions() if a.text()]
    assert acoes == ["Rede V + I", "Guardar como modelo…", "Atualizar «Rede V + I»", "Apagar «Rede V + I»"]
    f.definir_pedido(PedidoDeCaptura())
    s.carregar_modelo("Rede V + I")
    assert f.pedido == rede and f.botao_do_modelo.text() == "Modelo: Rede V + I"
    s.apagar_modelo("Rede V + I")
    assert projeto.modelos_de_captura == () and f.botao_do_modelo.text() == "Modelo: nenhum"
    projeto.pilha.undo()
    assert [m.nome for m in projeto.modelos_de_captura] == ["Rede V + I"]


def test_o_pedido_da_ultima_vez_volta(secao, qtbot):
    s = secao(lembrar=True)
    pedido = PedidoDeCaptura((Canal(0, "corrente"),), 200_000, duracao_s=60.0, titulo="Volta")
    s.formulario.definir_pedido(pedido)
    qtbot.waitUntil(lambda: preferencias.ultimo_pedido() == pedido, timeout=ESPERA_MS)
    assert secao(lembrar=True).formulario.pedido == pedido


# ------------------------------------------------------------------ o "Conferir antes" na placa simulada


@pytest.fixture
def area(qapp, config_limpa, qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("DADOS", str(tmp_path / "dados"))
    criar_aplicacao([], tema="escuro")
    servico = ServicoDaPlaca()
    conexao = ConexaoDaPlaca(servico, descoberta=Descoberta([FonteSimulador()]), pasta=tmp_path / "aplicativo",
                             cofre=CofreFalso())
    saude = SaudeDaPlaca(conexao)
    conferencia = ConferenciaDaPlaca(conexao, saude, pasta=tmp_path / "conferencias")
    a = AreaDeAquisicao(conexao, saude, conferencia=conferencia,
                        opcoes_da_captura={"pasta_das_sondas": lambda: SONDAS, "lembrar": False})
    a.resize(1440, 900)
    a.show()
    qtbot.waitExposed(a)
    qtbot.waitUntil(lambda: len(conexao.placas) == 1, timeout=ESPERA_MS)
    conexao.conectar(conexao.placas[0])
    qtbot.waitUntil(lambda: conexao.estado == "conectada" and saude.saude is not None and saude.capturas is not None
                    and not saude.conferindo, timeout=ESPERA_MS)
    a.mostrar_secao("capturar")
    yield a
    a.close()
    conexao.encerrar()
    assert servico.encerrar()
    a.deleteLater()


def test_conferir_antes_na_placa_simulada_sugere_a_faixa(area, qtbot, tmp_path):
    """A corrente da bancada simulada (~0,7 V de pico no pino) cabe em ±2,56 V; a tomada (~9 V) fica em ±10,24 V. A
    senha do sudo é a da sessão: nada pergunta. Depois de usar a faixa sugerida, a conferência pede outra."""
    s, f = area.capturar, area.capturar.formulario
    f.definir_pedido(PedidoDeCaptura((Canal(0, "corrente", ganho=19.65), Canal(1, ganho=19.357)), 400_000,
                                     duracao_s=3600.0))
    assert s.conferir.isEnabled()
    qtbot.mouseClick(s.conferir, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: area.conferencia.estado in ("feita", "falhou", "precisa_da_senha"), timeout=ESPERA_MS)
    assert area.conferencia.estado == "feita", area.conferencia.erro
    feita = area.conferencia.resultado
    assert feita.pedido.blocos_pedidos == 1 and feita.conferencia.integra and feita.pronta
    assert feita.faixas_sugeridas == {0: 5.12}
    assert s.titulo_da_conferencia.text().endswith("pronto para capturar")
    textos = s.lista_da_conferencia.textos
    assert any(t.startswith("Captura íntegra") for t in textos)
    assert any(t.startswith("Canal 0: ") and "pp no pino" in t for t in textos)
    assert any(t.startswith("Canal 1: o pico") and "usa 88 % de ±10,24 V, a maior faixa" in t for t in textos)
    assert f.linhas[0].sugerir.isVisible() and f.linhas[0].sugerir.text() == "usar ±2,56 V"
    assert not f.linhas[1].sugerir.isVisible() and s.usar_as_faixas.isVisible()
    s.usar_as_faixas.click()
    assert f.pedido.canal(0).faixa_v == 5.12 and not f.linhas[0].sugerir.isVisible()
    assert s.lista_da_conferencia.textos[0].startswith("O pedido mudou depois da conferência")
    assert not list((tmp_path / "conferencias").iterdir())                      # o arquivo da conferência não fica


def test_conferir_com_a_faixa_pequena_demais_mostra_a_saturacao(area, qtbot):
    s, f = area.capturar, area.capturar.formulario
    f.definir_pedido(PedidoDeCaptura((Canal(1, faixa_v=5.12),)))
    s.conferir_antes()
    qtbot.waitUntil(lambda: area.conferencia.estado in ("feita", "falhou"), timeout=ESPERA_MS)
    feita = area.conferencia.resultado
    assert not feita.pronta and feita.problemas == 1
    assert "1 problema(s)" in s.titulo_da_conferencia.text()
    # O pico cortado não diz qual faixa cabe: a conferência manda para a maior, a um clique.
    assert feita.faixas_sugeridas == {1: 20.48}
    assert any("fundo de escala em ±2,56 V (saturou): confira em ±10,24 V, a maior faixa" in t
               for t in s.lista_da_conferencia.textos)
    assert s.usar_as_faixas.isVisibleTo(s)
    qtbot.mouseClick(s.usar_as_faixas, Qt.MouseButton.LeftButton)
    assert f.pedido.canal(1).faixa_v == 20.48 and not s.usar_as_faixas.isVisibleTo(s)
    # Nela, a tomada da placa simulada (±9 V no pino) cabe, sem os 15 % de folga: pronto, com o aviso.
    s.conferir_antes()
    qtbot.waitUntil(lambda: area.conferencia.estado == "feita" and area.conferencia.resultado is not feita,
                    timeout=ESPERA_MS)
    assert area.conferencia.resultado.pronta and s.titulo_da_conferencia.text().endswith("pronto para capturar")
    assert any(t.startswith("Canal 1: o pico") and "a maior faixa: um surto de" in t
               for t in s.lista_da_conferencia.textos), s.lista_da_conferencia.textos


def test_sem_a_senha_da_sessao_a_conferencia_pergunta(area, qtbot):
    """Sem a senha desta conexão nem a do cofre, a conferência pede a do sudo; a errada é recusada, e a certa
    confere e fica na sessão."""
    from sh_placa.destino import SENHA_PADRAO_DA_IMAGEM

    s = area.capturar
    conexao_ssh = area.conexao.conexao_ssh
    original = conexao_ssh.senha
    conexao_ssh.senha = None
    try:
        s.conferir_antes()
        qtbot.waitUntil(lambda: area.conferencia.estado == "precisa_da_senha", timeout=ESPERA_MS)
        assert s.pedido_da_senha.isVisible() and "qual é a senha" in s.texto_da_senha.text()
        s.campo_da_senha.setText("errada")
        s._conferir_com_a_senha()
        qtbot.waitUntil(lambda: area.conferencia.estado in ("senha_recusada", "feita", "falhou"), timeout=ESPERA_MS)
        assert area.conferencia.estado == "senha_recusada" and "recusou" in s.texto_da_senha.text()
        s.campo_da_senha.setText(original or SENHA_PADRAO_DA_IMAGEM)
        s._conferir_com_a_senha()
        qtbot.waitUntil(lambda: area.conferencia.estado in ("senha_recusada", "feita", "falhou"), timeout=ESPERA_MS)
        assert area.conferencia.estado == "feita" and not s.pedido_da_senha.isVisible()
        assert area.saude.senha_do_sudo == (original or SENHA_PADRAO_DA_IMAGEM)
    finally:
        conexao_ssh.senha = original


def test_a_conferencia_some_com_a_placa(area, qtbot):
    area.capturar.conferir_antes()
    qtbot.waitUntil(lambda: area.conferencia.estado == "feita", timeout=ESPERA_MS)
    area.conexao.desconectar()
    qtbot.waitUntil(lambda: area.conexao.estado == "desconectada", timeout=ESPERA_MS)
    assert area.conferencia.resultado is None and not area.capturar.lista_da_conferencia.isVisible()
    assert not area.capturar.conferir.isEnabled() and "Conecte" in area.capturar.conferir.toolTip()


def test_o_firmware_de_antes_da_saida_continua_pede_a_atualizacao(area, qtbot):
    """A placa com o ``ler_adc`` de antes da F4.1 (como a de verdade, em 18/11/2026): a conferência não roda, e a
    seção diz o que fazer, sem perguntar a senha."""
    c = area.conexao
    sessao = c.sessoes
    c.trocar_cenario("firmware_antigo")
    qtbot.waitUntil(lambda: c.sessoes != sessao and c.estado == "conectada" and area.saude.saude is not None
                    and not area.saude.conferindo, timeout=ESPERA_MS)
    s = area.capturar
    qtbot.waitUntil(s.conferir.isEnabled, timeout=ESPERA_MS)
    s.conferir_antes()
    qtbot.waitUntil(lambda: area.conferencia.estado in ("feita", "falhou", "precisa_da_senha"), timeout=ESPERA_MS)
    assert area.conferencia.estado == "falhou" and area.conferencia.resultado is None
    assert "atualize o firmware da placa" in s.andamento.text() and s.andamento.isVisible()
    assert not s.pedido_da_senha.isVisible() and not s.lista_da_conferencia.isVisible()
