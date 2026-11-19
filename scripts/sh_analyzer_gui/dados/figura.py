"""A figura (a F5.1; docs/gui-plan.md, 10.1): os modelos de página, a figura, os painéis e o estilo. Sem Qt e sem o
desenho (que é a F5.2, com o Matplotlib).

* **Os modelos de página** dão a largura (a da coluna da revista, a do texto do relatório, a do slide), a altura
  inicial e o estilo inicial; a altura é da figura e muda até o máximo do modelo.
* **A figura** é uma grade de painéis (até 6 × 6) numa página de um modelo, com o idioma dos números (o separador
  decimal: "1,5" em pt-BR, "1.5" em en), o estilo e os eixos compartilhados (o x de cada coluna, o y de cada linha).
* **O painel** ocupa uma ou mais células da grade, sem se sobrepor a outro. Ele é **ligado** a uma vista da Análise
  (o id: mudou a vista, a figura acompanha) ou **congelado** (a cópia da vista no momento: os traços com as receitas e
  as opções; os dados vêm das mesmas capturas, que não mudam). O rótulo é automático, (a), (b)… na ordem de leitura,
  a menos que o painel diga outro ("" tira o rótulo). Os limites vazios são os da vista.
* **O estilo** (:class:`Estilo`, a figura inteira): a família (as do aplicativo e as do Matplotlib: a STIX é a do
  tipo Times que as revistas pedem), os tamanhos em pt (os rótulos, os números, o rótulo do painel, a legenda), as
  espessuras em pt, as marcas para dentro ou para fora, a moldura inteira ou só os eixos e a grade. **Os modelos de
  estilo** (:class:`ModeloDeEstilo`, FG-02) são estilos com nome que o usuário salva da figura e aplica em outra; eles
  ficam nas preferências (valem em qualquer projeto), por :func:`estilo_para_dict` e :func:`estilo_de_dict`.
* **O que muda em cada painel** (F5.7, FG-04): o estilo de cada traço (:class:`EstiloDoTraco`, pelo id do traço da
  vista: a cor, a espessura, o tracejado, o marcador e o nome na legenda; o que fica ``None`` vem da vista e do
  estilo), o lugar da legenda (:data:`LEGENDAS`), os limites, o nome de cada eixo (o da grandeza: a unidade vem
  sempre atrás, com o prefixo) e o prefixo do SI de cada eixo (``None``: o automático). O y (os limites, o nome, o
  prefixo) vale no painel de um eixo y só (uma faixa); com várias faixas, cada uma tem o dela, automático.
* **O inset** (:class:`Inset`, F5.8, FG-03): a ampliação de um trecho do painel num canto dele, com as linhas de
  ligação. As anotações (texto, seta, região, cota) são da vista (``dados/anotacoes.py``), e a figura as desenha.

**No arquivo de projeto** (``dados/projeto.py``, a versão 5) a figura vai por :func:`para_dict` e volta por
:func:`de_dict`; a vista congelada é escrita e lida pelo próprio ``projeto.py`` (os dois parâmetros que ele passa),
que conhece o formato das vistas. O que não vale é recusado com a razão (:class:`FiguraInvalida`).
"""

from __future__ import annotations

import math
import string
from collections.abc import Callable
from dataclasses import dataclass, field, fields, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .projeto import VistaSalva

IDIOMAS = {"pt-BR": ",", "en": "."}
"""O idioma dos números da figura e o separador decimal dele."""
FAMILIAS = ("STIX", "Inter", "IBM Plex Sans", "DejaVu Sans")
"""As famílias de letra da figura: a STIX (do tipo Times) e a DejaVu vêm com o Matplotlib; a Inter e a IBM Plex
Sans, com o aplicativo."""
GRADE_MAXIMA = 6
ALTURA_MINIMA_MM = 20.0
TAMANHO_PT = (4.0, 72.0)
ESPESSURA_PT = (0.1, 10.0)
TRACEJADOS = {"-": "contínuo", "--": "tracejado", ":": "pontilhado", "-.": "traço e ponto"}
"""Os tracejados de um traço (o código do Matplotlib e o nome)."""
MARCADORES = {"": "nenhum", "o": "círculo", "s": "quadrado", "^": "triângulo", "v": "triângulo para baixo",
              "D": "losango", "x": "xis", "+": "cruz"}
