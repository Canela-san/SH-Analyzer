"""O ``TracoLOD``: o item de gráfico que desenha um canal de qualquer tamanho, em qualquer zoom, a 60 quadros por
segundo (docs/gui-plan.md, seção 6.4).

Ele vive dentro de um ``PlotItem`` do PyQtGraph (que cuida dos eixos, da grade, do zoom e do pan) e, a cada mudança da
vista, pede à camada de dados (``dados.consulta``) só o que cabe nas colunas de pixel visíveis:

* **de longe**, a envoltória mín/máx de cada coluna, desenhada como **uma linha vertical de 1 px por coluna de
  pixel**, do mínimo ao máximo dela (o desenho dos osciloscópios digitais). Cada coluna pinta exatamente o seu pixel:
  um pico de uma amostra aparece inteiro, na coluna dele, e nada vaza para as vizinhas. Medido no protótipo
  (``prototipos/navegar.py``, 2 traços, 1 400 x 790 px): p95 de 9 ms por quadro em qualquer zoom. O polígono
  preenchido, que o benchmark mostrava rápido na banda uniforme (a captura inteira), passa de 150 ms no zoom
  intermediário, em que a banda de 60 Hz oscila de coluna para coluna e vira centenas de arestas longas;
* **de perto** (até 2 amostras por coluna), a linha que passa pelas amostras, com 1 px e antialiasing, e os pontos
  das amostras a partir de :data:`PIXELS_POR_AMOSTRA_PONTOS` pixels por amostra.

**De perto, o desenho é em pixels da tela:** a linha e os pontos das amostras passam para pixels aqui (a conta é do
NumPy) e vão ao QPainter sem a transformação da vista. Bem de perto, a escala do tempo passa de um milhão de pixels
por segundo, e o QPainter, com a caneta larga dos pontos nessa escala, pintava um bloco cheio entre as amostras em
vez dos pontos (o "retângulo" que aparecia de um passo da roda para o outro, com 8 pixels por amostra ou mais).

**A linha tem sempre 1 px na tela** (caneta cosmética): linha mais grossa com antialiasing custa até 100 s por quadro
no QPainter. A espessura de publicação é propriedade da figura (seção 10), não da tela. As colunas são de pixel do
dispositivo (em tela com escala de 200 %, o dobro das lógicas), e a caneta tem 1 pixel do dispositivo.

**Um cálculo por quadro:** a mudança da vista só agenda o recálculo (um ``QTimer`` de intervalo 0); várias mudanças no
mesmo ciclo de eventos (x e y, ou várias rodadas do mouse) viram uma consulta só.

Os valores chegam à tela pela conversão afim do traço (``escala`` e ``deslocamento``: códigos -> volts, ganho, offset,
inversão), aplicada à consulta e não aos dados.

**A escala própria do traço** (``graficos/escalas.py``) é a transformação do item na caixa (``setTransform``): a
consulta, os limites e os valores ficam na unidade do traço, e só o desenho (e a distância do clique) a usa.
"""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from pyqtgraph import functions as fn
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF

from ..dados.consulta import Amostras, Envoltoria, aplicar_afim, consultar
from ..dados.piramide import Piramide
from .clique import distancia_a_colunas, distancia_a_linha

PIXELS_POR_AMOSTRA_PONTOS = 8.0
"""A partir de quantos pixels por amostra os pontos das amostras aparecem."""


def _poligono(x: np.ndarray, y: np.ndarray) -> QPolygonF:
    """Um ``QPolygonF`` a partir de dois vetores, escrevendo direto na memória dele (sem um laço em Python)."""
    poligono = fn.create_qpolygonf(len(x))
    pontos = fn.ndarray_from_qpolygonf(poligono)
    pontos[:, 0] = x
    pontos[:, 1] = y
    return poligono


def _trechos_finitos(valores: np.ndarray, *outros: np.ndarray) -> list[tuple[int, int]]:
    """Os trechos ``[a, b)`` em que ``valores`` (e os ``outros``) são finitos: um ``NaN`` interrompe o desenho em vez
    de virar um vértice inválido."""
    finitos = np.isfinite(valores)
    for o in outros:
        finitos &= np.isfinite(o)
    if finitos.all():
        return [(0, len(valores))]
    bordas = np.flatnonzero(np.diff(np.concatenate([[False], finitos, [False]]).astype(np.int8)))
    return list(zip(bordas[0::2].tolist(), bordas[1::2].tolist()))


