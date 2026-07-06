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
    volatile uint32_t sample_period_ticks; // Offset 0  - Controle de frequência
    volatile uint32_t active_buffer;       // Offset 4  - 0 ou 1 (Onde a PRU está escrevendo)
    volatile uint32_t buffer_0_ready;      // Offset 8  - Flag (1 = cheio, ARM pode ler)
    volatile uint32_t buffer_1_ready;      // Offset 12 - Flag (1 = cheio, ARM pode ler)

    volatile uint32_t buffer_0_addr;       // Offset 16 - Endereço físico do Buffer 0 na DDR
    volatile uint32_t buffer_1_addr;       // Offset 20 - Endereço físico do Buffer 1 na DDR

    // ==========================================================================
    // NOVO CAMPO - Handshake de sincronização ARM -> PRU
    // ==========================================================================
    // PROBLEMA QUE ISSO RESOLVE:
    // A PRU (spi_core.asm) lê buffer_0_addr/buffer_1_addr apenas UMA VEZ, logo
    // no início da rotina, antes de entrar no laço principal. Se a PRU for
    // iniciada (remoteproc start) antes do ler_adc.c ter rodado e escrito os
    // endereços reais da DDR nesta struct, a PRU trava (LBBO) o valor 0x00000000
    // e passa a gravar as amostras num endereço físico completamente errado -
    // nunca tocando na região 0x9F000000 que o ARM está mapeando. Resultado:
    // o binário final fica cheio de zeros, porque a área que o ARM lê nunca
    // recebe escrita nenhuma da PRU.
    //
    // SOLUÇÃO: a PRU agora espera (busy-wait) este flag virar 1 antes de ler os
    // endereços de buffer e iniciar a aquisição. O ARM (ler_adc.c) só deve setar
    // este campo para 1 como ÚLTIMO passo da inicialização, depois de já ter
    // escrito buffer_0_addr, buffer_1_addr e zerado as flags de ready.
    volatile uint32_t config_ready;        // Offset 24 - 1 = ARM já configurou os endereços
};

#endif