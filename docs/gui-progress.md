# Andamento da interface gráfica

O diário e a lista de tarefas do desenvolvimento da GUI. O **plano** (o quê e por quê) está em [`gui-plan.md`](gui-plan.md); este arquivo diz **onde o trabalho parou e qual é o próximo passo**. Com ele, o trabalho continua igual depois de uma pausa, numa sessão nova ou nas mãos de outra pessoa.

**Atualize este arquivo a cada tarefa concluída e antes de qualquer pausa.**

---

## Próxima tarefa

> **F1.5: a vista de tempo** (seção 4b). Da Fase 1, estão feitas a F1.1 (a janela), a F1.2 (o modelo e o desfazer),
> a F1.3 (o projeto `.shproj`) e a F1.4 (abrir capturas e o painel do projeto).
>
>
> **No laboratório (opcional, 5 minutos):** a F0.2 colhe da BeagleBone os dados que a Aquisição vai usar (seção 6).

**Onde trabalhar:** no worktree `.claude/worktrees/interface` (o branch `feat/interface`), para não mexer no checkout do `main`, que é o do laboratório. Se ele não existir, crie-o com `git worktree add .claude/worktrees/interface feat/interface`.

---

## 1. Como retomar

1. **Entre no worktree do `feat/interface`** e confira a árvore. O checkout principal fica no `main`, para o laboratório:

   ```bash
   cd .claude/worktrees/interface
   ```

   ```bash
   git merge main
   ```

   O merge traz o motor e o firmware novos do laboratório; faça-o no começo de cada sessão.

   ```bash
   git status --short
   ```

   ```bash
   git log --oneline -10
   ```

   Se `git status` mostrar mudanças, a última sessão parou no meio de um passo: leia a última entrada do diário (seção 7) antes de mexer.
2. **Confira que está tudo verde:**

   ```bash
   scripts/ci.sh interface
   ```

   ```bash
   scripts/ci.sh rapido
   ```

3. **Leia a "Próxima tarefa"** acima e a descrição dela na seção 4: os arquivos, o "pronto quando" e os testes.
4. **Trabalhe em passos pequenos.** A cada passo:
   1. os testes do passo;
   2. o `scripts/ci.sh rapido`;
   3. um commit;
   4. este arquivo atualizado (o estado da tarefa e o diário).

**As regras do trabalho:**

- **Um commit a cada passo de implementação, sem perguntar. Nunca `git push`** até o dono do projeto pedir.
- **Commits em português, sem atribuição a ferramentas** (nada de `Co-Authored-By`).
- **Mudanças no motor** (`scripts/supraharmonicos/`) **e no firmware** (`firmware/`) vão em commits só delas (plano, seção 17).
- **O branch `feat/GUI`** (a GUI de um colega) **é ignorado:** nada dele, nem como referência.
- **Nomes e comentários em português**, como no resto do projeto.
- **Se for preciso parar no meio de um passo:** um commit `Em andamento: <tarefa>: <o que falta>` e uma linha no diário dizendo onde parou. Assim nada se perde se a sessão acabar.

---

## 2. Decisões tomadas

| Data | Decisão | Onde está |
|---|---|---|
| 12/11/2026 | A GUI é feita do zero, no `feat/interface`; o `feat/GUI` é ignorado e será apagado quando o colega sair | Plano, 17 |
| 12/11/2026 | Plataforma: PySide6 (≥ 6.8) com Qt Widgets e um sistema de design próprio | Plano, 5 |
| 12/11/2026 | Motor de gráficos: pirâmide mín/máx (M4) em disco + o item `TracoLOD` sobre o PyQtGraph (banda densa como polígono, linha de 1 px de perto); Matplotlib só na exportação | Plano, 6 |
| 12/11/2026 | **Layout unificado:** o A1 (Estúdio) como a estrutura, com o modo Instrumento (A2) e a grade de vistas (A3) dentro dele; na Aquisição, o B1 com o B2 como a seção "Capturar"; o F1 para as figuras | Plano, 13 |
| 12/11/2026 | Versões: v0.9 Análise; v0.10 Aquisição; v0.11 Figuras; v1.0 manutenção da placa e acabamento | Plano, 16 |
| 12/11/2026 | Commits locais a cada passo, sem push | Seção 1 |

---

## 3. O estado atual

**Feito, em commits locais no `feat/interface`:**

| Commit | O quê |
|---|---|
| `d565596` | O extra `gui` com o PySide6 e o PyQtGraph (o `gui-dev` com o pytest-qt); o pacote `scripts/sh_analyzer_gui/` com a janela vazia e o ícone; os testes do esqueleto, do motor sem Qt e do ícone |
| `49ac048` | O job `interface` da CI (`scripts/ci.sh interface`) |
| `e9f1468` | A primeira versão do plano |
| `e1d4887` | `scripts/benchmarks/plotagem_gui.py`: as medidas do motor de gráficos |
| `e21ba9d` | Os mockups em `docs/gui-mockups/` e as imagens em `docs/images/gui/` |
| `a029674` | O plano reescrito |
| `69347f0` | `scripts/benchmarks/paleta_cores.py`: a conferência das cores |
| `03c219f` | A escolha do layout no plano e este arquivo |

**O ambiente conferido nesta máquina (Linux):** Python 3.13, PySide6 6.12.0, PyQtGraph 0.14.0, Matplotlib 3.11.2, NumPy 2.5.4 e SciPy 1.18.1. Testes: `ci.sh rapido` com 915 aprovados e 2 pulados; `ci.sh interface` verde.

**Ainda não existe:** nenhuma tela além da janela vazia, a `api` do motor, o `sh_placa` e o agente da placa.

---

## 4. Fase 0 em tarefas

Os estados são ☐ a fazer, ▶ a próxima, ◐ em parte e ☑ feita. Cada tarefa cabe em uma ou duas sessões e termina com os testes passando.

