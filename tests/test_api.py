"""A ``supraharmonicos.api`` (o que a interface gráfica usa): abrir uma captura dá os mesmos canais, a mesma
calibração, os mesmos volts e a mesma correção de sonda que o caminho da CLI (``resolver_contexto`` e
``aplicar_correcao_sondas``), e os avisos do motor viram dados."""

import json
import logging

import numpy as np
import pytest
from capturas_sinteticas import FREQS_CAL, captura_producao, escrever_bin, planta_h
from supraharmonicos import api
from supraharmonicos.amostras import converter_para_tensao
from supraharmonicos.cli_adc_tool import montar_parser
from supraharmonicos.constantes import GRANDEZA_CORRENTE, GRANDEZA_TENSAO
from supraharmonicos.contexto import aplicar_correcao_sondas, resolver_contexto
from supraharmonicos.erros import ErroSHAN


@pytest.fixture(scope="module")
def ambiente(tmp_path_factory):
    base = tmp_path_factory.mktemp("api")
    sondas = base / "sondas"
    sondas.mkdir()
    perfil = {"id": "sonda_teste", "tipo": "resposta_frequencia",
              "pontos": [{"freq_hz": float(f), "ganho": float(planta_h(f))} for f in FREQS_CAL]}
    (sondas / "sonda_teste.json").write_text(json.dumps(perfil), encoding="utf-8")
    captura_producao(base / "ok.bin", dur_s=0.3)
    return base


def contexto_da_cli(ambiente, *flags):
    return resolver_contexto(montar_parser().parse_args([str(ambiente / "ok.bin"), "--sondas-dir",
                                                          str(ambiente / "sondas"), *flags]))


def test_canais_e_calibracao_iguais_aos_da_cli(ambiente):
    ctx = contexto_da_cli(ambiente)
    cap = api.abrir_captura(ambiente / "ok.bin", sondas_dir=ambiente / "sondas")
    assert [c.numero for c in cap.canais] == ctx.canais == [0, 1]
    assert [c.faixa_v for c in cap.canais] == ctx.faixas
    assert [c.ganho for c in cap.canais] == ctx.ganhos
    assert [c.offset_v for c in cap.canais] == ctx.offsets
    assert [c.faixa_confiavel for c in cap.canais] == ctx.faixas_confiaveis
    assert [c.grandeza for c in cap.canais] == [GRANDEZA_TENSAO, GRANDEZA_CORRENTE]
    assert [c.nome_grandeza for c in cap.canais] == ["tensão", "corrente"]
    assert cap.canal(1).sonda_id == "sonda_teste" and cap.canal(1).perfil.id == "sonda_teste"
    assert cap.canal(0).perfil is None
    assert all(c.taxa_hz == cap.cabecalho.frequencia_hz / 2 for c in cap.canais)


def test_volts_iguais_aos_da_cli_e_a_conversao_afim(ambiente):
    ctx = contexto_da_cli(ambiente)
    cap = api.abrir_captura(ambiente / "ok.bin", sondas_dir=ambiente / "sondas")
    assert isinstance(cap.amostras, np.memmap) and not cap.canal(0).amostras.flags.owndata    # visões, sem cópia
    todas = np.asarray(cap.amostras)
    for i, canal in enumerate(ctx.canais):
        codigos = todas[i::2]
        esperado = converter_para_tensao(codigos, ctx.faixas[i], ctx.ganhos[i], "uint16", ctx.offsets[i])
        np.testing.assert_array_equal(api.sinal_do_canal(cap, canal), esperado)
        np.testing.assert_array_equal(api.sinal_do_canal(cap, canal, 100, 250), esperado[100:250])
        c = cap.canal(canal)
        np.testing.assert_allclose(codigos * c.escala + c.deslocamento, esperado, rtol=0, atol=1e-12)


def test_correcao_de_sonda_igual_a_da_cli(ambiente):
    args = montar_parser().parse_args([str(ambiente / "ok.bin"), "--sondas-dir", str(ambiente / "sondas")])
    ctx = resolver_contexto(args)
    cap = api.abrir_captura(ambiente / "ok.bin", sondas_dir=ambiente / "sondas")
    por_canal = {c: api.sinal_do_canal(cap, c) for c in ctx.canais}
    aplicar_correcao_sondas(args, ctx, por_canal, cap.canal(1).taxa_hz)
    np.testing.assert_array_equal(api.sinal_do_canal(cap, 1, corrigir_sonda=True), por_canal[1])
    np.testing.assert_array_equal(api.sinal_do_canal(cap, 0, corrigir_sonda=True), por_canal[0])   # tensão: nada
    assert not np.array_equal(api.sinal_do_canal(cap, 1), por_canal[1])                            # corrigiu mesmo


