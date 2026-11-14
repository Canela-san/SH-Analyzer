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

**A FFT é o método padrão** (o que os pesquisadores de qualidade de energia usam), sincronizada aos ciclos da
fundamental como o ``adc_tool --fft``; num trecho sem a fundamental de 45 a 65 Hz (um tom de teste de 130 kHz sozinho,
por exemplo), a FFT é do trecho inteiro, sem sincronizar, com a janela Hann, e um aviso diz isso.

**A janela e os ciclos** (o inspetor): a janela é a da ``api`` (None: a padrão do método, a retangular na FFT
sincronizada e a Hann no Welch e na FFT sem sincronizar); ``ciclos`` limita a FFT sincronizada aos N primeiros ciclos
inteiros do trecho. **O preset da IEC 61000-4-7** (:data:`IEC_61000_4_7`) põe a janela de medição da norma: 10
ciclos numa rede de 50 Hz, 12 numa de 60 Hz (~200 ms), retangular e sincronizada com a fundamental; sem sincronismo,
a norma admite a Hann, que é o que a FFT faz quando não acha a fundamental.

**Os picos** (ES-02) são os ``picos`` mais altos acima do piso de ruído + :data:`ACIMA_DO_PISO_DB` e com
:data:`PROEMINENCIA_DOS_PICOS_DB` de proeminência, de 2 kHz à Nyquist: numa FFT só, de milhões de bins, o ruído tem
flutuações de mais de 10 dB acima do piso, e o ombro de um tom forte também. **Os harmônicos de f₁** só com a FFT
sincronizada (o Welch de 200 Hz não separa harmônicos de 50 Hz).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, fields, replace

import numpy as np
import supraharmonicos.api as api

from .cadeia import Cadeia, ContextoDaCadeia
from .materializacao import leitor_do_canal
from .piramide import Piramide, construir

METODOS = ("welch", "fft")
ESCALAS = ("db", "rms", "dbc")
TRECHOS = ("janela", "cursores", "captura")
MODOS = ("tom", "ruido")
LIMITE_DA_FFT = 1 << 24
"""A FFT de um segmento só vai inteira para a memória: até 16 M amostras (~6 GB menos que uma hora de captura)."""
LIMITE_DA_CADEIA = 1 << 23
"""Até 8 M amostras, o trecho de um traço com cadeia é transformado na hora, em ``float64``; acima, a materialização."""
ACIMA_DO_PISO_DB = 20.0
PROEMINENCIA_DOS_PICOS_DB = 10.0
CORTE_DOS_PICOS = api.CORTE_SUPRAHARMONICOS_PADRAO


JANELAS = {None: "Padrão do método", "retangular": "Retangular", "hann": "Hann", "blackmanharris": "Blackman-Harris",
           "flattop": "Flat-top", "kaiser": f"Kaiser (β = {api.KAISER_BETA_PADRAO:g})"}
"""As janelas da ``api`` (os nomes canônicos), com o nome para mostrar (o número, com o ponto: quem mostra põe o
separador das configurações, ``componentes.numeros.decimal``)."""
MAXIMO_DE_CICLOS = 100_000
FOLGA_DE_CICLOS = 10
"""Com ``ciclos``, a FFT sincronizada lê só o começo do trecho: os ciclos pedidos mais esta folga, no período mais
longo da busca da fundamental. O motor recorta o mesmo começo com uma folga menor (5 ciclos), e o resultado é o da
conta sobre o trecho inteiro."""


class OpcoesInvalidas(ValueError):
    """Uma opção da vista de espectro fora do que ela aceita; a mensagem diz qual e por quê."""


class AguardandoMaterializacao(Exception):
    """O trecho é grande demais para transformar na hora, e a materialização do traço ainda não ficou pronta."""


@dataclass(frozen=True)
class OpcoesDoEspectro:
    """O que a vista de espectro mostra (vai para o projeto)."""

    metodo: str = "fft"
    resolucao_hz: float = api.RESOLUCAO_WELCH_PADRAO
    janela: str | None = None                  # o nome canônico (JANELAS); None: a padrão do método
    ciclos: int | None = None                  # a FFT sincronizada só nos N primeiros ciclos do trecho; None: todos
    modo: str = "tom"
    escala: str = "db"
    frequencia_log: bool = False
    trecho: str = "cursores"                   # os cursores da vista de tempo; sem eles, a janela visível
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
        if self.janela not in JANELAS:
            raise OpcoesInvalidas(f"janela inválida: {self.janela!r} (use {', '.join(n for n in JANELAS if n)})")
        if self.ciclos is not None and not (isinstance(self.ciclos, int) and not isinstance(self.ciclos, bool)
                                            and 1 <= self.ciclos <= MAXIMO_DE_CICLOS):
            raise OpcoesInvalidas(f"ciclos inválidos: {self.ciclos!r} (de 1 a {MAXIMO_DE_CICLOS}, ou todos)")
        if self.vista_de_tempo is not None and not isinstance(self.vista_de_tempo, str):
            raise OpcoesInvalidas(f"vista de tempo inválida: {self.vista_de_tempo!r}")

    def com(self, **mudancas) -> OpcoesDoEspectro:
        return replace(self, **mudancas)

    @property
    def parametros(self) -> api.ParametrosEspectro:
        return api.ParametrosEspectro(self.metodo, self.janela, modo=self.modo, resolucao_hz=float(self.resolucao_hz),
                                      n_ciclos=self.ciclos if self.metodo == "fft" else None)

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


