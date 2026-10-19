"""Lógica do ``firmware/spi_core.asm``, conferida no mini-simulador ``pru_sim`` (sem BeagleBone, sem ``clpru``).

O assembly da PRU não roda no CI. O simulador executa o fonte de verdade e registra cada palavra que sai pelo MOSI;
estes testes conferem a CONFIGURAÇÃO do ADS8688 (ordem das transações, comandos de faixa por canal) e que o laço de
amostragem continua gravando amostras. Não verificam temporização real nem a sintaxe do ``clpru`` -- compile
(``make`` em ``firmware/``) e teste no BeagleBone depois de mexer no assembly.
"""

from pathlib import Path

import pytest
from pru_sim import (
    INSTRUCOES_IMEM_PRU,
    OFFSET_AUTO_SEQ_MASK,
    OFFSET_RANGE_SEL,
    PRU,
    ModeloADC,
    memoria_configurada,
)

ASM = Path(__file__).resolve().parents[1] / "firmware" / "spi_core.asm"

pytestmark = pytest.mark.skipif(not ASM.exists(), reason="firmware/spi_core.asm não encontrado neste checkout")

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
