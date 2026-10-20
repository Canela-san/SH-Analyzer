"""Perfis de sonda: carga/validação do JSON, interpolação, id seguro e correção em frequência."""

import json
import logging

import numpy as np
import pytest
from capturas_sinteticas import planta_h
from supraharmonicos.erros import ErroSHAN
from supraharmonicos.sonda import (
    PerfilSonda,
    aplicar_correcao_sonda,
    carregar_perfil_sonda,
    conferir_calibracao_perfil,
    resolver_perfil_canal,
)

FREQS = np.array([100, 150, 220, 330, 470, 680, 1000, 1500, 2200, 3300, 4700, 6800,
                  10000, 15000, 22000, 33000, 47000, 68000, 80000], dtype=float)


def escrever_perfil(caminho, **extra):
    d = {"id": caminho.stem, "tipo": "resposta_frequencia",
         "pontos": [{"freq_hz": float(f), "ganho": float(planta_h(f))} for f in FREQS]}
    d.update(extra)
    caminho.write_text(json.dumps(d), encoding="utf-8")   # json.dumps escreve NaN/Infinity se pedido
    return caminho


class TestCarregarPerfil:
    def test_perfil_valido_interpola_exatamente_nos_pontos(self, tmp_path):
        perfil = carregar_perfil_sonda(escrever_perfil(tmp_path / "ok.json"))
        np.testing.assert_allclose(perfil.ganho_em(FREQS), planta_h(FREQS), rtol=1e-9)

    def test_interpolacao_entre_pontos_fica_dentro_de_0_2_por_cento(self, tmp_path):
        perfil = carregar_perfil_sonda(escrever_perfil(tmp_path / "ok.json"))
        f = np.geomspace(120, 75_000, 400)
        assert np.abs(perfil.ganho_em(f) / planta_h(f) - 1).max() < 2e-3

    def test_fora_da_faixa_o_ganho_e_mantido_constante_nao_extrapolado(self, tmp_path):
        perfil = carregar_perfil_sonda(escrever_perfil(tmp_path / "ok.json"))
        g = perfil.ganho_em(np.array([0.0, 10.0, 99_999.0]))
        assert g[0] == g[1] == pytest.approx(planta_h(100.0))
        assert g[2] == pytest.approx(planta_h(80_000.0))

    def test_aviso_fora_da_faixa_sai_uma_unica_vez(self, tmp_path, caplog):
        perfil = carregar_perfil_sonda(escrever_perfil(tmp_path / "ok.json"))
        with caplog.at_level(logging.WARNING):
            perfil.ganho_em(np.array([50.0, 90_000.0]))
            perfil.ganho_em(np.array([50.0, 90_000.0]))
        assert len([r for r in caplog.records if "fora da faixa" in r.getMessage()]) == 1

    def test_dc_nao_dispara_o_aviso_de_faixa(self, tmp_path, caplog):
        perfil = carregar_perfil_sonda(escrever_perfil(tmp_path / "ok.json"))
        with caplog.at_level(logging.WARNING):
            perfil.ganho_em(np.array([0.0, 200.0, 5000.0]))
        assert not caplog.records

    def test_ganho_fixo(self, tmp_path):
        p = tmp_path / "fixo.json"
        p.write_text(json.dumps({"id": "fixo", "tipo": "ganho_fixo", "ganho": 0.5}), encoding="utf-8")
        np.testing.assert_allclose(carregar_perfil_sonda(p).ganho_em(np.array([0.0, 1e3, 1e5])), 0.5)

    @pytest.mark.parametrize("extra, trecho", [
        ({"pontos": [{"freq_hz": 100.0, "ganho": float("nan")}, {"freq_hz": 200.0, "ganho": 1.0}]}, "números finitos"),
        ({"pontos": [{"freq_hz": 100.0, "ganho": float("inf")}, {"freq_hz": 200.0, "ganho": 1.0}]}, "números finitos"),
        ({"pontos": [{"freq_hz": 0.0, "ganho": 1.0}, {"freq_hz": 200.0, "ganho": 1.0}]}, "precisa ser positivo"),
        ({"pontos": [{"freq_hz": 100.0, "ganho": -1.0}, {"freq_hz": 200.0, "ganho": 1.0}]}, "precisa ser positivo"),
        ({"pontos": [{"freq_hz": 100.0, "ganho": 1.0}, {"freq_hz": 100.0, "ganho": 1.1}]}, "repetida"),
        ({"faixa_freq_valida_hz": [5000, 500]}, "0 < min < max"),
        ({"faixa_freq_valida_hz": [500]}, "lista"),
        ({"tipo": "ganho_fixo"}, "precisa do campo 'ganho'"),
    ])
    def test_perfis_invalidos_dao_erro_limpo(self, tmp_path, extra, trecho):
        with pytest.raises(ErroSHAN, match=trecho):
            carregar_perfil_sonda(escrever_perfil(tmp_path / "ruim.json", **extra))

    def test_arquivo_inexistente_e_json_invalido(self, tmp_path):
        with pytest.raises(ErroSHAN, match="não encontrado"):
            carregar_perfil_sonda(tmp_path / "nada.json")
        p = tmp_path / "x.json"
        p.write_text("{nao é json", encoding="utf-8")
        with pytest.raises(ErroSHAN, match="não é um JSON válido"):
            carregar_perfil_sonda(p)


