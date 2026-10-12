"""Gerador de capturas sintéticas (``.bin`` com cabeçalho "SHAN") para os testes.

Não precisa de hardware: monta o ``.bin`` exatamente como ``firmware/ler_adc.c``
gravaria (cabeçalho de 1024 B v1 ou v2 + amostras intercaladas), a partir de
sinais em Volts no pino do ADC. Também sintetiza uma "sonda" de resposta em
frequência CONHECIDA (passa-baixa de 1ª ordem, fc = 30 kHz) para os testes de
calibração/correção.

Convenção do ADC (a mesma de ``adc_tool``): ``uint16`` com offset = faixa/2.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

FAIXA = 10.24            # V (ADS8688 +-FAIXA/2 em uint16)
FS_TOTAL_2CH = 400_000   # Hz, total -> 200 kHz por canal com 2 canais
R_SHUNT = 0.1            # ohm
SENS_NOMINAL = 0.1       # V/A (sonda 100 mV/A -> --ganho 10)

# 19 pontos ~log-espaçados: com poucos pontos o erro de INTERPOLAÇÃO (PCHIP)
# domina -- medido na auditoria para esta sonda de 1 polo: 7 pts -> 1,9 %,
# 12 -> 0,6 %, 18 -> 0,17 %, 25 -> 0,06 % (docs/auditoria_perfil_sonda.md).
FREQS_CAL = [100, 150, 220, 330, 470, 680, 1000, 1500, 2200, 3300, 4700, 6800,
             10000, 15000, 22000, 33000, 47000, 68000, 80000]
TONS_PRODUCAO = [(50.0, 10.0), (2500.0, 0.2), (9000.0, 0.1), (20000.0, 0.1), (40000.0, 0.1)]

FMT_V1 = "<4sIIQIII8BIIIIIdQQ64s256sI"
FMT_V2 = "<4sIIQIII8BIIIIIdQQ64s256s8B" + "32s" * 8 + "I"


def planta_h(f, fc_lp: float = 30e3, fc_hp: float = 5.0):
    """Magnitude 'verdadeira' (linear) da sonda simulada."""
    f = np.asarray(f, dtype=np.float64)
    return 1.0 / np.sqrt(1.0 + (f / fc_lp) ** 2) / np.sqrt(1.0 + (fc_hp / np.maximum(f, 1e-9)) ** 2)


def volts_para_codigos(v: np.ndarray, formato: str = "uint16") -> np.ndarray:
    if formato == "uint16":
        return np.clip(np.round((v + FAIXA / 2) / FAIXA * 65536), 0, 65535).astype("<u2")
    return np.clip(np.round(v / FAIXA * 32768), -32768, 32767).astype("<i2")


def montar_cabecalho(n_por_canal: int, canais, grandezas, sondas, fs_total: int,
                     versao: int = 2, titulo: str = "teste", descricao: str = "sintetico",
                     crc_valido: bool = True, total_amostras: int | None = None) -> bytes:
    """Cabeçalho de 1024 bytes (v1 ou v2) com CRC-32 correto (ou propositalmente errado)."""
    k = len(canais)
    lista = list(canais) + [0xFF] * (8 - k)
    mascara = sum(1 << c for c in canais)
    total = k * n_por_canal if total_amostras is None else total_amostras
    comuns = [b"SHAN", versao, 1024, 1_700_000_000, int(fs_total), mascara, k, *lista,
              1048576, 2, 200_000_000, 500, 0, n_por_canal / (fs_total / k), 1, total,
              titulo.encode("utf-8"), descricao.encode("utf-8")]
    if versao >= 2:
        gr = list(grandezas) + [0xFF] * (8 - k)
        ids = [s.encode("ascii") for s in sondas] + [b""] * (8 - k)
        fmt, vals = FMT_V2, [*comuns, *gr, *ids, 0]
    else:
        fmt, vals = FMT_V1, [*comuns, 0]
    bruto = bytearray(struct.pack(fmt, *vals))
    deslocamento_crc = struct.calcsize(fmt) - 4
    bruto += b"\x00" * (1024 - len(bruto))
    crc = zlib.crc32(bytes(bruto))
    if not crc_valido:
        crc ^= 0xDEADBEEF
    struct.pack_into("<I", bruto, deslocamento_crc, crc)
    return bytes(bruto)


def escrever_bin(caminho: Path, canais_v, canais=(0, 1), grandezas=(0, 1), sondas=("", ""),
                 fs_total: int = FS_TOTAL_2CH, formato: str = "uint16", com_cabecalho: bool = True,
                 **kw_cabecalho) -> Path:
    """Grava um '.bin'. ``canais_v``: um array de Volts por canal, na ordem de ``canais``."""
    caminho = Path(caminho)
    k = len(canais)
    n = min(len(c) for c in canais_v)
    v = np.empty(k * n)
    for i, c in enumerate(canais_v):
        v[i::k] = c[:n]
    codigos = volts_para_codigos(v, formato)
    with open(caminho, "wb") as f:
        if com_cabecalho:
            f.write(montar_cabecalho(n, canais, grandezas, sondas, fs_total, **kw_cabecalho))
        f.write(codigos.tobytes())
    return caminho


def captura_calibracao(freq_hz: float, seed: int, dur_s: float = 0.5, fs_canal: float = 200_000.0):
    """(v_ref, v_sonda) no pino do ADC: tom de 1 A; ref = R*I (shunt), sonda = SENS*H(f)*I; ruído de 0,5 mV."""
    rng = np.random.default_rng(seed)
    n = int(dur_s * fs_canal)
    i = np.sin(2 * np.pi * freq_hz * np.arange(n) / fs_canal + rng.uniform(0, 2 * np.pi))
    return R_SHUNT * i + rng.normal(0, 5e-4, n), SENS_NOMINAL * planta_h(freq_hz) * i + rng.normal(0, 5e-4, n)


def criar_pasta_calibracao(pasta: Path, freqs=FREQS_CAL, reps: int = 2, nome_sonda: str = "sonda_teste") -> Path:
    """Pasta no formato de ``firmware/calibrar_sonda.sh``: ``calibracao_<F>Hz_rep<N>.bin``."""
    pasta.mkdir(parents=True, exist_ok=True)
    rng, k = np.random.default_rng(1), 0
    for f in freqs:
        for r in range(1, reps + 1):
            vr, vs = captura_calibracao(f * (1 + rng.uniform(-0.01, 0.01)), seed=1000 + k)
            escrever_bin(pasta / f"calibracao_{f}Hz_rep{r}.bin", [vr, vs], (0, 1), (0, 1), ("", nome_sonda))
            k += 1
    return pasta


def captura_producao(caminho: Path, sonda_id: str = "sonda_teste", grandeza_canal1: int = 1, dur_s: float = 1.0) -> Path:
    """Canal 0 = tensão (50 Hz); canal 1 = saída da sonda para a corrente ``TONS_PRODUCAO``."""
    fs, rng = 200_000.0, np.random.default_rng(5)
    n = int(dur_s * fs)
    t = np.arange(n) / fs
    v_sonda = sum(SENS_NOMINAL * planta_h(f) * a * np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28))
                  for f, a in TONS_PRODUCAO)
    v_sonda = v_sonda + rng.normal(0, 5e-4, n)
    v_tensao = 3.25 * np.sin(2 * np.pi * 50 * t) + rng.normal(0, 5e-4, n)
    return escrever_bin(caminho, [v_tensao, v_sonda], (0, 1), (0, grandeza_canal1), ("", sonda_id))
