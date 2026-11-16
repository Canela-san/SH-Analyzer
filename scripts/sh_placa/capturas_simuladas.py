"""As capturas da placa simulada (docs/gui-plan.md, 11.11): ``.bin`` como o ``ler_adc`` grava, com o cabeçalho v9 (o
de hoje: ``struct cabecalho_arquivo`` do ``firmware/ler_adc.c``, campo a campo) e as amostras intercaladas por canal.
O motor (``supraharmonicos/cabecalho.py``) e o agente as leem como as de uma placa de verdade, e a Análise as abre.

**O sinal** (:func:`sinal_da_rede`) é o da bancada do projeto: o canal 1 na tomada (127 V, pelo divisor de
``--ganho 1:19.357``) e o canal 0 na corrente de uma carga não linear (uma sonda de 100 mV/A, ``--ganho 0:10``). Além
da fundamental de 60 Hz e dos harmônicos ímpares, os supraharmônicos de três fontes comuns numa casa: o inversor
fotovoltaico (16 kHz, modulado pela rede), os drivers de LED (perto de 40 kHz, com a frequência de chaveamento
oscilando com a tensão) e uma comunicação pela rede (um tom estreito em 72 kHz), sobre o ruído da bancada.

**O ADC mudo** (:func:`gravar_captura` com ``muda=True``) é o que o ``ler_adc`` deixa quando o SDO fica em 0 (a placa de
aquisição sem alimentação): um bloco só, todo em 0, e a captura interrompida.

O cabeçalho final traz o que o ``ler_adc`` mede em todas as amostras (o CRC delas, o mínimo, o máximo, as saturadas, a
média e o desvio de cada canal): é por ele que o agente vê o sinal parado.
"""

from __future__ import annotations

import hashlib
import math
import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TAXA_TOTAL_HZ = 400_000
AMOSTRAS_POR_BLOCO_DO_FIRMWARE = 1_048_576    # SAMPLES_PER_BUFFER (memoria_pru.h)
BLOCO_DAS_CAPTURAS = AMOSTRAS_POR_BLOCO_DO_FIRMWARE
"""O bloco das capturas simuladas: o do firmware (uma captura de 2 blocos tem 4 MiB). Os testes o diminuem
(``tests/conftest.py``): montam dezenas de placas."""
FAIXA_V = 20.48                               # ±10,24 V no pino (o código 0 do RANGE_SEL do ADS8688)
GRANDEZA_TENSAO, GRANDEZA_CORRENTE = 0, 1     # supraharmonicos/constantes.py
GANHO_DA_CORRENTE = 10.0                      # A por volt no pino: a sonda de 100 mV/A
GANHO_DA_TENSAO = 19.357                      # V por volt no pino: o divisor da tomada da bancada
CANAIS = (0, 1)                               # 0: a corrente; 1: a tensão da tomada
CABECALHO_V9 = 4096
VERSAO_DO_CABECALHO = 9
ATRASOS_CS = (3, 1, 3)                        # ATRASO_CS_*_PADRAO do memoria_pru.h
PROTOCOLO_DA_PRU = 5
MODO_SPI = 2                                  # o SPI rápido, gravando a fase B (75 ns)

# A parte fixa (os campos da v8, nos mesmos bytes desde então) e a extensão da v9, como em supraharmonicos/cabecalho.py.
_FIXA = ("<4sIIQIII8BIIIIIdQQ"          # magic ... total_amostras_gravadas (bytes 0 a 83)
         "272s32sIIII"                  # descrição, kernel, timestamp_ns, relógio sincronizado, uptime, carga
         "8B" + "32s" * 8 + "8B"        # grandeza, sonda e faixa de cada canal (bytes 404 em diante)
         "III3I32sdI"                   # a integridade, os atrasos do CS, a versão do firmware, a taxa medida, os buffers
         "IIII" "III"                   # a grade de tempo da PRU; o SPI
         "128s64s32sIIIIII"             # título, sistema, placa e os discos (a saída e o programa) e a memória
         "I")                           # o CRC do cabeçalho (byte 1020)
_EXTENSAO = "<IQIId16s32s512s8d8H8H8Q8d8d"
_OFFSET_DO_CRC = struct.calcsize(_FIXA) - 4


