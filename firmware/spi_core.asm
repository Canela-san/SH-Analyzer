.global ler_ads8688_asm
    .sect ".text"

; ==============================================================================
; MACRO: Leitura Branchless de 1 bit (Executa em exatos 8 ciclos = 40 ns)
; Lê o pino MISO (Bit 2), gera o Clock no SCLK (Bit 0) e acumula no r23.
; ==============================================================================
READ_BIT .macro
    SET r30, r30, 0     ; 1. Sobe SCLK (Bit 0)
    LSL r23, r23, 1     ; 2. Desloca acumulador para a esquerda (Abre espaço)
    NOP                 ; 3. Delay microscópico para o ADC estabilizar
    AND r22, r31, 4     ; 4. Lê pinos de entrada (r31) e isola o MISO (Bit 2)
    LSR r22, r22, 2     ; 5. Desloca o bit do MISO para a posição 0
    OR r23, r23, r22    ; 6. Injeta o bit lido no acumulador (Branchless)
    CLR r30, r30, 0     ; 7. Desce SCLK (Bit 0)
    NOP                 ; 8. Prepara próximo ciclo
    .endm

; ==============================================================================
; ASSINATURA: void ler_ads8688_asm(volatile struct shared_control *ctrl)
; r14 = Ponteiro base da struct shared_control (0x00010000)
; ==============================================================================
ler_ads8688_asm:
    ; --- 1. SETUP DE ENDEREÇOS E CONSTANTES ---
    ; Monta o endereço físico do Cycle Counter (0x2200C) no registrador r18
    LDI r18.w0, 0x200C
    LDI r18.w2, 0x0002

    ; Limite do Buffer: 1.048.576 amostras (2 MB)
    LDI r21.w0, 0x0000
    LDI r21.w2, 0x0010   ; 0x00100000 em Hex = 1.048.576

    ; Carrega a configuração inicial da Memória Compartilhada
    LBBO &r16, r14, 0, 4  ; r16 = sample_period_ticks (Offset 0)
    LBBO &r24, r14, 16, 4 ; r24 = buffer_0_addr (Endereço físico na DDR - Offset 16)
    LBBO &r25, r14, 20, 4 ; r25 = buffer_1_addr (Endereço físico na DDR - Offset 20)

    ; Inicialização das variáveis de controle de fluxo
    MOV r19, r24          ; r19 = Ponteiro Físico Atual (Começa apontando para o Buffer 0)
    MOV r15, 0            ; r15 = Contador de amostras no buffer atual
    MOV r26, 0            ; r26 = active_buffer_flag (0 = Buffer 0, 1 = Buffer 1)

    ; Configura o tempo alvo da PRIMEIRA amostra
    LBBO &r17, r18, 0, 4  ; Lê o Cycle Counter atual
    ADD r17, r17, r16     ; r17 = next_sample_time (Atual + Período)

laco_principal:
    ; --- 2. CONTROLE DE TEMPO (DETERMINISMO) ---
    ; Lê os ticks dinamicamente (permite ao ARM alterar a frequência em tempo real)
    LBBO &r16, r14, 0, 4

wait_time:
    LBBO &r22, r18, 0, 4    ; r22 = Lê o Cycle Counter em tempo real
    SUB r20, r17, r22       ; r20 = (Tempo Alvo) - (Tempo Atual)
    ; Se o bit 31 (Sinal) for 0, o resultado é positivo (ainda não chegou a hora)
    QBBC wait_time, r20, 31 
    
    ; Atualiza o alvo temporal para a PRÓXIMA amostra
    ADD r17, r17, r16       

    ; --- 3. TRANSAÇÃO SPI (LOOP UNROLLING) ---
    CLR r30, r30, 3         ; Abaixa o CS (Chip Select - Bit 3) para iniciar a conversão
    MOV r23, 0              ; Zera o acumulador de dados

    ; Extrai os 16 bits nativamente (MSB ao LSB) sem saltos condicionais
    READ_BIT
    READ_BIT
    READ_BIT
    READ_BIT
    READ_BIT
    READ_BIT
    READ_BIT
    READ_BIT
    READ_BIT
    READ_BIT
    READ_BIT
    READ_BIT
    READ_BIT
    READ_BIT
    READ_BIT
    READ_BIT

    SET r30, r30, 3         ; Levanta o CS (Finaliza a aquisição)

    ; --- 4. GRAVAÇÃO DIRETA NA MEMÓRIA DDR ---
    ; Salva a amostra de 16-bits (2 bytes) no endereço físico apontado por r19
    SBBO &r23, r19, 0, 2    
    ADD r19, r19, 2         ; Avança o ponteiro físico em 2 bytes

    ; --- 5. LÓGICA DE PING-PONG MACIÇO ---
    ADD r15, r15, 1         ; Incrementa o contador de amostras
    QBNE continua, r15, r21 ; Se (contador != SAMPLES_PER_BUFFER), pula a troca de buffer

    ; >>> INÍCIO DA TROCA DE BUFFER (SWAP) <<<
    MOV r15, 0              ; Zera o contador de amostras
    
    ; Verifica qual buffer está ativo no momento
    QBEQ troca_para_buffer_1, r26, 0 
    
troca_para_buffer_0:
    ; Se estava no 1, volta para o 0
    MOV r26, 0              ; Atualiza flag ativa para Buffer 0
    MOV r19, r24            ; Retorna o ponteiro de escrita para o início do Buffer 0
    LDI r27, 1              ; Registrador auxiliar com valor 1
    SBBO &r27, r14, 12, 4   ; Informa ao ARM: buffer_1_ready = 1 (Offset 12)
    QBA continua            ; Pula a lógica do Buffer 1

troca_para_buffer_1:
    ; Se estava no 0, vai para o 1
    MOV r26, 1              ; Atualiza flag ativa para Buffer 1
    MOV r19, r25            ; Move o ponteiro de escrita para o início do Buffer 1
    LDI r27, 1              ; Registrador auxiliar com valor 1
    SBBO &r27, r14, 8, 4    ; Informa ao ARM: buffer_0_ready = 1 (Offset 8)

continua:
    ; (Opcional) Atualiza na memória qual buffer a PRU está gravando agora
    ; Útil caso o ARM queira monitorar o status em tempo real
    SBBO &r26, r14, 4, 4

    ; Retorna ao início do laço (garantindo que o tempo de swap caiba na janela ociosa)
    QBA laco_principal