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
;     alto): até out/2026, os valores calibrados empiricamente (200/100/100
;     iterações de 2 ciclos = 2/1/1 µs), ~4 µs dos ~7 µs de cada amostra e o
;     que limitava a taxa a ~143 kS/s. Configuráveis desde out/2026 (ler_adc
;     --atraso-cs); desde 21/10/2026 o padrão é o mínimo do datasheet (SBAS582C,
;     tabela 7.6), 30/10/30 ns = 3/1/3: a varredura T7e não achou diferença de
;     qualidade até ele, e o teto subiu para ~326 kS/s.
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
;     --atraso-cs); com 200/100/100, a transação tem os mesmos 1166 ciclos do
;     firmware validado (tests/test_pru_asm.py confere). O padrão (0) é 3/1/3
;     desde 21/10/2026: 574 ciclos de CS baixo.
;
; --- REVISÃO DE 22/10/2026: GRADE EXATA -------------------------------------
;   - [JITTER] A espera era uma sondagem do contador: a amostra saía de 0 a 1
;     volta da sondagem depois do instante, ao acaso. Nas capturas de 21/10
;     (tom de 10 kHz), ~8,4 ns rms em todas as taxas e esperas de CS -- o
;     triplo do ruído do ADC nesse tom. Agora: sondagem só até faltarem
;     menos de 255 ciclos, e um laço de exatamente os ciclos que faltam
;     (espera_fina). O CS desce sempre no mesmo ciclo depois do instante.
;   - [FOLGA] O que roda entre duas amostras (DDR, troca de buffer, rebase)
;     pode demorar mais ou menos; a espera fina absorve, e a menor folga da
;     captura vai para shared_control (folga_minima_ciclos). Folga > 0 e
;     nenhuma amostra atrasada = toda amostra no ciclo exato da grade.
;   - [REBASE] O recuo da grade no rebase usava uma constante chutada (2
;     ciclos); agora a PRU mede, antes da 1ª amostra, a distância entre as
;     duas leituras do contador, e o rebase lê o contador de novo depois do
;     zero (ver rebase_contador).
;   - O período é lido uma vez (era relido da RAM compartilhada a cada
;     amostra) e active_buffer só é escrito na troca de buffer.
;   - O AUTO_RST virou o estágio 9 do laço de configuração (era uma cópia
;     inteira da transação): ~470 instruções a menos na IMEM.
;   No simulador (1 ciclo por instrução): quadro mínimo de 602 ciclos sem
;   troca de buffer e 615 com; a 312,5 kS/s (640 ciclos) sobram 25.
;   Validado na bancada (T7f, 22/10/2026): jitter de 0,00 ns, degrau de 0
;   ciclo nas trocas e nos rebases; folga de 3 a 13 ciclos a 312,5 kS/s.
;
; --- REVISÃO DE 22/10/2026 (2): QUADRO DE DURAÇÃO FIXA E TROCA ESPALHADA ----
;   - [DURAÇÃO FIXA] O quadro durava 605 + (bits 1 da amostra) ciclos: o OR
;     que acumulava um bit 1 esticava o SCLK (ver DATA_BIT). Medido no T7f: a
;     fração de amostras atrasadas de cada período da varredura J seguiu a
;     fração de amostras com tantos bits 1. Agora a leitura é um AND, sem
;     desvio: todo quadro dura o mesmo, qualquer que seja o sinal.
;   - [TROCA ESPALHADA] A troca de buffer fazia 5 acessos à RAM compartilhada
;     numa amostra só (~20 ciclos na placa). Agora ela só muda de buffer, e
;     os acessos vão um por amostra nas 5 seguintes (evento_de_buffer). O
;     rebase do contador não roda numa amostra com evento.
;   - [CS ALTO] A espera de CS alto mínimo (7 ciclos por amostra com o padrão)
;     só roda quando pedida acima de 9 iterações: até aí, o caminho entre a
;     subida e a próxima descida do CS já a garante (>= 19 ciclos).
;   No simulador com as latências medidas na placa (tests/pru_sim.py,
;   LATENCIAS_PRU_REAL): a 312,5 kS/s, folga de 41 ciclos numa amostra comum
;   (eram 20 a 35, conforme o sinal) e >= 31 com a troca (eram 3 a 13); teto
;   com período constante ~328 kS/s (era ~315). Falta a bancada (--grade).
; ==============================================================================
; PINOS (inalterado):
;   Bit 0 (r30) = SCLK   | Bit 1 (r30) = SDI/MOSI
;   Bit 2 (r31) = SDO/MISO | Bit 3 (r30) = CS
; ==============================================================================
; REGISTRADORES NOVOS/REAPROVEITADOS (configuração do modo automático, só
; usados uma vez, ANTES do laço principal — depois disso ficam sem uso):
;   r7 = registrador de rascunho onde o comando de 16 bits de cada
;        transação de configuração (AUTO_SEQ_EN, RANGE_SELn e, desde
;        22/10/2026, também o AUTO_RST) é montado, antes de ser alinhado para
;        os bits 31..16 de r28 (formato que CMD_BIT espera).
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

    ; NOTA: este bloco lê o SDO na mesma posição do DATA_BIT (o preâmbulo, que o
    ; laço principal confere) e mantém o CMD_BIT com EXATAMENTE a mesma duração
    ; do DATA_BIT em nível ALTO do SCLK, igual estava na versão validada em
    ; hardware. Remover essa simetria encurtou justo a margem de
    ; acomodação/aquisição antes da borda de descida, e é a suspeita mais
    ; provável para a distorção de 2x/período relatada historicamente.
    ; [DURAÇÃO FIXA, 22/10/2026] A leitura é um AND (r1 = 0 ou 4), sem desvio:
    ; ver DATA_BIT.
    LSL r5, r5, 1
    AND r1, r31, 4           ; SDO lido aqui (bit 2 de r31), no mesmo ciclo do QBBC de antes

    CLR r30, r30, 0          ; Desce o SCLK -> ADC lê o bit no SDI

    OR r5, r5, r1            ; o bit entra com o SCLK já baixo (no lugar de um NOP)
    NOP
    NOP
    .endm

