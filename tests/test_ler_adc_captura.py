"""A captura do ``firmware/ler_adc.c`` de ponta a ponta, no computador: o ``main`` de verdade contra uma placa falsa.

Até 11/11/2026 o ``main`` do ``ler_adc`` (o handshake com a PRU, o laço de blocos, o cabeçalho final, os códigos de
saída) só rodava na BeagleBone: os testes conferiam funções soltas e a ordem de trechos do fonte. Aqui o programa
inteiro roda contra ``tests/pru_falsa.py`` (um arquivo no lugar do ``/dev/mem`` e uma thread no lugar da PRU), e o
``.bin`` que ele grava é lido pelo ``supraharmonicos.cabecalho``, como na análise.
"""

import subprocess
import time

import numpy as np
import pytest
from pru_falsa import (
    AMOSTRAS_POR_BLOCO,
    DDR,
    PlacaFalsa,
    bloco_esperado,
    compilar_ler_adc,
    tem_gcc,
    versao_do_protocolo,
)
from supraharmonicos import cabecalho as cab

pytestmark = pytest.mark.skipif(not tem_gcc(), reason="sem gcc no computador")

TAMANHO_BLOCO = 2 * AMOSTRAS_POR_BLOCO


@pytest.fixture(scope="module")
def ler_adc(tmp_path_factory):
    return compilar_ler_adc(tmp_path_factory.mktemp("ler_adc_placa_falsa"))


@pytest.fixture
def placa(tmp_path):
    return PlacaFalsa(tmp_path)


def capturar(ler_adc, placa, *args, pru=None, **opcoes_da_pru):
    """Roda o ler_adc até o fim contra uma PRU falsa. Devolve (processo terminado, a PRU, o .bin)."""
    saida = placa.pasta / "captura.bin"
    pru = pru or placa.pru(**opcoes_da_pru)
    try:
        r = subprocess.run([str(ler_adc), *map(str, args), "-o", str(saida)], env=placa.ambiente, capture_output=True,
                           text=True, timeout=60)
    finally:
        pru.parar()
    return r, pru, saida


def blocos_do_arquivo(caminho) -> list[np.ndarray]:
    dados = np.fromfile(caminho, dtype="<u2", offset=cab.CABECALHO_TAMANHO_TOTAL)
    return [dados[i:i + AMOSTRAS_POR_BLOCO] for i in range(0, len(dados), AMOSTRAS_POR_BLOCO)]


def test_captura_inteira_o_que_a_pru_recebe_e_o_que_o_bin_guarda(ler_adc, placa):
    """3 blocos a 400 kS/s nos canais 1 e 0: a configuração que chega à PRU, os blocos na ordem em que encheram e o
    cabeçalho v8 que a análise lê."""
    r, pru, saida = capturar(ler_adc, placa, 400000, "1,0", "--blocos", 3, "--faixa-adc", "0:5.12", "--grandeza",
                             "0:corrente", "--sonda", "0:sct013_100a_sn001", "-t", "título é UTF-8", "-d", "ref: f=1000Hz")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Captura concluída" in r.stdout and "tudo certo" in r.stdout and r.stderr == ""

    # O que o ARM escreveu antes de config_ready = 1 (o contrato de memoria_pru.h).
    c = pru.configuracao
    assert c["sample_period_ticks"] == 500                     # 200 MHz / 400 kS/s
    assert c["auto_seq_mask"] == 0b11 and c["range_sel"] == 0x02          # canal 0 em ±2,56 V (código 2), o 1 no padrão
    assert (c["buffer_0_addr"], c["buffer_1_addr"]) == (DDR, DDR + TAMANHO_BLOCO)
    assert (c["atraso_cs_setup"], c["atraso_cs_hold"], c["atraso_cs_alto"]) == (3, 1, 3)
    assert c["modo_spi"] == 2 and c["buffer_0_ready"] == 0 and c["buffer_1_ready"] == 0

    # O arquivo: cabeçalho + 3 blocos inteiros, na ordem em que a PRU os encheu (buffers 0, 1, 0).
    assert saida.stat().st_size == cab.CABECALHO_TAMANHO_TOTAL + 3 * TAMANHO_BLOCO
    for k, bloco in enumerate(blocos_do_arquivo(saida)):
        assert np.array_equal(bloco, bloco_esperado(k)), f"bloco {k}"

    h = cab.ler_cabecalho(saida)
    assert h.versao_cabecalho == 8 and h.frequencia_hz == 400000 and h.sample_period_ticks == 500
    assert h.lista_canais[:2] == (0, 1) and h.num_canais == 2                 # ordem crescente: a da varredura
    assert h.blocos_gravados == 3 and h.total_amostras_gravadas == 3 * AMOSTRAS_POR_BLOCO
    assert (h.amostras_atrasadas, h.buffers_sobrescritos, h.quadros_preambulo_ruim) == (0, 0, 0)
    assert h.folga_minima_ciclos == 18 and h.ciclos_rebase == 7 and h.versao_protocolo_pru == versao_do_protocolo()
    assert h.faixa_adc_codigo_por_canal[:2] == (2, 0) and h.sonda_id_por_canal[0] == "sct013_100a_sn001"
    assert h.titulo == "título é UTF-8" and h.descricao == "ref: f=1000Hz"
    assert h.versao_firmware == "teste-placa-falsa" and h.modo_spi == 2
    assert h.kernel and h.disco_saida_total_kib and h.disco_saida_livre_fim_kib is not None    # o sistema, de verdade
    assert placa.remoteproc.read_text().startswith("stop")                    # a PRU não fica ligada depois


