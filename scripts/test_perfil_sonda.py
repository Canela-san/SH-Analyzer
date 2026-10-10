#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testes sintéticos de regressão do fluxo de perfil de sonda:
    gerar_perfil_sonda.py (análise das capturas) -> adc_tool.py (aplica a correção)

Não precisa de hardware: gera capturas '.bin' v2 (cabeçalho "SHAN" de 1024 B)
a partir de uma "sonda" de resposta em frequência CONHECIDA (passa-baixa de 1ª
ordem, fc=30 kHz) e confere, com tolerâncias numéricas, que:
  - o perfil gerado recupera a curva verdadeira;
  - a correção devolve a amplitude real de tons de teste;
  - cada falha encontrada na auditoria (docs/auditoria_perfil_sonda.md) continua
    corrigida: id de sonda malicioso, NaN/Inf no perfil, --ganho/--faixa/--formato
    divergentes, sonda em canal de tensão, captura saturada, sobrescrita
    destrutiva do perfil, captura com mais de 2 canais.

Uso (de qualquer pasta):   python3 scripts/testes/test_perfil_sonda.py
Também roda sob pytest (funções test_*). Dura ~1 min. Dependências: as de adc_tool.py.
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import traceback
import zlib
from pathlib import Path

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1]
ADC_TOOL = SCRIPTS / "adc_tool.py"
GERAR = SCRIPTS / "gerar_perfil_sonda.py"

FAIXA = 10.24            # mesma convenção de adc_tool.py: uint16, offset = faixa/2
FS_TOTAL_2CH = 400_000   # 2 canais -> 200 kHz por canal
R_SHUNT = 0.1            # ohm
SENS_NOMINAL = 0.1       # V/A (sonda 100 mV/A -> --ganho 10)
# 19 pontos ~log-espaçados (série E6 estendida): com poucos pontos o erro de INTERPOLAÇÃO (PCHIP) domina --
# medido na auditoria p/ esta sonda de 1 polo: 7 pts -> 1.9%, 12 -> 0.6%, 18 -> 0.17%, 25 -> 0.06% (docs/auditoria_perfil_sonda.md)
FREQS_CAL = [100, 150, 220, 330, 470, 680, 1000, 1500, 2200, 3300, 4700, 6800, 10000, 15000, 22000, 33000, 47000, 68000, 80000]
TONS_PRODUCAO = [(50.0, 10.0), (2500.0, 0.2), (9000.0, 0.1), (20000.0, 0.1), (40000.0, 0.1)]

_FMT_V2 = "<4sIIQIII8BIIIIIdQQ64s256s8B" + "32s" * 8 + "I"
_OFFSET_CRC = struct.calcsize(_FMT_V2) - 4

_TMP = None  # TemporaryDirectory da execução


# ---------------------------------------------------------------- fixtures --

def planta_h(f, fc_lp=30e3, fc_hp=5.0):
    """Magnitude 'verdadeira' (linear) da sonda simulada."""
    f = np.asarray(f, dtype=np.float64)
    return 1.0 / np.sqrt(1.0 + (f / fc_lp) ** 2) / np.sqrt(1.0 + (fc_hp / np.maximum(f, 1e-9)) ** 2)


def escrever_bin(caminho, canais_v, canais, grandezas, sondas, fs_total):
    """'.bin' v2: canais_v = lista de arrays em Volts (um por canal, na ordem de 'canais')."""
    n, k = min(len(c) for c in canais_v), len(canais)
    v = np.empty(k * n)
    for i, c in enumerate(canais_v):
        v[i::k] = c[:n]
    cod = np.clip(np.round((v + FAIXA / 2) / FAIXA * 65536), 0, 65535).astype("<u2")
    lista = list(canais) + [0xFF] * (8 - k)
    gr = list(grandezas) + [0xFF] * (8 - k)
    ids = [s.encode("ascii") for s in sondas] + [b""] * (8 - k)
    vals = [b"SHAN", 2, 1024, 1_700_000_000, fs_total, 0xFF, k, *lista, 1048576, 2, 200_000_000,
            500, 0, n / (fs_total / k), 1, k * n, b"teste", b"sintetico", *gr, *ids, 0]
    bruto = bytearray(struct.pack(_FMT_V2, *vals))
    bruto += b"\x00" * (1024 - len(bruto))
    struct.pack_into("<I", bruto, _OFFSET_CRC, zlib.crc32(bytes(bruto)))
    with open(caminho, "wb") as f:
        f.write(bytes(bruto))
        f.write(cod.tobytes())


