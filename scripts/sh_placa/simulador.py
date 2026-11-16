"""O simulador da BeagleBone (docs/gui-plan.md, 11.11): uma placa inteira neste computador, que a interface, os testes e
as demonstrações usam como usariam a de verdade.

* :func:`montar_sistema_falso` -- a árvore da placa (``/proc``, ``/sys``, ``/boot``, ``/lib/firmware``, ``/etc``) e a
  pasta do firmware, com capturas de verdade (``capturas_simuladas.py``), em que o **agente de verdade** roda;
* :class:`ServidorDoSimulador` -- a placa servida por **SSH**, em 127.0.0.1, numa porta livre: o mesmo protocolo da de
  verdade. Cada comando roda num shell deste computador, com o home e a raiz da placa simulada; o ``sudo``, o
  ``config-pin`` e o ``pgrep`` são os dela. O SFTP passa na vazão do USB (as transferências levam o tempo que levariam);
* :class:`Simulador` -- a placa sem o SSH (o agente rodado aqui): os testes do agente e do diagnóstico.

A árvore é a da placa de verdade do projeto, lida em 15/11/2026: a imagem Buster de 2020-04-06, o kernel
4.19.94-ti-r42, o ``uEnv.txt`` dela (com o ``mem=496M`` no ``optargs``), os overlays carregados, os ``.dtbo`` da PRU em
``/lib/firmware`` e o ``/proc/iomem`` como o usuário ``debian`` o vê (os endereços zerados: só o root vê). As
ferramentas (``make``, ``gcc``, ``clpru``, ``config-pin``, ``dtc``) são arquivos executáveis vazios, e o
``journalctl``, um script que mostra um diário falso. O cartão é o de 4 GB da placa (``/run/simulador``: o agente
desconta os arquivos da pasta do firmware), e o relógio, o deste computador mais o desvio do cenário.

**Os cenários** (:data:`CENARIOS`, de ``cenarios.py``; a interface deixa escolher): os do uso da placa (a rede de
60 Hz com supraharmônicos, o ADC mudo, o cartão cheio, a conexão que cai, o firmware de outra versão, o relógio
errado) e os da configuração dela, que o diagnóstico tem de reconhecer.

**A segurança:** o servidor só escuta no 127.0.0.1 e só aceita a chave gerada para ele (:meth:`ServidorDoSimulador.
acesso`, na pasta dele, que só o dono lê); sem a ``senha`` (a dos testes), ninguém entra com senha. Os comandos
rodam neste computador, como o usuário do aplicativo: por isso a interface não abre um terminal no simulador. O shell
é o POSIX (``/bin/sh``): no Windows, não há simulador.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

import asyncssh

from .agente import ClienteDoAgente, TransporteLocal
from .capturas_simuladas import Sistema, gravar_captura
from .cenarios import CENARIOS, Cenario  # noqa: F401 (o Cenario, para quem importa daqui)
from .destino import SENHA_PADRAO_DA_IMAGEM, Destino

if TYPE_CHECKING:
    from .chaves import ChaveDoAplicativo, HostsConhecidos


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
VAZAO_DO_USB_BYTES_S = 5_200_000
"""O SFTP da placa de verdade pelo USB (docs/gui-progress.md, seção 5): as transferências do simulador levam o mesmo
tempo."""
QUEDA_A_CADA_S = 45.0
FRACAO_DA_QUEDA = 0.4
"""No cenário ``conexao_instavel``: cada conexão cai depois de :data:`QUEDA_A_CADA_S`, e cada arquivo, na primeira vez
que é lido além desta fração dele (a retomada continua do ponto em que parou)."""


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
        ler_adc.write_text("#!/bin/sh\necho simulador\n")
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
    sistema = Sistema(KERNEL_SIMULADO, SISTEMA_SIMULADO, f"A335BNLT 00C0 {SERIE_SIMULADA}", versao_firmware=versao,
                      relogio_sincronizado=cenario != "relogio_errado", disco_total_kib=CARTAO_KIB,
                      disco_livre_kib=LIVRE_NORMAL_KIB)
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


# ------------------------------------------------------------------ a placa servida por SSH

SUDO = r"""#!/bin/sh
# O sudo da placa simulada: -A (a senha pelo SUDO_ASKPASS), -v (só validar), -n (sem perguntar), -k (esquecer).
estampa="$HOME/.sudo-validado"
[ "$1" = "-k" ] && { rm -f "$estampa"; exit 0; }
validar=0
while [ $# -gt 0 ]; do
    case "$1" in
        -v) validar=1 ;;
        -p) shift ;;
        --) shift; break ;;
        -*) ;;
        *) break ;;
    esac
    shift
