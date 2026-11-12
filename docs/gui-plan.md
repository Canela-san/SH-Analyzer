# Plano da interface gráfica do SH-Analyzer

O plano da **interface gráfica (GUI)** para analisar as capturas do SH-Analyzer. Ele cobre:

- os objetivos;
- as decisões de tecnologia;
- a arquitetura;
- as telas;
- o sistema de design;
- o orçamento de desempenho;
- a qualidade e a distribuição;
- o roteiro por fases.

O trabalho acontece no branch `feat/interface`, criado a partir do `main`. O `feat/GUI` guarda um protótipo anterior, que não faz parte deste plano e não vai para o `main`. A GUI estreia na **v0.9**; a **v1.0** é a GUI completa.

**Escrito em 12/11/2026, sobre a v0.8.**

---

## 1. Objetivo e princípios

Um aplicativo de desktop para Windows e Linux em que um pesquisador abre as capturas do SH-Analyzer, vê a forma de onda e o espectro, mede supraharmônicos e exporta figuras e números para um artigo, sem usar a linha de comando.

"Profissional, otimizado e bonito" vira critério verificável:

| Qualidade | O que significa aqui | Como se confere |
|---|---|---|
| **Profissional** | Os números são os mesmos da linha de comando, cada resultado diz de onde veio, e nenhum aviso do motor some | Testes de paridade com a CLI; proveniência em toda exportação |
| **Otimizado** | A tela nunca congela, e capturas de horas abrem em segundos | O orçamento de desempenho (seção 7), medido em testes |
| **Bonito e moderno** | Um sistema de design próprio (cores, tipografia, espaçamento, movimento), temas claro e escuro, feito com intenção | A galeria de componentes e a revisão das telas nos dois temas |

Seis princípios guiam as decisões:

1. **Um motor só.** A GUI não reimplementa análise: chama o pacote `supraharmonicos`, o mesmo da CLI. Um número na tela é o número da CLI.
2. **A tela nunca trava.** Todo cálculo que pode passar de ~16 ms roda em segundo plano, com progresso e cancelamento.
3. **Tudo reprodutível.** Cada figura e cada tabela exportada levam a captura (id e CRC do cabeçalho v9), os parâmetros, as versões e o **comando da CLI equivalente**.
4. **A confiabilidade fica à vista.** A integridade da captura, a faixa válida do perfil da sonda, a saturação e o aliasing provável aparecem na tela, não num log.
5. **Beleza por sistema, não por enfeite.** Tokens de cor, tipografia e espaçamento aplicados de forma consistente. As animações explicam uma mudança; não decoram.
6. **Windows e Linux iguais.** O mesmo código, testado nos dois a cada release.

---

## 2. Quem usa e para quê

| Perfil | O que faz | Jornada que tem de ser curta |
|---|---|---|
| **Pesquisador** do grupo | Analisa capturas de campo ou de laboratório | Abrir a pasta do dia → escolher a captura → espectro de 2 a 150 kHz e bandas → exportar a figura e a tabela |
| **Estudante na bancada** | Calibra cadeias e sondas, confere capturas | Abrir uma pasta `CAL_` → conferir a coleta (resumo e integridade) → medir a fase → ver o Bode e o ajuste → gravar o perfil |
| **Orientador ou revisor** | Confere resultados | Abrir um projeto → comparar capturas → ver a proveniência de cada número |

A meta: cada jornada principal em **até 5 ações** a partir da tela inicial, sem ler o manual.

---

## 3. Decisões de tecnologia

