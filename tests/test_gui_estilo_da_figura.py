"""O estilo de cada elemento da figura (F5.7; FG-02, FG-04, FG-05), sem Qt: o modelo (o estilo de cada traço, a
legenda, os nomes e os prefixos dos eixos, os modelos de estilo, a ida e a volta pelo projeto e o projeto da versão
5), cada propriedade nos artistas do Matplotlib, a matemática que não se desenha, a visão em cinza e com os
daltonismos e o pacote reproduzível com o estilo mudado (os mesmos pixels)."""

import json
from dataclasses import replace

import numpy as np
import pytest
from matplotlib.colors import to_hex
from sh_analyzer_gui.dados import desenho_da_figura as dd
from sh_analyzer_gui.dados import figura as fig
from sh_analyzer_gui.dados import visao_de_cores as vc
from sh_analyzer_gui.dados.figura import Estilo, EstiloDoTraco, Figura, FiguraInvalida, ModeloDeEstilo, Painel
from test_gui_desenho_da_figura import CORRENTE, TENSAO, Dados, _vista
from test_gui_pacote import _empacotar, _refazer, _rgb

V_B = replace(TENSAO, nome="V_B", cor=2)
VISTAS = {"v": _vista("v", TENSAO, V_B, CORRENTE)}              # t0 e t1 na faixa 0, t2 (a corrente) na 1


def _figura(estilo: Estilo | None = None, **painel) -> Figura:
    return Figura("f", "Estilo", "ieee_1", estilo=estilo, paineis=(Painel("a", vista="v", **painel),))


def _desenhar(figura: Figura, vistas=VISTAS, dados=None):
    return dd.desenhar(figura, vistas, dados or Dados(20_000), dpi=100)


# ------------------------------------------------------------------ o modelo

def test_o_estilo_de_cada_traco_e_o_que_ele_recusa():
    p = Painel("a", vista="v").com_estilo_do_traco("t0", EstiloDoTraco(cor="#AA0000", marcador="o"))
    assert p.estilo_do_traco("t0") == EstiloDoTraco(cor="#aa0000", marcador="o") and p.estilo_do_traco("t9").vazio
    assert p.com_estilo_do_traco("t0", EstiloDoTraco()).tracos == ()              # vazio: volta ao da vista
    for criar, mensagem in [(lambda: EstiloDoTraco(cor="vermelho"), "cor inválida"),
                            (lambda: EstiloDoTraco(espessura_pt=20), "fora de 0.1 a 10"),
                            (lambda: EstiloDoTraco(tracejado="~"), "tracejado desconhecido"),
                            (lambda: EstiloDoTraco(marcador="*"), "marcador desconhecido"),
                            (lambda: Painel("a", legenda="no meio"), "legenda desconhecida"),
                            (lambda: Painel("a", prefixo_y=2), "prefixo_y inválido"),
                            (lambda: Estilo(legenda_pt=100), "fora de 4 a 72"),
                            (lambda: Estilo(grade="sim"), "verdadeiro ou falso"),
                            (lambda: ModeloDeEstilo("  ", Estilo()), "sem nome")]:
        with pytest.raises(FiguraInvalida, match=mensagem):
            criar()


def test_o_estilo_vai_e_volta_pelo_projeto_e_o_da_versao_5():
    figura = _figura(Estilo("Inter", legenda_pt=6.5, marcas_para_dentro=False, moldura=False, grade=True),
                     tracos=(("t0", EstiloDoTraco("#000000", 1.5, ":", "s", "$V_{AB}$")),), legenda="fora_acima",
                     nome_x="Instante", nome_y="", prefixo_x=-6, prefixo_y=3, limites_y=(-1.0, 2.0))
    dados = json.loads(json.dumps(fig.para_dict(figura, lambda v: {})))
    assert dados["paineis"][0]["tracos"] == {"t0": {"cor": "#000000", "espessura_pt": 1.5, "tracejado": ":",
                                                    "marcador": "s", "nome": "$V_{AB}$"}}
    assert fig.de_dict(dados, "a figura", lambda v, o: None) == figura
    # Um estilo da versão 5 não tem o tamanho da legenda: ela fica do tamanho do texto, como era desenhada.
    antigo = {"id": "f", "nome": "F", "modelo": "fapesp", "estilo": {"familia": "STIX", "texto_pt": 9.5}}
    assert fig.de_dict(antigo, "a figura", lambda v, o: None).estilo.legenda_pt == 9.5


def test_os_modelos_de_estilo_em_json():
    a, b = ModeloDeEstilo("Revista", Estilo(grade=True)), ModeloDeEstilo("Slide", Estilo("Inter", texto_pt=16))
    dados = fig.modelos_de_estilo_para_json([a, b])
    # O que não vale (de outra versão, escrito à mão) fica de fora; o mesmo nome duas vezes vale o último.
    dados += [{"nome": "quebrado", "estilo": {"familia": "Comic"}}, "lixo", {"nome": "Revista", "estilo": {}}]
    assert fig.modelos_de_estilo_de_json(dados) == [b, ModeloDeEstilo("Revista", Estilo())]
    assert fig.modelos_de_estilo_de_json("nada") == []


