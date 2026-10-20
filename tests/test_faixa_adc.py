"""Faixa de entrada do ADC por canal (cabeçalho v3): como as ferramentas Python a resolvem e usam.

Regra: ``--faixa`` digitado > faixa gravada no cabeçalho v3 > 20.48 (a faixa de reset do ADC, capturas v1/v2).
O ``ler_adc --faixa-adc`` escolhe a faixa de cada canal (menor faixa = menor LSB e menos ruído em Volts); o
cabeçalho a registra e estas ferramentas a aplicam sozinhas -- sem isso, um ``--faixa`` esquecido escalaria a
amplitude errado em silêncio.
"""

import json
import logging
from pathlib import Path

import numpy as np
import pytest
from capturas_sinteticas import escrever_bin
from supraharmonicos.amostras import carregar_amostras_bin, converter_para_tensao
from supraharmonicos.cabecalho import CABECALHO_TAMANHO_TOTAL
from supraharmonicos.calibracao_sonda import processar_captura
from supraharmonicos.canais import desintercalar, faixa_cli_do_total_v, resolver_faixas
from supraharmonicos.cli_adc_tool import montar_parser
from supraharmonicos.contexto import resolver_contexto
from supraharmonicos.sonda import PerfilSonda, conferir_calibracao_perfil

FS = 200_000.0
T = np.arange(40_000) / FS


def senoide(amplitude_v: float, freq_hz: float = 1000.0) -> np.ndarray:
    return amplitude_v * np.sin(2 * np.pi * freq_hz * T)


# --------------------------------------------------------------------------------------
# resolver_faixas
# --------------------------------------------------------------------------------------
class TestResolverFaixas:
    def test_sem_nada_vale_o_padrao_historico_e_nao_e_confiavel(self):
        assert resolver_faixas(None, [0, 1], "uint16", None) == ([20.48, 20.48], [False, False])

    def test_sem_texto_usa_a_faixa_do_cabecalho_de_cada_canal(self):
        assert resolver_faixas(None, [0, 3], "uint16", (20.48, 5.12)) == ([20.48, 5.12], [True, True])

    def test_canal_de_faixa_desconhecida_cai_no_padrao(self):
        assert resolver_faixas(None, [0, 3], "uint16", (None, 5.12)) == ([20.48, 5.12], [False, True])

    def test_int16_usa_a_metade_positiva(self):
        """int16: V = código·faixa/32768 (faixa = +fundo de escala), uint16: V = código·faixa/65536 − faixa/2."""
        assert resolver_faixas(None, [0, 1], "int16", (20.48, 5.12)) == ([10.24, 2.56], [True, True])
        assert faixa_cli_do_total_v(20.48, "int16") == 10.24 and faixa_cli_do_total_v(20.48, "uint16") == 20.48

    def test_texto_digitado_vence_e_igual_ao_cabecalho_e_confiavel(self, caplog):
        with caplog.at_level(logging.WARNING):
            assert resolver_faixas("20.48,5.12", [0, 3], "uint16", (20.48, 5.12)) == ([20.48, 5.12], [True, True])
        assert not caplog.records

    def test_um_valor_vale_para_todos_os_canais(self):
        assert resolver_faixas("5.12", [0, 3], "uint16", None) == ([5.12, 5.12], [False, False])

    def test_texto_diferente_do_cabecalho_vence_mas_avisa(self, caplog):
        with caplog.at_level(logging.WARNING):
            faixas, confiaveis = resolver_faixas("10.24", [0, 3], "uint16", (20.48, 5.12))
        assert faixas == [10.24, 10.24] and confiaveis == [False, False]
        avisos = [r.getMessage() for r in caplog.records]
        assert len(avisos) == 2 and "canal 0" in avisos[0] and "20.48" in avisos[0] and "canal 3" in avisos[1]

    def test_cabecalho_com_outra_quantidade_de_canais_e_ignorado(self):
        assert resolver_faixas(None, [0, 1, 2], "uint16", (20.48, 5.12)) == ([20.48] * 3, [False] * 3)

    def test_valor_invalido_e_erro_de_uso(self):
        from supraharmonicos.erros import ErroSHAN

        with pytest.raises(ErroSHAN, match="--faixa"):
            resolver_faixas("abc", [0], "uint16", None)


