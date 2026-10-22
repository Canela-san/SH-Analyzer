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
  autocalibrado: jitter de 8,5 → 0,00 ns). Os números estão em [`bench-results.md`](bench-results.md#t7f-a-grade-de-tempo).

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

**Onde estão os outros limites (fora do firmware):**

1. **A taxa de 312,5 kS/s cobre a banda até ~140 kHz com 1 canal; com 2 canais, até ~70 kHz.** A cadeia de tensão
   atenua ~30 dB em 140 kHz (o filtro de ~15 kHz do ADC): falta o T3 até lá.
2. **Converter uma captura longa para Volts ainda usa o sinal inteiro em float64** (8 bytes por amostra): a análise
   de 10 min a 312,5 kS/s (188 milhões de amostras) pede ~1,5 GB de RAM; 1 h não caberia (P1).

---

## 2. Prioridade

| Código | Item | Ganho | Esforço | PRU? | Depende de |
|---|---|---|---|---|---|
| **F10** | Folga na troca de buffer: espalhar o trabalho da troca pelas amostras seguintes e tirar a espera de CS alto do caminho em dia | Alto: folga de 3 → ~18 ciclos a 312,5 kS/s; teto com período constante ~315 → ~322 kS/s | Baixo | sim | — |
| **F11** | Conferir que a DDR dos buffers está fora do Linux (`/proc/iomem`), no `ler_adc` e no `setup.sh` | Alto: evita corrupção silenciosa numa placa sem `mem=496M` | Baixo | não | — |
| **F12** | Simulador com as latências medidas na placa | Médio: a folga prevista passa a valer | Baixo | não | — |
| **S1** | Calibrar a sonda de corrente (T10) com hold-out | Alto para corrente | Médio (bancada) | não | — |
| **P1** | Análise de capturas longas por blocos (sem o sinal inteiro em float64) | Médio: 10 min = 1,6 GB; 1 h não cabe | Médio | não | — |
| **P8** | Potência, impedância e transferência V/I por frequência | Alto para pesquisa de emissão | Médio | não | S3 |
| **F6** | SIGTERM e queda do ssh como o Ctrl+C; bloco parcial; parar a PRU no fim | Médio | Baixo | sim (publicar a posição) | — |
| **F13** | Estabilidade em 1 h no padrão (grade, folga, frequência, amplitude) | Médio: o número do relatório | Baixo (bancada) | não | F10, P1 |
| **F9** | Descartar o transitório de troca de faixa já na PRU (a análise já descarta) | Baixo: dado certo desde a 1ª amostra | Baixo | sim | — |
| **F3** | SPI mais rápido (SCLK até 17 MHz) | Alto: teto ~315 → ~450 kS/s | Médio | sim | F10 |
| **F4** | `SAMPLES_PER_BUFFER` vindo do ARM, não duplicado no `.asm` | Médio: fim de uma sincronia manual | Baixo | sim | — |
| **F14** | Escrever 2 amostras por acesso à DDR | Incerto: pode encurtar a cauda do quadro comum (611 a 619 ciclos) | Médio | sim | F12 |
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

### F11 — Conferir que a memória dos buffers está fora do Linux

**Por quê.** Os buffers da PRU ficam em `0x9F000000` (os últimos 16 MB dos 512 MB da BeagleBone). O Linux não os usa
só porque a placa do laboratório sobe com `mem=496M` no `/boot/uEnv.txt` (conferido em 22/10 em `/proc/cmdline`). O
comentário "onde o Linux não toca" do `AM335x_PRU.cmd` não reserva nada. Numa placa ou imagem nova sem essa linha, o
Linux daria essas páginas a processos e ao cache de disco: a PRU as sobrescreveria (travamentos ao acaso) e o Linux
sobrescreveria as amostras antes de o `ler_adc` gravá-las (capturas corrompidas, sem aviso).

**Proposta.** O `ler_adc` (que já roda como root) lê `/proc/iomem` antes de configurar a PRU e recusa a captura se
algum trecho `System RAM` cobrir `0x9F000000` a `0x9F3FFFFF`, dizendo o que pôr no `uEnv.txt`. O `setup.sh` confere
o mesmo e avisa. O guia de instalação ganha a linha do `uEnv.txt`.

**Como saber que deu certo.** Na placa atual, nada muda. Num teste com um `/proc/iomem` de mentira que cobre a
região, o `ler_adc` recusa.

### F12 — Simulador com as latências medidas

**Por quê.** Com 1 ciclo por instrução, o simulador dava 25 ciclos de folga a 312,5 kS/s; a placa tem 3 a 5. A PRU
mediu 7 ciclos para um `LBBO` + `SBBO` no bloco de controle (contra 2), e a escrita na DDR varia de ponto a ponto. O
`tests/pru_sim.py` já modela latências (`Latencias`); falta um conjunto calibrado nas medidas do T7f (o quadro comum
de 611 a 619 ciclos e o da troca de ~631 a 638).

**Proposta.** Ajustar `Latencias` (custo de `LBBO`/`SBBO` por destino e uma escrita na DDR com cauda) até o simulador
reproduzir a folga e o teto do T7f, e usá-lo nos testes de folga.

**Como saber que deu certo.** O simulador reproduz o T7f: folga de 3 a 5 ciclos a 640, primeira troca atrasada perto
de 634 e amostras comuns perto de 619.

### F3 — SPI mais rápido

**Por quê.** Os 32 bits de cada quadro levam ~2,9 µs (~20 ciclos por bit de comando, ~16 por bit de dado: SCLK de
~10–12 MHz). O `CMD_BIT` tem NOPs para ficar simétrico ao `DATA_BIT` e um bloco que lê o MISO só para gastar o mesmo
tempo — herança da depuração dos jumpers. O ADS8688 aceita 17 MHz (59 ns por bit), o que daria ~1,9 µs por quadro e
o limite do próprio ADC (500 kS/s, 2 µs de ciclo).

**Proposta.** Depois de F2: reduzir os NOPs medindo, com a mesma bateria de F2, e com o osciloscópio no SCLK/SDO
(tSU_DOCK ≥ 25 ns antes da borda de descida). Cobrir até 150 kHz com 1 canal pede ≥ 300 kS/s.

**Estado em 22/10/2026.** Adiada para depois da grade de tempo (F1, T7f): primeiro o período constante com o SPI
validado (a tag `v0.7` é o backup desse firmware). Estimativa para quando for feita: bits de ~13 ciclos (~15 MHz,
dentro dos 17 MHz do ADS8688 e do ADuM3150) levam o quadro de ~613 a ~440 ciclos, um teto de ~450 kS/s, com 400 kS/s
exatos (500 ticks) com folga. O risco é o caminho de volta do SDO (o isolador duas vezes mais o atraso de saída do
ADC, 50 a 70 ns): a leitura passa para logo depois da borda seguinte, e o ponto dela deve ficar ajustável sem
recompilar, como as esperas do CS. Os 500 kS/s do ADS8688 são somados entre os canais: 150 kHz em 2 canais ao mesmo
tempo pedem outro ADC.

### F4 — `SAMPLES_PER_BUFFER` vindo do ARM

**Por quê.** O tamanho do bloco (1.048.576) está em `memoria_pru.h` e, de novo, num `LDI r21` do `.asm`: mudar um
lado sem o outro desalinha a troca de buffer sem nenhum erro.

**Proposta.** Um campo `amostras_por_buffer` em `shared_control`, escrito pelo `ler_adc` e lido pela PRU uma vez
(como os atrasos de CS). Remove a duplicação — melhor do que gerar o `.asm` no build.

### F6 — Ctrl+C sem perder o bloco em andamento; SIGTERM; parar a PRU no fim

**Por quê.** Numa captura indefinida, o Ctrl+C descarta o bloco que a PRU estava enchendo (até ~3,4 s a 312,5 kS/s).
Só o Ctrl+C (SIGINT) é tratado: um `kill` (SIGTERM) ou a queda do ssh sem o `varrer_taxa.sh` (SIGHUP) terminam o
`ler_adc` sem reescrever o cabeçalho final (blocos gravados, contadores e folga ficam zerados). E a PRU continua
amostrando para a DDR depois que o `ler_adc` sai, até a próxima captura.

**Proposta.** SIGTERM e SIGHUP tratados como o SIGINT (fim limpo, cabeçalho reescrito) e, no fim, `stop` no
remoteproc. Gravar o bloco parcial pede a posição de escrita da PRU, e publicá-la a cada amostra custa 1 acesso à
memória (só depois do F10, que abre a folga); sem ela, o `ler_adc` grava os blocos completos, como hoje.

### F13 — Estabilidade em 1 h no padrão

**Por quê.** O relatório precisa de um número de estabilidade com o firmware atual: a captura mais longa do T7f tem
5 min, e o T7c (10 min) é do firmware antigo.

**Proposta.** 1 h a 312,5 kS/s com o tom de 10 kHz (~2,2 GB; ~1 070 trocas e ~335 rebases): folga e atrasadas do
cabeçalho, jitter e degraus por trecho de 5 min, e a frequência e a amplitude do tom por bloco. A análise precisa do
P1 (por blocos) ou do `medir_captura.py` em trechos (`--inicio` e `--max-amostras`).

### F14 — Escrever 2 amostras por acesso à DDR

**Por quê.** A amostra comum leva de 611 a 619 ciclos, ao acaso (T7f, parte J); a parte variável é, muito
provavelmente, a escrita de 2 bytes na DDR, que passa pelo barramento do ARM.

**Proposta, exploratória.** Guardar a amostra par num registrador e escrever 4 bytes na ímpar: metade dos acessos.
Só vale se o F12 mostrar que a cauda vem dessa escrita, e se encurtar a cauda (a amostra que escreve continua
pagando o acesso).

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
| **S2** | Medir a **fase** da cadeia (osciloscópio na entrada e no CS do ADC) | Validar a função de transferência ajustada só pela magnitude; preparar S3 | Médio | Não |
| **S3** | Ganho **complexo** no perfil | Análise V×I, potência, direção de emissão | Médio–Alto | Sim: muda o formato do perfil |
| **S4** | **Subamostragem** para medir \|H\| acima da Nyquist | Estender a curva à banda de supraharmônicos sem subir a taxa; separar f0 de Q (correlação −0,87 hoje) | Médio | Não |
| **S5** | Perfil **absoluto** (V/A) | Eliminar o risco de usar um `--ganho` diferente do da calibração | Médio | Sim: muda o `--ganho` |
| **S6** | Teto de ganho da correção | Não "corrigir" ruído onde a sonda atenua muito (o filtro do ADC já tira 12,5 dB a 45 kHz) | Baixo | Sim: altera o resultado |
| **S7** | Repetições no T3 (`--repeticoes 3`) | Incerteza por ponto; ajuste ponderado e χ² no `gerar_figuras.py` | Baixo (bancada) | Não |

---

## Regras para quem for implementar

* Mudança no `spi_core.asm` só está pronta depois de montada com `clpru` e validada no hardware; o simulador
  (`tests/test_pru_asm.py`) confere a lógica e a grade de tempo em ciclos, não a latência real.
* O formato das **amostras** do `.bin` não muda (2 bytes por amostra, intercaladas); o cabeçalho pode crescer por
  versão, e o Python continua lendo todas as anteriores.
* Nada que rode por amostra na PRU deve ficar entre a espera e a descida do CS: o que precisa rodar por amostra vai
  na folga **antes** da espera (não muda o instante da amostra); o resto, na troca de buffer.
