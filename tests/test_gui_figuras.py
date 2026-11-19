"""As figuras no projeto aberto (F5.3), sem a tela: as edições da figura (``dados/figura.py``: pôr, trocar e tirar
um painel, trocar o modelo) e os comandos com desfazer (``modelo/comandos.py``): a figura nova, a mudada (os passos
seguidos que se juntam, o que não muda nada), a apagada; fechar a vista de um painel ligado o congela, e fechar a
captura tira os traços dela das cópias congeladas, e o projeto continua salvável; o desfazer devolve tudo."""

import json

import pytest
from sh_analyzer_gui.dados import figura as fig
from sh_analyzer_gui.dados.figura import FiguraInvalida, Painel

# ------------------------------------------------------------------ as edições, sem Qt


def test_por_um_painel():
    f = fig.nova("f", "F", "ieee_1", vista="v", id_do_painel="a")
    duas = fig.acrescentar_painel(f, "b", vista="v")
    assert (duas.linhas, duas.altura_mm, duas.paineis[1]) == (2, 132.0, Painel("b", 1, 0, vista="v"))
    # Numa grade com célula livre, o painel vai para ela, e a página não muda.
    larga = f.com(colunas=2, modelo="ieee_2", altura_mm=90.0)
    assert fig.acrescentar_painel(larga, "b").paineis[1] == Painel("b", 0, 1)
    # A linha nova ocupa a largura da grade; a altura para na máxima do modelo.
    alta = fig.acrescentar_painel(larga.com(paineis=(Painel("a", colunas=2),), altura_mm=200.0), "b")
    assert (alta.paineis[1].colunas, alta.altura_mm) == (2, 230.0)
    cheia = f.com(linhas=fig.GRADE_MAXIMA, paineis=tuple(Painel(f"p{i}", i) for i in range(fig.GRADE_MAXIMA)))
    with pytest.raises(FiguraInvalida, match="já tem 6 linhas"):
        fig.acrescentar_painel(cheia, "x")


def test_trocar_e_tirar_painel_e_a_menor_grade():
    f = fig.acrescentar_painel(fig.nova("f", "F", vista="v", id_do_painel="a"), "b")
    assert fig.menor_grade(f) == (2, 1)
    f = fig.trocar_painel(f, Painel("b", 1, 0, vista="v", rotulo="(z)"))
    assert f.rotulos() == {"a": "(a)", "b": "(z)"}
    assert [p.id for p in fig.tirar_painel(f, "a").paineis] == ["b"]
    with pytest.raises(FiguraInvalida, match="não tem o painel"):
        fig.trocar_painel(f, Painel("c"))
    with pytest.raises(FiguraInvalida, match="não tem o painel"):
        fig.tirar_painel(f, "c")


def test_trocar_o_modelo():
    f = fig.nova("f", "F", "ieee_1").com(altura_mm=200.0)
    slide = fig.trocar_modelo(f, "slide")
    assert (slide.largura_mm, slide.altura_mm, slide.estilo) == (254.0, 142.875, fig.modelo("slide").estilo)
    assert fig.trocar_modelo(f, "poster").altura_mm == 200.0


# ------------------------------------------------------------------ os comandos, com o Qt

pytest.importorskip("PySide6")

import numpy as np  # noqa: E402
from capturas_sinteticas import escrever_bin  # noqa: E402
from sh_analyzer_gui.dados import projeto as arq  # noqa: E402
from sh_analyzer_gui.dados.captura import abrir_fonte  # noqa: E402
from sh_analyzer_gui.dados.receita import ReceitaDoTraco  # noqa: E402
from sh_analyzer_gui.modelo import persistencia  # noqa: E402
from sh_analyzer_gui.modelo.comandos import (  # noqa: E402
    AdicionarFigura,
    AdicionarFonte,
    AdicionarTraco,
    AdicionarVista,
    MudarFigura,
    RemoverFigura,
    RemoverFonte,
    RemoverVista,
)
from sh_analyzer_gui.modelo.objetos import FonteDoProjeto, Projeto, Traco, Vista  # noqa: E402


