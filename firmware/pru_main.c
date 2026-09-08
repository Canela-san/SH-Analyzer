#include <stdint.h>
#include "memoria_pru.h"

struct resource_table {
    uint32_t ver; uint32_t num; uint32_t reserved[2];
};
#pragma DATA_SECTION(resource_table, ".resource_table")
#pragma RETAIN(resource_table)
struct resource_table resource_table = { 1, 0, {0, 0} };

volatile struct shared_control *ctrl = (volatile struct shared_control *)PRU_SHARED_RAM_PRU;

volatile uint32_t *pru_ctrl = (uint32_t *)0x22000;
volatile uint32_t *pru_cycle = (uint32_t *)0x2200C;

extern void ler_ads8688_asm(volatile struct shared_control *ctrl);

void main(void) {
    volatile uint32_t *pru_syscfg = (uint32_t *)0x26004;
    *pru_syscfg &= ~(1 << 4);

    *pru_ctrl |= (1 << 3);
    *pru_cycle = 0;

    if (ctrl->sample_period_ticks < 100) {
        ctrl->sample_period_ticks = 20000;
    }

    // [MODO AUTOMÁTICO] Mesmo espírito defensivo do clamp acima: só protege
    // contra RAM compartilhada "fria" (zerada/lixo) antes do ARM configurar
    // de verdade -- em uso normal, ler_adc.c sempre escreve auto_seq_mask
    // (com pelo menos 1 bit ligado) antes de sinalizar config_ready=1, e
    // espera_configuracao (spi_core.asm) só avança depois disso.
    //
    // Dois cuidados, substituindo o antigo clamp de num_canais/
    // comandos_canais[0] do modo manual multi-canal:
    //   1) Bits acima do bit 7 não correspondem a nenhum canal físico do
    //      ADS8688 (só há 8 -- canais 0-7) e contaminariam os bits de
    //      endereço/R-W do comando de escrita do registrador AUTO_SEQ_EN
    //      montado em spi_core.asm. Mascarado para 8 bits por segurança.
    //   2) auto_seq_mask == 0 (nenhum canal habilitado) não tem sentido
    //      físico -- a varredura automática não teria o que varrer. Cai no
    //      canal 1 (bit 1 -> 0x02), o mesmo padrão histórico usado antes da
    //      captura multi-canal (era o único canal desta placa com sinal de
    //      verdade conectado -- ver cabeçalho de spi_core.asm).
    ctrl->auto_seq_mask &= 0xFFu;
    if (ctrl->auto_seq_mask == 0) {
        ctrl->auto_seq_mask = 0x02u; // canal 1 - padrão histórico
    }

    ctrl->config_ready = 0;

    ler_ads8688_asm(ctrl);
}
