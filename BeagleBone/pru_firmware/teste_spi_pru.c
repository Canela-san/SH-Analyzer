#include <stdint.h>

struct resource_table {
    uint32_t ver;
    uint32_t num;
    uint32_t reserved[2];
};
#pragma DATA_SECTION(resource_table, ".resource_table")
#pragma RETAIN(resource_table)
struct resource_table resource_table = { 1, 0, {0, 0} };

// Fast I/O
volatile register uint32_t __R30; 
volatile register uint32_t __R31; 

#define SCLK_BIT (1 << 0) 
#define MOSI_BIT (1 << 1) 
#define MISO_BIT (1 << 2) 
#define CS_BIT   (1 << 3) 

// =====================================================================
// ARQUITETURA EXPANDIDA DA MEMÓRIA COMPARTILHADA
// =====================================================================
#define BUFFER_SIZE 2000 

struct shared_memory {
    volatile uint32_t sample_period_ticks; // NOVO: Controle Dinâmico da Frequência
    volatile uint32_t write_index;
    volatile uint32_t data[BUFFER_SIZE];
};

#define PRU_SHARED_RAM 0x00010000
volatile struct shared_memory *shared = (volatile struct shared_memory *)PRU_SHARED_RAM;

volatile uint32_t *pru_ctrl  = (uint32_t *)0x22000;
volatile uint32_t *pru_cycle = (uint32_t *)0x2200C;

void main(void) {
    volatile uint32_t *pru_syscfg = (uint32_t *)0x26004;
    *pru_syscfg &= ~(1 << 4);

    *pru_ctrl |= (1 << 3); 
    *pru_cycle = 0;        

    __R30 |= CS_BIT;
    __R30 &= ~SCLK_BIT;

    // Frequência de repouso segura inicial (ex: 10 kHz = 20.000 ticks)
    // Evita que a PRU trave caso o Linux ainda não tenha enviado a configuração
    if(shared->sample_period_ticks < 1000) {
        shared->sample_period_ticks = 20000; 
    }

    shared->write_index = 0; 
    
    uint32_t tx_frame = 0xC4000000;
    uint32_t next_sample_time = *pru_cycle + shared->sample_period_ticks;
    volatile uint32_t rx_frame;
    int i;

    while(1) {
        // 1. Lê a frequência exigida pelo Linux dinamicamente
        uint32_t current_ticks = shared->sample_period_ticks;
        
        // 2. Trava de Frequência com proteção de Overflow (Qualidade Contínua)
        // O cast para int32_t resolve matematicamente o momento em que o timer zera a cada 21s
        while ((int32_t)(next_sample_time - *pru_cycle) > 0);
        next_sample_time += current_ticks; 

        // 3. Transação SPI Fast I/O
        __R30 &= ~CS_BIT; 
        __delay_cycles(5); 
        rx_frame = 0; 

        for(i = 31; i >= 0; i--) {
            if((tx_frame >> i) & 1) __R30 |= MOSI_BIT;
            else __R30 &= ~MOSI_BIT;
            __delay_cycles(5); 

            __R30 |= SCLK_BIT;
            __delay_cycles(5);
            
            if(__R31 & MISO_BIT) rx_frame |= (1 << i);
            __delay_cycles(5);

            __R30 &= ~SCLK_BIT;
            __delay_cycles(5); 
        }
        __R30 |= CS_BIT; 
        
        // 4. Gravação Circular
        shared->data[shared->write_index] = rx_frame;
        
        uint32_t next_idx = shared->write_index + 1;
        if(next_idx >= BUFFER_SIZE) next_idx = 0; 
        shared->write_index = next_idx;
    }
}