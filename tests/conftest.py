"""Configuração compartilhada do pytest.

* Força o backend 'Agg' do matplotlib (testes nunca abrem janela).
* Isola o estado global do logging entre testes (a CLI liga handlers no
  logger ``supraharmonicos``; sem isto, um teste de CLI mudaria o ``caplog`` dos
  seguintes).
* ``cli``: roda ``main()`` de uma CLI no mesmo processo e devolve
  ``(codigo_de_saida, stdout, stderr)`` -- rápido, sem subprocess.
"""

import gc
import logging
import os
import sys

os.environ.setdefault("MPLBACKEND", "Agg")
# Uma thread do BLAS por processo: o pytest-xdist já põe um processo em cada núcleo, e o OpenBLAS de cada um abria uma
# thread por núcleo (8 processos x 8 threads disputando 8 núcleos; a suíte levava ~10% a mais).
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
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


def _apagar_o_que_o_qt_adiou() -> bool:
    """Apaga de verdade o que foi mandado apagar (o ``deleteLater`` das fixtures e do ``qtbot``): fora de um laço de
    eventos, o ``processEvents`` não apaga nada. Sem isso, cada janela de teste ficava viva (~1 200 widgets, as
    pirâmides abertas), o tema de cada teste novo passava por todas as anteriores, e a interface em série levava
    52 min. Sem o Qt carregado, não faz nada (os testes do motor nem o importam)."""
    qtcore = sys.modules.get("PySide6.QtCore")
    if qtcore is None or qtcore.QCoreApplication.instance() is None:
        return False
    qtcore.QCoreApplication.sendPostedEvents(None, qtcore.QEvent.Type.DeferredDelete)
    return True


def pytest_fixture_post_finalizer(fixturedef, request):
    """Logo depois de cada fixture terminar: a janela que ela fechou some antes da próxima limpeza (a fixture ``app``
    que volta o tema e as fontes repassava o QSS pela janela fechada, ~1 s por teste)."""
    _apagar_o_que_o_qt_adiou()


def _janelas_do_aplicativo() -> set[int]:
    """As janelas (widgets sem pai) do aplicativo vivas agora: as do ``sh_analyzer_gui``, não as do próprio Qt (a
    dica, os menus)."""
    qtw = sys.modules.get("PySide6.QtWidgets")
    if qtw is None or qtw.QApplication.instance() is None:
        return set()
    return {id(w) for w in qtw.QApplication.topLevelWidgets() if type(w).__module__.startswith("sh_analyzer_gui")}


@pytest.fixture(autouse=True)
def _apagar_os_widgets_do_teste():
    """No fim de cada teste, o que sobrou, e os ciclos entre o Python e os widgets (sem o ``gc``, sobram alguns). E
    acusa a janela que o teste abriu e não mandou apagar (``deleteLater`` ou ``qtbot.addWidget``): uma esquecida
    deixava a interface 20 vezes mais lenta para todos os testes seguintes do mesmo processo."""
    antes = _janelas_do_aplicativo()
    yield
    if not _apagar_o_que_o_qt_adiou():
        return
    gc.collect()
    qtw = sys.modules["PySide6.QtWidgets"]
    sobraram = [w for w in qtw.QApplication.topLevelWidgets()
                if type(w).__module__.startswith("sh_analyzer_gui") and id(w) not in antes]
    if sobraram:
        nomes = ", ".join(sorted({type(w).__name__ for w in sobraram}))
        for w in sobraram:          # o teste falha, mas os seguintes não pagam por ele
            w.close()
            w.deleteLater()
        _apagar_o_que_o_qt_adiou()
        pytest.fail(f"o teste deixou {len(sobraram)} janela(s) viva(s): {nomes}. Feche-a(s) com deleteLater() "
                    "(ou registre com qtbot.addWidget)", pytrace=False)


@pytest.fixture
def config_limpa(tmp_path, monkeypatch):
    """Uma pasta de configuração da interface só deste teste (``sh_analyzer_gui.configuracao``), com os primeiros
    passos já vistos (o cartão não aparece por cima das vistas; o teste dele apaga a marca)."""
    pasta = tmp_path / "config"
    pasta.mkdir(exist_ok=True)
    (pasta / "SH-Analyzer.ini").write_text("[ajuda]\nprimeiros_passos=vistos\n", encoding="utf-8")
    monkeypatch.setenv("SH_ANALYZER_CONFIG", str(pasta))
    return pasta


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
