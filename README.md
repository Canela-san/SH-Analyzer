---

# SH-Analyzer: Analisador de Supraharmônicos
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

Um projeto de hardware e software embarcado de alto desempenho para a identificação e análise de supraharmônicos em redes e cargas elétricas, utilizando uma PCB customizada e o microcomputador industrial BeagleBone.

---

## 📝 Sumário

* [Sobre o Projeto](https://www.google.com/search?q=%23sobre-o-projeto)
* [Arquitetura e Desempenho](https://www.google.com/search?q=%23arquitetura-e-desempenho)
* [Estrutura do Repositório](https://www.google.com/search?q=%23estrutura-do-reposit%C3%B3rio)
* [Hardware](https://www.google.com/search?q=%23hardware)
* [Firmware](https://www.google.com/search?q=%23firmware)
* [Scripts e Análise](https://www.google.com/search?q=%23scripts-e-an%C3%A1lise)
* [Começando](https://www.google.com/search?q=%23come%C3%A7ando)
* [Contexto Acadêmico](https://www.google.com/search?q=%23contexto-acad%C3%AAmico)
* [Licença](https://www.google.com/search?q=%23licen%C3%A7a)
* [Agradecimentos](https://www.google.com/search?q=%23agradecimentos)

## 📖 Sobre o Projeto

A crescente utilização de conversores eletrônicos de potência (CEPs) tem introduzido perturbações de alta frequência em redes elétricas, conhecidas como **supraharmônicos**. Esses componentes, tipicamente na faixa de dezenas de kHz, frequentemente escapam da detecção por analisadores de Qualidade de Energia Elétrica (QEE) convencionais.

O **SH-Analyzer** é um sistema de instrumentação dedicado à identificação precisa dessas componentes supraharmônicas na corrente e na tensão de uma instalação elétrica. O projeto engloba o desenvolvimento de um frontend analógico de condicionamento de sinais (PCB) e uma arquitetura de firmware focada em amostragem de altíssima frequência.

## ⚡ Arquitetura e Desempenho

Para atingir taxas de amostragem na ordem das centenas de kHz (com metas de expansão para a faixa dos MSPS), o projeto adota uma filosofia rigorosa: **a qualidade e a integridade dos dados estão acima de qualquer economia de armazenamento em disco ou velocidade superficial de execução no sistema operacional.**

O sistema utiliza uma arquitetura híbrida no BeagleBone:

* **PRUs (Programmable Real-Time Units):** Encarregadas do controle determinístico e *bit-banging* via comunicação SPI com o conversor Analógico-Digital (ADC).
* **Processador Principal (ARM):** Focado exclusivamente em extrair os dados brutos da memória com segurança e gravá-los em disco o mais rápido possível, evitando corrupção ou perdas de amostras causadas por gargalos de software.

## 📂 Estrutura do Repositório

```text
.
├── /docs/          # Proposta de Iniciação Científica (IC), datasheets dos componentes e relatórios
├── /firmware/      # Códigos-fonte da PRU (Assembly/C), programas do ARM e scripts de configuração (ex: setup.sh)
├── /hardware/      # Arquivos de design da PCB, esquemático elétrico e modelo 3D (Altium Designer)
└── /scripts/       # Scripts Python para conversão, pós-processamento, aplicação de filtros e visualização dos dados

```

## 🔩 Hardware

O hardware atua como um frontend analógico de precisão.

* **Função:** Condicionar e adaptar os níveis de tensão e corrente vindos dos sensores para a faixa de operação ótima do ADC de alta velocidade.
* **Ferramenta:** O projeto da placa foi integralmente desenvolvido no **Altium Designer**.
* **Conteúdo:** A pasta `/hardware` contém os esquemáticos, o layout da PCB, visualizações 3D em alta resolução, lista de materiais (BOM) e os arquivos Gerber para fabricação.

## 💻 Firmware

O firmware gerencia todo o ecossistema de aquisição em tempo real na BeagleBone.

* **Linguagens:** C e Assembly.
* **PRU:** O laço de controle crítico de tempo é executado nas PRUs (em Assembly ou C otimizado) para garantir latência zero na varredura dos dados do ADC.
* **ARM (Linux):** Códigos em C no processador principal gerenciam a leitura da memória compartilhada e o despejo (dump) eficiente dos blocos de dados para o armazenamento não volátil.
* **Setup:** O arquivo `setup.sh` automatiza a configuração da pinagem (device tree overlays) e a preparação do ambiente do sistema operacional antes da execução.

## 📊 Scripts e Análise

Para não sobrecarregar o processador embarcado durante a coleta crítica de dados, o cálculo de grandezas físicas e a análise espectral são desacoplados do firmware.

* **Pós-processamento:** A pasta `/scripts` contém rotinas em Python encarregadas de ler os arquivos binários gerados pela BeagleBone.
* **Funcionalidades:** Extração de métricas, Transformada Rápida de Fourier (FFT), filtragem digital e plotagem de gráficos para análise dos supraharmônicos.

## 🚀 Começando

### Pré-requisitos

* **Hardware:** Altium Designer (para edição da placa).
* **Software:** Sistema operacional Linux/PopOS ou Windows 10 para desenvolvimento, toolchain C/C++ (GCC) e compilador Texas Instruments (`clpru`) para a BeagleBone. Python 3+ para execução dos scripts.

### Instalação e Execução

1. **Fabricação da PCB:** Utilize os arquivos Gerber na pasta `/hardware` para produção da placa de circuito impresso.
2. **Preparação da BeagleBone:** Envie os arquivos da pasta `/firmware` para o microcomputador. Execute o `./setup.sh` para configurar os pinos e preparar o ambiente.
3. **Compilação:** Compile o firmware das PRUs e os binários do ARM utilizando os Makefiles fornecidos.
4. **Análise:** Após a coleta, transfira os arquivos de dados para o seu computador principal e utilize as ferramentas da pasta `/scripts` para visualização.

## 🎓 Contexto Acadêmico

Este projeto é o resultado prático de uma pesquisa de Iniciação Científica (IC) vinculada ao projeto "Sistema de identificação da presença de supraharmônicos em redes e cargas elétricas", desenvolvida no curso de Engenharia de Controle e Automação da Universidade Estadual de Campinas (Unicamp).

* **Orientação:** Prof. Dr. José Antenor Pomilio.
* **Coorientação:** Dr. Mateus Pinheiro Dias.

## 📄 Licença

Este projeto é distribuído sob a Licença MIT. Veja o arquivo `LICENSE` para mais detalhes.

## 🙏 Agradecimentos

Um agradecimento especial ao Prof. Dr. José Antenor Pomilio e ao Dr. Mateus Pinheiro Dias pela orientação contínua, excelência técnica e suporte ao longo de todo o desenvolvimento desta pesquisa.