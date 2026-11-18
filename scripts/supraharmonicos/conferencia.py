"""A conferência de uma captura curta (docs/gui-plan.md, 11.5: o "Conferir antes"): a bancada está pronta para
capturar? As regras são as do ``firmware/coleta/conferir.sh`` (o ``./coletar.sh conferir``), aqui em ``numpy`` e
sobre o bloco inteiro:

* **a integridade:** as amostras atrasadas, os buffers sobrescritos e os quadros com ruído no SDO do cabeçalho, que
  têm de ser 0;
* **cada canal:** o nível (o mínimo, o máximo, o pico a pico, a média e o ruído sem o DC, em volts no pino), a
  frequência (as subidas pelo meio do sinal, com histerese de 10 % do pico a pico: a do ``medir_sinal``), a
  saturação (as amostras no fundo de escala), o canal parado (todas as amostras iguais: o ADC mudo ou a entrada
  saturada) e o "quase só ruído" (menos de 3 LSB rms);
* **a faixa sugerida:** a menor faixa do ADC que comporta o pico com 15 % de folga (``faixa_para_o_pico``);
* **o que o cabeçalho diz do sistema:** a placa, o sistema e o kernel, a versão do firmware, o relógio (NTP), o disco
  e o protocolo da PRU (o ``conferir.sh`` alerta, sem impedir a captura).

Uma função pura sobre o arquivo: quem captura é o ``sh_placa`` (a saída contínua), e quem mostra é a interface.
Depende de: ``cabecalho``, ``constantes``, ``erros``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .cabecalho import CabecalhoArquivo, ler_cabecalho
from .constantes import FAIXA_LEGADA_V, FAIXAS_ADC_TOTAL_V
from .erros import ErroSHAN

FOLGA_DA_FAIXA = 0.85
"""O pico cabe numa faixa com 15 % de folga (o ``faixa_para_o_pico`` do ``comum.sh``)."""
RUIDO_MINIMO_LSB = 3.0
HISTERESE = 0.1
"""A histerese das subidas, em fração do pico a pico."""
PICO_A_PICO_MINIMO_CODIGOS = 16
"""Abaixo disto (em códigos do ADC), o sinal não tem frequência para medir."""
SUBIDAS_MINIMAS = 4
DISCO_QUASE_CHEIO_KIB = 204_800                # 200 MiB, o do conferir.sh
PROTOCOLO_COM_A_ACOMODACAO = 5                 # a PRU de 11/11/2026 em diante espera o ADC acomodar a faixa


def faixa_para_o_pico(pico_v: float) -> float:
    """A menor faixa total do ADS8688 (5,12, 10,24 ou 20,48 V) em que ``|pico_v|`` cabe com a folga."""
    pico = abs(pico_v)
    for faixa in sorted(FAIXAS_ADC_TOTAL_V.values()):
        if pico <= FOLGA_DA_FAIXA * faixa / 2:
            return faixa
    return max(FAIXAS_ADC_TOTAL_V.values())


@dataclass(frozen=True)
class NivelDoCanal:
    """O sinal de um canal na conferência, em volts no pino do ADC."""

    canal: int
    faixa_v: float                      # a faixa total com que a captura foi feita
    amostras: int
    minimo_v: float
    maximo_v: float
    media_v: float
    rms_v: float                        # sem o DC
    saturadas: int                      # as amostras no fundo de escala (o código 0 ou o 65535)
    frequencia_hz: float | None         # None: sem um sinal periódico para medir

    @property
    def vpp_v(self) -> float:
        return self.maximo_v - self.minimo_v

    @property
    def pico_v(self) -> float:
        return max(abs(self.minimo_v), abs(self.maximo_v))

    @property
    def lsb_v(self) -> float:
        return self.faixa_v / 65536

    @property
    def rms_lsb(self) -> float:
        return self.rms_v / self.lsb_v

    @property
    def parado(self) -> bool:
        """Todas as amostras iguais: o ADC mudo ou a entrada saturada."""
        return self.amostras > 0 and self.maximo_v == self.minimo_v

    @property
    def satura(self) -> bool:
        return self.saturadas > 0

    @property
    def so_ruido(self) -> bool:
        return not self.parado and self.rms_v < RUIDO_MINIMO_LSB * self.lsb_v

    @property
    def uso_da_faixa(self) -> float:
        """Quanto da meia faixa o pico usa (1 = o fundo de escala)."""
        return self.pico_v / (self.faixa_v / 2)

    @property
    def sem_folga(self) -> bool:
        """O pico passa da folga de 15 % da faixa, sem saturar (na maior faixa, um surto pequeno satura)."""
        return not self.satura and self.pico_v > FOLGA_DA_FAIXA * self.faixa_v / 2

    @property
    def faixa_sugerida_v(self) -> float | None:
        """A faixa que o canal pede, se for outra que a da captura: a menor que comporta o pico com a folga; no canal
        saturado, a maior (o pico cortado não diz qual cabe: é nela que a ``faixa_automatica`` do ``comum.sh`` mede, e
        a conferência seguinte acha a menor). ``None`` com o canal parado ou saturado já na maior faixa."""
        if self.parado:
            return None
        ideal = max(FAIXAS_ADC_TOTAL_V.values()) if self.satura else faixa_para_o_pico(self.pico_v)
        return None if math.isclose(ideal, self.faixa_v, rel_tol=1e-3) else ideal

    @property
    def problema(self) -> bool:
        """O que o ``conferir.sh`` conta como problema (o ✗): o canal parado ou saturado."""
        return self.parado or self.satura


@dataclass(frozen=True)
class Conferencia:
    """O que a captura curta mostrou. ``integridade``: as amostras atrasadas, os buffers sobrescritos e os quadros com
    ruído no SDO (``None`` num cabeçalho sem eles)."""

    cabecalho: CabecalhoArquivo
    canais: tuple[NivelDoCanal, ...]

    @property
    def integridade(self) -> tuple[int | None, int | None, int | None]:
        c = self.cabecalho
        return c.amostras_atrasadas, c.buffers_sobrescritos, c.quadros_preambulo_ruim

    @property
    def integra(self) -> bool:
        return all(x == 0 for x in self.integridade)

    @property
    def divergencias(self) -> tuple[int, int] | None:
        """As divergências de leitura nas fases A e C do SPI rápido (``None`` no lento, ou sem o campo)."""
        c = self.cabecalho
        if not c.spi_rapido or c.divergencias_fase_a is None or c.divergencias_fase_c is None:
            return None
        return c.divergencias_fase_a, c.divergencias_fase_c

    @property
    def disco_quase_cheio(self) -> bool:
        livre = self.cabecalho.disco_saida_livre_fim_kib
        return livre is not None and livre < DISCO_QUASE_CHEIO_KIB

    @property
    def pru_sem_acomodacao(self) -> bool:
        p = self.cabecalho.versao_protocolo_pru
        return p is not None and p < PROTOCOLO_COM_A_ACOMODACAO

    @property
    def problemas(self) -> int:
        """Quantos ✗ o ``conferir.sh`` daria: a integridade e cada canal parado ou saturado."""
        return (0 if self.integra else 1) + sum(1 for c in self.canais if c.problema)

    @property
    def pronta(self) -> bool:
        return self.problemas == 0

    def canal(self, numero: int) -> NivelDoCanal:
        for c in self.canais:
            if c.canal == numero:
                return c
        raise KeyError(f"o canal {numero} não está na conferência")


def frequencia_pelas_subidas(codigos: np.ndarray, taxa_hz: float) -> float | None:
    """A frequência de um sinal pelas subidas pelo meio do pico a pico, com histerese (a do ``medir_sinal`` do
    ``comum.sh``): uma subida só conta depois de o sinal ter descido abaixo de ``meio - 10 % do pico a pico``, e o
    instante dela é interpolado entre as duas amostras. ``None`` sem sinal (menos de 16 códigos de pico a pico) ou com
    menos de 4 subidas."""
    c = np.asarray(codigos, dtype=np.float64)
    if c.size < 2:
        return None
    minimo, maximo = float(c.min()), float(c.max())
    pp = maximo - minimo
    if pp < PICO_A_PICO_MINIMO_CODIGOS:
        return None
    meio, h = (minimo + maximo) / 2, HISTERESE * pp
    anterior, atual = c[:-1], c[1:]
    candidatas = np.flatnonzero((anterior < meio) & (atual >= meio)) + 1     # i: c[i-1] < meio <= c[i]
    marcas = np.where(anterior < meio - h, np.arange(c.size - 1), -1)
    armada_desde = np.maximum.accumulate(marcas)                             # a última amostra k abaixo, até i-1
    instantes = []
    ultima = 0
    for i in candidatas:
        if armada_desde[i - 1] >= ultima:
            instantes.append((i - 1) + (meio - c[i - 1]) / (c[i] - c[i - 1]))
            ultima = i
    if len(instantes) < SUBIDAS_MINIMAS or instantes[-1] <= instantes[0]:
        return None
    return (len(instantes) - 1) * taxa_hz / (instantes[-1] - instantes[0])


def medir_canal(codigos: np.ndarray, canal: int, faixa_v: float, taxa_hz: float) -> NivelDoCanal:
    """O nível de um canal dos códigos dele (``uint16``, o zero no meio da faixa) à taxa dele."""
    c = np.asarray(codigos)
    if c.size == 0:
        return NivelDoCanal(canal, faixa_v, 0, math.nan, math.nan, math.nan, math.nan, 0, None)
    lsb = faixa_v / 65536
    x = c.astype(np.float64)
    return NivelDoCanal(canal, faixa_v, int(c.size), (float(x.min()) - 32768) * lsb, (float(x.max()) - 32768) * lsb,
                        (float(x.mean()) - 32768) * lsb, float(x.std()) * lsb,
                        int(np.count_nonzero((c == 0) | (c == 65535))), frequencia_pelas_subidas(c, taxa_hz))


def conferir_captura(caminho: Path) -> Conferencia:
    """A conferência de ``caminho`` (um ``.bin`` com o cabeçalho): cada canal pelas amostras gravadas, com a faixa
    do cabeçalho. ``ErroSHAN`` num arquivo sem o cabeçalho ou sem amostras."""
    caminho = Path(caminho)
    cabecalho = ler_cabecalho(caminho)
    if cabecalho is None:
        raise ErroSHAN(f"'{caminho.name}' não tem o cabeçalho do ler_adc: não dá para conferir")
    tamanho = caminho.stat().st_size - cabecalho.tamanho_cabecalho
    n = tamanho // 2
    if n <= 0:
        raise ErroSHAN(f"'{caminho.name}' não tem amostras")
    amostras = np.memmap(caminho, dtype="<u2", mode="r", offset=cabecalho.tamanho_cabecalho, shape=(n,))
    k = cabecalho.num_canais
    taxa_por_canal = cabecalho.pru_clock_hz / cabecalho.sample_period_ticks / k
    faixas = [FAIXAS_ADC_TOTAL_V.get(codigo, FAIXA_LEGADA_V) for codigo in cabecalho.faixa_adc_codigo_por_canal] or \
        [FAIXA_LEGADA_V] * k
    canais = tuple(medir_canal(np.asarray(amostras[j::k]), canal, faixas[j], taxa_por_canal)
                   for j, canal in enumerate(cabecalho.lista_canais))
    del amostras
    return Conferencia(cabecalho, canais)
