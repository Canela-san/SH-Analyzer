#!/usr/bin/env python3
"""O agente do SH-Analyzer na BeagleBone: responde em JSON o que o aplicativo do computador pergunta sobre a placa
(docs/gui-plan.md, seções 11.2 e 11.9).

O aplicativo roda, pelo SSH, um comando por vez, com o código deste arquivo pelo stdin (a placa não precisa ter o
agente, e ele fala sempre o protocolo do aplicativo que o mandou, mesmo com um firmware antigo):

    SHAN_PASTA="$HOME"/firmware python3 - versao
    SHAN_PASTA="$HOME"/firmware python3 - saude

**Os comandos:**

* ``versao`` -- a versão do firmware (o arquivo ``VERSAO``) e a do Python;
* ``estado`` -- a placa, o sistema, a PRU, os pinos, a memória dos buffers, o firmware, o disco e as capturas;
* ``saude`` -- o ``estado``, mais o ``/boot/uEnv.txt``, os overlays, as ferramentas, o cabeçalho da captura mais
  recente (o ADC mudo aparece nela) e as **conferências**: cada problema com o nível (``erro`` impede capturar;
  ``aviso``; ``info``), o código, o texto e a correção;
* ``capturas`` -- os ``.bin`` da pasta do firmware e das pastas de coleta, com o resumo do cabeçalho (o título, a
  taxa, os canais, a duração, a integridade), e os ``resumo.csv`` das coletas;
* ``relogio`` -- a hora da placa e se o NTP a sincronizou (o mesmo ``adjtimex`` que o ``ler_adc`` grava no cabeçalho);
* ``logs [N] [--todos]`` -- as últimas N linhas (50) do kernel e do diário do systemd que falam da PRU, dos pinos e
  do firmware, e as de erro (com ``--todos``, todas);
* **os da manutenção** (a Fase 6): ``firmware_arquivos [ARQ...]`` (o hash de cada arquivo do código, os binários e o
  firmware instalado na PRU: o que muda numa atualização), ``anteriores`` (as cópias de segurança do firmware),
  ``inicializacao`` (o ``/boot/uEnv.txt`` inteiro, a linha do kernel, os overlays e os ``.dtbo`` da PRU: o assistente
  de pinos e overlays), ``sistema`` (o nome, o fuso, a memória, o cartão e a partição, o que ocupa o cartão, a rede e
  os serviços da imagem), ``internet`` (se a placa alcança a internet) e ``processos [N]`` (os que mais pesam);
* **os fluxos**, que respondem uma linha JSON por vez até o canal fechar (a primeira é o cabeçalho, com o
  ``protocolo``): ``monitor [INTERVALO] [N]`` (o processador, a memória, a temperatura, a carga e a rede) e
  ``seguir_logs`` (o diário ao vivo).

À mão, na placa, também vale ``python3 ~/firmware/agente/shan_agente.py saude``. O aplicativo lê um objeto JSON do
stdout, com ``"protocolo"`` (a versão deste formato) e ``"agente"``. Um comando desconhecido, ou com argumentos
errados, responde ``{"erro": ...}`` e sai com o código 2. **Nada aqui muda a placa: só lê, como o usuário ``debian``,
sem sudo** (o ``/proc/iomem`` sem os endereços, por isso: só o root os vê; o ``ler_adc`` o confere a cada captura).

**Por que um agente, e não comandos soltos:** respostas estruturadas, num esquema versionado, em vez de texto feito
para pessoas lido com ``sed``; testável no computador (``tests/test_agente.py``) sobre um sistema de arquivos falso;
e uma fonte de verdade só para o diagnóstico da interface e de uma futura CLI.

**Restrições da placa:** só a biblioteca padrão (a placa não tem pip) e compatível com o Python 3.7 (o da imagem
Buster; ``tests/test_agente.py`` confere a sintaxe). Cada campo é lido com cuidado: um arquivo que falta vira ``null``,
nunca um erro, porque cada imagem da BeagleBone tem um conjunto diferente.

**Para os testes e o simulador:** ``SHAN_RAIZ`` troca a raiz de todos os caminhos do sistema (``/proc``, ``/sys``,
``/boot``, ``/lib``, ``/dev/kmsg``, os programas) por uma pasta falsa, e ``SHAN_PASTA`` diz onde está a pasta do
firmware (por padrão, a pasta acima desta; lido pelo stdin, ``~/firmware``). É o que o ``ler_adc`` faz com
``BASE_PINMUX`` e companhia. Com a raiz falsa, o relógio do kernel (o ``adjtimex``, que é deste computador) não vale:
vale o arquivo do ``systemd-timesyncd`` da árvore falsa. O que uma árvore de arquivos não imita fica em
:data:`SIMULADOR`, dentro dela: a hora da placa simulada (a deste computador mais um desvio) e o cartão dela (o
tamanho e o que o sistema ocupa; o resto é a pasta do firmware, contada arquivo por arquivo). Sem a raiz falsa, nada
disso é lido.
"""

from __future__ import annotations

import json
import os
import re
import struct
import sys
import time
import zlib

# O csv, o errno, o subprocess e o ctypes são importados só pelos comandos que os usam: o agente chega pelo stdin e é
# compilado a cada chamada, e no único núcleo da placa cada importação custa (o subprocess, ~50 ms).

PROTOCOLO = 1
AGENTE = "4"

PINOS_DA_PRU = {"P9_28": "pruout", "P9_29": "pruout", "P9_30": "pruin", "P9_31": "pruout"}   # os do setup.sh
REMOTEPROC_PRU0 = "/sys/class/remoteproc/remoteproc1"                                       # o do ler_adc.c
ENDERECO_DA_PRU0 = "4a334000"                                       # o nome do remoteproc da PRU0: 4a334000.pru
NOME_DO_FIRMWARE_DA_PRU = "am335x-pru0-fw"                          # o do setup.sh
FIRMWARE_INSTALADO = "/lib/firmware/" + NOME_DO_FIRMWARE_DA_PRU
ESTADOS_NORMAIS_DA_PRU = ("running", "offline")
"""O remoteproc da PRU0 numa placa boa: ``running`` durante a captura e ``offline`` entre uma e outra (o ``ler_adc``
a liga no começo e a para no fim; visto na placa de verdade, 15/11/2026)."""
PRAZO_DA_PRU_NO_BOOT_S = 180
"""Até quanto tempo depois de ligar a falta da PRU0 no remoteproc é o boot que não terminou (com o overlay da PRU no
``uEnv.txt``): o driver dela aparece perto do fim do boot, e o SSH responde antes. Na placa de verdade (19/11/2026),
aos 71 s, com o boot terminando aos 71 s e o SSH respondendo desde uns 45 s."""
EEPROMS = ("/sys/bus/nvmem/devices/0-00500/nvmem", "/sys/bus/i2c/devices/0-0050/eeprom")
BASE_PINMUX = "/sys/devices/platform/ocp"
FAIXA_DOS_BUFFERS = (0x9F000000, 0x9F3FFFFF)                       # os 16 MB do fim da DDR (memoria_pru.h)
FONTES_DO_LER_ADC = ("ler_adc.c", "memoria_pru.h")                  # as do "mais_antigo" da coleta/campanha.sh
FONTES_DA_PRU = ("pru_main.c", "spi_core.asm", "memoria_pru.h")
DIRETORIOS_DE_PROGRAMAS = ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin")
FERRAMENTAS = ("make", "gcc", "clpru", "config-pin", "dtc", "journalctl")
PACOTES = {"make": "build-essential", "gcc": "build-essential", "clpru": "ti-pru-cgt-installer",
           "config-pin": "bb-cape-overlays", "dtc": "device-tree-compiler"}
"""O pacote de cada ferramenta na imagem da BeagleBoard (o ``dpkg -S`` da placa, 15/11/2026)."""
FERRAMENTAS_DO_SETUP = ("make", "gcc", "clpru", "config-pin")

TAXA_DE_REFERENCIA_BYTES_S = 800000      # 400 kS/s x 2 bytes: quanto disco uma captura gasta por segundo
DISCO_POUCO_KIB = 1024 * 1024            # menos que 1 GiB livre (~22 min a 400 kS/s): aviso
DISCO_MINIMO_KIB = 64 * 1024             # menos que 64 MiB (~1 min): erro
TEMPERATURA_ALTA_C = 75.0
CARGA_ALTA = 1.5                         # a carga média de 1 min num núcleo só: a cópia dos blocos disputa o ARM
MEMORIA_POUCA_KIB = 32 * 1024

TIME_ERROR = 5                           # o adjtimex: o relógio não está sincronizado
STA_UNSYNC = 0x0040

CABECALHO_MAGICO = b"SHAN"
CABECALHO_TAMANHO = 1024                 # o cabeçalho até a v8, e a parte fixa desde a v9
CABECALHO_TAMANHO_V9 = 4096
CABECALHO_TAMANHO_MINIMO_V9 = 1024 + 876 # a parte fixa e a extensão da v9 (supraharmonicos/cabecalho.py)
OFFSET_DO_CRC = {2: 668, 3: 676, 4: 700, 5: 744, 6: 760, 7: 772}    # até a v1, 404; desde a v8, 1020
VALOR_DESCONHECIDO = 0xFFFFFFFF
OFFSET_DOS_MINIMOS_V9 = 1676             # [v9, final] o código mínimo e o máximo de cada canal, em todas as amostras
OFFSET_DOS_MAXIMOS_V9 = 1692
PROFUNDIDADE_DAS_COLETAS = 3             # coleta/, capturas/<sonda>/descartadas/
MANIFESTOS = ("resumo.csv", "pontos_coletados.csv", "teto.csv", "referencia_externa.csv")
LIMITE_DE_CAPTURAS = 2000
LIMITE_DE_LINHAS = 5000

TERMOS_DOS_LOGS = ("remoteproc", "pru", "pinctrl", "pinmux", "mcasp", "capemgr", "uio", "ler_adc", "config-pin",
                   "setup.sh", "coletar", "shan_agente", "usb", "musb", "gadget", "mmc", "ext4")
