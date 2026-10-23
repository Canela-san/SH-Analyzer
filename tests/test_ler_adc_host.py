"""Partes do ``firmware/ler_adc.c`` que rodam no computador: compiladas com o gcc do host e chamadas por um harness.

O ``ler_adc`` só roda inteiro na BeagleBone (/dev/mem, PRU). Funções que não tocam o hardware, como a conferência da
reserva da DDR no /proc/iomem (F11), são testadas aqui: o harness inclui o ``.c`` com o ``main`` renomeado.
"""

import os
import re
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
    fim = fonte[fonte.index("imprimir_resultado(&config"):]
    assert 'escrever_estado_remoteproc("stop")' in fim


# --------------------------------------------------------------------------------------
# [23/10/2026] Frequência lida inteira, o teto da PRU e o início sem corrida
# --------------------------------------------------------------------------------------
HARNESS_TAXA = r"""
#define main ler_adc_main
#include "ler_adc.c"
#undef main
#include <stdlib.h>
int main(int argc, char **argv) {
    (void)argc;
    if (strcmp(argv[1], "freq") == 0) {
        uint32_t f = 0;
        int r = analisar_frequencia(argv[2], &f);
        printf("%d %u\n", r, f);
        return 0;
    }
    uint32_t atrasos[3] = {(uint32_t)atoi(argv[3]), (uint32_t)atoi(argv[4]), (uint32_t)atoi(argv[5])};
    uint32_t modo = (uint32_t)atoi(argv[2]);
    if (strcmp(argv[1], "teto") == 0) {
        printf("%u\n", teto_ticks_da_pru(modo, atrasos));
        return 0;
    }
    return conferir_teto_da_taxa((uint32_t)atoi(argv[6]), modo, atrasos, atoi(argv[7])) == 0 ? 0 : 9;
}
"""