# ------------------------------------------------------------------ o desenho

def test_cada_propriedade_do_traco_no_desenho():
    figura = _figura(tracos=(("t0", EstiloDoTraco("#112233", 2.0, "-.", "D", "Fase $A$")),
                             ("t1", EstiloDoTraco(marcador="x"))))
    pagina = _desenhar(figura)
    va, vb = pagina.mpl.axes[0].lines
    assert (to_hex(va.get_color()), va.get_linewidth(), va.get_linestyle(), va.get_marker(), va.get_label()) == \
        ("#112233", 2.0, "-.", "D", "Fase $A$")
    assert va.get_markersize() == pytest.approx(2.5 + 2.5 * 2.0)
    # Os marcadores espaçados (dez por eixo) e defasados entre os dois traços que os têm.
    assert va.get_markevery() == (0.0, 0.1) and vb.get_markevery() == pytest.approx((0.05, 0.1))
    assert vb.get_linewidth() == figura.estilo.linha_pt and vb.get_label() == "V_B"
    (corrente,) = pagina.mpl.axes[1].lines
    assert corrente.get_marker() == "None" and corrente.get_markevery() is None


def test_a_legenda_automatica_e_a_mesma_em_todo_dpi_e_foge_do_inset():
    """O canto da automática sai dos dados numa grade grossa (o "best" do Matplotlib decidia pelos vértices da
    redução M4, diferentes em cada dpi: a PNG e o PDF punham a legenda em cantos diferentes), e não cai no inset."""
    from sh_analyzer_gui.dados.figura import Inset

    cantos = {dd.desenhar(_figura(), VISTAS, Dados(20_000), dpi=dpi).mpl.axes[0].get_legend()._loc
              for dpi in (72, 100, 150, 300)}
    assert len(cantos) == 1
    for canto, proibido in (("sup_esq", 2), ("sup_dir", 1), ("inf_esq", 3)):
        figura = _figura(inset=Inset((0.01, 0.02), canto=canto))
        assert dd.desenhar(figura, VISTAS, Dados(20_000), dpi=100).mpl.axes[0].get_legend()._loc != proibido


@pytest.mark.parametrize(("legenda", "eixo", "loc", "fora"), [
    ("melhor", 0, 0, False), ("sup_esq", 0, 2, False), ("inf_dir", 1, 4, False), ("fora_dir", 0, 2, True),
    ("fora_acima", 0, 4, True)])
def test_a_legenda_em_cada_lugar(legenda, eixo, loc, fora):
    pagina = _desenhar(_figura(legenda=legenda))
    pagina.pixels()
    leg = pagina.mpl.axes[eixo].get_legend()
    assert leg is not None and (leg._loc in (1, 2, 3, 4) if legenda == "melhor" else leg._loc == loc)
    textos = [t.get_text() for t in leg.get_texts()]
    if fora:            # uma só, com os traços das duas faixas, fora do eixo de cima
        assert textos == ["V_A", "V_B", "I_A"] and pagina.mpl.axes[1].get_legend() is None
        caixa, eixo_ = leg.get_window_extent(), pagina.mpl.axes[0].get_window_extent()
        assert caixa.x0 > eixo_.x1 if legenda == "fora_dir" else caixa.y0 >= eixo_.y1
        assert leg._ncols == (3 if legenda == "fora_acima" else 1)
    else:               # a automática só com dois traços no eixo; um canto escolhido, também com um
        assert textos == (["V_A", "V_B"] if eixo == 0 else ["I_A"])
    assert all(e.get_legend() is None for e in _desenhar(_figura(legenda="nenhuma")).mpl.axes)


def test_os_nomes_os_prefixos_e_os_limites_dos_eixos():
    vistas = {"v": _vista("v", TENSAO)}
    pagina = _desenhar(_figura(nome_x="Instante", nome_y="$V_{AB}$", prefixo_x=-6, prefixo_y=-3,
                               limites_x=(0.0, 0.01), limites_y=(-250.0, 250.0)), vistas)
    (ax,) = pagina.mpl.axes
    assert (ax.get_xlabel(), ax.get_ylabel()) == ("Instante (µs)", "$V_{AB}$ (mV)")
    assert ax.get_xlim() == pytest.approx((0.0, 10_000.0)) and ax.get_ylim() == pytest.approx((-250e3, 250e3))
    x, y = ax.lines[0].get_data()
    assert x.max() < 10_010.0 and np.abs(y).max() > 1000      # os dados em µs (e uma amostra além) e em mV
    e = pagina.eixos["a"]
    assert (e.x, e.unidade_x, e.y, e.unidade_y, e.nome_y) == ((0.0, 0.01), "s", (-250.0, 250.0), "V", "Tensão")
    # Sem rótulo ("" no nome); o y de um painel com duas faixas fica o de cada uma.
    pagina = _desenhar(_figura(nome_x="", nome_y="Outro", prefixo_y=3))
    assert pagina.mpl.axes[-1].get_xlabel() == "" and pagina.mpl.axes[0].get_ylabel() == "Tensão (kV)"
    assert pagina.eixos["a"].y is None and pagina.eixos["a"].faixas == 2


