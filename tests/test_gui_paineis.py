"""Os painéis da janela: a seta que recolhe cada um e a aba que o painel recolhido deixa na borda da área central
(``componentes/painel.py``), o clique numa vista do painel do projeto (abre a aba dela) e o contador da aba de
avisos, que conta só os avisos ainda não vistos. Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtWidgets import QToolButton  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.analise.arvore import PAPEL_OBJETO, PAPEL_TIPO  # noqa: E402
from sh_analyzer_gui.componentes.avisos import ListaDeAvisos  # noqa: E402
from sh_analyzer_gui.componentes.painel import AbaVertical  # noqa: E402
from sh_analyzer_gui.dados.captura import Aviso  # noqa: E402
from sh_analyzer_gui.janela import ABA_AVISOS, JanelaPrincipal  # noqa: E402

FS = 200_000.0


@pytest.fixture
def janela(qapp, config_limpa, qtbot):
    criar_aplicacao([], tema="escuro")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.resize(1400, 900)
    j.show()
    qtbot.waitExposed(j)
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def botao_da_acao(pai, nome_da_acao):
    return next(b for b in pai.findChildren(QToolButton)
                if b.defaultAction() is not None and b.defaultAction().objectName() == nome_da_acao)


# ------------------------------------------------------------------ recolher e abrir

@pytest.mark.parametrize("dock, lado, recolher", [("dock_projeto", "esquerda", "recolher_projeto"),
                                                   ("dock_inspetor", "direita", "recolher_inspetor"),
                                                   ("dock_inferior", "baixo", "recolher_inferior")])
def test_a_seta_recolhe_e_a_aba_do_trilho_abre(janela, qtbot, dock, lado, recolher):
    painel, trilho = getattr(janela, dock), janela.trilhos[lado]
    assert painel.isVisible() and not trilho.isVisible()
    qtbot.mouseClick(botao_da_acao(painel, recolher), Qt.MouseButton.LeftButton)
    assert not painel.isVisible() and trilho.isVisible()
    assert trilho.geometry().width() > 0 and trilho.geometry().height() > 0
    aba = trilho.abas[0]
    qtbot.mouseClick(aba, Qt.MouseButton.LeftButton, pos=aba.rect().center())
    assert painel.isVisible() and not trilho.isVisible()
    # O atalho do painel (Ctrl+B, Ctrl+I, Ctrl+J) passa pela mesma ação: o trilho segue.
    painel.toggleViewAction().trigger()
    assert not painel.isVisible() and trilho.isVisible()
    painel.toggleViewAction().trigger()
    assert painel.isVisible() and not trilho.isVisible()


def test_as_abas_dos_lados_cabem_no_texto(qapp):
    aba = AbaVertical("Inspetor", "esquerda")
    curta = aba.sizeHint()
    longa = AbaVertical("Um painel de nome comprido", "direita").sizeHint()
    assert longa.height() > curta.height() and longa.width() == curta.width()
    fonte = aba.font()
    fonte.setPixelSize(fonte.pixelSize() * 2)                     # outra fonte, maior: a aba cresce junto
    aba.setFont(fonte)
    assert aba.sizeHint().height() > curta.height() and aba.sizeHint().width() > curta.width()
    assert aba.minimumSizeHint() == aba.sizeHint() != QSize()


def test_o_trilho_de_baixo_abre_na_pagina_e_mostra_os_contadores(janela, qtbot):
    janela.dock_inferior.hide()
    trilho = janela.trilhos["baixo"]
    assert [a.text() for a in trilho.abas] == [janela.painel_inferior.tabText(i)
                                               for i in range(janela.painel_inferior.count())]
    janela.avisos.adicionar([Aviso("aviso", "a sonda não confere"), Aviso("info", "faixa suposta")], "x", "x.bin")
    contador = trilho.contadores[ABA_AVISOS]
    assert contador.isVisible() and contador.text() == "2" and contador.property("nivel") == "aviso"
    qtbot.mouseClick(trilho.abas[ABA_AVISOS], Qt.MouseButton.LeftButton)
    assert janela.dock_inferior.isVisible() and janela.painel_inferior.currentIndex() == ABA_AVISOS
    # Vistos: o contador some, na aba e no trilho.
    assert janela.painel_inferior.contagens[ABA_AVISOS][0] == 0 and not contador.isVisible()


# ------------------------------------------------------------------ o contador de avisos

def test_o_contador_conta_so_os_avisos_nao_vistos(qapp, qtbot):
    lista = ListaDeAvisos()
    contagens = []
    lista.contagemMudou.connect(lambda n, nivel: contagens.append((n, nivel)))
    lista.adicionar([Aviso("info", "um"), Aviso("aviso", "dois")], "a")
    assert contagens[-1] == (2, "aviso") and lista.nao_vistos == 2
    lista.show()                                                  # a aba abriu: vistos
    qtbot.waitExposed(lista)
    assert contagens[-1] == (0, "info") and lista.nao_vistos == 0
    lista.adicionar([Aviso("erro", "três")], "b")                 # chegou com a lista à vista: já visto
    assert contagens[-1] == (0, "info")
    lista.hide()
    lista.adicionar([Aviso("info", "quatro")], "c")               # só o novo conta, e o nível é o dele
    assert contagens[-1] == (1, "info") and len(lista.avisos) == 4
    lista.remover_origem("c")
    assert contagens[-1] == (0, "info")
    lista.adicionar([Aviso("aviso", "cinco")], "d")
    lista.remover_origem("a")                                     # tirar avisos vistos não muda os não vistos
    assert contagens[-1] == (1, "aviso")


def test_na_janela_abrir_a_aba_de_avisos_zera_o_contador(janela, qtbot):
    painel = janela.painel_inferior
    painel.setCurrentIndex(0)
    janela.avisos.adicionar([Aviso("aviso", "a sonda não confere")], "x", "x.bin")
    assert painel.contagens[ABA_AVISOS] == (1, "aviso") and painel.contador(ABA_AVISOS).isVisible()
    painel.tabBar().setCurrentIndex(ABA_AVISOS)                   # o clique na aba
    assert painel.contagens[ABA_AVISOS][0] == 0 and not painel.contador(ABA_AVISOS).isVisible()
    painel.setCurrentIndex(0)
    janela.avisos.adicionar([Aviso("info", "outro")], "y", "y.bin")
    assert painel.contagens[ABA_AVISOS] == (1, "acento")          # só o novo


# ------------------------------------------------------------------ as vistas no painel do projeto

def test_um_clique_numa_vista_do_projeto_abre_a_aba_dela(janela, qtbot, tmp_path):
    t = np.arange(40_000) / FS
    caminho = escrever_bin(tmp_path / "c.bin", [np.sin(2 * np.pi * 50 * t), 0.5 * np.sin(2 * np.pi * 50 * t)],
                           fs_total=int(2 * FS), versao=9)
    (fonte,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    janela.area.plotar_canal(fonte, 0)
    tempo = janela.vista_ativa()
    janela.acoes["espectro"].trigger()
    espectro = janela.vista_ativa()
    assert espectro is not tempo
    arvore, proxy = janela.painel_projeto.arvore, janela.painel_projeto.proxy

    def linha_da(vista):
        return proxy.mapFromSource(janela.painel_projeto.modelo.indice_da_vista(vista))

    indice = linha_da(tempo)
    assert indice.data(PAPEL_TIPO) == "vista" and indice.data(PAPEL_OBJETO) is tempo
    qtbot.mouseClick(arvore.viewport(), Qt.MouseButton.LeftButton, pos=arvore.visualRect(indice).center())
    assert janela.vista_ativa() is tempo
    indice = linha_da(espectro)
    qtbot.mouseClick(arvore.viewport(), Qt.MouseButton.LeftButton, pos=arvore.visualRect(indice).center())
    assert janela.vista_ativa() is espectro
    assert janela.inspetor.currentWidget() is janela.inspetor.da_vista        # as propriedades do espectro
    # Clicar na vista que já está aberta mostra as propriedades dela de novo (sem trocar de aba).
    janela.inspetor.mostrar("", None)
    qtbot.mouseClick(arvore.viewport(), Qt.MouseButton.LeftButton, pos=arvore.visualRect(indice).center())
    assert janela.vista_ativa() is espectro and janela.inspetor.currentWidget() is janela.inspetor.da_vista
