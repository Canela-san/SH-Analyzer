"""Cabeçalho "SHAN": v1, v2, CRC, magic e conferência de consistência."""

import logging

import numpy as np
import pytest
from capturas_sinteticas import escrever_bin
from supraharmonicos.cabecalho import (
    CABECALHO_TAMANHO_TOTAL,
    conferir_consistencia_cabecalho,
    contar_amostras_arquivo_bin,
    ler_cabecalho,
)
from supraharmonicos.constantes import GRANDEZA_CORRENTE, GRANDEZA_TENSAO

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
        from supraharmonicos.cabecalho import imprimir_resumo_cabecalho

        c = ler_cabecalho(p)
        imprimir_resumo_cabecalho(c)
    assert c is not None and not c.crc32_valido
    assert any("CRC-32 do cabeçalho NÃO confere" in r.getMessage() and r.levelno == logging.WARNING
               for r in caplog.records)


def test_arquivo_menor_que_o_cabecalho_nao_quebra(tmp_path):
    p = tmp_path / "curto.bin"
    p.write_bytes(b"SHAN" + b"\x00" * 10)
    assert ler_cabecalho(p) is None or not ler_cabecalho(p).crc32_valido


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
