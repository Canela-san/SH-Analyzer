"""Núcleo do gerador de perfis: medir tom, resolver canais, agregar repetições e CLI."""

import json
import logging
import re

import numpy as np
import pytest
from capturas_sinteticas import (
    R_SHUNT,
    captura_calibracao,
    criar_pasta_amplitude_conhecida,
    criar_pasta_calibracao,
    criar_pasta_calibracao_1canal,
    escrever_bin,
    passa_baixa_2a_ordem,
    planta_h,
)
from supraharmonicos.cabecalho import ler_cabecalho
from supraharmonicos.calibracao_sonda import (
    PontoMedido,
    PontoPerfil,
    agregar_por_frequencia,
    descobrir_capturas,
    identificar_captura,
    ler_referencia_externa,
    medir_tom,
    resolucao_efetiva_hz,
    resolver_canais,
    resumir_resposta,
)
from supraharmonicos.cli_gerar_perfil import main
from supraharmonicos.erros import ErroSHAN

FS = 200_000.0


class TestMedirTom:
    def test_mede_frequencia_e_amplitude_reais_fora_da_nominal(self):
        t = np.arange(int(FS * 0.5)) / FS
        x = 0.37 * np.sin(2 * np.pi * 4_713.0 * t) + np.random.default_rng(0).normal(0, 5e-4, len(t))
        f, a = medir_tom(x, FS, 4_700.0, 10.0, "flattop", 100.0, 0.75)
        assert f == pytest.approx(4_713.0, abs=0.5)
        assert a == pytest.approx(0.37, rel=1e-3)

    @pytest.mark.parametrize("freq", [1_176.0, 9_659.0, 13_719.0, 55_838.0, 112_648.0])
    def test_amplitude_exata_qualquer_que_seja_a_posicao_do_tom_no_bin(self, freq):
        """O Welch de 100 Hz + parabólica sobre a flat-top errava até ~1,8 % de amplitude e ~14 Hz de
        frequência com o tom fora do centro do bin; o refinamento por FFT única remove esse erro."""
        fs = 400_000.0
        t = np.arange(int(fs * 1.0)) / fs
        x = 1.0 * np.sin(2 * np.pi * freq * t + 0.7) + np.random.default_rng(2).normal(0, 1.5e-4, len(t))
        f, a = medir_tom(x, fs, freq * 1.03, 10.0, "flattop", 100.0, 0.75)
        assert f == pytest.approx(freq, abs=0.5)
        assert a == pytest.approx(1.0, rel=5e-4)

    def test_captura_curta_ou_tom_perto_do_dc_cai_na_estimativa_do_welch(self):
        """Com poucos bins entre DC e o tom o refinamento por FFT única não vale: usa o Welch (e não falha)."""
        t = np.arange(20_000) / FS
        x = 0.5 * np.sin(2 * np.pi * 100.0 * t) + np.random.default_rng(3).normal(0, 5e-4, len(t))
        resultado = medir_tom(x, FS, 100.0, 10.0, "flattop", 100.0, 0.75)
        assert resultado is not None
        f, a = resultado
        assert f == pytest.approx(100.0, rel=0.05)
        assert a == pytest.approx(0.5, rel=0.05)

    def test_so_ruido_nao_vira_ponto(self):
        x = np.random.default_rng(1).normal(0, 5e-4, int(FS * 0.5))
        assert medir_tom(x, FS, 4_700.0, 10.0, "flattop", 100.0, 0.75) is None

    def test_resolucao_so_afina_nunca_engrossa(self):
        assert resolucao_efetiva_hz(60.0, 100.0) == pytest.approx(6.0)
        assert resolucao_efetiva_hz(50_000.0, 100.0) == 100.0
        assert resolucao_efetiva_hz(5.0, 100.0) == 1.0


class TestResolverCanais:
    def test_flags_explicitas_tem_prioridade(self):
        assert resolver_canais(None, 3, 5) == (3, 5)

    def test_deteccao_automatica_pelo_cabecalho_v2(self, tmp_path):
        vr, vs = captura_calibracao(1000.0, seed=1, dur_s=0.05)
        p = escrever_bin(tmp_path / "a.bin", [vr, vs], (2, 5), (0, 1), ("", "x"))
        assert resolver_canais(ler_cabecalho(p), None, None) == (2, 5)

    def test_sem_cabecalho_v2_exige_flags(self, tmp_path):
        vr, vs = captura_calibracao(1000.0, seed=1, dur_s=0.05)
        p = escrever_bin(tmp_path / "v1.bin", [vr, vs], versao=1)
        with pytest.raises(ErroSHAN, match="informe --canal-referencia e --canal-sonda"):
            resolver_canais(ler_cabecalho(p), None, None)

    def test_tres_canais_exigem_flags(self, tmp_path):
        v = np.zeros(100)
        p = escrever_bin(tmp_path / "3.bin", [v, v, v], (0, 1, 2), (0, 0, 1), ("", "", "x"), fs_total=600_000)
        with pytest.raises(ErroSHAN, match="exatamente 2"):
            resolver_canais(ler_cabecalho(p), None, None)


