"""A exportação da figura (``sh_analyzer_gui.dados.exportar_figura``, F5.4), sem Qt: cada formato sai e é conferido
(o PDF no tamanho da página, com as fontes embutidas em TrueType e a proveniência; o SVG com o texto editável ou em
curvas; o EPS e o PGF com a proveniência no comentário, o PGF compilado pelo LaTeX; o PNG e o TIFF no dpi pedido, o
TIFF em LZW), as opções que não valem (com a razão), as curvas rasterizadas, "todos os pontos" e a conta deles, o
progresso e o cancelar (sem arquivo pela metade) e a proveniência da figura."""

import io
import json
import re
import shutil
import subprocess
from xml.etree import ElementTree

import numpy as np
import pytest
from PIL import Image
from sh_analyzer_gui.dados import desenho_da_figura as dd
from sh_analyzer_gui.dados import exportar_figura as ex
from sh_analyzer_gui.dados import proveniencia as prov
from sh_analyzer_gui.dados.exportar_figura import OpcoesDeExportacao, OpcoesInvalidas
from sh_analyzer_gui.dados.figura import Figura, Painel
from supraharmonicos.api import Cancelado
from test_gui_desenho_da_figura import CORRENTE, TENSAO, Dados, _vista

PROVENIENCIA = {"figura": {"nome": "Afundamento (a)"}, "fontes": [{"nome": "rede.bin", "crc32_amostras": 3735928559}]}
FIGURA = Figura("f", "Afundamento", "ieee_1", altura_mm=100.0, linhas=2, paineis=(
    Painel("a", 0, 0, vista="v"), Painel("b", 1, 0, vista="w")))
VISTAS = {"v": _vista("v", TENSAO, CORRENTE), "w": _vista("w", TENSAO)}
PONTOS_POR_MM = 72 / 25.4


@pytest.fixture(scope="module")
def dados():
    return Dados(200_000)


def _exportar(tmp_path, dados, formato, **opcoes):
    destino = tmp_path / f"figura{ex.FORMATOS[formato].extensao}"
    ex.exportar(FIGURA, VISTAS, dados, destino, OpcoesDeExportacao(formato, **opcoes), proveniencia=PROVENIENCIA,
                aplicativo="0.8.0")
    assert not list(tmp_path.glob("*.parcial"))
    return destino


def _string_do_pdf(conteudo: bytes, chave: bytes) -> str:
    """A string de ``chave`` no dicionário de informações do PDF (literal, com os escapes; UTF-16 com o BOM)."""
    i = conteudo.index(b"/" + chave + b" (") + len(chave) + 3
    bruto, escape = bytearray(), False
    while True:
        c = conteudo[i]
        i += 1
        if escape:
            bruto.append(c)
            escape = False
        elif c == 0x5C:                       # \
            escape = True
        elif c == 0x29:                       # )
            break
        else:
            bruto.append(c)
    bruto = bytes(bruto)
    return bruto[2:].decode("utf-16-be") if bruto.startswith(b"\xfe\xff") else bruto.decode("latin-1")


def test_o_pdf(tmp_path, dados):
    conteudo = _exportar(tmp_path, dados, "pdf").read_bytes()
    caixa = [float(v) for v in re.search(rb"/MediaBox \[ ([^\]]*) \]", conteudo).group(1).split()]
    assert caixa == pytest.approx([0, 0, 88 * PONTOS_POR_MM, 100 * PONTOS_POR_MM])
    assert b"/FontFile2" in conteudo and b"/Type3" not in conteudo          # TrueType embutida (Type 42)
    assert json.loads(_string_do_pdf(conteudo, b"Subject")) == PROVENIENCIA
    assert _string_do_pdf(conteudo, b"Title") == "Afundamento"
    assert _string_do_pdf(conteudo, b"Creator") == "SH-Analyzer 0.8.0"
    assert b"/Subtype /Image" not in conteudo


@pytest.mark.parametrize("editavel", [True, False])
def test_o_svg(tmp_path, dados, editavel):
    raiz = ElementTree.parse(_exportar(tmp_path, dados, "svg", texto_editavel=editavel)).getroot()
    assert raiz.get("width") == f"{88 * PONTOS_POR_MM:.6f}pt" and raiz.get("height") == f"{100 * PONTOS_POR_MM:.6f}pt"
    textos = [e.text for e in raiz.iter("{http://www.w3.org/2000/svg}text")]
    assert ("Tensão (kV)" in "".join(t or "" for t in textos)) is editavel
    descricao = next(e.text for e in raiz.iter("{http://purl.org/dc/elements/1.1/}description"))
    assert json.loads(descricao) == PROVENIENCIA


