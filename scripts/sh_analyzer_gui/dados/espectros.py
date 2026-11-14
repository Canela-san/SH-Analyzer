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


# ---------------------------------------------------------------------------
# As bandas IEC e o espectrograma (ES-03, ES-04)
# ---------------------------------------------------------------------------

ESTATISTICAS = ("rms", "p95", "maximo", "minimo")
LIMITE_DA_SINCRONIZACAO = 1 << 26
"""As bandas sincronizadas acham os cruzamentos por zero da fundamental nos volts do trecho inteiro, na memória:
até 64 M amostras (~5 min a 200 kS/s, 512 MB)."""


def _validar_comum(opcoes) -> None:
    if opcoes.trecho not in TRECHOS:
        raise OpcoesInvalidas(f"trecho inválido: {opcoes.trecho!r} (use {', '.join(TRECHOS)})")
    if not (isinstance(opcoes.traco, int) and not isinstance(opcoes.traco, bool) and opcoes.traco >= 0):
        raise OpcoesInvalidas(f"traço inválido: {opcoes.traco!r} (a posição na vista de tempo)")
    if opcoes.vista_de_tempo is not None and not isinstance(opcoes.vista_de_tempo, str):
        raise OpcoesInvalidas(f"vista de tempo inválida: {opcoes.vista_de_tempo!r}")


class _OpcoesComDicionario:
    def com(self, **mudancas):
        return replace(self, **mudancas)

    def para_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def de_dict(cls, dados):
        if not isinstance(dados, dict):
            raise OpcoesInvalidas("as opções da vista são um objeto")
        desconhecidas = set(dados) - {f.name for f in fields(cls)}
        if desconhecidas:
            raise OpcoesInvalidas(f"opções desconhecidas: {', '.join(sorted(desconhecidas))}")
        return cls(**dados)


@dataclass(frozen=True)
class OpcoesDasBandas(_OpcoesComDicionario):
    """A vista das bandas IEC 61000-4-7 (anexo B): de qual traço (a posição na vista de tempo), o trecho, a faixa, a
    estatística do mapa de calor e as janelas sincronizadas."""

    traco: int = 0
    trecho: str = "captura"
    vista_de_tempo: str | None = None
    freq_min: float = 2000.0
    freq_max: float | None = None
    estatistica: str = "p95"
    sincronizar: bool = False

    def __post_init__(self) -> None:
        _validar_comum(self)
        if self.estatistica not in ESTATISTICAS:
            raise OpcoesInvalidas(f"estatística inválida: {self.estatistica!r} (use {', '.join(ESTATISTICAS)})")
        if not isinstance(self.sincronizar, bool):
            raise OpcoesInvalidas("sincronizar tem de ser verdadeiro ou falso")
        for nome in ("freq_min", "freq_max"):
            valor = getattr(self, nome)
            if valor is not None and not (isinstance(valor, (int, float)) and math.isfinite(valor) and valor >= 0):
                raise OpcoesInvalidas(f"{nome} inválida: {valor!r} (Hz)")

    @property
    def parametros(self) -> api.ParametrosBandasIEC:
        return api.ParametrosBandasIEC(float(self.freq_min), None if self.freq_max is None else float(self.freq_max),
                                       sincronizar=self.sincronizar)


@dataclass(frozen=True)
class OpcoesDoEspectrograma(_OpcoesComDicionario):
    """A vista do espectrograma: de qual traço, o trecho, a resolução, o modo e a faixa dinâmica do mapa de cores."""

    traco: int = 0
    trecho: str = "captura"
    vista_de_tempo: str | None = None
    resolucao_hz: float = api.RESOLUCAO_WELCH_PADRAO
    modo: str = "tom"
    faixa_dinamica_db: float = 80.0

    def __post_init__(self) -> None:
        _validar_comum(self)
        if self.modo not in MODOS:
            raise OpcoesInvalidas(f"modo inválido: {self.modo!r} (use {', '.join(MODOS)})")
        for nome in ("resolucao_hz", "faixa_dinamica_db"):
            valor = getattr(self, nome)
            if not (isinstance(valor, (int, float)) and math.isfinite(valor) and valor > 0):
                raise OpcoesInvalidas(f"{nome} inválida: {valor!r}")

    @property
    def parametros(self) -> api.ParametrosEspectrograma:
        return api.ParametrosEspectrograma(modo=self.modo, resolucao_hz=float(self.resolucao_hz))


