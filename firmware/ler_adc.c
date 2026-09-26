#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stdint.h>
#include <signal.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include "memoria_pru.h"

volatile int manter_execucao = 1;
void lidar_interrupcao(int dummy) { manter_execucao = 0; }

// Número de blocos capturados quando nem --blocos nem --duracao são
// passados na linha de comando -- mantém o comportamento histórico deste
// programa (a única forma de captura antes desta funcionalidade: sempre
// exatamente 1 bloco, via o antigo BLOCOS_PARA_CAPTURAR fixo). Ver main()
// e a documentação de --blocos/--duracao, logo abaixo, para como alterar
// isso em tempo de execução.
#define BLOCOS_PADRAO 1

// Canal usado quando nenhuma lista é passada em argv[2] (modo de um canal
// só) -- mantém o comportamento histórico deste programa: nesta placa, o
// canal 1 é o único de fato conectado a um sinal válido (ver nota no
// cabeçalho de spi_core.asm). Continua sendo o padrão implícito em modo
// multi-canal também, se o usuário não passar nada.
#define CANAL_PADRAO 1

// ============================================================================
// [CABECALHO DO ARQUIVO .bin]
// ============================================================================
// A partir desta versão, todo '.bin' gerado por este programa começa com um
// cabeçalho de tamanho FIXO (1024 bytes) antes de qualquer amostra bruta.
//
// ⚠️ QUEBRA DE COMPATIBILIDADE: arquivos '.bin' gerados por versões
// anteriores deste programa (sem cabeçalho) e o adc_tool.py atual (que ainda
// não sabe pular esses 1024 bytes) NÃO são compatíveis com este formato novo
// -- ver docs/contexto_projeto.md para o item pendente de atualizar o lado
// Python antes da próxima captura real.
#define CABECALHO_MAGIC "SHAN"      // 4 bytes, sem terminador nulo armazenado
#define CABECALHO_VERSAO 2u         // versão do FORMATO do cabeçalho (não do firmware/software) -- v2 adiciona grandeza_por_canal/sonda_id_por_canal (ver struct cabecalho_arquivo_campos); adc_tool.py ainda não foi atualizado para ler esses campos novos nesta revisão, ver docs/proposta_correcao_sonda.md
#define CABECALHO_TAMANHO_TOTAL 1024u

// Tamanho FIXO (bytes, incluindo o terminador nulo) dos campos de texto
// livre de rastreabilidade -- ver --titulo/--descricao e a struct logo
// abaixo. Nomeados aqui (em vez de "64"/"256" soltos no meio da struct e de
// novo na validação de tamanho em main()) pela mesma razão de sempre: uma
// única fonte de verdade para um número que precisa bater em mais de um
// lugar do arquivo.
#define CABECALHO_TITULO_TAMANHO 64u
#define CABECALHO_DESCRICAO_TAMANHO 256u

// [SONDA/GRANDEZA] Tamanho FIXO (bytes, incluindo o terminador nulo) do
// identificador de sonda por canal -- ver --sonda, sonda_id_por_canal na
// struct abaixo, e docs/proposta_correcao_sonda.md para o racional
// completo. 32 bytes (31 úteis de texto ASCII) cobre confortavelmente um
// código do tipo "fabricante_modelo_serial" sem precisar abreviar; o nome/
// descrição completos da sonda ficam no arquivo de perfil correspondente,
// do lado Python -- este campo é só a CHAVE de busca desse arquivo, não o
// perfil em si.
#define CABECALHO_SONDA_ID_TAMANHO 32u

// [SONDA/GRANDEZA] Valores possíveis para grandeza_por_canal na struct
// abaixo -- a grandeza física que cada canal habilitado está medindo.
// Mesma indexação de lista_canais (posição i descreve o canal
// lista_canais[i]); slots não usados (índice >= num_canais) ficam em
// GRANDEZA_NAO_USADA. Precisa ficar em sincronia manual com os mesmos
// valores do lado Python (adc_tool.py) -- não há arquivo de constantes
// compartilhado entre C e Python neste projeto (mesma situação já conhecida
// de ADS8688_MAX_CANAIS).
#define GRANDEZA_TENSAO       0u
#define GRANDEZA_CORRENTE     1u
#define GRANDEZA_TEMPERATURA  2u
#define GRANDEZA_NAO_USADA    0xFFu

// Grandeza assumida para um canal habilitado que não recebeu --grandeza
// explícito -- preserva o uso histórico deste programa (nenhuma flag nova
// = tudo como antes, canal de tensão).
#define GRANDEZA_PADRAO GRANDEZA_TENSAO

// Clock da PRU usado para converter uma frequência em Hz para um número de
// ciclos da PRU (sample_period_ticks, escrito em shared_control). Nomeado em
// vez de deixar "200000000" solto no meio da conta -- é o mesmo valor usado
// em spi_core.asm para todos os cálculos de timing (200 MHz); lá nunca
// precisou ser nomeado porque não entra em nenhuma conta em tempo de
// execução daquele lado, só aqui (e agora também no cabeçalho, ver abaixo).
#define PRU_CLOCK_HZ 200000000u

// Nome de arquivo gerado automaticamente quando -o/--saida não é passado:
// "captura_AAAAMMDD_HHMMSS.bin" -- ver gerar_nome_arquivo_automatico().
// Tamanho generoso (a string real tem ~27 bytes incluindo o terminador) para
// nunca chegar perto do limite mesmo com futuras mudanças de formato.
#define TAMANHO_NOME_ARQUIVO_AUTOMATICO 64

