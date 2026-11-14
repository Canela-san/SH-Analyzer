"""O espectro de um traço (docs/gui-plan.md, 9.5; ES-01 e ES-02), sem Qt: as opções da vista de espectro e a conta.

**A conta é a da ``api``** (``api.espectro``, a do ``adc_tool --fft`` e ``--welch``), sobre o trecho do traço:

* **sem cadeia**, o Welch roda direto nos códigos do ADC, lote a lote (uma captura inteira não vai para a memória), e
  o resultado sobe ``20·log10|escala|``: o Welch é linear (a média de cada segmento sai antes da janela), e o número
  é o do Welch sobre os volts a 1e-12. A FFT usa os volts do trecho (``api.sinal_do_canal``), até
  :data:`LIMITE_DA_FFT` amostras;
* **com cadeia**, o trecho passa pela cadeia como o traço da tela (com a margem, em ``float64``: ``Cadeia.previa``),
  até :data:`LIMITE_DA_CADEIA` amostras; num trecho maior, a conta lê a materialização (``float32``), e espera por ela
  se ainda não ficou pronta (:class:`AguardandoMaterializacao`). **Uma diferença deliberada da CLI:** o ``adc_tool``
  filtra só o trecho pedido, e as bordas dele têm o transitório do filtro; aqui o trecho é o do traço transformado
  inteiro, sem transitório nas bordas. Sem cadeia, os números são os da CLI.

O ganho do traço multiplica o espectro (``20·log10|ganho|``); o offset é só o DC, que o espectro tira.

**Os picos** (ES-02) são os ``picos`` mais altos acima do piso de ruído + :data:`ACIMA_DO_PISO_DB`, de 2 kHz à
Nyquist; **os harmônicos de f₁** só com a FFT sincronizada (o Welch de 200 Hz não separa harmônicos de 50 Hz).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, fields, replace

import numpy as np
import supraharmonicos.api as api

from .cadeia import Cadeia, ContextoDaCadeia
from .materializacao import leitor_do_canal

METODOS = ("welch", "fft")
ESCALAS = ("db", "rms", "dbc")
TRECHOS = ("janela", "cursores", "captura")
MODOS = ("tom", "ruido")
LIMITE_DA_FFT = 1 << 24
"""A FFT de um segmento só vai inteira para a memória: até 16 M amostras (~6 GB menos que uma hora de captura)."""
LIMITE_DA_CADEIA = 1 << 23
"""Até 8 M amostras, o trecho de um traço com cadeia é transformado na hora, em ``float64``; acima, a materialização."""
ACIMA_DO_PISO_DB = 10.0
CORTE_DOS_PICOS = api.CORTE_SUPRAHARMONICOS_PADRAO


class OpcoesInvalidas(ValueError):
    """Uma opção da vista de espectro fora do que ela aceita; a mensagem diz qual e por quê."""


class AguardandoMaterializacao(Exception):
    """O trecho é grande demais para transformar na hora, e a materialização do traço ainda não ficou pronta."""


@dataclass(frozen=True)
class OpcoesDoEspectro:
    """O que a vista de espectro mostra (vai para o projeto)."""

    metodo: str = "welch"
    resolucao_hz: float = api.RESOLUCAO_WELCH_PADRAO
    janela: str | None = None
    modo: str = "tom"
    escala: str = "db"
    frequencia_log: bool = False
    trecho: str = "janela"
    vista_de_tempo: str | None = None          # o id da vista de tempo ligada (None: a primeira do projeto)
    picos: int = 5
    harmonicos: bool = True

    def __post_init__(self) -> None:
        for nome, aceitos in (("metodo", METODOS), ("escala", ESCALAS), ("trecho", TRECHOS), ("modo", MODOS)):
            if getattr(self, nome) not in aceitos:
                raise OpcoesInvalidas(f"{nome} inválido: {getattr(self, nome)!r} (use {', '.join(aceitos)})")
        if not (isinstance(self.resolucao_hz, (int, float)) and math.isfinite(self.resolucao_hz)
                and self.resolucao_hz > 0):
            raise OpcoesInvalidas(f"resolução inválida: {self.resolucao_hz!r} (Hz, positiva)")
        if not (isinstance(self.picos, int) and not isinstance(self.picos, bool) and 0 <= self.picos <= 50):
            raise OpcoesInvalidas(f"número de picos inválido: {self.picos!r} (de 0 a 50)")
        if self.escala == "rms" and self.modo == "ruido":
            raise OpcoesInvalidas("o valor RMS por bin só existe no modo tom (no modo ruído, cada bin é uma densidade)")
        for nome in ("frequencia_log", "harmonicos"):
            if not isinstance(getattr(self, nome), bool):
                raise OpcoesInvalidas(f"{nome} tem de ser verdadeiro ou falso")
        if self.janela is not None and not isinstance(self.janela, str):
            raise OpcoesInvalidas(f"janela inválida: {self.janela!r}")
        if self.vista_de_tempo is not None and not isinstance(self.vista_de_tempo, str):
            raise OpcoesInvalidas(f"vista de tempo inválida: {self.vista_de_tempo!r}")

    def com(self, **mudancas) -> OpcoesDoEspectro:
        return replace(self, **mudancas)

    @property
    def parametros(self) -> api.ParametrosEspectro:
        return api.ParametrosEspectro(self.metodo, self.janela, modo=self.modo, resolucao_hz=float(self.resolucao_hz))

    def para_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def de_dict(cls, dados) -> OpcoesDoEspectro:
        if not isinstance(dados, dict):
            raise OpcoesInvalidas("as opções do espectro são um objeto")
        nomes = {f.name for f in fields(cls)}
        desconhecidas = set(dados) - nomes
        if desconhecidas:
            raise OpcoesInvalidas(f"opções desconhecidas: {', '.join(sorted(desconhecidas))}")
        return cls(**dados)


@dataclass(frozen=True, eq=False)
class TrechoDoTraco:
    """O que a conta do espectro de um traço precisa: o canal, a cadeia, o trecho em amostras do canal e o ganho."""

    captura: api.Captura
    numero: int
    cadeia: Cadeia
    contexto: ContextoDaCadeia
    inicio: int
    fim: int
    ganho: float = 1.0
    materializada: np.ndarray | None = None     # as amostras transformadas do canal inteiro, se já prontas

    @property
    def n_amostras(self) -> int:
        return self.fim - self.inicio


PISO_DO_MOTOR_DB = {"tom": -240.0, "ruido": -200.0}
"""O nível mínimo que o motor escreve (``espectro._normalizar_espectro``: amplitude de 1e-12, PSD de 1e-20); o das
bandas é -240 dB (``agrupar_em_bandas``)."""


def _subir(espectro: api.Espectro, fator: float) -> api.Espectro:
    """O espectro de ``fator · sinal``: os níveis sobem ``20·log10|fator|`` (nos dois modos), com o mesmo piso que o
    motor teria escrito sobre o sinal escalado (um bin zerado fica no piso, e não no piso escalado)."""
    if fator == 1.0:
        return espectro
    d = 20.0 * math.log10(abs(fator))
    db = np.maximum(espectro.db + d, PISO_DO_MOTOR_DB[espectro.parametros.modo])
    bandas = None if espectro.db_bandas is None else np.maximum(espectro.db_bandas + d, -240.0)
    return replace(espectro, db=db, db_bandas=bandas)


def espectro_do_trecho(trecho: TrechoDoTraco, parametros: api.ParametrosEspectro, *,
                       progresso: Callable[[float], None] | None = None,
                       cancelado: Callable[[], bool] | None = None) -> api.Espectro:
    """O espectro do traço no trecho (ver o começo do módulo). Levanta ``api.ErroSHAN`` com o motivo, e
    :class:`AguardandoMaterializacao`."""
    canal = trecho.captura.canal(trecho.numero)
    n = trecho.n_amostras
    if trecho.ganho == 0:
        raise api.ErroSHAN("o ganho do traço é zero")
    if n < 2:
        raise api.ErroSHAN(f"o trecho tem {n} amostra(s): aproxime menos o zoom ou afaste os cursores")
    if parametros.metodo == "fft" and n > LIMITE_DA_FFT:
        raise api.ErroSHAN(f"a FFT de {n} amostras não cabe na memória (até {LIMITE_DA_FFT}): use o Welch ou um "
                           "trecho menor")
    a, b = trecho.inicio, trecho.fim
    if trecho.cadeia.vazia:
        if parametros.metodo == "welch":
            esp = api.espectro(canal.amostras[a:b], canal.taxa_hz, parametros, progresso=progresso, cancelado=cancelado)
            return _subir(esp, canal.escala * trecho.ganho)
        return api.espectro(api.sinal_do_canal(trecho.captura, trecho.numero, a, b) * trecho.ganho, canal.taxa_hz,
                            parametros)
    if n <= LIMITE_DA_CADEIA:
        sinal = trecho.cadeia.previa(leitor_do_canal(trecho.captura, trecho.numero), len(canal.amostras), a, b,
                                     trecho.contexto).valores * trecho.ganho
        return api.espectro(sinal, canal.taxa_hz, parametros, progresso=progresso, cancelado=cancelado)
    if trecho.materializada is None:
        raise AguardandoMaterializacao()
    esp = api.espectro(trecho.materializada[a:b], canal.taxa_hz, parametros, progresso=progresso, cancelado=cancelado)
    return _subir(esp, trecho.ganho)


@dataclass(frozen=True)
class Marcas:
    """O que a vista marca num espectro: os picos, o piso de ruído e as frequências dos harmônicos de f₁."""

    picos: tuple[api.Pico, ...]
    piso_db: float
    harmonicos_hz: tuple[float, ...]


def marcas(espectro: api.Espectro, n_picos: int, harmonicos: bool, ordem_maxima: int = 50) -> Marcas:
    """Os ``n_picos`` mais altos acima do piso + 10 dB (de 2 kHz à Nyquist), o piso e, com a FFT sincronizada, os
    harmônicos de f₁ até ``ordem_maxima`` abaixo da Nyquist."""
    nyquist = espectro.taxa_hz / 2.0
    piso = espectro.piso(CORTE_DOS_PICOS) if nyquist > CORTE_DOS_PICOS else espectro.piso(0.0)
    achados: tuple[api.Pico, ...] = ()
    if n_picos and math.isfinite(piso) and nyquist > CORTE_DOS_PICOS:
        achados = api.picos(espectro, piso + ACIMA_DO_PISO_DB, maximo=n_picos)
    f0 = espectro.f0_hz
    frequencias = tuple(h * f0 for h in range(2, ordem_maxima + 1) if h * f0 < nyquist) if harmonicos and f0 else ()
    return Marcas(achados, piso, frequencias)
