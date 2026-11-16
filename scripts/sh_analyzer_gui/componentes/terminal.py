"""O terminal (docs/gui-plan.md, 11.8): um emulador xterm (o ``pyte``) pintado com o tema e a fonte mono, com a
rolagem, a seleção, a busca, o copiar e o colar.

Sem rede: recebe os bytes do PTY (:meth:`TelaDeTerminal.alimentar`) e devolve o que a pessoa digita
(``digitou(bytes)``) e o tamanho em células (``tamanhoMudou(colunas, linhas)``); a seção Terminal da Aquisição liga
as duas pontas à sessão na placa (``sh_placa/terminal.py``).

**O pyte só é importado na primeira tela** (:func:`_classe_da_tela`): a janela abre sem ele, como sem a rede da placa
(``tests/test_arquitetura.py``).

**O que o pyte não faz, a tela faz** (:class:`_Tela`, criada sobre a ``pyte.Screen``):

- *a rolagem:* a linha que sai por cima da tela inteira (sem margens, fora da tela alternativa) vai para o histórico
  (:data:`HISTORICO` linhas); o ``ESC[3J`` do ``clear`` o apaga, como no xterm;
- *a tela alternativa* (``?1049``, ``?1047``, ``?47``: o ``less``, o ``vim``, o ``htop``), que guarda a principal e a
  devolve na saída, com o cursor;
- *o redimensionamento* que guarda o que está perto do cursor: ao encolher, saem primeiro as linhas vazias de baixo, e
  depois as de cima, para o histórico (o pyte cortaria as de cima e deixaria o cursor no lugar, longe do prompt); ao
  crescer com o cursor na última linha, as linhas voltam do histórico, como no xterm e no VTE.

**A vazão:** o pyte é Python, e um ``cat`` grande chega mais rápido do que ele interpreta. A saída espera numa fila e
é interpretada em fatias de até :data:`FATIA_S` por volta do laço da interface: a tela segue respondendo (o Ctrl+C
chega). Se a fila passa de :data:`MAXIMO_NA_FILA`, o começo dela é pulado, com um aviso na tela (a gravação da sessão,
que não passa por aqui, tem tudo).

**As teclas** seguem o xterm (:func:`sequencia_da_tecla`): as setas no modo do cursor da aplicação (``?1h``), os
modificadores nas setas e nas teclas de função, o Alt como ``ESC``. O Ctrl+letra vai para a placa, mesmo quando a
janela tem um atalho com ela (o Ctrl+Z, o Ctrl+S); os do terminal são com Ctrl+Shift (copiar, colar, buscar), e o
Shift+PgUp/PgDn/Home/End rola o histórico.
"""

from __future__ import annotations

import math
import time
from collections import deque
from itertools import groupby

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QClipboard,
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QFrame, QMenu

from ..tema.aplicar import aparencia
from ..tema.fontes import fonte_mono
from ..tema.tokens import TAMANHOS, Tema

HISTORICO = 10_000
"""As linhas guardadas acima da tela (a rolagem)."""

FATIA_S = 0.008
"""O tempo de interpretação da saída por volta do laço da interface."""

PEDACO = 4096
MAXIMO_NA_FILA = 4 * 1024 * 1024
MARGEM = 6
CARACTERES_DE_PALAVRA = "-#%&+,./:=?@_~"
"""Além das letras e dos números: o duplo clique pega um caminho, um endereço, um ``debian@192.168.6.2`` inteiro."""

NOMES_ANSI = ("black", "red", "green", "brown", "blue", "magenta", "cyan", "white")
ALTERNATIVAS = (1049, 1047, 47)
BRACKETED_PASTE = 2004 << 5          # os modos privados no pyte: o número deslocado de 5 bits
CURSOR_DA_APLICACAO = 1 << 5         # o DECCKM

_Tela = None