; ==============================================================================
; MACRO: Lê 1 bit de dado do SDO (Ciclos 17-32 do frame do ADS8688)
; r23 = acumulador da amostra: cada bit entra no bit 2 (o MISO é o bit 2 de
; r31) e o DATA_BIT_ULTIMO alinha os 16 bits no fim (LSR de 2).
;
; [DURAÇÃO FIXA, 22/10/2026] Até aqui a leitura era QBBC + OR: um bit 1
; executava o OR e deixava o SCLK 1 ciclo a mais em nível alto. O quadro
; durava 605 + (número de bits 1 da amostra) ciclos na PRU de verdade -- de 0
; a 16 ciclos (80 ns) a mais, conforme o SINAL. Na varredura J do T7f
; (22/10/2026), a fração de amostras atrasadas em cada período bateu com a
; fração de amostras com tantos bits 1 (619 ticks: 5,58e-5 atrasadas e
; 5,53e-5 com 15 bits 1; 618: 8,07e-4 e 8,15e-4 com 14 ou mais; 617: 5,56e-3
; e 5,66e-3), e a "cauda aleatória da escrita na DDR" não existia. O
; instante da amostra (a descida do CS) nunca dependeu disso; a folga, o teto
; de taxa e o padrão do SCLK dependiam. Agora a leitura é um AND (sem desvio)
; e o bit entra com o SCLK já baixo, no lugar de um NOP: todo bit tem 9
; ciclos em alto e 7 em baixo, qualquer que seja o dado, e o MISO é lido no
; mesmo ciclo de antes (o 8º depois da subida do SCLK).
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
    AND r1, r31, 4           ; r1 = MISO << 2 (0 ou 4), sem desvio

    CLR r30, r30, 0          ; Desce o SCLK

    OR r23, r23, r1          ; o bit entra com o SCLK já baixo (no lugar de um NOP)
    NOP
    NOP
    .endm