// ----------------------------------------------------------------------------
// 'cabecalho_arquivo_campos' lista os campos de verdade, SEM padding. O
// padding para completar exatos 1024 bytes é calculado em TEMPO DE
// COMPILAÇÃO (ver 'cabecalho_arquivo', logo abaixo) a partir de
// sizeof(struct cabecalho_arquivo_campos) -- em vez de contar bytes na mão e
// escrever um array de tamanho fixo "no chute". Já tivemos um problema de
// sincronização manual de tamanho neste projeto (SAMPLES_PER_BUFFER, que
// precisa bater manualmente com o LDI hardcoded em spi_core.asm); a ideia
// aqui é não repetir esse padrão de erro para o cabeçalho -- se um campo for
// adicionado/removido no futuro, o padding se ajusta sozinho, e a
// verificação de tamanho logo abaixo pega em tempo de compilação qualquer
// inconsistência (por exemplo, os campos somados ultrapassando 1024 bytes).
//
// __attribute__((packed)) em AMBAS as structs: sem isso, o compilador
// poderia inserir bytes de padding ENTRE os campos para respeitar o
// alinhamento natural de cada tipo -- o caso mais óbvio aqui é
// 'timestamp_unix' (um uint64_t): os 3 campos anteriores somam 12 bytes, e
// em várias ABIs um uint64_t exige alinhamento de 8 bytes, o que inseriria 4
// bytes de padding invisível antes dele. Esse padding "automático" do
// compilador (a) varia entre arquitetura/ABI e até entre versões de
// compilador, e (b) tornaria o layout binário deste cabeçalho dependente de
// COMO ele foi compilado, não de uma especificação fixa -- inaceitável para
// um formato de arquivo que será lido de volta por outros programas
// (adc_tool.py, uma reimplementação futura em outra linguagem, etc.),
// possivelmente compilados/rodando em outra arquitetura. 'packed' fixa o
// layout em bytes, exatamente na ordem declarada, sem nenhum espaço extra --
// o mesmo raciocínio já aplicado ao formato de amostras brutas do '.bin'
// (sempre 2 bytes por amostra, sem metadado nenhum) e ao layout de
// 'shared_control' em memoria_pru.h (compartilhado por valor entre ARM e
// PRU).
//
// Custo aceito: acesso a um campo desalinhado (ex.: escrever em
// 'timestamp_unix' começando no byte 12, não no 16) pode ser um pouco mais
// lento que um acesso alinhado em alguns processadores -- no Cortex-A8 do
// BeagleBone isso é resolvido em hardware de forma transparente (não gera
// falha, só pode custar ciclos extras). Irrelevante aqui: o cabeçalho é
// montado e gravado UMA ÚNICA VEZ por captura (e reescrito uma segunda vez
// só no final, ver escrita final em main()), bem fora do laço principal de
// aquisição, que sim tem orçamento de tempo apertado.
//
// Convenção de byte order: gravado com o byte order NATIVO da CPU do
// BeagleBone (ARM Cortex-A8, little-endian) -- a mesma convenção já
// assumida pelas amostras brutas do '.bin' e pelo adc_tool.py (dtype numpy
// '<u2'/'<i2', o '<' explícito de little-endian). Um leitor rodando numa
// arquitetura big-endian precisaria converter os campos multi-byte na mão;
// não há necessidade disso hoje, mas vale documentar a suposição.
struct cabecalho_arquivo_campos {
    char     magic[4];                 // "SHAN" -- assinatura fixa, permite a uma ferramenta reconhecer o formato antes de tentar interpretar o resto
    uint32_t versao_cabecalho;         // versão do FORMATO deste cabeçalho (começa em 1) -- não confundir com versão do firmware/software
    uint32_t tamanho_cabecalho;        // bytes totais do cabeçalho (1024) -- gravado explicitamente para um leitor não precisar hardcodar esse número
    uint64_t timestamp_unix;           // segundos desde a epoch Unix (UTC), capturados no início do processamento dos argumentos -- aproximação a poucos milissegundos do início real da varredura do ADC (ainda faltam mmap/configuração do ADS8688 pela frente nesse instante)
    uint32_t frequencia_hz;            // frequência TOTAL de transação SPI pedida via linha de comando -- mesma semântica de -f/--frequencia no adc_tool.py
    uint32_t auto_seq_mask;            // máscara de canais habilitados (bit N = canal N) escrita em shared_control->auto_seq_mask -- ver memoria_pru.h
    uint32_t num_canais;               // popcount de auto_seq_mask -- quantidade de canais habilitados nesta captura
    uint8_t  lista_canais[ADS8688_MAX_CANAIS]; // canais habilitados, em ORDEM CRESCENTE (mesma ordem de varredura do ADS8688 e mesma ordem impressa no console) -- slots não usados (índice >= num_canais) ficam em 0xFF (nunca um canal válido, que é sempre 0-7)
    uint32_t samples_per_buffer;       // SAMPLES_PER_BUFFER no momento da captura -- tamanho de 1 bloco, em amostras BRUTAS intercaladas (não por canal)
    uint32_t bytes_por_amostra;        // largura de cada amostra bruta no '.bin', em bytes (hoje sempre 2 = sizeof(uint16_t))
    uint32_t pru_clock_hz;             // clock da PRU usado para converter Hz -> ciclos (PRU_CLOCK_HZ, hoje 200 MHz) -- permite reconstruir/conferir sample_period_ticks a partir de frequencia_hz sem hardcodar 200 MHz do lado de quem lê
    uint32_t sample_period_ticks;      // valor efetivamente escrito em shared_control->sample_period_ticks para esta captura
    uint32_t primeira_amostra_descartada; // 1 = a primeira amostra bruta de toda a captura foi descartada antes de chegar ao arquivo (comportamento padrão atual, ver main()); reservado para o caso, não implementado hoje, de um firmware futuro mudar isso
    double   duracao_pedida_segundos;  // se --duracao foi usado, a duração pedida em segundos; 0.0 caso contrário (--blocos ou o padrão de 1 bloco)
    uint64_t blocos_gravados;          // preenchido (reescrito) só ao FINAL da captura -- fica 0 enquanto a captura está em andamento, ou se o programa for encerrado (crash, kill -9) antes da reescrita final. uint64_t (não uint32_t) por consistência com blocos_salvos/total_amostras_gravadas, que já são de 64 bits no resto do arquivo -- ver main().
    uint64_t total_amostras_gravadas;  // idem, total de amostras BRUTAS intercaladas gravadas após o descarte da primeira -- equivale a (tamanho_do_arquivo - 1024) / bytes_por_amostra. uint64_t É NECESSÁRIO aqui, não só por consistência: a 500 kSPS contínuos, um uint32_t estouraria em pouco mais de 2 horas de captura.
    char     titulo[CABECALHO_TITULO_TAMANHO];       // [RASTREABILIDADE] --titulo/-t, opcional, texto livre em UTF-8, terminado em '\0'. Não informado -> todos os bytes zerados (string vazia), não lixo -- ver memset(0) da struct inteira em main(). Rejeitado (não truncado) em main() se não couber -- ver comentário lá sobre por que truncar um UTF-8 num limite de bytes arbitrário é arriscado.
    char     descricao[CABECALHO_DESCRICAO_TAMANHO]; // [RASTREABILIDADE] --descricao/-d, mesmas regras de titulo, só que maior -- espaço para uma frase completa sobre o objetivo/contexto do ensaio (ex.: local, o que estava sendo injetado/medido).
    uint8_t  grandeza_por_canal[ADS8688_MAX_CANAIS];             // [SONDA/GRANDEZA, v2] grandeza física de cada canal habilitado (GRANDEZA_TENSAO/CORRENTE/TEMPERATURA) -- mesma indexação de lista_canais (posição i descreve lista_canais[i]); slots não usados = GRANDEZA_NAO_USADA. Sem --grandeza na linha de comando, todo canal assume GRANDEZA_PADRAO (tensão), preservando o comportamento histórico.
    char     sonda_id_por_canal[ADS8688_MAX_CANAIS][CABECALHO_SONDA_ID_TAMANHO]; // [SONDA/GRANDEZA, v2] identificador ASCII da sonda usada em cada canal (--sonda), mesma indexação acima; string vazia = nenhuma sonda associada a este canal. Só a CHAVE de busca -- este programa não valida se o id corresponde a um arquivo de perfil real nem interpreta a curva de calibração; isso é feito inteiramente por adc_tool.py, que é onde os perfis de fato residem (ver docs/proposta_correcao_sonda.md).
    uint32_t header_crc32;             // CRC-32 (polinômio 0xEDB88320, o mesmo de zlib/PNG/Ethernet) de todo o cabeçalho, calculado com este próprio campo zerado -- permite a um leitor detectar um cabeçalho truncado/corrompido antes de confiar nos campos acima
} __attribute__((packed));

struct cabecalho_arquivo {
    struct cabecalho_arquivo_campos campos;
    uint8_t padding[CABECALHO_TAMANHO_TOTAL - sizeof(struct cabecalho_arquivo_campos)];
} __attribute__((packed));

// Verificação em tempo de compilação de que o cabeçalho tem exatos 1024
// bytes -- de propósito NÃO usa _Static_assert (recurso de C11) para não
// depender de um dialeto específico: o Makefile deste projeto compila só
// com "gcc -Wall -O3", sem "-std=", e nenhum lugar do repositório fixa a
// versão do GCC do toolchain da BeagleBone. Um array de tamanho negativo é
// erro de compilação garantido em qualquer dialeto de C, de C89 em diante --
// se a expressão abaixo for falsa, a compilação falha exatamente aqui, com
// uma mensagem apontando para esta linha, em vez de silenciosamente gerar
// um cabeçalho com o tamanho errado.
typedef char verificacao_cabecalho_1024_bytes[
    (sizeof(struct cabecalho_arquivo) == CABECALHO_TAMANHO_TOTAL) ? 1 : -1
];

