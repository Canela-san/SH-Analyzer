# SH-Analyzer — Contexto do Projeto

> Documento de referência compacto para uso como contexto por assistentes de IA.
> Atualizado em 07/09/2026. **A partir desta versão, o nome deste arquivo é
> fixo (`docs/contexto_projeto.md`) — não recriar com sufixo de versão.**
>
> Marco desta atualização: migração do ADS8688 do modo manual para o modo
> automático (AUTO_RST) **validada em hardware**, incluindo captura
> multi-canal. Esta versão do firmware/documentação acompanha um release no
> GitHub (nova versão da placa/firmware).

**Propósito:** os arquivos reais do projeto (firmware em C/Assembly, script de
análise em Python, arquivos de hardware) são grandes demais para enviar de uma
vez a um assistente de IA. Este documento resume arquitetura, estado atual,
decisões técnicas já validadas e próximos passos, num único lugar compacto.

---

## 1. Visão Geral do Projeto

**SH-Analyzer** (Analisador de Supraharmônicos) é um projeto de hardware e
firmware embarcado de alto desempenho para identificar **supraharmônicos**
— perturbações de alta frequência (dezenas de kHz) introduzidas por
conversores eletrônicos de potência em tensão/corrente de redes elétricas —
que normalmente escapam de analisadores de Qualidade de Energia Elétrica
(QEE) convencionais.

O sistema tem duas partes: (a) um **frontend analógico** (PCB própria, com
isolamento galvânico) que condiciona os sinais de tensão/corrente da rede, e
(b) um **BeagleBone** que faz a aquisição de altíssima frequência via
arquitetura híbrida **PRU (tempo real) + ARM (Linux)**. Dados brutos são
gravados em disco e pós-processados (FFT, filtragem, conversão de formato)
por um script Python dedicado (seção 5).

**Contexto acadêmico:** Iniciação Científica (IC) — "Sistema de identificação
da presença de supraharmônicos em redes e cargas elétricas", Engenharia de
Controle e Automação, Unicamp. Orientação: Prof. Dr. José Antenor Pomilio.
Coorientação: Dr. Mateus Pinheiro Dias. Repositório MIT; PCB e firmware por
Gabriel Canela (Canela).

---

## 2. Hardware

### 2.1 Plataforma de aquisição

BeagleBone: **ARM Cortex-A8 (Linux)** + subsistema **PRU-ICSS**. A PRU0 faz
o controle determinístico via bit-banging SPI e grava as amostras direto
numa região reservada da DDR; o ARM só extrai blocos prontos e grava em
disco, sem processamento em tempo real.

### 2.2 Componentes principais

| Componente | Peça | Função | Especificações-chave |
|---|---|---|---|
| ADC | Texas Instruments **ADS8688** (datasheet SBAS582C) | Conversão A/D dos canais de tensão/corrente | 8 canais single-ended (0–7); 16 bits; throughput agregado máx. **500 kSPS** somando todos os canais (com N canais habilitados, cai para 500 kSPS/N); opera em **modo automático (AUTO_RST)** — modo manual foi removido do projeto |
| Isolador SPI | Analog Devices **ADuM3150** (a confirmar contra esquemático/BOM) | Isolamento galvânico entre PRU/lado digital e o frontend conectado à rede | Família SPIsolator (iCoupler, isolamento magnético); 6 canais; isolação 3,75 kV; até 40 MHz (delay-clock) ou 17 MHz (4 fios) |

**✅ Bug de saturação SPI — resolvido.** Versões anteriores deste documento
registravam um bug em aberto (leitura presa em fundo de escala,
independente da tensão real de entrada). Causa raiz: integridade de sinal
nos **jumpers longos** usados para ligar a placa de aquisição ao frontend
analógico. Corrigido eliminando os jumpers e conectando as placas
diretamente. Consistente com o padrão de erro observado na época (captura
do preâmbulo de 16 bits, ver `scripts/analisar_preambulo.py`) e com a
suspeita já registrada de problema de integridade de sinal, não de lógica
de protocolo.

### 2.3 PCB

Projeto "DAQ_Module", **Altium Designer** (`hardware/DAQ_Module/`):
esquemático, layout, 3D, BOM, Gerber. Inclui isolamento galvânico entre PRU
e frontend conectado à rede.