def captura_calibracao(freq_hz, seed, dur_s=0.5, fs_canal=200_000.0):
    """(v_ref, v_sonda) no pino do ADC: tom de 1 A; ref = R*I (shunt), sonda = SENS*H(f)*I; ruído 0,5 mV."""
    rng = np.random.default_rng(seed)
    n = int(dur_s * fs_canal)
    i = np.sin(2 * np.pi * freq_hz * np.arange(n) / fs_canal + rng.uniform(0, 2 * np.pi))
    return R_SHUNT * i + rng.normal(0, 5e-4, n), SENS_NOMINAL * planta_h(freq_hz) * i + rng.normal(0, 5e-4, n)


def criar_pasta_calibracao(pasta, freqs=FREQS_CAL, reps=2, nome_sonda="sonda_teste"):
    pasta.mkdir(parents=True, exist_ok=True)
    rng, k = np.random.default_rng(1), 0
    for f in freqs:
        for r in range(1, reps + 1):
            vr, vs = captura_calibracao(f * (1 + rng.uniform(-0.01, 0.01)), seed=1000 + k)
            escrever_bin(pasta / f"calibracao_{f}Hz_rep{r}.bin", [vr, vs], (0, 1), (0, 1), ("", nome_sonda), FS_TOTAL_2CH)
            k += 1


def captura_producao(caminho, sonda_id="sonda_teste", grandeza_canal1=1, dur_s=1.0):
    """Canal 0 = tensão (50 Hz); canal 1 = saída da sonda para a corrente TONS_PRODUCAO."""
    fs, rng = 200_000.0, np.random.default_rng(5)
    n = int(dur_s * fs)
    t = np.arange(n) / fs
    v_sonda = sum(SENS_NOMINAL * planta_h(f) * a * np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28)) for f, a in TONS_PRODUCAO)
    v_sonda = v_sonda + rng.normal(0, 5e-4, n)
    v_tensao = 3.25 * np.sin(2 * np.pi * 50 * t) + rng.normal(0, 5e-4, n)
    escrever_bin(caminho, [v_tensao, v_sonda], (0, 1), (0, grandeza_canal1), ("", sonda_id), FS_TOTAL_2CH)


# ----------------------------------------------------------------- runners --

def _env():
    e = dict(os.environ)
    e["MPLBACKEND"] = "Agg"
    return e


def gerar(pasta, saida, *extra, ganho="1,10"):
    r = subprocess.run([sys.executable, str(GERAR), str(pasta), "--resistencia-shunt", str(R_SHUNT), "--ganho", ganho,
                        "--id", "sonda_teste", "-o", str(saida), *extra], capture_output=True, text=True, env=_env())
    return r.returncode, r.stdout, r.stderr


def adc_tool(arquivo, sondas_dir, *extra, ganho="1,10"):
    r = subprocess.run([sys.executable, str(ADC_TOOL), str(arquivo), "--ganho", ganho, "--sondas-dir", str(sondas_dir),
                        "--welch", "--resolucao-welch", "100", "--modo-espectro", "tom", "--picos", "-40",
                        "--freq-min-picos", "1000", "--filtro-passa-alta", "1000", "-o", str(Path(_TMP.name) / "x.png"), *extra],
                       capture_output=True, text=True, env=_env())
    return r.returncode, r.stdout, r.stderr


def picos_canal1(saida):
    """[(freq_hz, amplitude_linear)] dos picos reportados para o canal 1."""
    return [(float(m.group(1)), 10 ** (float(m.group(2)) / 20))
            for m in re.finditer(r"Canal 1 \[welch\] pico: ([\d.]+) Hz @ (-?[\d.]+) dB", saida)]


# ---------------------------------------------------------- estado compartilhado --

_ESTADO = {}


def _preparar():
    """Gera, uma vez, a pasta de calibração, o perfil e as capturas de produção usadas pelos testes."""
    if _ESTADO:
        return _ESTADO
    base = Path(_TMP.name)
    sondas = base / "sondas"
    sondas.mkdir()
    pasta = base / "capt" / "sonda_teste"
    criar_pasta_calibracao(pasta)
    rc, out, err = gerar(pasta, sondas / "sonda_teste.json")
    assert rc == 0, f"geração do perfil base falhou:\n{err}"
    prod = base / "prod"
    prod.mkdir()
    captura_producao(prod / "ok.bin")
    _ESTADO.update(base=base, sondas=sondas, pasta=pasta, prod=prod, perfil=sondas / "sonda_teste.json")
    return _ESTADO


# ------------------------------------------------------------------- testes --

def test_perfil_recupera_curva_verdadeira():
    e = _preparar()
    d = json.load(open(e["perfil"]))
    f = np.array([p["freq_hz"] for p in d["pontos"]])
    g = np.array([p["ganho"] for p in d["pontos"]])
    assert len(f) == len(FREQS_CAL)
    assert np.abs(g / planta_h(f) - 1).max() < 5e-4, "ganho medido deveria bater com a curva verdadeira (<0.05%)"
    assert all("n" in p and "desvio_pct" in p for p in d["pontos"]), "pontos devem trazer n e desvio_pct"
    assert d["calibracao_adc"]["ganho"]["sonda"] == 10.0


