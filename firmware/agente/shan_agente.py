#!/usr/bin/env python3
"""O agente do SH-Analyzer na BeagleBone: responde em JSON o que o aplicativo do computador pergunta sobre a placa
(docs/gui-plan.md, seção 11.2).

O aplicativo roda, pelo SSH, um comando por vez:

    python3 ~/firmware/agente/shan_agente.py versao
    python3 ~/firmware/agente/shan_agente.py estado

e lê um objeto JSON do stdout, com ``"protocolo"`` (a versão deste formato) e ``"agente"``. Um comando desconhecido
responde ``{"erro": ...}`` e sai com o código 2. Nada aqui muda a placa: só lê.

**Por que um agente, e não comandos soltos:** respostas estruturadas, num esquema versionado, em vez de texto feito
para pessoas lido com ``sed``; testável no computador (``tests/test_agente.py``) sobre um sistema de arquivos falso;
e uma fonte de verdade só para o diagnóstico da interface e de uma futura CLI.

**Restrições da placa:** só a biblioteca padrão (a placa não tem pip) e compatível com o Python 3.7 (a imagem pode ser
antiga; ``tests/test_agente.py`` confere a sintaxe). Cada campo é lido com cuidado: um arquivo que falta vira ``null``,
nunca um erro, porque cada imagem da BeagleBone tem um conjunto diferente.

**Para os testes e o simulador:** ``SHAN_RAIZ`` troca a raiz de todos os caminhos do sistema (``/proc``, ``/sys``,
``/boot``, ``/etc``) por uma pasta falsa, e ``SHAN_PASTA`` diz onde está a pasta do firmware (por padrão, a pasta
acima desta). É o que o ``ler_adc`` faz com ``BASE_PINMUX`` e companhia.
"""

from __future__ import annotations

import json
import os
import sys
import time

PROTOCOLO = 1
AGENTE = "1"

PINOS_DA_PRU = {"P9_28": "pruout", "P9_29": "pruout", "P9_30": "pruin", "P9_31": "pruout"}   # os do setup.sh
REMOTEPROC_PRU0 = "/sys/class/remoteproc/remoteproc1"                                       # o do ler_adc.c
EEPROMS = ("/sys/bus/nvmem/devices/0-00500/nvmem", "/sys/bus/i2c/devices/0-0050/eeprom")
BASE_PINMUX = "/sys/devices/platform/ocp"


def raiz():
    return os.environ.get("SHAN_RAIZ", "/")


def sistema(caminho):
    """Um caminho do sistema (``/proc/...``) dentro da raiz (a falsa, nos testes)."""
    return os.path.join(raiz(), caminho.lstrip("/"))


def pasta_do_firmware():
    return os.environ.get("SHAN_PASTA") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ler_texto(caminho, limite=4096):
    """O conteúdo de um arquivo de texto do sistema, sem espaços nas pontas; ``None`` se não der para ler."""
    try:
        with open(sistema(caminho), "rb") as f:
            return f.read(limite).decode("utf-8", "replace").strip().strip("\x00")
    except OSError:
        return None


def ler_numero(caminho, conversao=float):
    texto = ler_texto(caminho)
    try:
        return conversao(texto.split()[0]) if texto else None
    except ValueError:
        return None


# ------------------------------------------------------------------ as partes do estado

def _campo_da_eeprom(e, inicio, fim):
    return e[inicio:fim].decode("ascii", "replace").strip("\x00 ").strip() or None


def placa():
    """O nome, a revisão e o nº de série da EEPROM (o mesmo que o ``ler_adc`` grava no cabeçalho v8), e o modelo da
    árvore de dispositivos."""
    resultado = {"nome": None, "revisao": None, "serie": None, "modelo": ler_texto("/proc/device-tree/model")}
    for caminho in EEPROMS:
        try:
            with open(sistema(caminho), "rb") as f:
                e = f.read(28)
        except OSError:
            continue
        if len(e) == 28 and e[:4] == b"\xaa\x55\x33\xee":
            resultado.update(nome=_campo_da_eeprom(e, 4, 12), revisao=_campo_da_eeprom(e, 12, 16),
                             serie=_campo_da_eeprom(e, 16, 28))
            break
    return resultado


def sistema_operacional():
    dogtag = ler_texto("/etc/dogtag")
    if dogtag:
        return dogtag.splitlines()[0].strip()
    os_release = ler_texto("/etc/os-release") or ""
    for linha in os_release.splitlines():
        if linha.startswith("PRETTY_NAME="):
            return linha.split("=", 1)[1].strip().strip('"')
    return None


