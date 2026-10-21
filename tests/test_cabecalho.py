"""Cabeçalho "SHAN": v1, v2, v3 (faixa de entrada do ADC por canal), CRC, magic e conferência de consistência."""

import logging

import numpy as np
import pytest
from capturas_sinteticas import escrever_bin
from supraharmonicos.cabecalho import (
    CABECALHO_TAMANHO_TOTAL,
    conferir_consistencia_cabecalho,
    contar_amostras_arquivo_bin,
    imprimir_resumo_cabecalho,
    ler_cabecalho,
)
from supraharmonicos.constantes import FAIXAS_ADC_TOTAL_V, GRANDEZA_CORRENTE, GRANDEZA_TENSAO

T = np.arange(1000) / 200_000.0
SINAL = [np.sin(2 * np.pi * 1000 * T), 0.5 * np.sin(2 * np.pi * 2000 * T)]


def test_v2_le_metadados_grandeza_e_sonda(tmp_path):
    p = escrever_bin(tmp_path / "a.bin", SINAL, (0, 3), (GRANDEZA_TENSAO, GRANDEZA_CORRENTE), ("", "fluke_i30"),
                     titulo="Ensaio 1", descricao="bancada")
    c = ler_cabecalho(p)
    assert c is not None and c.crc32_valido
    assert c.versao_cabecalho == 2
    assert c.frequencia_hz == 400_000
    assert list(c.lista_canais) == [0, 3] and c.num_canais == 2
    assert list(c.grandeza_por_canal[:2]) == [GRANDEZA_TENSAO, GRANDEZA_CORRENTE]
    assert c.sonda_id_por_canal[1] == "fluke_i30" and c.sonda_id_por_canal[0] == ""
    assert c.titulo == "Ensaio 1" and c.descricao == "bancada"
    assert c.total_amostras_gravadas == 2000


def test_v1_continua_suportado_sem_campos_de_sonda(tmp_path):
    p = escrever_bin(tmp_path / "v1.bin", SINAL, versao=1)
    c = ler_cabecalho(p)
    assert c is not None and c.versao_cabecalho == 1 and c.crc32_valido
    assert not any(c.sonda_id_por_canal)


def test_sem_magic_devolve_none_arquivo_legado(tmp_path):
    p = escrever_bin(tmp_path / "legado.bin", SINAL, com_cabecalho=False)
    assert ler_cabecalho(p) is None


def test_crc_errado_e_sinalizado_com_aviso(tmp_path, caplog):
    p = escrever_bin(tmp_path / "crc.bin", SINAL, crc_valido=False)
    with caplog.at_level(logging.INFO):
        c = ler_cabecalho(p)
        imprimir_resumo_cabecalho(c)
    assert c is not None and not c.crc32_valido
    assert any("CRC-32 do cabeçalho NÃO confere" in r.getMessage() and r.levelno == logging.WARNING
               for r in caplog.records)


def test_arquivo_menor_que_o_cabecalho_nao_quebra(tmp_path):
    p = tmp_path / "curto.bin"
    p.write_bytes(b"SHAN" + b"\x00" * 10)          # tem o magic, mas não cabe um cabeçalho inteiro
    assert ler_cabecalho(p) is None


def test_contagem_de_amostras_pula_o_cabecalho(tmp_path):
    p = escrever_bin(tmp_path / "a.bin", SINAL)
    assert contar_amostras_arquivo_bin(p, "uint16", CABECALHO_TAMANHO_TOTAL) == 2000


@pytest.mark.parametrize("canais_cli, esperado_aviso", [([0, 1], "canais"), ([0, 3], None)])
def test_consistencia_avisa_quando_canais_cli_divergem_do_cabecalho(tmp_path, caplog, canais_cli, esperado_aviso):
    p = escrever_bin(tmp_path / "a.bin", SINAL, (0, 3), (0, 1), ("", "x"))
    c = ler_cabecalho(p)
    with caplog.at_level(logging.WARNING):
        conferir_consistencia_cabecalho(c, canais_cli, False, 2000, "uint16")
    avisos = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    if esperado_aviso:
        assert avisos and esperado_aviso in avisos[0]
    else:
        assert not avisos


