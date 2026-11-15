"""O inspetor do traço (F1.6): editar cada campo é um passo de desfazer, vários traços mudam juntos num passo só, os
valores que diferem aparecem como "vários" e um valor recusado pela receita não entra. Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.analise.dois_pontos import escala_por_dois_pontos  # noqa: E402
from sh_analyzer_gui.componentes.toast import Toast  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.modelo.comandos import MudarTracos  # noqa: E402


@pytest.fixture
def janela(qapp, config_limpa, qtbot):
    criar_aplicacao([], tema="escuro")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.show()
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


@pytest.fixture
def tracos(janela, qtbot, tmp_path):
    t = np.arange(20_000) / 200_000
    caminho = escrever_bin(tmp_path / "a.bin", [np.sin(2 * np.pi * 60 * t), np.cos(2 * np.pi * 60 * t)],
                           grandezas=(0, 1), versao=9, extensao={"ganhos": [10.0, 20.0]})
    (fonte,) = janela.controle.abrir_capturas([caminho])
    return janela.area.plotar_canal(fonte, 0), janela.area.plotar_canal(fonte, 1)


def editar(campo, texto):
    campo.setText(texto)
    campo.editingFinished.emit()


def test_selecionar_um_traco_mostra_o_inspetor_dele(janela, tracos):
    a, _ = tracos
    janela.selecao.definir([a])
    insp = janela.inspetor
    assert insp.currentWidget() is insp.do_traco
    t = insp.do_traco
    assert t.titulo.text() == a.nome and t.nome.text() == a.nome and t.canal.text() == "0 · tensão (V)"
    assert t.botoes_de_cor[0].isChecked() and t.visivel.isChecked() and t.faixa.value() == 1
    assert t.offset.unidade == "V" and t.ganho.text() == "1"
    janela.selecao.limpar()
    assert insp.currentWidget() is insp.vazio


def test_cada_campo_e_um_passo_de_desfazer(janela, tracos):
    a, _ = tracos
    janela.selecao.definir([a])
    t, pilha = janela.inspetor.do_traco, janela.projeto.pilha
    contagem = pilha.count()
    editar(t.nome, "V_A")
    t.botoes_de_cor[4].click()
    editar(t.ganho, "-2,5")
    editar(t.offset, "100m")
    editar(t.deslocamento, "4,2 ms")
    t.faixa.setValue(3)
    t.visivel.click()
    r = a.receita
    assert (r.nome, r.cor, r.ganho, r.offset, r.deslocamento_s, r.faixa, r.visivel) == \
        ("V_A", 4, -2.5, pytest.approx(0.1), pytest.approx(0.0042), 2, False)
    assert pilha.count() == contagem + 7
    assert t.offset.text() == "100 mV" and t.titulo.text() == "V_A"
    for _ in range(7):
        pilha.undo()
    assert a.receita.nome != "V_A" and a.receita.cor == 0 and a.receita.visivel
    assert t.nome.text() == a.nome and t.botoes_de_cor[0].isChecked()   # o inspetor acompanha o desfazer


def test_um_valor_igual_ou_recusado_nao_entra_na_pilha(janela, tracos):
    a, _ = tracos
    janela.selecao.definir([a])
    t, pilha = janela.inspetor.do_traco, janela.projeto.pilha
    contagem = pilha.count()
    editar(t.ganho, "0")
    assert t.ganho.property("invalido") is True and "ganho" in t.ganho.toolTip()
    editar(t.nome, "   ")                                              # vazio: volta o nome
    assert t.nome.text() == a.nome
    t.botoes_de_cor[0].click()                                          # a mesma cor
    assert pilha.count() == contagem and a.receita.ganho == 1.0


def test_varios_tracos_mudam_juntos_num_passo_so(janela, tracos):
    a, b = tracos
    janela.projeto.pilha.push(MudarTracos([b], ganho=3.0))
    janela.selecao.definir([a, b])
    t, pilha = janela.inspetor.do_traco, janela.projeto.pilha
    assert t.titulo.text() == "2 traços" and not t.nome.isEnabled() and t.nome.placeholderText() == "vários"
    assert t.ganho.text() == "" and t.ganho.placeholderText() == "vários"   # ganhos diferentes
    assert t.offset.text() == "0" and t.offset.unidade == ""             # o mesmo offset; unidades diferentes (V e A)
    assert t.faixa.value() == 0 and t.faixa.text() == "vários"          # faixas diferentes
    assert not any(b.isChecked() for b in t.botoes_de_cor)
    contagem = pilha.count()
    t.ganho.editingFinished.emit()                                      # passar pelo campo sem digitar: nada
    assert pilha.count() == contagem
    editar(t.deslocamento, "1 ms")
    assert a.receita.deslocamento_s == b.receita.deslocamento_s == pytest.approx(1e-3)
    assert pilha.count() == contagem + 1 and pilha.undoText() == "Mudar o deslocamento no tempo de 2 traços"
    inverter = [w for w in t.findChildren(type(t.botoes_de_cor[0])) if w.objectName() == "botao_inverter"][0]
    inverter.click()                                                    # cada um troca o sinal do seu, num passo
    assert (a.receita.ganho, b.receita.ganho) == (-1.0, -3.0) and pilha.count() == contagem + 2
    pilha.undo()
    assert (a.receita.ganho, b.receita.ganho) == (1.0, 3.0)
    t.visivel.click()
    assert a.receita.visivel == b.receita.visivel


def test_o_inspetor_segue_a_selecao_pela_vista(janela, tracos, qtbot):
    a, b = tracos
    w = janela.area.widget_da_vista(janela.vista_ativa())
    w.tracoClicado.emit(b, Qt.KeyboardModifier.NoModifier)
    assert janela.inspetor.do_traco.tracos == (b,)
    janela.projeto.pilha.push(MudarTracos([b], nome="I_A"))           # mudado por fora: o inspetor acompanha
    assert janela.inspetor.do_traco.titulo.text() == "I_A"


def escolher_unidade(seletor, texto):
    seletor.lineEdit().setText(texto)
    seletor.lineEdit().editingFinished.emit()


def faixa_do(janela, traco):
    w = janela.area.widget_da_vista(janela.vista_ativa())
    return w.faixas[traco.receita.faixa].getAxis("left").rotulo


def test_a_unidade_da_mesma_familia_converte_o_ganho_e_o_offset(janela, tracos):
    a, _ = tracos
    janela.selecao.definir([a])
    t, pilha = janela.inspetor.do_traco, janela.projeto.pilha
    assert t.unidade.currentText() == "V" and "a do canal" in t.unidade.toolTip()
    editar(t.offset, "0,25")
    contagem = pilha.count()
    escolher_unidade(t.unidade, "mV")
    r = a.receita
    assert (r.unidade, r.ganho, r.offset) == ("mV", pytest.approx(1000.0), pytest.approx(250.0))
    assert pilha.count() == contagem + 1 and pilha.undoText() == f"Unidade de {a.nome}: mV"
    assert t.ganho.unidade == "mV/V" and t.ganho.text() == "1000 mV/V" and t.offset.text() == "250 mV"
    assert faixa_do(janela, a) == "tensão (mV)"
    escolher_unidade(t.unidade, "V")                                    # de volta à do canal: sem unidade própria
    r = a.receita
    assert (r.unidade, r.ganho, r.offset) == ("", pytest.approx(1.0), pytest.approx(0.25))
    assert t.ganho.unidade == "" and faixa_do(janela, a) == "tensão (V)"
    pilha.undo()
    pilha.undo()
    assert (a.receita.unidade, a.receita.ganho, a.receita.offset) == ("", 1.0, 0.25)


def test_outra_familia_so_troca_o_rotulo_e_avisa(janela, tracos):
    a, _ = tracos
    janela.selecao.definir([a])
    t = janela.inspetor.do_traco
    escolher_unidade(t.unidade, "°C")
    assert (a.receita.unidade, a.receita.ganho, a.receita.offset) == ("°C", 1.0, 0.0)
    avisos = [w.rotulo.text() for w in janela.findChildren(Toast)]
    assert any("De V para °C não há conversão" in texto for texto in avisos)
    assert t.ganho.text() == "1 °C/V" and t.unidade.toolTip() == "temperatura"
    assert faixa_do(janela, a) == "temperatura (°C)"
    escolher_unidade(t.unidade, "K")                                    # °C para K: converte
    assert (a.receita.unidade, a.receita.ganho, a.receita.offset) == ("K", 1.0, pytest.approx(273.15))
    escolher_unidade(t.unidade, "kgf")                                  # fora do catálogo: vale, sem grandeza
    assert a.receita.unidade == "kgf" and faixa_do(janela, a) == "valor (kgf)"


def test_uma_unidade_invalida_nao_entra(janela, tracos):
    a, _ = tracos
    janela.selecao.definir([a])
    t, pilha = janela.inspetor.do_traco, janela.projeto.pilha
    contagem = pilha.count()
    escolher_unidade(t.unidade, "m s")
    assert t.unidade.property("invalido") is True and "espaços" in t.unidade.toolTip()
    escolher_unidade(t.unidade, "k")                                    # maiúscula conta: "k" não vira "K"
    assert a.receita.unidade == "k" and pilha.count() == contagem + 1


def test_varios_tracos_cada_um_converte_o_seu(janela, tracos):
    a, b = tracos
    janela.projeto.pilha.push(MudarTracos([b], ganho=3.0))
    janela.selecao.definir([a, b])
    t, pilha = janela.inspetor.do_traco, janela.projeto.pilha
    assert t.unidade.currentText() == "" and t.unidade.lineEdit().placeholderText() == "vários"
    assert not t.dois_pontos.isEnabled()                                # canais em V e em A: as entradas diferem
    contagem = pilha.count()
    escolher_unidade(t.unidade, "mA")
    assert (a.receita.unidade, a.receita.ganho) == ("mA", 1.0)          # V para mA: só o rótulo
    assert (b.receita.unidade, b.receita.ganho) == ("mA", pytest.approx(3000.0))   # A para mA: converte
    assert pilha.count() == contagem + 1
    pilha.undo()
    assert (a.receita.unidade, b.receita.unidade, b.receita.ganho) == ("", "", 3.0)


@pytest.mark.parametrize("x1, y1, x2, y2, ganho, offset", [
    (4e-3, 0.0, 20e-3, 10.0, 625.0, -2.5),       # 4 a 20 mA para 0 a 10 bar
    (0.0, -50.0, 1.0, 50.0, 100.0, -50.0),
    (2.0, 1.0, 1.0, 3.0, -2.0, 5.0),
])
def test_a_reta_dos_dois_pontos(x1, y1, x2, y2, ganho, offset):
    assert escala_por_dois_pontos(x1, y1, x2, y2) == (pytest.approx(ganho), pytest.approx(offset))


@pytest.mark.parametrize("x1, y1, x2, y2, trecho", [
    (1.0, 0.0, 1.0, 5.0, "entradas"), (0.0, 2.0, 1.0, 2.0, "zero"), (0.0, -1e308, 1e-308, 1e308, "finito"),
])
def test_dois_pontos_que_nao_dao_uma_escala(x1, y1, x2, y2, trecho):
    with pytest.raises(ValueError, match=trecho):
        escala_por_dois_pontos(x1, y1, x2, y2)


def test_calibrar_por_dois_pontos(janela, tracos):
    a, _ = tracos
    janela.selecao.definir([a])
    t, pilha = janela.inspetor.do_traco, janela.projeto.pilha
    d = t.calibrar_por_dois_pontos()
    assert d is t.dialogo_dois_pontos and d.isVisible()
    assert [c.text() for c in d.entradas + d.valores] == ["0 V", "1 V", "0 V", "1 V"]   # a escala de agora
    assert d.resultado.text() == "Ganho 1 · offset 0 V"
    escolher_unidade(d.seletor, "bar")
    for campo, texto in zip(d.entradas + d.valores, ["0,5", "4,5", "0", "10"]):
        editar(campo, texto)
    assert d.resultado.text() == "Ganho 2,5 bar/V · offset -1,25 bar" and d.aplicar.isEnabled()
    contagem = pilha.count()
    d.aplicar.click()
    r = a.receita
    assert (r.unidade, r.ganho, r.offset) == ("bar", pytest.approx(2.5), pytest.approx(-1.25))
    assert pilha.count() == contagem + 1 and pilha.undoText() == f"Dois pontos em {a.nome}"
    assert t.dialogo_dois_pontos is None and t.ganho.text() == "2,5 bar/V"

    d = t.calibrar_por_dois_pontos()                                    # abre com a escala nova, em bar
    assert [c.text() for c in d.valores] == ["-1,25 bar", "1,25 bar"]
    escolher_unidade(d.seletor, "kPa")                                  # os valores convertidos
    assert [c.text() for c in d.valores] == ["-125 kPa", "125 kPa"]
    editar(d.entradas[1], "0")                                          # as entradas iguais: não aplica
    assert not d.aplicar.isEnabled() and "entradas são iguais" in d.resultado.text()
    d.accept()
    assert d.isVisible() and pilha.count() == contagem + 1              # o diálogo fica, com o motivo
    d.reject()
    assert a.receita.unidade == "bar" and t.dialogo_dois_pontos is None
