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
  quadro que dependia do dado (F15);
* o F15, o F10 e o F3, validados na bancada em 22/10/2026 (T7f, 2ª rodada, e T7g): o quadro fixo (folga de 25
  ciclos a 312,5 kS/s com qualquer sinal; o simulador acertou o quadro comum ao ciclo), a troca espalhada e o SPI
  rápido (~15,4 MHz, 0 divergências de leitura em ~140 milhões de quadros, o mesmo ruído, período constante até
  419,3 kS/s). **400 kS/s com o SPI rápido é o padrão do `ler_adc` desde então** (`--spi lenta` volta ao de antes).

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

### Revisão do firmware (23/10/2026)

**500 kS/s não cabem na arquitetura atual.** A 500 kS/s cada amostra tem 400 ciclos (2 µs, o ciclo mínimo do
próprio ADS8688), e só o CS baixo do quadro rápido leva ~430. Chegar lá pediria bits de 12 ciclos (SCLK de 16,7 MHz,
colado nos ~17 MHz do ADC e do isolador: CS baixo de 392 ciclos e 6 de CS alto, sobrando 2), um laço contado ciclo a
ciclo no lugar da espera de precisão, a escrita na DDR passada à PRU1 (pelo scratchpad) e espaço na IMEM. A leitura do
SDO aguentaria: no T7g o bit volta entre 25 e 60 ns, e a fase B (75 ns) ficaria com ≥ 10 ns de margem. O ganho é
pequeno: Nyquist de 250 kHz com 1 canal e ~6 dB a mais de rejeição de aliasing; com 2 canais, 125 kHz por canal, ainda
sem cobrir 150 kHz. Fica em 400 kS/s.

**O limite da aquisição é o aliasing no topo da banda.** O único anti-aliasing é o passa-baixa interno do ADS8688.
Pelo modelo do T3f, uma imagem chega a 130 kHz só 12,9 dB abaixo de um componente real de mesma amplitude (vinda de
270 kHz a 400 kS/s) e a 150 kHz só 9 dB abaixo (de 250 kHz). Remédios: capturar em duas taxas e comparar (`adc_tool.py
aliasing`, 23/10/2026) e, na próxima placa, um filtro externo (H3).

**Corrigido** (sem mudar o laço principal; protocolo 4, falta a bancada: `make`/`setup.sh` e uma captura):
* o `ler_adc` recusa taxas acima do teto da PRU (477 ticks no SPI rápido, 610 no lento, mais as esperas de CS fora do
  padrão), a não ser com `--forcar-taxa`: pedir 500000 Hz dava ~430 kS/s gravados como 500 kS/s. A frequência é lida
  inteira (o `atoi` lia "400k" como 400 Hz);
* toda saída com erro depois de a PRU ser ligada a para (antes ela ficava amostrando até a próxima captura);
* o início não depende mais de uma espera fixa de 50 ms: o `pru_main.c` avisa que está pronto
  (`versao_protocolo_pru = 0`, depois de zerar `config_ready`) e só então o `ler_adc` configura;
* a configuração escreve 0 nos registradores 02h (canais desligados) e 03h (formato do SDO), que nada reescrevia
  entre capturas. Não é um RST, que voltaria a faixa a ±10,24 V e provocaria o transitório do F9 em toda captura.

**Aberto:** o `ler_adc` sobrescreve um `.bin` existente sem aviso (recusar, com `--sobrescrever` para os scripts, muda
o uso: decisão do usuário). Em captura multicanal, os canais são amostrados 1/fs um depois do outro (2,5 µs a
400 kS/s, 135° em 150 kHz): o P8 (V×I) terá de adiantar cada canal k de k/fs.

---

## 2. Prioridade

