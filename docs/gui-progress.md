# Andamento da interface gráfica

O diário e a lista de tarefas do desenvolvimento da GUI. O **plano** (o quê e por quê) está em [`gui-plan.md`](gui-plan.md); este arquivo diz **onde o trabalho parou e qual é o próximo passo**. Com ele, o trabalho continua igual depois de uma pausa, numa sessão nova ou nas mãos de outra pessoa.

**Atualize este arquivo a cada tarefa concluída e antes de qualquer pausa.**

---

## Próxima tarefa

> **A Fase 2 está feita** (seção 4c, F2.1 a F2.11; diário de 15/11): a jornada do pesquisador vai da captura ao
> espectro corrigido pela sonda, com os números da CLI (`tests/test_gui_jornada.py`), e o G1 passa com a cadeia
> ligada, durante e depois das materializações. **A tag v0.9** fica para o dono do projeto.
>
> **A Fase 3 está feita** (seção 4d, F3.1 a F3.10; diário de 16/11): a F3.1 (o laço `asyncio` do `sh_placa` e a ponte), a F3.2 (a conexão SSH,
> as chaves, o cofre e o registro de atividade), a F3.3 (a descoberta das placas), a F3.4 (o agente completo: a
> saúde, as capturas, o relógio e os logs), a F3.5 (a área de Aquisição na tela: a lista de placas, a conexão e a
> primeira conexão), a F3.6 (a visão geral e o diagnóstico, com o "Corrigir" do relógio e dos pinos) e a F3.7 (os
> arquivos e a transferência, que espera as capturas), a F3.8 (o terminal: o `pyte` num widget próprio, sobre um
> PTY no SSH, com as abas, os atalhos e a gravação) e a F3.9 (o simulador com os cenários, servido por SSH neste
> computador), conferidas no servidor SSH do teste e na placa de verdade. A jornada da Aquisição (achar, conectar,
> a visão geral, o diagnóstico, o relógio acertado, a captura transferida, conferida pelo CRC e aberta na Análise)
> roda de ponta a ponta com o simulador (`tests/test_gui_jornada_aquisicao.py`) e rodou na placa de verdade, na janela
> sem tela, em casa e na tomada do laboratório (seção 5).
>
> **A Fase 4, a captura, está feita** (seção 4e, F4.1 a F4.7; diário de 18/11). **A F4.1 está feita** (diário de 16/11): o
> `ler_adc -o -` (a captura pelo stdout, com o cabeçalho final depois do último bloco), o código 6 (a saída que fechou
> ou parou de andar por 10 s) e o `--progresso-json`, validados na placa de verdade (seção 5). **A F4.2 está feita**
> (diário de 17/11): a captura contínua no computador, sem Qt (`sh_placa/captura.py` e o fechamento do motor,
> `supraharmonicos/saida_continua.py`): o arquivo gravado enquanto chega, o Parar, a queda e o disco daqui fechados
> com o que chegou (a marca "fim escrito pelo computador" no cabeçalho), e a placa simulada transmitindo de verdade;
> validada na placa (seção 5). **A F4.3 está feita** (diário de 18/11): a seção Capturar, com o formulário de
> captura (o pedido validado ao vivo pelas regras do `ler_adc.c`, num contrato com o C), os modelos no projeto e o
> "Conferir antes" (um bloco do próprio pedido, medido no motor com as regras do `coletar.sh conferir`), validado na
> placa com o canal 1 na tomada de casa (seção 5). **A F4.4 está feita** (diário de 18/11): a captura na tela, com o
> cockpit (o tempo, a vazão, a integridade, o sinal e o espectro ao vivo), o Parar, a queda no computador (fechada com
> o que chegou) e no cartão (a captura segue na placa, desacoplada da conexão, e o aplicativo volta a acompanhá-la), e
> a transferência no fim; validada na placa (seção 5). **A F4.5 está feita** (diário de 18/11): o caderno de bancada,
> no `anotacoes.md` da sessão do dia (só acrescentado), com as entradas automáticas e as notas, na seção Capturar e na
> seção Notas do projeto. **A F4.6 está feita** (diário de 18/11): a seção Rotinas, com os modos do `coletar.sh` num
> formulário (a bancada vem do pedido da Capturar), a ajuda lida da placa e o "Rodar no terminal" numa aba nova, com as
> pausas da bancada lá; validada na placa. **A F4.7 está feita** (diário de 18/11): a jornada da captura de ponta a
> ponta na janela, com o simulador (`tests/test_gui_jornada_captura.py`), e 1 h direto no computador na placa de
> verdade, sem perder amostra, aberta na Análise (seção 5). **A tag v0.10** fica para o dono do projeto. **A Fase 5
> (figuras e exportação) está em tarefas** (seção 4f, F5.1 a F5.10). **A F5.1 está feita** (diário de 18/11): o
> modelo da figura e a versão 5 do projeto. **A F5.2 e a F5.3 estão feitas** (diário de 19/11): o desenho com o
> Matplotlib (o M4 nas colunas dos pixels, conferido contra todos os pontos) e a área Figuras (a vista vira figura
> com um clique, o painel ligado acompanha a vista, congelar, desfazer). **A F5.4 está feita** (diário de 19/11): a
> figura sai em PDF, SVG, EPS, PGF, PNG e TIFF, com a proveniência nos metadados, e vai para a área de
> transferência. **A próxima: a F5.5**, a exportação dos dados. **A placa de verdade ainda tem o `ler_adc` antigo** (v0.8, sem o `-o -`):
> a captura contínua e o "Conferir antes" dizem "atualize o firmware da placa" (o código 96 do roteiro, conferido
> nela), e o aplicativo vai precisar mandar o firmware novo (o `enviar` do `BeagleBone_Setup.sh`, ou a Fase 6).
>
> **Para o usuário ver na tela:** plotar um canal; no inspetor, "Adicionar etapa" (ou Ctrl+K, "passa-altas"); Ctrl+E
> (espectro), Ctrl+Shift+B (bandas IEC), Ctrl+Shift+E (espectrograma), Ctrl+Shift+H (harmônicos); Ctrl+, (as
> configurações); no inspetor, "Unidade" e "Dois pontos…"; Ctrl+O num `.csv` ou `.h5` do `adc_tool` (ou num `.bin`
> sem o cabeçalho); na vista de tempo, `Z` e arrastar, e o botão das camadas (sobrepor); no inspetor da captura,
> "Copiar JSON". Com dois canais transformados, o segundo diz "na fila" no chip e no painel de tarefas até a vez dele.
> **A Aquisição** (o seletor da barra superior, ou o chip da placa): a placa do USB e o simulador aparecem na lista
> sozinhos; um clique conecta (na primeira vez, o diálogo confere a impressão digital, pede a senha e instala a chave
> do aplicativo); "Conectar por IP…" para uma placa em outra rede. Conectada: a visão geral (os indicadores, a saúde,
> as capturas na placa e a atividade ao vivo), o "Acertar…" do relógio, o diagnóstico item a item, com o relatório, e
> os arquivos: "Transferir as novas" para a pasta da sessão do dia, "Abrir na Análise" e "Apagar da placa" (só o
> conferido). **O simulador** está na lista também: o "Cenário" da visão geral (ou o "Conectar no cenário" do menu
> da placa) troca a placa simulada (o ADC mudo, o cartão cheio, a conexão que cai, o relógio errado...).
> **A seção Capturar** (na barra lateral da Aquisição): o formulário com o comando embaixo, os problemas em cada
> campo, o menu "Modelo" e o "Conferir antes" (com o simulador: a faixa sugerida e "Usar as faixas sugeridas").
> **Capturar** (com o simulador): o cockpit no centro, com o sinal e o espectro ao vivo e o Parar; "No cartão da
> placa", os blocos e a transferência no fim. **O caderno de bancada**, à direita: as entradas sozinhas (a
> conferência, a captura, a queda, a transferência, o relógio acertado) e "Escrever uma nota…"; o "x" o esconde, o
> "Caderno" do título o traz. No diagnóstico, "Para o caderno"; na Análise, a seção "Notas" do projeto.
>
> **Com o usuário (quando puder):**
> - a jornada da Aquisição na tela, com a placa: a placa na lista, um clique, a visão geral, o "Acertar…", os
>   Arquivos ("Transferir", "Abrir na Análise") e o espectro da tomada;
> - a seção Capturar na tela: a leitura do formulário (as seções, os problemas no campo, o comando), num monitor de
>   verdade (a imagem sem tela foi conferida, mas o tamanho das fontes e o espaço são do usuário);
> - o cockpit e o caderno lado a lado num monitor de verdade: a janela de 1440 px cabe sem rolar de lado (sem tela);
>   numa menor, o caderno se esconde pelo "x";
> - o G1 com a cadeia, na tela: `uv run --extra gui python -m sh_analyzer_gui.prototipos.medir_vista --cadeia`
>   (sem tela, p95 de 11,9 a 12,9 ms durante as materializações e de 14,0 a 14,2 ms depois; se reprovar na tela, o
>   texto dos eixos em cache, com `QStaticText` (a F1.5), é o próximo passo);
> - o "pronto quando" da Fase 1: abrir uma captura de 1 h, navegar e medir com 8 traços de 2 fontes, em
>   `uv run --extra gui python -m sh_analyzer_gui`.
>
> **A placa de verdade** está no USB do computador do usuário (15/11/2026): `debian@192.168.6.2`, com a chave. O
> cabo tem mau contato (a conexão cai sem aviso), e o disco dela é pequeno (~1,5 GB livres): as capturas vêm
> para `$DADOS/lab/` e saem da placa depois de conferidas. **O canal 1 está na tomada da casa do usuário** (desde
> 18/11/2026: ~128 V rms, 9,3 V de pico no pino, 91 % da maior faixa; antes, na do laboratório, 132 V). A placa não
> tem bateria no relógio: desligada, ela volta atrasada (3 h 07 numa vez; ~37 h em 18/11).

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

   **Enquanto o `ci.sh` roda, não mexa na árvore nem no `.venv-ci`:** ele testa os arquivos de trabalho, e um `uv run`
   com `UV_PROJECT_ENVIRONMENT=.venv-ci/...` (o `ruff`, por exemplo) sincroniza o ambiente que ele está usando. Uma
   rodada com a árvore mudando no meio não vale para commit nenhum (18/11/2026).

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
| 16/11/2026 | O PySide6 abaixo do 6.12 na Python 3.10 e 3.11: o 6.12.0 tira uma referência do None a cada chamada de um método do Qt sem retorno, e ali a interface morria em minutos ("deallocating None"); da 3.12 em diante o None é imortal | `pyproject.toml`, o extra `gui`, e o bloco PEP 723 do `adc_tool.py`; `tests/test_gui_pyside.py` |
| 16/11/2026 | O simulador da placa sem a rede (`sh_placa/simulador.py`) e o servidor SSH dele à parte (`servidor_do_simulador.py`): os testes do agente e do diagnóstico rodam sem o extra `placa` | `tests/test_arquitetura.py` |

---

## 3. O estado atual

**Em 16/11/2026, no `feat/interface`, em commits locais:** as Fases 0 a 3 no código (a Fase 3: a Aquisição até a
conexão, os arquivos, o terminal e o simulador; seção 4d). O visualizador da Fase 1
(abrir as capturas, a vista de tempo, o inspetor, os cursores e as medidas, o projeto `.shproj` com o desfazer e a
paleta de comandos) ganhou na Fase 2 a cadeia de transformações (as afins, os filtros, o DC e a correção de sonda,
com a prévia e a materialização em segundo plano e o cache), as quatro vistas de frequência (espectro, bandas IEC,
espectrograma e harmônicos), os avisos nos chips e o log, as configurações com as unidades de qualquer sensor, e os
formatos do `adc_tool` (`.csv`, `.h5` e o `.bin` legado). As seções 4, 4b e 4c têm o commit de cada tarefa.

**Os commits só do motor** (podem ir ao `main` sozinhos): `974c58a` (a `api`), `e76684b` (a integridade e o
cabeçalho), `64f6e57` (a unidade do canal), `b5b02ab` (as medidas de um trecho), `00c1f67` (medir sem a fundamental e
aquecer sob demanda), `71ba268` (a taxa da PRU), `98d96e0` (a frequência, F2.1), `0ef8255` (os filtros), `28a1a04`
(a margem da sonda), `3110417` (`medir_sinal`), `631a770` (a faixa válida do perfil), `b368246` (o piso de ruído),
`8376894` (as bandas sem cancelamento), `a95ba57` (as FFTs de um lote em todos os núcleos), `c3ca56b` (a
proeminência dos picos), `220e422` e `eede2c1` (a fundamental), `9341048` (o aquecimento com uma trava), `7d0f40d` (a
pasta padrão das sondas), `6ac649d` (o cabeçalho num dicionário), `97a40d8` (os formatos), `61edf72` (a curva da
sonda em pedaços, sem prender o GIL) e `1257f5b` (o fechamento da saída contínua, F4.2). Os do firmware (F4.1):
`7551d7e`, `7745acb` e `a4f97b0` (este com o `cabecalho.py`: o formato muda pelos dois lados juntos). E o do agente da placa: `3f98d7b`. O diagnóstico da PRU entre capturas
(`0997175`) é do `sh_placa`, sem o agente.

**O ambiente:** Python 3.13, PySide6 6.12.0 (na 3.10 e na 3.11, o 6.11.3: seção 2), PyQtGraph 0.14.0, NumPy 2.5.4, SciPy 1.18.1; no extra `placa`,
asyncssh 2.24.1, zeroconf 0.154.0, pyserial 3.5, keyring 25.7.0 (o cofre do Linux é o Secret Service) e pyte 0.8.2. **A CI
roda em `.venv-ci/<versão>`** (desde 16/11/2026): o `.venv` é o de quem desenvolve, e o `ci.sh` não o troca mais.
Testes, na última rodada (19/11/2026, com a F5.4): o `ci.sh` completo em 333 s, com 2 525 em Python 3.13 (a
suíte inteira, com a interface) e 2 082 em 3.10 (sem o Qt).

**Desde 18/11/2026, a captura pela interface** (a Fase 4 até a F4.5, seção 4e): o formulário com o "Conferir antes",
a captura na tela (direto no computador ou no cartão, com o ao vivo, o Parar e a queda) e o caderno de bancada.

**Ainda não existe:** as rotinas como formulários nativos, com as pausas em diálogos (depois da v0.10); o resgate pela serial (v1.0); as exportações (a Fase 5, da F5.5 em diante).

---

## 4. Fase 0 em tarefas

Os estados são ☐ a fazer, ▶ a próxima, ◐ em parte e ☑ feita. Cada tarefa cabe em uma ou duas sessões e termina com os testes passando.

### ☑ F0.1: as decisões e este arquivo

O layout escolhido no plano, a conferência das cores em `scripts/benchmarks/paleta_cores.py` e este arquivo de andamento.

### ☑ F0.2: os dados da placa para a Aquisição

- **Objetivo:** confirmar na placa real o que o plano supõe:
  - o Python 3 para o agente;
  - os overlays e o `uEnv.txt`;
  - o gadget USB e o mDNS;
  - a vazão do SSH.
- **Como:** os comandos da seção 6. O resultado vai para a tabela de lá.
- **Pronto quando:** a tabela da seção 6 está preenchida, ou a tarefa fica para outra ida ao laboratório, sem prejuízo para as próximas.
- **Feito em 15/11/2026,** com a placa no USB em casa (a tabela da seção 6). O que muda para a Fase 3:
  - **o kernel é o 4.19**, não o 5.10 que o plano supõe: o diagnóstico (F3.4) aceita os overlays `*-4-19-TI-*`;
  - **o Python é o 3.7.3**, o que o agente já respeita;
  - **o nº de série do USB é o da EEPROM:** a descoberta (F3.3) reconhece a placa pela porta serial, antes do SSH;
  - **o mDNS dá um dos dois IPs do USB**, o da interface em que a pergunta chegou primeiro (o `getent` deu a
    192.168.7.2; o python-zeroconf da F3.3, ora a 6.2, ora a 7.2, uma vez as duas): os dois IPs vêm da sondagem da
    porta 22, e o mDNS só acrescenta o nome;
  - **a vazão é de ~5 MB/s**, limitada pela cifra no único núcleo da placa: a transferência (F3.7) prefere o
    `aes128-ctr` (5,9 MB/s), e pedidos SFTP em paralelo não aceleram.

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

### ☑ F2.8: os avisos nos chips, o erro inesperado e o log

**Feita em 14/11/2026:** `c669e2e` (o log e o erro inesperado) e `a4457bc` (os avisos no chip). O que ficou:

- **O log** (`registro.py`): `sh-analyzer.log` na pasta de logs do sistema (`platformdirs.user_log_dir`; a variável
  `SH_ANALYZER_LOG` a troca, e os testes a usam), em rotação (1 MiB e 5 cópias). A interface registra o que faz
  (abrir e salvar o projeto, abrir uma captura, as falhas); das bibliotecas, só os avisos; os do Qt e os do
  `warnings` passam por ele, e os erros saem também no terminal. Uma queda do processo deixa a pilha das threads em
  `quedas.log` (`faulthandler`). Nada de amostras, do conteúdo do projeto ou de senhas; os caminhos vão.
- **O erro inesperado** (`servicos/erros.py`, `componentes/dialogo_de_erro.py`): uma exceção que não é do motor
  (`ErroSHAN`) nem de arquivo (`OSError`), numa tarefa, num slot, num evento ou noutra thread, vai para o log com a
  pilha e para um diálogo **não modal**: o resumo, os detalhes para copiar (o ambiente e as pilhas) e o caminho do
  log, com um botão para abrir a pasta. O aplicativo segue. Os erros esperados continuam no lugar deles (o chip, a
  vista, o toast), sem janela. O mesmo erro repetido (num `paintEvent`, a cada quadro) conta as vezes no diálogo e
  vai ao log na 1.ª, 2.ª, 4.ª, 8.ª vez...
- **Os avisos no chip** (`dados/avisos.py`): um sinal à direita do chip, na cor do mais grave, e a lista na dica: a
  sonda registrada que não pôde ser usada, a faixa do ADC suposta, as amostras que não conferem com o CRC, uma etapa
  que não serve neste canal (um corte acima da Nyquist, um perfil que não abre) ou que não faz nada, e o erro da
  conta. Nas vistas de tempo e de espectro; a integridade conferida depois de plotar atualiza o chip.
- **Um texto errado corrigido:** com a sonda registrada sem um perfil usável, a correção automática dizia que "a
  captura não registra uma sonda"; agora diz que a registrada não pôde ser usada (a etapa e o inspetor).

O plano original:

- **O conteúdo:** os avisos do motor também no chip do traço (o problema da sonda, a faixa suposta); o diálogo de
  erro inesperado, com os detalhes copiáveis e o caminho do log, sem fechar o aplicativo (GE-09); o log em rotação
  na pasta do sistema, sem senhas nem conteúdo de arquivos (plano, 8.4).
- **Os testes:** um erro numa tarefa e num slot vira o diálogo, e o aplicativo segue; o log gravado e em rotação.

### ☑ F2.9: as configurações

**Feita em 14/11/2026:** `7d0f40d` (só do motor: a `api` diz a pasta padrão das sondas), `73be9e9` (as preferências
gravadas e aplicadas) e `f243ac5` (a tela). O que ficou:

- **A tela** (`areas/configuracoes.py`; o botão de ajustes, Ctrl+, e a paleta): Aparência, Números, Pastas e Cache,
  numa janela não modal; cada mudança vale na hora e fica gravada (`preferencias.py`). Substitui o menu de ajustes.
- **O separador decimal** vale para tudo o que se escreve (`numeros.formatar_si`, `formatar_duracao` e `decimal`, o
  dos números escritos à mão, e o texto para a planilha). Os números já na tela são escritos de novo pelo aviso da
  aparência (`Aparencia.avisar`): os eixos, as linhas de informação, a tabela de medidas (sem medir de novo), o
  inspetor, a árvore e a barra de status. A fonte dos números também vale na hora nos eixos.
- **O movimento:** o do sistema (`QStyleHints.accessibility().motionPreference`, o padrão), reduzido ou normal, em
  `Aparencia.movimento_reduzido`; o toast é a única animação até agora.
- **As pastas:** a dos dados (o diálogo de abrir começa nela sem um projeto aberto; sem ela, no recente mais novo; o
  padrão é a variável `$DADOS`, se existir), a das sondas (as capturas e os projetos abrem com ela; as já abertas
  mantêm o perfil que acharam) e a do cache (outra pasta é um cache novo; o que já roda termina no antigo).
- **O cache:** dois limites (as pirâmides, 4 GiB, e os traços transformados, 8 GiB, como antes), o uso e o
  "Limpar". Nem o limite nem o "Limpar" apagam o que está aberto (os serviços dizem o quê) nem o que uma tarefa
  constrói agora (`EmConstrucao`, nos dois caches: antes, um aparar de uma materialização podia apagar os arquivos
  de outra ainda em construção, com um limite pequeno).
- **Os campos numéricos sem as setas:** o estilo do sistema as desenhava quebradas nos dois temas; o valor muda pela
  digitação, pelas setas do teclado e pela roda.
- **A densidade da interface**, que o GE-05 também lista, não estava no conteúdo da F2.9 e ainda não existe.
- **Testes:** `tests/test_gui_configuracoes.py` (15) e o do botão de ajustes em `test_gui_janela.py`.

**As unidades, feitas em 15/11/2026** (o pedido do usuário: "quaisquer unidades que o usuário queira", com V, A, °C e
K como as principais): `8a6de44` (o catálogo e a unidade do traço), `fafae0a` (a seta das caixas de escolha),
`2669bf2` (o inspetor e os dois pontos) e `b946419` (os eixos e a página das unidades). O que ficou:

- **A unidade do traço** (`ReceitaDoTraco.unidade`; vazia, a do canal), gravada no projeto (os de antes abrem sem
  ela). O catálogo (`dados/unidades.py`): as principais, as de sensores comuns com a grandeza (temperatura, pressão,
  aceleração, velocidade, deslocamento, força, torque, potência, energia, rotação, ângulo, deformação, vazão...), as
  famílias que se convertem por uma afim exata (°C, K e °F; Pa, bar, psi, atm e mmHg; rpm e Hz...) e os múltiplos
  das que levam prefixo (mV, mA, kPa, µm). Um símbolo fora do catálogo vale, sem grandeza.
- **A escrita** põe o prefixo só onde ele cabe (1,5 mV, 23,46 °C, 1500 mV numa unidade já com prefixo; numa razão,
  vale o numerador: 100 °C/V); a leitura recusa um prefixo numa unidade sem prefixo ("2 m°C").
- **O inspetor:** a caixa da unidade (a lista com a grandeza ao lado; qualquer símbolo digitado; maiúsculas contam,
  k e K). Na mesma família, o ganho e o offset de cada traço são convertidos, num passo só (`MudarTracos` aceita
  uma mudança por traço); noutra, só o rótulo muda, e um aviso diz que a escala ficou. O ganho mostra a unidade
  dele (100 °C/V); o chip da legenda, a unidade do traço. **"Dois pontos…"** dá o ganho e o offset por dois valores
  conhecidos do sensor, e abre com a escala de agora.
- **Os eixos** escolhem o prefixo pela faixa visível ("tensão (mV)", "frequência (kHz)"), só nas unidades que o
  aceitam; o tempo para no segundo (uma hora é 3600 s). Desligável nas configurações (Números).
- **A página Unidades** das configurações: as do usuário (o símbolo, a grandeza, se leva prefixo), gravadas e
  aplicadas na partida, e o catálogo com as unidades em que cada uma se converte.
- **De passagem:** as caixas de escolha mostravam a seta do estilo do sistema (12.6), com uma borda escura no tema
  claro; agora é o ícone do SH-Analyzer, na cor do tema.
- **Ainda não:** o texto dos campos numéricos (a faixa, os limites do cache) fica colado à borda: o QSS não chega
  ao editor interno do `QSpinBox` (tentei o `padding` nele e no `QLineEdit` de dentro).
- **Testes:** `tests/test_gui_unidades.py` (o catálogo, a conversão, a validação), as unidades em
  `test_gui_numeros.py` e `test_gui_receita.py`, a mudança por traço em `test_gui_modelo.py`, o inspetor e os dois
  pontos em `test_gui_inspetor_traco.py` (+8), os eixos e a página em `test_gui_configuracoes.py` (+6).

O plano original:

- **O conteúdo** (GE-05): a tela de configurações, com o tema e as fontes (hoje no menu de ajustes), as pastas
  (`$DADOS`, sondas, cache), o separador decimal, as unidades, reduzir movimento e o limite do cache, todos
  gravados; "limpar o cache".
- **Os testes:** cada configuração gravada e aplicada na partida; o limite do cache respeitado.

### ☑ F2.10: o que ficou da Fase 1

**Feita em 15/11/2026:** `6ac649d` (só do motor: o cabeçalho num dicionário), `ef2b894` (copiar o cabeçalho),
`afff39b` (o zoom em caixa e sobrepor), `97a40d8` (só do motor: os formatos) e `8b500eb` (os formatos na
interface). O que ficou:

- **Os formatos (PD-02):** o Ctrl+O e o arrastar abrem o `.bin` com o cabeçalho, o `.bin` legado, o `.csv` do
  `adc_tool -c` e o `.h5` do `--export-hdf5`. O que não tem o cabeçalho pergunta a taxa total e os canais (o `-f` e
  o `--canais` da CLI, com as validações dela; `areas/analise/sem_cabecalho.py`), com a última resposta escrita e o
  que ela dá por canal e em duração; o projeto (o formato 3) os guarda, e reabri-lo não pergunta. O `.csv` diz os
  canais pela coluna `canal` (só a taxa é perguntada), e um convertido com `--inicio` no meio de um ciclo é alinhado
  pelo índice das amostras (a CLI leria as linhas pela ordem e trocaria os canais). O `.h5` abre com o cabeçalho do
  `.bin` de origem e a calibração da exportação; o CRC das amostras é conferido quando ele tem a captura inteira. A
  chave do cache de um `.h5` nunca é o CRC do `.bin` (ele pode ser só um trecho). O `.csv` e o `.h5` vão para a
  memória (o `.h5` até 2 GB de amostras; um maior pede o `.bin` de origem).
- **Copiar o cabeçalho (PD-07):** no inspetor da captura, "Copiar texto" (as seções, como aparecem) e "Copiar JSON"
  (todos os campos, sem arredondar: `api.cabecalho_em_dict`; sem o cabeçalho, a taxa e os canais informados).
- **O zoom em caixa (AN-04):** `Z` (ou o botão) arma; o arrasto com o botão esquerdo desenha a caixa, e a faixa passa
  a mostrar o tempo e o Y dela (o tempo, em todas). Uma caixa com um lado de menos de 4 px não muda aquele eixo. O
  zoom feito desarma, e Esc também.
- **Sobrepor (AN-03):** o botão das camadas põe todos os traços numa faixa só, num passo de desfazer, gravado no
  projeto (`OpcoesDoTempo`); a faixa de cada traço fica guardada e volta ao separar, e o inspetor desliga a faixa
  enquanto a vista sobrepõe.
- **Ainda não:** sobrepostos, os traços de unidades diferentes dividem o Y, até o cadeado dar a um deles a escala
  própria. Destravar sozinho não serve: um traço destravado fica parado quando o tempo da vista muda.
- **Testes:** `tests/test_api_formatos.py` (12: os volts da CLI, bit a bit, nos três formatos),
  `tests/test_gui_sem_cabecalho.py` (2), `tests/test_gui_zoom_em_caixa.py` (2, com eventos de mouse de verdade), o
  sobrepor em `test_gui_vista_tempo.py`, os formatos e o copiar em `test_gui_abrir_capturas.py` (+2), o projeto 3 em
  `test_gui_projeto.py`.

O plano original:

- **O conteúdo:**
  - abrir o `.h5` e o `.csv` do `adc_tool`, e o `.bin` legado pedindo a taxa e os canais (PD-02);
  - copiar o cabeçalho como texto ou JSON (PD-07);
  - o zoom em caixa (`Z` + arrastar) e o modo sobrepor da vista de tempo (AN-03, AN-04).
- **Os testes:** cada formato aberto com os mesmos volts da CLI; o zoom em caixa e o sobrepor.

### ☑ F2.11: o fechamento da Fase 2

**Feita em 15/11/2026:** `76e26ee` (a jornada do pesquisador), `ed70232` (o `medir_vista --cadeia`), `61edf72` (só do
motor: a curva da sonda em pedaços) e `0d7ddf2` (a fila das pesadas). O que ficou:

- **A jornada de ponta a ponta** (`tests/test_gui_jornada.py`), pelos gestos do usuário: Ctrl+O, o duplo clique na
  corrente da árvore, "Adicionar etapa: correção de sonda" no inspetor, Ctrl+E e a captura inteira na barra do
  espectro. O espectro bate com o `adc_tool --fft --sondas-dir` (pelo `.mat`, a precisão inteira): as frequências a
  1e-12 e os dB a 1e-7. Em cada tom, a diferença para o espectro sem a sonda é o que o polo dela tira (0,4 dB em 9
  kHz, 4,4 dB em 40 kHz), a 0,05 dB. Salvo e reaberto, o projeto dá o mesmo espectro, bit a bit.
- **O G1 com a cadeia** (`medir_vista --cadeia`; no conjunto de desempenho,
  `test_g1_oito_faixas_com_a_cadeia_durante_e_depois_das_materializacoes`): os 8 traços com a correção de sonda e um
  passa-altas de 2 kHz. Sem tela, **durante as materializações, p95 de 7,5 a 9,7 ms; depois, de 10,8 a 12,2 ms**
  (antes: 22 a 33 ms durante).
- **O que engasgava o desenho durante as materializações** (medido por quadro: o tempo de CPU da thread da
  interface era um terço do de parede, com ~1 000 trocas de contexto voluntárias no percurso, contra ~30 sem a
  cadeia; o `strace` mostrou as esperas no mutex e na condição do GIL, de 5 ms cada):
  - **duas contas pesadas ao mesmo tempo** (as materializações dos dois canais, e as medidas da janela visível, que
    refaziam a cadeia nos 12 M amostras de cada traço) disputavam o GIL com a interface: cada chamada ao Qt que o
    solta dava a vez a um trabalhador. Com os traços prontos e as contas ao fundo, duas juntas davam p95 de 38 a 40
    ms; uma de cada vez, 11 ms, o mesmo que sem nenhuma. **A fila das pesadas** (`GerenciadorDeTarefas.iniciar(...,
    pesada=True)`): uma de cada vez, ao lado das outras tarefas. As materializações vão para ela, e as medidas de um
    traço transformado numa região maior que a prévia também (são uma conta do tamanho da materialização); as que
    esperam dizem "na fila" no chip e no painel de tarefas (`Tarefa.comecou`);
  - **o PCHIP do SciPy não solta o GIL:** a curva da sonda em 2 Mi bins prendia as outras threads por ~33 ms
    seguidos. Em pedaços de 64 Ki pontos (`sonda.PONTOS_POR_AVALIACAO`), bit a bit o mesmo resultado.
  - **Descartado pelas medidas:** o intervalo de troca do GIL (1 ms não mudou nada), as páginas enormes do NumPy, a
    importação do SciPy, a coleta de lixo, as prévias e o `msync` (ele solta o GIL no Python 3.13).
- **Fica para depois:** o espectro e as vistas de mapa continuam no conjunto geral (com a vista de espectro aberta, a
  de tempo não é pintada); os 4 traços iguais de um canal medem a mesma cadeia 4 vezes.

O plano original:

- **O conteúdo:** a jornada do pesquisador num teste de ponta a ponta (abrir, plotar, ligar a correção de sonda,
  abrir o espectro, conferir com a CLI); o G1 medido de novo com a cadeia ligada; o plano e este arquivo em dia.
  **A tag v0.9** fica para o dono do projeto (nada vai ao GitHub sem ele pedir).

---

## 4d. Fase 3 em tarefas: Aquisição, a conexão

**Pronto quando** (o plano, seção 16, não dá um para a Fase 3; este é o daqui): a jornada da Aquisição roda com o
simulador e com a placa de verdade, pelo USB: achar a placa, conectar com a chave do aplicativo, ver a visão geral e
o diagnóstico, acertar o relógio, transferir uma captura, conferir o CRC e abri-la na Análise.

**O que já existe** (a F0.10): o agente com `versao` e `estado`, o `ClienteDoAgente` com o `TransporteLocal`, o
`EstadoDaPlaca.diagnostico()` e o simulador de 6 cenários, sobre uma árvore falsa, sem rede. Nenhuma dependência nova
ainda: o extra `placa` está no plano (seção 8.1), não no `pyproject.toml`.

**A ordem:** a F3.1 vem primeiro; a F3.2 depende dela. A F3.3 (depois da F3.1) e a F3.4 (a qualquer hora: só o
agente) são independentes entre si. A F3.5 precisa da F3.2 e da F3.3; a F3.6, da F3.4 e da F3.5; a F3.7 e a F3.8,
da F3.5. O servidor SSH do simulador nasce nos testes da F3.2 e cresce até a F3.9. A F3.10 fecha.

**Regras desta fase** (o plano, 4.3 e 11.1): tudo pelo SSH, sem abrir porta e sem instalar nada na placa; cada
comando rodado na placa vai para o registro de atividade; nada destrutivo sem confirmação, com o que vai acontecer
escrito no botão; senhas só no cofre do sistema. **As dependências novas** (asyncssh, zeroconf, pyserial, keyring e,
na F3.8, o pyte) **têm a permissão do usuário** (15/11/2026: "pode instalar tudo que você quiser" pelo projeto). As
mudanças no agente vão em commits só dele, como as do motor.

**A placa de verdade** está no USB do computador do usuário (seção 6): cada tarefa que fala com a placa é conferida
nela também, além do simulador. O cabo tem mau contato: a conexão que cai no meio é o caso comum, não o raro. O disco
dela é pequeno: o que for gravado lá para um teste sai depois de conferido.

### ☑ F3.1: o laço `asyncio`, as dependências e o job `placa`

- **Arquivos:** `scripts/sh_placa/laco.py` (a thread com o laço); `sh_analyzer_gui/servicos/placa.py` (a ponte
  para a interface); o extra `placa` no `pyproject.toml`; o job `placa` no `scripts/ci.sh`.
- **O conteúdo:**
  - o extra `placa` = asyncssh, zeroconf, pyserial e keyring, e o `gui-dev` passa a trazê-lo;
  - uma thread só para o laço `asyncio` (plano, 8.3). O `sh_placa` é `async` e não sabe do Qt. A ponte roda uma
    corrotina no laço e devolve o resultado (ou o erro) na thread da interface, por um sinal; uma chamada pode ser
    cancelada; ao fechar, o laço para e nenhuma thread fica;
  - o job `placa` no `ci.sh`: o agente, o `sh_placa` e o simulador, sem o Qt.
- **Os testes:** a ponte entrega o resultado e o erro na thread da interface, e cancela; fechar não deixa thread; a
  arquitetura confere que o `sh_placa` não importa o Qt nem a interface (a regra já existe).
- **Feito em 15/11/2026:**
  - **`sh_placa/laco.py`:** o `LacoAsyncio` (iniciar, submeter, parar) e a `Execucao`. **O fim de uma execução só
    chega quando a corrotina parou:** o futuro do `asyncio.run_coroutine_threadsafe` se dá por cancelado na hora do
    pedido, com a limpeza da corrotina ainda rodando, e uma transferência nova do mesmo arquivo começaria em cima da
    antiga. O `ao_terminar` é ligado no `submeter`, antes de a corrotina começar; uma falha no laço fora de uma
    execução vai para o log;
  - **`servicos/placa.py`:** a `Chamada` e o `ServicoDaPlaca`. **O estado da chamada só muda na thread da
    interface**, quando o aviso do laço chega, logo antes do `terminou` (a corrida do teste da fila das pesadas não
    acontece aqui). Os erros esperados (`ErroDaPlaca`, `OSError`, o tempo esgotado) ficam na chamada; outro é um
    defeito e vai para o relator. A thread nasce na primeira chamada e morre ao fechar a janela;
  - **o extra `placa`** no `pyproject.toml`, que o `gui-dev` traz; **o job `placa`** no `ci.sh` e no `ci.yml`, nos
    dois Pythons (3.10 e 3.13), sem o Qt; a regra nova da arquitetura: o asyncssh, o zeroconf, o pyserial e o
    keyring só no `sh_placa`;
  - **na placa de verdade:** o asyncssh pela thread do laço (a chave do computador, o `aes128-ctr`), o agente
    respondendo no Python 3.7.3 dela e o SFTP a 5,2 MB/s. Ela achou um defeito no diagnóstico (`0997175`): a PRU
    parada entre capturas é o normal, e a placa pronta aparecia como "não pronta para capturar";
  - **os testes:** `tests/test_sh_placa_laco.py` (8, sem o Qt) e `tests/test_gui_placa.py` (6).

### ☑ F3.2: a conexão SSH, as chaves e o registro de atividade

- **Arquivos:** `sh_placa/conexao.py`, `sh_placa/chaves.py` e `sh_placa/registro.py`; o `TransporteSSH` em
  `sh_placa/agente.py`; `tests/servidor_ssh.py` (um servidor do próprio asyncssh, com o agente de verdade sobre a
  árvore falsa do simulador).
- **O conteúdo** (AQ-02, AQ-03 e AQ-18; plano, 4.3 e 11.2):
  - a conexão por host ou IP, porta e usuário, com o salto (*ProxyJump*). Uma conexão reaproveitada, com um canal
    `exec` por chamada. O `TransporteSSH` tem a mesma interface do `TransporteLocal`, e o `ClienteDoAgente` não muda;
  - a chave `ed25519` do aplicativo, gerada na pasta de configuração (só o dono lê) e instalada na placa (o
    `ssh-copy-id`);
  - a impressão digital do host, confirmada na primeira vez (TOFU) e fixada. **Uma chave de host trocada bloqueia a
    conexão**, com a explicação;
  - a senha só no cofre do sistema (`keyring`), nunca num log nem na linha de comando;
  - o registro de atividade: cada comando rodado na placa, com a hora, a duração e o código de saída.
- **Os testes:** contra o servidor do teste: conectar com a senha e, depois, com a chave instalada; a chave do host
  trocada bloqueia; a senha não aparece no registro nem no log; cada comando está no registro; a conexão que cai vira
  um erro claro.
- **Feito em 15/11/2026:**
  - **`sh_placa/conexao.py`:** o `Destino` (host, porta, usuário e o salto) e a `ConexaoSSH`: uma conexão
    reaproveitada, um canal `exec` por comando, o `aes128-ctr` na frente. Nada do `~/.ssh` do usuário, do
    `ssh-agent` ou do `~/.ssh/config` entra. **Os erros são todos `ErroDaPlaca`**, com a mensagem pronta (a
    rede, a queda, o tempo, a senha, a chave do host); nenhum do asyncssh sai. **A queda no meio de um comando:** o
    `communicate` do asyncssh volta sem erro, sem o código nem o sinal; sem cuidar disso, um cabo que solta pareceria
    um comando morto por um sinal;
  - **a chave do host:** confirmada na primeira vez e fixada; a trocada bloqueia antes de qualquer senha ou chave
    sair (o servidor do teste confere que nenhuma autenticação começou), com as duas impressões e o que fazer. **Na
    placa de verdade,** a primeira impressão não era nenhuma das que o `ssh` do usuário conhecia: o asyncssh põe o
    RSA na frente. Agora a ordem é a do OpenSSH (o ED25519 primeiro), e a impressão é a do `ssh-keygen` da placa;
  - **`sh_placa/chaves.py`:** a chave `ed25519` do aplicativo (0600 desde o primeiro byte, numa pasta 0700), os hosts
    conhecidos no formato do `known_hosts` do OpenSSH (o terminal da F3.8 usa o mesmo arquivo) e o cofre de senhas
    (`keyring`; sem cofre no sistema, explica e segue sem guardar);
  - **`sh_placa/registro.py`:** cada comando com a hora, a duração, o código ou o motivo de não ter terminado, e os
    fatos da conexão;
  - **o agente pelo stdin** (o `TransporteSSH`): o código do agente do aplicativo vai no `python3 -`, e a placa não
    precisa tê-lo (o plano, 11.2, mudou com isso; o agente ganhou o padrão `~/firmware` lido pelo stdin, `3d68c49`).
    O `ClienteDoAgente` ficou `async`;
  - **`tests/servidor_ssh.py`:** um servidor do asyncssh com o agente de verdade sobre a placa simulada, a senha e as
    chaves do `authorized_keys` do home falso, a troca da chave de host, a queda e o salto;
  - **na placa de verdade:** a primeira conexão com a senha (0,38 s), a chave instalada, a segunda só com a chave
    (0,35 s), o `versao` e o `estado` pelo stdin (~0,5 s cada) e o diagnóstico sem nada. A chave de teste saiu da placa
    depois;
  - **os testes:** `tests/test_sh_placa_ssh.py` (15).

### ☑ F3.3: a descoberta das placas

- **Arquivos:** `sh_placa/descoberta.py`; as placas conhecidas nas preferências.
- **O conteúdo** (AQ-01; plano, 11.3):
  - **o USB:** a porta serial do gadget (`pyserial`, pelo VID:PID e pelo nº de série) e a sondagem da porta 22 em
    192.168.7.2 e 192.168.6.2;
  - **a LAN:** o mDNS (`zeroconf`): `beaglebone.local`, ou o nome que a placa anuncia;
  - **a WAN:** o host, a porta e o salto que o usuário informa;
  - **o simulador**, sempre na lista;
  - cada placa com o estado (conectada, disponível, vista há…), o caminho e a latência. As conhecidas ficam lembradas
    pelo nº de série da EEPROM (o mesmo do cabeçalho v8).
- **Os testes:** com portas seriais, respostas de mDNS e uma porta TCP falsas; a mesma placa achada por dois caminhos
  aparece uma vez.
- **Do laboratório:** o VID:PID do gadget e os IPs vêm da F0.2 (seção 6).
- **Feito em 15/11/2026:**
  - **`sh_placa/descoberta.py`:** as fontes (o USB, o mDNS, as conhecidas e o simulador) rodam juntas, e uma que
    falha não derruba as outras (`Descoberta.falhas` diz qual, para a interface). **A sonda** abre a porta, mede a
    latência, confere a saudação do SSH e lê a chave de host com uma troca de chaves, sem autenticar. O mesmo
    endereço é sondado uma vez por varredura (o USB e o mDNS acham os mesmos IPs), e a chave fica guardada por 2 min
    enquanto a saudação não muda: a placa, com um núcleo só, não refaz a troca de chaves a cada varredura;
  - **a mesma placa aparece uma vez:** os achados se juntam pelo nº de série, pela chave de host e pelo endereço; com
    um gadget só no USB, os IPs do USB são dele, a não ser que uma conhecida diga que a chave neles é de outra placa.
    Cada endereço vira um caminho, com os detalhes juntos ("USB (RNDIS) · beaglebone.local (mDNS)") e a menor
    latência; o melhor primeiro (o USB, o IP da rede do sistema, a latência);
  - **os estados:** disponível, só na serial (o gadget no USB e o SSH ainda sem responder: a placa ligando), pelo
    salto (não sondada: a conexão com o salto é do usuário), ausente (conhecida, com a hora da última vez) e o
    simulador;
  - **as conhecidas** (`sh_placa/conhecidas.py`, nas preferências como JSON): o nº de série, o nome, a chave de host e
    os 5 últimos endereços. **Um endereço é de uma conhecida só se a chave de host for a dela** (o IP de uma rede com
    DHCP pode ser de outra placa hoje); a chave liga ao nº de série uma placa achada só pelo mDNS ou pela LAN. Uma
    gravada estragada fica de fora, e as outras valem;
  - **o `Destino`** saiu da `conexao.py` para `sh_placa/destino.py`, sem o asyncssh: as preferências o gravam sem ele;
  - **na placa de verdade** (pelo `LacoAsyncio`): uma placa só, com o nº de série da EEPROM, a chave ED25519 que o
    usuário conhece, a porta serial e os dois IPs (~1 ms); a segunda varredura não refez a troca de chaves e deu o
    nome da conhecida. A varredura leva ~1,5 s, quase tudo a espera do mDNS: a lista da F3.5 mostra a anterior
    enquanto a próxima roda. **O mDNS dá um IP ou outro a cada vez** (a F0.2 foi corrigida);
  - **os testes:** `tests/test_sh_placa_descoberta.py` (10), com portas seriais e respostas de mDNS falsas e o
    servidor SSH do teste nos endereços 127.0.0.1 e 127.0.0.2, como os dois IPs do USB (`tests/servidor_ssh.py`
    escuta em vários endereços, na mesma porta), e o das preferências em `tests/test_gui_configuracoes.py`.

### ☑ F3.4: o agente completo (commits só do agente)

- **Arquivos:** `firmware/agente/shan_agente.py`; `sh_placa/estado.py`; `tests/test_agente.py`.
- **O conteúdo** (plano, 11.2 e 11.9). O agente continua só lendo, na biblioteca padrão do Python 3.7:
  - **`saude`:** as conferências do diagnóstico, cada uma com o nível, o código e a correção sugerida:
    - o relógio e o NTP;
    - o firmware × a versão do aplicativo, e o `ler_adc` compilado;
    - a PRU0 e o protocolo;
    - a memória dos buffers no `/proc/cmdline` e no `/proc/iomem`;
    - os pinos;
    - os overlays e o áudio do HDMI no `uEnv.txt`;
    - o disco e os minutos de captura que cabem nele;
    - o sistema e as ferramentas;
  - **`capturas`:** os `.bin` da placa com o resumo do cabeçalho (o título, a taxa, os canais, a duração, a
    integridade) e o `resumo.csv` das pastas de coleta;
  - **`relogio`:** a hora da placa e se ela está sincronizada;
  - **`logs`:** as últimas linhas do `dmesg` e do `journalctl`, filtradas;
  - o esquema de cada resposta, versionado (`"protocolo": 1`).
- **Os testes:** cada conferência sobre a árvore falsa, inclusive os `uEnv.txt` estranhos; a sintaxe do Python 3.7;
  o `EstadoDaPlaca` lendo cada resposta.
- **Do laboratório:** a F0.2 diz o que a placa de verdade tem (os overlays, as ferramentas, a versão do Python).
- **Feito em 15/11/2026** (os commits do agente, `f4f462d` e `2754155`, só com ele e os testes dele):
  - **`saude`:** os fatos do `estado`, o `/boot/uEnv.txt`, os overlays carregados, os `.dtbo` da PRU e as
    ferramentas, e as **conferências**, cada uma com o nível, o código, o texto e a correção. O diagnóstico agora é
    da placa (a fonte de verdade da interface, da CLI e do `setup.sh`); o `sh_placa/estado.py` só junta as duas que
    só o computador faz: o relógio comparado com o dele e o firmware comparado com o do aplicativo. As conferências:
    - **a PRU0:** ausente (com o overlay certo para o kernel que roda na correção), em outro remoteproc (um kernel
      que numera de outro jeito), outro núcleo no `remoteproc1`, parada com falha, outro firmware;
    - **o firmware:** não compilado, **compilado antes da última mudança do código** e **não instalado na PRU** (o
      `fw_pru.out` diferente do `/lib/firmware/am335x-pru0-fw`), como a `coleta/campanha.sh` confere; o protocolo da
      PRU vem do `memoria_pru.h` da pasta (o que a PRU escreve na memória só o root lê);
    - **a memória dos buffers** no boot de agora (`/proc/cmdline`) e no próximo (o `optargs` ou o `cmdline` do
      `uEnv.txt`: na placa de verdade, o `mem=496M` está no `optargs`). **O `/proc/iomem` sem sudo tem os endereços
      zerados:** o agente só o usa como root, e o `ler_adc` o confere a cada captura;
    - **o áudio do HDMI** carregado (o McASP0 nos pinos da PRU) ou não desligado no `uEnv.txt`; o overlay da PRU do
      `uEnv.txt` (o UIO, o de outro kernel, um que não existe, os overlays desligados); o kernel trocado;
    - os pinos, o disco, a temperatura, a carga, a memória e as ferramentas (com o `apt install` dos pacotes, os do
      `dpkg -S` da placa);
  - **`capturas`:** os `.bin` da pasta do firmware e das coletas (até 3 níveis), com o resumo do cabeçalho de v1 a v9:
    o título, a taxa, os canais, a duração, a integridade, o CRC e se o arquivo tem o tamanho que o cabeçalho diz. **O
    agente lê o cabeçalho sozinho** (a placa não tem o NumPy), e `tests/test_agente.py` confere, versão a versão, que
    o resumo é o que o motor lê. E os manifestos das coletas (`resumo.csv`, `pontos_coletados.csv`);
  - **`relogio`:** o `adjtimex`, o mesmo do `relogio_sincronizado` do cabeçalho, e há quanto tempo o processo roda.
    **A diferença para o computador fica entre dois limites** (`sh_placa/estado.py`): a hora foi lida antes de a
    resposta chegar, e o processo começou depois do pedido. Na placa, ±0,03 s, cercando a de um pingue-pongue num
    canal só; a hora da chegada sozinha dava 35 a 70 ms a menos. O "Corrigir" da F3.6 confere com ela;
  - **`logs`:** o `/dev/kmsg` (a PRU, os pinos, o firmware e os erros) e o diário do systemd, **filtrado pelos
    índices dele** (o `sudo`, por onde passam o `ler_adc` e o `setup.sh`, e os erros): o systemd 241 da imagem não
    tem o `--grep`, e filtrar as ~3500 linhas de um boot no agente levava 3,4 s; assim, 0,7 s;
  - **o tempo de cada comando na placa** (o agente compilado pelo stdin a cada chamada; o Python vazio leva 0,2 s):
    de 0,42 s (`versao`) a 0,67 s (`logs`). O `ctypes.util`, o `subprocess` e o `csv` são importados só onde se usam;
  - **o `sh_placa/estado.py`** lê cada resposta: `EstadoDaPlaca` (o estado; com a saúde, o diagnóstico),
    `RelogioDaPlaca`, `CapturasDaPlaca` (com a integridade de cada captura em frases curtas) e `LogsDaPlaca`. O
    `ClienteDoAgente` ganhou a `saude`, as `capturas`, o `relogio` e os `logs`. Pedir o diagnóstico ao `estado` é um
    erro de quem chama, e não uma lista vazia que pareceria uma placa boa (achou o teste da F3.2 que fazia isso);
  - **o simulador** (`7bd1c08`) tem a árvore da placa de verdade (a imagem Buster, o kernel 4.19, o `uEnv.txt` dela,
    os overlays, o `/lib/firmware`, o `/dev/kmsg` e um diário falso) e três cenários novos: o firmware da PRU de outra
    compilação, o áudio do HDMI ligado e a placa sem o overlay da PRU. **As duas `.bin` dele continuam "SHAN" e
    zeros**, e o agente as lista com o cabeçalho corrompido: a F3.9 as troca pelas sintéticas;
  - **na placa de verdade:** pela `ConexaoSSH`, a saúde diz só o relógio sem NTP (no USB, sem internet) e o firmware
    de outra versão do aplicativo, e a placa está pronta para capturar; os logs mostram cada captura (o `sudo` do
    `ler_adc`, a PRU ligada e parada);
  - **os testes:** `tests/test_agente.py` (70) e `tests/test_sh_placa.py`.