def _salvavel(projeto: Projeto, pasta) -> arq.ProjetoSalvo:
    """O projeto passa pelo arquivo (a validação inteira da ida e da volta)."""
    return arq.de_dict(json.loads(json.dumps(arq.para_dict(persistencia.descrever(projeto, pasta)))))


@pytest.fixture
def projeto(qapp, tmp_path):
    """Uma captura e uma vista ("v1") com a tensão."""
    p = Projeto()
    caminho = escrever_bin(tmp_path / "a.bin", [np.zeros(4096), np.ones(4096)], canais=(1, 3), versao=9)
    fonte = FonteDoProjeto(abrir_fonte(caminho))
    vista = Vista("V e I", id="v1")
    for comando in (AdicionarFonte(p, fonte), AdicionarVista(p, vista),
                    AdicionarTraco(vista, Traco(ReceitaDoTraco(fonte.id, 1, "V", 0)))):
        p.pilha.push(comando)
    yield p
    p.pilha.clear()


def test_a_figura_nova_mudada_e_apagada_com_desfazer(projeto, tmp_path):
    p = projeto
    f = fig.nova("f1", "Afundamento", vista="v1", id_do_painel="a")
    p.pilha.push(AdicionarFigura(p, f))
    assert p.figuras == (f,) and p.modificado
    with pytest.raises(ValueError, match="já está no projeto"):
        AdicionarFigura(p, f)
    with pytest.raises(ValueError, match="vista que não está no projeto: v9"):
        AdicionarFigura(p, fig.nova("f2", "Solta", vista="v9"))
    # Girar a altura: os passos seguidos viram um; o desfazer volta ao começo.
    for altura in (70.0, 80.0, 90.0):
        p.pilha.push(MudarFigura(p, p.figura("f1").com(altura_mm=altura), "Mudar a altura", juntar=True))
    assert p.figura("f1").altura_mm == 90.0 and p.pilha.count() == 5 and p.pilha.text(4) == "Mudar a altura (Afundamento)"
    p.pilha.undo()
    assert p.figura("f1") == f
    p.pilha.redo()
    # Uma mudança que não muda nada não vira passo.
    p.pilha.push(MudarFigura(p, p.figura("f1"), "Nada"))
    assert p.pilha.count() == 5
    antes = p.figura("f1")
    p.pilha.push(RemoverFigura(p, "f1"))
    assert p.figuras == ()
    p.pilha.undo()
    assert p.figuras == (antes,)
    _salvavel(p, tmp_path)


def test_fechar_a_vista_congela_o_painel_e_o_desfazer_o_religa(projeto, tmp_path):
    p = projeto
    vista = p.vista("v1")
    f = fig.acrescentar_painel(fig.nova("f1", "F", vista="v1", id_do_painel="a"), "b").com(
        paineis=(Painel("a", vista="v1"), Painel("b", 1, 0, vista="v1", limites_x=(0.0, 0.001))), linhas=2)
    p.pilha.push(AdicionarFigura(p, f))
    p.pilha.push(RemoverVista(p, vista, janela=(0.002, 0.004)))
    a, b = p.figura("f1").paineis
    assert a.congelado == persistencia.descrever_vista(vista) and a.limites_x == (0.002, 0.004)
    assert b.congelado is not None and b.limites_x == (0.0, 0.001)          # os limites próprios ficam
    assert p.figura("f1").vistas_ligadas() == set()
    salvo = _salvavel(p, tmp_path)
    assert salvo.figuras[0].paineis[0].congelado.tracos == a.congelado.tracos
    p.pilha.undo()
    assert p.vistas == (vista,) and p.figura("f1") == f


def test_fechar_a_captura_tira_os_tracos_das_copias_congeladas(projeto, tmp_path):
    p = projeto
    vista, fonte = p.vista("v1"), p.fontes[0]
    congelada = persistencia.descrever_vista(vista)
    f = fig.nova("f1", "F", id_do_painel="a").com(paineis=(Painel("a", vista="v1", congelado=congelada),))
    p.pilha.push(AdicionarFigura(p, f))
    p.pilha.push(RemoverFonte(p, fonte))
    assert p.figura("f1").paineis[0].congelado.tracos == () and vista.tracos == ()
    _salvavel(p, tmp_path)
    p.pilha.undo()
    assert p.figura("f1") == f and len(vista.tracos) == 1
