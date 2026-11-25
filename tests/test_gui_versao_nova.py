"""O aviso de versão nova: a consulta, o download conferido e o comando do instalador (``servicos/versao_nova.py``,
contra um servidor HTTP local no papel do GitHub: os testes nunca usam a internet), o cartão
(``componentes/versao_nova.py``) e a janela (consultar, pular, baixar e fechar para instalar)."""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from sh_analyzer_gui.servicos import versao_nova as vn

# ------------------------------------------------------------------ um GitHub local


class _Servidor:
    """Serve ``rotas`` (caminho → bytes, ou o status HTTP) e guarda os cabeçalhos dos pedidos."""

    def __init__(self):
        self.rotas: dict[str, bytes | int] = {}
        self.pedidos: list[dict[str, str]] = []
        servidor = self

        class Tratador(BaseHTTPRequestHandler):
            def do_GET(self):
                servidor.pedidos.append(dict(self.headers))
                corpo = servidor.rotas.get(self.path, 404)
                if isinstance(corpo, int):
                    self.send_error(corpo)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)

            def log_message(self, *_argumentos):
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def fechar(self):
        self.http.shutdown()
        self.http.server_close()


@pytest.fixture
def github():
    servidor = _Servidor()
    yield servidor
    servidor.fechar()


INSTALADOR = b"MZ" + bytes(range(256)) * 4000           # ~1 MB: vários blocos do download


def publicar(github, *, tag="v0.10", soma=None, draft=False):
    """Uma release com o instalador do Windows, o SHA256SUMS e as notas; devolve a URL da API."""
    nome = f"sh-analyzer-{tag}-windows-x64.exe"
    soma = soma or hashlib.sha256(INSTALADOR).hexdigest()
    github.rotas[f"/download/{nome}"] = INSTALADOR
    github.rotas["/download/SHA256SUMS"] = (f"{soma}  {nome}\n{'0' * 64}  sh-analyzer_0.10.0_amd64.deb\n").encode()
    github.rotas["/api/latest"] = json.dumps({
        "tag_name": tag, "draft": draft, "prerelease": False, "html_url": f"{github.url}/releases/{tag}",
        "body": "As novidades.",
        "assets": [{"name": nome, "browser_download_url": f"{github.url}/download/{nome}", "size": len(INSTALADOR)},
                   {"name": "SHA256SUMS", "browser_download_url": f"{github.url}/download/SHA256SUMS", "size": 1}],
    }).encode()
    return f"{github.url}/api/latest"


# ------------------------------------------------------------------ sem Qt


def test_as_versoes():
    assert vn.numeros("v0.9") == vn.numeros("0.9.0") == vn.numeros("0.9.0+git3.gabc") == (0, 9)
    assert vn.numeros("abc") is None
    assert vn.mais_nova("v0.10", "0.9.0") and vn.mais_nova("1.0", "0.9.9")
    assert not vn.mais_nova("v0.9", "0.9.0") and not vn.mais_nova("v0.9", "0.9.0+git12.gabc")
    assert not vn.mais_nova("v0.8", "0.9.0") and not vn.mais_nova("v0.10", "dev")


def test_como_foi_instalado(tmp_path):
    assert vn.como_foi_instalado(congelado=False) == "dev"
    pasta = tmp_path / "SH-Analyzer"
    pasta.mkdir()
    exe = pasta / "sh-analyzer-gui.exe"
    assert vn.como_foi_instalado(congelado=True, plataforma="win32", executavel=exe) == "pasta"
    (pasta / vn.DESINSTALADOR_DO_INNO).write_bytes(b"")
    assert vn.como_foi_instalado(congelado=True, plataforma="win32", executavel=exe) == "windows"
    lista = tmp_path / "sh-analyzer.list"
    no_opt = vn.PASTA_DO_APT / "sh-analyzer-gui"
    assert vn.como_foi_instalado(congelado=True, plataforma="linux", executavel=no_opt, lista_do_dpkg=lista) == "pasta"
    lista.write_text("/opt/sh-analyzer\n")
    assert vn.como_foi_instalado(congelado=True, plataforma="linux", executavel=no_opt, lista_do_dpkg=lista) == "apt"
    assert vn.como_foi_instalado(congelado=True, plataforma="linux", executavel=tmp_path / "x",
                                 lista_do_dpkg=lista) == "pasta"


