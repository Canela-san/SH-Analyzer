"""O espectro de um traço (``sh_analyzer_gui.dados.espectros``), sem Qt: os números são os da ``api`` (e esta os da
CLI, ``tests/test_api_frequencia.py``), o Welch direto nos códigos igual ao dos volts, a cadeia, as marcas e as
opções da vista."""

import numpy as np
import pytest
from capturas_sinteticas import escrever_bin
from sh_analyzer_gui.dados import espectros as esp
from sh_analyzer_gui.dados import materializacao as mat
from sh_analyzer_gui.dados.cadeia import Cadeia, Filtro
from supraharmonicos import api

FS = 200_000.0
N = 600_000


@pytest.fixture(scope="module")
def captura(tmp_path_factory):
    t = np.arange(N) / FS
    v = 0.3 + 3.0 * np.sin(2 * np.pi * 50 * t) + 0.02 * np.sin(2 * np.pi * 9_000 * t) \
        + 0.01 * np.sin(2 * np.pi * 31_000 * t) + np.random.default_rng(4).normal(0, 1e-3, N)
    caminho = escrever_bin(tmp_path_factory.mktemp("espectros") / "c.bin", [v, 0.5 * v], versao=9)
    return api.abrir_captura(caminho)


def trecho(captura, a=50_000, b=450_000, cadeia=None, ganho=1.0, materializada=None):
    return esp.TrechoDoTraco(captura, 0, cadeia or Cadeia(), mat.contexto_do_canal(captura.canal(0)), a, b, ganho,
                             materializada)


def test_o_welch_direto_nos_codigos_e_o_dos_volts(captura):
    """Sem cadeia, o Welch lê os códigos do ADC (a captura inteira não vai para a memória) e sobe 20·log10|escala|:
    o número é o do Welch sobre os volts, a 1e-12."""
    for metodo, ganho in (("welch", 1.0), ("welch", -2.5), ("fft", 1.0), ("fft", 3.0)):
        p = api.ParametrosEspectro(metodo, largura_bandas_hz=500)
        obtido = esp.espectro_do_trecho(trecho(captura, ganho=ganho), p)
        esperado = api.espectro(api.sinal_do_canal(captura, 0, 50_000, 450_000) * ganho, FS, p)
        np.testing.assert_allclose(obtido.db, esperado.db, rtol=0, atol=1e-9)
        np.testing.assert_allclose(obtido.db_bandas, esperado.db_bandas, rtol=0, atol=1e-9)
        assert obtido.n_segmentos == esperado.n_segmentos and obtido.f0_hz == esperado.f0_hz


def test_com_a_cadeia_o_trecho_e_o_do_traco_transformado(captura, tmp_path):
    cadeia = Cadeia((Filtro("passa_altas", (2000.0,), 4),))
    ctx = mat.contexto_do_canal(captura.canal(0))
    p = api.ParametrosEspectro()
    obtido = esp.espectro_do_trecho(trecho(captura, cadeia=cadeia), p)
    inteiro = cadeia.aplicar(api.sinal_do_canal(captura, 0), ctx).valores
    esperado = api.espectro(inteiro[50_000:450_000], FS, p)
    np.testing.assert_allclose(obtido.db, esperado.db, rtol=0, atol=1e-7)
    # Acima do limite da cadeia, a materialização: sem ela, espera; com ela, o mesmo espectro (float32).
    grande = esp.LIMITE_DA_CADEIA
    try:
        esp.LIMITE_DA_CADEIA = 1000
        with pytest.raises(esp.AguardandoMaterializacao):
            esp.espectro_do_trecho(trecho(captura, cadeia=cadeia), p)
        pronta = mat.CacheDeMaterializacoes(tmp_path).obter("k", cadeia, mat.leitor_do_canal(captura, 0), N, ctx)
        da_materializacao = esp.espectro_do_trecho(trecho(captura, cadeia=cadeia, materializada=pronta.amostras), p)
    finally:
        esp.LIMITE_DA_CADEIA = grande
    np.testing.assert_allclose(da_materializacao.db, esperado.db, rtol=0, atol=1e-4)    # o float32 do cache


def test_os_limites_viram_mensagens(captura):
    with pytest.raises(api.ErroSHAN, match="1 amostra"):
        esp.espectro_do_trecho(trecho(captura, 10, 11), api.ParametrosEspectro())
    limite = esp.LIMITE_DA_FFT
    try:
        esp.LIMITE_DA_FFT = 1000
        with pytest.raises(api.ErroSHAN, match="use o Welch"):
            esp.espectro_do_trecho(trecho(captura), api.ParametrosEspectro("fft"))
    finally:
        esp.LIMITE_DA_FFT = limite


def test_as_marcas_picos_piso_e_harmonicos(captura):
    welch = esp.espectro_do_trecho(trecho(captura), api.ParametrosEspectro())
    m = esp.marcas(welch, 5, True)
    assert [round(p.frequencia_hz / 1000) for p in m.picos] == [9, 31]       # os dois tons, acima do piso + 10 dB
    assert m.piso_db == pytest.approx(welch.piso(2000.0)) and m.harmonicos_hz == ()   # o Welch não tem f₁
    fft = esp.espectro_do_trecho(trecho(captura), api.ParametrosEspectro("fft"))
    m = esp.marcas(fft, 1, True, ordem_maxima=10)
    assert len(m.picos) == 1 and round(m.picos[0].frequencia_hz) == 9000
    np.testing.assert_allclose(m.harmonicos_hz, [h * fft.f0_hz for h in range(2, 11)])
    assert esp.marcas(fft, 0, False).picos == () and esp.marcas(fft, 0, False).harmonicos_hz == ()


