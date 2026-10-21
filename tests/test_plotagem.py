"""Testes de ``supraharmonicos.plotagem``: a forma de onda e o zoom da janela.

Por padrão, a forma de onda mostra todas as amostras do intervalo. A envoltória mín/máx só entra quando pedida
(``--simplificar``/``--max-pontos``), e, ampliada, ela seria um zigue-zague entre o mínimo e o máximo de cada coluna,
com pontos só nos extremos (uma "onda triangular"), e não as amostras: o zoom tem de redesenhar o trecho visível."""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from supraharmonicos.plotagem import (  # noqa: E402
    MAX_PONTOS_COM_MARCADOR,
    MAX_PONTOS_TEMPO,
    desenhar_forma_de_onda,
    pontos_para_plot,
    trecho_visivel,
)

FS = 100_000.0
F_TOM = 9_999.57          # o tom do T7: 10 amostras por ciclo


@pytest.fixture
def senoide():
    n = 1_048_576         # 1 bloco, como o teste.bin que mostrou o problema
    return 0.43 * np.sin(2 * np.pi * F_TOM * np.arange(n) / FS)


def _marcas(ax):
    """A linha dos marcadores (a segunda da forma de onda)."""
    return ax.get_lines()[1]


def test_por_padrao_todas_as_amostras(senoide):
    tempo, valores = pontos_para_plot(senoide, FS, 1.0)
    assert valores is senoide and len(tempo) == len(senoide)


def test_envoltoria_so_quando_pedida_e_com_pontos_nos_extremos(senoide):
    _, valores = pontos_para_plot(senoide, FS, 1.0, MAX_PONTOS_TEMPO)
    assert len(valores) <= MAX_PONTOS_TEMPO + 2
    assert np.all(np.abs(valores) > 0.40)          # só extremos: por isso, ampliada, ela parecia uma onda triangular


def test_trecho_visivel_com_margem_e_bordas():
    assert trecho_visivel(1000, FS, 1.0, 100 / FS, 140 / FS) == (99, 142)
    assert trecho_visivel(1000, FS, 1000.0, -5.0, 1e9) == (0, 1000)          # além das duas pontas
    i0, i1 = trecho_visivel(1000, FS, 1.0, 50.0, 60.0)                         # depois do fim: nada
    assert i1 - i0 == 0


def test_zoom_com_todas_as_amostras_so_poe_marcadores(senoide):
    fig, ax = plt.subplots()
    linha = desenhar_forma_de_onda(ax, senoide, FS, 1000.0, color="tab:green")
    try:
        assert len(linha.get_ydata()) == len(senoide)
        ax.set_xlim(1000 / FS * 1000, 1040 / FS * 1000)                         # o zoom num trecho de 4 ciclos
        assert len(linha.get_ydata()) == len(senoide)                          # os dados da linha não mudam
        i0, i1 = trecho_visivel(len(senoide), FS, 1000.0, *ax.get_xlim())
        assert i0 == 999 and 1041 <= i1 <= 1043                                # o trecho, com 1 amostra de margem
        np.testing.assert_array_equal(_marcas(ax).get_ydata(), senoide[i0:i1])
        ax.set_xlim(0, len(senoide) / FS * 1000)
        assert len(_marcas(ax).get_ydata()) == 0                                # muitas amostras: sem marcadores
    finally:
        plt.close(fig)


def test_zoom_na_envoltoria_mostra_as_amostras_de_verdade(senoide):
    fig, ax = plt.subplots()
    linha = desenhar_forma_de_onda(ax, senoide, FS, 1000.0, MAX_PONTOS_TEMPO, color="tab:green")
    try:
        assert len(linha.get_ydata()) <= MAX_PONTOS_TEMPO + 2
        ax.set_xlim(1000 / FS * 1000, 1040 / FS * 1000)
        i0, i1 = trecho_visivel(len(senoide), FS, 1000.0, *ax.get_xlim())
        np.testing.assert_array_equal(linha.get_ydata(), senoide[i0:i1])
        np.testing.assert_allclose(linha.get_xdata(), np.arange(i0, i1) / FS * 1000)
        assert np.min(np.abs(linha.get_ydata())) < 0.05                        # há amostras perto de zero: a senoide
        ax.set_xlim(0, (MAX_PONTOS_TEMPO + 5000) / FS * 1000)                  # mais que max_pontos: envoltória
        assert len(linha.get_ydata()) <= MAX_PONTOS_TEMPO + 2
        assert len(_marcas(ax).get_ydata()) == 0
        ax.set_xlim(0, (MAX_PONTOS_COM_MARCADOR + 100) / FS * 1000)            # amostras, ainda sem marcador
        assert MAX_PONTOS_COM_MARCADOR + 100 < len(linha.get_ydata()) <= MAX_PONTOS_COM_MARCADOR + 103
        assert len(_marcas(ax).get_ydata()) == 0
    finally:
        plt.close(fig)
