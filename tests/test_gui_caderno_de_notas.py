"""O caderno de notas (``dados/notas.py`` e ``componentes/caderno_de_notas.py``): as páginas em Markdown na pasta,
as referências aos gráficos (o endereço que vai e volta, o texto), e na janela: o Ctrl+Shift+N de qualquer área, a
gravação sozinha, as listas que continuam, as marcações e os atalhos delas (que ganham dos da janela), a referência
posta pelo gráfico e o clique nela, que leva a vista até ali, a imagem da vista e a página formatada."""

import math

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from sh_analyzer_gui.dados import notas  # noqa: E402
from sh_analyzer_gui.dados.notas import Referencia, ReferenciaInvalida  # noqa: E402
from sh_analyzer_gui.janela import AREA_ANALISE, AREA_FIGURAS  # noqa: E402
from sh_analyzer_gui.servicos.notas import central  # noqa: E402
from test_gui_anotacoes_na_tela import vista_aberta  # noqa: E402,F401
from test_gui_jornada_estilo import janela  # noqa: E402,F401

# ------------------------------------------------------------------ sem Qt: as páginas e as referências


def test_a_referencia_vai_e_volta_pelo_endereco_e_tem_um_texto_legivel():
    ponto = Referencia(vista="v1", nome="Tempo 1", x0=0.01, x1=0.02, tipo="ponto", px=0.0125, py=-1.5, faixa=2,
                       projeto="/tmp/meu projeto/p.shproj")
    assert Referencia.de_url(ponto.url()) == ponto and ponto.url().startswith("shanalyzer:ref?")
    assert ponto.texto() == "● Tempo 1 · t = 12,5 ms"
    trecho = Referencia(vista="v1", x0=0.02, x1=0.0125, dominio="t")           # em ordem
    assert (trecho.x0, trecho.x1) == (0.0125, 0.02)
    assert trecho.texto(".") == "↔ 12.5 ms → 20 ms, Δt = 7.5 ms"
    espectro = Referencia(vista="e", x0=2000.0, x1=9000.0, dominio="f")
    assert espectro.texto() == "↔ 2 kHz → 9 kHz, Δf = 7 kHz"
    md = trecho.markdown()
    ((inicio, fim, texto, achada),) = notas.referencias_em(f"antes {md} depois")
    assert achada == trecho and texto == trecho.texto() and fim - inicio == len(md)
    for errado in ("https://x", "shanalyzer:ref?vista=v&x0=a&x1=1", "shanalyzer:ref?x0=0&x1=1",
                   "shanalyzer:ref?vista=v&x0=0&x1=1&tipo=ponto"):
        with pytest.raises(ReferenciaInvalida):
            Referencia.de_url(errado)
    with pytest.raises(ReferenciaInvalida):
        Referencia(vista="v", x0=math.nan, x1=1.0)


def test_as_paginas_na_pasta_o_titulo_e_a_busca(tmp_path):
    pasta = tmp_path / "caderno"
    assert notas.paginas(pasta) == []
    a = notas.nova_pagina(pasta, "Ensaio de bancada")
    b = notas.nova_pagina(pasta, "Ensaio de bancada")
    assert a.name == "ensaio-de-bancada.md" and b.name == "ensaio-de-bancada-2.md"
    notas.gravar(b, "Sem título no começo\n\n## Depois\nCorrente de **fuga** em 9 kHz")
    assert notas.titulo_do_texto(a.read_text()) == "Ensaio de bancada"
    assert notas.titulo_do_texto("- [ ] Ligar o *gerador*\n") == "Ligar o gerador"
    assert notas.titulo_do_texto("# [link](x) e `código`") == "link e código"
    assert {p.titulo for p in notas.paginas(pasta)} == {"Ensaio de bancada", "Depois"}
    assert [p.caminho for p in notas.buscar(pasta, "FUGA")] == [b]
    assert {p.caminho for p in notas.buscar(pasta, "bancáda")} == {a}             # sem os acentos


