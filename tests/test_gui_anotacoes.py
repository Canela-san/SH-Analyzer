"""Os insets e as anotações (F5.8; FG-03, AN-11), sem Qt: o modelo das anotações (o que ele recusa, a ida e a volta
pelo JSON e pelo projeto, o texto da cota), cada anotação no desenho da figura (na faixa dela, nas unidades do eixo,
fora dos limites escondida, a vista que sobrepõe), o inset (os limites, o y automático, a redução nas colunas dele,
as linhas de ligação, os pontos que ele soma) e o pacote reproduzível com um inset e as quatro anotações (os mesmos
pixels)."""

import json
from dataclasses import replace

import numpy as np
import pytest
from matplotlib.text import Annotation
from sh_analyzer_gui.dados import anotacoes as anot
from sh_analyzer_gui.dados import desenho_da_figura as dd
from sh_analyzer_gui.dados import projeto as arq
from sh_analyzer_gui.dados.anotacoes import Anotacao, AnotacaoInvalida
from sh_analyzer_gui.dados.espectros import Desenho, Marcas
from sh_analyzer_gui.dados.figura import Figura, Inset, Painel
from sh_analyzer_gui.dados.piramide import construir
from sh_analyzer_gui.dados.projeto import ProjetoSalvo
from test_gui_desenho_da_figura import CORRENTE, TENSAO, Dados, _vista
from test_gui_pacote import CASOS, _empacotar, _refazer, _rgb

QUATRO = (Anotacao("a", "texto", 0.05, 200.0, texto="Pico"),
          Anotacao("b", "seta", 0.1, 250.0, 0.2, 600.0, "$V_{max}$"),
          Anotacao("c", "regiao", 0.35, 0.0, 0.3, texto="Afundamento"),
          Anotacao("d", "cota", 0.1, -0.015, 0.1125, faixa=1))


def _com(*anotacoes, sobrepor=False):
    opcoes = {"sobrepor": True} if sobrepor else {}
    return {"v": replace(_vista("v", TENSAO, CORRENTE, **opcoes), anotacoes=anotacoes)}


def _figura(**painel) -> Figura:
    return Figura("f", "Anotada", "ieee_1", paineis=(Painel("p", vista="v", **painel),))


# ------------------------------------------------------------------ o modelo

def test_o_que_a_anotacao_recusa_e_a_ordem_das_pontas():
    assert Anotacao("r", "regiao", 2.0, 0.0, 1.0).x0 == 1.0                       # da esquerda para a direita
    assert Anotacao("s", "seta", 1.0, 2.0, 3.0).y1 == 2.0                          # sem y1: na mesma altura
    assert Anotacao("t", "texto", 0, 0).movida(1.0, 2.0) == Anotacao("t", "texto", 1.0, 2.0)
    for criar, mensagem in [(lambda: Anotacao("", "texto", 0), "sem id"),
                            (lambda: Anotacao("x", "círculo", 0), "tipo de anotação desconhecido"),
                            (lambda: Anotacao("x", "cota", 0), "precisa do x1"),
                            (lambda: Anotacao("x", "regiao", 1.0, 0.0, 1.0), "dois x diferentes"),
                            (lambda: Anotacao("x", "texto", 0, 0, 1.0), "só um ponto"),
                            (lambda: Anotacao("x", "regiao", 0, 0, 1, 2), "não tem y1"),
                            (lambda: Anotacao("x", "texto", float("nan")), "x0 inválido"),
                            (lambda: Anotacao("x", "texto", 0, faixa=-1), "faixa da anotação")]:
        with pytest.raises(AnotacaoInvalida, match=mensagem):
            criar()


def test_o_texto_da_cota():
    cota = Anotacao("d", "cota", 0.1, 0.0, 0.10125)
    assert anot.texto_da_cota(cota) == "Δt = 1,25 ms"
    assert anot.texto_da_cota(cota, separador=".", matematica=True) == "$\\Delta t$ = 1.25 ms"
    assert anot.texto_da_cota(Anotacao("f", "cota", 2000.0, 0.0, 11_000.0), frequencia=True) == "Δf = 9 kHz"
    assert anot.texto_da_cota(cota.com(texto="meio ciclo")) == "meio ciclo"