@pytest.fixture(scope="module")
def taxa(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("harness_taxa")
    fonte = pasta / "harness.c"
    fonte.write_text(HARNESS_TAXA)
    binario = pasta / "harness"
    r = subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", f"-I{FIRMWARE}",
                        "-o", str(binario), str(fonte)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    def rodar(*args) -> subprocess.CompletedProcess:
        return subprocess.run([str(binario), *map(str, args)], capture_output=True, text=True)
    return rodar


@pytest.mark.parametrize("texto, esperado", [("400000", "0 400000"), ("1", "0 1"), ("500000", "0 500000"),
                                             ("400k", "-1 0"), ("4e5", "-1 0"), ("0", "-1 0"), ("500001", "-1 0"),
                                             ("", "-1 0"), ("99999999999999999999", "-1 0")])
def test_a_frequencia_e_lida_inteira(taxa, texto, esperado):
    """O atoi de antes lia '400k' como 400 Hz e '4e5' como 4 Hz, sem erro."""
    assert taxa("freq", texto).stdout.split() == esperado.split()


@pytest.mark.parametrize("modo", [0, 2])
@pytest.mark.parametrize("atrasos", [(3, 1, 3), (1, 1, 1), (10, 1, 3), (3, 5, 3), (3, 1, 9), (3, 1, 10), (3, 1, 20),
                                     (200, 100, 100)])
def test_o_teto_do_ler_adc_e_o_do_simulador_menos_o_tick_medido_na_placa(taxa, modo, atrasos):
    """Na placa, o teto com as esperas padrão foi 1 tick abaixo do simulador nos dois SPI (477 contra 478 no rápido,
    T7g; 610 contra 611 no lento, T7f). A conta do ler_adc para outras esperas tem de seguir o simulador."""
    import test_pru_asm as t
    from pru_sim import LATENCIAS_PRU_REAL
    periodo = 3000
    pru = t.executar_com_arm(t.pru_laco(periodo=periodo, atrasos=atrasos, modo_spi=modo, latencias=LATENCIAS_PRU_REAL,
                                        adc=t.ModeloADC(0x7FFF, atraso_ciclos=9)))
    teto_simulador = periodo - pru.regs[12]
    assert int(taxa("teto", modo, *atrasos).stdout) == teto_simulador - 1


def test_taxa_acima_do_teto_e_recusada_a_nao_ser_com_forcar(taxa):
    assert taxa("conferir", 2, 3, 1, 3, 419287, 0).returncode == 0            # 477 ticks: o teto do SPI rápido
    r = taxa("conferir", 2, 3, 1, 3, 419288, 0)
    assert r.returncode == 9 and "419287 Hz" in r.stderr and "--forcar-taxa" in r.stderr
    r = taxa("conferir", 2, 3, 1, 3, 500000, 1)
    assert r.returncode == 0 and "Aviso" in r.stderr
    assert taxa("conferir", 0, 3, 1, 3, 400000, 0).returncode == 9            # o SPI lento não chega a 400 kS/s
    assert taxa("conferir", 0, 3, 1, 3, 312500, 0).returncode == 0


def test_inicio_sem_corrida_a_pru_avisa_que_esta_pronta_depois_de_zerar_config_ready():
    """O ler_adc zera config_ready e escreve a marca com a PRU parada, e só configura depois de a PRU trocar a marca
    por 0, que o pru_main.c escreve DEPOIS de zerar config_ready (o config_ready = 1 do ARM nunca é apagado)."""
    pru_main = (FIRMWARE / "pru_main.c").read_text(encoding="utf-8")
    assert pru_main.index("ctrl->config_ready = 0;") < pru_main.index("ctrl->versao_protocolo_pru = 0;") \
        < pru_main.index("ler_ads8688_asm(ctrl);")
    fonte = (FIRMWARE / "ler_adc.c").read_text(encoding="utf-8")
    reinicio = fonte[fonte.index("static int reiniciar_pru_antes_da_captura"):]
    assert reinicio.index("ctrl->versao_protocolo_pru = PRU_AINDA_NAO_INICIOU;") \
        < reinicio.index('escrever_estado_remoteproc("start")') < reinicio.index("ctrl->versao_protocolo_pru != 0")
    principal = fonte[fonte.index("int main("):]
    assert principal.index("reiniciar_pru_antes_da_captura(ctrl)") < principal.index("ctrl->config_ready = 1;")
    assert "ctrl->versao_protocolo_pru = 0;" not in principal


def test_erro_depois_de_ligar_a_pru_para_a_pru():
    """Entre o reinício da PRU e o laço de captura, toda saída com erro passa por abortar_captura (que para a PRU)."""
    fonte = (FIRMWARE / "ler_adc.c").read_text(encoding="utf-8")
    principal = fonte[fonte.index("int main("):]
    trecho = principal[principal.index("if (reiniciar_pru_antes_da_captura(ctrl) != 0) {"):principal.index("while (manter_execucao")]
    depois_do_reinicio = trecho[trecho.index("ctrl->buffer_0_addr"):]
    assert "return -1;" not in depois_do_reinicio
    assert depois_do_reinicio.count("return abortar_captura(") == 3



# --------------------------------------------------------------------------------------
# [23/10/2026] Pinos da PRU, ADC mudo, o resumo que o coletar.sh lê (coleta/comum.sh) e os códigos de saída
# --------------------------------------------------------------------------------------
HARNESS_SAIDA = r"""
#define main ler_adc_main
#include "ler_adc.c"
#undef main
int main(int argc, char **argv) {
    if (strcmp(argv[1], "pinos") == 0) {
        printf("%d\n", preparar_pinos_da_pru(argv[2]));
        return 0;
    }
    if (strcmp(argv[1], "mudo") == 0) {
        uint16_t vivo[8] = {32800, 32801, 32800, 32799, 32800, 32800, 32802, 32800}, morto[8] = {0};
        printf("%d %d\n", amostras_todas_iguais(vivo, 8), amostras_todas_iguais(morto, 8));
        return 0;
    }
    /* resultado ATRASADAS DIV_A DIV_C BLOCOS -- argumentos do ler_adc */
    struct configuracao c;
    if (analisar_argumentos(argc - 6, argv + 6, &c) != 0) return 2;
    struct shared_control ctrl;
    memset(&ctrl, 0, sizeof(ctrl));
    ctrl.sample_period_ticks = c.ticks;
    uint32_t atrasadas = (uint32_t)atoi(argv[2]);
    struct contadores_integridade n = {atrasadas, 0, 0, atrasadas ? 0 : 18, atrasadas ? 77 : 0,
                                       (uint32_t)atoi(argv[3]), (uint32_t)atoi(argv[4])};
    unsigned long long blocos = (unsigned long long)atoi(argv[5]);
    struct resultado r = {blocos, blocos * SAMPLES_PER_BUFFER, blocos >= 2 ? 399931.0 : 0.0, 0.15, 0, 0};
    imprimir_resultado(&c, &ctrl, &n, &r);
    return 0;
}
"""


def _compilar(tmp_path_factory, nome: str, fonte: str, *extras: str) -> Path:
    pasta = tmp_path_factory.mktemp(nome)
    arquivo = pasta / f"{nome}.c"
    arquivo.write_text(fonte)
    binario = pasta / nome
    r = subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", f"-I{FIRMWARE}",
                        *extras, "-o", str(binario), str(arquivo)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return binario


@pytest.fixture(scope="module")
def saida(tmp_path_factory):
    binario = _compilar(tmp_path_factory, "harness_saida", HARNESS_SAIDA)

    def rodar(*args) -> subprocess.CompletedProcess:
        return subprocess.run([str(binario), *map(str, args)], capture_output=True, text=True,
                              env={"PATH": "/usr/bin:/bin", "TERM": "dumb"})
    return rodar


PINOS_DO_SPI = {"P9_31": "pruout", "P9_29": "pruout", "P9_30": "pruin", "P9_28": "pruout"}


def _pinmux(base: Path, modos: dict[str, str]) -> Path:
    for pino, modo in modos.items():
        (base / f"ocp:{pino}_pinmux").mkdir(parents=True, exist_ok=True)
        (base / f"ocp:{pino}_pinmux" / "state").write_text(modo + "\n")
    return base


def test_pinos_depois_de_um_reinicio_sao_configurados_de_novo(saida, tmp_path):
    """Depois de um reinício, o config-pin se perde (os pinos voltam a 'default'): o ler_adc avisa e escreve o modo
    da PRU, como o config-pin do setup.sh (echo MODO > state)."""
    base = _pinmux(tmp_path, {p: "default" for p in PINOS_DO_SPI})
    r = saida("pinos", base)
    assert r.stdout.split()[-1] == "0", r.stdout + r.stderr
    assert "Aviso:" in r.stderr and "P9_31 (SCLK) em 'default'" in r.stderr and "reiniciada" in r.stderr
    assert "pinos da PRU configurados" in r.stdout
    assert {p: (base / f"ocp:{p}_pinmux" / "state").read_text().strip() for p in PINOS_DO_SPI} == PINOS_DO_SPI


def test_pinos_ja_certos_nao_geram_aviso_nem_escrita(saida, tmp_path):
    base = _pinmux(tmp_path, PINOS_DO_SPI)
    antes = {p: (base / f"ocp:{p}_pinmux" / "state").stat().st_mtime_ns for p in PINOS_DO_SPI}
    r = saida("pinos", base)
    assert r.stdout.split()[-1] == "0" and r.stderr == ""
    assert {p: (base / f"ocp:{p}_pinmux" / "state").stat().st_mtime_ns for p in PINOS_DO_SPI} == antes


def test_sem_o_pinmux_do_config_pin_so_avisa(saida, tmp_path):
    r = saida("pinos", tmp_path / "nao_existe")
    assert r.stdout.split()[-1] == "1" and "não deu para conferir os pinos" in r.stderr and "setup.sh" in r.stderr


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="como root, o arquivo só-leitura é gravável")
def test_pino_que_nao_aceita_o_modo_e_erro(saida, tmp_path):
    base = _pinmux(tmp_path, {**PINOS_DO_SPI, "P9_31": "default"})
    (base / "ocp:P9_31_pinmux" / "state").chmod(0o444)
    r = saida("pinos", base)
    assert r.stdout.split()[-1] == "-1" and "Erro:" in r.stderr and "P9_31" in r.stderr


