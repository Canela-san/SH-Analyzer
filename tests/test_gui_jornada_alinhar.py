"""O alinhamento de traços na janela (TR-07, F5.9): duas capturas do mesmo sinal, a segunda com um atraso conhecido
(fracionário), na mesma vista; o "Alinhar…" do inspetor mede o atraso pelas amostras (as duas maneiras), o
"Aplicar" muda o deslocamento num passo de desfazer, e o Alt + arrastar anda o traço no tempo, um gesto um passo.
Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from sh_analyzer_gui.graficos.faixa import CaixaDaFaixa  # noqa: E402
from test_gui_vista_tempo import TAXA_TOTAL, abrir, janela  # noqa: E402,F401

TAXA = TAXA_TOTAL / 2
ATRASO = 146.9 / TAXA                 # 0,7345 ms: 146,9 amostras


def _sinal(t):
    return 0.1 * np.sin(2 * np.pi * 60 * t) + 0.01 * np.sin(2 * np.pi * 3e3 * t + 0.4)


def _captura(pasta, nome, atraso):
    pasta.mkdir(parents=True, exist_ok=True)
    t = np.arange(60_000) / TAXA
    v = _sinal(t - atraso)
    return escrever_bin(pasta / nome, [v, 0.5 * v], grandezas=(0, 0), versao=9)


def _vista_com_os_dois(janela, qtbot, tmp_path):  # noqa: F811
    f1 = abrir(janela, qtbot, _captura(tmp_path, "a.bin", 0.0))
    f2 = abrir(janela, qtbot, _captura(tmp_path, "b.bin", ATRASO))
    referencia = janela.area.plotar_canal(f1, 0)
    vista = janela.vista_ativa()
    atrasado = janela.area.plotar_canal(f2, 0, vista)
    return vista, referencia, atrasado


def _esperar_a_medida(qtbot, dialogo):
    qtbot.waitUntil(lambda: dialogo._tarefa is None and not dialogo._espera.isActive(), timeout=20_000)
    assert dialogo.alinhamento is not None, dialogo.resultado.text()
    return dialogo.alinhamento


def test_alinhar_pelo_inspetor_com_desfazer(janela, qtbot, tmp_path):  # noqa: F811
    vista, referencia, atrasado = _vista_com_os_dois(janela, qtbot, tmp_path)
    janela.selecao.definir([atrasado])
    inspetor = janela.inspetor.do_traco
    assert inspetor.alinhar.isEnabled()
    qtbot.mouseClick(inspetor.alinhar, Qt.MouseButton.LeftButton)
    dialogo = janela.area.dialogo_de_alinhar
    assert dialogo is not None and dialogo.isVisible() and dialogo.referencia_escolhida() is referencia
    # A correlação cruzada: o atraso pelas amostras, abaixo de um vigésimo de amostra (a quantização do ADC é o ruído).
    feito = _esperar_a_medida(qtbot, dialogo)
    assert feito.metodo == "correlacao" and abs(feito.atraso_s - ATRASO) * TAXA < 0.05 and feito.qualidade > 0.999
    assert "Atraso medido" in dialogo.resultado.text() and dialogo.aplicar.isEnabled()
    # O cruzamento por zero, de novo sozinho.
    dialogo.metodo.escolher(1)
    zero = _esperar_a_medida(qtbot, dialogo)
    assert zero.metodo == "zero" and abs(zero.atraso_s - ATRASO) * TAXA < 0.3 and zero.casados >= 10
    # Aplicar: o deslocamento que alinha, num passo de desfazer.
    qtbot.mouseClick(dialogo.aplicar, Qt.MouseButton.LeftButton)
    assert atrasado.receita.deslocamento_s == pytest.approx(-zero.atraso_s)
    pilha = janela.projeto.pilha
    assert pilha.undoText() == f"Alinhar {atrasado.nome} a {referencia.nome}"
    # Alinhado, a medida de novo dá zero.
    dialogo = janela.area.alinhar(atrasado)
    assert abs(_esperar_a_medida(qtbot, dialogo).atraso_s) * TAXA < 0.05
    dialogo.close()
    janela.acoes["desfazer"].trigger()
    assert atrasado.receita.deslocamento_s == 0.0


def test_os_trechos_dos_cursores_e_os_problemas(janela, qtbot, tmp_path):  # noqa: F811
    vista, referencia, atrasado = _vista_com_os_dois(janela, qtbot, tmp_path)
    w = janela.area.widget_da_vista(vista)
    w.ligar_cursores(True)
    w.cursores = [0.05, 0.1]
    dialogo = janela.area.alinhar(atrasado)
    _esperar_a_medida(qtbot, dialogo)
    assert dialogo.trecho.text().startswith("entre os cursores")
    assert dialogo.busca.valor == pytest.approx(0.005)
    # Uma busca maior que o que há do traço: a referência encolhe, e o resultado avisa.
    dialogo.busca.definir_valor(0.06)
    dialogo.busca.valorMudou.emit(0.06)
    feito = _esperar_a_medida(qtbot, dialogo)
    assert "a referência foi lida de" in feito.aviso and abs(feito.atraso_s - ATRASO) * TAXA < 0.05
    dialogo.busca.definir_valor(0.2)
    dialogo.busca.valorMudou.emit(0.2)
    qtbot.waitUntil(lambda: dialogo._tarefa is None and not dialogo._espera.isActive(), timeout=20_000)
    assert dialogo.alinhamento is None and "diminua a busca" in dialogo.resultado.text()
    assert not dialogo.aplicar.isEnabled()
    dialogo.close()
    # Sem outro traço na vista, não há referência.
    sozinho = janela.area.nova_vista()
    t = janela.area.plotar_canal(janela.projeto.fontes[0], 1, sozinho)
    dialogo = janela.area.alinhar(t)
    dialogo.medir()
    assert "Não há outro traço" in dialogo.resultado.text()
    dialogo.close()


class _Arrasto:
    """O pedaço do ``MouseDragEvent`` do PyQtGraph que a caixa lê."""

    def __init__(self, de, para, fase, alt=True):
        self.de, self.para, self.fase, self.alt = de, para, fase, alt

    def button(self):
        return Qt.MouseButton.LeftButton

    def modifiers(self):
        return Qt.KeyboardModifier.AltModifier if self.alt else Qt.KeyboardModifier.NoModifier

    def isStart(self):
        return self.fase == "inicio"

    def isFinish(self):
        return self.fase == "fim"

    def buttonDownScenePos(self):
        return self.de

    def scenePos(self):
        return self.para

    def accept(self):
        pass


def test_alt_e_arrastar_anda_o_traco_no_tempo(janela, qtbot, tmp_path):  # noqa: F811
    vista, referencia, atrasado = _vista_com_os_dois(janela, qtbot, tmp_path)
    w = janela.area.widget_da_vista(vista)
    caixa = w.itens[atrasado].getViewBox()
    assert isinstance(caixa, CaixaDaFaixa)
    w.mostrar_tempo(0.0, 0.05)
    # O começo do arrasto em cima do traço atrasado, num instante em que ele está longe do outro.
    t = 0.0123
    y = float(_sinal(np.array([t - ATRASO]))[0])
    qtbot.waitUntil(lambda: w.traco_em(caixa, t, y) is atrasado, timeout=10_000)     # desenhado na janela nova
    de = caixa.mapViewToScene(QPointF(t, y))
    passos = [caixa.mapViewToScene(QPointF(t + d, y)) for d in (0.001, 0.002, 0.003)]
    w.selecao.definir([atrasado])
    caixa.mouseDragEvent(_Arrasto(de, de, "inicio"))
    caixa.mouseDragEvent(_Arrasto(de, passos[0], "meio", alt=False))       # o Alt pode ser solto no meio
    caixa.mouseDragEvent(_Arrasto(de, passos[1], "meio"))
    caixa.mouseDragEvent(_Arrasto(de, passos[2], "fim"))
    assert atrasado.receita.deslocamento_s == pytest.approx(0.003, rel=1e-6)
    assert referencia.receita.deslocamento_s == 0.0
    pilha = janela.projeto.pilha
    assert pilha.undoText() == f"Deslocar {atrasado.nome} no tempo"
    janela.acoes["desfazer"].trigger()                 # o gesto inteiro, um passo
    assert atrasado.receita.deslocamento_s == 0.0
    # Começado fora de um traço, nada anda (e o gesto não vira pan).
    longe = caixa.mapViewToScene(QPointF(t, 5.0))
    antes = w.janela_de_tempo()
    caixa.mouseDragEvent(_Arrasto(longe, longe, "inicio"))
    caixa.mouseDragEvent(_Arrasto(longe, passos[2], "fim"))
    assert w.janela_de_tempo() == antes and atrasado.receita.deslocamento_s == 0.0
