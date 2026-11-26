"""A vista de tempo (F1.5): as abas das vistas, as faixas pela unidade, os traços que seguem a receita, o histórico
do zoom, a seleção (clique, chip, árvore, Ctrl), o Del, o minimapa e o tema. Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.componentes.fluxo import LayoutDeFluxo  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.modelo.comandos import MudarTracos  # noqa: E402
from sh_analyzer_gui.tema.aplicar import aparencia  # noqa: E402
from sh_analyzer_gui.tema.tokens import TEMAS, cor_do_traco  # noqa: E402

TAXA_TOTAL = 400_000


def captura(pasta, nome="a.bin", n=40_000, pico=None):
    """Dois canais (tensão e corrente, com o ganho declarado: V e A) de 60 Hz; ``pico`` põe uma amostra só, alta,
    no canal 0."""
    pasta.mkdir(parents=True, exist_ok=True)
    t = np.arange(n) / (TAXA_TOTAL / 2)
    v = 0.1 * np.sin(2 * np.pi * 60 * t)
    if pico is not None:
        v[pico] = 0.4
    return escrever_bin(pasta / nome, [v, 0.05 * np.cos(2 * np.pi * 60 * t)], grandezas=(0, 1), versao=9,
                        extensao={"ganhos": [10.0, 20.0]})


@pytest.fixture
def janela(qapp, config_limpa, qtbot):
    criar_aplicacao([], tema="escuro")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.resize(1400, 900)
    j.show()
    qtbot.waitExposed(j)
    yield j
    aparencia().aplicar("escuro")
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def abrir(janela, qtbot, caminho):
    (fonte,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    return fonte


def vista_aberta(janela):
    return janela.area.widget_da_vista(janela.vista_ativa())


def test_plotar_abre_a_aba_e_as_faixas_pela_unidade(janela, qtbot, tmp_path):
    fonte = abrir(janela, qtbot, captura(tmp_path))
    janela.area.plotar_canal(fonte, 0)
    assert janela.vistas.count() == 1 and janela.centro.currentWidget() is janela.vistas
    vista = janela.vista_ativa()
    janela.area.plotar_canal(fonte, 1)
    janela.area.plotar_canal(fonte, 0)                                  # o mesmo canal de novo: outra cor
    w = vista_aberta(janela)
    assert [t.receita.faixa for t in vista.tracos] == [0, 1, 0]         # V numa faixa, A noutra
    assert [t.receita.cor for t in vista.tracos] == [0, 1, 2]
    assert sorted(w.faixas) == [0, 1] and len(w.itens) == 3 and len(w.chips) == 3
    assert w.faixas[0].getAxis("left").rotulo == "tensão (V)"
    assert w.faixas[1].getAxis("left").rotulo == "corrente (A)"
    # A faixa nova não leva a folga do ajuste automático do PyQtGraph para o tempo (começava em −3,7 %).
    qtbot.wait(150)                                                     # o ajuste do PyQtGraph roda na pintura
    for faixa in w.faixas.values():
        assert faixa.getViewBox().viewRange()[0][0] == pytest.approx(0.0, abs=1e-12)
    assert w.janela_de_tempo()[1] >= 0.19                                # ajustada à captura inteira (0,2 s)
    assert "amostras" in w.info.text()


def test_os_tracos_seguem_a_receita(janela, qtbot, tmp_path):
    fonte = abrir(janela, qtbot, captura(tmp_path))
    traco = janela.area.plotar_canal(fonte, 0)
    w = vista_aberta(janela)
    item = w.itens[traco]
    p = janela.projeto.pilha
    p.push(MudarTracos([traco], cor=3))
    assert item.cor.name() == cor_do_traco(3, TEMAS["escuro"])[0] and w.chips[traco].cor.name() == item.cor.name()
    escala = item._escala
    p.push(MudarTracos([traco], ganho=-2.0, offset=1.5))
    assert item._escala == pytest.approx(-2.0 * escala) and item._deslocamento == pytest.approx(
        -2.0 * fonte.canal(0).deslocamento + 1.5)
    p.push(MudarTracos([traco], deslocamento_s=0.05))
    assert item._t0 == 0.05 and "50 ms" in w.chips[traco].resumo
    p.push(MudarTracos([traco], visivel=False))
    assert not item.isVisible() and not w.chips[traco].visivel
    p.push(MudarTracos([traco], faixa=3))                               # outra faixa: o mesmo item, movido
    assert sorted(w.faixas) == [3] and w.itens[traco] is item
    assert item.getViewBox() is w.faixas[3].getViewBox()
    for _ in range(5):
        p.undo()
    assert w.itens[traco].isVisible() and sorted(w.faixas) == [0]


def test_sobrepor_poe_os_tracos_numa_faixa_e_guarda_a_de_cada_um(janela, qtbot, tmp_path):
    """AN-03: sobrepor é um passo de desfazer nas opções da vista; a faixa de cada traço fica guardada e volta ao
    separar. O tempo visível não muda, e o inspetor diz que a faixa não vale enquanto a vista sobrepõe."""
    fonte = abrir(janela, qtbot, captura(tmp_path))
    v = janela.area.plotar_canal(fonte, 0)
    a = janela.area.plotar_canal(fonte, 1)
    w, pilha = vista_aberta(janela), janela.projeto.pilha
    assert sorted(w.faixas) == [0, 1] and not w.acao_sobrepor.isChecked()
    w.faixas[0].getViewBox().setXRange(0.05, 0.1, padding=0)
    janela_antes = w.janela_de_tempo()
    w.acao_sobrepor.trigger()
    assert w.vista.opcoes.sobrepor and w.acao_sobrepor.isChecked() and pilha.undoText().startswith("Sobrepor")
    assert sorted(w.faixas) == [0] and set(w.faixas[0].escalas.tracos) == {v, a}
    assert [t.receita.faixa for t in (v, a)] == [0, 1]                  # a de cada um, guardada
    assert w.janela_de_tempo() == pytest.approx(janela_antes)
    janela.selecao.definir([v, a])
    faixa = janela.inspetor.do_traco.faixa
    assert not faixa.isEnabled() and "sobrepõe" in faixa.toolTip()
    nova = janela.area.plotar_canal(fonte, 0)                            # um traço novo também vai para ela
    assert sorted(w.faixas) == [0] and nova in w.faixas[0].escalas.tracos
    pilha.undo()                                                         # o plotar
    pilha.undo()                                                         # o sobrepor
    assert not w.vista.opcoes.sobrepor and not w.acao_sobrepor.isChecked() and sorted(w.faixas) == [0, 1]
    assert w.faixas[1].escalas.tracos == [a] and faixa.isEnabled() and faixa.toolTip() == ""
    pilha.redo()
    assert sorted(w.faixas) == [0] and w.acao_sobrepor.isChecked()
    w.acao_sobrepor.trigger()                                            # o botão também separa
    assert sorted(w.faixas) == [0, 1] and pilha.undoText().startswith("Separar")


def test_a_piramide_que_chega_depois(janela, qtbot, tmp_path):
    (fonte,) = janela.controle.abrir_capturas([captura(tmp_path)])
    traco = janela.area.plotar_canal(fonte, 0)                          # plotado antes da pirâmide ficar pronta
    w = vista_aberta(janela)
    qtbot.waitUntil(lambda: traco in w.itens, timeout=10_000)
    assert w.chips[traco].progresso is None


def test_o_pico_de_uma_amostra_aparece_na_vista(janela, qtbot, tmp_path):
    """O G4 dentro da vista: na captura inteira, a coluna do pico de uma amostra chega ao valor dele."""
    fonte = abrir(janela, qtbot, captura(tmp_path, pico=23_456))
    traco = janela.area.plotar_canal(fonte, 0)
    item = vista_aberta(janela).itens[traco]
    qtbot.waitUntil(lambda: item.consulta is not None)
    pico = fonte.canal(0).escala * np.asarray(fonte.canal(0).amostras[23_456]) + fonte.canal(0).deslocamento
    assert float(np.nanmax(item.consulta.maximos)) == pytest.approx(pico)


def test_o_historico_do_zoom_e_o_ajustar(janela, qtbot, tmp_path):
    fonte = abrir(janela, qtbot, captura(tmp_path))
    janela.area.plotar_canal(fonte, 0)
    w = vista_aberta(janela)
    vb = w._faixa_principal().getViewBox()
    inteira = w.janela_de_tempo()
    w._registrar_no_historico()
    for janela_de_tempo in ((0.01, 0.02), (0.012, 0.013)):
        vb.setXRange(*janela_de_tempo, padding=0)
        w._registrar_no_historico()                                     # a parada de 400 ms, sem esperar
    assert w.historico[-2:] == [(0.01, 0.02), (0.012, 0.013)]
    assert w.voltar() and w.janela_de_tempo() == pytest.approx((0.01, 0.02))
    assert w.voltar() and w.janela_de_tempo() == pytest.approx(inteira)
    assert not w.voltar()
    vb.setXRange(0.05, 0.06, padding=0)
    qtbot.waitUntil(lambda: w.historico[-1] == pytest.approx((0.05, 0.06)), timeout=2000)   # a parada, de verdade
    w.ajustar()
    assert w.janela_de_tempo() == pytest.approx(inteira)
    assert w.acao_voltar.shortcut().toString() == "Backspace" and w.acao_ajustar.shortcut().toString() == "F"
    qtbot.waitUntil(lambda: w.minimapa.janela == pytest.approx(inteira), timeout=2000)   # o minimapa acompanha
    w.minimapa.janelaPedida.emit(0.05, 0.06)                            # arrastar a janela no minimapa
    assert w.janela_de_tempo() == pytest.approx((0.05, 0.06))
    w.minimapa.grab()


def test_selecionar_pelo_clique_pelo_chip_e_pela_arvore(janela, qtbot, tmp_path):
    fonte = abrir(janela, qtbot, captura(tmp_path))
    a = janela.area.plotar_canal(fonte, 0)
    b = janela.area.plotar_canal(fonte, 0)
    w = vista_aberta(janela)
    caixa = w.faixas[0].getViewBox()
    qtbot.waitUntil(lambda: w.itens[a].consulta is not None)
    x = 0.1
    y = float(fonte.canal(0).escala * np.asarray(fonte.canal(0).amostras[int(x * TAXA_TOTAL / 2)])
              + fonte.canal(0).deslocamento)
    caixa.clicada.emit(x, y, Qt.KeyboardModifier.NoModifier)
    assert len(janela.selecao.tracos) == 1                              # os dois estão ali; fica o mais perto
    assert w.itens[janela.selecao.tracos[0]].zValue() == 10
    caixa.clicada.emit(x, 1e3, Qt.KeyboardModifier.NoModifier)          # longe de tudo: limpa
    assert janela.selecao.tracos == ()
    w.chips[b].clicado.emit()
    assert janela.selecao.tracos == (b,) and w.chips[b].selecionado and not w.chips[a].selecionado
    w.tracoClicado.emit(a, Qt.KeyboardModifier.ControlModifier)         # Ctrl soma
    assert set(janela.selecao.tracos) == {a, b}
    janela.selecao.limpar()
    painel = janela.painel_projeto
    painel.arvore.setCurrentIndex(painel.proxy.mapFromSource(painel.modelo.indice_do_canal(fonte, 0)))
    assert set(janela.selecao.tracos) == {a, b}                         # o canal da árvore seleciona os traços dele


def test_del_remove_os_selecionados_e_o_desfazer_os_devolve(janela, qtbot, tmp_path):
    fonte = abrir(janela, qtbot, captura(tmp_path))
    a = janela.area.plotar_canal(fonte, 0)
    b = janela.area.plotar_canal(fonte, 1)
    vista = janela.vista_ativa()
    assert not janela.area.remover_selecionados()                       # nada selecionado
    janela.selecao.definir([a])
    janela.acoes["remover_selecionados"].trigger()
    assert vista.tracos == (b,) and janela.selecao.tracos == ()
    assert janela.acoes["remover_selecionados"].shortcut().matches(Qt.Key.Key_Delete)
    janela.acoes["desfazer"].trigger()
    assert vista.tracos == (a, b)


def test_abas_nova_vista_e_fechar(janela, qtbot, tmp_path):
    fonte = abrir(janela, qtbot, captura(tmp_path))
    janela.area.plotar_canal(fonte, 0)
    janela.acoes["nova_vista"].trigger()
    assert [janela.vistas.tabText(i) for i in range(2)] == ["Tempo", "Tempo 2"]
    assert janela.vista_ativa().nome == "Tempo 2"
    janela.area.plotar_canal(fonte, 1)                                  # entra na vista da aba aberta
    assert len(janela.projeto.vistas[1].tracos) == 1
    botao = janela.vistas.tabBar().tabButton(0, janela.vistas.tabBar().ButtonPosition.RightSide)
    botao.click()                                                       # fecha a primeira (desfazível)
    assert [v.nome for v in janela.projeto.vistas] == ["Tempo 2"] and janela.vistas.count() == 1
    janela.acoes["desfazer"].trigger()
    assert janela.vistas.count() == 2 and janela.vistas.tabText(0) == "Tempo"
    vazia = vista_aberta(janela)
    assert vazia.vista.nome == "Tempo"


def test_a_vista_vazia_e_o_tema(janela, qtbot, tmp_path):
    janela.acoes["nova_vista"].trigger()
    w = vista_aberta(janela)
    assert w.vazio.isVisible() and not w.grafico.isVisible() and not w.minimapa.isVisible()
    fonte = abrir(janela, qtbot, captura(tmp_path))
    traco = janela.area.plotar_canal(fonte, 0)
    assert w.grafico.isVisible() and w.minimapa.isVisible()
    aparencia().aplicar("claro")
    assert w.itens[traco].cor.name() == cor_do_traco(0, TEMAS["claro"])[0]
    assert w.grafico.backgroundBrush().color().name() == TEMAS["claro"].afundada
    w.grab()


def test_a_legenda_quebra_a_linha(qapp, qtbot):
    from PySide6.QtWidgets import QPushButton, QWidget

    caixa = QWidget()
    fluxo = LayoutDeFluxo(caixa, espaco=6)
    for i in range(12):
        fluxo.addWidget(QPushButton(f"traço {i}"))
    qtbot.addWidget(caixa)
    larga, estreita = fluxo.heightForWidth(2000), fluxo.heightForWidth(200)
    assert estreita > larga > 0
    caixa.resize(200, estreita)
    caixa.show()
    botoes = caixa.findChildren(QPushButton)
    assert all(b.geometry().right() <= 200 for b in botoes)             # nada cortado
    fluxo.limpar()
    assert fluxo.count() == 0 and all(not b.isVisible() for b in botoes)


@pytest.mark.parametrize("inicio, fim, pixels", [(0, 1, 800), (10.0, 10.0006, 1200), (-3.2, 4.1, 300),
                                                  (1e-6, 3e-6, 500), (0, 31.457, 1500)])
def test_a_grade_cai_nas_marcas_principais_do_eixo(qapp, inicio, fim, pixels):
    """A grade calcula as marcas sem o ``tickValues`` (lento), mas elas têm de ser as mesmas do eixo."""
    from sh_analyzer_gui.graficos.faixa import EixoDoTema, marcas_principais

    eixo = EixoDoTema("bottom")
    esperadas = eixo.tickValues(inicio, fim, pixels)[0][1]
    np.testing.assert_allclose(marcas_principais(eixo, inicio, fim, pixels), esperadas, rtol=0, atol=1e-12 * (fim - inicio))
    assert len(marcas_principais(eixo, 1.0, 1.0, 100)) == 0
