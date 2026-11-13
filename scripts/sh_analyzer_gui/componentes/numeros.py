"""Ler e escrever números com prefixo do SI, no padrão brasileiro (docs/gui-plan.md, 12.4): o que o campo
numérico aceita ("2,5k", "2500", "1,2 mV", "3e-6") e como as medidas aparecem ("2,5 kHz", "127,3 V").

**A leitura** aceita a vírgula ou o ponto como separador decimal. Com os dois no mesmo número, o último é o decimal e
o outro, o dos milhares ("1.234,5" ou "1,234.5"); com um só, ele é o decimal ("1.500" = 1,5: num campo de medida,
um número com ponto é quase sempre decimal). Espaços são ignorados. O prefixo (``p n µ u m k M G``) e a unidade são
opcionais; a unidade, se vier, tem de ser a do campo. "m" é mili e "M", mega.

**A escrita** escolhe o prefixo que deixa a mantissa entre 1 e 1000 (o formato de engenharia), com ``digitos``
algarismos significativos, sem zeros à direita, e a vírgula decimal (ou o ponto, em inglês).

Sem Qt: roda e se testa sem interface.
"""

from __future__ import annotations

import math
import re

PREFIXOS = {"p": -12, "n": -9, "µ": -6, "u": -6, "m": -3, "": 0, "k": 3, "M": 6, "G": 9}
_ESCRITA = {-12: "p", -9: "n", -6: "µ", -3: "m", 0: "", 3: "k", 6: "M", 9: "G"}
_NUMERO = re.compile(r"^([+-]?[0-9.,]*[0-9][0-9.,]*(?:[eE][+-]?[0-9]+)?)([pnµumkMG]?)(.*)$")


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
    try:
        valor = _mantissa(numero) * 10.0 ** PREFIXOS[prefixo]
    except ValueError as e:
        raise NumeroInvalido(f"'{texto}' não é um número ({e})") from None
    if not math.isfinite(valor):
        raise NumeroInvalido("o número tem de ser finito")
    return valor


def formatar_si(valor: float, unidade: str = "", digitos: int = 4, decimal: str = ",") -> str:
    """``valor`` com prefixo do SI e ``digitos`` algarismos significativos: ``formatar_si(2500, "Hz") == "2,5 kHz"``.
    ``decimal`` é ``","`` (português) ou ``"."`` (inglês)."""
    if not math.isfinite(valor):
        return "—"
    if valor == 0:
        return f"0 {unidade}".strip()
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
