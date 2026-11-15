"""As capturas que não são o ``.bin`` com o cabeçalho, pela ``api`` (PD-02): o ``.bin`` legado e o ``.csv`` do
``adc_tool -c`` pedem a taxa e os canais (:class:`api.CapturaSemCabecalho`), o ``.h5`` do ``--export-hdf5`` abre com o
cabeçalho do ``.bin`` de origem. Em todos, os volts são os da CLI, bit a bit. Sem Qt."""

import json

import h5py
import numpy as np
import pytest
from capturas_sinteticas import FS_TOTAL_2CH, escrever_bin
from supraharmonicos import api
from supraharmonicos.cli_adc_tool import main, montar_parser
from supraharmonicos.contexto import resolver_contexto
from supraharmonicos.erros import ErroSHAN
from supraharmonicos.modos import _carregar_sinal

N = 6000


def volts_da_cli(*argv) -> dict[int, np.ndarray]:
    """Os volts de cada canal pelo caminho da plotagem do ``adc_tool`` (``_carregar_sinal``)."""
    args = montar_parser().parse_args([str(a) for a in argv])
    return _carregar_sinal(args, resolver_contexto(args)).por_canal_tensao


@pytest.fixture
def sinais():
    t = np.arange(N) / (FS_TOTAL_2CH / 2)
    return [0.8 * np.sin(2 * np.pi * 60 * t), 0.3 * np.cos(2 * np.pi * 180 * t) - 0.1]


def test_os_parametros_sao_validados_com_as_mensagens_da_cli():
    p = api.ParametrosSemCabecalho.de_texto(400_000, " 3, 1")
    assert p.taxa_total_hz == 400_000.0 and isinstance(p.taxa_total_hz, float) and p.canais == (3, 1)
    assert p.texto_dos_canais == "3,1" and p == api.ParametrosSemCabecalho(4e5, [3, 1])
    for taxa in (0, -1.0, float("nan"), float("inf"), True, "400k"):
        with pytest.raises(ErroSHAN, match="taxa total"):
            api.ParametrosSemCabecalho(taxa, (0,))
    with pytest.raises(ErroSHAN, match="repetido"):
        api.ParametrosSemCabecalho.de_texto(1e5, "0,0")
    with pytest.raises(ErroSHAN, match="só tem canais 0-7"):
        api.ParametrosSemCabecalho(1e5, (8,))
    with pytest.raises(ErroSHAN, match="vazia"):
        api.ParametrosSemCabecalho.de_texto(1e5, " ")


