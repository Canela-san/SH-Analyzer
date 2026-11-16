"""O agente da placa (``firmware/agente/shan_agente.py``) sobre um sistema de arquivos falso de BeagleBone (o do
simulador): cada campo lido certo, o que falta vira null sem erro, cada conferência da saúde (com os ``uEnv.txt``
estranhos), o resumo do cabeçalho de cada versão igual ao do motor, os logs filtrados, os comandos errados, os
contratos com o firmware (o ``ler_adc.c``, o ``setup.sh``, o ``memoria_pru.h``) e as restrições da placa (só a
biblioteca padrão e a sintaxe do Python 3.7)."""

import ast
import importlib.util
import json
import os
import re
import struct
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from capturas_sinteticas import FAIXA, escrever_bin
from sh_placa.simulador import (
    CARTAO_KIB,
    CENARIOS,
    LIVRE_NORMAL_KIB,
    SERIE_SIMULADA,
    VERSAO_SIMULADA,
    montar_sistema_falso,
)
from supraharmonicos import cabecalho as motor

RAIZ_DO_PROJETO = Path(__file__).resolve().parents[1]
AGENTE = RAIZ_DO_PROJETO / "firmware" / "agente" / "shan_agente.py"


def rodar(*argv, raiz=None, pasta=None):
    ambiente = dict(os.environ)
    if raiz is not None:
        ambiente["SHAN_RAIZ"] = str(raiz)
    if pasta is not None:
        ambiente["SHAN_PASTA"] = str(pasta)
    r = subprocess.run([sys.executable, str(AGENTE), *argv], capture_output=True, text=True, env=ambiente, timeout=30)
    assert r.stderr == "", r.stderr
    return r.returncode, json.loads(r.stdout)


@pytest.fixture(scope="module")
def agente():
    """O agente como módulo, para as conferências sobre fatos montados à mão."""
    spec = importlib.util.spec_from_file_location("shan_agente", AGENTE)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def placa(tmp_path):
    return montar_sistema_falso(tmp_path)


# ------------------------------------------------------------------ o estado

def test_estado_le_cada_campo(placa):
    raiz, pasta = placa
    rc, e = rodar("estado", raiz=raiz, pasta=pasta)
    assert rc == 0 and e["protocolo"] == 1 and e["comando"] == "estado" and e["agente"] == "3"
    assert e["placa"] == {"nome": "A335BNLT", "revisao": "00C0", "serie": SERIE_SIMULADA,
                          "modelo": "TI AM335x BeagleBone Black"}
    assert e["sistema"] == "BeagleBoard.org Debian Buster IoT Image 2020-04-06"
    assert e["kernel"] == "4.19.94-ti-r42" and e["ligada_s"] == 8040.52 and e["carga"] == [0.31, 0.24, 0.18]
    assert e["memoria_disponivel_kib"] == 319488 and e["temperatura_c"] == 52.0
    assert e["pru"] == {"estado": "offline", "firmware": "am335x-pru0-fw", "nome": "4a334000.pru",   # entre capturas
                        "remoteproc_da_pru0": "/sys/class/remoteproc/remoteproc1"}
    assert all(p["certo"] for p in e["pinos"].values()) and set(e["pinos"]) == {"P9_28", "P9_29", "P9_30", "P9_31"}
    # Como o debian vê o /proc/iomem (os endereços zerados): não dá para saber, e o ler_adc confere como root.
    assert e["memoria_dos_buffers"]["mem_496m"] is True and e["memoria_dos_buffers"]["ram_sobre_os_buffers"] is None
    assert e["firmware"] == {"firmware": VERSAO_SIMULADA, "python": ".".join(map(str, sys.version_info[:3])),
                             "compilado": True, "ler_adc_antigo": False, "fw_pru": True, "fw_pru_antigo": False,
                             "fw_pru_instalado": "igual", "protocolo_da_pru": 5}
    binarios = sorted(pasta.glob("*.bin"))
    assert e["capturas"]["quantidade"] == len(binarios) == 3                    # a conferência e duas da tomada
    assert e["capturas"]["bytes"] == sum(f.stat().st_size for f in binarios)
    relogio = e["relogio"]
    assert (relogio["utc"], relogio["sincronizado"], relogio["fonte"]) == (pytest.approx(time.time(), abs=30), True,
                                                                            "timesyncd")
    assert set(relogio) == {"utc", "sincronizado", "fonte", "desde_o_inicio_s"}       # test_o_relogio confere o último
    assert e["disco"] == {"total_kib": CARTAO_KIB, "livre_kib": LIVRE_NORMAL_KIB}        # o cartão de 4 GB dela


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
    rc, e = rodar("saude", raiz=vazia, pasta=vazia)
    assert rc == 0
    assert e["placa"] == {"nome": None, "revisao": None, "serie": None, "modelo": None}
    assert e["pru"] == {"estado": None, "firmware": None, "nome": None, "remoteproc_da_pru0": None}
    assert e["memoria_dos_buffers"] == {"cmdline": None, "mem_496m": None, "ram_sobre_os_buffers": None}
    assert all(p["modo"] is None and p["certo"] is None for p in e["pinos"].values())
    assert e["firmware"]["firmware"] is None and e["firmware"]["compilado"] is False and e["firmware"]["fw_pru"] is False
    assert e["firmware"]["fw_pru_instalado"] is None and e["firmware"]["protocolo_da_pru"] is None
    assert e["capturas"]["quantidade"] == 0 and e["relogio"]["sincronizado"] is None and e["relogio"]["fonte"] is None
    assert e["uenv"] is None and e["overlays"] is None and e["dtbo_da_pru"] == []
    assert set(e["ferramentas"].values()) == {None}
    assert [c["codigo"] for c in e["conferencias"]] == [
        "pru_ausente", "nao_compilado", "pinos_desconhecidos", "mem_desconhecida", "versao_desconhecida",
        "uenv_ausente", "ferramentas"]


