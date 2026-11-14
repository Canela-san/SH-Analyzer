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