; O 16º bit do laço principal: o mesmo DATA_BIT, com o alinhamento final no lugar de um NOP (nenhum ciclo a mais).
DATA_BIT_ULTIMO .macro
    NOP
    NOP
    NOP

    SET r30, r30, 0          ; Sobe o SCLK

    NOP
    NOP
    NOP
    NOP
    NOP
    NOP

    LSL r23, r23, 1
    AND r1, r31, 4

    CLR r30, r30, 0          ; Desce o SCLK

    OR r23, r23, r1
    LSR r23, r23, 2          ; os 16 bits estavam em r23[17:2]: alinha em r23.w0 para o SBBO
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

    ; Limite do buffer: 1.048.576 amostras (2 MB por buffer), em r4. O r21 é a próxima amostra com trabalho de troca
    ; de buffer (ver evento_de_buffer): no começo, só a última do buffer. Tem de ser > 5 (os eventos 1 a 5).
    LDI r4.w0, 0x0000
    LDI r4.w2, 0x0010    ; 0x00100000 em Hex = 1.048.576 (SAMPLES_PER_BUFFER de memoria_pru.h)
    MOV r21, r4

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
    ; Um único corpo de transação é reaproveitado nas até 9 escritas e no
    ; AUTO_RST (laço abaixo): a IMEM da PRU (2048 instruções) não comportaria
    ; uma cópia dos macros para cada uma. Os desvios condicionais QB* só alcançam +-511 instruções, e o
    ; corpo da transação tem ~500: por isso os saltos que o atravessam são
    ; JMP (endereço absoluto). tests/test_pru_asm.py confere isso.
    ;
    ; Registradores do laço (livres: nada abaixo os usa depois da configuração):
    ;   r6  = estágio (0 = AUTO_SEQ_EN; k = 1..8 -> RANGE_SEL do canal k-1; 9 = AUTO_RST)
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
    QBEQ cfg_auto_rst, r6, 9
    QBNE cfg_canal, r6, 0
    LDI r7, 0x0300           ; estágio 0: AUTO_SEQ_EN
    OR  r7, r7, r8           ; r7 = 0x0300 | máscara
    QBA cfg_envia

    ; Estágio 9 (o último): o comando AUTO_RST (0xA000, registrador de COMANDO) -- inicia a varredura automática a
    ; partir do canal habilitado de menor número. Usa o mesmo corpo de transação, com 16 DATA_BIT em vez de 8 (32
    ; ciclos, como todo comando do registrador de comando). Até 22/10/2026 era uma cópia inteira da transação (624
    ; instruções); a única diferença de tempo é a instrução que decide entre 8 e 16 DATA_BIT (5 ns a mais com o SCLK
    ; baixo, uma vez), e a IMEM ganhou espaço para a espera de precisão do laço principal.
cfg_auto_rst:
    LDI r7, 0xA000
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
    ; Escrita de registrador de programa: só 8 DATA_BIT (24 ciclos no total) -- NÃO 16. Ver nota grande acima.
    ; O AUTO_RST (estágio 9) completa os 32 ciclos com mais 8. r23 (dado lido) é descartado de propósito.
    QBNE cfg_dados_fim, r6, 9
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
    DATA_BIT
cfg_dados_fim:

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
    QBEQ cfg_fim, r6, 10
    JMP cfg_proximo_comando