class TestResolverCanaisSemReferencia:
    """Modos 'fixa'/'externa': o canal de referência não é lido; a captura pode ter 1 canal só."""

    def test_um_canal_no_cabecalho_e_a_sonda(self, tmp_path):
        _, vs = captura_calibracao(1000.0, seed=1, dur_s=0.05)
        p = escrever_bin(tmp_path / "um.bin", [vs], (3,), (1,), ("x",))
        assert resolver_canais(ler_cabecalho(p), None, None, exige_referencia=False) == (None, 3)

    def test_flag_de_sonda_vence_a_deteccao(self, tmp_path):
        _, vs = captura_calibracao(1000.0, seed=1, dur_s=0.05)
        p = escrever_bin(tmp_path / "um.bin", [vs], (3,), (1,), ("x",))
        assert resolver_canais(ler_cabecalho(p), None, 3, exige_referencia=False) == (None, 3)

    def test_dois_canais_acham_a_sonda_pela_grandeza(self, tmp_path):
        vr, vs = captura_calibracao(1000.0, seed=1, dur_s=0.05)
        p = escrever_bin(tmp_path / "dois.bin", [vr, vs], (2, 5), (0, 1), ("", "x"))
        assert resolver_canais(ler_cabecalho(p), None, None, exige_referencia=False) == (None, 5)

    def test_varios_canais_sem_corrente_exigem_a_flag(self, tmp_path):
        v = np.zeros(100)
        p = escrever_bin(tmp_path / "3.bin", [v, v, v], (0, 1, 2), (0, 0, 0), ("", "", ""), fs_total=600_000)
        with pytest.raises(ErroSHAN, match="informe --canal-sonda"):
            resolver_canais(ler_cabecalho(p), None, None, exige_referencia=False)

    def test_sem_cabecalho_v2_exige_a_flag(self, tmp_path):
        _, vs = captura_calibracao(1000.0, seed=1, dur_s=0.05)
        p = escrever_bin(tmp_path / "v1.bin", [vs], (0,), versao=1)
        with pytest.raises(ErroSHAN, match="informe --canal-sonda"):
            resolver_canais(ler_cabecalho(p), None, None, exige_referencia=False)


class TestReferenciaExterna:
    def escrever(self, tmp_path, texto):
        p = tmp_path / "referencia_externa.csv"
        p.write_text(texto, encoding="utf-8")
        return p

    def test_tensao_no_shunt_vira_corrente_rms(self, tmp_path):
        p = self.escrever(tmp_path, "arquivo,v_shunt_rms_V\ncalibracao_100Hz_rep1.bin,0.2\n")
        assert ler_referencia_externa(p, 0.5) == {"calibracao_100Hz_rep1.bin": pytest.approx(0.4)}

    def test_corrente_direta_dispensa_o_shunt(self, tmp_path):
        p = self.escrever(tmp_path, "arquivo,corrente_rms_A\na.bin,0.25\n")
        assert ler_referencia_externa(p, None) == {"a.bin": 0.25}

    def test_ultima_linha_vale_e_comentarios_e_vazias_sao_ignorados(self, tmp_path):
        p = self.escrever(tmp_path, "# leituras\narquivo,v_shunt_rms_V\n\na.bin,0.1\nb.bin,\na.bin,0.3\n")
        assert ler_referencia_externa(p, 1.0) == {"a.bin": 0.3}   # b.bin sem valor = sem leitura

    def test_linha_sem_valor_anula_a_leitura_anterior(self, tmp_path):
        p = self.escrever(tmp_path, "arquivo,v_shunt_rms_V\na.bin,0.1\nb.bin,0.2\na.bin,\n")
        assert ler_referencia_externa(p, 1.0) == {"b.bin": 0.2}

    def test_planilha_ptbr_ponto_e_virgula_e_virgula_decimal(self, tmp_path):
        p = self.escrever(tmp_path, "arquivo;v_shunt_rms_V\na.bin;0,125\n")
        assert ler_referencia_externa(p, 1.0) == {"a.bin": pytest.approx(0.125)}

    @pytest.mark.parametrize("texto,trecho", [
        ("arquivo,v_shunt_rms_V\na.bin,abc\n", "não é um número"),
        ("arquivo,v_shunt_rms_V\na.bin,-1\n", "número positivo"),
        ("arquivo,v_shunt_rms_V\na.bin,0\n", "número positivo"),
        ("arquivo,v_shunt_rms_V\na.bin,nan\n", "número positivo"),
        ("nome,v_shunt_rms_V\na.bin,1\n", "coluna 'arquivo'"),
        ("arquivo,outra\na.bin,1\n", "v_shunt_rms_V"),
        ("# só comentário\n", "vazio"),
    ])
    def test_conteudo_invalido_e_erro_claro(self, tmp_path, texto, trecho):
        with pytest.raises(ErroSHAN, match=trecho):
            ler_referencia_externa(self.escrever(tmp_path, texto), 1.0)

    def test_tensao_sem_resistencia_e_erro(self, tmp_path):
        with pytest.raises(ErroSHAN, match="--resistencia-shunt"):
            ler_referencia_externa(self.escrever(tmp_path, "arquivo,v_shunt_rms_V\na.bin,1\n"), None)

    def test_arquivo_inexistente_e_erro(self, tmp_path):
        with pytest.raises(ErroSHAN, match="não encontrei"):
            ler_referencia_externa(tmp_path / "nao_existe.csv", 1.0)


