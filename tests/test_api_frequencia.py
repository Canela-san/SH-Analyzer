"""A frequência na ``supraharmonicos.api`` (o que a vista de espectro da interface vai usar): o espectro, os picos, o
espectrograma, as bandas IEC e os harmônicos dão os mesmos números que o ``adc_tool`` para o mesmo trecho.

A paridade é conferida contra a CLI de verdade, rodando no mesmo processo e exportando para o ``.mat`` (a precisão
inteira do ``float64``; o CSV tem 10 algarismos): o mesmo arquivo, o mesmo trecho (``--inicio``/``--fim`` contam as
amostras intercaladas; a API, as de um canal), a mesma correção de sonda."""

import json
import logging
import threading

import numpy as np
import pytest
from capturas_sinteticas import FREQS_CAL, captura_producao, planta_h
from supraharmonicos import api
from supraharmonicos.cli_adc_tool import main

RTOL = 1e-12
INICIO, FIM = 20_000, 1_580_000          # amostras intercaladas (2 canais): 10 000 a 790 000 de cada canal (3,9 s)


@pytest.fixture(scope="module")
def ambiente(tmp_path_factory):
    base = tmp_path_factory.mktemp("api_frequencia")
    sondas = base / "sondas"
    sondas.mkdir()
    perfil = {"id": "sonda_teste", "tipo": "resposta_frequencia",
              "pontos": [{"freq_hz": float(f), "ganho": float(planta_h(f))} for f in FREQS_CAL]}
    (sondas / "sonda_teste.json").write_text(json.dumps(perfil), encoding="utf-8")
    captura_producao(base / "ok.bin", dur_s=4.0)          # 19 janelas de 200 ms no trecho: uma série agregada de ~3 s
    return base


@pytest.fixture(scope="module")
def captura(ambiente):
    return api.abrir_captura(ambiente / "ok.bin", sondas_dir=ambiente / "sondas")


def rodar_cli(ambiente, nome, *flags):
    """Roda o adc_tool com ``flags`` sobre o trecho e devolve ``sh`` do .mat exportado."""
    from scipy.io import loadmat

    saida = ambiente / f"{nome}.mat"
    rc = main([str(ambiente / "ok.bin"), "--sondas-dir", str(ambiente / "sondas"), "--inicio", str(INICIO),
               "--fim", str(FIM), "--sem-grafico", "--exportar-mat", str(saida), *flags])
    assert rc in (0, None)
    return loadmat(saida, squeeze_me=True, struct_as_record=False)["sh"]


