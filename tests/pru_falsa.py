"""Uma placa FALSA para rodar o ``firmware/ler_adc.c`` inteiro no computador: a captura de ponta a ponta, sem BeagleBone.

O ``ler_adc`` fala com a PRU por dois pedaços do ``/dev/mem`` (o ``shared_control`` na RAM compartilhada e os dois
buffers na DDR) e a liga pelo remoteproc. Aqui, um arquivo esparso faz o papel do ``/dev/mem`` (as mesmas posições:
0x4A310000 e 0x9F000000), e :class:`PruFalsa`, uma thread do teste, o da PRU: mapeia o mesmo arquivo e segue o
protocolo do ``pru_main.c`` e do ``spi_core.asm`` (o aviso de "pronta", a leitura da configuração, a versão do
protocolo, os buffers alternados, a marca de pronto um pouco depois da troca e os contadores publicados depois dela).
O ``ler_adc`` é o de verdade, compilado com os caminhos da placa trocados (os ``#ifndef`` do topo dele).

O que NÃO é conferido aqui: o assembly (``pru_sim.py``), os tempos de verdade e o ``/dev/mem`` sem cache.
"""

from __future__ import annotations

import mmap
import os
import shutil
import struct
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
FIRMWARE = RAIZ / "firmware"

SHARED_RAM = 0x4A310000                 # PRU_SHARED_RAM_PHYS
DDR = 0x9F000000                        # DDR_RESERVED_PHYS
AMOSTRAS_POR_BLOCO = 1048576            # SAMPLES_PER_BUFFER
BYTES_POR_BUFFER = 2 * AMOSTRAS_POR_BLOCO
AINDA_NAO_INICIOU = 0xFFFFFFFF          # PRU_AINDA_NAO_INICIOU

# struct shared_control (firmware/memoria_pru.h); tests/test_contrato_firmware.py confere os offsets.
CAMPOS = {
    "sample_period_ticks": 0, "active_buffer": 4, "buffer_0_ready": 8, "buffer_1_ready": 12, "buffer_0_addr": 16,
    "buffer_1_addr": 20, "config_ready": 24, "auto_seq_mask": 28, "range_sel": 32, "amostras_atrasadas": 36,
    "buffers_sobrescritos": 40, "quadros_preambulo_ruim": 44, "atraso_cs_setup": 48, "atraso_cs_hold": 52,
    "atraso_cs_alto": 56, "folga_minima_ciclos": 60, "atraso_maximo_ciclos": 64, "ciclos_rebase": 68,
    "versao_protocolo_pru": 72, "modo_spi": 76, "divergencias_fase_a": 80, "divergencias_fase_c": 84,
}

HARNESS = r"""
#define _FILE_OFFSET_BITS 64
#include <stdlib.h>
#include <unistd.h>
#define geteuid() ((uid_t)0)                         /* o ler_adc exige root (a placa de verdade) */
#define CAMINHO_DEV_MEM getenv("FALSO_DEV_MEM")
#define CAMINHO_IOMEM getenv("FALSO_IOMEM")
#define REMOTEPROC_PRU0_ESTADO getenv("FALSO_REMOTEPROC")
#define BASE_PINMUX getenv("FALSO_PINMUX")
#include "ler_adc.c"
"""

IOMEM = "4a310000-4a312fff : 4a300000.pruss shrdram\n80000000-9effffff : System RAM\n"
PINOS = {"P9_31": "pruout", "P9_29": "pruout", "P9_30": "pruin", "P9_28": "pruout"}


def versao_do_protocolo() -> int:
    """VERSAO_PROTOCOLO_PRU de memoria_pru.h: a que a PRU de verdade publica."""
    import re
    return int(re.search(r"#define\s+VERSAO_PROTOCOLO_PRU\s+(\d+)", (FIRMWARE / "memoria_pru.h").read_text()).group(1))


def compilar_ler_adc(pasta: Path) -> Path:
    """O ler_adc de verdade, com os caminhos da placa vindos do ambiente (FALSO_*)."""
    fonte = pasta / "ler_adc_falsa_placa.c"
    fonte.write_text(HARNESS)
    binario = pasta / "ler_adc"
    r = subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-O1", f"-I{FIRMWARE}",
                        '-DVERSAO_FIRMWARE="teste-placa-falsa"', "-o", str(binario), str(fonte), "-lm"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return binario


def bloco_esperado(k: int, satura: bool = False) -> np.ndarray:
    """As amostras do bloco k (a partir de 0) que a PRU falsa grava: uma rampa de 1 a 65534 que começa em 1 + k (cada
    bloco é diferente, a posição de cada amostra dentro dele é conferível, e nenhuma toca o fundo de escala: o ler_adc
    acusa a saturação). ``satura``: a rampa inteira, de 0 a 65535."""
    rampa = np.arange(AMOSTRAS_POR_BLOCO, dtype=np.uint32) + k
    return (rampa % 65536 if satura else 1 + rampa % 65534).astype("<u2")