def test_o_eps(tmp_path, dados):
    conteudo = _exportar(tmp_path, dados, "eps").read_bytes().decode("latin-1")
    assert conteudo.startswith("%!PS-Adobe-3.0 EPSF-3.0") and "%%Creator: SH-Analyzer 0.8.0" in conteudo
    assert "%%BoundingBox: 0 0 250 284" in conteudo
    linha = next(x for x in conteudo.splitlines() if x.startswith("% SH-Analyzer: "))
    assert json.loads(linha.removeprefix("% SH-Analyzer: ")) == PROVENIENCIA
    assert conteudo.index("%%EndComments") < conteudo.index(linha)


def test_o_pgf_compila_no_latex(tmp_path, dados):
    sistema = ex.sistema_do_latex()
    if sistema is None:
        pytest.skip("sem LaTeX instalado")
    destino = _exportar(tmp_path, dados, "pgf")
    conteudo = destino.read_text(encoding="utf-8")
    primeira, segunda = conteudo.splitlines()[:2]
    assert primeira.startswith("%% SH-Analyzer") and json.loads(segunda.removeprefix("%% ")) == PROVENIENCIA
    assert "\\begin{pgfpicture}" in conteudo
    (tmp_path / "doc.tex").write_text("\\documentclass{article}\n\\usepackage{pgf}\n\\begin{document}\n"
                                      "\\input{figura.pgf}\n\\end{document}\n", encoding="utf-8")
    r = subprocess.run([sistema, "-interaction=nonstopmode", "-halt-on-error", "doc.tex"], cwd=tmp_path,
                       capture_output=True, timeout=120)
    assert r.returncode == 0 and (tmp_path / "doc.pdf").stat().st_size > 0


@pytest.mark.parametrize(("formato", "dpi"), [("png", 150), ("png", 300), ("tiff", 300)])
def test_as_imagens_no_dpi_pedido(tmp_path, dados, formato, dpi):
    imagem = Image.open(_exportar(tmp_path, dados, formato, dpi=dpi))
    assert imagem.mode == "RGB"
    assert imagem.size == (round(88 / 25.4 * dpi), round(100 / 25.4 * dpi))
    assert imagem.info["dpi"] == pytest.approx((dpi, dpi), abs=0.05)        # o PNG guarda pixels por metro, inteiros
    if formato == "png":
        assert json.loads(imagem.info["Description"]) == PROVENIENCIA and imagem.info["Software"] == "SH-Analyzer 0.8.0"
    else:
        assert imagem.info["compression"] == "tiff_lzw"
        assert json.loads(imagem.tag_v2[270]) == PROVENIENCIA and imagem.tag_v2[305] == "SH-Analyzer 0.8.0"
    assert np.asarray(imagem).min() < 100                                   # há tinta


def test_a_imagem_na_memoria_e_a_do_arquivo(tmp_path, dados):
    no_arquivo = _exportar(tmp_path, dados, "png", dpi=150).read_bytes()
    assert ex.em_bytes(FIGURA, VISTAS, dados, OpcoesDeExportacao("png", dpi=150), proveniencia=PROVENIENCIA,
                       aplicativo="0.8.0") == no_arquivo


@pytest.mark.parametrize(("criar", "trecho"), [
    (lambda: OpcoesDeExportacao("jpeg"), "formato desconhecido"),
    (lambda: OpcoesDeExportacao("png", dpi=100), "de 150 a 1200 dpi"),
    (lambda: OpcoesDeExportacao("tiff", dpi=200), "de 300 a 1200 dpi"),
    (lambda: OpcoesDeExportacao("pdf", dpi=1300), "de 150 a 1200 dpi"),
    (lambda: ex.conferir(Figura("p", "Pôster", "poster", altura_mm=1189.0), OpcoesDeExportacao("tiff", dpi=1200)),
     r"passa de 300 M pixels: use até 439 dpi"),
    (lambda: ex.conferir(Figura("p", "Pôster", "poster", altura_mm=1189.0),
                         OpcoesDeExportacao("pdf", dpi=1200, rasterizar_curvas=True)), "use até 439 dpi"),
])
def test_o_que_nao_vale_e_recusado(criar, trecho):
    with pytest.raises(OpcoesInvalidas, match=trecho):
        criar()