"""Os marcadores de um traço: espaçados na linha (uns dez por eixo), para distinguir os traços sem a cor."""
LEGENDAS = {"melhor": "automática", "sup_dir": "em cima, à direita", "sup_esq": "em cima, à esquerda",
            "inf_dir": "embaixo, à direita", "inf_esq": "embaixo, à esquerda", "fora_dir": "fora, à direita",
            "fora_acima": "fora, em cima", "nenhuma": "sem legenda"}
"""Onde a legenda de um painel fica. A automática aparece com mais de um traço no eixo, onde atrapalha menos; um
canto escolhido a mostra mesmo com um traço só."""
PREFIXOS = (-12, -9, -6, -3, 0, 3, 6, 9)
"""Os expoentes dos prefixos do SI que um eixo pode fixar (p a G)."""
CANTOS = {"sup_dir": "em cima, à direita", "sup_esq": "em cima, à esquerda", "inf_dir": "embaixo, à direita",
          "inf_esq": "embaixo, à esquerda"}
"""Os cantos do painel em que o inset fica."""
TAMANHO_DO_INSET = (0.2, 0.7)
"""O lado do inset, em fração do eixo."""


class FiguraInvalida(ValueError):
    """Uma figura, um painel ou um estilo que não vale (a mensagem diz por quê)."""


def _no_intervalo(valor, intervalo: tuple[float, float], o_que: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not intervalo[0] <= valor <= intervalo[1]:
        raise FiguraInvalida(f"{o_que} fora de {intervalo[0]:g} a {intervalo[1]:g}: {valor!r}")
    return float(valor)


def _booleano(valor, o_que: str) -> bool:
    if not isinstance(valor, bool):
        raise FiguraInvalida(f"{o_que} tem de ser verdadeiro ou falso: {valor!r}")
    return valor


def _cor(valor, o_que: str) -> str:
    """Uma cor ``#rrggbb`` (em minúsculas)."""
    if not (isinstance(valor, str) and len(valor) == 7 and valor[0] == "#"
            and all(c in string.hexdigits for c in valor[1:])):
        raise FiguraInvalida(f"{o_que}: cor inválida {valor!r} (use #rrggbb)")
    return valor.lower()


@dataclass(frozen=True)
class Estilo:
    """As letras e as linhas da figura (em pt)."""

    familia: str = "STIX"
    texto_pt: float = 8.0               # os rótulos dos eixos e os textos das anotações
    marcas_pt: float = 7.0              # os números das marcas
    rotulo_do_painel_pt: float = 9.0    # o (a), (b)…
    linha_pt: float = 0.8               # os traços
    eixo_pt: float = 0.5                # a moldura e as marcas
    legenda_pt: float = 8.0             # os nomes na legenda
    marcas_para_dentro: bool = True
    moldura: bool = True                # os quatro lados (as marcas em cima e à direita também); ou só os eixos
    grade: bool = False                 # as linhas da grade nas marcas principais

    def __post_init__(self):
        if self.familia not in FAMILIAS:
            raise FiguraInvalida(f"família de letra desconhecida: {self.familia!r} (use {', '.join(FAMILIAS)})")
        for nome in ("texto_pt", "marcas_pt", "rotulo_do_painel_pt", "legenda_pt"):
            object.__setattr__(self, nome, _no_intervalo(getattr(self, nome), TAMANHO_PT, f"o tamanho {nome}"))
        for nome in ("linha_pt", "eixo_pt"):
            object.__setattr__(self, nome, _no_intervalo(getattr(self, nome), ESPESSURA_PT, f"a espessura {nome}"))
        for nome in ("marcas_para_dentro", "moldura", "grade"):
            _booleano(getattr(self, nome), f"o estilo: {nome}")


@dataclass(frozen=True)
class ModeloDeEstilo:
    """Um estilo com nome, salvo pelo usuário (FG-02): aplicado, ele troca o estilo da figura inteira."""

    nome: str
    estilo: Estilo

    def __post_init__(self):
        if not isinstance(self.nome, str) or not self.nome.strip():
            raise FiguraInvalida("um modelo de estilo sem nome")
        object.__setattr__(self, "nome", self.nome.strip())


@dataclass(frozen=True)
class EstiloDoTraco:
    """O estilo de um traço num painel (``None``: o da vista; a espessura, a do estilo da figura)."""

    cor: str | None = None              # #rrggbb
    espessura_pt: float | None = None
    tracejado: str | None = None        # TRACEJADOS
    marcador: str = ""                  # MARCADORES
    nome: str | None = None             # o nome na legenda

    def __post_init__(self):
        if self.cor is not None:
            object.__setattr__(self, "cor", _cor(self.cor, "o traço"))
        if self.espessura_pt is not None:
            object.__setattr__(self, "espessura_pt", _no_intervalo(self.espessura_pt, ESPESSURA_PT,
                                                                   "a espessura do traço"))
        if self.tracejado is not None and self.tracejado not in TRACEJADOS:
            raise FiguraInvalida(f"tracejado desconhecido: {self.tracejado!r} (use {', '.join(TRACEJADOS)})")
        if self.marcador not in MARCADORES:
            raise FiguraInvalida(f"marcador desconhecido: {self.marcador!r} (use {', '.join(filter(None, MARCADORES))})")
        if self.nome is not None and not isinstance(self.nome, str):
            raise FiguraInvalida(f"o nome do traço é inválido: {self.nome!r}")

    @property
    def vazio(self) -> bool:
        return self == EstiloDoTraco()


@dataclass(frozen=True)
class Inset:
    """A ampliação de um trecho do painel (F5.8): ``limites_x`` (s ou Hz) e ``limites_y`` (``None``: os extremos do
    trecho, com folga), num ``canto`` do eixo, com ``tamanho`` de lado (a fração do eixo); ``faixa``: o eixo da vista
    de tempo com várias faixas (a posição, de cima para baixo); ``ligacoes``: o retângulo no trecho e as linhas que o
    ligam ao inset."""

    limites_x: tuple[float, float]
    limites_y: tuple[float, float] | None = None
    canto: str = "sup_dir"
    tamanho: float = 0.4
    faixa: int = 0
    ligacoes: bool = True

    def __post_init__(self):
        object.__setattr__(self, "limites_x", _limites(self.limites_x, "o inset: limites_x"))
        if self.limites_y is not None:
            object.__setattr__(self, "limites_y", _limites(self.limites_y, "o inset: limites_y"))
        if self.canto not in CANTOS:
            raise FiguraInvalida(f"o inset: canto desconhecido {self.canto!r} (use {', '.join(CANTOS)})")
        object.__setattr__(self, "tamanho", _no_intervalo(self.tamanho, TAMANHO_DO_INSET, "o tamanho do inset"))
        if isinstance(self.faixa, bool) or not isinstance(self.faixa, int) or self.faixa < 0:
            raise FiguraInvalida(f"o inset: faixa inválida {self.faixa!r}")
        _booleano(self.ligacoes, "o inset: ligacoes")

    @property
    def posicao(self) -> tuple[float, float, float, float]:
        """``(x0, y0, largura, altura)`` em fração do eixo, com uma margem de 4 %."""
        lado, margem = self.tamanho, 0.04
        x0 = 1.0 - margem - lado if self.canto.endswith("dir") else margem
        y0 = 1.0 - margem - lado if self.canto.startswith("sup") else margem
        return (x0, y0, lado, lado)


def _limites(limites, o_que: str) -> tuple[float, float]:
    if (not isinstance(limites, (tuple, list)) or len(limites) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in limites)
            or not limites[0] < limites[1]):
        raise FiguraInvalida(f"{o_que} inválidos: {limites!r} (o primeiro menor que o segundo)")
    return (float(limites[0]), float(limites[1]))


