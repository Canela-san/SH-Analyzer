"""Fluxo completo de ponta a ponta, via subprocess nas ENTRADAS reais de ``scripts/``:

    capturas de calibração -> gerar_perfil_sonda.py -> perfil .json -> adc_tool.py aplica a correção

Não precisa de hardware: as capturas '.bin' v2 (cabeçalho "SHAN") são sintetizadas a
partir de uma "sonda" de resposta em frequência CONHECIDA (passa-baixa de 1ª ordem,
fc = 30 kHz). Confere, com tolerâncias numéricas, que o perfil gerado recupera a curva
verdadeira e que a correção devolve a amplitude real dos tons -- e que cada falha
encontrada na auditoria (docs/auditoria_perfil_sonda.md) continua corrigida.

Lento (~1 min): marcado ``e2e``. Rodar só estes:  pytest -m e2e      Pular:  pytest -m "not e2e"
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from capturas_sinteticas import (
    FREQS_CAL,
    R_SHUNT,
    captura_calibracao,
    captura_producao,
    criar_pasta_calibracao,
    escrever_bin,
    planta_h,
)
from supraharmonicos.erros import ErroSHAN
from supraharmonicos.sonda import resolver_perfil_canal

pytestmark = pytest.mark.e2e

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
ADC_TOOL = SCRIPTS / "adc_tool.py"
GERAR = SCRIPTS / "gerar_perfil_sonda.py"


def _env():
    e = dict(os.environ)
    e["MPLBACKEND"] = "Agg"
    return e


def gerar(pasta, saida, *extra, ganho="1,10"):
    r = subprocess.run([sys.executable, str(GERAR), str(pasta), "--resistencia-shunt", str(R_SHUNT), "--ganho", ganho,
                        "--id", "sonda_teste", "-o", str(saida), *extra], capture_output=True, text=True, env=_env())
    return r.returncode, r.stdout, r.stderr


def adc_tool(arquivo, sondas_dir, png, *extra, ganho="1,10"):
    r = subprocess.run([sys.executable, str(ADC_TOOL), str(arquivo), "--ganho", ganho, "--sondas-dir", str(sondas_dir),
                        "--welch", "--resolucao-welch", "100", "--modo-espectro", "tom", "--picos", "-40",
                        "--freq-min-picos", "1000", "--filtro-passa-alta", "1000", "-o", str(png), *extra],
                       capture_output=True, text=True, env=_env())
    return r.returncode, r.stdout, r.stderr


def picos_canal1(saida):
    """[(freq_hz, amplitude_linear)] dos picos reportados para o canal 1."""
    return [(float(m.group(1)), 10 ** (float(m.group(2)) / 20))
            for m in re.finditer(r"Canal 1 \[welch\] pico: ([\d.]+) Hz @ (-?[\d.]+) dB", saida)]


class Ambiente:
    """Pasta de calibração, perfil gerado e capturas de produção, criados uma vez por módulo."""

    def __init__(self, base: Path):
        self.base = base
        self.sondas = base / "sondas"
        self.sondas.mkdir()
        self.pasta = criar_pasta_calibracao(base / "capt" / "sonda_teste")
        self.perfil = self.sondas / "sonda_teste.json"
        rc, _, err = gerar(self.pasta, self.perfil)
        assert rc == 0, f"geração do perfil base falhou:\n{err}"
        self.prod = base / "prod"
        self.prod.mkdir()
        captura_producao(self.prod / "ok.bin")
        self.png = base / "x.png"

    def adc_tool(self, arquivo, *extra, ganho="1,10"):
        return adc_tool(arquivo, self.sondas, self.png, *extra, ganho=ganho)


@pytest.fixture(scope="module")
def e(tmp_path_factory) -> Ambiente:
    return Ambiente(tmp_path_factory.mktemp("e2e_sonda"))


def test_perfil_recupera_curva_verdadeira(e):
    d = json.loads(e.perfil.read_text(encoding="utf-8"))
    f = np.array([p["freq_hz"] for p in d["pontos"]])
    g = np.array([p["ganho"] for p in d["pontos"]])
    assert len(f) == len(FREQS_CAL)
    assert np.abs(g / planta_h(f) - 1).max() < 5e-4, "ganho medido deveria bater com a curva verdadeira (<0.05%)"
    assert all("n" in p and "desvio_pct" in p for p in d["pontos"]), "pontos devem trazer n e desvio_pct"
    assert d["calibracao_adc"]["ganho"]["sonda"] == 10.0


def test_correcao_restaura_amplitude_dos_tons(e):
    rc, out, err = e.adc_tool(e.prod / "ok.bin")
    assert rc == 0, err
    verdade = {2500: 0.2, 9000: 0.1, 20000: 0.1, 40000: 0.1}
    achados = {round(f, -2) if f < 5000 else round(f, -3): a for f, a in picos_canal1(out)}
    assert set(achados) == set(verdade), achados
    for f, a in verdade.items():
        assert abs(achados[f] / a - 1) < 5e-3, f"{f} Hz: {achados[f]:.4f} vs {a}"
    assert "foi gerado com" not in err and "declara id" not in err, "perfil coerente não deveria gerar avisos de calibração/id"
    assert "acima de" in err, "Nyquist (100 kHz) > último ponto (80 kHz): deve avisar da faixa"


def test_sem_correcao_mostra_o_erro_da_sonda(e):
    rc, out, err = e.adc_tool(e.prod / "ok.bin", "--sem-correcao-sonda")
    a40 = picos_canal1(out)[-1][1]
    assert abs(a40 - 0.06) < 2e-3, f"sem correção, 40 kHz deveria sair ~0.06 A (sonda atenua 40%), saiu {a40:.4f}"


def test_sonda_registrada_em_canal_de_tensao_e_aplicada(e):
    captura_producao(e.prod / "tensao_com_sonda.bin", grandeza_canal1=0)
    rc, out, err = e.adc_tool(e.prod / "tensao_com_sonda.bin")
    assert "Canal 1: correção de sonda aplicada" in out, "antes da auditoria, canal de tensão com sonda era ignorado em silêncio"
    assert abs(picos_canal1(out)[-1][1] - 0.1) < 5e-4


def test_id_de_sonda_inseguro_e_rejeitado_fim_a_fim(e):
    fora = e.base / "fora"
    fora.mkdir()
    (fora / "evil.json").write_text(json.dumps({"id": "evil", "tipo": "ganho_fixo", "ganho": 0.5}), encoding="utf-8")
    # '../fora/evil' num '.bin' escaparia de sondas_dir antes da correção
    captura_producao(e.prod / "trav.bin", sonda_id="../fora/evil")
    rc, out, err = e.adc_tool(e.prod / "trav.bin")
    assert rc == 1 and "não é um nome de arquivo seguro" in (out + err) and "Traceback" not in err, (rc, err[-200:])
    # --sonda-perfil explícito (entrada do operador, não do .bin) continua livre
    rc, out, err = e.adc_tool(e.prod / "trav.bin", "--sonda-perfil", f"1:{fora / 'evil.json'}")
    assert rc == 0 and "correção de sonda aplicada" in out


def test_id_de_sonda_inseguro_formas_absolutas_e_relativas(e):
    for sid in ("/etc/passwd", "../x", "a/b", "a\\b", "..", ".oculto", "x..y", "com espaço"):
        with pytest.raises(ErroSHAN, match="nome de arquivo seguro"):
            resolver_perfil_canal(1, sid, {}, e.sondas)
    for sid in ("fluke_i30_01", "sonda-2", "i30s.v2"):    # ids que calibrar_sonda.sh gera: passam e caem em 'não existe'
        with pytest.raises(ErroSHAN, match="não existe um perfil"):
            resolver_perfil_canal(1, sid, {}, e.sondas)


def test_id_divergente_do_arquivo_avisa(e):
    d = json.loads(e.perfil.read_text(encoding="utf-8"))
    d["id"] = "OUTRA_sonda_9999"
    (e.sondas / "sonda_div.json").write_text(json.dumps(d), encoding="utf-8")
    captura_producao(e.prod / "div.bin", sonda_id="sonda_div")
    rc, out, err = e.adc_tool(e.prod / "div.bin")
    assert rc == 0 and "declara id='OUTRA_sonda_9999'" in err


def test_nan_e_infinito_no_perfil_dao_erro_limpo(e):
    base = json.loads(e.perfil.read_text(encoding="utf-8"))
    casos = {"nan": ("ganho", float("nan")), "inf": ("ganho", float("inf")), "fnan": ("freq_hz", float("nan"))}
    for nome, (campo, valor) in casos.items():
        d = json.loads(json.dumps(base))
        d["pontos"][3][campo] = valor
        (e.sondas / f"sonda_{nome}.json").write_text(json.dumps(d), encoding="utf-8")   # json.dumps escreve NaN/Infinity
        captura_producao(e.prod / f"{nome}.bin", sonda_id=f"sonda_{nome}")
        rc, out, err = e.adc_tool(e.prod / f"{nome}.bin")
        assert rc == 1 and "números finitos" in (out + err) and "Traceback" not in err, (nome, err[-200:])


def test_calibracao_divergente_avisa(e):
    rc, out, err = e.adc_tool(e.prod / "ok.bin", ganho="1,1")
    assert "--ganho do canal = 1, mas o perfil foi gerado com 10" in err and "0.1" in err
    rc, out, err = e.adc_tool(e.prod / "ok.bin", "--faixa", "5.12")
    assert "--faixa do canal = 5.12 V, mas o perfil foi gerado com 10.24" in err
    rc, out, err = e.adc_tool(e.prod / "ok.bin", "--formato", "int16")
    assert "--formato = int16, mas o perfil foi gerado com uint16" in err


def test_sobrescrita_cria_backup_e_falha_preserva_perfil(e):
    saida = e.base / "perfil_sobrescrita.json"
    assert gerar(e.pasta, saida)[0] == 0
    rc, out, err = gerar(e.pasta, saida)
    assert rc == 0 and Path(str(saida) + ".bak").exists() and "já existia" in err
    antes = saida.read_bytes()
    rc, out, err = gerar(e.pasta, saida, "--faixa-freq-valida", "5000", "500")   # min > max: round-trip tem que falhar
    assert rc == 1 and "NÃO carrega" in (out + err) and "Traceback" not in err
    assert saida.read_bytes() == antes and not Path(str(saida) + ".tmp").exists(), "perfil bom foi destruído/tmp ficou para trás"


def test_captura_saturada_e_descartada(e):
    pasta = e.base / "capt_sat"
    criar_pasta_calibracao(pasta)
    vr, vs = captura_calibracao(1000.0, seed=9)
    escrever_bin(pasta / "calibracao_1000Hz_rep2.bin", [vr, vs * 400], (0, 1), (0, 1), ("", "sonda_teste"))  # ±40 V: estoura o ADC
    saida = e.base / "perfil_sat.json"
    rc, out, err = gerar(pasta, saida)
    assert rc == 0 and "saturou o ADC" in err and "calibracao_1000Hz_rep2.bin" in err
    p1k = [p for p in json.loads(saida.read_text(encoding="utf-8"))["pontos"] if 900 < p["freq_hz"] < 1100][0]
    assert p1k["n"] == 1 and abs(p1k["ganho"] / planta_h(p1k["freq_hz"]) - 1) < 5e-4


def test_captura_com_3_canais_e_canais_forcados(e):
    pasta = e.base / "capt_3ch"
    pasta.mkdir()
    for f in FREQS_CAL:
        vr, vs = captura_calibracao(f * 1.003, seed=f)
        ruido = np.random.default_rng(3).normal(0, 0.5, len(vr))      # canal 1 = ruído forte
        escrever_bin(pasta / f"calibracao_{f}Hz_rep1.bin", [vr, ruido, vs], (0, 1, 2), (0, 0, 1), ("", "", "sonda_teste"),
                     fs_total=600_000)
    saida = e.base / "perfil_3ch.json"
    rc, out, err = gerar(pasta, saida, "--canal-referencia", "0", "--canal-sonda", "2")
    assert rc == 0, err[-300:]
    d = json.loads(saida.read_text(encoding="utf-8"))
    f = np.array([p["freq_hz"] for p in d["pontos"]])
    g = np.array([p["ganho"] for p in d["pontos"]])
    assert np.abs(g / planta_h(f) - 1).max() < 1e-3
    rc, out, err = gerar(pasta, e.base / "x.json", "--canal-referencia", "2", "--canal-sonda", "2")
    assert rc == 1 and "são o mesmo" in err
