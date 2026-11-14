"""A escala própria de cada traço (``graficos/escalas.py``): o eixo Y mostra a unidade e os números do traço
selecionado, o cadeado destrava o Y de um traço (os gestos com ele selecionado mexem só nele, e os dos outros não o
tiram do lugar), "Mesma escala" o devolve à escala comum, e os valores do traço não mudam. Na vista de tempo e na de
espectro. Na de tempo, o destravado tem também o seu tempo: o eixo do tempo o mostra, e as medidas, o espectro e o
minimapa usam o trecho dele. Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.componentes.chip import ChipDeTraco  # noqa: E402
from sh_analyzer_gui.componentes.numeros import formatar_si  # noqa: E402
from sh_analyzer_gui.graficos.escalas import COMUM, Afim, Escala  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.modelo.comandos import MudarTracos  # noqa: E402
from sh_analyzer_gui.tema.aplicar import aparencia  # noqa: E402
from sh_analyzer_gui.tema.tokens import cor_do_traco  # noqa: E402

FS = 200_000.0
N = 100_000


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
def separados(janela, qtbot, tmp_path):
    """Uma tensão de 3 V e uma corrente pequena (0,2 A: 20 mV no pino, com o ganho de 10 A/V declarado), cada uma na
    sua faixa (o plotar separa as unidades)."""
    t = np.arange(N) / FS
    caminho = escrever_bin(tmp_path / "c.bin", [3.0 * np.sin(2 * np.pi * 50 * t), 0.02 * np.cos(2 * np.pi * 50 * t)],
                           grandezas=(0, 1), fs_total=int(2 * FS), versao=9, extensao={"ganhos": [1.0, 10.0]})
    (fonte,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    v = janela.area.plotar_canal(fonte, 0)
    a = janela.area.plotar_canal(fonte, 1)
    tempo = janela.area.widget_da_vista(janela.vista_ativa())
    assert a.receita.faixa != v.receita.faixa and len(tempo.faixas) == 2
    qtbot.waitUntil(lambda: all(i.consulta is not None for i in tempo.itens.values()))
    return fonte, v, a, tempo


@pytest.fixture
def juntos(janela, qtbot, separados):
    """As duas na mesma faixa."""
    fonte, v, a, tempo = separados
    janela.projeto.pilha.push(MudarTracos([a], faixa=v.receita.faixa))
    assert len(tempo.faixas) == 1
    qtbot.waitUntil(lambda: all(i.consulta is not None for i in tempo.itens.values()))
    return fonte, v, a, tempo


def roda(grafico, caixa, modificadores=Qt.KeyboardModifier.ControlModifier, passos=1):
    porta = grafico.viewport()
    centro = grafico.mapFromScene(caixa.sceneBoundingRect().center())
    for _ in range(passos):
        QApplication.sendEvent(porta, QWheelEvent(QPointF(centro), QPointF(porta.mapToGlobal(centro)), QPoint(0, 0),
                                                  QPoint(0, 120), Qt.MouseButton.NoButton, modificadores,
                                                  Qt.ScrollPhase.NoScrollPhase, False))


def na_tela(caixa, escala: Escala, valor: float) -> float:
    """Onde o ``valor`` de um traço de ``escala`` cai na tela (a coordenada y da cena)."""
    return caixa.mapViewToScene(QPointF(0.0, escala.y.na_vista(valor))).y()


def no_tempo_da_tela(caixa, escala: Escala, t: float) -> float:
    """Onde o instante ``t`` de um traço de ``escala`` cai na tela (a coordenada x da cena)."""
    return caixa.mapViewToScene(QPointF(escala.x.na_vista(t), 0.0)).x()


# ------------------------------------------------------------------ a conta

def test_as_contas_da_escala():
    e = Afim(2.0, 1.0)
    assert e.no_traco(e.na_vista(3.5)) == pytest.approx(3.5) and Afim().comum and not e.comum
    # O zoom em volta de um centro deixa o centro no lugar; o pan anda o traço.
    z = e.ampliada(0.5, 7.0)
    assert z.na_vista(e.no_traco(7.0)) == pytest.approx(7.0) and z.k == pytest.approx(4.0)
    assert e.deslocada(0.25).na_vista(3.0) == pytest.approx(e.na_vista(3.0) - 0.25)
    # Acompanhar a faixa da caixa deixa o traço no mesmo ponto da faixa (no mesmo lugar da tela).
    antes, depois = (0.0, 10.0), (-5.0, 15.0)
    f = e.acompanhando(antes, depois)
    for valor in (-1.0, 0.0, 2.5):
        fracao = (e.na_vista(valor) - antes[0]) / 10.0
        assert (f.na_vista(valor) - depois[0]) / 20.0 == pytest.approx(fracao)
    # Enquadrar: os limites ocupam a faixa, com a folga de cada lado.
    q = Afim.enquadrando((-0.2, 0.2), (-3.0, 3.0), 0.0)
    assert (q.na_vista(-0.2), q.na_vista(0.2)) == pytest.approx((-3.0, 3.0))


def test_a_escala_tem_os_dois_eixos():
    assert COMUM.comum and COMUM.transformacao().isIdentity()
    e = Escala(Afim(0.5, 2.0), Afim(3.0, -1.0))
    ponto = e.transformacao().map(QPointF(4.0, 1.0))                # o item desenhado: x = 0,5·t + 2, y = 3·v − 1
    assert (ponto.x(), ponto.y()) == pytest.approx((4.0, 2.0)) and not e.comum
    # Um eixo sem fator (None) fica como está: o zoom só do Y não mexe no tempo, e o pan só do tempo não mexe no Y.
    so_y = e.ampliada(None, 0.5, QPointF(0.0, 0.0))
    assert so_y.x == e.x and so_y.y.k == pytest.approx(6.0)
    so_x = e.deslocada(1.0, None)
    assert so_x.y == e.y and so_x.x.c == pytest.approx(1.0)


# ------------------------------------------------------------------ a vista de tempo

def test_o_eixo_mostra_a_unidade_do_traco_selecionado(janela, juntos):
    fonte, v, a, tempo = juntos
    faixa = tempo.faixas[v.receita.faixa]
    tema = aparencia().tema
    # Sem seleção, o primeiro travado (a tensão); com unidades diferentes na faixa, o rótulo vem na cor do traço.
    assert faixa.rotulo_y == ("tensão (V)", cor_do_traco(v.receita.cor, tema)[0])
    janela.selecao.definir([a])
    assert faixa.rotulo_y == ("corrente (A)", cor_do_traco(a.receita.cor, tema)[0])
    assert "corrente (A)" in faixa.getAxis("left").labelText
    janela.selecao.definir([v, a])                                 # o último selecionado
    assert faixa.rotulo_y[0] == "corrente (A)"
    janela.selecao.limpar()
    assert faixa.rotulo_y[0] == "tensão (V)"


def test_o_cadeado_da_ao_traco_uma_escala_so_dele(janela, qtbot, juntos):
    fonte, v, a, tempo = juntos
    faixa = tempo.faixas[v.receita.faixa]
    caixa, eixo, escalas = faixa.getViewBox(), faixa.getAxis("left"), faixa.escalas
    assert not tempo.acao_destravar.isEnabled()                     # sem seleção, nada a destravar
    janela.selecao.definir([a])
    assert tempo.acao_destravar.isEnabled() and not tempo.acao_destravar.isChecked()
    tempo.acao_destravar.trigger()
    assert not escalas.travado(a) and tempo.acao_destravar.isChecked() and tempo.chips[a].escala == "solta"
    x0, x1 = caixa.viewRange()[0]
    valores_antes = tempo.itens[a].limites_y_em(x0, x1)
    y_antes = caixa.viewRange()[1]

    roda(tempo.grafico, caixa)                                      # Ctrl + roda: o zoom do Y, só na corrente
    assert caixa.viewRange()[1] == pytest.approx(y_antes)
    e = escalas.escala(a)
    assert e.y.k == pytest.approx(1.2) and e.x.comum and tempo.itens[v].transform().isIdentity()
    # O eixo mostra os números da corrente; os valores dela não mudaram (só o desenho).
    (y0, y1) = caixa.viewRange()[1]
    assert eixo.range == pytest.approx([e.y.no_traco(y0), e.y.no_traco(y1)])
    assert tempo.itens[a].limites_y_em(x0, x1) == pytest.approx(valores_antes)
    assert tempo.acao_igualar.isEnabled() and tempo.chips[a].escala == "solta"

    # Clicar na linha desenhada (ampliada) ainda seleciona a corrente.
    janela.selecao.limpar()
    t = (x0 + x1) / 2
    valor = float(fonte.canal(1).amostras[int(round(t * FS))]) * fonte.canal(1).escala + fonte.canal(1).deslocamento
    assert tempo.traco_em(caixa, t, e.y.na_vista(valor)) is a

    # Com a tensão (travada) selecionada, o zoom é da faixa: a corrente fica no mesmo lugar da tela.
    janela.selecao.definir([v])
    assert eixo.range == pytest.approx(list(caixa.viewRange()[1]))  # os números da tensão
    tela = [na_tela(caixa, escalas.escala(a), x) for x in (-0.1, 0.0, 0.15)]
    roda(tempo.grafico, caixa, passos=2)
    assert caixa.viewRange()[1] != pytest.approx(y_antes)
    assert [na_tela(caixa, escalas.escala(a), x) for x in (-0.1, 0.0, 0.15)] == pytest.approx(tela, abs=0.01)


def test_mesma_escala_e_travar_de_novo(janela, qtbot, juntos):
    fonte, v, a, tempo = juntos
    faixa = tempo.faixas[v.receita.faixa]
    caixa, escalas = faixa.getViewBox(), faixa.escalas
    janela.selecao.definir([a])
    tempo.acao_destravar.trigger()
    roda(tempo.grafico, caixa, passos=3)
    assert not escalas.escala(a).comum
    tempo.acao_igualar.trigger()                                    # "Mesma escala": a comum; o cadeado fica aberto
    assert escalas.escala(a).comum and not escalas.travado(a) and not tempo.acao_igualar.isEnabled()

    roda(tempo.grafico, caixa, passos=3)
    propria = escalas.escala(a)
    tempo.acao_destravar.trigger()                                  # travar de novo: a escala que ganhou fica
    assert escalas.travado(a) and escalas.escala(a) == propria and tempo.chips[a].escala == "propria"
    y_antes = caixa.viewRange()[1]
    roda(tempo.grafico, caixa)                                      # travada, ela anda com a faixa
    assert caixa.viewRange()[1] != pytest.approx(y_antes) and escalas.escala(a) == propria

    # Sem seleção, "Mesma escala" vale para todos.
    janela.selecao.limpar()
    assert tempo.acao_igualar.isEnabled()
    tempo.acao_igualar.trigger()
    assert escalas.escala(a).comum and tempo.chips[a].escala is None


def test_ajustar_poe_o_traco_destravado_na_altura_inteira(janela, qtbot, juntos):
    fonte, v, a, tempo = juntos
    faixa = tempo.faixas[v.receita.faixa]
    caixa, escalas = faixa.getViewBox(), faixa.escalas
    janela.selecao.definir([a])
    tempo.acao_destravar.trigger()
    tempo.ajustar()
    (y0, y1) = caixa.viewRange()[1]
    assert (y0, y1) == pytest.approx((-3.0 * 1.04, 3.0 * 1.04), rel=0.02)     # a tensão (travada) ajusta a faixa
    baixo, alto = escalas.limites_na_vista(a, tempo.itens[a].dataBounds(1))
    assert (baixo, alto) == pytest.approx((y0 + 0.02 / 1.04 * (y1 - y0), y1 - 0.02 / 1.04 * (y1 - y0)), rel=0.02)


def test_alt_roda_e_o_botao_do_meio_com_o_traco_destravado(janela, qtbot, juntos):
    fonte, v, a, tempo = juntos
    faixa = tempo.faixas[v.receita.faixa]
    caixa, escalas = faixa.getViewBox(), faixa.escalas
    janela.selecao.definir([a])
    tempo.acao_destravar.trigger()
    x, y = caixa.viewRange()
    roda(tempo.grafico, caixa, Qt.KeyboardModifier.AltModifier)    # o tempo e o Y, os dois só da corrente
    assert caixa.viewRange() == [pytest.approx(x), pytest.approx(y)]
    assert escalas.escala(a).x.k == pytest.approx(1.2) and escalas.escala(a).y.k == pytest.approx(1.2)
    caixa.translateBy(y=0.5)                                        # o pan do meio: só ela anda
    assert caixa.viewRange()[1] == pytest.approx(y)
    caixa.centralizar_no_zero()                                     # o clique do meio: o 0 dela no meio da faixa
    assert escalas.escala(a).y.na_vista(0.0) == pytest.approx(sum(y) / 2) and caixa.viewRange()[1] == pytest.approx(y)


def test_mudar_a_faixa_volta_o_traco_a_escala_comum(janela, qtbot, juntos):
    fonte, v, a, tempo = juntos
    janela.selecao.definir([a])
    tempo.acao_destravar.trigger()
    roda(tempo.grafico, tempo.faixas[v.receita.faixa].getViewBox())
    janela.projeto.pilha.push(MudarTracos([a], faixa=v.receita.faixa + 1))
    escalas = tempo.faixas[a.receita.faixa].escalas
    assert escalas.travado(a) and escalas.escala(a).comum and tempo.itens[a].transform().isIdentity()
    janela.projeto.pilha.undo()
    faixa = tempo.faixas[v.receita.faixa]
    assert faixa.escalas.escala(a).comum
    assert tempo.itens[a].getViewBox() is faixa.getViewBox() and tempo.itens[a] in faixa.items      # de volta nela


# ------------------------------------------------------------------ o tempo próprio

def test_o_traco_destravado_tem_o_seu_tempo(janela, qtbot, juntos):
    fonte, v, a, tempo = juntos
    faixa = tempo.faixas[v.receita.faixa]
    caixa, escalas, eixo_t = faixa.getViewBox(), faixa.escalas, faixa.getAxis("bottom")
    janela.selecao.definir([a])
    assert "tempo" in tempo.acao_destravar.toolTip()               # a dica diz que o tempo também fica só dele
    tempo.acao_destravar.trigger()
    x, y = caixa.viewRange()
    roda(tempo.grafico, caixa, Qt.KeyboardModifier.NoModifier)     # a roda: o zoom do tempo, só no da corrente
    assert caixa.viewRange() == [pytest.approx(x), pytest.approx(y)]
    e = escalas.escala(a)
    assert e.x.k == pytest.approx(1.2) and e.y.comum and tempo.itens[v].transform().isIdentity()
    assert tempo.chips[a].escala == "solta" and tempo.acao_igualar.isEnabled()
    # O eixo do tempo mostra o tempo dela, com o rótulo na cor dela; a região dela é o trecho dela que aparece.
    propria = (e.x.no_traco(x[0]), e.x.no_traco(x[1]))
    assert propria[1] - propria[0] == pytest.approx((x[1] - x[0]) / 1.2)
    assert eixo_t.range == pytest.approx(list(propria))
    assert faixa.rotulo_x == ("tempo (s)", cor_do_traco(a.receita.cor, aparencia().tema)[0])
    assert tempo.regiao_do_traco(a, *x) == pytest.approx(propria) and tempo.regiao_do_traco(v, *x) == tuple(x)
    assert tempo.regioes_proprias(*x).keys() == {a}
    assert formatar_si(propria[1] - propria[0], "s", 3) in tempo.info.text()     # a informação, no tempo dela
    # A tensão selecionada: o eixo volta ao tempo da vista.
    janela.selecao.definir([v])
    assert eixo_t.range == pytest.approx(list(x)) and faixa.rotulo_x == ("tempo (s)", None)
    assert formatar_si(x[1] - x[0], "s", 3) in tempo.info.text()
    # O zoom e o pan do tempo da vista (com a tensão, travada) não tiram a corrente do lugar na tela.
    tela = [no_tempo_da_tela(caixa, escalas.escala(a), t) for t in (0.1, 0.2, 0.3)]
    roda(tempo.grafico, caixa, Qt.KeyboardModifier.NoModifier, passos=2)
    roda(tempo.grafico, caixa, Qt.KeyboardModifier.ShiftModifier)
    novo = caixa.viewRange()[0]
    assert novo != pytest.approx(x)
    assert [no_tempo_da_tela(caixa, escalas.escala(a), t) for t in (0.1, 0.2, 0.3)] == pytest.approx(tela, abs=0.01)
    assert tempo.regiao_do_traco(a, *novo) == pytest.approx(propria)
    # "Mesma escala": de volta ao tempo da vista, e o rótulo perde a cor.
    janela.selecao.definir([a])
    tempo.acao_igualar.trigger()
    assert escalas.escala(a).comum and eixo_t.range == pytest.approx(list(novo)) and faixa.rotulo_x[1] is None


def test_o_tempo_proprio_numa_vista_de_varias_faixas(janela, qtbot, separados):
    fonte, v, a, tempo = separados
    da_tensao, da_corrente = tempo.faixas[v.receita.faixa].getViewBox(), tempo.faixas[a.receita.faixa].getViewBox()
    janela.selecao.definir([a])
    tempo.acao_destravar.trigger()
    x = da_tensao.viewRange()[0]
    roda(tempo.grafico, da_corrente, Qt.KeyboardModifier.NoModifier)   # na faixa dela: só o tempo dela muda
    assert da_tensao.viewRange()[0] == pytest.approx(x) and da_corrente.viewRange()[0] == pytest.approx(x)
    propria = tempo.regiao_do_traco(a, *x)
    assert propria[1] - propria[0] == pytest.approx((x[1] - x[0]) / 1.2)
    # O eixo do tempo fica embaixo da última faixa: ele mostra o tempo do selecionado, qualquer que seja a faixa.
    ultima = tempo.faixas[max(tempo.faixas)]
    assert ultima.getAxis("bottom").range == pytest.approx(list(propria)) and ultima.rotulo_x[1] is not None
    # A roda na faixa da tensão, sem seleção: o tempo da vista (as duas faixas); a corrente fica onde está.
    janela.selecao.limpar()
    assert ultima.getAxis("bottom").range == pytest.approx(list(x)) and ultima.rotulo_x[1] is None
    roda(tempo.grafico, da_tensao, Qt.KeyboardModifier.NoModifier, passos=2)
    novo = da_tensao.viewRange()[0]
    assert novo != pytest.approx(x) and da_corrente.viewRange()[0] == pytest.approx(novo)
    assert tempo.regiao_do_traco(a, *novo) == pytest.approx(propria)


def test_as_medidas_e_o_espectro_usam_o_trecho_do_traco(janela, qtbot, juntos):
    fonte, v, a, tempo = juntos
    caixa = tempo.faixas[v.receita.faixa].getViewBox()
    janela.selecao.definir([a])
    tempo.acao_destravar.trigger()
    roda(tempo.grafico, caixa, Qt.KeyboardModifier.NoModifier, passos=4)
    x = caixa.viewRange()[0]
    propria = tempo.regiao_do_traco(a, *x)
    tabela = janela.area.tabela_de_medidas
    qtbot.waitUntil(lambda: tabela.pedido is not None and a in tabela.pedido.por_traco, timeout=10_000)
    medidas = {m.traco: m for m in tabela.medidas}
    assert (medidas[a].inicio_s, medidas[a].fim_s) == pytest.approx(propria)
    assert (medidas[v].inicio_s, medidas[v].fim_s) == pytest.approx(x)

    def amostras(inicio, fim):
        return int(min(max(round(fim * FS), 0), N)) - int(min(max(round(inicio * FS), 0), N))

    assert medidas[a].medidas.n_amostras == amostras(*propria) < medidas[v].medidas.n_amostras == amostras(*x)
    linha = list(medidas).index(a)
    regiao = tabela.tabela.item(linha, 1)
    assert "tempo próprio" in regiao.text() and "tempo próprio" not in tabela.tabela.item(1 - linha, 1).text()
    assert "→" in regiao.toolTip()

    # O espectro da vista de tempo: o trecho da corrente é o dela.
    janela.acoes["espectro"].trigger()
    espectro = janela.area.widget_da_vista(janela.vista_ativa())
    pedidos, _ = espectro._trechos()
    trechos = {traco: trecho for traco, _, trecho in pedidos}
    assert trechos[a].n_amostras == amostras(*propria) and trechos[v].n_amostras == amostras(*x)
    assert trechos[a].inicio == int(min(max(round(propria[0] * FS), 0), N))


def test_ajustar_poe_o_traco_destravado_no_tempo_inteiro(janela, qtbot, juntos):
    fonte, v, a, tempo = juntos
    caixa = tempo.faixas[v.receita.faixa].getViewBox()
    janela.selecao.definir([a])
    tempo.acao_destravar.trigger()
    roda(tempo.grafico, caixa, Qt.KeyboardModifier.NoModifier, passos=3)
    roda(tempo.grafico, caixa, Qt.KeyboardModifier.ShiftModifier)
    assert not tempo.faixas[v.receita.faixa].escalas.escala(a).x.comum
    tempo.ajustar()
    x = caixa.viewRange()[0]
    assert tempo.regiao_do_traco(a, *x) == pytest.approx(x, rel=1e-6, abs=1e-9)   # a captura inteira, como a tensão


def test_o_minimapa_segue_o_tempo_do_traco_dele(janela, qtbot, juntos):
    fonte, v, a, tempo = juntos
    caixa = tempo.faixas[v.receita.faixa].getViewBox()
    assert tempo._modelo_do_minimapa is tempo.itens[v]              # o minimapa é o do primeiro traço
    janela.selecao.definir([v])
    tempo.acao_destravar.trigger()
    roda(tempo.grafico, caixa, Qt.KeyboardModifier.NoModifier, passos=3)
    x = caixa.viewRange()[0]
    propria = tempo.regiao_do_traco(v, *x)
    assert caixa.viewRange()[0] == pytest.approx(x) and tempo.minimapa.janela == pytest.approx(propria)
    # Arrastar a janela do minimapa anda o tempo da tensão (destravada); a vista fica.
    alvo = (propria[0] + 0.05, propria[1] + 0.05)
    tempo.minimapa.janelaPedida.emit(*alvo)
    assert caixa.viewRange()[0] == pytest.approx(x)
    assert tempo.regiao_do_traco(v, *x) == pytest.approx(alvo) and tempo.minimapa.janela == pytest.approx(alvo)
    # Travada de novo (com o tempo que ganhou), ela anda com a vista: o minimapa move a vista.
    tempo.acao_destravar.trigger()
    alvo = (alvo[0] - 0.02, alvo[1] - 0.02)
    tempo.minimapa.janelaPedida.emit(*alvo)
    assert caixa.viewRange()[0] != pytest.approx(x) and tempo.regiao_do_traco(v, *caixa.viewRange()[0]) == \
        pytest.approx(alvo)


# ------------------------------------------------------------------ a vista de espectro

def test_no_espectro_o_eixo_e_o_cadeado_seguem_o_traco(janela, qtbot, juntos):
    fonte, v, a, tempo = juntos
    janela.acoes["espectro"].trigger()
    espectro = janela.area.widget_da_vista(janela.vista_ativa())
    qtbot.waitUntil(lambda: len([r for r in espectro.resultados if r.desenho is not None]) == 2, timeout=10_000)
    vb, escalas = espectro.grafico.getViewBox(), espectro.escalas
    tema = aparencia().tema
    assert espectro._rotulo_desenhado[1] == cor_do_traco(v.receita.cor, tema)[0]
    rotulo_da_tensao = espectro._rotulo_desenhado[0]
    janela.selecao.definir([a])
    assert espectro._rotulo_desenhado == (espectro._rotulo_y(), cor_do_traco(a.receita.cor, tema)[0])
    assert espectro._rotulo_desenhado[0] != rotulo_da_tensao and "A" in espectro._rotulo_desenhado[0]

    espectro.acao_destravar.trigger()
    assert not escalas.travado(a) and espectro.chips[a].escala == "solta"
    y = vb.viewRange()[1]
    vb.scaleBy(y=0.5)                                               # o zoom do Y (como a roda): só na corrente
    assert vb.viewRange()[1] == pytest.approx(y) and escalas.escala(a).y.k == pytest.approx(2.0)
    assert espectro.curvas[v].transform().isIdentity()
    x = vb.viewRange()[0]
    vb.scaleBy(x=0.5)                                               # a frequência é uma só: o zoom dela é da caixa
    assert vb.viewRange()[0] != pytest.approx(x) and escalas.escala(a).x.comum
    # As marcas da tensão (o piso, do primeiro traço) ficam; destravada e ampliada, a tensão as leva junto.
    janela.selecao.definir([v])
    espectro.acao_destravar.trigger()
    vb.translateBy(y=10.0)
    qtbot.waitUntil(lambda: not escalas.escala(v).comum)
    qtbot.wait(20)
    (r,) = [r for r in espectro.resultados if r.traco is v]
    piso = next(m for m in espectro._marcas_desenhadas if hasattr(m, "label") and m.label is not None)
    assert piso.value() == pytest.approx(escalas.escala(v).y.na_vista(r.marcas.piso_db))
    # Mudar o que o Y mede volta todos à escala comum.
    espectro._mudar(escala="rms")
    qtbot.waitUntil(lambda: espectro.opcoes_calculadas == espectro.opcoes, timeout=10_000)
    assert escalas.escala(v).comum and escalas.escala(a).comum


def test_o_chip_mostra_o_cadeado(qapp):
    chip = ChipDeTraco("corrente", 1)
    largura = chip.sizeHint().width()
    chip.definir(escala="solta")
    assert chip.sizeHint().width() > largura and "destravada" in chip.toolTip()
    chip.definir(escala="propria")
    assert "travada" in chip.toolTip()
    chip.definir(escala=None)
    assert chip.sizeHint().width() == largura and chip.toolTip() == ""
    with pytest.raises(ValueError):
        chip.definir(escala="outra")
