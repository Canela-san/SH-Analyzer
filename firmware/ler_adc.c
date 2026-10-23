/*
 * ler_adc -- captura do SH-Analyzer na BeagleBone.
 *
 * A PRU0 (spi_core.asm) lê o ADS8688 pelo SPI numa grade de tempo exata e enche, alternando, dois buffers na DDR. Este
 * programa prepara a placa (pinos da PRU, memória reservada), configura e reinicia a PRU, grava cada buffer cheio num
 * .bin (cabeçalho de 1024 bytes + amostras de 16 bits intercaladas por canal) e confere a integridade da captura.
 *
 *   sudo ./ler_adc [FREQUENCIA [CANAIS]] [opções]        (./ler_adc --help)
 *
 * O contrato com a PRU está em memoria_pru.h; o formato do .bin, na struct cabecalho_arquivo_campos (lida por
 * scripts/supraharmonicos/cabecalho.py; tests/test_contrato_firmware.py confere os dois lados).
 */
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#include "memoria_pru.h"

// =====================================================================================================================
// Constantes
// =====================================================================================================================

#define CANAL_PADRAO 1                  // o canal de tensão da placa
#define BLOCOS_PADRAO 1
// 200 MHz ÷ 500, exata: Nyquist de 200 kHz com 1 canal, acima da banda de supraharmônicos (até 150 kHz).
#define FREQUENCIA_PADRAO_HZ 400000u
#define FREQUENCIA_MAXIMA_HZ 500000u    // o ADS8688 converte no máximo 500 kS/s no total

// Teto da PRU: o menor período, em ticks de 5 ns, com toda amostra no ciclo exato da grade, medido na placa com as
// esperas de CS padrão: 477 no SPI rápido (419,3 kS/s, T7g) e 610 no lento (327,9 kS/s, T7f). Abaixo dele as
// amostras atrasam e a taxa real fica menor que a do cabeçalho; ver teto_ticks_da_pru() para outras esperas.
#define TETO_TICKS_SPI_RAPIDO 477u
#define TETO_TICKS_SPI_LENTO  610u

#define PRU_CLOCK_HZ 200000000u
#define BUFFERS_PING_PONG 2u            // buffers de SAMPLES_PER_BUFFER amostras que a PRU alterna na DDR

// --- Cabeçalho do .bin --------------------------------------------------------------------------------------------
#define CABECALHO_MAGIC "SHAN"
#define CABECALHO_VERSAO 7u             // versão do FORMATO do cabeçalho (o histórico está em cabecalho.py)
#define CABECALHO_TAMANHO_TOTAL 1024u
#define CABECALHO_TITULO_TAMANHO 64u
#define CABECALHO_DESCRICAO_TAMANHO 256u
#define CABECALHO_SONDA_ID_TAMANHO 32u
#define CABECALHO_VERSAO_FIRMWARE_TAMANHO 32u
#ifndef VERSAO_FIRMWARE
#define VERSAO_FIRMWARE "desconhecida"  // o Makefile passa o 'git describe' (ou o arquivo VERSAO)
#endif

// Grandeza de cada canal (os mesmos códigos de supraharmonicos/constantes.py).
#define GRANDEZA_TENSAO       0u
#define GRANDEZA_CORRENTE     1u
#define GRANDEZA_TEMPERATURA  2u
#define GRANDEZA_NAO_USADA    0xFFu
#define GRANDEZA_PADRAO GRANDEZA_TENSAO

// Faixa de entrada do ADS8688 por canal (RANGE_SELn). O código é o índice de FAIXA_ADC_ESPAN_V, a faixa TOTAL em volts
// com VREF = 4,096 V (o --faixa do adc_tool.py).
#define FAIXA_ADC_NAO_USADA 0xFFu
#define FAIXA_ADC_PADRAO ADS8688_FAIXA_2_5_VREF
static const double FAIXA_ADC_ESPAN_V[] = {20.48, 10.24, 5.12};
#define FAIXA_ADC_NUM_CODIGOS 3

// --- Placa ------------------------------------------------------------------------------------------------------------
#define REMOTEPROC_PRU0_ESTADO "/sys/class/remoteproc/remoteproc1/state"
#define BASE_PINMUX "/sys/devices/platform/ocp"     // onde o config-pin lê e escreve o modo de cada pino
#define PRU_AINDA_NAO_INICIOU 0xFFFFFFFFu            // marca em versao_protocolo_pru, trocada por 0 pelo pru_main.c

// Com o ruído do ADC (~0,8 LSB rms), tantas amostras iguais seguidas só acontecem com o ADC mudo (SDO parado em 0: a
// placa de aquisição sem alimentação ou os pinos da PRU sem configuração) ou com a entrada saturada.
#define AMOSTRAS_CONFERIDAS_ADC_MUDO 65536u

// --- Códigos de saída -------------------------------------------------------------------------------------------------
#define SAIDA_OK 0
#define SAIDA_ERRO 1
#define SAIDA_USO 2
#define SAIDA_SOBRESCRITO 3             // buffers sobrescritos: amostras perdidas
#define SAIDA_ADC_MUDO 4

// =====================================================================================================================
// Cabeçalho do .bin
// =====================================================================================================================
// 1024 bytes, little-endian, sem padding entre campos (packed): o layout é o do arquivo, não o do compilador. Os
// campos finais (blocos, contadores, taxa medida, grade) só valem depois da reescrita no fim da captura; o CRC-32
// (zlib) cobre o cabeçalho inteiro com o próprio campo zerado.
struct cabecalho_arquivo_campos {
    char     magic[4];                                 // "SHAN"
    uint32_t versao_cabecalho;                         // CABECALHO_VERSAO
    uint32_t tamanho_cabecalho;                        // 1024
    uint64_t timestamp_unix;                           // início da captura (s, UTC; a placa não tem RTC: confira a hora)
    uint32_t frequencia_hz;                            // taxa TOTAL pedida
    uint32_t auto_seq_mask;                            // bit N = canal N na varredura
    uint32_t num_canais;
    uint8_t  lista_canais[ADS8688_MAX_CANAIS];         // em ordem crescente (a da varredura); 0xFF nos não usados
    uint32_t samples_per_buffer;                       // amostras brutas (todos os canais) por bloco
    uint32_t bytes_por_amostra;                        // 2
    uint32_t pru_clock_hz;
    uint32_t sample_period_ticks;                      // a taxa real é pru_clock_hz / sample_period_ticks
    uint32_t primeira_amostra_descartada;              // sempre 0: no AUTO_RST a 1ª amostra já é do canal certo
    double   duracao_pedida_segundos;                  // --duracao, ou 0
    uint64_t blocos_gravados;                          // [final]
    uint64_t total_amostras_gravadas;                  // [final]
    char     titulo[CABECALHO_TITULO_TAMANHO];         // UTF-8, terminado em '\0'
    char     descricao[CABECALHO_DESCRICAO_TAMANHO];
    uint8_t  grandeza_por_canal[ADS8688_MAX_CANAIS];   // [v2] por posição de lista_canais
    char     sonda_id_por_canal[ADS8688_MAX_CANAIS][CABECALHO_SONDA_ID_TAMANHO];   // [v2]
    uint8_t  faixa_adc_por_canal[ADS8688_MAX_CANAIS];  // [v3] código de faixa que o ADC recebeu
    uint32_t amostras_atrasadas;                       // [v4, final] contadores da PRU (memoria_pru.h)
    uint32_t buffers_sobrescritos;
    uint32_t quadros_preambulo_ruim;
    uint32_t atraso_cs_iteracoes[3];                   // [v4] esperas de CS (setup, hold, alto)
    char     versao_firmware[CABECALHO_VERSAO_FIRMWARE_TAMANHO];   // [v5] VERSAO_FIRMWARE
    double   taxa_medida_hz;                           // [v5, final] pelo relógio do ARM; 0 = não medida
    uint32_t buffers_ping_pong;                        // [v5]
    uint32_t folga_minima_ciclos;                      // [v6, final] grade de tempo publicada pela PRU
    uint32_t atraso_maximo_ciclos;
    uint32_t ciclos_rebase;
    uint32_t versao_protocolo_pru;
    uint32_t modo_spi;                                 // [v7] MODO_SPI_*
    uint32_t divergencias_fase_a;                      // [v7, final]
    uint32_t divergencias_fase_c;
    uint32_t header_crc32;
} __attribute__((packed));

struct cabecalho_arquivo {
    struct cabecalho_arquivo_campos campos;
    uint8_t padding[CABECALHO_TAMANHO_TOTAL - sizeof(struct cabecalho_arquivo_campos)];
} __attribute__((packed));

_Static_assert(sizeof(struct cabecalho_arquivo) == CABECALHO_TAMANHO_TOTAL, "o cabeçalho tem de ter 1024 bytes");

// CRC-32 refletido, polinômio 0xEDB88320 (o do zlib): o Python confere com zlib.crc32.
static uint32_t calcular_crc32(const void *dados, size_t tamanho) {
    const uint8_t *bytes = (const uint8_t *)dados;
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < tamanho; i++) {
        crc ^= bytes[i];
        for (int bit = 0; bit < 8; bit++) {
            crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
        }
    }
    return ~crc;
}

// =====================================================================================================================
// Saída no terminal
// =====================================================================================================================
// stdout: o resumo da captura, o progresso e, com -v, os detalhes. stderr: avisos e erros. Cores e a barra de progresso
// só num terminal (fora dele, como nos logs do varrer_taxa.sh e do calibrar_sonda.sh, o texto sai limpo).

static int verboso = 0;
static int terminal_stdout = 0;     // stdout é um terminal: barra de progresso
static int cor_stdout = 0;
static int cor_stderr = 0;
static int progresso_ativo = 0;     // a última linha do stdout é a barra (\r): limpá-la antes de qualquer outro texto

enum estilo { NEGRITO, FRACO, VERMELHO, VERDE, AMARELO, CIANO };
static const char *const CODIGOS_ANSI[] = {"\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[36m"};

