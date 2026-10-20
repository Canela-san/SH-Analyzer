"""As dependências declaradas nos blocos PEP 723 das entradas (``uv run script.py``)
precisam ser as de ``pyproject.toml`` -- senão ``uv run`` e ``pip install -e .``
instalariam ambientes diferentes."""

import re
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 (o mínimo suportado): tomllib só existe a partir da 3.11
    import tomli as tomllib

RAIZ = Path(__file__).resolve().parents[1]
SCRIPTS = RAIZ / "scripts"
ENTRADAS = ["adc_tool.py", "gerar_perfil_sonda.py", "medir_captura.py", "compactar_amostras.py"]


def nome_e_spec(requisito: str) -> tuple[str, str]:
    m = re.fullmatch(r"\s*([A-Za-z0-9_.\-]+)\s*(.*)", requisito)
    return m.group(1).lower().replace("_", "-"), m.group(2).replace(" ", "")


def dependencias_pep723(caminho: Path) -> dict[str, str]:
    texto = caminho.read_text(encoding="utf-8")
    bloco = re.search(r"^# /// script\n((?:#.*\n)+?)# ///$", texto, re.M)
    assert bloco, f"{caminho.name}: bloco PEP 723 ausente"
    conteudo = "\n".join(ln[2:] if ln.startswith("# ") else ln[1:] for ln in bloco.group(1).splitlines())
    return dict(nome_e_spec(r) for r in tomllib.loads(conteudo)["dependencies"])


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("entrada", ENTRADAS)
def test_dependencias_da_entrada_batem_com_o_pyproject(pyproject, entrada):
    projeto = pyproject["project"]
    declaradas = dict(nome_e_spec(r) for r in projeto["dependencies"])
    declaradas.update(dict(nome_e_spec(r) for extra in projeto["optional-dependencies"].values() for r in extra))
    for nome, spec in dependencias_pep723(SCRIPTS / entrada).items():
        assert nome in declaradas, f"{entrada} declara '{nome}', ausente do pyproject.toml"
        assert declaradas[nome] == spec, f"{entrada}: '{nome}{spec}' difere do pyproject ('{nome}{declaradas[nome]}')"


def test_pacote_nao_importa_nada_fora_das_dependencias_declaradas(pyproject):
    import ast
    import sys

    declaradas = {nome_e_spec(r)[0] for r in pyproject["project"]["dependencies"]}
    permitidos = {"numpy", "scipy", "matplotlib", "h5py", "rich"}
    assert permitidos == declaradas
    for p in (SCRIPTS / "supraharmonicos").glob("*.py"):
        for no in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(no, ast.Import):
                nomes = [a.name.split(".")[0] for a in no.names]
            elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
                nomes = [no.module.split(".")[0]]
            else:
                continue
            for n in nomes:
                assert n in sys.stdlib_module_names or n in permitidos, f"{p.name}: dependência não declarada '{n}'"
