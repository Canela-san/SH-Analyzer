"""Os ícones da interface: traço de 24 px no estilo do Lucide, desenhados para o SH-Analyzer (os mesmos dos mockups,
``docs/gui-mockups/desenho.js``), recoloridos pelo tema na hora (docs/gui-plan.md, 12.6).

Cada ícone é um caminho SVG; :func:`icone` o desenha com o ``QSvgRenderer`` na cor pedida, em 1x e 2x (telas com
escala), e guarda o resultado: pedir o mesmo ícone de novo não redesenha nada. :func:`icone_com_estados` dá cores
diferentes ao ícone ligado e ao desabilitado (os botões de alternar), e :class:`IconeDoTema` mantém o ícone de um
botão ou de uma ação na cor do tema, a cada troca.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QObject, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .aplicar import aparencia
from .tokens import Tema

CAMINHOS = {
    "ponteiro": "M5 3l14 8-6 2-2 6z",
    "zoom": "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M16 16l5 5 M11 8v6 M8 11h6",
    "mao": "M8 13V5.5a1.5 1.5 0 0 1 3 0V12 M11 11V4.5a1.5 1.5 0 0 1 3 0V12 M14 11.5V6a1.5 1.5 0 0 1 3 0v8a6 6 0 0 1-6 "
           "6h-1a6 6 0 0 1-5-2.7L3.5 14a1.5 1.5 0 0 1 2.5-1.7L8 15",
    "cursores": "M7 3v18 M17 3v18 M10 12h4 M10 12l1.6-1.6 M10 12l1.6 1.6 M14 12l-1.6-1.6 M14 12l-1.6 1.6",
    "regua": "M3 17L17 3l4 4L7 21z M7 13l2 2 M10 10l2 2 M13 7l2 2",
    "texto": "M4 7V5h16v2 M12 5v14 M9 19h6",
    "camadas": "M12 3l9 5-9 5-9-5z M3 13l9 5 9-5",
    "pasta": "M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2h8.5A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z",
    "arquivo": "M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z M14 3v5h5",
    "chip": "M7 7h10v10H7z M10 3v4 M14 3v4 M10 17v4 M14 17v4 M3 10h4 M3 14h4 M17 10h4 M17 14h4",
    "terminal": "M4 17l6-5-6-5 M12 19h8",
    "ajustes": "M4 6h9 M17 6h3 M4 12h3 M11 12h9 M4 18h11 M19 18h1 M15 4v4 M9 10v4 M17 16v4",
    "busca": "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M16 16l5 5",
    "mais": "M12 5v14 M5 12h14",
    "x": "M6 6l12 12 M18 6L6 18",
    "olho": "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
    "onda": "M2 12c2-6.5 4-6.5 6 0s4 6.5 6 0 4-6.5 6 0 2 4 2 4",
    "espectro": "M4 20V11 M9 20V4 M14 20v-8 M19 20v-5",
    "grade": "M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M13 13h7v7h-7z",
    "baixar": "M12 4v11 M7 10l5 5 5-5 M5 20h14",
    "enviar": "M12 20V9 M7 14l5-5 5 5 M5 4h14",
    "play": "M7 4l13 8-13 8z",
    "stop": "M6 6h12v12H6z",
    "girar": "M20 12a8 8 0 1 1-2.3-5.7 M20 4v5h-5",
    "ok": "M5 12.5l4.5 4.5L19 7",
    "alerta": "M12 3.5l9.5 16.5h-19z M12 10v4.5 M12 17.5v.2",
    "usb": "M12 3v13 M9.5 5.5L12 3l2.5 2.5 M12 12.5l-4-2V8 M12 14.5l4-2V10 M12 16.2a2.4 2.4 0 1 0 0 4.8 2.4 2.4 0 0 0 0-4.8z",
    "relogio": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2",
    "disco": "M3 13l3-8h12l3 8v5.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z M3 13h18 M17 16.5h.2",
    "chave": "M15 3.5a5 5 0 0 0-4.6 6.9L3.5 17.3V20.5h3.2l6.9-6.9A5 5 0 0 0 20.5 9l-3 1-2.5-2.5 1-3z",
    "sol": "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M12 2v2 M12 20v2 M4.9 4.9l1.4 1.4 M17.7 17.7l1.4 1.4 M2 12h2 M20 12h2 "
           "M4.9 19.1l1.4-1.4 M17.7 6.3l1.4-1.4",
    "lua": "M20 14.5A8.5 8.5 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z",
    "baixo": "M6 9l6 6 6-6",
    "direita": "M9 6l6 6-6 6",
    "filtro": "M3 5h18l-7 8v6l-4 2v-8z",
    "desfazer": "M9 14L4 9l5-5 M4 9h10.5a5.5 5.5 0 0 1 0 11H11",
    "refazer": "M15 14l5-5-5-5 M20 9H9.5a5.5 5.5 0 0 0 0 11H13",
    "sonda": "M4 20l5.5-5.5 M9.5 14.5l2 2 7.5-7.5-2-2-7.5 7.5z M15.5 5.5l3 3",
    "pulso": "M3 12h4l3-8 4 16 3-8h4",
    "expandir": "M4 9V4h5 M20 9V4h-5 M4 15v5h5 M20 15v5h-5",
    "mira": "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16z M12 2v4 M12 18v4 M2 12h4 M18 12h4",
    "livro": "M5 4.5h11a3 3 0 0 1 3 3V20H8a3 3 0 0 1-3-3z M5 17a3 3 0 0 1 3-3h11",
    "raio": "M13 2L4 14h7l-1 8 9-12h-7z",
    "imagem": "M4 5h16v14H4z M4 16l5-5 4 4 3-3 4 4 M15 9h.2",
    "energia": "M12 3v8 M6.3 7a8 8 0 1 0 11.4 0",
    "copiar": "M8 8h11v12H8z M5 16V4h11",
    "escudo": "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z M9 12l2 2 4-4",
    "pagina": "M6 3h9l4 4v14H6z M15 3v4h4",
    "link": "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1 M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
}


def svg(nome: str, cor: str, espessura: float = 1.8) -> str:
    """O SVG do ícone ``nome`` na cor ``cor`` (``#rrggbb``)."""
    if nome not in CAMINHOS:
        raise KeyError(f"ícone desconhecido: {nome!r}")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{cor}" '
            f'stroke-width="{espessura}" stroke-linecap="round" stroke-linejoin="round"><path d="{CAMINHOS[nome]}"/></svg>')


