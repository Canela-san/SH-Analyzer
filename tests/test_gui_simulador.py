"""O simulador na tela (F3.9): cada cenário do plano na visão geral e no diagnóstico, o cenário escolhido pela interface
(e lembrado), o relógio errado acertado pelo "Acertar…", e a conexão que cai no meio de uma transferência, com a
retomada sozinha quando ela volta. O simulador de verdade (por SSH, neste computador), sem placa e sem tela."""

import time

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("asyncssh")

from placas_de_teste import CofreFalso  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.area import AreaDeAquisicao  # noqa: E402
from sh_analyzer_gui.servicos.conexao_da_placa import ConexaoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.placa import ServicoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.saude_da_placa import SaudeDaPlaca  # noqa: E402
from sh_placa import simulador  # noqa: E402
from sh_placa.capturas_simuladas import Sistema, gravar_captura  # noqa: E402
from sh_placa.descoberta import Descoberta, FonteSimulador  # noqa: E402

ESPERA_MS = 20_000


@pytest.fixture
def abrir(qapp, config_limpa, qtbot, tmp_path, monkeypatch):
    """A área à vista, só com o simulador na lista; ``abrir(cenario)`` conecta nele e espera a saúde e as capturas."""
    monkeypatch.setenv("DADOS", str(tmp_path / "dados"))
    criar_aplicacao([], tema="escuro")
    abertas = []

    def _abrir(cenario=None):
        servico = ServicoDaPlaca()
        conexao = ConexaoDaPlaca(servico, descoberta=Descoberta([FonteSimulador()]), pasta=tmp_path / "aplicativo",
                                 cofre=CofreFalso())
        saude = SaudeDaPlaca(conexao)
        area = AreaDeAquisicao(conexao, saude)
        area.resize(1440, 860)
        area.show()
        qtbot.waitExposed(area)
        abertas.append((area, conexao, servico))
        qtbot.waitUntil(lambda: len(conexao.placas) == 1, timeout=ESPERA_MS)
        conexao.conectar(conexao.placas[0], cenario=cenario)
        esperar_a_placa(qtbot, area)
        return area

    yield _abrir
    for area, conexao, servico in abertas:
        area.close()
        conexao.encerrar()
        assert servico.encerrar()
        area.deleteLater()


def esperar_a_placa(qtbot, area):
    c, s = area.conexao, area.saude
    qtbot.waitUntil(lambda: c.estado == "conectada" and s.saude is not None and s.capturas is not None
                    and not s.conferindo, timeout=ESPERA_MS)


def niveis(area) -> dict[str, str]:
    area.mostrar_secao("diagnostico")
    return {chave: cartao.item.nivel for chave, cartao in area.diagnostico.cartoes.items()}


@pytest.mark.parametrize("cenario", ["normal", "adc_mudo", "disco_cheio", "conexao_instavel", "firmware_antigo",
                                     "relogio_errado"])
def test_cada_cenario_na_visao_geral_e_no_diagnostico(qtbot, abrir, cenario):
    area = abrir(cenario)
    v = area.visao_geral
    vistos = niveis(area)
    problemas = {k: n for k, n in vistos.items() if n in ("aviso", "erro")}
    assert vistos["conexao"] == "ok" and v.cenario.currentData() == cenario
    assert area.lateral.cartao.linhas[0].text() == simulador.CENARIOS[cenario].titulo
    assert v.aquisicao.valor.text() == ("ADC mudo" if cenario == "adc_mudo" else "Com sinal")
    if cenario in ("normal", "conexao_instavel"):
        assert problemas == {} and "Pronta para capturar" in area.diagnostico.subtitulo.text()
        assert "firmware v0.8.0-simulador (o deste aplicativo)" in v.subtitulo.text()
        assert v.cartao.valor.text().endswith("GiB") and v.relogio.valor.text().endswith(" s")
    elif cenario == "adc_mudo":
        assert problemas == {"aquisicao": "aviso"} and v.aquisicao.valor.property("nivel") == "aviso"
        assert v.linhas["aquisicao"].item.nivel == "aviso"                       # e na saúde resumida
    elif cenario == "disco_cheio":
        assert problemas == {"disco": "erro"} and v.cartao.valor.text() == "56 MiB"
        assert "Não está pronta para capturar" in area.diagnostico.subtitulo.text()
    elif cenario == "firmware_antigo":
        assert problemas == {"firmware": "aviso"}
        assert "firmware v0.7.0 (o deste aplicativo é v0.8.0-simulador)" in v.subtitulo.text()
    elif cenario == "relogio_errado":
        assert problemas == {"relogio": "aviso"} and v.relogio.valor.text() == "−2 dias e 5 h"
        assert v.relogio.detalhe.text().startswith("atrasado · sem NTP")
        assert v.linhas["relogio"].acao is not None                               # o "Acertar…"


