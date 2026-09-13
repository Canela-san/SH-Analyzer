# SH-Analyzer: Analisador de Supraharmônicos
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

Um projeto de hardware e software embarcado de alto desempenho para a identificação e análise de supraharmônicos em redes e cargas elétricas, utilizando uma PCB customizada e o microcomputador industrial BeagleBone.

---

## 📝 Sumário

* [Sobre o Projeto](#sobre-o-projeto)
* [Arquitetura e Desempenho](#arquitetura-e-desempenho)
* [Status Atual](#status-atual)
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

A crescente utilização de conversores eletrônicos de potência (CEPs) tem introduzido perturbações de alta frequência em redes elétricas, conhecidas como **supraharmônicos**. Esses componentes, tipicamente na faixa de dezenas de kHz, frequentemente escapam da detecção por analisadores de Qualidade de Energia Elétrica (QEE) convencionais.

O **SH-Analyzer** é um sistema de instrumentação dedicado à identificação precisa dessas componentes supraharmônicas na corrente e na tensão de uma instalação elétrica. O projeto engloba o desenvolvimento de um frontend analógico de condicionamento de sinais (PCB) e uma arquitetura de firmware focada em amostragem de altíssima frequência.

## ⚡ Arquitetura e Desempenho

Para atingir taxas de amostragem na ordem das centenas de kHz (com metas de expansão para a faixa dos MSPS), o projeto adota uma filosofia rigorosa: **a qualidade e a integridade dos dados estão acima de qualquer economia de armazenamento em disco ou velocidade superficial de execução no sistema operacional.**

O sistema utiliza uma arquitetura híbrida no BeagleBone:

* **PRU (Programmable Real-Time Unit):** encarregada do controle determinístico e *bit-banging* via comunicação SPI com o conversor Analógico-Digital ADS8688, e da gravação direta das amostras num par de buffers ("ping-pong") reservados numa região exclusiva da DDR (fora do alcance do gerenciador de memória do Linux). O ADS8688 opera em **modo automático de varredura (AUTO_RST)**: o host programa a sequência de canais uma única vez e o próprio ADC avança de canal sozinho a cada amostra, em ordem crescente — sem reenviar um comando de seleção de canal a cada quadro SPI, como exigiria o modo manual. Suporta capturar 1 ou vários canais do ADS8688 ao mesmo tempo, intercalados num mesmo par de buffers — ver `firmware/ler_adc.c` e `firmware/spi_core.asm`.
* **Processador Principal (ARM):** focado exclusivamente em extrair os blocos prontos da DDR e gravá-los em disco (`.bin`) o mais rápido possível, evitando corrupção ou perdas de amostras causadas por gargalos de software. Também é responsável por configurar quais canais do ADC serão lidos em cada captura, e por quanto tempo a captura roda (`--blocos`/`--duracao`, ver "Começando").
* **Sincronização ARM ↔ PRU:** feita via uma pequena struct de controle (`shared_control`, em `memoria_pru.h`) mapeada numa região dedicada da RAM interna da PRU-ICSS — inclui um handshake explícito (`config_ready`) para garantir que a PRU só comece a configurar o ADC e a gravar depois que o ARM já configurou os endereços físicos dos buffers e a máscara de canais habilitados.

## 🩺 Status Atual

O firmware original, um protótipo em C puro rodando diretamente no ARM sob Linux e limitado a ~102,4 kHz pelo jitter de escalonamento do sistema operacional, foi reescrito para a arquitetura híbrida PRU (Assembly) + ARM descrita acima. Já foram **validados em hardware**:

* Protocolo de **32 ciclos de SCLK por amostra** com o ADS8688 (16 de comando + 16 de leitura da conversão anterior).
* Handshake de sincronização `config_ready` entre ARM e PRU.
* Ressincronização periódica do registrador `CYCLE` da PRU (que **trava** em vez de dar a volta ao estourar 32 bits, ~21,47 s a 200 MHz) — sem isso, capturas longas travavam sozinhas.
* Inicialização explícita de CS/SCLK/MOSI em repouso antes do laço principal.
* Uso de laços de atraso (em vez de `NOP` repetido) para controlar a velocidade do SPI sem estourar os 8 KB de `PRU_IMEM`.
* Integridade do sinal SPI entre a placa de aquisição e o frontend analógico — um bug de saturação (leitura presa em fundo de escala) foi rastreado até os jumpers longos usados na bancada de testes; resolvido conectando as placas diretamente.
* **Captura em modo automático (AUTO_RST), 1 canal.**
* **Captura em modo automático (AUTO_RST), multi-canal** — testado com 5 canais simultâneos (0–4) a 102,4 kHz (≈20,48 kHz efetivos por canal): os canais fisicamente conectados à rede mostraram a forma de onda de 60 Hz esperada, e os canais deixados desconectados de propósito mostraram apenas ruído, confirmando que a varredura automática alterna corretamente entre canais.

A ferramenta de análise (`adc_tool.py`) passou por uma refatoração da sua arquitetura de análise espectral — ver [Análise Espectral e Tratamento de Vazamento](#análise-espectral-e-tratamento-de-vazamento) — **validada até aqui com sinais sintéticos** (fundamental e supraharmônicos gerados em software), não ainda com um sinal real injetado em bancada.

**Pendente:** validação quantitativa em bancada controlada, com um sinal/ruído de frequência e amplitude conhecidas injetado deliberadamente, para confirmar exatidão (não só plausibilidade) das leituras — tanto do hardware de aquisição quanto, agora, da nova arquitetura de análise espectral. Ver `docs/contexto_projeto.md`, seção 7, para o roteiro completo dos próximos passos.

## 📂 Estrutura do Repositório

```text
.
├── /docs/                     # Proposta de Iniciação Científica (IC), datasheets dos componentes, contexto do projeto e relatórios
├── /firmware/                 # Firmware da PRU (Assembly/C), programa do ARM, memoria_pru.h e scripts de deploy/depuração
├── /hardware/                 # Arquivos de design da PCB, esquemático elétrico e modelo 3D (Altium Designer)
└── /scripts/                  # Scripts Python para conversão, pós-processamento, aplicação de filtros e visualização dos dados

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
* **ARM (Linux):** `ler_adc.c` mapeia a região de controle e os buffers de dados via `/dev/mem`, monta a máscara de canais habilitados para o modo automático (um canal só, por padrão, ou uma lista), controla por quanto tempo a captura roda (`--blocos`/`--duracao`, ou 1 bloco por padrão) e despeja os blocos prontos direto em disco como binário bruto (`.bin`), sem processamento em tempo real.
* **`memoria_pru.h`:** define o layout da struct de controle compartilhada e as constantes de endereço físico/tamanho de buffer — compartilhado entre o código C do ARM e (por valor, manualmente sincronizado) as constantes hardcoded no Assembly da PRU.
* **Setup:** `setup.sh` automatiza a configuração da pinagem (via `config-pin`) e carrega o firmware compilado (`fw_pru.out`) no `remoteproc`.
* **Depuração:** `debug_sh_analyzer.sh` inspeciona, sem interromper a captura, o estado do `remoteproc`, o `dmesg` e o conteúdo ao vivo da struct de controle compartilhada via `/dev/mem` — útil para diagnosticar travamentos ou comportamento inesperado da PRU.

### Canais e ordem de amostragem

Em modo automático, o ADS8688 varre os canais habilitados sempre em **ordem crescente** de número de canal — não na ordem em que forem digitados na linha de comando. `ler_adc.c` ordena a lista internamente e imprime a ordem real usada; use exatamente essa ordem (impressa no console) ao passar `--canais` para `adc_tool.py`.

## 📊 Scripts e Análise

Para não sobrecarregar o processador embarcado durante a coleta crítica de dados, o cálculo de grandezas físicas e a análise espectral são desacoplados do firmware.

* **Pós-processamento:** a pasta `/scripts` contém rotinas em Python encarregadas de ler os arquivos binários gerados pela BeagleBone.
* **Funcionalidades:** extração de métricas, análise espectral (FFT ciclo-sincronizada e espectro médio por segmentação/Welch — ver [Análise Espectral e Tratamento de Vazamento](#análise-espectral-e-tratamento-de-vazamento)), filtragem digital, plotagem de gráficos e conversão de formato (`.bin` ↔ `.csv`) para análise dos supraharmônicos (`analise.py`, `adc_tool.py` — renomeado do antigo `plot_adc.py` —, `verificar_dados.py`). `adc_tool.py` lê, plota e converte tanto capturas de 1 canal quanto capturas multi-canal (`--canais`/`--canais-exibir`/`--layout-canais`), com análise espectral independente por canal e calibração (`--faixa`/`--ganho`/`--offset`) configurável por canal, além de filtragem digital opcional Butterworth passa-baixa e/ou passa-alta (`--filtro-passa-baixa`/`--filtro-passa-alta`/`--ordem-filtro`, ordem 4 a 8) aplicada antes de qualquer análise espectral e da plotagem — ver `python3 adc_tool.py --help` ou o docstring do módulo para a referência completa.
* **Diagnóstico:** `analisar_preambulo.py` inspeciona capturas feitas com o firmware de diagnóstico (`firmware/spi_core_diagnostico_preambulo.asm`), separando os 16 bits de "preâmbulo" (que deveriam ser sempre zero) dos 16 bits de dado real — foi essa ferramenta que ajudou a isolar o problema de integridade de sinal dos jumpers longos (ver "Status Atual").

## 🧮 Análise Espectral e Tratamento de Vazamento

Medir supraharmônicos corretamente depende tanto do hardware de aquisição quanto da matemática usada para transformar as amostras em um espectro de frequência. A FFT assume implicitamente que o trecho analisado se repete infinitamente; quando isso não é verdade, a descontinuidade na "emenda" vaza energia para frequências vizinhas (*spectral leakage*), borrando picos que deveriam ser nítidos — especialmente prejudicial para enxergar um supraharmônico de amplitude baixa perto de uma fundamental de amplitude alta. `adc_tool.py` trata esse problema com **duas estratégias complementares**, porque a fundamental/harmônicos e os supraharmônicos têm características diferentes que exigem tratamentos diferentes.

### `--fft`: corte em ciclos inteiros (fundamental e harmônicos)

A fundamental e seus harmônicos têm fase travada ao ciclo da rede elétrica, então dá para eliminar o vazamento na raiz: o trecho analisado é cortado exatamente num número inteiro de ciclos, localizados por cruzamento de zero interpolado linearmente (não preso à grade de amostragem). O processo:

1. Estimativa grosseira da fundamental por FFT (janela de Hann), refinada por interpolação parabólica em log-magnitude para reduzir o erro de quantização do bin sem precisar de uma FFT maior.
2. Filtro passa-baixa Butterworth (SOS, fase zero) isola a fundamental antes da detecção de cruzamento de zero.
3. Refinamento do período usando todos os ciclos disponíveis (dilui o erro de detecção de um cruzamento individual).
4. Corte do trecho exatamente nesses ciclos, ANTES da FFT principal.

```bash
# FFT ciclo-sincronizada de todos os ciclos completos da janela
python3 adc_tool.py captura.bin -f 102400 --fft

# Só os 10 primeiros ciclos (análise de um distúrbio momentâneo) --
# processa só o início da captura, não o buffer inteiro
python3 adc_tool.py captura.bin -f 102400 --fft 10
```

### `--welch`: espectro médio por segmentação (supraharmônicos)

Supraharmônicos vêm de conversores eletrônicos de potência chaveados e **não têm relação de fase com o ciclo da rede** — não existe corte de ciclo que elimine o vazamento desse conteúdo especificamente, e o próprio chaveamento costuma variar de frequência ao longo do tempo (*dithering*), o que uma única FFT longa borraria. Em vez de sincronismo de ciclo, `--welch` segmenta o sinal (tamanho definido por `--resolucao-welch`, em Hz de resolução), janela e transforma cada segmento, e **média** os periodogramas resultantes — reduz a variância da estimativa e suaviza a deriva de frequência, ao custo de uma resolução em frequência fixa.

```bash
# Espectro médio, resolução de 200 Hz, com passa-alta para remover o
# resíduo da fundamental antes de procurar supraharmônicos
python3 adc_tool.py captura.bin -f 102400 --welch --filtro-passa-alta 2000
```

> ⚠️ `--fft` precisa da fundamental intacta na faixa `--freq-min`/`--freq-max` para sincronizar o corte em ciclos. Um `--filtro-passa-alta` igual ou maior que `--freq-min` remove essa banda e invalida o resultado de `--fft` — nesse caso, rode `--fft` e `--welch`/`--picos` em **comandos separados**. `adc_tool.py` detecta essa combinação e avisa no console.

### Normalização, bandas e picos

* **`--modo-espectro {tom, ruido}`** — `tom` (padrão) mede a amplitude de um tom discreto; `ruido` reporta densidade espectral de potência (PSD, V²/Hz), correta para conteúdo de banda larga, onde `tom` daria uma leitura que muda artificialmente com o tamanho da FFT/segmento para o mesmo ruído físico.
* **`--agrupar-bandas HZ`** — resume o espectro em bandas de largura fixa (ex.: 200 Hz, convenção comum na caracterização de supraharmônicos), tornando o resultado comparável entre capturas com resoluções diferentes.
* **`--picos LIMIAR_DB`** — extrai frequência e amplitude de componentes espectrais individuais acima de um limiar, refinadas por interpolação parabólica — a extração quantitativa que complementa a inspeção visual do gráfico.

```bash
# Espectro médio, agrupado em bandas de 200 Hz, reportando picos acima de -60 dB
python3 adc_tool.py captura.bin -f 102400 --welch --agrupar-bandas 200 --picos -60
```

Rode `python3 adc_tool.py --help` (grupo "Análise espectral avançada") para a referência completa de flags.

## 🚀 Começando

### Pré-requisitos

* **Hardware:** Altium Designer (para edição da placa).
* **Software:** Linux/PopOS ou Windows 10 para desenvolvimento, toolchain C/C++ (GCC) e compilador Texas Instruments (`clpru`) para a BeagleBone. Python 3.10+ (com `numpy`/`pandas`/`matplotlib`/`scipy`) para os scripts. `adc_tool.py` também precisa de `PyQt6` (janela interativa do gráfico — sem ele, ainda funciona com `-o/--saida` para salvar em arquivo); declara suas dependências inline (PEP 723), então também pode ser rodado sem instalação manual via `uv run scripts/adc_tool.py ...`, se você tiver o [`uv`](https://docs.astral.sh/uv/) instalado.

### Instalação e Execução

1. **Fabricação da PCB:** utilize os arquivos Gerber na pasta `/hardware` para produção da placa de circuito impresso.
2. **Preparação da BeagleBone:** envie os arquivos da pasta `/firmware` para o microcomputador. **Evite jumpers longos** entre a placa de aquisição e o frontend analógico — conecte diretamente sempre que possível (ver "Status Atual").
3. **Compilação:** rode `make` dentro de `/firmware` para compilar o firmware da PRU (`fw_pru.out`) e o binário do ARM (`ler_adc`).
4. **Deploy:** execute `./setup.sh` para configurar os pinos e carregar o firmware na PRU.
5. **Aquisição:** rode `sudo ./ler_adc <frequência_em_Hz> [lista_de_canais] [--blocos N | --duracao T]` para iniciar a captura. `lista_de_canais` é opcional e separada por vírgulas sem espaços (ex.: `0,1,3`); sem ela, captura só o canal 1 (padrão histórico — único canal desta placa com sinal conectado por padrão). Com mais de um canal, a frequência informada é dividida entre eles, sempre em ordem crescente de canal (ver "Firmware").

   Por padrão, a captura para sozinha depois de **1 bloco** (`SAMPLES_PER_BUFFER` = 1.048.576 amostras brutas). Para controlar por quanto tempo a captura roda, use:
   * `--blocos N` — captura exatamente `N` blocos e para. `N=0` captura **indefinidamente**, até `Ctrl+C`.
   * `--duracao T` — alternativa mais conveniente quando o que importa é o tempo, não o número de blocos: aceita um sufixo `s`/`m`/`h` (ou nenhum, assumindo segundos) — ex. `600`, `10m`, `1.5h` — e o número de blocos equivalente é calculado automaticamente a partir da frequência escolhida.

   `--blocos` e `--duracao` são mutuamente exclusivas. Exemplos:
   ```bash
   sudo ./ler_adc 102400                    # 1 bloco, canal 1 (padrão)
   sudo ./ler_adc 102400 0,1,3 --blocos 5   # 5 blocos, 3 canais
   sudo ./ler_adc 102400 --blocos 0         # indefinido, até Ctrl+C
   sudo ./ler_adc 102400 --duracao 10m      # ~10 minutos de captura
   ```
   Rode `sudo ./ler_adc --help` para a referência completa de flags.

   * Se a captura parecer travada (nenhum "Bloco gravado" aparece), rode `firmware/debug_sh_analyzer.sh` em outro terminal antes de interromper — ele mostra se a PRU está progredindo ou presa, sem precisar de osciloscópio.
6. **Análise:** após a coleta, transfira os arquivos `.bin` para o seu computador principal e utilize as ferramentas da pasta `/scripts`. Para uma captura de 1 canal (padrão): `python3 adc_tool.py captura.bin -f <frequência_em_Hz> --fft` para visualizar, ou `adc_tool.py -c captura.bin -o captura.csv` para converter para `.csv`. Para uma captura multi-canal, informe a **mesma lista de canais, na ordem impressa pelo `ler_adc`** durante a captura, via `--canais`:
   ```bash
   # Captura feita com: sudo ./ler_adc 102400 0,1,3
   python3 adc_tool.py captura.bin -f 102400 --canais 0,1,3 --fft

   # Só os canais 0 e 3, sobrepostos no mesmo eixo em vez de subplots separados
   python3 adc_tool.py captura.bin -f 102400 --canais 0,1,3 \
       --canais-exibir 0,3 --layout-canais sobrepostos --fft

   # Canal 0 = tensão (ganho 19.53), canal 1 = corrente (ganho 0.1)
   python3 adc_tool.py captura.bin -f 102400 --canais 0,1 --ganho 19.53,0.1 --fft

   # Converter para .csv (ganha uma coluna 'canal' quando há mais de 1 canal)
   python3 adc_tool.py -c captura.bin -o captura.csv --canais 0,1,3
   ```
   Rode `python3 adc_tool.py --help` (seção "Captura multi-canal") para a referência completa.

   Para limpar ruído de alta frequência (ex.: aliasing residual perto da Nyquist) ou deriva de DC antes de plotar/calcular a FFT, use o filtro digital Butterworth opcional:
   ```bash
   # Captura a 102.4 kHz (Nyquist = 51.2 kHz): limpa ruído acima de 45 kHz
   python3 adc_tool.py captura.bin -f 102400 --filtro-passa-baixa 45000 --fft

   # Remove deriva de DC/baixa frequência com um filtro de ordem mais alta
   python3 adc_tool.py captura.bin -f 102400 --filtro-passa-alta 20 --ordem-filtro 8 --fft
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
