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

    if(ctrl->sample_period_ticks < 100) {
        ctrl->sample_period_ticks = 20000;
    }

    // [MULTI-CANAL] Mesmo espírito defensivo do clamp de sample_period_ticks
    // acima: só protege contra RAM compartilhada "fria" (zerada/lixo) antes
    // do ARM configurar de verdade -- em uso normal, ler_adc.c sempre
    // escreve num_canais/comandos_canais válidos antes de sinalizar
    // config_ready=1, e espera_configuracao (spi_core.asm) só avança depois
    // disso. Sem este clamp, um num_canais fora de [1, ADS8688_MAX_CANAIS]
    // faria o índice de canal em spi_core.asm andar fora dos limites do
    // array comandos_canais.
    if (ctrl->num_canais < 1 || ctrl->num_canais > ADS8688_MAX_CANAIS) {
        ctrl->num_canais = 1;
        ctrl->comandos_canais[0] = 0xC4000000u; // canal 1 - padrão histórico (pré multi-canal)
    }

    ctrl->config_ready = 0;

    ler_ads8688_asm(ctrl);
}