@dataclass(frozen=True)
class ModeloDePagina:
    """Uma página: a largura da figura nela, a altura inicial e a máxima, e o estilo inicial."""

    id: str
    nome: str
    largura_mm: float
    altura_mm: float
    altura_maxima_mm: float
    estilo: Estilo = field(default_factory=Estilo)


_SERIFA = Estilo()
_RELATORIO = Estilo(texto_pt=10.0, marcas_pt=9.0, rotulo_do_painel_pt=11.0, linha_pt=1.0, eixo_pt=0.6,
                    legenda_pt=10.0)
_SLIDE = Estilo("Inter", texto_pt=16.0, marcas_pt=14.0, rotulo_do_painel_pt=18.0, linha_pt=2.0, eixo_pt=1.0,
                legenda_pt=16.0)
_POSTER = Estilo("Inter", texto_pt=28.0, marcas_pt=24.0, rotulo_do_painel_pt=32.0, linha_pt=3.0, eixo_pt=1.5,
                 legenda_pt=28.0)

MODELOS: tuple[ModeloDePagina, ...] = (
    ModeloDePagina("ieee_1", "IEEE, 1 coluna", 88.0, 66.0, 230.0, _SERIFA),
    ModeloDePagina("ieee_2", "IEEE, 2 colunas", 181.0, 90.0, 230.0, _SERIFA),
    ModeloDePagina("elsevier_1", "Elsevier, 1 coluna", 90.0, 68.0, 240.0, _SERIFA),
    ModeloDePagina("elsevier_15", "Elsevier, 1,5 coluna", 140.0, 90.0, 240.0, _SERIFA),
    ModeloDePagina("elsevier_2", "Elsevier, 2 colunas", 190.0, 100.0, 240.0, _SERIFA),
    ModeloDePagina("fapesp", "Relatório FAPESP (A4, margens da ABNT)", 160.0, 100.0, 247.0, _RELATORIO),
    ModeloDePagina("slide", "Slide 16:9", 254.0, 142.875, 142.875, _SLIDE),
    ModeloDePagina("poster", "Pôster A0", 841.0, 500.0, 1189.0, _POSTER),
)
"""Os modelos de página (docs/gui-plan.md, 10.1). O relatório usa a largura do texto (A4 menos 3 + 2 cm de margem)."""


