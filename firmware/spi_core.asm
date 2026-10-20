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
; ✅ VALIDADO EM HARDWARE: a varredura automática (AUTO_RST) foi testada na PRU
; física com 1 canal e com 5 canais a 102,4 kHz de taxa total (≈20,48 kHz por
; canal): canais ligados à rede mostram os 60 Hz, canais desconectados mostram
; só ruído (ver docs/project-context.md e o README). Ainda falta a validação
; QUANTITATIVA de exatidão (amplitude e frequência de um sinal de referência
; calibrado, injetado em bancada).
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
;   - Registrador CYCLE da PRU como base de tempo (trava em vez de dar a
;     volta ao estourar 32 bits, ~21,47 s a 200 MHz) -- mas ver a revisão de
;     out/2026 abaixo: não é mais zerado na troca de buffer.
;   - Margens de tempo em torno do CS (setup, hold, tempo mínimo em nível
;     alto) mantidas com os mesmos valores calibrados empiricamente
;     (200/100/100 iterações de 2 ciclos = 2/1/1 µs). O datasheet (SBAS582C,
;     tabela 7.6) pede só 30/10/30 ns: são ~4 µs dos ~7 µs de cada amostra e o
;     que limita a taxa a ~140 kS/s. Configuráveis desde out/2026 (ler_adc
;     --atraso-cs) para medir em bancada até onde dá para reduzi-los.
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
;
; --- REVISÃO DE OUT/2026: GRADE DE TEMPO E INTEGRIDADE ----------------------
;   - [BUG] O CYCLE era zerado na troca de buffer DEPOIS da transação da última
;     amostra: a 1ª amostra do buffer seguinte saía ~1400 ciclos (~7 µs) além
;     do período. Medido nas capturas reais: +0,697 amostra em todas as 57
;     trocas da T7c (100 kS/s), +0,872 a 125 kS/s -- o "salto de fase" que o
;     medir_captura.py acusava na continuidade. E um buffer mais longo que
;     2^32 ciclos (taxa abaixo de ~48,8 kS/s) deixava o CYCLE travar no meio.
;     Agora: rebase sem perda (rebase_contador) quando o CYCLE passa de 2^31.
;   - [BUG] O CYCLE era zerado ANTES das ~10 transações de configuração: as
;     primeiras amostras de toda captura saíam mais depressa que o pedido
;     (correndo atrás da grade). Agora é zerado logo antes da 1ª amostra.
;   - Contadores de integridade (amostras atrasadas, buffers sobrescritos
;     antes de o ARM gravá-los, quadros com preâmbulo != 0), em registradores
;     e publicados na troca de buffer -- ver memoria_pru.h. O que roda por
;     amostra (pré-checagem do horário e do preâmbulo, ~5 instruções) fica na
;     folga entre a amostra e a espera pela próxima: não muda o instante de
;     nenhuma amostra; só perto da taxa máxima custa ~0,3 % dela.
;   - Atrasos de CS do laço principal lidos de shared_control (ler_adc
;     --atraso-cs); com o padrão (0 = 200/100/100), a transação tem os mesmos
;     1166 ciclos do firmware validado (tests/test_pru_asm.py confere).
;   Tudo isso foi conferido no simulador (tests/pru_sim.py); falta validar
;   no hardware: make + uma captura longa com um tom estável e o
;   medir_captura.py (continuidade sem saltos nas trocas de buffer).
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
    ; [MODO AUTOMÁTICO] Sequência de configuração do ADS8688 — até 10 transações
    ; separadas (AUTO_SEQ_EN, RANGE_SELn de cada canal habilitado e AUTO_RST),
    ; executadas uma única vez, ANTES do laço principal. Nenhum
    ; resultado lido via SDO aqui é gravado na DDR (ver descarte da primeira
    ; amostra do lado ARM em ler_adc.c, que cobre qualquer resíduo que ainda
    ; escape para o primeiro quadro do laço principal).
    ;
    ; ⚠️ CORREÇÃO (após bug observado em hardware, captura multi-canal
    ; saindo com todos os "canais" idênticos -- sinal de que a varredura
    ; automática nunca avançava de canal): a escrita de registrador de
    ; programa e o comando AUTO_RST NÃO têm a mesma duração. Confirmado
    ; contra o driver oficial do ADS8688 no kernel Linux
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

    ; --- Transações de escrita de registrador de programa: AUTO_SEQ_EN
    ; (estágio 0) e RANGE_SELn de cada canal habilitado (estágios 1 a 8).
    ;
    ; Formato do quadro de 16 bits: bits [15:9] = endereço (7 bits), bit [8]
    ; = R/W (1 = escrita), bits [7:0] = dado. 24 ciclos no total: 16 CMD_BIT
    ; (o comando de 16 bits) + 8 DATA_BIT (ciclos adicionais exigidos pelo
    ; datasheet, dado descartado).
    ;   - AUTO_SEQ_EN (endereço 0x01): parte fixa 0x0300; dado = máscara de
    ;     canais vinda de ctrl->auto_seq_mask (bit N ligado = canal N incluído
    ;     na varredura).
    ;   - RANGE_SELn (endereços 0x05 a 0x0C = canais 0 a 7): parte fixa
    ;     ((0x05 + n) << 9) | 0x100, ou seja, 0x0B00, 0x0D00, 0x0F00...;
    ;     dado = código de faixa Range_CHn[3:0] (0 = ±2,5·VREF, 1 = ±1,25·VREF,
    ;     2 = ±0,625·VREF), vindo de ctrl->range_sel (8 "nibbles" de 4 bits,
    ;     canal N nos bits 4N+3..4N).
    ;
    ; [POR QUE ESCREVER A FAIXA SEMPRE] O ADS8688 NÃO é reiniciado quando
    ; ler_adc reinicia a PRU: os registradores de programa do ADC guardam o
    ; valor da captura anterior até o ADC ser desligado ou receber RST. Sem
    ; escrever a faixa de TODO canal habilitado a cada captura (inclusive a
    ; padrão, código 0), uma captura com --faixa-adc ficaria "grudada" na
    ; seguinte e o cabeçalho do .bin descreveria uma escala diferente da real.
    ;
    ; Um único corpo de transação é reaproveitado nas até 9 escritas (laço
    ; abaixo): a IMEM da PRU (2048 instruções) não comportaria 9 cópias dos 24
    ; macros. Os desvios condicionais QB* só alcançam +-511 instruções, e o
    ; corpo da transação tem ~500: por isso os saltos que o atravessam são
    ; JMP (endereço absoluto). tests/test_pru_asm.py confere isso.
    ;
    ; Registradores do laço (livres: nada abaixo os usa depois da configuração):
    ;   r6  = estágio (0 = AUTO_SEQ_EN; k = 1..8 -> RANGE_SEL do canal k-1)
    ;   r7  = comando de 16 bits da transação em curso
    ;   r8  = ctrl->auto_seq_mask       r9  = ctrl->range_sel
    ;   r12 = máscara de canais, deslocada 1 bit por estágio (bit 0 = canal do estágio)
    ;   r13 = nibbles de faixa, deslocados 4 bits por canal (nibble 0 = canal do estágio)
    ;   r10 = parte fixa do comando do canal do estágio; r11 = passo (1 << 9) entre canais
    LBBO &r8, r14, 28, 4     ; r8 = ctrl->auto_seq_mask (0-255)
    LBBO &r9, r14, 32, 4     ; r9 = ctrl->range_sel (nibbles de faixa)
    LSL r12, r8, 1           ; alinhada um estágio ATRÁS: o 1º LSR de cfg_canal a deixa com bit 0 = canal 0
    MOV r13, r9
    LDI r10, 0x0900          ; 0x0B00 (canal 0) - 0x0200: o 1º ADD de cfg_canal chega em 0x0B00
    LDI r11, 0x0200
    LDI r6, 0