def test_eeprom_invalida_cai_no_modelo(placa):
    raiz, pasta = placa
    (raiz / "sys/bus/nvmem/devices/0-00500/nvmem").write_bytes(b"\x00" * 28)
    _, e = rodar("estado", raiz=raiz, pasta=pasta)
    assert e["placa"]["serie"] is None and e["placa"]["modelo"] == "TI AM335x BeagleBone Black"


def test_o_relogio_do_kernel(agente, monkeypatch, tmp_path):
    """Na placa (a raiz de verdade), o relógio vem do ``adjtimex``, como o ``relogio_sincronizado`` do cabeçalho; com
    a raiz falsa, o do kernel é deste computador e não vale: vale o arquivo do timesyncd da árvore."""
    if sys.platform.startswith("linux"):
        assert agente._relogio_do_kernel() in (True, False)        # o adjtimex de verdade, deste computador
    monkeypatch.delenv("SHAN_RAIZ", raising=False)
    monkeypatch.setattr(agente, "_relogio_do_kernel", lambda: False)
    assert (agente.relogio()["sincronizado"], agente.relogio()["fonte"]) == (False, "adjtimex")

    def nao_pergunte():
        raise AssertionError("com a raiz falsa, o relógio do kernel é o deste computador")

    monkeypatch.setattr(agente, "_relogio_do_kernel", nao_pergunte)
    monkeypatch.setenv("SHAN_RAIZ", str(tmp_path))
    assert (agente.relogio()["sincronizado"], agente.relogio()["fonte"]) == (None, None)


# ------------------------------------------------------------------ a saúde

CODIGOS_DE_CADA_CENARIO = {
    "normal": [], "pru_com_falha": ["pru_com_falha"], "pinos_errados": ["pinos"], "sem_mem_496m": ["mem_496m"],
    "firmware_antigo": [], "sem_compilar": ["nao_compilado"], "pru_desatualizada": ["pru_desatualizada"],
    "audio_hdmi": ["audio_hdmi", "pinos"], "sem_overlay_da_pru": ["pru_ausente"], "adc_mudo": ["adc_mudo"],
    "disco_cheio": ["disco_cheio"], "conexao_instavel": [], "relogio_errado": [],
}
"""O que a placa diz de si em cada cenário (o firmware de outra versão é o computador que vê: sh_placa/estado.py)."""


@pytest.mark.parametrize("cenario", CENARIOS)
def test_a_saude_de_cada_cenario(tmp_path, cenario):
    raiz, pasta = montar_sistema_falso(tmp_path, cenario)
    rc, s = rodar("saude", raiz=raiz, pasta=pasta)
    assert rc == 0 and s["comando"] == "saude"
    codigos = [c["codigo"] for c in s["conferencias"] if c["nivel"] != "info"]
    assert codigos == CODIGOS_DE_CADA_CENARIO[cenario]
    assert all(c["correcao"] for c in s["conferencias"] if c["nivel"] == "erro")      # todo erro diz como corrigir
    infos = ["relogio_sem_ntp", "capturas"] if cenario == "relogio_errado" else ["capturas"]
    assert [c["codigo"] for c in s["conferencias"] if c["nivel"] == "info"] == infos
    assert ("AM335X-PRU-RPROC-4-19-TI-00A0" in s["overlays"]) is (cenario != "sem_overlay_da_pru")
    assert "AM335X-PRU-RPROC-4-19-TI-00A0" in s["dtbo_da_pru"] and s["ferramentas"]["make"] == "/usr/bin/make"


