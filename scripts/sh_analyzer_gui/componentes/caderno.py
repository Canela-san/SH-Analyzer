"""As entradas de um caderno de bancada na tela (a F4.5): a mais nova em cima, com a hora e quem escreveu
("automático" ou "você"), o texto com o pouco de Markdown que as entradas usam (o `código`, o **negrito**, os itens
"- "). A mesma lista na Aquisição (o caderno do dia) e no inspetor do projeto (o de uma pasta de capturas).

Um ``QTextBrowser``: o texto se seleciona e se copia, quebra na largura e aguenta as centenas de entradas de um dia
sem um widget por entrada.
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence

from PySide6.QtWidgets import QFrame, QTextBrowser, QWidget
from shiboken6 import isValid

from ..dados.caderno import AUTOMATICO, Entrada
from ..tema.aplicar import aparencia
from ..tema.fontes import fonte_mono
from ..tema.tokens import TAMANHOS, Tema

_CODIGO = re.compile(r"`([^`]+)`")
_NEGRITO = re.compile(r"\*\*([^*]+)\*\*")


MARCAS = {"✓": "ok", "!": "aviso", "✗": "erro"}
"""As marcas das linhas de detalhe (as do ``conferir.sh``), e o papel da cor de cada uma."""


def html_da_linha(linha: str, familia_mono: str, cores: dict[str, str] | None = None) -> str:
    """Uma linha do texto de uma entrada em HTML: o recuo, o item ("- "; com uma marca, só a marca, na cor dela), o
    `código` na fonte mono e o **negrito**. ``cores``: o papel (``"ok"``...) e a cor."""
    recuo = len(linha) - len(linha.lstrip(" "))
    corpo = linha.lstrip(" ")
    inicio = ""
    if corpo.startswith("- "):
        corpo = corpo[2:]
        marca = corpo[:1]
        if marca in MARCAS and corpo[1:2] == " ":
            cor = (cores or {}).get(MARCAS[marca])
            inicio = (f"<span style='color:{cor}'>{html.escape(marca)}</span>" if cor else html.escape(marca)) + \
                "&nbsp;"
            corpo = corpo[2:]
        else:
            inicio = "•&nbsp;"
    corpo = html.escape(corpo, quote=False)
    corpo = _CODIGO.sub(lambda m: f"<span style=\"font-family:'{familia_mono}'\">{m.group(1)}</span>", corpo)
    corpo = _NEGRITO.sub(r"<b>\1</b>", corpo)
    return "&nbsp;" * recuo + inicio + corpo


class ListaDoCaderno(QTextBrowser):
    """``definir(entradas)`` (na ordem do arquivo); ``vazio``: o texto sem nenhuma. ``textos``: o que aparece, uma
    linha por entrada (``"14:10:03 · automático · Captura ..."``), para os testes e a acessibilidade."""

    def __init__(self, vazio: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("lista_do_caderno")
        self.setOpenLinks(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.vazio = vazio
        self.entradas: list[Entrada] = []
        self.textos: list[str] = []
        aparencia().mudou.connect(self._tema_mudou)

    def definir(self, entradas: Sequence[Entrada], vazio: str | None = None) -> None:
        self.entradas = list(entradas)
        if vazio is not None:
            self.vazio = vazio
        self.textos = [f"{e.hora_em_texto} · {e.autor} · {e.linhas[0]}" for e in reversed(self.entradas)]
        self._desenhar(aparencia().tema)

    def _tema_mudou(self, tema: Tema) -> None:
        if isValid(self):
            self._desenhar(tema)

    def _desenhar(self, t: Tema) -> None:
        mono = fonte_mono(TAMANHOS["secundario"]).family()
        if not self.entradas:
            self.setHtml(f"<div style='color:{t.mudo}'>{html.escape(self.vazio)}</div>")
            return
        cores = {"ok": t.ok, "aviso": t.aviso, "erro": t.erro}
        partes = []
        for i, e in enumerate(reversed(self.entradas)):
            cor_do_autor = t.mudo if e.autor == AUTOMATICO else t.acento
            corpo = "<br>".join(html_da_linha(linha, mono, cores) for linha in e.linhas)
            # O QTextDocument respeita a margem dos parágrafos (e não a de um div dentro de outro).
            partes.append(
                f"<p style='margin-top:{0 if i == 0 else 12}px; margin-bottom:2px; color:{t.mudo}; "
                f"font-size:{TAMANHOS['legenda']}px'>{e.hora_em_texto} · "
                f"<span style='color:{cor_do_autor}'>{html.escape(e.autor)}</span></p>"
                f"<p style='margin-top:0; margin-bottom:0; color:{t.texto}'>{corpo}</p>")
        rolagem = self.verticalScrollBar().value()
        self.setHtml("".join(partes))
        self.verticalScrollBar().setValue(rolagem)
