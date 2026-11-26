"""A exportação dos dados pela janela (F5.5; FG-07): o botão da vista abre o diálogo, que diz o que vai sair e o que
não dá (os cursores desligados, nenhuma transformação), pergunta onde e grava numa tarefa; o arquivo volta igual aos
valores do traço, com a proveniência ao lado; o diálogo lembra a escolha; um traço com transformações sai como na
tela (a materialização), sem elas (o canal) ou em códigos do ADC."""

import json

import h5py
import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

import scipy.io  # noqa: E402
from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.analise.exportar_dados import PedidoDeDados  # noqa: E402
from sh_analyzer_gui.dados.cadeia import Cadeia, Filtro  # noqa: E402
from sh_analyzer_gui.dados.exportar_dados import OpcoesDosDados  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.modelo.comandos import MudarTracos  # noqa: E402
from supraharmonicos import api  # noqa: E402
from test_gui_jornada_figura import _plotar  # noqa: E402

ESPERA_MS = 30_000
TAXA = 400_000
N = 20_000
PA = Cadeia((Filtro("passa_altas", (1000.0,), 4),))


@pytest.fixture
def janela(qapp, config_limpa):
    criar_aplicacao([], tema="escuro")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.resize(1400, 900)
    j.show()
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def _abrir(janela, qtbot, pasta, *canais):
    t = np.arange(N) / (TAXA / 2)
    v = 3.0 * np.sin(2 * np.pi * 60 * t) + 0.3 * np.sin(2 * np.pi * 3000 * t)
    i = 1.0 * np.sin(2 * np.pi * 60 * t - 0.5)
    pasta.mkdir(parents=True, exist_ok=True)
    assert janela.controle.abrir_capturas([escrever_bin(pasta / "rede.bin", [v, i], canais=(1, 3), versao=9)])
    (fonte,) = janela.projeto.fontes
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=ESPERA_MS)
    for numero in canais:
        _plotar(janela, fonte, numero)
    vista = janela.area.vista_ativa()
    widget = janela.area.widget_da_vista(vista)
    qtbot.waitUntil(lambda: len(vista.tracos) == len(canais) and widget.janela_de_tempo() is not None,
                    timeout=ESPERA_MS)
    return fonte, vista, widget


def _em_unidades(canal, inicio=0, fim=None):
    return canal.amostras[inicio:fim].astype(np.float64) * canal.escala + canal.deslocamento


def _exportar_pelo_dialogo(janela, qtbot, dialogo, destino):
    janela.controle.dialogos = DialogosFalsos(destino)
    with qtbot.waitSignal(janela.area.dadosExportados, timeout=ESPERA_MS) as sinal:
        qtbot.mouseClick(dialogo.exportar, Qt.MouseButton.LeftButton)
    return sinal.args[0]


def test_exportar_os_dados_pela_janela(janela, qtbot, tmp_path):
    fonte, vista, widget = _abrir(janela, qtbot, tmp_path / "dados", 1, 3)
    area = janela.area
    (tmp_path / "saida").mkdir()

    # 1. O diálogo: o CSV e a janela, por padrão; sem cursores e sem transformações, essas opções dizem por quê.
    qtbot.mouseClick(janela.botao_exportar_dados, Qt.MouseButton.LeftButton)
    dialogo = area.dialogo_de_dados
    assert dialogo is not None and dialogo.isVisible() and dialogo.exportar.isEnabled()
    assert not dialogo.regiao.botao(1).isEnabled() and "cursores" in dialogo.regiao.botao(1).toolTip()
    assert not dialogo.valores.botao(1).isEnabled()
    assert dialogo.separador.isEnabled() and dialogo.resumo.text().startswith("2 coluna(s)")

    # 2. A captura inteira em HDF5: o arquivo (a extensão entra sozinha), os valores e a captura de onde vieram.
    dialogo.formato.botao(1).click()
    assert not dialogo.separador.isEnabled() and dialogo.separador.toolTip() == "Só no CSV"
    dialogo.regiao.botao(2).click()
    assert "20 000 linhas" in dialogo.resumo.text()
    h5 = _exportar_pelo_dialogo(janela, qtbot, dialogo, tmp_path / "saida" / "rede")
    assert h5 == tmp_path / "saida" / "rede.h5" and area.dialogo_de_dados is None
    canais = [fonte.canal(1), fonte.canal(3)]
    with h5py.File(h5) as f5:
        np.testing.assert_array_equal(f5["valores"][:], np.column_stack([_em_unidades(c) for c in canais]))
        assert list(f5.attrs["nomes"]) == [t.receita.nome for t in vista.tracos]
        assert f5["captura"].attrs["cabecalho_versao"] == 9
    p = json.loads((tmp_path / "saida" / "rede.proveniencia.json").read_text(encoding="utf-8"))
    assert p["dados"]["regiao"] == "captura inteira" and p["dados"]["linhas"] == N
    assert p["fontes"][0]["crc32_amostras"] == fonte.fonte.captura.cabecalho.crc32_amostras
    assert p["comandos_da_cli"][0]["comando"].startswith("adc_tool.py ")

    # 3. O diálogo lembra; a janela visível em CSV, com o tempo de cada linha.
    qtbot.mouseClick(janela.botao_exportar_dados, Qt.MouseButton.LeftButton)
    dialogo = area.dialogo_de_dados
    assert (dialogo.formato.escolhida, dialogo.regiao.escolhida) == (1, 2)
    dialogo.formato.botao(0).click()
    dialogo.regiao.botao(0).click()
    a, b = widget.janela_de_tempo()
    csv = _exportar_pelo_dialogo(janela, qtbot, dialogo, tmp_path / "saida" / "janela.csv")
    linhas = [x for x in csv.read_text(encoding="utf-8").splitlines() if not x.startswith("#")][1:]
    tabela = np.array([[float(v.replace(",", ".")) for v in x.split(";")] for x in linhas])
    i0 = max(0, int(np.ceil(a * canais[0].taxa_hz - 1e-9)))          # a janela pode começar antes da captura
    assert tabela[0, 0] == pytest.approx(i0 / canais[0].taxa_hz, abs=1e-12) and tabela[-1, 0] <= b + 1e-12
    np.testing.assert_allclose(tabela[:, 1], _em_unidades(canais[0], i0, i0 + len(tabela)), rtol=1e-14, atol=1e-15)

    # 4. Entre os cursores, em NPZ, direto (sem o diálogo).
    widget.cursores = [0.02, 0.01]
    npz = tmp_path / "saida" / "cursores.npz"
    with qtbot.waitSignal(area.dadosExportados, timeout=ESPERA_MS):
        area.exportar_dados(vista, PedidoDeDados(OpcoesDosDados("npz"), "cursores"), npz)
    with np.load(npz) as z:
        assert z["valores"].shape == (round(0.01 * canais[0].taxa_hz) + 1, 2)
        assert float(z["t0_s"]) == pytest.approx(0.01)