def memoria_disponivel_kib():
    for linha in (ler_texto("/proc/meminfo", 16384) or "").splitlines():
        if linha.startswith("MemAvailable:"):
            try:
                return int(linha.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def disco(caminho):
    try:
        v = os.statvfs(caminho)
    except OSError:
        return None
    return {"total_kib": v.f_blocks * v.f_frsize // 1024, "livre_kib": v.f_bavail * v.f_frsize // 1024}


def relogio():
    """A hora da placa (para comparar com a do computador: ela não tem bateria de RTC) e se o NTP a sincronizou."""
    sincronizado = None
    if os.path.isdir(sistema("/run/systemd/timesync")):
        sincronizado = os.path.exists(sistema("/run/systemd/timesync/synchronized"))
    return {"utc": time.time(), "sincronizado": sincronizado}


def pru():
    estado = ler_texto(REMOTEPROC_PRU0 + "/state")
    return {"estado": estado, "firmware": ler_texto(REMOTEPROC_PRU0 + "/firmware"),
            "nome": ler_texto(REMOTEPROC_PRU0 + "/name")}


def pinos():
    """O modo de cada pino da PRU, onde o ``config-pin`` o grava, e se é o que o ``setup.sh`` configura."""
    resultado = {}
    for pino, esperado in sorted(PINOS_DA_PRU.items()):
        modo = ler_texto(BASE_PINMUX + "/ocp:" + pino + "_pinmux/state")
        resultado[pino] = {"modo": modo, "esperado": esperado, "certo": None if modo is None else modo == esperado}
    return resultado


def memoria_dos_buffers():
    """``mem=496M`` na linha do kernel: os 16 MB do fim da DDR ficam fora do Linux, para os buffers da PRU."""
    linha = ler_texto("/proc/cmdline")
    if linha is None:
        return {"cmdline": None, "mem_496m": None}
    return {"cmdline": linha, "mem_496m": "mem=496M" in linha.split()}


def capturas(pasta):
    """Os ``.bin`` na pasta do firmware: o número, o tamanho total e os mais recentes (nome, bytes, data)."""
    try:
        nomes = [n for n in os.listdir(pasta) if n.endswith(".bin")]
    except OSError:
        return None
    arquivos = []
    for nome in nomes:
        try:
            info = os.stat(os.path.join(pasta, nome))
        except OSError:
            continue
        arquivos.append({"nome": nome, "bytes": info.st_size, "modificado": info.st_mtime})
    arquivos.sort(key=lambda a: a["modificado"], reverse=True)
    return {"quantidade": len(arquivos), "bytes": sum(a["bytes"] for a in arquivos), "recentes": arquivos[:20]}


# ------------------------------------------------------------------ os comandos

def versao():
    pasta = pasta_do_firmware()
    try:
        with open(os.path.join(pasta, "VERSAO"), encoding="utf-8", errors="replace") as f:
            firmware = f.read(64).strip() or None
    except OSError:
        firmware = None
    return {"firmware": firmware, "python": ".".join(map(str, sys.version_info[:3]))}


def estado():
    pasta = pasta_do_firmware()
    carga = ler_texto("/proc/loadavg")
    temperatura = ler_numero("/sys/class/thermal/thermal_zone0/temp")
    return {
        "placa": placa(),
        "sistema": sistema_operacional(),
        "kernel": ler_texto("/proc/sys/kernel/osrelease"),
        "ligada_s": ler_numero("/proc/uptime"),
        "carga": [float(x) for x in carga.split()[:3]] if carga else None,
        "memoria_disponivel_kib": memoria_disponivel_kib(),
        "temperatura_c": None if temperatura is None else temperatura / 1000.0,
        "disco": disco(pasta),
        "relogio": relogio(),
        "pru": pru(),
        "pinos": pinos(),
        "memoria_dos_buffers": memoria_dos_buffers(),
        "firmware": dict(versao(), compilado=os.access(os.path.join(pasta, "ler_adc"), os.X_OK)),
        "capturas": capturas(pasta),
    }


COMANDOS = {"versao": versao, "estado": estado}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    comando = argv[0] if argv else ""
    if comando not in COMANDOS:
        resposta = {"protocolo": PROTOCOLO, "agente": AGENTE,
                    "erro": f"comando desconhecido: {comando!r} (os comandos: {', '.join(sorted(COMANDOS))})"}
        sys.stdout.write(json.dumps(resposta, ensure_ascii=False) + "\n")
        return 2
    resposta = {"protocolo": PROTOCOLO, "agente": AGENTE, "comando": comando}
    resposta.update(COMANDOS[comando]())
    sys.stdout.write(json.dumps(resposta, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