def _classe_da_tela():
    """A tela do pyte com a rolagem, a tela alternativa e o redimensionamento (a doc do módulo). Criada na primeira
    chamada, com o pyte importado aqui."""
    global _Tela
    if _Tela is not None:
        return _Tela
    from collections import defaultdict

    import pyte
    from pyte.screens import Margins, StaticDefaultDict

    class Tela(pyte.Screen):
        def __init__(self, colunas: int, linhas: int, historico: int, responder):
            self.historico: deque = deque(maxlen=historico)
            self.textos: deque = deque(maxlen=historico)     # o texto de cada linha do histórico, feito na busca
            self.guardadas = 0               # quantas linhas já foram para o histórico: o número da linha 0 da tela
            self._principal = None           # a tela principal, guardada durante a alternativa
            self._responder = responder
            super().__init__(colunas, linhas)

        @property
        def alternativa(self) -> bool:
            return self._principal is not None

        def _nova(self):
            return defaultdict(lambda: StaticDefaultDict(self.default_char))

        def _guardar(self, linha) -> None:
            self.historico.append(linha)
            self.textos.append(None)
            self.guardadas += 1

        def apagar_o_historico(self) -> None:
            self.historico.clear()
            self.textos.clear()

        def reset(self) -> None:
            self._principal = None
            super().reset()

        def index(self) -> None:
            topo, base = self.margins or Margins(0, self.lines - 1)
            if self.cursor.y == base and topo == 0 and not self.alternativa:
                self._guardar(self.buffer[0])
            super().index()

        def erase_in_display(self, how: int = 0, *args, **kwargs) -> None:
            super().erase_in_display(how, *args, **kwargs)
            if how == 3:
                self.apagar_o_historico()

        def set_mode(self, *modes, **kwargs) -> None:
            if kwargs.get("private") and (pedidos := [m for m in modes if m in ALTERNATIVAS]):
                self._entrar_na_alternativa(1049 in pedidos)
                modes = tuple(m for m in modes if m not in ALTERNATIVAS)
            super().set_mode(*modes, **kwargs)

        def reset_mode(self, *modes, **kwargs) -> None:
            if kwargs.get("private") and (pedidos := [m for m in modes if m in ALTERNATIVAS]):
                self._sair_da_alternativa(1049 in pedidos)
                modes = tuple(m for m in modes if m not in ALTERNATIVAS)
            super().reset_mode(*modes, **kwargs)

        def _entrar_na_alternativa(self, com_o_cursor: bool) -> None:
            if self.alternativa:
                return
            if com_o_cursor:
                self.save_cursor()
            self._principal, self.buffer = self.buffer, self._nova()
            self.dirty.update(range(self.lines))

        def _sair_da_alternativa(self, com_o_cursor: bool) -> None:
            if not self.alternativa:
                return
            principal, self._principal = self._principal, None
            for y in [y for y in principal if y >= self.lines]:      # o que a tela perdeu enquanto estava na outra
                del principal[y]
            for linha in principal.values():
                for x in [x for x in linha if x >= self.columns]:
                    del linha[x]
            self.buffer = principal
            if com_o_cursor:
                self.restore_cursor()
            self.dirty.update(range(self.lines))

        def resize(self, lines: int | None = None, columns: int | None = None) -> None:
            lines, columns = lines or self.lines, columns or self.columns
            if (lines, columns) == (self.lines, self.columns):
                return
            if lines < self.lines:
                self._encolher(self.lines - lines)
            elif lines > self.lines and not self.alternativa and self.cursor.y == self.lines - 1:
                self._crescer(lines - self.lines)
            if columns < self.columns:
                for linha in self.buffer.values():
                    for x in [x for x in linha if x >= columns]:
                        del linha[x]
                self.tabstops = {t for t in self.tabstops if t < columns}
            else:
                self.tabstops |= {t for t in range(8, columns, 8) if t >= self.columns}
            self.lines, self.columns = lines, columns
            self.set_margins()
            self.cursor.x = min(self.cursor.x, columns)
            self.cursor.y = min(self.cursor.y, lines - 1)
            self.dirty.update(range(lines))

        def _encolher(self, sobra: int) -> None:
            vazias = 0
            for y in range(self.lines - 1, self.cursor.y, -1):
                if not _linha_vazia(self.buffer.get(y)):
                    break
                vazias += 1
            de_baixo = min(sobra, vazias)
            for y in range(self.lines - de_baixo, self.lines):
                self.buffer.pop(y, None)
            de_cima = sobra - de_baixo
            if not de_cima:
                return
            antigas = dict(self.buffer)
            self.buffer.clear()
            if not self.alternativa:
                for y in range(de_cima):
                    self._guardar(antigas.get(y) or StaticDefaultDict(self.default_char))
            for y, linha in antigas.items():
                if de_cima <= y < self.lines:
                    self.buffer[y - de_cima] = linha
            self.cursor.y = max(0, self.cursor.y - de_cima)

        def _crescer(self, falta: int) -> None:
            voltam = min(falta, len(self.historico))
            if not voltam:
                return
            antigas = dict(self.buffer)
            self.buffer.clear()
            for y, linha in antigas.items():
                self.buffer[y + voltam] = linha
            for y in range(voltam - 1, -1, -1):
                self.buffer[y] = self.historico.pop()
                self.textos.pop()
            self.guardadas -= voltam
            self.cursor.y += voltam

        def write_process_input(self, data: str) -> None:
            self._responder(data)

    _Tela = Tela
    return Tela


def _linha_vazia(linha) -> bool:
    return linha is None or all(c.data in (" ", "") and c.bg == "default" and not c.reverse for c in linha.values())


def texto_da_linha(linha, colunas: int) -> tuple[str, list[int]]:
    """O texto de uma linha da tela (sem a metade de trás dos caracteres largos) e a coluna de cada caractere."""
    texto, onde = [], []
    for x in range(colunas):
        c = linha[x].data if linha is not None else " "
        if c == "":
            continue
        texto.append(c)
        onde.extend([x] * len(c))
    return "".join(texto), onde


# As teclas ----------------------------------------------------------------------------------------------------------

K = Qt.Key
_SETAS = {K.Key_Up: "A", K.Key_Down: "B", K.Key_Right: "C", K.Key_Left: "D", K.Key_Home: "H", K.Key_End: "F"}
_F1_A_F4 = {K.Key_F1: "P", K.Key_F2: "Q", K.Key_F3: "R", K.Key_F4: "S"}
_COM_TIL = {K.Key_Insert: 2, K.Key_Delete: 3, K.Key_PageUp: 5, K.Key_PageDown: 6, K.Key_F5: 15, K.Key_F6: 17,
            K.Key_F7: 18, K.Key_F8: 19, K.Key_F9: 20, K.Key_F10: 21, K.Key_F11: 23, K.Key_F12: 24}
