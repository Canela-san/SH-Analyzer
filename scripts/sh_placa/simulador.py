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

import json
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

from . import capturas_simuladas
from .agente import ClienteDoAgente, TransporteLocal
from .capturas_simuladas import Sistema, gravar_captura
from .cenarios import CENARIOS, Cenario  # noqa: F401 (o Cenario, para quem importa daqui)
from .ler_adc_simulado import MARCA_DA_PRU_QUE_NAO_SOBE
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

KMSG = """6,120,1210334,-;random: crng init done
6,121,5104871,-;NET: Registered protocol family 10
6,330,1852353605,-;remoteproc remoteproc1: stopped remote processor 4a334000.pru
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
espaço na frente, que são do registro de cima), com as mensagens da PRU de uma captura, o USB, um erro do cartão e
duas do boot que não importam."""

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


SETORES_DO_CARTAO = 7_471_104
INICIO_DA_PARTICAO = 8192
SETORES_DA_PARTICAO = 7_462_912
"""O eMMC da placa de verdade (o ``/sys/block/mmcblk1``, 19/11/2026): a partição já ocupa o cartão inteiro."""
SETORES_DO_CARTAO_GRANDE = 30_535_680
"""No cartão cheio: um cartão de 16 GB com a imagem de 4 GB gravada, sem a partição expandida (o caso de sempre de
"cartão cheio" num cartão grande)."""
EXPANDIR_A_PARTICAO = r"""#!/bin/sh
# O grow_partition.sh da placa simulada: a partição da raiz até o fim do cartão, no próximo boot (como o de verdade,
# que muda a tabela de partições e deixa o sistema de arquivos crescer depois do reinício). Só o root.
[ "${SHAN_COMO_ROOT:-}" = 1 ] || { echo "grow_partition.sh: precisa do root" >&2; exit 1; }
b="$SHAN_RAIZ/sys/block/mmcblk1"
echo $(( $(cat "$b/size") - $(cat "$b/mmcblk1p1/start") )) > "$SHAN_RAIZ/run/simulador/particao"
echo "a partição mmcblk1p1 vai até o fim do cartão: o sistema de arquivos cresce no próximo boot"
"""
JOURNALCTL = r"""#!/bin/sh
# O journalctl da placa simulada: o diário falso; com -f, o que chegar nele; o --vacuum-* apaga os arquivados (só o
# root). Fica na raiz falsa (o agente) e no PATH dos comandos dela: um "sudo journalctl" da placa simulada nunca
# chega ao journalctl deste computador.
r="${SHAN_RAIZ:-${0%/bin/journalctl}}"
arquivo="$r/var/log/journal-do-simulador.json"
case " $* " in *" -f "*) exec tail -n 0 -f "$arquivo" ;; esac
case " $* " in *" --vacuum-"*)
    [ "${SHAN_COMO_ROOT:-}" = 1 ] || { echo "Failed to vacuum: Permission denied" >&2; exit 1; }
    rm -f "$r"/var/log/journal/*/*.journal~; echo "Vacuuming done"; exit 0 ;;
esac
cat "$arquivo"
"""
APT_GET = r"""#!/bin/sh
# O apt-get da placa simulada: só o "clean" (o cache dos pacotes baixados), e só o root.
[ "$1" = clean ] || { echo "E: o apt-get da placa simulada só faz o clean" >&2; exit 100; }
[ "${SHAN_COMO_ROOT:-}" = 1 ] || { echo "E: Could not open lock file /var/cache/apt/archives/lock - open (13: Permission denied)" >&2; exit 100; }
rm -f "$SHAN_RAIZ"/var/cache/apt/archives/*.deb
"""
VERSAO_MODELO = "SHAN-VERSAO-MODELO"
"""No modelo do ``ler_adc`` (``run/simulador/ler_adc.modelo``): o lugar da versão, que o ``make`` da placa simulada
troca pela da pasta que ele compila."""
MARCA_DO_FIRMWARE_ANTIGO = "SHAN_SEM_SAIDA_CONTINUA"
"""No ``ler_adc.c`` da placa simulada: o firmware de antes da saída contínua (o ``make`` dela compila um ``ler_adc``
sem o ``-o -``)."""
MARCA_DE_FALHA_DE_COMPILACAO = "SHAN_FALHA_DE_COMPILACAO"
"""Num arquivo do código da placa simulada: o ``make`` dela falha (o erro de compilação de uma atualização)."""
SERVICOS = {
    "cloud9.socket": ["active", "listening", "enabled", 0, "Cloud9 IDE"],
    "cloud9.service": ["inactive", "dead", "static", 0, "Cloud9 IDE"],
    "bonescript.socket": ["active", "listening", "enabled", 0, "BoneScript API"],
    "bonescript.service": ["inactive", "dead", "disabled", 0, "BoneScript API"],
    "bonescript-autorun.service": ["active", "running", "enabled", 894, "Bonescript autorun"],
    "nodered.socket": ["active", "listening", "enabled", 0, "Node-RED"],
    "nodered.service": ["inactive", "dead", "disabled", 0, "Node-RED"],
    "nginx.service": ["active", "running", "enabled", 1015, "A high performance web server"],
    "ssh.service": ["active", "running", "enabled", 946, "OpenBSD Secure Shell server"],
    "dnsmasq.service": ["active", "running", "disabled", 1115, "dnsmasq - A lightweight DHCP and caching DNS server"],
    "avahi-daemon.service": ["active", "running", "enabled", 872, "Avahi mDNS/DNS-SD Stack"],
    "connman.service": ["active", "running", "enabled", 887, "Connection service"],
    "systemd-timesyncd.service": ["active", "running", "enabled", 843, "Network Time Synchronization"],
    "serial-getty@ttyGS0.service": ["active", "running", "enabled", 4357, "Serial Getty on ttyGS0"],
}
"""Os serviços da imagem na placa simulada (``ActiveState``, ``SubState``, ``UnitFileState``, ``MainPID``,
``Description``), como os da placa de verdade em 19/11/2026; o ``systemctl`` dela os lê e os muda."""
PROCESSOS = {1: ("systemd", "/sbin/init", 0, 1674), 894: ("nodejs", "/usr/bin/nodejs autorun.js", 0, 9529),
             946: ("sshd", "/usr/sbin/sshd -D", 0, 1194), 1015: ("nginx", "nginx: worker process", 33, 1389)}