def test_a_saude_diz_como_corrigir(tmp_path):
    """O que a correção diz depende do que a placa tem: o overlay certo para o kernel dela, e se o uEnv.txt já tem o
    mem=496M (então é só reiniciar)."""
    raiz, pasta = montar_sistema_falso(tmp_path / "sem_pru", "sem_overlay_da_pru")
    (pru,) = [c for c in rodar("saude", raiz=raiz, pasta=pasta)[1]["conferencias"] if c["codigo"] == "pru_ausente"]
    assert "uboot_overlay_pru=/lib/firmware/AM335X-PRU-RPROC-4-19-TI-00A0.dtbo" in pru["correcao"]
    raiz, pasta = montar_sistema_falso(tmp_path / "boot", "normal")
    (raiz / "proc/cmdline").write_text("console=ttyO0,115200n8 root=/dev/mmcblk1p1 ro\n")    # o boot de antes da linha
    (mem,) = [c for c in rodar("saude", raiz=raiz, pasta=pasta)[1]["conferencias"] if c["codigo"] == "mem_496m"]
    assert mem["correcao"] == "O /boot/uEnv.txt já tem: reiniciar a placa."


def fatos_bons(tmp_path):
    """Os fatos da placa simulada boa, para mudar um de cada vez."""
    raiz, pasta = montar_sistema_falso(tmp_path)
    return rodar("saude", raiz=raiz, pasta=pasta)[1]


def codigos(agente, fatos):
    return [c["codigo"] for c in agente.conferir(fatos) if c["codigo"] != "capturas"]


@pytest.mark.parametrize("mudar, esperado", [
    (lambda f: f["pru"].update(estado=None, nome=None, remoteproc_da_pru0="/sys/class/remoteproc/remoteproc2"),
     ["pru_em_outro_remoteproc"]),
    (lambda f: f["pru"].update(nome="wkup_m3"), ["pru_outro_nucleo"]),
    (lambda f: f["pru"].update(firmware="am335x-pru0-rc-encoder-fw"), ["pru_outro_firmware"]),
    (lambda f: f["pru"].update(estado="suspended"), ["pru_com_falha"]),
    (lambda f: f["firmware"].update(ler_adc_antigo=True), ["compilacao_antiga"]),
    (lambda f: f["firmware"].update(ler_adc_antigo=True, fw_pru_antigo=True), ["compilacao_antiga"]),
    (lambda f: f["firmware"].update(fw_pru_instalado="ausente"), ["pru_desatualizada"]),
    (lambda f: f["firmware"].update(firmware=None), ["versao_desconhecida"]),
    (lambda f: f["memoria_dos_buffers"].update(ram_sobre_os_buffers=True), ["ram_sobre_os_buffers"]),
    (lambda f: f["uenv"].update(mem_496m=False), ["mem_496m_no_proximo_boot"]),
    (lambda f: f["uenv"]["chaves"].update(uname_r="5.10.168-ti-r72"), ["kernel_trocado"]),
    (lambda f: [f["uenv"]["chaves"].pop(k) for k in ("disable_uboot_overlay_audio", "disable_uboot_overlay_video")],
     ["audio_hdmi_no_proximo_boot"]),
    (lambda f: f["uenv"]["chaves"].update(uboot_overlay_pru="/lib/firmware/AM335X-PRU-UIO-00A0.dtbo"),
     ["overlay_da_pru"]),
    (lambda f: f["uenv"]["chaves"].update(uboot_overlay_pru="/lib/firmware/AM335X-PRU-RPROC-4-14-TI-00A0.dtbo"),
     ["overlay_da_pru"]),
    (lambda f: f["uenv"]["chaves"].update(uboot_overlay_pru="/lib/firmware/NAO-EXISTE.dtbo"), ["overlay_da_pru"]),
    (lambda f: f["uenv"]["chaves"].update(enable_uboot_overlays="0"), ["overlay_da_pru"]),
    (lambda f: f["uenv"].update(linhas_estranhas=[7]), ["uenv_estranho"]),
    (lambda f: f["disco"].update(livre_kib=500 * 1024), ["disco"]),
    (lambda f: f["disco"].update(livre_kib=40 * 1024), ["disco_cheio"]),
    (lambda f: f.update(temperatura_c=81.0), ["temperatura"]),
    (lambda f: f.update(carga=[2.1, 1.0, 0.5]), ["carga"]),
    (lambda f: f.update(memoria_disponivel_kib=20_000), ["memoria"]),
    (lambda f: f["ferramentas"].update(clpru=None, make=None), ["ferramentas"]),
    (lambda f: f["ferramentas"].update(dtc=None, journalctl=None), []),          # o setup.sh não precisa delas
    (lambda f: f["relogio"].update(sincronizado=False), ["relogio_sem_ntp"]),
])
def test_cada_conferencia(agente, tmp_path, mudar, esperado):
    fatos = fatos_bons(tmp_path)
    assert codigos(agente, fatos) == []
    mudar(fatos)
    assert codigos(agente, fatos) == esperado


