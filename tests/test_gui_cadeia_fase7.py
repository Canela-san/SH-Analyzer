"""As etapas da Fase 7 na cadeia (F7.1 e F7.2: TR-05 e TR-06), sem Qt: cada uma contra a referência (a fórmula
fechada, a SciPy), o bloco a bloco igual ao vetor inteiro longe das bordas, a unidade que a cadeia dá ao traço, e a
expressão segura (o que ela recusa, e por quê)."""

import math

import numpy as np
import pytest
from scipy.signal import hilbert
from sh_analyzer_gui.dados import expressao as ex
from sh_analyzer_gui.dados.cadeia import (
    Cadeia,
    ContextoDaCadeia,
    Derivar,
    Envoltoria,
    EtapaInvalida,
    Expressao,
    FrequenciaInstantanea,
    Integrar,
    RemoverDC,
    RMSMovel,
    etapa_de_dict,
)
from supraharmonicos import api

FS = 50_000.0
T = np.arange(int(FS * 2)) / FS
CTX = ContextoDaCadeia(FS)


def em_blocos(cadeia, x, ctx=CTX, bloco=17_000):
    return np.concatenate([v for _i, v in cadeia.em_blocos(lambda a, b: x[a:b], len(x), ctx, bloco=bloco)])


def test_derivar_e_a_diferenca_central():
    w = 2 * np.pi * 60
    y = Cadeia((Derivar(),)).aplicar(np.sin(w * T), CTX).valores
    erro = np.max(np.abs(y[1:-1] - w * np.cos(w * T[1:-1]))) / w
    assert erro < 1.1 * (w / FS) ** 2 / 6                     # o erro da diferença central: (ωΔt)²/6
    assert Cadeia((Derivar(),)).unidade_de("V") == "V/s"


@pytest.mark.parametrize("corte", [5.0, 20.0])
def test_integrar_e_o_integrador_com_fuga(corte):
    """Longe do começo, a resposta a um cosseno é a de H(jω) = 1/(jω + ωc), e o bloco a bloco é o vetor inteiro."""
    c = Cadeia((Integrar(corte),))
    w, wc = 2 * np.pi * 60, 2 * np.pi * corte
    h = 1 / (1j * w + wc)
    x = np.cos(w * T)
    y = c.aplicar(x, CTX).valores
    m = c.margem(CTX)
    assert np.max(np.abs(y[m:] - np.real(h * np.exp(1j * w * T[m:])))) < 1e-5 * abs(h)     # a bilinear perto da analógica
    assert np.max(np.abs(em_blocos(c, x)[m:] - y[m:])) < 1e-9 * abs(h)
    assert c.unidade_de("A") == "A·s" and Integrar(corte).ganho_dc(CTX) == pytest.approx(1 / wc)


def test_integrar_recusa_o_corte_que_pede_memoria_demais():
    with pytest.raises(api.ErroSHAN, match="baixo demais"):
        Cadeia((Integrar(0.01),)).margem(ContextoDaCadeia(400_000.0))
    with pytest.raises(EtapaInvalida):
        Integrar(-1.0)


def test_rms_movel_de_um_seno():
    x = 3 * np.sin(2 * np.pi * 50 * T + 0.3)
    c = Cadeia((RMSMovel(20.0),))                       # 20 ms: um ciclo inteiro de 50 Hz (1 000 amostras)
    y = c.aplicar(x, CTX).valores
    assert np.max(np.abs(y[1000:-1000] - 3 / math.sqrt(2))) < 1e-9
    assert np.max(np.abs(em_blocos(c, x) - y)) < 1e-9


def test_a_envoltoria_e_a_do_sinal_analitico():
    envoltoria = 1 + 0.5 * np.sin(2 * np.pi * 3 * T)
    x = envoltoria * np.sin(2 * np.pi * 1000 * T)
    c = Cadeia((Envoltoria(20.0),))
    y = c.aplicar(x, CTX).valores
    m = c.margem(CTX)
    assert np.max(np.abs(y[m:-m] - envoltoria[m:-m])) < 1e-6
    assert np.max(np.abs(y[m:-m] - np.abs(hilbert(x))[m:-m])) < 1e-6
    assert np.max(np.abs(em_blocos(c, x)[m:-m] - y[m:-m])) < 1e-12
    y60 = Cadeia((Envoltoria(20.0),)).aplicar(np.sin(2 * np.pi * 60 * T), CTX).valores
    assert np.max(np.abs(y60[m:-m] - 1)) < 1e-4                # 3× a mínima já acompanha


