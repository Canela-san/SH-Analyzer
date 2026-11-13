"""Os componentes da interface (``sh_analyzer_gui.componentes``) e a galeria, sem tela (pytest-qt)."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.componentes import toast as toast_mod  # noqa: E402
from sh_analyzer_gui.componentes.basicos import Botao, CampoComUnidade, CartaoDeMedida, Segmentado  # noqa: E402
from sh_analyzer_gui.componentes.chip import ChipDeTraco  # noqa: E402
from sh_analyzer_gui.galeria import Galeria  # noqa: E402
from sh_analyzer_gui.tema.aplicar import aparencia  # noqa: E402
from sh_analyzer_gui.tema.tokens import TEMAS  # noqa: E402


@pytest.fixture
def app(qapp):
    criar_aplicacao([], tema="escuro")
    yield qapp
    aparencia(qapp).aplicar("escuro")


def test_botao_variantes(app, qtbot):
    for variante in ("primario", "secundario", "fantasma", "perigo"):
        b = Botao("ok", variante, "play")
        qtbot.addWidget(b)
        assert not b.icon().isNull()
        assert b.property("variante") == (None if variante == "secundario" else variante)
    with pytest.raises(ValueError):
        Botao("x", "roxo")


def test_campo_aceita_prefixo_e_recusa_o_que_nao_e_numero(app, qtbot):
    campo = CampoComUnidade("Hz", 1000, minimo=1, maximo=500_000)
    qtbot.addWidget(campo)
    assert campo.text() == "1 kHz"
    with qtbot.waitSignal(campo.valorMudou) as sinal:
        campo.setText("2,5k")
        campo.editingFinished.emit()
    assert sinal.args == [2500.0] and campo.valor == 2500 and campo.text() == "2,5 kHz"
    campo.setText("abc")
    campo.editingFinished.emit()
    assert campo.property("invalido") is True and campo.valor == 2500
    campo.setText("1 MHz")                       # fora da faixa
    campo.editingFinished.emit()
    assert campo.property("invalido") is True and "fora da faixa" in campo.toolTip()
    campo.definir_valor(400_000)
    assert campo.property("invalido") is False and campo.text() == "400 kHz"


def test_segmentado(app, qtbot):
    s = Segmentado(["FFT", "Welch", "IEC"], 1)
    qtbot.addWidget(s)
    assert s.escolhida == 1
    with qtbot.waitSignal(s.escolhaMudou) as sinal:
        s._grupo.button(2).click()
    assert sinal.args == [2] and s.escolhida == 2
    s.escolher(0)
    assert s.escolhida == 0
    with pytest.raises(ValueError):
        Segmentado([])


def test_chip_de_traco(app, qtbot):
    chip = ChipDeTraco("V_A", 0, "")
    qtbot.addWidget(chip)
    largura = chip.sizeHint().width()
    chip.definir(resumo="sonda · −DC", progresso=1.7)
    assert chip.sizeHint().width() > largura and chip.progresso == 1.0
    chip.definir(progresso=None)
    assert chip.progresso is None
    with qtbot.waitSignal(chip.clicado):
        qtbot.mouseClick(chip, Qt.MouseButton.LeftButton)
    assert chip.cor.name() == TEMAS["escuro"].tracos[0]
    aparencia().aplicar("claro")                 # a posição na paleta segue o tema: o mesmo matiz, outro tom
    assert chip.cor.name() == TEMAS["claro"].tracos[0]
    assert ChipDeTraco("x", "#123456").cor.name() == "#123456"
    chip.grab()                                   # pinta sem erro nos dois estados
    chip.definir(selecionado=True, visivel=False, progresso=0.5)
    chip.grab()


def test_cartao_de_medida(app, qtbot):
    c = CartaoDeMedida("RMS", 98.73, "V")
    qtbot.addWidget(c)
    assert c.texto == "98,73 V"
    c.definir(0.0012)
    assert c.texto == "1,2 mV"
    c.definir(float("nan"))
    assert c.texto == "—"


def test_toast_aparece_e_some(app, qtbot, monkeypatch):
    from PySide6.QtWidgets import QWidget
    pai = QWidget()
    pai.resize(400, 300)
    qtbot.addWidget(pai)
    pai.show()
    t = toast_mod.Toast.mostrar(pai, "Figura exportada", "sucesso", duracao_ms=50)
    assert t.isVisible() and t.parent() is pai and t.y() > 200
    qtbot.waitUntil(lambda: not pai.findChildren(toast_mod.Toast), timeout=2000)
    monkeypatch.setattr(toast_mod, "movimento_reduzido", True)
    toast_mod.Toast.mostrar(pai, "sem animação", "aviso", duracao_ms=20)
    qtbot.waitUntil(lambda: not pai.findChildren(toast_mod.Toast), timeout=1000)
    with pytest.raises(ValueError):
        toast_mod.Toast(pai, "x", "roxo")


def test_galeria_abre_e_troca_o_tema(app, qtbot):
    g = Galeria()
    qtbot.addWidget(g)
    g.show()
    assert len(g.botoes) == 4 and len(g.chips) == 4 and len(g.cartoes) == 4
    g.botao_tema.click()
    assert aparencia().tema is TEMAS["claro"]
    qtbot.mouseClick(g.chips[1], Qt.MouseButton.LeftButton)
    assert g.chips[1].selecionado and not g.chips[0].selecionado
