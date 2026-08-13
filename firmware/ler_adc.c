#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stdint.h>
#include <signal.h>
#include <string.h>
#include "memoria_pru.h"

volatile int manter_execucao = 1;
void lidar_interrupcao(int dummy) { manter_execucao = 0; }

#define BLOCOS_PARA_CAPTURAR 1   // auto-encerra depois de capturar essa quantidade

// Canal usado quando nenhuma lista é passada em argv[2] (modo de um canal
// só) -- mantém o comportamento histórico deste programa: nesta placa, o
// canal 1 é o único de fato conectado a um sinal válido (ver nota no
// cabeçalho de spi_core.asm). Continua sendo o padrão implícito em modo
// multi-canal também, se o usuário não passar nada.
#define CANAL_PADRAO 1

/*
 * Converte um número de canal (0-7) para o comando de 32 bits que
 * spi_core.asm espera em r28: o comando de "seleção manual de canal"
 * do ADS8688 (modo manual, datasheet SBAS582) é, nos 16 bits altos,
 *     1100 0 C2 C1 C0  0000 0000
 * ou seja, 0xC000 + (canal << 10) como valor de 16 bits -- 0xC000 para o
 * canal 0, 0xC400 para o canal 1 (o valor hardcoded na versão anterior,
 * de um canal só), 0xC800 para o canal 2, e assim por diante até 0xDC00
 * no canal 7. spi_core.asm consome esse comando alinhado à esquerda num
 * registrador de 32 bits (CMD_BIT desloca a partir do bit 31 para baixo),
 * daí o deslocamento adicional de 16 bits aqui.
 */
static uint32_t comando_canal(int canal) {
    return 0xC0000000u | ((uint32_t)canal << 26);
}

/*
 * Interpreta a lista de canais passada em argv[2] (ex.: "0,1,3"),
 * separada por vírgulas, sem espaços. Valida:
 *   - cada canal precisa estar entre 0 e 7 (o ADS8688 tem 8 entradas
 *     single-ended endereçáveis em modo manual);
 *   - no máximo ADS8688_MAX_CANAIS (8) entradas na lista -- o total de
 *     canais que o próprio ADC possui;
 *   - sem canais repetidos: repetir um canal na lista não divide a
 *     frequência entre canais DIFERENTES como pedido, só amostra o mesmo
 *     canal mais vezes por ciclo -- quase certamente um erro de digitação,
 *     por isso é tratado como erro em vez de silenciosamente aceito.
 *
 * A ORDEM da lista é preservada exatamente como digitada -- é essa ordem
 * que define a intercalação (round-robin) das amostras no arquivo de
 * saída. Ver o comentário grande dentro do laço de captura, em main(),
 * para a explicação completa de como a posição de cada amostra no
 * arquivo mapeia para o canal correspondente.
 *
 * Retorna o número de canais lidos (preenchendo 'canais_saida'), ou -1
 * em caso de erro (já reportado em stderr).
 */
static int analisar_lista_canais(const char *texto, int *canais_saida) {
    int total = 0;
    char copia[256];
    strncpy(copia, texto, sizeof(copia) - 1);
    copia[sizeof(copia) - 1] = '\0';

    char *cursor = copia;
    char *token;
    while ((token = strtok(cursor, ",")) != NULL) {
        cursor = NULL; // strtok: passar NULL nas chamadas seguintes continua a mesma string

        char *fim;
        long valor = strtol(token, &fim, 10);
        if (fim == token || *fim != '\0') {
            fprintf(stderr, "Erro: '%s' não é um número de canal válido em "
                             "'%s'.\n", token, texto);
            return -1;
        }
        if (valor < 0 || valor > 7) {
            fprintf(stderr, "Erro: canal %ld inválido -- o ADS8688 só tem "
                             "canais 0-7.\n", valor);
            return -1;
        }
        if (total >= ADS8688_MAX_CANAIS) {
            fprintf(stderr, "Erro: mais de %d canais em '%s' -- o ADS8688 "
                             "só tem %d entradas.\n",
                    ADS8688_MAX_CANAIS, texto, ADS8688_MAX_CANAIS);
            return -1;
        }
        for (int i = 0; i < total; i++) {
            if (canais_saida[i] == (int)valor) {
                fprintf(stderr, "Erro: canal %ld repetido em '%s' -- cada "
                                 "canal deve aparecer só uma vez na lista.\n",
                        valor, texto);
                return -1;
            }
        }
        canais_saida[total++] = (int)valor;
    }

    if (total == 0) {
        fprintf(stderr, "Erro: lista de canais vazia em '%s'.\n", texto);
        return -1;
    }
    return total;
}

