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


def test_versao_futura_avisa_e_e_lida_como_v9(tmp_path, caplog):
    from capturas_sinteticas import montar_cabecalho

    bruto = bytearray(montar_cabecalho(1000, (0, 1), (0, 1), ("", ""), 400_000, versao=9, versao_firmware="v9",
                                       spi=(2, 5, 0)))
    bruto[4:8] = (10).to_bytes(4, "little")                     # "versão 10": formato que este código ainda não conhece
    p = tmp_path / "futuro.bin"
    p.write_bytes(bytes(bruto))
    with caplog.at_level(logging.WARNING):
        c = ler_cabecalho(p)
    assert c.versao_cabecalho == 10 and c.faixa_adc_total_v_por_canal == (20.48, 20.48) and c.buffers_sobrescritos == 0
    assert c.versao_firmware == "v9" and c.folga_minima_ciclos == 20 and c.modo_spi == 2
    assert c.placa == "A335BNLT 00C0 3714BBBK1234" and c.tamanho_cabecalho == 4096 and c.hostname == "beaglebone"
    assert any("só conhece até a versão 9" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------------------
# v7: o modo do SPI e as divergências entre as fases de leitura (22/10/2026)
# --------------------------------------------------------------------------------------
def test_v7_le_o_spi_rapido_e_as_divergencias(tmp_path, caplog):
    p = escrever_bin(tmp_path / "v7.bin", SINAL, fs_total=400_000, versao=7, grade=(22, 0, 7, 3), blocos=1,
                     spi=(2, 0, 13))
    c = ler_cabecalho(p)
    assert c.crc32_valido and c.versao_cabecalho == 7 and c.sample_period_ticks == 500
    assert (c.modo_spi, c.divergencias_fase_a, c.divergencias_fase_c) == (2, 0, 13) and c.spi_rapido
    assert c.grade_exata is True                     # desde a v7, 1 bloco já tem a folga (com a troca de buffer)
    attrs = c.para_attrs_hdf5()
    assert attrs["modo_spi"] == 2 and attrs["divergencias_fase_c"] == 13
    with caplog.at_level(logging.INFO):
        imprimir_resumo_cabecalho(c)
    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert "SPI: rápido (~15,4 MHz), leitura da fase B (75 ns) gravada; 0 quadro(s) com a fase A diferente da B e 13 com a C" in texto


def test_v7_com_o_spi_lento_e_v6_sem_o_campo(tmp_path, caplog):
    lento = ler_cabecalho(escrever_bin(tmp_path / "p.bin", SINAL, fs_total=312_500, versao=7, spi=(0, 0, 0)))
    assert lento.modo_spi == 0 and not lento.spi_rapido and lento.descrever_spi().startswith("lento (~10,7 MHz")
    with caplog.at_level(logging.INFO):
        imprimir_resumo_cabecalho(lento)
    assert "SPI: lento" in "\n".join(r.getMessage() for r in caplog.records)
    v6 = ler_cabecalho(escrever_bin(tmp_path / "v6.bin", SINAL, fs_total=312_500, versao=6))
    assert v6.modo_spi is None and v6.descrever_spi() is None and "modo_spi" not in v6.para_attrs_hdf5()


def test_v7_folga_ainda_nao_publicada_vale_o_periodo(tmp_path):
    c = ler_cabecalho(escrever_bin(tmp_path / "n.bin", SINAL, fs_total=312_500, versao=7, grade=(640, 0, 7, 3)))
    assert c.grade_exata is None and "não publicada" in c.descrever_grade()


# --------------------------------------------------------------------------------------
# v6: grade de tempo publicada pela PRU (22/10/2026)
# --------------------------------------------------------------------------------------
def test_v6_le_a_grade_de_tempo(tmp_path, caplog):
    p = escrever_bin(tmp_path / "v6.bin", SINAL, fs_total=312_500, versao=6, grade=(23, 0, 3, 2), blocos=3)
    c = ler_cabecalho(p)
    assert c.crc32_valido and c.versao_cabecalho == 6 and c.sample_period_ticks == 640
    assert (c.folga_minima_ciclos, c.atraso_maximo_ciclos, c.ciclos_rebase, c.versao_protocolo_pru) == (23, 0, 3, 2)
    assert c.grade_exata is True
    attrs = c.para_attrs_hdf5()
    assert attrs["folga_minima_ciclos"] == 23 and attrs["ciclos_rebase"] == 3 and attrs["versao_protocolo_pru"] == 2
    with caplog.at_level(logging.INFO):
        imprimir_resumo_cabecalho(c)
    texto = "\n".join(r.getMessage() for r in caplog.records)
    # 200 MHz / (640 - 23) = 324,1 kS/s: a maior taxa em que a mesma folga ainda daria período constante
    assert ("Grade de tempo (PRU): exata -- toda amostra no ciclo da grade, folga mínima 23 ciclos (115 ns); "
            "período constante até ~324.1 kS/s") in texto


def test_v6_com_amostras_atrasadas_ou_um_bloco_so_nao_garante_a_grade(tmp_path):
    atrasada = ler_cabecalho(escrever_bin(tmp_path / "a.bin", SINAL, fs_total=312_500, versao=6, blocos=3,
                                          integridade=(5, 0, 0), grade=(0, 40, 2, 2)))
    assert atrasada.grade_exata is False
    assert atrasada.descrever_grade() == "5 amostra(s) fora da grade, a pior 40 ciclos (200 ns) atrasada"
    um_bloco = ler_cabecalho(escrever_bin(tmp_path / "b.bin", SINAL, fs_total=312_500, versao=6, grade=(640, 0, 2, 2)))
    assert um_bloco.grade_exata is None and "folga não publicada" in um_bloco.descrever_grade()
    v5 = ler_cabecalho(escrever_bin(tmp_path / "v5.bin", SINAL, versao=5))
    assert v5.folga_minima_ciclos is None and v5.grade_exata is None and v5.descrever_grade() is None
    assert "folga_minima_ciclos" not in v5.para_attrs_hdf5()


# --------------------------------------------------------------------------------------
# v5: versão do firmware e taxa medida pelo ARM (F5)
# --------------------------------------------------------------------------------------
def test_v8_le_titulo_e_descricao_maiores_e_o_sistema(tmp_path, caplog):
    titulo = "CAL F cs padrao 312500 quadrada256Hz16Vpp+2V 30s spi lenta f20.48 " + "x" * 61    # 127 bytes
    descricao = "d" * 271
    p = escrever_bin(tmp_path / "v8.bin", SINAL, (0, 3), (GRANDEZA_TENSAO, GRANDEZA_CORRENTE), ("", "fluke_i30"),
                     versao=8, titulo=titulo, descricao=descricao, codigos_faixa_adc=(2, 0), integridade=(0, 1, 0),
                     versao_firmware="v0.7-18-gabcdef0", spi=(2, 0, 3))
    c = ler_cabecalho(p)
    assert c.crc32_valido and c.versao_cabecalho == 8
    assert len(titulo.encode()) == 127 and c.titulo == titulo and c.descricao == descricao
    # os campos da v7 continuam lidos no mesmo lugar
    assert c.sonda_id_por_canal == ("", "fluke_i30") and c.faixa_adc_codigo_por_canal == (2, 0)
    assert c.buffers_sobrescritos == 1 and c.versao_firmware == "v0.7-18-gabcdef0" and c.divergencias_fase_c == 3
    assert c.kernel == "5.10.168-ti-r72" and c.placa == "A335BNLT 00C0 3714BBBK1234"
    assert c.sistema_operacional == "BeagleBoard.org Debian Bullseye IoT Image 2023-09-02"
    assert c.timestamp_ns == 123456789 and c.relogio_sincronizado is True and c.uptime_s == 3600
    assert c.carga_1min == 0.25 and c.memoria_disponivel_kib == 300_000
    assert (c.disco_saida_total_kib, c.disco_saida_livre_kib, c.disco_saida_livre_fim_kib) == (3_500_000, 2_000_000,
                                                                                               1_900_000)
    assert (c.disco_programa_total_kib, c.disco_programa_livre_kib) == (3_500_000, 2_000_000)
    attrs = c.para_attrs_hdf5()
    assert attrs["placa"] == c.placa and attrs["relogio_sincronizado"] == 1 and attrs["disco_saida_livre_kib"] == 2_000_000
    with caplog.at_level(logging.INFO):
        imprimir_resumo_cabecalho(c)
    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert "BeagleBone: placa A335BNLT 00C0 3714BBBK1234 | BeagleBoard.org Debian" in texto
    assert "relógio sincronizado (NTP); ligada há 1 h 00 min; carga do ARM 0.25; memória disponível 293 MiB" in texto
    assert "disco da captura: 1.91 de 3.34 GiB livres no início, 1.81 no fim" in texto


def test_v8_sem_o_que_o_ler_adc_nao_leu_e_relogio_sem_ntp(tmp_path, caplog):
    desconhecido = 0xFFFFFFFF
    p = escrever_bin(tmp_path / "v8.bin", SINAL, versao=8,
                     sistema={"kernel": "", "placa": "", "relogio": 0, "uptime": desconhecido, "carga": desconhecido,
                              "memoria": desconhecido, "saida": (desconhecido, desconhecido, desconhecido)})
    c = ler_cabecalho(p)
    assert c.crc32_valido and c.kernel == "" and c.placa == "" and c.relogio_sincronizado is False
    assert c.uptime_s is None and c.carga_1min is None and c.memoria_disponivel_kib is None
    assert c.disco_saida_total_kib is None and c.disco_saida_livre_fim_kib is None
    assert c.para_attrs_hdf5()["uptime_s"] == -1
    with caplog.at_level(logging.INFO):
        imprimir_resumo_cabecalho(c)
    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert "placa ? |" in texto and "kernel ?" in texto and "NÃO sincronizado: a data pode estar errada" in texto
    assert "disco da captura: ? de ? GiB livres no início;" in texto


def test_v7_nao_tem_o_sistema(tmp_path):
    c = ler_cabecalho(escrever_bin(tmp_path / "v7.bin", SINAL, versao=7, titulo="t" * 63))
    assert c.crc32_valido and c.titulo == "t" * 63 and c.placa == "" and c.relogio_sincronizado is None
    assert c.descrever_sistema() == [] and "placa" not in c.para_attrs_hdf5()


def test_v5_le_a_versao_do_firmware_e_a_taxa_medida(tmp_path, caplog):
    p = escrever_bin(tmp_path / "v5.bin", SINAL, versao=5, versao_firmware="v0.6-3-g1234abc-dirty",
                     taxa_medida_hz=399_990.0)
    c = ler_cabecalho(p)
    assert c.crc32_valido and c.versao_cabecalho == 5
    assert c.versao_firmware == "v0.6-3-g1234abc-dirty" and c.taxa_medida_hz == 399_990.0 and c.buffers_ping_pong == 2
    attrs = c.para_attrs_hdf5()
    assert attrs["versao_firmware"] == "v0.6-3-g1234abc-dirty" and attrs["taxa_medida_hz"] == 399_990.0
    with caplog.at_level(logging.INFO):
        imprimir_resumo_cabecalho(c)
    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert "Firmware: v0.6-3-g1234abc-dirty" in texto and "Taxa medida pelo ARM: 399990 Hz (-0.003 %" in texto
    assert "Ping-pong: 2 buffers de 1048576 amostras brutas (2.0 MiB cada; 524288 por canal; cada bloco dura 2.621 s)" in texto


def test_v5_sem_taxa_medida_e_v4_sem_versao(tmp_path):
    v5 = ler_cabecalho(escrever_bin(tmp_path / "um_bloco.bin", SINAL, versao=5))       # 1 bloco: o ARM não mede
    assert v5.taxa_medida_hz is None and v5.para_attrs_hdf5()["taxa_medida_hz"] == -1.0
    v4 = ler_cabecalho(escrever_bin(tmp_path / "v4.bin", SINAL, versao=4))
    assert v4.versao_firmware == "" and v4.taxa_medida_hz is None and "versao_firmware" not in v4.para_attrs_hdf5()
    assert v4.buffers_ping_pong is None and v5.para_attrs_hdf5()["buffers_ping_pong"] == 2


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


# ---------------------------------------------------------------------------
# [11/11/2026] Cabeçalho v9: 4096 bytes, os campos da v8 onde estavam e a extensão
# ---------------------------------------------------------------------------
def _captura_v9(tmp_path, nome="v9.bin", **kw):
    import numpy as np
    from capturas_sinteticas import escrever_bin
    t = np.arange(4000) / 200_000.0
    sinais = [3.0 * np.sin(2 * np.pi * 1000 * t), 0.5 * np.sin(2 * np.pi * 1000 * t) + 0.1]
    return escrever_bin(tmp_path / nome, sinais, versao=9, faixas_adc_total_v=[20.48, 5.12], **kw), sinais


def test_v9_tem_4096_bytes_e_nada_da_v8_mudou_de_lugar(tmp_path):
    """A v9 aumenta o cabeçalho para 4096 bytes SEM tirar nem mover campo: os 1024 primeiros bytes são os da v8 (os
    scripts leem campos por offset), inclusive primeira_amostra_descartada, e as amostras começam no byte 4096."""
    import struct

    import numpy as np
    from capturas_sinteticas import montar_cabecalho
    v8 = montar_cabecalho(1000, (0, 1), (0, 1), ("", "s"), 400_000, versao=8, titulo="t", descricao="d")
    v9 = montar_cabecalho(1000, (0, 1), (0, 1), ("", "s"), 400_000, versao=9, titulo="t", descricao="d")
    assert len(v8) == 1024 and len(v9) == 4096
    # iguais byte a byte, menos a versão (4), o tamanho (8) e o CRC (1020)
    diferentes = {i for i in range(1024) if v8[i] != v9[i]}
    assert diferentes <= {4, 8, 9, *range(1020, 1024)}
    assert struct.unpack_from("<I", v9, 8)[0] == 4096 and struct.unpack_from("<I", v9, 56)[0] == 0
    p, sinais = _captura_v9(tmp_path)
    c = ler_cabecalho(p)
    assert c.versao_cabecalho == 9 and c.crc32_valido and c.tamanho_cabecalho == 4096
    assert c.primeira_amostra_descartada is False
    codigos = np.fromfile(p, dtype="<u2", offset=c.tamanho_cabecalho)
    assert len(codigos) == 2 * 4000 == c.total_amostras_gravadas
    assert codigos[0] == 32768                                  # a 1ª amostra do canal 0: seno em zero, meio da escala


def test_v9_extensao_o_crc_das_amostras_e_o_sinal_de_cada_canal(tmp_path):
    """O que a extensão guarda: o CRC-32 das amostras (o arquivo é o que a captura gravou?), o fim da captura, o
    identificador, a máquina, o comando, o ganho declarado e o sinal de cada canal, medido em todas as amostras."""
    import numpy as np
    from supraharmonicos.cabecalho import conferir_crc_das_amostras
    p, sinais = _captura_v9(tmp_path, extensao={"ganhos": [19.357], "comando": "400000 0,1 --ganho 0:19.357"})
    c = ler_cabecalho(p)
    assert conferir_crc_das_amostras(p, c) is True
    assert c.id_captura == "00112233445566778899aabbccddeeff" and c.hostname == "beaglebone"
    assert c.linha_de_comando == "400000 0,1 --ganho 0:19.357" and c.ganho_por_canal == (19.357, None)
    assert c.timestamp_fim_unix == 1_700_000_010 and c.duracao_monotonica_s == 10.5 and c.pior_bloco_ms == 160
    # o sinal: 3 V de pico em ±10,24 V (LSB de 312,5 µV) e 0,5 V de pico com 0,1 V de offset em ±2,56 V (78,1 µV)
    lsb = (20.48 / 65536, 5.12 / 65536)
    for i, (pico, offset) in enumerate(((3.0, 0.0), (0.5, 0.1))):
        assert (c.codigo_maximo_por_canal[i] - 32768) * lsb[i] == pytest.approx(offset + pico, abs=2 * lsb[i])
        assert (c.codigo_minimo_por_canal[i] - 32768) * lsb[i] == pytest.approx(offset - pico, abs=2 * lsb[i])
        assert (c.media_codigos_por_canal[i] - 32768) * lsb[i] == pytest.approx(offset, abs=2 * lsb[i])
        assert c.desvio_codigos_por_canal[i] * lsb[i] == pytest.approx(pico / np.sqrt(2), rel=1e-3)   # RMS de uma senoide
    assert c.amostras_saturadas_por_canal == (0, 0)
    linhas = c.descrever_sinal_por_canal()
    assert "canal 0: de -3.0000 a +3.0000 V no pino (6.0000 Vpp = 116.14 pico a pico com o ganho 19.357)" in linhas[0]
    attrs = c.para_attrs_hdf5()
    assert attrs["id_captura"] == c.id_captura and attrs["crc32_amostras"] == c.crc32_amostras


def test_v9_amostra_alterada_ou_arquivo_cortado_nao_confere_com_o_crc(tmp_path):
    from supraharmonicos.cabecalho import conferir_crc_das_amostras
    p, _ = _captura_v9(tmp_path)
    c = ler_cabecalho(p)
    bruto = bytearray(p.read_bytes())
    bruto[4096 + 2000] ^= 0x01                                  # um bit de uma amostra, no meio do arquivo
    alterado = tmp_path / "alterado.bin"
    alterado.write_bytes(bytes(bruto))
    assert ler_cabecalho(alterado).crc32_valido and conferir_crc_das_amostras(alterado, c) is False
    cortado = tmp_path / "cortado.bin"
    cortado.write_bytes(p.read_bytes()[:-100])
    assert conferir_crc_das_amostras(cortado, c) is False
    # até a v8 não há CRC das amostras: nada a conferir
    from capturas_sinteticas import escrever_bin
    v8 = escrever_bin(tmp_path / "v8b.bin", SINAL, versao=8)
    assert conferir_crc_das_amostras(v8, ler_cabecalho(v8)) is None


def test_v9_sem_o_cabecalho_final_os_campos_finais_ficam_desconhecidos(tmp_path):
    """Uma captura que não chegou ao cabeçalho final (0 blocos) tem a extensão zerada: o CRC e o sinal são
    desconhecidos (None e ()), e não um CRC 0 ou um sinal de 0 V."""
    from capturas_sinteticas import montar_cabecalho
    p = tmp_path / "sem_final.bin"
    p.write_bytes(montar_cabecalho(1000, (1,), (0,), ("",), 400_000, versao=9, blocos=0, total_amostras=0))
    c = ler_cabecalho(p)
    assert c.crc32_valido and c.crc32_amostras is None and c.amostras_saturadas_por_canal == ()
    assert c.timestamp_fim_unix is None and c.descrever_sinal_por_canal() == [] and c.id_captura


def test_v9_cabecalho_cortado_e_acusado_pelo_crc(tmp_path):
    p, _ = _captura_v9(tmp_path)
    cortado = tmp_path / "cabecalho_cortado.bin"
    cortado.write_bytes(p.read_bytes()[:3000])                  # o arquivo acaba dentro do cabeçalho
    c = ler_cabecalho(cortado)
    assert c is not None and not c.crc32_valido


def test_os_canais_saem_em_sequencia_e_o_atraso_de_cada_um_vai_para_as_exportacoes(tmp_path, caplog):
    """O ADS8688 converte um canal por quadro: com 3 canais a 250 kS/s (800 ticks de 5 ns), o da posição k é amostrado
    k × 4 µs depois do primeiro (medido no T6b: 9,954 µs contra 10,000 a 100 kS/s). Sem esse número, quem compara a
    fase de dois canais erra 360°·f·Δt (72° em 50 kHz)."""
    import numpy as np
    from capturas_sinteticas import escrever_bin
    from supraharmonicos.cabecalho import imprimir_resumo_cabecalho
    t = np.arange(3000) / 100_000.0
    p = escrever_bin(tmp_path / "tres.bin", [np.sin(2 * np.pi * 1000 * t)] * 3, canais=(0, 1, 5), grandezas=(1, 0, 0),
                     sondas=("", "", ""), fs_total=250_000, versao=9, faixas_adc_total_v=[5.12] * 3)
    c = ler_cabecalho(p)
    assert c.atraso_de_amostragem_por_canal_s == pytest.approx((0.0, 4e-6, 8e-6))
    assert c.para_attrs_hdf5()["atraso_de_amostragem_por_canal_s"] == pytest.approx([0.0, 4e-6, 8e-6])
    with caplog.at_level(logging.INFO):
        imprimir_resumo_cabecalho(c)
    texto = " ".join(r.getMessage() for r in caplog.records)
    assert "canal 1 a +4.000 µs" in texto and "canal 5 a +8.000 µs" in texto
    um = escrever_bin(tmp_path / "um.bin", [np.sin(2 * np.pi * 1000 * t)], canais=(1,), grandezas=(0,), sondas=("",),
                      fs_total=100_000, versao=9, faixas_adc_total_v=[5.12])
    assert ler_cabecalho(um).atraso_de_amostragem_por_canal_s == (0.0,)