| Componente | Escolha | Por quê | Descartado |
|---|---|---|---|
| Linguagem | **Python ≥ 3.10** | O motor (`supraharmonicos`) já está em Python; a GUI o chama direto | Reescrever a análise em outra linguagem |
| Toolkit | **PySide6 (Qt 6, LGPLv3)** | Padrão em software de engenharia, nativo no Windows e no Linux. A LGPL é compatível com a licença MIT do projeto | **PyQt6**, que é GPL e obrigaria a distribuir a GUI como GPL. O extra `gui` do `pyproject.toml` pede o PyQt6 hoje: trocar (Fase 0) |
| Interface | **Qt Widgets** com um tema próprio em QSS | Docks, tabelas, árvores e o PyQtGraph são Widgets; testes simples com o pytest-qt | Qt Quick (QML) como base: uma segunda linguagem e difícil de integrar ao PyQtGraph. Fica a opção de usá-lo em telas pontuais |
| Gráficos interativos | **PyQtGraph (MIT)** | Desenha milhões de pontos com fluidez, com cursores, zoom e imagens (espectrograma) | Matplotlib interativo (lento), Plotly (navegador) |
| Figuras de publicação | **Matplotlib**, com o estilo do `report/gerar_figuras.py` | Já é dependência, e as figuras do relatório já seguem esse estilo | — |
| Ícones | **Lucide (ISC)**, em SVG recolorido pelo tema | Traço uniforme e moderno, licença livre | Ícones do sistema (diferentes entre Windows e Linux) |
| Fontes | **Inter** (interface) e **JetBrains Mono** (números), ambas OFL, embutidas | Iguais nos dois sistemas e com algarismos tabulares | Fontes do sistema |
| Tarefas | **QThreadPool**, com cancelamento e progresso | O NumPy e o SciPy liberam o GIL nas contas pesadas; threads bastam | Multiprocessamento: só se um perfil de desempenho mostrar que é preciso |
| Configuração e arquivos | **QSettings** e **platformdirs** (MIT) | As pastas certas em cada sistema (configuração, cache, logs) | Arquivos soltos na pasta do programa |
| Testes | **pytest-qt**, com `QT_QPA_PLATFORM=offscreen` na CI | Roda sem tela no GitHub Actions | — |
| Distribuição | **PyInstaller** (pasta única) + **Inno Setup** no Windows; **AppImage** no Linux | Maduros com o PySide6 e gerados na CI a cada tag | Nuitka (inicia mais rápido, mas o build é lento e frágil: reavaliar na Fase 5) |
| Idiomas | **Qt Linguist** (`self.tr`), português primeiro e inglês depois | O relatório já é bilíngue; pesquisadores de fora | Textos fixos no código |

**Licenças, para a distribuição:**

- PySide6 é LGPL: o instalador mantém as bibliotecas do Qt como arquivos separados e inclui o aviso da LGPL;
- PyQtGraph é MIT, o Lucide é ISC, Inter e JetBrains Mono são OFL;
- **não usar** bibliotecas de widgets GPL, como a PySide6-Fluent-Widgets.

---

## 4. Arquitetura

```text
┌──────────────────────────────────────────────────────────────────────────┐
│  sh_analyzer_gui  (Qt)                                                   │
│   app/          QApplication, tema, janela principal, atalhos           │
│   telas/        navegador, forma de onda, espectro, bandas, perfis...   │
│   componentes/  gráfico com pirâmide, cartão de métrica, inspector,     │
│                 campo com unidade, toast, paleta de comandos            │
│   nucleo/       Projeto, Captura aberta, Análise (parâmetros → resultado)│
│                 gerenciador de tarefas, cache, avisos                   │
│   tema/         tokens, QSS gerado, ícones, fontes                      │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ chama (nunca o contrário)
┌───────────────────────────────▼──────────────────────────────────────────┐
│  supraharmonicos.api   (novo, sem Qt e sem argparse)                     │
│   abrir_captura · sinal_do_canal · espectro · welch · bandas_iec ·       │
│   harmonicos · espectrograma · metricas · perfis · exportar              │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ funções puras que já existem
┌───────────────────────────────▼──────────────────────────────────────────┐
│  supraharmonicos  (motor atual: cabecalho, espectro, bandas_iec,         │
│  harmonicos, fundamental, sonda, metricas_captura, aliasing, ...)        │
│  CLI: adc_tool.py, medir_captura.py, medir_fase.py, ... (modos.py)       │
└──────────────────────────────────────────────────────────────────────────┘
```

**Regras de dependência**, conferidas por teste:

- o motor nunca importa o Qt;
- a GUI nunca monta um `argparse.Namespace`.

### 4.1 A camada `supraharmonicos.api`

A maior parte do motor já é feita de funções puras: `calcular_espectro`, `calcular_espectro_welch`, `calcular_bandas_iec`, `calcular_harmonicos`, `calcular_espectrograma`, `aplicar_correcao_sonda`, `analisar_espectro` e outras. O que prende o motor à linha de comando é:

- **`contexto.resolver_contexto(args)`**: o cabeçalho, os canais, as faixas, os ganhos, as grandezas e as sondas, resolvidos a partir das flags;
- **os `executar_*` do `modos.py`**, que recebem o `argparse.Namespace`.

A camada nova tira essa dependência sem duplicar lógica:

- **`abrir_captura(caminho, *, canais=None, faixas=None, ganhos=None, perfis=None) -> Captura`.** Faz o que o `resolver_contexto` faz hoje, com parâmetros explícitos. Devolve o cabeçalho, o memmap das amostras, os canais e a calibração resolvida, e os avisos estruturados (nível, código e mensagem). O `resolver_contexto(args)` passa a chamá-la, e a CLI não muda.
- **`sinal_do_canal(captura, canal, inicio, fim, *, corrigir_sonda=True) -> np.ndarray`.** Faz a conversão para unidades físicas e, se pedido, a correção pela sonda.
- **`espectro`, `welch`, `bandas_iec`, `harmonicos`, `espectrograma` e `metricas`.** Cada uma recebe parâmetros num dataclass imutável e devolve um resultado num dataclass. São finas sobre as funções que já existem.
- **Avisos.** Hoje o motor avisa pelo `logging`. A Fase 0 captura esses avisos por tarefa, com um handler, sem refatorar; depois, os mais importantes viram avisos estruturados (`Aviso(nivel, codigo, texto, canal)`).
- **Testes de paridade.** A CLI e a API dão os mesmos números nas capturas sintéticas (`tests/capturas_sinteticas.py`).

Essa camada vale por si só: deixa a CLI mais simples e é a base de qualquer interface futura, inclusive web.

### 4.2 O fluxo de dados

1. **Captura aberta.** O memmap é somente leitura, e nada é copiado.
2. **Pirâmide mín/máx de cada canal**, para a forma de onda (seção 7.2):
   - calculada em segundo plano, primeiro o nível mais grosso;
   - guardada no cache em disco, com a chave no id da captura e no CRC das amostras do cabeçalho v9 (ou no tamanho e na data do arquivo nas versões anteriores);
   - reabrir a captura é instantâneo.
3. **Análises:** `Análise = (captura, parâmetros) → resultado`.
   - Os parâmetros são imutáveis.
   - O resultado vai para o cache em memória (LRU) e, quando é caro, para o disco.
   - Mudar um parâmetro dispara uma tarefa nova depois de 300 ms sem mudanças (debounce), e a tarefa anterior é cancelada: vale a mais recente.
4. **Gerenciador de tarefas:**
   - fila no QThreadPool, com token de cancelamento, progresso e tempo estimado;
   - os erros do motor (`ErroSHAN`) viram uma mensagem na tela, não um travamento.

### 4.3 Projeto e estado

Um **projeto** (`.shproj`, JSON) guarda:

- as capturas, por caminho relativo;
- as análises abertas e os parâmetros delas;
- o mapeamento de canais para sondas;
- o layout da janela.

O projeto não guarda resultados, que saem do cache ou são recalculados. Mudanças de parâmetro entram num `QUndoStack`, com desfazer e refazer.

---

## 5. Telas

### 5.1 A janela principal

```text
┌───────────────────────────────────────────────────────────────────────────────┐
│ [logo] SH-Analyzer   Projeto: bancada 03/11 ▾     [Ctrl+K  Buscar comando…]  ◐ ⚙ │
├──────┬────────────────────────────────────────────────────────┬───────────────┤
│Captu-│ [Forma de onda] [Espectro] [Bandas IEC] [+]             │ PARÂMETROS    │
│ ras  │                                                        │ Método  FFT ▾ │
│Análi-│                                                        │ Janela  Hann ▾│
│ se   │            área de gráficos (abas e docks)             │ Resolução 1 Hz│
│Perfis│                                                        │ Canais ■0 ■1  │
│Cali- │                                                        ├───────────────┤
│bração│                                                        │ MEDIDAS       │
│Compa-│                                                        │ f₁ 59,998 Hz  │
│ rar  │                                                        │ 25 kHz −40,0  │
│Expor-│                                                        │   dBc         │
│ tar  │                                                        │ ⚠ 1 aviso     │
├──────┴────────────────────────────────────────────────────────┴───────────────┤
│ S1_25k.bin · 400 kS/s · 1 canal · 30 s · ✓ integridade · v0.8 │ FFT ▓▓▓▓░ 72 % │
└───────────────────────────────────────────────────────────────────────────────┘
```

- **A barra lateral** troca de área. Cada área tem uma área central com abas e docks, e o painel direito, de parâmetros e medidas, muda com a aba ativa.
- **A barra de status** mostra a captura ativa, um resumo de integridade (clicável) e as tarefas em andamento.
- **A paleta de comandos** (Ctrl+K) dá acesso a qualquer ação pelo nome, como "Abrir pasta", "Espectro de Welch" ou "Exportar figura".
- **O layout das docks** é salvo por projeto (`saveState`/`restoreState`).

### 5.2 As telas e quando cada uma entra