def test_o_bin_legado_pede_a_taxa_e_os_canais_e_abre_com_os_volts_da_cli(tmp_path, sinais):
    legado = escrever_bin(tmp_path / "legado.bin", sinais, com_cabecalho=False)
    with pytest.raises(api.CapturaSemCabecalho) as pedido:
        api.abrir_captura(legado)
    assert pedido.value.tipo == "bin" and pedido.value.canais is None and pedido.value.n_amostras == 2 * N
    parametros = api.ParametrosSemCabecalho.de_texto(FS_TOTAL_2CH, "2,5")
    cap = api.abrir_captura(legado, parametros=parametros)
    assert cap.tipo == "bin" and cap.cabecalho is None and cap.parametros == parametros
    assert cap.crc32_amostras is None and isinstance(cap.amostras, np.memmap)
    assert [c.numero for c in cap.canais] == [2, 5] and all(c.taxa_hz == FS_TOTAL_2CH / 2 for c in cap.canais)
    assert all(c.unidade == "V" and not c.faixa_confiavel for c in cap.canais)
    assert any("não registra a faixa" in a.texto for a in cap.avisos)              # o aviso da CLI, como dado
    cli = volts_da_cli(legado, "-f", FS_TOTAL_2CH, "--canais", "2,5")
    for canal in (2, 5):
        np.testing.assert_array_equal(api.sinal_do_canal(cap, canal), cli[canal])
    assert api.conferir_integridade(cap) is None
    secoes = dict(api.descrever_cabecalho(cap))
    assert dict(secoes["Captura"])["Cabeçalho"].startswith("nenhum") and "Integridade" not in secoes
    assert dict(secoes["Captura"])["Taxa total"] == f"{FS_TOTAL_2CH:g} Hz"
    dados = api.cabecalho_em_dict(cap)
    assert json.loads(json.dumps(dados, allow_nan=False)) == {
        "arquivo": "legado.bin", "tipo": "bin", "formato_amostras": "uint16",
        "parametros": {"taxa_total_hz": float(FS_TOTAL_2CH), "canais": [2, 5]}}
    # Um .bin com o cabeçalho não aceita a taxa e os canais de fora: nunca dois valores para a mesma coisa.
    com_cabecalho = escrever_bin(tmp_path / "novo.bin", sinais, versao=9)
    with pytest.raises(ErroSHAN, match="tem o cabeçalho do SH-Analyzer"):
        api.abrir_captura(com_cabecalho, parametros=parametros)
    # O CRC das amostras, só pelo cabeçalho: o do .bin v9; nenhum sem ele.
    assert api.crc32_das_amostras(com_cabecalho) == api.abrir_captura(com_cabecalho).crc32_amostras is not None
    assert api.crc32_das_amostras(legado) is None and api.crc32_das_amostras(tmp_path / "x.csv") is None


def test_o_csv_do_adc_tool_diz_os_canais_e_pede_so_a_taxa(tmp_path, cli, sinais):
    origem = escrever_bin(tmp_path / "a.bin", sinais, canais=(1, 3), grandezas=(0, 0))
    csv = tmp_path / "a.csv"
    rc, _, err = cli(main, "-c", origem, "-o", csv)
    assert rc == 0, err
    with pytest.raises(api.CapturaSemCabecalho) as pedido:
        api.abrir_captura(csv)
    assert pedido.value.tipo == "csv" and pedido.value.canais == (1, 3) and pedido.value.n_amostras == 2 * N
    cap = api.abrir_captura(csv, parametros=api.ParametrosSemCabecalho(FS_TOTAL_2CH, (1, 3)))
    assert cap.tipo == "csv" and cap.cabecalho is None and [c.numero for c in cap.canais] == [1, 3]
    da_cli_no_csv = volts_da_cli(csv, "-f", FS_TOTAL_2CH, "--canais", "1,3")
    da_cli_no_bin = volts_da_cli(origem)
    for canal in (1, 3):
        np.testing.assert_array_equal(api.sinal_do_canal(cap, canal), da_cli_no_csv[canal])
        np.testing.assert_array_equal(api.sinal_do_canal(cap, canal), da_cli_no_bin[canal])
    assert dict(dict(api.descrever_cabecalho(cap))["Captura"])["Tipo"] == ".csv do adc_tool"
    with pytest.raises(ErroSHAN, match="a coluna 'canal' diz os canais 1, 3, não 3, 1"):
        api.abrir_captura(csv, parametros=api.ParametrosSemCabecalho(FS_TOTAL_2CH, (3, 1)))

    # Convertido com --inicio no meio de um ciclo: o índice das amostras alinha, e cada canal fica com as dele (a CLI
    # leria as linhas pela ordem e trocaria os canais).
    cortado = tmp_path / "cortado.csv"
    rc, _, err = cli(main, "-c", origem, "-o", cortado, "--inicio", "1")
    assert rc == 0, err
    with pytest.raises(api.CapturaSemCabecalho) as pedido:
        api.abrir_captura(cortado)
    assert pedido.value.canais == (1, 3) and pedido.value.n_amostras == 2 * N - 1
    cap = api.abrir_captura(cortado, parametros=api.ParametrosSemCabecalho(FS_TOTAL_2CH, (1, 3)))
    for canal in (1, 3):
        np.testing.assert_array_equal(api.sinal_do_canal(cap, canal), da_cli_no_bin[canal][1:])


