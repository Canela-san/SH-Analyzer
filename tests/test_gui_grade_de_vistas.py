"""A grade das vistas (AN-09, F5.9): as abas com as células (componentes/grade_de_vistas.py), a célula ativa que segue
a aba e o clique, a troca de vista numa célula, e na janela os eixos ligados entre as vistas de tempo e entre as de
espectro, a grade guardada no projeto. Sem tela."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402
from sh_analyzer_gui.componentes.grade_de_vistas import AbasEmGrade  # noqa: E402
from test_gui_vista_tempo import abrir, captura, janela  # noqa: E402,F401


def _grade(qtbot, n=3):
    grade = AbasEmGrade()
    qtbot.addWidget(grade)
    vistas = [QLabel(f"vista {k}") for k in range(n)]
    for k, v in enumerate(vistas):
        grade.addTab(v, QIcon(), f"V{k}")
    grade.resize(800, 600)
    grade.show()
    qtbot.waitExposed(grade)
    return grade, vistas


def _nas_celulas(grade):
    return [c.widget for c in grade.celulas]


def test_uma_celula_e_como_as_abas(qtbot):
    grade, (a, b, c) = _grade(qtbot)
    mudou = []
    grade.currentChanged.connect(mudou.append)
    assert grade.count() == 3 and grade.currentWidget() is a and _nas_celulas(grade) == [a]
    assert a.isVisible() and not b.isVisible()
    grade.setCurrentIndex(2)
    assert mudou == [2] and _nas_celulas(grade) == [c] and c.isVisible() and not a.isVisible()
    grade.setTabText(2, "Outra")
    assert grade.tabText(2) == "Outra" and grade.indexOf(c) == 2
    grade.removeTab(2)
    assert grade.count() == 2 and grade.currentWidget() in (a, b) and _nas_celulas(grade) == [grade.currentWidget()]
    assert not grade.celulas[0].nome.isVisible()           # sozinha, o nome da vista é o da aba


def test_a_grade_preenche_as_celulas_e_segue_a_aba(qtbot):
    grade, (a, b, c) = _grade(qtbot)
    grade.setCurrentIndex(1)
    grade.definir_disposicao("lado_a_lado")
    # A que já aparecia primeiro, depois as outras pela ordem das abas; a ativa é a da aba atual.
    assert _nas_celulas(grade) == [b, a] and grade.celula_ativa() is grade.celulas[0]
    assert all(c_.nome.isVisible() for c_ in grade.celulas) and grade.celulas[0].nome.text() == "V1"
    assert grade.celulas[0].property("ativa") is True and grade.celulas[1].property("ativa") is False
    # A aba de uma vista que aparece ativa a célula dela; a de uma que não aparece a põe na ativa.
    grade.setCurrentIndex(0)
    assert grade.celula_ativa() is grade.celulas[1] and _nas_celulas(grade) == [b, a]
    grade.setCurrentIndex(2)
    assert _nas_celulas(grade) == [b, c] and grade.currentWidget() is c and not a.isVisible()
    # O menu do nome: a vista de outra célula troca de lugar com a desta.
    grade.mostrar_na_celula(grade.celulas[0], c)
    assert _nas_celulas(grade) == [c, b] and grade.currentWidget() is c
    # Quatro células com três vistas: uma vazia, com o convite; uma vista que sai deixa a célula para a de fora.
    grade.definir_disposicao("dois_por_dois")
    assert _nas_celulas(grade) == [c, b, a, None] and grade.celulas[3].vazio.isVisible()
    grade.setCurrentIndex(grade.indexOf(a))
    grade.removeTab(grade.indexOf(a))
    assert _nas_celulas(grade) == [c, b, None, None] and grade.currentWidget() in (b, c)
    grade.definir_disposicao("uma")
    assert _nas_celulas(grade) == [grade.currentWidget()]


def test_o_clique_numa_celula_a_ativa(qtbot):
    grade, (a, b, _c) = _grade(qtbot)
    grade.definir_disposicao("empilhadas")
    assert grade.currentWidget() is a
    mudou = []
    grade.currentChanged.connect(mudou.append)
    qtbot.mouseClick(b, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert grade.currentWidget() is b and mudou == [1] and grade.celula_ativa().widget is b
    # Uma vista nova vai para a célula vazia, se houver; sem nenhuma, para a ativa.
    grade.definir_disposicao("uma_e_duas")
    assert _nas_celulas(grade).count(None) == 0
    d = QLabel("d")
    grade.addTab(d, QIcon(), "V3")
    grade.setCurrentWidget(d)
    assert grade.celula_ativa().widget is d and b not in _nas_celulas(grade)


def test_no_2x2_as_colunas_andam_juntas(qtbot):
    grade, _ = _grade(qtbot, 4)
    grade.definir_disposicao("dois_por_dois")
    raiz = grade._raiz
    de_cima, de_baixo = raiz.widget(0), raiz.widget(1)
    de_cima.splitterMoved.emit(200, 1)
    de_cima.setSizes([200, 596])
    de_cima.splitterMoved.emit(200, 1)
    assert de_baixo.sizes() == de_cima.sizes()


# ---------------------------------------------------------------------- na janela

def _duas_vistas_de_tempo(janela, qtbot, tmp_path):
    f1 = abrir(janela, qtbot, captura(tmp_path / "a"))
    f2 = abrir(janela, qtbot, captura(tmp_path / "b", n=60_000))
    janela.area.plotar_canal(f1, 0)
    v1 = janela.vista_ativa()
    v2 = janela.area.nova_vista()
    janela.area.plotar_canal(f2, 0, v2)
    return v1, v2


def test_as_vistas_de_tempo_da_grade_andam_juntas(janela, qtbot, tmp_path):
    v1, v2 = _duas_vistas_de_tempo(janela, qtbot, tmp_path)
    w1, w2 = janela.area.widget_da_vista(v1), janela.area.widget_da_vista(v2)
    janela.acoes["disposicao_lado_a_lado"].trigger()
    assert janela.vistas.visiveis() == [w2, w1] and janela.vista_ativa() is v2
    assert janela.acoes["disposicao_lado_a_lado"].isChecked()
    # Ligadas, a outra vai para a janela da ativa; o zoom numa leva a outra, a cada passo.
    assert w1.janela_de_tempo() == pytest.approx(w2.janela_de_tempo())
    w1.mostrar_tempo(0.01, 0.02)
    assert w2.janela_de_tempo() == pytest.approx((0.01, 0.02))
    w2._faixa_principal().getViewBox().scaleBy(x=0.5)
    assert w1.janela_de_tempo() == pytest.approx(w2.janela_de_tempo())
    # O clique numa célula a ativa: o inspetor e as medidas são os dela.
    vb = w1._faixa_principal().getViewBox()
    ponto = w1.grafico.mapFromScene(vb.mapViewToScene(vb.viewRect().center()))
    qtbot.mouseClick(w1.grafico.viewport(), Qt.MouseButton.LeftButton, pos=ponto)
    assert janela.vista_ativa() is v1 and janela.vistas.currentWidget() is w1
    # Desligadas, cada uma no seu tempo.
    janela.acoes["ligar_eixos"].trigger()
    assert not janela.area.ligacao.ligada
    w1.mostrar_tempo(0.03, 0.05)
    assert w2.janela_de_tempo() != pytest.approx((0.03, 0.05))
    janela.acoes["ligar_eixos"].trigger()
    assert w2.janela_de_tempo() == pytest.approx((0.03, 0.05))       # religadas: a ativa manda


def test_os_espectros_andam_juntos_na_frequencia_em_hz(janela, qtbot, tmp_path):
    v1, v2 = _duas_vistas_de_tempo(janela, qtbot, tmp_path)
    janela.area.ativar_vista(v1)
    e1 = janela.area.abrir_espectro()
    janela.area.ativar_vista(v2)
    e2 = janela.area.abrir_espectro()
    w1, w2 = janela.area.widget_da_vista(e1), janela.area.widget_da_vista(e2)
    for w in (w1, w2):
        qtbot.waitUntil(lambda w=w: w.tem_dados, timeout=10_000)
    w2.log.click()                                       # uma na escala log, a outra na linear: a ligação é em Hz
    qtbot.waitUntil(lambda: w2._log_desenhado is True, timeout=10_000)
    janela.area.restaurar_grade({"disposicao": "lado_a_lado", "celulas": [e1.id, e2.id], "ligar": True})
    assert janela.vistas.visiveis() == [w1, w2]
    w1.mostrar_frequencias(500.0, 5000.0)
    assert w2.faixa_de_frequencia() == pytest.approx((500.0, 5000.0), rel=1e-6)


def test_a_grade_volta_com_o_projeto(janela, qtbot, tmp_path):
    v1, v2 = _duas_vistas_de_tempo(janela, qtbot, tmp_path)
    janela.area.restaurar_grade({"disposicao": "empilhadas", "celulas": [v1.id, v2.id], "ligar": False})
    assert janela.area.estado_da_grade() == {"disposicao": "empilhadas", "celulas": [v1.id, v2.id], "ligar": False}
    assert not janela.acoes["ligar_eixos"].isChecked()
    caminho = tmp_path / "p.shproj"
    assert janela.controle.salvar_como(caminho)
    janela.area.definir_disposicao("uma")
    assert janela.controle.abrir(caminho)
    vistas = {v.nome: v.id for v in janela.projeto.vistas}
    assert janela.area.estado_da_grade() == {"disposicao": "empilhadas", "ligar": False,
                                             "celulas": [vistas[v1.nome], vistas[v2.nome]]}
    assert janela.acoes["disposicao_empilhadas"].isChecked()
    # Estragada ou de vistas que não existem: fica o que estava, ou a célula vazia.
    assert not janela.area.restaurar_grade({"disposicao": "três"})
    assert janela.area.restaurar_grade({"disposicao": "lado_a_lado", "celulas": ["sumiu", None]})
    assert len(janela.vistas.visiveis()) == 1
