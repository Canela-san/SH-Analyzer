"""A jornada da figura (F5.3: o "pronto quando" da área Figuras, docs/gui-progress.md), na janela e pelos gestos:
abrir uma captura e plotar a tensão, transformar a vista numa figura IEEE de uma coluna com um clique, pôr um
segundo painel na grade, ligá-lo à mesma vista e congelá-lo; mudar a vista e ver o painel ligado acompanhar e o
congelado ficar; desfazer; salvar o projeto, abrir de novo e ver a mesma página. Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.janela import AREA_ANALISE, AREA_FIGURAS, JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.modelo.comandos import MudarTracos  # noqa: E402

ESPERA_MS = 30_000
TAXA = 400_000


@pytest.fixture
def janela(qapp, config_limpa):
    criar_aplicacao([], tema="escuro")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.resize(1400, 900)
    j.show()
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def _captura(pasta):
    t = np.arange(20_000) / (TAXA / 2)
    v = 3.0 * np.sin(2 * np.pi * 60 * t) + 0.3 * np.sin(2 * np.pi * 3000 * t)
    i = 1.0 * np.sin(2 * np.pi * 60 * t - 0.5)
    pasta.mkdir(parents=True, exist_ok=True)
    return escrever_bin(pasta / "rede.bin", [v, i], canais=(1, 3), versao=9)


def _plotar(janela, fonte, numero: int) -> None:
    """O duplo clique no canal, na árvore do projeto."""
    painel = janela.painel_projeto
    indice = painel.proxy.mapFromSource(painel.modelo.indice_do_canal(fonte, numero))
    painel.arvore.scrollTo(indice)
    ponto = painel.arvore.visualRect(indice).center()
    QTest.mouseClick(painel.arvore.viewport(), Qt.MouseButton.LeftButton, pos=ponto)
    QTest.mouseDClick(painel.arvore.viewport(), Qt.MouseButton.LeftButton, pos=ponto)


def _pagina(area) -> np.ndarray:
    """A página que está na tela, em RGBA."""
    imagem = area.pagina.folha.imagem.convertToFormat(QImage.Format.Format_RGBA8888)
    largura, altura = imagem.width(), imagem.height()
    bits = np.frombuffer(imagem.constBits(), np.uint8).reshape(altura, imagem.bytesPerLine())
    return bits[:, :4 * largura].reshape(altura, largura, 4).copy()


def _recorte(area, pixels: np.ndarray, id_do_painel: str) -> np.ndarray:
    x0, y0, x1, y1 = (round(v) for v in area.pagina.folha.caixas[id_do_painel])
    return pixels[y0:y1, x0:x1]


def _esperar_a_pagina(qtbot, area, gesto) -> np.ndarray:
    with qtbot.waitSignal(area.desenhada, timeout=ESPERA_MS):
        gesto()
    return _pagina(area)


def test_da_vista_a_figura_e_de_volta_pelo_projeto(janela, qtbot, tmp_path):
    # 1. A captura aberta e a tensão plotada: a vista nasce com ela.
    assert janela.controle.abrir_capturas([_captura(tmp_path / "dados")])
    (fonte,) = janela.projeto.fontes
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=ESPERA_MS)
    _plotar(janela, fonte, 1)
    vista = janela.vista_ativa()
    (traco,) = vista.tracos
    area = janela.figuras

    # 2. Um clique: a vista vira uma figura IEEE de uma coluna, e a janela vai para as Figuras.
    pagina = _esperar_a_pagina(qtbot, area, lambda: qtbot.mouseClick(janela.botao_figura_da_vista,
                                                                      Qt.MouseButton.LeftButton))
    assert janela.area_atual == AREA_FIGURAS
    (figura,) = janela.projeto.figuras
    (primeiro,) = figura.paineis
    assert (figura.modelo, figura.nome, primeiro.vista) == ("ieee_1", vista.nome, vista.id)
    assert area.figura is figura and area.lista.count() == 1 and pagina[..., :3].min() < 128     # há tinta
    assert "88 × 66 mm" in janela.status_da_figura.text()

    # 3. O segundo painel: entra numa linha nova (a página cresce), ligado à mesma vista, e é congelado.
    props = area.propriedades
    _esperar_a_pagina(qtbot, area, lambda: qtbot.mouseClick(props.acrescentar, Qt.MouseButton.LeftButton))
    figura = janela.projeto.figuras[0]
    segundo = next(p for p in figura.paineis if p.id != primeiro.id)
    assert (figura.linhas, figura.altura_mm, area.painel_id, segundo.vista) == (2, 132.0, segundo.id, None)
    i = props.vista.findData(vista.id)
    props.vista.setCurrentIndex(i)
    props.vista.activated.emit(i)
    assert janela.projeto.figuras[0].paineis[1].vista == vista.id
    antes = _esperar_a_pagina(qtbot, area, lambda: props.estado.botao(1).click())
    congelado = janela.projeto.figuras[0].paineis[1]
    assert congelado.congelado is not None and congelado.limites_x is not None
    assert set(area.pagina.folha.caixas) == {primeiro.id, segundo.id}

    # 4. A vista muda (o ganho do traço): o painel ligado acompanha, o congelado fica.
    janela.mostrar_area(AREA_ANALISE)
    janela.projeto.pilha.push(MudarTracos([traco], ganho=-2.0))
    depois = _esperar_a_pagina(qtbot, area, lambda: janela.mostrar_area(AREA_FIGURAS))
    assert not np.array_equal(_recorte(area, antes, primeiro.id), _recorte(area, depois, primeiro.id))
    assert np.array_equal(_recorte(area, antes, segundo.id), _recorte(area, depois, segundo.id))

    # 5. O desfazer volta a vista, e a figura volta junto; o refazer a muda de novo.
    voltou = _esperar_a_pagina(qtbot, area, janela.acoes["desfazer"].trigger)
    assert np.array_equal(voltou, antes)
    depois = _esperar_a_pagina(qtbot, area, janela.acoes["refazer"].trigger)

    # 6. Salvo e aberto de novo: a mesma página.
    janela.controle.dialogos = DialogosFalsos(tmp_path / "projetos" / "figura")
    assert janela.controle.salvar()
    caminho = janela.projeto.caminho
    assert janela.controle.novo() and janela.projeto.figuras == () and area.lista.count() == 0
    janela.mostrar_area(AREA_ANALISE)
    assert janela.controle.abrir(caminho)
    (fonte,) = janela.projeto.fontes
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=ESPERA_MS)
    reaberta = _esperar_a_pagina(qtbot, area, lambda: janela.mostrar_area(AREA_FIGURAS))
    assert janela.projeto.figuras[0] == figura.com(paineis=janela.projeto.figuras[0].paineis)
    assert np.array_equal(reaberta, depois)


def test_o_espectro_vira_figura_com_o_que_a_vista_calculou(janela, qtbot, tmp_path):
    """A vista de espectro também vira figura com um clique: o painel desenha o espectro que a vista calculou (o
    mesmo desenho, sem refazer a FFT), na escala de frequência e na faixa que ela mostra."""
    assert janela.controle.abrir_capturas([_captura(tmp_path / "dados")])
    (fonte,) = janela.projeto.fontes
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=ESPERA_MS)
    _plotar(janela, fonte, 1)
    janela.acoes["espectro"].trigger()
    espectro = janela.vista_ativa()
    widget = janela.area.widget_da_vista(espectro)
    qtbot.waitUntil(lambda: any(r.desenho is not None for r in widget.resultados), timeout=ESPERA_MS)
    area = janela.figuras
    _esperar_a_pagina(qtbot, area, lambda: qtbot.mouseClick(janela.botao_figura_da_vista,
                                                             Qt.MouseButton.LeftButton))
    (figura,) = janela.projeto.figuras
    assert figura.paineis[0].vista == espectro.id
    from sh_analyzer_gui.modelo.persistencia import descrever_vista

    salva = descrever_vista(espectro)
    (serie,) = area.dados.espectros(salva)
    (resultado,) = widget.resultados
    assert serie.desenho is resultado.desenho and serie.frequencia_log == espectro.opcoes.frequencia_log
    assert serie.rotulo_y == resultado.espectro.rotulo(resultado.unidade)
    assert area.dados.janela(salva) == janela.area.janela_da_vista(espectro)