def test_as_anotacoes_vao_e_voltam_pelo_projeto():
    from test_gui_projeto import exemplo

    p = exemplo()
    vista = replace(p.vistas[0], anotacoes=QUATRO)
    p = ProjetoSalvo(p.fontes, (vista, *p.vistas[1:]), p.layout, p.versao_do_aplicativo, p.modelos_de_captura)
    dados = json.loads(json.dumps(arq.para_dict(p)))
    assert dados["versao"] == 6 and dados["vistas"][0]["anotacoes"][3] == {
        "id": "d", "tipo": "cota", "x0": 0.1, "y0": -0.015, "x1": 0.1125, "faixa": 1}
    assert arq.de_dict(dados) == p
    dados["vistas"][0]["anotacoes"].append(dict(dados["vistas"][0]["anotacoes"][0]))
    with pytest.raises(arq.ProjetoInvalido, match="duas anotações com o mesmo id"):
        arq.de_dict(dados)
    dados["vistas"][0]["anotacoes"] = [{"id": "z", "tipo": "texto", "x0": 0, "cor": "azul"}]
    with pytest.raises(arq.ProjetoInvalido, match="campos desconhecidos: cor"):
        arq.de_dict(dados)


# ------------------------------------------------------------------ o desenho

def test_cada_anotacao_na_faixa_dela_e_nas_unidades_do_eixo():
    pagina = dd.desenhar(_figura(), _com(*QUATRO), Dados(200_000), dpi=100)
    pagina.pixels()
    tensao, corrente = pagina.mpl.axes
    assert tensao.get_ylabel() == "Tensão (kV)" and corrente.get_ylabel() == "Corrente (mA)"
    textos = {t.get_text(): t for t in tensao.texts}
    assert set(textos) == {"Pico", "$V_{max}$", "Afundamento"}
    pico = textos["Pico"]
    assert isinstance(pico, Annotation) and pico.xy == pytest.approx((50.0, 0.2))            # ms e kV
    seta = textos["$V_{max}$"]
    assert seta.xy == pytest.approx((100.0, 0.25)) and seta.xyann == pytest.approx((200.0, 0.6))
    assert seta.arrowprops["arrowstyle"] == "-|>"
    (regiao,) = tensao.patches
    assert (regiao.get_x(), regiao.get_x() + regiao.get_width()) == pytest.approx((300.0, 350.0))
    # A cota na faixa da corrente: a linha com as duas pontas e o Δt em cima, em mA.
    linha, rotulo = corrente.texts
    assert linha.arrowprops["arrowstyle"] == "<|-|>" and linha.xy == pytest.approx((100.0, -15.0))
    assert rotulo.get_text() == "$\\Delta t$ = 12,5 ms" and rotulo.xy == pytest.approx((106.25, -15.0))


def test_a_anotacao_fora_dos_limites_e_a_vista_que_sobrepoe():
    fora = Anotacao("z", "texto", 5.0, 0.0, texto="longe")                         # depois do fim da janela
    com_ela = dd.desenhar(_figura(), _com(fora, *QUATRO), Dados(200_000), dpi=100)
    assert "longe" in [t.get_text() for t in com_ela.mpl.axes[0].texts]
    sem_ela = dd.desenhar(_figura(), _com(*QUATRO), Dados(200_000), dpi=100)
    assert np.array_equal(com_ela.pixels(), sem_ela.pixels())                       # não aparece
    # Sobrepondo, a vista tem um eixo só, e todas as anotações vão nele.
    (eixo,) = dd.desenhar(_figura(), _com(*QUATRO, sobrepor=True), Dados(200_000), dpi=100).mpl.axes
    assert len(eixo.texts) == 5 and len(eixo.patches) == 1
    # Uma faixa que a vista não tem mais: a anotação fica de fora (e volta com a faixa).
    pagina = dd.desenhar(_figura(), _com(replace(QUATRO[0], faixa=7)), Dados(200_000), dpi=100)
    assert all(not ax.texts for ax in pagina.mpl.axes)


