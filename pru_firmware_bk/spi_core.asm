    .global ler_ads8688_asm
    .sect ".text"

; ==============================================================================
; VERSÃO DE DIAGNÓSTICO - SPI DELIBERADAMENTE LENTO (~180 ns/bit, ~5,5 MHz)
; ==============================================================================
; Objetivo: isolar se o problema da leitura sempre-zero é velocidade de
; chaveamento (optoacoplador + capacitância do cabo) ou ainda um bug de
; software. Esta versão usa o MESMO protocolo corrigido (frame de 32 ciclos,
; comando MAN_Ch_0 no SDI, handshake config_ready) do spi_core.asm, mas com
; uma margem de tempo por bit igual ou maior que a do firmware antigo
; (teste_spi_pru.c), que comprovadamente funcionava fisicamente.
;
; COMO USAR:
;   1. Troque este arquivo pelo spi_core.asm (ou ajuste o Makefile) e recompile.
;   2. Rode "sudo ./ler_adc 102400" (mesma frequência que já funcionava antes).
;   3. Plote o .bin resultante:
;        - Se aparecer tensão real (não mais zero constante) -> confirmado,
;          o gargalo é a velocidade do sinal físico. Aí sim vale subir aos
;          poucos (reduzindo os NOPs) e testar de novo a cada passo.
;        - Se continuar tudo zero -> ainda tem bug de software/fiação, e a
;          velocidade não é a causa - volte a olhar polaridade dos pinos e
;          mapeamento de bits.
; ==============================================================================
; PINOS (compatível com o antigo teste_spi_pru.c):
;   Bit 0 (r30) = SCLK   | Bit 1 (r30) = SDI/MOSI
;   Bit 2 (r31) = SDO/MISO | Bit 3 (r30) = CS
; ==============================================================================

; ==============================================================================
; COMANDO ENVIADO AO ADS8688: MAN_Ch_0 = 0xC000, carregado já alinhado no
; bit 31 do registrador (0xC0000000) - ver spi_core.asm para a explicação
; completa dessa técnica (evita imediato de 16 bits, que o clpru rejeita).
; ==============================================================================
CMD_BIT .macro
    LSR r29, r28, 30        ; Traz os bits [31:30] para as posições [1:0]
    AND r29, r29, 2         ; Isola só o bit de interesse (posição do SDI = Bit 1)
    CLR r30, r30, 1         ; Zera o pino SDI
    OR  r30, r30, r29       ; Escreve o bit de comando no SDI
    LSL r28, r28, 1         ; Desloca o comando (prepara o próximo bit)

    SET r30, r30, 0         ; Sobe o SCLK
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
    NOP
    NOP
    NOP
    NOP
    NOP                     ; ~15 NOPs em nível alto (~75 ns de folga)
    CLR r30, r30, 0         ; Desce o SCLK -> ADC lê o bit no SDI agora
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
    NOP
    NOP
    NOP
    NOP                     ; ~14 NOPs em nível baixo (~70 ns de folga)
    .endm

DATA_BIT .macro
    SET r30, r30, 0         ; Sobe o SCLK
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
    NOP
    NOP
    NOP
    NOP
    NOP                     ; ~15 NOPs em nível alto
    CLR r30, r30, 0         ; Desce o SCLK -> ADC atualiza o SDO
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
    NOP
    NOP
    NOP
    NOP
    NOP                     ; ~15 NOPs de acomodação antes de ler o SDO
    LSL r23, r23, 1         ; Abre espaço no acumulador
    AND r22, r31, 4         ; Lê o pino SDO/MISO (Bit 2)
    LSR r22, r22, 2         ; Alinha o bit lido na posição 0
    OR  r23, r23, r22       ; Injeta o bit lido no acumulador
    .endm