def _colunas_ligadas(minimos: np.ndarray, maximos: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """O trecho de cada coluna esticado até a anterior quando não encosta nela (ver :func:`_segmentos_de_coluna`)."""
    mn, mx = minimos.copy(), maximos.copy()
    sobe = minimos[1:] > maximos[:-1]               # a coluna está toda acima da anterior
    desce = maximos[1:] < minimos[:-1]              # toda abaixo
    mn[1:][sobe] = maximos[:-1][sobe]
    mx[1:][desce] = minimos[:-1][desce]
    return mn, mx


def _segmentos_de_coluna(centros_x: np.ndarray, minimos: np.ndarray, maximos: np.ndarray,
                         altura_pixel: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Os pontos (aos pares) das linhas verticais da envoltória: a coluna ``c`` vai de ``minimos[c]`` a
    ``maximos[c]`` em ``centros_x[c]``. Colunas com ``NaN`` ficam de fora (um buraco no desenho).

    **A ligação entre colunas:** se o trecho de uma coluna não encosta no da anterior (um degrau rápido do sinal),
    ele é esticado até ela -- é o pedaço vertical que a linha de todos os pontos desenharia ali, e fica dentro do
    que as duas colunas já têm (nada é inventado).

    **A altura mínima:** uma coluna mais baixa que ``altura_pixel`` (um sinal quase constante) cresce para os dois
    lados até ela -- o QPainter não desenha uma linha de comprimento zero, e a coluna sumiria."""
    mn, mx = _colunas_ligadas(minimos, maximos)
    if altura_pixel > 0:
        baixa = (mx - mn) < altura_pixel
        meio = (mx[baixa] + mn[baixa]) / 2
        mn[baixa], mx[baixa] = meio - altura_pixel / 2, meio + altura_pixel / 2
    finitas = np.isfinite(mn) & np.isfinite(mx)
    x = np.repeat(centros_x[finitas], 2)
    y = np.empty(len(x))
    y[0::2], y[1::2] = mn[finitas], mx[finitas]
    return x, y

class TracoLOD(pg.GraphicsObject):
    """Um canal desenhado pela pirâmide.

    ``amostras`` é o vetor do canal (a visão com passo dentro do memmap da captura) e ``piramide`` a dele. O eixo x é
    o tempo em segundos: a amostra ``i`` fica em ``t0 + i / taxa_hz``. O eixo y é ``valor * escala + deslocamento``.

    **Os dados podem ser só um pedaço do canal** (:meth:`definir_dados`): a prévia da janela visível de um traço com
    transformações, ou o começo já materializado dele. ``inicio`` diz qual amostra do canal é a primeira dos dados, e
    ``n_total`` o tamanho do canal inteiro: os limites do tempo (o "ajustar tudo") são sempre os do canal.
    """

    def __init__(self, piramide: Piramide, amostras: np.ndarray, taxa_hz: float, *, t0: float = 0.0,
                 escala: float = 1.0, deslocamento: float = 0.0, cor: str | QColor = "#7dd3fc", nome: str = "",
                 inicio: int = 0, n_total: int | None = None):
        super().__init__()
        if taxa_hz <= 0:
            raise ValueError(f"taxa_hz deve ser > 0 (recebido {taxa_hz}).")
        self._piramide = piramide
        self._amostras = amostras
        self._inicio = int(inicio)
        self._n_total = piramide.n_amostras if n_total is None else int(n_total)
        self._taxa = float(taxa_hz)
        self._t0 = float(t0)
        self._escala = float(escala)
        self._deslocamento = float(deslocamento)
        self.nome = nome
        self._cor = QColor(cor)
        self._consulta: Amostras | Envoltoria | None = None
        self._colunas: QPainterPath | None = None   # as linhas verticais da envoltória (aos pares)
        # A linha das amostras, um trecho (x, y) por pedaço finito, nas unidades da vista: vai para pixels ao pintar.
        self._linhas: list[tuple[np.ndarray, np.ndarray]] = []
        self._pontos = False                        # os pontos das amostras também
        self._dpr = 1.0
        self._sujo = False               # escondido quando a vista mudou: consulta ao aparecer
        self.recalculos = 0              # quantas consultas foram feitas (para os testes e o medidor de quadros)
        self.pinturas = 0                # quantas vezes foi pintado (o medidor de quadros por segundo)
        self._limites = self._calcular_limites()
        self._agendador = QTimer(self)        # filho do item: some junto com ele
        self._agendador.setSingleShot(True)
        self._agendador.setInterval(0)
        self._agendador.timeout.connect(self.recalcular)

    # ------------------------------------------------------------------ propriedades

    @property
    def cor(self) -> QColor:
        return QColor(self._cor)

    def definir_cor(self, cor: str | QColor) -> None:
        self._cor = QColor(cor)
        self.update()

    def definir_afim(self, escala: float, deslocamento: float) -> None:
        """Muda a conversão do eixo y (ganho, offset, inversão): instantâneo em qualquer tamanho de captura."""
        self.prepareGeometryChange()
        self._escala, self._deslocamento = float(escala), float(deslocamento)
        self._limites = self._calcular_limites()
        self.informViewBoundsChanged()
        self.recalcular()

    @property
    def _origem(self) -> float:
        """O tempo da primeira amostra dos dados."""
        return self._t0 + self._inicio / self._taxa

    @property
    def dados(self) -> tuple[Piramide, np.ndarray, int]:
        """A pirâmide, as amostras e o início (no canal) dos dados desenhados agora."""
        return self._piramide, self._amostras, self._inicio

    def definir_dados(self, piramide: Piramide, amostras: np.ndarray, inicio: int = 0, *, taxa_hz: float | None = None,
                      t0: float | None = None, n_total: int | None = None) -> None:
        """Troca os dados desenhados (a prévia, o começo materializado, o traço pronto) sem recriar o item: a cor, a
        conversão e a posição na faixa ficam. Dados com outra grade (o espectro de um trecho de outro tamanho tem outro
        espaçamento entre os bins, e outro número deles) trazem ``taxa_hz``, ``t0`` e ``n_total`` novos: sem eles, o
        eixo x ficaria na grade dos dados de antes."""
        if taxa_hz is not None and taxa_hz <= 0:
            raise ValueError(f"taxa_hz deve ser > 0 (recebido {taxa_hz}).")
        self.prepareGeometryChange()
        self._piramide, self._amostras, self._inicio = piramide, amostras, int(inicio)
        if taxa_hz is not None:
            self._taxa = float(taxa_hz)
        if t0 is not None:
            self._t0 = float(t0)
        if n_total is not None:
            self._n_total = int(n_total)
        self._limites = self._calcular_limites()
        self.informViewBoundsChanged()
        self.recalcular()

    def definir_t0(self, t0: float) -> None:
        """Anda o traço no tempo (o deslocamento da receita): a amostra 0 passa a ficar em ``t0``."""
        self.prepareGeometryChange()
        self._t0 = float(t0)
        self._limites = self._calcular_limites()
        self.informViewBoundsChanged()
        self.recalcular()

    @property
    def consulta(self) -> Amostras | Envoltoria | None:
        """O resultado da última consulta, já na unidade do eixo y (para as medidas e os testes)."""
        return self._consulta

    def tempo_da_amostra(self, indice: float) -> float:
        return self._origem + indice / self._taxa

    def limites_y_em(self, x0: float, x1: float) -> tuple[float, float] | None:
        """O mínimo e o máximo do traço (na unidade do eixo y) entre os tempos ``x0`` e ``x1``, ou None se os dados
        não têm amostra ali (a prévia de outra janela, o começo materializado que ainda não chegou). Uma consulta de
        uma coluna só à pirâmide: barata em qualquer tamanho."""
        inicio, fim = (x0 - self._origem) * self._taxa, (x1 - self._origem) * self._taxa + 1
        if fim <= 0 or inicio >= self._piramide.n_amostras:
            return None
        c = aplicar_afim(consultar(self._piramide, self._amostras, inicio, fim, 1), self._escala, self._deslocamento)
        valores = (np.concatenate([c.minimos, c.maximos]) if isinstance(c, Envoltoria) else np.asarray(c.valores))
        valores = valores[np.isfinite(valores)]
        return (float(valores.min()), float(valores.max())) if len(valores) else None

    # ------------------------------------------------------------------ os limites (autoRange e boundingRect)

    def _calcular_limites(self) -> tuple[float, float, float, float]:
        x0, x1 = self._t0, self._t0 + max(self._n_total - 1, 0) / self._taxa
        if not self._piramide.niveis:
            return x0, x1, 0.0, 0.0
        topo = self._piramide.niveis[-1]
        mn = topo.minimos.astype(np.float64) * self._escala + self._deslocamento
        mx = topo.maximos.astype(np.float64) * self._escala + self._deslocamento
        y0, y1 = float(np.nanmin(np.minimum(mn, mx))), float(np.nanmax(np.maximum(mn, mx)))
        return x0, x1, y0, y1

    # Os nomes em inglês abaixo são os que o PyQtGraph chama.
    def dataBounds(self, ax, frac=1.0, orthoRange=None):
        x0, x1, y0, y1 = self._limites
        return (x0, x1) if ax == 0 else (y0, y1)

    def pixelPadding(self):
        return 0

    def boundingRect(self):
        x0, x1, y0, y1 = self._limites
        return QRectF(x0, y0, max(x1 - x0, 1e-12), max(y1 - y0, 1e-12))

    # ------------------------------------------------------------------ a vista mudou: agenda uma consulta

    def viewChanged(self, view, oldView):
        self._agendador.start()             # entrou numa ViewBox: a primeira consulta

    def viewRangeChanged(self):
        self._agendador.start()

    def viewTransformChanged(self):
        self._agendador.start()

    def _colunas_visiveis(self) -> int:
        """Uma coluna por pixel do dispositivo (em tela com escala de 200 %, o dobro das lógicas)."""
        vb = self.getViewBox()
        largura = vb.width() if vb is not None else 0
        cena = self.scene()
        vistas = cena.views() if cena is not None else ()
        self._dpr = (vistas[0].devicePixelRatioF() or 1.0) if vistas else 1.0
        return max(1, int(math.ceil(largura * self._dpr)))

    def itemChange(self, mudanca, valor):
        # Um traço escondido não consulta nada (recalcular só desenharia para ninguém); ao aparecer, consulta.
        resultado = super().itemChange(mudanca, valor)
        if mudanca == self.GraphicsItemChange.ItemVisibleHasChanged and valor and self._sujo:
            self._agendador.start()
        elif mudanca == self.GraphicsItemChange.ItemTransformHasChanged:
            self._agendador.start()             # a escala própria mudou: a altura de um pixel, nos valores, também
        return resultado

    def _escala_propria(self) -> tuple[float, float]:
        """(k, c) da escala própria: y na vista = k·valor + c."""
        t = self.transform()
        return t.m22() or 1.0, t.dy()

    def recalcular(self) -> None:
        """Consulta a janela visível e monta os polígonos do próximo quadro."""
        vb = self.getViewBox()
        if vb is None:
            return
        if not self.isVisible():
            self._sujo = True
            return
        self._sujo = False
        (x0, x1), (y0, y1) = vb.viewRange()
        colunas = self._colunas_visiveis()
        inicio = (x0 - self._origem) * self._taxa
        fim = (x1 - self._origem) * self._taxa + 1
        consulta = aplicar_afim(consultar(self._piramide, self._amostras, inicio, fim, colunas),
                                self._escala, self._deslocamento)
        self.recalculos += 1
        self._consulta = consulta
        self._colunas, self._linhas, self._pontos = None, [], False
        if isinstance(consulta, Envoltoria) and len(consulta):
            centros = self._origem + (consulta.bordas[:-1] + consulta.bordas[1:] - 1) / (2 * self._taxa)
            # 1 pixel do dispositivo, em unidades de y. Direto da faixa visível e da altura da caixa: o
            # viewPixelSize do PyQtGraph mapeia pontos pela matriz em Python e custava 0,23 ms por traço e quadro.
            altura_pixel = abs(y1 - y0) / max(vb.height(), 1.0) / self._dpr / abs(self._escala_propria()[0])
            x, y = _segmentos_de_coluna(centros, consulta.minimos, consulta.maximos, altura_pixel)
            # Sem a conferência de finitos: os segmentos já saem sem NaN (as colunas vazias ficam de fora).
            self._colunas = fn.arrayToQPath(x, y, connect="pairs", finiteCheck=False) if len(x) else None
        elif isinstance(consulta, Amostras) and len(consulta):
            x = self._origem + consulta.indices / self._taxa
            self._linhas = [(x[a:b], consulta.valores[a:b]) for a, b in _trechos_finitos(consulta.valores)]
            pixels_por_amostra = colunas / max((x1 - x0) * self._taxa, 1e-12)
            self._pontos = pixels_por_amostra >= PIXELS_POR_AMOSTRA_PONTOS
        self.update()

    # ------------------------------------------------------------------ o desenho

    def paint(self, p: QPainter, *args) -> None:
        self.pinturas += 1
        if self._colunas is None and not self._linhas:
            return
        caneta = QPen(self._cor, 1.0 / self._dpr)       # 1 pixel do dispositivo
        caneta.setCosmetic(True)
        if self._colunas is not None:
            # Sem antialiasing: cada linha cai no centro de um pixel e o pinta inteiro, sem borrar as vizinhas.
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            caneta.setCapStyle(Qt.PenCapStyle.SquareCap)
            p.setPen(caneta)
            p.drawPath(self._colunas)
            return
        # A linha e os pontos em pixels da tela (ver o começo do arquivo): a transformação da vista vai para o NumPy,
        # e o QPainter desenha sem ela. O recorte da caixa continua valendo (ele é da tela, não da transformação).
        t = p.transform()
        poligonos = [_poligono(x * t.m11() + y * t.m21() + t.dx(), x * t.m12() + y * t.m22() + t.dy())
                     for x, y in self._linhas]
        p.save()
        p.resetTransform()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(caneta)
        for poligono in poligonos:
            p.drawPolyline(poligono)
        if self._pontos:
            ponto = QPen(self._cor, 4.0 / self._dpr)
            ponto.setCosmetic(True)
            ponto.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(ponto)
            for poligono in poligonos:
                p.drawPoints(poligono)
        p.restore()

    def ponto_mais_proximo(self, x: float) -> QPointF | None:
        """O ponto desenhado mais perto do tempo ``x`` (para a dica de valor): o centro da coluna ou a amostra."""
        c = self._consulta
        if c is None or not len(c):
            return None
        if isinstance(c, Amostras):
            i = int(np.clip(np.searchsorted(c.indices, (x - self._origem) * self._taxa), 0, len(c) - 1))
            return QPointF(self.tempo_da_amostra(c.indices[i]), float(c.valores[i]))
        col = int(np.clip(np.searchsorted(c.bordas, (x - self._origem) * self._taxa, side="right") - 1, 0, len(c) - 1))
        return QPointF(self.tempo_da_amostra((c.bordas[col] + c.bordas[col + 1] - 1) / 2), float(c.maximos[col]))

    def distancia_em_pixels(self, x: float, y: float) -> float:
        """Quantos pixels da tela separam o ponto ``(x, y)`` (nas unidades da vista) do desenho do traço: de perto,
        da linha entre as amostras; de longe, das linhas verticais das colunas em volta do ponto, como desenhadas.
        ``inf`` sem desenho. Serve para selecionar o traço clicando perto dele (``graficos/clique.py``)."""
        c, vb = self._consulta, self.getViewBox()
        if c is None or not len(c) or vb is None:
            return math.inf
        largura_px, altura_px = vb.viewPixelSize()
        k, deslocamento = self._escala_propria()           # o ponto e o pixel na unidade do traço
        y, altura_px = (y - deslocamento) / k, altura_px / abs(k)
        if isinstance(c, Amostras):
            return distancia_a_linha(x, y, self._origem + c.indices / self._taxa, c.valores, largura_px, altura_px)
        centros = self._origem + (c.bordas[:-1] + c.bordas[1:] - 1) / (2 * self._taxa)
        mn, mx = _colunas_ligadas(c.minimos, c.maximos)
        return distancia_a_colunas(x, y, centros, mn, mx, largura_px, altura_px)
