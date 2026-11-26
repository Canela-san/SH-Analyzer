"""O ``TracoLOD`` (``sh_analyzer_gui.graficos.traco_lod``), sem tela: os regimes pelo zoom, um cálculo por ciclo de
eventos, a conversão afim e, principalmente, a **fidelidade** do desenho (o portão G4 do docs/gui-plan.md, 6.7):

* **nenhum extremo some:** o mínimo e o máximo das amostras de cada coluna de pixel aparecem pintados por inteiro,
  nela ou numa vizinha. A consulta arredonda as bordas das colunas para blocos da pirâmide (``dados.consulta``), e
  um pico a menos de um bloco da borda de um pixel é desenhado no pixel ao lado: a posição vale com ±1 px;
* **nada é inventado:** o que foi pintado numa coluna não passa dos extremos dela e das vizinhas;
* **as colunas estão nos pixels certos:** o centro de cada coluna da consulta cai no seu pixel (sem deslocamento);
* **de perto, a linha e os pontos das amostras,** sem virar um bloco cheio na escala enorme do zoom no tempo.
"""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

import pyqtgraph as pg  # noqa: E402
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from sh_analyzer_gui.dados.consulta import Amostras, Envoltoria  # noqa: E402
from sh_analyzer_gui.dados.piramide import construir  # noqa: E402
from sh_analyzer_gui.graficos.traco_lod import TracoLOD  # noqa: E402

LARGURA, ALTURA = 600, 300


def sinal(n: int, semente: int = 0) -> np.ndarray:
    """Um passeio aleatório com picos de uma amostra só, para cima e para baixo."""
    rng = np.random.default_rng(semente)
    x = np.cumsum(rng.normal(0, 30, n))
    x = (x - x.mean()) / (np.abs(x).max() + 1) * 12_000
    picos = rng.choice(n, size=40, replace=False)
    x[picos] += np.where(rng.random(40) < 0.5, -18_000, 18_000)
    return np.clip(x, -32768, 32767).astype(np.int16)


@pytest.fixture
def grafico(qtbot):
    w = pg.PlotWidget(background="#000000")
    item = w.getPlotItem()
    item.hideAxis("left")
    item.hideAxis("bottom")
    item.hideButtons()
    item.layout.setContentsMargins(0, 0, 0, 0)
    w.resize(LARGURA, ALTURA)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    return w


def colocar(grafico, x, taxa=1.0, **kw) -> TracoLOD:
    (p,) = construir(x)
    traco = TracoLOD(p, x, taxa, cor="#ffffff", **kw)
    grafico.addItem(traco)
    return traco


def mostrar(qtbot, grafico, traco, x0, x1, y0, y1):
    grafico.getViewBox().setRange(xRange=(x0, x1), yRange=(y0, y1), padding=0)
    qtbot.wait(30)
    traco.recalcular()             # garante a consulta com a geometria final, antes de pintar
    return grafico.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)


def pixels(imagem: QImage) -> np.ndarray:
    w, h = imagem.width(), imagem.height()
    bruto = np.frombuffer(imagem.constBits(), np.uint8).reshape(h, imagem.bytesPerLine())
    return bruto[:, :w * 4].reshape(h, w, 4)[:, :, :3].max(axis=2)