# --------------------------------------------------------------------------------------
# adc_tool / medir_captura: contexto da captura
# --------------------------------------------------------------------------------------
def contexto(caminho, *extra):
    return resolver_contexto(montar_parser().parse_args([str(caminho), *extra]))


def test_contexto_usa_a_faixa_do_cabecalho_por_canal_e_o_offset_acompanha(tmp_path):
    p = escrever_bin(tmp_path / "v3.bin", [senoide(9.0), senoide(0.5)], (0, 1), (0, 1), ("", "s"),
                     faixas_adc_total_v=(20.48, 5.12))
    ctx = contexto(p)
    assert ctx.faixas == [20.48, 5.12] and ctx.faixas_confiaveis == [True, True]
    assert ctx.offsets == [10.24, 2.56]                      # offset automático = faixa/2 (uint16), por canal


def test_amplitude_em_volts_correta_em_cada_faixa(tmp_path):
    """Sinais no pino: 9 V no canal 0 (±10,24 V) e 0,5 V no canal 1 (±2,56 V). Sem ``--faixa`` nenhuma."""
    p = escrever_bin(tmp_path / "v3.bin", [senoide(9.0), senoide(0.5)], (0, 1), (0, 1), ("", "s"),
                     faixas_adc_total_v=(20.48, 5.12))
    ctx = contexto(p)
    por_canal = desintercalar(carregar_amostras_bin(p, "uint16", offset=CABECALHO_TAMANHO_TOTAL), ctx.canais)
    for canal, esperado in ((0, 9.0), (1, 0.5)):
        i = ctx.indice_no_ciclo(canal)
        v = converter_para_tensao(por_canal[canal], ctx.faixas[i], 1.0, "uint16", ctx.offsets[i])
        assert np.max(np.abs(v)) == pytest.approx(esperado, rel=1e-3)


def test_captura_v2_continua_com_o_padrao_historico(tmp_path):
    p = escrever_bin(tmp_path / "v2.bin", [senoide(1.0), senoide(1.0)])
    ctx = contexto(p)
    assert ctx.faixas == [20.48, 20.48] and ctx.faixas_confiaveis == [False, False]


def test_faixa_digitada_errada_avisa_e_vence(tmp_path, caplog):
    p = escrever_bin(tmp_path / "v3.bin", [senoide(1.0), senoide(1.0)], faixas_adc_total_v=(20.48, 5.12))
    with caplog.at_level(logging.WARNING):
        ctx = contexto(p, "--faixa", "10.24")
    assert ctx.faixas == [10.24, 10.24] and ctx.faixas_confiaveis == [False, False]
    assert any("canal 0" in r.getMessage() and "20.48" in r.getMessage() for r in caplog.records)


def test_menor_faixa_reduz_o_erro_de_quantizacao_na_mesma_proporcao():
    """O motivo de ``--faixa-adc``: um sinal pequeno quantizado em ±2,56 V tem 4x menos erro (em V) que em ±10,24 V."""
    from capturas_sinteticas import volts_para_codigos

    rng = np.random.default_rng(7)
    x = 0.01 * np.sin(2 * np.pi * rng.uniform(0, 1, 200_000)) + rng.uniform(-1, 1, 200_000) * 0.003   # ~10 mV, sem periodicidade
    erros = {}
    for total_v in (20.48, 10.24, 5.12):
        v = converter_para_tensao(volts_para_codigos(x, "uint16", total_v), total_v, 1.0, "uint16", total_v / 2)
        erros[total_v] = np.std(v - x)
    assert erros[20.48] / erros[5.12] == pytest.approx(4.0, rel=0.1)
    assert erros[20.48] / erros[10.24] == pytest.approx(2.0, rel=0.1)
    assert erros[5.12] == pytest.approx(5.12 / 65536 / np.sqrt(12), rel=0.1)       # = LSB/√12


# --------------------------------------------------------------------------------------
# gerar_perfil_sonda: processar_captura e o bloco calibracao_adc do JSON
# --------------------------------------------------------------------------------------
PARAMS = dict(tolerancia_pct=10.0, nome_janela="flattop", resolucao_hz=100.0, sobreposicao=0.75)


def ponto(caminho, faixa_texto=None, **extra):
    return processar_captura(caminho, 1000.0, "amplitude", None, 3, "uint16", faixa_texto, "1.0", None, **PARAMS, **extra)


