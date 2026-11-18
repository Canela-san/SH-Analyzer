"""A captura na tela (F4.4): o botão Capturar da seção, o cockpit (o tempo, a vazão, a integridade, o sinal e o
espectro ao vivo, a saída do ``ler_adc``), o Parar, a queda (no computador, fechada aqui; no cartão, a captura segue
e o acompanhamento volta), a transferência no fim, a senha perguntada, a captura que ficou pela metade e o fechar da
janela no meio. Na placa simulada (por SSH, neste computador), sem placa e sem tela."""

from __future__ import annotations

from collections import deque

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("asyncssh")

from dialogos_falsos import DialogosFalsos  # noqa: E402
from placas_de_teste import CofreFalso  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.area import AreaDeAquisicao  # noqa: E402
from sh_analyzer_gui.servicos.ao_vivo import calcular_quadro  # noqa: E402
from sh_analyzer_gui.servicos.captura_da_placa import arquivo_livre  # noqa: E402
from sh_analyzer_gui.servicos.conexao_da_placa import ConexaoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.conferencia_da_placa import ConferenciaDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.placa import ServicoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.saude_da_placa import SaudeDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.transferencias import TransferenciasDaPlaca  # noqa: E402
from sh_placa import capturas_simuladas  # noqa: E402
from sh_placa.descoberta import Descoberta, FonteSimulador  # noqa: E402
from sh_placa.pedido import Canal, PedidoDeCaptura  # noqa: E402
from supraharmonicos import api  # noqa: E402

ESPERA_MS = 40_000
SONDAS = __import__("pathlib").Path(__file__).resolve().parents[1] / "scripts" / "sondas"
REDE = (Canal(0, "corrente", ganho=19.65), Canal(1, ganho=19.357))


class Bancada:
    """A área de Aquisição conectada à placa simulada, com o que ela pede à janela anotado aqui."""

    def __init__(self, tmp_path, qtbot):
        criar_aplicacao([], tema="escuro")
        self.servico = ServicoDaPlaca()
        self.conexao = ConexaoDaPlaca(self.servico, descoberta=Descoberta([FonteSimulador()]),
                                      pasta=tmp_path / "aplicativo", cofre=CofreFalso())
        self.saude = SaudeDaPlaca(self.conexao)
        self.transferencias = TransferenciasDaPlaca(self.conexao, self.saude, indice=tmp_path / "copias.json")
        self.transferencias.destino = tmp_path / "trazidas"
        self.sessao = tmp_path / "sessao"
        self.no_projeto, self.na_analise, self.urls = [], [], []
        self.dialogos = DialogosFalsos()
        self.area = AreaDeAquisicao(
            self.conexao, self.saude, lambda: self.dialogos, self.transferencias,
            conferencia=ConferenciaDaPlaca(self.conexao, self.saude, pasta=tmp_path / "conferencias"),
            opcoes_da_captura={"pasta_das_sondas": lambda: SONDAS, "pasta_do_destino": lambda: self.sessao,
                               "lembrar": False},
            abrir_no_projeto=self.no_projeto.extend, mostrar_na_analise=self.na_analise.extend,
            abrir_url=self.urls.append)
        self.area.resize(1440, 900)
        self.area.show()
        qtbot.waitExposed(self.area)
        qtbot.waitUntil(lambda: len(self.conexao.placas) == 1, timeout=ESPERA_MS)
        self.conexao.conectar(self.conexao.placas[0])
        qtbot.waitUntil(lambda: self.conexao.estado == "conectada" and self.saude.saude is not None
                        and self.saude.capturas is not None and not self.saude.conferindo, timeout=ESPERA_MS)
        self.area.mostrar_secao("capturar")
        self.secao = self.area.capturar
        self.captura = self.area.captura

    def derrubar(self) -> None:
        """O cabo que solta: todas as conexões com a placa simulada caem (no laço dela)."""
        simulador = self.conexao._sessao.simulador
        assert self.servico.laco.agendar(simulador.derrubar)

    def fechar(self) -> None:
        self.area.close()
        self.conexao.encerrar()
        assert self.servico.encerrar()
        self.area.deleteLater()      # sem isso, cada teste deixava uma Aquisição inteira viva (~1 000 widgets)


