    .global ler_ads8688_asm
    .sect ".text"

; ==============================================================================
; VERSÃO DE DIAGNÓSTICO - CAPTURA TAMBÉM O "PREÂMBULO" (16 PRIMEIROS CICLOS)
; ==============================================================================
; Objetivo: descobrir se o MISO está preso em 1 o tempo todo (hardware) ou
; só durante a fase de dado (ADC/referência). Segundo o datasheet do
; ADS8688, o SDO fica em 0 durante os primeiros 16 ciclos de SCLK (fase em
; que só estamos escrevendo o comando); só a partir do 16º ciclo é que o
; SDO passa a mostrar os 16 bits reais da conversão anterior.
;
; Esta versão grava AMBOS os valores por amostra (4 bytes em vez de 2):
;   [preambulo_lo, preambulo_hi, dado_lo, dado_hi]
; ou seja, cada amostra agora é um par de uint16: (preambulo, dado).
;
; INTERPRETAÇÃO DO RESULTADO (ver script analisar_preambulo.py):
;   - preambulo ~= 0x0000 e dado sempre no mesmo valor -> comunicação SPI
;     básica está OK (o ADC "ouve" o CS/SCLK corretamente), o problema está
;     na conversão em si (referência, alimentação, canal, ou o ADC está
;     saturado/em erro).
;   - preambulo TAMBÉM travado (ex: sempre 0xFFFF) -> o MISO está sendo
;     lido como 1 o tempo todo, independente da fase do protocolo. Isso
;     aponta para hardware (pull-up dominando, fio desconectado, ADC sem
;     alimentação/referência deixando SDO em alta impedância) e não para
;     lógica de software.
;
; Baseado em spi_core_diagnostico_lento.asm (mesma margem de CS, mesmo
; reset de CYCLE, mesma inicialização de pinos em repouso).
; ==============================================================================
; PINOS (compatível com o antigo teste_spi_pru.c):
;   Bit 0 (r30) = SCLK   | Bit 1 (r30) = SDI/MOSI
;   Bit 2 (r31) = SDO/MISO | Bit 3 (r30) = CS
; ==============================================================================

; ==============================================================================
; VERSÃO 2 DE DIAGNÓSTICO: replica o MESMO ponto de amostragem do MISO que o
; código antigo comprovadamente funcional (teste_spi_pru.c) - ele lê o MISO
; logo APÓS SUBIR o SCLK (borda de subida), não depois de descer como a
; versão anterior deste diagnóstico fazia. Se o optoacoplador tiver tempos
; de subida/descida assimétricos (muito comum), sampleab um pino no
; momento errado do ciclo pode capturar sempre o mesmo "resquício" de uma
; transição lenta - o que bate exatamente com o padrão visto (uma única
; transição no meio dos 32 ciclos, sempre no mesmo lugar).
;
; Também MUITO mais lento: ~555 ns/bit (~1,8 MHz), bem além da margem do
; código antigo. Use com uma frequência de amostragem baixa (ex: 2000 Hz),
; já que cada transação agora consome ~17,8 us.
; ==============================================================================
; ==============================================================================
; DELAY_TICKS: mesmo mecanismo do spi_core.asm principal - ajuste este único
; valor para controlar a velocidade do SPI sem estourar a PRU_IMEM.
; ==============================================================================
DELAY_TICKS .set 1

CMD_BIT .macro
    ; 1. Configura o MOSI (SDI) testando estritamente o bit 31 (igual ao if do C)
    QBBC limpa_mosi?, r28, 31
    SET r30, r30, 1          ; Se bit 31 for 1, MOSI = 1
    QBA mosi_pronto?
limpa_mosi?:
    CLR r30, r30, 1          ; Se bit 31 for 0, MOSI = 0
mosi_pronto?:
    LSL r28, r28, 1          ; Desloca para o próximo bit

    ; 2. Delay Setup MOSI
    LDI r0, DELAY_TICKS
espera_a?: SUB r0, r0, 1; QBNE espera_a?, r0, 0

    ; 3. Sobe o SCLK
    SET r30, r30, 0

    ; 4. Delay duplo: Maximiza o tempo de estabilização do sinal físico
    LDI r0, DELAY_TICKS
espera_b?: SUB r0, r0, 1; QBNE espera_b?, r0, 0
    LDI r0, DELAY_TICKS
espera_c?: SUB r0, r0, 1; QBNE espera_c?, r0, 0

    ; 5. Amostra o MISO no último instante seguro (igual ao if do C)
    LSL r5, r5, 1
    QBBC pula_set_miso?, r31, 2
    OR r5, r5, 1             ; Adiciona 1 se o MISO estiver alto