# ------------------------------------------------------------------ na janela


def _editor(janela):  # noqa: F811
    return janela.caderno.editor


def _caderno_so_do_teste(janela, tmp_path):  # noqa: F811
    """O caderno numa pasta só deste teste (o $DADOS dos testes é um só para a sessão inteira)."""
    janela.caderno._pasta = tmp_path / "caderno"
    janela.caderno.pagina = None
    janela.caderno.listar()
    return janela.caderno


def _escrever(qtbot, editor, texto: str) -> None:
    for linha_k, linha in enumerate(texto.split("\n")):
        if linha_k:
            qtbot.keyClick(editor, Qt.Key.Key_Return)
        if linha:
            qtbot.keyClicks(editor, linha)


def test_o_atalho_de_qualquer_area_a_gravacao_as_listas_e_as_marcacoes(janela, qtbot, tmp_path):  # noqa: F811
    janela.resize(1300, 820)
    janela.show()
    qtbot.waitExposed(janela)
    caderno, acao = _caderno_so_do_teste(janela, tmp_path), janela.acoes["caderno"]
    assert not janela.dock_caderno.isVisible()
    assert acao.shortcut().toString() == "Ctrl+Shift+N"
    for area in (AREA_FIGURAS, AREA_ANALISE):            # o caderno é da janela: vale em qualquer área
        janela.mostrar_area(area)
        acao.trigger()
        assert janela.dock_caderno.isVisible()
        acao.trigger()
        assert not janela.dock_caderno.isVisible()
    acao.trigger()

    # A primeira página nasce no botão; o texto vai para o arquivo sozinho.
    caminho = caderno.nova_pagina("Ensaio")
    assert caminho.parent == caderno.pasta and caminho.read_text(encoding="utf-8") == "# Ensaio\n\n"
    editor = _editor(janela)
    editor.setFocus()
    _escrever(qtbot, editor, "- primeiro\nsegundo")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    qtbot.keyClick(editor, Qt.Key.Key_Return)          # o item vazio acaba a lista (a linha fica, limpa)
    _escrever(qtbot, editor, "1. um\ndois\n\n- [ ] tarefa\noutra")
    texto = editor.toPlainText()
    assert texto == "# Ensaio\n\n- primeiro\n- segundo\n1. um\n2. dois\n- [ ] tarefa\n- [ ] outra"
    qtbot.waitUntil(lambda: caminho.read_text(encoding="utf-8") == editor.toPlainText(), timeout=3000)

    # As marcações: Ctrl+B no editor é o negrito (não o painel do projeto da janela); os títulos.
    painel = janela.acoes["painel_projeto"].isChecked()
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    cursor.insertText("\nforte")
    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    qtbot.keyClick(editor, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    assert editor.toPlainText().endswith("**forte**") and janela.acoes["painel_projeto"].isChecked() == painel
    qtbot.keyClick(editor, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert editor.toPlainText().endswith("## **forte**")
    caderno.botoes["tarefa"].click()
    assert editor.toPlainText().endswith("- [ ] ## **forte**") or editor.toPlainText().endswith("- [ ] **forte**")
    assert caderno.gravar() and caminho.read_text(encoding="utf-8") == editor.toPlainText()

    # A página formatada: o Markdown de verdade (o título vira um título).
    caderno.ver.setChecked(True)
    assert caderno.pilha.currentWidget() is caderno.vista_formatada
    assert caderno.vista_formatada.toPlainText().splitlines()[0] == "Ensaio"          # sem o "# "
    caderno.ver.setChecked(False)
    # A lista das páginas e a busca.
    segunda = caderno.nova_pagina("Outra coisa")
    assert caderno.lista.count() == 2 and caderno.pagina == segunda
    caderno.busca.setText("Ensaio")
    assert caderno.lista.count() == 1
    caderno.busca.clear()
    caderno.lixeira = lambda c: c.unlink() is None                # não a lixeira do sistema
    assert caderno.para_a_lixeira(segunda, perguntar=False) and not segunda.exists() and caderno.lista.count() == 1


def test_a_referencia_do_grafico_vai_ao_caderno_e_o_clique_volta_a_vista(vista_aberta, qtbot,  # noqa: F811
                                                                         tmp_path):
    janela, vista, w, caixa, faixa = vista_aberta  # noqa: F811
    (x0, x1), (y0, y1) = caixa.viewRange()
    caderno = _caderno_so_do_teste(janela, tmp_path)
    # O menu do gráfico: o trecho entre os cursores vai para o caderno (que abre).
    w.ligar_cursores(True)
    c1, c2 = sorted(w.cursores)
    acoes = w.anotacoes.acoes(caixa, faixa, (x0 + x1) / 2, (y0 + y1) / 2, (c1, c2))
    next(a for a in acoes if a.text().startswith("Referenciar o trecho entre os cursores")).trigger()
    assert janela.dock_caderno.isVisible() and caderno.pagina is not None
    ((_i, _f, _texto, referencia),) = notas.referencias_em(caderno.editor.toPlainText())
    assert referencia.vista == vista.id and (referencia.x0, referencia.x1) == pytest.approx((c1, c2))
    assert referencia.nome == vista.nome and referencia.tipo == "intervalo"
    # O ponto clicado, com o zoom de agora.
    next(a for a in acoes if a.text() == "Referenciar este ponto no caderno").trigger()
    ponto = notas.referencias_em(caderno.editor.toPlainText())[-1][3]
    assert ponto.tipo == "ponto" and ponto.px == pytest.approx((x0 + x1) / 2) and (ponto.x0, ponto.x1) == \
        pytest.approx((x0, x1))

    # O clique na referência (Ctrl+clique no editor; aqui, pelo endereço) leva a vista até o trecho, com folga.
    w.mostrar_tempo(x0, x0 + 0.1 * (x1 - x0))
    caderno.abrir_endereco(referencia.url())
    largura = c2 - c1
    qtbot.waitUntil(lambda: w.janela_de_tempo()[0] == pytest.approx(c1 - 0.15 * largura, rel=1e-6), timeout=2000)
    assert w.janela_de_tempo()[1] == pytest.approx(c2 + 0.15 * largura)
    qtbot.waitUntil(lambda: bool(w.anotacoes._destaques), timeout=2000)       # o trecho destacado por um instante
    # A referência à vista e a imagem dela, pelos botões do caderno.
    caderno.ref_da_vista.click()
    ultima = notas.referencias_em(caderno.editor.toPlainText())[-1][3]
    assert ultima.vista == vista.id and (ultima.x0, ultima.x1) == pytest.approx(tuple(w.janela_de_tempo()))
    caderno.imagem.click()
    imagens = list((caderno.pasta / notas.PASTA_DAS_IMAGENS).glob("*.png"))
    assert len(imagens) == 1 and f"](imagens/{imagens[0].name})" in caderno.editor.toPlainText()
    # Uma referência a uma vista que não existe mais avisa e não muda nada.
    antes = w.janela_de_tempo()
    assert not janela.ir_para_referencia(Referencia(vista="sumiu", x0=0.0, x1=1.0))
    assert w.janela_de_tempo() == antes


def test_a_central_leva_a_referencia_mesmo_com_o_caderno_fechado(janela, qtbot, tmp_path):  # noqa: F811
    _caderno_so_do_teste(janela, tmp_path)
    referencia = Referencia(vista="v", x0=0.0, x1=1.0)
    assert not janela.dock_caderno.isVisible()
    central().referenciaPedida.emit(referencia)
    assert janela.dock_caderno.isVisible() or not janela.isVisible()
    assert referencia.markdown() in janela.caderno.editor.toPlainText()
