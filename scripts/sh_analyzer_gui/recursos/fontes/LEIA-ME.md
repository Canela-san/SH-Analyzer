# Fontes embutidas

As fontes que o aplicativo registra na partida, para ficar igual em qualquer máquina. A lista (a família, o papel,
os arquivos, a licença, a versão e de onde veio cada uma) está em `sh_analyzer_gui/tema/fontes_embutidas.py`, e o
`tests/test_tema.py` confere que cada arquivo daqui está nela e tem a licença ao lado.

| Família | Papel | Versão | Licença |
|---|---|---|---|
| Inter | interface | 4.001 (o arquivo variável, todos os pesos) | `Inter-OFL.txt` (SIL OFL 1.1) |
| JetBrains Mono | números alinhados e terminal | 2.304 (Regular, Medium, Bold) | `JetBrainsMono-OFL.txt` (SIL OFL 1.1) |

Para pôr uma fonte nova (para o usuário escolher nas configurações): os arquivos e a licença nesta pasta, e uma entrada
em `fontes_embutidas.py`. Só licenças livres que permitem embutir (OFL, Apache, MIT).
