# SH-Analyzer — Propostas de melhoria

Lista **só do que ainda está por fazer**, com o motivo medido, a proposta e como saber que deu certo. O que já foi
feito sai daqui: a história fica no `git log` e, para o relatório, em [`report-notes.md`](report-notes.md).

Cada item tem um código (F = firmware/aquisição, P = Python, T = testes/CI, R = repositório/dados/documentação,
H = hardware, S = sondas) e as colunas: **ganho** (o que melhora), **esforço** e se **toca a PRU** — mudança no
assembly só conta como feita depois de montada com `clpru` e validada no hardware.

Revisado em 22/10/2026. Saíram daqui, nesta ordem:

* a revisão do firmware (salto de 7 µs na troca de buffer, contadores de integridade, cabeçalho v4), a revisão dos
  testes e o novo `compactar_amostras.py`; a análise das capturas de bancada de 19/10 trouxe o F9 e o P6;
* R1 a R4 e T1: dados fora do repositório, nomes em inglês sem espaço nem acento, contagem de testes num lugar só,
  backups do Altium fora do git, `.gitattributes`/`.editorconfig`/`CITATION.cff` e a CI compilando o C e passando o
  `shellcheck`;
* a revisão do `adc_tool`: o P2 (importações sob demanda) e a parte do gráfico do P1; trouxe o P8;
* o P7, como opções extras do `--bandas-iec`: janelas sincronizadas e agregação de 3 s/10 min da IEC 61000-4-30;
* o R2 (histórico do git sem os dados antigos, `.git` de ~90 para ~29 MB num clone novo);
* o P6 (salto nas trocas de buffer em µs, comparado com os outros segmentos), o F9 na análise (o `medir_captura`
  pula 200 µs; as duas ferramentas avisam), o P4 (taxa da PRU por padrão, `--fs-pedida`), o P3 (correção de sonda
  em `contexto`), o P5 (atributos de proveniência no HDF5), o S8 (aviso de perfil com mais de 1 ano) e o F5
  (cabeçalho v5: versão do firmware e taxa medida pelo ARM). A conferência nas capturas de 19/10 mostrou que o salto
  antigo também derruba o SINAD de uma FFT de vários blocos (63 → 22 dB) e puxa a frequência em +1,5 ppm;
* o F2 (21/10, T7e): as esperas do CS desceram ao mínimo do datasheet (`3,1,3`) sem perda, e o padrão passou a
  312,5 kS/s;