// ----------------------------------------------------------------------------
// CRC-32 (implementação bit a bit, sem tabela de lookup) -- usado só para o
// cabeçalho de 1024 bytes, duas vezes por captura (uma vez no início, e de
// novo no final, ao reescrever blocos_gravados/total_amostras_gravadas).
// Nesse volume (1024 bytes = 8192 iterações de bit), a versão sem tabela é
// trivialmente rápida e evita carregar uma tabela de 256 uint32_t (1 KB) só
// para esse uso pontual -- bem diferente do laço de aquisição, onde cada
// instrução conta. Polinômio 0xEDB88320 (forma refletida) -- o mesmo usado
// por zlib, PNG e Ethernet (CRC-32/ISO-HDLC).
static uint32_t calcular_crc32(const void *dados, size_t tamanho) {
    const uint8_t *bytes = (const uint8_t *)dados;
    uint32_t crc = 0xFFFFFFFFu;

    for (size_t i = 0; i < tamanho; i++) {
        crc ^= bytes[i];
        for (int bit = 0; bit < 8; bit++) {
            uint32_t mascara = 0u - (crc & 1u); // 0xFFFFFFFF se bit=1, senão 0 -- aritmética unsigned, sempre bem definida (módulo 2^32)
            crc = (crc >> 1) ^ (0xEDB88320u & mascara);
        }
    }
    return ~crc;
}

/*
 * [CABECALHO/NOME DE ARQUIVO] Gera o nome padrão usado quando -o/--saida não
 * é passado na linha de comando: "captura_AAAAMMDD_HHMMSS.bin", a partir do
 * horário LOCAL do sistema no instante em que os argumentos são processados
 * -- conveniente para um humano navegando os arquivos depois. O instante
 * exato e inambíguo (epoch Unix, UTC) fica gravado à parte, no campo
 * timestamp_unix do cabeçalho -- ferramentas de pós-processamento devem
 * usar aquele campo, não tentar reconstruir a data a partir do nome do
 * arquivo (fuso horário do sistema pode mudar).
 *
 * ⚠️ A maioria das BeagleBones não tem RTC com bateria: se a placa não
 * estiver com o relógio sincronizado (NTP, ou ajustado manualmente) no
 * momento da captura, tanto o nome do arquivo quanto timestamp_unix podem
 * refletir um horário incorreto (ex.: próximo da epoch, 1970). Vale
 * conferir `date` antes de um ensaio cujo timestamp importe para o
 * relatório (ex.: validação em bancada, seção 7 do contexto do projeto).
 *
 * 'buffer' precisa ter pelo menos TAMANHO_NOME_ARQUIVO_AUTOMATICO bytes. Em
 * caso de falha (extremamente raro -- localtime_r ou strftime com erro),
 * cai para um nome fixo genérico em vez de deixar 'buffer' com conteúdo
 * indefinido, para nunca abrir um arquivo com um caminho corrompido/não
 * inicializado.
 */
static void gerar_nome_arquivo_automatico(time_t instante, char *buffer, size_t tamanho_buffer) {
    struct tm horario_local;
    if (localtime_r(&instante, &horario_local) == NULL) {
        snprintf(buffer, tamanho_buffer, "captura_sem_timestamp.bin");
        return;
    }

    char parte_data_hora[32];
    if (strftime(parte_data_hora, sizeof(parte_data_hora), "%Y%m%d_%H%M%S", &horario_local) == 0) {
        snprintf(buffer, tamanho_buffer, "captura_sem_timestamp.bin");
        return;
    }

    snprintf(buffer, tamanho_buffer, "captura_%s.bin", parte_data_hora);
}

/*
 * [CONTROLE DE DURAÇÃO DA CAPTURA] --blocos e --duracao (mutuamente
 * exclusivas, validado em main()) controlam por quanto tempo a captura
 * roda antes de fechar o arquivo .bin sozinha:
 *
 *   --blocos N   N > 0 -> captura exatamente N blocos e para (é o
 *                mecanismo "cru": era a única forma de captura antes
 *                desta funcionalidade, sempre com N fixo em 1).
 *                N = 0 -> captura INDEFINIDAMENTE, buffer atrás de
 *                buffer, até o usuário apertar Ctrl+C. SIGINT já é
 *                tratado por lidar_interrupcao(), então o arquivo é
 *                sempre fechado de forma limpa nesse momento -- nunca a
 *                meio de um fwrite() de um bloco em andamento (ver o
 *                laço principal, mais abaixo: só saímos do laço entre um
 *                bloco e outro, nunca durante a gravação de um).
 *
 *   --duracao T  Alternativa mais conveniente a --blocos quando o que
 *                importa é o TEMPO de captura, não o número de blocos em
 *                si (ex.: "quero 10 minutos de dados", sem ter que fazer
 *                a conta manualmente). T aceita um sufixo de unidade
 *                opcional -- 's' (segundos, também o padrão sem sufixo),
 *                'm' (minutos) ou 'h' (horas) -- e valores fracionários
 *                (ex.: '1.5h'). O número de blocos equivalente é
 *                calculado UMA ÚNICA VEZ, antes de abrir o arquivo/
 *                iniciar a captura (ver calcular_blocos_para_duracao),
 *                a partir da frequência total escolhida e de
 *                SAMPLES_PER_BUFFER -- não há monitoramento de relógio de
 *                parede durante a captura em si, só essa conversão
 *                antecipada para um número de blocos, que a partir daí é
 *                tratado exatamente como se tivesse vindo de --blocos.
 *                Arredondado para CIMA: um bloco parcial ainda representa
 *                tempo de captura real pedido pelo usuário, então nunca
 *                descartamos esse resto (melhor capturar um pouco mais
 *                que o pedido do que menos).
 *
 * Sem nenhuma das duas flags, o comportamento é o histórico: BLOCOS_PADRAO
 * (1) bloco.
 */

static void imprimir_uso(const char *nome_programa) {
    fprintf(stderr,
        "Uso: sudo %s <frequencia_hz> [lista_de_canais] [--blocos N | --duracao T] [-o ARQUIVO]\n"
        "\n"
        "  frequencia_hz     Frequência TOTAL de transação SPI, em Hz (1-500000).\n"
        "  lista_de_canais   Opcional. Canais do ADS8688, separados por vírgula\n"
        "                    sem espaços (ex.: '0,1,3'). Padrão: só o canal %d.\n"
        "  --blocos N        Opcional. Captura exatamente N blocos e para. N=0\n"
        "                    captura indefinidamente, até Ctrl+C. Padrão: %d bloco(s).\n"
        "  --duracao T       Opcional, alternativa a --blocos: captura pelo tempo T\n"
        "                    (ex.: '600', '10m', '1.5h' -- sem sufixo = segundos),\n"
        "                    convertido para um número de blocos automaticamente.\n"
        "                    --blocos e --duracao são mutuamente exclusivas.\n"
        "  -o, --saida ARQ   Opcional. Nome do arquivo '.bin' de saída. Sem esta\n"
        "                    flag, um nome é gerado automaticamente a partir do\n"
        "                    horário local, no formato 'captura_AAAAMMDD_HHMMSS.bin'.\n"
        "  -t, --titulo TXT  Opcional. Título curto da captura, gravado no cabeçalho\n"
        "                    (até %u bytes em UTF-8). Sem esta flag, fica vazio.\n"
        "  -d, --descricao TXT  Opcional. Descrição/contexto da captura, gravada no\n"
        "                    cabeçalho (até %u bytes em UTF-8). Sem esta flag, fica\n"
        "                    vazia. Texto maior que o limite é um ERRO (não é\n"
        "                    truncado) -- encurte e tente de novo.\n"
        "  --grandeza C:G[,...] Opcional. Grandeza física medida em cada canal,\n"
        "                    no formato 'canal:grandeza' (ex.:\n"
        "                    '0:tensao,1:corrente,3:corrente'). Valores aceitos:\n"
        "                    'tensao', 'corrente', 'temperatura'. Canal da captura\n"
        "                    não citado aqui assume 'tensao' (padrão histórico).\n"
        "  --sonda C:ID[,...]   Opcional. Identificador da sonda usada em cada\n"
        "                    canal, no formato 'canal:id' (ex.:\n"
        "                    '1:fluke_i30_01'), até %u bytes por id. Aceito em\n"
        "                    qualquer canal (tensão, corrente ou temperatura).\n"
        "                    Gravado só como texto no cabeçalho -- este programa\n"
        "                    NÃO valida se o id corresponde a um perfil real; a\n"
        "                    correção em si é feita por adc_tool.py, na análise.\n"
        "\n"
        "O arquivo gerado começa com um cabeçalho fixo de 1024 bytes (frequência,\n"
        "canais, timestamp, título/descrição, grandeza/sonda por canal e outros\n"
        "metadados da captura) antes das amostras brutas -- ver 'struct\n"
        "cabecalho_arquivo' em ler_adc.c.\n"
        "\n"
        "Exemplos:\n"
        "  sudo %s 102400                        # %d bloco(s), canal %d, nome automático\n"
        "  sudo %s 102400 0,1,3 --blocos 5       # 5 blocos, 3 canais\n"
        "  sudo %s 102400 --blocos 0             # indefinido, até Ctrl+C\n"
        "  sudo %s 102400 --duracao 10m          # ~10 minutos de captura\n"
        "  sudo %s 102400 -o ensaio_bancada.bin  # nome de arquivo explícito\n"
        "  sudo %s 102400 -t \"Medição Condomínio X\" -d \"Busca por supraharmônicos\"\n"
        "  sudo %s 102400 0,1 --grandeza 0:tensao,1:corrente --sonda 1:fluke_i30_01\n",
        nome_programa, CANAL_PADRAO, BLOCOS_PADRAO,
        CABECALHO_TITULO_TAMANHO - 1u, CABECALHO_DESCRICAO_TAMANHO - 1u,
        CABECALHO_SONDA_ID_TAMANHO - 1u,
        nome_programa, BLOCOS_PADRAO, CANAL_PADRAO,
        nome_programa, nome_programa, nome_programa, nome_programa, nome_programa,
        nome_programa);
}

