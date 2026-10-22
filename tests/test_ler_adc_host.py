"""Partes do ``firmware/ler_adc.c`` que rodam no computador: compiladas com o gcc do host e chamadas por um harness.

O ``ler_adc`` só roda inteiro na BeagleBone (/dev/mem, PRU). Funções que não tocam o hardware, como a conferência da
reserva da DDR no /proc/iomem (F11), são testadas aqui: o harness inclui o ``.c`` com o ``main`` renomeado.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
FIRMWARE = RAIZ / "firmware"

pytestmark = pytest.mark.skipif(shutil.which("gcc") is None, reason="sem gcc no computador")

HARNESS = r"""
#define main ler_adc_main
#include "ler_adc.c"
#undef main
#include <stdlib.h>
int main(int argc, char **argv) {
    (void)argc;
    return conferir_ddr_reservada(argv[1], strtoull(argv[2], NULL, 0), strtoull(argv[3], NULL, 0)) == 0 ? 0 : 9;
}
"""

# O /proc/iomem de uma BeagleBone com mem=496M (a RAM do Linux para em 0x9EFFFFFF) e o de uma sem.
IOMEM_COM_RESERVA = """44e07000-44e07fff : 44e07000.gpio gpio@0
4a310000-4a312fff : 4a300000.pruss shrdram
80000000-9effffff : System RAM
  80008000-80cfffff : Kernel code
  80e00000-80f6b6ff : Kernel data
"""
IOMEM_SEM_RESERVA = """4a310000-4a312fff : 4a300000.pruss shrdram
80000000-9fffffff : System RAM
  80008000-80cfffff : Kernel code
"""
IOMEM_SEM_ROOT = """00000000-00000000 : 4a300000.pruss shrdram
00000000-00000000 : System RAM
"""
INICIO, FIM = 0x9F000000, 0x9F400000                  # DDR_RESERVED_PHYS + 2 buffers de 2 MB


@pytest.fixture(scope="module")
def conferir(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("harness")
    fonte = pasta / "harness.c"
    fonte.write_text(HARNESS)
    binario = pasta / "harness"
    r = subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", f"-I{FIRMWARE}",
                        "-o", str(binario), str(fonte)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    def rodar(iomem: str) -> subprocess.CompletedProcess:
        arquivo = pasta / "iomem"
        arquivo.write_text(iomem)
        return subprocess.run([str(binario), str(arquivo), hex(INICIO), hex(FIM)], capture_output=True, text=True)
    return rodar


def test_com_mem_496m_os_buffers_estao_fora_do_linux(conferir):
    r = conferir(IOMEM_COM_RESERVA)
    assert r.returncode == 0 and r.stderr == ""


def test_sem_a_reserva_a_captura_e_recusada_com_o_remedio(conferir):
    r = conferir(IOMEM_SEM_RESERVA)
    assert r.returncode == 9
    assert "System RAM" in r.stderr and "mem=496M" in r.stderr


def test_sem_root_os_enderecos_sao_zeros_e_so_avisa(conferir):
    r = conferir(IOMEM_SEM_ROOT)
    assert r.returncode == 0 and "não foi conferida" in r.stderr


def test_ler_adc_trata_sigterm_e_sighup_como_o_ctrl_c_e_para_a_pru_no_fim():
    """F6: um kill ou a queda do ssh reescrevem o cabeçalho final; a PRU não fica gravando na DDR depois."""
    fonte = (FIRMWARE / "ler_adc.c").read_text(encoding="utf-8")
    for sinal in ("SIGINT", "SIGTERM", "SIGHUP"):
        assert f"signal({sinal}, lidar_interrupcao);" in fonte
    assert "signal(SIGPIPE, SIG_IGN);" in fonte
    fim = fonte[fonte.index("Cabeçalho final atualizado"):]
    assert 'escrever_estado_remoteproc("stop")' in fim