static int usa_cor(FILE *f) { return f == stderr ? cor_stderr : cor_stdout; }
static const char *ansi(FILE *f, enum estilo e) { return usa_cor(f) ? CODIGOS_ANSI[e] : ""; }
static const char *fim_ansi(FILE *f) { return usa_cor(f) ? "\033[0m" : ""; }

static int pode_usar_cor(int fd) {
    const char *term = getenv("TERM");
    return isatty(fd) && getenv("NO_COLOR") == NULL && term != NULL && strcmp(term, "dumb") != 0;
}

static void limpar_progresso(void) {
    if (progresso_ativo) {
        fputs("\r\033[K", stdout);
        fflush(stdout);
        progresso_ativo = 0;
    }
}

static const char *plural(unsigned long long n, const char *singular, const char *plural_) {
    return n == 1 ? singular : plural_;
}

__attribute__((format(printf, 1, 2)))
static void erro(const char *formato, ...) {
    limpar_progresso();
    fflush(stdout);
    fprintf(stderr, "%s%sErro:%s ", ansi(stderr, NEGRITO), ansi(stderr, VERMELHO), fim_ansi(stderr));
    va_list args;
    va_start(args, formato);
    vfprintf(stderr, formato, args);
    va_end(args);
    fputc('\n', stderr);
}

__attribute__((format(printf, 1, 2)))
static void aviso(const char *formato, ...) {
    limpar_progresso();
    fflush(stdout);
    fprintf(stderr, "%s%sAviso:%s ", ansi(stderr, NEGRITO), ansi(stderr, AMARELO), fim_ansi(stderr));
    va_list args;
    va_start(args, formato);
    vfprintf(stderr, formato, args);
    va_end(args);
    fputc('\n', stderr);
}

// Uma linha "rótulo  valor" do resumo (sempre exibida). O rótulo é alinhado em colunas, não em bytes (UTF-8).
#define LARGURA_ROTULO 12
__attribute__((format(printf, 2, 3)))
static void campo(const char *rotulo, const char *formato, ...) {
    limpar_progresso();
    int colunas = 0;
    for (const char *p = rotulo; *p; p++) {
        colunas += ((unsigned char)*p & 0xC0u) != 0x80u;
    }
    printf("  %s%s%*s%s ", ansi(stdout, FRACO), rotulo, colunas < LARGURA_ROTULO ? LARGURA_ROTULO - colunas : 0, "",
           fim_ansi(stdout));
    va_list args;
    va_start(args, formato);
    vprintf(formato, args);
    va_end(args);
    putchar('\n');
}

// Um detalhe (só com -v).
__attribute__((format(printf, 1, 2)))
static void detalhe(const char *formato, ...) {
    if (!verboso) {
        return;
    }
    limpar_progresso();
    printf("  %s·%s ", ansi(stdout, FRACO), fim_ansi(stdout));
    va_list args;
    va_start(args, formato);
    vprintf(formato, args);
    va_end(args);
    putchar('\n');
}

// Uma etapa concluída que vale mostrar sempre (ex.: pinos reconfigurados).
__attribute__((format(printf, 1, 2)))
static void feito(const char *formato, ...) {
    limpar_progresso();
    printf("  %s✓%s ", ansi(stdout, VERDE), fim_ansi(stdout));
    va_list args;
    va_start(args, formato);
    vprintf(formato, args);
    va_end(args);
    putchar('\n');
}

static void imprimir_ajuda(const char *argv0) {
    const char *programa = strrchr(argv0, '/') ? strrchr(argv0, '/') + 1 : argv0;
    printf("%sUso:%s sudo ./%s [FREQUENCIA [CANAIS]] [opções]\n"
           "\n"
           "Captura o ADS8688 pela PRU0 e grava um .bin (cabeçalho de 1024 bytes + amostras de 16 bits).\n"
           "\n"
           "%sArgumentos%s\n"
           "  FREQUENCIA            taxa TOTAL em Hz, inteiro (padrão: %u). Teto da PRU com as esperas\n"
           "                        de CS padrão: 419287 Hz com o SPI rápido e 327868 com o lento. Com N\n"
           "                        canais, cada um recebe FREQUENCIA/N. Prefira divisores de 200 MHz.\n"
           "  CANAIS                canais do ADS8688 separados por vírgula, sem espaços (padrão: %d).\n"
           "                        A varredura é sempre em ordem crescente.\n"
           "\n"
           "%sDuração%s (uma das duas; padrão: %d bloco de %u amostras)\n"
           "  --blocos N            N blocos e para; 0 = até Ctrl+C\n"
           "  --duracao T           tempo com sufixo s, m ou h (30s, 10m, 1.5h), em blocos inteiros\n"
           "\n"
           "%sArquivo e metadados%s\n"
           "  -o, --saida ARQUIVO   .bin de saída (padrão: captura_AAAAMMDD_HHMMSS.bin)\n"
           "  -t, --titulo TEXTO    título curto (até %u bytes)\n"
           "  -d, --descricao TEXTO descrição (até %u bytes)\n"
           "  --grandeza C:G,...    tensao, corrente ou temperatura por canal (padrão: tensao)\n"
           "  --sonda C:ID,...      id do perfil de sonda por canal (até %u bytes), para o adc_tool.py\n"
           "\n"
           "%sADC e PRU%s\n"
           "  --faixa-adc C:V,...   faixa total por canal: 20.48 (±10,24 V, padrão), 10.24 ou 5.12\n"
           "  --spi MODO            rapido (padrão, ~15,4 MHz, lê na fase B), rapido:a, rapido:c ou\n"
           "                        lenta (~10,7 MHz, o SPI de antes de 22/10/2026)\n"
           "  --atraso-cs S,H,A     esperas do CS em passos de 10 ns (padrão: %u,%u,%u, o mínimo do ADC)\n"
           "  --forcar-taxa         aceita uma taxa acima do teto da PRU (só para varrer o teto: a taxa\n"
           "                        real sai menor que a do cabeçalho)\n"
           "\n"
           "%sSaída%s\n"
           "  -v, --verbose         mostra também os detalhes: cabeçalho, PRU, pinos, cada bloco, tempos\n"
           "  -h, --help            esta ajuda\n"
           "\n"
           "Antes de capturar, o ler_adc confere a memória reservada da DDR e os pinos da PRU (P9_28 a\n"
           "P9_31; se a placa reiniciou, ele os configura de novo) e, a cada bloco, que o ADC está\n"
           "respondendo.\n"
           "\n"
           "%sCódigos de saída%s  0 ok · 1 erro · 2 argumento inválido · 3 buffers sobrescritos (amostras\n"
           "perdidas) · 4 ADC sem resposta\n"
           "\n"
           "%sExemplos%s\n"
           "  sudo ./%s                       # 400 kS/s no canal 1, 1 bloco\n"
           "  sudo ./%s --blocos 0            # até Ctrl+C\n"
           "  sudo ./%s 400000 1 --faixa-adc 1:5.12 --duracao 30s -o s0.bin -t \"S0 60 Hz\"\n"
           "  sudo ./%s 200000 0,1 --grandeza 0:corrente --sonda 0:sct013_100a_sn001 --blocos 4\n",
           ansi(stdout, NEGRITO), fim_ansi(stdout), programa,
           ansi(stdout, NEGRITO), fim_ansi(stdout), FREQUENCIA_PADRAO_HZ, CANAL_PADRAO,
           ansi(stdout, NEGRITO), fim_ansi(stdout), BLOCOS_PADRAO, SAMPLES_PER_BUFFER,
           ansi(stdout, NEGRITO), fim_ansi(stdout), CABECALHO_TITULO_TAMANHO - 1u, CABECALHO_DESCRICAO_TAMANHO - 1u,
           CABECALHO_SONDA_ID_TAMANHO - 1u,
           ansi(stdout, NEGRITO), fim_ansi(stdout), ATRASO_CS_SETUP_PADRAO, ATRASO_CS_HOLD_PADRAO,
           ATRASO_CS_ALTO_PADRAO,
           ansi(stdout, NEGRITO), fim_ansi(stdout),
           ansi(stdout, NEGRITO), fim_ansi(stdout),
           ansi(stdout, NEGRITO), fim_ansi(stdout), programa, programa, programa, programa);
}

// =====================================================================================================================
// Argumentos
// =====================================================================================================================

static const char *nome_da_grandeza(uint8_t grandeza) {
    switch (grandeza) {
        case GRANDEZA_TENSAO:      return "tensão";
        case GRANDEZA_CORRENTE:    return "corrente";
        case GRANDEZA_TEMPERATURA: return "temperatura";
        default:                   return "?";
    }
}

static char fase_do_modo_spi(uint32_t modo) {
    return modo == MODO_SPI_RAPIDO_A ? 'A' : (modo == MODO_SPI_RAPIDO_C ? 'C' : 'B');
}

// Lê a frequência total conferindo o texto inteiro ("400k" e "4e5" são erros, não 400 e 4 Hz). Devolve 0 ou -1.
static int analisar_frequencia(const char *texto, uint32_t *frequencia) {
    char *fim;
    errno = 0;
    unsigned long valor = strtoul(texto, &fim, 10);
    if (fim == texto || *fim != '\0' || errno != 0 || valor < 1 || valor > FREQUENCIA_MAXIMA_HZ) {
        erro("frequência inválida '%s': use um inteiro em Hz, de 1 a %u (ex.: 400000; sufixos como '400k' não são "
             "aceitos).", texto, FREQUENCIA_MAXIMA_HZ);
        return -1;
    }
    *frequencia = (uint32_t)valor;
    return 0;
}