def modelo(id: str) -> ModeloDePagina:
    for m in MODELOS:
        if m.id == id:
            return m
    raise FiguraInvalida(f"modelo de página desconhecido: {id!r} (use {', '.join(m.id for m in MODELOS)})")


@dataclass(frozen=True)
class Painel:
    """Um painel da grade: a célula de cima e da esquerda (``linha``, ``coluna``, a partir de 0) e quantas ocupa;
    ``vista``, o id da vista ligada; ``congelado``, a cópia da vista no momento (então ``vista`` só diz de onde
    veio); ``rotulo``, ``None`` para o automático; ``limites_x`` e ``limites_y``, ``None`` para os da vista;
    ``tracos``, o estilo de cada traço que muda (pelo id do traço); ``legenda`` (:data:`LEGENDAS`); ``nome_x`` e
    ``nome_y``, o nome da grandeza de cada eixo (``None``: o automático; ``""``: sem rótulo); ``prefixo_x`` e
    ``prefixo_y``, o expoente do prefixo do SI (``None``: o automático); ``inset``, a ampliação (F5.8)."""

    id: str
    linha: int = 0
    coluna: int = 0
    linhas: int = 1
    colunas: int = 1
    vista: str | None = None
    congelado: VistaSalva | None = None
    rotulo: str | None = None
    limites_x: tuple[float, float] | None = None
    limites_y: tuple[float, float] | None = None
    tracos: tuple[tuple[str, EstiloDoTraco], ...] = ()
    legenda: str = "melhor"
    nome_x: str | None = None
    nome_y: str | None = None
    prefixo_x: int | None = None
    prefixo_y: int | None = None
    inset: Inset | None = None

    def __post_init__(self):
        if not self.id:
            raise FiguraInvalida("um painel sem id")
        for nome, minimo in (("linha", 0), ("coluna", 0), ("linhas", 1), ("colunas", 1)):
            valor = getattr(self, nome)
            if isinstance(valor, bool) or not isinstance(valor, int) or valor < minimo:
                raise FiguraInvalida(f"o painel {self.id}: {nome} inválido: {valor!r}")
        for nome in ("limites_x", "limites_y"):
            if getattr(self, nome) is not None:
                object.__setattr__(self, nome, _limites(getattr(self, nome), f"o painel {self.id}: {nome}"))
        ids = [id_ for id_, _e in self.tracos]
        if len(set(ids)) != len(ids) or not all(isinstance(e, EstiloDoTraco) for _i, e in self.tracos):
            raise FiguraInvalida(f"o painel {self.id}: os estilos dos traços são inválidos")
        object.__setattr__(self, "tracos", tuple((i, e) for i, e in self.tracos if not e.vazio))
        if self.legenda not in LEGENDAS:
            raise FiguraInvalida(f"o painel {self.id}: legenda desconhecida {self.legenda!r} (use "
                                 f"{', '.join(LEGENDAS)})")
        for nome in ("nome_x", "nome_y", "rotulo"):
            if getattr(self, nome) is not None and not isinstance(getattr(self, nome), str):
                raise FiguraInvalida(f"o painel {self.id}: {nome} inválido: {getattr(self, nome)!r}")
        for nome in ("prefixo_x", "prefixo_y"):
            valor = getattr(self, nome)
            if valor is not None and (isinstance(valor, bool) or valor not in PREFIXOS):
                raise FiguraInvalida(f"o painel {self.id}: {nome} inválido: {valor!r} (use um de "
                                     f"{', '.join(map(str, PREFIXOS))})")

    def estilo_do_traco(self, id_do_traco: str) -> EstiloDoTraco:
        return next((e for i, e in self.tracos if i == id_do_traco), EstiloDoTraco())

    def com_estilo_do_traco(self, id_do_traco: str, estilo: EstiloDoTraco) -> Painel:
        """O painel com ``estilo`` no traço (um estilo vazio volta o traço ao da vista)."""
        tracos = tuple((i, e) for i, e in self.tracos if i != id_do_traco)
        return replace(self, tracos=tracos + (((id_do_traco, estilo),) if not estilo.vazio else ()))

    @property
    def celulas(self) -> set[tuple[int, int]]:
        return {(i, j) for i in range(self.linha, self.linha + self.linhas)
                for j in range(self.coluna, self.coluna + self.colunas)}

    @property
    def vazio(self) -> bool:
        return self.vista is None and self.congelado is None