class TestAgregacao:
    def pontos(self, ganhos_e_freqs, alvo=1000.0):
        return [PontoMedido(arquivo=__import__("pathlib").Path(f"calibracao_{int(alvo)}Hz_rep{i}.bin"), freq_alvo_hz=alvo,
                            freq_medida_hz=f, amplitude_sonda=g * 1.0, amplitude_referencia=1.0 * R_SHUNT)
                for i, (g, f) in enumerate(ganhos_e_freqs, 1)]

    def test_media_das_repeticoes_do_mesmo_alvo(self):
        [p] = agregar_por_frequencia(self.pontos([(0.50, 990.0), (0.52, 1010.0)]), "shunt", R_SHUNT)
        assert p.n_amostras == 2 and p.ganho == pytest.approx(0.51) and p.freq_hz == pytest.approx(1000.0)
        assert p.desvio_pct == pytest.approx(np.std([0.50, 0.52], ddof=1) / 0.51 * 100)

    def test_repeticoes_discordantes_avisam(self, caplog):
        with caplog.at_level(logging.WARNING):
            agregar_por_frequencia(self.pontos([(0.5, 1000.0), (0.8, 1000.0)]), "shunt", R_SHUNT)
        assert any("discordam" in r.getMessage() for r in caplog.records)

    @pytest.mark.parametrize("modo", ["externa", "amplitude", "osciloscopio"])
    def test_modos_de_um_canal_usam_a_referencia_de_cada_ponto(self, modo):
        pts = self.pontos([(0.5, 1000.0)])
        pts[0].referencia_pico = 2.0
        [p] = agregar_por_frequencia(pts, modo, None)
        assert p.ganho == pytest.approx(0.25)

    @pytest.mark.parametrize("modo", ["externa", "amplitude", "osciloscopio"])
    def test_modos_de_um_canal_sem_referencia_descartam_o_ponto(self, modo):
        assert agregar_por_frequencia(self.pontos([(0.5, 1000.0)]), modo, None) == []

    def test_cada_ponto_tem_a_sua_amplitude_injetada(self):
        """Gerador com a amplitude ajustada a cada frequência: o ganho sai de cada referência, não de uma média."""
        pts = self.pontos([(0.5, 1000.0), (0.5, 1000.0)])
        pts[0].referencia_pico, pts[1].referencia_pico = 1.0, 0.5
        [p] = agregar_por_frequencia(pts, "amplitude", None)
        assert p.n_amostras == 2 and p.ganho == pytest.approx((0.5 + 1.0) / 2)


def test_descobrir_capturas_filtra_pelo_padrao_de_nome(tmp_path):
    for nome in ["calibracao_100Hz_rep1.bin", "calibracao_100Hz_rep2_v2.bin", "outra.bin", "calibracao_x.bin"]:
        (tmp_path / nome).write_bytes(b"")
    assert [p.name for p in descobrir_capturas(tmp_path)] == ["calibracao_100Hz_rep1.bin", "calibracao_100Hz_rep2_v2.bin"]
    with pytest.raises(ErroSHAN, match="nenhum arquivo"):
        descobrir_capturas(tmp_path / "vazia") if (tmp_path / "vazia").mkdir() is None else None
    with pytest.raises(ErroSHAN, match="não é uma pasta"):
        descobrir_capturas(tmp_path / "nao_existe")


@pytest.fixture(scope="module")
def pasta(tmp_path_factory):
    return criar_pasta_calibracao(tmp_path_factory.mktemp("cal") / "sonda_teste", freqs=[1000, 5000, 20000], reps=1)


