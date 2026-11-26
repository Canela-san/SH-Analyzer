"""O desenho da figura (``sh_analyzer_gui.dados.desenho_da_figura``, F5.2), sem Qt: o M4 e os extremos exatos contra
as contas diretas, a fidelidade (a curva reduzida contra a de todos os pontos, pixel a pixel), a página no tamanho do
modelo, as faixas da vista de tempo com o tempo compartilhado, o prefixo do SI e o separador do idioma, o espectro, os
painéis sem desenho e as fontes do aplicativo."""

from dataclasses import replace

import numpy as np
import pytest
from scipy import ndimage
from sh_analyzer_gui.dados import desenho_da_figura as dd
from sh_analyzer_gui.dados import figura as fig
from sh_analyzer_gui.dados.espectros import Desenho, Marcas
from sh_analyzer_gui.dados.figura import Estilo, Figura, Painel
from sh_analyzer_gui.dados.piramide import construir
from sh_analyzer_gui.dados.projeto import TracoSalvo, VistaSalva
from sh_analyzer_gui.dados.receita import ReceitaDoTraco
from sh_analyzer_gui.dados.unidades import CATALOGO

TAXA = 400_000.0
AZUL, LARANJA = "#1f5fa8", "#c4501b"


def _rede(n: int, semente: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """A tensão e a corrente em códigos do ADC: 60 Hz com ruído, a tensão com 9 kHz e 40 impulsos de uma amostra."""
    rng = np.random.default_rng(semente)
    t = np.arange(n) / TAXA
    v = 3000 * np.sin(2 * np.pi * 60 * t) + 100 * np.sin(2 * np.pi * 9000 * t) + 60 * rng.standard_normal(n)
    v[rng.integers(0, n, 40)] = 32_000
    i = 2000 * np.sin(2 * np.pi * 60 * t - 0.5) + 80 * rng.standard_normal(n)
    return v.astype(np.int16), i.astype(np.int16)


class Dados:
    """O que a área Figuras dá ao desenho, com vetores: o canal 0 é a tensão (V), o 1 a corrente (A)."""

    def __init__(self, n: int = 200_000, janela=None, espectro: Desenho | None = None):
        self.canais = _rede(n)
        self.piramides = [construir(c)[0] for c in self.canais]
        self._janela, self._espectro = janela, espectro

    def tempo(self, vista, receita):
        k = receita.canal
        unidade, escala, cor = ("V", 0.1, AZUL) if k == 0 else ("A", 1e-5, LARANJA)
        return dd.SerieDoTempo(self.piramides[k], self.canais[k], TAXA, receita.nome, cor, unidade, escala=escala)

    def espectros(self, vista):
        log = vista.opcoes.get("frequencia_log", False)
        return [dd.SerieDoEspectro(self._espectro, "V", AZUL, "dBV", frequencia_log=log)] if self._espectro else []

    def janela(self, vista):
        return self._janela


TENSAO, CORRENTE = ReceitaDoTraco("f1", 0, "V_A", 0), ReceitaDoTraco("f1", 1, "I_A", 1, faixa=1)


def _vista(id_, *receitas, tipo="tempo", **opcoes) -> VistaSalva:
    return VistaSalva(id_, id_, tipo, tuple(TracoSalvo(f"t{k}", r) for k, r in enumerate(receitas)), opcoes)


def _tinta(pixels: np.ndarray) -> np.ndarray:
    return np.any(pixels[..., :3] != 255, axis=2)


# ------------------------------------------------------------------ as contas

def test_o_m4_de_cada_coluna():
    valores = np.array([5, 1, 9, 3, 3, 7, 0, 0, 8, 2, 6], dtype=np.int16)
    posicoes, saida = dd.m4(valores, [0, 5, 6, 11])
    # [5 1 9 3 3]: a primeira, a mínima, a máxima, a última; [7]: uma só; [0 0 8 2 6]: a mínima é a primeira.
    assert posicoes.tolist() == [0, 1, 2, 4, 5, 6, 8, 10]
    assert saida.tolist() == valores[[0, 1, 2, 4, 5, 6, 8, 10]].tolist()
    # Os NaN não contam; uma coluna só de NaN sai com a primeira e a última.
    com_nan = np.array([np.nan, 2.0, -1.0, np.nan, np.nan, np.nan])
    posicoes, _ = dd.m4(com_nan, [0, 4, 6])
    assert posicoes.tolist() == [0, 1, 2, 3, 4, 5]


def test_o_m4_em_lotes_e_a_envoltoria_da_piramide(monkeypatch):
    """A redução exata lida em lotes dá o mesmo que de uma vez; a da pirâmide (a prévia) acha os mesmos extremos
    quando as colunas caem em blocos dela."""
    v, _ = _rede(100_000)
    bordas = np.arange(0, 100_001, 1024)
    inteiro = dd.m4(v, bordas)
    monkeypatch.setattr(dd, "LOTE_DO_M4", 3000)
    em_lotes = dd.m4(v, bordas)
    assert all(np.array_equal(a, b) for a, b in zip(inteiro, em_lotes, strict=True))
    _posicoes, saida = dd.m4(v, bordas, piramide=construir(v)[0])
    colunas = saida.reshape(-1, 4)
    blocos = v[:len(bordas[:-1]) * 1024].reshape(-1, 1024)
    assert np.array_equal(colunas[:, 1], blocos.min(axis=1)) and np.array_equal(colunas[:, 2], blocos.max(axis=1))


def test_os_extremos_exatos_pela_piramide():
    rng = np.random.default_rng(3)
    valores = rng.standard_normal(70_001)
    valores[rng.integers(0, len(valores), 500)] = np.nan
    piramide = construir(valores)[0]
    for i0, i1 in [(0, 70_001), (5, 6), (31, 33), (1000, 1000), (12_345, 67_890), (69_000, 70_001)]:
        trecho = valores[i0:i1]
        esperado = (np.nanmin(trecho), np.nanmax(trecho)) if np.isfinite(trecho).any() else None
        assert dd.extremos(piramide, valores, i0, i1) == esperado


# ------------------------------------------------------------------ a fidelidade

def test_a_curva_reduzida_pinta_o_que_todos_os_pontos_pintam():
    """O "pronto quando" da F5.2 (docs/gui-plan.md, 10.3): sem o antisserrilhado, o M4 nas colunas dos pixels e a
    curva de todos os pontos (500 mil) pintam a mesma tinta a menos da borda do traço: a distância de Hausdorff entre
    as duas é de 1 pixel (nenhum dos 40 impulsos de uma amostra some, nada aparece), e menos de 6 % dos pixels de
    tinta mudam (~5 % medidos; um traço deslocado de um pixel mudaria a metade). A prévia (a envoltória da pirâmide,
    com a mínima e a máxima no meio da coluna) fica a 1 pixel também, com menos de 12 % (~9 %). O M4 desenha no
    máximo 4 pontos por coluna.

    Por que não a tinta idêntica: o M4 é exato para a linha de 1 pixel, em que a coluna só depende dos 4 pontos; no
    traço de 0,75 pt (1,6 px a 150 dpi), a borda depende da posição de cada ponto dentro do meio pixel da coluna."""
    dados = Dados(500_000)
    f = fig.nova("f", "Fidelidade", "ieee_1", vista="v")
    vistas = {"v": _vista("v", TENSAO)}
    todos = _tinta(dd.desenhar(f, vistas, dados, dpi=150, suavizar=False, todos_os_pontos=True).pixels())
    longe_de_todos = ndimage.distance_transform_edt(~todos)
    for exato, limite in ((True, 0.06), (False, 0.12)):
        pagina = dd.desenhar(f, vistas, dados, dpi=150, suavizar=False, exato=exato)
        reduzida = _tinta(pagina.pixels())
        assert longe_de_todos[reduzida].max() <= 1.0
        assert ndimage.distance_transform_edt(~reduzida)[todos].max() <= 1.0
        assert (todos ^ reduzida).sum() < limite * todos.sum()
        (eixo,) = pagina.mpl.axes
        (linha,) = eixo.get_lines()
        largura = eixo.get_window_extent().width
        assert len(linha.get_xdata()) <= 4 * dd.COLUNAS_POR_PIXEL * (largura + 2)


def test_a_pagina_tem_o_tamanho_do_modelo():
    f = fig.nova("f", "F", "elsevier_15", vista="v")
    pixels = dd.desenhar(f, {"v": _vista("v", TENSAO)}, Dados(20_000), dpi=100).pixels()
    assert pixels.shape == (round(f.altura_mm / 25.4 * 100), round(140.0 / 25.4 * 100), 4)


# ------------------------------------------------------------------ o que sai na página

def _textos_das_marcas(eixo) -> list[str]:
    return [t.get_text() for t in eixo.get_yticklabels() + eixo.get_xticklabels() if t.get_text()]


@pytest.mark.parametrize(("idioma", "separador", "tensao", "corrente", "tempo"), [
    ("pt-BR", ",", "Tensão (V)", "Corrente (mA)", "Tempo (ms)"),
    ("en", ".", "Voltage (V)", "Current (mA)", "Time (ms)")])
def test_as_faixas_o_tempo_compartilhado_e_o_idioma(idioma, separador, tensao, corrente, tempo):
    """Dois painéis com o x compartilhado: a vista com duas faixas vira dois eixos (a tensão em cima, a corrente em
    mA embaixo), a que sobrepõe vira um, com a legenda; o tempo (em ms, a janela da vista) só no de baixo; os números
    com o separador do idioma e o menos tipográfico."""
    dados = Dados(200_000, janela=(0.0, 0.0035))
    f = Figura("f", "F", "ieee_1", altura_mm=100.0, linhas=2, idioma=idioma, eixos_x_compartilhados=True, paineis=(
        Painel("a", 0, 0, vista="faixas"), Painel("b", 1, 0, vista="junto")))
    vistas = {"faixas": _vista("faixas", TENSAO, CORRENTE),
              "junto": _vista("junto", TENSAO, replace(CORRENTE, canal=0, nome="V_B"), sobrepor=True)}
    pagina = dd.desenhar(f, vistas, dados, dpi=100)
    pagina.pixels()
    v, i, junto = pagina.mpl.axes
    assert (v.get_ylabel(), i.get_ylabel(), junto.get_ylabel()) == (tensao, corrente, tensao)
    assert (v.get_title(loc="left"), junto.get_title(loc="left")) == ("(a)", "(b)")
    assert (v.get_xlabel(), i.get_xlabel(), junto.get_xlabel()) == ("", "", tempo)
    assert v.get_xlim() == i.get_xlim() == junto.get_xlim() == (0.0, 3.5)
    assert not any(t.get_text() for t in v.get_xticklabels() + i.get_xticklabels())
    assert v.get_legend() is None and [t.get_text() for t in junto.get_legend().get_texts()] == ["V_A", "V_B"]
    marcas = _textos_das_marcas(i) + _textos_das_marcas(junto)
    assert any(separador in m for m in marcas) and not any({",", "."} - {separador} & set(m) for m in marcas)
    assert any(m.startswith("−") for m in marcas) and not any("-" in m for m in marcas)
    # Os limites do y: os extremos exatos da janela, com 4 % de folga.
    trecho = dados.canais[1][:1401] * 1e-5 * 1e3
    folga = 0.04 * (trecho.max() - trecho.min())
    assert i.get_ylim() == pytest.approx((trecho.min() - folga, trecho.max() + folga))


def test_o_y_compartilhado_e_os_limites_do_painel():
    dados = Dados(100_000)
    f = Figura("f", "F", "ieee_2", colunas=2, eixos_y_compartilhados=True, paineis=(
        Painel("a", 0, 0, vista="v", limites_x=(0.0, 0.01), limites_y=(-400.0, 400.0)),
        Painel("b", 0, 1, vista="v", limites_x=(0.1, 0.2))))
    pagina = dd.desenhar(f, {"v": _vista("v", TENSAO)}, dados, dpi=80)
    a, b = pagina.mpl.axes
    # A união dos dois: os ±400 V do (a) e os impulsos de 3,2 kV do (b).
    assert a.get_ylim() == b.get_ylim() and a.get_ylim()[0] <= -0.4 and a.get_ylim()[1] >= 3.2
    assert (a.get_ylabel(), b.get_ylabel()) == ("Tensão (kV)", "")
    assert (a.get_xlim(), b.get_xlim()) == ((0.0, 10.0), pytest.approx((100.0, 200.0)))


@pytest.mark.parametrize("log", [False, True])
def test_o_espectro(log):
    rng = np.random.default_rng(5)
    niveis = -100 + 5 * rng.standard_normal(40_001)
    niveis[60], niveis[9000], niveis[0] = 40.0, 0.0, -np.inf
    desenho = Desenho(niveis, construir(niveis)[0], Marcas((), float("nan"), ()), 0.0, 5.0)
    f = replace(fig.nova("f", "F", "ieee_1", vista="e"), idioma="en")
    vista = _vista("e", TENSAO, tipo="espectro", frequencia_log=log)
    pagina = dd.desenhar(f, {"e": vista}, Dados(1000, espectro=desenho), dpi=100)
    pagina.pixels()
    (eixo,) = pagina.mpl.axes
    assert (eixo.get_xlabel(), eixo.get_ylabel()) == ("Frequency (kHz)", "Level (dBV)")
    assert eixo.get_xscale() == ("log" if log else "linear")
    assert eixo.get_xlim() == pytest.approx((0.005 if log else 0.0, 200.0))
    (linha,) = eixo.get_lines()
    x, y = linha.get_data()
    assert y.max() == 40.0 and x[np.argmax(y)] == pytest.approx(0.3)      # o pico de um bin, em 300 Hz
    assert 0.0 in y                                                        # e o de 45 kHz
    assert eixo.get_ylim()[0] < niveis[1:].min() and eixo.get_ylim()[1] > 40.0


class DadosMistos(Dados):
    """A tensão (dBV) e a corrente (dBA) no mesmo espectro."""

    def __init__(self, tensao: Desenho, corrente: Desenho):
        super().__init__(1000)
        self._series = (tensao, corrente)

    def espectros(self, vista):
        log = vista.opcoes.get("frequencia_log", False)
        return [dd.SerieDoEspectro(self._series[0], "V", AZUL, "dBV", frequencia_log=log, traco="t0"),
                dd.SerieDoEspectro(self._series[1], "I", LARANJA, "dBA", frequencia_log=log, traco="t1")]


@pytest.mark.parametrize("log", [False, True])
def test_o_espectro_com_grandezas_diferentes_tem_um_eixo_para_cada(log):
    """A tensão e a corrente nunca dividem o eixo: a corrente vai para o da direita, com o rótulo e a escala dela
    (antes, o painel inteiro saía em dBV, com a corrente desenhada nele)."""
    niveis_v = np.full(2001, -80.0)
    niveis_v[12] = 40.0
    niveis_i = np.full(2001, -140.0)
    niveis_i[12] = -20.0
    desenho = (Desenho(niveis_v, construir(niveis_v)[0], Marcas((), float("nan"), ()), 0.0, 5.0),
               Desenho(niveis_i, construir(niveis_i)[0], Marcas((), float("nan"), ()), 0.0, 5.0))
    f = replace(fig.nova("f", "F", "ieee_1", vista="e"), idioma="en")
    vista = _vista("e", TENSAO, CORRENTE, tipo="espectro", frequencia_log=log)
    pagina = dd.desenhar(f, {"e": vista}, DadosMistos(*desenho), dpi=100)
    pagina.pixels()
    esquerdo, direito = pagina.mpl.axes
    assert (esquerdo.get_ylabel(), direito.get_ylabel()) == ("Level (dBV)", "Level (dBA)")
    assert esquerdo.get_ylim()[1] > 40.0 > -80.0 > esquerdo.get_ylim()[0]
    assert direito.get_ylim()[1] > -20.0 > -140.0 > direito.get_ylim()[0] and direito.get_ylim()[1] < 40.0
    assert len(esquerdo.get_lines()) == 1 and len(direito.get_lines()) == 1
    assert esquerdo.get_xscale() == ("log" if log else "linear")
    assert len(esquerdo.get_legend().get_texts()) == 2


def test_os_paineis_sem_desenho():
    f = Figura("f", "F", "ieee_2", colunas=3, paineis=(
        Painel("a", 0, 0, vista="b"), Painel("b", 0, 1), Painel("c", 0, 2, vista="v")))
    vistas = {"b": _vista("b", TENSAO, tipo="bandas"), "v": _vista("v", replace(TENSAO, visivel=False))}
    pagina = dd.desenhar(f, vistas, Dados(1000), dpi=60)
    avisos = [[t.get_text() for t in eixo.texts] for eixo in pagina.mpl.axes]
    assert avisos == [["Este tipo de vista entra nas figuras depois"], ["Painel vazio"], ["Sem dados"]]


def test_o_painel_congelado_usa_a_copia():
    """O painel congelado desenha a cópia guardada, e não a vista do projeto (que pode ter mudado ou sumido)."""
    copia = _vista("v", TENSAO, CORRENTE)
    f = Figura("f", "F", paineis=(Painel("a", vista="v", congelado=copia),))
    pagina = dd.desenhar(f, {}, Dados(1000), dpi=60)
    assert [e.get_ylabel() for e in pagina.mpl.axes] == ["Tensão (kV)", "Corrente (mA)"]       # a captura inteira: os impulsos


def test_as_fontes_e_as_grandezas_em_ingles():
    assert {u.grandeza for u in CATALOGO} <= set(dd.GRANDEZAS_EM_INGLES)
    for familia in fig.FAMILIAS:
        f = replace(fig.nova("f", "F", "ieee_1", vista="v"), estilo=Estilo(familia, texto_pt=9))
        pagina = dd.desenhar(f, {"v": _vista("v", TENSAO)}, Dados(1000), dpi=60)
        rotulo = pagina.mpl.axes[0].yaxis.label
        assert rotulo.get_fontname() == dd.FAMILIAS_DO_MATPLOTLIB[familia][0] and rotulo.get_fontsize() == 9


def test_os_dados_colhidos_desenham_a_mesma_pagina():
    """A área colhe na thread da interface e desenha noutra: os dados colhidos dão a mesma página que os de origem.
    O painel congelado não pergunta a janela à vista (mostra a cópia inteira, ou os limites dele), e a caixa de cada
    painel cai dentro da página."""
    class Contando(Dados):
        janelas = 0

        def janela(self, vista):
            Contando.janelas += 1
            return super().janela(vista)

    dados = Contando(50_000, janela=(0.0, 0.02))
    vista = _vista("v", TENSAO, CORRENTE)
    f = Figura("f", "F", "ieee_1", altura_mm=120.0, linhas=2, paineis=(
        Painel("a", 0, 0, vista="v"), Painel("b", 1, 0, vista="v", congelado=vista)))
    vistas = {"v": vista}
    direto = dd.desenhar(f, vistas, dados, dpi=80)
    colhidos = dd.colher(f, vistas, dados)
    assert Contando.janelas == 2                                  # o painel ligado, na página e na colheita
    pelos_colhidos = dd.desenhar(f, vistas, colhidos, dpi=80)
    assert np.array_equal(direto.pixels(), pelos_colhidos.pixels())
    a, b = direto.mpl.axes[0], direto.mpl.axes[2]
    assert a.get_xlim() == (0.0, 20.0) and b.get_xlim()[1] == pytest.approx(49_999 / TAXA * 1e3)
    altura, largura = direto.pixels().shape[:2]
    for x0, y0, x1, y1 in direto.paineis.values():
        assert 0 <= x0 < x1 <= largura and 0 <= y0 < y1 <= altura
    assert direto.paineis["a"][3] <= direto.paineis["b"][1] + 1   # (a) em cima de (b)


def test_a_grandeza_do_canal_no_rotulo():
    """Uma unidade fora do catálogo ("u.a.") com a grandeza do canal: o rótulo usa a grandeza."""
    class ComGrandeza(Dados):
        def tempo(self, vista, receita):
            s = super().tempo(vista, receita)
            return dd.SerieDoTempo(s.piramide, s.amostras, s.taxa_hz, s.nome, s.cor, "u.a.", escala=1e-3,
                                   grandeza="vibração")

    f = fig.nova("f", "F", vista="v")
    dados = ComGrandeza(1000, janela=(0.0, 0.001))                 # sem os impulsos: até ~3,3 u.a.
    pagina = dd.desenhar(f, {"v": _vista("v", TENSAO)}, dados, dpi=60)
    assert pagina.mpl.axes[0].get_ylabel() == "Vibração (u.a.)"
    en = dd.desenhar(replace(f, idioma="en"), {"v": _vista("v", TENSAO)}, dados, dpi=60)
    assert en.mpl.axes[0].get_ylabel() == "vibração (u.a.)"        # fora do catálogo: como o canal a escreve


def test_um_desenho_por_vez_com_o_estilo_dele():
    """O ``rcParams`` é global: com o ``no_estilo``, o estilo de uma tarefa nunca muda o de outra no meio do desenho
    (a figura do pacote reproduzível que saía diferente numa CI carregada)."""
    import threading
    import time

    import matplotlib

    vistos, dentro = [], threading.Event()

    def primeira():
        with dd.no_estilo({"font.size": 3.0}):
            dentro.set()
            for _ in range(5):
                vistos.append(matplotlib.rcParams["font.size"])
                time.sleep(0.01)

    def segunda():
        dentro.wait()
        with dd.no_estilo({"font.size": 20.0}):
            vistos.append(("segunda", matplotlib.rcParams["font.size"]))

    linhas = [threading.Thread(target=primeira), threading.Thread(target=segunda)]
    for linha in linhas:
        linha.start()
    for linha in linhas:
        linha.join(5)
    assert vistos == [3.0] * 5 + [("segunda", 20.0)]
    with dd.no_estilo({"font.size": 7.0}), dd.no_estilo({"font.size": 8.0}):     # reentrante
        assert matplotlib.rcParams["font.size"] == 8.0
