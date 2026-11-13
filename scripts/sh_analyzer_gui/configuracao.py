"""A configuração do aplicativo: o layout da janela, o tema e as fontes escolhidas.

Num arquivo INI em todos os sistemas (no Linux, ``~/.config/SH-Analyzer/SH-Analyzer.ini``; no Windows, em
``%APPDATA%``): o mesmo formato em toda parte, legível e fácil de apagar para voltar ao padrão.

**A pasta pode ser trocada** pela variável de ambiente ``SH_ANALYZER_CONFIG``: os testes a apontam para uma pasta
temporária (``tests/conftest.py``), e nenhum teste toca a configuração de quem desenvolve; serve também para rodar
o aplicativo de um pendrive, com a configuração junto.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings

VARIAVEL_DA_PASTA = "SH_ANALYZER_CONFIG"
ORGANIZACAO = "SH-Analyzer"
APLICATIVO = "SH-Analyzer"


def configuracoes() -> QSettings:
    """A configuração do usuário (ou a da pasta de ``SH_ANALYZER_CONFIG``). Crie uma a cada uso: o ``QSettings``
    é barato e grava sozinho quando sai de escopo."""
    pasta = os.environ.get(VARIAVEL_DA_PASTA)
    if pasta:
        return QSettings(str(Path(pasta) / f"{APLICATIVO}.ini"), QSettings.Format.IniFormat)
    return QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, ORGANIZACAO, APLICATIVO)


def ler_bytes(chave: str) -> QByteArray | None:
    """Um valor binário (o layout da janela), ou ``None`` se não existir ou não for binário: um arquivo editado à
    mão ou de outra versão não derruba a partida."""
    valor = configuracoes().value(chave)
    return valor if isinstance(valor, QByteArray) and not valor.isEmpty() else None


def ler_texto(chave: str, padrao: str = "") -> str:
    valor = configuracoes().value(chave)
    return valor if isinstance(valor, str) else padrao


def gravar(chave: str, valor) -> None:
    c = configuracoes()
    c.setValue(chave, valor)
    c.sync()