### ☑ F0.1: as decisões e este arquivo

O layout escolhido no plano, a conferência das cores em `scripts/benchmarks/paleta_cores.py` e este arquivo de andamento.

### ☐ F0.2: os dados da placa para a Aquisição (no laboratório, opcional)

- **Objetivo:** confirmar na placa real o que o plano supõe:
  - o Python 3 para o agente;
  - os overlays e o `uEnv.txt`;
  - o gadget USB e o mDNS;
  - a vazão do SSH.
- **Como:** os comandos da seção 6. O resultado vai para a tabela de lá.
- **Pronto quando:** a tabela da seção 6 está preenchida, ou a tarefa fica para outra ida ao laboratório, sem prejuízo para as próximas.

### ☑ F0.3: a pirâmide mín/máx

- **Arquivos:**
  - `scripts/sh_analyzer_gui/dados/__init__.py`;
  - `scripts/sh_analyzer_gui/dados/piramide.py`;
  - `tests/test_gui_piramide.py`.

  O subpacote `dados` **não importa o Qt**, e o teste de arquitetura confere isso.
- **A fonte das amostras:** o memmap do `.bin`, com o cabeçalho lido pelo `supraharmonicos.cabecalho`. Cada canal é uma visão com passo (*stride*) dentro das amostras intercaladas: com N canais, a amostra `i` é do canal `lista_canais[i % N]`. Também `.h5` e vetores NumPy, para os testes e as fontes derivadas.
- **Os níveis** são os do benchmark:
  - o nível 0 guarda o mín e o máx de blocos de 32 amostras;
  - cada nível seguinte agrupa 8 blocos do anterior;
  - os níveis param quando sobram menos de 16 blocos;
  - o último bloco incompleto entra com o que tiver.
- **O tipo:** o mesmo da captura.
  - **No `uint16` em binário com deslocamento** (o formato do ADS8688), a ordem dos códigos é a mesma dos valores com sinal. Por isso o mín e o máx dos códigos crus valem.
  - **A conversão para volts** é afim e fica para a hora da consulta.
- **A construção:**
  - em blocos de ~32 M amostras, sem carregar a captura;
  - com um retorno de progresso (`progresso(fracao)`) e um cancelamento (`cancelado() -> bool`);
  - sem Qt e sem threads (quem chama decide onde roda).
- **O cache:**
  - **a pasta:** `platformdirs.user_cache_dir("sh-analyzer")/piramides/`;
  - **o nome:** a chave + o canal + a versão do formato da pirâmide;
  - **a chave:** o `crc32_amostras` do cabeçalho v9, ou o tamanho + a data de modificação + o caminho nas versões anteriores;
  - **a gravação é atômica:** num arquivo temporário, renomeado no fim; um arquivo pela metade nunca é lido.
  - O `platformdirs` (MIT) entrou no extra `gui`.
- **Testes:**
  - dados aleatórios com extremos nas bordas dos blocos, comprimentos que não são múltiplos de 32, 1 e 3 canais intercalados, `uint16` e `int16`: cada nível é igual ao mín e máx calculados à força bruta;
  - o cancelamento para no meio e não deixa cache;
  - reabrir pelo cache dá o mesmo.
- **Pronto quando:** os testes passam, e a construção numa captura sintética de 100 M amostras roda a ≥ 200 M amostras/s nesta máquina.
- **Feito em 13/11/2026:**
  - `dados/piramide.py`: `construir(amostras, n_canais)` faz as pirâmides de todos os canais numa passada só pelo arquivo;
  - `dados/cache.py`: o arquivo `.shpir` (cabeçalho JSON + vetores alinhados, aberto em `np.memmap`), a gravação atômica, a `chave_do_arquivo` e o `CacheDePiramides`, com limite de tamanho e a limpeza dos temporários;
  - `tests/test_gui_piramide.py`: 51 testes contra a força bruta, de 1 a 100 003 amostras, `int16`, `uint16` e `float` com `NaN`, de 1 a 8 canais, o memmap de um `.bin`, o progresso, o cancelamento e os arquivos estragados;
  - `tests/test_gui_desempenho.py`: o portão G3, que só roda com `pytest --desempenho` (o marcador e a opção estão no `conftest.py`);
  - `test_arquitetura.py`: a camada `dados` não importa o Qt nem o resto da interface, conferido pelo código e por um processo novo.

### ☑ F0.4: a consulta

- **Arquivos:** `scripts/sh_analyzer_gui/dados/consulta.py` e `tests/test_gui_consulta.py`.
- **A função:** `consultar(piramide, canal, i0, i1, colunas) -> Colunas`. Devolve, por coluna de pixel:
  - a amostra inicial da coluna;
  - o mín e o máx;
  - a primeira e a última amostra (M4).

  Com ≤ 2 amostras por coluna, devolve as amostras cruas (o modo "linha").
- **O nível:** o que dá ~2 blocos por coluna. As bordas da janela que não caem em bordas de bloco são completadas com as amostras cruas, para o mín e o máx serem **exatos**.
- **Testes:** igual à força bruta em janelas aleatórias, em todos os zooms, incluindo uma janela de 1 amostra e a captura inteira.
- **Pronto quando:** os testes passam e a consulta leva < 1 ms com 1 600 colunas.
- **Feito em 13/11/2026**, com duas decisões tomadas ao implementar:
  - **As bordas das colunas são arredondadas para bordas de bloco**, em vez de completadas com amostras cruas:
    - cada amostra continua em exatamente uma coluna, e o mín e o máx de cada coluna são exatos para o que ela cobre;
    - a envoltória devolve as bordas reais (`Envoltoria.bordas`);
    - com ≥ 8 blocos por coluna, a largura varia no máximo 1/8 de pixel;
    - em troca, a consulta não lê nenhuma amostra crua (ler as bordas das 1 600 colunas custaria 1 600 páginas do disco por quadro).
  - **Sem a primeira e a última amostra de cada coluna (o M4 completo):** o polígono da banda não precisa delas, e a exportação refaz a redução das amostras.
  - **Os três regimes:**
    - amostras, até 2 por coluna;
    - envoltória exata das amostras, até 256 por coluna;
    - pirâmide, daí para cima.

    `aplicar_afim` leva os códigos para a unidade física e troca o mín e o máx com a escala negativa.
  - **Os testes:**
    - `tests/test_gui_consulta.py`: 11 testes contra a força bruta, com janelas aleatórias em todos os zooms, as pontas, os canais intercalados em memmap, `NaN` e a pirâmide do cache;
    - o portão de < 1 ms em `test_gui_desempenho.py`, aprovado.

