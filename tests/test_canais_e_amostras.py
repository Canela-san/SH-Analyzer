"""Lista de canais, calibração por canal, desintercalação e conversão código -> volts."""

import numpy as np
import pytest
from supraharmonicos.amostras import (
    carregar_amostras_bin,
    carregar_amostras_csv,
    converter_para_tensao,
    detectar_tipo_arquivo,
    selecionar_intervalo,
)
from supraharmonicos.canais import (
    alinhar_ao_ciclo,
    analisar_lista_calibracao,
    analisar_lista_canais,
    desintercalar,
    resolver_offsets_por_canal,
    validar_subconjunto_canais,
)
from supraharmonicos.erros import ErroSHAN


class TestListaDeCanais:
    def test_preserva_a_ordem_informada(self):
        assert analisar_lista_canais("3, 1,0") == [3, 1, 0]

    @pytest.mark.parametrize("texto, trecho", [
        ("1,1", "repetido"),
        ("8", "só tem canais 0-7"),
        ("a", "não é um canal válido"),
        ("", "lista de canais vazia"),
    ])
    def test_entradas_invalidas(self, texto, trecho):
        with pytest.raises(ErroSHAN, match=trecho):
            analisar_lista_canais(texto)

    def test_exibir_precisa_ser_subconjunto(self):
        validar_subconjunto_canais([1], [0, 1])
        with pytest.raises(ErroSHAN, match="ausente"):
            validar_subconjunto_canais([2], [0, 1])


class TestCalibracaoPorCanal:
    def test_valor_unico_vale_para_todos(self):
        assert analisar_lista_calibracao("10.24", 3, "--faixa") == [10.24] * 3

    def test_quantidade_errada(self):
        with pytest.raises(ErroSHAN, match="Passe 1 valor ou exatamente 2"):
            analisar_lista_calibracao("1,2,3", 2, "--ganho")

    def test_nao_numerico(self):
        with pytest.raises(ErroSHAN, match="valor inválido"):
            analisar_lista_calibracao("x", 1, "--ganho")

    def test_offset_padrao_uint16_e_meia_faixa_int16_e_zero(self):
        assert resolver_offsets_por_canal(None, [10.24, 5.12], "uint16", 2) == [5.12, 2.56]
        assert resolver_offsets_por_canal(None, [10.24], "int16", 1) == [0.0]
        assert resolver_offsets_por_canal("0.5", [10.24, 5.12], "uint16", 2) == [0.5, 0.5]


def test_desintercalar_round_robin():
    amostras = np.arange(12, dtype=np.uint16)
    por_canal = desintercalar(amostras, [0, 2, 5], [2, 5])
    assert set(por_canal) == {2, 5}
    np.testing.assert_array_equal(por_canal[2], [1, 4, 7, 10])
    np.testing.assert_array_equal(por_canal[5], [2, 5, 8, 11])


class TestConversaoParaTensao:
    def test_uint16_meia_escala_e_zero_volt(self):
        v = converter_para_tensao(np.array([0, 32768, 65535], dtype=np.uint16), 10.24, 1.0, "uint16", 5.12)
        np.testing.assert_allclose(v, [-5.12, 0.0, 5.12 - 10.24 / 65536], atol=1e-12)

    def test_int16_com_ganho(self):
        v = converter_para_tensao(np.array([-32768, 0, 32767], dtype=np.int16), 10.24, 2.0, "int16", 0.0)
        np.testing.assert_allclose(v, [-20.48, 0.0, 2 * 10.24 * 32767 / 32768], atol=1e-9)


class TestLeituraDeArquivos:
    def test_bin_com_offset_pula_o_cabecalho(self, tmp_path):
        p = tmp_path / "x.bin"
        p.write_bytes(b"\xff" * 8 + np.array([1, 2, 3], dtype="<u2").tobytes())
        np.testing.assert_array_equal(carregar_amostras_bin(p, "uint16", offset=8), [1, 2, 3])

    def test_bin_inexistente_vazio_e_truncado(self, tmp_path):
        with pytest.raises(ErroSHAN, match="não encontrado"):
            carregar_amostras_bin(tmp_path / "nao_existe.bin", "uint16")
        vazio = tmp_path / "vazio.bin"
        vazio.write_bytes(b"")
        with pytest.raises(ErroSHAN):
            carregar_amostras_bin(vazio, "uint16")
        impar = tmp_path / "impar.bin"
        impar.write_bytes(b"\x00" * 7)
        with pytest.raises(ErroSHAN, match="falha ao abrir"):
            carregar_amostras_bin(impar, "uint16")

    def test_csv_le_a_coluna_valor_bruto(self, tmp_path):
        p = tmp_path / "x.csv"
        p.write_text("indice,valor_bruto\n0,10\n1,20\n", encoding="utf-8")
        np.testing.assert_array_equal(carregar_amostras_csv(p, "uint16"), [10, 20])

    def test_tipo_de_arquivo_pela_extensao(self, tmp_path):
        assert detectar_tipo_arquivo(tmp_path / "a.BIN") == "bin"
        assert detectar_tipo_arquivo(tmp_path / "a.csv") == "csv"
        with pytest.raises(ErroSHAN, match="extensão '.txt' não reconhecida"):
            detectar_tipo_arquivo(tmp_path / "a.txt")

    def test_selecionar_intervalo(self):
        dados = np.arange(100)
        trecho, ini, fim, total = selecionar_intervalo(dados, 10, 20)
        assert (ini, fim, total) == (10, 20, 100) and len(trecho) == 10
        with pytest.raises(ErroSHAN):
            selecionar_intervalo(dados, 50, 10)


class TestAlinhamentoAoCiclo:
    def test_inicio_no_meio_do_ciclo_volta_ao_comeco_dele_com_aviso(self, caplog):
        assert alinhar_ao_ciclo(7, 3) == 6
        assert "cai no meio de um ciclo de 3 canais" in caplog.text

    def test_inicio_alinhado_ou_um_canal_nao_muda_nada(self, caplog):
        assert alinhar_ao_ciclo(8, 2) == 8 and alinhar_ao_ciclo(5, 1) == 5 and alinhar_ao_ciclo(-4, 2) == 0
        assert caplog.text == ""


@pytest.mark.parametrize("texto", ["nan", "1,inf", "-inf"])
def test_calibracao_recusa_valores_nao_finitos(texto):
    with pytest.raises(ErroSHAN, match="números finitos"):
        analisar_lista_calibracao(texto, 2, "--ganho")
