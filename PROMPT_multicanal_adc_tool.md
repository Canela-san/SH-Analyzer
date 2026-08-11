# Prompt para tarefa futura: suporte multi-canal em `adc_tool.py`

> Cole este arquivo inteiro como instrução na próxima sessão em que for
> implementar isso. Ele foi escrito para ser autocontido: explica o que já
> mudou no firmware, por que mudou, e exatamente o que `adc_tool.py`
> precisa passar a fazer para acompanhar. **Não é para ser executado
> agora** -- é a especificação da próxima tarefa.

## 1. Contexto: o que já mudou no firmware

`firmware/ler_adc.c`, `firmware/spi_core.asm`, `firmware/pru_main.c` e
`firmware/memoria_pru.h` já foram atualizados para suportar captura de
**vários canais do ADS8688 intercalados numa mesma captura**. Resumo do
que mudou (leia os comentários nesses arquivos para os detalhes completos
-- em especial o cabeçalho de `spi_core.asm` e o bloco de comentário
dentro do laço de gravação em `ler_adc.c`):

- `ler_adc` agora aceita um segundo argumento posicional opcional: uma
  lista de canais separada por vírgula, sem espaços (ex.:
  `sudo ./ler_adc 102400 0,1,3`). **Sem esse argumento, continua
  capturando só o canal 1**, exatamente como antes -- isso não muda o
  comportamento de nenhum script/arquivo já existente.
- Com N canais selecionados, as amostras no `.bin` de saída ficam
  **intercaladas em round-robin, na ordem exata em que os canais foram
  passados na lista**: a amostra bruta na posição `i` do arquivo (0-based,
  contando o arquivo inteiro, concatenando todos os buffers) pertence ao
  canal `lista_de_canais[i % N]`. Essa correspondência é válida a partir
  da posição 0 -- **o firmware já descarta internamente a amostra de
  "alinhamento"** necessária por causa de um atraso de pipeline de 1
  quadro do ADS8688 em modo manual (ver comentário grande em `ler_adc.c` e
  no cabeçalho de `spi_core.asm` se quiser entender o motivo). Ou seja:
  **`adc_tool.py` não precisa se preocupar com esse detalhe, só precisa
  saber a lista de canais e a ordem usada na captura**, e aplicar
  `amostra[i] -> canal[i % N]` diretamente.
- **O formato do `.bin` em si NÃO mudou**: continua sendo uma sequência
  crua de inteiros de 16 bits (uint16/int16 conforme `--formato`), sem
  cabeçalho nenhum. A informação de "quais canais, em que ordem" **não
  fica gravada no arquivo** (mesma filosofia que já vale para a
  frequência de amostragem hoje, que também é só um parâmetro passado por
  fora na hora de analisar). Isso significa que o usuário precisa
  fornecer essa lista de novo ao `adc_tool.py`, na mesma ordem usada em
  `ler_adc` -- `ler_adc.c` já imprime essa lista no console na hora da
  captura, especificamente para o usuário anotar.
- O `-f`/`--frequencia` continua sendo a frequência TOTAL de transação
  (mesmo significado de sempre). Com N canais, a frequência **efetiva por
  canal** é `frequencia_total / N` -- é essa divisão que `adc_tool.py`
  precisa aplicar para montar o eixo do tempo e a base da FFT de cada
  canal individualmente.
- `SAMPLES_PER_BUFFER` (1.048.576) não é necessariamente múltiplo do
  número de canais escolhido -- o índice de canal na PRU nunca reinicia
  na troca de buffer, então a intercalação continua perfeitamente em fase
  atravessando buffers, mas ao desintercalar um arquivo completo (ou um
  recorte via `--inicio`/`--fim`) pode sobrar um "resto" de amostras no
  fim que não fecha um ciclo completo de N -- ver seção 4.7 abaixo.

## 2. Objetivo desta tarefa

Atualizar `adc_tool.py` para **ler, converter e plotar capturas
multi-canal**, mantendo o script funcionando exatamente como hoje quando
nenhuma flag nova for usada (retrocompatibilidade total com arquivos e
scripts/atalhos já existentes, de captura de 1 canal só).

Precisa dar suporte a:
1. Informar ao script quais canais estão no arquivo e em que ordem
   (metadado externo, já que o `.bin` não carrega isso).
2. Escolher, dentre os canais capturados, quais efetivamente
   plotar/analisar (pode ser um subconjunto).
3. Plotar os canais selecionados **juntos** (sobrepostos no mesmo eixo)
   OU **separados** (um subplot por canal) -- as duas opções precisam
   existir.
4. FFT por canal (cada canal tem sua própria fundamental, seu próprio
   recorte em ciclos inteiros, seu próprio espectro -- ver seção 4.4).
5. Modo de conversão (`.bin`<->`.csv`) sabendo lidar com o novo formato
   intercalado.