### ☑ F0.5: o `TracoLOD` e o protótipo

- **Arquivos:**
  - `scripts/sh_analyzer_gui/graficos/traco_lod.py`;
  - `scripts/sh_analyzer_gui/prototipos/navegar.py`, aberto com `python -m sh_analyzer_gui.prototipos.navegar ARQUIVO.bin`;
  - `tests/test_gui_traco_lod.py`.
- **O item:** um `QGraphicsObject` dentro do `PlotItem` do PyQtGraph.
  - **De longe:** a banda como polígono preenchido, com contorno de 1 px.
  - **De perto:** a linha das amostras, com 1 px e antialiasing, e os pontos a partir de ~8 px por amostra.
  - **A cada mudança da vista:** uma consulta por quadro, num temporizador de 16 ms com a vista marcada como "suja".
- **O protótipo:** abre uma captura, mostra todos os canais em faixas e mostra os quadros por segundo.
- **Testes (pytest-qt, sem tela):**
  - pintar nos dois regimes;
  - a fidelidade (portão G4): a banda pintada é igual, pixel a pixel, a pintar todos os pontos com uma caneta de 1 px sem antialiasing.
- **Pronto quando:** o protótipo navega a captura sintética de 100 M amostras sem engasgar nesta máquina.
- **Feito em 13/11/2026.** As medidas mudaram o desenho duas vezes:
  1. **O polígono em degraus com contorno** espalhava um pico pela coluna vizinha. O contorno de 1 px vaza meio pixel para cada lado, e o teste G4 pegou.
  2. **O polígono só de preenchimento** passou no G4, mas, no protótipo, o zoom intermediário (a banda de 60 Hz oscilando de coluna para coluna) dava p95 de 150 ms e quadros de até 930 ms. No benchmark com 8 traços, chegou a 16 s num quadro.
  3. **A escolha final: uma linha vertical de 1 px por coluna de pixel**, sem antialiasing (`_segmentos_de_coluna`):
     - os degraus entre colunas ficam ligados, e as colunas finas ganham 1 px;
     - os `NaN` viram buracos;
     - no protótipo, o p95 é de 10 ms com 2 faixas e de 16 ms com 8.
  - **Os arquivos:**
    - `dados/captura.py`: abrir um `.bin` com cabeçalho, com os canais como visões do memmap e os volts no pino do ADC, iguais aos da CLI. É provisório até a `api` da F0.7;
    - `graficos/traco_lod.py`;
    - `prototipos/navegar.py`, com `--sintetico MINUTOS`, `--canais` e `--medir`;
    - na parte `colunas` do `scripts/benchmarks/plotagem_gui.py`: polígono × linhas nos três regimes;
    - os testes `test_gui_traco_lod.py` (9, inclusive o G4), `test_gui_captura.py` (3) e `test_gui_prototipo.py` (2).
  - **Os acessórios do PyQtGraph pesavam mais que os traços:**
    - a grade semitransparente custava ~17 ms por quadro, e o protótipo ficou sem ela;
    - os rótulos com prefixo do SI refaziam o HTML a cada quadro (`enableAutoSIPrefix(False)`);
    - o eixo do tempo repetido em cada faixa (fica só na última);
    - a consulta deixou de usar `np.unique`.

### ◐ F0.6: os portões G1 a G5 (G1, G3 e G4 aprovados; falta o G2 em 4K e o G5 com o disco frio)

- **Arquivos:**
  - `tests/test_gui_desempenho.py`, marcado `desempenho` e fora do conjunto padrão. Registre o marcador no `pyproject.toml`.
  - Um gerador de captura sintética grande (`.bin` v9 com 1 h, 2 canais, 400 kS/s), sobre o `tests/capturas_sinteticas.py`. O arquivo de 2,9 GB vai para a pasta temporária e é reaproveitado.
- **Os portões** estão na seção 6.7 do plano. O G2 (4K a 200 %) e o G5 (disco frio) pedem uma tela de verdade e, para o Windows, uma máquina com Windows: anote aqui o que não deu para medir.
- **Para medir o G1 e o G2:** `uv run --extra gui python -m sh_analyzer_gui.prototipos.navegar --sintetico 60 --canais 8 --medir`, numa tela de verdade (sem `QT_QPA_PLATFORM=offscreen`). Com 8 faixas, sem tela, o p95 está em 16,0 ms, no limite.
- **Feito em 13/11/2026:**
  - **G3:** a pirâmide a ≥ 200 M amostras/s;
  - **G4:** a fidelidade;
  - **G1 sem tela, com 2 faixas:** p95 ≤ 16 ms, num teste marcado `desempenho` (`tests/test_gui_desempenho.py`, que roda com `pytest --desempenho`);
  - as funções do protótipo que o teste usa: `montar_faixas`, `percorrer_zoom` e `resumo_dos_quadros`.
