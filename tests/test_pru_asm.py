"""Lógica do ``firmware/spi_core.asm``, conferida no mini-simulador ``pru_sim`` (sem BeagleBone, sem ``clpru``).

O assembly da PRU não roda no CI. O simulador executa o fonte de verdade e registra cada palavra que sai pelo MOSI;
estes testes conferem a CONFIGURAÇÃO do ADS8688 (ordem das transações, comandos de faixa por canal), que o laço de
amostragem grava amostras, a GRADE DE TEMPO das amostras (desde 22/10/2026, EXATA: toda descida do CS sai um
período, ao ciclo, depois da anterior, com troca de buffer, rebase do contador, latências de memória hipotéticas e
escritas na DDR que demoram) e os contadores de integridade e de tempo que a PRU publica.
Não verificam a temporização real (as latências daqui são hipóteses) nem a sintaxe do ``clpru`` -- compile (``make``
em ``firmware/``) e teste no BeagleBone depois de mexer no assembly.
"""

import random
from pathlib import Path

import pytest
from pru_sim import (
    ENDERECO_CONTADOR_CICLOS,
    ENDERECO_SHARED_RAM,
    INSTRUCOES_IMEM_PRU,
    MASCARA32,
    OFFSET_AMOSTRAS_ATRASADAS,
    OFFSET_ATRASO_CS_SETUP,
    OFFSET_ATRASO_MAXIMO,
    OFFSET_AUTO_SEQ_MASK,
    OFFSET_BUFFER_0_READY,
    OFFSET_BUFFER_1_READY,
    OFFSET_BUFFERS_SOBRESCRITOS,
    OFFSET_CICLOS_REBASE,
    OFFSET_FOLGA_MINIMA,
    OFFSET_QUADROS_PREAMBULO_RUIM,
    OFFSET_RANGE_SEL,
    OFFSET_VERSAO_PROTOCOLO,
    PRU,
    Latencias,
    ModeloADC,
    memoria_configurada,
)

ASM = Path(__file__).resolve().parents[1] / "firmware" / "spi_core.asm"


CMD_AUTO_SEQ_EN = 0x0300          # escrita no registrador 01h (AUTO_SEQ_EN)
CMD_AUTO_RST = 0xA000             # comando AUTO_RST (varredura automática)
CMD_RANGE_SEL_CANAL0 = 0x0B00     # escrita no registrador 05h (RANGE_SEL0); canal N soma N * 0x200


def comando_range(canal: int, codigo: int) -> int:
    return CMD_RANGE_SEL_CANAL0 + canal * 0x200 + codigo


def configuracao(mascara: int, range_sel: int | None = 0, max_transacoes: int = 20) -> list[int]:
    """Palavras de comando (16 bits) das transações de CONFIGURAÇÃO: tudo até o AUTO_RST, inclusive."""
    pru = PRU(ASM, memoria_configurada(mascara, range_sel))
    pru.executar(max_transacoes=max_transacoes)
    palavras = [t.palavra16 for t in pru.transacoes]
    assert CMD_AUTO_RST in palavras, "o assembly não chegou a enviar o AUTO_RST"
    return palavras[: palavras.index(CMD_AUTO_RST) + 1]


def nibbles(**codigos: int) -> int:
    """nibbles(c0=2, c3=1) -> range_sel com o código 2 no canal 0 e 1 no canal 3."""
    valor = 0
    for nome, codigo in codigos.items():
        valor |= codigo << (4 * int(nome[1:]))
    return valor


def test_offsets_usados_pelo_simulador_batem_com_o_assembly():
    """O assembly lê a máscara e o range_sel por offset fixo; se alguém mover um campo da struct, falha aqui."""
    texto = ASM.read_text(encoding="utf-8")
    assert f"LBBO &r8, r14, {OFFSET_AUTO_SEQ_MASK}, 4" in texto
    assert f"LBBO &r9, r14, {OFFSET_RANGE_SEL}, 4" in texto


def test_sem_faixa_pedida_todos_os_canais_ficam_na_faixa_padrao():
    """range_sel = 0 (compatível com o comportamento histórico): AUTO_SEQ_EN, RANGE_SEL = 0 de cada canal, AUTO_RST."""
    assert configuracao(0b00000011, 0) == [
        CMD_AUTO_SEQ_EN | 0b11, comando_range(0, 0), comando_range(1, 0), CMD_AUTO_RST]