cfg_fim:

    ; --- Fim da configuração do ADS8688 — início da captura de verdade ---
    ;
    ; Registradores do laço principal (r6-r13 ficaram livres com o fim da configuração):
    ;   r6  = amostras atrasadas        r7 = buffers sobrescritos      r8 = quadros com preâmbulo != 0
    ;   r12 = folga mínima (ciclos)     r13 = atraso máximo (ciclos)
    ;         (os cinco vão para shared_control a cada troca de buffer -- ver memoria_pru.h)
    ;   r9  = atraso CS setup  r10 = atraso CS hold  r11 = atraso CS alto (iterações; 0 = padrão)
    ;   r29 = ciclos entre as duas leituras do contador no rebase (medidos abaixo)
    ;   r5  = os 16 bits lidos no SDO durante o comando (preâmbulo), zerado a cada quadro
    ;   r16 = período em ciclos, lido UMA vez (o ler_adc reinicia a PRU a cada captura; até 22/10/2026 era relido
    ;         da RAM compartilhada a cada amostra, o que só gastava a folga)
    LBBO &r9, r14, 48, 12    ; r9, r10, r11 = ctrl->atraso_cs_setup/hold/alto (0 = o padrão, 3/1/3)
    QBNE atraso_setup_ok, r9, 0
    LDI r9, 3
atraso_setup_ok:
    QBNE atraso_hold_ok, r10, 0
    LDI r10, 1
atraso_hold_ok:
    QBNE atraso_alto_ok, r11, 0
    LDI r11, 3
atraso_alto_ok:
    ; CS alto de até 9 iterações (19 ciclos) o próprio caminho entre a subida e a descida seguinte já garante: no
    ; mais curto (amostra atrasada, sem espera), são >= 19 instruções, 95 ns (escrita na DDR, contadores, leitura do
    ; contador e o caminho de amostra_atrasada; tests/test_pru_asm.py confere). O datasheet pede 30 ns. r11 = 0 pula
    ; a espera; acima de 9, ela roda como pedida.
    SUB r1, r11, 10
    QBBC atraso_alto_pedido, r1, 31   ; r11 >= 10: a espera vale
    LDI r11, 0
atraso_alto_pedido:

    LDI r6, 0
    LDI r7, 0
    LDI r8, 0
    SBBO &r6, r14, 36, 12    ; contadores publicados zerados
    MOV r12, r16             ; folga mínima: começa no período (a folga de uma amostra nunca passa dele)
    LDI r13, 0
    SBBO &r12, r14, 60, 8

    ; [GRADE EXATA] Calibração do rebase do contador (ver rebase_contador): o rebase lê o contador, o zera e o lê de
    ; novo, e precisa saber quantos ciclos separam as duas leituras. É a mesma sequência daqui (leitura, escrita
    ; no bloco de controle da PRU, leitura), só que escrevendo no WAKEUP_EN, o registrador vizinho, com o valor que
    ; ele já tem (não muda nada: só vale para a instrução SLP, que este firmware não usa). As latências de verdade
    ; (LBBO/SBBO nesse bloco) entram na medida; o simulador dá 2.
    SUB r27, r18, 4          ; r27 = 0x22008 (WAKEUP_EN)
    LBBO &r28, r27, 0, 4
    LBBO &r1, r18, 0, 4
    SBBO &r28, r27, 0, 4
    LBBO &r20, r18, 0, 4
    SUB r29, r20, r1
    SBBO &r29, r14, 68, 4    ; ctrl->ciclos_rebase (diagnóstico)
    LDI r20, 2               ; VERSAO_PROTOCOLO_PRU (memoria_pru.h): o ler_adc confere que é este firmware
    SBBO &r20, r14, 72, 4

    MOV r19, r24
    LDI r15, 0
    LDI r26, 0
    SBBO &r26, r14, 4, 4     ; active_buffer = 0 (depois, só muda na troca de buffer)

    ; A configuração acima levou ~10 transações: o contador de ciclos é zerado de novo aqui, para a 1ª amostra sair
    ; um período depois (e não ser contada como atrasada). Antes da 1ª amostra não há grade de tempo a preservar.
    LDI r20, 0
    SBBO &r20, r18, 0, 4     ; CYCLE = 0
    MOV r17, r16             ; r17 = instante da próxima amostra = 0 + período
    QBA laco_principal

    ; [AMOSTRA ATRASADA] O instante desta amostra já passou: a PRU não está conseguindo a taxa pedida (o trabalho
    ; entre duas amostras não coube no período) ou foi segurada (uma escrita na DDR que demorou). A amostra sai agora
    ; mesmo, é contada, e o atraso entra no máximo. Se o atraso ainda é menor que 1 período, a grade original é
    ; mantida (as próximas alcançam o horário); se já passa de 1 período, a grade recomeça daqui -- senão o atraso
    ; cresceria sem limite e, ao passar de 2^31 ciclos, a comparação com sinal se inverteria (uma espera de ~10 s).
