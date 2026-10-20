"""CLI do adc_tool rodando no mesmo processo: códigos de saída, stdout/stderr e arquivos gerados."""

import csv
import json
import re

import numpy as np
import pytest
from capturas_sinteticas import FREQS_CAL, captura_producao, escrever_bin, planta_h
from supraharmonicos.cli_adc_tool import main


@pytest.fixture(scope="module")
def ambiente(tmp_path_factory):
    base = tmp_path_factory.mktemp("cli_adc")
    sondas = base / "sondas"
    sondas.mkdir()
    perfil = {"id": "sonda_teste", "tipo": "resposta_frequencia",
              "pontos": [{"freq_hz": float(f), "ganho": float(planta_h(f))} for f in FREQS_CAL]}
    (sondas / "sonda_teste.json").write_text(json.dumps(perfil), encoding="utf-8")
    captura_producao(base / "ok.bin", dur_s=0.3)
    return base


ESPECTRO = ("--welch", "--resolucao-welch", "100", "--modo-espectro", "tom", "--picos", "-40",
            "--freq-min-picos", "1000", "--filtro-passa-alta", "1000")


def test_help_sai_com_zero(cli):
    rc, out, _ = cli(main, "--help")
    assert rc == 0 and "adc_tool.py" in out


def test_plotagem_completa_com_sonda_welch_e_picos(cli, ambiente):
    png = ambiente / "g.png"
    rc, out, err = cli(main, ambiente / "ok.bin", "--ganho", "1,10", "--sondas-dir", ambiente / "sondas", *ESPECTRO,
                       "-o", png)
    assert rc == 0, err
    assert png.stat().st_size > 1000
    # frequência e canais vieram do cabeçalho da captura
    assert "usando a frequência: 400000 Hz" in out
    assert "Canal 1: correção de sonda aplicada (perfil 'sonda_teste'" in out
    assert "Canal 1 [welch] pico: 40000" in out or "Canal 1 [welch] pico: 39" in out
    assert "Aviso:" not in out                      # avisos NUNCA vão para o stdout
    assert "acima de" in err and err.startswith("Aviso: ")   # faixa do perfil (80 kHz) < Nyquist (100 kHz)


def test_aviso_de_welch_sem_passa_alta_vai_para_stderr_com_prefixo(cli, ambiente):
    rc, out, err = cli(main, ambiente / "ok.bin", "--ganho", "1,10", "--sondas-dir", ambiente / "sondas", "--welch",
                       "-o", ambiente / "g2.png")
    assert rc == 0
    assert "Aviso: --welch/--picos sem --filtro-passa-alta" in err


def test_arquivo_inexistente_e_erro_de_dominio_codigo_1(cli, tmp_path):
    rc, out, err = cli(main, tmp_path / "nao_existe.bin", "-f", "400000", "--welch", "-o", tmp_path / "g.png")
    assert rc == 1
    assert err.strip().splitlines()[-1] == f"Erro: arquivo '{tmp_path / 'nao_existe.bin'}' não encontrado."


def test_canal_invalido_codigo_1(cli, ambiente):
    rc, _, err = cli(main, ambiente / "ok.bin", "--canais", "9", "--welch")
    assert rc == 1 and "Erro: canal 9 inválido em --canais -- ADS8688 só tem canais 0-7." in err


@pytest.mark.parametrize("argv, trecho", [
    (["-c", "{bin}"], "-o/--saida é obrigatório"),
    (["{bin}", "--picos", "-40"], "--picos requer --fft e/ou --welch"),
    (["{bin}", "--export-hdf5", "{tmp}/x.h5", "-c", "{bin}", "-o", "{tmp}/x.csv"], "não podem ser usados juntos"),
])
def test_erros_de_uso_dao_codigo_2_com_usage(cli, ambiente, argv, trecho):
    argv = [a.replace("{bin}", str(ambiente / "ok.bin")).replace("{tmp}", str(ambiente)) for a in argv]
    rc, _, err = cli(main, *argv)
    assert rc == 2 and "usage:" in err and trecho in err


def test_captura_legada_sem_cabecalho_exige_frequencia(cli, tmp_path):
    t = np.arange(2000) / 200_000.0
    p = escrever_bin(tmp_path / "legado.bin", [np.sin(2 * np.pi * 1000 * t)] * 2, com_cabecalho=False)
    rc, _, err = cli(main, p, "--canais", "0,1", "--welch", "-o", tmp_path / "g.png")
    assert rc == 2 and "-f/--frequencia é obrigatório" in err
    rc, out, err = cli(main, p, "--canais", "0,1", "-f", "400000", "--welch", "--resolucao-welch", "1000",
                       "-o", tmp_path / "g.png")
    assert rc == 0, err


