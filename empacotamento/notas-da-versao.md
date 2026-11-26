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

A v0.9.1 transforma o gráfico num **caderno de anotações** e traz o **caderno de notas**:

- **Anotações no gráfico** (a tecla A, ou o botão da caneta da vista):
  - textos, setas, linhas, retângulos, elipses, regiões, cotas de Δt e Δf, níveis e marcadores, cada um com a sua tecla;
  - o desenho à mão livre, com o mouse ou com a mesa digitalizadora (a pressão afina e engrossa a linha), o marca-texto e a borracha;
  - escolher, mover, esticar e distorcer pelas alças, inclusive o alvo de uma seta; o texto escrito no próprio gráfico;
  - o estilo de cada uma: a cor, o preenchimento, a espessura, o traço, a opacidade, a fonte, a ponta da seta, a forma do marcador e a trava;
  - as anotações vão para as figuras e para o pacote que as refaz.
- **O caderno de notas** (Ctrl+Shift+N, de qualquer lugar):
  - páginas em Markdown com o realce ao vivo (`#` vira um título, as listas, as tarefas, o código...) e a página formatada;
  - referências a um ponto ou a um trecho de um gráfico: o clique nelas leva a vista até ali;
  - a imagem do gráfico e as imagens coladas guardadas junto.
- **Correções:**
  - o traço não some mais a partir de um certo zoom;
  - apagar a duração na Captura para escrever outra não mostra mais um erro;
  - o diálogo dos pinos da PRU não corta mais o texto.
- E o que veio desde a v0.9: importar dados de fora (osciloscópio, CSV, WAV, COMTRADE), o relatório da captura, a análise em lote com a tendência, as curvas de limite das bandas IEC, a diferença entre espectros, o notebook do Jupyter no pacote da figura e uma partida três vezes mais rápida.

Os projetos com as anotações novas usam o formato 8: a v0.9 não os abre (ela pede para atualizar o aplicativo).
