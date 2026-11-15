"""O modelo e o desfazer (``sh_analyzer_gui.modelo``, F1.2): cada comando faz e desfaz, o modelo avisa quem desenha,
a seleção segue o projeto, e a janela mostra o projeto e o desfazer dele. Sem tela (pytest-qt)."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from sh_analyzer_gui.dados.captura import abrir_fonte  # noqa: E402
from sh_analyzer_gui.dados.receita import ReceitaDoTraco, ReceitaInvalida  # noqa: E402
from sh_analyzer_gui.modelo.comandos import (  # noqa: E402
    AdicionarFonte,
    AdicionarTraco,
    AdicionarVista,
    MudarTracos,
    RemoverFonte,
    RemoverTracos,
    RemoverVista,
    RenomearVista,
)
from sh_analyzer_gui.modelo.objetos import FonteDoProjeto, Projeto, Traco, Vista  # noqa: E402
from sh_analyzer_gui.modelo.selecao import Selecao  # noqa: E402


class Gravador:
    """Guarda cada emissão dos sinais ligados a ele: ``(nome, args)``."""

    def __init__(self):
        self.eventos = []

    def ligar(self, objeto, *nomes):
        for nome in nomes:
            getattr(objeto, nome).connect(lambda *args, nome=nome: self.eventos.append((nome, args)))
        return self

    def nomes(self):
        return [n for n, _ in self.eventos]

    def limpar(self):
        self.eventos.clear()


def traco(nome="V_A", cor=0, fonte="f1", canal=0) -> Traco:
    return Traco(ReceitaDoTraco(fonte=fonte, canal=canal, nome=nome, cor=cor))


@pytest.fixture
def projeto(qapp):
    p = Projeto()
    vista = Vista("Tempo")
    p.pilha.push(AdicionarVista(p, vista))
    p.pilha.clear()
    return p


def test_adicionar_e_remover_um_traco(projeto):
    vista = projeto.vistas[0]
    g = Gravador().ligar(vista, "tracoEntrou", "tracoSaiu").ligar(projeto, "tracoEntrou", "tracoSaiu")
    a = traco("V_A")
    projeto.pilha.push(AdicionarTraco(vista, a))
    assert vista.tracos == (a,) and g.nomes() == ["tracoEntrou", "tracoEntrou"]
    assert g.eventos[0][1] == (vista, a, 0)
    assert projeto.pilha.undoText() == "Adicionar V_A"
    g.limpar()
    projeto.pilha.undo()
    assert vista.tracos == () and g.nomes() == ["tracoSaiu", "tracoSaiu"]
    projeto.pilha.redo()
    assert vista.tracos == (a,)
    with pytest.raises(ValueError, match="já está"):
        AdicionarTraco(vista, a)


def test_remover_varios_devolve_cada_um_na_sua_posicao(projeto):
    vista = projeto.vistas[0]
    tracos = [traco(n, i) for i, n in enumerate("ABCDE")]
    for t in tracos:
        projeto.pilha.push(AdicionarTraco(vista, t))
    projeto.pilha.push(RemoverTracos(vista, [tracos[3], tracos[0], tracos[3], tracos[1]]))
    assert [t.nome for t in vista.tracos] == ["C", "E"]
    assert projeto.pilha.undoText() == "Remover 3 traços"
    projeto.pilha.undo()
    assert vista.tracos == tuple(tracos)
    with pytest.raises(ValueError, match="não está"):
        RemoverTracos(vista, [traco("fora")])
    with pytest.raises(ValueError):
        RemoverTracos(vista, [])


def test_a_cor_segue_o_traco_e_a_livre_volta_para_o_proximo(projeto):
    vista = projeto.vistas[0]
    a, b, c = (traco(n, vista.proxima_cor()) for n in "ABC")
    for t in (a, b, c):
        projeto.pilha.push(AdicionarTraco(vista, Traco(t.receita.com(cor=vista.proxima_cor()))))
    assert [t.receita.cor for t in vista.tracos] == [0, 1, 2]
    projeto.pilha.push(RemoverTracos(vista, [vista.tracos[1]]))
    assert [t.receita.cor for t in vista.tracos] == [0, 2]          # os que ficam não mudam de cor
    assert vista.proxima_cor() == 1


def test_mudar_varios_tracos_e_um_passo_so(projeto):
    vista = projeto.vistas[0]
    a, b = traco("A", 0), traco("B", 1)
    for t in (a, b):
        projeto.pilha.push(AdicionarTraco(vista, t))
    g = Gravador().ligar(projeto, "tracoMudou")
    projeto.pilha.push(MudarTracos([a, b], ganho=-1.0, offset=2.0))
    assert (a.receita.ganho, b.receita.offset) == (-1.0, 2.0)
    assert projeto.pilha.undoText() == "Mudar 2 traços"
    assert [args for _, args in g.eventos] == [(a, frozenset({"ganho", "offset"})), (b, frozenset({"ganho", "offset"}))]
    projeto.pilha.undo()
    assert (a.receita.ganho, b.receita.offset) == (1.0, 0.0)
    projeto.pilha.redo()
    projeto.pilha.push(MudarTracos([a], cor=4))
    assert projeto.pilha.undoText() == "Mudar a cor de A"
    projeto.pilha.push(MudarTracos([b], visivel=False))
    assert projeto.pilha.undoText() == "Esconder B"
    projeto.pilha.push(MudarTracos([b], nome="I_A"))
    assert projeto.pilha.undoText() == "Renomear B para I_A"


def test_uma_mudanca_para_cada_traco_e_um_passo_so(projeto):
    vista = projeto.vistas[0]
    a, b = traco("A", 0), traco("B", 1)
    for t in (a, b):
        projeto.pilha.push(AdicionarTraco(vista, t))
    contagem = projeto.pilha.count()
    projeto.pilha.push(MudarTracos({a: {"ganho": 2.0}, b: {"ganho": -3.0, "unidade": "°C"}}, texto="Unidade: °C"))
    assert (a.receita.ganho, a.receita.unidade, b.receita.ganho, b.receita.unidade) == (2.0, "", -3.0, "°C")
    assert projeto.pilha.count() == contagem + 1 and projeto.pilha.undoText() == "Unidade: °C"
    projeto.pilha.undo()
    assert (a.receita.ganho, b.receita.ganho, b.receita.unidade) == (1.0, 1.0, "")
    projeto.pilha.push(MudarTracos([a], unidade="K"))
    assert projeto.pilha.undoText() == "Mudar a unidade de A"
    with pytest.raises(ValueError, match="dicionário"):
        MudarTracos({a: {"ganho": 2.0}}, cor=1)
    with pytest.raises(ValueError, match="o que muda"):
        MudarTracos({a: {}})
    with pytest.raises(ReceitaInvalida, match="ganho"):              # um inválido recusa o comando inteiro
        MudarTracos({a: {"ganho": 2.0}, b: {"ganho": 0}})
    assert a.receita.ganho == 1.0


def test_uma_mudanca_invalida_nao_entra_na_pilha(projeto):
    vista = projeto.vistas[0]
    a = traco("A")
    projeto.pilha.push(AdicionarTraco(vista, a))
    contagem = projeto.pilha.count()
    with pytest.raises(ReceitaInvalida, match="ganho"):
        projeto.pilha.push(MudarTracos([a], ganho=0))
    with pytest.raises(ReceitaInvalida, match="canal"):
        MudarTracos([a], canal=3)
    assert projeto.pilha.count() == contagem and a.receita.ganho == 1.0


def test_mudancas_seguidas_se_juntam_quando_pedido(projeto):
    vista = projeto.vistas[0]
    a = traco("A")
    projeto.pilha.push(AdicionarTraco(vista, a))
    contagem = projeto.pilha.count()
    for ganho in (1.5, 2.0, 2.5):                                     # arrastar o ganho
        projeto.pilha.push(MudarTracos([a], juntar=True, ganho=ganho))
    assert projeto.pilha.count() == contagem + 1 and a.receita.ganho == 2.5
    projeto.pilha.push(MudarTracos([a], juntar=True, offset=1.0))      # outro campo: outro passo
    assert projeto.pilha.count() == contagem + 2
    projeto.pilha.undo()
    projeto.pilha.undo()
    assert a.receita.ganho == 1.0                                     # um desfazer volta o arrasto inteiro
    projeto.pilha.redo()
    projeto.pilha.push(MudarTracos([a], ganho=3.0))                    # sem juntar: passo próprio
    projeto.pilha.push(MudarTracos([a], ganho=4.0))
    assert projeto.pilha.count() == contagem + 3


def test_vistas_entram_saem_e_mudam_de_nome(projeto):
    g = Gravador().ligar(projeto, "vistaEntrou", "vistaSaiu", "vistaMudou", "tracoMudou")
    nova = Vista("Espectro? não, tempo")
    projeto.pilha.push(AdicionarVista(projeto, nova))
    a = traco("A")
    projeto.pilha.push(AdicionarTraco(nova, a))
    projeto.pilha.push(RenomearVista(nova, "  Afundamento  "))
    assert nova.nome == "Afundamento" and projeto.pilha.undoText() == "Renomear a vista Espectro? não, tempo para Afundamento"
    projeto.pilha.push(RemoverVista(projeto, nova))
    assert projeto.vistas == (projeto.vistas[0],) and nova.tracos == (a,)
    projeto.pilha.push(MudarTracos([a], cor=2))                         # a vista fora do projeto não repassa mais
    assert g.nomes() == ["vistaEntrou", "vistaMudou", "vistaSaiu"]
    projeto.pilha.undo()
    projeto.pilha.undo()
    assert projeto.vistas[1] is nova and nova.tracos == (a,)
    with pytest.raises(ValueError):
        RenomearVista(nova, "  ")
    with pytest.raises(ValueError, match="tipo"):
        Vista("x", tipo="xy")


@pytest.fixture
def fonte(tmp_path, qapp):
    caminho = escrever_bin(tmp_path / "c.bin", [np.zeros(2048), np.zeros(2048)], canais=(1, 3))
    return FonteDoProjeto(abrir_fonte(caminho, sondas_dir=tmp_path))


def test_fechar_uma_fonte_tira_os_tracos_dela_de_todas_as_vistas(projeto, fonte):
    projeto.pilha.push(AdicionarFonte(projeto, fonte))
    assert projeto.fonte(fonte.id) is fonte and fonte.canal(3).numero == 3 and fonte.posicao_do_canal(3) == 1
    with pytest.raises(KeyError):
        fonte.canal(2)
    v1, v2 = projeto.vistas[0], Vista("Outra")
    projeto.pilha.push(AdicionarVista(projeto, v2))
    outro = traco("de outra fonte", fonte="outra")
    proprios = [traco("c1", 0, fonte.id, 1), traco("c3", 1, fonte.id, 3)]
    for vista, t in ((v1, proprios[0]), (v1, outro), (v2, proprios[1]), (v1, traco("c3 de novo", 2, fonte.id, 3))):
        projeto.pilha.push(AdicionarTraco(vista, t))
    assert projeto.cores_do_canal(fonte.id, 3) == [2, 1]
    antes = {v: v.tracos for v in projeto.vistas}

    projeto.pilha.push(RemoverFonte(projeto, fonte))
    assert projeto.fontes == () and v1.tracos == (outro,) and v2.tracos == ()
    assert projeto.pilha.undoText() == "Fechar c.bin"
    projeto.pilha.undo()
    assert projeto.fontes == (fonte,) and {v: v.tracos for v in projeto.vistas} == antes


def test_a_selecao_segue_o_projeto(projeto):
    vista = projeto.vistas[0]
    a, b, c = traco("A", 0), traco("B", 1), traco("C", 2)
    for t in (a, b, c):
        projeto.pilha.push(AdicionarTraco(vista, t))
    selecao = Selecao(projeto)
    g = Gravador().ligar(selecao, "mudou")
    selecao.definir([a, b, a])
    assert selecao.tracos == (a, b)
    selecao.somar(c)
    selecao.alternar(a)
    assert selecao.tracos == (b, c) and a not in selecao
    selecao.definir([b, c])                                            # igual: não avisa de novo
    assert len(g.eventos) == 3
    projeto.pilha.push(RemoverTracos(vista, [b]))
    assert selecao.tracos == (c,)
    projeto.pilha.push(RemoverVista(projeto, vista))
    assert selecao.tracos == ()
    selecao.limpar()
    assert len(g.eventos) == 5


def test_o_projeto_avisa_quando_fica_modificado(projeto):
    g = Gravador().ligar(projeto, "modificadoMudou", "nomeMudou")
    assert not projeto.modificado and projeto.nome == "sem título"
    projeto.pilha.push(AdicionarTraco(projeto.vistas[0], traco()))
    assert projeto.modificado
    projeto.pilha.setClean()
    projeto.pilha.undo()
    assert projeto.modificado
    projeto.pilha.redo()
    from pathlib import Path

    projeto.definir_caminho(Path("/tmp/rede do bloco E.shproj"))
    assert projeto.nome == "rede do bloco E"
    assert g.eventos == [("modificadoMudou", (True,)), ("modificadoMudou", (False,)), ("modificadoMudou", (True,)),
                         ("modificadoMudou", (False,)), ("nomeMudou", ("rede do bloco E",))]


def test_a_janela_mostra_o_projeto_e_o_desfazer_dele(qapp, qtbot, config_limpa):
    from sh_analyzer_gui.app import criar_aplicacao
    from sh_analyzer_gui.janela import JanelaPrincipal

    criar_aplicacao([], tema="escuro")
    janela = JanelaPrincipal()
    qtbot.addWidget(janela)
    projeto = janela.projeto
    assert janela.pilha is projeto.pilha and not janela.isWindowModified()
    assert janela.barra.botao_projeto.text() == "sem título"
    projeto.pilha.push(AdicionarVista(projeto, Vista("Tempo")))
    assert janela.isWindowModified() and janela.barra.botao_projeto.text() == "sem título •"
    assert janela.acoes["desfazer"].isEnabled()

    outro = Projeto()
    janela.trocar_projeto(outro)
    assert janela.pilha is outro.pilha and not janela.acoes["desfazer"].isEnabled()
    assert not janela.isWindowModified() and janela.selecao is not None
    projeto.pilha.push(AdicionarVista(projeto, Vista("Fora")))        # o projeto antigo não mexe mais na janela
    assert not janela.isWindowModified()
    janela.acoes["desfazer"].trigger()
    assert len(projeto.vistas) == 2
    outro.pilha.setClean()
