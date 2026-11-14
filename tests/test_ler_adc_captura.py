"""A captura do ``firmware/ler_adc.c`` de ponta a ponta, no computador: o ``main`` de verdade contra uma placa falsa.

Até 11/11/2026 o ``main`` do ``ler_adc`` (o handshake com a PRU, o laço de blocos, o cabeçalho final, os códigos de
saída) só rodava na BeagleBone: os testes conferiam funções soltas e a ordem de trechos do fonte. Aqui o programa
inteiro roda contra ``tests/pru_falsa.py`` (um arquivo no lugar do ``/dev/mem`` e uma thread no lugar da PRU), e o
``.bin`` que ele grava é lido pelo ``supraharmonicos.cabecalho``, como na análise.
"""

import os
import re
import signal
import subprocess
import threading
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
CABECALHO = cab.CABECALHO_TAMANHO_V9          # o ler_adc grava a v9: 4096 bytes antes das amostras


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
    dados = np.fromfile(caminho, dtype="<u2", offset=CABECALHO)
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
    assert saida.stat().st_size == CABECALHO + 3 * TAMANHO_BLOCO
    for k, bloco in enumerate(blocos_do_arquivo(saida)):
        assert np.array_equal(bloco, bloco_esperado(k)), f"bloco {k}"

    h = cab.ler_cabecalho(saida)
    assert h.versao_cabecalho == 9 and h.frequencia_hz == 400000 and h.sample_period_ticks == 500
    assert h.lista_canais[:2] == (0, 1) and h.num_canais == 2                 # ordem crescente: a da varredura
    assert h.blocos_gravados == 3 and h.total_amostras_gravadas == 3 * AMOSTRAS_POR_BLOCO
    assert (h.amostras_atrasadas, h.buffers_sobrescritos, h.quadros_preambulo_ruim) == (0, 0, 0)
    assert h.folga_minima_ciclos == 18 and h.ciclos_rebase == 7 and h.versao_protocolo_pru == versao_do_protocolo()
    assert h.faixa_adc_codigo_por_canal[:2] == (2, 0) and h.sonda_id_por_canal[0] == "sct013_100a_sn001"
    assert h.titulo == "título é UTF-8" and h.descricao == "ref: f=1000Hz"
    assert h.versao_firmware == "teste-placa-falsa" and h.modo_spi == 2
    assert h.kernel and h.disco_saida_total_kib and h.disco_saida_livre_fim_kib is not None    # o sistema, de verdade
    assert h.tamanho_cabecalho == CABECALHO and h.primeira_amostra_descartada is False
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


def test_os_contadores_sao_os_dos_blocos_gravados_mesmo_com_o_disco_lento_no_ultimo(ler_adc, placa, tmp_path):
    """A PRU não para no último bloco que o ARM grava: ela segue enchendo o outro buffer e publica os contadores de novo
    na troca seguinte. Até 13/11/2026 o ler_adc os lia depois de GRAVAR cada bloco e outra vez no fim, e um disco que
    demorasse mais que um bloco (~2,5 s na maior taxa) no último punha no cabeçalho os eventos de um bloco que não está
    no arquivo (com dois blocos de demora, também um buffer "sobrescrito" e o código 3). Aqui a saída é um pipe, e o
    leitor só lê o último bloco depois de a PRU falsa publicar o seguinte. (Um pipe não volta ao começo: o cabeçalho
    final não é reescrito, e os contadores são os do resumo, que são os mesmos.)"""
    pipe = tmp_path / "saida.fifo"
    os.mkfifo(pipe)
    pru = placa.pru(atrasadas_por_bloco=5, preambulo_por_bloco=1)

    def leitor_que_trava_no_ultimo_bloco():
        with open(pipe, "rb") as f:
            restam = CABECALHO + TAMANHO_BLOCO
            while restam > 0 and (lido := f.read(min(restam, 1 << 20))):
                restam -= len(lido)
            limite = time.monotonic() + 30
            while pru.blocos_prontos < 3 and time.monotonic() < limite:
                time.sleep(0.005)
            while f.read(1 << 20):
                pass

    leitor = threading.Thread(target=leitor_que_trava_no_ultimo_bloco, daemon=True)
    leitor.start()
    try:
        r = subprocess.run([str(ler_adc), "--blocos", "2", "-o", str(pipe)], env=placa.ambiente, capture_output=True,
                           text=True, timeout=60)
    finally:
        pru.parar()
    leitor.join(timeout=10)
    assert r.returncode == 0 and "Captura concluída, com avisos" in r.stdout, r.stdout + r.stderr
    assert pru.blocos_prontos == 3                  # a troca seguinte saiu enquanto o ARM gravava o último bloco
    assert "10 amostras atrasadas, 0 buffers sobrescritos, 2 quadros com ruído no SDO" in r.stdout, r.stdout
    assert r.stderr.count("Aviso: 5 amostra(s) fora da grade") == 2, r.stderr      # uma vez por bloco gravado


