"""A seção Processamento do inspetor do traço (F2.4): adicionar, mudar, reordenar, desligar e tirar uma etapa, cada
passo um comando de desfazer; o corte acima da Nyquist recusado; a paleta acha "Adicionar etapa"; vários traços; e a
seção Calibração com um perfil escolhido. Sem tela."""

import json

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import FREQS_CAL, escrever_bin, planta_h  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.componentes.paleta import buscar  # noqa: E402
from sh_analyzer_gui.dados.cadeia import Cadeia, CorrecaoSonda, Filtro, RemoverDC  # noqa: E402
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
def tracos(janela, tmp_path):
    t = np.arange(20_000) / 200_000
    caminho = escrever_bin(tmp_path / "a.bin", [np.sin(2 * np.pi * 60 * t), np.cos(2 * np.pi * 60 * t)],
                           grandezas=(0, 1), versao=9)
    (fonte,) = janela.controle.abrir_capturas([caminho])
    return janela.area.plotar_canal(fonte, 0), janela.area.plotar_canal(fonte, 1)


def secao(janela):
    return janela.inspetor.do_traco.processamento


def editar(campo, texto):
    campo.setText(texto)
    campo.editingFinished.emit()


def test_cada_passo_da_cadeia_e_um_passo_de_desfazer(janela, tracos):
    a, _ = tracos
    janela.selecao.definir([a])
    sec, pilha = secao(janela), janela.projeto.pilha
    assert sec.cadeia == Cadeia() and "Nenhuma etapa" in sec.aviso.text()
    historico = [a.receita.cadeia]

    def passo():
        assert a.receita.cadeia != historico[-1]
        historico.append(a.receita.cadeia)

    sec.acoes[0].trigger()                                              # "Adicionar etapa: passa-altas"
    passo()
    assert a.receita.cadeia == Cadeia((Filtro("passa_altas", (2000.0,)),))
    (cartao,) = sec.cartoes
    assert not cartao.parametros.isHidden()                             # a etapa nova abre os parâmetros
    editar(cartao.cortes[0], "3k")
    passo()
    assert a.receita.cadeia.etapas[0].cortes == (3000.0,)
    editar(sec.cartoes[0].cortes[0], "150k")                           # acima da Nyquist (100 kHz): não entra
    assert a.receita.cadeia == historico[-1] and sec.cartoes[0].cortes[0].property("invalido")
    assert "Nyquist" in sec.cartoes[0].cortes[0].toolTip()
    sec.adicionar("remover_dc")
    passo()
    sec.adicionar("correcao_sonda")                                    # a sonda entra no começo da cadeia
    passo()
    assert [type(e) for e in a.receita.cadeia.etapas] == [CorrecaoSonda, Filtro, RemoverDC]
    sec.cartoes[0].findChild(type(sec.botao_adicionar), "descer_etapa").click()
    passo()
    assert [type(e) for e in a.receita.cadeia.etapas] == [Filtro, CorrecaoSonda, RemoverDC]
    sec.cartoes[0].chave.click()                                       # desliga o filtro
    passo()
    assert not a.receita.cadeia.etapas[0].ligada and a.receita.cadeia.resumo() == "sonda · −DC"
    sec.cartoes[2].findChild(type(sec.botao_adicionar), "remover_etapa").click()
    passo()
    assert [type(e) for e in a.receita.cadeia.etapas] == [Filtro, CorrecaoSonda]
    chip = janela.area.widget_da_vista(janela.vista_ativa()).chips[a]
    assert "sonda" in chip.resumo

    for esperada in reversed(historico[:-1]):                         # desfazer cada passo, um por um
        pilha.undo()
        assert a.receita.cadeia == esperada
        assert len(sec.cartoes) == len(esperada.etapas)               # o inspetor acompanha o desfazer
    assert pilha.text(pilha.index()).startswith("Adicionar passa-altas")    # o próximo a refazer


def test_o_tipo_e_a_ordem_do_filtro(janela, tracos):
    a, _ = tracos
    janela.selecao.definir([a])
    sec = secao(janela)
    sec.adicionar("passa_altas")
    cartao = sec.cartoes[0]
    indice = cartao.tipo.findData("passa_faixa")
    cartao.tipo.setCurrentIndex(indice)
    cartao.tipo.activated.emit(indice)
    assert a.receita.cadeia.etapas[0] == Filtro("passa_faixa", (2000.0, 80_000.0))   # o superior abaixo da Nyquist
    sec.cartoes[0].ordem.setValue(3)
    assert a.receita.cadeia.etapas[0].ordem == 3
    editar(sec.cartoes[0].cortes[1], "1k")                             # abaixo do inferior: recusado
    assert a.receita.cadeia.etapas[0].cortes == (2000.0, 80_000.0)
    assert "inferior" in sec.cartoes[0].cortes[1].toolTip()


def test_a_paleta_acha_adicionar_etapa(janela, tracos):
    a, _ = tracos
    janela.selecao.definir([a])
    (primeiro, *_) = buscar(janela.acoes_da_paleta(), "passa-altas")
    assert primeiro.texto == "Adicionar etapa: passa-altas"
    primeiro.acao.trigger()
    assert a.receita.cadeia.etapas[0].filtro == "passa_altas"
    janela.selecao.limpar()
    assert not buscar(janela.acoes_da_paleta(), "adicionar etapa")      # sem um traço no inspetor, nada


