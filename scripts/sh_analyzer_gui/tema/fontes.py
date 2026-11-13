"""As fontes da interface (docs/gui-plan.md, 12.4).

**As embutidas** ficam em ``sh_analyzer_gui/recursos/fontes/``, com a licença ao lado, e são registradas na partida:
o aplicativo fica igual em qualquer máquina, com ou sem a fonte instalada. A lista delas (de onde veio cada uma, a
versão, os arquivos e o papel) está em ``fontes_embutidas.py``, sem Qt.

**A escolha:** a fonte da interface e a mono podem ser trocadas (:func:`escolher_fonte`; a tela de configurações
entra na Fase 2). A padrão é a Inter na interface e a JetBrains Mono nos números alinhados e no terminal. Uma família
que não está registrada nem instalada cai na fonte do sistema: nada quebra, só a aparência muda.
"""

from __future__ import annotations

from importlib import resources

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from .fontes_embutidas import EMBUTIDAS, PAPEIS
from .tokens import FONTE_INTERFACE, FONTE_MONO, TAMANHOS

_escolhidas = {"interface": FONTE_INTERFACE, "mono": FONTE_MONO}


def pasta_das_fontes():
    return resources.files("sh_analyzer_gui") / "recursos" / "fontes"


def registrar_fontes() -> list[str]:
    """Registra as fontes de :data:`EMBUTIDAS` e devolve as famílias que entraram (registrar de novo não duplica:
    o Qt reaproveita a fonte já registrada)."""
    familias: set[str] = set()
    pasta = pasta_das_fontes()
    for fonte in EMBUTIDAS:
        for nome in fonte.arquivos:
            arquivo = pasta / nome
            if not arquivo.is_file():
                continue
            ident = QFontDatabase.addApplicationFontFromData(arquivo.read_bytes())
            if ident >= 0:
                familias.update(QFontDatabase.applicationFontFamilies(ident))
    return sorted(familias)


def _existe(familia: str) -> bool:
    return familia in QFontDatabase.families()


def familias_disponiveis(papel: str) -> list[str]:
    """As famílias que a configuração pode oferecer para ``papel``: as embutidas daquele papel que estão registradas."""
    if papel not in PAPEIS:
        raise ValueError(f"papel desconhecido: {papel!r} (use {', '.join(PAPEIS)})")
    return [f.familia for f in EMBUTIDAS if f.papel == papel and _existe(f.familia)]


def escolher_fonte(papel: str, familia: str, app: QApplication | None = None) -> None:
    """Troca a fonte da interface ou a mono. A da interface vale na hora para a aplicação inteira."""
    if papel not in PAPEIS:
        raise ValueError(f"papel desconhecido: {papel!r} (use {', '.join(PAPEIS)})")
    if not _existe(familia):
        raise ValueError(f"a fonte {familia!r} não está registrada nem instalada")
    _escolhidas[papel] = familia
    app = app or QApplication.instance()
    if papel == "interface" and app is not None:
        app.setFont(fonte_da_interface())


def fonte_escolhida(papel: str) -> str:
    return _escolhidas[papel]


def fonte_da_interface(tamanho: int = TAMANHOS["corpo"]) -> QFont:
    """A fonte escolhida para a interface (a Inter, por padrão), ou a geral do sistema. ``tamanho`` em pixels."""
    familia = _escolhidas["interface"]
    fonte = QFont(familia) if _existe(familia) else QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    fonte.setPixelSize(tamanho)
    return fonte


def fonte_mono(tamanho: int = TAMANHOS["secundario"]) -> QFont:
    """A fonte mono escolhida (a JetBrains Mono, por padrão), ou a de largura fixa do sistema."""
    familia = _escolhidas["mono"]
    fonte = QFont(familia) if _existe(familia) else QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    fonte.setPixelSize(tamanho)
    return fonte


def com_algarismos_tabulares(fonte: QFont) -> QFont:
    """A mesma fonte com algarismos de largura igual (``tnum``): as medidas não "dançam" quando o número muda.
    Precisa do Qt 6.7 (``QFont.setFeature``); antes dele, devolve a fonte como está."""
    tabular = QFont(fonte)
    if hasattr(tabular, "setFeature") and hasattr(QFont, "Tag"):
        tabular.setFeature(QFont.Tag("tnum"), 1)
    return tabular
