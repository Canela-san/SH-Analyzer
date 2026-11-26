"""As anotações como caderno (a camada de anotações, ``graficos/camada_de_anotacoes.py``, e a barra), na janela e
pelo mouse de verdade: escolher e mover, puxar o alvo da seta, esticar um retângulo pelas alças, criar com as
ferramentas, desenhar à mão livre (com a pressão da mesa), apagar com a borracha, o estilo pela barra (um passo de
desfazer), o texto escrito no próprio gráfico, o Delete e a barra fechada que não deixa rabiscar. Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from sh_analyzer_gui.dados.anotacoes import Anotacao  # noqa: E402
from sh_analyzer_gui.graficos import camada_de_anotacoes as camada_mod  # noqa: E402
from sh_analyzer_gui.janela import AREA_ANALISE  # noqa: E402
from test_gui_jornada_estilo import janela  # noqa: E402,F401
from test_gui_jornada_figura import ESPERA_MS, _captura, _plotar  # noqa: E402


@pytest.fixture
def vista_aberta(janela, qtbot, tmp_path):  # noqa: F811
    janela.resize(1400, 860)
    assert janela.controle.abrir_capturas([_captura(tmp_path / "dados")])
    (fonte,) = janela.projeto.fontes
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=ESPERA_MS)
    _plotar(janela, fonte, 1)
    janela.mostrar_area(AREA_ANALISE)
    vista = janela.vista_ativa()
    w = janela.area.widget_da_vista(vista)
    qtbot.waitUntil(lambda: w.tem_dados, timeout=ESPERA_MS)
    qtbot.wait(50)
    faixa = vista.tracos[0].receita.faixa
    return janela, vista, w, w._caixa_da_faixa(faixa), faixa


def _no_viewport(w, caixa, x, y) -> QPoint:
    """O ponto (nos dados) em pixels do viewport do gráfico."""
    return w.grafico.mapFromScene(caixa.mapViewToScene(QPointF(x, y)))


def _mouse(w, tipo, ponto: QPoint, botoes=Qt.MouseButton.LeftButton, botao=Qt.MouseButton.LeftButton,
           modificadores=Qt.KeyboardModifier.NoModifier):
    viewport = w.grafico.viewport()
    evento = QMouseEvent(tipo, QPointF(ponto), QPointF(viewport.mapToGlobal(ponto)), botao, botoes, modificadores)
    QApplication.sendEvent(viewport, evento)


def _arrastar(qtbot, w, de: QPoint, para: QPoint, passos: int = 8, modificadores=Qt.KeyboardModifier.NoModifier):
    _mouse(w, QEvent.Type.MouseMove, de, botoes=Qt.MouseButton.NoButton, botao=Qt.MouseButton.NoButton)
    _mouse(w, QEvent.Type.MouseButtonPress, de, modificadores=modificadores)
    for k in range(1, passos + 1):
        QTest.qWait(12)                      # o PyQtGraph ignora mais de 100 movimentos por segundo
        f = k / passos
        _mouse(w, QEvent.Type.MouseMove, QPoint(round(de.x() + f * (para.x() - de.x())),
                                                round(de.y() + f * (para.y() - de.y()))),
               botao=Qt.MouseButton.NoButton, modificadores=modificadores)
    _mouse(w, QEvent.Type.MouseButtonRelease, para, botoes=Qt.MouseButton.NoButton, modificadores=modificadores)
    qtbot.wait(10)


def _clicar(qtbot, w, ponto: QPoint, modificadores=Qt.KeyboardModifier.NoModifier):
    _mouse(w, QEvent.Type.MouseMove, ponto, botoes=Qt.MouseButton.NoButton, botao=Qt.MouseButton.NoButton)
    _mouse(w, QEvent.Type.MouseButtonPress, ponto, modificadores=modificadores)
    _mouse(w, QEvent.Type.MouseButtonRelease, ponto, botoes=Qt.MouseButton.NoButton, modificadores=modificadores)
    qtbot.wait(10)


def test_mover_puxar_o_alvo_da_seta_e_esticar_pelas_alcas(vista_aberta, qtbot):
    janela, vista, w, caixa, faixa = vista_aberta
    (x0, x1), (y0, y1) = caixa.viewRange()
    X, Y = (lambda f: x0 + f * (x1 - x0)), (lambda f: y0 + f * (y1 - y0))
    an, pilha = w.anotacoes, janela.projeto.pilha
    an.por(Anotacao("s", "seta", X(0.3), Y(0.5), X(0.2), Y(0.8), "alvo", faixa=faixa))
    an.por(Anotacao("r", "retangulo", X(0.6), Y(0.3), X(0.7), Y(0.5), faixa=faixa, preenchimento="#3b82f6"))
    qtbot.wait(20)

    # O clique na seta a escolhe; o arrasto da ponta (o alvo) só muda o alvo, num passo de desfazer.
    _clicar(qtbot, w, _no_viewport(w, caixa, X(0.25), Y(0.65)))
    assert an.selecionadas == {"s"}
    passos = pilha.index()
    _arrastar(qtbot, w, _no_viewport(w, caixa, X(0.3), Y(0.5)), _no_viewport(w, caixa, X(0.4), Y(0.4)))
    seta = vista.anotacoes[0]
    assert (seta.x0, seta.y0) == pytest.approx((X(0.4), Y(0.4)), rel=0.02)
    assert (seta.x1, seta.y1) == pytest.approx((X(0.2), Y(0.8)))
    assert pilha.index() == passos + 1 and pilha.undoText() == "Mudar a forma da anotação"

    # O arrasto do meio do retângulo (cheio) o move inteiro; a alça do canto o estica (distorce) só por ali.
    _arrastar(qtbot, w, _no_viewport(w, caixa, X(0.65), Y(0.4)), _no_viewport(w, caixa, X(0.75), Y(0.4)))
    r = vista.anotacoes[1]
    assert an.selecionadas == {"r"} and (r.x0, r.x1) == pytest.approx((X(0.7), X(0.8)), rel=0.02)
    assert (r.y0, r.y1) == pytest.approx((Y(0.3), Y(0.5)), abs=0.01 * (y1 - y0))
    _arrastar(qtbot, w, _no_viewport(w, caixa, r.x1, r.y1), _no_viewport(w, caixa, X(0.9), Y(0.9)))
    r2 = vista.anotacoes[1]
    assert (r2.x0, r2.y0) == pytest.approx((r.x0, r.y0)) and (r2.x1, r2.y1) == pytest.approx((X(0.9), Y(0.9)), rel=0.03)

    # Fora das anotações, o arrasto continua andando no tempo (nada de anotação muda) e o clique tira a escolha.
    antes, passos = vista.anotacoes, pilha.index()
    _arrastar(qtbot, w, _no_viewport(w, caixa, X(0.1), Y(0.2)), _no_viewport(w, caixa, X(0.05), Y(0.2)))
    assert vista.anotacoes == antes and pilha.index() == passos and caixa.viewRange()[0][0] > x0
    _clicar(qtbot, w, _no_viewport(w, caixa, *(lambda v: (v[0][0] + 0.02 * (v[0][1] - v[0][0]),
                                                          v[1][0] + 0.05 * (v[1][1] - v[1][0])))(caixa.viewRange())))
    assert an.selecionadas == set()

    # A anotação travada não se move pelo mouse.
    an.escolher(("r",))
    an.travar(True)
    travado = vista.anotacoes[1]
    _arrastar(qtbot, w, _no_viewport(w, caixa, (travado.x0 + travado.x1) / 2, (travado.y0 + travado.y1) / 2),
              _no_viewport(w, caixa, travado.x0, travado.y0))
    assert vista.anotacoes[1] == travado


def test_as_ferramentas_criam_e_a_barra_fechada_nao_rabisca(vista_aberta, qtbot, monkeypatch):
    janela, vista, w, caixa, faixa = vista_aberta
    (x0, x1), (y0, y1) = caixa.viewRange()
    X, Y = (lambda f: x0 + f * (x1 - x0)), (lambda f: y0 + f * (y1 - y0))
    an = w.anotacoes
    assert not w.barra_de_anotacao.isVisible() and an.ferramenta == "selecionar"

    # Com a barra fechada, o arrasto anda no tempo: nada de desenho.
    _arrastar(qtbot, w, _no_viewport(w, caixa, X(0.5), Y(0.5)), _no_viewport(w, caixa, X(0.4), Y(0.6)))
    assert vista.anotacoes == ()
    (x0, x1), (y0, y1) = caixa.viewRange()

    # A barra aberta (A): o retângulo pelo arrasto, que fica escolhido, e a ferramenta volta a ser a de escolher.
    w.acao_anotar.trigger()
    assert w.barra_de_anotacao.isVisible()
    w.barra_de_anotacao.acoes_das_ferramentas["retangulo"].trigger()
    assert an.ferramenta == "retangulo"
    _arrastar(qtbot, w, _no_viewport(w, caixa, X(0.2), Y(0.2)), _no_viewport(w, caixa, X(0.3), Y(0.4)))
    (r,) = vista.anotacoes
    assert r.tipo == "retangulo" and (r.x0, r.x1, r.y0, r.y1) == pytest.approx((X(0.2), X(0.3), Y(0.2), Y(0.4)),
                                                                               rel=0.03)
    assert an.selecionadas == {r.id} and an.ferramenta == "selecionar"

    # A seta: do alvo (o começo do arrasto) para o texto.
    an.definir_ferramenta("seta")
    _arrastar(qtbot, w, _no_viewport(w, caixa, X(0.5), Y(0.5)), _no_viewport(w, caixa, X(0.6), Y(0.7)))
    seta = vista.anotacoes[-1]
    assert seta.tipo == "seta" and seta.x0 == pytest.approx(X(0.5), rel=0.02)
    assert seta.y0 == pytest.approx(Y(0.5), abs=0.01 * (y1 - y0))

    # O marcador e o nível no clique; o texto pede o que escrever ali mesmo (Enter grava).
    an.definir_ferramenta("marcador")
    _clicar(qtbot, w, _no_viewport(w, caixa, X(0.7), Y(0.3)))
    assert vista.anotacoes[-1].tipo == "marcador"
    an.definir_ferramenta("texto")
    _clicar(qtbot, w, _no_viewport(w, caixa, X(0.1), Y(0.8)))
    editor = an.editor
    assert editor is not None and editor.isVisible()
    editor.setPlainText("Pico")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    texto = vista.anotacoes[-1]
    assert texto.tipo == "texto" and texto.texto == "Pico" and an.selecionadas == {texto.id}

    # A caneta desenha à mão livre, com a pressão da mesa (quando ela fala); a ferramenta fica.
    monkeypatch.setattr(camada_mod.mesa(), "pressao", lambda: 0.6)
    an.definir_ferramenta("caneta")
    _arrastar(qtbot, w, _no_viewport(w, caixa, X(0.3), Y(0.3)), _no_viewport(w, caixa, X(0.5), Y(0.35)), passos=30)
    desenho = vista.anotacoes[-1]
    assert desenho.tipo == "desenho" and len(desenho.pontos) > 10 and len(desenho.pressoes) == len(desenho.pontos)
    assert an.ferramenta == "caneta"

    # A borracha apaga o desenho que toca (um passo de desfazer), e só ele.
    n = len(vista.anotacoes)
    an.definir_ferramenta("borracha")
    _arrastar(qtbot, w, _no_viewport(w, caixa, X(0.4), Y(0.1)), _no_viewport(w, caixa, X(0.4), Y(0.6)), passos=20)
    assert len(vista.anotacoes) == n - 1 and all(a.tipo != "desenho" for a in vista.anotacoes)
    janela.acoes["desfazer"].trigger()
    assert vista.anotacoes[-1] == desenho

    # Fechar a barra volta à ferramenta de escolher.
    w.acao_anotar.trigger()
    assert not w.barra_de_anotacao.isVisible() and an.ferramenta == "selecionar"


def test_o_estilo_pela_barra_o_texto_no_grafico_e_o_delete(vista_aberta, qtbot):
    janela, vista, w, caixa, faixa = vista_aberta
    (x0, x1), (y0, y1) = caixa.viewRange()
    X, Y = (lambda f: x0 + f * (x1 - x0)), (lambda f: y0 + f * (y1 - y0))
    an, pilha = w.anotacoes, janela.projeto.pilha
    an.por(Anotacao("t", "texto", X(0.2), Y(0.5), texto="antes", faixa=faixa))
    an.por(Anotacao("e", "elipse", X(0.5), Y(0.3), X(0.7), Y(0.6), faixa=faixa))
    w.mostrar_anotacao(True)
    barra = w.barra_de_anotacao

    # A cor da paleta nas duas escolhidas: um passo só; e fica para as próximas.
    an.escolher(("t", "e"))
    passos = pilha.index()
    vermelho = next(a for a in barra.cor.menu().actions() if a.text() == "Vermelho")
    vermelho.trigger()
    assert [a.cor for a in vista.anotacoes] == ["#ef4444", "#ef4444"] and pilha.index() == passos + 1
    assert an.estilo["cor"] == "#ef4444"
    an.escolher(("e",))
    next(a for a in barra.espessura.menu().actions() if a.text() == "4 px").trigger()
    next(a for a in barra.traco.menu().actions() if a.text() == "Tracejado").trigger()
    assert vista.anotacoes[1].espessura == 4.0 and vista.anotacoes[1].traco == "tracejado"
    assert vista.anotacoes[0].espessura == 0.0

    # O duplo clique no texto o escreve ali mesmo.
    _mouse(w, QEvent.Type.MouseMove, _no_viewport(w, caixa, X(0.2) , Y(0.5)) + QPoint(8, -6),
           botoes=Qt.MouseButton.NoButton, botao=Qt.MouseButton.NoButton)
    ponto = _no_viewport(w, caixa, X(0.2), Y(0.5)) + QPoint(8, -6)
    _clicar(qtbot, w, ponto)
    _mouse(w, QEvent.Type.MouseButtonDblClick, ponto)
    _mouse(w, QEvent.Type.MouseButtonRelease, ponto, botoes=Qt.MouseButton.NoButton)
    qtbot.waitUntil(lambda: an.editor is not None, timeout=2000)
    an.editor.setPlainText("depois")
    qtbot.keyClick(an.editor, Qt.Key.Key_Return)
    assert vista.anotacoes[0].texto == "depois" and pilha.undoText() == "Mudar o texto de uma anotação"

    # Duplicar (Ctrl+D) e o Delete da janela tiram as escolhidas antes dos traços.
    an.escolher(("e",))
    an.duplicar()
    assert len(vista.anotacoes) == 3 and an.selecionadas == {vista.anotacoes[2].id}
    tracos = vista.tracos
    janela.acoes["remover_selecionados"].trigger()
    assert len(vista.anotacoes) == 2 and vista.tracos == tracos


def test_o_desenho_vai_e_volta_pelo_projeto_e_a_camada_desenha_todos(vista_aberta, qtbot, tmp_path):
    janela, vista, w, caixa, faixa = vista_aberta
    (x0, x1), (y0, y1) = caixa.viewRange()
    X, Y = (lambda f: x0 + f * (x1 - x0)), (lambda f: y0 + f * (y1 - y0))
    an = w.anotacoes
    pontos = tuple((X(0.1 + 0.3 * t), Y(0.5 + 0.2 * np.sin(8 * t))) for t in np.linspace(0, 1, 40))
    todas = [Anotacao("1", "texto", X(0.1), Y(0.9), texto="a", faixa=faixa, caixa=True, fonte=18),
             Anotacao("2", "seta", X(0.2), Y(0.5), X(0.1), Y(0.7), faixa=faixa, ponta="aberta"),
             Anotacao("3", "linha", X(0.3), Y(0.5), X(0.4), Y(0.7), faixa=faixa, traco="pontilhado"),
             Anotacao("4", "regiao", X(0.4), 0.0, X(0.45), faixa=faixa, preenchimento="#22c55e"),
             Anotacao("5", "cota", X(0.5), Y(0.2), X(0.6), faixa=faixa),
             Anotacao("6", "retangulo", X(0.6), Y(0.6), X(0.7), Y(0.8), faixa=faixa),
             Anotacao("7", "elipse", X(0.7), Y(0.6), X(0.8), Y(0.8), faixa=faixa, opacidade=0.5),
             Anotacao("8", "nivel", X(0.8), Y(0.3), faixa=faixa),
             Anotacao("9", "marcador", X(0.85), Y(0.5), faixa=faixa, forma="losango"),
             Anotacao("10", "desenho", 0, 0, faixa=faixa, pontos=pontos, pressoes=(0.5,) * len(pontos))]
    for a in todas:
        an.por(a)
    camada = an.camada_da_caixa(caixa)
    antes = camada.pinturas
    w.grafico.grab()
    assert camada.pinturas > antes and set(an.itens) == {a.id for a in todas}
    caminho = tmp_path / "p.shproj"
    assert janela.controle.salvar_como(caminho)
    assert janela.controle.abrir(caminho)
    assert janela.projeto.vistas[0].anotacoes == tuple(todas)