// Lista de canais ("0,1,3"), sem repetições, devolvida em ORDEM CRESCENTE: é a ordem em que o ADS8688 os varre em
// modo automático, qualquer que seja a digitada. Devolve o nº de canais ou -1.
static int analisar_lista_canais(const char *texto, int *canais) {
    char copia[256];
    snprintf(copia, sizeof(copia), "%s", texto);
    int total = 0;
    for (char *token = strtok(copia, ","); token != NULL; token = strtok(NULL, ",")) {
        char *fim;
        long valor = strtol(token, &fim, 10);
        if (fim == token || *fim != '\0' || valor < 0 || valor >= ADS8688_MAX_CANAIS) {
            erro("canal '%s' inválido em '%s': o ADS8688 tem os canais 0 a %d.", token, texto, ADS8688_MAX_CANAIS - 1);
            return -1;
        }
        for (int i = 0; i < total; i++) {
            if (canais[i] == (int)valor) {
                erro("o canal %ld aparece duas vezes em '%s'.", valor, texto);
                return -1;
            }
        }
        canais[total++] = (int)valor;
    }
    if (total == 0) {
        erro("lista de canais vazia: '%s'.", texto);
        return -1;
    }
    for (int i = 1; i < total; i++) {           // ordenação por inserção: são no máximo 8
        int chave = canais[i], j = i - 1;
        while (j >= 0 && canais[j] > chave) {
            canais[j + 1] = canais[j];
            j--;
        }
        canais[j + 1] = chave;
    }
    return total;
}

static int posicao_do_canal(const int *canais, int num_canais, int canal) {
    for (int i = 0; i < num_canais; i++) {
        if (canais[i] == canal) {
            return i;
        }
    }
    return -1;
}

// Um par "canal:valor" das opções por canal (--grandeza, --sonda, --faixa-adc). Separa o texto em 'token' (que é
// modificado), confere o canal e devolve a sua POSIÇÃO na captura (a indexação do cabeçalho), ou -1.
static int canal_do_par(char *token, const char *opcao, const char *exemplo, const int *canais, int num_canais,
                        const char **valor) {
    char *dois_pontos = strchr(token, ':');
    if (dois_pontos == NULL) {
        erro("'%s' em %s: use o formato 'canal:valor' (ex.: '%s').", token, opcao, exemplo);
        return -1;
    }
    *dois_pontos = '\0';
    *valor = dois_pontos + 1;
    char *fim;
    long canal = strtol(token, &fim, 10);
    if (fim == token || *fim != '\0') {
        erro("'%s' não é um número de canal em %s.", token, opcao);
        return -1;
    }
    int posicao = posicao_do_canal(canais, num_canais, (int)canal);
    if (posicao < 0) {
        erro("%s cita o canal %ld, que não está na captura.", opcao, canal);
        return -1;
    }
    return posicao;
}

static int analisar_lista_grandezas(const char *texto, const int *canais, int num_canais, uint8_t *grandezas) {
    char copia[512];
    snprintf(copia, sizeof(copia), "%s", texto);
    for (char *token = strtok(copia, ","); token != NULL; token = strtok(NULL, ",")) {
        const char *valor;
        int posicao = canal_do_par(token, "--grandeza", "0:tensao", canais, num_canais, &valor);
        if (posicao < 0) {
            return -1;
        }
        if (strcmp(valor, "tensao") == 0) {
            grandezas[posicao] = GRANDEZA_TENSAO;
        } else if (strcmp(valor, "corrente") == 0) {
            grandezas[posicao] = GRANDEZA_CORRENTE;
        } else if (strcmp(valor, "temperatura") == 0) {
            grandezas[posicao] = GRANDEZA_TEMPERATURA;
        } else {
            erro("grandeza '%s' desconhecida em --grandeza: use tensao, corrente ou temperatura.", valor);
            return -1;
        }
    }
    return 0;
}

// --sonda grava só o id (a chave do perfil); quem o resolve e corrige o sinal é o adc_tool.py. Um id longo demais é
// recusado, não truncado: cortado, ele poderia apontar para outra sonda.
static int analisar_lista_sondas(const char *texto, const int *canais, int num_canais,
                                 char sondas[][CABECALHO_SONDA_ID_TAMANHO]) {
    char copia[512];
    snprintf(copia, sizeof(copia), "%s", texto);
    for (char *token = strtok(copia, ","); token != NULL; token = strtok(NULL, ",")) {
        const char *valor;
        int posicao = canal_do_par(token, "--sonda", "1:sct013_100a_sn001", canais, num_canais, &valor);
        if (posicao < 0) {
            return -1;
        }
        size_t tamanho = strlen(valor);
        if (tamanho == 0 || tamanho > CABECALHO_SONDA_ID_TAMANHO - 1u) {
            erro("id de sonda '%s' em --sonda: precisa ter de 1 a %u bytes.", valor, CABECALHO_SONDA_ID_TAMANHO - 1u);
            return -1;
        }
        memcpy(sondas[posicao], valor, tamanho + 1);
    }
    return 0;
}

// A faixa tem de ser uma das três bipolares do ADS8688; outro número é recusado (gravar uma faixa diferente da que o
// ADC usa corromperia toda leitura).
static int analisar_lista_faixas(const char *texto, const int *canais, int num_canais, uint8_t *faixas) {
    char copia[512];
    snprintf(copia, sizeof(copia), "%s", texto);
    int citado[ADS8688_MAX_CANAIS] = {0};
    for (char *token = strtok(copia, ","); token != NULL; token = strtok(NULL, ",")) {
        const char *valor;
        int posicao = canal_do_par(token, "--faixa-adc", "1:5.12", canais, num_canais, &valor);
        if (posicao < 0) {
            return -1;
        }
        if (citado[posicao]) {
            erro("o canal %d aparece duas vezes em --faixa-adc.", canais[posicao]);
            return -1;
        }
        citado[posicao] = 1;
        char *fim;
        double volts = strtod(valor, &fim);
        int codigo = -1;
        for (int c = 0; fim != valor && *fim == '\0' && c < FAIXA_ADC_NUM_CODIGOS; c++) {
            double diferenca = volts - FAIXA_ADC_ESPAN_V[c];
            if (diferenca < 0.005 && diferenca > -0.005) {
                codigo = c;
            }
        }
        if (codigo < 0) {
            erro("faixa '%s' em --faixa-adc: use 20.48 (±10,24 V), 10.24 (±5,12 V) ou 5.12 (±2,56 V).", valor);
            return -1;
        }
        faixas[posicao] = (uint8_t)codigo;
    }
    return 0;
}

static int analisar_modo_spi(const char *texto) {
    if (strcmp(texto, "rapido") == 0 || strcmp(texto, "rápido") == 0 || strcmp(texto, "rapido:b") == 0) {
        return (int)MODO_SPI_RAPIDO_B;
    }
    if (strcmp(texto, "rapido:a") == 0) {
        return (int)MODO_SPI_RAPIDO_A;
    }
    if (strcmp(texto, "rapido:c") == 0) {
        return (int)MODO_SPI_RAPIDO_C;
    }
    if (strcmp(texto, "lenta") == 0 || strcmp(texto, "lento") == 0) {
        return (int)MODO_SPI_LENTO;
    }
    erro("--spi '%s': use rapido, rapido:a, rapido:c ou lenta%s.", texto,
         strncmp(texto, "padr", 4) == 0 ? " (desde 22/10/2026 o padrão é o rápido)" : "");
    return -1;
}

// "S,H,A": três inteiros de 1 a 10000 (iterações de 10 ns). 0 não serve: a espera da PRU conta para baixo até 0.
static int analisar_atrasos_cs(const char *texto, uint32_t atrasos[3]) {
    const char *p = texto;
    for (int k = 0; k < 3; k++) {
        char *fim;
        long valor = strtol(p, &fim, 10);
        if (fim == p || valor < 1 || valor > 10000 || (k < 2 && *fim != ',') || (k == 2 && *fim != '\0')) {
            erro("--atraso-cs '%s': use três inteiros de 1 a 10000 separados por vírgula (ex.: 3,1,3).", texto);
            return -1;
        }
        atrasos[k] = (uint32_t)valor;
        p = fim + 1;
    }
    return 0;
}

// Duração com sufixo opcional s, m ou h (sem sufixo = segundos). Devolve os segundos, ou -1.
static double analisar_duracao_em_segundos(const char *texto) {
    char *fim;
    double valor = strtod(texto, &fim);
    double multiplicador = 0.0;
    if (fim != texto) {
        if (*fim == '\0' || ((fim[0] == 's' || fim[0] == 'S') && fim[1] == '\0')) {
            multiplicador = 1.0;
        } else if ((fim[0] == 'm' || fim[0] == 'M') && fim[1] == '\0') {
            multiplicador = 60.0;
        } else if ((fim[0] == 'h' || fim[0] == 'H') && fim[1] == '\0') {
            multiplicador = 3600.0;
        }
    }
    if (multiplicador == 0.0 || valor * multiplicador <= 0.0) {
        erro("--duracao '%s': use um número positivo, com s, m ou h (ex.: 600, 10m, 1.5h).", texto);
        return -1.0;
    }
    return valor * multiplicador;
}

// Blocos inteiros que cobrem a duração pedida (arredonda para cima; pelo menos 1).
static unsigned long long calcular_blocos_para_duracao(double segundos, uint32_t frequencia) {
    double exatos = segundos * (double)frequencia / (double)SAMPLES_PER_BUFFER;
    unsigned long long blocos = (unsigned long long)exatos;
    if ((double)blocos < exatos) {
        blocos++;
    }
    return blocos < 1 ? 1 : blocos;
}

// O menor período (ticks) com todas as amostras na grade, para o SPI e as esperas de CS desta captura. Cada iteração
// de setup ou de hold além do padrão soma 2 ciclos ao quadro; a espera de CS alto só roda a partir de 10 iterações
// (abaixo disso o próprio caminho a garante, ver spi_core.asm) e então soma 2·A + 1. tests/test_ler_adc_host.py
// confere a conta contra o simulador da PRU.
static uint32_t teto_ticks_da_pru(uint32_t modo_spi, const uint32_t atrasos[3]) {
    long teto = (modo_spi == MODO_SPI_LENTO) ? (long)TETO_TICKS_SPI_LENTO : (long)TETO_TICKS_SPI_RAPIDO;
    teto += 2L * ((long)atrasos[0] - (long)ATRASO_CS_SETUP_PADRAO) + 2L * ((long)atrasos[1] - (long)ATRASO_CS_HOLD_PADRAO);
    if (atrasos[2] >= 10u) {
        teto += 2L * (long)atrasos[2] + 1L;
    }
    return (uint32_t)teto;
}