def test_pinos_do_ler_adc_sao_os_do_setup_sh():
    setup = (FIRMWARE / "setup.sh").read_text(encoding="utf-8")
    do_setup = dict(re.findall(r"^config-pin (P9_\d+) (\w+)", setup, re.M))
    fonte = (FIRMWARE / "ler_adc.c").read_text(encoding="utf-8")
    do_ler_adc = {p: m for p, m, _ in re.findall(r'\{"(P9_\d+)", "(\w+)", "([^"]*)"\}', fonte)}
    assert do_setup == do_ler_adc == PINOS_DO_SPI


def test_adc_mudo_e_amostras_todas_iguais(saida):
    assert saida("mudo").stdout.split() == ["0", "1"]


def _seds_do_coletar() -> dict[str, str]:
    """Os scripts sed com que o coletar.sh (coleta/comum.sh, ler_resumo) lê o resumo do ler_adc."""
    sh = (FIRMWARE / "coleta" / "comum.sh").read_text(encoding="utf-8")
    achados = {}
    for nome in ("integridade", "taxa_arm", "folga", "pior", "divergencias"):
        m = re.search(rf"{nome}=\$\(printf '%s\\n' \"\$saida\"\s*\\?\s*\|\s*sed -n '([^']+)'", sh)
        assert m, f"o coleta/comum.sh não lê mais '{nome}' com sed"
        achados[nome] = m.group(1)
    return achados