cfg_proximo_comando:
    QBNE cfg_canal, r6, 0
    LDI r7, 0x0300           ; estágio 0: AUTO_SEQ_EN
    OR  r7, r7, r8           ; r7 = 0x0300 | máscara
    QBA cfg_envia

cfg_canal:
    LSR r12, r12, 1
    ADD r10, r10, r11
    QBBS cfg_canal_habilitado, r12, 0
    JMP cfg_comando_enviado  ; canal fora da varredura: não há o que escrever
cfg_canal_habilitado:
    AND r7, r13, 0x0F        ; código de faixa deste canal (4 bits)
    OR  r7, r7, r10          ; r7 = ((0x05 + canal) << 9) | 0x100 | código

cfg_envia:
    LSL r28, r7, 16          ; alinha aos bits 31..16 de r28, formato que
                              ; CMD_BIT espera
    LDI r23, 0

    CLR r30, r30, 3          ; abaixa o CS

    LDI r1, 200
delay_cs_setup_cfg:
    SUB r1, r1, 1
    QBNE delay_cs_setup_cfg, r1, 0

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
delay_cs_hold_cfg:
    SUB r1, r1, 1
    QBNE delay_cs_hold_cfg, r1, 0

    SET r30, r30, 3          ; levanta o CS

    LDI r1, 100
delay_cs_high_cfg:
    SUB r1, r1, 1
    QBNE delay_cs_high_cfg, r1, 0