@dataclass(frozen=True)
class Figura:
    """Uma figura do projeto (o módulo diz o que é cada parte)."""

    id: str
    nome: str
    modelo: str = "ieee_1"
    altura_mm: float | None = None              # None: a do modelo
    linhas: int = 1
    colunas: int = 1
    paineis: tuple[Painel, ...] = ()
    idioma: str = "pt-BR"
    estilo: Estilo | None = None                # None: o do modelo
    eixos_x_compartilhados: bool = False        # na mesma coluna
    eixos_y_compartilhados: bool = False        # na mesma linha

    def __post_init__(self):
        if not self.id:
            raise FiguraInvalida("uma figura sem id")
        if not self.nome.strip():
            raise FiguraInvalida("uma figura sem nome")
        pagina = modelo(self.modelo)
        if self.altura_mm is None:
            object.__setattr__(self, "altura_mm", pagina.altura_mm)
        object.__setattr__(self, "altura_mm", _no_intervalo(
            self.altura_mm, (ALTURA_MINIMA_MM, pagina.altura_maxima_mm), f"a altura da figura {self.nome!r} (mm)"))
        if self.estilo is None:
            object.__setattr__(self, "estilo", pagina.estilo)
        if self.idioma not in IDIOMAS:
            raise FiguraInvalida(f"idioma desconhecido: {self.idioma!r} (use {', '.join(IDIOMAS)})")
        for nome in ("linhas", "colunas"):
            valor = getattr(self, nome)
            if isinstance(valor, bool) or not isinstance(valor, int) or not 1 <= valor <= GRADE_MAXIMA:
                raise FiguraInvalida(f"a grade da figura {self.nome!r}: {nome} fora de 1 a {GRADE_MAXIMA}: {valor!r}")
        ocupadas: dict[tuple[int, int], str] = {}
        ids = set()
        for p in self.paineis:
            if p.id in ids:
                raise FiguraInvalida(f"dois painéis com o id {p.id!r} na figura {self.nome!r}")
            ids.add(p.id)
            if p.linha + p.linhas > self.linhas or p.coluna + p.colunas > self.colunas:
                raise FiguraInvalida(f"o painel {p.id} sai da grade {self.linhas} × {self.colunas} da figura "
                                     f"{self.nome!r}")
            for celula in p.celulas:
                if celula in ocupadas:
                    raise FiguraInvalida(f"os painéis {ocupadas[celula]} e {p.id} se sobrepõem na figura {self.nome!r}")
                ocupadas[celula] = p.id

    @property
    def pagina(self) -> ModeloDePagina:
        return modelo(self.modelo)

    @property
    def largura_mm(self) -> float:
        return self.pagina.largura_mm

    @property
    def separador_decimal(self) -> str:
        return IDIOMAS[self.idioma]

    def em_ordem(self) -> tuple[Painel, ...]:
        """Os painéis na ordem de leitura: por linha, e na linha, por coluna."""
        return tuple(sorted(self.paineis, key=lambda p: (p.linha, p.coluna)))

    def rotulos(self) -> dict[str, str]:
        """O rótulo de cada painel (pelo id): o próprio, ou (a), (b)… na ordem de leitura, contando só os
        automáticos."""
        rotulos, n = {}, 0
        for p in self.em_ordem():
            if p.rotulo is not None:
                rotulos[p.id] = p.rotulo
            else:
                rotulos[p.id] = f"({_letra(n)})"
                n += 1
        return rotulos

    def vistas_ligadas(self) -> set[str]:
        """Os ids das vistas de que a figura depende (os painéis ligados, não os congelados)."""
        return {p.vista for p in self.paineis if p.vista is not None and p.congelado is None}

    def com(self, **mudancas) -> Figura:
        return replace(self, **mudancas)