@pytest.mark.parametrize("janela", [(0, 2_000_000), (700_000, 760_000), (1_234_567, 1_240_000)])
def test_g4_cada_coluna_pintada_cobre_os_extremos_e_nao_inventa(qtbot, grafico, janela):
    """Envoltória pela pirâmide (~3 300 amostras por pixel), envoltória das amostras (~100) e poucas amostras."""
    x = sinal(2_000_000)
    traco = colocar(grafico, x)
    imagem = pixels(mostrar(qtbot, grafico, traco, *janela, -32768, 32767))
    vb = grafico.getViewBox()

    def linha(valor):
        return vb.mapViewToDevice(QPointF(0, float(valor))).y()

    colunas = []
    for px in range(imagem.shape[1]):
        xa = vb.mapDeviceToView(QPointF(px, 0)).x()
        xb = vb.mapDeviceToView(QPointF(px + 1, 0)).x()
        a, b = max(0, int(np.ceil(xa))), min(len(x) - 1, int(np.floor(xb - 1e-9)))
        colunas.append((x[a:b + 1].min(), x[a:b + 1].max()) if b >= a else None)
    pintadas = imagem > 64
    conferidas = 0
    for px in range(2, len(colunas) - 2):
        if colunas[px] is None or not pintadas[:, px].any():
            assert colunas[px] is None, f"coluna {px}: há amostras e nada foi pintado"
            continue
        linhas = np.flatnonzero(pintadas[:, px])
        topo, base = linhas.min(), linhas.max()
        mn, mx = colunas[px]
        perto = [k for k in (px - 1, px, px + 1) if pintadas[:, k].any()]
        assert min(np.flatnonzero(pintadas[:, k]).min() for k in perto) <= linha(mx) + 1.5, (
            f"coluna {px}: o máximo {mx} não foi pintado nem nela nem ao lado")
        assert max(np.flatnonzero(pintadas[:, k]).max() for k in perto) >= linha(mn) - 1.5, (
            f"coluna {px}: o mínimo {mn} não foi pintado nem nela nem ao lado")
        vizinhas = [colunas[k] for k in (px - 1, px, px + 1) if colunas[k] is not None]
        assert topo >= linha(max(v[1] for v in vizinhas)) - 1.5, f"coluna {px}: pintou acima do que existe"
        assert base <= linha(min(v[0] for v in vizinhas)) + 1.5, f"coluna {px}: pintou abaixo do que existe"
        conferidas += 1
    assert conferidas > LARGURA * 0.5
    consulta = traco.consulta
    if isinstance(consulta, Envoltoria):
        centros = (consulta.bordas[:-1] + consulta.bordas[1:] - 1) / 2
        dispositivo = np.array([vb.mapViewToDevice(QPointF(float(c), 0)).x() for c in centros])
        assert np.all(np.abs(dispositivo - (np.arange(len(centros)) + 0.5)) <= 0.6), "colunas fora dos seus pixels"


def test_regimes_e_um_calculo_por_ciclo_de_eventos(qtbot, grafico):
    x = sinal(1_000_000, semente=2)
    traco = colocar(grafico, x)
    vb = grafico.getViewBox()
    vb.setRange(xRange=(0, len(x)), padding=0)
    qtbot.wait(30)
    assert isinstance(traco.consulta, Envoltoria)
    assert abs(len(traco.consulta) - vb.width()) <= 2           # uma coluna por pixel
    antes = traco.recalculos
    vb.setXRange(100, 300, padding=0)                            # três mudanças no mesmo ciclo...
    vb.setYRange(-1000, 1000, padding=0)
    vb.setXRange(100, 400, padding=0)
    qtbot.wait(30)
    assert traco.recalculos == antes + 1                         # ... uma consulta só
    assert isinstance(traco.consulta, Amostras)
    np.testing.assert_array_equal(traco.consulta.valores, x[100:401].astype(np.float64))


def test_tempo_taxa_e_conversao_afim(qtbot, grafico):
    x = sinal(200_000, semente=3)
    escala, deslocamento = 20.48 / 65536, -10.24
    traco = colocar(grafico, x, taxa=400_000.0, t0=10.0, escala=escala, deslocamento=deslocamento)
    vb = grafico.getViewBox()
    vb.autoRange(padding=0)
    qtbot.wait(30)
    (x0, x1), (y0, y1) = vb.viewRange()
    assert x0 == pytest.approx(10.0) and x1 == pytest.approx(10.0 + (len(x) - 1) / 400_000)
    assert y0 == pytest.approx(x.min() * escala + deslocamento) and y1 == pytest.approx(x.max() * escala + deslocamento)
    original = traco.consulta
    assert isinstance(original, Envoltoria)
    traco.definir_afim(-1.0, 0.0)                     # inverter, em códigos: o mínimo e o máximo trocam de lugar
    codigos_min = (original.minimos - deslocamento) / escala
    codigos_max = (original.maximos - deslocamento) / escala
    np.testing.assert_allclose(traco.consulta.maximos, -codigos_min, atol=1e-6)
    np.testing.assert_allclose(traco.consulta.minimos, -codigos_max, atol=1e-6)
    assert traco.dataBounds(1) == (-float(x.max()), -float(x.min()))
    p = traco.ponto_mais_proximo(10.1)
    assert p is not None and 10.0 <= p.x() <= 10.0 + len(x) / 400_000


def test_remover_com_consulta_agendada_nao_quebra(qtbot, grafico):
    x = sinal(100_000, semente=4)
    traco = colocar(grafico, x)
    grafico.getViewBox().setXRange(0, 50_000, padding=0)        # agenda uma consulta...
    grafico.removeItem(traco)                                   # ... e o traço sai antes dela
    traco.deleteLater()
    qtbot.wait(30)
    assert grafico.getPlotItem().items == []