def _mapas(nome: str, cor: str, tamanho: int) -> list[QPixmap]:
    """O ícone desenhado em ``tamanho`` px e no dobro (telas com escala de 200 %)."""
    renderizador = QSvgRenderer(QByteArray(svg(nome, cor).encode("utf-8")))
    mapas = []
    for escala in (1, 2):
        lado = tamanho * escala
        mapa = QPixmap(lado, lado)
        mapa.fill(Qt.GlobalColor.transparent)
        pintor = QPainter(mapa)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderizador.render(pintor)
        pintor.end()
        mapa.setDevicePixelRatio(escala)
        mapas.append(mapa)
    return mapas


@lru_cache(maxsize=512)
def icone(nome: str, cor: str, tamanho: int = 16) -> QIcon:
    """O ícone ``nome`` na cor ``cor``, em ``tamanho`` px e no dobro."""
    resultado = QIcon()
    for mapa in _mapas(nome, cor, tamanho):
        resultado.addPixmap(mapa)
    return resultado


@lru_cache(maxsize=256)
def icone_com_estados(nome: str, cor: str, cor_ligado: str, cor_desabilitado: str, tamanho: int = 16) -> QIcon:
    """O ícone com uma cor para o estado normal, outra para o ligado (``checked``) e outra para o desabilitado."""
    resultado = QIcon()
    for modo, estado, c in ((QIcon.Mode.Normal, QIcon.State.Off, cor), (QIcon.Mode.Normal, QIcon.State.On, cor_ligado),
                            (QIcon.Mode.Active, QIcon.State.Off, cor), (QIcon.Mode.Active, QIcon.State.On, cor_ligado),
                            (QIcon.Mode.Disabled, QIcon.State.Off, cor_desabilitado),
                            (QIcon.Mode.Disabled, QIcon.State.On, cor_desabilitado)):
        for mapa in _mapas(nome, c, tamanho):
            resultado.addPixmap(mapa, modo, estado)
    return resultado


class IconeDoTema(QObject):
    """Mantém o ícone de ``alvo`` (um botão ou uma ``QAction``: qualquer objeto com ``setIcon``) na cor ``papel``
    do tema (``"texto2"``, ``"acento"``...), redesenhado a cada troca de tema. Filho do alvo: some com ele, e a
    conexão com o tema se desfaz sozinha.

    ``IconeDoTema(botao, "sol")``; para trocar o desenho depois, :meth:`trocar`."""

    def __init__(self, alvo: QObject, nome: str, papel: str = "texto2", *, papel_ligado: str | None = None,
                 tamanho: int = 16):
        super().__init__(alvo)
        self._alvo, self.nome, self.papel, self.papel_ligado, self.tamanho = alvo, nome, papel, papel_ligado, tamanho
        aparencia().mudou.connect(self._aplicar)
        self._aplicar(aparencia().tema)

    def trocar(self, nome: str, papel: str | None = None) -> None:
        self.nome = nome
        if papel is not None:
            self.papel = papel
        self._aplicar(aparencia().tema)

    def _aplicar(self, tema: Tema) -> None:
        cor = getattr(tema, self.papel)
        if self.papel_ligado is None:
            self._alvo.setIcon(icone(self.nome, cor, self.tamanho))
        else:
            self._alvo.setIcon(icone_com_estados(self.nome, cor, getattr(tema, self.papel_ligado), tema.mudo,
                                                 self.tamanho))