"""``pid: (nome, linha de comando, uid, páginas residentes)`` dos processos da placa simulada."""
REDE = {"usb0": ("98:5d:ad:42:e4:7e", "192.168.7.2/24", "fe80::9a5d:adff:fe42:e47e/64"),
        "usb1": ("98:5d:ad:42:e4:82", "192.168.6.2/24", "fe80::9a5d:adff:fe42:e482/64"),
        "eth0": ("98:5d:ad:42:e4:7c", None, None)}


MAKE = r"""#!@PYTHON@
# O make da placa simulada: "compila" o firmware da pasta de agora (o ler_adc, do modelo da placa com a versão da
# pasta; o fw_pru.out, do código da PRU) e falha com a marca de erro de compilação num arquivo do código.
import hashlib, os, shlex, sys
from pathlib import Path

raiz, pasta = Path(os.environ["SHAN_RAIZ"]), Path.cwd()
alvos = [a for a in sys.argv[1:] if not a.startswith("-")]
versao = (pasta / "VERSAO").read_text().strip() if (pasta / "VERSAO").is_file() else "sem-versao"
if alvos[:1] == ["clean"]:
    for nome in ("ler_adc", "fw_pru.out", "pru_main.obj", "spi_core.obj", "pru_core.map"):
        (pasta / nome).unlink(missing_ok=True)
    print("rm -f ler_adc fw_pru.out *.obj *.map")
    sys.exit(0)
if alvos[:1] == ["versao"]:
    print(versao)
    sys.exit(0)
for nome in ("ler_adc.c", "memoria_pru.h", "pru_main.c", "spi_core.asm"):
    if not (pasta / nome).is_file():
        print("make: *** No rule to make target '%s', needed by 'ler_adc'.  Stop." % nome, file=sys.stderr)
        sys.exit(2)
for arquivo in sorted(pasta.iterdir()):
    if arquivo.suffix in (".c", ".h", ".asm") and "@FALHA@" in arquivo.read_text(errors="replace"):
        print("%s:1:1: error: @FALHA@" % arquivo.name, file=sys.stderr)
        print("make: *** [Makefile:40: ler_adc] Error 1", file=sys.stderr)
        sys.exit(2)
print("gcc -O2 -Wall -Wextra -std=gnu11 -o ler_adc ler_adc.c")
texto = (raiz / "run/simulador/ler_adc.modelo").read_text()
texto = texto.replace("SHAN_VERSAO=@MODELO@", "SHAN_VERSAO=" + shlex.quote(versao))
if "@ANTIGO@" in (pasta / "ler_adc.c").read_text(errors="replace"):
    texto = texto.replace("SHAN_ANTIGO=0", "SHAN_ANTIGO=1")
(pasta / "ler_adc").write_text(texto)
(pasta / "ler_adc").chmod(0o755)
print("clpru --silicon_version=3 -o2 pru_main.c spi_core.asm -o fw_pru.out")
codigo = b"".join((pasta / nome).read_bytes() for nome in ("pru_main.c", "spi_core.asm", "memoria_pru.h"))
fw = b"\x7fELF" + hashlib.sha256(codigo).digest()
if b"@PRU@" in codigo:
    fw += b"@PRU@"
(pasta / "fw_pru.out").write_bytes(fw)
"""
"""O ``make`` da placa simulada (o do ``firmware/Makefile``: ``clean``, ``versao`` e a compilação)."""