int main(int argc, char *argv[]) {
    signal(SIGINT, lidar_interrupcao);

    uint32_t frequencia_desejada = 30000;
    if (argc > 1) {
        frequencia_desejada = (uint32_t)atoi(argv[1]);
        if (frequencia_desejada == 0 || frequencia_desejada > 500000) {
            fprintf(stderr, "Erro: frequência inválida. Use um valor entre 1 e 500000 Hz.\n");
            return -1;
        }
    }

    // [MULTI-CANAL] argv[2], opcional: lista de canais a amostrar, ex.
    // "0,1,3" (sem espaços). Sem esse argumento, mantém o comportamento
    // histórico deste programa: um canal só, o canal 1 (CANAL_PADRAO).
    int canais[ADS8688_MAX_CANAIS];
    int num_canais;
    if (argc > 2) {
        num_canais = analisar_lista_canais(argv[2], canais);
        if (num_canais < 0) {
            return -1; // erro já reportado em stderr por analisar_lista_canais
        }
    } else {
        num_canais = 1;
        canais[0] = CANAL_PADRAO;
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

    // Cada amostra ocupa 2 bytes (só o dado real do ADC - o preâmbulo é lido
    // pela PRU só para manter o timing simétrico entre as duas metades do
    // frame SPI, mas nunca é gravado na DDR, então não entra aqui). Em modo
    // multi-canal, as amostras de canais diferentes ficam INTERCALADAS
    // nestes MESMOS buffers ping-pong (não existem buffers separados por
    // canal) -- ver o comentário grande dentro do laço de captura, mais
    // abaixo, para como a posição de cada amostra mapeia para o seu canal.
    size_t bytes_por_buffer = (size_t)SAMPLES_PER_BUFFER * sizeof(uint16_t);
    void *ddr_map = mmap(0, bytes_por_buffer * 2, PROT_READ, MAP_SHARED, mem_fd, DDR_RESERVED_PHYS);
    if (ddr_map == MAP_FAILED) {
        perror("Erro ao mapear a região DDR reservada");
        munmap(ctrl_map, 4096);
        close(mem_fd);
        return -1;
    }

    uint16_t *buffer_0_virtual = (uint16_t *)ddr_map;
    uint16_t *buffer_1_virtual = buffer_0_virtual + SAMPLES_PER_BUFFER;

    ctrl->buffer_0_addr = DDR_RESERVED_PHYS;
    ctrl->buffer_1_addr = DDR_RESERVED_PHYS + (uint32_t)bytes_por_buffer;
    ctrl->buffer_0_ready = 0;
    ctrl->buffer_1_ready = 0;
    ctrl->sample_period_ticks = 200000000 / frequencia_desejada;

    // [MULTI-CANAL] Monta a tabela de comandos de canal ANTES de sinalizar
    // config_ready=1 -- mesmo cuidado de ordenação já usado para
    // buffer_0_addr/buffer_1_addr acima: a PRU só lê num_canais/
    // comandos_canais depois de ver config_ready=1 (ver espera_configuracao
    // em spi_core.asm), então escrever a tabela antes evita que a PRU
    // comece a ler uma tabela ainda parcialmente escrita.
    ctrl->num_canais = (uint32_t)num_canais;
    for (int i = 0; i < num_canais; i++) {
        ctrl->comandos_canais[i] = comando_canal(canais[i]);
    }

    ctrl->config_ready = 1;

    FILE *ficheiro_bin = fopen("supraharmonicos_raw.bin", "wb");
    if (!ficheiro_bin) {
        perror("Erro ao criar supraharmonicos_raw.bin");
        munmap(ddr_map, bytes_por_buffer * 2);
        munmap(ctrl_map, 4096);
        close(mem_fd);
        return -1;
    }

    printf("Frequência total (taxa de transação SPI): %u Hz | "
           "SAMPLES_PER_BUFFER=%d | ticks=%u\n",
           frequencia_desejada, SAMPLES_PER_BUFFER, ctrl->sample_period_ticks);

    printf("Canais selecionados (%d): ", num_canais);
    for (int i = 0; i < num_canais; i++) {
        printf("%d%s", canais[i], (i + 1 < num_canais) ? ", " : "\n");
    }

    if (num_canais > 1) {
        // A frequência acima continua sendo a taxa de TRANSAÇÕES SPI (uma
        // amostra bruta por transação, como sempre foi); com N canais
        // intercalados, cada canal individualmente acaba sendo amostrado a
        // frequencia_desejada/N -- essa divisão é uma CONSEQUÊNCIA direta
        // da intercalação, não um parâmetro configurado à parte (não há
        // como aumentar a taxa total de transação além do que o barramento
        // SPI bit-banged suporta só porque mais canais foram pedidos).
        printf("Frequência efetiva por canal: %.2f Hz (%u Hz / %d canais)\n",
               (double)frequencia_desejada / num_canais, frequencia_desejada,
               num_canais);
        printf("Formato do arquivo: amostras intercaladas na ORDEM acima, "
               "repetindo em ciclo -- amostra_bruta[i] pertence ao canal "
               "canais[i %% %d]. Guarde essa lista e essa ordem: o "
               ".bin gerado não tem cabeçalho nenhum, então o futuro "
               "adc_tool.py vai precisar receber os mesmos canais, na "
               "mesma ordem, para desintercalar corretamente.\n",
               num_canais);
    }

    printf("Capturando %d blocos e encerrando automaticamente...\n", BLOCOS_PARA_CAPTURAR);

    unsigned long long blocos_salvos = 0;

    // [MULTI-CANAL] Só é preciso descartar UMA amostra "de alinhamento" na
    // primeiríssima vez que QUALQUER buffer for gravado -- depois disso, o
    // ciclo de canais já fica em fase com a posição no arquivo para o resto
    // da captura inteira, e nunca mais precisa de correção. Com um canal só
    // (num_canais == 1) não há nada para alinhar, então o descarte fica
    // desligado e o comportamento é idêntico ao de antes desta mudança.
    //
    // POR QUE ISSO É NECESSÁRIO: em modo manual, o ADS8688 devolve em cada
    // quadro SPI o resultado da conversão do comando enviado no quadro
    // ANTERIOR, não do comando que acabou de ser enviado agora (ver
    // cabeçalho de spi_core.asm). Com um canal só isso é invisível (o
    // canal comandado nunca muda de um quadro para o outro). Com vários
    // canais intercalados, a amostra bruta na posição k do fluxo de dados
    // corresponde, na verdade, ao canal que foi comandado na posição k-1 --
    // ou seja, a amostra 0 de toda a captura reflete um comando anterior ao
    // início da captura (indefinido) e NÃO pertence a canais[0].
    //
    // Em vez de resolver isso dentro da PRU (o que exigiria uma transação
    // de "aquecimento" extra, duplicando um bom trecho do código de
    // transação SPI bit-a-bit logo no início de spi_core.asm e pressionando
    // ainda mais os 8 KB de PRU_IMEM -- ver nota no README sobre esse
    // limite), a correção é feita aqui, do lado do ARM: a primeiríssima
    // amostra bruta de toda a captura (posição 0 do primeiro buffer
    // gravado) é descartada antes de escrever no arquivo. A partir da
    // amostra seguinte, a correspondência (posição no arquivo) ->
    // canais[posição % num_canais] fica exata para o resto da captura
    // (inclusive atravessando trocas de buffer -- o índice de canal usado
    // pela PRU nunca é reiniciado na troca de buffer, só o contador de
    // amostras-por-buffer é; ver spi_core.asm).
    int descarte_pendente = (num_canais > 1) ? 1 : 0;

    while (manter_execucao && blocos_salvos < BLOCOS_PARA_CAPTURAR) {
        if (ctrl->buffer_0_ready) {
            if (descarte_pendente) {
                fwrite(buffer_0_virtual + 1, sizeof(uint16_t),
                       SAMPLES_PER_BUFFER - 1, ficheiro_bin);
                descarte_pendente = 0;
            } else {
                fwrite(buffer_0_virtual, sizeof(uint16_t), SAMPLES_PER_BUFFER, ficheiro_bin);
            }
            ctrl->buffer_0_ready = 0;
            blocos_salvos++;
            printf("Bloco A gravado (%llu/%d)\n", blocos_salvos, BLOCOS_PARA_CAPTURAR);
        }
        if (ctrl->buffer_1_ready) {
            if (descarte_pendente) {
                fwrite(buffer_1_virtual + 1, sizeof(uint16_t),
                       SAMPLES_PER_BUFFER - 1, ficheiro_bin);
                descarte_pendente = 0;
            } else {
                fwrite(buffer_1_virtual, sizeof(uint16_t), SAMPLES_PER_BUFFER, ficheiro_bin);
            }
            ctrl->buffer_1_ready = 0;
            blocos_salvos++;
            printf("Bloco B gravado (%llu/%d)\n", blocos_salvos, BLOCOS_PARA_CAPTURAR);
        }
        usleep(2000);
    }

    printf("Captura concluída: %s\n", "supraharmonicos_raw.bin");

    fclose(ficheiro_bin);
    munmap(ddr_map, bytes_por_buffer * 2);
    munmap(ctrl_map, 4096);
    close(mem_fd);
    return 0;
}