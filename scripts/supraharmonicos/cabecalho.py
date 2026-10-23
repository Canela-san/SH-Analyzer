"""Cabeçalho binário do ``.bin`` (formato "SHAN").

Interpreta e valida o cabeçalho fixo de 1024 bytes gravado por
``firmware/ler_adc.c`` (``struct cabecalho_arquivo``): magic, versão (v1 a v6),
CRC-32, metadados da captura, grandeza, id de sonda e faixa de entrada do ADC
por canal.

Depende de: ``constantes``, ``erros``. Quem o consome: ``contexto``,
``hdf5``, ``modos``, ``calibracao_sonda``, ``cli_medir_captura``."""

import logging
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .constantes import (
    ADS8688_MAX_CANAIS,
    FAIXAS_ADC_TOTAL_V,
    FORMATOS_NUMPY,
    GRANDEZA_PADRAO,
    NOMES_GRANDEZA,
)
from .erros import ErroSHAN

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 0. Cabeçalho binário do '.bin' (formato "SHAN")
# ---------------------------------------------------------------------------
# A partir da versão do firmware que passou a gravar um cabeçalho fixo de
# 1024 bytes no início de cada captura (ver firmware/ler_adc.c, struct
# cabecalho_arquivo), todo '.bin' NOVO tem essa estrutura antes das amostras
# brutas. Arquivos mais antigos (sem cabeçalho) continuam suportados -- ver
# ler_cabecalho(), que detecta a ausência do magic number e retorna None
# nesse caso, deixando o chamador (main()) cair de volta no comportamento
# pré-cabeçalho.

CABECALHO_MAGIC = b"SHAN"
CABECALHO_TAMANHO_TOTAL = 1024
CABECALHO_VERSAO_SUPORTADA = 7  # versão mais recente do FORMATO do cabeçalho que este script sabe interpretar

# [SONDA/GRANDEZA] Tamanho fixo (bytes, incluindo terminador nulo) do id de
# sonda por canal na v2 do cabeçalho -- precisa bater com
# CABECALHO_SONDA_ID_TAMANHO em firmware/ler_adc.c (mesma situação de
# ADS8688_MAX_CANAIS: sincronia manual, sem arquivo de constantes
# compartilhado entre C e Python).
CABECALHO_SONDA_ID_TAMANHO = 32
CABECALHO_VERSAO_FIRMWARE_TAMANHO = 32   # [v5] CABECALHO_VERSAO_FIRMWARE_TAMANHO em firmware/ler_adc.c

# Format strings para struct.unpack, campo a campo -- espelham EXATAMENTE
# 'struct cabecalho_arquivo_campos' em firmware/ler_adc.c (packed, sem
# padding de alinhamento entre campos), em cada versão do formato. O
# prefixo '<' (little-endian) é o que garante a correspondência com
# __attribute__((packed)) do lado C: os prefixos de byte-order explícitos
# do módulo struct ('<', '>', '=', '!') desligam o padding "nativo" que
# '@'/nenhum prefixo aplicariam -- '<' também é o byte-order real da
# plataforma (BeagleBone: ARM Cortex-A8, little-endian).
#
# v1 (campos originais, sem grandeza/sonda):
#   4s   magic                        (4 bytes, ASCII "SHAN", NÃO terminado em nulo)
#   I    versao_cabecalho             (uint32_t)
#   I    tamanho_cabecalho            (uint32_t)
#   Q    timestamp_unix               (uint64_t, epoch Unix UTC)
#   I    frequencia_hz                (uint32_t)
#   I    auto_seq_mask                (uint32_t)
#   I    num_canais                   (uint32_t)
#   8B   lista_canais                 (8x uint8_t -- slots não usados = 0xFF)
#   I    samples_per_buffer           (uint32_t)
#   I    bytes_por_amostra            (uint32_t)
#   I    pru_clock_hz                 (uint32_t)
#   I    sample_period_ticks          (uint32_t)
#   I    primeira_amostra_descartada  (uint32_t, 0/1 como booleano)
#   d    duracao_pedida_segundos      (double, 8 bytes)
#   Q    blocos_gravados              (uint64_t)
#   Q    total_amostras_gravadas      (uint64_t)
#   64s  titulo                       (64 bytes, UTF-8, terminado em nulo + zero-padding)
#   256s descricao                    (256 bytes, UTF-8, terminado em nulo + zero-padding)
#   I    header_crc32                 (uint32_t, CRC-32/ISO-HDLC dos 1024 bytes com este campo zerado)
#
# v2 (mesmos campos acima, mais grandeza_por_canal/sonda_id_por_canal
# inseridos ENTRE descricao e header_crc32 -- ver docs/probe-correction-design.md):
#   8B   grandeza_por_canal           (8x uint8_t -- GRANDEZA_TENSAO/CORRENTE/TEMPERATURA/NAO_USADA)
#   32s * 8  sonda_id_por_canal       (8 strings de 32 bytes, uma por canal, terminadas em nulo)
#   I    header_crc32
#
# v3 (mesmos campos da v2, mais faixa_adc_por_canal inserido ENTRE
# sonda_id_por_canal e header_crc32):
#   8B   faixa_adc_por_canal          (8x uint8_t -- código de faixa do ADS8688 que cada canal usou:
#                                      0 = ±10,24 V, 1 = ±5,12 V, 2 = ±2,56 V; slot não usado = 0xFF.
#                                      Mesma indexação de lista_canais.)
#   I    header_crc32
#
# v4 (mesmos campos da v3, mais a integridade da captura ENTRE
# faixa_adc_por_canal e header_crc32 -- ver memoria_pru.h):
#   I    amostras_atrasadas           (a PRU não acompanhou a taxa pedida nessas amostras)
#   I    buffers_sobrescritos         (o ARM não copiou o buffer a tempo: amostras perdidas)
#   I    quadros_preambulo_ruim       (ruído na linha SDO durante o comando)
#   3I   atraso_cs_iteracoes          (setup, hold, alto do laço da PRU, em iterações de 10 ns)
#   I    header_crc32
#
# v5 (mesmos campos da v4, mais ENTRE atraso_cs_iteracoes e header_crc32):
#   32s  versao_firmware              (git describe do build do ler_adc, terminado em nulo)
#   d    taxa_medida_hz               (taxa total medida pelo relógio do ARM; 0 = não medida, < 2 blocos)
#   I    buffers_ping_pong            (quantos buffers de samples_per_buffer a PRU alterna na DDR; hoje 2)
#   I    header_crc32
#
# v6 (mesmos campos da v5, mais a grade de tempo publicada pela PRU ENTRE buffers_ping_pong e header_crc32 -- ver
# memoria_pru.h):
#   I    folga_minima_ciclos          (menor folga da captura, ciclos de 5 ns; > 0 = toda amostra no ciclo da grade)
#   I    atraso_maximo_ciclos         (maior atraso das amostras atrasadas, ciclos; 0 se nenhuma)
#   I    ciclos_rebase                (ciclos entre as duas leituras do contador no rebase, medidos pela PRU)
#   I    versao_protocolo_pru         (VERSAO_PROTOCOLO_PRU que a PRU escreveu; 2 desde 22/10/2026, 3 com o SPI rápido, 4 com o início sem corrida, 23/10)
#   I    header_crc32
#
# v7 (mesmos campos da v6, mais o SPI ENTRE versao_protocolo_pru e header_crc32 -- ver memoria_pru.h):
#   I    modo_spi                     (0 = lento, ~10,7 MHz; 1, 2, 3 = rápido, ~15,4 MHz, gravando a fase A, B ou C)
#   I    divergencias_fase_a          (quadros do SPI rápido em que a leitura a 60 ns discordou da de 75 ns)
#   I    divergencias_fase_c          (idem, a de 90 ns)
#   I    header_crc32
_FORMATO_CABECALHO_V1 = "<4sIIQIII8BIIIIIdQQ64s256sI"
_FORMATO_CABECALHO_V2 = "<4sIIQIII8BIIIIIdQQ64s256s8B" + "32s" * ADS8688_MAX_CANAIS + "I"
_FORMATO_CABECALHO_V3 = "<4sIIQIII8BIIIIIdQQ64s256s8B" + "32s" * ADS8688_MAX_CANAIS + "8BI"
_FORMATO_CABECALHO_V4 = "<4sIIQIII8BIIIIIdQQ64s256s8B" + "32s" * ADS8688_MAX_CANAIS + "8BIII3II"
_FORMATO_CABECALHO_V5 = ("<4sIIQIII8BIIIIIdQQ64s256s8B" + "32s" * ADS8688_MAX_CANAIS + "8BIII3I"
                         + f"{CABECALHO_VERSAO_FIRMWARE_TAMANHO}sdII")
