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
* **O estilo:** a família (as do aplicativo e as do Matplotlib: a STIX é a do tipo Times que as revistas pedem), os
  tamanhos em pt e as espessuras em pt.

**No arquivo de projeto** (``dados/projeto.py``, a versão 5) a figura vai por :func:`para_dict` e volta por
:func:`de_dict`; a vista congelada é escrita e lida pelo próprio ``projeto.py`` (os dois parâmetros que ele passa),
que conhece o formato das vistas. O que não vale é recusado com a razão (:class:`FiguraInvalida`).
"""

from __future__ import annotations

import string
from collections.abc import Callable
from dataclasses import dataclass, field, replace
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


class FiguraInvalida(ValueError):
    """Uma figura, um painel ou um estilo que não vale (a mensagem diz por quê)."""


def _no_intervalo(valor, intervalo: tuple[float, float], o_que: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not intervalo[0] <= valor <= intervalo[1]:
        raise FiguraInvalida(f"{o_que} fora de {intervalo[0]:g} a {intervalo[1]:g}: {valor!r}")
    return float(valor)


@dataclass(frozen=True)
class Estilo:
    """As letras e as linhas da figura (em pt)."""

    familia: str = "STIX"
    texto_pt: float = 8.0               # os rótulos dos eixos, a legenda
    marcas_pt: float = 7.0              # os números das marcas
    rotulo_do_painel_pt: float = 9.0    # o (a), (b)…
    linha_pt: float = 0.8               # os traços
    eixo_pt: float = 0.5                # a moldura e as marcas

    def __post_init__(self):
        if self.familia not in FAMILIAS:
            raise FiguraInvalida(f"família de letra desconhecida: {self.familia!r} (use {', '.join(FAMILIAS)})")
        for nome in ("texto_pt", "marcas_pt", "rotulo_do_painel_pt"):
            object.__setattr__(self, nome, _no_intervalo(getattr(self, nome), TAMANHO_PT, f"o tamanho {nome}"))
        for nome in ("linha_pt", "eixo_pt"):
            object.__setattr__(self, nome, _no_intervalo(getattr(self, nome), ESPESSURA_PT, f"a espessura {nome}"))


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
_RELATORIO = Estilo(texto_pt=10.0, marcas_pt=9.0, rotulo_do_painel_pt=11.0, linha_pt=1.0, eixo_pt=0.6)
_SLIDE = Estilo("Inter", texto_pt=16.0, marcas_pt=14.0, rotulo_do_painel_pt=18.0, linha_pt=2.0, eixo_pt=1.0)
_POSTER = Estilo("Inter", texto_pt=28.0, marcas_pt=24.0, rotulo_do_painel_pt=32.0, linha_pt=3.0, eixo_pt=1.5)

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
    veio); ``rotulo``, ``None`` para o automático; ``limites_x`` e ``limites_y``, ``None`` para os da vista."""

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

    def __post_init__(self):
        if not self.id:
            raise FiguraInvalida("um painel sem id")
        for nome, minimo in (("linha", 0), ("coluna", 0), ("linhas", 1), ("colunas", 1)):
            valor = getattr(self, nome)
            if isinstance(valor, bool) or not isinstance(valor, int) or valor < minimo:
                raise FiguraInvalida(f"o painel {self.id}: {nome} inválido: {valor!r}")
        for nome in ("limites_x", "limites_y"):
            limites = getattr(self, nome)
            if limites is None:
                continue
            if (len(limites) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in limites)
                    or not limites[0] < limites[1]):
                raise FiguraInvalida(f"o painel {self.id}: {nome} inválidos: {limites!r} (o primeiro menor que o "
                                     "segundo)")
            object.__setattr__(self, nome, (float(limites[0]), float(limites[1])))

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


# ------------------------------------------------------------------ o arquivo de projeto

_CAMPOS_DO_ESTILO = ("familia", "texto_pt", "marcas_pt", "rotulo_do_painel_pt", "linha_pt", "eixo_pt")


def para_dict(f: Figura, vista_para_dict: Callable[[VistaSalva], dict]) -> dict:
    estilo = {nome: getattr(f.estilo, nome) for nome in _CAMPOS_DO_ESTILO}
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
    if set(estilo_bruto) - set(_CAMPOS_DO_ESTILO):
        raise FiguraInvalida(f"o estilo de {onde} tem campos desconhecidos: "
                             f"{', '.join(sorted(set(estilo_bruto) - set(_CAMPOS_DO_ESTILO)))}")
    compartilhados = _objeto(d.get("eixos_compartilhados", {}), f"os eixos compartilhados de {onde}")
    paineis = []
    brutos = d.get("paineis", [])
    if not isinstance(brutos, list):
        raise FiguraInvalida(f"os painéis de {onde} não são uma lista")
    for i, bruto in enumerate(brutos):
        onde_p = f"o painel {i + 1} de {onde}"
        p = _objeto(bruto, onde_p)
        conhecidos_p = {"id", "linha", "coluna", "linhas", "colunas", "vista", "congelado", "rotulo", "limites_x",
                        "limites_y"}
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
                              p.get("colunas", 1), vista, congelado, rotulo, **limites))
    x, y = compartilhados.get("x", False), compartilhados.get("y", False)
    if not isinstance(x, bool) or not isinstance(y, bool):
        raise FiguraInvalida(f"os eixos compartilhados de {onde} têm de ser verdadeiro ou falso")
    id_do_modelo = _texto(d, "modelo", onde, "ieee_1")
    # O que o estilo salvo não diz vem do modelo de página (um arquivo escrito à mão pode trazer só a família).
    estilo = replace(modelo(id_do_modelo).estilo, **estilo_bruto) if estilo_bruto else None
    return Figura(_texto(d, "id", onde), _texto(d, "nome", onde), id_do_modelo,
                  d.get("altura_mm"), d.get("linhas", 1), d.get("colunas", 1), tuple(paineis),
                  _texto(d, "idioma", onde, "pt-BR"), estilo, x, y)
