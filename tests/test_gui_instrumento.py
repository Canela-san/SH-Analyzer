"""O modo Instrumento (F7.9: ``dados/instrumento.py``), sem Qt: o disparo com a histerese, os ciclos que se sobrepõem
no sincronismo (a fase conhecida de um segundo traço), a persistência que conta as amostras certas."""

import math

import numpy as np
import pytest
from capturas_sinteticas import FS_TOTAL_2CH, escrever_bin
from sh_analyzer_gui.dados import instrumento as ins
from sh_analyzer_gui.dados.cadeia import Cadeia
from sh_analyzer_gui.dados.espectros import TrechoDoTraco
from sh_analyzer_gui.dados.materializacao import contexto_do_canal
from supraharmonicos import api

FS = FS_TOTAL_2CH / 2
W = 2 * np.pi * 60


def test_os_disparos_de_uma_senoide():
    t = np.arange(int(FS * 0.1)) / FS
    x = np.sin(W * t + 0.3)
    subindo = ins.disparos(x, 0.0, "subindo") / FS
    esperados = (np.arange(1, 7) * 2 * np.pi - 0.3) / W
    assert np.allclose(subindo, esperados[:len(subindo)], atol=1e-7) and len(subindo) == 6
    descendo = ins.disparos(x, 0.0, "descendo") / FS
    assert np.allclose(descendo, (np.pi - 0.3 + np.arange(len(descendo)) * 2 * np.pi) / W, atol=1e-7)
    meio = ins.disparos(x, 0.5, "subindo") / FS                     # no nível: sin = 0,5
    assert np.allclose(np.sin(W * meio + 0.3), 0.5, atol=1e-6)


def test_a_histerese_contra_o_ruido():
    rng = np.random.default_rng(1)
    t = np.arange(int(FS * 0.5)) / FS
    x = np.sin(W * t) + 0.05 * rng.standard_normal(len(t))
    sem = ins.disparos(x, 0.0, "subindo")
    com = ins.disparos(x, 0.0, "subindo", histerese=0.3)
    assert len(sem) > 40 and len(com) == 30                           # 30 ciclos em 0,5 s
    assert np.allclose(np.diff(com) / FS, 1 / 60, atol=3e-4)
    morto = ins.disparos(x, 0.0, "subindo", histerese=0.3, tempo_morto=1.5 * FS / 60)   # um a cada dois ciclos
    assert len(morto) == 15


@pytest.fixture
def captura(tmp_path):
    rng = np.random.default_rng(2)
    t = np.arange(int(FS * 1.0)) / FS
    v = 8 * np.sin(W * t + 0.7) + 0.02 * rng.standard_normal(len(t))
    i = 3 * np.sin(W * t + 0.7 - math.radians(30)) + 0.02 * rng.standard_normal(len(t))
    return api.abrir_captura(escrever_bin(tmp_path / "vi.bin", [v, i], versao=9))


def trecho(captura, canal):
    c = captura.canal(canal)
    return TrechoDoTraco(captura, canal, Cadeia(), contexto_do_canal(c, captura=captura), 0, len(c.amostras))


def test_os_disparos_em_pedacos_sao_os_do_trecho_inteiro(captura):
    antes, depois = 0.002, 0.02
    inteiro = ins.disparos_do_trecho(trecho(captura, 0), 0.0, "subindo", 0.5, antes, depois)
    pedacos = ins.disparos_do_trecho(trecho(captura, 0), 0.0, "subindo", 0.5, antes, depois, pedaco=7_000)
    assert inteiro.n == pedacos.n == 58 and np.allclose(inteiro.instantes, pedacos.instantes)    # janela inteira
    morto = ins.disparos_do_trecho(trecho(captura, 0), 0.0, "subindo", 0.5, antes, depois, tempo_morto_s=0.025)
    assert morto.n == 29                                                     # o holdoff de 1,5 ciclo
    # o ruído de 0,02 V na inclinação de 8·ω V/s: ~7 µs em cada cruzamento
    assert inteiro.periodo_s == pytest.approx(1 / 60, rel=1e-4) and inteiro.desvio_do_periodo_s < 2e-5


def test_os_ciclos_se_sobrepoem_no_sincronismo(captura):
    antes, depois = 1 / 240, 1 / 60
    d = ins.disparos_do_trecho(trecho(captura, 0), 0.0, "subindo", 0.5, antes, depois)
    v = ins.ciclo_medio(trecho(captura, 0), d, antes, depois)
    i = ins.ciclo_medio(trecho(captura, 1), d, antes, depois)
    assert v.ciclos == i.ciclos == d.n
    assert np.interp(0.0, v.tempos_s, v.media) == pytest.approx(0.0, abs=0.01)    # o disparo no zero subindo
    assert np.max(v.desvio) < 0.05 and np.max(i.desvio) < 0.05               # só o ruído: os ciclos se sobrepõem
    assert v.rms == pytest.approx(8 / math.sqrt(2), rel=0.01) and v.pico_a_pico == pytest.approx(16, rel=0.01)
    zero_i = ins.disparos(i.media, 0.0, "subindo")                           # a corrente cruza 30° depois
    atraso = np.interp(zero_i[0], np.arange(len(i.tempos_s)), i.tempos_s)
    assert atraso == pytest.approx(30 / 360 / 60, abs=2e-5)


def test_a_persistencia_conta_as_amostras(captura):
    antes, depois = 0.001, 0.01
    d = ins.disparos_do_trecho(trecho(captura, 0), 0.0, "subindo", 0.5, antes, depois)
    p = ins.densidade(trecho(captura, 0), d, antes, depois, (-10.0, 10.0), colunas=100, linhas=64)
    por_ciclo = math.floor(depois * FS) + math.floor(antes * FS) + 1                # ± 1 pela fração do disparo
    assert p.fora == 0 and abs(p.amostras - d.n * por_ciclo) <= d.n
    assert int(p.contagens.sum()) == p.amostras
    estreita = ins.densidade(trecho(captura, 0), d, antes, depois, (-4.0, 4.0), colunas=100, linhas=64)
    assert estreita.amostras + estreita.fora == p.amostras and estreita.fora > 0
    coluna_do_disparo = int(antes / (antes + depois) * 100)
    linha_do_zero = int((0.0 + 10) / 20 * 64)
    perto = p.contagens[coluna_do_disparo, linha_do_zero - 1:linha_do_zero + 1].sum()
    assert perto > 0.8 * p.contagens[coluna_do_disparo].sum()                 # no disparo, o traço passa no zero