- **G1 na tela do usuário (13/11/2026): aprovado** com 8 faixas, numa captura sintética de 1 h (2,88 GB). A área era de 1 280 × 626 px; a mediana foi de 11,7 ms e o p95, de 14,4 ms.
- **Falta (pede uma tela de verdade):**
  - o G2 (4K a 200 %), pelo comando acima;
  - o G5 (disco frio): reinicie o computador e abra a captura de 1 h no protótipo;
  - o Windows.
- **Se reprovar:**
  1. primeiro, os eixos e a grade próprios (opacos, com o texto em cache), que vêm na Fase 1 de qualquer forma;
  2. depois, o desenho híbrido (o polígono quando a banda é lisa, plano 6.2);
  3. por fim, a GPU (plano 6.7).
- **Pronto quando:** os resultados estão na seção 5 deste arquivo e na 6.7 do plano. Se algum portão falhar, decida o plano B antes de seguir.

### ☑ F0.7: a `api` do motor (commits só do motor)

- **Arquivos:** `scripts/supraharmonicos/api.py`, `contexto.py` (o `resolver_contexto` passa a usar a `api`), `tests/test_api.py` e o `CAMADAS` do `tests/test_arquitetura.py`.
- **As funções:** `abrir_captura` e `sinal_do_canal` (plano, 8.2), com os avisos estruturados.
- **Pronto quando:** os testes de paridade com a CLI passam e toda a suíte continua verde.
- **Feito em 13/11/2026.**
  - **No motor** (o commit `974c58a`, só do motor, pronto para ir ao `main` sozinho):
    - o `resolver_contexto(args)` virou um adaptador de `resolver_contexto_explicito`, que recebe cada flag como parâmetro. A troca foi mecânica, e a suíte inteira continuou verde;
    - o `perfil_para_correcao` saiu do `aplicar_correcao_sondas`;
    - `api.py`: `abrir_captura`, `sinal_do_canal`, `Captura`, `CanalDaCaptura` (com `escala` e `deslocamento`) e os avisos como dados (`capturar_avisos`);
    - `tests/test_api.py`: a paridade com a CLI nos canais, na calibração, nos volts e na correção de sonda.
  - **A diferença deliberada da CLI:** se o perfil de um canal falta, a captura abre mesmo assim, e o problema vai para `CanalDaCaptura.problema_sonda` e para os avisos.
  - **Na interface:**
    - `dados/captura.py` virou `abrir_fonte`, a `api` mais a chave do cache, e o leitor provisório saiu;
    - o protótipo abre as capturas por ela;
    - `test_arquitetura.py` confere que a interface só importa do motor a `supraharmonicos.api`.

### ☑ F0.8: o tema

- **Arquivos:** `scripts/sh_analyzer_gui/tema/tokens.py`, `tema/qss.py`, `tema/icones.py` e `tema/fontes.py`.
- **Os tokens:** os valores de `docs/gui-mockups/tema.css`.
- **A partir deles:**
  - a `QPalette` e o QSS dos dois temas;
  - as fontes Inter e JetBrains Mono em `recursos/fontes/`, com os arquivos de licença OFL;
  - um subconjunto dos ícones do Lucide em `recursos/icones/`, com a licença ISC, recoloridos pelo tema.
- **O teste:** `tests/test_tema.py`, com a conta do `scripts/benchmarks/paleta_cores.py` sobre os tokens.
- **Pronto quando:** a janela vazia troca de tema sem reiniciar e o `test_tema.py` passa.
- **Feito em 13/11/2026:**
  - **sem Qt:**
    - `tema/tokens.py`: os dois temas, a paleta dos traços, a tipografia, os espaços e `cor_do_traco`, em que o 7º traço repete o matiz tracejado;
    - `tema/cores.py`: o contraste WCAG e a separação OKLab com daltonismo simulado;
    - `tests/test_tema.py`: as contas sobre os tokens, e o CSS dos mockups igual aos tokens (uma fonte de verdade só);
    - o `scripts/benchmarks/paleta_cores.py` passou a ler dos tokens;
  - **com Qt:**
    - `tema/aplicar.py`: o `Fusion`, a `QPalette` e o QSS gerados dos tokens. O `Aparencia` tem o sinal `mudou`, para os gráficos e os componentes pintados à mão; `"sistema"` segue o `QStyleHints.colorScheme`, com o escuro quando o sistema não informa;
    - `tema/icones.py`: 49 ícones desenhados para o projeto, os mesmos dos mockups, recoloridos e em cache, em 1x e 2x;
    - `tema/fontes.py`: registra o que estiver em `recursos/fontes/`, cai nas fontes do sistema, e liga os algarismos tabulares;
    - a janela aplica o tema na partida, e o botão sol/lua da barra de status troca o tema sem reiniciar;
    - `tests/test_gui_tema.py`;
  - **uma armadilha evitada:** o QSS não define `font-size`, que passaria por cima do `setFont` de cada widget.
- **As fontes embutidas (13/11/2026):** o usuário baixou e mandou os arquivos.
  - **Inter 4.001**, o arquivo variável do Google Fonts. Os estáticos se registram como "Inter 18pt", "Inter 18pt SemiBold"…; o variável, como "Inter", com todos os pesos, e é menor que quatro estáticos.
  - **JetBrains Mono 2.304**: Regular, Medium e Bold.
  - **As licenças OFL** ficam ao lado, em `recursos/fontes/`.
  - **A lista sem Qt** (`tema/fontes_embutidas.py`): o teste confere que cada arquivo da pasta está nela e tem licença.
  - **A troca de fonte** fica pronta para as configurações: `escolher_fonte` e `familias_disponiveis`.
  - O `.gitattributes` marca `*.ttf` e `*.otf` como binários.
  - **Depois, as opções** (os zips que o usuário baixou, todos do Google Fonts, com arquivos repetidos entre si; conferidos por hash, e a Inter era idêntica à já embutida):
    - **IBM Plex Sans 3.201** e **Atkinson Hyperlegible Next 2.001** (a de acessibilidade) para a interface, nos estáticos dos quatro pesos: o Qt vê os arquivos variáveis delas só com o "Regular";
    - **IBM Plex Mono 2.3** para a mono;
    - ao todo, 3,1 MB de fontes.
