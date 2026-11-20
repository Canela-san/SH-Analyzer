"""As métricas de bancada e o assistente de aliasing (F7.8: ``dados/bancada.py``), sem Qt: os números são os das
CLIs ``medir_captura`` e ``aliasing`` nos mesmos arquivos, e a zona das imagens segue o filtro do ADC."""

import csv
import math

import numpy as np
import pytest
from capturas_sinteticas import escrever_bin
from sh_analyzer_gui.dados import bancada as bc
from sh_analyzer_gui.dados.cadeia import Cadeia, Filtro
from sh_analyzer_gui.dados.espectros import TrechoDoTraco
from sh_analyzer_gui.dados.materializacao import contexto_do_canal
from supraharmonicos import api
from supraharmonicos import cli_aliasing, cli_medir_captura

FS_TOTAL = 400_000


def trecho(captura, canal=0, cadeia=None):
    c = captura.canal(canal)
    return TrechoDoTraco(captura, canal, cadeia or Cadeia(), contexto_do_canal(c, captura=captura), 0, len(c.amostras))


@pytest.fixture
def tom(tmp_path):
    """1 kHz a 9 V de pico (perto do fundo de escala de 20,48 V pp) com o 3º harmônico a −60 dBc e ruído."""
    fs = FS_TOTAL / 2
    t = np.arange(int(fs * 2)) / fs
    rng = np.random.default_rng(8)
    x = 9 * np.sin(2 * np.pi * 1000 * t) + 9e-3 * np.sin(2 * np.pi * 3000 * t) + 2e-3 * rng.standard_normal(len(t))
    caminho = escrever_bin(tmp_path / "tom.bin", [x, 0.1 * x], fs_total=FS_TOTAL, faixas_adc_total_v=20.48)
    return caminho, api.abrir_captura(caminho)


def _csv_da_cli(caminho, tmp_path, canal=0):
    saida = tmp_path / "m.csv"
    assert cli_medir_captura.main([str(caminho), "--csv", str(saida), "--sem-correcao-sonda"]) == 0
    with open(saida, encoding="utf-8") as f:
        return next(linha for linha in csv.DictReader(f) if int(linha["canal"]) == canal)


def test_as_metricas_sao_as_do_medir_captura(tom, tmp_path):
    caminho, captura = tom
    m = bc.medir(trecho(captura))
    cli = _csv_da_cli(caminho, tmp_path)
    e = m.espectro
    assert int(cli["inicio_por_canal"]) == m.inicio and int(cli["amostras_por_canal"]) == m.n_amostras
    for campo, valor in (("freq_tom_hz", e.freq_tom_hz), ("amplitude_pico", e.amplitude_pico),
                         ("thd_db", e.thd_db), ("sinad_db", e.sinad_db), ("snr_db", e.snr_db),
                         ("enob_bits", e.enob_bits), ("sfdr_dbc", e.sfdr_dbc),
                         ("ruido_rms_lsb", e.ruido_rms / m.lsb), ("rms_ca", m.basicas.rms_ac)):
        assert float(cli[campo]) == pytest.approx(valor, rel=1e-4, abs=1e-9), campo
    assert e.tem_tom and e.freq_tom_hz == pytest.approx(1000, abs=0.01)
    assert e.thd_db == pytest.approx(-60, abs=0.3)
    assert m.saturacao == 0 and not m.avisos


def test_com_cadeia_o_aviso_e_sem_a_saturacao(tom):
    _, captura = tom
    m = bc.medir(trecho(captura, cadeia=Cadeia((Filtro(filtro="passa_baixas", cortes=(20_000.0,)),))))
    assert math.isnan(m.saturacao) and any("cadeia" in a for a in m.avisos)


def test_a_zona_das_imagens():
    assert bc.atenuacao_do_adc_db(15_000) == pytest.approx(10 * math.log10(2))
    limite = bc.limite_das_imagens_hz(400_000)
    assert 90_000 < limite < 100_000                      # (f/(fs−f))² = −20 dB: f ≈ 0,24·fs
    assert bc.atenuacao_do_adc_db(400_000 - limite) - bc.atenuacao_do_adc_db(limite) == pytest.approx(20, abs=0.2)
    assert bc.limite_das_imagens_hz(100_000) < bc.limite_das_imagens_hz(400_000)


@pytest.fixture
def duas_taxas(tmp_path):
    """O mesmo sinal em 400 e 320 kS/s (um canal): um tom real de 20 kHz e uma entrada de 250 kHz (as imagens)."""
    caminhos = []
    for fs in (400_000, 320_000):
        t = np.arange(int(fs * 0.5)) / fs
        rng = np.random.default_rng(int(fs))
        x = 1.0 * np.sin(2 * np.pi * 20_000 * t) + 0.3 * np.sin(2 * np.pi * 250_000 * t) \
            + 1e-4 * rng.standard_normal(len(t))
        caminhos.append(escrever_bin(tmp_path / f"a{fs}.bin", [x], canais=(0,), grandezas=(0,), sondas=("",),
                                     fs_total=fs, faixas_adc_total_v=20.48))
    return caminhos


def test_o_aliasing_e_o_da_cli(duas_taxas, tmp_path):
    capturas = [(api.abrir_captura(c), 0) for c in duas_taxas]
    r = bc.aliasing(capturas)
    assert r.taxas_hz == [400_000, 320_000] and r.unidade == "dBV no pino do ADC"
    reais = [c for c in r.componentes if c.frequencia_entrada_hz is not None and all(c.reais)]
    imagens = [c for c in r.componentes if c.frequencia_entrada_hz is not None and not any(c.reais)]
    assert [round(c.frequencia_entrada_hz / 1e3) for c in reais] == [20]
    assert [round(c.frequencia_entrada_hz / 1e3) for c in imagens] == [250]
    assert imagens[0].picos[0].frequencia_hz == pytest.approx(150_000, abs=100)      # 400 − 250
    assert imagens[0].picos[1].frequencia_hz == pytest.approx(70_000, abs=100)       # 320 − 250
    saida = tmp_path / "al.csv"
    assert cli_aliasing.main([*map(str, duas_taxas), "--csv", str(saida)]) == 0
    with open(saida, encoding="utf-8") as f:
        da_cli = list(csv.DictReader(f))
    assert len(da_cli) == len(r.componentes)
    assert [float(x["entrada_hz"]) if x["entrada_hz"] else None for x in da_cli] == pytest.approx(
        [c.frequencia_entrada_hz for c in r.componentes], rel=1e-5)


def test_o_aliasing_recusa_a_mesma_taxa(duas_taxas):
    captura = api.abrir_captura(duas_taxas[0])
    with pytest.raises(api.ErroSHAN, match="mesma taxa"):
        bc.aliasing([(captura, 0), (captura, 0)])
    with pytest.raises(api.ErroSHAN, match="de 2 a"):
        bc.aliasing([(captura, 0)])
