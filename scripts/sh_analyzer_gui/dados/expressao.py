"""A expressão de um traço (TR-05; docs/gui-progress.md, F7.2): uma conta amostra a amostra com o traço (``a``) e os
canais da captura (``c0`` a ``c15``), lida por um analisador próprio. **Nunca ``eval``:** o texto vira a árvore da
``ast`` do Python, e só passa o que está na lista: os números, os nomes ``a``, ``c0``…, ``pi`` e ``e``, as quatro
operações, a potência (``^`` ou ``**``), o sinal, os parênteses e as funções de :data:`FUNCOES`. Um atributo, um
índice, uma chamada de outra coisa, uma comparação, um nome desconhecido: recusados, com o porquê.

A árvore conferida vira uma função de NumPy (:func:`compilar`), que recebe o traço e os canais (``float64``) e dá o
resultado do mesmo tamanho. Os símbolos tipográficos (×, ÷, −) valem como as operações.

Sem Qt.
"""

from __future__ import annotations

import ast
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import numpy as np

TAMANHO_MAXIMO = 300
NOS_MAXIMOS = 200
CANAIS_MAXIMOS = 16
EXPOENTE_MAXIMO = 64.0

FUNCOES: dict[str, tuple[Callable, int]] = {
    "abs": (np.abs, 1), "sqrt": (np.sqrt, 1), "exp": (np.exp, 1), "log": (np.log, 1), "log10": (np.log10, 1),
    "sin": (np.sin, 1), "cos": (np.cos, 1), "tan": (np.tan, 1), "atan": (np.arctan, 1), "sign": (np.sign, 1),
    "min": (np.minimum, 2), "max": (np.maximum, 2), "atan2": (np.arctan2, 2), "hypot": (np.hypot, 2),
}
"""As funções que a expressão aceita: o nome, a função da NumPy e quantos argumentos."""
CONSTANTES = {"pi": math.pi, "e": math.e}
_CANAL = re.compile(r"c(\d{1,2})$")
_OPERACOES = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply, ast.Div: np.divide}
_TIPOGRAFICOS = str.maketrans({"×": "*", "·": "*", "÷": "/", "−": "-", "^": "**"})


class ExpressaoInvalida(ValueError):
    """A expressão não é uma conta que vale; a mensagem diz o que e onde."""


@dataclass(frozen=True)
class ContaCompilada:
    """A expressão pronta: ``conta(a, canais)`` com ``canais = {numero: valores}``; os canais que ela usa; e o ganho
    em DC de ``a`` quando a conta é ``k·a`` (NaN se não é linear em ``a`` ou usa outros canais)."""

    texto: str
    canais: tuple[int, ...]
    usa_a: bool
    ganho_em_a: float
    _funcao: Callable

    def __call__(self, a: np.ndarray, canais: Mapping[int, np.ndarray]) -> np.ndarray:
        with np.errstate(all="ignore"):
            return self._funcao(np.asarray(a, dtype=np.float64), canais)


def _onde(no: ast.AST) -> str:
    coluna = getattr(no, "col_offset", None)
    return f" (na posição {coluna + 1})" if coluna is not None else ""


