"""Clicar num traço (docs/gui-plan.md, 9.2): o alcance em volta da linha e quem ganha quando há vários perto.

* **A distância é até o desenho**, em pixels da tela: até o segmento entre duas amostras (de perto, as amostras ficam
  longe umas das outras, e clicar no meio da linha conta), e até a linha vertical de cada coluna da envoltória (de
  longe), olhando as colunas vizinhas do clique, e não só a de baixo do mouse.
* **O alcance** é de :data:`ALCANCE_DO_CLIQUE_PX` pixels: um pouco mais que a espessura do traço mais o tremor da mão.
* **Com vários traços no alcance,** ganha o mais perto; empatados (menos de :data:`EMPATE_PX` de diferença: traços
  um em cima do outro), ganha o de cima no desenho (o selecionado, ou o que entrou por último).
"""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np

ALCANCE_DO_CLIQUE_PX = 9.0
EMPATE_PX = 1.0


def distancia_a_linha(x: float, y: float, xs: np.ndarray, ys: np.ndarray, largura_px: float,
                      altura_px: float) -> float:
    """A distância, em pixels, do ponto ``(x, y)`` à linha que liga os pontos ``(xs, ys)`` (tudo nas unidades da
    vista; ``largura_px`` e ``altura_px`` são quantas unidades cabem num pixel). ``NaN`` interrompe a linha.
    ``inf`` sem pontos."""
    xs = (np.asarray(xs, dtype=np.float64) - x) / max(abs(largura_px), 1e-300)
    ys = (np.asarray(ys, dtype=np.float64) - y) / max(abs(altura_px), 1e-300)
    if len(xs) == 0:
        return math.inf
    melhor = math.inf
    pontos = np.isfinite(xs) & np.isfinite(ys)
    if pontos.any():
        melhor = float(np.min(np.hypot(xs[pontos], ys[pontos])))
    if len(xs) > 1:
        ax, ay, bx, by = xs[:-1], ys[:-1], xs[1:], ys[1:]
        validos = np.isfinite(ax) & np.isfinite(ay) & np.isfinite(bx) & np.isfinite(by)
        ax, ay, bx, by = ax[validos], ay[validos], bx[validos], by[validos]
        if len(ax):
            dx, dy = bx - ax, by - ay
            comprimento = dx * dx + dy * dy
            with np.errstate(invalid="ignore", divide="ignore"):
                t = np.clip(np.where(comprimento > 0, -(ax * dx + ay * dy) / comprimento, 0.0), 0.0, 1.0)
            melhor = min(melhor, float(np.min(np.hypot(ax + t * dx, ay + t * dy))))
    return melhor


def distancia_a_colunas(x: float, y: float, centros: np.ndarray, minimos: np.ndarray, maximos: np.ndarray,
                        largura_px: float, altura_px: float) -> float:
    """A distância, em pixels, do ponto às linhas verticais da envoltória (a coluna ``c`` em ``centros[c]``, de
    ``minimos[c]`` a ``maximos[c]``), olhando só as colunas a até :data:`ALCANCE_DO_CLIQUE_PX` do clique."""
    largura_px, altura_px = max(abs(largura_px), 1e-300), max(abs(altura_px), 1e-300)
    perto = np.abs(centros - x) <= (ALCANCE_DO_CLIQUE_PX + 1) * largura_px
    if not perto.any():
        return math.inf
    dx = (centros[perto] - x) / largura_px
    baixo, alto = np.minimum(minimos[perto], maximos[perto]), np.maximum(minimos[perto], maximos[perto])
    fora = np.maximum(np.maximum(baixo - y, y - alto), 0.0) / altura_px
    d = np.hypot(dx, fora)
    d = d[np.isfinite(d)]
    return float(d.min()) if len(d) else math.inf


def mais_perto(candidatos: Iterable[tuple[float, float, object]]) -> object | None:
    """``candidatos``: ``(distância em pixels, ordem no desenho, objeto)``. O mais perto dentro do alcance; empatado,
    o de maior ordem (o desenhado por cima). None se nenhum está no alcance."""
    dentro = [c for c in candidatos if c[0] <= ALCANCE_DO_CLIQUE_PX]
    if not dentro:
        return None
    melhor = min(d for d, _, _ in dentro)
    empatados = [c for c in dentro if c[0] < melhor + EMPATE_PX]
    return max(empatados, key=lambda c: (c[1], -c[0]))[2]       # o de cima; na mesma ordem, o mais perto