# --------------------------------------------------------------------------------------
# Sinais: Ctrl+C, kill e a queda da conexão
# --------------------------------------------------------------------------------------
def capturar_com_sinal(ler_adc, placa, sinal, *args, depois_de_blocos=2, ignorar_hup=False, **opcoes_da_pru):
    """Manda ``sinal`` ao ler_adc depois de a PRU falsa encher ``depois_de_blocos`` blocos."""
    saida = placa.pasta / "captura.bin"
    pru = placa.pru(**opcoes_da_pru)
    preparar = (lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN)) if ignorar_hup else None
    processo = subprocess.Popen([str(ler_adc), *map(str, args), "-o", str(saida)], env=placa.ambiente,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=preparar)
    try:
        limite = time.monotonic() + 30
        while pru.blocos_prontos < depois_de_blocos and time.monotonic() < limite and processo.poll() is None:
            time.sleep(0.005)
        os.kill(processo.pid, sinal)
        stdout, stderr = processo.communicate(timeout=60)
    finally:
        processo.kill()
        pru.parar()
    return processo.returncode, stdout, stderr, saida


@pytest.mark.parametrize("sinal", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP], ids=["ctrl_c", "kill", "hup"])
def test_captura_cortada_por_um_sinal_fecha_o_arquivo_e_sai_com_o_codigo_5(ler_adc, placa, sinal):
    """Pedidos 200 blocos e parada no começo: o arquivo fecha inteiro (cabeçalho final, blocos completos), mas quem
    chamou tem de saber que a captura NÃO é a pedida. Até 11/11/2026 o código era 0, e o coletar.sh a dava por feita."""
    codigo, stdout, _, saida = capturar_com_sinal(ler_adc, placa, sinal, "--blocos", 200)
    assert codigo == 5, stdout
    assert "Captura interrompida antes do fim" in stdout
    h = cab.ler_cabecalho(saida)
    assert 1 <= h.blocos_gravados < 200          # a PRU já tinha enchido 2; o ARM pode estar 1 atrás
    assert saida.stat().st_size == CABECALHO + h.blocos_gravados * TAMANHO_BLOCO
    assert placa.remoteproc.read_text().startswith("stop")


def test_captura_ate_o_ctrl_c_termina_com_o_codigo_0(ler_adc, placa):
    """--blocos 0 é 'até Ctrl+C': parar por ele é o fim normal."""
    codigo, stdout, _, saida = capturar_com_sinal(ler_adc, placa, signal.SIGINT, "--blocos", 0)
    assert codigo == 0 and "Captura concluída" in stdout
    assert cab.ler_cabecalho(saida).blocos_gravados >= 1


def test_sighup_ignorado_por_quem_chamou_nao_corta_a_captura(ler_adc, placa):
    """O coletar.sh ignora o SIGHUP ('trap "" HUP') para a coleta sobreviver à queda do ssh, e o ler_adc herda isso:
    a captura em curso tem de ir até o fim. Até 11/11/2026 o ler_adc instalava o seu tratador por cima do ignorado, e a
    queda da conexão cortava a captura."""
    codigo, stdout, _, saida = capturar_com_sinal(ler_adc, placa, signal.SIGHUP, "--blocos", 6, ignorar_hup=True)
    assert codigo == 0, stdout
    assert "Captura concluída" in stdout and cab.ler_cabecalho(saida).blocos_gravados == 6


