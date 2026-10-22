"""A fase (e a magnitude) da cadeia por ondas quadradas, sem osciloscópio: ``fase_quadrada`` e ``medir_fase.py`` (S2).

As capturas são sintéticas (``quadrada_pela_cadeia``): a quadrada passa pelo 2ª ordem do T3 e por um atraso puro, o
gerador anda 43 ppm à frente da PRU, os harmônicos acima da Nyquist dobram, e há ruído e quantização. Curtas (0,3 s)
para o teste ser rápido; na bancada são 10 s, com ~6 vezes menos ruído.
"""

import csv
import json

import numpy as np
import pytest
from capturas_sinteticas import montar_cabecalho, quadrada_pela_cadeia
from supraharmonicos import fase_quadrada as fq
from supraharmonicos.cli_medir_fase import main
from supraharmonicos.sonda import carregar_perfil_sonda

FS = 312_500.0
F0, Q = fq.F0_PADRAO_HZ, fq.Q_PADRAO


def medir(f1=1280.0, fs=FS, dur=0.3, **kw):
    return fq.medir_quadrada(quadrada_pela_cadeia(fs, f1, dur, **kw).astype(float), fs)


def erros(r: fq.RespostaQuadrada, f0=F0, q=Q):
    """(erro de fase em graus, erro de magnitude em dB), nos harmônicos usados."""
    u = r.usado
    fase = np.degrees(r.fase_rel_rad - fq.fase_relativa_modelo(r.freq_hz, r.f1_hz, f0, q))[u]
    rel = np.abs(fq.h_segunda_ordem(r.freq_hz, f0, q)) / abs(fq.h_segunda_ordem(r.f1_hz, f0, q))
    return fase, 20 * np.log10(r.ganho_rel / rel)[u]


def test_fase_e_magnitude_da_cadeia_sem_referencia_externa():
    r = medir()
    fase, mag = erros(r)
    assert r.usado.sum() >= 55 and r.freq_hz[r.usado][-1] > 140e3
    assert np.max(np.abs(fase)) < 0.3 and np.max(np.abs(mag)) < 0.05
    # a 140 kHz a fase relativa passa de 400°: só a referência interna da quadrada a mede sem ambiguidade
    assert np.degrees(r.fase_rel_rad[r.usado][-1]) > 400


def test_um_atraso_puro_nao_muda_a_medida():
    """A conversão do ADC e o instante da amostra são atrasos puros: somem de arg Xₙ − n·arg X₁."""
    a = medir(atraso_s=0.0, seed=5)
    b = medir(atraso_s=20e-6, seed=5)
    diferenca = np.abs(np.degrees(a.fase_rel_rad - b.fase_rel_rad))[a.usado & b.usado]
    # 20 µs que não sumissem seriam 2π·140 kHz·20 µs ≈ 1000° no último harmônico; sobra só o ruído das capturas curtas
    assert np.max(diferenca) < 1.0 and np.mean(diferenca) < 0.1


def test_quadrada_invertida_da_a_mesma_fase():
    x = quadrada_pela_cadeia(FS, 1280.0, 0.3, seed=3)
    a = fq.medir_quadrada(x.astype(float), FS)
    b = fq.medir_quadrada((65535 - x).astype(float), FS)
    assert np.max(np.abs(np.degrees(a.fase_rel_rad - b.fase_rel_rad))) < 0.01


def test_o_duty_e_estimado_e_corrigido_na_magnitude_e_nao_muda_a_fase():
    r = medir(duty=0.503, seed=7)
    assert r.duty_desvio == pytest.approx(0.003, abs=2e-4)
    fase, mag = erros(r)
    assert np.max(np.abs(fase)) < 0.5 and np.max(np.abs(mag)) < 0.15
    sem_correcao = r.ganho_rel * np.abs(np.cos(np.pi * r.n * r.duty_desvio))     # o que daria ignorar o duty
    rel = np.abs(fq.h_segunda_ordem(r.freq_hz, F0, Q)) / abs(fq.h_segunda_ordem(r.f1_hz, F0, Q))
    assert np.max(np.abs(20 * np.log10(sem_correcao / rel))) > 1.0


def test_harmonico_perto_de_um_nulo_do_duty_fica_de_fora():
    r = medir(f1=256.0, duty=0.501, dur=0.5, seed=2)
    perto = np.abs(np.cos(np.pi * r.n * r.duty_desvio)) < fq.FATOR_DUTY_MINIMO
    assert np.any(perto) and not np.any(r.usado[perto])
    assert any("nulo do duty" in m for m in r.motivo)


def test_aliasing_sobre_um_harmonico_e_previsto_e_descartado():
    """Taxa/f₁ par (312,5 kS/s com 1250 Hz) e os dois relógios iguais: os harmônicos perto da taxa dobram em cima dos
    ímpares medidos. Com 1280 Hz (taxa/f₁ = 244,14), nenhum."""
    ruim = medir(f1=1250.0, ppm=0.0, seed=4)
    assert any(m.startswith("aliasing") for m in ruim.motivo)
    fase, _ = erros(ruim)
    assert np.max(np.abs(fase)) < 0.5                    # o que sobrou está limpo
    bom = medir(f1=1280.0, ppm=0.0, seed=4)
    assert not any(m.startswith("aliasing") for m in bom.motivo)


