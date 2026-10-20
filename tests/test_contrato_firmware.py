"""Contrato C <-> Python: o que o firmware grava é o que o Python lê.

Não há arquivo de constantes compartilhado entre o firmware (C/Assembly) e o
pós-processamento (Python); estes testes leem ``firmware/ler_adc.c`` (e
``firmware/memoria_pru.h``, se existir) e comparam com ``supraharmonicos``. Se
você mudar o formato do cabeçalho de um lado, o pytest falha até o outro lado
acompanhar -- é o substituto automático do "precisa ficar em sincronia manual"
dos comentários.
"""

import re
import struct
from pathlib import Path

import pytest
from supraharmonicos import cabecalho as cab
from supraharmonicos import constantes as const

RAIZ = Path(__file__).resolve().parents[1]
FIRMWARE = RAIZ / "firmware"
LER_ADC_C = FIRMWARE / "ler_adc.c"
MEMORIA_PRU_H = FIRMWARE / "memoria_pru.h"


def test_os_fontes_do_firmware_estao_no_repositorio():
    """Estes testes leem os fontes C. Antes eles eram PULADOS sem o arquivo -- um renome em firmware/ fazia o
    contrato C <-> Python sumir da suíte em silêncio. Agora a falta é uma falha."""
    for arquivo in (LER_ADC_C, MEMORIA_PRU_H):
        assert arquivo.is_file(), f"{arquivo.relative_to(RAIZ)} sumiu: atualize os testes de contrato junto com o renome"


def sem_comentarios(texto: str) -> str:
    texto = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
    return re.sub(r"//[^\n]*", "", texto)


