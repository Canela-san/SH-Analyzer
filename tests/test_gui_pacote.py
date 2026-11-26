"""O pacote reproduzível da figura (``sh_analyzer_gui.dados.pacote``, F5.6), sem Qt: o ``.zip`` com a figura, a
``figura.png`` de referência, o ``dados.h5``, o ``refazer_figura.py``, as fontes, a proveniência e o LEIA-ME; o
script rodando **num processo sem o SH-Analyzer** (``-I`` e os pacotes dele bloqueados) refaz a figura com os mesmos
pixels, nas figuras de tempo (as faixas, a legenda), de espectro (o eixo em log), com painéis sem desenho e com uma
fonte do aplicativo; a recusa do que a descrição não conhece; o cancelar sem arquivo pela metade."""

import json
import subprocess
import sys
import zipfile
from dataclasses import replace

import h5py
import numpy as np
import pytest
from PIL import Image
from sh_analyzer_gui.dados import desenho_da_figura as dd
from sh_analyzer_gui.dados import figura as fig
from sh_analyzer_gui.dados import pacote
from sh_analyzer_gui.dados.espectros import Desenho, Marcas
from sh_analyzer_gui.dados.exportar_figura import OpcoesDeExportacao
from sh_analyzer_gui.dados.figura import Estilo, Figura, Painel
from sh_analyzer_gui.dados.piramide import construir
from supraharmonicos.api import Cancelado
from test_gui_desenho_da_figura import CORRENTE, TENSAO, Dados, DadosMistos, _vista
from test_gui_exportar_figura import FIGURA, PROVENIENCIA, VISTAS

SEM_O_APLICATIVO = ("import runpy, sys; sys.modules.update(dict.fromkeys(['sh_analyzer_gui', 'supraharmonicos'])); "
                    "sys.argv = ['refazer_figura.py', *sys.argv[1:]]; runpy.run_path('refazer_figura.py', "
                    "run_name='__main__')")


def _espectro(log: bool):
    rng = np.random.default_rng(5)
    niveis = -100 + 5 * rng.standard_normal(40_001)
    niveis[60], niveis[9000] = 40.0, 0.0
    desenho = Desenho(niveis, construir(niveis)[0], Marcas((), float("nan"), ()), 0.0, 5.0)
    f = replace(fig.nova("f", "Espectro", "ieee_1", vista="e"), idioma="en")
    return f, {"e": _vista("e", TENSAO, tipo="espectro", frequencia_log=log)}, Dados(1000, espectro=desenho)


def _espectro_misto():
    """A tensão (dBV) e a corrente (dBA): a corrente no eixo da direita (o ``twinx``)."""
    niveis_v, niveis_i = np.full(2001, -80.0), np.full(2001, -140.0)
    niveis_v[12], niveis_i[30] = 40.0, -20.0
    desenhos = [Desenho(n, construir(n)[0], Marcas((), float("nan"), ()), 0.0, 5.0) for n in (niveis_v, niveis_i)]
    f = replace(fig.nova("f", "Misto", "ieee_1", vista="e"), idioma="en")
    return f, {"e": _vista("e", TENSAO, CORRENTE, tipo="espectro")}, DadosMistos(*desenhos)


CASOS = {
    "tempo": lambda: (FIGURA, VISTAS, Dados(200_000)),
    "legenda": lambda: (Figura("f", "Legenda", "ieee_1", paineis=(Painel("a", vista="v"),)),
                        {"v": _vista("v", TENSAO, replace(TENSAO, nome="V_B", cor=2))}, Dados(50_000)),
    "espectro_em_log": lambda: _espectro(True),
    "espectro_com_duas_grandezas": _espectro_misto,
    "paineis_sem_desenho_e_inter": lambda: (
        Figura("f", "Grade", "ieee_2", colunas=3, estilo=Estilo("Inter"), paineis=(
            Painel("a", 0, 0, vista="b"), Painel("b", 0, 1), Painel("c", 0, 2, vista="v"))),
        {"b": _vista("b", TENSAO, tipo="bandas"), "v": _vista("v", TENSAO, CORRENTE)}, Dados(20_000)),
}


def _empacotar(tmp_path, caso, formato="pdf", **kw):
    figura, vistas, dados = CASOS[caso]()
    destino = tmp_path / f"{figura.nome}.zip"
    pacote.empacotar(figura, vistas, dados, destino, OpcoesDeExportacao(formato, **kw), proveniencia=PROVENIENCIA,
                     aplicativo="0.8.0")
    assert not list(tmp_path.glob("*.parcial"))
    with zipfile.ZipFile(destino) as z:
        nomes = z.namelist()
        z.extractall(tmp_path / "aberto")
    return figura, tmp_path / "aberto" / figura.nome, nomes


def _refazer(pasta, *argumentos):
    """O script num processo isolado (``-I``), com o SH-Analyzer bloqueado: um ``import`` dele falharia."""
    return subprocess.run([sys.executable, "-I", "-c", SEM_O_APLICATIVO, *argumentos], cwd=pasta,
                          capture_output=True, text=True, timeout=120)


def _rgb(caminho):
    return np.asarray(Image.open(caminho).convert("RGB"))