def compilar(texto: str) -> ContaCompilada:
    """A conta de ``texto``, conferida. Levanta :class:`ExpressaoInvalida`."""
    if not isinstance(texto, str) or not texto.strip():
        raise ExpressaoInvalida("a expressão está vazia (use a, c0, c1…, por exemplo: a - c1)")
    if len(texto) > TAMANHO_MAXIMO:
        raise ExpressaoInvalida(f"a expressão passa de {TAMANHO_MAXIMO} caracteres")
    limpo = texto.strip().translate(_TIPOGRAFICOS)
    try:
        arvore = ast.parse(limpo, mode="eval")
    except SyntaxError as e:
        raise ExpressaoInvalida(f"a expressão não se lê: {e.msg} (na posição {e.offset or 0})") from None
    nos = sum(1 for _ in ast.walk(arvore))
    if nos > NOS_MAXIMOS:
        raise ExpressaoInvalida(f"a expressão é longa demais ({nos} partes; o máximo é {NOS_MAXIMOS})")
    canais: set[int] = set()
    usa_a = False

    def montar(no: ast.AST) -> Callable:
        nonlocal usa_a
        if isinstance(no, ast.Expression):
            return montar(no.body)
        if isinstance(no, ast.Constant):
            if isinstance(no.value, bool) or not isinstance(no.value, (int, float)):
                raise ExpressaoInvalida(f"só números valem como constantes, não {no.value!r}{_onde(no)}")
            valor = float(no.value)
            return lambda a, c: valor
        if isinstance(no, ast.Name):
            nome = no.id
            if nome == "a":
                usa_a = True
                return lambda a, c: a
            if nome in CONSTANTES:
                valor = CONSTANTES[nome]
                return lambda a, c: valor
            m = _CANAL.match(nome)
            if m:
                numero = int(m.group(1))
                if numero >= CANAIS_MAXIMOS:
                    raise ExpressaoInvalida(f"{nome}: os canais vão de c0 a c{CANAIS_MAXIMOS - 1}")
                canais.add(numero)
                return lambda a, c: c[numero]
            if nome in FUNCOES:
                raise ExpressaoInvalida(f"{nome} é uma função: use {nome}(…){_onde(no)}")
            raise ExpressaoInvalida(f"nome desconhecido: {nome}{_onde(no)} (use a, c0 a c{CANAIS_MAXIMOS - 1}, pi, e)")
        if isinstance(no, ast.UnaryOp) and isinstance(no.op, (ast.USub, ast.UAdd)):
            dentro = montar(no.operand)
            if isinstance(no.op, ast.USub):
                return lambda a, c: np.negative(dentro(a, c))
            return dentro
        if isinstance(no, ast.BinOp):
            esquerda, direita = montar(no.left), montar(no.right)
            if isinstance(no.op, ast.Pow):
                if isinstance(no.right, ast.Constant) and isinstance(no.right.value, (int, float)) \
                        and abs(float(no.right.value)) > EXPOENTE_MAXIMO:
                    raise ExpressaoInvalida(f"o expoente passa de {EXPOENTE_MAXIMO:g}{_onde(no)}")
                return lambda a, c: np.power(esquerda(a, c), direita(a, c))
            operacao = _OPERACOES.get(type(no.op))
            if operacao is None:
                raise ExpressaoInvalida(f"operação não aceita{_onde(no)} (use + − × ÷ ^)")
            return lambda a, c: operacao(esquerda(a, c), direita(a, c))
        if isinstance(no, ast.Call):
            if not isinstance(no.func, ast.Name) or no.func.id not in FUNCOES:
                nome = no.func.id if isinstance(no.func, ast.Name) else "isso"
                raise ExpressaoInvalida(f"função não aceita: {nome}{_onde(no)} (as que valem: "
                                        f"{', '.join(FUNCOES)})")
            if no.keywords:
                raise ExpressaoInvalida(f"{no.func.id} não aceita argumentos com nome{_onde(no)}")
            funcao, aridade = FUNCOES[no.func.id]
            if len(no.args) != aridade:
                raise ExpressaoInvalida(f"{no.func.id} recebe {aridade} argumento(s), não {len(no.args)}{_onde(no)}")
            argumentos = [montar(x) for x in no.args]
            return lambda a, c: funcao(*(f(a, c) for f in argumentos))
        if isinstance(no, ast.Tuple):
            raise ExpressaoInvalida("a vírgula separa os argumentos de uma função: use o ponto nos decimais (0.5)")
        if isinstance(no, ast.Compare):
            raise ExpressaoInvalida(f"comparações não valem{_onde(no)}")
        raise ExpressaoInvalida(f"isto não vale numa expressão: {type(no).__name__}{_onde(no)}")

    funcao = montar(arvore)
    ganho = math.nan
    if not canais:
        with np.errstate(all="ignore"):
            pontos = np.array([0.0, 1.0, 2.0, -3.0])
            y = np.broadcast_to(np.asarray(funcao(pontos, {}), dtype=np.float64), pontos.shape)
        if np.all(np.isfinite(y)) and abs(y[0]) < 1e-12 and np.allclose(y, y[1] * pontos, rtol=1e-12, atol=1e-12):
            ganho = float(y[1])
    return ContaCompilada(texto.strip(), tuple(sorted(canais)), usa_a, ganho, funcao)
