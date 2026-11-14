# Andamento da interface gráfica

O diário e a lista de tarefas do desenvolvimento da GUI. O **plano** (o quê e por quê) está em [`gui-plan.md`](gui-plan.md); este arquivo diz **onde o trabalho parou e qual é o próximo passo**. Com ele, o trabalho continua igual depois de uma pausa, numa sessão nova ou nas mãos de outra pessoa.

**Atualize este arquivo a cada tarefa concluída e antes de qualquer pausa.**

---

## Próxima tarefa

> **F2.8: os avisos nos chips, o erro inesperado e o log** (seção 4c). A F2.1 a F2.7 estão feitas: a cadeia no
> inspetor, o traço transformado na tela e as quatro vistas de frequência. A F2.8, a F2.9 e a F2.10 são independentes
> entre si.
>
> **Para o usuário ver na tela:** plotar um canal; no inspetor, "Adicionar etapa" (ou Ctrl+K, "passa-altas"); Ctrl+E
> (espectro), Ctrl+Shift+B (bandas IEC), Ctrl+Shift+E (espectrograma), Ctrl+Shift+H (harmônicos).
>
> **Com o usuário (quando puder):** o "pronto quando" da Fase 1, abrir uma captura de 1 h, navegar e medir com 8
> traços de 2 fontes, em `uv run --extra gui python -m sh_analyzer_gui`.
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

**Em 13/11/2026 (noite), no `feat/interface`, em commits locais:** as Fases 0 e 1 no código. O aplicativo abre
capturas (diálogo, arrastar e soltar, recentes), confere o CRC e mostra o cabeçalho, plota os canais em faixas pela
unidade com o `TracoLOD`, navega com o histórico e o minimapa, mede entre os cursores ou na janela visível (os números
da CLI, pela `api`), edita os traços no inspetor (tudo com desfazer), salva e reabre o projeto `.shproj` (com o
salvamento automático e a recuperação) e tem a paleta de comandos. As seções 4 e 4b têm o commit de cada tarefa.

**Os commits só do motor** (podem ir ao `main` sozinhos): `974c58a` (a `api`), `e76684b` (a integridade e o
cabeçalho), `64f6e57` (a unidade do canal), `b5b02ab` (as medidas de um trecho), `71ba268` (a taxa da PRU) e `98d96e0` (a frequência, F2.1), `0ef8255` (os filtros), `28a1a04` (a margem da sonda), `3110417` (`medir_sinal`), `631a770` (a faixa válida do perfil), `b368246` (o piso de ruído) e `8376894` (as bandas sem cancelamento). E o do agente da placa: `3f98d7b`.

**O ambiente:** Python 3.13, PySide6 6.12.0, PyQtGraph 0.14.0, NumPy 2.5.4, SciPy 1.18.1. Testes, na última rodada:
`ci.sh rapido` com 1 465 aprovados e `ci.sh interface` com 538 (14/11/2026).

**Ainda não existe:** a tela de configurações, o log em arquivo, os formatos `.h5` e `.csv` na abertura, as
figuras e a Aquisição.

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

### ☑ F1.5: a vista de tempo

**Feito** (`64f6e57`, só do motor: `CanalDaCaptura.unidade`; `97b7dca`, a interface): `areas/analise/vista_tempo.py`,
`graficos/faixa.py` (o eixo, a grade, a caixa com os gestos), `componentes/fluxo.py` (a legenda que quebra a linha) e
`prototipos/medir_vista.py`. Os testes em `test_gui_vista_tempo.py`; o G1 com 8 faixas em `test_gui_desempenho.py`
(opcional, `--desempenho`).
**O G1 com 8 faixas, sem tela, em 13/11:** não deu para medir: outra sessão estressava a CPU de propósito (carga 16 a
25). Sob essa carga: 8 faixas, mediana 35 ms; 2 faixas, 18 ms. O perfil mostrou dois gastos sem motivo, já tirados: a
grade com o `tickValues` do PyQtGraph (um terço do quadro) e o rótulo em HTML dos eixos escondidos. O que sobra é do
PyQtGraph (os eixos em `QPicture` e os caminhos dos traços). **Se o G1 reprovar na tela:** o eixo próprio, com o
texto em cache (`QStaticText`), é o próximo passo; os chips repintam a cada quadro no percurso de 1 minuto
(1,7 ms), a investigar.
**Para lembrar:** os eixos de cima e da direita de um `PlotItem` existem, escondidos, com o prefixo SI ligado;
desligue-o. Um widget tirado de um layout com `deleteLater` continua na tela até o laço de eventos voltar: esconda e
tire do pai antes (`LayoutDeFluxo.limpar`).

- **O conteúdo:**
  - as faixas, uma `ViewBox` por grandeza, com o tempo ligado entre elas, e o `TracoLOD`;
  - **o eixo e a grade próprios**, opacos e com o texto em cache: o que sobrava do G1 com 8 faixas;
  - o zoom e o pan com o histórico (Backspace), o minimapa e a legenda de chips;
  - a seleção: clicar perto do traço, no chip ou na árvore.
- **Os testes:** o G4 de novo, a seleção e o histórico; o G1 medido de novo com 8 faixas.

