"""O botão do meio na vista de tempo (a roda apertada): arrastar move a vista inteira, em cima de um traço ou não,
sem mudar as escalas e sem mudar os traços; um clique rápido põe o 0 do eixo Y no meio da faixa (e tira o offset do
traço clicado ou dos selecionados). Sem tela: com eventos falsos na caixa e com eventos de mouse de verdade pela
cena.

Também os gestos em cima dos eixos, que o PyQtGraph repassa à caixa com ``axis=``: a roda e o arrasto mexem só
naquele eixo, e o clique não mexe na seleção."""

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
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.modelo.comandos import MudarTracos  # noqa: E402

FS = 200_000


class Arrasto:
    """Um passo de arrasto do PyQtGraph, falso: as posições em pixels da caixa."""

    def __init__(self, caixa, anterior, atual):
        self._caixa, self._anterior, self._atual = caixa, anterior, atual

    def button(self):
        return Qt.MouseButton.MiddleButton

    def lastScenePos(self):
        return self._caixa.mapToScene(self._anterior)

    def scenePos(self):
        return self._caixa.mapToScene(self._atual)

    def accept(self):
        pass


class Clique:
    def __init__(self, caixa, ponto):
        self._cena = caixa.mapToScene(caixa.mapFromView(QPointF(*ponto)))

    def button(self):
        return Qt.MouseButton.MiddleButton

    def scenePos(self):
        return self._cena

    def double(self):
        return False

    def modifiers(self):
        return Qt.KeyboardModifier.NoModifier

    def accept(self):
        pass