| Tela | O que tem | Motor | Versão |
|---|---|---|---|
| **Início e navegador de capturas** | Veja abaixo | `cabecalho`, `contexto` | **v0.9** |
| **Inspector do cabeçalho** | Veja abaixo | `cabecalho.ler_cabecalho`, `conferir_crc_das_amostras` | **v0.9** |
| **Forma de onda** | Veja abaixo | `api.sinal_do_canal` + a pirâmide | **v0.9** |
| **Espectro** | Veja abaixo | `espectro`, `fundamental`, `sonda` | **v0.9** |
| **Harmônicos** | Tabela (componente, grupo e subgrupo da IEC 61000-4-7, % da fundamental, fase), barras, THD/THDG/THDS | `harmonicos` | **v0.9** |
| **Bandas IEC e espectrograma** | Veja abaixo | `bandas_iec`, `espectro.calcular_espectrograma` | **v0.9** |
| **Perfis de sonda** | A lista de `scripts/sondas/*.json`; o Bode (magnitude e fase, com barras de erro e a faixa válida); qual perfil cada canal usa, e por quê; as conferências de faixa, ganho e idade do perfil | `sonda`, `perfil_complexo` | **v0.9** (ver e aplicar), **v1.0** (comparar) |
| **Métricas de bancada** | Os cartões do `medir_captura`: ruído, SNR, SINAD, THD, ENOB, SFDR, jitter, degraus nas trocas de buffer; a tabela de várias capturas | `metricas_captura`, `cli_medir_captura` | **v1.0** |
| **Comparar** | Espectros e bandas de várias capturas sobrepostos ou lado a lado, com cores fixas por captura e a diferença em dB | as mesmas análises | **v1.0** |
| **Calibração** | Veja abaixo | `fase_quadrada`, `razao_quadrada`, `analise_razao`, `aliasing` | **v1.0** |
| **Exportar** | Veja abaixo | `exportacao`, `hdf5`, `report/gerar_figuras.py` | **v0.9** (figura e CSV), **v1.0** (completo) |
| **Configurações** | Tema (sistema, claro, escuro), idioma, pasta de dados (`$DADOS`), pasta de sondas, unidades, reduzir movimento, limpar o cache | — | **v0.9** |

**Início e navegador de capturas:**

- abrir um arquivo ou uma pasta (a do dia, `$DADOS/lab/AAAA-MM-DD/`, ou uma `CAL_`/`SH_`), arrastando e soltando;
- recentes e busca;
- uma lista com título, data, taxa, canais, duração, firmware e um selo de integridade (✓ ou ⚠);
- numa pasta de coleta, o `resumo.csv` lido: o código de saída e as colunas `vpp_pino_v`, `freq_medida_hz` e `sinal` de cada captura.

**Inspector do cabeçalho:**

- todos os campos, em grupos: captura, ADC e canais, integridade, sistema (v8) e extensão (v9);
- o CRC das amostras conferido;
- copiar como texto ou JSON.

**Forma de onda:**

- canais empilhados ou sobrepostos, com o eixo do tempo sincronizado;
- unidades físicas (V ou A, pelo ganho e pelo perfil);
- dois cursores com Δt, Δy e 1/Δt;
- RMS, pico a pico e média do trecho selecionado;
- a régua de "onde estou" na captura inteira (minimapa).

**Espectro:**

- FFT ou Welch; janela, resolução e escala (dBV, dBc, V RMS); frequência linear ou logarítmica;
- a faixa de 2 a 150 kHz sombreada;
- a tabela de picos, com marcadores;
- os harmônicos de f₁ marcados;
- sem e com a correção do perfil, sobrepostos;
- o piso de ruído;
- um aviso de "possível imagem" acima da faixa válida.

**Bandas IEC e espectrograma:**

- as bandas de 200 Hz no tempo, com RMS, máximo e P95;
- um mapa de calor banda × tempo;
- o espectrograma, com uma LUT perceptual;
- a nota sobre o método acima de 9 kHz, a extensão usual na literatura (veja o `--bandas-iec` no `user-guide.md`).

**Calibração** (assistentes passo a passo):

- a cadeia por ondas quadradas, com o Bode, o ajuste, o χ² e os resíduos;
- a razão de dois canais (sonda de corrente);
- o aliasing, com 2 ou 3 taxas;
- a gravação do perfil.

**Exportar:**

- figuras PNG, SVG e PDF no estilo de publicação, em português ou inglês;
- dados em CSV, MAT e HDF5;
- um relatório curto (HTML ou Markdown) com os números, a proveniência e o comando da CLI equivalente.

### 5.3 O que fica para depois da v1.0

- **Controle da BeagleBone pela GUI** (capturar, acompanhar a coleta, trazer arquivos): é poderoso, mas envolve rede, senhas e um processo longo na placa. Fica para uma v1.1, sobre o `BeagleBone_Setup.sh`.
- **Abrir pacotes `.zpaq.tar` direto** (`compactacao`).
- **Medidas ao vivo** durante a captura.

---

## 6. Sistema de design

### 6.1 Os tokens

