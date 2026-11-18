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
import atexit  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

os.environ["SH_ANALYZER_CONFIG"] = tempfile.mkdtemp(prefix="sh-analyzer-config-")
os.environ["SH_ANALYZER_CACHE"] = tempfile.mkdtemp(prefix="sh-analyzer-cache-")     # as pirâmides, idem
os.environ["SH_ANALYZER_LOG"] = tempfile.mkdtemp(prefix="sh-analyzer-log-")         # o log do aplicativo, idem
# Os dados do laboratório ($DADOS: a pasta da sessão do dia, com as capturas trazidas e o caderno de bancada), idem:
# um teste que monta a Aquisição sem dizer a pasta nunca escreve no anotacoes.md de verdade de quem desenvolve.
os.environ["DADOS"] = tempfile.mkdtemp(prefix="sh-analyzer-dados-")
# E saem no fim do processo (cada um do pytest-xdist tem as suas): sem isso, cada rodada deixava quatro pastas no /tmp.
for _pasta in (os.environ["SH_ANALYZER_CONFIG"], os.environ["SH_ANALYZER_CACHE"], os.environ["SH_ANALYZER_LOG"],
               os.environ["DADOS"]):
    atexit.register(shutil.rmtree, _pasta, ignore_errors=True)

import pytest  # noqa: E402
from sh_placa import capturas_simuladas  # noqa: E402

# As capturas da placa simulada com blocos de 4096 amostras: com os do firmware, cada placa dos testes teria ~10 MB, e
# eles montam dezenas.
capturas_simuladas.BLOCO_DAS_CAPTURAS = 4096


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