def _letra(n: int) -> str:
    """a, b, …, z, aa, ab…"""
    letras = string.ascii_lowercase
    texto = ""
    n += 1
    while n:
        n, resto = divmod(n - 1, 26)
        texto = letras[resto] + texto
    return texto


def nova(id: str, nome: str, id_do_modelo: str = "ieee_1", vista: str | None = None, id_do_painel: str = "") -> Figura:
    """Uma figura de um painel só, ligado a ``vista`` (o "uma vista vira figura com um clique")."""
    return Figura(id, nome, id_do_modelo, paineis=(Painel(id_do_painel or f"{id}-1", vista=vista),))


# ------------------------------------------------------------------ as edições (a área Figuras)

def acrescentar_painel(f: Figura, id_do_painel: str, vista: str | None = None) -> Figura:
    """``f`` com um painel novo: na primeira célula livre (na ordem de leitura) ou, com a grade cheia, numa linha
    nova embaixo, da largura da grade; a página cresce a altura de uma linha (até a máxima do modelo)."""
    ocupadas = set().union(*(p.celulas for p in f.paineis)) if f.paineis else set()
    livre = next(((i, j) for i in range(f.linhas) for j in range(f.colunas) if (i, j) not in ocupadas), None)
    if livre is not None:
        return replace(f, paineis=f.paineis + (Painel(id_do_painel, livre[0], livre[1], vista=vista),))
    if f.linhas >= GRADE_MAXIMA:
        raise FiguraInvalida(f"a grade da figura {f.nome!r} já tem {GRADE_MAXIMA} linhas")
    altura = min(f.altura_mm * (f.linhas + 1) / f.linhas, f.pagina.altura_maxima_mm)
    return replace(f, linhas=f.linhas + 1, altura_mm=altura,
                   paineis=f.paineis + (Painel(id_do_painel, f.linhas, 0, colunas=f.colunas, vista=vista),))


def trocar_painel(f: Figura, painel: Painel) -> Figura:
    """``f`` com ``painel`` no lugar do de mesmo id."""
    if painel.id not in {p.id for p in f.paineis}:
        raise FiguraInvalida(f"a figura {f.nome!r} não tem o painel {painel.id!r}")
    return replace(f, paineis=tuple(painel if p.id == painel.id else p for p in f.paineis))


def tirar_painel(f: Figura, id_do_painel: str) -> Figura:
    """``f`` sem o painel (a grade fica; a célula dele fica livre)."""
    if id_do_painel not in {p.id for p in f.paineis}:
        raise FiguraInvalida(f"a figura {f.nome!r} não tem o painel {id_do_painel!r}")
    return replace(f, paineis=tuple(p for p in f.paineis if p.id != id_do_painel))


def menor_grade(f: Figura) -> tuple[int, int]:
    """As linhas e as colunas que os painéis ocupam (a grade não encolhe abaixo disso)."""
    return (max((p.linha + p.linhas for p in f.paineis), default=1),
            max((p.coluna + p.colunas for p in f.paineis), default=1))


def trocar_modelo(f: Figura, id_do_modelo: str) -> Figura:
    """``f`` noutro modelo de página: a largura e o estilo dele; a altura de agora, dentro do que ele aceita (o slide
    tem a altura dele)."""
    pagina = modelo(id_do_modelo)
    altura = min(max(f.altura_mm, ALTURA_MINIMA_MM), pagina.altura_maxima_mm)
    return replace(f, modelo=id_do_modelo, altura_mm=altura, estilo=pagina.estilo)


# ------------------------------------------------------------------ o arquivo de projeto

_CAMPOS_DO_ESTILO = tuple(c.name for c in fields(Estilo))
_CAMPOS_DO_TRACO = tuple(c.name for c in fields(EstiloDoTraco))
_CAMPOS_DO_INSET = tuple(c.name for c in fields(Inset))


def estilo_para_dict(estilo: Estilo) -> dict:
    return {nome: getattr(estilo, nome) for nome in _CAMPOS_DO_ESTILO}


