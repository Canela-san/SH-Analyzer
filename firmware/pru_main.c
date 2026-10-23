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

    // [INÍCIO SEM CORRIDA, 23/10/2026] config_ready = 0 primeiro (uma RAM compartilhada com lixo, ou com o 1 da
    // captura anterior, não pode soltar a captura: é o caso do 'setup.sh', que liga a PRU sem nenhum ler_adc), e só
    // depois o aviso de "pronta" (versao_protocolo_pru = 0): o ler_adc espera esse 0 para escrever a configuração e o
    // config_ready = 1, que então nunca é apagado por aqui. Até 23/10/2026 o ARM esperava 50 ms fixos depois do start.
    //
    // Os ajustes de sample_period_ticks (< 100 -> 20000) e de auto_seq_mask (8 bits, 0 -> canal 1) que ficavam aqui
    // saíram: rodavam ANTES de o ARM escrever esses campos, que ele sempre reescreve com valores válidos, e por isso
    // nunca tinham efeito.
    ctrl->config_ready = 0;
    ctrl->versao_protocolo_pru = 0;

    ler_ads8688_asm(ctrl);
}