class TestResolverPerfilDoCanal:
    @pytest.mark.parametrize("sid", ["/etc/passwd", "../x", "a/b", "a\\b", "..", ".oculto", "x..y", "com espaço"])
    def test_id_inseguro_do_cabecalho_e_rejeitado(self, tmp_path, sid):
        with pytest.raises(ErroSHAN, match="nome de arquivo seguro"):
            resolver_perfil_canal(1, sid, {}, tmp_path)

    @pytest.mark.parametrize("sid", ["fluke_i30_01", "sonda-2", "i30s.v2"])
    def test_id_legitimo_passa_pela_validacao_e_cai_em_perfil_inexistente(self, tmp_path, sid):
        with pytest.raises(ErroSHAN, match="não existe um perfil"):
            resolver_perfil_canal(1, sid, {}, tmp_path)

    def test_id_do_cabecalho_resolve_para_sondas_dir(self, tmp_path):
        escrever_perfil(tmp_path / "minha_sonda.json")
        assert resolver_perfil_canal(1, "minha_sonda", {}, tmp_path).id == "minha_sonda"

    def test_sonda_perfil_explicito_tem_prioridade_e_pode_ficar_fora_de_sondas_dir(self, tmp_path):
        (tmp_path / "fora").mkdir()
        fora = escrever_perfil(tmp_path / "fora" / "x.json")
        # o id do cabeçalho seria recusado ('../'), mas o --sonda-perfil do operador vem antes e não é validado
        assert resolver_perfil_canal(1, "../ignorado", {1: fora}, tmp_path / "sondas").id == "x"

    def test_sem_id_e_sem_override_devolve_none(self, tmp_path):
        assert resolver_perfil_canal(1, "", {}, tmp_path) is None

    def test_id_divergente_do_arquivo_avisa(self, tmp_path, caplog):
        escrever_perfil(tmp_path / "a.json", id="OUTRA_9999")
        with caplog.at_level(logging.WARNING):
            resolver_perfil_canal(1, "a", {}, tmp_path)
        assert any("declara id='OUTRA_9999'" in r.getMessage() for r in caplog.records)


