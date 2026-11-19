"""A prévia da figura como outros a veem (F5.7; FG-05), sem Qt: em tons de cinza (a revista impressa em preto e
branco) e com a simulação dos três daltonismos de dicromacia (o vermelho, o verde ou o azul que falta).

* **Os daltonismos** pelas matrizes de Machado, Oliveira e Fernandes (2009), na gravidade máxima, aplicadas no RGB
  linear (o sRGB da página sem a curva de gama) e devolvidas ao sRGB; o que sai da faixa é cortado.
* **Os tons de cinza** pela luminância relativa (a Rec. 709, também no RGB linear), devolvida ao sRGB: o cinza que
  uma impressão fiel daria a cada cor.

Só a prévia muda (a página da área Figuras): a exportação sai sempre com as cores da figura.
"""

from __future__ import annotations

import numpy as np

VISOES = {"normal": "Cores normais", "cinza": "Tons de cinza", "deuteranopia": "Deuteranopia (sem o verde)",
          "protanopia": "Protanopia (sem o vermelho)", "tritanopia": "Tritanopia (sem o azul)"}
"""As visões da prévia (o id e o nome); a deuteranopia é a mais comum (~5 % dos homens)."""

MATRIZES = {
    "protanopia": np.array([[0.152286, 1.052583, -0.204868],
                            [0.114503, 0.786281, 0.099216],
                            [-0.003882, -0.048116, 1.051998]]),
    "deuteranopia": np.array([[0.367322, 0.860646, -0.227968],
                              [0.280085, 0.672501, 0.047413],
                              [-0.011820, 0.042940, 0.968881]]),
    "tritanopia": np.array([[1.255528, -0.076749, -0.178779],
                            [-0.078411, 0.930809, 0.147602],
                            [0.004733, 0.691367, 0.303900]]),
}
"""As matrizes de Machado et al. (2009), gravidade 1,0, no RGB linear."""
LUMINANCIA = np.array([0.2126, 0.7152, 0.0722])


def _para_linear(srgb: np.ndarray) -> np.ndarray:
    """Os valores de 0 a 255 do sRGB no RGB linear (0 a 1)."""
    c = np.arange(256, dtype=np.float64) / 255.0
    tabela = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return tabela[srgb]


def _para_srgb(linear: np.ndarray) -> np.ndarray:
    c = np.clip(linear, 0.0, 1.0)
    srgb = np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055)
    return np.rint(srgb * 255.0).astype(np.uint8)


def simular(rgba: np.ndarray, visao: str) -> np.ndarray:
    """A página ``rgba`` (``altura × largura × 4``, ``uint8``) como ``visao`` a mostra (uma cópia; a transparência
    fica). ``"normal"`` devolve a própria página."""
    if visao not in VISOES:
        raise ValueError(f"visão desconhecida: {visao!r} (use {', '.join(VISOES)})")
    if visao == "normal":
        return rgba
    linear = _para_linear(rgba[..., :3])
    if visao == "cinza":
        cinza = linear @ LUMINANCIA
        rgb = np.repeat(_para_srgb(cinza)[..., None], 3, axis=-1)
    else:
        rgb = _para_srgb(linear @ MATRIZES[visao].T)
    saida = np.empty_like(rgba)
    saida[..., :3] = rgb
    saida[..., 3] = rgba[..., 3]
    return saida