def test_o_inset_amplia_o_trecho_com_a_reducao_nas_colunas_dele():
    inset = Inset((0.2, 0.21), faixa=1, canto="inf_esq", tamanho=0.5)
    pagina = dd.desenhar(_figura(inset=inset), _com(), Dados(200_000), dpi=200)
    tensao, corrente = pagina.mpl.axes
    assert not tensao.child_axes
    (dentro,) = corrente.child_axes
    assert dentro.get_xlim() == pytest.approx((200.0, 210.0))
    x, y = dentro.lines[0].get_data()
    largura = dentro.get_window_extent().width
    assert 200.0 - 0.01 <= x.min() and x.max() <= 210.01 and len(x) <= 4 * 2 * (largura + 2)
    # O y automático: os extremos do trecho, com folga; as linhas de ligação saem do retângulo do trecho.
    serie = Dados(200_000).tempo(None, CORRENTE)
    trecho = serie.amostras[80_000:84_001] * serie.escala * 1000
    assert dentro.get_ylim()[0] < trecho.min() and dentro.get_ylim()[1] > trecho.max()
    assert dentro.get_ylim()[1] - dentro.get_ylim()[0] < 1.1 * (trecho.max() - trecho.min())
    (ligacoes,) = corrente.artists
    assert ligacoes.rectangle.get_bbox().bounds[:3] == pytest.approx((200.0, dentro.get_ylim()[0], 10.0))
    assert len(pagina.curvas) == 3
    # "Todos os pontos" conta os do inset também.
    assert dd.pontos(_figura(inset=inset), _com(), Dados(200_000)) == 2 * 200_000 + 4001
    # O y fixo; sem as ligações; o inset do espectro, em log.
    pagina = dd.desenhar(_figura(inset=replace(inset, limites_y=(-5e-3, 5e-3), ligacoes=False)), _com(),
                         Dados(200_000), dpi=100)
    (dentro,) = pagina.mpl.axes[1].child_axes
    assert dentro.get_ylim() == pytest.approx((-5.0, 5.0)) and not pagina.mpl.axes[1].artists


def test_o_inset_do_espectro_em_log():
    rng = np.random.default_rng(5)
    niveis = -100 + 5 * rng.standard_normal(40_001)
    niveis[9000] = 0.0
    desenho = Desenho(niveis, construir(niveis)[0], Marcas((), float("nan"), ()), 0.0, 5.0)
    vistas = {"e": replace(_vista("e", TENSAO, tipo="espectro", frequencia_log=True),
                           anotacoes=(Anotacao("c", "cota", 40_000.0, -20.0, 50_000.0),))}
    figura = Figura("f", "E", "ieee_1", paineis=(Painel("p", vista="e", inset=Inset((44_000.0, 46_000.0))),))
    pagina = dd.desenhar(figura, vistas, Dados(1000, espectro=desenho), dpi=100)
    (ax,) = pagina.mpl.axes
    (dentro,) = ax.child_axes
    assert dentro.get_xscale() == "log" and dentro.get_xlim() == pytest.approx((44.0, 46.0))     # kHz
    assert dentro.get_ylim()[1] > 0.0 > dentro.get_ylim()[0] > -130          # o pico de 0 dB e o ruído
    assert [t.get_text() for t in ax.texts] == ["", "$\\Delta f$ = 10 kHz"]


# ------------------------------------------------------------------ o pacote

def test_o_pacote_com_um_inset_e_as_quatro_anotacoes(tmp_path, monkeypatch):
    figura = _figura(inset=Inset((0.2, 0.21), faixa=1), legenda="sup_esq")
    monkeypatch.setitem(CASOS, "anotada", lambda: (figura, _com(*QUATRO), Dados(100_000)))
    _figura_, pasta, _nomes = _empacotar(tmp_path, "anotada")
    resultado = _refazer(pasta)
    assert resultado.returncode == 0, resultado.stderr
    assert "os mesmos pixels da figura.png" in resultado.stdout
    assert np.array_equal(_rgb(pasta / "figura.png"), _rgb(pasta / "figura_refeita.png"))
    import h5py

    with h5py.File(pasta / "dados.h5") as f5:
        corrente = json.loads(f5["eixos/01"].attrs["eixo"])
        inset = json.loads(f5["eixos/01/insets/00"].attrs["eixo"])
        assert len(f5["eixos/01/insets/00/linhas"]) == 1 and inset["ligacoes"]["linewidth"] > 0
        assert [t["tipo"] for t in corrente["textos"]] == ["anotacao", "anotacao"]
        tensao = json.loads(f5["eixos/00"].attrs["eixo"])
        assert tensao["faixas"][0]["x0"] == pytest.approx(300.0)
