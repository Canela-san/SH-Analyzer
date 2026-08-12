# SH-Analyzer: Analisador de Supraharmônicos
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

Um projeto de hardware e software embarcado de alto desempenho para a identificação e análise de supraharmônicos em redes e cargas elétricas, utilizando uma PCB customizada e o microcomputador industrial BeagleBone.

---

## 📝 Sumário

* [Sobre o Projeto](#sobre-o-projeto)
* [Arquitetura e Desempenho](#arquitetura-e-desempenho)
* [Status Atual / Depuração em Andamento](#status-atual--depuração-em-andamento)
* [Estrutura do Repositório](#estrutura-do-repositório)
* [Hardware](#hardware)
* [Firmware](#firmware)
* [Scripts e Análise](#scripts-e-análise)
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

* **PRU (Programmable Real-Time Unit):** Encarregada do controle determinístico e *bit-banging* via comunicação SPI (protocolo manual de 32 ciclos) com o conversor Analógico-Digital ADS8688, e da gravação direta das amostras num par de buffers ("ping-pong") reservados numa região exclusiva da DDR (fora do alcance do gerenciador de memória do Linux). Suporta capturar 1 ou vários canais do ADS8688 ao mesmo tempo, intercalados (round-robin) num mesmo par de buffers -- ver `firmware/ler_adc.c` e `firmware/spi_core.asm`.
* **Processador Principal (ARM):** Focado exclusivamente em extrair os blocos prontos da DDR e gravá-los em disco (`.bin`) o mais rápido possível, evitando corrupção ou perdas de amostras causadas por gargalos de software. Também é responsável por configurar quais canais do ADC serão lidos em cada captura.
* **Sincronização ARM ↔ PRU:** feita via uma pequena struct de controle (`shared_control`, em `memoria_pru.h`) mapeada numa região dedicada da RAM interna da PRU-ICSS - inclui um handshake explícito (`config_ready`) para garantir que a PRU só comece a gravar depois que o ARM já configurou os endereços físicos dos buffers, o número de canais ativos e a tabela de comandos de canal usada na intercalação.

## 🩺 Status Atual / Depuração em Andamento

A reescrita do firmware original (protótipo em C puro, veja `backup pre-assembly/`) para a arquitetura híbrida PRU (Assembly) + ARM, com o objetivo de superar o limite de ~102,4 kHz do protótipo, está em andamento. Já foram resolvidos e validados **em hardware**:

* Protocolo correto do ADS8688 em modo manual: frame de **32 ciclos de SCLK** por amostra (16 para escrever o comando + 16 para ler o dado da conversão anterior). Nesta placa, o canal 1 (`MAN_Ch_1`, comando `0xC400`) é o que está de fato conectado a um sinal válido -- o canal 0 fica saturado em fundo de escala mesmo com a comunicação SPI comprovadamente correta (ver histórico de depuração no cabeçalho de `firmware/spi_core.asm`). É por isso que o canal 1 é o padrão quando nenhuma lista de canais é passada a `ler_adc`.
* Handshake de sincronização `config_ready` entre ARM e PRU (evita a PRU gravar num endereço de buffer ainda não configurado).
* Ressincronização periódica do registrador `CYCLE` da PRU (que **trava** em vez de dar a volta ao estourar 32 bits, ~21,47 s a 200 MHz) - sem isso, capturas longas travavam sozinhas.
* Inicialização explícita de CS/SCLK/MOSI em repouso antes do laço principal.
* Uso de laços de atraso (em vez de `NOP` repetido) para controlar a velocidade do SPI sem estourar os 8 KB de `PRU_IMEM`.

### 🆕 Captura multi-canal -- implementada, aguardando validação em hardware

O firmware (`ler_adc.c`, `spi_core.asm`, `pru_main.c`, `memoria_pru.h`) e o `adc_tool.py` já têm suporte completo a capturar vários canais do ADS8688 intercalados (round-robin) numa mesma captura -- ver a seção "Começando" para o uso, e a seção 10 do docstring de `adc_tool.py` (`python3 adc_tool.py --help`) para a referência completa.

**O que já foi verificado:** a lógica do lado ARM (parsing de argumentos, montagem da tabela de comandos de canal, tratamento do atraso de pipeline de 1 quadro do ADS8688 -- ver comentário no cabeçalho de `spi_core.asm`) foi validada com testes automatizados isolados (dados sintéticos), e `adc_tool.py` foi validado ponta a ponta com capturas multi-canal sintéticas, incluindo o round-trip `.bin -> .csv -> .bin`.

**O que AINDA NÃO foi validado:** as mudanças em `spi_core.asm` (o índice de canal round-robin que substitui o comando fixo `MAN_Ch_1`) não foram compiladas com o `clpru` nem testadas na PRU real -- isso ainda precisa ser feito com cuidado antes de confiar na captura multi-canal em produção, especialmente considerando o bug de saturação de SPI abaixo, ainda em aberto mesmo no caminho de 1 canal já validado.

**Em aberto:** a comunicação SPI ainda está saturando no valor de fundo de escala (leitura constante, independente da tensão real de entrada), mesmo em velocidades bem mais lentas que o firmware original comprovadamente funcional (`backup pre-assembly/teste_spi_pru.c`). Os testes de diagnóstico (captura do "preâmbulo" de 16 bits que deveria ser sempre zero - ver `scripts/analisar_preambulo.py`) indicam um padrão de transição único e consistente, característico de assimetria de tempo de subida/descida num optoacoplador. Próximo passo: eliminar os jumpers longos e conectar as placas diretamente, para isolar se a causa é mesmo integridade de sinal.

## 📂 Estrutura do Repositório

```text
.
├── /docs/                     # Proposta de Iniciação Científica (IC), datasheets dos componentes e relatórios
├── /firmware/                 # Firmware da PRU (Assembly/C), programa do ARM, memoria_pru.h e scripts de deploy (setup.sh, comandos.sh)
├── /hardware/                 # Arquivos de design da PCB, esquemático elétrico e modelo 3D (Altium Designer)
├── /scripts/                  # Scripts Python para conversão, pós-processamento, aplicação de filtros e visualização dos dados
└── /backup pre-assembly/      # Protótipo funcional em C puro (pré-reescrita em Assembly), mantido como referência de comportamento correto

```

## 🔩 Hardware

O hardware atua como um frontend analógico de precisão.

* **Função:** Condicionar e adaptar os níveis de tensão e corrente vindos dos sensores para a faixa de operação ótima do ADC de alta velocidade, incluindo isolamento galvânico (optoacoplador) entre a PRU e o frontend conectado à rede elétrica.
* **Ferramenta:** O projeto da placa foi integralmente desenvolvido no **Altium Designer**.
* **Conteúdo:** A pasta `/hardware` contém os esquemáticos, o layout da PCB, visualizações 3D em alta resolução, lista de materiais (BOM) e os arquivos Gerber para fabricação.

## 💻 Firmware

O firmware gerencia todo o ecossistema de aquisição em tempo real na BeagleBone.

* **Linguagens:** C (ARM) e Assembly (PRU).
* **PRU:** o laço de controle crítico de tempo (`spi_core.asm`) é executado inteiramente em Assembly para garantir timing determinístico na varredura do ADC; `pru_main.c` faz a inicialização mínima (contador de ciclos, handshake) antes de chamar a rotina em Assembly.
* **ARM (Linux):** `ler_adc.c` mapeia a região de controle e os buffers de dados via `/dev/mem`, configura quais canais do ADS8688 serão lidos (um só, por padrão, ou uma lista intercalada), e despeja os blocos prontos direto em disco como binário bruto (`.bin`), sem processamento em tempo real.
* **`memoria_pru.h`:** define o layout da struct de controle compartilhada (incluindo a configuração multi-canal) e as constantes de endereço físico/tamanho de buffer - compartilhado entre o código C do ARM e (por valor, manualmente sincronizado) as constantes hardcoded no Assembly da PRU.
* **Setup:** o arquivo `setup.sh` automatiza a configuração da pinagem (via `config-pin`) e carrega o firmware compilado (`fw_pru.out`) no `remoteproc`.

## 📊 Scripts e Análise

Para não sobrecarregar o processador embarcado durante a coleta crítica de dados, o cálculo de grandezas físicas e a análise espectral são desacoplados do firmware.

* **Pós-processamento:** a pasta `/scripts` contém rotinas em Python encarregadas de ler os arquivos binários gerados pela BeagleBone.
* **Funcionalidades:** extração de métricas, Transformada Rápida de Fourier (FFT), filtragem digital, plotagem de gráficos e conversão de formato (`.bin` ↔ `.csv`) para análise dos supraharmônicos (`analise.py`, `adc_tool.py` — renomeado do antigo `plot_adc.py`, já que o script deixou de fazer só plotagem —, `verificar_dados.py`). `adc_tool.py` lê, plota e converte tanto capturas de 1 canal quanto capturas multi-canal (`--canais`/`--canais-exibir`/`--layout-canais`), com FFT independente por canal e calibração (`--faixa`/`--ganho`/`--offset`) configurável por canal -- ver `python3 adc_tool.py --help` ou a seção 10 do docstring do módulo para a referência completa.
* **Diagnóstico:** `analisar_preambulo.py` inspeciona capturas feitas com o firmware de diagnóstico (ver comentários em `firmware/spi_core_diagnostico_preambulo.asm`), separando os 16 bits de "preâmbulo" (que deveriam ser sempre zero) dos 16 bits de dado real, para isolar problemas de protocolo/hardware sem precisar de osciloscópio.

## 🚀 Começando

### Pré-requisitos

* **Hardware:** Altium Designer (para edição da placa).
* **Software:** Sistema operacional Linux/PopOS ou Windows 10 para desenvolvimento, toolchain C/C++ (GCC) e compilador Texas Instruments (`clpru`) para a BeagleBone. Python 3.10+ (com `numpy`/`pandas`/`matplotlib`/`scipy`) para execução dos scripts. `adc_tool.py` especificamente também precisa de `PyQt6` (janela interativa do gráfico -- sem ele, ainda funciona normalmente com `-o/--saida` para salvar em arquivo); ele declara todas as suas dependências inline (PEP 723) no próprio cabeçalho, então também pode ser rodado sem instalação manual via `uv run scripts/adc_tool.py ...`, se você tiver o [`uv`](https://docs.astral.sh/uv/) instalado.

### Instalação e Execução

1. **Fabricação da PCB:** utilize os arquivos Gerber na pasta `/hardware` para produção da placa de circuito impresso.
2. **Preparação da BeagleBone:** envie os arquivos da pasta `/firmware` para o microcomputador.
3. **Compilação:** rode `make` dentro de `/firmware` para compilar o firmware da PRU (`fw_pru.out`) e o binário do ARM (`ler_adc`).
4. **Deploy:** execute `./setup.sh` para configurar os pinos e carregar o firmware na PRU.
5. **Aquisição:** rode `sudo ./ler_adc <frequência_em_Hz> [lista_de_canais]` para iniciar a captura. `lista_de_canais` é opcional e separada por vírgulas sem espaços (ex.: `0,1,3`); sem ela, captura só o canal 1 (comportamento padrão/histórico). Com mais de um canal, a frequência informada é dividida entre eles (amostras intercaladas em round-robin, na ordem passada). Exemplos: `sudo ./ler_adc 102400` (só canal 1, como antes) ou `sudo ./ler_adc 102400 0,1,3` (3 canais, cada um efetivamente a ~34,1 kHz).
6. **Análise:** após a coleta, transfira os arquivos `.bin` para o seu computador principal e utilize as ferramentas da pasta `/scripts`. Para uma captura de 1 canal (padrão), nada muda: `python3 adc_tool.py captura.bin -f <frequência_em_Hz> --fft` para visualizar, ou `adc_tool.py -c captura.bin -o captura.csv` para converter para `.csv`. Para uma captura multi-canal, informe a MESMA lista de canais (e a mesma ordem) usada em `ler_adc` via `--canais` -- o `.bin` não carrega esse metadado, então é essa a hora de usar a lista que `ler_adc` imprimiu no console durante a captura:
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
   Rode `python3 adc_tool.py --help` (seção "Captura multi-canal") ou veja a seção 10 do docstring do módulo para a referência completa -- incluindo como funciona a calibração por canal, o layout de plotagem e o formato do `.csv` multi-canal.

## 🎓 Contexto Acadêmico

Este projeto é o resultado prático de uma pesquisa de Iniciação Científica (IC) vinculada ao projeto "Sistema de identificação da presença de supraharmônicos em redes e cargas elétricas", desenvolvida no curso de Engenharia de Controle e Automação da Universidade Estadual de Campinas (Unicamp).

* **Orientação:** Prof. Dr. José Antenor Pomilio.
* **Coorientação:** Dr. Mateus Pinheiro Dias.

## 📄 Licença

Este projeto é distribuído sob a Licença MIT. Veja o arquivo `LICENSE` para mais detalhes.

## 🙏 Agradecimentos

Um agradecimento especial ao Prof. Dr. José Antenor Pomilio e ao Dr. Mateus Pinheiro Dias pela orientação contínua, excelência técnica e suporte ao longo de todo o desenvolvimento desta pesquisa.