cfg_comando_enviado:
    QBEQ cfg_sem_nibble, r6, 0   ; estágio 0 (AUTO_SEQ_EN) não consome nibble
    LSR r13, r13, 4              ; estágios 1-8: passa ao nibble do próximo canal (também quando o canal foi pulado)
cfg_sem_nibble:
    ADD r6, r6, 1
    QBEQ cfg_fim, r6, 9
    JMP cfg_proximo_comando
cfg_fim:

    ; --- Transação final: envia o comando AUTO_RST (0xA000, registrador de
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
    ;
    ; Registradores do laço principal (r6-r13 ficaram livres com o fim da configuração):
    ;   r6  = amostras atrasadas        r7 = buffers sobrescritos      r8 = quadros com preâmbulo != 0
    ;         (os três vão para ctrl->amostras_atrasadas/buffers_sobrescritos/quadros_preambulo_ruim
    ;         a cada troca de buffer -- ver memoria_pru.h)
    ;   r9  = atraso CS setup  r10 = atraso CS hold  r11 = atraso CS alto (iterações; 0 = padrão)
    ;   r12 = 2^31, o passo do rebase do contador de ciclos (ver rebase_contador)
    ;   r5  = os 16 bits lidos no SDO durante o comando (preâmbulo), zerado a cada quadro
    LBBO &r9, r14, 48, 12    ; r9, r10, r11 = ctrl->atraso_cs_setup/hold/alto
    QBNE atraso_setup_ok, r9, 0
    LDI r9, 200
atraso_setup_ok:
    QBNE atraso_hold_ok, r10, 0
    LDI r10, 100
atraso_hold_ok:
    QBNE atraso_alto_ok, r11, 0
    LDI r11, 100
atraso_alto_ok:

    LDI r6, 0
    LDI r7, 0
    LDI r8, 0
    SBBO &r6, r14, 36, 12    ; contadores publicados zerados
    LDI r12.w0, 0x0000
    LDI r12.w2, 0x8000       ; r12 = 0x80000000

    MOV r19, r24
    LDI r15, 0
    LDI r26, 0

    ; A configuração acima levou ~10 transações: o contador de ciclos é zerado de novo aqui, para a 1ª amostra sair
    ; um período depois (e não ser contada como atrasada). Antes da 1ª amostra não há grade de tempo a preservar.
    LDI r20, 0
    SBBO &r20, r18, 0, 4     ; CYCLE = 0
    MOV r17, r16             ; r17 = instante da próxima amostra = 0 + período
    QBA laco_principal

    ; [AMOSTRA ATRASADA] O instante desta amostra já passou: a PRU não está conseguindo a taxa pedida (o laço leva
    ; ~1400 ciclos por amostra com os atrasos de CS padrão) ou foi segurada (escrita na DDR demorada). A amostra sai
    ; agora mesmo e é contada. Se o atraso ainda é menor que 1 período, a grade original é mantida (as próximas
    ; alcançam o horário); se já passa de 1 período, a grade recomeça daqui -- senão o atraso cresceria sem limite
    ; e, ao passar de 2^31 ciclos, a comparação com sinal do wait_time se inverteria (uma espera de ~10 s).
amostra_atrasada:
    ADD r6, r6, 1
    ADD r17, r17, r16        ; próximo instante na grade
    SUB r20, r22, r17        ; agora - próximo instante
    QBBS transacao_spi, r20, 31     ; negativo: ainda dá para voltar à grade
    ADD r17, r22, r16        ; atraso de mais de 1 período: recomeça a grade a partir de agora
    QBA transacao_spi

laco_principal:
    LBBO &r16, r14, 0, 4
    LDI r5, 0                ; preâmbulo deste quadro (os CMD_BIT o acumulam)

    ; Pré-checagem do horário: só roda na folga ANTES do instante da amostra (a espera abaixo absorve), então não
    ; muda quando a amostra é tomada.
    LBBO &r22, r18, 0, 4
    SUB r20, r17, r22
    QBBS amostra_atrasada, r20, 31

wait_time:
    LBBO &r22, r18, 0, 4
    SUB r20, r17, r22
    QBBC wait_time, r20, 31

    ADD r17, r17, r16

transacao_spi:
    ; --- TRANSAÇÃO SPI (32 CICLOS) ---
    CLR r30, r30, 3         ; Abaixa o CS

    MOV r1, r9               ; atraso CS setup (padrão 200 iterações = 2,0 µs; o datasheet pede 30 ns)
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

    MOV r1, r10              ; atraso CS hold (padrão 100 = 1,0 µs; o datasheet pede 10 ns)
delay_cs_hold:
    SUB r1, r1, 1
    QBNE delay_cs_hold, r1, 0

    SET r30, r30, 3          ; Levanta o CS - fim da transação

    ; Tempo mínimo de CS alto entre transações (recarga do capacitor interno
    ; de amostragem do ADS8688), independente da frequência configurada.
    MOV r1, r11              ; atraso CS alto (padrão 100 = 1,0 µs; o datasheet pede 30 ns)
delay_cs_high_minimo:
    SUB r1, r1, 1
    QBNE delay_cs_high_minimo, r1, 0

    ; --- GRAVAÇÃO DIRETA NA MEMÓRIA DDR ---
    SBBO &r23, r19, 0, 2
    ADD r19, r19, 2

    ; [INTEGRIDADE] Preâmbulo: o SDO fica em 0 durante o comando (datasheet 8.4.1.1.4). 2 instruções, com o CS já
    ; alto e antes da espera da próxima amostra -- não mudam o instante de nenhuma amostra.
    QBEQ preambulo_ok, r5, 0
    ADD r8, r8, 1
preambulo_ok:

    ; [MODO AUTOMÁTICO] Sem incremento de índice de canal aqui — o ADS8688
    ; já avançou sozinho para o próximo canal da varredura automática na
    ; borda de descida de CS que acabou de acontecer nesta mesma transação
    ; (ver cabeçalho do arquivo).

    ; --- LÓGICA DE PING-PONG ---
    ADD r15, r15, 1
    QBNE continua, r15, r21

    LDI r15, 0
    ; [CORRIGIDO] O contador de ciclos NÃO é mais zerado aqui. Zerá-lo depois da transação da última amostra
    ; empurrava a 1ª amostra do buffer seguinte ~1400 ciclos (~7 µs, a duração da transação) além do período: um
    ; salto de ~0,7 amostra a cada troca de buffer a 100 kS/s, medido nas capturas reais (T7c: +0,697 em todas as
    ; 57 trocas). E, com um buffer mais longo que 2^32 ciclos (~21,5 s, taxa abaixo de ~48,8 kS/s), o contador
    ; saturava no meio do buffer. O rebase sem perda (rebase_contador, abaixo) resolve os dois.

    QBEQ troca_para_buffer_1, r26, 0

troca_para_buffer_0:
    LDI r26, 0
    MOV r19, r24
    LDI r27, 1
    SBBO &r27, r14, 12, 4    ; buffer_1_ready = 1 (acabou de encher)
    LBBO &r27, r14, 8, 4     ; buffer_0_ready: o ARM já terminou de copiar o buffer que vai ser reescrito?
    QBA confere_sobrescrita

troca_para_buffer_1:
    LDI r26, 1
    MOV r19, r25
    LDI r27, 1
    SBBO &r27, r14, 8, 4     ; buffer_0_ready = 1 (acabou de encher)
    LBBO &r27, r14, 12, 4    ; buffer_1_ready: idem

confere_sobrescrita:
    ; [INTEGRIDADE] Ainda marcado como pronto = o ARM não o esvaziou: a PRU vai sobrescrever dados não gravados.
    QBEQ publica_contadores, r27, 0
    ADD r7, r7, 1
publica_contadores:
    SBBO &r6, r14, 36, 12    ; amostras_atrasadas, buffers_sobrescritos, quadros_preambulo_ruim (1 vez por buffer)

continua:
    SBBO &r26, r14, 4, 4
    ; O contador passou de 2^31 (~10,7 s desde o último rebase)? r22 é a leitura feita para esta amostra.
    QBBS rebase_contador, r22, 31
    JMP laco_principal

    ; [REBASE SEM PERDA] O contador de ciclos da PRU não dá a volta: trava em 0xFFFFFFFF (~21,47 s a 200 MHz).
    ; Antes disso, subtrai 2^31 do contador E do instante da próxima amostra: a diferença entre os dois -- que é o
    ; que a espera usa -- não muda, e a grade de tempo continua exatamente a mesma. Os ciclos que passam entre a
    ; leitura e a escrita do contador (DELTA, abaixo) são somados de volta; um erro de 1-2 ciclos aqui vale 5-10 ns
    ; uma vez a cada 10,7 s (o antigo zero na troca de buffer perdia ~7 µs a cada buffer). Roda na folga entre
    ; amostras (o instante da próxima é r17, que só é deslocado junto com o contador).
rebase_contador:
    LBBO &r22, r18, 0, 4     ; CYCLE agora
    SUB r22, r22, r12        ; - 2^31
    ADD r22, r22, 4          ; DELTA: as 3 instruções até a escrita + a latência da leitura
    SBBO &r22, r18, 0, 4     ; CYCLE = CYCLE - 2^31 (sem perder os ciclos do meio)
    SUB r17, r17, r12        ; mesma grade: o instante da próxima amostra anda junto
    JMP laco_principal
