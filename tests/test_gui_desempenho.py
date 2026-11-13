"""Os portões de desempenho da interface (docs/gui-plan.md, seção 6.7), medidos nesta máquina.

Ficam fora do conjunto padrão: medem tempo, e o tempo depende da máquina e da carga. Rode com::

    uv run --extra gui-dev pytest --desempenho -n 0 tests/test_gui_desempenho.py

Os limites são os do plano, com folga para um notebook comum; uma piora grande aparece aqui antes de aparecer na tela.
"""

import time

import numpy as np
import pytest
from sh_analyzer_gui.dados.consulta import consultar
from sh_analyzer_gui.dados.piramide import construir

pytestmark = pytest.mark.desempenho

N = 100_000_000          # 250 s de um canal a 400 kS/s, 200 MB em int16


@pytest.fixture(scope="module")
def sinal_grande(tmp_path_factory):
    """100 M amostras int16 num arquivo (memmap), como uma captura: 60 Hz, supraharmônicos e ruído."""
    caminho = tmp_path_factory.mktemp("desempenho") / "sinal.i16"
    rng = np.random.default_rng(1)
    with open(caminho, "wb") as f:
        for i in range(0, N, 10_000_000):
            t = np.arange(i, i + 10_000_000) / 400_000
            fase = np.sin(2 * np.pi * 60 * t)
            y = 20000 * fase + 600 * np.sin(2 * np.pi * 20_000 * t) * (fase < 0) + rng.normal(0, 40, len(t))
            f.write(y.astype(np.int16).tobytes())
    return np.memmap(caminho, dtype=np.int16, mode="r")


def test_g3_piramide_a_200_milhoes_de_amostras_por_segundo(sinal_grande):
    """G3: a pirâmide de uma captura de 1 h (1,44 bilhão de amostras) em < 8 s pede >= 200 M amostras/s."""
    construir(sinal_grande[:10_000_000])            # aquece o cache de páginas
    t = time.perf_counter()
    (p,) = construir(sinal_grande)
    taxa = N / (time.perf_counter() - t)
    assert p.n_amostras == N
    assert taxa >= 200e6, f"{taxa / 1e6:.0f} M amostras/s"


def test_consulta_em_menos_de_1_ms_em_qualquer_zoom(sinal_grande):
    """A consulta de 1 600 colunas, da captura inteira até poucas amostras por coluna, cabe com folga num quadro."""
    (p,) = construir(sinal_grande)
    for largura in (N, 10_000_000, 1_000_000, 300_000, 5_000):
        inicio = (N - largura) // 2
        consultar(p, sinal_grande, inicio, inicio + largura, 1600)        # aquece
        tempos = []
        for _ in range(20):
            t = time.perf_counter()
            consultar(p, sinal_grande, inicio, inicio + largura, 1600)
            tempos.append(time.perf_counter() - t)
        mediana = sorted(tempos)[len(tempos) // 2]
        assert mediana < 1e-3, f"{largura:,} amostras: {mediana * 1e3:.2f} ms"


def test_g1_duas_faixas_sem_tela(request, tmp_path_factory, monkeypatch):
    """G1, a parte que roda sem tela: 2 faixas de uma captura de 5 min (2 canais a 200 kS/s), o percurso de zoom e
    pan do protótipo, p95 <= 16 ms por quadro. Com 8 faixas e numa tela de verdade, rode o protótipo:
    ``python -m sh_analyzer_gui.prototipos.navegar --sintetico 60 --canais 8 --medir``."""
    pytest.importorskip("PySide6")
    pytest.importorskip("pytestqt")
    import tempfile

    import pyqtgraph as pg
    from PySide6.QtWidgets import QApplication
    from sh_analyzer_gui.prototipos import navegar

    qtbot = request.getfixturevalue("qtbot")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path_factory.mktemp("g1")))
    fonte = navegar.gerar_sintetico(5, 2)
    piramides = construir(fonte.amostras, 2)
    layout = pg.GraphicsLayoutWidget()
    layout.resize(1400, 790)
    qtbot.addWidget(layout)
    layout.show()
    qtbot.waitExposed(layout)
    tracos = navegar.montar_faixas(layout, fonte, piramides)
    qtbot.wait(50)
    canal = fonte.canais[0]
    navegar.percorrer_zoom(QApplication.instance(), layout, tracos[0], len(canal.amostras), canal.taxa_hz)  # aquece
    mediana, p95 = navegar.resumo_dos_quadros(
        navegar.percorrer_zoom(QApplication.instance(), layout, tracos[0], len(canal.amostras), canal.taxa_hz))
    assert p95 <= 0.016, f"mediana {mediana * 1e3:.1f} ms, p95 {p95 * 1e3:.1f} ms"


def test_g1_oito_faixas_na_vista_de_tempo(request, tmp_path, monkeypatch):
    """G1 na vista de verdade (F1.5): 8 traços em 8 faixas, com o eixo, a grade e o minimapa do tema, sobre uma
    captura de 1 min (2 canais a 200 kS/s, plotados 4 vezes cada). O percurso de zoom e pan do protótipo, p95 <= 16
    ms por quadro. Sem tela, o número é só uma referência: o G1 vale na tela do usuário."""
    pytest.importorskip("PySide6")
    pytest.importorskip("pytestqt")
    from capturas_sinteticas import escrever_bin
    from dialogos_falsos import DialogosFalsos
    from PySide6.QtWidgets import QApplication
    from sh_analyzer_gui.app import criar_aplicacao
    from sh_analyzer_gui.janela import JanelaPrincipal
    from sh_analyzer_gui.modelo.comandos import MudarTracos
    from sh_analyzer_gui.prototipos import navegar

    qtbot = request.getfixturevalue("qtbot")
    monkeypatch.setenv("SH_ANALYZER_CONFIG", str(tmp_path / "config"))
    n = 60 * 200_000
    t = np.arange(n) / 200_000
    caminho = escrever_bin(tmp_path / "um_minuto.bin", [np.sin(2 * np.pi * 60 * t), np.cos(2 * np.pi * 60 * t)],
                           versao=9)
    criar_aplicacao([], tema="escuro")
    janela = JanelaPrincipal()
    janela.controle.dialogos = DialogosFalsos()
    janela.resize(1600, 1000)
    janela.show()
    qtbot.waitExposed(janela)
    (fonte,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=60_000)
    for i in range(8):
        traco = janela.area.plotar_canal(fonte, i % 2)
        janela.projeto.pilha.push(MudarTracos([traco], faixa=i))
    vista = janela.area.widget_da_vista(janela.vista_ativa())
    assert len(vista.faixas) == 8
    qtbot.wait(50)
    item = next(iter(vista.itens.values()))
    canal = fonte.canal(0)
    app = QApplication.instance()
    navegar.percorrer_zoom(app, vista.grafico, item, len(canal.amostras), canal.taxa_hz)     # aquece
    mediana, p95 = navegar.resumo_dos_quadros(
        navegar.percorrer_zoom(app, vista.grafico, item, len(canal.amostras), canal.taxa_hz))
    janela.projeto.pilha.setClean()
    janela.close()
    assert p95 <= 0.016, f"mediana {mediana * 1e3:.1f} ms, p95 {p95 * 1e3:.1f} ms"