TEE = r"""#!/bin/sh
# O tee da placa simulada: o deste computador, menos no remoteproc da PRU, que o "kernel" dela interpreta (o start, o
# stop e o nome do firmware, com os erros do kernel de verdade).
alvo=
for a in "$@"; do
    case "$a" in */sys/class/remoteproc/remoteproc*/state|*/sys/class/remoteproc/remoteproc*/firmware) alvo=$a ;; esac
done
[ -n "$alvo" ] || exec @TEE@ "$@"
pedido=$(cat)
printf '%s\n' "$pedido"
d=$(dirname "$alvo")
estado=$(cat "$d/state" 2>/dev/null)
case "$alvo" in
    */firmware)
        [ "$estado" = running ] && { echo "tee: $alvo: Device or resource busy" >&2; exit 1; }
        printf '%s\n' "$pedido" > "$alvo"
        exit 0 ;;
esac
case "$pedido" in
    start)
        [ "$estado" = running ] && { echo "tee: $alvo: Device or resource busy" >&2; exit 1; }
        fw="$SHAN_RAIZ/lib/firmware/$(cat "$d/firmware")"
        if [ "${SHAN_COMO_ROOT:-}" != 1 ] && [ -z "$(find "$fw" -perm -0004 2>/dev/null)" ]; then
            echo "remoteproc remoteproc1: loading /lib/firmware/$(cat "$d/firmware") failed with error -13" \
                >> "$SHAN_RAIZ/dev/kmsg"
            echo "tee: $alvo: Permission denied" >&2      # o kernel lê o firmware como quem pede o start
            exit 1
        fi
        if grep -q @PRU@ "$fw" 2>/dev/null; then
            echo crashed > "$d/state"
            echo "tee: $alvo: Invalid argument" >&2
            exit 1
        fi
        echo running > "$d/state" ;;
    stop)
        [ "$estado" = running ] || { echo "tee: $alvo: Invalid argument" >&2; exit 1; }
        echo offline > "$d/state" ;;
    *) echo "tee: $alvo: Invalid argument" >&2; exit 1 ;;
esac
"""
"""O ``tee`` da placa simulada: o kernel do remoteproc (o ``echo start | tee .../state`` do ``setup.sh``)."""

