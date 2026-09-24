# SH-Analyzer — Contexto do Projeto

> Documento de referência compacto para uso como contexto por assistentes de
> IA. **O nome deste arquivo é fixo (`docs/contexto_projeto.md`) — não
> recriar com sufixo de versão.**

**Propósito:** os arquivos reais do projeto (firmware em C/Assembly, script
de análise em Python, arquivos de hardware) são grandes demais para enviar
de uma vez a um assistente de IA. Este documento resume arquitetura, estado
atual e decisões técnicas do sistema, num único lugar compacto.

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
arquitetura híbrida **PRU (tempo real) + ARM (Linux)**. Cada captura é
gravada em disco como um arquivo autodescritivo (cabeçalho de metadados +
amostras brutas, seção 4) e pós-processada — análise espectral, filtragem,
conversão de formato, exportação HDF5 — por um script Python dedicado
(seção 5).

**Contexto acadêmico:** Iniciação Científica (IC) — "Sistema de
identificação da presença de supraharmônicos em redes e cargas elétricas",
Engenharia de Controle e Automação, Unicamp. Orientação: Prof. Dr. José
Antenor Pomilio. Coorientação: Dr. Mateus Pinheiro Dias. Repositório MIT;
PCB e firmware por Gabriel Canela (Canela).

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
| ADC | Texas Instruments **ADS8688** (datasheet SBAS582C) | Conversão A/D dos canais de tensão/corrente | 8 canais single-ended (0–7); 16 bits; throughput agregado máx. **500 kSPS** somando todos os canais (com N canais habilitados, cai para 500 kSPS/N); opera em **modo automático (AUTO_RST)** |
| Isolador SPI | Analog Devices **ADuM3150** (a confirmar contra esquemático/BOM) | Isolamento galvânico entre PRU/lado digital e o frontend conectado à rede | Família SPIsolator (iCoupler, isolamento magnético); 6 canais; isolação 3,75 kV; até 40 MHz (delay-clock) ou 17 MHz (4 fios) |

A integridade do sinal SPI entre a placa de aquisição e o frontend analógico
depende de conexão elétrica direta entre as duas placas: jumpers longos
introduzem reflexo e ruído induzido suficientes para saturar as leituras do
ADC. O padrão de erro correspondente é observável nos 16 bits de preâmbulo
de cada quadro SPI, que devem permanecer sempre zero (`scripts/
analisar_preambulo.py` inspeciona essa condição a partir de uma captura de
diagnóstico dedicada, `firmware/spi_core_diagnostico_preambulo.asm`). Esse
problema já foi diagnosticado e corrigido (jumpers longos → conexão direta
entre as placas — ver seção 6.1 e `docs/notas_relatorio.md`, Marco 4); a
família ADuM3150 listada acima já é um isolador digital dedicado (não um
optoacoplador simples), então a suspeita original de descasamento de
subida/descida num componente inadequado para comunicação digital
provavelmente não se aplica mais — falta apenas confirmar a peça
formalmente contra o esquemático/BOM (ver `docs/melhorias-propostas.md`,
item 1.10).

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
  configura canais e frequência, grava o cabeçalho de metadados de cada
  captura (seção 4.2) e despeja os blocos prontos em disco (`.bin`).

### 3.2 Protocolo SPI com o ADS8688 — modo automático (AUTO_RST)

O ADS8688 opera em **modo automático de varredura (AUTO_RST)**: o host
programa a sequência de canais habilitados uma única vez, e o próprio ADC
avança de canal sozinho a cada quadro SPI, sempre em ordem crescente entre
os canais habilitados — sem reenviar um comando de seleção de canal a cada
amostra. Esta migração (do antigo modo manual, com um comando de canal
reenviado a cada quadro, para o modo automático) já foi implementada e
**validada em hardware**, com 1 canal e com múltiplos canais — ver seção
6.1 e `docs/notas_relatorio.md`, Marco 6, para o histórico completo (inclui
um bug real de protocolo encontrado e corrigido em hardware, não apenas uma
reescrita teórica a partir do datasheet).

- Frame de **32 ciclos de SCLK por amostra** no laço principal (16 de
  comando + 16 de leitura da conversão anterior). Os 16 ciclos de comando
  transportam sempre **NO_OP (`0x0000`)** durante a captura — o ADS8688 já
  sabe, por hardware, qual é o próximo canal da sequência.
