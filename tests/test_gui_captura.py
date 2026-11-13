"""Abrir um .bin para a interface (``sh_analyzer_gui.dados.captura``): os canais como visões do memmap, a taxa por
canal e a conversão para volts igual à da CLI. Sem Qt."""

import numpy as np
import pytest
from capturas_sinteticas import FS_TOTAL_2CH, escrever_bin
from sh_analyzer_gui.dados.captura import CapturaInvalida, abrir_bin
from supraharmonicos.amostras import converter_para_tensao


def test_canais_taxa_e_volts_iguais_aos_da_cli(tmp_path):
    t = np.arange(20_000) / (FS_TOTAL_2CH / 2)
    v0, v1 = 3.0 * np.sin(2 * np.pi * 60 * t), 1.2 * np.sin(2 * np.pi * 180 * t + 1)
    caminho = escrever_bin(tmp_path / "c.bin", [v0, v1], canais=(1, 3), grandezas=(0, 1), sondas=("cadeia", "sct"),
                           faixas_adc_total_v=[20.48, 5.12])
    cap = abrir_bin(caminho)
    assert [c.numero for c in cap.canais] == [1, 3] and [c.posicao for c in cap.canais] == [0, 1]
    assert [c.grandeza for c in cap.canais] == ["tensão", "corrente"] and [c.sonda for c in cap.canais] == ["cadeia", "sct"]
    assert all(c.taxa_hz == FS_TOTAL_2CH / 2 for c in cap.canais)
    assert len(cap.canais[0].amostras) == 20_000 and not cap.canais[0].amostras.flags.owndata   # visão, sem cópia
    for canal, faixa, original in zip(cap.canais, (20.48, 5.12), (v0, v1)):
        codigos = np.asarray(canal.amostras)
        esperado = converter_para_tensao(codigos, faixa, 1.0, "uint16", faixa / 2)
        np.testing.assert_allclose(codigos * canal.escala + canal.deslocamento, esperado)
        np.testing.assert_allclose(esperado, original, atol=faixa / 65536)
    assert cap.chave.startswith("arq")                  # v3: sem o CRC das amostras, a chave vem do arquivo


def test_v9_usa_o_crc_das_amostras_na_chave(tmp_path):
    caminho = escrever_bin(tmp_path / "c.bin", [np.zeros(4096), np.zeros(4096)], versao=9)
    assert abrir_bin(caminho).chave.startswith("crc")


def test_arquivo_sem_cabecalho_ou_sem_amostras(tmp_path):
    sem = escrever_bin(tmp_path / "legado.bin", [np.zeros(100), np.zeros(100)], com_cabecalho=False)
    with pytest.raises(CapturaInvalida):
        abrir_bin(sem)
    vazio = escrever_bin(tmp_path / "vazio.bin", [np.zeros(0), np.zeros(0)])
    with pytest.raises(CapturaInvalida):
        abrir_bin(vazio)
    with pytest.raises(ValueError):
        abrir_bin(sem, formato="float32")