def test_firmware_de_outro_protocolo_na_pru_e_recusado_sem_criar_o_arquivo(ler_adc, placa):
    r, _, saida = capturar(ler_adc, placa, "--blocos", 1, versao=versao_do_protocolo() - 1)
    assert r.returncode == 1 and "o firmware da PRU não é o deste ler_adc" in r.stderr
    assert not saida.exists() and placa.remoteproc.read_text().startswith("stop")


def test_pru_que_nao_avisa_que_esta_pronta_e_erro_em_meio_segundo(ler_adc, placa):
    inicio = time.monotonic()
    r, _, saida = capturar(ler_adc, placa, "--blocos", 1, responde=False)
    assert r.returncode == 1 and "a PRU não ficou pronta" in r.stderr and not saida.exists()
    assert time.monotonic() - inicio < 5


def test_adc_mudo_para_no_primeiro_bloco_com_o_codigo_4(ler_adc, placa):
    r, _, saida = capturar(ler_adc, placa, "--blocos", 5, mudo=True)
    assert r.returncode == 4 and "o ADC não está respondendo" in r.stderr
    assert cab.ler_cabecalho(saida).blocos_gravados == 1


def test_buffer_que_o_arm_nao_gravou_a_tempo_sai_com_o_codigo_3(ler_adc, placa):
    """A PRU não espera o ARM: se ela enche os 2 buffers e volta ao primeiro antes de o ARM gravá-lo, a sobrescrita
    é contada, vai para o cabeçalho e o código de saída é 3 (amostras perdidas)."""
    r, _, saida = capturar(ler_adc, placa, "--blocos", 4, da_uma_volta_no_arm=True)
    assert r.returncode == 3, r.stdout + r.stderr
    assert "Captura com amostras perdidas" in r.stdout and "PERDIDAS" in r.stderr
    assert cab.ler_cabecalho(saida).buffers_sobrescritos == 1
    primeiro = blocos_do_arquivo(saida)[0]                    # o bloco misturado: o começo já é do bloco seguinte
    assert np.array_equal(primeiro[:3], bloco_esperado(2)[:3]) and np.array_equal(primeiro[3:], bloco_esperado(0)[3:])


def test_amostras_atrasadas_e_ruido_no_sdo_vao_para_o_cabecalho_com_aviso(ler_adc, placa):
    r, _, saida = capturar(ler_adc, placa, "--blocos", 2, atrasadas_por_bloco=5, preambulo_por_bloco=1)
    assert r.returncode == 0 and "Captura concluída, com avisos" in r.stdout
    h = cab.ler_cabecalho(saida)
    assert h.amostras_atrasadas == 10 and h.quadros_preambulo_ruim == 2 and h.atraso_maximo_ciclos == 77
    assert "fora da grade" in r.stderr and "ruído no SDO" in r.stderr
