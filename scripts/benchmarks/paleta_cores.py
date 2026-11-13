"""A conferência das cores da interface (docs/gui-plan.md, seção 12): contraste e separação para daltônicos.

Para cada tema, confere:

* **o contraste (WCAG 2.2)** de cada cor de traço contra a área dos gráficos (≥ 3:1) e dos textos contra a superfície
  (≥ 4,5:1);
* **a separação em OKLab** (ΔE × 100) entre as cores dos traços, na visão normal e simulando protanopia, deuteranopia
  e tritanopia (matrizes de Machado, Oliveira e Fernandes, 2009, severidade 1):
  - os 4 primeiros traços, todos os pares: ≥ 8 em toda visão;
  - os 6, pares vizinhos: ≥ 8 em toda visão;
  - os 6, todos os pares: ≥ 15 na visão normal.

Os valores são os dos mockups (``docs/gui-mockups/tema.css``); quando existir o ``sh_analyzer_gui/tema/tokens.py``, esta
conta vira o ``tests/test_tema.py``. Uso: ``python scripts/benchmarks/paleta_cores.py`` (só NumPy); sai com 1 se algo
reprovar.
"""

import itertools
import sys

import numpy as np

# Simulação de daltonismo no RGB linear (Machado et al., 2009, severidade 1,0).
CVD = {
    "protanopia": np.array([[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216],
                            [-0.003882, -0.048116, 1.051998]]),
    "deuteranopia": np.array([[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413],
                              [-0.011820, 0.042940, 0.968881]]),
    "tritanopia": np.array([[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602],
                            [0.004733, 0.691367, 0.303900]]),
}

TEMAS = {
    "escuro": {
        "area_dos_graficos": "#0c1526",
        "superficie": "#16243b",
        "tracos": ["#7dd3fc", "#fbbf24", "#fb7185", "#818cf8", "#34d399", "#e879f9"],
        "textos": {"texto": "#e6edf6", "texto2": "#9fb0c8", "mudo": "#7d8fa9", "acento": "#7dd3fc",
                   "ok": "#4ade80", "aviso": "#fb923c", "erro": "#f87171"},
    },
    "claro": {
        "area_dos_graficos": "#ffffff",
        "superficie": "#ffffff",
        "tracos": ["#0284c7", "#d97706", "#be123c", "#3730a3", "#047857", "#c026d3"],
        "textos": {"texto": "#0f172a", "texto2": "#4b5b73", "mudo": "#64748b", "acento": "#0369a1",
                   "ok": "#15803d", "aviso": "#c2410c", "erro": "#b91c1c"},
    },
}


def rgb(cor: str) -> np.ndarray:
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
    def lum(c):
        r, g, bb = linear(rgb(c))
        return 0.2126 * r + 0.7152 * g + 0.0722 * bb
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def distancia(a: str, b: str, visao: str = "normal") -> float:
    la, lb = linear(rgb(a)), linear(rgb(b))
    if visao != "normal":
        la, lb = np.clip(CVD[visao] @ la, 0, 1), np.clip(CVD[visao] @ lb, 0, 1)
    return 100 * float(np.linalg.norm(oklab(la) - oklab(lb)))


def pior(pares, visoes) -> tuple[float, str, str, str]:
    return min((distancia(a, b, v), a, b, v) for a, b in pares for v in visoes)


def conferir(nome: str, tema: dict) -> list[str]:
    """Devolve a lista de reprovações (vazia = tudo certo) e escreve o relatório."""
    falhas = []
    escrever = sys.stdout.write
    escrever(f"\nTema {nome}\n")
    for i, cor in enumerate(tema["tracos"], 1):
        c = contraste(cor, tema["area_dos_graficos"])
        escrever(f"  traço {i} {cor}: contraste {c:4.1f}:1 contra {tema['area_dos_graficos']}\n")
        if c < 3:
            falhas.append(f"{nome}: traço {i} com contraste {c:.1f}:1 (< 3:1)")
    for papel, cor in tema["textos"].items():
        c = contraste(cor, tema["superficie"])
        if c < 4.5:
            falhas.append(f"{nome}: {papel} com contraste {c:.1f}:1 (< 4,5:1)")
    tracos = tema["tracos"]
    regras = [
        ("os 4 primeiros, todos os pares, daltonismo", itertools.combinations(tracos[:4], 2), list(CVD), 8),
        ("os 6, pares vizinhos, daltonismo", zip(tracos, tracos[1:]), list(CVD), 8),
        ("os 6, todos os pares, visão normal", itertools.combinations(tracos, 2), ["normal"], 15),
    ]
    for rotulo, pares, visoes, minimo in regras:
        d, a, b, v = pior(list(pares), visoes)
        marca = "ok" if d >= minimo else "REPROVA"
        escrever(f"  {rotulo:44} pior ΔE {d:5.1f} ({a} × {b}, {v}); mínimo {minimo}: {marca}\n")
        if d < minimo:
            falhas.append(f"{nome}: {rotulo}: ΔE {d:.1f} < {minimo}")
    return falhas


def main() -> int:
    falhas = [f for nome, tema in TEMAS.items() for f in conferir(nome, tema)]
    sys.stdout.write("\n" + ("Tudo certo.\n" if not falhas else "Reprovado:\n  " + "\n  ".join(falhas) + "\n"))
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
