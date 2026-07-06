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

    // 1. Recebendo a frequência por linha de comando (Padrão: 1 MSPS se nada for digitado)
    uint32_t frequencia_desejada = 1000000; 
    
    if (argc > 1) {
        frequencia_desejada = atoi(argv[1]);
        // Trava de segurança: Mínimo 1 SPS, Máximo 1.3 MSPS (Limite físico do código atual)
        if (frequencia_desejada < 1 || frequencia_desejada > 1300000) {
            printf("Erro: Frequência fora dos limites operacionais (1 a 1300000 Hz).\n");
            return -1;
        }
    }

    uint32_t ticks_calculados = 200000000 / frequencia_desejada;

    int mem_fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (mem_fd == -1) {
        printf("Erro fatal: Execute com sudo.\n");
        return -1;
    }
    
    // Mapeia a Área de Controle
    void *ctrl_map = mmap(0, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, mem_fd, PRU_SHARED_RAM_PHYS);
    volatile struct shared_control *ctrl = (volatile struct shared_control *)ctrl_map;

    // Mapeia os Buffers na DDR
    void *ddr_map = mmap(0, (SAMPLES_PER_BUFFER * 2 * sizeof(uint16_t)), 
                         PROT_READ, MAP_SHARED, mem_fd, DDR_RESERVED_PHYS);
    
    uint16_t *buffer_0_virtual = (uint16_t *)ddr_map;
    uint16_t *buffer_1_virtual = buffer_0_virtual + SAMPLES_PER_BUFFER;

    // Configura a PRU com a nova frequência
    ctrl->buffer_0_addr = DDR_RESERVED_PHYS;
    ctrl->buffer_1_addr = DDR_RESERVED_PHYS + (SAMPLES_PER_BUFFER * sizeof(uint16_t));
    ctrl->buffer_0_ready = 0;
    ctrl->buffer_1_ready = 0;
    ctrl->sample_period_ticks = ticks_calculados; // <--- Injeção dinâmica da frequência

    FILE *ficheiro_bin = fopen("supraharmonicos_raw.bin", "wb");
    
    printf("=========================================================\n");
    printf(" ALVO: %u kSPS (%u Hz) | TICKS DA PRU: %u\n", (frequencia_desejada/1000), frequencia_desejada, ticks_calculados);
    printf("=========================================================\n");
    printf("Gravando na DDR em Modo Ping-Pong...\n");

    unsigned long long blocos_salvos = 0;

    while(manter_execucao) {
        if(ctrl->buffer_0_ready) {
            fwrite(buffer_0_virtual, sizeof(uint16_t), SAMPLES_PER_BUFFER, ficheiro_bin);
            ctrl->buffer_0_ready = 0; 
            blocos_salvos++;
            printf("Bloco A gravado (%llu MB totais)\n", (blocos_salvos * 2));
        }
        
        if(ctrl->buffer_1_ready) {
            fwrite(buffer_1_virtual, sizeof(uint16_t), SAMPLES_PER_BUFFER, ficheiro_bin);
            ctrl->buffer_1_ready = 0; 
            blocos_salvos++;
            printf("Bloco B gravado (%llu MB totais)\n", (blocos_salvos * 2));
        }
        
        usleep(10000); 
    }

    printf("\nGravacao finalizada com seguranca.\n");
    fclose(ficheiro_bin);
    munmap(ddr_map, SAMPLES_PER_BUFFER * 2 * sizeof(uint16_t));
    munmap(ctrl_map, 4096);
    close(mem_fd);
    return 0;
}