"""Todo script executável do projeto roda com ``uv run`` (e com ``./script.py``), sem instalar nada antes.

``uv run script.py`` monta um ambiente só com o bloco PEP 723 (``# /// script``) do arquivo, ignorando o
``pyproject.toml``. Por isso, para cada script com ``if __name__ == "__main__"``:

* o bloco existe e o shebang é o do uv (``./script.py`` também passa pelo uv) e o arquivo é executável;
* tudo o que ele importa ao carregar -- inclusive pelos módulos do pacote e pelos vizinhos de pasta que ele
  importa -- está no bloco (senão ``uv run`` cai num ``ModuleNotFoundError`` que o ambiente de testes esconde);
* cada versão declarada é IGUAL à do ``pyproject.toml`` (senão ``uv run`` e ``pip install -e .`` instalariam
  ambientes diferentes).
"""

import ast
import os
import re
import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 (o mínimo suportado): tomllib só existe a partir da 3.11
    import tomli as tomllib

RAIZ = Path(__file__).resolve().parents[1]
SCRIPTS = RAIZ / "scripts"
PACOTE = SCRIPTS / "supraharmonicos"
SHEBANG_UV = "#!/usr/bin/env -S uv run --script"
# nome no 'import' -> nome da distribuição no PyPI, quando diferem
DISTRIBUICAO = {"PyQt6": "pyqt6"}


def _executaveis() -> list[Path]:
    achados = []
    for pasta in (SCRIPTS, RAIZ / "relatorio", RAIZ / "tests", RAIZ / "firmware"):
        for p in sorted(pasta.glob("*.py")):
            if re.search(r"""^if __name__ == ["']__main__["']:""", p.read_text(encoding="utf-8"), re.M):
                achados.append(p)
    return achados


EXECUTAVEIS = _executaveis()
IDS = [str(p.relative_to(RAIZ)) for p in EXECUTAVEIS]


def nome_e_spec(requisito: str) -> tuple[str, str]:
    m = re.fullmatch(r"\s*([A-Za-z0-9_.\-]+)\s*(.*)", requisito)
    return m.group(1).lower().replace("_", "-"), m.group(2).replace(" ", "")


def dependencias_pep723(caminho: Path) -> dict[str, str]:
    texto = caminho.read_text(encoding="utf-8")
    bloco = re.search(r"^# /// script\n((?:#.*\n)+?)# ///$", texto, re.M)
    assert bloco, f"{caminho.name}: bloco PEP 723 ausente"
    conteudo = "\n".join(ln[2:] if ln.startswith("# ") else ln[1:] for ln in bloco.group(1).splitlines())
    return dict(nome_e_spec(r) for r in tomllib.loads(conteudo)["dependencies"])


def _imports_ao_carregar(arvore: ast.AST):
    """Os ``import`` que rodam ao carregar o módulo: os de topo, os de dentro de if/try/with/class, mas NÃO os de
    dentro de funções (esses são importações sob demanda, como o matplotlib de ``modos.executar_plotagem``)."""
    for no in ast.iter_child_nodes(arvore):
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(no, (ast.Import, ast.ImportFrom)):
            yield no
        else:
            yield from _imports_ao_carregar(no)


def _externos_ao_carregar(script: Path) -> set[str]:
    """Pacotes de terceiros importados ao carregar ``script``, seguindo o pacote ``supraharmonicos`` e os
    módulos vizinhos (ex.: ``capturas_sinteticas`` para o ``ler_adc_falso``)."""
    externos: set[str] = set()
    vistos: set[Path] = set()
    fila = [script]
    while fila:
        atual = fila.pop()
        if atual in vistos:
            continue
        vistos.add(atual)
        for no in _imports_ao_carregar(ast.parse(atual.read_text(encoding="utf-8"))):
            if isinstance(no, ast.ImportFrom) and no.level:
                alvos = [no.module] if no.module else [a.name for a in no.names]
                fila += [PACOTE / f"{m.split('.')[0]}.py" for m in alvos if (PACOTE / f"{m.split('.')[0]}.py").exists()]
                continue
            nomes = [a.name for a in no.names] if isinstance(no, ast.Import) else [no.module or ""]
            if isinstance(no, ast.ImportFrom) and no.module == "supraharmonicos":
                nomes = [f"supraharmonicos.{a.name}" for a in no.names]
            for nome in nomes:
                partes = nome.split(".")
                if partes[0] == "supraharmonicos":
                    alvo = PACOTE / f"{partes[1]}.py" if len(partes) > 1 else PACOTE / "__init__.py"
                    if alvo.exists():
                        fila.append(alvo)
                elif (atual.parent / f"{partes[0]}.py").exists():
                    fila.append(atual.parent / f"{partes[0]}.py")
                elif partes[0] not in sys.stdlib_module_names and partes[0] != "__future__":
                    externos.add(partes[0])
    return externos


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))


