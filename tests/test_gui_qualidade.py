"""A qualidade de energia, os eventos e a transferência (F7.5 a F7.7: ``dados/qualidade.py``), sem Qt, em sinais de
resposta conhecida: a rede de 60 Hz com o 5º harmônico e um tom de supraharmônico, os afundamentos e as elevações nos
instantes certos, a saturação, um salto, e um filtro conhecido entre a entrada e a saída."""

import math

import numpy as np
import pytest
import scipy.signal
from capturas_sinteticas import FS_TOTAL_2CH, escrever_bin
from sh_analyzer_gui.dados import qualidade as q
from sh_analyzer_gui.dados.cadeia import Cadeia
from sh_analyzer_gui.dados.espectros import TrechoDoTraco
from sh_analyzer_gui.dados.materializacao import contexto_do_canal
from supraharmonicos import api

FS = FS_TOTAL_2CH / 2           # 200 kS/s por canal
W = 2 * np.pi * 60


def abrir(tmp_path, canal0, canal1=None, nome="q.bin"):
    canal1 = np.zeros_like(canal0) if canal1 is None else canal1
    return api.abrir_captura(escrever_bin(tmp_path / nome, [canal0, canal1], versao=9))


def trecho(captura, canal=0, inicio=0, fim=None):
    n = len(captura.canal(canal).amostras)
    return TrechoDoTraco(captura, canal, Cadeia(), contexto_do_canal(captura.canal(canal), captura=captura), inicio,
                         n if fim is None else fim)


@pytest.fixture
def rede(tmp_path):
    t = np.arange(int(FS * 2)) / FS
    x = 8 * np.sin(W * t) + 0.4 * np.sin(5 * W * t) + 0.1 * np.sin(2 * np.pi * 20_000 * t)
    return abrir(tmp_path, x)


def test_os_indices_da_rede(rede):
    r = q.indices(trecho(rede))
    assert r.ciclos_por_janela == 12 and r.n_janelas == 9                 # 2 s: 120 ciclos, 10 janelas menos a borda
    assert np.allclose(r.valores["frequencia"], 60.0, atol=1e-3)
    assert np.allclose(r.valores["thd"], 0.05, rtol=2e-3)
    assert np.allclose(r.valores["rms"], math.sqrt((64 + 0.16 + 0.01) / 2), rtol=1e-3)
    assert np.allclose(r.valores["supra_9_150k"], 0.1 / math.sqrt(2), rtol=2e-2)
    assert np.allclose(r.valores["fator_k"], (1 * 64 + 25 * 0.16) / (64 + 0.16), rtol=1e-3)
    assert r.estatisticas["thd"].p95 == pytest.approx(0.05, rel=2e-3)


def test_os_pedacos_dao_as_mesmas_janelas(rede):
    inteiro = q.indices(trecho(rede))
    em_pedacos = q.indices(trecho(rede), pedaco=50_000)
    assert abs(em_pedacos.n_janelas - inteiro.n_janelas) <= 1
    n = min(em_pedacos.n_janelas, inteiro.n_janelas)
    assert np.allclose(em_pedacos.inicios_s[:n], inteiro.inicios_s[:n], atol=2 / FS)
    assert np.allclose(em_pedacos.valores["thd"][:n], inteiro.valores["thd"][:n], rtol=1e-3)


def test_os_afundamentos_e_as_elevacoes(tmp_path):
    t = np.arange(int(FS * 3)) / FS
    amplitude = np.full(len(t), 8.0)
    amplitude[(t >= 0.5) & (t < 0.6)] = 4.0                    # 50 %: um afundamento de 100 ms
    amplitude[(t >= 1.5) & (t < 1.55)] = 9.6                   # 120 %: uma elevação de 50 ms
    amplitude[(t >= 2.2) & (t < 2.3)] = 0.0                    # uma interrupção
    captura = abrir(tmp_path, amplitude * np.sin(W * t))
    eventos = [e for e in q.eventos(trecho(captura)) if e.tipo != "descontinuidade"]
    tipos = [e.tipo for e in eventos]
    assert tipos == ["afundamento", "elevacao", "interrupcao"], eventos
    af, el, it = eventos
    assert af.inicio_s == pytest.approx(0.5, abs=1 / 60) and af.duracao_s == pytest.approx(0.1, abs=2 / 60)
    assert af.valor == pytest.approx(4.0 / math.sqrt(2), rel=0.02)
    assert el.inicio_s == pytest.approx(1.5, abs=1 / 60) and el.valor == pytest.approx(9.6 / math.sqrt(2), rel=0.02)
    assert it.inicio_s == pytest.approx(2.2, abs=1 / 60)


def test_a_saturacao_e_o_salto(tmp_path):
    t = np.arange(int(FS * 0.5)) / FS
    x = 8 * np.sin(W * t)
    x[30_000:30_010] = 12.0                                     # passa do fundo de escala: 10 amostras saturadas
    x[60_000] += 3.0                                            # um salto de uma amostra
    captura = abrir(tmp_path, x)
    eventos = q.eventos(trecho(captura), q.OpcoesDosEventos(tensao=False))
    saturacao = [e for e in eventos if e.tipo == "saturacao"]
    assert len(saturacao) == 1 and saturacao[0].valor == 10 and saturacao[0].inicio_s == pytest.approx(30_000 / FS)
    saltos = [e for e in eventos if e.tipo == "descontinuidade"]
    assert any(abs(e.inicio_s - 60_000 / FS) < 3 / FS for e in saltos)


def test_o_pico_de_supraharmonicos(tmp_path):
    t = np.arange(int(FS * 3)) / FS
    tom = np.where((t >= 1.0) & (t < 1.2), 0.5, 0.005) * np.sin(2 * np.pi * 30_000 * t)
    captura = abrir(tmp_path, 8 * np.sin(W * t) + tom)
    tr = trecho(captura)
    picos = [e for e in q.eventos(tr, indices_prontos=q.indices(tr)) if e.tipo == "supraharmonicos"]
    assert picos and all(0.8 <= e.inicio_s <= 1.2 for e in picos)


def test_a_transferencia_de_um_filtro_conhecido():
    rng = np.random.default_rng(5)
    x = rng.standard_normal(400_000)
    b, a = scipy.signal.butter(2, 5_000, fs=FS)
    y = scipy.signal.lfilter(b, a, x)
    r = q.transferencia(x, y, FS, 500.0)
    _, h = scipy.signal.freqz(b, a, worN=r.frequencias, fs=FS)
    dentro = (r.frequencias > 0) & (r.frequencias < 20_000)          # o DC sai com o detrend do Welch
    assert np.max(np.abs(r.magnitude_db[dentro] - 20 * np.log10(np.abs(h[dentro])))) < 0.3
    assert np.max(np.abs(r.fase_graus[dentro] - np.degrees(np.angle(h[dentro])))) < 2.0
    assert np.min(r.coerencia[dentro]) > 0.98          # o viés do Welch com segmentos curtos
    f, c = scipy.signal.coherence(x, y, fs=FS, nperseg=400, noverlap=200)
    assert np.allclose(r.coerencia, c, atol=1e-9) and r.medias == 1999


def test_o_intervalo_de_confianca_do_welch():
    baixo, alto = q.intervalo_de_confianca_db(100)
    assert -1.5 < baixo < 0 < alto < 1.5
    estreito = q.intervalo_de_confianca_db(10_000)
    assert abs(estreito[0]) < abs(baixo) and estreito[1] < alto
