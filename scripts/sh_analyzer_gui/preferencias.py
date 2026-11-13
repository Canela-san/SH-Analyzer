"""As preferências de aparência que sobrevivem entre as sessões: o tema e as fontes (a da interface e a dos números).

Gravadas na configuração (``configuracao.py``) a cada mudança e aplicadas na partida (``app.main``). A tela de
configurações completa vem depois (GE-05); por enquanto, o menu de ajustes da barra superior as troca.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from .configuracao import gravar, ler_texto
from .tema.aplicar import MODOS, aparencia
from .tema.fontes import escolher_fonte, familias_disponiveis

CHAVE_DO_TEMA = "aparencia/tema"
CHAVES_DAS_FONTES = {"interface": "aparencia/fonte_interface", "mono": "aparencia/fonte_mono"}


def tema_salvo() -> str:
    """O modo de tema gravado (``"sistema"``, ``"escuro"`` ou ``"claro"``); ``"sistema"`` se não houver um válido."""
    modo = ler_texto(CHAVE_DO_TEMA, "sistema")
    return modo if modo in MODOS else "sistema"


def mudar_tema(modo: str) -> None:
    aparencia().aplicar(modo)
    gravar(CHAVE_DO_TEMA, modo)


def alternar_tema() -> None:
    """Troca entre o escuro e o claro, e grava a escolha."""
    mudar_tema("claro" if aparencia().tema.escuro else "escuro")


def aplicar_fontes_salvas(app: QApplication | None = None) -> None:
    """Aplica as fontes gravadas que ainda existem; uma que sumiu fica no padrão, sem erro."""
    for papel, chave in CHAVES_DAS_FONTES.items():
        familia = ler_texto(chave)
        if familia and familia in familias_disponiveis(papel):
            escolher_fonte(papel, familia, app)


def mudar_fonte(papel: str, familia: str) -> None:
    escolher_fonte(papel, familia)
    gravar(CHAVES_DAS_FONTES[papel], familia)