// Recusa uma taxa acima do teto da PRU (devolve -1); com --forcar-taxa, só avisa.
static int conferir_teto_da_taxa(uint32_t frequencia, uint32_t modo_spi, const uint32_t atrasos[3], int forcar) {
    uint32_t ticks = PRU_CLOCK_HZ / frequencia;
    uint32_t teto = teto_ticks_da_pru(modo_spi, atrasos);
    if (ticks >= teto) {
        return 0;
    }
    const char *spi = (modo_spi == MODO_SPI_LENTO) ? "lento" : "rápido";
    if (forcar) {
        aviso("%u Hz (%u ticks) passam do teto da PRU com o SPI %s e estas esperas de CS (%u ticks = %u Hz): as "
              "amostras vão atrasar e a taxa real sairá menor que a do cabeçalho (--forcar-taxa).",
              frequencia, ticks, spi, teto, PRU_CLOCK_HZ / teto);
        return 0;
    }
    erro("%u Hz pedem %u ticks por amostra, abaixo do teto da PRU com o SPI %s e estas esperas de CS (%u ticks): as "
         "amostras atrasariam e a taxa real sairia menor que a do cabeçalho. Use até %u Hz, ou --forcar-taxa para "
         "varrer o teto.", frequencia, ticks, spi, teto, PRU_CLOCK_HZ / teto);
    return -1;
}

// "captura_AAAAMMDD_HHMMSS.bin" pela hora local (a placa não tem RTC: confira a hora antes de um ensaio).
static void gerar_nome_arquivo_automatico(time_t instante, char *nome, size_t tamanho) {
    struct tm local;
    char data_hora[32];
    if (localtime_r(&instante, &local) == NULL || strftime(data_hora, sizeof(data_hora), "%Y%m%d_%H%M%S", &local) == 0) {
        snprintf(nome, tamanho, "captura_sem_timestamp.bin");
        return;
    }
    snprintf(nome, tamanho, "captura_%s.bin", data_hora);
}

// Tudo o que a captura precisa, já validado: nada aqui toca a placa nem o disco.
struct configuracao {
    uint32_t frequencia;
    uint32_t ticks;
    int canais[ADS8688_MAX_CANAIS];                       // em ordem crescente
    int num_canais;
    uint32_t mascara;                                     // AUTO_SEQ_EN
    uint8_t grandezas[ADS8688_MAX_CANAIS];                // por posição de canais[]
    char sondas[ADS8688_MAX_CANAIS][CABECALHO_SONDA_ID_TAMANHO];
    uint8_t faixas[ADS8688_MAX_CANAIS];
    uint32_t range_sel;                                   // 4 bits por canal, indexado pelo NÚMERO do canal
    uint32_t atrasos_cs[3];
    uint32_t modo_spi;
    unsigned long long blocos;                            // 0 = até Ctrl+C
    double duracao_pedida;                                // 0 sem --duracao
    const char *titulo;
    const char *descricao;
    const char *arquivo;
    char arquivo_automatico[64];
    time_t instante;
    int forcar_taxa;
};

// Opção com valor: devolve-o e avança o índice, ou NULL com o erro impresso.
static const char *valor_da_opcao(int argc, char *argv[], int *i) {
    if (*i + 1 >= argc) {
        erro("%s precisa de um valor (veja --help).", argv[*i]);
        return NULL;
    }
    return argv[++*i];
}

// Devolve SAIDA_OK ou SAIDA_USO (com o erro impresso).
static int analisar_argumentos(int argc, char *argv[], struct configuracao *c) {
    const char *texto_canais = NULL, *texto_blocos = NULL, *texto_duracao = NULL, *texto_grandeza = NULL;
    const char *texto_sonda = NULL, *texto_faixa = NULL, *texto_atraso = NULL, *texto_spi = NULL;

    memset(c, 0, sizeof(*c));
    c->frequencia = FREQUENCIA_PADRAO_HZ;
    c->instante = time(NULL);
    int i = 1;
    if (argc > 1 && argv[1][0] != '-') {        // a frequência é o 1º argumento, quando há
        if (analisar_frequencia(argv[1], &c->frequencia) < 0) {
            return SAIDA_USO;
        }
        i = 2;
    }
    for (; i < argc; i++) {
        const char *a = argv[i];
        const char **destino = NULL;
        if (strcmp(a, "--blocos") == 0) {
            destino = &texto_blocos;
        } else if (strcmp(a, "--duracao") == 0) {
            destino = &texto_duracao;
        } else if (strcmp(a, "-o") == 0 || strcmp(a, "--saida") == 0) {
            destino = &c->arquivo;
        } else if (strcmp(a, "-t") == 0 || strcmp(a, "--titulo") == 0) {
            destino = &c->titulo;
        } else if (strcmp(a, "-d") == 0 || strcmp(a, "--descricao") == 0) {
            destino = &c->descricao;
        } else if (strcmp(a, "--grandeza") == 0) {
            destino = &texto_grandeza;
        } else if (strcmp(a, "--sonda") == 0) {
            destino = &texto_sonda;
        } else if (strcmp(a, "--faixa-adc") == 0) {
            destino = &texto_faixa;
        } else if (strcmp(a, "--atraso-cs") == 0) {
            destino = &texto_atraso;
        } else if (strcmp(a, "--spi") == 0) {
            destino = &texto_spi;
        } else if (strcmp(a, "--forcar-taxa") == 0) {
            c->forcar_taxa = 1;
        } else if (strcmp(a, "-v") == 0 || strcmp(a, "--verbose") == 0 || strcmp(a, "--verboso") == 0) {
            verboso = 1;
        } else if (a[0] == '-') {
            erro("opção desconhecida '%s' (veja %s --help).", a, argv[0]);
            return SAIDA_USO;
        } else if (texto_canais == NULL) {
            texto_canais = a;
        } else {
            erro("argumento a mais: '%s' (os canais já são '%s'; a frequência vem antes deles).", a, texto_canais);
            return SAIDA_USO;
        }
        if (destino != NULL && (*destino = valor_da_opcao(argc, argv, &i)) == NULL) {
            return SAIDA_USO;
        }
    }

    if (texto_canais != NULL) {
        c->num_canais = analisar_lista_canais(texto_canais, c->canais);
        if (c->num_canais < 0) {
            return SAIDA_USO;
        }
    } else {
        c->num_canais = 1;
        c->canais[0] = CANAL_PADRAO;
    }
    memset(c->grandezas, GRANDEZA_NAO_USADA, sizeof(c->grandezas));
    memset(c->faixas, FAIXA_ADC_NAO_USADA, sizeof(c->faixas));
    for (int k = 0; k < c->num_canais; k++) {
        c->grandezas[k] = GRANDEZA_PADRAO;
        c->faixas[k] = FAIXA_ADC_PADRAO;
        c->mascara |= 1u << c->canais[k];
    }
    if ((texto_grandeza && analisar_lista_grandezas(texto_grandeza, c->canais, c->num_canais, c->grandezas) < 0) ||
        (texto_sonda && analisar_lista_sondas(texto_sonda, c->canais, c->num_canais, c->sondas) < 0) ||
        (texto_faixa && analisar_lista_faixas(texto_faixa, c->canais, c->num_canais, c->faixas) < 0)) {
        return SAIDA_USO;
    }
    for (int k = 0; k < c->num_canais; k++) {
        c->range_sel |= ((uint32_t)c->faixas[k] & 0xFu) << (4 * c->canais[k]);
    }

    c->atrasos_cs[0] = ATRASO_CS_SETUP_PADRAO;
    c->atrasos_cs[1] = ATRASO_CS_HOLD_PADRAO;
    c->atrasos_cs[2] = ATRASO_CS_ALTO_PADRAO;
    if (texto_atraso && analisar_atrasos_cs(texto_atraso, c->atrasos_cs) < 0) {
        return SAIDA_USO;
    }
    c->modo_spi = MODO_SPI_RAPIDO_B;
    if (texto_spi) {
        int modo = analisar_modo_spi(texto_spi);
        if (modo < 0) {
            return SAIDA_USO;
        }
        c->modo_spi = (uint32_t)modo;
    }
    if (conferir_teto_da_taxa(c->frequencia, c->modo_spi, c->atrasos_cs, c->forcar_taxa) < 0) {
        return SAIDA_USO;
    }
    c->ticks = PRU_CLOCK_HZ / c->frequencia;

    if (texto_blocos && texto_duracao) {
        erro("--blocos e --duracao não podem ser usados juntos.");
        return SAIDA_USO;
    }
    c->blocos = BLOCOS_PADRAO;
    if (texto_blocos) {
        char *fim;
        long long valor = strtoll(texto_blocos, &fim, 10);
        if (fim == texto_blocos || *fim != '\0' || valor < 0) {
            erro("--blocos '%s': use um inteiro >= 0 (0 = até Ctrl+C).", texto_blocos);
            return SAIDA_USO;
        }
        c->blocos = (unsigned long long)valor;
    } else if (texto_duracao) {
        c->duracao_pedida = analisar_duracao_em_segundos(texto_duracao);
        if (c->duracao_pedida < 0.0) {
            return SAIDA_USO;
        }
        c->blocos = calcular_blocos_para_duracao(c->duracao_pedida, c->frequencia);
    }

    // Texto longo demais é recusado, não truncado: cortar UTF-8 num limite de bytes pode partir um caractere.
    if (c->titulo && strlen(c->titulo) > CABECALHO_TITULO_TAMANHO - 1u) {
        erro("--titulo tem %zu bytes; o limite é %u.", strlen(c->titulo), CABECALHO_TITULO_TAMANHO - 1u);
        return SAIDA_USO;
    }
    if (c->descricao && strlen(c->descricao) > CABECALHO_DESCRICAO_TAMANHO - 1u) {
        erro("--descricao tem %zu bytes; o limite é %u.", strlen(c->descricao), CABECALHO_DESCRICAO_TAMANHO - 1u);
        return SAIDA_USO;
    }
    if (c->arquivo != NULL && c->arquivo[0] == '\0') {
        erro("nome de arquivo vazio em -o.");
        return SAIDA_USO;
    }
    if (c->arquivo == NULL) {
        gerar_nome_arquivo_automatico(c->instante, c->arquivo_automatico, sizeof(c->arquivo_automatico));
        c->arquivo = c->arquivo_automatico;
    }
    return SAIDA_OK;
}

