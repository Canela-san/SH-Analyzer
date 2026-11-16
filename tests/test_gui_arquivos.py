"""Os arquivos da placa na tela (F3.7), com o servidor SSH do teste: transferir e abrir na Análise, o título embaixo
do nome do arquivo, o "apagar da placa" só depois da conferência e da confirmação, a queda no meio e a retomada sozinha quando a placa volta (o arquivo
idêntico), a interface sem travar durante a transferência, a fila esperando a captura terminar, e o gerenciador de
arquivos do sistema. Sem placa e sem tela."""

import shutil
import subprocess
import sys
import time

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("asyncssh")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from placas_de_teste import CofreFalso, Placas  # noqa: E402
from PySide6.QtCore import QElapsedTimer, QTimer  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.area import AreaDeAquisicao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.arquivos import COLUNAS, PAPEL_DO_TITULO  # noqa: E402
from sh_analyzer_gui.servicos import conexao_da_placa as modulo_da_conexao  # noqa: E402
from sh_analyzer_gui.servicos.conexao_da_placa import ConexaoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.placa import ServicoDaPlaca  # noqa: E402
from sh_analyzer_gui.servicos.saude_da_placa import SaudeDaPlaca  # noqa: E402
from sh_analyzer_gui.tema.aplicar import aparencia  # noqa: E402
from sh_placa.descoberta import Descoberta, FonteSimulador  # noqa: E402
from sh_placa.destino import Destino  # noqa: E402

ESPERA_MS = 20_000


@pytest.fixture
def placas(tmp_path):
    p = Placas(tmp_path)
    yield p
    p.fechar()


def captura(servidor, nome="rede.bin", amostras=1 << 18):
    t = np.arange(amostras) / 200_000
    return escrever_bin(servidor.home / "firmware" / nome, [np.sin(2 * np.pi * 60 * t), 0.1 * np.sin(2e4 * t)],
                        fs_total=400_000, versao=9, titulo=f"Teste {nome}")


@pytest.fixture
def abrir(qapp, config_limpa, qtbot, tmp_path, monkeypatch):
    """A área conectada ao servidor, na seção Arquivos, com as capturas lidas. Devolve a área e o que ela abriu."""
    monkeypatch.setenv("DADOS", str(tmp_path / "dados"))
    criar_aplicacao([], tema="escuro")
    abertas = []

    def _abrir(servidor, dialogos=None):
        servico = ServicoDaPlaca()
        conexao = ConexaoDaPlaca(servico, descoberta=Descoberta([FonteSimulador()]), pasta=tmp_path / "aplicativo",
                                 cofre=CofreFalso(**{f"debian@127.0.0.1:{servidor.porta}": servidor.senha}))
        saude = SaudeDaPlaca(conexao)
        abertos, urls = [], []
        area = AreaDeAquisicao(conexao, saude, (lambda: dialogos) if dialogos is not None else None,
                               abrir_na_analise=abertos.extend, abrir_url=urls.append)
        area.abertos, area.urls = abertos, urls
        area.resize(1400, 860)
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
        qtbot.waitUntil(lambda: saude.capturas is not None and not saude.conferindo, timeout=ESPERA_MS)
        area.mostrar_secao("arquivos")
        return area

    yield _abrir
    for area, conexao, servico in abertas:
        conexao.encerrar()
        assert servico.encerrar()
        area.close()
        area.deleteLater()


def linha_de(area, nome):
    return next(i for i, c in enumerate(area.arquivos._capturas) if c.arquivo == nome)


def selecionar(area, nome):
    area.arquivos.tabela.clearSelection()
    area.arquivos.tabela.selectRow(linha_de(area, nome))


def esperar_conferida(qtbot, area, nome):
    t = area.transferencias
    qtbot.waitUntil(lambda: (item := next((i for i in t.itens if i.captura.arquivo == nome), None)) is not None
                    and item.estado in ("conferida", "corrompida", "falhou"), timeout=ESPERA_MS)
    return next(i for i in t.itens if i.captura.arquivo == nome)


