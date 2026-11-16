"""O simulador da BeagleBone (docs/gui-plan.md, 11.11): um sistema de arquivos falso de uma placa (``/proc``, ``/sys``,
``/boot``, ``/lib/firmware``, ``/etc``, a pasta do firmware com capturas), em que o **agente de verdade** roda. A
interface, os testes e as demonstrações falam com ele exatamente como falariam com a placa.

A árvore é a da placa de verdade do projeto, lida em 15/11/2026: a imagem Buster de 2020-04-06, o kernel
4.19.94-ti-r42, o ``uEnv.txt`` dela (com o ``mem=496M`` no ``optargs``), os overlays carregados, os ``.dtbo`` da PRU em
``/lib/firmware`` e o ``/proc/iomem`` como o usuário ``debian`` o vê (os endereços zerados: só o root vê). As
ferramentas (``make``, ``gcc``, ``clpru``, ``config-pin``, ``dtc``) são arquivos executáveis vazios, e o
``journalctl``, um script que mostra um diário falso.

Os cenários (:data:`CENARIOS`) montam os problemas que o diagnóstico tem de reconhecer.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from .agente import ClienteDoAgente, TransporteLocal

CENARIOS = ("normal", "pru_com_falha", "pinos_errados", "sem_mem_496m", "firmware_antigo", "sem_compilar",
            "pru_desatualizada", "audio_hdmi", "sem_overlay_da_pru")
VERSAO_SIMULADA = "v0.8.0-simulador"
SERIE_SIMULADA = "3714BBBK1234"
KERNEL_SIMULADO = "4.19.94-ti-r42"
FONTES_COMPILADAS_EM = 1_794_600_000.0
"""A hora (``mtime``) do código do firmware na placa simulada; os binários são de uma hora depois (compilados)."""
FERRAMENTAS = ("make", "gcc", "clpru", "config-pin", "dtc")
OVERLAY_DA_PRU = "AM335X-PRU-RPROC-4-19-TI-00A0"

UENV = """#Docs: http://elinux.org/Beagleboard:U-boot_partitioning_layout_2.0

uname_r={kernel}
#uuid=
#dtb=

###U-Boot Overlays###
###Master Enable
enable_uboot_overlays=1
###
###Disable auto loading of virtual capes (emmc/video/wireless/adc)
#disable_uboot_overlay_emmc=1
{video}disable_uboot_overlay_video=1
{audio}disable_uboot_overlay_audio=1
#disable_uboot_overlay_wireless=1
#disable_uboot_overlay_adc=1
###
###PRUSS OPTIONS
###pru_rproc (4.14.x-ti kernel)
#uboot_overlay_pru=/lib/firmware/AM335X-PRU-RPROC-4-14-TI-00A0.dtbo
###pru_rproc (4.19.x-ti kernel)
{pru}uboot_overlay_pru=/lib/firmware/{overlay}.dtbo
###pru_uio (4.14.x-ti, 4.19.x-ti & mainline/bone kernel)
#uboot_overlay_pru=/lib/firmware/AM335X-PRU-UIO-00A0.dtbo
###
###Cape Universal Enable
enable_uboot_cape_universal=1
###U-Boot Overlays###

cmdline=coherent_pool=1M net.ifnames=0 lpj=1990656 rng_core.default_quality=100 quiet

##enable Generic eMMC Flasher:
#cmdline=init=/opt/scripts/tools/eMMC/init-eMMC-flasher-v3.sh

{mem}
"""

KMSG = """6,330,1852353605,-;remoteproc remoteproc1: stopped remote processor 4a334000.pru
 SUBSYSTEM=remoteproc
 DEVICE=+remoteproc:remoteproc1