def test_avisos_do_motor_viram_dados_e_o_logging_volta_como_estava(tmp_path):
    """Corrente sem sonda registrada: a CLI avisa no terminal; a API devolve o aviso."""
    caminho = captura_producao(tmp_path / "sem_sonda.bin", sonda_id="", dur_s=0.05)
    logger = logging.getLogger("supraharmonicos")
    nivel = logger.level
    cap = api.abrir_captura(caminho, sondas_dir=tmp_path)
    assert cap.canal(1).perfil is None and cap.canal(1).problema_sonda == ""
    assert any(a.nivel == "aviso" and "canal 1 é de corrente mas não tem sonda/perfil resolvido" in a.texto
               for a in cap.avisos)
    assert any(a.nivel == "info" and "não registra a faixa do ADC" in a.texto for a in cap.avisos)
    assert logger.level == nivel and not any(isinstance(h, api._Coletor) for h in logger.handlers)


def test_perfil_que_falta_nao_impede_de_abrir(ambiente, tmp_path):
    """A CLI para com um erro (a sonda registrada sem o arquivo do perfil); a API abre, sem o perfil naquele canal,
    e diz por quê -- a diferença deliberada documentada no módulo."""
    with pytest.raises(ErroSHAN):
        contexto_da_cli_sem_sondas = resolver_contexto(montar_parser().parse_args(
            [str(ambiente / "ok.bin"), "--sondas-dir", str(tmp_path)]))
        aplicar_correcao_sondas(montar_parser().parse_args([str(ambiente / "ok.bin")]), contexto_da_cli_sem_sondas,
                                {0: np.zeros(1), 1: np.zeros(1)}, 1.0)
    cap = api.abrir_captura(ambiente / "ok.bin", sondas_dir=tmp_path)
    assert cap.canal(1).perfil is None and "não existe um perfil" in cap.canal(1).problema_sonda
    assert any(a.nivel == "erro" and "não existe um perfil" in a.texto for a in cap.avisos)
    np.testing.assert_array_equal(api.sinal_do_canal(cap, 1, corrigir_sonda=True), api.sinal_do_canal(cap, 1))


def test_erros_viram_erro_shan(ambiente, tmp_path):
    legado = escrever_bin(tmp_path / "legado.bin", [np.zeros(100), np.zeros(100)], com_cabecalho=False)
    with pytest.raises(ErroSHAN, match="sem o cabeçalho"):
        api.abrir_captura(legado)
    (tmp_path / "x.csv").write_text("1\n2\n")
    with pytest.raises(ErroSHAN, match="só capturas .bin"):
        api.abrir_captura(tmp_path / "x.csv")
    with pytest.raises(ErroSHAN, match="formato desconhecido"):
        api.abrir_captura(ambiente / "ok.bin", formato="float32")
    cap = api.abrir_captura(ambiente / "ok.bin", sondas_dir=ambiente / "sondas")
    with pytest.raises(ErroSHAN, match="canal 5 não está na captura"):
        cap.canal(5)


def test_arquivo_cortado_no_meio_de_um_quadro(tmp_path):
    """Um quadro final incompleto fica de fora: os canais têm o mesmo número de amostras."""
    caminho = escrever_bin(tmp_path / "c.bin", [np.zeros(1000), np.ones(1000)])
    with open(caminho, "ab") as f:
        f.write(b"\x00\x80")                          # meia varredura a mais
    cap = api.abrir_captura(caminho)
    assert len(cap.canal(0).amostras) == len(cap.canal(1).amostras) == 1000


def test_conferir_integridade_com_progresso_e_cancelamento(tmp_path):
    from supraharmonicos.api import abrir_captura, conferir_integridade

    caminho = escrever_bin(tmp_path / "v9.bin", [np.zeros(50_000), np.ones(50_000)], versao=9)
    captura = abrir_captura(caminho)
    fracoes = []
    assert conferir_integridade(captura, progresso=fracoes.append) is True
    assert fracoes and fracoes[-1] == 1.0
    assert conferir_integridade(captura, cancelado=lambda: True) is None
    antigo = abrir_captura(escrever_bin(tmp_path / "v3.bin", [np.zeros(1000), np.zeros(1000)]))
    assert conferir_integridade(antigo) is None                        # sem o CRC gravado
    dados = bytearray(caminho.read_bytes())
    dados[-3] ^= 0xFF                                                   # uma amostra alterada depois da captura
    alterado = tmp_path / "alterado.bin"
    alterado.write_bytes(bytes(dados))
    assert conferir_integridade(abrir_captura(alterado)) is False


