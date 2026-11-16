"""A seção Terminal da Aquisição (F3.8), com o servidor SSH do teste (um ``sh -i`` num PTY deste computador): a aba
que abre sozinha, o tamanho da tela que chega ao PTY, a gravação no arquivo do dia (um por aba), o atalho que escreve
sem apertar o Enter, a queda do cabo com a aba reabrindo sozinha, o shell que sai, a pergunta antes de fechar uma aba
com uma captura rodando e o terminal do sistema com o ``ssh`` pronto. Sem placa e sem tela."""

import re
import shutil
import subprocess
import sys

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("asyncssh")
pytest.importorskip("pyte")
if not sys.platform.startswith("linux"):
    pytest.skip("o servidor do teste usa o PTY e o sh deste computador", allow_module_level=True)

from dialogos_falsos import DialogosFalsos  # noqa: E402
from placas_de_teste import CofreFalso, Placas  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao import terminal as modulo  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.area import AreaDeAquisicao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.terminal import EMULADORES, terminal_do_sistema  # noqa: E402
from sh_analyzer_gui.servicos import conexao_da_placa as modulo_da_conexao  # noqa: E402
from sh_analyzer_gui.servicos.conexao_da_placa import ConexaoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.placa import ServicoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.saude_da_placa import SaudeDaPlaca  # noqa: E402
from sh_placa.descoberta import Descoberta, FonteSimulador  # noqa: E402
from sh_placa.destino import Destino  # noqa: E402

ESPERA_MS = 20_000


@pytest.fixture
def placas(tmp_path):
    p = Placas(tmp_path)
    yield p
    p.fechar()


@pytest.fixture
def abrir(qapp, config_limpa, qtbot, tmp_path, monkeypatch):
    """A área conectada ao servidor, na seção Terminal, com a primeira aba aberta e o prompt na tela."""
    monkeypatch.setenv("DADOS", str(tmp_path / "dados"))
    criar_aplicacao([], tema="escuro")
    abertas = []

    def _abrir(servidor, dialogos=None):
        servico = ServicoDaPlaca()
        conexao = ConexaoDaPlaca(servico, descoberta=Descoberta([FonteSimulador()]), pasta=tmp_path / "aplicativo",
                                 cofre=CofreFalso(**{f"debian@127.0.0.1:{servidor.porta}": servidor.senha}))
        programas = []
        area = AreaDeAquisicao(conexao, SaudeDaPlaca(conexao), (lambda: dialogos) if dialogos is not None else None,
                               abrir_url=lambda _url: None, executar_programa=lambda a: programas.append(a) or True)
        area.programas = programas
        area.resize(1300, 800)
        area.show()
        qtbot.waitExposed(area)
        abertas.append((area, conexao, servico))
        conexao.conectar(destino=Destino("127.0.0.1", servidor.porta))
        qtbot.waitUntil(lambda: conexao.estado == "confirmar_host", timeout=ESPERA_MS)
        conexao.confirmar_host(True)
        qtbot.waitUntil(lambda: conexao.estado == "conectada", timeout=ESPERA_MS)
        conexao.dispensar_primeira_conexao()
        if area._dialogo is not None:
            area._dialogo.done(0)
        area.mostrar_secao("terminal")
        qtbot.waitUntil(lambda: area.terminal.abas.count() == 1, timeout=ESPERA_MS)
        esperar(qtbot, aba(area), r"placa\$$")
        return area

    yield _abrir
    for area, conexao, servico in abertas:
        area.terminal.fechar_todas()
        conexao.encerrar()
        assert servico.encerrar()
        area.close()
        area.deleteLater()


def aba(area, i=None):
    abas = area.terminal.abas
    return abas.currentWidget() if i is None else abas.widget(i)


def texto(a) -> str:
    """Tudo o que a aba mostra (a rolagem e a tela), uma linha por linha."""
    t = a.tela
    t.interpretar_tudo()
    return "\n".join(t._texto(n)[0].rstrip() for n in range(t._primeira(), t.tela.guardadas + t.tela.lines))


def esperar(qtbot, a, padrao: str) -> re.Match:
    achou = []
    qtbot.waitUntil(lambda: bool(achou.append(re.search(padrao, texto(a), re.MULTILINE)) or achou[-1]),
                    timeout=ESPERA_MS)
    return achou[-1]


def digitar(qtbot, a, linha: str) -> None:
    qtbot.keyClicks(a.tela, linha)
    qtbot.keyClick(a.tela, Qt.Key.Key_Return)