SYSTEMCTL = r"""#!@PYTHON@
# O systemctl da placa simulada: os serviços da imagem (run/simulador/servicos.json), o reinício e o desligar (um
# pedido que o servidor do simulador atende). O que muda a placa só com o sudo, como o de verdade.
import json, os, sys
from pathlib import Path

raiz = Path(os.environ["SHAN_RAIZ"])
arquivo = raiz / "run/simulador/servicos.json"
servicos = json.loads(arquivo.read_text())
args = [a for a in sys.argv[1:] if a not in ("--no-pager", "--quiet", "-q", "--no-block")]
como_root = os.environ.get("SHAN_COMO_ROOT") == "1"
if not args:
    sys.exit(1)
acao, resto = args[0], args[1:]
if acao == "show":
    props, unidades, i = None, [], 0
    while i < len(resto):
        if resto[i] == "-p":
            props, i = resto[i + 1].split(","), i + 2
            continue
        unidades.append(resto[i])
        i += 1
    blocos = []
    for u in unidades:
        v = servicos.get(u)
        d = dict(Id=u, Description=v[4] if v else u, LoadState="loaded" if v else "not-found",
                 ActiveState=v[0] if v else "inactive", SubState=v[1] if v else "dead",
                 UnitFileState=v[2] if v else "", MainPID=str(v[3] if v and v[0] == "active" else 0))
        blocos.append("\n".join("%s=%s" % (k, d[k]) for k in (props or d) if k in d))
    print("\n\n".join(blocos))
    sys.exit(0)
if acao == "is-active":
    v = servicos.get(resto[0]) if resto else None
    print(v[0] if v else "inactive")
    sys.exit(0 if v and v[0] == "active" else 3)
if not como_root:
    print("Failed to %s: Interactive authentication required." % acao, file=sys.stderr)
    sys.exit(4)
if acao in ("reboot", "poweroff"):
    (raiz / "run/simulador/pedido").write_text(acao)
    sys.exit(0)
if acao in ("enable", "disable", "start", "stop", "restart"):
    agora = "--now" in resto
    for u in (a for a in resto if not a.startswith("-")):
        if u not in servicos:
            print("Failed to %s unit: Unit %s not found." % (acao, u), file=sys.stderr)
            sys.exit(5)
        s = servicos[u]
        if acao == "enable" and s[2] != "static":
            s[2] = "enabled"
        if acao == "disable" and s[2] != "static":
            s[2] = "disabled"
        if acao in ("start", "restart") or (acao == "enable" and agora):
            s[0], s[1] = "active", "listening" if u.endswith(".socket") else "running"
        if acao == "stop" or (acao == "disable" and agora):
            s[0], s[1] = "inactive", "dead"
    arquivo.write_text(json.dumps(servicos, indent=1))
    sys.exit(0)
print("Unknown operation '%s'." % acao, file=sys.stderr)
sys.exit(1)
"""
"""O ``systemctl`` da placa simulada."""

CHPASSWD = r"""#!/bin/sh
# O chpasswd da placa simulada: "usuário:senha" pelo stdin; só o root (o sudo dela).
[ "${SHAN_COMO_ROOT:-}" = 1 ] || { echo "chpasswd: Permission denied." >&2; exit 1; }
IFS= read -r linha || exit 1
[ "${linha%%:*}" = debian ] || { echo "chpasswd: line 1: user '${linha%%:*}' does not exist" >&2; exit 1; }
printf '%s' "${linha#*:}" > "$HOME/@SENHA@"
"""
"""O ``chpasswd`` da placa simulada: a senha nova vale para o sudo e para o SSH dela."""


def _ip() -> str:
    """O ``ip`` da placa simulada: o ``ip -o addr show`` das interfaces dela."""
    linhas = []
    for i, (nome, (_mac, v4, v6)) in enumerate(REDE.items(), 5):
        for endereco in (v4, v6):
            if endereco:
                familia, escopo = ("inet6", "link") if ":" in endereco else ("inet", "global")
                linhas.append(f"{i}: {nome}    {familia} {endereco} scope {escopo} {nome}\\       valid_lft forever "
                              "preferred_lft forever")
    return "#!/bin/sh\n# O ip da placa simulada.\ncat <<'FIM'\n" + "\n".join(linhas) + "\nFIM\n"


