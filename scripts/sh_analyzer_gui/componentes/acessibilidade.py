"""Os nomes acessíveis (docs/gui-plan.md, 4.4): um leitor de tela (o Orca, o NVDA) lê o nome de cada controle. Os
botões só com ícone (a barra de cada vista, as abas, a barra superior) não têm texto, e sem o nome ficavam mudos.

:class:`NomesAcessiveis`, instalado na aplicação (``app.criar_aplicacao``), dá a cada botão sem texto e sem nome o da
dica dele, quando ele é preparado para aparecer (o ``Polish``) e quando a dica muda; um nome dado à mão nunca é
trocado. Custa um teste por widget preparado, nada por quadro.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractButton, QApplication

_ATALHO = re.compile(r"\s*\((?:Ctrl|Alt|Shift|F\d)[^)]*\)\s*$")
_MARCACAO = re.compile(r"<[^>]+>")


def nome_da_dica(dica: str) -> str:
    """O nome curto que a dica dá: a primeira linha, sem marcação e sem o atalho no fim ("Copiar (Ctrl+C)" vira
    "Copiar"; o atalho o leitor lê pela ação)."""
    primeira = _MARCACAO.sub("", dica).strip().splitlines()[0] if dica.strip() else ""
    return _ATALHO.sub("", primeira).strip()


def nomear(botao: QAbstractButton) -> None:
    """Dá a ``botao`` o nome da dica, se ele não tem texto nem nome (ou se o nome é o que a dica antiga deu)."""
    if botao.text().strip():
        return
    nome = nome_da_dica(botao.toolTip())
    atual = botao.accessibleName()
    if nome and (not atual or botao.property("_nome_da_dica") == atual):
        botao.setAccessibleName(nome)
        botao.setProperty("_nome_da_dica", nome)


class NomesAcessiveis(QObject):
    """O filtro de eventos da aplicação que nomeia os botões só com ícone (ver o começo do módulo)."""

    def eventFilter(self, objeto: QObject, evento: QEvent) -> bool:
        if evento.type() in (QEvent.Type.Polish, QEvent.Type.ToolTipChange) and isinstance(objeto, QAbstractButton):
            nomear(objeto)
        return False


def instalar(app: QApplication) -> None:
    """Uma vez por aplicação."""
    if getattr(app, "_nomes_acessiveis", None) is None:
        app._nomes_acessiveis = NomesAcessiveis(app)
        app.installEventFilter(app._nomes_acessiveis)