class TestCli:
    def test_gera_perfil_valido_que_recupera_a_planta(self, cli, pasta, tmp_path):
        saida = tmp_path / "perfil.json"
        rc, out, err = cli(main, pasta, "--resistencia-shunt", R_SHUNT, "--ganho", "1,10", "-o", saida)
        assert rc == 0, err
        d = json.loads(saida.read_text(encoding="utf-8"))
        assert d["id"] == "sonda_teste" and d["calibracao_adc"]["ganho"]["sonda"] == 10.0
        for p in d["pontos"]:
            assert p["ganho"] == pytest.approx(float(planta_h(p["freq_hz"])), rel=2e-3)
        assert "Perfil salvo em" in out and "Validação: perfil recarregado" in out

    def test_resistencia_invalida_e_erro_de_uso(self, cli, pasta, tmp_path):
        rc, _, err = cli(main, pasta, "--resistencia-shunt", 0, "-o", tmp_path / "p.json")
        assert rc == 2 and "--resistencia-shunt precisa ser positiva" in err

    def test_pasta_vazia_e_erro_de_dominio(self, cli, tmp_path):
        (tmp_path / "vazia").mkdir()
        rc, _, err = cli(main, tmp_path / "vazia", "--resistencia-shunt", R_SHUNT, "-o", tmp_path / "p.json")
        assert rc == 1 and err.startswith("Erro: nenhum arquivo 'calibracao_<FREQ>Hz_rep<N>.bin'")

    def test_arquivo_ruim_e_pulado_com_aviso_sem_prefixo_duplicado(self, cli, pasta, tmp_path):
        copia = tmp_path / "cal"
        copia.mkdir()
        for p in pasta.glob("*.bin"):
            (copia / p.name).write_bytes(p.read_bytes())
        (copia / "calibracao_3000Hz_rep1.bin").write_bytes(b"\x00" * 7)          # lixo
        rc, out, err = cli(main, copia, "--resistencia-shunt", R_SHUNT, "--ganho", "1,10", "--id", "x", "-o", tmp_path / "p.json")
        assert rc == 0
        assert "Aviso: pulando 'calibracao_3000Hz_rep1.bin' --" in err and "Erro:" not in err


@pytest.fixture(scope="module")
def pasta_1canal(tmp_path_factory):
    return criar_pasta_calibracao_1canal(tmp_path_factory.mktemp("cal1") / "sonda_teste", freqs=[1000, 5000, 20000, 80000])


class TestCliUmCanal:
    """Captura de 1 canal (só a sonda): Nyquist efetiva = taxa total / 2; corrente real por fora."""

    def test_referencia_externa_recupera_a_planta(self, cli, pasta_1canal, tmp_path):
        saida = tmp_path / "perfil.json"
        rc, out, err = cli(main, pasta_1canal, "--referencia-externa", "--resistencia-shunt", R_SHUNT,
                           "--ganho", "10", "-o", saida)
        assert rc == 0, err
        d = json.loads(saida.read_text(encoding="utf-8"))
        assert d["calibracao_adc"]["modo_referencia"] == "externa" and d["calibracao_adc"]["resistencia_shunt_ohms"] == R_SHUNT
        assert [p["freq_hz"] for p in d["pontos"]] == pytest.approx([1000, 5000, 20000, 80000], rel=5e-3)
        for p in d["pontos"]:
            assert p["ganho"] == pytest.approx(float(planta_h(p["freq_hz"])), rel=2e-3)

    def test_corrente_constante_tambem_funciona_com_um_canal(self, cli, pasta_1canal, tmp_path):
        saida = tmp_path / "perfil.json"
        rc, _, err = cli(main, pasta_1canal, "--amplitude-referencia", "1.0", "--ganho", "10", "-o", saida)
        assert rc == 0, err
        d = json.loads(saida.read_text(encoding="utf-8"))
        assert d["calibracao_adc"]["modo_referencia"] == "amplitude"
        assert d["calibracao_adc"]["referencia"] == {"origem": "constante", "amplitudes": ["1.0"]}
        assert d["pontos"][-1]["ganho"] == pytest.approx(float(planta_h(d["pontos"][-1]["freq_hz"])), rel=2e-3)

    def test_csv_em_outro_caminho_e_em_corrente(self, cli, pasta_1canal, tmp_path):
        csv_a = tmp_path / "scope.csv"
        linhas = ["arquivo,corrente_rms_A"] + [f"{p.name},{1 / np.sqrt(2):.6f}" for p in sorted(pasta_1canal.glob("*.bin"))]
        csv_a.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        rc, _, err = cli(main, pasta_1canal, "--referencia-externa", csv_a, "--ganho", "10", "-o", tmp_path / "p.json")
        assert rc == 0, err

    def test_ponto_sem_leitura_e_pulado_com_aviso(self, cli, pasta_1canal, tmp_path):
        copia = tmp_path / "cal"
        copia.mkdir()
        for p in pasta_1canal.glob("*"):
            (copia / p.name).write_bytes(p.read_bytes())
        linhas = (copia / "referencia_externa.csv").read_text().splitlines()
        (copia / "referencia_externa.csv").write_text("\n".join(ln for ln in linhas if "5000Hz" not in ln) + "\n")
        rc, _, err = cli(main, copia, "--referencia-externa", "--resistencia-shunt", R_SHUNT, "--ganho", "10",
                         "--id", "x", "-o", tmp_path / "p.json")
        assert rc == 0
        assert "pulando 'calibracao_5000Hz_rep1.bin' -- sem leitura do instrumento externo" in err

    def test_modo_shunt_pula_captura_de_um_canal(self, cli, pasta_1canal, tmp_path):
        rc, _, err = cli(main, pasta_1canal, "--resistencia-shunt", R_SHUNT, "--ganho", "10", "-o", tmp_path / "p.json")
        assert rc == 1 and "esperado exatamente 2" in err and "só 0 ponto(s)" in err

    def test_sem_nenhuma_referencia_e_erro_de_uso(self, cli, pasta_1canal, tmp_path):
        rc, _, err = cli(main, pasta_1canal, "-o", tmp_path / "p.json")
        assert rc == 2 and "informe a referência da grandeza injetada" in err and "ref: amp=" in err

    def test_referencias_incompativeis_sao_erro_de_uso(self, cli, pasta_1canal, tmp_path):
        rc, _, err = cli(main, pasta_1canal, "--referencia-externa", "--amplitude-referencia", "1", "-o", tmp_path / "p.json")
        assert rc == 2 and "não podem ser combinados" in err
        rc, _, err = cli(main, pasta_1canal, "--resistencia-shunt", "0.1", "--amplitude-referencia", "1", "-o", tmp_path / "p.json")
        assert rc == 2 and "não pode ser combinado" in err

    def test_csv_ausente_e_erro_de_dominio(self, cli, tmp_path):
        pasta = criar_pasta_calibracao_1canal(tmp_path / "s", freqs=[1000, 5000], com_referencia_externa=False)
        rc, _, err = cli(main, pasta, "--referencia-externa", "--resistencia-shunt", R_SHUNT, "-o", tmp_path / "p.json")
        assert rc == 1 and "não encontrei o arquivo de referência externa" in err