def test_os_textos_das_conferencias(agente, tmp_path):
    fatos = fatos_bons(tmp_path)
    fatos["ferramentas"].update(clpru=None, make=None, gcc=None)
    fatos["uenv"]["chaves"]["uboot_overlay_pru"] = "/lib/firmware/AM335X-PRU-RPROC-4-14-TI-00A0.dtbo"
    fatos["disco"]["livre_kib"] = 40 * 1024
    por_codigo = {c["codigo"]: c for c in agente.conferir(fatos)}
    assert por_codigo["ferramentas"]["correcao"] == "sudo apt install build-essential ti-pru-cgt-installer"
    assert "o do kernel 4.14, e a placa roda o 4.19.94-ti-r42" in por_codigo["overlay_da_pru"]["texto"]
    assert "AM335X-PRU-RPROC-4-19-TI-00A0.dtbo" in por_codigo["overlay_da_pru"]["correcao"]
    assert por_codigo["disco_cheio"]["texto"] == "O cartão está cheio: 40 MiB livres, ~52 s de captura a 400 kS/s."
    assert [c["nivel"] for c in agente.conferir(fatos)] == ["erro", "aviso", "aviso", "info"]
    fatos["carga"] = [2.14, 1.0, 0.5]
    (carga,) = [c for c in agente.conferir(fatos) if c["codigo"] == "carga"]
    assert "(carga de 2,1 num núcleo só)" in carga["texto"]


def test_os_pinos_sem_o_cape_universal(agente, tmp_path):
    fatos = fatos_bons(tmp_path)
    for info in fatos["pinos"].values():
        info.update(modo=None, certo=None)
    (pinos,) = [c for c in agente.conferir(fatos) if c["codigo"] == "pinos_desconhecidos"]
    assert pinos["correcao"].startswith("Conferir se a imagem tem o cape universal")
    del fatos["uenv"]["chaves"]["enable_uboot_cape_universal"]
    (pinos,) = [c for c in agente.conferir(fatos) if c["codigo"] == "pinos_desconhecidos"]
    assert pinos["correcao"].startswith("Pôr enable_uboot_cape_universal=1")


@pytest.mark.parametrize("texto, chaves, estranhas, mem", [
    # O da placa de verdade (15/11/2026): o mem=496M no optargs.
    ("uname_r=4.19.94-ti-r42\nenable_uboot_overlays=1\ncmdline=coherent_pool=1M quiet\noptargs=mem=496M\n",
     {"uname_r": "4.19.94-ti-r42", "enable_uboot_overlays": "1", "cmdline": "coherent_pool=1M quiet",
      "optargs": "mem=496M"}, [], True),
    # Editado no Windows (CRLF), com espaços em volta do "=" e o mem=496M no cmdline.
    ("# comentário\r\n  enable_uboot_overlays = 1 \r\n\r\ncmdline=coherent_pool=1M mem=496M quiet\r\n",
     {"enable_uboot_overlays": "1", "cmdline": "coherent_pool=1M mem=496M quiet"}, [], True),
    # A chave repetida: vale a última, como no u-boot; e o mem=496M comentado não vale.
    ("cmdline=quiet\n#cmdline=quiet mem=496M\ncmdline=quiet net.ifnames=0\n",
     {"cmdline": "quiet net.ifnames=0"}, [], False),
    # Uma linha sem "=", uma chave com espaço e uma com o BOM de um editor: ficam de fora, contadas.
    ("﻿uname_r=4.19\nisto não é chave\nmem total=496M\nenable_uboot_overlays=1\n",
     {"enable_uboot_overlays": "1"}, [1, 2, 3], False),
    # O valor com "=" dentro (o cmdline do eMMC flasher).
    ("cmdline=init=/opt/scripts/tools/eMMC/init-eMMC-flasher-v3.sh\n",
     {"cmdline": "init=/opt/scripts/tools/eMMC/init-eMMC-flasher-v3.sh"}, [], False),
])
def test_os_uenv_estranhos(agente, tmp_path, monkeypatch, texto, chaves, estranhas, mem):
    (tmp_path / "boot").mkdir()
    (tmp_path / "boot" / "uEnv.txt").write_bytes(texto.encode("utf-8"))
    monkeypatch.setenv("SHAN_RAIZ", str(tmp_path))
    assert agente.uenv() == {"chaves": chaves, "linhas_estranhas": estranhas, "mem_496m": mem}


@pytest.mark.parametrize("iomem, esperado", [
    ("80000000-9fffffff : System RAM\n  80008000-80cfffff : Kernel code\n", True),        # sem o mem=496M, como root
    ("80000000-9effffff : System RAM\n4a300000-4a37ffff : pruss\n", False),               # com ele
    ("80000000-9f3fffff : System RAM\n", True),                                            # 4 MB a menos não basta
    ("00000000-00000000 : System RAM\n00000000-00000000 : pruss\n", None),                 # como o debian vê
    ("", None),
])
def test_a_ram_sobre_os_buffers(agente, tmp_path, monkeypatch, iomem, esperado):
    (tmp_path / "proc").mkdir()
    (tmp_path / "proc" / "iomem").write_text(iomem)
    monkeypatch.setenv("SHAN_RAIZ", str(tmp_path))
    assert agente.ram_sobre_os_buffers() is esperado


# ------------------------------------------------------------------ as capturas

def captura(caminho, versao, **kw):
    t = np.arange(4096) / 200_000.0
    caminho.parent.mkdir(parents=True, exist_ok=True)
    return escrever_bin(caminho, [np.sin(2 * np.pi * 60 * t), 0.5 * np.sin(2 * np.pi * 60 * t)],
                        fs_total=400_000, versao=versao, **kw)


