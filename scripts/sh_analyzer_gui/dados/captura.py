"""Abrir uma captura para a interface: a ``supraharmonicos.api`` (o que cada canal é, com as regras da CLI) mais a
chave do cache de pirâmides.

A interface só fala com o motor pela ``api`` (``tests/test_arquitetura.py`` confere): os canais, a conversão para a
unidade física (``CanalDaCaptura.escala`` e ``deslocamento``, que o ``TracoLOD`` aplica na consulta), o perfil de
sonda de cada canal e os avisos vêm de lá. Um erro do motor (``ErroSHAN``) sobe para quem abriu, com a mensagem
pronta para mostrar; uma captura sem o cabeçalho (o ``.bin`` legado, o ``.csv``) levanta ``CapturaSemCabecalho``, e
quem abriu pergunta a taxa e os canais (``ParametrosSemCabecalho``) e abre de novo.

Sem Qt: roda e se testa sem interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from supraharmonicos.api import (
    Aviso,
    CanalDaCaptura,
    Captura,
    CapturaSemCabecalho,
    ErroSHAN,
    ParametrosSemCabecalho,
    abrir_captura,
    crc32_das_amostras,
)

from .cache import chave_do_arquivo

__all__ = ["Aviso", "CanalDaCaptura", "Captura", "CapturaSemCabecalho", "ErroSHAN", "Fonte", "ParametrosSemCabecalho",
           "abrir_fonte", "crc_das_amostras"]


@dataclass(frozen=True, eq=False)
class Fonte:
    """Uma captura aberta na interface: a da ``api`` e a chave do cache das pirâmides dela."""

    captura: Captura
    chave: str

    @property
    def caminho(self) -> Path:
        return self.captura.caminho

    @property
    def nome(self) -> str:
        return self.captura.caminho.name

    @property
    def canais(self) -> tuple[CanalDaCaptura, ...]:
        return self.captura.canais


def abrir_fonte(caminho: Path, *, formato: str | None = None, sondas_dir: Path | None = None,
                parametros: ParametrosSemCabecalho | None = None) -> Fonte:
    """Abre uma captura pela ``api`` (o ``.bin`` sem ler as amostras; ``parametros``: a taxa e os canais de uma sem
    o cabeçalho) e calcula a chave do cache: o CRC das amostras do ``.bin`` v9, ou o caminho, o tamanho e a data nos
    outros. Levanta ``ErroSHAN`` (``CapturaSemCabecalho`` quando faltam os ``parametros``)."""
    captura = abrir_captura(Path(caminho), formato=formato, sondas_dir=sondas_dir, parametros=parametros)
    return Fonte(captura, chave_do_arquivo(captura.caminho, captura.crc32_amostras))


def crc_das_amostras(caminho: Path) -> int | None:
    """O CRC das amostras de um ``.bin`` v9, lendo só o cabeçalho (``None`` sem ele, nas versões anteriores e nos
    outros tipos). Serve para reencontrar uma captura que mudou de lugar."""
    return crc32_das_amostras(Path(caminho))