### ☑ F3.5: a área de Aquisição e a lista de placas

- **Arquivos:** `areas/aquisicao/` (a área, a lista de placas e o diálogo de conectar); a área na barra superior,
  com o estado da placa.
- **O conteúdo** (o B1; plano, 9.1, 11.3 e 13.2):
  - a navegação lateral do B1: Visão geral, Capturar (a Fase 4), Arquivos, Terminal, Diagnóstico e Manutenção (a
    Fase 6). As que ainda não existem dizem quando chegam;
  - a lista de placas da F3.3, com conectar e desconectar;
  - o diálogo de conectar (host, porta, usuário, salto). Na primeira conexão:
    1. a impressão digital, para confirmar;
    2. a chave do aplicativo, instalada;
    3. a sugestão de trocar a senha padrão;
    4. a pergunta sobre acertar o relógio a cada conexão;
  - a qualidade do enlace ao conectar: a latência e a vazão num teste curto;
  - o estado da placa na barra superior.
- **Os testes:** com o simulador: a lista, conectar, a primeira conexão inteira, e a chave de host trocada mostrada
  como bloqueio.
- **Feito em 16/11/2026:**
  - **a janela em áreas:** a Análise numa `QMainWindow` própria (o Estúdio, `janela.estudio`), com os painéis
    dela; a Aquisição ocupa a janela inteira, e voltar à Análise traz os painéis como estavam. **Os atalhos da
    Análise só valem com ela à vista** (Ctrl+E, Ctrl+W, Delete, Ctrl+B/I/J moram no Estúdio, e o Qt não dispara o
    atalho de uma ação escondida), e a paleta só os oferece lá. Abrir uma captura ou um projeto, de qualquer área,
    leva à Análise. A barra de status tem a parte de cada área. O layout salvo é o do Estúdio, no mesmo formato;
  - **`servicos/conexao_da_placa.py`, a placa conectada** (sem a tela, testada sozinha): os estados (desconectada,
    conectando, confirmar o host, pedir a senha, bloqueada, conectada, reconectando, falhou), um só lugar que a área,
    o chip e a barra de status leem. **A impressão digital espera o usuário** por um futuro do laço, respondido pelo
    `LacoAsyncio.agendar`; a chave de uma placa conhecida, por outro endereço (o outro IP do USB), passa sem perguntar,
    e o registro diz por quê. **A senha:** a do cofre primeiro, uma vez por conta; o salto pede a dele (o
    `ErroDeAutenticacao` diz quem recusou). A chave do aplicativo é instalada só se o usuário quis, e a senha vai ao
    cofre só se ele pediu. **A queda:** tenta de novo sozinha por ~1 min, com esperas crescentes; a chave trocada e a
    senha recusada param na hora. Depois de conectar: a placa lembrada pelo nº de série, o resumo da primeira conexão
    e a medida do enlace. O simulador conecta pelo `TransporteLocal` (a F3.9 o põe atrás de um SSH);
  - **a janela abre sem a rede da placa:** o asyncssh, o zeroconf, o pyserial e o keyring custam ~0,7 s para
    importar e entram no laço da placa, na primeira busca ou conexão. Os erros da conexão foram para um módulo leve
    (`sh_placa/erros.py`) para a interface reconhecê-los pelo tipo; a regra nova da arquitetura confere num processo
    novo;
  - **a área (`areas/aquisicao/`), o B1:** a barra lateral com o cartão da placa (o estado, o nº de série, o caminho
    e o enlace; e o próximo passo quando algo deu errado: "Responder", "Ver", "Tentar de novo"), as seções, **a
    lista de placas** (o ponto do estado, o nome e, à direita, "USB", "LAN", "conectada", "vista há 3 h",
    "demonstração"; um clique conecta, o menu de contexto conecta por outro caminho e esquece uma conhecida; a lista
    só se refaz quando algo que se vê mudou), "Conectar por IP…" e "Desconectar". **A busca roda só com a área à
    vista**, a cada 5 s (30 s com uma placa conectada: cada sondagem é uma conexão no SSH dela). As seções que ainda
    não existem dizem o que vão ter e em que versão chegam;
  - **a visão geral desta etapa:** o cabeçalho da placa (o nome, o nº de série, o sistema, o kernel e o firmware) e o
    enlace (o caminho, a latência, a vazão contra os 1,6 MB/s que a saída contínua a 400 kS/s pede, desde quando e as
    quedas). O resto (os indicadores, a saúde, as capturas, o registro) é a F3.6;
  - **o diálogo da conexão** abre só quando há o que perguntar (conectar a uma placa conhecida da lista não abre
    nada): o endereço (aceita `debian@host:porta`, com o salto), a impressão digital com o comando para conferi-la,
    a senha (com "Instalar a chave do aplicativo" marcado e "Guardar no cofre" desmarcado), o bloqueio (as duas
    impressões; "Esquecer a chave antiga" só depois de o usuário dizer que conferiu na placa, e a impressão nova
    aparece para confirmar), a falha e o resumo da primeira conexão (a impressão guardada, a chave instalada, **a
    sugestão de trocar a senha padrão** com o `passwd` e **a pergunta do relógio**, lembrada com a placa em
    `PlacaConhecida.acertar_relogio`; quem acerta é a F3.6). **Fechar (Esc) é a resposta segura** de cada página:
    não confiar, cancelar, deixar o relógio para a próxima vez. O diálogo tem a altura da página da vez;
  - **o chip da barra superior** com o estado da placa (sem placa, conectando, conectada, reconectando, bloqueada,
    sem conexão), abreviado no meio para não empurrar a busca; um clique leva à Aquisição;
  - **no `sh_placa`:** `ConexaoSSH.medir_enlace` (a latência pela mediana de 5 ecos de um `cat` que já roda, e a
    vazão pelos zeros do `head`, contada do primeiro bloco; os dois no registro), `Destino.de_texto` (o endereço
    digitado), e o simulador nunca se junta a uma placa de verdade na lista (o nº de série dele é inventado, e o
    servidor SSH dos testes roda a árvore dele);
  - **na placa de verdade** (pelo USB, com uma configuração e uma chave temporárias, que saíram da placa depois): a
    busca achou a placa em 2,1 s, uma linha só (o USB ECM, o RNDIS com o mDNS e a porta serial), com o nº de série da
    EEPROM (`2017BBBK382A`); a primeira conexão inteira (a impressão que o usuário conhece, a senha, a chave
    instalada, a senha padrão apontada, o relógio perguntado) em 2,5 s fora o tempo das respostas; o enlace com
    1,1 ms e 6,6 MB/s; a segunda conexão só com a chave, sem diálogo, em 1,2 s; e o outro IP do USB aceito sem
    perguntar, em 1,6 s. **A placa ainda usa a senha padrão da imagem**, e a sugestão de trocá-la aparece;
  - **os testes:** `tests/test_gui_conexao_da_placa.py` (7: o serviço, sem a tela, com o salto, a queda e a volta),
    `tests/test_gui_aquisicao.py` (4: a tela, com cliques na lista e no diálogo) e `tests/placas_de_teste.py` (os
    servidores SSH do teste num laço próprio, como uma placa respondendo fora do laço da interface).

### ☑ F3.6: a visão geral e o diagnóstico

- **Arquivos:** `areas/aquisicao/visao_geral.py` e `areas/aquisicao/diagnostico.py`.
- **O conteúdo** (AQ-04, AQ-05 para ver, AQ-14; plano, 11.4 e 11.9):
  - **a visão geral do B1:**
    - o cabeçalho da placa: o modelo, o nº de série, o sistema, o kernel, e o firmware (e se é o do aplicativo);
    - os indicadores: relógio, PRU, cartão, processador e placa de aquisição;
    - a saúde resumida, as capturas na placa e o registro de atividade;
  - **o diagnóstico** item a item, só lendo, com os dois "Corrigir" simples:
    - **o relógio**, acertado pelo do computador, com a permissão lembrada;
    - **os pinos**, com o `config-pin`, como o `setup.sh`;
    - o sudo vai pelo askpass temporário em `/dev/shm` (plano, 11.2). "Ver o comando" mostra o que vai rodar, e o
      botão diz o que vai acontecer;
  - o relatório de diagnóstico em Markdown, para copiar ou salvar (o caderno chega na Fase 4).
- **Os testes:** cada cenário do simulador dá os itens certos; o "Corrigir" roda o comando certo, uma vez, e o
  registra; nada roda sem confirmação; a senha do sudo não aparece em lugar nenhum.
- **Feito em 16/11/2026:**
  - **no `sh_placa`, sem Qt** (a interface e uma futura CLI usam o mesmo):
    - **`correcoes.py`, as duas correções simples.** **O sudo pelo askpass:** a senha vai pelo stdin para um
      diretório em `/dev/shm` (a RAM), só do usuário; o `sudo -A -v` a lê uma vez, o arquivo some logo depois, o
      comando de root roda com `sudo -n` e, no fim, `sudo -k`. A senha nunca está num argumento, no registro ou no
      log; a errada é uma tentativa só (o askpass se apaga ao ser lido). **O relógio com a precisão do enlace:** o
      Python de root avisa que está pronto, e só então o computador manda a hora dele (mais a meia ida e volta); a
      placa conta, pelo `CLOCK_BOOTTIME`, o tempo até acertar com o `clock_settime`. **Os pinos** pelo `config-pin`,
      sem sudo (o pinmux é do grupo `gpio`, e o `debian` está nele), na ordem do `setup.sh` (contrato conferido);
    - **`diagnostico.py`, o diagnóstico item a item:** as linhas da tabela 11.9 do plano, cada uma com o pior nível,
      os fatos lidos (um item "ok" também diz por quê) e o "Corrigir" que cabe; todo código que o agente emite tem
      um item (conferido), e um desconhecido vai para "Outras conferências". **O relatório** em Markdown;
    - **`versao.py`, o firmware comparado pelo código:** o da placa é o deste aplicativo se o `firmware/` do commit
      da versão dela é o de agora (sem o `agente/`, que vai pelo stdin). Comparar os textos do `git describe`
      acusava "outra versão" a cada commit da interface: o aviso da F3.4 na placa de verdade era falso;
  - **`servicos/saude_da_placa.py`:** o que se sabe da placa conectada (a saúde, que chega com a conexão, as capturas,
    o firmware comparado), a atividade ao vivo (o registro de atividade, na thread da interface) e as correções, com
    a senha do sudo da sessão, do cofre ou a que o usuário dá. **Uma coisa por vez na placa:** o enlace, depois as
    capturas, depois o relógio a cada conexão (a vazão caía pela metade com a leitura das capturas junto). **O relógio
    a cada conexão** roda sozinho com a permissão lembrada com a placa (a pergunta da primeira conexão); sem a senha
    do sudo, fica o aviso, e nada roda;
  - **a visão geral do B1:** o cabeçalho (o firmware "o deste aplicativo" ou não), os cinco indicadores (o relógio
    com a incerteza e quando foi acertado, a PRU0, o cartão com a barra e os minutos que cabem, o processador, a
    última conferência do ADC na placa), a saúde resumida com o "Corrigir…" e o "Acertar…", as capturas na placa
    com a integridade de cada uma, e a atividade;
  - **o diagnóstico item a item:** cada item com o que foi lido, os problemas e a correção, o "Ver o comando" e o
    "Corrigir"; "Copiar o relatório" e "Salvar o relatório…";
  - **o diálogo da correção:** o que vai acontecer, o comando exato, o botão que diz a ação ("Pôr P9_28 e P9_31 no
    modo da PRU", "Acertar o relógio"), a senha do sudo só quando a sessão e o cofre não a têm (ou a placa a
    recusou) e, no relógio, a permissão de acertar a cada conexão. O resultado vai para um toast, inclusive o do
    relógio acertado sozinho;
  - **o chip da barra superior** fica em atenção com a placa conectada e não pronta para capturar;
  - **na placa de verdade:** o relógio estava **+1,14 s adiantado** (era +0,5 s na véspera: deriva ~2,6 s por dia
    sem NTP) e ficou dentro do limite da medida (±0,05 s); a senha errada do sudo, recusada sem rodar nada; a
    `/dev/shm` limpa e a credencial esquecida no fim; o `config-pin` nos quatro pinos; o firmware dela é o deste
    aplicativo; a placa não tem sensor de temperatura (o processador mostra a carga); o diagnóstico diz "Pronta
    para capturar", com o relógio sem NTP como informação;
  - **os testes:** `tests/test_sh_placa_correcoes.py` (4), `tests/test_sh_placa_diagnostico.py` (16, com cada
    cenário), `tests/test_gui_saude_da_placa.py` (4), `tests/test_gui_diagnostico.py` (7: os itens na tela, o
    "Corrigir" só depois de confirmar e uma vez, o relógio pedindo a senha e ela em lugar nenhum, o relatório); o
    servidor SSH do teste ganhou um sudo e um `config-pin` falsos.

### ☑ F3.7: os arquivos e a transferência

- **Arquivos:** `sh_placa/sftp.py` (a fila); `areas/aquisicao/arquivos.py`.
- **O conteúdo** (AQ-06 e AQ-07; plano, 11.7):
  - o navegador da placa, com o resumo do cabeçalho de cada `.bin` (pelo agente) e o `resumo.csv` das coletas;
  - **a fila de transferência:**
    - várias requisições SFTP em paralelo;
    - a retomada do ponto onde parou;
    - a vazão e o tempo restante;
    - o destino padrão na pasta da sessão do dia (`$DADOS/lab/AAAA-MM-DD/`);
  - **a conferência:** o `crc32_amostras` na v9 (`api.conferir_integridade`); nas versões antigas, o SHA-256 dos
    dois lados. "Apagar da placa" só para o conferido, e com confirmação;
  - **"Abrir na Análise"** (a cópia local) e **"Abrir no gerenciador de arquivos":**
    - no Linux, `gio mount sftp://` ou o `sshfs`;
    - no Windows, o SSHFS-Win, se houver; senão, o aviso.
- **Os testes:** uma transferência interrompida e retomada dá o arquivo idêntico; o CRC conferido; o "apagar"
  desligado antes da conferência; a interface sem travar durante a transferência.
- **Feito em 16/11/2026:**
  - **a pergunta do usuário** ("a PRU usa a mesma RAM do processador: uma transferência pode atrapalhar a medição?"),
    **medida na placa de verdade**, com a tomada no canal 1: capturas de 21 s a 400 kS/s alternando sem carga e com a
    carga de uma transferência ao lado (o cartão lido com `O_DIRECT`, a cifra e o USB), de três ao mesmo tempo e de
    três fluxos de cifra (o único núcleo saturado, 4,5 MB/s). **Em todas:** a folga mínima da PRU igual (18 ciclos,
    90 ns), nenhuma amostra atrasada, nenhum buffer sobrescrito, nenhum quadro com ruído no SDO, o mesmo piso de ruído
    entre os picos (0,317 µV/√Hz de 9 a 150 kHz) e o mesmo ruído de 150 a 200 kHz (0,070 mV), sem raias nos múltiplos
    de 8 kHz (os microquadros do USB). A emissão da rede da casa de 9 a 150 kHz mudou de 0,9 a 9,4 mV entre as
    capturas, com e sem carga (os aparelhos ligando e desligando): por isso a comparação é pelo piso. **Por quê:** a
    PRU grava na memória reservada sem esperar o ARM, e o `ler_adc` tem ~2,6 s para gravar cada buffer de 2 MiB.
    **Mesmo assim, a fila espera as capturas** (o `pgrep -x ler_adc` no começo de cada arquivo e a cada 10 s): custa
    pouco e cobre o que o teste não cobriu (o cartão cheio, capturas longas, outras taxas, a saída contínua);
  - **`sh_placa/sftp.py`:** baixar pelo SFTP com 8 pedidos de 256 KiB em voo (5,2 MiB/s na placa, o teto da cifra;
    um por vez, 4,1), num `.parcial` ao lado do destino, **com a retomada** se o arquivo na placa é o mesmo (o tamanho
    e a data) e, no fim, a data da placa; a conferência (o CRC das amostras da v9 contra o do cabeçalho; até a v8, o
    SHA-256 dos dois lados); o apagar pelo SFTP; o índice das cópias no computador (`copias.json`), entre as sessões;
    a origem é a placa ou o simulador (o disco deste computador), com a mesma interface;
  - **`servicos/transferencias.py`:** a fila (um arquivo por vez; os blocos dele em paralelo), a vazão e o tempo que
    falta, e **a queda do cabo**: o item fica interrompido, e quando a mesma placa volta a fila continua sozinha, do
    ponto em que parou. Outra placa não herda a fila;
  - **a seção Arquivos:** as capturas com o resumo do cabeçalho e onde cada uma está (só na placa, na fila,
    baixando, no computador, a cópia corrompida), as coletas com o `resumo.csv`, a fila com a vazão e o tempo que
    falta, "Transferir as novas", "Abrir na Análise", "Mostrar a pasta", "Mudar o destino…" e **"Apagar da placa…",
    só para o conferido e depois de confirmar**; "Abrir no gerenciador de arquivos" pelo `sftp://` no Linux (o
    Nautilus e o Dolphin falam SFTP), pelo SSHFS-Win no Windows, ou o aviso. A visão geral mostra o mesmo estado na
    tabela das capturas, como no B1;
  - **o destino** é a pasta da sessão do dia, `$DADOS/lab/AAAA-MM-DD` (`preferencias.pasta_da_sessao`), a mesma do
    `lab trazer`; sem o `$DADOS` nem uma pasta escolhida, a do `sessao_lab.sh` (`~/Documents/sh-analyzer-data`);
  - **na placa de verdade:** uma captura de 2 blocos (4 MiB) transferida e conferida pelo CRC das amostras em 1,1 s,
    aberta na Análise e apagada da placa (a cópia fica); uma transferência de 32 MiB cancelada no meio e retomada de
    10,2 MiB; o SHA-256 conferido dos dois lados;
  - **os testes:** `tests/test_sh_placa_sftp.py` (7: o arquivo idêntico, a queda e a retomada, o arquivo que mudou,
    a v9 pelo CRC e a v8 pelo SHA-256, a cópia corrompida, a espera da captura, o apagar e o índice) e
    `tests/test_gui_arquivos.py` (6: transferir e abrir, o apagar só conferido e confirmado, a queda e a volta
    sozinha, a interface sem travar, a fila esperando a captura, o gerenciador de arquivos). O servidor SSH do teste
    ganhou o SFTP e uma RAM própria para o sudo.

### ☑ F3.8: o terminal

- **Arquivos:** `componentes/terminal.py` (o widget, com o `pyte`); `areas/aquisicao/terminal.py`; o `pyte` no
  extra `placa`.
- **O conteúdo** (AQ-08; plano, 11.8):
  - o emulador VT100 do `pyte`, pintado num widget próprio com o tema e a fonte mono, sobre um PTY no SSH;
  - abas, rolagem com busca, copiar e colar;
  - a gravação em `$DIA/terminal_bbb.txt`, como o `lab ssh`;
  - os atalhos de comandos: clicar escreve o comando, e o Enter é do usuário;
  - "Abrir no terminal do sistema", com o `ssh` pronto: o GNOME Terminal ou o Konsole; no Windows, o Windows
    Terminal.
- **Os testes:** as sequências de escape mais comuns na tela; o tamanho do widget chega ao PTY; a gravação; o atalho
  não aperta o Enter.
- **Feito em 16/11/2026:**
  - **`sh_placa/terminal.py`:** o shell num PTY da placa, num canal da conexão de agora
    (`ConexaoSSH.abrir_terminal`); a saída em bytes, acrescentada ao arquivo da gravação com um cabeçalho por sessão
    (como o `script -a` do `lab ssh`); o tamanho e o fechar pedidos enquanto o canal ainda abre valem; o código de
    saída é esperado depois do fim da saída (o OpenSSH manda o EOF antes do `exit-status`); a abertura e o fechamento
    vão para o registro de atividade; e o `ssh` do terminal do sistema, com a chave e o `known_hosts` do aplicativo
    (e o salto pelo `ProxyCommand`);
  - **`componentes/terminal.py`:** a `TelaDeTerminal`, um emulador xterm sobre a tela do `pyte`, que ganhou a
    rolagem (10 000 linhas; o `ESC[3J` do `clear` a apaga), a tela alternativa (o `less`, o `vim`) e um
    redimensionamento que guarda o prompt (ao encolher, saem primeiro as linhas vazias de baixo; ao crescer, as do
    histórico voltam). A saída é interpretada em fatias de 8 ms por volta do laço da interface, e a fila cheia pula o
    começo com um aviso (a gravação tem tudo). As teclas do xterm (o modo do cursor da aplicação, os modificadores,
    o Alt como `ESC`, o AltGr do Windows); o Ctrl+letra vai para a placa mesmo quando a janela tem um atalho com ela;
    a seleção por caractere, palavra e linha, a do X11, o colar com o *bracketed paste*, a busca dando a volta. As 16
    cores da ANSI entraram nos tokens do tema, com o contraste de texto conferido nos dois;
  - **a seção Terminal:** as abas (a primeira abre sozinha; Ctrl+Shift+T, Ctrl+Shift+W, Ctrl+PgUp/PgDn), a busca, os
    atalhos (clicar escreve, o Enter é de quem lê), "Mostrar a gravação" e "Abrir no terminal do sistema" (o
    terminal da área de trabalho: o do COSMIC, o GNOME Terminal, o Konsole, o do `x-terminal-emulator` pelo programa
    que ele é; o Windows Terminal; o Terminal do macOS; sem nenhum, o comando vai para a área de transferência). **A
    queda do cabo:** a aba reabre sozinha quando a placa volta. **Fechar uma aba com o `ler_adc` rodando pergunta
    antes.** Cada aba grava no seu arquivo (`terminal_bbb.txt`, `terminal_bbb_2.txt`…), para as saídas não se
    misturarem;
  - **na placa de verdade** (pela tela, sem tela): o prompt em 0,9 s, com o título que o bash dá à aba; o PTY no
    tamanho da tela (112 × 39) e no novo depois de encolher a janela (79 × 29, o `SIGWINCH`); **os oito atalhos
    rodados de verdade**, inclusive o `coletar.sh conferir` (o `sudo` sem eco da senha, a captura íntegra, os símbolos
    e as cores dele; a `conferencia.bin` do teste apagada depois); o `less` na tela alternativa e a principal de
    volta; o Ctrl+C parando o `sleep` em 0,06 s (`$?` 130); o `exit 3` com o código 3 pelo OpenSSH e o "Reabrir"; a
    gravação na pasta do dia; o `ssh` do terminal do sistema entrando com a chave e o `known_hosts` do aplicativo
    (rodado aqui, sem janela, com `BatchMode`). Os comandos do teste começaram com espaço (fora do histórico do
    bash), e a chave do teste saiu da placa;
  - **o que a placa mostrou:** a primeira aba pedia o PTY no tamanho de antes do layout (80 × 24) e o mudava logo
    depois; o registro e o cabeçalho da gravação ficavam com o errado. O shell abre agora na volta seguinte do laço;
  - **de passagem:** o servidor SSH do teste ganhou o shell num PTY; o `preexec_fn` que dava o terminal de controle
    travava no processo com threads dos testes da interface, e o `setsid --ctty` do util-linux faz o mesmo sem
    Python no filho;
  - **os testes:** `tests/test_sh_placa_terminal.py` (6), `tests/test_gui_terminal.py` (13: as sequências de escape
    pintadas na tela, conferidas pelos pixels; a rolagem, a tela alternativa, o redimensionamento, a busca, a seleção,
    as teclas, o colar, a fila que não trava) e `tests/test_gui_terminal_da_placa.py` (8: o tamanho que chega ao PTY,
    a gravação de cada aba, o atalho sem o Enter, a queda e a volta sozinha, o shell que sai, a pergunta com a
    captura rodando, o terminal do sistema). O `pyte` fica fora da partida da janela (`test_arquitetura`).

### ☑ F3.9: o simulador com os cenários

- **Arquivos:** `sh_placa/simulador.py` (a placa simulada) e `sh_placa/servidor_do_simulador.py` (o SSH dela, desde
  a F3.10); `tests/servidor_ssh.py`.
