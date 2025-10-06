# SH-Analyzer: Analisador de Supraharmônicos
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

Um projeto de hardware e software embarcado para a identificação e análise de supraharmônicos em redes e cargas elétricas, utilizando uma PCB customizada e um microcomputador industrial BeagleBone.

---

## 📝 Sumário
* [Sobre o Projeto](#-sobre-o-projeto)
* [Funcionalidades](#-funcionalidades)
* [Estrutura do Repositório](#-estrutura-do-repositório)
* [Hardware](#-hardware)
* [Firmware](#-firmware)
* [Começando](#-começando)
* [Contexto Acadêmico](#-contexto-acadêmico)
* [Licença](#-licença)
* [Agradecimentos](#-agradecimentos)

## 📖 Sobre o Projeto

[cite_start]A crescente utilização de conversores eletrônicos de potência (CEPs) tem introduzido perturbações de alta frequência em redes elétricas, conhecidas como **supraharmônicos**[cite: 5]. [cite_start]Esses componentes, tipicamente na faixa de dezenas de kHz, podem não ser corretamente identificados por analisadores de Qualidade de Energia Elétrica (QEE) convencionais[cite: 7].

O **SH-Analyzer** nasce como uma solução para este problema. [cite_start]Trata-se de um sistema de instrumentação dedicado à identificação da presença de componentes supraharmônicos significativos na corrente e na tensão de uma instalação elétrica[cite: 8].

Este repositório contém o desenvolvimento do frontend de aquisição de dados, que inclui uma placa de circuito impresso (PCB) para condicionamento de sinais e o firmware de baixo nível para o processamento no microcomputador industrial.

## ✨ Funcionalidades

* [cite_start]**Condicionamento de Sinal**: Placa dedicada para compatibilizar os sinais de sensores de tensão e corrente com as entradas do conversor AD[cite: 14].
* **Aquisição de Dados em Alta Frequência**: Sistema projetado para digitalizar sinais na faixa de dezenas de kHz, onde os supraharmônicos se manifestam.
* **Processamento Embarcado**: Utilização do microcomputador industrial BeagleBone para controle da aquisição e processamento inicial dos dados.
* **Design Aberto**: Todos os arquivos de design de hardware, firmware e documentação estão disponíveis neste repositório.

## 📂 Estrutura do Repositório

O projeto está organizado nos seguintes diretórios:
Com certeza. Um README.md bem-feito é o cartão de visitas do seu repositório.

Com base nas informações que você forneceu e nos detalhes do projeto, preparei um arquivo README.md completo e profissional. Ele está estruturado com as seções mais importantes para um projeto de hardware e software embarcado.

Você pode copiar e colar o conteúdo abaixo diretamente em um arquivo README.md no seu repositório do GitHub.

Markdown

# SH-Analyzer: Analisador de Supraharmônicos
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

Um projeto de hardware e software embarcado para a identificação e análise de supraharmônicos em redes e cargas elétricas, utilizando uma PCB customizada e um microcomputador industrial BeagleBone.

---

## 📝 Sumário
* [Sobre o Projeto](#-sobre-o-projeto)
* [Funcionalidades](#-funcionalidades)
* [Estrutura do Repositório](#-estrutura-do-repositório)
* [Hardware](#-hardware)
* [Firmware](#-firmware)
* [Começando](#-começando)
* [Contexto Acadêmico](#-contexto-acadêmico)
* [Licença](#-licença)
* [Agradecimentos](#-agradecimentos)

## 📖 Sobre o Projeto

[cite_start]A crescente utilização de conversores eletrônicos de potência (CEPs) tem introduzido perturbações de alta frequência em redes elétricas, conhecidas como **supraharmônicos**[cite: 5]. [cite_start]Esses componentes, tipicamente na faixa de dezenas de kHz, podem não ser corretamente identificados por analisadores de Qualidade de Energia Elétrica (QEE) convencionais[cite: 7].

O **SH-Analyzer** nasce como uma solução para este problema. [cite_start]Trata-se de um sistema de instrumentação dedicado à identificação da presença de componentes supraharmônicos significativos na corrente e na tensão de uma instalação elétrica[cite: 8].

Este repositório contém o desenvolvimento do frontend de aquisição de dados, que inclui uma placa de circuito impresso (PCB) para condicionamento de sinais e o firmware de baixo nível para o processamento no microcomputador industrial.

## ✨ Funcionalidades

* [cite_start]**Condicionamento de Sinal**: Placa dedicada para compatibilizar os sinais de sensores de tensão e corrente com as entradas do conversor AD[cite: 14].
* **Aquisição de Dados em Alta Frequência**: Sistema projetado para digitalizar sinais na faixa de dezenas de kHz, onde os supraharmônicos se manifestam.
* **Processamento Embarcado**: Utilização do microcomputador industrial BeagleBone para controle da aquisição e processamento inicial dos dados.
* **Design Aberto**: Todos os arquivos de design de hardware, firmware e documentação estão disponíveis neste repositório.

## 📂 Estrutura do Repositório

O projeto está organizado nos seguintes diretórios:

.

├── /hardware/      # Arquivos de design da PCB (Esquemático, Layout, 3D, Gerber)

├── /firmware/      # Código fonte em Assembly para o BeagleBone (PRUs)

├── /docs/          # Documentação geral, datasheets, relatórios e guias

└── /simulation/    # Arquivos de simulação dos circuitos analógicos (PSIM, PSpice)


## 🔩 Hardware

O hardware consiste em uma placa de circuito impresso (PCB) que atua como um frontend analógico.

* **Função**: Adaptar os níveis de tensão e corrente vindos dos sensores para a faixa de operação do conversor Analógico-Digital (ADC).
* **Software de Design**: O projeto da PCB foi desenvolvido utilizando o **Altium Designer**.
* **Conteúdo**: O diretório `/hardware` contém os arquivos de esquemático, layout, visualização 3D, lista de materiais (BOM) e arquivos Gerber para fabricação.

## 💻 Firmware

O firmware é responsável por controlar o processo de amostragem do ADC e realizar a transferência dos dados.

* **Plataforma**: BeagleBone Black.
* **Linguagem**: **Assembly**, para garantir o controle em tempo real e a alta performance necessários para a amostragem de sinais em alta frequência. O código é voltado para as **PRUs** (Programmable Real-Time Units) do processador AM335x.
* **Funcionalidade**: O firmware inicializa o ADC, gerencia o timing das conversões e armazena os dados digitalizados em memória para posterior processamento ou envio.

## 🚀 Começando

Para replicar ou utilizar este projeto, siga os passos abaixo.

### Pré-requisitos
* Software Altium Designer para visualizar/editar os arquivos da PCB.
* Ambiente de desenvolvimento para a BeagleBone (ex: Code Composer Studio ou toolchain GCC para ARM).
* Componentes eletrônicos listados na Lista de Materiais (BOM).

### Instalação
1.  **Hardware**: Utilize os arquivos Gerber no diretório `/hardware` para fabricar a PCB. Realize a montagem dos componentes conforme a lista de materiais e o esquemático.
2.  **Firmware**: Clone o repositório. Compile o código Assembly localizado em `/firmware` e transfira o binário para o BeagleBone. Instruções detalhadas de compilação e deployment estão na documentação.

## 🎓 Contexto Acadêmico

[cite_start]Este projeto é resultado de uma pesquisa de **Iniciação Científica (IC)** desenvolvida no âmbito do projeto "Sistema de identificação da presença de supraharmônicos em redes e cargas elétricas"[cite: 2].

* [cite_start]**Orientador**: Prof. Dr. José Antenor Pomilio[cite: 3].
* [cite_start]**Objetivo**: Formação de recursos humanos qualificados para pesquisas na área de instrumentação voltada a estudos de QEE[cite: 15].

## 📄 Licença

Este projeto é distribuído sob a Licença MIT. Veja o arquivo `LICENSE` para mais detalhes.

## 🙏 Agradecimentos
* Agradecimento especial ao Prof. Dr. José Antenor Pomilio pela orientação e suporte durante o desenvolvimento deste projeto.
