    .global ler_ads8688_asm
    .sect ".text"

; ==============================================================================
; MACROS DE ATRASO (Ajustados para igualar a lentidão estrutural do código C)
; ==============================================================================
DELAY_10 .macro
    NOP
    NOP
    NOP
    NOP
    NOP
    NOP
    NOP
    NOP
    NOP
    NOP
    .endm

DELAY_SAFE .macro
    DELAY_10
    DELAY_10
    DELAY_10
    DELAY_10
    .endm

; ==============================================================================
; INÍCIO DA FUNÇÃO PRINCIPAL
; ==============================================================================
ler_ads8688_asm:
    ; --- INICIALIZAÇÃO DE SEGURANÇA ---
    SET r30, r30, 3         ; CS Alto (Standby seguro)
    CLR r30, r30, 0         ; SCLK Baixo (Modo 0 SPI)
    CLR r30, r30, 1         ; MOSI Baixo

    LDI r18.w0, 0x200C
    LDI r18.w2, 0x0002
    LDI r21.w0, 0x0000
    LDI r21.w2, 0x0010   

    LBBO &r16, r14, 0, 4  
    LBBO &r24, r14, 16, 4 
    LBBO &r25, r14, 20, 4 

    MOV r19, r24          
    LDI r15, 0            
    LDI r26, 0            

    LBBO &r17, r18, 0, 4  
    ADD r17, r17, r16     

laco_principal:
    LBBO &r16, r14, 0, 4

wait_time:
    LBBO &r22, r18, 0, 4    
    SUB r20, r17, r22       
    QBBC wait_time, r20, 31 
    ADD r17, r17, r16       

    ; --- INÍCIO TRANSAÇÃO SPI ---
    CLR r30, r30, 3         ; Abaixa o CS (ADC acorda)
    DELAY_SAFE              ; Tempo de estabilização do CS
    DELAY_SAFE

    LDI r23, 0              ; Zera o acumulador de leitura (MISO)
    LDI r29, 0xC400         ; Comando Ch0 a ser enviado (MOSI)
    LDI r28, 16             ; Contador para os 16 bits de dados

    ; --------------------------------------------------------
    ; LOOP 1: Envia Comando 0xC400 e Lê 16 Bits Reais
    ; --------------------------------------------------------
loop_dados:
    QBBC mosi_zero, r29, 15 ; Se o Bit 15 for 0, salta para mosi_zero
mosi_um:
    SET r30, r30, 1         ; MOSI = 1
    QBA mosi_done
mosi_zero:
    CLR r30, r30, 1         ; MOSI = 0
mosi_done:
    LSL r29, r29, 1         ; Prepara o próximo bit do comando

    DELAY_SAFE              ; Setup time do MOSI
    SET r30, r30, 0         ; Sobe SCLK
    DELAY_SAFE              ; Tempo de Propagação (Espera o MISO chegar)

    ; Leitura Nativa e Blindada do MISO (Bit 2 do r31)
    LSL r23, r23, 1         ; Abre espaço no acumulador
    QBBC miso_zero, r31, 2  ; Se MISO for 0, ignora e salta
    OR r23, r23, 1          ; Se MISO for 1, guarda o bit
miso_zero:

    CLR r30, r30, 0         ; Desce SCLK
    DELAY_SAFE              ; Hold time

    SUB r28, r28, 1
    QBNE loop_dados, r28, 0 ; Repete até 16 vezes

    ; --------------------------------------------------------
    ; LOOP 2: Gera 16 Clocks Dummy exigidos pelo ADC
    ; --------------------------------------------------------
    LDI r28, 16             ; Reseta contador
    CLR r30, r30, 1         ; Força MOSI = 0 

loop_dummy:
    DELAY_SAFE
    SET r30, r30, 0         ; Sobe SCLK
    DELAY_SAFE
    CLR r30, r30, 0         ; Desce SCLK
    DELAY_SAFE

    SUB r28, r28, 1
    QBNE loop_dummy, r28, 0

    ; --- FIM DA TRANSAÇÃO ---
    DELAY_SAFE
    SET r30, r30, 3         ; Sobe o CS (Encerra o pacote SPI)

    ; --- GRAVAÇÃO NA DDR E PING-PONG ---
    SBBO &r23, r19, 0, 2    
    ADD r19, r19, 2         

    ADD r15, r15, 1         
    QBNE continua, r15, r21 

    LDI r15, 0              
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
    QBA laco_principal
