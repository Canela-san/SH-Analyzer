.global ler_ads8688_asm
    .sect ".text"

; ==============================================================================
; SPI_CORE - VERSÃO DE PRODUÇÃO (validada em hardware)
; ==============================================================================
; Histórico resumido do que foi validado experimentalmente até chegar aqui:
;   - Frame de 32 ciclos de SCLK por amostra (16 para escrever o comando de
;     canal + 16 para ler o dado da conversão anterior), conforme datasheet
;     SBAS582 do ADS8688.
;   - Comando enviado a cada frame: MAN_Ch_1 (0xC400) - o canal 1, que é o
;     que está de fato conectado a um sinal válido nesta placa (o canal 0
;     ficava sempre saturado em fundo de escala, mesmo com a comunicação SPI
;     comprovadamente correta - ver histórico de depuração).
;   - Escrita do bit de MOSI feita com desvio condicional (QBBC), replicando
;     o if/else do firmware original em C (teste_spi_pru.c) - a versão
;     "branchless" com deslocamentos/máscaras não deu certo na prática.
;   - Amostragem do MISO no ÚLTIMO instante seguro antes da borda de DESCIDA
;     do SCLK (máximo tempo de acomodação do sinal dentro do período em que
;     o SCLK está alto) - foi essa mudança (mais a de cima) que resolveu a
;     leitura presa em fundo de escala.
;   - CS/SCLK/MOSI inicializados em repouso antes do laço principal.
;   - Registrador CYCLE da PRU é ressincronizado no início da aquisição e a
;     cada troca de buffer (ele trava em vez de dar a volta ao estourar
;     32 bits, ~21,47 s a 200 MHz).
;   - Margens de tempo em torno do CS (setup, hold, e tempo mínimo em nível
;     alto entre transações) mantidas como no arquivo validado.
;   - Preâmbulo (r5, capturado durante o CMD_BIT) é usado só para manter o
;     timing simétrico com o DATA_BIT - NUNCA é gravado na DDR. A única
;     escrita em memória do laço principal é "SBBO &r23, r19, 0, 2", ou
;     seja, só os 16 bits de dado real da amostra (2 bytes/amostra). A
;     captura do preâmbulo para diagnóstico (arquivo *_diagnostico_*.asm,
;     separado deste) não faz parte do fluxo de produção.
;
;   - [MULTI-CANAL] O comando de canal enviado a cada frame (r28) deixou de
;     ser fixo em MAN_Ch_1 (0xC4000000) e passou a vir de uma tabela em RAM
;     compartilhada (ctrl->comandos_canais[], escrita pelo ARM em
;     ler_adc.c), percorrida em round-robin por um índice (r6) que nunca é
;     reiniciado na troca de buffer -- só ao dar a volta em num_canais
;     (r7). Ver o bloco logo após espera_configuracao, e o trecho que
;     substitui o antigo "LDI32 r28, 0xC4000000" dentro de laco_principal.
;     IMPORTANTE (não removido daqui de propósito, é crítico para
;     entender o dado): o ADS8688 em modo manual devolve em cada frame o
;     resultado da conversão do comando enviado no frame ANTERIOR, não do
;     comando enviado agora. Com 1 canal só isso é invisível (o canal
;     nunca muda). Com vários canais intercalados, isso desalinharia em
;     1 posição a correspondência (posição no arquivo) <-> (canal) -- a
;     correção para isso foi feita DELIBERADAMENTE do lado do ARM
;     (descartando a primeiríssima amostra de toda a captura, ver
;     ler_adc.c), e não aqui, para não precisar duplicar mais um trecho
;     de código de transação SPI bit-a-bit e pressionar ainda mais os
;     8 KB de PRU_IMEM (ver nota no README sobre esse limite). Se um dia
;     esta rotina for alterada para não chamar mais o ARM de "dono" desse
;     alinhamento, lembre-se desse detalhe.
; ==============================================================================
; PINOS:
;   Bit 0 (r30) = SCLK   | Bit 1 (r30) = SDI/MOSI
;   Bit 2 (r31) = SDO/MISO | Bit 3 (r30) = CS
; ==============================================================================
; REGISTRADORES NOVOS (round-robin de canais, ver bloco de setup e
; laco_principal): r6 = índice do canal atual (0..num_canais-1, persiste
; durante toda a captura, NÃO é resetado na troca de buffer); r7 =
; num_canais (lido uma vez, constante durante a captura); r9 = endereço
; base de ctrl->comandos_canais[]; r8 = registrador de rascunho (scratch)
; usado só para calcular o endereço efetivo dentro do array a cada
; iteração.
; ==============================================================================