def test_descrever_cabecalho(tmp_path):
    from supraharmonicos.api import abrir_captura, descrever_cabecalho

    caminho = escrever_bin(tmp_path / "c.bin", [np.zeros(4096), np.zeros(4096)], canais=(1, 3), versao=9)
    secoes = dict(descrever_cabecalho(abrir_captura(caminho, sondas_dir=tmp_path)))
    assert list(secoes) == ["Captura", "Canais", "Integridade", "BeagleBone"]
    captura = dict(secoes["Captura"])
    assert captura["Arquivo"] == "c.bin" and captura["Cabeçalho"] == "v9" and captura["Amostras"] == "8192"
    assert [r for r, _ in secoes["Canais"]][:2] == ["Canal 1", "Canal 3"]
    assert "tensão" in dict(secoes["Canais"])["Canal 1"]
    assert all(v for _, linhas in secoes.items() for _, v in linhas)    # nada vazio nem "None"
    antigo = dict(descrever_cabecalho(abrir_captura(escrever_bin(tmp_path / "v3.bin", [np.zeros(9), np.zeros(9)]))))
    assert "CRC das amostras" not in dict(antigo["Integridade"])


def test_a_unidade_do_canal_segue_o_ganho_declarado(tmp_path):
    """Sem o ganho declarado na captura, o valor é a tensão no pino (V), mesmo num canal de corrente; com ele, a
    unidade da grandeza."""
    from supraharmonicos.api import abrir_captura

    sinais = [np.zeros(4096), np.zeros(4096)]
    sem = abrir_captura(escrever_bin(tmp_path / "sem.bin", sinais, grandezas=(0, 1), versao=9), sondas_dir=tmp_path)
    assert [(c.nome_grandeza, c.ganho_declarado, c.unidade) for c in sem.canais] == [("tensão", False, "V"),
                                                                                      ("corrente", False, "V")]
    com = abrir_captura(escrever_bin(tmp_path / "com.bin", sinais, grandezas=(0, 1), versao=9,
                                     extensao={"ganhos": [19.65, 20.0]}), sondas_dir=tmp_path)
    assert [(c.ganho, c.ganho_declarado, c.unidade) for c in com.canais] == [(19.65, True, "V"), (20.0, True, "A")]


def test_medir_regiao_igual_as_contas_da_cli(tmp_path):
    """As medidas de um trecho são as do ``calcular_basicas`` e do ``cruzamentos_da_fundamental`` sobre os volts da
    CLI, com o ganho e o offset do traço aplicados depois."""
    from supraharmonicos.api import abrir_captura, medir_regiao, sinal_do_canal
    from supraharmonicos.fundamental import cruzamentos_da_fundamental
    from supraharmonicos.metricas_captura import calcular_basicas

    fs = 200_000
    t = np.arange(fs // 2) / fs                                          # 0,5 s
    v = 2.0 * np.sin(2 * np.pi * 59.98 * t) + 0.3 + 0.05 * np.sin(2 * np.pi * 20_000 * t)
    captura = abrir_captura(escrever_bin(tmp_path / "c.bin", [v, np.zeros_like(v)], versao=9), sondas_dir=tmp_path)
    m = medir_regiao(captura, 0, 10_000, 90_000, ganho=-2.0, offset=0.5)
    sinal = sinal_do_canal(captura, 0, 10_000, 90_000) * -2.0 + 0.5
    b = calcular_basicas(sinal, fs)
    assert (m.n_amostras, m.media, m.rms, m.rms_ac, m.pico_a_pico) == (b.n_amostras, b.media, b.rms_total, b.rms_ac,
                                                                        b.pico_a_pico)
    assert m.pico == max(abs(b.minimo), abs(b.maximo))
    assert m.f1_hz == cruzamentos_da_fundamental(sinal, fs, 45.0, 65.0)[1] and m.f1_hz == pytest.approx(59.98, abs=0.01)
    sem = medir_regiao(captura, 1, 0, 50_000)                            # um canal parado: sem fundamental
    assert sem.f1_hz is None and sem.problema_f1
    with pytest.raises(ErroSHAN):
        medir_regiao(captura, 0, 5, 6)


def test_medir_regiao_sem_a_fundamental(tmp_path):
    from supraharmonicos.api import abrir_captura, aquecer, medir_regiao

    aquecer()
    t = np.arange(100_000) / 200_000
    captura = abrir_captura(escrever_bin(tmp_path / "c.bin", [np.sin(2 * np.pi * 60 * t), np.zeros_like(t)],
                                         versao=9), sondas_dir=tmp_path)
    com, sem = medir_regiao(captura, 0, 0, 100_000), medir_regiao(captura, 0, 0, 100_000, fundamental=False)
    assert com.f1_hz == pytest.approx(60, abs=0.01) and sem.f1_hz is None and "não foi calculada" in sem.problema_f1
    assert (sem.media, sem.rms, sem.pico_a_pico) == (com.media, com.rms, com.pico_a_pico)
