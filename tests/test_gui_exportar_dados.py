"""A exportação dos dados (``sh_analyzer_gui.dados.exportar_dados``, F5.5), sem Qt: o trecho (a janela de cada
traço, a captura inteira, as recusas), os quatro formatos lidos de volta iguais aos valores da tela (o CSV com 15
algarismos), os crus com a escala, o MAT v5 (lido pelo SciPy) e o v7.3 (o HDF5 com o cabeçalho do MATLAB), a memória
que não cresce com o trecho, o progresso, o cancelar sem arquivo pela metade e o ``proveniencia.json`` com os
comandos da CLI."""

import json
import tracemalloc
import zipfile

import h5py
import numpy as np
import pytest
import scipy.io
from capturas_sinteticas import escrever_bin
from sh_analyzer_gui.dados import exportar_dados as ed
from sh_analyzer_gui.dados import proveniencia as prov
from sh_analyzer_gui.dados.exportar_dados import ColunaDeDados, DadosInvalidos, OpcoesDosDados
from supraharmonicos import api
from supraharmonicos.api import Cancelado

N = 50_000


@pytest.fixture(scope="module")
def captura(tmp_path_factory):
    t = np.arange(N) / 200_000
    caminho = escrever_bin(tmp_path_factory.mktemp("captura") / "rede.bin",
                           [3.0 * np.sin(2 * np.pi * 60 * t), 1.0 * np.cos(2 * np.pi * 60 * t)], canais=(1, 3),
                           versao=9)
    return api.abrir_captura(caminho)


def _colunas(captura, transformada: bool = False):
    v, i = captura.canais
    colunas = [ColunaDeDados("V_A", v.amostras, v.taxa_hz, 0.0, v.escala * -1.5, v.deslocamento * -1.5 + 0.25, "V",
                             "tensão", fonte="f1", receita={"canal": 1, "ganho": -1.5, "offset": 0.25}),
               ColunaDeDados("I_A", i.amostras, i.taxa_hz, 0.001, i.escala, i.deslocamento, "A", "corrente",
                             fonte="f1", receita={"canal": 3})]
    if transformada:
        filtrado = np.convolve(v.amostras.astype(np.float64) * v.escala, np.ones(5) / 5, mode="same")
        colunas.append(ColunaDeDados("V_A filtrada", filtrado, v.taxa_hz, 0.0, 1.0, 0.0, "V", "tensão", codigos=False,
                                     fonte="f1", receita={"canal": 1, "etapas": [{"tipo": "media", "n": 5}]}))
    return colunas


def _esperado(trecho):
    return np.column_stack([np.asarray(c.amostras[i:i + trecho.n], np.float64) * c.escala + c.deslocamento
                            for c, i in zip(trecho.colunas, trecho.inicios, strict=True)])


def _fontes(captura):
    return {"f1": prov.FonteDaProveniencia("f1", "rede.bin", str(captura.caminho), 1234,
                                           captura.cabecalho.crc32_amostras, api.cabecalho_em_dict(captura))}


def _exportar(tmp_path, trecho, opcoes, origem, **kw):
    p = prov.dos_dados(trecho, opcoes, _fontes(origem), aplicativo="0.8.0", regiao="janela")
    destino = tmp_path / f"dados{ed.FORMATOS[opcoes.formato].extensao}"
    saida = ed.exportar(trecho, destino, opcoes, proveniencia=p, **kw)
    assert saida == [destino, ed.caminho_da_proveniencia(destino)] and not list(tmp_path.glob("*.parcial"))
    return destino


# ------------------------------------------------------------------ o trecho