// =====================================================================================================================
// Placa: memória reservada, pinos da PRU, reinício da PRU
// =====================================================================================================================

// Os buffers ficam nos últimos 16 MB da DDR, fora do Linux só com 'mem=496M' no /boot/uEnv.txt: sem isso, o Linux e a
// PRU escreveriam na mesma memória, em silêncio. Confere no /proc/iomem (``caminho``; os testes passam outro) que
// nenhuma "System RAM" cobre [inicio, fim). Sem root o arquivo mostra só zeros: avisa e segue. Devolve -1 no conflito.
static int conferir_ddr_reservada(const char *caminho, unsigned long long inicio, unsigned long long fim) {
    FILE *iomem = fopen(caminho, "r");
    if (iomem == NULL) {
        aviso("não deu para ler %s (%s): a reserva da DDR para a PRU não foi conferida.", caminho, strerror(errno));
        return 0;
    }
    char linha[256];
    int enderecos_visiveis = 0, conflito = 0;
    while (fgets(linha, sizeof(linha), iomem) != NULL) {
        unsigned long long a, b;
        char nome[200];
        if (linha[0] == ' ' || sscanf(linha, "%llx-%llx : %199[^\n]", &a, &b, nome) != 3) {
            continue;                       // só o nível de cima; as sub-faixas vêm indentadas
        }
        enderecos_visiveis |= (a != 0 || b != 0);
        if (strcmp(nome, "System RAM") == 0 && a < fim && b >= inicio) {
            erro("a memória dos buffers da PRU (0x%llX-0x%llX) é RAM do Linux (/proc/iomem: %llX-%llX : System RAM): a "
                 "PRU escreveria por cima do sistema. Ponha 'mem=496M' na linha cmdline= do /boot/uEnv.txt e reinicie "
                 "a placa.", inicio, fim - 1, a, b);
            conflito = 1;
        }
    }
    fclose(iomem);
    if (!enderecos_visiveis) {
        aviso("o /proc/iomem não mostra endereços (rode com sudo): a reserva da DDR não foi conferida.");
        return 0;
    }
    return conflito ? -1 : 0;
}

// Os pinos do SPI na PRU0 (os mesmos do setup.sh; tests/test_ler_adc_host.py confere). O config-pin não sobrevive a um
// reinício da placa: sem ele, a PRU chaveia pinos desligados e lê o SDO parado em 0 (uma captura toda zerada que passa
// em todas as outras checagens).
struct pino_pru {
    const char *pino;
    const char *modo;
    const char *sinal;
};
static const struct pino_pru PINOS_PRU[] = {
    {"P9_31", "pruout", "SCLK"},
    {"P9_29", "pruout", "SDI"},
    {"P9_30", "pruin", "SDO"},
    {"P9_28", "pruout", "CS"},
};
#define NUM_PINOS_PRU (sizeof(PINOS_PRU) / sizeof(PINOS_PRU[0]))

static void caminho_do_pino(const char *base, const char *pino, char *caminho, size_t tamanho) {
    snprintf(caminho, tamanho, "%s/ocp:%s_pinmux/state", base, pino);
}

static int ler_modo_do_pino(const char *base, const char *pino, char *modo, size_t tamanho) {
    char caminho[256];
    caminho_do_pino(base, pino, caminho, sizeof(caminho));
    FILE *f = fopen(caminho, "r");
    if (f == NULL) {
        return -1;
    }
    if (fgets(modo, (int)tamanho, f) == NULL) {
        modo[0] = '\0';
    }
    fclose(f);
    modo[strcspn(modo, " \t\r\n")] = '\0';
    return 0;
}

// Escreve o modo como o config-pin (echo MODO > state). O sysfs só acusa um modo inválido no fclose.
static int escrever_modo_do_pino(const char *base, const char *pino, const char *modo) {
    char caminho[256];
    caminho_do_pino(base, pino, caminho, sizeof(caminho));
    FILE *f = fopen(caminho, "w");
    if (f == NULL) {
        return -1;
    }
    int falhou = fprintf(f, "%s\n", modo) < 0;
    return (fclose(f) != 0 || falhou) ? -1 : 0;
}

// Confere o modo de cada pino do SPI e, se a placa reiniciou (ou alguém mexeu), põe de volta o da PRU. Devolve 0 com
// os pinos certos, 1 se não deu para conferir (imagem sem o pinmux do config-pin: só avisa) e -1 se não deu para
// configurar (erro impresso).
static int preparar_pinos_da_pru(const char *base) {
    char modos[NUM_PINOS_PRU][32];
    for (size_t i = 0; i < NUM_PINOS_PRU; i++) {
        if (ler_modo_do_pino(base, PINOS_PRU[i].pino, modos[i], sizeof(modos[i])) != 0) {
            aviso("não deu para conferir os pinos da PRU (%s/ocp:%s_pinmux/state: %s). Se a captura sair zerada, rode "
                  "sudo ./setup.sh.", base, PINOS_PRU[i].pino, strerror(errno));
            return 1;
        }
    }
    char errados[256] = "";
    size_t usado = 0;
    for (size_t i = 0; i < NUM_PINOS_PRU; i++) {
        if (strcmp(modos[i], PINOS_PRU[i].modo) != 0 && usado < sizeof(errados)) {
            usado += (size_t)snprintf(errados + usado, sizeof(errados) - usado, "%s%s (%s) em '%s'",
                                      usado ? ", " : "", PINOS_PRU[i].pino, PINOS_PRU[i].sinal,
                                      modos[i][0] ? modos[i] : "?");
        }
    }
    if (usado == 0) {
        detalhe("pinos da PRU no modo do SPI (P9_28 a P9_31)");
        return 0;
    }
    aviso("os pinos da PRU não estavam no modo do SPI: %s. A placa foi reiniciada? Configurando agora, como o "
          "config-pin do setup.sh.", errados);
    for (size_t i = 0; i < NUM_PINOS_PRU; i++) {
        if (strcmp(modos[i], PINOS_PRU[i].modo) == 0) {
            continue;
        }
        char lido[32] = "";
        errno = 0;
        if (escrever_modo_do_pino(base, PINOS_PRU[i].pino, PINOS_PRU[i].modo) != 0 ||
            ler_modo_do_pino(base, PINOS_PRU[i].pino, lido, sizeof(lido)) != 0 || strcmp(lido, PINOS_PRU[i].modo) != 0) {
            erro("não deu para pôr o %s em '%s' (%s): rode sudo ./setup.sh e confira o overlay da PRU no "
                 "/boot/uEnv.txt.", PINOS_PRU[i].pino, PINOS_PRU[i].modo, errno ? strerror(errno) : "modo não aceito");
            return -1;
        }
    }
    feito("pinos da PRU configurados (P9_28 a P9_31)");
    return 0;
}

static int escrever_estado_remoteproc(const char *comando) {
    int fd = open(REMOTEPROC_PRU0_ESTADO, O_WRONLY);
    if (fd < 0) {
        return -1;
    }
    size_t tamanho = strlen(comando);
    ssize_t escrito = write(fd, comando, tamanho);
    close(fd);
    return (escrito == (ssize_t)tamanho) ? 0 : -1;
}

// A PRU lê a configuração uma vez por boot (espera_configuracao em spi_core.asm) e depois só amostra: sem reiniciá-la a
// cada captura, os canais e a faixa da captura anterior continuariam valendo. Com a PRU parada, zera config_ready e
// marca versao_protocolo_pru; depois do start, espera o pru_main.c trocar a marca por 0 ("pronta, esperando a
// configuração") antes de o ARM escrevê-la.
static int reiniciar_pru_antes_da_captura(volatile struct shared_control *ctrl) {
    escrever_estado_remoteproc("stop");     // falha se ela já estava parada: não é erro
    usleep(50000);

    ctrl->config_ready = 0;
    ctrl->versao_protocolo_pru = PRU_AINDA_NAO_INICIOU;

    if (escrever_estado_remoteproc("start") != 0) {
        erro("não deu para ligar a PRU por %s: rode sudo ./setup.sh para carregar o firmware (em algumas imagens a "
             "PRU0 é o remoteproc0).", REMOTEPROC_PRU0_ESTADO);
        return -1;
    }
    for (int espera_ms = 0; espera_ms < 500 && ctrl->versao_protocolo_pru != 0; espera_ms++) {
        usleep(1000);
    }
    if (ctrl->versao_protocolo_pru != 0) {
        erro("a PRU não ficou pronta em 500 ms (versao_protocolo_pru = 0x%08X). O fw_pru.out carregado é anterior a "
             "23/10/2026 ou a PRU não iniciou: recompile e recarregue os dois com sudo ./setup.sh.",
             ctrl->versao_protocolo_pru);
        escrever_estado_remoteproc("stop");
        return -1;
    }
    return 0;
}

// Saída com erro depois de a PRU ser ligada: para a PRU (senão ela seguiria escrevendo na DDR até a próxima captura),
// fecha o arquivo, se aberto, e desfaz os mapeamentos.
static int abortar_captura(FILE *arquivo, void *ddr_map, size_t bytes_ddr, void *ctrl_map, int mem_fd) {
    escrever_estado_remoteproc("stop");
    if (arquivo != NULL) {
        fclose(arquivo);
    }
    munmap(ddr_map, bytes_ddr);
    munmap(ctrl_map, 4096);
    close(mem_fd);
    return SAIDA_ERRO;
}

