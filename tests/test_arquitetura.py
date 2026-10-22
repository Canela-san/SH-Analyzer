"""Regras de arquitetura do pacote ``supraharmonicos`` -- ver docs/software-architecture.md.

Estes testes existem para que a estrutura continue sendo a que a documentação
descreve, sem depender de revisão manual:

1. dependências entre módulos só descem de camada (sem ciclos);
2. código de biblioteca não imprime nem encerra o processo (``print``,
   ``sys.exit``, ``SystemExit``): usa ``logging`` e ``ErroSHAN``;
3. dependências pesadas ficam confinadas (matplotlib, h5py, rich);
4. as entradas em ``scripts/`` são finas.
"""

import ast
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
PACOTE = SCRIPTS / "supraharmonicos"

# Camada de cada módulo: um módulo só pode importar módulos de camada ESTRITAMENTE menor.
CAMADAS = {
    # 0 -- fundações (não dependem de ninguém do pacote)
    "erros": 0, "constantes": 0, "registro": 0,
    # 1 -- formatos e algoritmos puros
    "cabecalho": 1, "amostras": 1, "canais": 1, "filtros": 1, "fundamental": 1, "sonda": 1, "plotagem": 1,
    "referencia": 1, "osciloscopio": 1, "harmonicos": 1, "bandas_iec": 1, "fase_quadrada": 1,
    # 2 -- composições de camada 1
    "espectro": 2, "conversao": 2, "hdf5": 2, "contexto": 2, "metricas_captura": 2, "compactacao": 2, "exportacao": 2,
    # 3 -- aplicação
    "calibracao_sonda": 3, "modos": 3,
    # 4
    "escrita_perfil": 4, "cli_adc_tool": 4, "cli_medir_captura": 4, "cli_compactar": 4, "cli_info": 4,
    # 5
    "cli_gerar_perfil": 5, "cli_medir_fase": 5,
    # 6 -- a porta de entrada (adc_tool.py SUBCOMANDO): escolhe a CLI e a importa só quando pedida
    "cli_principal": 6,
}
MODULOS_CLI = {"cli_adc_tool", "cli_gerar_perfil", "cli_medir_captura", "cli_compactar", "cli_info", "cli_principal",
               "cli_medir_fase"}


def modulos_do_pacote() -> list[str]:
    return sorted(p.stem for p in PACOTE.glob("*.py") if p.stem != "__init__")


def importados_internos(modulo: str) -> set[str]:
    arvore = ast.parse((PACOTE / f"{modulo}.py").read_text(encoding="utf-8"))
    achados = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom) and no.level == 1:
            if no.module:
                achados.add(no.module.split(".")[0])
            else:                                  # 'from . import plotagem'
                achados.update(a.name for a in no.names)
    return achados


def importados_externos(modulo: str) -> set[str]:
    arvore = ast.parse((PACOTE / f"{modulo}.py").read_text(encoding="utf-8"))
    achados = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            achados.update(a.name.split(".")[0] for a in no.names)
        elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
            achados.add(no.module.split(".")[0])
    return achados


def test_todo_modulo_tem_camada_declarada():
    assert set(modulos_do_pacote()) == set(CAMADAS), (
        "módulo novo/removido: atualize CAMADAS aqui e a tabela de docs/software-architecture.md"
    )


@pytest.mark.parametrize("modulo", sorted(CAMADAS))
def test_dependencias_so_descem_de_camada(modulo):
    for dep in importados_internos(modulo):
        assert dep in CAMADAS, f"{modulo} importa módulo desconhecido {dep}"
        assert CAMADAS[dep] < CAMADAS[modulo], (
            f"{modulo} (camada {CAMADAS[modulo]}) não pode importar {dep} (camada {CAMADAS[dep]})"
        )


def test_so_a_cli_conhece_o_logging_do_console():
    for modulo in modulos_do_pacote():
        if modulo not in MODULOS_CLI:
            assert "registro" not in importados_internos(modulo), f"{modulo}: só cli_* configuram o logging"


def test_nenhuma_cli_e_importada_por_outro_modulo():
    """Só a porta de entrada (cli_principal) escolhe e importa as CLIs, e só dentro das funções (sob demanda)."""
    for modulo in modulos_do_pacote():
        if modulo != "cli_principal":
            assert not (importados_internos(modulo) & MODULOS_CLI), f"{modulo} importa uma CLI"
    topo = ast.parse((PACOTE / "cli_principal.py").read_text(encoding="utf-8")).body
    assert not any(isinstance(n, ast.ImportFrom) and n.level == 1 and n.module in MODULOS_CLI for n in topo)