- **Falta (Fase 2, GE-05):** guardar nas configurações a escolha do tema e da fonte.

### ☑ F0.9: a galeria de componentes

- **Arquivos:** `scripts/sh_analyzer_gui/componentes/` e `scripts/sh_analyzer_gui/galeria.py`, aberta com `python -m sh_analyzer_gui.galeria`.
- **Os 6 primeiros componentes:**
  - botão (primário, secundário, fantasma, perigo, ícone);
  - campo numérico com unidade e prefixo do SI;
  - seletor segmentado;
  - chip de traço;
  - cartão de medida;
  - toast.
- **Pronto quando:** a galeria mostra os 6 nos dois temas, parecidos com os mockups, com um teste pytest-qt que abre cada um.
- **Feito em 13/11/2026:**
  - `componentes/numeros.py`, sem Qt: lê "2,5k", "2500", "1,2 mV", "1.234,5" e escreve "2,5 kHz", com o prefixo de engenharia e a vírgula decimal. Tem 50 testes;
  - `componentes/basicos.py`:
    - `Botao` com variante e ícone recolorido;
    - `CampoComUnidade`, que marca em vermelho o que não é número ou está fora da faixa, sem perder o valor;
    - `Segmentado`;
    - `CartaoDeMedida`;
  - `componentes/chip.py`: `ChipDeTraco`, pintado, com o progresso. A cor é a posição na paleta, então troca de tom com o tema;
  - `componentes/toast.py`: entra e sai em 200 ms e respeita o movimento reduzido;
  - `galeria.py`, que abre com `python -m sh_analyzer_gui.galeria`;
  - os testes `test_gui_numeros.py` e `test_gui_componentes.py`.
  - **Um bug que os testes pegaram:** ligar `aparencia().mudou` a uma `lambda` deixa a conexão viva depois que o widget morre. A ligação tem de ser a um método, e um teste agora proíbe a `lambda`.

### ☑ F0.10: o `sh_placa`, o agente e o simulador

- **Arquivos:**
  - `firmware/agente/shan_agente.py` (só a biblioteca padrão; as raízes `/sys`, `/proc` e `/boot` configuráveis por variável de ambiente, para os testes);
  - `scripts/sh_placa/` (o cliente que roda o agente e lê o JSON, e o simulador);
  - o extra `placa` no `pyproject.toml`;
  - `tests/test_agente.py` e `tests/test_sh_placa.py`.
- **Os comandos:** só `versao` e `estado`, por enquanto (plano, 11.2). O `ci.sh` do firmware passa a conferir o agente.
- **Pronto quando:** o agente responde sobre uma árvore falsa, e o simulador responde os mesmos dois comandos.
- **Feito em 13/11/2026:**
  - **`firmware/agente/shan_agente.py`**, que só lê, com os comandos `versao` e `estado` em JSON, `"protocolo": 1`:
    - responde a placa (a EEPROM, como o `ler_adc`), o sistema, o kernel, o tempo ligada, a carga, a memória, a temperatura, o disco, o relógio e o NTP;
    - responde também a PRU0 (o remoteproc), os pinos P9_28 a P9_31, o `mem=496M`, o firmware (`VERSAO`, compilado ou não) e as capturas;
    - o que falta vira `null`;
    - só usa a biblioteca padrão; a sintaxe é conferida para o Python 3.7 e ele roda de verdade no 3.8;
    - `SHAN_RAIZ` e `SHAN_PASTA` trocam a raiz do sistema e a pasta do firmware.
  - **`scripts/sh_placa/`**, sem Qt:
    - `agente.py`: o `ClienteDoAgente`, que confere o JSON, o protocolo e o erro, e o `TransporteLocal`. O SSH entra na Fase 3, com a mesma interface;
    - `estado.py`: o `EstadoDaPlaca.diagnostico()`, com o nível, o código, o texto e a correção de cada problema;
    - `simulador.py`: um sistema de arquivos falso de BeagleBone, em 6 cenários, em que o **agente de verdade** roda.
  - **Testes:** `test_agente.py` (sobre a raiz falsa) e `test_sh_placa.py` (o diagnóstico de cada cenário e as respostas estranhas). A arquitetura confere que o `sh_placa` não importa o Qt nem a interface, e o `ci.sh` roda o ruff no agente.
  - **O extra `placa`** (asyncssh, zeroconf…) fica para a Fase 3, quando o SSH entrar: hoje não há dependência nova.

### ◐ F0.11: o instalador de teste (o Linux feito; falta o Windows)

- **O quê:** um PyInstaller em pasta, com o PySide6, o PyQtGraph e o SciPy. Primeiro no Linux; no Windows quando houver uma máquina.
- **Pronto quando:** o tamanho e o tempo de abrir estão anotados na seção 5.
- **Feito no Linux em 13/11/2026:**
  - **A receita:** `empacotamento/sh-analyzer-gui.spec`, com `empacotamento/entrada.py`;
  - **o conteúdo:** a interface inteira, o `sh_placa` e a `api` do motor, sem os módulos do Qt que não se usam;
  - **a construção:** leva 52 s;
  - **a pasta:** 382 MB, 128 MB compactada em zstd e 150 MB em gzip;
  - **a partida:** 0,36 s, com 81 MB de memória, sem tela, pela opção `--sair-ao-abrir`;
  - **a linha de comando do aplicativo** ganhou `--help`, `--versao` e `--tema`.