---

## 3. Firmware — Arquitetura Híbrida PRU + ARM

### 3.1 Divisão de responsabilidades

- **PRU0 (`spi_core.asm`, Assembly):** laço crítico de tempo — bit-banging
  SPI com o ADS8688 e gravação direta das amostras num par de buffers
  "ping-pong" na DDR.
- **`pru_main.c`:** inicialização mínima da PRU (resource_table exigida pelo
  remoteproc; clamps de segurança para `sample_period_ticks` e
  `auto_seq_mask`, caso a RAM compartilhada esteja "fria").
- **ARM/Linux (`ler_adc.c`, C):** mapeia controle e buffers via `/dev/mem`,
  configura canais/frequência, despeja blocos prontos em disco (`.bin`).

### 3.2 Protocolo SPI com o ADS8688 — modo automático (AUTO_RST)

**✅ Migrado do modo manual e validado em hardware** (1 canal e multi-canal).
O modo manual (comando de canal reenviado a cada quadro) foi removido do
projeto.

- Frame de **32 ciclos de SCLK por amostra** no laço principal (16 + 16,
  igual sempre foi) — a diferença é que os 16 ciclos que antes escreviam o
  comando de seleção de canal agora escrevem sempre **NO_OP (`0x0000`)**. O
  ADS8688 avança sozinho para o próximo canal habilitado a cada borda de
  descida de CS, sempre em **ordem crescente** entre os canais habilitados.