def test_segmentos_de_coluna_ligam_os_degraus_e_pulam_nan():
    from sh_analyzer_gui.graficos.traco_lod import _segmentos_de_coluna

    centros = np.arange(5, dtype=float)
    mn = np.array([0.0, 10.0, 10.0, -5.0, np.nan])
    mx = np.array([1.0, 12.0, 10.0, -4.0, np.nan])          # sobe, constante, desce, buraco
    x, y = _segmentos_de_coluna(centros, mn, mx)
    np.testing.assert_array_equal(x, [0, 0, 1, 1, 2, 2, 3, 3])
    np.testing.assert_array_equal(y, [0, 1, 1, 12, 10, 10, -5, 10])   # a 2ª desce até a 1ª; a 4ª sobe até a 3ª
    _, y = _segmentos_de_coluna(centros, mn, mx, altura_pixel=0.5)
    np.testing.assert_array_equal(y, [0, 1, 1, 12, 9.75, 10.25, -5, 10])  # a constante ganha meio pixel de cada lado


def test_nan_interrompe_o_desenho_sem_quebrar(qtbot, grafico):
    rng = np.random.default_rng(6)
    x = rng.normal(size=300_000)
    x[100_000:150_000] = np.nan
    traco = colocar(grafico, x)
    imagem = pixels(mostrar(qtbot, grafico, traco, 0, len(x), -6, 6))
    assert traco._colunas is not None
    meio = imagem.shape[1] * 125_000 // len(x)
    assert not (imagem[:, meio - 3:meio + 3] > 64).any()   # o buraco fica vazio
    traco.getViewBox().setRange(xRange=(99_990, 100_010), padding=0)
    qtbot.wait(30)
    assert isinstance(traco.consulta, Amostras) and len(traco._linhas) == 1


def test_sinal_constante_aparece(qtbot, grafico):
    x = np.full(500_000, 1000, np.int16)
    traco = colocar(grafico, x)
    imagem = pixels(mostrar(qtbot, grafico, traco, 0, len(x), -32768, 32767))
    assert (imagem[:, 5:-5] > 64).any(axis=0).all()       # cada coluna aparece, com a altura mínima de 1 px
    assert (imagem[:, 5:-5] > 64).sum(axis=0).max() <= 2  # e não mais que isso


def test_de_perto_os_pontos_nao_viram_um_bloco_cheio(qtbot, grafico):
    """O bug do "retângulo": bem de perto (8 px por amostra ou mais, quando os pontos das amostras aparecem), longe
    do tempo 0 e com a taxa de 200 kHz, a escala do tempo passa de 10⁶ px/s, e o QPainter pintava com a caneta dos
    pontos um bloco cheio entre a linha e a primeira amostra. Desenhados em pixels da tela, ficam a linha e os
    pontos."""
    taxa = 200_000.0
    x = np.linspace(0, 20_000, 100_000)                          # uma rampa: o bloco ficava embaixo dela
    traco = colocar(grafico, x, taxa=taxa, t0=19.5)
    inicio = 19.5 + 50_000 / taxa
    fim = inicio + 60 / taxa                                     # 60 amostras em 600 px: 10 px por amostra
    meio = x[50_030]
    # 5 px por unidade: a rampa sobe 1 px a cada amostra, 60 px na janela.
    imagem = pixels(mostrar(qtbot, grafico, traco, inicio, fim, meio - 30, meio + 30))
    assert isinstance(traco.consulta, Amostras) and traco._pontos
    acesas = imagem > 64
    assert acesas.any(axis=0)[5:-5].all()                        # a linha passa por todas as colunas
    # Cada coluna tem a linha (1 ou 2 px) e, perto das amostras, o ponto (4 px). O bloco cheio ia até 60 px.
    assert acesas.sum(axis=0).max() <= 12, acesas.sum(axis=0).max()
    assert acesas.mean() < 0.03, acesas.mean()                   # o bloco cheio pintava ~10 % da imagem


@pytest.mark.parametrize("largura_s", [1e-6, 1.5e-9, 1e-9, 1e-12])
def test_bem_de_perto_o_traco_continua_pintado(qtbot, grafico, largura_s):
    """O retângulo do item, com os dados inteiros, passava de 2³¹ pixels bem de perto (1 ns em 600 px, com 10 ms de
    dados): a cena do Qt o levava a inteiros, o número dava a volta e o traço não era pintado (sumia num zoom e
    voltava em outro). Cortado na vista, ele aparece em qualquer zoom."""
    taxa = 400_000.0
    t = np.arange(4000) / taxa
    x = (1000 * np.sin(2 * np.pi * 50 * t)).astype(np.float32)
    traco = colocar(grafico, x, taxa=taxa)
    centro = 1000.67 / taxa
    y = float(np.interp(centro, t, x))
    antes = traco.pinturas
    imagem = pixels(mostrar(qtbot, grafico, traco, centro - largura_s / 2, centro + largura_s / 2, y - 500, y + 500))
    assert traco.pinturas > antes and (imagem > 50).sum() > 0