def test_o_trecho_de_cada_traco_e_as_recusas(captura):
    colunas = _colunas(captura)
    taxa = colunas[0].taxa_hz
    trecho = ed.recortar(colunas, [(0.01, 0.02), (0.01, 0.02)])
    # V_A: das amostras de 0,01 s a 0,02 s (as das pontas incluídas); I_A anda 1 ms: as dele começam 1 ms antes.
    assert trecho.inicios == (round(0.01 * taxa), round(0.009 * taxa)) and trecho.n == round(0.01 * taxa) + 1
    assert trecho.t0_por_coluna == pytest.approx([0.01, 0.01])
    inteira = ed.recortar(colunas)
    assert (inteira.inicios, inteira.n) == ((0, 0), N)
    with pytest.raises(DadosInvalidos, match="taxas diferentes"):
        ed.recortar([colunas[0], ColunaDeDados("x", np.zeros(10), 1000.0)])
    with pytest.raises(DadosInvalidos, match="nenhuma amostra"):
        ed.recortar(colunas, [(9.0, 10.0), (9.0, 10.0)])
    with pytest.raises(DadosInvalidos, match="nenhum traço"):
        ed.recortar([])
    with pytest.raises(DadosInvalidos, match="tem transformações"):
        ed.conferir(ed.recortar(_colunas(captura, True)), OpcoesDosDados("hdf5", crus=True))
    with pytest.raises(DadosInvalidos, match="o mesmo"):
        OpcoesDosDados("csv", separador=",", decimal=",")


# ------------------------------------------------------------------ os formatos, lidos de volta

def _ler_csv(caminho, separador=";", decimal=","):
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    comentarios = [x for x in linhas if x.startswith("#")]
    cabecalho, *dados = [x for x in linhas if not x.startswith("#")]
    tabela = np.array([[float(v.replace(decimal, ".")) for v in x.split(separador)] for x in dados])
    return comentarios, cabecalho.split(separador), tabela


@pytest.mark.parametrize(("separador", "decimal"), [(";", ","), (",", "."), ("\t", ",")])
def test_o_csv(tmp_path, captura, separador, decimal):
    trecho = ed.recortar(_colunas(captura, True), [(0.01, 0.03)] * 3)
    destino = _exportar(tmp_path, trecho, OpcoesDosDados("csv", separador=separador, decimal=decimal), captura,
                        linhas_por_bloco=1000)
    comentarios, cabecalho, tabela = _ler_csv(destino, separador, decimal)
    assert cabecalho == ["tempo_s", "V_A (V)", "I_A (A)", "V_A filtrada (V)"]
    assert tabela[:, 0] == pytest.approx(0.01 + np.arange(trecho.n) / trecho.taxa_hz, rel=1e-14, abs=1e-15)
    np.testing.assert_allclose(tabela[:, 1:], _esperado(trecho), rtol=1e-14, atol=1e-15)
    assert any("transformações" in c for c in comentarios) and comentarios[-1] == "# proveniência: dados.proveniencia.json"


def test_o_csv_crus(tmp_path, captura):
    trecho = ed.recortar(_colunas(captura), [(0.0, 0.005)] * 2)
    comentarios, cabecalho, tabela = _ler_csv(_exportar(tmp_path, trecho, OpcoesDosDados("csv", crus=True), captura))
    assert cabecalho == ["tempo_s", "V_A", "I_A"]
    np.testing.assert_array_equal(tabela[:, 1:], trecho.bloco(0, trecho.n, crus=True))
    assert any(c.startswith("# V_A: valor = código × ") for c in comentarios)


def test_o_hdf5(tmp_path, captura):
    trecho = ed.recortar(_colunas(captura, True), [(0.0, 0.1)] * 3)
    atributos, bruto = api.cabecalho_para_hdf5(captura)
    destino = _exportar(tmp_path, trecho, OpcoesDosDados("hdf5"), captura, linhas_por_bloco=7_000,
                        captura=(atributos, bruto))
    with h5py.File(destino) as f5:
        np.testing.assert_array_equal(f5["valores"][:], _esperado(trecho))
        assert list(f5.attrs["nomes"]) == ["V_A", "I_A", "V_A filtrada"] and f5.attrs["taxa_hz"] == trecho.taxa_hz
        assert f5["captura"].attrs["cabecalho_versao"] == 9 and bytes(f5["captura/cabecalho_bruto"][:]) == bruto
        assert f5["captura"].attrs["arquivo_origem"] == "rede.bin"
        assert json.loads(f5.attrs["transformacoes_por_coluna"])[2] == [{"tipo": "media", "n": 5}]
        assert json.loads(f5.attrs["proveniencia"])["dados"]["linhas"] == trecho.n