@dataclass(frozen=True)
class Sistema:
    """O que o ``ler_adc`` grava da placa no cabeçalho (v8): de onde a captura veio."""

    kernel: str
    sistema: str
    placa: str                                # "A335BNLT 00C0 3714BBBK1234", como a EEPROM
    maquina: str = "beaglebone"
    versao_firmware: str = ""
    relogio_sincronizado: bool = True
    ligada_s: int = 8040
    disco_total_kib: int = 0
    disco_livre_kib: int = 0
    memoria_kib: int = 319_488


def sinal_da_rede(n: int, taxa_por_canal: float, semente: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """``(corrente, tensão)``: ``n`` amostras de cada canal, em volts no pino do ADC (ver o módulo)."""
    rng = np.random.default_rng(semente)
    t = np.arange(n) / taxa_por_canal
    rede = 2 * np.pi * (60.0 + rng.uniform(-0.02, 0.02)) * t
    tensao = 127 * math.sqrt(2) * (np.sin(rede) + 0.022 * np.sin(3 * rede + 0.4) + 0.031 * np.sin(5 * rede + 2.1)
                                   + 0.012 * np.sin(7 * rede + 1.0))
    corrente = 2.0 * math.sqrt(2) * (np.sin(rede - 0.35) + 0.28 * np.sin(3 * rede + 0.9)
                                     + 0.14 * np.sin(5 * rede + 2.4) + 0.06 * np.sin(7 * rede + 0.3))
    # O inversor: 16 kHz, mais forte perto dos picos da rede (as bandas laterais em 16 kHz ± 120 Hz).
    inversor = np.sin(2 * np.pi * 16_000 * t + rng.uniform(0, 2 * np.pi)) * (1 + 0.5 * np.sin(2 * rede))
    # Os drivers de LED: o chaveamento entre 38,5 e 41,5 kHz, acompanhando a tensão, e só perto dos picos dela.
    fase_do_led = 2 * np.pi * np.cumsum(40_000 + 1_500 * np.sin(rede)) / taxa_por_canal
    led = np.sin(fase_do_led) * np.abs(np.sin(rede))
    tensao += 0.6 * inversor + 0.25 * led + 0.12 * np.sin(2 * np.pi * 72_000 * t) + rng.normal(0, 0.05, n)
    corrente += 0.08 * inversor + 0.03 * led + rng.normal(0, 0.002, n)
    return corrente / GANHO_DA_CORRENTE, tensao / GANHO_DA_TENSAO


def em_codigos(volts: np.ndarray) -> np.ndarray:
    """Volts no pino para os códigos do ADC (``uint16`` com o zero no meio da faixa), como o ``adc_tool`` lê."""
    return np.clip(np.round((volts + FAIXA_V / 2) / FAIXA_V * 65536), 0, 65535).astype("<u2")


def gravar_captura(caminho: Path, *, inicio: float, blocos: int, sistema: Sistema, titulo: str = "",
                   descricao: str = "", muda: bool = False, semente: int = 0,
                   amostras_por_bloco: int | None = None) -> Path:
    """Grava uma captura de ``blocos`` blocos dos dois canais (de :data:`BLOCO_DAS_CAPTURAS` amostras, sem
    ``amostras_por_bloco``), começada em ``inicio`` (o ``time.time()`` da placa), e põe nela a data do fim, como o
    ``ler_adc`` deixaria. ``muda``: o ADC mudo (um bloco, todo em 0)."""
    caminho = Path(caminho)
    if amostras_por_bloco is None:
        amostras_por_bloco = BLOCO_DAS_CAPTURAS
    k = len(CANAIS)
    if muda:
        blocos = 1
    total = blocos * amostras_por_bloco
    n = total // k
    taxa_por_canal = TAXA_TOTAL_HZ / k
    if muda:
        codigos = np.zeros(total, dtype="<u2")
    else:
        codigos = np.empty(total, dtype="<u2")
        for i, volts in enumerate(sinal_da_rede(n, taxa_por_canal, semente)):
            codigos[i::k] = em_codigos(volts)
    duracao = total / TAXA_TOTAL_HZ
    ganhos = "0:10,1:19.357"
    comando = f"{TAXA_TOTAL_HZ} {','.join(map(str, CANAIS))} --blocos {blocos} --ganho {ganhos} -o {caminho.name}"
    cabecalho = montar_cabecalho(codigos, inicio=inicio, duracao_pedida_s=duracao, blocos=blocos,
                                 amostras_por_bloco=amostras_por_bloco, sistema=sistema, titulo=titulo,
                                 descricao=descricao, comando=comando, identidade=f"{caminho.name}:{semente}")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "wb") as f:
        f.write(cabecalho)
        f.write(codigos.tobytes())
    fim = inicio + duracao
    os.utime(caminho, (fim, fim))
    return caminho