- **O conteúdo** (AQ-19; plano, 11.11):
  - o simulador como uma placa na lista: o mesmo protocolo, servido por SSH no próprio computador, com o agente de
    verdade sobre a árvore falsa;
  - os cenários:
    - a rede de 60 Hz com supraharmônicos;
    - o ADC mudo;
    - o disco cheio;
    - a conexão que cai no meio;
    - o firmware de outra versão;
    - o relógio errado;
  - as capturas sintéticas (as de `tests/capturas_sinteticas.py`) nos Arquivos;
  - o cenário escolhido pela interface.
- **Os testes:** cada cenário na visão geral e no diagnóstico; a conexão que cai no meio de uma transferência, e a
  retomada.
- **Feito em 16/11/2026:**
  - **o servidor** (o `ServidorDoSimulador`, hoje em `sh_placa/servidor_do_simulador.py`): o asyncssh no 127.0.0.1,
    numa porta livre, com o agente de verdade sobre a árvore falsa e o SFTP dela. A chave do host e a do aplicativo
    são geradas para ele (o `acesso()` devolve a chave e o `known_hosts`), e só a chave entra: ninguém daqui entra
    com uma senha conhecida. O sudo pede a senha da imagem, que a sessão conhece. O `ssh` sem comando é recusado com
    a explicação.
    O SFTP divide 5,2 MB/s entre os pedidos, como o USB; a conexão que cai derruba tudo na primeira leitura além de
    40 % de um arquivo, e de novo a cada 45 s. A pasta da placa simulada sai no `fechar`. O servidor dos testes
    (`tests/servidor_ssh.py`) virou uma subclasse dele: a senha, o terminal num PTY, o salto e a chave RSA;
  - **os cenários** (`sh_placa/cenarios.py`): os seis do plano, de uso, e os sete de configuração da F0.10, com o
    título e a descrição de cada um; o `montar_sistema_falso` monta a árvore de cada um;
  - **as capturas** (`sh_placa/capturas_simuladas.py`): no formato do firmware (v9, 2 canais a 400 kS/s, blocos de
    2²⁰ amostras, o CRC das amostras e o do cabeçalho), com a rede de 127 V e os supraharmônicos do plano (11.11). O
    espectro de uma delas, lido pelo motor, tem os picos em 60 Hz, 16, 40 e 72 kHz (o teste confere);
  - **o agente (v3):** a `ultima_captura` na saúde (o arquivo, o tamanho, a data e o cabeçalho, com os canais
    parados), e os avisos `adc_mudo` (todos os canais em 0) e `sinal_parado` (um canal com o mínimo igual ao
    máximo). Na árvore falsa, o cartão e o relógio são os da placa simulada (`/run/simulador/disco` e `relogio`), e
    o "Acertar…" grava ali (o relógio deste computador não é tocado);
  - **na interface:** o "Cenário" na visão geral, só com o simulador (trocar reconecta numa placa nova, e a de antes
    é apagada), e o "Conectar no cenário" no menu da placa, com o último lembrado; o cartão da lateral com o título
    do cenário; a "Placa de aquisição" da visão geral ("Com sinal", "ADC mudo", "Sinal parado") e o item do
    diagnóstico, pela captura mais recente; o relógio errado legível ("−2 dias e 5 h", "atrasado · sem NTP"). A
    seção Terminal explica que o simulador não tem terminal;
  - **as decisões:** as capturas ficam no `sh_placa`, e não as de `tests/capturas_sinteticas.py` (o aplicativo não
    leva os testes); só a chave entra; sem terminal (um shell nele seria o deste computador); só no Linux e no macOS
    (o agente e os scripts da árvore falsa precisam de um shell POSIX); a `OrigemLocal` saiu, porque o simulador
    passa pelo SFTP como a placa;
  - **na tela (sem tela), com o simulador de verdade** (os blocos do firmware, a vazão do USB): cada cenário conecta
    em 1,0 a 1,9 s, com a visão geral e o diagnóstico de cada um. No da conexão que cai, uma captura de 4 MiB foi
    interrompida em 40 %; a conexão voltou sozinha, e a retomada terminou com a cópia conferida pelo CRC, em 2,1 s;
  - **o que a tela mostrou:**
    - a queda no meio da transferência deixava tarefas sem dono ("Task exception was never retrieved"): o leitor
      paralelo do asyncssh não cancela as suas quando a leitura é cancelada. Agora cada bloco é lido em pedidos
      simples, cancelados e esperados juntos (o teste reproduz o caso);
    - **na placa:** o OpenSSH 7.9 da imagem não diz o tamanho máximo de um pedido (o `limits@openssh.com`), e o
      asyncssh pede 16 KiB. O pedido que volta com menos é pedido de novo (o teste também). A vazão ficou a mesma
      (seção 5);
    - o resumo do ADC mudo repetia o aviso: agora diz o que se viu ("os 2 canais em 0");
    - **fica para a F3.10:** a coluna Título dos Arquivos tem 40 px numa janela de 1 440 px (o painel das
      transferências no mínimo, e as outras colunas no tamanho delas), e o título só se lê no tooltip;
  - **o que fica para o instalador (F0.11):** o PyInstaller não leva o `firmware/agente/shan_agente.py`, que o
    `sh_placa.agente` procura ao lado do código, e o simulador usa o `sys.executable` como o `python3`. No aplicativo
    congelado, nem a placa nem o simulador rodariam o agente;
  - **os testes:** `tests/test_sh_placa_simulador.py` (12: só a chave e sem terminal, a pasta que sai, o Windows, a
    vazão, a queda no meio e a retomada, a leitura cancelada antes da queda, a queda periódica, o cartão cheio e o
    apagar, o relógio errado e o acerto, o ADC mudo, os títulos e o espectro) e `tests/test_gui_simulador.py` (9:
    cada cenário do plano na visão geral e no diagnóstico, o cenário escolhido e lembrado, o "Acertar…" e a queda no
    meio de uma transferência com a retomada); o pedido com menos bytes em `tests/test_sh_placa_sftp.py`.

### ☑ F3.10: o fechamento da Fase 3

- **O conteúdo:**
  - a jornada da Aquisição num teste de ponta a ponta, com o simulador por SSH: achar, conectar com a chave do
    aplicativo, ver a visão geral e o diagnóstico, corrigir o relógio, transferir uma captura, conferir o CRC e
    abri-la na Análise;
  - **na placa de verdade, com o usuário (no laboratório):** a mesma jornada pelo USB, com a vazão anotada na seção 5;
  - o plano e este arquivo em dia.
- **Feito em 16/11/2026:**
  - **a jornada com o simulador** (`tests/test_gui_jornada_aquisicao.py`, ~9 s): na janela e pelos gestos (o seletor
    da barra superior, o clique na lista, as seções da coluna da esquerda, os botões). O simulador aparece sozinho e
    conecta com um clique (a chave); a visão geral e o diagnóstico não têm nada a corrigir; no cenário do relógio
    errado, o "Acertar…" não pede a senha e deixa a diferença abaixo de 1 s; a captura de rede é transferida e
    conferida pelo CRC das amostras; e "Abrir na Análise" leva à Análise, onde a tensão é plotada (o duplo clique na
    árvore) e o espectro da captura inteira tem a rede no maior pico e os supraharmônicos da placa simulada (16, 40 e
    72 kHz) acima do piso;
  - **na placa de verdade**, a mesma jornada na janela, sem tela, com a configuração e os dados em pastas
    temporárias (o usuário a confere na tela). A captura é uma conferência (`coletar.sh conferir`, o canal 1 na
    tomada, 2 blocos), tirada pelo `ssh` como o terminal faria:
    - **em casa:** achada em 1,6 s; a primeira conexão (a impressão, a senha, a chave instalada) em 2,5 s; o relógio
      de +2,15 s acertado para −0,04 s; 4 MiB transferidos e conferidos pelo CRC em 0,91 s; na Análise, f₁ =
      59,98 Hz (127,5 V);
    - **no laboratório:** a placa desligada voltou com o relógio 3 h 07 atrasado (sem bateria) e os pinos da PRU no
      `default` (ela reiniciou). O diagnóstico disse "Não está pronta" pelos pinos e avisou o relógio; o "Acertar…"
      levou a diferença de −11 239 s a −0,04 s, e o `ler_adc` da conferência configurou os pinos. A tomada do
      laboratório (132 V, f₁ = 59,99 Hz) tem o H5 em −37,8 dBc, o H7 em −39,5 dBc e uma emissão em ~18 kHz
      (−54 dBc), com os múltiplos em 36, 54 e 72 kHz;
    - depois de cada uma, a chave do teste saiu do `authorized_keys` e a conferência saiu do cartão (a captura do
      usuário que estava lá ficou);
  - **os Arquivos:** o título da captura foi para baixo do nome do arquivo, na coluna que fica com a largura que
    sobra e nunca menos que a dos nomes. Numa coluna própria, ele ficava com 40 px numa janela de 1 440 px;
  - **o que a CI pegou:** desde a F3.9, o `simulador.py` importava o asyncssh, e o job `testes` (sem o extra
    `placa`) não importava mais os testes do agente e do diagnóstico. A placa simulada ficou no `simulador.py`, sem
    a rede, e o servidor SSH foi para o `servidor_do_simulador.py`; o `test_arquitetura` confere;
  - **o que o usuário pegou:** a interface morria em minutos com "Fatal Python error: none_dealloc: deallocating
    None". O PySide6 6.12.0 tira uma referência do None a cada chamada de um método do Qt sem retorno (até um
    `setWindowTitle`); da Python 3.12 em diante o None é imortal e nada acontece, mas o `ci.sh` interrompido tinha
    deixado o `.venv` na 3.10. O extra `gui` pede o 6.11 na 3.10 e na 3.11 (o 6.11.3 não tem o defeito, medido na
    janela inteira), e o `tests/test_gui_pyside.py` confere. A interface inteira passa na 3.10 com o 6.11.3
    (823 testes, 7 pulados, em 8 min 22 s). O bloco PEP 723 do `adc_tool.py` tem as mesmas duas linhas (o
    `uv run` na 3.10 instalava o 6.12.0 para a janela do matplotlib), e o `test_dependencias` compara todas as linhas
    de cada pacote, com os marcadores;
  - **de passagem:** cada processo do pytest deixava três pastas no `/tmp` (eram 2 520): agora saem no fim. E o
    teste da queda periódica do simulador esperava tempos fixos, que a máquina cheia passava.

---

## 4e. Fase 4 em tarefas: Aquisição, a captura

**Pronto quando** (o plano, seção 16): uma captura de 1 h vai direto para o computador, sem perder amostra, e abre na
Análise no fim. Conferido com o simulador num teste de ponta a ponta e na placa de verdade, pelo USB. **Tag v0.10**
(para o dono do projeto).

**O que já existe:** a conexão, o agente, a visão geral, os arquivos, a transferência conferida pelo CRC, o terminal e
o simulador por SSH (a Fase 3); o `ler_adc` grava no cartão, com o cabeçalho v9 (o CRC das amostras, o sinal de cada
canal) e os códigos de saída 0 a 5; a `pru_falsa` roda o `main` de verdade no computador
(`tests/test_ler_adc_captura.py`).

**A ordem:** a F4.1 (o firmware) vem primeiro e é validada em bancada antes de a interface depender dela. A F4.2 (o
lado do computador, sem Qt) precisa da F4.1; a F4.3 (o formulário) é independente das duas; a F4.4 (a captura na tela)
precisa da F4.2 e da F4.3. A F4.5 (o caderno) e a F4.6 (as rotinas pelo terminal) vêm depois da F4.3. A F4.7 fecha.

**Regras desta fase:** as do firmware em commits só dele, como as do motor e as do agente; o formato do `.bin` muda só
pelos dois lados juntos (o C e o `cabecalho.py`, com o `test_contrato_firmware`); a captura no computador é **byte a
byte** o arquivo que o `ler_adc` gravaria no cartão (o plano, 11.6). **O ao vivo anda de bloco em bloco:** a PRU
entrega blocos de 1 048 576 amostras (2,6 s a 400 kS/s; 21 s a 50 kS/s), e o `ler_adc` só os vê inteiros.

### ☑ F4.1: a saída contínua e o progresso em JSON no `ler_adc` (commits só do firmware)

- **Arquivos:** `firmware/ler_adc.c`; `tests/test_ler_adc_captura.py` (a `pru_falsa`); a ajuda, o guia do usuário e a
  arquitetura.
- **O conteúdo:**
  - **`-o -`:** o fluxo no stdout: o cabeçalho provisório (4 096 bytes), os blocos à medida que ficam prontos e, no
    fim, o cabeçalho final (4 096 bytes) depois do último bloco: quem recebe o põe no offset 0 e tira os 4 096 do fim,
    e o arquivo fica o do cartão. O texto do `ler_adc` (o resumo, os avisos, os detalhes) vai todo para o stderr: o
    fd 1 passa a ser o stderr, e o fluxo segue numa cópia do stdout de antes, e nada que imprima texto o corrompe.
    Recusado num terminal. O disco da saída fica "desconhecido" no cabeçalho (um pipe não tem disco);
  - **o código 6, "saída fechada":** quem recebe parou (o `EPIPE`: a conexão caiu, o computador fechou). A captura
    para, a PRU para, e o que chegou do outro lado é uma captura válida até o último bloco inteiro;
  - **`--progresso-json`:** uma linha JSON por bloco no stderr, com o evento (`inicio`, `bloco`, `fim`), os blocos, as
    amostras, o tempo, a gravação do bloco e os contadores de integridade; no fim, o código de saída e o CRC das
    amostras. A barra de progresso para humanos sai;
  - **validado em bancada:** a placa de verdade grava pelo SSH no computador; o arquivo remontado passa no
    `cabecalho.py` e no CRC das amostras; puxar o cabo (ou matar o `ssh`) dá o código 6 e a PRU parada.
- **Os testes:** o fluxo remontado = o arquivo do `-o arquivo` (os blocos, os contadores, o CRC das amostras); o texto
  nunca entra no fluxo; o leitor que fecha no meio dá o código 6 e a PRU parada; `-o -` num terminal é recusado; as
  linhas JSON (uma por bloco, os contadores do cabeçalho, o `fim` com o código).
- **Feito em 16/11/2026** (`7551d7e`, só o firmware e os testes dele):
  - **o fluxo:** o cabeçalho provisório, os blocos e o cabeçalho final depois do último bloco. O fd 1 passa a ser o
    stderr, e o fluxo segue numa cópia do stdout: nenhum `printf` precisou mudar, e nenhum texto entra nele;
  - **o que a bancada mostrou antes de pedir:** quem recebe pelo `ssh` e some sem fechar (o cabo USB que sai) não dá
    o `EPIPE` na placa: o pipe do `sshd` fica aberto até o TCP desistir (~15 min), e um `write` preso não sai nem com
    o Ctrl+C (o glibc retoma a chamada), com a PRU sobrescrevendo os buffers. O fluxo é escrito sem o stdio e sem
    bloquear, com `poll`: sem nada andar por 10 s (2 s depois de uma parada pedida, a do aplicativo que voltou depois
    da queda), é o código 6, como o `EPIPE`. As flags do pipe de quem chamou voltam no fim;
  - **o `--progresso-json`:** `inicio` (a configuração, o identificador da captura, a taxa real, o tamanho do bloco),
    um `bloco` por bloco (os contadores acumulados, os do cabeçalho, as saturadas por canal, o tempo de cada um no
    ARM) e o `fim` (o código, o motivo e o CRC das amostras), com um campo `formato` para as próximas versões;
  - **na placa de verdade** (compilado nela com `-Werror`, no ARM de 32 bits, numa pasta à parte, apagada depois):
    4 blocos a 400 kS/s pelo `ssh` no computador, remontados, com o CRC do cabeçalho e o das amostras certos (a tomada
    do laboratório: 131,9 V, 59,986 Hz); o `ssh` daqui morto no meio: o código 6 em menos de 5 s, os 8 blocos que
    chegaram com o CRC que a placa deu; o `ssh` daqui congelado (o cabo, sem aviso): o código 6 em 16 s; o SIGINT por
    outra conexão (o Parar): o código 0 e o fluxo inteiro, com o cabeçalho final. A PRU parada nos quatro;
  - **os testes:** 8 novos em `tests/test_ler_adc_captura.py` (o fluxo remontado contra o arquivo do cartão, campo a
    campo; o leitor que fecha; o leitor que some sem fechar, com a espera encurtada pelo ambiente da `pru_falsa`; a
    parada com a saída travada; o Ctrl+C; o terminal; as linhas JSON com o fluxo e com o arquivo).

### ☑ F4.2: a captura contínua no computador, sem Qt (`sh_placa`)

- **O conteúdo:**
  - rodar o `ler_adc -o - --progresso-json` pelo SSH (com o `sudo` da placa), gravar o arquivo enquanto recebe, ler
    as linhas de progresso e, no fim, pôr o cabeçalho final no offset 0 e conferir o CRC das amostras;
  - **Parar:** o `SIGINT` no `ler_adc` (que fecha o cabeçalho certo);
  - **a queda:** o arquivo parcial fechado pelo computador: os campos de fim calculados dele (os blocos inteiros, o
    CRC das amostras, o sinal de cada canal) e a marca "fim escrito pelo computador" na reserva da v9 (o C e o
    `cabecalho.py` juntos, no mesmo commit, com o `test_contrato_firmware`);
  - **o simulador transmite uma captura:** a placa simulada responde ao `ler_adc -o -` com um fluxo de verdade (as
    capturas simuladas), nos cenários (a conexão que cai, o ADC mudo, o buffer sobrescrito).
- **Feito em 17/11/2026** (a marca no cabeçalho em `a4f97b0`, de 16/11, com o C; o motor em `1257f5b`; o `sh_placa` em
  `4c85596` e `0b543cf`; o simulador em `e849e12`):
  - **o fechamento, no motor** (`supraharmonicos/saida_continua.py`): `fechar` põe o cabeçalho final no lugar do
    provisório e confere o CRC das amostras (o que quem recebeu calculou enquanto chegava, sem reler o arquivo); na
    queda, corta no último bloco inteiro e calcula aqui o CRC e o sinal de cada canal (as fórmulas do C, com o canal
    pela posição no arquivo), os contadores, o tempo e a taxa das linhas de progresso (`Acompanhamento`; a do último
    bloco pode não ter chegado: o tempo dele sai da taxa medida) e a marca `fim_pelo_computador`. Uma captura já
    fechada volta como está. `cabecalho.reescrever_campos` troca campos pelo nome da struct do C e refaz o CRC;
  - **a captura, no `sh_placa`** (`sh_placa/captura.py`, `CapturaContinua`): o roteiro na placa (a pasta do
    firmware; o código 95 sem o `ler_adc`, o 96 com um de antes da saída contínua; o sudo validado uma vez, como em
    `correcoes.py`), o arquivo num `.parcial` renomeado no fim (nada é sobrescrito), o `Progresso` a cada linha, a
    cada bloco inteiro e a cada 0,5 s (os blocos contados já estão no arquivo: a tela os lê de lá), o texto do
    `ler_adc` à parte, a queda e o disco daqui que falha fechados com o que chegou, e `recuperar` para o `.parcial`
    de um aplicativo que fechou no meio;
  - **o Parar, pelo lado root:** uma linha no stdin do roteiro; na placa, o `sudo` roda um shell de root com o
    `ler_adc` em segundo plano e o leitor dessa linha, que manda o SIGINT direto a ele (e também quando o stdin
    fecha). **A bancada achou** o que o simulador não mostraria (o `sudo` dele é um `exec`): o usuário não pode
    mandar sinais ao `sudo` (ele roda inteiro como root: "Operation not permitted"), e um `sudo -n kill` de outro
    processo não teria a credencial (ela é do shell que a validou, e vence em 15 min, menos que uma captura longa);
  - **a placa simulada captura** (`sh_placa/ler_adc_simulado.py`): a linha de comando do `ler_adc.c` (os mesmos
    erros de uso), o cartão (`-o ARQUIVO`) e a saída contínua no ritmo da taxa, o Ctrl+C, o código 6, o ADC mudo, o
    firmware de antes da F4.1 e os erros de configuração que impedem a captura; as capturas simuladas com qualquer
    taxa e canais, o cabeçalho provisório e o sinal contínuo de um bloco para o outro (o "buffer sobrescrito" ficou
    de fora: o simulador não tem a PRU, e a `pru_falsa` já o cobre no C);
  - **na placa de verdade** (o `ler_adc` novo compilado nela numa pasta à parte, apagada depois; seção 5): a captura
    inteira em 3 canais, o Parar, a queda, a senha errada, o firmware v0.8 da pasta de sempre (o código 96) e um
    `.parcial` recuperado, todos com os dois CRCs certos;
  - **os testes:** `tests/test_saida_continua.py` (14, com o `ler_adc` de verdade cortado no meio de um bloco com 1, 3
    e 7 canais, contra a mesma captura no cartão), `tests/test_sh_placa_captura.py` (13, o `ler_adc` de verdade com a
    `pru_falsa` atrás do servidor SSH do teste), 4 novos em `tests/test_sh_placa_simulador.py` e 2 em
    `tests/test_cabecalho.py`.

### ☑ F4.3: o formulário de captura (o B2)

- **O conteúdo:** os campos do plano (11.5) com a validação ao vivo: o título e a descrição em bytes, os canais na
  ordem real, a grandeza, a sonda (o perfil existe e a grandeza bate), a faixa com o LSB, a taxa até o teto da PRU com
  a Nyquist por canal, a duração com o tamanho e o espaço no destino, o destino (o computador ou o cartão) e o
  avançado recolhido; o comando montado, visível; **os modelos** com nome, no projeto; **"Conferir antes"** (o
  `coletar.sh conferir`, ~10 s), com o resultado no caderno.
- **O desenho** (18/11/2026, antes do código):
  - **o pedido, sem Qt** (`sh_placa/pedido.py`): `PedidoDeCaptura` (os canais com a grandeza, a sonda, a faixa e o
    ganho; a taxa; a duração ou os blocos, ou "até parar"; o título e a descrição; o destino; o avançado) monta os
    argumentos do `ler_adc` e o comando visível, e `validar(contexto)` devolve os problemas por campo, com o nível
    (o erro impede a captura; o aviso, não). As regras são as do `ler_adc.c` (o teto da PRU portado de
    `teto_ticks_da_pru`, os limites em bytes, as faixas, os blocos de uma duração); as de fora do C vêm do motor (o id
    de sonda seguro, o perfil na pasta das sondas, a calibração do perfil contra a faixa e o ganho do canal, como o
    `conferir_calibracao_perfil` avisaria na análise) e do contexto (o espaço no destino, a vazão do enlace, uma
    captura do mesmo nome no cartão). **O contrato com o C:** o `ler_adc.c` de verdade, compilado num harness, lê os
    argumentos de cada pedido e devolve o que entendeu; o `ler_argumentos` daqui (o caminho de volta) tem de dar o
    mesmo, nos aceitos e nos recusados. A placa simulada passa a ler a linha de comando por ele (ela aceitava menos
    que o C: sem a temperatura, a faixa, a sonda e o teto);
  - **os modelos de captura no projeto** (`.shproj` versão 4, `modelos_de_captura`): o pedido inteiro com um nome;
    guardar e apagar entram no desfazer, como o resto do projeto;
  - **"Conferir antes"**, a captura curta com o pedido do formulário (um bloco, pela saída contínua da F4.2, num
    arquivo temporário) medida no motor com as regras do `coletar.sh conferir` (a integridade, o ADC mudo, e em cada
    canal o nível, o offset, o ruído em LSB, a frequência, a saturação e a menor faixa que comporta o pico com 15 %
    de folga). **Por que não rodar o `coletar.sh conferir`:** ele usa uma faixa para todos os canais e só o SPI
    rápido ou o lento, e o resultado é texto para humanos (o mesmo motivo do `--progresso-json`, no plano 11.5); com
    o pedido do formulário, a conferência mede exatamente a captura que vai ser feita. A rotina segue no terminal (a
    F4.6). A faixa sugerida vira o "sugerir" de cada canal; o caderno é a F4.5;
  - **a tela** (`areas/aquisicao/capturar.py`, a coluna esquerda do B2): a seção "Capturar" da Aquisição, no lugar da
    página "chega na v0.10". O botão Capturar fica para a F4.4.
