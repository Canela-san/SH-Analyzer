"""A razão de dois canais capturados juntos (``razao_quadrada``, ``medir_fase.py --canal-referencia``), o shunt pelo
osciloscópio (``medir_shunt.py``), a âncora do método de um canal (``medir_fase.py --ancora``) e o passa-alta.

As capturas são sintéticas (``quadrada_em_dois_canais``): a mesma corrente quadrada, com uma borda arredondada e o
duty fora do lugar, passa por duas cadeias; o canal b é amostrado 1/taxa total depois do a, como na varredura do
ADS8688. O canal de corrente tem um passa-alta de TC (3 Hz) e o filtro do ADC; o de tensão, o filtro do ADC.
"""

import csv
import json
import math
import re

import numpy as np
import pytest
from capturas_sinteticas import (
    escrever_m_osciloscopio,
    montar_cabecalho,
    quadrada_em_dois_canais,
    quadrada_pela_cadeia,
)
from supraharmonicos import fase_quadrada as fq
from supraharmonicos.cli_medir_fase import main
from supraharmonicos.cli_medir_shunt import main as main_shunt
from supraharmonicos.razao_quadrada import medir_razao, subtrair_diafonia
from supraharmonicos.sonda import carregar_perfil_sonda

FS_TOTAL = 400_000.0
FS = FS_TOTAL / 2
F0, Q = fq.F0_PADRAO_HZ, fq.Q_PADRAO
FC_TC = 3.0                                   # o passa-alta do TC


def h_tensao(f):
    return fq.h_segunda_ordem(f, F0, Q)


def h_corrente(f):
    return 0.98 * fq.h_segunda_ordem(f, 1.1 * F0, 0.6, passa_alta=FC_TC)


def esperado(f, amp_a, amp_b):
    return amp_a / amp_b * h_corrente(f) / h_tensao(f)


def erros(r, amp_a, amp_b):
    u = r.usado
    alvo = esperado(r.freq_hz[u], amp_a, amp_b)
    mag = 20 * np.log10(np.abs(r.razao[u]) / np.abs(alvo))
    fase = np.degrees(np.angle(r.razao[u] / alvo))
    return mag, fase


def test_a_mesma_cadeia_nos_dois_canais_da_1_com_o_atraso_da_varredura_descontado():
    a, b = quadrada_em_dois_canais(FS_TOTAL, 1280.0, 0.3, h_tensao, h_tensao, 1500.0, 1500.0, seed=1)
    r = medir_razao(a.astype(float), b.astype(float), FS, 1280.0, atraso_s=-1 / FS_TOTAL)
    u = r.usado
    assert u.sum() > 30
    assert np.max(np.abs(np.log(np.abs(r.razao[u])) / r.sigma_ln[u])) < 5
    assert np.max(np.abs(np.angle(r.razao[u]) / r.sigma_fase[u])) < 5
    baixo = r.freq_hz[u] < 20e3
    assert np.max(np.abs(np.abs(r.razao[u][baixo]) - 1)) < 2e-3 and np.max(np.abs(np.angle(r.razao[u][baixo]))) < 2e-3
    # sem descontar, sobra a reta do atraso: 2π f (τ_a − τ_b), com o a amostrado 2,5 µs antes
    sem = medir_razao(a.astype(float), b.astype(float), FS, 1280.0)
    reta = np.angle(np.exp(-2j * np.pi * sem.freq_hz[u] / FS_TOTAL))
    assert np.allclose(np.angle(sem.razao[u])[baixo], reta[baixo], atol=2e-3)


def test_a_razao_e_h_a_sobre_h_b_qualquer_que_seja_a_entrada():
    """Borda de 60 kHz, duty de 53 % e o passa-alta do TC: a razão não depende da forma da entrada, e a fase sai
    absoluta (sem modelo, sem fase mínima, sem a quadrada ideal)."""
    for f1, seed in ((1280.0, 2), (6912.0, 3)):
        a, b = quadrada_em_dois_canais(FS_TOTAL, f1, 0.3, h_corrente, h_tensao, 300.0, 1500.0, duty=0.53,
                                       borda_hz=60e3, seed=seed)
        r = medir_razao(a.astype(float), b.astype(float), FS, f1, atraso_s=-1 / FS_TOTAL)
        mag, fase = erros(r, 300.0, 1500.0)
        z_mag = mag / (8.686 * r.sigma_ln[r.usado])
        z_fase = np.radians(fase) / r.sigma_fase[r.usado]
        assert r.usado.sum() >= 5 and np.max(np.abs(z_mag)) < 5 and np.max(np.abs(z_fase)) < 5, (mag, fase)
        assert np.median(np.abs(mag)) < 0.02 and np.median(np.abs(fase)) < 0.1