def test_o_estilo_da_figura_nos_parametros():
    estilo = Estilo(legenda_pt=6.0, marcas_para_dentro=False, moldura=False, grade=True)
    pagina = _desenhar(_figura(estilo, legenda="sup_dir"))
    pagina.pixels()
    ax = pagina.mpl.axes[0]
    assert ax.get_legend().get_texts()[0].get_fontsize() == 6.0
    assert not ax.spines["top"].get_visible() and not ax.spines["right"].get_visible()
    assert ax.xaxis.get_major_ticks()[0].tick1line.get_marker() == 3                # TICKDOWN: para fora
    assert not ax.xaxis.get_major_ticks()[0].tick2line.get_visible()
    assert any(t.gridline.get_visible() for t in ax.xaxis.get_major_ticks())
    padrao = _desenhar(_figura()).mpl.axes[0]
    padrao.figure.canvas.draw()
    assert padrao.spines["top"].get_visible() and not padrao.xaxis.get_major_ticks()[0].gridline.get_visible()


def test_a_matematica_que_nao_se_desenha_sai_como_foi_escrita():
    assert dd.erro_no_texto("$\\Delta t$ = 1 ms") is None and dd.erro_no_texto("R$ 5") is None
    assert dd.erro_no_texto("$\\naoexiste$") is not None
    pagina = _desenhar(_figura(nome_y="$\\naoexiste$", rotulo="$(a$)$",
                               tracos=(("t0", EstiloDoTraco(nome="$x^$")),)), {"v": _vista("v", TENSAO)})
    pagina.pixels()                                                    # não derruba o desenho
    ax = pagina.mpl.axes[0]
    assert ax.get_ylabel() == "\\$\\naoexiste\\$ (kV)" and ax.lines[0].get_label() == "\\$x^\\$"


# ------------------------------------------------------------------ a visão de cores

def test_a_visao_em_cinza_e_com_daltonismo():
    vermelho, verde, azul, branco = [255, 0, 0, 255], [0, 160, 0, 255], [0, 0, 255, 255], [255, 255, 255, 128]
    pagina = np.array([[vermelho, verde, azul, branco]], dtype=np.uint8)
    assert vc.simular(pagina, "normal") is pagina
    cinza = vc.simular(pagina, "cinza")
    assert np.all(cinza[..., 0] == cinza[..., 1]) and np.all(cinza[..., 1] == cinza[..., 2])
    assert cinza[0, :, 0].tolist() == [127, 137, 76, 255] and cinza[0, 3, 3] == 128          # a luminância, o alfa
    distancia = {v: float(np.abs(vc.simular(pagina, v)[0, 0, :3].astype(int)
                                 - vc.simular(pagina, v)[0, 1, :3].astype(int)).sum()) for v in vc.MATRIZES}
    normal = float(np.abs(pagina[0, 0, :3].astype(int) - pagina[0, 1, :3].astype(int)).sum())
    # O vermelho e o verde quase se confundem sem o vermelho ou o verde; sem o azul, ficam distintos.
    assert distancia["deuteranopia"] < normal / 3 and distancia["protanopia"] < normal / 3
    assert distancia["tritanopia"] > normal / 2
    assert vc.simular(pagina, "deuteranopia")[0, 3, :3].tolist() == [255, 255, 255]      # o branco fica
    with pytest.raises(ValueError, match="visão desconhecida"):
        vc.simular(pagina, "sépia")


# ------------------------------------------------------------------ o pacote

def test_o_pacote_refaz_o_estilo_com_os_mesmos_pixels(tmp_path, monkeypatch):
    import test_gui_pacote

    estilo = Estilo("IBM Plex Sans", legenda_pt=6.0, marcas_para_dentro=False, moldura=False, grade=True)
    figura = _figura(estilo, legenda="fora_acima", nome_x="$t$", prefixo_y=-3,
                     tracos=(("t0", EstiloDoTraco("#000000", 1.2, "--", "o", "$V_A$")),
                             ("t2", EstiloDoTraco(marcador="^"))))
    monkeypatch.setitem(test_gui_pacote.CASOS, "estilo", lambda: (figura, VISTAS, Dados(50_000)))
    _figura_, pasta, nomes = _empacotar(tmp_path, "estilo")
    assert any("/fontes/IBMPlexSans" in n for n in nomes)
    resultado = _refazer(pasta)
    assert resultado.returncode == 0, resultado.stderr
    assert "os mesmos pixels da figura.png" in resultado.stdout
    assert np.array_equal(_rgb(pasta / "figura.png"), _rgb(pasta / "figura_refeita.png"))
