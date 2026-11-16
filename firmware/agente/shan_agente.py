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
* ``saude`` -- o ``estado``, mais o ``/boot/uEnv.txt``, os overlays, as ferramentas e as **conferências**: cada
  problema com o nível (``erro`` impede capturar; ``aviso``; ``info``), o código, o texto e a correção;
* ``capturas`` -- os ``.bin`` da pasta do firmware e das pastas de coleta, com o resumo do cabeçalho (o título, a
  taxa, os canais, a duração, a integridade), e os ``resumo.csv`` das coletas;
* ``relogio`` -- a hora da placa e se o NTP a sincronizou (o mesmo ``adjtimex`` que o ``ler_adc`` grava no cabeçalho);
* ``logs [N]`` -- as últimas N linhas (50) do kernel e do diário do systemd que falam da PRU, dos pinos e do
  firmware, e as de erro.

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
vale o arquivo do ``systemd-timesyncd`` da árvore falsa.
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
AGENTE = "2"

PINOS_DA_PRU = {"P9_28": "pruout", "P9_29": "pruout", "P9_30": "pruin", "P9_31": "pruout"}   # os do setup.sh
REMOTEPROC_PRU0 = "/sys/class/remoteproc/remoteproc1"                                       # o do ler_adc.c
ENDERECO_DA_PRU0 = "4a334000"                                       # o nome do remoteproc da PRU0: 4a334000.pru
NOME_DO_FIRMWARE_DA_PRU = "am335x-pru0-fw"                          # o do setup.sh
FIRMWARE_INSTALADO = "/lib/firmware/" + NOME_DO_FIRMWARE_DA_PRU
ESTADOS_NORMAIS_DA_PRU = ("running", "offline")
"""O remoteproc da PRU0 numa placa boa: ``running`` durante a captura e ``offline`` entre uma e outra (o ``ler_adc``
a liga no começo e a para no fim; visto na placa de verdade, 15/11/2026)."""
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
PROFUNDIDADE_DAS_COLETAS = 3             # coleta/, capturas/<sonda>/descartadas/
MANIFESTOS = ("resumo.csv", "pontos_coletados.csv", "teto.csv", "referencia_externa.csv")
LIMITE_DE_CAPTURAS = 2000
LIMITE_DE_LINHAS = 5000

TERMOS_DOS_LOGS = ("remoteproc", "pru", "pinctrl", "pinmux", "mcasp", "capemgr", "uio", "ler_adc", "config-pin",
                   "setup.sh", "coletar", "shan_agente")
