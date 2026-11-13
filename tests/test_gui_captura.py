"""Abrir uma captura na interface (``sh_analyzer_gui.dados.captura``): a ``api`` do motor (cuja paridade com a CLI
está em ``test_api.py``) e a chave do cache. Sem Qt."""

import numpy as np
import pytest
from capturas_sinteticas import FS_TOTAL_2CH, escrever_bin
from sh_analyzer_gui.dados.captura import ErroSHAN, abrir_fonte
from supraharmonicos.amostras import converter_para_tensao


def test_canais_como_visoes_e_a_conversao_da_cli(tmp_path):
    t = np.arange(20_000) / (FS_TOTAL_2CH / 2)
    v0, v1 = 3.0 * np.sin(2 * np.pi * 60 * t), 1.2 * np.sin(2 * np.pi * 180 * t + 1)
    caminho = escrever_bin(tmp_path / "c.bin", [v0, v1], canais=(1, 3), grandezas=(0, 1), sondas=("", ""),
                           faixas_adc_total_v=[20.48, 5.12])
    fonte = abrir_fonte(caminho, sondas_dir=tmp_path)
    assert fonte.nome == "c.bin" and [c.numero for c in fonte.canais] == [1, 3]
    assert [c.nome_grandeza for c in fonte.canais] == ["tensão", "corrente"]
    assert all(c.taxa_hz == FS_TOTAL_2CH / 2 for c in fonte.canais)
    assert len(fonte.canais[0].amostras) == 20_000 and not fonte.canais[0].amostras.flags.owndata
    for canal, faixa, original in zip(fonte.canais, (20.48, 5.12), (v0, v1)):
        codigos = np.asarray(canal.amostras)
        esperado = converter_para_tensao(codigos, faixa, 1.0, "uint16", faixa / 2)
        np.testing.assert_allclose(codigos * canal.escala + canal.deslocamento, esperado, atol=1e-12)
        np.testing.assert_allclose(esperado, original, atol=faixa / 65536)
    assert fonte.chave.startswith("arq")                # v3: sem o CRC das amostras, a chave vem do arquivo


def test_v9_usa_o_crc_das_amostras_na_chave(tmp_path):
    caminho = escrever_bin(tmp_path / "c.bin", [np.zeros(4096), np.zeros(4096)], versao=9)
    assert abrir_fonte(caminho).chave.startswith("crc")


def test_erros_do_motor_sobem_como_erro_shan(tmp_path):
    sem = escrever_bin(tmp_path / "legado.bin", [np.zeros(100), np.zeros(100)], com_cabecalho=False)
    with pytest.raises(ErroSHAN, match="sem o cabeçalho"):
        abrir_fonte(sem)
    with pytest.raises(ErroSHAN):
        abrir_fonte(sem, formato="float32")
