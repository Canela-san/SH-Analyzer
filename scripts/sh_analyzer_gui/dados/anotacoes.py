r"""As anotações de uma vista (a F5.8; docs/gui-plan.md, 10.1; AN-11 e FG-03), sem Qt: o texto, a seta, a região e
a cota de Δt (ou de Δf, no espectro). Elas são **da vista**: a Análise as desenha sobre os traços, ficam no projeto
(``VistaSalva.anotacoes``) e vão para a figura com o painel ligado (o congelado leva a cópia delas).

**As coordenadas** são as dos dados da vista, sem prefixo: o x em segundos (no tempo da vista) ou em hertz, o y na
unidade da faixa (a escala comum dos traços dela: a de quem não tem escala própria). ``faixa`` é o número da faixa da
vista de tempo (o ``receita.faixa`` dos traços dela); vistas que sobrepõem os traços põem todas na faixa única.

* **texto:** o texto em ``(x0, y0)`` (o canto de baixo, à esquerda);
* **seta:** a ponta em ``(x0, y0)``, o que ela aponta, e o começo (com o texto, se houver) em ``(x1, y1)``;
* **região:** a faixa de ``x0`` a ``x1``, da altura inteira do eixo, com o texto em cima, à esquerda;
* **cota:** a medida de ``x0`` a ``x1`` na altura ``y0``, com as duas pontas e o texto em cima; sem texto, o próprio
  Δt (ou Δf) com o prefixo do SI (:func:`texto_da_cota`).

Os textos aceitam a matemática do mathtext na figura (``$\Delta t$``); na Análise eles aparecem como foram escritos.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace

from .unidades import PREFIXO_DO_EXPOENTE, expoente_de_engenharia

TIPOS = {"texto": "Texto", "seta": "Seta", "regiao": "Região", "cota": "Cota"}
"""Os tipos de anotação e o nome de cada um."""
COM_FIM = {"seta", "regiao", "cota"}
"""Os tipos que têm ``x1``."""


class AnotacaoInvalida(ValueError):
    """Uma anotação que não vale (a mensagem diz por quê)."""


def _numero(valor, o_que: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise AnotacaoInvalida(f"{o_que} inválido: {valor!r}")
    return float(valor)


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

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id:
            raise AnotacaoInvalida("uma anotação sem id")
        if self.tipo not in TIPOS:
            raise AnotacaoInvalida(f"tipo de anotação desconhecido: {self.tipo!r} (use {', '.join(TIPOS)})")
        object.__setattr__(self, "x0", _numero(self.x0, "o x0"))
        object.__setattr__(self, "y0", _numero(self.y0, "o y0"))
        if self.tipo in COM_FIM:
            if self.x1 is None:
                raise AnotacaoInvalida(f"a {TIPOS[self.tipo].lower()} precisa do x1")
            object.__setattr__(self, "x1", _numero(self.x1, "o x1"))
        elif self.x1 is not None or self.y1 is not None:
            raise AnotacaoInvalida("o texto tem só um ponto (x0, y0)")
        if self.tipo == "seta":
            object.__setattr__(self, "y1", _numero(self.y0 if self.y1 is None else self.y1, "o y1"))
        elif self.y1 is not None:
            raise AnotacaoInvalida(f"a {TIPOS[self.tipo].lower()} não tem y1")
        if self.tipo in ("regiao", "cota"):
            if self.x0 == self.x1:
                raise AnotacaoInvalida(f"a {TIPOS[self.tipo].lower()} precisa de dois x diferentes")
            if self.x1 < self.x0:                                   # sempre da esquerda para a direita
                x0, x1 = self.x1, self.x0
                object.__setattr__(self, "x0", x0)
                object.__setattr__(self, "x1", x1)
        if not isinstance(self.texto, str):
            raise AnotacaoInvalida(f"o texto da anotação é inválido: {self.texto!r}")
        if isinstance(self.faixa, bool) or not isinstance(self.faixa, int) or self.faixa < 0:
            raise AnotacaoInvalida(f"a faixa da anotação é inválida: {self.faixa!r}")

    def com(self, **mudancas) -> Anotacao:
        return replace(self, **mudancas)

    def movida(self, dx: float, dy: float = 0.0) -> Anotacao:
        """A anotação inteira andada de ``dx`` no x e de ``dy`` no y."""
        return replace(self, x0=self.x0 + dx, y0=self.y0 + dy,
                       x1=None if self.x1 is None else self.x1 + dx,
                       y1=None if self.y1 is None else self.y1 + dy)


_CAMPOS = tuple(c.name for c in fields(Anotacao))


def para_dict(a: Anotacao) -> dict:
    return {c: getattr(a, c) for c in _CAMPOS if getattr(a, c) not in (None, "") and not (c == "faixa" and a.faixa == 0)}


def de_dict(dados, onde: str) -> Anotacao:
    if not isinstance(dados, dict):
        raise AnotacaoInvalida(f"{onde} não é um objeto")
    if set(dados) - set(_CAMPOS):
        raise AnotacaoInvalida(f"{onde} tem campos desconhecidos: {', '.join(sorted(set(dados) - set(_CAMPOS)))}")
    if "id" not in dados or "tipo" not in dados or "x0" not in dados:
        raise AnotacaoInvalida(f"{onde} está incompleta (id, tipo e x0)")
    try:
        return Anotacao(**dados)
    except AnotacaoInvalida as erro:
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