amostra_atrasada:
    ADD r6, r6, 1
    SUB r1, r22, r17         ; quanto o instante já tinha passado (ciclos)
    MAX r13, r13, r1
    ADD r17, r17, r16        ; próximo instante na grade
    SUB r20, r22, r17        ; agora - próximo instante
    QBBS transacao_spi, r20, 31     ; negativo: ainda dá para voltar à grade
    ADD r17, r22, r16        ; atraso de mais de 1 período: recomeça a grade a partir de agora
    QBA transacao_spi

    ; [GRADE EXATA, 22/10/2026] Até aqui a espera era só uma sondagem: ler o contador até passar do instante. A
    ; amostra saía na 1ª leitura depois dele -- de 0 a 1 volta da sondagem (~6 ciclos na PRU de verdade) mais
    ; tarde, ao acaso. Medido nas capturas de 21/10 (tom de 10 kHz): ~8,4 ns rms de jitter em todas as taxas e
    ; esperas de CS, o triplo do ruído do ADC num tom desses. Agora a espera tem duas fases:
    ;   - grossa: sondagem, só enquanto faltam mais de 255 ciclos;
    ;   - fina: com R = ciclos que faltam (lidos UMA vez), um laço de exatamente R ciclos (o bit 0 de R vale 1
    ;     ciclo, e cada volta do laço vale 2). Da leitura até a descida do CS são sempre 11 + R ciclos: o CS
    ;     desce num ciclo fixo depois do instante da grade, qualquer que seja o caminho até ali.
    ; O que roda antes da leitura (escrita na DDR, troca de buffer, rebase) pode demorar mais ou menos: a espera
    ; fina absorve, desde que sobre folga (R >= 0). A menor folga da captura vai para o r12 (ver memoria_pru.h).
laco_principal:
    LDI r5, 0                ; preâmbulo deste quadro (os CMD_BIT o acumulam)
    LBBO &r22, r18, 0, 4     ; 1ª leitura do contador depois do trabalho da amostra anterior
    SUB r20, r17, r22        ; R = ciclos até o instante da amostra
    QBBS amostra_atrasada, r20, 31
    MIN r12, r12, r20        ; folga mínima
    SUB r1, r20, 255         ; R - 255 < 0: faltam menos de 255 ciclos. (O sinal da subtração, e não um QBGE/QBLT,
    QBBS espera_fina, r1, 31 ; cuja ordem de operandos é a contrária da leitura: QBLT x, r1, 255 = "se 255 < r1".)

espera_grossa:
    LBBO &r22, r18, 0, 4
    SUB r20, r17, r22
    QBBS amostra_atrasada, r20, 31  ; uma leitura demorou tanto que o instante passou
    NOP                      ; da leitura até espera_fina: 5 instruções, como no caminho da 1ª leitura (com o MIN)
    SUB r1, r20, 255
    QBBC espera_grossa, r1, 31

espera_fina:
    QBBC espera_fina_par, r20, 0
    NOP                      ; R ímpar: 1 ciclo a mais
espera_fina_par:
    LSR r1, r20, 1
    ADD r1, r1, 1            ; R/2 + 1 voltas de 2 ciclos (a última é a fixa)
espera_fina_laco:
    SUB r1, r1, 1
    QBNE espera_fina_laco, r1, 0

    ADD r17, r17, r16

