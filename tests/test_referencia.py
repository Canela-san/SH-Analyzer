"""``referencia``: amplitude com unidades, frequência e o marcador ``ref:`` dos metadados."""

import math

import pytest
from supraharmonicos.erros import ErroSHAN
from supraharmonicos.referencia import (
    analisar_amplitude,
    analisar_frequencia,
    extrair_referencia,
    formatar_referencia,
    pico_fisico,
)


class TestAmplitude:
    @pytest.mark.parametrize("texto,pico,unidade,tipo", [
        ("500mVpp", 0.25, "V", "pp"),
        ("500 mV pp", 0.25, "V", "pp"),
        ("500mV_pp", 0.25, "V", "pp"),
        ("500mVp-p", 0.25, "V", "pp"),
        ("0,5Vpp", 0.25, "V", "pp"),
        ("1Vpk-pk", 0.5, "V", "pp"),
        ("250mVpk", 0.25, "V", "pico"),
        ("250mVp", 0.25, "V", "pico"),
        ("0.25V pico", 0.25, "V", "pico"),
        ("500uVpp", 0.25e-3, "V", "pp"),
        ("500µVpp", 0.25e-3, "V", "pp"),
        ("1e-1Vpk", 0.1, "V", "pico"),
        ("2Arms", 2 * math.sqrt(2), "A", "rms"),
        ("353.55mVrms", 0.5, "V", "rms"),
        ("1.2 A_pp", 0.6, "A", "pp"),
        ("3kApk", 3000.0, "A", "pico"),
        ("500mvpp", 0.25, "V", "pp"),
    ])
    def test_converte_para_pico(self, texto, pico, unidade, tipo):
        a = analisar_amplitude(texto)
        assert a.pico == pytest.approx(pico, rel=1e-3 if "353" in texto else 1e-12)
        assert (a.unidade, a.tipo, a.texto) == (unidade, tipo, texto.strip())

    def test_numero_puro_e_pico_em_amperes_como_antes(self):
        a = analisar_amplitude("0.5")
        assert (a.pico, a.unidade, a.tipo) == (0.5, "A", "pico")

    def test_propriedades_derivadas(self):
        a = analisar_amplitude("500mVpp")
        assert a.pico_a_pico == pytest.approx(0.5) and a.rms == pytest.approx(0.25 / math.sqrt(2))

    @pytest.mark.parametrize("texto,trecho", [
        ("500mV", "sem tipo"),            # fator 2 escondido: não pode passar em silêncio
        ("2A", "sem tipo"),
        ("2rms", "sem unidade"),
        ("500pp", "sem unidade"),
        ("10m", "sem unidade"),
        ("500MVpp", "não entendida"),     # M maiúsculo = mega: não suportado
        ("abc", "não entendida"),
        ("", "não entendida"),
        ("-1Vpp", "positivo"),
        ("0Vpp", "positivo"),
        ("500mVpp extra", "não entendida"),
    ])
    def test_entradas_invalidas_dao_erro_claro(self, texto, trecho):
        with pytest.raises(ErroSHAN, match=trecho):
            analisar_amplitude(texto)


class TestFrequencia:
    @pytest.mark.parametrize("texto,hz", [("1000", 1000.0), ("1000Hz", 1000.0), ("1.5kHz", 1500.0), ("1,5 khz", 1500.0),
                                          ("2MHz", 2e6), ("50 hz", 50.0), ("1e3", 1000.0)])
    def test_valores(self, texto, hz):
        assert analisar_frequencia(texto) == pytest.approx(hz)

    @pytest.mark.parametrize("texto", ["5mHz", "abc", "", "0Hz", "-5Hz", "1 GHz"])
    def test_invalidos(self, texto):
        with pytest.raises(ErroSHAN):
            analisar_frequencia(texto)


class TestPicoFisico:
    def test_tensao_vira_grandeza_fisica_pelo_ganho(self):
        assert pico_fisico(analisar_amplitude("500mVpp"), 10.0) == pytest.approx(2.5)

    def test_corrente_ja_e_grandeza_fisica(self):
        assert pico_fisico(analisar_amplitude("2Apk"), 10.0) == pytest.approx(2.0)


class TestMetadados:
    def test_ida_e_volta(self):
        texto = formatar_referencia(1234.5678, "500mVpp")
        assert texto == "ref: f=1234.5678Hz amp=500mVpp"
        r = extrair_referencia(texto)
        assert r.freq_hz == pytest.approx(1234.5678) and r.amplitude.pico == pytest.approx(0.25)

    def test_so_um_dos_campos(self):
        assert formatar_referencia(freq_hz=50.0) == "ref: f=50Hz"
        assert extrair_referencia("ref: amp=2Arms").freq_hz is None
        assert formatar_referencia() == ""

    def test_texto_livre_antes_e_depois_e_ignorado(self):
        r = extrair_referencia("Sonda i30s, bancada 2; ref: f=1kHz amp=250mVpk, gerador em Hi-Z. obs: ok")
        assert r.freq_hz == 1000.0 and r.amplitude.pico == pytest.approx(0.25)

    def test_maiusculas_e_chave_desconhecida(self):
        r = extrair_referencia("REF: F=2kHz carga=50ohm AMP=1Vpp")
        assert r.freq_hz == 2000.0 and r.amplitude.pico == pytest.approx(0.5)

    @pytest.mark.parametrize("descricao", [None, "", "sem marcador", "ref: carga=50ohm", "preferencia: f=1Hz"])
    def test_sem_referencia_utilizavel_devolve_none(self, descricao):
        assert extrair_referencia(descricao) is None

    def test_valor_ilegivel_e_erro(self):
        with pytest.raises(ErroSHAN, match="sem tipo"):
            extrair_referencia("ref: f=1000Hz amp=500mV")

    def test_amplitude_com_espaco_nao_cabe_nos_metadados(self):
        with pytest.raises(ErroSHAN, match="sem espaços"):
            formatar_referencia(1000.0, "500 mVpp")

    def test_cabe_no_campo_de_256_bytes(self):
        assert len(formatar_referencia(123456.789012, "176.7766953mVrms").encode()) < 256
