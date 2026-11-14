"""Os dois botões da escala própria dos traços (``graficos/escalas.py``), os mesmos na vista de tempo e na de
espectro: o cadeado (destravar ou travar a escala do Y dos traços selecionados) e "Mesma escala" (os selecionados,
ou todos sem seleção, de volta à escala comum). Eles também entram na paleta de comandos."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget

from ...tema.icones import IconeDoTema


def _tr(texto: str) -> str:
    return QCoreApplication.translate("acoes_da_escala", texto)


def estado_do_chip(travado: bool, comum: bool) -> str | None:
    """O que o chip do traço mostra: ``"solta"`` (o cadeado aberto), ``"propria"`` (travado numa escala que não é
    a comum) ou nada."""
    return "solta" if not travado else (None if comum else "propria")


def acoes_da_escala(vista: QWidget, destravar: Callable[[bool], None],
                    igualar: Callable[[], None]) -> tuple[QAction, QAction]:
    """O cadeado (``destravar(destravado)``) e "Mesma escala" (``igualar()``), ligados à ``vista``."""
    cadeado = QAction(_tr("Escala própria do traço"), vista)
    cadeado.setObjectName("destravar_escala")
    cadeado.setCheckable(True)
    cadeado.setEnabled(False)
    cadeado.triggered.connect(destravar)
    IconeDoTema(cadeado, "cadeado", papel_ligado="acento", nome_ligado="cadeado_aberto")
    mesma = QAction(_tr("Mesma escala"), vista)
    mesma.setObjectName("igualar_escalas")
    mesma.setEnabled(False)
    mesma.setToolTip(_tr("Mesma escala: os traços selecionados (sem seleção, todos) voltam à escala comum do eixo Y"))
    mesma.triggered.connect(lambda _=False: igualar())
    IconeDoTema(mesma, "igualar")
    for acao in (cadeado, mesma):
        acao.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        vista.addAction(acao)
    return cadeado, mesma


def atualizar_acoes_da_escala(cadeado: QAction, mesma: QAction, selecionados: list[tuple[bool, bool]],
                              alvos: list[tuple[bool, bool]]) -> None:
    """``selecionados`` e ``alvos`` (os selecionados, ou todos sem seleção): ``(travado, na escala comum)`` de cada
    traço. O cadeado vale para os selecionados e fica aberto se todos estão destravados; "Mesma escala", se algum
    alvo não está na escala comum."""
    aberto = bool(selecionados) and all(not travado for travado, _ in selecionados)
    cadeado.setEnabled(bool(selecionados))
    cadeado.setChecked(aberto)
    if not selecionados:
        dica = _tr("Escala própria: selecione um traço para destravar a escala do Y dele")
    elif aberto:
        dica = _tr("Travar a escala de novo: o traço volta a andar com os outros, na escala que tem agora")
    else:
        dica = _tr("Destravar a escala do Y do traço selecionado: o zoom e o pan do Y passam a ser só dele, e os dos "
                   "outros não o mexem")
    cadeado.setToolTip(dica)
    mesma.setEnabled(any(not comum for _, comum in alvos))
