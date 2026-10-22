"""Testes de ``report/gerar_figuras.py``: o ajuste do passa-baixa recupera parâmetros conhecidos e as figuras
são geradas (sem LaTeX, para ser rápido e não depender dele no CI)."""

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "report" / "gerar_figuras.py"


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
    assert gf.com_incerteza(1.2345, 0.0996) == "1.23(10)"            # incerteza que arredonda para 100 vira 10


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


def test_figura_do_readme_sai_em_svg_transparente_e_igual_a_cada_execucao(gf, tmp_path):
    # Com --saida, a figura do README vai para a pasta pedida (sem ela, iria para docs/images/).
    assert gf.main(["readme_cadeia_tensao", "--sem-latex", "--saida", str(tmp_path / "a")]) == 0
    assert gf.main(["readme_cadeia_tensao", "--sem-latex", "--saida", str(tmp_path / "b")]) == 0
    svg = (tmp_path / "a" / "voltage-chain-response.svg").read_bytes()
    assert svg == (tmp_path / "b" / "voltage-chain-response.svg").read_bytes()   # nada de data nem ids aleatórios
    assert b"<dc:date>" not in svg and b"<text" not in svg                       # texto em curvas
    assert not (tmp_path / "a" / "readme_cadeia_tensao.pdf").exists()


def test_figuras_de_bancada_sem_as_capturas_sao_puladas(gf, tmp_path, monkeypatch, capsys):
    """Sem $DADOS (a CI, outro computador), as figuras do T7f avisam e as outras saem; pedida pelo nome, o código
    de saída é 1."""
    monkeypatch.setattr(gf, "PASTA_T7F", tmp_path / "nada")
    assert gf.main(["grade_teto", "--sem-latex", "--saida", str(tmp_path)]) == 1
    assert "faltam as capturas" in capsys.readouterr().err and not (tmp_path / "grade_teto.pdf").exists()


def test_teto_com_periodo_constante_sai_do_resumo_da_varredura(gf, tmp_path, monkeypatch):
    """A parte J do resumo.csv: a maior taxa sem nenhuma atrasada daí para baixo, onde as amostras comuns começam a
    atrasar e onde todas atrasam; e a menor folga das capturas no padrão."""
    pasta = tmp_path / "T7f"
    pasta.mkdir()
    linhas = ["parte,arquivo,esperas_cs,taxa_pedida_hz,canais,entrada,amostras_atrasadas,buffers_sobrescritos,"
              "quadros_sdo_ruido,taxa_arm_hz,desvio_arm_pct,codigo_saida,folga_ciclos,atraso_max_ciclos",
              'G,g.bin,"padrao",312500,"1",tom,0,0,0,312500,+0.00,0,4,',
              'H,h.bin,"padrao",312500,"1",tom,0,0,0,312500,+0.00,0,3,']
    atrasadas = {640: 0, 639: 0, 638: 1, 637: 0, 636: 5, 635: 2097151}
    for ticks, n in atrasadas.items():
        linhas.append(f'J,j{ticks}.bin,"padrao",{200_000_000 // ticks},"1",tom,{n},0,0,0,+0.00,0,,')
    (pasta / "resumo.csv").write_text("\n".join(linhas) + "\n")
    monkeypatch.setattr(gf, "PASTA_T7F", pasta)
    monkeypatch.setattr(gf, "DADOS", tmp_path)
    assert gf.main(["grade_teto", "--sem-latex", "--saida", str(tmp_path)]) == 0
    macros = (tmp_path / "grade_teto.tex").read_text()
    assert r"\GradeFolgaMin}{3}" in macros
    assert r"\GradeTetoConstante}{\num{313.0}}" in macros                 # 639 ticks: daí para cima, nenhuma
    assert r"\GradeTetoComuns}{\num{314.5}}" in macros                    # 636 ticks: mais de 2 atrasadas
    assert r"\GradeTetoTodas}{\num{315.0}}" in macros                     # 635 ticks: todas


def test_comparacao_dos_perfis_de_tensao_mostra_a_mesma_cadeia(gf, tmp_path):
    """T3 de 22/10 (312,5 kS/s, ±2,56 V, até 140 kHz) contra o de 19/10 (100 kS/s, ±10,24 V, até 45 kHz): a mesma
    cadeia, a ~0,1 dB nas frequências em comum, e o 2ª ordem ainda vale até 140 kHz."""
    assert gf.main(["perfil_cadeia_tensao_comparacao", "--sem-latex", "--saida", str(tmp_path)]) == 0
    macros = (tmp_path / "perfil_cadeia_tensao_comparacao.tex").read_text(encoding="utf-8")
    dif = float(macros.split(r"\CadeiaTensaoDifRms}{\qty{")[1].split("}")[0])
    assert dif < 0.2
    assert r"\CadeiaTensaoNovaFmax}{\qty{140}" in macros
    residuo = float(macros.split(r"\CadeiaTensaoNovaResiduo}{\qty{")[1].split("}")[0])
    assert residuo < 0.2


def test_grade_bits_recupera_a_duracao_do_quadro_de_uma_varredura_sintetica(gf, tmp_path, monkeypatch):
    """Uma varredura J feita com um quadro de 605 + (bits 1) ciclos: a figura acha 605 e a razão medida/prevista ~1."""
    from capturas_sinteticas import montar_cabecalho

    pasta = tmp_path / "T7f"
    pasta.mkdir()
    n = 1 << 16
    codigos = (32768 + 6000 * np.sin(2 * np.pi * 0.01234 * np.arange(n))).astype("<u2")    # cruza o meio da escala
    cab = montar_cabecalho(n, (1,), (1,), ("",), 312500, versao=6, amostras_por_buffer=n // 2, blocos=2)
    (pasta / "J_cspadrao_312500_tom.bin").write_bytes(cab + codigos.tobytes())
    bits = np.unpackbits(codigos[1:].view(np.uint8)).reshape(-1, 16).sum(axis=1)
    linhas = ["parte,arquivo,esperas_cs,taxa_pedida_hz,canais,entrada,amostras_atrasadas,buffers_sobrescritos,"
              "quadros_sdo_ruido,taxa_arm_hz,desvio_arm_pct,codigo_saida,folga_ciclos,atraso_max_ciclos"]
    for ticks in range(630, 605, -1):
        atrasadas = int(np.sum(605 + bits > ticks))
        linhas.append(f'J,j{ticks}.bin,"padrao",{200_000_000 // ticks},"1",tom,{atrasadas},0,0,0,+0.00,0,,')
    (pasta / "resumo.csv").write_text("\n".join(linhas) + "\n")
    monkeypatch.setattr(gf, "PASTA_T7F", pasta)
    monkeypatch.setattr(gf, "DADOS", tmp_path)
    assert gf.main(["grade_bits", "--sem-latex", "--saida", str(tmp_path)]) == 0
    macros = (tmp_path / "grade_bits.tex").read_text()
    assert r"\GradeBitsBase}{605}" in macros
    for nome in ("GradeBitsRazaoMin", "GradeBitsRazaoMax"):
        assert float(macros.split(rf"\{nome}}}{{\num{{")[1].split("}")[0]) == pytest.approx(1.0, abs=0.02)
