"""A janela do Estúdio (``sh_analyzer_gui.janela``, F1.1): as regiões, os painéis que recolhem, o layout salvo, o
desfazer, o tema e as preferências. Sem tela (pytest-qt), com a configuração numa pasta temporária."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QByteArray, Qt  # noqa: E402
from PySide6.QtGui import QKeySequence, QUndoCommand  # noqa: E402
from PySide6.QtWidgets import QDockWidget, QWidget  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.componentes.barra_superior import LARGURA_COMPACTA, BarraSuperior  # noqa: E402
from sh_analyzer_gui.componentes.painel import ALTURA_DO_TITULO  # noqa: E402
from sh_analyzer_gui.configuracao import gravar  # noqa: E402
from sh_analyzer_gui.janela import (  # noqa: E402
    AREA_ANALISE,
    AREA_AQUISICAO,
    AREA_FIGURAS,
    CHAVE_DA_GEOMETRIA,
    CHAVE_DO_ESTADO,
    JanelaPrincipal,
)
from sh_analyzer_gui.tema.aplicar import aparencia  # noqa: E402
from sh_analyzer_gui.tema.fontes import escolher_fonte, fonte_escolhida  # noqa: E402
from sh_analyzer_gui.tema.tokens import FONTE_INTERFACE, FONTE_MONO  # noqa: E402
from sh_placa.descoberta import Descoberta, FonteSimulador  # noqa: E402


@pytest.fixture
def app(qapp, config_limpa):
    criar_aplicacao([], tema="escuro")
    yield qapp
    aparencia(qapp).aplicar("escuro")
    escolher_fonte("interface", FONTE_INTERFACE)
    escolher_fonte("mono", FONTE_MONO)


def abrir_janela(qtbot) -> JanelaPrincipal:
    janela = JanelaPrincipal()
    qtbot.addWidget(janela)
    janela.show()
    qtbot.waitExposed(janela)
    return janela


@pytest.fixture
def janela(app, qtbot):
    """A janela aberta. Fechada aqui, e não pelo ``qtbot.addWidget``: o pytest-qt fecha as janelas dele antes da
    limpeza das fixtures, e uma janela com mudanças perguntaria se quer salvar."""
    j = JanelaPrincipal()
    j.show()
    qtbot.waitExposed(j)
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


class Somar(QUndoCommand):
    """Um comando de teste: soma ``n`` a uma lista de um elemento."""

    def __init__(self, alvo: list, n: int):
        super().__init__(f"Somar {n}")
        self.alvo, self.n = alvo, n

    def redo(self):
        self.alvo[0] += self.n

    def undo(self):
        self.alvo[0] -= self.n


def test_a_janela_tem_cada_regiao(janela):
    assert isinstance(janela.menuWidget(), BarraSuperior)
    lados = {"projeto": Qt.DockWidgetArea.LeftDockWidgetArea, "inspetor": Qt.DockWidgetArea.RightDockWidgetArea,
             "inferior": Qt.DockWidgetArea.BottomDockWidgetArea}
    for nome, lado in lados.items():
        dock = janela.findChild(QDockWidget, nome)
        assert dock is not None and dock.isVisible(), nome
        assert janela.estudio.dockWidgetArea(dock) == lado          # os painéis são da Análise (o Estúdio)
    # O Projeto e o Inspetor têm a altura inteira; o painel de baixo fica só embaixo das vistas.
    assert janela.dock_projeto.geometry().bottom() > janela.dock_inferior.geometry().top()
    assert janela.dock_inferior.geometry().left() >= janela.dock_projeto.geometry().right()
    assert janela.centro.currentWidget() is janela.vazio_central
    assert [janela.painel_inferior.tabText(i) for i in range(3)] == ["Medidas", "Tarefas", "Avisos"]
    assert janela.status_fonte.text() == "Nenhuma captura aberta"


def test_o_titulo_do_painel_nao_cobre_o_conteudo(janela):
    """O ``QDockWidget`` reserva a altura do título pelo ``sizeHint``: sem ele, o filtro subia por cima do título."""
    titulo = janela.dock_projeto.titleBarWidget()
    assert titulo.rotulo.text() == "PROJETO" and titulo.height() == ALTURA_DO_TITULO
    topo_do_filtro = janela.filtro_do_projeto.mapTo(janela, janela.filtro_do_projeto.rect().topLeft()).y()
    assert topo_do_filtro >= titulo.mapTo(janela, titulo.rect().bottomLeft()).y()


def test_as_areas_e_as_paginas(janela, qtbot):
    """A Análise e a Aquisição; as Figuras dizem quando chegam. Cada área é uma página da janela, com a sua parte na
    barra de status, e os painéis da Análise somem com ela e voltam como estavam."""
    areas = janela.barra.areas
    assert areas.escolhida == AREA_ANALISE and areas.botao(AREA_ANALISE).isEnabled()
    assert areas.botao(AREA_AQUISICAO).isEnabled()
    assert not areas.botao(AREA_FIGURAS).isEnabled() and areas.botao(AREA_FIGURAS).toolTip() == "Chega na v0.11"
    janela.conexao_da_placa.descoberta = Descoberta([FonteSimulador()])   # sem sondar a rede de verdade
    janela.acoes["painel_inspetor"].trigger()                     # um painel recolhido na Análise
    areas.botao(AREA_AQUISICAO).click()
    assert janela.area_atual == AREA_AQUISICAO and janela.aquisicao.isVisible()
    assert not janela.dock_projeto.isVisible() and janela.status_por_area.currentWidget() is janela.status_da_placa
    # Os atalhos da Análise (Delete, Ctrl+E, Ctrl+B…) não agem aqui: o Qt só dispara o atalho de uma ação com algum
    # widget dela visível, e os dessas moram no Estúdio. A paleta também não os oferece.
    for nome in ("espectro", "remover_selecionados", "fechar_vista", "painel_projeto", "painel_inferior"):
        widgets = [w for w in janela.acoes[nome].associatedObjects() if isinstance(w, QWidget)]
        assert widgets and not any(w.isVisible() for w in widgets), nome
    oferecidas = {a.objectName() for a in janela.acoes_da_paleta()}
    assert "espectro" not in oferecidas and {"abrir", "paleta", "configuracoes"} <= oferecidas
    areas.botao(AREA_FIGURAS).click()                             # desabilitada: nada muda
    assert janela.area_atual == AREA_AQUISICAO
    janela.mostrar_area(AREA_ANALISE)
    assert areas.escolhida == AREA_ANALISE and janela.dock_projeto.isVisible()
    assert not janela.dock_inspetor.isVisible() and janela.status_fonte.isVisible()
    assert any(w.isVisible() for w in janela.acoes["espectro"].associatedObjects() if isinstance(w, QWidget))
    janela.barra.chip_placa.click()                               # o chip da placa leva à Aquisição
    assert janela.area_atual == AREA_AQUISICAO
    qtbot.waitUntil(lambda: [p.estado for p in janela.conexao_da_placa.placas] == ["simulador"], timeout=10_000)


def test_os_paineis_recolhem_pelas_acoes_com_os_atalhos(janela):
    for nome, atalho, dock in (("painel_projeto", "Ctrl+B", janela.dock_projeto),
                               ("painel_inspetor", "Ctrl+I", janela.dock_inspetor),
                               ("painel_inferior", "Ctrl+J", janela.dock_inferior)):
        acao = janela.acoes[nome]
        assert acao.shortcut() == QKeySequence(atalho) and acao in janela.estudio.actions()
        acao.trigger()
        assert not dock.isVisible(), nome
        acao.trigger()
        assert dock.isVisible(), nome


def test_o_layout_e_salvo_ao_fechar_e_restaurado_ao_abrir(app, qtbot, config_limpa):
    primeira = abrir_janela(qtbot)
    primeira.acoes["painel_inspetor"].trigger()
    primeira.acoes["painel_inferior"].trigger()
    primeira.close()
    assert (config_limpa / "SH-Analyzer.ini").is_file()

    segunda = abrir_janela(qtbot)
    assert segunda._layout_restaurado
    assert segunda.dock_projeto.isVisible()
    assert not segunda.dock_inspetor.isVisible() and not segunda.dock_inferior.isVisible()


def test_um_layout_invalido_ou_de_outra_versao_cai_no_padrao(app, qtbot):
    gravar(CHAVE_DO_ESTADO, QByteArray(b"nao e um layout"))
    gravar(CHAVE_DA_GEOMETRIA, "nem binario")
    janela = abrir_janela(qtbot)
    assert not janela._layout_restaurado
    assert all(d.isVisible() for d in (janela.dock_projeto, janela.dock_inspetor, janela.dock_inferior))

    gravar(CHAVE_DO_ESTADO, janela.estudio.saveState(0))   # um layout de outra versão
    outra = JanelaPrincipal()
    qtbot.addWidget(outra)
    assert not outra.restaurar_layout()


def test_desfazer_e_refazer_seguem_a_pilha(janela):
    desfazer, refazer = janela.acoes["desfazer"], janela.acoes["refazer"]
    assert janela.barra.botao_desfazer.defaultAction() is desfazer
    assert janela.barra.botao_refazer.defaultAction() is refazer
    assert not desfazer.isEnabled() and not refazer.isEnabled()
    valor = [0]
    janela.pilha.push(Somar(valor, 5))
    assert valor == [5] and desfazer.isEnabled() and "Somar 5" in desfazer.toolTip()
    desfazer.trigger()
    assert valor == [0] and refazer.isEnabled() and not desfazer.isEnabled()
    refazer.trigger()
    assert valor == [5]


def test_o_botao_do_tema_troca_e_grava(janela):
    assert aparencia().tema.escuro and janela.acoes["alternar_tema"].toolTip() == "Tema claro"
    janela.barra.botao_tema.click()
    assert not aparencia().tema.escuro and janela.acoes["alternar_tema"].toolTip() == "Tema escuro"
    assert preferencias.tema_salvo() == "claro"


def test_o_botao_de_ajustes_abre_as_configuracoes(janela):
    assert janela.barra.botao_ajustes.defaultAction() is janela.acoes["configuracoes"]
    assert janela.acoes["configuracoes"].shortcut().toString() == "Ctrl+,"
    janela.barra.botao_ajustes.click()
    dialogo = janela.dialogo_de_configuracoes
    assert dialogo.isVisible() and dialogo.secao == "aparencia"
    assert janela.abrir_configuracoes("cache") is dialogo and dialogo.secao == "cache"   # uma só, na seção pedida


def test_as_preferencias_gravadas_valem_na_partida(app):
    gravar("aparencia/tema", "claro")
    gravar("aparencia/fonte_interface", "Atkinson Hyperlegible Next")
    gravar("aparencia/fonte_mono", "uma fonte que não existe")
    assert preferencias.tema_salvo() == "claro"
    preferencias.aplicar_fontes_salvas()
    assert fonte_escolhida("interface") == "Atkinson Hyperlegible Next"
    assert fonte_escolhida("mono") == FONTE_MONO                 # a que sumiu fica no padrão
    gravar("aparencia/tema", "roxo")
    assert preferencias.tema_salvo() == "sistema"


def test_a_barra_encolhe_numa_janela_estreita(janela, qtbot):
    barra = janela.barra
    janela.resize(LARGURA_COMPACTA + 200, 800)
    qtbot.waitUntil(lambda: not barra.compacta)
    assert barra.chip_placa.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    assert barra.rotulo_projeto.isVisible()
    janela.resize(960, 600)
    qtbot.waitUntil(lambda: barra.compacta)
    assert barra.chip_placa.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert not barra.rotulo_projeto.isVisible()
    # O seletor das áreas nunca encolhe (depois que o layout assenta: a medida de agora pode ser de antes do resize).
    qtbot.waitUntil(lambda: barra.areas.width() >= barra.areas.sizeHint().width())
    assert barra.minimumSizeHint().width() <= 960


def test_o_chip_da_placa(janela):
    chip = janela.barra.chip_placa
    assert chip.estado == "sem_placa" and chip.text() == "Sem placa"
    chip.definir("conectada", "BeagleBone · USB", "192.168.7.2")
    assert chip.property("estado") == "conectada" and "192.168.7.2" in chip.toolTip()
    with pytest.raises(ValueError):
        chip.definir("ligada", "x")


def test_os_contadores_das_abas(janela):
    painel = janela.painel_inferior
    barra_de_abas = painel.tabBar()
    largura = barra_de_abas.tabRect(1).width()
    painel.definir_contagem(1, 12, "acento")
    contador = barra_de_abas.tabButton(1, barra_de_abas.ButtonPosition.RightSide)
    assert contador.text() == "12" and contador.isVisible() and contador.property("nivel") == "acento"
    assert barra_de_abas.tabRect(1).width() > largura
    painel.definir_contagem(1, 0)
    assert barra_de_abas.tabButton(1, barra_de_abas.ButtonPosition.RightSide) is None
    assert barra_de_abas.tabRect(1).width() == largura                  # sem vão no zero
    with pytest.raises(ValueError):
        painel.definir_contagem(2, 1, "roxo")


def test_ctrl_k_abre_a_paleta(janela):
    janela.acoes["paleta"].trigger()
    assert janela.paleta.isVisible() and janela.paleta.lista.count() > 5


def test_apagar_a_janela_com_comandos_na_pilha_nao_da_erro(app, qtbot):
    """Ao apagar a janela, a pilha se limpa e muda o texto do desfazer quando a ação já pode ter sido apagada: a
    dica era atualizada por uma lambda que segurava a ação, e o erro estourava no teste seguinte (o pytest-qt pega
    as exceções do laço de eventos)."""
    from dialogos_falsos import DialogosFalsos

    janela = JanelaPrincipal()
    janela.controle.dialogos = DialogosFalsos("descartar")
    janela.show()
    janela.pilha.push(Somar([0], 1))
    janela.pilha.push(Somar([0], 2))
    janela.pilha.undo()
    apagada = []
    janela.destroyed.connect(lambda: apagada.append(True))
    janela.close()
    janela.deleteLater()
    qtbot.waitUntil(lambda: apagada == [True])