/*
 * [MODO AUTOMÁTICO] Interpreta a lista de canais (ex.: "0,1,3"), separada
 * por vírgulas, sem espaços -- recebida via linha de comando (a posição
 * exata do argumento é resolvida em main(), pelo laço de parsing logo
 * abaixo de argv[2]; não precisa mais ser exatamente argv[2]). Valida:
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

/*
 * [SONDA/GRANDEZA] Traduz um número de canal físico (0-7) para sua POSIÇÃO
 * dentro de 'canais' (a lista já ordenada em ordem crescente, produzida por
 * analisar_lista_canais) -- a mesma indexação usada por lista_canais no
 * cabeçalho, e portanto também por grandeza_por_canal/sonda_id_por_canal.
 * Existe como função separada, em vez de embutir a busca linear em cada
 * chamador, para deixar explícito que --grandeza/--sonda são informados
 * pelo NÚMERO do canal (o que o usuário digitou), não pela posição -- essa
 * tradução evita reproduzir, para estas duas flags novas, a mesma classe de
 * bug de desalinhamento que a ordenação de canais em modo automático já
 * exigiu corrigir uma vez neste projeto (ver docstring de
 * analisar_lista_canais).
 *
 * Retorna a posição (>= 0) se 'canal_alvo' está em 'canais', ou -1 se não
 * está.
 */
static int posicao_do_canal(const int *canais, int num_canais, int canal_alvo) {
    for (int i = 0; i < num_canais; i++) {
        if (canais[i] == canal_alvo) {
            return i;
        }
    }
    return -1;
}

/*
 * [SONDA/GRANDEZA] Interpreta --grandeza (ex.: "0:tensao,1:corrente,3:corrente"),
 * uma lista de pares "canal:grandeza" separados por vírgula, sem espaços.
 * Cada canal citado precisa fazer parte de 'canais' (a lista final, já
 * ordenada, vinda de analisar_lista_canais) -- referenciar um canal fora da
 * captura é erro. Canais da captura que não aparecerem aqui mantêm o valor
 * já presente em 'grandeza_saida' (ver chamador: preenchido com
 * GRANDEZA_PADRAO antes desta função ser chamada), preservando o uso
 * histórico deste programa (nenhuma flag nova = tudo como antes, canal de
 * tensão).
 *
 * 'grandeza_saida' precisa ter pelo menos ADS8688_MAX_CANAIS posições, já
 * indexadas pela MESMA posição que 'canais' usa (posição i descreve
 * canais[i]) -- não pelo número físico do canal (ver posicao_do_canal).
 *
 * Retorna 0 em sucesso, -1 em erro (já reportado em stderr).
 */
static int analisar_lista_grandezas(const char *texto, const int *canais, int num_canais,
                                     uint8_t *grandeza_saida) {
    char copia[512];
    strncpy(copia, texto, sizeof(copia) - 1);
    copia[sizeof(copia) - 1] = '\0';

    char *cursor = copia;
    char *token;
    while ((token = strtok(cursor, ",")) != NULL) {
        cursor = NULL;

        char *dois_pontos = strchr(token, ':');
        if (dois_pontos == NULL) {
            fprintf(stderr, "Erro: '%s' em --grandeza precisa estar no "
                             "formato 'canal:grandeza' (ex.: '0:tensao').\n",
                    token);
            return -1;
        }
        *dois_pontos = '\0';
        const char *parte_canal = token;
        const char *parte_grandeza = dois_pontos + 1;

        char *fim;
        long canal = strtol(parte_canal, &fim, 10);
        if (fim == parte_canal || *fim != '\0') {
            fprintf(stderr, "Erro: '%s' não é um número de canal válido em "
                             "--grandeza.\n", parte_canal);
            return -1;
        }

        int posicao = posicao_do_canal(canais, num_canais, (int)canal);
        if (posicao < 0) {
            fprintf(stderr, "Erro: --grandeza referencia o canal %ld, que "
                             "não faz parte da captura (canais "
                             "selecionados: ", canal);
            for (int i = 0; i < num_canais; i++) {
                fprintf(stderr, "%d%s", canais[i], (i + 1 < num_canais) ? ", " : "");
            }
            fprintf(stderr, ").\n");
            return -1;
        }

        uint8_t valor;
        if (strcmp(parte_grandeza, "tensao") == 0) {
            valor = GRANDEZA_TENSAO;
        } else if (strcmp(parte_grandeza, "corrente") == 0) {
            valor = GRANDEZA_CORRENTE;
        } else if (strcmp(parte_grandeza, "temperatura") == 0) {
            valor = GRANDEZA_TEMPERATURA;
        } else {
            fprintf(stderr, "Erro: grandeza '%s' desconhecida em --grandeza "
                             "(canal %ld) -- use 'tensao', 'corrente' ou "
                             "'temperatura'.\n", parte_grandeza, canal);
            return -1;
        }

        grandeza_saida[posicao] = valor;
    }

    return 0;
}

/*
 * [SONDA/GRANDEZA] Interpreta --sonda (ex.:
 * "1:fluke_i30_01,3:tp_101_sn2"), mesma sintaxe "canal:valor" de
 * --grandeza. Aceito em QUALQUER canal (tensão, corrente ou temperatura) --
 * por pedido explícito, este programa não restringe --sonda a canais de
 * corrente. ler_adc.c também não sabe (nem precisa saber) se o id
 * informado corresponde a um perfil de sonda real: essa validação, e toda a
 * lógica de correção em si, ficam inteiramente do lado Python
 * (adc_tool.py), que é onde os arquivos de perfil de fato existem -- aqui
 * só se grava a string, como uma chave de busca para o outro lado resolver
 * depois (ver docs/proposta_correcao_sonda.md).
 *
 * 'sonda_saida' precisa ter pelo menos ADS8688_MAX_CANAIS linhas de
 * CABECALHO_SONDA_ID_TAMANHO bytes cada, na mesma indexação por posição de
 * 'canais' usada por analisar_lista_grandezas/lista_canais.
 *
 * Retorna 0 em sucesso, -1 em erro (já reportado em stderr) -- o único erro
 * possível aqui é sintaxe ou um id que não cabe no campo de tamanho fixo do
 * cabeçalho (REJEITADO, não truncado -- mesma filosofia já usada para
 * --titulo/--descricao, pela mesma razão: um id truncado na mão poderia
 * colidir silenciosamente com outra sonda de nome parecido).
 */