### ☑ F1.6: o inspetor do traço

**Feito:** `areas/analise/inspetor_traco.py` (e o `CampoComUnidade` com o estado "vários"); a seleção de traços vai
para o inspetor. Os testes em `test_gui_inspetor_traco.py`.

- **O conteúdo:** a identidade, a aparência (a cor da paleta), e a escala e o tempo, cada mudança como um comando de desfazer.
- **Os testes:** editar, desfazer e editar vários traços de uma vez.

### ☑ F1.7: os cursores e as medidas

**Feito** (`b5b02ab`, só do motor: `api.medir_regiao`, com as contas da CLI): `servicos/medidas.py` (em segundo
plano; vale o pedido mais recente; acima de 20 M amostras, não lê), `areas/analise/medidas.py` (a tabela, que copia
para a planilha com a vírgula decimal) e os cursores na vista (C, as setas). Os testes em `test_gui_medidas.py`.
**Para lembrar:** a f₁ precisa de dois cruzamentos por zero (a regra da CLI): com um ciclo só, fica vazia, com o
motivo na dica. As tarefas com `mostrar=False` não aparecem no painel.

- **O conteúdo:**
  - dois cursores, com Δt, 1/Δt e Δy;
  - as medidas da região (média, RMS, pico, pico a pico, f₁), calculadas das amostras pela `api` (`sinal_do_canal`), nunca do desenho;
  - a tabela de medidas, que copia para a planilha.
- **Os testes:** os números iguais aos da CLI para a mesma região.

### ☑ F1.8: a paleta de comandos e os atalhos

**Feito** (`d616812`): `componentes/paleta.py` (a paleta, com a busca sem acentos, e a lista dos atalhos). Os testes
em `test_gui_paleta.py`. **Para lembrar:** nos testes, mande as teclas por `QApplication.sendEvent`; o `event()`
direto do widget pula os filtros de evento.

- **O conteúdo:** Ctrl+K com busca por nome em todas as ações, e a lista dos atalhos.
- **Os testes:** achar e rodar uma ação pela paleta.

---

## 4c. Fase 2 em tarefas: transformações e frequência

**Pronto quando** (o plano, seção 16): a jornada do pesquisador vai da captura ao espectro corrigido pela sonda, e os
números batem com a CLI. **Tag v0.9.**

**A ordem:** a F2.1 (a `api`) e a F2.2 (a cadeia, sem Qt) vêm primeiro; a F2.3 depende da F2.2; a F2.4, da F2.3; as
vistas de frequência (F2.5 a F2.7) dependem da F2.1 e usam a cadeia da F2.2. A F2.8 a F2.10 são independentes entre
si. A F2.11 fecha.

### ☑ F2.1: a `api` da frequência (commits só do motor)

**Feita em 14/11/2026:** `71ba268` (a taxa da PRU) e `98d96e0` (a frequência), só do motor; `dc03d91` (o `Cancelado`
da pirâmide é o do motor). O que ficou diferente do previsto:

- **As contas recebem o sinal, não a captura:** `espectro(sinal, taxa_hz, ParametrosEspectro(...))`, e o mesmo para
  `espectrograma`, `bandas_iec` e `harmonicos`; `picos(espectro, limiar_db, ...)`. O sinal vem do
  `sinal_do_canal` ou, na F2.2, da cadeia do traço. O Welch, o espectrograma e as bandas leem um memmap um lote por
  vez, com `progresso` e `cancelado` (cancelada, a conta levanta `api.Cancelado`).
- **Além da CLI:** a FFT sem sincronizar (com a Hann), as escalas do `Espectro.niveis` (`db`, `linear`, `rms`,
  `dbc`), os N maiores picos e a sincronização das bandas por outro sinal (`referencia`: a CLI usa a tensão).
- **A taxa do canal** passou a ser a que a PRU gera (clock ÷ ticks), como no `adc_tool`; a `api` usava a pedida (a
  102,4 kHz, 64 ppm de diferença).
- **Os testes** estão em `tests/test_api_frequencia.py`: a paridade com a CLI de verdade, pelo `.mat` (a precisão
  inteira), com `--fft`, `--welch`, `--picos`, `--agrupar-bandas`, `--espectrograma`, `--bandas-iec` (fixas,
  sincronizadas e agregadas) e `--harmonicos`, a 1e-12 relativo.

O plano original:

- **Arquivos:** `supraharmonicos/api.py`; testes em `tests/test_api.py`.
- **O conteúdo:** parâmetros num dataclass imutável e resultado noutro (plano, 8.2), sobre as funções que já existem:
  - `espectro(captura, canal, inicio, fim, parametros)`: FFT e Welch (`espectro.calcular_espectro`,
    `calcular_espectro_welch`), com a janela, a resolução e a escala;
  - `picos(...)`, `espectrograma(...)`, `bandas_iec(...)` e `harmonicos(...)` (`bandas_iec`, `harmonicos`);
  - o progresso e o cancelamento nas contas longas (as bandas e o espectrograma de uma captura inteira).
- **Os testes:** a paridade com a CLI nas capturas sintéticas (`tests/capturas_sinteticas.py`): os mesmos números
  do `adc_tool --fft`, `--welch` e `--bandas-iec` para o mesmo trecho.