def test_o_hdf5_crus_no_tipo_da_captura(tmp_path, captura):
    trecho = ed.recortar(_colunas(captura))
    with h5py.File(_exportar(tmp_path, trecho, OpcoesDosDados("hdf5", crus=True), captura)) as f5:
        codigos = f5["amostras"][:]
        assert codigos.dtype == captura.canais[0].amostras.dtype
        np.testing.assert_array_equal(codigos * f5.attrs["escala_por_coluna"] + f5.attrs["deslocamento_por_coluna"],
                                      _esperado(trecho))


def test_o_npz(tmp_path, captura):
    trecho = ed.recortar(_colunas(captura, True), [(0.05, 0.2)] * 3)
    with np.load(_exportar(tmp_path, trecho, OpcoesDosDados("npz"), captura, linhas_por_bloco=3_333)) as z:
        np.testing.assert_array_equal(z["valores"], _esperado(trecho))
        assert list(z["nomes"]) == ["V_A", "I_A", "V_A filtrada"] and float(z["t0_s"]) == pytest.approx(0.05)
        assert json.loads(str(z["proveniencia"]))["colunas"][0]["receita"]["ganho"] == -1.5


def test_o_mat_v5_lido_pelo_scipy(tmp_path, captura):
    trecho = ed.recortar(_colunas(captura, True), [(0.0, 0.2)] * 3)
    m = scipy.io.loadmat(_exportar(tmp_path, trecho, OpcoesDosDados("mat"), captura, linhas_por_bloco=5_000))
    np.testing.assert_array_equal(m["valores"], _esperado(trecho))
    assert [x.rstrip() for x in m["nomes"]] == ["V_A", "I_A", "V_A filtrada"]
    assert m["taxa_hz"][0, 0] == trecho.taxa_hz and m["linhas"][0, 0] == trecho.n
    assert json.loads(str(m["proveniencia"][0]))["aplicativo"]["versao"] == "0.8.0"


def test_o_mat_crus_lido_pelo_scipy(tmp_path, captura):
    trecho = ed.recortar(_colunas(captura))
    m = scipy.io.loadmat(_exportar(tmp_path, trecho, OpcoesDosDados("mat", crus=True), captura))
    assert m["amostras"].dtype == captura.canais[0].amostras.dtype
    np.testing.assert_array_equal(m["amostras"] * m["escala_por_coluna"] + m["deslocamento_por_coluna"],
                                  _esperado(trecho))


def test_o_mat_v73_acima_do_limite(tmp_path, captura, monkeypatch):
    """Acima de 2 GB por variável, o v7.3: o HDF5 com os 512 bytes do cabeçalho do MATLAB e cada variável
    transposta, com a ``MATLAB_class``."""
    monkeypatch.setattr(ed, "LIMITE_DO_MAT_V5", 1000)
    trecho = ed.recortar(_colunas(captura, True), [(0.0, 0.2)] * 3)
    destino = _exportar(tmp_path, trecho, OpcoesDosDados("mat"), captura, linhas_por_bloco=6_000)
    cabecalho = destino.read_bytes()[:128]
    assert cabecalho.startswith(b"MATLAB 7.3 MAT-file") and b"HDF5 schema 1.00" in cabecalho
    assert cabecalho[124:128] == b"\x00\x02IM"
    with h5py.File(destino) as f5:
        assert f5.userblock_size == 512
        valores = f5["valores"]
        assert valores.attrs["MATLAB_class"] == b"double" and valores.shape == (3, trecho.n)
        np.testing.assert_array_equal(valores[:].T, _esperado(trecho))
        nomes = f5["nomes"]
        assert nomes.attrs["MATLAB_class"] == b"char" and nomes.attrs["MATLAB_int_decode"] == 2
        assert ["".join(map(chr, linha)).rstrip() for linha in nomes[:].T] == ["V_A", "I_A", "V_A filtrada"]


# ------------------------------------------------------------------ a memória, o progresso, o cancelar

