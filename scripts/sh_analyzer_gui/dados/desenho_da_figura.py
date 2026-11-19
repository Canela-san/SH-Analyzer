"""O desenho da figura com o Matplotlib (a F5.2; docs/gui-plan.md, 10.1 e 10.3), sem Qt: a figura do projeto
(``figura.py``) vira uma página do Matplotlib no tamanho dela, que a prévia (a área Figuras) e a exportação (a F5.4)
usam iguais.

**Os dados vêm de fora** (:class:`DadosDaFigura`): quem desenha não sabe de capturas abertas, de materializações nem
de temas. Para cada traço de tempo, a pirâmide e as amostras (as do canal ou as da materialização), a taxa, o início,
a conversão para a unidade física, a cor e o nome; para cada traço de espectro, o desenho já calculado pela vista
(``espectros.Desenho``) e o rótulo do eixo; e a janela que a vista mostra (os limites de um painel ligado sem limites
próprios).

**A vista de tempo** sai como ela está na tela: uma faixa por eixo (a mesma ordem, o tempo compartilhado e os números
do tempo só embaixo), ou todos os traços num eixo se ela sobrepõe. Os limites do y são os extremos exatos da janela
(pela pirâmide, com as pontas lidas das amostras), com 4 % de folga; os de um painel com ``limites_y`` valem quando a
vista tem uma faixa só.

**A fidelidade** (10.3): cada traço é reduzido pelo M4 (a primeira, a mínima, a máxima e a última amostra de cada
coluna, nos instantes delas) em 2 colunas por pixel do dispositivo final, **alinhadas aos pixels do eixo**: o desenho
tem duas passadas, a primeira acha o leiaute (os eixos, os rótulos, os limites já fixos) e a segunda reduz cada traço
nas colunas que caem sobre os pixels. Na linha de 1 pixel, a curva reduzida pinta o que a de todos os pontos pinta
(Jugel et al., 2014); no traço mais grosso da página, a borda do traço pode mudar de 1 pixel (ela depende da posição
de cada ponto dentro da coluna): ``tests/test_gui_desenho_da_figura.py`` compara as duas pixel a pixel (a distância
de Hausdorff de 1 pixel, ~5 % dos pixels de tinta na borda, nenhum pico perdido). Um eixo de 1 000 px desenha ~8 000
pontos de uma captura de qualquer tamanho. ``exato=False`` (a prévia na tela) troca a leitura das amostras pela
envoltória da pirâmide, com a primeira e a última de cada coluna lidas direto: o mesmo desenho a olho, sem ler a
captura inteira. ``todos_os_pontos=True`` desliga a redução.

**Os números** saem no idioma da figura (o separador decimal, o sinal de menos tipográfico) e com o prefixo do SI comum
ao eixo ("Tensão (kV)"); o tempo em ms abaixo de 2 s, como o ``adc_tool``.

**As vistas que ainda não entram** (as bandas, o espectrograma, os harmônicos) deixam o painel com um aviso; o
espectro congelado também (a cópia da vista não guarda o espectro, e recalculá-lo fica para depois).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
from matplotlib import font_manager, rc_context
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure as FiguraDoMatplotlib
from matplotlib.ticker import FuncFormatter, NullFormatter, ScalarFormatter
from matplotlib.transforms import Bbox
from supraharmonicos.api import Cancelado

from .consulta import Amostras, consultar
from .espectros import Desenho, envoltoria_log
from .figura import Estilo, Figura, Painel
from .piramide import Piramide
from .projeto import VistaSalva
from .receita import ReceitaDoTraco
from .unidades import PREFIXO_DO_EXPOENTE, aceita_prefixos, expoente_de_engenharia
from .unidades import grandeza as grandeza_da_unidade

PASTA_DAS_FONTES = Path(__file__).resolve().parents[1] / "recursos" / "fontes"
FAMILIAS_DO_MATPLOTLIB = {"STIX": ("STIXGeneral", "stix"), "DejaVu Sans": ("DejaVu Sans", "dejavusans"),
                          "Inter": ("Inter", "dejavusans"), "IBM Plex Sans": ("IBM Plex Sans", "dejavusans")}
"""A família do estilo -> (o nome dela no Matplotlib, as letras da matemática)."""
COLUNAS_POR_PIXEL = 2
DPI_DO_LEIAUTE = 150.0
LIMIAR_DO_TEMPO_EM_MS = 2.0
FOLGA_DO_Y = 0.04
LOTE_DO_M4 = 1 << 23                    # amostras lidas de uma vez na redução exata (~64 MB em float64)
TEXTOS = {"pt-BR": {"tempo": "Tempo", "frequencia": "Frequência", "valor": "Valor", "nivel": "Nível",
                    "depois": "Este tipo de vista entra nas figuras depois", "vazio": "Painel vazio",
                    "sem_dados": "Sem dados", "espectro_congelado": "O espectro congelado entra nas figuras depois"},
          "en": {"tempo": "Time", "frequencia": "Frequency", "valor": "Value", "nivel": "Level",
                 "depois": "This view type comes to figures later", "vazio": "Empty panel", "sem_dados": "No data",
                 "espectro_congelado": "Frozen spectra come to figures later"}}
GRANDEZAS_EM_INGLES = {
    "aceleração": "Acceleration", "ângulo": "Angle", "campo magnético": "Magnetic field", "comprimento": "Length",
    "corrente": "Current", "deformação": "Strain", "deslocamento": "Displacement", "energia": "Energy",
    "força": "Force", "frequência": "Frequency", "iluminância": "Illuminance", "massa": "Mass",
    "percentual": "Percentage", "potência": "Power", "potência aparente": "Apparent power",
    "potência reativa": "Reactive power", "pressão": "Pressure", "resistência": "Resistance",
    "rotação": "Rotational speed", "temperatura": "Temperature", "tensão": "Voltage", "torque": "Torque",
    "umidade relativa": "Relative humidity", "vazão": "Flow rate", "velocidade": "Velocity"}
"""As grandezas do catálogo de ``unidades`` em inglês (o teste confere que nenhuma falta)."""


# ------------------------------------------------------------------ o que vem de fora

@dataclass(frozen=True, eq=False)
class SerieDoTempo:
    """Um traço de tempo: as ``amostras`` (a posição 0 é a amostra ``inicio`` do canal) e a ``piramide`` delas, a
    taxa, ``t0`` (o deslocamento no tempo, em s), a conversão ``valor = amostra · escala + deslocamento`` para a
    ``unidade``, e como desenhá-lo."""

    piramide: Piramide
    amostras: np.ndarray
    taxa_hz: float
    nome: str
    cor: str
    unidade: str = ""
    t0: float = 0.0
    escala: float = 1.0
    deslocamento: float = 0.0
    inicio: int = 0
    tracejado: bool = False
    grandeza: str = ""                  # a do canal ("tensão"), quando a unidade não a diz (uma unidade digitada)

    def __post_init__(self) -> None:
        if not (self.taxa_hz > 0 and math.isfinite(self.taxa_hz)):
            raise ValueError(f"taxa inválida: {self.taxa_hz!r}")
        if len(self.amostras) != self.piramide.n_amostras:
            raise ValueError("as amostras e a pirâmide não são do mesmo tamanho")


@dataclass(frozen=True, eq=False)
class SerieDoEspectro:
    """Um traço de espectro: o desenho da vista (os níveis na escala dela, numa grade uniforme), o rótulo do eixo y
    ("dBV", "V") e se a frequência é logarítmica."""

    desenho: Desenho
    nome: str
    cor: str
    rotulo_y: str = ""
    frequencia_log: bool = False
    tracejado: bool = False


class DadosDaFigura(Protocol):
    """O que o desenho pede a quem tem as capturas (a área Figuras, com o projeto aberto; um teste, com vetores)."""

    def tempo(self, vista: VistaSalva, receita: ReceitaDoTraco) -> SerieDoTempo | None: ...

    def espectros(self, vista: VistaSalva) -> Sequence[SerieDoEspectro]: ...

    def janela(self, vista: VistaSalva) -> tuple[float, float] | None: ...


class DadosColhidos:
    """O que :func:`colher` tirou de outro :class:`DadosDaFigura`, guardado: a área Figuras colhe na thread da
    interface (as vistas abertas, as materializações) e desenha numa de trabalho, que só lê estes vetores."""

    def __init__(self):
        self._tempo: dict[tuple[int, ReceitaDoTraco], SerieDoTempo | None] = {}
        self._espectros: dict[int, list[SerieDoEspectro]] = {}
        self._janela: dict[int, tuple[float, float] | None] = {}

    def tempo(self, vista: VistaSalva, receita: ReceitaDoTraco) -> SerieDoTempo | None:
        return self._tempo.get((id(vista), receita))

    def espectros(self, vista: VistaSalva) -> list[SerieDoEspectro]:
        return self._espectros.get(id(vista), [])

    def janela(self, vista: VistaSalva) -> tuple[float, float] | None:
        return self._janela.get(id(vista))


def colher(figura: Figura, vistas: Mapping[str, VistaSalva], dados: DadosDaFigura) -> DadosColhidos:
    """Tudo o que :func:`desenhar` vai pedir a ``dados`` para desenhar ``figura`` com ``vistas`` (as mesmas, que
    seguram as vistas vivas até o desenho)."""
    colhidos = DadosColhidos()
    for painel in figura.paineis:
        vista = vista_do_painel(painel, vistas)
        if vista is None:
            continue
        if painel.congelado is None:
            colhidos._janela[id(vista)] = dados.janela(vista)
        if vista.tipo == "tempo":
            for t in vista.tracos:
                if t.receita.visivel:
                    colhidos._tempo[(id(vista), t.receita)] = dados.tempo(vista, t.receita)
        elif vista.tipo == "espectro" and painel.congelado is None:
            colhidos._espectros[id(vista)] = list(dados.espectros(vista))
    return colhidos


# ------------------------------------------------------------------ as fontes e o estilo

_registradas = False


def registrar_as_fontes() -> None:
    """As fontes do aplicativo no Matplotlib (uma vez; a STIX e a DejaVu já vêm com ele)."""
    global _registradas
    if not _registradas:
        for arquivo in sorted(PASTA_DAS_FONTES.glob("*.ttf")):
            font_manager.fontManager.addfont(str(arquivo))
        _registradas = True


def parametros_do_estilo(estilo: Estilo) -> dict:
    """Os ``rcParams`` do estilo: o desenho e a rasterização rodam dentro deles (o Matplotlib lê parte deles na
    hora de desenhar, e não na de criar)."""
    familia, matematica = FAMILIAS_DO_MATPLOTLIB[estilo.familia]
    return {"font.family": familia, "mathtext.fontset": matematica, "font.size": estilo.texto_pt,
            "axes.labelsize": estilo.texto_pt, "axes.titlesize": estilo.rotulo_do_painel_pt,
            "legend.fontsize": estilo.texto_pt, "xtick.labelsize": estilo.marcas_pt,
            "ytick.labelsize": estilo.marcas_pt, "axes.linewidth": estilo.eixo_pt,
            "xtick.major.width": estilo.eixo_pt, "ytick.major.width": estilo.eixo_pt,
            "xtick.minor.width": estilo.eixo_pt * 0.7, "ytick.minor.width": estilo.eixo_pt * 0.7,
            "xtick.direction": "in", "ytick.direction": "in", "xtick.top": True, "ytick.right": True,
            "lines.linewidth": estilo.linha_pt, "path.simplify": False, "axes.unicode_minus": True,
            "axes.titlelocation": "left", "axes.titlepad": 3.0, "legend.frameon": False,
            "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white"}


@dataclass(eq=False)
class PaginaDesenhada:
    """A página do Matplotlib e o estilo dela (a rasterização roda dentro dele), e onde cada painel ficou: ``paineis``
    leva o id à caixa ``(x0, y0, x1, y1)`` em pixels da página, de cima para baixo (os eixos, os números, os rótulos
    e o título): a área Figuras escolhe o painel clicado por ela."""

    mpl: FiguraDoMatplotlib
    rc: dict = field(default_factory=dict)
    paineis: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)
    curvas: list = field(default_factory=list)          # as linhas dos dados (rasterizá-las, na exportação)

    def pixels(self) -> np.ndarray:
        """A página rasterizada (RGBA, ``altura × largura × 4``) no dpi dela: a prévia e o teste de fidelidade."""
        with rc_context(self.rc):
            self.mpl.canvas.draw()
            return np.asarray(self.mpl.canvas.buffer_rgba()).copy()


# ------------------------------------------------------------------ a redução

def m4(valores: np.ndarray, bordas: np.ndarray, *, piramide: Piramide | None = None,
       ler: Callable[[int], None] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """O M4 das colunas ``[bordas[c], bordas[c + 1])`` (posições em ``valores``): as posições (em ordem, sem repetir)
    da primeira, da mínima, da máxima e da última amostra de cada coluna, e os valores delas. Com ``piramide``, a
    mínima e a máxima vêm da envoltória dela, no meio da coluna (a prévia: sem ler as amostras do meio). ``ler(n)``
    sai depois de cada lote lido (o progresso; ele pode interromper levantando uma exceção)."""
    bordas = np.asarray(bordas, dtype=np.int64)
    bordas = bordas[np.concatenate([[True], bordas[1:] > bordas[:-1]])]
    if len(bordas) < 2:
        return np.zeros(0), np.zeros(0)
    primeiros, ultimos = bordas[:-1], bordas[1:] - 1
    if piramide is not None:
        mn, mx = _envoltoria_nas_colunas(piramide, valores, bordas)
        meio = (primeiros + ultimos) / 2.0
        posicoes = np.stack([primeiros, meio - 0.25, meio + 0.25, ultimos], axis=1).astype(np.float64)
        saida = np.stack([np.asarray(valores[primeiros], np.float64), mn, mx,
                          np.asarray(valores[ultimos], np.float64)], axis=1)
        largas = (ultimos - primeiros) >= 3           # as de 1 a 3 amostras saem com elas mesmas, sem o meio
        estreitas = np.flatnonzero(~largas)
        posicoes, saida = posicoes[largas].ravel(), saida[largas].ravel()
        if len(estreitas):
            soltas = np.concatenate([np.arange(primeiros[c], ultimos[c] + 1) for c in estreitas]).astype(np.float64)
            posicoes = np.concatenate([posicoes, soltas])
            saida = np.concatenate([saida, np.asarray(valores[soltas.astype(np.int64)], np.float64)])
            ordem = np.argsort(posicoes, kind="stable")
            posicoes, saida = posicoes[ordem], saida[ordem]
        return posicoes, saida
    i_min, i_max = _argextremos(valores, bordas, ler)
    indices = np.sort(np.stack([primeiros, i_min, i_max, ultimos], axis=1), axis=1)
    distintos = np.ones(indices.shape, dtype=bool)
    distintos[:, 1:] = indices[:, 1:] != indices[:, :-1]
    indices = indices[distintos]
    return indices.astype(np.float64), np.asarray(valores[indices], np.float64)


def _argextremos(valores: np.ndarray, bordas: np.ndarray,
                 ler: Callable[[int], None] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """A posição da (primeira) mínima e da (primeira) máxima de cada coluna, lendo as amostras em lotes de colunas
    inteiras. Os NaN não contam; uma coluna só de NaN fica com a primeira posição."""
    n_colunas = len(bordas) - 1
    i_min, i_max = bordas[:-1].copy(), bordas[:-1].copy()
    c = 0
    while c < n_colunas:
        fim = max(int(np.searchsorted(bordas, bordas[c] + LOTE_DO_M4, side="right")) - 1, c + 1)
        trecho = np.asarray(valores[bordas[c]:bordas[fim]])
        relativas = bordas[c:fim] - bordas[c]
        tamanhos = np.diff(bordas[c:fim + 1])
        coluna = np.repeat(np.arange(fim - c), tamanhos)
        for saida, reduzir in ((i_min, np.fmin), (i_max, np.fmax)):
            extremos_ = reduzir.reduceat(trecho, relativas)
            onde = np.flatnonzero(trecho == np.repeat(extremos_, tamanhos))
            colunas, primeira = np.unique(coluna[onde], return_index=True)
            saida[c + colunas] = bordas[c] + onde[primeira]
        if ler is not None:
            ler(len(trecho))
        c = fim
    return i_min, i_max


def _envoltoria_nas_colunas(piramide: Piramide, valores: np.ndarray, bordas: np.ndarray):
    """O mínimo e o máximo de cada coluna pela pirâmide (uma consulta de tantas colunas quantas as bordas pedem; a
    coluna mais estreita que um bloco fica com a do bloco vizinho)."""
    n = len(bordas) - 1
    consulta = consultar(piramide, valores, float(bordas[0]), float(bordas[-1]), n)
    if isinstance(consulta, Amostras):
        posicoes = np.searchsorted(bordas, consulta.indices, side="right") - 1
        mn_bloco = mx_bloco = np.asarray(consulta.valores, np.float64)
    else:
        centros = (consulta.bordas[:-1] + consulta.bordas[1:]) / 2
        posicoes = np.searchsorted(bordas, centros, side="right") - 1
        mn_bloco, mx_bloco = consulta.minimos.astype(np.float64), consulta.maximos.astype(np.float64)
    posicoes = np.clip(posicoes, 0, n - 1)
    mn, mx = np.full(n, np.inf), np.full(n, -np.inf)
    np.fmin.at(mn, posicoes, mn_bloco)
    np.fmax.at(mx, posicoes, mx_bloco)
    vazias = mn > mx
    if vazias.any() and not vazias.all():
        cheias = np.flatnonzero(~vazias)
        perto = cheias[np.clip(np.searchsorted(cheias, np.flatnonzero(vazias)), 0, len(cheias) - 1)]
        mn[vazias], mx[vazias] = mn[perto], mx[perto]
    return mn, mx


def extremos(piramide: Piramide, valores: np.ndarray, i0: int, i1: int) -> tuple[float, float] | None:
    """O mínimo e o máximo exatos de ``valores[i0:i1]``: os blocos inteiros pela pirâmide (do nível mais grosso ao
    mais fino) e as pontas que sobram (menos de um bloco do nível 0 de cada lado) lidas das amostras. Sem os NaN;
    ``None`` se não sobra valor."""
    mn, mx = math.inf, -math.inf
    pedacos = [(i0, i1)] if i1 > i0 else []
    for nivel in reversed(piramide.niveis):
        b, restantes = nivel.bloco, []
        for a, z in pedacos:
            ba, bz = -(-a // b), z // b
            if bz > ba:
                mins, maxs = nivel.minimos[ba:bz], nivel.maximos[ba:bz]
                if np.isfinite(mins).any():
                    mn, mx = min(mn, float(np.nanmin(mins))), max(mx, float(np.nanmax(maxs)))
                restantes += [(a, ba * b), (bz * b, z)]
            else:
                restantes.append((a, z))
        pedacos = [(a, z) for a, z in restantes if z > a]
    for a, z in pedacos:
        trecho = np.asarray(valores[a:z], np.float64)
        trecho = trecho[np.isfinite(trecho)]
        if len(trecho):
            mn, mx = min(mn, float(trecho.min())), max(mx, float(trecho.max()))
    return (mn, mx) if mn <= mx else None


# ------------------------------------------------------------------ os números

class _NumerosDoIdioma(ScalarFormatter):
    """O formatador do Matplotlib (as casas certas para as marcas), com o separador e o menos tipográfico."""

    def __init__(self, separador: str):
        super().__init__(useOffset=False, useMathText=False)
        self.set_powerlimits((-4, 5))
        self.separador = separador

    def __call__(self, x, pos=None):
        return super().__call__(x, pos).replace(".", self.separador)

    def fix_minus(self, s):
        return s.replace("-", "−")


def _numeros_do_log(separador: str) -> FuncFormatter:
    return FuncFormatter(lambda v, _p=None: f"{v:.10g}".replace("-", "−").replace(".", separador))


def _prefixo(unidade: str, maior: float) -> tuple[float, str]:
    """O fator e o prefixo do SI que deixam ``maior`` entre 1 e 1000 (nenhum numa unidade sem prefixo, como °C, ou
    num eixo sem unidade)."""
    if not unidade or not aceita_prefixos(unidade) or not (maior > 0 and math.isfinite(maior)):
        return 1.0, ""
    expoente = expoente_de_engenharia(maior)
    return 10.0 ** -expoente, PREFIXO_DO_EXPOENTE[expoente]


def _nome_da_grandeza(unidade: str, grandeza: str, idioma: str, textos: dict) -> str:
    nome = grandeza or (grandeza_da_unidade(unidade) if unidade else "")
    if not nome:
        return textos["valor"]
    return GRANDEZAS_EM_INGLES.get(nome.lower(), nome) if idioma == "en" else nome[0].upper() + nome[1:]


# ------------------------------------------------------------------ o plano de cada painel

@dataclass(eq=False)
class _Faixa:
    """Um eixo de tempo: os traços dele e os limites do y (na unidade física)."""

    series: list[SerieDoTempo]
    unidade: str
    limites_y: tuple[float, float]
    grandeza: str = ""


@dataclass(eq=False)
class _Plano:
    """O que um painel vai desenhar, antes de haver eixos: o tipo, a janela do x (s ou Hz) e o resto do tipo."""

    painel: Painel
    tipo: str                 # "tempo", "espectro", "vazio", "depois", "espectro_congelado" ou "sem_dados"
    janela: tuple[float, float] = (0.0, 1.0)
    faixas: list[_Faixa] = field(default_factory=list)
    espectros: list[SerieDoEspectro] = field(default_factory=list)
    log: bool = False
    limites_y: tuple[float, float] | None = None
    rotulo_y: str = ""

    @property
    def chave_x(self) -> tuple | None:
        """Os painéis da mesma coluna com a mesma chave dividem o x (``eixos_x_compartilhados``)."""
        if self.tipo == "tempo":
            return ("tempo", self.painel.coluna, self.painel.colunas)
        if self.tipo == "espectro":
            return ("espectro", self.log, self.painel.coluna, self.painel.colunas)
        return None

    @property
    def chave_y(self) -> tuple | None:
        """Os painéis da mesma linha com a mesma chave dividem o y (``eixos_y_compartilhados``): a mesma grandeza."""
        if self.tipo == "tempo" and len(self.faixas) == 1:
            return ("tempo", self.faixas[0].unidade, self.painel.linha, self.painel.linhas)
        if self.tipo == "espectro":
            return ("espectro", self.rotulo_y, self.painel.linha, self.painel.linhas)
        return None


def vista_do_painel(painel: Painel, vistas: Mapping[str, VistaSalva]) -> VistaSalva | None:
    """O que o painel desenha: a cópia congelada, ou a vista ligada (``None``: o painel vazio, ou a vista sumiu)."""
    return painel.congelado or (vistas.get(painel.vista) if painel.vista else None)


def _janela_da_vista(painel: Painel, vista: VistaSalva, dados: DadosDaFigura) -> tuple[float, float] | None:
    """Os limites do x: os do painel ou, num painel ligado, os que a vista mostra agora (o congelado sem limites
    próprios mostra tudo)."""
    return painel.limites_x or (dados.janela(vista) if painel.congelado is None else None)


def _plano(painel: Painel, vistas: Mapping[str, VistaSalva], dados: DadosDaFigura) -> _Plano:
    vista = vista_do_painel(painel, vistas)
    if vista is None:
        return _Plano(painel, "vazio")
    if vista.tipo == "tempo":
        return _plano_do_tempo(painel, vista, dados)
    if vista.tipo == "espectro":
        return _plano_do_espectro(painel, vista, dados)
    return _Plano(painel, "depois")


def _plano_do_tempo(painel: Painel, vista: VistaSalva, dados: DadosDaFigura) -> _Plano:
    por_faixa: dict[int, list[SerieDoTempo]] = {}
    sobrepor = bool(vista.opcoes.get("sobrepor", False))
    for t in vista.tracos:
        if t.receita.visivel and (s := dados.tempo(vista, t.receita)) is not None and s.piramide.n_amostras:
            por_faixa.setdefault(0 if sobrepor else t.receita.faixa, []).append(s)
    if not por_faixa:
        return _Plano(painel, "sem_dados")
    todas = [s for series in por_faixa.values() for s in series]
    janela = _janela_da_vista(painel, vista, dados) or (
        min(s.t0 + s.inicio / s.taxa_hz for s in todas),
        max(s.t0 + (s.inicio + s.piramide.n_amostras - 1) / s.taxa_hz for s in todas))
    faixas = []
    for numero in sorted(por_faixa):
        series = por_faixa[numero]
        unidades, grandezas = {s.unidade for s in series}, {s.grandeza for s in series}
        unidade = next(iter(unidades)) if len(unidades) == 1 else ""
        grandeza = next(iter(grandezas)) if len(unidades) == 1 and len(grandezas) == 1 else ""
        faixas.append(_Faixa(series, unidade, _limites_do_tempo(series, janela), grandeza))
    if painel.limites_y and len(faixas) == 1:
        faixas[0].limites_y = painel.limites_y
    return _Plano(painel, "tempo", janela, faixas=faixas)


def _limites_do_tempo(series: list[SerieDoTempo], janela: tuple[float, float]) -> tuple[float, float]:
    mn, mx = math.inf, -math.inf
    for s in series:
        a = math.ceil((janela[0] - s.t0) * s.taxa_hz) - s.inicio           # só as de dentro da janela
        z = math.floor((janela[1] - s.t0) * s.taxa_hz) - s.inicio + 1
        e = extremos(s.piramide, s.amostras, max(0, a), min(s.piramide.n_amostras, z))
        if e is not None:
            v = (e[0] * s.escala + s.deslocamento, e[1] * s.escala + s.deslocamento)
            mn, mx = min(mn, *v), max(mx, *v)
    return _com_folga(mn, mx)


def _com_folga(mn: float, mx: float) -> tuple[float, float]:
    if not mn <= mx:
        return 0.0, 1.0
    if mn == mx:
        d = abs(mn) * 0.1 or 1.0
        return mn - d, mx + d
    d = FOLGA_DO_Y * (mx - mn)
    return mn - d, mx + d


def _plano_do_espectro(painel: Painel, vista: VistaSalva, dados: DadosDaFigura) -> _Plano:
    if painel.congelado is not None:
        return _Plano(painel, "espectro_congelado")
    series = list(dados.espectros(vista))
    if not series:
        return _Plano(painel, "sem_dados")
    log = series[0].frequencia_log
    f_min = min(s.desenho.f0 + (s.desenho.df if log else 0.0) for s in series)
    f_max = max(s.desenho.f0 + s.desenho.df * (len(s.desenho.niveis) - 1) for s in series)
    janela = _janela_da_vista(painel, vista, dados) or (f_min, f_max)
    limites_y = painel.limites_y
    if limites_y is None:
        mn, mx = math.inf, -math.inf
        for s in series:
            d = s.desenho
            a = max(0, math.ceil((janela[0] - d.f0) / d.df))
            z = min(len(d.niveis), math.floor((janela[1] - d.f0) / d.df) + 1)
            trecho = d.niveis[a:z][np.isfinite(d.niveis[a:z])]
            if len(trecho):
                mn, mx = min(mn, float(trecho.min())), max(mx, float(trecho.max()))
        limites_y = _com_folga(mn, mx)
    return _Plano(painel, "espectro", janela, espectros=series, log=log, limites_y=limites_y,
                  rotulo_y=series[0].rotulo_y)


def pontos(figura: Figura, vistas: Mapping[str, VistaSalva], dados: DadosDaFigura) -> int:
    """Quantos pontos as curvas da figura têm na janela de cada painel: o que "todos os pontos" desenha (e o que deixa
    o arquivo vetorial grande)."""
    planos = [_plano(p, vistas, dados) for p in figura.em_ordem()]
    _compartilhar(planos, figura)
    total = 0
    for plano in planos:
        for faixa in plano.faixas:
            for s in faixa.series:
                a = math.ceil((plano.janela[0] - s.t0) * s.taxa_hz) - s.inicio
                z = math.floor((plano.janela[1] - s.t0) * s.taxa_hz) - s.inicio + 1
                total += max(0, min(s.piramide.n_amostras, z) - max(0, a))
        for s in plano.espectros:
            d = s.desenho
            a = max(0, math.floor((plano.janela[0] - d.f0) / d.df))
            z = min(len(d.niveis), math.ceil((plano.janela[1] - d.f0) / d.df) + 1)
            total += max(0, z - a)
    return total


def _compartilhar(planos: list[_Plano], figura: Figura) -> None:
    """Os painéis que dividem um eixo passam a ter a mesma janela (a união) ou os mesmos limites do y (a união)."""
    if figura.eixos_x_compartilhados:
        for grupo in _grupos(planos, lambda p: p.chave_x):
            janela = (min(p.janela[0] for p in grupo), max(p.janela[1] for p in grupo))
            for p in grupo:
                p.janela = janela
    if figura.eixos_y_compartilhados:
        for grupo in _grupos(planos, lambda p: p.chave_y):
            limites = [p.faixas[0].limites_y if p.tipo == "tempo" else p.limites_y for p in grupo]
            uniao = (min(v[0] for v in limites), max(v[1] for v in limites))
            for p in grupo:
                if p.tipo == "tempo":
                    p.faixas[0].limites_y = uniao
                else:
                    p.limites_y = uniao


def _grupos(planos: list[_Plano], chave) -> list[list[_Plano]]:
    grupos: dict[tuple, list[_Plano]] = {}
    for p in planos:
        if (k := chave(p)) is not None:
            grupos.setdefault(k, []).append(p)
    return [g for g in grupos.values() if len(g) > 1]


# ------------------------------------------------------------------ o desenho

@dataclass(eq=False)
class _Curva:
    """Uma linha que a segunda passada reduz: a posição ``i`` de ``valores`` está em ``x0 + i · passo`` (s ou Hz) e
    vale ``valores[i] · escala + deslocamento``; os fatores levam à unidade dos eixos (ms, kHz, kV)."""

    linha: object
    eixo: object
    valores: np.ndarray
    piramide: Piramide | None
    x0: float
    passo: float
    fator_x: float = 1.0
    fator_y: float = 1.0
    escala: float = 1.0
    deslocamento: float = 0.0
    desenho_log: Desenho | None = None       # um espectro na frequência logarítmica (``envoltoria_log``)


def desenhar(figura: Figura, vistas: Mapping[str, VistaSalva], dados: DadosDaFigura, *, dpi: float = 300.0,
             exato: bool = True, todos_os_pontos: bool = False, suavizar: bool = True,
             progresso: Callable[[float], None] | None = None, cancelado: Callable[[], bool] | None = None,
             pixels_inteiros: bool = False) -> PaginaDesenhada:
    """A figura no tamanho da página (``figura.largura_mm`` × ``figura.altura_mm``) e em ``dpi`` (o da exportação,
    ou o da tela na prévia). ``suavizar=False`` desliga o antisserrilhado das curvas (o teste de fidelidade).

    O leiaute é achado em no máximo :data:`DPI_DO_LEIAUTE` (ele é em polegadas: não depende do dpi), e só a redução
    usa o ``dpi``: um pôster A0 a 1 200 dpi não aloca a página inteira em pixels para isso. ``progresso(fração)`` sai
    a cada lote de amostras lido pela redução exata; ``cancelado()`` verdadeiro a interrompe (``Cancelado``).
    ``pixels_inteiros``: a página com um número inteiro de pixels em ``dpi``, o mais perto do tamanho do modelo (as
    imagens: o Matplotlib truncaria 519,7 px em 519)."""
    registrar_as_fontes()
    rc = parametros_do_estilo(figura.estilo)
    textos = TEXTOS[figura.idioma]
    planos = [_plano(p, vistas, dados) for p in figura.em_ordem()]
    _compartilhar(planos, figura)
    with rc_context(rc):
        dpi_do_leiaute = min(dpi, DPI_DO_LEIAUTE)
        tamanho = (figura.largura_mm / 25.4, figura.altura_mm / 25.4)
        if pixels_inteiros:
            tamanho = tuple((round(polegadas * dpi) + 1e-6) / dpi for polegadas in tamanho)
        mpl = FiguraDoMatplotlib(figsize=tamanho, dpi=dpi_do_leiaute, layout="constrained")
        canvas = FigureCanvasAgg(mpl)
        mpl.get_layout_engine().set(w_pad=2 / 72, h_pad=2 / 72, wspace=0.02, hspace=0.02)
        grade = mpl.add_gridspec(figura.linhas, figura.colunas)
        rotulos = figura.rotulos()
        primeiro_x: dict[tuple, object] = {}
        primeiro_y: dict[tuple, object] = {}
        eixos_x: dict[tuple, list] = {}
        eixos_y: dict[tuple, list] = {}
        curvas: list[_Curva] = []
        eixos_do_painel: dict[str, list] = {}
        for plano in planos:
            p = plano.painel
            celula = grade[p.linha:p.linha + p.linhas, p.coluna:p.coluna + p.colunas]
            kx = plano.chave_x if figura.eixos_x_compartilhados else None
            ky = plano.chave_y if figura.eixos_y_compartilhados else None
            if plano.tipo == "tempo":
                eixos = _eixos_das_faixas(mpl, celula, len(plano.faixas), primeiro_x.get(kx), primeiro_y.get(ky))
                curvas += _desenhar_o_tempo(eixos, plano, figura, textos, suavizar)
            else:
                eixos = [mpl.add_subplot(celula, sharex=primeiro_x.get(kx), sharey=primeiro_y.get(ky))]
                if plano.tipo == "espectro":
                    curvas += _desenhar_o_espectro(eixos[0], plano, figura, textos, suavizar)
                else:
                    _aviso_no_eixo(eixos[0], textos[plano.tipo])
            if kx is not None:
                primeiro_x.setdefault(kx, eixos[-1])
                eixos_x.setdefault(kx, []).append((p.linha + p.linhas, eixos[-1]))
            if ky is not None:
                primeiro_y.setdefault(ky, eixos[0])
                eixos_y.setdefault(ky, []).append((p.coluna, eixos[0]))
            if rotulos[p.id]:
                eixos[0].set_title(rotulos[p.id])
            eixos_do_painel[p.id] = eixos
        _so_os_de_fora(eixos_x, eixos_y)
        # A segunda passada: com o leiaute feito, cada curva reduzida nas colunas dos pixels do eixo dela, no dpi
        # de saída.
        mpl.draw_without_rendering()
        renderizador = canvas.get_renderer()
        escala = dpi / dpi_do_leiaute
        altura = mpl.bbox.height
        caixas = {}
        for id_, eixos in eixos_do_painel.items():
            uniao = Bbox.union([e.get_tightbbox(renderizador) for e in eixos])
            caixas[id_] = (uniao.x0 * escala, (altura - uniao.y1) * escala, uniao.x1 * escala,
                           (altura - uniao.y0) * escala)
        mpl.set_dpi(dpi)
        leitura = _Leitura(curvas, exato=exato, todos=todos_os_pontos, progresso=progresso, cancelado=cancelado)
        for curva in curvas:
            _reduzir(curva, exato=exato, todos=todos_os_pontos, ler=leitura.leu)
        if progresso is not None:
            progresso(1.0)
    return PaginaDesenhada(mpl, rc, caixas, [c.linha for c in curvas])


def _eixos_das_faixas(mpl, celula, n: int, junto_x, junto_y) -> list:
    """Um eixo por faixa na célula do painel, de cima para baixo, com o tempo compartilhado."""
    if n == 1:
        return [mpl.add_subplot(celula, sharex=junto_x, sharey=junto_y)]
    sub = celula.subgridspec(n, 1, hspace=0.0)
    eixos: list = []
    for i in range(n):
        eixos.append(mpl.add_subplot(sub[i, 0], sharex=eixos[0] if eixos else junto_x))
    for eixo in eixos[:-1]:
        eixo.tick_params(labelbottom=False)
    return eixos


def _so_os_de_fora(eixos_x: dict, eixos_y: dict) -> None:
    """Nos eixos compartilhados, os números e o rótulo só no de baixo (o x) e no da esquerda (o y)."""
    for grupo in eixos_x.values():
        ultimo = max(b for b, _e in grupo)
        for baixo, eixo in grupo:
            if baixo < ultimo:
                eixo.tick_params(labelbottom=False)
                eixo.set_xlabel("")
    for grupo in eixos_y.values():
        primeira = min(c for c, _e in grupo)
        for coluna, eixo in grupo:
            if coluna > primeira:
                eixo.tick_params(labelleft=False)
                eixo.set_ylabel("")


def _aviso_no_eixo(eixo, texto: str) -> None:
    eixo.set_xticks([])
    eixo.set_yticks([])
    eixo.text(0.5, 0.5, texto, transform=eixo.transAxes, ha="center", va="center", color="0.45")


def _numeros(eixo, separador: str) -> None:
    eixo.xaxis.set_major_formatter(_NumerosDoIdioma(separador))
    eixo.yaxis.set_major_formatter(_NumerosDoIdioma(separador))


def _desenhar_o_tempo(eixos: list, plano: _Plano, figura: Figura, textos: dict, suavizar: bool) -> list[_Curva]:
    janela = plano.janela
    fator_x = 1000.0 if janela[1] - janela[0] < LIMIAR_DO_TEMPO_EM_MS else 1.0
    curvas = []
    for eixo, faixa in zip(eixos, plano.faixas, strict=True):
        y0, y1 = faixa.limites_y
        fator_y, prefixo = _prefixo(faixa.unidade, max(abs(y0), abs(y1)))
        for s in faixa.series:
            linha, = eixo.plot([], [], color=s.cor, linestyle="--" if s.tracejado else "-", label=s.nome,
                               antialiased=suavizar)
            curvas.append(_Curva(linha, eixo, s.amostras, s.piramide, s.t0 + s.inicio / s.taxa_hz, 1.0 / s.taxa_hz,
                                 fator_x, fator_y, s.escala, s.deslocamento))
        eixo.set_ylim(y0 * fator_y, y1 * fator_y)
        nome = _nome_da_grandeza(faixa.unidade, faixa.grandeza, figura.idioma, textos)
        eixo.set_ylabel(f"{nome} ({prefixo}{faixa.unidade})" if faixa.unidade else nome)
        _numeros(eixo, figura.separador_decimal)
        if len(faixa.series) > 1:
            eixo.legend(loc="best")
    eixos[0].set_xlim(janela[0] * fator_x, janela[1] * fator_x)
    eixos[-1].set_xlabel(f"{textos['tempo']} ({'ms' if fator_x == 1000.0 else 's'})")
    return curvas


def _desenhar_o_espectro(eixo, plano: _Plano, figura: Figura, textos: dict, suavizar: bool) -> list[_Curva]:
    fator_x, prefixo_x = _prefixo("Hz", max(abs(plano.janela[0]), abs(plano.janela[1])))
    curvas = []
    for s in plano.espectros:
        linha, = eixo.plot([], [], color=s.cor, linestyle="--" if s.tracejado else "-", label=s.nome,
                           antialiased=suavizar)
        d = s.desenho
        curvas.append(_Curva(linha, eixo, d.niveis, d.piramide, d.f0, d.df, fator_x,
                             desenho_log=d if plano.log else None))
    if plano.log:
        eixo.set_xscale("log")
    eixo.set_xlim(plano.janela[0] * fator_x, plano.janela[1] * fator_x)
    eixo.set_ylim(*plano.limites_y)
    _numeros(eixo, figura.separador_decimal)
    if plano.log:
        eixo.xaxis.set_major_formatter(_numeros_do_log(figura.separador_decimal))
        eixo.xaxis.set_minor_formatter(NullFormatter())
    eixo.set_xlabel(f"{textos['frequencia']} ({prefixo_x}Hz)")
    eixo.set_ylabel(f"{textos['nivel']} ({plano.rotulo_y})" if plano.rotulo_y else textos["nivel"])
    if len(plano.espectros) > 1:
        eixo.legend(loc="best")
    return curvas


def _colunas_e_janela(curva: _Curva) -> tuple[int, int, int, int]:
    """As colunas do eixo na tela (``k0``, ``k1``: os meios pixels) e as posições da janela (``i0``, ``i1``)."""
    eixo = curva.eixo
    xa, xb = sorted(v / curva.fator_x for v in eixo.get_xlim())
    caixa = eixo.get_window_extent()
    k0, k1 = math.floor(caixa.x0 * COLUNAS_POR_PIXEL), math.ceil(caixa.x1 * COLUNAS_POR_PIXEL)
    n = len(curva.valores)
    i0 = max(0, math.floor((xa - curva.x0) / curva.passo) - 1)
    i1 = min(n, math.ceil((xb - curva.x0) / curva.passo) + 2)
    return k0, k1, i0, i1


class _Leitura:
    """A conta do progresso da redução: as amostras que a redução exata vai ler, e as já lidas."""

    def __init__(self, curvas: list[_Curva], *, exato: bool, todos: bool, progresso, cancelado):
        self.progresso, self.cancelado, self.lidas = progresso, cancelado, 0
        self.total = 0
        if exato and not todos:
            for c in curvas:
                if c.desenho_log is None:
                    k0, k1, i0, i1 = _colunas_e_janela(c)
                    if i1 - i0 > 4 * (k1 - k0):
                        self.total += i1 - i0

    def leu(self, n: int) -> None:
        if self.cancelado is not None and self.cancelado():
            raise Cancelado()
        self.lidas += n
        if self.progresso is not None and self.total:
            self.progresso(min(1.0, self.lidas / self.total))


def _reduzir(curva: _Curva, *, exato: bool, todos: bool, ler: Callable[[int], None] | None = None) -> None:
    """Os dados da linha: os pontos que pintam a janela do eixo (o M4 nas colunas dos pixels, ou todos)."""
    eixo = curva.eixo
    xa, xb = sorted(v / curva.fator_x for v in eixo.get_xlim())
    k0, k1, i0, i1 = _colunas_e_janela(curva)
    if curva.desenho_log is not None:
        x, y = envoltoria_log(curva.desenho_log, xa, xb, max(2, k1 - k0))
        curva.linha.set_data(np.asarray(x) * curva.fator_x, y)
        return
    if i1 <= i0:
        curva.linha.set_data([], [])
        return
    if todos or i1 - i0 <= 4 * (k1 - k0):
        posicoes = np.arange(i0, i1, dtype=np.float64)
        valores = np.asarray(curva.valores[i0:i1], np.float64)
    else:
        # As bordas das colunas: as dos meios pixels do eixo na tela, levadas ao x dos dados e daí às posições
        # (arredondadas para cima: a amostra na borda fica na coluna da direita, como a rasterização a põe).
        tela = np.column_stack([np.arange(k0, k1 + 1) / COLUNAS_POR_PIXEL, np.zeros(k1 - k0 + 1)])
        x_das_bordas = eixo.transData.inverted().transform(tela)[:, 0] / curva.fator_x
        bordas = np.ceil((x_das_bordas - curva.x0) / curva.passo)
        bordas = np.clip(np.concatenate([[i0], bordas, [i1]]), i0, i1).astype(np.int64)
        posicoes, valores = m4(curva.valores, np.maximum.accumulate(bordas),
                               piramide=None if exato else curva.piramide, ler=ler)
    x = (curva.x0 + posicoes * curva.passo) * curva.fator_x
    curva.linha.set_data(x, (valores * curva.escala + curva.deslocamento) * curva.fator_y)