def test_scipy_so_e_importado_dentro_das_funcoes():
    """Importar o pacote não carrega o SciPy (~2 s): cada função importa a parte que usa, quando é chamada. Assim
    `adc_tool.py --help`, `info`, a conversão e o HDF5 não pagam por uma análise espectral que não pedem."""
    for modulo in modulos_do_pacote():
        topo = ast.parse((PACOTE / f"{modulo}.py").read_text(encoding="utf-8")).body
        for no in topo:
            if isinstance(no, ast.Import):
                assert not any(a.name.split(".")[0] == "scipy" for a in no.names), f"{modulo}: import scipy no topo"
            elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
                assert no.module.split(".")[0] != "scipy", f"{modulo}:{no.lineno}: from {no.module} import no topo"


@pytest.mark.parametrize("modulo", sorted(set(CAMADAS) - {"registro"}))
def test_biblioteca_nao_imprime_nem_encerra_o_processo(modulo):
    arvore = ast.parse((PACOTE / f"{modulo}.py").read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id == "print":
            pytest.fail(f"{modulo}:{no.lineno}: print() -- use logging (ver registro.py)")
        if isinstance(no, ast.Raise) and no.exc is not None:
            alvo = no.exc.func if isinstance(no.exc, ast.Call) else no.exc
            if isinstance(alvo, ast.Name) and alvo.id == "SystemExit":
                pytest.fail(f"{modulo}:{no.lineno}: raise SystemExit -- levante ErroSHAN (ver erros.py)")
        if isinstance(no, ast.Attribute) and isinstance(no.value, ast.Name) and no.value.id == "sys" and no.attr == "exit":
            pytest.fail(f"{modulo}:{no.lineno}: sys.exit -- levante ErroSHAN (ver erros.py)")


def test_dependencias_pesadas_ficam_confinadas():
    com_matplotlib = {m for m in modulos_do_pacote() if "matplotlib" in importados_externos(m)}
    assert com_matplotlib == {"plotagem", "escrita_perfil"}, com_matplotlib
    # escrita_perfil só importa matplotlib DENTRO de gerar_grafico (uso de --plot), nunca no topo
    topo = ast.parse((PACOTE / "escrita_perfil.py").read_text(encoding="utf-8")).body
    assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) and "matplotlib" in ast.dump(n) for n in topo)
    assert {m for m in modulos_do_pacote() if "h5py" in importados_externos(m)} == {"hdf5"}
    assert {m for m in modulos_do_pacote() if "rich" in importados_externos(m)} == {"cli_compactar"}
    topo = ast.parse((PACOTE / "hdf5.py").read_text(encoding="utf-8")).body
    assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) and "h5py" in ast.dump(n) for n in topo)


def test_plotagem_so_e_importada_pelo_modo_de_plotagem_de_forma_tardia():
    for modulo in modulos_do_pacote():
        if modulo == "modos":
            topo = ast.parse((PACOTE / "modos.py").read_text(encoding="utf-8")).body
            assert not any(isinstance(n, ast.ImportFrom) and any(a.name == "plotagem" for a in n.names) for n in topo), \
                "modos deve importar plotagem dentro de executar_plotagem (quem converte não paga o matplotlib)"
        else:
            assert "plotagem" not in importados_internos(modulo)


@pytest.mark.parametrize("entrada", ["adc_tool.py", "gerar_perfil_sonda.py", "medir_captura.py", "compactar_amostras.py",
                                     "medir_fase.py"])
def test_entradas_em_scripts_sao_finas(entrada):
    texto = (SCRIPTS / entrada).read_text(encoding="utf-8")
    codigo = [ln for ln in ast.parse(texto).body if not isinstance(ln, ast.Expr)]   # tira o docstring
    assert len(texto.splitlines()) < 40
    assert len(codigo) <= 2, "a lógica mora em scripts/supraharmonicos; a entrada só chama main()"
    assert "SystemExit(main())" in texto and "from supraharmonicos." in texto


def test_medir_captura_nao_depende_dos_modos_do_adc_tool():
    """P3: a correção de sonda mora em ``contexto``; o ``medir_captura`` não arrasta os modos do ``adc_tool``."""
    assert "modos" not in importados_internos("cli_medir_captura")
    assert "aplicar_correcao_sondas" in (PACOTE / "contexto.py").read_text(encoding="utf-8")