@dataclass(frozen=True)
class PresetDoEspectro:
    """Um conjunto de opções com nome (o começo de um lugar de presets): ``aplicar(opcoes, f1_hz)`` devolve as
    opções com o preset; ``segue(opcoes, f1_hz)`` diz se elas já são as dele. ``f1_hz`` é a fundamental medida (None
    se ainda não se sabe)."""

    nome: str
    descricao: Callable[[float | None], str]
    aplicar: Callable[[OpcoesDoEspectro, float | None], OpcoesDoEspectro]
    segue: Callable[[OpcoesDoEspectro, float | None], bool]
    dica: str = ""


REDE_PADRAO_HZ = 60.0
"""A rede suposta enquanto a fundamental não foi medida: a brasileira."""


def ciclos_da_iec(f1_hz: float | None) -> int:
    """Os ciclos da janela de medição da IEC 61000-4-7 (~200 ms): 10 numa rede de 50 Hz, 12 numa de 60 Hz. Sem a
    fundamental medida, os da rede de :data:`REDE_PADRAO_HZ`."""
    f1 = f1_hz if f1_hz is not None and math.isfinite(f1_hz) else REDE_PADRAO_HZ
    return 10 if f1 < 55.0 else 12


def _aplicar_iec(opcoes: OpcoesDoEspectro, f1_hz: float | None) -> OpcoesDoEspectro:
    return opcoes.com(metodo="fft", modo="tom", janela=None, ciclos=ciclos_da_iec(f1_hz))


def _segue_a_iec(opcoes: OpcoesDoEspectro, f1_hz: float | None) -> bool:
    return (opcoes.metodo, opcoes.modo, opcoes.janela, opcoes.ciclos) == ("fft", "tom", None, ciclos_da_iec(f1_hz))


def _descrever_iec(f1_hz: float | None) -> str:
    n = ciclos_da_iec(f1_hz)
    return f"{n} ciclos de {50 if n == 10 else 60} Hz (~200 ms), janela retangular sincronizada"


IEC_61000_4_7 = PresetDoEspectro(
    "IEC 61000-4-7", _descrever_iec, _aplicar_iec, _segue_a_iec,
    dica="A janela de medição da IEC 61000-4-7 (a mesma da IEC 61000-4-30 classe A): 10 ciclos numa rede de 50 Hz, 12 "
         "numa de 60 Hz (~200 ms), retangular e sincronizada com a fundamental, a partir do começo do trecho. Sem "
         "sincronismo, a norma admite a Hann, e é o que a FFT faz quando não acha a fundamental (com um aviso).")
PRESETS_DO_ESPECTRO = (IEC_61000_4_7,)


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
    """O espectro do traço no trecho (ver o começo do módulo). A FFT sincronizada num trecho sem a fundamental vira a
    FFT do trecho inteiro, sem sincronizar (com um aviso). Levanta ``api.ErroSHAN`` com o motivo, e
    :class:`AguardandoMaterializacao`."""
    try:
        return _espectro_do_trecho(trecho, parametros, progresso=progresso, cancelado=cancelado)
    except api.ErroSHAN:
        if not parametros.sincronizada or trecho.n_amostras < 2 or trecho.ganho == 0:
            raise
    livre = replace(parametros, sincronizar=False)
    espectro = _espectro_do_trecho(trecho, livre, progresso=progresso, cancelado=cancelado)
    aviso = api.Aviso("aviso", f"sem a fundamental de {parametros.freq_min_fundamental:g} a "
                               f"{parametros.freq_max_fundamental:g} Hz no trecho para sincronizar: a FFT do trecho "
                               f"inteiro, com a janela {espectro.rotulo_janela}")
    return replace(espectro, avisos=(*espectro.avisos, aviso))


