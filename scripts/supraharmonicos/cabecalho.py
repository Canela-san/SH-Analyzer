"""Cabeçalho binário do ``.bin`` (formato "SHAN").

Interpreta e valida o cabeçalho fixo de 1024 bytes gravado por
``firmware/ler_adc.c`` (``struct cabecalho_arquivo``): magic, versão (v1/v2),
CRC-32, metadados da captura, grandeza e id de sonda por canal.

Depende de: ``constantes``, ``erros``. Quem o consome: ``amostras``,
``conversao``, ``hdf5``, ``modos``, ``perfil_calibracao``."""

import logging
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .constantes import (
    ADS8688_MAX_CANAIS,
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
CABECALHO_VERSAO_SUPORTADA = 2  # versão mais recente do FORMATO do cabeçalho que este script sabe interpretar

# [SONDA/GRANDEZA] Tamanho fixo (bytes, incluindo terminador nulo) do id de
# sonda por canal na v2 do cabeçalho -- precisa bater com
# CABECALHO_SONDA_ID_TAMANHO em firmware/ler_adc.c (mesma situação de
# ADS8688_MAX_CANAIS: sincronia manual, sem arquivo de constantes
# compartilhado entre C e Python).
CABECALHO_SONDA_ID_TAMANHO = 32

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
# inseridos ENTRE descricao e header_crc32 -- ver docs/proposta_correcao_sonda.md):
#   8B   grandeza_por_canal           (8x uint8_t -- GRANDEZA_TENSAO/CORRENTE/TEMPERATURA/NAO_USADA)
#   32s * 8  sonda_id_por_canal       (8 strings de 32 bytes, uma por canal, terminadas em nulo)
#   I    header_crc32
_FORMATO_CABECALHO_V1 = "<4sIIQIII8BIIIIIdQQ64s256sI"
_FORMATO_CABECALHO_V2 = "<4sIIQIII8BIIIIIdQQ64s256s8B" + "32s" * ADS8688_MAX_CANAIS + "I"

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

_TAMANHO_CAMPOS_V1 = struct.calcsize(_FORMATO_CABECALHO_V1)  # 408 bytes
_TAMANHO_CAMPOS_V2 = struct.calcsize(_FORMATO_CABECALHO_V2)  # 408 + 8 + 8*32 = 672 bytes
_OFFSET_HEADER_CRC32_V1 = _TAMANHO_CAMPOS_V1 - struct.calcsize("I")  # 404
_OFFSET_HEADER_CRC32_V2 = _TAMANHO_CAMPOS_V2 - struct.calcsize("I")  # 668


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

    @property
    def timestamp_iso_utc(self) -> str:
        """Representação legível de timestamp_unix. ⚠️ Reflete o relógio da
        BeagleBone no instante da captura -- a maioria das BeagleBones não
        tem RTC com bateria, então sem sincronização de rede (NTP) no
        momento da captura este valor pode estar incorreto (ex.: próximo
        de 1970)."""
        return datetime.fromtimestamp(self.timestamp_unix, tz=timezone.utc).isoformat()

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
        return {
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
    grandeza_por_canal/sonda_id_por_canal) e v2 (com esses campos) têm
    layouts diferentes a partir do byte 404; tentar sempre desempacotar com
    o formato mais novo quebraria a leitura de um '.bin' v1 antigo (o
    header_crc32 apareceria no lugar errado, entre muitas outras coisas).
    Uma versão > 2 (formato futuro que este script ainda não conhece) é
    tratada como v2 na tentativa de leitura -- mais provável de funcionar
    parcialmente do que assumir v1 -- mas com aviso.
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
    else:
        formato, contagens, offset_crc = _FORMATO_CABECALHO_V2, _CONTAGENS_CABECALHO_V2, _OFFSET_HEADER_CRC32_V2
        tem_grandeza_sonda = True

    if versao_cabecalho != CABECALHO_VERSAO_SUPORTADA:
        log.warning(
            f"cabeçalho de '{caminho}' está na versão "
            f"{versao_cabecalho}, mas este script só foi testado com a "
            f"versão {CABECALHO_VERSAO_SUPORTADA}. Os campos abaixo podem "
            f"estar incompletos ou incorretos se o formato mudou."
        )

    tamanho_campos = struct.calcsize(formato)
    campos = struct.unpack(formato, bruto[:tamanho_campos])

    if tem_grandeza_sonda:
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
    if cabecalho.titulo:
        log.info(f"  Título: {cabecalho.titulo}")
    if cabecalho.descricao:
        log.info(f"  Descrição: {cabecalho.descricao}")
    log.info(
        f"  Capturado em: {cabecalho.timestamp_iso_utc} "
        f"(epoch {cabecalho.timestamp_unix})"
    )
    log.info(f"  Frequência: {cabecalho.frequencia_hz} Hz total | canais: {list(cabecalho.lista_canais)}")
    if cabecalho.versao_cabecalho >= 2:
        partes = []
        for canal, grandeza, sonda_id in zip(
            cabecalho.lista_canais, cabecalho.grandeza_por_canal, cabecalho.sonda_id_por_canal
        ):
            nome = NOMES_GRANDEZA.get(grandeza, f"desconhecida ({grandeza})")
            partes.append(f"canal {canal}: {nome}" + (f" (sonda: {sonda_id})" if sonda_id else ""))
        log.info("  Grandeza/sonda por canal: " + " | ".join(partes))
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
