"""A consulta: o que o desenho precisa para mostrar uma janela da captura em ``colunas`` colunas de pixel.

Há três regimes, pela quantidade de amostras por coluna (``apc``):

* **amostras** (``apc <= AMOSTRAS_POR_COLUNA_LINHA``, 2): as próprias amostras da janela -- de perto, desenha-se a
  linha que passa por elas (e, bem de perto, os pontos);
* **envoltória exata das amostras** (até ``BLOCOS_POR_COLUNA`` blocos do nível 0 por coluna, 256 amostras): o
  mínimo e o máximo de cada coluna, calculados das amostras, com as bordas das colunas exatamente onde caem;
* **envoltória pela pirâmide** (daí para cima): o nível mais grosso com pelo menos ``BLOCOS_POR_COLUNA`` (8) blocos
  por coluna. As bordas das colunas são **arredondadas para bordas de bloco**, e a envoltória devolve onde cada
  coluna começa e acaba de fato.

**Por que arredondar as bordas não engana ninguém:** cada amostra cai em exatamente uma coluna, e o mínimo e o
máximo de cada coluna são exatos para as amostras que ela cobre. Com 8 blocos ou mais por coluna, a largura de uma
coluna varia no máximo um bloco (1/8 de pixel): invisível. Em troca, a consulta não lê nenhuma amostra crua, só a
pirâmide -- que está na memória -- e leva ~0,1 ms para 1 600 colunas em qualquer zoom.

A primeira e a última amostra de cada coluna (o "M4" completo) não são devolvidas: o desenho da banda como polígono
não precisa delas. A exportação, que não tem pressa, refaz a redução a partir das amostras (docs/gui-plan.md, 10.3).

Os valores saem no tipo da captura (códigos do ADC); :func:`aplicar_afim` os leva para a unidade física.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .piramide import Piramide

AMOSTRAS_POR_COLUNA_LINHA = 2
"""Até isto de amostras por coluna, devolvem-se as amostras (o desenho é a linha que passa por elas)."""
BLOCOS_POR_COLUNA = 8
"""Blocos da pirâmide por coluna, no mínimo: a largura de uma coluna varia no máximo 1/8 de pixel."""


@dataclass(frozen=True, eq=False)
class Amostras:
    """As amostras de uma janela pequena: ``indices`` (posição de cada amostra no canal) e ``valores``."""

    indices: np.ndarray
    valores: np.ndarray

    def __len__(self) -> int:
        return len(self.indices)


@dataclass(frozen=True, eq=False)
class Envoltoria:
    """O mínimo e o máximo de cada coluna. A coluna ``c`` cobre as amostras ``[bordas[c], bordas[c + 1])``."""

    bordas: np.ndarray
    minimos: np.ndarray
    maximos: np.ndarray

    def __len__(self) -> int:
        return len(self.minimos)


def consultar(piramide: Piramide, amostras: np.ndarray, inicio: float, fim: float,
              colunas: int) -> Amostras | Envoltoria:
    """O que desenhar para as amostras ``[inicio, fim)`` do canal em ``colunas`` colunas de pixel.

    ``amostras`` são as do canal (o vetor 1-D, ou a visão com passo dentro de um memmap intercalado), e
    ``piramide`` é a dele. ``inicio`` e ``fim`` podem ser fracionários (a vista do gráfico raramente cai numa
    amostra) e podem passar das pontas: a janela é cortada no canal e arredondada para fora, para nenhuma amostra
    visível ficar de fora. Uma janela vazia devolve :class:`Amostras` vazias.
    """
    if colunas < 1:
        raise ValueError(f"colunas deve ser >= 1 (recebido {colunas}).")
    n = piramide.n_amostras
    i0 = max(0, int(np.floor(inicio)))
    i1 = min(n, int(np.ceil(fim)))
    if i1 <= i0:
        return Amostras(np.zeros(0, np.int64), np.asarray(amostras[0:0]))
    por_coluna = (i1 - i0) / colunas
    if por_coluna <= AMOSTRAS_POR_COLUNA_LINHA:
        return Amostras(np.arange(i0, i1, dtype=np.int64), np.asarray(amostras[i0:i1]))
    nivel = piramide.nivel_para(por_coluna, BLOCOS_POR_COLUNA)
    flutuante = np.issubdtype(piramide.dtype, np.floating)
    if nivel is None:
        # Poucas amostras por coluna: a envoltória vem das próprias amostras, com as bordas exatas.
        bordas = _sem_repeticao(i0 + (np.arange(colunas + 1, dtype=np.int64) * (i1 - i0)) // colunas)
        valores = np.ascontiguousarray(amostras[i0:i1])
        mn, mx = _reduzir_em(valores, valores, bordas[:-1] - i0, flutuante)
        return Envoltoria(bordas, mn, mx)
    b0 = i0 // nivel.bloco
    b1 = min(len(nivel), -(-i1 // nivel.bloco))
    bordas_blocos = _sem_repeticao(b0 + (np.arange(colunas + 1, dtype=np.int64) * (b1 - b0)) // colunas)
    mn, mx = _reduzir_em(nivel.minimos[b0:b1], nivel.maximos[b0:b1], bordas_blocos[:-1] - b0, flutuante)
    bordas = np.minimum(bordas_blocos * nivel.bloco, n)
    return Envoltoria(bordas, mn, mx)


def _sem_repeticao(bordas: np.ndarray) -> np.ndarray:
    """As bordas (já em ordem crescente) sem as repetidas: uma coluna vazia não existe. Mais barato que ``np.unique``,
    que ordenaria de novo a cada quadro."""
    distintas = np.empty(len(bordas), dtype=bool)
    distintas[0] = True
    np.greater(bordas[1:], bordas[:-1], out=distintas[1:])
    return bordas if distintas.all() else bordas[distintas]


def _reduzir_em(minimos: np.ndarray, maximos: np.ndarray, inicios: np.ndarray,
                flutuante: bool) -> tuple[np.ndarray, np.ndarray]:
    """Mínimo e máximo de cada fatia que começa em ``inicios`` (e vai até a próxima, ou até o fim)."""
    if flutuante:
        return np.fmin.reduceat(minimos, inicios), np.fmax.reduceat(maximos, inicios)
    return np.minimum.reduceat(minimos, inicios), np.maximum.reduceat(maximos, inicios)


def aplicar_afim(consulta: Amostras | Envoltoria, escala: float = 1.0,
                 deslocamento: float = 0.0) -> Amostras | Envoltoria:
    """A consulta em outra unidade: ``valor * escala + deslocamento``, em ``float64``.

    É assim que os códigos do ADC viram volts, e que o ganho, o offset e a inversão de um traço agem direto na
    pirâmide (docs/gui-plan.md, 7.2). Com a escala negativa, o mínimo e o máximo trocam de lugar."""
    if isinstance(consulta, Amostras):
        return Amostras(consulta.indices, consulta.valores.astype(np.float64) * escala + deslocamento)
    mn = consulta.minimos.astype(np.float64) * escala + deslocamento
    mx = consulta.maximos.astype(np.float64) * escala + deslocamento
    if escala < 0:
        mn, mx = mx, mn
    return Envoltoria(consulta.bordas, mn, mx)
