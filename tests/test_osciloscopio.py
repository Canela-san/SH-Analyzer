"""``osciloscopio``: leitura de ``.m``/``.mat``/``.csv`` e medida da senoide, contra sinais de valor conhecido."""

import argparse

import numpy as np
import pytest
from scipy.io import savemat
from supraharmonicos.erros import ErroSHAN
from supraharmonicos.osciloscopio import (
    adicionar_argumentos_osciloscopio,
    ler_csv,
    ler_forma_de_onda,
    ler_forma_de_onda_dos_args,
    ler_m,
    localizar_arquivo_osciloscopio,
    medir_senoide,
    montar_forma_de_onda,
)

FS = 2e6                # 6000 amostras = 3 ms = ~37 ciclos do tom de teste
N = 6000
F_TOM = 12345.6
AMP = 0.25
NL = "\n"


@pytest.fixture(scope="module")
def sinal():
    t = np.arange(N) / FS
    return t, AMP * np.sin(2 * np.pi * F_TOM * t + 0.7) + 0.01


def vetor(a, sep=" "):
    return "[" + sep.join(f"{x:.12g}" for x in a) + "]"


class TestMedirSenoide:
    @pytest.mark.parametrize("fs,f,n", [(1e8, 12345.6, 500_000), (1e9, 100e3, 4_000_000), (5e6, 50.0, 1_000_000),
                                        (1e6, 1e3, 100_000), (2e5, 9876.5, 200_000)])
    def test_recupera_amplitude_frequencia_e_dc_com_ruido(self, fs, f, n):
        rng = np.random.default_rng(1)
        y = AMP * np.sin(2 * np.pi * f * np.arange(n) / fs + 0.3) + 0.01 + rng.normal(0, 0.005, n)
        r = medir_senoide(y, fs)
        assert r.amplitude_pico == pytest.approx(AMP, rel=2e-4)
        assert r.freq_hz == pytest.approx(f, rel=2e-5)
        assert r.offset == pytest.approx(0.01, abs=2e-4)
        assert r.residuo_rms == pytest.approx(0.005, rel=0.05)
        assert r.amplitude_pico_a_pico == pytest.approx(2 * r.amplitude_pico)
        assert r.amplitude_rms == pytest.approx(r.amplitude_pico / np.sqrt(2))

    def test_nao_precisa_de_ciclos_inteiros(self):
        # 7,37 ciclos: a FFT sem janela erraria; o ajuste de mínimos quadrados não
        n, fs = 10_000, 1e6
        y = AMP * np.sin(2 * np.pi * 737.0 * np.arange(n) / fs + 1.0)
        r = medir_senoide(y, fs)
        assert r.amplitude_pico == pytest.approx(AMP, rel=1e-6) and r.freq_hz == pytest.approx(737.0, rel=1e-6)

    def test_poucos_ciclos_exigem_dica_e_avisam(self, caplog):
        n, fs = 10_000, 1e6                                    # 2 ciclos de 200 Hz
        y = AMP * np.sin(2 * np.pi * 200.0 * np.arange(n) / fs + 0.3)
        with caplog.at_level("WARNING"):
            r = medir_senoide(y, fs, freq_dica=195.0)
        assert r.amplitude_pico == pytest.approx(AMP, rel=1e-4)
        assert any("ciclo" in m.getMessage() for m in caplog.records)

    def test_dica_escolhe_o_tom_certo_entre_dois(self):
        n, fs = 200_000, 1e6
        t = np.arange(n) / fs
        y = 0.1 * np.sin(2 * np.pi * 1000 * t) + 0.5 * np.sin(2 * np.pi * 7000 * t)
        assert medir_senoide(y, fs).freq_hz == pytest.approx(7000, rel=1e-6)
        r = medir_senoide(y, fs, freq_dica=1050.0)
        assert r.freq_hz == pytest.approx(1000, rel=1e-4) and r.amplitude_pico == pytest.approx(0.1, rel=1e-3)   # com outro tom forte presente a precisão é menor

    def test_menos_de_um_ciclo_e_erro(self):
        y = np.sin(2 * np.pi * 1000.0 * np.arange(500) / 1e6)             # meio ciclo
        with pytest.raises(ErroSHAN, match="menos de 1 ciclo"):
            medir_senoide(y, 1e6, freq_dica=1000.0)

    def test_registro_curto_ou_taxa_invalida_e_erro(self):
        with pytest.raises(ErroSHAN, match="amostras"):
            medir_senoide(np.zeros(10), 1e6)
        with pytest.raises(ErroSHAN, match="taxa"):
            medir_senoide(np.zeros(1000), 0.0)


