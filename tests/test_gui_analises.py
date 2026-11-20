"""As contas das análises da Fase 7 (F7.3 e F7.4: ``dados/analises.py``), sem Qt: a potência pela IEEE 1459 em cargas
de resposta conhecida (a resistiva, a indutiva, a não linear), os momentos combinados bloco a bloco, e o histograma e
as estatísticas do trecho (dos códigos do ADC e dos valores com cadeia) contra a NumPy e a SciPy."""

import math

import numpy as np
import pytest
import scipy.stats
from capturas_sinteticas import FS_TOTAL_2CH, escrever_bin
from sh_analyzer_gui.dados import analises as an
from sh_analyzer_gui.dados.cadeia import Cadeia, RemoverDC
from sh_analyzer_gui.dados.espectros import TrechoDoTraco
from sh_analyzer_gui.dados.materializacao import contexto_do_canal
from supraharmonicos import api

FS = 100_000.0
T = np.arange(int(FS * 0.5)) / FS
W = 2 * np.pi * 60


def test_a_carga_resistiva():
    v = 230 * math.sqrt(2) * np.sin(W * T)
    p = an.potencia(v, v / 23.0, FS)
    assert p.p == pytest.approx(2300, rel=1e-6) and p.fp == pytest.approx(1, abs=1e-6)
    assert p.q1 == pytest.approx(0, abs=1e-3) and p.ciclos >= 28


def test_a_carga_indutiva():
    v = 230 * math.sqrt(2) * np.sin(W * T)
    i = 10 * math.sqrt(2) * np.sin(W * T - math.radians(30))
    p = an.potencia(v, i, FS)
    assert p.p == pytest.approx(2300 * math.cos(math.radians(30)), rel=1e-5)
    assert p.q1 == pytest.approx(2300 * math.sin(math.radians(30)), rel=1e-5)        # positiva: a corrente atrasa
    assert p.fi1_graus == pytest.approx(30, abs=1e-3) and p.cos_fi1 == pytest.approx(math.cos(math.radians(30)))
    assert p.s == pytest.approx(2300, rel=1e-6) and p.sn == pytest.approx(0, abs=0.5)


def test_a_carga_nao_linear():
    """A corrente com o 3º harmônico (40 % da fundamental): o FP fica abaixo do cos φ₁, e S_N, o THD e a potência
    seguem das fórmulas da norma."""
    v = 230 * math.sqrt(2) * np.sin(W * T)
    i1, i3 = 10.0, 4.0
    i = math.sqrt(2) * (i1 * np.sin(W * T) + i3 * np.sin(3 * W * T))
    p = an.potencia(v, i, FS)
    i_rms = math.hypot(i1, i3)
    assert p.i_rms == pytest.approx(i_rms, rel=1e-6) and p.thd_i == pytest.approx(i3 / i1, rel=1e-5)
    assert p.p == pytest.approx(230 * i1, rel=1e-6) and p.s == pytest.approx(230 * i_rms, rel=1e-6)
    assert p.fp == pytest.approx(i1 / i_rms, rel=1e-6) and p.fp < p.cos_fi1
    assert p.sn == pytest.approx(math.sqrt((230 * i_rms) ** 2 - (230 * i1) ** 2), rel=1e-5)


def test_a_potencia_sem_fundamental_diz_por_que():
    with pytest.raises(api.ErroSHAN):
        an.potencia(np.random.default_rng(0).standard_normal(1000), np.ones(1000), FS)


def test_os_momentos_combinados_bloco_a_bloco():
    x = np.random.default_rng(1).gamma(2.0, 3.0, 100_003) + 1e6      # assimétrica, longe do zero
    m = an.Momentos()
    for parte in np.array_split(x, 7):
        m = m.mais(an.Momentos.de(parte))
    assert m.n == len(x) and m.media == pytest.approx(np.mean(x), rel=1e-15)
    var = m.m2 / m.n
    assert var == pytest.approx(np.var(x), rel=1e-9)
    assert (m.m3 / m.n) / var ** 1.5 == pytest.approx(scipy.stats.skew(x), rel=1e-7)
    assert (m.m4 / m.n) / var ** 2 - 3 == pytest.approx(scipy.stats.kurtosis(x), rel=1e-7)