def montar_cabecalho(codigos: np.ndarray, *, inicio: float, duracao_pedida_s: float, blocos: int,
                     amostras_por_bloco: int, sistema: Sistema, titulo: str, descricao: str, comando: str,
                     identidade: str) -> bytes:
    """O cabeçalho final (4096 bytes, com os dois CRCs) de uma captura dos :data:`CANAIS` com estas amostras."""
    k = len(CANAIS)
    total = len(codigos)
    lista = [*CANAIS, *[0xFF] * (8 - k)]
    inicio_s, inicio_ns = int(inicio), int(round((inicio % 1) * 1e9)) % 1_000_000_000
    duracao = total / TAXA_TOTAL_HZ
    grandezas = [GRANDEZA_CORRENTE, GRANDEZA_TENSAO, *[0xFF] * (8 - k)]
    fixa = struct.pack(
        _FIXA, b"SHAN", VERSAO_DO_CABECALHO, CABECALHO_V9, inicio_s, TAXA_TOTAL_HZ, sum(1 << c for c in CANAIS), k,
        *lista, amostras_por_bloco, 2, 200_000_000, 200_000_000 // TAXA_TOTAL_HZ, 0, duracao_pedida_s, blocos, total,
        _texto(descricao, 272), _texto(sistema.kernel, 32), inicio_ns, 1 if sistema.relogio_sincronizado else 0,
        sistema.ligada_s, 310,
        *grandezas, *[b""] * 8, *[0] * k, *[0xFF] * (8 - k),
        0, 0, 0, *ATRASOS_CS, _texto(sistema.versao_firmware, 32), TAXA_TOTAL_HZ * 0.999_996_8 if blocos >= 2 else 0.0, 2,
        18, 0, 2, PROTOCOLO_DA_PRU, MODO_SPI, 0, 0,
        _texto(titulo, 128), _texto(sistema.sistema, 64), _texto(sistema.placa, 32),
        sistema.disco_total_kib, sistema.disco_livre_kib, sistema.disco_livre_kib, sistema.disco_total_kib,
        sistema.disco_livre_kib, sistema.memoria_kib, 0)
    por_canal = [codigos[i::k] for i in range(k)]
    medias = [float(c.mean(dtype=np.float64)) for c in por_canal]
    fim = inicio + duracao
    extensao = struct.pack(
        _EXTENSAO, zlib.crc32(codigos.tobytes()), int(fim), int(round((fim % 1) * 1e9)) % 1_000_000_000, 161,
        duracao + 0.003, hashlib.sha256(identidade.encode()).digest()[:16], _texto(sistema.maquina, 32),
        _texto(comando, 512), GANHO_DA_CORRENTE, GANHO_DA_TENSAO, *[0.0] * (8 - k),
        *_oito(int(c.min()) for c in por_canal), *_oito(int(c.max()) for c in por_canal),
        *_oito(int(np.count_nonzero((c == 0) | (c == 65535))) for c in por_canal),
        *_oito(medias, 0.0), *_oito((float(c.std(dtype=np.float64)) for c in por_canal), 0.0))
    bruto = bytearray(fixa.ljust(1024, b"\x00") + extensao)
    bruto += bytes(CABECALHO_V9 - len(bruto))
    struct.pack_into("<I", bruto, _OFFSET_DO_CRC, zlib.crc32(bytes(bruto)))
    return bytes(bruto)


def _texto(valor: str, tamanho: int) -> bytes:
    """Um campo de texto do cabeçalho: UTF-8, cortado para caber com o nulo do fim."""
    return valor.encode("utf-8")[:tamanho - 1]


def _oito(valores, vazio=0) -> list:
    valores = list(valores)
    return [*valores, *[vazio] * (8 - len(valores))]
