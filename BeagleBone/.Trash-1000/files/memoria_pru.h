#ifndef MEMORIA_PRU_H
#define MEMORIA_PRU_H

#include <stdint.h>

#define PRU_SHARED_RAM_PHYS 0x4A310000 // Para o ARM (12 KB)
#define PRU_SHARED_RAM_PRU  0x00010000 // Para a PRU (12 KB)

// Onde nossa memória exclusiva de 16 MB começa na DDR
#define DDR_RESERVED_PHYS   0x9F000000 

// 1.048.576 amostras = exatos 2.097.152 bytes (2 MB) por buffer
#define SAMPLES_PER_BUFFER  1048576 

struct shared_control {
    volatile uint32_t sample_period_ticks; // Controle de frequência
    volatile uint32_t active_buffer;       // 0 ou 1 (Onde a PRU está escrevendo)
    volatile uint32_t buffer_0_ready;      // Flag (1 = cheio, ARM pode ler)
    volatile uint32_t buffer_1_ready;      // Flag (1 = cheio, ARM pode ler)
    
    volatile uint32_t buffer_0_addr;       // Endereço físico do Buffer 0 na DDR
    volatile uint32_t buffer_1_addr;       // Endereço físico do Buffer 1 na DDR
};

#endif
