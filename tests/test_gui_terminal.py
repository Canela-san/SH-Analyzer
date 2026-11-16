"""O terminal da interface (``componentes/terminal.py``, F3.8), sem rede e sem tela: as sequências de escape mais
comuns pintadas na tela (as cores do tema, o vídeo reverso, o negrito, o cursor, o apagar), a rolagem, a tela
alternativa do ``less``, o redimensionamento que guarda o prompt, a busca, a seleção, as teclas do xterm, o colar com
o *bracketed paste*, a fila que não trava a interface e o tamanho que chega a quem liga o PTY."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("pyte")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.componentes import terminal as modulo  # noqa: E402
from sh_analyzer_gui.componentes.terminal import (  # noqa: E402
    TelaDeTerminal,
    sequencia_da_tecla,
    tecla_do_terminal,
)
from sh_analyzer_gui.tema.aplicar import aparencia  # noqa: E402
from sh_analyzer_gui.tema.tokens import TEMAS  # noqa: E402

K, M = Qt.Key, Qt.KeyboardModifier


@pytest.fixture
def app(qapp):
    criar_aplicacao([], tema="escuro")
    yield qapp
    aparencia(qapp).aplicar("escuro")


@pytest.fixture
def terminal(app, qtbot):
    """Um terminal de 40 × 10, já com o tamanho na tela."""
    t = TelaDeTerminal()
    qtbot.addWidget(t)
    t.resize(t.tamanho_para(40, 10))
    t.show()
    qtbot.waitExposed(t)
    assert (t.colunas, t.linhas) == (40, 10)
    enviados = []
    t.digitou.connect(enviados.append)
    t.enviados = enviados
    return t


def mostrar(t, texto: str) -> None:
    t.alimentar(texto.encode())
    t.interpretar_tudo()


def imagem(t):
    t.viewport().repaint()
    return t.viewport().grab().toImage()


def fundo(t, coluna, linha) -> str:
    """A cor do fundo da célula: o canto de cima, fora do desenho do caractere."""
    r = t.retangulo_da_celula(coluna, linha)
    return QColor(imagem(t).pixel(r.left() + 1, r.top() + 1)).name()


def tinta(t, coluna, linha) -> QColor:
    """A cor do caractere na célula: o pixel mais longe do fundo dela (o miolo da haste, sem a suavização)."""
    img, r = imagem(t), t.retangulo_da_celula(coluna, linha)
    base = QColor(img.pixel(r.left(), r.top()))
    pixels = [QColor(img.pixel(x, y)) for x in range(r.left(), r.right() + 1) for y in range(r.top(), r.bottom() + 1)]
    return max(pixels, key=lambda c: distancia(c, base))


def distancia(a: QColor, b) -> int:
    b = QColor(b)
    return max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue()))


def test_as_sequencias_mais_comuns_na_tela(terminal):
    tema = TEMAS["escuro"]
    mostrar(terminal, "\x1b[2J\x1b[H"                                  # limpa, cursor no canto
                      "\x1b[31mH\x1b[0m \x1b[1;32mN\x1b[0m"              # vermelho; verde em negrito
                      "\x1b[3;5H\x1b[44m  \x1b[0m"                       # fundo azul na linha 3, coluna 5
                      "\x1b[5;1H\x1b[7mREV\x1b[0m"                       # vídeo reverso
                      "\x1b[6;1H\x1b[38;5;196mH\x1b[38;2;10;200;30mH\x1b[0m"   # 256 cores e 24 bits
                      "\x1b[8;1Happagar\x1b[8;3H\x1b[K"                  # apaga até o fim da linha
                      "\x1b[10;1Hfim")
    linhas = terminal.linhas_visiveis()
    assert linhas[0] == "H N" and linhas[4] == "REV" and linhas[5] == "HH" and linhas[7] == "ap" and linhas[9] == "fim"
    assert distancia(tinta(terminal, 0, 0), tema.ansi[1]) < 40                     # a cor do tema, e não a do xterm
    assert distancia(tinta(terminal, 2, 0), tema.ansi[2]) < 40
    assert terminal.tela.buffer[0][2].bold
    assert fundo(terminal, 4, 2) == QColor(tema.ansi[4]).name()
    assert fundo(terminal, 3, 2) == QColor(tema.afundada).name()             # o fundo do terminal
    assert fundo(terminal, 0, 4) == QColor(tema.texto).name()                # reverso: o texto vira o fundo
    assert distancia(tinta(terminal, 0, 5), tema.ansi[9]) < 40                     # o 196 é o vermelho claro do tema
    assert distancia(tinta(terminal, 1, 5), "#0ac81e") < 40                        # 24 bits: a cor pedida
    assert (terminal.tela.cursor.x, terminal.tela.cursor.y) == (3, 9)


def test_o_cursor_segue_o_foco_e_o_modo(terminal, qtbot):
    tema = TEMAS["escuro"]
    mostrar(terminal, "ab")
    terminal.setFocus()
    qtbot.waitUntil(terminal.hasFocus)
    assert fundo(terminal, 2, 0) == QColor(tema.destaque).name()            # o bloco do cursor
    mostrar(terminal, "\x1b[?25l")                                                  # escondido (o vim, o htop)
    assert fundo(terminal, 2, 0) == QColor(tema.afundada).name()


def test_o_tema_claro(terminal):
    aparencia().aplicar("claro")
    mostrar(terminal, "\x1b[41m \x1b[0m")
    assert fundo(terminal, 0, 0) == QColor(TEMAS["claro"].ansi[1]).name()
    assert fundo(terminal, 5, 5) == QColor(TEMAS["claro"].afundada).name()


def test_a_rolagem_guarda_o_que_sobe(terminal):
    mostrar(terminal, "\r\n".join(f"linha {i}" for i in range(30)))
    assert terminal.linhas_visiveis()[-1] == "linha 29" and len(terminal.tela.historico) == 20
    terminal.rolar(5)
    assert terminal.linhas_visiveis()[0] == "linha 15"
    mostrar(terminal, "\r\nmais uma")                                               # rolado: a vista fica parada
    assert terminal.linhas_visiveis()[0] == "linha 15" and terminal.rolagem == 6
    terminal.escrever("x")                                                          # digitar volta para o fim
    assert terminal.rolagem == 0 and terminal.linhas_visiveis()[-1] == "mais uma"
    assert terminal.verticalScrollBar().maximum() == 21
    mostrar(terminal, "\x1b[H\x1b[2J\x1b[3J")                                       # o clear do Debian
    assert len(terminal.tela.historico) == 0 and terminal.linhas_visiveis() == [""] * 10


def test_a_tela_alternativa_devolve_a_principal(terminal):
    mostrar(terminal, "\r\n".join(f"antes {i}" for i in range(12)))
    guardadas = len(terminal.tela.historico)
    mostrar(terminal, "\x1b[?1049h\x1b[H\x1b[2Jo less mostra isto" + "\r\n" * 15)
    assert terminal.linhas_visiveis()[0] == "" and len(terminal.tela.historico) == guardadas   # nada vai à rolagem
    mostrar(terminal, "\x1b[?1049l")
    assert terminal.linhas_visiveis()[-1] == "antes 11"
    assert (terminal.tela.cursor.x, terminal.tela.cursor.y) == (8, 9)


def test_encolher_guarda_o_prompt_e_crescer_traz_de_volta(terminal, qtbot):
    mostrar(terminal, "\r\n".join(f"saida {i}" for i in range(9)) + "\r\n$ ")      # a tela cheia, o prompt embaixo
    terminal.resize(terminal.tamanho_para(40, 6))
    assert terminal.linhas == 6 and terminal.linhas_visiveis()[-1] == "$"
    assert (terminal.tela.cursor.x, terminal.tela.cursor.y) == (2, 5)
    assert terminal.tela.historico and terminal.linhas_visiveis()[0] == "saida 4"
    terminal.resize(terminal.tamanho_para(40, 10))
    assert terminal.linhas_visiveis()[0] == "saida 0" and terminal.tela.cursor.y == 9

    mostrar(terminal, "\x1b[H\x1b[2J\x1b[3J$ ")                                     # o prompt no alto
    terminal.resize(terminal.tamanho_para(30, 4))
    assert terminal.linhas_visiveis()[0] == "$" and not terminal.tela.historico     # saem as vazias de baixo
    with qtbot.waitSignal(terminal.tamanhoMudou) as sinal:
        pass
    assert sinal.args == [30, 4]


def test_a_busca_para_cima_e_para_baixo(terminal):
    mostrar(terminal, "\r\n".join(["erro: um", "ok", "ERRO: dois", *[f"x{i}" for i in range(20)], "$ "]))
    assert terminal.buscar("erro")
    assert terminal.selecionado() == "ERRO" and terminal.linhas_visiveis()[0] != "x14"   # à vista
    assert terminal.buscar("erro", de_novo=True)
    assert terminal.selecionado() == "erro"
    assert terminal.buscar("erro", de_novo=True)                                    # dá a volta
    assert terminal.selecionado() == "ERRO"
    assert terminal.buscar("erro", para_tras=False, de_novo=True)
    assert terminal.selecionado() == "erro"
    assert terminal.buscar("erro:")                                                 # o texto crescendo: a mesma
    assert terminal.selecionado() == "erro:"
    assert not terminal.buscar("não tem")


def test_selecionar_com_o_mouse_e_copiar(terminal, qtbot):
    mostrar(terminal, "debian@192.168.6.2 ls\r\nsegunda linha")
    r0, r1 = terminal.retangulo_da_celula(0, 0), terminal.retangulo_da_celula(5, 1)
    qtbot.mousePress(terminal.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(r0.left() + 1, r0.center().y()))
    qtbot.mouseMove(terminal.viewport(), QPoint(r1.right() + 1, r1.center().y()))
    qtbot.mouseRelease(terminal.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(r1.right() + 1, r1.center().y()))
    assert terminal.selecionado() == "debian@192.168.6.2 ls\nsegund"
    assert terminal.copiar() and QGuiApplication.clipboard().text() == "debian@192.168.6.2 ls\nsegund"
    r = terminal.retangulo_da_celula(9, 0)
    qtbot.mouseDClick(terminal.viewport(), Qt.MouseButton.LeftButton, pos=r.center())
    assert terminal.selecionado() == "debian@192.168.6.2"                           # a palavra inteira


def test_as_teclas_do_xterm():
    assert sequencia_da_tecla(K.Key_Return, M.NoModifier, "\r") == b"\r"
    assert sequencia_da_tecla(K.Key_Backspace, M.NoModifier, "\x08") == b"\x7f"
    assert sequencia_da_tecla(K.Key_Up, M.NoModifier, "") == b"\x1b[A"
    assert sequencia_da_tecla(K.Key_Up, M.NoModifier, "", cursor_da_aplicacao=True) == b"\x1bOA"
    assert sequencia_da_tecla(K.Key_Left, M.ControlModifier, "") == b"\x1b[1;5D"
    assert sequencia_da_tecla(K.Key_C, M.ControlModifier, "\x03") == b"\x03"
    assert sequencia_da_tecla(K.Key_B, M.AltModifier, "b") == b"\x1bb"
    assert sequencia_da_tecla(K.Key_Delete, M.NoModifier, "") == b"\x1b[3~"
    assert sequencia_da_tecla(K.Key_F1, M.NoModifier, "") == b"\x1bOP"
    assert sequencia_da_tecla(K.Key_F5, M.ShiftModifier, "") == b"\x1b[15;2~"
    assert sequencia_da_tecla(K.Key_Tab, M.NoModifier, "\t") == b"\t"
    assert sequencia_da_tecla(K.Key_Backtab, M.ShiftModifier, "") == b"\x1b[Z"
    assert sequencia_da_tecla(K.Key_Ccedilla, M.NoModifier, "ç") == "ç".encode()
    assert sequencia_da_tecla(K.Key_Q, M.ControlModifier | M.AltModifier, "/") == b"/"   # o AltGr do Windows
    assert tecla_do_terminal(K.Key_Z, M.ControlModifier)                            # o Ctrl+Z é do shell
    assert not tecla_do_terminal(K.Key_C, M.ControlModifier | M.ShiftModifier)      # o copiar é da tela
    assert not tecla_do_terminal(K.Key_PageDown, M.ControlModifier)                 # trocar de aba


def test_digitar_e_os_atalhos_da_tela(terminal, qtbot):
    terminal.setFocus()
    qtbot.keyClicks(terminal, "ls")
    qtbot.keyClick(terminal, K.Key_Return)
    qtbot.keyClick(terminal, K.Key_C, M.ControlModifier)
    assert b"".join(terminal.enviados) == b"ls\r\x03"
    mostrar(terminal, "\r\n".join(str(i) for i in range(30)))
    qtbot.keyClick(terminal, K.Key_PageUp, M.ShiftModifier)                         # rola, sem mandar nada
    assert terminal.rolagem == 9 and b"".join(terminal.enviados) == b"ls\r\x03"
    with qtbot.waitSignal(terminal.buscaPedida):
        qtbot.keyClick(terminal, K.Key_F, M.ControlModifier | M.ShiftModifier)


def test_escrever_nao_aperta_o_enter_e_colar_usa_as_marcas(terminal):
    terminal.escrever("./coletar.sh conferir")
    assert terminal.enviados == [b"./coletar.sh conferir"]
    terminal.colar("um\ndois\n")
    assert terminal.enviados[-1] == b"um\rdois\r"
    mostrar(terminal, "\x1b[?2004h")                                                # o bash liga as marcas
    terminal.colar("um\ndois")
    assert terminal.enviados[-1] == b"\x1b[200~um\rdois\x1b[201~"


def test_as_respostas_ao_programa_e_o_titulo(terminal, qtbot):
    with qtbot.waitSignal(terminal.tituloMudou) as titulo:
        mostrar(terminal, "\x1b]0;debian@beaglebone: ~\x07ab\x1b[6n")
    assert titulo.args == ["debian@beaglebone: ~"]
    assert terminal.enviados == [b"\x1b[1;3R"]                                      # a posição do cursor


def test_a_saida_grande_nao_trava_a_interface(terminal, qtbot, monkeypatch):
    monkeypatch.setattr(modulo, "MAXIMO_NA_FILA", 256 * 1024)
    terminal.alimentar(b"".join(b"linha %d de uma saida bem grande\r\n" % i for i in range(20_000)))
    assert terminal.puladas > 0                                                     # a fila cheia pulou o começo
    qtbot.waitUntil(lambda: not terminal._fila, timeout=20_000)
    visiveis = terminal.linhas_visiveis()
    assert visiveis[-2] == "linha 19999 de uma saida bem grande"
    assert any("pulados aqui" in terminal._texto(n)[0] for n in range(terminal._primeira(), terminal.tela.guardadas))
