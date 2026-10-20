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
8. [Medir uma captura para o relatório: `medir_captura.py`](#medir-uma-captura-para-o-relatório-medir_capturapy)
9. [Guardar as capturas sem perdas: `compactar_amostras.py`](#guardar-as-capturas-sem-perdas-compactar_amostraspy)
10. [O arquivo `.bin`](#o-arquivo-bin)
11. [Utilitários](#utilitários)
12. [Problemas comuns](#problemas-comuns)

Indo ao laboratório validar o projeto inteiro? Siga o [`roteiro_laboratorio.md`](roteiro_laboratorio.md): testes numerados, sinal a injetar em cada um, comandos e o que anotar.

> Os comandos `uv run scripts/...` deste guia são executados **a partir da raiz do repositório**, no computador (`./scripts/adc_tool.py ...` também funciona: o próprio script chama o `uv`). Os comandos `./setup.sh`, `./ler_adc` e `./calibrar_sonda.sh` são executados **na BeagleBone**, dentro da pasta `firmware/`.

---

## O fluxo em resumo

| Etapa | Onde | Ferramenta | Resultado |
|---|---|---|---|
| 1. Preparar | BeagleBone | `firmware/setup.sh` | Pinos configurados, firmware da PRU carregado, `ler_adc` compilado |
| 2. Capturar | BeagleBone | `firmware/ler_adc` | Arquivo `.bin` autodescritivo |
| 3. Transferir | — | `scp` (ou similar) | `.bin` no seu computador |
| 4. Analisar | Computador | `scripts/adc_tool.py` | Gráficos, lista de picos, CSV ou HDF5 |
| (extra) Calibrar sonda | BeagleBone + computador | `firmware/calibrar_sonda.sh` → `scripts/gerar_perfil_sonda.py` | Perfil `.json` que corrige a resposta em frequência da sonda |
| (extra) Medir para o relatório | Computador | `scripts/medir_captura.py` | Números com unidade (ruído, THD, SINAD, ENOB, SFDR, continuidade, diafonia) e uma linha de CSV por canal |

---

## Preparar a BeagleBone

**Antes de ligar:** conecte a placa de aquisição ao frontend analógico com o cabo mais curto possível. Jumpers longos acoplam ruído no barramento SPI e saturam as leituras do ADC.

**Pré-requisitos na BeagleBone:** `gcc` e o compilador `clpru` da Texas Instruments.

**Primeira vez, e depois de qualquer mudança no firmware:**

```bash
cd firmware
./setup.sh
```

O `setup.sh` faz, nesta ordem: configura os pinos SPI (`config-pin`), recompila tudo (`make clean && make`, que gera `ler_adc` e `fw_pru.out`), copia o firmware para `/lib/firmware/am335x-pru0-fw` e reinicia a PRU pelo `remoteproc`. Ele para no primeiro erro (uma compilação que falha não carrega firmware velho na PRU) e, no fim, confere que a PRU ficou rodando; se não ficou, mostra as últimas mensagens do kernel. Para conferir à mão:

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
| `--faixa-adc C:V[,...]` | **Faixa de entrada do ADC** de cada canal, como fundo de escala total em Volts: `20.48` (±10,24 V, o padrão), `10.24` (±5,12 V) ou `5.12` (±2,56 V). Ex.: `0:20.48,1:5.12`. Canal não citado = `20.48`. Veja [Faixa de entrada do ADC](#faixa-de-entrada-do-adc) |
| `--atraso-cs S,H,A` | **Experimental.** Atrasos do CS em cada amostra, em passos de 10 ns: CS descendo → 1º clock, último clock → CS subindo, CS alto entre amostras. Padrão `200,100,100` (2/1/1 µs, os validados). Veja [Integridade e taxa máxima](#integridade-da-captura-e-taxa-máxima) |

Exemplos:

```bash
sudo ./ler_adc 102400                                   # 1 bloco, canal 1, nome automático
sudo ./ler_adc 102400 0,1,3 --blocos 5                  # 5 blocos, 3 canais
sudo ./ler_adc 102400 --blocos 0                        # indefinido, até Ctrl+C
sudo ./ler_adc 102400 --duracao 10m -o ensaio_bancada.bin \
    -t "Ensaio de bancada" -d "Sinal de 15 kHz injetado no canal 1"
sudo ./ler_adc 102400 0,1 --grandeza 0:tensao,1:corrente --sonda 1:fluke_i30_01
sudo ./ler_adc 100000 0,1 --faixa-adc 0:20.48,1:5.12   # canal 0 em ±10,24 V, canal 1 (sinal pequeno) em ±2,56 V
```

### Faixa de entrada do ADC

O ADS8688 converte cada canal em 16 bits dentro de uma **faixa de entrada** programável **por canal**. Quanto menor a faixa, menor o degrau de quantização (LSB) em Volts, e o mesmo sinal é medido com mais resolução:

| `--faixa-adc` (fundo de escala total) | Faixa de entrada | LSB (16 bits) | Quando usar |
|---|---|---|---|
| `20.48` (padrão) | ±10,24 V | 312,5 µV | Sinais que chegam perto de 10 V de pico (o canal de tensão da rede, depois do divisor) |
| `10.24` | ±5,12 V | 156,3 µV | Sinais de até ~4,5 V de pico |
| `5.12` | ±2,56 V | 78,1 µV | Sinais de até ~2,2 V de pico: saída de sondas de corrente e sensores de mV |

* **Escolha a menor faixa que comporta o pico do sinal, com 10 a 20% de margem.** Faixa maior que o necessário desperdiça resolução; faixa menor corta o sinal (o ADC satura em 0 ou 65535 e a captura perde a forma de onda). O erro de quantização cai exatamente na proporção da faixa (4x entre `20.48` e `5.12`); o ruído do próprio ADC cai menos, porque o SNR típico do datasheet também cai um pouco nas faixas menores (92, 91 e 89 dB). Meça o ganho real no passo T2 do [roteiro de laboratório](roteiro_laboratorio.md).
* **O que o programa faz.** A PRU escreve a faixa de cada canal habilitado nos registradores `RANGE_SELn` do ADC **a cada captura** (o ADC guarda o valor entre capturas) e o `ler_adc` grava o código no cabeçalho (versão 3). Sem `--faixa-adc`, todos os canais ficam em `20.48`, o padrão de fábrica do ADC.
* **Na análise, não precisa informar.** O `adc_tool.py`, o `medir_captura.py` e o `gerar_perfil_sonda.py` convertem cada canal em Volts com a faixa gravada no cabeçalho. Um `--faixa` digitado **vence**, mas avisa se divergir do cabeçalho. Capturas de versão 1 ou 2 do cabeçalho não registram a faixa: assumem `--faixa 10.24`, como sempre foi (confirme com um sinal de amplitude conhecida, passo T0 do roteiro).
* As faixas unipolares do ADS8688 (0 a 5 V, 0 a 10 V) **não** são suportadas: o pós-processamento assume saída bipolar, com 0 V no meio da escala.

### Integridade da captura e taxa máxima

Enquanto captura, a PRU conta três coisas que indicariam dados ruins, sem custo para a amostragem (as contas ficam na folga entre uma amostra e a espera pela próxima, e só são publicadas a cada bloco). O `ler_adc` avisa a cada bloco, imprime um resumo no fim e grava os três no cabeçalho (versão 4):

| Contador | O que significa | O que fazer |
|---|---|---|
| amostras atrasadas | A PRU chegou atrasada para tomar a amostra: a taxa pedida passou do que ela alcança (~140 kS/s com os atrasos padrão). A taxa real do arquivo é **menor** que a do cabeçalho | Peça uma taxa menor (até 100 kS/s é o seguro) |
| buffers sobrescritos | A PRU começou a reescrever um bloco que o ARM ainda não tinha gravado: amostras **perdidas**. O `ler_adc` sai com código 3 | Refaça a captura; veja se o cartão SD está lento ou o sistema sobrecarregado |
| quadros com ruído no SDO | O ADC mantém a linha de dados em 0 durante o comando de cada amostra; um 1 ali é ruído ou reflexo na ligação (o problema histórico dos jumpers longos) | Confira a ligação ADC ↔ BeagleBone; essas amostras são suspeitas |

No fim, o `ler_adc` também mostra a **taxa real**, medida pelo relógio do ARM entre o primeiro e o último bloco (precisa de 2 blocos ou mais; incerteza ~0,02 %). O `adc_tool.py`, o `medir_captura.py` e o `gerar_perfil_sonda.py` avisam quando um contador do cabeçalho não é zero, e a calibração de sonda descarta a captura com amostras perdidas ou atrasadas.

**O que limita a taxa.** Cada amostra leva ~7 µs na PRU: ~3 µs são os 32 clocks do SPI (feitos em software) e ~4 µs são três esperas do CS (2, 1 e 1 µs), calibradas na época do problema dos jumpers. O datasheet do ADS8688 pede só 30, 10 e 30 ns. Com `--atraso-cs` dá para medir em bancada até onde elas podem cair (teste T7e do [roteiro](roteiro_laboratorio.md)); só reduzi-las levaria o teto de ~140 para ~330 kS/s. Valores reduzidos são **experimentais**: confira o ruído, a distorção e a continuidade antes de usar uma captura feita assim.

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

Os `.bin` são grandes e ficam fora do Git (estão no `.gitignore`). Para guardar muitas capturas, o `compactar_amostras.py` as arquiva sem perdas num único pacote com ~11 % do tamanho (veja [Guardar as capturas sem perdas](#guardar-as-capturas-sem-perdas-compactar_amostraspy)).

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

Numa captura de vários canais, `--inicio` e `--fim` contam amostras **brutas** (com 2 canais, 2 por instante). Se `--inicio` cair no meio de um ciclo de canais, ele é arredondado para baixo até o começo do ciclo (com aviso): senão um canal seria lido com o rótulo do outro.

Sem `-o`, abre uma janela interativa. Em um computador sem tela (por exemplo, via SSH), use sempre `-o`.

### Vários canais

```bash
# Só os canais 0 e 3, sobrepostos no mesmo eixo
uv run scripts/adc_tool.py captura.bin --canais-exibir 0,3 --layout-canais sobrepostos --fft
```

Cada canal tem a sua própria análise espectral. `--layout-canais` aceita `separados` (um gráfico por canal, padrão) e `sobrepostos`.

### Converter amostras em unidades físicas

Por padrão, o código de 16 bits do ADC vira Volts na entrada do ADC (`--formato uint16`, `--faixa` lida do cabeçalho da captura, ou 10.24 em capturas antigas, `--ganho 1.0`, offset automático). Para ler a grandeza real, informe o ganho do frontend/sensor de cada canal, na ordem dos canais:

```bash
# Canal 0 = tensão (ganho 19.53), canal 1 = corrente (ganho 0.1)
uv run scripts/adc_tool.py captura.bin --ganho 19.53,0.1 --fft
```

`--faixa`, `--ganho` e `--offset` aceitam um valor (vale para todos os canais) ou uma lista (um por canal). `--faixa` é o **fundo de escala total** em Volts (`20.48` para ±10,24 V; `10.24` para ±5,12 V; `5.12` para ±2,56 V, com `--formato uint16`) e quase nunca precisa ser digitado: veja [Faixa de entrada do ADC](#faixa-de-entrada-do-adc).

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
| `--modo-espectro ruido` | Densidade espectral de potência (V²/Hz; A²/Hz num canal de corrente): correta para ruído de banda larga |
| `--agrupar-bandas HZ` | Resume o espectro em bandas de largura fixa (ex.: 200 Hz), com o nível **RMS** de cada banda. Facilita comparar capturas com resoluções diferentes; dá o mesmo valor em `tom` e em `ruido`, com qualquer janela |
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

O canal de **tensão** também passa pelo filtro de ~15 kHz do ADC (veja abaixo), então, para supraharmônicos de tensão, a cadeia de tensão (divisor + frontend + ADC) é calibrada com o **mesmo fluxo**, como se fosse uma sonda: `calibrar_sonda.sh --grandeza tensao`. O que muda é só a bancada (o gerador vai direto à entrada do divisor, sem shunt) e os textos do script; o perfil é aplicado ao canal de tensão em produção com `--sonda <canal>:<id>`.

O fluxo tem três passos:

### Passo 1: coletar os pontos (na BeagleBone)

> **O que é "a sonda" neste projeto.** O perfil descreve o **conjunto medido de ponta a ponta**: a sonda de corrente (ou, com `--grandeza tensao`, o divisor/ponta do canal de tensão), o frontend/isolador e o ADS8688 (que tem um filtro passa-baixa interno de 2ª ordem em cada canal, corte de ~15 kHz). Tudo o que esse conjunto atenua ou realça entra no ganho por frequência do perfil, e a correção em produção o desfaz. Por isso a referência precisa ser **o que foi injetado na entrada do conjunto**, e a frequência de corte do filtro do ADC não precisa ser conhecida: ela aparece na curva medida.

Para o perfil, o script precisa saber **o que foi injetado** em cada frequência. Há quatro jeitos (escolha um):

| Jeito | Opção do `calibrar_sonda.sh` | Canais por captura | Nyquist por canal | Quando usar |
|---|---|---|---|---|
| **Amplitude conhecida** | `--amplitude 500mVpp` (ou `--amplitude-por-ponto`) | **1** (só a saída da sonda) | taxa ÷ 2 | O gerador injeta uma **senoide pura** de amplitude e frequência ajustáveis e você **sabe a amplitude** que ajustou. Nada é digitado a cada ponto: amplitude e frequência ficam gravadas nos **metadados** de cada captura, e várias frequências dão o perfil |
| **Osciloscópio** | `--ref-externa` (leitura digitada) ou o `.m` do osciloscópio (veja abaixo) | **1** | taxa ÷ 2 | Chega até a banda inteira de supraharmônicos, e o osciloscópio mede o que o gerador **de fato** entregou (planura do gerador incluída) |
| Segundo canal do ADC | `--canal-referencia N` | 2 (sonda e shunt) | taxa ÷ 4 | Sem instrumento externo. O shunt (ou a entrada da cadeia de tensão) vai a um segundo canal; divide a taxa entre os dois. **O filtro de ~15 kHz do ADC é igual nos dois canais e se cancela na razão: o perfil sai sem ele** |
| Amplitude constante, sem declarar | (nenhuma das anteriores) | 1 | taxa ÷ 2 | Você mantém a mesma amplitude em todas as frequências e a informa só depois, em `gerar_perfil_sonda.py --amplitude-referencia` (a deriva do gerador entra no perfil) |

**Corrente ou tensão?** `--grandeza corrente` (o padrão) ou `--grandeza tensao`. Vai para o cabeçalho de cada captura (`ler_adc --grandeza`), fica no plano (`--modo retomar` a herda) e muda as instruções: com `tensao`, o osciloscópio mede a tensão **na entrada da cadeia** (não há shunt), a leitura vai para a coluna `tensao_rms_V` do `referencia_externa.csv` e o comando sugerido no fim não leva `--resistencia-shunt`. Sem a opção, o modo interativo pergunta. Coletas feitas antes dessa opção ficaram marcadas como corrente (é só um rótulo: nos modos de 1 canal o `gerar_perfil_sonda.py` não o usa).

**Qual canal?** Por padrão a calibração usa **um canal só**, e o número dele é obrigatório: `--canal-sonda N` (0 a 7; se você esquecer, o script pergunta). É o canal onde a saída da sonda está ligada, o mesmo que você usará em produção: o perfil descreve a cadeia daquele canal.

Monte a bancada: gerador de sinal (com amplificador, se precisar de mais corrente), o condutor atravessando a garra da sonda e, nos jeitos que medem a corrente, um **resistor shunt de precisão e baixa indutância** em série. Com `--ref-externa`, o osciloscópio mede a tensão sobre o shunt (a corrente real é V ÷ R); com `--canal-referencia`, um segundo canal do ADC faz isso. Com `--amplitude`, não há nada para medir: vale a amplitude que você ajustou no gerador. A amplitude pode variar de uma frequência para outra em todos os jeitos, **menos** no de amplitude constante sem declarar (use `--amplitude-por-ponto` quando ela mudar). Ajuste para o sinal da sonda ocupar ~20% a ~80% da escala do ADC, sem saturar.

**Amplitude conhecida (`--amplitude`).** Sinal injetado: uma **senoide pura** (a conversão entre pico a pico, pico e eficaz só vale para senoide) com amplitude e frequência reguláveis.

* **Como escrever a amplitude:** número + unidade + tipo, sempre os três: `500mVpp` (pico a pico), `250mVpk` (pico), `176.8mVrms` (eficaz), `2Arms`. `500mV` sozinho é recusado de propósito: pico a pico, pico e eficaz diferem por um fator 2 ou 1,41, que viraria erro de ganho silencioso. Prefixos `n`, `u` (ou `µ`), `m` e `k`; espaços e vírgula decimal são aceitos.
* **Em V ou em A.** Em **V**, é a tensão injetada no ponto onde o `--ganho` do canal é aplicado (a saída da sonda, antes do ganho); a grandeza física injetada é `V × ganho` (500 mVpp com `--ganho 10` são 2,5 A de pico). Em **A**, é a própria corrente. Na **cadeia de tensão** isso quer dizer a tensão **no pino do ADC**, não a da entrada do divisor: 20 Vpp na entrada × 0,051662 = `--amplitude 1.0332Vpp` (o script pergunta assim e recusa amplitude em A com `--grandeza tensao`). O ganho do perfil sai como (amplitude medida) ÷ (amplitude injetada), na mesma grandeza física.
* **Metadados.** Cada captura sai do `ler_adc` com `ref: f=1000Hz amp=500mVpp` no campo `descricao` do cabeçalho (`-d`), e o `gerar_perfil_sonda.py` lê esse trecho: não há nada para digitar depois. Se a amplitude muda entre pontos (o gerador não mantém o nível, ou você a reduziu para não saturar), use `--amplitude-por-ponto`: o script pergunta a amplitude de cada frequência (ENTER mantém a anterior; `--amplitude` dá o valor inicial).
* **Cuidados com o gerador.** (1) O "500 mVpp" do display de um gerador vale para carga de **50 Ω**; numa entrada de alta impedância a tensão real é o **dobro** (1 Vpp). Configure o gerador para *High-Z* ou confira com o osciloscópio. (2) A planura do gerador em função da frequência (décimos de dB, mais em frequência alta) entra no perfil como se fosse da sonda; por isso vale conferir alguns pontos com o osciloscópio (veja "Conferir o método"). (3) Se você injeta **tensão** no lugar da saída da sonda, o perfil mede o frontend e o ADC, **sem a sonda de corrente**; para incluí-la, injete **corrente** de verdade pela garra (amplitude em A, conhecida pela tensão no shunt ÷ R).

Você só diz **quantos pontos** quer, a **taxa de amostragem** do ADC e o **nome da sonda**. O script escolhe as frequências, chama o `ler_adc` para cada uma (com cabeçalho preenchido corretamente), confere o `.bin` e guarda tudo no formato que o `gerar_perfil_sonda.py` lê:

```bash
cd firmware
# 1 canal, referência no osciloscópio, até a banda de supraharmônicos (Nyquist 200 kHz, pontos até 160 kHz):
sudo ./calibrar_sonda.sh --taxa 400000 --canal-sonda 1 --pontos 24 --freq-max 160k --sonda fluke_i30_sn0001 --ref-externa

# Amplitude conhecida: senoide de 500 mVpp no gerador, a mesma em todos os pontos; vai para os metadados de cada captura
sudo ./calibrar_sonda.sh --taxa 400000 --canal-sonda 1 --pontos 24 --freq-max 160k --sonda fluke_i30_sn0001 --amplitude 500mVpp

# Sem osciloscópio: segundo canal do ADC (canal 0) no shunt; Nyquist por canal = taxa/4
sudo ./calibrar_sonda.sh --taxa 204800 --canal-sonda 1 --canal-referencia 0 --pontos 20 --sonda fluke_i30_sn0001

# Cadeia de tensão (divisor no canal 1), referência no osciloscópio na entrada do divisor
sudo ./calibrar_sonda.sh --taxa 100000 --canal-sonda 1 --pontos 24 --freq-max 45k --sonda cadeia_tensao --grandeza tensao --ref-externa

# Sonda com saída de poucos mV: faixa de entrada do ADC de ±2,56 V no canal da sonda (mais resolução)
sudo ./calibrar_sonda.sh --taxa 100000 --canal-sonda 1 --pontos 20 --sonda fluke_i30_sn0001 --amplitude 5mVpp --faixa-adc 5.12
```

`--faixa-adc` (e `--faixa-adc-referencia`, para o canal de referência) escolhe a [faixa de entrada do ADC](#faixa-de-entrada-do-adc), vale para todo o plano (fica em `plano_coleta.txt`, e `--modo retomar` a reaproveita) e é conferida no cabeçalho de cada captura. Escolha a menor faixa que comporta o pico da saída da sonda, sem saturar nas amplitudes mais altas do plano.

> Se aparecer `Permission denied`, o arquivo está sem permissão de execução: rode `chmod +x calibrar_sonda.sh` uma vez (ou use `sudo bash calibrar_sonda.sh`). Sem nenhuma opção, o script pergunta o que precisa. A taxa aceita `102400`, `102.4k` ou `102,4 kHz`.

**Quais frequências?** O script espalha os pontos em **escala logarítmica** entre 50 Hz e **80% da Nyquist efetiva** (com 1 canal a 400 kHz, de 50 Hz a 160 kHz; com 2 canais a 102,4 kHz, de 50 Hz a 20,4 kHz), arredondados para valores fáceis de ajustar no gerador, e mostra o plano antes de começar. Escala logarítmica é a escolha padrão porque a resposta de uma sonda varia por décadas de frequência, e depois da primeira rodada o script sugere **pontos extras** onde o ganho mais variou entre vizinhos. Para outra faixa: `--freq-min` e `--freq-max`.

> **Nyquist efetiva.** A taxa que você informa é a **total**, dividida entre os canais da captura. Com **1 canal** (o padrão), ele é amostrado a essa taxa e a maior frequência que dá para medir é **taxa ÷ 2**: a 400 kHz, 200 kHz. Com **2 canais** (`--canal-referencia`), cada um é amostrado à metade da taxa e o limite cai para **taxa ÷ 4**: a 500 kHz (o máximo do ADC), 125 kHz, o que **não cobre** os 150 kHz dos supraharmônicos. Por isso, para calibrar até 150 kHz, use 1 canal e pelo menos ~400 kHz. O script recusa planos a partir de 98% do limite e avisa acima de 90%.
>
> **O ADS8688 tem um filtro passa-baixa interno de 2ª ordem em cada canal, com corte de ~15 kHz** (seção 8.3.5 do datasheet). Acima disso o sinal chega ao conversor cada vez menor (algo como −15 a −21 dB em 50 kHz e −33 a −40 dB em 150 kHz, a medir). Por isso o script avisa "sinal fraco" nas frequências altas: é esperado. Mantenha a amplitude no pino do ADC alta (~4 V de pico) para que o sinal ainda fique acima do ruído. O perfil gerado inclui esse filtro, e a correção devolve a amplitude, **amplificando também o ruído** na mesma proporção (+30 dB em 100 kHz).

**Em cada ponto**, o script diz o que fazer:

```text
Ponto 4 de 20  |  129 Hz  |  repetição 1 de 1
  >>> INJETE 129 Hz no gerador <<<
  ENTER para medir  |  p = pular este ponto  |  a = abortar:
```

Você ajusta o gerador e aperta ENTER. Com `--amplitude`, a instrução também diz a amplitude (`Ajuste o gerador para uma SENOIDE pura de 500mVpp`); com `--amplitude-por-ponto`, o script pergunta a amplitude que o gerador está injetando (`Amplitude da senoide no gerador (...) [anterior]`). Com `--ref-externa`, o script pede então a leitura do osciloscópio (`Osciloscópio: tensão RMS no shunt, em V (ex.: 0.7071 ou 707.1m)`; com `--grandeza tensao`, `tensão RMS na entrada da cadeia`); leia o **RMS de ciclos inteiros, com média**, e digite (ENTER sem valor deixa o ponto sem referência, e o gerador de perfil o descarta). A captura leva ~10 s (um bloco a 102,4 kHz). O script então confere a captura:

* **cabeçalho**: taxa, canais, a grandeza pedida no canal da sonda (`corrente` ou `tensão`), id da sonda, CRC-32 e tamanho do arquivo (o `ler_adc` devolve sucesso mesmo quando o disco enche e a captura sai cortada, e só o tamanho revela isso);
* **saturação** do ADC (mais de 0,05% das amostras no fundo de escala, o mesmo critério que o `gerar_perfil_sonda.py` usa para descartar a captura);
* **nível do sinal**: sem sinal (gerador desligado, sonda fora do condutor, menos de 0,2% da escala pico a pico) é erro; abaixo de 10% da escala é aviso de sinal fraco;
* **frequência realmente injetada**: se ficou mais de 5% fora do planejado, avisa; mais de 10%, é erro (o gerador está ajustado errado).

Ele mostra o nível de cada canal, a frequência medida e o **ganho relativo ao ponto de menor frequência** (em dB; com amplitude conhecida, já descontada a amplitude injetada em cada ponto), o que ajuda a perceber na hora uma ligação errada. Depois você escolhe (ENTER aceita a sugestão: `C` se a captura está boa, `R` se tem erro):

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
| `calibracao_<FREQ>Hz_rep<N>.bin` | As capturas aceitas, que o `gerar_perfil_sonda.py` lê. O campo `descricao` do cabeçalho leva o que foi injetado (`ref: f=1000Hz amp=500mVpp`; só `f=` se a amplitude não foi declarada) |
| `referencia_externa.csv` | Só com `--ref-externa`: a tensão RMS que você digitou em cada ponto, na coluna `v_shunt_rms_V` (corrente: tensão no shunt) ou `tensao_rms_V` (tensão: entrada da cadeia) |
| `pontos_coletados.csv` | Histórico de cada ponto: status (`ok`, `ok_com_aviso_...`, `aceito_com_erro_...`, `pulado`, `substituido`), métricas rápidas e a amplitude injetada (`amplitude_ref`) |
| `plano_coleta.txt` | Grandeza, taxa, canais, amplitude, repetições e frequências do plano (é o que o `--modo retomar` lê) |
| `ler_adc.log` | Saída completa do `ler_adc` em cada tentativa |
| `descartadas/` | Capturas substituídas pelo `--modo refazer` (nunca são apagadas) |

Ao terminar, o script mostra a tabela da coleta (frequência medida, nível da sonda, ganho relativo) e o comando do próximo passo. Se você pedir uma coleta nova numa sonda que já tem pasta, ele oferece retomar ou arquivar a anterior em `capturas/_arquivadas/` (nada é apagado).

**Dica:** use de 15 a 25 pontos. Com poucos pontos (6, por exemplo), o erro de interpolação entre eles pode chegar a ~0,5% ou mais. O script avisa quando o plano tem menos de 10.

### Passo 2: gerar o perfil (no computador)

Copie a pasta `capturas/<id-da-sonda>/` para o computador e rode o comando que corresponde ao jeito que você usou no passo 1:

```bash
# --amplitude (1 canal, senoide de amplitude conhecida): nenhuma flag de referência, a amplitude de cada captura está nos metadados
uv run scripts/gerar_perfil_sonda.py capturas/fluke_i30_sn0001 --ganho 10 --plot

# --ref-externa (1 canal + osciloscópio). --resistencia-shunt é o valor EFETIVO do shunt (R/N se o fio deu N voltas na garra)
uv run scripts/gerar_perfil_sonda.py capturas/fluke_i30_sn0001 --referencia-externa --resistencia-shunt 0.1 --ganho 10 --plot

# --canal-referencia (2 canais): a corrente real vem do segundo canal
uv run scripts/gerar_perfil_sonda.py capturas/fluke_i30_sn0001 --resistencia-shunt 0.1 --ganho 10 --plot

# Amplitude constante em toda a varredura, informada aqui (capturas sem metadados de amplitude)
uv run scripts/gerar_perfil_sonda.py capturas/fluke_i30_sn0001 --amplitude-referencia 500mVpp --ganho 10 --plot

# A referência vem de um .m do osciloscópio por captura (calibracao_1000Hz_rep1.bin -> calibracao_1000Hz_rep1.m)
uv run scripts/gerar_perfil_sonda.py capturas/fluke_i30_sn0001 --referencia-osciloscopio --ganho 10 --plot

# Cadeia de tensão (--grandeza tensao --ref-externa): a leitura já é a tensão de entrada, não há shunt
uv run scripts/gerar_perfil_sonda.py capturas/cadeia_tensao --referencia-externa --ganho 19.357 --plot
```

Uma coleta de tensão feita antes de `--grandeza tensao` gravou a leitura na coluna `v_shunt_rms_V`; nesse caso some `--resistencia-shunt 1` (com 1 Ω, a "corrente" calculada é a própria tensão). Na cadeia de tensão com **2 canais**, os dois canais estão marcados como tensão: passe `--canal-referencia R --canal-sonda S --resistencia-shunt 1` (o script imprime o comando exato no fim).

* **De onde vem a referência.** Sem nenhuma flag de referência, se as capturas trazem `ref: amp=...` nos metadados, o script usa a amplitude de **cada captura** (modo `amplitude`; o perfil registra `modo_referencia: "amplitude"`). `--amplitude-referencia AMP` (`500mVpp`, `2Arms`; um número puro continua valendo como pico em A) vale para **todas** as capturas e, se os metadados dizem outra coisa, **vence com um aviso**. `--referencia-osciloscopio` usa um arquivo do osciloscópio por captura. `--referencia-externa [CSV]` lê o `referencia_externa.csv` da pasta (ou o arquivo que você indicar) e calcula a corrente de pico de cada ponto como `√2 × V_RMS ÷ R` (coluna `v_shunt_rms_V`; com `corrente_rms_A` ou `tensao_rms_V` o valor já é a grandeza física e não precisa de `--resistencia-shunt`); pontos sem leitura ficam de fora. Com `--resistencia-shunt` sozinho, a corrente vem do segundo canal da captura. As quatro fontes são exclusivas.
* **Amplitude em V ou A.** Em V, a amplitude é a tensão no ponto onde o `--ganho` é aplicado (grandeza física = V × `--ganho`); em A, já é a grandeza física. O ganho do perfil sai como amplitude medida ÷ amplitude injetada, na mesma grandeza.
* **Resumo da resposta.** Ao final, o script imprime e grava no perfil (`calibracao_adc.resposta_conjunto`) o ganho de baixa frequência, a frequência da queda de 3 dB, a inclinação final (um passa-baixa de 2ª ordem cai 12 dB/oitava; o filtro de ~15 kHz do ADS8688 aparece aqui) e quanto a correção amplifica o ruído na maior frequência medida.
* `--ganho` é o fator tensão no pino do ADC → grandeza física (corrente: tipicamente 1 ÷ sensibilidade, sonda de 100 mV/A → `--ganho 10`; tensão: 1 ÷ razão do divisor, ex.: `19.357`). O perfil é **relativo** a ele: use o mesmo valor em produção. O script avisa se o ganho na menor frequência ficar fora de 0,7 a 1,3, o que indica um `--ganho` errado.
* O script **mede** a frequência e a amplitude de cada captura (não confia no nome do arquivo; FFT única da captura inteira, com erro de amplitude < 0,01% em sinais sintéticos), descarta capturas com sinal fraco demais (SNR abaixo de 20 dB) e avisa se alguma repetição divergir mais de 10%.
* `--plot` salva um PNG com a curva obtida.
* Use os mesmos `--formato` e `--ganho` que você usará no `adc_tool.py`; o `adc_tool.py` avisa se forem diferentes. A `--faixa` não precisa ser a mesma: a de cada captura vem do cabeçalho (`--faixa-adc`), e um perfil gerado assim vale para qualquer faixa. Capturas de cabeçalho v1/v2 (sem a faixa) assumem 10.24, e aí o `adc_tool.py` avisa se a `--faixa` de produção for outra.

O resultado é `scripts/sondas/<id>.json`. Para ver o formato de um perfil, abra [`exemplo_sonda.json`](exemplo_sonda.json).

### Referência pelo osciloscópio (arquivo `.m`)

Se você tem o osciloscópio de gigasamples medindo o **mesmo sinal** de cada captura, ele é a referência mais independente: mede o que o gerador de fato entregou, com a planura do gerador incluída.

1. Em cada ponto, salve a forma de onda do osciloscópio (`.m` do MATLAB, ou `.mat`/`.csv`/`.txt`) com o **mesmo nome base da captura**, na mesma pasta: `calibracao_1000Hz_rep1.bin` ↔ `calibracao_1000Hz_rep1.m`. Se preferir outra pasta: `--referencia-osciloscopio PASTA`.
2. Rode `gerar_perfil_sonda.py capturas/<id> --referencia-osciloscopio --ganho G`. A senoide do arquivo é ajustada por mínimos quadrados (amplitude, frequência, fase e nível DC; o método de referência para tons, IEEE 1057) e a amplitude vira a referência daquela captura. Capturas sem arquivo do osciloscópio ficam de fora, com aviso.
3. O formato de um `.m` varia conforme o osciloscópio, então o leitor é tolerante (variáveis `Y = [...]`, vetor de tempo, matriz `[t v]`, escalares como `Tinterval`). Se não tiver certeza do que é a forma de onda, ele **para e lista o que achou**; aí use `--osc-var NOME` (ou `NOME:COLUNA`), `--osc-tempo NOME` e `--osc-fs HZ`. Ponta 10x que o osciloscópio não compensou: `--osc-escala 10`. Se o arquivo já está em A (tensão no shunt ÷ R), use `--osc-unidade A`.

### Conferir o método com o osciloscópio (uma medição basta)

Antes de confiar no perfil, vale checar o conjunto numa captura onde você **sabe a amplitude injetada** e tem o `.m`. O `medir_captura.py` compara as três coisas, na grandeza física do canal:

```bash
# Captura SEM correção: a razão ADC/injetado é o ganho do conjunto naquela frequência
uv run scripts/medir_captura.py senoide.bin --sem-correcao-sonda --amplitude-referencia 500mVpp --osciloscopio senoide.m --ganho 10

# Captura COM o perfil já aplicado (de preferência numa frequência que NÃO entrou na calibração): a razão deve dar ~1
uv run scripts/medir_captura.py senoide.bin --amplitude-referencia 500mVpp --osciloscopio senoide.m --ganho 10
```

A saída traz `vs amplitude injetada` (ADC ÷ injetado), `vs osciloscópio` (ADC ÷ osciloscópio, com a frequência em ppm) e `osciloscópio vs injetada`: se o osciloscópio e a amplitude do gerador divergem mais de ~1%, o gerador não entregou o que foi ajustado (carga de 50 Ω × alta impedância, por exemplo), e o osciloscópio é a referência melhor para o perfil. Sem `--amplitude-referencia`, a amplitude usada é a gravada nos metadados da captura (`ref: amp=...`).

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

## Medir uma captura para o relatório: `medir_captura.py`

O `adc_tool.py` mostra o sinal; o `medir_captura.py` o **mede** e imprime números com unidade, prontos para uma tabela. Serve para caracterizar o ADC (ruído, distorção), conferir a integridade de uma captura e comparar com um osciloscópio.

```bash
uv run scripts/medir_captura.py captura.bin                          # tudo sobre o maior tom
uv run scripts/medir_captura.py curto_*.bin --sem-tom --csv res.csv  # só ruído; uma linha de CSV por canal
uv run scripts/medir_captura.py t.bin --freq 10000 --referencia-rms 1.7654 --referencia-freq 10000.02
```

O que ele mede, por canal:

* **Estatística**: DC, RMS CA, pico a pico, saturação (acima de 0,05% das amostras no fundo de escala, ele avisa).
* **Ruído**: densidade (nV/√Hz, pela mediana do espectro) e ruído RMS em LSB.
* **Tom e distorção**: frequência e amplitude (pico e RMS) do maior pico, THD (até o harmônico `--harmonicos`, padrão 9; os que passam de Nyquist são medidos dobrados e marcados `[alias]`), SINAD, SNR, ENOB (corrigido para um tom abaixo do fundo de escala) e SFDR.
* **Continuidade**: salto de fase do tom entre segmentos, em amostras equivalentes. Uma amostra perdida ou duplicada vale ~1,0; acima de 0,5 é descontinuidade.
* **Acoplamento** (2 canais ou mais): diafonia (quanto do tom do canal mais forte aparece nos outros) e atraso entre canais, contra o esperado (`Δposição ÷ taxa total`).
* **Comparação com instrumento**: `--referencia-rms` (RMS do tom lido no osciloscópio, na unidade do canal) e `--referencia-freq` (Hz, do contador) dão o erro em % e em ppm. `--amplitude-referencia` (a amplitude injetada, com unidade e tipo; padrão: a dos metadados) e `--osciloscopio` (o `.m` do mesmo sinal) comparam o ADC com a amplitude ajustada e com a medida do osciloscópio (veja "Conferir o método com o osciloscópio"). `--fs-pru` analisa com a taxa que a PRU de fato gera (`clock ÷ ticks`, que difere da pedida quando 200 MHz ÷ taxa não é inteiro).

Canais de corrente com sonda registrada no cabeçalho são corrigidos pelo perfil antes das métricas, como no `adc_tool.py`. Nesse caso, ruído, SINAD e ENOB **não** descrevem o ADC: use `--sem-correcao-sonda` para caracterizá-lo. O método (FFT única, janela Kaiser β = 14, vazamento abaixo de −110 dBc) e os limites estão em [`arquitetura_software.md`](arquitetura_software.md) e no docstring de `supraharmonicos/metricas_captura.py`; os testes de laboratório que o usam, em [`roteiro_laboratorio.md`](roteiro_laboratorio.md).

---

## Guardar as capturas sem perdas: `compactar_amostras.py`

Um `.bin` guarda as amostras cruas, 2 bytes cada, sem compressão. O `compactar_amostras.py` junta pastas inteiras (as capturas e o que mais estiver nelas: `.csv`, logs, planos de coleta) num único **pacote** `.zpaq.tar` com cerca de 11 % do tamanho, e só o dá por pronto depois de relê-lo do disco, descomprimir tudo e conferir que cada arquivo volta **idêntico, bit a bit** (SHA-256). Precisa do `zpaq` (`sudo apt install zpaq`; se faltar, o script oferece instalar).

```bash
uv run scripts/compactar_amostras.py Collected_Data                         # → Collected_Data_<data>.zpaq.tar
uv run scripts/compactar_amostras.py listar Collected_Data_<data>.zpaq.tar   # o que tem dentro (instantâneo)
uv run scripts/compactar_amostras.py extrair Collected_Data_<data>.zpaq.tar                    # restaura tudo aqui
uv run scripts/compactar_amostras.py extrair Collected_Data_<data>.zpaq.tar T7c_10min.bin -d /tmp/x   # só um
uv run scripts/compactar_amostras.py verificar Collected_Data_<data>.zpaq.tar  # confere o pacote (de vez em quando)
```

* **O que entra.** Tudo o que houver nas pastas dadas, recursivamente, com o caminho a partir da pasta (como o `tar`): `compactar Collected_Data/lab` guarda `lab/2026-10-19/...`. `--excluir '*.png'` deixa algo de fora; links simbólicos não entram (o script avisa).
* **O que ele usa da máquina.** Um compressor por núcleo, até o que couber em 70 % da memória livre (~800 MB cada; `--memoria GB` e `-j N` mudam isso), com prioridade baixa: o computador continua usável. A tela mostra o progresso e o tempo que falta. O zpaq -m5 é lento e simétrico: os 407 MB do `Collected_Data` levaram 15 min para comprimir e outros 15 para verificar (i7-7700HQ, 8 processos, ~0,07 MB/s cada). Um arquivo grande vira peças de 64 MiB e cada peça ocupa um processo do começo ao fim, então é a maior peça que costuma decidir o tempo total. `--rapido` usa o xz: ~20 vezes mais rápido, pacote ~40 % maior, não precisa do zpaq.
* **Nada fica pela metade.** Até ser verificado, o pacote se chama `*.parcial`; um Ctrl+C ou erro apaga o parcial e os temporários. Se um original mudar durante a compactação, o script para e pede para rodar de novo.
* **Liberar o espaço.** `--remover-originais` apaga os originais depois da verificação, só os que continuam idênticos ao que foi guardado (cada um é conferido de novo), e pede confirmação (`--sim` para não perguntar). Ainda assim, guarde o pacote em **dois lugares** (outro disco, nuvem): é a única cópia dos dados.
* **Extrair.** Os arquivos voltam com a data e as permissões originais, cada um conferido pelo SHA-256 antes de ganhar o nome final. O padrão pode ser o nome do arquivo, um caminho, uma pasta (`lab/capturas`) ou um curinga (`'*100Hz*'`). Um arquivo que já existe no destino é pulado (`--sobrescrever` para substituir).

**Por que zpaq, e o que tem dentro.** Medido nas capturas do projeto: o ruído do ADC limita qualquer compressor sem perdas a ~1,1–2,2 bits por amostra, e o zpaq -m5 (modelagem de contexto) é o que chega mais perto (~10 % do original; 7-Zip e xz ficam em ~14 %, FLAC em ~15 %). Antes de comprimir, as amostras de uma captura multicanal são **desentrelaçadas** (todas do canal 0, depois as do 1...), o que rende ~6 % numa captura de 8 canais. No `Collected_Data` inteiro (407 MB, 129 arquivos), o pacote ficou com **44,9 MB (11,0 %)**; o 7-Zip do script antigo dava 59,4 MB (14,6 %), e o `--max` dele (zpaq -m5 com tudo num arquivo só) 45,1 MB, sem verificação, sem extração de um arquivo isolado e com 4,7 GB de RAM. Ou seja: o zpaq já está perto do limite que o ruído do ADC permite, e o ganho deste script sobre aquele modo é a segurança, não o tamanho. O pacote é um `tar` comum com um `LEIA-ME.txt` que explica como recuperar tudo **sem este programa** (só `tar`, `zpaq` e, para as capturas multicanal, cinco linhas de numpy), um `manifesto.json` legível (caminhos, tamanhos, datas, SHA-256, resumo do cabeçalho de cada captura) e as peças `pecas/*.zpaq`, uma (ou mais, num arquivo grande) por arquivo. Uma peça corrompida estraga só o arquivo dela, e o `verificar` diz qual.

---

## O arquivo `.bin`

Um `.bin` é um **cabeçalho fixo de 1024 bytes** seguido das **amostras brutas** (2 bytes cada, intercaladas por canal: com N canais, a amostra `i` pertence ao canal `lista_canais[i % N]`).

O cabeçalho começa com o texto `SHAN` e termina com um **CRC-32**; se o `adc_tool.py` perceber que o CRC não confere (arquivo truncado ou corrompido), ele avisa. Campos principais:

| Campo | Descrição |
|---|---|
| `versao_cabecalho` | Versão do formato (hoje 4) |
| `timestamp_unix` | Instante da captura (UTC) |
| `frequencia_hz` | Frequência total de amostragem |
| `lista_canais` | Canais capturados, em ordem crescente |
| `grandeza_por_canal`, `sonda_id_por_canal` | Grandeza e sonda de cada canal (versão 2) |
| `faixa_adc_por_canal` | Código da faixa de entrada do ADC de cada canal: 0 = ±10,24 V, 1 = ±5,12 V, 2 = ±2,56 V (versão 3) |
| `amostras_atrasadas`, `buffers_sobrescritos`, `quadros_preambulo_ruim` | Integridade da captura, contada pela PRU (versão 4; veja [Integridade da captura](#integridade-da-captura-e-taxa-máxima)) |
| `atraso_cs_iteracoes` | Atrasos do CS usados na captura (versão 4; `--atraso-cs`) |
| `samples_per_buffer`, `bytes_por_amostra` | Geometria dos blocos |
| `blocos_gravados`, `total_amostras_gravadas` | Totais reais, preenchidos ao final da captura |
| `titulo`, `descricao` | Texto livre (`-t`, até 63 bytes; `-d`, até 255 bytes). Convenção para calibração: um trecho `ref: f=1000Hz amp=500mVpp` na descrição registra a frequência e a amplitude injetadas, e o `gerar_perfil_sonda.py` o lê; texto livre antes ou depois é ignorado |
| `header_crc32` | Detecta corrupção do cabeçalho |

Arquivos feitos antes do cabeçalho existir continuam sendo lidos (veja [Capturas sem cabeçalho](#capturas-sem-cabeçalho-arquivos-antigos)), e os de versão 1 a 3 do cabeçalho também. A tabela completa, com os deslocamentos de cada campo, está em [`contexto_projeto.md`](contexto_projeto.md) (seção `formato_bin_v2`, que descreve também a v3 e a v4).

**Capturas feitas antes de out/2026** (cabeçalho versão 3 ou anterior) têm um salto de ~7 µs a cada bloco (~0,7 amostra a 100 kS/s), um defeito do firmware antigo já corrigido. Para análise espectral de um bloco só, ele não aparece; em análises de fase ou de continuidade que atravessam blocos, sim. O `medir_captura.py` o aponta (DESCONTINUIDADE "numa troca de buffer da PRU").

---

## Utilitários

| Script | Onde roda | O que faz |
|---|---|---|
| `scripts/set_date.sh` | Computador | Copia a data e hora do computador para a BeagleBone via SSH (como instante absoluto em UTC, então vale qualquer que seja o fuso dela). Padrão: `debian@192.168.6.2`; troque com `BBB_USER` e `BBB_IP`. **Nenhuma senha fica no arquivo:** use chave SSH (`ssh-copy-id debian@192.168.6.2`) ou deixe o `ssh`/`sudo` pedirem a senha no terminal. Se preferir não digitar, exporte `SSHPASS` (e tenha o `sshpass` instalado) |
| `scripts/compactar_amostras.py` | Computador | Arquiva pastas de captura sem perdas num pacote `.zpaq.tar` (~11 % do tamanho), conferido bit a bit; também `listar`, `extrair` e `verificar`. Veja [Guardar as capturas sem perdas](#guardar-as-capturas-sem-perdas-compactar_amostraspy) |
| `relatorio/gerar_figuras.py` | Computador | Gera as figuras do relatório (PDF vetorial, já no tamanho final, com o texto composto pelo LaTeX) e um `.tex` com os números citados (macros siunitx). `uv run relatorio/gerar_figuras.py` gera todas; `--listar`, `--png` (prévia), `--formato artigo --idioma en` (coluna de artigo, em inglês), `--saida PASTA` (ex.: a pasta do projeto LaTeX). Inclua no documento sem `width=`, para as fontes baterem com as do texto |

---

## Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `uv: command not found` | `uv` não instalado | Instale o [`uv`](https://docs.astral.sh/uv/) |
| A janela do gráfico não abre | Computador sem tela (SSH, servidor) | Use `-o grafico.png` para salvar em arquivo |
| `-f/--frequencia é obrigatório no modo de plotagem` | Arquivo sem cabeçalho (captura antiga) | Informe `-f` (frequência total) e `--canais` |
| Aviso "CRC-32 do cabeçalho NÃO confere" | Cópia truncada ou arquivo corrompido | Copie o arquivo de novo e compare o tamanho. Os campos mostrados podem estar errados |
| Aviso "canal N é de corrente mas não tem sonda/perfil resolvido" | A captura não registrou a sonda | Use `--sonda-perfil N:ARQUIVO.json` (ou refaça a captura com `--sonda`) |
| `compactar_amostras.py`: "o zpaq não está instalado" | Falta o compressor | `sudo apt install zpaq`, ou `--rapido` (xz, pacote maior) |
| `ler_adc`: "amostra(s) tomada(s) depois do instante previsto" | Taxa acima do que a PRU alcança (~140 kS/s) | Use até 100 kS/s; a taxa real foi menor que a gravada |
| `ler_adc` sai com código 3, "buffer(s) sobrescrito(s)" | O ARM não gravou um bloco a tempo: amostras perdidas | Refaça; verifique o cartão SD e o que mais está rodando na BeagleBone |
| `medir_captura`: DESCONTINUIDADE "numa troca de buffer da PRU" | Captura feita com o firmware anterior a out/2026 | Recompile o firmware (`./setup.sh`) e capture de novo |
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
| `calibrar_sonda.sh`: "praticamente sem sinal" | Gerador desligado, shunt/sonda mal ligados ou canal errado | Confira a bancada e o número de `--canal-sonda` (e `--canal-referencia`, se usou) |
| `calibrar_sonda.sh`: "sinal fraco" nas frequências altas | Filtro passa-baixa de ~15 kHz embutido no ADS8688 | Esperado. Aumente a amplitude no pino do ADC; aceite o ponto (`C`) se ainda tiver ≥ 0,2% da escala |
| `calibrar_sonda.sh` recusa o plano: "frequência máxima ... Nyquist" | `--freq-max` ≥ 98% da Nyquist efetiva (taxa ÷ 2 com 1 canal, ÷ 4 com 2) | Aumente `--taxa` ou use 1 canal; para 150 kHz, 400 kHz e 1 canal |
| `calibrar_sonda.sh`/`gerar_perfil_sonda.py`: amplitude "sem tipo" ou "sem unidade" | `500mV`, `0.5` ou `2rms`: faltou dizer se é pico a pico, pico ou eficaz, ou se é V ou A | Escreva número + unidade + tipo: `500mVpp`, `250mVpk`, `176.8mVrms`, `2Arms` |
| `gerar_perfil_sonda.py`: "informe a referência da grandeza injetada" ou "sem amplitude conhecida" | As capturas não trazem `ref: amp=...` nos metadados e nenhuma flag de referência foi dada | Use `--amplitude-referencia AMP` (mesma amplitude em todas), `--referencia-osciloscopio`, `--referencia-externa` ou `--resistencia-shunt`; ou refaça a coleta com `--amplitude` |
| `gerar_perfil_sonda.py`: "ADC/osciloscópio" ou "osciloscópio vs injetada" diverge mais de ~1% | O gerador não entregou a amplitude ajustada (carga de 50 Ω × alta impedância, planura em frequência alta) | Use o osciloscópio como referência (`--referencia-osciloscopio`) ou corrija o ajuste do gerador |
| `gerar_perfil_sonda.py`: ganho na menor frequência fora de [0,7; 1,3] | `--ganho` diferente de 1 ÷ sensibilidade da sonda | Confira o `--ganho` (sonda de 100 mV/A → 10) e o `--resistencia-shunt` |

Se o problema não está aqui, a referência técnica completa está em [`contexto_projeto.md`](contexto_projeto.md).
