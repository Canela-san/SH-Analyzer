"""O que deixa a vista de tempo fluida (docs/gui-progress.md, 14/11): a sincronização incremental das faixas, as
marcas rápidas do eixo (iguais às do PyQtGraph), as medidas de texto guardadas, o traço escondido que não consulta e
o minimapa leve. Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QFont, QImage, QPainter  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.graficos.faixa import EixoDoTema, MedidorDeTexto  # noqa: E402
from sh_analyzer_gui.graficos.minimapa import Minimapa  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.modelo.comandos import MudarTracos, RemoverTracos  # noqa: E402


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
def fonte(janela, qtbot, tmp_path):
    t = np.arange(40_000) / 200_000
    caminho = escrever_bin(tmp_path / "a.bin", [np.sin(2 * np.pi * 60 * t), np.cos(2 * np.pi * 60 * t)], versao=9)
    (f,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: f.piramides is not None, timeout=10_000)
    return f


def linhas_do_layout(vista):
    """A linha de cada faixa no layout, pelo número da faixa."""
    return {n: vista.grafico.ci.items[f][0][0] for n, f in vista.faixas.items()}


def test_as_faixas_mudam_sem_refazer_tudo(janela, fonte):
    tracos = [janela.area.plotar_canal(fonte, k % 2) for k in range(3)]
    for k, t in enumerate(tracos):
        janela.projeto.pilha.push(MudarTracos([t], faixa=k))
    w = janela.area.widget_da_vista(janela.vista_ativa())
    faixas = dict(w.faixas)
    itens = dict(w.itens)
    assert linhas_do_layout(w) == {0: 0, 1: 1, 2: 2}
    vb = w._faixa_principal().getViewBox()
    vb.setXRange(0.05, 0.06, padding=0)
    # A faixa 0 some (o traço dela vai para a 5): as outras ficam, e os itens são os mesmos.
    janela.projeto.pilha.push(MudarTracos([tracos[0]], faixa=5))
    assert sorted(w.faixas) == [1, 2, 5] and w.faixas[1] is faixas[1] and w.faixas[2] is faixas[2]
    assert all(w.itens[t] is itens[t] for t in tracos)
    assert linhas_do_layout(w) == {1: 0, 2: 1, 5: 2}                  # as linhas compactadas, na ordem
    assert w.itens[tracos[0]].getViewBox() is w.faixas[5].getViewBox()
    assert w.janela_de_tempo() == pytest.approx((0.05, 0.06))          # o tempo não mudou
    # A nova principal (a faixa 1) manda no tempo de todas.
    w._faixa_principal().getViewBox().setXRange(0.07, 0.08, padding=0)
    for faixa in w.faixas.values():
        assert faixa.getViewBox().viewRange()[0] == pytest.approx([0.07, 0.08])
    assert not w.faixas[1].getAxis("bottom").isVisible() and w.faixas[5].getAxis("bottom").isVisible()
    # Uma faixa nova no começo reordena; tirar um traço tira a faixa vazia.
    janela.projeto.pilha.push(MudarTracos([tracos[2]], faixa=0))
    assert linhas_do_layout(w) == {0: 0, 1: 1, 5: 2}
    janela.projeto.pilha.push(RemoverTracos(janela.vista_ativa(), [tracos[1]]))
    assert sorted(w.faixas) == [0, 5] and tracos[1] not in w.itens
    for _ in range(3):                                                  # tirar, faixa 0, faixa 5
        janela.projeto.pilha.undo()
    assert sorted(w.faixas) == [0, 1, 2] and linhas_do_layout(w) == {0: 0, 1: 1, 2: 2}
    assert all(w.itens[t].getViewBox() is w.faixas[k].getViewBox() for k, t in enumerate(tracos))


def test_o_traco_escondido_nao_consulta(janela, fonte, qtbot):
    traco = janela.area.plotar_canal(fonte, 0)
    w = janela.area.widget_da_vista(janela.vista_ativa())
    item = w.itens[traco]
    qtbot.waitUntil(lambda: item.recalculos > 0)
    janela.projeto.pilha.push(MudarTracos([traco], visivel=False))
    antes = item.recalculos
    vb = w._faixa_principal().getViewBox()
    for k in range(5):
        vb.setXRange(0.01 * k, 0.01 * k + 0.02, padding=0)
        item.recalcular()
    assert item.recalculos == antes
    janela.projeto.pilha.push(MudarTracos([traco], visivel=True))
    qtbot.waitUntil(lambda: item.recalculos > antes)                   # ao aparecer, consulta a janela de agora
    assert item.consulta is not None


@pytest.mark.parametrize("inicio, fim, pixels", [(0, 1, 800), (10.0, 10.0006, 1200), (-3.2, 4.1, 300),
                                                  (1e-6, 3e-6, 500), (0, 31.457, 1500), (5, 5.5, 60)])
def test_as_marcas_rapidas_sao_as_do_pyqtgraph(qapp, inicio, fim, pixels):
    import pyqtgraph as pg

    rapido, original = EixoDoTema("bottom"), pg.AxisItem("bottom")
    esperado = original.tickValues(inicio, fim, pixels)
    obtido = rapido.tickValues(inicio, fim, pixels)
    assert len(obtido) == len(esperado)
    for (e1, v1), (e2, v2) in zip(obtido, esperado):
        assert e1 == pytest.approx(e2)
        np.testing.assert_allclose(v1, v2, rtol=0, atol=1e-9 * (fim - inicio))


def test_o_medidor_de_texto_mede_como_o_pintor(qapp):
    imagem = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied)
    pintor = QPainter(imagem)
    fonte = QFont("Inter")
    fonte.setPixelSize(11)
    pintor.setFont(fonte)
    medidor = MedidorDeTexto()
    medidor.setFont(fonte)
    caixa = QRectF(0, 0, 100, 100)
    for texto in ("10,0005", "−3,2", "1e-06", "123456"):
        esperado = pintor.boundingRect(caixa, Qt.AlignmentFlag.AlignCenter, texto)
        obtido = medidor.boundingRect(caixa, Qt.AlignmentFlag.AlignCenter, texto)
        assert obtido.width() == pytest.approx(esperado.width(), abs=1)
        assert obtido.height() == pytest.approx(esperado.height(), abs=1)
        assert medidor.boundingRect(caixa, Qt.AlignmentFlag.AlignCenter, texto) == obtido   # da memória
    pintor.end()


def test_o_minimapa(janela, fonte, qtbot):
    janela.area.plotar_canal(fonte, 0)
    w = janela.area.widget_da_vista(janela.vista_ativa())
    mapa: Minimapa = w.minimapa
    assert mapa.isVisible() and mapa.fim_total == pytest.approx(0.2, abs=1e-4)
    w._faixa_principal().getViewBox().setXRange(0.05, 0.07, padding=0)
    qtbot.waitUntil(lambda: mapa.janela == pytest.approx((0.05, 0.07)), timeout=2000)
    mapa.grab()
    pedidos = []
    mapa.janelaPedida.connect(lambda a, b: pedidos.append((a, b)))
    largura = mapa.width()
    qtbot.mouseClick(mapa, Qt.MouseButton.LeftButton, pos=QPointF(largura * 0.75, 10).toPoint())
    a, b = pedidos[-1]
    assert b - a == pytest.approx(0.02) and (a + b) / 2 == pytest.approx(0.15, abs=0.002)   # centrada no clique
    janela.projeto.pilha.push(MudarTracos([janela.vista_ativa().tracos[0]], visivel=False))
    assert not mapa.isVisible()
