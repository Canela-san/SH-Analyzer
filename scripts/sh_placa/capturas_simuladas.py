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
VALOR_DESCONHECIDO = 0xFFFFFFFF               # num campo numérico do sistema: o ler_adc não conseguiu ler

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
    disco_total_kib: int = 0                  # o cartão: o disco do programa e o da captura num arquivo
    disco_livre_kib: int = 0
    memoria_kib: int = 319_488
    disco_livre_fim_kib: int | None = None    # o livre no fim da captura (None: o do início)
    saida_no_disco: bool = True               # False: a saída contínua, cujo disco é o de quem recebe (desconhecido)


def _disco_da_saida(sistema: Sistema, final: bool) -> tuple[int, int, int]:
    """O total, o livre no início e o livre no fim do disco da captura, como o ``ler_adc`` os grava: desconhecidos na
    saída contínua; o do fim, só no cabeçalho final."""
    if not sistema.saida_no_disco:
        return VALOR_DESCONHECIDO, VALOR_DESCONHECIDO, VALOR_DESCONHECIDO
    fim = sistema.disco_livre_kib if sistema.disco_livre_fim_kib is None else sistema.disco_livre_fim_kib
    return sistema.disco_total_kib, sistema.disco_livre_kib, fim if final else VALOR_DESCONHECIDO