class TestCalibracaoDoPerfil:
    def perfil(self, tmp_path):
        cal = {"formato": "uint16", "faixa_v": {"referencia": 10.24, "sonda": 10.24}, "ganho": {"referencia": 1.0, "sonda": 10.0}}
        return carregar_perfil_sonda(escrever_perfil(tmp_path / "c.json", calibracao_adc=cal))

    def test_coerente_nao_avisa(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            conferir_calibracao_perfil(self.perfil(tmp_path), 1, "uint16", 10.24, 10.0)
        assert not caplog.records

    @pytest.mark.parametrize("formato, faixa, ganho, trecho", [
        ("uint16", 10.24, 1.0, "--ganho do canal = 1, mas o perfil foi gerado com 10"),
        ("uint16", 5.12, 10.0, "--faixa do canal = 5.12 V, mas o perfil foi gerado com 10.24"),
        ("int16", 10.24, 10.0, "--formato = int16, mas o perfil foi gerado com uint16"),
    ])
    def test_divergente_avisa(self, tmp_path, caplog, formato, faixa, ganho, trecho):
        with caplog.at_level(logging.WARNING):
            conferir_calibracao_perfil(self.perfil(tmp_path), 1, formato, faixa, ganho)
        assert any(trecho in r.getMessage() for r in caplog.records)


class TestCorrecaoEmFrequencia:
    FS = 200_000.0

    def sinal_e_verdade(self, tons):
        t = np.arange(int(self.FS * 1.0)) / self.FS
        rng = np.random.default_rng(0)
        medido = sum(a * planta_h(f) * np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) for f, a in tons)
        return medido

    def test_restaura_a_amplitude_de_cada_tom(self, tmp_path):
        perfil = carregar_perfil_sonda(escrever_perfil(tmp_path / "ok.json"))
        tons = [(2500.0, 0.2), (9000.0, 0.1), (20000.0, 0.1), (40000.0, 0.1)]
        corrigido = aplicar_correcao_sonda(self.sinal_e_verdade(tons), self.FS, perfil)
        espectro = np.abs(np.fft.rfft(corrigido)) * 2 / len(corrigido)
        freqs = np.fft.rfftfreq(len(corrigido), 1 / self.FS)
        for f, a in tons:
            assert espectro[np.argmin(np.abs(freqs - f))] == pytest.approx(a, rel=5e-3)

    def test_ganho_unitario_e_identidade_e_tamanho_quase_primo_e_preservado(self, tmp_path):
        p = tmp_path / "um.json"
        p.write_text(json.dumps({"id": "um", "tipo": "ganho_fixo", "ganho": 1.0}), encoding="utf-8")
        x = np.random.default_rng(1).normal(size=20_011)       # 20011 é primo: exercita next_fast_len
        y = aplicar_correcao_sonda(x, self.FS, carregar_perfil_sonda(p))
        assert y.shape == x.shape
        np.testing.assert_allclose(y, x, atol=1e-9)

    def test_avisa_quando_a_correcao_amplifica_muito_o_ruido(self, tmp_path, caplog):
        p = tmp_path / "forte.json"
        p.write_text(json.dumps({"id": "forte", "tipo": "resposta_frequencia", "pontos": [
            {"freq_hz": 100.0, "ganho": 1.0}, {"freq_hz": 50_000.0, "ganho": 0.01}]}), encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            aplicar_correcao_sonda(np.random.default_rng(2).normal(size=4096), self.FS, carregar_perfil_sonda(p))
        assert any("amplifica o ruído" in r.getMessage() for r in caplog.records)


def test_perfil_sonda_pode_ser_construido_direto_em_memoria(tmp_path, caplog):
    perfil = PerfilSonda(id="mem", tipo="resposta_frequencia", caminho=tmp_path / "mem.json",
                         pontos_freq_hz=np.array([100.0, 1000.0]), pontos_ganho=np.array([1.0, 0.5]))
    assert perfil.ganho_em(np.array([100.0]))[0] == pytest.approx(1.0)
    perfil.silenciar_aviso_fora_da_faixa()
    with caplog.at_level(logging.WARNING):
        perfil.ganho_em(np.array([10.0, 5000.0]))          # fora da faixa, mas o aviso foi silenciado
    assert not caplog.records