static int analisar_lista_sondas(const char *texto, const int *canais, int num_canais,
                                  char sonda_saida[][CABECALHO_SONDA_ID_TAMANHO]) {
    char copia[512];
    strncpy(copia, texto, sizeof(copia) - 1);
    copia[sizeof(copia) - 1] = '\0';

    char *cursor = copia;
    char *token;
    while ((token = strtok(cursor, ",")) != NULL) {
        cursor = NULL;

        char *dois_pontos = strchr(token, ':');
        if (dois_pontos == NULL) {
            fprintf(stderr, "Erro: '%s' em --sonda precisa estar no formato "
                             "'canal:id' (ex.: '1:fluke_i30_01').\n",
                    token);
            return -1;
        }
        *dois_pontos = '\0';
        const char *parte_canal = token;
        const char *parte_id = dois_pontos + 1;

        char *fim;
        long canal = strtol(parte_canal, &fim, 10);
        if (fim == parte_canal || *fim != '\0') {
            fprintf(stderr, "Erro: '%s' não é um número de canal válido em "
                             "--sonda.\n", parte_canal);
            return -1;
        }

        int posicao = posicao_do_canal(canais, num_canais, (int)canal);
        if (posicao < 0) {
            fprintf(stderr, "Erro: --sonda referencia o canal %ld, que não "
                             "faz parte da captura (canais selecionados: ",
                    canal);
            for (int i = 0; i < num_canais; i++) {
                fprintf(stderr, "%d%s", canais[i], (i + 1 < num_canais) ? ", " : "");
            }
            fprintf(stderr, ").\n");
            return -1;
        }

        if (parte_id[0] == '\0') {
            fprintf(stderr, "Erro: id de sonda vazio para o canal %ld em "
                             "--sonda.\n", canal);
            return -1;
        }
        if (strlen(parte_id) > CABECALHO_SONDA_ID_TAMANHO - 1u) {
            fprintf(stderr, "Erro: id de sonda '%s' (canal %ld) tem %zu "
                             "bytes, mas o campo do cabeçalho só suporta até "
                             "%u bytes (%u no total, reservando 1 para o "
                             "terminador nulo). Encurte o id.\n",
                    parte_id, canal, strlen(parte_id),
                    CABECALHO_SONDA_ID_TAMANHO - 1u, CABECALHO_SONDA_ID_TAMANHO);
            return -1;
        }

        strncpy(sonda_saida[posicao], parte_id, CABECALHO_SONDA_ID_TAMANHO - 1u);
        sonda_saida[posicao][CABECALHO_SONDA_ID_TAMANHO - 1u] = '\0';
    }

    return 0;
}

/*
 * Interpreta uma duração de captura (--duracao) em segundos. Aceita um
 * sufixo de unidade opcional, sem distinguir maiúsculas/minúsculas: 's'
 * (segundos -- também o padrão quando nenhum sufixo é dado), 'm' (minutos)
 * ou 'h' (horas). Valores fracionários são aceitos (ex.: '1.5h' = 90
 * minutos) -- não há motivo para obrigar o usuário a converter a unidade
 * manualmente, já que a conversão final para blocos arredonda para cima de
 * qualquer forma (ver calcular_blocos_para_duracao).
 *
 * Retorna a duração em segundos (> 0), ou -1.0 em caso de erro (já
 * reportado em stderr).
 */
static double analisar_duracao_em_segundos(const char *texto) {
    char *fim;
    double valor = strtod(texto, &fim);

    if (fim == texto) {
        fprintf(stderr, "Erro: '%s' não é uma duração válida em --duracao "
                         "(use um número, opcionalmente seguido de 's', 'm' "
                         "ou 'h' -- ex.: '600', '10m', '1.5h').\n", texto);
        return -1.0;
    }

    double multiplicador;
    if (*fim == '\0' || ((fim[0] == 's' || fim[0] == 'S') && fim[1] == '\0')) {
        multiplicador = 1.0; // segundos (padrão sem sufixo)
    } else if ((fim[0] == 'm' || fim[0] == 'M') && fim[1] == '\0') {
        multiplicador = 60.0;
    } else if ((fim[0] == 'h' || fim[0] == 'H') && fim[1] == '\0') {
        multiplicador = 3600.0;
    } else {
        fprintf(stderr, "Erro: sufixo de unidade '%s' não reconhecido em "
                         "--duracao='%s' -- use 's' (segundos), 'm' "
                         "(minutos), 'h' (horas), ou nenhum sufixo (assume "
                         "segundos).\n", fim, texto);
        return -1.0;
    }

    double segundos = valor * multiplicador;
    if (segundos <= 0.0) {
        fprintf(stderr, "Erro: --duracao precisa ser um valor positivo "
                         "(recebido: '%s' = %.3f segundo(s)).\n", texto, segundos);
        return -1.0;
    }
    return segundos;
}

/*
 * Converte uma duração (em segundos) para um número de blocos, a partir da
 * frequência TOTAL de transação SPI escolhida e de SAMPLES_PER_BUFFER
 * (fixo, ver memoria_pru.h). Isso NÃO depende do número de canais:
 * SAMPLES_PER_BUFFER conta amostras BRUTAS intercaladas -- o tempo para
 * encher um buffer é sempre SAMPLES_PER_BUFFER / frequencia_desejada,
 * independente de quantos canais estão habilitados (dividir a frequência
 * entre canais é uma consequência da intercalação, não muda quantas
 * amostras brutas totais cabem num buffer nem quanto tempo isso leva).
 *
 * Arredondado para CIMA -- calculado manualmente, sem <math.h>/ceil(), só
 * para não precisar linkar libm no Makefile por causa de uma única
 * chamada. Um bloco parcial ainda representa tempo de captura real pedido
 * pelo usuário, e é preferível capturar um pouco mais do que o pedido a
 * capturar menos. Nunca retorna 0 -- mesmo uma duração muito curta ainda
 * resulta em pelo menos 1 bloco (não existe captura de "menos de 1 bloco"
 * nesta arquitetura de ping-pong).
 */
static unsigned long long calcular_blocos_para_duracao(double segundos,
                                                          uint32_t frequencia_desejada) {
    double segundos_por_bloco = (double)SAMPLES_PER_BUFFER / (double)frequencia_desejada;
    double blocos_exatos = segundos / segundos_por_bloco;

    unsigned long long blocos = (unsigned long long)blocos_exatos;
    if ((double)blocos < blocos_exatos) {
        blocos += 1; // arredonda para cima manualmente
    }
    if (blocos < 1) {
        blocos = 1;
    }
    return blocos;
}

/*
 * Imprime a mensagem de progresso "Bloco X gravado" no formato apropriado
 * para o modo de captura ativo -- com total conhecido (--blocos N > 0,
 * --duracao, ou o padrão) ou indefinido (--blocos 0). Extraído para uma
 * função só para não duplicar essa decisão nos dois blocos quase idênticos
 * (buffer 0 / buffer 1) do laço principal, mais abaixo.
 */
static void imprimir_bloco_gravado(char rotulo, unsigned long long blocos_salvos,
                                    unsigned long long blocos_desejados) {
    if (blocos_desejados == 0) {
        printf("Bloco %c gravado (%llu, captura indefinida -- Ctrl+C para "
               "parar e salvar)\n", rotulo, blocos_salvos);
    } else {
        printf("Bloco %c gravado (%llu/%llu)\n", rotulo, blocos_salvos, blocos_desejados);
    }
}