def test_o_cenario_escolhido_pela_interface_e_lembrado(qtbot, abrir):
    area = abrir()
    c, v = area.conexao, area.visao_geral
    assert c.cenario == "normal" and v.cenario.isVisible() and v.rotulo_do_cenario.isVisible()
    antes = c._sessao.simulador.pasta
    v.cenario.setCurrentIndex(v.cenario.findData("disco_cheio"))
    v.cenario.activated.emit(v.cenario.currentIndex())                         # como o clique na lista
    assert c.estado == "conectando" and c.cenario == "disco_cheio"
    esperar_a_placa(qtbot, area)
    assert c._sessao.simulador.pasta != antes and preferencias.cenario_do_simulador() == "disco_cheio"
    qtbot.waitUntil(lambda: not antes.exists(), timeout=ESPERA_MS)               # a placa de antes foi apagada
    assert niveis(area)["disco"] == "erro"
    c.desconectar()
    c.conectar(c.placas[0])                                                     # o último cenário escolhido
    esperar_a_placa(qtbot, area)
    assert c.cenario == "disco_cheio" and area.lateral.cartao.linhas[0].text() == "Cartão cheio"
    menu = area.lateral.lista.menu_da_placa(c.placas[0])                        # e no menu da lista
    (submenu,) = [a.menu() for a in menu.actions() if a.menu() is not None]
    marcados = [a.text() for a in submenu.actions() if a.isChecked()]
    assert marcados == ["Cartão cheio"] and len([a for a in submenu.actions() if a.isSeparator()]) == 1
    preferencias.mudar_cenario_do_simulador("de_uma_versao_antiga")
    assert preferencias.cenario_do_simulador() == "normal"


def test_o_relogio_errado_acertado_pelo_computador(qtbot, abrir):
    """O sudo da placa simulada pede a senha da imagem, que a sessão conhece: o "Acertar…" não pergunta, e a placa
    fica com a hora deste computador (o relógio daqui não é tocado)."""
    area = abrir("relogio_errado")
    dialogo = area.corrigir("relogio")
    assert not dialogo.caixa_da_senha.isVisible()
    dialogo.confirmar.click()
    qtbot.waitUntil(lambda: not dialogo.isVisible(), timeout=ESPERA_MS)
    qtbot.waitUntil(lambda: area.saude.relogio_acertado is not None and not area.saude.conferindo, timeout=ESPERA_MS)
    assert abs(area.saude.saude.relogio.diferenca_s()) < 1.0
    assert "acertado pelo computador às " in area.visao_geral.relogio.detalhe.text()
    assert niveis(area)["relogio"] in ("ok", "info")


def test_a_conexao_que_cai_no_meio_da_transferencia_e_a_retomada(qtbot, abrir):
    """No cenário da conexão que cai: a transferência é cortada no meio (o item fica interrompido), a conexão volta
    sozinha, e a fila continua do ponto em que parou, até a cópia conferida (o CRC das amostras)."""
    area = abrir("conexao_instavel")
    c, t = area.conexao, area.transferencias
    servidor = c._sessao.simulador
    grande = servidor.home / "firmware" / "rede_longa.bin"                     # ~2 MiB: várias leituras do SFTP
    gravar_captura(grande, inicio=time.time() - 30, blocos=4, sistema=Sistema("k", "s", "p"),
                   amostras_por_bloco=1 << 18)
    area.saude.conferir()
    qtbot.waitUntil(lambda: not area.saude.conferindo and any(x.arquivo == "rede_longa.bin"
                                                               for x in area.saude.capturas.capturas),
                    timeout=ESPERA_MS)
    estados = []
    t.mudou.connect(lambda: estados.extend(i.estado for i in t.itens if i.captura.arquivo == "rede_longa.bin"))
    t.transferir([x for x in area.saude.capturas.capturas if x.arquivo == "rede_longa.bin"])
    qtbot.waitUntil(lambda: (i := next((i for i in t.itens if i.captura.arquivo == "rede_longa.bin"), None))
                    is not None and i.estado in ("conferida", "corrompida", "falhou"), timeout=ESPERA_MS * 2)
    (item,) = [i for i in t.itens if i.captura.arquivo == "rede_longa.bin"]
    assert (item.estado, item.como) == ("conferida", "crc32")
    assert item.local.read_bytes() == grande.read_bytes()
    assert "interrompida" in estados and c.quedas >= 1 and "caiu" in area.lateral.cartao.linhas[1].text()