# --------------------------------------------------------------------------------------
# A hora do cabeçalho, a taxa medida e o fechamento do arquivo
# --------------------------------------------------------------------------------------
def test_a_hora_do_cabecalho_e_a_de_quando_a_pru_e_solta(ler_adc, placa):
    """O cabeçalho v8 guarda a fração de segundo do início. Ela só diz algo se o instante for o de quando o ARM solta
    a PRU (config_ready = 1), e não o do começo do programa, antes de a PRU ser reiniciada: aqui a PRU falsa leva
    300 ms para ficar pronta, como um remoteproc lento (o limite de 150 ms dá folga a uma máquina de testes ocupada)."""
    r, pru, saida = capturar(ler_adc, placa, "--blocos", 1, demora_para_ficar_pronta_s=0.3)
    assert r.returncode == 0, r.stdout + r.stderr
    h = cab.ler_cabecalho(saida)
    antes_da_pru_ver = pru.instante_da_configuracao - (h.timestamp_unix + h.timestamp_ns * 1e-9)
    assert 0 <= antes_da_pru_ver < 0.15, antes_da_pru_ver


def test_a_taxa_medida_nao_depende_de_quanto_o_disco_demora(ler_adc, placa, tmp_path):
    """A taxa medida pelo relógio do ARM é (blocos - 1) x amostras por bloco / (tempo entre o 1º e o último ficarem
    prontos). O tempo que o ARM leva para GRAVAR um bloco não entra: aqui a saída é um pipe, e o leitor segura o 1º
    bloco por ~0,15 s (um cartão SD que demorou). A PRU falsa enche um bloco a cada 0,25 s."""
    pipe = tmp_path / "saida.fifo"
    os.mkfifo(pipe)

    def leitor_lento():
        with open(pipe, "rb") as f:
            restam = CABECALHO + TAMANHO_BLOCO
            while restam > 0:                                  # o cabeçalho e o 1º bloco, devagar
                restam -= len(f.read(min(restam, 262144)))
                time.sleep(0.015)
            while f.read(1 << 20):
                pass

    leitor = threading.Thread(target=leitor_lento, daemon=True)
    leitor.start()
    pru = placa.pru(intervalo_s=0.25)
    try:
        r = subprocess.run([str(ler_adc), "--blocos", "3", "-o", str(pipe)], env=placa.ambiente, capture_output=True,
                           text=True, timeout=60)
    finally:
        pru.parar()
    leitor.join(timeout=10)
    medida = float(re.search(r"Taxa medida\s+(\d+) S/s", r.stdout).group(1))
    real = 2 * AMOSTRAS_POR_BLOCO / (pru.instantes_pronto[2] - pru.instantes_pronto[0])
    assert medida == pytest.approx(real, rel=0.10), (medida, real)      # com o relógio de depois da gravação: +37 %


