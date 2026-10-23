"""Imagens de aliasing por duas taxas (``supraharmonicos.aliasing`` e ``adc_tool.py aliasing``).

Sinais sintéticos com componentes acima da Nyquist amostrados a 400 e a 320 kS/s, como o ADS8688 faria (o filtro dele
age antes da amostragem e atenua igual nas duas capturas: aqui, nada): o real fica no lugar; a imagem muda.
"""

from __future__ import annotations

import csv

import numpy as np
import pytest
from capturas_sinteticas import escrever_bin

from supraharmonicos import cli_aliasing, cli_principal
from supraharmonicos.aliasing import Pico, dobrar, entradas_ambiguas, entradas_possiveis, parear

FS_A, FS_B = 400_000, 320_000
FAIXA_A, FAIXA_B = (2e3, 0.98 * FS_A / 2), (2e3, 0.98 * FS_B / 2)


def test_dobrar_leva_a_entrada_para_a_faixa_de_0_a_nyquist():
    assert dobrar(130e3, FS_A) == 130e3
    assert dobrar(270e3, FS_A) == 130e3 and dobrar(270e3, FS_B) == 50e3
    assert dobrar(530e3, FS_A) == 130e3 and dobrar(670e3, FS_A) == 130e3
    assert dobrar(170e3, FS_B) == 150e3


def test_entradas_possiveis_sao_k_fs_mais_ou_menos_f():
    assert entradas_possiveis(130e3, FS_A, 1e6) == [130e3, 270e3, 530e3, 670e3, 930e3]
    assert all(dobrar(f, FS_A) == pytest.approx(130e3) for f in entradas_possiveis(130e3, FS_A, 3e6))


def test_entradas_que_caem_no_mesmo_lugar_nas_duas_taxas():
    """Com 400 e 320 kS/s, 360 kHz aparece em 40 kHz nas duas: ali duas taxas não separam a imagem do real."""
    ambiguas = entradas_ambiguas(FS_A, FS_B, 150e3, 1e6, 50.0)
    assert (40e3, 360e3) in ambiguas and (120e3, 520e3) in ambiguas
    for x, entrada in ambiguas:
        assert dobrar(entrada, FS_A) == pytest.approx(x) and dobrar(entrada, FS_B) == pytest.approx(x)
        assert entrada > FS_B / 2


def _parear(picos_a, picos_b, tolerancia_db=3.0):
    return parear(picos_a, FS_A, FAIXA_A, picos_b, FS_B, FAIXA_B, 100.0, tolerancia_db, 1e6)


def test_real_fica_no_lugar_e_a_imagem_aponta_a_entrada():
    a = [Pico(60e3, -20.0), Pico(130e3, -40.0)]
    b = [Pico(60e3, -20.1), Pico(50e3, -40.2)]
    real, imagem = _parear(a, b)
    assert real.frequencia_entrada_hz == pytest.approx(60e3) and real.real_em_a and real.real_em_b
    assert real.diagnostico == "real"
    assert imagem.frequencia_entrada_hz == pytest.approx(270e3)
    assert not imagem.real_em_a and not imagem.real_em_b and "270.00 kHz" in imagem.diagnostico


def test_acima_da_nyquist_de_b_o_real_de_a_e_imagem_em_b():
    (c,) = _parear([Pico(170e3, -30.0)], [Pico(150e3, -30.0)])
    assert c.frequencia_entrada_hz == pytest.approx(170e3)
    assert c.real_em_a and not c.real_em_b and c.diagnostico.startswith("real em A; imagem em B")


def test_pico_sem_par_nao_vira_imagem_inventada():
    componentes = _parear([Pico(60e3, -20.0), Pico(99e3, -50.0)], [Pico(60e3, -20.0)])
    sem_par = [c for c in componentes if c.em_b is None]
    assert len(sem_par) == 1 and sem_par[0].em_a.frequencia_hz == 99e3 and sem_par[0].frequencia_entrada_hz is None
    assert "sem par" in sem_par[0].diagnostico