done
if [ "$validar" = 1 ]; then
    [ -x "$SUDO_ASKPASS" ] || { echo "sudo: no askpass program specified" >&2; exit 1; }
    if [ "$("$SUDO_ASKPASS")" != "$SHAN_SENHA_DO_SUDO" ]; then
        echo "Sorry, try again." >&2
        echo "sudo: 1 incorrect password attempt" >&2
        exit 1
    fi
    touch "$estampa"
    exit 0
fi
[ -f "$estampa" ] || { echo "sudo: a password is required" >&2; exit 1; }
printf '%s\0' "$*" >> "$HOME/.sudo-comandos"
exec "$@"
"""
"""O sudo da placa simulada: faz o que o de verdade faz com ``-A``, ``-v``, ``-n`` e ``-k`` (a senha pelo
``SUDO_ASKPASS``, a credencial validada e esquecida) e roda o comando como o usuário deste computador (na raiz falsa:
o acerto do relógio escreve o desvio dela, e não mexe no relógio daqui)."""

CONFIG_PIN = r"""#!/bin/sh
# O config-pin da placa simulada: o modo no pinmux da árvore falsa.
[ $# -eq 2 ] || { echo "Usage: config-pin <pin> <mode>" >&2; exit 1; }
estado="$SHAN_RAIZ/sys/devices/platform/ocp/ocp:$1_pinmux/state"
[ -f "$estado" ] || { echo "ERROR: open() for $estado failed, No such file or directory" >&2; exit 1; }
printf '%s
' "$2" > "$estado"
"""

PGREP = r"""#!{python}
# O pgrep da placa simulada: o de verdade, só com os processos desta placa (os de executável dentro da pasta dos
# processos dela, SHAN_PROCESSOS): um programa deste computador com o mesmo nome não é uma captura na placa.
import os, subprocess, sys

raiz = os.path.realpath(os.environ["SHAN_PROCESSOS"]) + os.sep


def desta_placa(pid):
    try:
        return os.path.realpath(f"/proc/{{pid}}/exe").startswith(raiz)
    except OSError:
        return False


r = subprocess.run([{pgrep!r}, *sys.argv[1:]], capture_output=True, text=True)
linhas = [linha for linha in r.stdout.splitlines() if desta_placa(linha.split()[0])]
sys.stdout.write("".join(linha + "\n" for linha in linhas))
sys.exit(0 if linhas else 1)
"""


class ServidorDoSimulador:
    """A placa simulada (:func:`montar_sistema_falso`) servida por SSH, neste computador. ``await iniciar()`` escuta;
    :meth:`acesso` dá a chave e o ``known_hosts`` com que o aplicativo entra (a :class:`~sh_placa.conexao.ConexaoSSH`
    de sempre, para :attr:`destino`); :meth:`fechar` para e apaga a pasta, se foi ele que a criou.

    ``pasta``: onde montar a placa (``None``: uma temporária); ``senha``: a do usuário pelo SSH (``None``: só a chave;
    os testes da primeira conexão dão uma); ``senha_do_sudo``: a que o sudo da placa pede (a padrão da imagem);
    ``enderecos``: onde escutar (vários, como a placa nos dois IPs do USB), na mesma porta; ``processos``: a pasta dos
    executáveis que o ``pgrep`` dela vê (a dela, por padrão); ``vazao_bytes_s``: a do SFTP (``None``: sem limite).
    Para o que roda nela: :attr:`comandos` e :attr:`comandos_de_root`; :meth:`derrubar` (o cabo que solta)."""

    def __init__(self, pasta: Path | None = None, cenario: str = "normal", *, usuario: str = "debian",
                 senha: str | None = None, senha_do_sudo: str = SENHA_PADRAO_DA_IMAGEM,
                 enderecos: tuple[str, ...] = ("127.0.0.1",), processos: Path | None = None,
                 amostras_por_bloco: int | None = None, vazao_bytes_s: float | None = VAZAO_DO_USB_BYTES_S):
        if sys.platform == "win32":
            raise RuntimeError("o simulador da placa precisa de um shell POSIX (/bin/sh): no Windows, não há")
        self._temporaria = pasta is None
        self.pasta = Path(tempfile.mkdtemp(prefix="sh-placa-simulada-")) if pasta is None else Path(pasta)
        try:
            self.raiz, firmware = montar_sistema_falso(self.pasta, cenario, amostras_por_bloco=amostras_por_bloco)
        except BaseException:
            if self._temporaria:
                shutil.rmtree(self.pasta, ignore_errors=True)
            raise
        self.cenario, self.usuario, self.senha = cenario, usuario, senha
        self.senha_do_sudo, self.enderecos, self.vazao_bytes_s = senha_do_sudo, enderecos, vazao_bytes_s
        self.home = firmware.parent
        self.comandos: list[str] = []
        self.conexoes: set[asyncssh.SSHServerConnection] = set()
        self._rodando: set[asyncio.Task] = set()            # os comandos ainda rodando (o _rodar de cada um)
        self._servidores: list[asyncssh.SSHAcceptor] = []
        self._livre_em = 0.0                               # quando o "cabo" fica livre de novo (a vazão do SFTP)
        self._ja_caiu: set[str] = set()                    # os arquivos que já cortaram uma transferência
        self.porta = 0
        self.chave_do_host = asyncssh.generate_private_key("ssh-ed25519")
        binarios = self.pasta / "bin"
        binarios.mkdir(exist_ok=True)
        (binarios / "python3").symlink_to(sys.executable)
        pgrep = PGREP.format(python=sys.executable, pgrep=shutil.which("pgrep") or "/usr/bin/pgrep")
        for nome, roteiro in (("sudo", SUDO), ("config-pin", CONFIG_PIN), ("pgrep", pgrep)):
            (binarios / nome).write_text(roteiro)
            (binarios / nome).chmod(0o755)
        self.ram = self.pasta / "ram"                    # a /dev/shm da placa (o SHAN_RAM do sudo)
        self.ram.mkdir(exist_ok=True)
        self.ambiente = {"HOME": str(self.home), "PATH": f"{binarios}{os.pathsep}{os.environ.get('PATH', '')}",
                         "SHAN_RAIZ": str(self.raiz), "LANG": "C.UTF-8", "SHAN_SENHA_DO_SUDO": self.senha_do_sudo,
                         "SHAN_RAM": str(self.ram),
                         "SHAN_PROCESSOS": str(processos if processos is not None else self.pasta)}

    @property
    def destino(self) -> Destino:
        return Destino(self.enderecos[0], self.porta, self.usuario)

    @property
    def authorized_keys(self) -> Path:
        return self.home / ".ssh" / "authorized_keys"

    @property
    def comandos_de_root(self) -> list[str]:
        """O que o sudo rodou: os argumentos de cada comando, juntos (um comando de várias linhas é um só)."""
        arquivo = self.home / ".sudo-comandos"
        return arquivo.read_text().split("\0")[:-1] if arquivo.exists() else []

    @property
    def impressao(self) -> str:
        return self.chave_do_host.get_fingerprint()

    def acesso(self) -> tuple[ChaveDoAplicativo, HostsConhecidos]:
        """A chave e o ``known_hosts`` com que o aplicativo entra (gerados na primeira vez, numa pasta só do dono, dentro
        da do simulador): a chave fica no ``authorized_keys`` da placa, e a chave de host, fixada. Depois do
        :meth:`iniciar` (a porta faz parte do nome no ``known_hosts``)."""
        from .chaves import ChaveDoAplicativo, HostsConhecidos

        pasta = self.pasta / "cliente"
        chave = ChaveDoAplicativo(pasta)
        linha = chave.linha_publica
        self.authorized_keys.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        ja = self.authorized_keys.read_text().splitlines() if self.authorized_keys.exists() else []
        if linha not in ja:
            with open(self.authorized_keys, "a", encoding="ascii") as f:
                f.write(linha + "\n")
            self.authorized_keys.chmod(0o600)
        hosts = HostsConhecidos(pasta / "known_hosts")
        hosts.fixar(self.destino.host, self.porta, self.chave_do_host)
        return chave, hosts

    async def iniciar(self) -> ServidorDoSimulador:
        """Escuta em cada endereço, na porta que o primeiro ganhou (a porta 0 daria uma a cada endereço) ou na já
        escolhida."""
        for endereco in self.enderecos:
            servidor = await asyncssh.create_server(
                self._lado_do_servidor, endereco, self.porta, server_host_keys=self._chaves_do_host(),
                process_factory=self._rodar, encoding=None, reuse_address=True,
                sftp_factory=lambda canal: _SFTPDoSimulador(canal, self),
                line_editor=False)               # o PTY é o do sistema, como o sshd da placa
            self._servidores.append(servidor)
            self.porta = servidor.sockets[0].getsockname()[1]
        return self

    async def parar(self) -> None:
        """Derruba as conexões e para de escutar; volta com todo comando morto e colhido (com o canal fechado, o
        vigia de cada um mata o grupo dele), para nenhum processo sobreviver à placa."""
        self.derrubar()
        for servidor in self._servidores:
            servidor.close()
            await servidor.wait_closed()
        self._servidores = []
        await asyncio.gather(*self._rodando, return_exceptions=True)

    async def fechar(self) -> None:
        """Para e, se a pasta é dele (a temporária), a apaga."""
        await self.parar()
        if self._temporaria:
            await asyncio.to_thread(shutil.rmtree, self.pasta, True)

    def derrubar(self) -> None:
        """Todas as conexões caem de uma vez, sem despedida (o cabo que solta)."""
        for conexao in list(self.conexoes):
            conexao.abort()

    async def __aenter__(self) -> ServidorDoSimulador:
        return await self.iniciar()

    async def __aexit__(self, *_excecao) -> None:
        await self.parar()

    # ------------------------------------------------------------------ o que os testes trocam

    def _lado_do_servidor(self) -> asyncssh.SSHServer:
        return _LadoDoServidor(self)

    def _chaves_do_host(self) -> list[asyncssh.SSHKey]:
        return [self.chave_do_host]

    async def _sem_comando(self, processo: asyncssh.SSHServerProcess) -> None:
        """O ``ssh`` sem comando (um terminal): a placa simulada não tem, porque o shell seria o deste computador."""
        processo.stderr.write(b"o simulador da placa nao tem terminal: o shell seria o deste computador\n")
        processo.exit(1)

    # ------------------------------------------------------------------ os comandos

    async def _rodar(self, processo: asyncssh.SSHServerProcess) -> None:
        """Um comando num shell de verdade, num grupo de processos só dele, com o stdin, o stdout e o stderr ligados
        ao canal. Se o canal fecha antes (o cliente desistiu, a conexão caiu), o grupo inteiro é morto: o ``dash`` não
        faz ``exec`` do último comando, e um ``sleep 30`` sobreviveria ao shell, com os pipes abertos."""
        tarefa = asyncio.current_task()
        self._rodando.add(tarefa)
        try:
            if processo.command is None:
                await self._sem_comando(processo)
            else:
                await self._rodar_comando(processo)
        finally:
            self._rodando.discard(tarefa)

    async def _rodar_comando(self, processo: asyncssh.SSHServerProcess) -> None:
        comando = processo.command
        self.comandos.append(comando)
        shell = await asyncio.create_subprocess_exec(
            "/bin/sh", "-c", comando, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=self.home, env=self.ambiente, start_new_session=True)
        entrada = asyncio.create_task(_bombear_entrada(processo, shell))
        vigia = asyncio.create_task(matar_quando_o_canal_fechar(processo, shell))
        copias = [asyncio.create_task(_copiar(shell.stdout, processo.stdout)),
                  asyncio.create_task(_copiar(shell.stderr, processo.stderr))]
        try:
            await asyncio.gather(*copias)
            processo.exit(await shell.wait())
        except (asyncssh.Error, OSError):
            pass
        finally:
            for auxiliar in (entrada, vigia, *copias):
                auxiliar.cancel()
            matar(shell)
            shell.stdin.close()
            await asyncio.gather(entrada, vigia, *copias, return_exceptions=True)
            # O que sobrou nos pipes (um comando cortado no meio: o cliente fechou o canal e a cópia parou) é lido até
            # o fim, com o grupo já morto: os transportes do subprocesso fecham com o laço vivo, e não no coletor de
            # lixo, depois dele (um aviso no Python 3.10).
            await asyncio.gather(shell.stdout.read(), shell.stderr.read(), return_exceptions=True)
            await shell.wait()

    # ------------------------------------------------------------------ o SFTP

    async def _esperar_a_vazao(self, n: int) -> None:
        """Os ``n`` bytes passam pelo "cabo" na :attr:`vazao_bytes_s`, um bloco depois do outro (os pedidos em paralelo
        do SFTP dividem a vazão, como no USB)."""
        if not self.vazao_bytes_s or n <= 0:
            return
        agora = asyncio.get_running_loop().time()
        self._livre_em = max(agora, self._livre_em) + n / self.vazao_bytes_s
        await asyncio.sleep(self._livre_em - agora)

    def _leu(self, caminho: str, ate: int, tamanho: int) -> None:
        """No cenário da conexão que cai: a primeira leitura de um arquivo além de :data:`FRACAO_DA_QUEDA` dele derruba
        tudo (logo depois de a resposta sair)."""
        if self.cenario != "conexao_instavel" or not tamanho or caminho in self._ja_caiu:
            return
        if ate >= FRACAO_DA_QUEDA * tamanho:
            self._ja_caiu.add(caminho)
            asyncio.get_running_loop().call_soon(self.derrubar)


class _LadoDoServidor(asyncssh.SSHServer):
    """A autenticação (as chaves do ``authorized_keys`` da placa; a senha, se houver) e as conexões abertas."""

    def __init__(self, dono: ServidorDoSimulador):
        self.dono = dono
        self.conexao: asyncssh.SSHServerConnection | None = None
        self._queda: asyncio.TimerHandle | None = None

    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
        self.conexao = conn
        self.dono.conexoes.add(conn)
        if self.dono.cenario == "conexao_instavel":
            self._queda = asyncio.get_running_loop().call_later(QUEDA_A_CADA_S, conn.abort)

    def connection_lost(self, exc: Exception | None) -> None:
        self.dono.conexoes.discard(self.conexao)
        if self._queda is not None:
            self._queda.cancel()

    def begin_auth(self, username: str) -> bool:
        if self.dono.authorized_keys.exists():
            self.conexao.set_authorized_keys(str(self.dono.authorized_keys))   # lido de novo a cada conexão
        return True

    def password_auth_supported(self) -> bool:
        return self.dono.senha is not None

    def validate_password(self, username: str, password: str) -> bool:
        return self.dono.senha is not None and username == self.dono.usuario and password == self.dono.senha


class _SFTPDoSimulador(asyncssh.SFTPServer):
    """O SFTP da placa: o do asyncssh, na vazão do USB, e com a queda no meio do cenário da conexão que cai."""

    def __init__(self, canal: asyncssh.SSHServerChannel, dono: ServidorDoSimulador):
        super().__init__(canal)
        self.dono = dono
        self._abertos: dict[object, tuple[str, int]] = {}

    def open(self, path: bytes, pflags: int, attrs: asyncssh.SFTPAttrs) -> object:
        arquivo = super().open(path, pflags, attrs)
        with contextlib.suppress(OSError, AttributeError):
            self._abertos[arquivo] = (os.fsdecode(path), os.fstat(arquivo.fileno()).st_size)
        return arquivo

    def close(self, file_obj: object) -> None:
        self._abertos.pop(file_obj, None)
        super().close(file_obj)

    async def read(self, file_obj: object, offset: int, size: int) -> bytes:
        dados = super().read(file_obj, offset, size)
        await self.dono._esperar_a_vazao(len(dados))
        caminho, tamanho = self._abertos.get(file_obj, ("", 0))
        self.dono._leu(caminho, offset + len(dados), tamanho)
        return dados


async def _bombear_entrada(processo: asyncssh.SSHServerProcess, shell: asyncio.subprocess.Process) -> None:
    try:
        while dados := await processo.stdin.read(65536):
            shell.stdin.write(dados)
            await shell.stdin.drain()
    except (asyncssh.Error, OSError):
        pass
    finally:
        shell.stdin.close()


async def _copiar(origem: asyncio.StreamReader, destino) -> None:
    while dados := await origem.read(65536):
        destino.write(dados)


async def matar_quando_o_canal_fechar(processo: asyncssh.SSHServerProcess, shell: asyncio.subprocess.Process) -> None:
    await processo.channel.wait_closed()
    matar(shell)


def matar(shell: asyncio.subprocess.Process) -> None:
    """O shell e o que ele rodou (o grupo dele), se ainda está de pé."""
    if shell.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(shell.pid, signal.SIGKILL)