- **Para cortar depois:** as duas cópias do OpenBLAS (48 MB) e o Qt Quick, o Qml e o Pdf (21 MB), que entraram apesar das exclusões.
- **Falta:** o Windows, com o `.ico` da marca e o Inno Setup, quando houver uma máquina com Windows.

### ☑ F0.12: o fechamento da Fase 0

- Os resultados dos portões no plano.
- O plano B decidido, se for preciso.
- A Fase 1 quebrada em tarefas, nesta seção, no mesmo formato.
- **Feito em 13/11/2026:**
  - **os portões:** G1, G3 e G4 aprovados (seção 6.7 do plano). O G2 (4K), o G5 (disco frio) e o Windows ficam a medir, e não bloqueiam a Fase 1;
  - **o plano B da GPU:** não é necessário por ora;
  - **a Fase 1:** quebrada em tarefas logo abaixo, na seção 4b.

---

## 4b. Fase 1 em tarefas: o visualizador

**Pronto quando:** a captura de 1 h abre, navega a 60 q/s e mede, com 8 traços de 2 fontes.

### ☑ F1.1: a janela do Estúdio (A1)

**Feito** (`808a0bf`): `janela.py` reescrita; `componentes/barra_superior.py` e `componentes/painel.py` (o título do
painel, o estado vazio, as abas com contador); `configuracao.py` (o INI, com a pasta trocada por
`SH_ANALYZER_CONFIG`) e `preferencias.py` (o tema e as fontes gravados). Os testes em `tests/test_gui_janela.py`.
**Para lembrar:** o `QDockWidget` reserva a altura do título pelo `sizeHint`; a ação de recolher um dock só fica
habilitada se ele for "fechável"; nada de `lambda` que segure um objeto do Qt num sinal que pode sair durante a
destruição da janela (o erro aparece no teste seguinte).

- **Arquivos:** `janela.py` reescrita e `componentes/` (a barra superior).
- **A estrutura:**
  - a **barra superior**: a marca, o projeto, as três áreas num `Segmentado` (a Figuras e a Aquisição ainda desabilitadas), o campo da paleta de comandos, o chip da placa, desfazer e refazer, o tema e as configurações;
  - os **docks:** o Projeto à esquerda e o Inspetor à direita;
  - as **vistas** no centro, em abas;
  - o **painel de baixo**, com as Medidas, as Tarefas e os Avisos;
  - a barra de status.
- **O layout:** salvo e restaurado (`saveState`/`restoreState`, por enquanto no `QSettings`; por projeto na F1.3). Ctrl+B, Ctrl+I e Ctrl+J recolhem os painéis.
- **Os testes:** a janela abre com cada região, recolhe os painéis e guarda o layout. O `QSettings` dos testes vai para uma pasta temporária, nunca a do usuário.

### ☑ F1.2: o modelo e o desfazer

**Feito** (`8d9b719`): `dados/receita.py` (a `ReceitaDoTraco`, sem Qt) e `modelo/` (`objetos.py`, `selecao.py`,
`comandos.py`); a janela com o projeto num `QUndoGroup`. Os testes em `test_gui_receita.py` e `test_gui_modelo.py`.
**Para lembrar:** nada de `QUndoCommand(parent=...)` (o Python não segura o filho; o processo caiu num teste em
paralelo); um comando de vários passos os guarda ele mesmo. Os repasses de sinal são de sinal para sinal.

- **Arquivos:** `modelo/`: `Projeto`, `Fonte`, `Vista`, `Traco`, com sinais do Qt, e os comandos (`QUndoCommand`).
- **O conteúdo:**
  - adicionar e remover um traço, e mudar uma propriedade, cada um como um comando;
  - o `QUndoStack` na janela;
  - o estado do traço: a fonte, o canal, a posição na paleta (a cor), a escala e o deslocamento, a visibilidade e a faixa.
- **Os testes:** cada comando faz e desfaz, e o modelo avisa quem desenha.

### ☑ F1.3: o projeto `.shproj`

**Feito** (`a604e16`): `dados/projeto.py` (sem Qt), `modelo/persistencia.py`, `controle_do_projeto.py` e
`componentes/avisos.py`. Os testes em `test_gui_projeto.py` e `test_gui_controle_projeto.py`.
**Para lembrar:** os diálogos passam por `controle.dialogos` (nos testes, `tests/dialogos_falsos.py`); sem tela, um
diálogo não previsto levanta `DialogoSemTela`. O pytest-qt fecha as janelas do `qtbot.addWidget` **antes** da limpeza
das fixtures: uma janela que pode terminar o teste com mudanças é fechada pela própria fixture, depois do
`setClean()`. Uma captura ausente é uma `FonteDoProjeto` com `fonte=None` e a `origem` do arquivo.

- **Arquivos:** `dados/projeto.py` (sem Qt), com o JSON versionado (`"formato": "sh-analyzer-projeto"`).
- **O conteúdo:**
  - as fontes, por caminho relativo e pelo CRC;
  - salvar, abrir e reencontrar uma fonte movida pelo CRC;
  - o salvamento automático (`.shproj~`) e a recuperação depois de uma queda.
- **Os testes:** ida e volta, um formato futuro recusado com a mensagem, e a recuperação.

### ☑ F1.4: abrir capturas e o painel Projeto

**Feito** (`e76684b`, só do motor: `api.conferir_integridade` e `api.descrever_cabecalho`; `84e4fa9`, a interface):
`servicos/` (as tarefas e o preparo de cada captura), `areas/analise/` (`arvore.py`, `inspetor.py`, `area.py`) e
`componentes/tarefas.py`. Os testes em `test_gui_abrir_capturas.py`. Conferido com as capturas do laboratório de
13/11 (`FIG_2026-11-13`): abrem, a pirâmide sai, o CRC confere.
**Para lembrar:** quem segue um sinal do projeto **depois** da árvore precisa ser ligado depois dela (a ordem das
conexões é a ordem das chamadas). **Não rode `uv run` com outro extra enquanto a CI roda em segundo plano:** o `uv`
reinstala o ambiente compartilhado no meio, e um teste que abre um subprocesso falha sem motivo.

