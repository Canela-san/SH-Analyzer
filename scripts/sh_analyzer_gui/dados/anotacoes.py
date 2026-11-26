r"""As anotações de uma vista (a F5.8; docs/gui-plan.md, 10.1; AN-11 e FG-03), sem Qt: as formas, os textos e os
desenhos à mão livre que o usuário põe sobre os traços, como num caderno. Elas são **da vista**: a Análise as desenha
sobre os traços, ficam no projeto (``VistaSalva.anotacoes``) e vão para a figura com o painel ligado (o congelado
leva a cópia delas).

**As coordenadas** são as dos dados da vista, sem prefixo: o x em segundos (no tempo da vista) ou em hertz, o y na
unidade da faixa (a escala comum dos traços dela: a de quem não tem escala própria). ``faixa`` é o número da faixa da
vista de tempo (o ``receita.faixa`` dos traços dela); vistas que sobrepõem os traços põem todas na faixa única. As
anotações acompanham os dados no zoom e no pan; as espessuras e os textos ficam do mesmo tamanho na tela.

* **texto:** o texto em ``(x0, y0)`` (o canto de baixo, à esquerda); com ``caixa``, num quadro com fundo;
* **seta:** a ponta em ``(x0, y0)``, o que ela aponta, e o começo (com o texto, se houver) em ``(x1, y1)``;
  ``ponta`` escolhe a cabeça (cheia, aberta, nas duas pontas, uma bolinha ou nenhuma);
* **linha:** o segmento de ``(x0, y0)`` a ``(x1, y1)``, com o texto no meio;
* **região:** a faixa de ``x0`` a ``x1``, da altura inteira do eixo, com o texto em cima, à esquerda;
* **cota:** a medida de ``x0`` a ``x1`` na altura ``y0``, com as duas pontas e o texto em cima; sem texto, o próprio
  Δt (ou Δf) com o prefixo do SI (:func:`texto_da_cota`);
* **retângulo** e **elipse:** a forma entre os cantos ``(x0, y0)`` e ``(x1, y1)``, com o texto no meio;
* **nível:** a linha horizontal em ``y0``, da largura inteira do eixo (um limiar), com o texto em ``x0``; sem texto,
  o próprio valor;
* **marcador:** um ponto marcado em ``(x0, y0)`` (``forma``: círculo, quadrado, losango, triângulo, x, mais ou
  estrela), com o texto ao lado;
* **desenho:** um traço à mão livre (o mouse ou a mesa digitalizadora): os ``pontos`` e, da mesa, a ``pressoes`` de
  cada um (de 0 a 1), que afinam e engrossam a linha. ``(x0, y0)`` é o primeiro ponto.

**O estilo** de cada uma: ``cor`` (vazia: a do tema na Análise, o preto na figura), ``espessura`` (px na tela; 0: a do
tipo), ``traco`` (sólido, tracejado, pontilhado, traço e ponto), ``opacidade``, ``preenchimento`` e
``opacidade_do_fundo`` (o fundo do retângulo, da elipse, da região e do quadro do texto), ``fonte`` (pt; 0: a do
tema), ``negrito``, ``italico`` e ``travada`` (não se move nem se muda pelo mouse). A ordem na lista é a ordem do
desenho: a última fica por cima.

Os textos aceitam a matemática do mathtext na figura (``$\Delta t$``); na Análise eles aparecem como foram escritos.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, fields, replace

from .unidades import PREFIXO_DO_EXPOENTE, expoente_de_engenharia

TIPOS = {"texto": "Texto", "seta": "Seta", "linha": "Linha", "regiao": "Região", "cota": "Cota",
         "retangulo": "Retângulo", "elipse": "Elipse", "nivel": "Nível", "marcador": "Marcador",
         "desenho": "Desenho"}
"""Os tipos de anotação e o nome de cada um."""
COM_FIM = {"seta", "linha", "regiao", "cota", "retangulo", "elipse"}
"""Os tipos que têm ``x1``."""
COM_Y1 = {"seta", "linha", "retangulo", "elipse"}
"""Os tipos que têm ``y1`` (sem ele, na altura de ``y0``)."""
FORMAS = ("retangulo", "elipse")
TRACOS = {"solido": "Sólido", "tracejado": "Tracejado", "pontilhado": "Pontilhado", "traco_ponto": "Traço e ponto"}
PONTAS = {"cheia": "Cheia", "aberta": "Aberta", "dupla": "Nas duas pontas", "circulo": "Bolinha",
          "nenhuma": "Nenhuma"}
MARCAS = {"circulo": "Círculo", "quadrado": "Quadrado", "losango": "Losango", "triangulo": "Triângulo", "x": "X",
          "mais": "Mais", "estrela": "Estrela"}
ESPESSURA_MAXIMA = 48.0
FONTE_MINIMA, FONTE_MAXIMA = 4.0, 96.0
_COR = re.compile(r"^#[0-9a-fA-F]{6}$")


class AnotacaoInvalida(ValueError):
    """Uma anotação que não vale (a mensagem diz por quê)."""


def _numero(valor, o_que: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise AnotacaoInvalida(f"{o_que} inválido: {valor!r}")
    return float(valor)


def _cor(valor, o_que: str) -> str:
    if not isinstance(valor, str) or (valor and not _COR.match(valor)):
        raise AnotacaoInvalida(f"{o_que} inválida: {valor!r} (use #rrggbb, ou vazio)")
    return valor.lower()


def _escolha(valor, opcoes: dict, o_que: str) -> str:
    if valor not in opcoes:
        raise AnotacaoInvalida(f"{o_que} desconhecido: {valor!r} (use {', '.join(opcoes)})")
    return valor


def _fracao(valor, o_que: str, minimo: float = 0.0) -> float:
    v = _numero(valor, o_que)
    if not minimo <= v <= 1.0:
        raise AnotacaoInvalida(f"{o_que} fora de {minimo:g} a 1: {valor!r}")
    return v


@dataclass(frozen=True)
class Anotacao:
    id: str
    tipo: str
    x0: float
    y0: float = 0.0
    x1: float | None = None
    y1: float | None = None
    texto: str = ""
    faixa: int = 0
    cor: str = ""
    espessura: float = 0.0
    traco: str = "solido"
    opacidade: float = 1.0
    preenchimento: str = ""
    opacidade_do_fundo: float = 0.2
    fonte: float = 0.0
    negrito: bool = False
    italico: bool = False
    caixa: bool = False
    ponta: str = "cheia"
    forma: str = "circulo"
    travada: bool = False
    pontos: tuple = ()
    pressoes: tuple = ()

    def __post_init__(self):
        definir = object.__setattr__
        if not isinstance(self.id, str) or not self.id:
            raise AnotacaoInvalida("uma anotação sem id")
        if self.tipo not in TIPOS:
            raise AnotacaoInvalida(f"tipo de anotação desconhecido: {self.tipo!r} (use {', '.join(TIPOS)})")
        nome = TIPOS[self.tipo].lower()
        if self.tipo == "desenho":
            pontos = self.pontos
            if not isinstance(pontos, (tuple, list)) or not pontos:
                raise AnotacaoInvalida("o desenho precisa de pelo menos um ponto")
            try:
                pontos = tuple((_numero(p[0], "um ponto do desenho"), _numero(p[1], "um ponto do desenho"))
                               for p in pontos)
            except (TypeError, IndexError):
                raise AnotacaoInvalida("os pontos do desenho são pares (x, y)") from None
            definir(self, "pontos", pontos)
            pressoes = tuple(_fracao(v, "a pressão de um ponto") for v in (self.pressoes or ()))
            if pressoes and len(pressoes) != len(pontos):
                raise AnotacaoInvalida("o desenho tem uma pressão para cada ponto (ou nenhuma)")
            definir(self, "pressoes", pressoes)
            definir(self, "x0", pontos[0][0])
            definir(self, "y0", pontos[0][1])
        elif self.pontos or self.pressoes:
            raise AnotacaoInvalida(f"só o desenho tem pontos (a {nome} não)")
        definir(self, "x0", _numero(self.x0, "o x0"))
        definir(self, "y0", _numero(self.y0, "o y0"))
        if self.tipo in COM_FIM:
            if self.x1 is None:
                raise AnotacaoInvalida(f"a {nome} precisa do x1")
            definir(self, "x1", _numero(self.x1, "o x1"))
        elif self.x1 is not None or self.y1 is not None:
            raise AnotacaoInvalida(f"o {nome} tem só um ponto (x0, y0)" if self.tipo in ("texto", "marcador", "nivel")
                                   else f"a {nome} não tem x1 nem y1")
        if self.tipo in COM_Y1:
            definir(self, "y1", _numero(self.y0 if self.y1 is None else self.y1, "o y1"))
        elif self.y1 is not None:
            raise AnotacaoInvalida(f"a {nome} não tem y1")
        if self.tipo in ("regiao", "cota") + FORMAS:
            if self.x0 == self.x1:
                raise AnotacaoInvalida(f"a {nome} precisa de dois x diferentes")
            if self.x1 < self.x0:                                   # sempre da esquerda para a direita
                x0, x1 = self.x1, self.x0
                definir(self, "x0", x0)
                definir(self, "x1", x1)
        if self.tipo in FORMAS:
            if self.y0 == self.y1:
                raise AnotacaoInvalida(f"a {nome} precisa de dois y diferentes")
            if self.y1 < self.y0:                                   # e de baixo para cima
                y0, y1 = self.y1, self.y0
                definir(self, "y0", y0)
                definir(self, "y1", y1)
        if not isinstance(self.texto, str):
            raise AnotacaoInvalida(f"o texto da anotação é inválido: {self.texto!r}")
        if isinstance(self.faixa, bool) or not isinstance(self.faixa, int) or self.faixa < 0:
            raise AnotacaoInvalida(f"a faixa da anotação é inválida: {self.faixa!r}")
        definir(self, "cor", _cor(self.cor, "a cor"))
        definir(self, "preenchimento", _cor(self.preenchimento, "a cor do preenchimento"))
        espessura = _numero(self.espessura, "a espessura")
        if not 0.0 <= espessura <= ESPESSURA_MAXIMA:
            raise AnotacaoInvalida(f"a espessura vai de 0 (a do tipo) a {ESPESSURA_MAXIMA:g} px: {espessura!r}")
        definir(self, "espessura", espessura)
        fonte = _numero(self.fonte, "o tamanho da fonte")
        if fonte and not FONTE_MINIMA <= fonte <= FONTE_MAXIMA:
            raise AnotacaoInvalida(f"o tamanho da fonte vai de {FONTE_MINIMA:g} a {FONTE_MAXIMA:g} pt (0: o do tema)")
        definir(self, "fonte", fonte)
        definir(self, "opacidade", _fracao(self.opacidade, "a opacidade", 0.05))
        definir(self, "opacidade_do_fundo", _fracao(self.opacidade_do_fundo, "a opacidade do fundo"))
        _escolha(self.traco, TRACOS, "o traço")
        _escolha(self.ponta, PONTAS, "a ponta da seta")
        _escolha(self.forma, MARCAS, "a forma do marcador")
        for nome_do_campo in ("negrito", "italico", "caixa", "travada"):
            if not isinstance(getattr(self, nome_do_campo), bool):
                raise AnotacaoInvalida(f"o campo {nome_do_campo} é sim ou não: {getattr(self, nome_do_campo)!r}")

    def com(self, **mudancas) -> Anotacao:
        return replace(self, **mudancas)

    def movida(self, dx: float, dy: float = 0.0) -> Anotacao:
        """A anotação inteira andada de ``dx`` no x e de ``dy`` no y."""
        if self.tipo == "desenho":
            return replace(self, pontos=tuple((x + dx, y + dy) for x, y in self.pontos))
        return replace(self, x0=self.x0 + dx, y0=self.y0 + dy,
                       x1=None if self.x1 is None else self.x1 + dx,
                       y1=None if self.y1 is None else self.y1 + dy)

    def limites(self) -> tuple[float, float, float, float]:
        """O retângulo ``(x0, x1, y0, y1)`` que a anotação ocupa nos dados (sem os textos, que têm o tamanho da
        tela; a região e o nível vão de um lado ao outro do eixo, e aqui ficam só no x ou no y deles)."""
        if self.tipo == "desenho":
            xs = [p[0] for p in self.pontos]
            ys = [p[1] for p in self.pontos]
            return min(xs), max(xs), min(ys), max(ys)
        xs = [self.x0] + ([self.x1] if self.x1 is not None else [])
        ys = [self.y0] + ([self.y1] if self.y1 is not None else [])
        return min(xs), max(xs), min(ys), max(ys)

    def esticada(self, de: tuple[float, float, float, float], para: tuple[float, float, float, float]) -> Anotacao:
        """A anotação levada do retângulo ``de`` ao ``para`` (``(x0, x1, y0, y1)``): o desenho e as formas se esticam
        com ele (as alças do retângulo de seleção)."""
        a0, a1, b0, b1 = de
        c0, c1, d0, d1 = para

        def fx(x):
            return c0 + (x - a0) * (c1 - c0) / (a1 - a0) if a1 != a0 else x + (c0 - a0)

        def fy(y):
            return d0 + (y - b0) * (d1 - d0) / (b1 - b0) if b1 != b0 else y + (d0 - b0)

        if self.tipo == "desenho":
            return replace(self, pontos=tuple((fx(x), fy(y)) for x, y in self.pontos))
        return replace(self, x0=fx(self.x0), y0=fy(self.y0), x1=None if self.x1 is None else fx(self.x1),
                       y1=None if self.y1 is None else fy(self.y1))


_CAMPOS = tuple(c.name for c in fields(Anotacao))


_PADROES = {c.name: c.default for c in fields(Anotacao) if c.name not in ("id", "tipo", "x0")}


def para_dict(a: Anotacao) -> dict:
    """A anotação em JSON, sem os campos que estão no padrão (um projeto sem estilo fica como era). Os pontos do
    desenho vão como pares; o ``x0`` e o ``y0`` dele saem do primeiro ponto."""
    dados = {}
    for c in _CAMPOS:
        valor = getattr(a, c)
        if c in _PADROES and (valor == _PADROES[c] or valor is None):
            continue
        if a.tipo == "desenho" and c in ("x0", "y0"):
            continue
        if c == "pontos":
            valor = [[x, y] for x, y in valor]
        elif c == "pressoes":
            valor = list(valor)
        dados[c] = valor
    return dados


def de_dict(dados, onde: str) -> Anotacao:
    if not isinstance(dados, dict):
        raise AnotacaoInvalida(f"{onde} não é um objeto")
    if set(dados) - set(_CAMPOS):
        raise AnotacaoInvalida(f"{onde} tem campos desconhecidos: {', '.join(sorted(set(dados) - set(_CAMPOS)))}")
    if dados.get("tipo") == "desenho" and "x0" not in dados and dados.get("pontos"):
        dados = {**dados, "x0": 0.0}                     # o primeiro ponto, que o desenho põe no lugar
    if "id" not in dados or "tipo" not in dados or "x0" not in dados:
        raise AnotacaoInvalida(f"{onde} está incompleta (id, tipo e x0)")
    if isinstance(dados.get("pontos"), list):
        dados = {**dados, "pontos": tuple(tuple(p) if isinstance(p, list) else p for p in dados["pontos"])}
    if isinstance(dados.get("pressoes"), list):
        dados = {**dados, "pressoes": tuple(dados["pressoes"])}
    try:
        return Anotacao(**dados)
    except AnotacaoInvalida as erro:
        raise AnotacaoInvalida(f"{onde}: {erro}") from None
    except TypeError as erro:
        raise AnotacaoInvalida(f"{onde}: {erro}") from None


def lista_de_dict(dados, onde: str) -> tuple[Anotacao, ...]:
    """As anotações de uma vista (os ids sem repetir)."""
    if not isinstance(dados, list):
        raise AnotacaoInvalida(f"as anotações de {onde} não são uma lista")
    anotacoes = tuple(de_dict(d, f"a anotação {i + 1} de {onde}") for i, d in enumerate(dados))
    ids = [a.id for a in anotacoes]
    if len(set(ids)) != len(ids):
        raise AnotacaoInvalida(f"duas anotações com o mesmo id em {onde}")
    return anotacoes


def formatar(valor: float, unidade: str, separador: str = ",", digitos: int = 4) -> str:
    """``valor`` com o prefixo do SI e ``digitos`` algarismos significativos (``0,001 25 s`` -> ``1,25 ms``)."""
    if valor == 0 or not math.isfinite(valor):
        return f"0 {unidade}"
    expoente = expoente_de_engenharia(valor)
    mantissa = valor / 10.0 ** expoente
    casas = max(0, digitos - 1 - math.floor(math.log10(abs(mantissa))))
    texto = f"{mantissa:.{casas}f}"
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return f"{texto.replace('.', separador).replace('-', '−')} {PREFIXO_DO_EXPOENTE[expoente]}{unidade}"


def texto_da_cota(a: Anotacao, *, frequencia: bool = False, separador: str = ",", matematica: bool = False) -> str:
    """O texto da cota: o do usuário, ou o Δt (Δf, com ``frequencia``) entre as pontas. ``matematica``: o Δ pelo
    mathtext (a figura); sem ela, o caractere (a Análise)."""
    if a.texto:
        return a.texto
    simbolo = ("$\\Delta f$" if frequencia else "$\\Delta t$") if matematica else ("Δf" if frequencia else "Δt")
    return f"{simbolo} = {formatar(a.x1 - a.x0, 'Hz' if frequencia else 's', separador)}"


def texto_do_nivel(a: Anotacao, unidade: str = "", separador: str = ",") -> str:
    """O texto do nível: o do usuário, ou o próprio valor com o prefixo do SI."""
    if a.texto:
        return a.texto
    return formatar(a.y0, unidade, separador) if unidade else formatar(a.y0, "", separador).strip()


def rotulo(a: Anotacao, *, frequencia: bool = False, separador: str = ",") -> str:
    """O nome curto da anotação para as listas e os menus: o tipo e o texto ("Seta: pico")."""
    texto = texto_da_cota(a, frequencia=frequencia, separador=separador) if a.tipo == "cota" else a.texto
    texto = " ".join(texto.split())
    if len(texto) > 40:
        texto = texto[:39] + "…"
    return f"{TIPOS[a.tipo]}: {texto}" if texto else TIPOS[a.tipo]