// 1 se as n amostras são todas iguais: o ADC não respondeu (SDO parado) ou a entrada está saturada.
static int amostras_todas_iguais(const volatile uint16_t *amostras, size_t n) {
    for (size_t i = 1; i < n; i++) {
        if (amostras[i] != amostras[0]) {
            return 0;
        }
    }
    return 1;
}

// =====================================================================================================================
// Captura
// =====================================================================================================================

static volatile sig_atomic_t manter_execucao = 1;
static volatile sig_atomic_t sinal_recebido = 0;

// SIGINT (Ctrl+C), SIGTERM e SIGHUP (o ssh caiu): o laço sai entre dois blocos e o cabeçalho final é reescrito.
static void lidar_interrupcao(int sinal) {
    sinal_recebido = sinal;
    manter_execucao = 0;
}

static double segundos_monotonicos(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
}

// Os contadores que a PRU publica depois de cada troca de buffer (memoria_pru.h).
struct contadores_integridade {
    uint32_t amostras_atrasadas;
    uint32_t buffers_sobrescritos;
    uint32_t quadros_preambulo_ruim;
    uint32_t folga_minima_ciclos;
    uint32_t atraso_maximo_ciclos;
    uint32_t divergencias_fase_a;
    uint32_t divergencias_fase_c;
};

// Lê os contadores e avisa do que aumentou desde a última leitura.
static void conferir_integridade(volatile struct shared_control *ctrl, struct contadores_integridade *vistos) {
    struct contadores_integridade agora = {
        ctrl->amostras_atrasadas, ctrl->buffers_sobrescritos, ctrl->quadros_preambulo_ruim,
        ctrl->folga_minima_ciclos, ctrl->atraso_maximo_ciclos, ctrl->divergencias_fase_a, ctrl->divergencias_fase_c
    };
    if (agora.buffers_sobrescritos > vistos->buffers_sobrescritos) {
        erro("%u buffer(s) reescrito(s) pela PRU antes de gravado(s): há amostras PERDIDAS (o ARM atrasou: disco lento "
             "ou sistema ocupado).", agora.buffers_sobrescritos - vistos->buffers_sobrescritos);
    }
    if (agora.amostras_atrasadas > vistos->amostras_atrasadas) {
        aviso("%u amostra(s) fora da grade (até %u ciclos de 5 ns): a PRU não acompanhou a taxa; o período entre elas "
              "não é o do cabeçalho.", agora.amostras_atrasadas - vistos->amostras_atrasadas, agora.atraso_maximo_ciclos);
    }
    if (agora.quadros_preambulo_ruim > vistos->quadros_preambulo_ruim) {
        aviso("%u quadro(s) SPI com ruído no SDO: confira a ligação ADC <-> BeagleBone; essas amostras são suspeitas.",
              agora.quadros_preambulo_ruim - vistos->quadros_preambulo_ruim);
    }
    *vistos = agora;
}

#define LARGURA_BARRA 24

static void mostrar_progresso(unsigned long long feitos, unsigned long long total, double segundos_por_bloco) {
    if (!terminal_stdout) {
        return;
    }
    printf("\r\033[K  %sCapturando%s  ", ansi(stdout, NEGRITO), fim_ansi(stdout));
    if (total > 0) {
        unsigned long long cheios = feitos * LARGURA_BARRA / total;
        fputs(ansi(stdout, CIANO), stdout);
        for (unsigned long long k = 0; k < LARGURA_BARRA; k++) {
            fputs(k < cheios ? "█" : "░", stdout);
        }
        printf("%s  %llu/%llu %s · %.1f de %.1f s", fim_ansi(stdout), feitos, total, plural(total, "bloco", "blocos"),
               (double)feitos * segundos_por_bloco, (double)total * segundos_por_bloco);
    } else {
        printf("%llu %s · %.1f s %s(Ctrl+C para parar e salvar)%s", feitos, plural(feitos, "bloco", "blocos"),
               (double)feitos * segundos_por_bloco, ansi(stdout, FRACO), fim_ansi(stdout));
    }
    fflush(stdout);
    progresso_ativo = 1;
}

static void imprimir_configuracao(const struct configuracao *c, double segundos_por_bloco) {
    printf("%sler_adc%s · SH-Analyzer · firmware %s\n", ansi(stdout, NEGRITO), fim_ansi(stdout), VERSAO_FIRMWARE);
    campo("Arquivo", "%s", c->arquivo);
    if (c->titulo) {
        campo("Título", "%s", c->titulo);
    }
    if (c->descricao && verboso) {
        campo("Descrição", "%s", c->descricao);
    }
    double taxa_real = (double)PRU_CLOCK_HZ / (double)c->ticks;
    char spi[48];
    if (c->modo_spi == MODO_SPI_LENTO) {
        snprintf(spi, sizeof(spi), "SPI lento");
    } else {
        snprintf(spi, sizeof(spi), "SPI rápido, fase %c", fase_do_modo_spi(c->modo_spi));
    }
    char real[64] = "";             // fora dos divisores de 200 MHz, a PRU arredonda o período (o adc_tool.py usa o real)
    if (taxa_real != (double)c->frequencia) {
        snprintf(real, sizeof(real), "; a PRU gera %.2f S/s", taxa_real);
    }
    if (c->num_canais > 1) {
        campo("Taxa", "%u S/s no total, %.0f S/s por canal (%s%s)", c->frequencia, taxa_real / c->num_canais, spi,
              real);
    } else {
        campo("Taxa", "%u S/s (%s%s)", c->frequencia, spi, real);
    }
    for (int k = 0; k < c->num_canais; k++) {
        char rotulo[16], sonda[48] = "";
        snprintf(rotulo, sizeof(rotulo), "Canal %d", c->canais[k]);
        if (c->sondas[k][0]) {
            snprintf(sonda, sizeof(sonda), ", sonda %s", c->sondas[k]);
        }
        campo(rotulo, "%s, ±%.2f V%s", nome_da_grandeza(c->grandezas[k]), FAIXA_ADC_ESPAN_V[c->faixas[k]] / 2.0, sonda);
    }
    if (c->blocos == 0) {
        campo("Duração", "até Ctrl+C (blocos de %.3f s)", segundos_por_bloco);
    } else if (c->duracao_pedida > 0.0) {
        campo("Duração", "%llu %s = %.2f s (pedida: %g s)", c->blocos, plural(c->blocos, "bloco", "blocos"),
              (double)c->blocos * segundos_por_bloco, c->duracao_pedida);
    } else {
        campo("Duração", "%llu %s = %.2f s", c->blocos, plural(c->blocos, "bloco", "blocos"),
              (double)c->blocos * segundos_por_bloco);
    }
    if (c->atrasos_cs[0] != ATRASO_CS_SETUP_PADRAO || c->atrasos_cs[1] != ATRASO_CS_HOLD_PADRAO ||
        c->atrasos_cs[2] != ATRASO_CS_ALTO_PADRAO) {
        campo("Esperas CS", "%u/%u/%u iterações (%u/%u/%u ns; padrão %u/%u/%u)", c->atrasos_cs[0], c->atrasos_cs[1],
              c->atrasos_cs[2], 10 * c->atrasos_cs[0], 10 * c->atrasos_cs[1], 10 * c->atrasos_cs[2],
              ATRASO_CS_SETUP_PADRAO, ATRASO_CS_HOLD_PADRAO, ATRASO_CS_ALTO_PADRAO);
    }
    detalhe("período de %u ticks de 5 ns; blocos de %u amostras brutas (%.3f s) em %u buffers ping-pong na DDR",
            c->ticks, SAMPLES_PER_BUFFER, segundos_por_bloco, BUFFERS_PING_PONG);
    if (c->num_canais > 1) {
        detalhe("amostras intercaladas na ordem dos canais acima: a amostra i é do canal da posição i %% %d",
                c->num_canais);
    }
    putchar('\n');
}

// O que a captura deixou: um resultado e os números, sempre no mesmo formato (o varrer_taxa.sh lê as linhas
// Integridade, Grade, SPI e Taxa medida).
struct resultado {
    unsigned long long blocos;
    unsigned long long amostras;
    double taxa_medida;                     // 0 = não medida (menos de 2 blocos)
    double pior_gravacao_s;
    int erro_escrita;
    int adc_mudo;
};