* o F1 (21 e 22/10, T7e e T7f): a revisão do firmware rodou no hardware. O salto de 7 µs na troca sumiu; o defeito
  do rebase do contador apareceu e foi corrigido; e a grade ficou exata (espera de precisão, folga publicada, rebase
  autocalibrado: jitter de 8,5 → 0,00 ns). Os números estão em [`bench-results.md`](bench-results.md#t7f-a-grade-de-tempo);
* o F11 (o `ler_adc` e o `setup.sh` conferem no `/proc/iomem` que a DDR dos buffers está fora do Linux), o F12 (o
  simulador com as latências medidas: reproduz a folga do T7f), a parte do F6 que não pede a PRU (SIGTERM e SIGHUP
  como o Ctrl+C; a PRU parada no fim da captura) e o F14, que perdeu o motivo: a "cauda da escrita na DDR" era o
  quadro que dependia do dado (F15).

---

## 1. Avaliação geral

**O que está bem resolvido** (manter): o Python é um pacote em camadas cujas regras são conferidas por teste
(`test_arquitetura.py`); as entradas em `scripts/` são finas e rodam com `uv run`; há CI, contrato automático
C ↔ Python, um simulador do assembly da PRU, testes em paralelo; cada
`.bin` se descreve sozinho (cabeçalho com CRC, faixa do ADC, integridade da captura); os dados brutos têm um
arquivamento sem perdas conferido bit a bit; a documentação cobre operação, arquitetura, laboratório e relatório.

### Avaliação do firmware (22/10/2026)

Feita com as 46 capturas do T7f e uma releitura do `spi_core.asm`, do `pru_main.c`, do `ler_adc.c`, do `setup.sh` e
da configuração da BeagleBone.

**Validado no hardware (não mexer sem motivo):**

* **A grade de tempo é exata:** jitter de 0,00 ns (piso do método ~0,3 ns), degrau de zero ciclo em 89 trocas de
  buffer e 28 rebases do contador, nenhuma amostra fora da grade a 312,5 kS/s (5 min, ARM ocupado, 2 canais).
* **A integridade do SPI:** 0 quadros com ruído no SDO em todas as capturas desde 19/10, com o SCLK a ~10,7 MHz.
* **O ADC no nível do datasheet:** o ruído com o tom é o da entrada em curto (0,77 LSB); o que sobra no SINAD é do
  gerador.
* **O protocolo ARM ↔ PRU:** o `ler_adc` recusa a captura se a PRU estiver com outro firmware; os contadores
  (atrasadas, sobrescritos, SDO) e a folga vão para o cabeçalho.
* **O ARM acompanha:** 0 buffers sobrescritos, também com um `dd` enchendo a DDR. O `ler_adc` tem ~3,4 s por bloco
  para gravar 2 MB.

**Onde ainda há margem ou risco, medido:**

1. **A folga a 312,5 kS/s é de só 3 a 5 ciclos (15 a 25 ns)** (F10). Na PRU real, o quadro comum leva ~612 ciclos
   (de 611 a 619, ao acaso: a escrita na DDR passa pelo barramento do ARM) e o da troca de buffer, ~634 (de 631 a
   638): a troca faz 5 acessos à memória compartilhada de uma vez (~22 ciclos). Até agora, nenhuma amostra saiu
   atrasada em ~130 trocas a 312,5 kS/s. Mas a cauda da escrita na DDR é aleatória: numa captura de horas (~1 000
   trocas por hora), uma troca atrasar alguns ciclos é plausível. Seria contada e é pequena (5 a 20 ns, uma
   amostra), mas tira o "toda amostra no ciclo exato".
2. **A reserva da DDR depende de uma linha fora do projeto** (F11). Os buffers ficam em `0x9F000000`, os últimos
   16 MB da DDR da BeagleBone. O Linux não os usa só porque o `/boot/uEnv.txt` da placa tem `mem=496M` (conferido em
   22/10: `/proc/cmdline`). Numa placa ou imagem nova sem essa linha, o Linux e a PRU escreveriam na mesma memória,
   em silêncio: capturas corrompidas e travamentos ao acaso. Nada no projeto confere isso hoje (o comentário no
   `AM335x_PRU.cmd` não reserva nada).
3. **O simulador prevê folga demais** (F12). Com 1 ciclo por instrução, ele dava 25 ciclos de folga onde a placa tem
   3 a 5. A PRU mediu 7 ciclos para um `LBBO` + `SBBO` no bloco de controle (o simulador conta 2). Sem calibrar as
   latências, o simulador não diz se uma mudança cabe.
4. **Um `kill` (SIGTERM) ou a queda do ssh deixam o cabeçalho incompleto** (F6): só o Ctrl+C reescreve o cabeçalho
   final (blocos, contadores, folga). E a PRU continua amostrando depois que o `ler_adc` sai.
5. **A estabilidade em 1 h com o firmware atual não foi medida** (F13). A captura mais longa do T7f tem 5 min; a de
   10 min (T7c) é do firmware antigo. A análise de uma captura de 1 h também esbarra no P1 (memória).
6. **O teto com período constante é ~315 kS/s.** Acima disso, até ~322 kS/s, só a troca de buffer atrasa (F10 a
   levaria a ~322 kS/s); acima de ~323 kS/s, as amostras comuns. Mais que isso pede o SPI mais rápido (F3: ~450 kS/s
   no papel). Os 500 kS/s do ADS8688 são divididos entre os canais, e o filtro interno de ~15 kHz não sai.

**Recomendação, em ordem:** F10 (a folga, que fecha o item 1), F11 (uma conferência de poucas linhas que evita o
pior defeito possível) e F12 (para a folga prevista bater com a medida), validados juntos com
`./varrer_taxa.sh --grade` (~15 min). Depois, o F6 e o F13. O F3 só quando a taxa acima de 315 kS/s for necessária.

**Atualização, mais tarde no mesmo dia (T3 e T1 a 312,5 kS/s e uma releitura da parte J):** o item 1 tinha outra
causa. O quadro comum durava **605 + (bits 1 da amostra) ciclos**: a fração de amostras atrasadas de cada período da
parte J bateu com a fração de amostras com tantos bits 1, por 4 décadas (F15). Não havia cauda aleatória da DDR. As
correções F15 e F10 estão no `spi_core.asm` (o simulador calibrado prevê folga ≥ 29 ciclos a 312,5 kS/s, qualquer
que seja o sinal); os itens 2 a 4 foram resolvidos (F11, F12, F6 sem o bloco parcial). Falta a bancada:
`./varrer_taxa.sh --grade`.

**Onde estão os outros limites (fora do firmware):**

1. **A taxa de 312,5 kS/s cobre a banda até ~140 kHz com 1 canal; com 2 canais, até ~70 kHz.** A cadeia de tensão
   atenua ~30 dB em 140 kHz (o filtro de ~15 kHz do ADC): falta o T3 até lá.
2. **Converter uma captura longa para Volts ainda usa o sinal inteiro em float64** (8 bytes por amostra): a análise
   de 10 min a 312,5 kS/s (188 milhões de amostras) pede ~1,5 GB de RAM; 1 h não caberia (P1).

---

## 2. Prioridade

| Código | Item | Ganho | Esforço | PRU? | Depende de |
|---|---|---|---|---|---|
| **F15** | Quadro de duração fixa: ler o bit sem desvio (**implementado**, falta a bancada) | Alto: folga independente do sinal; a amostra comum ganha até 15 ciclos | Baixo | sim | — |
| **F10** | Troca de buffer espalhada; espera de CS alto só quando pedida (**implementado**, falta a bancada) | Alto: folga de 3 → ≥ 29 ciclos a 312,5 kS/s (com o F15); teto ~315 → ~327 kS/s | Baixo | sim | — |
| **S1** | Calibrar a sonda de corrente (T10) com hold-out | Alto para corrente | Médio (bancada) | não | — |
| **P1** | Análise de capturas longas por blocos (sem o sinal inteiro em float64) | Médio: 10 min = 1,6 GB; 1 h não cabe | Médio | não | — |
| **P8** | Potência, impedância e transferência V/I por frequência | Alto para pesquisa de emissão | Médio | não | S3 |
| **F6** | Gravar o bloco parcial no fim de uma captura indefinida | Baixo–Médio | Baixo | sim (publicar a posição) | F10 |
| **F13** | Estabilidade em 1 h no padrão (grade, folga, frequência, amplitude) | Médio: o número do relatório | Baixo (bancada) | não | F10, P1 |
| **F9** | Descartar o transitório de troca de faixa já na PRU (a análise já descarta) | Baixo: dado certo desde a 1ª amostra | Baixo | sim | — |
| **F3** | SPI rápido, ~15,4 MHz, com a leitura em 3 fases (**implementado como `--spi rapido`**, falta a bancada) | Alto: teto ~327 → ~418 kS/s; 400 kS/s exatos | Médio | sim | F10, F15 |
| **F4** | `SAMPLES_PER_BUFFER` vindo do ARM, não duplicado no `.asm` | Médio: fim de uma sincronia manual | Baixo | sim | — |
| **F7** | Conferência rápida do `calibrar_sonda.sh` mais leve na BeagleBone | Médio | Baixo | não | medir na BBB |
| **S2–S7** | Fase, subamostragem, perfil absoluto, teto de ganho, repetições | Alto para V×I | Médio–Alto | não | S1 |
| **F8** | Endereço do canal no SDO (verificar a ordem dos canais a cada amostra) | Baixo–Médio | Médio | sim | F3 |
| **H1–H2** | Isolador contra o BOM, pontos de teste na próxima PCB | Baixo–Médio | Baixo–Médio | não | — |
| **T2–T3** | Testes de host do C; cobertura da plotagem | Baixo | Baixo | não | — |

---

## 3. Firmware e aquisição

### F10 — Folga na troca de buffer

**Por quê.** A 312,5 kS/s (640 ciclos), a troca de buffer deixa 3 a 5 ciclos de folga (T7f): ela faz, de uma vez,
5 acessos à memória compartilhada (marca o buffer cheio, lê o outro, publica `active_buffer`, os contadores e a
folga), ~22 ciclos a mais que uma amostra comum. E toda amostra em dia ainda espera o CS alto mínimo (`A` = 3
iterações, 7 ciclos), que o próprio caminho entre duas amostras já garante: o CS fica alto ≥ 25 ciclos mesmo sem a
espera, e 66 a 312,5 kS/s.

**Proposta.**

* **Espalhar a troca.** Na amostra da troca, só o essencial: o ponteiro de escrita passa para o outro buffer e o
  contador volta a 0. O resto vai para as amostras 1, 2 e 3 do buffer novo, um ou dois acessos por amostra. O gatilho
  é o mesmo comparador de hoje (`QBNE continua, r15, r21`): o `r21` vira "a próxima amostra com trabalho" (1, 2, 3
  e então o tamanho do buffer), sem nenhuma instrução a mais por amostra comum. O rebase do contador não roda nessas
  amostras (fica para a seguinte).
* **A espera de CS alto só quando faz falta:** com `A` ≤ 10 iterações (100 ns), o caminho em dia a pula (1
  instrução em vez de 7 ciclos); a amostra atrasada, que sai emendada na anterior, continua esperando.

Estimativa: a troca passa a custar ~5 a 8 ciclos a mais que uma amostra comum (era ~22) e toda amostra ganha ~6;
folga de ~18 ciclos a 312,5 kS/s; teto com período constante de ~315 para ~322 kS/s (o limite passa a ser a cauda da
escrita na DDR nas amostras comuns). O atraso de 1 a 3 amostras para marcar o buffer cheio (até 10 µs) não muda nada
para o ARM, que olha a cada 2 ms.

**Como saber que deu certo.** No simulador calibrado (F12), a folga prevista; na bancada, `./varrer_taxa.sh --grade`:
folga ≥ 15 ciclos em todas as capturas do padrão, e na parte J nenhuma atrasada até ~322 kS/s.

**Estado em 22/10/2026: implementado, falta a bancada.** A troca só muda de buffer (nenhum acesso à memória); os 5
acessos vão um por amostra nas 5 seguintes (buffer pronto, `active_buffer`, conferência de sobrescrita, contadores,
folga). O rebase não roda numa amostra com evento. A espera de CS alto só roda pedida acima de 9 iterações: o caminho
mais curto entre a subida e a descida seguinte já tem 19 ciclos (95 ns; o datasheet pede 30 ns). No simulador
calibrado, com o F15: folga de 40 ciclos numa amostra comum e ≥ 29 com a troca e os eventos, a 312,5 kS/s; teto ~327 kS/s
(`tests/test_pru_asm.py`). A `--grade` agora vai até 590 ticks (339 kS/s) e recusa o firmware anterior.

### F15 — Quadro de duração fixa (a leitura do bit sem desvio)

**Por quê.** O `DATA_BIT` lia o MISO com `QBBC` + `OR`: um bit 1 executava o `OR` e deixava o SCLK 1 ciclo a mais em
nível alto. O quadro durava **605 + (bits 1 da amostra) ciclos** na placa: 0 a 16 ciclos (até 80 ns) a mais, conforme
o sinal. Na parte J do T7f, a fração de amostras atrasadas de cada período bateu com a fração de amostras com tantos
bits 1 (619 ticks: 5,58 × 10⁻⁵ contra 5,53 × 10⁻⁵ com 15 bits 1; 616 ticks: 2,44 × 10⁻² contra 2,56 × 10⁻²), e as 43
capturas de calibração de 22/10 tiveram folga de exatamente 20 ciclos (640 − 605 − 15). O instante da amostra nunca
dependeu disso; a folga, o teto e o padrão do SCLK, sim.

**Proposta e estado (implementado, falta a bancada).** A leitura vira `AND r1, r31, 4` no mesmo ciclo do `QBBC` de
antes, e o bit entra no acumulador com o SCLK já baixo, no lugar de um NOP; o 16º bit alinha os 16 bits (um `LSR` no
lugar de outro NOP). Todo bit tem 9 ciclos em alto e 7 em baixo; o quadro não ganhou nenhum ciclo. O mesmo na leitura
do preâmbulo (`CMD_BIT`).

**Como saber que deu certo.** Na `--grade`: a mesma folga em todas as capturas do padrão, com o tom e em curto; na
parte J, nenhuma amostra comum atrasada até ~334 kS/s (599 ticks). E o SINAD/THD do tom igual ou melhor que no T7f
(o padrão do SCLK deixa de variar com o dado).

### F3 — SPI mais rápido

**Por quê.** Os 32 bits de cada quadro levam ~2,9 µs (~20 ciclos por bit de comando, ~16 por bit de dado: SCLK de
~10,7 MHz). O ADS8688 e o isolador aceitam 17 MHz. Com o quadro fixo e a troca espalhada, o teto do SPI padrão é
~327 kS/s; 400 kS/s exatos (500 ticks) pedem um quadro mais curto.

**Estado em 22/10/2026: implementado como opção (`ler_adc --spi rapido`), falta a bancada.** A tag `v0.7` é o
backup do firmware anterior (o mesmo, sem o modo rápido). No modo rápido:

* **bits de 13 ciclos** (65 ns: ~15,4 MHz), 6 em alto e 7 em baixo, nos 32 bits; o MOSI fica parado em 0 (NO_OP).
  O CS fica baixo 430 ciclos (eram 573). A configuração do ADC continua com os bits de sempre;
* **cada bit de dado é lido em 3 instantes** depois da borda do SCLK que o lança: A = 60 ns (logo antes da borda
  seguinte, como um SPI comum), B = 75 ns (a mesma latência do modo padrão, que lê certo desde 19/10) e C = 90 ns.
  Grava-se a B (ou a pedida: `rapido:a`, `rapido:c`), e a PRU conta os quadros em que A ou C discordam de B, sem
  desvio que dependa do dado. É a margem de tempo do SDO (o caminho de volta pelo isolador, ~50 a 70 ns), medida pela
  própria PRU: A errada = o bit ainda não tinha voltado; C errada = o seguinte já tinha. Substitui o osciloscópio no
  SCLK/SDO, que não dá para ligar;
* protocolo 3 (`modo_spi` e as divergências no `shared_control`) e cabeçalho v7 (o modo e as divergências).

No simulador calibrado: folga de 173 ciclos a 312,5 kS/s; a 400 kS/s, 22 ciclos e a grade exata; teto com período
constante ~418 kS/s (a ~428, as amostras comuns). Com o modelo do caminho do SDO (`ModeloADC.atraso_ciclos`), a
palavra sai certa nas 3 fases para caminhos de 25 a 55 ns, e as divergências acusam um caminho longo ou curto demais.

**Como saber que deu certo.** `./varrer_taxa.sh --spi` (~11 min): na parte P (312,5 kS/s), o mesmo SINAD, ruído e
THD no padrão e no rápido, e **0 divergências** na fase gravada; no ideal, também em A e C (margem de ≥ 15 ns para
cada lado). Na S, 60 s a 400 kS/s sem amostra atrasada; na T, o teto perto de 418 kS/s; na U, o ruído em curto igual
ao do padrão. Se a A divergir, a B ainda vale (o caminho passa de 60 ns); se a C divergir, idem (o bit seguinte chega
antes de 90 ns). Se a própria B estiver errada, o SINAD cai (bits trocados): volte ao padrão e traga as capturas.
Com tudo certo, o rápido vira o padrão. Os 500 kS/s do ADS8688 são somados entre os canais: 150 kHz em 2 canais ao
mesmo tempo pedem outro ADC.

### F4 — `SAMPLES_PER_BUFFER` vindo do ARM

**Por quê.** O tamanho do bloco (1.048.576) está em `memoria_pru.h` e, de novo, num `LDI r21` do `.asm`: mudar um
lado sem o outro desalinha a troca de buffer sem nenhum erro.

**Proposta.** Um campo `amostras_por_buffer` em `shared_control`, escrito pelo `ler_adc` e lido pela PRU uma vez
(como os atrasos de CS). Remove a duplicação — melhor do que gerar o `.asm` no build.

### F6 — O bloco parcial no fim de uma captura indefinida

**Por quê.** Numa captura indefinida, o Ctrl+C descarta o bloco que a PRU estava enchendo (até ~3,4 s a 312,5 kS/s).
(O resto do F6 foi feito em 22/10/2026: SIGTERM e SIGHUP terminam como o Ctrl+C, com o cabeçalho final reescrito, e o
`ler_adc` para a PRU no fim.)

**Proposta.** Gravar o bloco parcial pede a posição de escrita da PRU, e publicá-la a cada amostra custa 1 acesso à
memória: cabe na folga aberta pelo F10 e pelo F15 (≥ 29 ciclos), depois de validados.

### F13 — Estabilidade em 1 h no padrão

**Por quê.** O relatório precisa de um número de estabilidade com o firmware atual: a captura mais longa do T7f tem
5 min, e o T7c (10 min) é do firmware antigo.

**Proposta.** 1 h a 312,5 kS/s com o tom de 10 kHz (~2,2 GB; ~1 070 trocas e ~335 rebases): folga e atrasadas do
cabeçalho, jitter e degraus por trecho de 5 min, e a frequência e a amplitude do tom por bloco. A análise precisa do
P1 (por blocos) ou do `medir_captura.py` em trechos (`--inicio` e `--max-amostras`).

### F7 — Conferência rápida do `calibrar_sonda.sh` mais leve

**Por quê.** A cada captura, o script analisa 262.144 amostras em `od | awk`: 0,7 s no PC; numa Cortex-A8 deve
passar de vários segundos por ponto (não medido). É também o que domina o tempo de `tests/test_calibrar_sonda.py`.

**Proposta.** Medir na BeagleBone (`time` numa captura). Se incomodar: analisar 65.536 amostras (sobram > 30 ciclos
do tom mais baixo do plano) ou mover a análise para um pequeno programa em C compilado junto com o `ler_adc`.

### F8 — Conferir a ordem dos canais a cada amostra

**Por quê.** O bug histórico de "canal trocado" passou meses sem ser visto. O ADS8688 pode anexar o endereço do canal
ao dado (registrador 03h, `SDO_FORMAT`): 3 bits a mais por quadro.

**Proposta.** Um modo de diagnóstico (`ler_adc --conferir-canais`) que liga esse formato, lê os 3 bits extras e
conta quadros fora da sequência esperada (um quarto contador de integridade). Custa ~3 clocks por quadro: deixar
desligado por padrão, ou ligar depois de F3.

### F9 — Descartar o transitório depois de trocar a faixa

**Por quê.** Nas capturas de 19/10 (roteiro, T0 e T1), toda vez que a faixa de um canal muda em relação à captura
anterior, as ~6 primeiras amostras desse canal (60 µs a 100 kS/s) decaem de até ~1 V até o valor certo. É o ADC se
acomodando à nova escala, com constante de tempo próxima à do passa-baixa interno. Sem troca de faixa, não há
transitório. Hoje nada é descartado, e o ruído medido sem `--inicio 100` sai 7 a 8 vezes maior.

**Já feito na análise (21/10):** o `medir_captura.py` pula os primeiros 200 µs de cada canal (`--inicio 0` mede
tudo) e ele e o `adc_tool.py` avisam quando o começo de um trecho foge do resto (`detectar_transitorio_inicial`).
O transitório é um tempo (< 1 LSB em ~80 µs com 1 e com 2 canais), não um nº de amostras.

**Proposta, o que falta.** Na PRU: depois de escrever os `RANGE_SELn` e o `AUTO_RST`, fazer ~16 quadros descartados
(≥ 100 µs) antes de zerar o contador de ciclos e começar a gravar, reaproveitando o corpo da transação (a IMEM está
em 68,7 % desde 22/10/2026, quando o AUTO_RST passou a reaproveitar o corpo da configuração; antes, 91,7 %). O campo `primeira_amostra_descartada` do cabeçalho já existe para registrar isso. Ganho: o `.bin` sai
certo desde a 1ª amostra também para quem o lê fora destas ferramentas.

**Como saber que deu certo.** Repetir a sequência de faixas do T0 (20.48 → 10.24 → 5.12) e conferir que as
primeiras amostras de cada captura já estão dentro do ruído (±3 LSB do valor final).

---

## 4. Software Python

### P1 — Análise de capturas longas por blocos

**Por quê.** O gráfico desenha a envoltória mín/máx quando pedido (`--simplificar`: o da captura de 10 min cai de
26 s e 4,3 GB para 6 s e 1,6 GB), mas a análise ainda converte o trecho inteiro para Volts em float64 antes de tudo: 60 milhões de
amostras são ~0,5 GB por cópia, e o filtro e a correção de sonda fazem cópias. Uma captura de 1 h a 100 kS/s não
caberia em 16 GB.

**Proposta.** O Welch, o espectrograma e as bandas IEC já processam por segmentos: levar a conversão a Volts (e o
filtro, com `sosfilt` + estado entre blocos, ou `sosfiltfilt` por blocos sobrepostos) para dentro do laço, lendo do
memmap. A FFT única da `--fft` continua precisando do trecho inteiro (limitar a `--fft N` ciclos em capturas longas).

### P8 — Potência, impedância e transferência V/I por frequência

**Por quê.** Com tensão e corrente na mesma captura, a pesquisa de emissão quer a potência por componente, a
impedância vista pela carga e a direção da emissão, por frequência. Hoje a correção de sonda é só de magnitude (S3),
e os canais são amostrados com 1/taxa de diferença.

**Proposta.** Depois do S3 (ganho complexo no perfil): compensar o atraso de multiplexação (fase 2π·f·Δt, Δt
conhecido do cabeçalho) e a fase de cada sonda, e calcular, por harmônico e por banda, P, Q, a impedância V/I e a
coerência entre os canais (que diz se a relação é confiável naquela frequência). Antes disso, qualquer número de
potência acima de poucos harmônicos seria enganoso.

---

## 5. Testes e CI

### T2 — Testes de host do C

**Por quê.** As funções de parsing do `ler_adc.c` (`analisar_lista_canais`, `--faixa-adc`, `--atraso-cs`) são
puras, mas `static` dentro do arquivo.

**Proposta.** Movê-las para `parsing.c/.h` e um executável de teste compilado pela CI (lista vazia, canal repetido,
fora de 0–7, valores-limite).

### T3 — Cobertura onde está baixa

`plotagem.py` (49 %) e `escrita_perfil.py` (65 %) — `pytest --cov=scripts/supraharmonicos`. Ganho baixo: o que
importa (contas) já está coberto; vale cobrir a decimação de P1 quando ela existir.

---

## 6. Repositório, dados e documentação

### R5 — Diagrama ARM ↔ PRU ↔ ADC e lições aprendidas

Um diagrama de sequência (configuração, laço, troca de buffer com os contadores, rebase do contador) em
`software-architecture.md` ou num `docs/firmware.md`, e um recorte por tema (tempo do SPI, integridade de sinal,
formato de arquivo) das lições hoje espalhadas em comentários e em `report-notes.md`. Ganho de portfólio.

---

## 7. Hardware

### H1 — Confirmar o isolador contra o esquemático/BOM

O contexto cita o ADuM3150 (isolador digital, com distorção de largura de pulso especificada) "a confirmar". Fechar
isso e medir SCLK/MOSI/MISO na saída do isolador. Com F2/F3 (SPI mais rápido) a margem de tempo do isolador passa a
importar.

### H2 — Pontos de teste na próxima revisão da PCB

SCLK/CS/MOSI/MISO dos dois lados da barreira de isolamento e um GPIO livre da PRU exposto (marcar a primeira amostra
gravada — útil para medir a fase, S2). Desacoplamento de baixo ESR junto ao ADC e trilhas de SPI curtas.

---

## 8. Fluxo de sondas

Propostas da [`probe-profile-audit.md`](probe-profile-audit.md) (seção 4) e do T3. A primeira calibração
real (cadeia de tensão, `scripts/sondas/cadeia_tensao.json`) já foi feita.

| Código | Proposta | Para quê | Esforço | Decisão de projeto? |
|---|---|---|---|---|
| **S1** | Calibrar a sonda de corrente (T10) e validar por frequências retidas (*hold-out*) | Exatidão de um perfil real; detectar ressonância perdida | Médio (bancada) | Não |
| **S2** | Medir a **fase** da cadeia **com uma onda quadrada, sem osciloscópio** (abaixo) | Validar a função de transferência ajustada só pela magnitude; preparar S3 | Médio | Não |
| **S3** | Ganho **complexo** no perfil | Análise V×I, potência, direção de emissão | Médio–Alto | Sim: muda o formato do perfil |
| **S4** | **Subamostragem** para medir \|H\| acima da Nyquist | Estender a curva à banda de supraharmônicos sem subir a taxa; separar f0 de Q (correlação −0,87 hoje) | Médio | Não |
| **S5** | Perfil **absoluto** (V/A) | Eliminar o risco de usar um `--ganho` diferente do da calibração | Médio | Sim: muda o `--ganho` |
| **S6** | Teto de ganho da correção | Não "corrigir" ruído onde a sonda atenua muito (o filtro do ADC já tira 12,5 dB a 45 kHz) | Baixo | Sim: altera o resultado |
| **S7** | Repetições no T3 (`--repeticoes 3`) | Incerteza por ponto; ajuste ponderado e χ² no `gerar_figuras.py` | Baixo (bancada) | Não |

**S2, revisado em 22/10/2026: a fase pela onda quadrada.** Sem o osciloscópio no SPI nem a entrada auxiliar dele,
a referência de tempo tem de vir do próprio sinal. Uma quadrada simétrica tem harmônicos ímpares com fase conhecida
entre si: no centro do pulso, todos são cossenos reais, qualquer que seja o duty. Numa captura, a fase de cada um
menos n vezes a da fundamental, `arg Xₙ − n·arg X₁`, não depende do instante em que a captura começou. Ela vale
`ψ(n·f₁) − n·ψ(f₁)`, a fase da cadeia menos a reta da fase em baixa frequência. Um atraso puro (a conversão, o
instante da amostra) some, e é o que se quer do filtro analógico. A magnitude de cada harmônico, dividida pelo 1/n
teórico, dá a resposta relativa à fundamental, também sem osciloscópio.

Simulado com o 2ª ordem do T3 (f0 = 24,17 kHz, Q = 0,529), com atraso puro de 3 µs, 43 ppm entre os relógios,
aliasing, quantização e o ruído do ADC. Uma quadrada de 1 kHz, 1 s a 312,5 kS/s, dá 70 pontos até 140 kHz:

* a fase com erro de 0,03° rms;
* f0 e Q recuperados só pela fase (24 167 Hz e 0,5288);
* a magnitude a 0,005 dB.

Um erro de duty não muda a fase, mas muda a magnitude dos harmônicos altos (3,8 dB com 0,2 %). Ele é estimado pelo
2º harmônico e corrigido (volta a 0,01 dB). As taxas e f₁ são escolhidas para o aliasing cair fora dos harmônicos
ímpares (taxa/f₁ ímpar ou meio-inteiro: 312,5 kS/s com 1 kHz; a 400 kS/s, f₁ = 997,5 Hz).

A ideia de dois tons somados num canal do gerador é o mesmo princípio, com um harmônico só. Ela pede f₂ múltiplo
inteiro de f₁ e o "alinhar fase" do gerador a cada troca de frequência, porque a fase relativa entre os canais tem de
ser conhecida. A quadrada já traz isso de fábrica, com todos os pontos numa captura só.

**Falta:** a ferramenta de análise (fase, magnitude e duty por harmônico; o ajuste conjunto) e, depois, o S3 (o ganho
complexo no perfil).

### Buffers da DDR (avaliação de 22/10/2026)

Dois buffers de 1.048.576 amostras (2 MB cada), nos 16 MB reservados. A 400 kS/s, cada um enche em 2,6 s.

* **O barramento não depende do tamanho do buffer, só da taxa.** A PRU escreve 2 bytes por amostra (0,8 MB/s a
  400 kS/s): uma fração mínima da DDR. A cópia do ARM (2 MB por bloco) não atrasou nenhum quadro no T7f: a cauda
  do quadro era o dado (F15), e com um `dd` enchendo a DDR a folga mudou 1 ciclo.
* **A margem do ARM** é o tempo de um bloco (2,6 s a 400 kS/s) contra a cópia e o `fwrite` de 2 MB (dezenas de ms,
  para o cache de páginas do Linux). Desde 22/10 o `ler_adc` imprime o pior tempo e a margem (`ARM: ...`). Nenhum
  buffer foi sobrescrito em captura nenhuma, inclusive 5 min a 312,5 kS/s com a DDR ocupada.
* **Mais buffers** (4 de 2 MB, por exemplo) só aumentariam a tolerância a uma parada longa do ARM (de 2,6 para
  7,9 s): mexe na PRU e no `ler_adc`, e só vale se a margem medida for pequena ou se aparecer um sobrescrito.
  **Buffers maiores** pioram as capturas curtas (1 bloco = o mínimo: a calibração de sonda dura um bloco por ponto).
* **O limite real das capturas longas é o disco da placa:** ~1,4 GB livres, 0,8 MB/s a 400 kS/s, ~30 min. 1 h
  (F13) pede outro destino (um pendrive, ou a gravação pela rede).

---

## Regras para quem for implementar

* Mudança no `spi_core.asm` só está pronta depois de montada com `clpru` e validada no hardware; o simulador
  (`tests/test_pru_asm.py`) confere a lógica e a grade de tempo em ciclos, não a latência real.
* O formato das **amostras** do `.bin` não muda (2 bytes por amostra, intercaladas); o cabeçalho pode crescer por
  versão, e o Python continua lendo todas as anteriores.
* Nada que rode por amostra na PRU deve ficar entre a espera e a descida do CS: o que precisa rodar por amostra vai
  na folga **antes** da espera (não muda o instante da amostra); o resto, na troca de buffer.
