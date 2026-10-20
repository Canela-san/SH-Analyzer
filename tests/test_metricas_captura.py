"""``metricas_captura`` e ``medir_captura.py``: as métricas contra sinais de valor CONHECIDO.

Cada teste sintetiza um sinal cuja resposta correta é exata (amplitude, nível do harmônico,
densidade de ruído, atraso entre canais, amostra removida...) e confere o número medido com a
tolerância que o método realmente tem. Nada aqui depende de hardware."""

import csv
import json
import math

import numpy as np
import pytest
from capturas_sinteticas import (
    FAIXA,
    FREQS_CAL,
    SENS_NOMINAL,
    escrever_bin,
    escrever_m_osciloscopio,
    planta_h,
    volts_para_codigos,
)
from supraharmonicos.cli_medir_captura import COLUNAS_CSV, main
from supraharmonicos.erros import ErroSHAN
from supraharmonicos.metricas_captura import (
    analisar_espectro,
    calcular_acoplamento,
    calcular_basicas,
    fracao_saturada,
    projetar_tom,
    verificar_continuidade,
)

FS = 400_000.0
N = 1 << 20


def tempo(n=N, fs=FS):
    return np.arange(n) / fs


def seno(f, amplitude, n=N, fs=FS, fase=0.0):
    return amplitude * np.sin(2 * np.pi * f * tempo(n, fs) + fase)


@pytest.fixture
def rng():
    return np.random.default_rng(42)


# ---------------------------------------------------------------------------
# Tom, ruído, estatísticas
# ---------------------------------------------------------------------------

class TestTomERuido:
    def test_frequencia_e_amplitude_do_tom_fora_do_bin(self, rng):
        sinal = seno(12_345.6, 2.0) + 0.5 + rng.normal(0, 1e-3, N)
        e = analisar_espectro(sinal, FS)
        assert e.tem_tom
        assert e.freq_tom_hz == pytest.approx(12_345.6, abs=0.05)
        assert e.amplitude_pico == pytest.approx(2.0, rel=1e-3)
        assert e.amplitude_rms == pytest.approx(2.0 / math.sqrt(2), rel=1e-3)

    def test_densidade_e_ruido_rms_batem_com_o_sigma_injetado(self, rng):
        sigma = 1e-3
        e = analisar_espectro(seno(5_000.0, 1.0) + rng.normal(0, sigma, N), FS)
        assert e.densidade_ruido == pytest.approx(sigma * math.sqrt(2.0 / FS), rel=0.03)
        assert e.ruido_rms == pytest.approx(sigma, rel=0.02)
        # SNR = potência do tom / potência do ruído
        assert e.snr_db == pytest.approx(10 * math.log10((1.0 / 2) / sigma ** 2), abs=0.3)

    def test_sem_tom_so_mede_o_piso(self, rng):
        ruido = rng.normal(0, 2e-3, N)
        for procurar in (True, False):
            e = analisar_espectro(ruido, FS, procurar_tom=procurar)
            assert not e.tem_tom
            assert e.ruido_rms == pytest.approx(2e-3, rel=0.02)

    def test_dica_de_frequencia_escolhe_o_tom_fraco_entre_dois(self, rng):
        sinal = seno(60.0, 5.0) + seno(10_000.0, 0.05) + rng.normal(0, 1e-4, N)
        assert analisar_espectro(sinal, FS).freq_tom_hz == pytest.approx(60.0, abs=0.1)
        e = analisar_espectro(sinal, FS, freq_dica=10_000.0)
        assert e.freq_tom_hz == pytest.approx(10_000.0, abs=0.1)
        assert e.amplitude_pico == pytest.approx(0.05, rel=1e-2)

    def test_poucas_amostras_e_erro(self):
        with pytest.raises(ErroSHAN, match="mínimo"):
            analisar_espectro(np.zeros(1000), FS)

    def test_basicas(self):
        b = calcular_basicas(seno(1000.0, 2.0, n=400_000) + 0.25, FS, lsb=1e-4)
        assert b.media == pytest.approx(0.25, abs=1e-3)
        assert b.rms_ac == pytest.approx(2.0 / math.sqrt(2), rel=1e-3)
        assert b.pico_a_pico == pytest.approx(4.0, rel=1e-3)
        assert b.rms_ac_lsb == pytest.approx(b.rms_ac / 1e-4)
        assert b.duracao_s == pytest.approx(1.0)

    def test_fracao_saturada(self):
        codigos = np.array([0, 1, 2, 65535, 5, 65535, 7, 8], dtype=np.uint16)
        assert fracao_saturada(codigos, "uint16") == pytest.approx(3 / 8)
        assert fracao_saturada(np.array([-32768, 0, 32767, 5], dtype=np.int16), "int16") == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Distorção