static void imprimir_resultado(const struct configuracao *c, volatile struct shared_control *ctrl,
                               const struct contadores_integridade *n, const struct resultado *r) {
    const char *simbolo, *texto;
    enum estilo cor;
    if (r->adc_mudo) {
        simbolo = "✗"; cor = VERMELHO; texto = "Captura interrompida: o ADC não respondeu";
    } else if (r->erro_escrita) {
        simbolo = "✗"; cor = VERMELHO; texto = "Captura interrompida: erro de escrita";
    } else if (n->buffers_sobrescritos) {
        simbolo = "✗"; cor = VERMELHO; texto = "Captura com amostras perdidas";
    } else if (sinal_recebido && c->blocos != 0) {
        simbolo = "!"; cor = AMARELO; texto = "Captura interrompida antes do fim";
    } else if (n->amostras_atrasadas || n->quadros_preambulo_ruim) {
        simbolo = "!"; cor = AMARELO; texto = "Captura concluída, com avisos";
    } else {
        simbolo = "✓"; cor = VERDE; texto = "Captura concluída";
    }
    limpar_progresso();
    printf("\n%s%s%s %s%s\n", ansi(stdout, NEGRITO), ansi(stdout, cor), simbolo, texto, fim_ansi(stdout));

    double segundos = (double)r->amostras * (double)c->ticks / (double)PRU_CLOCK_HZ;
    double mib = (double)(CABECALHO_TAMANHO_TOTAL + r->amostras * sizeof(uint16_t)) / (1024.0 * 1024.0);
    campo("Arquivo", "%s (%llu %s, %.2f s, %.1f MiB)", c->arquivo, r->blocos, plural(r->blocos, "bloco", "blocos"),
          segundos, mib);

    int integro = !(n->amostras_atrasadas | n->buffers_sobrescritos | n->quadros_preambulo_ruim);
    campo("Integridade", "%s%s%s: %u %s, %u %s, %u %s", ansi(stdout, integro ? VERDE : AMARELO),
          integro ? "tudo certo" : "PROBLEMAS", fim_ansi(stdout),
          n->amostras_atrasadas, plural(n->amostras_atrasadas, "amostra atrasada", "amostras atrasadas"),
          n->buffers_sobrescritos, plural(n->buffers_sobrescritos, "buffer sobrescrito", "buffers sobrescritos"),
          n->quadros_preambulo_ruim, plural(n->quadros_preambulo_ruim, "quadro com ruído no SDO",
                                             "quadros com ruído no SDO"));

    uint32_t periodo = ctrl->sample_period_ticks;
    if (r->blocos == 0 || (n->amostras_atrasadas == 0 && n->folga_minima_ciclos >= periodo)) {
        campo("Grade", "folga ainda não publicada (a PRU a publica depois de cada bloco)");
    } else if (n->amostras_atrasadas == 0) {
        campo("Grade", "exata: folga mínima %u %s (%u ns), período constante até %.0f S/s", n->folga_minima_ciclos,
              plural(n->folga_minima_ciclos, "ciclo", "ciclos"), 5u * n->folga_minima_ciclos,
              (double)PRU_CLOCK_HZ / (double)(periodo - n->folga_minima_ciclos));
    } else {
        campo("Grade", "%u %s fora da grade, a pior %u %s (%u ns) atrasada", n->amostras_atrasadas,
              plural(n->amostras_atrasadas, "amostra", "amostras"), n->atraso_maximo_ciclos,
              plural(n->atraso_maximo_ciclos, "ciclo", "ciclos"), 5u * n->atraso_maximo_ciclos);
    }

    if (c->modo_spi == MODO_SPI_LENTO) {
        campo("SPI", "lento (~10,7 MHz)");
    } else {
        campo("SPI", "rápido, fase %c gravada; divergências de leitura: %u na fase A e %u na C",
              fase_do_modo_spi(c->modo_spi), n->divergencias_fase_a, n->divergencias_fase_c);
        if (n->divergencias_fase_a || n->divergencias_fase_c) {
            aviso("%s", n->divergencias_fase_c == 0
                  ? "o SDO volta perto de 60 ns depois da borda: a fase B (75 ns) tem margem só de um lado."
                  : n->divergencias_fase_a == 0
                  ? "o bit seguinte chega antes de 90 ns: a fase B (75 ns) tem margem só de um lado."
                  : "as fases A e C discordam da B: a janela do bit é estreita; compare o SINAD com --spi lenta.");
        }
    }

    if (r->taxa_medida > 0.0) {
        double desvio = 100.0 * (r->taxa_medida / c->frequencia - 1.0);
        campo("Taxa medida", "%.0f S/s pelo relógio do ARM (%+.2f %% da pedida)%s", r->taxa_medida, desvio,
              (desvio < -0.5 || desvio > 0.5) ? " -- DIFERENTE da pedida, confira" : "");
    }
    double segundos_por_bloco = (double)SAMPLES_PER_BUFFER * (double)c->ticks / (double)PRU_CLOCK_HZ;
    if (r->blocos > 0) {
        double margem = segundos_por_bloco / (r->pior_gravacao_s + 0.002);   // + a espera do laço (2 ms)
        detalhe("rebase do contador: %u ciclos entre as leituras", ctrl->ciclos_rebase);
        detalhe("gravação no ARM: o pior bloco levou %.0f ms; cada bloco enche em %.0f ms (margem de %.0fx)",
                1e3 * r->pior_gravacao_s, 1e3 * segundos_por_bloco, margem);
        if (margem < 3.0) {
            aviso("o ARM levou %.0f ms para gravar um bloco que enche em %.0f ms: pouca margem antes de perder "
                  "amostras (disco lento ou sistema ocupado?).", 1e3 * r->pior_gravacao_s, 1e3 * segundos_por_bloco);
        }
    }
}

// =====================================================================================================================
// main
// =====================================================================================================================

