    .global ler_ads8688_asm
    .sect ".text"

; ==============================================================================
; SPI_CORE — MODO AUTOMÁTICO (AUTO_RST) DO ADS8688
; ==============================================================================
; [MUDANÇA DE ARQUITETURA] Esta versão substitui o antigo modo manual
; (MAN_Ch_x, um comando de seleção de canal reenviado a cada quadro SPI) pelo
; modo de varredura automática do ADS8688 (comando AUTO_RST). Referência:
; datasheet SBAS582C, seção 8.4.2.5 ("Auto Channel Enable with Reset").
;
; POR QUE: em modo manual, o host precisa reenviar o comando de canal em TODO
; quadro, mesmo quando o canal não muda entre amostras (caso do canal único) ou
; quando a sequência de canais é sempre a mesma (caso multi-canal já
; implementado). Em modo automático, o host escreve a sequência UMA VEZ e o
; próprio ADS8688 avança de canal sozinho a cada borda de descida de CS. Isso
; elimina: (a) a tabela ctrl->comandos_canais[] e o índice round-robin (r6/r7/
; r8/r9 na versão anterior) do laço principal, (b) o acesso à RAM compartilhada
; (LBBO) que essa tabela exigia a cada amostra, e (c) faz o MOSI ficar
; eletricamente parado (sempre 0x0000/NO_OP) durante a fase de "comando" de
; toda amostra do laço principal — sem alternância de bits dependente de
; canal, o que é relevante especificamente para este projeto (medição de
; supraharmônicos = sensível a ruído de chaveamento digital acoplado na cadeia
; analógica).
;
; ⚠️ AINDA NÃO VALIDADO EM HARDWARE (ver docs/Contexto do Projeto-3.md, seção
; 4). O modo manual (single-channel e multi-canal) foi validado em hardware
; real; esta reescrita para modo automático foi implementada com base na
; leitura do datasheet, mas ainda não foi compilada com o clpru nem testada na
; PRU física. Tratar como experimento isolado nesta branch, com o mesmo rigor
; de validação já aplicado ao modo manual, antes de fazer merge na main (ver
; roadmap no Contexto do Projeto).
;
; --- O QUE FOI PRESERVADO DO MODO MANUAL (validado em hardware, não mudou) ---
;   - Frame de 32 ciclos de SCLK por amostra (16 para "comando" + 16 para
;     leitura de dado) — no modo automático, os 16 ciclos de "comando" viram
;     NO_OP (0x0000) em regime de captura, mas a estrutura do frame continua
;     sendo de 32 ciclos completos: o próprio datasheet exige isso mesmo em
;     modo automático ("the command frame must be a complete frame of 32 SCLK
;     cycles") para o ADC acumular corretamente o próximo canal da sequência.
;   - Escrita do bit de MOSI feita com desvio condicional (QBBC) dentro de
;     CMD_BIT — mantida por completo, mesmo hoje sempre testando um bit 0 (já
;     que o comando em regime de captura é sempre 0x00000000/NO_OP): manter o
;     macro idêntico preserva EXATAMENTE o timing já validado no hardware,
;     em vez de tentar "otimizar" removendo instruções de um bloco cuja
;     simetria de duração com DATA_BIT já se mostrou crítica no passado (ver
;     nota dentro do macro CMD_BIT).
;   - Amostragem do MISO no ÚLTIMO instante seguro antes da borda de DESCIDA
;     do SCLK (resolveu o bug histórico de leitura presa em fundo de escala).
;   - CS/SCLK/MOSI inicializados em repouso antes de qualquer transação SPI.
;   - Registrador CYCLE da PRU ressincronizado no início da aquisição e a cada
;     troca de buffer (trava em vez de dar a volta ao estourar 32 bits,
;     ~21,47 s a 200 MHz).
;   - Margens de tempo em torno do CS (setup, hold, tempo mínimo em nível
;     alto) mantidas com os mesmos valores calibrados empiricamente
;     (200/100/100 ciclos) — NÃO foram comparadas ao datasheet do ADS8688 e
;     não foram alteradas aqui; ver nota de desempenho no Contexto do Projeto
;     sobre uma possível folga não aproveitada nesses números.
;
; --- O QUE MUDOU (removido nesta versão) ------------------------------------
;   - Modo manual (MAN_Ch_x) completamente removido, por pedido explícito:
;     este projeto não precisa mais oferecer os dois modos.
;   - Índice de canal round-robin em software (antigos r6=índice, r7=
;     num_canais, r8=escrátio de endereço, r9=base do array) removido do laço
;     principal — o ADS8688 agora faz esse trabalho sozinho, em hardware.
;     (r6/r8/r9 ficaram livres; r7 foi reaproveitado só na transação de
;     configuração, ver "REGISTRADORES" abaixo.)
;   - IMPORTANTE (ordem dos canais): o ADS8688 em modo automático SEMPRE
;     varre os canais habilitados em ORDEM CRESCENTE de número de canal — ao
;     contrário do modo manual multi-canal antigo, onde a ordem de
;     intercalação era livre (definida pela ordem digitada em --canais). A
;     ordenação agora é feita do lado ARM (ler_adc.c) antes de montar a
;     máscara de bits enviada aqui.
; ==============================================================================
; PINOS (inalterado):
;   Bit 0 (r30) = SCLK   | Bit 1 (r30) = SDI/MOSI
;   Bit 2 (r31) = SDO/MISO | Bit 3 (r30) = CS
; ==============================================================================
; REGISTRADORES NOVOS/REAPROVEITADOS (configuração do modo automático, só
; usados uma vez, ANTES do laço principal — depois disso ficam sem uso):
;   r7 = registrador de rascunho onde o comando de 16 bits da escrita de
;        AUTO_SEQ_EN (transação 1) é montado, antes de ser alinhado para os
;        bits 31..16 de r28 (formato que CMD_BIT espera). Não usado na
;        transação 2 (AUTO_RST), que carrega r28 direto via LDI.w0/.w2.
; Os antigos r6 (índice round-robin), r8/r9 (endereço/tabela de canais) do
; modo manual multi-canal NÃO são mais usados em lugar nenhum deste arquivo.
; ==============================================================================

; ==============================================================================
; MACRO: Escreve 1 bit de comando no SDI (Ciclos 1-16 do frame do ADS8688)
; r28 = registrador de comando (deslocado a cada chamada, MSB no bit 31).
; Em regime de captura (laço principal), r28 é sempre 0x00000000 (NO_OP) —
; ver nota grande no cabeçalho do arquivo sobre por que o macro foi mantido
; idêntico ao validado em hardware, mesmo com o comando agora sendo
; constante.
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
    ; relatada historicamente (a taxa de variação do sinal é máxima nos
    ; cruzamentos por zero, onde essa margem apertada mais afetaria a
    ; leitura). Por isso continua aqui mesmo agora que o comando é
    ; sempre NO_OP.
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

    ; ==========================================================================
    ; [MODO AUTOMÁTICO] Sequência de configuração do ADS8688 — 2 transações
    ; separadas, executadas uma única vez, ANTES do laço principal. Nenhum
    ; resultado lido via SDO aqui é gravado na DDR (ver descarte da primeira
    ; amostra do lado ARM em ler_adc.c, que cobre qualquer resíduo que ainda
    ; escape para o primeiro quadro do laço principal).
    ;
    ; ⚠️ CORREÇÃO (após bug observado em hardware, captura multi-canal
    ; saindo com todos os "canais" idênticos -- sinal de que a varredura
    ; automática nunca avançava de canal): as 2 transações NÃO têm a mesma
    ; duração. Confirmado contra o driver oficial do ADS8688 no kernel Linux
    ; (drivers/iio/adc/ti-ads8688.c, ADS8688_PROG_DONT_CARE_BITS=8) e por
    ; resposta de suporte da TI no fórum E2E:
    ;   - Escrita de REGISTRADOR DE PROGRAMA (AUTO_SEQ_EN, abaixo) usa 24
    ;     ciclos de SCLK no total: 16 do comando de 16 bits + 8 ciclos
    ;     adicionais. NÃO 32. Usar 32 ciclos aqui (como uma transação normal)
    ;     deixa o MOSI parado no nível do último bit do comando por 8 ciclos
    ;     de SCLK a mais do que o ADS8688 espera, com o CS ainda baixo -- o
    ;     chip passa a interpretar isso como bits de comando extras
    ;     grudados na escrita, corrompendo a máscara de canais. Foi
    ;     exatamente isso que causou o bug.
    ;   - Comando de REGISTRADOR DE COMANDO (AUTO_RST, RST, MAN_Ch_x, NO_OP)
    ;     usa 32 ciclos, igual sempre foi (16 de comando + 16 de leitura).
    ; ==========================================================================

    ; --- Transação 1: escreve o registrador de programa AUTO_SEQ_EN
    ; (endereço 0x01) com a máscara de canais vinda de ctrl->auto_seq_mask
    ; (bit N ligado = canal N incluído na varredura). Formato do quadro de
    ; 16 bits: bits [15:9] = endereço (7 bits), bit [8] = R/W (1 = escrita),
    ; bits [7:0] = dado -- para o endereço 0x01 em modo de escrita, a parte
    ; fixa (endereço<<9 | R/W<<8) vale 0x0300. 24 ciclos no total: 16
    ; CMD_BIT (o comando de 16 bits) + 8 DATA_BIT (ciclos adicionais
    ; exigidos pelo datasheet, dado descartado).
    LBBO &r7, r14, 28, 4     ; r7 = ctrl->auto_seq_mask (0-255)
    LDI r20, 0x0300
    OR  r7, r7, r20          ; r7 = comando de 16 bits (0x0300 | máscara)
    LSL r28, r7, 16          ; alinha aos bits 31..16 de r28, formato que
                              ; CMD_BIT espera
    LDI r23, 0

    CLR r30, r30, 3          ; abaixa o CS

    LDI r1, 200
delay_cs_setup_auto1:
    SUB r1, r1, 1
    QBNE delay_cs_setup_auto1, r1, 0

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
    ; só 8 DATA_BIT aqui (24 ciclos no total) -- NÃO 16. Ver nota grande
    ; acima. r23 (dado lido) é descartado de propósito.

    LDI r1, 100
delay_cs_hold_auto1:
    SUB r1, r1, 1
    QBNE delay_cs_hold_auto1, r1, 0

    SET r30, r30, 3          ; levanta o CS

    LDI r1, 100
delay_cs_high_auto1:
    SUB r1, r1, 1
    QBNE delay_cs_high_auto1, r1, 0

    ; --- Transação 2: envia o comando AUTO_RST (0xA000, registrador de
    ; comando) -- inicia a varredura automática a partir do canal habilitado
    ; de menor número. Transação normal de 32 ciclos (16 CMD_BIT + 16
    ; DATA_BIT), igual a qualquer comando do registrador de comando.
    LDI r28.w0, 0x0000
    LDI r28.w2, 0xA000        ; comando AUTO_RST (fixo)
    LDI r23, 0

    CLR r30, r30, 3          ; abaixa o CS

    LDI r1, 200
delay_cs_setup_auto2:
    SUB r1, r1, 1
    QBNE delay_cs_setup_auto2, r1, 0

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
    ; 16 DATA_BIT aqui (32 ciclos no total) -- transação normal. r23
    ; descartado de propósito.

    LDI r1, 100
delay_cs_hold_auto2:
    SUB r1, r1, 1
    QBNE delay_cs_hold_auto2, r1, 0

    SET r30, r30, 3          ; levanta o CS

    LDI r1, 100
delay_cs_high_auto2:
    SUB r1, r1, 1
    QBNE delay_cs_high_auto2, r1, 0

    ; --- Fim da configuração do ADS8688 — início da captura de verdade ---
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

    ; [MODO AUTOMÁTICO] r28 = NO_OP (0x00000000) em TODO quadro do laço
    ; principal — mantém o ADS8688 em modo automático e faz o próprio chip
    ; avançar de canal sozinho (ver cabeçalho do arquivo). Substitui a
    ; antiga leitura de ctrl->comandos_canais[r6] via tabela em RAM
    ; compartilhada (3 instruções: LSL+ADD+LBBO) por uma única LDI — menos
    ; código, menos ciclos por amostra, e sem o acesso à RAM compartilhada
    ; que a LBBO exigia a cada transação.
    LDI r28, 0

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

    ; [MODO AUTOMÁTICO] Sem incremento de índice de canal aqui — o ADS8688
    ; já avançou sozinho para o próximo canal da varredura automática na
    ; borda de descida de CS que acabou de acontecer nesta mesma transação
    ; (ver cabeçalho do arquivo). Isso elimina do laço principal os antigos
    ; r6/r7/r8/r9 (índice, num_canais, base do array, endereço efetivo) e o
    ; bloco de incremento/wrap que existia aqui antes.

    ; --- LÓGICA DE PING-PONG (inalterada) ---
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
