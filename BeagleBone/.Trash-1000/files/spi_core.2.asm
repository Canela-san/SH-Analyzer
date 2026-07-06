.global ler_ads8688_asm
    .sect ".text"

; ==============================================================================
; PINOS (compatível com o antigo teste_spi_pru.c):
;   Bit 0 (r30) = SCLK   | Bit 1 (r30) = SDI/MOSI
;   Bit 2 (r31) = SDO/MISO | Bit 3 (r30) = CS
; ==============================================================================

; ==============================================================================
; COMANDO ENVIADO AO ADS8688 (registrador de comando, 16 bits, MSB primeiro)
; Conforme a Table 6 (Command Register Map) do datasheet SBAS582:
;   0xC000 = MAN_Ch_0 (seleciona/mantém o canal 0 em modo manual)
;   0xC400 = MAN_Ch_1, 0xC800 = MAN_Ch_2, ... (para trocar de canal, troque aqui)
; O valor 0x0000 (NO_OP) NUNCA deve ser usado sozinho: recém-ligado, o ADS8688
; fica em IDLE e não converte nada até receber um comando válido pelo menos uma
; vez - por isso mandamos o comando em TODO frame, exatamente como o
; teste_spi_pru.c antigo fazia (lá, porém, o valor usado era 0xC400 = canal 1
; por engano; aqui usamos 0xC000 = canal 0, que é o que o enunciado pede).
CMD_CANAL_0 .set 0xC000

; ==============================================================================
; MACRO: Escreve 1 bit de comando no SDI (Ciclos 1-16 do frame do ADS8688)
; O ADS8688 lê o SDI na BORDA DE DESCIDA do SCLK (datasheet, 8.4.1.1.3).
; Por isso o bit é colocado no pino ANTES de gerar o pulso, garantindo o
; tempo de setup (tSU_DICK = 5 ns) antes da borda de descida.
; r28 = registrador de comando (deslocado a cada chamada, MSB primeiro)
; Duração alvo: ~12 ciclos de PRU (60 ns) -> dentro do limite fSCLK <= 17 MHz
; do datasheet (tSCLK minimo = 59 ns), necessário para dar tempo do ADC
; terminar a conversão anterior (tCONV ~ 850 ns) antes da 16a borda de descida.
; ==============================================================================
CMD_BIT .macro
    AND r29, r28, 0x8000    ; 1. Isola o bit mais significativo do comando
    LSR r29, r29, 14        ; 2. Move esse bit para a posição do SDI (Bit 1)
    CLR r30, r30, 1         ; 3. Zera o pino SDI
    OR  r30, r30, r29       ; 4. Escreve o bit de comando no SDI (branchless)
    LSL r28, r28, 1         ; 5. Prepara o próximo bit do comando

    SET r30, r30, 0         ; 6. Sobe o SCLK
    NOP                     ; 7.
    NOP                     ; 8.
    NOP                     ; 9. Tempo em nível alto (respeita tPH_CK)
    CLR r30, r30, 0         ; 10. Desce o SCLK -> ADC lê o bit no SDI agora
    NOP                     ; 11.
    NOP                     ; 12. Tempo em nível baixo (respeita tPL_CK)
    .endm

; ==============================================================================
; MACRO: Lê 1 bit de dado do SDO (Ciclos 17-32 do frame do ADS8688)
; O SDO só começa a apresentar dados válidos a partir da 16a borda de descida
; (datasheet, Event 3): a cada nova borda de descida gerada aqui, o ADC expõe
; o próximo bit (MSB primeiro) para ser lido.
; r23 = acumulador de 16 bits da amostra
; ==============================================================================
DATA_BIT .macro
    SET r30, r30, 0         ; 1. Sobe o SCLK
    NOP                     ; 2.
    NOP                     ; 3.
    NOP                     ; 4. Tempo em nível alto
    CLR r30, r30, 0         ; 5. Desce o SCLK -> ADC atualiza o SDO
    NOP                     ; 6.
    NOP                     ; 7. Delay para o SDO estabilizar após a borda
    LSL r23, r23, 1         ; 8. Abre espaço no acumulador
    AND r22, r31, 4         ; 9. Lê o pino SDO/MISO (Bit 2)
    LSR r22, r22, 2         ; 10. Alinha o bit lido na posição 0
    OR  r23, r23, r22       ; 11. Injeta o bit lido no acumulador
    NOP                     ; 12. Tempo em nível baixo
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

    ; ==========================================================================
    ; NOVO: SINCRONIZAÇÃO COM O ARM ANTES DE LER OS ENDEREÇOS DE BUFFER
    ; ==========================================================================
    ; Sem isso, se a PRU iniciar antes do ler_adc.c configurar buffer_0_addr/
    ; buffer_1_addr, esses valores seriam lidos como 0 (RAM zerada) e a PRU
    ; passaria a sessão inteira gravando amostras no endereço físico errado -
    ; nunca escrevendo na DDR que o ARM está de fato lendo. Por isso esperamos
    ; aqui até o ARM sinalizar (offset 24 = config_ready) que já terminou de
    ; escrever os endereços corretos.
espera_configuracao:
    LBBO &r20, r14, 24, 4
    QBEQ espera_configuracao, r20, 0

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

    ; --- 3. TRANSAÇÃO SPI (FRAME COMPLETO DE 32 CICLOS DO ADS8688) ---
    ; O ADS8688 exige 32 pulsos de SCLK por amostra em modo manual:
    ;   ciclos 1-16  -> escreve o comando de 16 bits no SDI (SDO fica em 0)
    ;   ciclos 17-32 -> lê os 16 bits da conversão ANTERIOR no SDO
    ; (ver datasheet SBAS582, seção "Data Acquisition Example", Eventos 1-3)
    CLR r30, r30, 3         ; Abaixa o CS (Chip Select - Bit 3) para iniciar a conversão
    MOV r23, 0              ; Zera o acumulador de dados
    LDI r28, CMD_CANAL_0    ; Carrega o comando (seleciona/mantém o canal 0)

    ; Ciclos 1-16: escreve o comando (SDI)
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

    ; Ciclos 17-32: lê os 16 bits de dado (SDO)
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