# ---------------------------------------------------------------------------
# Amplitude conhecida (metadados / constante) e osciloscópio: o conjunto "sonda" medido de ponta a ponta
# ---------------------------------------------------------------------------

FREQS_CONJUNTO = [100, 220, 470, 1000, 2200, 4700, 10000, 15000, 22000, 33000, 47000, 68000, 80000]


def esperado(freq_hz, fc=15e3):
    return passa_baixa_2a_ordem(freq_hz, fc)


def ler_json(caminho):
    return json.loads(caminho.read_text(encoding="utf-8"))


class TestIdentificarCaptura:
    def test_metadado_vence_o_nome_e_aceita_nome_livre(self, tmp_path):
        pasta = criar_pasta_amplitude_conhecida(tmp_path / "s", freqs=[1000, 5000], nomes_livres=True)
        assert [p.name for p in descobrir_capturas(pasta)] == ["medicao_00.bin", "medicao_01.bin"]
        assert identificar_captura(pasta / "medicao_01.bin")[0] == 5000.0
        freq, ref = identificar_captura(pasta / "medicao_00.bin")
        assert freq == 1000.0 and ref.amplitude.texto == "500mVpp"

    def test_sem_metadado_cai_no_nome_do_arquivo(self, tmp_path):
        pasta = criar_pasta_amplitude_conhecida(tmp_path / "s", freqs=[1000], metadados=False)
        assert identificar_captura(pasta / "calibracao_1000Hz_rep1.bin") == (1000.0, None)

    def test_metadado_ilegivel_vale_como_ausente_com_aviso(self, tmp_path, caplog):
        pasta = tmp_path / "s"
        pasta.mkdir()
        escrever_bin(pasta / "calibracao_1000Hz_rep1.bin", [np.zeros(1000)], (3,), (1,), ("x",), fs_total=200_000,
                     descricao="ref: f=1000Hz amp=500mV")
        with caplog.at_level(logging.WARNING):
            assert identificar_captura(pasta / "calibracao_1000Hz_rep1.bin") == (1000.0, None)
        assert any("ilegíveis" in r.getMessage() for r in caplog.records)

    def test_bin_sem_metadado_e_sem_nome_do_padrao_nao_e_captura(self, tmp_path):
        pasta = criar_pasta_amplitude_conhecida(tmp_path / "s", freqs=[1000], metadados=False)
        (pasta / "outro.bin").write_bytes((pasta / "calibracao_1000Hz_rep1.bin").read_bytes())
        assert [p.name for p in descobrir_capturas(pasta)] == ["calibracao_1000Hz_rep1.bin"]