transacao_spi:
    ; --- TRANSAÇÃO SPI (32 CICLOS) ---
    CLR r30, r30, 3         ; Abaixa o CS: o instante da amostra

    MOV r1, r9               ; atraso CS setup (padrão 3 iterações = 30 ns, o mínimo do datasheet)
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
    DATA_BIT_ULTIMO          ; o 16º: alinha os bits em r23.w0

    MOV r1, r10              ; atraso CS hold (padrão 1 iteração = 10 ns, o mínimo do datasheet)
delay_cs_hold:
    SUB r1, r1, 1
    QBNE delay_cs_hold, r1, 0

    SET r30, r30, 3          ; Levanta o CS - fim da transação

    ; Tempo mínimo de CS alto entre transações (recarga do capacitor interno
    ; de amostragem do ADS8688), independente da frequência configurada.
    ; [22/10/2026] Com r11 = 0 (atraso pedido de até 9 iterações, o padrão incluído), a espera não roda: o caminho
    ; daqui até a próxima descida do CS já tem >= 19 ciclos (95 ns), mesmo com a amostra atrasada (ver
    ; atraso_alto_ok). Eram 7 ciclos por amostra no caminho crítico, sem efeito no CS.
    QBEQ cs_alto_garantido, r11, 0
    MOV r1, r11              ; atraso CS alto pedido (iterações de 2 ciclos)
delay_cs_high_minimo:
    SUB r1, r1, 1
    QBNE delay_cs_high_minimo, r1, 0
cs_alto_garantido:

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
    ; r15 = amostras gravadas no buffer atual; r21 = a próxima com trabalho de troca (evento_de_buffer). Numa amostra
    ; comum, só estas 2 instruções (as mesmas de antes).
    ADD r15, r15, 1
    QBNE continua, r15, r21

    ; [TROCA ESPALHADA, 22/10/2026] Até aqui, a amostra da troca fazia tudo de uma vez: 5 acessos à memória
    ; compartilhada (marcar o buffer cheio, conferir o outro, publicar active_buffer, os contadores e a folga). Na
    ; PRU de verdade, ~20 ciclos a mais que uma amostra comum: a 312,5 kS/s, sobravam 3 a 13 ciclos de folga nela
    ; (T7f). Agora a troca em si só muda de buffer (nenhum acesso à memória), e o resto vai para as 5 amostras
    ; seguintes, um acesso por amostra (eventos 1 a 5). O rebase do contador não roda numa amostra com evento:
    ; fica para a seguinte (o contador só trava em 2^32, ~10 s depois de 2^31).
    ; [CORRIGIDO] O contador de ciclos NÃO é zerado na troca. Zerá-lo depois da transação da última amostra
    ; empurrava a 1ª amostra do buffer seguinte ~1400 ciclos (~7 µs, a duração da transação) além do período: um
    ; salto de ~0,7 amostra a cada troca de buffer a 100 kS/s, medido nas capturas reais (T7c: +0,697 em todas as
    ; 57 trocas). E, com um buffer mais longo que 2^32 ciclos (~21,5 s, taxa abaixo de ~48,8 kS/s), o contador
    ; saturava no meio do buffer. O rebase sem perda (rebase_contador, abaixo) resolve os dois.
    ; Todo o trabalho fica antes da 1ª leitura do contador da amostra seguinte: a espera fina o absorve.
evento_de_buffer:
    QBEQ troca_de_buffer, r15, r4
    ADD r21, r21, 1          ; o próximo evento é na amostra seguinte
    QBEQ evento_1, r15, 1
    QBEQ evento_2, r15, 2
    QBEQ evento_3, r15, 3
    QBEQ evento_4, r15, 4

    ; Evento 5: a folga e o atraso máximo (até aqui, com a troca e os eventos 1 a 4). Fim dos eventos.
    SBBO &r12, r14, 60, 8    ; folga_minima_ciclos, atraso_maximo_ciclos
    MOV r21, r4              ; o próximo evento é a troca, no fim do buffer
    JMP laco_principal

troca_de_buffer:
    LDI r15, 0
    LDI r21, 1               ; evento 1 na 1ª amostra do buffer novo
    QBEQ troca_para_buffer_1, r26, 0
    LDI r26, 0               ; o 1 acabou de encher: grava no 0
    MOV r19, r24
    JMP laco_principal
