"""O simulador da BeagleBone (docs/gui-plan.md, 11.11): um sistema de arquivos falso de uma placa (``/proc``, ``/sys``,
``/etc``, a pasta do firmware com capturas), em que o **agente de verdade** roda. A interface, os testes e as
demonstrações falam com ele exatamente como falariam com a placa.

Os cenários (:data:`CENARIOS`) montam os problemas que o diagnóstico tem de reconhecer.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .agente import ClienteDoAgente, TransporteLocal

CENARIOS = ("normal", "pru_com_falha", "pinos_errados", "sem_mem_496m", "firmware_antigo", "sem_compilar")
VERSAO_SIMULADA = "v0.8.0-simulador"
SERIE_SIMULADA = "3714BBBK1234"


def _escrever(raiz: Path, caminho: str, conteudo: str | bytes) -> None:
    destino = raiz / caminho.lstrip("/")
    destino.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(conteudo, bytes):
        destino.write_bytes(conteudo)
    else:
        destino.write_text(conteudo, encoding="utf-8")


def montar_sistema_falso(pasta: Path, cenario: str = "normal", versao_firmware: str = VERSAO_SIMULADA) -> tuple[Path, Path]:
    """Monta em ``pasta`` a raiz falsa e a pasta do firmware de uma BeagleBone Black; devolve ``(raiz, firmware)``."""
    if cenario not in CENARIOS:
        raise ValueError(f"cenário desconhecido: {cenario!r} (os cenários: {', '.join(CENARIOS)})")
    raiz, firmware = Path(pasta) / "raiz", Path(pasta) / "home" / "debian" / "firmware"
    eeprom = b"\xaa\x55\x33\xee" + b"A335BNLT" + b"00C0" + SERIE_SIMULADA.encode("ascii") + b"\xff" * 4
    _escrever(raiz, "/sys/bus/nvmem/devices/0-00500/nvmem", eeprom)
    _escrever(raiz, "/proc/device-tree/model", "TI AM335x BeagleBone Black\x00")
    _escrever(raiz, "/etc/dogtag", "BeagleBoard.org Debian Bullseye IoT Image 2023-09-02\n")
    _escrever(raiz, "/proc/sys/kernel/osrelease", "5.10.168-ti-r71\n")
    _escrever(raiz, "/proc/uptime", "8040.52 15000.11\n")
    _escrever(raiz, "/proc/loadavg", "0.31 0.24 0.18 1/120 999\n")
    _escrever(raiz, "/proc/meminfo", "MemTotal:  496000 kB\nMemFree:  250000 kB\nMemAvailable:  319488 kB\n")
    _escrever(raiz, "/sys/class/thermal/thermal_zone0/temp", "52000\n")
    _escrever(raiz, "/run/systemd/timesync/synchronized", "")
    cmdline = "console=ttyS0,115200n8 root=/dev/mmcblk0p1 ro rootfstype=ext4 rootwait coherent_pool=1M"
    _escrever(raiz, "/proc/cmdline", cmdline + ("" if cenario == "sem_mem_496m" else " mem=496M") + "\n")
    rproc = "/sys/class/remoteproc/remoteproc1"
    # Entre uma captura e outra, a PRU de uma placa boa está parada (o ler_adc a liga e a para).
    _escrever(raiz, rproc + "/state", "crashed\n" if cenario == "pru_com_falha" else "offline\n")
    _escrever(raiz, rproc + "/firmware", "am335x-pru0-fw\n")
    _escrever(raiz, rproc + "/name", "4a334000.pru\n")
    for pino, modo in (("P9_28", "pruout"), ("P9_29", "pruout"), ("P9_30", "pruin"), ("P9_31", "pruout")):
        if cenario == "pinos_errados" and pino in ("P9_28", "P9_31"):
            modo = "default"
        _escrever(raiz, f"/sys/devices/platform/ocp/ocp:{pino}_pinmux/state", modo + "\n")
    firmware.mkdir(parents=True, exist_ok=True)
    (firmware / "VERSAO").write_text("v0.7.0\n" if cenario == "firmware_antigo" else versao_firmware + "\n")
    if cenario != "sem_compilar":
        ler_adc = firmware / "ler_adc"
        ler_adc.write_text("#!/bin/sh\necho simulador\n")
        ler_adc.chmod(0o755)
    for nome, tamanho in (("rede_bloco_E_0930.bin", 20_480), ("conferir_0844.bin", 8_192)):
        (firmware / nome).write_bytes(b"SHAN" + bytes(tamanho - 4))
    return raiz, firmware


class Simulador:
    """Uma placa simulada: ``with Simulador("pru_com_falha") as cliente: await cliente.estado()``. A pasta
    temporária some no fim."""

    def __init__(self, cenario: str = "normal", versao_firmware: str = VERSAO_SIMULADA):
        self.cenario, self.versao_firmware = cenario, versao_firmware
        self._pasta: Path | None = None

    def __enter__(self) -> ClienteDoAgente:
        self._pasta = Path(tempfile.mkdtemp(prefix="sh-placa-simulada-"))
        raiz, firmware = montar_sistema_falso(self._pasta, self.cenario, self.versao_firmware)
        return ClienteDoAgente(TransporteLocal(raiz=raiz, pasta_firmware=firmware))

    def __exit__(self, *exc) -> None:
        if self._pasta is not None:
            shutil.rmtree(self._pasta, ignore_errors=True)
