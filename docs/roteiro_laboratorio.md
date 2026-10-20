# Roteiro de laboratório

Lista de testes para validar o SH-Analyzer **de ponta a ponta** (ADC, firmware/PRU, divisor de tensão, sonda de corrente e software), com o sinal a injetar em cada um, os comandos exatos, o que anotar no osciloscópio e o que esperar. Feito para sair do laboratório com **dados que entram direto no relatório**.

Pré-requisito: [`guia_de_uso.md`](guia_de_uso.md) (capturar e analisar). Este roteiro supõe que você já sabe rodar `ler_adc` e `adc_tool.py`.

**Premissas desta versão** (todas conferidas nos testes indicados; se alguma falhar, o roteiro diz o que trocar):

* **Taxa de trabalho: no máximo 100 kS/s no total.** O hardware sustenta ~130 kS/s e o ADC aceitaria 500 kS/s; taxas acima de 100 kS/s só aparecem para **documentar o limite** (T1, T4, T7e).
* **Canal de tensão (canal 1 do ADC) = divisor resistivo de 5 resistores ligado direto ao ADS8688**, sem sonda. "Sonda de tensão", neste roteiro, é o **divisor + o filtro de ~15 kHz do ADC**, e o perfil dela corrige os dois.
* **Canal de corrente (canal 0 do ADC) = SCT013 100A:50mA + resistor de 0,12 Ω + 2 resistores em série + ADC**, **com o capacitor de filtro removido** (o capacitor existente é um passa-baixa de frequência de corte baixíssima, incompatível com supraharmônicos).
* **Faixa de entrada do ADC escolhida por canal** (`--faixa-adc`): **canal de tensão em ±10,24 V** (o padrão, `20.48`: o divisor já usa 91% dela com 127 V RMS) e **canal de corrente em ±2,56 V** (`--faixa-adc 0:5.12`: o sinal tem dezenas de µV e a faixa menor reduz o ruído em volts). O firmware escreve a faixa no ADC e a registra no cabeçalho, e as ferramentas de análise a leem de lá (nada de `--faixa` nos comandos). **A escala em si (referência de 4,096 V, mapeamento do código) é confirmada no T0, passo 6**; veja o fato 3.

**Índice**