@dataclass
class PruFalsa(threading.Thread):
    """A PRU do outro lado do ``/dev/mem`` falso. Liga com ``start()``; ``parar()`` no fim do teste."""

    mem: Path
    intervalo_s: float = 0.03               # tempo para "encher" um bloco
    versao: int | None = None               # a versão do protocolo que ela publica (None = a do memoria_pru.h)
    responde: bool = True                   # False: nunca avisa que está pronta (firmware antigo, PRU travada)
    da_uma_volta_no_arm: bool = False       # enche os 2 buffers e começa a reescrever o 1º antes de o ARM gravá-lo
    mudo: bool = False                      # o ADC sem resposta: amostras todas 0
    satura: bool = False                    # o sinal bate no fundo de escala (códigos 0 e 65535)
    atrasadas_por_bloco: int = 0
    preambulo_por_bloco: int = 0
    folga: int = 18
    max_blocos: int | None = None           # para de produzir depois de tantos blocos
    demora_para_ficar_pronta_s: float = 0.0  # o tempo do start do remoteproc até o pru_main.c avisar
    # As amostras de cada bloco, em vez da rampa: sinal(taxa_total_hz, auto_seq_mask, k) -> AMOSTRAS_POR_BLOCO códigos
    # (o 'ler_adc verificar' precisa de um espectro de verdade). A taxa é a da configuração que o ARM escreveu.
    sinal: Callable[[float, int, int], np.ndarray] | None = None
    instante_da_configuracao: float = 0.0   # time.time() em que ela viu config_ready = 1
    configuracao: dict[str, int] = field(default_factory=dict)      # o que o ARM escreveu antes de config_ready = 1
    configuracoes: list[dict[str, int]] = field(default_factory=list)   # a de cada reinício, em ordem
    blocos_prontos: int = 0
    instantes_pronto: list[float] = field(default_factory=list)     # time.monotonic() de cada marca de pronto
    erro: BaseException | None = None

    def __post_init__(self) -> None:
        super().__init__(daemon=True)
        self._parar = threading.Event()
        self._arquivo = open(self.mem, "r+b")
        self._ctrl = mmap.mmap(self._arquivo.fileno(), 4096, offset=SHARED_RAM)
        self._ddr = mmap.mmap(self._arquivo.fileno(), 2 * BYTES_POR_BUFFER, offset=DDR)

    def __hash__(self) -> int:               # o dataclass tira o __hash__ que o threading.Thread usa
        return id(self)

    def ler(self, campo: str) -> int:
        return struct.unpack_from("<I", self._ctrl, CAMPOS[campo])[0]

    def escrever(self, campo: str, valor: int) -> None:
        struct.pack_into("<I", self._ctrl, CAMPOS[campo], valor & 0xFFFFFFFF)

    def parar(self) -> None:
        self._parar.set()
        self.join(timeout=10)
        self._ctrl.close()
        self._ddr.close()
        self._arquivo.close()
        if self.erro is not None:
            raise self.erro

    def _esperar(self, condicao) -> bool:
        while not self._parar.is_set():
            if condicao():
                return True
            time.sleep(0.0005)
        return False

    def run(self) -> None:
        try:
            self._rodar()
        except BaseException as e:           # noqa: BLE001 -- o erro da thread aparece no parar()
            self.erro = e

    def _reiniciada(self) -> bool:
        """O ARM pôs a marca de novo: reiniciou a PRU para outra captura (o 'ler_adc verificar' faz uma por taxa)."""
        return self.ler("versao_protocolo_pru") == AINDA_NAO_INICIOU

    def _rodar(self) -> None:
        # Cada volta é um boot da PRU: o ARM a reinicia (a marca em versao_protocolo_pru) a cada captura.
        while not self._parar.is_set():
            if not self._uma_captura():
                return

    def _uma_captura(self) -> bool:
        """Uma captura, do boot ao fim. False = parar (o teste acabou, ou a PRU não responde)."""
        # pru_main.c: com a marca do ARM no lugar (ele acabou de dar o start), zera config_ready e só então avisa.
        if not self._esperar(self._reiniciada) or not self.responde:
            return False
        if self._parar.wait(self.demora_para_ficar_pronta_s):
            return False
        self.escrever("config_ready", 0)
        self.escrever("versao_protocolo_pru", 0)
        if not self._esperar(lambda: self.ler("config_ready") == 1):
            return False
        self.instante_da_configuracao = time.time()
        self.configuracao = {campo: self.ler(campo) for campo in CAMPOS}
        self.configuracoes.append(self.configuracao)
        taxa = 200e6 / self.configuracao["sample_period_ticks"]
        # spi_core.asm, antes da 1ª amostra: zera o que publica e escreve a versão do protocolo.
        for campo in ("amostras_atrasadas", "buffers_sobrescritos", "quadros_preambulo_ruim", "atraso_maximo_ciclos",
                      "divergencias_fase_a", "divergencias_fase_c", "active_buffer"):
            self.escrever(campo, 0)
        self.escrever("folga_minima_ciclos", self.configuracao["sample_period_ticks"])
        self.escrever("ciclos_rebase", 7)
        time.sleep(0.003)
        self.escrever("versao_protocolo_pru", versao_do_protocolo() if self.versao is None else self.versao)
        sobrescritos = 0
        k = 0
        while not self._parar.is_set() and (self.max_blocos is None or k < self.max_blocos):
            b = k % 2
            pronto = f"buffer_{b}_ready"
            if self.ler(pronto) != 0 and not self._esperar(
                    lambda: self.ler(pronto) == 0 or self._reiniciada()):                       # noqa: B023
                return False
            if self._reiniciada():
                return True
            if self.mudo:
                dados = np.zeros(AMOSTRAS_POR_BLOCO, dtype="<u2")
            elif self.sinal is not None:
                dados = np.asarray(self.sinal(taxa, self.configuracao["auto_seq_mask"], k), dtype="<u2")
            else:
                dados = bloco_esperado(k, self.satura)
            self._ddr[b * BYTES_POR_BUFFER:(b + 1) * BYTES_POR_BUFFER] = dados.tobytes()
            if self._parar.wait(self.intervalo_s):
                return False
            if self._reiniciada():
                return True
            # A troca e os eventos 1 a 7: o buffer pronto, o ativo e os contadores, nesta ordem.
            if self.da_uma_volta_no_arm and k == 0:
                k = 1                        # o ARM "não viu" o bloco 0 a tempo: a marca dele só vem com a do bloco 1
                continue
            if self.da_uma_volta_no_arm and k == 1:
                # Os 2 buffers cheios e o ARM sem ter gravado nenhum: a PRU não espera, volta ao buffer 0 (as 3
                # primeiras amostras do bloco seguinte) e, no evento 3, vê que ele ainda está marcado como pronto.
                # (Aqui a reescrita vem antes da marca, para o teste não depender de quem chega primeiro.)
                self._ddr[0:6] = bloco_esperado(2)[:3].tobytes()
                self.escrever("buffer_0_ready", 1)
                sobrescritos += 1
            self.escrever(pronto, 1)
            self.instantes_pronto.append(time.monotonic())
            self.escrever("active_buffer", 1 - b)
            k += 1
            self.blocos_prontos = k
            self.escrever("amostras_atrasadas", k * self.atrasadas_por_bloco)
            self.escrever("buffers_sobrescritos", sobrescritos)
            self.escrever("quadros_preambulo_ruim", k * self.preambulo_por_bloco)
            self.escrever("folga_minima_ciclos", self.folga)
            self.escrever("atraso_maximo_ciclos", 77 if self.atrasadas_por_bloco else 0)
        return True


