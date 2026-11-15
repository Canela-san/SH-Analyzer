"""As unidades dos traços (docs/gui-plan.md, GE-05): um traço pode estar em qualquer unidade, a do canal (V, A) ou a
que o usuário escolher para o sensor dele (°C, K, Pa, m/s², rpm...).

* **O catálogo** (:data:`CATALOGO`) tem as principais (V, A, °C, K) e as comuns de sensores, cada uma com a grandeza
  que ela mede. As **unidades próprias** do usuário (as configurações) entram junto (:func:`definir_proprias`); uma
  unidade digitada que não está em nenhum dos dois também vale (sem grandeza conhecida).
* **Os múltiplos:** uma unidade do catálogo que aceita os prefixos do SI vale com eles também (mV, mA, kPa, µm,
  kN): é a mesma grandeza, na escala do prefixo (:func:`procurar`).
* **A conversão:** as unidades de uma mesma família (as temperaturas, as pressões, as acelerações...) se convertem
  entre si por uma afim exata (:func:`conversao`): trocar °C por K num traço muda o ganho e o offset dele, e os
  números continuam certos. Entre famílias diferentes não há conversão: trocar V por °C é dizer o que o sinal mede (a
  escala vem do ganho e do offset, ou dos dois pontos do inspetor).
* **Os prefixos na escrita:** ``numeros.formatar_si`` põe o prefixo (1,5 mV, 12 kPa) só nas unidades que o aceitam;
  °C, %, psi, os múltiplos (mV, kPa: o prefixo já está ali) e as outras sem prefixo saem com os algarismos na
  unidade (23,45 °C). Numa razão (°C/V), vale o numerador. Uma unidade fora do catálogo aceita (S/s, as digitadas).

Sem Qt: o modelo, as contas e os testes usam sem interface.
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

TAMANHO_MAXIMO = 16
PREFIXOS_DO_SI = {"p": -12, "n": -9, "µ": -6, "u": -6, "m": -3, "": 0, "k": 3, "M": 6, "G": 9}
"""Os prefixos que se leem e escrevem (o expoente de 10); ``u`` é o micro digitado sem o µ."""


class UnidadeInvalida(ValueError):
    """O símbolo não serve como unidade (vazio, longo demais, com espaços ou caracteres de controle)."""


@dataclass(frozen=True)
class Unidade:
    """``simbolo`` e a ``grandeza`` que ele mede. Na ``familia``, o valor na unidade base é ``a·valor + b`` (as de
    uma família se convertem entre si). ``prefixos``: aceita os prefixos do SI na escrita."""

    simbolo: str
    grandeza: str
    familia: str | None = None
    a: float = 1.0
    b: float = 0.0
    prefixos: bool = True


_F = 5.0 / 9.0
CATALOGO: tuple[Unidade, ...] = (
    # As principais.
    Unidade("V", "tensão", "tensão"),
    Unidade("A", "corrente", "corrente"),
    Unidade("°C", "temperatura", "temperatura", 1.0, 273.15, prefixos=False),
    Unidade("K", "temperatura", "temperatura"),
    # As de sensores comuns, por grandeza.
    Unidade("°F", "temperatura", "temperatura", _F, 273.15 - 32.0 * _F, prefixos=False),
    Unidade("Pa", "pressão", "pressão"),
    Unidade("bar", "pressão", "pressão", 1e5),
    Unidade("psi", "pressão", "pressão", 6894.757293168361, prefixos=False),
    Unidade("atm", "pressão", "pressão", 101325.0, prefixos=False),
    Unidade("mmHg", "pressão", "pressão", 133.322387415, prefixos=False),
    Unidade("m/s²", "aceleração", "aceleração"),
    Unidade("g", "aceleração", "aceleração", 9.80665),
    Unidade("m/s", "velocidade", "velocidade"),
    Unidade("km/h", "velocidade", "velocidade", 1 / 3.6, prefixos=False),
    Unidade("m", "deslocamento", "comprimento"),
    Unidade("N", "força", "força"),
    Unidade("N·m", "torque", "torque"),
    Unidade("kg", "massa", "massa", prefixos=False),
    Unidade("W", "potência", "potência"),
    Unidade("VA", "potência aparente", "potência aparente"),
    Unidade("var", "potência reativa", "potência reativa"),
    Unidade("J", "energia", "energia"),
    Unidade("Wh", "energia", "energia", 3600.0),
    Unidade("Ω", "resistência", "resistência"),
    Unidade("T", "campo magnético", "campo magnético"),
    Unidade("Hz", "frequência", "frequência"),
    Unidade("rpm", "rotação", "frequência", 1 / 60.0, prefixos=False),
    Unidade("rad", "ângulo", "ângulo"),
    Unidade("°", "ângulo", "ângulo", math.pi / 180.0, prefixos=False),
    Unidade("ε", "deformação", "deformação"),
    Unidade("lx", "iluminância", "iluminância"),
    Unidade("L/min", "vazão", "vazão", 1e-3 / 60.0, prefixos=False),
    Unidade("m³/h", "vazão", "vazão", 1 / 3600.0, prefixos=False),
    Unidade("%RH", "umidade relativa", prefixos=False),
    Unidade("%", "percentual", prefixos=False),
)
PRINCIPAIS = ("V", "A", "°C", "K")

_proprias: tuple[Unidade, ...] = ()


def validar_simbolo(simbolo: str) -> str:
    """O símbolo limpo (sem os espaços das pontas). Levanta :class:`UnidadeInvalida`."""
    if not isinstance(simbolo, str):
        raise UnidadeInvalida(f"a unidade tem de ser um texto, não {simbolo!r}")
    limpo = simbolo.strip()
    if not limpo:
        raise UnidadeInvalida("a unidade não pode ficar vazia")
    if len(limpo) > TAMANHO_MAXIMO:
        raise UnidadeInvalida(f"a unidade tem mais de {TAMANHO_MAXIMO} caracteres")
    if any(unicodedata.category(c).startswith("C") for c in limpo):
        raise UnidadeInvalida("a unidade tem um caractere de controle")
    if any(c.isspace() for c in limpo):     # os campos leem "1,5 kPa" sem os espaços: a unidade não pode ter um
        raise UnidadeInvalida("a unidade não pode ter espaços (use N·m, m/s)")
    return limpo


def definir_proprias(unidades: Iterable[Unidade]) -> None:
    """As unidades próprias do usuário (as configurações). As que repetem um símbolo do catálogo ficam de fora."""
    global _proprias
    do_catalogo = {u.simbolo for u in CATALOGO}
    vistas: set[str] = set()
    proprias = []
    for u in unidades:
        if u.simbolo in do_catalogo or u.simbolo in vistas:
            continue
        vistas.add(u.simbolo)
        proprias.append(u)
    _proprias = tuple(proprias)


def proprias() -> tuple[Unidade, ...]:
    return _proprias


def todas() -> tuple[Unidade, ...]:
    """O catálogo (as principais primeiro) e as próprias do usuário."""
    return CATALOGO + _proprias


def procurar(simbolo: str) -> Unidade | None:
    """A unidade do catálogo ou própria com este símbolo; ou o múltiplo de uma que aceita prefixos ("mA": a corrente,
    em ``a = 10⁻³``, que não aceita outro prefixo na escrita); ou ``None``."""
    exata = next((u for u in todas() if u.simbolo == simbolo), None)
    if exata is not None or len(simbolo) < 2 or not PREFIXOS_DO_SI.get(simbolo[0]):
        return exata
    base = next((u for u in todas() if u.simbolo == simbolo[1:]), None)
    if base is None or not base.prefixos:
        return None
    return Unidade(simbolo, base.grandeza, base.familia, base.a * 10.0 ** PREFIXOS_DO_SI[simbolo[0]], base.b,
                   prefixos=False)


def aceita_prefixos(simbolo: str) -> bool:
    """Se a escrita põe o prefixo do SI nesta unidade. Numa razão fora do catálogo (°C/V, mV/V), vale o numerador;
    uma unidade desconhecida aceita (S/s, as digitadas)."""
    u = procurar(simbolo)
    if u is not None:
        return u.prefixos
    numerador, barra, _ = simbolo.partition("/")
    return aceita_prefixos(numerador) if barra and numerador else True


def grandeza(simbolo: str) -> str:
    """A grandeza da unidade, ou ``""`` se ela não é conhecida."""
    u = procurar(simbolo)
    return u.grandeza if u is not None else ""


def conversao(de: str, para: str) -> tuple[float, float] | None:
    """``(c, d)`` com ``valor em para = c·(valor em de) + d``, se as duas são da mesma família; ``None`` se não se
    convertem (famílias diferentes, ou uma unidade sem família)."""
    if de == para:
        return 1.0, 0.0
    u, v = procurar(de), procurar(para)
    if u is None or v is None or u.familia is None or u.familia != v.familia:
        return None
    return u.a / v.a, (u.b - v.b) / v.a


def do_traco(unidade_da_receita: str, unidade_do_canal: str, grandeza_do_canal: str) -> tuple[str, str]:
    """``(grandeza, unidade)`` de um traço: a do canal, sem uma unidade própria; com ela, a grandeza dela (``""``
    se ela não é conhecida)."""
    if not unidade_da_receita or unidade_da_receita == unidade_do_canal:
        return grandeza_do_canal, unidade_do_canal
    return grandeza(unidade_da_receita), unidade_da_receita


def rotulo(grandeza_: str, unidade: str) -> str:
    """O rótulo de um eixo: "temperatura (°C)"; sem a grandeza, "valor (rpm)"."""
    return f"{grandeza_ or 'valor'} ({unidade})" if unidade else (grandeza_ or "valor")