- **Sequência de configuração (executada 1x, antes do laço principal,
  resultado sempre descartado):**
  1. **Escreve o registrador de programa `AUTO_SEQ_EN`** (endereço `0x01`)
     com a máscara de canais (`ctrl->auto_seq_mask`, bit N = canal N
     habilitado). Comando de 16 bits = `0x0300 | máscara` (bits `[15:9]` =
     endereço, bit `[8]` = R/W=1, bits `[7:0]` = dado).
     **⚠️ Ponto crítico de protocolo, já causou um bug real:** escrita de
     registrador de programa usa **24 ciclos de SCLK no total** (16 do
     comando + **8 ciclos adicionais**), **não 32**. Confirmado contra o
     driver oficial do ADS8688 no kernel Linux
     (`drivers/iio/adc/ti-ads8688.c`, `ADS8688_PROG_DONT_CARE_BITS = 8`) e
     uma resposta de suporte da própria TI no fórum E2E apontando o mesmo
     erro em outro projeto. Usar 32 ciclos aqui (tratando como uma
     transação normal) deixa o MOSI "pendurado" no nível do último bit do
     comando por 8 ciclos a mais do que o ADS8688 espera, com o CS ainda
     baixo — o chip interpreta isso como bits de comando extras,
     corrompendo a máscara de canais. **Esse foi exatamente o bug que
     causou a primeira tentativa de captura multi-canal sair com todos os
     canais idênticos** (ver seção 4).
  2. **Envia o comando `AUTO_RST`** (`0xA000`, registrador de comando,
     transação normal de 32 ciclos) — inicia a varredura a partir do canal
     habilitado de menor número.
  Referência: datasheet SBAS582C, seção 8.4.2.5 ("Auto Channel Enable with
  Reset").
- Pinagem na PRU (inalterada): bit 0 de r30 = SCLK, bit 1 = MOSI/SDI, bit 2
  de r31 = MISO/SDO, bit 3 de r30 = CS.
- MISO amostrado no último instante seguro antes da borda de descida do
  SCLK — herdado do modo manual validado; macros `CMD_BIT`/`DATA_BIT`
  **não foram alteradas** na migração.
- Atrasos de CS mantidos com os valores calibrados empiricamente (não
  revisados nesta migração): setup ≈1 us (200 ciclos), hold ≈0,5 us
  (100 ciclos), CS-alto mínimo ≈0,5 us (100 ciclos).
- **Benefício adicional (ainda não medido/confirmado com osciloscópio):**
  como o laço principal sempre envia `0x0000`, o MOSI fica eletricamente
  parado durante toda a fase de "comando" de cada amostra — ao contrário do
  modo manual, onde o comando de canal fazia o MOSI chavear em padrões
  dependentes do canal. Para um projeto que mede especificamente ruído de
  alta frequência, isso é uma fonte a menos de chaveamento digital
  potencialmente acoplado à cadeia analógica sensível.

### 3.3 Sincronização ARM ↔ PRU — `shared_control` (`memoria_pru.h`)

`shared_control` foi simplificada nesta migração: o antigo par `num_canais`
+ `comandos_canais[8]` (índice round-robin do modo manual multi-canal) foi
substituído por um único campo, `auto_seq_mask`. Struct caiu de 64 para
**32 bytes**.

| Offset | Campo | Escrito por | Descrição |
|---|---|---|---|
| 0 | `sample_period_ticks` | ARM (relido a cada iteração pela PRU) | Período entre amostras em ciclos de PRU (200 MHz) |
| 4 | `active_buffer` | PRU | Qual buffer (0/1) está ativo |
| 8 / 12 | `buffer_0_ready` / `buffer_1_ready` | PRU seta, ARM zera | Sinaliza buffer pronto para leitura |
| 16 / 20 | `buffer_0_addr` / `buffer_1_addr` | ARM | Endereços físicos na DDR reservada |
| 24 | `config_ready` | ARM seta 1; PRU zera após ler | Handshake inicial |
| 28 | `auto_seq_mask` | ARM (lido 1x pela PRU) | Máscara de bits (bit N = canal N habilitado) do registrador `AUTO_SEQ_EN` |

A PRU não precisa mais saber quantos canais estão ativos, só a máscara.

### 3.4 Buffers ping-pong e memória

- 16 MB reservados na DDR (`0x9F000000`), fora do alcance do Linux; hoje só
  **4 MB usados** (2 buffers × 2 MB = 2 × 1.048.576 amostras × 2 bytes).
- `SAMPLES_PER_BUFFER` = **1.048.576** — precisa bater manualmente com o
  `LDI r21` hardcoded em `spi_core.asm`.
- **Risco documentado, ainda não mitigado:** a troca de buffer na PRU não
  checa se o ARM já terminou de processar o buffer anterior (sem
  backpressure) → corrupção silenciosa é possível se o ARM atrasar. Risco
  cresce ao subir a frequência de amostragem (ver seção 7).

### 3.5 Build e deploy

- `firmware/Makefile`: `make` compila ARM (`gcc -O3` → `ler_adc`) e PRU
  (`clpru --silicon_version=3` → `fw_pru.out`). Inalterado.
- `firmware/setup.sh`: configura os 4 pinos via `config-pin` e recarrega
  `fw_pru.out` no remoteproc (stop/start). Inalterado.
- **PRU_IMEM confirmado dentro do orçamento:** compilação real (`.map`)
  mostrou ≈5.480 de 8.192 bytes usados (≈67%), ≈2.712 bytes livres (≈33%)
  — mesmo com a sequência de configuração do modo automático adicionada.
  Esse número foi medido ANTES do ajuste final de 32→24 ciclos na escrita
  de `AUTO_SEQ_EN` (que reduziu 8 instruções `DATA_BIT`, então o uso real
  hoje é ligeiramente menor). Recomenda-se checar o `.map` de novo a cada
  mudança relevante no Assembly.
- **Nota de implementação:** as 2 transações de configuração (escrita de
  `AUTO_SEQ_EN` e `AUTO_RST`) são escritas por extenso (sem laço/loop) no
  Assembly, porque têm durações diferentes (24 vs. 32 ciclos) — uma
  tentativa anterior de compartilhar as duas num único laço de 2 iterações
  esbarrou num limite da PRU: as instruções de branch condicional "rápido"
  (`QBEQ`/`QBNE`/`QBBS`/`QBBC`) só codificam deslocamento relativo de
  **±511 palavras**, insuficiente para pular de volta por cima de uma
  transação SPI inteira (~600+ instruções expandidas). `JMP` incondicional
  não tem esse limite (é o que `laco_principal` usa) — mas como as 2
  transações passaram a ter tamanhos diferentes de qualquer forma, optou-se
  por não usar laço nenhum, priorizando simplicidade sobre economia de
  código.

---

## 4. Captura Multi-Canal — modo automático, VALIDADA EM HARDWARE

**✅ Status: validada.** Teste realizado com `sudo ./ler_adc 102400
0,1,2,3,4` (5 canais, 20,48 kHz efetivos por canal) numa bancada com tensão
de rede real conectada aos canais 1 e 3, e os canais 0, 2 e 4 deixados
desconectados de propósito. Resultado no `adc_tool.py`: canais 1 e 3
mostraram a onda de 60 Hz esperada; canais 0, 2 e 4 mostraram apenas ruído
— exatamente o comportamento esperado de canais desconectados, confirmando
que a varredura automática está de fato alternando entre canais
corretamente.

**Bug encontrado e corrigido durante essa validação** (ver seção 3.2 para o
detalhe técnico): a primeira tentativa saiu com os 5 canais **idênticos**
entre si — sintoma de que o ADS8688 nunca saía do primeiro canal
selecionado (a varredura automática não estava avançando de verdade), causa
raiz identificada como a escrita incorreta (32 em vez de 24 ciclos) do
registrador `AUTO_SEQ_EN`.

- O ADS8688 sempre varre os canais habilitados em **ordem crescente** de
  número — `ler_adc.c` ordena a lista de canais internamente antes de
  montar a máscara e de imprimir no console; a ordem impressa é a que deve
  ser usada em `--canais` no `adc_tool.py`.
- **Descarte da primeira amostra — generalizado.** Sempre descartada (1
  canal ou vários) — o ADS8688 sempre devolve em cada quadro SPI o
  resultado do quadro ANTERIOR, e a primeira transação de configuração
  reflete dado residual de antes da captura. Implementado do lado ARM
  (`ler_adc.c`).
- Uso: `sudo ./ler_adc <freq_hz> [lista_canais]` — lista opcional, ex.
  `0,1,3`; sem ela, captura só o canal 1 (padrão histórico).
- Formato do `.bin`: amostra bruta na posição *i* (já descontada a amostra
  0 descartada) pertence a `canais[i % num_canais]`, com `canais` na ordem
  crescente impressa no console.
- `adc_tool.py` não precisou de nenhuma alteração para funcionar com o modo
  automático — ele já tratava `--canais` como uma lista arbitrária
  fornecida pelo usuário.

**Pendente (validação quantitativa, não mais de funcionamento básico):**
confirmar com um gerador de sinal/ruído em frequência conhecida, injetado
de forma controlada, que a amplitude e a frequência medidas batem com o que
foi injetado — isso ainda não foi feito (ver seção 7, Passo 2).

---

## 5. `scripts/adc_tool.py` — Ferramenta de Análise

Renomeado do antigo `plot_adc.py` — deixou de fazer só plotagem. Não é
formalmente parte do escopo da IC, mas foi necessário desenvolver para
poder verificar e depurar o hardware/firmware de aquisição — cresceu ao
longo do projeto conforme cada novo problema de hardware/firmware exigiu
uma nova função de diagnóstico. Declara dependências inline (PEP 723:
matplotlib, numpy, scipy, PyQt6), roda via `uv run scripts/adc_tool.py ...`
sem instalação manual.

### 5.1 Dois modos

- **Conversão** (`-c/--converter` + `-o/--saida`): converte `.bin` ↔ `.csv`,
  detectando direção pelas extensões. Processa em blocos (streaming).
- **Plotagem** (padrão): plota forma de onda no tempo e, opcionalmente
  (`--fft`), o espectro de frequência. Aceita `.bin` (`numpy.memmap`) ou
  `.csv` (carregado inteiro).

### 5.2 FFT sem vazamento espectral (spectral leakage)

Estratégia de 5 passos: (1) estimativa grosseira da fundamental via
FFT+Hann (`--freq-min`/`--freq-max`, padrão 45–65 Hz); (2) filtro
passa-baixa Butterworth ordem 4 para isolar a fundamental; (3) cruzamentos
por zero ascendentes interpolados linearmente; (4) refinamento do período
usando todos os ciclos disponíveis; (5) corte do trecho em ciclos inteiros
antes da FFT principal.

### 5.3 Recursos principais

- **Janelas espectrais** (`--janela`): retangular/boxcar (padrão), hann,
  blackman-harris, flattop, kaiser (+ `--kaiser-beta`).
- **`--fft N`:** analisa só os primeiros N ciclos completos.
- **Multi-canal completo:** `--canais`, `--canais-exibir`,
  `--layout-canais {separados, sobrepostos}`; FFT independente por canal;
  calibração `--faixa`/`--ganho`/`--offset` (valor único ou lista).
- **Filtragem digital opcional** (Butterworth SOS + `sosfiltfilt`,
  `--ordem-filtro` 4–8), aplicada antes de qualquer outra etapa.
- Conversão `.bin`→`.csv` ganha coluna `canal` quando há mais de 1 canal.

---

## 6. Status Atual

### 6.1 Validado em hardware

- Protocolo de 32 ciclos do ADS8688 (comando/leitura).
- Handshake `config_ready` entre ARM e PRU.
- Ressincronização periódica do registrador CYCLE da PRU.
- Inicialização explícita de CS/SCLK/MOSI em repouso.
- Laços de atraso para controlar velocidade do SPI sem estourar PRU_IMEM.
- Integridade de sinal entre placas (jumpers longos → conexão direta).
- **Modo automático (AUTO_RST), 1 canal.**
- **Modo automático (AUTO_RST), multi-canal (5 canais testados)** —
  incluindo a correção do bug de escrita do registrador `AUTO_SEQ_EN`.
- `PRU_IMEM` dentro do orçamento de 8 KB com folga confortável.

### 6.2 Pendente

- Validação quantitativa em bancada controlada com sinal/ruído de
  frequência conhecida injetado (Passo 2, seção 7) — a validação atual é
  qualitativa (canal conectado mostra sinal, desconectado mostra ruído),
  ainda não confirma exatidão de amplitude/frequência.
- Margens de tempo do CS (200/100/100 ciclos) seguem sem comparação formal
  com o datasheet do ADS8688.
- Risco de corrupção silenciosa no ping-pong sem backpressure (seção 3.4).
- Benefício de ruído do MOSI parado em modo automático (seção 3.2) não
  medido com osciloscópio.

---

## 7. Próximos Passos

**Passo 1 — Modo automático do ADS8688.** ✅ **Concluído e validado em
hardware** (1 canal e multi-canal, ver seções 3 e 4).

**Passo 2 — Validação quantitativa em laboratório controlado (a
102,4 kHz).** Este é o próximo passo real agora. Gerar uma rede elétrica
limpa e controlada, injetar ruído em frequências específicas conhecidas,
medir com o SH-Analyzer. Comparar o espectro medido contra o ruído
efetivamente injetado demonstra que os dados coletados **não estão sendo
corrompidos** e que a amplitude/frequência medidas são exatas — este é o
resultado que dá credibilidade científica às leituras para o relatório
final.

**Passo 3 — Aumento gradual da frequência (se sobrar tempo).** Partindo de
102,4 kHz (validado), subir a frequência aos poucos até os dados começarem
a falhar/corromper, mapeando o teto real do sistema completo. Atenção: risco
de corrupção silenciosa do ping-pong sem backpressure fica mais provável em
frequências mais altas.

**Passo 4 — Diagnóstico de gargalo.** Ao identificar um gargalo/limite,
isolar em qual elo da cadeia ele está: ADS8688 (teto físico de 500 kSPS
agregado), ADuM3150/isolador SPI, PRU (timing do bit-banging, folga de
PRU_IMEM) ou o firmware em si.

**Passo 5 — Relatório final.** Com todos os dados de laboratório
coletados: gerar imagens/gráficos (via `adc_tool.py`) e escrever o
relatório final da IC. Ver `docs/notas_apresentacao_relatorio.md` para um
roteiro cronológico completo do que foi feito, útil tanto para a
apresentação para a equipe quanto para o relatório.

---

## 8. Notas de Desempenho / Otimização

### 8.1 Implementado

- Removido o índice round-robin de canais em software da PRU — em modo
  automático isso é trabalho do próprio ADC. ~3 instruções por amostra
  (`LSL`+`ADD`+`LBBO`, incluindo acesso à RAM compartilhada) viraram 1
  (`LDI r28, 0`).
- MOSI eletricamente parado durante a fase de comando do laço principal
  (potencial redução de ruído de chaveamento — não medido ainda).
- `shared_control` 2x menor (64 → 32 bytes).
- Checagem do retorno de `fwrite()` em `ler_adc.c` — gravação incompleta
  agora interrompe a captura com mensagem clara em vez de gerar `.bin`
  truncado silenciosamente.
- Correção do timing da escrita de `AUTO_SEQ_EN` (24 vs. 32 ciclos) —
  tecnicamente uma correção de correção, mas também uma otimização: 8
  ciclos a menos nessa transação (só acontece 1x por captura, então o
  ganho de desempenho é irrelevante — o que importa aqui é a correção
  funcional).

### 8.2 Identificado, não alterado (requer validação em bancada)

- Margens de tempo do CS (200/100/100 ciclos ≈ 1 us / 0,5 us / 0,5 us):
  calibradas empiricamente, não comparadas ao datasheet. Maior potencial de
  ganho de frequência máxima identificado até agora, mas só deve ser
  ajustado com medição real (osciloscópio), não às cegas.
- Gargalo real ainda não confirmado por instrumentação (pino de PRU
  "sonda", ver `docs/melhorias-propostas.md`).
- Risco de corrupção silenciosa no ping-pong sem backpressure.
- `BLOCOS_PARA_CAPTURAR` fixo em 1; `SCHED_FIFO` + `mlockall()` no ARM;
  revisão do `usleep(2000)` fixo do polling — catalogados, não
  implementados.
- `SAMPLES_PER_BUFFER` sincronizado manualmente entre `memoria_pru.h` e
  `spi_core.asm` — sem checagem automática.
- Ampliação do uso da DDR reservada (hoje só 4 MB dos 16 MB).

---

## 9. Estrutura do Repositório (inventário de arquivos)

| Caminho | Conteúdo / papel |
|---|---|
| `README.md` | Visão geral, arquitetura, status, guia de uso — atualizado junto com esta versão para refletir o modo automático |
| `LICENSE` | MIT |
| `.gitignore` | Artefatos de build, dados coletados, ambiente Python/editor |
| `firmware/setup.sh` | Deploy: config-pin dos 4 pinos + carrega `fw_pru.out` no remoteproc. Inalterado |
| `firmware/Makefile` | `make` → compila ARM (`ler_adc`) e PRU (`fw_pru.out`). Inalterado |
| `firmware/AM335x_PRU.cmd` | Linker script da PRU. Inalterado |
| `firmware/memoria_pru.h` | `shared_control` simplificado (32 bytes), `auto_seq_mask` (seção 3.3) |
| `firmware/pru_main.c` | Clamp defensivo para `auto_seq_mask` |
| `firmware/spi_core.asm` | Modo automático (AUTO_RST), validado em hardware (1 canal e multi-canal) — macros `CMD_BIT`/`DATA_BIT` mantidas idênticas ao validado |
| `firmware/ler_adc.c` | Monta máscara `auto_seq_mask`, ordena canais em ordem crescente, descarte incondicional da 1ª amostra, checa retorno de `fwrite()` |
| `firmware/debug_sh_analyzer.sh` | **Novo.** Script de diagnóstico (remoteproc, dmesg, leitura ao vivo de `shared_control` via `/dev/mem`) — útil para depurar travamentos sem osciloscópio |
| `scripts/adc_tool.py` | Conversão `.bin`↔`.csv` + plotagem + FFT + filtros digitais, multi-canal completo |
| `hardware/DAQ_Module/` | Projeto Altium Designer (esquemático + PCB) do frontend analógico/DAQ |
| `docs/melhorias-propostas.md` | Revisão técnica: taxa de amostragem + reorganização/profissionalização do repo (seção 8) |
| `docs/contexto_projeto.md` | Este documento — nome fixo a partir de agora |
| `docs/notas_apresentacao_relatorio.md` | **Novo.** Roteiro cronológico do que foi feito, para apresentação à equipe e para o relatório final |

---

*Documento gerado para uso como contexto de IA — mantenha-o atualizado
sempre que houver mudanças estruturais relevantes no projeto (novos
componentes, mudanças de protocolo, resultados de laboratório, etc.).*