def test_o_tamanho_da_tela_chega_ao_pty(qtbot, placas, abrir):
    area = abrir(placas.nova())
    a = aba(area)
    digitar(qtbot, a, "echo tamanho-1 $(stty size)")
    linhas, colunas = map(int, esperar(qtbot, a, r"^tamanho-1 (\d+) (\d+)$").groups())
    assert (colunas, linhas) == (a.tela.colunas, a.tela.linhas) and colunas > 80
    aberto = next(e.descricao for e in area.conexao.registro.entradas if e.descricao.startswith("terminal aberto"))
    assert f"{colunas}×{linhas}" in aberto                                  # o PTY já abriu no tamanho da tela
    area.resize(1000, 640)                                                  # a janela menor
    qtbot.waitUntil(lambda: a.tela.colunas < colunas)
    qtbot.wait(150)                                                         # o aviso do tamanho, depois do arrastar
    digitar(qtbot, a, "echo tamanho-2 $(stty size)")
    assert esperar(qtbot, a, r"^tamanho-2 (\d+) (\d+)$").groups() == (str(a.tela.linhas), str(a.tela.colunas))


def test_a_gravacao_de_cada_aba_na_pasta_do_dia(qtbot, placas, abrir):
    area = abrir(placas.nova())
    digitar(qtbot, aba(area), "echo gravado-$((2+3))")
    esperar(qtbot, aba(area), r"^gravado-5$")
    segunda = area.terminal.nova_aba()
    esperar(qtbot, segunda, r"placa\$$")
    digitar(qtbot, segunda, "echo segunda-$((1+1))")
    esperar(qtbot, segunda, r"^segunda-2$")
    dia = preferencias.pasta_da_sessao()
    primeira = (dia / "terminal_bbb.txt").read_bytes()
    assert b"gravado-5" in primeira and b"segunda-2" not in primeira
    assert primeira.startswith(b"\n--- terminal da placa debian@127.0.0.1")
    assert b"segunda-2" in (dia / "terminal_bbb_2.txt").read_bytes()
    assert area.terminal.abas.tabText(1) == "Terminal 2"
    assert any(e.descricao.startswith("terminal aberto") for e in area.conexao.registro.entradas)


def test_o_atalho_escreve_e_nao_aperta_o_enter(qtbot, placas, abrir, monkeypatch):
    area = abrir(placas.nova())
    a = aba(area)
    atalho = next(b for b in area.terminal.atalhos if b.comando.startswith("pgrep"))
    monkeypatch.setattr(atalho, "comando", "echo atalho-$((40+2))")
    atalho.click()
    esperar(qtbot, a, r"placa\$ echo atalho-\$\(\(40\+2\)\)$")              # escrito na linha do prompt...
    qtbot.wait(300)
    assert "atalho-42" not in texto(a)                                      # ...e não rodou
    assert area.focusWidget() is a.tela                                     # o Enter vai para o terminal
    qtbot.keyClick(a.tela, Qt.Key.Key_Return)
    esperar(qtbot, a, r"^atalho-42$")


def test_a_queda_do_cabo_e_a_aba_que_reabre_sozinha(qtbot, placas, abrir, monkeypatch):
    monkeypatch.setattr(modulo_da_conexao, "ESPERAS_DA_RECONEXAO_S", (0.2, 0.3, 0.5, 1, 1))
    servidor = placas.nova()
    area = abrir(servidor)
    a = aba(area)
    digitar(qtbot, a, "echo antes-da-queda")
    esperar(qtbot, a, r"^antes-da-queda$")
    sessao = a.sessao
    placas.laco.agendar(servidor.derrubar)                                  # o cabo que solta
    qtbot.waitUntil(lambda: a.sessao is not sessao and a.aberta, timeout=ESPERA_MS)
    esperar(qtbot, a, r"── reaberto às \d\d:\d\d:\d\d ──\n(.*\n)*placa\$$")
    assert "antes-da-queda" in texto(a) and area.terminal.abas.count() == 1
    digitar(qtbot, a, "echo depois-da-queda")
    esperar(qtbot, a, r"^depois-da-queda$")
    descricoes = [e.descricao for e in area.conexao.registro.entradas]
    assert "terminal fechado (a conexão caiu antes do fim do shell)" in descricoes


def test_o_shell_que_sai_espera_o_reabrir(qtbot, placas, abrir):
    area = abrir(placas.nova())
    a = aba(area)
    digitar(qtbot, a, "exit 3")
    qtbot.waitUntil(lambda: a.estado == "terminou", timeout=ESPERA_MS)
    assert a.codigo == 3 and a.aviso.isVisible() and "código 3" in a.texto_do_aviso.text()
    assert not any(b.isEnabled() for b in area.terminal.atalhos)            # nenhuma aba aberta para escrever
    a.reabrir.click()
    esperar(qtbot, a, r"reaberto às .*\n(.*\n)*placa\$$")
    assert a.aberta and not a.aviso.isVisible()


