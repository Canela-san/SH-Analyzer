#ifndef MEMORIA_PRU_H
#define MEMORIA_PRU_H

#include <stdint.h>

#define PRU_SHARED_RAM_PHYS 0x4A310000 // Para o ARM (12 KB)
#define PRU_SHARED_RAM_PRU  0x00010000 // Para a PRU (12 KB)

#define DDR_RESERVED_PHYS   0x9F000000

// ==============================================================================
// Amostras por buffer (versão de produção, sem captura de preâmbulo - cada
// amostra ocupa 2 bytes, só o dado real do ADC). Este valor TEM que bater
// exatamente com o "LDI r21" hardcoded em spi_core.asm - lá não dá pra usar
// #define, o valor está escrito diretamente em hexadecimal:
//   LDI r21.w0, 0x0000
//   LDI r21.w2, 0x0010   ; 0x00100000 = 1.048.576
// Se um dia mudar esse número, tem que mudar dos dois lados.
// ==============================================================================
#define SAMPLES_PER_BUFFER  1048576

struct shared_control {
    volatile uint32_t sample_period_ticks; // Offset 0
    volatile uint32_t active_buffer;       // Offset 4
    volatile uint32_t buffer_0_ready;      // Offset 8
    volatile uint32_t buffer_1_ready;      // Offset 12
    volatile uint32_t buffer_0_addr;       // Offset 16
    volatile uint32_t buffer_1_addr;       // Offset 20
    volatile uint32_t config_ready;        // Offset 24
};

#endif