def test_a_consulta(github):
    url = publicar(github)
    lancamento = vn.consultar("0.9.0", url)
    assert lancamento.versao == "0.10" and lancamento.notas == "As novidades."
    assert lancamento.instalador_do_windows.nome == "sh-analyzer-v0.10-windows-x64.exe"
    assert lancamento.somas.nome == "SHA256SUMS"
    assert github.pedidos[-1]["User-Agent"] == "SH-Analyzer/0.9.0"          # nada do usuário vai junto
    assert vn.consultar("0.10.0", url) is None                                # já é a última
    assert vn.consultar("0.9.0", publicar(github, draft=True)) is None
    github.rotas["/api/latest"] = 500
    with pytest.raises(OSError):
        vn.consultar("0.9.0", url)


def test_o_download_conferido(github, tmp_path):
    lancamento = vn.consultar("0.9.0", publicar(github))
    fracoes = []
    instalador = vn.baixar_instalador(lancamento, "0.9.0", fracoes.append, lambda: False, tmp_path)
    assert instalador.read_bytes() == INSTALADOR
    assert fracoes[-1] == 1.0 and fracoes == sorted(fracoes) and len(fracoes) > 2


def test_o_download_com_a_soma_errada_e_apagado(github, tmp_path):
    lancamento = vn.consultar("0.9.0", publicar(github, soma="f" * 64))
    with pytest.raises(vn.ErroDeAtualizacao, match="não confere"):
        vn.baixar_instalador(lancamento, "0.9.0", lambda _f: None, lambda: False, tmp_path)
    assert not list(tmp_path.iterdir())


def test_o_download_cancelado(github, tmp_path):
    lancamento = vn.consultar("0.9.0", publicar(github))
    with pytest.raises(InterruptedError):
        vn.baixar_instalador(lancamento, "0.9.0", lambda _f: None, lambda: True, tmp_path)
    assert not list(tmp_path.iterdir())


def test_sem_o_instalador_ou_sem_a_soma(github, tmp_path):
    lancamento = vn.consultar("0.9.0", publicar(github))
    sem_somas = vn.Lancamento(lancamento.versao, lancamento.pagina, "", lancamento.instalador_do_windows, None)
    with pytest.raises(vn.ErroDeAtualizacao, match="página"):
        vn.baixar_instalador(sem_somas, "0.9.0", lambda _f: None, lambda: False, tmp_path)
    github.rotas["/download/SHA256SUMS"] = b"0" * 64 + b"  outro.exe\n"
    with pytest.raises(vn.ErroDeAtualizacao, match="não tem a soma"):
        vn.baixar_instalador(lancamento, "0.9.0", lambda _f: None, lambda: False, tmp_path)


def test_a_soma_esperada():
    soma = "a" * 64
    assert vn.soma_esperada(f"{soma}  x.exe\n{'b' * 64} *y.exe\n", "x.exe") == soma
    assert vn.soma_esperada(f"{'b' * 64} *y.exe\n", "y.exe") == "b" * 64
    assert vn.soma_esperada("lixo\n", "x.exe") is None


def test_o_instalador_calado_reabre_o_aplicativo():
    comando = vn.comando_do_instalador(Path("C:/t/sh.exe"))
    assert comando[1:] == ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/REABRIR=1"]
    # O mesmo parâmetro que o instalador do Inno Setup lê para reabrir.
    iss = (Path(__file__).resolve().parents[1] / "empacotamento" / "sh-analyzer-gui.iss").read_text()
    assert "{param:REABRIR|0}" in iss


def test_uma_consulta_por_dia():
    assert vn.deve_consultar(None, 1000.0)
    assert not vn.deve_consultar(1000.0, 1000.0 + vn.INTERVALO_S - 1)
    assert vn.deve_consultar(1000.0, 1000.0 + vn.INTERVALO_S)
    assert vn.deve_consultar(5000.0, 1000.0)                                  # o relógio voltou


# ------------------------------------------------------------------ o cartão e a janela

LANCAMENTO = vn.Lancamento("0.10", "https://exemplo/releases/v0.10", "As novidades.",
                           vn.Arquivo("sh-analyzer-v0.10-windows-x64.exe", "https://exemplo/x.exe", 10),
                           vn.Arquivo("SHA256SUMS", "https://exemplo/SHA256SUMS", 1))


@pytest.fixture
def qt(qapp, config_limpa):
    pytest.importorskip("pytestqt")
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
