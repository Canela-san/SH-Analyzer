# Roteiro de laboratório

Lista de testes para validar o SH-Analyzer **de ponta a ponta** (ADC, firmware/PRU, frontend, sonda de corrente e software), com o sinal a injetar em cada um, os comandos exatos, o que anotar no osciloscópio e o que esperar. Feito para sair do laboratório com **dados que entram direto no relatório**.

Pré-requisito: [`guia_de_uso.md`](guia_de_uso.md) (capturar e analisar). Este roteiro supõe que você já sabe rodar `ler_adc` e `adc_tool.py`.

**Índice**

1. [Antes de ir: o que o datasheet e o código já dizem](#antes-de-ir-o-que-o-datasheet-e-o-código-já-dizem)
2. [Equipamentos, segurança e boas práticas](#equipamentos-segurança-e-boas-práticas)
3. [Convenções e a ferramenta `medir_captura.py`](#convenções-e-a-ferramenta-medir_capturapy)
4. [Plano: ordem, tempo e prioridade](#plano-ordem-tempo-e-prioridade)
5. [Os testes](#os-testes): [T0](#t0-preparação-e-sanidade) · [T1](#t1-piso-de-ruído-entrada-em-curto) · [T2](#t2-tensão-contínua-ganho-offset-e-linearidade) · [T3](#t3-resposta-em-frequência-da-cadeia) · [T4](#t4-frequência-de-amostragem-real) · [T5](#t5-distorção-e-faixa-dinâmica) · [T6](#t6-vários-canais-diafonia-e-atraso) · [T7](#t7-integridade-em-taxas-altas) · [T8](#t8-aliasing) · [T9](#t9-sinais-de-espectro-conhecido) · [T10](#t10-perfil-da-sonda-de-corrente) · [T11](#t11-ponta-a-ponta)
6. [Dados e figuras para o relatório](#dados-e-figuras-para-o-relatório)
7. [Critérios de aceitação](#critérios-de-aceitação)
8. [Problemas de bancada](#problemas-de-bancada)
9. [Checklist ao sair do laboratório](#checklist-ao-sair-do-laboratório)

---

## Antes de ir: o que o datasheet e o código já dizem

Cinco fatos mudam o planejamento. Todos devem ser **confirmados** nos testes indicados.

**1. O ADS8688 tem um filtro passa-baixa de 2ª ordem em cada canal, com corte de ~15 kHz.** Está no datasheet do repositório ([`Datasheets/ads8688.pdf`](Datasheets/ads8688.pdf), seção 8.3.5 e Figura 55; tabela de características dinâmicas: banda de pequenos sinais de **−3 dB em 15 kHz** e de −0,1 dB em 2,5 kHz). É um anti-aliasing embutido, e não dá para desligar. Consequência para a banda de supraharmônicos (2–150 kHz): o sinal chega ao conversor **muito atenuado**. Uma estimativa grosseira, entre um filtro de dois polos reais e um Butterworth de 2ª ordem:

| Frequência | 10 kHz | 15 kHz | 30 kHz | 50 kHz | 100 kHz | 150 kHz | 200 kHz |
|---|---|---|---|---|---|---|---|
| Atenuação estimada | −1 dB | −3 dB | −8 a −12 dB | −15 a −21 dB | −26 a −33 dB | −33 a −40 dB | −37 a −45 dB |

Os números reais só saem do **T3**. Daí vêm três decisões deste roteiro: (a) o perfil da cadeia (sonda **mais** frontend **mais** ADC) precisa ser medido até a maior frequência de interesse; (b) a correção por perfil amplifica o ruído na mesma proporção (+30 dB em 100 kHz), o que limita a menor amplitude detectável lá; (c) o anti-aliasing é fraco: componentes de 200 a 500 kHz de um conversor chaveado só caem uns 40 dB e **dobram para dentro da banda** (T8).

**2. A frequência de Nyquist de cada canal é a taxa total ÷ número de canais ÷ 2.** Para chegar a 150 kHz é preciso **1 canal** e taxa de pelo menos ~400 kS/s (Nyquist 200 kHz). Com 2 canais em 500 kS/s, o limite é 125 kHz. Por isso a calibração da sonda é feita com **um canal só** e a corrente real vem do osciloscópio ([T10](#t10-perfil-da-sonda-de-corrente)).

**3. A taxa de amostragem real pode diferir da pedida.** O `ler_adc` calcula `ticks = 200 MHz ÷ taxa` com divisão **inteira**. Taxas que dividem 200 MHz exatamente (100, 200, 250, 400 e 500 kS/s) saem exatas; as outras não:

| Taxa pedida | Ticks | Taxa gerada | Diferença |
|---|---|---|---|
| 100 000 | 2000 | 100 000 | 0 |
| 102 400 | 1953 | 102 406,55 | **+64 ppm** |
| 200 000 | 1000 | 200 000 | 0 |
| 204 800 | 976 | 204 918,03 | +576 ppm |
| 250 000 | 800 | 250 000 | 0 |
| 300 000 | 666 | 300 300,30 | **+1001 ppm** |
| 400 000 | 500 | 400 000 | 0 |
| 500 000 | 400 | 500 000 | 0 |

Isso desloca todas as frequências medidas pela mesma razão (um tom de 10 kHz aparece em 9 999,36 Hz a 102,4 kS/s). Além disso, o relógio de 200 MHz da PRU vem do cristal da BeagleBone, que tem erro de dezenas de ppm. É uma hipótese a confirmar no [T4](#t4-frequência-de-amostragem-real). **Recomendação: use 400 kS/s** (ou 100, 200, 250 ou 500) nos testes de exatidão.

**4. O osciloscópio é referência excelente para tempo e frequência, mas não para amplitude.** Um osciloscópio de 8 bits tem exatidão vertical típica de 1 a 2%. Os erros do ADC abaixo disso **não aparecem** numa comparação direta. Para amplitude, use um **multímetro de bancada true-RMS** (de 6½ dígitos, com banda de AC até 100 kHz ou mais) sempre que a frequência permitir, e o osciloscópio de GS/s para o resto. Registre no relatório a exatidão de cada instrumento.

**5. Um gerador de funções comum não serve para medir THD de um ADC de 16 bits.** O ADS8688 tem THD de −102 dB (típico, 1 kHz); geradores comuns têm −50 a −70 dBc, e o osciloscópio de 8 bits não enxerga abaixo de uns −50 dBc. O T5 explica o que fazer (filtro passa-faixa no gerador, ou fonte de baixa distorção).

> **Fora do roteiro, mas relevante:** se o canal de **tensão** usa o transdutor LV 25-P (o datasheet está em `Datasheets/LV25-P.PDF`), ele informa tempo de resposta de 40 µs (equivalente a algo como 9 kHz de banda). Confirme qual sensor está na sua placa. O T3 mede a cadeia de tensão inteira, qualquer que seja ela.

---

## Equipamentos, segurança e boas práticas

### O que levar

| Item | Para quê |
|---|---|
| Gerador de funções/arbitrário (2 canais, de preferência) | Todos os tons. Anote modelo, frequência máxima, THD e exatidão de frequência |
| Osciloscópio de GS/s, com ponta ×10 compensada e contador de frequência | Referência de frequência, forma de onda, RMS e FFT |
| Multímetro de bancada true-RMS (6½ dígitos, se houver) | Referência de DC e de amplitude AC até ~100 kHz |
| Fonte DC ajustável | T2 |
| Resistores de precisão não indutivos: shunt (0,1 a 10 Ω, 0,1 a 1%) e resistores de 1 kΩ | T10, T9c (somador), terminações |
| Terminadores BNC de 50 Ω, curto BNC, conectores T de BNC | T1, T6 |
| Sonda de corrente e sua alimentação (Hall precisa de fonte e de "zero") | T10 e T11 |
| Medidor LCR ou analisador de impedância (opcional) | Conferir a indutância do shunt |
| Amplificador de potência (opcional) | Corrente acima de ~0,1 A em alta frequência |
| Transformador de isolamento 1:1 e osciloscópio isolado ou ponta diferencial | **Só** para o T11 com carga real na rede |
| Notebook com este repositório e `uv`; cabo USB/Ethernet para a BeagleBone | Análise |

### Segurança

* **Limite do ADC.** A faixa configurada (`--faixa 10.24`) é de **±5,12 V**. O datasheet dá ±20 V como máximo absoluto na entrada, e apenas **±11 V se o ADC estiver sem alimentação** (AVDD flutuando). Nunca injete sinal com a placa desligada. Comece sempre com amplitude mínima no gerador e suba.
* **Rede elétrica.** Só na etapa final (T11), com supervisão do orientador ou do técnico. A BeagleBone, o notebook e o osciloscópio estão ligados à terra: a garra de terra da ponta **em curto com a terra** de qualquer ponto da rede danifica o equipamento e machuca. Use transformador de isolamento, ponta diferencial ou osciloscópio isolado. O isolamento galvânico do frontend (DAQ_Module) protege o ADC, não o osciloscópio.
* **Sonda de corrente.** Não passe condutor energizado pela garra de uma sonda Hall sem conferir a corrente máxima dela. Em baixa tensão (gerador + shunt), não há risco.
* Desligue a saída do gerador antes de trocar ligações.

### Boas práticas de medição

* **Impedância do gerador.** A saída é de 50 Ω. A entrada do ADS8688 é de 1 MΩ: ajuste o gerador para carga **"High-Z"** (senão a amplitude mostrada no painel sai com o dobro do valor real) ou, melhor, **ignore o painel** e leia a amplitude real no osciloscópio/multímetro, no mesmo nó que o ADC.
* **Mesmo nó.** Ponta do osciloscópio e entrada do ADC ligadas no mesmo ponto (conector T de BNC). Cabos curtos (menos de 1 m) para 150 kHz não têm problema de linha de transmissão.
* **Terra.** Um só ponto de terra. Se aparecer zumbido de 50/60 Hz, veja [Problemas de bancada](#problemas-de-bancada).
* **Aquecimento.** Ligue tudo 30 minutos antes (gerador, osciloscópio, BeagleBone e frontend). Deriva térmica entra no resultado.
* **Osciloscópio.** Ponta compensada (ajuste no sinal de calibração); acoplamento DC; limite de banda desligado; sinal ocupando 60% ou mais da tela; use a medida de **RMS em número inteiro de ciclos** (≥ 8 ciclos) com média de 16 aquisições ou mais. Anote a escala vertical usada.
* **Frequência.** Leia a frequência no contador do osciloscópio (ou do multímetro) e use esse valor, não o do painel do gerador. Se o gerador tiver entrada de referência de 10 MHz, ligue-o à saída de referência do osciloscópio.
* **Caderno de laboratório.** Para cada teste: data, hora, temperatura, ajustes do gerador e do osciloscópio, comprimento dos cabos, qual canal, qual taxa. O título gravado na captura (`-t`) já guarda o essencial.

---

## Convenções e a ferramenta `medir_captura.py`

### Nomes e pastas

* **Na BeagleBone** (`firmware/`): `T<n><letra>_<descrição>.bin`, por exemplo `T5a_1k_m6dBFS.bin`, e título curto no cabeçalho com `-t "T5a 1kHz -6dBFS"` (até 63 bytes).
* **No computador:** copie tudo para `lab/AAAA-MM-DD/`. Todos os resultados numéricos vão para **um único** `lab/AAAA-MM-DD/resultados.csv`.
* **Exemplos supõem canal 0 = tensão e canal 1 = saída da sonda de corrente.** Troque pelos seus.
* **Forma de onda do osciloscópio (`.m`).** Salve o arquivo de cada ponto com o **mesmo nome base da captura** (`calibracao_1000Hz_rep1.m` ao lado de `calibracao_1000Hz_rep1.bin`); o `gerar_perfil_sonda.py --referencia-osciloscopio` e o `medir_captura.py --osciloscopio` o encontram sozinhos. Anote o ajuste vertical e se a ponta é 10x (`--osc-escala`).
* **"A sonda" = o conjunto.** Neste projeto, "sonda" e "perfil da sonda" designam o conjunto medido de ponta a ponta (sonda de corrente + frontend/isolador + ADS8688 com o filtro de ~15 kHz). A frequência de corte do filtro do ADC não precisa ser conhecida: aparece na curva medida.
* `dBFS`: 0 dBFS = 5,12 V de **pico** no pino do ADC (faixa de 10,24 V). Tabela de amplitudes para o T5: −0,5 dBFS = 4,83 V pico (9,67 Vpp); −6 dBFS = 2,57 V (5,13 Vpp); −20 dBFS = 0,512 V (1,02 Vpp); −40 dBFS = 51,2 mV (102 mVpp); −60 dBFS = 5,12 mV (10,2 mVpp).

Para copiar as capturas:

```bash
scp 'debian@<ip-da-beaglebone>:caminho/firmware/T*.bin' lab/2026-10-20/
```

### `medir_captura.py` em um minuto

Mede uma ou mais capturas e imprime **números com unidade**, prontos para uma tabela:

```bash
uv run scripts/medir_captura.py lab/2026-10-20/T5a_*.bin --csv lab/2026-10-20/resultados.csv
```

Como o `adc_tool.py`, ele lê frequência, canais e sonda do cabeçalho (e aceita `-f`, `--canais`, `--faixa`, `--ganho`, `--offset`, `--formato`). O que mede, por canal:

| Grandeza | Significado | Onde aparece |
|---|---|---|
| DC, RMS CA, pico a pico, saturação | Estatística básica. Saturação acima de 0,05% das amostras = captura inválida (aviso) | `media`, `rms_ca`, `pico_a_pico`, `saturacao_pct` |
| Densidade de ruído, ruído em LSB | Piso de ruído (mediana do espectro). 1 LSB = faixa × ganho ÷ 65536 | `densidade_ruido_por_rthz`, `ruido_rms_lsb` |
| Tom | Frequência e amplitude (pico e RMS) do maior pico espectral, em FFT com janela Kaiser sobre a captura inteira | `freq_tom_hz`, `amplitude_pico`, `amplitude_rms` |
| Harmônicos e THD | Soma das potências dos harmônicos (até `--harmonicos`, padrão 9) sobre a fundamental, em dB. Harmônicos acima de Nyquist são medidos na frequência **dobrada** (marcados `[alias]`) | `thd_db`, `thd_pct` |
| SINAD, SNR, ENOB | Sinal ÷ (ruído + distorção); sinal ÷ ruído; bits efetivos, **corrigidos** para um tom abaixo do fundo de escala | `sinad_db`, `snr_db`, `enob_bits` |
| SFDR | Fundamental ÷ maior espúrio, em dBc, com a frequência do espúrio e se ele é um harmônico | `sfdr_dbc`, `freq_espurio_hz`, `ordem_espurio` |
| Continuidade | Maior salto de fase do tom entre segmentos, em **amostras equivalentes**. Uma amostra perdida ou duplicada vale ~1,0 | `salto_max_amostras`, `saltos_acima_do_limite`, `variacao_amplitude_pct` (variação da amplitude do tom entre segmentos) |
| Acoplamento (≥ 2 canais) | Amplitude de cada canal no tom do canal mais forte (diafonia, dB) e atraso entre canais (µs) | `diafonia_db`, `atraso_medido_us`, `atraso_esperado_us` |
| Comparação com instrumento | `--referencia-rms` (RMS lido, na unidade do canal) e `--referencia-freq` (Hz): erro em % e em ppm. `--amplitude-referencia` (`500mVpp`; padrão: a dos metadados) e `--osciloscopio` (o `.m`): ADC ÷ injetado, ADC ÷ osciloscópio e osciloscópio ÷ injetado | `erro_amplitude_pct`, `erro_freq_ppm`, `razao_vs_amplitude_ref`, `razao_vs_osc`, `osc_vs_amplitude_ref_pct` |

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
| `--inicio N`, `--max-amostras N` | Janela de análise, por canal (padrão: as primeiras 4 194 304 amostras, ≈ 10 s a 400 kS/s) |

**Limites do método** (para citar no relatório): usa uma FFT única sobre até 4 M amostras com janela Kaiser (β = 14), cujo vazamento limita o SINAD medido a ~110 dB (acima do ADC de 16 bits, com folga); um tom a menos de ~13 bins do DC (captura curta demais para tom muito grave) sai impreciso e a ferramenta avisa; só enxerga harmônicos que não coincidem entre si depois de dobrados.

---

## Plano: ordem, tempo e prioridade

| Teste | O que valida | Tempo | Dia sugerido |
|---|---|---|---|
| [T0](#t0-preparação-e-sanidade) | Bancada, firmware, cabeçalho | 20 min | 1 |
| [T1](#t1-piso-de-ruído-entrada-em-curto) | Ruído, offset, ruído vs taxa e nº de canais | 30 min | 1 |
| [T2](#t2-tensão-contínua-ganho-offset-e-linearidade) | Ganho real, offset, linearidade | 40 min | 1 |
| [T3](#t3-resposta-em-frequência-da-cadeia) | **Resposta em frequência da cadeia de tensão** (filtro de 15 kHz) | 60-90 min | 1 |
| [T4](#t4-frequência-de-amostragem-real) | Taxa de amostragem real (ppm) | 30 min | 2 |
| [T5](#t5-distorção-e-faixa-dinâmica) | THD, SINAD, ENOB, SFDR | 60 min | 2 |
| [T6](#t6-vários-canais-diafonia-e-atraso) | Diafonia e atraso entre canais | 45 min | 2 |
| [T7](#t7-integridade-em-taxas-altas) | Nenhuma amostra perdida em taxa alta e sob carga | 60 min | 2 |
| [T8](#t8-aliasing) | Rejeição de aliasing | 30 min | 2 |
| [T9](#t9-sinais-de-espectro-conhecido) | Pipeline de supraharmônicos contra espectros conhecidos | 2 h | 3 |
| [T10](#t10-perfil-da-sonda-de-corrente) | **Perfil da sonda de corrente** + validação | 3-4 h | 4 |
| [T11](#t11-ponta-a-ponta) | O sistema inteiro: sinal composto e carga real | 1-2 h | 5 |

**Se só houver um dia:** T0, T1, T3, T4, T7a e T10 (nessa ordem). É o mínimo para afirmar que o sistema captura sem perder dados e para ter o perfil da sonda.

---

## Os testes

### T0: preparação e sanidade

**Objetivo.** Ter certeza de que firmware, relógio e cabeçalho estão certos antes de gastar tempo em medidas.

1. No computador, com a BeagleBone por USB: `scripts/set_date.sh`. Na BeagleBone: `date` deve mostrar a data de hoje.
2. Na BeagleBone: `cd firmware && ./setup.sh && dmesg | tail -n 20` (a PRU sobe sem reclamar).
3. Ligue o gerador, o osciloscópio, o frontend e a BeagleBone **30 minutos antes** do T1.
4. Entrada do canal em curto (ou terminada em 50 Ω). Capture:

```bash
sudo ./ler_adc 400000 1 --blocos 1 -o T0_sanidade.bin -t "T0 sanidade 400k"
ls -l T0_sanidade.bin        # 2098176 bytes = 1024 de cabeçalho + 1048576 amostras de 2 bytes
```

5. No computador: `uv run scripts/medir_captura.py lab/2026-10-20/T0_sanidade.bin --sem-tom`.

**Passou se:** o resumo do cabeçalho aparece sem "CRC-32 NÃO confere"; o tamanho do arquivo é o esperado; a saída do `medir_captura` não tem avisos; o DC (`media`) é de poucos mV.

### T1: piso de ruído (entrada em curto)

**Objetivo.** Ruído, offset e como eles variam com a taxa e o número de canais.

**Montagem.** Todos os canais usados com a entrada em curto (conector BNC com curto ou terminador de 50 Ω). Se der para acessar o pino do ADC, faça uma rodada ali e outra pela entrada do frontend: a diferença é o ruído do condicionamento.

**Sinal.** Nenhum.

```bash
sudo ./ler_adc 102400 1   --blocos 1 -o T1_curto_102k_1ch.bin -t "T1 curto 102.4k 1ch"
sudo ./ler_adc 400000 1   --blocos 4 -o T1_curto_400k_1ch.bin -t "T1 curto 400k 1ch"
sudo ./ler_adc 500000 1   --blocos 5 -o T1_curto_500k_1ch.bin -t "T1 curto 500k 1ch"
sudo ./ler_adc 400000 0,1 --blocos 4 -o T1_curto_400k_2ch.bin -t "T1 curto 400k 2ch"
sudo ./ler_adc 500000 0,1,2,3,4,5,6,7 --blocos 5 -o T1_curto_500k_8ch.bin -t "T1 curto 500k 8ch"
```

```fish
uv run scripts/medir_captura.py lab/2026-10-20/T1_*.bin --sem-tom --sem-correcao-sonda --csv lab/2026-10-20/resultados.csv
uv run scripts/adc_tool.py lab/2026-10-20/T1_curto_400k_1ch.bin --welch --modo-espectro ruido --sem-correcao-sonda -o lab/2026-10-20/fig_T1_psd.png
```

**Anote.** Nada no osciloscópio (opcional: tensão de ruído na entrada, só para ver se há zumbido evidente).

**Esperado.** O SNR de 89 a 91 dB do datasheet (tom em −0,5 dBFS) corresponde a um ruído de **~96 a 121 µV RMS**, ou **0,6 a 0,8 LSB**. O offset deve ficar dentro de ±1 mV (típico ±0,5 mV) se você estiver medindo no pino do ADC. Ruído de 2 LSB ou mais indica problema de placa (cabo longo, terra, USB, alimentação): investigue antes de seguir. O espectro de ruído (PSD) deve ser plano, com poucos picos; **qualquer pico fixo** (50/60 Hz e harmônicos, relógio, 100 kHz) vai aparecer nos dados reais e precisa ser identificado.

**Para o relatório.** Tabela: taxa × nº de canais × (ruído em LSB, µV RMS, nV/√Hz, offset em mV). Figura: a PSD do curto.

### T2: tensão contínua (ganho, offset e linearidade)

**Objetivo.** Ganho real da cadeia (vira o `--ganho` calibrado), offset e erro de linearidade, com DC.

**Montagem.** Fonte DC → entrada do canal **e** multímetro no mesmo nó.

**Sinal.** 7 níveis de DC: −4,5 V, −3 V, −1,5 V, 0 V, +1,5 V, +3 V, +4,5 V no pino do ADC (se o canal passa por frontend com divisor, use os níveis equivalentes na entrada dele; anote a leitura do multímetro em cada ponto).

```bash
sudo ./ler_adc 100000 1 --blocos 1 -o T2_dc_m4v5.bin -t "T2 DC -4.5V"    # e assim para os 7 níveis
```

```fish
uv run scripts/medir_captura.py lab/2026-10-20/T2_dc_*.bin --sem-tom --sem-correcao-sonda --csv lab/2026-10-20/resultados.csv
```

**Anote.** A tensão lida no multímetro em cada ponto (com todos os dígitos).

**Análise (planilha).** Coluna `media` do CSV contra a leitura do multímetro: ajuste linear. A inclinação é o ganho real (compare com o `--ganho` nominal; se diferir, use o medido); o intercepto é o offset; o resíduo do ajuste, em LSB, é o erro de linearidade.

**Esperado (datasheet, faixa ±1,25·VREF).** Erro de ganho típico ±0,02% da faixa (máx. ±0,05%), offset típico ±0,5 mV (máx. ±1 mV), INL típica ±0,75 LSB (máx. ±2 LSB). O multímetro e os resistores do divisor limitam o que você consegue provar: registre as incertezas.

**Para o relatório.** Gráfico `media` × referência com a reta e o resíduo em LSB; ganho e offset medidos.

### T3: resposta em frequência da cadeia

**Objetivo.** Medir a **atenuação de amplitude** da cadeia de tensão (frontend e filtro de 15 kHz do ADC) de 50 Hz até perto de Nyquist. É o resultado mais importante para a banda de supraharmônicos, e dele sai um perfil (`.json`) para corrigir os canais de tensão.

**Montagem.** Gerador → nó de entrada do canal. Ponta do osciloscópio (ou multímetro) no **mesmo nó**.

**Sinal.** Senoide pura, de 50 Hz a 200 kHz em 25 pontos logarítmicos, com **~4 V de pico no pino do ADC (8 Vpp, 78% da escala) em todas as frequências**, sem passar de ±5 V. Mantenha o nível alto: acima de 100 kHz o que o conversor registra é só 1 a 3% do que está no pino (tabela do início), e com 4 V de pico o código de 150 kHz ainda tem ~2 a 5% da escala, o bastante para uma boa relação sinal/ruído. Em cada frequência você lê o RMS real **no pino** (osciloscópio/multímetro), então a amplitude pode mudar de ponto a ponto (o gerador cai em alta frequência): não precisa ser constante.

**Execução com o assistente de calibração**, que escolhe as frequências, confere cada captura e guarda o RMS que você digita:

```bash
cd firmware
sudo ./calibrar_sonda.sh --taxa 500000 --canal-sonda 0 --pontos 25 --freq-max 200k --sonda cadeia_tensao --ref-externa
```

* A pergunta "**tensão RMS no shunt**" significa, aqui, a **tensão RMS do nó de entrada** que você lê no osciloscópio/multímetro (ex.: `1.7654`). Ignore o texto de "corrente" e "shunt".
* Leia o RMS **antes** de apertar ENTER para medir (com o sinal estável) e digite quando o script perguntar.
* Em altas frequências o script avisa "sinal fraco no canal da sonda" (abaixo de 10% da escala) e, se ficar abaixo de 0,2% da escala pico a pico, recusa o ponto como "sem sinal". O aviso é esperado por causa do filtro: aceite com `C`. Se for recusado, aumente a amplitude do gerador.

**Variante com amplitude conhecida (nada a digitar a cada ponto).** Se o gerador mantém o nível (confira no osciloscópio em 3 ou 4 frequências), informe a amplitude que ajustou: o script a grava nos metadados de cada captura (`ref: f=.. amp=..`). Ajuste o gerador para carga **High-Z** (o painel em 50 Ω mostra metade da tensão real):

```bash
sudo ./calibrar_sonda.sh --taxa 500000 --canal-sonda 0 --pontos 25 --freq-max 200k --sonda cadeia_tensao --amplitude 8Vpp
```

```fish
uv run scripts/gerar_perfil_sonda.py capturas/cadeia_tensao --ganho 1 --plot
```

Sem `--referencia-externa`, `--resistencia-shunt` nem `--amplitude-referencia`: a amplitude de cada captura vem dos metadados. A amplitude em V é a tensão no ponto onde o `--ganho` é aplicado, então com `--ganho 1` a grandeza física é a própria tensão. Se o gerador cair em alta frequência, use `--amplitude-por-ponto` e digite a amplitude lida no osciloscópio, ou salve um `.m` por ponto e use `--referencia-osciloscopio`.

No computador, com a leitura do osciloscópio digitada (o truque: com `--resistencia-shunt 1`, a "corrente" calculada é numericamente a tensão em volts):

```fish
uv run scripts/gerar_perfil_sonda.py capturas/cadeia_tensao --referencia-externa --resistencia-shunt 1 --ganho 1 --plot
```

(`--ganho 1` se o nó lido é o pino do ADC; se você injeta e lê na entrada do frontend, use o ganho nominal do frontend: o perfil sai **relativo a ele**.) O resultado é `scripts/sondas/cadeia_tensao.json` e um PNG com a curva.

**Verificação pontual, sem o assistente.** Para conferir a amplitude em uma frequência, sem gerar perfil:

```bash
sudo ./ler_adc 500000 1 --blocos 2 -o T3_f50000.bin -t "T3 50 kHz"
```

```fish
uv run scripts/medir_captura.py lab/2026-10-20/T3_f50000.bin --freq 50000 --referencia-rms 1.7654 --sem-correcao-sonda --csv lab/2026-10-20/resultados.csv
```

Imprime o erro de amplitude em % (ADC contra instrumento): a diferença da cadeia nessa frequência.

**Ensaio prévio do fluxo.** O caminho "assistente → `gerar_perfil_sonda.py` → correção no `medir_captura.py`" foi ensaiado com dados sintéticos de uma cadeia de dois polos com −3 dB em 15 kHz (24 pontos, 50 Hz a 160 kHz, 400 kS/s, 1 canal): o perfil recuperou o ganho com erro de 0,001%, e uma onda quadrada de 10 kHz, que sem correção mostrava a 15ª harmônica 31 dB abaixo da teoria, voltou à teoria em ±0,05 dB até 150 kHz (a fundamental, em 0,03%). Harmônicos pares a −100 dBc que apareçam na lista são só ruído amplificado pela correção. Avisos "fora da faixa válida" aparecem se a análise tiver componentes além do último ponto do perfil (o ganho é mantido constante ali, sem extrapolar).

**Esperado.** Ganho plano (±0,1 dB) até ~2,5 kHz e **−3 dB perto de 15 kHz**, seguido de queda de 12 dB por oitava: algo entre −26 e −33 dB em 100 kHz (tabela do início). O `gerar_perfil_sonda.py` já imprime o resumo da resposta (ganho de baixa frequência, frequência de −3 dB, inclinação final em dB/oitava e quanto a correção amplifica o ruído na maior frequência) e o grava no perfil (`calibracao_adc.resposta_conjunto`). Se o frontend (ou o LV 25-P) tiver pólos mais baixos, a curva cai antes. Se a curva mostrar ressonâncias ou picos, são do frontend: aumente a densidade de pontos ali (`--modo refinar`).

**Para o relatório.** A curva de ganho (dB) × frequência (eixo logarítmico), com a frequência de −3 dB marcada e a curva teórica do datasheet por cima; tabela de ganho em 1, 10, 15, 30, 50, 100 e 150 kHz.

### T4: frequência de amostragem real

**Objetivo.** Medir quanto a taxa gerada pela PRU difere da pedida, e se a diferença é só a divisão inteira dos ticks.

**Montagem.** Gerador → canal; osciloscópio no mesmo nó **com o contador de frequência** (ou use a entrada de 10 MHz de referência do gerador).

**Sinal.** Senoide de **10,000 kHz**, ~50% da escala. Anote a frequência real no contador, com todos os dígitos (ex.: `10000.02`).

Capture com cada taxa (1 canal, ~1 bloco; a 100 kS/s são ~10 s):

```bash
for taxa in 100000 102400 200000 250000 300000 400000 500000; do
  sudo ./ler_adc $taxa 1 --blocos 1 -o T4_fs_$taxa.bin -t "T4 fs $taxa"
done
```

```fish
for taxa in 100000 102400 200000 250000 300000 400000 500000
    uv run scripts/medir_captura.py lab/2026-10-20/T4_fs_$taxa.bin --freq 10000 --referencia-freq 10000.02 --sem-correcao-sonda --csv lab/2026-10-20/resultados.csv
end
```

**Como ler.** Sem `--fs-pru`, a análise supõe a taxa pedida. Se a taxa real da PRU for `fs_real = fs_pedida × (1 + δ)`, o tom aparece na frequência errada e o `erro_freq_ppm` do CSV é `−δ × 10⁶` (frequência medida menos a do contador, em ppm; usa-se o valor do contador como verdade, então o erro do gerador não entra). A primeira linha da saída de cada captura informa o que o firmware **deveria** gerar pelos ticks: `o PRU gera 102406.55 Hz = +64.0 ppm`; a coluna `fs_pru_hz` do CSV guarda esse valor. Compare:

* Taxas que dividem 200 MHz (100, 200, 250, 400, 500 kS/s) devem dar **todas o mesmo `erro_freq_ppm`**: é o erro do cristal da PRU (δ_cristal), comum a todas.
* 102,4 kS/s deve dar `−(δ_cristal + 64 ppm)` e 300 kS/s, `−(δ_cristal + 1001 ppm)`: a diferença para as taxas exatas é o arredondamento dos ticks.
* Se as taxas exatas **não** derem o mesmo valor, o laço da PRU tem um número de ciclos fixo a mais por amostra (a hipótese "taxa = clock ÷ ticks" está errada): isso também vai para o relatório.
* Repita com `--fs-pru` em 102,4 kS/s: o `erro_freq_ppm` deve cair para o mesmo valor das taxas exatas (a análise passa a usar a taxa que o PRU gera).

**Esperado.** Cristal da BeagleBone na faixa de dezenas de ppm. Em frequências medidas, isso é um erro relativo de 0,00x%, desprezível para amplitude, mas relevante se você quiser separar tons muito próximos ou comparar a frequência com uma referência.

**Para o relatório.** Tabela: taxa pedida × ticks × taxa gerada prevista × erro medido (ppm). Recomendação do uso de taxas exatas.

### T5: distorção e faixa dinâmica

**Objetivo.** THD, SINAD, ENOB e SFDR do ADC com tom puro, contra o nível e contra a frequência.

**Atenção à fonte.** O THD do gerador de funções (−50 a −70 dBc) **esconde** o THD de −102 dB do ADC. Duas saídas: passar o gerador por um filtro passa-faixa (LC ou ativo) na frequência do tom, ou usar uma fonte de baixa distorção (uma boa placa de som, com THD melhor que −90 dB). Se o THD medido for igual ao do datasheet do gerador, o resultado é limite do **gerador**, não do ADC, e o relatório deve dizer isso.

**Montagem.** Pino do ADC, se possível (use `--sem-correcao-sonda` e `--ganho 1`), para medir o ADC sozinho. Se só houver acesso pelo frontend, use o `--ganho` do frontend: o resultado é o da cadeia.

**T5a: varredura de amplitude, 1 kHz.** Níveis −0,5, −6, −20, −40 e −60 dBFS (amplitudes na tabela de [Convenções](#nomes-e-pastas)):

```bash
sudo ./ler_adc 400000 1 --blocos 4 -o T5a_1k_m6dBFS.bin -t "T5a 1kHz -6dBFS"    # e os outros níveis
```

**T5b: varredura de frequência, −1 dBFS.** 1, 5, 10, 20, 50 e 100 kHz (4,5 V de pico no pino; confirme que não satura).

```fish
uv run scripts/medir_captura.py lab/2026-10-20/T5*.bin --sem-correcao-sonda --faixa 10.24 --ganho 1 --harmonicos 9 --csv lab/2026-10-20/resultados.csv
```

**Anote.** Amplitude real no osciloscópio/multímetro em cada ponto; modelo e THD do gerador; se usou filtro.

**Esperado (datasheet, tom em −0,5 dBFS, 1 kHz, ±1,25·VREF).** SNR 91 dB (mín. 89), SINAD 91 dB (mín. 88,5), **ENOB ≈ 14,8 bits** (mín. 14,4), THD −102 dB, SFDR 103 dB. Com a amplitude caindo, o SINAD cai 1 dB por dB até o piso de ruído. Em frequências mais altas o THD medido parece **melhor** do que é: os harmônicos (2f, 3f...) são atenuados mais ainda pelo filtro de 15 kHz.

**Para o relatório.** Figura: SINAD (e ENOB) × nível em dBFS; a faixa dinâmica é o nível em que o SINAD chega a 0 dB. Figura: THD, SINAD e SFDR × frequência. Tabela: valores medidos contra datasheet.

### T6: vários canais (diafonia e atraso)

**Objetivo.** Quanto um canal vaza no outro, e se o intervalo de multiplexação entre canais é o esperado (importante para qualquer cálculo que combine tensão e corrente).

**T6a: diafonia.** Capture 2 canais (0 e 1) a 400 kS/s. **Canal 0** recebe um tom de 10 kHz a −1 dBFS; **canal 1** com a entrada em curto (ou terminada com a mesma resistência da fonte). Repita com 50 kHz. Repita com o tom no canal 1 e o canal 0 em curto (o canal que é amostrado logo depois do agressor sofre a "diafonia de memória"). Se quiser o pior caso, capture 8 canais a 500 kS/s com o tom no canal 0 e os demais em curto.

```bash
sudo ./ler_adc 400000 0,1 --blocos 4 -o T6a_10k_ch0.bin -t "T6a 10kHz ch0 agressor"
sudo ./ler_adc 500000 0,1,2,3,4,5,6,7 --blocos 5 -o T6a_10k_8ch.bin -t "T6a 10kHz 8ch"
```

**T6b: atraso entre canais.** O **mesmo** sinal (conector T de BNC, cabos de mesmo comprimento) nos canais 0 e 1, a 400 kS/s, em 10, 50 e 100 kHz.

```bash
sudo ./ler_adc 400000 0,1 --blocos 4 -o T6b_10k.bin -t "T6b mesmo sinal 10kHz"
```

```fish
uv run scripts/medir_captura.py lab/2026-10-20/T6*.bin --sem-correcao-sonda --csv lab/2026-10-20/resultados.csv
```

**Como ler.** A saída traz "Acoplamento entre canais no tom de ...": em T6a, `diafonia_db` do canal em curto; em T6b, `atraso_medido_us` contra `atraso_esperado_us`.

**Esperado.** Datasheet: isolamento entre canais de **110 dB** e diafonia de memória de **90 dB** (com agressor em sobrecarga de 2× o fundo de escala; com −1 dBFS, deve ser igual ou melhor). O que a ferramenta mede é limitado pelo ruído (~−110 a −120 dB): se o resultado estiver no piso, escreva "melhor que X dB". O atraso entre canais consecutivos deve ser **1/taxa total** (2,5 µs a 400 kS/s): é o que a PRU configura, e vale compensar no cálculo de potência (a 50 Hz isso é 0,045°, desprezível; a 100 kHz, 90°).

**Para o relatório.** Tabela de diafonia (frequência × par de canais); tabela de atraso medido contra esperado.

### T7: integridade em taxas altas

**Objetivo.** Provar que **nenhuma amostra é perdida ou duplicada** nas maiores taxas e sob carga na BeagleBone, e que os dados chegam ao disco inteiros (requisito de desempenho do projeto).

**Sinal.** Senoide de 10 kHz a −6 dBFS, estável (a continuidade se verifica pela fase do tom: um tom estável é essencial).

**T7a: taxas.** 10 s em cada taxa, 1 canal (blocos: 102,4 kS/s = 1; 200 kS/s = 2; 400 kS/s = 4; 500 kS/s = 5).

```bash
sudo ./ler_adc 102400 1 --blocos 1 -o T7a_102k.bin -t "T7a 102.4k"
sudo ./ler_adc 200000 1 --blocos 2 -o T7a_200k.bin -t "T7a 200k"
sudo ./ler_adc 400000 1 --blocos 4 -o T7a_400k.bin -t "T7a 400k"
sudo ./ler_adc 500000 1 --blocos 5 -o T7a_500k.bin -t "T7a 500k"
```

**T7b: máximo agregado.** 8 canais a 500 kS/s (62,5 kS/s por canal), 10 s, tom de 5 kHz no canal 0 (os outros, em curto).

**T7c: longa duração e deriva.** 10 minutos a 400 kS/s com o tom (≈ 480 MB; confira o espaço livre).

```bash
sudo ./ler_adc 400000 1 --duracao 10m -o T7c_10min.bin -t "T7c 10 min 400k"
```

```fish
for ini in (seq 0 24000000 216000000)
    uv run scripts/medir_captura.py lab/2026-10-20/T7c_10min.bin --freq 10000 --inicio $ini --max-amostras 4000000 --rotulo "T7c ini $ini" --sem-correcao-sonda --csv lab/2026-10-20/resultados.csv
end
```

**T7d: sob carga.** Repita o T7a a 500 kS/s **enquanto** outra janela copia um arquivo grande por `scp` e outra roda `top`. Mostra se o sistema de arquivos ou a CPU atrapalham a captura.

```fish
uv run scripts/medir_captura.py lab/2026-10-20/T7*.bin --freq 10000 --sem-correcao-sonda --csv lab/2026-10-20/resultados.csv
```

**Esperado.** Em cada captura: `continuidade : OK`, **0 eventos**, maior salto de fase **menor que 0,5 amostra** (um problema real dá ~1,0, ou múltiplos); tamanho do arquivo igual ao do cabeçalho (a ferramenta avisa se não for); amplitude do tom varia menos de ~0,1% entre segmentos. No T7c, o tom pode derivar um pouco pelo gerador: compare com a leitura do osciloscópio no início e no fim.

**Passou se:** zero eventos em todas as taxas, inclusive T7b e T7d. Um evento = anote em qual taxa, que amostra (`perto da amostra N`) e olhe a saída do terminal do `ler_adc` e o `dmesg` daquele instante.

**Para o relatório.** Tabela taxa × canais × duração × nº de eventos × maior salto. É a evidência do requisito de "não corromper os dados medidos".

### T8: aliasing

**Objetivo.** Quanto de um sinal **acima** de Nyquist dobra para dentro da banda, dado o anti-aliasing embutido (e fraco) do ADC.

**Sinal.** Senoides de 50% da escala em frequências **acima** de Nyquist a **400 kS/s** (Nyquist 200 kHz): 210, 250, 300 e 350 kHz. Cada uma aparece em `|f − 400 kHz|`: 190, 150, 100 e 50 kHz. Leia no osciloscópio a amplitude real RMS de cada tom (o gerador cai de amplitude em alta frequência).

```bash
sudo ./ler_adc 400000 1 --blocos 2 -o T8_f300k.bin -t "T8 300kHz alias 100k"
```

```fish
uv run scripts/medir_captura.py lab/2026-10-20/T8_f300k.bin --freq 100000 --referencia-rms 1.7654 --sem-correcao-sonda --csv lab/2026-10-20/resultados.csv
```

(`--freq` é a frequência **onde o tom aparece** depois do dobramento; `--referencia-rms` é a leitura do osciloscópio do tom real de 300 kHz.)

**Esperado.** `erro_amplitude_pct` por volta de −99% (-37 a -45 dB, a atenuação do filtro nessas frequências): **~1% do sinal de entrada aparece como um falso tom na banda**. Um conversor chaveado em 300 kHz com 1 V de ondulação deixaria ~10 mV de "supraharmônico" em 100 kHz.

**Para o relatório.** Tabela: frequência real × frequência aparente × rejeição (dB). A conclusão de projeto: se houver emissão acima de Nyquist, um filtro anti-aliasing externo (ou taxa maior) é necessário.

### T9: sinais de espectro conhecido

**Objetivo.** Conferir o **pipeline** de supraharmônicos (FFT, Welch, picos, correção) contra espectros que se sabe calcular de antemão. Capture todos a 400 kS/s, 1 canal, e compare com a teoria e com o osciloscópio.

**T9a: onda quadrada.** 10 kHz, 50% de ciclo, 2 V de pico (4 Vpp), sem offset. Os harmônicos ímpares têm amplitude de pico `4A/(nπ)`: −9,54 dBc (3ª), −13,98 (5ª), −16,90 (7ª), −19,08 (9ª), −20,83 (11ª), −22,28 (13ª), −23,52 dBc (15ª, 150 kHz). Um ciclo de trabalho fora de 50% (o gerador tem ~1% de erro) cria harmônicos pares: use isso como teste.

```bash
sudo ./ler_adc 400000 1 --blocos 4 -o T9a_quadrada_10k.bin -t "T9a quadrada 10k" --grandeza 0:tensao --sonda 0:cadeia_tensao
```

```fish
# sem correção da cadeia (o que o ADC "vê") e com a correção do perfil do T3
uv run scripts/medir_captura.py lab/2026-10-20/T9a_quadrada_10k.bin --freq 10000 --harmonicos 15 --sem-correcao-sonda --rotulo "T9a sem correcao" --csv lab/2026-10-20/resultados.csv
uv run scripts/medir_captura.py lab/2026-10-20/T9a_quadrada_10k.bin --freq 10000 --harmonicos 15 --rotulo "T9a com perfil" --csv lab/2026-10-20/resultados.csv
uv run scripts/adc_tool.py lab/2026-10-20/T9a_quadrada_10k.bin --welch --picos -70 --filtro-passa-alta 2000 -o lab/2026-10-20/fig_T9a.png
```

**Esperado.** Sem correção, os harmônicos altos saem **bem abaixo** da teoria (o filtro). Com o perfil do T3, os níveis relativos devem bater com a teoria em ~1 dB até 150 kHz. É a demonstração mais convincente de que o perfil funciona. Compare com a FFT do osciloscópio (mesma janela de tempo).

**T9b: dois tons e resolução.** 20,0 kHz e 20,3 kHz, mesma amplitude (−12 dBFS cada), somadas com dois resistores de 1 kΩ. O Welch com `--resolucao-welch 200` não separa; com `--resolucao-welch 50` separa. Mede o limite de resolução do método. Produtos de intermodulação (19,7 e 20,6 kHz) mostram a linearidade.

**T9c: fundamental forte e supraharmônicos fracos.** O caso real: 50 Hz a ~80% da escala (4 V de pico) somado a 9 kHz em −60 dBc (4 mV de pico), 35 kHz em −50 dBc (13 mV) e 100 kHz em −40 dBc (40 mV). Gerador arbitrário de 2 canais ou dois geradores com somador resistivo. **Meça cada fonte sozinha** no osciloscópio/multímetro (em amplitude maior) para saber os níveis reais; depois some.

```fish
uv run scripts/adc_tool.py lab/2026-10-20/T9c.bin --welch --janela hann --filtro-passa-alta 2000 --picos -100 -o lab/2026-10-20/fig_T9c_welch.png
uv run scripts/adc_tool.py lab/2026-10-20/T9c.bin --fft --janela hann -o lab/2026-10-20/fig_T9c_fft.png
```

**Esperado.** Os três tons são vistos acima do piso; sem a correção da cadeia, o de 100 kHz sai ~26 a 33 dB abaixo do injetado. Anote o **menor tom detectável** (10 dB acima do piso) em cada frequência: é o limite de detecção do sistema.

**T9d: modulação em frequência (dithering).** Portadora quadrada de 20 kHz com FM de ±1 kHz a 100 Hz: espalha a energia em torno de 20 kHz. Compare `--fft --freq-min 19000 --freq-max 21000` (borra) com `--welch` (média) e `--agrupar-bandas 200`. A FM não muda a potência da portadora: o RMS lido **no pino** (osciloscópio) deve ser o mesmo com e sem modulação. No ADC, o filtro de 15 kHz pesa de forma diferente os componentes espalhados (e os harmônicos da quadrada), então compare o `rms_ca` das duas capturas (com e sem modulação) **com a correção do perfil** e aceite ±2%.

**T9e (opcional): distúrbio momentâneo.** Salva de 10 kHz com 5 ms ligados a cada 100 ms: use `adc_tool.py captura.bin --inicio N --fim M --fft --freq-min 9000 --freq-max 11000` para isolar uma salva e `--fft 10 --freq-min 9000 --freq-max 11000` (os 10 primeiros ciclos). O `--fft` procura a fundamental entre 45 e 65 Hz por padrão: sem `--freq-min/--freq-max` ele não acha um tom de 10 kHz.

**Para o relatório.** Figuras sobrepostas "teoria × ADC (sem correção) × ADC (com perfil) × osciloscópio" para a quadrada; o menor tom detectável do T9c; os espectros do T9d.

### T10: perfil da sonda de corrente

**Objetivo.** Medir a resposta em frequência da **sonda mais a cadeia de aquisição** do canal de produção, gerar `scripts/sondas/<id>.json` e **validar** o perfil em frequências que não entraram nele. É o objetivo central do projeto.

**Regras de ouro.**

1. **Mesmo canal, mesma faixa e mesmo `--ganho`** que você usará em produção. O perfil só vale para essa cadeia (o `adc_tool.py` e o `medir_captura.py` avisam se divergirem).
2. **Um canal só**, taxa de **400 kS/s** (Nyquist 200 kHz, taxa exata; ver T4). Com `--freq-max 160k` você cobre toda a banda de supraharmônicos (até 150 kHz) sem tom próximo demais de Nyquist.
3. A corrente real vem do **osciloscópio** (`--ref-externa`, lida sobre o shunt, ou o `.m` de cada ponto) ou da **amplitude conhecida** da senoide (`--amplitude`, veja o passo 1b). Com isso a amplitude **pode mudar a cada frequência** (use `--amplitude-por-ponto` no segundo caso): ajuste o gerador (ou o amplificador, ou o número de voltas) para a saída da sonda ficar em **~4 V de pico no pino do ADC** em todas as frequências, sem saturar. Isso é essencial, porque o filtro de 15 kHz do ADC reduz o sinal em alta frequência a poucos % do nível do pino, e porque a resposta da própria sonda também cai.

**Montagem.**

```text
Gerador (+ amplificador) ──► fio que atravessa a garra da sonda ──► shunt R ──► retorno (terra do gerador)
                                                                 ▲
                            ponta ×10 do osciloscópio aqui ──────┘   (terra da ponta no retorno)

Sonda de corrente ──► (condicionamento) ──► canal 1 do ADC (BeagleBone)
```

* O **shunt** deve ser de baixa indutância (filme fino, coaxial ou vários resistores em paralelo) e ficar do lado do **retorno**: a tensão nele é medida com a ponta no lado do gerador e a terra da ponta no retorno (sem ponta diferencial). Se der, meça a impedância do shunt no maior frequência com um medidor LCR.
* A corrente máxima é a do gerador: `I_pico ≈ V_pico(aberto) / (50 Ω + R)`. Para mais corrente, use um amplificador de potência, ou passe o fio **N voltas** pela garra da sonda (a sonda enxerga `N × I`: informe `--resistencia-shunt R/N`). Confira que o resultado não muda com N; se mudar, a indutância entre as voltas está atrapalhando em alta frequência.
* Condutor centralizado na garra e sempre na mesma orientação. Zere/desmagnetize a sonda Hall conforme o manual, e espere o aquecimento dela.
* Mantenha o laço de corrente pequeno: cada microhenry de laço a 150 kHz vale ~0,9 Ω, e isso (somado ao 50 Ω do gerador) só limita a corrente, mas **não** afeta o resultado, porque a corrente real é medida sobre o shunt.

**Passo 1: coletar (na BeagleBone).** 24 pontos, 2 repetições:

```bash
cd firmware
sudo ./calibrar_sonda.sh --taxa 400000 --canal-sonda 1 --pontos 24 --freq-max 160k \
    --repeticoes 2 --sonda minha_sonda_sn001 --ref-externa
```

Em cada ponto: ajuste a frequência e a amplitude no gerador, espere estabilizar, **leia o RMS da tensão no shunt** no osciloscópio (de preferência o RMS de ciclos inteiros, com média), aperte ENTER para medir e digite o valor quando o script perguntar (ex.: `0.1234` ou `123.4m`). O script confere cada captura e oferece `[C]ontinuar`, `[R]efazer`, `[P]ular`, `[A]bortar`. Depois da primeira rodada, use `--modo refinar --pontos 4` para acrescentar pontos onde o ganho mais varia (ressonâncias) e `--modo adensar` se a curva for acidentada. Mais detalhes em [`guia_de_uso.md`](guia_de_uso.md#sondas-de-corrente-calibração-e-correção).

**Passo 1b: variante com amplitude conhecida.** Quando o sinal injetado é uma **senoide pura** de amplitude e frequência ajustáveis e você sabe a amplitude (ex.: 500 mVpp), o script a grava nos metadados e dispensa a leitura a cada ponto:

```bash
sudo ./calibrar_sonda.sh --taxa 400000 --canal-sonda 1 --pontos 24 --freq-max 160k \
    --repeticoes 2 --sonda minha_sonda_sn001 --amplitude 500mVpp
```

Escreva a amplitude com **unidade e tipo** (`500mVpp`, `250mVpk`, `176.8mVrms`, `2Arms`). Duas ressalvas de bancada que mudam o resultado: (1) o painel do gerador vale para carga de 50 Ω; em alta impedância a tensão real é o dobro, então ajuste *High-Z* ou confira no osciloscópio; (2) se você injeta **tensão** no lugar da saída da sonda, o perfil mede o frontend e o ADC **sem a sonda de corrente**: para incluí-la, injete **corrente** pela garra (amplitude em A, por exemplo `--amplitude 100mApk`, conhecida pela tensão no shunt ÷ R). A amplitude em V é a tensão no ponto onde o `--ganho` é aplicado (500 mVpp com `--ganho 10` = 2,5 A de pico).

**Conferir o método (uma medição com amplitude conhecida e `.m`).** Antes da coleta completa, ou com uma captura que você já tenha, verifique se o método devolve a amplitude certa:

```fish
# SEM correção: ADC/injetado é o ganho do conjunto nessa frequência; ADC/osciloscópio mostra se o gerador entregou o que foi ajustado
uv run scripts/medir_captura.py captura.bin --sem-correcao-sonda --amplitude-referencia 500mVpp --osciloscopio captura.m --ganho 10 --rotulo "metodo 33kHz" --csv lab/2026-10-20/resultados.csv
```

Se `osciloscópio vs injetada` passar de ~1%, use o osciloscópio como referência do perfil. Com o perfil pronto, repita **com** a correção: ADC/injetado deve dar ~1 numa frequência que não entrou na calibração.

**Linearidade (faça no meio da coleta).** Em 1 kHz, capture 5 amplitudes de corrente (de ~10% a ~90% da escala) com `--modo refazer --freqs 1000` ou como capturas avulsas: o ganho **não** pode depender da amplitude. Se depender, a sonda satura ou o shunt aquece.

**Passo 2: gerar o perfil (no computador).** Copie `capturas/minha_sonda_sn001/` (e os `.m` do osciloscópio, se houver) e rode:

```fish
uv run scripts/gerar_perfil_sonda.py capturas/minha_sonda_sn001 --referencia-externa \
    --resistencia-shunt 1.0 --ganho 10 --formato uint16 --faixa 10.24 \
    --fabricante "Fluke" --modelo "i30s" --numero-serie "SN001" --plot
```

(`--resistencia-shunt` é o valor **efetivo**, `R/N` se usou N voltas; `--ganho` é o do **canal da sonda**, o mesmo da produção. Para a coleta do passo 1b o comando é o mesmo **sem** `--referencia-externa` e `--resistencia-shunt`: a amplitude vem dos metadados. Para um `.m` por captura, troque por `--referencia-osciloscopio`.) O script mede a frequência e a amplitude de cada captura, calcula `ganho = amplitude da sonda ÷ corrente de pico` (com `corrente de pico = √2 × V_RMS ÷ R`), agrega as repetições e grava o `.json`. Atenção aos avisos: repetições que divergem mais de 10% (remeça o ponto), SNR baixo, ganho na menor frequência fora de [0,7; 1,3] (o `--ganho` provavelmente não é 1/sensibilidade nominal).

**Passo 3: validar em frequências que ficaram de fora (hold-out).** Escolha 4 a 6 frequências **que não estão** no perfil e que ficam entre pontos: por exemplo 330 Hz, 3,3 kHz, 12 kHz, 33 kHz, 75 kHz e 133 kHz. Em cada uma, capture **registrando a sonda no cabeçalho** (para a correção ser automática) e leia o RMS no shunt:

```bash
sudo ./ler_adc 400000 1 --blocos 2 -o H_33kHz.bin -t "H 33kHz" --grandeza 1:corrente --sonda 1:minha_sonda_sn001
```

```fish
# I_rms (A) = V_rms(shunt) / R_efetivo. Exemplo: 85,2 mV sobre 1 ohm -> 0.0852 A
uv run scripts/medir_captura.py lab/2026-10-20/H_33kHz.bin --ganho 10 --freq 33000 --referencia-rms 0.0852 --rotulo "H 33kHz" --csv lab/2026-10-20/resultados.csv
```

O `erro_amplitude_pct` do CSV é o erro do **sistema corrigido** contra o osciloscópio, nas frequências de validação. Repita com `--sem-correcao-sonda` para mostrar o quanto a correção melhora.

**Esperado.** Sem correção, o erro em 100 kHz será de dezenas de % (filtro do ADC mais a banda da sonda). Com correção, deve cair para **poucos %**, limitado por: exatidão do osciloscópio (1 a 2%), do shunt, interpolação entre pontos (0,17% com 18 pontos, 0,06% com 25, para curvas suaves; ver [`auditoria_perfil_sonda.md`](auditoria_perfil_sonda.md)) e pela repetibilidade (o desvio entre repetições aparece no próprio perfil). A correção restaura a **amplitude**, não a fase: não use o canal corrigido para potência por componente.

**Comparar as referências (para o relatório).** Gere o perfil pela amplitude conhecida e pelo `.m` (`-o scripts/sondas/x_amp.json` e `-o scripts/sondas/x_osc.json`) e compare os ganhos ponto a ponto: a diferença em dB por frequência é a planura do gerador somada ao erro de amplitude do painel, ou seja, o quanto a "amplitude conhecida" é confiável sem osciloscópio.

**Para o relatório.** A curva do perfil (PNG do `--plot`) com os pontos e as barras de desvio; o resumo da resposta do conjunto (−3 dB, inclinação, amplificação de ruído); a tabela de validação (frequência, corrente de referência, corrente medida sem e com correção, erro %); o teste de linearidade; a comparação amplitude conhecida × osciloscópio; o orçamento de incerteza (osciloscópio, shunt, interpolação, repetibilidade, planura do gerador).

### T11: ponta a ponta

**Objetivo.** Medir um sinal **parecido com o real** com o sistema completo (sonda corrigida, tensão corrigida, pipeline de análise) e compará-lo com o osciloscópio.

**T11a: corrente composta (com gerador).** Tons simultâneos de corrente pela sonda: 50 Hz (o maior), 5 kHz, 20 kHz, 60 kHz e 120 kHz, com correntes diferentes (ex.: 100 mA, 20 mA, 10 mA, 5 mA, 3 mA de pico; use N voltas, ou amplificador, se precisar). Procedimento:

1. Meça **cada tom sozinho** sobre o shunt (RMS no osciloscópio/multímetro) e anote `I_rms` por tom (`V_rms ÷ R`).
2. Ligue **todos juntos** (gerador arbitrário ou somador) e capture com a sonda e a tensão registradas (`--grandeza 0:tensao,1:corrente --sonda 0:cadeia_tensao,1:minha_sonda_sn001`), 2 canais a 400 kS/s (Nyquist por canal de 100 kHz: troque o 120 kHz por 90 kHz), ou 1 canal (sonda) a 400 kS/s.
3. Em paralelo, no osciloscópio, grave a mesma forma de onda (para a figura "forma de onda × ADC").

```fish
uv run scripts/adc_tool.py lab/2026-10-20/T11a.bin --welch --janela hann --filtro-passa-alta 2000 --picos -90 -o lab/2026-10-20/fig_T11a.png
uv run scripts/medir_captura.py lab/2026-10-20/T11a.bin --canais-medir 1 --freq 20000 --referencia-rms 0.0071 --rotulo "T11a 20kHz" --csv lab/2026-10-20/resultados.csv
```

(`--freq` seleciona cada tom em ±10%; repita para cada um, com a respectiva `I_rms`.)

**Esperado.** Cada tom com erro de poucos % contra o valor medido sozinho, e **nenhum tom espúrio** acima do piso fora dos tons injetados (intermodulação e aliasing aparecem como picos extras).

**T11b: carga real (opcional, exige supervisão).** Uma carga chaveada (fonte de computador, carregador, driver de LED, dimmer) na rede, a corrente pela sonda e o osciloscópio **isolado** no mesmo ponto de medida (shunt de baixa tensão em série). Capture 10 s e compare a lista de picos do `--welch --picos` (com a correção) com a FFT do osciloscópio nos mesmos picos (frequência e amplitude): a frequência de chaveamento e seus primeiros harmônicos.

**Para o relatório.** Tabela dos tons de T11a (corrente injetada, medida, erro %); figura com os espectros ADC × osciloscópio de T11b.

---

## Dados e figuras para o relatório

| Item | Origem |
|---|---|
| Foto da bancada e diagrama de ligações de cada teste; lista de instrumentos com modelo, exatidão e data da última calibração | Todos |
| Ruído em LSB, µV e nV/√Hz × taxa e nº de canais; PSD do curto | T1 |
| Ganho e offset medidos; resíduo de linearidade em LSB | T2 |
| **Resposta em frequência da cadeia** (dB × Hz, −3 dB) | T3 |
| Erro da taxa de amostragem (ppm) × taxa pedida | T4 |
| SINAD/ENOB × nível; THD, SINAD e SFDR × frequência; faixa dinâmica | T5 |
| Diafonia e atraso entre canais | T6 |
| Tabela de continuidade (eventos, salto máximo) por taxa e carga; deriva em 10 min | T7 |
| Rejeição de aliasing × frequência | T8 |
| Quadrada: teoria × ADC × perfil × osciloscópio; menor tom detectável; resolução de dois tons | T9 |
| **Perfil da sonda** (curva, pontos, desvios); validação hold-out (erro % com e sem correção); linearidade | T10 |
| Tons compostos e carga real: ADC × osciloscópio | T11 |
| `resultados.csv` de cada dia, os `.bin` (compactar com `scripts/compactar_amostras.sh`) e os prints do osciloscópio | Todos |

**Sugestão de estrutura:** uma tabela "requisito do projeto → teste → resultado → critério" com os testes T7 (não perder dados), T10 (perfil da sonda), T3 (banda de supraharmônicos) e T11 (ponta a ponta).

**Declare no relatório** as limitações que você encontrou: o filtro de 15 kHz do ADC e sua correção (que amplifica o ruído), o aliasing de componentes acima de Nyquist, a taxa de amostragem real, a exatidão do osciloscópio e o fato de a correção de sonda restaurar só a amplitude (não a fase).

---

## Critérios de aceitação

Os limites abaixo são **propostas** (baseadas no datasheet e em boas práticas); ajuste e justifique no relatório.

| Teste | Critério | Referência |
|---|---|---|
| T0 | Cabeçalho íntegro, tamanho do arquivo correto, sem avisos | Projeto |
| T1 | Ruído ≤ ~1 LSB RMS (no pino do ADC); offset ≤ ±1 mV | Datasheet (SNR ≥ 89 dB; offset máx. ±1 mV) |
| T2 | Erro de ganho ≤ 0,1% da faixa (limitado pelo multímetro); INL ≤ 2 LSB | Datasheet (±0,05%; ±2 LSB) |
| T3 | −3 dB perto de 15 kHz; planicidade ±0,1 dB abaixo de 2,5 kHz (ADC) | Datasheet |
| T4 | Erro de taxa explicado pelos ticks e pelo cristal (diferença entre taxas exatas < 5 ppm) | Projeto |
| T5 | SINAD ≥ 88,5 dB a −0,5 dBFS, 1 kHz (ENOB ≥ 14,4 bits); SFDR ≥ 100 dB (se a fonte permitir) | Datasheet |
| T6 | Diafonia ≤ −90 dB; atraso entre canais = 1/taxa total ±2% | Datasheet; projeto |
| T7 | **0 eventos de continuidade** em todas as taxas e sob carga; amplitude estável em ±0,1% | Projeto (requisito de desempenho) |
| T8 | Rejeição documentada; sem exigência numérica (é uma característica do ADC) | Datasheet |
| T9 | Harmônicos da quadrada dentro de ±1 dB da teoria (com perfil); menor tom detectável documentado | Teoria |
| T10 | Erro de validação (hold-out) ≤ 3% em 50 Hz a 150 kHz (ou o melhor que a exatidão do osciloscópio e do shunt permitirem, com justificativa) | Projeto |
| T11 | Cada tom dentro de ~5% do valor de referência, sem tons espúrios | Projeto |

---

## Problemas de bancada

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Pico forte de 50/60 Hz e harmônicos no curto | Laço de terra (USB/rede, gerador e osciloscópio em tomadas diferentes) | Um só ponto de terra; notebook com bateria; cabos de sinal curtos e trançados; ferrite |
| Ruído muito acima de 1 LSB | Jumper longo entre a placa de aquisição e o frontend; fonte ruidosa; USB | Veja "Preparar a BeagleBone" no [guia](guia_de_uso.md); desligue o que não precisa |
| Amplitude no ADC o dobro (ou a metade) do esperado | Gerador em 50 Ω com carga High-Z (ou o contrário) | Ajuste a carga do gerador e **leia o osciloscópio**, não o painel |
| `saturou o ADC` | Amplitude alta (ou ganho do frontend alto) | Reduza; lembre que o frontend pode ter ganho |
| `sinal fraco` em frequência alta | Filtro de 15 kHz do ADC | Esperado; aumente a corrente ou a amplitude do gerador; aceite se ≥ 0,2% da escala |
| `frequência medida fora da planejada` | Gerador mal ajustado, ou taxa pedida ≠ gerada | Confira o contador do osciloscópio; veja T4 |
| Perfil com ganho de 1,0 em baixa frequência muito diferente (ex.: 0,1) | `--ganho` diferente de 1/sensibilidade da sonda | Use o ganho nominal certo (ex.: 100 mV/A → `--ganho 10`) |
| Perfil "dentes de serra" ou pontos fora da curva | Gerador instável; shunt aquecendo; ponta mal compensada; sonda sem zero | Refaça os pontos (`R`); repita com `--repeticoes`; compense a ponta |
| `ler_adc` trava | PRU parada | `dmesg`; `./setup.sh` |
| Disco cheio | Capturas longas | `df -h`; copie e apague; `calibrar_sonda.sh` pausa abaixo de 50 MB |

---

## Checklist ao sair do laboratório

- [ ] Todos os `.bin` copiados para o computador (e **também** em um segundo lugar) e o tamanho conferido.
- [ ] `resultados.csv` do dia salvo, com uma linha por canal medido.
- [ ] Pasta `capturas/<sonda>/` (inclui `referencia_externa.csv` e `plano_coleta.txt`) copiada, junto com o `.m` do osciloscópio de cada ponto (mesmo nome da captura) e a amplitude ajustada no gerador (`--amplitude`, já nos metadados).
- [ ] Perfil `scripts/sondas/<id>.json` gerado e validado (T10), e o PNG da curva.
- [ ] Fotos da bancada e prints do osciloscópio de cada teste (com a escala visível).
- [ ] Caderno: instrumentos e ajustes, temperatura, anomalias, o que **ficou por fazer**.
- [ ] Hipóteses confirmadas ou refutadas: filtro de 15 kHz (T3), taxa real e ticks (T4), diafonia (T6), perda de amostras (T7).
- [ ] Se algo mudou (outro `--ganho`, outro canal, nova taxa), anote: o perfil só vale para a cadeia em que foi medido.