def test_faixa_por_canal_vai_para_o_registrador_do_proprio_canal():
    palavras = configuracao(0b00000011, nibbles(c0=0, c1=2))
    assert palavras == [CMD_AUTO_SEQ_EN | 0b11, comando_range(0, 0), comando_range(1, 2), CMD_AUTO_RST]


def test_canal_7_usa_o_ultimo_nibble_e_o_ultimo_registrador():
    palavras = configuracao(0b10000001, nibbles(c0=1, c7=2))
    assert palavras == [CMD_AUTO_SEQ_EN | 0b10000001, comando_range(0, 1), comando_range(7, 2), CMD_AUTO_RST]
    assert comando_range(7, 2) == 0x1902          # registrador 0Ch: (0x0C << 9) | 0x100 | 2


@pytest.mark.parametrize("mascara", [0b00000001, 0b00000010, 0b01010101, 0b11111111, 0b10000000])
def test_um_comando_de_faixa_por_canal_habilitado_em_ordem_crescente(mascara):
    canais = [c for c in range(8) if mascara >> c & 1]
    codigos = {f"c{c}": 1 + (c % 2) for c in canais}              # 1 e 2 alternados: nenhum é o padrão
    palavras = configuracao(mascara, nibbles(**codigos))
    esperado = [CMD_AUTO_SEQ_EN | mascara] + [comando_range(c, 1 + (c % 2)) for c in canais] + [CMD_AUTO_RST]
    assert palavras == esperado


def test_nibble_de_canal_desabilitado_e_ignorado():
    """Só os canais da máscara são escritos: o código do canal 5 (desabilitado) não gera transação."""
    palavras = configuracao(0b00000011, nibbles(c0=2, c1=1, c5=2))
    assert palavras == [CMD_AUTO_SEQ_EN | 0b11, comando_range(0, 2), comando_range(1, 1), CMD_AUTO_RST]


def test_o_codigo_padrao_tambem_e_escrito_porque_o_registrador_do_adc_persiste():
    """O ADS8688 não reinicia quando a PRU reinicia: sem escrever o 0, a faixa da captura anterior ficaria valendo
    e o cabeçalho (que diz 'faixa 0') mentiria."""
    palavras = configuracao(0b00000010, nibbles(c1=0))
    assert comando_range(1, 0) in palavras


@pytest.mark.parametrize("bits", range(0, 4))
def test_comandos_de_configuracao_tem_24_ciclos_de_sclk_e_o_auto_rst_32(bits):
    pru = PRU(ASM, memoria_configurada(0b00000011, nibbles(c0=bits % 3, c1=(bits + 1) % 3)))
    pru.executar(max_transacoes=8)
    por_palavra = {t.palavra16: t.ciclos_sclk for t in pru.transacoes}
    for palavra, ciclos in por_palavra.items():
        if palavra == CMD_AUTO_RST:
            assert ciclos == 32
        elif palavra & 0x0100:                                       # escrita em registrador de programa
            assert ciclos == 24, hex(palavra)


def test_so_o_nibble_de_cada_canal_vale_nao_o_registrador_inteiro():
    """Códigos com bits acima do nibble do canal vizinho não vazam: canal 0 = 0x2, canal 1 = 0x1."""
    palavras = configuracao(0b11, 0x12)
    assert palavras[1] == comando_range(0, 2) and palavras[2] == comando_range(1, 1)


def test_depois_da_configuracao_o_laco_principal_grava_amostras_na_ddr():
    pru = PRU(ASM, memoria_configurada(0b00000011, nibbles(c0=0, c1=2)), ModeloADC(0xABCD))
    pru.executar(max_transacoes=16)
    assert pru.escritas_ddr, "nenhuma amostra gravada na DDR"
    assert all(valor == 0xABCD for _, valor in pru.escritas_ddr[:8])
    enderecos = [e for e, _ in pru.escritas_ddr[:8]]
    assert enderecos == [0x9F000000 + 2 * i for i in range(8)]       # amostras de 16 bits, consecutivas


