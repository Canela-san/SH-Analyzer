# Andamento da interface gráfica

O diário e a lista de tarefas do desenvolvimento da GUI. O **plano** (o quê e por quê) está em [`gui-plan.md`](gui-plan.md); este arquivo diz **onde o trabalho parou e qual é o próximo passo**. Com ele, o trabalho continua igual depois de uma pausa, numa sessão nova ou nas mãos de outra pessoa.

**Atualize este arquivo a cada tarefa concluída e antes de qualquer pausa.**

---

## Próxima tarefa

> **F0.6: os portões G1 a G5** (seção 4). Comece medindo o protótipo numa tela de verdade (o G1 com 8 faixas está no limite, seção 5).
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

Os estados são ☐ a fazer, ▶ a próxima e ☑ feita. Cada tarefa cabe em uma ou duas sessões e termina com os testes passando.

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

### ▶ F0.6: os portões G1 a G5

- **Arquivos:**
  - `tests/test_gui_desempenho.py`, marcado `desempenho` e fora do conjunto padrão. Registre o marcador no `pyproject.toml`.
  - Um gerador de captura sintética grande (`.bin` v9 com 1 h, 2 canais, 400 kS/s), sobre o `tests/capturas_sinteticas.py`. O arquivo de 2,9 GB vai para a pasta temporária e é reaproveitado.
- **Os portões** estão na seção 6.7 do plano. O G2 (4K a 200 %) e o G5 (disco frio) pedem uma tela de verdade e, para o Windows, uma máquina com Windows: anote aqui o que não deu para medir.
- **Para medir o G1 e o G2:** `uv run --extra gui python -m sh_analyzer_gui.prototipos.navegar --sintetico 60 --canais 8 --medir`, numa tela de verdade (sem `QT_QPA_PLATFORM=offscreen`). Com 8 faixas, sem tela, o p95 está em 16,0 ms, no limite.
- **Se reprovar:**
  1. primeiro, os eixos e a grade próprios (opacos, com o texto em cache), que vêm na Fase 1 de qualquer forma;
  2. depois, o desenho híbrido (o polígono quando a banda é lisa, plano 6.2);
  3. por fim, a GPU (plano 6.7).
- **Pronto quando:** os resultados estão na seção 5 deste arquivo e na 6.7 do plano. Se algum portão falhar, decida o plano B antes de seguir.

### ☐ F0.7: a `api` do motor (commits só do motor)

- **Arquivos:** `scripts/supraharmonicos/api.py`, `contexto.py` (o `resolver_contexto` passa a usar a `api`), `tests/test_api.py` e o `CAMADAS` do `tests/test_arquitetura.py`.
- **As funções:** `abrir_captura` e `sinal_do_canal` (plano, 8.2), com os avisos estruturados.
- **Pronto quando:** os testes de paridade com a CLI passam e toda a suíte continua verde.

### ☐ F0.8: o tema

- **Arquivos:** `scripts/sh_analyzer_gui/tema/tokens.py`, `tema/qss.py`, `tema/icones.py` e `tema/fontes.py`.
- **Os tokens:** os valores de `docs/gui-mockups/tema.css`.
- **A partir deles:**
  - a `QPalette` e o QSS dos dois temas;
  - as fontes Inter e JetBrains Mono em `recursos/fontes/`, com os arquivos de licença OFL;
  - um subconjunto dos ícones do Lucide em `recursos/icones/`, com a licença ISC, recoloridos pelo tema.
- **O teste:** `tests/test_tema.py`, com a conta do `scripts/benchmarks/paleta_cores.py` sobre os tokens.
- **Pronto quando:** a janela vazia troca de tema sem reiniciar e o `test_tema.py` passa.

### ☐ F0.9: a galeria de componentes

- **Arquivos:** `scripts/sh_analyzer_gui/componentes/` e `scripts/sh_analyzer_gui/galeria.py`, aberta com `python -m sh_analyzer_gui.galeria`.
- **Os 6 primeiros componentes:**
  - botão (primário, secundário, fantasma, perigo, ícone);
  - campo numérico com unidade e prefixo do SI;
  - seletor segmentado;
  - chip de traço;
  - cartão de medida;
  - toast.
- **Pronto quando:** a galeria mostra os 6 nos dois temas, parecidos com os mockups, com um teste pytest-qt que abre cada um.

### ☐ F0.10: o `sh_placa`, o agente e o simulador

- **Arquivos:**
  - `firmware/agente/shan_agente.py` (só a biblioteca padrão; as raízes `/sys`, `/proc` e `/boot` configuráveis por variável de ambiente, para os testes);
  - `scripts/sh_placa/` (o cliente que roda o agente e lê o JSON, e o simulador);
  - o extra `placa` no `pyproject.toml`;
  - `tests/test_agente.py` e `tests/test_sh_placa.py`.
- **Os comandos:** só `versao` e `estado`, por enquanto (plano, 11.2). O `ci.sh` do firmware passa a conferir o agente.
- **Pronto quando:** o agente responde sobre uma árvore falsa, e o simulador responde os mesmos dois comandos.

### ☐ F0.11: o instalador de teste

- **O quê:** um PyInstaller em pasta, com o PySide6, o PyQtGraph e o SciPy. Primeiro no Linux; no Windows quando houver uma máquina.
- **Pronto quando:** o tamanho e o tempo de abrir estão anotados na seção 5.

### ☐ F0.12: o fechamento da Fase 0

- Os resultados dos portões no plano.
- O plano B decidido, se for preciso.
- A Fase 1 quebrada em tarefas, nesta seção, no mesmo formato.

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
  - **Próximo:** a F0.6, medindo o protótipo numa tela de verdade.

---

## 8. Perguntas em aberto

São as do plano, seção 19. Não bloqueiam a Fase 0:

- o tema padrão na primeira execução;
- a ordem das versões (Aquisição antes de Figuras);
- a regra de sudo sem senha na placa;
- o inglês na v1.0;
- a assinatura de código no Windows.
