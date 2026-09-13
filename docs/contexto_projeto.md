# SH-Analyzer — Contexto do Projeto

> Documento de referência compacto para uso como contexto por assistentes de IA.
> Atualizado em 12/09/2026. **O nome deste arquivo é fixo
> (`docs/contexto_projeto.md`) — não recriar com sufixo de versão.**
>
> Marco desta atualização: refatoração da arquitetura de análise espectral de
> `scripts/adc_tool.py` — separação explícita entre análise ciclo-sincronizada
> (fundamental/harmônicos, técnica já existente) e análise por segmentação e
> média espectral, método de Welch (nova, direcionada a supraharmônicos), com
> normalização configurável (tom/ruído), agrupamento em bandas e extração de
> picos por interpolação parabólica. A refatoração foi implementada e testada
> com sinais sintéticos (fundamental + supraharmônicos injetados + ruído,
> incluindo *dithering* de frequência); a validação em bancada com sinal real
> continua sendo o Passo 2 (seção 7), que agora passa a usar esta ferramenta
> ampliada.

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
gravados em disco e pós-processados (análise espectral, filtragem, conversão
de formato) por um script Python dedicado (seção 5).

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
- `adc_tool.py` não precisou de nenhuma alteração estrutural para funcionar
  com o modo automático — ele já tratava `--canais` como uma lista
  arbitrária fornecida pelo usuário.

**Pendente (validação quantitativa, não mais de funcionamento básico):**
confirmar com um gerador de sinal/ruído em frequência conhecida, injetado
de forma controlada, que a amplitude e a frequência medidas batem com o que
foi injetado — isso ainda não foi feito (ver seção 7, Passo 2).

---

## 5. `scripts/adc_tool.py` — Arquitetura de Análise Espectral

Renomeado do antigo `plot_adc.py` — deixou de fazer só plotagem. Não é
formalmente parte do escopo da IC, mas foi necessário desenvolver para
poder verificar e depurar o hardware/firmware de aquisição — cresceu ao
longo do projeto conforme cada novo problema de hardware/firmware exigiu
uma nova função de diagnóstico. Declara dependências inline (PEP 723:
matplotlib, numpy≥1.20, scipy, PyQt6), roda via `uv run scripts/adc_tool.py
...` sem instalação manual.

### 5.1 Dois modos de operação

- **Conversão** (`-c/--converter` + `-o/--saida`): converte `.bin` ↔ `.csv`,
  detectando direção pelas extensões. Processa em blocos (streaming), tanto
  na leitura do `.bin` (`numpy.memmap`) quanto na escrita/leitura do `.csv`.
- **Plotagem** (padrão): plota a forma de onda no tempo e, opcionalmente, o
  espectro de frequência — agora por **duas estratégias complementares**
  (seção 5.2), não mais uma só.

### 5.2 Duas estratégias de análise espectral — e por quê

A limitação da técnica original de combate a vazamento espectral (*spectral
leakage*, recorte em ciclos inteiros, seção 5.3) é que ela só funciona para
conteúdo cuja fase está travada ao ciclo da rede elétrica — a fundamental e
seus harmônicos verdadeiros. **Supraharmônicos gerados por conversores
eletrônicos de potência não têm relação de fase com o ciclo de 50/60 Hz**:
não existe corte de janela sincronizado ao ciclo que elimine o vazamento
desse conteúdo especificamente, porque o corte ataca a descontinuidade
errada. Por isso `adc_tool.py` passou a oferecer duas estratégias,
selecionáveis por flag e combináveis numa mesma chamada (cada uma plota sua
própria curva, no mesmo eixo de frequência):

| | `--fft` (ciclo-sincronizado) | `--welch` (segmentado, médio) |
|---|---|---|
| Alvo | Fundamental e harmônicos de baixa ordem | Supraharmônicos (ruído de conversores chaveados) |
| Como ataca o vazamento | Corte em ciclos inteiros por cruzamento de zero (fase travada ao ciclo de rede) | Janela espectral + média entre segmentos (independe de fase) |
| Resolução em frequência | Cresce com a duração da captura | Fixa, definida por `--resolucao-welch` (Hz) |
| Robustez a não estacionariedade | Baixa (assume conteúdo estável durante a janela) | Alta — a média entre segmentos suaviza *dithering* de frequência de chaveamento ao longo da captura |
| Função central | `recortar_ciclos_inteiros` + `calcular_espectro` | `calcular_espectro_welch` |

