"""O simulador da BeagleBone (docs/gui-plan.md, 11.11): uma placa inteira neste computador, que a interface, os testes e
as demonstrações usam como usariam a de verdade.

* :func:`montar_sistema_falso` -- a árvore da placa (``/proc``, ``/sys``, ``/boot``, ``/lib/firmware``, ``/etc``) e a
  pasta do firmware, com capturas de verdade (``capturas_simuladas.py``), em que o **agente de verdade** roda, e o
  ``ler_adc`` dela (``ler_adc_simulado.py``), que captura no cartão e pela saída contínua;
* :class:`Simulador` -- a placa sem o SSH (o agente rodado aqui): os testes do agente e do diagnóstico;
* a placa servida por **SSH** (o que a interface usa) fica em ``servidor_do_simulador.py``, que precisa do asyncssh
  (o extra ``placa``): este módulo não, para os testes do agente rodarem sem ele.

A árvore é a da placa de verdade do projeto, lida em 15/11/2026: a imagem Buster de 2020-04-06, o kernel
4.19.94-ti-r42, o ``uEnv.txt`` dela (com o ``mem=496M`` no ``optargs``), os overlays carregados, os ``.dtbo`` da PRU em
``/lib/firmware`` e o ``/proc/iomem`` como o usuário ``debian`` o vê (os endereços zerados: só o root vê). As
ferramentas (``make``, ``gcc``, ``clpru``, ``config-pin``, ``dtc``) são arquivos executáveis vazios, e o
``journalctl``, um script que mostra um diário falso. O cartão é o de 4 GB da placa (``/run/simulador``: o agente
desconta os arquivos da pasta do firmware), e o relógio, o deste computador mais o desvio do cenário.

**Os cenários** (:data:`CENARIOS`, de ``cenarios.py``; a interface deixa escolher): os do uso da placa (a rede de
60 Hz com supraharmônicos, o ADC mudo, o cartão cheio, a conexão que cai, o firmware de outra versão, o relógio
errado) e os da configuração dela, que o diagnóstico tem de reconhecer.

"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

from . import capturas_simuladas
from .agente import ClienteDoAgente, TransporteLocal
from .capturas_simuladas import Sistema, gravar_captura
from .cenarios import CENARIOS, Cenario  # noqa: F401 (o Cenario, para quem importa daqui)
from .ler_adc_simulado import roteiro as roteiro_do_ler_adc

VERSAO_SIMULADA = "v0.8.0-simulador"
"""A versão do firmware da placa simulada, e a do aplicativo para ela (o cenário ``firmware_antigo`` tem outra)."""
VERSAO_ANTIGA = "v0.7.0"
SERIE_SIMULADA = "3714BBBK1234"
KERNEL_SIMULADO = "4.19.94-ti-r42"
SISTEMA_SIMULADO = "BeagleBoard.org Debian Buster IoT Image 2020-04-06"
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



CARTAO_KIB = 3_558_400
"""A partição do eMMC de 4 GB da placa (o ``df`` dela, 15/11/2026)."""
LIVRE_NORMAL_KIB = 1_520_000             # ~1,5 GB livres, como na placa de verdade
LIVRE_NO_CARTAO_CHEIO_KIB = 56 * 1024    # abaixo dos 64 MiB do erro do agente; apagar duas capturas da tomada o resolve
DESVIO_DO_RELOGIO_ERRADO_S = -(2 * 86_400 + 5 * 3600 + 13 * 60 + 27.0)
"""A placa desligada por dois dias, ligada sem internet: o relógio volta de onde parou (o ``timesyncd`` guarda a hora
ao desligar), e fica atrás do computador."""


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


def montar_sistema_falso(pasta: Path, cenario: str = "normal", versao_firmware: str = VERSAO_SIMULADA, *,
                         amostras_por_bloco: int | None = None, agora: float | None = None) -> tuple[Path, Path]:
    """Monta em ``pasta`` a raiz falsa e a pasta do firmware de uma BeagleBone Black; devolve ``(raiz, firmware)``.
    ``amostras_por_bloco``: o bloco das capturas (``capturas_simuladas.BLOCO_DAS_CAPTURAS``, o do firmware, por
    padrão); ``agora``: a hora deste computador (as capturas são de antes dela)."""
    if cenario not in CENARIOS:
        raise ValueError(f"cenário desconhecido: {cenario!r} (os cenários: {', '.join(CENARIOS)})")
    agora = time.time() if agora is None else agora
    raiz, firmware = Path(pasta) / "raiz", Path(pasta) / "home" / "debian" / "firmware"
    eeprom = b"\xaa\x55\x33\xee" + b"A335BNLT" + b"00C0" + SERIE_SIMULADA.encode("ascii") + b"\xff" * 4
    _escrever(raiz, "/sys/bus/nvmem/devices/0-00500/nvmem", eeprom)
    _escrever(raiz, "/proc/device-tree/model", "TI AM335x BeagleBone Black\x00")
    _escrever(raiz, "/etc/dogtag", SISTEMA_SIMULADO + "\n")
    _escrever(raiz, "/proc/sys/kernel/osrelease", KERNEL_SIMULADO + "\n")
    _escrever(raiz, "/proc/uptime", "8040.52 15000.11\n")
    _escrever(raiz, "/proc/loadavg", "0.31 0.24 0.18 1/120 999\n")
    _escrever(raiz, "/proc/meminfo", "MemTotal:  478796 kB\nMemFree:  250000 kB\nMemAvailable:  319488 kB\n")
    _escrever(raiz, "/sys/class/thermal/thermal_zone0/temp", "52000\n")
    # O timesyncd sempre roda; o arquivo "synchronized" só existe depois de o NTP acertar a hora.
    (raiz / "run" / "systemd" / "timesync").mkdir(parents=True, exist_ok=True)
    desvio = DESVIO_DO_RELOGIO_ERRADO_S if cenario == "relogio_errado" else 0.0
    if cenario == "relogio_errado":
        _escrever(raiz, "/run/simulador/relogio", f"{desvio!r}\n")
    else:
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
    versao = VERSAO_ANTIGA if cenario == "firmware_antigo" else versao_firmware
    (firmware / "VERSAO").write_text(versao + "\n")
    fontes = {"ler_adc.c": "/* o ler_adc da placa simulada */\n", "pru_main.c": "/* a PRU0 */\n",
              "spi_core.asm": "; o laço da PRU0\n",
              "memoria_pru.h": "// o contrato ARM <-> PRU\n#define VERSAO_PROTOCOLO_PRU 5u\n"}
    for nome, texto in fontes.items():
        (firmware / nome).write_text(texto, encoding="utf-8")
        os.utime(firmware / nome, (FONTES_COMPILADAS_EM, FONTES_COMPILADAS_EM))
    fw_pru = b"\x7fELF" + b"o fw_pru.out da placa simulada".ljust(60, b"\x00")
    if cenario != "sem_compilar":
        ler_adc = firmware / "ler_adc"
        ler_adc.write_text(roteiro_do_ler_adc(cenario, amostras_por_bloco or capturas_simuladas.BLOCO_DAS_CAPTURAS,
                                              _sistema(cenario, versao)))
        ler_adc.chmod(0o755)
        (firmware / "fw_pru.out").write_bytes(fw_pru)
        for nome in ("ler_adc", "fw_pru.out"):
            os.utime(firmware / nome, (FONTES_COMPILADAS_EM + 3600, FONTES_COMPILADAS_EM + 3600))
    # O que o setup.sh instalou na PRU: o fw_pru.out desta pasta, ou o de uma compilação anterior.
    _escrever(raiz, "/lib/firmware/am335x-pru0-fw", fw_pru if cenario != "pru_desatualizada" else fw_pru[::-1])
    _gravar_as_capturas(firmware, cenario, versao, agora + desvio, amostras_por_bloco)
    usado_kib = sum(f.stat().st_size for f in firmware.rglob("*") if f.is_file()) // 1024
    livre = LIVRE_NO_CARTAO_CHEIO_KIB if cenario == "disco_cheio" else LIVRE_NORMAL_KIB
    _escrever(raiz, "/run/simulador/disco", f"{CARTAO_KIB} {CARTAO_KIB - livre - usado_kib}\n")
    return raiz, firmware


def _gravar_as_capturas(firmware: Path, cenario: str, versao: str, agora_na_placa: float,
                        bloco: int | None) -> None:
    """As capturas que estão na placa: uma conferência (o ``coletar.sh conferir``) e duas da tomada, da última
    hora e meia; no cartão cheio, quatro; no ADC mudo, a conferência mais recente ficou em 0."""
    sistema = _sistema(cenario, versao)
    capturas = [("conferir", 125, 1, "Conferência", False), ("rede_bloco_A", 112, 2, "Rede da casa", False),
                ("rede_bloco_B", 97, 2, "Rede da casa", False)]
    if cenario == "disco_cheio":
        capturas += [("rede_bloco_C", 82, 2, "Rede da casa", False), ("rede_bloco_D", 67, 2, "Rede da casa", False)]
    if cenario == "adc_mudo":                # a placa ligada pelo USB hoje: a conferência de agora há pouco ficou muda
        capturas.append(("conferir", 25, 1, "Conferência", True))
    for semente, (prefixo, minutos_atras, blocos, titulo, muda) in enumerate(capturas):
        inicio = agora_na_placa - minutos_atras * 60
        nome = f"{prefixo}_{time.strftime('%H%M', time.localtime(inicio))}.bin"
        gravar_captura(firmware / nome, inicio=inicio, blocos=blocos, sistema=sistema, titulo=titulo,
                       descricao="Captura do simulador: a tomada (canal 1, 127 V) e a corrente de uma carga não "
                                 "linear (canal 0, sonda de 100 mV/A).",
                       muda=muda, semente=semente, amostras_por_bloco=bloco)


def _sistema(cenario: str, versao: str) -> Sistema:
    """O sistema da placa simulada, como o ``ler_adc`` o grava no cabeçalho."""
    return Sistema(KERNEL_SIMULADO, SISTEMA_SIMULADO, f"A335BNLT 00C0 {SERIE_SIMULADA}", versao_firmware=versao,
                   relogio_sincronizado=cenario != "relogio_errado", disco_total_kib=CARTAO_KIB,
                   disco_livre_kib=LIVRE_NORMAL_KIB)


class Simulador:
    """Uma placa simulada sem o SSH (o agente rodado aqui, pelo ``TransporteLocal``): ``with Simulador("pru_com_falha")
    as cliente: await cliente.estado()``. A pasta temporária some no fim."""

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