- **Feito em 18/11/2026** (o `sh_placa` em `fbded87`, `d4d5929`, `2d8c826` e `d1f7d0e`; o simulador em `ca61759` e
  `92bb000`; o motor em `4c87c77` e `d64e42a`; a interface em `5d67657`, `384e811` e `81cbc1c`):
  - **o pedido** (`sh_placa/pedido.py`), como no desenho, com o contrato contra o `analisar_argumentos` do C
    compilado num harness (os aceitos e os recusados, a mesma mensagem e o código 2) e o teto da PRU igual ao do C em
    cada SPI e espera de CS. As mensagens com a vírgula decimal e os MiB, como o resto da interface;
  - **o formulário** (`areas/aquisicao/formulario_de_captura.py`), em seções: o título e a descrição (o contador em
    bytes), os canais (ligar e desligar; o desligado guarda o que tinha), a grandeza, a sonda (com os perfis da pasta;
    o ganho vazio vem do perfil), a faixa com o LSB e o "sugerir" da conferência, a taxa com a Nyquist por canal, a
    duração (tempo, blocos ou até parar) com o tamanho, o destino com o espaço e o avançado recolhido. Cada problema
    aparece no campo dele (o erro impede; o aviso, não), e o comando, embaixo, é o que vai rodar;
  - **os modelos** no `.shproj` versão 4, num menu na seção (guardar, atualizar, apagar, com o desfazer); o pedido da
    última vez volta ao abrir;
  - **"Conferir antes"** (`sh_placa/conferencia.py` e `servicos/conferencia_da_placa.py`): um bloco do pedido pela
    saída contínua, medido no motor (`supraharmonicos/conferencia.py`, conferido contra o `medir_sinal` e o
    `faixa_para_o_pico` do `comum.sh` de verdade) e apagado; a senha do sudo é a da sessão, a desta conexão ou a do
    cofre, e a seção a pergunta quando não há nenhuma. O resultado fica em linhas (✓, ! e ✗), com a faixa sugerida de
    cada canal a um clique e o aviso quando o pedido muda depois da conferência;
  - **o que a bancada mostrou** (a placa no USB, o canal 1 na tomada da casa do usuário): as medidas do motor são as
    do próprio `ler_adc`, dígito a dígito; o canal saturado não sugeria faixa nenhuma (agora sugere a maior, como a
    `faixa_automatica` do `comum.sh`: o pico cortado não diz qual cabe); a tomada no divisor usa 91 % da maior faixa,
    sem os 15 % de folga, e ninguém avisava (agora: "um surto de 10 % satura"); e o "mais resolução" valia só para a
    faixa menor. **A imagem sem tela mostrou** que o "usar ±10,24 V" ao lado do ganho pedia 396 px numa coluna de 372
    e cortava o formulário: a sugestão foi para uma linha dela, com o motivo. **O simulador tinha um erro:** gravava
    0 KiB livres no disco da saída contínua (o C grava "desconhecido"), e a conferência dizia o cartão cheio; agora
    segue o C, e o `-o ARQUIVO` usa o cartão simulado;
  - **a placa de verdade ainda tem o `ler_adc` v0.8** na pasta do firmware: na tela, a conferência diz "atualize o
    firmware da placa" (o código 96), sem pedir a senha. Na bancada, o `ler_adc` deste branch rodou numa pasta à
    parte (`~/f43`, compilado nela com `-Werror` e apagado depois);
  - **os testes:** `tests/test_sh_placa_pedido.py` (145, com o harness do C), `tests/test_conferencia.py` (24, com o
    bash e o awk de verdade), `tests/test_gui_capturar.py` (16), o `Conferir antes` em `tests/test_sh_placa_captura.py`
    (o `ler_adc` de verdade com a PRU falsa), os modelos em `tests/test_gui_projeto.py` e `tests/test_gui_modelo.py`, e
    o disco e as opções do `ler_adc` simulado em `tests/test_sh_placa_simulador.py`.

### ☑ F4.4: a captura na tela

- **O conteúdo:** o tempo e a barra, os bytes e a vazão, os contadores de integridade, o sinal ao vivo (os últimos
  50 ms do bloco mais recente) e o espectro ao vivo (Welch, com a média dos blocos); **Parar**; no fim, o CRC
  conferido e a captura no projeto; **a queda:** o parcial fechado e o aviso, com o que se perdeu; **o destino no
  cartão:** o `-o` na placa e, no fim, a transferência sozinha (se pedida).
- **O desenho** (18/11/2026, antes do código):
  - **o nome do arquivo** (`sh_placa/pedido.py`, `nome_do_arquivo`): o do `ler_adc` (`captura_AAAAMMDD_HHMMSS.bin`),
    com o relógio deste computador (o da placa pode estar errado: ela não tem bateria), e o título em ASCII na frente,
    se houver; nada é sobrescrito (no computador, `_2`, `_3`...; no cartão, a validação já recusa o nome que existe).
    No cartão, o pedido leva o nome escolhido no `-o`, e o comando do cockpit é o que rodou;
  - **o computador:** a `CapturaContinua` da F4.2, como está;
  - **o cartão, desacoplado da conexão** (`sh_placa/captura.py`, `CapturaNoCartao`): o cabo tem mau contato, e o
    motivo de gravar no cartão é a captura sobreviver a ele. Na placa, o `ler_adc -o NOME --progresso-json` roda num
    `setsid` (com o `HUP` ignorado, que ele respeita), com o texto, as linhas de progresso, o PID e o código de saída
    em `~/firmware/.em_curso/NOME/`. O aplicativo acompanha por um `tail -F` dessas linhas; a queda só interrompe o
    acompanhamento, e a conexão seguinte (ou o aplicativo aberto de novo) volta a acompanhar do começo do arquivo de
    progresso. **Parar** é um `sudo kill -INT` no PID, com a senha validada como nas correções. No fim, a pasta
    `.em_curso` dela é apagada e, se o pedido diz `trazer_no_fim`, a captura entra na fila de transferências (que
    já espera nenhuma captura rodar e confere o SHA-256);
  - **o ao vivo** (o computador): a cada bloco inteiro no `.parcial`, uma thread abre o que chegou pela `api` do
    motor (`abrir_ao_vivo`: o cabeçalho provisório e os blocos inteiros, nas unidades de cada canal, como o
    `abrir_captura`) e calcula os últimos 50 ms de cada canal e o Welch dele; o espectro mostrado é a média (em
    potência) dos últimos 8 blocos. O ao vivo anda de bloco em bloco (2,6 s a 400 kS/s): é o que a saída contínua
    entrega. **No cartão**, as amostras ficam na placa até a transferência: o cockpit mostra o progresso e a
    integridade de cada bloco, sem o sinal (ler pedaços da captura pela rede, no único núcleo da placa, competiria
    com ela);
  - **o fim:** o CRC das amostras conferido (o do `fechar` da F4.2), o resumo da integridade e do que parou a
    captura (o fim pedido, a queda com o que se perdeu, o ADC mudo), e a captura posta no projeto, com "Abrir na
    Análise". **Uma captura que ficou pela metade** (o aplicativo fechado no meio: o `.parcial` na pasta da sessão)
    aparece na seção, com "Fechar a captura" (o `recuperar` da F4.2). Fechar a janela no meio de uma captura para o
    computador pergunta antes;
  - **a tela:** o cockpit do B2 no centro da seção, no lugar do comando e do "Antes de capturar", com o formulário
    travado enquanto a captura roda: a barra de estado (o tempo, a barra, o recebido, a vazão, os contadores,
    Parar), o sinal ao vivo (um gráfico por canal), o espectro ao vivo (um canal por vez, a faixa de 2 a 150 kHz
    marcada) e a saída do `ler_adc`. A senha do sudo segue a da conferência. O caderno é a F4.5.
- **Feito em 18/11/2026** (o `sh_placa` em `1472519`; o motor em `dcfd8f1`; a interface em `080f78b`, `7a21de5` e
  `5365d8e`):
  - **o nome e o cartão** (`sh_placa/pedido.py`, `nome_do_arquivo`; `sh_placa/captura_no_cartao.py`), como no
    desenho. A pasta da captura em curso fica na pasta do firmware (`.em_curso/NOME/`: o `pid`, o `progresso`, o
    `texto` e o `codigo`), e quem a recolhe é o `limpar`. O roteiro de início confere o nome que já existe (94) e
    outra captura rodando (93) antes da senha;
  - **o ao vivo** (`servicos/ao_vivo.py`, pelo `api.abrir_ao_vivo`): uma conta por vez numa thread, e só o bloco
    mais recente; no fim, o quadro do último bloco sai do arquivo final (uma captura curta acaba antes do primeiro
    quadro);
  - **o serviço** (`servicos/captura_da_placa.py`, `CapturaDaPlaca`): os estados, a senha (a da sessão, a desta
    conexão, a do cofre), o Parar, a queda no cartão (o estado `sem_conexao` e a retomada na próxima sessão da mesma
    placa, pelo `em_curso`), a fila de transferências no fim e onde a captura que terminou está neste computador
    (`local_do_fim`: o arquivo, ou a cópia conferida da do cartão);
  - **o cockpit** (`areas/aquisicao/ao_vivo.py`) no centro da seção, no lugar do comando; o formulário travado
    enquanto a captura roda; o fim com o resumo e as ações (Abrir na Análise, Mostrar na pasta, Trazer, Nova
    captura); o `.parcial` da sessão com "Fechar a captura"; fechar a janela no meio pergunta;
  - **o que a imagem sem tela mostrou:** a barra de estado numa linha só cortava o Parar e rolava de lado, e os
    gráficos ao vivo empurravam o espectro para fora da tela. A barra foi para duas linhas, e os gráficos para
    alturas fixas, com o nome do canal numa etiqueta dentro do gráfico (em pé, ele era mais alto que o gráfico de
    cada canal). No cartão, a saída do `ler_adc` rolava de lado com o nome do arquivo (agora quebra). E a captura do
    cartão, trazida e conferida, não mostrava o "Abrir na Análise" (agora mostra, pelo `local_do_fim`);
  - **o que a bancada mostrou** (a placa no USB, o canal 1 na tomada; o `ler_adc` deste branch em `~/f44`, compilado
    com `-Werror` e apagado depois; seção 5): as três capturas como no simulador, sem nenhuma correção;
  - **os testes:** `tests/test_gui_captura_na_tela.py` (9: a captura no computador com o ao vivo e o projeto, o
    Parar, a queda no computador, o cartão com a queda, a retomada e a transferência, a senha, o `.parcial`, fechar a
    janela, o nome livre e o quadro pela `api`), os do cartão em `tests/test_sh_placa_captura.py` (o `ler_adc` de
    verdade com a PRU falsa: a queda, a retomada, o Parar, o nome que existe, outra captura rodando), o nome em
    `tests/test_sh_placa_pedido.py`, o cartão com o SFTP em `tests/test_sh_placa_simulador.py` e o `abrir_ao_vivo` em
    `tests/test_saida_continua.py`.

### ☑ F4.5: o caderno de bancada

- **O conteúdo:** as notas com hora e as entradas automáticas (a captura, a conferência, a transferência, a
  correção), no `anotacoes.md` da sessão do dia (o mesmo do `sessao_lab.sh`, PD-09); a seção "Notas" no projeto.
- **O desenho** (18/11/2026, antes do código):
  - **o arquivo é do usuário** (`dados/caderno.py`, sem Qt): o `anotacoes.md` da pasta da sessão do dia (a mesma das
    capturas e das transferências, `preferencias.pasta_da_sessao`, a do `lab`). O `lab` o cria do modelo
    (`docs/lab-notes-template.md`) e o usuário o preenche à mão (`lab notas`); o aplicativo **só acrescenta ao fim**,
    nunca reescreve. Cada entrada é uma linha de lista em Markdown, legível no editor e no relatório:
    `- **14:10:03** · automático · Captura ... iniciada: ...` (ou `· você ·`), com as linhas de detalhe recuadas em
    dois espaços. As entradas ficam sob um título `## Caderno de bancada`, escrito antes da primeira e de novo quando
    o último título do arquivo é outro (o usuário escreveu uma seção depois): nada entra no meio do que ele escreveu.
    Sem o arquivo, o aplicativo o cria só com o título do dia (`# Anotações da bancada: AAAA-MM-DD`), e o `lab`
    depois o acha "já existia". Cada entrada é um `write` só, no modo de acréscimo. A leitura acha as entradas em
    qualquer parte do arquivo: as escritas à mão no mesmo formato também valem;
  - **as entradas automáticas** vêm de sinais novos dos serviços, emitidos na hora do fato (e não de comparar
    estados): os marcos da captura (`CapturaDaPlaca.marco`: começou, a conexão caiu com ela seguindo no cartão,
    acompanhada de novo, terminou, não deu), o fim da conferência (`ConferenciaDaPlaca.terminou`), a transferência no
    estado final (`TransferenciasDaPlaca.terminou`: conferida, corrompida, interrompida, falhou; a cancelada pelo
    usuário não entra) e a correção que terminou (`SaudeDaPlaca.corrigiu`: os pinos e o relógio, inclusive o acerto
    sozinho ao conectar). As frases usam o que a tela mostra (o resumo do pedido e o comando, as linhas da conferência
    e do fim, com os mesmos números), com as linhas de detalhe marcadas como no `conferir.sh`: ✓, ! e ✗. **O relatório
    do diagnóstico** vai para o caderno com um clique ("Para o caderno", ao lado do "Copiar o relatório"; o plano,
    11.9);
  - **o serviço** (`servicos/caderno.py`, `CadernoDaSessao`): o caminho do dia refeito a cada escrita e a cada minuto
    (a sessão que passa da meia-noite vai para o arquivo do dia novo, como as capturas); as entradas lidas de novo
    quando o arquivo muda fora do aplicativo (um `QFileSystemWatcher` no arquivo e na pasta: o `nvim` grava trocando o
    arquivo); um erro de disco não perde a nota (o motivo aparece, e o texto fica no campo). Com o arquivo aberto no
    editor, é o editor que avisa que ele mudou no disco antes de gravar por cima;
  - **na Aquisição** (`areas/aquisicao/caderno.py`): a coluna da direita do B2 na seção Capturar (300 px), com as
    entradas (a mais nova em cima, a hora e "automático" ou "você"), o "Escrever uma nota…" embaixo (Enter grava) e
    "Abrir no editor". A coluna se esconde (lembrado nas preferências) para as telas estreitas, e volta pelo
    "Caderno" do título da seção;
  - **no projeto** (a seção "Notas" da árvore, a terceira depois de Fontes e Vistas): os cadernos das pastas das
    capturas do projeto, um por pasta que tem o `anotacoes.md`, com o número de entradas. Calculados das fontes, sem
    nada novo no `.shproj` (o projeto guarda receitas). Um clique mostra o caderno no inspetor (só leitura, com
    "Abrir no editor"); o duplo clique o abre no editor. A nota nova é só no caderno do dia, na Aquisição: a hora de
    agora num caderno de outro dia enganaria;
  - **o simulador que para leva as capturas no cartão junto** (`servidor_do_simulador.py`): o `setsid` as solta da
    conexão de propósito, e uma "até parar" na placa simulada seguiria neste computador depois do aplicativo fechar.
    Como a placa desligada, o simulador que para mata as que rodam (o grupo de cada uma, conferido pelo `ps`).
- **Feito em 18/11/2026** (o simulador em `2dbc88e`; a interface em `6c27347`):
  - **como no desenho:** o formato (`dados/caderno.py`), o caderno da sessão (`servicos/caderno.py`), as frases e as
    ligações (`areas/aquisicao/entradas_do_caderno.py`), a coluna na seção Capturar (`areas/aquisicao/caderno.py`), a
    lista das entradas, a mesma na Aquisição e no inspetor (`componentes/caderno.py`), a seção Notas da árvore e o
    inspetor do caderno; o "Para o caderno" no diagnóstico;
  - **o que a imagem sem tela mostrou:** com a coluna de 300 px, o cockpit não cabia na janela de 1440 px (o padrão):
    a linha das ações do fim (471 px) rolava de lado. O "Nova captura" foi para o topo do painel do fim, e o "média
    de N blocos" do espectro e o título do fim quebram: o cockpit pede 398 px, e cabe. As entradas grudavam (o
    `QTextDocument` não respeita a margem de um `div` dentro de outro: agora são parágrafos), e as linhas de detalhe
    saíam com duas marcas ("• ✓"; agora só a marca, na cor dela). **E um erro da F4.3:** o ruído em LSB da
    conferência saía com o ponto ("671.7 LSB"; agora com a vírgula, como o resto);
  - **o arquivo do `lab`:** o modelo do repositório, criado como o `sessao_lab.sh` o cria, só ganha linhas no fim
    (o teste confere byte a byte); a seção entra uma vez, e de novo só depois de uma seção do usuário;
  - **os testes não escrevem mais nos dados de quem desenvolve:** o `conftest.py` põe o `$DADOS` numa pasta
    temporária, como já fazia com a configuração, o cache e o log. Um teste que montasse a Aquisição sem dizer a pasta
    escreveria no `anotacoes.md` de verdade (o relógio acertado ao conectar basta);
  - **na placa de verdade, nada:** o caderno não fala com a placa, e as entradas vêm dos serviços que a F4.4 conferiu
    nela. A interface na placa ainda espera o `ler_adc` novo na pasta do firmware (o "atualize o firmware");
  - **os testes:** `tests/test_gui_caderno.py` (16: o formato, o arquivo do `lab`, as entradas à mão, o caderno da
    sessão com o editor, o dia e o disco, a coluna, as frases, a seção Notas com o inspetor e a coluna lembrada), as
    entradas da captura, da queda, da volta, da transferência, da conferência e do relatório nos fluxos de
    `tests/test_gui_captura_na_tela.py` (10), e o simulador que para em `tests/test_sh_placa_simulador.py` (conferido
    com a correção desligada: ele falha).

### ☑ F4.6: as rotinas do `coletar.sh` pelo terminal

- **O conteúdo:** as rotinas (a sonda, a calibração, a campanha) abrem no terminal embutido com o comando montado pelo
  formulário, com as pausas "mude a bancada e tecle Enter" que elas já têm (o plano, 11.5).