- **O conteúdo:**
  - abrir por diálogo, arrastando e soltando, e pelos recentes;
  - a árvore das fontes e dos canais (um `QAbstractItemModel`), com o ponto da cor onde o canal está plotado;
  - a vista do cabeçalho, com o CRC conferido;
  - os avisos da `api` no painel de avisos;
  - a construção da pirâmide em segundo plano (um `QRunnable`), com o progresso e o cancelamento.
- **Os testes:** abrir uma captura sintética, a árvore e o cancelamento.

### ▶ F1.5: a vista de tempo

- **O conteúdo:**
  - as faixas, uma `ViewBox` por grandeza, com o tempo ligado entre elas, e o `TracoLOD`;
  - **o eixo e a grade próprios**, opacos e com o texto em cache: o que sobrava do G1 com 8 faixas;
  - o zoom e o pan com o histórico (Backspace), o minimapa e a legenda de chips;
  - a seleção: clicar perto do traço, no chip ou na árvore.
- **Os testes:** o G4 de novo, a seleção e o histórico; o G1 medido de novo com 8 faixas.

### ☐ F1.6: o inspetor do traço

- **O conteúdo:** a identidade, a aparência (a cor da paleta), e a escala e o tempo, cada mudança como um comando de desfazer.
- **Os testes:** editar, desfazer e editar vários traços de uma vez.

### ☐ F1.7: os cursores e as medidas

- **O conteúdo:**
  - dois cursores, com Δt, 1/Δt e Δy;
  - as medidas da região (média, RMS, pico, pico a pico, f₁), calculadas das amostras pela `api` (`sinal_do_canal`), nunca do desenho;
  - a tabela de medidas, que copia para a planilha.
- **Os testes:** os números iguais aos da CLI para a mesma região.

### ☐ F1.8: a paleta de comandos e os atalhos

- **O conteúdo:** Ctrl+K com busca por nome em todas as ações, e a lista dos atalhos.
- **Os testes:** achar e rodar uma ação pela paleta.

---

## 5. Resultados medidos

| Data | O quê | Resultado | Onde |
|---|---|---|---|
| 12/11/2026 | Pirâmide: construção e consulta (100 M amostras) | 308 a 315 M amostras/s; consulta 0,12 a 0,14 ms; +7,1 % de espaço | `plotagem_gui.py piramide` |
| 12/11/2026 | Banda cheia, 8 traços: linha × polígono | 60 a 67 ms × 10,9 a 11,7 ms por quadro | `plotagem_gui.py banda espessura` |
| 12/11/2026 | Cores: contraste e daltonismo, nos dois temas | Tudo aprovado | `paleta_cores.py` |
| 13/11/2026 | G3: a pirâmide de 100 M amostras `int16` em memmap (`dados/piramide.py`) | Aprovado (≥ 200 M amostras/s) | `pytest --desempenho tests/test_gui_desempenho.py` |
| 13/11/2026 | A consulta de 1 600 colunas, da captura inteira (100 M) até 5 000 amostras | Aprovado (< 1 ms) | idem |
| 13/11/2026 | G4: fidelidade do `TracoLOD` (extremos por coluna de pixel, ±1 px; nada inventado; colunas nos pixels) | Aprovado, em 3 zooms | `tests/test_gui_traco_lod.py` |
| 13/11/2026 | G1 sem tela, 1 400 × 790 px, zoom e pan da captura inteira até 50 amostras: **2 faixas** | Aprovado: mediana de 6,1 ms, p95 de 10,2 ms | `navegar --sintetico 10 --canais 2 --medir` |
| 13/11/2026 | G1 sem tela, mesmo percurso: **8 faixas** | **No limite:** mediana de 12,7 ms, p95 de 16,0 ms. Os traços custam ~1,5 ms; o resto são os eixos e as caixas de vista do PyQtGraph | `navegar --sintetico 10 --canais 8 --medir` |
| 13/11/2026 | **G1 na tela do usuário: 8 faixas**, captura sintética de 1 h (2,88 GB), 1 280 × 626 px | **Aprovado:** mediana de 11,7 ms, p95 de 14,4 ms | `navegar --sintetico 60 --canais 8 --medir` |
| 13/11/2026 | Instalador do PyInstaller no Linux (a interface, o `sh_placa` e a `api` do motor) | Pasta de 382 MB (128 MB em zstd, 150 MB em gzip); construção em 52 s; partida em 0,36 s com 81 MB | `empacotamento/sh-analyzer-gui.spec` |
| 13/11/2026 | 8 traços sobrepostos, 1 600 × 900 px: polígono × linha por coluna | Banda cheia: 6,3 × 29,3 ms; banda oscilante: **16 366** × 19,0 ms; ciclos: 4,4 × 3,2 ms | `plotagem_gui.py colunas` |

---

## 6. Os dados da placa para a Aquisição (F0.2)

**Com a placa conectada e o `lab` aberto** (as variáveis `DIA` e `SH_ANALYZER` existem), cada comando grava a resposta na pasta do dia. Nenhum muda nada na placa nem no computador.

**Na placa** (pelo `BeagleBone_Setup.sh ssh`):

```bash
scripts/BeagleBone_Setup.sh ssh 'python3 --version; uname -r; head -1 /etc/dogtag; cat /proc/cmdline; grep -E "^[^#]*(overlay|cape|cmdline)" /boot/uEnv.txt; ls /proc/device-tree/chosen/overlays 2>/dev/null; ls /lib/firmware | grep -i -E "pru|rproc"; for c in config-pin dtc avahi-daemon setsid systemd-run; do command -v $c || echo "sem $c"; done' > "$DIA/placa_para_gui.txt" 2>&1
```