GRANDEZAS_HARMONICAS = ("subgrupo", "grupo", "componente")
ESCALAS_HARMONICAS = ("pct", "rms")


@dataclass(frozen=True)
class OpcoesDosHarmonicos(_OpcoesComDicionario):
    """A vista dos harmônicos (IEC 61000-4-7): de qual traço, o trecho, a ordem máxima, a grandeza das barras (o
    subgrupo, que a IEC 61000-4-30 classe A pede; o grupo; ou a componente) e a escala (% da fundamental ou o valor
    RMS)."""

    traco: int = 0
    trecho: str = "janela"
    vista_de_tempo: str | None = None
    ordem_maxima: int = api.ORDEM_MAXIMA_IEC
    grandeza: str = "subgrupo"
    escala: str = "pct"

    def __post_init__(self) -> None:
        _validar_comum(self)
        if self.grandeza not in GRANDEZAS_HARMONICAS:
            raise OpcoesInvalidas(f"grandeza inválida: {self.grandeza!r} (use {', '.join(GRANDEZAS_HARMONICAS)})")
        if self.escala not in ESCALAS_HARMONICAS:
            raise OpcoesInvalidas(f"escala inválida: {self.escala!r} (use {', '.join(ESCALAS_HARMONICAS)})")
        if not (isinstance(self.ordem_maxima, int) and not isinstance(self.ordem_maxima, bool)
                and 2 <= self.ordem_maxima <= 200):
            raise OpcoesInvalidas(f"ordem máxima inválida: {self.ordem_maxima!r} (de 2 a 200)")

    @property
    def parametros(self) -> api.ParametrosHarmonicos:
        return api.ParametrosHarmonicos(self.ordem_maxima)


def harmonicos_do_trecho(trecho: TrechoDoTraco, parametros: api.ParametrosHarmonicos) -> api.ResultadoHarmonicos:
    """Os harmônicos do traço no trecho (``api.harmonicos``: o ``adc_tool --fft --harmonicos``, com a janela
    retangular sincronizada pelos cruzamentos por zero da fundamental). A FFT é um segmento só, nos volts do trecho
    na memória: até :data:`LIMITE_DA_FFT` amostras. Sem cadeia, os números são os da CLI."""
    if trecho.ganho == 0:
        raise api.ErroSHAN("o ganho do traço é zero")
    if trecho.n_amostras > LIMITE_DA_FFT:
        raise api.ErroSHAN(f"os harmônicos são uma FFT do trecho inteiro, na memória: até {LIMITE_DA_FFT} amostras "
                           f"(o trecho tem {trecho.n_amostras}); use a janela visível ou os cursores")
    canal = trecho.captura.canal(trecho.numero)
    if trecho.cadeia.vazia:
        volts = api.sinal_do_canal(trecho.captura, trecho.numero, trecho.inicio, trecho.fim) * trecho.ganho
    else:
        sinal, fator = _sinal_do_trecho(trecho, None, None)
        volts = np.asarray(sinal, dtype=np.float64) * fator
    return api.harmonicos(volts, canal.taxa_hz, parametros)


OPCOES_DO_TIPO = {"espectro": OpcoesDoEspectro, "bandas": OpcoesDasBandas, "espectrograma": OpcoesDoEspectrograma,
                  "harmonicos": OpcoesDosHarmonicos}
"""A classe das opções de cada tipo de vista de frequência (a vista de tempo não tem opções)."""


def _escalar_bandas(resultado: api.ResultadoBandasIEC, fator: float) -> api.ResultadoBandasIEC:
    """As bandas de ``fator · sinal``: os níveis (RMS de cada banda) multiplicados por ``|fator|``."""
    if fator == 1.0:
        return resultado
    f = abs(fator)
    b = resultado.bandas
    agregados = {nome: replace(serie, niveis=serie.niveis * f) for nome, serie in b.agregados.items()}
    return replace(resultado, bandas=replace(b, niveis=b.niveis * f, agregados=agregados))


