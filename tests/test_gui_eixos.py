"""Os números dos eixos acompanham os dados (o pedido do usuário, 15/11/2026: "tenho que saber a tensão e o tempo que
estou olhando"). Com o prefixo do SI automático, o ``setRange`` do PyQtGraph conta com o ``updateAutoSIPrefix`` para
invalidar o desenho do eixo; o do ``EixoDoTema`` só o fazia quando o prefixo mudava, e os números ficavam parados no
zoom, no pan e na mudança de escala. Aqui, os números conferidos são os pintados (``EixoDoTema.numeros``), em cada
vista. Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from mouse_de_verdade import arrastar  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.graficos.faixa import EixoDoTema  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402

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
def tempo(janela, qtbot, tmp_path):
    t = np.arange(FS) / FS                                               # 1 s de 60 Hz com 9 kHz
    caminho = escrever_bin(tmp_path / "a.bin", [np.sin(2 * np.pi * 60 * t) + 0.1 * np.sin(2 * np.pi * 9_000 * t),
                                                 np.cos(2 * np.pi * 60 * t)], grandezas=(0, 0), versao=9)
    (fonte,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    janela.area.plotar_canal(fonte, 0)
    vista = janela.area.widget_da_vista(janela.vista_ativa())
    return vista, next(iter(vista.faixas.values()))


def numeros(grafico, eixo) -> list[str]:
    """Os números do eixo depois de o gráfico pintar."""
    grafico.grab()
    return eixo.numeros


def test_o_eixo_refaz_os_numeros_sem_mudar_o_prefixo(qapp):
    import pyqtgraph as pg

    grafico = pg.PlotWidget(axisItems={"left": EixoDoTema("left")})
    grafico.resize(300, 400)
    eixo = grafico.getAxis("left")
    eixo.definir_rotulo("tensão", "V")
    grafico.setYRange(0, 10, padding=0)
    antes = numeros(grafico, eixo)
    grafico.setYRange(20, 30, padding=0)                                 # o mesmo prefixo (V)
    depois = numeros(grafico, eixo)
    assert eixo.rotulo == "tensão (V)" and antes != depois
    assert depois and all(20 <= float(n) <= 30 for n in depois)


def test_na_vista_de_tempo_o_zoom_a_escala_e_o_arrasto_do_meio_mudam_os_numeros(janela, tempo, qtbot):
    vista, faixa = tempo
    caixa, x, y = faixa.getViewBox(), faixa.getAxis("bottom"), faixa.getAxis("left")
    caixa.setRange(xRange=(0.2, 0.4), yRange=(-1.0, 1.0), padding=0)
    antes = numeros(vista.grafico, x), numeros(vista.grafico, y), x.rotulo

    caixa.setXRange(0.25, 0.35, padding=0)                               # o zoom no tempo, no mesmo prefixo
    assert x.rotulo == antes[2] and numeros(vista.grafico, x) != antes[0]

    caixa.scaleBy(y=0.5)                                                 # a escala do Y (o Ctrl + roda)
    assert numeros(vista.grafico, y) != antes[1]

    meio = vista.grafico.mapFromScene(caixa.sceneBoundingRect().center())
    pan = numeros(vista.grafico, x), numeros(vista.grafico, y), caixa.viewRange()
    arrastar(vista.grafico.viewport(), meio, meio + QPoint(80, -40), Qt.MouseButton.MiddleButton)
    (x0, _x1), (y0, _y1) = caixa.viewRange()                             # o botão do meio: as duas direções
    assert x0 < pan[2][0][0] and y0 < pan[2][1][0]
    assert numeros(vista.grafico, x) != pan[0] and numeros(vista.grafico, y) != pan[1]


@pytest.mark.parametrize("tipo", ["espectro", "bandas", "espectrograma", "harmonicos"])
def test_nas_vistas_de_frequencia_o_zoom_muda_os_numeros(janela, tempo, qtbot, tipo):
    janela.area.abrir_analise(tipo)
    w = janela.area.widget_da_vista(janela.vista_ativa())
    pronta = (lambda: bool(w.resultados)) if tipo == "espectro" else (lambda: w.resultado is not None)
    qtbot.waitUntil(pronta, timeout=10_000)
    caixa, x, y = w.grafico.getViewBox(), w.grafico.getAxis("bottom"), w.grafico.getAxis("left")
    # O resultado chega antes de o gráfico ganhar a faixa dele (sob carga, a CI mediu os dois eixos vazios).
    qtbot.waitUntil(lambda: bool(numeros(w.grafico, x)) and bool(numeros(w.grafico, y)), timeout=10_000)
    antes = numeros(w.grafico, x), numeros(w.grafico, y)
    (x0, x1), (y0, y1) = caixa.viewRange()
    caixa.setRange(xRange=(x0 + 0.3 * (x1 - x0), x0 + 0.35 * (x1 - x0)),
                   yRange=(y0 + 0.4 * (y1 - y0), y0 + 0.45 * (y1 - y0)), padding=0)
    assert numeros(w.grafico, x) != antes[0]
    assert numeros(w.grafico, y) != antes[1]
