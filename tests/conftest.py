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

import pytest  # noqa: E402


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