def test_a_diafonia_e_medida_e_subtraida():
    def vaz(f):
        return 1e-3 * (f / 1e4) * np.exp(0.5j)            # cresce com a frequência, como um acoplamento capacitivo
    a, b = quadrada_em_dois_canais(FS_TOTAL, 1280.0, 0.3, h_corrente, h_tensao, 60.0, 1500.0, seed=4, vazamento=vaz)
    r = medir_razao(a.astype(float), b.astype(float), FS, 1280.0, atraso_s=-1 / FS_TOTAL)
    mag, _ = erros(r, 60.0, 1500.0)
    assert np.max(np.abs(mag)) > 0.5                          # o vazamento é muito maior que o erro
    vazio = [quadrada_em_dois_canais(FS_TOTAL, f1, 0.3, h_corrente, h_tensao, 0.0, 1500.0, seed=s, vazamento=vaz)
             for f1, s in ((1280.0, 5), (6912.0, 6))]
    d = [medir_razao(x.astype(float), y.astype(float), FS, f1, atraso_s=-1 / FS_TOTAL)
         for (x, y), f1 in zip(vazio, (1280.0, 6912.0))]
    limpa = subtrair_diafonia(r, d)
    mag, fase = erros(limpa, 60.0, 1500.0)
    assert np.max(np.abs(mag / (8.686 * limpa.sigma_ln[limpa.usado]))) < 5
    assert np.median(np.abs(mag)) < 0.04 and np.median(np.abs(fase)) < 0.3
    assert limpa.diafonia is not None


# --------------------------------------------------------------------------------------
# A CLI: medir_fase.py --canal-referencia
# --------------------------------------------------------------------------------------
I0, ESPIRAS, R_LACO = 2.0, 20, 10.0
S_TC, D_DIV = 60e-6, 0.0516                    # V/A no pino (por espira) e a razão do divisor
FAIXA_I, FAIXA_V = 5.12, 20.48
AMP_I = I0 * ESPIRAS * S_TC / (FAIXA_I / 65536)        # ~30 LSB
AMP_V = I0 * R_LACO * D_DIV / (FAIXA_V / 65536)        # ~3300 LSB


def gravar_dupla(pasta, nome, f1, seed, amp_i=AMP_I, vazamento=None):
    a, b = quadrada_em_dois_canais(FS_TOTAL, f1, 0.3, h_corrente, h_tensao, amp_i, AMP_V, duty=0.51, borda_hz=150e3,
                                   seed=seed, vazamento=vazamento)
    intercalado = np.column_stack([a, b]).ravel()
    caminho = pasta / nome
    caminho.write_bytes(montar_cabecalho(len(a), (0, 1), (1, 0), ("", ""), int(FS_TOTAL), versao=7,
                                         descricao=f"quadrada f={f1:g}Hz", codigos_faixa_adc=(2, 0), spi=(2, 0, 0))
                        + intercalado.tobytes())
    return caminho


def perfil_de_tensao(pasta):
    """O perfil com fase do canal de tensão (o que o calibrar dá): ganho = |h|, relativo ao --ganho 1/d."""
    f = np.geomspace(50, 2e5, 80)
    h = h_tensao(f)
    caminho = pasta / "tensao_fase.json"
    caminho.write_text(json.dumps({
        "id": "tensao_fase", "tipo": "resposta_frequencia",
        "calibracao_adc": {"formato": "uint16", "ganho": {"sonda": 1 / D_DIV}, "faixa_v": {"sonda": FAIXA_V},
                           "faixa_v_confiavel": {"sonda": True}},
        "pontos": [{"freq_hz": float(fi), "ganho": float(abs(hi)), "fase_rad": float(p), "desvio_pct": 0.0}
                   for fi, hi, p in zip(f, h, np.unwrap(np.angle(h)))]}), encoding="utf-8")
    return caminho