def programas_da_placa(senha_trocada: str = ".senha-da-placa") -> dict[str, str]:
    """Os programas da placa simulada que ficam no PATH dos comandos dela (o ``sudo``, o ``config-pin`` e o ``pgrep``
    à parte): o ``make``, o ``tee`` do kernel, o ``systemctl``, o ``chpasswd``, o ``ip``, o ``apt-get`` e o
    ``journalctl``. Todo programa que muda o sistema e que um comando da placa simulada roda tem de estar aqui: senão,
    ele roda o deste computador."""
    trocas = {"@PYTHON@": sys.executable, "@FALHA@": MARCA_DE_FALHA_DE_COMPILACAO, "@MODELO@": VERSAO_MODELO,
              "@ANTIGO@": MARCA_DO_FIRMWARE_ANTIGO, "@PRU@": MARCA_DA_PRU_QUE_NAO_SOBE.decode(),
              "@TEE@": shutil.which("tee") or "/usr/bin/tee", "@SENHA@": senha_trocada}
    programas = {"make": MAKE, "tee": TEE, "systemctl": SYSTEMCTL, "chpasswd": CHPASSWD, "ip": _ip(),
                 "apt-get": APT_GET, "journalctl": JOURNALCTL}
    for nome, texto in programas.items():
        for marca, valor in trocas.items():
            texto = texto.replace(marca, valor)
        programas[nome] = texto
    return programas


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
    _escrever(raiz, "/proc/sys/kernel/random/boot_id", f"{uuid.uuid4()}\n")
    _escrever(raiz, "/proc/loadavg", "0.31 0.24 0.18 1/120 999\n")
    _escrever(raiz, "/proc/meminfo", "MemTotal:  478796 kB\nMemFree:  250000 kB\nMemAvailable:  319488 kB\n")
    _escrever(raiz, "/sys/class/thermal/thermal_zone0/temp", "52000\n")
    _escrever(raiz, "/proc/stat", "cpu  1200 0 640 90000 120 0 14 0 0 0\ncpu0 1200 0 640 90000 120 0 14 0 0 0\n")
    for pid, (nome, linha, uid, paginas) in PROCESSOS.items():
        _escrever(raiz, f"/proc/{pid}/stat", f"{pid} ({nome}) S 1 {pid} {pid} 0 -1 0 0 0 0 0 40 12 0 0 20 0 1 0 "
                                            f"100 1000000 {paginas} 0\n")
        _escrever(raiz, f"/proc/{pid}/cmdline", linha.replace(" ", "\0") + "\0")
        _escrever(raiz, f"/proc/{pid}/status", f"Name:\t{nome}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n"
                                              f"VmRSS:\t{paginas * 4} kB\n")
    _escrever(raiz, "/etc/hostname", "beaglebone\n")
    _escrever(raiz, "/etc/timezone", "Etc/UTC\n")
    for nome, (mac, ipv4, _ipv6) in REDE.items():
        _escrever(raiz, f"/sys/class/net/{nome}/operstate", ("up" if ipv4 else "down") + "\n")
        _escrever(raiz, f"/sys/class/net/{nome}/address", mac + "\n")
        _escrever(raiz, f"/sys/class/net/{nome}/statistics/rx_bytes", "1119687\n" if ipv4 else "0\n")
        _escrever(raiz, f"/sys/class/net/{nome}/statistics/tx_bytes", "1121178\n" if ipv4 else "0\n")
    _escrever(raiz, "/sys/class/net/lo/operstate", "unknown\n")
    cheio = cenario == "disco_cheio"
    _escrever(raiz, "/sys/block/mmcblk1/size", f"{SETORES_DO_CARTAO_GRANDE if cheio else SETORES_DO_CARTAO}\n")
    _escrever(raiz, "/sys/block/mmcblk1/mmcblk1p1/size", f"{SETORES_DA_PARTICAO}\n")
    _escrever(raiz, "/sys/block/mmcblk1/mmcblk1p1/start", f"{INICIO_DA_PARTICAO}\n")
    _escrever(raiz, "/opt/scripts/tools/grow_partition.sh",
              EXPANDIR_A_PARTICAO if cheio else "#!/bin/sh\necho 'a partição já ocupa o cartão'\n", executavel=True)
    _escrever(raiz, "/run/log/journal/0123456789abcdef/system.journal", b"LPKSHHRH" + b"\0" * 4088)
    (raiz / "var" / "cache" / "apt" / "archives").mkdir(parents=True, exist_ok=True)
    if cheio:
        _o_que_limpar(raiz, Path(pasta) / "home" / "debian", agora)
    _escrever(raiz, "/run/simulador/internet", "nao\n")
    _escrever(raiz, "/run/simulador/servicos.json", json.dumps(SERVICOS, indent=1))
    programas = programas_da_placa()
    for nome in ("ip", "systemctl"):                 # os que o agente roda (os do PATH ficam com o servidor)
        _escrever(raiz, f"/bin/{nome}", programas[nome], executavel=True)
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
    _escrever(raiz, "/bin/journalctl", JOURNALCTL, executavel=True)

    firmware.mkdir(parents=True, exist_ok=True)
    versao = VERSAO_ANTIGA if cenario == "firmware_antigo" else versao_firmware
    (firmware / "VERSAO").write_text(versao + "\n")
    antigo = cenario == "firmware_antigo"
    fontes = {"ler_adc.c": "/* o ler_adc da placa simulada" + (f" ({MARCA_DO_FIRMWARE_ANTIGO})" if antigo else "")
                           + " */\n", "pru_main.c": "/* a PRU0 */\n",
              "spi_core.asm": "; o laço da PRU0\n",
              "memoria_pru.h": "// o contrato ARM <-> PRU\n#define VERSAO_PROTOCOLO_PRU 5u\n",
              "Makefile": "# o Makefile da placa simulada (o make dela é o do simulador: servidor_do_simulador.py)\n"}
    for nome, texto in fontes.items():
        (firmware / nome).write_text(texto, encoding="utf-8")
        os.utime(firmware / nome, (FONTES_COMPILADAS_EM, FONTES_COMPILADAS_EM))
    fw_pru = b"\x7fELF" + b"o fw_pru.out da placa simulada".ljust(60, b"\x00")
    bloco = amostras_por_bloco or capturas_simuladas.BLOCO_DAS_CAPTURAS
    _escrever(raiz, "/run/simulador/ler_adc.modelo", roteiro_do_ler_adc(
        "normal" if antigo else cenario, bloco, _sistema(cenario, VERSAO_MODELO)))
    if cenario != "sem_compilar":
        ler_adc = firmware / "ler_adc"
        ler_adc.write_text(roteiro_do_ler_adc(cenario, bloco, _sistema(cenario, versao), antigo=antigo))
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


