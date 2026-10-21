"""Gerador de capturas sintéticas (``.bin`` com cabeçalho "SHAN") para os testes.

Não precisa de hardware: monta o ``.bin`` exatamente como ``firmware/ler_adc.c``
gravaria (cabeçalho de 1024 B v1, v2 ou v3 + amostras intercaladas), a partir de
sinais em Volts no pino do ADC. Também sintetiza uma "sonda" de resposta em
frequência CONHECIDA (passa-baixa de 1ª ordem, fc = 30 kHz) para os testes de
calibração/correção.

Convenção do ADC (a mesma de ``adc_tool``): ``uint16`` com offset = faixa/2.

Faixa do ADC: por padrão o cabeçalho é v2 (que não registra a faixa) e as amostras são codificadas com
``FAIXA`` = 20.48 V totais -- a faixa de reset do ADC, que as ferramentas assumem sem cabeçalho v3. Com ``faixas_adc_total_v=(...)`` (um valor
por canal: 20.48, 10.24 ou 5.12) o cabeçalho sai v3, com o código de faixa de cada canal, e cada canal é
codificado com a SUA faixa, como o ADS8688 faria.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

FAIXA = 20.48            # V (ADS8688 +-FAIXA/2 em uint16): a faixa de reset, a que as ferramentas assumem sem cabeçalho v3
FS_TOTAL_2CH = 400_000   # Hz, total -> 200 kHz por canal com 2 canais
R_SHUNT = 0.1            # ohm
SENS_NOMINAL = 0.1       # V/A (sonda 100 mV/A -> --ganho 10)

# 19 pontos ~log-espaçados: com poucos pontos o erro de INTERPOLAÇÃO (PCHIP)
# domina -- medido na auditoria para esta sonda de 1 polo: 7 pts -> 1,9 %,
# 12 -> 0,6 %, 18 -> 0,17 %, 25 -> 0,06 % (docs/probe-profile-audit.md).
FREQS_CAL = [100, 150, 220, 330, 470, 680, 1000, 1500, 2200, 3300, 4700, 6800,
             10000, 15000, 22000, 33000, 47000, 68000, 80000]
TONS_PRODUCAO = [(50.0, 10.0), (2500.0, 0.2), (9000.0, 0.1), (20000.0, 0.1), (40000.0, 0.1)]

FMT_V1 = "<4sIIQIII8BIIIIIdQQ64s256sI"
FMT_V2 = "<4sIIQIII8BIIIIIdQQ64s256s8B" + "32s" * 8 + "I"
FMT_V3 = "<4sIIQIII8BIIIIIdQQ64s256s8B" + "32s" * 8 + "8BI"
FMT_V4 = "<4sIIQIII8BIIIIIdQQ64s256s8B" + "32s" * 8 + "8BIII3II"
FMT_V5 = "<4sIIQIII8BIIIIIdQQ64s256s8B" + "32s" * 8 + "8BIII3I32sdI"
CODIGO_DA_FAIXA = {20.48: 0, 10.24: 1, 5.12: 2}   # fundo de escala total (V) -> código RANGE_SELn


def planta_h(f, fc_lp: float = 30e3, fc_hp: float = 5.0):
    """Magnitude 'verdadeira' (linear) da sonda simulada."""
    f = np.asarray(f, dtype=np.float64)
    return 1.0 / np.sqrt(1.0 + (f / fc_lp) ** 2) / np.sqrt(1.0 + (fc_hp / np.maximum(f, 1e-9)) ** 2)


def volts_para_codigos(v: np.ndarray, formato: str = "uint16", faixa: float = FAIXA) -> np.ndarray:
    if formato == "uint16":
        return np.clip(np.round((v + faixa / 2) / faixa * 65536), 0, 65535).astype("<u2")
    return np.clip(np.round(v / faixa * 32768), -32768, 32767).astype("<i2")


def montar_cabecalho(n_por_canal: int, canais, grandezas, sondas, fs_total: int,
                     versao: int = 2, titulo: str = "teste", descricao: str = "sintetico",
                     crc_valido: bool = True, total_amostras: int | None = None,
                     codigos_faixa_adc=None, integridade=(0, 0, 0), atrasos_cs=(200, 100, 100),
                     amostras_por_buffer: int = 1048576, versao_firmware: str = "v0.0-teste",
                     taxa_medida_hz: float = 0.0) -> bytes:
    """Cabeçalho de 1024 bytes (v1 a v5) com CRC-32 correto (ou propositalmente errado).

    ``codigos_faixa_adc`` (v3+): um código de faixa por canal (padrão: 0 = ±10,24 V em todos).
    ``integridade`` (v4): (amostras_atrasadas, buffers_sobrescritos, quadros_preambulo_ruim); ``atrasos_cs`` (v4):
    as iterações de setup/hold/alto do CS. ``amostras_por_buffer``: o tamanho do bloco da PRU (o do firmware é
    1.048.576; menor, para um teste ter trocas de buffer numa captura curta). ``versao_firmware`` e
    ``taxa_medida_hz`` (v5): o git describe do build e a taxa medida pelo ARM (0 = não medida)."""
    k = len(canais)
    lista = list(canais) + [0xFF] * (8 - k)
    mascara = sum(1 << c for c in canais)
    total = k * n_por_canal if total_amostras is None else total_amostras
    comuns = [b"SHAN", versao, 1024, 1_700_000_000, int(fs_total), mascara, k, *lista,
              amostras_por_buffer, 2, 200_000_000, 200_000_000 // int(fs_total), 0, n_por_canal / (fs_total / k), 1, total,
              titulo.encode("utf-8"), descricao.encode("utf-8")]
    if versao >= 3:
        gr = list(grandezas) + [0xFF] * (8 - k)
        ids = [s.encode("ascii") for s in sondas] + [b""] * (8 - k)
        codigos = list(codigos_faixa_adc if codigos_faixa_adc is not None else [0] * k) + [0xFF] * (8 - k)
        if versao >= 5:
            fmt, vals = FMT_V5, [*comuns, *gr, *ids, *codigos, *integridade, *atrasos_cs,
                                 versao_firmware.encode("ascii"), float(taxa_medida_hz), 0]
        elif versao >= 4:
            fmt, vals = FMT_V4, [*comuns, *gr, *ids, *codigos, *integridade, *atrasos_cs, 0]
        else:
            fmt, vals = FMT_V3, [*comuns, *gr, *ids, *codigos, 0]
    elif versao >= 2:
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


def regravar_crc(caminho: Path) -> None:
    """Recalcula o CRC-32 do cabeçalho depois de um teste editar um campo dele (título, descrição...), para que
    o teste confira só o efeito da edição -- e não o de um CRC quebrado."""
    bruto = bytearray(Path(caminho).read_bytes())
    versao = struct.unpack_from("<I", bruto, 4)[0]
    fmt = (FMT_V5 if versao >= 5 else FMT_V4 if versao == 4 else FMT_V3 if versao == 3
           else FMT_V2 if versao == 2 else FMT_V1)
    deslocamento_crc = struct.calcsize(fmt) - 4
    struct.pack_into("<I", bruto, deslocamento_crc, 0)
    struct.pack_into("<I", bruto, deslocamento_crc, zlib.crc32(bytes(bruto[:1024])))
    Path(caminho).write_bytes(bytes(bruto))


def escrever_bin(caminho: Path, canais_v, canais=(0, 1), grandezas=(0, 1), sondas=("", ""),
                 fs_total: int = FS_TOTAL_2CH, formato: str = "uint16", com_cabecalho: bool = True,
                 faixas_adc_total_v=None, **kw_cabecalho) -> Path:
    """Grava um '.bin'. ``canais_v``: um array de Volts por canal, na ordem de ``canais``.

    ``faixas_adc_total_v``: fundo de escala total (V) de cada canal -- 20.48, 10.24 ou 5.12 (um valor por canal,
    ou um só para todos). Dá cabeçalho v3 e codifica cada canal com a sua faixa."""
    caminho = Path(caminho)
    k = len(canais)
    n = min(len(c) for c in canais_v)
    if faixas_adc_total_v is not None:
        faixas = [float(f) for f in (faixas_adc_total_v if hasattr(faixas_adc_total_v, "__len__") else [faixas_adc_total_v] * k)]
        kw_cabecalho.setdefault("versao", 3)
        kw_cabecalho.setdefault("codigos_faixa_adc", [CODIGO_DA_FAIXA[f] for f in faixas])
    else:
        faixas = [FAIXA] * k
    codigos = np.empty(k * n, dtype="<u2" if formato == "uint16" else "<i2")
    for i, c in enumerate(canais_v):
        codigos[i::k] = volts_para_codigos(np.asarray(c[:n], dtype=np.float64), formato, faixas[i])
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


def criar_pasta_calibracao_1canal(pasta: Path, freqs=FREQS_CAL, canal: int = 3, corrente_a: float = 1.0,
                                  nome_sonda: str = "sonda_teste", com_referencia_externa: bool = True,
                                  fs_total: int = 200_000) -> Path:
    """Pasta no formato de ``calibrar_sonda.sh`` com UM canal só (a sonda) e, opcionalmente, o
    ``referencia_externa.csv`` com a tensão RMS lida "no osciloscópio" sobre o shunt (``R_SHUNT``)."""
    pasta.mkdir(parents=True, exist_ok=True)
    linhas = ["arquivo,v_shunt_rms_V"]
    for k, f in enumerate(freqs):
        _, v_sonda = captura_calibracao(f, seed=2000 + k, fs_canal=float(fs_total))
        nome = f"calibracao_{f}Hz_rep1.bin"
        escrever_bin(pasta / nome, [v_sonda * corrente_a], (canal,), (1,), (nome_sonda,), fs_total=fs_total)
        linhas.append(f"{nome},{R_SHUNT * corrente_a / np.sqrt(2):.6f}")
    if com_referencia_externa:
        (pasta / "referencia_externa.csv").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return pasta


def passa_baixa_2a_ordem(f, fc: float = 15e3):
    """Magnitude (linear) de um Butterworth de 2ª ordem -- o filtro interno do ADS8688 (~15 kHz, datasheet 8.3.5)."""
    return 1.0 / np.sqrt(1.0 + (np.asarray(f, dtype=np.float64) / fc) ** 4)


def escrever_m_osciloscopio(caminho: Path, valores: np.ndarray, fs: float) -> Path:
    """``.m`` no estilo de um osciloscópio: escalares do tempo + um vetor ``Y``."""
    corpo = " ".join(f"{x:.9g}" for x in valores)
    Path(caminho).write_text(f"% forma de onda sintetica\nTinterval = {1.0 / fs:.12g};\nTstart = 0;\nY = [{corpo}];\n", encoding="utf-8")
    return Path(caminho)


def criar_pasta_amplitude_conhecida(pasta: Path, freqs=FREQS_CAL, canal: int = 3, amplitudes=lambda f: "500mVpp",
                                    fc: float = 15e3, fs_total: int = 200_000, dur_s: float = 0.5,
                                    nome_sonda: str = "sonda_teste", metadados: bool = True, erro_gerador: float = 1.0,
                                    nomes_livres: bool = False, osciloscopio: bool = False, ganho_nominal: float = 1.0) -> Path:
    """Pasta de calibração com 1 canal, injetando uma senoide de amplitude CONHECIDA e medindo o conjunto
    (passa-baixa de 2ª ordem em ``fc``). ``amplitudes(f)`` dá o texto ajustado no gerador (vai para ``ref: amp=``);
    o que o gerador de fato entrega é ``erro_gerador`` vezes isso (o ADC e o osciloscópio veem o valor real, o
    metadado guarda o valor do mostrador). ``osciloscopio`` grava ao lado de cada ``.bin`` um ``.m`` com o sinal real.
    ``ganho_nominal``: o ADC mede ``V_real * H(f)`` e é isso que ``--ganho`` converte em grandeza física."""
    from supraharmonicos.referencia import analisar_amplitude, formatar_referencia

    pasta.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    n = int(dur_s * fs_total)
    for k, f in enumerate(freqs):
        texto = amplitudes(f)
        pico_real = analisar_amplitude(texto).pico * erro_gerador
        f_real = f * (1 + rng.uniform(-0.004, 0.004))                  # o gerador nunca acerta a frequência do mostrador
        fase = rng.uniform(0, 2 * np.pi)
        t = np.arange(n) / fs_total
        v_adc = pico_real * float(passa_baixa_2a_ordem(f_real, fc)) * np.sin(2 * np.pi * f_real * t + fase) + rng.normal(0, 5e-4, n)
        nome = f"medicao_{k:02d}.bin" if nomes_livres else f"calibracao_{f}Hz_rep1.bin"
        descricao = formatar_referencia(f, texto) if metadados else "sem metadados"
        escrever_bin(pasta / nome, [v_adc], (canal,), (1,), (nome_sonda,), fs_total=fs_total, descricao=descricao)
        if osciloscopio:
            fs_osc = 200.0 * f_real                                       # 20 ciclos, 200 amostras por ciclo
            v_osc = pico_real * np.sin(2 * np.pi * f_real * np.arange(4000) / fs_osc + fase) + rng.normal(0, 2e-3, 4000)
            escrever_m_osciloscopio(pasta / (Path(nome).stem + ".m"), v_osc, fs_osc)
    return pasta