def arrastar(caixa, pontos):
    """Um arrasto falso pelos ``pontos`` (unidades da vista, mapeadas para pixels com a vista de antes do arrasto:
    com a vista andando, o ponto do mouse em pixels fica o mesmo)."""
    passos = [caixa.mapFromView(QPointF(*p)) for p in pontos]
    for k in range(1, len(passos)):
        caixa.mouseDragEvent(Arrasto(caixa, passos[k - 1], passos[k]))


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
                           grandezas=(0, 0), versao=9)
    (fonte,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    a = janela.area.plotar_canal(fonte, 0)
    b = janela.area.plotar_canal(fonte, 1)                               # a mesma faixa (as duas em V)
    vista = janela.area.widget_da_vista(janela.vista_ativa())
    caixa = vista.faixas[0].getViewBox()
    caixa.setXRange(0.05, 0.06, padding=0)
    qtbot.waitUntil(lambda: all(i.consulta is not None for i in vista.itens.values()))
    return fonte, a, b, vista, caixa


def ponto_no_traco(fonte, canal, t):
    c = fonte.canal(canal)
    return t, float(np.asarray(c.amostras[int(round(t * FS))]) * c.escala + c.deslocamento)


@pytest.mark.parametrize("onde", ["em cima do traço", "no vazio"])
def test_arrastar_move_a_vista_sem_mudar_a_escala_nem_os_tracos(janela, plotado, onde):
    fonte, a, b, vista, caixa = plotado
    (x0, x1), (y0, y1) = caixa.viewRange()
    if onde == "em cima do traço":
        x, y = ponto_no_traco(fonte, 0, 0.05 + 1 / 240)          # o pico de 60 Hz do canal 0
        assert vista.traco_em(caixa, x, y) is a
    else:
        x, y = 0.055, y1 * 0.95
        assert vista.traco_em(caixa, x, y) is None
    contagem = janela.projeto.pilha.count()
    arrastar(caixa, [(x, y), (x + 0.001, y - 0.2), (x + 0.002, y - 0.4)])
    (n0, n1), (m0, m1) = caixa.viewRange()
    assert (n1 - n0, m1 - m0) == pytest.approx((x1 - x0, y1 - y0))               # a mesma escala
    assert n0 == pytest.approx(x0 - 0.002, abs=1e-6) and m0 == pytest.approx(y0 + 0.4, abs=1e-6)  # andou
    assert janela.projeto.pilha.count() == contagem                              # a vista, não os dados
    assert (a.receita.offset, a.receita.deslocamento_s, b.receita.offset) == (0, 0, 0)
    for faixa in vista.faixas.values():                                          # o tempo, em todas as faixas
        assert faixa.getViewBox().viewRange()[0] == pytest.approx([n0, n1])


def test_o_clique_rapido_poe_o_zero_no_meio(janela, plotado):
    fonte, a, b, vista, caixa = plotado
    janela.projeto.pilha.push(MudarTracos([a], offset=0.7))
    janela.projeto.pilha.push(MudarTracos([b], offset=-0.4))
    caixa.setYRange(0.5, 3.5, padding=0)
    tempo = caixa.viewRange()[0]
    caixa.mouseClickEvent(Clique(caixa, (0.055, 3.4)))                             # no vazio, nada selecionado
    _, (y0, y1) = caixa.viewRange()
    assert (y0, y1) == pytest.approx((-1.5, 1.5)) and caixa.viewRange()[0] == pytest.approx(tempo)
    assert (a.receita.offset, b.receita.offset) == (0.7, -0.4)                     # sem alvo: só a vista
    x, y = ponto_no_traco(fonte, 0, 0.05 + 1 / 240)
    caixa.mouseClickEvent(Clique(caixa, (x, y + 0.7)))                             # em cima do traço a
    assert a.receita.offset == 0 and b.receita.offset == -0.4
    assert janela.projeto.pilha.undoText() == f"Centralizar {a.nome}"
    janela.selecao.definir([b])
    caixa.mouseClickEvent(Clique(caixa, (0.055, 1.4)))                             # no vazio, com b selecionado
    assert b.receita.offset == 0


def test_com_eventos_de_mouse_de_verdade(janela, plotado, qtbot):
    """O caminho real: o botão do meio apertado, arrastado e solto no gráfico, pela cena do PyQtGraph."""
    fonte, a, b, vista, caixa = plotado
    porta = vista.grafico.viewport()

    def pixel(x, y):
        cena = caixa.mapViewToScene(QPointF(x, y))
        return vista.grafico.mapFromScene(cena)

    def evento(tipo, ponto: QPoint, botoes):
        global_ = porta.mapToGlobal(ponto)
        botao = Qt.MouseButton.MiddleButton if tipo != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
        QApplication.sendEvent(porta, QMouseEvent(tipo, QPointF(ponto), QPointF(global_), botao, botoes,
                                                  Qt.KeyboardModifier.NoModifier))

    x, y = ponto_no_traco(fonte, 0, 0.05 + 1 / 720)                # a 30°: 0,5 V (o b está em 0,25 V)
    assert vista.traco_em(caixa, x, y) is a
    (x0, x1), (y0, y1) = caixa.viewRange()
    contagem = janela.projeto.pilha.count()
    inicio = pixel(x, y)
    evento(QEvent.Type.MouseButtonPress, inicio, Qt.MouseButton.MiddleButton)
    for k in range(1, 6):
        evento(QEvent.Type.MouseMove, inicio + QPoint(0, -8 * k), Qt.MouseButton.MiddleButton)
    evento(QEvent.Type.MouseButtonRelease, inicio + QPoint(0, -40), Qt.MouseButton.NoButton)
    (n0, n1), (m0, m1) = caixa.viewRange()
    assert m0 < y0 and m1 - m0 == pytest.approx(y1 - y0)                         # a vista desceu: os dados subiram
    assert (n0, n1) == pytest.approx((x0, x1))
    assert janela.projeto.pilha.count() == contagem and a.receita.offset == 0     # o traço não mudou
    # Um clique rápido em cima de um traço com offset: o offset volta a 0.
    janela.projeto.pilha.push(MudarTracos([a], offset=0.3))
    qtbot.waitUntil(lambda: vista.traco_em(caixa, x, y + 0.3) is a)
    chamadas = []
    caixa.centroPedido.connect(lambda cx, cy: chamadas.append((cx, cy, vista.traco_em(caixa, cx, cy))))
    alvo = pixel(x, y + 0.3)
    evento(QEvent.Type.MouseButtonPress, alvo, Qt.MouseButton.MiddleButton)
    evento(QEvent.Type.MouseButtonRelease, alvo, Qt.MouseButton.NoButton)
    assert chamadas, "o clique rápido não chegou à caixa"
    assert a.receita.offset == 0, (chamadas, x, y)


def test_em_cima_dos_eixos_a_roda_e_o_arrasto_mexem_so_naquele_eixo(janela, plotado):
    """A roda nos números do Y dava ``TypeError`` (``wheelEvent() got an unexpected keyword argument 'axis'``)."""
    fonte, a, b, vista, caixa = plotado
    faixa = vista.faixas[0]
    porta = vista.grafico.viewport()

    def no_eixo(lado) -> QPoint:
        eixo = faixa.getAxis(lado)
        return vista.grafico.mapFromScene(eixo.mapToScene(eixo.boundingRect().center()))

    def roda(ponto: QPoint, passos=1):
        QApplication.sendEvent(porta, QWheelEvent(QPointF(ponto), QPointF(porta.mapToGlobal(ponto)), QPoint(0, 0),
                                                  QPoint(0, 120 * passos), Qt.MouseButton.NoButton,
                                                  Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
                                                  False))

    def mouse(tipo, ponto: QPoint, botao, botoes):
        QApplication.sendEvent(porta, QMouseEvent(tipo, QPointF(ponto), QPointF(porta.mapToGlobal(ponto)), botao,
                                                  botoes, Qt.KeyboardModifier.NoModifier))

    (x0, x1), (y0, y1) = caixa.viewRange()
    roda(no_eixo("left"))                                        # no Y: zoom só no Y, sem o Ctrl
    (n0, n1), (m0, m1) = caixa.viewRange()
    assert (n0, n1) == pytest.approx((x0, x1)) and m1 - m0 == pytest.approx((y1 - y0) / 1.2)
    roda(no_eixo("bottom"))                                      # no tempo: zoom só no tempo
    (p0, p1), (q0, q1) = caixa.viewRange()
    assert p1 - p0 == pytest.approx((x1 - x0) / 1.2) and (q0, q1) == pytest.approx((m0, m1))

    # O botão do meio arrastado nos números do Y: a vista anda só no Y, e nenhum traço muda.
    contagem = janela.projeto.pilha.count()
    inicio = no_eixo("left")
    mouse(QEvent.Type.MouseButtonPress, inicio, Qt.MouseButton.MiddleButton, Qt.MouseButton.MiddleButton)
    for k in range(1, 6):
        mouse(QEvent.Type.MouseMove, inicio + QPoint(6 * k, -8 * k), Qt.MouseButton.NoButton,
              Qt.MouseButton.MiddleButton)
    mouse(QEvent.Type.MouseButtonRelease, inicio + QPoint(30, -40), Qt.MouseButton.MiddleButton,
          Qt.MouseButton.NoButton)
    (r0, r1), (s0, s1) = caixa.viewRange()
    assert (r0, r1) == pytest.approx((p0, p1)) and s0 < q0 and s1 - s0 == pytest.approx(q1 - q0)
    assert janela.projeto.pilha.count() == contagem

    # Um clique nos números não tira a seleção.
    janela.selecao.definir([a])
    ponto = no_eixo("left")
    mouse(QEvent.Type.MouseButtonPress, ponto, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    mouse(QEvent.Type.MouseButtonRelease, ponto, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    assert list(janela.selecao.tracos) == [a]
