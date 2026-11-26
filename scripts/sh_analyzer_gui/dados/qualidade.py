"""A qualidade de energia e os eventos de um traço (F7.5 e F7.6; docs/gui-progress.md, 4h), sem Qt.

**Os índices** (:func:`indices`) seguem a IEC 61000-4-30 (classe A, onde dá): a janela de medição é de 10 ciclos numa
rede de 50 Hz e de 12 numa de 60 Hz (~200 ms), **sincronizada** com a fundamental (os cruzamentos por zero do motor,
``api.cruzamentos_da_fundamental``); em cada uma, a frequência (os ciclos ÷ o tempo deles), o RMS, a FFT retangular
dos ciclos inteiros (os harmônicos caem nos bins h·N), e daí o THD (até a 40ª, a IEC 61000-4-7), o fator K (o da
corrente: Σh²·I²ₕ ÷ ΣI²ₕ, até a 50ª), o fator de crista (o pico ÷ o RMS), o fator de forma (o RMS ÷ a média do módulo)
e o RMS das faixas de 2 a 9 kHz e de 9 a 150 kHz (os supraharmônicos, a soma da potência dos bins da faixa). **A
agregação** de 150/180 ciclos (~3 s) junta 15 janelas: o RMS das grandezas de RMS, a média das outras. **As
estatísticas** de cada índice: o mínimo, a média, o P95, o P99 e o máximo das janelas.

**Os eventos** (:func:`eventos`):

* **afundamentos, elevações e interrupções**: o RMS de um ciclo atualizado a cada meio ciclo (o U_rms(½) da norma)
  contra a tensão de referência (a dada, ou a mediana do trecho): abaixo de 90 % é um afundamento, abaixo de 5 % uma
  interrupção, acima de 110 % uma elevação; o fim, quando volta para dentro com a histerese de 2 %;
* **os picos de supraharmônicos**: as janelas de 200 ms em que o RMS de 2 a 9 kHz ou o de 9 a 150 kHz passa de 10×
  (20 dB) a mediana dele (as janelas vizinhas juntas num evento só);
* **a saturação**: as sequências de amostras no menor ou no maior código do ADC (só no traço sem cadeia);
* **as descontinuidades**: os saltos de uma amostra para a outra maiores que 8 desvios robustos da diferença (o
  desvio pela mediana do módulo, que um salto não puxa, e nunca menor que o degrau do ADC) e que não seguem a forma
  de onda;
* **o cabeçalho**: os buffers sobrescritos e as amostras atrasadas que o ``ler_adc`` contou (sem o instante).

A captura inteira não vai para a memória: o trecho é lido em pedaços de :data:`PEDACO` amostras, com a sobreposição de
alguns ciclos (os cruzamentos de um pedaço não dependem da borda dele).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import supraharmonicos.api as api

from .espectros import INDICES_DE_QUALIDADE, LIMITE_DA_CADEIA, AguardandoMaterializacao, TrechoDoTraco
from .materializacao import leitor_do_canal

PEDACO = 1 << 21
"""As amostras de cada pedaço lido (~10 s a 200 kS/s)."""
SOBRA_EM_CICLOS = 3
PEDACO_MINIMO_S = (2 * 12 + 2 * SOBRA_EM_CICLOS) / 45.0
"""O menor pedaço: duas janelas e as sobras dos dois lados na menor fundamental (45 Hz)."""
ORDEM_DO_THD = 40
ORDEM_DO_FATOR_K = 50
JANELAS_DA_AGREGACAO = 15
FAIXAS_SUPRA = ((2_000.0, 9_000.0), (9_000.0, 150_000.0))
LIMIAR_DO_AFUNDAMENTO = 0.90
LIMIAR_DA_INTERRUPCAO = 0.05
LIMIAR_DA_ELEVACAO = 1.10
HISTERESE = 0.02
FATOR_DO_PICO_SUPRA = 10.0
DESVIOS_DO_SALTO = 8.0
INDICES = INDICES_DE_QUALIDADE
NOMES_DOS_INDICES = {"frequencia": "Frequência", "rms": "RMS", "thd": "THD", "fator_k": "Fator K",
                     "crista": "Fator de crista", "forma": "Fator de forma", "supra_2_9k": "RMS de 2 a 9 kHz",
                     "supra_9_150k": "RMS de 9 a 150 kHz"}
INDICES_DE_RMS = ("rms", "supra_2_9k", "supra_9_150k")


def ler(trecho: TrechoDoTraco, a: int, b: int) -> np.ndarray:
    """Os valores do traço nas amostras ``[a, b)`` do canal (``float64``, com o ganho e o offset)."""
    canal = trecho.captura.canal(trecho.numero)
    if trecho.cadeia.vazia:
        return np.asarray(canal.amostras[a:b], dtype=np.float64) * (canal.escala * trecho.ganho) + (
            canal.deslocamento * trecho.ganho + trecho.offset)
    if trecho.n_amostras <= LIMITE_DA_CADEIA:
        valores = trecho.cadeia.previa(leitor_do_canal(trecho.captura, trecho.numero), len(canal.amostras), a, b,
                                       trecho.contexto).valores
        return valores * trecho.ganho + trecho.offset
    if trecho.materializada is None:
        raise AguardandoMaterializacao()
    return np.asarray(trecho.materializada[a:b], dtype=np.float64) * trecho.ganho + trecho.offset


# ------------------------------------------------------------------ os índices (F7.6)


@dataclass(frozen=True)
class EstatisticaDoIndice:
    minimo: float
    media: float
    p95: float
    p99: float
    maximo: float


@dataclass(frozen=True)
class IndicesDeQualidade:
    """Os índices de cada janela de 10/12 ciclos (``inicios_s``: o começo de cada uma, no tempo do canal, em s, a
    partir do começo da captura) e os agregados de 150/180 ciclos; ``ciclos_por_janela``: 10 ou 12."""

    inicios_s: np.ndarray
    valores: dict[str, np.ndarray]
    agregados_s: np.ndarray
    agregados: dict[str, np.ndarray]
    ciclos_por_janela: int
    estatisticas: dict[str, EstatisticaDoIndice] = field(default_factory=dict)
    trechos_sem_fundamental: int = 0
    rms_meio_minimo: np.ndarray | None = None     # o menor e o maior RMS de meio ciclo em cada janela
    rms_meio_maximo: np.ndarray | None = None

    @property
    def n_janelas(self) -> int:
        return len(self.inicios_s)

    def marcadas(self, referencia: float | None = None) -> np.ndarray:
        """As janelas marcadas (o *flagging* da IEC 61000-4-30): as que têm um RMS de meio ciclo abaixo de 90 % ou
        acima de 110 % da referência (a dada, ou a mediana do RMS das janelas), num afundamento, numa elevação ou numa
        interrupção. A norma tira os valores delas das estatísticas, e marca os agregados que as incluem: a
        frequência, o THD e os outros índices de uma janela com um degrau na tensão não descrevem a rede."""
        vazio = np.zeros(self.n_janelas, dtype=bool)
        if self.rms_meio_minimo is None or not self.n_janelas:
            return vazio
        ref = referencia or float(np.nanmedian(self.valores["rms"]))
        if not ref > 0:
            return vazio
        with np.errstate(invalid="ignore"):
            return (self.rms_meio_minimo < LIMIAR_DO_AFUNDAMENTO * ref) | (self.rms_meio_maximo > LIMIAR_DA_ELEVACAO * ref)

    def agregados_marcados(self, marcadas: np.ndarray) -> np.ndarray:
        """Os agregados que incluem uma janela marcada."""
        n_ag = len(self.agregados_s)
        if not n_ag:
            return np.zeros(0, dtype=bool)
        return marcadas[:n_ag * JANELAS_DA_AGREGACAO].reshape(n_ag, JANELAS_DA_AGREGACAO).any(axis=1)

    def estatisticas_de(self, manter: np.ndarray) -> dict[str, EstatisticaDoIndice]:
        """As estatísticas só das janelas de ``manter`` (as não marcadas, por exemplo)."""
        return {nome: _estatistica(v[manter]) for nome, v in self.valores.items()}


def _estatistica(x: np.ndarray) -> EstatisticaDoIndice:
    x = x[np.isfinite(x)]
    if not len(x):
        return EstatisticaDoIndice(*(math.nan,) * 5)
    return EstatisticaDoIndice(float(np.min(x)), float(np.mean(x)), float(np.percentile(x, 95)),
                               float(np.percentile(x, 99)), float(np.max(x)))


def _indices_da_janela(x: np.ndarray, n_ciclos: int, duracao_s: float, taxa_hz: float) -> dict[str, float]:
    n = len(x)
    rms = math.sqrt(float(np.mean(x * x)))
    espectro = np.fft.rfft(x) / n
    potencia = np.abs(espectro) ** 2 * 2.0                     # o RMS² de cada componente (sem o DC)
    potencia[0] = abs(espectro[0]) ** 2
    harmonicos = np.array([potencia[h * n_ciclos] if h * n_ciclos < len(potencia) else 0.0
                           for h in range(1, ORDEM_DO_FATOR_K + 1)])
    h1 = harmonicos[0]
    thd = math.sqrt(float(np.sum(harmonicos[1:ORDEM_DO_THD]))) / math.sqrt(h1) if h1 > 0 else math.nan
    ordens = np.arange(1, ORDEM_DO_FATOR_K + 1)
    fator_k = float(np.sum(ordens ** 2 * harmonicos) / np.sum(harmonicos)) if np.sum(harmonicos) > 0 else math.nan
    media_abs = float(np.mean(np.abs(x)))
    resolucao = 1.0 / duracao_s
    faixas = []
    for f0, f1 in FAIXAS_SUPRA:
        i0, i1 = math.ceil(f0 / resolucao), math.floor(min(f1, taxa_hz / 2) / resolucao)
        faixas.append(math.sqrt(float(np.sum(potencia[i0:i1 + 1]))) if i1 >= i0 else math.nan)
    return {"frequencia": n_ciclos / duracao_s, "rms": rms, "thd": thd, "fator_k": fator_k,
            "crista": float(np.max(np.abs(x))) / rms if rms > 0 else math.nan,
            "forma": rms / media_abs if media_abs > 0 else math.nan,
            "supra_2_9k": faixas[0], "supra_9_150k": faixas[1]}


def _cruzamentos(x: np.ndarray, taxa_hz: float) -> tuple[np.ndarray, float]:
    return api.cruzamentos_da_fundamental(x, taxa_hz, api.FREQ_MIN_FUNDAMENTAL, api.FREQ_MAX_FUNDAMENTAL)


def indices(trecho: TrechoDoTraco, *, progresso: Callable[[float], None] | None = None,
            cancelado: Callable[[], bool] | None = None, pedaco: int | None = None) -> IndicesDeQualidade:
    """Os índices de qualidade do trecho (ver o começo do módulo). Levanta ``api.ErroSHAN`` sem a fundamental.

    Os pedaços: cada um começa uns ciclos antes do cruzamento em que a próxima janela começa (``alvo``), e as janelas
    seguem do cruzamento dele mais perto do alvo; as janelas ficam contíguas, como na norma."""
    taxa = trecho.captura.canal(trecho.numero).taxa_hz
    pedaco = max(pedaco or PEDACO, int(math.ceil(PEDACO_MINIMO_S * taxa)))
    a, fim = trecho.inicio, trecho.fim
    if fim - a < 4:
        raise api.ErroSHAN("o trecho é curto demais para os índices de qualidade")
    inicios, linhas, extremos = [], [], []
    sem_fundamental = 0
    n_ciclos = None
    pos, alvo, continua = a, float(a), False
    while pos < fim:
        if cancelado is not None and cancelado():
            raise api.Cancelado()
        b = min(fim, pos + pedaco)
        x = ler(trecho, pos, b)
        try:
            cruz, f1 = _cruzamentos(x, taxa)
        except api.ErroSHAN:
            sem_fundamental += 1
            pos, alvo, continua = b, float(b), False
            continue
        if n_ciclos is None:
            n_ciclos = 12 if f1 > 55.0 else 10
        if continua:
            k = int(np.argmin(np.abs(cruz - (alvo - pos))))
        else:
            k = int(np.searchsorted(cruz, alvo - pos))
        # O fim do pedaço tem o transitório do filtro dos cruzamentos (sosfiltfilt): as janelas param umas sobras
        # antes dele, e o pedaço seguinte as refaz desde o alvo.
        sobra = int(SOBRA_EM_CICLOS * taxa / max(f1, 1.0))
        limite = len(x) if b >= fim else len(x) - sobra
        usados = None
        fins_meio, rms_meio = _rms_de_meio_ciclo(x, cruz)
        while k + n_ciclos < len(cruz) and cruz[k + n_ciclos] <= limite:
            i0, i1 = int(round(cruz[k])), int(round(cruz[k + n_ciclos]))
            duracao = (cruz[k + n_ciclos] - cruz[k]) / taxa
            linhas.append(_indices_da_janela(x[i0:i1], n_ciclos, duracao, taxa))
            inicios.append((pos + cruz[k]) / taxa)
            j0, j1 = np.searchsorted(fins_meio, [cruz[k], cruz[k + n_ciclos]], side="right")
            meio = rms_meio[j0:j1]
            extremos.append((float(np.min(meio)), float(np.max(meio))) if len(meio) else (math.nan, math.nan))
            usados = k + n_ciclos
            k += n_ciclos
        if b >= fim:
            break
        if usados is None:
            pos, alvo, continua = b, float(b), False
            continue
        alvo = pos + float(cruz[usados])
        pos, continua = max(pos + 1, int(math.floor(alvo)) - sobra), True
        if progresso is not None:
            progresso((pos - a) / (fim - a))
    if not linhas:
        raise api.ErroSHAN("o trecho não tem uma fundamental de 45 a 65 Hz: os índices de qualidade precisam dela")
    return _montar(np.array(inicios), linhas, n_ciclos, sem_fundamental, np.array(extremos))


def _montar(inicios: np.ndarray, linhas: list[dict], n_ciclos: int, sem_fundamental: int,
            extremos: np.ndarray) -> IndicesDeQualidade:
    valores = {nome: np.array([linha[nome] for linha in linhas]) for nome in INDICES}
    n_ag = len(inicios) // JANELAS_DA_AGREGACAO
    agregados = {}
    for nome, v in valores.items():
        blocos = v[:n_ag * JANELAS_DA_AGREGACAO].reshape(n_ag, JANELAS_DA_AGREGACAO) if n_ag else np.zeros((0, 1))
        agregados[nome] = (np.sqrt(np.mean(blocos ** 2, axis=1)) if nome in INDICES_DE_RMS
                           else np.mean(blocos, axis=1))
    agregados_s = inicios[:n_ag * JANELAS_DA_AGREGACAO:JANELAS_DA_AGREGACAO] if n_ag else np.zeros(0)
    estatisticas = {nome: _estatistica(v) for nome, v in valores.items()}
    return IndicesDeQualidade(inicios, valores, agregados_s, agregados, n_ciclos, estatisticas, sem_fundamental,
                              extremos[:, 0].copy(), extremos[:, 1].copy())


# ------------------------------------------------------------------ os eventos (F7.5)


TIPOS_DE_EVENTO = {"afundamento": "Afundamento", "elevacao": "Elevação", "interrupcao": "Interrupção",
                   "supraharmonicos": "Pico de supraharmônicos", "saturacao": "Saturação",
                   "descontinuidade": "Descontinuidade", "cabecalho": "Registro do ler_adc"}


@dataclass(frozen=True)
class Evento:
    """Um evento: o tipo (:data:`TIPOS_DE_EVENTO`), o começo e a duração (s, no tempo do canal desde o começo da
    captura; NaN no do cabeçalho, sem instante), o valor que o caracteriza (a tensão residual de um afundamento, a de
    pico de uma elevação, o RMS da faixa, o salto) e o texto."""

    tipo: str
    inicio_s: float
    duracao_s: float
    valor: float
    detalhe: str = ""


@dataclass(frozen=True)
class CriteriosDosEventos:
    referencia: float | None = None       # a tensão de referência (None: a mediana do RMS de ½ ciclo do trecho)
    tensao: bool = True                    # procurar afundamentos, elevações e interrupções (o traço é uma tensão)


def _rms_de_meio_ciclo(x: np.ndarray, cruz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """O RMS de um ciclo, atualizado a cada meio ciclo (os meios ciclos entre os cruzamentos subindo): os instantes
    (o fim de cada janela, em amostras de ``x``) e os valores."""
    meios = np.sort(np.concatenate([cruz, (cruz[:-1] + cruz[1:]) / 2]))
    if len(meios) < 3:
        return np.zeros(0), np.zeros(0)
    quadrados = np.concatenate([[0.0], np.cumsum(np.asarray(x, dtype=np.float64) ** 2)])
    idx = np.clip(np.round(meios).astype(np.int64), 0, len(x))
    a, b = idx[:-2], idx[2:]
    validos = b > a
    a, b = a[validos], b[validos]
    return meios[2:][validos], np.sqrt(np.maximum(quadrados[b] - quadrados[a], 0.0) / (b - a))


def _numero(valor: float, casas: int) -> str:
    return f"{valor:.{casas}f}"


def _eventos_de_tensao(instantes_s: np.ndarray, rms: np.ndarray, referencia: float,
                       numero: Callable[[float, int], str] = _numero) -> list[Evento]:
    eventos = []
    estado, inicio, extremo = None, 0.0, 0.0
    for t, v in zip(instantes_s, rms):
        r = v / referencia
        if estado is None:
            if r < LIMIAR_DA_INTERRUPCAO:
                estado, inicio, extremo = "interrupcao", t, v
            elif r < LIMIAR_DO_AFUNDAMENTO:
                estado, inicio, extremo = "afundamento", t, v
            elif r > LIMIAR_DA_ELEVACAO:
                estado, inicio, extremo = "elevacao", t, v
            continue
        if estado == "afundamento" and r < LIMIAR_DA_INTERRUPCAO:
            estado = "interrupcao"
        if estado in ("afundamento", "interrupcao"):
            extremo = min(extremo, v)
            terminou = r >= LIMIAR_DO_AFUNDAMENTO + HISTERESE
        else:
            extremo = max(extremo, v)
            terminou = r <= LIMIAR_DA_ELEVACAO - HISTERESE
        if terminou:
            eventos.append(Evento(estado, inicio, t - inicio, extremo,
                                  f"{numero(100 * extremo / referencia, 1)} % da referência"))
            estado = None
    if estado is not None:
        eventos.append(Evento(estado, inicio, float(instantes_s[-1]) - inicio, extremo,
                              f"{numero(100 * extremo / referencia, 1)} % da referência (até o fim do trecho)"))
    return eventos


def _sequencias(mascara: np.ndarray) -> list[tuple[int, int]]:
    """As sequências de verdadeiros: ``(início, fim)`` em amostras."""
    if not mascara.any():
        return []
    d = np.diff(np.concatenate([[0], mascara.astype(np.int8), [0]]))
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]))


def eventos(trecho: TrechoDoTraco, opcoes: CriteriosDosEventos = CriteriosDosEventos(), *,
            indices_prontos: IndicesDeQualidade | None = None, progresso=None, cancelado=None,
            pedaco: int | None = None, numero: Callable[[float, int], str] = _numero) -> list[Evento]:
    """Os eventos do trecho, em ordem de tempo (ver o começo do módulo). ``numero(valor, casas)`` escreve os números
    dos detalhes (a interface passa o dela, com o separador decimal das configurações)."""
    pedaco = pedaco or PEDACO
    canal = trecho.captura.canal(trecho.numero)
    taxa = canal.taxa_hz
    a, fim = trecho.inicio, trecho.fim
    lista: list[Evento] = []
    instantes, rms = [], []
    saltos = []
    codigos = None if not trecho.cadeia.vazia else canal.amostras
    lsb = abs(canal.escala * trecho.ganho) if trecho.cadeia.vazia else 0.0      # o degrau do ADC, na unidade do traço
    baixo = alto = None
    if codigos is not None and np.issubdtype(codigos.dtype, np.integer):
        info = np.iinfo(codigos.dtype)
        baixo, alto = info.min, info.max
    ultimo_fim = None
    for pos in range(a, fim, pedaco):
        if cancelado is not None and cancelado():
            raise api.Cancelado()
        b = min(fim, pos + pedaco)
        sobra = int(SOBRA_EM_CICLOS * taxa / 45.0)
        p0 = max(a, pos - sobra)
        x = ler(trecho, p0, b)
        if opcoes.tensao:
            try:
                cruz, _f1 = _cruzamentos(x, taxa)
                fins, valores = _rms_de_meio_ciclo(x, cruz)
                novos = (p0 + fins) / taxa
                manter = novos > (ultimo_fim if ultimo_fim is not None else -math.inf)
                instantes.extend(novos[manter])
                rms.extend(valores[manter])
                if len(novos):
                    ultimo_fim = float(novos[-1])
            except api.ErroSHAN:
                pass
        if baixo is not None:
            parte = np.asarray(codigos[pos:b])
            for i0, i1 in _sequencias((parte == baixo) | (parte == alto)):
                lista.append(Evento("saturacao", (pos + i0) / taxa, (i1 - i0) / taxa,
                                    float(i1 - i0), f"{i1 - i0} amostra(s) no fundo de escala"))
        d = np.diff(x[pos - p0 - 1 if pos > a else 0:])
        if len(d) > 2:
            d2 = np.diff(d)                                        # o salto que não segue a forma de onda
            desvio = 1.4826 * float(np.median(np.abs(d2 - np.median(d2)))) or float(np.std(d2)) or 1e-30
            # Num sinal lento e quantizado, quase toda segunda diferença é 0 LSB e o desvio robusto vai a zero:
            # sem um piso, cada degrau de quantização virava um salto (19 161 num segundo a 0,8 V de pico).
            desvio = max(desvio, lsb)
            for j in np.nonzero(np.abs(d2) > DESVIOS_DO_SALTO * 3 * desvio)[0]:
                saltos.append(((pos if pos > a else p0) + j + 1, float(d[j + 1] if j + 1 < len(d) else d[j])))
        if progresso is not None:
            progresso((b - a) / (fim - a))
    if opcoes.tensao and len(rms):
        rms_arr, t_arr = np.array(rms), np.array(instantes)
        referencia = opcoes.referencia or float(np.median(rms_arr))
        if referencia > 0:
            lista.extend(_eventos_de_tensao(t_arr, rms_arr, referencia, numero))
    # os saltos vizinhos (o mesmo degrau visto por duas diferenças) viram um só
    ultimo = -10
    for amostra, salto in sorted(saltos):
        if amostra - ultimo > 2:
            lista.append(Evento("descontinuidade", amostra / taxa, 0.0, salto, "um salto fora da forma de onda"))
        ultimo = amostra
    q = indices_prontos
    if q is not None and q.n_janelas:
        # as janelas marcadas (um degrau na tensão espalha a fundamental pelo espectro) ficam de fora
        marcadas = q.marcadas(opcoes.referencia) if opcoes.tensao else np.zeros(q.n_janelas, dtype=bool)
        for nome in ("supra_9_150k", "supra_2_9k"):
            v = np.where(marcadas, np.nan, q.valores[nome])
            mediana = float(np.nanmedian(v)) if np.isfinite(v).any() else math.nan
            if not mediana > 0:
                continue
            # as janelas vizinhas acima do limiar são um evento só: do começo da primeira ao fim da última
            duracoes = q.ciclos_por_janela / q.valores["frequencia"]
            with np.errstate(invalid="ignore"):
                acima = v > FATOR_DO_PICO_SUPRA * mediana
            for k0, k1 in _sequencias(acima):
                pico = float(np.max(v[k0:k1]))
                inicio = float(q.inicios_s[k0])
                lista.append(Evento("supraharmonicos", inicio, float(q.inicios_s[k1 - 1] + duracoes[k1 - 1]) - inicio,
                                    pico, f"{NOMES_DOS_INDICES[nome]}: {numero(pico / mediana, 1)}× a mediana "
                                          f"({k1 - k0} janela(s))"))
    cab = trecho.captura.cabecalho
    for campo, texto in (("buffers_sobrescritos", "buffer(s) sobrescrito(s): amostras perdidas"),
                         ("amostras_atrasadas", "amostra(s) atrasada(s): a PRU não acompanhou a taxa")):
        n = getattr(cab, campo, None) if cab is not None else None
        if n:
            lista.append(Evento("cabecalho", math.nan, math.nan, float(n), f"{n} {texto}"))
    return sorted(lista, key=lambda e: (math.isnan(e.inicio_s), e.inicio_s))


# ------------------------------------------------------------------ a transferência (F7.7)

PEDACO_DA_TRANSFERENCIA = 1 << 20
"""As amostras de cada pedaço lido na transferência (os segmentos inteiros que cabem nele)."""
SOBREPOSICAO_DO_HANN = 0.167
"""A correlação entre segmentos vizinhos da Hann com 50 % de sobreposição (Welch, 1967): ν ≈ 2K / (1 + 2c²)."""


def medias_equivalentes(medias: int) -> float:
    """As médias independentes que valem ``medias`` segmentos da Hann com 50 % de sobreposição: ν/2."""
    return medias / (1 + 2 * SOBREPOSICAO_DO_HANN ** 2)


@dataclass(frozen=True)
class Transferencia:
    """A função de transferência H₁ = P_xy / P_xx (a saída ``y`` sobre a entrada ``x``), a coerência, a densidade
    espectral cruzada e as das duas (V²/Hz, de um lado), pelo Welch (Hann, 50 % de sobreposição, a média de cada
    segmento tirada), com ``medias`` segmentos de ``amostras_por_segmento``."""

    frequencias: np.ndarray
    h: np.ndarray
    coerencia: np.ndarray
    pxy: np.ndarray
    pxx: np.ndarray
    pyy: np.ndarray
    medias: int
    amostras_por_segmento: int = 0

    @property
    def magnitude_db(self) -> np.ndarray:
        with np.errstate(divide="ignore"):
            return 20 * np.log10(np.abs(self.h))

    @property
    def fase_graus(self) -> np.ndarray:
        return np.degrees(np.angle(self.h))

    def intervalo(self, confianca: float = 0.95) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """O intervalo de confiança de H₁ em cada frequência: |H| mínimo e máximo (dB; −∞ quando o círculo de
        confiança passa pela origem) e a meia largura da fase (°; 180 quando passa). O círculo em volta de Ĥ tem o raio
        r² = 2/(n−2) · F₂,ₙ₋₂(confiança) · (1 − γ²)/γ² · |Ĥ|² (Bendat e Piersol, *Random Data*, 4ª ed., 9.2.4), com
        n as médias independentes (:func:`medias_equivalentes`). Vale para o ruído na saída, não na entrada."""
        from scipy.stats import f as distribuicao_f

        n = medias_equivalentes(self.medias)
        vazio = np.full(len(self.h), np.nan)
        if n <= 2.0:
            return vazio, vazio.copy(), vazio.copy()
        g2 = np.clip(self.coerencia, 1e-12, 1.0)
        modulo = np.abs(self.h)
        raio = np.sqrt(2.0 / (n - 2.0) * distribuicao_f.ppf(confianca, 2, n - 2.0) * (1.0 - g2) / g2) * modulo
        with np.errstate(divide="ignore", invalid="ignore"):
            baixo = np.where(modulo > raio, 20 * np.log10(np.maximum(modulo - raio, 1e-300)), -np.inf)
            alto = 20 * np.log10(modulo + raio)
            fase = np.where(modulo > raio, np.degrees(np.arcsin(np.clip(raio / modulo, 0.0, 1.0))), 180.0)
        return baixo, alto, fase


def transferencia(x: np.ndarray, y: np.ndarray, taxa_hz: float, resolucao_hz: float) -> Transferencia:
    """H₁, a coerência e as densidades de ``x`` (a entrada) e ``y`` (a saída), com segmentos de ``taxa/resolução``
    amostras: os mesmos números do ``scipy.signal.welch``/``csd`` (Hann, 50 %, ``detrend="constant"``). Levanta
    ``api.ErroSHAN`` com menos de dois segmentos."""
    if len(x) != len(y):
        raise api.ErroSHAN(f"a entrada e a saída têm tamanhos diferentes ({len(x)} e {len(y)} amostras)")
    x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    return _transferencia(lambda i, j: x[i:j], lambda i, j: y[i:j], len(x), taxa_hz, resolucao_hz)


def transferencia_do_trecho(entrada: TrechoDoTraco, saida: TrechoDoTraco, resolucao_hz: float, *,
                            progresso: Callable[[float], None] | None = None,
                            cancelado: Callable[[], bool] | None = None,
                            pedaco: int | None = None) -> Transferencia:
    """A transferência da entrada para a saída, lidas em pedaços (a captura inteira não vai para a memória); os
    dois trechos começam no mesmo instante, e vale o tamanho do menor."""
    taxa = entrada.captura.canal(entrada.numero).taxa_hz
    m = min(entrada.n_amostras, saida.n_amostras)
    return _transferencia(lambda i, j: ler(entrada, entrada.inicio + i, entrada.inicio + j),
                          lambda i, j: ler(saida, saida.inicio + i, saida.inicio + j), m, taxa, resolucao_hz,
                          progresso=progresso, cancelado=cancelado, pedaco=pedaco)


def _transferencia(ler_x, ler_y, m: int, taxa_hz: float, resolucao_hz: float, *, progresso=None, cancelado=None,
                   pedaco: int | None = None) -> Transferencia:
    from numpy.lib.stride_tricks import sliding_window_view
    from scipy.signal import get_window

    if not resolucao_hz > 0:
        raise api.ErroSHAN("a resolução tem de ser positiva")
    n = int(round(taxa_hz / resolucao_hz))
    if n < 8:
        raise api.ErroSHAN("a resolução pedida é grossa demais para a taxa")
    if m < 2 * n:
        raise api.ErroSHAN(f"o trecho tem {m} amostras, e a resolução de {resolucao_hz:g} Hz pede pelo menos "
                           f"{2 * n} (dois segmentos)")
    passo = n - n // 2
    segmentos = 1 + (m - n) // passo
    janela = get_window("hann", n)
    por_pedaco = max(1, ((pedaco or PEDACO_DA_TRANSFERENCIA) - n) // passo + 1)
    sxx = np.zeros(n // 2 + 1)
    syy = np.zeros(n // 2 + 1)
    sxy = np.zeros(n // 2 + 1, dtype=np.complex128)
    for k0 in range(0, segmentos, por_pedaco):
        if cancelado is not None and cancelado():
            raise api.Cancelado()
        k1 = min(segmentos, k0 + por_pedaco)
        i, j = k0 * passo, (k1 - 1) * passo + n
        espectros = []
        for leitor in (ler_x, ler_y):
            partes = sliding_window_view(np.asarray(leitor(i, j), dtype=np.float64), n)[::passo]
            espectros.append(np.fft.rfft((partes - partes.mean(axis=1, keepdims=True)) * janela, axis=1))
        fx, fy = espectros
        sxx += np.sum(fx.real ** 2 + fx.imag ** 2, axis=0)
        syy += np.sum(fy.real ** 2 + fy.imag ** 2, axis=0)
        sxy += np.sum(np.conj(fx) * fy, axis=0)
        if progresso is not None:
            progresso(k1 / segmentos)
    escala = np.full(n // 2 + 1, 2.0 / (taxa_hz * float(np.sum(janela ** 2)) * segmentos))
    escala[0] /= 2
    if n % 2 == 0:
        escala[-1] /= 2
    pxx, pyy, pxy = sxx * escala, syy * escala, sxy * escala
    with np.errstate(divide="ignore", invalid="ignore"):
        h = pxy / pxx
        coerencia = (pxy.real ** 2 + pxy.imag ** 2) / (pxx * pyy)
    frequencias = np.fft.rfftfreq(n, 1.0 / taxa_hz)
    return Transferencia(frequencias, h, np.clip(np.nan_to_num(coerencia), 0.0, 1.0), pxy, pxx, pyy, segmentos, n)


def graus_de_liberdade_do_welch(janela: np.ndarray, passo: int, segmentos: int) -> float:
    """Os graus de liberdade ν de uma densidade do Welch com ``segmentos`` segmentos da ``janela``, um a cada
    ``passo`` amostras: ν = 2K / (1 + 2·Σⱼ (1 − j/K)·ρ(j)²), com ρ(j) a correlação da janela com ela mesma deslocada
    de j passos (Percival e Walden, *Spectral Analysis for Physical Applications*, 1993, 7.3). Na Hann com 50 %,
    ρ(1) = 1/6, a aproximação de :func:`medias_equivalentes`; sem sobreposição, ν = 2K."""
    w = np.asarray(janela, dtype=np.float64)
    n = len(w)
    energia = float(np.dot(w, w))
    if segmentos < 1 or not energia > 0:
        return math.nan
    soma, j = 0.0, 1
    while j < segmentos and j * passo < n:
        rho = float(np.dot(w[:n - j * passo], w[j * passo:])) / energia
        soma += (1.0 - j / segmentos) * rho ** 2
        j += 1
    return 2.0 * segmentos / (1.0 + 2.0 * soma)


def intervalo_de_confianca_db(medias: int, confianca: float = 0.95, *,
                              graus: float | None = None) -> tuple[float, float]:
    """O intervalo de confiança de uma densidade do Welch, em dB em volta da estimativa: com ν graus de liberdade
    (``graus``, de :func:`graus_de_liberdade_do_welch`; sem eles, a Hann com 50 % de sobreposição: ν =
    2·:func:`medias_equivalentes`), o verdadeiro fica entre ν·P/χ²(ν, 1−α/2) e ν·P/χ²(ν, α/2)."""
    from scipy.stats import chi2

    nu = graus if graus is not None else 2 * medias_equivalentes(medias)
    if not nu > 0:
        return math.nan, math.nan
    alfa = 1 - confianca
    return (10 * math.log10(nu / chi2.ppf(1 - alfa / 2, nu)), 10 * math.log10(nu / chi2.ppf(alfa / 2, nu)))


def intervalo_do_welch(espectro: api.Espectro, confianca: float = 0.95) -> tuple[float, float]:
    """O intervalo de confiança (dB) de cada bin de um espectro do Welch do motor: a janela, o segmento e o passo
    dele (a sobreposição), com os graus de liberdade de :func:`graus_de_liberdade_do_welch`. Vale para um bin de
    ruído (um processo aleatório); um tom estável varia muito menos."""

    p = espectro.parametros
    n = api.tamanho_segmento_welch(espectro.taxa_hz, p.resolucao_hz)
    passo = max(1, int(round(n * (1.0 - p.sobreposicao))))
    janela = api.obter_janela(espectro.janela, n, p.kaiser_beta)
    return intervalo_de_confianca_db(espectro.n_segmentos, confianca,
                                     graus=graus_de_liberdade_do_welch(janela, passo, espectro.n_segmentos))