class TestLerM:
    def test_vetor_e_intervalo_de_amostragem(self, sinal):
        _, y = sinal
        v = ler_m(f"% osciloscópio\nTinterval = {1 / FS:.12g};\nTstart = -1e-3;\nY = {vetor(y)};\n")
        f = montar_forma_de_onda(v, "x.m")
        assert f.fs == pytest.approx(FS) and len(f.valores) == N and "Tinterval" in f.origem

    def test_vetor_de_tempo_e_de_valores(self, sinal):
        t, y = sinal
        f = montar_forma_de_onda(ler_m(f"x = {vetor(t, '; ')};\ny = {vetor(y, ';' + NL)};\n"), "x.m")
        assert f.fs == pytest.approx(FS, rel=1e-6) and f.origem.startswith('variável "y"')

    def test_matriz_tempo_e_valor(self, sinal):
        t, y = sinal
        linhas = ";\n".join(f"{a:.12g} {b:.12g}" for a, b in zip(t, y))
        f = montar_forma_de_onda(ler_m(f"data = [{linhas}];\n"), "x.m")
        assert f.fs == pytest.approx(FS, rel=1e-6) and "coluna 1" in f.origem
        assert medir_senoide(f.valores, f.fs).amplitude_pico == pytest.approx(AMP, rel=1e-4)

    def test_colunas_soltas_depois_de_comentarios(self, sinal):
        t, y = sinal
        corpo = "\n".join(f"{a:.12g}, {b:.12g}" for a, b in zip(t, y))
        f = montar_forma_de_onda(ler_m(f"% Time (s), Channel 1 (V)\n% gerado pelo osciloscópio\n{corpo}\n"), "x.m")
        assert f.fs == pytest.approx(FS, rel=1e-6) and len(f.valores) == N

    def test_continuacao_envoltorio_e_taxa_em_hz(self, sinal):
        _, y = sinal
        numeros = " ...\n".join(f"{x:.9g}" for x in y[:100])
        f = montar_forma_de_onda(ler_m(f"Fs = {FS:g};\nCH1 = single([{numeros}]);\n"), "x.m")
        assert f.fs == FS and len(f.valores) == 100

    def test_varias_atribuicoes_na_mesma_linha(self, sinal):
        _, y = sinal
        v = ler_m(f"dt = 1e-8; Y = {vetor(y[:100])}; n = 100;")
        assert set(v) == {"dt", "Y", "n"} and len(v["Y"]) == 100

    def test_comentarios_e_texto_nao_numerico_sao_ignorados(self):
        v = ler_m("% Y = [1 2 3];\nnome = 'canal 1';\nescala = 2.5;  % V/div\n")
        assert list(v) == ["escala"] and v["escala"][0] == 2.5


class TestLerCsv:
    def test_cabecalho_de_rotulos_e_colunas(self, sinal):
        t, y = sinal
        corpo = "\n".join(f"{a:.12g},{b:.12g}" for a, b in zip(t, y))
        v = ler_csv(f"Record Length,{N}\nSample Interval,5e-07\nTime,CH1\n{corpo}\n")
        assert set(v) == {"Record Length", "Sample Interval", "Time", "CH1"}
        f = montar_forma_de_onda(v, "x.csv")
        assert f.fs == pytest.approx(FS, rel=1e-6) and f.origem.startswith('variável "CH1"')

    def test_ponto_e_virgula_com_virgula_decimal(self, sinal):
        t, y = sinal
        corpo = "\n".join(f"{a:.12g};{b:.12g}".replace(".", ",") for a, b in zip(t, y))
        f = montar_forma_de_onda(ler_csv(f"Tempo;Canal\n{corpo}\n"), "x.csv")
        assert f.fs == pytest.approx(FS, rel=1e-6) and len(f.valores) == N

    def test_uma_coluna_sem_cabecalho_precisa_da_taxa(self, sinal):
        _, y = sinal
        v = ler_csv("\n".join(f"{b:.12g}" for b in y) + "\n")
        with pytest.raises(ErroSHAN, match="--osc-fs"):
            montar_forma_de_onda(v, "x.csv")
        assert montar_forma_de_onda(v, "x.csv", fs=FS).fs == FS