class TestResumoDaResposta:
    def pontos(self, freqs, fc=15e3):
        return [PontoPerfil(f, float(esperado(f, fc)), 1, 0.0) for f in freqs]

    def test_acha_a_queda_de_3_db_e_a_inclinacao_de_um_passa_baixa_de_2a_ordem(self):
        r = resumir_resposta(self.pontos(FREQS_CONJUNTO))
        assert r.freq_menos3db_hz == pytest.approx(15e3, rel=0.05)
        assert r.inclinacao_db_oitava == pytest.approx(-12.0, abs=0.5)
        assert r.ganho_baixa_frequencia == pytest.approx(1.0, abs=1e-3)
        assert r.ganho_final_db == pytest.approx(20 * np.log10(esperado(80000)), abs=0.05)

    def test_passa_baixa_de_primeira_ordem_da_6_db_por_oitava(self):
        pts = [PontoPerfil(f, float(planta_h(f, 30e3, 1e-3)), 1, 0.0) for f in FREQS_CONJUNTO + [120000, 160000]]
        r = resumir_resposta(pts)
        assert r.freq_menos3db_hz == pytest.approx(30e3, rel=0.06) and r.inclinacao_db_oitava == pytest.approx(-6.0, abs=0.7)

    def test_resposta_plana_nao_tem_queda(self):
        r = resumir_resposta([PontoPerfil(f, 0.98, 1, 0.0) for f in (100, 1000, 10000, 50000)])
        assert r.freq_menos3db_hz is None and r.inclinacao_db_oitava is None and r.ganho_final_db == pytest.approx(0.0)

    def test_poucos_pontos_nao_resumem(self):
        assert resumir_resposta(self.pontos([100, 1000])) is None


@pytest.fixture(scope="module")
def pasta_meta(tmp_path_factory):
    return criar_pasta_amplitude_conhecida(tmp_path_factory.mktemp("amp") / "sonda_teste", freqs=FREQS_CONJUNTO)


@pytest.fixture(scope="module")
def pasta_osc(tmp_path_factory):
    """O gerador entrega 2 % menos que o mostrador (500 mVpp): só o osciloscópio vê isso."""
    return criar_pasta_amplitude_conhecida(tmp_path_factory.mktemp("osc") / "sonda_teste", freqs=FREQS_OSC,
                                           erro_gerador=0.98, osciloscopio=True)


FREQS_OSC = [100, 470, 1000, 4700, 15000, 33000, 80000]