def test_cabe_na_imem_da_pru_com_folga_para_o_codigo_c():
    pru = PRU(ASM, memoria_configurada(0b1))
    assert pru.total_instrucoes <= INSTRUCOES_IMEM_PRU - 150, (
        f"{pru.total_instrucoes} instruções no .asm: sobram poucas das {INSTRUCOES_IMEM_PRU} da IMEM para o main() em C"
    )


def test_nenhum_desvio_condicional_passa_do_alcance_do_qb():
    """QB* só alcança +-511 instruções; mais que isso exige JMP (o clpru recusa o resto na montagem)."""
    assert PRU(ASM, memoria_configurada(0b1)).violacoes_desvio == []


# --------------------------------------------------------------------------------------
# Laço principal: grade de tempo das amostras e detectores de integridade (revisão out/2026)
# --------------------------------------------------------------------------------------
CONFIG_1CANAL = 3               # transações de configuração com 1 canal: AUTO_SEQ_EN, RANGE_SEL e AUTO_RST
PERIODO = 2000                  # 100 kS/s a 200 MHz


def pru_laco(buffer: int = 4, periodo: int = PERIODO, adc: ModeloADC | None = None, atrasos=None,
             latencias: Latencias | None = None) -> PRU:
    """PRU com 1 canal e buffers de ``buffer`` amostras (o real tem 1.048.576: inviável de simular)."""
    mem = memoria_configurada(0b10, 0, periodo_ticks=periodo)
    if atrasos is not None:
        for k, valor in enumerate(atrasos):
            mem[ENDERECO_SHARED_RAM + OFFSET_ATRASO_CS_SETUP + 4 * k] = valor
    pru = PRU(ASM, mem, adc, latencias)
    for ins in pru.instrucoes:
        if ins.mnemonico == "LDI" and ins.operandos[0].lower() == "r21.w0":
            ins.operandos[1] = str(buffer & 0xFFFF)
        elif ins.mnemonico == "LDI" and ins.operandos[0].lower() == "r21.w2":
            ins.operandos[1] = str(buffer >> 16)
    return pru


def intervalos(pru: PRU) -> list[int]:
    instantes = pru.instantes_cs[CONFIG_1CANAL:]
    return [b - a for a, b in zip(instantes, instantes[1:])]


def contador(pru: PRU, offset: int) -> int:
    return pru.ler_mem(ENDERECO_SHARED_RAM + offset, 4)


def test_grade_de_tempo_continua_na_troca_de_buffer_e_no_comeco():
    """Antes, o contador de ciclos era zerado DEPOIS da transação da última amostra de cada buffer: a 1ª do buffer
    seguinte saía ~1400 ciclos atrasada (+0,697 amostra a 100 kS/s, medido nas 57 trocas da captura T7c). E o
    zero antes da configuração fazia as primeiras amostras de toda captura saírem mais rápido que o pedido."""
    pru = pru_laco(buffer=4)
    pru.executar(max_transacoes=CONFIG_1CANAL + 14)          # 3 trocas de buffer no meio
    assert set(intervalos(pru)) == {PERIODO}, intervalos(pru)   # exato: até 21/10/2026, 0 a 2 ciclos de jitter


def test_rebase_do_contador_mantem_a_grade_e_evita_a_trava_em_2_elevado_a_32():
    """O contador da PRU trava em 0xFFFFFFFF (~21,5 s). Simula uma captura já rodando há ~10,7 s: o rebase (o
    contador zerado e o alvo recuado o mesmo tanto) acontece sem mexer no intervalo entre amostras.

    Com a escrita que ZERA o contador (como na BeagleBone), a versão que escrevia CYCLE - 2^31 falhava aqui: a grade
    atrasava ~1 quadro mais o que já tinha passado de 2^31, como os degraus de 5 a 13 µs a cada 10,74 s medidos na
    varredura T7e de 21/10/2026."""
    pru = pru_laco(buffer=1 << 20)
    pru.executar(max_transacoes=CONFIG_1CANAL + 3)
    salto = (1 << 31) - 5_000                                 # o contador e o alvo andam juntos, como no tempo real
    pru.base_contador -= salto
    pru.regs[17] = (pru.regs[17] + salto) & MASCARA32
    pru.executar(max_transacoes=CONFIG_1CANAL + 12)
    assert pru.ler_mem(ENDERECO_CONTADOR_CICLOS, 4) < 1 << 31, "o rebase não aconteceu"
    assert set(intervalos(pru)) == {PERIODO}, intervalos(pru)