def _espectro_do_trecho(trecho: TrechoDoTraco, parametros: api.ParametrosEspectro, *, progresso, cancelado):
    canal = trecho.captura.canal(trecho.numero)
    if parametros.sincronizada and parametros.n_ciclos:
        # Os 12 ciclos da IEC numa captura de uma hora: o começo do trecho basta (e cabe na FFT).
        basta = math.ceil((parametros.n_ciclos + FOLGA_DE_CICLOS) * canal.taxa_hz / parametros.freq_min_fundamental)
        trecho = replace(trecho, fim=min(trecho.fim, trecho.inicio + basta))
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
    """Os ``n_picos`` mais altos acima do piso + 20 dB e com 10 dB de proeminência (de 2 kHz à Nyquist), o piso e, com
    a FFT sincronizada, os harmônicos de f₁ até ``ordem_maxima`` abaixo da Nyquist."""
    nyquist = espectro.taxa_hz / 2.0
    piso = espectro.piso(CORTE_DOS_PICOS) if nyquist > CORTE_DOS_PICOS else espectro.piso(0.0)
    achados: tuple[api.Pico, ...] = ()
    if n_picos and math.isfinite(piso) and nyquist > CORTE_DOS_PICOS:
        achados = api.picos(espectro, piso + ACIMA_DO_PISO_DB, maximo=n_picos, proeminencia_db=PROEMINENCIA_DOS_PICOS_DB)
    f0 = espectro.f0_hz
    frequencias = tuple(h * f0 for h in range(2, ordem_maxima + 1) if h * f0 < nyquist) if harmonicos and f0 else ()
    return Marcas(achados, piso, frequencias)


# ---------------------------------------------------------------------------
# O desenho de um espectro: os níveis na escala, a pirâmide e as marcas, preparados fora da tela
# ---------------------------------------------------------------------------

@dataclass(frozen=True, eq=False)
class Desenho:
    """O que a vista precisa para desenhar um espectro de qualquer tamanho sem custo por quadro: os níveis na escala
    mostrada, a pirâmide mín/máx deles (a mesma da vista de tempo: os bins são uniformes em frequência, e um pico de
    um bin aparece em qualquer zoom), as marcas e a grade (o bin ``i`` está em ``f0 + i·df``)."""

    niveis: np.ndarray
    piramide: Piramide
    marcas: Marcas
    f0: float
    df: float

    def indice(self, frequencia_hz: float) -> int:
        """O bin mais perto de ``frequencia_hz`` (sem procurar: a grade é uniforme)."""
        return int(min(max(round((frequencia_hz - self.f0) / self.df), 0), len(self.niveis) - 1))

    def nivel_em(self, frequencia_hz: float) -> float:
        return float(self.niveis[self.indice(frequencia_hz)])


def preparar_desenho(espectro: api.Espectro, escala: str, n_picos: int, harmonicos: bool) -> Desenho:
    """Os níveis de ``espectro`` na ``escala``, a pirâmide deles e as marcas: as contas que custam O(bins), feitas uma
    vez (na thread de trabalho), e não a cada quadro."""
    niveis = np.ascontiguousarray(espectro.niveis(escala), dtype=np.float64)
    df = float(espectro.freqs_hz[1] - espectro.freqs_hz[0]) if len(espectro.freqs_hz) > 1 else 1.0
    return Desenho(niveis, construir(niveis)[0], marcas(espectro, n_picos, harmonicos), float(espectro.freqs_hz[0]),
                   df)


def envoltoria_log(desenho: Desenho, f_min: float, f_max: float, colunas: int) -> tuple[np.ndarray, np.ndarray]:
    """O traço de um espectro na frequência logarítmica entre ``f_min`` e ``f_max``, em ``colunas`` colunas de
    pixel: as colunas com um bin só passam por ele; as com vários, pelo mínimo e pelo máximo deles (nada some, nem um
    pico de um bin). Sem o DC. Custa O(bins visíveis), e não depende do zoom."""
    n = len(desenho.niveis)
    f_min, f_max = max(f_min, desenho.f0 + desenho.df), max(f_max, f_min * (1 + 1e-9))
    bordas_f = np.geomspace(f_min, f_max, max(2, colunas) + 1)
    bordas = np.clip(np.ceil((bordas_f - desenho.f0) / desenho.df).astype(np.int64), 1, n)
    bordas = np.unique(bordas)
    if len(bordas) < 2:
        i = desenho.indice(f_min)
        return np.array([desenho.f0 + i * desenho.df]), desenho.niveis[i:i + 1].copy()
    trecho = desenho.niveis[bordas[0]:bordas[-1]]
    relativas = bordas[:-1] - bordas[0]
    minimos = np.minimum.reduceat(trecho, relativas)
    maximos = np.maximum.reduceat(trecho, relativas)
    tamanhos = np.diff(bordas)
    centros = desenho.f0 + desenho.df * (bordas[:-1] + (tamanhos - 1) / 2.0)
    um = tamanhos == 1
    x = np.repeat(centros, np.where(um, 1, 2))
    y = np.empty(len(x))
    posicao = np.concatenate([[0], np.cumsum(np.where(um, 1, 2))[:-1]])
    y[posicao] = np.where(um, maximos, minimos)
    varios = ~um
    y[posicao[varios] + 1] = maximos[varios]
    return x, y


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
