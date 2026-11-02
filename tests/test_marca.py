"""Testes de ``report/gerar_marca.py``: os SVGs da marca commitados em ``docs/images/`` são os que o script gera
(ninguém editou um à mão nem esqueceu de refazê-los depois de mudar o desenho)."""

import importlib.util
import sys
import xml.dom.minidom
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "report" / "gerar_marca.py"


@pytest.fixture(scope="module")
def gm():
    spec = importlib.util.spec_from_file_location("gerar_marca", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    yield modulo
    sys.modules.pop(spec.name, None)


def test_svgs_commitados_sao_os_que_o_script_gera(gm):
    for nome, conteudo in gm.svgs().items():
        commitado = RAIZ / "docs" / "images" / nome
        assert commitado.exists(), f"{nome}: rode 'uv run report/gerar_marca.py' e commite o SVG"
        assert commitado.read_bytes() == conteudo.encode("utf-8"), (
            f"{nome} difere do que report/gerar_marca.py gera: rode o script e commite o SVG")


def test_svgs_sao_xml_valido_com_titulo_e_descricao(gm):
    for nome, conteudo in gm.svgs().items():
        raiz = xml.dom.minidom.parseString(conteudo.encode("utf-8")).documentElement
        assert raiz.tagName == "svg", nome
        assert raiz.getElementsByTagName("title")[0].firstChild.data == "SH-Analyzer", nome
        assert raiz.getElementsByTagName("desc")[0].firstChild.data, nome


def test_main_grava_os_seis_arquivos_na_pasta_pedida(gm, tmp_path):
    assert gm.main(["--saida", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(gm.svgs())