Os valores saem da marca (`report/gerar_marca.py`, o ícone `docs/images/app-icon.svg`) e são definidos uma vez, em `tema/tokens.py`. O QSS dos dois temas é gerado a partir deles.

| Token | Escuro | Claro | Uso |
|---|---|---|---|
| `fundo` | `#0f1a2e` | `#f7f9fc` | Janela (o escuro é o do ícone) |
| `superficie` | `#16243b` | `#ffffff` | Painéis e cartões |
| `superficie_elevada` | `#1d2e4a` | `#ffffff` + borda | Menus, diálogos, toasts |
| `borda` | `#2a3d5a` | `#d8dee8` | Divisórias, campos |
| `texto` | `#f0f6fc` | `#0f172a` | Texto principal |
| `texto_secundario` | `#8b949e` | `#57606a` | Rótulos, unidades |
| `acento` | `#7dd3fc` (céu) | `#0369a1` | Seleção, foco, botão primário. No claro, um tom mais escuro que o `#0284c7` da marca, que dá só 4,1:1 contra o branco |
| `destaque` | `#fbbf24` (âmbar) | `#b45309` | Marcadores, medidas destacadas |
| `sucesso` / `aviso` / `erro` | verde / âmbar / vermelho, cada um com ícone | idem | Estado (nunca só a cor) |

- **Contraste:** o texto pede ≥ 4,5:1 contra a superfície e os elementos de gráfico ≥ 3:1, conferidos por teste nos dois temas.
- **Cores dos canais:** uma paleta categórica segura para daltônicos (a de Paul Tol, a mesma das figuras do relatório). **A cor segue o número do canal, não a ordem na tela**: o canal 1 é sempre da mesma cor.

### 6.2 Tipografia, espaço e forma

- **Inter** na interface, com algarismos tabulares nas medidas; **JetBrains Mono** em valores do cabeçalho e números alinhados.
- **Escala de tamanhos:** 12 (legendas), 13 (corpo), 15 (títulos de painel), 18 (seção) e 24 (título de tela).
- **Espaçamento** numa grade de 4 px (4, 8, 12, 16, 24, 32).
- **Formas:** raio de 6 px em campos e botões e de 10 px em cartões. Profundidade por borda e superfície, não por sombra pesada.
- **Números no padrão brasileiro em português,** com a vírgula decimal, e no padrão inglês em inglês. Prefixos SI (kHz, µs, mV), e a unidade sempre ao lado do valor.

### 6.3 Movimento

| Onde | Como | Duração |
|---|---|---|
| Troca de tela ou aba | Fade com deslocamento de 8 px | 180 ms |
| Painel que abre ou fecha | Deslize | 200 ms |
| Toasts (exportado, aviso) | Entra de baixo, some sozinho | 200 ms + 4 s |
| Hover e press | Cor de fundo | 120 ms |
| Tarefa em andamento | Barra de progresso; esqueleto pulsando onde o resultado vai aparecer | contínuo |
| Zoom por botão ("ajustar", "ir para o pico") | Transição do intervalo do eixo | 250 ms |

- **Curva:** OutCubic na entrada e InCubic na saída (`QPropertyAnimation`/`QVariantAnimation`).
- **Nunca** animar dados enquanto o usuário os lê, nem o zoom feito com o mouse.
- **"Reduzir movimento"** nas configurações (e no sistema, quando ele informar) troca tudo por mudanças instantâneas.

### 6.4 Os componentes

São construídos uma vez e mostrados na **galeria de componentes**, uma janela de desenvolvimento com todos eles nos dois temas, que também serve de teste visual:

- botões primário, secundário, fantasma e de ícone;
- campo numérico com unidade e prefixo SI (aceita "2,5k" e "2500");
- seletor segmentado;
- chip de estado;
- cartão de métrica (valor, unidade, variação, ajuda);
- tabela com cabeçalho fixo, ordenação, cópia e exportação;
- toast;
- diálogo;
- paleta de comandos;
- estado vazio (ilustração e uma ação);
- esqueleto de carregamento;
- inspector chave/valor;
- legenda de canais clicável.

### 6.5 Os gráficos

Um único componente `Grafico`, sobre o PyQtGraph, aplica o tema a todos:

- grade recessiva e eixos discretos;
- cursor em cruz com tooltip (valor e unidade);
- legenda clicável que mostra ou esconde a série;
- menu de contexto com copiar imagem, exportar dados e redefinir o zoom;
- rótulos de eixo com unidade;
- marcadores de pico com rótulo seletivo, nunca em todos os pontos.

---

## 7. Desempenho

### 7.1 O orçamento

Medido num notebook de laboratório comum (4 núcleos, 8 GB, SSD), no Windows e no Linux:

| Situação | Meta |
|---|---|
| Abrir o aplicativo até a janela | < 1,5 s |
| Abrir uma captura de 30 s a 400 kS/s (12 M amostras, 24 MB) | Forma de onda visível em < 300 ms; completa em < 1 s |
| Abrir uma captura de 1 h a 400 kS/s (2,9 GB) | Visível em < 2 s, com a pirâmide em segundo plano; reabrir em < 0,5 s, pelo cache |
| Pan e zoom na forma de onda, 8 canais | ≥ 60 quadros por segundo |
| FFT de 12 M amostras | < 1,5 s, em segundo plano |
| Welch e bandas IEC de uma captura de 1 h | Em blocos, memória constante, com progresso |
| Thread da interface | Nenhum bloqueio > 16 ms |
| Memória | Pico < 2× o tamanho do trecho analisado; nunca a captura inteira em float64 |

### 7.2 As técnicas

- **Memmap sempre.** As amostras são lidas do disco sob demanda, como a CLI já faz (`carregar_amostras_bin`, `desintercalar` sem cópia).
- **Pirâmide mín/máx da forma de onda:**
  - níveis com fator 16 (16, 256, 4096... amostras por par mín/máx), calculados em blocos com `np.minimum.reduceat`/`np.maximum.reduceat`;
  - o gráfico pede ao cache o nível que dá ~2 pares por pixel no zoom atual e só lê as amostras de verdade quando cabem na tela;
  - o resultado é o mesmo da envoltória do `adc_tool` (`pontos_para_plot`), mas sem recalcular a cada zoom.
- **Espectros longos na tela:** o máximo por coluna de pixel, para nenhum pico sumir. O cursor lê o espectro completo.
- **Espectrograma:** um `ImageItem` com dados em `uint8` e a LUT do tema, recalculado no trecho visível.
- **Itens de gráfico reaproveitados** (`setData`) e atualizações agrupadas num quadro.
- **Imports sob demanda.** O SciPy, o h5py e o Matplotlib só carregam quando uma tela os usa, como na CLI. O PySide6 e o PyQtGraph carregam na partida.
- **`scipy.fft` com `workers`,** nos núcleos disponíveis.
- **Cache de resultados:** LRU em memória e, para pirâmides e espectrogramas, em disco (`platformdirs.user_cache_dir`), com limite de tamanho e botão de limpar.
- **Medir antes de otimizar:** testes de desempenho com capturas sintéticas grandes, o `py-spy` para perfis e um vigia da thread da interface no modo de desenvolvimento, que registra todo bloqueio acima de 16 ms.

---

## 8. Qualidade, testes e CI

- **Paridade com a CLI.** Os mesmos números pela API e pela CLI, em todas as análises da v0.9.
- **Testes da GUI (pytest-qt):** abrir uma captura sintética, mudar parâmetros e conferir o resultado no modelo da tabela ou do gráfico; o cancelamento de tarefas; o projeto salvo e reaberto.
- **Galeria de componentes** em captura de tela nos dois temas, comparada com tolerância (opcional, Fase 5).
- **Desempenho** como teste. As metas da seção 7 viram testes marcados (`-m desempenho`), rodados fora do conjunto padrão; uma piora de mais de 20 % falha.
- **Robustez:**
  - todo erro não tratado abre um diálogo com os detalhes copiáveis e o caminho do log;
  - capturas corrompidas, truncadas, de versões antigas (v1 a v9) e `.csv` são abertas ou recusadas com uma mensagem clara.
- **Tipos:** dicas de tipo em todo o pacote da GUI, conferidas pelo `pyright` no modo básico.
- **CI:**
  - um job `interface` no GitHub Actions instala o extra `gui-dev` e roda o pytest-qt com `QT_QPA_PLATFORM=offscreen`;
  - os jobs atuais continuam sem o Qt (o motor não depende dele);
  - em cada tag, um job em Windows e Linux gera os instaladores e os anexa ao release.
- **Teste com usuários** (Fase 5): três pesquisadores, as três jornadas da seção 2, medindo o tempo e os erros. O que travar vira tarefa antes da v1.0.

---

## 9. Distribuição e versões

- **Windows:** PyInstaller numa pasta só e um instalador do Inno Setup, com atalho no menu Iniciar e a associação dos arquivos `.shproj`. A assinatura de código é opcional; sem ela, o Windows mostra o aviso do SmartScreen na primeira execução.
- **Linux:** AppImage, testado em X11 e Wayland; um `.deb` é opcional.
- **Para quem desenvolve:** `uv run --extra gui sh-analyzer-gui`, pelo `[project.gui-scripts]` do `pyproject.toml`.
- **Tamanho esperado:** 150 a 250 MB (Qt, NumPy e SciPy), sem os módulos do Qt que não são usados (WebEngine, Multimedia, 3D).
- **Atualizações:** na v1.0, só um aviso de versão nova (consulta opcional aos releases do GitHub); sem atualização automática.
- **Versões:** um repositório e uma versão para o motor, a CLI e a GUI. A v0.9 é a primeira GUI usável; a v1.0, a completa e testada com usuários.