def test_correcao_restaura_amplitude_dos_tons():
    e = _preparar()
    rc, out, err = adc_tool(e["prod"] / "ok.bin", e["sondas"])
    assert rc == 0, err
    verdade = {2500: 0.2, 9000: 0.1, 20000: 0.1, 40000: 0.1}
    achados = {round(f, -2) if f < 5000 else round(f, -3): a for f, a in picos_canal1(out)}
    assert set(achados) == set(verdade), achados
    for f, a in verdade.items():
        assert abs(achados[f] / a - 1) < 5e-3, f"{f} Hz: {achados[f]:.4f} vs {a}"
    assert "foi gerado com" not in err and "declara id" not in err, "perfil coerente não deveria gerar avisos de calibração/id"
    assert "acima de" in err, "Nyquist (100 kHz) > último ponto (80 kHz): deve avisar da faixa"


def test_sem_correcao_mostra_o_erro_da_sonda():
    e = _preparar()
    rc, out, err = adc_tool(e["prod"] / "ok.bin", e["sondas"], "--sem-correcao-sonda")
    a40 = picos_canal1(out)[-1][1]
    assert abs(a40 - 0.06) < 2e-3, f"sem correção, 40 kHz deveria sair ~0.06 A (sonda atenua 40%), saiu {a40:.4f}"


def test_sonda_registrada_em_canal_de_tensao_e_aplicada():
    e = _preparar()
    captura_producao(e["prod"] / "tensao_com_sonda.bin", grandeza_canal1=0)
    rc, out, err = adc_tool(e["prod"] / "tensao_com_sonda.bin", e["sondas"])
    assert "Canal 1: correção de sonda aplicada" in out, "antes da auditoria, canal de tensão com sonda era ignorado em silêncio"
    assert abs(picos_canal1(out)[-1][1] - 0.1) < 5e-4


def test_id_de_sonda_inseguro_e_rejeitado():
    e = _preparar()
    fora = e["base"] / "fora"
    fora.mkdir()
    json.dump({"id": "evil", "tipo": "ganho_fixo", "ganho": 0.5}, open(fora / "evil.json", "w"))
    # (a) fim a fim: '../fora/evil' num '.bin' escaparia de sondas_dir antes da correção
    captura_producao(e["prod"] / "trav.bin", sonda_id="../fora/evil")
    rc, out, err = adc_tool(e["prod"] / "trav.bin", e["sondas"])
    assert rc != 0 and "não é um nome de arquivo seguro" in (out + err) and "Traceback" not in err, (rc, err[-200:])
    # (b) caminho absoluto (o '/' da direita substituiria sondas_dir) e demais formas, direto na função
    sys.path.insert(0, str(SCRIPTS))
    import adc_tool as at
    for sid in ("/etc/passwd", "../x", "a/b", "a\\b", "..", ".oculto", "x..y", "com espaço"):
        try:
            at.resolver_perfil_canal(1, sid, {}, e["sondas"])
        except SystemExit as exc:
            assert "nome de arquivo seguro" in str(exc), (sid, str(exc))
        else:
            raise AssertionError(f"id inseguro aceito: {sid!r}")
    # ids legítimos (os que calibrar_sonda.sh gera) continuam passando pela validação -> caem em 'perfil não existe'
    for sid in ("fluke_i30_01", "sonda-2", "i30s.v2"):
        try:
            at.resolver_perfil_canal(1, sid, {}, e["sondas"])
        except SystemExit as exc:
            assert "não existe um perfil" in str(exc), (sid, str(exc))
    # --sonda-perfil explícito (entrada do operador, não do .bin) continua livre
    rc, out, err = adc_tool(e["prod"] / "trav.bin", e["sondas"], "--sonda-perfil", f"1:{fora / 'evil.json'}")
    assert rc == 0 and "correção de sonda aplicada" in out


def test_id_divergente_do_arquivo_avisa():
    e = _preparar()
    d = json.load(open(e["perfil"]))
    d["id"] = "OUTRA_sonda_9999"
    json.dump(d, open(e["sondas"] / "sonda_div.json", "w"))
    captura_producao(e["prod"] / "div.bin", sonda_id="sonda_div")
    rc, out, err = adc_tool(e["prod"] / "div.bin", e["sondas"])
    assert rc == 0 and "declara id='OUTRA_sonda_9999'" in err