# --------------------------------------------------------------------------------------
# v3: faixa de entrada do ADC por canal
# --------------------------------------------------------------------------------------
def test_v3_le_a_faixa_de_cada_canal_e_o_crc(tmp_path):
    p = escrever_bin(tmp_path / "v3.bin", SINAL, (0, 3), (GRANDEZA_TENSAO, GRANDEZA_CORRENTE), ("", "fluke_i30"),
                     faixas_adc_total_v=(20.48, 5.12))
    c = ler_cabecalho(p)
    assert c is not None and c.versao_cabecalho == 3 and c.crc32_valido
    assert c.faixa_adc_codigo_por_canal == (0, 2)
    assert c.faixa_adc_total_v_por_canal == (20.48, 5.12)
    assert list(c.lista_canais) == [0, 3] and c.sonda_id_por_canal[1] == "fluke_i30"    # os campos antigos seguem certos


def test_v3_com_crc_errado_e_sinalizado(tmp_path):
    p = escrever_bin(tmp_path / "v3.bin", SINAL, faixas_adc_total_v=10.24, crc_valido=False)
    c = ler_cabecalho(p)
    assert c is not None and c.versao_cabecalho == 3 and not c.crc32_valido


@pytest.mark.parametrize("versao", [1, 2])
def test_v1_e_v2_nao_sabem_a_faixa_do_adc(tmp_path, versao, caplog):
    p = escrever_bin(tmp_path / "antigo.bin", SINAL, versao=versao)
    with caplog.at_level(logging.WARNING):
        c = ler_cabecalho(p)
    assert c.faixa_adc_codigo_por_canal == () and c.faixa_adc_total_v_por_canal == (None, None)
    assert not caplog.records, "versões conhecidas (v1, v2) não devem gerar aviso"
    assert "faixa_adc_codigo_por_canal" not in c.para_attrs_hdf5()


def test_v3_vai_para_os_atributos_hdf5(tmp_path):
    p = escrever_bin(tmp_path / "v3.bin", SINAL, faixas_adc_total_v=(10.24, 5.12))
    attrs = ler_cabecalho(p).para_attrs_hdf5()
    assert list(attrs["faixa_adc_codigo_por_canal"]) == [1, 2]


def test_codigo_de_faixa_desconhecido_vira_none_sem_quebrar(tmp_path):
    from capturas_sinteticas import montar_cabecalho

    bruto = montar_cabecalho(1000, (0, 1), (0, 1), ("", ""), 400_000, versao=3, codigos_faixa_adc=[0, 9])
    p = tmp_path / "estranho.bin"
    p.write_bytes(bruto)
    c = ler_cabecalho(p)
    assert c.faixa_adc_codigo_por_canal == (0, 9) and c.faixa_adc_total_v_por_canal == (20.48, None)