### 5.3 `--fft`: recorte em ciclos inteiros (técnica original, mantida)

Estratégia de 5 passos, inalterada em essência desde a versão anterior:

1. Estimativa grosseira da fundamental por FFT + janela de Hann fixa,
   dentro de `--freq-min`/`--freq-max` (padrão 45–65 Hz).
2. **Novo:** o pico dessa estimativa é refinado por **interpolação
   parabólica em log-magnitude** (`refinar_pico_parabolico`) — reduz o
   erro de quantização do bin (*scalloping loss*) sem precisar de uma FFT
   maior, melhorando a precisão do corte do passa-baixa que segue.
3. Filtro passa-baixa Butterworth (ordem 4) isola a fundamental antes da
   detecção de cruzamento de zero. **Corrigido nesta atualização:** estava
   implementado na forma clássica `(b, a)`, inconsistente com o resto do
   código na mesma razão fs/f0 extrema (dezenas de milhares para 1) em que
   essa forma perde precisão numérica — migrado para SOS (Second-Order
   Sections) + `sosfiltfilt`, a mesma técnica já usada em
   `aplicar_filtro_digital`.
4. Cruzamentos por zero ascendentes, interpolados linearmente entre
   amostras vizinhas.
5. Refinamento do período usando todos os ciclos disponíveis, e corte do
   trecho exatamente nesses ciclos antes da FFT principal.

**Novo (desempenho):** com `--fft N` (análise de distúrbios momentâneos, só
os N primeiros ciclos), o sinal agora é pré-truncado a uma estimativa
generosa de amostras necessárias (`estimar_amostras_para_n_ciclos`, baseada
no pior caso de `--freq-min` + margem de ciclos) ANTES de filtrar/buscar
cruzamentos — evita processar uma captura inteira de minutos só para olhar
os primeiros milissegundos. Em teste local (captura sintética de 1 minuto a
102,4 kHz), `--fft 5` processou só o início da captura, sem alterar o
resultado (f0 detectada idêntica à de `--fft` sem truncamento, dentro do
erro normal de estimativa).

### 5.4 `--welch`: espectro médio por segmentação (novo)

Implementa o método de Welch: o sinal é dividido em segmentos de tamanho
`fs_efetiva / --resolucao-welch` amostras (padrão de resolução: 200 Hz),
com sobreposição configurável (`--sobreposicao-welch`, padrão 50%); cada
segmento é janelado e transformado, e os periodogramas (`|X(f)|²`)
resultantes são **mediados** — não as fases. Isso reduz a variância da
estimativa espectral (proporcionalmente a `1/√(nº de segmentos)`) e suaviza
deriva de frequência de chaveamento (*dithering*) ao longo da captura, ao
custo de uma resolução em frequência fixa (não cresce com o tamanho da
captura, ao contrário de `--fft`).

Implementado com `numpy.lib.stride_tricks.sliding_window_view`, processado
em lotes (`calcular_espectro_welch`) em vez de 1 segmento por vez em laço
Python puro (lento para os milhares de segmentos de uma captura longa) ou
de todos de uma vez (poderia esgotar RAM numa captura de vários minutos com
sobreposição) — equilíbrio deliberado entre desempenho (FFT vetorizada por
lote) e uso de memória.

### 5.5 `--modo-espectro {tom, ruido}`: duas normalizações, um mesmo espectro

Um mesmo espectro de potência bruto pode ser normalizado de duas formas,
conforme o tipo de conteúdo analisado (`_normalizar_espectro`):

- **`tom`** (padrão, comportamento idêntico ao de antes desta atualização):
  amplitude linear corrigida pelo ganho coerente da janela — correta para
  um **tom discreto** (a fundamental, um harmônico), cuja energia cai
  essencialmente num único bin.
- **`ruido`** (novo): densidade espectral de potência (PSD, V²/Hz),
  normalizada pelo ganho incoerente/ENBW (*Equivalent Noise Bandwidth*) da
  janela. Necessário para **conteúdo de banda larga** — sem essa
  normalização, a leitura em modo `tom` do MESMO ruído físico mudaria
  artificialmente conforme o tamanho da FFT/segmento escolhido, invalidando
  qualquer comparação entre capturas com parâmetros diferentes.

Aplica-se igualmente a `--fft` (com 1 único segmento, é um periodograma
simples) e a `--welch` (média de vários periodogramas).

