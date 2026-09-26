# SH-Analyzer: Analisador de Supraharmônicos
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

Um projeto de hardware e software embarcado de alto desempenho para a identificação e análise de supraharmônicos em redes e cargas elétricas, utilizando uma PCB customizada e o microcomputador industrial BeagleBone.

---

## 📝 Sumário

* [Sobre o Projeto](#sobre-o-projeto)
* [Arquitetura e Desempenho](#arquitetura-e-desempenho)
* [Formato de Dados](#formato-de-dados)
* [Validação em Hardware](#validação-em-hardware)
* [Estrutura do Repositório](#estrutura-do-repositório)
* [Hardware](#hardware)
* [Firmware](#firmware)
* [Scripts e Análise](#scripts-e-análise)
* [Análise Espectral e Tratamento de Vazamento](#análise-espectral-e-tratamento-de-vazamento)
* [Começando](#começando)
* [Contexto Acadêmico](#contexto-acadêmico)
* [Licença](#licença)
* [Agradecimentos](#agradecimentos)

## 📖 Sobre o Projeto

A crescente utilização de conversores eletrônicos de potência (CEPs) introduz perturbações de alta frequência em redes elétricas, conhecidas como **supraharmônicos**. Esses componentes, tipicamente na faixa de dezenas de kHz, frequentemente escapam da detecção por analisadores de Qualidade de Energia Elétrica (QEE) convencionais.

O **SH-Analyzer** é um sistema de instrumentação dedicado à identificação precisa dessas componentes supraharmônicas na corrente e na tensão de uma instalação elétrica. O projeto reúne um frontend analógico de condicionamento de sinais (PCB própria) e uma arquitetura de firmware para amostragem de altíssima frequência, com um formato de captura autodescritivo e um pipeline de pós-processamento pronto para interoperar com ferramentas científicas de terceiros via HDF5.

## ⚡ Arquitetura e Desempenho

Para atingir taxas de amostragem na ordem das centenas de kHz (com metas de expansão para a faixa dos MSPS), o projeto adota uma filosofia rigorosa: **a qualidade e a integridade dos dados estão acima de qualquer economia de armazenamento em disco ou velocidade superficial de execução no sistema operacional.**

O sistema utiliza uma arquitetura híbrida no BeagleBone:

* **PRU (Programmable Real-Time Unit):** encarregada do controle determinístico e *bit-banging* via comunicação SPI com o conversor Analógico-Digital ADS8688, e da gravação direta das amostras num par de buffers ("ping-pong") reservados numa região exclusiva da DDR (fora do alcance do gerenciador de memória do Linux). O ADS8688 opera em **modo automático de varredura (AUTO_RST)**: o host programa a sequência de canais uma única vez e o próprio ADC avança de canal sozinho a cada amostra, em ordem crescente, sem reenviar um comando de seleção de canal a cada quadro SPI. Suporta 1 ou vários canais do ADS8688 simultaneamente, intercalados num mesmo par de buffers — ver `firmware/ler_adc.c` e `firmware/spi_core.asm`.
* **Processador Principal (ARM):** focado exclusivamente em extrair os blocos prontos da DDR e gravá-los em disco o mais rápido possível, evitando corrupção ou perdas de amostras por gargalos de software. Também configura quais canais serão lidos em cada captura, por quanto tempo a captura roda (`--blocos`/`--duracao`, ver [Começando](#começando)) e grava o cabeçalho de metadados de cada arquivo (ver [Formato de Dados](#formato-de-dados)).
* **Sincronização ARM ↔ PRU:** feita via uma pequena struct de controle (`shared_control`, em `memoria_pru.h`) mapeada numa região dedicada da RAM interna da PRU-ICSS — inclui um handshake explícito (`config_ready`) que garante que a PRU só comece a configurar o ADC e a gravar depois que o ARM já tiver configurado os endereços físicos dos buffers e a máscara de canais habilitados.

## 💾 Formato de Dados

Cada captura é um único arquivo `.bin`, autodescritivo, composto por um **cabeçalho fixo de 1024 bytes** seguido das amostras brutas.

### Cabeçalho

O cabeçalho é um layout binário compacto (`struct` empacotada, byte order little-endian), identificado pelo magic number `"SHAN"` e protegido por um checksum CRC-32. Entre os campos gravados:

| Campo | Descrição |
|---|---|
| `versao_cabecalho` | Versão do formato do cabeçalho |
| `timestamp_unix` | Instante da captura (epoch Unix, UTC) |
| `frequencia_hz` | Frequência total de amostragem, em Hz |
| `auto_seq_mask` / `lista_canais` | Canais habilitados, em ordem crescente |
| `samples_per_buffer` / `bytes_por_amostra` | Geometria de cada bloco de captura |
| `blocos_gravados` / `total_amostras_gravadas` | Totais reais da captura, preenchidos ao final |
| `titulo` / `descricao` | Texto livre em UTF-8 para identificar a captura |
| `header_crc32` | Checksum do cabeçalho, para detectar corrupção ou truncamento |

`ler_adc` aceita `-t "título"` e `-d "descrição"` na linha de comando para preencher os dois campos de texto, e `-o arquivo.bin` para escolher o nome do arquivo de saída — sem essa flag, um nome é gerado automaticamente a partir do timestamp da captura.

`adc_tool.py` lê esse cabeçalho automaticamente ao abrir um arquivo: quando presente, `-f`/`--frequencia` e `--canais` deixam de ser obrigatórios e um resumo da captura (título, descrição, canais, duração real vs. solicitada, integridade do CRC) é impresso no console antes de qualquer análise. Arquivos sem cabeçalho continuam sendo lidos normalmente, exigindo esses parâmetros na linha de comando.

### Exportação para HDF5

```bash
python3 adc_tool.py captura.bin --export-hdf5 captura.h5 --incluir-tensao
```

`adc_tool.py` converte qualquer captura para o padrão industrial **HDF5**, gerando:

* `/amostras` — matriz 2D (amostras por canal × número de canais) com os códigos brutos do ADC, preservando exatamente o dado original;
* `/tensao_v` (opcional, com `--incluir-tensao`) — a mesma matriz já calibrada em Volts;
* todos os metadados do cabeçalho, mais os parâmetros de calibração usados na exportação (faixa, ganho, offset por canal), gravados como atributos na raiz do arquivo.

A escrita é feita em blocos sobre o arquivo `.bin` mapeado em memória, sem nunca materializar a captura inteira na RAM — viável mesmo para arquivos de dezenas de gigabytes.

## ✅ Validação em Hardware

* Protocolo de aquisição de 32 ciclos de SCLK por amostra (16 de comando + 16 de leitura) com o ADS8688.
* Handshake de sincronização entre ARM e PRU, e ressincronização periódica do contador de ciclos da PRU, permitindo capturas contínuas de duração arbitrária.
* Modo automático de varredura (AUTO_RST), com 1 canal e com múltiplos canais — testado com 5 canais simultâneos (0–4) a 102,4 kHz totais (≈20,48 kHz efetivos por canal): os canais fisicamente conectados à rede mostram a forma de onda de 60 Hz esperada, e os canais deixados desconectados mostram apenas ruído, confirmando a alternância correta entre canais.
* Integridade do sinal SPI entre a placa de aquisição e o frontend analógico, com isolamento galvânico.
* Cabeçalho de metadados por captura, com verificação de integridade por CRC-32.
* Exportação para HDF5 com metadados completos e uso de memória constante, independente do tamanho da captura.

A ferramenta de análise espectral (`adc_tool.py`) é validada com sinais sintéticos (fundamental, harmônicos e supraharmônicos gerados em software, incluindo *dithering* de frequência), cobrindo as duas estratégias de análise, normalização tom/ruído, agrupamento em bandas, extração de picos e captura multi-canal.

**Escopo atual:** a validação de hardware confirma a correção qualitativa da aquisição (canal conectado mostra sinal, canal desconectado mostra ruído) e a correção numérica da análise espectral sobre sinais sintéticos. A validação quantitativa de exatidão — amplitude e frequência medidas contra um sinal de referência calibrado, injetado em bancada controlada — é a próxima etapa do roteiro experimental (ver `docs/contexto_projeto.md`, seção de trabalhos futuros).

## 📂 Estrutura do Repositório

```text
.
├── /docs/                     # Proposta de Iniciação Científica (IC), datasheets dos componentes, contexto do projeto e relatórios
├── /firmware/                 # Firmware da PRU (Assembly/C), programa do ARM, memoria_pru.h e scripts de deploy/depuração
├── /hardware/                 # Arquivos de design da PCB, esquemático elétrico e modelo 3D (Altium Designer)
└── /scripts/                  # Scripts Python para conversão, exportação, pós-processamento e visualização dos dados

```

## 🔩 Hardware

O hardware atua como um frontend analógico de precisão.

* **Função:** Condicionar e adaptar os níveis de tensão e corrente vindos dos sensores para a faixa de operação ótima do ADC de alta velocidade, incluindo isolamento galvânico entre a PRU e o frontend conectado à rede elétrica.
* **Ferramenta:** O projeto da placa foi integralmente desenvolvido no **Altium Designer**.
* **Conteúdo:** A pasta `/hardware` contém os esquemáticos, o layout da PCB, visualizações 3D em alta resolução, lista de materiais (BOM) e os arquivos Gerber para fabricação.

## 💻 Firmware

O firmware gerencia todo o ecossistema de aquisição em tempo real na BeagleBone.

* **Linguagens:** C (ARM) e Assembly (PRU).
* **PRU:** o laço de controle crítico de tempo (`spi_core.asm`) é executado inteiramente em Assembly para garantir timing determinístico na varredura do ADC — inclui a sequência de configuração do modo automático (escrita do registrador `AUTO_SEQ_EN` + comando `AUTO_RST`) e o laço principal de aquisição; `pru_main.c` faz a inicialização mínima (contador de ciclos, handshake, clamps de segurança) antes de chamar a rotina em Assembly.
* **ARM (Linux):** `ler_adc.c` mapeia a região de controle e os buffers de dados via `/dev/mem`, monta a máscara de canais habilitados para o modo automático (um canal só, por padrão, ou uma lista) e controla por quanto tempo a captura roda (`--blocos`/`--duracao`, ou 1 bloco por padrão). Cada captura é gravada como um `.bin` com o cabeçalho de metadados descrito em [Formato de Dados](#formato-de-dados), seguido das amostras brutas, sem processamento em tempo real. O nome do arquivo de saída é configurável (`-o`) ou gerado automaticamente a partir do timestamp da captura.
* **`memoria_pru.h`:** define o layout da struct de controle compartilhada e as constantes de endereço físico/tamanho de buffer, usadas tanto pelo código C do ARM quanto (por valor) pelo Assembly da PRU.
* **Setup:** `setup.sh` automatiza a configuração da pinagem (via `config-pin`) e carrega o firmware compilado (`fw_pru.out`) no `remoteproc`.
* **Depuração:** `debug_sh_analyzer.sh` inspeciona, sem interromper a captura, o estado do `remoteproc`, o `dmesg` e o conteúdo ao vivo da struct de controle compartilhada via `/dev/mem` — útil para diagnosticar travamentos ou comportamento inesperado da PRU.

### Canais e ordem de amostragem

Em modo automático, o ADS8688 varre os canais habilitados sempre em **ordem crescente** de número de canal — não na ordem em que forem digitados na linha de comando. `ler_adc.c` ordena a lista internamente e imprime a ordem real usada; use exatamente essa ordem ao passar `--canais` para `adc_tool.py` (ou omita a flag: a ordem correta já vem do cabeçalho da captura, ver [Formato de Dados](#formato-de-dados)).

## 📊 Scripts e Análise

Para não sobrecarregar o processador embarcado durante a coleta crítica de dados, o cálculo de grandezas físicas e a análise espectral são desacoplados do firmware e executados em `/scripts`.

`adc_tool.py` é a ferramenta central de pós-processamento. Reconhece automaticamente o cabeçalho de metadados de cada captura (ver [Formato de Dados](#formato-de-dados)) e oferece três modos de operação:

* **Plotagem** (padrão): forma de onda no tempo e, opcionalmente, espectro de frequência, com suporte completo a captura multi-canal (`--canais`/`--canais-exibir`/`--layout-canais`), análise espectral independente por canal, calibração por canal (`--faixa`/`--ganho`/`--offset`) e filtragem digital opcional Butterworth passa-baixa e/ou passa-alta (`--filtro-passa-baixa`/`--filtro-passa-alta`/`--ordem-filtro`, ordem 4 a 8, fase zero), aplicada antes de qualquer análise espectral e da plotagem.
* **Conversão** (`-c`/`--converter` + `-o`/`--saida`): `.bin` ↔ `.csv`, processado em blocos (streaming), sem carregar arquivos grandes inteiros na memória.
* **Exportação HDF5** (`--export-hdf5`): converte a captura para o padrão industrial HDF5, com os metadados do cabeçalho gravados como atributos na raiz — ver [Formato de Dados](#formato-de-dados).

`analisar_preambulo.py` complementa o pacote com uma ferramenta de diagnóstico de integridade de sinal, usada com o firmware de diagnóstico (`firmware/spi_core_diagnostico_preambulo.asm`) para inspecionar os 16 bits de "preâmbulo" de cada quadro SPI (que devem ser sempre zero).

Rode `python3 adc_tool.py --help` para a referência completa de flags.

## 🧮 Análise Espectral e Tratamento de Vazamento

Medir supraharmônicos corretamente depende tanto do hardware de aquisição quanto da matemática usada para transformar as amostras em um espectro de frequência. A FFT assume implicitamente que o trecho analisado se repete infinitamente; quando isso não é verdade, a descontinuidade na "emenda" vaza energia para frequências vizinhas (*spectral leakage*), borrando picos que deveriam ser nítidos — especialmente prejudicial para enxergar um supraharmônico de amplitude baixa perto de uma fundamental de amplitude alta. `adc_tool.py` trata esse problema com **duas estratégias complementares**, porque a fundamental/harmônicos e os supraharmônicos têm características diferentes que exigem tratamentos diferentes.

### `--fft`: corte em ciclos inteiros (fundamental e harmônicos)

A fundamental e seus harmônicos têm fase travada ao ciclo da rede elétrica, o que permite eliminar o vazamento na raiz: o trecho analisado é cortado exatamente num número inteiro de ciclos, localizados por cruzamento de zero interpolado linearmente (não preso à grade de amostragem). O processo:

1. Estimativa grosseira da fundamental por FFT (janela de Hann), refinada por interpolação parabólica em log-magnitude para reduzir o erro de quantização do bin sem precisar de uma FFT maior.
2. Filtro passa-baixa Butterworth (SOS, fase zero) isola a fundamental antes da detecção de cruzamento de zero.
3. Refinamento do período usando todos os ciclos disponíveis (dilui o erro de detecção de um cruzamento individual).
4. Corte do trecho exatamente nesses ciclos, ANTES da FFT principal.

```bash
# FFT ciclo-sincronizada de todos os ciclos completos da janela
python3 adc_tool.py captura.bin --fft

# Só os 10 primeiros ciclos (análise de um distúrbio momentâneo) --
# processa só o início da captura, não o buffer inteiro
python3 adc_tool.py captura.bin --fft 10
```

### `--welch`: espectro médio por segmentação (supraharmônicos)

Supraharmônicos vêm de conversores eletrônicos de potência chaveados e **não têm relação de fase com o ciclo da rede** — não existe corte de ciclo que elimine o vazamento desse conteúdo especificamente, e o próprio chaveamento costuma variar de frequência ao longo do tempo (*dithering*), o que uma única FFT longa borraria. Em vez de sincronismo de ciclo, `--welch` segmenta o sinal (tamanho definido por `--resolucao-welch`, em Hz de resolução), janela e transforma cada segmento, e **média** os periodogramas resultantes — reduz a variância da estimativa e suaviza a deriva de frequência, ao custo de uma resolução em frequência fixa.

```bash
# Espectro médio, resolução de 200 Hz, com passa-alta para remover o
# resíduo da fundamental antes de procurar supraharmônicos
python3 adc_tool.py captura.bin --welch --filtro-passa-alta 2000
```

> ⚠️ `--fft` precisa da fundamental intacta na faixa `--freq-min`/`--freq-max` para sincronizar o corte em ciclos. Um `--filtro-passa-alta` igual ou maior que `--freq-min` remove essa banda e invalida o resultado de `--fft` — nesse caso, rode `--fft` e `--welch`/`--picos` em **comandos separados**. `adc_tool.py` detecta essa combinação e avisa no console.

### Normalização, bandas e picos

* **`--modo-espectro {tom, ruido}`** — `tom` (padrão) mede a amplitude de um tom discreto; `ruido` reporta densidade espectral de potência (PSD, V²/Hz), correta para conteúdo de banda larga, onde `tom` daria uma leitura que muda artificialmente com o tamanho da FFT/segmento para o mesmo ruído físico.
* **`--agrupar-bandas HZ`** — resume o espectro em bandas de largura fixa (ex.: 200 Hz, convenção comum na caracterização de supraharmônicos), tornando o resultado comparável entre capturas com resoluções diferentes.
* **`--picos LIMIAR_DB`** — extrai frequência e amplitude de componentes espectrais individuais acima de um limiar, refinadas por interpolação parabólica — a extração quantitativa que complementa a inspeção visual do gráfico.

```bash
# Espectro médio, agrupado em bandas de 200 Hz, reportando picos acima de -60 dB
python3 adc_tool.py captura.bin --welch --agrupar-bandas 200 --picos -60
```

Rode `python3 adc_tool.py --help` (grupo "Análise espectral avançada") para a referência completa de flags.

## 🚀 Começando

### Pré-requisitos

* **Hardware:** Altium Designer (para edição da placa).
* **Software:** Linux/PopOS ou Windows 10 para desenvolvimento, toolchain C/C++ (GCC) e compilador Texas Instruments (`clpru`) para a BeagleBone. Python 3.10+ (com `numpy`/`pandas`/`matplotlib`/`scipy`/`h5py`) para os scripts. `adc_tool.py` também precisa de `PyQt6` (janela interativa do gráfico — sem ele, ainda funciona com `-o/--saida` para salvar em arquivo); declara suas dependências inline (PEP 723), então também pode ser rodado sem instalação manual via `uv run scripts/adc_tool.py ...`, se você tiver o [`uv`](https://docs.astral.sh/uv/) instalado.

### Instalação e Execução

1. **Fabricação da PCB:** utilize os arquivos Gerber na pasta `/hardware` para produção da placa de circuito impresso.
2. **Preparação da BeagleBone:** envie os arquivos da pasta `/firmware` para o microcomputador. Evite jumpers longos entre a placa de aquisição e o frontend analógico — a proximidade elétrica direta entre as duas placas reduz ruído acoplado no barramento SPI.
3. **Compilação:** rode `make` dentro de `/firmware` para compilar o firmware da PRU (`fw_pru.out`) e o binário do ARM (`ler_adc`).
4. **Deploy:** execute `./setup.sh` para configurar os pinos e carregar o firmware na PRU.
5. **Aquisição:** rode `sudo ./ler_adc <frequência_em_Hz> [lista_de_canais] [--blocos N | --duracao T] [-o arquivo.bin] [-t "título"] [-d "descrição"]` para iniciar a captura.
   * `lista_de_canais` é opcional e separada por vírgulas sem espaços (ex.: `0,1,3`); sem ela, captura só o canal 1 (único canal desta placa com sinal conectado por padrão). Com mais de um canal, a frequência informada é dividida entre eles, sempre em ordem crescente de canal.
   * `--blocos N` / `--duracao T` controlam por quanto tempo a captura roda: `--blocos N` para exatamente N blocos (`N=0` = indefinido, até `Ctrl+C`); `--duracao T` aceita um sufixo `s`/`m`/`h` (ex.: `10m`, `1.5h`) e converte automaticamente para o número de blocos equivalente. São mutuamente exclusivas; sem nenhuma das duas, a captura para sozinha após **1 bloco** (`SAMPLES_PER_BUFFER` = 1.048.576 amostras brutas).
   * `-o arquivo.bin` define o nome do arquivo de saída; sem essa flag, um nome é gerado automaticamente a partir do timestamp da captura.
   * `-t "título"` e `-d "descrição"` gravam texto livre no cabeçalho do arquivo, para identificar a captura mais tarde sem depender só do nome do arquivo.

   ```bash
   sudo ./ler_adc 102400                                  # 1 bloco, canal 1, nome automático
   sudo ./ler_adc 102400 0,1,3 --blocos 5                 # 5 blocos, 3 canais
   sudo ./ler_adc 102400 --blocos 0                       # indefinido, até Ctrl+C
   sudo ./ler_adc 102400 --duracao 10m -o ensaio_bancada.bin \
       -t "Ensaio de bancada" -d "Sinal de 15 kHz injetado no canal 1"
   ```
   Rode `sudo ./ler_adc --help` para a referência completa de flags. Se a captura parecer travada (nenhum "Bloco gravado" aparece), rode `firmware/debug_sh_analyzer.sh` em outro terminal — ele mostra se a PRU está progredindo ou presa, sem precisar de osciloscópio.
6. **Análise:** transfira os arquivos `.bin` para o seu computador principal e utilize as ferramentas da pasta `/scripts`. Quando o arquivo tem o cabeçalho de metadados (ver [Formato de Dados](#formato-de-dados)), `-f`/`--frequencia` e `--canais` são preenchidos automaticamente:
   ```bash
   python3 adc_tool.py captura.bin --fft                                       # visualizar
   python3 adc_tool.py -c captura.bin -o captura.csv                           # converter para .csv
   python3 adc_tool.py captura.bin --export-hdf5 captura.h5 --incluir-tensao   # exportar para HDF5
   ```
   Sem cabeçalho (capturas de arquivos legados), informe manualmente a mesma frequência e lista de canais usadas na captura, na ordem impressa por `ler_adc`:
   ```bash
   # Captura feita com: sudo ./ler_adc 102400 0,1,3
   python3 adc_tool.py captura.bin -f 102400 --canais 0,1,3 --fft

   # Só os canais 0 e 3, sobrepostos no mesmo eixo em vez de subplots separados
   python3 adc_tool.py captura.bin -f 102400 --canais 0,1,3 \
       --canais-exibir 0,3 --layout-canais sobrepostos --fft

   # Canal 0 = tensão (ganho 19.53), canal 1 = corrente (ganho 0.1)
   python3 adc_tool.py captura.bin -f 102400 --canais 0,1 --ganho 19.53,0.1 --fft
   ```

   Para limpar ruído de alta frequência (ex.: aliasing residual perto da Nyquist) ou deriva de DC antes de plotar/calcular a FFT, use o filtro digital Butterworth opcional:
   ```bash
   # Captura a 102.4 kHz (Nyquist = 51.2 kHz): limpa ruído acima de 45 kHz
   python3 adc_tool.py captura.bin --filtro-passa-baixa 45000 --fft

   # Remove deriva de DC/baixa frequência com um filtro de ordem mais alta
   python3 adc_tool.py captura.bin --filtro-passa-alta 20 --ordem-filtro 8 --fft
   ```
   O filtro só se aplica ao modo de plotagem (não afeta a coluna opcional do modo de conversão, que continua refletindo o dado bruto sem filtragem, para preservar o round-trip `.bin`↔`.csv` sem perdas).

   Para caracterizar especificamente **supraharmônicos** (conteúdo sem relação de fase com o ciclo da rede), use `--welch` em vez de, ou junto com, `--fft` — ver [Análise Espectral e Tratamento de Vazamento](#análise-espectral-e-tratamento-de-vazamento) para a explicação completa, o porquê de cada técnica e mais exemplos (`--modo-espectro`, `--agrupar-bandas`, `--picos`).

## 🎓 Contexto Acadêmico

Este projeto é o resultado prático de uma pesquisa de Iniciação Científica (IC) vinculada ao projeto "Sistema de identificação da presença de supraharmônicos em redes e cargas elétricas", desenvolvida no curso de Engenharia de Controle e Automação da Universidade Estadual de Campinas (Unicamp).

* **Orientação:** Prof. Dr. José Antenor Pomilio.
* **Coorientação:** Dr. Mateus Pinheiro Dias.

## 📄 Licença

Este projeto é distribuído sob a Licença MIT. Veja o arquivo `LICENSE` para mais detalhes.

## 🙏 Agradecimentos

Um agradecimento especial ao Prof. Dr. José Antenor Pomilio e ao Dr. Mateus Pinheiro Dias pela orientação contínua, excelência técnica e suporte ao longo de todo o desenvolvimento desta pesquisa.
