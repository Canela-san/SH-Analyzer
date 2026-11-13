"""A consulta da camada de dados (``sh_analyzer_gui.dados.consulta``): para qualquer janela e qualquer número de
colunas, cada amostra visível cai em exatamente uma coluna, e o mínimo e o máximo de cada coluna são os das amostras
que ela cobre (contra a força bruta). Sem Qt."""

import numpy as np
import pytest
from sh_analyzer_gui.dados.consulta import (
    AMOSTRAS_POR_COLUNA_LINHA,
    BLOCOS_POR_COLUNA,
    Amostras,
    Envoltoria,
    aplicar_afim,
    consultar,
)
from sh_analyzer_gui.dados.piramide import BLOCO_BASE, construir


def sinal(n: int, semente: int = 0, dtype=np.int16) -> np.ndarray:
    """Ruído com picos isolados de uma amostra (os que uma redução errada esconderia)."""
    rng = np.random.default_rng(semente)
    x = rng.integers(-2000, 2000, n).astype(dtype)
    picos = rng.choice(n, size=max(1, n // 5000), replace=False)
    x[picos] = np.where(rng.random(len(picos)) < 0.5, np.iinfo(dtype).min, np.iinfo(dtype).max)
    return x


def conferir_envoltoria(env: Envoltoria, x: np.ndarray, inicio: int, fim: int, colunas: int):
    b = env.bordas
    assert len(b) == len(env) + 1 and len(env) <= colunas
    assert np.all(np.diff(b) > 0), "as colunas têm de ser crescentes e não vazias"
    i0, i1 = max(0, inicio), min(len(x), fim)
    assert b[0] <= i0 and b[-1] >= i1, "toda amostra visível tem de cair numa coluna"
    assert b[0] >= 0 and b[-1] <= len(x)
    for c in range(len(env)):
        trecho = x[b[c]:b[c + 1]]
        assert env.minimos[c] == trecho.min() and env.maximos[c] == trecho.max(), f"coluna {c}: {b[c]}..{b[c + 1]}"
    return b


@pytest.fixture(scope="module")
def grande():
    x = sinal(3_000_017, semente=1)
    (p,) = construir(x)
    return x, p


@pytest.mark.parametrize("colunas", [1, 7, 333, 1600])
def test_janelas_aleatorias_em_todos_os_zooms(grande, colunas):
    x, p = grande
    rng = np.random.default_rng(colunas)
    for _ in range(40):
        largura = int(10 ** rng.uniform(0.5, np.log10(len(x))))
        inicio = int(rng.integers(-1000, len(x)))
        r = consultar(p, x, inicio, inicio + largura, colunas)
        i0, i1 = max(0, inicio), min(len(x), inicio + largura)
        if isinstance(r, Amostras):
            assert (i1 - i0) / colunas <= AMOSTRAS_POR_COLUNA_LINHA or i1 <= i0
            np.testing.assert_array_equal(r.indices, np.arange(i0, max(i0, i1)))
            np.testing.assert_array_equal(r.valores, x[i0:i1])
        else:
            conferir_envoltoria(r, x, inicio, inicio + largura, colunas)


def test_a_captura_inteira_usa_a_piramide_e_e_exata(grande):
    x, p = grande
    env = consultar(p, x, 0, len(x), 1600)
    assert isinstance(env, Envoltoria) and len(env) == 1600
    b = conferir_envoltoria(env, x, 0, len(x), 1600)
    larguras = np.diff(b)
    # com >= 8 blocos por coluna, as colunas variam no máximo um bloco do nível usado
    assert larguras.min() >= BLOCOS_POR_COLUNA * BLOCO_BASE
    nivel = p.nivel_para(len(x) / 1600, BLOCOS_POR_COLUNA)
    assert larguras[:-1].max() - larguras[:-1].min() <= nivel.bloco
    assert x.min() == env.minimos.min() and x.max() == env.maximos.max()      # nenhum pico some


def test_regimes_pela_quantidade_de_amostras_por_coluna(grande):
    x, p = grande
    assert isinstance(consultar(p, x, 100, 100 + 2 * 1600, 1600), Amostras)          # 2 por coluna: amostras
    r = consultar(p, x, 100, 100 + 3 * 1600, 1600)                                  # 3: envoltória das amostras
    assert isinstance(r, Envoltoria) and len(r) == 1600 and np.all(np.diff(r.bordas) == 3)
    r = consultar(p, x, 100, 100 + 300 * 1600, 1600)                                # 300: pela pirâmide (bloco 32)
    assert isinstance(r, Envoltoria) and r.bordas[0] % BLOCO_BASE == 0


def test_janela_fracionaria_vazia_e_nas_pontas(grande):
    x, p = grande
    r = consultar(p, x, 10.4, 12.2, 100)                     # [10.4, 12.2) -> amostras 10, 11 e 12
    np.testing.assert_array_equal(r.indices, [10, 11, 12])
    assert len(consultar(p, x, 5, 5, 100)) == 0 and len(consultar(p, x, len(x), len(x) + 10, 10)) == 0
    assert len(consultar(p, x, -50, -10, 10)) == 0
    fim = consultar(p, x, len(x) - 900_000, len(x) + 5_000, 800)       # o bloco final incompleto
    b = conferir_envoltoria(fim, x, len(x) - 900_000, len(x), 800)
    assert b[-1] == len(x)
    with pytest.raises(ValueError):
        consultar(p, x, 0, 10, 0)


def test_canal_intercalado_num_memmap(tmp_path):
    canais = [sinal(400_003, semente=c, dtype=np.int16).astype(np.uint16) for c in range(3)]
    caminho = tmp_path / "c.bin"
    caminho.write_bytes(np.stack(canais, axis=1).reshape(-1).tobytes())
    tudo = np.memmap(caminho, dtype=np.uint16, mode="r")
    piramides = construir(tudo, 3)
    for c in range(3):
        visao = tudo[c::3]
        for inicio, fim, colunas in ((0, 400_003, 700), (12_345, 13_000, 1600), (1_000, 300_000, 999)):
            r = consultar(piramides[c], visao, inicio, fim, colunas)
            if isinstance(r, Envoltoria):
                conferir_envoltoria(r, canais[c], inicio, fim, colunas)
            else:
                np.testing.assert_array_equal(r.valores, canais[c][inicio:fim])


def test_ponto_flutuante_com_nan():
    rng = np.random.default_rng(4)
    x = rng.normal(size=200_000)
    x[1_000:1_010] = np.nan
    x[77_777] = 50.0
    (p,) = construir(x)
    env = consultar(p, x, 0, len(x), 100)
    assert np.nanmax(env.maximos) == 50.0 and not np.isnan(env.minimos).any()


def test_aplicar_afim():
    x = np.array([0, 10, -5, 7, 3, -8, 1, 2, 9, -1] * 1000, np.int16)
    (p,) = construir(x)
    env = consultar(p, x, 0, len(x), 10)
    volts = aplicar_afim(env, 0.5, 1.0)
    np.testing.assert_allclose(volts.minimos, env.minimos * 0.5 + 1.0)
    invertido = aplicar_afim(env, -2.0)                       # a escala negativa troca o mínimo e o máximo
    np.testing.assert_allclose(invertido.minimos, env.maximos * -2.0)
    np.testing.assert_allclose(invertido.maximos, env.minimos * -2.0)
    assert np.all(invertido.minimos <= invertido.maximos)
    amostras = aplicar_afim(consultar(p, x, 0, 10, 10), 3.0, -1.0)
    np.testing.assert_allclose(amostras.valores, x[:10] * 3.0 - 1.0)
    assert amostras.valores.dtype == np.float64


def test_consulta_sobre_a_piramide_aberta_do_cache(tmp_path):
    """A pirâmide do cache vem em memmap: a consulta sobre ela dá o mesmo que sobre a recém-construída."""
    from sh_analyzer_gui.dados.cache import CacheDePiramides

    x = sinal(500_000, semente=9)
    (do_cache,) = CacheDePiramides(tmp_path).obter("k", x)
    (nova,) = construir(x)
    for inicio, fim in ((0, 500_000), (1234, 98_765)):
        a, b = consultar(do_cache, x, inicio, fim, 640), consultar(nova, x, inicio, fim, 640)
        np.testing.assert_array_equal(a.bordas, b.bordas)
        np.testing.assert_array_equal(a.minimos, b.minimos)
        np.testing.assert_array_equal(a.maximos, b.maximos)