def test_a_frequencia_ciclo_a_ciclo():
    f0 = 59.7
    fase = 2 * np.pi * f0 * T
    x = np.sin(fase) + 0.05 * np.sin(5 * fase)                 # o 5º harmônico sai no passa-faixa
    c = Cadeia((FrequenciaInstantanea(60.0),))
    y = c.aplicar(x, CTX).valores
    m = c.margem(CTX)
    assert np.max(np.abs(y[m:-m] - f0)) < 1e-3
    assert np.max(np.abs(em_blocos(c, x)[m:-m] - y[m:-m])) < 1e-9
    assert c.unidade_de("V") == "Hz"
    # um degrau de frequência aparece no ciclo em que acontece
    f = np.where(T < 1.0, 60.0, 61.0)
    y = c.aplicar(np.sin(2 * np.pi * np.cumsum(f) / FS), CTX).valores
    assert y[int(0.5 * FS)] == pytest.approx(60.0, abs=1e-3) and y[int(1.5 * FS)] == pytest.approx(61.0, abs=1e-3)


def test_a_expressao_com_os_outros_canais():
    c0, c1 = np.sin(2 * np.pi * 60 * T), 2 * np.cos(2 * np.pi * 60 * T)
    ctx = ContextoDaCadeia(FS, ler_canal=lambda n, a, b: (c0, c1)[n][a:b], n_canais=2)
    c = Cadeia((Expressao("a × c1 − 2^2 + sqrt(abs(c0))", unidade_da_saida="W"),))
    y = c.aplicar(c0, ctx, 0).valores
    assert np.allclose(y, c0 * c1 - 4 + np.sqrt(np.abs(c0)), rtol=0, atol=1e-15)
    assert np.array_equal(em_blocos(c, c0, ctx), y) and c.unidade_de("V") == "W"
    with pytest.raises(api.ErroSHAN, match="c3"):
        Cadeia((Expressao("a - c3"),)).aplicar(c0, ctx, 0)
    with pytest.raises(api.ErroSHAN, match="captura"):
        Cadeia((Expressao("a - c1"),)).aplicar(c0, CTX, 0)


def test_a_expressao_sem_numero_vira_zero_com_aviso():
    ctx = ContextoDaCadeia(FS, ler_canal=lambda n, a, b: np.zeros(b - a), n_canais=2)
    r = Cadeia((Expressao("a / c1"),)).aplicar(np.ones(10), ctx, 0)
    assert np.array_equal(r.valores, np.zeros(10)) and any("10 amostra" in a.texto for a in r.avisos)


@pytest.mark.parametrize("texto, motivo", [
    ("__import__('os')", "função não aceita"), ("a.real", "Attribute"), ("a[0]", "Subscript"),
    ("a if 1 else 2", "IfExp"), ("a*0,5", "ponto nos decimais"), ("foo(a)", "função não aceita"),
    ("a < 1", "comparações"), ("c99", "c0 a c15"), ("sin(a, 2)", "1 argumento"), ("a ** 100", "expoente"),
    ("sqrt", "é uma função"), ("x + 1", "nome desconhecido"), ("", "vazia"), ("lambda: 1", "Lambda"),
])
def test_a_expressao_recusa_o_que_nao_esta_na_lista(texto, motivo):
    with pytest.raises(ex.ExpressaoInvalida, match=motivo):
        ex.compilar(texto)


def test_o_ganho_em_dc_so_da_conta_linear_em_a():
    assert ex.compilar("2*a").ganho_em_a == 2.0 and ex.compilar("-a/4").ganho_em_a == -0.25
    for texto in ("a - 1", "a*a", "a*c1", "abs(a)"):
        assert math.isnan(ex.compilar(texto).ganho_em_a), texto


def test_o_menos_dc_depois_de_uma_nao_linear_avisa():
    r = Cadeia((RMSMovel(20.0), RemoverDC())).aplicar(np.sin(2 * np.pi * 50 * T),
                                                     ContextoDaCadeia(FS, media=0.0))
    assert any("muda com o trecho" in a.texto for a in r.avisos)


@pytest.mark.parametrize("etapa", [Derivar(), Integrar(3.0), RMSMovel(10.0), Envoltoria(50.0),
                                   FrequenciaInstantanea(50.0), Expressao("a*c1", unidade_da_saida="W")])
def test_cada_etapa_vai_e_volta_pelo_projeto(etapa):
    assert etapa_de_dict(etapa.para_dict()) == etapa