def sinal_da_rede(n: int, taxa_por_canal: float, semente: int = 0, *, inicio: int = 0,
                  fase_da_rede: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """``(corrente, tensão)``: ``n`` amostras de cada canal, em volts no pino do ADC (ver o módulo), a partir da
    amostra ``inicio`` (o sinal continua de um pedaço para o outro: a rede, o inversor e os LEDs são os da mesma
    ``semente``; o ruído, de cada pedaço). ``fase_da_rede``: a fase da fundamental e dos harmônicos (as outras fases
    de um sistema trifásico)."""
    parametros = np.random.default_rng(semente)
    f_rede = 60.0 + parametros.uniform(-0.02, 0.02)
    fase_do_inversor = parametros.uniform(0, 2 * np.pi)
    ruido = np.random.default_rng([semente, inicio])
    t = (inicio + np.arange(n)) / taxa_por_canal
    rede = 2 * np.pi * f_rede * t + fase_da_rede
    tensao = 127 * math.sqrt(2) * (np.sin(rede) + 0.022 * np.sin(3 * rede + 0.4) + 0.031 * np.sin(5 * rede + 2.1)
                                   + 0.012 * np.sin(7 * rede + 1.0))
    corrente = 2.0 * math.sqrt(2) * (np.sin(rede - 0.35) + 0.28 * np.sin(3 * rede + 0.9)
                                     + 0.14 * np.sin(5 * rede + 2.4) + 0.06 * np.sin(7 * rede + 0.3))
    # O inversor: 16 kHz, mais forte perto dos picos da rede (as bandas laterais em 16 kHz ± 120 Hz).
    inversor = np.sin(2 * np.pi * 16_000 * t + fase_do_inversor) * (1 + 0.5 * np.sin(2 * rede))
    # Os drivers de LED: o chaveamento entre 38,5 e 41,5 kHz, acompanhando a tensão, e só perto dos picos dela (a fase
    # é a integral da frequência, em forma fechada: contínua de um pedaço para o outro).
    fase_do_led = 2 * np.pi * 40_000 * t - 1_500 / f_rede * np.cos(rede)
    led = np.sin(fase_do_led) * np.abs(np.sin(rede))
    tensao += 0.6 * inversor + 0.25 * led + 0.12 * np.sin(2 * np.pi * 72_000 * t) + ruido.normal(0, 0.05, n)
    corrente += 0.08 * inversor + 0.03 * led + ruido.normal(0, 0.002, n)
    return corrente / GANHO_DA_CORRENTE, tensao / GANHO_DA_TENSAO


FAIXAS_V = (20.48, 10.24, 5.12)               # o código de cada faixa é a posição (FAIXA_ADC_ESPAN_V do C)


def em_codigos(volts: np.ndarray, faixa_v: float = FAIXA_V) -> np.ndarray:
    """Volts no pino para os códigos do ADC (``uint16`` com o zero no meio da faixa), como o ``adc_tool`` lê: o que
    passa da faixa fica no fundo de escala (a saturação do ADC)."""
    return np.clip(np.round((volts + faixa_v / 2) / faixa_v * 65536), 0, 65535).astype("<u2")


def grandeza_do_canal(canal: int) -> int:
    """O que cada canal da placa simulada mede: os pares são a corrente; os ímpares, a tensão (o 0 e o 1 da bancada;
    o 2 e o 3, o 4 e o 5, as outras fases)."""
    return GRANDEZA_CORRENTE if canal % 2 == 0 else GRANDEZA_TENSAO


def codigos_do_bloco(canais: tuple[int, ...], taxa_total_hz: float, amostras_por_bloco: int, bloco: int,
                     semente: int = 0, faixas: tuple[float, ...] = ()) -> np.ndarray:
    """As amostras intercaladas do bloco ``bloco`` (a partir de 0) de uma captura contínua dos ``canais``: a amostra
    ``p`` da captura é do canal ``canais[p % k]`` (um bloco não tem um número inteiro de varreduras com 3, 5, 6 ou 7
    canais), e o sinal de cada canal continua de um bloco para o outro. ``faixas``: a faixa total de cada canal (a do
    ``--faixa-adc``; sem ela, ±10,24 V)."""
    k = len(canais)
    taxa_por_canal = taxa_total_hz / k
    codigos = np.empty(amostras_por_bloco, dtype="<u2")
    primeira = bloco * amostras_por_bloco
    for j, canal in enumerate(canais):
        i0 = (j - primeira) % k                         # a 1ª posição do canal j neste bloco
        n = len(range(i0, amostras_por_bloco, k))
        if not n:
            continue
        corrente, tensao = sinal_da_rede(n, taxa_por_canal, semente, inicio=(primeira + i0) // k,
                                         fase_da_rede=-2 * np.pi / 3 * ((canal // 2) % 3))
        codigos[i0::k] = em_codigos(corrente if grandeza_do_canal(canal) == GRANDEZA_CORRENTE else tensao,
                                    faixas[j] if faixas else FAIXA_V)
    return codigos


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
    configuracao = Configuracao(CANAIS, TAXA_TOTAL_HZ, amostras_por_bloco, duracao, titulo, descricao, comando,
                                ganhos=(GANHO_DA_CORRENTE, GANHO_DA_TENSAO))
    medido = Medida(k)
    medido.somar(codigos)
    fim = medido.fim(inicio + duracao, duracao + 0.003, pior_bloco_ms=161,
                     taxa_medida_hz=TAXA_TOTAL_HZ * 0.999_996_8 if blocos >= 2 else 0.0)
    cabecalho = montar_cabecalho(configuracao, inicio=inicio, sistema=sistema, identidade=f"{caminho.name}:{semente}",
                                 fim=fim)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "wb") as f:
        f.write(cabecalho)
        f.write(codigos.tobytes())
    os.utime(caminho, (inicio + duracao, inicio + duracao))
    return caminho


@dataclass(frozen=True)
class Configuracao:
    """O que o cabeçalho guarda do pedido de uma captura (a linha de comando do ``ler_adc``)."""

    canais: tuple[int, ...] = CANAIS
    taxa_total_hz: int = TAXA_TOTAL_HZ
    amostras_por_bloco: int = AMOSTRAS_POR_BLOCO_DO_FIRMWARE
    duracao_pedida_s: float = 0.0
    titulo: str = ""
    descricao: str = ""
    comando: str = ""
    grandezas: tuple[int, ...] = ()       # a de cada canal; sem ela, a da placa simulada (grandeza_do_canal)
    ganhos: tuple[float, ...] = ()        # o --ganho de cada canal; 0 = não declarado
    faixas: tuple[float, ...] = ()        # a faixa total de cada canal (FAIXAS_V); sem ela, ±10,24 V
    sondas: tuple[str, ...] = ()          # o --sonda de cada canal; "" = nenhuma
    modo_spi: int = MODO_SPI
    atrasos_cs: tuple[int, int, int] = ATRASOS_CS


@dataclass(frozen=True)
class Fim:
    """O que o ``ler_adc`` mede em todas as amostras e grava no cabeçalho final (os campos [final] da v9)."""

    blocos: int
    amostras: int
    crc32: int
    instante: float                       # o time.time() da placa no último bloco
    duracao_s: float
    pior_bloco_ms: int
    taxa_medida_hz: float
    minimos: tuple[int, ...]
    maximos: tuple[int, ...]
    saturadas: tuple[int, ...]
    medias: tuple[float, ...]
    desvios: tuple[float, ...]
    integridade: tuple[int, int, int] = (0, 0, 0)    # as amostras atrasadas, os buffers sobrescritos, o preâmbulo


class Medida:
    """O CRC e o sinal de cada canal, somados bloco a bloco como o ``ler_adc`` (o canal pela posição na captura)."""

    def __init__(self, num_canais: int):
        self.k = num_canais
        self.amostras = 0
        self.crc = 0
        self.minimos = [65535] * num_canais
        self.maximos = [0] * num_canais
        self.saturadas = [0] * num_canais
        self.contadas = [0] * num_canais
        self.somas = [0] * num_canais
        self.quadrados = [0.0] * num_canais

    def somar(self, codigos: np.ndarray) -> None:
        self.crc = zlib.crc32(codigos.tobytes(), self.crc)
        for j in range(self.k):
            canal = codigos[(j - self.amostras) % self.k::self.k]
            if not len(canal):
                continue
            x = canal.astype(np.int64) - 32768
            self.minimos[j] = min(self.minimos[j], int(canal.min()))
            self.maximos[j] = max(self.maximos[j], int(canal.max()))
            self.saturadas[j] += int(np.count_nonzero((canal == 0) | (canal == 65535)))
            self.contadas[j] += len(canal)
            self.somas[j] += int(x.sum())
            self.quadrados[j] += float(np.dot(x.astype(np.float64), x.astype(np.float64)))
        self.amostras += len(codigos)

    def fim(self, instante: float, duracao_s: float, *, pior_bloco_ms: int, taxa_medida_hz: float, blocos: int = 0,
            integridade: tuple[int, int, int] = (0, 0, 0)) -> Fim:
        medias = [s / n if n else 0.0 for s, n in zip(self.somas, self.contadas)]
        desvios = [math.sqrt(max(q / n - m * m, 0.0)) if n else 0.0
                   for q, n, m in zip(self.quadrados, self.contadas, medias)]
        return Fim(blocos or 0, self.amostras, self.crc, instante, duracao_s, pior_bloco_ms, taxa_medida_hz,
                   tuple(self.minimos), tuple(self.maximos), tuple(self.saturadas),
                   tuple(32768.0 + m if n else 0.0 for m, n in zip(medias, self.contadas)), tuple(desvios),
                   integridade)


def montar_cabecalho(configuracao: Configuracao, *, inicio: float, sistema: Sistema, identidade: str,
                     fim: Fim | None) -> bytes:
    """O cabeçalho v9 (4096 bytes, com o CRC) de uma captura: o provisório (``fim`` ``None``: o que o ``ler_adc``
    manda antes do 1º bloco, com os campos [final] zerados) ou o final."""
    c = configuracao
    k = len(c.canais)
    lista = [*c.canais, *[0xFF] * (8 - k)]
    inicio_s, inicio_ns = int(inicio), int(round((inicio % 1) * 1e9)) % 1_000_000_000
    grandezas = list(c.grandezas or (grandeza_do_canal(canal) for canal in c.canais))
    faixas = [FAIXAS_V.index(f) for f in c.faixas] if c.faixas else [0] * k
    sondas = [_texto(s, 32) for s in c.sondas] if c.sondas else [b""] * k
    ticks = 200_000_000 // c.taxa_total_hz
    blocos, total = (fim.blocos or fim.amostras // c.amostras_por_bloco, fim.amostras) if fim else (0, 0)
    integridade = fim.integridade if fim else (0, 0, 0)
    fixa = struct.pack(
        _FIXA, b"SHAN", VERSAO_DO_CABECALHO, CABECALHO_V9, inicio_s, c.taxa_total_hz, sum(1 << n for n in c.canais), k,
        *lista, c.amostras_por_bloco, 2, 200_000_000, ticks, 0, c.duracao_pedida_s, blocos, total,
        _texto(c.descricao, 272), _texto(sistema.kernel, 32), inicio_ns, 1 if sistema.relogio_sincronizado else 0,
        sistema.ligada_s, 310,
        *grandezas, *[0xFF] * (8 - k), *sondas, *[b""] * (8 - k), *faixas, *[0xFF] * (8 - k),
        *integridade, *c.atrasos_cs, _texto(sistema.versao_firmware, 32), fim.taxa_medida_hz if fim else 0.0, 2,
        18, 0, 2 if fim else 0, PROTOCOLO_DA_PRU, c.modo_spi, 0, 0,
        _texto(c.titulo, 128), _texto(sistema.sistema, 64), _texto(sistema.placa, 32),
        *_disco_da_saida(sistema, fim is not None), sistema.disco_total_kib, sistema.disco_livre_kib,
        sistema.memoria_kib, 0)
    ganhos = [*c.ganhos, *[0.0] * (8 - len(c.ganhos))]
    if fim is None:
        finais = [0, 0, 0, 0, 0.0]
        sinal = [0] * 8 * 3 + [0.0] * 8 * 2           # o mínimo, o máximo e as saturadas; a média e o desvio
    else:
        final = fim.instante
        finais = [fim.crc32, int(final), int(round((final % 1) * 1e9)) % 1_000_000_000, fim.pior_bloco_ms,
                  fim.duracao_s]
        sinal = [*_oito(fim.minimos), *_oito(fim.maximos), *_oito(fim.saturadas), *_oito(fim.medias, 0.0),
                 *_oito(fim.desvios, 0.0)]
    extensao = struct.pack(_EXTENSAO, *finais, hashlib.sha256(identidade.encode()).digest()[:16],
                           _texto(sistema.maquina, 32), _texto(c.comando, 512), *ganhos, *sinal)
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