# ---------------------------------------------------------------------------

class TestDistorcao:
    def test_harmonicos_e_thd_contra_niveis_injetados(self, rng):
        f0 = 12_345.6
        sinal = (seno(f0, 2.0) + seno(2 * f0, 2.0 * 10 ** (-70 / 20)) + seno(3 * f0, 2.0 * 10 ** (-60 / 20))
                 + rng.normal(0, 1e-3, N))
        e = analisar_espectro(sinal, FS)
        niveis = {h.ordem: h for h in e.harmonicos}
        assert niveis[2].nivel_dbc == pytest.approx(-70.0, abs=0.3)
        assert niveis[3].nivel_dbc == pytest.approx(-60.0, abs=0.3)
        assert niveis[3].freq_hz == pytest.approx(3 * f0, abs=0.5)
        assert math.isinf(niveis[5].nivel_dbc)                      # abaixo do piso de ruído
        assert e.thd_db == pytest.approx(10 * math.log10(1e-6 + 1e-7), abs=0.3)
        assert e.thd_pct == pytest.approx(100 * math.sqrt(1.1e-6), rel=0.05)
        assert e.sfdr_dbc == pytest.approx(60.0, abs=0.5) and e.ordem_espurio == 3

    def test_harmonico_acima_de_nyquist_e_medido_dobrado(self, rng):
        f0 = 120_000.0                                  # 2f0 = 240 kHz > Nyquist (200 kHz) -> aparece em 160 kHz
        e = analisar_espectro(seno(f0, 2.0) + seno(160_000.0, 2.0 * 10 ** (-60 / 20)) + rng.normal(0, 1e-3, N), FS)
        h2 = next(h for h in e.harmonicos if h.ordem == 2)
        assert h2.aliasado and h2.freq_hz == pytest.approx(160_000.0, abs=1.0)
        assert h2.nivel_dbc == pytest.approx(-60.0, abs=0.5)

    def test_espurio_que_nao_e_harmonico(self, rng):
        sinal = seno(12_345.6, 2.0) + seno(77_000.0, 2.0 * 10 ** (-70 / 20)) + rng.normal(0, 3e-4, N)
        e = analisar_espectro(sinal, FS)
        assert e.sfdr_dbc == pytest.approx(70.0, abs=0.6)
        assert e.freq_espurio_hz == pytest.approx(77_000.0, abs=2.0)
        assert e.ordem_espurio is None

    def test_senoide_quantizada_em_16_bits_da_enob_perto_de_16(self):
        # Só a quantização do ADC: SINAD ideal = 6,02·16 + 1,76 dB (+ 20·log10(0,98) para um tom a 98 % do fundo de escala).
        v = seno(12_345.6, 0.98 * FAIXA / 2, n=1 << 21)
        quantizado = (volts_para_codigos(v).astype(np.float64) - 32768.0) * (FAIXA / 65536.0)
        e = analisar_espectro(quantizado, FS, fundo_escala_pp=FAIXA)
        assert e.sinad_db == pytest.approx(6.02 * 16 + 1.76 + 20 * math.log10(0.98), abs=0.5)
        assert e.enob_bits == pytest.approx(16.0, abs=0.1)

    @pytest.mark.parametrize("f0", [12_345.6, 12_345.7, 5_000.33, 150_000.17])
    def test_o_piso_do_proprio_metodo_fica_bem_abaixo_do_ruido_de_16_bits(self, f0):
        # Senoide ideal em ponto flutuante (sem ruído algum): tudo o que sobra é vazamento da janela.
        # Com a Blackman-Harris isto dava SINAD 87-96 dB, e o ENOB de um ADC de 16 bits sairia ~1,5 bit pior.
        e = analisar_espectro(seno(f0, 4.0, n=1 << 21), FS)
        assert e.sinad_db > 105.0
        assert e.sfdr_dbc > 110.0

    def test_enob_corrige_o_fundo_de_escala(self, rng):
        sinal = seno(10_000.0, 0.5) + rng.normal(0, 1e-3, N)
        sem = analisar_espectro(sinal, FS)
        com = analisar_espectro(sinal, FS, fundo_escala_pp=FAIXA)
        # tom de 1 V pp num fundo de escala de 10,24 V pp: a correção soma 20·log10(10,24/1)/6,02 ≈ 3,4 bits
        assert com.enob_bits - sem.enob_bits == pytest.approx(20 * math.log10(FAIXA / 1.0) / 6.02, abs=0.01)