class TestMat:
    def test_mat_v73_da_erro_orientando_a_salvar_de_outro_jeito(self, tmp_path):
        import h5py
        with h5py.File(tmp_path / "b.mat", "w") as f:        # HDF5 puro: o scipy não o reconhece como .mat v5
            f["Y"] = np.zeros(100)
        with pytest.raises(ErroSHAN, match="não consegui ler|v7.3"):
            ler_forma_de_onda(tmp_path / "b.mat")

    def test_matriz_e_escalar(self, tmp_path, sinal):
        t, y = sinal
        savemat(tmp_path / "a.mat", {"Tinterval": 1 / FS, "Y": y})
        f = ler_forma_de_onda(tmp_path / "a.mat")
        assert f.fs == pytest.approx(FS) and len(f.valores) == N

    def test_varios_canais_exigem_escolha(self, tmp_path, sinal):
        t, y = sinal
        savemat(tmp_path / "a.mat", {"dados": np.column_stack([t, y, 2 * y])})
        with pytest.raises(ErroSHAN, match="vários canais|mais de uma"):
            ler_forma_de_onda(tmp_path / "a.mat")
        f = ler_forma_de_onda(tmp_path / "a.mat", variavel="dados:2")
        assert f.fs == pytest.approx(FS, rel=1e-6) and f.valores[100] == pytest.approx(2 * y[100])


class TestEscolha:
    def test_duas_formas_de_onda_listam_as_opcoes(self, sinal):
        _, y = sinal
        v = {"A": y, "B": y * 2, "dt": np.array([1e-8])}
        with pytest.raises(ErroSHAN, match=r"--osc-var.*|A \(6000 pts\)"):
            montar_forma_de_onda(v, "x.m")
        assert montar_forma_de_onda(v, "x.m", variavel="b").valores[10] == pytest.approx(2 * y[10])

    def test_nome_preferido_desempata(self, sinal):
        _, y = sinal
        f = montar_forma_de_onda({"Y": y, "lixo": y[::-1].copy(), "dt": np.array([1e-8])}, "x.m")
        assert f.origem.startswith('variável "Y"')

    def test_variavel_inexistente_lista_as_que_existem(self, sinal):
        with pytest.raises(ErroSHAN, match=r"não achei a variável 'Z'.*Y \(6000\)"):
            montar_forma_de_onda({"Y": sinal[1]}, "x.m", variavel="Z")

    def test_sem_forma_de_onda_e_erro_com_pedido_das_linhas(self):
        with pytest.raises(ErroSHAN, match="primeiras linhas"):
            montar_forma_de_onda({"a": np.array([1.0])}, "x.m")

    def test_escala_e_taxa_explicita(self, sinal):
        _, y = sinal
        f = montar_forma_de_onda({"Y": y}, "x.m", fs=2e6, escala=10.0)
        assert f.fs == 2e6 and f.valores[5] == pytest.approx(10 * y[5])

    def test_nan_e_erro(self):
        y = np.ones(1000)
        y[5] = np.nan
        with pytest.raises(ErroSHAN, match="NaN"):
            montar_forma_de_onda({"Y": y}, "x.m", fs=1e6)


def test_localizar_arquivo_irmao(tmp_path):
    captura = tmp_path / "calibracao_1000Hz_rep1.bin"
    captura.write_bytes(b"")
    assert localizar_arquivo_osciloscopio(captura) is None
    (tmp_path / "calibracao_1000Hz_rep1.csv").write_text("1\n")
    (tmp_path / "calibracao_1000Hz_rep1.m").write_text("Y=[1];")
    assert localizar_arquivo_osciloscopio(captura).suffix == ".m"            # .m tem prioridade
    outra = tmp_path / "osc"
    outra.mkdir()
    assert localizar_arquivo_osciloscopio(captura, outra) is None


def test_argumentos_compartilhados_das_clis(tmp_path, sinal):
    _, y = sinal
    (tmp_path / "a.m").write_text(f"Y = {vetor(y)};\n")
    parser = argparse.ArgumentParser()
    adicionar_argumentos_osciloscopio(parser)
    args = parser.parse_args(["--osc-fs", f"{FS:g}", "--osc-escala", "2"])
    f = ler_forma_de_onda_dos_args(tmp_path / "a.m", args)
    assert f.fs == FS and f.valores[3] == pytest.approx(2 * y[3])
    with pytest.raises(ErroSHAN, match="--osc-escala"):
        ler_forma_de_onda_dos_args(tmp_path / "a.m", parser.parse_args(["--osc-fs", f"{FS:g}", "--osc-escala", "0"]))
    with pytest.raises(ErroSHAN, match="não encontrado"):
        ler_forma_de_onda(tmp_path / "nao_existe.m")