troca_para_buffer_1:
    LDI r26, 1               ; o 0 acabou de encher: grava no 1
    MOV r19, r25
    JMP laco_principal

    ; Evento 1: marca o buffer que acabou de encher (o que NÃO é o r26). É o que o ARM espera para copiá-lo.
evento_1:
    LDI r27, 1
    QBEQ evento_1_buffer_1, r26, 0
    SBBO &r27, r14, 8, 4     ; buffer_0_ready = 1
    JMP laco_principal
evento_1_buffer_1:
    SBBO &r27, r14, 12, 4    ; buffer_1_ready = 1
    JMP laco_principal

    ; Evento 2: active_buffer (só informativo para o ARM; até 22/10/2026 era escrito a cada amostra).
evento_2:
    SBBO &r26, r14, 4, 4
    JMP laco_principal

    ; Evento 3: [INTEGRIDADE] o buffer que está sendo reescrito ainda está marcado como pronto? Então o ARM não o
    ; esvaziou, e a PRU está sobrescrevendo dados não gravados.
evento_3:
    QBEQ evento_3_buffer_0, r26, 0
    LBBO &r27, r14, 12, 4    ; buffer_1_ready
    QBA evento_3_confere
evento_3_buffer_0:
    LBBO &r27, r14, 8, 4     ; buffer_0_ready
evento_3_confere:
    QBNE evento_3_sobrescrito, r27, 0    ; (laco_principal está longe demais para um QB*: o JMP vai até lá)
    JMP laco_principal
evento_3_sobrescrito:
    ADD r7, r7, 1
    JMP laco_principal

    ; Evento 4: amostras_atrasadas, buffers_sobrescritos, quadros_preambulo_ruim (1 vez por buffer).
evento_4:
    SBBO &r6, r14, 36, 12
    JMP laco_principal

continua:
    ; O contador passou de 2^31 (~10,7 s desde o último rebase)? r22 é a última leitura feita para esta amostra.
    QBBS rebase_contador, r22, 31
    JMP laco_principal

    ; [REBASE SEM PERDA] O contador de ciclos da PRU não dá a volta: trava em 0xFFFFFFFF (~21,47 s a 200 MHz).
    ; Antes disso, o contador é ZERADO e o instante da próxima amostra recua o mesmo tanto -- a diferença entre os
    ; dois, que é o que a espera usa, não muda, e a grade de tempo continua a mesma.
    ; [CORRIGIDO em 21/10/2026] Com a PRU rodando, uma escrita no contador o ZERA, qualquer que seja o valor: o
    ; firmware anterior escrevia CYCLE - 2^31 e a grade atrasava 5 a 13 µs a cada 10,74 s (varredura T7e).
    ;
    ; O recuo é o valor lido (v) mais os ciclos entre essa leitura e o zero valer. Até 22/10/2026 esses ciclos eram
    ; uma constante chutada (2: "1 a 4 na PRU de verdade"); um erro de 1 ciclo deslocava a grade em 5 ns a cada
    ; 10,7 s. Agora eles são medidos: a 2ª leitura (u) conta os ciclos desde o zero, e a distância entre as duas
    ; leituras (r29) foi medida antes da captura com a mesma sequência de instruções. Daí:
    ;     zero - 1ª leitura = r29 - u     e     recuo = v + r29 - u
    ; Roda na folga entre amostras (o instante da próxima é r17, que só é deslocado junto com o contador).
rebase_contador:
    LDI r20, 0
    LBBO &r22, r18, 0, 4     ; v = CYCLE agora
    SBBO &r20, r18, 0, 4     ; CYCLE = 0
    LBBO &r1, r18, 0, 4      ; u = ciclos desde o zero
    SUB r17, r17, r22
    SUB r17, r17, r29
    ADD r17, r17, r1         ; o instante da próxima amostra, no referencial novo
    JMP laco_principal
