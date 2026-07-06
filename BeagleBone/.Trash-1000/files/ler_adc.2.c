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

    uint32_t frequencia_desejada = 1000000; // Alvo: 1000 kSPS
    
    int mem_fd = open("/dev/mem", O_RDWR | O_SYNC);
    
    // 1. Mapeia a Área de Controle (Shared RAM)
    void *ctrl_map = mmap(0, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, mem_fd, PRU_SHARED_RAM_PHYS);
    volatile struct shared_control *ctrl = (volatile struct shared_control *)ctrl_map;

    // 2. Mapeia os Buffers Gigantes na DDR Reservada (4 MB total mapeado)
    void *ddr_map = mmap(0, (SAMPLES_PER_BUFFER * 2 * sizeof(uint16_t)), 
                         PROT_READ, MAP_SHARED, mem_fd, DDR_RESERVED_PHYS);
    
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
    ctrl->sample_period_ticks = 200000000 / frequencia_desejada; // A 1 MSPS = 200 ticks
    ctrl->config_ready = 1; // <-- Sinal final: PRU pode iniciar a aquisição agora

    // 4. Arquivo Binário de Alta Velocidade
    FILE *ficheiro_bin = fopen("supraharmonicos_raw.bin", "wb");
    
    printf("Gravando na DDR em Modo Ping-Pong (2MB/bloco)...\n");

    unsigned long long blocos_salvos = 0;

    while(manter_execucao) {
        if(ctrl->buffer_0_ready) {
            // Despeja 2MB no disco em uma única operação de I/O
            fwrite(buffer_0_virtual, sizeof(uint16_t), SAMPLES_PER_BUFFER, ficheiro_bin);
            ctrl->buffer_0_ready = 0; // Libera o buffer para a PRU
            blocos_salvos++;
            printf("Bloco A gravado (%llu MB totais)\n", (blocos_salvos * 2));
        }
        
        if(ctrl->buffer_1_ready) {
            fwrite(buffer_1_virtual, sizeof(uint16_t), SAMPLES_PER_BUFFER, ficheiro_bin);
            ctrl->buffer_1_ready = 0; 
            blocos_salvos++;
            printf("Bloco B gravado (%llu MB totais)\n", (blocos_salvos * 2));
        }
        
        usleep(10000); // Dorme 10ms (Linux economiza muita CPU)
    }

    fclose(ficheiro_bin);
    munmap(ddr_map, SAMPLES_PER_BUFFER * 2 * sizeof(uint16_t));
    munmap(ctrl_map, 4096);
    close(mem_fd);
    return 0;
}