"""O resgate pela serial (a F6.8), sem tela: a porta da placa achada (o gadget), o console aberto num
pseudoterminal no lugar dela (o login que chega, o que se digita e os atalhos indo para o outro lado), a porta que cai,
a porta sem permissão (o porquê e o comando do grupo, sem botão de abrir), o caminho pelo cartão microSD e o caminho
na Manutenção sem placa."""

import os
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("serial")
if not sys.platform.startswith("linux"):
    pytest.skip("o pseudoterminal no lugar da porta serial", allow_module_level=True)

import pty  # noqa: E402

import test_gui_simulador  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.manutencao.resgate import PaginaDoResgate  # noqa: E402
from sh_placa import console_serial  # noqa: E402

abrir = test_gui_simulador.abrir        # a fixture que conecta ao simulador


def porta_falsa(caminho, *, da_placa=True):
    return SimpleNamespace(device=caminho, vid=0x1D6B if da_placa else 0x0403, pid=0x0104 if da_placa else 0x6001,
                           product="BeagleBoneBlack" if da_placa else "FT232R", serial_number="2017BBBK382A",
                           description="cabo serial")


def ler_tudo(fd, qtbot, contem: bytes, tempo_ms=5000) -> bytes:
    lido = b""

    def chegou():
        nonlocal lido
        try:
            lido += os.read(fd, 4096)
        except BlockingIOError:
            pass
        return contem in lido

    qtbot.waitUntil(chegou, timeout=tempo_ms)
    return lido


@pytest.fixture
def pseudoterminal():
    mestre, escravo = pty.openpty()
    os.set_blocking(mestre, False)
    yield mestre, os.ttyname(escravo)
    for fd in (mestre, escravo):
        try:
            os.close(fd)
        except OSError:
            pass


def test_o_console_serial_num_pseudoterminal(qtbot, qapp, config_limpa, pseudoterminal):
    criar_aplicacao([], tema="escuro")
    mestre, caminho = pseudoterminal
    pagina = PaginaDoResgate(listar_portas=lambda: console_serial.portas(lambda: [porta_falsa(caminho)]))
    qtbot.addWidget(pagina)
    pagina.resize(1200, 800)
    pagina.show()
    assert pagina.escolha.currentText().startswith("BeagleBone Black") and pagina.abrir.isEnabled()
    assert not pagina.permissao.isVisible()
    assert pagina.pelo_cartao_sd.isVisible() and "/dev/mmcblk1p1" in pagina.pelo_cartao_sd.text()
    assert pagina.abrir_o_console() and pagina.fechar.isVisible() and not pagina.escolha.isEnabled()
    assert not pagina.pelo_cartao_sd.isVisible()                      # o caminho do cartão é para sem a serial

    os.write(mestre, b"\r\nDebian GNU/Linux 10 beaglebone ttyGS0\r\n\r\nbeaglebone login: ")
    qtbot.waitUntil(lambda: any("beaglebone login:" in linha for linha in pagina.tela.linhas_visiveis()),
                    timeout=5000)
    pagina.tela.digitou.emit(b"debian\r")
    assert b"debian\r" in ler_tudo(mestre, qtbot, b"debian\r")
    pagina.atalhos[0].click()                                         # "As redes": o Enter é de quem lê
    assert ler_tudo(mestre, qtbot, b"ip -br addr").endswith(b"ip -br addr")

    pagina.fechar.click()
    assert pagina.console is None and pagina.leitor is None and pagina.abrir.isVisible()
    assert pagina.abrir_o_console()                                   # de novo, e a página some: a porta fecha
    pagina.hide()
    assert pagina.console is None


def test_a_porta_sem_permissao_diz_o_que_fazer(qtbot, qapp, config_limpa, tmp_path):
    criar_aplicacao([], tema="escuro")
    trancada = tmp_path / "ttyACM9"
    trancada.write_text("")
    trancada.chmod(0)
    if os.access(trancada, os.R_OK | os.W_OK):
        pytest.skip("rodando como root: nada é trancado")
    pagina = PaginaDoResgate(listar_portas=lambda: console_serial.portas(lambda: [porta_falsa(str(trancada))]))
    qtbot.addWidget(pagina)
    pagina.show()
    assert "sem permissão" in pagina.escolha.currentText() and not pagina.abrir.isEnabled()
    assert pagina.permissao.isVisible() and pagina.comando.text().startswith("sudo usermod -aG ")
    assert "saia da sessão" in pagina.porque.text()


def test_o_resgate_na_manutencao_sem_placa(qtbot, abrir):
    area = abrir("normal")
    m = area.manutencao
    area.conexao.desconectar()
    qtbot.waitUntil(lambda: area.conexao.estado == "desconectada", timeout=10_000)
    area.mostrar_secao("manutencao")
    assert m.estados.currentIndex() == 0 and m.abrir_o_resgate.isVisible()
    m.abrir_o_resgate.click()
    assert m.estados.currentWidget() is m.resgate and m.resgate.isVisible()
    m.resgate.voltar_.click()
    assert m.estados.currentIndex() == 0
