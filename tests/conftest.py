"""Configuração compartilhada do pytest.

* Força o backend 'Agg' do matplotlib (testes nunca abrem janela).
* Isola o estado global do logging entre testes (a CLI liga handlers no
  logger ``supraharmonicos``; sem isto, um teste de CLI mudaria o ``caplog`` dos
  seguintes).
* ``cli``: roda ``main()`` de uma CLI no mesmo processo e devolve
  ``(codigo_de_saida, stdout, stderr)`` -- rápido, sem subprocess.
"""

import logging
import os

os.environ.setdefault("MPLBACKEND", "Agg")
# A interface gráfica sem tela (tests/test_interface.py): na CI não há monitor, e na sua máquina nenhuma janela pisca.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# A configuração da interface (layout, tema, fontes) numa pasta temporária: nenhum teste lê nem grava a de quem
# desenvolve. Vale também para os subprocessos (o teste de partida do aplicativo). Os testes que precisam de uma
# configuração limpa usam a fixture ``config_limpa``.
import tempfile  # noqa: E402

os.environ["SH_ANALYZER_CONFIG"] = tempfile.mkdtemp(prefix="sh-analyzer-config-")

import pytest  # noqa: E402


def pytest_addoption(parser):
    parser.addoption("--desempenho", action="store_true",
                     help="roda os testes marcados 'desempenho' (tempo e memória; lentos e dependentes da máquina)")


def pytest_collection_modifyitems(config, items):
    """Os testes de desempenho medem tempo: dependem da máquina e da carga, e ficam fora do conjunto padrão."""
    if config.getoption("--desempenho"):
        return
    pular = pytest.mark.skip(reason="teste de desempenho: rode com --desempenho")
    for item in items:
        if "desempenho" in item.keywords:
            item.add_marker(pular)


@pytest.fixture(autouse=True)
def _isolar_logging():
    yield
    raiz = logging.getLogger("supraharmonicos")
    for h in list(raiz.handlers):
        if not isinstance(h, logging.NullHandler):
            raiz.removeHandler(h)
    raiz.propagate = True
    raiz.setLevel(logging.NOTSET)


@pytest.fixture
def config_limpa(tmp_path, monkeypatch):
    """Uma pasta de configuração da interface só deste teste (``sh_analyzer_gui.configuracao``)."""
    monkeypatch.setenv("SH_ANALYZER_CONFIG", str(tmp_path / "config"))
    return tmp_path / "config"


@pytest.fixture
def cli(capsys):
    """``cli(main, *argv) -> (rc, stdout, stderr)``; ``SystemExit`` (ex.: ``parser.error``) vira o código."""

    def _rodar(main, *argv):
        try:
            rc = main([str(a) for a in argv])
        except SystemExit as e:
            rc = e.code
        capturado = capsys.readouterr()
        return rc, capturado.out, capturado.err

    return _rodar