def test_o_poster_vetorial_sai_em_qualquer_dpi():
    """Sem imagem, o pôster sai a 1 200 dpi: o leiaute é achado em 150 dpi, e só a redução usa o dpi pedido."""
    ex.conferir(Figura("p", "Pôster", "poster", altura_mm=1189.0), OpcoesDeExportacao("pdf", dpi=1200))
    assert ex.dpi_maximo(FIGURA) == 1200.0


def test_o_pgf_sem_latex_e_sem_arquivo(monkeypatch, dados):
    # Com um LaTeX (fingido: a CI não tem nenhum), o que falta é o arquivo das imagens das curvas.
    monkeypatch.setattr(shutil, "which", lambda nome: f"/usr/bin/{nome}")
    with pytest.raises(OpcoesInvalidas, match="arquivo"):
        ex.exportar(FIGURA, VISTAS, dados, io.BytesIO(), OpcoesDeExportacao("pgf", rasterizar_curvas=True))
    monkeypatch.setattr(shutil, "which", lambda _nome: None)
    with pytest.raises(OpcoesInvalidas, match="precisa de um LaTeX"):
        ex.conferir(FIGURA, OpcoesDeExportacao("pgf"))


def test_as_curvas_rasterizadas_e_todos_os_pontos(tmp_path, dados):
    """Rasterizadas, as curvas viram imagem no PDF e o texto continua vetorial; com todos os pontos (a conta de
    :func:`pontos`), o PDF cresce."""
    reduzido = _exportar(tmp_path, dados, "pdf", dpi=300).stat().st_size
    rasterizado = _exportar(tmp_path, dados, "pdf", dpi=300, rasterizar_curvas=True).read_bytes()
    assert b"/Subtype /Image" in rasterizado and b"/FontFile2" in rasterizado
    todos = _exportar(tmp_path, dados, "pdf", dpi=300, todos_os_pontos=True).stat().st_size
    assert todos > 5 * reduzido
    # (a): a tensão e a corrente na captura inteira; (b): a tensão.
    assert ex.pontos(FIGURA, VISTAS, dados) == 3 * 200_000
    assert ex.LIMITE_DE_PONTOS == 2_000_000


def test_o_progresso_e_o_cancelar(tmp_path, dados, monkeypatch):
    monkeypatch.setattr(dd, "LOTE_DO_M4", 20_000)
    fracoes = []
    destino = tmp_path / "f.pdf"
    ex.exportar(FIGURA, VISTAS, dados, destino, OpcoesDeExportacao("pdf"), progresso=fracoes.append)
    assert fracoes == sorted(fracoes) and fracoes[-1] == 1.0 and len({round(f, 3) for f in fracoes if f < 0.8}) > 5
    cancelar = tmp_path / "cancelada.pdf"
    lidas = []
    with pytest.raises(Cancelado):
        ex.exportar(FIGURA, VISTAS, dados, cancelar, OpcoesDeExportacao("pdf"), progresso=lidas.append,
                    cancelado=lambda: len(lidas) >= 3)
    assert not cancelar.exists() and not list(tmp_path.glob("*.parcial"))


def test_a_proveniencia_da_figura():
    fontes = {"f1": prov.FonteDaProveniencia("f1", "rede.bin", "/lab/rede.bin", 2048, 0xDEADBEEF,
                                             {"versao_cabecalho": 9, "versao_firmware": "0.9", "hostname": "bbb",
                                              "lista_canais": [1, 3]}),
              "f9": prov.FonteDaProveniencia("f9", "outra.bin", "/lab/outra.bin")}
    p = prov.da_figura(FIGURA, VISTAS, fontes, aplicativo="0.8.0")
    assert (p["formato"], p["aplicativo"]["versao"], p["figura"]["largura_mm"]) == (prov.FORMATO, "0.8.0", 88.0)
    assert [(x["rotulo"], x["vista"]["nome"], len(x["vista"]["tracos"])) for x in p["paineis"]] == [
        ("(a)", "v", 2), ("(b)", "w", 1)]
    assert p["paineis"][0]["vista"]["tracos"][1] == CORRENTE.para_dict()
    (fonte,) = p["fontes"]                                       # só a que algum painel usa
    assert fonte["crc32_amostras"] == 0xDEADBEEF
    assert fonte["cabecalho"] == {"versao_cabecalho": 9, "versao_firmware": "0.9", "lista_canais": [1, 3]}
    assert json.loads(prov.em_texto(p)) == p