@pytest.fixture
def captura(tmp_path):
    t = np.arange(200_000) / (FS_TOTAL_2CH / 2)
    rng = np.random.default_rng(3)
    v = 9.0 * np.sin(2 * np.pi * 60 * t) + 0.05 * rng.standard_normal(len(t))
    satura = np.clip(12.0 * np.sin(2 * np.pi * 60 * t), -11.0, 11.0)          # passa da faixa de ±10,24 V
    return api.abrir_captura(escrever_bin(tmp_path / "c.bin", [v, satura], versao=9))


def trecho(captura, canal, cadeia=None, ganho=1.0, offset=0.0, inicio=0, fim=None):
    n = len(captura.canal(canal).amostras)
    cadeia = Cadeia() if cadeia is None else cadeia
    return TrechoDoTraco(captura, canal, cadeia, contexto_do_canal(captura.canal(canal), captura=captura), inicio,
                         n if fim is None else fim, ganho, None, offset)


def test_as_estatisticas_dos_codigos(captura):
    r = an.histograma_e_estatisticas(trecho(captura, 0, ganho=2.0, offset=1.0, inicio=1000, fim=150_000), 100)
    x = api.sinal_do_canal(captura, 0, 1000, 150_000) * 2.0 + 1.0
    e = r.estatisticas
    assert e.n == len(x) and e.media == pytest.approx(np.mean(x), abs=1e-12)
    assert e.desvio == pytest.approx(np.std(x), rel=1e-12) and e.rms == pytest.approx(np.sqrt(np.mean(x * x)))
    assert e.assimetria == pytest.approx(scipy.stats.skew(x), abs=1e-9)
    assert e.curtose == pytest.approx(scipy.stats.kurtosis(x), abs=1e-9)
    assert e.percentis_exatos
    for p, valor in e.percentis.items():
        assert valor == pytest.approx(np.percentile(x, p), abs=1e-12), p
    h = r.histograma
    assert h.codigos and h.total == len(x) and len(h.bordas) == len(h.contagens) + 1
    assert h.saturadas_baixo == 0 and h.saturadas_alto == 0 and 0.8 < h.ocupacao < 0.95


def test_a_saturacao_e_a_ocupacao_do_adc(captura):
    codigos = np.asarray(captura.canal(1).amostras)
    h = an.histograma_e_estatisticas(trecho(captura, 1), 50).histograma
    assert h.saturadas_baixo == int(np.count_nonzero(codigos == 0)) > 0
    assert h.saturadas_alto == int(np.count_nonzero(codigos == 65535)) > 0 and h.ocupacao == pytest.approx(1.0)


def test_as_estatisticas_com_cadeia_e_o_histograma_fino(captura, monkeypatch):
    t = trecho(captura, 0, Cadeia((RemoverDC(),)))
    x = api.sinal_do_canal(captura, 0)
    x = x - np.mean(x)
    exato = an.histograma_e_estatisticas(t, 64)
    assert exato.estatisticas.percentis_exatos and not exato.histograma.codigos
    assert exato.estatisticas.media == pytest.approx(0, abs=1e-9)
    assert np.array_equal(exato.histograma.contagens, np.histogram(x, 64, (x.min(), x.max()))[0])
    monkeypatch.setattr(an, "LIMITE_EXATO", 1000)                 # o caminho das capturas longas
    monkeypatch.setattr(an, "BLOCO", 30_000)
    fino = an.histograma_e_estatisticas(t, 64).estatisticas
    assert not fino.percentis_exatos and fino.resolucao_dos_percentis > 0
    for p, valor in fino.percentis.items():
        assert abs(valor - np.percentile(x, p)) <= fino.resolucao_dos_percentis, p
    assert fino.desvio == pytest.approx(np.std(x), rel=1e-12)


def test_o_xy_vira_densidade_com_muitas_amostras(monkeypatch):
    v = 230 * math.sqrt(2) * np.sin(W * T)
    i = 10 * math.sqrt(2) * np.sin(W * T - 0.5)
    r = an.xy(v, i, FS)
    assert r.densidade is None and len(r.x) == len(T) and r.potencia is not None
    monkeypatch.setattr(an, "MAXIMO_DE_PONTOS_DO_XY", 1000)
    r = an.xy(v, i, FS)
    assert r.x is None and r.densidade.shape == (an.COLUNAS_DA_DENSIDADE,) * 2 and r.densidade.sum() == len(T)