### ☑ F2.2: a cadeia de transformações, sem Qt

**Feita em 14/11/2026:** `0ef8255` e `28a1a04` (só do motor: os filtros e a margem da sonda na `api`) e `828ef77`
(a cadeia, a receita e o projeto v2). O que ficou diferente do previsto:

- **Os blocos não fazem duas passadas.** A prévia e os blocos usam um mecanismo só, para a cadeia inteira: cada
  pedaço é lido com a margem da cadeia de cada lado, a cadeia roda nele como num vetor inteiro, e as bordas são
  descartadas (*overlap-save*). A margem de um filtro sai da sua resposta ao impulso (a cauda abaixo de 1e-12); a da
  sonda, do alcance da IFFT de 1/ganho(f) (`api.margem_da_correcao_sonda`, 1e-9 do pico). Não precisa de um arquivo
  intermediário por etapa, e dá o vetor inteiro a 1e-9 relativo com os filtros.
- **A correção de sonda em blocos não dá o vetor inteiro a 1e-9:** a do vetor inteiro é uma FFT circular (perto das
  bordas, ela mistura o começo com o fim), e a resposta ao impulso de 1/ganho(f) decai devagar (a soma da cauda nem
  converge). No miolo, os blocos ficam abaixo de 1e-6 do RMS (4e-7 medidos com a sonda de teste).
- **O "remover o DC"** tira a média do **canal inteiro** (`ContextoDaCadeia.media`), passada pelo ganho em DC das
  etapas de antes; a média do trecho mudaria a cada pan. Quem calcula a média do canal (uma passada pelo memmap) é a
  F2.3; sem ela, a etapa tira a média do trecho.
- **A ordem:** o canal na unidade física, a cadeia, e só no fim o ganho, o offset e o deslocamento do traço (que
  seguem direto na pirâmide). A CLI faz a correção de sonda e depois os filtros; a cadeia segue a ordem do usuário.

O plano original:

- **Arquivos:** `dados/cadeia.py`; a `ReceitaDoTraco` ganha as etapas; o `.shproj` sobe para a versão 2 (e lê a 1).
- **O conteúdo** (plano, 7.2):
  - as etapas, cada uma com a sua classe (afim, com memória) e os parâmetros validados: os filtros (passa-baixas,
    passa-altas, passa-faixa, rejeita-faixa; Butterworth primeiro), remover o DC e a correção de sonda
    (`aplicar_correcao_sonda`, automática pelo cabeçalho ou escolhida);
  - a **prévia**: a janela visível com a margem de acomodação de cada etapa, descartada nas bordas;
  - a **fase zero em blocos** (duas passadas, o estado levado de um bloco ao outro) e a **correção de sonda em
    blocos** (sobreposição e soma).
- **Os testes:** a paridade em blocos com o vetor inteiro (o `sosfiltfilt` e o `aplicar_correcao_sonda`, a 1e-9
  relativo); cada etapa inválida recusada com a mensagem; a ida e volta pelo projeto, e o projeto v1 aberto.

### ☑ F2.3: a materialização e o cache

**Feita em 14/11/2026:** `3d7ffda` (sem Qt: a materialização, o cache e a média do canal), `3110417` (só do motor:
`api.medir_sinal`) e `263e25e` (o serviço, a vista de tempo e as medidas). As decisões:

- **O cache guarda `float32`:** o arredondamento fica 256 vezes abaixo de um LSB do ADC no fundo de escala (e é
  relativo: um valor pequeno depois de um passa-altas guarda a mesma precisão). As contas de um trecho (as medidas)
  refazem a cadeia em `float64` das amostras do ADC.
- **A chave é o conteúdo:** a captura (o CRC), o canal, a taxa, as etapas **ligadas**, o conteúdo de cada perfil de
  sonda e a média do canal (se a cadeia remove o DC). A pirâmide, gravada por último e de forma atômica, é a marca de
  pronto; as amostras vão direto para o arquivo final (no Windows, um arquivo mapeado não se renomeia).
- **O que a tela mostra de um traço com cadeia, nesta ordem:** a materialização pronta; o começo já materializado,
  se ele cobre a janela; a prévia da janela (até 1 M amostras); o começo já materializado; nada. **Nunca o canal cru
  no lugar do transformado.** O traço se preenche da esquerda para a direita enquanto a materialização roda.
- **A prévia** tem uma thread só dela (uma materialização longa não a deixa na fila) e sai 60 ms depois da última
  mudança do zoom ou do pan, com um quarto de janela de folga de cada lado. Medido: ~110 ns por amostra com a sonda e
  dois filtros (1 s de janela a 200 kS/s em ~115 ms); a materialização anda a ~8 M amostras/s (5 min de captura em
  ~8 s; 1 h em ~90 s).
- **As medidas** de um traço com cadeia são as do sinal transformado (a cadeia na região com a margem).
- **Fica para a F2.9:** o limite do cache e o "limpar" na tela de configurações (o `CacheDeMaterializacoes` já os
  tem).

O plano original:

