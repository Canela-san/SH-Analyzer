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

    // Chama o núcleo Assembly (nunca retorna)
    ler_ads8688_asm(ctrl);
}