# ---------------------------------------------------------------------------
# Continuidade e acoplamento
# ---------------------------------------------------------------------------

class TestContinuidade:
    def test_captura_limpa_nao_tem_salto(self, rng):
        c = verificar_continuidade(seno(12_345.6, 2.0) + rng.normal(0, 1e-3, N), FS, 12_345.6)
        assert c is not None and c.saltos_acima_do_limite == 0 and c.salto_max_amostras < 0.05

    @pytest.mark.parametrize("operacao", ["perde", "duplica"])
    def test_uma_amostra_perdida_ou_duplicada_aparece_como_salto_de_uma_amostra(self, rng, operacao):
        sinal = seno(12_345.6, 2.0) + rng.normal(0, 1e-3, N)
        corte = 600_000
        sinal = np.delete(sinal, corte) if operacao == "perde" else np.insert(sinal, corte, sinal[corte])
        c = verificar_continuidade(sinal, FS, 12_345.6)
        assert c.saltos_acima_do_limite == 1
        assert c.salto_max_amostras == pytest.approx(1.0, abs=0.15)
        assert abs(c.indice_salto_max - corte) <= 2 * c.amostras_por_segmento

    def test_captura_curta_demais_nao_e_verificada(self):
        assert verificar_continuidade(seno(12_345.6, 2.0, n=100_000), FS, 12_345.6) is None

    def test_tom_de_baixa_frequencia_aumenta_o_segmento(self):
        c = verificar_continuidade(seno(50.0, 2.0, n=1 << 21), FS, 50.0)
        assert c.amostras_por_segmento >= 10 * FS / 50.0


class TestAcoplamento:
    def test_projecao_recupera_amplitude_e_fase(self):
        amplitude, fase = projetar_tom(seno(10_000.0, 1.5, fase=0.7), FS, 10_000.0)
        assert amplitude == pytest.approx(1.5, rel=1e-3)
        assert fase == pytest.approx(0.7 - math.pi / 2, abs=1e-3)          # sin(x+φ) = cos(x+φ-π/2)

    def test_atraso_entre_canais_multiplexados(self):
        fs_total, f = 2 * FS, 25_000.0                                        # 2 canais -> 400 kS/s por canal... fs_canal = FS
        n = 1 << 18
        a = seno(f, 1.0, n=n)
        b = np.sin(2 * np.pi * f * (np.arange(n) / FS + 1.0 / fs_total))      # canal na posição 1: amostrado 1/fs_total depois
        tons = {0: projetar_tom(a, FS, f), 1: projetar_tom(b, FS, f)}
        (acopl,) = calcular_acoplamento(tons, {0: 0, 1: 1}, f, fs_total)
        assert acopl.atraso_esperado_us == pytest.approx(1e6 / fs_total)
        assert acopl.atraso_medido_us == pytest.approx(acopl.atraso_esperado_us, rel=0.02)
        assert acopl.diafonia_db == pytest.approx(0.0, abs=0.05)

    def test_diafonia_de_um_canal_em_curto(self, rng):
        n = 1 << 19
        tons = {0: projetar_tom(seno(10_000.0, 2.0, n=n), FS, 10_000.0),
                1: projetar_tom(seno(10_000.0, 2e-3, n=n) + rng.normal(0, 1e-5, n), FS, 10_000.0)}
        (acopl,) = calcular_acoplamento(tons, {0: 0, 1: 1}, 10_000.0, 2 * FS)
        assert acopl.canal == 1 and acopl.canal_agressor == 0
        assert acopl.diafonia_db == pytest.approx(-60.0, abs=0.3)

    def test_um_canal_so_nao_tem_acoplamento(self):
        assert calcular_acoplamento({0: (1.0, 0.0)}, {0: 0}, 1000.0, FS) == []


# ---------------------------------------------------------------------------
# CLI (mesmo processo)
# ---------------------------------------------------------------------------