### 5.6 `--agrupar-bandas`: agregação em bandas fixas

Resume o espectro fino em bandas de largura configurável (ex.: 200 Hz —
convenção comum na literatura e em documentos técnicos de caracterização de
supraharmônicos), reportando o nível RMS de tensão de cada banda em vez do
valor bin a bin. Torna o resultado **comparável entre capturas com
resoluções em frequência diferentes**, ao contrário do valor por bin, que
muda de significado só porque o tamanho da FFT/segmento mudou. Funciona
sobre o espectro de `--fft` e/ou `--welch`, em qualquer um dos dois modos
de normalização (`agrupar_em_bandas` reconcilia as duas convenções para o
mesmo nível de banda em dBV).

### 5.7 `--picos`: extração quantitativa de frequência e amplitude

Localiza picos espectrais acima de um limiar configurável dentro de uma
faixa de busca (`--freq-min-picos`/`--freq-max-picos`, padrão a partir de
2000 Hz — início convencional da faixa de supraharmônicos), via
`scipy.signal.find_peaks`, e refina cada um por **interpolação parabólica**
(a mesma técnica da seção 5.3, item 2, aqui aplicada à extração de
componentes individuais). Entrega frequência e amplitude de cada
supraharmônico sem depender de aumentar o tamanho da FFT para "acertar" o
bin exato — a extração quantitativa que faltava para ir além da inspeção
visual do gráfico. Roda sobre o espectro FINO (antes de `--agrupar-bandas`,
que resolveria só em múltiplos de sua largura de banda).

### 5.8 Filtragem digital e um cuidado novo de uso combinado

A filtragem digital opcional (Butterworth SOS + `sosfiltfilt`,
`--filtro-passa-baixa`/`--filtro-passa-alta`, ordem 4–8) já existia e
continua igual: aplicada a cada canal, em Volts, antes de qualquer outra
etapa. O que muda nesta atualização:

- A correção de SOS no filtro interno do recorte em ciclos (seção 5.3).
- **Novo aviso de uso combinado:** `--fft` depende da fundamental estar
  presente na faixa `--freq-min`/`--freq-max` para sincronizar o corte em
  ciclos. Se `--filtro-passa-alta` for igual ou maior que `--freq-min`, a
  fundamental é removida ANTES do corte, e a estimativa de f0/o corte
  resultante ficam inválidos — sintoma observado em teste: f0 estimada
  caindo para poucos Hz em vez de ~60 Hz. `adc_tool.py` agora detecta essa
  combinação e avisa no console, recomendando rodar `--fft` e
  `--welch`/`--picos` (que sim se beneficiam de um passa-alta acima da
  fundamental, para não deixar resíduo mascarar um supraharmônico fraco)
  em **chamadas separadas**.

### 5.9 Recursos herdados (inalterados)

- Multi-canal completo: `--canais`, `--canais-exibir`,
  `--layout-canais {separados, sobrepostos}`; cada canal processado de
  forma independente por `--fft`/`--welch`.
- Calibração `--faixa`/`--ganho`/`--offset` (valor único ou lista por
  canal).
- Conversão `.bin`→`.csv` ganha coluna `canal` quando há mais de 1 canal;
  round-trip sem perdas (só `valor_bruto` é usado na reconstrução).

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

### 6.2 Validado com sinais sintéticos (não hardware)

- **Refatoração da análise espectral de `adc_tool.py`** (seção 5): testada
  com sinais sintéticos gerados em Python (fundamental de 60 Hz +
  supraharmônicos injetados — incluindo um com *dithering* de frequência —
  + ruído gaussiano), cobrindo `--fft`, `--welch`, `--modo-espectro`,
  `--agrupar-bandas`, `--picos`, multi-canal (com *aliasing* proposital
  acima da Nyquist efetiva de um canal) e round-trip `.bin`↔`.csv`. Os
  picos injetados foram recuperados com erro compatível com a resolução
  espectral (exemplo: 15.321,3 Hz injetado → 15.321,37 Hz encontrado por
  `--picos`). **Isto não substitui a validação quantitativa em bancada com
  sinal real (Passo 2, seção 7)** — confirma a correção matemática/
  numérica da implementação, não a fidelidade do hardware de aquisição.

### 6.3 Pendente