def test_par_ambiguo_fica_com_o_real_e_avisa_da_imagem():
    """40 kHz nas duas taxas: real em 40 kHz ou a imagem de 360 kHz. A entrada mais baixa vale (o filtro do ADC
    atenua a de cima), e a outra sai no aviso."""
    (c,) = _parear([Pico(40e3, -30.0)], [Pico(40e3, -30.0)])
    assert c.frequencia_entrada_hz == pytest.approx(40e3) and c.diagnostico.startswith("real")
    assert any(f == pytest.approx(360e3) for f in c.ambiguas_hz) and "AMBÍGUO" in c.diagnostico


def test_hipotese_com_amplitudes_que_batem_vale_primeiro():
    """Em A, 130 kHz; em B, um pico em 130 kHz bem mais fraco (outra coisa) e um em 50 kHz com a mesma amplitude:
    é a imagem de 270 kHz, e não um real em 130 kHz."""
    componentes = _parear([Pico(130e3, -40.0)], [Pico(130e3, -60.0), Pico(50e3, -40.1)])
    pareado = next(c for c in componentes if c.em_a is not None and c.em_b is not None)
    assert pareado.frequencia_entrada_hz == pytest.approx(270e3) and pareado.amplitudes_batem


def _captura(caminho, fs, tons, dur_s=0.5, seed=0):
    t = np.arange(int(dur_s * fs)) / fs
    v = sum(a * np.sin(2 * np.pi * f * t + 0.3 * k) for k, (f, a) in enumerate(tons))
    v = v + np.random.default_rng(seed).normal(0, 2e-4, len(t))
    return escrever_bin(caminho, [v], canais=(1,), grandezas=(0,), sondas=("",), fs_total=fs, faixas_adc_total_v=5.12)


TONS = [(10e3, 0.5), (60e3, 0.05), (170e3, 0.05), (270e3, 0.05)]


def test_cli_separa_reais_e_imagens_e_grava_o_csv(tmp_path, capsys):
    a = _captura(tmp_path / "A_400k.bin", FS_A, TONS, seed=1)
    b = _captura(tmp_path / "B_320k.bin", FS_B, TONS, seed=2)
    saida = tmp_path / "aliasing.csv"
    assert cli_aliasing.main([str(a), str(b), "--csv", str(saida)]) == 0
    linhas = list(csv.DictReader(saida.open(encoding="utf-8")))
    por_entrada = {round(float(r["entrada_hz"]) / 1e3): r for r in linhas if r["entrada_hz"]}
    assert set(por_entrada) == {10, 60, 170, 270}, linhas
    assert por_entrada[10]["diagnostico"] == "real" and por_entrada[60]["diagnostico"] == "real"
    assert float(por_entrada[270]["a_hz"]) == pytest.approx(130e3, abs=30)
    assert float(por_entrada[270]["b_hz"]) == pytest.approx(50e3, abs=30)
    assert por_entrada[170]["real_em_a"] == "1" and por_entrada[170]["real_em_b"] == "0"
    assert float(por_entrada[170]["b_hz"]) == pytest.approx(150e3, abs=30)
    for r in linhas:                                    # mesma entrada, mesma atenuação: a amplitude bate
        assert abs(float(r["a_db"]) - float(r["b_db"])) < 0.5
    assert "40 kHz (de 360)" in capsys.readouterr().out          # o aviso das frequências que as duas taxas não separam


def test_cli_recusa_duas_capturas_na_mesma_taxa(tmp_path):
    a = _captura(tmp_path / "A.bin", FS_A, TONS[:2])
    b = _captura(tmp_path / "B.bin", FS_A, TONS[:2], seed=3)
    with pytest.raises(SystemExit) as e:
        cli_aliasing.main([str(a), str(b)])
    assert e.value.code == 2


def test_aliasing_e_um_subcomando_do_adc_tool():
    assert "aliasing" in cli_principal.SUBCOMANDOS
    assert "aliasing" in cli_principal.texto_subcomandos()