"""O que é "o que importa" nos logs: a PRU, os pinos, o firmware, o USB (o cabo com mau contato) e o cartão."""
PRIORIDADE_DE_ERRO = 3                   # err, crit, alert e emerg entram sempre
LINHAS_LIDAS_DO_DIARIO = 500
FILTRO_DO_DIARIO = ("SYSLOG_IDENTIFIER=sudo", "+", "PRIORITY=0", "PRIORITY=1", "PRIORITY=2", "PRIORITY=3")
"""O que o ``journalctl`` já entrega filtrado, pelos índices do diário: o ``sudo`` (cada ``ler_adc`` e ``setup.sh``
passa por ele) ou um erro. O da imagem Buster (systemd 241) não tem o ``--grep``, e ler as ~3500 linhas de um boot
para filtrar aqui levava 3 s na placa; assim, 0,1 s (15/11/2026)."""
CHAVE_DO_UENV = re.compile(r"^[A-Za-z0-9_.]+$")
SIMULADOR = "/run/simulador"
"""Só na raiz falsa (``SHAN_RAIZ``): ``relogio``, quantos segundos a hora da placa está adiantada da deste computador
(negativo: atrasada; o acerto do relógio da placa simulada o reescreve), e ``disco``, ``total reservado`` em KiB (o
cartão simulado e o que o sistema ocupa nele)."""


class ErroDeUso(Exception):
    """Um comando com argumentos errados (código 2, como um comando desconhecido)."""


def raiz():
    return os.environ.get("SHAN_RAIZ", "/")


def sistema(caminho):
    """Um caminho do sistema (``/proc/...``) dentro da raiz (a falsa, nos testes)."""
    return os.path.join(raiz(), caminho.lstrip("/"))


def pasta_do_firmware():
    """``SHAN_PASTA``; sem ela, a pasta acima desta (o agente fica em ``firmware/agente/``). Lido pelo stdin
    (``python3 -``), o agente não tem pasta (o ``__file__`` é ``<stdin>``): o padrão é ``~/firmware``, o do
    ``BeagleBone_Setup.sh``."""
    if os.environ.get("SHAN_PASTA"):
        return os.environ["SHAN_PASTA"]
    if os.path.isfile(__file__):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(os.path.expanduser("~"), "firmware")


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


def programa(nome):
    """Onde está o programa ``nome`` na placa (``/usr/bin/make``), ou ``None``. Procura nas pastas de sempre, e não
    só no ``PATH`` do SSH (o ``avahi-daemon`` fica em ``/usr/sbin``, fora dele)."""
    for pasta in DIRETORIOS_DE_PROGRAMAS:
        caminho = pasta + "/" + nome
        real = sistema(caminho)
        if os.path.isfile(real) and os.access(real, os.X_OK):
            return caminho
    return None