- **Arquivos:** `servicos/materializar.py`; o cache em `dados/cache.py`.
- **O conteúdo:**
  - a captura inteira transformada em segundo plano, em blocos, gravada com a sua pirâmide;
  - o cache endereçado pelo conteúdo (o CRC da fonte, o canal e a receita): duas vistas com a mesma receita dividem
    o arquivo; o limite de tamanho (LRU) e o "limpar";
  - o `TracoLOD` mostra a prévia enquanto a materialização roda, e troca para ela quando fica pronta.
- **Os testes:** o traço materializado igual ao do motor sobre o vetor inteiro; cancelar no meio; o cache
  reaproveitado e o limite respeitado; a prévia em menos de 200 ms (plano, 7.2).

### ☑ F2.4: a cadeia no inspetor e nos chips

**Feita em 14/11/2026:** `631a770` (só do motor: `PerfilSonda.faixa_valida`) e `c510dec` (a seção Processamento e a
Calibração). As decisões:

- **A reordenação é por setas** (▲ ▼ em cada cartão), e não por arrastar: dá para fazer pelo teclado e testar.
  "Adicionar etapa" é um menu de 6 itens; a busca fica com a paleta de comandos (Ctrl+K: "Adicionar etapa:
  passa-altas"), que acha as ações quando um traço está no inspetor.
- **Os padrões das etapas novas:** a correção de sonda entra no começo da cadeia (é onde a sonda age, e é a ordem da
  CLI); o passa-altas em 2 kHz; o passa-baixas em 80 % da Nyquist (até 150 kHz); o rejeita-faixa em 45 a 65 Hz.
- **A correção de sonda não entra sozinha** num traço novo (ela custa uma materialização): a seção Calibração diz que
  o perfil existe e não está na cadeia, com o botão "Aplicar a correção de sonda".
- **Fica para a F2.5:** a faixa válida do perfil sombreada no gráfico. Ela é de frequência, e o lugar dela é a vista
  de espectro; a seção Calibração já a mostra em texto.

O plano original:

- **O conteúdo:**
  - a seção **Processamento** do inspetor (plano, 9.4): um cartão por etapa (ligar e desligar, reordenar, abrir os
    parâmetros) e "Adicionar etapa" com um menu buscável; cada mudança, um comando de desfazer;
  - o resumo no chip (`sonda · −DC`) e o progresso da materialização;
  - a seção **Calibração**: o perfil de sonda, a faixa válida (sombreada no gráfico) e os avisos da conferência.
- **Os testes:** adicionar, mudar, reordenar e desligar uma etapa, e desfazer cada passo; a faixa válida no gráfico.

### ☑ F2.5: a vista de espectro

**Feita em 14/11/2026:** `b368246` (só do motor: o piso de ruído), `e0ff797` (sem Qt: as opções e a conta) e
`16f5478` (a vista). As decisões:

- **O espectro segue uma vista de tempo:** os traços visíveis dela, cada um com a sua cadeia. Mudar a cadeia lá muda o
  espectro aqui, e os números nunca divergem do traço da tela. A vista de espectro não tem traços próprios nesta
  versão (o plano, 7.1, admite; fica para quando houver um caso).
- **Sem cadeia, o Welch roda nos códigos do ADC** (lote a lote: a captura inteira não vai para a memória) e sobe
  `20·log10|escala|`, com o piso do motor: o número é o do Welch sobre os volts a 1e-9 dB. A FFT vai até 16 M
  amostras (ela é um segmento só, na memória).
- **Com cadeia, o trecho é o do traço transformado** (com a margem, em `float64`), até 8 M amostras; acima, a
  materialização. **Diferença deliberada da CLI:** o `adc_tool` filtra só o trecho, com o transitório do filtro nas
  bordas; aqui não há transitório. Sem cadeia, os números são os da CLI.
- **Os harmônicos de f₁ só com a FFT sincronizada:** o Welch de 200 Hz não separa harmônicos de 50 Hz.
- **Os picos:** os 5 mais altos acima do piso de ruído + 10 dB (o piso é a mediana dos bins de 2 kHz à Nyquist).
- **Fica para a F2.7:** as medidas do espectro (o THD e os grupos), com os harmônicos.

O plano original:

- **Arquivos:** `areas/analise/vista_espectro.py`; o tipo `"espectro"` no projeto.
- **O conteúdo** (ES-01, ES-02):
  - FFT e Welch de cada traço, com a cadeia dele, sobre um trecho: a região dos cursores, a janela visível da vista
    de tempo ligada ou a captura inteira;
  - a escala (dBV, dBc, V RMS), a frequência linear ou logarítmica, e a faixa de 2 a 150 kHz sombreada;
  - os picos marcados, os harmônicos de f₁ e o piso de ruído;
  - as contas em segundo plano (vale o pedido mais recente), o cursor de frequência e as medidas.
- **Os testes:** os números da vista iguais aos da `api` (e esta, aos da CLI); trocar a escala e o trecho.

### ☑ F2.6: as bandas IEC e o espectrograma

**Feita em 14/11/2026:** `8376894` (só do motor: a soma de cada banda sem cancelamento), o commit sem Qt das contas e
`f525189` (as duas vistas). As decisões:

- **Um achado de precisão no motor:** as bandas saíam da diferença de uma soma acumulada da potência, que carrega a
  fundamental; uma banda fraca ao lado da rede perdia até ~1e-6 relativo no cancelamento. Agora cada banda soma só
  os seus bins, e os números da CLI mudam nessa ordem, nas bandas fracas.
- **As duas vistas seguem um traço da vista de tempo** (o seletor da barra), com a cadeia dele; o trecho padrão é a
  captura inteira. Sem cadeia, as contas rodam nos códigos do ADC e são escaladas (são lineares), sem pôr a captura
  na memória; as bandas sincronizadas acham a fundamental nos volts do trecho, até 64 M amostras (~5 min).
- **O tempo ligado nos dois sentidos**, copiando o intervalo: o `setXLink` do PyQtGraph alinha pela posição na tela.
- **A tabela das bandas** vem na ordem da estatística escolhida (o P95 primeiro, como o `adc_tool`); o mapa de calor
  mostra o nível de cada janela, em dB.
- **Fica para depois:** a vista de espectro ainda não usa a base `VistaLigada` (as duas cuidam da vista de tempo do
  mesmo jeito); juntar quando a F2.7 trouxer a terceira vista de frequência por traço.

O plano original:

- **O conteúdo** (ES-03, ES-04): a tabela das bandas de 200 Hz e o mapa de calor banda × tempo (RMS, máximo, P95);
  o espectrograma com o mapa de cores perceptual, com o tempo ligado ao da vista de tempo. Uma captura longa vai em
  blocos, com o progresso no painel de tarefas.
- **Os testes:** as bandas iguais às do `adc_tool --bandas-iec`; o tempo ligado; cancelar.

### ☑ F2.7: os harmônicos

**Feita em 14/11/2026:** `57ece6d`. A vista segue um traço da vista de tempo (a base `VistaLigada` da F2.6), com a
janela visível como trecho padrão; sem cadeia, a tabela é a do `adc_tool --fft --harmonicos 40` a 1e-12. As barras
mostram o subgrupo por padrão (a grandeza da IEC 61000-4-30 classe A), em % da fundamental. **Fica para depois:** a
janela sincronizada (os ciclos inteiros usados) marcada na vista de tempo.

O plano original:

- **O conteúdo** (ES-05): barras e tabela dos grupos e subgrupos da IEC 61000-4-7, o THD, o THDG e o THDS, da janela
  sincronizada pelos cruzamentos por zero.
- **Os testes:** a tabela igual à da CLI para o mesmo trecho.

### ☐ F2.8: os avisos nos chips, o erro inesperado e o log

- **O conteúdo:** os avisos do motor também no chip do traço (o problema da sonda, a faixa suposta); o diálogo de
  erro inesperado, com os detalhes copiáveis e o caminho do log, sem fechar o aplicativo (GE-09); o log em rotação
  na pasta do sistema, sem senhas nem conteúdo de arquivos (plano, 8.4).
- **Os testes:** um erro numa tarefa e num slot vira o diálogo, e o aplicativo segue; o log gravado e em rotação.

### ☐ F2.9: as configurações

- **O conteúdo** (GE-05): a tela de configurações, com o tema e as fontes (hoje no menu de ajustes), as pastas
  (`$DADOS`, sondas, cache), o separador decimal, as unidades, reduzir movimento e o limite do cache, todos
  gravados; "limpar o cache".
- **Os testes:** cada configuração gravada e aplicada na partida; o limite do cache respeitado.

### ☐ F2.10: o que ficou da Fase 1

- **O conteúdo:**
  - abrir o `.h5` e o `.csv` do `adc_tool`, e o `.bin` legado pedindo a taxa e os canais (PD-02);
  - copiar o cabeçalho como texto ou JSON (PD-07);
  - o zoom em caixa (`Z` + arrastar) e o modo sobrepor da vista de tempo (AN-03, AN-04).
- **Os testes:** cada formato aberto com os mesmos volts da CLI; o zoom em caixa e o sobrepor.

### ☐ F2.11: o fechamento da Fase 2

- **O conteúdo:** a jornada do pesquisador num teste de ponta a ponta (abrir, plotar, ligar a correção de sonda,
  abrir o espectro, conferir com a CLI); o G1 medido de novo com a cadeia ligada; o plano e este arquivo em dia.
  **A tag v0.9** fica para o dono do projeto (nada vai ao GitHub sem ele pedir).

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
| 14/11/2026 | **G1 na vista de tempo, na tela do usuário, 8 faixas** (área de 702 × 214 px), antes da rodada de fluidez | **Reprovado:** mediana de 18,8 ms, p95 de 20,6 ms | `prototipos/medir_vista.py` |
| 14/11/2026 | Bancada sem tela, 8 faixas, 1 022 × 558 px: o quadro antes e depois da rodada de fluidez | Mediana de 16,5 → **9,6 ms**; p95 de 21,8 → **11,8 ms**. O custo fixo (nada desenhado) caiu de 8,8 para 2,2 ms | bancada do diário de 14/11 |
| 14/11/2026 | **G1 na vista de tempo, na tela do usuário, 8 faixas, depois da rodada** | **Aprovado:** mediana de 8,0 ms, p95 de 9,7 ms | `prototipos/medir_vista.py` |
| 14/11/2026 | Travadas da tela (o laço de eventos parado), captura de 5 min: plotar 8 traços; mudar a faixa de um traço | 0,81 → **0,15 s**; 0,12 → **0,03 s** | idem |
| 13/11/2026 | G1 sem tela na **vista de tempo**, 8 faixas, com a CPU sob estresse de outra sessão (carga de 16 a 25) | **Sem valor como medida:** mediana de 35 ms. O perfil achou e tirou dois gastos (a grade com o `tickValues` e o rótulo HTML dos eixos escondidos) | `prototipos/medir_vista.py`, perfil |
| 14/11/2026 | **O espectro de uma FFT de 60 s** (6 M bins), 1 600 × 1 000 px, sem tela: arrastar, zoom, cursor | Antes: 316, 319 e 330 ms por quadro (o aplicativo travava). **Depois: 7,4, 6,2 e 2,2 ms**; a tela leve durante a conta (o pior quadro da vista de tempo, 15 ms) | `pytest --desempenho tests/test_gui_desempenho.py -k espectro` |
| 14/11/2026 | As FFTs de um lote em todos os núcleos (8), `scipy.fft` com `workers=-1` | O lote do Welch (2048 × 1000) de 7,1 para 2,5 ms; o das bandas (64 × 40 000) de 13,8 para 10,9 ms | o diário de 14/11 |
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
- **13/11/2026 (noite):** a F1.5, a vista de tempo, conferida com as capturas do laboratório (60 Hz com 20 kHz e
  130 kHz). O G1 com 8 faixas fica para a tela do usuário. **Próximo:** a F1.6.
- **13/11/2026 (noite):** a F1.6, o inspetor do traço. **Próximo:** a F1.7.
- **13/11/2026 (noite):** a F1.7, os cursores e as medidas. **Próximo:** a F1.8.
- **13/11/2026 (noite):** a F1.8, a paleta de comandos. **A Fase 1 está feita no código.** Os dois CIs verdes (1 304
  e 427 testes). **Próximo:** o G1 com 8 faixas e o "pronto quando" na tela do usuário; depois, a Fase 2 em tarefas.
- **14/11/2026:** o `main` do GitHub (as correções dos testes do firmware) trazido para cá (`3ad791f`). **A rodada
  de fluidez** (`00c1f67` só do motor; `730f4ea` a interface), medida com um perfil e uma bancada que desliga cada
  parte da vista:
  - **O quadro do zoom com 8 faixas:** os traços escondidos não consultam mais; o texto da janela de tempo tem
    largura fixa (mudando de largura a cada quadro, ele refazia o layout da janela inteira); o `TracoLOD` não usa o
    `viewPixelSize` do PyQtGraph (0,23 ms por traço); os eixos fazem as marcas sem o `np.isclose`, guardam as medidas
    dos textos, desenham direto (sem a `QPicture`) e o Y fica num cache de pixels; o minimapa virou um widget leve.
  - **As travadas fora do zoom:** a vista é sincronizada aos poucos (só muda o que mudou); a tabela de medidas mede
    as colunas uma vez; o inspetor do cabeçalho usa um rótulo de texto rico por seção; a f₁ automática da janela vai
    até 1 M amostras; o SciPy é importado em segundo plano na partida (a primeira medida o importava, com o GIL
    preso por ~1,5 s).
  - **O que sobra do quadro** (~8 ms na bancada) é do PyQtGraph: as 8 `ViewBox` ligadas no tempo (~2 ms), o eixo do
    tempo (~1,6 ms) e os caminhos dos traços (~0,2 ms cada). Se um dia faltar folga: uma `ViewBox` só para todas as
    faixas, cada uma com a sua transformação em Y.
  - **Uma corrida corrigida:** o `GerenciadorDeTarefas.iniciar` começava a tarefa antes de quem chamou ligar o
    `terminou`; uma tarefa rápida (a conferência de uma captura sem CRC) terminava antes e o fim se perdia (a
    captura ficava "conferindo"). Os ouvintes agora vão no próprio `iniciar` (`ao_terminar`, `ao_progredir`).
  - **Para lembrar:** os scripts da GUI fora do pytest abrem a janela na tela do usuário se não tiverem
    `QT_QPA_PLATFORM=offscreen` (o `medir_vista` abriu umas sete vezes nesta rodada). Numa tela pequena, as 8 faixas
    ficam com ~27 px cada, com os painéis abertos: recolha-os (Ctrl+B/I/J).

- **14/11/2026:** o botão do meio na vista de tempo, a pedido do usuário: arrastar em cima de um traço move só ele
  (o offset em Y e o deslocamento no tempo; um passo de desfazer por arrasto, pela marca de gesto do
  `MudarTracos`); em outro lugar, move a vista nas duas direções sem mudar as escalas; o clique rápido põe o 0 do
  eixo Y no meio da faixa e tira o offset do traço clicado (ou dos selecionados nela). Testado também com eventos
  de mouse de verdade pela cena do PyQtGraph.
  - **Uma queda achada pela CI** (um *segmentation fault*, 1 vez em 4 rodadas): a coleta de lixo automática do
    Python rodou numa tarefa em segundo plano (uma medida de uma janela já fechada, importando o SciPy) e apagou
    widgets fora da thread da interface. Agora a coleta só roda na thread da interface, num temporizador do Qt
    (`app.ligar_coleta_na_thread_da_interface`, o `GarbageCollector` do PyQtGraph), e nenhuma tarefa começa depois
    de `GerenciadorDeTarefas.encerrar()`. **Para lembrar:** com a coleta automática desligada, uma conta longa e
    síncrona na thread da interface acumula lixo até o laço de eventos voltar.
  - **Os avisos `qt.qpa.wayland.textinput`** que o usuário viu no terminal ("Trying to disable ... but ... is
    focused") são do plugin de Wayland do Qt, a cada troca de foco entre superfícies; o aplicativo silencia essa
    categoria (`QT_LOGGING_RULES` ainda a liga de volta).
- **14/11/2026:** a Fase 2 quebrada em tarefas (seção 4c). **Próximo:** a F2.1.
- **14/11/2026:** dois defeitos que o usuário achou testando com a B2 do laboratório (60 Hz + 130 kHz, 200 kHz por
  canal):
  - **A onda virava um "retângulo" de perto,** de um passo da roda para o outro: a partir de 8 px por amostra (os
    pontos das amostras), o QPainter, com a caneta de 4 px dos pontos e a escala do tempo acima de 10⁶ px/s,
    pintava um bloco cheio entre a linha e a primeira amostra (isolado num `QImage`: 140 pontos acendiam 49 923 px
    em vez de ~1 800). Não depende do tempo da janela, só da escala. O `TracoLOD` agora passa a linha e os pontos
    das amostras para pixels da tela no NumPy e os desenha sem a transformação da vista; a envoltória (de longe)
    continua como estava. Teste: `test_de_perto_os_pontos_nao_viram_um_bloco_cheio`.
  - **A roda em cima dos números dos eixos dava `TypeError`:** o `AxisItem` do PyQtGraph repassa a roda e o
    arrasto à caixa com `axis=`, e a `CaixaDaFaixa` não aceitava. Agora, em cima de um eixo, a roda e o arrasto
    mexem só naquele eixo (a roda nos números do Y dá o zoom no Y sem o Ctrl), e um clique ali não mexe na seleção.
    As posições da caixa saem sempre da cena (`scenePos`): o `pos()` de um evento repassado está nas coordenadas do
    eixo.
  - **Para lembrar:** a 200 kHz por canal, o tom de 130 kHz das capturas B aparece em 70 kHz (acima de Nyquist,
    100 kHz): o pico do espectro do canal 0 da B2 está em 70,0 kHz.
- **14/11/2026:** o usuário mudou de ideia sobre o botão do meio em cima de um traço: o arrasto ali **não move mais
  só aquele traço**, move a vista como em qualquer outro lugar (sem mudar as escalas nem os traços). Saíram os sinais
  `arrasteDoMeioComecou` e `tracoArrastado` da `CaixaDaFaixa` e o modo `"traco"`; o offset e o deslocamento no tempo
  de um traço continuam no inspetor. O clique rápido do meio segue igual (o 0 no meio da faixa; em cima de um traço,
  tira o offset dele).
- **14/11/2026:** **o ícone na barra de aplicativos do Linux** (o usuário, no Pop!_OS com o COSMIC, via a engrenagem
  genérica). No Wayland, o painel não usa o ícone da janela: acha o ícone pelo `app_id` da janela, procurando um
  `<app_id>.desktop`. O Qt mandava o nome do executável do Python. Agora a aplicação põe `app_id` = `sh-analyzer`
  (`setDesktopFileName`), e `sh-analyzer-gui --instalar-atalho` (módulo `atalho.py`, sem Qt) grava
  `~/.local/share/applications/sh-analyzer.desktop` e o ícone em `~/.local/share/icons/hicolor/scalable/apps/`;
  `--remover-atalho` os apaga. O atalho abre esta cópia pelo `uv` com o extra `gui` (o ambiente pode estar sem o
  PySide6 depois de um `uv run` sem o extra). O AppImage (seção 15 do plano) trará o seu.
- **14/11/2026:** **a F2.1, a `api` da frequência** (seção 4c). Achados no caminho, todos corrigidos no motor:
  - a `api` usava a taxa pedida, e a CLI usa a que a PRU gera: a 102,4 kHz, a fundamental e o eixo do tempo ficavam
    64 ppm fora dos da CLI;
  - com um memmap `float32` (o formato que o cache das transformações deve ter), o Welch e o espectrograma faziam a
    conta em `float32` e erravam até 0,001 dB; os lotes agora vão a `float64`;
  - o lote do Welch tinha sempre 2048 segmentos: a 5 Hz de resolução e 200 kS/s, 650 MB de uma vez. Agora tem no
    máximo ~2 M valores (16 MB); na resolução padrão (200 Hz), nada muda;
  - as bandas IEC convertiam o trecho inteiro para `float64` de uma vez (5,8 GB numa captura de 1 h); agora, um lote
    de 64 janelas por vez;
  - o `capturar_avisos` juntava os avisos de todas as threads e podia deixar o logger do motor em INFO; agora cada
    coleta fica com os avisos da sua thread.
  - **Testes:** `ci.sh rapido` com 1 364 aprovados.
- **14/11/2026:** **a F2.2, a cadeia de transformações** (seção 4c). No motor, os filtros de faixa (o
  `aplicar_filtro_digital` aceitava um corte só), a validação dos filtros com o motivo e a margem da correção de sonda
  (`sonda.alcance_da_correcao`, que não gasta o aviso de "fora da faixa" do perfil: o `ganho_em` só avisa uma vez por
  perfil). Na interface, `dados/cadeia.py`, a receita com a cadeia e o `.shproj` v2.
  - **Testes:** `ci.sh rapido` com 1 410 aprovados e `ci.sh interface` com 487.
- **14/11/2026:** **a F2.3, a materialização e o cache** (seção 4c). O pedido do usuário para esta rodada: "sempre
  pensando em fluidez de uso e precisão dos dados gerados". Daí a prévia numa thread só dela, o preenchimento
  progressivo, o "nunca o canal cru no lugar do transformado" e as medidas do sinal transformado em `float64`.
  - **Testes:** `ci.sh rapido` com 1 423 aprovados e `ci.sh interface` com 499; os de desempenho (`--desempenho`)
    passam, com a prévia de 1 s abaixo de 200 ms.
  - **Próximo:** a F2.4, a cadeia no inspetor e nos chips.
- **14/11/2026:** **a F2.4, a cadeia no inspetor** (seção 4c). Achado no caminho: o teste das medidas do traço
  transformado oscilava com a máquina carregada (o pedido automático da vista chegava depois do pedido do teste e o
  trocava); o teste passou a esperar a resposta do seu pedido.
  - **Testes:** `ci.sh rapido` com 1 430 aprovados e `ci.sh interface` com 505.
  - **Próximo:** a F2.5, a vista de espectro.
- **14/11/2026:** **a F2.5, a vista de espectro** (seção 4c). Achado no caminho: ao ligar a frequência log, o cursor
  ficava na posição em Hz, que o eixo log lê como expoente (10⁵⁰⁰⁰⁰); o cursor guarda a frequência em Hz e é
  reposicionado a cada desenho.
  - **Testes:** `ci.sh rapido` com 1 449 aprovados e `ci.sh interface` com 523.
  - **Próximo:** a F2.6, as bandas IEC e o espectrograma.
- **14/11/2026:** **a F2.6, as bandas IEC e o espectrograma** (seção 4c). Achados no caminho: a soma acumulada das
  bandas (acima); o `setXLink` que alinhava pela tela; e um teste do espectro que oscilava com a máquina carregada
  (esperava o primeiro sinal de "calculado", e um pedido de antes da mudança podia chegar depois). Cada resultado
  agora guarda as opções e o trecho que o produziram.
  - **Testes:** `ci.sh rapido` com 1 462 aprovados e `ci.sh interface` com 535.
  - **Próximo:** a F2.7, os harmônicos.
- **14/11/2026:** **a F2.7, os harmônicos** (seção 4c).
  - **Testes:** `ci.sh rapido` com 1 465 aprovados e `ci.sh interface` com 538.
  - **Próximo:** a F2.8, a F2.9 ou a F2.10 (independentes).
- **14/11/2026:** **o espectro travava o aplicativo** (relato do usuário: com os cursores em 20 períodos, tudo perdia a
  fluidez, e arrastar a FFT "dava dor de cabeça"). A causa: o trecho padrão era a janela visível (a captura inteira),
  e a FFT de 60 s tem 6 M bins; cada quadro custava ~320 ms (o PyQtGraph recortava e reduzia os 6 M pontos a cada
  mudança da vista, e o cursor copiava o espectro inteiro a cada movimento). O que mudou (`5619602`, e `a95ba57` só
  do motor):
  - o espectro na frequência linear é desenhado pela pirâmide mín/máx (o `TracoLOD`: os bins são uniformes), e na log
    pela envoltória por coluna de pixel; os níveis, a pirâmide e as marcas são preparados na thread de trabalho;
  - o espectro de um trecho já calculado não é refeito (nas quatro vistas de frequência);
  - a grade do tema, o eixo Y em cache, os harmônicos num item só; o zoom do usuário fica quando o resultado chega;
  - o trecho padrão do espectro passa a ser o dos cursores (sem eles, a janela visível);
  - as FFTs em lote (Welch, espectrograma, bandas) em todos os núcleos.
  - **Medido:** a tabela da seção 5. Um portão novo, `tests/test_gui_desempenho.py -k espectro`: menos de 16 ms por
    quadro com 3 M bins.
  - **O que fica:** a FFT de um trecho de 60 s leva ~1,5 s (a busca da fundamental, 0,85 s, e a FFT de 12 M pontos com
    o fator primo 1499, 0,6 s), em segundo plano; um tamanho mais "redondo" mudaria os números da CLI.
  - **Testes:** `ci.sh rapido` com 1 466 aprovados e `ci.sh interface` com 539.
---

## 8. Perguntas em aberto

São as do plano, seção 19. Não bloqueiam a Fase 0:

- o tema padrão na primeira execução;
- a ordem das versões (Aquisição antes de Figuras);
- a regra de sudo sem senha na placa;
- o inglês na v1.0;
- a assinatura de código no Windows.