class TestCliAmplitudeConhecida:
    """O sinal injetado é uma senoide pura de amplitude conhecida; o perfil sai de ganho = medido / injetado."""

    def conferir_planta(self, d, rel=3e-3):
        for p in d["pontos"]:
            assert p["ganho"] == pytest.approx(float(esperado(p["freq_hz"])), rel=rel), p

    def test_modo_automatico_le_a_amplitude_dos_metadados(self, cli, pasta_meta, tmp_path):
        saida = tmp_path / "p.json"
        rc, out, err = cli(main, pasta_meta, "-o", saida)
        assert rc == 0, err
        d = ler_json(saida)
        assert d["calibracao_adc"]["modo_referencia"] == "amplitude"
        assert d["calibracao_adc"]["referencia"] == {"origem": "metadados", "amplitudes": ["500mVpp"]}
        assert "gravada nos metadados de 13 das 13" in out
        self.conferir_planta(d)

    def test_resumo_do_conjunto_no_log_e_no_json(self, cli, pasta_meta, tmp_path):
        saida = tmp_path / "p.json"
        rc, out, err = cli(main, pasta_meta, "-o", saida)
        resumo = ler_json(saida)["calibracao_adc"]["resposta_conjunto"]
        assert resumo["freq_menos3db_hz"] == pytest.approx(15e3, rel=0.05)
        assert resumo["inclinacao_db_por_oitava"] == pytest.approx(-12.0, abs=0.7)
        assert "queda de 3 dB em ~" in out and "dB/oitava" in out and "amplifica" in out

    def test_o_ganho_nao_depende_do_ganho_do_canal_quando_a_amplitude_e_em_volts(self, cli, pasta_meta, tmp_path):
        """V é a tensão no ponto onde o --ganho é aplicado: a grandeza física verdadeira é V * ganho, e o ganho do perfil é o mesmo."""
        saida = tmp_path / "p.json"
        rc, _, err = cli(main, pasta_meta, "--ganho", "10", "-o", saida)
        assert rc == 0, err
        self.conferir_planta(ler_json(saida))

    def test_constante_na_linha_de_comando_funciona_sem_metadados(self, cli, tmp_path):
        pasta = criar_pasta_amplitude_conhecida(tmp_path / "s", freqs=FREQS_CONJUNTO, metadados=False)
        saida = tmp_path / "p.json"
        rc, _, err = cli(main, pasta, "--amplitude-referencia", "500mVpp", "-o", saida)
        assert rc == 0, err
        d = ler_json(saida)
        assert d["calibracao_adc"]["referencia"] == {"origem": "constante", "amplitudes": ["500mVpp"]}
        self.conferir_planta(d)

    def test_nomes_livres_com_a_frequencia_nos_metadados(self, cli, tmp_path):
        pasta = criar_pasta_amplitude_conhecida(tmp_path / "s", freqs=FREQS_CONJUNTO, nomes_livres=True)
        rc, _, err = cli(main, pasta, "--id", "x", "-o", tmp_path / "p.json")
        assert rc == 0, err
        self.conferir_planta(ler_json(tmp_path / "p.json"))

    def test_amplitude_diferente_a_cada_ponto(self, cli, tmp_path):
        """O gerador tem a amplitude regulada a cada frequência; cada captura usa a sua."""
        pasta = criar_pasta_amplitude_conhecida(tmp_path / "s", freqs=FREQS_CONJUNTO,
                                                amplitudes=lambda f: "1Vpp" if f < 1000 else ("400mVrms" if f < 20000 else "250mVpk"))
        rc, _, err = cli(main, pasta, "-o", tmp_path / "p.json")
        assert rc == 0, err
        d = ler_json(tmp_path / "p.json")
        assert d["calibracao_adc"]["referencia"]["amplitudes"] == ["1Vpp", "250mVpk", "400mVrms"]
        self.conferir_planta(d)

    def test_a_constante_vence_os_metadados_e_avisa(self, cli, pasta_meta, tmp_path):
        rc, _, err = cli(main, pasta_meta, "--amplitude-referencia", "400mVpp", "-o", tmp_path / "p.json")
        assert rc == 0
        assert "os metadados dizem 500mVpp, mas --amplitude-referencia 400mVpp vale" in err
        assert ler_json(tmp_path / "p.json")["pontos"][0]["ganho"] == pytest.approx(float(esperado(100)) * 1.25, rel=3e-3)

    def test_captura_sem_amplitude_e_pulada_com_aviso(self, cli, tmp_path):
        pasta = criar_pasta_amplitude_conhecida(tmp_path / "s", freqs=FREQS_CONJUNTO)
        sem = criar_pasta_amplitude_conhecida(tmp_path / "t", freqs=[3300], metadados=False)
        (pasta / "calibracao_3300Hz_rep1.bin").write_bytes((sem / "calibracao_3300Hz_rep1.bin").read_bytes())
        rc, _, err = cli(main, pasta, "-o", tmp_path / "p.json")
        assert rc == 0
        assert "pulando 'calibracao_3300Hz_rep1.bin' -- sem amplitude conhecida" in err

    def test_gerador_em_outra_frequencia_que_o_metadado_avisa(self, cli, tmp_path):
        pasta = criar_pasta_amplitude_conhecida(tmp_path / "s", freqs=[1000, 2000, 5000])
        errado = pasta / "calibracao_2000Hz_rep1.bin"
        dados = errado.read_bytes()
        dados = dados.replace(b"f=2000Hz", b"f=2100Hz")                                 # metadado diz 2100, a captura é 2000
        errado.write_bytes(dados)
        rc, _, err = cli(main, pasta, "--id", "x", "-o", tmp_path / "p.json")
        assert rc == 0 or "CRC" in err
        assert "o gerador estava em 2100 Hz" in err

    @pytest.mark.parametrize("valor,trecho", [("500mV", "sem tipo"), ("abc", "não entendida"), ("0Vpp", "positivo")])
    def test_amplitude_invalida_e_erro_de_uso(self, cli, pasta_meta, tmp_path, valor, trecho):
        rc, _, err = cli(main, pasta_meta, "--amplitude-referencia", valor, "-o", tmp_path / "p.json")
        assert rc == 2 and "--amplitude-referencia:" in err and trecho in err