@pytest.mark.parametrize("versao", range(1, 10))
def test_o_resumo_do_cabecalho_e_o_do_motor(tmp_path, versao):
    """O agente lê o cabeçalho sozinho (a placa não tem o NumPy): o resumo dele tem de ser o que o motor lê, em cada
    versão do formato."""
    pasta = tmp_path / "firmware"
    arquivo = captura(pasta / "rede.bin", versao, titulo="Rede da casa", descricao="canal 1 na tomada",
                      integridade=(3, 1, 2) if versao >= 4 else (0, 0, 0), versao_firmware="v0.8-137-g9b0ae82")
    rc, r = rodar("capturas", raiz=tmp_path, pasta=pasta)
    assert rc == 0 and r["total"] == 1
    (item,) = r["capturas"]
    c, m = item["cabecalho"], motor.ler_cabecalho(arquivo)
    assert (item["arquivo"], item["bytes"]) == ("rede.bin", arquivo.stat().st_size)
    assert c["versao"] == m.versao_cabecalho == versao and c["crc_valido"] is m.crc32_valido is True
    assert (c["titulo"], c["descricao"]) == (m.titulo, m.descricao)
    assert (c["taxa_hz"], c["canais"], c["amostras"], c["blocos"]) == (
        m.frequencia_hz, list(m.lista_canais), m.total_amostras_gravadas, m.blocos_gravados)
    assert c["duracao_s"] == pytest.approx(m.duracao_real_segundos) and c["bytes_por_amostra"] == m.bytes_por_amostra
    assert c["duracao_pedida_s"] == pytest.approx(m.duracao_pedida_segundos)
    assert (c["amostras_atrasadas"], c["buffers_sobrescritos"], c["quadros_sdo_ruido"]) == (
        m.amostras_atrasadas, m.buffers_sobrescritos, m.quadros_preambulo_ruim)
    assert c["versao_firmware"] == (m.versao_firmware or None) and c["relogio_sincronizado"] == m.relogio_sincronizado
    assert c["inicio_utc"] == pytest.approx(m.timestamp_unix + (m.timestamp_ns or 0) / 1e9)
    assert (c["id"], c["maquina"]) == ((m.id_captura or None), (m.hostname or None))
    assert c["completa"] is True and c["bytes_esperados"] == arquivo.stat().st_size and c["final"] is True
    if versao >= 9:                       # o sinal mexeu nos dois canais: nenhum parado (o mínimo e o máximo do motor)
        assert c["canais_parados"] == [] and m.codigo_minimo_por_canal != m.codigo_maximo_por_canal
    else:
        assert c["canais_parados"] is None


def test_as_capturas_estragadas(tmp_path):
    pasta = tmp_path / "firmware"
    captura(pasta / "crc_errado.bin", 9, crc_valido=False)
    cortada = captura(pasta / "cortada.bin", 9)
    cortada.write_bytes(cortada.read_bytes()[:-1000])                    # a transferência que parou no meio
    curta = captura(pasta / "curta.bin", 9)
    curta.write_bytes(curta.read_bytes()[:3000])                        # nem o cabeçalho inteiro
    (pasta / "antiga.bin").write_bytes(bytes(5000))                     # de antes do cabeçalho
    captura(pasta / "interrompida.bin", 9, total_amostras=0, blocos=0)  # sem o cabeçalho final (o ler_adc morto)
    _, r = rodar("capturas", raiz=tmp_path, pasta=pasta)
    por_nome = {c["arquivo"]: c["cabecalho"] for c in r["capturas"]}
    assert por_nome["crc_errado.bin"]["crc_valido"] is False and por_nome["crc_errado.bin"]["completa"] is True
    assert por_nome["cortada.bin"]["crc_valido"] is True and por_nome["cortada.bin"]["completa"] is False
    assert por_nome["curta.bin"]["crc_valido"] is False and por_nome["curta.bin"]["versao"] == 9
    assert por_nome["antiga.bin"] is None
    assert por_nome["interrompida.bin"]["final"] is False and por_nome["interrompida.bin"]["completa"] is None
    assert motor.ler_cabecalho(pasta / "crc_errado.bin").crc32_valido is False