def test_taxa_acima_do_que_o_laco_alcanca_conta_amostras_atrasadas_e_nao_trava():
    pru = pru_laco(buffer=4, periodo=500)                     # 400 kS/s: o quadro leva ~600 ciclos
    pru.executar(max_transacoes=CONFIG_1CANAL + 9)
    assert contador(pru, OFFSET_AMOSTRAS_ATRASADAS) == 7      # publicado na troca depois da 8ª; a 1ª sai na hora
    assert max(intervalos(pru)) < 700                         # sai o mais rápido que dá, sem esperas absurdas
    # o pior atraso, em ciclos, também é publicado: cresce até passar de 1 período, quando a grade recomeça
    assert 500 < contador(pru, OFFSET_ATRASO_MAXIMO) < 2 * 500


def test_amostra_atrasada_por_pouco_volta_para_a_grade():
    """Um atraso menor que 1 período (ex.: uma escrita na DDR que demorou) não desloca as amostras seguintes. Com o
    quadro de 1395 ciclos das esperas 200/100/100, perder 1000 ciclos num período de 2000 atrasa a amostra (com o
    padrão de 3/1/3, o quadro de 609 deixaria folga para absorvê-los)."""
    pru = pru_laco(buffer=1 << 20, atrasos=(200, 100, 100))
    pru.executar(max_transacoes=CONFIG_1CANAL + 3)
    pru.base_contador -= 1_000                                # a PRU "perdeu" 1000 ciclos (meio período)
    pru.executar(max_transacoes=CONFIG_1CANAL + 8)
    assert contador(pru, OFFSET_AMOSTRAS_ATRASADAS) == 0      # só é publicado na troca de buffer...
    assert pru.regs[6] == 1                                   # ...mas foi contada
    d = intervalos(pru)
    # a atrasada sai assim que a transação anterior acaba; a seguinte já cai no ponto da grade de antes
    assert d[2] < PERIODO - 500 and d[2] + d[3] == 2 * PERIODO - 1_000
    assert set(d[4:]) == {PERIODO}, d


def test_buffer_que_o_arm_nao_esvaziou_conta_como_sobrescrito():
    """Sem ninguém limpando buffer_N_ready (um ARM que parou), cada troca depois da 1ª reescreve dados não gravados."""
    pru = pru_laco(buffer=4)
    pru.executar(max_transacoes=CONFIG_1CANAL + 13)           # 3 trocas: 0->1 (o 1 nunca foi cheio), 1->0, 0->1
    assert contador(pru, OFFSET_BUFFERS_SOBRESCRITOS) == 2


def test_com_o_arm_esvaziando_os_buffers_nao_ha_sobrescrita():
    pru = pru_laco(buffer=4)
    for n in range(CONFIG_1CANAL + 1, CONFIG_1CANAL + 14):
        pru.executar(max_transacoes=n)
        for offset in (OFFSET_BUFFER_0_READY, OFFSET_BUFFER_1_READY):     # o ARM copiou e liberou
            pru.escrever_mem(ENDERECO_SHARED_RAM + offset, 0, 4)
    assert contador(pru, OFFSET_BUFFERS_SOBRESCRITOS) == 0 and contador(pru, OFFSET_AMOSTRAS_ATRASADAS) == 0


def test_preambulo_diferente_de_zero_e_contado():
    """O SDO fica em 0 nas 15 primeiras bordas (datasheet 8.4.1.1.4); um 1 ali é ruído na linha."""
    adc = ModeloADC(0x1234, ruido_no_quadro={CONFIG_1CANAL + 1, CONFIG_1CANAL + 3})    # 2ª e 4ª amostras
    pru = pru_laco(buffer=4, adc=adc)
    pru.executar(max_transacoes=CONFIG_1CANAL + 5)
    assert contador(pru, OFFSET_QUADROS_PREAMBULO_RUIM) == 2
    assert all(v == 0x1234 for _, v in pru.escritas_ddr[:4])  # o dado é gravado do mesmo jeito (só é contado)


