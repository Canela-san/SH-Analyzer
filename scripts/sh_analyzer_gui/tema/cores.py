"""As contas que conferem as cores (docs/gui-plan.md, 12.2 e 12.3): o contraste WCAG 2.2 e a separação em OKLab
(ΔE x 100), na visão normal e simulando protanopia, deuteranopia e tritanopia (matrizes de Machado, Oliveira e
Fernandes, 2009, severidade 1).

Sem Qt (só NumPy): ``tests/test_tema.py`` e ``scripts/benchmarks/paleta_cores.py`` usam estas funções sobre os
tokens.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence

import numpy as np

CVD = {
    "protanopia": np.array([[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216],
                            [-0.003882, -0.048116, 1.051998]]),
    "deuteranopia": np.array([[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413],
                              [-0.011820, 0.042940, 0.968881]]),
    "tritanopia": np.array([[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602],
                            [0.004733, 0.691367, 0.303900]]),
}

CONTRASTE_TEXTO = 4.5
"""Mínimo para texto contra a superfície (WCAG 2.2, AA)."""
CONTRASTE_GRAFICO = 3.0
"""Mínimo para elementos de gráfico contra a área dos dados."""
DELTA_E_DALTONISMO = 8.0
"""Separação mínima em OKLab (x100) entre cores de traço que se encontram, com daltonismo simulado."""
DELTA_E_NORMAL = 15.0
"""Separação mínima entre quaisquer duas cores de traço, na visão normal."""


def rgb(cor: str) -> np.ndarray:
    """``#rrggbb`` -> RGB em [0, 1]."""
    if len(cor) != 7 or cor[0] != "#":
        raise ValueError(f"cor inválida: {cor!r} (use #rrggbb)")
    return np.array([int(cor[i:i + 2], 16) / 255 for i in (1, 3, 5)])


def linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def oklab(lin: np.ndarray) -> np.ndarray:
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]])
    return m2 @ np.cbrt(m1 @ lin)


def contraste(a: str, b: str) -> float:
    """O contraste WCAG entre duas cores (1 a 21)."""
    def lum(c):
        r, g, bb = linear(rgb(c))
        return 0.2126 * r + 0.7152 * g + 0.0722 * bb
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return float((la + 0.05) / (lb + 0.05))


def distancia(a: str, b: str, visao: str = "normal") -> float:
    """A distância em OKLab (x100) entre duas cores, na visão normal ou com um tipo de daltonismo (``CVD``)."""
    la, lb = linear(rgb(a)), linear(rgb(b))
    if visao != "normal":
        la, lb = np.clip(CVD[visao] @ la, 0, 1), np.clip(CVD[visao] @ lb, 0, 1)
    return 100 * float(np.linalg.norm(oklab(la) - oklab(lb)))


def pior_par(pares: Iterable[tuple[str, str]], visoes: Sequence[str]) -> tuple[float, str, str, str]:
    """O par mais parecido: ``(distância, cor_a, cor_b, visão)``."""
    return min((distancia(a, b, v), a, b, v) for a, b in pares for v in visoes)


def regras_da_paleta(tracos: Sequence[str]) -> list[tuple[str, float, float, tuple[str, str, str]]]:
    """As três regras da paleta (12.3), cada uma como ``(nome, pior distância, mínimo, (cor_a, cor_b, visão))``:

    * os 4 primeiros traços, todos os pares, com daltonismo;
    * os 6, pares vizinhos, com daltonismo;
    * os 6, todos os pares, na visão normal."""
    regras = [
        ("os 4 primeiros, todos os pares, daltonismo", itertools.combinations(tracos[:4], 2), list(CVD),
         DELTA_E_DALTONISMO),
        ("os 6, pares vizinhos, daltonismo", zip(tracos, tracos[1:]), list(CVD), DELTA_E_DALTONISMO),
        ("os 6, todos os pares, visão normal", itertools.combinations(tracos, 2), ["normal"], DELTA_E_NORMAL),
    ]
    saida = []
    for nome, pares, visoes, minimo in regras:
        d, a, b, v = pior_par(list(pares), visoes)
        saida.append((nome, d, minimo, (a, b, v)))
    return saida
