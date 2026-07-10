#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stdint.h>
#include <signal.h>
#include "memoria_pru.h"

volatile int manter_execucao = 1;
void lidar_interrupcao(int dummy) { manter_execucao = 0; }

int main(int argc, char *argv[]) {
    signal(SIGINT, lidar_interrupcao);

    // Frequência configurável por linha de comando (ex: ./ler_adc 409600).
    // Antes estava fixa em 1000000 (1 MSPS) - por isso, mesmo com o resto
    // corrigido, você não estaria de fato testando os 409.6 kHz desejados.
    uint32_t frequencia_desejada = 1000000; // Padrão: 1 MSPS
    if (argc > 1) {
        frequencia_desejada = (uint32_t)atoi(argv[1]);
        // Limite prático: ~500 kSPS é o throughput máximo do ADS8688 em
        // modo manual (datasheet SBAS582); acima disso o frame de 32
        // ciclos SPI não cabe mais no período da amostra.
        if (frequencia_desejada == 0 || frequencia_desejada > 500000) {
            fprintf(stderr, "Erro: frequência inválida. Use um valor entre 1 e 500000 Hz.\n");
            return -1;
        }
    }

    int mem_fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (mem_fd < 0) {
        perror("Erro ao abrir /dev/mem (rode com sudo)");
        return -1;
    }

    // 1. Mapeia a Área de Controle (Shared RAM)
    void *ctrl_map = mmap(0, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, mem_fd, PRU_SHARED_RAM_PHYS);
    if (ctrl_map == MAP_FAILED) {
        perror("Erro ao mapear a área de controle (shared RAM)");
        close(mem_fd);
        return -1;
    }
    volatile struct shared_control *ctrl = (volatile struct shared_control *)ctrl_map;

    // 2. Mapeia os Buffers Gigantes na DDR Reservada (4 MB total mapeado)
    void *ddr_map = mmap(0, (SAMPLES_PER_BUFFER * 2 * sizeof(uint16_t)), 
                         PROT_READ, MAP_SHARED, mem_fd, DDR_RESERVED_PHYS);
    if (ddr_map == MAP_FAILED) {
        perror("Erro ao mapear a região DDR reservada (confira DDR_RESERVED_PHYS e a reserva de memória no boot)");
        munmap(ctrl_map, 4096);
        close(mem_fd);
        return -1;
    }
    
    uint16_t *buffer_0_virtual = (uint16_t *)ddr_map;
    uint16_t *buffer_1_virtual = buffer_0_virtual + SAMPLES_PER_BUFFER;

    // 3. Configura a PRU
    // IMPORTANTE: config_ready só é setado por último, no final deste bloco -
    // é o que garante que a PRU (que fica presa em "espera_configuracao" logo
    // no início do spi_core.asm) só comece a gravar depois que TODOS os campos
    // abaixo já estiverem com valores válidos.
    ctrl->buffer_0_addr = DDR_RESERVED_PHYS;
    ctrl->buffer_1_addr = DDR_RESERVED_PHYS + (SAMPLES_PER_BUFFER * sizeof(uint16_t));
    ctrl->buffer_0_ready = 0;
    ctrl->buffer_1_ready = 0;
    ctrl->sample_period_ticks = 200000000 / frequencia_desejada;
    ctrl->config_ready = 1; // <-- Sinal final: PRU pode iniciar a aquisição agora

    // 4. Arquivo Binário de Alta Velocidade
    FILE *ficheiro_bin = fopen("supraharmonicos_raw.bin", "wb");
    
    printf("Frequência alvo: %u Hz (sample_period_ticks = %u)\n", frequencia_desejada, ctrl->sample_period_ticks);
    printf("Gravando na DDR em Modo Ping-Pong (2MB/bloco)...\n");

    unsigned long long blocos_salvos = 0;
    unsigned long long iteracoes = 0;

    while(manter_execucao) {
        if(ctrl->buffer_0_ready) {
            size_t escritos = fwrite(buffer_0_virtual, sizeof(uint16_t), SAMPLES_PER_BUFFER, ficheiro_bin);
            if (escritos != SAMPLES_PER_BUFFER) {
                fprintf(stderr, "AVISO: fwrite gravou %zu de %d amostras (disco cheio? erro de I/O?)\n",
                        escritos, SAMPLES_PER_BUFFER);
            }
            ctrl->buffer_0_ready = 0; // Libera o buffer para a PRU
            blocos_salvos++;
            printf("Bloco A gravado (%llu MB totais)\n", (blocos_salvos * 2));
        }
        
        if(ctrl->buffer_1_ready) {
            size_t escritos = fwrite(buffer_1_virtual, sizeof(uint16_t), SAMPLES_PER_BUFFER, ficheiro_bin);
            if (escritos != SAMPLES_PER_BUFFER) {
                fprintf(stderr, "AVISO: fwrite gravou %zu de %d amostras (disco cheio? erro de I/O?)\n",
                        escritos, SAMPLES_PER_BUFFER);
            }
            ctrl->buffer_1_ready = 0; 
            blocos_salvos++;
            printf("Bloco B gravado (%llu MB totais)\n", (blocos_salvos * 2));
        }

        // ======================================================================
        // NOVO: "batimento cardíaco" de diagnóstico, a cada ~1s (100 * 10ms).
        // ======================================================================
        // Objetivo: se a coleta "parar" de novo, este log mostra se foi a PRU
        // que travou (active_buffer para de mudar), se os buffers enchem mas
        // as flags de ready nunca saem do 1 (ARM não está limpando a tempo),
        // ou se o próprio processo do ARM ainda está vivo mas sem novidade.
        // Redirecione a saída para um arquivo (ex: "sudo ./ler_adc 102400 |
        // tee log.txt") para poder inspecionar depois que "parar".
        iteracoes++;
        if (iteracoes % 100 == 0) {
            fprintf(stderr, "[heartbeat] active_buffer=%u buf0_ready=%u buf1_ready=%u blocos=%llu\n",
                    ctrl->active_buffer, ctrl->buffer_0_ready, ctrl->buffer_1_ready, blocos_salvos);
        }

        usleep(10000); // Dorme 10ms (Linux economiza muita CPU)
    }

    fclose(ficheiro_bin);
    munmap(ddr_map, SAMPLES_PER_BUFFER * 2 * sizeof(uint16_t));
    munmap(ctrl_map, 4096);
    close(mem_fd);
    return 0;
}
