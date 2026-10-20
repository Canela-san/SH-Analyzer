"""Testes de ``relatorio/gerar_figuras.py``: o ajuste do passa-baixa recupera parâmetros conhecidos e as figuras
são geradas (sem LaTeX, para ser rápido e não depender dele no CI)."""

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "relatorio" / "gerar_figuras.py"


@pytest.fixture(scope="module")
def gf():
    spec = importlib.util.spec_from_file_location("gerar_figuras", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo      # os @dataclass do script procuram o próprio módulo aqui
    spec.loader.exec_module(modulo)
    yield modulo
    sys.modules.pop(spec.name, None)


def test_ajuste_de_2a_ordem_recupera_parametros_conhecidos_e_vence_os_outros_modelos(gf):
    rng = np.random.default_rng(1)
    f = np.geomspace(50, 45_000, 48)
    k, f0, q = 0.997, 24_000.0, 0.54
    ganho = 10 ** ((gf.mag_db_ordem2(f, k, f0, q) + rng.normal(0, 0.05, f.size)) / 20)
    ajustes = gf.ajustar_passa_baixa(f, ganho)
    aj = ajustes["ordem2"]
    for valor, verdade, sigma in zip(aj.parametros, (k, f0, q), aj.incertezas):
        assert abs(valor - verdade) < 4 * sigma, (valor, verdade, sigma)
    assert aj.sigma_residuo_db == pytest.approx(0.05, rel=0.3)
    assert aj.bic < ajustes["ordem1"].bic - 10           # 1ª ordem: decisivamente pior
    assert aj.bic < ajustes["ordem2_polo"].bic            # o polo extra não se paga


def test_ajuste_ponderado_usa_as_incertezas_medidas(gf):
    rng = np.random.default_rng(2)
    f = np.geomspace(50, 45_000, 40)
    sigma = np.full(f.size, 0.1)
    ganho = 10 ** ((gf.mag_db_ordem2(f, 1.0, 20_000, 0.7) + rng.normal(0, 0.1, f.size)) / 20)
    aj = gf.ajustar_passa_baixa(f, ganho, sigma)["ordem2"]
    assert aj.pesos_medidos
    chi2_reduzido = float(np.sum((aj.residuos_db / sigma) ** 2)) / (f.size - 3)
    assert 0.5 < chi2_reduzido < 1.6                    # modelo certo e incerteza certa: χ²/ν ~ 1


@pytest.mark.parametrize("q", [0.4, 0.54, 1 / math.sqrt(2), 1.5])
def test_freq_menos_3db_cai_3_db_abaixo_do_patamar(gf, q):
    f3 = gf.freq_menos_3db(10_000.0, q)
    assert gf.mag_db_ordem2(np.array([f3]), 1.0, 10_000.0, q)[0] == pytest.approx(-10 * math.log10(2), abs=1e-9)
    if q == 1 / math.sqrt(2):
        assert f3 == pytest.approx(10_000.0)              # Butterworth: f-3dB = f0


def test_polos_e_incerteza_no_formato_do_siunitx(gf):
    p1, p2 = gf.polos_hz(24_000.0, 0.5)                   # Q = 0,5: polo real duplo em -f0
    assert p1 == pytest.approx(-24_000.0) and p2 == pytest.approx(-24_000.0)
    assert gf.com_incerteza(24_061.9, 212.2, 1e3) == "24.06(21)"
    assert gf.com_incerteza(0.53996, 0.00627) == "0.5400(63)"
    assert gf.com_incerteza(-0.0270, 0.0248) == "-0.027(25)"


def test_gera_a_figura_do_perfil_de_tensao_e_as_macros(gf, tmp_path):
    assert gf.main(["perfil_cadeia_tensao", "--sem-latex", "--saida", str(tmp_path)]) == 0
    pdf = tmp_path / "perfil_cadeia_tensao.pdf"
    assert pdf.read_bytes().startswith(b"%PDF")
    macros = (tmp_path / "perfil_cadeia_tensao.tex").read_text(encoding="utf-8")
    assert r"\CadeiaTensaoFzero}{\qty{" in macros and r"\kilo\hertz" in macros
    assert "Fase NÃO medida" in macros


def test_formato_de_artigo_em_ingles_vai_para_outro_arquivo(gf, tmp_path):
    assert gf.main(["perfil_cadeia_tensao", "--sem-latex", "--formato", "artigo", "--idioma", "en",
                    "--saida", str(tmp_path)]) == 0
    assert (tmp_path / "perfil_cadeia_tensao_artigo_en.pdf").exists()


def test_figura_desconhecida_e_recusada(gf, tmp_path):
    assert gf.main(["nao_existe", "--saida", str(tmp_path)]) == 2
