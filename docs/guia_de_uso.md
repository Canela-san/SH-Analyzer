# Guia de uso

Passo a passo para quem vai **operar** o SH-Analyzer: capturar na BeagleBone, analisar no computador e calibrar sondas de corrente. Para uma visão geral do projeto, comece pelo [`README.md`](../README.md).

**Índice**

1. [O fluxo em resumo](#o-fluxo-em-resumo)
2. [Preparar a BeagleBone](#preparar-a-beaglebone)
3. [Capturar com `ler_adc`](#capturar-com-ler_adc)
4. [Levar a captura para o computador](#levar-a-captura-para-o-computador)
5. [Analisar com `adc_tool.py`](#analisar-com-adc_toolpy)
6. [FFT ou Welch?](#fft-ou-welch)
7. [Sondas de corrente: calibração e correção](#sondas-de-corrente-calibração-e-correção)
8. [O arquivo `.bin`](#o-arquivo-bin)
9. [Utilitários](#utilitários)
10. [Problemas comuns](#problemas-comuns)

> Os comandos `uv run scripts/...` deste guia são executados **a partir da raiz do repositório**, no computador. Os comandos `./setup.sh`, `./ler_adc` e `./calibrar_sonda.sh` são executados **na BeagleBone**, dentro da pasta `firmware/`.

---

## O fluxo em resumo

| Etapa | Onde | Ferramenta | Resultado |
|---|---|---|---|
| 1. Preparar | BeagleBone | `firmware/setup.sh` | Pinos configurados, firmware da PRU carregado, `ler_adc` compilado |
| 2. Capturar | BeagleBone | `firmware/ler_adc` | Arquivo `.bin` autodescritivo |
| 3. Transferir | — | `scp` (ou similar) | `.bin` no seu computador |
| 4. Analisar | Computador | `scripts/adc_tool.py` | Gráficos, lista de picos, CSV ou HDF5 |
| (extra) Calibrar sonda | BeagleBone + computador | `firmware/calibrar_sonda.sh` → `scripts/gerar_perfil_sonda.py` | Perfil `.json` que corrige a resposta em frequência da sonda |

---

## Preparar a BeagleBone

**Antes de ligar:** conecte a placa de aquisição ao frontend analógico com o cabo mais curto possível. Jumpers longos acoplam ruído no barramento SPI e saturam as leituras do ADC.

**Pré-requisitos na BeagleBone:** `gcc` e o compilador `clpru` da Texas Instruments.

**Primeira vez, e depois de qualquer mudança no firmware:**

```bash
cd firmware
./setup.sh
```

O `setup.sh` faz, nesta ordem: configura os pinos SPI (`config-pin`), recompila tudo (`make clean && make`, que gera `ler_adc` e `fw_pru.out`), copia o firmware para `/lib/firmware/am335x-pru0-fw` e reinicia a PRU pelo `remoteproc`. Para conferir se a PRU subiu sem reclamar:

```bash
dmesg | tail -n 20
```

**Acerte o relógio.** A BeagleBone não tem bateria de RTC, então depois de ligada ela pode estar com a data errada, e o `timestamp` gravado no cabeçalho de cada captura sairia errado. No **computador**, com a BeagleBone conectada por USB, o script `scripts/set_date.sh` copia a data e hora do computador para ela (veja [Utilitários](#utilitários)). O `calibrar_sonda.sh` avisa quando o relógio marca um ano antes de 2024.

---

## Capturar com `ler_adc`

```bash
sudo ./ler_adc <frequencia_hz> [lista_de_canais] [opções]
```

`sudo` é necessário porque o programa acessa `/dev/mem`.

| Argumento | O que faz |
|---|---|
| `frequencia_hz` | Frequência **total** de amostragem, de 1 a 500000 Hz. Com mais de um canal, ela é dividida entre eles |
| `lista_de_canais` | Canais do ADS8688 separados por vírgula, sem espaços (ex.: `0,1,3`). Sem ela, captura só o **canal 1** |
| `--blocos N` | Captura exatamente N blocos e para. `N=0` captura até você apertar `Ctrl+C`. Padrão: 1 bloco |
| `--duracao T` | Alternativa a `--blocos`: captura por um tempo (`600`, `10m`, `1.5h`; sem sufixo = segundos). As duas flags são mutuamente exclusivas |
| `-o ARQUIVO` | Nome do `.bin` de saída. Sem ele: `captura_AAAAMMDD_HHMMSS.bin` (hora local) |
| `-t "título"` | Título curto gravado no cabeçalho (até 63 bytes em UTF-8) |
| `-d "descrição"` | Descrição gravada no cabeçalho (até 255 bytes). Texto maior que o limite é **erro**, não é truncado |
| `--grandeza C:G[,...]` | Grandeza de cada canal: `tensao`, `corrente` ou `temperatura` (ex.: `0:tensao,1:corrente`). Canal não citado = `tensao` |
| `--sonda C:ID[,...]` | Id da sonda usada em cada canal (ex.: `1:fluke_i30_01`), até 31 caracteres. É só um texto no cabeçalho; a correção é feita depois, no `adc_tool.py` |

Exemplos:

```bash
sudo ./ler_adc 102400                                   # 1 bloco, canal 1, nome automático
sudo ./ler_adc 102400 0,1,3 --blocos 5                  # 5 blocos, 3 canais
sudo ./ler_adc 102400 --blocos 0                        # indefinido, até Ctrl+C
sudo ./ler_adc 102400 --duracao 10m -o ensaio_bancada.bin \
    -t "Ensaio de bancada" -d "Sinal de 15 kHz injetado no canal 1"
sudo ./ler_adc 102400 0,1 --grandeza 0:tensao,1:corrente --sonda 1:fluke_i30_01
```

### Números úteis

* **1 bloco = 1.048.576 amostras** (somando todos os canais). A 102,4 kHz totais, isso é 10,24 s.
* **Tamanho do arquivo:** cada amostra ocupa 2 bytes. A 102,4 kHz são ~200 kB/s, ou cerca de 700 MB por hora.
* **Frequência efetiva por canal** = frequência total ÷ número de canais. A **Nyquist** de cada canal é metade disso. Exemplo: 5 canais a 102,4 kHz totais dão 20,48 kHz por canal e Nyquist de 10,24 kHz. Para enxergar supraharmônicos mais altos, use poucos canais ou aumente a frequência total.

### A ordem dos canais

O ADS8688 varre os canais habilitados **sempre em ordem crescente**, não na ordem digitada. O `ler_adc` ordena a lista e imprime a ordem real. Você não precisa se preocupar com isso na análise: o cabeçalho da captura já guarda a ordem correta.

---

## Levar a captura para o computador

Qualquer cópia serve. Com `scp`:

```bash
scp debian@<ip-da-beaglebone>:caminho/da/captura.bin .
```

Os `.bin` são grandes e ficam fora do Git (estão no `.gitignore`). Para guardar muitas capturas, `scripts/compactar_amostras.sh` compacta tudo num único arquivo (veja [Utilitários](#utilitários)).

---

## Analisar com `adc_tool.py`

```bash
uv run scripts/adc_tool.py captura.bin [opções]
```

O `uv` instala as dependências na primeira execução. Quando o `.bin` tem cabeçalho (todas as capturas feitas com o `ler_adc` atual têm), a frequência, os canais, a grandeza de cada canal e a sonda vêm de lá, e um resumo da captura é impresso antes da análise. O que você passar na linha de comando sempre tem prioridade sobre o cabeçalho.

A ferramenta tem três modos: **plotagem** (padrão), **conversão** `.bin` ↔ `.csv` e **exportação HDF5**. A referência completa de flags está em `uv run scripts/adc_tool.py --help`.

### Plotagem

```bash
uv run scripts/adc_tool.py captura.bin                      # só a forma de onda no tempo
uv run scripts/adc_tool.py captura.bin --fft                # + espectro por FFT
uv run scripts/adc_tool.py captura.bin --welch              # + espectro médio (Welch)
uv run scripts/adc_tool.py captura.bin --fft -o grafico.png # salva em arquivo em vez de abrir a janela
uv run scripts/adc_tool.py captura.bin --inicio 50000 --fim 150000 --fft   # só um trecho (índices de amostra)
```

Sem `-o`, abre uma janela interativa. Em um computador sem tela (por exemplo, via SSH), use sempre `-o`.

### Vários canais

```bash
# Só os canais 0 e 3, sobrepostos no mesmo eixo
uv run scripts/adc_tool.py captura.bin --canais-exibir 0,3 --layout-canais sobrepostos --fft
```

Cada canal tem a sua própria análise espectral. `--layout-canais` aceita `separados` (um gráfico por canal, padrão) e `sobrepostos`.

### Converter amostras em unidades físicas

Por padrão, o código de 16 bits do ADC vira Volts na entrada do ADC (`--formato uint16`, `--faixa 10.24`, `--ganho 1.0`, offset automático). Para ler a grandeza real, informe o ganho do frontend/sensor de cada canal, na ordem dos canais:

```bash
# Canal 0 = tensão (ganho 19.53), canal 1 = corrente (ganho 0.1)
uv run scripts/adc_tool.py captura.bin --ganho 19.53,0.1 --fft
```

`--faixa`, `--ganho` e `--offset` aceitam um valor (vale para todos os canais) ou uma lista (um por canal).

### Filtros digitais

Filtros Butterworth de fase zero, aplicados antes de qualquer análise:

```bash
uv run scripts/adc_tool.py captura.bin --filtro-passa-baixa 45000 --fft       # corta ruído perto da Nyquist
uv run scripts/adc_tool.py captura.bin --filtro-passa-alta 20 --ordem-filtro 8 --fft   # remove deriva de DC
```

### Normalização, bandas e picos

| Flag | Para quê |
|---|---|
| `--modo-espectro tom` (padrão) | Amplitude de um tom discreto |
| `--modo-espectro ruido` | Densidade espectral de potência (V²/Hz): correta para ruído de banda larga |
| `--agrupar-bandas HZ` | Resume o espectro em bandas de largura fixa (ex.: 200 Hz). Facilita comparar capturas com resoluções diferentes |
| `--picos LIMIAR_DB` | Lista no console a frequência e a amplitude dos picos acima do limiar (padrão: de 2 kHz até a Nyquist) |
| `--janela NOME` | Janela espectral: `retangular` (padrão), `hann`, `blackmanharris`, `flattop`, `kaiser` |

```bash
# Espectro médio, em bandas de 200 Hz, listando os picos acima de -60 dB
uv run scripts/adc_tool.py captura.bin --welch --agrupar-bandas 200 --picos -60
```

### Converter para CSV e exportar para HDF5

```bash
uv run scripts/adc_tool.py -c captura.bin -o captura.csv                         # .bin -> .csv
uv run scripts/adc_tool.py -c captura.csv -o captura_volta.bin                   # .csv -> .bin
uv run scripts/adc_tool.py captura.bin --export-hdf5 captura.h5 --incluir-tensao # HDF5
```

* O **HDF5** tem `/amostras` (códigos brutos, matriz amostras × canais), opcionalmente `/tensao_v` (em Volts) e todos os metadados do cabeçalho como atributos. O arquivo é escrito em blocos, então funciona mesmo com capturas de dezenas de GB.
* O **CSV** guarda só os valores brutos. O cabeçalho não sobrevive à ida e volta.
* Nenhuma das duas exportações aplica a [correção de sonda](#sondas-de-corrente-calibração-e-correção).

### Capturas sem cabeçalho (arquivos antigos)

Sem cabeçalho, informe você mesmo a frequência total e a lista de canais, na ordem impressa pelo `ler_adc`:

```bash
# Captura feita com: sudo ./ler_adc 102400 0,1,3
uv run scripts/adc_tool.py captura.bin -f 102400 --canais 0,1,3 --fft
```

---

## FFT ou Welch?

A FFT assume que o trecho analisado se repete infinitamente. Quando a "emenda" entre o fim e o começo do trecho é descontínua, parte da energia vaza para as frequências vizinhas (*vazamento espectral*) e borra os picos. Isso atrapalha principalmente quem procura um supraharmônico fraco ao lado de uma fundamental forte. Fundamental e supraharmônicos pedem tratamentos diferentes:

| | `--fft` | `--welch` |
|---|---|---|
| **Serve para** | Fundamental e harmônicos | Supraharmônicos |
| **Ideia** | Corta o sinal em um número inteiro de ciclos da rede, o que elimina o vazamento na origem | Divide o sinal em segmentos, calcula o espectro de cada um e tira a **média** |
| **Por que** | Fundamental e harmônicos têm fase travada na rede, então dá para sincronizar o corte | Supraharmônicos vêm de conversores chaveados e **não têm relação de fase com a rede**. Além disso, a frequência de chaveamento costuma oscilar (*dithering*), o que uma FFT longa borraria |
| **Custo** | Precisa da fundamental na faixa `--freq-min`/`--freq-max` (padrão 45–65 Hz) | Resolução fixa em frequência, definida por `--resolucao-welch` (padrão 200 Hz) |

Você pode usar as duas na mesma execução: cada uma desenha a sua curva.

```bash
uv run scripts/adc_tool.py captura.bin --fft              # todos os ciclos completos da janela
uv run scripts/adc_tool.py captura.bin --fft 10           # só os 10 primeiros ciclos (um distúrbio momentâneo)
uv run scripts/adc_tool.py captura.bin --welch --resolucao-welch 100 --filtro-passa-alta 2000
```

> ⚠️ **Cuidado ao combinar `--fft` com filtro passa-alta.** Um `--filtro-passa-alta` igual ou maior que `--freq-min` remove a fundamental, e o `--fft` não consegue mais sincronizar o corte em ciclos. O `adc_tool.py` detecta isso e avisa. Nesse caso, rode `--fft` e `--welch`/`--picos` em comandos separados.

Para os detalhes de implementação (estimativa da fundamental, janelas, normalização), veja a seção `pipeline_dsp_python` de [`contexto_projeto.md`](contexto_projeto.md).

---

## Sondas de corrente: calibração e correção

**Por quê:** o frontend de **tensão** tem ganho constante, então basta o `--ganho`. Uma **sonda de corrente**, ao contrário, atenua de forma diferente em cada frequência. Medir supraharmônicos de corrente sem corrigir isso dá amplitudes erradas. A solução é medir a resposta em frequência da sonda uma vez, guardar num **perfil** (`.json`) e deixar o `adc_tool.py` corrigir cada captura.

O fluxo tem três passos:

### Passo 1: coletar os pontos (na BeagleBone)

Monte a bancada: gerador de sinal, um **resistor shunt de precisão** em série com a sonda, o **canal 0** medindo a tensão sobre o shunt (a corrente real é V/R) e o **canal 1** lendo a saída da sonda. Ajuste a amplitude do gerador para o sinal ocupar de ~20% a ~80% da escala do ADC e **mantenha a mesma amplitude em todas as frequências**. Se a sua bancada usa outros canais, passe `--canal-referencia` e `--canal-sonda`.

Você só diz **quantos pontos** quer, a **taxa de amostragem** do ADC e o **nome da sonda**. O script escolhe as frequências, chama o `ler_adc` para cada uma (com cabeçalho preenchido corretamente), confere o `.bin` e guarda tudo no formato que o `gerar_perfil_sonda.py` lê:

```bash
cd firmware
sudo ./calibrar_sonda.sh --taxa 102400 --pontos 20 --sonda fluke_i30_sn0001
```

> Se aparecer `Permission denied`, o arquivo está sem permissão de execução: rode `chmod +x calibrar_sonda.sh` uma vez (ou use `sudo bash calibrar_sonda.sh`). Sem nenhuma opção, o script pergunta o que precisa. A taxa aceita `102400`, `102.4k` ou `102,4 kHz`.

**Quais frequências?** O script espalha os pontos em **escala logarítmica** entre 50 Hz e **80% da Nyquist efetiva** (a 102,4 kHz, de 50 Hz a 20,4 kHz), arredondados para valores fáceis de ajustar no gerador, e mostra o plano antes de começar. Escala logarítmica é a escolha padrão porque a resposta de uma sonda varia por décadas de frequência, e depois da primeira rodada o script sugere **pontos extras** onde o ganho mais variou entre vizinhos. Para outra faixa: `--freq-min` e `--freq-max`.

> **Nyquist efetiva.** A taxa que você informa é a **total**, dividida entre os dois canais: a 102,4 kHz, cada canal é amostrado a 51,2 kHz, e a maior frequência que dá para medir é **taxa ÷ 4 = 25,6 kHz**. O script recusa planos que passem disso e avisa acima de 90% do limite.

**Em cada ponto**, o script diz o que fazer:

```text
Ponto 4 de 20  |  129 Hz  |  repetição 1 de 1
  >>> INJETE 129 Hz no gerador <<<
  ENTER para medir  |  p = pular este ponto  |  a = abortar:
```

Você ajusta o gerador, aperta ENTER e espera ~10 s (um bloco a 102,4 kHz). O script então confere a captura:

* **cabeçalho**: taxa, canais, grandeza `corrente` no canal da sonda, id da sonda, CRC-32 e tamanho do arquivo (o `ler_adc` devolve sucesso mesmo quando o disco enche e a captura sai cortada, e só o tamanho revela isso);
* **saturação** do ADC (mais de 0,05% das amostras no fundo de escala, o mesmo critério que o `gerar_perfil_sonda.py` usa para descartar a captura);
* **nível do sinal**: sem sinal (gerador desligado, sonda fora do condutor) é erro; sinal fraco é aviso;
* **frequência realmente injetada**: se ficou mais de 5% fora do planejado, avisa; mais de 10%, é erro (o gerador está ajustado errado).

Ele mostra o nível de cada canal, a frequência medida e o **ganho relativo ao ponto de menor frequência** (em dB), o que ajuda a perceber na hora uma ligação errada. Depois você escolhe (ENTER aceita a sugestão: `C` se a captura está boa, `R` se tem erro):

| Tecla | O que faz |
|---|---|
| `C` | **Continuar**: aceita a captura e segue |
| `R` | **Refazer**: descarta e mede o mesmo ponto de novo |
| `P` | **Pular**: descarta e deixa o ponto de fora (dá para pegá-lo depois com `--modo retomar`) |
| `A` | **Abortar**: encerra; o que já foi aceito fica salvo |

Uma captura nunca vira ponto sem você aceitar: ela é gravada num arquivo temporário e só ganha o nome definitivo depois. Ctrl+C também é seguro (descarta a captura em andamento e mantém as aceitas). Se o `ler_adc` travar, o script o interrompe após um tempo limite e deixa você refazer o ponto.

**Modos** (`--modo`), todos sobre a mesma pasta `capturas/<id-da-sonda>/`:

| Modo | Para quê |
|---|---|
| `novo` (padrão) | Plano novo de `--pontos` frequências |
| `retomar` | Continua uma coleta interrompida: mede só o que falta do plano (taxa e canais vêm do plano salvo) |
| `refinar` | Acrescenta pontos onde o ganho muda mais entre frequências vizinhas (`--pontos N` = quantos extras) |
| `adensar` | Acrescenta 1 ponto (média geométrica) entre **cada** par de frequências já capturadas |
| `refazer` | Mede de novo pontos já aceitos (`--freqs 200,1000`; sem `--freqs`, sugere os aceitos com erro). A captura antiga só sai de cena depois que a nova é aceita, e vai para `descartadas/` |
| `resumo` | Só mostra a tabela da coleta e os próximos passos (não mede nada) |

Outras opções úteis: `--repeticoes N` (várias capturas por frequência: o `gerar_perfil_sonda.py` tira a média e registra o desvio entre repetições), `--blocos N` (capturas mais longas, boas para frequências baixas), `--sim`/`-y` (não pede confirmação do plano), `--verboso` (mostra a saída do `ler_adc`) e `--help` (lista completa).

**O que fica em disco** (em `capturas/<id-da-sonda>/`, na pasta onde você rodou o script):

| Arquivo | Conteúdo |
|---|---|
| `calibracao_<FREQ>Hz_rep<N>.bin` | As capturas aceitas, que o `gerar_perfil_sonda.py` lê |
| `pontos_coletados.csv` | Histórico de cada ponto: status (`ok`, `ok_com_aviso_...`, `aceito_com_erro_...`, `pulado`, `substituido`) e métricas rápidas |
| `plano_coleta.txt` | Taxa, canais, repetições e frequências do plano (é o que o `--modo retomar` lê) |
| `ler_adc.log` | Saída completa do `ler_adc` em cada tentativa |
| `descartadas/` | Capturas substituídas pelo `--modo refazer` (nunca são apagadas) |

Ao terminar, o script mostra a tabela da coleta (frequência medida, nível da sonda, ganho relativo) e o comando do próximo passo. Se você pedir uma coleta nova numa sonda que já tem pasta, ele oferece retomar ou arquivar a anterior em `capturas/_arquivadas/` (nada é apagado).

**Dica:** use de 15 a 25 pontos. Com poucos pontos (6, por exemplo), o erro de interpolação entre eles pode chegar a ~0,5% ou mais. O script avisa quando o plano tem menos de 10.

### Passo 2: gerar o perfil (no computador)

Copie a pasta `capturas/<id-da-sonda>/` para o computador e rode:

```bash
uv run scripts/gerar_perfil_sonda.py capturas/fluke_i30_sn0001 --resistencia-shunt 0.1 --plot
```

* `--resistencia-shunt OHMS` (recomendado) calcula a corrente real de cada ponto a partir da tensão medida sobre o shunt, o que absorve a deriva de amplitude do gerador. A alternativa é `--amplitude-referencia A`, para uma corrente constante em toda a varredura.
* O script **mede** a frequência e a amplitude de cada captura (não confia no nome do arquivo), descarta capturas com sinal fraco demais (SNR abaixo de 20 dB) e avisa se alguma repetição divergir mais de 10%.
* `--plot` salva um PNG com a curva obtida.
* Use os mesmos `--formato`, `--faixa` e `--ganho` que você usará no `adc_tool.py`; o `adc_tool.py` avisa se forem diferentes.

O resultado é `scripts/sondas/<id>.json`. Para ver o formato de um perfil, abra [`exemplo_sonda.json`](exemplo_sonda.json).

### Passo 3: usar o perfil na análise

Se a captura foi feita com `--grandeza` e `--sonda`, **não há nada a fazer**: o `adc_tool.py` lê o id no cabeçalho, procura `scripts/sondas/<id>.json` e aplica a correção sozinho.

```bash
sudo ./ler_adc 102400 0,1 --grandeza 0:tensao,1:corrente --sonda 1:fluke_i30_sn0001   # na BeagleBone
uv run scripts/adc_tool.py captura.bin --welch --picos -60                             # no computador
```

Outras situações:

```bash
# Captura antiga, sem sonda no cabeçalho: aponte o perfil na mão
uv run scripts/adc_tool.py captura.bin --grandeza 1:corrente --sonda-perfil 1:scripts/sondas/fluke_i30_sn0001.json --welch

# Comparar com o espectro sem correção
uv run scripts/adc_tool.py captura.bin --sem-correcao-sonda --welch
```

### O que a correção não faz

* Corrige a **amplitude** por frequência, **não a fase**. Não use para análises que dependam da fase relativa entre tensão e corrente (potência por componente, por exemplo).
* O perfil descreve a **sonda e a cadeia de aquisição juntas** (ADC, isolador, frontend). Se o frontend mudar, recalibre.
* A confiabilidade física do perfil depende da bancada: tolerância e indutância parasita do shunt, qualidade do gerador, linearidade da sonda.
* As exportações CSV/HDF5 não aplicam a correção.

A análise completa dos limites está em [`auditoria_perfil_sonda.md`](auditoria_perfil_sonda.md).

---

## O arquivo `.bin`

Um `.bin` é um **cabeçalho fixo de 1024 bytes** seguido das **amostras brutas** (2 bytes cada, intercaladas por canal: com N canais, a amostra `i` pertence ao canal `lista_canais[i % N]`).

O cabeçalho começa com o texto `SHAN` e termina com um **CRC-32**; se o `adc_tool.py` perceber que o CRC não confere (arquivo truncado ou corrompido), ele avisa. Campos principais:

| Campo | Descrição |
|---|---|
| `versao_cabecalho` | Versão do formato (hoje 2) |
| `timestamp_unix` | Instante da captura (UTC) |
| `frequencia_hz` | Frequência total de amostragem |
| `lista_canais` | Canais capturados, em ordem crescente |
| `grandeza_por_canal`, `sonda_id_por_canal` | Grandeza e sonda de cada canal (versão 2) |
| `samples_per_buffer`, `bytes_por_amostra` | Geometria dos blocos |
| `blocos_gravados`, `total_amostras_gravadas` | Totais reais, preenchidos ao final da captura |
| `titulo`, `descricao` | Texto livre (`-t`, `-d`) |
| `header_crc32` | Detecta corrupção do cabeçalho |

Arquivos feitos antes do cabeçalho existir continuam sendo lidos (veja [Capturas sem cabeçalho](#capturas-sem-cabeçalho-arquivos-antigos)), e os de versão 1 do cabeçalho também. A tabela completa, com os deslocamentos de cada campo, está em [`contexto_projeto.md`](contexto_projeto.md) (seção `formato_bin_v2`).

---

## Utilitários

| Script | Onde roda | O que faz |
|---|---|---|
| `scripts/set_date.sh` | Computador | Copia a data e hora do computador para a BeagleBone via SSH (como instante absoluto em UTC, então vale qualquer que seja o fuso dela). Padrão: `debian@192.168.6.2`; troque com `BBB_USER` e `BBB_IP`. **Nenhuma senha fica no arquivo:** use chave SSH (`ssh-copy-id debian@192.168.6.2`) ou deixe o `ssh`/`sudo` pedirem a senha no terminal. Se preferir não digitar, exporte `SSHPASS` (e tenha o `sshpass` instalado) |
| `scripts/compactar_amostras.sh` | Computador | Compacta `.bin` e `.h5` de uma pasta num único arquivo, priorizando a taxa de compressão. Padrão: 7-Zip (LZMA2). `--max` usa `zpaq -m5`, mais lento e mais forte. Opções: `--dir PASTA`, `-o ARQUIVO` |

---

## Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `uv: command not found` | `uv` não instalado | Instale o [`uv`](https://docs.astral.sh/uv/) |
| A janela do gráfico não abre | Computador sem tela (SSH, servidor) | Use `-o grafico.png` para salvar em arquivo |
| `-f/--frequencia é obrigatório no modo de plotagem` | Arquivo sem cabeçalho (captura antiga) | Informe `-f` (frequência total) e `--canais` |
| Aviso "CRC-32 do cabeçalho NÃO confere" | Cópia truncada ou arquivo corrompido | Copie o arquivo de novo e compare o tamanho. Os campos mostrados podem estar errados |
| Aviso "canal N é de corrente mas não tem sonda/perfil resolvido" | A captura não registrou a sonda | Use `--sonda-perfil N:ARQUIVO.json` (ou refaça a captura com `--sonda`) |
| A captura não termina e nenhuma linha `Bloco A gravado (...)` aparece | PRU parada ou presa | Confira `dmesg \| tail -n 20` e `cat /sys/class/remoteproc/remoteproc1/state`. Rode `./setup.sh` de novo |
| Timestamp do cabeçalho errado | Relógio da BeagleBone desatualizado | Rode `scripts/set_date.sh` no computador |
| `--fft` dá resultado estranho depois de aplicar passa-alta | Filtro removeu a fundamental | Veja o aviso em [FFT ou Welch?](#fft-ou-welch) e rode `--fft` e `--welch` separados |
| `ler_adc` recusa o `-t` ou o `-d` com erro | Título acima de 63 bytes ou descrição acima de 255 (o texto não é truncado) | Encurte o texto (letras acentuadas ocupam 2 bytes) |
| Canais parecem trocados | Você digitou os canais fora de ordem | O ADC sempre varre em ordem crescente. Deixe a ordem vir do cabeçalho (não passe `--canais`) |
| `Permission denied` ao rodar `calibrar_sonda.sh` | Arquivo sem permissão de execução | `chmod +x calibrar_sonda.sh` |
| `calibrar_sonda.sh`: "o `ler_adc` travou (estourou o tempo limite)" | PRU parada ou presa | Confira o `dmesg` e rode `./setup.sh` de novo; depois refaça o ponto (`R`) |
| `calibrar_sonda.sh`: "captura incompleta (disco cheio?)" | O `ler_adc` devolve sucesso mesmo com o disco cheio, a captura sai cortada | Libere espaço (copie capturas antigas para o computador) e refaça o ponto |
| `calibrar_sonda.sh`: "saturou o ADC" | Amplitude do gerador (ou corrente) alta demais | Reduza a amplitude e refaça o ponto. Capturas saturadas são descartadas pelo `gerar_perfil_sonda.py` |
| `calibrar_sonda.sh`: "frequência medida fora da planejada" | Gerador ajustado errado | Corrija a frequência no gerador e refaça o ponto |
| `calibrar_sonda.sh`: "praticamente sem sinal" | Gerador desligado, shunt/sonda mal ligados ou canal errado | Confira a bancada e os números de `--canal-referencia`/`--canal-sonda` |

Se o problema não está aqui, a referência técnica completa está em [`contexto_projeto.md`](contexto_projeto.md).
