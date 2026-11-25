## Instalar

**Ubuntu, Pop!_OS e Debian** (Ubuntu 22.04 ou mais novo, Debian 12 ou mais novo): num terminal, uma vez só:

```bash
sudo wget -qO /usr/share/keyrings/sh-analyzer.gpg https://canela-san.github.io/SH-Analyzer/sh-analyzer.gpg
sudo wget -qO /etc/apt/sources.list.d/sh-analyzer.sources https://canela-san.github.io/SH-Analyzer/sh-analyzer.sources
sudo apt update
sudo apt install sh-analyzer
```

Depois disso, o SH-Analyzer aparece no menu de aplicativos. As versões novas chegam pelo Atualizador de Programas do sistema (ou com `sudo apt upgrade`). Também dá para instalar só o `.deb` desta página, com dois cliques: ele já configura o repositório para as próximas versões.

**Windows 10 e 11** (64 bits): baixe e abra o `sh-analyzer-…-windows-x64.exe`. Ele instala para o seu usuário, sem pedir o administrador, e cria o atalho na área de trabalho. O instalador ainda não é assinado, então o Windows pode mostrar "O Windows protegeu o computador". Nesse caso, clique em **Mais informações → Executar assim mesmo**. As versões seguintes são oferecidas pelo próprio aplicativo, que as instala com um clique.

**Outras distribuições Linux:** use a pasta do `.tar.gz`. Descompacte-a e rode o `sh-analyzer-gui` de dentro dela.

Para conferir o que baixou, as somas SHA-256 de cada arquivo estão no `SHA256SUMS`.

## O que há de novo

A v0.9 traz a **interface gráfica** do SH-Analyzer, para quem analisa sem a linha de comando:

- **Análise:**
  - o espectro, o espectrograma, a forma de onda e o modo Instrumento (os ciclos sobrepostos, como num osciloscópio, com o disparo que rejeita a alta frequência);
  - a grade de vistas com os eixos ligados.
- **Análises para pesquisa:**
  - a detecção de eventos;
  - os índices de qualidade de energia da IEC 61000-4-30 (janelas de 12 ciclos, com as janelas marcadas);
  - a função de transferência e a coerência, com o intervalo de confiança;
  - as métricas de bancada e o aliasing.
- **Figuras para artigo:**
  - os modelos IEEE e outros, o estilo de cada elemento, a visão em cinza e com daltonismo;
  - a exportação em PDF, SVG, PNG e PGF;
  - o pacote que refaz cada figura sem o SH-Analyzer.
- **Dados:** a exportação em HDF5, MAT, NPZ e CSV, e os pacotes compactados `.zpaq.tar`.
- **A placa:**
  - a conexão pela rede e a captura direto no computador, com o "Conferir antes";
  - as rotinas de coleta e o caderno de bancada;
  - a manutenção: o firmware, os logs, os serviços e o resgate pela serial;
  - uma placa simulada, para aprender sem o hardware.
- **Ajuda:** o guia embutido ("?" e F1 em cada vista) e os primeiros passos.
- **Projetos** `.shproj`, que guardam as vistas, os cursores e as figuras.