def test_os_dados_com_e_sem_as_transformacoes(janela, qtbot, tmp_path):
    fonte, vista, _widget = _abrir(janela, qtbot, tmp_path / "dados", 1)
    area = janela.area
    (traco,) = vista.tracos
    janela.projeto.pilha.push(MudarTracos([traco], cadeia=PA))
    canal = fonte.canal(1)

    # 1. Como na tela: a materialização (o diálogo espera por ela).
    qtbot.mouseClick(janela.botao_exportar_dados, Qt.MouseButton.LeftButton)
    dialogo = area.dialogo_de_dados
    assert dialogo.valores.botao(1).isEnabled()
    estado = janela.materializacoes.estado_de(traco)
    qtbot.waitUntil(lambda: estado.pronta is not None and dialogo.exportar.isEnabled(), timeout=ESPERA_MS)
    dialogo.formato.botao(3).click()
    dialogo.regiao.botao(2).click()
    tela = _exportar_pelo_dialogo(janela, qtbot, dialogo, tmp_path / "tela.npz")
    with np.load(tela) as z:
        np.testing.assert_array_equal(z["valores"][:, 0], np.asarray(estado.pronta.amostras, np.float64))
        assert json.loads(str(z["transformacoes_por_coluna"][0]))[0]["tipo"] == "filtro"

    # 2. Sem as transformações: o canal, com a cadeia na proveniência como não aplicada, e o comando da CLI.
    sem = tmp_path / "canal.npz"
    with qtbot.waitSignal(area.dadosExportados, timeout=ESPERA_MS):
        area.exportar_dados(vista, PedidoDeDados(OpcoesDosDados("npz"), "inteira", transformacoes=False), sem)
    with np.load(sem) as z:
        np.testing.assert_array_equal(z["valores"][:, 0], _em_unidades(canal))
    p = json.loads((tmp_path / "canal.proveniencia.json").read_text(encoding="utf-8"))
    assert p["colunas"][0]["receita"]["etapas_nao_aplicadas"] and p["comandos_da_cli"][0]["comando"]

    # 3. Os códigos do ADC, em MAT: o tipo da captura e a escala para a unidade.
    crus = tmp_path / "crus.mat"
    with qtbot.waitSignal(area.dadosExportados, timeout=ESPERA_MS):
        area.exportar_dados(vista, PedidoDeDados(OpcoesDosDados("mat", crus=True), "inteira"), crus)
    m = scipy.io.loadmat(crus)
    assert m["amostras"].dtype == canal.amostras.dtype
    np.testing.assert_array_equal(m["amostras"][:, 0], canal.amostras)
    assert m["escala_por_coluna"][0, 0] == canal.escala

    # 4. A fonte derivada (TR-08): os valores com o filtro, numa captura que entra no projeto.
    derivada = tmp_path / "filtrada.derivada.h5"
    with qtbot.waitSignal(area.dadosExportados, timeout=ESPERA_MS):
        area.exportar_dados(vista, PedidoDeDados(OpcoesDosDados("captura"), "inteira"), derivada)
    assert [f.nome for f in janela.projeto.fontes][-1] == "filtrada.derivada.h5"
    nova = janela.projeto.fontes[-1]
    um_codigo = np.ptp(estado.pronta.amostras) / 52_428
    assert np.max(np.abs(api.sinal_do_canal(nova.fonte.captura, 0) - estado.pronta.amostras)) <= um_codigo
