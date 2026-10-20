"""Testes dos utilitários de shell: ``scripts/compactar_amostras.sh`` e ``scripts/set_date.sh``.

Rodam os scripts de verdade (bash), com programas FALSOS no PATH onde o real não pode ser usado
(``ssh``, ``sudo`` e ``date -s`` no ``set_date.sh``; um ``7z`` que falha). Marcados ``e2e``.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
COMPACTAR = RAIZ / "scripts" / "compactar_amostras.sh"
SET_DATE = RAIZ / "scripts" / "set_date.sh"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform != "linux" or shutil.which("bash") is None, reason="precisa de Linux com bash"),
]


def _executavel(caminho: Path, conteudo: str) -> Path:
    caminho.write_text(conteudo)
    caminho.chmod(0o755)
    return caminho


@pytest.fixture
def dados(tmp_path):
    pasta = tmp_path / "dados"
    pasta.mkdir()
    (pasta / "a.bin").write_bytes(os.urandom(200_000))
    (pasta / "b.h5").write_bytes(bytes(1000))
    return pasta


def _compactar(*args, cwd: Path, path_extra: Path | None = None):
    env = dict(os.environ)
    if path_extra is not None:
        env["PATH"] = f"{path_extra}:{env['PATH']}"
    return subprocess.run(["bash", str(COMPACTAR), *map(str, args)], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=300)


@pytest.mark.skipif(shutil.which("7z") is None, reason="7z não instalado")
def test_7z_guarda_so_os_nomes_e_respeita_o_caminho_de_saida(dados, tmp_path):
    saida = tmp_path / "saida"
    saida.mkdir()
    proc = _compactar("--dir", dados, "-o", "teste.7z", cwd=saida)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    listagem = subprocess.run(["7z", "l", "-slt", str(saida / "teste.7z")], capture_output=True, text=True).stdout
    assert sorted(re.findall(r"^Path = (.+)$", listagem, re.M)[1:]) == ["a.bin", "b.h5"]   # o 1º 'Path' é o do .7z


@pytest.mark.skipif(shutil.which("zpaq") is None, reason="zpaq não instalado")
def test_zpaq_nao_grava_caminho_absoluto(dados, tmp_path):
    proc = _compactar("--max", "--dir", dados, "-o", tmp_path / "t.zpaq", cwd=tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    listagem = subprocess.run(["zpaq", "list", str(tmp_path / "t.zpaq")], capture_output=True, text=True).stdout
    assert re.search(r" a\.bin$", listagem, re.M) and str(dados) not in listagem


def test_falha_do_compressor_apaga_o_arquivo_pela_metade(dados, tmp_path):
    falsos = tmp_path / "falsos"
    falsos.mkdir()
    _executavel(falsos / "7z", '#!/bin/sh\nfor a; do case "$a" in *.7z) echo parcial > "$a";; esac; done\nexit 2\n')
    proc = _compactar("--dir", dados, "-o", "quebrado.7z", cwd=tmp_path, path_extra=falsos)
    assert proc.returncode == 2
    assert not (tmp_path / "quebrado.7z").exists()
    assert "Removendo arquivo de saída incompleto" in proc.stdout and "Falhou durante" in proc.stderr


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
