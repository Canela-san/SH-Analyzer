# Roteiro de laboratório

Lista de testes para validar o SH-Analyzer **de ponta a ponta** (ADC, firmware/PRU, divisor de tensão, sonda de corrente e software), com o sinal a injetar em cada um, os comandos exatos, o que anotar no osciloscópio e o que esperar. Feito para sair do laboratório com **dados que entram direto no relatório**.

Pré-requisito: [`user-guide.md`](user-guide.md) (capturar e analisar). Este roteiro supõe que você já sabe rodar `ler_adc` e `adc_tool.py`.

**Premissas desta versão** (todas conferidas nos testes indicados; se alguma falhar, o roteiro diz o que trocar):

* **Taxa de trabalho: no máximo 100 kS/s no total.** O firmware atual chega a ~140 kS/s (o gargalo está localizado: as três esperas do CS, ~57 % de cada amostra; veja o fato 1) e o ADC aceitaria 500 kS/s; taxas acima de 100 kS/s só aparecem para **documentar o limite** (T1, T4, T7e).
* **Canal de tensão (canal 1 do ADC) = divisor resistivo de 5 resistores ligado direto ao ADS8688**, sem sonda. "Sonda de tensão", neste roteiro, é o **divisor + o filtro de ~15 kHz do ADC**, e o perfil dela corrige os dois.
* **Canal de corrente (canal 0 do ADC) = SCT013 100A:50mA + resistor de 0,12 Ω + 2 resistores em série + ADC**, **com o capacitor de filtro removido** (o capacitor existente é um passa-baixa de frequência de corte baixíssima, incompatível com supraharmônicos).
* **Faixa de entrada do ADC escolhida por canal** (`--faixa-adc`): **canal de tensão em ±10,24 V** (o padrão, `20.48`: o divisor já usa 91% dela com 127 V RMS) e **canal de corrente em ±2,56 V** (`--faixa-adc 0:5.12`: o sinal tem dezenas de µV e a faixa menor reduz o ruído em volts). O firmware escreve a faixa no ADC e a registra no cabeçalho, e as ferramentas de análise a leem de lá (nada de `--faixa` nos comandos). **A escala em si (referência de 4,096 V, mapeamento do código) foi confirmada nas três faixas no T0 de 19/10/2026**; veja o fato 3.

**Índice**

