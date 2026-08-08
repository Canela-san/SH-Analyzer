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
; ==============================================================================
; PINOS:
;   Bit 0 (r30) = SCLK   | Bit 1 (r30) = SDI/MOSI
;   Bit 2 (r31) = SDO/MISO | Bit 3 (r30) = CS
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
    LDI32 r28, 0xC4000000    ; MAN_Ch_1 - ver nota no cabeçalho do arquivo

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