def _esparso(caminho: Path, tamanho: int) -> None:
    """Um arquivo de ``tamanho`` bytes que não ocupa o disco deste computador (o ``truncate``)."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "wb") as f:
        f.truncate(tamanho)


def _o_que_limpar(raiz: Path, home: Path, agora: float) -> None:
    """No cartão cheio: o cache do ``apt`` (três pacotes), o diário guardado no cartão (o de agora e dois arquivados)
    e duas tarefas da manutenção que terminaram e ficaram."""
    for nome, mb in (("python3-numpy_1.16.2-1_armhf.deb", 22), ("nodejs_10.24.0-1_armhf.deb", 31),
                     ("linux-image-4.19.94-ti-r73_1buster_armhf.deb", 38)):
        _esparso(raiz / "var/cache/apt/archives" / nome, mb * 1024 * 1024)
    diario = raiz / "var/log/journal/0123456789abcdef"
    _esparso(diario / "system.journal", 8 * 1024 * 1024)
    for i in (1, 2):
        _esparso(diario / f"system@00059f0c8a7e2b{i}d-000000000000{i}a2f.journal~", 40 * 1024 * 1024)
    for i, horas in ((1, 50), (2, 26)):
        pasta = home / ".sh-analyzer" / "tarefas" / f"manutencao-antiga-2026111{i}-0930{i}0-c0d{i}"
        pasta.mkdir(parents=True, exist_ok=True)
        for arquivo, conteudo in (("tipo", "manutencao-antiga"), ("titulo", f"Uma tarefa antiga ({i})"),
                                  ("inicio", f"{agora - horas * 3600:.0f}"), ("pid", "99999"), ("codigo", "0"),
                                  ("passos", ""), ("resultado", ""), ("log", "terminou\n")):
            (pasta / arquivo).write_text(conteudo + ("\n" if conteudo and arquivo != "log" else ""))


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


def chaves_do_uenv(texto: str) -> dict[str, str]:
    """As chaves ativas de um ``uEnv.txt`` (a última vale, como no u-boot)."""
    chaves = {}
    for linha in texto.splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, _, valor = linha.partition("=")
            chaves[chave.strip()] = valor.strip()
    return chaves


def aplicar_o_boot(raiz: Path, desligada_s: float = 40.0) -> None:
    """O boot da placa simulada, depois de um reinício (o ``systemctl reboot``): o u-boot lê o ``/boot/uEnv.txt`` e
    monta a linha do kernel (o ``optargs`` logo depois do console, o ``cmdline`` no fim) e os overlays (o da PRU, se o
    ``.dtbo`` existe; o do HDMI, com ou sem o áudio, se o vídeo não está desligado); a PRU0 existe só com o overlay
    dela, e fica parada; os pinos voltam ao ``default`` (o ``config-pin`` não é permanente), e sem o
    ``cape_universal`` nem existem; o relógio volta de onde parou ao desligar (o ``timesyncd`` guarda a hora: atrasado
    o tempo em que a placa ficou desligada) e sem o NTP; o tempo ligada recomeça."""
    try:
        texto = (raiz / "boot/uEnv.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        texto = ""
    u = chaves_do_uenv(texto)
    partes = ["console=ttyO0,115200n8"]
    if u.get("optargs"):
        partes.append(u["optargs"])
    partes.append("bone_capemgr.uboot_capemgr_enabled=1 root=/dev/mmcblk1p1 ro rootfstype=ext4 rootwait")
    if u.get("cmdline"):
        partes.append(u["cmdline"])
    _escrever(raiz, "/proc/cmdline", " ".join(partes) + "\n")
    pasta = raiz / "proc/device-tree/chosen/overlays"
    shutil.rmtree(pasta, ignore_errors=True)
    overlays = []
    if u.get("enable_uboot_overlays") == "1":
        if u.get("disable_uboot_overlay_adc") != "1":
            overlays.append("BB-ADC-00A0")
        if u.get("disable_uboot_overlay_emmc") != "1":
            overlays.append("BB-BONE-eMMC1-01-00A0")
        if u.get("disable_uboot_overlay_video") != "1":
            overlays.append("BB-NHDMI-TDA998x-00A0" if u.get("disable_uboot_overlay_audio") == "1"
                            else "BB-HDMI-TDA998x-00A0")
        pru = u.get("uboot_overlay_pru", "")
        if pru and (raiz / pru.lstrip("/")).is_file():
            overlays.append(Path(pru).name.removesuffix(".dtbo"))
    _escrever(raiz, "/proc/device-tree/chosen/overlays/name", "overlays\x00")
    for overlay in overlays:
        _escrever(raiz, f"/proc/device-tree/chosen/overlays/{overlay}", "Fri Apr  3 23:36:17 2020\x00")
    rproc = raiz / "sys/class/remoteproc/remoteproc1"
    if any(re.search(r"PRU-RPROC", o) for o in overlays):
        _escrever(raiz, "/sys/class/remoteproc/remoteproc1/state", "offline\n")
        _escrever(raiz, "/sys/class/remoteproc/remoteproc1/firmware", "am335x-pru0-fw\n")
        _escrever(raiz, "/sys/class/remoteproc/remoteproc1/name", "4a334000.pru\n")
    else:
        shutil.rmtree(rproc, ignore_errors=True)
    for pino in ("P9_28", "P9_29", "P9_30", "P9_31"):
        estado = f"/sys/devices/platform/ocp/ocp:{pino}_pinmux/state"
        if u.get("enable_uboot_cape_universal") == "1":
            _escrever(raiz, estado, "default\n")
        else:
            shutil.rmtree((raiz / estado.lstrip("/")).parent, ignore_errors=True)
    relogio = raiz / "run/simulador/relogio"
    try:
        desvio = float(relogio.read_text().strip() or 0)
    except (OSError, ValueError):
        desvio = 0.0
    _escrever(raiz, "/run/simulador/relogio", f"{desvio - desligada_s!r}\n")
    (raiz / "run/systemd/timesync/synchronized").unlink(missing_ok=True)
    _escrever(raiz, "/proc/uptime", "35.10 30.02\n")
    _escrever(raiz, "/proc/sys/kernel/random/boot_id", f"{uuid.uuid4()}\n")       # um boot novo
    pedida = raiz / "run/simulador/particao"                      # o grow_partition.sh: a tabela nova vale agora
    try:
        _escrever(raiz, "/sys/block/mmcblk1/mmcblk1p1/size", f"{int(pedida.read_text().strip())}\n")
        pedida.unlink()
    except (OSError, ValueError):
        pass


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
