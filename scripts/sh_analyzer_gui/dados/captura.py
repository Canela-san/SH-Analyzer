"""Abrir uma captura para a interface: a ``supraharmonicos.api`` (o que cada canal é, com as regras da CLI) mais a
chave do cache de pirâmides.

A interface só fala com o motor pela ``api`` (``tests/test_arquitetura.py`` confere): os canais, a conversão para a
unidade física (``CanalDaCaptura.escala`` e ``deslocamento``, que o ``TracoLOD`` aplica na consulta), o perfil de
sonda de cada canal e os avisos vêm de lá. Um erro do motor (``ErroSHAN``) sobe para quem abriu, com a mensagem
pronta para mostrar.

Sem Qt: roda e se testa sem interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from supraharmonicos.api import CanalDaCaptura, Captura, ErroSHAN, abrir_captura

from .cache import chave_do_arquivo

__all__ = ["CanalDaCaptura", "Captura", "ErroSHAN", "Fonte", "abrir_fonte"]


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


def abrir_fonte(caminho: Path, *, formato: str = "uint16", sondas_dir: Path | None = None) -> Fonte:
    """Abre um ``.bin`` com cabeçalho pela ``api`` (sem ler as amostras) e calcula a chave do cache: o CRC das
    amostras do cabeçalho v9, ou o caminho, o tamanho e a data nas versões anteriores. Levanta ``ErroSHAN``."""
    captura = abrir_captura(Path(caminho), formato=formato, sondas_dir=sondas_dir)
    return Fonte(captura, chave_do_arquivo(captura.caminho, captura.cabecalho.crc32_amostras))