def duracao_transacao(pru: PRU) -> int:
    """Ciclos com o CS baixo numa transação do laço principal."""
    return pru.instantes_cs_sobe[CONFIG_1CANAL + 1] - pru.instantes_cs[CONFIG_1CANAL + 1]


def test_atrasos_de_cs_padrao_sao_o_minimo_do_datasheet():
    """0 no campo = o padrão, 3/1/3 desde 21/10/2026 (30/10/30 ns): CS baixo de 566 + 2·(3+1) = 574 ciclos."""
    for atrasos in (None, (0, 0, 0), (3, 1, 3)):
        pru = pru_laco(atrasos=atrasos)
        pru.executar(max_transacoes=CONFIG_1CANAL + 3)
        assert duracao_transacao(pru) == 574, atrasos
        assert set(intervalos(pru)) == {PERIODO}


def test_atrasos_de_cs_antigos_mantem_a_transacao_validada_em_hardware():
    """200/100/100, o padrão até 21/10/2026: a transação tem a MESMA duração do firmware validado em bancada."""
    pru = pru_laco(atrasos=(200, 100, 100))
    pru.executar(max_transacoes=CONFIG_1CANAL + 3)
    assert duracao_transacao(pru) == 1166                     # o mesmo valor do spi_core.asm anterior (5,83 µs)


def test_atrasos_de_cs_configuraveis_encurtam_a_transacao():
    pru = pru_laco(atrasos=(20, 10, 10))
    pru.executar(max_transacoes=CONFIG_1CANAL + 3)
    assert duracao_transacao(pru) == 1166 - 2 * (180 + 90)    # setup e hold ficam com o CS baixo (2 ciclos/iteração)
    assert set(intervalos(pru)) == {PERIODO}


# --------------------------------------------------------------------------------------
# Grade exata (22/10/2026): espera de precisão, folga publicada e rebase autocalibrado
# --------------------------------------------------------------------------------------
PERIODO_312K = 640              # 312,5 kS/s, a taxa padrão

# Hipóteses de latência da PRU de verdade (não medidas): o LBBO lê o contador em algum ciclo dele, o zero do
# contador vale algum tempo depois do SBBO começar. A grade não pode depender de nenhuma delas.
LATENCIAS = [
    Latencias(),
    Latencias(leitura=2, amostra_leitura=1, escrita=1, efeito_escrita=2),
    Latencias(leitura=3, amostra_leitura=3, escrita=2, efeito_escrita=0),
    Latencias(leitura=1, amostra_leitura=0, escrita=3, efeito_escrita=4),
]


def instantes_no_laco(pru: PRU) -> list[int]:
    return pru.instantes_cs[CONFIG_1CANAL:]


@pytest.mark.parametrize("lat", LATENCIAS, ids=lambda lat: f"L{lat.leitura}a{lat.amostra_leitura}E{lat.escrita}e{lat.efeito_escrita}")
def test_grade_exata_com_latencias_de_memoria_troca_e_rebase(lat):
    """Toda descida do CS, um período depois da anterior, AO CICLO: na troca de buffer (a cada 4 amostras aqui) e
    no rebase do contador -- este com a calibração medida pela própria PRU, qualquer que seja a latência."""
    pru = pru_laco(buffer=4, periodo=PERIODO_312K, latencias=lat)
    pru.executar(max_transacoes=CONFIG_1CANAL + 6)
    salto = (1 << 31) - 3_000                                 # pula para perto de 2^31: o rebase vem em ~5 amostras
    pru.base_contador -= salto
    pru.regs[17] = (pru.regs[17] + salto) & MASCARA32
    pru.executar(max_transacoes=CONFIG_1CANAL + 20)
    assert pru.ler_mem(ENDERECO_CONTADOR_CICLOS, 4) < 1 << 31, "o rebase não aconteceu"
    assert set(intervalos(pru)) == {PERIODO_312K}, intervalos(pru)
    assert contador(pru, OFFSET_AMOSTRAS_ATRASADAS) == 0
    assert contador(pru, OFFSET_CICLOS_REBASE) == 2 + lat.leitura + lat.escrita   # LBBO + SBBO, medidos pela PRU


