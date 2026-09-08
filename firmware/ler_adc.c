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
 * [MODO AUTOMÁTICO] Interpreta a lista de canais passada em argv[2] (ex.:
 * "0,1,3"), separada por vírgulas, sem espaços. Valida:
 *   - cada canal precisa estar entre 0 e 7 (o ADS8688 tem 8 entradas
 *     single-ended endereçáveis);
 *   - no máximo ADS8688_MAX_CANAIS (8) entradas na lista -- o total de
 *     canais que o próprio ADC possui;
 *   - sem canais repetidos: repetir um canal na lista não divide a
 *     frequência entre canais DIFERENTES como pedido, só amostra o mesmo
 *     canal mais vezes por ciclo -- quase certamente um erro de digitação,
 *     por isso é tratado como erro em vez de silenciosamente aceito.
 *
 * IMPORTANTE -- mudança de comportamento em relação ao antigo modo manual:
 * a lista é ORDENADA EM ORDEM CRESCENTE antes de retornar, independente da
 * ordem em que foi digitada. Isso não é uma escolha de estilo: o ADS8688 em
 * modo automático (AUTO_RST) sempre varre os canais habilitados em ordem
 * crescente de número de canal -- é assim que o hardware funciona, não algo
 * configurável (ver datasheet SBAS582C, seção 8.4.2.5). No antigo modo
 * manual, a ordem de intercalação era livre (definida pela ordem digitada);
 * agora ela é sempre a ordem numérica dos canais. Ordenar aqui garante que
 * a ordem impressa no console -- que o usuário deve copiar para --canais no
 * adc_tool.py -- bata exatamente com a ordem real de intercalação no
 * arquivo .bin, não importa em que ordem o usuário digitou na linha de
 * comando.
 *
 * Retorna o número de canais lidos (preenchendo 'canais_saida', já
 * ordenado), ou -1 em caso de erro (já reportado em stderr).
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

    // [MODO AUTOMÁTICO] Ordena em ordem crescente -- ver docstring acima.
    // Insertion sort: total é no máximo 8, o custo é irrelevante.
    for (int i = 1; i < total; i++) {
        int chave = canais_saida[i];
        int j = i - 1;
        while (j >= 0 && canais_saida[j] > chave) {
            canais_saida[j + 1] = canais_saida[j];
            j--;
        }
        canais_saida[j + 1] = chave;
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

    // argv[2], opcional: lista de canais a amostrar, ex. "0,1,3" (sem
    // espaços). Sem esse argumento, mantém o comportamento histórico deste
    // programa: um canal só, o canal 1 (CANAL_PADRAO). A ordem final
    // impressa/usada é sempre crescente -- ver analisar_lista_canais().
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

    // [MODO AUTOMÁTICO] Monta a máscara de bits do registrador AUTO_SEQ_EN
    // do ADS8688 a partir da lista de canais já validada/ordenada: bit N
    // ligado = canal N incluído na varredura automática. Substitui a antiga
    // tabela comandos_canais[] (um comando manual de 32 bits por canal,
    // consumida pela PRU em round-robin); agora a PRU só precisa desta
    // única palavra de 32 bits (só os 8 bits baixos são significativos).
    uint32_t mascara_auto_seq = 0;
    for (int i = 0; i < num_canais; i++) {
        mascara_auto_seq |= (1u << canais[i]);
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

    // [MODO AUTOMÁTICO] Escreve a máscara ANTES de sinalizar config_ready=1
    // -- mesmo cuidado de ordenação já usado para buffer_0_addr/
    // buffer_1_addr acima: a PRU só lê auto_seq_mask depois de ver
    // config_ready=1 (ver espera_configuracao em spi_core.asm).
    ctrl->auto_seq_mask = mascara_auto_seq;

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

    printf("Canais selecionados (%d), em ordem crescente -- a varredura "
           "automática do ADS8688 sempre segue essa ordem, "
           "independente de como foram digitados: ", num_canais);
    for (int i = 0; i < num_canais; i++) {
        printf("%d%s", canais[i], (i + 1 < num_canais) ? ", " : "\n");
    }

    if (num_canais > 1) {
        // A frequência acima continua sendo a taxa de TRANSAÇÕES SPI (uma
        // amostra bruta por transação, como sempre foi); com N canais
        // intercalados, cada canal individualmente acaba sendo amostrado a
        // frequencia_desejada/N -- essa divisão é uma CONSEQUÊNCIA direta
        // da intercalação, não um parâmetro configurado à parte.
        printf("Frequência efetiva por canal: %.2f Hz (%u Hz / %d canais)\n",
               (double)frequencia_desejada / num_canais, frequencia_desejada,
               num_canais);
        printf("Formato do arquivo: amostras intercaladas em ORDEM "
               "CRESCENTE de canal (imposta pelo hardware em modo "
               "automático) -- amostra_bruta[i] pertence ao canal "
               "canais[i %% %d], usando a lista já ordenada impressa acima. "
               "O .bin gerado não tem cabeçalho nenhum, então o adc_tool.py "
               "precisa receber essa mesma lista/ordem via --canais para "
               "desintercalar corretamente.\n",
               num_canais);
    }

    printf("A primeira amostra bruta de toda a captura é sempre descartada "
           "antes de chegar no arquivo (dado residual do ADS8688 anterior "
           "ao início real da varredura -- ver comentário no laço de "
           "captura abaixo).\n");

    printf("Capturando %d blocos e encerrando automaticamente...\n", BLOCOS_PARA_CAPTURAR);

    unsigned long long blocos_salvos = 0;

    // A primeira amostra bruta de TODA captura -- 1 canal ou vários -- é
    // sempre descartada, incondicionalmente.
    //
    // POR QUE: o ADS8688 (em qualquer modo, manual ou automático) sempre
    // devolve, em cada quadro SPI, o resultado do comando/estado do quadro
    // ANTERIOR, nunca do quadro atual (ver cabeçalho de spi_core.asm). A
    // própria primeiríssima transação SPI que a PRU executa depois do boot
    // -- ainda dentro da sequência de configuração do modo automático,
    // antes mesmo do laço principal começar -- necessariamente reflete o
    // que já estava pendente no ADS8688 de ANTES da captura começar (lixo
    // de inicialização, ou resíduo de uma execução anterior do firmware).
    // Esse resíduo se propaga, por causa desse mesmo efeito de pipeline de
    // 1 quadro, até a primeira amostra que de fato chega no laço principal
    // e é gravada na DDR.
    //
    // Antes desta mudança, o descarte só era feito em captura multi-canal
    // (para realinhar posição <-> canal). A partir de agora é sempre feito,
    // porque o problema de fundo ("primeiro dado é antigo/residual") existe
    // também com 1 canal só -- só não era corrigido. Descartar exatamente 1
    // amostra é uma amostra a menos em mais de 1 milhão por buffer --
    // estatisticamente irrelevante para a FFT -- e mantém intacto o
    // alinhamento (amostra retida 0 -> canais[0]) usado em todo o resto
    // deste programa e em adc_tool.py.
    int descarte_pendente = 1;

    while (manter_execucao && blocos_salvos < BLOCOS_PARA_CAPTURAR) {
        if (ctrl->buffer_0_ready) {
            const uint16_t *origem = buffer_0_virtual;
            size_t esperado = SAMPLES_PER_BUFFER;
            if (descarte_pendente) {
                origem = buffer_0_virtual + 1;
                esperado = SAMPLES_PER_BUFFER - 1;
            }
            size_t gravado = fwrite(origem, sizeof(uint16_t), esperado, ficheiro_bin);
            ctrl->buffer_0_ready = 0;
            if (gravado != esperado) {
                fprintf(stderr, "Erro: fwrite gravou só %zu/%zu amostras no "
                                 "bloco A -- disco cheio ou erro de I/O? "
                                 "Encerrando a captura para não deixar um "
                                 ".bin truncado sem aviso.\n",
                        gravado, esperado);
                manter_execucao = 0;
            } else {
                descarte_pendente = 0;
                blocos_salvos++;
                printf("Bloco A gravado (%llu/%d)\n", blocos_salvos, BLOCOS_PARA_CAPTURAR);
            }
        }
        if (ctrl->buffer_1_ready) {
            const uint16_t *origem = buffer_1_virtual;
            size_t esperado = SAMPLES_PER_BUFFER;
            if (descarte_pendente) {
                origem = buffer_1_virtual + 1;
                esperado = SAMPLES_PER_BUFFER - 1;
            }
            size_t gravado = fwrite(origem, sizeof(uint16_t), esperado, ficheiro_bin);
            ctrl->buffer_1_ready = 0;
            if (gravado != esperado) {
                fprintf(stderr, "Erro: fwrite gravou só %zu/%zu amostras no "
                                 "bloco B -- disco cheio ou erro de I/O? "
                                 "Encerrando a captura para não deixar um "
                                 ".bin truncado sem aviso.\n",
                        gravado, esperado);
                manter_execucao = 0;
            } else {
                descarte_pendente = 0;
                blocos_salvos++;
                printf("Bloco B gravado (%llu/%d)\n", blocos_salvos, BLOCOS_PARA_CAPTURAR);
            }
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