"""Conversão .bin <-> .csv e exportação HDF5 (sempre em blocos)."""

import h5py
import numpy as np
import pytest
from capturas_sinteticas import FAIXA, escrever_bin
from supraharmonicos.cabecalho import CABECALHO_TAMANHO_TOTAL, ler_cabecalho
from supraharmonicos.conversao import converter_arquivo
from supraharmonicos.erros import ErroSHAN
from supraharmonicos.hdf5 import exportar_hdf5

T = np.arange(5000) / 200_000.0
SINAL = [3.0 * np.sin(2 * np.pi * 1000 * T), 1.5 * np.sin(2 * np.pi * 2000 * T)]
PAR = dict(canais=[0, 1], faixas=[FAIXA, FAIXA], ganhos=[1.0, 10.0], offsets=[FAIXA / 2, FAIXA / 2])


def bin_de_teste(tmp_path):
    return escrever_bin(tmp_path / "c.bin", SINAL)


def test_bin_csv_bin_preserva_os_codigos_brutos(tmp_path):
    original = bin_de_teste(tmp_path)
    csv = tmp_path / "c.csv"
    converter_arquivo(original, csv, "uint16", 0, None, False, **PAR, tamanho_chunk=777, offset_amostras=CABECALHO_TAMANHO_TOTAL)
    volta = tmp_path / "volta.bin"
    converter_arquivo(csv, volta, "uint16", 0, None, False, **PAR, tamanho_chunk=1234)
    esperado = np.fromfile(original, dtype="<u2", offset=CABECALHO_TAMANHO_TOTAL)
    np.testing.assert_array_equal(np.fromfile(volta, dtype="<u2"), esperado)


def test_csv_com_tensao_tem_a_coluna_convertida(tmp_path):
    csv = tmp_path / "c.csv"
    converter_arquivo(bin_de_teste(tmp_path), csv, "uint16", 0, 10, True, **PAR, tamanho_chunk=4,
                      offset_amostras=CABECALHO_TAMANHO_TOTAL)
    linhas = csv.read_text(encoding="utf-8").splitlines()
    assert "tensao_v" in linhas[0] and len(linhas) == 11


def test_extensao_desconhecida_e_erro_de_dominio(tmp_path):
    with pytest.raises(ErroSHAN, match="extensão '.txt' não reconhecida"):
        converter_arquivo(bin_de_teste(tmp_path), tmp_path / "x.txt", "uint16", 0, None, False, **PAR, tamanho_chunk=100)


def test_exportacao_hdf5_grava_metadados_e_dados(tmp_path):
    p = bin_de_teste(tmp_path)
    cab = ler_cabecalho(p)
    destino = tmp_path / "c.h5"
    n_linhas, n_canais = exportar_hdf5(p, destino, "uint16", [0, 1], cab, PAR["faixas"], PAR["ganhos"], PAR["offsets"],
                                       True, CABECALHO_TAMANHO_TOTAL, 0, None, tamanho_chunk=999,
                                       grandeza_por_canal=[0, 1], sonda_id_por_canal=["", "sonda_x"])
    assert (n_linhas, n_canais) == (5000, 2)
    with h5py.File(destino, "r") as f:
        bruto = f["amostras"][()]
        assert bruto.shape == (5000, 2)
        np.testing.assert_array_equal(bruto.ravel(), np.fromfile(p, dtype="<u2", offset=CABECALHO_TAMANHO_TOTAL))
        # tensao_v = (codigo/65536*faixa - offset) * ganho, por canal
        esperado = (bruto / 65536.0 * FAIXA - FAIXA / 2) * np.array([1.0, 10.0])
        np.testing.assert_allclose(f["tensao_v"][()], esperado, atol=1e-4)
        assert f.attrs["cabecalho_versao"] == 2 and f.attrs["frequencia_hz"] == 400_000
        assert list(f.attrs["canais_ordem"]) == [0, 1]
        assert list(f.attrs["grandeza_por_canal"]) == [0, 1]
        assert [s.decode() for s in f.attrs["sonda_id_por_canal"]] == ["", "sonda_x"]


def test_exportacao_hdf5_com_inicio_no_meio_do_ciclo_nao_troca_os_canais(tmp_path):
    p = escrever_bin(tmp_path / "dc.bin", [np.full(1000, 1.0), np.full(1000, -2.0)])   # canal 0 = +1 V, canal 1 = -2 V
    destino = tmp_path / "dc.h5"
    exportar_hdf5(p, destino, "uint16", [0, 1], ler_cabecalho(p), **{k: PAR[k] for k in ("faixas", "offsets")},
                  ganhos=[1.0, 1.0], incluir_tensao=True, offset_amostras=CABECALHO_TAMANHO_TOTAL, inicio=1, fim=None)
    with h5py.File(destino, "r") as f:
        tensao = f["tensao_v"][()]
    np.testing.assert_allclose(tensao[:, 0], 1.0, atol=1e-3)    # sem o alinhamento, a coluna 0 seria o canal 1
    np.testing.assert_allclose(tensao[:, 1], -2.0, atol=1e-3)


@pytest.mark.parametrize("valor", ["abc", "70000", "-1"])
def test_csv_com_valor_invalido_e_erro_claro_e_nao_deixa_bin_pela_metade(tmp_path, valor):
    csv = tmp_path / "x.csv"
    csv.write_text("amostra,valor_bruto\n0,100\n1,200\n2," + valor + "\n", encoding="utf-8")
    destino = tmp_path / "x.bin"
    with pytest.raises(ErroSHAN, match="linha de dados 3"):
        converter_arquivo(csv, destino, "uint16", 0, None, False, **PAR, tamanho_chunk=100)
    assert not destino.exists()