def test_processar_captura_mede_a_amplitude_certa_em_qualquer_faixa(tmp_path):
    for total_v in (20.48, 10.24, 5.12):
        p = escrever_bin(tmp_path / f"c_{total_v}.bin", [senoide(0.2)], (3,), (1,), ("x",), fs_total=int(FS),
                         faixas_adc_total_v=total_v)
        pt = ponto(p)
        assert pt is not None
        assert pt.amplitude_sonda == pytest.approx(0.2, rel=2e-3)
        assert pt.faixa_sonda == total_v and pt.faixas_confiaveis == (False, True)


def test_processar_captura_v2_assume_a_faixa_de_reset_e_nao_e_confiavel(tmp_path):
    p = escrever_bin(tmp_path / "v2.bin", [senoide(0.2)], (3,), (1,), ("x",), fs_total=int(FS))
    pt = ponto(p)
    assert pt.amplitude_sonda == pytest.approx(0.2, rel=2e-3)
    assert pt.faixa_sonda == 20.48 and pt.faixas_confiaveis == (False, False)


def test_gerar_perfil_registra_a_faixa_e_se_ela_e_confiavel(tmp_path):
    from types import SimpleNamespace

    from supraharmonicos.calibracao_sonda import PontoPerfil
    from supraharmonicos.cli_gerar_perfil import _resumir_faixas
    from supraharmonicos.escrita_perfil import montar_perfil_json

    pts = []
    for total_v in (5.12, 10.24):
        p = escrever_bin(tmp_path / f"c_{total_v}.bin", [senoide(0.2)], (3,), (1,), ("x",), fs_total=int(FS),
                         faixas_adc_total_v=total_v)
        pts.append(ponto(p))
    resumo = _resumir_faixas(pts)
    assert resumo["sonda"] == 5.12 and resumo["sonda_confiavel"] is True      # a 1ª captura; todas confiáveis
    args = SimpleNamespace(
        id="s", data_calibracao="2026-10-19", fabricante=None, modelo=None, numero_serie=None, tipo_saida=None,
        incerteza_estimada_pct=None, faixa_freq_valida=None, calibrado_com=None, faixa=None, ganho="1.0", formato="uint16",
        modo_referencia="amplitude", resistencia_shunt=None, faixas_resumo=resumo)
    perfil = montar_perfil_json([PontoPerfil(freq_hz=1000.0, ganho=1.0, n_amostras=2, desvio_pct=0.0)], args)
    cal = perfil["calibracao_adc"]
    assert cal["faixa_v"]["sonda"] == 5.12 and cal["faixa_v_confiavel"]["sonda"] is True
    json.dumps(perfil)                                                           # serializável


def perfil_com(calibracao_adc: dict) -> PerfilSonda:
    return PerfilSonda("s", "resposta_frequencia", Path("s.json"), np.array([100.0, 1000.0]), np.array([1.0, 1.0]),
                       calibracao_adc=calibracao_adc)


def test_perfil_gerado_com_faixa_real_nao_acusa_faixa_diferente_na_producao(caplog):
    """Perfil medido em ±2,56 V e usado numa captura em ±10,24 V: ambos em Volts reais do pino -> sem alarme."""
    perfil = perfil_com({"formato": "uint16", "faixa_v": {"sonda": 5.12}, "ganho": {"sonda": 1.0},
                         "faixa_v_confiavel": {"sonda": True}})
    with caplog.at_level(logging.WARNING):
        conferir_calibracao_perfil(perfil, 1, "uint16", 20.48, 1.0, faixa_confiavel=True)
    assert not caplog.records


def test_perfil_antigo_ou_faixa_digitada_continua_avisando_da_diferenca(caplog):
    perfil = perfil_com({"formato": "uint16", "faixa_v": {"sonda": 10.24}, "ganho": {"sonda": 1.0}})
    with caplog.at_level(logging.WARNING):
        conferir_calibracao_perfil(perfil, 1, "uint16", 20.48, 1.0, faixa_confiavel=True)   # perfil sem 'faixa_v_confiavel'
        conferir_calibracao_perfil(perfil, 1, "uint16", 20.48, 1.0)                          # produção com --faixa digitada
    assert sum("--faixa do canal" in r.getMessage() for r in caplog.records) == 2
