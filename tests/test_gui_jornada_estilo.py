"""A jornada do estilo da figura (F5.7: o "pronto quando", docs/gui-progress.md), na janela: cada propriedade (o
estilo da figura, os eixos e os traços do painel) muda a prévia e entra na exportação, cada uma é um passo de
desfazer e, desfeitas todas, a página volta a ser a de antes; um modelo de estilo salvo aplica-se a outra figura; a
visão em cinza e com daltonismo muda só a prévia. Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.dados.exportar_figura import OpcoesDeExportacao  # noqa: E402
from sh_analyzer_gui.dados.figura import EstiloDoTraco  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from test_gui_jornada_figura import ESPERA_MS, _captura, _esperar_a_pagina, _pagina, _plotar  # noqa: E402


@pytest.fixture
def janela(qapp, config_limpa):
    criar_aplicacao([], tema="claro")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.resize(1400, 900)
    j.show()
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def _escolher(caixa, dado) -> None:
    i = caixa.findData(dado)
    assert i >= 0, dado
    caixa.setCurrentIndex(i)
    caixa.activated.emit(i)


def _escolher_texto(caixa, texto: str) -> None:
    i = caixa.findText(texto)
    assert i >= 0, texto
    caixa.setCurrentIndex(i)
    caixa.activated.emit(i)


def _escrever(campo, texto: str) -> None:
    campo.setText(texto)
    campo.editingFinished.emit()


def _figura_com_dois_tracos(janela, qtbot, tmp_path):
    assert janela.controle.abrir_capturas([_captura(tmp_path / "dados")])
    (fonte,) = janela.projeto.fontes
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=ESPERA_MS)
    _plotar(janela, fonte, 1)
    _plotar(janela, fonte, 3)
    area = janela.figuras
    _esperar_a_pagina(qtbot, area, lambda: qtbot.mouseClick(janela.botao_figura_da_vista, Qt.MouseButton.LeftButton))
    return area


def test_cada_propriedade_muda_a_previa_e_a_exportacao_com_desfazer(janela, qtbot, tmp_path):
    area = _figura_com_dois_tracos(janela, qtbot, tmp_path)
    props = area.propriedades
    estilo, eixos, tracos = props.estilo, props.secao_dos_eixos, props.secao_dos_tracos
    assert eixos.isVisibleTo(props) and tracos.isVisibleTo(props)
    assert [t.nome for t in tracos.tracos] == [t.receita.nome for t in janela.vista_ativa().tracos]
    # O que o desenho achou aparece apagado nos campos vazios.
    assert eixos.nome["x"].placeholderText() == "Tempo" and eixos.maximo["x"].placeholderText().endswith("ms")
    assert eixos.nome["y"].isEnabled() and eixos.nome["y"].placeholderText() == "Tensão"   # os dois na faixa
    inicio = _pagina(area)
    pilha = janela.projeto.pilha
    passos = pilha.index()
    id_do_traco = tracos.traco_atual.id

    gestos = [
        lambda: estilo.tamanhos["legenda_pt"].setValue(6.0),
        lambda: estilo.grade.setChecked(True),
        lambda: estilo.marcas.botao(1).click(),
        lambda: estilo.moldura.setChecked(False),
        lambda: _escolher_texto(estilo.familia, "Inter"),
        lambda: _escolher(eixos.legenda, "fora_acima"),
        lambda: _escrever(eixos.nome["x"], "Instante"),
        lambda: _escolher(eixos.prefixo["x"], -6),
        lambda: _escrever(eixos.maximo["x"], "20 ms"),
        lambda: _escrever(eixos.nome["y"], "$v(t)$"),
        lambda: _escolher(eixos.prefixo["y"], -3),
        lambda: _escolher(tracos.cor, "#000000"),
        lambda: _escrever(tracos.hexa, "#112233"),
        lambda: tracos.espessura.setValue(1.5),
        lambda: _escolher(tracos.tracejado, ":"),
        lambda: _escolher(tracos.marcador, "o"),
        lambda: _escrever(tracos.nome, "$V_{AB}$"),
    ]
    anterior = inicio
    for gesto in gestos:
        pagina = _esperar_a_pagina(qtbot, area, gesto)
        assert not np.array_equal(pagina, anterior)                  # cada propriedade muda a prévia
        anterior = pagina
    assert pilha.index() == passos + len(gestos)                     # um passo de desfazer cada

    figura = janela.projeto.figuras[0]
    (painel,) = figura.paineis
    e = figura.estilo
    assert (e.legenda_pt, e.grade, e.marcas_para_dentro, e.moldura, e.familia) == (6.0, True, False, False, "Inter")
    assert (painel.legenda, painel.nome_x, painel.prefixo_x) == ("fora_acima", "Instante", -6)
    assert (painel.nome_y, painel.prefixo_y) == ("$v(t)$", -3)
    assert painel.limites_x[1] == pytest.approx(0.02)
    assert painel.estilo_do_traco(id_do_traco) == EstiloDoTraco("#112233", 1.5, ":", "o", "$V_{AB}$")

    # A exportação sai com o mesmo estilo (o SVG com o texto como texto).
    svg = tmp_path / "estilo.svg"
    with qtbot.waitSignal(area.exportada, timeout=ESPERA_MS):
        area.exportar(OpcoesDeExportacao("svg"), svg)
    conteudo = svg.read_text(encoding="utf-8")
    assert "#112233" in conteudo and "Instante (µs)" in conteudo and "font-size: 6px" in conteudo
    assert "Inter" in conteudo and "stroke-dasharray" in conteudo

    # Desfeito tudo, a página volta a ser a de antes.
    for _ in gestos:
        _esperar_a_pagina(qtbot, area, janela.acoes["desfazer"].trigger)
    assert np.array_equal(_pagina(area), inicio)
    assert janela.projeto.figuras[0].paineis[0].tracos == () and props.secao_dos_tracos.voltar.isEnabled() is False


def test_um_modelo_de_estilo_salvo_vale_em_outra_figura(janela, qtbot, tmp_path):
    area = _figura_com_dois_tracos(janela, qtbot, tmp_path)
    estilo = area.propriedades.estilo
    _esperar_a_pagina(qtbot, area, lambda: estilo.grade.setChecked(True))
    _esperar_a_pagina(qtbot, area, lambda: estilo.tamanhos["marcas_pt"].setValue(5.5))
    salvo = janela.projeto.figuras[0].estilo
    estilo.pedir_nome = lambda _titulo, _rotulo, _texto: "Revista X"
    qtbot.mouseClick(estilo.salvar, Qt.MouseButton.LeftButton)
    assert [m.nome for m in preferencias.modelos_de_estilo()] == ["Revista X"]
    assert estilo.modelo.findData("Revista X") > 0 and "✓" in estilo.modelo.itemText(estilo.modelo.findData(
        "Revista X"))

    # Outra figura (nasce com o estilo da página): o modelo a muda, num passo de desfazer.
    _esperar_a_pagina(qtbot, area, lambda: area.nova_figura("ieee_2"))
    outra = area.figura
    assert outra.estilo != salvo
    _esperar_a_pagina(qtbot, area, lambda: _escolher(estilo.modelo, "Revista X"))
    assert area.figura.estilo == salvo and estilo.modelo.currentIndex() == 0
    _esperar_a_pagina(qtbot, area, janela.acoes["desfazer"].trigger)
    assert area.figura.estilo == outra.estilo
    # O da página volta a figura ao estilo com que ela nasceu; apagar o modelo o tira das preferências.
    _esperar_a_pagina(qtbot, area, lambda: _escolher(estilo.modelo, "Revista X"))
    _esperar_a_pagina(qtbot, area, lambda: _escolher(estilo.modelo, ""))
    assert area.figura.estilo == outra.pagina.estilo
    estilo.apagar.menu().actions()[0].trigger()
    assert preferencias.modelos_de_estilo() == [] and estilo.modelo.findData("Revista X") < 0


def test_a_visao_muda_so_a_previa(janela, qtbot, tmp_path):
    area = _figura_com_dois_tracos(janela, qtbot, tmp_path)
    cores = _pagina(area)
    figura, passos = janela.projeto.figuras[0], janela.projeto.pilha.index()
    visao = area.pagina.visao
    visao.setCurrentIndex(visao.findData("cinza"))
    cinza = _pagina(area)
    assert np.array_equal(cinza[..., 0], cinza[..., 1]) and not np.array_equal(cinza, cores)
    visao.setCurrentIndex(visao.findData("deuteranopia"))
    assert not np.array_equal(_pagina(area), cinza)
    assert janela.projeto.figuras[0] == figura and janela.projeto.pilha.index() == passos
    visao.setCurrentIndex(visao.findData("normal"))
    assert np.array_equal(_pagina(area), cores)
