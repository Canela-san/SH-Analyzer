"""Ler e escrever números com prefixo do SI, no padrão brasileiro (docs/gui-plan.md, 12.4): o que o campo
numérico aceita ("2,5k", "2500", "1,2 mV", "3e-6") e como as medidas aparecem ("2,5 kHz", "127,3 V").

**A leitura** aceita a vírgula ou o ponto como separador decimal. Com os dois no mesmo número, o último é o decimal e
o outro, o dos milhares ("1.234,5" ou "1,234.5"); com um só, ele é o decimal ("1.500" = 1,5: num campo de medida,
um número com ponto é quase sempre decimal). Espaços são ignorados. O prefixo (``p n µ u m k M G``) e a unidade são
opcionais; a unidade, se vier, tem de ser a do campo. "m" é mili e "M", mega. Uma unidade sem prefixo (°C, %, psi:
``unidades.aceita_prefixos``) não leva um, nem na leitura nem na escrita ("23,46 °C").

**A escrita** escolhe o prefixo que deixa a mantissa entre 1 e 1000 (o formato de engenharia), com ``digitos``
algarismos significativos, sem zeros à direita, e o separador decimal das configurações (:func:`separador_decimal`:
a vírgula, por padrão, ou o ponto). :func:`decimal` põe esse separador num número já escrito pelo Python.

Sem Qt: roda e se testa sem interface.
"""

from __future__ import annotations

import math
import re

from ..dados.unidades import PREFIXOS_DO_SI, aceita_prefixos

SEPARADORES = (",", ".")
_separador = ","

_ESCRITA = {-12: "p", -9: "n", -6: "µ", -3: "m", 0: "", 3: "k", 6: "M", 9: "G"}
_NUMERO = re.compile(r"^([+-]?[0-9.,]*[0-9][0-9.,]*(?:[eE][+-]?[0-9]+)?)([pnµumkMG]?)(.*)$")


def separador_decimal() -> str:
    """O separador decimal da escrita (``","`` ou ``"."``), o das configurações."""
    return _separador


def definir_separador_decimal(separador: str) -> None:
    """Troca o separador decimal de tudo o que se escreve daqui em diante (a leitura aceita os dois sempre)."""
    global _separador
    if separador not in SEPARADORES:
        raise ValueError(f"separador decimal desconhecido: {separador!r} (use {' ou '.join(SEPARADORES)})")
    _separador = separador


def decimal(texto: str) -> str:
    """Um número já escrito pelo Python (``f"{x:.2f}"``, ``repr``) com o separador decimal das configurações."""
    return texto if _separador == "." else texto.replace(".", _separador)


class NumeroInvalido(ValueError):
    """O texto não é um número que o campo aceita (com a mensagem pronta para mostrar)."""


def _mantissa(texto: str) -> float:
    expoente = ""
    m = re.search(r"[eE][+-]?[0-9]+$", texto)
    if m:
        texto, expoente = texto[:m.start()], m.group(0)
    virgulas, pontos = texto.count(","), texto.count(".")
    if virgulas and pontos:
        decimal = "," if texto.rfind(",") > texto.rfind(".") else "."
        milhar = "." if decimal == "," else ","
        texto = texto.replace(milhar, "").replace(decimal, ".")
    elif virgulas > 1 or pontos > 1:
        raise NumeroInvalido("mais de um separador decimal")
    else:
        texto = texto.replace(",", ".")
    return float(texto + expoente)


def ler_numero(texto: str, unidade: str = "") -> float:
    """O valor de ``texto`` (ver o docstring do módulo). Levanta :class:`NumeroInvalido`."""
    limpo = texto.replace(" ", "").replace(" ", "").replace(" ", "")
    if not limpo:
        raise NumeroInvalido("vazio")
    m = _NUMERO.match(limpo)
    if not m:
        raise NumeroInvalido(f"'{texto}' não é um número")
    numero, prefixo, resto = m.groups()
    if unidade and prefixo + resto == unidade:      # "5 m" num campo em metros: a unidade, não mili
        prefixo, resto = "", unidade
    if resto and resto != unidade:
        raise NumeroInvalido(f"unidade '{resto}' não é a do campo ({unidade or 'sem unidade'})")
    if prefixo and unidade and not aceita_prefixos(unidade):
        raise NumeroInvalido(f"{unidade} não leva prefixo do SI")
    try:
        valor = _mantissa(numero) * 10.0 ** PREFIXOS_DO_SI[prefixo]
    except ValueError as e:
        raise NumeroInvalido(f"'{texto}' não é um número ({e})") from None
    if not math.isfinite(valor):
        raise NumeroInvalido("o número tem de ser finito")
    return valor