class PlacaFalsa:
    """A pasta com o ``/dev/mem`` falso, o remoteproc, os pinos e o ``/proc/iomem``, e o ambiente do ``ler_adc``."""

    def __init__(self, pasta: Path) -> None:
        self.pasta = pasta
        self.mem = pasta / "dev_mem"
        with open(self.mem, "wb") as f:
            f.truncate(DDR + 2 * BYTES_POR_BUFFER)             # esparso: só o que for escrito ocupa disco
        self.remoteproc = pasta / "remoteproc_state"
        self.remoteproc.write_text("offline\n")
        (pasta / "iomem").write_text(IOMEM)
        for pino, modo in PINOS.items():
            pinmux = pasta / "pinmux" / f"ocp:{pino}_pinmux"
            pinmux.mkdir(parents=True)
            (pinmux / "state").write_text(modo + "\n")
        self.ambiente = {**os.environ, "FALSO_DEV_MEM": str(self.mem), "FALSO_IOMEM": str(pasta / "iomem"),
                         "FALSO_REMOTEPROC": str(self.remoteproc), "FALSO_PINMUX": str(pasta / "pinmux"),
                         "TERM": "dumb", "LC_ALL": "C"}

    def pru(self, **opcoes) -> PruFalsa:
        pru = PruFalsa(self.mem, **opcoes)
        pru.start()
        return pru


def tem_gcc() -> bool:
    return shutil.which("gcc") is not None
