"""O caderno de notas do pesquisador (Ctrl+Shift+N, de qualquer lugar): um bloco de notas rápido, em páginas de
Markdown, que fica no lado da janela por cima de qualquer área (``dados/notas.py`` guarda as páginas).

* **O editor** escreve o Markdown como texto, com o realce dele ao vivo (:class:`RealceDoMarkdown`): ``#`` vira um
  título grande, ``**negrito**``, ``*itálico*``, ``~~tachado~~``, ``código``, as listas, as tarefas (``- [ ]``, e a
  feita, ``- [x]``, riscada), as citações (``>``), os blocos de código, os links e as imagens. As listas continuam no
  Enter (e acabam num item vazio); Tab e Shift+Tab mudam o nível. A barra põe cada marcação (e os atalhos: Ctrl+B,
  Ctrl+I, Ctrl+K o link, Ctrl+Shift+X o tachado, Ctrl+1, 2 e 3 os títulos, Ctrl+Shift+L a tarefa).
* **"Ver"** mostra a página formatada (o Markdown do Qt, com as imagens).
* **As referências aos gráficos** (``dados/notas.py``): o clique direito num gráfico, a barra de anotação ou o botão
  daqui põem um link para um ponto ou um trecho de uma vista; o clique nele (Ctrl+clique no editor) leva a vista até
  ali e o destaca.
* **As imagens:** colar uma imagem (Ctrl+V) a grava na pasta ``imagens`` do caderno; o botão da vista põe a imagem
  do gráfico à frente.
* **A gravação** é sozinha, 0,7 s depois da última mudança (e ao trocar de página ou fechar).
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QFile, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QFont,
    QKeySequence,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..componentes.fluxo import LayoutDeFluxo
from ..dados import notas
from ..dados.notas import ESQUEMA, Referencia, ReferenciaInvalida
from ..servicos.notas import central
from ..tema.aplicar import aparencia
from ..tema.fontes import fonte_da_interface, fonte_mono
from ..tema.icones import IconeDoTema
from ..tema.tokens import TAMANHOS

ESPERA_DA_GRAVACAO_MS = 700
ESCALA_DOS_TITULOS = (1.75, 1.45, 1.25, 1.12, 1.05, 1.0)

_TITULO = re.compile(r"^(\s{0,3})(#{1,6})(\s+)(.*)$")
_CERCA = re.compile(r"^\s*(```|~~~)")
_CITACAO = re.compile(r"^(\s*>+\s?)(.*)$")
_LISTA = re.compile(r"^(\s*)([-*+]|\d+[.)])(\s+)(\[[ xX]\]\s+)?")
_REGUA = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_CODIGO = re.compile(r"`[^`\n]+`")
_NEGRITO = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_ITALICO = re.compile(r"(?<![*_\w])([*_])(?=\S)(.+?)(?<=\S)\1(?![*_\w])")
_TACHADO = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_LINK = re.compile(r"(!?)\[([^\]\n]*)\]\(([^)\s]*)\)")
_ENDERECO = re.compile(r"(?<![(<\w])https?://[^\s)>]+")


# ---------------------------------------------------------------------- o realce


class RealceDoMarkdown(QSyntaxHighlighter):
    """O Markdown realçado no próprio texto, com as cores do tema (refeito na troca)."""

    def __init__(self, documento: QTextDocument, fonte_base: QFont):
        super().__init__(documento)
        self.fonte_base = QFont(fonte_base)
        self._formatos()
        aparencia().mudou.connect(self._tema_mudou)

    def _tema_mudou(self, _tema) -> None:
        self._formatos()
        self.rehighlight()

    def _formatos(self) -> None:
        t = aparencia().tema

        def formato(cor: str | None = None, *, negrito=False, italico=False, fonte: QFont | None = None,
                    fundo: str | None = None, sublinhado=False, tachado=False) -> QTextCharFormat:
            f = QTextCharFormat()
            if fonte is not None:
                f.setFont(fonte, QTextCharFormat.FontPropertiesInheritanceBehavior.FontPropertiesSpecifiedOnly)
            if cor:
                f.setForeground(QColor(cor))
            if negrito:
                f.setFontWeight(QFont.Weight.Bold)
            if italico:
                f.setFontItalic(True)
            if fundo:
                f.setBackground(QColor(fundo))
            if sublinhado:
                f.setFontUnderline(True)
            if tachado:
                f.setFontStrikeOut(True)
            return f

        base = self.fonte_base.pixelSize() if self.fonte_base.pixelSize() > 0 else TAMANHOS["corpo"]
        self.titulos = []
        for escala in ESCALA_DOS_TITULOS:
            fonte = QFont(self.fonte_base)
            fonte.setPixelSize(round(base * escala))
            fonte.setWeight(QFont.Weight.Bold)
            self.titulos.append(formato(t.texto, fonte=fonte))
        mono = fonte_mono(max(10, base - 1))
        self.marca = formato(t.mudo)
        self.negrito = formato(negrito=True)
        self.italico = formato(italico=True)
        self.tachado = formato(t.mudo, tachado=True)
        self.codigo = formato(t.destaque, fonte=mono, fundo=t.afundada)
        self.citacao = formato(t.texto2, italico=True)
        self.lista = formato(t.acento, negrito=True)
        self.feita = formato(t.mudo, tachado=True)
        self.caixa = formato(t.acento, negrito=True)
        self.link = formato(t.acento, sublinhado=True)
        pequeno = QFont(self.fonte_base)
        pequeno.setPixelSize(max(9, base - 3))
        self.endereco = formato(t.mudo, fonte=pequeno)
        self.referencia = formato(t.destaque, negrito=True, fundo=t.afundada)
        self.imagem = formato(t.ok)
        self.regua = formato(t.mudo)

    def highlightBlock(self, texto: str) -> None:
        anterior = self.previousBlockState()
        if _CERCA.match(texto):
            self.setFormat(0, len(texto), self.codigo)
            self.setCurrentBlockState(0 if anterior == 1 else 1)
            return
        if anterior == 1:                                   # dentro de um bloco de código
            self.setFormat(0, len(texto), self.codigo)
            self.setCurrentBlockState(1)
            return
        self.setCurrentBlockState(0)
        m = _TITULO.match(texto)
        if m:
            nivel = len(m.group(2))
            self.setFormat(0, len(texto), self.titulos[nivel - 1])
            self.setFormat(len(m.group(1)), len(m.group(2)), self.marca)
            self._em_linha(texto, len(m.group(0)) - len(m.group(4)))
            return
        if _REGUA.match(texto):
            self.setFormat(0, len(texto), self.regua)
            return
        inicio = 0
        m = _CITACAO.match(texto)
        if m:
            self.setFormat(0, len(texto), self.citacao)
            self.setFormat(0, len(m.group(1)), self.marca)
            inicio = len(m.group(1))
        m = _LISTA.match(texto)
        if m:
            fim_do_marcador = m.end(3)
            self.setFormat(len(m.group(1)), len(m.group(2)), self.lista)
            if m.group(4):
                self.setFormat(fim_do_marcador, len(m.group(4)), self.caixa)
                if m.group(4)[1] in "xX":
                    self.setFormat(m.end(4), len(texto) - m.end(4), self.feita)
            inicio = max(inicio, m.end())
        self._em_linha(texto, inicio)

    def _em_linha(self, texto: str, inicio: int) -> None:
        """O que vale no meio da linha: o código, os links e as referências, o negrito, o itálico e o tachado."""
        ocupado = []
        for m in _CODIGO.finditer(texto, inicio):
            self.setFormat(m.start(), m.end() - m.start(), self.codigo)
            ocupado.append((m.start(), m.end()))
        for m in _LINK.finditer(texto, inicio):
            if any(a <= m.start() < b for a, b in ocupado):
                continue
            imagem, rotulo, endereco = m.group(1), m.group(2), m.group(3)
            comeco_do_rotulo = m.start() + len(imagem) + 1
            self.setFormat(m.start(), m.end() - m.start(), self.marca)
            if endereco.startswith(f"{ESQUEMA}:"):
                self.setFormat(comeco_do_rotulo, len(rotulo), self.referencia)
            else:
                self.setFormat(comeco_do_rotulo, len(rotulo), self.imagem if imagem else self.link)
            self.setFormat(m.end() - len(endereco) - 1, len(endereco), self.endereco)
            ocupado.append((m.start(), m.end()))
        for m in _ENDERECO.finditer(texto, inicio):
            if not any(a <= m.start() < b for a, b in ocupado):
                self.setFormat(m.start(), m.end() - m.start(), self.link)
        for expressao, formato in ((_NEGRITO, self.negrito), (_ITALICO, self.italico), (_TACHADO, self.tachado)):
            for m in expressao.finditer(texto, inicio):
                if any(a <= m.start() < b for a, b in ocupado):
                    continue
                for k in range(m.start(), m.end()):
                    atual = self.format(k)
                    atual.merge(formato)
                    self.setFormat(k, 1, atual)


# ---------------------------------------------------------------------- o editor


class EditorDeMarkdown(QPlainTextEdit):
    """O texto da página: o Markdown com o realce, as listas que continuam, os atalhos de marcação, o Ctrl+clique nos
    links e nas referências e as imagens coladas (``gravar_imagem``: quem sabe onde guardá-las)."""

    linkPedido = Signal(str)                      # o endereço de um link (Ctrl+clique)

    ATALHOS = {(Qt.Key.Key_B, False): "negrito", (Qt.Key.Key_I, False): "italico", (Qt.Key.Key_K, False): "link",
               (Qt.Key.Key_X, True): "tachado", (Qt.Key.Key_1, False): "h1", (Qt.Key.Key_2, False): "h2",
               (Qt.Key.Key_3, False): "h3", (Qt.Key.Key_L, True): "tarefa"}
    """(a tecla, com Shift) com o Ctrl -> a marcação. Ganham dos atalhos da janela enquanto o editor tem o foco."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("editor_do_caderno")
        self.setFont(fonte_da_interface(TAMANHOS["corpo"] + 1))
        self.setTabChangesFocus(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setPlaceholderText(self.tr("# Título\n\nEscreva à vontade: o Markdown vale (# títulos, **negrito**, "
                                        "- listas, - [ ] tarefas…). O clique direito num gráfico põe aqui uma "
                                        "referência a ele."))
        self.realce = RealceDoMarkdown(self.document(), self.font())
        self.gravar_imagem: Callable[[object], str | None] | None = None
        self.viewport().setMouseTracking(True)

    # -- as marcações

    def envolver(self, antes: str, depois: str | None = None, vazio: str = "") -> None:
        """Põe ``antes`` e ``depois`` em volta da seleção (sem ela, em volta de ``vazio``, que fica escolhido)."""
        depois = antes if depois is None else depois
        cursor = self.textCursor()
        texto = cursor.selectedText() or vazio
        cursor.beginEditBlock()
        cursor.insertText(f"{antes}{texto}{depois}")
        cursor.endEditBlock()
        if texto:
            cursor.setPosition(cursor.position() - len(depois) - len(texto))
            cursor.setPosition(cursor.position() + len(texto), QTextCursor.MoveMode.KeepAnchor)
        else:
            cursor.setPosition(cursor.position() - len(depois))
        self.setTextCursor(cursor)
        self.setFocus()

    def prefixar(self, prefixo: str, *, trocar: re.Pattern | None = None, numerar: bool = False) -> None:
        """Põe ``prefixo`` no começo de cada linha escolhida (``trocar``: o prefixo que ele substitui; se todas já o
        têm, tira). ``numerar``: 1., 2., 3."""
        cursor = self.textCursor()
        inicio, fim = sorted((cursor.anchor(), cursor.position()))
        documento = self.document()
        primeiro, ultimo = documento.findBlock(inicio), documento.findBlock(fim)
        blocos = []
        bloco = primeiro
        while bloco.isValid():
            blocos.append(bloco)
            if bloco == ultimo:
                break
            bloco = bloco.next()
        todos = all(b.text().lstrip().startswith(prefixo.strip()) for b in blocos) and not numerar
        cursor.beginEditBlock()
        for k, bloco in enumerate(blocos):
            texto = bloco.text()
            novo = texto
            if trocar is not None:
                novo = trocar.sub("", novo, count=1)
            if todos:
                novo = texto.replace(prefixo, "", 1)
            else:
                novo = (f"{k + 1}. " if numerar else prefixo) + novo.lstrip() if not novo.startswith(prefixo) \
                    else novo
            c = QTextCursor(bloco)
            c.select(QTextCursor.SelectionType.LineUnderCursor)
            c.insertText(novo)
        cursor.endEditBlock()
        self.setFocus()

    def titulo(self, nivel: int) -> None:
        self.prefixar("#" * nivel + " ", trocar=re.compile(r"^\s{0,3}#{1,6}\s+"))

    def marcar(self, nome: str) -> None:
        """Uma marcação da barra ou do atalho."""
        if nome == "negrito":
            self.envolver("**", vazio=self.tr("negrito"))
        elif nome == "italico":
            self.envolver("*", vazio=self.tr("itálico"))
        elif nome == "tachado":
            self.envolver("~~", vazio=self.tr("tachado"))
        elif nome == "codigo":
            self.envolver("`", vazio=self.tr("código"))
        elif nome == "link":
            self.envolver("[", "](https://)", vazio=self.tr("texto"))
        elif nome in ("h1", "h2", "h3"):
            self.titulo(int(nome[1]))
        elif nome == "lista":
            self.prefixar("- ", trocar=_LISTA)
        elif nome == "numerada":
            self.prefixar("1. ", trocar=_LISTA, numerar=True)
        elif nome == "tarefa":
            self.prefixar("- [ ] ", trocar=_LISTA)
        elif nome == "citacao":
            self.prefixar("> ")
        elif nome == "regua":
            self.inserir_linhas("---")
        elif nome == "tabela":
            self.inserir_linhas(self.tr("| Coluna | Coluna |\n| --- | --- |\n|  |  |"))
        elif nome == "bloco":
            self.inserir_linhas("```\n\n```", recuar=4)
        elif nome == "hora":
            self.insertPlainText(datetime.datetime.now().strftime("**%H:%M** "))

    def inserir_linhas(self, texto: str, recuar: int = 0) -> None:
        """Põe ``texto`` em linhas próprias, no cursor."""
        cursor = self.textCursor()
        antes = "" if cursor.atBlockStart() else "\n"
        cursor.insertText(f"{antes}{texto}\n")
        if recuar:
            cursor.setPosition(cursor.position() - recuar)
        self.setTextCursor(cursor)
        self.setFocus()

    def inserir(self, texto: str) -> None:
        """Põe ``texto`` no cursor, com um espaço antes quando ele vem colado a uma palavra."""
        cursor = self.textCursor()
        if not cursor.atBlockStart():
            anterior = self.document().characterAt(cursor.position() - 1)
            if anterior and not anterior.isspace():
                texto = " " + texto
        cursor.insertText(texto)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    # -- o teclado

    def event(self, evento) -> bool:
        if evento.type() == QEvent.Type.ShortcutOverride and \
                evento.modifiers() & Qt.KeyboardModifier.ControlModifier:
            shift = bool(evento.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if (Qt.Key(evento.key()), shift) in self.ATALHOS:
                evento.accept()                 # o atalho é do editor, não da janela (o Ctrl+B do painel...)
                return True
        return super().event(evento)

    def keyPressEvent(self, evento) -> None:
        if evento.modifiers() & Qt.KeyboardModifier.ControlModifier:
            shift = bool(evento.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            nome = self.ATALHOS.get((Qt.Key(evento.key()), shift))
            if nome is not None:
                self.marcar(nome)
                return
        if evento.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not evento.modifiers():
            if self._continuar_a_lista():
                return
        if evento.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and self._recuar(evento.key() == Qt.Key.Key_Backtab
                                                                                 or bool(evento.modifiers() &
                                                                                         Qt.KeyboardModifier.ShiftModifier)):
            return
        super().keyPressEvent(evento)

    def _continuar_a_lista(self) -> bool:
        """O Enter numa lista põe o próximo item (o número seguinte, a tarefa por fazer); num item vazio, acaba a
        lista. Na citação, a próxima linha também é citação, e a vazia acaba."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            return False
        linha = cursor.block().text()
        m = _LISTA.match(linha)
        if m is not None and cursor.positionInBlock() >= m.end():
            if not linha[m.end():].strip():
                cursor.select(QTextCursor.SelectionType.LineUnderCursor)       # o item vazio acaba a lista
                cursor.insertText("")
                return True
            marcador = m.group(2)
            if marcador[:-1].isdigit():
                marcador = f"{int(marcador[:-1]) + 1}{marcador[-1]}"
            caixa = "[ ] " if m.group(4) else ""
            cursor.insertText(f"\n{m.group(1)}{marcador}{m.group(3)}{caixa}")
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
            return True
        m = _CITACAO.match(linha)
        if m is not None and cursor.positionInBlock() >= len(m.group(1)):
            if not m.group(2).strip():
                cursor.select(QTextCursor.SelectionType.LineUnderCursor)
                cursor.insertText("")
            else:
                cursor.insertText("\n" + m.group(1))
                self.setTextCursor(cursor)
            return True
        return False

    def _recuar(self, para_tras: bool) -> bool:
        """Tab e Shift+Tab nas linhas de lista: um nível a mais ou a menos (2 espaços)."""
        cursor = self.textCursor()
        inicio, fim = sorted((cursor.anchor(), cursor.position()))
        documento = self.document()
        bloco, ultimo = documento.findBlock(inicio), documento.findBlock(fim)
        blocos = []
        while bloco.isValid():
            blocos.append(bloco)
            if bloco == ultimo:
                break
            bloco = bloco.next()
        if not all(_LISTA.match(b.text()) for b in blocos):
            return False
        cursor.beginEditBlock()
        for b in blocos:
            c = QTextCursor(b)
            if para_tras:
                espacos = len(b.text()) - len(b.text().lstrip(" "))
                c.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, min(2, espacos))
                c.removeSelectedText()
            else:
                c.insertText("  ")
        cursor.endEditBlock()
        return True

    # -- os links

    def endereco_em(self, posicao) -> str | None:
        """O endereço do link (ou da referência) no ponto do widget, ou ``None``."""
        cursor = self.cursorForPosition(posicao)
        texto, coluna = cursor.block().text(), cursor.positionInBlock()
        for m in _LINK.finditer(texto):
            if m.start() <= coluna <= m.end():
                return m.group(3)
        for m in _ENDERECO.finditer(texto):
            if m.start() <= coluna <= m.end():
                return m.group(0)
        return None

    def mouseMoveEvent(self, evento) -> None:
        super().mouseMoveEvent(evento)
        sobre = evento.modifiers() & Qt.KeyboardModifier.ControlModifier and \
            self.endereco_em(evento.position().toPoint())
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if sobre else Qt.CursorShape.IBeamCursor)

    def mouseReleaseEvent(self, evento) -> None:
        if evento.button() == Qt.MouseButton.LeftButton and \
                evento.modifiers() & Qt.KeyboardModifier.ControlModifier:
            endereco = self.endereco_em(evento.position().toPoint())
            if endereco:
                self.linkPedido.emit(endereco)
                return
        super().mouseReleaseEvent(evento)

    # -- as imagens coladas

    def canInsertFromMimeData(self, fonte) -> bool:
        return fonte.hasImage() or super().canInsertFromMimeData(fonte)

    def insertFromMimeData(self, fonte) -> None:
        if fonte.hasImage() and self.gravar_imagem is not None:
            markdown = self.gravar_imagem(fonte.imageData())
            if markdown:
                self.inserir_linhas(markdown)
                return
        if fonte.hasText():
            self.insertPlainText(fonte.text())         # só o texto: o caderno é Markdown
            return
        super().insertFromMimeData(fonte)


# ---------------------------------------------------------------------- o caderno


def _para_a_lixeira(caminho: Path) -> bool:
    foi = QFile.moveToTrash(str(caminho))
    return bool(foi[0] if isinstance(foi, tuple) else foi)


BOTOES_DE_MARCACAO = (
    ("h1", "H1", "Título (Ctrl+1)"), ("h2", "H2", "Subtítulo (Ctrl+2)"), ("h3", "H3", "Seção (Ctrl+3)"), None,
    ("negrito", "B", "Negrito (Ctrl+B)"), ("italico", "I", "Itálico (Ctrl+I)"),
    ("tachado", "S", "Tachado (Ctrl+Shift+X)"), ("codigo", "</>", "Código"), None,
    ("lista", "•", "Lista"), ("numerada", "1.", "Lista numerada"), ("tarefa", "☐", "Tarefa (Ctrl+Shift+L)"),
    ("citacao", "❝", "Citação"), None,
    ("link", "↗", "Link (Ctrl+K)"), ("tabela", "▦", "Tabela"), ("bloco", "{ }", "Bloco de código"),
    ("regua", "—", "Linha horizontal"), ("hora", "◷", "A hora de agora"),
)


class CadernoDeNotas(QWidget):
    """As páginas da ``pasta`` (criada na primeira página), uma aberta no editor. ``referencia_da_vista()`` e
    ``imagem_da_vista()``: o que os botões da vista à frente põem (quem sabe da vista é a janela)."""

    gravado = Signal(object)                       # o Path da página gravada

    def __init__(self, pasta: Path | Callable[[], Path], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("caderno_de_notas")
        self._pasta = pasta
        self.pagina: Path | None = None
        self.referencia_da_vista: Callable[[], Referencia | None] = lambda: None
        self.imagem_da_vista: Callable[[], tuple[object, str] | None] = lambda: None
        self._carregando = False
        self.lixeira: Callable[[Path], bool] = _para_a_lixeira      # os testes trocam (a lixeira de verdade)
        self._espera = QTimer(self)
        self._espera.setSingleShot(True)
        self._espera.setInterval(ESPERA_DA_GRAVACAO_MS)
        self._espera.timeout.connect(self.gravar)

        self.busca = QLineEdit()
        self.busca.setObjectName("busca_do_caderno")
        self.busca.setPlaceholderText(self.tr("Buscar nas páginas…"))
        self.busca.setClearButtonEnabled(True)
        self.busca.textChanged.connect(lambda _t: self.listar())
        self.nova = QToolButton()
        self.nova.setObjectName("nova_pagina")
        self.nova.setToolTip(self.tr("Nova página"))
        self.nova.setAutoRaise(True)
        IconeDoTema(self.nova, "mais")
        self.nova.clicked.connect(lambda: self.nova_pagina())
        topo = QHBoxLayout()
        topo.setContentsMargins(0, 0, 0, 0)
        topo.setSpacing(4)
        topo.addWidget(self.busca, 1)
        topo.addWidget(self.nova)
        self.lista = QListWidget()
        self.lista.setObjectName("paginas_do_caderno")
        self.lista.currentItemChanged.connect(self._escolheu)
        self.lista.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lista.customContextMenuRequested.connect(self._menu_da_lista)
        cima = QWidget()
        coluna_de_cima = QVBoxLayout(cima)
        coluna_de_cima.setContentsMargins(0, 0, 0, 0)
        coluna_de_cima.setSpacing(4)
        coluna_de_cima.addLayout(topo)
        coluna_de_cima.addWidget(self.lista)

        self.editor = EditorDeMarkdown()
        self.editor.textChanged.connect(self._mudou)
        self.editor.linkPedido.connect(self.abrir_endereco)
        self.editor.gravar_imagem = self._gravar_imagem
        self.vista_formatada = QTextBrowser()
        self.vista_formatada.setObjectName("pagina_formatada")
        self.vista_formatada.setOpenLinks(False)
        self.vista_formatada.anchorClicked.connect(lambda url: self.abrir_endereco(url.toString()))
        self.pilha = QStackedWidget()
        self.pilha.addWidget(self.editor)
        self.pilha.addWidget(self.vista_formatada)

        barra = QWidget()
        barra.setObjectName("barra_do_caderno")
        fluxo = LayoutDeFluxo(barra)
        fluxo.setContentsMargins(0, 0, 0, 0)
        self.botoes: dict[str, QToolButton] = {}
        for item in BOTOES_DE_MARCACAO:
            if item is None:
                espaco = QWidget()
                espaco.setFixedSize(4, 4)
                fluxo.addWidget(espaco)
                continue
            nome, rotulo, dica = item
            b = QToolButton()
            b.setObjectName(f"marcar_{nome}")
            b.setText(rotulo)
            b.setToolTip(self.tr(dica))
            b.setAutoRaise(True)
            b.setMinimumSize(QSize(26, 24))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            if nome == "negrito":
                f = b.font()
                f.setBold(True)
                b.setFont(f)
            elif nome == "italico":
                f = b.font()
                f.setItalic(True)
                b.setFont(f)
            b.clicked.connect(lambda _=False, n=nome: self.editor.marcar(n))
            fluxo.addWidget(b)
            self.botoes[nome] = b
        segunda = QHBoxLayout()
        segunda.setContentsMargins(0, 0, 0, 0)
        segunda.setSpacing(4)
        self.ref_da_vista = QToolButton()
        self.ref_da_vista.setObjectName("referencia_da_vista")
        self.ref_da_vista.setText(self.tr("Referência à vista"))
        self.ref_da_vista.setToolTip(self.tr("Um link para o que a vista à frente mostra (o clique nele volta até ali)"))
        self.ref_da_vista.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.ref_da_vista.setAutoRaise(True)
        IconeDoTema(self.ref_da_vista, "link")
        self.ref_da_vista.clicked.connect(self._referenciar_a_vista)
        self.imagem = QToolButton()
        self.imagem.setObjectName("imagem_da_vista")
        self.imagem.setText(self.tr("Imagem da vista"))
        self.imagem.setToolTip(self.tr("A imagem do gráfico à frente, guardada no caderno"))
        self.imagem.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.imagem.setAutoRaise(True)
        IconeDoTema(self.imagem, "imagem")
        self.imagem.clicked.connect(self._imagem_da_vista)
        self.ver = QToolButton()
        self.ver.setObjectName("ver_formatada")
        self.ver.setText(self.tr("Ver"))
        self.ver.setToolTip(self.tr("A página formatada (o clique numa referência leva ao gráfico)"))
        self.ver.setCheckable(True)
        self.ver.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.ver.setAutoRaise(True)
        IconeDoTema(self.ver, "olho", papel_ligado="acento")
        self.ver.toggled.connect(self.mostrar_formatada)
        segunda.addWidget(self.ref_da_vista)
        segunda.addWidget(self.imagem)
        segunda.addStretch(1)
        segunda.addWidget(self.ver)

        baixo = QWidget()
        coluna_de_baixo = QVBoxLayout(baixo)
        coluna_de_baixo.setContentsMargins(0, 0, 0, 0)
        coluna_de_baixo.setSpacing(4)
        coluna_de_baixo.addWidget(barra)
        coluna_de_baixo.addLayout(segunda)
        coluna_de_baixo.addWidget(self.pilha, 1)
        self.situacao = QLabel()
        self.situacao.setObjectName("texto_mudo")
        coluna_de_baixo.addWidget(self.situacao)

        self.divisoria = QSplitter(Qt.Orientation.Vertical)
        self.divisoria.setChildrenCollapsible(False)
        self.divisoria.addWidget(cima)
        self.divisoria.addWidget(baixo)
        self.divisoria.setStretchFactor(1, 1)
        self.divisoria.setSizes([96, 560])
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(8, 6, 8, 6)
        coluna.addWidget(self.divisoria)
        self._acao_do_atalho()
        self.listar()

    @property
    def pasta(self) -> Path:
        return Path(self._pasta() if callable(self._pasta) else self._pasta)

    def _acao_do_atalho(self) -> None:
        nova = QAction(self)
        nova.setShortcut(QKeySequence("Ctrl+Alt+N"))
        nova.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        nova.triggered.connect(lambda: self.nova_pagina())
        self.addAction(nova)

    # ------------------------------------------------------------------ as páginas

    def listar(self) -> None:
        """A lista das páginas (as da busca), com a aberta escolhida."""
        self.lista.blockSignals(True)
        try:
            self.lista.clear()
            for pagina in notas.buscar(self.pasta, self.busca.text()):
                item = QListWidgetItem(pagina.titulo)
                item.setData(Qt.ItemDataRole.UserRole, str(pagina.caminho))
                item.setToolTip(f"{pagina.caminho.name} · " + datetime.datetime.fromtimestamp(pagina.mudou_em)
                                .strftime(self.tr("mudada em %d/%m/%Y, %H:%M")))
                self.lista.addItem(item)
                if self.pagina is not None and pagina.caminho == self.pagina:
                    self.lista.setCurrentItem(item)
        finally:
            self.lista.blockSignals(False)
        if self.pagina is None and self.lista.count():
            self.abrir(Path(self.lista.item(0).data(Qt.ItemDataRole.UserRole)))
        self._mostrar_situacao()

    def _escolheu(self, item, _anterior) -> None:
        if item is not None:
            self.abrir(Path(item.data(Qt.ItemDataRole.UserRole)))

    def abrir(self, caminho: Path) -> None:
        """Abre a página (gravando antes a aberta)."""
        if self.pagina == caminho:
            return
        self.gravar()
        try:
            texto = caminho.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as erro:
            self.situacao.setText(self.tr("Não deu para abrir {}: {}").format(caminho.name, erro))
            return
        self.pagina = caminho
        self._carregando = True
        try:
            self.editor.setPlainText(texto)
        finally:
            self._carregando = False
        self.editor.document().setModified(False)
        if self.ver.isChecked():
            self._formatar()
        self._mostrar_situacao()

    def nova_pagina(self, titulo: str = "") -> Path:
        self.gravar()
        caminho = notas.nova_pagina(self.pasta, titulo)
        self.pagina = None
        self.abrir(caminho)
        self.listar()
        self.ver.setChecked(False)
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        return caminho

    def _mudou(self) -> None:
        if not self._carregando:
            self._espera.start()

    def gravar(self) -> bool:
        """Grava a página aberta, se ela mudou."""
        self._espera.stop()
        if self.pagina is None or not self.editor.document().isModified():
            return False
        try:
            notas.gravar(self.pagina, self.editor.toPlainText())
        except OSError as erro:
            self.situacao.setText(self.tr("Não deu para gravar: {}").format(erro))
            return False
        self.editor.document().setModified(False)
        titulo = notas.titulo_do_texto(self.editor.toPlainText(), self.pagina.stem)
        item = self.lista.currentItem()
        if item is not None and Path(item.data(Qt.ItemDataRole.UserRole)) == self.pagina:
            item.setText(titulo)
        self.situacao.setText(self.tr("Gravada às {}").format(datetime.datetime.now().strftime("%H:%M:%S")))
        self.gravado.emit(self.pagina)
        return True

    def _mostrar_situacao(self) -> None:
        if self.pagina is None:
            self.situacao.setText(self.tr("Nenhuma página ainda: escreva, e a primeira nasce sozinha."))
        else:
            self.situacao.setText(str(self.pagina))
        self.situacao.setToolTip(str(self.pasta))

    def _garantir_pagina(self) -> None:
        """Uma página aberta para escrever (sem nenhuma, uma nova)."""
        if self.pagina is None:
            self.nova_pagina()

    def _menu_da_lista(self, ponto) -> None:
        item = self.lista.itemAt(ponto)
        menu = QMenu(self)
        if item is not None:
            caminho = Path(item.data(Qt.ItemDataRole.UserRole))
            menu.addAction(self.tr("Pôr na lixeira…"), lambda: self.para_a_lixeira(caminho))
        menu.addAction(self.tr("Nova página"), lambda: self.nova_pagina())
        menu.addAction(self.tr("Abrir a pasta do caderno"),
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.pasta))))
        menu.exec(self.lista.viewport().mapToGlobal(ponto))

    def para_a_lixeira(self, caminho: Path, *, perguntar: bool = True) -> bool:
        """Põe a página na lixeira do sistema (dá para recuperar de lá), depois de perguntar."""
        if perguntar and QMessageBox.question(
                self, self.tr("Pôr na lixeira"),
                self.tr("Pôr a página “{}” na lixeira do sistema? Dá para recuperá-la de lá.").format(
                    notas.titulo_do_texto(caminho.read_text(encoding="utf-8"), caminho.stem))) \
                != QMessageBox.StandardButton.Yes:
            return False
        if caminho == self.pagina:
            self.gravar()
        if not self.lixeira(caminho):
            self.situacao.setText(self.tr("A lixeira não aceitou {}").format(caminho.name))
            return False
        if caminho == self.pagina:
            self.pagina = None
            self._carregando = True
            try:
                self.editor.clear()
            finally:
                self._carregando = False
        self.listar()
        return True

    # ------------------------------------------------------------------ ver formatada

    def mostrar_formatada(self, ver: bool = True) -> None:
        if self.ver.isChecked() != ver:
            self.ver.setChecked(ver)
            return
        if ver:
            self.gravar()
            self._formatar()
        self.pilha.setCurrentWidget(self.vista_formatada if ver else self.editor)
        for botao in self.botoes.values():
            botao.setEnabled(not ver)

    def _formatar(self) -> None:
        documento = self.vista_formatada.document()
        if self.pagina is not None:
            documento.setBaseUrl(QUrl.fromLocalFile(str(self.pagina.parent) + "/"))
            self.vista_formatada.setSearchPaths([str(self.pagina.parent)])
        documento.setDefaultFont(fonte_da_interface(TAMANHOS["corpo"] + 1))
        self.vista_formatada.setMarkdown(self.editor.toPlainText())
        # O ar entre os blocos (o Markdown do Qt cola os parágrafos): mais antes dos títulos, menos entre os itens.
        cursor = QTextCursor(documento)
        cursor.beginEditBlock()
        bloco = documento.begin()
        while bloco.isValid():
            formato = bloco.blockFormat()
            if formato.headingLevel():
                formato.setTopMargin(12 if bloco.previous().isValid() else 0)
                formato.setBottomMargin(4)
            elif bloco.textList() is not None:
                formato.setBottomMargin(2)
            else:
                formato.setBottomMargin(8)
            formato.setLineHeight(118, 1)                   # proporcional (QTextBlockFormat.ProportionalHeight)
            c = QTextCursor(bloco)
            c.setBlockFormat(formato)
            bloco = bloco.next()
        cursor.endEditBlock()

    # ------------------------------------------------------------------ as referências e os links

    def inserir_referencia(self, referencia: Referencia) -> None:
        """Põe o link da referência no cursor da página aberta (sem nenhuma, numa nova)."""
        self._garantir_pagina()
        self.mostrar_formatada(False)
        from ..componentes.numeros import separador_decimal
        self.editor.inserir(referencia.markdown(separador_decimal()) + " ")
        self.editor.setFocus()

    def inserir_texto(self, texto: str) -> None:
        self._garantir_pagina()
        self.mostrar_formatada(False)
        self.editor.inserir_linhas(texto)

    def abrir_endereco(self, endereco: str) -> None:
        if endereco.startswith(f"{ESQUEMA}:"):
            try:
                referencia = Referencia.de_url(endereco)
            except ReferenciaInvalida as erro:
                self.situacao.setText(str(erro))
                return
            central().irPedido.emit(referencia)
            return
        url = QUrl(endereco)
        if url.isRelative() and self.pagina is not None:
            url = QUrl.fromLocalFile(str((self.pagina.parent / endereco).resolve()))
        if url.scheme() in ("http", "https", "file", "mailto"):
            QDesktopServices.openUrl(url)

    def _referenciar_a_vista(self) -> None:
        referencia = self.referencia_da_vista()
        if referencia is None:
            self.situacao.setText(self.tr("Nenhuma vista de tempo ou de espectro à frente na Análise."))
            return
        self.inserir_referencia(referencia)

    def _imagem_da_vista(self) -> None:
        resultado = self.imagem_da_vista()
        if resultado is None:
            self.situacao.setText(self.tr("Nenhuma vista à frente na Análise."))
            return
        imagem, legenda = resultado
        markdown = self._gravar_imagem(imagem, legenda)
        if markdown:
            self.inserir_texto(markdown)

    def _gravar_imagem(self, imagem, legenda: str = "") -> str | None:
        """Grava a imagem (``QImage`` ou ``QPixmap``) na pasta das imagens e devolve o Markdown dela."""
        self._garantir_pagina()
        pasta = self.pasta / notas.PASTA_DAS_IMAGENS
        pasta.mkdir(parents=True, exist_ok=True)
        base = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        caminho = pasta / f"{base}.png"
        n = 2
        while caminho.exists():
            caminho = pasta / f"{base}-{n}.png"
            n += 1
        if not imagem.save(str(caminho), "PNG"):
            self.situacao.setText(self.tr("Não deu para gravar a imagem."))
            return None
        relativo = caminho.relative_to(self.pagina.parent if self.pagina is not None else self.pasta)
        legenda = (legenda or self.tr("imagem")).replace("[", "(").replace("]", ")")
        return f"![{legenda}]({relativo.as_posix()})"


__all__ = ["CadernoDeNotas", "EditorDeMarkdown", "RealceDoMarkdown"]
