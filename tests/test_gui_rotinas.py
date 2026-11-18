"""A seção Rotinas da Aquisição (a F4.6): a lista dos modos, o formulário preenchido pelo pedido da Capturar, a linha
de comando, os valores que não servem, e, com o servidor SSH do teste (um ``sh -i`` num PTY deste computador, com o
``coletar.sh`` do repositório na pasta do firmware): a rotina com ``--simular`` numa aba nova do Terminal, com o
plano na tela, a entrada no caderno e a ajuda do modo lida da placa. Sem placa e sem tela."""

import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("asyncssh")
pytest.importorskip("pyte")
if not sys.platform.startswith("linux"):
    pytest.skip("o servidor do teste usa o PTY e o sh deste computador", allow_module_level=True)

from placas_de_teste import CofreFalso, Placas  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.area import AreaDeAquisicao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.rotinas import Rotinas  # noqa: E402
from sh_analyzer_gui.servicos.conexao_da_placa import ConexaoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.placa import ServicoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.saude_da_placa import SaudeDaPlaca  # noqa: E402
from sh_placa import rotinas as rt  # noqa: E402
from sh_placa.descoberta import Descoberta, FonteSimulador  # noqa: E402
from sh_placa.destino import Destino  # noqa: E402
from sh_placa.pedido import Canal, PedidoDeCaptura  # noqa: E402
from test_gui_terminal_da_placa import aba, esperar, texto  # noqa: E402

ESPERA_MS = 15_000
RAIZ = Path(__file__).resolve().parents[1]
PEDIDO = PedidoDeCaptura((Canal(1, "corrente", sonda="sct013_100a_sn001", faixa_v=5.12), Canal(3)))


@pytest.fixture
def secao(qapp, config_limpa, qtbot, tmp_path):
    """A seção sozinha, sem placa conectada."""
    criar_aplicacao([], tema="escuro")
    servico = ServicoDaPlaca()
    conexao = ConexaoDaPlaca(servico, descoberta=Descoberta([]), pasta=tmp_path / "aplicativo", cofre=CofreFalso())
    s = Rotinas(conexao, pedido_atual=lambda: PEDIDO, rodar_no_terminal=lambda _linha, _rotulo: True)
    qtbot.addWidget(s)
    s.resize(1100, 800)
    s.show()
    yield s
    conexao.encerrar()
    assert servico.encerrar()


def test_o_formulario_vem_do_pedido_e_monta_a_linha(secao):
    s = secao
    assert s.lista.count() == len(rt.ROTINAS) and s.rotina.modo == "conferir"
    s.escolher("calibrar")
    f = s.formulario
    assert f.valores()["--canal"] == "1" and f.valores()["--grandeza"] == "corrente"
    assert f.valores()["--sonda"] == "sct013_100a_sn001"
    f.campos["--segundos"].setText("5")
    f.campos["--referencia"].setChecked(True)
    esperado = ("cd ~/firmware && ./coletar.sh calibrar --grandeza corrente --canal 1 --sonda sct013_100a_sn001 "
                "--referencia --segundos 5")
    assert s.linha.rotulo.text() == esperado
    assert s.simular.isVisibleTo(s) and s.continuar.isVisibleTo(s)
    assert not s.rodar.isEnabled() and "Conecte uma placa" in s.estado.text()

    f.outras.setText("--espiras '3")                              # as aspas abertas
    assert s.erro.isVisibleTo(s) and "aspas" in s.erro.text()
    f.outras.setText("--espiras 3")
    assert not s.erro.isVisibleTo(s) and s.linha.rotulo.text() == esperado + " --espiras 3"

    s.escolher("sonda")                                           # outro modo, e a volta: os valores ficam
    assert not s.simular.isVisibleTo(s) and s.formulario.valores()["--canal-sonda"] == "1"
    s.escolher("calibrar")
    assert s.linha.rotulo.text() == esperado + " --espiras 3"
    f.campos["--canal"].setText("4")
    s.preencher_do_pedido()                                       # a bancada de novo pelo pedido; o resto fica
    assert f.valores()["--canal"] == "1" and f.valores()["--segundos"] == "5"


@pytest.fixture
def placas(tmp_path):
    p = Placas(tmp_path)
    yield p
    p.fechar()


@pytest.fixture
def area(qapp, config_limpa, qtbot, tmp_path, monkeypatch, placas):
    """A área conectada ao servidor do teste, com o ``coletar.sh`` do repositório na pasta do firmware."""
    monkeypatch.setenv("DADOS", str(tmp_path / "dados"))
    criar_aplicacao([], tema="escuro")
    servidor = placas.nova()
    firmware = servidor.home / "firmware"
    shutil.copy2(RAIZ / "firmware" / "coletar.sh", firmware / "coletar.sh")
    shutil.copytree(RAIZ / "firmware" / "coleta", firmware / "coleta")
    servico = ServicoDaPlaca()
    conexao = ConexaoDaPlaca(servico, descoberta=Descoberta([FonteSimulador()]), pasta=tmp_path / "aplicativo",
                             cofre=CofreFalso(**{f"debian@127.0.0.1:{servidor.porta}": servidor.senha}))
    a = AreaDeAquisicao(conexao, SaudeDaPlaca(conexao), abrir_url=lambda _url: None)
    a.resize(1300, 800)
    a.show()
    qtbot.waitExposed(a)
    conexao.conectar(destino=Destino("127.0.0.1", servidor.porta))
    qtbot.waitUntil(lambda: conexao.estado == "confirmar_host", timeout=ESPERA_MS)
    conexao.confirmar_host(True)
    qtbot.waitUntil(lambda: conexao.estado == "conectada", timeout=ESPERA_MS)
    conexao.dispensar_primeira_conexao()
    if a._dialogo is not None:
        a._dialogo.done(0)
    a.mostrar_secao("rotinas")
    yield a
    a.terminal.fechar_todas()
    conexao.encerrar()
    assert servico.encerrar()
    a.close()
    a.deleteLater()


def test_a_rotina_roda_numa_aba_nova_e_vai_para_o_caderno(area, qtbot):
    s = area.rotinas
    s.escolher("ruido")
    s.formulario.campos["--canais"].setText("1")
    assert s.simular.isEnabled() and "aba nova do Terminal" in s.estado.text()
    s.simular.click()
    assert area.secao == "terminal" and area.terminal.abas.count() == 1   # só a da rotina: a automática não abre
    a = aba(area)
    assert a.titulo == "ruido"
    esperar(qtbot, a, r"--simular: nada foi capturado")
    assert "cd ~/firmware && ./coletar.sh ruido --canais 1 --simular" in texto(a)
    (entrada,) = area.caderno.entradas
    assert "Piso de ruído" in entrada.texto and "`cd ~/firmware && ./coletar.sh ruido --canais 1 --simular`" in \
        entrada.texto

    area.mostrar_secao("rotinas")                                 # a ajuda do modo, a do coletar.sh da placa
    s.ver_ajuda.setChecked(True)
    qtbot.waitUntil(lambda: "Uso: ./coletar.sh ruido" in s.ajuda.toPlainText(), timeout=ESPERA_MS)
    s.escolher("teto")
    qtbot.waitUntil(lambda: "Uso: ./coletar.sh teto" in s.ajuda.toPlainText(), timeout=ESPERA_MS)
