"""Testes dos utilitários de shell ``scripts/set_date.sh`` e ``scripts/enviar_firmware.sh``.

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


# ---------------------------------------------------------------------------
# enviar_firmware.sh: só firmware/, com a versão e o plano B (sem copiar capturas)
# ---------------------------------------------------------------------------

ENVIAR = RAIZ / "scripts" / "enviar_firmware.sh"
GIT = ["git", "-c", "user.name=Teste", "-c", "user.email=teste@exemplo", "-c", "commit.gpgsign=false",
       "-c", "tag.gpgsign=false"]


@pytest.fixture
def bancada(tmp_path):
    """Um repositório de brinquedo com o script e um firmware/ mínimo, e um ssh falso que roda o comando "remoto"
    num home falso (``bancada.home``), lendo o tar do stdin como o ssh de verdade."""
    if shutil.which("git") is None or shutil.which("tar") is None:
        pytest.skip("precisa de git e tar")
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "firmware").mkdir()
    shutil.copy2(ENVIAR, repo / "scripts" / "enviar_firmware.sh")
    (repo / ".gitignore").write_text("firmware/VERSAO\nfirmware/ler_adc\n")
    (repo / "firmware" / "ler_adc.c").write_text("int main(void) { return 0; }\n")
    (repo / "firmware" / "Makefile").write_text("all:\n")
    _executavel(repo / "firmware" / "setup.sh", "#!/bin/bash\necho \"setup rodou em $(basename \"$PWD\")\"\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "inicial"], cwd=repo, check=True)
    subprocess.run([*GIT, "tag", "-a", "v9.9", "-m", "v9.9"], cwd=repo, check=True)   # anotada, como as do projeto
    (repo / "firmware" / "ler_adc").write_text("binário compilado no PC: não pode ir\n")   # ignorado pelo git
    home = tmp_path / "home_bbb"
    home.mkdir()
    falsos = tmp_path / "falsos"
    falsos.mkdir()
    _executavel(falsos / "ssh", f'#!/bin/bash\ncd "{home}" && exec bash -c "${{@: -1}}"\n')

    class Bancada:
        pass

    b = Bancada()
    b.repo, b.home = repo, home

    def rodar(*args, **env_extra):
        env = {**os.environ, "PATH": f"{falsos}:{os.environ['PATH']}", **env_extra}
        return subprocess.run(["bash", str(repo / "scripts" / "enviar_firmware.sh"), *args], cwd=repo, env=env,
                              capture_output=True, text=True, timeout=60)

    def commit(mensagem):
        subprocess.run([*GIT, "commit", "-q", "-am", mensagem], cwd=repo, check=True)

    b.rodar, b.commit = rodar, commit
    return b


def test_envia_so_o_firmware_versionado_com_a_versao(bancada):
    r = bancada.rodar()
    assert r.returncode == 0, r.stderr
    remoto = bancada.home / "firmware"
    assert sorted(p.name for p in remoto.iterdir()) == ["Makefile", "VERSAO", "ler_adc.c", "setup.sh"]
    assert (remoto / "VERSAO").read_text() == "v9.9\n"
    assert (remoto / "setup.sh").stat().st_mode & 0o111                        # continua executável
    assert not (bancada.home / "firmware-anteriores").exists()
    assert "primeira cópia" in r.stdout and 'Firmware: v9.9' in r.stdout


def test_segundo_envio_guarda_o_plano_b_sem_as_capturas(bancada):
    assert bancada.rodar().returncode == 0
    remoto = bancada.home / "firmware"
    (remoto / "ler_adc").write_text("binário compilado na BeagleBone\n")
    (remoto / "T0.bin").write_bytes(b"\x00" * 4096)                             # uma captura na pasta do firmware
    (remoto / "capturas").mkdir()
    (remoto / "capturas" / "x.bin").write_bytes(b"\x00" * 16)
    (bancada.repo / "firmware" / "ler_adc.c").write_text("int main(void) { return 1; }\n")
    bancada.commit("ler_adc novo")
    r = bancada.rodar()
    assert r.returncode == 0, r.stderr
    (plano_b,) = (bancada.home / "firmware-anteriores").iterdir()
    assert plano_b.name.endswith("_v9.9")
    assert sorted(p.name for p in plano_b.iterdir()) == ["Makefile", "VERSAO", "ler_adc", "ler_adc.c", "setup.sh"]
    assert "return 0" in (plano_b / "ler_adc.c").read_text()                     # o código antigo, inteiro
    assert "return 1" in (remoto / "ler_adc.c").read_text()
    assert (remoto / "VERSAO").read_text().startswith("v9.9-1-g")
    assert (remoto / "T0.bin").stat().st_size == 4096 and (remoto / "capturas" / "x.bin").exists()   # nada apagado


def test_recusa_firmware_com_mudancas_nao_commitadas(bancada):
    (bancada.repo / "firmware" / "ler_adc.c").write_text("int main(void) { return 2; }\n")
    r = bancada.rodar()
    assert r.returncode == 1 and "mudanças não commitadas" in r.stderr and "ler_adc.c" in r.stderr
    assert not (bancada.home / "firmware").exists()
    r = bancada.rodar("--forcar")
    assert r.returncode == 0, r.stderr
    assert (bancada.home / "firmware" / "VERSAO").read_text() == "v9.9-dirty\n"


def test_simular_nao_escreve_nem_envia(bancada):
    r = bancada.rodar("--simular")
    assert r.returncode == 0 and "--simular" in r.stdout and "ler_adc.c" in r.stdout
    assert not (bancada.home / "firmware").exists() and not (bancada.repo / "firmware" / "VERSAO").exists()


def test_pasta_com_til_e_setup(bancada):
    r = bancada.rodar("--setup", BBB_PASTA="~/sh/firmware")
    assert r.returncode == 0, r.stderr
    assert (bancada.home / "sh" / "firmware" / "VERSAO").exists()               # o '~/' vira o home, não uma pasta '~'
    assert "setup rodou em firmware" in r.stdout


def test_opcao_desconhecida_e_erro(bancada):
    r = bancada.rodar("--nao-existe")
    assert r.returncode == 1 and "opção desconhecida" in r.stderr