def test_os_scripts_executaveis_foram_encontrados():
    nomes = {p.name for p in EXECUTAVEIS}
    assert {"adc_tool.py", "gerar_perfil_sonda.py", "medir_captura.py", "compactar_amostras.py",
            "gerar_figuras.py", "ler_adc_falso.py"} <= nomes


@pytest.mark.parametrize("script", EXECUTAVEIS, ids=IDS)
def test_script_roda_com_uv_run(script):
    linhas = script.read_text(encoding="utf-8").splitlines()
    assert linhas[0] == SHEBANG_UV, f"{script.name}: o shebang precisa ser '{SHEBANG_UV}' (./{script.name} usa o uv)"
    assert "# /// script" in linhas[1:12], f"{script.name}: bloco PEP 723 ausente logo depois do shebang"
    if os.name == "posix":
        assert os.access(script, os.X_OK), f"{script.name}: sem permissão de execução (chmod +x)"


@pytest.mark.parametrize("script", EXECUTAVEIS, ids=IDS)
def test_script_declara_tudo_o_que_importa(script):
    declaradas = set(dependencias_pep723(script))
    faltando = {m for m in _externos_ao_carregar(script) if DISTRIBUICAO.get(m, m).lower() not in declaradas}
    assert not faltando, f"{script.name} importa {sorted(faltando)} mas não os declara no bloco PEP 723"


@pytest.mark.parametrize("script", EXECUTAVEIS, ids=IDS)
def test_versoes_do_script_batem_com_o_pyproject(pyproject, script):
    projeto = pyproject["project"]
    declaradas = dict(nome_e_spec(r) for r in projeto["dependencies"])
    declaradas.update(dict(nome_e_spec(r) for extra in projeto["optional-dependencies"].values() for r in extra))
    for nome, spec in dependencias_pep723(script).items():
        assert nome in declaradas, f"{script.name} declara '{nome}', ausente do pyproject.toml"
        assert declaradas[nome] == spec, f"{script.name}: '{nome}{spec}' difere do pyproject ('{nome}{declaradas[nome]}')"


def test_detector_de_imports_enxerga_o_pacote_e_ignora_imports_sob_demanda():
    """Sanidade do próprio teste: o fecho do adc_tool passa pelo pacote (scipy vem de lá, não da entrada) e não
    inclui o matplotlib, que só é importado dentro de uma função."""
    externos = _externos_ao_carregar(SCRIPTS / "adc_tool.py")
    assert {"numpy", "scipy"} <= externos and "matplotlib" not in externos


def test_pacote_nao_importa_nada_fora_das_dependencias_declaradas(pyproject):
    declaradas = {nome_e_spec(r)[0] for r in pyproject["project"]["dependencies"]}
    permitidos = {"numpy", "scipy", "matplotlib", "h5py", "rich"}
    assert permitidos == declaradas
    for p in PACOTE.glob("*.py"):
        for no in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(no, ast.Import):
                nomes = [a.name.split(".")[0] for a in no.names]
            elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
                nomes = [no.module.split(".")[0]]
            else:
                continue
            for n in nomes:
                assert n in sys.stdlib_module_names or n in permitidos, f"{p.name}: dependência não declarada '{n}'"