def test_erro_ao_fechar_o_arquivo_nao_passa_em_silencio(ler_adc, placa):
    """Num disco cheio (/dev/full) nada é gravado. Com o cabeçalho de 1024 bytes (até a v8), ele ficava no buffer do
    stdio até o fclose, que não era conferido: a captura 'terminava' com um arquivo vazio e sem nenhum erro. Com o de
    4096 bytes a escrita já falha no cabeçalho; nos dois casos, é erro (código 1)."""
    if not os.path.exists("/dev/full"):
        pytest.skip("sem /dev/full")
    pru = placa.pru(max_blocos=0)                              # nenhum bloco: só o cabeçalho é escrito
    processo = subprocess.Popen([str(ler_adc), "--blocos", "0", "-o", "/dev/full"], env=placa.ambiente,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        limite = time.monotonic() + 30
        while not pru.configuracao and time.monotonic() < limite:
            time.sleep(0.005)
        time.sleep(0.1)
        os.kill(processo.pid, signal.SIGINT)
        _, stderr = processo.communicate(timeout=60)
    finally:
        processo.kill()
        pru.parar()
    assert processo.returncode == 1, stderr
    assert "não deu para terminar de gravar" in stderr or "não deu para gravar o cabeçalho" in stderr, stderr


# --------------------------------------------------------------------------------------
# [11/11/2026] Cabeçalho v9: a extensão que o ler_adc grava
# --------------------------------------------------------------------------------------
def test_v9_o_crc_das_amostras_a_identificacao_e_o_ganho_declarado(ler_adc, placa):
    """O ler_adc de verdade grava a extensão da v9: o CRC-32 das amostras (conferido pelo Python contra o arquivo), o
    identificador (um por captura), a máquina, a linha de comando, o ganho e o fim da captura."""
    r, pru, saida = capturar(ler_adc, placa, 400000, 1, "--blocos", 2, "--ganho", "1:19.357")
    assert r.returncode == 0 and r.stderr == "", r.stdout + r.stderr
    h = cab.ler_cabecalho(saida)
    assert h.crc32_valido and cab.conferir_crc_das_amostras(saida, h) is True
    assert h.hostname == os.uname().nodename[:31] and len(h.id_captura) == 32 and int(h.id_captura, 16) != 0
    assert h.linha_de_comando == f"400000 1 --blocos 2 --ganho 1:19.357 -o {saida}"
    assert h.ganho_por_canal == (19.357,) and "ganho 19.357" in r.stdout
    inicio = h.timestamp_unix + h.timestamp_ns * 1e-9
    fim = h.timestamp_fim_unix + h.timestamp_fim_ns * 1e-9
    assert 0 < fim - inicio < 10 and h.duracao_monotonica_s == pytest.approx(fim - inicio, abs=0.05)
    assert h.pior_bloco_ms is not None and h.pior_bloco_ms < 5000
    # um bit trocado numa amostra, depois da captura: o cabeçalho continua válido, e o CRC das amostras acusa
    bruto = bytearray(saida.read_bytes())
    bruto[CABECALHO + 123457] ^= 0x10
    saida.write_bytes(bytes(bruto))
    assert cab.ler_cabecalho(saida).crc32_valido and cab.conferir_crc_das_amostras(saida, h) is False
    # outra captura, outro identificador
    r2, _, saida2 = capturar(ler_adc, placa, 400000, 1, "--blocos", 1)
    assert cab.ler_cabecalho(saida2).id_captura != h.id_captura


@pytest.mark.parametrize("canais", ["1", "0,1,2", "0,1,2,3,4,5,6"])
def test_v9_o_sinal_de_cada_canal_e_o_das_amostras_do_arquivo(ler_adc, placa, canais):
    """Mínimo, máximo, média, desvio e saturadas de cada canal, medidos pelo ler_adc em todas as amostras. O bloco
    (1.048.576 amostras) não tem um número inteiro de varreduras com 3 ou 7 canais: o canal de cada amostra é o da
    posição dela no ARQUIVO, e o numpy sobre o arquivo desintercalado tem de dar os mesmos números."""
    r, _, saida = capturar(ler_adc, placa, 100000, canais, "--blocos", 3)
    assert r.returncode == 0, r.stdout + r.stderr
    h = cab.ler_cabecalho(saida)
    k = h.num_canais
    dados = np.fromfile(saida, dtype="<u2", offset=CABECALHO)
    for i in range(k):
        canal = dados[i::k].astype(np.float64)
        assert h.codigo_minimo_por_canal[i] == canal.min() and h.codigo_maximo_por_canal[i] == canal.max()
        assert h.media_codigos_por_canal[i] == pytest.approx(canal.mean(), abs=1e-6)
        assert h.desvio_codigos_por_canal[i] == pytest.approx(canal.std(), rel=1e-9)
    assert h.amostras_saturadas_por_canal == (0,) * k and "SATUROU" not in r.stderr
    assert r.stdout.count(" V no pino (") == k                 # uma linha de sinal por canal no resumo


def test_v9_a_saturacao_aparece_no_fim_da_captura_e_no_cabecalho(ler_adc, placa):
    """Uma amostra no fundo de escala é um sinal cortado. O ler_adc conta as de cada canal em todas as amostras, avisa
    no fim da captura (e não só na análise) e grava a contagem no cabeçalho."""
    r, _, saida = capturar(ler_adc, placa, 400000, "0,1", "--blocos", 1, "--faixa-adc", "0:5.12", satura=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "o canal 0 SATUROU" in r.stderr and "Use uma faixa maior" in r.stderr
    assert "o canal 1 SATUROU" in r.stderr and "É a maior faixa do ADC" in r.stderr
    h = cab.ler_cabecalho(saida)
    dados = np.fromfile(saida, dtype="<u2", offset=CABECALHO)
    esperadas = tuple(int(np.count_nonzero((dados[i::2] == 0) | (dados[i::2] == 65535))) for i in range(2))
    assert h.amostras_saturadas_por_canal == esperadas and sum(esperadas) > 0
