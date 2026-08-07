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

#define BLOCOS_PARA_CAPTURAR 8   // auto-encerra depois de capturar essa quantidade

int main(int argc, char *argv[]) {
    signal(SIGINT, lidar_interrupcao);

    uint32_t frequencia_desejada = 2000; // Bem mais baixa - a transação agora leva ~21 us
    if (argc > 1) {
        frequencia_desejada = (uint32_t)atoi(argv[1]);
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

    void *ctrl_map = mmap(0, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, mem_fd, PRU_SHARED_RAM_PHYS);
    if (ctrl_map == MAP_FAILED) {
        perror("Erro ao mapear a área de controle (shared RAM)");
        close(mem_fd);
        return -1;
    }
    volatile struct shared_control *ctrl = (volatile struct shared_control *)ctrl_map;

    // NOVO: cada amostra agora ocupa 4 bytes (preambulo uint16 + dado uint16)
    // em vez de 2. O tamanho total mapeado e o endereço do buffer 1 têm que
    // refletir isso.
    size_t bytes_por_buffer = (size_t)SAMPLES_PER_BUFFER * 2 * sizeof(uint16_t);
    void *ddr_map = mmap(0, bytes_por_buffer * 2, PROT_READ, MAP_SHARED, mem_fd, DDR_RESERVED_PHYS);
    if (ddr_map == MAP_FAILED) {
        perror("Erro ao mapear a região DDR reservada");
        munmap(ctrl_map, 4096);
        close(mem_fd);
        return -1;
    }

    uint16_t *buffer_0_virtual = (uint16_t *)ddr_map;
    uint16_t *buffer_1_virtual = buffer_0_virtual + (SAMPLES_PER_BUFFER * 2);

    ctrl->buffer_0_addr = DDR_RESERVED_PHYS;
    ctrl->buffer_1_addr = DDR_RESERVED_PHYS + (uint32_t)bytes_por_buffer;
    ctrl->buffer_0_ready = 0;
    ctrl->buffer_1_ready = 0;
    ctrl->sample_period_ticks = 200000000 / frequencia_desejada;
    ctrl->config_ready = 1;

    FILE *ficheiro_bin = fopen("diagnostico_preambulo.bin", "wb");
    if (!ficheiro_bin) {
        perror("Erro ao criar diagnostico_preambulo.bin");
        munmap(ddr_map, bytes_por_buffer * 2);
        munmap(ctrl_map, 4096);
        close(mem_fd);
        return -1;
    }

    printf("Frequência: %u Hz | SAMPLES_PER_BUFFER=%d (diagnóstico) | ticks=%u\n",
           frequencia_desejada, SAMPLES_PER_BUFFER, ctrl->sample_period_ticks);
    printf("Capturando %d blocos e encerrando automaticamente...\n", BLOCOS_PARA_CAPTURAR);

    unsigned long long blocos_salvos = 0;

    while (manter_execucao && blocos_salvos < BLOCOS_PARA_CAPTURAR) {
        if (ctrl->buffer_0_ready) {
            fwrite(buffer_0_virtual, sizeof(uint16_t), SAMPLES_PER_BUFFER * 2, ficheiro_bin);
            ctrl->buffer_0_ready = 0;
            blocos_salvos++;
            printf("Bloco A gravado (%llu/%d)\n", blocos_salvos, BLOCOS_PARA_CAPTURAR);
        }
        if (ctrl->buffer_1_ready) {
            fwrite(buffer_1_virtual, sizeof(uint16_t), SAMPLES_PER_BUFFER * 2, ficheiro_bin);
            ctrl->buffer_1_ready = 0;
            blocos_salvos++;
            printf("Bloco B gravado (%llu/%d)\n", blocos_salvos, BLOCOS_PARA_CAPTURAR);
        }
        usleep(2000);
    }

    printf("Diagnóstico concluído: %s\n", "diagnostico_preambulo.bin");

    fclose(ficheiro_bin);
    munmap(ddr_map, bytes_por_buffer * 2);
    munmap(ctrl_map, 4096);
    close(mem_fd);
    return 0;
}