_FORMATO_CABECALHO_V6 = _FORMATO_CABECALHO_V5[:-1] + "IIII" + "I"
_FORMATO_CABECALHO_V7 = _FORMATO_CABECALHO_V6[:-1] + "III" + "I"

# Contagens de valores por campo, na mesma ordem do format string -- usadas
# por _consumir() para dividir a tupla plana devolvida por struct.unpack.
# Cada entrada é 1 (campo escalar) ou N (campo com N valores, ex.: 8 para
# lista_canais/grandeza_por_canal, que vêm de "8B"). Isso evita ter que
# escrever a atribuição por desempacotamento de tupla do jeito usual
# (ex.: "a, *b, c = tupla") -- que só permite UM '*' por atribuição, e este
# cabeçalho tem TRÊS campos que são, cada um, vários valores dentro do
# mesmo unpack (lista_canais, e agora também grandeza_por_canal e
# sonda_id_por_canal).
_CONTAGENS_CABECALHO_V1 = [1, 1, 1, 1, 1, 1, 1, 8, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
_CONTAGENS_CABECALHO_V2 = _CONTAGENS_CABECALHO_V1[:-1] + [8, ADS8688_MAX_CANAIS, 1]  # ...antes do header_crc32: +8 (grandeza) +8 (sonda) +1 (crc)
_CONTAGENS_CABECALHO_V3 = _CONTAGENS_CABECALHO_V2[:-1] + [8, 1]  # v2 + 8 bytes de faixa_adc_por_canal antes do crc
_CONTAGENS_CABECALHO_V4 = _CONTAGENS_CABECALHO_V3[:-1] + [1, 1, 1, 3, 1]  # v3 + 3 contadores + 3 atrasos antes do crc
_CONTAGENS_CABECALHO_V5 = _CONTAGENS_CABECALHO_V4[:-1] + [1, 1, 1, 1]  # v4 + versão, taxa medida e nº de buffers antes do crc
_CONTAGENS_CABECALHO_V6 = _CONTAGENS_CABECALHO_V5[:-1] + [1, 1, 1, 1, 1]  # v5 + os 4 campos da grade de tempo antes do crc
_CONTAGENS_CABECALHO_V7 = _CONTAGENS_CABECALHO_V6[:-1] + [1, 1, 1, 1]  # v6 + modo do SPI e as 2 divergências antes do crc

_TAMANHO_CAMPOS_V1 = struct.calcsize(_FORMATO_CABECALHO_V1)  # 408 bytes
_TAMANHO_CAMPOS_V2 = struct.calcsize(_FORMATO_CABECALHO_V2)  # 408 + 8 + 8*32 = 672 bytes
_TAMANHO_CAMPOS_V3 = struct.calcsize(_FORMATO_CABECALHO_V3)  # 672 + 8 = 680 bytes
_TAMANHO_CAMPOS_V4 = struct.calcsize(_FORMATO_CABECALHO_V4)  # 680 + 24 = 704 bytes
_TAMANHO_CAMPOS_V5 = struct.calcsize(_FORMATO_CABECALHO_V5)  # 704 + 32 + 8 + 4 = 748 bytes
_TAMANHO_CAMPOS_V6 = struct.calcsize(_FORMATO_CABECALHO_V6)  # 748 + 16 = 764 bytes
_TAMANHO_CAMPOS_V7 = struct.calcsize(_FORMATO_CABECALHO_V7)  # 764 + 12 = 776 bytes
_OFFSET_HEADER_CRC32_V1 = _TAMANHO_CAMPOS_V1 - struct.calcsize("I")  # 404
_OFFSET_HEADER_CRC32_V2 = _TAMANHO_CAMPOS_V2 - struct.calcsize("I")  # 668
_OFFSET_HEADER_CRC32_V3 = _TAMANHO_CAMPOS_V3 - struct.calcsize("I")  # 676
_OFFSET_HEADER_CRC32_V4 = _TAMANHO_CAMPOS_V4 - struct.calcsize("I")  # 700
_OFFSET_HEADER_CRC32_V5 = _TAMANHO_CAMPOS_V5 - struct.calcsize("I")  # 744
_OFFSET_HEADER_CRC32_V6 = _TAMANHO_CAMPOS_V6 - struct.calcsize("I")  # 760
_OFFSET_HEADER_CRC32_V7 = _TAMANHO_CAMPOS_V7 - struct.calcsize("I")  # 772


def _consumir(campos_tupla: tuple, contagens: list[int]) -> list:
    """Divide 'campos_tupla' (a tupla plana devolvida por struct.unpack) em
    blocos, nos tamanhos dados por 'contagens' -- 1 devolve um valor
    escalar, N > 1 devolve uma tupla de N valores. Existe só para contornar
    a limitação do Python de aceitar no máximo um '*' por atribuição de
    tupla (ver comentário em _CONTAGENS_CABECALHO_V1, acima). O assert é o
    equivalente, em tempo de execução, à verificação de tamanho em tempo de
    COMPILAÇÃO que o lado C faz para o cabeçalho (verificacao_cabecalho_1024_bytes
    em ler_adc.c) -- pega uma dessincronização entre o format string e a
    lista de contagens antes que ela vire um bug silencioso mais adiante."""
    partes = []
    i = 0
    for n in contagens:
        partes.append(campos_tupla[i] if n == 1 else campos_tupla[i:i + n])
        i += n
    assert i == len(campos_tupla), (
        f"soma das contagens ({i}) não bate com o tamanho da tupla "
        f"({len(campos_tupla)}) -- format string do cabeçalho e lista de "
        f"contagens ficaram dessincronizados"
    )
    return partes


@dataclass(frozen=True)
class CabecalhoArquivo:
    """Metadados extraídos do cabeçalho de 1024 bytes de um '.bin' novo --
    ver ler_cabecalho() para como é construído a partir dos bytes brutos."""
    versao_cabecalho: int
    tamanho_cabecalho: int
    timestamp_unix: int
    frequencia_hz: int
    auto_seq_mask: int
    num_canais: int
    lista_canais: tuple[int, ...]
    samples_per_buffer: int
    bytes_por_amostra: int
    pru_clock_hz: int
    sample_period_ticks: int
    primeira_amostra_descartada: bool
    duracao_pedida_segundos: float
    blocos_gravados: int
    total_amostras_gravadas: int
    titulo: str
    descricao: str
    header_crc32: int
    crc32_valido: bool  # calculado por este script ao ler -- não é, em si, um campo do cabeçalho
    # [SONDA/GRANDEZA, v2] Ambos SEMPRE presentes (mesmo tamanho de
    # lista_canais), independente da versão do cabeçalho de origem: para um
    # '.bin' v1 (sem estes campos), ler_cabecalho() os preenche com o
    # padrão histórico -- GRANDEZA_PADRAO (tensão) em todo canal habilitado
    # e string vazia (nenhuma sonda) -- em vez de deixar quem usa esta
    # classe ter que checar a versão a cada acesso. Mesma indexação de
    # lista_canais: posição i descreve o canal lista_canais[i].
    grandeza_por_canal: tuple[int, ...]
    sonda_id_por_canal: tuple[str, ...]
    # [FAIXA DE ENTRADA, v3] Código de faixa (RANGE_SELn do ADS8688) com que
    # o ADC converteu cada canal -- mesma indexação de lista_canais. Em um
    # '.bin' v1/v2 (anterior ao registro da faixa) fica VAZIO: a faixa real
    # é desconhecida e quem usa deve cair no padrão histórico (ver
    # canais.resolver_faixas). Use faixa_adc_total_v_por_canal para os Volts.
    faixa_adc_codigo_por_canal: tuple[int, ...] = ()
    # [INTEGRIDADE, v4] Contados pela PRU durante a captura (ver memoria_pru.h). None em v1-v3: o firmware antigo não
    # media -- desconhecido, não "zero".
    amostras_atrasadas: int | None = None
    buffers_sobrescritos: int | None = None
    quadros_preambulo_ruim: int | None = None
    atraso_cs_iteracoes: tuple[int, ...] = ()       # (setup, hold, alto), iterações de 10 ns; () antes da v4
    # [v5] Qual build do ler_adc gravou ("" antes da v5: desconhecido) e a taxa total medida pelo relógio do ARM
    # (None antes da v5 ou se a captura teve menos de 2 blocos).
    versao_firmware: str = ""
    taxa_medida_hz: float | None = None
    buffers_ping_pong: int | None = None             # [v5] None antes: desconhecido (o firmware sempre usou 2)
    # [GRADE, v6] Publicados pela PRU (ver memoria_pru.h). None antes da v6: o firmware não media.
    folga_minima_ciclos: int | None = None
    atraso_maximo_ciclos: int | None = None
    ciclos_rebase: int | None = None
    versao_protocolo_pru: int | None = None
    # [SPI, v7] None antes da v7: o SPI era sempre o padrão.
    modo_spi: int | None = None
    divergencias_fase_a: int | None = None
    divergencias_fase_c: int | None = None

    @property
    def _folga_publicada(self) -> bool:
        """A v6 (firmware do T7f) só tinha a folga com a troca a partir de 2 blocos; desde a v7, a PRU a publica 5
        amostras depois de cada troca, e 1 bloco já a tem (com a troca). Antes de publicada, ela vale o período."""
        if self.folga_minima_ciclos is None:
            return False
        if self.versao_cabecalho < 7 and self.blocos_gravados < 2:
            return False
        return self.amostras_atrasadas != 0 or self.folga_minima_ciclos < self.sample_period_ticks

    @property
    def grade_exata(self) -> bool | None:
        """True quando a PRU garante que TODA amostra saiu no ciclo exato da grade (firmware de 22/10/2026 em diante:
        espera de precisão, nenhuma amostra atrasada e folga publicada). None quando não dá para saber: cabeçalho
        anterior à v6, ou a folga ainda não publicada (v6 com 1 bloco só)."""
        if not self._folga_publicada:
            return None
        return bool(self.amostras_atrasadas == 0 and self.folga_minima_ciclos < self.sample_period_ticks)

    @property
    def spi_rapido(self) -> bool:
        return bool(self.modo_spi)

    def descrever_spi(self) -> str | None:
        """Uma frase sobre o SPI da captura (v7); None antes da v7."""
        if self.modo_spi is None:
            return None
        if self.modo_spi == 0:
            return "lento (~10,7 MHz; o padrão até 22/10/2026)"
        fase = {1: "A (60 ns)", 2: "B (75 ns)", 3: "C (90 ns)"}.get(self.modo_spi, f"desconhecida ({self.modo_spi})")
        return (f"rápido (~15,4 MHz), leitura da fase {fase} gravada; {self.divergencias_fase_a} quadro(s) com a fase "
                f"A diferente da B e {self.divergencias_fase_c} com a C")

    @property
    def problemas_integridade(self) -> list[str]:
        """Frases (sem prefixo) para o que a PRU contou de errado nesta captura; vazio = nada (ou v1-v3)."""
        problemas = []
        if self.buffers_sobrescritos:
            problemas.append(f"{self.buffers_sobrescritos} buffer(s) sobrescrito(s) antes de gravados: a captura tem "
                             "amostras PERDIDAS (descontinuidade a cada um) -- refaça a captura")
        if self.amostras_atrasadas:
            total = max(self.total_amostras_gravadas, 1)
            problemas.append(f"{self.amostras_atrasadas} amostra(s) ({100 * self.amostras_atrasadas / total:.2g} %) saíram "
                             "depois do instante previsto: a PRU não acompanhou a taxa pedida e a taxa real é MENOR "
                             f"que os {self.frequencia_hz} Hz do cabeçalho")
        if self.quadros_preambulo_ruim:
            problemas.append(f"{self.quadros_preambulo_ruim} quadro(s) SPI com ruído na linha SDO: essas amostras são "
                             "suspeitas -- confira a ligação ADC <-> BeagleBone")
        return problemas

    @property
    def faixa_adc_total_v_por_canal(self) -> tuple[float | None, ...]:
        """Fundo de escala TOTAL (V, pico a pico) de cada canal, na ordem de
        lista_canais -- o valor de ``--faixa`` com ``--formato uint16``.
        None onde a faixa é desconhecida (cabeçalho v1/v2, ou código fora da
        tabela de FAIXAS_ADC_TOTAL_V)."""
        if not self.faixa_adc_codigo_por_canal:
            return tuple(None for _ in self.lista_canais)
        return tuple(FAIXAS_ADC_TOTAL_V.get(codigo) for codigo in self.faixa_adc_codigo_por_canal)

    @property
    def timestamp_iso_utc(self) -> str:
        """Representação legível de timestamp_unix. ⚠️ Reflete o relógio da
        BeagleBone no instante da captura -- a maioria das BeagleBones não
        tem RTC com bateria, então sem sincronização de rede (NTP) no
        momento da captura este valor pode estar incorreto (ex.: próximo
        de 1970). Um valor impossível (cabeçalho corrompido) vira um texto, não uma exceção."""
        try:
            return datetime.fromtimestamp(self.timestamp_unix, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return f"inválido ({self.timestamp_unix})"

    @property
    def frequencia_pru_hz(self) -> float | None:
        """A taxa TOTAL que a PRU de fato gera: ``pru_clock_hz ÷ sample_period_ticks``. O ``ler_adc`` arredonda os
        ticks para inteiro, então ela difere da pedida quando 200 MHz ÷ taxa não é inteiro (102.400 Hz pedidos viram
        102.406,55 Hz, +64 ppm); confirmado em bancada a 0,02 ppm (T4, 19/10/2026). None sem os dois campos."""
        if self.pru_clock_hz <= 0 or self.sample_period_ticks <= 0:
            return None
        return self.pru_clock_hz / self.sample_period_ticks

    @property
    def duracao_real_segundos(self) -> float | None:
        """total_amostras_gravadas / frequencia_hz -- duração de fato
        capturada, para comparar com duracao_pedida_segundos (só preenchida
        quando --duracao foi usado no firmware). None se frequencia_hz == 0
        (não deveria acontecer na prática, mas evita divisão por zero)."""
        if self.frequencia_hz == 0:
            return None
        return self.total_amostras_gravadas / self.frequencia_hz

    def para_attrs_hdf5(self) -> dict[str, object]:
        """Achata os campos para um dict pronto para virar atributos HDF5 na
        raiz do arquivo -- h5py aceita escalares (int/float/str/bool) e
        arrays numpy diretamente como valor de atributo; só lista_canais
        precisa virar um array explícito (h5py não aceita tuplas Python)."""
        attrs = {
            "cabecalho_versao": self.versao_cabecalho,
            "cabecalho_tamanho_bytes": self.tamanho_cabecalho,
            "timestamp_unix": self.timestamp_unix,
            "timestamp_iso_utc": self.timestamp_iso_utc,
            "frequencia_hz": self.frequencia_hz,
            "auto_seq_mask": self.auto_seq_mask,
            "num_canais": self.num_canais,
            "lista_canais": np.array(self.lista_canais, dtype=np.uint8),
            "samples_per_buffer": self.samples_per_buffer,
            "bytes_por_amostra": self.bytes_por_amostra,
            "pru_clock_hz": self.pru_clock_hz,
            "sample_period_ticks": self.sample_period_ticks,
            "primeira_amostra_descartada": self.primeira_amostra_descartada,
            "duracao_pedida_segundos": self.duracao_pedida_segundos,
            "duracao_real_segundos": (
                self.duracao_real_segundos if self.duracao_real_segundos is not None else -1.0
            ),
            "blocos_gravados": self.blocos_gravados,
            "total_amostras_gravadas": self.total_amostras_gravadas,
            "titulo": self.titulo,
            "descricao": self.descricao,
            "header_crc32": self.header_crc32,
            "header_crc32_valido": self.crc32_valido,
            "grandeza_por_canal": np.array(self.grandeza_por_canal, dtype=np.uint8),
            "sonda_id_por_canal": np.array(self.sonda_id_por_canal, dtype="S32"),
        }
        if self.faixa_adc_codigo_por_canal:  # só v3+: a faixa de v1/v2 é desconhecida, não vale gravar um valor inventado
            attrs["faixa_adc_codigo_por_canal"] = np.array(self.faixa_adc_codigo_por_canal, dtype=np.uint8)
        if self.amostras_atrasadas is not None:  # só v4+: idem
            attrs["amostras_atrasadas"] = self.amostras_atrasadas
            attrs["buffers_sobrescritos"] = self.buffers_sobrescritos
            attrs["quadros_preambulo_ruim"] = self.quadros_preambulo_ruim
            attrs["atraso_cs_iteracoes"] = np.array(self.atraso_cs_iteracoes, dtype=np.uint32)
        if self.versao_cabecalho >= 5:  # só v5+
            attrs["versao_firmware"] = self.versao_firmware
            attrs["taxa_medida_hz"] = self.taxa_medida_hz if self.taxa_medida_hz is not None else -1.0
            attrs["buffers_ping_pong"] = self.buffers_ping_pong
        if self.folga_minima_ciclos is not None:  # só v6+
            attrs["folga_minima_ciclos"] = self.folga_minima_ciclos
            attrs["atraso_maximo_ciclos"] = self.atraso_maximo_ciclos
            attrs["ciclos_rebase"] = self.ciclos_rebase
            attrs["versao_protocolo_pru"] = self.versao_protocolo_pru
        if self.modo_spi is not None:  # só v7+
            attrs["modo_spi"] = self.modo_spi
            attrs["divergencias_fase_a"] = self.divergencias_fase_a
            attrs["divergencias_fase_c"] = self.divergencias_fase_c
        return attrs

    def descrever_grade(self) -> str | None:
        """Uma frase sobre o período entre amostras, do que a PRU publicou (v6); None antes da v6."""
        if self.folga_minima_ciclos is None:
            return None
        if not self._folga_publicada:
            return "folga não publicada (firmware do T7f: só a partir de 2 blocos)"
        if self.grade_exata:
            ticks = self.sample_period_ticks
            teto = (f"; período constante até ~{self.pru_clock_hz / (ticks - self.folga_minima_ciclos) / 1e3:.1f} kS/s"
                    if self.pru_clock_hz > 0 else "")
            return (f"exata -- toda amostra no ciclo da grade, folga mínima {self.folga_minima_ciclos} ciclos "
                    f"({5 * self.folga_minima_ciclos} ns){teto}")
        return (f"{self.amostras_atrasadas} amostra(s) fora da grade, a pior {self.atraso_maximo_ciclos} ciclos "
                f"({5 * (self.atraso_maximo_ciclos or 0)} ns) atrasada")


def ler_cabecalho(caminho: Path) -> CabecalhoArquivo | None:
    """Lê e valida os primeiros 1024 bytes de 'caminho'.

    Retorna None quando o arquivo não parece ter esse cabeçalho -- menor
    que 1024 bytes, ou os 4 primeiros bytes não são o magic number "SHAN"
    (formato antigo do firmware, sem cabeçalho, ou não é um '.bin' do
    SH-Analyzer). None aqui NÃO é um erro: é o sinal para quem chama cair de
    volta no comportamento pré-cabeçalho (offset=0 no memmap, -f/--canais
    voltam a ser obrigatórios).

    Quando o magic bate mas o CRC-32 gravado não confere com o CRC
    recalculado sobre os 1024 bytes (mesma convenção do firmware: campo do
    CRC zerado antes de calcular -- ver ler_adc.c), o cabeçalho AINDA é
    retornado, com crc32_valido=False -- os campos podem estar parcialmente
    certos (só um byte pode ter sido corrompido), e cabe a quem usa decidir
    se confia ou prefere passar -f/--canais manualmente.

    [SONDA/GRANDEZA] A versão do formato (campo versao_cabecalho, os 4
    bytes logo após o magic) é lida ANTES do resto -- só ela decide qual
    format string de struct.unpack usar para o restante dos bytes. v1 (sem
    grandeza_por_canal/sonda_id_por_canal), v2 (com esses campos), v3 (mais
    faixa_adc_por_canal) e v4 (mais os contadores de integridade e os atrasos
    de CS) têm layouts diferentes a partir do byte 404 (v1 x v2), 668 (v2 x
    v3) e 676 (v3 x v4); tentar sempre desempacotar com o formato mais novo
    quebraria a leitura de um '.bin' antigo (o header_crc32 apareceria no
    lugar errado, entre muitas outras coisas). A v5 acrescenta a versão do
    firmware e a taxa medida pelo ARM no lugar do CRC da v4 (byte 700). Uma
    versão > 5 (formato futuro que este script ainda não conhece) é tratada
    como v5 na tentativa de leitura -- mais provável de funcionar
    parcialmente do que assumir uma versão antiga -- mas com aviso.
    """
    try:
        with open(caminho, "rb") as f:
            bruto = f.read(CABECALHO_TAMANHO_TOTAL)
    except FileNotFoundError:
        return None  # deixa o erro "arquivo não encontrado" aparecer mais tarde, no carregamento de verdade (carregar_amostras)

    if len(bruto) < CABECALHO_TAMANHO_TOTAL:
        return None  # arquivo menor que 1 cabeçalho inteiro -- não pode ser o formato novo
    if bruto[:4] != CABECALHO_MAGIC:
        return None  # sem magic number -- arquivo legado (pré-cabeçalho) ou não é um '.bin' do SH-Analyzer

    # Peek: só magic (4 bytes) + versao_cabecalho (uint32 logo em seguida) --
    # o suficiente para decidir qual format string usar no restante.
    (versao_cabecalho,) = struct.unpack_from("<I", bruto, 4)

    if versao_cabecalho <= 1:
        formato, contagens, offset_crc = _FORMATO_CABECALHO_V1, _CONTAGENS_CABECALHO_V1, _OFFSET_HEADER_CRC32_V1
        tem_grandeza_sonda = False
        tem_faixa_adc = False
    elif versao_cabecalho == 2:
        formato, contagens, offset_crc = _FORMATO_CABECALHO_V2, _CONTAGENS_CABECALHO_V2, _OFFSET_HEADER_CRC32_V2
        tem_grandeza_sonda = True
        tem_faixa_adc = False
    elif versao_cabecalho == 3:
        formato, contagens, offset_crc = _FORMATO_CABECALHO_V3, _CONTAGENS_CABECALHO_V3, _OFFSET_HEADER_CRC32_V3
        tem_grandeza_sonda = True
        tem_faixa_adc = True
    elif versao_cabecalho == 4:
        formato, contagens, offset_crc = _FORMATO_CABECALHO_V4, _CONTAGENS_CABECALHO_V4, _OFFSET_HEADER_CRC32_V4
        tem_grandeza_sonda = True
        tem_faixa_adc = True
    elif versao_cabecalho == 5:
        formato, contagens, offset_crc = _FORMATO_CABECALHO_V5, _CONTAGENS_CABECALHO_V5, _OFFSET_HEADER_CRC32_V5
        tem_grandeza_sonda = True
        tem_faixa_adc = True
    elif versao_cabecalho == 6:
        formato, contagens, offset_crc = _FORMATO_CABECALHO_V6, _CONTAGENS_CABECALHO_V6, _OFFSET_HEADER_CRC32_V6
        tem_grandeza_sonda = True
        tem_faixa_adc = True
    else:
        formato, contagens, offset_crc = _FORMATO_CABECALHO_V7, _CONTAGENS_CABECALHO_V7, _OFFSET_HEADER_CRC32_V7
        tem_grandeza_sonda = True
        tem_faixa_adc = True
    tem_integridade = versao_cabecalho >= 4
    tem_versao_firmware = versao_cabecalho >= 5
    tem_grade = versao_cabecalho >= 6
    tem_spi = versao_cabecalho >= 7

    # Só versões MAIS NOVAS que a suportada são suspeitas: v1 e v2 são formatos
    # conhecidos (lidos acima) e não merecem aviso.
    if versao_cabecalho > CABECALHO_VERSAO_SUPORTADA:
        log.warning(
            f"cabeçalho de '{caminho}' está na versão "
            f"{versao_cabecalho}, mas este script só conhece até a "
            f"versão {CABECALHO_VERSAO_SUPORTADA}. Os campos abaixo podem "
            f"estar incompletos ou incorretos se o formato mudou."
        )

    tamanho_campos = struct.calcsize(formato)
    campos = struct.unpack(formato, bruto[:tamanho_campos])

    faixa_adc_bytes = None
    integridade = (None, None, None, ())
    versao_firmware, taxa_medida_hz, buffers_ping_pong = "", None, None
    grade = (None, None, None, None)
    spi = (None, None, None)
    if tem_spi:
        (
            _magic, _versao, tamanho_cabecalho, timestamp_unix, frequencia_hz,
            auto_seq_mask, num_canais, lista_canais_bytes, samples_per_buffer,
            bytes_por_amostra, pru_clock_hz, sample_period_ticks,
            primeira_amostra_descartada, duracao_pedida_segundos, blocos_gravados,
            total_amostras_gravadas, titulo_bruto, descricao_bruto,
            grandeza_bytes, sonda_id_bytes_lista, faixa_adc_bytes,
            atrasadas, sobrescritos, preambulo, atrasos_cs, versao_bruta, taxa_medida, buffers_ping_pong,
            folga, atraso_max, ciclos_rebase, protocolo, modo_spi, div_a, div_c, header_crc32,
        ) = _consumir(campos, contagens)
        integridade = (atrasadas, sobrescritos, preambulo, tuple(atrasos_cs))
        versao_firmware = versao_bruta.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        taxa_medida_hz = float(taxa_medida) if taxa_medida > 0 else None
        grade = (folga, atraso_max, ciclos_rebase, protocolo)
        spi = (modo_spi, div_a, div_c)
    elif tem_grade:
        (
            _magic, _versao, tamanho_cabecalho, timestamp_unix, frequencia_hz,
            auto_seq_mask, num_canais, lista_canais_bytes, samples_per_buffer,
            bytes_por_amostra, pru_clock_hz, sample_period_ticks,
            primeira_amostra_descartada, duracao_pedida_segundos, blocos_gravados,
            total_amostras_gravadas, titulo_bruto, descricao_bruto,
            grandeza_bytes, sonda_id_bytes_lista, faixa_adc_bytes,
            atrasadas, sobrescritos, preambulo, atrasos_cs, versao_bruta, taxa_medida, buffers_ping_pong,
            folga, atraso_max, ciclos_rebase, protocolo, header_crc32,
        ) = _consumir(campos, contagens)
        integridade = (atrasadas, sobrescritos, preambulo, tuple(atrasos_cs))
        versao_firmware = versao_bruta.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        taxa_medida_hz = float(taxa_medida) if taxa_medida > 0 else None
        grade = (folga, atraso_max, ciclos_rebase, protocolo)
    elif tem_versao_firmware:
        (
            _magic, _versao, tamanho_cabecalho, timestamp_unix, frequencia_hz,
            auto_seq_mask, num_canais, lista_canais_bytes, samples_per_buffer,
            bytes_por_amostra, pru_clock_hz, sample_period_ticks,
            primeira_amostra_descartada, duracao_pedida_segundos, blocos_gravados,
            total_amostras_gravadas, titulo_bruto, descricao_bruto,
            grandeza_bytes, sonda_id_bytes_lista, faixa_adc_bytes,
            atrasadas, sobrescritos, preambulo, atrasos_cs, versao_bruta, taxa_medida, buffers_ping_pong, header_crc32,
        ) = _consumir(campos, contagens)
        integridade = (atrasadas, sobrescritos, preambulo, tuple(atrasos_cs))
        versao_firmware = versao_bruta.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        taxa_medida_hz = float(taxa_medida) if taxa_medida > 0 else None
    elif tem_integridade:
        (
            _magic, _versao, tamanho_cabecalho, timestamp_unix, frequencia_hz,
            auto_seq_mask, num_canais, lista_canais_bytes, samples_per_buffer,
            bytes_por_amostra, pru_clock_hz, sample_period_ticks,
            primeira_amostra_descartada, duracao_pedida_segundos, blocos_gravados,
            total_amostras_gravadas, titulo_bruto, descricao_bruto,
            grandeza_bytes, sonda_id_bytes_lista, faixa_adc_bytes,
            atrasadas, sobrescritos, preambulo, atrasos_cs, header_crc32,
        ) = _consumir(campos, contagens)
        integridade = (atrasadas, sobrescritos, preambulo, tuple(atrasos_cs))
    elif tem_faixa_adc:
        (
            _magic, _versao, tamanho_cabecalho, timestamp_unix, frequencia_hz,
            auto_seq_mask, num_canais, lista_canais_bytes, samples_per_buffer,
            bytes_por_amostra, pru_clock_hz, sample_period_ticks,
            primeira_amostra_descartada, duracao_pedida_segundos, blocos_gravados,
            total_amostras_gravadas, titulo_bruto, descricao_bruto,
            grandeza_bytes, sonda_id_bytes_lista, faixa_adc_bytes, header_crc32,
        ) = _consumir(campos, contagens)
    elif tem_grandeza_sonda:
        (
            _magic, _versao, tamanho_cabecalho, timestamp_unix, frequencia_hz,
            auto_seq_mask, num_canais, lista_canais_bytes, samples_per_buffer,
            bytes_por_amostra, pru_clock_hz, sample_period_ticks,
            primeira_amostra_descartada, duracao_pedida_segundos, blocos_gravados,
            total_amostras_gravadas, titulo_bruto, descricao_bruto,
            grandeza_bytes, sonda_id_bytes_lista, header_crc32,
        ) = _consumir(campos, contagens)
    else:
        (
            _magic, _versao, tamanho_cabecalho, timestamp_unix, frequencia_hz,
            auto_seq_mask, num_canais, lista_canais_bytes, samples_per_buffer,
            bytes_por_amostra, pru_clock_hz, sample_period_ticks,
            primeira_amostra_descartada, duracao_pedida_segundos, blocos_gravados,
            total_amostras_gravadas, titulo_bruto, descricao_bruto, header_crc32,
        ) = _consumir(campos, contagens)
        grandeza_bytes = None
        sonda_id_bytes_lista = None

    # CRC-32 recalculado sobre os 1024 bytes com o campo header_crc32 (no
    # offset correto PARA ESTA VERSÃO do formato) zerado -- mesmo algoritmo
    # (CRC-32/ISO-HDLC, polinômio 0xEDB88320) implementado bit a bit em
    # ler_adc.c; zlib.crc32 já é exatamente esse CRC, então não há motivo
    # para reimplementar manualmente aqui como foi feito em C (lá, a
    # reimplementação evitava puxar uma lib externa só para isso).
    bruto_para_crc = bytearray(bruto)
    bruto_para_crc[offset_crc:offset_crc + 4] = b"\x00\x00\x00\x00"
    crc_recalculado = zlib.crc32(bruto_para_crc)
    crc32_valido = (crc_recalculado == header_crc32)

    # titulo/descricao são strings estilo C dentro de um buffer de tamanho
    # fixo: o conteúdo de verdade termina no primeiro '\0', o resto é
    # zero-padding (nunca lixo -- o firmware sempre zera a struct inteira
    # antes de preencher os campos, ver ler_adc.c). errors="replace" em vez
    # de deixar estourar: um decode UTF-8 inválido aqui só afetaria texto
    # descritivo não-crítico, não os campos numéricos que definem como as
    # AMOSTRAS devem ser interpretadas -- não vale abortar o programa
    # inteiro por causa do título.
    titulo = titulo_bruto.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    descricao = descricao_bruto.split(b"\x00", 1)[0].decode("utf-8", errors="replace")

    lista_canais = tuple(lista_canais_bytes[:num_canais])

    # [SONDA/GRANDEZA] v1 não tem estes campos -- preenche com o padrão
    # histórico (todo canal habilitado = tensão, nenhuma sonda) em vez de
    # None, para quem usa CabecalhoArquivo não precisar checar a versão a
    # cada acesso (ver docstring do dataclass). v2 usa os bytes lidos de
    # verdade, na mesma indexação por posição de lista_canais.
    if tem_grandeza_sonda:
        grandeza_por_canal = tuple(grandeza_bytes[:num_canais])
        sonda_id_por_canal = tuple(
            bruto_id.split(b"\x00", 1)[0].decode("ascii", errors="replace")
            for bruto_id in sonda_id_bytes_lista[:num_canais]
        )
    else:
        grandeza_por_canal = tuple(GRANDEZA_PADRAO for _ in range(num_canais))
        sonda_id_por_canal = tuple("" for _ in range(num_canais))

    # [FAIXA DE ENTRADA, v3] v1/v2 não registram a faixa: tupla vazia =
    # "desconhecida" (inventar um código aqui faria o Python afirmar uma faixa
    # que ninguém garantiu).
    faixa_adc_codigo_por_canal = tuple(faixa_adc_bytes[:num_canais]) if tem_faixa_adc else ()

    return CabecalhoArquivo(
        versao_cabecalho=versao_cabecalho,
        tamanho_cabecalho=tamanho_cabecalho,
        timestamp_unix=timestamp_unix,
        frequencia_hz=frequencia_hz,
        auto_seq_mask=auto_seq_mask,
        num_canais=num_canais,
        lista_canais=lista_canais,
        samples_per_buffer=samples_per_buffer,
        bytes_por_amostra=bytes_por_amostra,
        pru_clock_hz=pru_clock_hz,
        sample_period_ticks=sample_period_ticks,
        primeira_amostra_descartada=bool(primeira_amostra_descartada),
        duracao_pedida_segundos=duracao_pedida_segundos,
        blocos_gravados=blocos_gravados,
        total_amostras_gravadas=total_amostras_gravadas,
        titulo=titulo,
        descricao=descricao,
        header_crc32=header_crc32,
        crc32_valido=crc32_valido,
        grandeza_por_canal=grandeza_por_canal,
        sonda_id_por_canal=sonda_id_por_canal,
        faixa_adc_codigo_por_canal=faixa_adc_codigo_por_canal,
        amostras_atrasadas=integridade[0],
        buffers_sobrescritos=integridade[1],
        quadros_preambulo_ruim=integridade[2],
        atraso_cs_iteracoes=integridade[3],
        versao_firmware=versao_firmware,
        taxa_medida_hz=taxa_medida_hz,
        buffers_ping_pong=buffers_ping_pong,
        folga_minima_ciclos=grade[0],
        atraso_maximo_ciclos=grade[1],
        ciclos_rebase=grade[2],
        versao_protocolo_pru=grade[3],
        modo_spi=spi[0],
        divergencias_fase_a=spi[1],
        divergencias_fase_c=spi[2],
    )


def imprimir_resumo_cabecalho(cabecalho: CabecalhoArquivo) -> None:
    """Bloco de resumo impresso no console quando um cabeçalho válido é
    encontrado -- visão rápida de proveniência/integridade antes de entrar
    na análise em si."""
    log.info(f"Versão de cabeçalho: {cabecalho.versao_cabecalho}")
    if not cabecalho.crc32_valido:
        log.warning(
            "CRC-32 do cabeçalho NÃO confere -- os campos abaixo podem "
            "estar corrompidos/incompletos. Considere passar -f/--canais "
            "manualmente se algum valor parecer estranho."
        )
    if cabecalho.versao_firmware:
        log.info(f"  Firmware: {cabecalho.versao_firmware}")
    if cabecalho.titulo:
        log.info(f"  Título: {cabecalho.titulo}")
    if cabecalho.descricao:
        log.info(f"  Descrição: {cabecalho.descricao}")
    log.info(
        f"  Capturado em: {cabecalho.timestamp_iso_utc} "
        f"(epoch {cabecalho.timestamp_unix})"
    )
    fs_pru = cabecalho.frequencia_pru_hz
    gerada = ""
    if fs_pru is not None and cabecalho.frequencia_hz > 0 and fs_pru != cabecalho.frequencia_hz:
        gerada = (f" (a PRU gera {fs_pru:.2f} Hz = {cabecalho.sample_period_ticks} ticks, "
                  f"{(fs_pru / cabecalho.frequencia_hz - 1) * 1e6:+.1f} ppm)")
    log.info(f"  Frequência: {cabecalho.frequencia_hz} Hz total{gerada} | canais: {list(cabecalho.lista_canais)}")
    if cabecalho.samples_per_buffer > 0 and cabecalho.num_canais > 0:
        n_buf = cabecalho.buffers_ping_pong
        por_bloco = (f"; cada bloco dura {cabecalho.samples_per_buffer / (fs_pru or cabecalho.frequencia_hz):.3f} s"
                     if (fs_pru or cabecalho.frequencia_hz) else "")
        log.info(f"  Ping-pong: {n_buf if n_buf is not None else 2} buffers de {cabecalho.samples_per_buffer} amostras "
                 f"brutas ({cabecalho.samples_per_buffer * max(cabecalho.bytes_por_amostra, 1) / 2**20:.1f} MiB cada; "
                 f"{cabecalho.samples_per_buffer // cabecalho.num_canais} por canal{por_bloco})"
                 + ("" if n_buf is not None else " -- o nº de buffers só é gravado desde a v5; o firmware sempre usou 2"))
    if cabecalho.taxa_medida_hz is not None and fs_pru:
        log.info(f"  Taxa medida pelo ARM: {cabecalho.taxa_medida_hz:.0f} Hz "
                 f"({(cabecalho.taxa_medida_hz / fs_pru - 1) * 100:+.3f} % da que a PRU gera; incerteza ~0,02 %)")
    grade = cabecalho.descrever_grade()
    if grade:
        log.info(f"  Grade de tempo (PRU): {grade}")
    if cabecalho.modo_spi is not None:
        log.info(f"  SPI: {cabecalho.descrever_spi()}")
    if cabecalho.versao_cabecalho >= 2:
        partes = []
        for canal, grandeza, sonda_id in zip(
            cabecalho.lista_canais, cabecalho.grandeza_por_canal, cabecalho.sonda_id_por_canal
        ):
            nome = NOMES_GRANDEZA.get(grandeza, f"desconhecida ({grandeza})")
            partes.append(f"canal {canal}: {nome}" + (f" (sonda: {sonda_id})" if sonda_id else ""))
        log.info("  Grandeza/sonda por canal: " + " | ".join(partes))
    if cabecalho.faixa_adc_codigo_por_canal:
        partes = []
        for canal, codigo, total_v in zip(
            cabecalho.lista_canais, cabecalho.faixa_adc_codigo_por_canal, cabecalho.faixa_adc_total_v_por_canal
        ):
            partes.append(f"canal {canal}: ±{total_v / 2:g} V" if total_v is not None
                          else f"canal {canal}: código {codigo} (desconhecido)")
        log.info("  Faixa de entrada do ADC por canal: " + " | ".join(partes))
    if cabecalho.atraso_cs_iteracoes and tuple(cabecalho.atraso_cs_iteracoes) != (200, 100, 100):
        log.info("  Atrasos de CS da PRU: " + "/".join(str(a) for a in cabecalho.atraso_cs_iteracoes)
                 + " iterações (o padrão validado é 200/100/100)")
    for problema in cabecalho.problemas_integridade:
        log.warning(f"integridade da captura: {problema}.")
    if cabecalho.total_amostras_gravadas > 0:
        duracao_real = cabecalho.duracao_real_segundos
        texto_duracao = f"{duracao_real:.3f} s reais" if duracao_real is not None else "duração real desconhecida"
        texto_pedida = (
            f" (pedida: {cabecalho.duracao_pedida_segundos:.3f} s)"
            if cabecalho.duracao_pedida_segundos > 0 else ""
        )
        log.info(
            f"  {cabecalho.blocos_gravados} bloco(s), "
            f"{cabecalho.total_amostras_gravadas} amostra(s) brutas -- {texto_duracao}{texto_pedida}"
        )
    else:
        log.info(
            "  blocos_gravados/total_amostras_gravadas = 0 -- captura "
            "provavelmente interrompida antes da atualização final do "
            "cabeçalho (os dados de amostra em si não são afetados por isso)."
        )


def contar_amostras_arquivo_bin(caminho: Path, formato: str, offset: int) -> int:
    """Conta quantas amostras cabem no arquivo depois de 'offset' bytes, só
    pelo tamanho em disco (sem abrir memmap) -- usado nas checagens de
    consistência contra o cabeçalho, antes de efetivamente carregar os
    dados."""
    tamanho_bytes = caminho.stat().st_size
    itemsize = FORMATOS_NUMPY[formato].itemsize
    return max(0, tamanho_bytes - offset) // itemsize


def conferir_consistencia_cabecalho(cabecalho: CabecalhoArquivo, canais: list[int],
                                     canais_veio_do_cabecalho: bool,
                                     n_amostras_no_arquivo: int, formato: str) -> None:
    """Confere os metadados do cabeçalho contra o que foi de fato
    fornecido/carregado. A checagem de --canais só roda quando --canais foi
    informado explicitamente (comparar o cabeçalho contra ele mesmo seria
    tautológico); as outras duas (total de amostras, bytes por amostra)
    sempre rodam."""
    if not canais_veio_do_cabecalho:
        if len(canais) != cabecalho.num_canais:
            raise ErroSHAN(
                f"--canais tem {len(canais)} canal(is) ({canais}), mas "
                f"o cabeçalho da captura registra {cabecalho.num_canais} "
                f"canal(is) ({list(cabecalho.lista_canais)}). Isso não é só "
                f"um rótulo errado -- a CONTAGEM de canais define o passo da "
                f"desintercalação; usar a contagem errada embaralha todos os "
                f"canais entre si. Ajuste --canais para ter "
                f"{cabecalho.num_canais} entrada(s), ou omita a flag para "
                f"usar os canais do cabeçalho automaticamente."
            )
        if tuple(canais) != cabecalho.lista_canais:
            log.warning(
                f"--canais {canais} tem a mesma quantidade de canais "
                f"do cabeçalho, mas números diferentes de "
                f"{list(cabecalho.lista_canais)} -- a desintercalação em si "
                f"fica correta (mesma contagem), mas os RÓTULOS de canal no "
                f"gráfico/CSV/HDF5 vão descrever fisicamente canais "
                f"diferentes dos usados na captura."
            )

    if cabecalho.total_amostras_gravadas > 0 and n_amostras_no_arquivo != cabecalho.total_amostras_gravadas:
        log.warning(
            f"o cabeçalho registra {cabecalho.total_amostras_gravadas} "
            f"amostra(s) brutas gravadas, mas o arquivo tem "
            f"{n_amostras_no_arquivo} amostra(s) após o cabeçalho -- pode "
            f"estar truncado, concatenado com outro arquivo, ou algo além do "
            f"esperado."
        )

    bytes_formato = FORMATOS_NUMPY[formato].itemsize
    if cabecalho.bytes_por_amostra != 0 and cabecalho.bytes_por_amostra != bytes_formato:
        log.warning(
            f"o cabeçalho registra {cabecalho.bytes_por_amostra} "
            f"byte(s) por amostra, mas --formato {formato} interpreta cada "
            f"amostra como {bytes_formato} byte(s) -- os dados podem ser "
            f"lidos incorretamente."
        )
