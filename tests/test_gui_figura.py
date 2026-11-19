"""O modelo da figura (``sh_analyzer_gui.dados.figura``, F5.1), sem Qt: os modelos de página, a figura nova e os
rótulos, o que não vale (com a razão), a ida e a volta pelo ``.shproj`` (a versão 5, com um painel ligado e um
congelado), o projeto da versão 4 sem figuras e, com o Qt, a figura que passa pelo projeto aberto."""

import json
from dataclasses import replace

import pytest
from sh_analyzer_gui.dados import figura as fig
from sh_analyzer_gui.dados import projeto as arq
from sh_analyzer_gui.dados.figura import Estilo, Figura, FiguraInvalida, Painel
from sh_analyzer_gui.dados.projeto import ProjetoInvalido
from test_gui_projeto import exemplo


def test_os_modelos_de_pagina():
    larguras = {m.id: m.largura_mm for m in fig.MODELOS}
    assert larguras == {"ieee_1": 88.0, "ieee_2": 181.0, "elsevier_1": 90.0, "elsevier_15": 140.0,
                        "elsevier_2": 190.0, "fapesp": 210.0 - 30.0 - 20.0, "slide": 254.0, "poster": 841.0}
    slide, poster = fig.modelo("slide"), fig.modelo("poster")
    assert slide.altura_mm / slide.largura_mm == pytest.approx(9 / 16) and poster.altura_maxima_mm == 1189.0
    assert fig.modelo("ieee_1").estilo.familia == "STIX" and slide.estilo.familia == "Inter"
    with pytest.raises(FiguraInvalida, match="modelo de página desconhecido"):
        fig.modelo("a4")


def test_a_figura_nova_e_os_rotulos():
    f = fig.nova("f1", "Afundamento", "ieee_2", vista="v1")
    assert (f.largura_mm, f.altura_mm, f.estilo) == (181.0, 90.0, fig.modelo("ieee_2").estilo)
    assert [p.vista for p in f.paineis] == ["v1"] and f.rotulos() == {"f1-1": "(a)"} and f.separador_decimal == ","
    # Numa grade 2 × 3: um painel largo em cima, os de baixo na ordem de leitura; um sem rótulo e um com o próprio
    # não contam nas letras.
    grade = Figura("f2", "Grade", linhas=2, colunas=3, idioma="en", paineis=(
        Painel("baixo3", 1, 2, vista="v2"), Painel("cima", 0, 0, colunas=3, vista="v1"),
        Painel("baixo1", 1, 0, rotulo=""), Painel("baixo2", 1, 1, rotulo="(z)", vista="v1")))
    assert [p.id for p in grade.em_ordem()] == ["cima", "baixo1", "baixo2", "baixo3"]
    assert grade.rotulos() == {"cima": "(a)", "baixo1": "", "baixo2": "(z)", "baixo3": "(b)"}
    assert grade.vistas_ligadas() == {"v1", "v2"} and grade.separador_decimal == "."
    assert [fig._letra(n) for n in (0, 25, 26, 27)] == ["a", "z", "aa", "ab"]


@pytest.mark.parametrize(("criar", "trecho"), [
    (lambda: Figura("f", "F", paineis=(Painel("p", 0, 1),)), "sai da grade"),
    (lambda: Figura("f", "F", colunas=2, paineis=(Painel("p", colunas=2), Painel("q", 0, 1))), "se sobrepõem"),
    (lambda: Figura("f", "F", paineis=(Painel("p"), Painel("p")), colunas=2), "dois painéis com o id"),
    (lambda: Figura("f", "F", "nature"), "modelo de página desconhecido"),
    (lambda: Figura("f", "F", altura_mm=-5), "a altura"),
    (lambda: Figura("f", "F", altura_mm=300), "a altura"),
    (lambda: Figura("f", "F", idioma="fr"), "idioma desconhecido"),
    (lambda: Figura("f", "F", linhas=7), "fora de 1 a 6"),
    (lambda: Figura("f", " "), "sem nome"),
    (lambda: Painel("p", limites_x=(2.0, 1.0)), "o primeiro menor"),
    (lambda: Painel("p", linha=-1), "linha inválido"),
    (lambda: Estilo("Comic Sans"), "família de letra desconhecida"),
    (lambda: Estilo(texto_pt=2), "fora de 4 a 72"),
    (lambda: Estilo(linha_pt=0), "fora de 0.1 a 10"),
])
def test_o_que_nao_vale_e_recusado(criar, trecho):
    with pytest.raises(FiguraInvalida, match=trecho):
        criar()