def test_rebase_com_a_constante_antiga_deslocaria_a_grade():
    """Controle do teste acima: com latências, o recuo fixo de antes (v + 2) erra a grade em alguns ciclos."""
    lat = Latencias(leitura=2, amostra_leitura=1, escrita=1, efeito_escrita=2)
    pru = pru_laco(buffer=1 << 20, periodo=PERIODO_312K, latencias=lat)
    pru.executar(max_transacoes=CONFIG_1CANAL + 3)
    pru.regs[29] = 1                                          # finge a calibração de antes (2 = recuo v + 2, com u = 1)
    salto = (1 << 31) - 3_000
    pru.base_contador -= salto
    pru.regs[17] = (pru.regs[17] + salto) & MASCARA32
    pru.executar(max_transacoes=CONFIG_1CANAL + 12)
    assert set(intervalos(pru)) != {PERIODO_312K}


def test_escrita_na_ddr_que_demora_nao_desloca_a_amostra():
    """Uma escrita na DDR esperando o barramento (o ARM copiando um buffer) come a folga, mas a espera fina a
    absorve: o CS desce no mesmo ciclo. Antes, ela só mudava qual volta da sondagem pegava o instante."""
    sorteio = random.Random(22102026)
    pru = pru_laco(buffer=4, periodo=PERIODO_312K, latencias=Latencias(ddr=lambda: sorteio.randint(0, 12)))
    pru.executar(max_transacoes=CONFIG_1CANAL + 40)
    assert set(intervalos(pru)) == {PERIODO_312K}
    assert contador(pru, OFFSET_AMOSTRAS_ATRASADAS) == 0 and contador(pru, OFFSET_FOLGA_MINIMA) > 0


def test_a_folga_publicada_e_a_margem_de_verdade():
    """Folga F a 640 ciclos: com o período F ciclos mais curto ainda não há amostra atrasada (folga 0); 1 ciclo a
    menos, há. É o que torna a folga do cabeçalho um teto medido, e não uma estimativa."""
    pru = pru_laco(buffer=4, periodo=PERIODO_312K)
    pru.executar(max_transacoes=CONFIG_1CANAL + 14)
    folga = contador(pru, OFFSET_FOLGA_MINIMA)
    assert 0 < folga < 60
    no_limite = pru_laco(buffer=4, periodo=PERIODO_312K - folga)
    no_limite.executar(max_transacoes=CONFIG_1CANAL + 14)
    assert contador(no_limite, OFFSET_AMOSTRAS_ATRASADAS) == 0 and contador(no_limite, OFFSET_FOLGA_MINIMA) == 0
    assert set(intervalos(no_limite)) == {PERIODO_312K - folga}
    alem = pru_laco(buffer=4, periodo=PERIODO_312K - folga - 1)
    alem.executar(max_transacoes=CONFIG_1CANAL + 14)
    assert contador(alem, OFFSET_AMOSTRAS_ATRASADAS) > 0


def test_a_troca_de_buffer_e_o_que_mais_gasta_folga():
    """Sem troca, sobra mais: a menor folga de uma captura real (buffer de 1.048.576) vem da troca de buffer."""
    sem_troca = pru_laco(buffer=1 << 20, periodo=PERIODO_312K)
    sem_troca.executar(max_transacoes=CONFIG_1CANAL + 6)
    com_troca = pru_laco(buffer=4, periodo=PERIODO_312K)
    com_troca.executar(max_transacoes=CONFIG_1CANAL + 14)
    assert com_troca.regs[12] < sem_troca.regs[12]


def test_versao_do_protocolo_e_publicada_antes_da_primeira_amostra():
    pru = pru_laco()
    pru.executar(max_transacoes=CONFIG_1CANAL + 1)
    assert contador(pru, OFFSET_VERSAO_PROTOCOLO) == 2 and contador(pru, OFFSET_CICLOS_REBASE) == 2


def test_auto_rst_sai_do_mesmo_corpo_da_configuracao_e_libera_a_imem():
    """O AUTO_RST era uma cópia inteira da transação (624 instruções); agora é o estágio 9 do laço de configuração."""
    pru = PRU(ASM, memoria_configurada(0b1))
    assert pru.total_instrucoes < 1500
    texto = ASM.read_text(encoding="utf-8")
    assert texto.count("LDI r7, 0xA000") == 1 and "0xA000" not in texto.replace("LDI r7, 0xA000", "").split("cfg_auto_rst")[0]
