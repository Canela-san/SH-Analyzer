#include <stdint.h>
#include "memoria_pru.h"

// Mantém a resource table vazia
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

    *pru_ctrl |= (1 << 3); // Habilita o Cycle Counter
    *pru_cycle = 0;        

    if(ctrl->sample_period_ticks < 100) {
        ctrl->sample_period_ticks = 20000; 
    }

    // ==========================================================================
    // NOVO: força config_ready = 0 a cada boot da PRU.
    // ==========================================================================
    // A memória compartilhada da PRU costuma reter o conteúdo antigo entre um
    // "stop" e um "start" do firmware (não é zerada automaticamente). Sem esta
    // linha, se um run anterior já tivesse deixado config_ready = 1, a rotina
    // em assembly pularia direto para ler buffer_0_addr/buffer_1_addr - que
    // ainda não foram (re)configurados pelo ler_adc.c desta nova execução -
    // reintroduzindo a condição de corrida que fazia a PRU escrever no
    // endereço físico errado. Zerando aqui, a PRU SEMPRE espera um sinal novo
    // e explícito do ARM (ver ler_adc.c) antes de iniciar a aquisição.
    ctrl->config_ready = 0;

    // Chama o núcleo Assembly (nunca retorna)
    ler_ads8688_asm(ctrl);
}
