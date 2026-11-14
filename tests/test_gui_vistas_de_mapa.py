"""As vistas das bandas IEC e do espectrograma (F2.6): os números são os da ``api`` (e esta, os do ``adc_tool
--bandas-iec``), a tabela na ordem da estatística, o tempo ligado ao da vista de tempo, as opções com desfazer e o
pedido novo que cancela o anterior. Sem tela."""

import threading

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.dados import espectros as esp  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from supraharmonicos import api  # noqa: E402

FS = 200_000.0
N = 400_000


@pytest.fixture
def janela(qapp, config_limpa, qtbot):
    criar_aplicacao([], tema="escuro")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.resize(1400, 900)
    j.show()
    qtbot.waitExposed(j)
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


@pytest.fixture
def plotado(janela, qtbot, tmp_path):
    t = np.arange(N) / FS
    v = 3.0 * np.sin(2 * np.pi * 50 * t) + 0.05 * np.sin(2 * np.pi * 9_050 * t) * (t > 1.0) \
        + np.random.default_rng(9).normal(0, 1e-3, N)
    caminho = escrever_bin(tmp_path / "c.bin", [v, 0.5 * v], grandezas=(0, 1), versao=9)
    (fonte,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    traco = janela.area.plotar_canal(fonte, 0)
    return fonte, traco, janela.area.widget_da_vista(janela.vista_ativa())


def abrir(janela, qtbot, acao):
    janela.acoes[acao].trigger()
    w = janela.area.widget_da_vista(janela.vista_ativa())
    qtbot.waitUntil(lambda: w.resultado is not None, timeout=10_000)
    return w


def test_as_bandas_sao_as_da_api_com_a_tabela_e_o_tempo_ligado(janela, qtbot, plotado):
    fonte, traco, tempo = plotado
    w = abrir(janela, qtbot, "bandas")
    assert w.vista.tipo == "bandas" and w.vista.nome == f"Bandas de {tempo.vista.nome}"
    esperado = api.bandas_iec(api.sinal_do_canal(fonte.fonte.captura, 0), FS, esp.OpcoesDasBandas().parametros)
    # Os códigos escalados e os volts arredondam diferente: ~1e-12 nas bandas fracas.
    np.testing.assert_allclose(w.resultado.bandas.niveis, esperado.bandas.niveis, rtol=1e-11)
    p95 = esperado.bandas.estatisticas()["p95"]
    assert w.linhas()[0][0] == esperado.bandas.centros_hz[int(np.argmax(p95))] == 9100.0   # o tom de 9 050 Hz
    assert w.tabela.rowCount() == len(esperado.bandas.centros_hz) and w.tabela.item(0, 0).text() == "9,1 kHz"
    # O mapa no tempo da vista de tempo: o tom só depois de 1 s; e o zoom de lá vem para cá.
    retangulo = w.imagem.mapRectToParent(w.imagem.boundingRect())
    assert retangulo.left() == pytest.approx(0.0) and retangulo.right() == pytest.approx(2.0, abs=1e-9)
    tempo.faixas[0].getViewBox().setXRange(0.5, 1.5, padding=0)
    x0, x1 = w.grafico.getViewBox().viewRange()[0]
    assert (x0, x1) == pytest.approx((0.5, 1.5), abs=1e-6)


def test_a_ordem_da_tabela_e_a_sincronizacao_com_desfazer(janela, qtbot, plotado):
    fonte, traco, tempo = plotado
    w = abrir(janela, qtbot, "bandas")
    pilha = janela.projeto.pilha
    w.estatistica.botao(3).click()                                     # o mínimo
    qtbot.waitUntil(lambda: w.opcoes_calculadas == w.opcoes, timeout=10_000)
    minimos = [est["minimo"] for _, est in w.linhas()]
    assert minimos == sorted(minimos, reverse=True)
    w.sincronizar.click()
    qtbot.waitUntil(lambda: w.opcoes_calculadas == w.opcoes, timeout=10_000)
    assert w.resultado.bandas.sincronizada and "sincronizadas" in w.info.text()
    pilha.undo()
    qtbot.waitUntil(lambda: w.opcoes_calculadas == w.opcoes, timeout=10_000)
    assert not w.resultado.bandas.sincronizada and not w.sincronizar.isChecked()
    pilha.undo()
    assert w.opcoes.estatistica == "p95"


def test_o_espectrograma_e_o_da_api_e_a_faixa_dinamica(janela, qtbot, plotado):
    fonte, traco, tempo = plotado
    w = abrir(janela, qtbot, "espectrograma")
    esperado = api.espectrograma(api.sinal_do_canal(fonte.fonte.captura, 0), FS, esp.OpcoesDoEspectrograma().parametros)
    np.testing.assert_allclose(w.resultado.db, esperado.db, rtol=0, atol=1e-9)
    topo = float(np.max(esperado.db))
    assert w.barra.levels() == pytest.approx((topo - 80.0, topo))
    w.faixa.setText("60")
    w.faixa.editingFinished.emit()
    assert w.opcoes.faixa_dinamica_db == 60.0 and w.barra.levels() == pytest.approx((topo - 60.0, topo))
    assert "colunas" in w.info.text()


def test_o_pedido_novo_cancela_o_anterior(janela, qtbot, plotado):
    fonte, traco, tempo = plotado
    w = abrir(janela, qtbot, "espectrograma")
    soltar = threading.Event()
    conta = w._conta

    def lenta(trecho, progresso, cancelado):
        while not soltar.wait(0.01):
            if cancelado():
                raise api.Cancelado()
        return conta(trecho, progresso, cancelado)

    w._conta = lenta
    w._chave_calculada = None                    # força a conta (o mesmo trecho não seria refeito)
    w._calcular()
    primeira = w._tarefa
    w._chave_calculada = None
    w._calcular()
    qtbot.waitUntil(lambda: primeira.estado == "cancelada", timeout=5_000)
    soltar.set()
    qtbot.waitUntil(lambda: w._tarefa is None, timeout=10_000)


def test_os_harmonicos_sao_os_da_api_com_as_barras_e_os_indices(janela, qtbot, plotado):
    fonte, traco, tempo = plotado
    w = abrir(janela, qtbot, "harmonicos")
    assert w.vista.tipo == "harmonicos" and w.opcoes.trecho == "janela"
    t0, t1 = tempo.janela_de_tempo()
    a, b = int(min(max(round(t0 * FS), 0), N)), int(min(max(round(t1 * FS), 0), N))
    esperado = api.harmonicos(api.sinal_do_canal(fonte.fonte.captura, 0, a, b), FS).tabela
    tab = w.resultado.tabela
    assert (tab.f0_hz, tab.n_ciclos, tab.thds_pct) == (esperado.f0_hz, esperado.n_ciclos, esperado.thds_pct)
    assert len(tab.harmonicos) == 40 and w.tabela.rowCount() == 40
    ordens, alturas = w.valores()
    np.testing.assert_allclose(alturas, [100 * h.rms_subgrupo / esperado.harmonicos[0].rms_subgrupo
                                         for h in esperado.harmonicos[1:]], rtol=1e-12)
    assert list(ordens) == list(range(2, 41))
    assert "THDS" in w.info.text() and f"{esperado.n_ciclos} ciclos" in w.info.text()
    pilha = janela.projeto.pilha
    w.escala.botao(1).click()                                         # o valor RMS
    w.grandeza.botao(2).click()                                       # a componente
    _, alturas = w.valores()
    np.testing.assert_allclose(alturas, [h.rms for h in esperado.harmonicos[1:]], rtol=1e-12)
    assert "valor RMS (V)" in w.grafico.getAxis("left").labelText
    w.ordem.setValue(10)
    qtbot.waitUntil(lambda: w.opcoes_calculadas == w.opcoes, timeout=10_000)
    assert len(w.resultado.tabela.harmonicos) == 10
    for _ in range(3):
        pilha.undo()
    qtbot.waitUntil(lambda: w.opcoes_calculadas == w.opcoes, timeout=10_000)
    assert w.opcoes == type(w.opcoes)(vista_de_tempo=tempo.vista.id) and len(w.resultado.tabela.harmonicos) == 40