int main(int argc, char *argv[]) {
    signal(SIGINT, lidar_interrupcao);

    // -h/--help em QUALQUER posição -> mostra o uso e sai, sem exigir
    // frequência nem nenhum outro argumento válido. Checado antes de
    // qualquer outro parsing para não disparar, por exemplo, "frequência
    // inválida" ao rodar só `ler_adc --help`.
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
            imprimir_uso(argv[0]);
            return 0;
        }
    }

    uint32_t frequencia_desejada = 30000;
    if (argc > 1) {
        frequencia_desejada = (uint32_t)atoi(argv[1]);
        if (frequencia_desejada == 0 || frequencia_desejada > 500000) {
            fprintf(stderr, "Erro: frequência inválida. Use um valor entre 1 e 500000 Hz.\n");
            imprimir_uso(argv[0]);
            return -1;
        }
    }

    // argv[2] em diante: um argumento posicional opcional (a lista de
    // canais) e, em qualquer ordem, as flags opcionais --blocos/--duracao
    // e -o/--saida (ver docstrings acima). Nenhuma biblioteca de parsing
    // (getopt etc.) é usada aqui -- mesmo estilo de parsing manual já usado
    // neste arquivo para a lista de canais.
    const char *lista_canais_texto = NULL;
    const char *blocos_texto = NULL;
    const char *duracao_texto = NULL;
    const char *nome_arquivo_texto = NULL; // [CABECALHO/NOME DE ARQUIVO] valor de -o/--saida, se passado
    const char *titulo_texto = NULL;       // [CABECALHO/RASTREABILIDADE] valor de -t/--titulo, se passado
    const char *descricao_texto = NULL;    // [CABECALHO/RASTREABILIDADE] valor de -d/--descricao, se passado
    const char *grandeza_texto = NULL;     // [SONDA/GRANDEZA] valor de --grandeza, se passado
    const char *sonda_texto = NULL;        // [SONDA/GRANDEZA] valor de --sonda, se passado

    for (int i = 2; i < argc; i++) {
        if (strcmp(argv[i], "--blocos") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr, "Erro: --blocos precisa de um valor (ex.: "
                                 "--blocos 3, ou --blocos 0 para captura "
                                 "indefinida).\n");
                return -1;
            }
            blocos_texto = argv[++i];
        } else if (strcmp(argv[i], "--duracao") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr, "Erro: --duracao precisa de um valor (ex.: "
                                 "--duracao 600, --duracao 10m, --duracao "
                                 "1.5h).\n");
                return -1;
            }
            duracao_texto = argv[++i];
        } else if (strcmp(argv[i], "-o") == 0 || strcmp(argv[i], "--saida") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr, "Erro: %s precisa de um nome de arquivo "
                                 "(ex.: -o captura.bin).\n", argv[i]);
                return -1;
            }
            nome_arquivo_texto = argv[++i];
            if (nome_arquivo_texto[0] == '\0') {
                fprintf(stderr, "Erro: nome de arquivo vazio em -o/--saida.\n");
                return -1;
            }
        } else if (strcmp(argv[i], "-t") == 0 || strcmp(argv[i], "--titulo") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr, "Erro: %s precisa de um valor (ex.: -t "
                                 "\"Medição Condomínio X\").\n", argv[i]);
                return -1;
            }
            titulo_texto = argv[++i];
        } else if (strcmp(argv[i], "-d") == 0 || strcmp(argv[i], "--descricao") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr, "Erro: %s precisa de um valor (ex.: -d "
                                 "\"Busca por supraharmônicos\").\n", argv[i]);
                return -1;
            }
            descricao_texto = argv[++i];
        } else if (strcmp(argv[i], "--grandeza") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr, "Erro: --grandeza precisa de um valor (ex.: "
                                 "--grandeza 0:tensao,1:corrente).\n");
                return -1;
            }
            grandeza_texto = argv[++i];
        } else if (strcmp(argv[i], "--sonda") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr, "Erro: --sonda precisa de um valor (ex.: "
                                 "--sonda 1:fluke_i30_01).\n");
                return -1;
            }
            sonda_texto = argv[++i];
        } else if (argv[i][0] == '-') {
            fprintf(stderr, "Erro: opção desconhecida '%s'.\n", argv[i]);
            imprimir_uso(argv[0]);
            return -1;
        } else if (lista_canais_texto == NULL) {
            lista_canais_texto = argv[i];
        } else {
            fprintf(stderr, "Erro: argumento posicional inesperado '%s' -- "
                             "a lista de canais já foi informada como "
                             "'%s'.\n", argv[i], lista_canais_texto);
            return -1;
        }
    }

    if (blocos_texto != NULL && duracao_texto != NULL) {
        fprintf(stderr, "Erro: --blocos e --duracao são mutuamente "
                         "exclusivas -- escolha só uma forma de controlar a "
                         "duração da captura.\n");
        return -1;
    }

    // argv[2] (agora lista_canais_texto), opcional: lista de canais a
    // amostrar, ex. "0,1,3" (sem espaços). Sem esse argumento, mantém o
    // comportamento histórico deste programa: um canal só, o canal 1
    // (CANAL_PADRAO). A ordem final impressa/usada é sempre crescente --
    // ver analisar_lista_canais().
    int canais[ADS8688_MAX_CANAIS];
    int num_canais;
    if (lista_canais_texto != NULL) {
        num_canais = analisar_lista_canais(lista_canais_texto, canais);
        if (num_canais < 0) {
            return -1; // erro já reportado em stderr por analisar_lista_canais
        }
    } else {
        num_canais = 1;
        canais[0] = CANAL_PADRAO;
    }

    // [SONDA/GRANDEZA] Resolvido logo após 'canais'/'num_canais' -- ambas as
    // flags são expressas em NÚMERO de canal (analisar_lista_grandezas/
    // analisar_lista_sondas traduzem para posição internamente), então
    // dependem da lista final já validada e ordenada. Mesma filosofia de
    // "validar primeiro, tocar hardware/disco depois" do resto do arquivo.
    //
    // grandeza_canais começa com GRANDEZA_NAO_USADA em todo slot (mesmo
    // sentinela de lista_canais), depois GRANDEZA_PADRAO só nos slots
    // realmente usados por esta captura (0..num_canais) -- --grandeza, se
    // passado, sobrescreve a partir daí. sonda_canais começa vazio (nenhuma
    // sonda associada) em todo canal; --sonda, se passado, preenche.
    uint8_t grandeza_canais[ADS8688_MAX_CANAIS];
    char sonda_canais[ADS8688_MAX_CANAIS][CABECALHO_SONDA_ID_TAMANHO];
    memset(grandeza_canais, GRANDEZA_NAO_USADA, sizeof(grandeza_canais));
    memset(sonda_canais, 0, sizeof(sonda_canais));
    for (int i = 0; i < num_canais; i++) {
        grandeza_canais[i] = GRANDEZA_PADRAO;
    }
    if (grandeza_texto != NULL) {
        if (analisar_lista_grandezas(grandeza_texto, canais, num_canais, grandeza_canais) < 0) {
            return -1; // erro já reportado em stderr por analisar_lista_grandezas
        }
    }
    if (sonda_texto != NULL) {
        if (analisar_lista_sondas(sonda_texto, canais, num_canais, sonda_canais) < 0) {
            return -1; // erro já reportado em stderr por analisar_lista_sondas
        }
    }

    // Resolve blocos_desejados cedo (antes de tocar em /dev/mem ou criar o
    // arquivo de saída) -- mesma filosofia de "validar primeiro, tocar
    // hardware/disco depois" já seguida no resto deste programa.
    double duracao_pedida_segundos = 0.0; // [CABECALHO] 0.0 quando --duracao não é usado; gravado no cabeçalho para referência futura da captura
    unsigned long long blocos_desejados = BLOCOS_PADRAO;
    if (blocos_texto != NULL) {
        char *fim;
        long long valor = strtoll(blocos_texto, &fim, 10);
        if (fim == blocos_texto || *fim != '\0') {
            fprintf(stderr, "Erro: '%s' não é um número de blocos válido em "
                             "--blocos.\n", blocos_texto);
            return -1;
        }
        if (valor < 0) {
            fprintf(stderr, "Erro: --blocos não pode ser negativo (use 0 "
                             "para captura indefinida, até Ctrl+C).\n");
            return -1;
        }
        blocos_desejados = (unsigned long long)valor;
    } else if (duracao_texto != NULL) {
        duracao_pedida_segundos = analisar_duracao_em_segundos(duracao_texto);
        if (duracao_pedida_segundos < 0.0) {
            return -1; // erro já reportado por analisar_duracao_em_segundos
        }
        blocos_desejados = calcular_blocos_para_duracao(duracao_pedida_segundos, frequencia_desejada);
        double segundos_por_bloco = (double)SAMPLES_PER_BUFFER / (double)frequencia_desejada;
        printf("Duração pedida: %.3f s -> %llu bloco(s) "
               "(%.3f s de captura real, %.3f s/bloco a %u Hz total).\n",
               duracao_pedida_segundos, blocos_desejados,
               (double)blocos_desejados * segundos_por_bloco, segundos_por_bloco,
               frequencia_desejada);
    }

    // [CABECALHO/NOME DE ARQUIVO] Resolvido cedo (antes de tocar em
    // /dev/mem ou criar o arquivo de saída) -- mesma filosofia de "validar
    // primeiro, tocar hardware/disco depois". O mesmo instante capturado
    // aqui é usado tanto para gerar o nome automático do arquivo (se
    // -o/--saida não foi passado) quanto para o campo timestamp_unix do
    // cabeçalho, mais abaixo -- uma única fonte de verdade para "quando
    // esta captura começou".
    time_t instante_captura = time(NULL);

    char nome_arquivo_automatico[TAMANHO_NOME_ARQUIVO_AUTOMATICO];
    const char *nome_arquivo_saida;
    if (nome_arquivo_texto != NULL) {
        nome_arquivo_saida = nome_arquivo_texto;
    } else {
        gerar_nome_arquivo_automatico(instante_captura, nome_arquivo_automatico,
                                       sizeof(nome_arquivo_automatico));
        nome_arquivo_saida = nome_arquivo_automatico;
    }

    // [CABECALHO/RASTREABILIDADE] Valida o tamanho de --titulo/--descricao
    // cedo -- mesma filosofia de "validar primeiro, tocar hardware/disco
    // depois" já seguida no resto deste programa. REJEITA (em vez de
    // truncar) quando o texto não cabe no campo de tamanho fixo do
    // cabeçalho: truncar uma string em UTF-8 num limite de bytes arbitrário
    // arrisca cortar no meio de uma sequência multibyte, gravando UTF-8
    // inválido no arquivo -- rejeitar evita esse problema por completo, e é
    // consistente com a filosofia deste programa de falhar alto em vez de
    // silenciosamente corromper/truncar dados (mesmo espírito da checagem
    // de retorno de fwrite() no laço principal, mais abaixo). strlen() mede
    // bytes, não "caracteres"/pontos de código -- exatamente o que importa
    // aqui, já que o campo do cabeçalho tem um limite em BYTES; argv já
    // chega do shell como os bytes brutos em UTF-8, sem nenhuma decodificação
    // necessária ou possível neste nível.
    if (titulo_texto != NULL && strlen(titulo_texto) > CABECALHO_TITULO_TAMANHO - 1u) {
        fprintf(stderr, "Erro: --titulo tem %zu bytes (em UTF-8), mas o "
                         "campo do cabeçalho só suporta até %u bytes de "
                         "texto (%u no total, reservando 1 para o "
                         "terminador nulo). Encurte o título.\n",
                strlen(titulo_texto), CABECALHO_TITULO_TAMANHO - 1u, CABECALHO_TITULO_TAMANHO);
        return -1;
    }
    if (descricao_texto != NULL && strlen(descricao_texto) > CABECALHO_DESCRICAO_TAMANHO - 1u) {
        fprintf(stderr, "Erro: --descricao tem %zu bytes (em UTF-8), mas o "
                         "campo do cabeçalho só suporta até %u bytes de "
                         "texto (%u no total, reservando 1 para o "
                         "terminador nulo). Encurte a descrição.\n",
                strlen(descricao_texto), CABECALHO_DESCRICAO_TAMANHO - 1u, CABECALHO_DESCRICAO_TAMANHO);
        return -1;
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
    ctrl->sample_period_ticks = PRU_CLOCK_HZ / frequencia_desejada;

    // [MODO AUTOMÁTICO] Escreve a máscara ANTES de sinalizar config_ready=1
    // -- mesmo cuidado de ordenação já usado para buffer_0_addr/
    // buffer_1_addr acima: a PRU só lê auto_seq_mask depois de ver
    // config_ready=1 (ver espera_configuracao em spi_core.asm).
    ctrl->auto_seq_mask = mascara_auto_seq;

    ctrl->config_ready = 1;

    FILE *ficheiro_bin = fopen(nome_arquivo_saida, "wb");
    if (!ficheiro_bin) {
        fprintf(stderr, "Erro ao criar '%s': %s\n", nome_arquivo_saida, strerror(errno));
        munmap(ddr_map, bytes_por_buffer * 2);
        munmap(ctrl_map, 4096);
        close(mem_fd);
        return -1;
    }

    // [CABECALHO/NOME DE ARQUIVO] Monta e grava o cabeçalho de 1024 bytes
    // UMA ÚNICA VEZ, logo após abrir o arquivo e ANTES de qualquer amostra
    // -- blocos_gravados/total_amostras_gravadas ficam zerados aqui (ainda
    // não sabemos o total final) e são reescritos no MESMO offset (0) só
    // depois que o laço principal terminar, ver o fim de main(). memset a
    // zero primeiro para que os bytes de padding (e qualquer campo não
    // preenchido explicitamente) sejam determinísticos -- sem isso, o
    // padding conteria lixo de pilha não inicializado, tornando o CRC (e o
    // próprio arquivo) não reprodutível entre execuções com os mesmos
    // parâmetros.
    struct cabecalho_arquivo cabecalho;
    memset(&cabecalho, 0, sizeof(cabecalho));

    memcpy(cabecalho.campos.magic, CABECALHO_MAGIC, sizeof(cabecalho.campos.magic));
    cabecalho.campos.versao_cabecalho = CABECALHO_VERSAO;
    cabecalho.campos.tamanho_cabecalho = (uint32_t)sizeof(cabecalho);
    cabecalho.campos.timestamp_unix = (uint64_t)instante_captura;
    cabecalho.campos.frequencia_hz = frequencia_desejada;
    cabecalho.campos.auto_seq_mask = mascara_auto_seq;
    cabecalho.campos.num_canais = (uint32_t)num_canais;

    memset(cabecalho.campos.lista_canais, 0xFF, sizeof(cabecalho.campos.lista_canais));
    for (int i = 0; i < num_canais; i++) {
        cabecalho.campos.lista_canais[i] = (uint8_t)canais[i];
    }

    // [SONDA/GRANDEZA] grandeza_canais/sonda_canais já vêm prontos (com os
    // sentinelas/padrões corretos nos slots não usados) de mais acima --
    // só copiar para dentro da struct do cabeçalho.
    memcpy(cabecalho.campos.grandeza_por_canal, grandeza_canais, sizeof(grandeza_canais));
    memcpy(cabecalho.campos.sonda_id_por_canal, sonda_canais, sizeof(sonda_canais));

    cabecalho.campos.samples_per_buffer = (uint32_t)SAMPLES_PER_BUFFER;
    cabecalho.campos.bytes_por_amostra = (uint32_t)sizeof(uint16_t);
    cabecalho.campos.pru_clock_hz = PRU_CLOCK_HZ;
    cabecalho.campos.sample_period_ticks = ctrl->sample_period_ticks;
    cabecalho.campos.primeira_amostra_descartada = 1u;
    cabecalho.campos.duracao_pedida_segundos = duracao_pedida_segundos;
    cabecalho.campos.blocos_gravados = 0;         // preenchido no final, ver fim de main()
    cabecalho.campos.total_amostras_gravadas = 0; // idem

    // [CABECALHO/RASTREABILIDADE] titulo/descricao já ficaram zerados (todos
    // os bytes) pelo memset(&cabecalho, 0, ...) logo acima -- se
    // titulo_texto/descricao_texto forem NULL (flag não passada), os campos
    // simplesmente permanecem como estão: strings vazias, não lixo. Quando
    // passados, o tamanho já foi validado mais acima (rejeitado se não
    // coubesse), então o memcpy abaixo -- incluindo o '\0' final -- nunca
    // ultrapassa os limites de titulo[]/descricao[]. O restante de cada
    // array (depois do '\0') continua zerado, do memset inicial.
    if (titulo_texto != NULL) {
        memcpy(cabecalho.campos.titulo, titulo_texto, strlen(titulo_texto) + 1);
    }
    if (descricao_texto != NULL) {
        memcpy(cabecalho.campos.descricao, descricao_texto, strlen(descricao_texto) + 1);
    }

    cabecalho.campos.header_crc32 = 0; // zerado durante o próprio cálculo do CRC
    cabecalho.campos.header_crc32 = calcular_crc32(&cabecalho, sizeof(cabecalho));

    if (fwrite(&cabecalho, sizeof(cabecalho), 1, ficheiro_bin) != 1) {
        fprintf(stderr, "Erro: falha ao gravar o cabeçalho (%zu bytes) em "
                         "'%s'.\n", sizeof(cabecalho), nome_arquivo_saida);
        fclose(ficheiro_bin);
        munmap(ddr_map, bytes_por_buffer * 2);
        munmap(ctrl_map, 4096);
        close(mem_fd);
        return -1;
    }

    printf("Cabeçalho gravado (%zu bytes) em '%s' | magic=%.4s versao=%u | "
           "timestamp_unix=%llu | crc32=0x%08X\n",
           sizeof(cabecalho), nome_arquivo_saida, cabecalho.campos.magic,
           cabecalho.campos.versao_cabecalho,
           (unsigned long long)cabecalho.campos.timestamp_unix,
           cabecalho.campos.header_crc32);
    printf("  Título: %s\n", (titulo_texto != NULL) ? cabecalho.campos.titulo : "(não informado)");
    printf("  Descrição: %s\n", (descricao_texto != NULL) ? cabecalho.campos.descricao : "(não informada)");

    printf("Frequência total (taxa de transação SPI): %u Hz | "
           "SAMPLES_PER_BUFFER=%d | ticks=%u\n",
           frequencia_desejada, SAMPLES_PER_BUFFER, ctrl->sample_period_ticks);

    printf("Canais selecionados (%d), em ordem crescente -- a varredura "
           "automática do ADS8688 sempre segue essa ordem, "
           "independente de como foram digitados: ", num_canais);
    for (int i = 0; i < num_canais; i++) {
        printf("%d%s", canais[i], (i + 1 < num_canais) ? ", " : "\n");
    }

    printf("Grandeza/sonda por canal:\n");
    for (int i = 0; i < num_canais; i++) {
        const char *nome_grandeza;
        switch (grandeza_canais[i]) {
            case GRANDEZA_TENSAO:      nome_grandeza = "tensao"; break;
            case GRANDEZA_CORRENTE:    nome_grandeza = "corrente"; break;
            case GRANDEZA_TEMPERATURA: nome_grandeza = "temperatura"; break;
            default:                   nome_grandeza = "desconhecida"; break;
        }
        if (sonda_canais[i][0] != '\0') {
            printf("  Canal %d: %s (sonda: %s)\n", canais[i], nome_grandeza, sonda_canais[i]);
        } else {
            printf("  Canal %d: %s\n", canais[i], nome_grandeza);
        }
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
               "O .bin gerado tem um cabeçalho de 1024 bytes seguido pelas "
               "amostras (ver mensagem de cabeçalho acima), então o "
               "adc_tool.py precisa pular esses bytes e receber essa mesma "
               "lista/ordem via --canais para desintercalar corretamente.\n",
               num_canais);
    }

    printf("A primeira amostra bruta de toda a captura é sempre descartada "
           "antes de chegar no arquivo (dado residual do ADS8688 anterior "
           "ao início real da varredura -- ver comentário no laço de "
           "captura abaixo).\n");

    if (blocos_desejados == 0) {
        printf("Capturando indefinidamente -- pressione Ctrl+C para parar e "
               "salvar o arquivo...\n");
    } else {
        printf("Capturando %llu bloco(s) e encerrando automaticamente...\n",
               blocos_desejados);
    }

    unsigned long long blocos_salvos = 0;
    unsigned long long total_amostras_gravadas = 0; // [CABECALHO] soma de amostras brutas efetivamente gravadas (pós-descarte) -- preenchido no cabeçalho final

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

    while (manter_execucao && (blocos_desejados == 0 || blocos_salvos < blocos_desejados)) {
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
                total_amostras_gravadas += gravado;
                imprimir_bloco_gravado('A', blocos_salvos, blocos_desejados);
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
                total_amostras_gravadas += gravado;
                imprimir_bloco_gravado('B', blocos_salvos, blocos_desejados);
            }
        }
        usleep(2000);
    }

    printf("Captura concluída: %s (%llu bloco(s) gravado(s))\n",
           nome_arquivo_saida, blocos_salvos);

    // [CABECALHO/NOME DE ARQUIVO] Reescreve o cabeçalho no INÍCIO do
    // arquivo, agora preenchendo blocos_gravados/total_amostras_gravadas
    // (que ficaram zerados na primeira gravação, acima) com os valores
    // finais reais, e recalculando o CRC sobre o cabeçalho já atualizado.
    // Só acontece aqui, DEPOIS que o laço principal já terminou -- não
    // introduz nenhum atraso adicional no caminho crítico de gravação dos
    // blocos. Tratado como um "melhor esforço": se o fseek/fwrite falhar,
    // avisa mas não retorna erro -- as amostras em si já estão gravadas e
    // íntegras nesse ponto, só os 2 campos de resumo do cabeçalho é que
    // ficariam desatualizados (em 0).
    cabecalho.campos.blocos_gravados = blocos_salvos;
    cabecalho.campos.total_amostras_gravadas = total_amostras_gravadas;
    cabecalho.campos.header_crc32 = 0;
    cabecalho.campos.header_crc32 = calcular_crc32(&cabecalho, sizeof(cabecalho));

    if (fseek(ficheiro_bin, 0, SEEK_SET) != 0) {
        fprintf(stderr, "Aviso: não foi possível reposicionar '%s' para "
                         "reescrever o cabeçalho final (%s) -- os campos "
                         "blocos_gravados/total_amostras_gravadas do "
                         "cabeçalho ficaram com o valor inicial (0); as "
                         "amostras gravadas continuam íntegras.\n",
                nome_arquivo_saida, strerror(errno));
    } else if (fwrite(&cabecalho, sizeof(cabecalho), 1, ficheiro_bin) != 1) {
        fprintf(stderr, "Aviso: falha ao reescrever o cabeçalho final em "
                         "'%s' -- as amostras gravadas continuam íntegras, "
                         "mas os campos blocos_gravados/"
                         "total_amostras_gravadas do cabeçalho podem ter "
                         "ficado com o valor inicial (0).\n", nome_arquivo_saida);
    } else {
        printf("Cabeçalho final atualizado: blocos_gravados=%llu | "
               "total_amostras_gravadas=%llu\n",
               blocos_salvos, total_amostras_gravadas);
    }

    fclose(ficheiro_bin);
    munmap(ddr_map, bytes_por_buffer * 2);
    munmap(ctrl_map, 4096);
    close(mem_fd);
    return 0;
}