- **Sequência de configuração** (executada uma vez, antes do laço
  principal, resultado sempre descartado):
  1. Escreve o registrador de programa `AUTO_SEQ_EN` (endereço `0x01`) com
     a máscara de canais habilitados (`ctrl->auto_seq_mask`, bit N = canal
     N). Comando de 16 bits = `0x0300 | máscara` (bits `[15:9]` =
     endereço, bit `[8]` = R/W=1, bits `[7:0]` = dado). **Esta escrita usa
     24 ciclos de SCLK no total** (16 do comando + 8 ciclos adicionais
     exigidos pelo datasheet para escrita de registrador de programa) —
     diferente da transação normal de 32 ciclos usada pelo registrador de
     comando. Confirmado contra o datasheet SBAS582C e contra o driver
     oficial do ADS8688 no kernel Linux (`drivers/iio/adc/ti-ads8688.c`,
     `ADS8688_PROG_DONT_CARE_BITS = 8`).
  2. Envia o comando `AUTO_RST` (`0xA000`, registrador de comando,
     transação normal de 32 ciclos) — inicia a varredura a partir do canal
     habilitado de menor número.
  Referência: datasheet SBAS582C, seção 8.4.2.5 ("Auto Channel Enable with
  Reset").
- Pinagem na PRU: bit 0 de r30 = SCLK, bit 1 = MOSI/SDI, bit 2 de r31 =
  MISO/SDO, bit 3 de r30 = CS.
- MISO é amostrado no último instante seguro antes da borda de descida do
  SCLK, maximizando o tempo de acomodação do sinal.
- Atrasos de CS calibrados empiricamente: setup ≈1 µs (200 ciclos), hold
  ≈0,5 µs (100 ciclos), CS-alto mínimo ≈0,5 µs (100 ciclos) — sem
  comparação formal com os tempos mínimos do datasheet (oportunidade de
  ajuste, ver seção 8).
- Como o comando enviado em cada amostra do laço principal é sempre
  `0x0000`, o MOSI permanece eletricamente parado durante a fase de
  comando — reduz uma fonte de chaveamento digital potencialmente acoplada
  à cadeia analógica sensível a ruído de alta frequência (benefício ainda
  não quantificado com osciloscópio).

> **Nota de higiene de código:** o cabeçalho de comentários no topo de
> `spi_core.asm` ainda traz um aviso "⚠️ AINDA NÃO VALIDADO EM HARDWARE"
> (e referencia um nome de arquivo antigo, `Contexto do Projeto-3.md`, de
> antes da convenção de nome fixo desta seção 1). Esse aviso está
> desatualizado — o próprio arquivo documenta, mais abaixo, um bug real
> encontrado **em hardware** (a diferença de 24 vs. 32 ciclos na escrita
> de `AUTO_SEQ_EN`) e corrigido, e a validação com 5 canais está registrada
> nesta seção e em `docs/notas_relatorio.md` (Marco 6). Ver
> `docs/melhorias-propostas.md` para a sugestão de correção desse
> comentário (item de baixíssimo esforço, mas relevante para não confundir
> um leitor futuro do código-fonte).

### 3.3 Sincronização ARM ↔ PRU — `shared_control` (`memoria_pru.h`)

A struct `shared_control` (32 bytes), mapeada numa região dedicada da RAM
interna da PRU-ICSS, é o único canal de comunicação entre o ARM e a PRU:

| Offset | Campo | Escrito por | Descrição |
|---|---|---|---|
| 0 | `sample_period_ticks` | ARM (relido a cada iteração pela PRU) | Período entre amostras em ciclos de PRU (200 MHz) |
| 4 | `active_buffer` | PRU | Qual buffer (0/1) está ativo |
| 8 / 12 | `buffer_0_ready` / `buffer_1_ready` | PRU seta, ARM zera | Sinaliza buffer pronto para leitura |
| 16 / 20 | `buffer_0_addr` / `buffer_1_addr` | ARM | Endereços físicos na DDR reservada |
| 24 | `config_ready` | ARM seta 1; PRU zera após ler | Handshake inicial |
| 28 | `auto_seq_mask` | ARM (lido 1x pela PRU) | Máscara de bits (bit N = canal N habilitado) do registrador `AUTO_SEQ_EN` |

A PRU não precisa saber quantos canais estão ativos nem em que ordem — só a
máscara de bits, que o próprio ADS8688 consome ao entrar em modo de
varredura automática; a ordem de varredura (sempre crescente) é decidida
pelo hardware do ADC, não pelo firmware.

### 3.4 Buffers ping-pong e memória

- 16 MB reservados na DDR (`0x9F000000`), fora do alcance do Linux; hoje só
  **4 MB usados** (2 buffers × 2 MB = 2 × 1.048.576 amostras × 2 bytes).
- `SAMPLES_PER_BUFFER` = **1.048.576** — precisa bater manualmente com o
  `LDI r21` hardcoded em `spi_core.asm`; o cabeçalho de cada `.bin` (seção
  4.2, campo `samples_per_buffer`) documenta o valor usado em cada captura.
- **Limitação conhecida:** a troca de buffer na PRU não verifica se o ARM
  já terminou de processar o buffer anterior (sem backpressure) —
  corrupção silenciosa é possível se o ARM atrasar; o risco cresce com o
  aumento da frequência de amostragem (ver seção 7).

### 3.5 Build e deploy

- `firmware/Makefile`: `make` compila ARM (`gcc -O3` → `ler_adc`) e PRU
  (`clpru --silicon_version=3` → `fw_pru.out`).
- `firmware/setup.sh`: configura os 4 pinos via `config-pin` e recarrega
  `fw_pru.out` no remoteproc (stop/start). Hoje não confere se a PRU de
  fato entrou em estado `running` depois do `start` — só um comentário
  sugerindo checar `dmesg` manualmente (ver `docs/melhorias-propostas.md`,
  item 2.6, para a versão defensiva proposta).
- **Orçamento de `PRU_IMEM`:** a compilação atual usa aproximadamente
  **5.480 de 8.192 bytes (~67%)** disponíveis, com folga confortável para
  expansão futura. Recomenda-se checar o `.map` gerado pela compilação após
  qualquer mudança relevante no Assembly.
- **Nota de implementação:** as 2 transações de configuração (escrita de
  `AUTO_SEQ_EN` e comando `AUTO_RST`) são implementadas sem laço, por
  extenso, no Assembly. As instruções de desvio condicional "rápido" da PRU
  (`QBEQ`/`QBNE`/`QBBS`/`QBBC`) codificam deslocamento relativo de no
  máximo **±511 palavras**, insuficiente para uma transação SPI completa
  (~600+ instruções expandidas); como as duas transações também têm
  durações diferentes (24 vs. 32 ciclos), a implementação sem laço favorece
  simplicidade sobre economia de código.

---

## 4. Formato de Dados

### 4.1 Layout do arquivo `.bin`

Cada captura é um único arquivo: um **cabeçalho fixo de 1024 bytes**,
seguido das amostras brutas do ADC (`uint16_t`, 2 bytes cada, intercaladas
por canal).

**Intercalação:** com N canais habilitados, a amostra na posição *i* do
array de amostras (pós-cabeçalho) pertence a `lista_canais[i % N]`, onde
`lista_canais` é a lista de canais habilitados em ordem crescente — a mesma
ordem que o ADS8688 usa fisicamente para varrer os canais (seção 3.2).

**Descarte da primeira amostra:** o ADS8688 sempre devolve, em cada quadro
SPI, o resultado do quadro ANTERIOR — a primeiríssima transação após o boot
reflete dado residual de antes do início real da captura. `ler_adc.c`
descarta incondicionalmente essa primeira amostra bruta (1 amostra a menos
em mais de 1 milhão por buffer, estatisticamente irrelevante), preservando
o alinhamento amostra-retida-0 ↔ `lista_canais[0]`.

### 4.2 Cabeçalho

Struct empacotada (`__attribute__((packed))`, sem padding de alinhamento),
byte order little-endian (nativo do Cortex-A8), identificada pelo magic
number `"SHAN"`:

| Offset | Campo | Tipo | Descrição |
|---|---|---|---|
| 0 | `magic` | `char[4]` | `"SHAN"` — assinatura do formato |
| 4 | `versao_cabecalho` | `uint32_t` | Versão do formato do cabeçalho (atual: 1) |
| 8 | `tamanho_cabecalho` | `uint32_t` | Bytes totais do cabeçalho (1024) |
| 12 | `timestamp_unix` | `uint64_t` | Epoch Unix (UTC) do início da captura |
| 20 | `frequencia_hz` | `uint32_t` | Frequência total de transação SPI |
| 24 | `auto_seq_mask` | `uint32_t` | Máscara de canais habilitados (bit N = canal N) |
| 28 | `num_canais` | `uint32_t` | Quantidade de canais habilitados |
| 32 | `lista_canais` | `uint8_t[8]` | Canais habilitados, ordem crescente; slots não usados = `0xFF` |
| 40 | `samples_per_buffer` | `uint32_t` | Tamanho de 1 bloco de captura, em amostras brutas |
| 44 | `bytes_por_amostra` | `uint32_t` | Largura de cada amostra bruta (hoje sempre 2) |
| 48 | `pru_clock_hz` | `uint32_t` | Clock da PRU usado para calcular `sample_period_ticks` |
| 52 | `sample_period_ticks` | `uint32_t` | Ciclos de PRU entre amostras |
| 56 | `primeira_amostra_descartada` | `uint32_t` | Booleano — confirma o descarte descrito em 4.1 |
| 60 | `duracao_pedida_segundos` | `double` | Duração pedida via `--duracao`; `0.0` se não usada |
| 68 | `blocos_gravados` | `uint64_t` | Total de blocos gravados, preenchido ao final da captura |
| 76 | `total_amostras_gravadas` | `uint64_t` | Total de amostras brutas gravadas, pós-descarte |
| 84 | `titulo` | `char[64]` | Texto livre em UTF-8, `-t` na linha de comando |
| 148 | `descricao` | `char[256]` | Texto livre em UTF-8, `-d` na linha de comando |
| 404 | `header_crc32` | `uint32_t` | CRC-32 (ISO-HDLC) dos 1024 bytes, calculado com este campo zerado |
| 408 | — | `uint8_t[616]` | Padding reservado, zerado |

`blocos_gravados` e `total_amostras_gravadas` ficam em 0 na gravação
inicial do cabeçalho (o total real só é conhecido ao final da captura);
`ler_adc.c` reescreve o cabeçalho no offset 0 após o laço principal
terminar, com os valores finais e o CRC recalculado — fora do caminho
crítico de tempo, já que ocorre depois do término da aquisição.

Este cabeçalho embutido também resolve, de forma mais robusta do que
originalmente cogitado, o problema de rastreabilidade de metadados por
captura: uma versão anterior deste documento e de `docs/
melhorias-propostas.md` cogitava um arquivo lateral (*sidecar*) `.json`
separado para essa finalidade; a implementação real optou por embutir os
metadados diretamente no `.bin` (com verificação de integridade via CRC-32,
que um `.json` avulso não teria) — um arquivo, sem risco de o sidecar se
perder ou ficar dessincronizado do `.bin` correspondente. Não há, ainda,
um campo de hash do commit do firmware no cabeçalho (rastreabilidade de
versão do firmware por captura permanece um item em aberto — ver seção 8 e
`docs/melhorias-propostas.md`, item 2.4).

`adc_tool.py` detecta o cabeçalho pelo magic number: quando ausente
(arquivos legados, sem cabeçalho), o script exige `-f/--frequencia` e
`--canais` explícitos; quando presente, usa os campos do cabeçalho como
padrão para esses parâmetros, valida o CRC-32 (avisando, sem bloquear, se
não conferir) e confere consistência entre um `--canais` explícito e a
captura real — contagem diferente da registrada no cabeçalho é erro (a
desintercalação ficaria matematicamente incorreta); mesma contagem com
canais diferentes é aviso (só os rótulos ficam incorretos).

### 4.3 Exportação HDF5

`adc_tool.py --export-hdf5 ARQUIVO.h5` converte uma captura para o formato
HDF5:

- `/amostras`: matriz 2D `(amostras_por_canal, num_canais)`, códigos brutos
  do ADC, mesmo dtype de `--formato`.
- `/tensao_v` (opcional, `--incluir-tensao`): a mesma matriz calibrada em
  Volts, `float32`.
- Atributos na raiz do arquivo: todos os campos do cabeçalho (seção 4.2),
  mais os parâmetros de calibração usados na exportação (faixa/ganho/offset
  por canal).

A escrita percorre o `.bin` mapeado em memória (`numpy.memmap`) em blocos,
nunca materializando a captura inteira na RAM — a exportação permanece
viável independentemente do tamanho do arquivo de origem, dentro do espaço
em disco disponível para o `.h5` de saída. Essa propriedade (uso de memória
Python praticamente constante, independente do tamanho do arquivo de
origem ou do tamanho do bloco de processamento) já foi verificada
empiricamente com `tracemalloc` sobre um arquivo sintético de 130 MB — ver
`docs/notas_relatorio.md`, Marco 8.

---

## 5. `scripts/adc_tool.py` — Pós-processamento e Análise Espectral

### 5.1 Modos de operação

- **Plotagem** (padrão): forma de onda no tempo e, opcionalmente, espectro
  de frequência (seções 5.2–5.7), com suporte completo a captura
  multi-canal.
- **Conversão** (`-c/--converter` + `-o/--saida`): `.bin` ↔ `.csv`,
  processado em blocos (streaming), sem carregar arquivos grandes inteiros
  na memória.
- **Exportação HDF5** (`--export-hdf5`): ver seção 4.3.

Em qualquer modo, quando o `.bin` de entrada tem o cabeçalho de metadados
(seção 4.2), `-f/--frequencia` e `--canais` são preenchidos automaticamente
a partir dele.

Declara dependências inline (PEP 723: matplotlib, numpy, scipy, PyQt6,
h5py); roda via `uv run scripts/adc_tool.py ...` sem instalação manual, se
o [`uv`](https://docs.astral.sh/uv/) estiver disponível.

> **Nota de nomenclatura:** todo o resto deste documento, o README e o
> próprio script (docstring interno, `argparse(prog="adc_tool.py")`) tratam
> o arquivo como `adc_tool.py`, em minúsculas. Ver
> `docs/melhorias-propostas.md` para uma discrepância de nome de arquivo em
> disco encontrada durante esta revisão, que quebra esse comando tal como
> documentado em sistemas de arquivos sensíveis a maiúsculas/minúsculas
> (Linux).

### 5.2 Duas estratégias de análise espectral — e por quê

A FFT assume implicitamente que o trecho analisado se repete infinitamente;
quando isso não é verdade, a descontinuidade na "emenda" vaza energia para
frequências vizinhas (*spectral leakage*). A fundamental/harmônicos e os
supraharmônicos exigem tratamentos diferentes, porque só os primeiros têm
fase travada ao ciclo da rede — `adc_tool.py` oferece duas estratégias
complementares, selecionáveis por flag e combináveis numa mesma chamada:

| | `--fft` (ciclo-sincronizado) | `--welch` (segmentado, médio) |
|---|---|---|
| Alvo | Fundamental e harmônicos de baixa ordem | Supraharmônicos (ruído de conversores chaveados) |
| Como ataca o vazamento | Corte em ciclos inteiros por cruzamento de zero (fase travada ao ciclo de rede) | Janela espectral + média entre segmentos (independe de fase) |
| Resolução em frequência | Cresce com a duração da captura | Fixa, definida por `--resolucao-welch` (Hz) |
| Robustez a não estacionariedade | Baixa (assume conteúdo estável durante a janela) | Alta — a média entre segmentos suaviza *dithering* de frequência de chaveamento |
| Função central | `recortar_ciclos_inteiros` + `calcular_espectro` | `calcular_espectro_welch` |

Este par de estratégias — junto com a normalização tom/ruído (seção 5.5), o
agrupamento em bandas (seção 5.6) e a extração de picos (seção 5.7) — é
resultado de uma refatoração de `adc_tool.py` orientada especificamente a
DSP, feita depois da versão inicial da ferramenta (que cobria só `--fft`,
janelas espectrais e suporte multi-canal — ver `docs/notas_relatorio.md`,
Marco 5) e validada com sinais sintéticos (Marco 7 do mesmo documento). É a
parte da ferramenta mais diretamente ligada ao objetivo científico do
projeto: sem `--welch`/`--agrupar-bandas`/`--picos`, a ferramenta mediria
bem a fundamental e seus harmônicos, mas não teria um caminho matematicamente
apropriado para caracterizar o próprio supraharmônico que o projeto existe
para medir.

### 5.3 `--fft`: recorte em ciclos inteiros

Estratégia de 5 passos:

1. Estimativa grosseira da fundamental por FFT + janela de Hann, dentro de
   `--freq-min`/`--freq-max` (padrão 45–65 Hz).
2. Refinamento do pico por interpolação parabólica em log-magnitude
   (`refinar_pico_parabolico`) — reduz o erro de quantização do bin
   (*scalloping loss*) sem precisar de uma FFT maior.
3. Filtro passa-baixa Butterworth (SOS + `sosfiltfilt`) isola a fundamental
   antes da detecção de cruzamento de zero — a forma SOS é usada em vez da
   clássica `(b, a)` por estabilidade numérica na razão fs/f0 extrema
   típica deste sistema (dezenas de milhares para 1).
4. Cruzamentos por zero ascendentes, interpolados linearmente entre
   amostras vizinhas.
5. Refinamento do período usando todos os ciclos disponíveis, e corte do
   trecho exatamente nesses ciclos antes da FFT principal.

Com `--fft N` (análise de distúrbios momentâneos, só os N primeiros
ciclos), o sinal é pré-truncado a uma estimativa generosa de amostras
necessárias (`estimar_amostras_para_n_ciclos`) antes de filtrar/buscar
cruzamentos, evitando processar uma captura inteira de minutos só para
olhar os primeiros milissegundos.

### 5.4 `--welch`: espectro médio por segmentação

Implementa o método de Welch: o sinal é dividido em segmentos de tamanho
`fs_efetiva / --resolucao-welch` amostras (padrão de resolução: 200 Hz),
com sobreposição configurável (`--sobreposicao-welch`, padrão 50%); cada
segmento é janelado e transformado, e os periodogramas (`|X(f)|²`)
resultantes são **mediados** — não as fases. Reduz a variância da
estimativa espectral (proporcionalmente a `1/√(nº de segmentos)`) e suaviza
deriva de frequência de chaveamento (*dithering*) ao longo da captura, ao
custo de uma resolução em frequência fixa.

Processado em lotes (`numpy.lib.stride_tricks.sliding_window_view`, função
`calcular_espectro_welch`) em vez de 1 segmento por vez em laço Python puro
— equilíbrio entre desempenho (FFT vetorizada por lote) e uso de memória
(uma captura longa com sobreposição pode gerar centenas de milhares de
segmentos).

### 5.5 `--modo-espectro {tom, ruido}`: duas normalizações, um mesmo espectro

- **`tom`** (padrão): amplitude linear corrigida pelo ganho coerente da
  janela — correta para um **tom discreto** (a fundamental, um harmônico),
  cuja energia cai essencialmente num único bin.
- **`ruido`**: densidade espectral de potência (PSD, V²/Hz), normalizada
  pelo ganho incoerente/ENBW (*Equivalent Noise Bandwidth*) da janela —
  necessária para **conteúdo de banda larga**, onde `tom` daria uma leitura
  que muda artificialmente conforme o tamanho da FFT/segmento, para o mesmo
  ruído físico.

Aplica-se igualmente a `--fft` (com 1 único segmento, é um periodograma
simples) e a `--welch` (média de vários periodogramas).

### 5.6 `--agrupar-bandas`: agregação em bandas fixas

Resume o espectro fino em bandas de largura configurável (ex.: 200 Hz —
convenção comum na literatura de caracterização de supraharmônicos),
reportando o nível RMS de tensão de cada banda em vez do valor bin a bin.
Torna o resultado comparável entre capturas com resoluções em frequência
diferentes. Funciona sobre o espectro de `--fft` e/ou `--welch`, em
qualquer um dos dois modos de normalização (`agrupar_em_bandas` reconcilia
as duas convenções para o mesmo nível de banda em dBV).

### 5.7 `--picos`: extração quantitativa de frequência e amplitude

Localiza picos espectrais acima de um limiar configurável dentro de uma
faixa de busca (`--freq-min-picos`/`--freq-max-picos`, padrão a partir de
2000 Hz — início convencional da faixa de supraharmônicos, IEC 61000-4-7),
via `scipy.signal.find_peaks`, e refina cada um por interpolação
parabólica. Entrega frequência e amplitude de cada supraharmônico sem
depender de aumentar o tamanho da FFT para "acertar" o bin exato. Roda
sobre o espectro FINO (antes de `--agrupar-bandas`).

### 5.8 Filtragem digital e uso combinado com `--fft`

Filtragem opcional (Butterworth SOS + `sosfiltfilt`,
`--filtro-passa-baixa`/`--filtro-passa-alta`, ordem 4–8) é aplicada a cada
canal, em Volts, antes de qualquer outra etapa (recorte em ciclos,
`--fft`/`--welch`, plotagem).

**Uso combinado com `--fft`:** `--fft` depende da fundamental estar
presente na faixa `--freq-min`/`--freq-max` para sincronizar o corte em
ciclos. Um `--filtro-passa-alta` igual ou maior que `--freq-min` remove
essa banda antes do corte, invalidando a estimativa de f0. `adc_tool.py`
detecta essa combinação e avisa no console; a alternativa é rodar `--fft` e
`--welch`/`--picos` (que se beneficiam de um passa-alta acima da
fundamental) em **comandos separados**.

### 5.9 Suporte multi-canal e calibração

- `--canais`, `--canais-exibir`, `--layout-canais {separados, sobrepostos}`
  — cada canal processado de forma independente por `--fft`/`--welch`. Sem
  `--canais` explícito, a lista vem do cabeçalho da captura quando
  disponível (seção 4.2).
- Calibração `--faixa`/`--ganho`/`--offset` (valor único ou lista por
  canal).
- Conversão `.bin`→`.csv` ganha coluna `canal` quando há mais de 1 canal;
  round-trip sem perdas (só `valor_bruto` é usado na reconstrução) — a ida
  por `.csv` não preserva o cabeçalho de metadados, já que o CSV não tem
  onde armazená-lo.
- A validação de `--canais` (0–7, sem repetição, no máximo
  `ADS8688_MAX_CANAIS`) duplica manualmente, em Python, a mesma regra já
  aplicada em `ler_adc.c` — não há um arquivo de constantes compartilhado
  entre o firmware em C/Assembly e este script (ver seção 8).

---

## 6. Status de Validação

### 6.1 Validado em hardware

- Protocolo de 32 ciclos do ADS8688 (comando/leitura) e a sequência de
  configuração do modo automático (seção 3.2).
- Handshake `config_ready` entre ARM e PRU, com ressincronização periódica
  do registrador CYCLE da PRU (permite capturas de duração arbitrária sem
  travar).
- Inicialização explícita de CS/SCLK/MOSI em repouso; laços de atraso para
  controlar velocidade do SPI sem estourar `PRU_IMEM`.
- Integridade de sinal entre placa de aquisição e frontend (seção 2.2) —
  jumpers longos identificados como causa raiz da saturação e substituídos
  por conexão direta entre as placas.
- Captura em modo automático (AUTO_RST), com 1 canal e com múltiplos
  canais — testado com 5 canais simultâneos (0–4) a 102,4 kHz (≈20,48 kHz
  efetivos por canal): os canais fisicamente conectados à rede mostram a
  onda de 60 Hz esperada; os canais deixados desconectados mostram apenas
  ruído, confirmando a alternância correta entre canais habilitados.
- Cabeçalho de metadados do `.bin` (seção 4.2), incluindo verificação de
  integridade por CRC-32 — a implementação em si já foi hardware-exercitada
  na captura acima; a validação end-to-end específica do cabeçalho (campo a
  campo, contra uma captura real) segue como item de trabalho pendente (ver
  seção 6.3 e `docs/notas_relatorio.md`, Marco 9).
- `PRU_IMEM` dentro do orçamento de 8 KB, com folga confortável.

### 6.2 Validado com sinais sintéticos

A arquitetura de análise espectral de `adc_tool.py` (seção 5) é validada
com sinais sintéticos gerados em Python (fundamental de 60 Hz +
supraharmônicos injetados, incluindo um com *dithering* de frequência, +
ruído gaussiano), cobrindo `--fft`, `--welch`, `--modo-espectro`,
`--agrupar-bandas`, `--picos`, multi-canal (com *aliasing* proposital acima
da Nyquist efetiva de um canal) e round-trip `.bin`↔`.csv`. Os picos
injetados são recuperados com erro compatível com a resolução espectral
(exemplo: 15.321,3 Hz injetado → 15.321,37 Hz encontrado por `--picos`).
Isto confirma a correção matemática/numérica da implementação, não a
fidelidade do hardware de aquisição — ver seção 6.3.

### 6.3 Escopo pendente

- **Validação quantitativa em bancada controlada**, com sinal/ruído de
  frequência e amplitude conhecidas injetado deliberadamente: nem a
  validação em hardware (seção 6.1, qualitativa — canal conectado mostra
  sinal, desconectado mostra ruído) nem a validação sintética (seção 6.2,
  numérica sobre sinais gerados em software) confirmam ainda exatidão de
  amplitude/frequência sobre um sinal real passando pela cadeia analógica
  completa (frontend + ADC + PRU).
- Risco de corrupção silenciosa no ping-pong sem backpressure (seção 3.4).
- Benefício de ruído do MOSI parado em modo automático (seção 3.2) não
  medido com osciloscópio.
- Cabeçalho de metadados (seção 4.2) ainda não exercitado numa captura real
  na BeagleBone — validado até aqui só por testes automatizados com
  arquivos sintéticos (offsets de campo, round-trip de CRC).

---

## 7. Trabalhos Futuros

**Validação quantitativa em bancada controlada (a 102,4 kHz).** Gerar uma
rede elétrica limpa e controlada, injetar ruído em frequências específicas
conhecidas, medir com o SH-Analyzer, e comparar o espectro medido contra o
ruído efetivamente injetado. Este resultado é o que dá credibilidade
científica às leituras para o relatório final. Usa `--welch` +
`--agrupar-bandas` + `--picos` para o ruído injetado (supraharmônico, sem
relação de fase com a rede) e `--fft` para a fundamental/harmônicos — a
mesma validação em bancada serve também como a primeira validação em
hardware real da análise espectral (até aqui, validada só com sinais
sintéticos, seção 6.2).

**Aumento gradual da frequência de amostragem.** Partindo de 102,4 kHz
(validado), subir a frequência aos poucos até os dados começarem a
falhar/corromper, mapeando o teto real do sistema completo. O risco de
corrupção silenciosa do ping-pong sem backpressure (seção 3.4) fica mais
provável em frequências mais altas. Uma revisão de `docs/
melhorias-propostas.md` feita em paralelo a este documento encontrou
indícios de que uma estimativa antiga do "piso" de velocidade da
implementação de bit-banging (baseada num comentário que não existe mais no
`ler_adc.c` atual) já está desatualizada: o teste de 102,4 kHz acima
**já roda acima** dessa estimativa antiga, sugerindo que a folga real hoje
é maior do que se pensava — reforço a mais para medir o piso real (ver
`docs/melhorias-propostas.md`, itens 1.1–1.3) antes de assumir qualquer
número de cabeça.

**Diagnóstico de gargalo.** Ao identificar um gargalo/limite, isolar em
qual elo da cadeia ele está: ADS8688 (teto físico de 500 kSPS agregado),
ADuM3150/isolador SPI, PRU (timing do bit-banging, folga de `PRU_IMEM`) ou
o firmware em si.

**Relatório final.** Com os dados de laboratório coletados: gerar
imagens/gráficos (via `adc_tool.py`) e escrever o relatório final da IC —
ver `docs/notas_relatorio.md` para o roteiro cronológico do
desenvolvimento, usado como matéria-prima para a apresentação e o
relatório.

---

## 8. Considerações de Desempenho

O laço principal do firmware evita qualquer acesso à RAM compartilhada por
amostra: o modo automático do ADS8688 elimina a necessidade de uma tabela
de comandos por canal, reduzindo o custo por amostra a uma única instrução
(`LDI r28, 0`, o NO_OP enviado em todo quadro). A struct `shared_control` de
32 bytes (seção 3.3) e a checagem de retorno de `fwrite()` em `ler_adc.c`
(interrompe a captura com mensagem clara em caso de gravação incompleta, em
vez de gerar um `.bin` truncado silenciosamente) completam o conjunto de
decisões que priorizam previsibilidade de tempo e integridade de dados
sobre economia marginal de código.

Do lado de `adc_tool.py`: o filtro interno de isolamento da fundamental
(`recortar_ciclos_inteiros`, seção 5.3) usa SOS + `sosfiltfilt` pela mesma
razão de estabilidade numérica de `aplicar_filtro_digital`; `--fft N`
pré-trunca a captura a uma estimativa de amostras necessárias antes de
filtrar/buscar cruzamentos, fazendo o custo escalar com N em vez do tamanho
total da janela; `calcular_espectro_welch` é vetorizado em lotes
(`sliding_window_view`) em vez de 1 segmento por vez, necessário porque uma
captura de minutos com sobreposição gera centenas de milhares de segmentos;
a exportação HDF5 (seção 4.3) segue o mesmo princípio, percorrendo o `.bin`
mapeado em memória em blocos.

**Oportunidades identificadas, ainda não implementadas** (requerem
validação em bancada antes de qualquer ajuste):

- Margens de tempo do CS (200/100/100 ciclos ≈ 1 µs / 0,5 µs / 0,5 µs):
  calibradas empiricamente, não comparadas ao datasheet — maior potencial
  de ganho de frequência máxima identificado até agora, mas só deve ser
  ajustado com medição real (osciloscópio).
- Backpressure no ping-pong (seção 3.4).
- `SCHED_FIFO` + `mlockall()` no lado ARM; revisão do `usleep(2000)` fixo
  do polling (o `BLOCOS_PADRAO`/checagem de `fwrite()` já foram
  endereçados — ver `docs/melhorias-propostas.md`, item 1.8).
- `SAMPLES_PER_BUFFER` sincronizado manualmente entre `memoria_pru.h` e
  `spi_core.asm`, sem checagem automática em tempo de compilação entre os
  dois lados; `ADS8688_MAX_CANAIS` tem o mesmo problema, agora duplicado
  também em `adc_tool.py` (Python), já que não existe um arquivo de
  constantes compartilhado entre C/Assembly e o script de análise (seção
  5.9).
- Ampliação do uso da DDR reservada (hoje 4 MB dos 16 MB disponíveis).

Ver `docs/melhorias-propostas.md` para o detalhamento de impacto/esforço de
cada oportunidade listada acima, incluindo o que já foi resolvido desde a
última revisão daquele documento.

---

## 9. Estrutura do Repositório (inventário de arquivos)

| Caminho | Conteúdo / papel |
|---|---|
| `README.md` | Visão geral, arquitetura, formato de dados, status de validação, guia de uso |
| `LICENSE` | MIT |
| `.gitignore` | Artefatos de build, dados coletados, ambiente Python/editor, temporários do Altium Designer |
| `firmware/setup.sh` | Deploy: config-pin dos 4 pinos + carrega `fw_pru.out` no remoteproc |
| `firmware/Makefile` | `make` → compila ARM (`ler_adc`) e PRU (`fw_pru.out`) |
| `firmware/AM335x_PRU.cmd` | Linker script da PRU |
| `firmware/memoria_pru.h` | Struct `shared_control` (32 bytes) e `auto_seq_mask` (seção 3.3) |
| `firmware/pru_main.c` | Clamp defensivo para `auto_seq_mask` |
| `firmware/spi_core.asm` | Modo automático (AUTO_RST), validado em hardware (1 canal e multi-canal) — macros `CMD_BIT`/`DATA_BIT` |
| `firmware/ler_adc.c` | Monta a máscara `auto_seq_mask`, ordena canais em ordem crescente, descarta a primeira amostra, grava e atualiza o cabeçalho de metadados (seção 4.2), controla nome de saída (`-o`), título/descrição (`-t`/`-d`) e duração da captura (`--blocos`/`--duracao`) |
| `firmware/debug_sh_analyzer.sh` | Script de diagnóstico (remoteproc, dmesg, leitura ao vivo de `shared_control` via `/dev/mem`) — útil para depurar travamentos sem osciloscópio |
| `scripts/adc_tool.py` | Leitura do cabeçalho de metadados, conversão `.bin`↔`.csv`, exportação HDF5, plotagem e as duas estratégias de análise espectral (seção 5) |
| `scripts/set_date.sh` | Sincroniza a data/hora local (dev machine) para a BeagleBone via SSH — mitiga a ausência de RTC com bateria mencionada em `ler_adc.c`/seção 4.2 (`timestamp_unix`) |
| `scripts/compactar_amostras.sh` | Compacta capturas `.bin`/`.h5`/`.hdf5` num único arquivo, priorizando densidade de compressão (7-Zip/LZMA2 por padrão, `zpaq -m5` opcional) — arquivamento de longo prazo, fora do caminho crítico de captura |
| `hardware/DAQ_Module/` | Projeto Altium Designer (esquemático + PCB) do frontend analógico/DAQ |
| `docs/melhorias-propostas.md` | Revisão técnica: taxa de amostragem + reorganização/profissionalização do repo (seção 8) |
| `docs/contexto_projeto.md` | Este documento |
| `docs/notas_relatorio.md` | Roteiro cronológico do desenvolvimento, para apresentação à equipe e para o relatório final |

---

*Documento gerado para uso como contexto de IA — mantenha-o sincronizado com
o estado real do repositório sempre que houver mudanças estruturais
relevantes no projeto (novos componentes, mudanças de protocolo, resultados
de laboratório, etc.).*
