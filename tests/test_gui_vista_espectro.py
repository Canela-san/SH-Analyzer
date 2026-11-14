"""A vista de espectro (F2.5): os números da vista são os da ``api`` sobre o trecho de cada traço (e os da ``api``, os
da CLI); trocar a escala, o método e o trecho (cada um um passo de desfazer); a cadeia da vista de tempo; as marcas;
e as opções no projeto. Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.dados import projeto as arq  # noqa: E402
from sh_analyzer_gui.dados.cadeia import Cadeia, Filtro  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.modelo.comandos import MudarTracos  # noqa: E402
from sh_analyzer_gui.modelo.persistencia import descrever  # noqa: E402
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
def aberto(janela, qtbot, tmp_path):
    t = np.arange(N) / FS
    v = 3.0 * np.sin(2 * np.pi * 50 * t) + 0.05 * np.sin(2 * np.pi * 9_000 * t) \
        + np.random.default_rng(8).normal(0, 1e-3, N)
    caminho = escrever_bin(tmp_path / "c.bin", [v, 0.5 * v], grandezas=(0, 1), versao=9)
    (fonte,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    traco = janela.area.plotar_canal(fonte, 0)
    tempo = janela.area.widget_da_vista(janela.vista_ativa())
    janela.acoes["espectro"].trigger()
    espectro = janela.area.widget_da_vista(janela.vista_ativa())
    qtbot.waitUntil(lambda: bool(espectro.resultados), timeout=10_000)
    return fonte, traco, tempo, espectro


def recalcular(qtbot, espectro, mexer, quando=None):
    """Mexe e espera o resultado das opções novas (um resultado pedido antes pode chegar depois da mudança)."""
    mexer()
    qtbot.waitUntil(lambda: espectro.opcoes_calculadas == espectro.opcoes and (quando is None or quando()),
                    timeout=10_000)


def trecho_da_janela(tempo, traco):
    t0, t1 = tempo.janela_de_tempo()
    a = int(min(max(round((t0 - traco.receita.deslocamento_s) * FS), 0), N))
    b = int(min(max(round((t1 - traco.receita.deslocamento_s) * FS), 0), N))
    return a, b


def test_abrir_o_espectro_segue_a_vista_de_tempo_com_os_numeros_da_api(janela, aberto):
    fonte, traco, tempo, espectro = aberto
    vista = espectro.vista
    assert vista.tipo == "espectro" and vista.opcoes.vista_de_tempo == tempo.vista.id
    assert vista.nome == f"Espectro de {tempo.vista.nome}" and janela.vista_ativa() is vista
    (r,) = espectro.resultados
    a, b = trecho_da_janela(tempo, traco)
    esperado = api.espectro(api.sinal_do_canal(fonte.fonte.captura, 0, a, b), FS)
    np.testing.assert_allclose(r.espectro.db, esperado.db, rtol=0, atol=1e-9)
    x, y = espectro.curvas[traco].getData()
    np.testing.assert_allclose(y, esperado.db, rtol=0, atol=1e-9)
    assert [round(p.frequencia_hz / 1000) for p in r.marcas.picos] == [9]
    assert "Welch" in espectro.info.text() and "segmentos" in espectro.info.text()


def test_a_escala_o_metodo_e_o_trecho_cada_um_um_passo_de_desfazer(janela, qtbot, aberto):
    fonte, traco, tempo, espectro = aberto
    pilha = janela.projeto.pilha
    recalcular(qtbot, espectro, lambda: espectro.escala.botao(1).click())          # RMS
    assert espectro.opcoes.escala == "rms"
    _, y = espectro.curvas[traco].getData()
    np.testing.assert_allclose(y, espectro.resultados[0].espectro.niveis("rms"))
    assert "valor RMS (V)" in espectro.grafico.getAxis("left").labelText
    recalcular(qtbot, espectro, lambda: espectro.metodo.botao(1).click())          # FFT sincronizada
    e = espectro.resultados[0].espectro
    assert e.parametros.metodo == "fft" and e.f0_hz == pytest.approx(50, abs=0.01)
    assert espectro.resultados[0].marcas.harmonicos_hz[0] == pytest.approx(2 * e.f0_hz)
    recalcular(qtbot, espectro, lambda: espectro.trecho.botao(2).click())          # a captura inteira
    assert espectro.resultados[0].espectro.n_amostras <= N and espectro.opcoes.trecho == "captura"
    recalcular(qtbot, espectro, pilha.undo)
    recalcular(qtbot, espectro, pilha.undo)
    recalcular(qtbot, espectro, pilha.undo)
    assert espectro.opcoes == type(espectro.opcoes)(vista_de_tempo=tempo.vista.id)
    assert espectro.escala.escolhida == 0 and espectro.metodo.escolhida == 0


def test_os_cursores_da_vista_de_tempo(janela, qtbot, aberto):
    fonte, traco, tempo, espectro = aberto
    tempo.ligar_cursores(True)
    recalcular(qtbot, espectro, lambda: espectro.trecho.botao(1).click())
    a, b = (int(round(c * FS)) for c in sorted(tempo.cursores))
    esperado = api.espectro(api.sinal_do_canal(fonte.fonte.captura, 0, a, b), FS)
    np.testing.assert_allclose(espectro.resultados[0].espectro.db, esperado.db, rtol=0, atol=1e-9)


def test_a_cadeia_da_vista_de_tempo_muda_o_espectro(janela, qtbot, aberto):
    fonte, traco, tempo, espectro = aberto
    antes = espectro.resultados[0].espectro.nivel_em(50)
    cadeia = Cadeia((Filtro("passa_altas", (2000.0,), 4),))
    recalcular(qtbot, espectro, lambda: janela.projeto.pilha.push(MudarTracos([traco], cadeia=cadeia)),
               quando=lambda: espectro.resultados[0].trecho.cadeia == cadeia)
    depois = espectro.resultados[0].espectro.nivel_em(50)
    assert depois < antes - 60                                       # o passa-altas tirou os 50 Hz
    assert "PA 2 kHz" in espectro.chips[traco].resumo


def test_a_frequencia_log_tira_o_dc_e_as_opcoes_vao_para_o_projeto(janela, qtbot, aberto, tmp_path):
    fonte, traco, tempo, espectro = aberto
    recalcular(qtbot, espectro, lambda: espectro.log.click())
    x, _ = espectro.curvas[traco].getData()
    assert x[0] > 0 and espectro.grafico.getPlotItem().ctrl.logXCheck.isChecked()
    salvo = arq.de_dict(arq.para_dict(descrever(janela.projeto, tmp_path)))
    (vista_salva,) = [v for v in salvo.vistas if v.tipo == "espectro"]
    assert vista_salva.opcoes["frequencia_log"] is True and vista_salva.opcoes["vista_de_tempo"] == tempo.vista.id


def test_plotar_com_o_espectro_aberto_vai_para_a_vista_de_tempo(janela, aberto):
    fonte, traco, tempo, espectro = aberto
    novo = janela.area.plotar_canal(fonte, 1)
    assert novo in tempo.vista.tracos and not espectro.vista.tracos
