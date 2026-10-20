"""As ferramentas de análise para pesquisa do ``adc_tool``: tabela de harmônicos, bandas da IEC 61000-4-7 no tempo,
espectrograma, exportação (CSV/JSON/MATLAB), os subcomandos e o carregamento sob demanda das bibliotecas.

Os sinais são sintéticos, com a resposta certa conhecida de antemão."""

import csv
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from capturas_sinteticas import escrever_bin
from supraharmonicos.bandas_iec import calcular_bandas_iec, centros_das_bandas
from supraharmonicos.cli_principal import SUBCOMANDOS
from supraharmonicos.cli_principal import main as principal
from supraharmonicos.erros import ErroSHAN
from supraharmonicos.espectro import calcular_espectro_welch, calcular_espectrograma
from supraharmonicos.exportacao import exportar_csv, exportar_mat
from supraharmonicos.fundamental import recortar_ciclos_inteiros
from supraharmonicos.harmonicos import calcular_harmonicos

RAIZ = Path(__file__).resolve().parents[1]
FS = 100_000.0


def _rede(t, fase_inicial=0.0):
    """127 V a 60 Hz com 5 % de 3º (+30°) e 2 % de 5º (-45°), no referencial seno."""
    w = 2 * np.pi * 60.0
    return np.sqrt(2) * (127 * np.sin(w * t + fase_inicial)
                         + 6.35 * np.sin(3 * (w * t + fase_inicial) + np.radians(30))
                         + 2.54 * np.sin(5 * (w * t + fase_inicial) - np.radians(45)))


# ---------------------------------------------------------------------------------------------------------------
# Harmônicos
# ---------------------------------------------------------------------------------------------------------------
class TestHarmonicos:
    def test_amplitudes_fases_e_thd_conhecidos_em_qualquer_inicio(self):
        n = int(round(60 * FS / 60.0))                       # 60 ciclos exatos
        for inicio in (0.0, 0.00123, 0.0101):
            t = np.arange(n) / FS + inicio
            tabela = calcular_harmonicos(_rede(t), FS, 60.0, 60, 7)
            h = {x.ordem: x for x in tabela.harmonicos}
            assert h[1].rms == pytest.approx(127, rel=1e-9) and h[1].fase_graus == 0.0
            assert h[3].rms == pytest.approx(6.35, rel=1e-9) and h[3].fase_graus == pytest.approx(30, abs=1e-6)
            assert h[5].rms == pytest.approx(2.54, rel=1e-9) and h[5].fase_graus == pytest.approx(-45, abs=1e-6)
            assert h[3].pct_fundamental == pytest.approx(5.0, rel=1e-9)
            assert tabela.thd_pct == pytest.approx(100 * math.hypot(6.35, 2.54) / 127, rel=1e-9)
            assert h[2].rms < 1e-9 and h[3].frequencia_hz == pytest.approx(180.0)

    def test_grupo_soma_o_inter_harmonico_vizinho_e_a_componente_nao(self):
        n = int(round(12 * FS / 60.0))                       # 12 ciclos: bins de 5 Hz, como na IEC 61000-4-7
        t = np.arange(n) / FS
        x = np.sqrt(2) * (100 * np.sin(2 * np.pi * 60 * t) + 3 * np.sin(2 * np.pi * 185 * t))   # 185 Hz: perto do 3º
        h3 = calcular_harmonicos(x, FS, 60.0, 12, 3).harmonicos[2]
        assert h3.rms < 1e-9                                  # a componente de 180 Hz não existe
        assert h3.rms_grupo == pytest.approx(3.0, rel=1e-9)   # o grupo de 180 Hz (150..210 Hz) contém os 185 Hz

    def test_ordens_acima_de_nyquist_sao_omitidas(self):
        n = int(round(10 * 2000 / 60.0))
        t = np.arange(n) / 2000.0
        tabela = calcular_harmonicos(np.sin(2 * np.pi * 60 * t), 2000.0, 60.0, 10, 50)
        assert max(h.frequencia_hz for h in tabela.harmonicos) < 1000.0

    def test_sem_fundamental_e_erro(self):
        with pytest.raises(ErroSHAN):
            calcular_harmonicos(np.zeros(1000), FS, 60.0, 1, 5)

    def test_fft_sem_fundamental_na_busca_e_erro_em_vez_de_f0_absurdo(self):
        t = np.arange(int(FS)) / FS
        with pytest.raises(ErroSHAN, match="fora da busca"):
            recortar_ciclos_inteiros(np.sin(2 * np.pi * 10_000 * t), FS, 45.0, 65.0, None)