int main(int argc, char *argv[]) {
    signal(SIGINT, lidar_interrupcao);
    signal(SIGTERM, lidar_interrupcao);
    signal(SIGHUP, lidar_interrupcao);
    signal(SIGPIPE, SIG_IGN);       // um '| tee' que morreu com o ssh não pode matar o ler_adc antes do cabeçalho final
    setvbuf(stdout, NULL, _IOLBF, 0);   // num log (2>&1), stdout e stderr na ordem em que aconteceram

    terminal_stdout = isatty(STDOUT_FILENO);
    cor_stdout = pode_usar_cor(STDOUT_FILENO);
    cor_stderr = pode_usar_cor(STDERR_FILENO);

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
            imprimir_ajuda(argv[0]);
            return SAIDA_OK;
        }
    }

    struct configuracao config;
    int codigo = analisar_argumentos(argc, argv, &config);
    if (codigo != SAIDA_OK) {
        return codigo;
    }
    if (geteuid() != 0) {
        erro("o ler_adc precisa de root (a PRU, os pinos e /dev/mem): rode com sudo.");
        return SAIDA_ERRO;
    }
    double segundos_por_bloco = (double)SAMPLES_PER_BUFFER * (double)config.ticks / (double)PRU_CLOCK_HZ;
    imprimir_configuracao(&config, segundos_por_bloco);

    // --- Placa --------------------------------------------------------------------------------------------------------
    size_t bytes_por_buffer = (size_t)SAMPLES_PER_BUFFER * sizeof(uint16_t);
    unsigned long long fim_ddr = (unsigned long long)DDR_RESERVED_PHYS + bytes_por_buffer * BUFFERS_PING_PONG;
    if (conferir_ddr_reservada("/proc/iomem", DDR_RESERVED_PHYS, fim_ddr) != 0) {
        return SAIDA_ERRO;
    }
    detalhe("DDR dos buffers fora do Linux (0x%X-0x%llX)", DDR_RESERVED_PHYS, fim_ddr - 1);
    if (preparar_pinos_da_pru(BASE_PINMUX) < 0) {
        return SAIDA_ERRO;
    }

    int mem_fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (mem_fd < 0) {
        erro("não deu para abrir /dev/mem: %s.", strerror(errno));
        return SAIDA_ERRO;
    }
    void *ctrl_map = mmap(0, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, mem_fd, PRU_SHARED_RAM_PHYS);
    if (ctrl_map == MAP_FAILED) {
        erro("não deu para mapear a RAM compartilhada da PRU: %s.", strerror(errno));
        close(mem_fd);
        return SAIDA_ERRO;
    }
    volatile struct shared_control *ctrl = (volatile struct shared_control *)ctrl_map;
    void *ddr_map = mmap(0, bytes_por_buffer * BUFFERS_PING_PONG, PROT_READ, MAP_SHARED, mem_fd, DDR_RESERVED_PHYS);
    if (ddr_map == MAP_FAILED) {
        erro("não deu para mapear a DDR reservada: %s.", strerror(errno));
        munmap(ctrl_map, 4096);
        close(mem_fd);
        return SAIDA_ERRO;
    }
    const volatile uint16_t *buffers[BUFFERS_PING_PONG] = {
        (const volatile uint16_t *)ddr_map, (const volatile uint16_t *)ddr_map + SAMPLES_PER_BUFFER
    };
    volatile uint32_t *prontos[BUFFERS_PING_PONG] = {&ctrl->buffer_0_ready, &ctrl->buffer_1_ready};

    if (reiniciar_pru_antes_da_captura(ctrl) != 0) {
        munmap(ddr_map, bytes_por_buffer * BUFFERS_PING_PONG);
        munmap(ctrl_map, 4096);
        close(mem_fd);
        return SAIDA_ERRO;
    }

    // A PRU lê a configuração só depois de config_ready = 1. O versao_protocolo_pru já está em 0 (o aviso de "pronta").
    ctrl->buffer_0_addr = DDR_RESERVED_PHYS;
    ctrl->buffer_1_addr = DDR_RESERVED_PHYS + (uint32_t)bytes_por_buffer;
    ctrl->buffer_0_ready = 0;
    ctrl->buffer_1_ready = 0;
    ctrl->sample_period_ticks = config.ticks;
    ctrl->auto_seq_mask = config.mascara;
    ctrl->range_sel = config.range_sel;
    ctrl->amostras_atrasadas = 0;
    ctrl->buffers_sobrescritos = 0;
    ctrl->quadros_preambulo_ruim = 0;
    ctrl->atraso_cs_setup = config.atrasos_cs[0];
    ctrl->atraso_cs_hold = config.atrasos_cs[1];
    ctrl->atraso_cs_alto = config.atrasos_cs[2];
    ctrl->modo_spi = config.modo_spi;
    ctrl->divergencias_fase_a = 0;
    ctrl->divergencias_fase_c = 0;
    ctrl->folga_minima_ciclos = 0;
    ctrl->atraso_maximo_ciclos = 0;
    ctrl->ciclos_rebase = 0;
    ctrl->config_ready = 1;

    // A PRU escreve a versão do protocolo depois de configurar o ADS8688 (~0,1 ms): outro valor = o fw_pru.out
    // carregado não é o deste ler_adc (o 'make' foi feito, mas a PRU não recebeu o firmware novo, ou o contrário).
    for (int espera_ms = 0; espera_ms < 500 && ctrl->versao_protocolo_pru == 0; espera_ms++) {
        usleep(1000);
    }
    if (ctrl->versao_protocolo_pru != VERSAO_PROTOCOLO_PRU) {
        erro("o firmware da PRU não é o deste ler_adc (protocolo %u; este espera %u): recompile e recarregue os dois "
             "com sudo ./setup.sh.", ctrl->versao_protocolo_pru, VERSAO_PROTOCOLO_PRU);
        return abortar_captura(NULL, ddr_map, bytes_por_buffer * BUFFERS_PING_PONG, ctrl_map, mem_fd);
    }
    detalhe("PRU reiniciada e configurada (protocolo %u)", VERSAO_PROTOCOLO_PRU);

    // --- Arquivo -------------------------------------------------------------------------------------------------------
    FILE *arquivo = fopen(config.arquivo, "wb");
    if (arquivo == NULL) {
        erro("não deu para criar '%s': %s%s.", config.arquivo, strerror(errno),
             errno == ENOENT ? " (a pasta existe? crie-a com mkdir -p)" : "");
        return abortar_captura(NULL, ddr_map, bytes_por_buffer * BUFFERS_PING_PONG, ctrl_map, mem_fd);
    }

    struct cabecalho_arquivo cabecalho;
    memset(&cabecalho, 0, sizeof(cabecalho));     // padding e campos não usados determinísticos (o CRC também)
    struct cabecalho_arquivo_campos *h = &cabecalho.campos;
    memcpy(h->magic, CABECALHO_MAGIC, sizeof(h->magic));
    h->versao_cabecalho = CABECALHO_VERSAO;
    h->tamanho_cabecalho = (uint32_t)sizeof(cabecalho);
    h->timestamp_unix = (uint64_t)config.instante;
    h->frequencia_hz = config.frequencia;
    h->auto_seq_mask = config.mascara;
    h->num_canais = (uint32_t)config.num_canais;
    memset(h->lista_canais, 0xFF, sizeof(h->lista_canais));
    for (int k = 0; k < config.num_canais; k++) {
        h->lista_canais[k] = (uint8_t)config.canais[k];
    }
    h->samples_per_buffer = SAMPLES_PER_BUFFER;
    h->bytes_por_amostra = (uint32_t)sizeof(uint16_t);
    h->pru_clock_hz = PRU_CLOCK_HZ;
    h->sample_period_ticks = config.ticks;
    h->primeira_amostra_descartada = 0u;
    h->duracao_pedida_segundos = config.duracao_pedida;
    if (config.titulo) {
        memcpy(h->titulo, config.titulo, strlen(config.titulo) + 1);
    }
    if (config.descricao) {
        memcpy(h->descricao, config.descricao, strlen(config.descricao) + 1);
    }
    memcpy(h->grandeza_por_canal, config.grandezas, sizeof(h->grandeza_por_canal));
    memcpy(h->sonda_id_por_canal, config.sondas, sizeof(h->sonda_id_por_canal));
    memcpy(h->faixa_adc_por_canal, config.faixas, sizeof(h->faixa_adc_por_canal));
    memcpy(h->atraso_cs_iteracoes, config.atrasos_cs, sizeof(h->atraso_cs_iteracoes));
    snprintf(h->versao_firmware, sizeof(h->versao_firmware), "%s", VERSAO_FIRMWARE);
    h->buffers_ping_pong = BUFFERS_PING_PONG;
    h->modo_spi = config.modo_spi;
    h->header_crc32 = calcular_crc32(&cabecalho, sizeof(cabecalho));
    if (fwrite(&cabecalho, sizeof(cabecalho), 1, arquivo) != 1) {
        erro("não deu para gravar o cabeçalho em '%s'.", config.arquivo);
        return abortar_captura(arquivo, ddr_map, bytes_por_buffer * BUFFERS_PING_PONG, ctrl_map, mem_fd);
    }
    detalhe("cabeçalho v%u gravado (%u bytes, CRC 0x%08X, início %llu)", CABECALHO_VERSAO, CABECALHO_TAMANHO_TOTAL,
            h->header_crc32, (unsigned long long)h->timestamp_unix);

    // --- Laço de blocos --------------------------------------------------------------------------------------------
    // Sem descarte de amostra: no AUTO_RST, o quadro do próprio AUTO_RST (na configuração, nunca gravado) é o que traz
    // lixo; a 1ª amostra do laço já é do canal de menor número, e a amostra i é do canal da posição i % N.
    struct contadores_integridade integridade = {0, 0, 0, 0, 0, 0, 0};
    struct resultado resultado = {0, 0, 0.0, 0.0, 0, 0};
    double instante_primeiro = 0.0, instante_ultimo = 0.0;
    uint16_t valor_mudo = 0;
    mostrar_progresso(0, config.blocos, segundos_por_bloco);
    while (manter_execucao && (config.blocos == 0 || resultado.blocos < config.blocos)) {
        for (unsigned b = 0; b < BUFFERS_PING_PONG && manter_execucao; b++) {
            if (!*prontos[b] || (config.blocos != 0 && resultado.blocos >= config.blocos)) {
                continue;
            }
            double inicio = segundos_monotonicos();
            int mudo = amostras_todas_iguais(buffers[b], AMOSTRAS_CONFERIDAS_ADC_MUDO);
            size_t gravadas = fwrite((const void *)buffers[b], sizeof(uint16_t), SAMPLES_PER_BUFFER, arquivo);
            *prontos[b] = 0;
            double gasto = segundos_monotonicos() - inicio;
            resultado.pior_gravacao_s = gasto > resultado.pior_gravacao_s ? gasto : resultado.pior_gravacao_s;
            if (gravadas != SAMPLES_PER_BUFFER) {
                erro("a gravação do bloco %llu parou em %zu de %u amostras (%s): disco cheio? A captura foi "
                     "encerrada.", resultado.blocos + 1, gravadas, SAMPLES_PER_BUFFER, strerror(errno));
                resultado.erro_escrita = 1;
                manter_execucao = 0;
                break;
            }
            resultado.blocos++;
            resultado.amostras += gravadas;
            instante_ultimo = segundos_monotonicos();
            if (resultado.blocos == 1) {
                instante_primeiro = instante_ultimo;
            }
            conferir_integridade(ctrl, &integridade);
            if (mudo) {
                valor_mudo = buffers[b][0];
                resultado.adc_mudo = 1;
                manter_execucao = 0;
                break;
            }
            if (!terminal_stdout) {
                detalhe("bloco %llu gravado (buffer %c, %.0f ms)", resultado.blocos, 'A' + b, 1e3 * gasto);
            }
            mostrar_progresso(resultado.blocos, config.blocos, segundos_por_bloco);
        }
        usleep(2000);
    }
    if (progresso_ativo) {
        putchar('\n');
        progresso_ativo = 0;
    }
    if (resultado.adc_mudo) {
        erro("o ADC não está respondendo: as %u primeiras amostras do bloco %llu valem todas 0x%04X. %s A captura foi "
             "interrompida.", AMOSTRAS_CONFERIDAS_ADC_MUDO, resultado.blocos, valor_mudo,
             valor_mudo == 0
             ? "Causas prováveis: a placa de aquisição sem alimentação (a BeagleBone tem de estar na fonte de 5 V do "
               "conector: pelo USB, a placa fica desligada) ou os pinos da PRU sem configuração (sudo ./setup.sh)."
             : "A entrada está saturada (fundo de escala) ou o ADC travou.");
    }

    // --- Fim ----------------------------------------------------------------------------------------------------------
    conferir_integridade(ctrl, &integridade);
    if (resultado.blocos >= 2 && instante_ultimo > instante_primeiro) {
        // Entre o 1º e o último bloco, pelo relógio do ARM (~0,02 % num bloco de ~2,6 s: o laço espera 2 ms).
        resultado.taxa_medida = (double)(resultado.blocos - 1) * SAMPLES_PER_BUFFER / (instante_ultimo - instante_primeiro);
    }
    if (resultado.blocos == 0 && !resultado.adc_mudo) {
        aviso("nenhum bloco gravado: '%s' tem só o cabeçalho.", config.arquivo);
    }

    h->blocos_gravados = resultado.blocos;
    h->total_amostras_gravadas = resultado.amostras;
    h->amostras_atrasadas = integridade.amostras_atrasadas;
    h->buffers_sobrescritos = integridade.buffers_sobrescritos;
    h->quadros_preambulo_ruim = integridade.quadros_preambulo_ruim;
    h->taxa_medida_hz = resultado.taxa_medida;
    h->folga_minima_ciclos = integridade.folga_minima_ciclos;
    h->atraso_maximo_ciclos = integridade.atraso_maximo_ciclos;
    h->ciclos_rebase = ctrl->ciclos_rebase;
    h->versao_protocolo_pru = ctrl->versao_protocolo_pru;
    h->divergencias_fase_a = integridade.divergencias_fase_a;
    h->divergencias_fase_c = integridade.divergencias_fase_c;
    h->header_crc32 = 0;
    h->header_crc32 = calcular_crc32(&cabecalho, sizeof(cabecalho));
    if (fseek(arquivo, 0, SEEK_SET) != 0 || fwrite(&cabecalho, sizeof(cabecalho), 1, arquivo) != 1) {
        aviso("não deu para reescrever o cabeçalho final de '%s' (%s): as amostras estão íntegras, mas os blocos, os "
              "contadores e a taxa medida ficaram em 0 no cabeçalho.", config.arquivo, strerror(errno));
    } else {
        detalhe("cabeçalho final reescrito (%llu blocos, %llu amostras)", resultado.blocos, resultado.amostras);
    }
    fclose(arquivo);

    imprimir_resultado(&config, ctrl, &integridade, &resultado);

    munmap(ddr_map, bytes_por_buffer * BUFFERS_PING_PONG);
    munmap(ctrl_map, 4096);
    close(mem_fd);
    if (escrever_estado_remoteproc("stop") == 0) {   // a PRU não fica escrevendo na DDR depois da captura
        detalhe("PRU parada (a próxima captura a liga de novo)");
    }

    if (resultado.erro_escrita) {
        return SAIDA_ERRO;
    }
    if (resultado.adc_mudo) {
        return SAIDA_ADC_MUDO;
    }
    return integridade.buffers_sobrescritos ? SAIDA_SOBRESCRITO : SAIDA_OK;
}
