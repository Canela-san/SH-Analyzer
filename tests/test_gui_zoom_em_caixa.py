"""O zoom em caixa na vista de tempo (AN-04): ``Z`` (ou o botão) arma, arrastar com o botão esquerdo desenha a caixa
e a faixa passa a mostrar o que estava nela; um zoom feito desarma, e Esc também. E o duplo clique, que não mexe no
zoom. Com eventos de mouse de verdade, pela cena do PyQtGraph. Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from mouse_de_verdade import duplo_clique  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.modelo.comandos import MudarTracos  # noqa: E402

FS = 200_000


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
    t = np.arange(FS // 5) / FS                                          # 0,2 s de 60 Hz
    caminho = escrever_bin(tmp_path / "a.bin", [np.sin(2 * np.pi * 60 * t), 0.5 * np.sin(2 * np.pi * 60 * t)],
                           grandezas=(0, 1), versao=9)
    (fonte,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    a = janela.area.plotar_canal(fonte, 0)
    b = janela.area.plotar_canal(fonte, 1)
    janela.projeto.pilha.push(MudarTracos([b], faixa=a.receita.faixa + 1))  # sem sonda, é V também: outra faixa
    vista = janela.area.widget_da_vista(janela.vista_ativa())
    caixa = vista.faixas[a.receita.faixa].getViewBox()
    caixa.setRange(xRange=(0.0, 0.2), yRange=(-1.5, 1.5), padding=0)
    qtbot.waitUntil(lambda: all(i.consulta is not None for i in vista.itens.values()))
    return a, b, vista, caixa


def arrastar(vista, caixa, de, ate, botao=Qt.MouseButton.LeftButton):
    """Aperta em ``de``, arrasta em passos e solta em ``ate`` (nas unidades da vista), pelo viewport de verdade.

    Com uma pausa entre os passos, como um mouse de verdade: o PyQtGraph ignora movimentos a mais de 100 por segundo
    (``mouseRateLimit``), e um arrasto inteiro dentro disso vira um clique."""
    porta = vista.grafico.viewport()

    def pixel(x, y) -> QPoint:
        return vista.grafico.mapFromScene(caixa.mapViewToScene(QPointF(x, y)))

    def evento(tipo, ponto: QPoint, botoes):
        apertado = botao if tipo != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
        QApplication.sendEvent(porta, QMouseEvent(tipo, QPointF(ponto), QPointF(porta.mapToGlobal(ponto)), apertado,
                                                  botoes, Qt.KeyboardModifier.NoModifier))

    inicio, fim = pixel(*de), pixel(*ate)
    evento(QEvent.Type.MouseButtonPress, inicio, botao)
    for k in range(1, 6):
        QTest.qWait(12)
        evento(QEvent.Type.MouseMove, inicio + (fim - inicio) * k / 5, botao)
    evento(QEvent.Type.MouseButtonRelease, fim, Qt.MouseButton.NoButton)


def test_z_arma_e_o_arrasto_mostra_a_caixa(janela, plotado):
    a, b, vista, caixa = plotado
    outra = vista.faixas[b.receita.faixa].getViewBox()
    _, y_da_outra = outra.viewRange()
    assert not vista.acao_caixa.isChecked()
    vista.acao_caixa.trigger()                                           # o Z
    assert all(f.getViewBox().zoom_em_caixa for f in vista.faixas.values())
    assert vista.grafico.cursor().shape() == Qt.CursorShape.CrossCursor
    arrastar(vista, caixa, (0.05, -0.5), (0.1, 0.75))
    (x0, x1), (y0, y1) = caixa.viewRange()
    assert (x0, x1) == pytest.approx((0.05, 0.1), abs=2e-4) and (y0, y1) == pytest.approx((-0.5, 0.75), abs=0.02)
    assert outra.viewRange()[0] == pytest.approx([x0, x1])              # o tempo, em todas as faixas
    assert outra.viewRange()[1] == pytest.approx(y_da_outra)            # o Y, só na da caixa
    assert not vista.acao_caixa.isChecked()                              # um zoom feito desarma
    assert not any(f.getViewBox().zoom_em_caixa for f in vista.faixas.values())
    assert vista.grafico.cursor().shape() != Qt.CursorShape.CrossCursor
    # Desarmado, o arrasto anda no tempo, como sempre.
    arrastar(vista, caixa, (0.07, 0.0), (0.06, 0.0))
    (n0, n1), (m0, m1) = caixa.viewRange()
    assert n1 - n0 == pytest.approx(x1 - x0) and n0 > x0 and (m0, m1) == pytest.approx((y0, y1))


def test_uma_caixa_baixa_e_zoom_so_no_tempo_e_esc_desarma(janela, plotado):
    a, b, vista, caixa = plotado
    _, (y0, y1) = caixa.viewRange()
    vista.armar_zoom_em_caixa()
    assert vista.acao_caixa.isChecked()
    arrastar(vista, caixa, (0.02, 0.2), (0.12, 0.2 + 1e-4))              # menos de um pixel de altura
    (x0, x1), (m0, m1) = caixa.viewRange()
    assert (x0, x1) == pytest.approx((0.02, 0.12), abs=2e-4) and (m0, m1) == pytest.approx((y0, y1))
    vista.acao_caixa.trigger()
    assert vista.acao_caixa.isChecked()
    desarmar = next(acao for acao in vista.actions() if acao.shortcut().toString() == "Esc")
    desarmar.trigger()
    assert not vista.acao_caixa.isChecked() and not caixa.zoom_em_caixa
    antes = caixa.viewRange()
    arrastar(vista, caixa, (0.05, 0.1), (0.05, 0.1))                     # um clique parado: nada muda
    assert all(eixo == pytest.approx(antes_do_eixo) for eixo, antes_do_eixo in zip(caixa.viewRange(), antes))


def test_o_duplo_clique_nao_mexe_no_zoom_e_seleciona_como_um_clique(janela, plotado):
    """O pedido do usuário (15/11/2026): o duplo clique levava a vista ao mais longe que ela ia (ajustar tudo). Agora
    o zoom fica, e o primeiro clique dele seleciona o traço, como um clique; ajustar tudo é o F."""
    a, b, vista, caixa = plotado
    caixa.setRange(xRange=(0.02, 0.06), yRange=(-0.5, 1.2), padding=0)
    antes = caixa.viewRange()
    no_traco = vista.itens[a].ponto_mais_proximo(0.04)                  # um ponto do traço a, na vista
    ponto = vista.grafico.mapFromScene(caixa.mapViewToScene(no_traco))
    duplo_clique(vista.grafico.viewport(), ponto)
    assert caixa.viewRange() == antes
    assert janela.selecao.tracos == (a,)
    vista.acao_ajustar.trigger()                                         # o F ainda ajusta tudo
    assert caixa.viewRange()[0][1] - caixa.viewRange()[0][0] > 0.15
