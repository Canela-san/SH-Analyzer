"""O Python do aplicativo empacotado (``sh_placa.como_python``; F7.12) e a versão do firmware que vai no pacote
(``sh_placa.versao``): o que o executável do PyInstaller faz no lugar do ``sys.executable`` para a placa simulada e
para o agente local. Aqui, fora do pacote, :func:`rodar` é chamada por um Python de verdade, num processo à parte."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from sh_placa import como_python, versao
from sh_placa.agente import AGENTE

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _como_python(*argv: str, entrada: str | None = None) -> subprocess.CompletedProcess:
    codigo = (f"import sys; sys.path.insert(0, {str(SCRIPTS)!r}); from sh_placa.como_python import rodar; "
              f"sys.exit(rodar({list(argv)!r}))")
    return subprocess.run([sys.executable, "-c", codigo], input=entrada, capture_output=True, text=True, timeout=60)


def test_menos_c_com_os_argumentos():
    r = _como_python("-c", "import sys; print(sys.argv)", "a", "b c")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "['-c', 'a', 'b c']"


def test_o_codigo_pelo_stdin_e_o_main_de_verdade():
    """O agente vai pelo stdin (``python3 - comando``); uma classe do código acha o módulo dela (a dataclass)."""
    codigo = ("import sys\nfrom dataclasses import dataclass\n@dataclass\nclass A:\n    x: int\n"
              "print(sys.argv, A(3), __name__)\n")
    r = _como_python("-u", "-I", "-", "estado", entrada=codigo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "['-', 'estado'] A(x=3) __main__"


def test_um_script_com_a_pasta_dele_no_path(tmp_path):
    (tmp_path / "vizinho.py").write_text("VALOR = 42\n")
    script = tmp_path / "programa.py"
    script.write_text("import sys, vizinho\nprint(__name__, sys.argv[1:], vizinho.VALOR)\nsys.exit(5)\n")
    r = _como_python(str(script), "x")
    assert r.returncode == 5, r.stderr
    assert r.stdout.strip() == "__main__ ['x'] 42"


def test_menos_m():
    r = _como_python("-m", "json.tool", entrada='{"a": 1}')
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"a": 1}


@pytest.mark.parametrize("argv", [["-X", "dev", "-c", "pass"], [], ["-c"]])
def test_o_que_nao_tem_sai_com_2(argv):
    r = _como_python(*argv)
    assert r.returncode == 2 and "uso: python" in r.stderr


def test_o_agente_responde_por_ele():
    """O agente local do pacote: ``shan_agente.py versao`` pelo :func:`rodar`, como o ``TransporteLocal`` o roda."""
    r = _como_python(str(AGENTE), "versao")
    assert r.returncode == 0, r.stderr
    assert "protocolo" in json.loads(r.stdout.splitlines()[-1])


def test_fora_do_pacote_nada_muda(monkeypatch):
    monkeypatch.setenv(como_python.VARIAVEL, "1")
    assert como_python.ambiente() == {} and not como_python.pedido()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert como_python.ambiente() == {como_python.VARIAVEL: "1"} and como_python.pedido()
    assert not como_python.pedido({})


def _pacote(tmp_path: Path, versao_do_pacote: str, commits: list[str]) -> Path:
    (tmp_path / "firmware").mkdir()
    (tmp_path / "firmware" / "VERSAO").write_text(versao_do_pacote + "\n")
    (tmp_path / versao.ARQUIVO_DOS_COMMITS).write_text("".join(c + "\n" for c in commits))
    return tmp_path


def test_a_versao_do_firmware_no_pacote(tmp_path):
    """No pacote, sem o ``git``: a placa enviada de um commit com o mesmo firmware vale; outra, ou com ``-dirty``,
    dá a do pacote (e a interface oferece a atualização)."""
    mesmo, outro = "9b0ae82" + "0" * 33, "1234567" + "f" * 33
    pacote = _pacote(tmp_path, "v0.9-12-gabcdef0", [mesmo, "abcdef0" + "1" * 33])
    assert versao.firmware_do_aplicativo("v0.8-137-g9b0ae82", pacote=pacote) == "v0.8-137-g9b0ae82"
    assert versao.firmware_do_aplicativo("v0.8-137-g9b0ae82-dirty", pacote=pacote) == "v0.9-12-gabcdef0"
    assert versao.firmware_do_aplicativo(outro[:7], pacote=pacote) == "v0.9-12-gabcdef0"
    assert versao.firmware_do_aplicativo(None, pacote=pacote) == "v0.9-12-gabcdef0"
    assert versao.firmware_do_aplicativo("v0.8.0", pacote=pacote) == "v0.9-12-gabcdef0"
