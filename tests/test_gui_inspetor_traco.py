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
