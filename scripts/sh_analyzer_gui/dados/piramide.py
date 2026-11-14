"""A pirâmide mín/máx de um sinal (docs/gui-plan.md, seção 6.4).

Um gráfico tem ~1 600 colunas de pixel; uma captura de 1 h a 400 kS/s tem 720 milhões de amostras por canal. Para
desenhar qualquer trecho, em qualquer zoom, sem ler a captura inteira a cada quadro, a pirâmide guarda o mínimo e o
máximo de blocos cada vez maiores:

* o nível 0 guarda, para cada bloco de :data:`BLOCO_BASE` (32) amostras, o mínimo e o máximo;
* cada nível seguinte junta :data:`FATOR` (8) blocos do anterior (256, 2 048, 16 384... amostras por bloco);
* os níveis param quando o último tem menos de :data:`MIN_BLOCOS` (16) blocos.

O espaço extra é ~7 % do sinal (os níveis somam 2/32 x 8/7 dos valores, no mesmo tipo do sinal). Os mínimos e máximos
são **exatos**: a consulta (``consulta.py``) completa as bordas da janela com as amostras de verdade, e nenhum pico
some em nenhum zoom.

**O tipo é o do sinal.** Nas capturas, ``uint16`` em binário com deslocamento (o formato do ADS8688) ou ``int16``: a
ordem dos códigos é a mesma dos valores com sinal, então o mínimo e o máximo dos códigos crus valem, e a conversão
para volts (afim) fica para a consulta. Em sinais de ponto flutuante (importados ou derivados), um ``NaN`` não
contamina o bloco: o mínimo e o máximo ignoram os ``NaN`` (só um bloco inteiro de ``NaN`` dá ``NaN``).

Nada aqui importa o Qt. A construção roda onde quem chama quiser (uma thread do ``QThreadPool``, um processo), com
um retorno de progresso e um pedido de cancelamento. Cancelada, ela levanta o ``Cancelado`` do motor (o mesmo das
contas de frequência da ``supraharmonicos.api``): o gerenciador de tarefas reconhece um só.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from supraharmonicos.api import Cancelado

BLOCO_BASE = 32
"""Amostras por bloco no nível 0."""
FATOR = 8
"""Blocos de um nível que viram um bloco do nível seguinte."""
MIN_BLOCOS = 2 * FATOR
"""Um nível novo só é feito se o anterior tiver pelo menos isso de blocos."""
AMOSTRAS_POR_LEITURA = BLOCO_BASE * (1 << 20)
"""Amostras por canal lidas de cada vez na construção (~32 M: 64 MB por canal em int16)."""


@dataclass(frozen=True, eq=False)
class Nivel:
    """Um nível da pirâmide: o mínimo e o máximo de cada bloco de ``bloco`` amostras.

    O último bloco pode ser incompleto (o sinal raramente é múltiplo do bloco): ele cobre o que sobrou."""

    bloco: int
    minimos: np.ndarray
    maximos: np.ndarray

    def __len__(self) -> int:
        return len(self.minimos)


@dataclass(frozen=True, eq=False)
class Piramide:
    """Os níveis de um canal, do mais fino (``niveis[0]``, blocos de 32 amostras) ao mais grosso."""

    n_amostras: int
    dtype: np.dtype
    niveis: tuple[Nivel, ...]

    @property
    def nbytes(self) -> int:
        return sum(n.minimos.nbytes + n.maximos.nbytes for n in self.niveis)

    def nivel_para(self, amostras_por_coluna: float, blocos_por_coluna: int = 2) -> Nivel | None:
        """O nível mais grosso com pelo menos ``blocos_por_coluna`` blocos por coluna de pixel; ``None`` se nem o
        nível 0 serve (a janela tem tão poucas amostras por coluna que é melhor lê-las direto)."""
        escolhido = None
        for nivel in self.niveis:
            if nivel.bloco * blocos_por_coluna <= amostras_por_coluna:
                escolhido = nivel
            else:
                break
        return escolhido


def _reduzir(blocos: np.ndarray, flutuante: bool) -> tuple[np.ndarray, np.ndarray]:
    """Mínimo e máximo de cada linha de ``blocos`` (2-D). Em ponto flutuante, ignorando os ``NaN``."""
    if flutuante:
        return np.fmin.reduce(blocos, axis=1), np.fmax.reduce(blocos, axis=1)
    return blocos.min(axis=1), blocos.max(axis=1)


def _reduzir_com_sobra(valores_min: np.ndarray, valores_max: np.ndarray, tamanho: int,
                       flutuante: bool) -> tuple[np.ndarray, np.ndarray]:
    """Junta grupos de ``tamanho`` valores; o grupo final incompleto (se houver) vira um bloco também."""
    cheios = len(valores_min) // tamanho * tamanho
    mn, _ = _reduzir(valores_min[:cheios].reshape(-1, tamanho), flutuante)
    _, mx = _reduzir(valores_max[:cheios].reshape(-1, tamanho), flutuante)
    if cheios < len(valores_min):
        resto_min, _ = _reduzir(valores_min[cheios:].reshape(1, -1), flutuante)
        _, resto_max = _reduzir(valores_max[cheios:].reshape(1, -1), flutuante)
        mn, mx = np.concatenate([mn, resto_min]), np.concatenate([mx, resto_max])
    return mn, mx


def _niveis_acima(base_min: np.ndarray, base_max: np.ndarray, flutuante: bool) -> list[Nivel]:
    niveis = [Nivel(BLOCO_BASE, base_min, base_max)]
    while len(niveis[-1]) >= MIN_BLOCOS:
        anterior = niveis[-1]
        mn, mx = _reduzir_com_sobra(anterior.minimos, anterior.maximos, FATOR, flutuante)
        niveis.append(Nivel(anterior.bloco * FATOR, mn, mx))
    return niveis


def construir(amostras: np.ndarray | Sequence, n_canais: int = 1, *,
              progresso: Callable[[float], None] | None = None,
              cancelado: Callable[[], bool] | None = None,
              amostras_por_leitura: int = AMOSTRAS_POR_LEITURA) -> list[Piramide]:
    """As pirâmides de todos os canais de um sinal intercalado, numa passada só pelo arquivo.

    ``amostras`` é o vetor 1-D das amostras na ordem do arquivo (um ``np.memmap``, de preferência): com ``n_canais``
    canais, a amostra ``i`` é do canal ``i % n_canais``. Um quadro final incompleto (o arquivo cortado no meio de
    uma varredura) é ignorado, como na leitura das capturas.

    Lê ``amostras_por_leitura`` amostras por canal de cada vez (múltiplo de :data:`BLOCO_BASE`). Depois de cada
    leitura chama ``progresso(fração)``; antes de cada uma, ``cancelado()``, e levanta :class:`Cancelado` se ele
    devolver verdadeiro. Devolve uma :class:`Piramide` por canal, na ordem dos canais no arquivo.
    """
    if n_canais < 1:
        raise ValueError(f"n_canais deve ser >= 1 (recebido {n_canais}).")
    if amostras_por_leitura < BLOCO_BASE or amostras_por_leitura % BLOCO_BASE:
        raise ValueError(f"amostras_por_leitura deve ser múltiplo de {BLOCO_BASE} (recebido {amostras_por_leitura}).")
    dados = amostras if isinstance(amostras, np.ndarray) else np.asarray(amostras)
    if dados.ndim != 1:
        raise ValueError(f"as amostras devem ser um vetor 1-D (recebido {dados.ndim}-D).")
    dtype = dados.dtype
    flutuante = np.issubdtype(dtype, np.floating)
    n = len(dados) // n_canais
    if n == 0:
        return [Piramide(0, dtype, ()) for _ in range(n_canais)]

    n_blocos = -(-n // BLOCO_BASE)
    base_min = [np.empty(n_blocos, dtype) for _ in range(n_canais)]
    base_max = [np.empty(n_blocos, dtype) for _ in range(n_canais)]
    for inicio in range(0, n, amostras_por_leitura):
        if cancelado is not None and cancelado():
            raise Cancelado("construção da pirâmide cancelada")
        fim = min(inicio + amostras_por_leitura, n)
        lidas = np.asarray(dados[inicio * n_canais:fim * n_canais])
        quadros = lidas.reshape(-1, n_canais)
        b0 = inicio // BLOCO_BASE
        cheios = (fim - inicio) // BLOCO_BASE * BLOCO_BASE
        for c in range(n_canais):
            canal = quadros[:, c] if n_canais > 1 else lidas
            if cheios:
                trecho = np.ascontiguousarray(canal[:cheios]).reshape(-1, BLOCO_BASE)
                mn, mx = _reduzir(trecho, flutuante)
                base_min[c][b0:b0 + len(mn)] = mn
                base_max[c][b0:b0 + len(mx)] = mx
            if cheios < len(canal):        # o bloco final incompleto (só na última leitura)
                mn, mx = _reduzir(np.ascontiguousarray(canal[cheios:]).reshape(1, -1), flutuante)
                base_min[c][-1], base_max[c][-1] = mn[0], mx[0]
        if progresso is not None:
            progresso(fim / n)
    return [Piramide(n, dtype, tuple(_niveis_acima(base_min[c], base_max[c], flutuante))) for c in range(n_canais)]