def test_modo_conversao_bin_para_csv(cli, ambiente):
    destino = ambiente / "saida.csv"
    rc, out, err = cli(main, "-c", ambiente / "ok.bin", "-o", destino, "--incluir-tensao", "--ganho", "1,10")
    assert rc == 0, err
    assert "Convertido:" in out and "(.bin) -> " in out
    with open(destino, newline="", encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    assert list(linhas[0]) == ["amostra", "canal", "valor_bruto", "tensao_v"]
    assert len(linhas) == 2 * 60_000                                     # 0,3 s x 200 kHz por canal, 2 canais
    assert [ln["canal"] for ln in linhas[:4]] == ["0", "1", "0", "1"]    # intercalado, na ordem do cabeçalho
    v0 = [float(ln["tensao_v"]) for ln in linhas[0::2]]                  # canal 0: 3,25 V de pico a 50 Hz
    assert max(v0) == pytest.approx(3.25, abs=0.01) and min(v0) == pytest.approx(-3.25, abs=0.01)


def test_modo_exportacao_hdf5(cli, ambiente):
    destino = ambiente / "saida.h5"
    rc, out, err = cli(main, ambiente / "ok.bin", "--export-hdf5", destino, "--ganho", "1,10", "--incluir-tensao")
    assert rc == 0, err
    assert destino.exists() and "Exportado:" in out and "+ tensao_v calibrada" in out


def test_exportacao_avisa_que_ignora_flags_de_plotagem(cli, ambiente):
    rc, _, err = cli(main, ambiente / "ok.bin", "--export-hdf5", ambiente / "y.h5", "--welch")
    assert rc == 0 and "Aviso: --export-hdf5 ignora --fft/--welch/--picos/--agrupar-bandas" in err


def test_inicio_no_meio_do_ciclo_mantem_cada_canal_com_o_seu_rotulo(tmp_path):
    from supraharmonicos.cli_adc_tool import montar_parser
    from supraharmonicos.contexto import resolver_contexto
    from supraharmonicos.modos import _carregar_sinal

    p = escrever_bin(tmp_path / "dc.bin", [np.full(4000, 1.0), np.full(4000, -2.0)])   # canal 0 = +1 V, canal 1 = -2 V
    args = montar_parser().parse_args([str(p), "--inicio", "101"])
    sinal = _carregar_sinal(args, resolver_contexto(args))
    assert sinal.idx_inicio == 100
    assert np.mean(sinal.por_canal_tensao[0]) == pytest.approx(1.0, abs=1e-3)
    assert np.mean(sinal.por_canal_tensao[1]) == pytest.approx(-2.0, abs=1e-3)


@pytest.mark.parametrize("argv, trecho", [
    (["-f", "0", "--welch"], "-f/--frequencia precisa ser um número positivo"),
    (["-f", "nan", "--welch"], "-f/--frequencia precisa ser um número positivo"),
    (["--tamanho-chunk", "0"], "--tamanho-chunk precisa ser >= 1"),
    (["--welch", "--picos", "-40", "--distancia-minima-picos", "0"], "--distancia-minima-picos precisa ser positiva"),
])
def test_valores_numericos_invalidos_sao_erro_de_uso(cli, ambiente, argv, trecho):
    rc, _, err = cli(main, ambiente / "ok.bin", *argv)
    assert rc == 2 and trecho in err


def test_cabecalho_com_lista_de_canais_corrompida_e_erro_claro(cli, tmp_path):
    p = escrever_bin(tmp_path / "corrompido.bin", [np.zeros(1000), np.zeros(1000)])
    bruto = bytearray(p.read_bytes())
    bruto[33] = 0                     # lista_canais (offset 32) = [0, 0]: canal repetido, e o CRC deixa de conferir
    p.write_bytes(bytes(bruto))
    rc, _, err = cli(main, p, "--welch")
    assert rc == 1 and "lista de canais do cabeçalho é inválida" in err and "CRC-32" in err


def test_espectro_de_canal_de_corrente_e_rotulado_em_dba():
    import argparse

    from supraharmonicos.modos import _rotulo_espectro
    tom = argparse.Namespace(agrupar_bandas=None, modo_espectro="tom")
    assert _rotulo_espectro(tom, {1: 1}) == "Magnitude (dBA)"
    assert _rotulo_espectro(tom, {0: 0}) == "Magnitude (dBV)"
    assert _rotulo_espectro(argparse.Namespace(agrupar_bandas=200.0, modo_espectro="ruido"), {0: 0, 1: 1}) \
        == "Nível RMS por banda de 200 Hz (dB re unidade do canal)"


# --------------------------------------------------------------------------------------
# --fft (ciclos inteiros), gráfico de eixo único e --grandeza/--sonda-perfil
# --------------------------------------------------------------------------------------
def _captura_rede(caminho, canais=(1,), fs_total=100_000):
    """60 Hz (3 V) + 3º harmônico (0,3 V) + 5º (0,15 V): o que a --fft em ciclos inteiros foi feita para medir."""
    k = len(canais)
    t = np.arange(50_000 // k) / (fs_total / k)
    v = 3.0 * np.sin(2 * np.pi * 60 * t) + 0.3 * np.sin(2 * np.pi * 180 * t) + 0.15 * np.sin(2 * np.pi * 300 * t)
    return escrever_bin(caminho, [v] * k, canais=canais, grandezas=(0,) * k, sondas=("",) * k, fs_total=fs_total)


def test_fft_em_ciclos_inteiros_mede_a_fundamental_e_os_harmonicos(cli, tmp_path):
    p = _captura_rede(tmp_path / "rede.bin")
    rc, out, err = cli(main, p, "--fft", "--picos", "-60", "--freq-min-picos", "100", "-o", tmp_path / "g.png")
    assert rc == 0, err
    assert re.search(r"FFT \(ciclo\): f0 = 60\.00\d Hz \| 28 ciclo\(s\) completo\(s\)", out), out
    picos = {round(float(f)): 10 ** (float(db) / 20) for f, db in re.findall(r"\[ciclo\] pico: ([\d.]+) Hz @ (-?[\d.]+) dB", out)}
    assert set(picos) == {180, 300}
    assert picos[180] == pytest.approx(0.3, rel=2e-3) and picos[300] == pytest.approx(0.15, rel=2e-3)
    assert (tmp_path / "g.png").stat().st_size > 1000


@pytest.mark.parametrize("canais, extra", [((1,), ()), ((0, 1), ("--layout-canais", "sobrepostos"))])
def test_grafico_de_eixo_unico_com_fft_e_welch(cli, tmp_path, canais, extra):
    """1 canal, ou vários com --layout-canais sobrepostos: tempo e espectro num eixo só, as duas análises juntas."""
    p = _captura_rede(tmp_path / "rede.bin", canais=canais)
    rc, out, err = cli(main, p, "--fft", "--welch", "--resolucao-welch", "50", *extra, "-o", tmp_path / "g.png")
    assert rc == 0, err
    assert "Gráfico salvo em" in out and (tmp_path / "g.png").stat().st_size > 1000


def test_grandeza_por_flag_vence_o_cabecalho(cli, ambiente):
    """O cabeçalho diz corrente com sonda no canal 1; --grandeza 1:temperatura manda, e temperatura não se corrige
    em frequência (com tensão a sonda REGISTRADA ainda seria aplicada -- ver modos.aplicar_correcao_sondas)."""
    rc, out, err = cli(main, ambiente / "ok.bin", "--grandeza", "1:temperatura", "--ganho", "1,10", "--sondas-dir",
                       ambiente / "sondas", "--welch", "--fim", "20000", "-o", ambiente / "g3.png")
    assert rc == 0, err
    assert "canal 1 é de temperatura" in err and "correção de sonda aplicada" not in out


@pytest.mark.parametrize("flag, valor, trecho", [
    ("--grandeza", "1:xyz", "grandeza 'xyz' desconhecida"),
    ("--grandeza", "1corrente", "precisa estar no formato 'canal:valor'"),
    ("--grandeza", "x:corrente", "'x' não é um canal válido"),
    ("--grandeza", "5:corrente", "--grandeza: canal 5 não está na captura (canais: 0, 1)"),
    ("--sonda-perfil", "7:qualquer.json", "--sonda-perfil: canal 7 não está na captura"),
    ("--sonda-perfil", "1:/nao/existe.json", "não encontrado"),
])
def test_grandeza_e_sonda_perfil_invalidos_dao_erro_claro(cli, ambiente, flag, valor, trecho):
    rc, _, err = cli(main, ambiente / "ok.bin", flag, valor, "--welch", "-o", ambiente / "g4.png")
    assert rc == 1 and trecho in err, err
