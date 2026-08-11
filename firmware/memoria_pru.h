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
//
// IMPORTANTE (modo multi-canal): este é o número TOTAL de amostras brutas
// por buffer, intercalando todos os canais selecionados -- não é "amostras
// por canal". Com N canais ativos, cada canal individual recebe
// aproximadamente SAMPLES_PER_BUFFER/N amostras por buffer (o resto da
// divisão, se houver, fica espalhado pelo próximo buffer, já que o índice
// de canal usado pela PRU nunca é reiniciado na troca de buffer -- ver
// spi_core.asm).
// ==============================================================================
#define SAMPLES_PER_BUFFER  1048576

// Número máximo de canais simultâneos numa captura: é o número de entradas
// físicas do ADS8688 (canais 0-7). Também define o tamanho do array
// comandos_canais[] logo abaixo -- TEM que bater com o mesmo valor
// assumido em spi_core.asm (lá não há #define: o deslocamento de 32 bytes
// até o início do array, e o tamanho do array, estão implícitos nos
// operandos hardcoded de LBBO/SBBO; se este valor mudar, o Assembly
// também precisa mudar).
#define ADS8688_MAX_CANAIS 8

struct shared_control {
    volatile uint32_t sample_period_ticks; // Offset 0
    volatile uint32_t active_buffer;       // Offset 4
    volatile uint32_t buffer_0_ready;      // Offset 8
    volatile uint32_t buffer_1_ready;      // Offset 12
    volatile uint32_t buffer_0_addr;       // Offset 16
    volatile uint32_t buffer_1_addr;       // Offset 20
    volatile uint32_t config_ready;        // Offset 24

    // --- Configuração multi-canal ------------------------------------------
    // Adicionado para suportar a intercalação (round-robin) de vários
    // canais do ADS8688 numa mesma captura. Escritos pelo ARM
    // (ler_adc.c) ANTES de sinalizar config_ready=1, e lidos pela PRU
    // (spi_core.asm) uma única vez, logo depois do handshake de
    // config_ready -- não mudam durante o resto da captura.
    volatile uint32_t num_canais;                          // Offset 28
    // Cada entrada já vem PRONTA no formato de 32 bits que o registrador
    // de comando (r28) espera em spi_core.asm: o comando de seleção
    // manual de canal do ADS8688 (datasheet SBAS582), alinhado à
    // esquerda -- ver comando_canal() em ler_adc.c. Só as primeiras
    // 'num_canais' entradas são válidas; o restante do array é ignorado.
    volatile uint32_t comandos_canais[ADS8688_MAX_CANAIS]; // Offset 32..63
};

#endif