@pytest.mark.parametrize("conteudo, trecho", [
    ("amostra,canal,valor_bruto\n0,1,100\n1,3,200\n2,3,300\n3,1,400\n", "não segue um ciclo dos canais 1, 3"),
    ("amostra,valor_bruto\n0,70000\n", "fora do que o formato uint16 guarda"),
    ("amostra,valor_bruto\n0,abc\n", "could not convert"),
    ("amostra,valor_bruto\n", "não tem linhas de dados"),
])
def test_um_csv_mexido_e_recusado_com_o_motivo(tmp_path, conteudo, trecho):
    caminho = tmp_path / "x.csv"
    caminho.write_text(conteudo)
    with pytest.raises(ErroSHAN, match=trecho):
        api.abrir_captura(caminho, parametros=api.ParametrosSemCabecalho(1e5, (1, 3)))


def test_o_csv_de_um_canal_pede_os_canais_tambem(tmp_path):
    caminho = tmp_path / "um.csv"
    caminho.write_text("amostra,valor_bruto\n" + "".join(f"{i},{32768 + i}\n" for i in range(10)))
    with pytest.raises(api.CapturaSemCabecalho) as pedido:
        api.abrir_captura(caminho)
    assert pedido.value.canais is None and pedido.value.n_amostras == 10
    cap = api.abrir_captura(caminho, parametros=api.ParametrosSemCabecalho(1e5, (4,)))
    assert [c.numero for c in cap.canais] == [4] and len(cap.canal(4).amostras) == 10


def test_o_h5_do_adc_tool_abre_com_o_cabecalho_de_origem_e_os_volts_da_cli(tmp_path, cli, sinais):
    origem = escrever_bin(tmp_path / "a.bin", sinais, canais=(1, 3), grandezas=(0, 1), versao=9,
                          extensao={"ganhos": [10.0, 20.0]})
    h5 = tmp_path / "a.h5"
    rc, _, err = cli(main, origem, "--export-hdf5", h5, "--incluir-tensao")
    assert rc == 0, err
    do_bin = api.abrir_captura(origem)
    cap = api.abrir_captura(h5)
    assert cap.tipo == "h5" and cap.cabecalho.versao_cabecalho == 9 and cap.formato == "uint16"
    assert cap.hdf5 == api.OrigemDoHdf5("a.bin", (0, 2 * N), cap.hdf5.versao_codigo)
    assert cap.crc32_amostras is None and do_bin.crc32_amostras is not None   # a chave do cache não é a do .bin
    for a, b in zip(cap.canais, do_bin.canais, strict=True):
        assert (a.numero, a.taxa_hz, a.faixa_v, a.ganho, a.offset_v, a.grandeza, a.unidade, a.faixa_confiavel) == \
               (b.numero, b.taxa_hz, b.faixa_v, b.ganho, b.offset_v, b.grandeza, b.unidade, b.faixa_confiavel)
    assert [c.unidade for c in cap.canais] == ["V", "A"]
    da_cli = volts_da_cli(origem)
    with h5py.File(h5, "r") as f5:
        tensao = f5["tensao_v"][()]
    for i, canal in enumerate((1, 3)):
        np.testing.assert_array_equal(api.sinal_do_canal(cap, canal), da_cli[canal])
        np.testing.assert_allclose(api.sinal_do_canal(cap, canal), tensao[:, i], rtol=1e-6, atol=1e-6)
    assert api.conferir_integridade(cap) is True                       # a captura inteira: o CRC do .bin confere
    secoes = dict(api.descrever_cabecalho(cap))
    assert dict(secoes["Captura"])["Cabeçalho"] == "v9 (do .bin de origem)"
    assert dict(secoes["Captura"])["Exportado de"] == "a.bin" and "Integridade" in secoes
    dados = api.cabecalho_em_dict(cap)
    assert dados["tipo"] == "h5" and dados["hdf5"]["trecho"] == [0, 2 * N] and dados["versao_cabecalho"] == 9
    json.dumps(dados, allow_nan=False)
    with pytest.raises(ErroSHAN, match="são uint16, não int16"):
        api.abrir_captura(h5, formato="int16")
    with pytest.raises(ErroSHAN, match="tem o cabeçalho do SH-Analyzer"):
        api.abrir_captura(h5, parametros=api.ParametrosSemCabecalho(FS_TOTAL_2CH, (1, 3)))

    # Uma amostra mexida: o CRC não confere mais.
    with h5py.File(h5, "r+") as f5:
        f5["amostras"][10, 0] ^= 1
    assert api.conferir_integridade(api.abrir_captura(h5)) is False