## 3. Especificação de CLI (proposta de nomes de flag -- pode ajustar se
   achar um nome melhor, mas mantenha o padrão do resto do script: minúsculo,
   com hífen, sem acento, em português, com `--help` bem escrito e um novo
   bloco no docstring do módulo, no mesmo estilo detalhado das seções já
   existentes)

- `--canais LISTA` (ex.: `--canais 0,1,3`): canais presentes no arquivo,
  **na mesma ordem usada na captura** (`ler_adc <freq> <canais>`).
  Default: `"1"` (um canal só, igual ao comportamento de hoje -- fluxo de
  1 canal continua funcionando sem passar essa flag). Vale tanto no modo
  de plotagem quanto no de conversão `.bin` -> `.csv` (não é necessária em
  `.csv` -> `.bin` se o CSV já tiver a coluna `canal`, ver seção 4.5).
- `--canais-exibir LISTA` (ex.: `--canais-exibir 0,3`): subconjunto de
  `--canais` que deve ser efetivamente plotado/analisado. Default: todos
  os canais de `--canais`. Deve validar que todo canal aqui também está
  em `--canais` (erro claro se não estiver).
- `--layout-canais {separados,sobrepostos}`: como organizar múltiplos
  canais exibidos. `separados` (sugestão de default -- mais seguro
  visualmente quando os canais medem grandezas diferentes, ex. tensão e
  corrente, com escalas bem diferentes): um subplot de forma de onda por
  canal (e, se `--fft`, mais um subplot de espectro por canal, ou um
  layout em grade -- pensar no layout com calma, mas manter a mesma ideia
  do gráfico atual de "sombrear o trecho usado na FFT no gráfico do
  tempo" para CADA canal). `sobrepostos`: todos os canais selecionados no
  MESMO eixo de tempo (cores diferentes + legenda), e, se `--fft`, todos
  os espectros sobrepostos no mesmo eixo de frequência (também com
  legenda). Só faz sentido pedir `--layout-canais` quando mais de 1 canal
  está em `--canais-exibir`; com 1 só, ignore/avise que a flag não teve
  efeito.

## 4. Pontos de design que precisam de decisão explícita na implementação

### 4.1 Desintercalação (core da mudança)
Escreva uma função central, algo como
`desintercalar(amostras_brutas, num_canais) -> dict[canal_id -> array]`,
usada tanto no modo de plotagem quanto no de conversão. Dica de
implementação eficiente com numpy (evita loop em Python amostra a
amostra, que seria lento para arquivos grandes): truncar o array para um
múltiplo de `num_canais` e usar
`amostras[:n_truncado].reshape(-1, num_canais)`, onde a coluna `k` (via
`[:, k]`) já dá as amostras do `num_canais`-ésimo canal na lista, na
ordem certa, sem loop explícito. Isso ainda é uma VIEW do array original
(inclusive se vier de um `.bin` aberto via memmap), então mantém o
espírito de "não carregar mais memória do que o necessário" que o script
já segue hoje -- só vira cópia de verdade quando alguma operação
posterior (filtro, FFT, plot) força isso, igual já acontece hoje com o
array de 1 canal só.

### 4.2 Frequência efetiva por canal
Ao montar o eixo do tempo e passar `fs` para `estimar_frequencia_fundamental`
/ `recortar_ciclos_inteiros` / `calcular_espectro_dbv` de cada canal, use
`fs_efetiva = args.frequencia / num_canais` (não `args.frequencia` puro --
esse é a taxa de transação total, não a taxa de amostragem de UM canal).

### 4.3 Plotagem: "separados" vs "sobrepostos"
Pense no layout de figura com cuidado -- o layout atual já é 2 linhas
(tempo + FFT) quando `--fft` está ativo. Com múltiplos canais em modo
`separados`, uma grade de `num_canais_exibidos` linhas (ou colunas) x
(1 ou 2 colunas, dependendo se `--fft` está ativo) é o caminho mais
natural com `plt.subplots`. Em modo `sobrepostos`, mantém a mesma grade
de 1 (ou 2) linhas de hoje, só adicionando uma série/curva por canal no
mesmo eixo, com legenda indicando o canal.

### 4.4 FFT por canal
Cada canal selecionado passa pelo pipeline JÁ EXISTENTE
(`estimar_frequencia_fundamental` -> `recortar_ciclos_inteiros` ->
`calcular_espectro_dbv`) de forma **independente** -- não assuma que
todos os canais têm exatamente a mesma fundamental/fase, mesmo sendo a
mesma rede elétrica (ruído, sensor, ganho e acoplamento diferentes por
canal podem afetar a detecção de cruzamento por zero de cada um
ligeiramente diferente). `--freq-min`/`--freq-max`/`--janela`/
`--kaiser-beta`/`--fft N` continuam sendo parâmetros GLOBAIS (mesmos para
todos os canais processados) -- não precisa (nem faz muito sentido)
torná-los por-canal.

### 4.5 Modo de conversão: nova coluna `canal` no CSV
Quando `--canais` tiver mais de 1 canal (ou sempre que o usuário passar
`--canais` explicitamente, mesmo com 1 só, para deixar auto-descritivo -- decida
o critério e documente), `bin_para_csv` deve escrever uma coluna `canal`
a mais (ex.: `amostra,canal,valor_bruto[,tensao_v]`), com o número do
canal de cada linha (`lista_canais[amostra_idx % num_canais]`).

Isso tem uma consequência boa: como o `.csv` passa a carregar o canal por
linha, ele fica **autodescritivo** -- `csv_para_bin` não precisa mais de
`--canais` para reconstruir o `.bin` corretamente, já que a ordem das
linhas no CSV já preserva a intercalação original (só precisa escrever
`valor_bruto` na ordem em que as linhas aparecem, exatamente como já
faz hoje). Ainda pode ser interessante validar que o padrão da coluna
`canal` é ciclicamente consistente (mesmo período de repetição do
início ao fim) e avisar (não necessariamente falhar) se não for --
pode indicar um CSV editado manualmente ou corrompido.

### 4.6 Calibração por canal (`--faixa`/`--ganho`/`--offset`)
**Decisão de design importante, pense com calma:** hoje `--faixa`,
`--ganho` e `--offset` são valores únicos, globais. Num uso real
multi-canal deste projeto (supraharmônicos de tensão E corrente), é
bem provável que canais diferentes tenham sensores/ganhos diferentes
(ex.: canal 0 = tensão com um ganho, canal 1 = corrente com outro ganho
completamente diferente). Recomendo permitir que essas três flags
aceitem **ou um valor único** (aplicado a todos os canais, mantém
retrocompatibilidade total com o uso atual de 1 canal) **ou uma lista
separada por vírgula do mesmo tamanho de `--canais`** (um valor por
canal, na mesma ordem). Documente isso claramente no `--help` de cada
flag e no docstring do módulo. Se implementar isso, a coluna
`tensao_v` do CSV (com `--incluir-tensao`) também precisa usar a
calibração correta por linha, conforme o canal daquela linha.

### 4.7 `--inicio`/`--fim` vs. limites de ciclo de canal
`--inicio`/`--fim` continuam contando posições BRUTAS no arquivo (sem
mudar o significado de hoje -- retrocompatível). Documente que, ao
desintercalar um recorte `--inicio:--fim`, o número de amostras
selecionado pode não ser múltiplo de `num_canais`; trunque para baixo
(`(fim - inicio) // num_canais * num_canais` amostras brutas
consideradas) antes de desintercalar, para que todos os canais
resultem em arrays do MESMO tamanho -- não deixe um canal com 1 amostra
a mais que os outros por causa de um resto de divisão, isso quebraria
qualquer alinhamento de tempo entre os canais nos gráficos
`sobrepostos`.

### 4.8 Retrocompatibilidade (obrigatório)
Rodar `adc_tool.py arquivo.bin -f 102400 [--fft]` **sem nenhuma flag
nova** precisa continuar produzindo exatamente o mesmo resultado que
produz hoje (1 canal, mesmo comportamento, mesmos nomes de variável/
saída no console). Trate o caminho de 1 canal (`--canais` no valor
default `"1"`) como um caso particular do caminho multi-canal
(`num_canais == 1`), não como dois caminhos de código totalmente
separados -- isso evita duplicar lógica e o risco de os dois caminhos
divergirem com o tempo.

## 5. Atualização do docstring do módulo

O módulo mantém um índice numerado no topo (`ÍNDICE` -- seções 1 a 9
hoje) e cada flag tem uma explicação longa em `--help`. Siga o MESMO
padrão para a funcionalidade multi-canal: uma nova seção no índice (ex.:
"10. CAPTURA E ANÁLISE MULTI-CANAL"), explicando a convenção de
intercalação, o papel de `--canais`/`--canais-exibir`/`--layout-canais`,
a divisão de frequência por canal, e a nova coluna `canal` no `.csv` --
e novos exemplos de uso na seção 9 (linha de comando) e no `epilog` do
`argparse`.

## 6. O que NÃO mudar

- Não mude o formato binário `.bin` em si (continua sem cabeçalho,
  little-endian, uint16/int16 conforme `--formato`) -- só a forma como
  `adc_tool.py` interpreta a intercalação das amostras dentro dele.
- Não quebre a leitura via `numpy.memmap` para `.bin` (seção 8 do
  docstring atual, sobre desempenho/memória) -- a desintercalação deve
  continuar sendo "preguiçosa" (view, não cópia) sempre que possível.
- Não mude o comportamento de nenhuma flag existente quando `--canais`
  não for passado (fica no default de 1 canal só).