def test_nan_e_infinito_no_perfil_dao_erro_limpo():
    e = _preparar()
    base = json.load(open(e["perfil"]))
    casos = {"nan": ("ganho", float("nan")), "inf": ("ganho", float("inf")), "fnan": ("freq_hz", float("nan"))}
    for nome, (campo, valor) in casos.items():
        d = json.loads(json.dumps(base))
        d["pontos"][3][campo] = valor
        json.dump(d, open(e["sondas"] / f"sonda_{nome}.json", "w"))   # json.dump escreve NaN/Infinity (json.load aceita)
        captura_producao(e["prod"] / f"{nome}.bin", sonda_id=f"sonda_{nome}")
        rc, out, err = adc_tool(e["prod"] / f"{nome}.bin", e["sondas"])
        assert rc != 0 and "números finitos" in (out + err) and "Traceback" not in err, (nome, err[-200:])


def test_calibracao_divergente_avisa():
    e = _preparar()
    rc, out, err = adc_tool(e["prod"] / "ok.bin", e["sondas"], ganho="1,1")
    assert "--ganho do canal = 1, mas o perfil foi gerado com 10" in err and "0.1" in err
    rc, out, err = adc_tool(e["prod"] / "ok.bin", e["sondas"], "--faixa", "5.12")
    assert "--faixa do canal = 5.12 V, mas o perfil foi gerado com 10.24" in err
    rc, out, err = adc_tool(e["prod"] / "ok.bin", e["sondas"], "--formato", "int16")
    assert "--formato = int16, mas o perfil foi gerado com uint16" in err


def test_sobrescrita_cria_backup_e_falha_preserva_perfil():
    e = _preparar()
    saida = e["base"] / "perfil_sobrescrita.json"
    assert gerar(e["pasta"], saida)[0] == 0
    rc, out, err = gerar(e["pasta"], saida)
    assert rc == 0 and Path(str(saida) + ".bak").exists() and "já existia" in err
    antes = saida.read_bytes()
    rc, out, err = gerar(e["pasta"], saida, "--faixa-freq-valida", "5000", "500")   # min > max: round-trip tem que falhar
    assert rc != 0 and "NÃO carrega" in (out + err) and "Traceback" not in err
    assert saida.read_bytes() == antes and not Path(str(saida) + ".tmp").exists(), "perfil bom foi destruído/tmp ficou para trás"


def test_captura_saturada_e_descartada():
    e = _preparar()
    pasta = e["base"] / "capt_sat"
    criar_pasta_calibracao(pasta)
    vr, vs = captura_calibracao(1000.0, seed=9)
    escrever_bin(pasta / "calibracao_1000Hz_rep2.bin", [vr, vs * 400], (0, 1), (0, 1), ("", "sonda_teste"), FS_TOTAL_2CH)  # ±40 V: estoura o ADC
    saida = e["base"] / "perfil_sat.json"
    rc, out, err = gerar(pasta, saida)
    assert rc == 0 and "saturou o ADC" in err and "calibracao_1000Hz_rep2.bin" in err
    p1k = [p for p in json.load(open(saida))["pontos"] if 900 < p["freq_hz"] < 1100][0]
    assert p1k["n"] == 1 and abs(p1k["ganho"] / planta_h(p1k["freq_hz"]) - 1) < 5e-4


def test_captura_com_3_canais_e_canais_forcados():
    e = _preparar()
    pasta = e["base"] / "capt_3ch"
    pasta.mkdir()
    for f in FREQS_CAL:
        vr, vs = captura_calibracao(f * 1.003, seed=f)
        ruido = np.random.default_rng(3).normal(0, 0.5, len(vr))      # canal 1 = ruído forte
        escrever_bin(pasta / f"calibracao_{f}Hz_rep1.bin", [vr, ruido, vs], (0, 1, 2), (0, 0, 1), ("", "", "sonda_teste"), 600_000)
    saida = e["base"] / "perfil_3ch.json"
    rc, out, err = gerar(pasta, saida, "--canal-referencia", "0", "--canal-sonda", "2")
    assert rc == 0, err[-300:]
    d = json.load(open(saida))
    f = np.array([p["freq_hz"] for p in d["pontos"]])
    g = np.array([p["ganho"] for p in d["pontos"]])
    assert np.abs(g / planta_h(f) - 1).max() < 1e-3
    rc, out, err = gerar(pasta, e["base"] / "x.json", "--canal-referencia", "2", "--canal-sonda", "2")
    assert rc != 0 and "são o mesmo" in err


# ------------------------------------------------------------------- runner --

def main():
    global _TMP
    _TMP = tempfile.TemporaryDirectory(prefix="test_perfil_sonda_")
    testes = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    falhas = 0
    try:
        for nome, fn in testes:
            try:
                fn()
                print(f"[PASS] {nome}")
            except Exception:                                   # noqa: BLE001 -- relatório, não lógica
                falhas += 1
                print(f"[FAIL] {nome}\n{traceback.format_exc()}")
    finally:
        _TMP.cleanup()
    print(f"\n{len(testes) - falhas}/{len(testes)} testes passaram.")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