# ---------------------------------------------------------------------------------------------------------------
# Bandas IEC 61000-4-7 (anexo B)
# ---------------------------------------------------------------------------------------------------------------
class TestBandasIEC:
    def test_centros_e_bordas_da_norma(self):
        assert list(centros_das_bandas(2000, 9000, 200)[:3]) == [2100, 2300, 2500]
        assert centros_das_bandas(2000, 9000, 200)[-1] == 8900
        t = np.arange(int(FS)) / FS
        # 3000 Hz é a borda: pertence a (2800, 3000], a banda de 2900, e não à de 3100
        bandas = calcular_bandas_iec(np.sqrt(2) * np.sin(2 * np.pi * 3000 * t), FS, freq_max=4000)
        est = bandas.estatisticas()
        i2900, i3100 = list(bandas.centros_hz).index(2900), list(bandas.centros_hz).index(3100)
        assert est["rms"][i2900] == pytest.approx(1.0, rel=1e-9) and est["rms"][i3100] < 1e-9

    def test_estatisticas_de_um_tom_que_liga_no_meio(self):
        t = np.arange(int(2 * FS)) / FS
        bandas = calcular_bandas_iec(np.sqrt(2) * np.sin(2 * np.pi * 2150 * t) * (t >= 1.0), FS, freq_max=3000)
        est = bandas.estatisticas()
        i = list(bandas.centros_hz).index(2100)
        assert bandas.niveis.shape == (10, len(bandas.centros_hz)) and bandas.duracao_janela_s == pytest.approx(0.2)
        assert est["maximo"][i] == pytest.approx(1.0, rel=1e-9) and est["minimo"][i] < 1e-9
        assert est["rms"][i] == pytest.approx(math.sqrt(0.5), rel=1e-9) and est["p95"][i] == pytest.approx(1.0)
        assert list(np.round(bandas.niveis[:, i], 6)) == [0.0] * 5 + [1.0] * 5

    def test_trecho_mais_curto_que_uma_janela_e_erro(self):
        with pytest.raises(ErroSHAN, match="200 ms"):
            calcular_bandas_iec(np.zeros(1000), FS)


# ---------------------------------------------------------------------------------------------------------------
# Espectrograma
# ---------------------------------------------------------------------------------------------------------------
class TestEspectrograma:
    def test_mostra_quando_o_tom_liga_e_tem_o_nivel_do_welch(self):
        t = np.arange(int(4 * FS)) / FS
        x = np.sqrt(2) * np.sin(2 * np.pi * 20_000 * t) * (t >= 2.0)
        tempos, freqs, matriz = calcular_espectrograma(x, FS, "hann", 8.6, 200, 0.5, "tom", max_colunas=40)
        k = int(np.argmin(abs(freqs - 20_000)))
        assert matriz.shape == (len(tempos), len(freqs)) and len(tempos) <= 40
        assert matriz[tempos < 1.5, k].max() < -80 and matriz[tempos > 2.5, k].min() > 0
        _, db_welch, _ = calcular_espectro_welch(x[t >= 2.0], FS, "hann", 8.6, 200, 0.5, "tom")
        assert matriz[-1, k] == pytest.approx(db_welch[k], abs=0.01)
        assert tempos[0] > 0 and tempos[-1] < 4.0 and np.all(np.diff(tempos) > 0)


