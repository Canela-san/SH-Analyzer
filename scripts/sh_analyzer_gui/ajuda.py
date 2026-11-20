"""A ajuda contextual (F7.11, GE-08; docs/gui-progress.md, 4h): o guia da interface (``docs/gui-guide.md``) num leitor
dentro do aplicativo, e o botão "?" de cada painel e de cada vista, que abre a seção dele.

**O guia** tem uma seção por assunto, cada uma começada por ``## Título {#identificador}``; :func:`ler_guia` o separa
nelas (o texto de cada uma, sem o identificador, em Markdown). **O leitor** (:class:`LeitorDoGuia`) mostra uma seção
de cada vez, com a lista das seções e a busca (que filtra pelo título e pelo texto); há um por janela, que não
bloqueia. :func:`botao_de_ajuda` faz o "?" de uma seção, e :func:`abrir_ajuda` abre o leitor nela.

No aplicativo empacotado (o PyInstaller), o guia vai em ``ajuda/gui-guide.md`` ao lado do executável.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

NOME_DO_GUIA = "gui-guide.md"
SECAO_DO_TIPO = {"tempo": "tempo", "espectro": "espectro", "bandas": "bandas", "espectrograma": "espectrograma",
                 "harmonicos": "harmonicos", "sonda": "perfis", "xy": "xy", "histograma": "histograma",
                 "eventos": "eventos", "qualidade": "qualidade", "transferencia": "transferencia",
                 "metricas": "metricas", "instrumento": "instrumento"}
"""A seção do guia de cada tipo de vista (o "?" da vista e o F1 com ela à frente)."""
_TITULO = re.compile(r"^## (.+?)\s*\{#([a-z0-9-]+)\}\s*$")


@dataclass(frozen=True)
class Secao:
    id: str
    titulo: str
    texto: str          # o Markdown da seção, com o título (sem o identificador)


def caminho_do_guia() -> Path:
    """O guia: o empacotado (ao lado do executável do PyInstaller) ou o do repositório (``docs/``)."""
    base = getattr(sys, "_MEIPASS", None)
    if base is not None:
        return Path(base) / "ajuda" / NOME_DO_GUIA
    return Path(__file__).resolve().parents[2] / "docs" / NOME_DO_GUIA


def ler_guia(caminho: Path | None = None) -> list[Secao]:
    """As seções do guia, na ordem; o que vem antes da primeira é a introdução (``id`` "guia")."""
    texto = (caminho or caminho_do_guia()).read_text(encoding="utf-8")
    secoes: list[Secao] = []
    atual_id, atual_titulo, linhas = "guia", "", []

    def fechar():
        corpo = "\n".join(linhas).strip()
        if corpo:
            titulo = atual_titulo or "Sobre o guia"                 # a introdução, antes da primeira seção
            secoes.append(Secao(atual_id, titulo, corpo))

    for linha in texto.splitlines():
        m = _TITULO.match(linha)
        if m:
            fechar()
            atual_titulo, atual_id = m.group(1), m.group(2)
            linhas = [f"## {atual_titulo}"]
        else:
            linhas.append(linha)
    fechar()
    return secoes


class LeitorDoGuia(QDialog):
    """O guia numa janela que não bloqueia: a lista das seções, a busca e o texto da escolhida."""

    def __init__(self, parent: QWidget | None = None, caminho: Path | None = None):
        super().__init__(parent)
        self.setObjectName("leitor_do_guia")
        self.setWindowTitle(self.tr("Guia do SH-Analyzer"))
        self.resize(900, 640)
        self.secoes = ler_guia(caminho)
        self._por_id = {s.id: s for s in self.secoes}
        self.secao_atual: str | None = None
        self.busca = QLineEdit()
        self.busca.setObjectName("busca_do_guia")
        self.busca.setPlaceholderText(self.tr("Buscar no guia"))
        self.busca.setClearButtonEnabled(True)
        self.busca.textChanged.connect(self._filtrar)
        self.lista = QListWidget()
        self.lista.setObjectName("secoes_do_guia")
        for s in self.secoes:
            item = QListWidgetItem(s.titulo)
            item.setData(Qt.ItemDataRole.UserRole, s.id)
            self.lista.addItem(item)
        self.lista.currentItemChanged.connect(
            lambda item, _anterior: self.mostrar(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None)
        self.texto = QTextBrowser()
        self.texto.setObjectName("texto_do_guia")
        self.texto.setOpenExternalLinks(True)
        self.texto.document().setDocumentMargin(14)
        esquerda = QWidget()
        coluna = QVBoxLayout(esquerda)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.addWidget(self.busca)
        coluna.addWidget(self.lista, 1)
        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.addWidget(esquerda)
        divisor.addWidget(self.texto)
        divisor.setSizes([240, 660])
        linha = QHBoxLayout(self)
        linha.addWidget(divisor)

    def mostrar(self, secao_id: str) -> None:
        """A seção ``secao_id`` (uma desconhecida mostra a primeira: o guia ficou para trás do botão)."""
        secao = self._por_id.get(secao_id) or self.secoes[0]
        self.secao_atual = secao.id
        self.texto.setMarkdown(secao.texto)
        for i in range(self.lista.count()):
            item = self.lista.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == secao.id and self.lista.currentRow() != i:
                self.lista.blockSignals(True)
                self.lista.setCurrentRow(i)
                self.lista.blockSignals(False)

    def _filtrar(self, texto: str) -> None:
        procurado = texto.strip().lower()
        for i in range(self.lista.count()):
            item = self.lista.item(i)
            secao = self._por_id[item.data(Qt.ItemDataRole.UserRole)]
            item.setHidden(bool(procurado) and procurado not in secao.texto.lower())


def abrir_ajuda(widget: QWidget, secao_id: str) -> LeitorDoGuia:
    """O leitor da janela de ``widget`` (um por janela, criado na primeira vez), na seção pedida, à frente."""
    janela = widget.window()
    leitor = getattr(janela, "leitor_do_guia", None)
    if leitor is None:
        leitor = LeitorDoGuia(janela)
        janela.leitor_do_guia = leitor
    leitor.mostrar(secao_id)
    leitor.show()
    leitor.raise_()
    leitor.activateWindow()
    return leitor


def botao_de_ajuda(secao_id: str, dica: str = "", parent: QWidget | None = None, *,
                   qual: Callable[[], str] | None = None) -> QToolButton:
    """O "?" de um painel ou de uma vista: abre o guia na seção ``secao_id`` (ou na que ``qual()`` disser na hora:
    a da aba à frente, num painel com abas)."""
    botao = QToolButton(parent)
    botao.setObjectName(f"ajuda_{secao_id}")
    botao.setText("?")
    botao.setAutoRaise(True)
    botao.setProperty("ajuda", secao_id)
    botao.setToolTip(dica or botao.tr("Ajuda: o que é isto e como ler os números (o guia)"))
    botao.clicked.connect(lambda: abrir_ajuda(botao, qual() if qual is not None else secao_id))
    return botao
