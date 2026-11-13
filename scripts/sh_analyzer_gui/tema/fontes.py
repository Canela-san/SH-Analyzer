"""As fontes da interface (docs/gui-plan.md, 12.4): **Inter** na interface e **JetBrains Mono** nos números alinhados
e no terminal, ambas OFL.

Os arquivos ``.ttf``/``.otf`` em ``sh_analyzer_gui/recursos/fontes/`` (com a licença ao lado) são registrados na
partida, e o aplicativo fica igual em qualquer máquina. Enquanto eles não estiverem lá (docs/gui-progress.md, F0.8),
valem as fontes instaladas no sistema, e na falta delas, as do sistema operacional: nada quebra, só a aparência muda.
"""

from __future__ import annotations

from importlib import resources

from PySide6.QtGui import QFont, QFontDatabase

from .tokens import FONTE_INTERFACE, FONTE_MONO, TAMANHOS


def registrar_fontes() -> list[str]:
    """Registra as fontes embutidas e devolve as famílias que entraram."""
    familias: list[str] = []
    pasta = resources.files("sh_analyzer_gui") / "recursos" / "fontes"
    if not pasta.is_dir():
        return familias
    for arquivo in sorted(pasta.iterdir(), key=lambda a: a.name):
        if arquivo.name.lower().endswith((".ttf", ".otf")):
            ident = QFontDatabase.addApplicationFontFromData(arquivo.read_bytes())
            if ident >= 0:
                familias.extend(QFontDatabase.applicationFontFamilies(ident))
    return sorted(set(familias))


def _existe(familia: str) -> bool:
    return familia in QFontDatabase.families()


def fonte_da_interface(tamanho: int = TAMANHOS["corpo"]) -> QFont:
    """A Inter, se houver; senão, a fonte geral do sistema. ``tamanho`` em pixels lógicos."""
    fonte = QFont(FONTE_INTERFACE) if _existe(FONTE_INTERFACE) else QFontDatabase.systemFont(
        QFontDatabase.SystemFont.GeneralFont)
    fonte.setPixelSize(tamanho)
    return fonte


def fonte_mono(tamanho: int = TAMANHOS["secundario"]) -> QFont:
    """A JetBrains Mono, se houver; senão, a fonte de largura fixa do sistema."""
    fonte = QFont(FONTE_MONO) if _existe(FONTE_MONO) else QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    fonte.setPixelSize(tamanho)
    return fonte


def com_algarismos_tabulares(fonte: QFont) -> QFont:
    """A mesma fonte com algarismos de largura igual (``tnum``): as medidas não "dançam" quando o número muda.
    Precisa do Qt 6.7 (``QFont.setFeature``); antes dele, devolve a fonte como está."""
    tabular = QFont(fonte)
    if hasattr(tabular, "setFeature") and hasattr(QFont, "Tag"):
        tabular.setFeature(QFont.Tag("tnum"), 1)
    return tabular