1. [Estado da campanha](#estado-da-campanha) (o que já foi medido e o que vem a seguir) e o [passo a passo da próxima ida](#passo-a-passo-da-próxima-ida-firmware-novo-e-taxa-máxima)
2. [Antes de ir: o que o datasheet e o código já dizem](#antes-de-ir-o-que-o-datasheet-e-o-código-já-dizem)
3. [Equipamentos, segurança e boas práticas](#equipamentos-segurança-e-boas-práticas)
4. [Convenções e a ferramenta `medir_captura.py`](#convenções-e-a-ferramenta-medir_capturapy)
5. [Plano: ordem, tempo e prioridade](#plano-ordem-tempo-e-prioridade)
6. [Os testes](#os-testes): [T0](#t0-preparação-e-sanidade) · [T1](#t1-piso-de-ruído-entrada-em-curto) · [T2](#t2-tensão-contínua-ganho-offset-e-linearidade) · [T3](#t3-resposta-em-frequência-da-cadeia-de-tensão) · [T4](#t4-frequência-de-amostragem-real) · [T5](#t5-distorção-e-faixa-dinâmica) · [T6](#t6-vários-canais-diafonia-e-atraso) · [T7](#t7-integridade-e-limite-de-taxa) · [T8](#t8-aliasing) · [T9](#t9-sinais-de-espectro-conhecido) · [T10](#t10-perfil-da-sonda-de-corrente) · [T11](#t11-ponta-a-ponta)
7. [Dados e figuras para o relatório](#dados-e-figuras-para-o-relatório)
8. [Critérios de aceitação](#critérios-de-aceitação)
9. [Problemas de bancada](#problemas-de-bancada)
10. [Checklist ao sair do laboratório](#checklist-ao-sair-do-laboratório)

---

## Estado da campanha

Atualize esta tabela a cada ida ao laboratório: ela é o resumo do avanço para a apresentação quinzenal ([`report-notes.md`](report-notes.md#7-apresentação-quinzenal-ao-orientador)) e diz o que já pode entrar no relatório. Os números vêm de `$DADOS/lab/2026-10-19/resultados.csv`, gerado com os comandos de cada teste; o detalhe está no parágrafo **Executado em 19/10/2026** do teste.

| Teste | Situação | Resultado principal | Falta |
|---|---|---|---|
| [T0](#t0-preparação-e-sanidade) | ✅ 19/10 | Escala do ADC **confirmada nas três faixas** (razão 0,9997; 0,9997; 0,9992). Achado: as ~6 primeiras amostras depois de uma troca de faixa são transitório | Refazer o −10 V (as capturas "−10 V" saíram com 0 V na entrada) |
| [T1](#t1-piso-de-ruído-entrada-em-curto) | ✅ 19/10 | Ruído de 160 / 91 / 58 µV RMS nas faixas de ±10,24 / ±5,12 / ±2,56 V, igual ao datasheet (172 / 96 / 61 µV); não muda com a taxa nem com 2 canais. Offset do canal 1: +3,5 mV (canal 0: +0,05 mV) | Pino do canal 1 em curto direto (origem do offset) |
| [T2](#t2-tensão-contínua-ganho-offset-e-linearidade) | ✅ 19/10 | Razão real do divisor 0,051554 (`$GV` medido = 19,397; −0,03 % do nominal com a carga do ADC); resíduo de linearidade ≤ 0,22 LSB | — |
| [T3](#t3-resposta-em-frequência-da-cadeia-de-tensão) | ✅ 19/10 | −3 dB em 17,3 kHz; 2ª ordem com f0 = 24,1 kHz e Q = 0,54 | `--repeticoes 3`; fase |
| [T4](#t4-frequência-de-amostragem-real) | 🟡 19/10 | Taxa = 200 MHz ÷ ticks confirmada (102,4 kS/s: −64,0 ppm; 110 kS/s: −100,0 ppm; as exatas concordam em 0,02 ppm) | Leitura do contador do osciloscópio (separa gerador e cristal: hoje, −43,2 ppm somados) |
| [T5](#t5-distorção-e-faixa-dinâmica) | ⏳ | Prévia, das capturas do T4: SINAD 61 dB e ENOB 14,4 bits com o tom em −27,5 dBFS; THD −71,6 dB, limitado pelo gerador | Tudo |
| [T6](#t6-vários-canais-diafonia-e-atraso) | 🟡 19/10 | Diafonia 1 → 0 de −94,7 dB em 10 kHz; atraso entre canais 9,954 µs (esperado 10,000) | Refazer o ponto de 40 kHz em **20 kHz** (com 2 canais a Nyquist é 25 kHz) |
| [T7](#t7-integridade-e-limite-de-taxa) | 🟡 19/10, firmware antigo | T7c: salto de +0,697 amostra em **todas** as 57 trocas de buffer (defeito corrigido em out/2026); dentro de cada bloco, tom estável em 0,09 ppm e 0,01 % por 10 min | Recompilar e refazer T7a a T7c com ≥ 3 blocos; T7d; T7e |
| [T8](#t8-aliasing) a [T11](#t11-ponta-a-ponta) | ⏳ | — | Tudo; o T10 é o objetivo central |

### Passo a passo da próxima ida: firmware novo e taxa máxima

O dia tem um objetivo: validar o firmware de out/2026 e **decidir a taxa de trabalho**, antes de calibrar a sonda
(T10) e de refazer o que depende da banda. Cada etapa diz o que conferir e quando parar; o detalhe de cada uma está
no teste indicado. São ~2 h 30 min. Os blocos `bash` rodam na BeagleBone, no terminal do `scripts/BeagleBone_Setup.sh ssh`; os
`fish`, no computador, na raiz do repositório, com as [variáveis do roteiro](#nomes-e-pastas) (`DIA`).

**Sinal do dia todo:** senoide de **10,000 kHz, 20 Vpp, High-Z** no nó de entrada do divisor (canal 1), com o
**contador de frequência** do osciloscópio no mesmo sinal. Anote a leitura (ex.: 10 000,02 Hz): ela entra no
`--referencia-freq`. Ligue tudo 30 minutos antes da etapa 4.

**1. Firmware novo na BeagleBone e compilação (10 min).** No computador ([detalhes e plano B](#antes-de-sair-e-ao-chegar-levar-o-firmware-novo-à-beaglebone)):

```fish
scripts/BeagleBone_Setup.sh                    # o painel: a placa responde? relógio, firmware, PRU, disco
scripts/BeagleBone_Setup.sh enviar --simular   # confira a versão (v0.6-...) e a lista de arquivos
scripts/BeagleBone_Setup.sh preparar           # acerta o relógio, guarda o plano B, copia, compila e carrega a PRU
```

Se o firmware não ficar em `~/firmware` na placa, acrescente `--pasta caminho/firmware` (ou grave-a uma vez com o
`configurar`). Confira: o `setup.sh` termina com `PRU0 rodando o firmware novo.` e o painel do fim mostra a versão
nova e a PRU0 rodando. Os comandos da BeagleBone abaixo rodam num terminal aberto com
`scripts/BeagleBone_Setup.sh ssh` (já na pasta do firmware, com o sudo sem senha). **Se o `make` falhar**, guarde a mensagem e o
`dmesg | tail -n 20` e volte ao firmware de 19/10 (plano B, no link acima): o dia segue com o T10 e as pendências
curtas, e a taxa fica para outra ida.

**2. A correção do salto, em hardware (10 min; T0 passo 2 e [T7a](#t7-integridade-e-limite-de-taxa)).** Na
BeagleBone, com o tom:

```bash
./ler_adc --help | grep -E -- "--atraso-cs|--faixa-adc"   # as duas opções existem
sudo ./ler_adc 100000 1 --blocos 3 -o T7a_fs_100000.bin -t "T7a 100000"
sudo ./ler_adc 50000 1 --blocos 3 -o T7a_fs_50000.bin -t "T7a 50000"
```

No terminal de cada captura: `Firmware: v0.6-...`, `Taxa real medida pelo ARM: ...` **sem** "DIFERENTE da pedida"
e `Integridade: 0 amostra(s) atrasada(s), 0 buffer(s) sobrescrito(s), 0 quadro(s) com ruído no SDO -- tudo certo`.
No computador:

```fish
scripts/BeagleBone_Setup.sh trazer 'T7a*.bin' $DIA
uv run scripts/adc_tool.py info $DIA/T7a_fs_100000.bin     # Versão de cabeçalho: 5; Firmware; sem "CRC-32 NÃO confere"
uv run scripts/medir_captura.py $DIA/T7a_fs_*.bin --freq 10000 --sem-correcao-sonda --inicio 100 --csv $DIA/resultados.csv
```

**Passou:** `continuidade : OK` e `trocas de buffer : OK`, com o salto nas trocas nos milésimos de amostra, como fora
delas (em 19/10: `DESTOAM`, 6,96 µs). **Se aparecer `DESTOAM`**, a correção não funcionou no hardware: pare, guarde as
capturas e a saída do terminal e siga com o plano B. Subir a taxa num firmware com a grade errada não vale a pena.

**3. O "antes", com as esperas padrão (15 min; [T7e](#t7e-onde-está-o-limite-de-taxa), métodos 2 e 1).** Para o
relatório: mostra onde o firmware para hoje. Se o tempo apertar, pule o método 1 e faça só a foto.

* Método 2: ponta do osciloscópio no **CS** e no **SCLK** enquanto roda
  `sudo ./ler_adc 100000 1 --duracao 2m -o T7e_osc_padrao.bin -t "T7e osc padrao"`. Esperado: período de 10,00 µs e
  CS baixo de 5,83 µs. **Fotografe a tela.**
* Método 1: o laço de taxas do T7e, de 100 a 500 kS/s com as esperas padrão. Acima de ~140 kS/s, o `ler_adc` deve
  acusar amostras atrasadas e a `Taxa real medida pelo ARM` deve parar de subir.

**4. As esperas mínimas, a 100 kS/s (30 min; T7e, método 4, passo 1).** Os 7 conjuntos de `--atraso-cs`, do padrão ao
piso do datasheet, e o `medir_captura.py` com a tabela-resumo. Um conjunto **passa** com `Integridade: ... tudo certo`
e com amplitude, frequência, SINAD, ruído e DC iguais aos do padrão (critérios no T7e). Depois, os dois menores
conjuntos que passaram, com a **entrada em curto** (gerador fora da entrada), contra o padrão:

```bash
for cs in 200,100,100 MENOR SEGUNDO_MENOR; do     # troque pelos dois menores que passaram (ex.: 3,1,3 6,2,6)
  sudo ./ler_adc 100000 1 --blocos 3 --atraso-cs $cs -o T7e_curto_${cs//,/_}.bin -t "T7e curto cs $cs"
done 2>&1 | tee T7e_curto.txt
```

```fish
uv run scripts/medir_captura.py $DIA/T7e_curto_*.bin --sem-tom --sem-correcao-sonda --inicio 100 --csv $DIA/T7e_cs.csv
```

O ruído (`ruido_rms_lsb`) e o pico a pico têm de ser os do padrão (~0,51 LSB, como no T1). Se algum conjunto falhar,
o passo 2 do T7e diz qual espera importa.

**5. As esperas de trabalho e o teto (20 min; T7e, passos 3 e 4).** Esperas de trabalho = o **dobro** do menor
conjunto que passou, nunca menos que `6,2,6`. Com elas, o laço de taxas exatas até 312,5 kS/s. A espera **A** (CS
alto) só é posta à prova aqui: a 100 kS/s o CS fica alto até a próxima amostra, por mais de 4 µs, qualquer que seja o
A. Uma taxa passa com `0 amostra(s) atrasada(s)`, a taxa medida pelo ARM igual à pedida e o SINAD e o ruído iguais
aos da etapa 4. A maior que passa com ≥ 10 % de folga é a **taxa de trabalho** (250 kS/s, se o hardware aguentar).

**6. Confirmar no osciloscópio (10 min; T7e, passo 5).** Com as esperas e a taxa de trabalho: o período do CS é
1/taxa, e o CS baixo dura (566 + 2 × (S + H)) × 5 ns (3,13 µs com `20,10,10`). **Fotografe a tela**: é o "depois" da
foto da etapa 3.

**7. Decidir e registrar.** Anote na tabela acima a taxa e as esperas de trabalho. Até elas virarem o padrão do
firmware (`ATRASO_CS_*_PADRAO` em `firmware/memoria_pru.h`, com os testes que fixam o padrão), passe `--atraso-cs` em
**toda** captura, inclusive no `calibrar_sonda.sh`. Depois:

* **Se a taxa subiu:** o T1 na taxa e nas esperas novas (o quadro mais curto trouxe ruído?), o T7a, o T7b e o T7c
  (10 min) na taxa final, e então o T10-0 e o T10. Na sequência, o T3 inteiro (com `--repeticoes 3`), o T4 e o T6
  na taxa nova; por último, T5, T8, T9 e T11. A tabela [O que refazer](#o-que-refazer-com-o-firmware-de-out2026)
  diz o porquê de cada um.
* **Se ficou em 100 kS/s:** o T7b e o T7c, o T10-0 e o T10, e as pendências curtas (o contador no T4, os 20 kHz no
  T6a, o −10 V do T0, as repetições do T3). Depois, T5, T8, T9 e T11.

### O que refazer com o firmware de out/2026

**O que muda e o que não muda.** Com os atrasos de CS padrão (sem `--atraso-cs`), a transação SPI do firmware novo é
idêntica à antiga: os mesmos 1 166 ciclos e os mesmos instantes de CS e SCLK, conferidos no simulador. Mudam só:

* a grade de tempo nas trocas de buffer (o salto de 6,97 µs a cada bloco sumiu);
* as ~10 primeiras amostras de cada captura (antes saíam adiantadas);
* as capturas abaixo de 48,8 kS/s, em que um bloco dura mais de 21,5 s (o contador travava no meio dele);
* o cabeçalho v4, com a integridade de cada captura.

O ADC, o divisor, o filtro analógico interno do ADS8688, o ruído e a escala **não** dependem do firmware nem da taxa
de amostragem. Uma medida feita dentro de um bloco, a 100 kS/s, vale com o firmware novo.

**O que depende da taxa:** a banda que se mede. Um perfil (T3, T10) vale até 0,9 × Nyquist da taxa em que foi
medido, com 1 canal. Acima disso, a correção mantém o ganho do último ponto, o que dá um valor errado (o
`adc_tool.py` avisa). Também dependem da taxa o *aliasing* (T8) e os sinais de teste (T9, T11).

| Teste | Se a taxa ficar em 100 kS/s | Se a taxa subir (esperas do CS reduzidas no T7e) |
|---|---|---|
| T0 | Só o passo 2 (sanidade do firmware novo) e o −10 V pendente | Idem: a escala não depende da taxa |
| T1 | Não precisa | **Refazer** na taxa e nas esperas novas: é o que mostra se o quadro mais curto trouxe ruído (T7e, método 4) |
| T2 | Não precisa | Não precisa (DC) |
| T3 | Não precisa; só faltam as repetições (`--repeticoes 3`) | **Refazer inteiro** até 0,9 × Nyquist, com `--repeticoes 3`. Os pontos até 45 kHz continuariam valendo (o filtro é analógico), mas uma curva só, medida de uma vez, é melhor para o relatório |
| T4 | Não precisa; falta a leitura do contador | **Refazer** nas taxas novas, com o contador (30 min) |
| T5 | Fazer (nunca foi feito) | Fazer na taxa final |
| T6 | Não precisa; falta o ponto de 20 kHz | **Refazer** com as esperas novas (a diafonia de memória pode mudar com quadros mais curtos) |
| T7a a T7c | **Refazer**: é a validação da correção | Refazer na taxa final |
| T7e | **Fazer**: decide a taxa | — |
| T8, T9, T11 | Fazer | Fazer na taxa final |
| T10 (sonda de corrente) | Fazer | Fazer **só depois do T7e**, na taxa final |

**Quando vale subir a taxa.** Use só taxas que dividem 200 MHz exatamente: 125, 160, 200, 250 e 400 kS/s (fato 6).
Com 1 canal, o perfil cobre até 45 kHz a 100 kS/s, 56 kHz a 125, 72 kHz a 160, 90 kHz a 200 e 112 kHz a 250 kS/s
(150 kHz pedem ~333 kS/s).

* **≥ 200 kS/s com integridade** (0 amostras atrasadas, 0 quadros com ruído no SDO, ruído e SINAD iguais aos do
  padrão): a banda medida dobra. Vale refazer tudo o que vai para o relatório, na coluna da direita.
* **125 a 160 kS/s:** ganho de 25 a 60 % na banda. Decida com o orientador; fique numa taxa exata.
* **Abaixo disso:** fique em 100 kS/s; os dados de 19/10 (T0 a T4, T6) continuam valendo.

Lembre que, em produção, tensão e corrente juntas dividem a taxa por 2 (os canais são multiplexados). Um perfil
medido com 1 canal na taxa máxima vale para qualquer taxa menor por canal: calibre uma vez, na taxa mais alta que
passar no T7e.

### Antes de sair e ao chegar: levar o firmware novo à BeagleBone

O firmware de out/2026 só foi conferido no simulador. Guarde o de 19/10, que funcionou, **antes** de copiar o novo:
se o `make` falhar ou o firmware novo se comportar mal, você volta a ele em 2 minutos e o dia não se perde. Vai
**só a pasta `firmware/`** (o repositório e o `.git` não fazem falta lá). No computador, com tudo commitado:

```fish
scripts/BeagleBone_Setup.sh configurar         # uma vez: IP, usuário, senha e a pasta do firmware lá
scripts/BeagleBone_Setup.sh enviar --simular   # confira a versão e a lista de arquivos
scripts/BeagleBone_Setup.sh preparar           # relógio + plano B guardado + firmware novo + setup.sh
git tag bancada-(date +%F)                     # marca o commit que foi para a bancada (depois: git push --tags)
```

Sem o `configurar`, valem os padrões da imagem Debian (`debian@192.168.6.2`, senha `temppwd`, pasta `~/firmware`);
`--ip`, `--pasta` e as variáveis `BBB_*` mudam um valor só naquele comando ([guia de uso](user-guide.md#preparar-a-beaglebone)).
O `enviar` guarda o firmware que estava lá, **só o código e os binários** (não as capturas: o antigo `cp -a` da pasta
inteira as duplicava), em `~/firmware-anteriores/<data>_<versão>/`. Para o firmware de 19/10, que não tinha
`VERSAO`, o nome termina em `sem-versao`. Ele também escreve em `firmware/VERSAO` o `git describe`, que o `ler_adc`
novo grava no cabeçalho (v5) e imprime na largada (`Firmware: v0.6-...`); o `adc_tool.py info` a mostra de cada
captura. Ele recusa enviar com mudanças não commitadas em `firmware/` (a versão apontaria para um código que não
existe); `--forcar` envia assim mesmo, com `-dirty` na versão.

Depois do `preparar` (que já roda o `setup.sh` lá), o T0, passo 2.
**Plano B**, se o `make` falhar ou o T0 mostrar algo estranho: guarde a mensagem de erro e a saída do `dmesg`, rode
`cd ~/firmware-anteriores/<data>_sem-versao && ./setup.sh` (no terminal do `ssh`) e siga o dia com o firmware antigo (as capturas
continuam na pasta de sempre; só os comandos rodam da pasta do plano B). O T7 não valida nada com ele (o salto continua), mas o T10 e as
pendências curtas sim; as ferramentas leem o cabeçalho v3 normalmente.

Leve também: o tom de 10,000 kHz e o **contador de frequência** do osciloscópio (anote a leitura: faltou em 19/10);
pelo menos 500 MB livres na BeagleBone (`df -h`); e, no computador, as variáveis `DADOS` e `DIA` (Convenções).

**Próxima ida ao laboratório:** siga o [passo a passo](#passo-a-passo-da-próxima-ida-firmware-novo-e-taxa-máxima).
Os resultados de 19/10 continuam no relatório como caracterização do ADC (T0, T2) e como o "antes" da correção do
firmware (T7c).

---

## Antes de ir: o que o datasheet e o código já dizem

Oito fatos mudam o planejamento. Todos devem ser **confirmados** nos testes indicados.

**1. O teto de trabalho é 100 kS/s no total, e a Nyquist de cada canal é a taxa ÷ nº de canais ÷ 2.** O ADS8688 aceita 500 kS/s, mas o firmware hoje chega a ~140 kS/s. O gargalo foi localizado no próprio quadro SPI da PRU (~7 µs por amostra): ~4 µs são as três esperas do CS, calibradas empiricamente em 2/1/1 µs contra 30/10/30 ns do datasheet, e ~3 µs são os 32 clocks do SPI feitos em software. Quanto as esperas podem cair se mede no [T7e](#t7e-onde-está-o-limite-de-taxa). Trabalha-se em **100 kS/s**, que também é uma taxa exata da PRU (2000 ticks). Com **1 canal**, Nyquist = **50 kHz**; com **2 canais**, 50 kS/s cada, Nyquist = **25 kHz**. Consequências:

* o perfil e as medições valem até **~45 kHz** (90% de Nyquist), e a calibração usa `--freq-max 45k`;
* a banda de supraharmônicos (2 a 150 kHz) fica **só em parte coberta**. Cobrir até 150 kHz exigiria pelo menos 300 kS/s: **fica como sugestão de melhoria**; só reduzir as esperas do CS levaria o teto a ~330 kS/s no papel (T7e, método 4);
* componentes entre 50 e 150 kHz **dobram** para dentro de 0 a 50 kHz e não dá para separá-las depois ([T8](#t8-aliasing));
* acima de 100 kS/s use taxas só nos testes que pedem (T1, T4, T7), para mostrar no relatório o limite real e o que acontece além dele.

**2. O ADS8688 tem um filtro passa-baixa de 2ª ordem em cada canal, com corte de ~15 kHz.** Está no datasheet do repositório ([`datasheets/ads8688.pdf`](datasheets/ads8688.pdf), seção 8.3.5 e Figura 55; banda de pequenos sinais de **−3 dB em 15 kHz** e de −0,1 dB em 2,5 kHz). Não dá para desligar. Estimativa grosseira, entre um filtro de dois polos reais e um Butterworth de 2ª ordem:

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

**Hipóteses do [T0](#t0-preparação-e-sanidade), passo 6, e do T1, conferidas em 19/10/2026:**

* (a) A referência é a interna de 4,096 V e o código sai em binário deslocado: **confirmada**.
* (b) A escrita em `RANGE_SELn` pega em cada canal: **confirmada**, com a mesma tensão no pino nas três faixas (±0,08 %).
* (b') A conversão vale desde a primeira amostra: **não**. Depois de **trocar a faixa** de um canal em relação à captura anterior, as ~6 primeiras amostras desse canal (60 µs a 100 kS/s) são um transitório de acomodação, de até ~1 V no pino. Sem troca de faixa, não há transitório. Nas análises, pule o começo (`--inicio 100`).
* (c) O ruído por faixa segue o datasheet: **confirmada** (T1).

Capturas **antigas** (cabeçalho v1/v2, sem registro da faixa): o ADC estava na faixa de reset de ±10,24 V, e desde out/2026 as ferramentas as leem assim (`--faixa 20.48`). Até então elas assumiam 10.24, o que dava **a metade do valor real**: números antigos tirados dessas capturas precisam ser refeitos.

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

Isso desloca todas as frequências medidas pela mesma razão (um tom de 10 kHz aparece em 9 999,36 Hz a 102,4 kS/s). Além disso, o relógio de 200 MHz da PRU vem do cristal da BeagleBone, que tem erro de dezenas de ppm. O arredondamento foi **confirmado no [T4](#t4-frequência-de-amostragem-real)** em 19/10/2026 (−64,0 ppm a 102,4 kS/s e −100,0 ppm a 110 kS/s, como na tabela); falta separar o erro do cristal do erro do gerador. **Recomendação: use 100 kS/s** (ou 50 kS/s) nos testes de exatidão.

**7. Os instrumentos têm incerteza própria (cite no relatório).** O osciloscópio **MSO46** converte com 8 bits a 6,25 GS/s, 12 bits a 3,125 GS/s e até 16 bits em modo Hi-Res a 125 MS/s, com exatidão de ganho DC de **±1%** (±1,5% em ganho variável; o datasheet da série 4 ainda deixa 0,1%/°C acima de 30 °C). Para sinais de até 100 kHz use taxa de amostragem baixa (≤ 125 MS/s), Hi-Res ou média, e limite de banda. A ponta de corrente **TCP0030A** tem exatidão garantida de ±3% (típica ±1%) de DC a 60 Hz e ±1,5% de 60 Hz a 5 kHz na faixa de 5 A; **acima de 5 kHz não há exatidão especificada** (banda nominal de 120 MHz), então ela é a melhor referência disponível, não uma verdade absoluta. O multímetro **Fluke 289** é a melhor referência de tensão AC em 60 Hz a 1 kHz (confira a tabela de exatidão do manual: piora acima disso); o CEM DT-989 não tem banda conhecida (não use para AC acima de 60 Hz). Orçamento de incerteza do relatório: algo entre 1 e 3% para a referência.

**8. Um gerador de funções comum não serve para medir THD de um ADC de 16 bits.** O ADS8688 tem THD de −102 dB (típico, 1 kHz); geradores comuns têm −50 a −70 dBc, e o osciloscópio não enxerga abaixo de uns −60 dBc. O T5 explica o que fazer (filtro passa-faixa no gerador, ou fonte de baixa distorção).

> **Fora do roteiro:** o `datasheets/lv25-p.pdf` do repositório **não se aplica a esta placa**: o canal de tensão é um divisor resistivo, e não o transdutor LV 25-P.

---

## Equipamentos, segurança e boas práticas

### O que levar

Equipamentos do seu levantamento (`bench-notes.md`), com o que importa de cada um para o roteiro:

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
* **No computador:** copie tudo para `$DADOS/lab/AAAA-MM-DD/` (a pasta do dia, `$DIA` nos comandos), **fora do repositório**: dentro dele, um `git clean` apagaria os dados. As coletas do `calibrar_sonda.sh` (`firmware/capturas/<id>/` na BeagleBone) vão para `$DIA/capturas/<id>/`. Todos os resultados numéricos vão para **um único** `$DIA/resultados.csv`.
* **Canais desta bancada, em todos os testes: canal 1 = tensão (divisor) e canal 0 = corrente (SCT013).** Os comandos abaixo já usam essa atribuição (para mudá-la, troque o número do canal no `ler_adc`, em `--faixa-adc`, `--grandeza`, `--sonda` e `--canal-sonda`). Nos comandos de captura, o argumento depois da taxa é a lista de canais. **Com os dois canais, o ADS8688 varre sempre em ordem crescente: o canal 0 (corrente) é convertido primeiro e o canal 1 (tensão) 1/taxa total depois** (10 µs a 100 kS/s; veja o T6b).
* **Variáveis do roteiro (fish, no computador, na raiz do repositório).** Defina uma vez por sessão e use nos comandos de análise; assim, se o T2 ou o T10-0 mudarem um ganho, ou se você for analisar outro dia, troca só uma linha:

```fish
set -q DADOS; or set -Ux DADOS ~/Documents/sh-analyzer-data   # a pasta de dados (fica salva no fish)
set DIA $DADOS/lab/(date +%F)   # a pasta do dia de bancada; para outro dia: set DIA $DADOS/lab/2026-10-19
mkdir -p $DIA
set GV 19.357      # --ganho do canal de tensão: 1 ÷ razão do divisor (34,629 kΩ ÷ 1,789 kΩ)
set GI 16667       # --ganho do canal de corrente: 1 ÷ 60 µV/A (SCT013 100A:50mA sobre 0,12 Ω)
```

* **Faixa do ADC nos comandos.** Na **captura** (BeagleBone), o canal de tensão usa o padrão (nada a passar, ±10,24 V) e o de corrente leva `--faixa-adc 0:5.12` (±2,56 V). Na **análise** (computador), **não** se passa `--faixa`: ela vem do cabeçalho de cada captura (a primeira linha da saída mostra `canal 0: ±10.24 V` e `canal 1: ±2.56 V`). Se a captura for de um `ler_adc` antigo (sem faixa no cabeçalho), as ferramentas usam a faixa de reset, 20.48 (±10,24 V), e avisam.

* **Forma de onda do osciloscópio (`.m`).** Salve o arquivo de cada ponto com o **mesmo nome base da captura** (`calibracao_1000Hz_rep1.m` ao lado de `calibracao_1000Hz_rep1.bin`); o `gerar_perfil_sonda.py --referencia-osciloscopio` e o `medir_captura.py --osciloscopio` o encontram sozinhos. Anote o ajuste vertical e se a ponta é 10x (`--osc-escala`). Nesta versão, a variável salva pelo osciloscópio deve estar na **grandeza física** (tensão no nó de entrada do divisor; corrente da TCP0030A em A) e use `--osc-unidade A` (o nome é histórico: "A" aqui quer dizer "já está na grandeza física do canal, não multiplique pelo `--ganho`").
* **"A sonda" = o conjunto.** Neste projeto, "sonda" e "perfil da sonda" designam o conjunto medido de ponta a ponta: no canal de tensão, o **divisor + o ADS8688**; no de corrente, o **SCT013 + resistores + o ADS8688**. A frequência de corte do filtro do ADC não precisa ser conhecida: aparece na curva medida.
* **Grandeza no perfil de tensão.** Com `--grandeza tensao`, o `calibrar_sonda.sh` grava `--grandeza <canal>:tensao` nas capturas do divisor, como em produção (`--grandeza 1:tensao --sonda 1:cadeia_tensao`), e os textos dele falam da tensão na entrada da cadeia em vez de "shunt". Coletas feitas antes dessa opção ficaram marcadas como `corrente`: é só um rótulo, que o gerador de perfil não usa nos modos de 1 canal.
* **0 dBFS = metade do fundo de escala total** no pino do ADC: 10,24 V no canal 1 (tensão, ±10,24 V; 2,56 V no canal 0, corrente, em ±2,56 V). Amplitudes de pico no pino do canal 1: −0,5 dBFS = 9,67 V; −6 dBFS = 5,13 V; −20 dBFS = 1,024 V; −40 dBFS = 102 mV; −60 dBFS = 10,2 mV. **Pelo divisor** o gerador só chega a 0,517 V de pico (−26 dBFS): a tabela de gerador do [T5](#t5-distorção-e-faixa-dinâmica) já converte.

Para copiar as capturas (e as coletas de calibração do dia):

```fish
scripts/BeagleBone_Setup.sh trazer 'T*.bin' $DIA
scp -r 'debian@192.168.6.2:firmware/capturas' $DIA/     # as coletas do calibrar_sonda.sh (uma pasta inteira)
```

### `medir_captura.py` em um minuto

Mede uma ou mais capturas e imprime **números com unidade**, prontos para uma tabela:

```fish
uv run scripts/medir_captura.py $DIA/T5a_*.bin --csv $DIA/resultados.csv
```

Como o `adc_tool.py`, ele lê frequência, canais, sonda **e a faixa do ADC de cada canal** do cabeçalho (e aceita `-f`, `--canais`, `--faixa`, `--ganho`, `--offset`, `--formato`). **Atenção:** o cabeçalho **não** guarda o ganho; passe `--ganho $GV` no canal de tensão e `--ganho $GI` no de corrente, senão ele usa 1 (numa captura com os dois canais, `--ganho $GI,$GV`: um valor por canal, na ordem crescente dos canais, 0 e 1). `--faixa` só serve para sobrepor a do cabeçalho (ele avisa se divergir) ou para capturas antigas (v1/v2), que assumem a faixa de reset, 20.48. O que mede, por canal:

| Grandeza | Significado | Onde aparece |
|---|---|---|
| DC, RMS CA, pico a pico, saturação | Estatística básica. Saturação acima de 0,05% das amostras = captura inválida (aviso) | `media`, `rms_ca`, `pico_a_pico`, `saturacao_pct` |
| Densidade de ruído, ruído em LSB | Piso de ruído (mediana do espectro). 1 LSB = faixa total × ganho ÷ 65536 (a faixa de cada canal) | `densidade_ruido_por_rthz`, `ruido_rms_lsb` |
| Tom | Frequência e amplitude (pico e RMS) do maior pico espectral, em FFT com janela Kaiser sobre a captura inteira | `freq_tom_hz`, `amplitude_pico`, `amplitude_rms` |
| Harmônicos e THD | Soma das potências dos harmônicos (até `--harmonicos`, padrão 9) sobre a fundamental, em dB. Harmônicos acima de Nyquist são medidos na frequência **dobrada** (marcados `[alias]`) | `thd_db`, `thd_pct` |
| SINAD, SNR, ENOB | Sinal ÷ (ruído + distorção); sinal ÷ ruído; bits efetivos, **corrigidos** para um tom abaixo do fundo de escala | `sinad_db`, `snr_db`, `enob_bits` |
| SFDR | Fundamental ÷ maior espúrio, em dBc, com a frequência do espúrio e se ele é um harmônico | `sfdr_dbc`, `freq_espurio_hz`, `ordem_espurio` |
| Continuidade | Maior salto de fase do tom entre segmentos, em **amostras equivalentes** e em µs. Uma amostra perdida ou duplicada vale ~1,0 | `salto_max_amostras`, `salto_max_us`, `saltos_acima_do_limite`, `variacao_amplitude_pct` (variação da amplitude do tom entre segmentos) |
| Trocas de buffer | O salto **em cada troca de buffer da PRU** (a cada 1 048 576 amostras brutas) contra o típico dos outros segmentos. "DESTOAM" quando a mediana das trocas passa de 10 vezes o típico e de 0,05 µs: pega um atraso fixo menor que meia amostra, que a continuidade sozinha não acusa (o de 7 µs com 2 canais). Uma captura de 1 bloco não tem troca ("esta captura não testa a troca") | `trocas_buffer`, `salto_trocas_amostras`, `salto_trocas_us`, `salto_tipico_amostras`, `trocas_destoam` |
| Acoplamento (≥ 2 canais) | Amplitude de cada canal no tom do canal mais forte (diafonia, dB) e atraso entre canais (µs) | `diafonia_db`, `atraso_medido_us`, `atraso_esperado_us` |
| Comparação com instrumento | `--referencia-rms` (RMS lido, **na unidade física do canal**: V no nó de entrada do divisor; A no condutor, vezes o número de espiras) e `--referencia-freq` (Hz): erro em % e em ppm. `--amplitude-referencia` (`500mVpp`; padrão: a dos metadados; em V é a tensão **no pino**, antes do `--ganho`) e `--osciloscopio` (o `.m`): ADC ÷ injetado, ADC ÷ osciloscópio e osciloscópio ÷ injetado | `erro_amplitude_pct`, `erro_freq_ppm`, `razao_vs_amplitude_ref`, `razao_vs_osc`, `osc_vs_amplitude_ref_pct` |

Opções que você vai usar muito:

| Opção | Para quê |
|---|---|
| `--freq HZ` | Dica da frequência do tom (busca em ±10%). Obrigatória quando há interferência mais forte que o tom (60 Hz) |
| `--sem-tom` | Só ruído e estatística (entrada em curto) |
| `--canais-medir 1` | Mede só um dos canais da captura |
| `--rotulo "texto"` | Nome do teste no CSV (padrão: título do cabeçalho) |
| `--fs-pedida` | Analisa com a taxa **pedida**. O padrão (desde out/2026) é a que a PRU de fato gera, `clock ÷ ticks` do cabeçalho; as duas só diferem quando 200 MHz ÷ taxa não é inteiro (102,4 kS/s: +64 ppm). Serve para repetir o T4. (O antigo `--fs-pru` ainda é aceito e não muda nada) |
| `--sem-correcao-sonda` | Não aplica o perfil da sonda/cadeia. **Use para caracterizar o ADC**; sem isso, ruído e ENOB de um canal corrigido não descrevem o ADC |
| `--sondas-dir`, `--sonda-perfil C:ARQ` | Onde achar o perfil (padrão: `scripts/sondas/`) |
| `--inicio N`, `--max-amostras N` | Janela de análise, por canal (padrão: 4 194 304 amostras, ≈ 42 s a 100 kS/s, depois de pular os primeiros **200 µs**, 20 amostras a 100 kS/s). O pulo é o transitório de uma troca de faixa: se a faixa de algum canal mudou desde a captura anterior, as primeiras amostras decaem de até ~1 V e inflam o `rms_ca` (2,5 LSB em vez de 0,6 LSB numa captura de 10 s, no T0). Com `--inicio 0` mede tudo, e a ferramenta avisa quando o começo foge do resto. Os comandos deste roteiro continuam com `--inicio 100` (1 ms), que sobra; a coluna `inicio_por_canal` do CSV registra o usado |

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

1. No computador, com a BeagleBone por USB: `scripts/BeagleBone_Setup.sh hora` (o `preparar` já faz). O painel (`scripts/BeagleBone_Setup.sh`) mostra o relógio dela com `(certo)`.
2. Na BeagleBone: `cd firmware && ./setup.sh && dmesg | tail -n 20` (a PRU sobe sem reclamar). O `setup.sh` **recompila** o firmware (`make clean; make`): é preciso fazer isso depois de atualizar o repositório. A revisão de out/2026 (grade de tempo e contadores de integridade, cabeçalho v4) mexeu no `spi_core.asm` e só foi validada no simulador `tests/pru_sim.py`. Se o `make` falhar, guarde a mensagem e use o plano B ([Antes de sair e ao chegar](#antes-de-sair-e-ao-chegar-levar-o-firmware-novo-à-beaglebone)). Confira com `./ler_adc --help` que as opções `--faixa-adc` e `--atraso-cs` existem, e, na captura do passo 5, que o `ler_adc` termina com a linha `Integridade: 0 amostra(s) atrasada(s), 0 buffer(s) sobrescrito(s), 0 quadro(s) com ruído no SDO -- tudo certo` e que o resumo do cabeçalho diz `Versão de cabeçalho: 5` e `Firmware:` com a versão que você copiou.
3. Ligue o gerador, o osciloscópio, a ponta TCP0030A, o frontend e a BeagleBone **30 minutos antes** do T1.
4. **Capacitor do canal de corrente:** com tudo desligado, meça o valor dele (Fluke ou LCR; o seu 63 mF parece impreciso) e fotografe a placa. Anote o valor, **remova-o** e confirme que os dois resistores em série (1,79 kΩ e 1,7929 kΩ) continuam no lugar.
5. Entrada do canal de tensão em curto (a entrada do divisor ligada ao retorno). Capture:

```bash
sudo ./ler_adc 100000 1 --blocos 1 -o T0_sanidade.bin -t "T0 sanidade 100k"
ls -l T0_sanidade.bin        # 2098176 bytes = 1024 de cabeçalho + 1048576 amostras de 2 bytes
```

```fish
uv run scripts/medir_captura.py $DIA/T0_sanidade.bin --sem-tom --sem-correcao-sonda --inicio 100
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
    uv run scripts/medir_captura.py $DIA/T0_dc_p10_f$f.bin --sem-tom --sem-correcao-sonda --ganho 1 --inicio 100
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

Repita com **−10,000 V** em pelo menos a faixa de ±2,56 V (o sinal da leitura confere, e `media` muda de sinal sem offset grande). O T2 refina o ganho do divisor; este passo só confirma a escala. As capturas **antigas** (anteriores à faixa por canal) já são lidas com ±10,24 V pelas ferramentas desde out/2026; a `media` delas tem de bater com a de `T0_dc_p10_f2048.bin` para o mesmo sinal.

**Passou se:** o resumo do cabeçalho aparece sem "CRC-32 NÃO confere"; o tamanho do arquivo é o esperado; a saída do `medir_captura` não tem avisos; o DC (`media`) do curto é de poucos mV; **as três faixas dão a mesma tensão no pino (razão ≈ 1,00)**. Para a razão ficar limpa, desconte de cada `media` o offset da mesma faixa (a `media` com 0 V na entrada): o canal 1 tem ~3 mV de offset, 0,7 % dos 0,515 V.

**Executado em 19/10/2026** (firmware anterior à revisão de out/2026, cabeçalho v3; Fluke 289: `V_in` = 9,988 V):

| Faixa | `media` com +10 V | `media` com 0 V (offset) | Razão, descontado o offset | Ruído (0 V) |
|---|---|---|---|---|
| ±10,24 V | 518,41 mV | 3,47 mV | **0,9997** | 0,51 LSB (160 µV) |
| ±5,12 V | 517,40 mV | 2,46 mV | **0,9997** | 0,59 LSB (92 µV) |
| ±2,56 V | 517,22 mV | 2,55 mV | **0,9992** | 0,74 LSB (58 µV) |

* **Escala conferida:** referência de 4,096 V, escrita de `RANGE_SELn` e conversão código → volts certas nas três faixas, dentro de 0,08 %. As capturas antigas (v1/v2) eram lidas com metade do valor real (fato 3); as ferramentas foram corrigidas em out/2026.
* **As capturas `T0_dc_n10_*` saíram com 0 V na entrada**, não −10 V: a `media` delas é igual à do curto. Serviram como medida do offset por faixa (a coluna do meio). O −10 V do T2 confere (−511,6 mV no pino); refaça só se quiser o sinal negativo nas faixas menores.
* **Achado: transitório depois de trocar a faixa.** Em toda captura em que a faixa de um canal mudou desde a captura anterior, as ~6 primeiras amostras desse canal decaem de até ~1 V até o valor certo. No fim, a constante de tempo é de ~8 µs, próxima à do passa-baixa medido no T3 (polos em −22 kHz: 7 µs), o que sugere o filtro interno do ADC se acomodando à nova escala. Sem troca de faixa, não há transitório: são 15 capturas de 19/10, todas coerentes com essa regra. Na média de 10 s o efeito é desprezível (µV), mas no `rms_ca` ele domina (2,5 LSB em vez de 0,6 LSB): por isso o `--inicio 100` nos comandos. Para o relatório: "as primeiras 60 µs depois de mudar a faixa de entrada são descartadas".

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
uv run scripts/medir_captura.py $DIA/T1_*.bin --sem-tom --sem-correcao-sonda --ganho 1 --inicio 100 --csv $DIA/resultados.csv
uv run scripts/adc_tool.py $DIA/T1_curto_100k_1ch.bin --welch --modo-espectro ruido --sem-correcao-sonda --inicio 100 -o $DIA/fig_T1_psd.png
```

(`--inicio 100`: pula o transitório de troca de faixa do T0. Sem ele, o ruído das capturas de 19/10 que trocaram de faixa sai 7 a 8 vezes maior: 4,1 a 5,7 LSB em vez de 0,5 a 0,75 LSB.)

**Anote.** Nada no osciloscópio (opcional: tensão de ruído na entrada, só para ver se há zumbido evidente).

**Esperado.** Pelo datasheet (tom em −0,5 dBFS), o ruído no pino depende da faixa: **±10,24 V** (SNR de 90 a 92 dB): **~170 a 215 µV RMS**, ou **0,55 a 0,7 LSB** (1 LSB = 312,5 µV); **±5,12 V** (SNR típico de 91 dB, mínimo de 89 dB): **~96 a 121 µV** (0,6 a 0,8 LSB de 156 µV); **±2,56 V** (SNR típico de 89 dB, mínimo de 87,5 dB): **~61 a 72 µV** (0,8 a 0,9 LSB de 78 µV). Ou seja, reduzir a faixa diminui o ruído **em volts** (cerca de 1,8× e 2,8×), mas não na proporção da faixa: confira esses números, são a evidência de quanto a faixa menor ajuda. O offset deve ficar dentro de ±0,75 mV (típico ±0,5 mV) no pino do ADC. Ruído de 2 LSB ou mais indica problema de placa (cabo longo, terra, USB, alimentação): investigue antes de seguir. O espectro de ruído (PSD) deve ser plano, com poucos picos; **qualquer pico fixo** (60 Hz e harmônicos, relógio, 50 kHz) vai aparecer nos dados reais e precisa ser identificado. Para o relatório, converta o ruído para **a entrada de cada cadeia**: ÷ 0,051662 no canal de tensão (**~3,3 a 4,2 mV RMS** de banda larga) e ÷ 60 µV/A no de corrente (**~3 a 4 A RMS** equivalentes, com 1 espira): é a medida honesta da sensibilidade do projeto. Acima de 100 kS/s o ruído pode piorar (as margens de tempo do SPI): é o dado que se quer.

**Para o relatório.** Tabela: taxa × nº de canais × (ruído em LSB, µV RMS, nV/√Hz, offset em mV, ruído equivalente na entrada). Tabela do ruído por **faixa de entrada** (±10,24; ±5,12 e ±2,56 V) em µV RMS e em LSB, contra o datasheet. Figura: a PSD do curto.

**Executado em 19/10/2026** (curto na entrada, `--inicio 100`):

| Captura | Canal e faixa | Ruído | Offset | Datasheet (típico) |
|---|---|---|---|---|
| 50, 100, 130, 200 e "500" kS/s, 1 canal | 1, ±10,24 V | **0,51 a 0,52 LSB** (159 a 161 µV) | +3,39 a +3,48 mV | 172 µV |
| 100 kS/s, 1 canal | 1, ±5,12 V | **0,58 LSB** (91 µV) | +2,47 mV | 96 µV |
| 100 kS/s, 1 canal | 1, ±2,56 V | **0,75 LSB** (58 µV) | +2,55 mV | 61 µV |
| 100 kS/s, 2 canais | 0 (curto), ±2,56 V / 1, ±10,24 V | 0,71 LSB (56 µV) / 0,51 LSB (159 µV) | +0,05 mV / +3,44 mV | |
| 100 kS/s, sonda ligada sem condutor (1 e 2 canais) | 0, ±2,56 V | 0,71 LSB (55 µV) | +0,12 mV | |

* **O ruído segue o datasheet nas três faixas** (5 a 7 % abaixo do típico) e cai 1,8× e 2,8× em volts com a faixa, como previsto: a faixa menor ajuda o canal de corrente.
* **Não depende da taxa nem do número de canais.** Acima de ~140 kS/s a taxa real é menor que a pedida (T7e); a densidade em nV/√Hz dessas capturas só vale com a taxa real.
* **Sonda ligada = curto:** com 0,71 LSB nos dois casos, o SCT013 sem condutor não acrescenta ruído de ambiente mensurável em banda larga. Picos fixos (60 Hz, rádio), se houver, só aparecem na PSD: gere a `fig_T1_psd` também para `T1_sonda_100k_1ch.bin`.
* **O offset do canal 1 (+2,5 a +3,5 mV no pino, 50 a 67 mV referidos à entrada do divisor) é de 10 a 70 vezes o do canal 0 (+0,05 a +0,21 mV) e passa do máximo do datasheet (±0,75 mV).** O canal 0 tem 0,12 Ω de impedância de fonte e o canal 1, 1,7 kΩ (o divisor). A hipótese é que o offset venha da ligação do divisor (retorno ou terra), e não do ADC. Para conferir, faça uma rodada com o pino do canal 1 (R5) em curto direto. Na banda de supraharmônicos ele não importa: o filtro passa-alta e a FFT o removem.

### T2: tensão contínua (ganho, offset e linearidade)

**Objetivo.** Ganho real do divisor (vira o `$GV` calibrado), offset e linearidade, com DC.

**T2a: pelo divisor (canal 1).** O gerador em DC é a fonte (offset de ±10 V em High-Z), o Fluke 289 mede no nó de entrada do divisor. Sinal: **−10, −5, 0, +5 e +10 V** (os 5 níveis do gerador, anote cada leitura do multímetro com todos os dígitos).

```bash
sudo ./ler_adc 100000 1 --blocos 1 -o T2_dc_p5v.bin -t "T2 DC +5V"    # e assim para os 5 níveis
```

```fish
uv run scripts/medir_captura.py $DIA/T2_dc_*.bin --sem-tom --sem-correcao-sonda --ganho 1 --csv $DIA/resultados.csv
```

**Análise (planilha).** `media` (volts no pino) contra a leitura do multímetro na entrada: ajuste linear. A **inclinação é a razão real do divisor com a carga do ADC**: compare com 0,05157 (nominal com a carga de 1 MΩ; 0,051662 sem ela). Se for diferente por mais de ~0,3%, use `1 ÷ inclinação` como `$GV` (e se for perto de **metade** ou do **dobro**, a escala do T0 está errada). O intercepto é o offset (esperado ±0,75 mV no pino, ±15 mV referido à entrada); o resíduo, em LSB, é o erro de linearidade **na faixa de ±0,5 V do pino** (só 10% da escala).

**T2b (opcional): linearidade na escala inteira.** O divisor só deixa ver ±0,52 V no pino. Se algum outro canal tiver a entrada ligada direto no pino do ADC, repita lá com DC de **−9, −6, −3, 0, +3, +6, +9 V** do gerador (≤ ±10 V). Sem esse acesso, a linearidade acima de ±0,5 V só pode ser conferida na rede (T2c).

**T2c (opcional, com supervisão): a rede.** Transformador de isolamento + autotransformador (se houver), 3 níveis de rede: ~60, ~100 e ~127 V RMS. Fluke 289 no mesmo nó; capture 1 bloco a 100 kS/s e rode `medir_captura.py ... --freq 60 --referencia-rms <leitura do Fluke> --ganho $GV` (precisa estar sem saturação: `saturacao_pct` = 0). **Nunca 220 V** (satura). Mostra o ganho no uso real do projeto e a margem até o fundo de escala (127 V = 91%).

**Esperado (datasheet, faixa de ±2,5 × VREF).** Erro de ganho típico ±0,02% da faixa (máx. ±0,05%), offset típico ±0,5 mV (máx. ±0,75 mV), INL típica ±0,75 LSB (máx. ±2 LSB). Os resistores do divisor (medidos com multímetro) e o multímetro limitam o que você consegue provar: registre as incertezas.

**Para o relatório.** Gráfico `media` × referência com a reta e o resíduo em LSB; razão real do divisor, offset e (se feita) linearidade em escala inteira.

**Executado em 19/10/2026** (T2a, faixa de ±10,24 V; Fluke 289 no nó de entrada: +9,989; +4,9924; +0,0019; −4,9924 e −9,988 V):

| Grandeza | Medido | Esperado |
|---|---|---|
| Inclinação (razão real do divisor com a carga do ADC) | **0,051554** | 0,05157 (−0,03 %); sem a carga, 0,051662 (−0,21 %, contra −0,17 % previstos) |
| `$GV` = 1 ÷ inclinação | **19,397** | 19,357 nominal (+0,21 %, abaixo do limiar de 0,3 % para trocar) |
| Intercepto (offset no pino) | +3,49 mV | o mesmo do T1 |
| Resíduo de linearidade | ≤ 0,22 LSB nos 5 pontos | INL do datasheet ±0,75 LSB típica (só ±0,5 V do pino, 5 % da escala) |
| Ruído em cada nível | 0,50 a 0,57 LSB | o do T1 (o gerador em DC não acrescenta ruído) |

O `$GV` continua 19,357, como no perfil do T3: o ganho de baixa frequência do perfil (K = 0,9969) já absorve a carga do ADC, e 19,357 ÷ 0,9969 = 19,417 fica a 0,1 % do valor DC medido aqui.

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
uv run scripts/gerar_perfil_sonda.py $DIA/capturas/cadeia_tensao --referencia-externa --ganho $GV --plot
```

Uma coleta feita antes de `--grandeza tensao` gravou a leitura na coluna `v_shunt_rms_V`: para ela, some `--resistencia-shunt 1` (com 1 Ω, a "corrente" calculada é numericamente a tensão em volts). Para a variante de amplitude conhecida, o mesmo comando **sem** `--referencia-externa` (a amplitude vem dos metadados). Para um `.m` por ponto (tensão na entrada do divisor, em V), troque por `--referencia-osciloscopio --osc-unidade A`. O resultado é `scripts/sondas/cadeia_tensao.json` e um PNG com a curva. O `$GV` usado aqui é o mesmo que vai em produção: o perfil sai **relativo a ele** (ganho de baixa frequência esperado ~0,998, a carga de 1 MΩ).

**Verificação pontual, sem o assistente.** Para conferir a amplitude em uma frequência, sem gerar perfil:

```bash
sudo ./ler_adc 100000 1 --blocos 2 -o T3_f40000.bin -t "T3 40 kHz"
```

```fish
uv run scripts/medir_captura.py $DIA/T3_f40000.bin --freq 40000 --referencia-rms 7.0712 --sem-correcao-sonda --ganho $GV --csv $DIA/resultados.csv
```

Imprime o erro de amplitude em % (ADC contra instrumento): a atenuação da cadeia nessa frequência.

**Ensaio prévio do fluxo.** O caminho "assistente → `gerar_perfil_sonda.py` → correção no `medir_captura.py`" foi ensaiado com dados sintéticos de uma cadeia de dois polos com −3 dB em 15 kHz (24 pontos, 50 Hz a 160 kHz, **400 kS/s**, 1 canal): o perfil recuperou o ganho com erro de 0,001%, e uma onda quadrada de 10 kHz, que sem correção mostrava a 15ª harmônica 31 dB abaixo da teoria, voltou à teoria em ±0,05 dB até 150 kHz (a fundamental, em 0,03%). A 100 kS/s o fluxo é o mesmo, mas só vai até 45 kHz. Avisos "fora da faixa válida" aparecem se a análise tiver componentes além do último ponto do perfil (o ganho é mantido constante ali, sem extrapolar).

**Esperado.** Ganho plano (±0,1 dB) até ~2,5 kHz, **−3 dB perto de 15 kHz** e queda de 12 dB por oitava, chegando a algo entre −14 e −19 dB em 45 kHz. O `gerar_perfil_sonda.py` imprime o resumo da resposta (ganho de baixa frequência, frequência de −3 dB, inclinação final em dB/oitava e quanto a correção amplifica o ruído na maior frequência: ~+14 a +19 dB) e o grava no perfil (`calibracao_adc.resposta_conjunto`). Como o último ponto é 45 kHz, a inclinação final tem pouca excursão: a frequência de −3 dB é o resultado mais seguro. Se a curva mostrar ressonâncias ou picos, são do divisor ou da fiação: aumente a densidade de pontos ali (`--modo refinar`).

**Para o relatório.** A curva de ganho (dB) × frequência (eixo logarítmico), com a frequência de −3 dB marcada e a curva teórica do datasheet por cima; tabela de ganho em 1, 5, 10, 15, 20, 30 e 45 kHz. A figura sai do script das figuras do relatório, que lê o perfil, ajusta um passa-baixa de 2ª ordem (em dB) e grava, além do PDF, as macros com K, f0, Q e f−3dB para o texto:

```fish
uv run report/gerar_figuras.py perfil_cadeia_tensao --png
```

**Executado em 19/10/2026** (48 pontos de 50 Hz a 45 kHz, `--ref-externa`, sem repetições; `scripts/sondas/cadeia_tensao.json`): −3 dB em **17,3 kHz** e −12,5 dB em 45 kHz; o 2ª ordem ajusta com f0 = 24,1 kHz, Q = 0,54 e resíduo de 0,13 dB. Para a próxima rodada: `--grandeza tensao` (a coleta de 19/10 é anterior à opção e ficou marcada como corrente, o que não muda o perfil) e `--repeticoes 3`, para ter a incerteza de cada ponto (o ajuste passa a ser ponderado). A fase não foi medida: a função de transferência vale sob a hipótese de fase mínima (ver `docs/report-notes.md`, Marco 12).

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
    uv run scripts/medir_captura.py $DIA/T4_fs_$taxa.bin --freq 10000 --referencia-freq 10000.02 --sem-correcao-sonda --inicio 100 --csv $DIA/resultados.csv
end
```

(As taxas acima de 125 kS/s ficam no [T7e](#t7e-onde-está-o-limite-de-taxa): lá a taxa real pode nem acompanhar a pedida.)

**Como ler.** Desde out/2026, o `medir_captura.py` (e o `adc_tool.py` e o `gerar_perfil_sonda.py`) analisa com a taxa que a PRU **gera**, `200 MHz ÷ ticks`, gravada no cabeçalho: a primeira linha de cada captura diz `102406.55 Hz (a que a PRU gera, clock ÷ ticks; a pedida era 102400 Hz, +64.0 ppm ...)`, e a coluna `fs_pru_hz` do CSV guarda esse valor. Com ela, **todas as taxas devem dar o mesmo `erro_freq_ppm`**: é o erro do cristal da PRU (δ_cristal), comum a todas (frequência medida menos a do contador, em ppm; o contador é a verdade, então o erro do gerador não entra). Para ver o arredondamento dos ticks, rode de novo com `--fs-pedida` (a análise supõe a taxa pedida, como antes):

* Taxas que dividem 200 MHz (50, 100, 125 kS/s) dão o mesmo valor com e sem `--fs-pedida`.
* Com `--fs-pedida`, 102,4 kS/s deve dar `−(δ_cristal + 64 ppm)` e 110 kS/s, `−(δ_cristal + 100 ppm)`: a diferença para as taxas exatas é o arredondamento dos ticks.
* Se as taxas exatas **não** derem o mesmo valor, o laço da PRU tem um número de ciclos fixo a mais por amostra (a hipótese "taxa = clock ÷ ticks" está errada): isso também vai para o relatório.
* Use o trecho inteiro só com o firmware novo. Com o antigo, o salto na troca de buffer puxa a frequência medida em ~+1,5 ppm e a amplitude em −0,3 % numa captura de 2 blocos: por isso as capturas de 19/10 foram medidas no primeiro bloco (`--max-amostras 1048000`).

**Esperado.** Cristal da BeagleBone na faixa de dezenas de ppm. Em frequências medidas, isso é um erro relativo de 0,00x%, desprezível para amplitude, mas relevante se você quiser separar tons muito próximos ou comparar a frequência com uma referência.

**Para o relatório.** Tabela: taxa pedida × ticks × taxa gerada prevista × erro medido (ppm). Recomendação do uso de taxas exatas.

**Executado em 19/10/2026** (10 kHz, 20 Vpp; **sem a leitura do contador**; firmware antigo, então só o primeiro bloco: `--inicio 100 --max-amostras 1048000`, porque o salto na troca de buffer desloca a frequência estimada nas capturas de 2 blocos):

| Taxa pedida | Ticks | Tom medido | Diferença para as taxas exatas | Prevista pelos ticks |
|---|---|---|---|---|
| 50 000 | 4000 | 9 999,5681 Hz | 0 (referência) | 0 |
| 100 000 | 2000 | 9 999,5682 Hz | +0,01 ppm | 0 |
| 125 000 | 1600 | 9 999,5680 Hz | −0,01 ppm | 0 |
| 102 400 | 1953 | 9 998,9279 Hz | **−64,03 ppm** | −64,0 ppm |
| 110 000 | 1818 | 9 998,5684 Hz | **−99,98 ppm** | −100,0 ppm |

* **A hipótese "taxa = 200 MHz ÷ ticks" vale:** as três taxas exatas concordam em 0,02 ppm (não há ciclo fixo a mais por amostra) e as outras duas erram exatamente o arredondamento. Com a taxa da PRU (hoje o padrão; na época, `--fs-pru`), 102,4 e 110 kS/s caem em 9 999,5679 e 9 999,5684 Hz, sobre as exatas. A tabela acima é a do `--fs-pedida`.
* **Erro comum de −43,2 ppm** (o tom aparece em 9 999,568 Hz): é o erro do cristal da BeagleBone **somado** ao do gerador. Só a leitura do contador do osciloscópio separa os dois; anote-a na próxima vez.
* De quebra, as capturas dão a prévia do T5 a −27,5 dBFS (tom de 0,4316 V de pico): SINAD 60,5 a 61,5 dB, ENOB 14,3 a 14,5 bits e THD −71,6 dB, com a 3ª harmônica a −73 dBc. É o THD do **gerador** (fato 8), não o do ADC.

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
uv run scripts/medir_captura.py $DIA/T5*.bin --sem-correcao-sonda --ganho 1 --harmonicos 9 --csv $DIA/resultados.csv
```

(`--ganho 1`: o ADC sozinho, em volts no pino.)

**Anote.** Amplitude real no osciloscópio/multímetro em cada ponto; modelo e THD do gerador; se usou filtro.

**Esperado (datasheet, tom em −0,5 dBFS, 1 kHz, faixa de ±2,5 × VREF).** SNR 92 dB (mín. 90), SINAD 91,5 dB (mín. 89), **ENOB ≈ 14,9 bits** (mín. 14,5), THD −102 dB, SFDR 103 dB. Como o nível máximo pelo divisor é −26 dBFS, o SINAD medido tende a ~66 dB (cai 1 dB por dB de nível, até o piso de ruído); a **faixa dinâmica** vem da extrapolação da reta de SINAD × nível. O ENOB do `medir_captura.py` já é corrigido para o nível do tom. Em frequências mais altas o THD medido parece **melhor** do que é: os harmônicos (2f, 3f...) são atenuados mais ainda pelo filtro de 15 kHz, e acima de Nyquist dobram para dentro.

**Para o relatório.** Figura: SINAD (e ENOB) × nível em dBFS; a faixa dinâmica é o nível em que o SINAD chega a 0 dB. Figura: THD, SINAD e SFDR × frequência. Tabela: valores medidos contra datasheet.

**Prévia (capturas do T4, 19/10/2026):** 10 kHz a −27,5 dBFS sem filtro no gerador dá SINAD de 61 dB, ENOB de 14,4 bits e THD de −71,6 dB. O SINAD está no esperado para o nível (≥ 62 dB a −26 dBFS) e o THD é o do gerador: o T5 de verdade precisa do filtro ou da fonte de baixa distorção.

### T6: vários canais (diafonia e atraso)

**Objetivo.** Quanto um canal vaza no outro, e se o intervalo de multiplexação entre canais é o esperado (importante para qualquer cálculo que combine tensão e corrente).

**T6a: diafonia.** Capture 2 canais (0 e 1) a 100 kS/s (50 kS/s cada). **Canal 1** (tensão) recebe um tom de 10 kHz com **20 Vpp** (−26 dBFS no pino, o máximo pelo divisor); **canal 0** (corrente) com a entrada em curto. Repita com **20 kHz**: com 2 canais a Nyquist de cada um é **25 kHz**, e um tom de 40 kHz aparece dobrado em 10 kHz (foi o que aconteceu em 19/10). Na varredura (0, 1, 0, 1, ...), o canal 0 é amostrado **logo depois** do 1, que é o pior caso para a "diafonia de memória". (O agressor no canal 0 não é possível: o resistor de 0,12 Ω da entrada de corrente curto-circuita o gerador. Só seria possível com acesso direto ao pino.) Para o pior caso global, capture 8 canais a 100 kS/s com o tom no canal 1 e os demais em curto, se as entradas forem acessíveis (o canal 2 é o amostrado logo depois do 1).

```bash
sudo ./ler_adc 100000 0,1 --faixa-adc 0:5.12 --blocos 2 -o T6a_10k_ch1.bin -t "T6a 10kHz ch1 agressor"
sudo ./ler_adc 100000 0,1 --faixa-adc 0:5.12 --blocos 2 -o T6a_20k_ch1.bin -t "T6a 20kHz ch1 agressor"
```

**T6b: atraso entre canais.** Precisa do **mesmo sinal** nos dois canais, com o mesmo condicionamento. Se a placa tiver dois canais equivalentes (dois divisores, ou dois pinos acessíveis), ligue-os em paralelo com um conector T de BNC, cabos do mesmo comprimento, a 100 kS/s, em 1, 5 e 10 kHz. Senão, use o teste **V–I** (opcional): gerador → resistor de 10,92 Ω → **N espiras** no SCT013 → retorno; a tensão **no resistor** vai para o divisor (canal 1) e a corrente é a do SCT013 (canal 0), com o MSO46 medindo a mesma tensão (TPP0500B) e a corrente (TCP0030A) ao mesmo tempo. A diferença entre o atraso visto pelo ADC e o do osciloscópio é o atraso da cadeia (acrescido da fase do SCT013, que o perfil de amplitude **não** corrige). O sinal da corrente é fraco (T10-0): use 1 kHz e 4 blocos, e só confie no resultado se o `snr_db` do canal 0 (corrente) passar de 30 dB. Na varredura, o canal 0 é convertido **antes** do 1 (1/taxa total, 10 µs a 100 kS/s): esse atraso de conversão é o que entra no `atraso_esperado_us`, somado ao das cadeias.

```bash
sudo ./ler_adc 100000 1,2 --faixa-adc 1:5.12,2:5.12 --blocos 4 -o T6b_1k.bin -t "T6b mesmo sinal 1kHz"   # dois canais de tensão em paralelo (como em 19/10)
sudo ./ler_adc 100000 0,1 --faixa-adc 0:5.12 --blocos 4 -o T6b_VI_1k.bin -t "T6b V-I 1kHz"                # ou o teste V-I
```

```fish
uv run scripts/medir_captura.py $DIA/T6*.bin --sem-correcao-sonda --csv $DIA/resultados.csv
```

(A diafonia é medida em volts no pino, então as faixas diferentes dos dois canais, lidas do cabeçalho, não atrapalham; o canal 0 em ±2,56 V tem menos ruído, e a diafonia mínima mensurável melhora na mesma medida.)

**Como ler.** A saída traz "Acoplamento entre canais no tom de ...": em T6a, `diafonia_db` do canal em curto; em T6b, `atraso_medido_us` contra `atraso_esperado_us`.

**Esperado.** Datasheet: isolamento entre canais de **110 dB** e diafonia de memória de **90 dB** (com agressor em sobrecarga de 2× o fundo de escala). Aqui o agressor está 26 dB abaixo do fundo de escala e o que a ferramenta mede é limitado pelo ruído por bin (~−110 dB): se o resultado estiver no piso, escreva "melhor que X dB". O atraso entre canais consecutivos deve ser **1/taxa total** (10 µs a 100 kS/s): é o que a PRU configura, e vale compensar no cálculo de potência (a 60 Hz isso é 0,22°; a 5 kHz, 18°; a 40 kHz, 144°).

**Para o relatório.** Tabela de diafonia (frequência × par de canais); tabela de atraso medido contra esperado.

**Executado em 19/10/2026** (firmware antigo; os dois canais em ±2,56 V; `--inicio 100`):

| Captura | Resultado | Leitura |
|---|---|---|
| T6a, 10 kHz no canal 1 (−15,5 dBFS na faixa de ±2,56 V), canal 0 em curto | Diafonia **−94,7 dB** (5,6 µV RMS no canal 0, ~37 dB acima do ruído por bin) | Dentro da diafonia de memória do datasheet (90 dB, com o agressor em sobrecarga). É o canal convertido logo depois do agressor, o pior caso |
| T6a, "40 kHz" | Tom em **10,0017 kHz** nos dois canais: o 40 kHz dobrou (Nyquist de 25 kHz com 2 canais); diafonia de −83,2 dB entre os tons dobrados | Não vale como ponto de 40 kHz. O comando passou a pedir 20 kHz |
| T6b, 1 kHz nos canais 1 e 2 em paralelo | Atraso **9,954 µs** contra 10,000 µs (−0,46 %, dentro de ±2 %); amplitude do canal 2 0,48 % acima da do canal 1 | O atraso é a multiplexação, como a PRU configura. A diferença de amplitude é do condicionamento de cada canal: confirme o que estava ligado ao canal 2 |
| T7b, 8 canais com o tom nos canais 1 e 2 | Canal 3 a −42 dB e canal 4 a −58 dB do tom; canais 5 a 7 sem tom | Entradas **abertas**, sem fonte que as segure: não é medida de diafonia, e o relatório não deve citá-la como tal |

O SINAD de 22 a 42 dB que a ferramenta imprime nessas capturas é o salto do firmware antigo na troca de buffer, e não ruído (T7).

### T7: integridade e limite de taxa

**Objetivo.** Provar que **nenhuma amostra é perdida ou duplicada** até 100 kS/s e sob carga na BeagleBone, que os dados chegam ao disco inteiros (requisito de desempenho do projeto), e **documentar onde está o limite real** e o que acontece acima dele.

**Sinal.** Senoide de 10 kHz com 20 Vpp (−26 dBFS no pino), estável (a continuidade se verifica pela fase do tom: um tom estável é essencial). Canal 1 (tensão).

**T7a: taxas até o limite recomendado.** 1 canal, **3 blocos** em cada taxa (31 s a 100 kS/s). Tem de ser mais de 1 bloco: o que se quer ver são as **trocas de buffer** da PRU, e uma captura de 1 bloco (10 s a 100 kS/s) não tem nenhuma; as de 19/10 eram assim.

```bash
for taxa in 50000 100000; do
  sudo ./ler_adc $taxa 1 --blocos 3 -o T7a_fs_$taxa.bin -t "T7a $taxa"
done
```

**T7b: dois canais.** 2 canais a 100 kS/s (50 kS/s por canal), `--blocos 3`, tom de 10 kHz no canal 1 (tensão) e o canal 0 em curto; e, se as entradas forem acessíveis, 8 canais a 100 kS/s (12,5 kS/s por canal) com `--blocos 8`: com 8 canais, 1 bloco dá só 131 072 amostras por canal, pouco para a continuidade (a ferramenta responde "não verificada").

**T7c: longa duração e deriva.** 10 minutos a 100 kS/s com o tom (≈ 120 MB; confira o espaço livre).

```bash
sudo ./ler_adc 100000 1 --duracao 10m -o T7c_10min.bin -t "T7c 10 min 100k"
```

```fish
for ini in (seq 0 6000000 54000000)
    uv run scripts/medir_captura.py $DIA/T7c_10min.bin --freq 10000 --inicio $ini --max-amostras 4000000 --rotulo "T7c ini $ini" --sem-correcao-sonda --csv $DIA/resultados.csv
end
```

**T7d: sob carga.** Repita o T7a a 100 kS/s **enquanto** outra janela copia um arquivo grande por `scp` e outra roda `top`. Mostra se o sistema de arquivos ou a CPU atrapalham a captura.

```fish
uv run scripts/medir_captura.py $DIA/T7[abcd]*.bin --freq 10000 --sem-correcao-sonda --inicio 100 --csv $DIA/resultados.csv
```

**Esperado.** Em cada captura: `continuidade : OK`, **0 eventos**, maior salto de fase **de poucos milésimos de amostra** (0,001 a 0,004 nas capturas de 19/10 sem troca de buffer, 0,01 a 0,04 µs), e a linha `trocas de buffer : OK -- N no trecho, salto mediano 0.00x amostra(s) (0.0x µs ...) contra 0.00x ... longe delas`: o salto nas trocas igual ao dos outros segmentos. O critério de 0,5 amostra **do canal** não basta sozinho: o salto de 7 µs do firmware antigo vale 0,7 amostra com 1 canal a 100 kS/s, mas 0,35 com 2 canais e 0,09 com 8. É a linha das trocas que o pega em qualquer nº de canais (nas capturas de 19/10: `DESTOAM -- ... 6.96 µs ... contra 0.0229 µs`). Tamanho do arquivo igual ao do cabeçalho (a ferramenta avisa se não for); amplitude do tom varia menos de ~0,1% entre segmentos. No T7c, o tom pode derivar um pouco pelo gerador: compare com a leitura do osciloscópio no início e no fim.

**Passou se:** zero eventos e `trocas de buffer : OK` em todas as capturas de até 100 kS/s, inclusive T7b e T7d, e o `ler_adc` termina com `Integridade: 0 amostra(s) atrasada(s), 0 buffer(s) sobrescrito(s), 0 quadro(s) com ruído no SDO -- tudo certo`. Um evento = anote em qual taxa, que amostra (`perto da amostra N`) e olhe a saída do terminal do `ler_adc` e o `dmesg` daquele instante.

**Executado em 19/10/2026, com o firmware anterior a out/2026** (canal 1, tom de 10 kHz, `--inicio 100`):

| Captura | Blocos | Maior salto | Leitura |
|---|---|---|---|
| T7a, 50 e 100 kS/s, 1 canal | 1 | 0,003 a 0,004 amostra | OK, mas sem nenhuma troca de buffer dentro da captura |
| T7b, 50 e 100 kS/s, 2 canais | 1 | 0,001 a 0,002 amostra | Idem |
| T7b, 8 canais | 1 | não verificada | Curta demais por canal |
| T4, 110 e 125 kS/s; T6a; T6b | 2 a 4 | **0,77 e 0,87**; 0,35 com 2 canais | Salto em toda troca de buffer |
| **T7c, 10 min a 100 kS/s** | 58 | **+0,697 amostra (6,97 µs) em todas as 57 trocas**, desvio de ±0,002 | O defeito do firmware antigo (abaixo) |

* **O defeito:** o contador de ciclos da PRU era zerado a cada troca de buffer **depois** da transação da última amostra, e a primeira amostra do bloco seguinte saía uma transação (~1 394 ciclos, 6,97 µs) atrasada. O salto, em amostras, cresce com a taxa (0,697 a 100 kS/s, 0,77 a 110 kS/s, 0,87 a 125 kS/s): é um tempo fixo. Nenhuma amostra se perdeu; a grade de tempo é que escorregou. O `medir_captura.py` o aponta ("numa troca de buffer da PRU"). A correção (out/2026) está no [Marco 13](report-notes.md#marco-13--revisão-do-firmware-grade-de-tempo-e-integridade-da-captura) das notas.
* **Dentro de cada bloco, o sistema é estável:** em 11 janelas de 1 bloco espalhadas pelos 10 min, o tom ficou em 9 999,5690 a 9 999,5699 Hz (0,09 ppm) e a amplitude em 0,304809 a 0,304836 V RMS (0,009 %).
* **A refazer, com o firmware novo** (`./setup.sh`): T7a e T7b com ≥ 3 blocos e o T7c. O maior salto tem de cair para os milésimos em todas as trocas, e o `ler_adc` tem de terminar com a linha `Integridade: ... tudo certo`. É a validação em hardware da correção (o simulador já confere a lógica).

#### T7e: onde está o limite de taxa

**Objetivo.** Saber **até onde** vai a taxa real e **qual parte** do projeto é o gargalo (a PRU/SPI, o ADC ou o lado ARM), em vez de supor. **Ordem:** o método 2 (osciloscópio, 10 min), o método 1 com as esperas padrão, o **método 4** (a busca das esperas mínimas e do teto: é ele que decide a taxa de trabalho) e o método 3 só se aparecerem buffers sobrescritos. São os itens F2 e F3 de [`improvement-proposals.md`](improvement-proposals.md#f2--medir-até-onde-as-esperas-do-cs-podem-cair), medidos em bancada.

**Hipótese a testar** (confirmada na leitura do firmware e no simulador em out/2026; falta a medida no CS). O ADS8688 precisa só de ~2 µs por amostra (500 kS/s), mas a PRU gasta bem mais: pela contagem estática do `spi_core.asm` (±10%), 32 bits de SCLK de ~16 a 19 ciclos cada (≈ 2,9 µs) mais os três laços de atraso do CS (200 + 100 + 100 iterações de 2 ciclos = 800 ciclos = **4,0 µs**) dão **~7 µs por quadro**, ou seja, ~140 kS/s no papel; o limite que você observou (130 kS/s) está nessa faixa. Executar o próprio `spi_core.asm` num simulador de PRU (`tests/pru_sim.py`, 1 ciclo por instrução, sem hardware) deu o mesmo resultado: **1 395 ciclos = 6,98 µs por quadro (~143 kS/s)** no firmware de out/2026, dos quais **800 ciclos (57 %) são os três laços de atraso do CS** (em geral, 595 + 2 × (S + H + A) ciclos; ver o método 4). É um teto de papel (acessos à memória externa podem somar ciclos): só o osciloscópio (método 2) confirma. Os mínimos do datasheet são 30/10/30 ns (tSU_CSCK, tD_CKCS, tPH_CS); reduza só pelo método 4, medindo. Se for isso, a taxa **real** satura entre 130 e 145 kS/s, **sem perder amostra**, qualquer que seja a taxa pedida, e o firmware de out/2026 conta as **amostras atrasadas** a cada captura. O lado ARM é improvável (130 kS/s = 260 kB/s; cada buffer de 2 MB demora ~8 s para encher).

**Método 1: pelo tom.** 3 blocos em cada taxa pedida (para ter a taxa medida pelo ARM e trocas de buffer dentro do
arquivo; ~20 a 30 s cada), com a senoide de 10,000 kHz do T4 (anote a leitura do contador):

```bash
for taxa in 100000 110000 120000 125000 130000 135000 140000 150000 200000 250000 500000; do
  sudo ./ler_adc $taxa 1 --blocos 3 -o T7e_fs_$taxa.bin -t "T7e fs $taxa" 2>&1 | tee -a T7e_saida_ler_adc.txt
done
grep -E "Integridade|Taxa real" T7e_saida_ler_adc.txt     # uma linha de cada por taxa, na ordem do laço
```

```fish
for taxa in 100000 110000 120000 125000 130000 135000 140000 150000 200000 250000 500000
    uv run scripts/medir_captura.py $DIA/T7e_fs_$taxa.bin --referencia-freq 10000.02 --sem-correcao-sonda --rotulo "T7e fs $taxa" --csv $DIA/resultados.csv
end
```

(sem `--freq`: o tom pode aparecer deslocado quando a taxa real é menor que a pedida; a ferramenta usa o maior pico.) Calcule **`fs_real = fs_pedida × 10000,02 ÷ freq_tom_hz`** (equivale a `fs_pedida ÷ (1 + erro_freq_ppm × 10⁻⁶)`).

**Método 2: pelo CS no osciloscópio (10 min, sem tocar no firmware).** Ponta do MSO46 no **CS** do ADS8688 (e, num segundo canal, no **SCLK**), terra curto, gatilho na borda de descida do CS. Para cada taxa pedida, meça o **período** do CS e a **largura** do nível baixo. A 100 kS/s o período é de 10,00 µs; a 130 kS/s, de 7,69 µs. Se, ao pedir 200 ou 500 kS/s, o período **para de diminuir** perto de ~7 a 8 µs, o limite é o quadro da PRU: anote quanto dura cada parte (CS baixo ≈ 2 µs de setup + ~2,9 µs de 32 bits de SCLK + 1 µs de hold; CS alto ≥ 1 µs). O ADC aguentaria um quadro de ~2 µs: pelo datasheet, a amostra é tomada na borda de descida do CS, a conversão leva até 850 ns (tCONV) e a aquisição pede pelo menos 1,15 µs (tACQ) antes da próxima borda de descida, com SCLK de até 17 MHz.

**Método 4: buscar o extremo das esperas do CS (firmware de out/2026).** É o teste que decide a taxa de trabalho. As
três esperas de cada amostra são dadas ao `ler_adc` em `--atraso-cs S,H,A`, em iterações de 10 ns:

* **S (setup):** do CS descer ao 1º clock (datasheet: tSU_CSCK ≥ 30 ns);
* **H (hold):** do último clock ao CS subir (tD_CKCS ≥ 10 ns);
* **A (alto):** o CS em nível alto entre duas amostras (tPH_CS ≥ 30 ns).

O padrão `200,100,100` (2/1/1 µs) foi calibrado empiricamente, na época dos jumpers longos. O piso do datasheet é
**`3,1,3`** (30/10/30 ns, tabela 7.6): abaixo dele o ADC trabalha fora da especificação, mesmo que pareça funcionar,
e a busca não desce além. A conversão (≤ 850 ns) não limita: ela termina durante os 16 bits de comando (1,6 µs),
qualquer que seja o setup.

**Quanto cada conjunto rende.** Pelo simulador da PRU, o quadro mínimo é de **595 + 2 × (S + H + A) ciclos** de 5 ns.
Os 595 ciclos fixos (~3 µs) são os 32 clocks do SPI feitos em software, e por isso nenhuma espera passa de ~330 kS/s
(para ir além, F3: SCLK mais rápido). A última coluna deixa ≥ 10 % de folga, porque o simulador conta 1 ciclo por
instrução e o acesso real à DDR pode custar mais:

| `--atraso-cs` | Quadro mínimo | Taxa máxima (papel) | Maior taxa exata com ≥ 10 % de folga |
|---|---|---|---|
| `200,100,100` (padrão) | 1 395 ciclos = 6,98 µs | 143 kS/s | 125 kS/s |
| `100,50,50` | 995 ciclos = 4,98 µs | 201 kS/s | 160 kS/s |
| `50,25,25` | 795 ciclos = 3,98 µs | 252 kS/s | 200 kS/s |
| `20,10,10` | 675 ciclos = 3,38 µs | 296 kS/s | 250 kS/s |
| `10,5,5` | 635 ciclos = 3,18 µs | 315 kS/s | 250 kS/s |
| `6,2,6` | 623 ciclos = 3,12 µs | 321 kS/s | 250 kS/s |
| `3,1,3` (piso do datasheet) | 609 ciclos = 3,05 µs | 328 kS/s | 250 kS/s |

Ou seja: 250 kS/s é o teto prático com o SPI atual, e já `20,10,10` chega lá. A busca diz se o hardware aguenta.

**Sinal:** o tom de 10,000 kHz do T4 (20 Vpp, canal 1, contador do osciloscópio anotado). Todas as capturas com
`--blocos 3`, para ter a taxa medida pelo ARM e trocas de buffer dentro do arquivo.

*Passo 1: a qualidade contra as esperas, a 100 kS/s.* A 100 kS/s todos os conjuntos cabem no período, então só a
qualidade pode mudar. Aqui só o S e o H mudam o quadro de verdade: depois do A, a PRU espera a próxima amostra com o
CS alto, e a 100 kS/s ele fica alto por mais de 4 µs, qualquer que seja o A. O A é posto à prova no passo 4, quando o
quadro enche o período. Na BeagleBone:

```bash
for cs in 200,100,100 100,50,50 50,25,25 20,10,10 10,5,5 6,2,6 3,1,3; do
  sudo ./ler_adc 100000 1 --blocos 3 --atraso-cs $cs -o T7e_cs_${cs//,/_}.bin -t "T7e cs $cs 100k"
done 2>&1 | tee T7e_passo1.txt
grep -E "Integridade|Taxa real" T7e_passo1.txt     # uma linha de cada por captura, na ordem do laço
```

No computador:

```fish
uv run scripts/medir_captura.py $DIA/T7e_cs_*.bin --freq 10000 --sem-correcao-sonda --inicio 100 --csv $DIA/T7e_cs.csv
```

Com várias capturas, o `medir_captura.py` termina com uma **tabela-resumo**, uma linha por captura: tom, amplitude,
SINAD, SNR, THD, ruído em LSB, DC e maior salto, lado a lado. É nela que se comparam os conjuntos.

Um conjunto **passa** se, comparado com o `200,100,100`:

* o `ler_adc` termina com `Integridade: 0 amostra(s) atrasada(s), 0 buffer(s) sobrescrito(s), 0 quadro(s) com ruído
  no SDO -- tudo certo` (o ruído no SDO é o primeiro sinal de clock ou dado chegando fora de hora);
* a amplitude do tom fica igual em ±0,02 %, e a frequência em ±0,01 ppm;
* SINAD e SNR ficam em ±0,5 dB, THD em ±1 dB, densidade de ruído em ±5 % e DC (`media`) em ±0,1 mV;
* a continuidade fica nos milésimos de amostra.

Para pegar erro de bit que um tom pode esconder, repita os dois menores conjuntos que passaram com a **entrada em
curto**: o ruído e o pico a pico têm de ser os do T1 (0,51 LSB).

*Passo 2 (só se algum conjunto falhar): qual espera importa.* Volte ao último conjunto bom, fixe duas esperas nele e
baixe só a terceira, uma de cada vez (por exemplo, se `10,5,5` passa e `6,2,6` falha: `6,5,5`, depois `10,2,5`, depois
`10,5,6`). Assim se sabe qual tempo o hardware precisa de verdade (o isolador ADuM3150 atrasa os sinais nos dois
sentidos) e qual pode ir ao piso.

*Passo 3: escolher as esperas de trabalho.* Use o **dobro** do menor conjunto que passou em tudo, em iterações, e
nunca menos que `6,2,6` (o dobro do piso). É a margem para temperatura, cabos e outro exemplar da placa. Exemplos:
`3,1,3` passou → `6,2,6`; `10,5,5` foi o último bom → `20,10,10`.

*Passo 4: o teto com as esperas escolhidas.* Suba pelas taxas exatas (fato 6). A de 312,5 kS/s deve falhar e mostra
onde está a borda:

```bash
CS=20,10,10    # as escolhidas no passo 3
for taxa in 125000 160000 200000 250000 312500; do
  sudo ./ler_adc $taxa 1 --blocos 3 --atraso-cs $CS -o T7e_teto_${taxa}.bin -t "T7e teto $taxa cs $CS"
done 2>&1 | tee T7e_passo4.txt
grep -E "Integridade|Taxa real" T7e_passo4.txt
```

```fish
uv run scripts/medir_captura.py $DIA/T7e_teto_*.bin --referencia-freq 10000.02 --sem-correcao-sonda --inicio 100 --csv $DIA/T7e_teto.csv
```

(sem `--freq`: se a PRU não alcançar a taxa, o tom aparece deslocado.) Uma taxa **passa** com:

* `0 amostra(s) atrasada(s)`;
* `Taxa real medida pelo ARM` igual à pedida (sem o aviso "DIFERENTE da pedida");
* `erro_freq_ppm` igual ao das taxas exatas do T4 (o mesmo erro de cristal);
* SINAD e ruído iguais aos do passo 1.

A maior taxa que passa é o **teto medido**. A de trabalho é a maior que passa com ≥ 10 % de folga (a tabela acima).
Se uma taxa que **cabe** no quadro (pela tabela) falhar sem amostras atrasadas, com ruído no SDO ou SINAD pior, o
suspeito é o A, que a 100 kS/s não foi testado: repita essa taxa com o A dobrado (ex.: `20,10,20`).

*Passo 5: confirmar no osciloscópio* (método 2), com as esperas escolhidas e a taxa de trabalho. O período do CS tem
de ser 1/taxa; o CS baixo, (566 + 2 × (S + H)) × 5 ns (5,83 µs no padrão; 3,13 µs com `20,10,10`); o resto do
período é o CS alto. Fotografe a tela, para a anatomia do quadro no relatório.

*Passo 6: usar.* Até virarem o padrão do firmware (`ATRASO_CS_*_PADRAO` em `firmware/memoria_pru.h`, junto com os
testes que fixam o padrão), passe `--atraso-cs` **em toda captura** na taxa nova, inclusive no
`calibrar_sonda.sh --atraso-cs S,H,A`, que o repassa ao `ler_adc` e confere no cabeçalho de cada captura. O que
refazer a partir daí está em [O que refazer com o firmware de out/2026](#o-que-refazer-com-o-firmware-de-out2026).

**Método 3: separar o lado ARM.** Repita o ponto de 130 kS/s (e o de 100 kS/s) (a) gravando em disco, (b) gravando em RAM (`-o /dev/shm/T7e_ram.bin`, 2,6 MB) e (c) com o disco ocupado (`scp` grande em outra janela). Se só (c) gerar eventos de continuidade, o gargalo é de I/O do ARM; se (a), (b) e (c) derem o mesmo, não é o ARM.

**Como ler.**

| Observação | Gargalo provável | Melhoria (ver `improvement-proposals.md`) |
|---|---|---|
| `fs_real` **satura** (130 a 145 kS/s) e o período do CS para de diminuir; continuidade OK; o `ler_adc` acusa amostras atrasadas | Tempo fixo do quadro da PRU (atrasos do CS e bits do SPI) | F2 (atrasos do CS, método 4) e F3 (SPI) |
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
uv run scripts/medir_captura.py $DIA/T8_f120k.bin --freq 20000 --referencia-rms 7.07 --sem-correcao-sonda --ganho $GV --csv $DIA/resultados.csv
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
uv run scripts/medir_captura.py $DIA/T9a_quadrada_2k.bin --freq 2000 --harmonicos 15 --sem-correcao-sonda --ganho $GV --rotulo "T9a sem correcao" --csv $DIA/resultados.csv
uv run scripts/medir_captura.py $DIA/T9a_quadrada_2k.bin --freq 2000 --harmonicos 15 --ganho $GV --rotulo "T9a com perfil" --csv $DIA/resultados.csv
uv run scripts/adc_tool.py $DIA/T9a_quadrada_2k.bin --welch --picos -70 --filtro-passa-alta 500 --ganho $GV -o $DIA/fig_T9a.png
```

**Esperado.** Sem correção, os harmônicos altos saem **bem abaixo** da teoria (o filtro: a 15ª, em 30 kHz, ~−9 a −12 dB abaixo do que seria). Com o perfil do T3, os níveis relativos devem bater com a teoria em ~1 dB até a 15ª harmônica (30 kHz). É a demonstração mais convincente de que o perfil funciona. Compare com a FFT do osciloscópio (mesma janela de tempo).

**T9b: dois tons e resolução.** 20,0 kHz e 20,3 kHz, mesma amplitude, somadas pela função *Combine* do SDG1032X (CH1 + CH2) ou com dois resistores de 1 kΩ (cada tom fica com metade da amplitude do gerador). Com o gerador a 20 Vpp em cada canal e a soma resistiva, saem 5 V de pico por tom no nó (0,26 V no pino, −32 dBFS). O Welch com `--resolucao-welch 200` não separa; com `--resolucao-welch 50` separa. Mede o limite de resolução do método. Produtos de intermodulação (19,7 e 20,6 kHz) mostram a linearidade.

**T9c: fundamental forte e supraharmônicos fracos.** O caso real: **60 Hz** a ~9 V de pico no gerador (18 Vpp; 0,47 V no pino) somado a 9 kHz em −60 dBc (9 mV de pico), 25 kHz em −50 dBc (28 mV) e 40 kHz em −40 dBc (90 mV). Gerador arbitrário de 2 canais ou dois geradores com somador resistivo. Os tons fracos têm 1,5 a 15 LSB de pico no pino (9 a 90 mV de pico na entrada do divisor, onde 1 LSB vale 6 mV): só aparecem na FFT porque o ganho de processamento deixa o ruído por bin em ~7 µV na entrada. **Meça cada fonte sozinha** no osciloscópio (em amplitude maior) para saber os níveis reais; depois some. O DAC do gerador tem 14 bits (1,2 mV de passo em 20 Vpp): confira que a soma não distorce.

```fish
uv run scripts/adc_tool.py $DIA/T9c.bin --welch --janela hann --filtro-passa-alta 2000 --picos -100 --ganho $GV -o $DIA/fig_T9c_welch.png
uv run scripts/adc_tool.py $DIA/T9c.bin --fft --janela hann --ganho $GV -o $DIA/fig_T9c_fft.png
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
uv run scripts/medir_captura.py $DIA/T10_0_1k_N10.bin --sem-correcao-sonda --ganho $GI --freq 1000 --referencia-rms 1.16
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
* O script confere cabeçalho, CRC e tamanho do arquivo, que valem sim. Depois da primeira rodada, use `--modo refinar --pontos 4` para acrescentar pontos onde o ganho mais varia (ressonâncias do SCT013 em alta frequência) e `--modo adensar` se a curva for acidentada. Mais detalhes em [`user-guide.md`](user-guide.md#sondas-de-corrente-calibração-e-correção).

**Quanto sinal sobra (ordem de grandeza, ruído branco do ADC, N = 10 e 116 mA RMS, faixa de ±2,56 V).** Tom de 70 µV em 1 kHz: ~55 a 57 dB acima do ruído por bin com 10 s (erro de amplitude por ruído ~0,2%); em 20 kHz (−4 dB do filtro): ~51 dB (0,3%); em 40 kHz (−17 dB): ~38 a 40 dB (1%); com 4 blocos (42 s) cada ponto ganha ~6 dB (em 40 kHz: ~0,6%). Em ±10,24 V seriam 9 dB a menos (46 a 48; 42; 29 a 31 dB; erros de 0,5%; 0,8%; 3%). Interferência real (60 Hz e harmônicos, rádio) vai piorar isso: o `gerar_perfil_sonda.py` avisa quando o tom de um ponto não passa 20 dB acima do piso por bin; refaça esses pontos com mais blocos ou mais espiras.

**Passo 1b: variante com `.m` do osciloscópio.** Em vez de digitar o RMS, salve a forma de onda da TCP0030A (em A) de cada ponto como `.m` (ou `.mat`/`.csv`) com o **mesmo nome base da captura** (`calibracao_1000Hz_rep1.m`), com pelo menos 10 ciclos e 20 amostras por ciclo. O `calibrar_sonda.sh` é o mesmo comando do passo 1, **sem** `--ref-externa` (nesse modo ele não pede nenhum valor a cada ponto: só captura; ou use `--ref-externa` e salve também o `.m`, para ter as duas referências e poder compará-las). A amplitude de cada `.m` entra no passo 2, com `--referencia-osciloscopio` no lugar de `--referencia-externa`. A amplitude de referência vem do ajuste de senoide por mínimos quadrados (IEEE 1057), que usa todos os ciclos e é melhor que o RMS lido do painel.

**Passo 1c: amplitude "conhecida" não se aplica aqui** (a corrente não é `V_gerador ÷ R`: o resistor de fio enrolado e os 50 Ω de saída deixam o valor dependente da frequência). Só use `--amplitude ...Apk` se tiver medido a corrente na TCP0030A numa frequência e souber que o gerador é plano. Em **tensão** o método vale, e a variante do T3 já usa esse raciocínio.

**Conferir o método (uma medição com amplitude conhecida e `.m`).** Antes da coleta completa, ou com uma captura que você já tenha, verifique se o método devolve a amplitude certa:

```fish
# SEM correção: ADC/osciloscópio mostra o ganho do conjunto nessa frequência, com a corrente real vinda do .m da TCP0030A (A)
uv run scripts/medir_captura.py captura.bin --sem-correcao-sonda --osciloscopio captura.m --osc-unidade A --osc-escala 10 --ganho $GI --rotulo "metodo 12kHz" --csv $DIA/resultados.csv
```

(`--osc-escala 10` = N espiras: o valor do osciloscópio é multiplicado por 10.) Com o perfil pronto, repita **com** a correção: ADC ÷ osciloscópio deve dar ~1 numa frequência que não entrou na calibração.

**Linearidade (faça no meio da coleta).** Em 1 kHz, capture 5 amplitudes (gerador em 2, 5, 10, 15 e 20 Vpp; o SNR cai nas menores) e 3 valores de N (5, 10, 20): o ganho **não** pode depender da amplitude nem de N. Se depender da amplitude, o SCT013 satura ou o resistor aquece.

**Ponto de 60 Hz com a corrente da rede (opcional, com supervisão).** Com transformador de isolamento, **127 V** sobre os **dois resistores de 22,12 Ω em série** (44,24 Ω) dá **2,87 A RMS** (cada resistor com 63,5 V e 182 W, dentro dos 93 V e 400 W). Fio **uma só vez** (N = 1, a configuração de produção) pela TCP0030A (ainda na faixa de 5 A, exatidão de ±1% a 60 Hz) e pelo SCT013: o sinal é de 172 µV RMS (0,55 LSB), ~55 dB acima do ruído por bin. É o melhor ponto de ancoragem do ganho em baixa frequência. **Nunca 220 V** (110 V por resistor, acima dos 93 V) e confira o aquecimento.

**Passo 2: gerar o perfil (no computador).** Copie `capturas/sct013_100a_sn001/` para `$DIA/capturas/` (com os `.m` do osciloscópio, se houver) e rode:

```fish
uv run scripts/gerar_perfil_sonda.py $DIA/capturas/sct013_100a_sn001 --referencia-externa \
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
uv run scripts/medir_captura.py $DIA/H_27kHz.bin --ganho $GI --freq 27000 --referencia-rms 1.12 --rotulo "H 27kHz" --csv $DIA/resultados.csv
```

O `erro_amplitude_pct` do CSV é o erro do **sistema corrigido** contra a TCP0030A, nas frequências de validação. Repita com `--sem-correcao-sonda` para mostrar o quanto a correção melhora.

**Esperado.** Sem correção, o erro em 40 kHz será de dezenas de % (filtro do ADC mais a banda do SCT013). Com correção, deve cair para **poucos %**, limitado por: exatidão da TCP0030A (±1,5% até 5 kHz e **sem especificação** acima: some a incerteza do osciloscópio de ±1%), SNR (~0,2% até 20 kHz e ~1% em 40 kHz em ±2,56 V), interpolação entre pontos (0,17% com 18 pontos, 0,06% com 25, para curvas suaves; ver [`probe-profile-audit.md`](probe-profile-audit.md)) e repetibilidade (o desvio entre repetições aparece no próprio perfil). A correção restaura a **amplitude**, não a fase: não use o canal corrigido para potência por componente.

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
uv run scripts/adc_tool.py $DIA/T11a.bin --welch --janela hann --filtro-passa-alta 20 --picos -90 --ganho $GV -o $DIA/fig_T11a.png

# Um comando por tom: --freq escolhe o tom (busca em ±10%) e --referencia-rms é o RMS medido SOZINHO (V no nó de entrada)
uv run scripts/medir_captura.py $DIA/T11a.bin --freq 60    --referencia-rms 4.24  --ganho $GV --rotulo "T11a 60Hz"  --csv $DIA/resultados.csv
uv run scripts/medir_captura.py $DIA/T11a.bin --freq 2000  --referencia-rms 1.06  --ganho $GV --rotulo "T11a 2kHz"  --csv $DIA/resultados.csv
uv run scripts/medir_captura.py $DIA/T11a.bin --freq 9000  --referencia-rms 0.354 --ganho $GV --rotulo "T11a 9kHz"  --csv $DIA/resultados.csv
uv run scripts/medir_captura.py $DIA/T11a.bin --freq 20000 --referencia-rms 0.106 --ganho $GV --rotulo "T11a 20kHz" --csv $DIA/resultados.csv
uv run scripts/medir_captura.py $DIA/T11a.bin --freq 40000 --referencia-rms 0.035 --ganho $GV --rotulo "T11a 40kHz" --csv $DIA/resultados.csv
```

(Confira que a coluna `correcao_sonda` do CSV está `sim`: se estiver vazia, o perfil `cadeia_tensao` não foi achado em `scripts/sondas/` ou a captura não registrou `--sonda 1:cadeia_tensao`. Rode também com `--sem-correcao-sonda` para mostrar o efeito da correção.)

**Esperado.** Cada tom com erro de poucos % contra o valor medido sozinho (o de 40 kHz é o mais sensível: a correção ali amplifica ~17 dB, junto com o ruído), e **nenhum pico espúrio** fora dos tons injetados e de seus harmônicos (intermodulação e aliasing aparecem como picos extras: veja onde caem).

**T11b: corrente composta (só se o T10-0 e o T10 deram SNR suficiente).** Dois tons de corrente pelo SCT013 com N = 10, do mesmo circuito do T10 (resistor de 10,92 Ω): **1 kHz** (12 Vpp no gerador, ~70 mA RMS) e **20 kHz** (8 Vpp, ~46 mA RMS), somados pelo Combine ou por forma arbitrária. Meça **cada tom sozinho** na TCP0030A (RMS × N) e depois os dois juntos, **só o canal 0**, a 100 kS/s:

```bash
sudo ./ler_adc 100000 0 --faixa-adc 0:5.12 --blocos 4 -o T11b.bin -t "T11b corrente composta" --grandeza 0:corrente --sonda 0:sct013_100a_sn001
```

```fish
# --referencia-rms = N x I_rms do tom medido sozinho (aqui N=10: 70 mA -> 0.70 e 46 mA -> 0.46)
uv run scripts/medir_captura.py $DIA/T11b.bin --freq 1000  --referencia-rms 0.70 --ganho $GI --rotulo "T11b 1kHz"  --csv $DIA/resultados.csv
uv run scripts/medir_captura.py $DIA/T11b.bin --freq 20000 --referencia-rms 0.46 --ganho $GI --rotulo "T11b 20kHz" --csv $DIA/resultados.csv
```

Mesmo critério do T11a, com o SNR por bin do T10 (cada tom precisa de ≥ 30 dB acima do piso). Aqui N = 10 serve só para ter sinal: com N = 1 (o uso real) os tons ficam 20 dB mais fracos (veja o piso de detecção do T10).

**T11c: carga real (opcional, exige supervisão).** Uma carga chaveada (fonte de computador, carregador, driver de LED, dimmer) na rede de **127 V** (nunca 220 V: o divisor satura), com **transformador de isolamento** e o osciloscópio isolado. Capture 10 s no canal de tensão e compare a lista de picos do `--welch --picos` (com a correção) com a FFT do osciloscópio nos mesmos picos (frequência e amplitude): a frequência de chaveamento e seus primeiros harmônicos, **até 45 kHz**. É o teste mais próximo do uso real. A corrente da carga também pode ser capturada (SCT013 com 1 espira, canal 0), mas os supraharmônicos de miliampères ficam **abaixo do piso** (ver T10): só os de 60 Hz e seus primeiros harmônicos aparecem; registre isso.

**Para o relatório.** Tabela dos tons de T11a e T11b (valor injetado, medido, erro %); figura com os espectros ADC × osciloscópio de T11c.

---

## Dados e figuras para o relatório

A coluna "Situação" diz o que já existe (✅), o que existe mas tem de ser refeito (🟡) e o que falta (⏳).

| Item | Origem | Situação |
|---|---|---|
| Foto da bancada e diagrama de ligações de cada teste; lista de instrumentos com modelo, exatidão e data da última calibração; valor do capacitor removido | Todos | ⏳ (a lista de instrumentos está em `bench-notes.md`) |
| Escala do ADC conferida nas três faixas (razão `media` ÷ `V_in × 0,05157`); transitório de troca de faixa | T0 | ✅ tabela no T0 |
| Ruído em LSB, µV e nV/√Hz × taxa e nº de canais; **ruído × faixa de entrada**; PSD do curto; ruído equivalente na entrada de cada cadeia | T1 | ✅ tabela no T1; ⏳ PSD |
| Razão real do divisor e offset; resíduo de linearidade em LSB | T2 | ✅ tabela no T2; ⏳ gráfico |
| **Perfil da cadeia de tensão** (dB × Hz, −3 dB) e o ajuste do passa-baixa (K, f0, Q, resíduos): `report/gerar_figuras.py` | T3 | ✅ `report/figures/` |
| Erro da taxa de amostragem (ppm) × taxa pedida | T4 | 🟡 tabela no T4, sem o contador |
| SINAD/ENOB × nível; THD, SINAD e SFDR × frequência; faixa dinâmica | T5 | ⏳ (prévia no T5) |
| Diafonia e atraso entre canais | T6 | 🟡 tabela no T6; falta 20 kHz |
| Tabela de continuidade (eventos, salto máximo) por taxa e carga; deriva em 10 min; **salto de 6,97 µs a cada bloco antes da correção** (figura: fase do tom × tempo ao redor de uma troca, antes e depois) | T7 | 🟡 tabela do firmware antigo no T7; falta o depois |
| **Taxa real × taxa pedida (limite de ~140 kS/s), período do CS, gargalo; taxa máxima × atrasos do CS** | T7e | ⏳ |
| Rejeição de aliasing × frequência (e o que sobra do 50–150 kHz) | T8 | ⏳ |
| Quadrada: teoria × ADC × perfil × osciloscópio; menor tom detectável; resolução de dois tons | T9 | ⏳ |
| **Perfil da sonda de corrente** (curva, pontos, desvios); validação hold-out (erro % com e sem correção); linearidade (amplitude e N); piso de detecção | T10 | ⏳ |
| Tons compostos e carga real: ADC × osciloscópio | T11 | ⏳ |
| `resultados.csv` de cada dia, os `.bin` (arquivar sem perdas com `uv run scripts/compactar_amostras.py PASTA_DO_DIA`: ~11 % do tamanho, conferido pelo SHA-256) e os prints do osciloscópio | Todos | 🟡 19/10: `.bin` e `resultados.csv`; faltam os prints |

**Sugestão de estrutura:** uma tabela "requisito do projeto → teste → resultado → critério" com os testes T7 (não perder dados e limite de taxa), T10 (perfil da sonda), T3 (banda de supraharmônicos de tensão) e T11 (ponta a ponta).

**Declare no relatório** as limitações que você encontrou: a taxa de trabalho de 100 kS/s (teto de ~140 kS/s no firmware atual) e, com ela, a banda coberta (até 45 kHz de 150 kHz) e o aliasing do que está acima; o filtro de 15 kHz do ADC e sua correção (que amplifica o ruído); a baixa sensibilidade do canal de corrente (60 µV/A) e o piso de detecção resultante (mesmo na menor faixa do ADC, ±2,56 V); a faixa de ±10,24 V do canal de tensão, sem margem para reduzir (127 V RMS = 91%); o aliasing de componentes acima de Nyquist; a taxa de amostragem real; a exatidão do osciloscópio e da TCP0030A (sem especificação acima de 5 kHz); o fato de a correção de sonda restaurar só a amplitude (não a fase); o transitório de ~60 µs depois de trocar a faixa de um canal; e que as capturas de 19/10 têm o salto de 6,97 µs a cada bloco do firmware antigo (as análises de um bloco não são afetadas; as de fase e de continuidade, sim). **Sugestões de melhoria** que saem daqui: reduzir as esperas do CS e acelerar o SPI da PRU (T7e) para chegar a ≥ 300 kS/s; mais ganho (ou carga maior) antes do ADC no canal de corrente; um anti-aliasing externo mais forte.

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
| Ruído muito acima de 1 LSB | Jumper longo entre a placa de aquisição e o frontend; fonte ruidosa; USB | Veja "Preparar a BeagleBone" no [guia](user-guide.md); desligue o que não precisa |
| Tensão lida pela **metade** (ou o dobro) do que o Fluke mostra | `--faixa` digitado diferente da do cabeçalho (a ferramenta avisa), ferramentas anteriores a out/2026 numa captura antiga (v1/v2: liam 10.24), ou escala-base do ADC diferente da suposta | Omita `--faixa` (vale a do cabeçalho; nas v1/v2, a faixa de reset, 20.48); atualize o repositório; refaça o T0, passo 6 |
| Amplitude no ADC o dobro (ou a metade) do esperado, só com o gerador | Gerador em 50 Ω com carga High-Z (ou o contrário) | Ajuste a carga do gerador (High-Z) e **leia o osciloscópio**, não o painel |
| `saturou o ADC` | Amplitude acima da faixa pedida (rede de 220 V; `--faixa-adc 1:10.24` com 127 V; ou o canal de corrente em ±2,56 V com sinal alto) | Reduza o sinal ou aumente a faixa (`--faixa-adc`); no canal de tensão, ±10,24 V cobre até 140 V RMS |
| `sinal fraco` em todo ponto do canal de tensão | Máximo de 5% da escala pelo divisor | Esperado; aceite com `C` |
| `praticamente sem sinal` em todo ponto do canal de corrente | Sensibilidade de 60 µV/A (limiar 0,2% da escala = ~10 mV pico a pico em ±2,56 V) | Esperado: digite `C` (ENTER refaz). Confira o SNR com o T10-0 |
| Sinal de corrente nulo (só ruído) mesmo com N = 20 | SCT013 aberto ou fora da garra; fio fora do centro; resistor de 0,12 Ω ou resistores em série dessoldados; gerador desligado | Confira a ligação com a TCP0030A; meça a tensão sobre o 0,12 Ω com o osciloscópio |
| Perfil de tensão com ganho de baixa frequência ~0,05 (em vez de ~1) | `--amplitude` em volts na **entrada** do divisor com `--ganho 19.357` | Informe a amplitude do **pino** (1,0332Vpp) ou use `--referencia-externa` |
| `frequência medida fora da planejada` | Gerador mal ajustado, ou taxa pedida ≠ gerada | Confira o contador do osciloscópio; veja T4 |
| O tom aparece em outra frequência acima de ~140 kS/s | A PRU não alcança a taxa pedida (T7e) | Calcule `fs_real` e use só taxas até 100 kS/s |
| Perfil com ganho de 1,0 em baixa frequência muito diferente (ex.: 0,1) | `--ganho` diferente de 1/sensibilidade | Use o ganho certo (divisor: 19,357; SCT013 sobre 0,12 Ω: 16 667) |
| Perfil "dentes de serra" ou pontos fora da curva | Gerador instável; resistor aquecendo; ponta mal compensada; TCP0030A sem zero/DEGAUSS | Refaça os pontos (`R`); repita com `--repeticoes`; compense a ponta |
| `ler_adc` trava | PRU parada | `dmesg`; `./setup.sh` |
| `ler_adc` termina com código 3 e a linha `Integridade:` acusa **buffers sobrescritos** | O ARM não gravou um bloco antes de a PRU voltar a ele: amostras perdidas e um bloco misturado | Captura inválida. Grave em RAM (`-o /dev/shm/...`) ou num disco mais rápido; feche o que estiver usando o disco; T7e, método 3 |
| A linha `Integridade:` acusa **amostras atrasadas** | A taxa pedida passou do que a PRU alcança (~140 kS/s com os atrasos de CS padrão) | A taxa real é menor que a do cabeçalho: use a que o `ler_adc` imprime ou fique em ≤ 100 kS/s. Esperado no T7e |
| A linha `Integridade:` acusa **quadros com ruído no SDO** | Ruído ou reflexo na linha de dados (o problema dos jumpers longos) | Encurte e reforce as ligações entre a BeagleBone e a placa; as amostras desses quadros são suspeitas |
| `DESCONTINUIDADE ... numa troca de buffer da PRU` (~0,7 amostra a 100 kS/s, ~0,35 com 2 canais) | Firmware anterior a out/2026 | `./setup.sh` e refaça a captura; nas antigas, analise um bloco por vez (`--inicio`/`--max-amostras`) |
| Ruído do T1 de 4 a 6 LSB numa faixa nova, mas normal nas outras | Transitório das primeiras ~6 amostras depois de trocar a faixa | `--inicio 100` |
| Tom em frequência inesperada com vários canais (ex.: 40 kHz aparece em 10 kHz) | Acima da Nyquist **do canal** (taxa ÷ nº de canais ÷ 2) | Reduza a frequência ou o número de canais |
| Disco cheio | Capturas longas | `df -h`; copie e apague; `calibrar_sonda.sh` pausa abaixo de 50 MB |

---

## Checklist ao sair do laboratório

- [ ] Todos os `.bin` copiados para o computador (e **também** em um segundo lugar: `uv run scripts/compactar_amostras.py $DIA`, e o pacote em dois lugares) e o tamanho conferido.
- [ ] A saída de terminal do `ler_adc` de cada captura guardada (a linha `Integridade:` e a taxa real medida não ficam só no cabeçalho).
- [ ] `resultados.csv` do dia salvo, com uma linha por canal medido.
- [ ] Pastas `capturas/cadeia_tensao/` e `capturas/sct013_100a_sn001/` em `$DIA/capturas/` (incluem `referencia_externa.csv` e `plano_coleta.txt`) copiadas, junto com o `.m` do osciloscópio de cada ponto (mesmo nome da captura) e as leituras da TCP0030A.
- [ ] Escala do ADC conferida no T0 (razões das três faixas) e a tabela de ruído por faixa do T1; os valores de `$GV` e `$GI` realmente usados nos perfis e a faixa de cada canal (`--faixa-adc`) anotados.
- [ ] Perfis `scripts/sondas/cadeia_tensao.json` e `scripts/sondas/sct013_100a_sn001.json` gerados e validados (T3, T10), e os PNG das curvas.
- [ ] Limite de taxa (T7e): tabela `fs_real` × taxa pedida, período do CS, saída do `ler_adc`.
- [ ] Leitura do contador de frequência do osciloscópio anotada em cada teste com tom (sem ela o T4 não separa o cristal do gerador).
- [ ] Fotos da bancada (e da placa antes de remover o capacitor) e prints do osciloscópio de cada teste (com a escala visível).
- [ ] Caderno: instrumentos e ajustes, temperatura, anomalias, o que **ficou por fazer**; o que estava ligado em cada canal (inclusive os que não são o 0 e o 1).
- [ ] A tabela [Estado da campanha](#estado-da-campanha) atualizada.
- [ ] Hipóteses confirmadas ou refutadas: escala e faixas do ADC (T0, T1), filtro de 15 kHz (T3), taxa real e ticks (T4), diafonia (T6), perda de amostras e gargalo (T7), sensibilidade de 60 µV/A (T10-0).
- [ ] Se algo mudou (outro `--ganho`, outro canal, nova taxa, outro número de espiras), anote: o perfil só vale para a cadeia em que foi medido.
