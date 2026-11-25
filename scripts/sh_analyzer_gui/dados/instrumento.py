"""O modo Instrumento (F7.9, AN-08 e AN-06; docs/gui-progress.md, 4h): os ciclos de vários traços sobrepostos no
disparo de um deles, como num osciloscópio, sem Qt.

* **O disparo** (:func:`disparos`): os instantes (com a fração da amostra, pela interpolação linear) em que o traço
  de disparo cruza o nível na borda pedida, com a histerese (o sinal tem de voltar para o outro lado do nível, a uma
  distância dela, antes do próximo: o ruído em cima do nível não dispara de novo) e o tempo morto (*holdoff*: um
  disparo só depois do fim da janela do anterior, como no osciloscópio). Com o **rejeitar AF**
  (:func:`sinal_de_disparo`), o disparo é procurado no traço passado por um passa-baixa de :data:`CORTE_DO_REJEITAR_AF_HZ`
  (Butterworth de 2ª ordem, de ida e volta: sem atraso, o instante do disparo é o do traço): a rede dispara uma vez
  por ciclo mesmo com um surto de supraharmônicos por cima, que cruzaria o nível dezenas de vezes.
* **A persistência** (:func:`densidade`): cada amostra de cada ciclo cai numa célula (o tempo desde o disparo, o
  valor): a contagem é exata (as amostras, sem interpolar), e o "fósforo" é ela em escala logarítmica.
* **O ciclo médio** (:func:`ciclo_medio`): os ciclos interpolados numa grade comum e a média e o desvio em cada
  instante; e as medidas dele (o RMS, o pico a pico, a média) e as do disparo (o período, a frequência e o desvio do
  período, o *jitter* do disparo).

Os traços são lidos em pedaços (``qualidade.ler``): a captura inteira não vai para a memória.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import supraharmonicos.api as api

from .espectros import TrechoDoTraco
from .qualidade import ler

PEDACO = 1 << 21
MAXIMO_DE_CICLOS = 5000
CORTE_DO_REJEITAR_AF_HZ = 1_000.0
CICLOS_DA_MARGEM_DO_FILTRO = 8
"""A margem lida de cada lado do pedaço para o passa-baixa de ida e volta (em períodos do corte): a resposta dele
some em ~1 período; com 8, a borda do pedaço não muda o disparo."""
PONTOS_DO_CICLO_MEDIO = 1000
BORDAS = ("subindo", "descendo")


def disparos(x: np.ndarray, nivel: float, borda: str = "subindo", histerese: float = 0.0,
             tempo_morto: float = 0.0) -> np.ndarray:
    """Os instantes (em amostras de ``x``, com fração) dos disparos: ``x`` cruza ``nivel`` na ``borda`` depois de ter
    estado do outro lado a ``histerese`` dele; e cada um a pelo menos ``tempo_morto`` amostras do anterior."""
    if borda not in BORDAS:
        raise ValueError(f"borda inválida: {borda!r} (use {', '.join(BORDAS)})")
    y = np.asarray(x, dtype=np.float64) - nivel
    if borda == "descendo":
        y = -y
    h = abs(histerese)
    acima = y >= 0
    candidatos = np.nonzero(acima[1:] & ~acima[:-1])[0] + 1          # y passa de < 0 a >= 0 entre i-1 e i
    if not len(candidatos):
        return np.zeros(0)
    # o gatilho de Schmitt: um cruzamento só vale se o sinal esteve abaixo de −histerese depois do cruzamento
    # anterior (o ruído em cima do nível cruza de novo sem se afastar dele)
    indices = np.arange(len(y))
    ultimo_armado = np.maximum.accumulate(np.where(y < -h, indices, -1))
    anterior = np.concatenate([[-1], candidatos[:-1]])
    validos = candidatos[ultimo_armado[candidatos - 1] > anterior]
    y0, y1 = y[validos - 1], y[validos]
    instantes = (validos - 1) + np.where(y1 != y0, -y0 / np.where(y1 != y0, y1 - y0, 1.0), 0.0)
    if tempo_morto <= 0 or len(instantes) < 2:
        return instantes
    saida = [instantes[0]]
    for t in instantes[1:]:
        if t - saida[-1] >= tempo_morto:
            saida.append(t)
    return np.array(saida)


def sinal_de_disparo(x: np.ndarray, taxa_hz: float, corte_hz: float = 0.0) -> np.ndarray:
    """O sinal em que o disparo é procurado: ``x``, ou (``corte_hz`` > 0, o rejeitar AF) ``x`` passado por um
    Butterworth de 2ª ordem em ``corte_hz``, de ida e volta (sem atraso). Levanta ``api.ErroSHAN`` se o corte não cabe
    na taxa."""
    if not corte_hz > 0:
        return np.asarray(x, dtype=np.float64)
    if corte_hz >= 0.4 * taxa_hz:
        raise api.ErroSHAN(f"o rejeitar AF ({corte_hz:g} Hz) precisa de uma taxa acima de {corte_hz / 0.4:g} Hz")
    import scipy.signal

    sos = scipy.signal.butter(2, corte_hz, fs=taxa_hz, output="sos")
    x = np.asarray(x, dtype=np.float64)
    if len(x) <= 3 * (2 * len(sos) + 1):
        return x
    return scipy.signal.sosfiltfilt(sos, x)


@dataclass(frozen=True)
class Disparo:
    """Os disparos de um trecho: os instantes (em amostras do canal de disparo, desde o começo da captura) e o
    período entre eles (as estatísticas, em s)."""

    instantes: np.ndarray
    taxa_hz: float

    @property
    def n(self) -> int:
        return len(self.instantes)

    @property
    def periodos_s(self) -> np.ndarray:
        return np.diff(self.instantes) / self.taxa_hz

    @property
    def periodo_s(self) -> float:
        p = self.periodos_s
        return float(np.median(p)) if len(p) else math.nan

    @property
    def desvio_do_periodo_s(self) -> float:
        p = self.periodos_s
        return float(np.std(p)) if len(p) > 1 else math.nan


def disparos_do_trecho(trecho: TrechoDoTraco, nivel: float, borda: str, histerese: float, antes_s: float,
                       depois_s: float, *, tempo_morto_s: float = 0.0, rejeitar_af_hz: float = 0.0,
                       maximo: int = MAXIMO_DE_CICLOS, pedaco: int = PEDACO,
                       cancelado: Callable[[], bool] | None = None) -> Disparo:
    """Os disparos do trecho, lidos em pedaços, com a janela inteira (``antes_s``, ``depois_s``) dentro dele; até
    ``maximo``. As janelas podem se sobrepor (uma de dois ciclos tem um disparo a cada ciclo: a persistência e o
    ciclo médio usam todos); ``tempo_morto_s`` afasta os disparos, como o *holdoff* do osciloscópio;
    ``rejeitar_af_hz`` procura o disparo no traço por um passa-baixa (:func:`sinal_de_disparo`), com uma margem lida
    de cada lado do pedaço para o filtro não sentir a borda."""
    taxa = trecho.captura.canal(trecho.numero).taxa_hz
    antes, depois = antes_s * taxa, depois_s * taxa
    instantes: list[float] = []
    ultimo = -math.inf
    sobra = int(antes + depois) + 2                     # o pedaço começa antes: o gatilho se arma de novo ali
    margem = int(math.ceil(CICLOS_DA_MARGEM_DO_FILTRO * taxa / rejeitar_af_hz)) if rejeitar_af_hz > 0 else 0
    pos = trecho.inicio
    while pos < trecho.fim and len(instantes) < maximo:
        if cancelado is not None and cancelado():
            raise api.Cancelado()
        b = min(trecho.fim, pos + max(pedaco, 4 * sobra))
        a = max(trecho.inicio, pos - sobra)
        a_lido, b_lido = max(trecho.inicio, a - margem), min(trecho.fim, b + margem)
        x = sinal_de_disparo(ler(trecho, a_lido, b_lido), taxa, rejeitar_af_hz)[a - a_lido:b - a_lido]
        achados = disparos(x, nivel, borda, histerese) + a
        for t in achados:
            if t <= ultimo + 0.5 or t - ultimo < tempo_morto_s * taxa or t - antes < trecho.inicio \
                    or t + depois > trecho.fim - 1:
                continue                     # o mesmo de um pedaço anterior, o tempo morto, a janela fora do trecho
            instantes.append(float(t))
            ultimo = t
            if len(instantes) >= maximo:
                break
        pos = b
    return Disparo(np.array(instantes), taxa)


@dataclass(frozen=True)
class Densidade:
    """A contagem das amostras de cada célula: ``contagens[coluna, linha]`` (o tempo desde o disparo, o valor) e os
    limites (s e unidade do traço)."""

    contagens: np.ndarray
    tempo: tuple[float, float]
    valor: tuple[float, float]
    amostras: int               # as amostras que caíram dentro (a soma das contagens)
    fora: int                   # as que ficaram fora da faixa de valores


def _janelas(trecho: TrechoDoTraco, deslocamento: float, instantes: np.ndarray, antes: float, depois: float,
             cancelado=None):
    """Cada ciclo: os índices (do canal do traço) e os tempos relativos ao disparo (em amostras do traço), com o
    ``deslocamento`` (em amostras do traço) entre o tempo do disparo e o do traço."""
    n = len(trecho.captura.canal(trecho.numero).amostras)
    for t in instantes:
        if cancelado is not None and cancelado():
            raise api.Cancelado()
        centro = t + deslocamento
        i0, i1 = max(0, math.ceil(centro - antes)), min(n, math.floor(centro + depois) + 1)
        if i1 - i0 < 2:
            continue
        yield i0, i1, np.arange(i0, i1) - centro


def densidade(trecho: TrechoDoTraco, disparo: Disparo, antes_s: float, depois_s: float, faixa: tuple[float, float],
              *, colunas: int = 400, linhas: int = 256, deslocamento_s: float = 0.0,
              cancelado: Callable[[], bool] | None = None) -> Densidade:
    """A persistência do traço nos ciclos do disparo: cada amostra conta 1 na célula dela (ver o começo do módulo).
    ``deslocamento_s``: o instante do disparo no tempo deste traço menos o no do traço de disparo (os deslocamentos
    no tempo e as taxas diferentes)."""
    taxa = trecho.captura.canal(trecho.numero).taxa_hz
    escala = taxa / disparo.taxa_hz
    antes, depois = antes_s * taxa, depois_s * taxa
    y0, y1 = faixa
    if not y1 > y0:
        raise api.ErroSHAN("a faixa de valores da persistência é vazia")
    contagens = np.zeros((colunas, linhas), dtype=np.int64)
    dentro = fora = 0
    for i0, i1, rel in _janelas(trecho, deslocamento_s * taxa, disparo.instantes * escala, antes, depois, cancelado):
        y = ler(trecho, i0, i1)
        c = np.minimum(np.floor((rel + antes) / (antes + depois) * colunas).astype(np.int64), colunas - 1)
        r = np.floor((y - y0) / (y1 - y0) * linhas).astype(np.int64)
        ok = (c >= 0) & (c < colunas) & (r >= 0) & (r < linhas)
        np.add.at(contagens, (c[ok], r[ok]), 1)
        dentro += int(np.count_nonzero(ok))
        fora += int(len(ok) - np.count_nonzero(ok))
    return Densidade(contagens, (-antes_s, depois_s), (y0, y1), dentro, fora)


@dataclass(frozen=True)
class CicloMedio:
    """A média e o desvio dos ciclos em cada instante da grade (s desde o disparo), e as medidas do ciclo médio."""

    tempos_s: np.ndarray
    media: np.ndarray
    desvio: np.ndarray
    ciclos: int
    minimo: float
    maximo: float

    @property
    def rms(self) -> float:
        return float(np.sqrt(np.mean(self.media ** 2))) if len(self.media) else math.nan

    @property
    def pico_a_pico(self) -> float:
        return float(np.max(self.media) - np.min(self.media)) if len(self.media) else math.nan

    @property
    def valor_medio(self) -> float:
        return float(np.mean(self.media)) if len(self.media) else math.nan


def ciclo_medio(trecho: TrechoDoTraco, disparo: Disparo, antes_s: float, depois_s: float, *,
                pontos: int = PONTOS_DO_CICLO_MEDIO, deslocamento_s: float = 0.0,
                cancelado: Callable[[], bool] | None = None) -> CicloMedio:
    """Os ciclos do traço interpolados (linear) na grade de ``pontos`` instantes, a média e o desvio (Welford: um
    ciclo de cada vez), e o mínimo e o máximo das amostras dos ciclos (para a escala)."""
    taxa = trecho.captura.canal(trecho.numero).taxa_hz
    escala = taxa / disparo.taxa_hz
    antes, depois = antes_s * taxa, depois_s * taxa
    grade = np.linspace(-antes, depois, pontos)
    media = np.zeros(pontos)
    m2 = np.zeros(pontos)
    n = 0
    minimo, maximo = math.inf, -math.inf
    for i0, i1, rel in _janelas(trecho, deslocamento_s * taxa, disparo.instantes * escala, antes, depois, cancelado):
        y = ler(trecho, i0, i1)
        if rel[0] > grade[0] + 1 or rel[-1] < grade[-1] - 1:
            continue                                             # o ciclo da borda da captura: incompleto
        v = np.interp(grade, rel, y)
        n += 1
        delta = v - media
        media += delta / n
        m2 += delta * (v - media)
        minimo, maximo = min(minimo, float(np.min(y))), max(maximo, float(np.max(y)))
    desvio = np.sqrt(m2 / (n - 1)) if n > 1 else np.zeros(pontos)
    return CicloMedio(grade / taxa, media if n else np.full(pontos, np.nan), desvio, n,
                      minimo if n else math.nan, maximo if n else math.nan)


def passo_125(valor: float) -> float:
    """O menor passo da série 1-2-5 (…, 0,1, 0,2, 0,5, 1, 2, 5, 10…) que não é menor que ``valor``: a escala por
    divisão do osciloscópio."""
    if not valor > 0 or not math.isfinite(valor):
        return 1.0
    decada = 10.0 ** math.floor(math.log10(valor))
    for m in (1.0, 2.0, 5.0, 10.0):
        if m * decada >= valor * (1 - 1e-9):
            return m * decada
    return 10.0 * decada