; ==============================================================================
; MACRO: Escreve 1 bit de comando no SDI (Ciclos 1-16 do frame do ADS8688)
; r28 = registrador de comando (deslocado a cada chamada, MSB no bit 31)
; ==============================================================================
CMD_BIT .macro
    ; 1. Configura o MOSI testando o bit 31 (igual ao if/else do C validado)
    QBBC limpa_mosi?, r28, 31
    SET r30, r30, 1          ; bit 31 = 1 -> MOSI alto
    QBA mosi_pronto?
limpa_mosi?:
    CLR r30, r30, 1          ; bit 31 = 0 -> MOSI baixo
mosi_pronto?:
    LSL r28, r28, 1          ; Desloca para o próximo bit

    NOP
    NOP
    NOP

    SET r30, r30, 0          ; Sobe o SCLK

    NOP
    NOP
    NOP
    NOP
    NOP
    NOP                      ; Acomodação máxima antes da borda de descida

    ; NOTA: este bloco não faz nada útil com o resultado (r5 é descartado) -
    ; ele existe só para manter o CMD_BIT com EXATAMENTE a mesma duração do
    ; DATA_BIT em nível ALTO do SCLK, igual estava na versão validada em
    ; hardware (lá esse bloco capturava o preâmbulo de diagnóstico, na
    ; mesma posição, logo antes de descer o SCLK). Remover essa simetria
    ; encurtou justo a margem de acomodação/aquisição antes da borda de
    ; descida, e é a suspeita mais provável para a distorção de 2x/período
    ; relatada (a taxa de variação do sinal é máxima nos cruzamentos por
    ; zero, onde essa margem apertada mais afetaria a leitura).
    LSL r5, r5, 1
    QBBC pula_descarte?, r31, 2
    OR r5, r5, 1
pula_descarte?:

    CLR r30, r30, 0          ; Desce o SCLK -> ADC lê o bit no SDI

    NOP
    NOP
    NOP
    .endm

; ==============================================================================
; MACRO: Lê 1 bit de dado do SDO (Ciclos 17-32 do frame do ADS8688)
; r23 = acumulador de 16 bits da amostra
; ==============================================================================
DATA_BIT .macro
    NOP
    NOP
    NOP

    SET r30, r30, 0          ; Sobe o SCLK

    NOP
    NOP
    NOP
    NOP
    NOP
    NOP                      ; Acomodação máxima antes da amostragem

    ; Amostra o MISO no ÚLTIMO instante seguro, logo antes de descer o SCLK
    LSL r23, r23, 1
    QBBC pula_dado?, r31, 2
    OR r23, r23, 1
pula_dado?:

    CLR r30, r30, 0          ; Desce o SCLK

    NOP
    NOP
    NOP
    .endm

; ==============================================================================
; ASSINATURA: void ler_ads8688_asm(volatile struct shared_control *ctrl)
; r14 = Ponteiro base da struct shared_control (0x00010000)
; ==============================================================================
ler_ads8688_asm:
    SET r30, r30, 3   ; CS alto (desselecionado)
    CLR r30, r30, 0   ; SCLK baixo
    CLR r30, r30, 1   ; MOSI baixo

    ; Monta o endereço físico do Cycle Counter (0x2200C) no registrador r18
    LDI r18.w0, 0x200C
    LDI r18.w2, 0x0002

    ; Limite do buffer: 1.048.576 amostras (2 MB por buffer)
    LDI r21.w0, 0x0000
    LDI r21.w2, 0x0010   ; 0x00100000 em Hex = 1.048.576

espera_configuracao:
    LBBO &r20, r14, 24, 4
    QBEQ espera_configuracao, r20, 0

    ; Zera o contador de ciclos agora, no momento real em que a aquisição
    ; começa (ver histórico: CYCLE trava ao estourar, não dá a volta).
    LDI r20, 0
    SBBO &r20, r18, 0, 4

    LBBO &r16, r14, 0, 4  ; r16 = sample_period_ticks
    LBBO &r24, r14, 16, 4 ; r24 = buffer_0_addr
    LBBO &r25, r14, 20, 4 ; r25 = buffer_1_addr

    ; [MULTI-CANAL] Config de canais: lida uma única vez aqui, fora do
    ; laço - não muda durante o resto da captura (ao contrário de r16,
    ; que é relido a cada iteração dentro de laco_principal para permitir
    ; ajuste dinâmico de frequência). r9 fica com o endereço BASE do array
    ; (ctrl + 32); o índice de canal r6 começa em 0 e nunca é reiniciado
    ; depois disso, nem mesmo na troca de buffer (ver "continua:" mais
    ; abaixo) - só dá a volta ao chegar em r7 (num_canais).
    LBBO &r7, r14, 28, 4   ; r7 = num_canais
    ADD r9, r14, 32        ; r9 = endereço base de ctrl->comandos_canais[]
    LDI r6, 0               ; r6 = índice do canal atual

    MOV r19, r24
    LDI r15, 0
    LDI r26, 0

    MOV r17, r16           ; r17 = next_sample_time = 0 + período