@pytest.fixture
def bancada(qapp, config_limpa, qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("DADOS", str(tmp_path / "dados"))
    b = Bancada(tmp_path, qtbot)
    yield b
    b.fechar()


def test_a_captura_no_computador_mostra_o_ao_vivo_e_entra_no_projeto(bancada, qtbot):
    """Dois blocos de V e I direto no computador: o cockpit no lugar do pedido, o formulário travado, o sinal dos
    últimos 50 ms e o espectro de cada canal a cada bloco, e no fim o CRC conferido e a captura no projeto."""
    b = bancada
    s, c = b.secao, b.captura
    s.formulario.definir_pedido(PedidoDeCaptura(REDE, 400_000, blocos=2, titulo="Rede de casa"))
    assert s.capturar.isEnabled()
    qtbot.mouseClick(s.capturar, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: c.estado == "capturando", timeout=ESPERA_MS)
    assert s.paginas.currentWidget() is s.cockpit and not s.formulario.isEnabled()
    assert not s.conferir.isEnabled() and s.cockpit.barra.estado.text() == "Gravando"
    assert c.arquivo.parent == b.sessao and c.arquivo.name.startswith("rede_de_casa_")
    qtbot.waitUntil(lambda: s.ao_vivo.quadro is not None, timeout=ESPERA_MS)
    quadro = s.ao_vivo.quadro
    assert [canal.numero for canal in quadro.canais] == [0, 1]
    corrente, tensao = quadro.canais
    # 50 ms a 200 kS/s por canal, ou o bloco inteiro, se ele é menor (os blocos dos testes, BLOCO_DAS_CAPTURAS)
    n = min(10_000, capturas_simuladas.BLOCO_DAS_CAPTURAS // 2)
    assert len(tensao.sinal) == n and tensao.tempo_s[-1] == 0.0
    assert (corrente.unidade, tensao.unidade) == ("A", "V")
    assert np.max(np.abs(tensao.sinal)) == pytest.approx(127 * 2 ** 0.5, rel=0.15)    # a tomada da placa simulada
    assert len(s.cockpit.sinal.curva(1).getData()[0]) == n
    assert s.cockpit.espectro.curva.getData()[0] is not None and s.cockpit.espectro.numero == 0
    qtbot.waitUntil(lambda: c.estado == "feita", timeout=ESPERA_MS)
    f = c.fim
    assert (f.blocos, f.motivo, f.caiu, f.crc_confere, f.parada_pedida) == (2, "ok", False, True, False)
    assert s.cockpit.fim.isVisible() and s.cockpit.fim.titulo.text().startswith("Captura concluída")
    textos = s.cockpit.fim.lista.textos
    assert any("O CRC das amostras confere" in t for t in textos)
    assert any(t.startswith("Integridade: nenhuma amostra atrasada") for t in textos)
    assert b.no_projeto == [c.arquivo] and c.arquivo.exists()
    assert s.formulario.isEnabled() and s.conferir.isEnabled()
    assert any("Captura concluída" in linha for linha in c.linhas)
    qtbot.mouseClick(s.cockpit.fim.abrir, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(s.cockpit.fim.pasta, Qt.MouseButton.LeftButton)
    assert b.na_analise == [c.arquivo] and b.urls[0].toLocalFile() == str(b.sessao)
    # O caderno da sessão (a F4.5): o começo, com o pedido e o comando, e o fim, com o resumo da tela.
    assert b.area.caderno.caminho == b.sessao / "anotacoes.md"
    inicio, fim = [e.texto for e in b.area.caderno.entradas if c.nome in e.texto]
    assert inicio.startswith(f"Captura `{c.nome}` (“Rede de casa”) iniciada: 2 canais · 400 kS/s")
    assert "direto no computador." in inicio and inicio.split("\n")[1].startswith("`sudo ./ler_adc 400000 0,1 ")
    assert fim.startswith("Captura concluída: ") and f"(`{c.nome}`)." in fim
    assert "\n- ✓ O CRC das amostras confere com o do ler_adc" in fim and "\n- ✓ Integridade: nenhuma" in fim
    qtbot.mouseClick(s.cockpit.fim.nova, Qt.MouseButton.LeftButton)
    assert c.estado is None and s.paginas.currentWidget() is s.pagina_do_pedido


def test_parar_fecha_a_captura_no_ultimo_bloco(bancada, qtbot):
    b = bancada
    s, c = b.secao, b.captura
    s.formulario.definir_pedido(PedidoDeCaptura((Canal(1),), 400_000, blocos=0))
    s.capturar_agora()
    qtbot.waitUntil(lambda: c.progresso is not None and c.progresso.blocos >= 1, timeout=ESPERA_MS)
    assert s.cockpit.barra.parar.isEnabled() and s.cockpit.barra.total.text() == "/ até o Parar"
    qtbot.mouseClick(s.cockpit.barra.parar, Qt.MouseButton.LeftButton)
    assert c.estado == "parando" and not s.cockpit.barra.parar.isEnabled()
    qtbot.waitUntil(lambda: c.estado == "feita", timeout=ESPERA_MS)
    assert c.fim.parada_pedida and c.fim.blocos >= 1 and c.fim.crc_confere is True
    assert s.cockpit.fim.titulo.text().startswith("Captura parada em")


def test_a_queda_no_computador_fecha_o_que_chegou_e_avisa(bancada, qtbot):
    b = bancada
    s, c = b.secao, b.captura
    s.formulario.definir_pedido(PedidoDeCaptura((Canal(1),), 400_000, blocos=0))
    s.capturar_agora()
    qtbot.waitUntil(lambda: c.progresso is not None and c.progresso.blocos >= 1, timeout=ESPERA_MS)
    b.derrubar()
    qtbot.waitUntil(lambda: c.estado == "feita", timeout=ESPERA_MS)
    assert c.fim.caiu and c.fim.motivo == "conexao_caiu" and c.fim.blocos >= 1
    assert s.cockpit.fim.titulo.text() == "A captura parou: a conexão caiu"
    assert any(t.startswith("Fechada aqui com os blocos inteiros") for t in s.cockpit.fim.lista.textos), \
        s.cockpit.fim.lista.textos
    assert b.no_projeto == [c.arquivo] and api.conferir_integridade(api.abrir_captura(c.arquivo)) is True


def test_no_cartao_a_queda_nao_para_a_captura_e_ela_vem_para_o_computador(bancada, qtbot):
    """No cartão: o cockpit mostra os blocos (sem o sinal), o cabo que cai não para a captura, o acompanhamento volta
    com a conexão, e no fim a captura entra na fila, vem conferida e vai para o projeto."""
    b = bancada
    s, c = b.secao, b.captura
    s.formulario.definir_pedido(PedidoDeCaptura((Canal(1),), 400_000, blocos=3, destino="cartao", titulo="Cartão"))
    s.capturar_agora()
    qtbot.waitUntil(lambda: c.progresso is not None and c.progresso.blocos >= 1, timeout=ESPERA_MS)
    assert c.no_cartao and s.cockpit.no_cartao.isVisible() and not s.cockpit.graficos.isVisible()
    assert c.pedido.arquivo_no_cartao == c.nome and c.nome.startswith("cartao_")
    estados = []
    c.mudou.connect(lambda: estados.append(c.estado))
    b.derrubar()
    qtbot.waitUntil(lambda: c.estado == "feita", timeout=ESPERA_MS)
    assert "sem_conexao" in estados and c.retomada
    assert (c.fim.destino, c.fim.blocos, c.fim.motivo) == ("cartao", 3, "ok")
    qtbot.waitUntil(lambda: len(b.no_projeto) == 1, timeout=ESPERA_MS)
    (trazida,) = b.no_projeto
    assert trazida == b.transferencias.destino / c.nome and api.abrir_captura(trazida).cabecalho.blocos_gravados == 3
    assert any(t.startswith("No computador, conferida") for t in s.cockpit.fim.lista.textos)
    assert not s.cockpit.fim.trazer.isVisible()
    # Trazida, ela se abre daqui como a do computador.
    assert s.cockpit.fim.abrir.isVisible() and s.cockpit.fim.pasta.isVisible()
    qtbot.mouseClick(s.cockpit.fim.abrir, Qt.MouseButton.LeftButton)
    assert b.na_analise == [trazida]
    # No caderno, a queda, a volta, o fim e a transferência, nessa ordem.
    caderno = b.area.caderno
    qtbot.waitUntil(lambda: any("veio para o computador e confere" in e.texto for e in caderno.entradas),
                    timeout=ESPERA_MS)
    textos = [e.texto for e in caderno.entradas if c.nome in e.texto]
    assert [t.split(" ")[0] for t in textos] == ["Captura", "A", "A", "Captura", f"`{c.nome}`"]
    assert textos[1].startswith(f"A conexão caiu durante a captura `{c.nome}`: ela segue no cartão")
    assert textos[2].startswith(f"A captura `{c.nome}`, no cartão, acompanhada de novo")
    assert textos[3].startswith("Captura concluída") and textos[4].endswith(f"`{trazida}`.")


def test_a_conferencia_e_o_relatorio_do_diagnostico_vao_para_o_caderno(bancada, qtbot):
    """O "Conferir antes" entra no caderno com as linhas da tela (✓, !, ✗), e o "Para o caderno" do diagnóstico
    leva o relatório inteiro numa entrada (recuado no arquivo, inteiro na leitura)."""
    from sh_analyzer_gui.dados import caderno as formato

    b = bancada
    s, caderno = b.secao, b.area.caderno
    s.formulario.definir_pedido(PedidoDeCaptura((Canal(1),), 400_000, blocos=1))
    qtbot.mouseClick(s.conferir, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: b.area.conferencia.estado == "feita", timeout=ESPERA_MS)
    conferencia = caderno.entradas[-1]
    assert conferencia.autor == "automático" and conferencia.texto.startswith("Conferência: ")
    assert "\n- ✓ Canal 1: " in conferencia.texto and "\n- ✓ Captura íntegra" in conferencia.texto
    assert s.caderno.lista.textos[0].startswith(f"{conferencia.hora_em_texto} · automático · Conferência: ")
    b.area.mostrar_secao("diagnostico")
    b.area.diagnostico.para_o_caderno.click()
    relatorio = caderno.entradas[-1]
    assert relatorio.texto.startswith("Relatório do diagnóstico:\n\n# Diagnóstico da placa\n")
    assert formato.ler(caderno.caminho)[-1] == relatorio
    assert caderno.caminho.read_text(encoding="utf-8").count(formato.TITULO) == 1


def test_a_senha_do_sudo_e_perguntada_para_a_captura(bancada, qtbot):
    b = bancada
    s, c = b.secao, b.captura
    conexao_ssh = b.conexao.conexao_ssh
    original, conexao_ssh.senha = conexao_ssh.senha, None
    try:
        s.formulario.definir_pedido(PedidoDeCaptura((Canal(1),), 400_000, blocos=1))
        s.capturar_agora()
        qtbot.waitUntil(lambda: c.estado == "precisa_da_senha", timeout=ESPERA_MS)
        assert s.paginas.currentWidget() is s.pagina_do_pedido and s.pedido_da_senha.isVisible()
        assert "A captura usa o sudo" in s.texto_da_senha.text() and s.com_a_senha.text() == "Capturar"
        s.campo_da_senha.setText(original)
        s._conferir_com_a_senha()
        qtbot.waitUntil(lambda: c.estado == "feita", timeout=ESPERA_MS)
        assert c.fim.blocos == 1 and b.saude.senha_do_sudo == original and not s.pedido_da_senha.isVisible()
    finally:
        conexao_ssh.senha = original


def test_a_captura_que_ficou_pela_metade_e_fechada_e_entra_no_projeto(bancada, qtbot):
    from capturas_sinteticas import montar_cabecalho
    b = bancada
    s = b.secao
    b.sessao.mkdir(parents=True, exist_ok=True)
    provisorio = montar_cabecalho(1000, (0,), (0,), ("",), 400_000, versao=9, blocos=0, total_amostras=0,
                                  amostras_por_buffer=1000)
    parcial = b.sessao / "captura_20261118_101500.bin.parcial"
    parcial.write_bytes(provisorio + np.arange(2500, dtype="<u2").tobytes())
    assert s.procurar_parciais() == [parcial]
    assert s.painel_do_parcial.isVisible() and "captura_20261118_101500.bin" in s.texto_do_parcial.text()
    qtbot.mouseClick(s.fechar_o_parcial, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bool(b.no_projeto), timeout=ESPERA_MS)
    final = b.sessao / "captura_20261118_101500.bin"
    assert b.no_projeto == [final] and not parcial.exists() and not s.painel_do_parcial.isVisible()
    assert api.abrir_captura(final).cabecalho.fim_pelo_computador


def test_fechar_a_janela_no_meio_pergunta_e_interrompe(bancada, qtbot):
    b = bancada
    s, c = b.secao, b.captura
    s.formulario.definir_pedido(PedidoDeCaptura((Canal(1),), 400_000, blocos=0))
    s.capturar_agora()
    qtbot.waitUntil(lambda: c.estado == "capturando", timeout=ESPERA_MS)
    b.dialogos.respostas = [None]
    assert not b.area.pode_fechar() and c.rodando
    b.dialogos.respostas = ["fechar"]
    assert b.area.pode_fechar()
    qtbot.waitUntil(lambda: not c.rodando, timeout=ESPERA_MS)
    assert b.dialogos.perguntas == ["Uma captura está rodando"] * 2


def test_o_nome_livre_nunca_sobrescreve(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"")
    (tmp_path / "a_2.bin.parcial").write_bytes(b"")
    assert arquivo_livre(tmp_path, "a.bin") == tmp_path / "a_3.bin"
    assert arquivo_livre(tmp_path, "b.bin") == tmp_path / "b.bin"


def test_o_quadro_ao_vivo_e_o_ultimo_bloco_pela_api(tmp_path):
    """Sem Qt: o sinal é o fim do último bloco, nas unidades do canal, e o espectro é a média em potência dos
    blocos vistos (um bloco só: o Welch dele)."""
    from capturas_sinteticas import montar_cabecalho
    por_bloco, k = 4000, 2
    provisorio = montar_cabecalho(por_bloco, (0, 3), (0, 0), ("", ""), 400_000, versao=9, blocos=0,
                                  total_amostras=0, amostras_por_buffer=por_bloco)
    t = np.arange(3 * por_bloco // k) / 200_000
    codigos = np.empty(3 * por_bloco, dtype="<u2")
    codigos[0::2] = (32768 + 8000 * np.sin(2 * np.pi * 1000 * t)).astype("<u2")
    codigos[1::2] = 32768 + 100
    parcial = tmp_path / "x.bin.parcial"
    parcial.write_bytes(provisorio + codigos.tobytes())
    historico: dict = {}
    q1 = calcular_quadro(parcial, 1, historico, janela_s=0.005)
    q3 = calcular_quadro(parcial, 3, historico, janela_s=0.005)
    captura = api.abrir_ao_vivo(parcial, 3)
    fim = api.sinal_do_canal(captura, 0)
    a, b = q3.canais
    assert (a.numero, b.numero, q1.blocos, q3.blocos) == (0, 3, 1, 3) and len(a.sinal) == 1000
    np.testing.assert_allclose(a.sinal, fim[-1000:])
    assert a.na_media == 2 and isinstance(historico[0], deque)
    ultimo = api.espectro(fim[-por_bloco // k:], 200_000.0)
    primeiro = api.espectro(api.sinal_do_canal(captura, 0, 0, por_bloco // k), 200_000.0)
    esperado = 10 * np.log10((10 ** (ultimo.db / 10) + 10 ** (primeiro.db / 10)) / 2)
    np.testing.assert_allclose(a.db, esperado, rtol=1e-9)