PRIORIDADE_DE_ERRO = 3                   # err, crit, alert e emerg entram sempre
LINHAS_LIDAS_DO_DIARIO = 500
FILTRO_DO_DIARIO = ("SYSLOG_IDENTIFIER=sudo", "+", "PRIORITY=0", "PRIORITY=1", "PRIORITY=2", "PRIORITY=3")
"""O que o ``journalctl`` já entrega filtrado, pelos índices do diário: o ``sudo`` (cada ``ler_adc`` e ``setup.sh``
passa por ele) ou um erro. O da imagem Buster (systemd 241) não tem o ``--grep``, e ler as ~3500 linhas de um boot
para filtrar aqui levava 3 s na placa; assim, 0,1 s (15/11/2026)."""
CHAVE_DO_UENV = re.compile(r"^[A-Za-z0-9_.]+$")


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
    try:
        v = os.statvfs(caminho)
    except OSError:
        return None
    return {"total_kib": v.f_blocks * v.f_frsize // 1024, "livre_kib": v.f_bavail * v.f_frsize // 1024}


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
    utc = time.time()
    try:
        boot = time.clock_gettime(time.CLOCK_BOOTTIME)
    except (AttributeError, OSError):
        boot = None
    return {"utc": utc, "sincronizado": sincronizado, "fonte": fonte,
            "desde_o_inicio_s": None if boot is None else _desde_o_inicio(boot)}


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
    resumo = f.get("capturas") or {}
    if resumo.get("quantidade"):
        item("info", "capturas", f"{resumo['quantidade']} captura(s) na placa ({resumo.get('bytes', 0) / 1048576.0:.0f} "
             "MiB).")
    ordem = {"erro": 0, "aviso": 1, "info": 2}
    return sorted(itens, key=lambda x: ordem[x["nivel"]])


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
        "relogio_sincronizado": None, "id": None, "maquina": None,
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


def logs_do_kernel(quantas):
    """As mensagens do kernel (o ``/dev/kmsg``, o que o ``dmesg`` lê) da PRU, dos pinos e do firmware, e as de erro;
    ``None`` se o kernel não deixa ler (``dmesg_restrict``)."""
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
        if _relevante(texto, prioridade):
            linhas.append({"utc": None if boot is None else boot + desde_o_boot, "desde_o_boot_s": desde_o_boot,
                           "nivel": prioridade, "origem": "kernel", "texto": texto})
    return linhas[-quantas:]


def logs_do_diario(quantas):
    """As linhas do diário do systemd deste boot (``journalctl -o json``, :data:`FILTRO_DO_DIARIO`) que falam do
    firmware, e as de erro; as do kernel ficam de fora (já vêm do ``/dev/kmsg``). ``None`` sem o ``journalctl``, ou se
    ele falhou."""
    import subprocess

    journalctl = programa("journalctl")
    if journalctl is None:
        return None
    try:
        r = subprocess.run([sistema(journalctl), "-o", "json", "--no-pager", "-b", "-n", str(LINHAS_LIDAS_DO_DIARIO),
                            *FILTRO_DO_DIARIO], capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    linhas = []
    for linha in r.stdout.decode("utf-8", "replace").splitlines():
        try:
            e = json.loads(linha)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("_TRANSPORT") == "kernel" or not isinstance(e.get("MESSAGE"), str):
            continue                           # uma mensagem binária vem como lista de bytes
        texto = e["MESSAGE"]
        try:
            prioridade = int(e.get("PRIORITY"))
        except (TypeError, ValueError):
            prioridade = None
        origem = e.get("SYSLOG_IDENTIFIER") or e.get("_COMM")
        if _relevante(texto + " " + (origem or ""), prioridade):
            try:
                utc = int(e["__REALTIME_TIMESTAMP"]) / 1e6
            except (KeyError, TypeError, ValueError):
                utc = None
            linhas.append({"utc": utc, "nivel": prioridade, "origem": origem, "texto": texto})
    return linhas[-quantas:]


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


def saude():
    fatos = estado()
    fatos.update(uenv=uenv(), overlays=overlays_carregados(), dtbo_da_pru=dtbos_da_pru(), ferramentas=ferramentas())
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


def logs(quantas=50):
    return {"kernel": logs_do_kernel(quantas), "diario": logs_do_diario(quantas), "termos": list(TERMOS_DOS_LOGS)}


def _sem_argumentos(funcao):
    def comando(argumentos):
        if argumentos:
            raise ErroDeUso(f"o comando não leva argumentos: {' '.join(argumentos)}")
        return funcao()
    return comando


def _comando_logs(argumentos):
    if len(argumentos) > 1:
        raise ErroDeUso("logs leva no máximo um argumento, o número de linhas")
    try:
        quantas = int(argumentos[0]) if argumentos else 50
    except ValueError:
        raise ErroDeUso(f"o número de linhas não é um número: {argumentos[0]!r}") from None
    if not 1 <= quantas <= 1000:
        raise ErroDeUso(f"o número de linhas vai de 1 a 1000: {quantas}")
    return logs(quantas)


COMANDOS = {"versao": _sem_argumentos(versao), "estado": _sem_argumentos(estado), "saude": _sem_argumentos(saude),
            "capturas": _sem_argumentos(capturas), "relogio": _sem_argumentos(relogio), "logs": _comando_logs}


def _responder(resposta, codigo):
    sys.stdout.write(json.dumps(resposta, ensure_ascii=False) + "\n")
    return codigo


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    comando = argv[0] if argv else ""
    if comando not in COMANDOS:
        return _responder({"protocolo": PROTOCOLO, "agente": AGENTE, "erro": f"comando desconhecido: {comando!r} (os "
                           f"comandos: {', '.join(sorted(COMANDOS))})"}, 2)
    try:
        dados = COMANDOS[comando](argv[1:])
    except ErroDeUso as e:
        return _responder({"protocolo": PROTOCOLO, "agente": AGENTE, "comando": comando, "erro": str(e)}, 2)
    resposta = {"protocolo": PROTOCOLO, "agente": AGENTE, "comando": comando}
    resposta.update(dados)
    return _responder(resposta, 0)


if __name__ == "__main__":
    sys.exit(main())