def test_fechar_a_aba_com_uma_captura_rodando_pergunta(qtbot, placas, abrir, tmp_path):
    dialogos = DialogosFalsos(None, "fechar")
    area = abrir(placas.nova(), dialogos)
    area.terminal.pedir_para_fechar(aba(area))                              # nada rodando: fecha sem perguntar
    qtbot.waitUntil(lambda: area.terminal.abas.count() == 0, timeout=ESPERA_MS)
    assert dialogos.perguntas == []
    a = area.terminal.nova_aba()
    esperar(qtbot, a, r"placa\$$")
    ler_adc = tmp_path / "ler_adc"
    shutil.copy(shutil.which("sleep"), ler_adc)
    rodando = subprocess.Popen([str(ler_adc), "30"])                       # a captura "na placa" (aqui)
    try:
        area.terminal.pedir_para_fechar(a)
        qtbot.waitUntil(lambda: dialogos.perguntas == ["Fechar o terminal"], timeout=ESPERA_MS)
        assert area.terminal.abas.count() == 1                              # "Cancelar": a aba fica
        area.terminal.pedir_para_fechar(a)
        qtbot.waitUntil(lambda: area.terminal.abas.count() == 0, timeout=ESPERA_MS)
    finally:
        rodando.kill()
        rodando.wait()
    descricoes = [e.descricao for e in area.conexao.registro.entradas]
    assert "terminal fechado na interface" in descricoes


def test_abrir_no_terminal_do_sistema(qtbot, placas, abrir, monkeypatch):
    servidor = placas.nova()
    area = abrir(servidor)
    monkeypatch.setattr(modulo, "terminal_do_sistema", lambda ssh: ["/usr/bin/cosmic-term", "--", *ssh])
    area.terminal.do_sistema.click()
    (programa,) = area.programas
    chave = area.conexao.conexao_ssh.chave.caminho
    assert programa[:3] == ["/usr/bin/cosmic-term", "--", "ssh"]
    assert programa[-3:] == ["-p", str(servidor.porta), "debian@127.0.0.1"]
    assert ("-i" in programa) == chave.exists()
    assert f"UserKnownHostsFile={area.conexao.conexao_ssh.hosts.arquivo}" in programa

    monkeypatch.setattr(modulo, "terminal_do_sistema", lambda ssh: None)    # nenhum terminal conhecido
    area.terminal.do_sistema.click()
    assert QGuiApplication.clipboard().text().startswith("ssh ") and len(area.programas) == 1


def test_os_terminais_de_cada_sistema(tmp_path):
    ssh = ["ssh", "-p", "2222", "debian@192.168.6.2"]

    def so(*nomes):
        return lambda nome: f"/usr/bin/{nome}" if nome in nomes else None

    assert terminal_do_sistema(ssh, "linux", so("xterm", "konsole"), {"XDG_CURRENT_DESKTOP": "KDE"}) == \
        ["/usr/bin/konsole", "-e", *ssh]
    assert terminal_do_sistema(ssh, "linux", so("gnome-terminal", "xterm"), {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}) \
        == ["/usr/bin/gnome-terminal", "--", *ssh]
    assert terminal_do_sistema(ssh, "linux", so("xterm"), {}) == ["/usr/bin/xterm", "-e", *ssh]
    assert terminal_do_sistema(ssh, "linux", so(), {}) is None
    alternativa = tmp_path / "x-terminal-emulator"                         # o do Debian: o programa que ele é
    alternativa.symlink_to(tmp_path / "xfce4-terminal.wrapper")
    procurar = {"x-terminal-emulator": str(alternativa), "xfce4-terminal": "/usr/bin/xfce4-terminal",
                "xterm": "/usr/bin/xterm"}.get
    assert terminal_do_sistema(ssh, "linux", procurar, {}) == ["/usr/bin/xfce4-terminal", "-x", *ssh]
    assert terminal_do_sistema(ssh, "win32", so("wt"), {})[:4] == ["/usr/bin/wt", "new-tab", "--title", "BeagleBone"]
    assert terminal_do_sistema(ssh, "win32", so(), {"COMSPEC": "cmd.exe"}) == ["cmd.exe", "/c", "start", "", *ssh]
    mac = terminal_do_sistema(ssh, "darwin", so(), {})
    assert mac[0] == "osascript" and 'do script "ssh -p 2222 debian@192.168.6.2"' in mac[2]
    assert set(EMULADORES) >= {"cosmic-term", "gnome-terminal", "konsole"}