def test_transferir_conferir_e_abrir_na_analise(qtbot, placas, abrir):
    servidor = placas.nova()
    original = captura(servidor)
    area = abrir(servidor)
    arquivos = area.arquivos
    selecionar(area, "rede.bin")
    assert arquivos.transferir.isEnabled() and not arquivos.apagar.isEnabled() and not arquivos.abrir.isEnabled()
    arquivos.transferir.click()
    item = esperar_conferida(qtbot, area, "rede.bin")
    assert (item.estado, item.como) == ("conferida", "crc32")
    destino = preferencias.pasta_da_sessao() / "rede.bin"
    assert item.local == destino and destino.read_bytes() == original.read_bytes()
    assert str(destino).startswith(str(preferencias.pasta_da_sessao().parents[1]))       # $DADOS/lab/AAAA-MM-DD
    selecionar(area, "rede.bin")
    assert arquivos.abrir.isEnabled() and arquivos.apagar.isEnabled()
    selo = arquivos.tabela.cellWidget(linha_de(area, "rede.bin"), arquivos.tabela.columnCount() - 1)
    assert selo.text() == "no computador"
    arquivos.abrir.click()
    assert area.abertos == [destino]
    linha = next(r for r in range(area.visao_geral.tabela.rowCount())
                 if area.visao_geral.tabela.item(r, 0).text() == "rede.bin")
    assert area.visao_geral.tabela.cellWidget(linha, 5).text() == "no computador"         # e na visão geral


def test_o_titulo_embaixo_do_nome_e_a_largura_da_coluna(qtbot, placas, abrir):
    """O título da captura vai embaixo do nome do arquivo, em cor de metadado (conferido pelos pixels), na coluna que
    fica com a largura que as outras deixam; na janela estreita, ela fica com a largura dos nomes, e a tabela rola de
    lado."""
    servidor = placas.nova()
    captura(servidor, "rede_da_bancada_com_um_nome_comprido.bin")
    area = abrir(servidor)
    tabela = area.arquivos.tabela
    assert "Título" not in COLUNAS and tabela.columnCount() == len(COLUNAS)
    linha = linha_de(area, "rede_da_bancada_com_um_nome_comprido.bin")
    item = tabela.item(linha, 0)
    assert item.text() == "rede_da_bancada_com_um_nome_comprido.bin"
    assert item.data(PAPEL_DO_TITULO) == "Teste rede_da_bancada_com_um_nome_comprido.bin"
    assert item.toolTip() == "rede_da_bancada_com_um_nome_comprido.bin\nTeste rede_da_bancada_com_um_nome_comprido.bin"
    cabeca = tabela.horizontalHeader()
    area.resize(1800, 860)
    qtbot.waitUntil(lambda: sum(cabeca.sectionSize(c) for c in range(len(COLUNAS))) == tabela.viewport().width(),
                    timeout=ESPERA_MS)
    assert cabeca.sectionSize(0) > tabela.sizeHintForColumn(0) and tabela.horizontalScrollBar().maximum() == 0
    celula = tabela.visualRect(tabela.model().index(linha, 0))
    imagem = tabela.viewport().grab(celula).toImage()
    mudo = QColor(aparencia().tema.mudo)
    perto = [(x, y) for y in range(imagem.height()) for x in range(imagem.width())
             if max(abs(imagem.pixelColor(x, y).red() - mudo.red()), abs(imagem.pixelColor(x, y).green() - mudo.green()),
                    abs(imagem.pixelColor(x, y).blue() - mudo.blue())) <= 12]
    assert perto and min(y for _x, y in perto) > imagem.height() / 2            # o título, na metade de baixo
    area.resize(900, 860)
    qtbot.waitUntil(lambda: cabeca.sectionSize(0) == tabela.sizeHintForColumn(0), timeout=ESPERA_MS)
    assert tabela.horizontalScrollBar().maximum() > 0


