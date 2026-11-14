"""Nenhum texto espremido nem emendado (o retorno do usuário de 14/11): os menus da esquerda para a direita, com o
atalho afastado do rótulo; nenhum botão mais estreito que o texto dele; as áreas no centro da janela; e o inspetor
com a largura do conteúdo. Medido pelo próprio Qt (os size hints), e não por números fixos: vale para qualquer fonte e
língua. Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QAbstractButton, QMenu  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402


@pytest.fixture
def janela(qapp, config_limpa, qtbot, tmp_path):
    criar_aplicacao([], tema="escuro")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.resize(1400, 860)
    j.show()
    qtbot.waitExposed(j)
    t = np.arange(40_000) / 200_000
    caminho = escrever_bin(tmp_path / "c.bin", [np.sin(2 * np.pi * 50 * t), 0 * t], grandezas=(0, 1), versao=9)
    (fonte,) = j.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    traco = j.area.plotar_canal(fonte, 0)
    j.acoes["espectro"].trigger()
    j.selecao.definir([traco])
    secao = j.inspetor.do_traco.processamento
    secao.adicionar("passa_faixa")
    secao.adicionar("correcao_sonda")
    qtbot.wait(50)
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def test_o_menu_do_projeto_afasta_o_atalho_do_rotulo(janela):
    menu = janela.barra.botao_projeto.menu()
    assert menu.layoutDirection() == Qt.LayoutDirection.LeftToRight      # o botão é RTL (a seta), o menu não
    fm = menu.fontMetrics()
    com_atalho = [a for a in menu.actions() if not a.shortcut().isEmpty()]
    assert com_atalho
    for acao in com_atalho:
        rotulo = acao.text().replace("&", "")
        atalho = acao.shortcut().toString(acao.shortcut().SequenceFormat.NativeText)
        assert menu.sizeHint().width() >= fm.horizontalAdvance(rotulo) + fm.horizontalAdvance(atalho) + 24, rotulo
    for menu in janela.findChildren(QMenu):
        assert not menu.isRightToLeft(), [a.text() for a in menu.actions()]


def test_nenhum_botao_mais_estreito_que_o_texto(janela, qtbot):
    """Os botões visíveis da janela (as barras das vistas, o inspetor, os segmentados) têm pelo menos a largura que o
    texto deles pede: um layout que não cabe quebra em linhas ou alarga o painel, e não corta "Welch" em "W...h"."""
    espremidos = []
    for botao in janela.findChildren(QAbstractButton):
        if not botao.isVisibleTo(janela) or not botao.text().strip():
            continue
        if botao.width() < botao.minimumSizeHint().width() - 1:
            espremidos.append((botao.text(), botao.width(), botao.minimumSizeHint().width()))
    assert not espremidos


def test_as_areas_no_centro_da_janela(janela, qtbot):
    areas = janela.barra.areas
    centro = areas.mapTo(janela, areas.rect().center()).x()
    assert abs(centro - janela.width() / 2) <= 3
    janela.barra.definir_projeto("um projeto com um nome bem comprido de verdade", True)
    qtbot.wait(20)
    centro = areas.mapTo(janela, areas.rect().center()).x()
    assert abs(centro - janela.width() / 2) <= 3                       # o nome do projeto não o empurra


def test_o_inspetor_tem_a_largura_do_conteudo(janela):
    conteudo = janela.inspetor.do_traco.widget()
    assert janela.dock_inspetor.width() >= conteudo.minimumSizeHint().width()
