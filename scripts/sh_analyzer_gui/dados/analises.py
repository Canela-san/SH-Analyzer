"""As análises da Fase 7 sobre o trecho de um traço (docs/gui-progress.md, 4h), sem Qt: as estatísticas e o
histograma (F7.4), a potência pela IEEE 1459 e o XY (F7.3). As vistas (``areas/analise/vistas_de_analise.py``) só
desenham o que sai daqui.

**Os valores do trecho** (:func:`blocos_do_trecho`) são os do traço como ele aparece: o canal na unidade física, a
cadeia, e o ganho e o offset do traço; em blocos, para a captura inteira não ir para a memória. Sem cadeia, os
códigos do ADC também saem (:func:`codigos_do_trecho`): o histograma deles é exato, código a código.

**As contas** são as de referência, conferidas nos testes: os momentos centrais pela combinação de Chan (bloco a
bloco, em ``float64``, sem a perda de precisão da soma de x⁴), os percentis exatos até :data:`LIMITE_EXATO` amostras
(e pelo histograma fino acima, com o erro de meia coluna dito), e a potência pelas definições da IEEE 1459-2010
(a fundamental pelos fasores de um número inteiro de ciclos, achados pelos cruzamentos por zero do motor).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace

import numpy as np
import supraharmonicos.api as api

from .espectros import LIMITE_DA_CADEIA, AguardandoMaterializacao, TrechoDoTraco
from .materializacao import leitor_do_canal

BLOCO = 1 << 22
LIMITE_EXATO = 1 << 25
"""Até 32 M amostras (256 MB em ``float64``), os percentis são os exatos (``np.percentile``); acima, do histograma."""
COLUNAS_DO_HISTOGRAMA_FINO = 1 << 16
PERCENTIS = (1.0, 5.0, 50.0, 95.0, 99.0)
MAXIMO_DE_PONTOS_DO_XY = 200_000
"""Até tantos pontos, o XY é a curva; acima, a densidade (a persistência)."""
COLUNAS_DA_DENSIDADE = 256


# ------------------------------------------------------------------ os valores do trecho


def _afim(trecho: TrechoDoTraco) -> tuple[float, float]:
    canal = trecho.captura.canal(trecho.numero)
    ganho, offset = trecho.ganho, getattr(trecho, "offset", 0.0)
    return canal.escala * ganho, canal.deslocamento * ganho + offset


def codigos_do_trecho(trecho: TrechoDoTraco) -> np.ndarray | None:
    """Os códigos do ADC do trecho (memmap, sem cópia), ou None num traço com cadeia (os valores não são códigos)."""
    if not trecho.cadeia.vazia:
        return None
    return trecho.captura.canal(trecho.numero).amostras[trecho.inicio:trecho.fim]


def blocos_do_trecho(trecho: TrechoDoTraco, *, bloco: int = BLOCO, cancelado: Callable[[], bool] | None = None,
                     progresso: Callable[[float], None] | None = None) -> Iterator[np.ndarray]:
    """Os valores do traço no trecho, em blocos de ``float64``. Levanta :class:`AguardandoMaterializacao` num trecho
    grande de um traço com cadeia que ainda não foi materializado."""
    canal = trecho.captura.canal(trecho.numero)
    a, b, n = trecho.inicio, trecho.fim, trecho.fim - trecho.inicio
    if n <= 0:
        return
    if trecho.cadeia.vazia:
        escala, deslocamento = _afim(trecho)
        fonte = canal.amostras
    elif n <= LIMITE_DA_CADEIA:
        valores = trecho.cadeia.previa(leitor_do_canal(trecho.captura, trecho.numero), len(canal.amostras), a, b,
                                       trecho.contexto).valores
        yield valores * trecho.ganho + getattr(trecho, "offset", 0.0)
        if progresso is not None:
            progresso(1.0)
        return
    else:
        if trecho.materializada is None:
            raise AguardandoMaterializacao()
        escala, deslocamento, fonte = trecho.ganho, getattr(trecho, "offset", 0.0), trecho.materializada
    for inicio in range(a, b, bloco):
        if cancelado is not None and cancelado():
            raise api.Cancelado()
        fim = min(b, inicio + bloco)
        yield np.asarray(fonte[inicio:fim], dtype=np.float64) * escala + deslocamento
        if progresso is not None:
            progresso((fim - a) / n)


def valores_do_trecho(trecho: TrechoDoTraco, **opcoes) -> np.ndarray:
    """Os valores do trecho inteiro, numa matriz só (para o XY e a potência, que são de uma janela)."""
    partes = list(blocos_do_trecho(trecho, **opcoes))
    return np.concatenate(partes) if partes else np.zeros(0)


# ------------------------------------------------------------------ as estatísticas e o histograma (F7.4)


@dataclass(frozen=True)
class Momentos:
    """Os momentos de um conjunto, combináveis (Chan et al., 1979): n, a média e as somas centrais M2, M3 e M4."""

    n: int = 0
    media: float = 0.0
    m2: float = 0.0
    m3: float = 0.0
    m4: float = 0.0
    minimo: float = math.inf
    maximo: float = -math.inf

    @classmethod
    def de(cls, x: np.ndarray) -> Momentos:
        n = len(x)
        if n == 0:
            return cls()
        media = float(np.mean(x))
        d = x - media
        d2 = d * d
        return cls(n, media, float(np.sum(d2)), float(np.sum(d2 * d)), float(np.sum(d2 * d2)), float(np.min(x)),
                   float(np.max(x)))

    def mais(self, o: Momentos) -> Momentos:
        if o.n == 0:
            return self
        if self.n == 0:
            return o
        n = self.n + o.n
        delta = o.media - self.media
        d_n = delta / n
        m2 = self.m2 + o.m2 + delta * d_n * self.n * o.n
        m3 = (self.m3 + o.m3 + d_n * d_n * delta * self.n * o.n * (self.n - o.n)
              + 3 * d_n * (self.n * o.m2 - o.n * self.m2))
        m4 = (self.m4 + o.m4 + d_n ** 3 * delta * self.n * o.n * (self.n ** 2 - self.n * o.n + o.n ** 2)
              + 6 * d_n * d_n * (self.n ** 2 * o.m2 + o.n ** 2 * self.m2) + 4 * d_n * (self.n * o.m3 - o.n * self.m3))
        return Momentos(n, self.media + delta * o.n / n, m2, m3, m4, min(self.minimo, o.minimo),
                        max(self.maximo, o.maximo))


@dataclass(frozen=True)
class Estatisticas:
    """As estatísticas de um trecho, na unidade do traço. ``desvio`` é o desvio-padrão da população (o RMS sem o DC,
    o das medidas); a assimetria e a curtose são as da população (a curtose em excesso: 0 numa normal), as da
    ``scipy.stats`` com ``bias=True``. ``percentis_exatos``: falso quando vieram do histograma fino (com o erro de
    ``resolucao_dos_percentis``)."""

    n: int
    media: float
    rms: float
    desvio: float
    assimetria: float
    curtose: float
    minimo: float
    maximo: float
    percentis: dict[float, float]
    percentis_exatos: bool
    resolucao_dos_percentis: float = 0.0
    fator_de_crista: float = math.nan

    @property
    def pico_a_pico(self) -> float:
        return self.maximo - self.minimo


@dataclass(frozen=True)
class Histograma:
    """O histograma do trecho: as bordas das colunas (``n + 1``) e as contagens; ``saturadas_baixo``/``_alto``: as
    amostras no menor e no maior código do ADC (só sem cadeia); ``ocupacao``: a fração da faixa do ADC que o trecho
    usa (de 0 a 1)."""

    bordas: np.ndarray
    contagens: np.ndarray
    saturadas_baixo: int | None = None
    saturadas_alto: int | None = None
    ocupacao: float | None = None
    codigos: bool = False                      # as colunas são códigos do ADC (uma por código, ou juntando vários)

    @property
    def total(self) -> int:
        return int(self.contagens.sum())

    def cdf(self) -> np.ndarray:
        """A distribuição acumulada no fim de cada coluna (de 0 a 1)."""
        total = self.total
        return np.cumsum(self.contagens) / total if total else np.zeros(len(self.contagens))


@dataclass(frozen=True)
class ResultadoDoHistograma:
    estatisticas: Estatisticas
    histograma: Histograma


def _limites_do_codigo(dtype) -> tuple[int, int]:
    info = np.iinfo(dtype)
    return int(info.min), int(info.max)


def histograma_e_estatisticas(trecho: TrechoDoTraco, colunas: int = 200, *, progresso=None,
                              cancelado=None) -> ResultadoDoHistograma:
    """O histograma (``colunas`` colunas do mínimo ao máximo do trecho) e as estatísticas do trecho. Sem cadeia, a
    contagem é a dos códigos do ADC (exata) e as estatísticas saem dela; com cadeia, duas passadas pelos valores."""
    if trecho.fim <= trecho.inicio:
        raise api.ErroSHAN("o trecho está vazio")
    if not 2 <= colunas <= 100_000:
        raise api.ErroSHAN(f"o histograma tem de 2 a 100 000 colunas (pedido: {colunas})")
    codigos = codigos_do_trecho(trecho)
    if codigos is not None and np.issubdtype(codigos.dtype, np.integer) and codigos.dtype.itemsize <= 2:
        return _dos_codigos(trecho, codigos, colunas, progresso, cancelado)
    return _dos_valores(trecho, colunas, progresso, cancelado)


def _dos_codigos(trecho, codigos, colunas, progresso, cancelado) -> ResultadoDoHistograma:
    baixo, alto = _limites_do_codigo(codigos.dtype)
    contagem = np.zeros(alto - baixo + 1, dtype=np.int64)
    n = len(codigos)
    for i in range(0, n, BLOCO):
        if cancelado is not None and cancelado():
            raise api.Cancelado()
        parte = np.asarray(codigos[i:i + BLOCO]).astype(np.int64) - baixo
        contagem += np.bincount(parte, minlength=len(contagem))
        if progresso is not None:
            progresso(min(1.0, (i + BLOCO) / n))
    escala, deslocamento = _afim(trecho)
    usados = np.nonzero(contagem)[0]
    c_min, c_max = int(usados[0]), int(usados[-1])
    valores = (np.arange(len(contagem)) + baixo) * escala + deslocamento
    pesos = contagem.astype(np.float64)
    media = float(np.dot(pesos, valores) / n)
    d = valores - media
    m2, m3, m4 = (float(np.dot(pesos, d ** k)) for k in (2, 3, 4))
    acumulada = np.cumsum(contagem)
    percentis = {}
    for p in PERCENTIS:                                   # o np.percentile "linear" sobre os valores ordenados
        posicao = p / 100 * (n - 1)
        k0 = int(math.floor(posicao))
        i0 = int(np.searchsorted(acumulada, k0 + 1))
        i1 = int(np.searchsorted(acumulada, min(k0 + 2, n)))
        percentis[p] = float(valores[i0] + (posicao - k0) * (valores[i1] - valores[i0]))
    est = _estatisticas(n, media, m2, m3, m4, float(valores[c_min]), float(valores[c_max]), percentis, True, 0.0)
    # as colunas: juntam códigos vizinhos (cada coluna, um número inteiro de códigos)
    largura = max(1, math.ceil((c_max - c_min + 1) / colunas))
    inicio = c_min
    fim = c_min + largura * math.ceil((c_max - c_min + 1) / largura)
    juntas = np.zeros(fim - inicio, dtype=np.int64)
    juntas[:c_max - c_min + 1] = contagem[c_min:c_max + 1]
    contagens = juntas.reshape(-1, largura).sum(axis=1)
    bordas = (np.arange(inicio, fim + 1, largura) - 0.5 + baixo) * escala + deslocamento
    if escala < 0:
        bordas, contagens = bordas[::-1], contagens[::-1]
    h = Histograma(bordas, contagens, int(contagem[0]), int(contagem[-1]), (c_max - c_min) / (alto - baixo), True)
    return ResultadoDoHistograma(est, h)


def _estatisticas(n, media, m2, m3, m4, minimo, maximo, percentis, exatos, resolucao) -> Estatisticas:
    var = m2 / n if n else math.nan
    desvio = math.sqrt(var) if var >= 0 else math.nan
    assimetria = (m3 / n) / var ** 1.5 if var > 0 else math.nan
    curtose = (m4 / n) / var ** 2 - 3.0 if var > 0 else math.nan
    rms = math.sqrt(var + media * media) if n else math.nan
    pico = max(abs(minimo), abs(maximo))
    crista = pico / rms if rms > 0 else math.nan
    return Estatisticas(n, media, rms, desvio, assimetria, curtose, minimo, maximo, percentis, exatos, resolucao,
                        crista)


def _dos_valores(trecho, colunas, progresso, cancelado) -> ResultadoDoHistograma:
    n = trecho.fim - trecho.inicio
    exato = n <= LIMITE_EXATO

    def passada(fator, base):
        return (lambda f: progresso(base + fator * f)) if progresso is not None else None

    momentos = Momentos()
    todos = [] if exato else None
    for parte in blocos_do_trecho(trecho, cancelado=cancelado, progresso=passada(0.5, 0.0)):
        momentos = momentos.mais(Momentos.de(parte))
        if todos is not None:
            todos.append(parte)
    lo, hi = momentos.minimo, momentos.maximo
    if not hi > lo:
        hi = lo + (abs(lo) or 1.0) * 1e-9
    if todos is not None:
        x = np.concatenate(todos)
        contagens, bordas = np.histogram(x, bins=colunas, range=(lo, hi))
        percentis = dict(zip(PERCENTIS, (float(v) for v in np.percentile(x, PERCENTIS))))
        resolucao = 0.0
    else:
        fino = np.zeros(COLUNAS_DO_HISTOGRAMA_FINO, dtype=np.int64)
        for parte in blocos_do_trecho(trecho, cancelado=cancelado, progresso=passada(0.5, 0.5)):
            fino += np.histogram(parte, bins=COLUNAS_DO_HISTOGRAMA_FINO, range=(lo, hi))[0]
        bordas_finas = np.linspace(lo, hi, COLUNAS_DO_HISTOGRAMA_FINO + 1)
        acumulada = np.cumsum(fino) / momentos.n
        percentis = {p: float(np.interp(p / 100, acumulada, bordas_finas[1:])) for p in PERCENTIS}
        resolucao = (hi - lo) / COLUNAS_DO_HISTOGRAMA_FINO
        juntar = COLUNAS_DO_HISTOGRAMA_FINO // math.gcd(COLUNAS_DO_HISTOGRAMA_FINO, colunas)
        if juntar * colunas == COLUNAS_DO_HISTOGRAMA_FINO:
            contagens = fino.reshape(colunas, -1).sum(axis=1)
        else:                                            # colunas que não dividem o fino: refaz pela posição
            centros = (bordas_finas[:-1] + bordas_finas[1:]) / 2
            contagens = np.histogram(centros, bins=colunas, range=(lo, hi), weights=fino)[0].astype(np.int64)
        bordas = np.linspace(lo, hi, colunas + 1)
    est = _estatisticas(momentos.n, momentos.media, momentos.m2, momentos.m3, momentos.m4, momentos.minimo,
                        momentos.maximo, percentis, exato, resolucao)
    return ResultadoDoHistograma(est, Histograma(bordas, contagens))


# ------------------------------------------------------------------ a potência (F7.3, ME-03)


@dataclass(frozen=True)
class Potencia:
    """As grandezas da IEEE 1459-2010 (seção 3.2, monofásico) de uma tensão ``v`` e uma corrente ``i`` num número
    inteiro de ciclos da fundamental da tensão:

    * ``v_rms``, ``i_rms``: os valores eficazes totais; ``v1``, ``i1``: os da fundamental;
    * ``p``: a potência ativa (a média de v·i); ``s = v_rms·i_rms``: a aparente; ``fp = p / s``: o fator de potência;
    * ``p1``, ``q1``, ``s1``: as da fundamental (``q1 = v1·i1·sen θ1``, positiva quando a corrente atrasa: indutiva);
    * ``cos_fi1``: o fator de potência de deslocamento; ``fi1_graus``: θ1, o ângulo da tensão menos o da corrente;
    * ``sn = sqrt(s² − s1²)``: a potência aparente não fundamental; ``thd_v``, ``thd_i`` em fração (I_H / I_1).
    """

    f1_hz: float
    ciclos: int
    v_rms: float
    i_rms: float
    v1: float
    i1: float
    p: float
    s: float
    fp: float
    p1: float
    q1: float
    s1: float
    cos_fi1: float
    fi1_graus: float
    sn: float
    thd_v: float
    thd_i: float


def _media_continua(y: np.ndarray, c0: float, c1: float):
    """A média de ``y`` (amostrado nos índices inteiros) de ``c0`` a ``c1`` (com fração): a integral pelo trapézio,
    com as pontas interpoladas. Num número inteiro de ciclos que não cai em amostras inteiras, a média de um produto
    de senos não erra pelo pedaço de amostra que sobra (o erro fica o do trapézio, (ωΔt)²/12)."""
    i0, i1 = math.ceil(c0), math.floor(c1)
    dentro = np.trapezoid(y[i0:i1 + 1]) if i1 > i0 else 0.0
    esquerda = y[i0 - 1] + (c0 - (i0 - 1)) * (y[i0] - y[i0 - 1]) if i0 > c0 else y[i0]
    direita = y[i1] + (c1 - i1) * (y[i1 + 1] - y[i1]) if c1 > i1 else y[i1]
    return (dentro + (i0 - c0) * (esquerda + y[i0]) / 2 + (c1 - i1) * (y[i1] + direita) / 2) / (c1 - c0)


def potencia(v: np.ndarray, i: np.ndarray, taxa_hz: float, *, freq_min: float = api.FREQ_MIN_FUNDAMENTAL,
             freq_max: float = api.FREQ_MAX_FUNDAMENTAL) -> Potencia:
    """A potência de ``v`` e ``i`` (as mesmas amostras no tempo, a mesma taxa). Os ciclos inteiros vão do primeiro
    ao último cruzamento por zero subindo da fundamental de ``v`` (o motor os acha). Levanta ``api.ErroSHAN`` sem
    uma fundamental ou com menos de um ciclo."""
    v = np.asarray(v, dtype=np.float64)
    i = np.asarray(i, dtype=np.float64)
    if v.shape != i.shape:
        raise api.ErroSHAN(f"a tensão e a corrente têm tamanhos diferentes ({len(v)} e {len(i)} amostras)")
    if len(v) < 4:
        raise api.ErroSHAN("o trecho é curto demais para a potência")
    cruzamentos, f1 = api.cruzamentos_da_fundamental(v, taxa_hz, freq_min, freq_max)
    if len(cruzamentos) < 2:
        raise api.ErroSHAN("o trecho tem menos de um ciclo inteiro da fundamental da tensão")
    c0, c1 = float(cruzamentos[0]), float(cruzamentos[-1])
    ciclos = len(cruzamentos) - 1
    f1_exata = ciclos * taxa_hz / (c1 - c0)
    a, b = max(0, math.floor(c0) - 1), min(len(v), math.ceil(c1) + 2)
    vv, ii = v[a:b], i[a:b]
    c0, c1 = c0 - a, c1 - a
    giro = np.exp(-1j * 2 * np.pi * f1_exata * (np.arange(len(vv)) - c0) / taxa_hz)
    v1f = complex(_media_continua(vv * giro, c0, c1)) * math.sqrt(2)      # o fasor RMS da fundamental
    i1f = complex(_media_continua(ii * giro, c0, c1)) * math.sqrt(2)
    v_rms = math.sqrt(float(_media_continua(vv * vv, c0, c1)))
    i_rms = math.sqrt(float(_media_continua(ii * ii, c0, c1)))
    p = float(_media_continua(vv * ii, c0, c1))
    s = v_rms * i_rms
    v1, i1 = abs(v1f), abs(i1f)
    theta = float(np.angle(v1f) - np.angle(i1f))
    theta = (theta + math.pi) % (2 * math.pi) - math.pi
    p1, q1, s1 = v1 * i1 * math.cos(theta), v1 * i1 * math.sin(theta), v1 * i1
    vh = math.sqrt(max(v_rms ** 2 - v1 ** 2, 0.0))
    ih = math.sqrt(max(i_rms ** 2 - i1 ** 2, 0.0))
    return Potencia(f1_hz=float(f1_exata if math.isfinite(f1_exata) else f1), ciclos=ciclos, v_rms=v_rms,
                    i_rms=i_rms, v1=v1, i1=i1, p=p, s=s, fp=p / s if s > 0 else math.nan, p1=p1, q1=q1, s1=s1,
                    cos_fi1=math.cos(theta), fi1_graus=math.degrees(theta),
                    sn=math.sqrt(max(s * s - s1 * s1, 0.0)), thd_v=vh / v1 if v1 > 0 else math.nan,
                    thd_i=ih / i1 if i1 > 0 else math.nan)


# ------------------------------------------------------------------ o XY (F7.3)


@dataclass(frozen=True)
class ResultadoDoXY:
    """O XY de dois traços: a curva (``x``, ``y``, até :data:`MAXIMO_DE_PONTOS_DO_XY` pontos) ou a densidade (a
    persistência: quantas amostras caem em cada célula, com os limites); e a potência, quando os dois são uma tensão
    e uma corrente (ou o pedido)."""

    x: np.ndarray | None
    y: np.ndarray | None
    densidade: np.ndarray | None
    limites: tuple[float, float, float, float]
    n: int
    potencia: Potencia | None = None
    problema_da_potencia: str = ""


def xy(vx: np.ndarray, vy: np.ndarray, taxa_hz: float, *, com_potencia: bool = True,
       colunas: int = COLUNAS_DA_DENSIDADE) -> ResultadoDoXY:
    """O XY de ``vx`` (horizontal) e ``vy`` (vertical), as mesmas amostras no tempo."""
    if len(vx) != len(vy):
        raise api.ErroSHAN(f"os dois traços têm tamanhos diferentes no trecho ({len(vx)} e {len(vy)} amostras)")
    n = len(vx)
    if n == 0:
        raise api.ErroSHAN("o trecho está vazio")
    limites = (float(np.min(vx)), float(np.max(vx)), float(np.min(vy)), float(np.max(vy)))
    if n <= MAXIMO_DE_PONTOS_DO_XY:
        r = ResultadoDoXY(np.asarray(vx), np.asarray(vy), None, limites, n)
    else:
        x0, x1, y0, y1 = limites
        densidade, _bx, _by = np.histogram2d(vx, vy, bins=colunas,
                                             range=((x0, x1 if x1 > x0 else x0 + 1), (y0, y1 if y1 > y0 else y0 + 1)))
        r = ResultadoDoXY(None, None, densidade, limites, n)
    if com_potencia:
        try:
            r = replace(r, potencia=potencia(vx, vy, taxa_hz))
        except api.ErroSHAN as e:
            r = replace(r, problema_da_potencia=str(e))
    return r