---

## 10. Roteiro por fases

As durações são em semanas de meio período. O relatório científico final tem prioridade, e o roteiro se ajusta a ele.

### Fase 0: fundação e protótipos de risco (2 semanas)

**Dependências e esqueleto:**

- [x] Trocar o extra `gui` de `PyQt6` para `PySide6` + `pyqtgraph`, também no cabeçalho de dependências do `scripts/adc_tool.py` e no `tests/test_dependencias.py`; o backend interativo do Matplotlib (QtAgg) roda com o PySide6. Os testes da interface ficam no extra `gui-dev`.
- [x] Criar o pacote `scripts/sh_analyzer_gui/` (incluído no `pyproject.toml`), o ponto de entrada `sh-analyzer-gui` e uma janela vazia com o ícone da marca.
- [x] Criar o teste de dependências: o motor não importa o Qt (`tests/test_arquitetura.py`).
- [ ] Quando a `api` existir: a GUI só chama o motor por ela, sem montar um `argparse.Namespace`.

**A camada da API:**

- [ ] Criar `supraharmonicos.api.abrir_captura` e fazer o `resolver_contexto` chamá-la.
- [ ] Criar `sinal_do_canal` e o primeiro par de análises (espectro e Welch), com testes de paridade.

**Protótipos de risco:**

- [ ] A pirâmide numa captura sintética de 1 h e 8 canais no PyQtGraph: confirmar os 60 quadros por segundo e a memória.
- [ ] Um instalador do PyInstaller com o PySide6 e o SciPy, no Windows e no Linux: medir o tamanho e a partida.

**Tema:**

- [ ] Os tokens, o QSS gerado nos dois temas, as fontes embutidas e os ícones.
- [ ] A galeria de componentes com os 6 primeiros: botão, campo com unidade, seletor, chip, cartão e toast.

**CI:**

- [x] O job `interface` com pytest-qt em modo offscreen (`scripts/ci.sh interface`).

**Pronto quando:** o aplicativo abre no Windows e no Linux nos dois temas, abre um `.bin` e mostra o cabeçalho; os dois protótipos de risco cumprem o orçamento.

### Fase 1: visualização, rumo à v0.9 alfa (3 semanas)

- [ ] **A janela principal:** barra lateral, abas e docks, painel de parâmetros e medidas, barra de status, layout salvo.
- [ ] **O gerenciador de tarefas** (cancelamento, progresso, debounce, a mais recente vale) e o cache.
- [ ] **O navegador de capturas:** abrir uma pasta, a lista com o selo de integridade, o `resumo.csv` das coletas, recentes, arrastar e soltar.
- [ ] **O inspector do cabeçalho**, com o CRC conferido.
- [ ] **A forma de onda:** a pirâmide, os canais, as unidades físicas, os cursores e as medidas do trecho.
- [ ] **O espectro:** FFT e Welch, janelas, escalas, picos, a faixa de 2 a 150 kHz e a correção do perfil sobreposta.
- [ ] **Os avisos do motor** num painel e no chip da barra de status.

**Pronto quando:** a jornada do pesquisador vai até o espectro, a captura de 30 s cumpre o orçamento e os números batem com a CLI.

### Fase 2: análises, rumo à v0.9 (3 semanas)

- [ ] **Harmônicos:** a tabela e as barras, com THD, THDG e THDS.
- [ ] **Bandas IEC e espectrograma**, em blocos para capturas longas.
- [ ] **Perfis de sonda:** a lista, o Bode, o mapeamento por canal e as conferências.
- [ ] **A exportação básica:** a figura no estilo de publicação (PNG, SVG, PDF) e o CSV, com a proveniência e o comando da CLI.
- [ ] **As configurações:** tema, pastas, unidades e reduzir movimento.
- [ ] **A paleta de comandos e os atalhos.**

**Pronto quando:** a jornada do pesquisador fica completa, com a figura e a tabela exportadas. **Tag v0.9.**

### Fase 3: fluxos de pesquisa (2 a 3 semanas)

- [ ] **Projetos `.shproj`,** com desfazer e refazer de parâmetros.
- [ ] **Comparar capturas.**
- [ ] **Métricas de bancada** (`medir_captura`), em cartões e tabela.
- [ ] **A exportação completa:** MAT, HDF5 e o relatório curto em HTML ou Markdown.
- [ ] **A interface em inglês** (Qt Linguist).