def _mtime(caminho):
    try:
        return os.stat(caminho).st_mtime
    except OSError:
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
    simulado = _disco_simulado(caminho) if raiz() != "/" else None
    if simulado is not None:
        return simulado
    try:
        v = os.statvfs(caminho)
    except OSError:
        return None
    return {"total_kib": v.f_blocks * v.f_frsize // 1024, "livre_kib": v.f_bavail * v.f_frsize // 1024}


def _disco_simulado(pasta):
    """O cartão da placa simulada (:data:`SIMULADOR`): o livre é o que sobra do tamanho dele, menos o sistema e os
    arquivos da pasta do firmware (apagar uma captura libera o espaço dela). ``None`` sem o arquivo."""
    try:
        total, reservado = (int(x) for x in (ler_texto(SIMULADOR + "/disco") or "").split()[:2])
    except ValueError:
        return None
    usado = 0
    for atual, _pastas, arquivos in os.walk(pasta):
        for nome in arquivos:
            try:
                usado += os.lstat(os.path.join(atual, nome)).st_size
            except OSError:
                pass
    return {"total_kib": total, "livre_kib": max(0, total - reservado - usado // 1024)}


def _relogio_do_kernel():
    """O que o ``ler_adc`` grava no cabeçalho (``relogio_sincronizado``, ler_adc.c): o ``adjtimex`` só lendo
    (``modes = 0``); ``TIME_ERROR`` ou ``STA_UNSYNC`` = não sincronizado. ``None`` fora do Linux, ou sem o ctypes."""
    try:
        import ctypes

        class Timex(ctypes.Structure):         # o começo da struct timex, e espaço de sobra para o resto
            _fields_ = [("modes", ctypes.c_uint), ("offset", ctypes.c_long), ("freq", ctypes.c_long),
                        ("maxerror", ctypes.c_long), ("esterror", ctypes.c_long), ("status", ctypes.c_int),
                        ("resto", ctypes.c_byte * 512)]

        try:
            libc = ctypes.CDLL("libc.so.6", use_errno=True)    # a glibc; o ctypes.util custa ~0,2 s na placa
        except OSError:
            import ctypes.util

            libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        adjtimex = libc.adjtimex
    except (ImportError, OSError, AttributeError, TypeError):
        return None
    timex = Timex()
    estado = adjtimex(ctypes.byref(timex))
    if estado < 0:
        return None
    return not (estado == TIME_ERROR or timex.status & STA_UNSYNC)


def _desde_o_inicio(boot):
    """Há quanto tempo, no mínimo, este processo roda no instante ``boot`` (o ``CLOCK_BOOTTIME``): o início dele é o
    do ``/proc/self/stat`` (em ticks, desde o boot; arredondado para baixo, por isso o tick a mais). É deste processo,
    e não da placa: fora da raiz falsa. ``None`` fora do Linux."""
    try:
        with open("/proc/self/stat") as f:
            stat = f.read()
        inicio = int(stat[stat.rfind(")") + 2:].split()[19])
        return max(0.0, boot - (inicio + 1) / float(os.sysconf("SC_CLK_TCK")))
    except (OSError, ValueError, IndexError):
        return None


def relogio():
    """A hora da placa (para comparar com a do computador: ela não tem bateria de RTC), se o NTP a sincronizou e há
    quanto tempo este processo roda (``desde_o_inicio_s``).

    **Por que o tempo de processo:** o computador sabe quando pediu e quando a resposta chegou. A hora foi lida antes
    de a resposta chegar, e o processo começou depois do pedido: a diferença do relógio fica entre ``utc - chegada`` e
    ``utc - desde_o_inicio_s - pedido``. Sem o segundo limite, a partida e o fim do Python na placa (~0,5 s) entram
    na medida (sh_placa/estado.py; conferido na placa contra um pingue-pongue, 15/11/2026)."""
    sincronizado, fonte = (_relogio_do_kernel(), "adjtimex") if raiz() == "/" else (None, None)
    if sincronizado is None:
        fonte = None
        if os.path.isdir(sistema("/run/systemd/timesync")):
            sincronizado, fonte = os.path.exists(sistema("/run/systemd/timesync/synchronized")), "timesyncd"
    utc = time.time() + (desvio_do_relogio_simulado() if raiz() != "/" else 0.0)
    try:
        boot = time.clock_gettime(time.CLOCK_BOOTTIME)
    except (AttributeError, OSError):
        boot = None
    return {"utc": utc, "sincronizado": sincronizado, "fonte": fonte,
            "desde_o_inicio_s": None if boot is None else _desde_o_inicio(boot)}


def desvio_do_relogio_simulado():
    """Na raiz falsa: quanto a hora da placa simulada está adiantada da deste computador (:data:`SIMULADOR`)."""
    try:
        return float(ler_texto(SIMULADOR + "/relogio") or 0.0)
    except ValueError:
        return 0.0


def pru():
    """O remoteproc que o ``ler_adc`` usa e, se a PRU0 for outro (um kernel que numera de outro jeito), qual é."""
    pru0 = None
    try:
        entradas = sorted(os.listdir(sistema("/sys/class/remoteproc")))
    except OSError:
        entradas = []
    for entrada in entradas:
        if ENDERECO_DA_PRU0 in (ler_texto("/sys/class/remoteproc/" + entrada + "/name") or ""):
            pru0 = "/sys/class/remoteproc/" + entrada
            break
    return {"estado": ler_texto(REMOTEPROC_PRU0 + "/state"), "firmware": ler_texto(REMOTEPROC_PRU0 + "/firmware"),
            "nome": ler_texto(REMOTEPROC_PRU0 + "/name"), "remoteproc_da_pru0": pru0}


def pinos():
    """O modo de cada pino da PRU, onde o ``config-pin`` o grava, e se é o que o ``setup.sh`` configura."""
    resultado = {}
    for pino, esperado in sorted(PINOS_DA_PRU.items()):
        modo = ler_texto(BASE_PINMUX + "/ocp:" + pino + "_pinmux/state")
        resultado[pino] = {"modo": modo, "esperado": esperado, "certo": None if modo is None else modo == esperado}
    return resultado


def ram_sobre_os_buffers():
    """``True`` se a "System RAM" do ``/proc/iomem`` cobre os buffers da PRU (o que o ``setup.sh`` confere), ``False``
    se não, e ``None`` se não dá para saber: sem o arquivo, ou com os endereços zerados (só o root os vê)."""
    texto = ler_texto("/proc/iomem", 1 << 16)
    if not texto:
        return None
    faixas, algum_endereco = [], False
    for linha in texto.splitlines():
        if linha.startswith(" "):
            continue                           # só as faixas de cima (as de dentro são partes delas)
        intervalo, _, nome = linha.partition(" : ")
        inicio, _, fim = intervalo.strip().partition("-")
        try:
            a, b = int(inicio, 16), int(fim, 16)
        except ValueError:
            continue
        algum_endereco = algum_endereco or a != 0 or b != 0
        if nome.strip() == "System RAM":
            faixas.append((a, b))
    if not algum_endereco:
        return None
    return any(a <= FAIXA_DOS_BUFFERS[1] and b >= FAIXA_DOS_BUFFERS[0] for a, b in faixas)


def memoria_dos_buffers():
    """``mem=496M`` na linha do kernel: os 16 MB do fim da DDR ficam fora do Linux, para os buffers da PRU."""
    linha = ler_texto("/proc/cmdline")
    return {"cmdline": linha, "mem_496m": None if linha is None else "mem=496M" in linha.split(),
            "ram_sobre_os_buffers": ram_sobre_os_buffers()}


def _comparar(um, outro):
    """``"igual"``, ``"diferente"``, ``"ausente"`` (``outro`` não existe) ou ``None`` (não deu para ler)."""
    try:
        with open(um, "rb") as f:
            a = f.read(1 << 22)
    except OSError:
        return None
    try:
        with open(outro, "rb") as f:
            b = f.read(1 << 22)
    except FileNotFoundError:
        return "ausente"
    except OSError:
        return None
    return "igual" if a == b else "diferente"


def protocolo_da_pru(pasta):
    """O ``VERSAO_PROTOCOLO_PRU`` do ``memoria_pru.h`` da pasta: o contrato entre o ``ler_adc`` e a PRU que ela
    compila (o que a PRU escreve na memória só o root lê)."""
    try:
        with open(os.path.join(pasta, "memoria_pru.h"), encoding="utf-8", errors="replace") as f:
            m = re.search(r"#define\s+VERSAO_PROTOCOLO_PRU\s+(\d+)", f.read())
    except OSError:
        return None
    return int(m.group(1)) if m else None


def firmware(pasta):
    """A versão, e se o firmware da pasta está compilado, compilado depois da última mudança do código (como confere
    a ``coleta/campanha.sh``) e instalado na PRU (o ``fw_pru.out`` é o ``/lib/firmware/am335x-pru0-fw``)."""
    ler_adc, fw_pru = os.path.join(pasta, "ler_adc"), os.path.join(pasta, "fw_pru.out")

    def mais_antigo(binario, fontes):
        quando = _mtime(binario)
        if quando is None:
            return None
        return any(quando < t for t in (_mtime(os.path.join(pasta, f)) for f in fontes) if t is not None)

    tem_fw_pru = os.path.isfile(fw_pru)
    return dict(versao(), compilado=os.access(ler_adc, os.X_OK), ler_adc_antigo=mais_antigo(ler_adc, FONTES_DO_LER_ADC),
                fw_pru=tem_fw_pru, fw_pru_antigo=mais_antigo(fw_pru, FONTES_DA_PRU),
                fw_pru_instalado=_comparar(fw_pru, sistema(FIRMWARE_INSTALADO)) if tem_fw_pru else None,
                protocolo_da_pru=protocolo_da_pru(pasta))


def _varrer(pasta):
    """Os ``.bin`` e os manifestos das coletas (caminhos relativos a ``pasta``, com ``/``): a pasta do firmware e as
    de dentro, até :data:`PROFUNDIDADE_DAS_COLETAS` níveis (a coleta, ``capturas/<sonda>/descartadas``)."""
    binarios, manifestos = [], []
    base = os.path.abspath(pasta)
    for atual, pastas, arquivos in os.walk(base):
        rel = os.path.relpath(atual, base)
        nivel = 0 if rel == "." else rel.count(os.sep) + 1
        pastas[:] = [] if nivel >= PROFUNDIDADE_DAS_COLETAS else sorted(
            p for p in pastas if not p.startswith(".") and not (nivel == 0 and p == "agente"))
        for nome in arquivos:
            caminho = nome if rel == "." else os.path.join(rel, nome)
            if nome.endswith(".bin"):
                binarios.append(caminho.replace(os.sep, "/"))
            elif nome in MANIFESTOS:
                manifestos.append(caminho.replace(os.sep, "/"))
    return binarios, manifestos


def _capturas_por_data(pasta):
    """``[(modificado, caminho relativo, bytes)]``, as mais recentes primeiro; ``None`` sem a pasta."""
    if not os.path.isdir(pasta):
        return None
    itens = []
    for rel in _varrer(pasta)[0]:
        try:
            info = os.stat(os.path.join(pasta, rel))
        except OSError:
            continue
        itens.append((info.st_mtime, rel, info.st_size))
    itens.sort(reverse=True)
    return itens


def resumo_das_capturas(pasta):
    """O número, o tamanho total e as mais recentes (o caminho, os bytes, a data), sem abrir nenhuma."""
    itens = _capturas_por_data(pasta)
    if itens is None:
        return None
    return {"quantidade": len(itens), "bytes": sum(i[2] for i in itens),
            "recentes": [{"nome": rel, "bytes": tamanho, "modificado": quando} for quando, rel, tamanho in itens[:20]]}


# ------------------------------------------------------------------ o que só a saúde lê

def uenv():
    """As chaves do ``/boot/uEnv.txt`` (a última vale, como no u-boot), as linhas que não são comentário nem
    ``chave=valor`` e se o ``mem=496M`` está no ``cmdline`` ou no ``optargs`` (o u-boot junta os dois na linha do
    kernel). ``None`` sem o arquivo."""
    texto = ler_texto("/boot/uEnv.txt", 1 << 16)
    if texto is None:
        return None
    chaves, estranhas = {}, []
    for numero, linha in enumerate(texto.splitlines(), 1):
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        chave, igual, valor = linha.partition("=")
        chave = chave.strip()
        if not igual or not CHAVE_DO_UENV.match(chave):
            estranhas.append(numero)
            continue
        chaves[chave] = valor.strip()
    linha_do_kernel = (chaves.get("optargs", "") + " " + chaves.get("cmdline", "")).split()
    return {"chaves": chaves, "linhas_estranhas": estranhas, "mem_496m": "mem=496M" in linha_do_kernel}


def overlays_carregados():
    """Os overlays que o u-boot aplicou neste boot (``/proc/device-tree/chosen/overlays``), ou ``None``."""
    try:
        nomes = os.listdir(sistema("/proc/device-tree/chosen/overlays"))
    except OSError:
        return None
    return sorted(n for n in nomes if n != "name")


def dtbos_da_pru():
    """Os overlays da PRU que a placa tem em ``/lib/firmware`` (sem o ``.dtbo``): os do remoteproc de cada kernel e
    o do UIO."""
    try:
        nomes = os.listdir(sistema("/lib/firmware"))
    except OSError:
        return []
    return sorted(n[:-5] for n in nomes if n.endswith(".dtbo") and "PRU" in n.upper())


def ferramentas():
    return {nome: programa(nome) for nome in FERRAMENTAS}


# ------------------------------------------------------------------ as conferências

def _versao_do_kernel(texto):
    m = re.match(r"(\d+)\.(\d+)", texto or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _overlay_sugerido(dtbos, kernel):
    """O overlay do remoteproc da PRU para o kernel que roda (``AM335X-PRU-RPROC-4-19-TI-00A0``), se a placa o tem."""
    versao_do_kernel = _versao_do_kernel(kernel)
    if versao_do_kernel is None:
        return None
    prefixo = f"AM335X-PRU-RPROC-{versao_do_kernel[0]}-{versao_do_kernel[1]}-TI"
    candidatos = [d for d in dtbos if d.upper().startswith(prefixo) and "PRUCAPE" not in d.upper()]
    return (prefixo + "-00A0") if (prefixo + "-00A0") in dtbos else (candidatos[0] if candidatos else None)


def _problema_do_overlay_da_pru(u, kernel, dtbos):
    """``(texto, correção)`` se o ``uEnv.txt`` não carrega o overlay da PRU certo para este kernel; ``None`` se
    carrega (ou sem o arquivo, que é outra conferência)."""
    if u is None:
        return None
    chaves = u["chaves"]
    sugerido = _overlay_sugerido(dtbos, kernel)
    if sugerido:
        trocar = (f"Pôr uboot_overlay_pru=/lib/firmware/{sugerido}.dtbo no /boot/uEnv.txt e reiniciar a placa (o "
                  "assistente de pinos e overlays).")
    else:
        trocar = (f"Pôr no uboot_overlay_pru do /boot/uEnv.txt o overlay AM335X-PRU-RPROC do kernel {kernel or 'da placa'}"
                  " (em /lib/firmware) e reiniciar a placa.")
    if chaves.get("enable_uboot_overlays") != "1":
        return ("Os overlays do u-boot estão desligados no /boot/uEnv.txt (enable_uboot_overlays): o da PRU não "
                "carrega.", "Pôr enable_uboot_overlays=1 no /boot/uEnv.txt e reiniciar a placa.")
    caminho = chaves.get("uboot_overlay_pru")
    if not caminho:
        return "O /boot/uEnv.txt não carrega o overlay da PRU (uboot_overlay_pru).", trocar
    nome = os.path.basename(caminho)
    nome = nome[:-5] if nome.endswith(".dtbo") else nome
    if "UIO" in nome.upper():
        return f"O /boot/uEnv.txt põe a PRU no modo UIO ({nome}), e o ler_adc usa o remoteproc.", trocar
    if nome not in dtbos and not os.path.exists(sistema(caminho)):
        return f"O overlay da PRU do /boot/uEnv.txt ({caminho}) não existe na placa.", trocar
    m = re.search(r"RPROC-(\d+)-(\d+)-TI", nome.upper())
    versao_do_kernel = _versao_do_kernel(kernel)
    if m and versao_do_kernel and (int(m.group(1)), int(m.group(2))) != versao_do_kernel:
        return (f"O overlay da PRU do /boot/uEnv.txt ({nome}) é o do kernel {m.group(1)}.{m.group(2)}, e a placa roda "
                f"o {kernel}."), trocar
    return None


def conferir(f):
    """As conferências do diagnóstico sobre os fatos da :func:`saude` (docs/gui-plan.md, 11.9), do mais grave ao
    menos grave. O relógio comparado com o do computador e o firmware comparado com o do aplicativo são do computador
    (``sh_placa/estado.py``): só ele sabe a hora certa e a versão dele."""
    itens = []

    def item(nivel, codigo, texto, correcao=None):
        itens.append({"nivel": nivel, "codigo": codigo, "texto": texto, "correcao": correcao})

    u = f.get("uenv")
    chaves = (u or {}).get("chaves") or {}
    kernel = f.get("kernel")
    overlays = f.get("overlays") or []

    # A PRU0.
    p = f.get("pru") or {}
    overlay = _problema_do_overlay_da_pru(u, kernel, f.get("dtbo_da_pru") or [])
    if p.get("estado") is None:
        if p.get("remoteproc_da_pru0"):
            item("erro", "pru_em_outro_remoteproc",
                 f"A PRU0 é a {p['remoteproc_da_pru0']}, e o ler_adc e o setup.sh usam a {REMOTEPROC_PRU0}: este kernel "
                 "numera os remoteprocs de outro jeito.",
                 "Usar a imagem da BeagleBoard com o kernel 4.19-ti (a do firmware), ou mudar o REMOTEPROC_PRU0 do "
                 "ler_adc.c e o REMOTEPROC do setup.sh.")
        elif not overlay and (f.get("ligada_s") or PRAZO_DA_PRU_NO_BOOT_S) < PRAZO_DA_PRU_NO_BOOT_S:
            item("aviso", "pru_subindo", "A placa ligou há {:.0f} s, e a PRU0 ainda não aparece no remoteproc: o driver "
                 "dela sobe perto do fim do boot (uns 70 s depois de ligar). A captura espera por ela.".format(
                     f["ligada_s"]))
        else:
            item("erro", "pru_ausente", "A PRU0 não aparece no remoteproc: o overlay da PRU não está carregado."
                 + (" " + overlay[0] if overlay else ""),
                 overlay[1] if overlay else "Conferir o overlay da PRU (uboot_overlay_pru) no /boot/uEnv.txt e "
                 "reiniciar a placa (o assistente de pinos e overlays).")
    else:
        if ENDERECO_DA_PRU0 not in (p.get("nome") or ""):
            item("erro", "pru_outro_nucleo", f"O {REMOTEPROC_PRU0} é o '{p.get('nome')}', e não a PRU0 "
                 f"({ENDERECO_DA_PRU0}.pru): o ler_adc reiniciaria o núcleo errado.",
                 "Conferir o overlay da PRU no /boot/uEnv.txt (o assistente de pinos e overlays).")
        elif p["estado"] not in ESTADOS_NORMAIS_DA_PRU:
            item("erro", "pru_com_falha", f"A PRU0 está '{p['estado']}' (o normal é 'running' durante a captura e "
                 "'offline' entre uma e outra).", "Rodar o setup.sh (recompila e recarrega o firmware na PRU).")
        if p.get("firmware") and p["firmware"] != NOME_DO_FIRMWARE_DA_PRU:
            item("erro", "pru_outro_firmware", f"A PRU0 carrega o firmware '{p['firmware']}', e não o "
                 f"{NOME_DO_FIRMWARE_DA_PRU} do setup.sh.", "Rodar o setup.sh (ele acerta o nome e recarrega).")
        if overlay:
            item("aviso", "overlay_da_pru", overlay[0] + " A PRU pode não aparecer no próximo boot.", overlay[1])

    # O áudio do HDMI: o McASP0 dele disputa os pinos da PRU.
    hdmi = [o for o in overlays if o.upper().startswith("BB-HDMI-")]
    correcao_do_audio = ("Pôr disable_uboot_overlay_audio=1 no /boot/uEnv.txt e reiniciar a placa (o assistente de "
                         "pinos e overlays).")
    if hdmi:
        item("erro", "audio_hdmi", f"O áudio do HDMI está ligado (o overlay {hdmi[0]}): o McASP0 dele usa os pinos "
             "P9_28, P9_29 e P9_31, que são os da PRU.", correcao_do_audio)
    elif u is not None and chaves.get("enable_uboot_overlays") == "1" \
            and "1" not in (chaves.get("disable_uboot_overlay_audio"), chaves.get("disable_uboot_overlay_video")):
        item("aviso", "audio_hdmi_no_proximo_boot", "O /boot/uEnv.txt não desliga o áudio do HDMI: no próximo boot, o "
             "McASP0 pega os pinos P9_28, P9_29 e P9_31 da PRU.", correcao_do_audio)

    # Os pinos.
    estados_dos_pinos = f.get("pinos") or {}
    errados = sorted(n for n, info in estados_dos_pinos.items() if info.get("certo") is False)
    desconhecidos = sorted(n for n, info in estados_dos_pinos.items() if info.get("certo") is None)
    if errados:
        item("erro", "pinos", f"Pinos fora do modo da PRU: {', '.join(errados)}.",
             "Desligar o áudio do HDMI antes: com ele, o config-pin não consegue." if hdmi else
             "config-pin (o setup.sh faz; o ler_adc também tenta na hora de capturar).")
    elif desconhecidos:
        item("aviso", "pinos_desconhecidos",
             f"Não deu para conferir os pinos {', '.join(desconhecidos)} (sem o pinmux do config-pin).",
             "Pôr enable_uboot_cape_universal=1 no /boot/uEnv.txt e reiniciar a placa (é ele que cria o pinmux do "
             "config-pin)." if u is not None and chaves.get("enable_uboot_cape_universal") != "1" else
             "Conferir se a imagem tem o cape universal (o config-pin precisa dele).")

    # A memória dos buffers.
    m = f.get("memoria_dos_buffers") or {}
    mem_no_uenv = (u or {}).get("mem_496m")
    if m.get("mem_496m") is False:
        item("erro", "mem_496m", "Falta 'mem=496M' na linha do kernel: a PRU escreveria por cima da memória do Linux.",
             "O /boot/uEnv.txt já tem: reiniciar a placa." if mem_no_uenv else
             "Pôr mem=496M na linha optargs= (ou na cmdline=) do /boot/uEnv.txt e reiniciar a placa.")
    elif m.get("mem_496m") is None:
        item("aviso", "mem_desconhecida", "Não deu para ler a linha do kernel (/proc/cmdline).")
    elif mem_no_uenv is False:
        item("aviso", "mem_496m_no_proximo_boot", "A linha do kernel tem mem=496M, e o /boot/uEnv.txt não (nem no "
             "optargs nem no cmdline): no próximo boot, a PRU escreveria por cima da memória do Linux.",
             "Pôr mem=496M na linha optargs= do /boot/uEnv.txt.")
    if m.get("ram_sobre_os_buffers") is True:
        item("erro", "ram_sobre_os_buffers", "A RAM do Linux cobre os buffers da PRU (0x9F000000 a 0x9F3FFFFF, no "
             "/proc/iomem).", "Pôr mem=496M na linha optargs= do /boot/uEnv.txt e reiniciar a placa.")

    # O firmware.
    fw = f.get("firmware") or {}
    faltam = [n for n, tem in (("ler_adc", fw.get("compilado")), ("fw_pru.out", fw.get("fw_pru"))) if tem is False]
    if faltam:
        item("erro", "nao_compilado", f"O firmware não está compilado: {'faltam' if len(faltam) > 1 else 'falta'} "
             f"{' e '.join(faltam)} na pasta dele.", "Rodar o setup.sh (compila e carrega na PRU).")
    antigos = [n for n, antigo in (("ler_adc", fw.get("ler_adc_antigo")), ("fw_pru.out", fw.get("fw_pru_antigo")))
               if antigo]
    if antigos:
        item("erro", "compilacao_antiga", f"{' e '.join(antigos)} "
             f"{'são mais antigos' if len(antigos) > 1 else 'é mais antigo'} que o código: o firmware mudou depois da "
             "última compilação.", "Rodar o setup.sh (compila de novo e carrega na PRU).")
    if fw.get("fw_pru_instalado") == "diferente":
        item("erro", "pru_desatualizada", f"A PRU carrega um firmware ({FIRMWARE_INSTALADO}) que não é o fw_pru.out "
             "desta pasta.", "Rodar o setup.sh (instala o fw_pru.out e recarrega a PRU).")
    elif fw.get("fw_pru_instalado") == "ausente":
        item("erro", "pru_desatualizada", f"Não há o {FIRMWARE_INSTALADO}: a PRU não tem o que carregar.",
             "Rodar o setup.sh (instala o fw_pru.out e recarrega a PRU).")
    if "firmware" in fw and fw["firmware"] is None:
        item("aviso", "versao_desconhecida", "A pasta do firmware não tem o arquivo VERSAO.",
             "Enviar o firmware pelo aplicativo (ou pelo BeagleBone_Setup.sh enviar).")

    # O /boot/uEnv.txt e o kernel.
    if u is None and "uenv" in f:
        item("aviso", "uenv_ausente", "Não deu para ler o /boot/uEnv.txt: não dá para conferir os overlays e o "
             "mem=496M do próximo boot.")
    elif u is not None:
        if chaves.get("uname_r") and kernel and chaves["uname_r"] != kernel:
            item("aviso", "kernel_trocado", f"O /boot/uEnv.txt aponta o kernel {chaves['uname_r']}, e a placa roda o "
                 f"{kernel}: o próximo boot troca de kernel (e o overlay da PRU é de cada versão).",
                 "Reiniciar a placa e conferir de novo.")
        if u.get("linhas_estranhas"):
            linhas = ", ".join(f"a {n}" for n in u["linhas_estranhas"][:5])
            item("info", "uenv_estranho", f"O /boot/uEnv.txt tem linhas que não são comentário nem chave=valor ({linhas}).")

    # O disco, o sistema e as ferramentas.
    livre = (f.get("disco") or {}).get("livre_kib")
    if livre is not None:
        minutos = livre * 1024.0 / TAXA_DE_REFERENCIA_BYTES_S / 60
        if livre < DISCO_MINIMO_KIB:
            item("erro", "disco_cheio", f"O cartão está cheio: {livre / 1024.0:.0f} MiB livres, ~{minutos * 60:.0f} s "
                 "de captura a 400 kS/s.", "Transferir as capturas e apagar as já conferidas.")
        elif livre < DISCO_POUCO_KIB:
            item("aviso", "disco", f"Pouco espaço no cartão: ~{minutos:.0f} min de captura a 400 kS/s.",
                 "Transferir as capturas e apagar as já conferidas.")
    temperatura = f.get("temperatura_c")
    if temperatura is not None and temperatura > TEMPERATURA_ALTA_C:
        item("aviso", "temperatura", f"O processador está a {temperatura:.0f} °C.")
    carga = f.get("carga")
    if carga and carga[0] >= CARGA_ALTA:
        carga_no_texto = f"{carga[0]:.1f}".replace(".", ",")          # o texto é em português
        item("aviso", "carga", f"A placa está ocupada (carga de {carga_no_texto} num núcleo só): uma captura pode "
             "perder blocos.", "Ver o que está rodando (top) antes de capturar.")
    memoria = f.get("memoria_disponivel_kib")
    if memoria is not None and memoria < MEMORIA_POUCA_KIB:
        item("aviso", "memoria", f"Pouca memória livre: {memoria / 1024.0:.0f} MiB.")
    presentes = f.get("ferramentas") or {}
    sem = [n for n in FERRAMENTAS_DO_SETUP if n in presentes and presentes[n] is None]
    if sem:
        pacotes = sorted({PACOTES[n] for n in sem})
        item("aviso", "ferramentas", f"Faltam na placa: {', '.join(sem)}. Sem elas, o setup.sh não compila o firmware "
             "nem configura os pinos.", "sudo apt install " + " ".join(pacotes))

    # O relógio e as capturas.
    if (f.get("relogio") or {}).get("sincronizado") is False:
        item("info", "relogio_sem_ntp", "O NTP não sincronizou o relógio da placa (sem internet?): a hora das capturas "
             "vem do acerto pelo computador.")
    ultima = f.get("ultima_captura") or {}
    cabecalho = ultima.get("cabecalho") or {}
    parados = cabecalho.get("canais_parados")
    if parados:
        nome = ultima.get("arquivo")
        if len(parados) == len(cabecalho.get("canais") or ()) and all(p["codigo"] == 0 for p in parados):
            item("aviso", "adc_mudo", f"A captura mais recente ({nome}) ficou em 0 em todas as amostras: o ADC não "
                 "respondeu.", "Ligar a BeagleBone na fonte de 5 V (pelo USB, a placa de aquisição fica sem "
                 "alimentação) e conferir os pinos da PRU; depois, uma captura de conferência.")
        else:
            canais = _lista_de_canais(p["canal"] for p in parados)
            valores = sorted({f"0x{p['codigo']:04X}" for p in parados})
            item("aviso", "sinal_parado", f"Na captura mais recente ({nome}), o sinal {canais} ficou parado em "
                 f"{' e '.join(valores)}: a entrada saturada ou o ADC travado.",
                 "Conferir a ligação e a faixa do canal antes de capturar de novo.")
    resumo = f.get("capturas") or {}
    if resumo.get("quantidade"):
        item("info", "capturas", f"{resumo['quantidade']} captura(s) na placa ({resumo.get('bytes', 0) / 1048576.0:.0f} "
             "MiB).")
    ordem = {"erro": 0, "aviso": 1, "info": 2}
    return sorted(itens, key=lambda x: ordem[x["nivel"]])


def _lista_de_canais(canais):
    """"do canal 1", "dos canais 0 e 1"."""
    canais = [str(c) for c in canais]
    if len(canais) == 1:
        return "do canal " + canais[0]
    return "dos canais " + ", ".join(canais[:-1]) + " e " + canais[-1]


# ------------------------------------------------------------------ as capturas

def _texto(bruto, inicio, tamanho):
    return bruto[inicio:inicio + tamanho].split(b"\x00", 1)[0].decode("utf-8", "replace").strip() or None


def resumo_do_cabecalho(caminho, tamanho_do_arquivo):
    """O resumo do cabeçalho "SHAN" de um ``.bin`` (``struct cabecalho_arquivo`` do ``ler_adc.c``, de v1 a v9: os
    mesmos campos que ``supraharmonicos/cabecalho.py`` lê, e ``tests/test_agente.py`` confere que os dois concordam).
    ``None`` num arquivo sem o cabeçalho (o de um firmware antigo, ou outro arquivo)."""
    try:
        with open(caminho, "rb") as f:
            bruto = f.read(CABECALHO_TAMANHO)
            if len(bruto) < CABECALHO_TAMANHO or bruto[:4] != CABECALHO_MAGICO:
                return None
            versao, tamanho = struct.unpack_from("<II", bruto, 4)
            if versao >= 9:
                if not CABECALHO_TAMANHO_MINIMO_V9 <= tamanho <= 1 << 20 or tamanho % 2:
                    tamanho = CABECALHO_TAMANHO_V9
                bruto += f.read(tamanho - CABECALHO_TAMANHO)
            else:
                tamanho = CABECALHO_TAMANHO
    except OSError:
        return None
    inteiro = len(bruto) == tamanho
    bruto = bruto.ljust(tamanho, b"\x00")
    inicio, taxa, _mascara, n_canais = struct.unpack_from("<QIII", bruto, 12)
    lista = struct.unpack_from("<8B", bruto, 32)
    bytes_por_amostra = struct.unpack_from("<I", bruto, 44)[0]
    duracao_pedida = struct.unpack_from("<d", bruto, 60)[0]
    blocos, amostras = struct.unpack_from("<QQ", bruto, 68)
    offset_do_crc = 1020 if versao >= 8 else OFFSET_DO_CRC.get(versao, 404)
    (crc,) = struct.unpack_from("<I", bruto, offset_do_crc)
    coberto = bruto[:tamanho if versao >= 9 else CABECALHO_TAMANHO]
    crc_certo = zlib.crc32(coberto[:offset_do_crc] + b"\x00" * 4 + coberto[offset_do_crc + 4:]) & 0xFFFFFFFF
    novo = versao >= 8
    resumo = {
        "versao": versao, "crc_valido": inteiro and crc == crc_certo,
        "titulo": _texto(bruto, 772, 128) if novo else _texto(bruto, 84, 64),
        "descricao": _texto(bruto, 84, 272) if novo else _texto(bruto, 148, 256),
        "inicio_utc": inicio + (struct.unpack_from("<I", bruto, 388)[0] / 1e9 if novo else 0.0),
        "taxa_hz": taxa, "canais": list(lista[:min(n_canais, 8)]), "bytes_por_amostra": bytes_por_amostra,
        "blocos": blocos, "amostras": amostras, "duracao_s": amostras / float(taxa) if taxa else None,
        "duracao_pedida_s": duracao_pedida, "final": amostras > 0,
        "amostras_atrasadas": None, "buffers_sobrescritos": None, "quadros_sdo_ruido": None,
        "versao_firmware": _texto(bruto, 700, 32) if versao >= 5 else None,
        "relogio_sincronizado": None, "id": None, "maquina": None, "canais_parados": None,
    }
    if versao >= 4:
        resumo["amostras_atrasadas"], resumo["buffers_sobrescritos"], resumo["quadros_sdo_ruido"] = \
            struct.unpack_from("<III", bruto, 676)
    if novo:
        sincronizado = struct.unpack_from("<I", bruto, 392)[0]
        resumo["relogio_sincronizado"] = None if sincronizado == VALOR_DESCONHECIDO else sincronizado == 1
    if versao >= 9:
        resumo["id"] = bruto[1052:1068].hex() if any(bruto[1052:1068]) else None
        resumo["maquina"] = _texto(bruto, 1068, 32)
        if amostras > 0 and inteiro:
            # O sinal de cada canal em todas as amostras (o ler_adc mede e grava no cabeçalho final): o mínimo igual ao
            # máximo é um canal parado, o ADC que não respondeu (em 0) ou a entrada saturada.
            minimos = struct.unpack_from("<8H", bruto, OFFSET_DOS_MINIMOS_V9)
            maximos = struct.unpack_from("<8H", bruto, OFFSET_DOS_MAXIMOS_V9)
            resumo["canais_parados"] = [{"canal": c, "codigo": minimos[i]} for i, c in enumerate(resumo["canais"])
                                        if minimos[i] == maximos[i]]
    # Uma captura com o cabeçalho final tem exatamente as amostras dele; menos é um arquivo cortado (a transferência,
    # o disco), mais é outro arquivo grudado.
    esperado = tamanho + amostras * bytes_por_amostra if amostras and bytes_por_amostra else None
    resumo["bytes_esperados"] = esperado
    resumo["completa"] = None if esperado is None else tamanho_do_arquivo == esperado
    return resumo


def ler_manifesto(pasta, rel):
    """Um ``resumo.csv`` (ou outro manifesto) de uma coleta: as colunas e as linhas (até :data:`LIMITE_DE_LINHAS`)."""
    import csv
    import itertools

    caminho = os.path.join(pasta, rel)
    resultado = {"arquivo": rel, "colunas": None, "linhas": None, "cortado": False, "modificado": _mtime(caminho)}
    try:
        with open(caminho, newline="", encoding="utf-8", errors="replace") as f:
            linhas = list(itertools.islice(csv.reader(f), LIMITE_DE_LINHAS + 2))
    except (OSError, csv.Error):
        return resultado
    resultado.update(colunas=linhas[0] if linhas else [], linhas=linhas[1:LIMITE_DE_LINHAS + 1],
                     cortado=len(linhas) > LIMITE_DE_LINHAS + 1)
    return resultado


# ------------------------------------------------------------------ os logs

def _relevante(texto, prioridade):
    return (prioridade is not None and prioridade <= PRIORIDADE_DE_ERRO) or \
        any(t in texto.lower() for t in TERMOS_DOS_LOGS)


def logs_do_kernel(quantas, todos=False):
    """As mensagens do kernel (o ``/dev/kmsg``, o que o ``dmesg`` lê) da PRU, dos pinos e do firmware, e as de erro
    (com ``todos``, todas); ``None`` se o kernel não deixa ler (``dmesg_restrict``)."""
    import errno

    try:
        fd = os.open(sistema("/dev/kmsg"), os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    pedacos = []
    try:
        while True:
            try:
                pedaco = os.read(fd, 1 << 16)
            except BlockingIOError:
                break                          # o fim do que o kernel guardou
            except OSError as e:
                if e.errno == errno.EPIPE:     # um registro sobrescrito enquanto lia: segue do próximo
                    continue
                raise
            if not pedaco:
                break
            pedacos.append(pedaco)
    except OSError:
        return None
    finally:
        os.close(fd)
    ligada = ler_numero("/proc/uptime")
    boot = time.time() - ligada if ligada is not None else None
    linhas = []
    for linha in b"".join(pedacos).decode("utf-8", "replace").splitlines():
        if not linha or linha[0] == " ":
            continue                           # as linhas com espaço são do registro de cima (SUBSYSTEM=...)
        cabeca, _, texto = linha.partition(";")
        partes = cabeca.split(",")
        try:
            prioridade, desde_o_boot = int(partes[0]) & 7, int(partes[2]) / 1e6
        except (IndexError, ValueError):
            continue
        if todos or _relevante(texto, prioridade):
            linhas.append({"utc": None if boot is None else boot + desde_o_boot, "desde_o_boot_s": desde_o_boot,
                           "nivel": prioridade, "origem": "kernel", "texto": texto})
    return linhas[-quantas:]


def _entrada_do_diario(linha, todos=False):
    """Uma linha do ``journalctl -o json`` como o agente a responde (o ``utc``, o nível, a origem, o texto); ``None``
    para a que não se lê, a binária e, sem ``todos``, a que não é do firmware nem um erro."""
    try:
        e = json.loads(linha)
    except ValueError:
        return None
    if not isinstance(e, dict) or not isinstance(e.get("MESSAGE"), str):
        return None                            # uma mensagem binária vem como lista de bytes
    texto = e["MESSAGE"]
    try:
        prioridade = int(e.get("PRIORITY"))
    except (TypeError, ValueError):
        prioridade = None
    kernel = e.get("_TRANSPORT") == "kernel"
    origem = "kernel" if kernel else (e.get("SYSLOG_IDENTIFIER") or e.get("_COMM"))
    if not todos and not _relevante(texto + " " + (origem or ""), prioridade):
        return None
    try:
        utc = int(e["__REALTIME_TIMESTAMP"]) / 1e6
    except (KeyError, TypeError, ValueError):
        utc = None
    return {"utc": utc, "nivel": prioridade, "origem": origem, "texto": texto}


def logs_do_diario(quantas, todos=False):
    """As linhas do diário do systemd deste boot (``journalctl -o json``, :data:`FILTRO_DO_DIARIO`) que falam do
    firmware, e as de erro (com ``todos``, as últimas ``quantas``, sem o filtro); as do kernel ficam de fora (já vêm
    do ``/dev/kmsg``). ``None`` sem o ``journalctl``, ou se ele falhou."""
    import subprocess

    journalctl = programa("journalctl")
    if journalctl is None:
        return None
    filtro = [] if todos else list(FILTRO_DO_DIARIO)
    lidas = quantas if todos else LINHAS_LIDAS_DO_DIARIO
    try:
        r = subprocess.run([sistema(journalctl), "-o", "json", "--no-pager", "-b", "-n", str(lidas)] + filtro,
                           capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    linhas = []
    for linha in r.stdout.decode("utf-8", "replace").splitlines():
        entrada = _entrada_do_diario(linha, todos)
        if entrada is not None and entrada["origem"] != "kernel":
            linhas.append(entrada)
    return linhas[-quantas:]


# ------------------------------------------------------------------ a manutenção (a Fase 6)

SUBPASTAS_DO_CODIGO = ("coleta", "agente")
"""As pastas de código dentro da pasta do firmware (as outras são das coletas: capturas, manifestos)."""
EXTENSOES_DA_COMPILACAO = (".bin", ".obj", ".o", ".map", ".out", ".tmp", ".parcial")
"""O que não é código na pasta do firmware: as capturas e o que o ``make`` gera."""
BINARIOS = ("ler_adc", "fw_pru.out")
LIMITE_DO_HASH = 8 << 20                 # um arquivo de código maior que isto não é código
PRU_INSTALADA_NA_COPIA = "am335x-pru0-fw.instalado"
"""Na cópia de segurança de uma atualização: o firmware que estava instalado na PRU (o ``/lib/firmware``)."""
UENV = "/boot/uEnv.txt"
PREFIXO_DAS_COPIAS_DO_UENV = "uEnv.txt.sh-analyzer-"
LIMITE_DO_UENV = 64 * 1024
SERVICOS_DA_IMAGEM = (
    ("cloud9.socket", "opcional", "O Cloud9, o editor web da imagem (porta 3000)."),
    ("cloud9.service", "opcional", "O Cloud9 rodando (aberto pelo socket)."),
    ("bonescript.socket", "opcional", "O BoneScript, a biblioteca web da imagem (porta 80, pelo nginx)."),
    ("bonescript.service", "opcional", "O BoneScript rodando (aberto pelo socket)."),
    ("bonescript-autorun.service", "opcional", "Roda sozinho os programas do Cloud9 na pasta autorun."),
    ("nodered.socket", "opcional", "O Node-RED, o editor de fluxos da imagem (porta 1880)."),
    ("nodered.service", "opcional", "O Node-RED rodando (aberto pelo socket)."),
    ("nginx.service", "opcional", "O servidor web da imagem (a página da placa na porta 80)."),
    ("apache2.service", "opcional", "Um servidor web (algumas imagens o trazem no lugar do nginx)."),
    ("ssh.service", "necessario", "O SSH: o caminho do aplicativo até a placa."),
    ("dnsmasq.service", "necessario", "Dá o endereço ao computador pelo USB (o DHCP das redes do gadget)."),
    ("avahi-daemon.service", "necessario", "O mDNS: a placa achada como beaglebone.local."),
    ("connman.service", "necessario", "Liga a Ethernet e o Wi-Fi."),
    ("systemd-timesyncd.service", "necessario", "Acerta o relógio pela internet (NTP), quando há internet."),
    ("serial-getty@ttyGS0.service", "necessario", "O console pela porta serial do USB (o resgate)."),
)
"""Os serviços da imagem da BeagleBoard que a manutenção mostra (vistos na placa de verdade, 19/11/2026): os
``opcional`` não servem ao SH-Analyzer e disputam o núcleo único com a captura; os ``necessario`` não se desligam."""
PROPRIEDADES_DO_SERVICO = ("Id", "Description", "LoadState", "ActiveState", "SubState", "UnitFileState", "MainPID")
INTERFACES_IGNORADAS = ("lo",)
HOST_DA_INTERNET = ("deb.debian.org", 80)
LIMITE_DE_PROCESSOS = 50


def pasta_do_home():
    """O home do usuário da placa: a pasta acima da do firmware (na raiz falsa, o home simulado)."""
    return os.path.dirname(os.path.abspath(pasta_do_firmware()))


def pasta_das_anteriores():
    """Onde ficam as cópias de segurança do firmware: ``~/firmware-anteriores``, a do ``enviar``."""
    return os.path.abspath(pasta_do_firmware()) + "-anteriores"


def _sha256(caminho, limite=LIMITE_DO_HASH):
    import hashlib

    try:
        if os.path.getsize(caminho) > limite:
            return None
        h = hashlib.sha256()
        with open(caminho, "rb") as f:
            for pedaco in iter(lambda: f.read(1 << 16), b""):
                h.update(pedaco)
        return h.hexdigest()
    except OSError:
        return None


def _e_codigo(nome):
    return not nome.startswith(".") and not nome.endswith(EXTENSOES_DA_COMPILACAO) and nome not in BINARIOS \
        and nome != "VERSAO"


def arquivos_do_codigo(pasta):
    """O código na pasta do firmware (caminhos relativos, com ``/``): os arquivos do alto e os de
    :data:`SUBPASTAS_DO_CODIGO`, sem as capturas nem o que a compilação gera."""
    rels = []
    for sub in ("",) + SUBPASTAS_DO_CODIGO:
        base = os.path.join(pasta, sub) if sub else pasta
        try:
            nomes = sorted(os.listdir(base))
        except OSError:
            continue
        for nome in nomes:
            if _e_codigo(nome) and os.path.isfile(os.path.join(base, nome)):
                rels.append(sub + "/" + nome if sub else nome)
    return rels


def _descrever_arquivo(caminho):
    try:
        info = os.stat(caminho)
    except OSError:
        return None
    return {"sha256": _sha256(caminho), "bytes": info.st_size, "modificado": info.st_mtime,
            "executavel": bool(info.st_mode & 0o111)}


def firmware_arquivos(rels):
    """Os arquivos do código do firmware da placa (os pedidos, ou todos), com o hash, o tamanho e a data; os binários;
    e o firmware instalado na PRU. É o que o aplicativo compara com o dele antes de atualizar (só o que mudou vai)."""
    pasta = pasta_do_firmware()
    for rel in rels:
        if rel.startswith("/") or ".." in rel.split("/"):
            raise ErroDeUso(f"um caminho fora da pasta do firmware: {rel!r}")
    lista = list(rels) if rels else arquivos_do_codigo(pasta)
    return {"pasta": pasta, "existe": os.path.isdir(pasta), "versao": versao()["firmware"],
            "arquivos": {rel: _descrever_arquivo(os.path.join(pasta, rel)) for rel in lista},
            "binarios": {nome: _descrever_arquivo(os.path.join(pasta, nome)) for nome in BINARIOS},
            "pru_instalada": _descrever_arquivo(sistema(FIRMWARE_INSTALADO))}


def _versao_da_copia(caminho, nome):
    texto = None
    try:
        with open(os.path.join(caminho, "VERSAO"), encoding="utf-8", errors="replace") as f:
            texto = f.read(64).strip() or None
    except OSError:
        pass
    if texto is None:                       # o nome do enviar: AAAA-MM-DD_HHMMSS_<versão>
        partes = nome.split("_", 2)
        texto = partes[2] if len(partes) == 3 else None
    return texto


def anteriores():
    """As cópias de segurança do firmware (``~/firmware-anteriores``), as mais novas primeiro: a versão, a data, o
    tamanho, os arquivos e se a cópia dá para voltar (tem o código; os binários e a PRU instalada, se a cópia é de
    uma atualização pelo aplicativo). As do ``enviar`` guardam os arquivos das subpastas no alto da cópia."""
    base = pasta_das_anteriores()
    try:
        nomes = sorted(os.listdir(base), reverse=True)
    except OSError:
        return {"pasta": base, "copias": []}
    copias = []
    for nome in nomes:
        caminho = os.path.join(base, nome)
        if nome.startswith(".") or not os.path.isdir(caminho):
            continue
        arquivos, total = [], 0
        for atual, pastas, nomes_dos_arquivos in os.walk(caminho):
            pastas[:] = sorted(p for p in pastas if not p.startswith("."))
            for n in sorted(nomes_dos_arquivos):
                completo = os.path.join(atual, n)
                try:
                    total += os.lstat(completo).st_size
                except OSError:
                    continue
                arquivos.append(os.path.relpath(completo, caminho).replace(os.sep, "/"))
        copias.append({"nome": nome, "versao": _versao_da_copia(caminho, nome), "bytes": total,
                       "modificado": _mtime(caminho), "arquivos": arquivos,
                       "codigo": "ler_adc.c" in arquivos and "Makefile" in arquivos,
                       "binarios": all(b in arquivos for b in BINARIOS),
                       "pru_instalada": PRU_INSTALADA_NA_COPIA in arquivos})
    return {"pasta": base, "copias": copias}


def inicializacao():
    """O que o assistente de pinos e overlays lê: o ``/boot/uEnv.txt`` inteiro (com o hash, para a gravação conferir
    que ninguém o mudou entre a leitura e a escrita), a linha do kernel deste boot, o kernel, os overlays carregados,
    os ``.dtbo`` da PRU e as cópias que o assistente já fez."""
    caminho = sistema(UENV)
    texto = None
    try:
        with open(caminho, "rb") as f:
            bruto = f.read(LIMITE_DO_UENV + 1)
        texto = None if len(bruto) > LIMITE_DO_UENV else bruto.decode("utf-8", "replace")
    except OSError:
        bruto = None
    copias = []
    pasta = os.path.dirname(caminho)
    try:
        nomes = sorted(os.listdir(pasta), reverse=True)
    except OSError:
        nomes = []
    for nome in nomes:
        if nome.startswith(PREFIXO_DAS_COPIAS_DO_UENV):
            try:
                info = os.stat(os.path.join(pasta, nome))
            except OSError:
                continue
            copias.append({"nome": nome, "bytes": info.st_size, "modificado": info.st_mtime})
    import hashlib

    return {"uenv": {"caminho": UENV, "texto": texto, "bytes": None if bruto is None else len(bruto),
                     "sha256": None if bruto is None else hashlib.sha256(bruto).hexdigest()},
            "cmdline": ler_texto("/proc/cmdline"), "kernel": ler_texto("/proc/sys/kernel/osrelease"),
            "overlays": overlays_carregados(), "dtbos_da_pru": dtbos_da_pru(), "copias": copias,
            "pinos": pinos()}


def _rodar(argv, tempo=10, entrada=None):
    """``(código, stdout)`` de um programa da placa (na raiz falsa, o dela); ``None`` se não deu para rodar."""
    import subprocess

    caminho = programa(argv[0])
    if caminho is None:
        return None
    try:
        r = subprocess.run([sistema(caminho)] + list(argv[1:]), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           input=entrada, timeout=tempo)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.returncode, r.stdout.decode("utf-8", "replace")


def servicos():
    """Os serviços da imagem (:data:`SERVICOS_DA_IMAGEM`): o estado (``active``…), se sobe no boot
    (``enabled``…), o PID e a memória dele. ``None`` sem o ``systemctl``."""
    unidades = [u for u, _p, _t in SERVICOS_DA_IMAGEM]
    r = _rodar(["systemctl", "show", "--no-pager", "-p", ",".join(PROPRIEDADES_DO_SERVICO)] + unidades)
    if r is None:
        return None
    blocos, atual = [], {}
    for linha in r[1].splitlines() + [""]:
        if not linha.strip():
            if atual:
                blocos.append(atual)
            atual = {}
            continue
        chave, _, valor = linha.partition("=")
        atual[chave] = valor
    por_id = {b.get("Id"): b for b in blocos}
    lista = []
    for unidade, papel, texto in SERVICOS_DA_IMAGEM:
        b = por_id.get(unidade)
        if b is None or b.get("LoadState") == "not-found":
            continue
        try:
            pid = int(b.get("MainPID") or 0)
        except ValueError:
            pid = 0
        memoria = None
        if pid:
            for linha in (ler_texto(f"/proc/{pid}/status", 8192) or "").splitlines():
                if linha.startswith("VmRSS:"):
                    try:
                        memoria = int(linha.split()[1])
                    except (IndexError, ValueError):
                        pass
        lista.append({"unidade": unidade, "papel": papel, "texto": texto, "descricao": b.get("Description"),
                      "ativo": b.get("ActiveState"), "sub": b.get("SubState"), "no_boot": b.get("UnitFileState"),
                      "pid": pid or None, "memoria_kib": memoria})
    return lista


def rede():
    """As interfaces (o estado, o MAC, os bytes) e os endereços (do ``ip -o addr``)."""
    base = sistema("/sys/class/net")
    try:
        nomes = sorted(os.listdir(base))
    except OSError:
        return None
    enderecos = {}
    r = _rodar(["ip", "-o", "addr", "show"])
    if r is not None and r[0] == 0:
        for linha in r[1].splitlines():
            partes = linha.split()
            if len(partes) >= 4 and partes[2] in ("inet", "inet6"):
                enderecos.setdefault(partes[1], []).append(partes[3])
    lista = []
    for nome in nomes:
        if nome in INTERFACES_IGNORADAS:
            continue
        caminho = "/sys/class/net/" + nome
        lista.append({"nome": nome, "estado": ler_texto(caminho + "/operstate"), "mac": ler_texto(caminho + "/address"),
                      "rx_bytes": ler_numero(caminho + "/statistics/rx_bytes", int),
                      "tx_bytes": ler_numero(caminho + "/statistics/tx_bytes", int),
                      "enderecos": enderecos.get(nome, [])})
    return lista


def _tamanho_da_pasta(caminho):
    total, achou = 0, os.path.isdir(caminho)
    for atual, _pastas, arquivos in os.walk(caminho):
        for nome in arquivos:
            try:
                total += os.lstat(os.path.join(atual, nome)).st_size
            except OSError:
                pass
    return total if achou else None


def _bloco_da_raiz():
    """O cartão e a partição da raiz (``mmcblk1``, ``mmcblk1p1``), da linha do kernel (``root=/dev/mmcblk1p1``)."""
    m = re.search(r"\broot=/dev/(mmcblk\d+)(p\d+)\b", ler_texto("/proc/cmdline") or "")
    return (m.group(1), m.group(1) + m.group(2)) if m else (None, None)


def cartao():
    """O cartão (o eMMC ou o SD) e a partição da raiz, em bytes, e quanto do cartão fica fora dela (o que expandir a
    partição ganharia; só a última partição cresce). O script da imagem que expande, se ela o tem."""
    disco_, particao = _bloco_da_raiz()
    if disco_ is None:
        return None
    setores = ler_numero(f"/sys/block/{disco_}/size", int)
    tamanho = ler_numero(f"/sys/block/{disco_}/{particao}/size", int)
    inicio = ler_numero(f"/sys/block/{disco_}/{particao}/start", int)
    if setores is None or tamanho is None or inicio is None:
        return {"disco": disco_, "particao": particao, "bytes": None, "particao_bytes": None, "fora_bytes": None}
    script = "/opt/scripts/tools/grow_partition.sh"
    return {"disco": disco_, "particao": particao, "bytes": setores * 512, "particao_bytes": tamanho * 512,
            "fora_bytes": max(0, setores - inicio - tamanho) * 512,
            "script_de_expandir": script if os.path.isfile(sistema(script)) else None}


def ocupacao():
    """O que ocupa o cartão e pode ser limpo (em bytes; ``None`` se não deu para ler): as cópias do firmware, as
    tarefas, o diário do systemd (o persistente; o da RAM some no reinício) e o cache do ``apt``. As capturas ficam
    com os Arquivos (só se apaga o conferido no computador)."""
    pasta = pasta_do_firmware()
    capturas = resumo_das_capturas(pasta)
    return {"anteriores": _tamanho_da_pasta(pasta_das_anteriores()),
            "tarefas": _tamanho_da_pasta(os.path.join(pasta_do_home(), ".sh-analyzer", "tarefas")),
            "diario": _tamanho_da_pasta(sistema("/var/log/journal")),
            "diario_na_ram": _tamanho_da_pasta(sistema("/run/log/journal")),
            "apt": _tamanho_da_pasta(sistema("/var/cache/apt/archives")),
            "capturas": None if capturas is None else capturas["bytes"]}


def _memoria():
    campos = {}
    for linha in (ler_texto("/proc/meminfo", 16384) or "").splitlines():
        nome, _, resto = linha.partition(":")
        try:
            campos[nome] = int(resto.split()[0])
        except (IndexError, ValueError):
            pass
    return {"total_kib": campos.get("MemTotal"), "disponivel_kib": campos.get("MemAvailable"),
            "swap_total_kib": campos.get("SwapTotal"), "swap_livre_kib": campos.get("SwapFree")}


def _fuso():
    fuso = ler_texto("/etc/timezone")
    if fuso:
        return fuso
    try:
        destino = os.readlink(sistema("/etc/localtime"))
    except OSError:
        return None
    return destino.split("zoneinfo/", 1)[1] if "zoneinfo/" in destino else None


def sistema_detalhe():
    """A página Sistema da manutenção: o nome, o fuso, a memória, o cartão e a partição, a ocupação, a rede e os
    serviços da imagem."""
    pasta = pasta_do_firmware()
    return {"nome": ler_texto("/etc/hostname"), "fuso": _fuso(), "kernel": ler_texto("/proc/sys/kernel/osrelease"),
            "sistema": sistema_operacional(), "ligada_s": ler_numero("/proc/uptime"), "memoria": _memoria(),
            "disco": disco(pasta), "cartao": cartao(), "ocupacao": ocupacao(), "rede": rede(),
            "servicos": servicos()}


def internet():
    """Se a placa alcança a internet (o ``apt`` e o NTP precisam): o nome de :data:`HOST_DA_INTERNET` resolvido e uma
    conexão TCP a ele, com o tempo. Na raiz falsa, a resposta do simulador (``/run/simulador/internet``)."""
    if raiz() != "/":
        texto = ler_texto(SIMULADOR + "/internet")
        return {"dns": texto == "sim", "alcanca": texto == "sim", "ms": 42.0 if texto == "sim" else None}
    import socket

    host, porta = HOST_DA_INTERNET
    inicio = time.time()
    try:
        endereco = socket.getaddrinfo(host, porta, socket.AF_INET, socket.SOCK_STREAM)[0][4]
    except (OSError, IndexError):
        return {"dns": False, "alcanca": False, "ms": None}
    try:
        with socket.create_connection(endereco, timeout=3):
            pass
    except OSError:
        return {"dns": True, "alcanca": False, "ms": None}
    return {"dns": True, "alcanca": True, "ms": (time.time() - inicio) * 1000.0}


def _tempo_da_cpu():
    """``(total, ocioso)`` em jiffies, da linha ``cpu`` do ``/proc/stat``."""
    for linha in (ler_texto("/proc/stat", 8192) or "").splitlines():
        if linha.startswith("cpu "):
            try:
                valores = [int(x) for x in linha.split()[1:]]
            except ValueError:
                return None
            return sum(valores), valores[3] + (valores[4] if len(valores) > 4 else 0)
    return None


def _tempo_dos_processos():
    """``{pid: (jiffies do processo, nome, uid, rss em páginas, linha de comando)}`` de cada processo."""
    base = sistema("/proc")
    tempos = {}
    try:
        nomes = os.listdir(base)
    except OSError:
        return tempos
    for nome in nomes:
        if not nome.isdigit():
            continue
        try:
            with open(os.path.join(base, nome, "stat"), encoding="utf-8", errors="replace") as f:
                stat = f.read()
            with open(os.path.join(base, nome, "cmdline"), "rb") as f:
                linha = f.read(512).replace(b"\x00", b" ").decode("utf-8", "replace").strip()
            uid = None
            with open(os.path.join(base, nome, "status"), encoding="utf-8", errors="replace") as f:
                for l_ in f:
                    if l_.startswith("Uid:"):
                        uid = int(l_.split()[1])
                        break
        except (OSError, ValueError):
            continue
        fim = stat.rfind(")")
        comando = stat[stat.find("(") + 1:fim]
        campos = stat[fim + 2:].split()
        try:
            tempos[int(nome)] = (int(campos[11]) + int(campos[12]), comando, uid, int(campos[21]), linha)
        except (IndexError, ValueError):
            continue
    return tempos


def processos(quantos, janela_s=0.5):
    """Os processos que mais pesam: o processador (em %, medido em ``janela_s``) e a memória residente, com o dono e
    a linha de comando."""
    import pwd

    antes, cpu_antes = _tempo_dos_processos(), _tempo_da_cpu()
    time.sleep(janela_s)
    depois, cpu_depois = _tempo_dos_processos(), _tempo_da_cpu()
    decorrido = (cpu_depois[0] - cpu_antes[0]) if cpu_antes and cpu_depois else 0
    pagina_kib = os.sysconf("SC_PAGE_SIZE") // 1024
    lista = []
    eu = os.getpid()
    for pid, (tempo, comando, uid, rss, linha) in depois.items():
        if pid == eu:
            continue                        # o próprio agente, que mede
        anterior = antes.get(pid)
        uso = 100.0 * (tempo - anterior[0]) / decorrido if anterior and decorrido > 0 else 0.0
        try:
            dono = pwd.getpwuid(uid).pw_name if uid is not None and raiz() == "/" else None
        except KeyError:
            dono = None
        lista.append({"pid": pid, "nome": comando, "dono": dono, "uid": uid, "cpu": uso, "memoria_kib": rss * pagina_kib,
                      "linha": linha})
    lista.sort(key=lambda p: (-p["cpu"], -p["memoria_kib"]))
    total = 100.0 * (1.0 - (cpu_depois[1] - cpu_antes[1]) / decorrido) if cpu_antes and cpu_depois and decorrido else None
    return {"cpu": total, "processos": lista[:quantos], "total": len(lista)}


def amostra(anterior):
    """Uma amostra do monitor: o processador (desde ``anterior``, o ``_tempo_da_cpu`` da amostra de antes), a memória,
    a temperatura, a carga e os bytes de cada interface de rede."""
    cpu = _tempo_da_cpu()
    uso = None
    if cpu and anterior and cpu[0] > anterior[0]:
        uso = 100.0 * (1.0 - (cpu[1] - anterior[1]) / float(cpu[0] - anterior[0]))
    carga = (ler_texto("/proc/loadavg") or "").split()
    temperatura = ler_numero("/sys/class/thermal/thermal_zone0/temp")
    redes = {}
    try:
        nomes = os.listdir(sistema("/sys/class/net"))
    except OSError:
        nomes = []
    for nome in nomes:
        if nome not in INTERFACES_IGNORADAS:
            redes[nome] = [ler_numero(f"/sys/class/net/{nome}/statistics/rx_bytes", int),
                           ler_numero(f"/sys/class/net/{nome}/statistics/tx_bytes", int)]
    memoria = _memoria()
    try:
        carga1 = float(carga[0])
    except (IndexError, ValueError):
        carga1 = None
    return cpu, {"t": time.time(), "cpu": uso, "carga": carga1,
                 "temperatura_c": None if temperatura is None else temperatura / 1000.0,
                 "memoria_kib": memoria["total_kib"], "disponivel_kib": memoria["disponivel_kib"], "rede": redes}


def monitor(intervalo, quantas):
    """Uma linha JSON por amostra (:func:`amostra`), a cada ``intervalo`` s, até ``quantas`` (0: até o canal fechar).
    Um processo só, em vez de um Python novo a cada amostra (cada partida custa ~0,3 s do núcleo único da placa)."""
    anterior, n = _tempo_da_cpu(), 0
    try:
        while quantas == 0 or n < quantas:
            time.sleep(intervalo)
            anterior, dados = amostra(anterior)
            sys.stdout.write(json.dumps(dados) + "\n")
            sys.stdout.flush()
            n += 1
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    return None


def seguir_logs():
    """O diário do systemd ao vivo (``journalctl -f -o json``, o kernel junto), uma linha JSON por entrada, até o
    canal fechar."""
    import subprocess

    journalctl = programa("journalctl")
    if journalctl is None:
        sys.stdout.write(json.dumps({"erro": "a placa não tem o journalctl"}) + "\n")
        return None
    processo = subprocess.Popen([sistema(journalctl), "-f", "-o", "json", "-n", "0", "--no-pager"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        for linha in processo.stdout:
            entrada = _entrada_do_diario(linha.decode("utf-8", "replace"), todos=True)
            if entrada is not None:
                sys.stdout.write(json.dumps(entrada, ensure_ascii=False) + "\n")
                sys.stdout.flush()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        processo.kill()
    return None


# ------------------------------------------------------------------ os comandos

def versao():
    pasta = pasta_do_firmware()
    try:
        with open(os.path.join(pasta, "VERSAO"), encoding="utf-8", errors="replace") as f:
            versao_do_firmware = f.read(64).strip() or None
    except OSError:
        versao_do_firmware = None
    return {"firmware": versao_do_firmware, "python": ".".join(map(str, sys.version_info[:3]))}


def estado():
    pasta = pasta_do_firmware()
    carga = ler_texto("/proc/loadavg")
    temperatura = ler_numero("/sys/class/thermal/thermal_zone0/temp")
    try:
        carga = [float(x) for x in carga.split()[:3]] if carga else None
    except ValueError:
        carga = None
    return {
        "placa": placa(),
        "sistema": sistema_operacional(),
        "kernel": ler_texto("/proc/sys/kernel/osrelease"),
        "ligada_s": ler_numero("/proc/uptime"),
        "boot": ler_texto("/proc/sys/kernel/random/boot_id"),
        "carga": carga,
        "memoria_disponivel_kib": memoria_disponivel_kib(),
        "temperatura_c": None if temperatura is None else temperatura / 1000.0,
        "disco": disco(pasta),
        "relogio": relogio(),
        "pru": pru(),
        "pinos": pinos(),
        "memoria_dos_buffers": memoria_dos_buffers(),
        "firmware": firmware(pasta),
        "capturas": resumo_das_capturas(pasta),
    }


def ultima_captura(pasta):
    """A captura mais recente, com o resumo do cabeçalho (o sinal dela diz se o ADC respondeu); ``None`` sem nenhuma."""
    itens = _capturas_por_data(pasta)
    if not itens:
        return None
    quando, rel, tamanho = itens[0]
    return {"arquivo": rel, "bytes": tamanho, "modificado": quando,
            "cabecalho": resumo_do_cabecalho(os.path.join(pasta, rel), tamanho)}


def saude():
    fatos = estado()
    fatos.update(uenv=uenv(), overlays=overlays_carregados(), dtbo_da_pru=dtbos_da_pru(), ferramentas=ferramentas(),
                 ultima_captura=ultima_captura(pasta_do_firmware()))
    fatos["conferencias"] = conferir(fatos)
    return fatos


def capturas():
    pasta = pasta_do_firmware()
    itens = _capturas_por_data(pasta)
    if itens is None:
        return {"pasta": pasta, "total": None, "capturas": None, "coletas": None}
    lista = []
    for quando, rel, tamanho in itens[:LIMITE_DE_CAPTURAS]:
        lista.append({"arquivo": rel, "bytes": tamanho, "modificado": quando,
                      "cabecalho": resumo_do_cabecalho(os.path.join(pasta, rel), tamanho)})
    return {"pasta": pasta, "total": len(itens), "capturas": lista,
            "coletas": [ler_manifesto(pasta, rel) for rel in _varrer(pasta)[1]]}


def logs(quantas=50, todos=False):
    return {"kernel": logs_do_kernel(quantas, todos), "diario": logs_do_diario(quantas, todos),
            "termos": list(TERMOS_DOS_LOGS), "todos": todos}


def _sem_argumentos(funcao):
    def comando(argumentos):
        if argumentos:
            raise ErroDeUso(f"o comando não leva argumentos: {' '.join(argumentos)}")
        return funcao()
    return comando


def _inteiro(texto, nome, minimo, maximo):
    try:
        valor = int(texto)
    except ValueError:
        raise ErroDeUso(f"{nome} não é um número: {texto!r}") from None
    if not minimo <= valor <= maximo:
        raise ErroDeUso(f"{nome} vai de {minimo} a {maximo}: {valor}")
    return valor


def _comando_logs(argumentos):
    todos = "--todos" in argumentos
    resto = [a for a in argumentos if a != "--todos"]
    if len(resto) > 1:
        raise ErroDeUso("logs leva no máximo o número de linhas e --todos")
    return logs(_inteiro(resto[0], "o número de linhas", 1, 5000) if resto else 50, todos)


def _comando_processos(argumentos):
    if len(argumentos) > 1:
        raise ErroDeUso("processos leva no máximo um argumento, quantos")
    return processos(_inteiro(argumentos[0], "quantos", 1, LIMITE_DE_PROCESSOS) if argumentos else 15)


def _comando_monitor(argumentos):
    if len(argumentos) > 2:
        raise ErroDeUso("monitor leva no máximo o intervalo (em s) e quantas amostras (0: até o canal fechar)")
    try:
        intervalo = float(argumentos[0]) if argumentos else 2.0
    except ValueError:
        raise ErroDeUso(f"o intervalo não é um número: {argumentos[0]!r}") from None
    if not 0.2 <= intervalo <= 60:
        raise ErroDeUso(f"o intervalo vai de 0,2 a 60 s: {intervalo}")
    quantas = _inteiro(argumentos[1], "quantas", 0, 100000) if len(argumentos) > 1 else 0
    return lambda: monitor(intervalo, quantas)


def _comando_seguir_logs(argumentos):
    if argumentos:
        raise ErroDeUso(f"o comando não leva argumentos: {' '.join(argumentos)}")
    return seguir_logs


COMANDOS = {"versao": _sem_argumentos(versao), "estado": _sem_argumentos(estado), "saude": _sem_argumentos(saude),
            "capturas": _sem_argumentos(capturas), "relogio": _sem_argumentos(relogio), "logs": _comando_logs,
            "firmware_arquivos": firmware_arquivos, "anteriores": _sem_argumentos(anteriores),
            "inicializacao": _sem_argumentos(inicializacao), "sistema": _sem_argumentos(sistema_detalhe),
            "internet": _sem_argumentos(internet), "processos": _comando_processos}
FLUXOS = {"monitor": _comando_monitor, "seguir_logs": _comando_seguir_logs}
"""Os comandos que respondem uma linha JSON por vez, até o canal fechar (o monitor, os logs ao vivo): cada um confere
os argumentos e devolve a função que escreve as linhas, chamada depois do cabeçalho."""


def _responder(resposta, codigo):
    sys.stdout.write(json.dumps(resposta, ensure_ascii=False) + "\n")
    return codigo


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    comando = argv[0] if argv else ""
    if comando not in COMANDOS and comando not in FLUXOS:
        return _responder({"protocolo": PROTOCOLO, "agente": AGENTE, "erro": f"comando desconhecido: {comando!r} (os "
                           f"comandos: {', '.join(sorted(list(COMANDOS) + list(FLUXOS)))})"}, 2)
    try:
        if comando in FLUXOS:
            fluxo = FLUXOS[comando](argv[1:])
            sys.stdout.write(json.dumps({"protocolo": PROTOCOLO, "agente": AGENTE, "comando": comando}) + "\n")
            sys.stdout.flush()
            fluxo()
            return 0
        dados = COMANDOS[comando](argv[1:])
    except ErroDeUso as e:
        return _responder({"protocolo": PROTOCOLO, "agente": AGENTE, "comando": comando, "erro": str(e)}, 2)
    resposta = {"protocolo": PROTOCOLO, "agente": AGENTE, "comando": comando}
    resposta.update(dados)
    return _responder(resposta, 0)


if __name__ == "__main__":
    sys.exit(main())