def estilo_de_dict(dados, onde: str, base: Estilo | None = None) -> Estilo:
    """O estilo de um JSON já lido; o que ele não diz vem de ``base`` (o do modelo de página). Um estilo da versão 5,
    sem o tamanho da legenda, a tem do tamanho do texto (como era desenhada)."""
    d = _objeto(dados, onde)
    if set(d) - set(_CAMPOS_DO_ESTILO):
        raise FiguraInvalida(f"{onde} tem campos desconhecidos: {', '.join(sorted(set(d) - set(_CAMPOS_DO_ESTILO)))}")
    if "legenda_pt" not in d and "texto_pt" in d:
        d = {**d, "legenda_pt": d["texto_pt"]}
    return replace(base or Estilo(), **d)


def modelos_de_estilo_para_json(modelos) -> list[dict]:
    return [{"nome": m.nome, "estilo": estilo_para_dict(m.estilo)} for m in modelos]


def modelos_de_estilo_de_json(dados) -> list[ModeloDeEstilo]:
    """Os modelos de estilo das preferências; um que não vale fica de fora (o arquivo pode ser de outra versão)."""
    modelos: list[ModeloDeEstilo] = []
    for bruto in dados if isinstance(dados, list) else []:
        try:
            m = ModeloDeEstilo(_objeto(bruto, "o modelo")["nome"], estilo_de_dict(bruto.get("estilo", {}), "o estilo"))
        except (FiguraInvalida, KeyError, TypeError):
            continue
        modelos = [outro for outro in modelos if outro.nome != m.nome] + [m]
    return modelos


def para_dict(f: Figura, vista_para_dict: Callable[[VistaSalva], dict]) -> dict:
    estilo = estilo_para_dict(f.estilo)
    return {"id": f.id, "nome": f.nome, "modelo": f.modelo, "altura_mm": f.altura_mm, "linhas": f.linhas,
            "colunas": f.colunas, "idioma": f.idioma, "estilo": estilo,
            "eixos_compartilhados": {"x": f.eixos_x_compartilhados, "y": f.eixos_y_compartilhados},
            "paineis": [_painel_para_dict(p, vista_para_dict) for p in f.paineis]}


def _painel_para_dict(p: Painel, vista_para_dict) -> dict:
    d: dict[str, Any] = {"id": p.id, "linha": p.linha, "coluna": p.coluna, "linhas": p.linhas, "colunas": p.colunas}
    if p.vista is not None:
        d["vista"] = p.vista
    if p.congelado is not None:
        d["congelado"] = vista_para_dict(p.congelado)
    if p.rotulo is not None:
        d["rotulo"] = p.rotulo
    for nome in ("limites_x", "limites_y"):
        if getattr(p, nome) is not None:
            d[nome] = list(getattr(p, nome))
    if p.tracos:
        d["tracos"] = {i: {c: getattr(e, c) for c in _CAMPOS_DO_TRACO if getattr(e, c) not in (None, "")}
                       for i, e in p.tracos}
    if p.legenda != "melhor":
        d["legenda"] = p.legenda
    for nome in ("nome_x", "nome_y", "prefixo_x", "prefixo_y"):
        if getattr(p, nome) is not None:
            d[nome] = getattr(p, nome)
    if p.inset is not None:
        valores = {c: getattr(p.inset, c) for c in _CAMPOS_DO_INSET}
        d["inset"] = {c: list(v) if isinstance(v, tuple) else v for c, v in valores.items() if v is not None}
    return d


def _objeto(valor, onde: str) -> dict:
    if not isinstance(valor, dict):
        raise FiguraInvalida(f"{onde} não é um objeto")
    return valor


def _texto(dados: dict, nome: str, onde: str, padrao: str | None = None) -> str:
    valor = dados.get(nome, padrao)
    if not isinstance(valor, str):
        raise FiguraInvalida(f"o campo {nome!r} em {onde} tem um valor inválido: {valor!r}")
    return valor