def test_apagar_so_o_conferido_e_com_confirmacao(qtbot, placas, abrir):
    servidor = placas.nova()
    original = captura(servidor)
    dialogos = DialogosFalsos(None, "apagar")
    area = abrir(servidor, dialogos)
    arquivos = area.arquivos
    selecionar(area, "rede.bin")
    arquivos.apagar_selecionadas()                                            # não conferida: nada
    assert original.exists() and dialogos.perguntas == []
    area.transferencias.transferir(arquivos.selecionadas())
    esperar_conferida(qtbot, area, "rede.bin")
    selecionar(area, "rede.bin")
    arquivos.apagar.click()                                                   # "Cancelar" na pergunta
    assert original.exists() and dialogos.perguntas == ["Apagar da placa"]
    selecionar(area, "rede.bin")
    arquivos.apagar.click()                                                   # agora sim
    qtbot.waitUntil(lambda: not original.exists(), timeout=ESPERA_MS)
    qtbot.waitUntil(lambda: all(c.arquivo != "rede.bin" for c in arquivos._capturas), timeout=ESPERA_MS)
    assert any(e.descricao == "apagar rede.bin da placa (SFTP)" for e in area.conexao.registro.entradas)
    assert (preferencias.pasta_da_sessao() / "rede.bin").exists()             # a cópia fica


def test_a_queda_no_meio_e_a_retomada_sozinha(qtbot, placas, abrir, monkeypatch):
    monkeypatch.setattr(modulo_da_conexao, "ESPERAS_DA_RECONEXAO_S", (0.2, 0.3, 0.5, 1, 1))
    servidor = placas.nova()
    original = captura(servidor, "longa.bin", amostras=1 << 22)              # 16 MiB
    area = abrir(servidor)
    t = area.transferencias
    caiu = []

    def derrubar_no_meio(item):
        if not caiu and item.fracao > 0.2:
            caiu.append(item.transferidos)
            placas.laco.agendar(servidor.derrubar)                            # o cabo que solta

    t.progrediu.connect(derrubar_no_meio)
    t.transferir([c for c in area.arquivos._capturas if c.arquivo == "longa.bin"])
    item = esperar_conferida(qtbot, area, "longa.bin")
    assert caiu and item.estado == "conferida"
    assert item.local.read_bytes() == original.read_bytes()
    baixadas = [e for e in area.conexao.registro.entradas if e.descricao.startswith("baixar longa.bin")]
    assert baixadas[0].codigo is None and "retomando de" in baixadas[-1].descricao


def test_a_interface_nao_trava_durante_a_transferencia(qtbot, placas, abrir):
    servidor = placas.nova()
    captura(servidor, "longa.bin", amostras=1 << 22)
    area = abrir(servidor)
    relogio, intervalos = QElapsedTimer(), []
    relogio.start()

    def tique():
        intervalos.append(relogio.restart())

    temporizador = QTimer()
    temporizador.timeout.connect(tique)
    temporizador.start(10)
    area.transferencias.transferir([c for c in area.arquivos._capturas if c.arquivo == "longa.bin"])
    esperar_conferida(qtbot, area, "longa.bin")
    temporizador.stop()
    assert len(intervalos) > 20 and max(intervalos) < 250, max(intervalos)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="o pgrep e o nome do processo, como na placa")
def test_a_fila_espera_a_captura_terminar(qtbot, placas, abrir, tmp_path):
    servidor = placas.nova()
    captura(servidor)
    area = abrir(servidor)
    ler_adc = tmp_path / "ler_adc"
    shutil.copy(shutil.which("sleep"), ler_adc)
    rodando = subprocess.Popen([str(ler_adc), "30"])                         # a captura "na placa" (aqui)
    try:
        area.transferencias.transferir([c for c in area.arquivos._capturas if c.arquivo == "rede.bin"])
        qtbot.waitUntil(lambda: area.transferencias.itens[0].estado == "esperando_a_captura", timeout=ESPERA_MS)
        linha = area.arquivos._linhas_da_fila[id(area.transferencias.itens[0])]
        assert linha.texto.text().startswith("esperando a captura terminar")
        time.sleep(0.5)
        assert area.transferencias.itens[0].transferidos == 0
    finally:
        rodando.kill()
        rodando.wait()
    assert esperar_conferida(qtbot, area, "rede.bin").estado == "conferida"


def test_o_gerenciador_de_arquivos(qtbot, placas, abrir):
    servidor = placas.nova()
    area = abrir(servidor)
    area.arquivos.gerenciador.click()
    (url,) = area.urls
    if sys.platform.startswith("linux"):
        assert url.scheme() == "sftp" and url.userName() == "debian" and url.host() == "127.0.0.1"
        assert url.port() == servidor.porta and url.path() == str(servidor.home / "firmware")