def test_versao_futura_avisa_e_e_lida_como_v5(tmp_path, caplog):
    from capturas_sinteticas import montar_cabecalho

    bruto = bytearray(montar_cabecalho(1000, (0, 1), (0, 1), ("", ""), 400_000, versao=5, versao_firmware="v9"))
    bruto[4:8] = (6).to_bytes(4, "little")                      # "versão 6": formato que este código ainda não conhece
    p = tmp_path / "futuro.bin"
    p.write_bytes(bytes(bruto))
    with caplog.at_level(logging.WARNING):
        c = ler_cabecalho(p)
    assert c.versao_cabecalho == 6 and c.faixa_adc_total_v_por_canal == (20.48, 20.48) and c.buffers_sobrescritos == 0
    assert c.versao_firmware == "v9"
    assert any("só conhece até a versão 5" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------------------
# v5: versão do firmware e taxa medida pelo ARM (F5)
# --------------------------------------------------------------------------------------
def test_v5_le_a_versao_do_firmware_e_a_taxa_medida(tmp_path, caplog):
    p = escrever_bin(tmp_path / "v5.bin", SINAL, versao=5, versao_firmware="v0.6-3-g1234abc-dirty",
                     taxa_medida_hz=399_990.0)
    c = ler_cabecalho(p)
    assert c.crc32_valido and c.versao_cabecalho == 5
    assert c.versao_firmware == "v0.6-3-g1234abc-dirty" and c.taxa_medida_hz == 399_990.0
    attrs = c.para_attrs_hdf5()
    assert attrs["versao_firmware"] == "v0.6-3-g1234abc-dirty" and attrs["taxa_medida_hz"] == 399_990.0
    with caplog.at_level(logging.INFO):
        imprimir_resumo_cabecalho(c)
    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert "Firmware: v0.6-3-g1234abc-dirty" in texto and "Taxa medida pelo ARM: 399990 Hz (-0.003 %" in texto


def test_v5_sem_taxa_medida_e_v4_sem_versao(tmp_path):
    v5 = ler_cabecalho(escrever_bin(tmp_path / "um_bloco.bin", SINAL, versao=5))       # 1 bloco: o ARM não mede
    assert v5.taxa_medida_hz is None and v5.para_attrs_hdf5()["taxa_medida_hz"] == -1.0
    v4 = ler_cabecalho(escrever_bin(tmp_path / "v4.bin", SINAL, versao=4))
    assert v4.versao_firmware == "" and v4.taxa_medida_hz is None and "versao_firmware" not in v4.para_attrs_hdf5()


# --------------------------------------------------------------------------------------
# v4: integridade da captura (contada pela PRU) e atrasos de CS
# --------------------------------------------------------------------------------------
def test_v4_le_os_contadores_e_os_atrasos(tmp_path):
    p = escrever_bin(tmp_path / "v4.bin", SINAL, (0, 3), versao=4, faixas_adc_total_v=(20.48, 5.12),
                     integridade=(7, 1, 2), atrasos_cs=(20, 10, 10))
    c = ler_cabecalho(p)
    assert c.versao_cabecalho == 4 and c.crc32_valido and c.faixa_adc_codigo_por_canal == (0, 2)
    assert (c.amostras_atrasadas, c.buffers_sobrescritos, c.quadros_preambulo_ruim) == (7, 1, 2)
    assert c.atraso_cs_iteracoes == (20, 10, 10)
    problemas = c.problemas_integridade
    assert len(problemas) == 3 and "PERDIDAS" in problemas[0] and "MENOR" in problemas[1] and "SDO" in problemas[2]
    attrs = c.para_attrs_hdf5()
    assert attrs["buffers_sobrescritos"] == 1 and list(attrs["atraso_cs_iteracoes"]) == [20, 10, 10]


def test_v4_sem_problemas_e_v3_desconhecido_nao_avisam(tmp_path, caplog):
    v4 = ler_cabecalho(escrever_bin(tmp_path / "ok.bin", SINAL, versao=4))
    v3 = ler_cabecalho(escrever_bin(tmp_path / "v3.bin", SINAL, faixas_adc_total_v=10.24))
    assert v4.problemas_integridade == [] and v4.atraso_cs_iteracoes == (200, 100, 100)
    assert v3.amostras_atrasadas is None and v3.problemas_integridade == []        # desconhecido, não zero
    with caplog.at_level(logging.WARNING):
        imprimir_resumo_cabecalho(v4)
        imprimir_resumo_cabecalho(v3)
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_resumo_avisa_dos_problemas_de_integridade(tmp_path, caplog):
    c = ler_cabecalho(escrever_bin(tmp_path / "ruim.bin", SINAL, versao=4, integridade=(0, 2, 0)))
    with caplog.at_level(logging.WARNING):
        imprimir_resumo_cabecalho(c)
    assert any("2 buffer(s) sobrescrito(s)" in r.getMessage() for r in caplog.records)


def test_resumo_mostra_a_faixa_por_canal(tmp_path, caplog):
    p = escrever_bin(tmp_path / "v3.bin", SINAL, (0, 3), faixas_adc_total_v=(20.48, 5.12))
    with caplog.at_level(logging.INFO):
        imprimir_resumo_cabecalho(ler_cabecalho(p))
    texto = " ".join(r.getMessage() for r in caplog.records)
    assert "canal 0: ±10.24 V" in texto and "canal 3: ±2.56 V" in texto


def test_tabela_de_faixas_cobre_os_tres_codigos_do_ads8688():
    assert FAIXAS_ADC_TOTAL_V == {0: 20.48, 1: 10.24, 2: 5.12}