def de_dict(dados, onde: str, vista_de_dict: Callable[[Any, str], VistaSalva]) -> Figura:
    """A figura de um JSON já lido (``onde``: "a figura 2", para as mensagens). :class:`FiguraInvalida` se não vale."""
    d = _objeto(dados, onde)
    conhecidos = {"id", "nome", "modelo", "altura_mm", "linhas", "colunas", "idioma", "estilo",
                  "eixos_compartilhados", "paineis"}
    if set(d) - conhecidos:
        raise FiguraInvalida(f"{onde} tem campos desconhecidos: {', '.join(sorted(set(d) - conhecidos))}")
    estilo_bruto = _objeto(d.get("estilo", {}), f"o estilo de {onde}")
    compartilhados = _objeto(d.get("eixos_compartilhados", {}), f"os eixos compartilhados de {onde}")
    paineis = []
    brutos = d.get("paineis", [])
    if not isinstance(brutos, list):
        raise FiguraInvalida(f"os painéis de {onde} não são uma lista")
    for i, bruto in enumerate(brutos):
        onde_p = f"o painel {i + 1} de {onde}"
        p = _objeto(bruto, onde_p)
        conhecidos_p = {"id", "linha", "coluna", "linhas", "colunas", "vista", "congelado", "rotulo", "limites_x",
                        "limites_y", "tracos", "legenda", "nome_x", "nome_y", "prefixo_x", "prefixo_y", "inset"}
        if set(p) - conhecidos_p:
            raise FiguraInvalida(f"{onde_p} tem campos desconhecidos: {', '.join(sorted(set(p) - conhecidos_p))}")
        vista = p.get("vista")
        if vista is not None and not isinstance(vista, str):
            raise FiguraInvalida(f"a vista de {onde_p} é inválida: {vista!r}")
        rotulo = p.get("rotulo")
        if rotulo is not None and not isinstance(rotulo, str):
            raise FiguraInvalida(f"o rótulo de {onde_p} é inválido: {rotulo!r}")
        limites = {}
        for nome in ("limites_x", "limites_y"):
            valor = p.get(nome)
            if valor is not None and not isinstance(valor, list):
                raise FiguraInvalida(f"{nome} de {onde_p} não é uma lista: {valor!r}")
            limites[nome] = tuple(valor) if valor is not None else None
        congelado = vista_de_dict(p["congelado"], f"a vista congelada de {onde_p}") if "congelado" in p else None
        paineis.append(Painel(_texto(p, "id", onde_p), p.get("linha", 0), p.get("coluna", 0), p.get("linhas", 1),
                              p.get("colunas", 1), vista, congelado, rotulo, **limites,
                              tracos=_tracos_de_dict(p.get("tracos", {}), onde_p), legenda=p.get("legenda", "melhor"),
                              nome_x=p.get("nome_x"), nome_y=p.get("nome_y"), prefixo_x=p.get("prefixo_x"),
                              prefixo_y=p.get("prefixo_y"), inset=_inset_de_dict(p.get("inset"), onde_p)))
    x, y = compartilhados.get("x", False), compartilhados.get("y", False)
    if not isinstance(x, bool) or not isinstance(y, bool):
        raise FiguraInvalida(f"os eixos compartilhados de {onde} têm de ser verdadeiro ou falso")
    id_do_modelo = _texto(d, "modelo", onde, "ieee_1")
    # O que o estilo salvo não diz vem do modelo de página (um arquivo escrito à mão pode trazer só a família).
    estilo = estilo_de_dict(estilo_bruto, f"o estilo de {onde}", modelo(id_do_modelo).estilo) if estilo_bruto else None
    return Figura(_texto(d, "id", onde), _texto(d, "nome", onde), id_do_modelo,
                  d.get("altura_mm"), d.get("linhas", 1), d.get("colunas", 1), tuple(paineis),
                  _texto(d, "idioma", onde, "pt-BR"), estilo, x, y)


def _tracos_de_dict(dados, onde: str) -> tuple[tuple[str, EstiloDoTraco], ...]:
    tracos = []
    for id_, bruto in _objeto(dados, f"os traços de {onde}").items():
        e = _objeto(bruto, f"o traço {id_} de {onde}")
        if set(e) - set(_CAMPOS_DO_TRACO):
            raise FiguraInvalida(f"o traço {id_} de {onde} tem campos desconhecidos: "
                                 f"{', '.join(sorted(set(e) - set(_CAMPOS_DO_TRACO)))}")
        tracos.append((id_, EstiloDoTraco(**e)))
    return tuple(tracos)


def _inset_de_dict(dados, onde: str) -> Inset | None:
    if dados is None:
        return None
    d = _objeto(dados, f"o inset de {onde}")
    if set(d) - set(_CAMPOS_DO_INSET) or "limites_x" not in d:
        raise FiguraInvalida(f"o inset de {onde} é inválido (campos: {', '.join(sorted(d))})")
    return Inset(**{k: tuple(v) if isinstance(v, list) else v for k, v in d.items()})