def _com_figuras() -> arq.ProjetoSalvo:
    p = exemplo()
    congelada = replace(p.vistas[0], id="v1-copia")
    figura = Figura("fig1", "Afundamento e corrente", "ieee_2", altura_mm=120.0, linhas=2, colunas=1, idioma="en",
                    estilo=Estilo("Inter", texto_pt=9, linha_pt=1.2), eixos_x_compartilhados=True, paineis=(
                        Painel("a", 0, 0, vista="v1", limites_x=(0.1, 0.2)),
                        Painel("b", 1, 0, vista="v1", congelado=congelada, rotulo="(b) 09h30", limites_y=(-2, 2))))
    return replace(p, figuras=(figura, fig.nova("fig2", "Vazia", "slide", vista="v2")))


def test_a_figura_vai_e_volta_pelo_projeto():
    p = _com_figuras()
    dados = json.loads(json.dumps(arq.para_dict(p)))
    assert dados["versao"] == arq.VERSAO and [f["id"] for f in dados["figuras"]] == ["fig1", "fig2"]
    assert arq.de_dict(dados) == p
    # Um estilo salvo pela metade completa com o do modelo de página.
    dados["figuras"][1]["estilo"] = {"familia": "STIX"}
    assert arq.de_dict(dados).figuras[1].estilo == replace(fig.modelo("slide").estilo, familia="STIX")


def test_um_projeto_da_versao_4_abre_sem_figuras():
    dados = arq.para_dict(_com_figuras())
    dados["versao"] = 4
    assert arq.de_dict(dados).figuras == ()


@pytest.mark.parametrize(("estragar", "trecho"), [
    (lambda d: d["figuras"][0]["paineis"][0].update(vista="v9"), "aponta para uma vista que não está no projeto"),
    (lambda d: d["figuras"][1].update(id="fig1"), "duas figuras com o id"),
    (lambda d: d["figuras"][0].update(cor="azul"), "campos desconhecidos: cor"),
    (lambda d: d["figuras"][0]["paineis"][1]["congelado"]["tracos"][0].update(fonte="f9"),
     "o traço 1 de a vista congelada de o painel 2 de a figura 1 aponta para uma fonte"),
    (lambda d: d["figuras"][0]["estilo"].update(texto_pt="grande"), "fora de 4 a 72"),
    (lambda d: d.update(figuras={}), "as figuras não são uma lista"),
])
def test_a_figura_que_nao_vale_recusa_o_projeto(estragar, trecho):
    dados = json.loads(json.dumps(arq.para_dict(_com_figuras())))
    estragar(dados)
    with pytest.raises(ProjetoInvalido, match=trecho):
        arq.de_dict(dados)


def test_a_figura_passa_pelo_projeto_aberto(tmp_path):
    """Com o Qt: o projeto aberto (``persistencia.montar``) guarda as figuras, e o salvo de novo as devolve iguais."""
    pytest.importorskip("PySide6")
    from sh_analyzer_gui.modelo import persistencia

    salvo = _com_figuras()
    projeto, _avisos = persistencia.montar(salvo, None, tmp_path, abrir=lambda *_a, **_k: None,
                                           crc_de=lambda _c: None)
    assert projeto.figuras == salvo.figuras and projeto.figura("fig2").pagina.id == "slide"
    assert persistencia.descrever(projeto, tmp_path).figuras == salvo.figuras