1. [Antes de ir: o que o datasheet e o código já dizem](#antes-de-ir-o-que-o-datasheet-e-o-código-já-dizem)
2. [Equipamentos, segurança e boas práticas](#equipamentos-segurança-e-boas-práticas)
3. [Convenções e a ferramenta `medir_captura.py`](#convenções-e-a-ferramenta-medir_capturapy)
4. [Plano: ordem, tempo e prioridade](#plano-ordem-tempo-e-prioridade)
5. [Os testes](#os-testes): [T0](#t0-preparação-e-sanidade) · [T1](#t1-piso-de-ruído-entrada-em-curto) · [T2](#t2-tensão-contínua-ganho-offset-e-linearidade) · [T3](#t3-resposta-em-frequência-da-cadeia-de-tensão) · [T4](#t4-frequência-de-amostragem-real) · [T5](#t5-distorção-e-faixa-dinâmica) · [T6](#t6-vários-canais-diafonia-e-atraso) · [T7](#t7-integridade-e-limite-de-taxa) · [T8](#t8-aliasing) · [T9](#t9-sinais-de-espectro-conhecido) · [T10](#t10-perfil-da-sonda-de-corrente) · [T11](#t11-ponta-a-ponta)
6. [Dados e figuras para o relatório](#dados-e-figuras-para-o-relatório)
7. [Critérios de aceitação](#critérios-de-aceitação)
8. [Problemas de bancada](#problemas-de-bancada)
9. [Checklist ao sair do laboratório](#checklist-ao-sair-do-laboratório)

---

## Antes de ir: o que o datasheet e o código já dizem

Oito fatos mudam o planejamento. Todos devem ser **confirmados** nos testes indicados.

**1. O teto de trabalho é 100 kS/s no total, e a Nyquist de cada canal é a taxa ÷ nº de canais ÷ 2.** O ADS8688 aceita 500 kS/s, mas o projeto hoje só sustenta ~130 kS/s (o gargalo ainda não foi isolado: [T7e](#t7e-onde-está-o-limite-de-taxa)); trabalha-se em **100 kS/s**, que também é uma taxa exata da PRU (2000 ticks). Com **1 canal**, Nyquist = **50 kHz**; com **2 canais**, 50 kS/s cada, Nyquist = **25 kHz**. Consequências:

* o perfil e as medições valem até **~45 kHz** (90% de Nyquist), e a calibração usa `--freq-max 45k`;
* a banda de supraharmônicos (2 a 150 kHz) fica **só em parte coberta**. Cobrir até 150 kHz exigiria pelo menos 300 kS/s: **fica como sugestão de melhoria**, dependente de achar o gargalo (T7e);
* componentes entre 50 e 150 kHz **dobram** para dentro de 0 a 50 kHz e não dá para separá-las depois ([T8](#t8-aliasing));
* acima de 100 kS/s use taxas só nos testes que pedem (T1, T4, T7), para mostrar no relatório o limite real e o que acontece além dele.

**2. O ADS8688 tem um filtro passa-baixa de 2ª ordem em cada canal, com corte de ~15 kHz.** Está no datasheet do repositório ([`Datasheets/ads8688.pdf`](Datasheets/ads8688.pdf), seção 8.3.5 e Figura 55; banda de pequenos sinais de **−3 dB em 15 kHz** e de −0,1 dB em 2,5 kHz). Não dá para desligar. Estimativa grosseira, entre um filtro de dois polos reais e um Butterworth de 2ª ordem:

| Frequência | 10 kHz | 15 kHz | 30 kHz | 45 kHz | 60 kHz | 90 kHz | 130 kHz |
|---|---|---|---|---|---|---|---|
| Atenuação estimada | −1 a −2 dB | −3 dB | −8 a −12 dB | −14 a −19 dB | −18 a −24 dB | −24 a −31 dB | −30 a −38 dB |

Os números reais saem do **T3** (tensão) e do **T10** (corrente). Daí vêm três decisões: (a) o perfil precisa cobrir o **conjunto** (divisor ou sonda, frontend e ADC) até a maior frequência de interesse; (b) a correção amplifica o ruído na mesma proporção (cerca de +14 a +19 dB perto de 45 kHz), o que limita a menor amplitude detectável ali; (c) o anti-aliasing é fraco: componentes de 60 a 130 kHz só caem de 18 a 38 dB e **dobram para dentro da banda** (T8).

**3. A faixa de entrada do ADC é escolhida pelo firmware (`--faixa-adc`), e diminuí-la melhora a resolução.** O `ler_adc --faixa-adc canal:volts` faz a PRU gravar o código de faixa de cada canal habilitado nos registradores `RANGE_SELn` do ADS8688 (05h a 0Ch; seção 8.3.4 do datasheet) **a cada captura** (o ADC guarda o valor entre capturas), e o cabeçalho (versão 3) registra o que foi aplicado. O `adc_tool.py`, o `medir_captura.py` e o `gerar_perfil_sonda.py` convertem código em volts com a faixa **do cabeçalho**, canal a canal; só digite `--faixa` para sobrepor (e eles avisam se divergir). Faixas bipolares aceitas, com a referência interna de 4,096 V (as unipolares do ADS8688 **não** são suportadas):

| `--faixa-adc` (fundo de escala total) | Faixa | 1 LSB | Ruído no pino (SNR típico do datasheet, tom em −0,5 dBFS) |
|---|---|---|---|
| `20.48` (padrão) | ±10,24 V (±2,5 × VREF) | 312,5 µV | ~172 µV RMS (92 dB) |
| `10.24` | ±5,12 V (±1,25 × VREF) | 156,3 µV | ~96 µV RMS (91 dB) |
| `5.12` | ±2,56 V (±0,625 × VREF) | 78,1 µV | ~61 µV RMS (89 dB) |

Pelo datasheet, a cada passo o LSB cai exatamente pela metade, mas o ruído em volts cai menos (~1,8× e ~2,8× contra a faixa padrão): em LSB, o ruído **sobe** (0,55 para ~0,8 LSB RMS). Ou seja, sim: faixa menor melhora a medida de sinais pequenos, até onde o sinal cabe. **Quem decide a faixa é o pico do sinal no pino**, com margem:

* **Canal 1 (tensão): fica em ±10,24 V.** 127 V RMS dão 9,28 V de pico no pino (91% da faixa) e +10% de tensão de rede (140 V RMS) já chega ao limite (±10,2 V). Não há como reduzir: ±5,12 V não comporta nem 127 V RMS.
* **Canal 0 (corrente): ±2,56 V** (`--faixa-adc 0:5.12`). O sinal esperado é de dezenas de µV a poucos mV (fato 5): sobra mais de 99% da faixa, e ±2,56 V é a menor do ADC.

**Hipóteses a confirmar no [T0](#t0-preparação-e-sanidade), passo 6 (e no T1):** (a) a referência é a interna de 4,096 V e o código sai em binário deslocado (o que as ferramentas assumem), (b) a escrita em `RANGE_SELn` pega em cada canal e a conversão vale desde a primeira amostra, (c) o ruído por faixa segue o datasheet. Capturas **antigas** (cabeçalho v1/v2, sem registro da faixa) são lidas com `--faixa 10.24`: se o ADC estava mesmo na faixa de reset de ±10,24 V, essas capturas saíram com **a metade do valor real**; reconverta-as com `--faixa 20.48`.

**4. Cadeia de tensão: o divisor de 5 resistores.** Os resistores medidos (R1 a R5, em série; o ADC mede R5):

| Item | Valor |
|---|---|
| R1, R2, R3, R4, R5 | 8,212 kΩ, 8,190 kΩ, 8,208 kΩ, 8,230 kΩ, **1,7890 kΩ** |
| Soma | 34,629 kΩ |
| Razão nominal R5 ÷ soma | **0,051662** (÷ 19,357; −25,7 dB) |
| Com a carga de 1 MΩ do ADC (0,85 a 1,15 MΩ) | 0,05157 (÷ 19,39), **−0,17%** (−0,15 a −0,20%) |
| Impedância vista pelo ADC | 1,70 kΩ (o datasheet pede menos de 30 kΩ para a proteção de ±20 V valer) |
| Gerador SDG1032X, 20 Vpp em High-Z (10 V de pico) | 0,517 V de pico no pino: **5% da faixa de ±10,24 V** (−26 dBFS) |
| Fundo de escala de ±10,24 V no pino | ±198 V de pico na entrada (**140 V RMS**) |
| Rede 127 V RMS (180 V de pico) | 9,28 V no pino: 91% da faixa. **Cabe** (com +10% de rede, ~10,2 V: no limite) |
| Rede 220 V RMS (311 V de pico) | 16,1 V no pino: 157% da faixa. **Satura** (o máximo absoluto de ±20 V não é ultrapassado) |
| 1 LSB, na entrada do divisor | 6,05 mV |
| Ruído do ADC (0,55 a 0,7 LSB RMS), na entrada | 3,3 a 4,2 mV RMS em banda larga |

**Não reduza a faixa do canal de tensão:** com `--faixa-adc 1:10.24` (±5,12 V) todas as linhas de "faixa" caem pela metade, o fundo de escala passa a ±99 V de pico (70 V RMS) e **nem 127 V RMS cabe**. O `--ganho` nominal do canal de tensão é **19,357** (o perfil sai relativo a ele; a carga de 1 MΩ aparece como ganho de baixa frequência ~0,998).

**5. Cadeia de corrente: o SCT013 sobre 0,12 Ω rende pouquíssimo sinal.** Premissa (confirme no T10-0): o SCT013 100A:50mA é um transformador de corrente de 2000:1 e o resistor de 0,12 Ω da placa é a carga (burden) dele. Então:

| Item | Valor |
|---|---|
| Sensibilidade nominal | 0,12 Ω × 0,5 mA/A = **60 µV por ampère** de corrente primária (por espira) |
| `--ganho` nominal | **16 667** A/V (1 ÷ 60 µV/A) |
| Resistores em série (1,79 kΩ + 1,7929 kΩ) sobre 1 MΩ do ADC | −0,36% (aparece no perfil) |
| 1 LSB | ±10,24 V: 312,5 µV = 5,2 A com 1 espira (0,52 A com 10). **±2,56 V (`--faixa-adc 0:5.12`, a deste roteiro): 78,1 µV = 1,3 A** com 1 espira (0,13 A com 10) |
| Ruído do ADC (datasheet) | ±10,24 V: 170 a 220 µV RMS = ~3 a 4 A RMS equivalentes em banda larga (0 a 50 kHz), ~5 mA por bin de 0,1 Hz numa captura de 10 s. **±2,56 V: ~61 µV RMS = ~1 A RMS** (banda larga), **~1,8 mA por bin** (≈ 9 dB melhor) |
| Corrente máxima do gerador (20 Vpp High-Z, 50 Ω de saída) | 200 mA de pico sem carga; **~116 mA RMS** com o resistor de 10,92 Ω |
| 116 mA RMS com 10 espiras | 1,16 A·espira = 70 µV RMS = **0,9 LSB** em ±2,56 V (0,22 LSB em ±10,24 V), ~55 a 57 dB acima do ruído por bin em ±2,56 V (46 a 48 dB em ±10,24 V; captura de 10 s); em 40 kHz o filtro derruba ~17 dB e sobram ~38 a 40 dB (29 a 31 dB em ±10,24 V) |
| Rede 127 V sobre os dois resistores de 22,12 Ω em série (44,24 Ω) | 2,87 A RMS, 172 µV RMS (2,2 LSB em ±2,56 V): serve para o ponto de **60 Hz** |

Ou seja: o canal funciona, mas só por causa do **ganho de processamento da FFT** (cada bin vê uma fração minúscula do ruído); um tom tem que ter de dezenas de µV para cima. Por isso o T10 usa **várias espiras no SCT013**, capturas longas e a corrente de referência medida pela ponta TCP0030A. O pior sinal detectável é uma propriedade do projeto (para o relatório e para uma melhoria futura: resistor de carga maior ou ganho antes do ADC; a faixa de ±2,56 V, a menor do ADC, **já está em uso**). **O capacitor** do filtro, que será removido, tem R = 1,79 kΩ + 1,7929 kΩ = 3,583 kΩ: fc = 1 ÷ (2π · 3,583 kΩ · C) é 705 Hz para 63 nF, 7 Hz para 6,3 µF e 0,7 Hz para 63 µF. **Anote o valor medido e fotografe a placa antes de tirá-lo.**

**6. A taxa de amostragem real pode diferir da pedida.** O `ler_adc` calcula `ticks = 200 MHz ÷ taxa` com divisão **inteira**. Taxas que dividem 200 MHz exatamente saem exatas; as outras não:

| Taxa pedida | Ticks | Taxa gerada | Diferença |
|---|---|---|---|
| 50 000 | 4000 | 50 000 | 0 |
| **100 000** | 2000 | 100 000 | 0 |
| 102 400 | 1953 | 102 406,55 | **+64 ppm** |
| 110 000 | 1818 | 110 011,0 | +100 ppm |
| 125 000 | 1600 | 125 000 | 0 |
| 130 000 | 1538 | 130 039,0 | +300 ppm |
| 150 000 | 1333 | 150 037,5 | +250 ppm |
| 200 000 | 1000 | 200 000 | 0 |
| 500 000 | 400 | 500 000 | 0 |

Isso desloca todas as frequências medidas pela mesma razão (um tom de 10 kHz aparece em 9 999,36 Hz a 102,4 kS/s). Além disso, o relógio de 200 MHz da PRU vem do cristal da BeagleBone, que tem erro de dezenas de ppm. É uma hipótese a confirmar no [T4](#t4-frequência-de-amostragem-real). **Recomendação: use 100 kS/s** (ou 50 kS/s) nos testes de exatidão.

**7. Os instrumentos têm incerteza própria (cite no relatório).** O osciloscópio **MSO46** converte com 8 bits a 6,25 GS/s, 12 bits a 3,125 GS/s e até 16 bits em modo Hi-Res a 125 MS/s, com exatidão de ganho DC de **±1%** (±1,5% em ganho variável; o datasheet da série 4 ainda deixa 0,1%/°C acima de 30 °C). Para sinais de até 100 kHz use taxa de amostragem baixa (≤ 125 MS/s), Hi-Res ou média, e limite de banda. A ponta de corrente **TCP0030A** tem exatidão garantida de ±3% (típica ±1%) de DC a 60 Hz e ±1,5% de 60 Hz a 5 kHz na faixa de 5 A; **acima de 5 kHz não há exatidão especificada** (banda nominal de 120 MHz), então ela é a melhor referência disponível, não uma verdade absoluta. O multímetro **Fluke 289** é a melhor referência de tensão AC em 60 Hz a 1 kHz (confira a tabela de exatidão do manual: piora acima disso); o CEM DT-989 não tem banda conhecida (não use para AC acima de 60 Hz). Orçamento de incerteza do relatório: algo entre 1 e 3% para a referência.

**8. Um gerador de funções comum não serve para medir THD de um ADC de 16 bits.** O ADS8688 tem THD de −102 dB (típico, 1 kHz); geradores comuns têm −50 a −70 dBc, e o osciloscópio não enxerga abaixo de uns −60 dBc. O T5 explica o que fazer (filtro passa-faixa no gerador, ou fonte de baixa distorção).

> **Fora do roteiro:** o `Datasheets/LV25-P.PDF` do repositório **não se aplica a esta placa**: o canal de tensão é um divisor resistivo, e não o transdutor LV 25-P.

---

## Equipamentos, segurança e boas práticas

### O que levar

Equipamentos do seu levantamento (`Anotações - Teste de bancada.md`), com o que importa de cada um para o roteiro:

| Item | Para quê |
|---|---|
| **Gerador Siglent SDG1032X** (30 MHz, 150 MSa/s, 14 bits, 2 canais; **20 Vpp em High-Z e 10 Vpp em 50 Ω**; offset de ±10 V em High-Z; os 2 canais podem ser combinados) | Todos os tons. Ajuste a carga para **High-Z** com o divisor de tensão |
| **Osciloscópio Tektronix MSO46** (500 MHz, 6,25 GS/s, 6 canais) | Referência de tensão e de corrente, frequência (contador), FFT, formas de onda (`.m`/`.mat`) e o período do CS da PRU (T7e) |
| **Ponta de tensão TPP0500B** (500 MHz, 10 MΩ ∥ 3,9 pF, 300 V CAT II) | Tensão no nó de entrada do divisor |
| **Ponta de corrente TCP0030A** (5 A ou 30 A, DC a 120 MHz) | **Referência de corrente** do T10 (faixa de 5 A) |
| **Multímetros Fluke 289 e CEM DT-989** (true RMS) | DC (T2) e AC de 60 Hz a 1 kHz (Fluke); o CEM só para DC e 60 Hz |
| **SCT013 100A:50mA** (YHDC) | Sonda de corrente sob teste |
| **2 resistores de 22,12 Ω, 400 W, 93 V**, com derivação central (10,92 Ω) | Carga de corrente do T10 e da rede (T10 ponto de 60 Hz, T11c). **Corrente máxima de 4,2 A cada** (93 V ÷ 22,12 Ω) |
| Terminadores BNC de 50 Ω, curto BNC, conectores T de BNC | T1, T6 |
| Fio flexível de pelo menos 1,5 mm² e fita para fixar as espiras | T10: 10 a 20 voltas pela garra do SCT013 (janela de ~13 mm: confira quantas cabem) |
| Medidor LCR (opcional) | Capacitor removido, indutância dos resistores de potência (fio enrolado: indutivos em alta frequência) |
| Transformador de isolamento 1:1 (e, de preferência, autotransformador) | **Só** para o T2c e o T11c com a rede |
| Notebook com este repositório e `uv`; cabo USB/Ethernet para a BeagleBone | Análise |

### Segurança

* **Limite do ADC.** O máximo absoluto na entrada é de ±20 V (com a placa alimentada e fonte de baixa impedância) e **apenas ±11 V se o ADC estiver sem alimentação**. Nunca injete sinal com a placa desligada. Comece sempre com amplitude mínima no gerador e suba. **Rede de 220 V não cabe** no divisor (fato 4: satura em 157% da faixa), e uma faixa menor que ±10,24 V no canal de tensão (`--faixa-adc 1:10.24`) tira até os 127 V. A faixa escolhida muda só o ponto de saturação: o limite de ±20 V nos pinos é o mesmo em todas.
* **Rede elétrica.** Só nas etapas marcadas (T2c, T11c), com supervisão do orientador ou do técnico. A BeagleBone, o notebook e o osciloscópio estão ligados à terra: a garra de terra da ponta **em curto com a terra** de qualquer ponto da rede danifica o equipamento e machuca. Use transformador de isolamento, ponta diferencial ou osciloscópio isolado. O isolamento galvânico do frontend (DAQ_Module) protege o ADC, não o osciloscópio.
* **Resistores de potência.** 400 W viram calor: deixe longe de fios e de plástico, não encoste, e respeite 93 V e 4,2 A. Com o gerador (≤ 0,2 A) não há risco; na rede, sim.
* **SCT013.** É um transformador de corrente: **nunca deixe o secundário aberto** com corrente no primário (tensão perigosa e saturação). Mantenha o resistor de 0,12 Ω ligado sempre; só mexa na placa com o primário desenergizado.
* **TCP0030A.** Não passe mais que 30 A RMS (e 50 A de pico) por ela; **desmagnetize (botão DEGAUSS) e faça o zero** a cada ligação, com o condutor fora da garra.
* Desligue a saída do gerador antes de trocar ligações e descarregue capacitores antes de mexer na placa (inclusive antes de remover o capacitor do filtro).

### Boas práticas de medição

* **Impedância do gerador.** A saída é de 50 Ω. A entrada do divisor é de 34,6 kΩ: ajuste o gerador para carga **"High-Z"** (senão o painel erra por um fator 2: com "50 Ω" configurado e carga real de alta impedância, sai o **dobro** do valor do painel). Mesmo em High-Z a tensão real fica 0,14% abaixo do painel (50 Ω ÷ 34,6 kΩ). O que vale é a leitura do osciloscópio ou do multímetro **no mesmo nó**.
* **Mesmo nó.** Ponta do osciloscópio e entrada do divisor no mesmo ponto (conector T de BNC). Cabos curtos (menos de 1 m) até 50 kHz não têm problema de linha de transmissão. Não meça direto sobre R5 (nó do ADC) com a ponta de 10 MΩ ∥ 3,9 pF: a ponta pesa 0,4% a 100 kHz sobre 1,7 kΩ; meça na entrada do divisor, onde a fonte é de 50 Ω.
* **Terra.** Um só ponto de terra (gerador, ponta e retorno do divisor). Se aparecer zumbido de 60 Hz, veja [Problemas de bancada](#problemas-de-bancada).
* **Aquecimento.** Ligue tudo 30 minutos antes (gerador, osciloscópio, ponta TCP0030A, BeagleBone e frontend). Deriva térmica entra no resultado.
* **Osciloscópio.** Ponta compensada (ajuste no sinal de calibração); acoplamento DC; **limite de banda em 20 MHz ou menos** (os sinais têm no máximo 50 kHz; reduz o ruído); sinal ocupando 60% ou mais da tela; use a medida de **RMS em número inteiro de ciclos** (≥ 8 ciclos) com média de 16 aquisições ou mais, ou modo Hi-Res. Anote a escala vertical usada. Para gravar a forma de onda (`.m`): pelo menos 10 ciclos do tom e 20 amostras por ciclo.
* **Frequência.** Leia a frequência no contador do osciloscópio (o SDG1032X também tem um contador de frequência de entrada) e use esse valor, não o do painel do gerador. Se o gerador tiver entrada de referência de 10 MHz, ligue-o à saída de referência do osciloscópio.
* **Caderno de laboratório.** Para cada teste: data, hora, temperatura, ajustes do gerador e do osciloscópio, comprimento dos cabos, qual canal, qual taxa. O título gravado na captura (`-t`) já guarda o essencial.

---

## Convenções e a ferramenta `medir_captura.py`

### Nomes e pastas

* **Na BeagleBone** (`firmware/`): `T<n><letra>_<descrição>.bin`, por exemplo `T5a_1k_m40dBFS.bin`, e título curto no cabeçalho com `-t "T5a 1kHz -40dBFS"` (até 63 bytes).
* **No computador:** copie tudo para `lab/AAAA-MM-DD/`. Todos os resultados numéricos vão para **um único** `lab/AAAA-MM-DD/resultados.csv`.
* **Canais desta bancada, em todos os testes: canal 1 = tensão (divisor) e canal 0 = corrente (SCT013).** Os comandos abaixo já usam essa atribuição (para mudá-la, troque o número do canal no `ler_adc`, em `--faixa-adc`, `--grandeza`, `--sonda` e `--canal-sonda`). Nos comandos de captura, o argumento depois da taxa é a lista de canais. **Com os dois canais, o ADS8688 varre sempre em ordem crescente: o canal 0 (corrente) é convertido primeiro e o canal 1 (tensão) 1/taxa total depois** (10 µs a 100 kS/s; veja o T6b).
* **Variáveis do roteiro (fish, no computador).** Defina uma vez por sessão e use nos comandos de análise; assim, se o T2 ou o T10-0 mudarem um ganho, você troca só uma linha:

```fish
set GV 19.357      # --ganho do canal de tensão: 1 ÷ razão do divisor (34,629 kΩ ÷ 1,789 kΩ)
set GI 16667       # --ganho do canal de corrente: 1 ÷ 60 µV/A (SCT013 100A:50mA sobre 0,12 Ω)
```

* **Faixa do ADC nos comandos.** Na **captura** (BeagleBone), o canal de tensão usa o padrão (nada a passar, ±10,24 V) e o de corrente leva `--faixa-adc 0:5.12` (±2,56 V). Na **análise** (computador), **não** se passa `--faixa`: ela vem do cabeçalho de cada captura (a primeira linha da saída mostra `canal 0: ±10.24 V` e `canal 1: ±2.56 V`). Se a captura for de um `ler_adc` antigo (sem faixa no cabeçalho), as ferramentas usam 10.24 e avisam.

* **Forma de onda do osciloscópio (`.m`).** Salve o arquivo de cada ponto com o **mesmo nome base da captura** (`calibracao_1000Hz_rep1.m` ao lado de `calibracao_1000Hz_rep1.bin`); o `gerar_perfil_sonda.py --referencia-osciloscopio` e o `medir_captura.py --osciloscopio` o encontram sozinhos. Anote o ajuste vertical e se a ponta é 10x (`--osc-escala`). Nesta versão, a variável salva pelo osciloscópio deve estar na **grandeza física** (tensão no nó de entrada do divisor; corrente da TCP0030A em A) e use `--osc-unidade A` (o nome é histórico: "A" aqui quer dizer "já está na grandeza física do canal, não multiplique pelo `--ganho`").
* **"A sonda" = o conjunto.** Neste projeto, "sonda" e "perfil da sonda" designam o conjunto medido de ponta a ponta: no canal de tensão, o **divisor + o ADS8688**; no de corrente, o **SCT013 + resistores + o ADS8688**. A frequência de corte do filtro do ADC não precisa ser conhecida: aparece na curva medida.
* **Grandeza no perfil de tensão.** Com `--grandeza tensao`, o `calibrar_sonda.sh` grava `--grandeza <canal>:tensao` nas capturas do divisor, como em produção (`--grandeza 1:tensao --sonda 1:cadeia_tensao`), e os textos dele falam da tensão na entrada da cadeia em vez de "shunt". Coletas feitas antes dessa opção ficaram marcadas como `corrente`: é só um rótulo, que o gerador de perfil não usa nos modos de 1 canal.
* **0 dBFS = metade do fundo de escala total** no pino do ADC: 10,24 V no canal 1 (tensão, ±10,24 V; 2,56 V no canal 0, corrente, em ±2,56 V). Amplitudes de pico no pino do canal 1: −0,5 dBFS = 9,67 V; −6 dBFS = 5,13 V; −20 dBFS = 1,024 V; −40 dBFS = 102 mV; −60 dBFS = 10,2 mV. **Pelo divisor** o gerador só chega a 0,517 V de pico (−26 dBFS): a tabela de gerador do [T5](#t5-distorção-e-faixa-dinâmica) já converte.

Para copiar as capturas:

```bash
scp 'debian@<ip-da-beaglebone>:caminho/firmware/T*.bin' lab/2026-10-20/
```

### `medir_captura.py` em um minuto

Mede uma ou mais capturas e imprime **números com unidade**, prontos para uma tabela:

```fish
uv run scripts/medir_captura.py lab/2026-10-20/T5a_*.bin --csv lab/2026-10-20/resultados.csv
```

Como o `adc_tool.py`, ele lê frequência, canais, sonda **e a faixa do ADC de cada canal** do cabeçalho (e aceita `-f`, `--canais`, `--faixa`, `--ganho`, `--offset`, `--formato`). **Atenção:** o cabeçalho **não** guarda o ganho; passe `--ganho $GV` no canal de tensão e `--ganho $GI` no de corrente, senão ele usa 1 (numa captura com os dois canais, `--ganho $GI,$GV`: um valor por canal, na ordem crescente dos canais, 0 e 1). `--faixa` só serve para sobrepor a do cabeçalho (ele avisa se divergir) ou para capturas antigas (v1/v2), que assumem 10.24. O que mede, por canal:

| Grandeza | Significado | Onde aparece |
|---|---|---|
| DC, RMS CA, pico a pico, saturação | Estatística básica. Saturação acima de 0,05% das amostras = captura inválida (aviso) | `media`, `rms_ca`, `pico_a_pico`, `saturacao_pct` |
| Densidade de ruído, ruído em LSB | Piso de ruído (mediana do espectro). 1 LSB = faixa total × ganho ÷ 65536 (a faixa de cada canal) | `densidade_ruido_por_rthz`, `ruido_rms_lsb` |
| Tom | Frequência e amplitude (pico e RMS) do maior pico espectral, em FFT com janela Kaiser sobre a captura inteira | `freq_tom_hz`, `amplitude_pico`, `amplitude_rms` |
| Harmônicos e THD | Soma das potências dos harmônicos (até `--harmonicos`, padrão 9) sobre a fundamental, em dB. Harmônicos acima de Nyquist são medidos na frequência **dobrada** (marcados `[alias]`) | `thd_db`, `thd_pct` |
| SINAD, SNR, ENOB | Sinal ÷ (ruído + distorção); sinal ÷ ruído; bits efetivos, **corrigidos** para um tom abaixo do fundo de escala | `sinad_db`, `snr_db`, `enob_bits` |
| SFDR | Fundamental ÷ maior espúrio, em dBc, com a frequência do espúrio e se ele é um harmônico | `sfdr_dbc`, `freq_espurio_hz`, `ordem_espurio` |
| Continuidade | Maior salto de fase do tom entre segmentos, em **amostras equivalentes**. Uma amostra perdida ou duplicada vale ~1,0 | `salto_max_amostras`, `saltos_acima_do_limite`, `variacao_amplitude_pct` (variação da amplitude do tom entre segmentos) |
| Acoplamento (≥ 2 canais) | Amplitude de cada canal no tom do canal mais forte (diafonia, dB) e atraso entre canais (µs) | `diafonia_db`, `atraso_medido_us`, `atraso_esperado_us` |
| Comparação com instrumento | `--referencia-rms` (RMS lido, **na unidade física do canal**: V no nó de entrada do divisor; A no condutor, vezes o número de espiras) e `--referencia-freq` (Hz): erro em % e em ppm. `--amplitude-referencia` (`500mVpp`; padrão: a dos metadados; em V é a tensão **no pino**, antes do `--ganho`) e `--osciloscopio` (o `.m`): ADC ÷ injetado, ADC ÷ osciloscópio e osciloscópio ÷ injetado | `erro_amplitude_pct`, `erro_freq_ppm`, `razao_vs_amplitude_ref`, `razao_vs_osc`, `osc_vs_amplitude_ref_pct` |

Opções que você vai usar muito:

| Opção | Para quê |
|---|---|
| `--freq HZ` | Dica da frequência do tom (busca em ±10%). Obrigatória quando há interferência mais forte que o tom (60 Hz) |
| `--sem-tom` | Só ruído e estatística (entrada em curto) |
| `--canais-medir 1` | Mede só um dos canais da captura |
| `--rotulo "texto"` | Nome do teste no CSV (padrão: título do cabeçalho) |
| `--fs-pru` | Usa a frequência que o PRU **de fato** gera (`clock ÷ ticks` do cabeçalho). Sem ela, a análise usa a pedida |
| `--sem-correcao-sonda` | Não aplica o perfil da sonda/cadeia. **Use para caracterizar o ADC**; sem isso, ruído e ENOB de um canal corrigido não descrevem o ADC |
| `--sondas-dir`, `--sonda-perfil C:ARQ` | Onde achar o perfil (padrão: `scripts/sondas/`) |
| `--inicio N`, `--max-amostras N` | Janela de análise, por canal (padrão: as primeiras 4 194 304 amostras, ≈ 42 s a 100 kS/s) |

**Limites do método** (para citar no relatório): usa uma FFT única sobre até 4 M amostras com janela Kaiser (β = 14), cujo vazamento limita o SINAD medido a ~110 dB (acima do ADC de 16 bits, com folga); um tom a menos de ~13 bins do DC (captura curta demais para tom muito grave) sai impreciso e a ferramenta avisa; só enxerga harmônicos que não coincidem entre si depois de dobrados.

---

## Plano: ordem, tempo e prioridade

| Teste | O que valida | Tempo | Dia sugerido |
|---|---|---|---|
| [T0](#t0-preparação-e-sanidade) | Bancada, firmware, cabeçalho, **escala do ADC nas três faixas** | 40 min | 1 |
| [T1](#t1-piso-de-ruído-entrada-em-curto) | Ruído, offset, ruído vs taxa, nº de canais e **faixa de entrada** | 40 min | 1 |
| [T2](#t2-tensão-contínua-ganho-offset-e-linearidade) | Ganho real do divisor, offset, linearidade | 40 min | 1 |
| [T3](#t3-resposta-em-frequência-da-cadeia-de-tensão) | **Perfil da cadeia de tensão** (divisor + filtro de 15 kHz) | 60-90 min | 1 |
| [T4](#t4-frequência-de-amostragem-real) | Taxa de amostragem real (ppm) | 30 min | 2 |
| [T5](#t5-distorção-e-faixa-dinâmica) | THD, SINAD, ENOB, SFDR | 60 min | 2 |
| [T6](#t6-vários-canais-diafonia-e-atraso) | Diafonia e atraso entre canais | 45 min | 2 |
| [T7](#t7-integridade-e-limite-de-taxa) | Nenhuma amostra perdida até 100 kS/s e sob carga; **limite real de taxa (T7e)** | 90 min | 2 |
| [T8](#t8-aliasing) | Rejeição de aliasing | 30 min | 2 |
| [T9](#t9-sinais-de-espectro-conhecido) | Pipeline de supraharmônicos contra espectros conhecidos | 2 h | 3 |
| [T10](#t10-perfil-da-sonda-de-corrente) | **Perfil da sonda de corrente** + validação | 3-4 h | 4 |
| [T11](#t11-ponta-a-ponta) | O sistema inteiro: sinal composto e carga real | 1-2 h | 5 |

**Se só houver um dia:** T0, T1, T3, T7a, T7e e T10 (nessa ordem). É o mínimo para afirmar que o sistema captura sem perder dados, ter o limite de taxa documentado e os perfis do divisor e da sonda.

---

## Os testes

### T0: preparação e sanidade

**Objetivo.** Ter certeza de que firmware, relógio, cabeçalho **e a escala do ADC (nas três faixas)** estão certos antes de gastar tempo em medidas.

1. No computador, com a BeagleBone por USB: `scripts/set_date.sh`. Na BeagleBone: `date` deve mostrar a data de hoje.
2. Na BeagleBone: `cd firmware && ./setup.sh && dmesg | tail -n 20` (a PRU sobe sem reclamar). O `setup.sh` **recompila** o firmware (`make clean; make`): é preciso fazer isso depois de atualizar o repositório, porque a escrita da faixa do ADC está no `spi_core.asm` e no `ler_adc`. Se o `make` falhar, pare aqui e guarde a mensagem (o assembly da PRU foi validado só num simulador, nunca no `clpru`). Confira com `./ler_adc --help` que a opção `--faixa-adc` existe.
3. Ligue o gerador, o osciloscópio, a ponta TCP0030A, o frontend e a BeagleBone **30 minutos antes** do T1.
4. **Capacitor do canal de corrente:** com tudo desligado, meça o valor dele (Fluke ou LCR; o seu 63 mF parece impreciso) e fotografe a placa. Anote o valor, **remova-o** e confirme que os dois resistores em série (1,79 kΩ e 1,7929 kΩ) continuam no lugar.
5. Entrada do canal de tensão em curto (a entrada do divisor ligada ao retorno). Capture:

```bash
sudo ./ler_adc 100000 1 --blocos 1 -o T0_sanidade.bin -t "T0 sanidade 100k"
ls -l T0_sanidade.bin        # 2098176 bytes = 1024 de cabeçalho + 1048576 amostras de 2 bytes
```

```fish
uv run scripts/medir_captura.py lab/2026-10-20/T0_sanidade.bin --sem-tom --sem-correcao-sonda
```

6. **Escala do ADC nas três faixas (10 minutos).** Gerador em **DC** (forma de onda DC, *High-Z*) com **+10,000 V** no nó de entrada do divisor, o Fluke 289 no mesmo nó (anote a leitura `V_in`, com todos os dígitos). No pino do ADC isso é `V_in × 0,05157` ≈ 0,516 V, que cabe nas três faixas. Capture o canal de tensão **uma vez em cada faixa**:

```bash
sudo ./ler_adc 100000 1 --blocos 1 --faixa-adc 1:20.48 -o T0_dc_p10_f2048.bin -t "T0 DC +10V faixa 20.48"
sudo ./ler_adc 100000 1 --blocos 1 --faixa-adc 1:10.24 -o T0_dc_p10_f1024.bin -t "T0 DC +10V faixa 10.24"
sudo ./ler_adc 100000 1 --blocos 1 --faixa-adc 1:5.12  -o T0_dc_p10_f512.bin  -t "T0 DC +10V faixa 5.12"
```

```fish
# --ganho 1: o 'media' sai em volts NO PINO, na faixa que o cabeçalho de cada captura registra
for f in 2048 1024 512
    uv run scripts/medir_captura.py lab/2026-10-20/T0_dc_p10_f$f.bin --sem-tom --sem-correcao-sonda --ganho 1
end
```

Cada saída mostra, no resumo do cabeçalho, `canal 1: ±10.24 V`, `±5.12 V` e `±2.56 V`, respectivamente (se aparecer `±10.24 V` nas três, o `ler_adc` não está gravando a faixa: recompile). Divida cada `media` por `V_in × 0,05157` (a **razão** abaixo) e compare:

| Razão com 20.48 | Razão com 10.24 | Razão com 5.12 | Conclusão |
|---|---|---|---|
| ≈ 1,00 | ≈ 1,00 | ≈ 1,00 | **Tudo certo**: referência de 4,096 V, escrita de `RANGE_SELn` e conversão código → volts conferem. As três `media` devem concordar entre si em poucos mV (diferença de offset por faixa; datasheet: ±0,5 mV típico) |
| ≈ 1,00 | ≈ 0,50 | ≈ 0,25 | A escrita de `RANGE_SELn` **não pegou**: o ADC continua em ±10,24 V e só o cabeçalho diz o contrário. Problema de firmware (guarde o `dmesg` e a saída do `ler_adc`) |
| ≈ 2,00 | ≈ 2,00 | ≈ 2,00 | A escala-base é **metade** da suposta (referência de 2,048 V, por exemplo) |
| ≈ 0,50 | ≈ 0,50 | ≈ 0,50 | A escala-base é o **dobro** da suposta |
| Outra combinação | | | Pare e investigue (ganho no frontend, referência externa, `RANGE_SEL` escrito por outra rotina, ADC saturando) antes de seguir |

Repita com **−10,000 V** em pelo menos a faixa de ±2,56 V (o sinal da leitura confere, e `media` muda de sinal sem offset grande). O T2 refina o ganho do divisor; este passo só confirma a escala. Para as capturas **antigas** (anteriores a esta versão), compare a `media` delas (lidas com 10.24) com a de `T0_dc_p10_f2048.bin`: se a antiga der metade, ela estava mesmo em ±10,24 V e deve ser relida com `--faixa 20.48`.

**Passou se:** o resumo do cabeçalho aparece sem "CRC-32 NÃO confere"; o tamanho do arquivo é o esperado; a saída do `medir_captura` não tem avisos; o DC (`media`) do curto é de poucos mV; **as três faixas dão a mesma tensão no pino (razão ≈ 1,00)**.

### T1: piso de ruído (entrada em curto)

**Objetivo.** Ruído, offset e como eles variam com a taxa e o número de canais.

**Montagem.** Três condições, todas sem sinal:

* **Canal 1 (tensão):** entrada do divisor em curto. Se der para acessar o pino do ADC (R5), faça uma rodada ali e outra pela entrada do divisor: a diferença é o ruído do divisor (1,7 kΩ de impedância de fonte).
* **Canal 0 (corrente), curto:** terminais de entrada da placa em curto.
* **Canal 0, sonda ligada:** SCT013 ligado, garra fechada, **sem condutor**. Mostra o ruído captado do ambiente (60 Hz, rádio).

**Sinal.** Nenhum.

```bash
sudo ./ler_adc 100000 1   --blocos 1 -o T1_curto_100k_1ch.bin -t "T1 curto 100k 1ch"
sudo ./ler_adc 50000 1    --blocos 1 -o T1_curto_50k_1ch.bin -t "T1 curto 50k 1ch"
sudo ./ler_adc 100000 0,1 --faixa-adc 0:5.12 --blocos 1 -o T1_curto_100k_2ch.bin -t "T1 curto 100k 2ch"
# ruído × faixa de entrada (canal 1 em curto; a de 20.48 é a T1_curto_100k_1ch): o dado que mostra quanto reduzir a faixa ajuda
sudo ./ler_adc 100000 1 --faixa-adc 1:10.24 --blocos 1 -o T1_curto_100k_faixa1024.bin -t "T1 curto 100k faixa 10.24"
sudo ./ler_adc 100000 1 --faixa-adc 1:5.12  --blocos 1 -o T1_curto_100k_faixa512.bin  -t "T1 curto 100k faixa 5.12"
# opcional, se os outros canais tiverem entrada acessível (em curto):
sudo ./ler_adc 100000 0,1,2,3,4,5,6,7 --blocos 1 -o T1_curto_100k_8ch.bin -t "T1 curto 100k 8ch"
# ACIMA do recomendado (só para o relatório; veja T7e):
sudo ./ler_adc 130000 1 --blocos 1 -o T1_curto_130k_1ch.bin -t "T1 curto 130k 1ch"
sudo ./ler_adc 200000 1 --blocos 2 -o T1_curto_200k_1ch.bin -t "T1 curto 200k 1ch"
sudo ./ler_adc 500000 1 --blocos 5 -o T1_curto_500k_1ch.bin -t "T1 curto 500k 1ch"
```

Repita com a condição "sonda ligada, sem condutor" no canal 0, **já na faixa de produção do canal de corrente**:

```bash
sudo ./ler_adc 100000 0   --faixa-adc 0:5.12 --blocos 1 -o T1_sonda_100k_1ch.bin -t "T1 sonda 100k 1ch"
sudo ./ler_adc 100000 0,1 --faixa-adc 0:5.12 --blocos 1 -o T1_sonda_100k_2ch.bin -t "T1 sonda 100k 2ch"
```

Para ver o efeito da faixa no **mesmo** canal, faça também o canal 0 (corrente) em curto nas três faixas (`--faixa-adc 0:20.48`, `0:10.24` e `0:5.12`, um canal só): o ruído em volts deve cair com a faixa e o ruído em LSB, subir.

```fish
uv run scripts/medir_captura.py lab/2026-10-20/T1_*.bin --sem-tom --sem-correcao-sonda --csv lab/2026-10-20/resultados.csv
uv run scripts/adc_tool.py lab/2026-10-20/T1_curto_100k_1ch.bin --welch --modo-espectro ruido --sem-correcao-sonda -o lab/2026-10-20/fig_T1_psd.png
```

**Anote.** Nada no osciloscópio (opcional: tensão de ruído na entrada, só para ver se há zumbido evidente).

**Esperado.** Pelo datasheet (tom em −0,5 dBFS), o ruído no pino depende da faixa: **±10,24 V** (SNR de 90 a 92 dB): **~170 a 215 µV RMS**, ou **0,55 a 0,7 LSB** (1 LSB = 312,5 µV); **±5,12 V** (SNR típico de 91 dB, mínimo de 89 dB): **~96 a 121 µV** (0,6 a 0,8 LSB de 156 µV); **±2,56 V** (SNR típico de 89 dB, mínimo de 87,5 dB): **~61 a 72 µV** (0,8 a 0,9 LSB de 78 µV). Ou seja, reduzir a faixa diminui o ruído **em volts** (cerca de 1,8× e 2,8×), mas não na proporção da faixa: confira esses números, são a evidência de quanto a faixa menor ajuda. O offset deve ficar dentro de ±0,75 mV (típico ±0,5 mV) no pino do ADC. Ruído de 2 LSB ou mais indica problema de placa (cabo longo, terra, USB, alimentação): investigue antes de seguir. O espectro de ruído (PSD) deve ser plano, com poucos picos; **qualquer pico fixo** (60 Hz e harmônicos, relógio, 50 kHz) vai aparecer nos dados reais e precisa ser identificado. Para o relatório, converta o ruído para **a entrada de cada cadeia**: ÷ 0,051662 no canal de tensão (**~3,3 a 4,2 mV RMS** de banda larga) e ÷ 60 µV/A no de corrente (**~3 a 4 A RMS** equivalentes, com 1 espira): é a medida honesta da sensibilidade do projeto. Acima de 100 kS/s o ruído pode piorar (as margens de tempo do SPI): é o dado que se quer.

**Para o relatório.** Tabela: taxa × nº de canais × (ruído em LSB, µV RMS, nV/√Hz, offset em mV, ruído equivalente na entrada). Tabela do ruído por **faixa de entrada** (±10,24; ±5,12 e ±2,56 V) em µV RMS e em LSB, contra o datasheet. Figura: a PSD do curto.

### T2: tensão contínua (ganho, offset e linearidade)

**Objetivo.** Ganho real do divisor (vira o `$GV` calibrado), offset e linearidade, com DC.

**T2a: pelo divisor (canal 1).** O gerador em DC é a fonte (offset de ±10 V em High-Z), o Fluke 289 mede no nó de entrada do divisor. Sinal: **−10, −5, 0, +5 e +10 V** (os 5 níveis do gerador, anote cada leitura do multímetro com todos os dígitos).

```bash
sudo ./ler_adc 100000 1 --blocos 1 -o T2_dc_p5v.bin -t "T2 DC +5V"    # e assim para os 5 níveis
```

```fish
uv run scripts/medir_captura.py lab/2026-10-20/T2_dc_*.bin --sem-tom --sem-correcao-sonda --ganho 1 --csv lab/2026-10-20/resultados.csv
```

**Análise (planilha).** `media` (volts no pino) contra a leitura do multímetro na entrada: ajuste linear. A **inclinação é a razão real do divisor com a carga do ADC**: compare com 0,05157 (nominal com a carga de 1 MΩ; 0,051662 sem ela). Se for diferente por mais de ~0,3%, use `1 ÷ inclinação` como `$GV` (e se for perto de **metade** ou do **dobro**, a escala do T0 está errada). O intercepto é o offset (esperado ±0,75 mV no pino, ±15 mV referido à entrada); o resíduo, em LSB, é o erro de linearidade **na faixa de ±0,5 V do pino** (só 10% da escala).

**T2b (opcional): linearidade na escala inteira.** O divisor só deixa ver ±0,52 V no pino. Se algum outro canal tiver a entrada ligada direto no pino do ADC, repita lá com DC de **−9, −6, −3, 0, +3, +6, +9 V** do gerador (≤ ±10 V). Sem esse acesso, a linearidade acima de ±0,5 V só pode ser conferida na rede (T2c).

**T2c (opcional, com supervisão): a rede.** Transformador de isolamento + autotransformador (se houver), 3 níveis de rede: ~60, ~100 e ~127 V RMS. Fluke 289 no mesmo nó; capture 1 bloco a 100 kS/s e rode `medir_captura.py ... --freq 60 --referencia-rms <leitura do Fluke> --ganho $GV` (precisa estar sem saturação: `saturacao_pct` = 0). **Nunca 220 V** (satura). Mostra o ganho no uso real do projeto e a margem até o fundo de escala (127 V = 91%).

**Esperado (datasheet, faixa de ±2,5 × VREF).** Erro de ganho típico ±0,02% da faixa (máx. ±0,05%), offset típico ±0,5 mV (máx. ±0,75 mV), INL típica ±0,75 LSB (máx. ±2 LSB). Os resistores do divisor (medidos com multímetro) e o multímetro limitam o que você consegue provar: registre as incertezas.

**Para o relatório.** Gráfico `media` × referência com a reta e o resíduo em LSB; razão real do divisor, offset e (se feita) linearidade em escala inteira.

### T3: resposta em frequência da cadeia de tensão

**Objetivo.** Medir a **atenuação de amplitude** da cadeia de tensão (divisor e filtro de 15 kHz do ADC) de 50 Hz até 45 kHz (90% da Nyquist de 1 canal a 100 kS/s). É o resultado mais importante para a banda de supraharmônicos de tensão, e dele sai um perfil (`.json`) para corrigir o canal de tensão. Trate-o como "o perfil da sonda de tensão".

**Montagem.** Gerador (*High-Z*) → nó de entrada do divisor. Ponta TPP0500B do osciloscópio e o Fluke (em baixa frequência) no **mesmo nó**.

**Sinal.** Senoide pura, de 50 Hz a **45 kHz** em 24 pontos logarítmicos, **sempre com a amplitude máxima do gerador (20 Vpp)**: no pino fica 1,03 Vpp (5% da faixa de ±10,24 V), e perto de 45 kHz o filtro deixa só ~0,1 Vpp (0,5% da escala, ainda acima do limiar de 0,2% do assistente). Não reduza a amplitude. Em cada frequência você lê o RMS real **na entrada do divisor** (osciloscópio; o gerador cai de amplitude em alta frequência), então a amplitude pode mudar de ponto a ponto: não precisa ser constante.

**Execução com o assistente de calibração**, que escolhe as frequências, confere cada captura e guarda o RMS que você digita:

```bash
cd firmware
sudo ./calibrar_sonda.sh --taxa 100000 --canal-sonda 1 --pontos 24 --freq-max 45k --blocos 1 --sonda cadeia_tensao --grandeza tensao --ref-externa
```

* O script pede a "**tensão RMS na entrada da cadeia**": a do nó de entrada do divisor que você lê no osciloscópio/multímetro (ex.: `7.0712` para 20 Vpp; aceita também `7.0712 Vrms` ou `7071.2m`).
* Leia o RMS **antes** de apertar ENTER para medir (com o sinal estável) e digite quando o script perguntar.
* Em **todos** os pontos o script avisa "sinal fraco no canal da sonda" (o máximo é 5% da escala, e o limiar de aviso é 10%): é esperado, aceite com `C`. Em 45 kHz o nível cai para ~0,5% da escala; se algum ponto for recusado como "sem sinal" (abaixo de 0,2%), confira o gerador (20 Vpp, *High-Z*) e a ligação.

**Variante com amplitude conhecida (nada a digitar a cada ponto).** Se o gerador mantém o nível (confira no osciloscópio em 3 ou 4 frequências), informe a amplitude que ajustou: o script a grava nos metadados de cada captura (`ref: f=.. amp=..`). **Atenção à convenção:** em volts, a amplitude é a tensão **no pino do ADC, antes do `--ganho`**, e não na entrada do divisor. Informe, portanto, o que o divisor nominal entrega ao pino: 20 Vpp no gerador (*High-Z*) × 0,051662 = **1,0332 Vpp**:

```bash
sudo ./calibrar_sonda.sh --taxa 100000 --canal-sonda 1 --pontos 24 --freq-max 45k --blocos 1 --sonda cadeia_tensao --grandeza tensao --amplitude 1.0332Vpp
```

(Se informar `20Vpp` junto com `--ganho 19.357`, o gerador de perfil entende 387 Vpp injetados e o ganho de baixa frequência sai ~0,05: o aviso "fora de [0,7; 1,3]" denuncia o erro.)

No computador, com a leitura do osciloscópio digitada (coluna `tensao_rms_V`: a leitura já é a tensão física, sem shunt):

```fish
uv run scripts/gerar_perfil_sonda.py capturas/cadeia_tensao --referencia-externa --ganho $GV --plot
```

Uma coleta feita antes de `--grandeza tensao` gravou a leitura na coluna `v_shunt_rms_V`: para ela, some `--resistencia-shunt 1` (com 1 Ω, a "corrente" calculada é numericamente a tensão em volts). Para a variante de amplitude conhecida, o mesmo comando **sem** `--referencia-externa` (a amplitude vem dos metadados). Para um `.m` por ponto (tensão na entrada do divisor, em V), troque por `--referencia-osciloscopio --osc-unidade A`. O resultado é `scripts/sondas/cadeia_tensao.json` e um PNG com a curva. O `$GV` usado aqui é o mesmo que vai em produção: o perfil sai **relativo a ele** (ganho de baixa frequência esperado ~0,998, a carga de 1 MΩ).

**Verificação pontual, sem o assistente.** Para conferir a amplitude em uma frequência, sem gerar perfil:

```bash
sudo ./ler_adc 100000 1 --blocos 2 -o T3_f40000.bin -t "T3 40 kHz"
```

```fish
uv run scripts/medir_captura.py lab/2026-10-20/T3_f40000.bin --freq 40000 --referencia-rms 7.0712 --sem-correcao-sonda --ganho $GV --csv lab/2026-10-20/resultados.csv
```

Imprime o erro de amplitude em % (ADC contra instrumento): a atenuação da cadeia nessa frequência.

**Ensaio prévio do fluxo.** O caminho "assistente → `gerar_perfil_sonda.py` → correção no `medir_captura.py`" foi ensaiado com dados sintéticos de uma cadeia de dois polos com −3 dB em 15 kHz (24 pontos, 50 Hz a 160 kHz, **400 kS/s**, 1 canal): o perfil recuperou o ganho com erro de 0,001%, e uma onda quadrada de 10 kHz, que sem correção mostrava a 15ª harmônica 31 dB abaixo da teoria, voltou à teoria em ±0,05 dB até 150 kHz (a fundamental, em 0,03%). A 100 kS/s o fluxo é o mesmo, mas só vai até 45 kHz. Avisos "fora da faixa válida" aparecem se a análise tiver componentes além do último ponto do perfil (o ganho é mantido constante ali, sem extrapolar).

**Esperado.** Ganho plano (±0,1 dB) até ~2,5 kHz, **−3 dB perto de 15 kHz** e queda de 12 dB por oitava, chegando a algo entre −14 e −19 dB em 45 kHz. O `gerar_perfil_sonda.py` imprime o resumo da resposta (ganho de baixa frequência, frequência de −3 dB, inclinação final em dB/oitava e quanto a correção amplifica o ruído na maior frequência: ~+14 a +19 dB) e o grava no perfil (`calibracao_adc.resposta_conjunto`). Como o último ponto é 45 kHz, a inclinação final tem pouca excursão: a frequência de −3 dB é o resultado mais seguro. Se a curva mostrar ressonâncias ou picos, são do divisor ou da fiação: aumente a densidade de pontos ali (`--modo refinar`).

**Para o relatório.** A curva de ganho (dB) × frequência (eixo logarítmico), com a frequência de −3 dB marcada e a curva teórica do datasheet por cima; tabela de ganho em 1, 5, 10, 15, 20, 30 e 45 kHz. A figura sai do script das figuras do relatório, que lê o perfil, ajusta um passa-baixa de 2ª ordem (em dB) e grava, além do PDF, as macros com K, f0, Q e f−3dB para o texto:

```fish
uv run relatorio/gerar_figuras.py perfil_cadeia_tensao --png
```

**Executado em 19/10/2026** (48 pontos de 50 Hz a 45 kHz, `--ref-externa`, sem repetições; `scripts/sondas/cadeia_tensao.json`): −3 dB em **17,3 kHz** e −12,5 dB em 45 kHz; o 2ª ordem ajusta com f0 = 24,1 kHz, Q = 0,54 e resíduo de 0,13 dB. Para a próxima rodada: `--grandeza tensao` (a coleta de 19/10 é anterior à opção e ficou marcada como corrente, o que não muda o perfil) e `--repeticoes 3`, para ter a incerteza de cada ponto (o ajuste passa a ser ponderado). A fase não foi medida: a função de transferência vale sob a hipótese de fase mínima (ver `docs/notas_relatorio.md`, Marco 12).

### T4: frequência de amostragem real

**Objetivo.** Medir quanto a taxa gerada pela PRU difere da pedida, e se a diferença é só a divisão inteira dos ticks.

**Montagem.** Gerador → divisor (canal 1); osciloscópio no mesmo nó **com o contador de frequência** (ou use a entrada de 10 MHz de referência do gerador).

**Sinal.** Senoide de **10,000 kHz**, 20 Vpp (máximo do gerador). Anote a frequência real no contador, com todos os dígitos (ex.: `10000.02`).

Capture com cada taxa (1 canal, ~10 s):

```bash
for taxa in 50000 100000 102400 110000 125000; do
  sudo ./ler_adc $taxa 1 --duracao 10s -o T4_fs_$taxa.bin -t "T4 fs $taxa"
done
```

```fish
for taxa in 50000 100000 102400 110000 125000
    uv run scripts/medir_captura.py lab/2026-10-20/T4_fs_$taxa.bin --freq 10000 --referencia-freq 10000.02 --sem-correcao-sonda --csv lab/2026-10-20/resultados.csv
end
```

(As taxas acima de 125 kS/s ficam no [T7e](#t7e-onde-está-o-limite-de-taxa): lá a taxa real pode nem acompanhar a pedida.)

**Como ler.** Sem `--fs-pru`, a análise supõe a taxa pedida. Se a taxa real da PRU for `fs_real = fs_pedida × (1 + δ)`, o tom aparece na frequência errada e o `erro_freq_ppm` do CSV é `−δ × 10⁶` (frequência medida menos a do contador, em ppm; usa-se o valor do contador como verdade, então o erro do gerador não entra). A primeira linha da saída de cada captura informa o que o firmware **deveria** gerar pelos ticks: `o PRU gera 102406.55 Hz = +64.0 ppm`; a coluna `fs_pru_hz` do CSV guarda esse valor. Compare:

* Taxas que dividem 200 MHz (50, 100, 125 kS/s) devem dar **todas o mesmo `erro_freq_ppm`**: é o erro do cristal da PRU (δ_cristal), comum a todas.
* 102,4 kS/s deve dar `−(δ_cristal + 64 ppm)` e 110 kS/s, `−(δ_cristal + 100 ppm)`: a diferença para as taxas exatas é o arredondamento dos ticks.
* Se as taxas exatas **não** derem o mesmo valor, o laço da PRU tem um número de ciclos fixo a mais por amostra (a hipótese "taxa = clock ÷ ticks" está errada): isso também vai para o relatório.
* Repita com `--fs-pru` em 102,4 kS/s: o `erro_freq_ppm` deve cair para o mesmo valor das taxas exatas (a análise passa a usar a taxa que o PRU gera).

**Esperado.** Cristal da BeagleBone na faixa de dezenas de ppm. Em frequências medidas, isso é um erro relativo de 0,00x%, desprezível para amplitude, mas relevante se você quiser separar tons muito próximos ou comparar a frequência com uma referência.

**Para o relatório.** Tabela: taxa pedida × ticks × taxa gerada prevista × erro medido (ppm). Recomendação do uso de taxas exatas.

### T5: distorção e faixa dinâmica

**Objetivo.** THD, SINAD, ENOB e SFDR do ADC com tom puro, contra o nível e contra a frequência.

**Atenção à fonte.** O THD do gerador de funções (−50 a −70 dBc) **esconde** o THD de −102 dB do ADC. Duas saídas: passar o gerador por um filtro passa-faixa (LC ou ativo) na frequência do tom, ou usar uma fonte de baixa distorção (uma boa placa de som, com THD melhor que −90 dB). Se o THD medido for igual ao do datasheet do gerador, o resultado é limite do **gerador**, não do ADC, e o relatório deve dizer isso.

**Montagem e limite do nível.** Pelo divisor o gerador só entrega ao pino **−26 dBFS** (0,517 V de pico, com 20 Vpp). A varredura de nível fica, então, de −26 a −70 dBFS. Se houver acesso direto ao pino de algum canal, acrescente os níveis altos (−0,5 e −6 dBFS: 19,3 Vpp e 10,3 Vpp, com `--ganho 1`). Tabela do que ajustar no gerador (*High-Z*), nível no pino → entrada do divisor:

| Nível no pino | Pico no pino | Vpp no gerador (pelo divisor) |
|---|---|---|
| −26 dBFS | 513 mV | **19,9 Vpp** (máximo) |
| −30 dBFS | 324 mV | 12,5 Vpp |
| −40 dBFS | 102 mV | 3,96 Vpp |
| −50 dBFS | 32,4 mV | 1,25 Vpp |
| −60 dBFS | 10,2 mV | 0,40 Vpp |
| −70 dBFS | 3,2 mV | 0,125 Vpp |

**T5a: varredura de amplitude, 1 kHz.** Níveis −26, −30, −40, −50, −60 e −70 dBFS:

```bash
sudo ./ler_adc 100000 1 --blocos 2 -o T5a_1k_m40dBFS.bin -t "T5a 1kHz -40dBFS"    # e os outros níveis
```

**T5b: varredura de frequência, −26 dBFS (20 Vpp).** 1, 5, 10, 20 e 40 kHz (**não** use 50 kHz: é a própria Nyquist).

```fish
uv run scripts/medir_captura.py lab/2026-10-20/T5*.bin --sem-correcao-sonda --ganho 1 --harmonicos 9 --csv lab/2026-10-20/resultados.csv
```

(`--ganho 1`: o ADC sozinho, em volts no pino.)

**Anote.** Amplitude real no osciloscópio/multímetro em cada ponto; modelo e THD do gerador; se usou filtro.

**Esperado (datasheet, tom em −0,5 dBFS, 1 kHz, faixa de ±2,5 × VREF).** SNR 92 dB (mín. 90), SINAD 91,5 dB (mín. 89), **ENOB ≈ 14,9 bits** (mín. 14,5), THD −102 dB, SFDR 103 dB. Como o nível máximo pelo divisor é −26 dBFS, o SINAD medido tende a ~66 dB (cai 1 dB por dB de nível, até o piso de ruído); a **faixa dinâmica** vem da extrapolação da reta de SINAD × nível. O ENOB do `medir_captura.py` já é corrigido para o nível do tom. Em frequências mais altas o THD medido parece **melhor** do que é: os harmônicos (2f, 3f...) são atenuados mais ainda pelo filtro de 15 kHz, e acima de Nyquist dobram para dentro.

**Para o relatório.** Figura: SINAD (e ENOB) × nível em dBFS; a faixa dinâmica é o nível em que o SINAD chega a 0 dB. Figura: THD, SINAD e SFDR × frequência. Tabela: valores medidos contra datasheet.

### T6: vários canais (diafonia e atraso)

**Objetivo.** Quanto um canal vaza no outro, e se o intervalo de multiplexação entre canais é o esperado (importante para qualquer cálculo que combine tensão e corrente).

**T6a: diafonia.** Capture 2 canais (0 e 1) a 100 kS/s (50 kS/s cada). **Canal 1** (tensão) recebe um tom de 10 kHz com **20 Vpp** (−26 dBFS no pino, o máximo pelo divisor); **canal 0** (corrente) com a entrada em curto. Repita com 40 kHz. Na varredura (0, 1, 0, 1, ...), o canal 0 é amostrado **logo depois** do 1, que é o pior caso para a "diafonia de memória". (O agressor no canal 0 não é possível: o resistor de 0,12 Ω da entrada de corrente curto-circuita o gerador. Só seria possível com acesso direto ao pino.) Para o pior caso global, capture 8 canais a 100 kS/s com o tom no canal 1 e os demais em curto, se as entradas forem acessíveis (o canal 2 é o amostrado logo depois do 1).

```bash
sudo ./ler_adc 100000 0,1 --faixa-adc 0:5.12 --blocos 2 -o T6a_10k_ch1.bin -t "T6a 10kHz ch1 agressor"
sudo ./ler_adc 100000 0,1 --faixa-adc 0:5.12 --blocos 2 -o T6a_40k_ch1.bin -t "T6a 40kHz ch1 agressor"
```

**T6b: atraso entre canais.** Precisa do **mesmo sinal** nos dois canais, com o mesmo condicionamento. Se a placa tiver dois canais equivalentes (dois divisores, ou dois pinos acessíveis), ligue-os em paralelo com um conector T de BNC, cabos do mesmo comprimento, a 100 kS/s, em 1, 5 e 10 kHz. Senão, use o teste **V–I** (opcional): gerador → resistor de 10,92 Ω → **N espiras** no SCT013 → retorno; a tensão **no resistor** vai para o divisor (canal 1) e a corrente é a do SCT013 (canal 0), com o MSO46 medindo a mesma tensão (TPP0500B) e a corrente (TCP0030A) ao mesmo tempo. A diferença entre o atraso visto pelo ADC e o do osciloscópio é o atraso da cadeia (acrescido da fase do SCT013, que o perfil de amplitude **não** corrige). O sinal da corrente é fraco (T10-0): use 1 kHz e 4 blocos, e só confie no resultado se o `snr_db` do canal 0 (corrente) passar de 30 dB. Na varredura, o canal 0 é convertido **antes** do 1 (1/taxa total, 10 µs a 100 kS/s): esse atraso de conversão é o que entra no `atraso_esperado_us`, somado ao das cadeias.

```bash
sudo ./ler_adc 100000 0,1 --faixa-adc 0:5.12 --blocos 4 -o T6b_1k.bin -t "T6b mesmo sinal 1kHz"
```

```fish
uv run scripts/medir_captura.py lab/2026-10-20/T6*.bin --sem-correcao-sonda --csv lab/2026-10-20/resultados.csv
```

(A diafonia é medida em volts no pino, então as faixas diferentes dos dois canais, lidas do cabeçalho, não atrapalham; o canal 0 em ±2,56 V tem menos ruído, e a diafonia mínima mensurável melhora na mesma medida.)

**Como ler.** A saída traz "Acoplamento entre canais no tom de ...": em T6a, `diafonia_db` do canal em curto; em T6b, `atraso_medido_us` contra `atraso_esperado_us`.

**Esperado.** Datasheet: isolamento entre canais de **110 dB** e diafonia de memória de **90 dB** (com agressor em sobrecarga de 2× o fundo de escala). Aqui o agressor está 26 dB abaixo do fundo de escala e o que a ferramenta mede é limitado pelo ruído por bin (~−110 dB): se o resultado estiver no piso, escreva "melhor que X dB". O atraso entre canais consecutivos deve ser **1/taxa total** (10 µs a 100 kS/s): é o que a PRU configura, e vale compensar no cálculo de potência (a 60 Hz isso é 0,22°; a 5 kHz, 18°; a 40 kHz, 144°).

**Para o relatório.** Tabela de diafonia (frequência × par de canais); tabela de atraso medido contra esperado.

### T7: integridade e limite de taxa

**Objetivo.** Provar que **nenhuma amostra é perdida ou duplicada** até 100 kS/s e sob carga na BeagleBone, que os dados chegam ao disco inteiros (requisito de desempenho do projeto), e **documentar onde está o limite real** e o que acontece acima dele.

**Sinal.** Senoide de 10 kHz com 20 Vpp (−26 dBFS no pino), estável (a continuidade se verifica pela fase do tom: um tom estável é essencial). Canal 1 (tensão).

**T7a: taxas até o limite recomendado.** 10 s em cada taxa, 1 canal.

```bash
for taxa in 50000 100000; do
  sudo ./ler_adc $taxa 1 --duracao 10s -o T7a_fs_$taxa.bin -t "T7a $taxa"
done
```

**T7b: dois canais.** 2 canais a 100 kS/s (50 kS/s por canal), 10 s, tom de 10 kHz no canal 1 (tensão) e o canal 0 em curto; e, se as entradas forem acessíveis, 8 canais a 100 kS/s (12,5 kS/s por canal).

**T7c: longa duração e deriva.** 10 minutos a 100 kS/s com o tom (≈ 120 MB; confira o espaço livre).

```bash
sudo ./ler_adc 100000 1 --duracao 10m -o T7c_10min.bin -t "T7c 10 min 100k"
```

```fish
for ini in (seq 0 6000000 54000000)
    uv run scripts/medir_captura.py lab/2026-10-20/T7c_10min.bin --freq 10000 --inicio $ini --max-amostras 4000000 --rotulo "T7c ini $ini" --sem-correcao-sonda --csv lab/2026-10-20/resultados.csv
end
```

**T7d: sob carga.** Repita o T7a a 100 kS/s **enquanto** outra janela copia um arquivo grande por `scp` e outra roda `top`. Mostra se o sistema de arquivos ou a CPU atrapalham a captura.

```fish
uv run scripts/medir_captura.py lab/2026-10-20/T7[abcd]*.bin --freq 10000 --sem-correcao-sonda --csv lab/2026-10-20/resultados.csv
```

**Esperado.** Em cada captura: `continuidade : OK`, **0 eventos**, maior salto de fase **menor que 0,5 amostra** (um problema real dá ~1,0, ou múltiplos); tamanho do arquivo igual ao do cabeçalho (a ferramenta avisa se não for); amplitude do tom varia menos de ~0,1% entre segmentos. No T7c, o tom pode derivar um pouco pelo gerador: compare com a leitura do osciloscópio no início e no fim.

**Passou se:** zero eventos em todas as capturas de até 100 kS/s, inclusive T7b e T7d, e o `ler_adc` termina com `Integridade: 0 amostra(s) atrasada(s), 0 buffer(s) sobrescrito(s), 0 quadro(s) com ruído no SDO -- tudo certo`. Um evento = anote em qual taxa, que amostra (`perto da amostra N`) e olhe a saída do terminal do `ler_adc` e o `dmesg` daquele instante.

**Firmware anterior a out/2026.** As capturas de 19/10 (T7c, T4) mostram um salto de ~0,7 amostra (6,97 µs) **em cada troca de buffer** (amostras 1.048.576, 2.097.152...): o contador de ciclos da PRU era zerado ali depois da transação da última amostra. O `medir_captura.py` o aponta ("numa troca de buffer da PRU"). Depois de recompilar (`./setup.sh`), refaça o T7c: a continuidade tem de sair **OK** nos 10 min. É a validação em hardware da correção (o simulador já confere a lógica).

#### T7e: onde está o limite de taxa

**Objetivo.** Saber **até onde** vai a taxa real e **qual parte** do projeto é o gargalo (a PRU/SPI, o ADC ou o lado ARM), em vez de supor. São os itens F2 e F3 de [`melhorias-propostas.md`](melhorias-propostas.md#f2--medir-até-onde-as-esperas-do-cs-podem-cair), medidos em bancada.

**Hipótese a testar** (confirmada no firmware em out/2026; falta a medida no CS). O ADS8688 precisa só de ~2 µs por amostra (500 kS/s), mas a PRU gasta bem mais: pela contagem estática do `spi_core.asm` (±10%), 32 bits de SCLK de ~16 a 19 ciclos cada (≈ 2,9 µs) mais os três laços de atraso do CS (200 + 100 + 100 iterações de 2 ciclos = 800 ciclos = **4,0 µs**) dão **~7 µs por quadro**, ou seja, ~140 kS/s no papel; o limite que você observou (130 kS/s) está nessa faixa. Executar o próprio `spi_core.asm` num simulador de PRU (`tests/pru_sim.py`, 1 ciclo por instrução, sem hardware) deu o mesmo resultado: **1379 ciclos = 6,9 µs por quadro (~145 kS/s)**, dos quais **800 ciclos (58%) são os três laços de atraso do CS**. É um teto de papel (acessos à memória externa podem somar ciclos): só o osciloscópio (método 2) confirma. Os mínimos do datasheet são 30/10/30 ns (tSU_CSCK, tD_CKCS, tPH_CS); reduza só pelo método 4, medindo. Se for isso, a taxa **real** satura em torno de 130 kS/s, **sem perder amostra**, qualquer que seja a taxa pedida. O lado ARM é improvável (130 kS/s = 260 kB/s; cada buffer de 2 MB demora ~8 s para encher).

**Método 1: pelo tom.** 10 s em cada taxa pedida, com a senoide de 10,000 kHz do T4 (anote a leitura do contador):

```bash
for taxa in 100000 110000 120000 125000 130000 135000 140000 150000 200000 250000 500000; do
  sudo ./ler_adc $taxa 1 --duracao 10s -o T7e_fs_$taxa.bin -t "T7e fs $taxa" 2>&1 | tee -a T7e_saida_ler_adc.txt
done
```

```fish
for taxa in 100000 110000 120000 125000 130000 135000 140000 150000 200000 250000 500000
    uv run scripts/medir_captura.py lab/2026-10-20/T7e_fs_$taxa.bin --referencia-freq 10000.02 --sem-correcao-sonda --rotulo "T7e fs $taxa" --csv lab/2026-10-20/resultados.csv
end
```

(sem `--freq`: o tom pode aparecer deslocado quando a taxa real é menor que a pedida; a ferramenta usa o maior pico.) Calcule **`fs_real = fs_pedida × 10000,02 ÷ freq_tom_hz`** (equivale a `fs_pedida ÷ (1 + erro_freq_ppm × 10⁻⁶)`).

**Método 2: pelo CS no osciloscópio (10 min, sem tocar no firmware).** Ponta do MSO46 no **CS** do ADS8688 (e, num segundo canal, no **SCLK**), terra curto, gatilho na borda de descida do CS. Para cada taxa pedida, meça o **período** do CS e a **largura** do nível baixo. A 100 kS/s o período é de 10,00 µs; a 130 kS/s, de 7,69 µs. Se, ao pedir 200 ou 500 kS/s, o período **para de diminuir** perto de ~7 a 8 µs, o limite é o quadro da PRU: anote quanto dura cada parte (CS baixo ≈ 2 µs de setup + ~2,9 µs de 32 bits de SCLK + 1 µs de hold; CS alto ≥ 1 µs; o datasheet pede tACQ ≥ 1,15 µs de CS alto e SCLK de até 17 MHz, ou seja, o ADC aguentaria um quadro de ~2 µs).

**Método 4: reduzir os atrasos do CS (firmware de out/2026).** Os três atrasos (2/1/1 µs) são ~57 % de cada amostra; o datasheet pede 30/10/30 ns (tabela 7.6), e a conversão (≤ 850 ns) já termina durante os 16 bits de comando (1,6 µs). Com o mesmo tom de 10 kHz, compare a **qualidade** com os atrasos reduzidos na taxa de trabalho e depois o **limite**:

```bash
for cs in 200,100,100 100,50,50 50,25,25 20,10,10 5,3,3; do
  sudo ./ler_adc 100000 1 --duracao 20s --atraso-cs $cs -o T7e_cs_${cs//,/_}_100k.bin -t "T7e cs $cs 100k"
  sudo ./ler_adc 250000 1 --duracao 20s --atraso-cs $cs -o T7e_cs_${cs//,/_}_250k.bin -t "T7e cs $cs 250k"
done 2>&1 | tee -a T7e_saida_atraso_cs.txt
```

Em cada captura, o `ler_adc` imprime a **taxa real medida** e o número de **amostras atrasadas** (0 = a PRU acompanhou). Rode o `medir_captura.py` nas de 100 kS/s: ruído, SINAD/ENOB, THD e continuidade têm de ficar iguais aos de `200,100,100`. O menor conjunto que mantém tudo isso, com uma margem (o dobro, por exemplo), é o candidato a novo padrão; a 250 kS/s ele mostra o novo teto. Até ser validado assim, capturas com atrasos reduzidos são **experimentais**.

**Método 3: separar o lado ARM.** Repita o ponto de 130 kS/s (e o de 100 kS/s) (a) gravando em disco, (b) gravando em RAM (`-o /dev/shm/T7e_ram.bin`, 2,6 MB) e (c) com o disco ocupado (`scp` grande em outra janela). Se só (c) gerar eventos de continuidade, o gargalo é de I/O do ARM; se (a), (b) e (c) derem o mesmo, não é o ARM.

**Como ler.**

| Observação | Gargalo provável | Melhoria (ver `melhorias-propostas.md`) |
|---|---|---|
| `fs_real` **satura** (~130 kS/s) e o período do CS para de diminuir; continuidade OK; o `ler_adc` acusa amostras atrasadas | Tempo fixo do quadro da PRU (atrasos do CS e bits do SPI) | F2 (atrasos do CS, método 4) e F3 (SPI) |
| `fs_real` = pedida, mas o `ler_adc` acusa buffers sobrescritos, mais com disco ocupado | Escrita/CPU do ARM | R1 (cartão/disco) e F6 |
| `fs_real` = pedida, sem eventos, mas ruído sobe com a taxa | Acoplamento digital-analógico ou tempo de aquisição do ADC | H1, H2 |

**Anote.** Para cada taxa: `fs_real`, eventos, tudo o que o `ler_adc` escreveu no terminal (`T7e_saida_ler_adc.txt`) e o `dmesg`; a taxa a partir da qual o resultado deixa de ser confiável.

**Para o relatório.** Figura: `fs_real` × taxa pedida (a "joelheira" no limite); tabela de eventos por taxa e por condição de carga; o período do CS e a anatomia do quadro; a conclusão sobre o gargalo e a taxa que seria necessária (≥ 300 kS/s) para cobrir a banda até 150 kHz.

**Para o relatório (geral do T7).** Tabela taxa × canais × duração × nº de eventos × maior salto. É a evidência do requisito de "não corromper os dados medidos".

### T8: aliasing

**Objetivo.** Quanto de um sinal **acima** de Nyquist dobra para dentro da banda, dado o anti-aliasing embutido (e fraco) do ADC.

**Sinal.** Senoides de **20 Vpp** (a amplitude máxima do gerador) em frequências **acima** de Nyquist a **100 kS/s** (Nyquist 50 kHz): 60, 75, 90, 120 e 130 kHz. Cada uma aparece em `|f − k × 100 kHz|`: 40, 25, 10, 20 e 30 kHz. Leia no osciloscópio o RMS real de cada tom na entrada do divisor (o gerador cai de amplitude em alta frequência).

```bash
sudo ./ler_adc 100000 1 --blocos 2 -o T8_f120k.bin -t "T8 120kHz alias 20k"
```

```fish
uv run scripts/medir_captura.py lab/2026-10-20/T8_f120k.bin --freq 20000 --referencia-rms 7.07 --sem-correcao-sonda --ganho $GV --csv lab/2026-10-20/resultados.csv
```

(`--freq` é a frequência **onde o tom aparece** depois do dobramento; `--referencia-rms` é a leitura do osciloscópio do tom real de 120 kHz, na entrada do divisor.)

**Esperado.** `erro_amplitude_pct` entre −87% e −99%, segundo a atenuação do filtro de 15 kHz na frequência **real** do tom (estimativa entre dois polos reais e Butterworth):

| Frequência real | Aparece em | Atenuação esperada | Resíduo na banda |
|---|---|---|---|
| 60 kHz | 40 kHz | −18 a −24 dB | 12 a 8% |
| 75 kHz | 25 kHz | −21 a −28 dB | 9 a 4% |
| 90 kHz | 10 kHz | −24 a −31 dB | 6 a 3% |
| 120 kHz | 20 kHz | −29 a −36 dB | 3,5 a 1,5% |
| 130 kHz | 30 kHz | −30 a −38 dB | 3 a 1,3% |

Ou seja, **de 1 a 12% do sinal de entrada aparece como um falso tom na banda**, e a **correção de perfil piora**: ela amplifica o falso tom pelo ganho da frequência aparente. Um conversor chaveado em 120 kHz com 1 V de ondulação deixaria ~30 mV de "supraharmônico" em 20 kHz.

**Para o relatório.** Tabela: frequência real × frequência aparente × rejeição (dB). A conclusão de projeto: com no máximo 100 kS/s e o filtro de 15 kHz, as emissões de 50 a 150 kHz **não** podem ser medidas nem separadas das de 0 a 50 kHz: é preciso (a) uma taxa maior, depois de resolvido o gargalo (T7e), ou (b) um filtro anti-aliasing externo mais forte.

### T9: sinais de espectro conhecido

**Objetivo.** Conferir o **pipeline** de supraharmônicos (FFT, Welch, picos, correção) contra espectros que se sabe calcular de antemão. Capture todos a 100 kS/s, 1 canal (canal 1, com `--ganho $GV` e o perfil `cadeia_tensao` do T3), e compare com a teoria e com o osciloscópio. **Cuidado com o aliasing:** acima de 50 kHz tudo dobra (T8), então a comparação vai só até ~30 kHz.

**T9a: onda quadrada.** **2 kHz**, 50% de ciclo, 20 Vpp (10 V de pico no gerador, sem offset). Os harmônicos ímpares têm amplitude de pico `4A/(nπ)`: −9,54 dBc (3ª, 6 kHz), −13,98 (5ª, 10 kHz), −16,90 (7ª, 14 kHz), −19,08 (9ª, 18 kHz), −20,83 (11ª, 22 kHz), −22,28 (13ª, 26 kHz), −23,52 dBc (15ª, 30 kHz). Além da 15ª, os harmônicos de 17ª a 25ª (34 a 50 kHz) ficam contaminados pelos harmônicos acima de Nyquist que dobram (a 100 kS/s, a 35ª, de 70 kHz, cai em 30 kHz, por exemplo): a conta mostra um erro de até ±0,7 dB na 15ª e menos de 0,2 dB até a 9ª. Um ciclo de trabalho fora de 50% (o gerador tem ~1% de erro) cria harmônicos pares: use isso como teste.

```bash
sudo ./ler_adc 100000 1 --blocos 4 -o T9a_quadrada_2k.bin -t "T9a quadrada 2k" --grandeza 1:tensao --sonda 1:cadeia_tensao
```

```fish
# sem correção da cadeia (o que o ADC "vê") e com a correção do perfil do T3
uv run scripts/medir_captura.py lab/2026-10-20/T9a_quadrada_2k.bin --freq 2000 --harmonicos 15 --sem-correcao-sonda --ganho $GV --rotulo "T9a sem correcao" --csv lab/2026-10-20/resultados.csv
uv run scripts/medir_captura.py lab/2026-10-20/T9a_quadrada_2k.bin --freq 2000 --harmonicos 15 --ganho $GV --rotulo "T9a com perfil" --csv lab/2026-10-20/resultados.csv
uv run scripts/adc_tool.py lab/2026-10-20/T9a_quadrada_2k.bin --welch --picos -70 --filtro-passa-alta 500 --ganho $GV -o lab/2026-10-20/fig_T9a.png
```

**Esperado.** Sem correção, os harmônicos altos saem **bem abaixo** da teoria (o filtro: a 15ª, em 30 kHz, ~−9 a −12 dB abaixo do que seria). Com o perfil do T3, os níveis relativos devem bater com a teoria em ~1 dB até a 15ª harmônica (30 kHz). É a demonstração mais convincente de que o perfil funciona. Compare com a FFT do osciloscópio (mesma janela de tempo).

**T9b: dois tons e resolução.** 20,0 kHz e 20,3 kHz, mesma amplitude, somadas pela função *Combine* do SDG1032X (CH1 + CH2) ou com dois resistores de 1 kΩ (cada tom fica com metade da amplitude do gerador). Com o gerador a 20 Vpp em cada canal e a soma resistiva, saem 5 V de pico por tom no nó (0,26 V no pino, −32 dBFS). O Welch com `--resolucao-welch 200` não separa; com `--resolucao-welch 50` separa. Mede o limite de resolução do método. Produtos de intermodulação (19,7 e 20,6 kHz) mostram a linearidade.

**T9c: fundamental forte e supraharmônicos fracos.** O caso real: **60 Hz** a ~9 V de pico no gerador (18 Vpp; 0,47 V no pino) somado a 9 kHz em −60 dBc (9 mV de pico), 25 kHz em −50 dBc (28 mV) e 40 kHz em −40 dBc (90 mV). Gerador arbitrário de 2 canais ou dois geradores com somador resistivo. Os tons fracos têm 1,5 a 15 LSB de pico no pino (9 a 90 mV de pico na entrada do divisor, onde 1 LSB vale 6 mV): só aparecem na FFT porque o ganho de processamento deixa o ruído por bin em ~7 µV na entrada. **Meça cada fonte sozinha** no osciloscópio (em amplitude maior) para saber os níveis reais; depois some. O DAC do gerador tem 14 bits (1,2 mV de passo em 20 Vpp): confira que a soma não distorce.

```fish
uv run scripts/adc_tool.py lab/2026-10-20/T9c.bin --welch --janela hann --filtro-passa-alta 2000 --picos -100 --ganho $GV -o lab/2026-10-20/fig_T9c_welch.png
uv run scripts/adc_tool.py lab/2026-10-20/T9c.bin --fft --janela hann --ganho $GV -o lab/2026-10-20/fig_T9c_fft.png
```

**Esperado.** Os três tons são vistos acima do piso; sem a correção da cadeia, o de 40 kHz sai ~12 a 17 dB abaixo do injetado. Anote o **menor tom detectável** (10 dB acima do piso) em cada frequência: é o limite de detecção do sistema.

**T9d: modulação em frequência (dithering).** Portadora **senoidal** de 20 kHz com FM de ±1 kHz a 100 Hz (os harmônicos de uma quadrada dobrariam, T8): espalha a energia em torno de 20 kHz. Compare `--fft --freq-min 19000 --freq-max 21000` (borra) com `--welch` (média) e `--agrupar-bandas 200`. A FM não muda a potência da portadora: o RMS lido **na entrada** (osciloscópio) deve ser o mesmo com e sem modulação. No ADC, o filtro de 15 kHz pesa de forma diferente os componentes espalhados, então compare o `rms_ca` das duas capturas (com e sem modulação) **com a correção do perfil** e aceite ±2%.

**T9e (opcional): distúrbio momentâneo.** Salva de 10 kHz com 5 ms ligados a cada 100 ms: use `adc_tool.py captura.bin --inicio N --fim M --fft --freq-min 9000 --freq-max 11000` para isolar uma salva e `--fft 10 --freq-min 9000 --freq-max 11000` (os 10 primeiros ciclos). O `--fft` procura a fundamental entre 45 e 65 Hz por padrão: sem `--freq-min/--freq-max` ele não acha um tom de 10 kHz.

**Para o relatório.** Figuras sobrepostas "teoria × ADC (sem correção) × ADC (com perfil) × osciloscópio" para a quadrada; o menor tom detectável do T9c; os espectros do T9d.

### T10: perfil da sonda de corrente

**Objetivo.** Medir a resposta em frequência da **sonda mais a cadeia de aquisição** (SCT013 + resistor de 0,12 Ω + resistores em série + ADS8688, com o capacitor removido) do canal de produção, gerar `scripts/sondas/<id>.json` e **validar** o perfil em frequências que não entraram nele. É o objetivo central do projeto.

**Regras de ouro.**

1. **Mesmo canal e mesmo `--ganho` (`$GI`)** que você usará em produção, **e a faixa de ±2,56 V (`--faixa-adc 0:5.12`)**, que é a que dá mais resolução a esse sinal. O ganho em volts no pino não depende da faixa (o cabeçalho a registra e as ferramentas convertem sozinhas), mas o ruído depende: use a de produção. O perfil só vale para essa cadeia (o `adc_tool.py` e o `medir_captura.py` avisam se o `--ganho` divergir).
2. **Um canal só**, taxa de **100 kS/s** (Nyquist 50 kHz, taxa exata; ver T4). Com `--freq-max 45k` você cobre de 50 Hz até 90% de Nyquist. Acima de 50 kHz é impossível (aliasing, T8): isso é uma limitação do projeto a declarar.
3. **A corrente de referência vem da ponta TCP0030A** (faixa de 5 A), **não** de um shunt externo nem de "tensão do gerador ÷ resistência": o resistor de 22,12 Ω é de fio enrolado (indutivo em alta frequência) e o gerador tem 50 Ω de saída, então o valor da corrente muda com a frequência e **só a ponta o mede**. A amplitude pode mudar a cada ponto: ajuste o gerador sempre ao **máximo (20 Vpp, High-Z)** para maximizar o sinal.
4. **A referência é "N × I"** (ampère-espira): o SCT013 enxerga as N espiras e a TCP0030A uma só passada. O perfil sai **por ampère de corrente primária de 1 espira**, que é o uso em produção (condutor passando uma vez pela garra).

**Montagem.**

```text
SDG1032X (High-Z, 20 Vpp) ─► resistor 10,92 Ω ─► 1 passada pela TCP0030A ─► N espiras no SCT013 ─► retorno ao gerador
                                                          │
              MSO46: TCP0030A (faixa 5 A) em A ─────────────┘          (terra do gerador, um só ponto)

SCT013 ─► placa (0,12 Ω ∥ 1,79 kΩ + 1,7929 kΩ, sem o capacitor) ─► canal 0 do ADC (BeagleBone)
```

* O resistor de 10,92 Ω (derivação central do de 22,12 Ω) limita a corrente a ~164 mA de pico (116 mA RMS): `I_pico ≈ V_pico(aberto) ÷ (50 Ω + R)`. Dá para usar o de 22,12 Ω (98 mA RMS) ou os dois em paralelo (~116 mA RMS). **Não** ultrapasse 4,2 A por resistor (só importa na rede).
* **Várias espiras no SCT013 (N = 10 de início; 20 se o SNR faltar).** O sinal do SCT013 por espira é de 60 µV/A (fato 5): com 116 mA RMS e N = 10, são ~70 µV RMS no pino (0,9 LSB em ±2,56 V). Passe o fio N vezes **no mesmo sentido**, centrado e fixo com fita; confira que o resultado **não** depende de N (veja a linearidade abaixo): se depender em alta frequência, a capacitância e a indutância entre espiras estão atrapalhando.
* **TCP0030A:** aqueça 20 minutos, **desmagnetize (DEGAUSS) e faça o zero** com o condutor **fora** da garra, depois feche a garra no fio, no sentido da seta. Com 116 mA RMS ela está em 2% da faixa de 5 A: use média de 16 ou mais aquisições (ou Hi-Res), limite de banda de 20 MHz ou menos e RMS de ciclos inteiros, e anote o ruído dela sem corrente (é o piso da sua referência).
* O SCT013 é um **transformador** (só AC; não há zero a fazer) e o secundário **não pode ficar aberto** (fio solto da placa) com corrente no primário.
* Mantenha o laço de corrente pequeno: cada microhenry de laço a 45 kHz vale ~0,3 Ω, o que só limita a corrente (somado aos 50 Ω do gerador) e **não** afeta o resultado, porque a corrente real é medida na TCP0030A.

**T10-0: o sinal é suficiente? (15 minutos, antes da coleta)**. Confirma a premissa de 60 µV/A e escolhe N. Em 1 kHz e 20 Vpp, N = 10, capture 2 blocos e compare com a TCP0030A (RMS em A lido no osciloscópio, multiplicado por N):

```bash
sudo ./ler_adc 100000 0 --faixa-adc 0:5.12 --blocos 2 -o T10_0_1k_N10.bin -t "T10-0 1kHz N10" --grandeza 0:corrente
```

```fish
# --referencia-rms = N x I_rms da TCP0030A. Exemplo: N=10, 116 mA -> 1.16
uv run scripts/medir_captura.py lab/2026-10-20/T10_0_1k_N10.bin --sem-correcao-sonda --ganho $GI --freq 1000 --referencia-rms 1.16
```

**Esperado.**

* A ferramenta **acha o tom** em 1 kHz (ela só aceita um pico que esteja ≥ 20 dB acima da mediana do espectro; sem isso, imprime "nenhum tom" e o sinal está abaixo do aceitável).
* `erro_amplitude_pct` perto de **0% (dentro de ±20%** nesta checagem rápida; o objetivo é só confirmar a sensibilidade, o perfil refina isso).
* **Ignore o `snr_db` deste comando:** ele é a potência do tom contra **todo** o ruído da banda de 0 a 50 kHz. Com 70 µV de tom e ~61 µV de ruído de banda larga (faixa de ±2,56 V) ele sai **perto de 0 dB** (~ +1 dB; seria ~ −9 dB em ±10,24 V), e isso é normal. O que decide é o SNR **por bin**, que você calcula assim: `20·log10( amplitude_rms ÷ (densidade_ruido_por_rthz × √resolução) )`, com a `resolução espectral` que a saída imprime (≈ 0,05 Hz com 2 blocos). Esperado: **~55 dB ou mais** em 1 kHz (~46 dB se a captura ficar em ±10,24 V). Mínimo para seguir: **30 dB**.
* Se o `erro_amplitude_pct` for de dezenas de vezes (amplitude medida ≈ 0,02× ou 50× a referência), a premissa "0,12 Ω sobre 2000:1" está errada (outro resistor de carga, ou ganho antes do ADC): refaça `$GI` com `GI_real = $GI ÷ razão_medida_sobre_esperada` e a conta dos fatos 4 e 5.
* Se o SNR por bin for menor que 30 dB, aumente N (até 20), use 4 blocos e procure fontes de ruído (T1).
* Repita com N = 5 e N = 20: a razão medida ÷ referência deve ser **constante dentro de ~3%** (a medida **não** pode depender de N).

**Passo 1: coletar (na BeagleBone).** 24 pontos, 2 repetições, 4 blocos por captura (≈ 42 s: o dobro de tempo é 3 dB de SNR; veja a conta abaixo):

```bash
cd firmware
sudo ./calibrar_sonda.sh --taxa 100000 --canal-sonda 0 --pontos 24 --freq-max 45k \
    --blocos 4 --repeticoes 2 --sonda sct013_100a_sn001 --ref-externa --faixa-adc 5.12
```

O `--faixa-adc 5.12` coloca o canal da sonda em ±2,56 V; vale para todo o plano (fica em `plano_coleta.txt`) e o script confere, em cada captura, se o cabeçalho registrou o código pedido. Em cada ponto: ajuste a frequência no gerador (20 Vpp, High-Z), espere estabilizar, **leia o RMS da corrente na TCP0030A** (A, RMS de ciclos inteiros, com média), aperte ENTER para medir e digite o valor **em ampères, da ponta (uma passada)** quando o script perguntar (ex.: `0.1162` ou `116.2m`; o script escreve "tensão no shunt, em V": aqui é a corrente em A, e o N entra depois, em `--resistencia-shunt`).

* **O script vai dizer "praticamente sem sinal no canal da sonda" em todos os pontos.** O limiar dele é 0,2% da escala (~10 mV pico a pico em ±2,56 V; ~41 mV em ±10,24 V) e o seu sinal tem dezenas de µV: é esperado e **não** invalida a captura. **Digite `C`** para aceitar (a sugestão do menu, neste caso, é `R`: apertar só ENTER refaz o ponto). A captura fica registrada com `aceito_com_erro_qc_sem_sinal_sonda` no manifesto e o `gerar_perfil_sonda.py` a usa normalmente (ele mede a frequência e a amplitude por FFT, que enxerga tons abaixo de 1 LSB). Os campos "frequência medida" e "ganho relativo" que o script mostra, calculados por métodos rápidos sobre ruído, **não valem** aqui.
* O script confere cabeçalho, CRC e tamanho do arquivo, que valem sim. Depois da primeira rodada, use `--modo refinar --pontos 4` para acrescentar pontos onde o ganho mais varia (ressonâncias do SCT013 em alta frequência) e `--modo adensar` se a curva for acidentada. Mais detalhes em [`guia_de_uso.md`](guia_de_uso.md#sondas-de-corrente-calibração-e-correção).

**Quanto sinal sobra (ordem de grandeza, ruído branco do ADC, N = 10 e 116 mA RMS, faixa de ±2,56 V).** Tom de 70 µV em 1 kHz: ~55 a 57 dB acima do ruído por bin com 10 s (erro de amplitude por ruído ~0,2%); em 20 kHz (−4 dB do filtro): ~51 dB (0,3%); em 40 kHz (−17 dB): ~38 a 40 dB (1%); com 4 blocos (42 s) cada ponto ganha ~6 dB (em 40 kHz: ~0,6%). Em ±10,24 V seriam 9 dB a menos (46 a 48; 42; 29 a 31 dB; erros de 0,5%; 0,8%; 3%). Interferência real (60 Hz e harmônicos, rádio) vai piorar isso: o `gerar_perfil_sonda.py` avisa quando o tom de um ponto não passa 20 dB acima do piso por bin; refaça esses pontos com mais blocos ou mais espiras.

**Passo 1b: variante com `.m` do osciloscópio.** Em vez de digitar o RMS, salve a forma de onda da TCP0030A (em A) de cada ponto como `.m` (ou `.mat`/`.csv`) com o **mesmo nome base da captura** (`calibracao_1000Hz_rep1.m`), com pelo menos 10 ciclos e 20 amostras por ciclo. O `calibrar_sonda.sh` é o mesmo comando do passo 1, **sem** `--ref-externa` (nesse modo ele não pede nenhum valor a cada ponto: só captura; ou use `--ref-externa` e salve também o `.m`, para ter as duas referências e poder compará-las). A amplitude de cada `.m` entra no passo 2, com `--referencia-osciloscopio` no lugar de `--referencia-externa`. A amplitude de referência vem do ajuste de senoide por mínimos quadrados (IEEE 1057), que usa todos os ciclos e é melhor que o RMS lido do painel.

**Passo 1c: amplitude "conhecida" não se aplica aqui** (a corrente não é `V_gerador ÷ R`: o resistor de fio enrolado e os 50 Ω de saída deixam o valor dependente da frequência). Só use `--amplitude ...Apk` se tiver medido a corrente na TCP0030A numa frequência e souber que o gerador é plano. Em **tensão** o método vale, e a variante do T3 já usa esse raciocínio.

**Conferir o método (uma medição com amplitude conhecida e `.m`).** Antes da coleta completa, ou com uma captura que você já tenha, verifique se o método devolve a amplitude certa:

```fish
# SEM correção: ADC/osciloscópio mostra o ganho do conjunto nessa frequência, com a corrente real vinda do .m da TCP0030A (A)
uv run scripts/medir_captura.py captura.bin --sem-correcao-sonda --osciloscopio captura.m --osc-unidade A --osc-escala 10 --ganho $GI --rotulo "metodo 12kHz" --csv lab/2026-10-20/resultados.csv
```

(`--osc-escala 10` = N espiras: o valor do osciloscópio é multiplicado por 10.) Com o perfil pronto, repita **com** a correção: ADC ÷ osciloscópio deve dar ~1 numa frequência que não entrou na calibração.

**Linearidade (faça no meio da coleta).** Em 1 kHz, capture 5 amplitudes (gerador em 2, 5, 10, 15 e 20 Vpp; o SNR cai nas menores) e 3 valores de N (5, 10, 20): o ganho **não** pode depender da amplitude nem de N. Se depender da amplitude, o SCT013 satura ou o resistor aquece.

**Ponto de 60 Hz com a corrente da rede (opcional, com supervisão).** Com transformador de isolamento, **127 V** sobre os **dois resistores de 22,12 Ω em série** (44,24 Ω) dá **2,87 A RMS** (cada resistor com 63,5 V e 182 W, dentro dos 93 V e 400 W). Fio **uma só vez** (N = 1, a configuração de produção) pela TCP0030A (ainda na faixa de 5 A, exatidão de ±1% a 60 Hz) e pelo SCT013: o sinal é de 172 µV RMS (0,55 LSB), ~55 dB acima do ruído por bin. É o melhor ponto de ancoragem do ganho em baixa frequência. **Nunca 220 V** (110 V por resistor, acima dos 93 V) e confira o aquecimento.

**Passo 2: gerar o perfil (no computador).** Copie `capturas/sct013_100a_sn001/` (e os `.m` do osciloscópio, se houver) e rode:

```fish
uv run scripts/gerar_perfil_sonda.py capturas/sct013_100a_sn001 --referencia-externa \
    --resistencia-shunt 0.1 --ganho $GI --formato uint16 \
    --fabricante "YHDC" --modelo "SCT013 100A:50mA" --numero-serie "SN001" --plot
```

(`--resistencia-shunt` é `1 ÷ N`: com N = 10 a "tensão" digitada, que na verdade é a corrente em A da TCP0030A, vira `N × I`. `--ganho` é o do **canal da sonda**, o mesmo da produção. Para o `.m` por captura, troque por `--referencia-osciloscopio --osc-unidade A --osc-escala 10`.) O script mede a frequência e a amplitude de cada captura, calcula `ganho = amplitude da sonda ÷ corrente de pico` (com `corrente de pico = √2 × I_RMS × N`), agrega as repetições e grava o `.json`. Atenção aos avisos: repetições que divergem mais de 10% (remeça o ponto, com mais blocos), SNR baixo (esperado em 40 a 45 kHz), ganho na menor frequência fora de [0,7; 1,3] (o `$GI` provavelmente não é 1/sensibilidade nominal: ajuste-o e refaça o perfil).

**Passo 3: validar em frequências que ficaram de fora (hold-out).** Escolha 4 a 6 frequências **que não estão** no perfil e que ficam entre pontos: por exemplo 330 Hz, 3,3 kHz, 12 kHz, 27 kHz e 41 kHz. Em cada uma, capture **registrando a sonda no cabeçalho** (para a correção ser automática) e leia a corrente na TCP0030A:

```bash
sudo ./ler_adc 100000 0 --faixa-adc 0:5.12 --duracao 40s -o H_27kHz.bin -t "H 27kHz" --grandeza 0:corrente --sonda 0:sct013_100a_sn001
```

```fish
# --referencia-rms = N x I_rms da TCP0030A. Exemplo: N=10 e 112 mA -> 1.12
uv run scripts/medir_captura.py lab/2026-10-20/H_27kHz.bin --ganho $GI --freq 27000 --referencia-rms 1.12 --rotulo "H 27kHz" --csv lab/2026-10-20/resultados.csv
```

O `erro_amplitude_pct` do CSV é o erro do **sistema corrigido** contra a TCP0030A, nas frequências de validação. Repita com `--sem-correcao-sonda` para mostrar o quanto a correção melhora.

**Esperado.** Sem correção, o erro em 40 kHz será de dezenas de % (filtro do ADC mais a banda do SCT013). Com correção, deve cair para **poucos %**, limitado por: exatidão da TCP0030A (±1,5% até 5 kHz e **sem especificação** acima: some a incerteza do osciloscópio de ±1%), SNR (~0,2% até 20 kHz e ~1% em 40 kHz em ±2,56 V), interpolação entre pontos (0,17% com 18 pontos, 0,06% com 25, para curvas suaves; ver [`auditoria_perfil_sonda.md`](auditoria_perfil_sonda.md)) e repetibilidade (o desvio entre repetições aparece no próprio perfil). A correção restaura a **amplitude**, não a fase: não use o canal corrigido para potência por componente.

**Comparar as referências (para o relatório).** Gere o perfil pela leitura digitada e pelo `.m` (`-o scripts/sondas/x_digitado.json` e `-o scripts/sondas/x_osc.json`) e compare os ganhos ponto a ponto: a diferença em dB por frequência é a incerteza de leitura do RMS do painel. Para o **perfil de tensão** (T3), compare também a amplitude conhecida (1,0332 Vpp) com o osciloscópio: a diferença é a planura do gerador somada ao erro de amplitude do painel, ou seja, o quanto a "amplitude conhecida" é confiável sem osciloscópio.

**Piso de detecção (para o relatório).** O ruído do ADC visto pelo canal de corrente, na faixa de ±2,56 V, é de ~1,8 mA por bin de 0,1 Hz numa captura de 10 s com 1 espira (~12 mA em 40 kHz, depois de desfazer o filtro) e de ~70 mA numa banda de 200 Hz (em ±10,24 V seriam ~5 mA, ~35 mA e ~0,2 A). Calcule os seus números com o `ruido_rms_lsb` do T1 e com o ganho do perfil em cada frequência: é o que diz se supraharmônicos de corrente de miliampères são mensuráveis com a placa atual, ou se são necessários mais ganho antes do ADC ou um resistor de carga maior (a faixa de entrada de ±2,56 V, a menor do ADC, já está em uso).

**Para o relatório.** A curva do perfil (PNG do `--plot`) com os pontos e as barras de desvio; o resumo da resposta do conjunto (−3 dB, inclinação, amplificação de ruído); a tabela de validação (frequência, corrente de referência, corrente medida sem e com correção, erro %); o teste de linearidade (amplitude e N); a comparação entre referências; o orçamento de incerteza (TCP0030A, osciloscópio, SNR, interpolação, repetibilidade); o piso de detecção.

### T11: ponta a ponta

**Objetivo.** Medir um sinal **parecido com o real** com o sistema completo (sonda corrigida, tensão corrigida, pipeline de análise) e compará-lo com o osciloscópio.

**T11a: tensão composta (com gerador).** Cinco tons simultâneos na entrada do divisor, somando no máximo 20 Vpp: **60 Hz** (12 Vpp), **2 kHz** (3 Vpp), **9 kHz** (1 Vpp), **20 kHz** (0,3 Vpp) e **40 kHz** (0,1 Vpp), total de 16,4 Vpp. Monte a soma com uma forma de onda arbitrária no gerador, ou com a função **Combine** dos dois canais do SDG1032X (a mesma do T9b). Procedimento:

1. Meça **cada tom sozinho** no nó de entrada do divisor (RMS no osciloscópio; o Fluke 289 para 60 Hz e 2 kHz) e anote. Valores nominais (V RMS): 4,243; 1,061; 0,354; 0,106; 0,035. **Use o que você mediu**, não o nominal.
2. Ligue **todos juntos** e capture 1 canal a 100 kS/s, 4 blocos, com a tensão e a sonda registradas no cabeçalho.
3. Em paralelo, grave no osciloscópio a mesma forma de onda (para a figura "forma de onda × ADC") e use a FFT dele.

```bash
sudo ./ler_adc 100000 1 --blocos 4 -o T11a.bin -t "T11a tensao composta" --grandeza 1:tensao --sonda 1:cadeia_tensao
```

```fish
# Espectro com a correção da cadeia de tensão (picos até -90 dB)
uv run scripts/adc_tool.py lab/2026-10-20/T11a.bin --welch --janela hann --filtro-passa-alta 20 --picos -90 --ganho $GV -o lab/2026-10-20/fig_T11a.png

# Um comando por tom: --freq escolhe o tom (busca em ±10%) e --referencia-rms é o RMS medido SOZINHO (V no nó de entrada)
uv run scripts/medir_captura.py lab/2026-10-20/T11a.bin --freq 60    --referencia-rms 4.24  --ganho $GV --rotulo "T11a 60Hz"  --csv lab/2026-10-20/resultados.csv
uv run scripts/medir_captura.py lab/2026-10-20/T11a.bin --freq 2000  --referencia-rms 1.06  --ganho $GV --rotulo "T11a 2kHz"  --csv lab/2026-10-20/resultados.csv
uv run scripts/medir_captura.py lab/2026-10-20/T11a.bin --freq 9000  --referencia-rms 0.354 --ganho $GV --rotulo "T11a 9kHz"  --csv lab/2026-10-20/resultados.csv
uv run scripts/medir_captura.py lab/2026-10-20/T11a.bin --freq 20000 --referencia-rms 0.106 --ganho $GV --rotulo "T11a 20kHz" --csv lab/2026-10-20/resultados.csv
uv run scripts/medir_captura.py lab/2026-10-20/T11a.bin --freq 40000 --referencia-rms 0.035 --ganho $GV --rotulo "T11a 40kHz" --csv lab/2026-10-20/resultados.csv
```

(Confira que a coluna `correcao_sonda` do CSV está `sim`: se estiver vazia, o perfil `cadeia_tensao` não foi achado em `scripts/sondas/` ou a captura não registrou `--sonda 1:cadeia_tensao`. Rode também com `--sem-correcao-sonda` para mostrar o efeito da correção.)

**Esperado.** Cada tom com erro de poucos % contra o valor medido sozinho (o de 40 kHz é o mais sensível: a correção ali amplifica ~17 dB, junto com o ruído), e **nenhum pico espúrio** fora dos tons injetados e de seus harmônicos (intermodulação e aliasing aparecem como picos extras: veja onde caem).

**T11b: corrente composta (só se o T10-0 e o T10 deram SNR suficiente).** Dois tons de corrente pelo SCT013 com N = 10, do mesmo circuito do T10 (resistor de 10,92 Ω): **1 kHz** (12 Vpp no gerador, ~70 mA RMS) e **20 kHz** (8 Vpp, ~46 mA RMS), somados pelo Combine ou por forma arbitrária. Meça **cada tom sozinho** na TCP0030A (RMS × N) e depois os dois juntos, **só o canal 0**, a 100 kS/s:

```bash
sudo ./ler_adc 100000 0 --faixa-adc 0:5.12 --blocos 4 -o T11b.bin -t "T11b corrente composta" --grandeza 0:corrente --sonda 0:sct013_100a_sn001
```

```fish
# --referencia-rms = N x I_rms do tom medido sozinho (aqui N=10: 70 mA -> 0.70 e 46 mA -> 0.46)
uv run scripts/medir_captura.py lab/2026-10-20/T11b.bin --freq 1000  --referencia-rms 0.70 --ganho $GI --rotulo "T11b 1kHz"  --csv lab/2026-10-20/resultados.csv
uv run scripts/medir_captura.py lab/2026-10-20/T11b.bin --freq 20000 --referencia-rms 0.46 --ganho $GI --rotulo "T11b 20kHz" --csv lab/2026-10-20/resultados.csv
```

Mesmo critério do T11a, com o SNR por bin do T10 (cada tom precisa de ≥ 30 dB acima do piso). Aqui N = 10 serve só para ter sinal: com N = 1 (o uso real) os tons ficam 20 dB mais fracos (veja o piso de detecção do T10).

**T11c: carga real (opcional, exige supervisão).** Uma carga chaveada (fonte de computador, carregador, driver de LED, dimmer) na rede de **127 V** (nunca 220 V: o divisor satura), com **transformador de isolamento** e o osciloscópio isolado. Capture 10 s no canal de tensão e compare a lista de picos do `--welch --picos` (com a correção) com a FFT do osciloscópio nos mesmos picos (frequência e amplitude): a frequência de chaveamento e seus primeiros harmônicos, **até 45 kHz**. É o teste mais próximo do uso real. A corrente da carga também pode ser capturada (SCT013 com 1 espira, canal 0), mas os supraharmônicos de miliampères ficam **abaixo do piso** (ver T10): só os de 60 Hz e seus primeiros harmônicos aparecem; registre isso.

**Para o relatório.** Tabela dos tons de T11a e T11b (valor injetado, medido, erro %); figura com os espectros ADC × osciloscópio de T11c.

---

## Dados e figuras para o relatório

| Item | Origem |
|---|---|
| Foto da bancada e diagrama de ligações de cada teste; lista de instrumentos com modelo, exatidão e data da última calibração; valor do capacitor removido | Todos |
| Escala do ADC conferida nas três faixas (razão `media` ÷ `V_in × 0,05157`) | T0 |
| Ruído em LSB, µV e nV/√Hz × taxa e nº de canais; **ruído × faixa de entrada**; PSD do curto; ruído equivalente na entrada de cada cadeia | T1 |
| Razão real do divisor e offset; resíduo de linearidade em LSB | T2 |
| **Perfil da cadeia de tensão** (dB × Hz, −3 dB) e o ajuste do passa-baixa (K, f0, Q, resíduos): `relatorio/gerar_figuras.py` | T3 |
| Erro da taxa de amostragem (ppm) × taxa pedida | T4 |
| SINAD/ENOB × nível; THD, SINAD e SFDR × frequência; faixa dinâmica | T5 |
| Diafonia e atraso entre canais | T6 |
| Tabela de continuidade (eventos, salto máximo) por taxa e carga; deriva em 10 min | T7 |
| **Taxa real × taxa pedida (limite de ~130 kS/s), período do CS, gargalo** | T7e |
| Rejeição de aliasing × frequência (e o que sobra do 50–150 kHz) | T8 |
| Quadrada: teoria × ADC × perfil × osciloscópio; menor tom detectável; resolução de dois tons | T9 |
| **Perfil da sonda de corrente** (curva, pontos, desvios); validação hold-out (erro % com e sem correção); linearidade (amplitude e N); piso de detecção | T10 |
| Tons compostos e carga real: ADC × osciloscópio | T11 |
| `resultados.csv` de cada dia, os `.bin` (arquivar sem perdas com `uv run scripts/compactar_amostras.py PASTA_DO_DIA`: ~11 % do tamanho, conferido pelo SHA-256) e os prints do osciloscópio | Todos |

**Sugestão de estrutura:** uma tabela "requisito do projeto → teste → resultado → critério" com os testes T7 (não perder dados e limite de taxa), T10 (perfil da sonda), T3 (banda de supraharmônicos de tensão) e T11 (ponta a ponta).

**Declare no relatório** as limitações que você encontrou: a taxa máxima de 100 kS/s (130 kS/s medido) e, com ela, a banda coberta (até 45 kHz de 150 kHz) e o aliasing do que está acima; o filtro de 15 kHz do ADC e sua correção (que amplifica o ruído); a baixa sensibilidade do canal de corrente (60 µV/A) e o piso de detecção resultante (mesmo na menor faixa do ADC, ±2,56 V); a faixa de ±10,24 V do canal de tensão, sem margem para reduzir (127 V RMS = 91%); o aliasing de componentes acima de Nyquist; a taxa de amostragem real; a exatidão do osciloscópio e da TCP0030A (sem especificação acima de 5 kHz); e o fato de a correção de sonda restaurar só a amplitude (não a fase). **Sugestões de melhoria** que saem daqui: resolver o gargalo da PRU (T7e) para chegar a ≥ 300 kS/s; mais ganho (ou carga maior) antes do ADC no canal de corrente; um anti-aliasing externo mais forte.

---

## Critérios de aceitação

Os limites abaixo são **propostas** (baseadas no datasheet e em boas práticas); ajuste e justifique no relatório.

| Teste | Critério | Referência |
|---|---|---|
| T0 | Cabeçalho íntegro, tamanho do arquivo correto, sem avisos; razão da escala ≈ 1,00 (±1%) nas três faixas | Projeto |
| T1 | Ruído ≤ ~1 LSB RMS da faixa usada (no pino do ADC: ≤ ~220 µV em ±10,24 V; ≤ ~80 µV em ±2,56 V); offset ≤ ±1 mV | Datasheet (SNR ≥ 89 dB; offset máx. ±0,75 mV) |
| T2 | Erro de ganho ≤ 0,1% da faixa (limitado pelo multímetro e pelos resistores); INL ≤ 2 LSB | Datasheet (±0,05%; ±2 LSB) |
| T3 | −3 dB perto de 15 kHz; planicidade ±0,1 dB abaixo de 2,5 kHz (ADC); ganho de baixa frequência 0,998 ± 0,5% | Datasheet; projeto |
| T4 | Erro de taxa explicado pelos ticks e pelo cristal (diferença entre taxas exatas < 5 ppm) | Projeto |
| T5 | SINAD ≈ SINAD do datasheet menos o nível (−26 dBFS: ≥ 62 dB); SFDR ≥ 100 dB (se a fonte permitir) | Datasheet |
| T6 | Diafonia ≤ −90 dB (ou "melhor que" o piso); atraso entre canais = 1/taxa total ±2% | Datasheet; projeto |
| T7 | **0 eventos de continuidade** até 100 kS/s e sob carga; amplitude estável em ±0,1%. Acima: documentar `fs_real` e a taxa de saturação | Projeto (requisito de desempenho) |
| T8 | Rejeição documentada; sem exigência numérica (é uma característica do ADC) | Datasheet |
| T9 | Harmônicos da quadrada dentro de ±1 dB da teoria (com perfil) até a 15ª (30 kHz); menor tom detectável documentado | Teoria |
| T10 | Erro de validação (hold-out) ≤ 3% de 60 Hz a 20 kHz e ≤ 5% até 45 kHz (ou o melhor que o SNR e a exatidão da TCP0030A permitirem, com justificativa) | Projeto |
| T11 | Cada tom dentro de ~5% do valor de referência, sem tons espúrios | Projeto |

---

## Problemas de bancada

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Pico forte de 60 Hz e harmônicos no curto | Laço de terra (USB/rede, gerador e osciloscópio em tomadas diferentes) | Um só ponto de terra; notebook com bateria; cabos de sinal curtos e trançados; ferrite |
| Ruído muito acima de 1 LSB | Jumper longo entre a placa de aquisição e o frontend; fonte ruidosa; USB | Veja "Preparar a BeagleBone" no [guia](guia_de_uso.md); desligue o que não precisa |
| Tensão lida pela **metade** (ou o dobro) do que o Fluke mostra | `--faixa` digitado diferente da do cabeçalho (a ferramenta avisa), captura antiga (v1/v2, assume 10.24), ou escala-base do ADC diferente da suposta | Omita `--faixa` (vale a do cabeçalho); para capturas antigas use `--faixa 20.48`; refaça o T0, passo 6 |
| Amplitude no ADC o dobro (ou a metade) do esperado, só com o gerador | Gerador em 50 Ω com carga High-Z (ou o contrário) | Ajuste a carga do gerador (High-Z) e **leia o osciloscópio**, não o painel |
| `saturou o ADC` | Amplitude acima da faixa pedida (rede de 220 V; `--faixa-adc 1:10.24` com 127 V; ou o canal de corrente em ±2,56 V com sinal alto) | Reduza o sinal ou aumente a faixa (`--faixa-adc`); no canal de tensão, ±10,24 V cobre até 140 V RMS |
| `sinal fraco` em todo ponto do canal de tensão | Máximo de 5% da escala pelo divisor | Esperado; aceite com `C` |
| `praticamente sem sinal` em todo ponto do canal de corrente | Sensibilidade de 60 µV/A (limiar 0,2% da escala = ~10 mV pico a pico em ±2,56 V) | Esperado: digite `C` (ENTER refaz). Confira o SNR com o T10-0 |
| Sinal de corrente nulo (só ruído) mesmo com N = 20 | SCT013 aberto ou fora da garra; fio fora do centro; resistor de 0,12 Ω ou resistores em série dessoldados; gerador desligado | Confira a ligação com a TCP0030A; meça a tensão sobre o 0,12 Ω com o osciloscópio |
| Perfil de tensão com ganho de baixa frequência ~0,05 (em vez de ~1) | `--amplitude` em volts na **entrada** do divisor com `--ganho 19.357` | Informe a amplitude do **pino** (1,0332Vpp) ou use `--referencia-externa` |
| `frequência medida fora da planejada` | Gerador mal ajustado, ou taxa pedida ≠ gerada | Confira o contador do osciloscópio; veja T4 |
| O tom aparece em outra frequência acima de ~130 kS/s | A PRU não alcança a taxa pedida (T7e) | Calcule `fs_real` e use só taxas até 100 kS/s |
| Perfil com ganho de 1,0 em baixa frequência muito diferente (ex.: 0,1) | `--ganho` diferente de 1/sensibilidade | Use o ganho certo (divisor: 19,357; SCT013 sobre 0,12 Ω: 16 667) |
| Perfil "dentes de serra" ou pontos fora da curva | Gerador instável; resistor aquecendo; ponta mal compensada; TCP0030A sem zero/DEGAUSS | Refaça os pontos (`R`); repita com `--repeticoes`; compense a ponta |
| `ler_adc` trava | PRU parada | `dmesg`; `./setup.sh` |
| Disco cheio | Capturas longas | `df -h`; copie e apague; `calibrar_sonda.sh` pausa abaixo de 50 MB |

---

## Checklist ao sair do laboratório

- [ ] Todos os `.bin` copiados para o computador (e **também** em um segundo lugar) e o tamanho conferido.
- [ ] `resultados.csv` do dia salvo, com uma linha por canal medido.
- [ ] Pastas `capturas/cadeia_tensao/` e `capturas/sct013_100a_sn001/` (incluem `referencia_externa.csv` e `plano_coleta.txt`) copiadas, junto com o `.m` do osciloscópio de cada ponto (mesmo nome da captura) e as leituras da TCP0030A.
- [ ] Escala do ADC conferida no T0 (razões das três faixas) e a tabela de ruído por faixa do T1; os valores de `$GV` e `$GI` realmente usados nos perfis e a faixa de cada canal (`--faixa-adc`) anotados.
- [ ] Perfis `scripts/sondas/cadeia_tensao.json` e `scripts/sondas/sct013_100a_sn001.json` gerados e validados (T3, T10), e os PNG das curvas.
- [ ] Limite de taxa (T7e): tabela `fs_real` × taxa pedida, período do CS, saída do `ler_adc`.
- [ ] Fotos da bancada (e da placa antes de remover o capacitor) e prints do osciloscópio de cada teste (com a escala visível).
- [ ] Caderno: instrumentos e ajustes, temperatura, anomalias, o que **ficou por fazer**.
- [ ] Hipóteses confirmadas ou refutadas: escala e faixas do ADC (T0, T1), filtro de 15 kHz (T3), taxa real e ticks (T4), diafonia (T6), perda de amostras e gargalo (T7), sensibilidade de 60 µV/A (T10-0).
- [ ] Se algo mudou (outro `--ganho`, outro canal, nova taxa, outro número de espiras), anote: o perfil só vale para a cadeia em que foi medido.
