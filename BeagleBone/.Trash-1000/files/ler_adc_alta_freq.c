#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stdint.h>
#include <signal.h>

// Endereço Físico da Memória Compartilhada do PRU
#define PRU_SHARED_RAM_PHYS 0x4A310000
#define PAGE_SIZE 4096
#define MAP_SIZE (PAGE_SIZE * 3) // 12KB (Tamanho total da Shared RAM da PRU)

// Estrutura espelhada do código da PRU
#define BUFFER_SIZE 2000
struct ring_buffer {
    volatile uint32_t write_index;
    volatile uint32_t data[BUFFER_SIZE];
};

// Range do ADS8688 (±10.24V) e centro de escala
#define V_RANGE_MAX 10.24
#define ADC_MID_SCALE 32768.0

// Variável global para controlo de paragem segura
volatile int manter_execucao = 1;

void lidar_interrupcao(int dummy) {
    manter_execucao = 0;
}

int main() {
    // Interceta o Ctrl+C para fechar o ficheiro corretamente
    signal(SIGINT, lidar_interrupcao);

    int mem_fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (mem_fd == -1) {
        printf("Erro fatal: É necessário executar com sudo.\n");
        return -1;
    }

    // Mapeia a memória física do PRU para o espaço de utilizador do Linux
    void *map_base = mmap(0, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, mem_fd, PRU_SHARED_RAM_PHYS);
    if (map_base == (void *) -1) {
        printf("Erro ao mapear a memória.\n");
        close(mem_fd);
        return -1;
    }

    // Aponta a estrutura para a base da memória mapeada
    volatile struct ring_buffer *shared = (volatile struct ring_buffer *)map_base;

    // Ficheiro de saída de dados
    FILE *ficheiro_csv = fopen("amostras_100khz.csv", "w");
    if(ficheiro_csv == NULL) {
        printf("Erro ao criar o ficheiro CSV.\n");
        munmap(map_base, MAP_SIZE);
        close(mem_fd);
        return -1;
    }
    
    // Cabeçalho do CSV
    fprintf(ficheiro_csv, "Amostra,Codigo_Digital,Tensao_V\n");

    printf("A gravar dados do ADC a 100 kHz...\n");
    printf("Pressione [Ctrl+C] para parar com segurança e guardar o ficheiro.\n");

    // Sincroniza o índice de leitura inicial com o de escrita atual
    uint32_t read_index = shared->write_index; 
    unsigned long long contador_amostras = 0;

    // Loop de extração de dados
    while(manter_execucao) {
        // Lê o índice atualizado pela PRU
        uint32_t current_write_index = shared->write_index;
        
        // Descarrega o buffer até que o índice de leitura alcance o de escrita
        while(read_index != current_write_index) {
            uint32_t raw_frame = shared->data[read_index];
            uint16_t adc_code = raw_frame & 0xFFFF;
            
            // Função de transferência matemática
            float voltage = (((float)adc_code - ADC_MID_SCALE) / ADC_MID_SCALE) * V_RANGE_MAX;

            // Grava diretamente no disco
            fprintf(ficheiro_csv, "%llu,0x%04X,%.4f\n", contador_amostras++, adc_code, voltage);

            // Avança o ponteiro de leitura circularmente
            read_index++;
            if(read_index >= BUFFER_SIZE) {
                read_index = 0;
            }
        }
        
        // Pausa de 1 milissegundo para o processador respirar. 
        // A 100 kHz, 1ms acumula apenas 100 amostras na PRU, o que é muito seguro 
        // visto que o nosso buffer tem espaço para 2000 amostras (20ms).
        usleep(1000); 
    }

    printf("\nProcesso finalizado com excelência.\n");
    printf("Total capturado: %llu amostras.\n", contador_amostras);
    printf("Ficheiro guardado em: 'amostras_100khz.csv'\n");

    fclose(ficheiro_csv);
    munmap(map_base, MAP_SIZE);
    close(mem_fd);
    
    return 0;
}