6,331,2916323129,-;remoteproc remoteproc1: powering up 4a334000.pru
6,332,2916323378,-;remoteproc remoteproc1: Booting fw image am335x-pru0-fw, size 26492
6,333,2916327755,-;remoteproc remoteproc1: remote processor 4a334000.pru is now up
6,334,2927340853,-;remoteproc remoteproc1: stopped remote processor 4a334000.pru
6,335,3000000000,-;usb 1-1: new high-speed USB device number 2 using musb-hdrc
3,336,3100000000,-;mmcblk1: error -110 transferring data, sector 3014656, nr 8, cmd response 0x900, card status 0xb00
"""
"""O ``/dev/kmsg`` da placa (o formato do kernel: ``prioridade,número,µs desde o boot,-;mensagem``, e as linhas com
espaço na frente, que são do registro de cima), com as mensagens da PRU de uma captura e um erro do cartão."""

JOURNAL = (
    '{"__REALTIME_TIMESTAMP": "1794787200000000", "PRIORITY": "6", "SYSLOG_IDENTIFIER": "systemd", '
    '"MESSAGE": "Started Session 41 of user debian.", "_TRANSPORT": "journal"}\n'
    '{"__REALTIME_TIMESTAMP": "1794787260000000", "PRIORITY": "5", "SYSLOG_IDENTIFIER": "sudo", '
    '"MESSAGE": "  debian : PWD=/home/debian/firmware ; USER=root ; COMMAND=./ler_adc 400000 0,1 --blocos 30 -o '
    'rede.bin", "_TRANSPORT": "syslog"}\n'
    '{"__REALTIME_TIMESTAMP": "1794787300000000", "PRIORITY": "3", "SYSLOG_IDENTIFIER": "wpa_supplicant", '
    '"MESSAGE": "Failed to open config file", "_TRANSPORT": "stdout"}\n'
    '{"__REALTIME_TIMESTAMP": "1794787310000000", "PRIORITY": "6", "_TRANSPORT": "kernel", '
    '"MESSAGE": "remoteproc remoteproc1: stopped remote processor 4a334000.pru"}\n'
)
"""As linhas do ``journalctl -o json`` da placa: uma sessão, o ``sudo`` do ``ler_adc``, um erro de outro serviço e uma
do kernel (que os logs do agente tiram: já vêm do ``/dev/kmsg``)."""


def _escrever(raiz: Path, caminho: str, conteudo: str | bytes, executavel: bool = False) -> Path:
    destino = raiz / caminho.lstrip("/")
    destino.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(conteudo, bytes):
        destino.write_bytes(conteudo)
    else:
        destino.write_text(conteudo, encoding="utf-8")
    if executavel:
        destino.chmod(0o755)
    return destino


def montar_sistema_falso(pasta: Path, cenario: str = "normal", versao_firmware: str = VERSAO_SIMULADA) -> tuple[Path, Path]:
    """Monta em ``pasta`` a raiz falsa e a pasta do firmware de uma BeagleBone Black; devolve ``(raiz, firmware)``."""
    if cenario not in CENARIOS:
        raise ValueError(f"cenário desconhecido: {cenario!r} (os cenários: {', '.join(CENARIOS)})")
    raiz, firmware = Path(pasta) / "raiz", Path(pasta) / "home" / "debian" / "firmware"
    eeprom = b"\xaa\x55\x33\xee" + b"A335BNLT" + b"00C0" + SERIE_SIMULADA.encode("ascii") + b"\xff" * 4
    _escrever(raiz, "/sys/bus/nvmem/devices/0-00500/nvmem", eeprom)
    _escrever(raiz, "/proc/device-tree/model", "TI AM335x BeagleBone Black\x00")
    _escrever(raiz, "/etc/dogtag", "BeagleBoard.org Debian Buster IoT Image 2020-04-06\n")
    _escrever(raiz, "/proc/sys/kernel/osrelease", KERNEL_SIMULADO + "\n")
    _escrever(raiz, "/proc/uptime", "8040.52 15000.11\n")
    _escrever(raiz, "/proc/loadavg", "0.31 0.24 0.18 1/120 999\n")
    _escrever(raiz, "/proc/meminfo", "MemTotal:  478796 kB\nMemFree:  250000 kB\nMemAvailable:  319488 kB\n")
    _escrever(raiz, "/sys/class/thermal/thermal_zone0/temp", "52000\n")
    _escrever(raiz, "/run/systemd/timesync/synchronized", "")
    # A linha do kernel que o u-boot monta: o optargs do uEnv.txt vem antes do cmdline.
    cmdline = ("console=ttyO0,115200n8" + ("" if cenario == "sem_mem_496m" else " mem=496M")
               + " bone_capemgr.uboot_capemgr_enabled=1 root=/dev/mmcblk1p1 ro rootfstype=ext4 rootwait"
               " coherent_pool=1M net.ifnames=0 lpj=1990656 rng_core.default_quality=100 quiet")
    _escrever(raiz, "/proc/cmdline", cmdline + "\n")
    # Como o usuário debian vê o /proc/iomem: os nomes, com os endereços zerados.
    _escrever(raiz, "/proc/iomem", "00000000-00000000 : 40300000.ocmcram\n00000000-00000000 : System RAM\n"
                                   "  00000000-00000000 : Kernel code\n  00000000-00000000 : Kernel data\n")
    _escrever(raiz, "/boot/uEnv.txt", UENV.format(
        kernel=KERNEL_SIMULADO, overlay=OVERLAY_DA_PRU,
        video="#" if cenario == "audio_hdmi" else "", audio="#" if cenario == "audio_hdmi" else "",
        pru="#" if cenario == "sem_overlay_da_pru" else "",
        mem="" if cenario == "sem_mem_496m" else "optargs=mem=496M"))
    overlays = ["BB-ADC-00A0", "BB-BONE-eMMC1-01-00A0"]
    if cenario != "sem_overlay_da_pru":
        overlays.append(OVERLAY_DA_PRU)
    if cenario == "audio_hdmi":
        overlays.append("BB-HDMI-TDA998x-00A0")         # o HDMI com o áudio: o McASP0 nos pinos da PRU
    _escrever(raiz, "/proc/device-tree/chosen/overlays/name", "overlays\x00")
    for overlay in overlays:
        _escrever(raiz, f"/proc/device-tree/chosen/overlays/{overlay}", "Fri Apr  3 23:36:17 2020\x00")
    for dtbo in ("AM335X-PRU-RPROC-4-14-TI-00A0", "AM335X-PRU-RPROC-4-19-TI-00A0",
                 "AM335X-PRU-RPROC-4-19-TI-PRUCAPE-00A0", "AM335X-PRU-UIO-00A0"):
        _escrever(raiz, f"/lib/firmware/{dtbo}.dtbo", b"\xd0\x0d\xfe\xed")
    _escrever(raiz, "/sys/class/remoteproc/remoteproc0/name", "wkup_m3\n")
    if cenario != "sem_overlay_da_pru":
        rproc = "/sys/class/remoteproc/remoteproc1"
        # Entre uma captura e outra, a PRU de uma placa boa está parada (o ler_adc a liga e a para).
        _escrever(raiz, rproc + "/state", "crashed\n" if cenario == "pru_com_falha" else "offline\n")
        _escrever(raiz, rproc + "/firmware", "am335x-pru0-fw\n")
        _escrever(raiz, rproc + "/name", "4a334000.pru\n")
    for pino, modo in (("P9_28", "pruout"), ("P9_29", "pruout"), ("P9_30", "pruin"), ("P9_31", "pruout")):
        if (cenario == "pinos_errados" and pino in ("P9_28", "P9_31")) or (cenario == "audio_hdmi" and pino != "P9_30"):
            modo = "default"
        _escrever(raiz, f"/sys/devices/platform/ocp/ocp:{pino}_pinmux/state", modo + "\n")
    for ferramenta in FERRAMENTAS:
        _escrever(raiz, f"/usr/bin/{ferramenta}", "#!/bin/sh\nexit 0\n", executavel=True)
    _escrever(raiz, "/dev/kmsg", KMSG)
    _escrever(raiz, "/var/log/journal-do-simulador.json", JOURNAL)
    _escrever(raiz, "/bin/journalctl", '#!/bin/sh\ncat "${0%/bin/journalctl}/var/log/journal-do-simulador.json"\n',
              executavel=True)

    firmware.mkdir(parents=True, exist_ok=True)
    (firmware / "VERSAO").write_text("v0.7.0\n" if cenario == "firmware_antigo" else versao_firmware + "\n")
    fontes = {"ler_adc.c": "/* o ler_adc da placa simulada */\n", "pru_main.c": "/* a PRU0 */\n",
              "spi_core.asm": "; o laço da PRU0\n",
              "memoria_pru.h": "// o contrato ARM <-> PRU\n#define VERSAO_PROTOCOLO_PRU 5u\n"}
    for nome, texto in fontes.items():
        (firmware / nome).write_text(texto, encoding="utf-8")
        os.utime(firmware / nome, (FONTES_COMPILADAS_EM, FONTES_COMPILADAS_EM))
    fw_pru = b"\x7fELF" + b"o fw_pru.out da placa simulada".ljust(60, b"\x00")
    if cenario != "sem_compilar":
        ler_adc = firmware / "ler_adc"
        ler_adc.write_text("#!/bin/sh\necho simulador\n")
        ler_adc.chmod(0o755)
        (firmware / "fw_pru.out").write_bytes(fw_pru)
        for nome in ("ler_adc", "fw_pru.out"):
            os.utime(firmware / nome, (FONTES_COMPILADAS_EM + 3600, FONTES_COMPILADAS_EM + 3600))
    # O que o setup.sh instalou na PRU: o fw_pru.out desta pasta, ou o de uma compilação anterior.
    _escrever(raiz, "/lib/firmware/am335x-pru0-fw", fw_pru if cenario != "pru_desatualizada" else fw_pru[::-1])
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