def _ler_como_o_coletar(texto: str) -> dict[str, str]:
    return {nome: subprocess.run(["sed", "-n", script], input=texto, capture_output=True, text=True).stdout.strip()
            for nome, script in _seds_do_coletar().items()}


def test_o_coletar_le_o_resumo_do_ler_adc(saida):
    """O resumo de verdade (imprimir_resultado), lido com os mesmos sed do coletar.sh: uma captura limpa e uma com
    amostras atrasadas e divergências (no singular e no plural)."""
    limpo = saida("resultado", 0, 0, 0, 12, "ler_adc", "400000", "1", "--blocos", "12")
    assert _ler_como_o_coletar(limpo.stdout + limpo.stderr) == {
        "integridade": "0 0 0", "taxa_arm": "399931 -0.02", "folga": "18", "pior": "", "divergencias": "0 0"}
    atrasado = saida("resultado", 1, 1, 7, 2, "ler_adc", "400000", "1", "--blocos", "2")
    lido = _ler_como_o_coletar(atrasado.stdout + atrasado.stderr)
    assert lido["integridade"] == "1 0 0" and lido["pior"] == "77" and lido["folga"] == ""
    assert lido["divergencias"] == "1 7"
    assert "Captura concluída, com avisos" in atrasado.stdout and "Aviso:" in atrasado.stderr


@pytest.fixture(scope="module")
def ler_adc(tmp_path_factory):
    return _compilar(tmp_path_factory, "ler_adc", (FIRMWARE / "ler_adc.c").read_text(encoding="utf-8"),
                     '-DVERSAO_FIRMWARE="v0.0-teste"')


def test_ajuda_e_codigos_de_saida(ler_adc):
    ajuda = subprocess.run([str(ler_adc), "--help"], capture_output=True, text=True)
    assert ajuda.returncode == 0 and "-v, --verbose" in ajuda.stdout and "--forcar-taxa" in ajuda.stdout
    for args in (["400k"], ["--xyz"], ["400000", "1", "--faixa-adc", "1:5.13"], ["500000"], ["--blocos"]):
        r = subprocess.run([str(ler_adc), *args], capture_output=True, text=True)
        assert r.returncode == 2 and r.stderr.startswith("Erro:"), (args, r.stderr)
    if os.geteuid() != 0:
        r = subprocess.run([str(ler_adc), "400000", "1"], capture_output=True, text=True)
        assert r.returncode == 1 and "sudo" in r.stderr