def test_ajuste_recupera_f0_e_q_pela_fase_sozinha_e_pela_magnitude():
    medidas = [medir(f1=1280.0, seed=1), medir(f1=6400.0, seed=2)]
    for usar_mag, usar_fase in ((True, True), (True, False), (False, True)):
        aj = fq.ajustar_segunda_ordem(medidas, usar_mag, usar_fase, f0_inicial=20000, q_inicial=0.7)
        assert aj.f0_hz == pytest.approx(F0, rel=1e-3) and aj.q == pytest.approx(Q, rel=1e-3), aj


def test_fase_absoluta_supondo_fase_minima_e_a_do_filtro():
    r = medir(seed=9)
    psi = fq.fase_absoluta(r, F0, Q)
    verdade = np.unwrap(np.angle(fq.h_segunda_ordem(r.freq_hz, F0, Q)))
    assert np.max(np.abs(np.degrees(psi - verdade)[r.usado])) < 0.3


def test_quadrada_rapida_demais_e_recusada():
    with pytest.raises(fq.ErroSHAN, match="harmônico"):
        fq.medir_quadrada(quadrada_pela_cadeia(FS, 60_000.0, 0.05).astype(float), FS)


# --------------------------------------------------------------------------------------
# A CLI: medir_fase.py
# --------------------------------------------------------------------------------------
def gravar(pasta, nome, fs, f1, spi=0, **kw):
    x = quadrada_pela_cadeia(float(fs), f1, 0.3, **kw)
    caminho = pasta / nome
    caminho.write_bytes(montar_cabecalho(len(x), (1,), (0,), ("",), int(fs), versao=7,
                                         descricao=f"quadrada f={f1:g}Hz", spi=(spi, 0, 0)) + x.tobytes())
    return caminho


@pytest.fixture
def capturas(tmp_path):
    return [gravar(tmp_path, "F_312500_q1280.bin", 312_500, 1280.0, seed=1),
            gravar(tmp_path, "F_400000_q1280.bin", 400_000, 1280.0, spi=2, seed=2)]


def test_medir_fase_ajusta_grava_csv_grafico_e_perfil_com_fase(cli, capturas, tmp_path):
    saida = tmp_path / "cadeia_fase.json"
    rc, out, err = cli(main, *capturas, "--csv", tmp_path / "fase.csv", "--plot", tmp_path / "bode.png",
                       "--perfil-base", "scripts/sondas/cadeia_tensao_312k.json", "--saida-perfil", saida)
    assert rc == 0, err
    assert "400 kS/s (SPI rápido)" in out and "FASE MÍNIMA" in out
    linhas = list(csv.DictReader(open(tmp_path / "fase.csv", encoding="utf-8")))
    assert {linha["arquivo"] for linha in linhas} == {c.name for c in capturas}
    assert all(linha["usado"] in ("sim", "não") for linha in linhas)
    assert (tmp_path / "bode.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    perfil = json.loads(saida.read_text(encoding="utf-8"))
    assert perfil["id"] == "cadeia_fase" and perfil["resposta_fase"]["segunda_ordem"]["f0_hz"] == pytest.approx(F0, rel=2e-3)
    medidos = [p for p in perfil["pontos"] if "sigma_fase_rad" in p]
    assert len(medidos) > 60 and all("fase_rad" in p for p in perfil["pontos"])
    assert perfil["faixa_freq_valida_hz"][0] < 100 and perfil["faixa_freq_valida_hz"][1] > 180e3   # base + quadradas
    carregado = carregar_perfil_sonda(saida)               # a correção de magnitude de sempre continua valendo
    alto = carregado.ganho_em(np.array([100e3]))[0]
    assert alto == pytest.approx(0.998 * abs(fq.h_segunda_ordem(100e3, F0, Q)), rel=0.01)


def test_medir_fase_avisa_quando_a_cadeia_nao_e_um_segundo_ordem(cli, tmp_path):
    """Com um polo real a 60 kHz a mais, a magnitude e a fase pedem filtros diferentes: o aviso diz para usar a fase
    medida, e não a de um modelo."""
    arquivos = [gravar(tmp_path, f"F_{f1}.bin", 312_500, f1, polo_hz=60e3, seed=s)
                for f1, s in ((1280.0, 1), (6400.0, 2))]
    rc, out, err = cli(main, *arquivos)
    assert rc == 0 and "NÃO dão o mesmo filtro" in err


def test_medir_fase_saida_de_perfil_pede_o_perfil_base(cli, capturas, tmp_path):
    rc, _, err = cli(main, capturas[0], "--saida-perfil", tmp_path / "p.json")
    assert rc == 2 and "--perfil-base" in err