- Validação quantitativa em bancada controlada com sinal/ruído de
  frequência conhecida injetado (Passo 2, seção 7) — a validação atual é
  qualitativa em hardware (canal conectado mostra sinal, desconectado
  mostra ruído) e, agora também, numérica sobre sinais sintéticos (seção
  6.2); nenhuma das duas confirma ainda exatidão de amplitude/frequência
  sobre um sinal real passando pela cadeia analógica completa (frontend +
  ADC + PRU).
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
final. **Com a refatoração de `adc_tool.py` (seção 5), este passo passa a
usar `--welch` + `--agrupar-bandas` + `--picos` para o ruído injetado
(supraharmônico, sem relação de fase com a rede) e `--fft` para a
fundamental/harmônicos — a mesma validação em bancada passa a servir
também como a primeira validação em hardware real da nova arquitetura de
análise (até aqui, validada só com sinais sintéticos, seção 6.2).**

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
- **Filtro interno de isolamento da fundamental** (`recortar_ciclos_inteiros`,
  seção 5.3) migrado de `(b, a)` para SOS + `sosfiltfilt` — mesma técnica
  de `aplicar_filtro_digital`, corrigindo uma inconsistência de precisão
  numérica na razão fs/f0 mais extrema do script (dezenas de milhares para
  1).
- `--fft N` (análise de distúrbios momentâneos) agora pré-trunca a captura
  a uma estimativa de amostras necessárias antes de filtrar/buscar
  cruzamentos, em vez de processar o buffer inteiro selecionado por
  `--inicio`/`--fim` — custo passa a escalar com N, não com o tamanho
  total da janela.
- `calcular_espectro_welch` vetorizado em lotes
  (`numpy.lib.stride_tricks.sliding_window_view`) em vez de 1 segmento por
  vez em laço Python — necessário porque uma captura de minutos com 50% de
  sobreposição gera centenas de milhares de segmentos.

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
| `README.md` | Visão geral, arquitetura, status, guia de uso — atualizado junto com esta versão para refletir a nova arquitetura de análise espectral |
| `LICENSE` | MIT |
| `.gitignore` | Artefatos de build, dados coletados, ambiente Python/editor |
| `firmware/setup.sh` | Deploy: config-pin dos 4 pinos + carrega `fw_pru.out` no remoteproc. Inalterado |
| `firmware/Makefile` | `make` → compila ARM (`ler_adc`) e PRU (`fw_pru.out`). Inalterado |
| `firmware/AM335x_PRU.cmd` | Linker script da PRU. Inalterado |
| `firmware/memoria_pru.h` | `shared_control` simplificado (32 bytes), `auto_seq_mask` (seção 3.3) |
| `firmware/pru_main.c` | Clamp defensivo para `auto_seq_mask` |
| `firmware/spi_core.asm` | Modo automático (AUTO_RST), validado em hardware (1 canal e multi-canal) — macros `CMD_BIT`/`DATA_BIT` mantidas idênticas ao validado |
| `firmware/ler_adc.c` | Monta máscara `auto_seq_mask`, ordena canais em ordem crescente, descarte incondicional da 1ª amostra, checa retorno de `fwrite()`, controla duração da captura (`--blocos`/`--duracao`) |
| `firmware/debug_sh_analyzer.sh` | Script de diagnóstico (remoteproc, dmesg, leitura ao vivo de `shared_control` via `/dev/mem`) — útil para depurar travamentos sem osciloscópio |
| `scripts/adc_tool.py` | Conversão `.bin`↔`.csv` + plotagem + **duas estratégias de análise espectral** (`--fft` ciclo-sincronizado, `--welch` segmentado/médio) + normalização tom/ruído + agrupamento em bandas + extração de picos + filtros digitais, multi-canal completo (seção 5) |
| `hardware/DAQ_Module/` | Projeto Altium Designer (esquemático + PCB) do frontend analógico/DAQ |
| `docs/melhorias-propostas.md` | Revisão técnica: taxa de amostragem + reorganização/profissionalização do repo (seção 8) |
| `docs/contexto_projeto.md` | Este documento — nome fixo a partir de agora |
| `docs/notas_apresentacao_relatorio.md` | Roteiro cronológico do que foi feito, para apresentação à equipe e para o relatório final |

---

*Documento gerado para uso como contexto de IA — mantenha-o atualizado
sempre que houver mudanças estruturais relevantes no projeto (novos
componentes, mudanças de protocolo, resultados de laboratório, etc.).*