def ler_csv(caminho):
    with open(caminho, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def pasta(tmp_path_factory):
    base = tmp_path_factory.mktemp("medir")
    rng = np.random.default_rng(7)
    f0 = 12_345.6
    um = seno(f0, 2.0) + seno(3 * f0, 2.0 * 10 ** (-60 / 20)) + rng.normal(0, 5e-4, N)
    escrever_bin(base / "um_canal.bin", [um], canais=(3,), grandezas=(0,), sondas=("",), fs_total=int(FS), titulo="T3 senoide")
    # 2 canais intercalados: tom no 0, canal 1 em curto (ruído + 0,1 % de diafonia); fs_total = 2·FS
    n = 1 << 19
    agressor = seno(f0, 2.0, n=n, fs=FS) + rng.normal(0, 5e-4, n)
    vitima = seno(f0, 2e-3, n=n, fs=FS) + rng.normal(0, 5e-4, n)
    escrever_bin(base / "dois_canais.bin", [agressor, vitima], canais=(0, 1), grandezas=(0, 0), sondas=("", ""),
                 fs_total=int(2 * FS))
    escrever_bin(base / "sem_cabecalho.bin", [um[:1 << 18]], canais=(1,), grandezas=(0,), sondas=("",),
                 com_cabecalho=False)
    escrever_bin(base / "ceifado.bin", [np.clip(seno(f0, 6.0, n=1 << 18), -FAIXA / 2, FAIXA / 2 - 1e-3)], canais=(1,),
                 grandezas=(0,), sondas=("",), fs_total=int(FS))
    return base


class TestCli:
    def test_um_canal_imprime_o_relatorio_e_grava_o_csv(self, cli, pasta):
        saida = pasta / "r1.csv"
        rc, out, err = cli(main, pasta / "um_canal.bin", "--csv", saida)
        assert rc == 0, err
        for trecho in ("T3 senoide", "Canal 3", "THD (H2..H9)", "SINAD / SNR / ENOB", "SFDR", "continuidade          : OK",
                       "Nyquist por canal 200000"):
            assert trecho in out, trecho
        (linha,) = ler_csv(saida)
        assert list(linha) == COLUNAS_CSV
        assert linha["rotulo"] == "T3 senoide" and linha["canal"] == "3" and linha["grandeza"] == "tensão"
        assert float(linha["freq_tom_hz"]) == pytest.approx(12_345.6, abs=0.1)
        assert float(linha["amplitude_pico"]) == pytest.approx(2.0, rel=2e-3)
        assert float(linha["thd_db"]) == pytest.approx(-60.0, abs=0.5)
        assert float(linha["ruido_rms_lsb"]) == pytest.approx(5e-4 / (FAIXA / 65536), rel=0.1)
        assert linha["diafonia_db"] == ""                                  # 1 canal só: não há acoplamento

    def test_varias_capturas_terminam_com_uma_tabela_resumo(self, cli, pasta):
        rc, out, err = cli(main, pasta / "um_canal.bin", pasta / "dois_canais.bin")
        assert rc == 0, err
        resumo = out[out.index("Resumo (3 canais medidos"):].splitlines()
        assert "SINAD dB" in resumo[1] and "salto (amostras)" in resumo[1]
        assert [linha.split()[:2] for linha in resumo[2:5]] == [["um_canal.bin", "3"], ["dois_canais.bin", "0"],
                                                                ["dois_canais.bin", "1"]]
        assert "12345.6" in resumo[2]                                       # o tom, com 4 casas

    def test_uma_captura_so_nao_tem_tabela_resumo(self, cli, pasta):
        rc, out, _ = cli(main, pasta / "um_canal.bin")
        assert rc == 0 and "Resumo (" not in out

    def test_csv_acumula_linhas_com_um_unico_cabecalho(self, cli, pasta, tmp_path):
        saida = tmp_path / "r.csv"
        for rotulo in ("A", "B"):
            assert cli(main, pasta / "um_canal.bin", "--rotulo", rotulo, "--csv", saida)[0] == 0
        assert [linha["rotulo"] for linha in ler_csv(saida)] == ["A", "B"]
        assert saida.read_text(encoding="utf-8").count("arquivo,rotulo") == 1

    def test_csv_existente_com_outras_colunas_e_recusado(self, cli, pasta, tmp_path):
        saida = tmp_path / "velho.csv"
        saida.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
        rc, _, err = cli(main, pasta / "um_canal.bin", "--csv", saida)
        assert rc == 1 and "outras colunas" in err
        assert saida.read_text(encoding="utf-8") == "a,b,c\n1,2,3\n"

    def test_dois_canais_dao_diafonia_e_atraso(self, cli, pasta, tmp_path):
        saida = tmp_path / "r2.csv"
        rc, out, err = cli(main, pasta / "dois_canais.bin", "--csv", saida)
        assert rc == 0, err
        assert "Acoplamento entre canais" in out
        por_canal = {linha["canal"]: linha for linha in ler_csv(saida)}
        assert set(por_canal) == {"0", "1"}
        assert float(por_canal["1"]["diafonia_db"]) == pytest.approx(-60.0, abs=0.5)
        assert float(por_canal["1"]["atraso_esperado_us"]) == pytest.approx(1e6 / (2 * FS))
        assert por_canal["0"]["diafonia_db"] == ""                         # o agressor não tem diafonia

    def test_canais_medir_escolhe_um_subconjunto(self, cli, pasta, tmp_path):
        saida = tmp_path / "r3.csv"
        rc, out, _ = cli(main, pasta / "dois_canais.bin", "--canais-medir", "1", "--freq", "12345", "--csv", saida)
        assert rc == 0 and "Canal 0" not in out
        assert [linha["canal"] for linha in ler_csv(saida)] == ["1"]

    def test_sem_cabecalho_exige_a_frequencia(self, cli, pasta):
        rc, _, err = cli(main, pasta / "sem_cabecalho.bin")
        assert rc == 1 and "-f/--frequencia" in err
        rc, out, _ = cli(main, pasta / "sem_cabecalho.bin", "-f", int(FS))
        assert rc == 0 and "Canal 1" in out

    def test_fs_pru_usa_os_ticks_do_cabecalho(self, cli, pasta, tmp_path):
        # o cabeçalho sintético grava sample_period_ticks = 500 (200 MHz/500 = 400 kHz) -- o cabeçalho de
        # 'um_canal.bin' pede 400 kHz, então as duas frequências coincidem; num arquivo que PEDE outra, divergem:
        n = 1 << 18
        base = escrever_bin(tmp_path / "pedida_100k.bin", [seno(5_000.0, 1.0, n=n, fs=100_000.0)], canais=(1,),
                            grandezas=(0,), sondas=("",), fs_total=100_000)
        _, out_nominal, _ = cli(main, base)
        assert "o PRU gera 400000.00 Hz = +3000000.0 ppm" in out_nominal
        saida = tmp_path / "pru.csv"
        rc, out, _ = cli(main, base, "--fs-pru", "--freq", "20000", "--csv", saida)
        assert rc == 0 and "a gerada pelo PRU" in out
        assert float(ler_csv(saida)[0]["freq_tom_hz"]) == pytest.approx(5_000.0 * 4, abs=0.5)

    def test_captura_saturada_avisa_no_stderr(self, cli, pasta):
        rc, out, err = cli(main, pasta / "ceifado.bin")
        assert rc == 0 and "Aviso: canal 1" in err and "saturou" in err
        assert "Aviso" not in out

    def test_um_arquivo_ruim_nao_derruba_os_outros(self, cli, pasta, tmp_path):
        saida = tmp_path / "parcial.csv"
        rc, out, err = cli(main, pasta / "nao_existe.bin", pasta / "um_canal.bin", "--csv", saida)
        assert rc == 1 and "não encontrado" in err and "Canal 3" in out
        assert len(ler_csv(saida)) == 1

    def test_so_aceita_bin(self, cli, tmp_path):
        arquivo = tmp_path / "x.csv"
        arquivo.write_text("a\n", encoding="utf-8")
        rc, _, err = cli(main, arquivo)
        assert rc == 1 and "'.bin'" in err

    def test_flags_invalidas_saem_com_codigo_2(self, cli, pasta):
        assert cli(main, pasta / "um_canal.bin", "--harmonicos", "1")[0] == 2
        assert cli(main, pasta / "um_canal.bin", "--max-amostras", "0")[0] == 2

    def test_max_amostras_e_inicio_limitam_a_janela(self, cli, pasta, tmp_path):
        saida = tmp_path / "r4.csv"
        rc, _, err = cli(main, pasta / "um_canal.bin", "--inicio", "1000", "--max-amostras", "100000", "--csv", saida)
        assert rc == 0, err
        assert int(ler_csv(saida)[0]["amostras_por_canal"]) == 100000

    def test_sem_tom_nao_procura_pico(self, cli, pasta):
        rc, out, _ = cli(main, pasta / "um_canal.bin", "--sem-tom")
        assert rc == 0 and "densidade de ruído" in out and "THD" not in out


CORRENTE_A = 3.0
FREQ_SONDA = 20_000.0


@pytest.fixture(scope="module")
def ambiente_sonda(tmp_path_factory):
    base = tmp_path_factory.mktemp("sonda")
    sondas = base / "sondas"
    sondas.mkdir()
    perfil = {"id": "sonda_teste", "tipo": "resposta_frequencia",
              "pontos": [{"freq_hz": float(f), "ganho": float(planta_h(f))} for f in FREQS_CAL]}
    (sondas / "sonda_teste.json").write_text(json.dumps(perfil), encoding="utf-8")
    n = 1 << 18
    saida_sonda = SENS_NOMINAL * planta_h(FREQ_SONDA) * CORRENTE_A * np.sin(2 * np.pi * FREQ_SONDA * tempo(n, 200_000.0))
    escrever_bin(base / "corrente.bin", [saida_sonda], canais=(1,), grandezas=(1,), sondas=("sonda_teste",), fs_total=200_000)
    return base


def args_sonda(ambiente, *extra):
    return ("--ganho", "10", "--sondas-dir", ambiente / "sondas", *extra)


class TestCliSondaEReferencia:
    """--sonda/--ganho: amplitude em Ampères REAIS; --referencia-*: erro contra o osciloscópio."""

    def test_corrente_sai_corrigida_pela_sonda(self, cli, ambiente_sonda, tmp_path):
        saida = tmp_path / "c.csv"
        rc, out, err = cli(main, ambiente_sonda / "corrente.bin", *args_sonda(ambiente_sonda, "--csv", saida))
        assert rc == 0, err
        (linha,) = ler_csv(saida)
        assert linha["grandeza"] == "corrente" and linha["unidade"] == "A" and linha["correcao_sonda"] == "sim"
        assert float(linha["amplitude_pico"]) == pytest.approx(CORRENTE_A, rel=0.01)
        assert "corrigido pelo perfil da sonda" in out

    def test_sem_correcao_a_amplitude_fica_abaixo_do_real(self, cli, ambiente_sonda, tmp_path):
        saida = tmp_path / "s.csv"
        rc, _, err = cli(main, ambiente_sonda / "corrente.bin", *args_sonda(ambiente_sonda, "--sem-correcao-sonda", "--csv", saida))
        assert rc == 0, err
        (linha,) = ler_csv(saida)
        assert linha["correcao_sonda"] == ""
        assert float(linha["amplitude_pico"]) == pytest.approx(CORRENTE_A * planta_h(FREQ_SONDA), rel=0.01)

    def test_erro_de_amplitude_contra_o_osciloscopio(self, cli, ambiente_sonda, tmp_path):
        saida = tmp_path / "ref.csv"
        i_rms = CORRENTE_A / math.sqrt(2)
        rc, out, err = cli(main, ambiente_sonda / "corrente.bin",
                           *args_sonda(ambiente_sonda, "--referencia-rms", i_rms * 0.99, "--csv", saida))
        assert rc == 0, err
        assert "vs referência (amplitude)" in out
        (linha,) = ler_csv(saida)
        assert float(linha["erro_amplitude_pct"]) == pytest.approx(1.0, abs=1.0)    # ADC vs "0,99 do real": ~+1 %, ± interpolação
        assert float(linha["referencia_rms"]) == pytest.approx(i_rms * 0.99)

    def test_erro_de_frequencia_em_ppm(self, cli, pasta, tmp_path):
        saida = tmp_path / "ppm.csv"
        rc, out, err = cli(main, pasta / "um_canal.bin", "--referencia-freq", 12_345.0, "--csv", saida)
        assert rc == 0, err
        assert "vs referência (frequência)" in out
        assert float(ler_csv(saida)[0]["erro_freq_ppm"]) == pytest.approx((12_345.6 - 12_345.0) / 12_345.0 * 1e6, rel=0.01)

    def test_referencia_sem_tom_avisa(self, cli, pasta):
        rc, _, err = cli(main, pasta / "um_canal.bin", "--sem-tom", "--referencia-rms", 1.0)
        assert rc == 0 and "sem tom" in err


# ---------------------------------------------------------------------------
# Amplitude injetada conhecida + osciloscópio: a checagem do ADC e do método do perfil
# ---------------------------------------------------------------------------

F_REF = 5000.0
PICO_MOSTRADOR = 0.25            # 500 mVpp no mostrador do gerador
ERRO_GERADOR = 0.98              # o gerador entrega 2 % menos que o mostrador
GANHO_CADEIA = 0.9               # atenuação do conjunto (sonda + frontend + filtro do ADC) nessa frequência


@pytest.fixture(scope="module")
def ambiente_ref(tmp_path_factory):
    from supraharmonicos.referencia import formatar_referencia

    base = tmp_path_factory.mktemp("ref")
    rng = np.random.default_rng(11)
    real = PICO_MOSTRADOR * ERRO_GERADOR
    descricao = formatar_referencia(F_REF, "500mVpp")
    adc = GANHO_CADEIA * real * np.sin(2 * np.pi * F_REF * tempo(1 << 18, 200_000.0) + 0.4) + rng.normal(0, 5e-4, 1 << 18)
    escrever_bin(base / "um.bin", [adc], canais=(3,), grandezas=(0,), sondas=("",), fs_total=200_000, descricao=descricao)
    fs_osc = 200.0 * F_REF
    osc = real * np.sin(2 * np.pi * F_REF * np.arange(8000) / fs_osc + 0.1) + rng.normal(0, 2e-3, 8000)
    escrever_m_osciloscopio(base / "um.m", osc, fs_osc)
    # 60 Hz da rede 20x maior que o tom: só a frequência dos metadados faz o tom ser achado
    com_rede = adc * 0.2 + 1.0 * np.sin(2 * np.pi * 60.0 * tempo(1 << 18, 200_000.0))
    escrever_bin(base / "rede.bin", [com_rede], canais=(3,), grandezas=(0,), sondas=("",), fs_total=200_000, descricao=descricao)
    escrever_bin(base / "sem_meta.bin", [adc], canais=(3,), grandezas=(0,), sondas=("",), fs_total=200_000)
    return base


class TestAmplitudeInjetadaEOsciloscopio:
    def medir(self, cli, ambiente, tmp_path, *extra, arquivo="um.bin"):
        saida = tmp_path / "r.csv"
        rc, out, err = cli(main, ambiente / arquivo, *extra, "--csv", saida)
        return rc, out, err, (ler_csv(saida)[0] if saida.exists() else None)

    def test_amplitude_dos_metadados_e_osciloscopio_irmao(self, cli, ambiente_ref, tmp_path):
        rc, out, err, linha = self.medir(cli, ambiente_ref, tmp_path, "--osciloscopio")
        assert rc == 0, err
        assert "referência gravada na captura: f=5000 Hz, amp=500mVpp" in out
        assert "vs amplitude injetada" in out and "vs osciloscópio" in out and "osciloscópio vs injetada" in out
        assert linha["ref_amplitude_texto"] == "500mVpp"
        assert float(linha["ref_amplitude_pico"]) == pytest.approx(PICO_MOSTRADOR)
        assert float(linha["razao_vs_amplitude_ref"]) == pytest.approx(GANHO_CADEIA * ERRO_GERADOR, rel=3e-3)
        assert float(linha["razao_vs_osc"]) == pytest.approx(GANHO_CADEIA, rel=3e-3)
        assert float(linha["osc_vs_amplitude_ref_pct"]) == pytest.approx(-2.0, abs=0.1)
        assert float(linha["osc_freq_hz"]) == pytest.approx(F_REF, rel=1e-5)
        assert abs(float(linha["erro_freq_vs_osc_ppm"])) < 30
        assert linha["osc_arquivo"] == "um.m"

    def test_arquivo_explicito_e_pasta(self, cli, ambiente_ref, tmp_path):
        for destino in (ambiente_ref / "um.m", ambiente_ref):
            rc, _, err, linha = self.medir(cli, ambiente_ref, tmp_path, "--osciloscopio", destino)
            assert rc == 0, err
            assert float(linha["razao_vs_osc"]) == pytest.approx(GANHO_CADEIA, rel=3e-3)
            (tmp_path / "r.csv").unlink()

    def test_a_linha_de_comando_vence_os_metadados(self, cli, ambiente_ref, tmp_path):
        rc, out, err, linha = self.medir(cli, ambiente_ref, tmp_path, "--amplitude-referencia", "400mVpp")
        assert rc == 0, err
        assert "linha de comando" in out
        assert float(linha["razao_vs_amplitude_ref"]) == pytest.approx(GANHO_CADEIA * ERRO_GERADOR * 0.25 / 0.2, rel=3e-3)

    def test_o_ganho_converte_volts_em_grandeza_fisica_e_a_razao_nao_muda(self, cli, ambiente_ref, tmp_path):
        rc, _, err, linha = self.medir(cli, ambiente_ref, tmp_path, "--ganho", "10", "--osciloscopio")
        assert rc == 0, err
        assert float(linha["ref_amplitude_pico"]) == pytest.approx(PICO_MOSTRADOR * 10)
        assert float(linha["razao_vs_amplitude_ref"]) == pytest.approx(GANHO_CADEIA * ERRO_GERADOR, rel=3e-3)
        assert float(linha["razao_vs_osc"]) == pytest.approx(GANHO_CADEIA, rel=3e-3)

    def test_metadado_de_frequencia_acha_o_tom_fraco_ao_lado_da_rede(self, cli, ambiente_ref, tmp_path):
        rc, _, err, linha = self.medir(cli, ambiente_ref, tmp_path, arquivo="rede.bin")
        assert rc == 0, err
        assert float(linha["freq_tom_hz"]) == pytest.approx(F_REF, rel=1e-4)
        assert float(linha["razao_vs_amplitude_ref"]) == pytest.approx(0.2 * GANHO_CADEIA * ERRO_GERADOR, rel=5e-3)

    def test_sem_nenhuma_referencia_as_colunas_novas_ficam_vazias(self, cli, ambiente_ref, tmp_path):
        rc, out, err, linha = self.medir(cli, ambiente_ref, tmp_path, arquivo="sem_meta.bin")
        assert rc == 0 and "vs amplitude injetada" not in out
        assert linha["razao_vs_amplitude_ref"] == "" and linha["osc_arquivo"] == ""

    def test_canal_corrigido_pelo_perfil_volta_a_razao_um(self, cli, ambiente_sonda, tmp_path):
        """A checagem do método: 3 A injetados; sem correção a razão é o ganho do conjunto, com correção é 1."""
        escrever_m_osciloscopio(ambiente_sonda / "corrente.m", CORRENTE_A * np.sin(2 * np.pi * FREQ_SONDA * np.arange(6000) / (100 * FREQ_SONDA)),
                                100 * FREQ_SONDA)
        razoes = {}
        for nome, extra in (("com", ()), ("sem", ("--sem-correcao-sonda",))):
            saida = tmp_path / f"{nome}.csv"
            rc, _, err = cli(main, ambiente_sonda / "corrente.bin", *args_sonda(ambiente_sonda, "--amplitude-referencia", "3Apk",
                                                                               "--osciloscopio", "--osc-unidade", "A", "--csv", saida, *extra))
            assert rc == 0, err
            linha = ler_csv(saida)[0]
            razoes[nome] = (float(linha["razao_vs_amplitude_ref"]), float(linha["razao_vs_osc"]))
        assert razoes["com"] == pytest.approx((1.0, 1.0), abs=0.01)
        assert razoes["sem"] == pytest.approx((float(planta_h(FREQ_SONDA)),) * 2, rel=0.01)

    def test_arquivo_do_osciloscopio_inexistente_e_erro_de_dominio(self, cli, ambiente_ref, tmp_path):
        rc, _, err, _ = self.medir(cli, ambiente_ref, tmp_path, "--osciloscopio", ambiente_ref / "nao_existe.m")
        assert rc == 1 and "não achei o arquivo do osciloscópio" in err
        rc, _, err, _ = self.medir(cli, ambiente_ref, tmp_path, "--osciloscopio", arquivo="sem_meta.bin")
        assert rc == 1 and "esperava 'sem_meta.m'" in err

    def test_flags_invalidas_saem_com_codigo_2(self, cli, ambiente_ref, tmp_path):
        assert cli(main, ambiente_ref / "um.bin", "--osc-fs", "1e6")[0] == 2
        rc, _, err = cli(main, ambiente_ref / "um.bin", "--amplitude-referencia", "500mV")
        assert rc == 2 and "sem tipo" in err
        rc, _, err = cli(main, ambiente_ref / "um.bin", ambiente_ref / "rede.bin", "--osciloscopio", ambiente_ref / "um.m")
        assert rc == 2 and "uma captura só" in err


def test_salto_numa_troca_de_buffer_aponta_o_bug_do_firmware_antigo(cli, tmp_path):
    """Firmware anterior a out/2026: ~1400 ciclos perdidos a cada troca de buffer. Simula isso num tom estável
    (v3 = firmware antigo) e confere que o medir_captura localiza o salto e explica a causa."""
    from capturas_sinteticas import escrever_bin, regravar_crc
    from supraharmonicos.cli_medir_captura import main

    fs, f, spb = 100_000.0, 1_000.0, 1 << 18                     # 4 segmentos por buffer (o real tem 16)
    n = 3 * spb
    t = np.arange(n) / fs
    t[spb:] += 7e-6                                              # 7 µs a mais a cada troca de buffer
    t[2 * spb:] += 7e-6
    v = 3.0 * np.sin(2 * np.pi * f * t)
    p = escrever_bin(tmp_path / "antigo.bin", [v], canais=(1,), grandezas=(0,), sondas=("",), fs_total=int(fs),
                     faixas_adc_total_v=20.48)
    bruto = bytearray(p.read_bytes())
    bruto[40:44] = spb.to_bytes(4, "little")                     # samples_per_buffer
    p.write_bytes(bytes(bruto))
    regravar_crc(p)
    rc, out, err = cli(main, p, "--freq", "1000")
    assert rc == 0, err
    assert "DESCONTINUIDADE" in out and "troca de buffer da PRU: é o bug do firmware anterior" in out
