"""O agente da placa (``firmware/agente/shan_agente.py``) sobre um sistema de arquivos falso de BeagleBone (o do
simulador): cada campo lido certo, o que falta vira null sem erro, o comando desconhecido, e as restrições da placa
(só a biblioteca padrão e a sintaxe do Python 3.7)."""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sh_placa.simulador import SERIE_SIMULADA, VERSAO_SIMULADA, montar_sistema_falso

AGENTE = Path(__file__).resolve().parents[1] / "firmware" / "agente" / "shan_agente.py"


def rodar(*argv, raiz=None, pasta=None):
    ambiente = dict(os.environ)
    if raiz is not None:
        ambiente["SHAN_RAIZ"] = str(raiz)
    if pasta is not None:
        ambiente["SHAN_PASTA"] = str(pasta)
    r = subprocess.run([sys.executable, str(AGENTE), *argv], capture_output=True, text=True, env=ambiente, timeout=30)
    return r.returncode, json.loads(r.stdout)


@pytest.fixture
def placa(tmp_path):
    return montar_sistema_falso(tmp_path)


def test_estado_le_cada_campo(placa):
    raiz, pasta = placa
    rc, e = rodar("estado", raiz=raiz, pasta=pasta)
    assert rc == 0 and e["protocolo"] == 1 and e["comando"] == "estado"
    assert e["placa"] == {"nome": "A335BNLT", "revisao": "00C0", "serie": SERIE_SIMULADA,
                          "modelo": "TI AM335x BeagleBone Black"}
    assert e["sistema"] == "BeagleBoard.org Debian Buster IoT Image 2020-04-06"
    assert e["kernel"] == "4.19.94-ti-r42" and e["ligada_s"] == 8040.52 and e["carga"] == [0.31, 0.24, 0.18]
    assert e["memoria_disponivel_kib"] == 319488 and e["temperatura_c"] == 52.0
    assert e["pru"] == {"estado": "offline", "firmware": "am335x-pru0-fw", "nome": "4a334000.pru"}   # entre capturas
    assert all(p["certo"] for p in e["pinos"].values()) and set(e["pinos"]) == {"P9_28", "P9_29", "P9_30", "P9_31"}
    assert e["memoria_dos_buffers"]["mem_496m"] is True
    assert e["firmware"] == {"firmware": VERSAO_SIMULADA, "python": ".".join(map(str, sys.version_info[:3])),
                             "compilado": True}
    assert e["capturas"]["quantidade"] == 2 and e["capturas"]["bytes"] == 20_480 + 8_192
    assert e["relogio"]["sincronizado"] is True and e["disco"]["total_kib"] > 0


def test_pelo_stdin_como_o_aplicativo_o_roda(placa):
    """O aplicativo manda o código do agente pelo stdin (``python3 -``, ``sh_placa.agente.TransporteSSH``). Com a
    ``SHAN_PASTA``, a pasta é a dela; sem, a ``~/firmware`` (o ``__file__`` é ``<stdin>``, e a pasta acima dele seria
    a de cima da pasta atual, sem aviso)."""
    raiz, pasta = placa
    home = pasta.parent
    for pasta_pedida in (str(pasta), None):
        ambiente = {**os.environ, "SHAN_RAIZ": str(raiz), "HOME": str(home)}
        ambiente.pop("SHAN_PASTA", None)
        if pasta_pedida is not None:
            ambiente["SHAN_PASTA"] = pasta_pedida
        r = subprocess.run([sys.executable, "-", "versao"], input=AGENTE.read_text(encoding="utf-8"),
                           capture_output=True, text=True, env=ambiente, cwd=raiz, timeout=30)
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["firmware"] == VERSAO_SIMULADA


def test_o_que_falta_vira_null(tmp_path):
    vazia = tmp_path / "vazia"
    vazia.mkdir()
    rc, e = rodar("estado", raiz=vazia, pasta=vazia)
    assert rc == 0
    assert e["placa"] == {"nome": None, "revisao": None, "serie": None, "modelo": None}
    assert e["pru"]["estado"] is None and e["memoria_dos_buffers"] == {"cmdline": None, "mem_496m": None}
    assert all(p["modo"] is None and p["certo"] is None for p in e["pinos"].values())
    assert e["firmware"]["firmware"] is None and e["firmware"]["compilado"] is False
    assert e["capturas"]["quantidade"] == 0 and e["relogio"]["sincronizado"] is None


def test_eeprom_invalida_cai_no_modelo(placa):
    raiz, pasta = placa
    (raiz / "sys/bus/nvmem/devices/0-00500/nvmem").write_bytes(b"\x00" * 28)
    _, e = rodar("estado", raiz=raiz, pasta=pasta)
    assert e["placa"]["serie"] is None and e["placa"]["modelo"] == "TI AM335x BeagleBone Black"


def test_versao_e_comando_desconhecido(placa):
    raiz, pasta = placa
    rc, v = rodar("versao", raiz=raiz, pasta=pasta)
    assert rc == 0 and v["firmware"] == VERSAO_SIMULADA and v["agente"] == "1"
    rc, erro = rodar("formatar_o_disco", raiz=raiz, pasta=pasta)
    assert rc == 2 and "comando desconhecido" in erro["erro"] and erro["protocolo"] == 1
    rc, erro = rodar(raiz=raiz, pasta=pasta)
    assert rc == 2


def test_so_biblioteca_padrao_e_sintaxe_do_python_37():
    """A placa não tem pip, e a imagem dela pode trazer um Python antigo."""
    texto = AGENTE.read_text(encoding="utf-8")
    arvore = ast.parse(texto, feature_version=(3, 7))
    modulos = {a.name.split(".")[0] for n in ast.walk(arvore) if isinstance(n, ast.Import) for a in n.names}
    modulos |= {n.module.split(".")[0] for n in ast.walk(arvore) if isinstance(n, ast.ImportFrom) and n.module}
    assert modulos <= set(sys.stdlib_module_names) | {"__future__"}, modulos
    assert texto.startswith("#!/usr/bin/env python3\n") and os.access(AGENTE, os.X_OK)