def test_varios_tracos_mudam_juntos_e_cadeias_diferentes_pedem_um_so(janela, tracos):
    a, b = tracos
    janela.selecao.definir([a, b])
    sec, pilha = secao(janela), janela.projeto.pilha
    antes = pilha.count()
    sec.adicionar("remover_dc")
    assert a.receita.cadeia == b.receita.cadeia == Cadeia((RemoverDC(),)) and pilha.count() == antes + 1
    pilha.push(MudarTracos([b], cadeia=Cadeia()))
    assert sec.cadeia is None and "cadeias diferentes" in sec.aviso.text()
    assert not sec.botao_adicionar.isEnabled() and not any(acao.isEnabled() for acao in sec.acoes)
    assert not sec.adicionar("passa_altas")


def test_a_calibracao_com_um_perfil_escolhido(janela, tracos, tmp_path):
    _, b = tracos
    perfil = tmp_path / "sonda_x.json"
    perfil.write_text(json.dumps({"id": "sonda_x", "tipo": "resposta_frequencia", "data_calibracao": "2023-11-01",
                                  "pontos": [{"freq_hz": float(f), "ganho": float(planta_h(f))} for f in FREQS_CAL]}),
                      encoding="utf-8")
    janela.selecao.definir([b])
    insp, sec = janela.inspetor.do_traco, secao(janela)
    assert "Nenhuma sonda registrada" in insp.calibracao.text() and insp.aplicar_correcao.isHidden()
    sec.adicionar("correcao_sonda")
    assert "não tem o que aplicar" in insp.calibracao.text()           # automática, num canal sem sonda
    janela.controle.dialogos = DialogosFalsos(str(perfil))
    combo = sec.cartoes[0].perfil
    indice = combo.findData("escolher")
    combo.setCurrentIndex(indice)
    combo.activated.emit(indice)
    assert b.receita.cadeia.etapas[0] == CorrecaoSonda(perfil=str(perfil))
    texto = insp.calibracao.text()
    assert "Perfil sonda_x (escolhido): sonda_x.json" in texto and "Faixa válida: 100 Hz a 80 kHz" in texto
    assert "Calibrado em 2023-11-01 (13 dias antes da captura)" in texto and "A correção está na cadeia" in texto
    assert janela.controle.dialogos.perguntas == ["Escolher o perfil de sonda"]
    # Cancelar o diálogo não muda nada.
    janela.controle.dialogos = DialogosFalsos(None)
    combo = sec.cartoes[0].perfil
    combo.setCurrentIndex(combo.findData("escolher"))
    combo.activated.emit(combo.findData("escolher"))
    assert b.receita.cadeia.etapas[0].perfil == str(perfil)


def test_mudar_o_ganho_nao_refaz_os_cartoes(janela, tracos):
    a, _ = tracos
    janela.selecao.definir([a])
    sec = secao(janela)
    sec.adicionar("passa_altas")
    cartao = sec.cartoes[0]
    janela.projeto.pilha.push(MudarTracos([a], ganho=2.0))
    assert sec.cartoes[0] is cartao                                    # o mesmo cartão (e o foco, se houver)
    janela.projeto.pilha.push(MudarTracos([a], cadeia=Cadeia()))
    assert not sec.cartoes


def test_as_etapas_da_fase_7_no_cartao(janela, tracos, qtbot):
    """F7.1 e F7.2: o integrador com o campo do corte, a unidade que a cadeia dá ao traço, e a expressão com o outro
    canal da captura (A × B), materializada como os outros traços."""
    a, _ = tracos
    janela.selecao.definir([a])
    sec = secao(janela)
    sec.adicionar("integrar")
    corte = sec.cartoes[0].campos["corte_hz"]
    editar(corte, "10")
    assert a.receita.cadeia.etapas[0].corte_hz == 10.0 and a.receita.unidade_de("V") == "V·s"
    editar(sec.cartoes[0].campos["corte_hz"], "0,001")                    # memória longa demais: recusado
    assert a.receita.cadeia.etapas[0].corte_hz == 10.0
    sec.remover(0)

    sec.adicionar("a_vezes_b")
    cartao = sec.cartoes[0]
    assert a.receita.cadeia.etapas[0].expressao == "a * c1"
    cartao.expressao.setText("a ** foo")
    cartao.expressao.editingFinished.emit()
    assert "nome desconhecido" in cartao.problema.text() and a.receita.cadeia.etapas[0].expressao == "a * c1"
    cartao.expressao.setText("a × c1")
    cartao.unidade_da_saida.setText("W")
    cartao.unidade_da_saida.editingFinished.emit()
    assert a.receita.cadeia.etapas[0].unidade_da_saida == "W" and a.receita.unidade_de("V") == "W"
    def pronta():
        estado = janela.materializacoes.estado_de(a)
        return estado.pronta if estado is not None else None

    qtbot.waitUntil(lambda: pronta() is not None, timeout=20_000)
    t = np.arange(20_000) / 200_000
    esperado = np.sin(2 * np.pi * 60 * t) * np.cos(2 * np.pi * 60 * t)
    np.testing.assert_allclose(pronta().amostras, esperado, atol=1e-3)     # o ADC de 16 bits nos dois canais