def _sinal_do_trecho(trecho: TrechoDoTraco, progresso, cancelado):
    """O sinal do trecho para as contas lineares e o fator que falta aplicar: os códigos do ADC (sem cadeia), o
    traço transformado na hora (até 8 M amostras) ou a materialização."""
    canal = trecho.captura.canal(trecho.numero)
    a, b = trecho.inicio, trecho.fim
    if trecho.cadeia.vazia:
        return canal.amostras[a:b], canal.escala * trecho.ganho
    if trecho.n_amostras <= LIMITE_DA_CADEIA:
        return trecho.cadeia.previa(leitor_do_canal(trecho.captura, trecho.numero), len(canal.amostras), a, b,
                                    trecho.contexto).valores, trecho.ganho
    if trecho.materializada is None:
        raise AguardandoMaterializacao()
    return trecho.materializada[a:b], trecho.ganho


def bandas_do_trecho(trecho: TrechoDoTraco, parametros: api.ParametrosBandasIEC, *, progresso=None,
                     cancelado=None) -> api.ResultadoBandasIEC:
    """As bandas IEC do traço no trecho (``api.bandas_iec``, a do ``adc_tool --bandas-iec``). Sem cadeia, em cima dos
    códigos do ADC, multiplicadas pela escala (as bandas são lineares: a média de cada janela sai antes da FFT).
    Sincronizadas, as janelas seguem a fundamental do próprio traço, nos volts do trecho (até
    :data:`LIMITE_DA_SINCRONIZACAO` amostras)."""
    if trecho.ganho == 0:
        raise api.ErroSHAN("o ganho do traço é zero")
    canal = trecho.captura.canal(trecho.numero)
    if parametros.sincronizar:
        if trecho.n_amostras > LIMITE_DA_SINCRONIZACAO:
            raise api.ErroSHAN(f"as bandas sincronizadas acham a fundamental no trecho inteiro, na memória: até "
                               f"{LIMITE_DA_SINCRONIZACAO} amostras (o trecho tem {trecho.n_amostras}); use as "
                               "janelas fixas ou um trecho menor")
        if trecho.cadeia.vazia:        # os volts de verdade (o código uint16 tem o zero em 32 768)
            volts = api.sinal_do_canal(trecho.captura, trecho.numero, trecho.inicio, trecho.fim) * trecho.ganho
        else:
            sinal, fator = _sinal_do_trecho(trecho, progresso, cancelado)
            volts = np.asarray(sinal, dtype=np.float64) * fator
        return api.bandas_iec(volts, canal.taxa_hz, parametros, progresso=progresso, cancelado=cancelado)
    sinal, fator = _sinal_do_trecho(trecho, progresso, cancelado)
    return _escalar_bandas(api.bandas_iec(sinal, canal.taxa_hz, parametros, progresso=progresso,
                                          cancelado=cancelado), fator)


def espectrograma_do_trecho(trecho: TrechoDoTraco, parametros: api.ParametrosEspectrograma, *, progresso=None,
                            cancelado=None) -> api.Espectrograma:
    """O espectrograma do traço no trecho (``api.espectrograma``, o ``adc_tool --espectrograma``). Sem cadeia, em
    cima dos códigos, subindo ``20·log10|escala|`` (com o piso do motor)."""
    if trecho.ganho == 0:
        raise api.ErroSHAN("o ganho do traço é zero")
    canal = trecho.captura.canal(trecho.numero)
    sinal, fator = _sinal_do_trecho(trecho, progresso, cancelado)
    resultado = api.espectrograma(sinal, canal.taxa_hz, parametros, progresso=progresso, cancelado=cancelado)
    if fator == 1.0:
        return resultado
    d = 20.0 * math.log10(abs(fator))
    return replace(resultado, db=np.maximum(resultado.db + d, PISO_DO_MOTOR_DB[parametros.modo]))