| Código | Item | Ganho | Esforço | PRU? | Depende de |
|---|---|---|---|---|---|
| **S1** | Calibrar a sonda de corrente (T10) com hold-out | Alto para corrente | Médio (bancada) | não | — |
| **P1** | Análise de capturas longas por blocos (sem o sinal inteiro em float64) | Médio: 10 min = 1,6 GB; 1 h não cabe | Médio | não | — |
| **P8** | Potência, impedância e transferência V/I por frequência | Alto para pesquisa de emissão | Médio | não | S3 |
| **F6** | Gravar o bloco parcial no fim de uma captura indefinida | Baixo–Médio | Baixo | sim (publicar a posição) | F10 |
| **F13** | Estabilidade em 1 h no padrão (grade, folga, frequência, amplitude) | Médio: o número do relatório | Baixo (bancada) | não | F10, P1 |
| **F9** | Descartar o transitório de troca de faixa já na PRU (a análise já descarta) | Baixo: dado certo desde a 1ª amostra | Baixo | sim | — |
| **F4** | `SAMPLES_PER_BUFFER` vindo do ARM, não duplicado no `.asm` | Médio: fim de uma sincronia manual | Baixo | sim | — |
| **F7** | Conferência rápida do `calibrar_sonda.sh` mais leve na BeagleBone | Médio | Baixo | não | medir na BBB |
| **S2–S7** | Fase, subamostragem, perfil absoluto, teto de ganho, repetições | Alto para V×I | Médio–Alto | não | S1 |
| **F8** | Endereço do canal no SDO (verificar a ordem dos canais a cada amostra) | Baixo–Médio | Médio | sim | F3 |
| **H1–H2** | Isolador contra o BOM, pontos de teste na próxima PCB | Baixo–Médio | Baixo–Médio | não | — |
| **H3** | Filtro anti-aliasing externo (~170–200 kHz) na próxima PCB | Médio: a imagem a 150 kHz está só 9 dB abaixo | Médio | não | — |
| **T2–T3** | Testes de host do C; cobertura da plotagem | Baixo | Baixo | não | — |

---

## 3. Firmware e aquisição

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
em 89,1 % desde 23/10/2026, com o quadro do SPI rápido; o teste limita o `.asm` a 1.850 das 2.048 instruções, e
sobram 25: para abrir espaço, a instrução `LOOP` da PRU no quadro da configuração liberaria ~500). O campo `primeira_amostra_descartada` do cabeçalho já existe para registrar isso. Ganho: o `.bin` sai
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

### H3 — Filtro anti-aliasing externo na próxima revisão da PCB

**Por quê.** O único anti-aliasing da cadeia é o passa-baixa interno do ADS8688 (2ª ordem, ~15 kHz). A 400 kS/s, uma
imagem chega a 150 kHz só 9 dB abaixo de um componente real de mesma amplitude, e a 130 kHz, 12,9 dB (revisão de
23/10/2026). Fontes chaveadas emitem acima de 150 kHz.

**Proposta.** Um passa-baixa de ~170 a 200 kHz antes da entrada do ADC, de ordem suficiente para somar 20 a 30 dB em
250 a 400 kHz. A atenuação dele em 150 kHz entra no perfil da cadeia, medido pelo método das quadradas (T3f), como o
resto.

---

## 8. Fluxo de sondas

Propostas da [`probe-profile-audit.md`](probe-profile-audit.md) (seção 4) e do T3. A primeira calibração
real (cadeia de tensão, `scripts/sondas/cadeia_tensao.json`) já foi feita.

| Código | Proposta | Para quê | Esforço | Decisão de projeto? |
|---|---|---|---|---|
| **S1** | Calibrar a sonda de corrente (T10) e validar por frequências retidas (*hold-out*) | Exatidão de um perfil real; detectar ressonância perdida | Médio (bancada) | Não |
| **S2** | Medir a **fase** da cadeia **com uma onda quadrada, sem osciloscópio** (abaixo; ferramenta e coleta prontas, falta a bancada) | Validar a função de transferência ajustada só pela magnitude; preparar S3 | Baixo (bancada) | Não |
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

**Estado (22/10/2026): medido (o [T3f](bench-results.md#t3f-a-fase-da-cadeia-por-ondas-quadradas)).** O
`./varrer_taxa.sh --fase` coletou 7 quadradas (256 a 20736 Hz, múltiplos ímpares de 256 Hz), 30 s cada, a 312,5 e a
400 kS/s, e as variantes de amplitude e offset. O `scripts/medir_fase.py` deu:

* **o modelo:** a cadeia de tensão é um 2ª ordem com f0 = 22,811 kHz e Q = 0,5001, vezes um polo real em 800 kHz;
* **o ajuste:** resíduo de 0,01 dB e 0,14°, e a magnitude e a fase dão o mesmo filtro (fase mínima);
* **a grade:** incerteza de ~0,002 dB e ~0,01°.

O polo a mais entra quando o BIC o pede (`--polo auto`). Duas lições ficaram na ferramenta:

* **O INL aparece na fundamental.** ~1 LSB de erro em arg X₁ entra multiplicado por n (10° no harmônico 580 da
  quadrada de 256 Hz). Ele é tirado por captura no ajuste, na costura (inclusive na captura-base, onde viraria um
  atraso puro) e no piso das variantes, que ele dobrava.
* **A quadrada não usa referência.** Por isso ela mostrou que o T3 por senoides herdou ~1,3 dB da referência do
  osciloscópio em alta frequência.

Depois: o S3 (usar a fase na correção).

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