- **O desenho (18/11/2026):**
  - **sem o Qt, `sh_placa/rotinas.py`:** os sete modos do `coletar.sh` (conferir, calibrar, sonda, aliasing, ruído,
    teto, bancada), cada um com o resumo, as opções principais (a opção, o rótulo, a ajuda, o tipo: texto, escolha ou
    marca), se para e pede a bancada, se aceita `--simular` e `--continuar`; `valores_do_pedido` preenche o que é a
    bancada (os canais, o canal da sonda, a grandeza, a sonda, a taxa, a faixa e o SPI) com o pedido da Capturar, e
    deixa o resto vazio (o padrão do script, que dá uma boa análise); `comando` monta
    `cd ~/firmware && ./coletar.sh MODO ...`, cada valor com `shlex.quote`, e as "outras opções" do usuário lidas
    pelo `shlex` (aspas abertas são recusadas). A ajuda do script não é lida por máquina (é feita para gente: duas
    opções numa linha, os padrões no meio do texto); um teste confere que cada opção da tabela está na ajuda de
    cada modo e que todo modo da ajuda está na tabela, e outro roda os comandos montados com `--simular` no
    `coletar.sh` do repositório;
  - **a seção Rotinas** da Aquisição (entre a Capturar e a Arquivos): a lista dos modos à esquerda (com "para e pede
    a bancada" quando para), o formulário do escolhido, a linha de comando pronta (só leitura, com o copiar: as outras opções cobrem o resto) e "Rodar no terminal",
    "Simular" (com `--simular`), "Continuar a última" (com `--continuar`) e "Ver a ajuda". Rodar abre uma aba nova do
    terminal com o nome do modo, roda o comando lá (as pausas, o `sudo` e as respostas ficam na aba, gravadas no
    `terminal_bbb_N.txt` do dia) e põe uma entrada no caderno; os valores de cada modo ficam enquanto o aplicativo
    está aberto, e "Do pedido" os refaz pela Capturar;
  - **os testes:** a tabela contra a ajuda, o comando (as aspas, os vazios, as marcas, as outras opções), os comandos
    com `--simular` aceitos pelo `coletar.sh` de verdade, e a seção com o servidor SSH dos testes (o `sh -i` num PTY):
    rodar uma rotina com `--simular` na placa do teste, a aba nova com o nome do modo e o plano na tela, e a entrada
    no caderno;
  - **pronto quando:** a calibração e a sonda rodam da seção na placa de verdade até a primeira pausa (com
    `--simular`, até o fim do plano).
- **Feito em 18/11/2026:** o `sh_placa` (as rotinas e o comando, `2a129fc`; o terminal com a entrada inicial e o SPI
  só fora do padrão, `2a592ff`) e a interface (a seção Rotinas, `dcf011a`). Mudou do desenho: a linha de comando é só
  leitura (editá-la à mão desligaria o formulário; as "outras opções" cobrem o resto), e o SPI do pedido só entra
  quando é o lento (o rápido é o padrão do script, como no comando do `ler_adc`). **Na placa** (seção 5): a
  calibração e a sonda até a primeira pausa, e a calibração com `--simular` até o fim do plano.

### ☑ F4.7: o fechamento da Fase 4

- **O conteúdo:** a jornada da captura num teste de ponta a ponta com o simulador (o formulário, a captura, o Parar,
  a queda, a captura na Análise); **na placa de verdade:** uma captura de 1 h direto no computador, sem perder amostra,
  aberta na Análise; o plano e este arquivo em dia.
- **O desenho (18/11/2026):**
  - **o teste de ponta a ponta,** `tests/test_gui_jornada_captura.py`, na janela e pelos gestos, como o da F3.10:
    a Aquisição, o simulador achado e conectado com um clique, a seção Capturar pela coluna da esquerda, o pedido (um
    modelo posto no formulário, o título digitado), o "Conferir antes", o Capturar com o ao vivo no cockpit, o Parar,
    a captura que entra no projeto e o "Abrir na Análise" com o canal plotado (as amostras do arquivo são as que o
    cockpit contou); depois uma captura no cartão, a queda do cabo no meio, a volta do acompanhamento, a cópia
    conferida e trazida para o projeto; e o caderno da sessão com tudo na ordem;
  - **na placa de verdade:** o aplicativo inteiro (a janela, sem tela), conectado pelo USB, o canal 1 na tomada de
    casa, 400 kS/s, 1 h direto no computador, com o `ler_adc` deste branch compilado numa pasta à parte (`~/f47`,
    apagada no fim; a placa segue com a v0.8). Pronto quando: o CRC das amostras confere, a integridade é zero (nenhuma
    amostra atrasada, nenhum buffer sobrescrito, nenhum preâmbulo ruim), o número de amostras é o pedido, e a captura
    abre na Análise com a pirâmide feita e o canal plotado (o tempo de cada passo vai para a seção 5). A queda do cabo
    no meio (o mau contato) fecha a captura com o que chegou: se acontecer, a rodada se repete;
  - **o plano e este arquivo:** a Fase 4 marcada como feita, com o que mudou do plano (11.5 e 11.6).
- **Feito em 18/11/2026:** o teste de ponta a ponta (`5e3249c`) e um defeito achado na bancada (`dcc1db0`: a captura
  direto no computador ignorava a pasta do firmware do serviço, que só a do cartão usava). **Na placa** (seção 5): 1 h
  sem perder amostra, aberta na Análise. O plano em dia (`docs/gui-plan.md`: a Fase 4 cumprida, 11.5 e 11.6).

## 4f. Fase 5 em tarefas: figuras e exportação

O plano (`docs/gui-plan.md`, seção 10 e a Fase 5): a área Figuras (o mockup F1: a lista de figuras e modelos à
esquerda, a página no tamanho real ao centro, as propriedades do elemento à direita), a exportação da figura com a
fidelidade da seção 10.3, a exportação dos dados com a proveniência e o pacote reproduzível. **Pronto quando:** uma
figura IEEE sai em PDF e em pacote reproduzível, e o script do pacote refaz a figura sem o aplicativo. **Tag v0.11.**

A ordem leva cedo ao "pronto quando" (o modelo, o desenho, a tela, o PDF e o pacote) e deixa o acabamento (o estilo
de cada elemento, os insets e as anotações) para depois do caminho inteiro de pé. Cada tarefa tem os testes dela e
o diário.

### ☑ F5.1: o modelo da figura, sem Qt

- **O conteúdo:** `dados/figura.py`: os modelos de página (IEEE de 88 e 181 mm, Elsevier de 90, 140 e 190 mm, o
  relatório FAPESP em A4 com as margens da ABNT, o slide 16:9 e o pôster A0), a figura (o modelo, a grade de
  painéis, o idioma dos números) e o painel (ligado a uma vista do projeto pelo id, ou congelado com os dados do
  momento; o rótulo (a), (b)…; os limites; os eixos compartilhados na linha e na coluna) e o estilo (as fontes
  embutidas e os tamanhos em pt, as espessuras); a figura no arquivo de projeto (`ProjetoSalvo.figuras`, a versão 5
  do `.shproj`, que ainda lê a 4) e os números do SI com o separador do idioma.
- **Pronto quando:** a figura vai e volta do `.shproj` igual, um projeto da versão 4 abre sem figuras, e o que não
  vale (um painel fora da grade, um modelo desconhecido, um tamanho negativo) é recusado com a razão.
- **Feito em 18/11/2026** (`5e4e545`): `dados/figura.py` (os oito modelos de página, a figura, o painel, o estilo, os
  rótulos automáticos e a ida e a volta), a versão 5 do `.shproj` (a leitura de uma vista virou uma função, usada
  também pela vista congelada de um painel) e as figuras no projeto observável (`figurasMudaram`, `_por_figura`,
  `_tirar_figura`; os comandos com desfazer vêm com a tela, na F5.3). **Decisões:** a vista congelada é a cópia da
  vista (os traços com as receitas e as opções), e não dos dados: as capturas não mudam, e a figura congelada se
  refaz igual; as famílias de letra são a STIX (do tipo Times, que vem com o Matplotlib) e a DejaVu Sans (idem), e a
  Inter e a IBM Plex Sans (do aplicativo); a Latin Modern e a TeX Gyre Termes do plano ficam de fora até alguém
  pedir (seriam mais arquivos de fonte no pacote); os números do SI com o separador do idioma usam o `formatar_si`
  que já existia (`componentes/numeros.py`, sem Qt).

### ☑ F5.2: o desenho com o Matplotlib e a fidelidade

- **O conteúdo:** `figura → matplotlib.figure.Figure` (sem Qt): cada painel desenha os traços da vista dele (tempo e
  espectro primeiro; as bandas, o espectrograma e os harmônicos depois), com os dados pela pirâmide reduzidos pelo M4
  na resolução de saída (2 colunas por pixel do dispositivo final), as unidades do SI com prefixo, os rótulos (a),
  (b)…, os eixos compartilhados e a legenda; as fontes do aplicativo registradas no Matplotlib.
- **Pronto quando:** o teste de fidelidade passa (a curva reduzida e a de todos os pontos dão os mesmos pixels na
  resolução de saída, seção 10.3), e uma figura de dois painéis sai com os números do idioma escolhido.
- **Feita em 19/11/2026** (`4972da3`, `01395a4`, `9fca9ec`): `dados/desenho_da_figura.py` (sem Qt): a página no
  tamanho do modelo (o leiaute *constrained* do Matplotlib), a grade com os painéis largos, a vista de tempo como ela
  está na tela (uma faixa por eixo, o tempo compartilhado e os números do tempo só embaixo; a que sobrepõe, num eixo
  com a legenda), o espectro (linear e log), os eixos compartilhados entre painéis (a união das janelas), os rótulos
  (a), (b)…, o prefixo do SI comum ao eixo ("Tensão (kV)", nenhum em °C ou sem unidade), o tempo em ms abaixo de 2 s,
  o separador e o menos tipográfico do idioma, as grandezas em inglês, as fontes do aplicativo registradas, e as
  vistas que ainda não entram com um aviso no painel. Os limites do y são os extremos exatos da janela (os blocos
  pela pirâmide e as pontas lidas das amostras). **O M4** roda em duas passadas: a primeira acha o leiaute, a segunda
  reduz cada traço nas colunas que caem sobre os meios pixels do eixo; o exato (a exportação) lê as amostras em lotes
  de 8 M, a prévia usa a envoltória da pirâmide. **A fidelidade, medida:** sem o antisserrilhado, a curva reduzida e
  a de todos os pontos (500 mil) ficam a 1 pixel uma da outra (a distância de Hausdorff entre as tintas: nenhum dos
  impulsos de uma amostra some, nada aparece), com ~5 % dos pixels de tinta diferentes, todos na borda do traço (a
  prévia, ~9 %). **Decisão:** a promessa do plano ("os mesmos pixels") vale para a linha de 1 pixel; no traço de
  0,75 pt (1,6 px a 150 dpi, 3,1 px a 300 dpi), a borda depende de onde cada ponto cai dentro da coluna, e nem 8
  colunas por pixel a zeram (o alinhamento das colunas aos pixels também não muda a conta). Desenhar a curva inteira
  em pedaços dá os mesmos pixels que de uma vez (o Agg não perde tinta na referência). O teste afirma o que vale: a
  distância de 1 pixel e menos de 6 % (12 % na prévia), o que pega um traço deslocado (que mudaria metade da tinta)
  ou um pico perdido.
### ☑ F5.3: a área Figuras na tela

- **O conteúdo:** a área (o F1) com a lista das figuras do projeto e dos modelos de página, a página em tamanho real
  (a prévia Agg do próprio desenho da F5.2, refeita fora da thread da interface), as propriedades do painel escolhido;
  "uma vista vira figura com um clique" (FG-01) e o painel ligado que acompanha a vista; congelar; desfazer.
- **Pronto quando:** pelos gestos, uma vista vira uma figura IEEE de uma coluna, um segundo painel entra na grade, a
  vista muda e a figura acompanha, e o projeto salvo e reaberto mostra a mesma página.
- **Feita em 19/11/2026** (`03a171e`, `6e4a7d7`, `0b64c40`): `areas/figuras/` (a área no F1: a lista das figuras e
  dos modelos de página, a página no tamanho real ou do tamanho que cabe, as propriedades da página, da grade e do
  painel escolhido; o clique num painel o escolhe), o botão de imagem ao lado das abas da Análise (FG-01: a vista
  aberta vira uma figura IEEE de uma coluna e a janela vai para as Figuras), a linha da figura na barra de status, e
  os comandos com desfazer (`AdicionarFigura`, `MudarFigura`, que junta os passos de girar a altura, e
  `RemoverFigura`). **O painel ligado acompanha a vista:** os traços, as opções e a janela que ela mostra (a Análise
  avisa, `exibicaoMudou`), e a materialização de um traço com cadeia quando ela fica pronta. **Congelar** guarda a
  cópia da vista e a janela do momento; religar volta a acompanhar as duas. **A prévia é o desenho da F5.2** no dpi
  da tela: os dados são colhidos na thread da interface (`colher`, só referências) e o Matplotlib desenha numa de
  trabalho; com a área escondida, nada se desenha. **Decisões:** fechar a vista de um painel ligado o congela (com a
  janela que ela mostrava), e fechar uma captura tira os traços dela das cópias congeladas, no mesmo passo de
  desfazer: o projeto continua salvável (o arquivo exige as vistas e as capturas de cada painel); os espectros vêm
  do que a vista de espectro já calculou (os traços da vista de tempo ligada a ela), sem refazer a FFT, e o espectro
  congelado mostra um aviso até ganhar o cálculo próprio (o botão "Congelado" fica para a vista de tempo); as
  edições da figura são funções sem Qt em `dados/figura.py` (pôr um painel na primeira célula livre ou numa linha
  nova, com a página crescendo uma linha; trocar o modelo com o estilo dele). **Conferido na tela sem tela:** a área
  em 1 400 × 900 com dois painéis (um ligado e um congelado).
### ☑ F5.4: a exportação da figura

- **O conteúdo:** PDF (fontes Type 42, a proveniência nos metadados), SVG (o texto editável ou em curvas), EPS, PGF,
  PNG e TIFF (dpi de 150 a 1 200; o TIFF com LZW); "rasterizar só as curvas densas" e "todos os pontos" (com o aviso
  acima de ~2 M pontos); copiar a figura para a área de transferência (PNG e SVG, FG-09).
- **Pronto quando:** cada formato sai e é conferido (o PDF com as fontes embutidas e o tamanho da página do modelo, o
  PNG no dpi pedido), e a exportação longa roda fora da thread da interface, com o progresso.
- **Feita em 19/11/2026** (`d62a619`, `e260379`, `2e01ec9`, `ce671f8`, `b87759b`): `dados/exportar_figura.py` e
  `dados/proveniencia.py` (sem Qt) e a seção Exportar da área Figuras (o formato, a resolução, o texto editável do
  SVG, as curvas rasterizadas, "todos os pontos" com a conta e o aviso, o "Exportar figura…" numa tarefa pesada com
  o andamento na seção e no painel das tarefas, e o copiar). **Conferido em cada formato:** o PDF no tamanho da
  página (88 × 100 mm = 249,4 × 283,5 pt), as fontes como TrueType embutida (`/FontFile2`, sem Type 3) e a
  proveniência no `Subject`; o SVG do tamanho da página, com o texto como texto ou em curvas; o EPS com a caixa da
  página e a proveniência num comentário depois do `%%EndComments`; o PGF compilado pelo xelatex num documento (sem
  caractere faltando); o PNG e o TIFF em RGB, no número de pixels e no dpi pedidos, o TIFF em LZW, com a proveniência
  na `Description` e na `ImageDescription`. **A proveniência** (o aplicativo, a figura, cada painel com a vista e as
  receitas, e as capturas usadas com o caminho, o tamanho, o CRC e o cabeçalho resumido) fica pronta para o
  `proveniencia.json` da F5.5. **Decisões:** o dpi vale também nos vetoriais (é a resolução do M4, 600 por padrão, e a
  das curvas rasterizadas); o leiaute é achado em até 150 dpi e só a redução usa o dpi pedido (um pôster A0 a
  1 200 dpi não aloca 9 GB de pixels para isso); uma imagem passa no máximo de 300 M pixels (o A0 em TIFF vai até
  439 dpi, e a seção diz isso ali); as imagens têm um número inteiro de pixels, arredondado (o Matplotlib truncava
  519,7 px em 519); o PGF precisa de um LaTeX instalado (o botão fica desabilitado sem ele, com a razão), mede o texto
  com o LaTeX do sistema e deixa as fontes para o documento; o PNG copiado sai a 300 dpi, ou menos numa página
  grande (~6 000 px no lado maior). **Um defeito achado:** com o PySide6 6.12, um `QMimeData` criado no Python e
  deixado na área de transferência derruba o processo na saída (até num script de seis linhas); a área de
  transferência agora é limpa no `atexit` se ainda tem o que o aplicativo pôs (comparado pelo objeto C++), e a
  figura copiada não sobrevive ao aplicativo fechado.
### ▶ F5.5: a exportação dos dados

- **O conteúdo:** CSV, HDF5 (o leiaute do `adc_tool`), MAT (v5 até 2 GB, v7.3 acima) e NPZ (FG-07): a janela, a
  região dos cursores ou a captura inteira, em blocos e com progresso; crus ou em unidades; com ou sem as
  transformações; sempre com o `proveniencia.json` (as fontes com o CRC, o cabeçalho resumido, a receita de cada
  traço, as versões e os comandos equivalentes da CLI).
- **Pronto quando:** os quatro formatos voltam iguais aos dados da tela (lidos de novo nos testes), e a captura
  inteira de 1 h sai em blocos sem estourar a memória.

### ☐ F5.6: o pacote reproduzível

- **O conteúdo:** o `.zip` (FG-08) com a figura nos formatos escolhidos, o `dados.h5` com os dados de cada painel na
  resolução usada, o `refazer_figura.py` (só NumPy, h5py e Matplotlib), o `proveniencia.json` e um `LEIA-ME.md`.
- **Pronto quando:** num processo sem o SH-Analyzer no caminho, o `refazer_figura.py` refaz a figura, e ela dá os
  mesmos pixels que a exportada pelo aplicativo.

### ☐ F5.7: o estilo de cada elemento e os modelos de estilo

- **O conteúdo:** editar tudo o que se vê (FG-04): fontes e tamanhos em pt, espessuras, cores, tracejados,
  marcadores, a legenda (qualquer canto ou fora do eixo), os limites, os rótulos e as unidades; os modelos de estilo
  próprios, salvos do estilo atual (FG-02); a prévia em tons de cinza e com a simulação de daltonismo (FG-05).
- **Pronto quando:** cada propriedade muda a prévia e a exportação igual, com desfazer, e um modelo de estilo salvo
  aplica-se a outra figura.

### ☐ F5.8: os insets e as anotações

- **O conteúdo:** o *inset* de ampliação com as linhas de ligação, as anotações (texto, seta, região, cota de Δt) e a
  matemática pelo mathtext (FG-03); as anotações também nas vistas da Análise.
- **Pronto quando:** uma figura com um inset e as quatro anotações sai igual na prévia, no PDF e no pacote.

### ☐ F5.9: as vistas em grade, o alinhamento de traços e os perfis de sonda

- **O conteúdo:** o que a Fase 5 do plano junta à Análise: as vistas em grade, o alinhamento de traços (o atraso
  entre capturas) e o editor dos perfis de sonda.
- **Pronto quando:** a desenhar no começo da tarefa (o plano só os nomeia).

### ☐ F5.10: o fechamento da Fase 5

- **O conteúdo:** a jornada da figura num teste de ponta a ponta (da captura à figura IEEE em PDF e em pacote, com o
  script do pacote refazendo a figura fora do aplicativo); o plano e este arquivo em dia.

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
| 15/11/2026 | G1 sem tela, 8 faixas, 954 × 526 px, **com a cadeia** (sonda + passa-altas em cada traço): durante as materializações; depois | **Durante: reprovado**, mediana de 9,4 ms, p95 de 32,9 ms. **Depois: aprovado**, mediana de 9,2 ms, p95 de 12,8 ms (sem a cadeia: 8,3 e 10,2 ms) | `medir_vista --cadeia` |
| 15/11/2026 | O mesmo percurso sobre traços já prontos, com **duas materializações ao fundo** × **uma de cada vez** | Duas: p95 de 37,9 e 40,1 ms (~920 trocas voluntárias da thread da interface). Uma: 11,0 e 11,2 ms (30 a 118), o mesmo que sem nenhuma (13,8 ms) | bancada do diário de 15/11 |
| 15/11/2026 | G1 sem tela, 8 faixas, **com a cadeia**, depois da fila das pesadas e da curva da sonda em pedaços | **Aprovado. Durante:** mediana de 5,1 a 5,3 ms, p95 de 7,5 a 9,7 ms. **Depois:** mediana de 8,8 a 8,9 ms, p95 de 10,8 a 12,2 ms (3 rodadas). **Otimista:** os números dos eixos estavam parados (`b946419`) e quase não eram redesenhados; as duas linhas de 15/11 acima também | `medir_vista --cadeia`; `pytest --desempenho` |
| 15/11/2026 | **G1 sem tela, 8 faixas, com os eixos redesenhados** a cada zoom e pan (a correção dos números parados) | **Aprovado. Sem a cadeia:** mediana de 9,4 ms, p95 de 11,3 ms. **Com a cadeia, durante:** mediana de 7,3 a 7,4 ms, p95 de 11,9 a 12,9 ms; **depois:** mediana de 10,2 a 10,4 ms, p95 de 14,0 a 14,2 ms (2 rodadas). Redesenhar os eixos custa ~1,5 ms por quadro | `medir_vista [--cadeia]`; `pytest --desempenho` |
| 15/11/2026 | **A vazão do USB, na placa de verdade** (192.168.6.2), 46 MiB e 8 MiB de captura | `scp` e `rsync`: 4,8 MB/s; `ssh cat` com o `chacha20-poly1305`, o `aes128-gcm` e o `aes128-ctr`: 5,2, 5,7 e **5,9 MB/s**; **o SFTP do asyncssh com o `aes128-ctr`: 5,2 MB/s**. O limite é a cifra no único núcleo da placa (o eMMC lê a 264 MB/s) | seção 6; a sonda da F3.1 |
| 16/11/2026 | **O SFTP da placa com o leitor da F3.9** (os pedidos de 16 KiB: o OpenSSH 7.9 dela não tem o `limits@openssh.com`) × o leitor paralelo do asyncssh, 8 MiB, duas rodadas de cada | Os dois: **5,0 a 5,1 MiB/s** com o `aes128-ctr` da conexão (4,5 MiB/s com a cifra padrão do asyncssh); o SHA-256 igual | o diário de 16/11 (F3.9) |
| 16/11/2026 | **A saída contínua na placa de verdade** (`ler_adc -o -` pelo `ssh`, 400 kS/s, um canal, pelo USB) | O bloco de 2 MiB em ~420 ms no ARM (a cópia, o CRC e o envio; enche em 2 621 ms); remontado = o formato do cartão, com os dois CRCs; o `ssh` morto: o código 6; congelado: o código 6 em 16 s (10 s sem andar); o SIGINT: o fluxo inteiro e o código 0 | o diário de 16/11 (F4.1) |
| 17/11/2026 | **A captura contínua (F4.2) na placa de verdade**, pelo `sh_placa`, pelo USB, a 400 kS/s | 4 blocos em 3 canais: os dois CRCs certos, aberta na `api`; 12 blocos em 2 canais (31,5 s): a vazão de 0,77 MB/s (a da captura: 0,8 MB/s), o pior bloco no ARM em 388 ms, nenhuma amostra atrasada; o Parar no 3º bloco: o código 0, o cabeçalho do `ler_adc`; a conexão abortada no 3º bloco: fechada aqui com 3 blocos, e a placa sem o `ler_adc`, com a PRU parada e a `/dev/shm` vazia; a senha errada: o código 98; o `ler_adc` v0.8: o código 96 | o diário de 17/11 (F4.2) |
| 17/11/2026 | **Uma captura de 152 s pelo SSH** (58 blocos, 116 MiB, um canal, 400 kS/s; parada pelo root) | A taxa medida de 400 000,2 S/s, o pior bloco no ARM em 445 ms (de 2 621 ms), nenhuma amostra atrasada nem buffer sobrescrito; o CRC das amostras certo | idem |
| 18/11/2026 | **O "Conferir antes" (F4.3) na placa de verdade**, pelo `sh_placa`, pelo USB; o canal 1 na tomada da casa | Um bloco a 400 kS/s em **4,6 s** (2,6 s de captura); o canal 1: de −9,3169 a +9,3241 V no pino (18,64 Vpp, ~128 V rms na tomada), 60,04 Hz, 91 % da maior faixa: **as medidas do motor iguais às do `ler_adc`**, dígito a dígito; em ±2,56 V: 82 % das amostras saturadas, ✗, e a sugestão da maior faixa; os canais 0 e 1 com faixas por canal e o SPI lento a 200 kS/s: íntegra, as faixas e o SPI certos no cabeçalho, o canal 0 (sem nada) com 0,7 LSB rms; o arquivo apagado nos três | o diário de 18/11 (F4.3) |
| 18/11/2026 | **A captura na tela (F4.4) na placa de verdade**, pelo `sh_placa` e pelas contas da interface, pelo USB; o canal 1 na tomada da casa | **No computador:** 3 blocos a 400 kS/s em 9,0 s, o CRC das amostras certo e a integridade limpa; o quadro do ao vivo com 20 000 amostras (50 ms), 9,37 V de pico no pino, 60,00 Hz. **No cartão, até parar:** o Parar no 2º bloco, o código 0, a cópia pelo SFTP (4 MiB em 0,8 s) conferida pelo CRC-32. **No cartão, com a queda:** a conexão fechada no 1º bloco; 2 s depois, a conexão nova achou a captura rodando (`em_curso`) e a acompanhou até o 4º bloco; a cópia (8 MiB em 1,6 s) conferida. A placa ficou limpa | o diário de 18/11 (F4.4) |
| 18/11/2026 | **As rotinas (F4.6) na placa de verdade**, pela seção Rotinas e o terminal embutido (a placa com o `coletar.sh` da v0.8) | `calibrar --simular`: o plano inteiro (68 capturas) em 10 s; `calibrar --faixas 20.48`: até a 1ª pausa ("Mude a bancada: gerador: ONDA QUADRADA de 256 Hz…"), depois do `sudo`; `sonda --pontos 3`: até "Iniciar a coleta? [S/n]"; as duas faixas juntas, recusadas pelo próprio script (faltam 57 MB no cartão). Três abas com o nome do modo, três gravações, uma entrada no caderno por rotina | `bancada_f46.py` (fora do repositório) |
| 18/11/2026 | **1 h direto no computador (F4.7, o "pronto quando" da Fase 4)**, pelo aplicativo inteiro (a janela, sem tela), com o `ler_adc` deste branch em `~/f47`: o canal 1 na tomada de casa, 400 kS/s, ±10,24 V | 3 603 s sem queda; 1 374 blocos, 1 440 743 424 amostras (2,88 GB); o CRC das amostras confere; 0 amostras atrasadas, 0 buffers sobrescritos, 0 preâmbulos ruins, atraso máximo de 0 ciclos; a taxa medida 399 999,84 Hz; na Análise, a pirâmide em 3,8 s e o canal plotado em 0,07 s (128,7 V rms) | `bancada_f47.py` (fora do repositório) |
| 16/11/2026 | **A jornada da Aquisição na placa de verdade**, na janela (sem tela), pelo USB: em casa e na tomada do laboratório | Achada em 1,6 s; a primeira conexão (a impressão, a senha, a chave) em 2,5 e 2,6 s; o enlace com 1,0 e 0,9 ms e 4,6 e 6,6 MB/s; uma conferência de 4 MiB transferida e conferida pelo CRC em 0,91 e 0,93 s (o SFTP a 5,2 e 5,3 MiB/s); o relógio acertado com ±0,05 s, de +2,15 s e de −3 h 07 | o diário de 16/11 (F3.10) |
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

**Colhido em 15/11/2026**, com a placa no USB em casa (`$DADOS/lab/2026-11-15/`, os dois `.txt` e a captura da rede). O canal 1 na tomada: 127,7 V rms, 60,00 Hz, sem saturar na faixa de ±10,24 V.

| Item | O que o plano supõe | Na placa |
|---|---|---|
| Python 3 na placa | Existe (o agente usa só a biblioteca padrão) | **3.7.3** |
| Kernel e imagem | Debian da BeagleBoard, kernel 5.10-ti ou parecido | **4.19.94-ti-r42**, Debian 10 (Buster IoT de 2020-04-06); 1 núcleo ARMv7 |
| `mem=496M` na linha do kernel | Sim | Sim |
| Overlays carregados | O de PRU remoteproc; o de áudio do HDMI desligado ou o cape universal | `AM335X-PRU-RPROC-4-19-TI-00A0`, `BB-ADC-00A0`, `BB-BONE-eMMC1-01-00A0`; o vídeo e o áudio do HDMI desligados, o cape universal ligado (`uEnv.txt`) |
| `.dtbo` de PRU em `/lib/firmware` | Algum `*PRU-RPROC*` | Os de 4.4 a 4.19, com e sem o PRUCAPE, e o `AM335X-PRU-UIO` |
| `config-pin`, `dtc`, `avahi-daemon`, `setsid`, `systemd-run` | Existem | Todos. O `avahi-daemon` está em `/usr/sbin`, fora do `PATH` do `debian` (o `command -v` não o acha), e roda |
| O gadget USB no `lsusb` | Um dispositivo da BeagleBone (anote o VID:PID) | **`1d6b:0104`** (Multifunction Composite Gadget). O nº de série do USB é o da EEPROM (`2017BBBK382A`); a porta serial é a `/dev/ttyACM0` (interface 05, `/dev/serial/by-id/usb-BeagleBoard.org_BeagleBoneBlack_<série>-if05`) |
| A interface de rede do USB no computador | 192.168.6.x ou 192.168.7.x | As duas: a placa é a **192.168.6.2** (ECM, a do Linux; o computador, 192.168.6.1) e a 192.168.7.2 (RNDIS; o computador, 192.168.7.1). Ping de 0,6 ms |
| `beaglebone.local` resolve | Sim, pelo mDNS | Sim, para um dos dois IPs do USB: o `getent`, a **192.168.7.2**; o python-zeroconf (F3.3), ora a 6.2, ora a 7.2 (a placa responde pela interface em que a pergunta chegou primeiro) |
| Vazão do `scp` de uma captura grande | ~10 MB/s | **4,8 MB/s** (`scp` e `rsync`, 46 MiB em 10 s). Pela cifra: `chacha20-poly1305` 5,2, `aes128-gcm` 5,7 e **`aes128-ctr` 5,9 MB/s**. O limite é a cifra no único núcleo da placa (o eMMC lê a 264 MB/s): pedidos em paralelo não ajudam |
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
- **14/11/2026:** **o retorno do usuário sobre o espectro.** Ficou fluido, mas:
  - **o eixo da frequência saía errado** (um tom de 130 kHz a 400 kS/s aparecia em 377 kHz, e o traço ia além da
    Nyquist): o `TracoLOD` trocava os dados de um espectro novo e ficava com a grade do anterior (o espaçamento e o
    número de bins mudam com o trecho). `72e87af`; o teste muda o trecho três vezes;
  - **a FFT passou a ser o método padrão** (o Welch fica como segundo: os pesquisadores de potência não o usam). Sem a
    fundamental para sincronizar, a FFT é do trecho inteiro, com a Hann e um aviso;
  - **a sincronização achava uma fundamental que não existe** (65,9 Hz num tom de 130 kHz sozinho: os cruzamentos por
    zero do ruído de quantização). O motor agora exige que a fundamental tenha pelo menos 1/1000 do RMS do trecho,
    medido longe das bordas do filtro (`220e422`, `eede2c1`); a CLI deixa de sincronizar a nada também;
  - **os picos** ganharam um botão (desligado ao abrir) e deixaram de pegar o ruído: piso + 20 dB e 10 dB de
    proeminência (`c3ca56b` no motor: a proeminência opcional em `api.picos`);
  - **os valores sob o mouse** (botão, desligado) e **os cursores A e B em todas as vistas de frequência** (C), com
    Δf e Δ nível no espectro, e o encosto no pico a até 4 pixels (`0e98e3f`).
  - **Um limite anotado, sem mexer:** com a rede 26 dB abaixo de um tom forte (0,05 V de 50 Hz sob 1 V em 130 kHz),
    a f₁ dos cruzamentos erra ~0,2 Hz (o passa-baixa de 4ª ordem da busca, com o corte em 6e-4 da Nyquist, não
    atenua o tom o bastante). Com a rede a 14 dB ou menos do tom, ela acerta a 0,0002 Hz.
  - **Testes:** `ci.sh rapido` com 1 473 aprovados e `ci.sh interface` com 545; os 5 de desempenho passam.
- **14/11/2026:** **o segundo retorno do usuário** (a cara e a robustez):
  - **os cursores de todas as vistas são os da vista de tempo** (`400e26d`): `graficos/cursores.py`
    (`CursoresDaVista`) tem a lógica e a cara deles, e a vista de tempo também passou a usá-lo; as medidas dos
    cursores de qualquer vista vão para a tabela de Medidas do painel de baixo (`MedidasDaVista`), e não para um
    texto em cima do gráfico. Saiu o encosto no pico (os do tempo não têm): as setas andam um bin;
  - **os textos emendados e espremidos** (`ce66744`): o menu do projeto herdava a direção da direita para a esquerda
    do botão (a seta depois do nome) e grudava o atalho no rótulo; as barras das vistas de frequência quebram em
    linhas em vez de cortar o texto ("W...h"); a busca encolhe pela largura do próprio texto, e não por um número
    fixo. `tests/test_gui_textos.py` confere pelos size hints do Qt (vale para qualquer fonte e língua);
  - **o inspetor** declara a largura mínima do conteúdo: o dock não encolhe abaixo do que cabe (o padrão sobe para
    380 px, e a versão do layout salvo para 2);
  - **Análise, Figuras e Aquisição no centro da janela** (três colunas iguais; o nome do projeto, abreviado além de
    220 px); **o × das abas** maior e mais forte; **o espectro** sem a faixa laranja e com o texto do mouse só com o
    nível e a frequência;
  - **dois achados de robustez:** duas tarefas importando o SciPy ao mesmo tempo caíam no deadlock das travas de
    importação do Python (o aquecimento agora tem uma trava, e toda tarefa espera por ele); e uma tarefa que terminava
    depois de a janela fechar avisava um objeto apagado.
  - **Testes:** `ci.sh rapido` com 1 479 aprovados e `ci.sh interface` com 549; os 5 de desempenho passam.
- **14/11/2026 (F2.8):** os avisos nos chips, o erro inesperado e o log (seção 4c).
  - **Feito:** o log em rotação na pasta do sistema, o diálogo de erro inesperado não modal (de uma tarefa, de um
    slot, de um evento ou de outra thread) e os avisos do traço no chip, nas vistas de tempo e de espectro.
  - **Dois achados no caminho:** a correção automática de sonda dizia "a captura não registra uma sonda" quando a
    sonda estava registrada mas o perfil não servia (corrigido na etapa e no inspetor); e o chip da vista de tempo
    só ouvia a fonte enquanto a pirâmide era feita, e não via a conferência do CRC que termina depois.
  - **O teste de partida** (o `main` num subprocesso) gravaria o log na pasta de verdade: o `conftest.py` aponta
    `SH_ANALYZER_LOG` para uma pasta temporária, como já fazia com a configuração e o cache.
  - **Um teste instável pego na CI:** o do chip forçava a integridade "nao_confere" antes de a conferência de verdade
    terminar, e o "sem_crc" dela chegava depois; ele agora espera a conferência.
  - **Testes:** `ci.sh rapido` com 1 489 aprovados e `ci.sh interface` com 559; os 5 de desempenho passam.
  - **Próximo:** a F2.9 (as configurações).
- **14/11/2026:** **o terceiro retorno do usuário** (a fluidez de trabalhar no gráfico):
  - **Alt + roda** na vista de tempo amplia o tempo e o Y com o mesmo fator: a forma do sinal fica (seção 9.2 do
    plano, e na lista de gestos da paleta);
  - **uma mudança não mexe na vista** (plano, 9.2): uma etapa da cadeia, o ganho, o offset, o deslocamento, outro
    método ou outro trecho do espectro deixam o tempo e o Y onde estavam. Eram quatro causas: a vista de tempo
    reajustava o Y de propósito a cada mudança da cadeia; as faixas criadas depois ficavam com o ajuste automático do
    pyqtgraph ligado; o espectro reajustava tudo nas opções de método e de trecho; e a de harmônicos ligava o ajuste
    automático a cada desenho. Agora o Y só se reajusta quando passa a medir outra coisa (dB, RMS, dBc; amplitude ou
    densidade), e, se o traço mudado sai inteiro da vista (tirar o DC de 2,5 V), ela anda até ele com a mesma altura
    (`manter_o_y` em `graficos/faixa.py`). Ligar e desligar o eixo log do espectro mantém a mesma faixa em Hz;
  - **o clique na linha** (`graficos/clique.py`): o alcance subiu de 6 para 9 px e passou a contar até o segmento
    entre as amostras (de perto, clicar entre duas amostras não pegava) e até a coluna da envoltória (de longe). Com
    vários traços no alcance, ganha o mais perto; empatados (menos de 1 px), o de cima. Vale também nas curvas do
    espectro, que antes não se selecionavam pelo gráfico;
  - **a janela, os ciclos e o preset IEC 61000-4-7** no inspetor ("Análise do espectro"): no traço selecionado de um
    espectro, e na vista quando nada está selecionado. A janela vem da `api` (retangular, Hann, Blackman-Harris,
    flat-top, Kaiser, ou a padrão do método); os ciclos são os da FFT sincronizada (o `--fft N` da CLI). O preset põe
    o que a norma pede: FFT sincronizada, janela retangular, 10 ciclos em 50 Hz ou 12 em 60 Hz (~200 ms), com a
    fundamental medida no último espectro. **A lembrança do usuário era 12 períodos com Hann:** os 12 conferem (60
    Hz); a Hann a norma só admite sem sincronismo, e a FFT já cai nela sozinha, com aviso, quando não acha os
    cruzamentos. Os presets ficam em `PRESETS_DO_ESPECTRO` (`dados/espectros.py`), prontos para o lugar de presets
    que o usuário quer depois; cada um também é um comando da paleta;
  - **Ctrl+W** fecha a vista ativa (desfazível, como o ×).
  - **Dois testes antigos** dependiam do comportamento de antes: um esperava o Y reajustado depois de um passa-altas
    (agora a vista fica); o outro clicava "no vazio" a 7 px da linha, que o alcance novo pega.
  - **Testes:** `tests/test_gui_vistas_que_ficam.py` (9); `ci.sh rapido` com 1 498 aprovados e `ci.sh interface`
    com 568; os 5 de desempenho passam.
- **14/11/2026:** **o quarto retorno do usuário** (vários traços num gráfico, e os painéis):
  - **o eixo Y mostra o traço selecionado:** a unidade e os números dele (selecionar a corrente numa faixa com a
    tensão passa o eixo para A); com unidades ou escalas diferentes no gráfico, o rótulo fica na cor do traço que ele
    mostra. Na vista de tempo e na de espectro;
  - **a escala própria de cada traço** (`graficos/escalas.py`, plano 9.2): o cadeado na barra da vista destrava o
    selecionado (o zoom e o pan do Y passam a ser só dele, e os dos outros não o tiram do lugar), e "Mesma escala"
    devolve os traços à escala comum. É a transformação do item na caixa: os valores, as medidas e os cursores não
    mudam. Todos os gestos do Y passam por `CaixaComEscalas` (o `scaleBy` e o `translateBy` que o PyQtGraph e a
    faixa usam), e o chip mostra o cadeado. **Só o Y:** o tempo e a frequência continuam um só para todos os traços,
    porque é neles que os cursores e as medidas se alinham (o usuário pediu "x e y"; o exemplo dele era o Y da
    corrente);
  - **os painéis recolhem com uma seta** (no título dos laterais, ao lado das abas no de baixo), e o painel
    recolhido deixa a sua aba na borda da área central (`TrilhoDoPainel`): o nome de cima para baixo nos dos lados;
    embaixo, uma aba por página, com o contador;
  - **um clique numa vista do painel do projeto abre a aba dela** (e, se ela já está aberta, as propriedades dela no
    inspetor);
  - **o contador da aba de avisos conta só os não vistos:** abrir a aba os dá por vistos; ele volta só com avisos
    novos;
  - **um defeito antigo achado no caminho:** mudar um traço de faixa e desfazer o deixava fora de todas as faixas
    (ele sumia do gráfico). A faixa ainda o tinha na lista do `PlotItem`, que recusava o item de volta. Agora ele sai
    da faixa pelo `PlotItem`.
  - **Testes:** `tests/test_gui_escalas.py` (9) e `tests/test_gui_paineis.py` (8); `ci.sh rapido` com 1 520
    aprovados e `ci.sh interface` com 590; os 5 de desempenho passam.
- **14/11/2026:** **o tempo próprio do traço destravado** (o usuário pediu, depois do quarto retorno):
  - **a escala tem os dois eixos** (`Escala(x, y)`, cada um um `Afim`): na vista de tempo (`com_tempo`), o zoom e o
    pan do tempo com o destravado selecionado são só dele, e os da vista não o tiram do lugar. No espectro, a
    frequência continua uma só;
  - **o eixo do tempo mostra o último selecionado** (os números pelo tempo dele, e o rótulo na cor dele quando o
    tempo é próprio); a grade de cada faixa segue os dois eixos;
  - **o que se mede segue o tempo do traço:** `VistaDeTempo.regiao_do_traco` dá o trecho dele que aparece na região
    da tela. As medidas (`PedidoDeMedida.por_traco`; a tabela marca "tempo próprio"), o espectro, as vistas de
    bandas, espectrograma e harmônicos e a prévia do traço transformado o usam; a linha de informação e o minimapa
    também (arrastar a janela do minimapa anda o tempo do traço dele, se ele está destravado);
  - **o `TracoLOD` consulta a janela no tempo dele** (`janela_do_traco`), e a distância do clique leva em conta o
    zoom do tempo;
  - **Testes:** `tests/test_gui_escalas.py` (15); `ci.sh rapido` com 1 526 aprovados e `ci.sh interface` com 595
    (e uma falha intermitente, sem relação com esta mudança: `test_uma_tarefa_rapida_nao_perde_o_fim`, 1 em 15
    rodadas, porque o `ao_terminar` da tarefa é ligado antes do `_terminou` do gerenciador); os 5 de desempenho
    passam.
- **14/11/2026:** **a F2.9, as configurações** (seção 4c), e um teste intermitente corrigido:
  - **a tela** (Ctrl+, ou o botão de ajustes): a aparência, o separador decimal, as pastas e o cache, valendo na hora
    e gravados; os números já na tela são escritos de novo quando o separador muda;
  - **o cache** ganhou o "Limpar" e o limite de cada um, sem nunca apagar o que está aberto nem o que está sendo
    construído (antes, um limite pequeno podia apagar uma materialização ainda em construção);
  - **a pasta das sondas** vale ao abrir uma captura e ao reabrir um projeto; a dos dados, no diálogo de abrir;
  - **o teste intermitente** (`test_uma_tarefa_rapida_nao_perde_o_fim`, 1 vez em 15): cada ligação do `terminou`
    vira um evento na fila da interface, e o `ao_terminar` era ligado antes do gerenciador; às vezes o teste via a
    última tarefa ainda nas ativas. Agora o gerenciador ouve primeiro (`9768729`), e o teste confere a ordem em
    toda tarefa (passou 30 de 30 vezes).
  - **Falta da F2.9:** "as unidades" (seção 8).
  - **Testes:** `tests/test_gui_configuracoes.py` (15); `ci.sh rapido` com 1 541 aprovados e `ci.sh interface` com
    611; os 5 de desempenho passam.
- **15/11/2026:** **as unidades, o fim da F2.9** (seção 4c). O pedido: o aplicativo analisa o sinal de qualquer
  sensor, em qualquer unidade, com V, A, °C e K como as principais.
  - **a unidade de cada traço**, com o catálogo, a conversão dentro da família (°C e K, V e mV), os múltiplos (mV,
    mA, kPa) e qualquer símbolo digitado; no inspetor, a caixa da unidade e "Dois pontos…" (a escala do sensor por
    dois valores conhecidos);
  - **os eixos com o prefixo do SI** pela faixa visível ("tensão (mV)", "tempo (ms)"), desligável; a página
    **Unidades** das configurações, com as do usuário;
  - **de passagem:** a seta das caixas de escolha passou a ser a do SH-Analyzer (era a do sistema).
  - **Testes:** `ci.sh rapido` com 1 654 aprovados e `ci.sh interface` com 724; os 5 de desempenho passam.
- **15/11/2026:** **a F2.10, o que ficou da Fase 1** (seção 4c):
  - **os formatos:** o `.csv` e o `.h5` do `adc_tool` e o `.bin` legado; o legado e o `.csv` perguntam a taxa e os
    canais (o `.csv` só a taxa, quando a coluna `canal` diz os canais), guardados no projeto (o formato 3, que também
    leva as opções da vista de tempo). Os volts são os da CLI, bit a bit;
  - **copiar o cabeçalho** em texto ou em JSON;
  - **o zoom em caixa** (`Z`) e **sobrepor** os traços numa faixa;
  - **de passagem:** o teste do arrasto mostrou que o PyQtGraph ignora movimentos do mouse a mais de 100 por segundo
    (`mouseRateLimit`): um arrasto falso rápido demais vira um clique, e o do teste anda com pausas. Um `.bin` vazio
    era "sem cabeçalho" e agora é um erro, sem perguntar nada.
  - **Testes:** `ci.sh rapido` com 1 681 aprovados e `ci.sh interface` com 738; os 5 de desempenho passam.
- **15/11/2026:** **a F2.11, o fechamento da Fase 2** (seção 4c):
  - **a jornada do pesquisador** num teste de ponta a ponta, pelos gestos do usuário, com os números da CLI;
  - **o G1 com a cadeia:** reprovado durante as materializações (p95 de 22 a 33 ms). A investigação, medida a medida:
    quase nada do quadro lento estava no código da vista; o tempo de CPU da interface era um terço do de parede, e o
    `strace` mostrou as esperas no GIL. Duas contas pesadas ao mesmo tempo (os dois canais, e as medidas da janela
    visível refazendo a cadeia) eram a causa; uma de cada vez não atrapalha. A **fila das pesadas** resolveu, com o
    "na fila" no chip e no painel; e, no motor, **a curva da sonda em pedaços** (o PCHIP prendia o GIL por 33 ms);
  - **o plano e este arquivo** em dia: a Fase 2 marcada como feita, com o "pronto quando" cumprido.
  - **Testes:** `ci.sh rapido` com 1 687 aprovados e `ci.sh interface` com 743; os 6 de desempenho
    passam (o G1 com a cadeia é o novo).
- **15/11/2026:** **o duplo clique e a Fase 3 em tarefas:**
  - **o pedido do usuário:** o duplo clique levava o gráfico ao mais longe que ele ia (ajustar tudo), na vista de
    tempo e na de espectro. Agora ele não mexe no zoom, em nenhuma vista: o primeiro clique dele seleciona, como um
    clique. Ajustar tudo é o `F` (ou o botão da barra), que a vista de espectro ganhou (antes, o duplo clique era o
    único jeito de ajustá-la). As vistas de mapa não reagiam ao duplo clique. Um teste com o duplo clique de verdade
    em cada vista (`tests/mouse_de_verdade.py`, `ac0bd3d`: o `QTest.mouseDClick` não chega à cena do PyQtGraph como um duplo
    clique);
  - **a Fase 3 em tarefas** (seção 4d): F3.1 a F3.10, com o "pronto quando", a ordem e as regras da fase.
  - **Testes:** `ci.sh interface` com 745 aprovados (os 2 novos são o duplo clique).
  - **Próximo:** a F3.1, pedindo a permissão para baixar as dependências.
- **15/11/2026:** **os números dos eixos parados** (o relato do usuário: "tenho que saber a tensão e o tempo que estou
  olhando"):
  - **o defeito:** em todos os gráficos, os números dos eixos não acompanhavam o zoom, o pan (o botão do meio) nem a
    mudança de escala; só mudavam quando o prefixo do SI mudava. Veio com os prefixos nos eixos (`b946419`, a F2.10):
    com o prefixo automático, o `setRange` do PyQtGraph não invalida o desenho do eixo e conta com o
    `updateAutoSIPrefix` para isso; o do `EixoDoTema` só refazia o rótulo quando o prefixo mudava, e com ele o
    desenho. Agora o rótulo continua sendo refeito só na troca de prefixo, e os números sempre;
  - **os testes** (`tests/test_gui_eixos.py`) conferem os números pintados (`EixoDoTema.numeros`): o eixo sozinho,
    no mesmo prefixo; na vista de tempo, o zoom, a escala do Y e o arrasto de verdade com o botão do meio; nas
    vistas de espectro, bandas, espectrograma e harmônicos, o zoom. Os 6 falham sem a correção.
    `tests/mouse_de_verdade.py` ganhou o `arrastar`, que o zoom em caixa também usa;
  - **o G1 medido de novo:** os de hoje, depois de `b946419`, eram otimistas, com os eixos quase sem redesenho.
    Com eles: aprovado, mas com menos folga (p95 de 14,0 a 14,2 ms depois das materializações). Redesenhar os eixos
    custa ~1,5 ms por quadro (seção 5);
  - **de passagem:** uma corrida no teste da fila das pesadas, vista no `ci.sh rapido` (os testes em paralelo): o
    chip da materialização que começa só deixa o "na fila" quando o "começou" chega pela fila de eventos, e o teste
    não esperava por ele, como já esperava pelo painel.
  - **Testes:** `ci.sh rapido` com 1 695 aprovados e `ci.sh interface` com 751; os 6 de desempenho passam.
- **15/11/2026:** **a placa de verdade no USB, a F0.2 e a F3.1:**
  - **a placa:** o usuário a ligou no computador, com o canal 1 na tomada da casa, e deu liberdade para instalar e
    para usá-la. A chave SSH do computador foi instalada (`ssh-copy-id`), o relógio acertado (estava 2 dias
    atrasado) e o firmware atualizado (`enviar --setup`, de `v0.8-6` para `v0.8-137-g9b0ae82`: o `main` mais o
    agente). **A rede da casa:** 127,7 V rms, 60,00 Hz, sem saturar; já com supraharmônicos de verdade (uma
    componente em 40,0 kHz, ~81 mV no pino × o divisor, antes da correção da cadeia). As capturas estão em
    `$DADOS/lab/2026-11-15/` e saíram da placa depois do CRC conferido;
  - **a F0.2** (seção 6), com o que muda na Fase 3: o kernel 4.19, o nº de série da EEPROM no USB, o mDNS só na
    192.168.7.2 e a vazão de ~5 MB/s, presa à cifra no único núcleo da placa;
  - **a F3.1** (seção 4d): o laço `asyncio` numa thread própria, a ponte para a interface, o extra e o job `placa`.
    Conferida também na placa, onde achou um defeito do diagnóstico (a PRU parada entre capturas, `0997175`);
  - **de passagem:** o `ci.sh placa` troca o Python do `.venv` (3.10 e 3.13), e o `rapido` depois dele rodou sem o
    PySide6, como o job `testes` do GitHub: o `test_gui_atalho.py`, que diz "sem Qt", falhava inteiro na importação
    (`12cdd32`). E um teste novo do laço que dependia da carga da máquina (ele achava que segurava o laço, e não
    segurava), corrigido e conferido 15 vezes com os 8 núcleos ocupados.
  - **Testes:** `ci.sh rapido` com 1 716 aprovados, `ci.sh interface` com 759 e `ci.sh placa` com 129 em cada
    Python.
  - **Próximo:** a F3.2, a conexão SSH (com a placa de verdade além do servidor do teste).
- **15/11/2026:** **a F3.2, a conexão SSH, as chaves e o registro** (seção 4d):
  - **a decisão:** o agente vai pelo stdin (`python3 -`), e não da pasta do firmware da placa. Ele fala sempre o
    protocolo do aplicativo, e uma placa com o firmware antigo é diagnosticada em vez de responder outro protocolo
    (o plano, 11.2, mudou);
  - **o que a placa de verdade mostrou:** a impressão digital da primeira conexão não era nenhuma das que o `ssh` do
    usuário conhecia (o asyncssh negocia o RSA primeiro; agora é o ED25519, como o OpenSSH). E o servidor do teste
    mostrou que a queda no meio de um comando volta do asyncssh sem erro;
  - **na placa:** a primeira conexão com a senha, a chave instalada, a segunda só com a chave, o agente pelo stdin e o
    diagnóstico sem nada; a chave de teste saiu da placa depois.
  - **Testes:** `ci.sh placa` com 146 em cada Python, `ci.sh rapido` com 1 411 (sem o Qt, como o job `testes`) e
    `ci.sh interface` com 759.
  - **Próximo:** a F3.3, a descoberta (o USB, o mDNS e o IP).
- **15/11/2026:** **a F3.3, a descoberta das placas** (seção 4d):
  - **na placa de verdade:** o USB (a serial e os dois IPs) e o mDNS juntos numa placa só, com o nº de série e a
    chave de host certos; a chave lida uma vez e guardada entre as varreduras;
  - **o que a placa mostrou:** o mDNS responde com o IP da interface em que a pergunta chegou primeiro, ora a
    192.168.6.2, ora a 192.168.7.2. A F0.2 dizia "só a 7.2", pelo `getent` de um dia; a descoberta não depende disso,
    porque sonda os dois IPs do USB;
  - **o log:** o asyncssh escreve ~14 linhas de INFO por varredura, que o log do aplicativo não grava (só os avisos
    das bibliotecas), como deve ser numa varredura que se repete;
  - **de passagem:** o servidor SSH do teste deixava vivo, por 30 s depois do teste, o `sleep 30` do teste do tempo
    esgotado (F3.2): o `dash` não faz `exec` do último comando, e matar o shell deixava o `sleep` com os pipes
    abertos. Aparecia só no Python 3.10, como um aviso do coletor de lixo num teste qualquer depois dele (um GC
    depois de cada teste achou o dono). Agora cada comando roda num grupo de processos, morto inteiro, e o `parar`
    só volta com todos colhidos.
  - **Testes:** `ci.sh placa` com 156 em cada Python, `ci.sh rapido` com 1 421 e `ci.sh interface` com 760.
  - **Próximo:** a F3.5, a área de Aquisição e a lista de placas.
- **15/11/2026:** **a F3.4, o agente completo** (seção 4d):
  - **na placa de verdade:** cada fato da saúde conferido à mão (o firmware instalado na PRU igual ao da pasta, o
    protocolo 5, o `adjtimex` sem sincronizar, as ferramentas e os pacotes delas);
  - **o que a placa mostrou:** o `/proc/iomem` sem os endereços para o `debian`; o `mem=496M` no `optargs`, e não no
    `cmdline`; o systemd 241 sem o `--grep` (o diário inteiro levava 3,4 s; pelos índices, 0,1 s); o `find_library`
    do `ctypes` rodando o `ldconfig` (~0,2 s); e **o relógio medido contra a chegada da resposta, 35 a 70 ms abaixo
    do de verdade**, pela partida e pelo fim do Python na placa. Agora fica entre dois limites, conferidos contra um
    pingue-pongue;
  - **de passagem:** a primeira chamada numa conexão nova leva ~1 s a mais na placa (a sessão do sshd), o que a F3.5
    pode esconder conectando antes de a pessoa pedir.
  - **Testes:** `ci.sh placa` com 224 em cada Python, `ci.sh rapido` com 1 489 e `ci.sh interface` com 760.
  - **Próximo:** a F3.5, a área de Aquisição e a lista de placas.
- **16/11/2026:** **a F3.5, a área de Aquisição e a lista de placas** (seção 4d):
  - **a decisão da janela:** os painéis do Estúdio são da Análise. Em vez de esconder os docks ao trocar de área (e
    salvar o layout errado, e deixar o Ctrl+B mexer num painel escondido), a Análise virou uma `QMainWindow` dentro
    da janela, com os docks e os atalhos dela; o Qt não dispara o atalho de uma ação sem widget visível, e o Delete na
    Aquisição não apaga traços da Análise;
  - **o que as capturas mostraram** (sem tela, cada página do diálogo e a área, nos dois temas): o texto das caixas de
    marcar não quebra e era cortado (agora o rótulo curto e a explicação embaixo); a `QStackedWidget` dava a todas as
    páginas a altura da mais alta (agora uma coluna com só a página da vez); o nome "Simulador (BeagleBone Black)"
    cortado na lista e no chip; e o simulador marcado como "conectada" junto da placa do servidor de teste, que tem o
    mesmo nº de série (o simulador nunca mais se junta a uma placa);
  - **um erro meu, corrigido:** duas rodadas do script de capturas rodaram sem uma configuração temporária e
    gravaram uma placa falsa nas placas conhecidas da configuração do usuário (a chave `placa/conhecidas`, que só
    tinha ela, foi apagada; o resto ficou como estava). Os scripts fixam o `SH_ANALYZER_CONFIG` agora;
  - **de passagem:** o servidor SSH do teste deixava, no Python 3.10, o pipe de um comando cortado no meio aberto até
    o coletor de lixo (um aviso, em 2 de 8 rodadas do teste do enlace): agora lê o que sobrou depois de matar o grupo.
  - **Testes:** `ci.sh placa` com 242 em cada Python, `ci.sh rapido` com 1 842 e `ci.sh interface` com 772.
  - **Próximo:** a F3.6, a visão geral e o diagnóstico.
- **16/11/2026:** **a F3.6, a visão geral e o diagnóstico** (seção 4d):
  - **o que a placa mostrou:** o relógio deriva ~2,6 s por dia sem NTP (de +0,5 s para +1,14 s em seis horas), o que
    justifica o acerto a cada conexão; a placa não tem sensor de temperatura; o `config-pin` não precisa de sudo; e
    **o aviso "firmware de outra versão" era falso**: o `git describe` muda a cada commit, e o código do firmware é o
    mesmo. Agora a comparação é pelo código;
  - **o que as capturas mostraram:** a vazão do enlace pela metade (3,2 MB/s) quando a leitura das capturas rodava
    junto (um núcleo só): agora uma coisa por vez; e "estava 0,04 s adiantado; agora, −0,04 s", que parecia não ter
    acertado (a estimativa é o meio de uma faixa de ±0,05 s que cerca o zero): agora "está certo, dentro do limite
    da medida";
  - **um erro meu, corrigido:** o relatório comparava o relógio com a hora dele, e não pelos limites da resposta
    (dava −0,09 s, e a tela, −0,04 s).
  - **Testes:** `ci.sh placa` com 262 em cada Python, `ci.sh rapido` com 1 873 e `ci.sh interface` com 783.
  - **Próximo:** a F3.7, os arquivos e a transferência.
- **16/11/2026:** **a F3.7, os arquivos e a transferência** (seção 4d):
  - **o pedido:** "a PRU usa a memória RAM igual ao processador principal: fazer streaming do arquivo assim pode de
    algum jeito atrapalhar as medições?". Medido na placa (13 capturas, a tomada no canal 1): não, em nada que se
    meça (a seção 4d tem os números). A fila espera as capturas assim mesmo;
  - **o que a placa mostrou:** o SFTP pipelinado chega ao teto da cifra (5,2 MiB/s) com 8 pedidos em voo; a cópia
    de uma captura de 4 MiB, com a conferência, leva 1,1 s;
  - **um erro meu, corrigido:** no primeiro lote do teste de carga, o `kill` do subshell não matou o `ssh` filho, e
    uma carga continuou nas capturas seguintes (só a comparação A1 × B1 daquele lote valeu); o segundo lote rodou
    cada carga como um processo próprio, com a placa conferida sem carga antes de cada captura. E dois testes
    conferiam a `/dev/shm` inteira, o que falhava rodando em paralelo: cada servidor de teste tem a sua agora.
  - **Testes:** `ci.sh placa` com 269 em cada Python, `ci.sh rapido` com 1 886 e `ci.sh interface` com 789.
  - **Próximo:** a F3.8, o terminal.
- **16/11/2026:** **a F3.8, o terminal** (seção 4d):
  - **as decisões:** o `pyte` interpreta, e a tela é nossa (a rolagem, a tela alternativa e o redimensionamento que
    o `pyte` não tem, pintados com os tokens do tema); a saída em fatias de 8 ms, para um `cat` grande não travar a
    janela; uma gravação por aba, para as saídas não se misturarem; a aba que caiu com o cabo reabre sozinha; fechar
    uma aba com o `ler_adc` rodando pergunta antes (a captura começada nela morreria junto);
  - **o que a placa mostrou:** o PTY da primeira aba nascia em 80 × 24, antes do layout (corrigido); o resto, como
    no servidor do teste: os atalhos, o `sudo` do `coletar.sh conferir`, o `less`, o Ctrl+C e o código de saída pelo
    OpenSSH;
  - **um erro meu, corrigido:** o primeiro teste da seção esperava o prompt com o espaço do fim, que o texto da tela
    tira; e o fechar da última aba abria outra na mesma hora (agora a aba nova vem só com a placa chegando ou com a
    seção aparecendo, e sem abas há o "Abrir um terminal");
  - **de passagem:** no `ci.sh rapido`, o `pgrep -x ler_adc` do servidor do teste via o `ler_adc` falso de outro
    teste rodando em paralelo (os comandos rodam neste computador); o `pgrep` de cada placa falsa vê agora só os
    processos do teste dela. E o `test_gui_eixos` das harmônicas falhou uma vez com a máquina cheia (os números do
    eixo X vazios já antes do zoom): passa sozinho, e fica anotado.
  - **Testes:** `ci.sh placa` com 275 em cada Python, `ci.sh rapido` com 1 915 e `ci.sh interface` com 810.
  - **Próximo:** a F3.9, o simulador com os cenários.
- **16/11/2026:** **a F3.9, o simulador com os cenários** (seção 4d):
  - **as decisões:** o simulador é uma placa servida por SSH neste computador, com o agente de verdade, e não um
    transporte local: a interface passa pelo mesmo caminho da placa (a chave, o SFTP, a retomada, o registro); as
    capturas simuladas têm o formato e os sinais do firmware; os cenários de configuração da F0.10 ficam junto dos do
    plano, num grupo à parte;
  - **o que a tela mostrou:** as tarefas sem dono do asyncssh na queda (corrigido no `sftp.py`, com o teste) e o
    resumo do ADC mudo que repetia o aviso;
  - **o que a placa mostrou:** o OpenSSH 7.9 sem o `limits@openssh.com` (pedidos de 16 KiB) e a vazão igual à de
    antes da troca do leitor;
  - **para o instalador:** o agente fora do pacote do PyInstaller (seção 4d, F3.9).
  - **Testes:** `ci.sh placa` com 309 em cada Python, `ci.sh rapido` com 1 576 e `ci.sh interface` com 819. O
    `rapido` rodou depois do `placa`, e o `uv run --extra dev` tirou do ambiente o Qt e o asyncssh: os testes deles
    ficaram para os passos próprios (a contagem não se compara com a dos dias anteriores).
  - **Próximo:** a F3.10, o fechamento da Fase 3.
- **16/11/2026:** **a F3.10, o fechamento da Fase 3** (seção 4d). **A Fase 3 está feita:** a jornada da Aquisição
  roda de ponta a ponta com o simulador e rodou na placa de verdade, em casa e no laboratório:
  - **o pedido:** "sim, e faça a F3.10" (o título nos Arquivos antes), e, no meio, "tentei rodar o software, apenas
    usando um pouco ele já crasha" ("deallocating None");
  - **o que a placa mostrou:** no laboratório, a placa que volta desligada (o relógio 3 h 07 atrasado, os pinos no
    `default`): o diagnóstico e o "Acertar…" fazem o que devem, e o `ler_adc` configura os pinos sozinho. A tomada do
    laboratório tem uma emissão em ~18 kHz com os múltiplos;
  - **um erro meu, corrigido:** o `simulador.py` da F3.9 com o asyncssh, que a CI completa pegou (o `rapido` daqui
    passava porque o `.venv` ainda tinha o asyncssh). E o `ci.sh` completo, interrompido no passo da 3.10, deixou o
    `.venv` do worktree na 3.10, onde o defeito do PySide6 6.12.0 derruba a interface: o usuário a abriu dali. O
    extra `gui` agora pede o 6.11 na 3.10 e na 3.11. O mesmo pedido faltou no bloco PEP 723 do `adc_tool.py`, e o
    `test_dependencias` da CI completa pegou;
  - **Testes:** o `ci.sh` completo passou: 1 713 em cada Python (58 pulados: os do Qt e do asyncssh, que têm os seus
    jobs, os de desempenho e os do compilador de 32 bits), o `placa` com 310 em cada Python e a interface com 822 na 3.13 (8 pulados: os de
    desempenho e o do None, que só vale na 3.10 e na 3.11). A interface na 3.10, com o PySide6 6.11.3: 823.
  - **Próximo:** a Fase 4, a captura: quebrá-la em tarefas (seção 4e).
- **16/11/2026:** **a Fase 4 em tarefas e a F4.1** (seção 4e):
  - **o pedido:** "faça o que for melhor para o projeto. continue o desenvolvimento";
  - **antes, a causa do "deallocating None" resolvida de vez:** o `ci.sh` usa `.venv-ci/<versão>` com `--exact`
    (`03cac5e`), e o `.venv` do worktree não muda mais de Python nem de pacotes (conferido: o mesmo `pyvenv.cfg` antes
    e depois da CI completa). De quebra, o job `placa` ficou de fato sem o Qt (antes, o que o ambiente tinha de outra
    etapa passava);
  - **a seção 4e:** sete tarefas, do firmware ao fechamento, com a ordem e as regras (o formato do `.bin` só pelos
    dois lados juntos; o ao vivo anda de bloco em bloco: 2,6 s a 400 kS/s);
  - **a F4.1:** o `ler_adc -o -`, o código 6 e o `--progresso-json` (`7551d7e`), validados na placa. A bancada achou
    o que o teste não acharia: o cabo que sai não fecha o pipe na placa, e o `write` ficaria preso por ~15 min;
  - **Testes:** os do firmware (101, com os 8 novos). O `ci.sh` completo, antes da F4.1 (tudo certo, com os ambientes
    novos) e depois dela: 1 721 em cada Python (eram 1 713), o `placa` com 310 e a interface com 822, e o `.venv`
    intocado nas duas.
  - **Próximo:** a F4.2.
- **17/11/2026:** **a F4.2, a captura contínua no computador, sem Qt** (seção 4e):
  - **o pedido:** "Sim, comece" (a F4.2, depois da F4.1);
  - **a ordem dos commits, por componente:** o motor (o fechamento, `1257f5b`), o `sh_placa` (a captura, `4c85596`),
    o simulador (o `ler_adc` dele, `e849e12`) e, depois da bancada, o `sh_placa` de novo (o Parar, `0b543cf`). A marca
    no cabeçalho foi na véspera, com o C (`a4f97b0`);
  - **o que a placa mostrou:** o Parar não parava. O `kill -INT` no `sudo` dava "Operation not permitted" (o sudo
    roda inteiro como root), e o simulador não o mostraria (o `sudo` dele é um `exec`). O leitor do Parar foi para um
    shell de root. Os dois testes à parte que deixei presos na placa (um `wait` no sudo) foram encerrados e as pastas
    deles na `/dev/shm` apagadas (só com o askpass, sem a senha); a placa ficou limpa;
  - **na placa, de quebra:** uma captura de 152 s pelo SSH (58 blocos, nenhuma amostra atrasada) e um `.parcial`
    deixado por um teste cortado, recuperado com os 37 blocos e o CRC certo;
  - **Testes:** o `ci.sh` completo passou: 1 741 em cada Python (eram 1 721), o `placa` com 329 (eram 310) e a
    interface com 824 (eram 822); o `.venv` intocado (o mesmo `pyvenv.cfg` antes e depois).
  - **Próximo:** a F4.3, o formulário de captura.
- **18/11/2026:** **a F4.3, o formulário de captura** (seção 4e):
  - **o pedido:** "sim, faça o F4.3", com o canal 1 agora na tomada da casa do usuário;
  - **a ordem dos commits, por componente:** o `sh_placa` (o pedido, `fbded87` e `d4d5929`), o simulador (a linha de
    comando do C, `ca61759`), a interface (os modelos no `.shproj` v4, `5d67657`), o motor (a conferência,
    `4c87c77`), o `sh_placa` (o "Conferir antes", `2d8c826`) e, depois da bancada, o motor (`d64e42a`), o `sh_placa`
    (as mensagens, `d1f7d0e`), o simulador (o disco, `92bb000`) e a interface (a seção, `384e811`, e a linha da
    sugestão, `81cbc1c`);
  - **o desenho antes do código** (a seção 4e): o pedido sem Qt e com contrato contra o C, e o "Conferir antes" com o
    pedido do próprio formulário, e não o `coletar.sh conferir` (uma faixa para todos os canais, dois SPIs, texto);
  - **o que a placa mostrou:** as medidas iguais às do `ler_adc`; o canal saturado sem sugestão de faixa, a tomada
    sem folga sem aviso e o "mais resolução" na faixa maior (os três corrigidos, seção 4e). O simulador dizia o cartão
    cheio na saída contínua (0 KiB em vez de "desconhecido"), e o teste da seção o pegou;
  - **a placa ficou limpa:** a `~/f43` apagada, nenhum `ler_adc` rodando, a `/dev/shm` vazia, a captura do usuário
    (`FEM_*.bin`) intocada. O relógio dela estava ~37 h atrasado (desligada sem bateria); a conferência não depende
    dele, e o "Acertar…" da visão geral resolve ao conectar pelo aplicativo;
  - **Testes:** o `ci.sh` completo passou: 1 919 em cada Python (eram 1 741), o `placa` com 477 (eram 329) e a
    interface com 850 (eram 824); o `.venv` intocado (o mesmo `pyvenv.cfg` antes e depois).
  - **Próximo:** a F4.4, a captura na tela.
- **18/11/2026 (depois):** **a F4.4, a captura na tela** (seção 4e, o desenho em `a05fb03`):
  - **o pedido:** "Faça a F4.4", e depois "termine a F4.4 e faça a F4.5";
  - **a ordem dos commits, por componente:** o `sh_placa` (o cartão e o nome, `1472519`), o motor (o
    `abrir_ao_vivo`, `dcfd8f1`) e a interface (o serviço, o ao vivo e o cockpit, `080f78b`; os testes, `7a21de5`; o
    que a imagem sem tela mostrou, `5365d8e`; o import do motor, `4c961dd`);
  - **o que a imagem sem tela mostrou:** a barra de estado cortava o Parar, os gráficos ao vivo empurravam o
    espectro para baixo da dobra, o nome do canal em pé era mais alto que o gráfico, a saída do `ler_adc` rolava de
    lado no cartão, e a captura do cartão, trazida e conferida, não mostrava o "Abrir na Análise" (os cinco corrigidos,
    seção 4e);
  - **o que a placa mostrou** (seção 5): as três capturas como no simulador, sem correção nenhuma. O `ler_adc`
    deste branch foi compilado em `~/f44` com `-Werror` e apagado depois; nenhum `ler_adc` rodando, a captura do
    usuário (`FEM_*.bin`) intocada, 1,5 GB livres como antes;
  - **o que a CI mostrou:** o `ao_vivo.py` importava o pacote do motor (`from supraharmonicos import api`), e o teste
    da arquitetura o recusa (`4c961dd`). A CI completa de novo fica para o fim da F4.5 (a segunda rodada foi
    interrompida: ela rodava sobre a árvore enquanto a F4.5 era escrita);
  - **achado de quebra:** três `ler_adc` da PRU falsa presos havia ~3 h neste computador, de rodadas dos testes do
    cartão que falharam durante o desenvolvimento (o `setsid` os solta da conexão, de propósito, e a PRU falsa morre
    com o teste). Foram encerrados; a correção vem com a F4.5 (o simulador que para leva as capturas no cartão
    junto);
  - **Testes:** `tests/test_gui_captura_na_tela.py` (9) e os do cartão no `sh_placa` (46 com os do simulador e os da
    tela, juntos), mais os 29 da seção, da área e da captura na tela juntos.
  - **Próximo:** a F4.5, o caderno de bancada.
- **18/11/2026 (noite):** **a F4.5, o caderno de bancada** (seção 4e, o desenho em `b26b1f4`):
  - **o pedido:** "termine a F4.4 e faça a F4.5";
  - **a ordem dos commits, por componente:** o simulador (a placa simulada que para leva as capturas no cartão
    junto, `2dbc88e`) e a interface (o caderno na Aquisição e a seção Notas do projeto, `6c27347`);
  - **o que a imagem sem tela mostrou:** a 1 440 px, o cockpit não cabia ao lado do caderno (mínimo de 471 px; o
    "Nova captura" subiu para o cabeçalho, e o rótulo do espectro e o título do fim quebram a linha: 398 px), as
    entradas emendavam umas nas outras e as linhas marcadas saíam com "• ✓" (agora parágrafos, só com a marca
    colorida), e o "671.7 LSB" da F4.3 usava ponto (agora `decimal`);
  - **isolamento:** o `conftest.py` aponta o `$DADOS` para uma pasta temporária, e nenhum teste escreve no
    `anotacoes.md` de verdade;
  - **a placa:** não precisou (o caderno não fala com ela; as entradas vêm dos sinais dos serviços, já validados na
    F4.4);
  - **Testes:** o `ci.sh` completo passou: 1 922 em cada Python (eram 1 919), o `placa` com 487 (eram 477) e a
    interface com 876 (eram 850); o `.venv` intocado. A etapa da interface levou 52 min em série (`-n 0`), o que
    levou à revisão da CI logo a seguir.
  - **Próximo:** a F4.6.
- **18/11/2026 (noite, depois):** **a revisão da CI** (o pedido: "As CIs estão demorando muito, faça uma revisão para
  agilizar muito o tempo de execução, simplifique os testes e remova redundâncias"):
  - **o vazamento das janelas** (`e43da75`): o `deleteLater` das fixtures nunca apagava nada (fora de um laço de
    eventos, o `processEvents` não apaga), e cada teste deixava a janela viva (~1 200 widgets, as pirâmides abertas);
    o tema de cada teste novo passava por todas, e a interface em série chegou a 52 min. O `conftest.py` agora apaga
    o que foi mandado apagar ao fim de cada fixture e acusa a janela do aplicativo que ficou viva (três testes a
    deixavam: a `Bancada` da captura na tela, o seletor de unidade e uma janela de layout);
  - **as somas termo a termo:** a quadrada filtrada do `medir_sinal` por uma `irfft` (`fff33fd`, 128 s para 0,2 s) e as
    quadradas sintéticas por uma chirp-z em blocos (`cf56f39`, os mesmos códigos, até 100 vezes mais rápidas);
  - **redundância:** o coletar sonda de um canal sem o CRC e o tamanho, que não dependem do canal (`f430d55`);
  - **o `ci.sh`** (`ec2807e`): uma rodada do pytest por Python (o `sh_placa` junto, a etapa `placa` e o job dela
    saíram), a interface em paralelo (o `-n 0` saiu), um ambiente por Python e por Qt (o `--exact` não reinstala o
    PySide6 a cada etapa) e o BLAS com uma thread por processo do xdist;
  - **Testes:** o `ci.sh` completo em 307 s (era ~25 min, e a última rodada levou ~70): 2 431 em 3.13 com a
    interface (190 s) e 2 004 em 3.10 sem o Qt (105 s); a interface sozinha, em paralelo, em 94 s; o `.venv` intocado.
  - **Próximo:** a F4.6.
- **18/11/2026 (madrugada):** **a F4.6, as rotinas do `coletar.sh` pelo terminal** (seção 4e, o desenho em `15902d1`):
  - **o pedido:** "Faça a F4.6";
  - **a ordem dos commits, por componente:** o `sh_placa` (as rotinas, `2a129fc`; o terminal com a entrada inicial,
    `2a592ff`) e a interface (a seção Rotinas, `dcf011a`);
  - **o que a imagem sem tela mostrou:** o painel das opções tinha a altura do maior modo (o `QStackedWidget` guarda
    a dica da página maior mesmo com a política `Ignored`), e os campos de um modo curto ficavam espalhados; agora o
    painel guarda só o formulário do modo escolhido;
  - **o que a placa mostrou** (seção 5): a calibração com as duas faixas não cabe no cartão (o script recusa:
    faltam 57 MB, com a captura `FEM_*.bin` do usuário ocupando o espaço); com uma faixa, ela chega à primeira pausa.
    A pasta `CAL_*` que a rotina interrompida deixou (só o `log.txt` e o `resumo.csv`, sem captura) foi apagada; a
    captura do usuário intacta, 1,5 GB livres como antes, nenhum `ler_adc` rodando;
  - **Testes:** `tests/test_sh_placa_rotinas.py` (19: a tabela contra a ajuda de cada modo, o comando, os recusados
    e os comandos montados rodando com `--simular` no `coletar.sh` do repositório) e `tests/test_gui_rotinas.py` (2:
    o formulário pelo pedido e a rotina numa aba nova do servidor SSH dos testes, com o plano na tela, o caderno e a
    ajuda da placa). O `ci.sh` completo passou em 310 s: 2 452 em 3.13 com a interface (eram 2 431) e 2 023 em
    3.10 sem o Qt (eram 2 004); o `.venv` intocado.
  - **Próximo:** a F4.7.
- **18/11/2026 (madrugada, depois):** **a F4.7, o fechamento da Fase 4** (seção 4e, o desenho em `58f59c2`):
  - **o pedido:** "faça a F4.7";
  - **os commits:** a interface (a pasta do firmware na captura direto no computador, `dcc1db0`; a jornada da captura
    de ponta a ponta, `5e3249c`) e os docs (o plano e este arquivo);
  - **o que a bancada mostrou primeiro:** com o `ler_adc` novo em `~/f47`, a captura direto no computador ainda
    dizia "atualize o firmware": o serviço passava a pasta do firmware só para a captura no cartão. Corrigido, com o
    teste que a confere nos dois destinos;
  - **a placa** (seção 5): o aplicativo inteiro na janela sem tela, 1 h da tomada de casa a 400 kS/s, sem queda do
    cabo; o CRC confere, a integridade é zero, as amostras são as pedidas (1 374 blocos inteiros), e a captura abre na
    Análise em 3,8 s (a pirâmide) com a tensão de 128,7 V rms. O `ler_adc` deste branch foi compilado em `~/f47` com
    `-Werror` e apagado no fim; nenhum `ler_adc` rodando, a captura do usuário intacta, 1,5 GB livres como antes. A
    captura de 1 h (2,9 GB) ficou fora do repositório, na pasta de rascunho da sessão;
  - **Testes:** `tests/test_gui_jornada_captura.py` (1, na janela, ~14 s) e o caso novo em
    `tests/test_gui_captura_na_tela.py` (a pasta do firmware nos dois destinos). O `ci.sh` completo passou em
    311 s: 2 454 em 3.13 com a interface e 2 023 em 3.10 sem o Qt; o `.venv` intocado.
  - **Próximo:** a Fase 5, a quebrar em tarefas (seção 4f).
- **18/11/2026 (quase meia-noite):** **a medição de 1 h guardada e a F5.1** (o pedido: "guarde essa medição na minha pasta de dados em
  documentos, depois continue o desenvolvimento da GUI"):
  - **a medição:** `~/Documents/sh-analyzer-data/lab/2026-11-18/f4_7_1_h_da_tomada_20261118_221756.bin` (movida da
    pasta de rascunho, o CRC conferido de novo no lugar novo), e as duas entradas automáticas dela no `anotacoes.md`
    do dia (o começo, com o comando, e o fim, com o resumo), com o caminho novo;
  - **a Fase 5 em tarefas** (seção 4f, `933cf3f`): o modelo, o desenho, a tela, a exportação da figura, a dos dados
    e o pacote primeiro (o caminho até o "pronto quando"), o estilo, os insets e as anotações depois;
  - **a F5.1** (`5e4e545`, a seção 4f diz o quê e as decisões);
  - **Testes:** `tests/test_gui_figura.py` (25). O `ci.sh` completo passou em 322 s: 2 479 em 3.13 com a interface
    e 2 047 em 3.10 sem o Qt; o `.venv` intocado.
  - **Próximo:** a F5.2.
- **19/11/2026 (madrugada):** **a F5.2 e a F5.3** (o pedido: "faça a 5.2 e 5.3"):
  - **a F5.2** (`4972da3`, `01395a4`, `9fca9ec`): o desenho da figura com o Matplotlib, sem Qt; o prefixo do SI foi
    para `dados/unidades.py` (o desenho não pode importar os componentes); a fidelidade medida (seção 4f): 1 pixel de
    Hausdorff, ~5 % da tinta na borda do traço;
  - **a F5.3** (`03a171e`, `6e4a7d7`, `0b64c40`): a área Figuras, a jornada da figura pelos gestos (da vista à página,
    um segundo painel congelado, a vista que muda, o desfazer, salvar e abrir de novo com a mesma página) e o espectro
    que vira figura com o que a vista calculou;
  - **Testes:** `tests/test_gui_desenho_da_figura.py` (15), `tests/test_gui_figuras.py` (6) e
    `tests/test_gui_jornada_figura.py` (2); o `test_gui_janela.py` com as Figuras habilitadas; e o `test_gui_eixos.py` espera os números do eixo dos harmônicos antes de medir (a primeira rodada da CI os mediu vazios, sob carga). O `ci.sh` completo
    passou em 324 s: 2 502 em 3.13 com a interface e 2 062 em 3.10 sem o Qt; o `.venv` intocado.
  - **Próximo:** a F5.4 (a exportação da figura).
- **19/11/2026 (madrugada, depois):** **a F5.4** (o pedido: "faça a F5.4"; a seção 4f diz o quê e as decisões):
  - a exportação sem Qt (`d62a619`) e os testes de cada formato (`e260379`); a área de transferência que não derruba
    o aplicativo na saída (`2e01ec9`); a seção Exportar (`ce671f8`) e os testes pela janela (`b87759b`);
  - **Testes:** `tests/test_gui_exportar_figura.py` (20), `tests/test_gui_area_de_transferencia.py` (2) e um caso
    novo em `tests/test_gui_jornada_figura.py`. O `ci.sh` completo passou em 333 s: 2 525 em 3.13 com a interface
    e 2 082 em 3.10 sem o Qt; o `.venv` intocado.
  - **Próximo:** a F5.5 (a exportação dos dados).
---

## 8. Perguntas em aberto

São as do plano, seção 19. Não bloqueiam a Fase 0:

- o tema padrão na primeira execução;
- a ordem das versões (Aquisição antes de Figuras);
- a regra de sudo sem senha na placa;
- o inglês na v1.0;
- a assinatura de código no Windows.

