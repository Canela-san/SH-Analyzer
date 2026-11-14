"""O botão do meio na vista de tempo (a roda apertada): arrastar em cima de um traço move só ele (o offset e o
deslocamento no tempo, um passo de desfazer por arrasto); em outro lugar, move a vista inteira sem mudar as escalas;
um clique rápido põe o 0 do eixo Y no meio da faixa (e tira o offset do traço clicado ou dos selecionados). Sem
tela: com eventos falsos na caixa e com eventos de mouse de verdade pela cena."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.modelo.comandos import MudarTracos  # noqa: E402

FS = 200_000


class Arrasto:
    """Um passo de arrasto do PyQtGraph, falso: as posições nas unidades da vista."""

    def __init__(self, caixa, inicio, anterior, atual, *, comeca=False, termina=False):
        self._caixa = caixa
        self._inicio, self._anterior, self._atual = (caixa.mapFromView(QPointF(*p)) for p in (inicio, anterior, atual))
        self._comeca, self._termina = comeca, termina

    def button(self):
        return Qt.MouseButton.MiddleButton

    def buttonDownPos(self):
        return self._inicio

    def lastPos(self):
        return self._anterior

    def pos(self):
        return self._atual

    def isStart(self):
        return self._comeca

    def isFinish(self):
        return self._termina

    def accept(self):
        pass


class Clique:
    def __init__(self, caixa, ponto):
        self._pos = caixa.mapFromView(QPointF(*ponto))

    def button(self):
        return Qt.MouseButton.MiddleButton

    def pos(self):
        return self._pos

    def double(self):
        return False

    def modifiers(self):
        return Qt.KeyboardModifier.NoModifier

    def accept(self):
        pass


def arrastar(caixa, pontos):
    """Um arrasto falso pelos ``pontos`` (unidades da vista, mapeadas com a vista de antes do arrasto)."""
    passos = [caixa.mapFromView(QPointF(*p)) for p in pontos]
    pontos_item = [(caixa.mapToView(q).x(), caixa.mapToView(q).y()) for q in passos]
    for k in range(1, len(pontos_item)):
        evento = Arrasto(caixa, pontos_item[0], pontos_item[k - 1], pontos_item[k], comeca=k == 1,
                         termina=k == len(pontos_item) - 1)
        # Mapeia de novo a cada passo: com a vista andando, o ponto do mouse em pixels fica o mesmo.
        evento._inicio, evento._anterior, evento._atual = passos[0], passos[k - 1], passos[k]
        caixa.mouseDragEvent(evento)


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


def test_arrastar_um_traco_move_so_ele_num_passo_de_desfazer(janela, plotado, qtbot):
    fonte, a, b, vista, caixa = plotado
    faixa_antes = [v for r in caixa.viewRange() for v in r]
    contagem = janela.projeto.pilha.count()
    # O pico de 60 Hz do canal 0, longe do canal 1 (que tem a metade da amplitude).
    x, y = ponto_no_traco(fonte, 0, 0.05 + 1 / 240)
    assert vista.traco_em(caixa, x, y) is a
    arrastar(caixa, [(x, y), (x + 0.001, y + 0.1), (x + 0.002, y + 0.3)])
    assert a.receita.offset == pytest.approx(0.3, rel=1e-6) and a.receita.deslocamento_s == pytest.approx(0.002)
    assert b.receita.offset == 0 and b.receita.deslocamento_s == 0               # só ele
    assert [v for r in caixa.viewRange() for v in r] == pytest.approx(faixa_antes)   # a vista não andou
    assert janela.projeto.pilha.count() == contagem + 1 and janela.projeto.pilha.undoText() == f"Mover {a.nome}"
    item = vista.itens[a]
    assert item._t0 == pytest.approx(0.002) and "2 ms" in vista.chips[a].resumo
    arrastar(caixa, [(x + 0.002, y + 0.3), (x + 0.002, y + 0.5)])                  # outro arrasto: outro passo
    assert janela.projeto.pilha.count() == contagem + 2
    janela.projeto.pilha.undo()
    janela.projeto.pilha.undo()
    assert a.receita.offset == 0 and a.receita.deslocamento_s == 0


def test_arrastar_fora_dos_tracos_move_a_vista_sem_mudar_a_escala(janela, plotado):
    fonte, a, b, vista, caixa = plotado
    (x0, x1), (y0, y1) = caixa.viewRange()
    assert vista.traco_em(caixa, 0.055, y1 * 0.95) is None
    contagem = janela.projeto.pilha.count()
    arrastar(caixa, [(0.055, y1 * 0.95), (0.056, y1 * 0.95 - 0.2), (0.057, y1 * 0.95 - 0.4)])
    (n0, n1), (m0, m1) = caixa.viewRange()
    assert (n1 - n0, m1 - m0) == pytest.approx((x1 - x0, y1 - y0))               # a mesma escala
    assert n0 == pytest.approx(x0 - 0.002, abs=1e-6) and m0 == pytest.approx(y0 + 0.4, abs=1e-6)  # andou
    assert janela.projeto.pilha.count() == contagem and a.receita.offset == 0     # a vista, não os dados
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
    inicio = pixel(x, y)
    evento(QEvent.Type.MouseButtonPress, inicio, Qt.MouseButton.MiddleButton)
    for k in range(1, 6):
        evento(QEvent.Type.MouseMove, inicio + QPoint(0, -8 * k), Qt.MouseButton.MiddleButton)
    evento(QEvent.Type.MouseButtonRelease, inicio + QPoint(0, -40), Qt.MouseButton.NoButton)
    assert a.receita.offset > 0 and b.receita.offset == 0                          # subiu só o traço a
    assert janela.projeto.pilha.undoText() == f"Mover {a.nome}"
    # Um clique rápido em cima dele: volta ao 0.
    chamadas = []
    caixa.centroPedido.connect(lambda cx, cy: chamadas.append((cx, cy, vista.traco_em(caixa, cx, cy))))
    alvo = pixel(x, y + a.receita.offset)
    evento(QEvent.Type.MouseButtonPress, alvo, Qt.MouseButton.MiddleButton)
    evento(QEvent.Type.MouseButtonRelease, alvo, Qt.MouseButton.NoButton)
    assert chamadas, "o clique rápido não chegou à caixa"
    assert a.receita.offset == 0, (chamadas, x, y)