def formatar_si(valor: float, unidade: str = "", digitos: int = 4, decimal: str | None = None) -> str:
    """``valor`` com prefixo do SI e ``digitos`` algarismos significativos: ``formatar_si(2500, "Hz") == "2,5 kHz"``.
    Numa unidade que não aceita prefixo (°C, %, psi: ``unidades.aceita_prefixos``), os algarismos na unidade:
    ``formatar_si(23.456, "°C") == "23,46 °C"``. ``decimal`` (``","`` ou ``"."``) troca o separador das configurações
    só nesta chamada."""
    decimal = decimal or _separador
    if not math.isfinite(valor):
        return "—"
    if valor == 0:
        return f"0 {unidade}".strip()
    if unidade and not aceita_prefixos(unidade):
        return f"{_sem_prefixo(valor, digitos, decimal)} {unidade}"
    expoente = int(math.floor(math.log10(abs(valor)) / 3) * 3)
    expoente = max(-12, min(9, expoente))
    mantissa = valor / 10.0 ** expoente
    casas = max(0, digitos - 1 - int(math.floor(math.log10(abs(mantissa)))))
    texto = f"{mantissa:.{casas}f}"
    if abs(float(texto)) >= 1000 and expoente < 9:          # o arredondamento passou de 999,95 para 1000
        expoente += 3
        mantissa = valor / 10.0 ** expoente
        casas = max(0, digitos - 1 - int(math.floor(math.log10(abs(mantissa)))))
        texto = f"{mantissa:.{casas}f}"
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    texto = texto.replace(".", decimal)
    return f"{texto} {_ESCRITA[expoente]}{unidade}".strip()


def _sem_prefixo(valor: float, digitos: int, decimal: str) -> str:
    """``digitos`` algarismos significativos, sem prefixo (em notação científica fora de 10⁻⁴ a 10⁹)."""
    ordem = int(math.floor(math.log10(abs(valor))))
    if not -4 <= ordem < 9:
        mantissa, expoente = f"{valor:.{max(0, digitos - 1)}e}".split("e")
        if "." in mantissa:
            mantissa = mantissa.rstrip("0").rstrip(".")
        return f"{mantissa.replace('.', decimal)}e{int(expoente)}"
    texto = f"{valor:.{max(0, digitos - 1 - ordem)}f}"
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto.replace(".", decimal)


UNIDADES_DE_BYTES = ("B", "KiB", "MiB", "GiB", "TiB")


def formatar_bytes(tamanho: float, decimal: str | None = None) -> str:
    """Um tamanho em bytes nas unidades binárias, com até três algarismos: "512 B", "1,5 MiB", "12 GiB"."""
    valor, i = float(tamanho), 0
    while abs(valor) >= 1024 and i < len(UNIDADES_DE_BYTES) - 1:
        valor /= 1024
        i += 1
    texto = f"{valor:.0f}" if i == 0 or abs(valor) >= 10 else f"{valor:.1f}".rstrip("0").rstrip(".")
    return f"{texto.replace('.', decimal or _separador)} {UNIDADES_DE_BYTES[i]}"


def formatar_duracao(segundos: float, decimal: str | None = None) -> str:
    """Uma duração legível: "4,2 s", "12 min 30 s", "1 h 02", "26 h 40". ``—`` para o que não é número."""
    decimal = decimal or _separador
    if not math.isfinite(segundos) or segundos < 0:
        return "—"
    if segundos < 60:
        texto = f"{segundos:.3g}" if segundos < 10 else f"{segundos:.0f}"
        return f"{texto.replace('.', decimal)} s"
    inteiros = round(segundos)
    if inteiros < 3600:
        minutos, resto = divmod(inteiros, 60)
        return f"{minutos} min {resto:02d} s" if resto else f"{minutos} min"
    horas, resto = divmod(inteiros, 3600)
    return f"{horas} h {resto // 60:02d}"
