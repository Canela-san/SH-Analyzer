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


def ler_lista(chave: str) -> list[str]:
    """Uma lista de textos (os recentes); vazia se não houver ou se o valor for de outro tipo."""
    valor = configuracoes().value(chave)
    if isinstance(valor, str):
        return [valor]
    return [v for v in valor if isinstance(v, str)] if isinstance(valor, list) else []


def lembrar(chave: str, valor: str, limite: int = 10) -> list[str]:
    """Põe ``valor`` no topo da lista ``chave`` (sem repetir, no máximo ``limite``) e devolve a lista nova."""
    lista = [valor, *(v for v in ler_lista(chave) if v != valor)][:limite]
    gravar(chave, lista)
    return lista


def esquecer(chave: str, valor: str) -> None:
    gravar(chave, [v for v in ler_lista(chave) if v != valor])


def pasta_de_recuperacao() -> Path:
    """Onde vai o salvamento automático de um projeto sem título (ao lado da configuração quando
    ``SH_ANALYZER_CONFIG`` está definida; senão, na pasta de dados do usuário)."""
    pasta = os.environ.get(VARIAVEL_DA_PASTA)
    if pasta:
        return Path(pasta) / "recuperacao"
    from platformdirs import user_data_dir

    return Path(user_data_dir(APLICATIVO, ORGANIZACAO)) / "recuperacao"
