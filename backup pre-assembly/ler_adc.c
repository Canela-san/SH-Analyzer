#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stdint.h>
#include <signal.h>
#include <math.h>

// ==================================================================
// CONFIGURAÇÕES DE CORES DO TERMINAL (ANSI)
// ==================================================================
#define C_CYAN   "\033[1;36m"
#define C_GREEN  "\033[1;32m"
#define C_YELLOW "\033[1;33m"
#define C_RED    "\033[1;31m"
#define C_RESET  "\033[0m"
#define C_BOLD   "\033[1m"

// ==================================================================
// PARÂMETROS DE MEMÓRIA E HARDWARE
// ==================================================================
#define PRU_SHARED_RAM_PHYS 0x4A310000
#define PAGE_SIZE 4096
#define MAP_SIZE (PAGE_SIZE * 3) 
#define BUFFER_SIZE 2000

struct shared_memory {
    volatile uint32_t sample_period_ticks;
    volatile uint32_t write_index;
    volatile uint32_t data[BUFFER_SIZE];
};

#define V_RANGE_MAX 10.24
#define ADC_MID_SCALE 32768.0

// Novos resistores mapeados na placa (em Ohms)
#define R_SERIES 32775.0
#define R_PARALLEL 1793.7
#define DIVIDER_FACTOR (((R_SERIES + R_PARALLEL) / R_PARALLEL) * 1.01) // ~19.272


volatile int manter_execucao = 1;

void lidar_interrupcao(int dummy) {
    manter_execucao = 0;
}

int main(int argc, char *argv[]) {
    signal(SIGINT, lidar_interrupcao);

    uint32_t frequencia_desejada = 10000; 
    if (argc > 1) {
        frequencia_desejada = atoi(argv[1]);
        if (frequencia_desejada <= 0 || frequencia_desejada > 400000) {
            printf(C_RED "Erro: Frequência irreal. Escolha um valor válido.\n" C_RESET);
            return -1;
        }
    }

    int mem_fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (mem_fd == -1) {
        printf(C_RED "Erro fatal: Execute com sudo.\n" C_RESET);
        return -1;
    }

    void *map_base = mmap(0, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, mem_fd, PRU_SHARED_RAM_PHYS);
    if (map_base == (void *) -1) {
        printf(C_RED "Erro ao mapear a memória.\n" C_RESET);
        close(mem_fd);
        return -1;
    }

    volatile struct shared_memory *shared = (volatile struct shared_memory *)map_base;

    uint32_t ticks_calculados = 200000000 / frequencia_desejada;
    shared->sample_period_ticks = ticks_calculados;

    usleep(100000); 

    char nome_ficheiro[64];
    snprintf(nome_ficheiro, sizeof(nome_ficheiro), "amostras_%dkHz.csv", frequencia_desejada / 1000);
    
    FILE *ficheiro_csv = fopen(nome_ficheiro, "w");
    if(ficheiro_csv == NULL) {
        printf(C_RED "Erro ao criar o ficheiro CSV.\n" C_RESET);
        munmap(map_base, MAP_SIZE);
        close(mem_fd);
        return -1;
    }
    
    fprintf(ficheiro_csv, "Amostra,Codigo_Digital,Tensao_ADC_V,Tensao_Real_V\n");

    printf(C_CYAN "=========================================================\n" C_RESET);
    printf(C_BOLD " ⚡ SISTEMA DE AQUISIÇÃO DE ALTA PRECISÃO - UNICAMP ⚡\n" C_RESET);
    printf(C_CYAN "=========================================================\n" C_RESET);
    printf(" Frequência Alvo : %s%u Hz%s\n", C_YELLOW, frequencia_desejada, C_RESET);
    printf(" Divisor Físico  : %s1 : %.3f%s\n", C_YELLOW, DIVIDER_FACTOR, C_RESET);
    printf(" Saída de Dados  : %s%s%s\n", C_GREEN, nome_ficheiro, C_RESET);
    printf(C_CYAN "=========================================================\n" C_RESET);
    printf(C_BOLD " Pressione [Ctrl+C] para finalizar a gravação com segurança.\n\n" C_RESET);

    uint32_t read_index = shared->write_index; 
    unsigned long long contador_amostras = 0;

    float dc_offset_estimado = 0.0;
    float alpha = 0.0002;

    uint32_t update_rate = frequencia_desejada / 1; 
    if(update_rate == 0) update_rate = 1;

    while(manter_execucao) {
        uint32_t current_write_index = shared->write_index;
        
        while(read_index != current_write_index) {
            uint32_t raw_frame = shared->data[read_index];
            uint16_t adc_code = raw_frame & 0xFFFF;
            
            float v_adc_bruta = (((float)adc_code - ADC_MID_SCALE) / ADC_MID_SCALE) * V_RANGE_MAX;
            
            // Filtro Acoplamento AC Digital
            dc_offset_estimado = (alpha * v_adc_bruta) + ((1.0 - alpha) * dc_offset_estimado);
            float v_adc_ac_coupled = v_adc_bruta - dc_offset_estimado;
            
            float v_real = v_adc_ac_coupled * DIVIDER_FACTOR;

            fprintf(ficheiro_csv, "%llu,0x%04X,%.4f,%.4f\n", contador_amostras, adc_code, v_adc_ac_coupled, v_real);
            contador_amostras++;


            if (contador_amostras % update_rate == 0) {
  
                printf("\r " C_BOLD "Status:" C_RESET " %s%8llu%s ams | Rede: %s%+8.2f V%s | ADC: %s%+6.3f V%s | Offset DC: %+6.3f V  ", 
                       C_YELLOW, contador_amostras, C_RESET,
                       C_GREEN, v_real, C_RESET,
                       C_CYAN, v_adc_ac_coupled, C_RESET,
                       dc_offset_estimado);
                fflush(stdout); 
            }

            read_index++;
            if(read_index >= BUFFER_SIZE) read_index = 0;
        }
        
        usleep(1000); 
    }

    // Rodapé de finalização
    printf("\n\n" C_GREEN "✅ Processo finalizado com excelência." C_RESET "\n");
    printf("Total capturado: %s%llu amostras%s.\n", C_YELLOW, contador_amostras, C_RESET);

    fclose(ficheiro_csv);
    munmap(map_base, MAP_SIZE);
    close(mem_fd);
    
    return 0;
}