**No computador** (o gadget USB, os IPs e o mDNS):

```bash
lsusb > "$DIA/usb_para_gui.txt"; ip -brief addr >> "$DIA/usb_para_gui.txt"; getent hosts beaglebone.local >> "$DIA/usb_para_gui.txt"
```

**A vazão:** quando trouxer uma captura grande, anote o tamanho e o tempo. Se usar o `lab trazer`, ponha `time` na frente.

Depois, preencha a tabela (ou peça para preencher a partir dos arquivos `placa_para_gui.txt` e `usb_para_gui.txt`):

| Item | O que o plano supõe | Na placa |
|---|---|---|
| Python 3 na placa | Existe (o agente usa só a biblioteca padrão) | |
| Kernel e imagem | Debian da BeagleBoard, kernel 5.10-ti ou parecido | |
| `mem=496M` na linha do kernel | Sim | |
| Overlays carregados | O de PRU remoteproc; o de áudio do HDMI desligado ou o cape universal | |
| `.dtbo` de PRU em `/lib/firmware` | Algum `*PRU-RPROC*` | |
| `config-pin`, `dtc`, `avahi-daemon`, `setsid`, `systemd-run` | Existem | |
| O gadget USB no `lsusb` | Um dispositivo da BeagleBone (anote o VID:PID) | |
| A interface de rede do USB no computador | 192.168.6.x ou 192.168.7.x | |
| `beaglebone.local` resolve | Sim, pelo mDNS | |
| Vazão do `scp` de uma captura grande | ~10 MB/s | |
| (Se houver um Windows no laboratório) a placa aparece como rede no USB | Sim (RNDIS) | |

---

## 7. Diário

Uma entrada por sessão, a mais nova no fim: o que foi feito, onde parou e o que vem depois.

- **12/11/2026:**
  - **Feito:** o plano reescrito, as medidas do motor de gráficos, os mockups, o layout unificado (A1 + B1, com o A2, o A3 e o B2 dentro deles), a conferência das cores e este arquivo.
  - **Parado em:** nada em andamento.
  - **Próximo:** a F0.2 no laboratório, se houver tempo; depois, a F0.3.
  - **Observado, fora da GUI:** o `tests/test_ler_adc_captura.py::test_amostras_atrasadas_e_ruido_no_sdo_vao_para_o_cabecalho_com_aviso` falhou uma vez no `ci.sh rapido` com a máquina carregada (15 amostras atrasadas em vez de 10) e passou 3 vezes isolado. Parece instável: a PRU falsa publicaria os contadores de uma troca de buffer a mais antes de parar. Não foi mexido.
- **13/11/2026:**
  - **Feito:**
    - o worktree `.claude/worktrees/interface`, com o `main` do laboratório trazido para o `feat/interface` (merge sem conflito);
    - a F0.3, a pirâmide e o cache (seção 4);
    - a F0.4, a consulta;
    - a F0.5, o `TracoLOD`, o protótipo e as medidas que trocaram o desenho da banda (seção 4);
    - o extra `gui` passou a pedir `pyqtgraph>=0.14` e `platformdirs>=4`.
  - **Parado em:** nada em andamento.
    - a parte automática da F0.6: o G1 sem tela, com 2 faixas, num teste de desempenho;
    - a F0.7: a `api` do motor (um commit só do motor) e a interface abrindo as capturas por ela;
    - a F0.8, o tema, menos as fontes embutidas;
    - a F0.9, os 6 componentes e a galeria;
    - as fontes opcionais (IBM Plex Sans e Mono, Atkinson Hyperlegible Next), tiradas de zips com arquivos repetidos;
    - a F0.10: o agente da placa, o `sh_placa` e o simulador.
  - **Depois, no mesmo dia:**
    - o G1 medido na tela do usuário, aprovado com 8 faixas;
    - as fontes Inter e JetBrains Mono embutidas, com os arquivos que ele baixou.
    - a F0.11 no Linux: o PyInstaller, com a pasta de 382 MB (128 MB compactada) e a partida em 0,36 s. O app ganhou `--help`, `--versao` e `--tema`; um `--help` sem tratamento tinha aberto uma janela na tela do usuário;
    - a F0.12: a Fase 0 fechada e a Fase 1 quebrada em tarefas (seção 4b).
  - **Próximo:** a F1.1, a janela do Estúdio.
- **13/11/2026 (tarde):** a F1.1, a janela do Estúdio, com o layout salvo, Ctrl+B/I/J, o menu de ajustes (tema e
  fontes gravados) e a barra compacta abaixo de 1200 px. Os testes da interface usam uma pasta de configuração
  temporária (`SH_ANALYZER_CONFIG`, no `conftest.py`). Dados de laboratório para testar e fotografar:
  `~/Documents/sh-analyzer-data/lab/2026-11-13/FIG_2026-11-13/` (60 Hz com tom de 20 kHz ou 130 kHz, tensão e
  corrente; pequenos, 25 MB cada). **Próximo:** a F1.2.
- **13/11/2026 (tarde):** a F1.2, o modelo e o desfazer. **Próximo:** a F1.3.
- **13/11/2026 (noite):** a F1.3, o projeto `.shproj`, com o salvamento automático e a recuperação. **Próximo:** a
  F1.4.
- **13/11/2026 (noite):** a F1.4, abrir capturas, com a árvore, o inspetor do cabeçalho, as tarefas e o CRC
  conferido. **Próximo:** a F1.5.

---

## 8. Perguntas em aberto

São as do plano, seção 19. Não bloqueiam a Fase 0:

- o tema padrão na primeira execução;
- a ordem das versões (Aquisição antes de Figuras);
- a regra de sudo sem senha na placa;
- o inglês na v1.0;
- a assinatura de código no Windows.