@pytest.mark.parametrize("caso", list(CASOS))
def test_o_script_refaz_a_figura_com_os_mesmos_pixels(tmp_path, caso):
    figura, pasta, nomes = _empacotar(tmp_path, caso)
    base = {f"{figura.nome}/{n}" for n in ("figura.pdf", "figura.png", "dados.h5", "refazer_figura.py",
                                           "proveniencia.json", "LEIA-ME.md")}
    assert base <= set(nomes)
    resultado = _refazer(pasta)
    assert resultado.returncode == 0, resultado.stderr
    assert "os mesmos pixels da figura.png" in resultado.stdout
    original, refeita = _rgb(pasta / "figura.png"), _rgb(pasta / "figura_refeita.png")
    assert original.shape == refeita.shape and np.array_equal(original, refeita)
    assert np.count_nonzero(original.min(axis=-1) < 128) > 1000          # a figura tem o que comparar


def test_o_conteudo_do_pacote(tmp_path):
    figura, pasta, nomes = _empacotar(tmp_path, "tempo", dpi=300)
    assert all(n.startswith(f"{figura.nome}/") for n in nomes)
    assert not any("/fontes/" in n for n in nomes)                         # a STIX vem com o Matplotlib
    assert json.loads((pasta / "proveniencia.json").read_text(encoding="utf-8")) == PROVENIENCIA
    leia = (pasta / "LEIA-ME.md").read_text(encoding="utf-8")
    assert "python refazer_figura.py" in leia and "300 dpi" in leia and "## English" in leia
    imagem = Image.open(pasta / "figura.png")
    assert imagem.info["dpi"] == pytest.approx((300, 300), abs=0.05)
    with h5py.File(pasta / "dados.h5") as f5:
        assert f5.attrs["formato"] == pacote.FORMATO and f5.attrs["dpi"] == 300
        assert len(f5["eixos"]) == 3                                        # (a) com as duas faixas, e (b)
        tensao = f5["eixos/00/linhas/00"]
        assert tensao.attrs["rotulo"] == "V_A" and f5["eixos/00"].attrs["rotulo_y"] == "Tensão (kV)"
        x = tensao["x"][:]
        assert np.all(np.diff(x) >= 0) and 100 < len(x) < 4 * 2 * 1100       # o M4: até 4 pontos por coluna
        assert json.loads(f5["eixos/00"].attrs["eixo"])["legenda"] is None       # um traço por faixa


def test_a_legenda_no_lugar_que_o_desenho_achou(tmp_path):
    _figura, pasta, _nomes = _empacotar(tmp_path, "legenda")
    with h5py.File(pasta / "dados.h5") as f5:
        legenda = json.loads(f5["eixos/00"].attrs["eixo"])["legenda"]
    assert legenda["textos"] == ["V_A", "V_B"] and legenda["linhas"] == [[0, 0], [0, 1]] and legenda["colunas"] == 1
    assert all(0.0 <= v <= 1.0 for v in legenda["canto"])


def test_as_fontes_do_aplicativo_vao_com_as_licencas(tmp_path):
    _figura, pasta, _nomes = _empacotar(tmp_path, "paineis_sem_desenho_e_inter", "svg")
    fontes = sorted(p.name for p in (pasta / "fontes").iterdir())
    assert "Inter-VariableFont.ttf" in fontes and "Inter-OFL.txt" in fontes
    assert not any(n.startswith(("IBMPlex", "JetBrains", "Atkinson")) for n in fontes)
    assert (pasta / "figura.svg").exists()


@pytest.mark.parametrize(("formato", "esperados"), [("png", {"figura.png"}), ("tiff", {"figura.tif", "figura.png"})])
def test_a_figura_em_imagem(tmp_path, formato, esperados):
    figura, pasta, nomes = _empacotar(tmp_path, "espectro_em_log", formato, dpi=300)
    assert {n.removeprefix(f"{figura.nome}/") for n in nomes if "/figura." in n} == esperados
    if formato == "tiff":
        assert np.array_equal(_rgb(pasta / "figura.tif"), _rgb(pasta / "figura.png"))


def test_o_script_em_pdf(tmp_path):
    _figura, pasta, _nomes = _empacotar(tmp_path, "tempo")
    resultado = _refazer(pasta, "--formato", "pdf", "--saida", "outra.pdf")
    assert resultado.returncode == 0, resultado.stderr
    assert (pasta / "outra.pdf").read_bytes().startswith(b"%PDF")


def test_a_referencia_de_um_vetorial_em_dpi_alto(tmp_path):
    _figura, pasta, _nomes = _empacotar(tmp_path, "espectro_em_log", dpi=1200)
    assert Image.open(pasta / "figura.png").info["dpi"] == pytest.approx((600, 600), abs=0.05)
    assert "os mesmos pixels" in _refazer(pasta).stdout


def test_o_que_a_descricao_nao_conhece_e_recusado():
    pagina = dd.desenhar(FIGURA, VISTAS, Dados(20_000), dpi=60)
    pagina.mpl.axes[0].fill_between([0, 1], [0, 1])
    pagina.pixels()
    with pytest.raises(pacote.PacoteInvalido, match="PolyCollection"):
        pacote.descrever(pagina)


def test_o_cancelar_nao_deixa_arquivo(tmp_path):
    destino = tmp_path / "p.zip"
    with pytest.raises(Cancelado):
        pacote.empacotar(FIGURA, VISTAS, Dados(200_000), destino, OpcoesDeExportacao("pdf"), proveniencia={},
                         cancelado=lambda: True)
    assert list(tmp_path.iterdir()) == []