def test_as_capturas_das_coletas(tmp_path):
    """As pastas que o coletar.sh cria na pasta do firmware (a coleta com o resumo.csv, as sondas em capturas/), até 3
    níveis; a do agente e as ocultas ficam de fora."""
    pasta = tmp_path / "firmware"
    for rel in ("solta.bin", "CAMPANHA_2026-11-15_1000/E_0930.bin", "capturas/fluke_i30/p01.bin",
                "capturas/fluke_i30/descartadas/p01_a.bin", "capturas/fluke_i30/descartadas/velhas/fundo.bin",
                "agente/teste.bin", ".lixeira/apagada.bin"):
        captura(pasta / rel, 9)
    coleta = pasta / "CAMPANHA_2026-11-15_1000" / "resumo.csv"
    coleta.write_text("parte,arquivo,amostras_atrasadas,sinal\nE,E_0930.bin,0,ok\nE,\"E,0931.bin\",2,fraco\n")
    (pasta / "capturas" / "fluke_i30" / "pontos_coletados.csv").write_text("ponto,status\n1,aceito\n")
    _, r = rodar("capturas", raiz=tmp_path, pasta=pasta)
    assert sorted(c["arquivo"] for c in r["capturas"]) == [
        "CAMPANHA_2026-11-15_1000/E_0930.bin", "capturas/fluke_i30/descartadas/p01_a.bin",
        "capturas/fluke_i30/p01.bin", "solta.bin"]
    coletas = {c["arquivo"]: c for c in r["coletas"]}
    resumo = coletas["CAMPANHA_2026-11-15_1000/resumo.csv"]
    assert resumo["colunas"] == ["parte", "arquivo", "amostras_atrasadas", "sinal"]
    assert resumo["linhas"] == [["E", "E_0930.bin", "0", "ok"], ["E", "E,0931.bin", "2", "fraco"]]
    assert coletas["capturas/fluke_i30/pontos_coletados.csv"]["linhas"] == [["1", "aceito"]]
    assert resumo["cortado"] is False and resumo["modificado"] > 0


def test_as_capturas_mais_recentes_primeiro(tmp_path):
    pasta = tmp_path / "firmware"
    for i, nome in enumerate(("a.bin", "b.bin", "c.bin")):
        os.utime(captura(pasta / nome, 9), (1_794_000_000 + i * 60, 1_794_000_000 + i * 60))
    _, r = rodar("capturas", raiz=tmp_path, pasta=pasta)
    assert [c["arquivo"] for c in r["capturas"]] == ["c.bin", "b.bin", "a.bin"]
    _, e = rodar("estado", raiz=tmp_path, pasta=pasta)
    assert [c["nome"] for c in e["capturas"]["recentes"]] == ["c.bin", "b.bin", "a.bin"]
    _, sem = rodar("capturas", raiz=tmp_path, pasta=tmp_path / "nao_existe")
    assert (sem["capturas"], sem["coletas"], sem["total"]) == (None, None, None)