@pytest.mark.parametrize("mudanca, trecho_da_mensagem", [
    ({"metodo": "periodograma"}, "metodo"), ({"escala": "dBV"}, "escala"), ({"trecho": "tudo"}, "trecho"),
    ({"resolucao_hz": 0}, "resolução"), ({"picos": 99}, "picos"), ({"escala": "rms", "modo": "ruido"}, "modo tom"),
    ({"frequencia_log": "sim"}, "frequencia_log"),
])
def test_opcoes_invalidas_sao_recusadas(mudanca, trecho_da_mensagem):
    with pytest.raises(esp.OpcoesInvalidas, match=trecho_da_mensagem):
        esp.OpcoesDoEspectro(**mudanca)


def test_as_opcoes_vao_e_voltam_pelo_dicionario():
    o = esp.OpcoesDoEspectro(metodo="fft", escala="dbc", frequencia_log=True, trecho="captura", vista_de_tempo="v1")
    assert esp.OpcoesDoEspectro.de_dict(o.para_dict()) == o
    assert o.parametros == api.ParametrosEspectro("fft", None, modo="tom", resolucao_hz=200.0)
    with pytest.raises(esp.OpcoesInvalidas, match="desconhecidas"):
        esp.OpcoesDoEspectro.de_dict({"cor": 1})


# ---------------------------------------------------------------------------
# As bandas IEC e o espectrograma
# ---------------------------------------------------------------------------

def test_as_bandas_nos_codigos_sao_as_dos_volts_e_as_da_cli(captura, tmp_path):
    """Sem cadeia, as bandas rodam nos códigos do ADC e são multiplicadas pela escala: os números da api sobre os
    volts, e os do adc_tool --bandas-iec (pelo .mat, a precisão inteira)."""
    from scipy.io import loadmat
    from supraharmonicos.cli_adc_tool import main

    p = esp.OpcoesDasBandas(freq_max=40_000).parametros
    for ganho in (1.0, -2.0):
        obtido = esp.bandas_do_trecho(trecho(captura, 0, N, ganho=ganho), p)
        esperado = api.bandas_iec(api.sinal_do_canal(captura, 0) * ganho, FS, p)
        np.testing.assert_allclose(obtido.bandas.niveis, esperado.bandas.niveis, rtol=1e-12)
        np.testing.assert_array_equal(obtido.bandas.centros_hz, esperado.bandas.centros_hz)
    saida = tmp_path / "bandas.mat"
    assert main([str(captura.caminho), "--bandas-iec", "--bandas-iec-max", "40000", "--sem-grafico",
                 "--exportar-mat", str(saida)]) in (0, None)
    cli = loadmat(saida, squeeze_me=True, struct_as_record=False)["sh"].canal0.bandas_iec
    obtido = esp.bandas_do_trecho(trecho(captura, 0, N), p)
    np.testing.assert_allclose(obtido.bandas.niveis, cli.niveis, rtol=1e-12)
    np.testing.assert_allclose(obtido.bandas.estatisticas()["p95"], cli.p95, rtol=1e-12)


def test_as_bandas_sincronizadas_e_com_a_cadeia(captura):
    p = esp.OpcoesDasBandas(freq_max=20_000, sincronizar=True).parametros
    obtido = esp.bandas_do_trecho(trecho(captura, 0, N), p)
    esperado = api.bandas_iec(api.sinal_do_canal(captura, 0), FS, p)
    np.testing.assert_allclose(obtido.bandas.niveis, esperado.bandas.niveis, rtol=1e-12)
    assert obtido.bandas.sincronizada and obtido.bandas.ciclos_por_janela == 10
    cadeia = Cadeia((Filtro("passa_altas", (1000.0,), 4),))
    com_cadeia = esp.bandas_do_trecho(trecho(captura, 0, N, cadeia=cadeia), esp.OpcoesDasBandas().parametros)
    inteiro = cadeia.aplicar(api.sinal_do_canal(captura, 0), mat.contexto_do_canal(captura.canal(0))).valores
    np.testing.assert_allclose(com_cadeia.bandas.niveis,
                               api.bandas_iec(inteiro, FS, esp.OpcoesDasBandas().parametros).bandas.niveis, rtol=1e-9)
    with pytest.raises(api.Cancelado):
        esp.bandas_do_trecho(trecho(captura, 0, N), esp.OpcoesDasBandas().parametros, cancelado=lambda: True)


def test_o_espectrograma_nos_codigos_e_o_dos_volts(captura):
    p = esp.OpcoesDoEspectrograma(resolucao_hz=500).parametros
    obtido = esp.espectrograma_do_trecho(trecho(captura, 0, N, ganho=3.0), p)
    esperado = api.espectrograma(api.sinal_do_canal(captura, 0) * 3.0, FS, p)
    np.testing.assert_allclose(obtido.db, esperado.db, rtol=0, atol=1e-9)
    np.testing.assert_array_equal(obtido.tempos_s, esperado.tempos_s)


@pytest.mark.parametrize("classe, mudanca, trecho_da_mensagem", [
    (esp.OpcoesDasBandas, {"estatistica": "media"}, "estatística"),
    (esp.OpcoesDasBandas, {"traco": -1}, "traço"),
    (esp.OpcoesDasBandas, {"freq_min": -5}, "freq_min"),
    (esp.OpcoesDoEspectrograma, {"faixa_dinamica_db": 0}, "faixa_dinamica_db"),
    (esp.OpcoesDoEspectrograma, {"trecho": "tudo"}, "trecho"),
])
def test_opcoes_das_bandas_e_do_espectrograma(classe, mudanca, trecho_da_mensagem):
    with pytest.raises(esp.OpcoesInvalidas, match=trecho_da_mensagem):
        classe(**mudanca)
    o = classe(vista_de_tempo="v1", traco=2)
    assert classe.de_dict(o.para_dict()) == o
