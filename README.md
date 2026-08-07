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

* **PRU (Programmable Real-Time Unit):** Encarregada do controle determinístico e *bit-banging* via comunicação SPI (protocolo manual de 32 ciclos) com o conversor Analógico-Digital ADS8688, e da gravação direta das amostras num par de buffers ("ping-pong") reservados numa região exclusiva da DDR (fora do alcance do gerenciador de memória do Linux).
* **Processador Principal (ARM):** Focado exclusivamente em extrair os blocos prontos da DDR e gravá-los em disco (`.bin`) o mais rápido possível, evitando corrupção ou perdas de amostras causadas por gargalos de software.
* **Sincronização ARM ↔ PRU:** feita via uma pequena struct de controle (`shared_control`, em `memoria_pru.h`) mapeada numa região dedicada da RAM interna da PRU-ICSS - inclui um handshake explícito (`config_ready`) para garantir que a PRU só comece a gravar depois que o ARM já configurou os endereços físicos dos buffers.

## 🩺 Status Atual / Depuração em Andamento

A reescrita do firmware original (protótipo em C puro, veja `backup pre-assembly/`) para a arquitetura híbrida PRU (Assembly) + ARM, com o objetivo de superar o limite de ~102,4 kHz do protótipo, está em andamento. Já foram resolvidos e validados:

* Protocolo correto do ADS8688 em modo manual: frame de **32 ciclos de SCLK** por amostra (16 para escrever o comando + 16 para ler o dado da conversão anterior), com o comando `MAN_Ch_0` reenviado a cada frame.
* Handshake de sincronização `config_ready` entre ARM e PRU (evita a PRU gravar num endereço de buffer ainda não configurado).
* Ressincronização periódica do registrador `CYCLE` da PRU (que **trava** em vez de dar a volta ao estourar 32 bits, ~21,47 s a 200 MHz) - sem isso, capturas longas travavam sozinhas.
* Inicialização explícita de CS/SCLK/MOSI em repouso antes do laço principal.
* Uso de laços de atraso (em vez de `NOP` repetido) para controlar a velocidade do SPI sem estourar os 8 KB de `PRU_IMEM`.

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
* **ARM (Linux):** `ler_adc.c` mapeia a região de controle e os buffers de dados via `/dev/mem`, e despeja os blocos prontos direto em disco como binário bruto (`.bin`), sem processamento em tempo real.
* **`memoria_pru.h`:** define o layout da struct de controle compartilhada e as constantes de endereço físico/tamanho de buffer - compartilhado entre o código C do ARM e (por valor, manualmente sincronizado) as constantes hardcoded no Assembly da PRU.
* **Setup:** o arquivo `setup.sh` automatiza a configuração da pinagem (via `config-pin`) e carrega o firmware compilado (`fw_pru.out`) no `remoteproc`.

## 📊 Scripts e Análise

Para não sobrecarregar o processador embarcado durante a coleta crítica de dados, o cálculo de grandezas físicas e a análise espectral são desacoplados do firmware.

* **Pós-processamento:** a pasta `/scripts` contém rotinas em Python encarregadas de ler os arquivos binários gerados pela BeagleBone.
* **Funcionalidades:** extração de métricas, Transformada Rápida de Fourier (FFT), filtragem digital e plotagem de gráficos para análise dos supraharmônicos (`analise.py`, `plot_adc.py`, `verificar_dados.py`).
* **Diagnóstico:** `analisar_preambulo.py` inspeciona capturas feitas com o firmware de diagnóstico (ver comentários em `firmware/spi_core_diagnostico_preambulo.asm`), separando os 16 bits de "preâmbulo" (que deveriam ser sempre zero) dos 16 bits de dado real, para isolar problemas de protocolo/hardware sem precisar de osciloscópio.

## 🚀 Começando

### Pré-requisitos

* **Hardware:** Altium Designer (para edição da placa).
* **Software:** Sistema operacional Linux/PopOS ou Windows 10 para desenvolvimento, toolchain C/C++ (GCC) e compilador Texas Instruments (`clpru`) para a BeagleBone. Python 3+ (com `numpy`/`pandas`/`matplotlib`/`scipy`) para execução dos scripts.

### Instalação e Execução

1. **Fabricação da PCB:** utilize os arquivos Gerber na pasta `/hardware` para produção da placa de circuito impresso.
2. **Preparação da BeagleBone:** envie os arquivos da pasta `/firmware` para o microcomputador.
3. **Compilação:** rode `make` dentro de `/firmware` para compilar o firmware da PRU (`fw_pru.out`) e o binário do ARM (`ler_adc`).
4. **Deploy:** execute `./setup.sh` para configurar os pinos e carregar o firmware na PRU.
5. **Aquisição:** rode `sudo ./ler_adc <frequência_em_Hz>` para iniciar a captura.
6. **Análise:** após a coleta, transfira os arquivos `.bin` para o seu computador principal e utilize as ferramentas da pasta `/scripts` para visualização.

## 🎓 Contexto Acadêmico

Este projeto é o resultado prático de uma pesquisa de Iniciação Científica (IC) vinculada ao projeto "Sistema de identificação da presença de supraharmônicos em redes e cargas elétricas", desenvolvida no curso de Engenharia de Controle e Automação da Universidade Estadual de Campinas (Unicamp).

* **Orientação:** Prof. Dr. José Antenor Pomilio.
* **Coorientação:** Dr. Mateus Pinheiro Dias.

## 📄 Licença

Este projeto é distribuído sob a Licença MIT. Veja o arquivo `LICENSE` para mais detalhes.

## 🙏 Agradecimentos

Um agradecimento especial ao Prof. Dr. José Antenor Pomilio e ao Dr. Mateus Pinheiro Dias pela orientação contínua, excelência técnica e suporte ao longo de todo o desenvolvimento desta pesquisa.