def parada(caminho, *volts, quando=1_794_000_000):
    """Uma captura v9 com cada canal parado em ``volts`` (o ADC mudo: o código 0, a -FAIXA/2), na hora ``quando``."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    escrever_bin(caminho, [np.full(4096, v) for v in volts], canais=tuple(range(len(volts))),
                 grandezas=(0,) * len(volts), sondas=("",) * len(volts), versao=9)
    os.utime(caminho, (quando, quando))
    return caminho


def test_o_adc_mudo_na_captura_mais_recente(tmp_path):
    """O ler_adc grava o mínimo e o máximo de cada canal no cabeçalho final: um canal em que os dois são iguais ficou
    parado. Em 0 nos canais todos é o ADC mudo (a placa de aquisição sem alimentação, os pinos sem configuração); vale
    a captura mais recente, a que diz como a placa está agora."""
    raiz, pasta = montar_sistema_falso(tmp_path)
    mudo = parada(pasta / "conferir_1015.bin", -FAIXA / 2, -FAIXA / 2, quando=time.time() + 60)
    _, s = rodar("saude", raiz=raiz, pasta=pasta)
    assert s["ultima_captura"]["arquivo"] == "conferir_1015.bin"
    assert s["ultima_captura"]["cabecalho"]["canais_parados"] == [{"canal": 0, "codigo": 0}, {"canal": 1, "codigo": 0}]
    (adc,) = [c for c in s["conferencias"] if c["codigo"] in ("adc_mudo", "sinal_parado")]
    assert (adc["nivel"], adc["codigo"]) == ("aviso", "adc_mudo")
    assert adc["texto"] == "A captura mais recente (conferir_1015.bin) ficou em 0 em todas as amostras: o ADC não respondeu."
    assert "fonte de 5 V" in adc["correcao"]
    _, r = rodar("capturas", raiz=raiz, pasta=pasta)
    assert {c["arquivo"]: c["cabecalho"] for c in r["capturas"]}["conferir_1015.bin"]["canais_parados"] == [
        {"canal": 0, "codigo": 0}, {"canal": 1, "codigo": 0}]

    # Um canal só, no fundo de escala: a entrada saturada (ou o ADC travado), e não mudo.
    escrever_bin(mudo, [np.sin(np.arange(4096) / 10), np.full(4096, FAIXA)], versao=9)
    os.utime(mudo, (time.time() + 60,) * 2)
    _, s = rodar("saude", raiz=raiz, pasta=pasta)
    (adc,) = [c for c in s["conferencias"] if c["codigo"] in ("adc_mudo", "sinal_parado")]
    assert adc["codigo"] == "sinal_parado" and adc["texto"] == (
        "Na captura mais recente (conferir_1015.bin), o sinal do canal 1 ficou parado em 0xFFFF: a entrada saturada "
        "ou o ADC travado.")

    # Uma captura boa depois da muda: a placa voltou, e a muda é só uma captura antiga.
    escrever_bin(pasta / "rede_1020.bin", [np.sin(np.arange(4096) / 10)] * 2, versao=9)
    os.utime(pasta / "rede_1020.bin", (time.time() + 120,) * 2)
    _, s = rodar("saude", raiz=raiz, pasta=pasta)
    assert s["ultima_captura"]["arquivo"] == "rede_1020.bin"
    assert not [c for c in s["conferencias"] if c["codigo"] in ("adc_mudo", "sinal_parado")]


def test_o_cartao_e_o_relogio_da_placa_simulada(placa):
    """Na raiz falsa, o que a árvore de arquivos não imita: o cartão (o tamanho, menos o sistema e os arquivos da pasta
    do firmware: apagar uma captura libera o espaço dela) e a hora (a deste computador mais o desvio)."""
    raiz, pasta = placa
    (raiz / "run" / "simulador").mkdir(parents=True, exist_ok=True)
    (raiz / "run" / "simulador" / "disco").write_text("3600000 3500000\n")
    (raiz / "run" / "simulador" / "relogio").write_text("-191607.5\n")

    def ocupado_kib():
        return sum(f.stat().st_size for f in pasta.rglob("*") if f.is_file()) // 1024

    _, e = rodar("estado", raiz=raiz, pasta=pasta)
    assert e["disco"] == {"total_kib": 3_600_000, "livre_kib": 100_000 - ocupado_kib()}
    assert e["relogio"]["utc"] == pytest.approx(time.time() - 191_607.5, abs=30)
    grande = pasta / "grande.bin"
    grande.write_bytes(bytes(5 * 1024 * 1024))
    assert rodar("estado", raiz=raiz, pasta=pasta)[1]["disco"]["livre_kib"] == 100_000 - ocupado_kib()
    grande.unlink()
    assert rodar("estado", raiz=raiz, pasta=pasta)[1]["disco"]["livre_kib"] == 100_000 - ocupado_kib()
    (raiz / "run" / "simulador" / "disco").write_text("3600000 3599990\n")                 # cheio: nunca negativo
    assert rodar("estado", raiz=raiz, pasta=pasta)[1]["disco"]["livre_kib"] == 0
    (raiz / "run" / "simulador" / "disco").write_text("estragado\n")                       # o disco deste computador
    assert rodar("estado", raiz=raiz, pasta=pasta)[1]["disco"]["total_kib"] > 0


# ------------------------------------------------------------------ o relógio e os logs

def test_o_relogio(placa):
    """A hora, e há quanto tempo o processo roda: com ela, o computador põe a diferença do relógio entre dois
    limites (sh_placa/estado.py). O processo começou depois do pedido e leu a hora antes de responder."""
    raiz, pasta = placa
    antes = time.time()
    rc, r = rodar("relogio", raiz=raiz, pasta=pasta)
    depois = time.time()
    assert rc == 0 and antes <= r["utc"] <= depois and (r["sincronizado"], r["fonte"]) == (True, "timesyncd")
    if sys.platform.startswith("linux"):
        assert 0 < r["desde_o_inicio_s"] and antes <= r["utc"] - r["desde_o_inicio_s"] <= r["utc"]
    else:
        assert r["desde_o_inicio_s"] is None
    (raiz / "run/systemd/timesync/synchronized").unlink()
    assert rodar("relogio", raiz=raiz, pasta=pasta)[1]["sincronizado"] is False


def test_os_logs_filtrados(placa):
    raiz, pasta = placa
    rc, r = rodar("logs", raiz=raiz, pasta=pasta)
    assert rc == 0
    kernel = [x["texto"] for x in r["kernel"]]
    assert kernel[0] == "remoteproc remoteproc1: stopped remote processor 4a334000.pru" and len(kernel) == 6
    assert kernel[-1].startswith("mmcblk1: error -110")                     # um erro do kernel entra sempre
    assert not any("usb 1-1" in t for t in kernel) and not any(t.startswith(" ") for t in kernel)
    agora = time.time()
    assert r["kernel"][1]["utc"] == pytest.approx(agora - 8040.52 + 2916.323129, abs=30)
    assert r["kernel"][1]["desde_o_boot_s"] == pytest.approx(2916.323129) and r["kernel"][-1]["nivel"] == 3
    diario = [(x["origem"], x["nivel"]) for x in r["diario"]]
    assert diario == [("sudo", 5), ("wpa_supplicant", 3)]                   # o ler_adc pelo sudo, e um erro
    assert r["diario"][0]["utc"] == 1794787260.0 and "ler_adc" in r["diario"][0]["texto"]
    assert [x["texto"] for x in rodar("logs", "2", raiz=raiz, pasta=pasta)[1]["kernel"]] == kernel[-2:]


def test_o_filtro_do_diario_vai_para_o_journalctl(placa):
    """O journalctl da imagem Buster não tem o --grep: o filtro vai pelos índices do diário, e o agente lê só o que
    vem."""
    raiz, pasta = placa
    pedido = raiz / "pedido.txt"
    (raiz / "bin" / "journalctl").write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{pedido}"\n')
    rodar("logs", raiz=raiz, pasta=pasta)
    assert pedido.read_text().split("\n")[:-1] == [
        "-o", "json", "--no-pager", "-b", "-n", "500",
        "SYSLOG_IDENTIFIER=sudo", "+", "PRIORITY=0", "PRIORITY=1", "PRIORITY=2", "PRIORITY=3"]
    (raiz / "bin" / "journalctl").unlink()
    (raiz / "dev" / "kmsg").unlink()
    _, r = rodar("logs", raiz=raiz, pasta=pasta)
    assert (r["kernel"], r["diario"]) == (None, None)


# ------------------------------------------------------------------ os comandos

def test_versao_e_comandos_errados(placa):
    raiz, pasta = placa
    rc, v = rodar("versao", raiz=raiz, pasta=pasta)
    assert rc == 0 and v["firmware"] == VERSAO_SIMULADA and v["agente"] == "3"
    rc, erro = rodar("formatar_o_disco", raiz=raiz, pasta=pasta)
    assert rc == 2 and "comando desconhecido" in erro["erro"] and erro["protocolo"] == 1
    assert "capturas, estado, logs, relogio, saude, versao" in erro["erro"]
    rc, erro = rodar(raiz=raiz, pasta=pasta)
    assert rc == 2
    for argv, trecho in ((("estado", "--tudo"), "não leva argumentos"), (("logs", "muitas"), "não é um número"),
                         (("logs", "0"), "de 1 a 1000"), (("logs", "5", "6"), "no máximo um")):
        rc, erro = rodar(*argv, raiz=raiz, pasta=pasta)
        assert rc == 2 and trecho in erro["erro"] and erro["comando"] == argv[0]


# ------------------------------------------------------------------ os contratos com o firmware

def test_os_contratos_com_o_firmware(agente):
    """O que o agente sabe do firmware é o que o firmware é: o remoteproc e os pinos do setup.sh e do ler_adc.c, a
    faixa dos buffers do memoria_pru.h e do setup.sh, e o formato do cabeçalho do motor."""
    setup = (RAIZ_DO_PROJETO / "firmware" / "setup.sh").read_text(encoding="utf-8")
    ler_adc = (RAIZ_DO_PROJETO / "firmware" / "ler_adc.c").read_text(encoding="utf-8")
    memoria = (RAIZ_DO_PROJETO / "firmware" / "memoria_pru.h").read_text(encoding="utf-8")
    assert f"REMOTEPROC={agente.REMOTEPROC_PRU0}\n" in setup and f"NOME_FIRMWARE={agente.NOME_DO_FIRMWARE_DA_PRU}" in setup
    assert f'"{agente.REMOTEPROC_PRU0}/state"' in ler_adc
    assert dict(re.findall(r"^config-pin (P9_\d+) (\w+)", setup, re.M)) == agente.PINOS_DA_PRU
    assert int(re.search(r"#define DDR_RESERVED_PHYS\s+(0x[0-9A-Fa-f]+)", memoria).group(1), 16) == \
        agente.FAIXA_DOS_BUFFERS[0]
    assert '"9f400000"' in setup and agente.FAIXA_DOS_BUFFERS[1] == 0x9F3FFFFF
    assert agente.protocolo_da_pru(RAIZ_DO_PROJETO / "firmware") == \
        int(re.search(r"#define VERSAO_PROTOCOLO_PRU (\d+)u", memoria).group(1))
    assert agente.CABECALHO_TAMANHO_MINIMO_V9 == motor.CABECALHO_TAMANHO_TOTAL + struct.calcsize(motor._FORMATO_EXTENSAO_V9)
    assert agente.CABECALHO_TAMANHO_V9 == motor.CABECALHO_TAMANHO_V9
    assert agente.OFFSET_DO_CRC == {v: getattr(motor, f"_OFFSET_HEADER_CRC32_V{v}") for v in range(2, 8)}
    assert motor._OFFSET_HEADER_CRC32_V1 == 404 and motor._OFFSET_HEADER_CRC32_V8 == 1020


def test_so_biblioteca_padrao_e_sintaxe_do_python_37():
    """A placa não tem pip, e a imagem dela pode trazer um Python antigo."""
    texto = AGENTE.read_text(encoding="utf-8")
    arvore = ast.parse(texto, feature_version=(3, 7))
    modulos = {a.name.split(".")[0] for n in ast.walk(arvore) if isinstance(n, ast.Import) for a in n.names}
    modulos |= {n.module.split(".")[0] for n in ast.walk(arvore) if isinstance(n, ast.ImportFrom) and n.module}
    assert modulos <= set(sys.stdlib_module_names) | {"__future__"}, modulos
    assert texto.startswith("#!/usr/bin/env python3\n") and os.access(AGENTE, os.X_OK)