_CTRL_SIMBOLOS = {K.Key_At: "\x00", K.Key_Space: "\x00", K.Key_2: "\x00", K.Key_BracketLeft: "\x1b", K.Key_3: "\x1b",
                  K.Key_Backslash: "\x1c", K.Key_4: "\x1c", K.Key_BracketRight: "\x1d", K.Key_5: "\x1d",
                  K.Key_AsciiCircum: "\x1e", K.Key_6: "\x1e", K.Key_Underscore: "\x1f", K.Key_Minus: "\x1f",
                  K.Key_7: "\x1f", K.Key_Slash: "\x1f", K.Key_8: "\x7f", K.Key_Question: "\x7f"}


def sequencia_da_tecla(tecla: int, modificadores: Qt.KeyboardModifier, texto: str,
                       cursor_da_aplicacao: bool = False) -> bytes:
    """O que o xterm manda para uma tecla (vazio: nada a mandar)."""
    m = Qt.KeyboardModifier
    shift, alt, ctrl = (bool(modificadores & m.ShiftModifier), bool(modificadores & m.AltModifier),
                        bool(modificadores & m.ControlModifier))
    if ctrl and alt and texto.isprintable() and texto:     # o AltGr do Windows: Ctrl+Alt, com o caractere pronto
        return texto.encode()
    codigo = 1 + shift + 2 * alt + 4 * ctrl
    if tecla in _SETAS:
        letra = _SETAS[tecla]
        if codigo > 1:
            return f"\x1b[1;{codigo}{letra}".encode()
        return (("\x1bO" if cursor_da_aplicacao else "\x1b[") + letra).encode()
    if tecla in _F1_A_F4:
        letra = _F1_A_F4[tecla]
        return (f"\x1b[1;{codigo}{letra}" if codigo > 1 else f"\x1bO{letra}").encode()
    if tecla in _COM_TIL:
        n = _COM_TIL[tecla]
        return (f"\x1b[{n};{codigo}~" if codigo > 1 else f"\x1b[{n}~").encode()
    prefixo = "\x1b" if alt else ""
    if tecla in (K.Key_Return, K.Key_Enter):
        return (prefixo + "\r").encode()
    if tecla == K.Key_Backspace:
        return (prefixo + ("\x08" if ctrl else "\x7f")).encode()
    if tecla == K.Key_Backtab or (tecla == K.Key_Tab and shift):
        return b"\x1b[Z"
    if tecla == K.Key_Tab:
        return b"\t"
    if tecla == K.Key_Escape:
        return b"\x1b"
    if ctrl:
        if K.Key_A <= tecla <= K.Key_Z:
            return (prefixo + chr(tecla - K.Key_A + 1)).encode()
        if tecla in _CTRL_SIMBOLOS:
            return (prefixo + _CTRL_SIMBOLOS[tecla]).encode()
    return (prefixo + texto).encode() if texto else b""


def tecla_do_terminal(tecla: int, modificadores: Qt.KeyboardModifier) -> bool:
    """Se a tecla é do terminal, mesmo havendo um atalho da janela com ela (o ``ShortcutOverride``). Ficam com a
    janela: o Ctrl+Shift+letra ou número (os atalhos do próprio terminal e os da janela), o Ctrl+número que não é um
    caractere de controle, o Ctrl+Tab e o Ctrl+PgUp/PgDn (trocar de aba)."""
    m = Qt.KeyboardModifier
    ctrl, shift = bool(modificadores & m.ControlModifier), bool(modificadores & m.ShiftModifier)
    letra_ou_numero = K.Key_A <= tecla <= K.Key_Z or K.Key_0 <= tecla <= K.Key_9
    if ctrl and shift and letra_ou_numero:
        return False
    if ctrl and (K.Key_0 <= tecla <= K.Key_9 and tecla not in _CTRL_SIMBOLOS
                 or tecla in (K.Key_Tab, K.Key_Backtab, K.Key_PageUp, K.Key_PageDown)):
        return False
    return True


# A tela ---------------------------------------------------------------------------------------------------------------

class _Cores:
    """As cores do tema para o terminal, em ``QColor``, por nome do pyte (o ``default``, as 16 da ANSI, as 256 e as
    de 24 bits)."""

    def __init__(self, tema: Tema):
        import pyte.graphics as g

        self.fundo, self.texto = QColor(tema.afundada), QColor(tema.texto)
        self.cursor, self.cursor_texto = QColor(tema.destaque), QColor(tema.destaque_texto)
        self.selecao, self.selecao_texto = QColor(tema.acento), QColor(tema.acento_texto)
        self._nomes = {}
        for i, nome in enumerate(NOMES_ANSI):
            self._nomes[nome] = QColor(tema.ansi[i])
            self._nomes["bright" + nome] = QColor(tema.ansi[8 + i])
        for i in range(16):                      # as 16 primeiras das 256 são as do tema, e não as do xterm
            self._nomes.setdefault(g.FG_BG_256[i], QColor(tema.ansi[i]))
        self._outras: dict[str, QColor] = {}

    def de(self, nome: str, frente: bool) -> QColor:
        if nome == "default":
            return self.texto if frente else self.fundo
        cor = self._nomes.get(nome)
        if cor is None:
            cor = self._outras.get(nome)
            if cor is None:
                cor = QColor("#" + nome) if len(nome) == 6 else (self.texto if frente else self.fundo)
                if not cor.isValid():
                    cor = self.texto if frente else self.fundo
                self._outras[nome] = cor
        return cor