class TestCliOsciloscopio:
    def test_o_osciloscopio_corrige_o_erro_do_mostrador_do_gerador(self, cli, pasta_osc, tmp_path):
        rc, _, err = cli(main, pasta_osc, "--referencia-osciloscopio", "-o", tmp_path / "osc.json")
        assert rc == 0, err
        osc = ler_json(tmp_path / "osc.json")
        assert osc["calibracao_adc"]["modo_referencia"] == "osciloscopio"
        assert osc["calibracao_adc"]["referencia"] == {"origem": "osciloscopio", "escala": 1.0, "unidade": "V"}
        for p in osc["pontos"]:
            assert p["ganho"] == pytest.approx(float(esperado(p["freq_hz"])), rel=4e-3)

        rc, _, err = cli(main, pasta_osc, "-o", tmp_path / "amp.json")           # só o mostrador do gerador: 2 % de erro
        assert rc == 0, err
        for p in ler_json(tmp_path / "amp.json")["pontos"]:
            assert p["ganho"] == pytest.approx(float(esperado(p["freq_hz"])) * 0.98, rel=4e-3)

    def test_mostra_a_frequencia_do_adc_contra_a_do_osciloscopio(self, cli, pasta_osc, tmp_path):
        rc, out, err = cli(main, pasta_osc, "--referencia-osciloscopio", "-o", tmp_path / "p.json")
        assert re.search(r"calibracao_1000Hz_rep1.bin: osciloscópio \d+\.\d+ Hz, [\d.]+ Vpp \(ADC: [+-]\d+ ppm na frequência\)", out), out

    def test_com_ganho_o_valor_do_osciloscopio_em_volts_vira_grandeza_fisica(self, cli, pasta_osc, tmp_path):
        rc, _, err = cli(main, pasta_osc, "--referencia-osciloscopio", "--ganho", "10", "-o", tmp_path / "p.json")
        assert rc == 0, err
        assert ler_json(tmp_path / "p.json")["pontos"][0]["ganho"] == pytest.approx(float(esperado(100)), rel=4e-3)

    def test_unidade_a_com_escala_para_osciloscopio_no_shunt(self, cli, pasta_osc, tmp_path):
        """Osciloscópio no shunt de 0,1 ohm: V/0,1 = A, e A não é multiplicado pelo --ganho."""
        rc, _, err = cli(main, pasta_osc, "--referencia-osciloscopio", "--osc-escala", "10", "--osc-unidade", "A",
                         "--ganho", "0.1", "-o", tmp_path / "p.json")
        assert rc == 0, err
        # A_real = 10 * V_osc; ADC mede V*H -> fisico = 0.1 * V*H ; ganho = 0.1*H*V / (10*V) = H/100
        assert ler_json(tmp_path / "p.json")["pontos"][0]["ganho"] == pytest.approx(float(esperado(100)) / 100, rel=4e-3)

    def test_captura_sem_arquivo_do_osciloscopio_e_pulada(self, cli, pasta_osc, tmp_path):
        copia = tmp_path / "c"
        copia.mkdir()
        for p in pasta_osc.iterdir():
            if "4700Hz" not in p.name or p.suffix == ".bin":
                (copia / p.name).write_bytes(p.read_bytes())
        rc, _, err = cli(main, copia, "--referencia-osciloscopio", "--id", "x", "-o", tmp_path / "p.json")
        assert rc == 0
        assert "pulando 'calibracao_4700Hz_rep1.bin' -- sem arquivo do osciloscópio 'calibracao_4700Hz_rep1.m'" in err

    def test_pasta_separada_para_os_arquivos_do_osciloscopio(self, cli, pasta_osc, tmp_path):
        so_bins, so_osc = tmp_path / "bins", tmp_path / "osc"
        so_bins.mkdir()
        so_osc.mkdir()
        for p in pasta_osc.iterdir():
            (so_bins if p.suffix == ".bin" else so_osc).joinpath(p.name).write_bytes(p.read_bytes())
        rc, _, err = cli(main, so_bins, "--referencia-osciloscopio", so_osc, "--id", "x", "-o", tmp_path / "p.json")
        assert rc == 0, err

    def test_arquivo_do_osciloscopio_ilegivel_e_pulado_com_motivo(self, cli, pasta_osc, tmp_path):
        copia = tmp_path / "c"
        copia.mkdir()
        for p in pasta_osc.iterdir():
            (copia / p.name).write_bytes(p.read_bytes())
        (copia / "calibracao_1000Hz_rep1.m").write_text("nada util aqui = 'texto';\n")
        rc, _, err = cli(main, copia, "--referencia-osciloscopio", "--id", "x", "-o", tmp_path / "p.json")
        assert rc == 0
        assert "pulando 'calibracao_1000Hz_rep1.bin' -- osciloscópio 'calibracao_1000Hz_rep1.m': não achei nenhuma forma de onda" in err

    def test_opcoes_osc_sem_o_modo_sao_erro_de_uso(self, cli, pasta_osc, tmp_path):
        rc, _, err = cli(main, pasta_osc, "--osc-fs", "1e6", "-o", tmp_path / "p.json")
        assert rc == 2 and "--osc-*" in err

    def test_osciloscopio_nao_combina_com_resistencia_shunt(self, cli, pasta_osc, tmp_path):
        rc, _, err = cli(main, pasta_osc, "--referencia-osciloscopio", "--resistencia-shunt", "0.1", "-o", tmp_path / "p.json")
        assert rc == 2 and "--osc-escala" in err