# ---------------------------------------------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------------------------------------------
def _resultados():
    n = int(round(60 * FS / 60.0))
    t = np.arange(n) / FS
    tabela = calcular_harmonicos(_rede(t), FS, 60.0, 60, 5)
    bandas = calcular_bandas_iec(np.sqrt(2) * np.sin(2 * np.pi * 2150 * t), FS, freq_max=3000)
    canal = {"unidade": "V", "grandeza": "tensão", "modo": "tom",
             "welch": {"f": np.array([0.0, 100.0]), "db": np.array([-80.0, -6.0206])},
             "welch_bandas": {"f": np.array([100.0]), "db": np.array([-9.0309])},
             "harmonicos": tabela, "bandas_iec": bandas,
             "espectrograma": {"t": np.array([0.5, 1.5]), "f": np.array([0.0, 100.0]), "db": np.zeros((2, 2))}}
    return {"canais": {1: canal}, "picos": [{"canal": 1, "metodo": "welch", "frequencia_hz": 100.0, "amplitude_db": -6.0}]}


def test_exportar_csv_e_json(tmp_path):
    escritos = exportar_csv(tmp_path / "x", _resultados(), {"comando": "teste", "valor": float("nan")})
    nomes = {p.name for p in escritos}
    assert {"x_canal1_welch.csv", "x_canal1_welch_bandas.csv", "x_canal1_harmonicos.csv", "x_canal1_bandas_iec.csv",
            "x_canal1_bandas_iec_serie.csv", "x_canal1_espectrograma.csv", "x_picos.csv", "x_metadados.json"} == nomes
    with open(tmp_path / "x_canal1_welch.csv", encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    assert float(linhas[1]["amplitude_pico_V"]) == pytest.approx(0.5, rel=1e-4)      # -6,02 dBV de pico
    with open(tmp_path / "x_canal1_harmonicos.csv", encoding="utf-8") as f:
        h3 = list(csv.DictReader(f))[2]
    assert float(h3["rms_V"]) == pytest.approx(6.35) and float(h3["fase_graus"]) == pytest.approx(30.0)
    meta = json.loads((tmp_path / "x_metadados.json").read_text(encoding="utf-8"))
    assert meta == {"comando": "teste", "valor": None}                                   # NaN vira null


def test_exportar_mat_e_lido_de_volta(tmp_path):
    from scipy.io import loadmat
    caminho = exportar_mat(tmp_path / "x.mat", _resultados(), {"comando": "teste", "calibracao": {"canal1": {"ganho": 1.0}}})
    sh = loadmat(caminho, squeeze_me=True, struct_as_record=False)["sh"]
    assert sh.canal1.harmonicos.thd_pct == pytest.approx(100 * math.hypot(6.35, 2.54) / 127)
    assert list(sh.canal1.welch.f) == [0.0, 100.0] and sh.canal1.unidade == "V"
    assert sh.canal1.bandas_iec.niveis.shape[1] == len(sh.canal1.bandas_iec.centros_hz)
    assert sh.metadados.comando == "teste" and sh.metadados.calibracao.canal1.ganho == 1.0


# ---------------------------------------------------------------------------------------------------------------
# A análise inteira pela linha de comando, e os subcomandos
# ---------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def captura(tmp_path_factory):
    """2 s de rede a 60 Hz com 3º e 5º, mais um supraharmônico de 9 kHz que só aparece no segundo segundo."""
    t = np.arange(int(2 * FS)) / FS
    x = _rede(t) / 19.357 + np.sqrt(2) * 0.01 * np.sin(2 * np.pi * 9_050 * t) * (t >= 1.0)   # no pino do ADC
    return escrever_bin(tmp_path_factory.mktemp("pesquisa") / "rede.bin", [x], canais=(1,), grandezas=(0,),
                        sondas=("",), fs_total=int(FS), faixas_adc_total_v=20.48, titulo="rede sintetica")


def test_analise_completa_sem_grafico_exporta_tudo(cli, captura, tmp_path):
    rc, out, err = cli(principal, captura, "--ganho", "19.357", "--sem-grafico", "--fft", "--harmonicos", "5",
                       "--welch", "--picos", "-60", "--bandas-iec", "--bandas-iec-max", "10000", "--espectrograma",
                       "--exportar", tmp_path / "r", "--exportar-mat", tmp_path / "r.mat")
    assert rc == 0, err
    assert "THD (componentes) = 5.38" in out and "Bandas IEC 61000-4-7" in out and "Espectrograma:" in out
    assert "Gráfico salvo" not in out
    meta = json.loads((tmp_path / "r_metadados.json").read_text(encoding="utf-8"))
    assert meta["espectro"]["welch"]["janela"] == "Hann" and meta["espectro"]["fft"]["janela"].startswith("Retangular")
    assert meta["calibracao"]["canal1"]["ganho"] == 19.357 and meta["captura"]["titulo"] == "rede sintetica"
    assert meta["resultados_por_canal"]["canal1"]["harmonicos"]["thd_pct"] == pytest.approx(5.385, abs=0.01)
    with open(tmp_path / "r_canal1_bandas_iec.csv", encoding="utf-8") as f:
        banda = {round(float(linha["centro_hz"])): linha for linha in csv.DictReader(f)}
    assert float(banda[9100]["maximo_V"]) == pytest.approx(0.01 * 19.357, rel=0.02)     # 9050 Hz em (9000, 9200]
    assert float(banda[9100]["minimo_V"]) < 0.001                                       # desligado no 1º segundo
    assert (tmp_path / "r.mat").exists() and (tmp_path / "r_picos.csv").exists()


def test_harmonicos_sem_fft_e_erro_de_uso(cli, captura):
    rc, _, err = cli(principal, captura, "--sem-grafico", "--harmonicos", "5")
    assert rc == 2 and "--harmonicos requer --fft" in err


def test_figuras_extras_ao_lado_da_principal(cli, captura, tmp_path):
    rc, out, err = cli(principal, captura, "--bandas-iec", "--bandas-iec-max", "5000", "--espectrograma",
                       "-o", tmp_path / "g.png")
    assert rc == 0, err
    assert {p.name for p in tmp_path.iterdir()} == {"g.png", "g_espectrograma.png", "g_bandas_iec.png"}


def test_subcomandos_e_o_caminho_antigo(cli, captura, tmp_path):
    rc, out, _ = cli(principal, "info", captura, "--estatisticas", "--ganho", "19.357")
    assert rc == 0 and "rede sintetica" in out and "fator de crista" in out
    rc, out, _ = cli(principal, "medir", captura, "--freq", "60", "--sem-correcao-sonda")
    assert rc == 0 and "SINAD / SNR / ENOB" in out
    rc, out, _ = cli(principal, "analisar", captura, "--sem-grafico")
    assert rc == 0 and "Janela de dados" in out
    rc, out, _ = cli(principal, captura, "--sem-grafico")                          # sem subcomando: a análise
    assert rc == 0 and "Janela de dados" in out
    rc, out, _ = cli(principal, "--help")
    assert rc == 0 and all(nome in out for nome in SUBCOMANDOS) and "--harmonicos" in out


@pytest.mark.parametrize("argumentos, proibidas", [
    (["--help"], {"scipy", "matplotlib", "h5py", "rich"}),
    (["info", "{captura}", "--estatisticas"], {"scipy", "matplotlib", "h5py", "rich"}),
    (["{captura}", "--sem-grafico"], {"scipy", "matplotlib", "h5py", "rich"}),
    (["{captura}", "--sem-grafico", "--welch"], {"matplotlib", "h5py", "rich"}),
])
def test_cada_comando_so_carrega_o_que_usa(captura, argumentos, proibidas):
    """Num processo limpo: o que cada comando deixa em sys.modules. O SciPy custa ~2 s e o matplotlib ~1 s."""
    argv = [a.format(captura=captura) for a in argumentos]
    codigo = ("import sys; from supraharmonicos.cli_principal import main\n"
              f"try:\n    main({argv!r})\nexcept SystemExit:\n    pass\n"
              "print('CARREGADAS=' + ','.join(sorted({m.split('.')[0] for m in sys.modules})))")
    ambiente = {**os.environ, "PYTHONPATH": str(RAIZ / "scripts")}
    ambiente.pop("MPLBACKEND", None)
    saida = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, env=ambiente, timeout=120)
    carregadas = set(saida.stdout.rsplit("CARREGADAS=", 1)[1].strip().split(","))
    assert not carregadas & proibidas, (argumentos, carregadas & proibidas, saida.stderr[-500:])
