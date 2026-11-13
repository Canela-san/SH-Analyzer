"""Abrir uma captura ``.bin`` para a interface: o memmap das amostras e, para cada canal, a visão das amostras dele, a
taxa e a conversão dos códigos do ADC para volts.

**Provisório até a ``supraharmonicos.api`` (F0.7 em docs/gui-progress.md).** Aqui só se lê o cabeçalho e se monta a
conversão para **volts no pino do ADC** (a faixa de cada canal, sem o ganho da sonda), com as mesmas regras da CLI
(``converter_para_tensao`` e ``resolver_offsets_por_canal``): ``uint16`` em binário com deslocamento, o offset na
metade da faixa. A calibração completa (ganhos, perfis de sonda, grandezas físicas) virá da ``api``.

Sem Qt: roda e se testa sem interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from supraharmonicos.cabecalho import CabecalhoArquivo, ler_cabecalho
from supraharmonicos.canais import resolver_offsets_por_canal
from supraharmonicos.constantes import FAIXA_LEGADA_V, FORMATOS_NUMPY

from .cache import chave_do_arquivo

GRANDEZAS = {0: "tensão", 1: "corrente", 2: "temperatura"}


class CapturaInvalida(ValueError):
    """O arquivo não pode ser aberto pela interface (sem cabeçalho, vazio, de outro formato)."""


@dataclass(frozen=True, eq=False)
class Canal:
    """Um canal de uma captura, pronto para a pirâmide e o gráfico."""

    numero: int            # o canal do ADC (0 a 7)
    posicao: int           # a posição na intercalação (a ordem crescente dos canais)
    amostras: np.ndarray   # a visão com passo dentro do memmap: nenhuma cópia
    taxa_hz: float         # a taxa deste canal (a total dividida pelo número de canais)
    escala: float          # volts por código, no pino do ADC
    deslocamento: float    # volts = código * escala + deslocamento
    grandeza: str
    sonda: str

    @property
    def nome(self) -> str:
        return f"canal {self.numero}"

    @property
    def duracao_s(self) -> float:
        return len(self.amostras) / self.taxa_hz


@dataclass(frozen=True, eq=False)
class Captura:
    """Uma captura aberta: o cabeçalho, todas as amostras (intercaladas, em memmap) e os canais."""

    caminho: Path
    cabecalho: CabecalhoArquivo
    amostras: np.ndarray
    canais: tuple[Canal, ...]
    chave: str             # a chave do cache de pirâmides (cache.chave_do_arquivo)
    formato: str = "uint16"


def abrir_bin(caminho: Path, formato: str = "uint16") -> Captura:
    """Abre um ``.bin`` com cabeçalho (v1 a v9) em memmap, sem ler as amostras.

    Levanta :class:`CapturaInvalida` se o arquivo não tiver cabeçalho (o formato legado pede os canais e a taxa,
    que a interface ainda não pergunta) ou não tiver amostras."""
    caminho = Path(caminho)
    if formato not in FORMATOS_NUMPY:
        raise ValueError(f"formato desconhecido: {formato!r}")
    cabecalho = ler_cabecalho(caminho)
    if cabecalho is None:
        raise CapturaInvalida(f"{caminho.name}: sem o cabeçalho do SH-Analyzer (formato legado ainda não suportado "
                              "na interface; use o adc_tool.py)")
    dtype = FORMATOS_NUMPY[formato]
    tamanho = caminho.stat().st_size - cabecalho.tamanho_cabecalho
    n_canais = cabecalho.num_canais
    if n_canais < 1 or tamanho < dtype.itemsize * n_canais:
        raise CapturaInvalida(f"{caminho.name}: nenhuma amostra depois do cabeçalho")
    amostras = np.memmap(caminho, dtype=dtype, mode="r", offset=cabecalho.tamanho_cabecalho,
                         shape=(tamanho // dtype.itemsize,))
    faixas = [f if f is not None else FAIXA_LEGADA_V for f in cabecalho.faixa_adc_total_v_por_canal]
    offsets = resolver_offsets_por_canal(None, faixas, formato, n_canais)
    lsb_divisor = 32768.0 if formato == "int16" else 65536.0
    taxa = cabecalho.frequencia_hz / n_canais
    canais = []
    for posicao, numero in enumerate(cabecalho.lista_canais[:n_canais]):
        grandezas = getattr(cabecalho, "grandeza_por_canal", ()) or ()
        sondas = getattr(cabecalho, "sonda_id_por_canal", ()) or ()
        canais.append(Canal(
            numero=int(numero), posicao=posicao,
            amostras=amostras[posicao::n_canais] if n_canais > 1 else amostras,
            taxa_hz=taxa,
            escala=faixas[posicao] / lsb_divisor,
            deslocamento=-offsets[posicao],
            grandeza=GRANDEZAS.get(grandezas[posicao] if posicao < len(grandezas) else 0, "?"),
            sonda=sondas[posicao] if posicao < len(sondas) else "",
        ))
    crc = getattr(cabecalho, "crc32_amostras", None)
    return Captura(caminho, cabecalho, amostras, tuple(canais), chave_do_arquivo(caminho, crc), formato)