@pytest.mark.parametrize("formato", ["hdf5", "npz", "mat", "csv"])
def test_a_memoria_nao_cresce_com_o_trecho(tmp_path, formato):
    """4 M linhas de duas colunas (64 MB em float64), em blocos de 64 k: o pico fica no tamanho dos blocos (o CSV,
    que o tracemalloc deixa lento, com 40 k linhas em blocos de 1 k)."""
    n, bloco = (4_000_000, 65_536) if formato != "csv" else (40_000, 1_024)
    codigos = np.memmap(tmp_path / "codigos.bin", dtype=np.int16, mode="w+", shape=(n, 2))
    codigos[:] = (np.arange(n * 2) % 30_000).reshape(n, 2)
    colunas = [ColunaDeDados(f"c{k}", codigos[:, k], 400_000.0, escala=1e-3) for k in range(2)]
    trecho = ed.recortar(colunas)
    tracemalloc.start()
    try:
        destino = tmp_path / f"d{ed.FORMATOS[formato].extensao}"
        ed.exportar(trecho, destino, OpcoesDosDados(formato), proveniencia={}, linhas_por_bloco=bloco)
        _, pico = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    limite = 0.25 * n * 2 * 8 if formato != "csv" else 0.5 * destino.stat().st_size    # o texto não se acumula
    assert pico < limite, f"pico de {pico / 1e6:.2f} MB"


def test_o_progresso_e_o_cancelar(tmp_path, captura):
    trecho = ed.recortar(_colunas(captura))
    fracoes = []
    _exportar(tmp_path, trecho, OpcoesDosDados("npz"), captura, linhas_por_bloco=5_000, progresso=fracoes.append)
    assert fracoes == sorted(fracoes) and fracoes[-1] == 1.0 and len(fracoes) >= 10
    lidas = []
    destino = tmp_path / "cancelada.h5"
    with pytest.raises(Cancelado):
        ed.exportar(trecho, destino, OpcoesDosDados("hdf5"), proveniencia={}, linhas_por_bloco=5_000,
                    progresso=lidas.append, cancelado=lambda: len(lidas) >= 3)
    assert not destino.exists() and not ed.caminho_da_proveniencia(destino).exists()
    assert not list(tmp_path.glob("*.parcial"))


def test_a_proveniencia_e_os_comandos_da_cli(tmp_path, captura):
    trecho = ed.recortar(_colunas(captura, True), [(0.01, 0.02)] * 3)
    destino = _exportar(tmp_path, trecho, OpcoesDosDados("csv"), captura)
    p = json.loads(ed.caminho_da_proveniencia(destino).read_text(encoding="utf-8"))
    assert (p["dados"]["formato"], p["dados"]["linhas"], p["dados"]["separador"]) == ("csv", trecho.n, ";")
    assert [c["nome"] for c in p["colunas"]] == ["V_A", "I_A", "V_A filtrada"]
    assert p["colunas"][2]["transformada"] and p["colunas"][0]["receita"]["ganho"] == -1.5
    (fonte,) = p["fontes"]
    assert fonte["crc32_amostras"] == captura.cabecalho.crc32_amostras and fonte["cabecalho"]["num_canais"] == 2
    (comando,) = p["comandos_da_cli"]
    assert comando["comando"] is None and "transformações" in comando["nota"]       # a filtrada não tem
    sem_filtro = prov.dos_dados(ed.recortar(_colunas(captura), [(0.01, 0.02)] * 2), OpcoesDosDados("hdf5"),
                                _fontes(captura), aplicativo="0.8.0", regiao="janela")
    (comando,) = sem_filtro["comandos_da_cli"]
    inicio = round(0.01 * trecho.taxa_hz) * 2
    assert comando["comando"] == (f"adc_tool.py {captura.caminho} --export-hdf5 saida.h5 --inicio {inicio} "
                                  f"--fim {inicio + 2 * trecho.n} --incluir-tensao")


def test_o_npz_e_um_zip_sem_compressao(tmp_path, captura):
    destino = _exportar(tmp_path, ed.recortar(_colunas(captura)), OpcoesDosDados("npz"), captura)
    with zipfile.ZipFile(destino) as z:
        assert all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist())
        assert {"valores.npy", "nomes.npy", "taxa_hz.npy", "proveniencia.npy"} <= set(z.namelist())
