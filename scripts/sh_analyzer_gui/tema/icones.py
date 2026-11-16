"""Os ícones da interface: traço de 24 px no estilo do Lucide, desenhados para o SH-Analyzer (os mesmos dos mockups,
``docs/gui-mockups/desenho.js``), recoloridos pelo tema na hora (docs/gui-plan.md, 12.6).

Cada ícone é um caminho SVG (``svgs.py``, sem Qt); :func:`icone` o desenha com o ``QSvgRenderer`` na cor pedida, em 1x e 2x (telas com
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
from .svgs import CAMINHOS, svg
from .tokens import Tema

__all__ = ["CAMINHOS", "IconeDoTema", "icone", "icone_com_estados", "icone_de_lista", "svg"]



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
def icone_com_estados(nome: str, cor: str, cor_ligado: str, cor_desabilitado: str, tamanho: int = 16,
                      nome_ligado: str | None = None) -> QIcon:
    """O ícone com uma cor para o estado normal, outra para o ligado (``checked``) e outra para o desabilitado. Com
    ``nome_ligado``, o ligado é outro desenho (o cadeado aberto)."""
    resultado = QIcon()
    ligado = nome_ligado or nome
    for modo, estado, c in ((QIcon.Mode.Normal, QIcon.State.Off, cor), (QIcon.Mode.Normal, QIcon.State.On, cor_ligado),
                            (QIcon.Mode.Active, QIcon.State.Off, cor), (QIcon.Mode.Active, QIcon.State.On, cor_ligado),
                            (QIcon.Mode.Disabled, QIcon.State.Off, cor_desabilitado),
                            (QIcon.Mode.Disabled, QIcon.State.On, cor_desabilitado)):
        for mapa in _mapas(ligado if estado == QIcon.State.On else nome, c, tamanho):
            resultado.addPixmap(mapa, modo, estado)
    return resultado


@lru_cache(maxsize=128)
def icone_de_lista(nome: str, cor: str, cor_selecionado: str, tamanho: int = 16) -> QIcon:
    """O ícone de um item de lista: ``cor`` no item normal e ``cor_selecionado`` no escolhido (a navegação lateral, em
    que o item escolhido fica na cor do acento)."""
    resultado = QIcon()
    for modo, c in ((QIcon.Mode.Normal, cor), (QIcon.Mode.Active, cor), (QIcon.Mode.Selected, cor_selecionado)):
        for mapa in _mapas(nome, c, tamanho):
            resultado.addPixmap(mapa, modo)
    return resultado


class IconeDoTema(QObject):
    """Mantém o ícone de ``alvo`` (um botão ou uma ``QAction``: qualquer objeto com ``setIcon``) na cor ``papel``
    do tema (``"texto2"``, ``"acento"``...), redesenhado a cada troca de tema. Filho do alvo: some com ele, e a
    conexão com o tema se desfaz sozinha.

    ``IconeDoTema(botao, "sol")``; para trocar o desenho depois, :meth:`trocar`."""

    def __init__(self, alvo: QObject, nome: str, papel: str = "texto2", *, papel_ligado: str | None = None,
                 tamanho: int = 16, nome_ligado: str | None = None):
        super().__init__(alvo)
        self._alvo, self.nome, self.papel, self.papel_ligado, self.tamanho = alvo, nome, papel, papel_ligado, tamanho
        self.nome_ligado = nome_ligado
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
                                                 self.tamanho, self.nome_ligado))