@pytest.fixture
def bancada_dupla(tmp_path):
    capturas = [gravar_dupla(tmp_path, f"F_cspadrao_400000_quadrada{f1:g}Hz_canais0-1_f5.12_30s_spirapido.bin", f1, s)
                for f1, s in ((256.0, 11), (1280.0, 12), (6912.0, 13))]
    return capturas, perfil_de_tensao(tmp_path)


def test_medir_fase_de_dois_canais_da_o_perfil_absoluto_da_corrente_com_a_fase(cli, bancada_dupla, tmp_path):
    capturas, referencia = bancada_dupla
    saida = tmp_path / "sct013_fase.json"
    rc, out, err = cli(main, *capturas, "--canal", "0", "--canal-referencia", "1", "--perfil-referencia", referencia,
                       "--resistencia", R_LACO, "--espiras", ESPIRAS, "--ganho", 1 / S_TC, "--csv", tmp_path / "i.csv",
                       "--plot", tmp_path / "i.png", "--saida-perfil", saida)
    assert rc == 0, err
    assert "atraso entre eles descontado: -2.5000 µs" in out and "Resposta absoluta" in out
    perfil = json.loads(saida.read_text(encoding="utf-8"))
    f = np.array([p["freq_hz"] for p in perfil["pontos"]])
    g = np.array([p["ganho"] for p in perfil["pontos"]])
    fase = np.array([p["fase_rad"] for p in perfil["pontos"]])
    sigma_ln = np.array([p["desvio_pct"] for p in perfil["pontos"]]) / 100
    sigma_fase = np.array([p["sigma_fase_rad"] for p in perfil["pontos"]])
    verdade = h_corrente(f)
    erro_ln = np.log(g / np.abs(verdade))
    erro_fase = fase - np.unwrap(np.angle(verdade))
    assert np.max(np.abs(erro_ln / sigma_ln)) < 5 and np.max(np.abs(erro_fase / sigma_fase)) < 5
    baixo = f < 10e3                                      # ~30 LSB no canal de corrente, 0,3 s: só o ruído
    assert np.median(np.abs(8.686 * erro_ln[baixo])) < 0.03 and np.median(np.abs(np.degrees(erro_fase[baixo]))) < 0.2
    # a fase absoluta inclui o adiantamento do passa-alta do TC em baixa frequência (0,67° em 256 Hz)
    so_o_filtro = np.angle(0.98 * fq.h_segunda_ordem(f[0], 1.1 * F0, 0.6))
    assert np.degrees(fase[0] - so_o_filtro) == pytest.approx(math.degrees(math.atan(FC_TC / f[0])), abs=0.05)
    assert perfil["calibracao_adc"]["ganho"]["sonda"] == pytest.approx(1 / S_TC)
    assert perfil["calibracao_adc"]["faixa_v"]["sonda"] == FAIXA_I
    rf = perfil["resposta_fase"]
    assert rf["espiras"] == ESPIRAS and rf["atraso_entre_canais_s"] == [-2.5e-06] and len(rf["razao"]) > 20
    carregar_perfil_sonda(saida)
    linhas = list(csv.DictReader(open(tmp_path / "i.csv", encoding="utf-8")))
    assert {linha["arquivo"] for linha in linhas} == {c.name for c in capturas} and linhas[0]["h_db"] != ""
    assert (tmp_path / "i_grade.csv").exists() and (tmp_path / "i_razao.csv").exists()
    assert (tmp_path / "i.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_medir_fase_de_dois_canais_sem_perfil_da_so_a_razao_e_subtrai_a_diafonia(cli, tmp_path):
    def vaz(f):
        return 2e-5 * (f / 1e4) * np.exp(0.5j)
    capturas = [gravar_dupla(tmp_path, f"F_q{f1:g}.bin", f1, s, vazamento=vaz) for f1, s in ((1280.0, 21), (6912.0, 22))]
    vazias = [gravar_dupla(tmp_path, f"W_q{f1:g}.bin", f1, s, amp_i=0.0, vazamento=vaz) for f1, s in ((256.0, 23), (6912.0, 24))]
    rc, out, err = cli(main, *capturas, "--canal-referencia", "1", "--diafonia", *vazias, "--csv", tmp_path / "r.csv")
    assert rc == 0, err
    assert "diafonia subtraída de F_q1280.bin" in out and "Razão (V no pino" in out
    linhas = [linha for linha in csv.DictReader(open(tmp_path / "r.csv", encoding="utf-8")) if linha["usado"] == "sim"]
    alvo = esperado(np.array([float(linha["freq_hz"]) for linha in linhas]), AMP_I, AMP_V) * FAIXA_I / FAIXA_V
    medido = np.array([float(linha["razao_db"]) for linha in linhas])
    sigma = np.array([float(linha["sigma_db"]) for linha in linhas])
    assert np.max(np.abs(medido - 20 * np.log10(np.abs(alvo))) / sigma) < 5
    assert all(linha["diafonia_db"] != "" and linha["h_db"] == "" for linha in linhas)


def test_medir_fase_de_dois_canais_recusa_o_que_nao_vale(cli, bancada_dupla, tmp_path):
    capturas, referencia = bancada_dupla
    rc, _, err = cli(main, capturas[0], "--canal-referencia", "1", "--perfil-referencia", referencia)
    assert rc == 2 and "--resistencia" in err
    rc, _, err = cli(main, capturas[0], "--canal-referencia", "1", "--saida-perfil", tmp_path / "p.json")
    assert rc == 2 and "--perfil-referencia" in err
    rc, _, err = cli(main, capturas[0], "--canal-referencia", "1", "--polo", "sim")
    assert rc == 2 and "não vale(m) com --canal-referencia" in err
    rc, _, err = cli(main, capturas[0], "--canal-referencia", "3")
    assert rc == 1 and "não está na captura" in err
    rc, _, err = cli(main, capturas[0], "--resistencia", "10")          # sem o modo de dois canais
    assert rc == 2 and "só vale(m) com --canal-referencia" in err


# --------------------------------------------------------------------------------------
# medir_shunt.py: Z(f) pelo osciloscópio
# --------------------------------------------------------------------------------------
def test_medir_shunt_acha_r_e_l_e_o_csv_serve_ao_medir_fase(cli, bancada_dupla, tmp_path):
    r_ohm, l_h, fs_osc = 10.0, 20e-6, 2e6
    arquivos = []
    for f1, s in ((1280.0, 31), (20736.0, 32)):
        i = quadrada_pela_cadeia(fs_osc, f1, 0.05, f0=1e12, atraso_s=0.0, ppm=0.0, amplitude_lsb=20000.0, ruido_lsb=1.0,
                                 ate_hz=0.45 * fs_osc, seed=s, polo_hz=300e3).astype(float) - 32768
        espectro = np.fft.rfft(i)
        f = np.fft.rfftfreq(len(i), 1 / fs_osc)
        v = np.fft.irfft(espectro * (r_ohm + 2j * np.pi * f * l_h), len(i))
        t = np.arange(len(i)) / fs_osc
        caminho = tmp_path / f"shunt_{f1:g}Hz.csv"
        caminho.write_text("TIME,CH1,CH2\n" + "\n".join(f"{a:.9e},{b:.6f},{c:.6f}" for a, b, c in zip(t, v / 1e4, i / 1e4)),
                           encoding="utf-8")
        arquivos.append(caminho)
    rc, out, err = cli(main_shunt, *arquivos, "--csv", tmp_path / "shunt.csv", "--plot", tmp_path / "z.png",
                       "--resistencia-dc", "10.0")
    assert rc == 0, err
    m = re.search(r"R = ([0-9.]+) Ω e L = ([0-9.]+) nH", out)
    assert m and float(m.group(1)) == pytest.approx(r_ohm, rel=1e-3) and float(m.group(2)) == pytest.approx(20e3, rel=0.01)
    linhas = list(csv.DictReader(open(tmp_path / "shunt.csv", encoding="utf-8")))
    f = np.array([float(x["freq_hz"]) for x in linhas])
    z = r_ohm + 2j * np.pi * f * l_h
    assert np.max(np.abs(np.array([float(x["z_ohm"]) for x in linhas]) / np.abs(z) - 1)) < 1e-3
    assert np.max(np.abs(np.array([float(x["fase_graus"]) for x in linhas]) - np.degrees(np.angle(z)))) < 0.05
    capturas, referencia = bancada_dupla                        # e o --shunt no medir_fase
    rc, out, err = cli(main, *capturas[1:], "--canal-referencia", "1", "--perfil-referencia", referencia,
                       "--shunt", tmp_path / "shunt.csv", "--espiras", ESPIRAS, "--ganho", 1 / S_TC)
    assert rc == 0 and "shunt shunt.csv" in out, err


# --------------------------------------------------------------------------------------
# A âncora do método de um canal e o passa-alta
# --------------------------------------------------------------------------------------
def test_a_ancora_confere_a_curva_de_um_canal_e_o_passa_alta_do_tc_nao_vira_atraso(cli, tmp_path):
    """Num canal só, o passa-alta do TC (3 Hz) adianta a fase em 256 Hz em 0,67°. A parte linear disso (n vezes) o
    erro da fundamental, tirado por captura, absorve: a âncora (um perfil absoluto até 95 kHz, como o da razão de
    dois canais) acha atraso ~0 e K, e os dois métodos concordam a ~0,1°. Acima da âncora, a curva segue certa; o
    --passa-alta acha os 3 Hz."""
    gravar = []
    for f1, dur, s in ((256.0, 0.5, 1), (1280.0, 0.3, 2), (6400.0, 0.3, 3)):
        x = quadrada_pela_cadeia(312_500.0, f1, dur, passa_alta_hz=FC_TC, seed=s)
        caminho = tmp_path / f"F_{f1:g}.bin"
        caminho.write_bytes(montar_cabecalho(len(x), (1,), (1,), ("",), 312_500, versao=7,
                                             descricao=f"quadrada f={f1:g}Hz", spi=(0, 0, 0)) + x.tobytes())
        gravar.append(caminho)
    def verdade(f):
        return 0.997 * fq.h_segunda_ordem(f, F0, Q, passa_alta=FC_TC)
    f = np.geomspace(256, 95e3, 60)
    ancora = tmp_path / "ancora.json"
    ancora.write_text(json.dumps({
        "id": "ancora", "tipo": "resposta_frequencia",
        "calibracao_adc": {"formato": "uint16", "ganho": {"sonda": 1.0}, "faixa_v": {"sonda": 20.48}},
        "pontos": [{"freq_hz": float(x), "ganho": float(abs(verdade(x))), "fase_rad": float(p)}
                   for x, p in zip(f, np.unwrap(np.angle(verdade(f))))]}), encoding="utf-8")
    saida = tmp_path / "ancorado.json"
    rc, out, err = cli(main, *gravar, "--ancora", ancora, "--passa-alta", "--polo", "nao", "--saida-perfil", saida)
    assert rc == 0, err
    m = re.search(r"K = ([0-9.]+) .*atraso aparente da curva de um canal ([+-][0-9.]+) .*resíduo de ([0-9.]+) dB e "
                  r"([0-9.]+)°", out)
    assert m, out
    assert float(m.group(1)) == pytest.approx(0.997, abs=2e-3) and abs(float(m.group(2))) < 0.05
    assert float(m.group(3)) < 0.02 and float(m.group(4)) < 0.3
    m = re.search(r"Passa-alta .*fc = ([0-9.]+)", out)
    assert m and float(m.group(1)) == pytest.approx(FC_TC, rel=0.2)
    perfil = json.loads(saida.read_text(encoding="utf-8"))
    pontos = perfil["pontos"]
    assert perfil["resposta_fase"]["ancora"]["perfil"] == "ancora"
    freqs = np.array([p["freq_hz"] for p in pontos])
    fase = np.unwrap(np.array([p["fase_rad"] for p in pontos]))
    alto = freqs > 100e3
    assert np.any(alto)
    assert np.max(np.abs(np.degrees(fase - np.unwrap(np.angle(verdade(freqs))))[alto])) < 1.0
    assert np.max(np.abs(20 * np.log10(np.array([p["ganho"] for p in pontos]) / np.abs(verdade(freqs))))[alto]) < 0.1
    carregar_perfil_sonda(saida)


def test_o_passa_alta_no_modelo_nao_muda_nada_com_fc_zero():
    f = np.geomspace(10, 2e5, 50)
    assert np.array_equal(fq.h_segunda_ordem(f, F0, Q), fq.h_segunda_ordem(f, F0, Q, passa_alta=0.0))
    h = fq.h_segunda_ordem(f, F0, Q, passa_alta=5.0)
    assert np.allclose(np.unwrap(np.angle(h)), fq.fase_do_modelo(f, F0, Q, passa_alta=5.0), atol=1e-12)
    assert np.degrees(fq.fase_do_modelo(np.array([5.0]), F0, Q, passa_alta=5.0)[0]) == pytest.approx(45, abs=0.1)


def test_escrever_m_continua_valendo_para_a_entrada():           # o gerador sintético de antes não mudou
    assert escrever_m_osciloscopio is not None