def trecho(captura, canal):
    return api.sinal_do_canal(captura, canal, INICIO // 2, FIM // 2, corrigir_sonda=True)


def mesmo(obtido, esperado):
    np.testing.assert_allclose(np.asarray(obtido, dtype=float), np.asarray(esperado, dtype=float), rtol=RTOL, atol=0)


def picos_da_cli(sh, canal, metodo):
    todos = np.atleast_1d(sh.picos)
    return [(float(p.frequencia_hz), float(p.amplitude_db)) for p in todos
            if int(p.canal) == canal and p.metodo == metodo]


# ---------------------------------------------------------------------------
# A paridade com a CLI
# ---------------------------------------------------------------------------

def test_fft_sincronizada_bandas_picos_e_harmonicos_iguais_aos_da_cli(ambiente, captura):
    sh = rodar_cli(ambiente, "fft", "--fft", "--harmonicos", "25", "--picos", "-70", "--agrupar-bandas", "200")
    for canal in (0, 1):
        cli = getattr(sh, f"canal{canal}")
        esp = api.espectro(trecho(captura, canal), captura.canal(canal).taxa_hz,
                           api.ParametrosEspectro("fft", largura_bandas_hz=200))
        mesmo(esp.freqs_hz, cli.fft.f)
        mesmo(esp.db, cli.fft.db)
        assert (esp.f0_hz, esp.n_ciclos, esp.n_amostras, esp.inicio_local) == (
            cli.fft.f0_hz, cli.fft.n_ciclos, cli.fft.amostras, cli.fft.inicio_local)
        assert esp.janela == "boxcar" and esp.n_segmentos == 1
        mesmo(esp.centros_bandas_hz, cli.fft_bandas.f)
        mesmo(esp.db_bandas, cli.fft_bandas.db)

        achados = api.picos(esp, -70)
        esperados = picos_da_cli(sh, canal, "ciclo")
        assert len(achados) == len(esperados) and (canal == 0 or achados)    # a tensão não tem tons acima de 2 kHz
        mesmo([p.frequencia_hz for p in achados], [f for f, _ in esperados])
        mesmo([p.db for p in achados], [d for _, d in esperados])

        h = api.harmonicos(trecho(captura, canal), captura.canal(canal).taxa_hz, api.ParametrosHarmonicos(25))
        tab, esperado = h.tabela, cli.harmonicos
        assert (tab.f0_hz, tab.n_ciclos) == (esperado.f0_hz, esperado.n_ciclos)
        assert (h.inicio_local, h.fim_local - h.inicio_local) == (cli.fft.inicio_local, cli.fft.amostras)
        for campo, coluna in (("rms", "rms"), ("rms_grupo", "rms_grupo"), ("rms_subgrupo", "rms_subgrupo"),
                              ("pct_fundamental", "pct_fundamental"), ("fase_graus", "fase_graus"),
                              ("frequencia_hz", "f")):
            mesmo([getattr(x, campo) for x in tab.harmonicos], getattr(esperado, coluna))
        mesmo([tab.thd_pct, tab.thdg_pct, tab.thds_pct, tab.rms_total],
              [esperado.thd_pct, esperado.thdg_pct, esperado.thds_pct, esperado.rms_total])


def test_welch_com_janela_modo_ruido_bandas_e_picos_igual_ao_da_cli(ambiente, captura):
    flags = ("--welch", "--resolucao-welch", "50", "--sobreposicao-welch", "0.25", "--janela", "flat-top",
             "--modo-espectro", "ruido", "--agrupar-bandas", "500", "--picos", "-120", "--freq-min-picos", "1000",
             "--distancia-minima-picos", "300")
    sh = rodar_cli(ambiente, "welch", *flags)
    parametros = api.ParametrosEspectro("welch", janela="flat-top", modo="ruido", resolucao_hz=50, sobreposicao=0.25,
                                        largura_bandas_hz=500)
    for canal in (0, 1):
        cli = getattr(sh, f"canal{canal}")
        esp = api.espectro(trecho(captura, canal), captura.canal(canal).taxa_hz, parametros)
        mesmo(esp.freqs_hz, cli.welch.f)
        mesmo(esp.db, cli.welch.db)
        assert esp.n_segmentos == cli.welch.n_segmentos and esp.janela == "flattop"
        mesmo(esp.centros_bandas_hz, cli.welch_bandas.f)
        mesmo(esp.db_bandas, cli.welch_bandas.db)
        achados = api.picos(esp, -120, freq_min=1000, distancia_minima_hz=300)
        esperados = picos_da_cli(sh, canal, "welch")
        assert len(achados) == len(esperados) and (canal == 0 or achados)
        mesmo([p.frequencia_hz for p in achados], [f for f, _ in esperados])


def test_espectrograma_igual_ao_da_cli(ambiente, captura):
    sh = rodar_cli(ambiente, "espectrograma", "--espectrograma", "--resolucao-welch", "400", "--janela", "kaiser",
                   "--kaiser-beta", "6")
    cli = sh.canal1.espectrograma
    esp = api.espectrograma(trecho(captura, 1), captura.canal(1).taxa_hz,
                            api.ParametrosEspectrograma(janela="kaiser", kaiser_beta=6, resolucao_hz=400))
    mesmo(esp.tempos_s, cli.t)
    mesmo(esp.freqs_hz, cli.f)
    mesmo(esp.db, cli.db)
    assert esp.db.shape == (len(esp.tempos_s), len(esp.freqs_hz)) and esp.rotulo_janela == "Kaiser (beta=6)"


def test_bandas_iec_fixas_iguais_as_da_cli(ambiente, captura):
    sh = rodar_cli(ambiente, "bandas", "--bandas-iec", "--bandas-iec-max", "20000")
    for canal in (0, 1):
        cli = getattr(sh, f"canal{canal}").bandas_iec
        r = api.bandas_iec(trecho(captura, canal), captura.canal(canal).taxa_hz, api.ParametrosBandasIEC(freq_max=20_000))
        mesmo(r.bandas.centros_hz, cli.centros_hz)
        mesmo(r.bandas.tempos_s, cli.tempos_s)
        mesmo(r.bandas.niveis, cli.niveis)
        for estatistica in ("rms", "maximo", "p95", "minimo"):
            mesmo(r.bandas.estatisticas()[estatistica], getattr(cli, estatistica))
        assert not r.bandas.sincronizada and r.janelas_descartadas == 0


def test_bandas_iec_sincronizadas_e_agregadas_iguais_as_da_cli(ambiente, captura):
    """A CLI sincroniza as janelas de todos os canais pela tensão (o canal 0); a API, pela ``referencia`` dada."""
    sh = rodar_cli(ambiente, "bandas_sinc", "--bandas-iec", "--bandas-iec-max", "9000", "--bandas-iec-sincronizar",
                   "--bandas-iec-agregar")
    tensao = trecho(captura, 0)
    parametros = api.ParametrosBandasIEC(freq_max=9000, sincronizar=True, agregar=True)
    for canal in (0, 1):
        cli = getattr(sh, f"canal{canal}").bandas_iec
        r = api.bandas_iec(trecho(captura, canal), captura.canal(canal).taxa_hz, parametros, referencia=tensao)
        assert r.bandas.sincronizada and (r.bandas.ciclos_por_janela, r.bandas.f0_hz) == (cli.ciclos_por_janela,
                                                                                          cli.f0_hz)
        mesmo(r.bandas.tempos_s, cli.tempos_s)
        mesmo(r.bandas.niveis, cli.niveis)
        assert set(r.bandas.agregados) == {"3s"}
        agregada = r.bandas.agregados["3s"].niveis
        mesmo(agregada, np.reshape(cli.agregado_3s.niveis, agregada.shape))     # o .mat achata 1 intervalo


# ---------------------------------------------------------------------------
# O que a CLI não tem: a FFT sem sincronizar, as escalas, os N maiores picos
# ---------------------------------------------------------------------------

def tom(n=20_000, fs=100_000.0, f=1_000.0, amplitude=2.0, dc=0.0):
    t = np.arange(n) / fs
    return dc + amplitude * np.sin(2 * np.pi * f * t), fs


def test_fft_sem_sincronizar_usa_o_trecho_inteiro_e_a_hann():
    sinal, fs = tom()
    esp = api.espectro(sinal, fs, api.ParametrosEspectro("fft", sincronizar=False))
    assert esp.janela == "hann" and esp.n_amostras == len(sinal) and esp.inicio_local == 0 and esp.f0_hz is None
    assert esp.resolucao_hz == pytest.approx(fs / len(sinal))
    assert esp.nivel_em(1_000.0) == pytest.approx(20 * np.log10(2.0), abs=1e-9)    # bin exato: a amplitude de pico


def test_sem_a_fundamental_a_fft_sincronizada_explica_por_que():
    sinal, fs = tom()                                       # 1 kHz, sem nada entre 45 e 65 Hz
    with pytest.raises(api.ErroSHAN):
        api.espectro(sinal, fs, api.ParametrosEspectro("fft"))
    with pytest.raises(api.ErroSHAN):
        api.harmonicos(sinal, fs)


def test_as_escalas_do_espectro():
    sinal, fs = tom(dc=0.5)
    esp = api.espectro(sinal, fs, api.ParametrosEspectro("fft", janela="retangular", sincronizar=False))
    i = int(np.argmin(np.abs(esp.freqs_hz - 1_000.0)))
    assert esp.niveis("linear")[i] == pytest.approx(2.0, rel=1e-9)
    assert esp.niveis("rms")[i] == pytest.approx(2.0 / np.sqrt(2), rel=1e-9)
    assert esp.niveis("rms")[0] == esp.niveis("linear")[0]                   # o DC não tem par: o próprio nível
    dbc = esp.niveis("dbc")                                                  # sem f0: o bin mais alto fora do DC
    assert dbc[i] == 0.0 and dbc.max() == 0.0
    assert esp.niveis("dbc", referencia_hz=1_000.0)[i] == 0.0
    np.testing.assert_array_equal(esp.niveis(), esp.db)
    assert esp.rotulo("V") == "Magnitude (dBV)"

    psd = api.espectro(sinal, fs, api.ParametrosEspectro("welch", modo="ruido"))
    np.testing.assert_allclose(psd.niveis("linear"), 10 ** (psd.db / 10))
    assert psd.rotulo("A") == "PSD (dB re A²/Hz)"
    with pytest.raises(api.ErroSHAN, match="modo tom"):
        psd.niveis("rms")
    with pytest.raises(api.ErroSHAN, match="escala desconhecida"):
        psd.niveis("dBV")


def test_a_fundamental_e_a_referencia_do_dbc_na_fft_sincronizada(captura):
    esp = api.espectro(trecho(captura, 0), captura.canal(0).taxa_hz, api.ParametrosEspectro("fft"))
    assert esp.niveis("dbc")[esp.n_ciclos] == 0.0           # a fundamental cai no bin n_ciclos


def test_os_n_maiores_picos_em_ordem_de_frequencia(captura):
    esp = api.espectro(trecho(captura, 1), captura.canal(1).taxa_hz, api.ParametrosEspectro("welch"))
    todos = api.picos(esp, -80, freq_min=1_000)
    tres = api.picos(esp, -80, freq_min=1_000, maximo=3)
    assert len(todos) > 3 and len(tres) == 3
    assert [p.frequencia_hz for p in tres] == sorted(p.frequencia_hz for p in tres)
    assert sorted(p.db for p in tres) == sorted(p.db for p in todos)[-3:]


def test_pedir_mais_ciclos_do_que_ha_vira_um_aviso(captura):
    esp = api.espectro(trecho(captura, 0), captura.canal(0).taxa_hz, api.ParametrosEspectro("fft", n_ciclos=10_000))
    assert esp.n_ciclos < 10_000 and any("10000 ciclos" in a.texto for a in esp.avisos)


@pytest.mark.parametrize("parametros, trecho_da_mensagem", [
    (api.ParametrosEspectro("periodograma"), "método"),
    (api.ParametrosEspectro(modo="pico"), "modo"),
    (api.ParametrosEspectro(janela="triangular"), "janela"),
    (api.ParametrosEspectro(janela="kaiser", kaiser_beta=-1), "beta"),
    (api.ParametrosEspectro(resolucao_hz=0), "resolução"),
    (api.ParametrosEspectro(resolucao_hz=20_000), "16 amostras"),
    (api.ParametrosEspectro(sobreposicao=1.0), "sobreposição"),
    (api.ParametrosEspectro("fft", n_ciclos=0), "ciclos"),
    (api.ParametrosEspectro("fft", freq_min_fundamental=70), "fundamental"),
    (api.ParametrosEspectro(largura_bandas_hz=-200), "largura"),
])
def test_parametros_invalidos_do_espectro_sao_recusados_com_o_motivo(parametros, trecho_da_mensagem):
    sinal, fs = tom()
    with pytest.raises(api.ErroSHAN, match=trecho_da_mensagem):
        api.espectro(sinal, fs, parametros)


def test_parametros_invalidos_das_outras_contas():
    sinal, fs = tom()
    esp = api.espectro(sinal, fs)
    with pytest.raises(api.ErroSHAN, match="mínimo < máximo"):
        api.picos(esp, -80, freq_min=10_000, freq_max=5_000)
    with pytest.raises(api.ErroSHAN, match=">= 1"):
        api.picos(esp, -80, maximo=0)
    with pytest.raises(api.ErroSHAN, match="nenhuma banda"):
        api.bandas_iec(sinal, fs, api.ParametrosBandasIEC(freq_min=49_900))
    with pytest.raises(api.ErroSHAN, match="largura"):
        api.bandas_iec(sinal, fs, api.ParametrosBandasIEC(largura_hz=0))
    with pytest.raises(api.ErroSHAN, match="ordem máxima"):
        api.harmonicos(sinal, fs, api.ParametrosHarmonicos(ordem_maxima=0))
    with pytest.raises(api.ErroSHAN, match="coluna"):
        api.espectrograma(sinal, fs, api.ParametrosEspectrograma(max_colunas=0))
    with pytest.raises(api.ErroSHAN, match="taxa"):
        api.espectro(sinal, 0.0)


# ---------------------------------------------------------------------------
# As contas longas: um memmap, o progresso e o cancelamento
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def longo(tmp_path_factory):
    """60 s de ruído a 50 kHz num memmap de float32 (o formato do cache das transformações): vários lotes em cada
    conta (o Welch e o espectrograma de 5 Hz, com 10 000 amostras por segmento, vão em lotes de 209 segmentos; as
    bandas, de 64 janelas)."""
    caminho = tmp_path_factory.mktemp("longo") / "sinal.f32"
    valores = np.random.default_rng(3).normal(0, 1, 3_000_000).astype(np.float32)
    valores.tofile(caminho)
    return np.memmap(caminho, dtype=np.float32, mode="r"), 50_000.0


CONTAS_LONGAS = {
    "welch": lambda s, fs, **kw: api.espectro(s, fs, api.ParametrosEspectro(resolucao_hz=5), **kw),
    "espectrograma": lambda s, fs, **kw: api.espectrograma(s, fs, api.ParametrosEspectrograma(resolucao_hz=5), **kw),
    "bandas": lambda s, fs, **kw: api.bandas_iec(s, fs, **kw),
}


@pytest.mark.parametrize("conta", sorted(CONTAS_LONGAS))
def test_as_contas_longas_aceitam_um_memmap_e_dao_o_progresso(longo, conta):
    sinal, fs = longo
    fracoes = []
    resultado = CONTAS_LONGAS[conta](sinal, fs, progresso=fracoes.append)
    assert len(fracoes) >= 2 and fracoes == sorted(fracoes) and fracoes[-1] == 1.0 and 0 < fracoes[0] < 1
    na_memoria = CONTAS_LONGAS[conta](np.asarray(sinal, dtype=np.float64), fs)
    for nome in ("db", "bandas"):
        if hasattr(resultado, nome):
            obtido, esperado = getattr(resultado, nome), getattr(na_memoria, nome)
            if nome == "bandas":
                obtido, esperado = obtido.niveis, esperado.niveis
            np.testing.assert_allclose(obtido, esperado, rtol=1e-12)


@pytest.mark.parametrize("conta", sorted(CONTAS_LONGAS))
def test_as_contas_longas_param_quando_canceladas(longo, conta):
    sinal, fs = longo
    fracoes = []
    with pytest.raises(api.Cancelado):
        CONTAS_LONGAS[conta](sinal, fs, progresso=fracoes.append, cancelado=lambda: len(fracoes) >= 1)
    assert len(fracoes) == 1
    assert not issubclass(api.Cancelado, api.ErroSHAN)       # cancelar não é um erro para mostrar


def test_bandas_sincronizadas_dao_o_progresso_e_param_quando_canceladas(captura):
    sinal, fs = trecho(captura, 0), captura.canal(0).taxa_hz
    parametros = api.ParametrosBandasIEC(freq_max=9000, sincronizar=True)
    fracoes = []
    api.bandas_iec(sinal, fs, parametros, progresso=fracoes.append)
    assert fracoes[-1] == 1.0
    with pytest.raises(api.Cancelado):
        api.bandas_iec(sinal, fs, parametros, cancelado=lambda: True)


def test_os_avisos_de_cada_thread_ficam_com_ela():
    """Duas contas ao mesmo tempo, em threads diferentes: cada uma recebe só os seus avisos, e o nível do logger do
    motor volta ao de antes quando a última termina."""
    logger = logging.getLogger(api.LOGGER_DO_MOTOR)
    nivel = logger.level
    dentro = threading.Barrier(2)
    resultados = {}

    def conta(nome):
        with api.capturar_avisos() as avisos:
            dentro.wait(timeout=5)
            logger.warning(f"aviso de {nome}")
            dentro.wait(timeout=5)
        resultados[nome] = [a.texto for a in avisos]

    threads = [threading.Thread(target=conta, args=(nome,)) for nome in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert resultados == {"a": ["aviso de a"], "b": ["aviso de b"]}
    assert logger.level == nivel and not any(isinstance(h, api._Coletor) for h in logger.handlers)


# ---------------------------------------------------------------------------
# Os filtros da cadeia de transformações
# ---------------------------------------------------------------------------

def test_filtros_iguais_aos_da_cli(ambiente, captura):
    """O --filtro-passa-alta e o --filtro-passa-baixa (com --ordem-filtro) do adc_tool, depois da correção de sonda:
    o Welch do canal filtrado pela API é o da CLI."""
    sh = rodar_cli(ambiente, "filtros", "--welch", "--filtro-passa-alta", "2000", "--filtro-passa-baixa", "45000",
                   "--ordem-filtro", "4")
    taxa = captura.canal(1).taxa_hz
    filtrado = api.filtrar(api.filtrar(trecho(captura, 1), taxa, "passa_altas", 2000, 4), taxa, "passa_baixas",
                           45_000, 4)
    esp = api.espectro(filtrado, taxa)
    mesmo(esp.db, sh.canal1.welch.db)


def test_passa_faixa_e_rejeita_faixa():
    fs = 100_000.0
    t = np.arange(200_000) / fs
    sinal = np.sin(2 * np.pi * 1_000 * t) + np.sin(2 * np.pi * 10_000 * t)
    meio = slice(50_000, 150_000)

    def amplitude(x, f):
        return api.espectro(x[meio], fs, api.ParametrosEspectro("fft", sincronizar=False)).nivel_em(f)

    faixa = api.filtrar(sinal, fs, "passa_faixa", (5_000, 20_000), 4)
    rejeita = api.filtrar(sinal, fs, "rejeita_faixa", (5_000, 20_000), 4)
    assert amplitude(faixa, 10_000) == pytest.approx(0, abs=0.05) and amplitude(faixa, 1_000) < -60
    assert amplitude(rejeita, 1_000) == pytest.approx(0, abs=0.05) and amplitude(rejeita, 10_000) < -60
    sos = api.projetar_filtro("passa_faixa", (5_000, 20_000), 4, fs)
    assert sos.shape == (4, 6)                                 # a faixa tem o dobro de polos: 2 x 4 = 8, 4 seções


@pytest.mark.parametrize("tipo, cortes, ordem, trecho_da_mensagem", [
    ("passa_tudo", 1000, 4, "desconhecido"),
    ("passa_altas", (1000, 2000), 4, "1 corte"),
    ("passa_faixa", 1000, 4, "2 corte"),
    ("passa_baixas", 0, 4, "entre 0 e a Nyquist"),
    ("passa_baixas", 50_000, 4, "entre 0 e a Nyquist"),
    ("passa_faixa", (2000, 1000), 4, "inferior"),
    ("passa_baixas", 1000, 0, "ordem"),
    ("passa_baixas", 1000, 4.0, "ordem"),
    ("passa_baixas", "mil", 4, "cortes inválidos"),
])
def test_filtros_invalidos_sao_recusados_com_o_motivo(tipo, cortes, ordem, trecho_da_mensagem):
    with pytest.raises(api.ErroSHAN, match=trecho_da_mensagem):
        api.filtrar(np.zeros(1000), 100_000.0, tipo, cortes, ordem)


def test_carregar_um_perfil_escolhido(ambiente, tmp_path):
    perfil = api.carregar_perfil(ambiente / "sondas" / "sonda_teste.json")
    assert perfil.id == "sonda_teste"
    with pytest.raises(api.ErroSHAN):
        api.carregar_perfil(tmp_path / "nao_existe.json")