def test_o_h5_de_um_trecho_com_outro_ganho_tem_os_volts_da_cli_com_as_mesmas_flags(tmp_path, cli, sinais):
    origem = escrever_bin(tmp_path / "a.bin", sinais, grandezas=(0, 1), versao=9)
    h5 = tmp_path / "trecho.h5"
    rc, _, err = cli(main, origem, "--export-hdf5", h5, "--inicio", "200", "--fim", "2200", "--ganho", "2,4")
    assert rc == 0, err
    cap = api.abrir_captura(h5)
    assert cap.hdf5.trecho == (200, 2200) and [c.ganho for c in cap.canais] == [2.0, 4.0]
    assert [c.unidade for c in cap.canais] == ["V", "A"]                  # com --ganho, a unidade da grandeza
    da_cli = volts_da_cli(origem, "--ganho", "2,4")
    for canal in (0, 1):
        np.testing.assert_array_equal(api.sinal_do_canal(cap, canal), da_cli[canal][100:1100])
    assert api.conferir_integridade(cap) is None                         # só um trecho: não há o que conferir


def test_o_h5_de_um_legado_pede_so_a_taxa(tmp_path, cli, sinais):
    legado = escrever_bin(tmp_path / "legado.bin", sinais, com_cabecalho=False)
    h5 = tmp_path / "legado.h5"
    rc, _, err = cli(main, legado, "--export-hdf5", h5, "-f", FS_TOTAL_2CH, "--canais", "2,5")
    assert rc == 0, err
    with pytest.raises(api.CapturaSemCabecalho) as pedido:
        api.abrir_captura(h5)
    assert pedido.value.tipo == "h5" and pedido.value.canais == (2, 5) and pedido.value.n_amostras == 2 * N
    cap = api.abrir_captura(h5, parametros=api.ParametrosSemCabecalho(FS_TOTAL_2CH, (2, 5)))
    da_cli = volts_da_cli(legado, "-f", FS_TOTAL_2CH, "--canais", "2,5")
    for canal in (2, 5):
        np.testing.assert_array_equal(api.sinal_do_canal(cap, canal), da_cli[canal])
    with pytest.raises(ErroSHAN, match="o .h5 diz os canais 2, 5, não 5, 2"):
        api.abrir_captura(h5, parametros=api.ParametrosSemCabecalho(FS_TOTAL_2CH, (5, 2)))


def test_um_h5_que_nao_e_do_adc_tool(tmp_path):
    estranho = tmp_path / "estranho.h5"
    with h5py.File(estranho, "w") as f5:
        f5["dados"] = np.zeros(3)
    with pytest.raises(ErroSHAN, match="não é um .h5 do adc_tool --export-hdf5 \\(falta: /amostras, canais_ordem"):
        api.abrir_captura(estranho)
    (tmp_path / "texto.h5").write_text("não sou HDF5")
    with pytest.raises(ErroSHAN, match="não é um HDF5 legível"):
        api.abrir_captura(tmp_path / "texto.h5")
