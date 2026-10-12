"""Núcleo do gerador de perfis: medir tom, resolver canais, agregar repetições e CLI."""

import json
import logging

import numpy as np
import pytest
from capturas_sinteticas import (
    R_SHUNT,
    captura_calibracao,
    criar_pasta_calibracao,
    escrever_bin,
    planta_h,
)
from supraharmonicos.cabecalho import ler_cabecalho
from supraharmonicos.calibracao_sonda import (
    PontoMedido,
    agregar_por_frequencia,
    descobrir_capturas,
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
        # Frequência: janela flat-top (lóbulo largo) + interpolação parabólica têm viés de ~0,3 % --
        # irrelevante para o perfil (a curva é interpolada em log-frequência), mas é o que o método entrega.
        assert f == pytest.approx(4_713.0, rel=5e-3)
        assert a == pytest.approx(0.37, rel=5e-3)

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
