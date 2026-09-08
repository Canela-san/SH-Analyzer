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
// [MODO AUTOMÁTICO] Isto não muda com a migração do modo manual para o modo
// automático (AUTO_RST) do ADS8688: continua sendo o número TOTAL de
// amostras brutas por buffer, intercalando todos os canais habilitados -- não
// é "amostras por canal". Com N canais habilitados, cada canal individual
// recebe aproximadamente SAMPLES_PER_BUFFER/N amostras por buffer. A única
// coisa que mudou é COMO o ADS8688 decide qual canal vem em cada amostra
// (agora em hardware, sempre em ordem crescente de canal -- ver
// auto_seq_mask abaixo), não o tamanho ou a forma dos buffers.
// ==============================================================================
#define SAMPLES_PER_BUFFER  1048576

// Número máximo de canais simultâneos numa captura: é o número de entradas
// físicas do ADS8688 (canais 0-7). Usado hoje só do lado ARM (ler_adc.c),
// para validar a lista de canais recebida na linha de comando (--canais) e
// para limitar o tamanho do array local usado antes de montar a máscara de
// bits. A PRU (spi_core.asm) NÃO usa mais esta constante desde a migração
// para o modo automático -- ela não precisa mais saber QUANTOS canais estão
// ativos, só a máscara de bits (auto_seq_mask, abaixo), que o próprio
// ADS8688 consome sozinho ao entrar em modo de varredura automática.
#define ADS8688_MAX_CANAIS 8

struct shared_control {
    volatile uint32_t sample_period_ticks; // Offset 0
    volatile uint32_t active_buffer;       // Offset 4
    volatile uint32_t buffer_0_ready;      // Offset 8
    volatile uint32_t buffer_1_ready;      // Offset 12
    volatile uint32_t buffer_0_addr;       // Offset 16
    volatile uint32_t buffer_1_addr;       // Offset 20
    volatile uint32_t config_ready;        // Offset 24

    // --- [MODO AUTOMÁTICO] Configuração de varredura automática ------------
    // Substitui, a partir desta versão, o antigo par num_canais (offset 28)
    // + comandos_canais[8] (offsets 32-63) do modo manual multi-canal
    // (removido -- ver histórico no cabeçalho de spi_core.asm). Escrito pelo
    // ARM (ler_adc.c) ANTES de sinalizar config_ready=1, e lido pela PRU
    // (spi_core.asm) uma única vez, durante a configuração inicial do
    // ADS8688 (escrita do registrador de programa AUTO_SEQ_EN) -- não muda
    // durante o resto da captura.
    //
    // Bit N (0-7) ligado = canal N incluído na varredura automática do
    // ADS8688 (comando AUTO_RST). O hardware do ADC sempre varre os canais
    // habilitados em ORDEM CRESCENTE de número, independente de qualquer
    // ordem "desejada" -- diferente do antigo modo manual multi-canal, onde
    // a ordem de intercalação era livre (definida pela ordem da lista
    // passada em --canais). Só os 8 bits menos significativos são válidos
    // (ADS8688_MAX_CANAIS = 8 canais físicos); bits acima desses são
    // mascarados por segurança do lado da PRU (ver pru_main.c).
    //
    // Efeito colateral positivo desta simplificação: a struct caiu de 64
    // para 32 bytes -- menos RAM compartilhada sincronizada manualmente
    // entre ARM e PRU, e um handshake de configuração inicial mais rápido
    // (uma palavra de 32 bits a menos para escrever antes de sinalizar
    // config_ready=1).
    volatile uint32_t auto_seq_mask;       // Offset 28
};

#endif