class TelaDeTerminal(QAbstractScrollArea):
    """O terminal: a tela, a rolagem com a barra, a seleção com o mouse, a busca, o copiar e o colar."""

    digitou = Signal(bytes)
    tamanhoMudou = Signal(int, int)          # colunas, linhas
    tituloMudou = Signal(str)
    buscaPedida = Signal()

    def __init__(self, parent=None, *, colunas: int = 80, linhas: int = 24, historico: int = HISTORICO):
        super().__init__(parent)
        import pyte

        self.setObjectName("terminal")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)   # sem a barra mudar o nº de colunas
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.tela = _classe_da_tela()(colunas, linhas, historico, self._responder)
        self._fluxo = pyte.ByteStream(self.tela)
        self._fila = bytearray()
        self.puladas = 0                     # bytes da saída pulados na tela (a fila cheia)
        self._interpretar = QTimer(self, singleShot=True, interval=0)
        self._interpretar.timeout.connect(lambda: self._interpretar_um_pouco())
        self._avisar_tamanho = QTimer(self, singleShot=True, interval=50)
        self._avisar_tamanho.timeout.connect(lambda: self.tamanhoMudou.emit(self.tela.columns, self.tela.lines))
        self._rolagem = 0                    # linhas acima da tela ao vivo (0: embaixo, acompanhando a saída)
        self._roda = 0.0
        self._ancora: tuple[int, int] | None = None
        self._ponta: tuple[int, int] | None = None
        self._modo_de_selecao = "caractere"
        self._ultimo_duplo = 0.0
        self.titulo = ""
        self._cores = _Cores(aparencia().tema)
        self._medir(fonte_mono(TAMANHOS["corpo"]))
        aparencia().mudou.connect(self._tema_mudou)
        self.verticalScrollBar().setSingleStep(1)
        self.verticalScrollBar().valueChanged.connect(self._barra_mexeu)
        self._atualizar_barra()

    # --- a entrada e a saída -----------------------------------------------------------------------------------------

    def alimentar(self, dados: bytes) -> None:
        """A saída do PTY. Interpretada aos poucos, no laço da interface (a doc do módulo)."""
        self._fila += dados
        if len(self._fila) > MAXIMO_NA_FILA:
            corte = len(self._fila) - MAXIMO_NA_FILA // 4
            fim_de_linha = self._fila.find(b"\n", corte)
            corte = fim_de_linha + 1 if fim_de_linha >= 0 else corte
            self.puladas += corte
            del self._fila[:corte]
            mb = f"{self.puladas / 1e6:.1f}".replace(".", ",")
            aviso = f"\x18\x1b[0m\r\n\x1b[7m … a saída chegou mais rápido do que a tela desenha: {mb} MB pulados aqui … \x1b[0m\r\n"
            self._fila[:0] = aviso.encode()
        if not self._interpretar.isActive():
            self._interpretar.start()

    def interpretar_tudo(self) -> None:
        """Interpreta a fila inteira agora (os testes)."""
        self._interpretar_um_pouco(sem_limite=True)

    def _interpretar_um_pouco(self, sem_limite: bool = False) -> None:
        inicio, antes = time.perf_counter(), self.tela.guardadas
        while self._fila and (sem_limite or time.perf_counter() - inicio < FATIA_S):
            pedaco = bytes(self._fila[:PEDACO])
            del self._fila[:PEDACO]
            self._fluxo.feed(pedaco)
        if self._fila and not sem_limite:
            self._interpretar.start()
        novas = self.tela.guardadas - antes
        if self._rolagem and novas > 0:      # rolado para cima: o que se lê fica parado
            self._rolagem = min(self._rolagem + novas, len(self.tela.historico))
        self._atualizar_barra()
        if self.tela.title != self.titulo:
            self.titulo = self.tela.title
            self.tituloMudou.emit(self.titulo)
        self.viewport().update()

    def _responder(self, texto: str) -> None:
        """As respostas do terminal que a aplicação pede (a posição do cursor, a identificação)."""
        self.digitou.emit(texto.encode())

    def _enviar(self, dados: bytes) -> None:
        if dados:
            self._ir_para_o_fim()
            self.digitou.emit(dados)

    def escrever(self, texto: str) -> None:
        """Escreve ``texto`` como se fosse digitado (o atalho de um comando: sem o Enter, que é da pessoa)."""
        self._enviar(texto.encode())
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def colar(self, texto: str) -> None:
        """Cola ``texto``: as quebras viram o Enter do terminal, e com o *bracketed paste* ligado (o bash 5.1 liga)
        vai entre as marcas, para o shell não rodar as linhas uma a uma."""
        if not texto:
            return
        texto = texto.replace("\r\n", "\r").replace("\n", "\r")
        if BRACKETED_PASTE in self.tela.mode:
            texto = "\x1b[200~" + texto.replace("\x1b[201~", "") + "\x1b[201~"
        self._enviar(texto.encode())

    # --- as medidas e o tamanho --------------------------------------------------------------------------------------

    def _medir(self, fonte: QFont) -> None:
        self._fonte = fonte
        self._negrito, self._italico, self._negrito_italico = QFont(fonte), QFont(fonte), QFont(fonte)
        self._negrito.setBold(True)
        self._italico.setItalic(True)
        self._negrito_italico.setBold(True)
        self._negrito_italico.setItalic(True)
        m = QFontMetricsF(fonte)
        self._larg = m.horizontalAdvance("M" * 100) / 100      # o avanço de uma sequência, como o drawText faz
        self._alt = math.ceil(m.lineSpacing())
        self._base = m.ascent() + (self._alt - m.height()) / 2
        self._sublinhado = min(self._alt - 1.0, self._base + max(1.0, m.underlinePos()))
        self._mesma_largura_em_negrito = abs(QFontMetricsF(self._negrito).horizontalAdvance("M" * 100) / 100
                                             - self._larg) < 0.01

    @property
    def colunas(self) -> int:
        return self.tela.columns

    @property
    def linhas(self) -> int:
        return self.tela.lines

    def tamanho_para(self, colunas: int, linhas: int) -> QSize:
        """O tamanho do widget (com a barra) para ``colunas`` × ``linhas``."""
        largura = math.ceil(colunas * self._larg) + 2 * MARGEM + self.verticalScrollBar().sizeHint().width()
        return QSize(largura, linhas * self._alt + 2 * MARGEM)

    def sizeHint(self):
        return self.tamanho_para(80, 24)

    def minimumSizeHint(self):
        return self.tamanho_para(20, 4)

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        area = self.viewport().size()
        colunas = max(2, int((area.width() - 2 * MARGEM) // self._larg))
        linhas = max(1, int((area.height() - 2 * MARGEM) // self._alt))
        if (colunas, linhas) != (self.tela.columns, self.tela.lines):
            self.tela.resize(linhas, colunas)
            self._rolagem = min(self._rolagem, len(self.tela.historico))
            self._atualizar_barra()
            self._avisar_tamanho.start()     # para o PTY, quando o arrastar da janela para

    # --- a rolagem ---------------------------------------------------------------------------------------------------

    def _atualizar_barra(self) -> None:
        barra, n = self.verticalScrollBar(), len(self.tela.historico)
        barra.blockSignals(True)
        barra.setRange(0, n)
        barra.setPageStep(self.tela.lines)
        barra.setValue(n - self._rolagem)
        barra.blockSignals(False)

    def _barra_mexeu(self, valor: int) -> None:
        self._rolagem = len(self.tela.historico) - valor
        self.viewport().update()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        self.viewport().update()

    def rolar(self, linhas: int) -> None:
        """Rola o histórico (positivo: para cima)."""
        self._rolagem = max(0, min(len(self.tela.historico), self._rolagem + linhas))
        self._atualizar_barra()
        self.viewport().update()

    def _ir_para_o_fim(self) -> None:
        if self._rolagem:
            self.rolar(-self._rolagem)

    @property
    def rolagem(self) -> int:
        return self._rolagem

    def limpar_a_rolagem(self) -> None:
        self.tela.apagar_o_historico()
        self._rolagem = 0
        self._ancora = self._ponta = None
        self._atualizar_barra()
        self.viewport().update()

    # --- as linhas por número ----------------------------------------------------------------------------------------
    # O número de uma linha não muda quando ela sobe para o histórico: a linha y da tela é a ``guardadas + y``.

    def _primeira(self) -> int:
        return self.tela.guardadas - len(self.tela.historico)

    def _linha(self, numero: int):
        i = numero - self._primeira()
        n = len(self.tela.historico)
        if 0 <= i < n:
            return self.tela.historico[i]
        if n <= i < n + self.tela.lines:
            return self.tela.buffer.get(i - n)
        return None

    def _texto(self, numero: int) -> tuple[str, list[int]]:
        i = numero - self._primeira()
        if 0 <= i < len(self.tela.historico):            # as do histórico não mudam mais: o texto fica guardado
            feito = self.tela.textos[i]
            if feito is None:
                feito = self.tela.textos[i] = texto_da_linha(self.tela.historico[i], self.tela.columns)
            return feito
        return texto_da_linha(self._linha(numero), self.tela.columns)

    def _numero_no_topo(self) -> int:
        return self.tela.guardadas - self._rolagem

    def linhas_visiveis(self) -> list[str]:
        """O texto das linhas na tela agora (com a rolagem), sem os espaços do fim."""
        topo = self._numero_no_topo()
        return [self._texto(topo + y)[0].rstrip() for y in range(self.tela.lines)]

    def retangulo_da_celula(self, coluna: int, linha: int) -> QRect:
        """Onde fica a célula (``coluna``, ``linha`` da tela visível) no viewport."""
        x0, x1 = MARGEM + coluna * self._larg, MARGEM + (coluna + 1) * self._larg
        return QRect(round(x0), MARGEM + linha * self._alt, round(x1) - round(x0), self._alt)

    # --- a seleção ---------------------------------------------------------------------------------------------------

    def _posicao(self, ponto: QPoint, borda: bool) -> tuple[int, int]:
        """A célula sob o ponto (número da linha, coluna); ``borda``: a fronteira entre células mais perto."""
        x = (ponto.x() - MARGEM) / self._larg
        coluna = round(x) if borda else math.floor(x)
        coluna = max(0, min(self.tela.columns if borda else self.tela.columns - 1, coluna))
        y = max(0, min(self.tela.lines - 1, (ponto.y() - MARGEM) // self._alt))
        return self._numero_no_topo() + int(y), coluna

    def _selecao(self) -> tuple[tuple[int, int], tuple[int, int]] | None:
        """O começo (incluído) e o fim (excluído), ordenados, com a palavra ou a linha completadas."""
        if self._ancora is None or self._ponta is None:
            return None
        inicio, fim = sorted((self._ancora, self._ponta))
        if self._modo_de_selecao == "palavra":
            inicio, fim = (inicio[0], self._palavra(inicio)[0]), (fim[0], self._palavra(fim)[1])
        elif self._modo_de_selecao == "linha":
            inicio, fim = (inicio[0], 0), (fim[0], self.tela.columns)
        return (inicio, fim) if inicio < fim else None

    def _palavra(self, onde: tuple[int, int]) -> tuple[int, int]:
        linha = self._linha(onde[0])

        def de_palavra(x):
            c = linha[x].data if linha is not None else " "
            return c != "" and (c.isalnum() or c in CARACTERES_DE_PALAVRA)

        x = min(onde[1], self.tela.columns - 1)
        if not de_palavra(x):
            return x, x + 1
        a, b = x, x
        while a > 0 and de_palavra(a - 1):
            a -= 1
        while b < self.tela.columns - 1 and de_palavra(b + 1):
            b += 1
        return a, b + 1

    def selecionado(self) -> str:
        """O texto selecionado, uma linha da tela por linha, sem os espaços do fim de cada uma."""
        selecao = self._selecao()
        if selecao is None:
            return ""
        (l0, c0), (l1, c1) = selecao
        partes = []
        for numero in range(l0, l1 + 1):
            linha = self._linha(numero)
            de, ate = (c0 if numero == l0 else 0), (c1 if numero == l1 else self.tela.columns)
            texto = "".join(linha[x].data if linha is not None else " " for x in range(de, ate))
            partes.append(texto.rstrip())
        return "\n".join(partes)

    def selecionar_tudo(self) -> None:
        self._modo_de_selecao = "caractere"
        self._ancora, self._ponta = (self._primeira(), 0), (self.tela.guardadas + self.tela.lines - 1,
                                                             self.tela.columns)
        self.viewport().update()

    def copiar(self) -> bool:
        texto = self.selecionado()
        if texto:
            QGuiApplication.clipboard().setText(texto)
        return bool(texto)

    def colar_da_area_de_transferencia(self, modo=None) -> None:
        area = QGuiApplication.clipboard()
        self.colar(area.text() if modo is None else area.text(modo))

    # --- a busca -----------------------------------------------------------------------------------------------------

    def buscar(self, texto: str, para_tras: bool = True, de_novo: bool = False) -> bool:
        """Procura ``texto`` (sem diferenciar maiúsculas) no histórico e na tela, para cima (``para_tras``) ou para
        baixo, a partir da seleção (ou do fim, ou do começo), dando a volta. A achada fica selecionada e à vista.
        ``de_novo``: a próxima depois da selecionada; sem ele, a selecionada ainda serve (a busca a cada tecla, com o
        texto crescendo)."""
        if not texto:
            return False
        agulha = texto.lower()
        primeira, ultima = self._primeira(), self.tela.guardadas + self.tela.lines - 1
        total = ultima - primeira + 1
        selecao = self._selecao()
        if selecao is None:
            partida, coluna = (ultima if para_tras else primeira), None
        else:
            (partida, coluna), _ = selecao
        for passo in range(total + 1):          # a linha de partida entra duas vezes: o lado de lá dela, no fim
            numero = primeira + (partida - primeira + (-passo if para_tras else passo)) % total
            original, onde = self._texto(numero)
            linha = original.lower() if len(original.lower()) == len(original) else original
            limitada = passo == 0 and coluna is not None
            if para_tras:
                ate = _indice(onde, coluna if de_novo else coluna + 1) if limitada else len(linha)
                i = linha.rfind(agulha, 0, ate - 1 + len(agulha)) if ate > 0 else -1
            else:
                i = linha.find(agulha, _indice(onde, coluna + 1 if de_novo else coluna) if limitada else 0)
            if i >= 0:
                ultimo = i + len(agulha) - 1
                self._modo_de_selecao = "caractere"
                self._ancora = (numero, onde[i])
                self._ponta = (numero, onde[ultimo] + (2 if _largo(linha[ultimo]) else 1))
                self._mostrar(numero)
                return True
        return False

    def _mostrar(self, numero: int) -> None:
        topo = self._numero_no_topo()
        if not topo <= numero < topo + self.tela.lines:
            self._rolagem = max(0, min(len(self.tela.historico), self.tela.guardadas - (numero - self.tela.lines // 2)))
            self._atualizar_barra()
        self.viewport().update()

    # --- o tema ------------------------------------------------------------------------------------------------------

    def _tema_mudou(self, tema: Tema) -> None:
        self._cores = _Cores(tema)
        self.viewport().update()

    # --- a pintura ---------------------------------------------------------------------------------------------------

    def paintEvent(self, evento) -> None:
        p = QPainter(self.viewport())
        cores, tela = self._cores, self.tela
        p.fillRect(self.viewport().rect(), cores.fundo)
        topo, selecao = self._numero_no_topo(), self._selecao()
        for y in range(tela.lines):
            self._pintar_linha(p, y, topo + y, selecao)
        self._pintar_cursor(p)
        p.end()

    def _pintar_linha(self, p: QPainter, y: int, numero: int, selecao) -> None:
        """Uma linha, em corridas de células com as mesmas cores e o mesmo estilo (um ``drawText`` por corrida)."""
        linha, cores, colunas = self._linha(numero), self._cores, self.tela.columns
        sel_de = sel_ate = -1
        if selecao is not None and selecao[0][0] <= numero <= selecao[1][0]:
            sel_de = selecao[0][1] if numero == selecao[0][0] else 0
            sel_ate = selecao[1][1] if numero == selecao[1][0] else colunas
        sem_estilo = (False, False, False, False)
        celulas = []
        for x in range(colunas):
            c = linha[x] if linha is not None else None
            if c is None:
                dado, frente, fundo, estilo = " ", cores.texto, cores.fundo, sem_estilo
            else:
                dado, frente, fundo = c.data, cores.de(c.fg, True), cores.de(c.bg, False)
                if c.reverse:
                    frente, fundo = fundo, frente
                estilo = (c.bold, c.italics, c.underscore, c.strikethrough)
            if sel_de <= x < sel_ate:
                frente, fundo = cores.selecao_texto, cores.selecao
            celulas.append((dado, frente, fundo, estilo))
        topo, x = MARGEM + y * self._alt, 0
        for _, grupo in groupby(celulas, key=lambda c: (c[1].rgba(), c[2].rgba(), c[3])):
            grupo = list(grupo)
            _, frente, fundo, estilo = grupo[0]
            self._pintar_corrida(p, topo, x, [c[0] for c in grupo], estilo, frente, fundo)
            x += len(grupo)

    def _pintar_corrida(self, p: QPainter, topo: float, inicio: int, corrida: list[str], estilo, frente: QColor,
                        fundo: QColor) -> None:
        negrito, italico, sublinhado, riscado = estilo
        x0 = MARGEM + inicio * self._larg
        largura = len(corrida) * self._larg
        if fundo != self._cores.fundo:
            p.fillRect(QRectF(x0, topo, largura, self._alt), fundo)
        texto = "".join(corrida)
        if texto.strip():
            p.setFont(self._negrito_italico if negrito and italico else self._negrito if negrito
                      else self._italico if italico else self._fonte)
            p.setPen(frente)
            simples = texto.isascii() and "" not in corrida and (not negrito or self._mesma_largura_em_negrito)
            if simples:
                p.drawText(QPointF(x0, topo + self._base), texto)
            else:                            # caractere a caractere: o largo, e o que vem de outra fonte
                for i, c in enumerate(corrida):
                    if c not in ("", " "):
                        p.drawText(QPointF(x0 + i * self._larg, topo + self._base), c)
        if sublinhado or riscado:
            p.setPen(QPen(frente, 1))
            for ligado, altura in ((sublinhado, self._sublinhado), (riscado, self._base * 0.62)):
                if ligado:
                    p.drawLine(QPointF(x0, topo + altura), QPointF(x0 + largura, topo + altura))

    def _pintar_cursor(self, p: QPainter) -> None:
        tela = self.tela
        if tela.cursor.hidden:
            return
        y = tela.cursor.y + self._rolagem
        if y >= tela.lines:
            return                           # rolado para cima: o cursor está abaixo da vista
        x = min(tela.cursor.x, tela.columns - 1)
        linha = tela.buffer.get(tela.cursor.y)
        c = linha[x] if linha is not None else None
        largo = c is not None and _largo(c.data)
        r = QRectF(MARGEM + x * self._larg, MARGEM + y * self._alt, self._larg * (2 if largo else 1), self._alt)
        if self.hasFocus():
            p.fillRect(r, self._cores.cursor)
            if c is not None and c.data.strip():
                p.setFont(self._negrito if c.bold else self._fonte)
                p.setPen(self._cores.cursor_texto)
                p.drawText(QPointF(r.x(), r.y() + self._base), c.data)
        else:
            p.setPen(QPen(self._cores.cursor, 1))
            p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))

    # --- o teclado ---------------------------------------------------------------------------------------------------

    def event(self, evento) -> bool:
        if evento.type() == QEvent.Type.ShortcutOverride and tecla_do_terminal(evento.key(), evento.modifiers()):
            evento.accept()
            return True
        return super().event(evento)

    def focusNextPrevChild(self, proximo: bool) -> bool:
        return False                         # o Tab é do shell (completar)

    def keyPressEvent(self, evento) -> None:
        tecla, mods = evento.key(), evento.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        m = Qt.KeyboardModifier
        ctrl_shift = m.ControlModifier | m.ShiftModifier
        if mods == ctrl_shift and tecla == K.Key_C or mods == m.ControlModifier and tecla == K.Key_Insert:
            self.copiar()
        elif mods == ctrl_shift and tecla == K.Key_V or mods == m.ShiftModifier and tecla == K.Key_Insert:
            self.colar_da_area_de_transferencia()
        elif mods == ctrl_shift and tecla == K.Key_F:
            self.buscaPedida.emit()
        elif mods == ctrl_shift and tecla == K.Key_A:
            self.selecionar_tudo()
        elif mods == m.ShiftModifier and tecla in (K.Key_PageUp, K.Key_PageDown):
            self.rolar((1 if tecla == K.Key_PageUp else -1) * max(1, self.tela.lines - 1))
        elif mods == m.ShiftModifier and tecla in (K.Key_Home, K.Key_End):
            self.rolar(len(self.tela.historico) if tecla == K.Key_Home else -self._rolagem)
        elif mods & m.ControlModifier and mods & m.ShiftModifier:
            super().keyPressEvent(evento)
        else:
            dados = sequencia_da_tecla(tecla, mods, evento.text(), CURSOR_DA_APLICACAO in self.tela.mode)
            if dados:
                self._enviar(dados)
            else:
                super().keyPressEvent(evento)

    def inputMethodEvent(self, evento) -> None:
        if evento.commitString():
            self._enviar(evento.commitString().encode())
        evento.accept()

    def inputMethodQuery(self, consulta):
        if consulta == Qt.InputMethodQuery.ImCursorRectangle:
            return self.retangulo_da_celula(min(self.tela.cursor.x, self.tela.columns - 1),
                                            self.tela.cursor.y + self._rolagem)
        return super().inputMethodQuery(consulta)

    def focusInEvent(self, evento) -> None:
        super().focusInEvent(evento)
        self.viewport().update()

    def focusOutEvent(self, evento) -> None:
        super().focusOutEvent(evento)
        self.viewport().update()

    # --- o mouse -----------------------------------------------------------------------------------------------------

    def mousePressEvent(self, evento) -> None:
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        botao = evento.button()
        if botao == Qt.MouseButton.LeftButton:
            ponto = evento.position().toPoint()
            triplo = time.monotonic() - self._ultimo_duplo < QApplication.doubleClickInterval() / 1000
            if evento.modifiers() & Qt.KeyboardModifier.ShiftModifier and self._ancora is not None:
                self._ponta = self._posicao(ponto, self._modo_de_selecao == "caractere")
            elif triplo:
                self._modo_de_selecao = "linha"
                self._ancora = self._ponta = self._posicao(ponto, False)
            else:
                self._modo_de_selecao = "caractere"
                self._ancora = self._ponta = self._posicao(ponto, True)
            self.viewport().update()
        elif botao == Qt.MouseButton.MiddleButton:
            area = QGuiApplication.clipboard()
            self.colar_da_area_de_transferencia(QClipboard.Mode.Selection if area.supportsSelection() else None)

    def mouseDoubleClickEvent(self, evento) -> None:
        if evento.button() != Qt.MouseButton.LeftButton:
            return
        self._ultimo_duplo = time.monotonic()
        self._modo_de_selecao = "palavra"
        self._ancora = self._ponta = self._posicao(evento.position().toPoint(), False)
        self.viewport().update()

    def mouseMoveEvent(self, evento) -> None:
        if not evento.buttons() & Qt.MouseButton.LeftButton or self._ancora is None:
            return
        ponto = evento.position().toPoint()
        if ponto.y() < 0:
            self.rolar(1)
        elif ponto.y() > self.viewport().height():
            self.rolar(-1)
        self._ponta = self._posicao(ponto, self._modo_de_selecao == "caractere")
        self.viewport().update()

    def mouseReleaseEvent(self, evento) -> None:
        if evento.button() == Qt.MouseButton.LeftButton and (texto := self.selecionado()):
            area = QGuiApplication.clipboard()
            if area.supportsSelection():     # a seleção do X11: o botão do meio cola
                area.setText(texto, QClipboard.Mode.Selection)

    def wheelEvent(self, evento) -> None:
        self._roda += evento.angleDelta().y() / 120 * 3
        linhas = int(self._roda)
        if not linhas:
            return
        self._roda -= linhas
        if self.tela.alternativa and not self._rolagem:    # o less, o vim: a roda vira as setas
            seta = K.Key_Up if linhas > 0 else K.Key_Down
            sequencia = sequencia_da_tecla(seta, Qt.KeyboardModifier.NoModifier, "",
                                           CURSOR_DA_APLICACAO in self.tela.mode)
            self.digitou.emit(sequencia * abs(linhas))
        else:
            self.rolar(linhas)
        evento.accept()

    def contextMenuEvent(self, evento) -> None:
        menu = QMenu(self)
        copiar = QAction(self.tr("Copiar"), menu, shortcut=QKeySequence("Ctrl+Shift+C"))
        copiar.setEnabled(bool(self.selecionado()))
        copiar.triggered.connect(self.copiar)
        colar = QAction(self.tr("Colar"), menu, shortcut=QKeySequence("Ctrl+Shift+V"))
        colar.setEnabled(bool(QGuiApplication.clipboard().text()))
        colar.triggered.connect(lambda: self.colar_da_area_de_transferencia())
        tudo = QAction(self.tr("Selecionar tudo"), menu, shortcut=QKeySequence("Ctrl+Shift+A"))
        tudo.triggered.connect(self.selecionar_tudo)
        buscar = QAction(self.tr("Buscar…"), menu, shortcut=QKeySequence("Ctrl+Shift+F"))
        buscar.triggered.connect(self.buscaPedida.emit)
        limpar = QAction(self.tr("Limpar a rolagem"), menu)
        limpar.setEnabled(bool(self.tela.historico))
        limpar.triggered.connect(self.limpar_a_rolagem)
        menu.addActions([copiar, colar, tudo])
        menu.addSeparator()
        menu.addActions([buscar, limpar])
        menu.exec(evento.globalPos())


def _largo(c: str) -> bool:
    from wcwidth import wcwidth  # o do pyte: a mesma conta de largura que ele fez ao pôr o caractere na tela

    return bool(c) and wcwidth(c[0]) == 2


def _indice(onde: list[int], coluna: int) -> int:
    """O índice no texto da linha do primeiro caractere na ``coluna`` ou depois dela."""
    for i, x in enumerate(onde):
        if x >= coluna:
            return i
    return len(onde)
