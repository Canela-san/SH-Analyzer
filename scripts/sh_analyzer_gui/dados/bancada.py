"""As métricas de bancada (F7.8, ME-05) e o assistente de aliasing (ES-06; docs/gui-progress.md, 4h), sem Qt.

**As métricas** (:func:`medir`) são as do ``medir_captura`` (``supraharmonicos.metricas_captura``), com as mesmas
contas e os mesmos padrões da CLI: as básicas (o DC, o RMS CA, o pico a pico, em LSB), a FFT única com a Kaiser β = 14
(o tom, os harmônicos dobrados para dentro da Nyquist, o THD, o SINAD, o SNR, o ENOB corrigido pelo fundo de escala,
o SFDR e a densidade do ruído), a continuidade (o salto de fase entre segmentos, em amostras), os saltos nas trocas de
buffer da PRU, o jitter da amostragem e os degraus de tempo nas trocas e nos rebases do contador. O trecho começa
depois do transitório da troca de faixa do ADS8688 (quando começa no começo da captura) e vai até
:data:`MAXIMO_DE_AMOSTRAS`, como na CLI.

**O aliasing** (:func:`aliasing`): duas a quatro capturas do mesmo sinal em taxas diferentes; os picos de cada uma
(o Welch, acima do piso), pareados pelo ``supraharmonicos.aliasing``: cada componente sai real, imagem (com a entrada
de onde veio) ou ambíguo. As amostras são as do pino do ADC (a sonda e a cadeia não entram: o filtro do ADC atenua
igual nas duas taxas, e as amplitudes têm de bater).

**A zona das imagens** (:func:`limite_das_imagens_hz`): o único anti-aliasing é o passa-baixa de 2ª ordem do ADS8688
(~15 kHz); acima do limite, uma entrada em fs − f chega ao espectro menos de 20 dB abaixo de uma real em f, e um pico
dali pode ser uma imagem.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import supraharmonicos.api as api
from supraharmonicos import aliasing as al
from supraharmonicos import metricas_captura as mc
from supraharmonicos.amostras import converter_para_tensao
from supraharmonicos.constantes import (
    CORTE_SUPRAHARMONICOS_PADRAO,
    DISTANCIA_MINIMA_PICOS_PADRAO,
    DURACAO_TRANSITORIO_FAIXA_S,
)

from .espectros import TrechoDoTraco
from .qualidade import ler

MAXIMO_DE_AMOSTRAS = 1 << 22
"""As amostras analisadas (≈ 10 s a 400 kS/s), o ``--max-amostras`` padrão do ``medir_captura``."""
SATURACAO_AVISO = 5e-4
"""A fração de amostras no fundo de escala acima da qual o THD e o SINAD perdem o sentido (a da CLI)."""
CORTE_DO_ADC_HZ = 15_000.0
ORDEM_DO_FILTRO_DO_ADC = 2
MARGEM_DAS_IMAGENS_DB = 20.0


@dataclass(frozen=True)
class MetricasDeBancada:
    """As métricas de um trecho (as classes do ``metricas_captura``), o LSB e o fundo de escala na unidade do traço,
    a fração saturada (NaN com cadeia: os códigos não dizem) e o trecho medido (``inicio``, em amostras do canal)."""

    basicas: mc.Basicas
    espectro: mc.Espectro
    continuidade: mc.Continuidade | None
    trocas: mc.TrocasBuffer | None
    jitter: mc.Jitter | None
    degraus_trocas: mc.Degraus | None
    degraus_rebases: mc.Degraus | None
    lsb: float
    fundo_de_escala: float
    saturacao: float
    inicio: int
    n_amostras: int
    taxa_hz: float
    avisos: tuple[str, ...] = ()


def medir(trecho: TrechoDoTraco, *, harmonicos: int = mc.HARMONICOS_PADRAO,
          cancelado: Callable[[], bool] | None = None) -> MetricasDeBancada:
    """As métricas de bancada do trecho (ver o começo do módulo). Levanta ``api.ErroSHAN`` num trecho curto."""
    canal = trecho.captura.canal(trecho.numero)
    fs = canal.taxa_hz
    inicio = trecho.inicio
    if inicio == 0:
        inicio = min(trecho.fim, math.ceil(DURACAO_TRANSITORIO_FAIXA_S * fs))     # o transitório da troca de faixa
    fim = min(trecho.fim, inicio + MAXIMO_DE_AMOSTRAS)
    if fim - inicio < mc.AMOSTRAS_MINIMAS:
        raise api.ErroSHAN(f"o trecho tem {fim - inicio} amostras: as métricas pedem pelo menos {mc.AMOSTRAS_MINIMAS}")
    avisos = []
    if trecho.fim > fim:
        avisos.append(f"só os primeiros {(fim - inicio) / fs:.3g} s do trecho ({MAXIMO_DE_AMOSTRAS} amostras, o "
                      "limite do medir_captura)")
    x = ler(trecho, inicio, fim)
    if cancelado is not None and cancelado():
        raise api.Cancelado()
    lsb = canal.escala * abs(trecho.ganho)
    fundo = lsb * 65536.0
    if trecho.cadeia.vazia and trecho.materializada is None:
        saturacao = mc.fracao_saturada(np.asarray(canal.amostras[inicio:fim]), canal.formato)
    else:
        saturacao = math.nan
        avisos.append("o traço passa por uma cadeia: o ruído, o SINAD e o ENOB descrevem o traço, não o ADC (para o "
                      "ADC, meça o canal sem cadeia)")
    if saturacao > SATURACAO_AVISO:
        avisos.append(f"{saturacao * 100:.3f} % das amostras no fundo de escala: a captura saturou, e a amplitude, o "
                      "THD e o SINAD não são confiáveis")
    basicas = mc.calcular_basicas(x, fs, lsb)
    espectro = mc.analisar_espectro(x, fs, None, harmonicos, fundo)
    if cancelado is not None and cancelado():
        raise api.Cancelado()
    cont = mc.verificar_continuidade(x, fs, espectro.freq_tom_hz) if espectro.tem_tom else None
    cab = trecho.captura.cabecalho
    n_canais = max(getattr(cab, "num_canais", 1) or 1, 1) if cab is not None else 1
    por_buffer = getattr(cab, "samples_per_buffer", 0) if cab is not None else 0
    trocas = None
    if cont is not None and por_buffer > 0:
        n = cont.segmentos * cont.amostras_por_segmento
        trocas = mc.comparar_trocas_de_buffer(cont, fs, mc.posicoes_das_trocas(por_buffer, n_canais, inicio, n))
    jitter = degraus_trocas = degraus_rebases = None
    if espectro.tem_tom and espectro.snr_db >= mc.SNR_MINIMO_GRADE_DB:
        jitter = mc.estimar_jitter(x, fs, espectro.freq_tom_hz)
        if por_buffer > 0:
            n = len(x)
            degraus_trocas = mc.medir_degraus_de_tempo(x, fs, espectro.freq_tom_hz,
                                                       mc.posicoes_das_trocas(por_buffer, n_canais, inicio, n))
            if getattr(cab, "versao_cabecalho", 0) >= 4:
                degraus_rebases = mc.medir_degraus_de_tempo(
                    x, fs, espectro.freq_tom_hz,
                    mc.posicoes_dos_rebases(cab.pru_clock_hz, cab.sample_period_ticks, n_canais, inicio, n))
    elif espectro.tem_tom:
        avisos.append(f"o jitter não foi medido: o tom está só {espectro.snr_db:.0f} dB acima do ruído (precisa de "
                      f"{mc.SNR_MINIMO_GRADE_DB:.0f})")
    return MetricasDeBancada(basicas, espectro, cont, trocas, jitter, degraus_trocas, degraus_rebases, lsb, fundo,
                             saturacao, inicio, len(x), fs, tuple(avisos))


# ------------------------------------------------------------------ a zona das imagens


def atenuacao_do_adc_db(f_hz: float | np.ndarray) -> float | np.ndarray:
    """O quanto o passa-baixa do ADS8688 atenua em ``f_hz`` (dB, positivo): o modelo de Butterworth de 2ª ordem em
    :data:`CORTE_DO_ADC_HZ` (o datasheet, 8.3.5; aproximado: o perfil da sonda mede o de verdade)."""
    return 10.0 * np.log10(1.0 + (np.asarray(f_hz, dtype=np.float64) / CORTE_DO_ADC_HZ) ** (2 * ORDEM_DO_FILTRO_DO_ADC))


def limite_das_imagens_hz(taxa_hz: float, margem_db: float = MARGEM_DAS_IMAGENS_DB) -> float:
    """A menor frequência (até a Nyquist) em que uma entrada em ``taxa − f`` chega ao espectro menos de
    ``margem_db`` abaixo de uma real de mesma amplitude em f: dali para cima, um pico pode ser uma imagem."""
    f = np.linspace(0.0, taxa_hz / 2, 4097)[1:]
    vantagem = atenuacao_do_adc_db(taxa_hz - f) - atenuacao_do_adc_db(f)
    perto = np.nonzero(vantagem < margem_db)[0]
    return float(f[perto[0]]) if len(perto) else taxa_hz / 2


# ------------------------------------------------------------------ o assistente de aliasing


@dataclass(frozen=True)
class ParametrosDoAliasing:
    """Os do ``aliasing`` da CLI, com os mesmos padrões."""

    freq_min_hz: float = CORTE_SUPRAHARMONICOS_PADRAO
    freq_max_hz: float | None = None
    acima_do_piso_db: float = 20.0
    resolucao_hz: float = 25.0
    tolerancia_hz: float = 100.0
    tolerancia_db: float = 3.0
    f_max_entrada_hz: float = 1e6
    inicio_s: float = 1e-3
    max_segundos: float = 10.0


FRACAO_DA_NYQUIST = 0.98


@dataclass(frozen=True)
class ResultadoDoAliasing:
    componentes: list
    taxas_hz: list[float]
    faixas_hz: list[tuple[float, float]]
    pisos_db: list[float]
    n_picos: list[int]
    ambiguas: list[tuple[float, float]] = field(default_factory=list)
    unidade: str = "dBV no pino do ADC"

    @property
    def reais(self) -> int:
        return sum(1 for c in self.componentes if c.frequencia_entrada_hz is not None
                   and all(r for r, p in zip(c.reais, c.picos) if p is not None))

    @property
    def sem_par(self) -> int:
        return sum(1 for c in self.componentes if c.frequencia_entrada_hz is None)


def aliasing(capturas: list[tuple[api.Captura, int]], p: ParametrosDoAliasing = ParametrosDoAliasing(), *,
             progresso: Callable[[float], None] | None = None,
             cancelado: Callable[[], bool] | None = None) -> ResultadoDoAliasing:
    """O pareamento das capturas ``(captura, canal)`` (ver o começo do módulo). Levanta ``api.ErroSHAN`` com o
    motivo: menos de duas, mais de :data:`aliasing.LETRAS`, duas na mesma taxa, curtas demais."""
    if not 2 <= len(capturas) <= len(al.LETRAS):
        raise api.ErroSHAN(f"escolha de 2 a {len(al.LETRAS)} capturas do mesmo sinal, cada uma numa taxa")
    canais = [cap.canal(numero) for cap, numero in capturas]
    taxas = [c.taxa_hz for c in canais]
    for i in range(len(taxas)):
        for j in range(i + 1, len(taxas)):
            if abs(taxas[i] - taxas[j]) <= p.tolerancia_hz:
                raise api.ErroSHAN(f"as capturas {al.LETRAS[i]} e {al.LETRAS[j]} têm a mesma taxa por canal "
                                   f"({taxas[i]:.0f} S/s): cada captura tem de estar numa taxa (ex.: 400000, 390625 e "
                                   "320000)")
    em_volts = all(c.faixa_confiavel for c in canais)
    faixas, picos, pisos = [], [], []
    for k, (c, fs) in enumerate(zip(canais, taxas)):
        if cancelado is not None and cancelado():
            raise api.Cancelado()
        inicio = int(round(p.inicio_s * fs))
        fim = min(len(c.amostras), inicio + int(p.max_segundos * fs))
        if fim - inicio < 4 * fs / p.resolucao_hz:
            raise api.ErroSHAN(f"a captura {al.LETRAS[k]} é curta demais para a resolução de {p.resolucao_hz:g} Hz "
                               f"({max(fim - inicio, 0)} amostras)")
        codigos = np.asarray(c.amostras[inicio:fim])
        sinal = (converter_para_tensao(codigos, c.faixa_v, 1.0, c.formato, c.offset_v) if em_volts
                 else codigos.astype(np.float64))
        f_max = min(p.freq_max_hz or math.inf, FRACAO_DA_NYQUIST * fs / 2)
        if f_max <= p.freq_min_hz:
            raise api.ErroSHAN(f"captura {al.LETRAS[k]}: a faixa analisada é vazia ({p.freq_min_hz:g} a {f_max:g} Hz)")
        achados, piso = al.picos_do_sinal(sinal, fs, p.freq_min_hz, f_max, p.acima_do_piso_db, p.resolucao_hz,
                                          DISTANCIA_MINIMA_PICOS_PADRAO)
        faixas.append((p.freq_min_hz, f_max))
        picos.append(achados)
        pisos.append(piso)
        if progresso is not None:
            progresso((k + 1) / (len(canais) + 1))
    componentes = al.parear_varias(picos, taxas, faixas, p.tolerancia_hz, p.tolerancia_db, p.f_max_entrada_hz)
    ambiguas = al.entradas_ambiguas_em_todas(taxas, min(f[1] for f in faixas), p.f_max_entrada_hz, p.tolerancia_hz)
    return ResultadoDoAliasing(componentes, taxas, faixas, pisos, [len(x) for x in picos], ambiguas,
                               "dBV no pino do ADC" if em_volts else "dB re 1 LSB")
