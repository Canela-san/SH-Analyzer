"""Núcleo de DSP: filtros, fundamental, janelas, espectro (FFT/Welch), bandas e picos."""

import numpy as np
import pytest
from supraharmonicos.erros import ErroSHAN
from supraharmonicos.espectro import (
    agrupar_em_bandas,
    calcular_espectro,
    calcular_espectro_welch,
    enbw_bins,
    encontrar_picos_espectro,
    resolver_nome_janela,
    tamanho_segmento_welch,
)
from supraharmonicos.filtros import aplicar_filtro_digital, validar_corte_filtro
from supraharmonicos.fundamental import (
    estimar_frequencia_fundamental,
    recortar_ciclos_inteiros,
    refinar_pico_parabolico,
)

FS = 200_000.0


def tempo(dur_s):
    return np.arange(int(FS * dur_s)) / FS


class TestFiltros:
    def test_passa_alta_remove_a_fundamental_e_preserva_o_resto(self):
        t = tempo(1.0)
        x = np.sin(2 * np.pi * 50 * t) + 0.1 * np.sin(2 * np.pi * 3000 * t)
        y = aplicar_filtro_digital(x, FS, "high", 1000.0, 5)
        assert np.std(y) == pytest.approx(0.1 / np.sqrt(2), rel=1e-3)

    def test_passa_baixa_remove_o_tom_alto(self):
        t = tempo(1.0)
        x = np.sin(2 * np.pi * 100 * t) + np.sin(2 * np.pi * 50_000 * t)
        y = aplicar_filtro_digital(x, FS, "low", 1000.0, 5)
        assert np.std(y) == pytest.approx(1 / np.sqrt(2), rel=1e-2)

    def test_fase_zero_nao_desloca_o_sinal(self):
        t = tempo(0.5)
        x = np.sin(2 * np.pi * 1000 * t)
        y = aplicar_filtro_digital(x, FS, "high", 100.0, 4)
        meio = slice(len(t) // 4, 3 * len(t) // 4)
        assert np.max(np.abs(y[meio] - x[meio])) < 1e-3

    @pytest.mark.parametrize("corte", [0.0, -5.0, 100_000.0, 150_000.0])
    def test_corte_invalido(self, corte):
        with pytest.raises(ErroSHAN):
            validar_corte_filtro(corte, FS, "--filtro-passa-alta")

    def test_janela_curta_demais_para_a_ordem_vira_erro_de_dominio(self):
        with pytest.raises(ErroSHAN, match="falha ao aplicar o filtro"):
            aplicar_filtro_digital(np.zeros(10), FS, "high", 1000.0, 8)


class TestFundamental:
    def sinal_50hz(self, f0=50.0, dur=1.0):
        t = tempo(dur)
        return np.sin(2 * np.pi * f0 * t) + 0.1 * np.sin(2 * np.pi * 3000 * t)

    def test_estima_a_frequencia_com_precisao(self):
        assert estimar_frequencia_fundamental(self.sinal_50hz(49.8), FS, 40, 70) == pytest.approx(49.8, abs=0.05)  # estimador FFT + parábola: ~0,02 Hz de erro em 1 s de captura

    def test_corte_em_ciclos_inteiros(self):
        sinal, i0, i1, f0, n = recortar_ciclos_inteiros(self.sinal_50hz(), FS, 40, 70, 10)
        assert n == 10 and f0 == pytest.approx(50.0, abs=0.01)
        assert len(sinal) == i1 - i0                      # sinal[i0:i1]: o fim é exclusivo
        assert len(sinal) / FS == pytest.approx(10 / f0, rel=1e-3)

    def test_poucos_dados_viram_erro_de_dominio(self):
        with pytest.raises(ErroSHAN, match="poucos dados"):
            estimar_frequencia_fundamental(np.zeros(8), FS, 40, 70)

    def test_refino_parabolico_recupera_pico_entre_bins(self):
        n = 20_000
        t = np.arange(n) / FS
        f_real = 10_037.0                                     # cai entre dois bins (resolução 10 Hz)
        _, db = calcular_espectro(np.sin(2 * np.pi * f_real * t), FS, "hann", 8.6, "tom")
        i = int(np.argmax(db))
        delta, amp_db = refinar_pico_parabolico(db, i)
        resolucao = FS / n
        assert i * resolucao + delta * resolucao == pytest.approx(f_real, abs=0.5)
        assert 10 ** (amp_db / 20) == pytest.approx(1.0, rel=2e-2)


class TestEspectro:
    @pytest.mark.parametrize("janela", ["retangular", "hann", "flattop", "blackmanharris", "kaiser"])
    def test_tom_com_ciclos_inteiros_tem_amplitude_exata(self, janela):
        t = tempo(0.1)
        x = 0.5 * np.sin(2 * np.pi * 10_000 * t)
        nome = resolver_nome_janela(janela)
        freqs, db = calcular_espectro(x, FS, nome, 8.6, "tom")
        i = int(np.argmax(db))
        assert freqs[i] == pytest.approx(10_000.0, abs=freqs[1])
        assert 10 ** (db[i] / 20) == pytest.approx(0.5, rel=1e-2)

    def test_janela_desconhecida(self):
        with pytest.raises(ErroSHAN):
            resolver_nome_janela("nao_existe")

    def test_welch_mede_dois_tons_com_amplitudes_corretas(self):
        t = tempo(1.0)
        x = 0.5 * np.sin(2 * np.pi * 10_000 * t) + 0.01 * np.sin(2 * np.pi * 33_333 * t + 0.3)
        freqs, db, n_seg = calcular_espectro_welch(x, FS, "flattop", 8.6, 100.0, 0.5, "tom")
        assert n_seg > 100
        picos = encontrar_picos_espectro(freqs, db, 1000.0, 100_000.0, -60.0, 500.0)
        assert len(picos) == 2
        assert picos[0]["frequencia_hz"] == pytest.approx(10_000.0, abs=1.0)
        assert 10 ** (picos[0]["amplitude_db"] / 20) == pytest.approx(0.5, rel=1e-3)
        assert 10 ** (picos[1]["amplitude_db"] / 20) == pytest.approx(0.01, rel=0.05)

    def test_welch_modo_ruido_psd_nao_depende_da_resolucao(self):
        x = np.random.default_rng(3).normal(0, 1.0, int(FS * 2))
        medias = []
        for res in (200.0, 800.0):
            _, db, _ = calcular_espectro_welch(x, FS, "hann", 8.6, res, 0.5, "ruido")
            medias.append(np.mean(db[5:-5]))
        assert medias[0] == pytest.approx(medias[1], abs=0.5)         # PSD de ruído branco é plana e invariante

    def test_agrupar_em_bandas(self):
        freqs = np.arange(0, 10_000, 10.0)
        db = np.full_like(freqs, -60.0)
        f_b, db_b = agrupar_em_bandas(freqs, db, 200.0, "tom")
        assert len(f_b) == len(db_b) and 40 <= len(f_b) <= 51
        assert np.all(np.diff(f_b) > 0)

    def test_limiar_de_picos_e_distancia_minima(self):
        freqs = np.arange(0, 20_000, 10.0)
        db = np.full_like(freqs, -100.0)
        db[500] = -20.0     # 5 kHz
        db[510] = -30.0     # 5,1 kHz, a menos de 500 Hz do maior -> suprimido
        db[1500] = -50.0    # 15 kHz
        picos = encontrar_picos_espectro(freqs, db, 1000.0, 19_000.0, -60.0, 500.0)
        assert [round(p["frequencia_hz"]) for p in picos] == [5000, 15000]


class TestNiveisPorBanda:
    """--agrupar-bandas: o nível RMS de uma banda não pode depender da janela nem do modo de normalização."""

    @pytest.mark.parametrize("janela", ["boxcar", "hann", "flattop", "blackmanharris"])
    def test_tom_e_ruido_dao_o_rms_do_seno_com_qualquer_janela(self, janela):
        fs, n, f0, amp = 100_000.0, 1 << 16, 5_013.7, 1.0      # tom fora do centro do bin, de propósito
        t = np.arange(n) / fs
        sinal = amp * np.sin(2 * np.pi * f0 * t)
        esperado = 20 * np.log10(amp / np.sqrt(2))              # -3,01 dB: RMS de um seno de pico 1
        for modo in ("tom", "ruido"):
            freqs, db = calcular_espectro(sinal, fs, janela, 8.6, modo)
            f_b, db_b = agrupar_em_bandas(freqs, db, 1000.0, modo, enbw=enbw_bins(janela, n, 8.6))
            banda = int(np.argmin(np.abs(f_b - 5_500.0)))       # a banda [5 kHz, 6 kHz)
            assert db_b[banda] == pytest.approx(esperado, abs=0.05), (janela, modo)

    def test_welch_em_tom_tambem_bate_com_o_rms(self):
        fs, f0 = 100_000.0, 12_345.0
        t = np.arange(400_000) / fs
        sinal = 0.5 * np.sin(2 * np.pi * f0 * t)
        freqs, db, _ = calcular_espectro_welch(sinal, fs, "flattop", 8.6, 100.0, 0.5, "tom")
        f_b, db_b = agrupar_em_bandas(freqs, db, 2000.0, "tom",
                                      enbw=enbw_bins("flattop", tamanho_segmento_welch(fs, 100.0), 8.6))
        banda = int(np.argmin(np.abs(f_b - 13_000.0)))
        assert db_b[banda] == pytest.approx(20 * np.log10(0.5 / np.sqrt(2)), abs=0.05)

    @pytest.mark.parametrize("n", [4096, 4097])
    def test_psd_de_um_lado_fecha_parseval_com_n_par_e_impar(self, n):
        """O último bin só deixa de dobrar quando é o de Nyquist (N par): com N ímpar ele tem par negativo."""
        fs = 1000.0
        sinal = np.random.default_rng(3).normal(0, 1.0, n)
        freqs, db = calcular_espectro(sinal, fs, "boxcar", 8.6, "ruido")
        potencia = np.sum(10 ** (db / 10)) * (freqs[1] - freqs[0])
        assert potencia == pytest.approx(np.var(sinal), rel=1e-9)
