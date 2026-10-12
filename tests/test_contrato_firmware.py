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

pytestmark = pytest.mark.skipif(not LER_ADC_C.exists(), reason="firmware/ler_adc.c não encontrado neste checkout")


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
    if not MEMORIA_PRU_H.exists():
        return None
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
    if esperado is None:
        pytest.skip("firmware/memoria_pru.h (ADS8688_MAX_CANAIS) não encontrado neste checkout")
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


def test_layout_da_struct_v2_bate_com_o_formato_python(fonte_c, defines):
    c = normalizar(formato_struct_c(fonte_c, defines))
    py = normalizar(formato_struct_python(cab._FORMATO_CABECALHO_V2))
    assert c == py


def test_tamanhos_derivados(fonte_c, defines):
    assert cab._TAMANHO_CAMPOS_V2 == struct.calcsize(cab._FORMATO_CABECALHO_V2) == 672
    assert cab._TAMANHO_CAMPOS_V2 < inteiro_c(defines["CABECALHO_TAMANHO_TOTAL"])
    assert cab._OFFSET_HEADER_CRC32_V2 == cab._TAMANHO_CAMPOS_V2 - 4          # o CRC é o ÚLTIMO campo


def test_v1_e_o_prefixo_de_v2_sem_grandeza_e_sonda():
    v1 = normalizar(formato_struct_python(cab._FORMATO_CABECALHO_V1))
    v2 = normalizar(formato_struct_python(cab._FORMATO_CABECALHO_V2))
    grandeza_e_sonda = [("B", 1)] * const.ADS8688_MAX_CANAIS + [("s", cab.CABECALHO_SONDA_ID_TAMANHO)] * const.ADS8688_MAX_CANAIS
    assert v2[:-1 - len(grandeza_e_sonda)] == v1[:-1] and v2[-1] == v1[-1] == ("I", 1)


def test_crc32_do_firmware_e_o_mesmo_polinomio_do_zlib(fonte_c):
    assert "0xEDB88320u" in fonte_c, "polinômio do CRC mudou no firmware -- o Python usa zlib.crc32 (0xEDB88320)"
