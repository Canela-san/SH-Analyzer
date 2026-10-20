"""Testes do utilitário de shell ``scripts/set_date.sh``.

Rodam o script de verdade (bash), com programas FALSOS no PATH onde o real não pode ser usado (``ssh``, ``sudo``
e ``date -s``). Marcados ``e2e``. (O ``compactar_amostras`` virou Python: ``tests/test_compactacao.py``.)
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SET_DATE = RAIZ / "scripts" / "set_date.sh"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform != "linux" or shutil.which("bash") is None, reason="precisa de Linux com bash"),
]


def _executavel(caminho: Path, conteudo: str) -> Path:
    caminho.write_text(conteudo)
    caminho.chmod(0o755)
    return caminho


def test_set_date_desconta_o_tempo_da_senha_do_sudo(tmp_path):
    """O ssh falso roda o comando remoto aqui mesmo; o sudo falso demora 1 s (o operador digitando a senha)
    e o date falso anota a hora que seria gravada, em vez de mudar o relógio."""
    falsos = tmp_path / "falsos"
    falsos.mkdir()
    registro = tmp_path / "hora_gravada"
    _executavel(falsos / "ssh", '#!/bin/bash\nexec bash -c "${@: -1}"\n')
    _executavel(falsos / "sudo", '#!/bin/bash\nwhile [ "$1" != bash ]; do shift; done\nsleep 1\nexec "$@"\n')
    _executavel(falsos / "date", f'#!/bin/bash\nif [ "$1 $2" = "-u -s" ]; then echo "${{3#@}}" > "{registro}"; exit 0; fi\n'
                                 'exec /usr/bin/date "$@"\n')
    env = {**os.environ, "PATH": f"{falsos}:{os.environ['PATH']}"}
    env.pop("SSHPASS", None)
    antes = float(subprocess.run(["/usr/bin/date", "-u", "+%s.%N"], capture_output=True, text=True).stdout)
    proc = subprocess.run(["bash", str(SET_DATE)], env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    gravada = float(registro.read_text())
    assert 1.0 <= gravada - antes < 3.0     # a hora enviada mais o segundo gasto no sudo (com folga para a máquina)