laco_principal:
    LBBO &r16, r14, 0, 4

wait_time:
    LBBO &r22, r18, 0, 4
    SUB r20, r17, r22
    QBBC wait_time, r20, 31

    ADD r17, r17, r16

    ; --- TRANSAÇÃO SPI (32 CICLOS) ---
    CLR r30, r30, 3         ; Abaixa o CS

    LDI r1, 200
delay_cs_setup:
    SUB r1, r1, 1
    QBNE delay_cs_setup, r1, 0

    LDI r23, 0

    ; [MULTI-CANAL] r28 = ctrl->comandos_canais[r6] (substitui o antigo
    ; "LDI32 r28, 0xC4000000" fixo em MAN_Ch_1 - ver nota no cabeçalho do
    ; arquivo). Endereço efetivo calculado em 2 passos (em vez de
    ; endereçamento indexado por registrador direto no LBBO) para não
    ; depender de um modo de endereçamento cujo suporte eu não conseguiria
    ; validar aqui sem o compilador clpru à mão - só usa a mesma forma
    ; "base + deslocamento constante (0)" já comprovada no resto do
    ; arquivo.
    LSL r8, r6, 2            ; r8 = índice_canal * 4 (bytes por entrada)
    ADD r8, r8, r9           ; r8 = endereço efetivo de comandos_canais[r6]
    LBBO &r28, r8, 0, 4      ; r28 = comando de 32 bits do canal atual

    CMD_BIT
    CMD_BIT
    CMD_BIT
    CMD_BIT
    CMD_BIT
    CMD_BIT
    CMD_BIT
    CMD_BIT
    CMD_BIT
    CMD_BIT
    CMD_BIT
    CMD_BIT
    CMD_BIT
    CMD_BIT
    CMD_BIT
    CMD_BIT

    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT

    LDI r1, 100
delay_cs_hold:
    SUB r1, r1, 1
    QBNE delay_cs_hold, r1, 0

    SET r30, r30, 3          ; Levanta o CS - fim da transação

    ; Tempo mínimo de CS alto entre transações (recarga do capacitor interno
    ; de amostragem do ADS8688), independente da frequência configurada.
    LDI r1, 100
delay_cs_high_minimo:
    SUB r1, r1, 1
    QBNE delay_cs_high_minimo, r1, 0

    ; --- GRAVAÇÃO DIRETA NA MEMÓRIA DDR ---
    SBBO &r23, r19, 0, 2
    ADD r19, r19, 2

    ; --- AVANÇA O ÍNDICE DE CANAL (round-robin) ---
    ; Roda de forma totalmente independente da lógica de ping-pong logo
    ; abaixo: r6 SÓ dá a volta ao chegar em num_canais (r7), nunca é
    ; tocado pela troca de buffer. Isso é o que garante que a
    ; correspondência (posição da amostra no arquivo final, concatenando
    ; todos os buffers) <-> canal se mantenha em fase por toda a captura,
    ; mesmo com SAMPLES_PER_BUFFER não sendo múltiplo de num_canais (ex.:
    ; 1.048.576 amostras não é múltiplo de 3). Instruções fora da janela
    ; de timing crítico do SCLK (acontecem depois do CS já ter subido, na
    ; folga entre transações), então não afetam o timing bit-a-bit
    ; validado em hardware.
    ADD r6, r6, 1
    QBNE canal_ok, r6, r7
    LDI r6, 0
canal_ok:

    ; --- LÓGICA DE PING-PONG ---
    ADD r15, r15, 1
    QBNE continua, r15, r21

    LDI r15, 0

    LDI r20, 0
    SBBO &r20, r18, 0, 4    ; CYCLE = 0
    MOV r17, r16            ; próxima amostra alvo = 0 + 1 período

    QBEQ troca_para_buffer_1, r26, 0

troca_para_buffer_0:
    LDI r26, 0
    MOV r19, r24
    LDI r27, 1
    SBBO &r27, r14, 12, 4
    QBA continua

troca_para_buffer_1:
    LDI r26, 1
    MOV r19, r25
    LDI r27, 1
    SBBO &r27, r14, 8, 4

continua:
    SBBO &r26, r14, 4, 4
    JMP laco_principal