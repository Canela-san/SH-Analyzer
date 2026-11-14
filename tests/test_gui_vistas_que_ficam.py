"""O terceiro retorno do usuário: a vista fica onde ele a pôs depois de uma mudança (uma etapa da cadeia, o ganho, o
método, o trecho), o Alt + roda dá zoom nos dois eixos, clicar perto da linha seleciona o traço (no tempo e no
espectro), o Ctrl+W fecha a vista, e a janela, os ciclos e o preset da IEC 61000-4-7 no inspetor. Sem tela."""

import math

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.analise.vista_espectro import METODOS  # noqa: E402
from sh_analyzer_gui.dados import espectros as esp  # noqa: E402
from sh_analyzer_gui.dados.cadeia import Cadeia, Filtro, RemoverDC  # noqa: E402
from sh_analyzer_gui.graficos.clique import ALCANCE_DO_CLIQUE_PX, distancia_a_linha, mais_perto  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.modelo.comandos import MudarTracos  # noqa: E402

FS = 200_000.0
N = 200_000


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
    """Dois canais de tensão (a mesma faixa) e um de corrente (outra faixa): 2,5 V de DC com 1 V de 50 Hz e um tom de
    9 kHz; o segundo, a metade; a corrente, um cosseno."""
    t = np.arange(N) / FS
    v = 2.5 + np.sin(2 * np.pi * 50 * t) + 0.05 * np.sin(2 * np.pi * 9_000 * t)
    caminho = escrever_bin(tmp_path / "c.bin", [v, 0.5 * v, 0.2 * np.cos(2 * np.pi * 50 * t)], canais=(0, 1, 2),
                           grandezas=(0, 0, 1), sondas=("", "", ""), fs_total=int(3 * FS), versao=9)
    (fonte,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    a = janela.area.plotar_canal(fonte, 0)
    b = janela.area.plotar_canal(fonte, 1)
    i = janela.area.plotar_canal(fonte, 2)
    tempo = janela.area.widget_da_vista(janela.vista_ativa())
    return fonte, a, b, i, tempo


def pronta(janela, traco):
    estado = janela.materializacoes.estado_de(traco)
    return estado is not None and estado.pronta is not None


# ------------------------------------------------------------------ a vista de tempo

def test_alt_e_a_roda_dao_zoom_nos_dois_eixos_juntos(janela, qtbot, plotado):
    fonte, a, b, i, tempo = plotado
    caixa = tempo.faixas[a.receita.faixa].getViewBox()
    porta = tempo.grafico.viewport()
    centro = tempo.grafico.mapFromScene(caixa.sceneBoundingRect().center())

    def roda(angulo: QPoint):
        QApplication.sendEvent(porta, QWheelEvent(QPointF(centro), QPointF(porta.mapToGlobal(centro)), QPoint(0, 0),
                                                  angulo, Qt.MouseButton.NoButton, Qt.KeyboardModifier.AltModifier,
                                                  Qt.ScrollPhase.NoScrollPhase, False))

    (x0, x1), (y0, y1) = caixa.viewRange()
    roda(QPoint(0, 120))
    (p0, p1), (q0, q1) = caixa.viewRange()
    assert p1 - p0 == pytest.approx((x1 - x0) / 1.2) and q1 - q0 == pytest.approx((y1 - y0) / 1.2)
    # Com o Alt, o sistema costuma mandar a roda de lado: o zoom é o mesmo.
    roda(QPoint(-120, 0))
    (r0, r1), (s0, s1) = caixa.viewRange()
    assert r1 - r0 == pytest.approx((p1 - p0) * 1.2) and s1 - s0 == pytest.approx((q1 - q0) * 1.2)


def test_uma_etapa_na_cadeia_nao_mexe_na_vista(janela, qtbot, plotado):
    fonte, a, b, i, tempo = plotado
    caixa = tempo.faixas[a.receita.faixa].getViewBox()
    caixa.setXRange(0.30, 0.34, padding=0)
    caixa.setYRange(1.6, 4.5, padding=0)                              # o sinal, de 1,45 a 3,55 V, aparece em parte
    antes = caixa.viewRange()
    janela.projeto.pilha.push(MudarTracos([a], cadeia=Cadeia((Filtro("passa_baixas", (5_000.0,)),))))
    qtbot.waitUntil(lambda: pronta(janela, a), timeout=10_000)
    qtbot.wait(100)
    assert caixa.viewRange()[0] == pytest.approx(antes[0]) and caixa.viewRange()[1] == pytest.approx(antes[1])

    # Tirar o DC leva o traço inteiro para fora da vista: ela anda até ele, com a mesma altura e o mesmo tempo.
    janela.projeto.pilha.push(MudarTracos([a], cadeia=Cadeia((Filtro("passa_baixas", (5_000.0,)), RemoverDC()))))
    qtbot.waitUntil(lambda: abs(sum(caixa.viewRange()[1]) / 2) < 0.6, timeout=10_000)
    (x0, x1), (y0, y1) = caixa.viewRange()
    assert (x0, x1) == pytest.approx(antes[0]) and y1 - y0 == pytest.approx(2.9)


def test_numa_faixa_em_que_so_o_tempo_mudou_o_ganho_nao_reajusta_o_y(janela, qtbot, plotado):
    """A faixa da corrente nasceu depois do primeiro ajuste: o PyQtGraph ainda ajustava o Y dela sozinho."""
    fonte, a, b, i, tempo = plotado
    caixa = tempo.faixas[i.receita.faixa].getViewBox()
    qtbot.wait(50)
    antes = caixa.viewRange()[1]
    janela.projeto.pilha.push(MudarTracos([i], ganho=3.0))
    qtbot.wait(100)
    assert caixa.viewRange()[1] == pytest.approx(antes)


def test_clicar_na_linha_entre_duas_amostras_seleciona_o_traco(janela, qtbot, plotado):
    fonte, a, b, i, tempo = plotado
    caixa = tempo.faixas[a.receita.faixa].getViewBox()
    canal = fonte.canal(0)
    taxa = canal.taxa_hz                                              # a que a PRU gera, e não a pedida
    k = 60_000                                                        # 0,3 s
    caixa.setXRange(k / taxa, (k + 12) / taxa, padding=0)             # ~100 px entre as amostras
    item = tempo.itens[a]
    item.recalcular()
    v0, v1 = (float(x) * canal.escala + canal.deslocamento for x in canal.amostras[k + 5:k + 7])
    caixa.setYRange(min(v0, v1) - 0.01, max(v0, v1) + 0.01, padding=0)
    item.recalcular()
    tempo.itens[b].recalcular()
    largura, altura = caixa.viewPixelSize()
    assert 1 / taxa / largura > 40                                    # as amostras longe uma da outra
    x, y = (k + 5.5) / taxa, (v0 + v1) / 2                            # no meio da linha, longe das duas amostras
    assert tempo.traco_em(caixa, x, y + 5 * altura) is a
    assert tempo.traco_em(caixa, x, y + (ALCANCE_DO_CLIQUE_PX + 3) * altura) is None


def test_ctrl_w_fecha_a_vista_ativa(janela, qtbot, plotado):
    fonte, a, b, i, tempo = plotado
    assert janela.acoes["fechar_vista"].shortcut().toString() == "Ctrl+W"
    janela.acoes["espectro"].trigger()
    espectro = janela.vista_ativa()
    assert espectro.tipo == "espectro"
    janela.acoes["fechar_vista"].trigger()
    assert espectro not in janela.projeto.vistas and janela.vista_ativa() is tempo.vista
    janela.projeto.pilha.undo()                                       # desfazível, como o × da aba
    assert espectro in janela.projeto.vistas


def test_a_distancia_ate_a_linha_e_o_desempate():
    xs, ys = np.array([0.0, 10.0]), np.array([0.0, 0.0])
    assert distancia_a_linha(5.0, 3.0, xs, ys, 1.0, 1.0) == pytest.approx(3.0)      # no meio do segmento
    assert distancia_a_linha(13.0, 4.0, xs, ys, 1.0, 1.0) == pytest.approx(5.0)     # depois da ponta
    assert distancia_a_linha(5.0, 3.0, np.array([0.0, np.nan, 10.0]), np.zeros(3), 1.0, 1.0) == pytest.approx(
        math.hypot(5, 3))                                                            # o NaN corta a linha
    assert mais_perto([(3.0, 0, "a"), (2.0, 0, "b")]) == "b"
    assert mais_perto([(2.4, 1, "por cima"), (2.0, 0, "por baixo")]) == "por cima"  # empatados: o de cima
    assert mais_perto([(ALCANCE_DO_CLIQUE_PX + 0.1, 0, "longe")]) is None


# ------------------------------------------------------------------ o espectro

@pytest.fixture
def espectro(janela, qtbot, plotado):
    fonte, a, b, i, tempo = plotado
    janela.acoes["espectro"].trigger()
    w = janela.area.widget_da_vista(janela.vista_ativa())
    qtbot.waitUntil(lambda: bool(w.resultados) and all(r.desenho is not None for r in w.resultados), timeout=10_000)
    return w


def recalcular(qtbot, w, mexer):
    mexer()
    qtbot.waitUntil(lambda: w.opcoes_calculadas == w.opcoes and all(r.desenho is not None for r in w.resultados),
                    timeout=10_000)


def test_trocar_o_metodo_e_o_trecho_deixa_a_vista_e_a_escala_reajusta_o_y(janela, qtbot, plotado, espectro):
    vb = espectro.grafico.getViewBox()
    vb.setXRange(8_000, 10_000, padding=0)
    vb.setYRange(-80, -10, padding=0)
    antes = vb.viewRange()
    recalcular(qtbot, espectro, lambda: espectro.metodo.botao(METODOS.index("welch")).click())
    assert espectro.opcoes.metodo == "welch"
    assert vb.viewRange()[0] == pytest.approx(antes[0]) and vb.viewRange()[1] == pytest.approx(antes[1])
    recalcular(qtbot, espectro, lambda: espectro.trecho.botao(2).click())            # a captura inteira
    assert vb.viewRange()[0] == pytest.approx(antes[0]) and vb.viewRange()[1] == pytest.approx(antes[1])
    # Outra escala no Y (o valor RMS, em volts): o Y se ajusta; a frequência fica.
    recalcular(qtbot, espectro, lambda: espectro.escala.botao(1).click())
    (x0, x1), (y0, y1) = vb.viewRange()
    assert (x0, x1) == pytest.approx(antes[0]) and y0 > -1 and y1 < 1
    # A frequência log: a mesma faixa de frequências, na escala nova.
    recalcular(qtbot, espectro, lambda: espectro.log.click())
    (l0, l1), _ = vb.viewRange()
    assert (10 ** l0, 10 ** l1) == pytest.approx((8_000, 10_000), rel=1e-6)


def test_clicar_na_curva_mostra_a_janela_os_ciclos_e_o_preset_no_inspetor(janela, qtbot, plotado, espectro):
    fonte, a, b, i, tempo = plotado
    inspetor = janela.inspetor
    janela.selecao.limpar()
    assert inspetor.currentWidget() is inspetor.da_vista               # sem seleção: as opções da vista
    vb = espectro.grafico.getViewBox()
    vb.setXRange(8_500, 9_500, padding=0)
    d = next(r for r in espectro.resultados if r.traco is a).desenho
    i0 = d.indice(8_500)
    pico = i0 + int(np.argmax(d.niveis[i0:d.indice(9_500)]))         # o tom (a taxa da PRU o tira de 9 000 Hz)
    f_pico, nivel = d.f0 + pico * d.df, float(d.niveis[pico])
    vb.setYRange(nivel - 40, nivel + 10, padding=0)
    for item in espectro.curvas.values():
        item.recalcular()
    porta = espectro.grafico.viewport()
    ponto = espectro.grafico.mapFromScene(vb.mapViewToScene(QPointF(f_pico, nivel - 1)))
    for tipo, botoes in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                         (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
        QApplication.sendEvent(porta, QMouseEvent(tipo, QPointF(ponto), QPointF(porta.mapToGlobal(ponto)),
                                                  Qt.MouseButton.LeftButton, botoes, Qt.KeyboardModifier.NoModifier))
    qtbot.waitUntil(lambda: list(janela.selecao.tracos) == [a], timeout=2_000)
    assert inspetor.currentWidget() is inspetor.do_traco and inspetor.do_traco.secao_espectro.isVisible()
    assert espectro.chips[a].selecionado and espectro.curvas[a].zValue() > espectro.curvas[b].zValue()

    secao = inspetor.do_traco.espectro
    pilha = janela.projeto.pilha
    recalcular(qtbot, espectro, lambda: secao.janela.activated.emit(secao.janela.findData("hann")))
    assert espectro.opcoes.janela == "hann" and espectro.resultados[0].espectro.janela == "hann"
    recalcular(qtbot, espectro, lambda: secao.ciclos.setValue(7))
    assert espectro.opcoes.ciclos == 7 and espectro.resultados[0].espectro.n_ciclos == 7

    # O preset da IEC 61000-4-7: a rede é de 50 Hz, então 10 ciclos, a janela retangular sincronizada.
    cartao = secao.cartoes[0]
    assert cartao.aplicar.isEnabled() and "10 ciclos de 50 Hz" in cartao.descricao.text()
    recalcular(qtbot, espectro, cartao.aplicar.click)
    o = espectro.opcoes
    assert (o.metodo, o.modo, o.janela, o.ciclos) == ("fft", "tom", None, 10)
    e = espectro.resultados[0].espectro
    assert e.janela == "boxcar" and e.n_ciclos == 10                  # a retangular, pelo nome do SciPy and e.f0_hz == pytest.approx(50, abs=0.01)
    assert not cartao.aplicar.isEnabled() and cartao.aplicar.text() == "Aplicado"
    assert any("IEC 61000-4-7" in acao.text() for acao in janela.acoes_da_paleta())
    recalcular(qtbot, espectro, pilha.undo)                           # um passo de desfazer cada
    assert espectro.opcoes.ciclos == 7 and cartao.aplicar.isEnabled()


def test_as_opcoes_novas_vao_e_voltam_do_projeto():
    o = esp.OpcoesDoEspectro(janela="blackmanharris", ciclos=12)
    assert esp.OpcoesDoEspectro.de_dict(o.para_dict()) == o
    assert esp.OpcoesDoEspectro.de_dict({"metodo": "fft"}).ciclos is None          # um projeto de antes
    assert o.parametros.n_ciclos == 12 and o.com(metodo="welch").parametros.n_ciclos is None
    for ruim in ({"janela": "triangular"}, {"ciclos": 0}, {"ciclos": 2.5}):
        with pytest.raises(esp.OpcoesInvalidas):
            esp.OpcoesDoEspectro(**ruim)
    assert esp.ciclos_da_iec(None) == 12 and esp.ciclos_da_iec(59.98) == 12 and esp.ciclos_da_iec(50.02) == 10
