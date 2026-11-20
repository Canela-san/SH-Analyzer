"""A receita de um traço (docs/gui-plan.md, 7.1): de qual canal ele vem, a cadeia de transformações e como é
mostrado. **Um traço nunca copia dados**; ele guarda só esta receita, e o gráfico a aplica sobre a pirâmide do canal.

A ordem: o canal na unidade física, a cadeia (``cadeia.py``: a correção de sonda, os filtros, o "remover o DC") e, no
fim, o ganho, o offset e o deslocamento no tempo do traço (a apresentação, direto na pirâmide).

**A unidade do traço** (``unidade``) é a dos valores depois do ganho e do offset: vazia, a do canal (V, A); senão, a
que o usuário escolheu para o sensor (°C, Pa, rpm: ``unidades.py``). Com ela, o ganho e o offset são a
escala do sensor (10 mV/°C: ganho de 100 °C/V).

Imutável: uma mudança é uma receita nova (``com``), e o desfazer guarda a de antes e a de depois. Validada na
criação: uma receita inválida nunca entra no modelo nem no arquivo de projeto.

Sem Qt: o modelo (``modelo/``) e o arquivo de projeto (``dados/projeto.py``) usam a mesma.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, replace

from .cadeia import Cadeia, EtapaInvalida
from .unidades import UnidadeInvalida, validar_simbolo

EDITAVEIS = ("nome", "cor", "ganho", "offset", "deslocamento_s", "visivel", "faixa", "cadeia", "unidade")
"""O que o usuário muda num traço. A fonte e o canal, não: outro canal é outro traço."""


class ReceitaInvalida(ValueError):
    """Um campo fora do que a receita aceita; a mensagem diz qual e por quê."""


def _inteiro(valor) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _finito(valor) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor)


@dataclass(frozen=True)
class ReceitaDoTraco:
    fonte: str                  # o id da fonte no projeto
    canal: int                  # o número do canal na captura (o do cabeçalho)
    nome: str
    cor: int                    # a posição na paleta (12.3): a cor segue o traço, não a ordem na legenda
    ganho: float = 1.0          # multiplica o valor em unidade física; negativo inverte
    offset: float = 0.0         # somado depois do ganho, na unidade do traço
    deslocamento_s: float = 0.0  # o traço andado no tempo (positivo = para a direita)
    visivel: bool = True
    faixa: int = 0              # em qual faixa da vista de tempo
    cadeia: Cadeia = field(default_factory=Cadeia)    # as transformações, antes do ganho e do offset
    unidade: str = ""           # a do traço (depois do ganho e do offset); vazia: a do canal

    def __post_init__(self) -> None:
        if not isinstance(self.fonte, str) or not self.fonte:
            raise ReceitaInvalida("a fonte do traço é obrigatória")
        if not _inteiro(self.canal) or self.canal < 0:
            raise ReceitaInvalida(f"canal inválido: {self.canal!r}")
        if not isinstance(self.nome, str) or not self.nome.strip():
            raise ReceitaInvalida("o nome do traço não pode ficar vazio")
        if not _inteiro(self.cor) or self.cor < 0:
            raise ReceitaInvalida(f"cor inválida: {self.cor!r} (a posição na paleta: 0, 1, 2...)")
        if not _finito(self.ganho) or self.ganho == 0:
            raise ReceitaInvalida(f"ganho inválido: {self.ganho!r} (um número diferente de zero)")
        if not _finito(self.offset):
            raise ReceitaInvalida(f"offset inválido: {self.offset!r}")
        if not _finito(self.deslocamento_s):
            raise ReceitaInvalida(f"deslocamento no tempo inválido: {self.deslocamento_s!r}")
        if not isinstance(self.visivel, bool):
            raise ReceitaInvalida(f"visível tem de ser verdadeiro ou falso, não {self.visivel!r}")
        if not _inteiro(self.faixa) or self.faixa < 0:
            raise ReceitaInvalida(f"faixa inválida: {self.faixa!r}")
        if not isinstance(self.cadeia, Cadeia):
            raise ReceitaInvalida(f"a cadeia de transformações tem de ser uma Cadeia, não {self.cadeia!r}")
        if self.unidade != "":
            try:
                if validar_simbolo(self.unidade) != self.unidade:
                    raise UnidadeInvalida("a unidade tem espaços nas pontas")
            except UnidadeInvalida as e:
                raise ReceitaInvalida(f"unidade inválida: {e}") from None

    def com(self, **mudancas) -> ReceitaDoTraco:
        """A receita com ``mudancas`` (só os campos de :data:`EDITAVEIS`). Levanta :class:`ReceitaInvalida`."""
        fora = set(mudancas) - set(EDITAVEIS)
        if fora:
            raise ReceitaInvalida(f"não dá para mudar {', '.join(sorted(fora))} num traço")
        for campo in ("nome", "unidade"):
            if campo in mudancas and isinstance(mudancas[campo], str):
                mudancas[campo] = mudancas[campo].strip()
        return replace(self, **mudancas)

    def diferencas(self, outra: ReceitaDoTraco) -> frozenset[str]:
        """Os campos que mudam desta receita para ``outra``."""
        return frozenset(f.name for f in fields(self) if getattr(self, f.name) != getattr(outra, f.name))

    def para_dict(self) -> dict:
        """Os campos para o arquivo de projeto; a cadeia vai como a lista ``etapas``."""
        dados = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "cadeia"}
        dados["etapas"] = self.cadeia.para_lista()
        return dados

    @classmethod
    def de_dict(cls, dados: dict) -> ReceitaDoTraco:
        """A receita do arquivo de projeto (os campos de :meth:`para_dict`; sem ``etapas``, a cadeia vazia).
        Levanta :class:`ReceitaInvalida` (um campo inválido) ou ``TypeError`` (um campo obrigatório que falta)."""
        valores = {f.name: dados[f.name] for f in fields(cls) if f.name != "cadeia" and f.name in dados}
        if "etapas" in dados:
            try:
                valores["cadeia"] = Cadeia.de_lista(dados["etapas"])
            except EtapaInvalida as e:
                raise ReceitaInvalida(f"a cadeia de transformações é inválida: {e}") from None
        return cls(**valores)

    def unidade_de(self, unidade_do_canal: str) -> str:
        """A unidade dos valores do traço: a dele ou, sem uma, a que a cadeia dá ao canal (V → V/s na derivada)."""
        return self.unidade or self.cadeia.unidade_de(unidade_do_canal)

    def afim(self, escala_do_canal: float, deslocamento_do_canal: float) -> tuple[float, float]:
        """A conversão inteira, do código do ADC ao valor mostrado: ``y = escala * codigo + deslocamento``, juntando
        a do canal (a calibração, da ``api``) com o ganho e o offset do traço. Vai direto na pirâmide (7.2)."""
        return self.ganho * escala_do_canal, self.ganho * deslocamento_do_canal + self.offset


def proxima_cor(em_uso) -> int:
    """A menor posição da paleta que nenhum traço usa: remover o traço 2 libera o âmbar para o próximo, e os outros
    não mudam de cor (12.3)."""
    usadas = set(em_uso)
    cor = 0
    while cor in usadas:
        cor += 1
    return cor