### Fase 4: calibração (3 semanas)

- [ ] **O assistente da cadeia por ondas quadradas:** escolher a pasta `CAL_`, rodar, ver o Bode, o ajuste e os resíduos, e gravar o perfil.
- [ ] **O assistente da razão de dois canais,** para a sonda de corrente: shunt, espiras, diafonia e âncora.
- [ ] **O aliasing** com 2 ou 3 taxas.

### Fase 5: acabamento e v1.0 (2 semanas)

- [ ] **Animações e microinterações** revistas tela a tela; estados vazios e uma primeira execução guiada.
- [ ] **Teste com três pesquisadores** e as correções que ele pedir.
- [ ] **Os instaladores gerados na CI** a cada tag; o guia de uso da GUI em `docs/`.
- [ ] **Comparação visual da galeria** nos dois temas e testes de desempenho na CI.

**Pronto quando:** as três jornadas da seção 2 rodam sem ajuda e o orçamento de desempenho é cumprido no Windows e no Linux. **Tag v1.0.**

**Total estimado:** 15 a 17 semanas de meio período.

---

## 11. O branch e o fluxo de trabalho

- **O branch `feat/interface`,** criado a partir do `main`, guarda todo o trabalho da GUI. Uma tarefa grande pode ter um branch próprio a partir dele (`interface/<tema>`, por exemplo `interface/piramide`), mesclado de volta quando estiver pronta.
- **Não use o nome `feat/gui`.** No Windows e no macOS, os nomes de branch não diferenciam maiúsculas de minúsculas, e ele colidiria com o `feat/GUI`.
- **O `feat/GUI` não entra no `feat/interface` nem no `main`.** Ele guarda um protótipo anterior e será apagado quando não for mais necessário.
- **Mudanças no motor** (`scripts/supraharmonicos/`, incluindo a `api`) vão **primeiro para o `main`**, porque mudam a CLI também. Depois o `main` entra no `feat/interface`. Assim o motor não diverge entre os dois branches.
- **Atualizar o `feat/interface` com o `main`** pelo menos uma vez por semana (merge).
- **A CI roda a cada push no `feat/interface`,** além do `main` e dos PRs.
- **Na v0.9, um PR do `feat/interface` para o `main`.** A exclusão automática de branches está ligada no GitHub: o `feat/interface` é apagado no merge. O trabalho segue num branch novo a partir do `main`, ou volta pelo botão "Restore branch" do PR.
- **Convenções do projeto:**
  - nomes e comentários em português, como no motor;
  - mensagens de commit em português;
  - documentos com nome em inglês e conteúdo em português.

---

## 12. Riscos

| Risco | Efeito | Mitigação |
|---|---|---|
| A pirâmide ou o PyQtGraph não sustentam 60 quadros por segundo com 8 canais longos | A tela principal fica lenta | Protótipo na Fase 0. Plano B: desenho em OpenGL (`useOpenGL`) ou o VisPy só na forma de onda |
| O instalador com o SciPy fica grande ou lento para abrir | Má primeira impressão | Protótipo na Fase 0. Excluir módulos do Qt; avaliar o Nuitka na Fase 5 |
| Refatorar o `resolver_contexto` muda o comportamento da CLI | Números diferentes na CLI | Testes de paridade antes e depois; a CLI continua com os seus testes |
| Wayland ou HiDPI no Linux e escalas de 125 % ou 150 % no Windows | Interface borrada ou desalinhada | Testar nas duas plataformas a cada fase; ícones em SVG |
| O escopo cresce (calibração, BeagleBone, ao vivo) | A v1.0 atrasa | As fases fecham o escopo; a BeagleBone e o ao vivo ficam para a v1.1 |
| O relatório final disputa o tempo | O roteiro escorrega | O relatório tem prioridade; a v0.9 já é útil sozinha |
| Licenças (GPL por engano) | Obriga a mudar a licença ou a reescrever | Só bibliotecas MIT, BSD, ISC, LGPL e OFL; o teste de dependências confere a lista |

---

## 13. Decisões em aberto

- **A fonte da interface:** Inter (sugerida) ou Fira Sans, a das figuras do README. Decidir na Fase 0, vendo a galeria.
- **A calibração na v1.0 ou numa v1.1:** ela é a parte mais complexa e a que menos pessoas usam.
- **O inglês na v1.0:** depende de a GUI ser mostrada fora do grupo.
- **A assinatura de código no Windows:** tem custo, e o aviso do SmartScreen só aparece na primeira execução.
- **O suporte ao macOS:** o PySide6 funciona, mas sem teste; fica fora até alguém precisar.