pula_set_miso?:

    ; 6. Desce o SCLK
    CLR r30, r30, 0

    ; 7. Delay Hold SCLK
    LDI r0, DELAY_TICKS
espera_d?: SUB r0, r0, 1; QBNE espera_d?, r0, 0
    .endm

DATA_BIT .macro
    ; O MOSI já está em 0 do último CMD_BIT, não precisamos mexer

    ; 1. Delay Setup
    LDI r0, DELAY_TICKS
espera_e?: SUB r0, r0, 1; QBNE espera_e?, r0, 0

    ; 2. Sobe o SCLK
    SET r30, r30, 0

    ; 3. Delay duplo: Maximiza o tempo de estabilização do sinal físico
    LDI r0, DELAY_TICKS
espera_f?: SUB r0, r0, 1; QBNE espera_f?, r0, 0
    LDI r0, DELAY_TICKS
espera_g?: SUB r0, r0, 1; QBNE espera_g?, r0, 0

    ; 4. Amostra o MISO (Dado real) no último instante seguro
    LSL r23, r23, 1
    QBBC pula_set_dado?, r31, 2
    OR r23, r23, 1
pula_set_dado?:

    ; 5. Desce o SCLK
    CLR r30, r30, 0

    ; 6. Delay Hold SCLK
    LDI r0, DELAY_TICKS
espera_h?: SUB r0, r0, 1; QBNE espera_h?, r0, 0
    .endm

; ==============================================================================
; ASSINATURA: void ler_ads8688_asm(volatile struct shared_control *ctrl)
; r14 = Ponteiro base da struct shared_control (0x00010000)
; r5  = acumulador do preâmbulo (NOVO - só para diagnóstico)
; ==============================================================================
ler_ads8688_asm:
    SET r30, r30, 3   ; CS alto (desselecionado)
    CLR r30, r30, 0   ; SCLK baixo
    CLR r30, r30, 1   ; MOSI baixo

    LDI r18.w0, 0x200C
    LDI r18.w2, 0x0002

    ; ==========================================================================
    ; NOVO: SAMPLES_PER_BUFFER reduzido para 8192 (era 1.048.576), só para
    ; este diagnóstico encher o buffer quase instantaneamente. Se mudar este
    ; valor, ajuste também SAMPLES_PER_BUFFER em memoria_pru_diagnostico.h
    ; para bater exatamente com o mesmo número.
    ; ==========================================================================
    LDI r21.w0, 0x2000   ; 0x00002000 em Hex = 8.192
    LDI r21.w2, 0x0000

espera_configuracao:
    LBBO &r20, r14, 24, 4
    QBEQ espera_configuracao, r20, 0

    LDI r20, 0
    SBBO &r20, r18, 0, 4

    LBBO &r16, r14, 0, 4  ; r16 = sample_period_ticks
    LBBO &r24, r14, 16, 4 ; r24 = buffer_0_addr
    LBBO &r25, r14, 20, 4 ; r25 = buffer_1_addr

    MOV r19, r24
    LDI r15, 0
    LDI r26, 0

    LBBO &r17, r18, 0, 4
    ADD r17, r17, r16

    ; ==========================================================================
    ; NOVO: manda um comando de RESET (0x8500) uma única vez, antes do laço
    ; principal, para garantir que o ADS8688 comece do valor padrão de
    ; fábrica conhecido (registrador de range = ±2,5*VREF = ±10,24V em TODOS
    ; os canais, conforme Table 3 do datasheet SBAS582), independente de
    ; qualquer configuração residual deixada por sessões de teste anteriores
    ; (o registrador de range só volta ao padrão com RESET ou power-cycle -
    ; nunca mandamos esse comando antes, e o histórico de depuração já teve
    ; várias versões com bugs que mandavam bits inesperados pelo SDI).
    ; ==========================================================================

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
    LDI r5, 0                ; NOVO: zera o acumulador do preâmbulo
    LDI32 r28, 0xC4000000

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

    SET r30, r30, 3          ; Levanta o CS - Fim da transação

    ; =======================================================================
    ; TRAVA DE QUALIDADE DE AQUISIÇÃO
    ; Garante >400ns de CS ALTO para o ADS8688 recarregar o capacitor interno,
    ; mesmo que a frequência exigida pela memória compartilhada seja extrema ou 0.
    ; =======================================================================
    LDI r1, 100
delay_cs_high_minimo:
    SUB r1, r1, 1
    QBNE delay_cs_high_minimo, r1, 0

    ; Grava preâmbulo (2 bytes) + dado (2 bytes) = 4 bytes/amostra
    SBBO &r5, r19, 0, 2
    SBBO &r23, r19, 2, 2
    ADD r19, r19, 4

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
