"""Núcleo do gerador de perfis: medir tom, resolver canais, agregar repetições e CLI."""

import json
import logging

import numpy as np
import pytest
from capturas_sinteticas import (
    R_SHUNT,
    captura_calibracao,
    criar_pasta_calibracao,
    criar_pasta_calibracao_1canal,
    escrever_bin,
    planta_h,
)
from supraharmonicos.cabecalho import ler_cabecalho
from supraharmonicos.calibracao_sonda import (
    PontoMedido,
    agregar_por_frequencia,
    descobrir_capturas,
    ler_referencia_externa,
    medir_tom,
    resolucao_efetiva_hz,
    resolver_canais,
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
        [p] = agregar_por_frequencia(self.pontos([(0.50, 990.0), (0.52, 1010.0)]), "shunt", None, R_SHUNT)
        assert p.n_amostras == 2 and p.ganho == pytest.approx(0.51) and p.freq_hz == pytest.approx(1000.0)
        assert p.desvio_pct == pytest.approx(np.std([0.50, 0.52], ddof=1) / 0.51 * 100)

    def test_repeticoes_discordantes_avisam(self, caplog):
        with caplog.at_level(logging.WARNING):
            agregar_por_frequencia(self.pontos([(0.5, 1000.0), (0.8, 1000.0)]), "shunt", None, R_SHUNT)
        assert any("discordam" in r.getMessage() for r in caplog.records)

    def test_modo_fixa_usa_a_amplitude_informada(self):
        [p] = agregar_por_frequencia(self.pontos([(0.5, 1000.0)]), "fixa", 2.0, None)
        assert p.ganho == pytest.approx(0.25)

    def test_modo_externa_usa_a_corrente_lida_em_cada_ponto(self):
        pts = self.pontos([(0.5, 1000.0)])
        pts[0].corrente_externa_pico_a = 2.0
        [p] = agregar_por_frequencia(pts, "externa", None, None)
        assert p.ganho == pytest.approx(0.25)

    def test_modo_externa_sem_leitura_descarta_o_ponto(self):
        assert agregar_por_frequencia(self.pontos([(0.5, 1000.0)]), "externa", None, None) == []


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
        assert d["calibracao_adc"]["modo_referencia"] == "fixa"
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
        assert rc == 2 and "informe a referência da corrente real" in err

    def test_referencias_incompativeis_sao_erro_de_uso(self, cli, pasta_1canal, tmp_path):
        rc, _, err = cli(main, pasta_1canal, "--referencia-externa", "--amplitude-referencia", "1", "-o", tmp_path / "p.json")
        assert rc == 2 and "não pode ser combinado" in err
        rc, _, err = cli(main, pasta_1canal, "--resistencia-shunt", "0.1", "--amplitude-referencia", "1", "-o", tmp_path / "p.json")
        assert rc == 2 and "não pode ser combinado" in err

    def test_csv_ausente_e_erro_de_dominio(self, cli, tmp_path):
        pasta = criar_pasta_calibracao_1canal(tmp_path / "s", freqs=[1000, 5000], com_referencia_externa=False)
        rc, _, err = cli(main, pasta, "--referencia-externa", "--resistencia-shunt", R_SHUNT, "-o", tmp_path / "p.json")
        assert rc == 1 and "não encontrei o arquivo de referência externa" in err