; ==============================================================================
; ASSINATURA: void ler_ads8688_asm(volatile struct shared_control *ctrl)
; r14 = Ponteiro base da struct shared_control (0x00010000)
; ==============================================================================
ler_ads8688_asm:
    ; ==========================================================================
    ; NOVO: inicializa os pinos do SPI em repouso (CS alto/desselecionado,
    ; SCLK baixo, MOSI baixo) ANTES de entrar em espera_configuracao.
    ; ==========================================================================
    ; O código antigo (teste_spi_pru.c), que funciona, fazia exatamente isso
    ; logo no início ("__R30 |= CS_BIT; __R30 &= ~SCLK_BIT;"). O código novo
    ; nunca fazia - a primeira vez que r30 era tocado era dentro do laço
    ; principal. Isso deixava o CS no estado padrão de reset da PRU (0 =
    ; provavelmente ASSERTADO) durante todo o tempo de espera pelo
    ; config_ready, que pode ser vários segundos. Um CS preso em nível baixo
    ; por tempo indefinido, sem os pulsos de clock esperados, é uma sequência
    ; fora do protocolo e pode deixar o ADS8688 num estado interno inválido
    ; antes mesmo da primeira transação real.
    SET r30, r30, 3   ; CS alto (desselecionado)
    CLR r30, r30, 0   ; SCLK baixo
    CLR r30, r30, 1   ; MOSI baixo

    LDI r18.w0, 0x200C
    LDI r18.w2, 0x0002

    LDI r21.w0, 0x0000
    LDI r21.w2, 0x0010   ; 0x00100000 em Hex = 1.048.576

espera_configuracao:
    LBBO &r20, r14, 24, 4
    QBEQ espera_configuracao, r20, 0

    ; ==========================================================================
    ; NOVO: zera o contador de ciclos AGORA, no momento real em que a
    ; aquisição começa - não só uma vez no boot da PRU (pru_main.c).
    ; ==========================================================================
    ; O registrador CYCLE da PRU NÃO se comporta como um contador comum: ele
    ; NÃO dá a volta (overflow) sozinho ao passar de 0xFFFFFFFF - ele TRAVA
    ; nesse valor e para de incrementar (comportamento confirmado no fórum
    ; oficial da TI E2E e relatado de forma independente na comunidade
    ; BeagleBoard). A ~200 MHz isso acontece sozinho depois de ~21,47 s. Como
    ; o laço de espera pelo config_ready pode demorar (dependendo de quando
    ; o ler_adc é executado), o contador pode já ter travado antes mesmo da
    ; primeira amostra - por isso resetamos aqui, e não só no boot. Uma vez
    ; travado, r22 (tempo atual) para de avançar enquanto r17 (próxima
    ; amostra alvo) continua crescendo e dando a volta normalmente - a
    ; comparação de sinal no wait_time nunca mais fica "no passado", e o
    ; laço trava para sempre. É exatamente isso que explica o padrão
    ; observado (quanto mais se espera pra rodar o ler_adc, menos blocos).
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

laco_principal:
    LBBO &r16, r14, 0, 4

wait_time:
    LBBO &r22, r18, 0, 4
    SUB r20, r17, r22
    QBBC wait_time, r20, 31

    ADD r17, r17, r16

    ; --- TRANSAÇÃO SPI (32 CICLOS, VERSÃO LENTA DE DIAGNÓSTICO) ---
    CLR r30, r30, 3         ; Abaixa o CS

    ; ==========================================================================
    ; NOVO: margem entre a borda de descida do CS e o primeiro pulso de SCLK.
    ; Se o CS também passa por um optoacoplador lento, o ADC pode ainda não
    ; ter "enxergado" o CS baixo quando já começamos a gerar os pulsos de
    ; clock - nesse caso o ADC nunca se considera selecionado, e o SDO fica
    ; em alta impedância (lido como 1 constante se houver pull-up na linha,
    ; explicando o 0xFFFF). Ajuste r1 conforme necessário.
    ; ==========================================================================
    LDI r1, 100              ; ~200 ciclos = ~1 us de folga (ajustável)
delay_cs_setup:
    SUB r1, r1, 1
    QBNE delay_cs_setup, r1, 0

    LDI r23, 0
    LDI r28.w0, 0x0000
    LDI r28.w2, 0xC000

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

    ; Margem simétrica antes de levantar o CS de volta
    LDI r1, 50
delay_cs_hold:
    SUB r1, r1, 1
    QBNE delay_cs_hold, r1, 0

    SET r30, r30, 3

    SBBO &r23, r19, 0, 2
    ADD r19, r19, 2

    ADD r15, r15, 1
    QBNE continua, r15, r21

    LDI r15, 0

    ; ==========================================================================
    ; NOVO: re-sincroniza o contador de ciclos a cada troca de buffer (a cada
    ; ~SAMPLES_PER_BUFFER/frequência segundos - nas frequências testadas isso
    ; é bem menos que os ~21,47 s em que o registrador CYCLE trava). Zera
    ; CYCLE e realinha r17 (próxima amostra alvo) para a mesma base "zero",
    ; sem perder o ritmo (o desvio introduzido é de poucos ciclos de PRU,
    ; irrelevante). Isso evita que uma captura longa trave no meio, mesmo
    ; que dure muito mais que ~21 s.
    ; ==========================================================================
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