@pytest.fixture(scope="module")
def fonte_c() -> str:
    return sem_comentarios(LER_ADC_C.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def defines(fonte_c) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^\s*#define\s+(\w+)\s+(.+?)\s*$", fonte_c, re.M)}


def inteiro_c(texto: str) -> int:
    """'1024u' -> 1024, '0xFFu' -> 255."""
    return int(re.sub(r"[uUlL]+$", "", texto.strip()), 0)


def max_canais_c() -> int | None:
    m = re.search(r"#\s*define\s+ADS8688_MAX_CANAIS\s+\(?(\d+)", MEMORIA_PRU_H.read_text(encoding="utf-8"))
    return int(m.group(1)) if m else None


def test_constantes_numericas_do_cabecalho(defines):
    assert defines["CABECALHO_MAGIC"].strip('"').encode() == cab.CABECALHO_MAGIC
    assert inteiro_c(defines["CABECALHO_VERSAO"]) == cab.CABECALHO_VERSAO_SUPORTADA
    assert inteiro_c(defines["CABECALHO_TAMANHO_TOTAL"]) == cab.CABECALHO_TAMANHO_TOTAL
    assert inteiro_c(defines["CABECALHO_SONDA_ID_TAMANHO"]) == cab.CABECALHO_SONDA_ID_TAMANHO


def test_codigos_de_grandeza(defines):
    assert inteiro_c(defines["GRANDEZA_TENSAO"]) == const.GRANDEZA_TENSAO
    assert inteiro_c(defines["GRANDEZA_CORRENTE"]) == const.GRANDEZA_CORRENTE
    assert inteiro_c(defines["GRANDEZA_TEMPERATURA"]) == const.GRANDEZA_TEMPERATURA
    assert inteiro_c(defines["GRANDEZA_NAO_USADA"]) == const.GRANDEZA_NAO_USADA
    assert defines["GRANDEZA_PADRAO"] == "GRANDEZA_TENSAO" and const.GRANDEZA_PADRAO == const.GRANDEZA_TENSAO


def test_max_canais_bate_com_memoria_pru_h():
    esperado = max_canais_c()
    assert esperado is not None, "#define ADS8688_MAX_CANAIS não encontrado em firmware/memoria_pru.h"
    assert const.ADS8688_MAX_CANAIS == esperado


def formato_struct_c(fonte_c: str, defines: dict[str, str]) -> list[tuple[str, int]]:
    """Lê 'struct cabecalho_arquivo_campos {...}' e devolve [(código struct, repetições)] SEM padding (packed)."""
    corpo = re.search(r"struct\s+cabecalho_arquivo_campos\s*\{(.*?)\}\s*__attribute__\(\(packed\)\)", fonte_c, re.S)
    assert corpo, "struct cabecalho_arquivo_campos (packed) não encontrada em ler_adc.c"
    max_canais = max_canais_c() or const.ADS8688_MAX_CANAIS

    def valor(expr: str) -> int:
        expr = expr.strip()
        if expr == "ADS8688_MAX_CANAIS":
            return max_canais
        return inteiro_c(defines[expr]) if expr in defines else inteiro_c(expr)

    tipos = {"uint32_t": "I", "uint64_t": "Q", "double": "d", "uint8_t": "B", "char": "s"}
    campos: list[tuple[str, int]] = []
    for linha in corpo.group(1).split(";"):
        linha = linha.strip()
        if not linha:
            continue
        m = re.fullmatch(r"(\w+)\s+(\w+)((?:\[[^\]]+\])*)", linha)
        assert m, f"campo C não reconhecido: {linha!r}"
        tipo, _nome, dims = m.groups()
        dimensoes = [valor(d) for d in re.findall(r"\[([^\]]+)\]", dims)]
        codigo = tipos[tipo]
        if not dimensoes:
            campos.append((codigo, 1))
        elif len(dimensoes) == 1:
            campos.append((codigo, dimensoes[0]))          # char[N] -> 'Ns' ; uint8_t[N] -> 'NB'
        else:                                             # char[A][B] -> A campos 'Bs'
            assert codigo == "s" and len(dimensoes) == 2
            campos.extend([("s", dimensoes[1])] * dimensoes[0])
    return campos


def formato_struct_python(fmt: str) -> list[tuple[str, int]]:
    campos = []
    for m in re.finditer(r"(\d*)([A-Za-z])", fmt.lstrip("<>=@!")):
        n, codigo = int(m.group(1) or 1), m.group(2)
        campos.append((codigo, n))
    return campos


def normalizar(campos: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Expande 'NB'/'NI'... em N campos unitários (só 's' mantém a contagem como tamanho do texto)."""
    saida: list[tuple[str, int]] = []
    for codigo, n in campos:
        saida.extend([(codigo, 1)] * n if codigo != "s" else [(codigo, n)])
    return saida


def test_layout_da_struct_v4_bate_com_o_formato_python(fonte_c, defines):
    c = normalizar(formato_struct_c(fonte_c, defines))
    py = normalizar(formato_struct_python(cab._FORMATO_CABECALHO_V4))
    assert c == py


def test_tamanhos_derivados(fonte_c, defines):
    assert cab._TAMANHO_CAMPOS_V2 == struct.calcsize(cab._FORMATO_CABECALHO_V2) == 672
    assert cab._TAMANHO_CAMPOS_V3 == struct.calcsize(cab._FORMATO_CABECALHO_V3) == 680
    assert cab._TAMANHO_CAMPOS_V3 < inteiro_c(defines["CABECALHO_TAMANHO_TOTAL"])
    assert cab._OFFSET_HEADER_CRC32_V2 == cab._TAMANHO_CAMPOS_V2 - 4 == 668   # o CRC é o ÚLTIMO campo
    assert cab._OFFSET_HEADER_CRC32_V3 == cab._TAMANHO_CAMPOS_V3 - 4 == 676
    assert cab._TAMANHO_CAMPOS_V4 == struct.calcsize(cab._FORMATO_CABECALHO_V4) == 704
    assert cab._OFFSET_HEADER_CRC32_V4 == cab._TAMANHO_CAMPOS_V4 - 4 == 700
    assert cab._TAMANHO_CAMPOS_V4 < inteiro_c(defines["CABECALHO_TAMANHO_TOTAL"])
    for fmt, contagens in ((cab._FORMATO_CABECALHO_V3, cab._CONTAGENS_CABECALHO_V3),
                           (cab._FORMATO_CABECALHO_V4, cab._CONTAGENS_CABECALHO_V4)):
        assert sum(contagens) == len(struct.unpack(fmt, bytes(struct.calcsize(fmt))))


def test_v3_e_o_prefixo_de_v4_sem_a_integridade():
    v3 = normalizar(formato_struct_python(cab._FORMATO_CABECALHO_V3))
    v4 = normalizar(formato_struct_python(cab._FORMATO_CABECALHO_V4))
    assert v4[:-7] == v3[:-1] and v4[-7:] == [("I", 1)] * 7      # 3 contadores + 3 atrasos + o CRC


def test_offsets_do_cabecalho_usados_por_calibrar_sonda_sh():
    """calibrar_sonda.sh lê o cabeçalho por offsets fixos (od); precisam bater com o layout v3."""
    sh = (FIRMWARE / "calibrar_sonda.sh").read_text(encoding="utf-8")
    offs = {m.group(1): int(m.group(2)) for m in re.finditer(r"readonly (CAB_(?:OFF|TAM)_\w+)=(\d+)", sh)}
    off_faixa = cab._TAMANHO_CAMPOS_V2 - 4                                   # logo depois de sonda_id_por_canal, antes do CRC
    assert offs["CAB_OFF_CRC_V2"] == cab._OFFSET_HEADER_CRC32_V2
    assert offs["CAB_OFF_FAIXA_ADC"] == off_faixa
    assert offs["CAB_OFF_CRC_V3"] == cab._OFFSET_HEADER_CRC32_V3 == off_faixa + const.ADS8688_MAX_CANAIS
    # v4: contadores de integridade logo depois da faixa, onde ficava o CRC da v3
    assert offs["CAB_OFF_ATRASADAS"] == cab._OFFSET_HEADER_CRC32_V3
    assert offs["CAB_OFF_SOBRESCRITOS"] == offs["CAB_OFF_ATRASADAS"] + 4
    assert offs["CAB_OFF_PREAMBULO"] == offs["CAB_OFF_ATRASADAS"] + 8
    assert offs["CAB_OFF_CRC_V4"] == cab._OFFSET_HEADER_CRC32_V4
    assert offs["CAB_OFF_SONDA_ID"] + const.ADS8688_MAX_CANAIS * cab.CABECALHO_SONDA_ID_TAMANHO == off_faixa
    assert offs["CAB_OFF_GRANDEZA"] + const.ADS8688_MAX_CANAIS == offs["CAB_OFF_SONDA_ID"]
    assert offs["CAB_TAM_SONDA_ID"] == cab.CABECALHO_SONDA_ID_TAMANHO


def test_v2_e_o_prefixo_de_v3_sem_faixa_adc():
    v2 = normalizar(formato_struct_python(cab._FORMATO_CABECALHO_V2))
    v3 = normalizar(formato_struct_python(cab._FORMATO_CABECALHO_V3))
    assert v3[:-1 - const.ADS8688_MAX_CANAIS] == v2[:-1] and v3[-1] == v2[-1] == ("I", 1)
    assert v3[-1 - const.ADS8688_MAX_CANAIS:-1] == [("B", 1)] * const.ADS8688_MAX_CANAIS


def test_v1_e_o_prefixo_de_v2_sem_grandeza_e_sonda():
    v1 = normalizar(formato_struct_python(cab._FORMATO_CABECALHO_V1))
    v2 = normalizar(formato_struct_python(cab._FORMATO_CABECALHO_V2))
    grandeza_e_sonda = [("B", 1)] * const.ADS8688_MAX_CANAIS + [("s", cab.CABECALHO_SONDA_ID_TAMANHO)] * const.ADS8688_MAX_CANAIS
    assert v2[:-1 - len(grandeza_e_sonda)] == v1[:-1] and v2[-1] == v1[-1] == ("I", 1)


def test_crc32_do_firmware_e_o_mesmo_polinomio_do_zlib(fonte_c):
    assert "0xEDB88320u" in fonte_c, "polinômio do CRC mudou no firmware -- o Python usa zlib.crc32 (0xEDB88320)"


# ---------------------------------------------------------------------------
# Faixa de entrada do ADC por canal (RANGE_SELn do ADS8688)
# ---------------------------------------------------------------------------

def _memoria_pru_sem_comentarios() -> str:
    return sem_comentarios(MEMORIA_PRU_H.read_text(encoding="utf-8"))


def test_codigos_de_faixa_do_adc(fonte_c, defines):
    assert inteiro_c(defines["FAIXA_ADC_NAO_USADA"]) == const.FAIXA_ADC_NAO_USADA
    m = re.search(r"FAIXA_ADC_ESPAN_V\[\]\s*=\s*\{([^}]*)\}", fonte_c)
    assert m, "tabela FAIXA_ADC_ESPAN_V não encontrada em ler_adc.c"
    espans_c = [float(v) for v in m.group(1).split(",")]
    assert espans_c == [const.FAIXAS_ADC_TOTAL_V[c] for c in range(len(espans_c))]
    assert inteiro_c(defines["FAIXA_ADC_NUM_CODIGOS"]) == len(const.FAIXAS_ADC_TOTAL_V) == len(espans_c)
    assert defines["FAIXA_ADC_PADRAO"] == "ADS8688_FAIXA_2_5_VREF" and const.FAIXAS_ADC_TOTAL_V[0] == 20.48   # padrão = reset do ADC


def test_faixas_do_adc_batem_com_a_definicao_do_ads8688():
    """Código c -> ±2,5·VREF/2^c com VREF = 4,096 V: o fundo de escala TOTAL é 5·VREF/2^c."""
    for codigo, total_v in const.FAIXAS_ADC_TOTAL_V.items():
        assert total_v == pytest.approx(5 * 4.096 / 2 ** codigo)


def test_codigos_de_faixa_em_memoria_pru_h():
    h = _memoria_pru_sem_comentarios()
    codigos = {m.group(1): inteiro_c(m.group(2)) for m in re.finditer(r"#\s*define\s+(ADS8688_FAIXA_\w+)\s+(\w+)", h)}
    assert codigos == {"ADS8688_FAIXA_2_5_VREF": 0, "ADS8688_FAIXA_1_25_VREF": 1, "ADS8688_FAIXA_0_625_VREF": 2}
    assert sorted(codigos.values()) == sorted(const.FAIXAS_ADC_TOTAL_V)


def test_offsets_da_memoria_compartilhada_pru():
    """spi_core.asm lê auto_seq_mask/range_sel por offset FIXO (LBBO); a struct tem de ter os campos lá."""
    h = _memoria_pru_sem_comentarios()
    corpo = re.search(r"struct\s+shared_control\s*\{(.*?)\}", h, re.S).group(1)
    nomes = re.findall(r"uint32_t\s+(\w+)\s*;", corpo)
    offsets = {nome: 4 * i for i, nome in enumerate(nomes)}
    assert offsets["config_ready"] == 24 and offsets["auto_seq_mask"] == 28 and offsets["range_sel"] == 32
    # integridade (PRU -> ARM) e atrasos de CS (ARM -> PRU): o assembly os lê/escreve em bloco de 12 bytes
    assert [offsets[n] for n in ("amostras_atrasadas", "buffers_sobrescritos", "quadros_preambulo_ruim")] == [36, 40, 44]
    assert [offsets[n] for n in ("atraso_cs_setup", "atraso_cs_hold", "atraso_cs_alto")] == [48, 52, 56]
    asm = sem_comentarios_asm((FIRMWARE / "spi_core.asm").read_text(encoding="utf-8"))
    assert "SBBO &r6, r14, 36, 12" in asm and "LBBO &r9, r14, 48, 12" in asm


def sem_comentarios_asm(texto: str) -> str:
    return "\n".join(ln.split(";", 1)[0] for ln in texto.splitlines())


def test_atrasos_de_cs_padrao_do_c_e_do_assembly_sao_os_mesmos():
    """0 no campo = o padrão do assembly; o ler_adc grava o seu padrão: os dois têm de ser o mesmo (200/100/100)."""
    h = _memoria_pru_sem_comentarios()
    padrao_c = [inteiro_c(re.search(rf"#\s*define\s+ATRASO_CS_{n}_PADRAO\s+(\w+)", h).group(1))
                for n in ("SETUP", "HOLD", "ALTO")]
    asm = sem_comentarios_asm((FIRMWARE / "spi_core.asm").read_text(encoding="utf-8"))
    padrao_asm = [int(re.search(rf"QBNE atraso_{n}_ok, r{r}, 0\s+LDI r{r}, (\d+)", asm).group(1))
                  for n, r in (("setup", 9), ("hold", 10), ("alto", 11))]
    assert padrao_c == padrao_asm == [200, 100, 100]
