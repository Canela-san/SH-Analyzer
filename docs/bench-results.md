# Resultados de bancada

O registro dos resultados medidos do SH-Analyzer, um teste por seção, prontos para o relatório. Cada resultado diz
**quando** foi medido, **com que firmware**, **onde estão os dados** e **com que condições**, e traz os números que
podem ser citados. Os procedimentos (como medir) ficam no [roteiro de laboratório](lab-procedure.md); a narrativa
(por que, o que mudou) fica nas [notas do relatório](report-notes.md). Aqui ficam só os números e de onde eles vêm.

**Convenções.**

* `$DADOS` é a pasta das capturas (no computador do projeto, `~/Documents/sh-analyzer-data`); `$DADOS/lab/AAAA-MM-DD/`
  é um dia de bancada.
* O firmware é o `git describe` gravado no cabeçalho de cada captura (a linha `Firmware:` do `ler_adc`).
* LSB é o da faixa usada: 312,5 µV em ±10,24 V, 156,3 µV em ±5,12 V e 78,1 µV em ±2,56 V.
* Um resultado medido com um firmware que tinha um defeito conhecido diz qual, e se o defeito afeta o número.

**Figuras e números para o LaTeX.** As figuras dos testes saem de `report/gerar_figuras.py`, lidas direto das capturas
e dos perfis, com os números ao lado como macros siunitx. Inclua sem escalar:

```latex
\includegraphics{figures/grade_jitter.pdf}
\input{figures/grade_jitter.tex}   % \GradeJitterAntes, \GradeJitterDepois, \GradeRuidoLargoAntes, ...
```

```bash
uv run report/gerar_figuras.py --listar          # as figuras disponíveis
uv run report/gerar_figuras.py grade_jitter grade_degraus grade_teto --png
```

As figuras de bancada precisam das capturas em `$DADOS`. Sem elas, o script avisa e gera as outras.

## Índice

| Teste | O que mede | Data | Firmware | Figura | Estado |
|---|---|---|---|---|---|
| [T7f](#t7f-a-grade-de-tempo) | O período entre amostras: jitter, degraus, folga e teto com período constante; o quadro que dependia do dado | 22/10/2026 | `v0.7-1-gb2f9078` | `grade_jitter`, `grade_degraus`, `grade_teto`, `grade_bits` | ✅ (falta repetir com o quadro fixo) |
| [T7e](#t7e-esperas-do-cs-e-teto-de-taxa) | Esperas do CS e taxa máxima | 21/10/2026 | `v0.6-10`/`-11` | — | ✅ |
| [T7a–c](#t7a-a-t7c-integridade-e-estabilidade) | Integridade, estabilidade em 10 min e o salto antigo nas trocas de buffer | 19/10/2026 | anterior a out/2026 | — | ✅ (firmware antigo) |
| [T6](#t6-vários-canais) | Diafonia e atraso entre canais | 19/10 e 22/10/2026 | antigo e `v0.7-1` | — | 🟡 |
| [T4](#t4-taxa-de-amostragem-real) | Taxa gerada × pedida | 19/10/2026 | anterior a out/2026 | — | 🟡 (falta o contador) |
| [T3](#t3-resposta-em-frequência-da-cadeia-de-tensão) | Resposta em frequência da cadeia de tensão até 140 kHz | 19/10 e 22/10/2026 | antigo e `v0.7-1` | `perfil_cadeia_tensao`, `perfil_cadeia_tensao_comparacao` | ✅ |
| [T2](#t2-tensão-contínua) | Razão do divisor e linearidade em DC | 19/10/2026 | anterior a out/2026 | — | ✅ |
| [T1](#t1-piso-de-ruído) | Ruído e offset com a entrada em curto | 19/10 e 22/10/2026 | antigo e `v0.7-1` | — | ✅ |
| [T0](#t0-escala-do-adc) | Escala do ADC nas três faixas | 19/10/2026 | anterior a out/2026 | — | ✅ |

O que falta medir: a `--grade` com o firmware do quadro fixo (o T7f de novo), o T5 (distorção com fonte limpa), o T8
(*aliasing*), o T9 (espectros conhecidos), o T10 (a sonda de corrente) e o T11 (ponta a ponta). Veja a
[tabela de estado](lab-procedure.md#estado-da-campanha).

---

## T7f: a grade de tempo

**22/10/2026** · firmware `v0.7-1-gb2f9078` (protocolo 2: espera de precisão, folga publicada, rebase autocalibrado)
· `$DADOS/lab/2026-10-22/T7f_2026-10-22_0435/` (46 capturas, `firmware/varrer_taxa.sh --grade`, ~465 MB) · tom de
10 kHz (gerador Siglent SDG1032X, 20 Vpp, High-Z) no canal 1, faixa de ±2,56 V · comparação com
`$DADOS/lab/2026-10-21/T7e_2026-10-21_1731/B_cs3-1-3_312500_tom.bin` (firmware `v0.6-10`, espera por sondagem).

| Grandeza | Antes (21/10) | Depois (22/10) | Condições |
|---|---|---|---|
| Jitter de amostragem | **8,5 ns rms** | **0,00 ns** (piso do método ~0,3 ns) | 312,5 kS/s, 10 s; igual a 100 kS/s, com 2 canais e com o ARM ocupado |
| Ruído onde o tom é plano (o do ADC) | 0,78 LSB | 0,79 LSB | o mesmo da entrada em curto (T1: 0,75 LSB) |
| Ruído de banda larga com o tom (fora de ±50 Hz do tom e dos harmônicos) | **2,23 LSB** | **0,77 LSB** | FFT de 6,7 s |
| SNR / SINAD | 64,0 / 63,4 dB | **69,4 / 67,4 dB** | 10 s, como em 21/10; 6,7 s: 71,2 / 68,6 dB |
| THD (H2 a H9) | −71,9 dB | −71,9 dB | é a do gerador |
| Degrau de tempo nas trocas de buffer | +0,3 ns (2 trocas) | **−0,03 ± 0,03 ns** (89 trocas; o pior, +0,8 ns) | 5 min a 312,5 kS/s |
| Degrau de tempo nos rebases do contador | +4,8 e +6,6 µs (defeito de 21/10) | **−0,04 ± 0,07 ns** (28 rebases; o pior, +0,8 ns) | 5 min a 312,5 kS/s |
| Escala do "nada aconteceu" (degrau medido entre eventos) | ±0,1 a 1,4 ns | ±0,29 ns | desvio robusto |
| Amostras fora da grade a 312,5 kS/s | não medidas | **0** | 60 s, 5 min, 60 s com o ARM ocupado (`dd` na DDR), 60 s com 2 canais |
| Folga mínima da PRU a 312,5 kS/s | não medida | **3 a 5 ciclos (15 a 25 ns)** | a carga no ARM custou 1 ciclo |
| Ciclos entre as leituras do contador no rebase | — | 7 (o simulador dá 2) | medidos pela PRU a cada captura |
| Diafonia, canal 1 → canal 0 | −94,1 a −95,1 dB (250 kS/s) | −97,3 dB | 2 canais, 312,5 kS/s no total |

**O teto com período constante** (parte J: 1 tick por vez, 2 blocos e 1 troca de buffer por taxa):

| Ticks | Taxa | Amostras fora da grade (de 2 097 152) | O que atrasa |
|---|---|---|---|
| 640 a 635 | 312,50 a 314,96 kS/s | 0 (folga de 2 a 10 ciclos) | nada |
| 634 a 620 | 315,5 a 322,6 kS/s | 1 ou 2, de 1 a 13 ciclos (uma vez, a 632 ticks, nenhuma) | a troca de buffer (e a amostra seguinte) |
| 619 a 611 | 323,1 a 327,3 kS/s | de 117 a 1,56 milhão | também as amostras comuns |
| 610 ou menos | 327,9 kS/s ou mais | todas | o laço sem espera (~326 a 328 kS/s, como em 21/10) |

**O que os números dizem.**

* **O jitter de 8,5 ns era da PRU** (a espera por sondagem soltava a amostra de 0 a ~6 ciclos depois do instante) e
  sumiu com a espera de precisão. O ruído com o tom caiu ao do ADC, e o SNR subiu ~5 dB em 10 s.
* **Um degrau na PRU só pode valer múltiplos de 5 ns** (1 ciclo de 200 MHz). Todos os degraus medidos ficaram abaixo
  de 1 ns: **zero ciclos** em toda troca de buffer e em todo rebase do contador.
* **O que sobra no SINAD é do gerador:** o ruído de fase a menos de 5 Hz do tom (±0,7 a 1 Hz, a −72 a −80 dBc) e a
  THD de −72 dB. Por isso uma FFT de 60 s dá SINAD menor (~60 dB) que uma de 10 s: ela resolve esse ruído de fase.
* **A folga é pequena, e dependia do sinal.** O quadro comum leva **605 + (bits 1 da amostra) ciclos**: a leitura de
  um bit 1 executava uma instrução a mais e esticava o SCLK em 1 ciclo. Não era "a escrita na DDR, ao acaso", como
  esta seção dizia até a análise de 22/10 (abaixo). A troca de buffer soma ~20 ciclos (5 acessos à memória
  compartilhada de uma vez): a 640 ciclos, sobram 3 a 13 nela, conforme os bits 1 da amostra da troca. O simulador,
  com 1 ciclo por instrução, previa 25; com as latências medidas (F12), reproduz a placa.

**O quadro dependia do dado** (análise de 22/10, a mesma varredura J). A fração de amostras atrasadas a cada período
bate com a fração de amostras que têm tantos bits 1, tirada das próprias capturas (o tom cruza o meio da escala:
0x7FFF tem 15 bits 1, 0x8000 tem 1):

| Ticks | Atrasadas | Amostras com ≥ N bits 1 | N |
|---|---|---|---|
| 619 | 5,58 × 10⁻⁵ | 5,53 × 10⁻⁵ | 15 |
| 618 | 8,07 × 10⁻⁴ | 8,15 × 10⁻⁴ | 14 |
| 617 | 5,56 × 10⁻³ | 5,66 × 10⁻³ | 13 |
| 616 | 2,44 × 10⁻² | 2,56 × 10⁻² | 12 |

* O ajuste dá um quadro de **605 + bits 1** ciclos (medida/prevista de 0,94 a 0,98). Nas 43 capturas de calibração de
  22/10 (1 bloco, sem troca), a folga foi **exatamente 20 ciclos em todas**: 640 − 605 − 15.
* **O instante da amostra nunca dependeu disso** (a descida do CS vem depois da espera de precisão): o jitter de
  0,00 ns continua valendo. Dependiam a folga, o teto de taxa e o padrão do SCLK (9 ou 10 ciclos em alto, conforme o
  bit lido).
* Corrigido no firmware seguinte (leitura sem desvio, troca de buffer espalhada): o simulador calibrado prevê 41
  ciclos de folga numa amostra comum, qualquer que seja o sinal, e ≥ 31 com a troca; teto ~328 kS/s. Falta a bancada
  (`./varrer_taxa.sh --grade`, agora até 339 kS/s).
* Figura `grade_bits` (macros `\GradeBitsBase`, `\GradeBitsRazaoMin`, `\GradeBitsRazaoMax`, `\GradeBitsPeriodoEx`,
  `\GradeBitsMedidaEx`, `\GradeBitsPrevistaEx`).

**Figuras:** `grade_jitter` (o ruído contra a inclinação do tom, antes e depois), `grade_degraus` (os 117 degraus de
5 min, dentro de ±1/2 ciclo), `grade_teto` (a parte J) e `grade_bits` (a parte J contra os bits 1). **Macros:** `\GradeJitterAntes`, `\GradeJitterDepois`,
`\GradeRuidoPlanoAntes`, `\GradeRuidoLargoAntes`, `\GradeRuidoLargoDepois`, `\GradeTrocasN`, `\GradeTrocasMedia`,
`\GradeRebasesN`, `\GradeRebasesMedia`, `\GradeDegrauPior`, `\GradeControle`, `\GradeCiclosRebase`,
`\GradeFolgaMin`, `\GradeFolgaMinNs`, `\GradeTetoConstante`, `\GradeTetoTrocas`, `\GradeTetoComuns`,
`\GradeTetoTodas`.

**Para medir de novo:**

```bash
uv run scripts/medir_captura.py $DADOS/lab/2026-10-22/T7f_2026-10-22_0435/G_*.bin --max-amostras 3145000 --csv t7f.csv
```

## T7e: esperas do CS e teto de taxa

**21/10/2026** · firmware `v0.6-10` e `v0.6-11` (a parte retomada com `--continuar`; espera por sondagem; rebase do contador com defeito: degrau de 5 a 13 µs a cada
10,74 s, corrigido no mesmo dia) · `$DADOS/lab/2026-10-21/T7e_2026-10-21_1731/` (101 capturas) · tom de 10 kHz em
±2,56 V. Os números de qualidade foram medidos antes de 10,7 s (antes do 1º rebase).

| `--atraso-cs` (S,H,A) | Teto medido (ARM) | Simulador |
|---|---|---|
| `200,100,100` (o padrão até 21/10) | 142,8 kS/s | 143,3 kS/s |
| `100,50,50` | 199,8 kS/s | 201 kS/s |
| `50,25,25` | 250,0 kS/s | 252 kS/s |
| `20,10,10` | 294,5 kS/s | 296 kS/s |
| `10,5,5` | 313 kS/s | 315 kS/s |
| `6,2,6` | 319 kS/s | 321 kS/s |
| `3,1,3` (o mínimo do datasheet; o padrão desde 21/10) | 326 kS/s | 328 kS/s |

* **A qualidade não depende das esperas:** até `3,1,3` e até 250 kS/s, SINAD de 62,1 a 63,7 dB, THD de −71,6 a
  −72,0 dB, ruído com o tom de 2,4 a 2,9 LSB (o jitter de 8,5 ns, achado depois: T7f), amplitude em ±0,02 %, DC em
  ±0,05 mV; em curto, 0,74 a 0,76 LSB; 0 quadros com ruído no SDO e 0 buffers sobrescritos.
* Esse "teto" é o do laço sem espera (todas as amostras atrasadas). O teto com período constante é o do T7f.

## T7a a T7c: integridade e estabilidade

**19/10/2026** · firmware anterior a out/2026 (zerava o contador de ciclos na troca de buffer: a grade escorregava
6,97 µs a cada troca) · `$DADOS/lab/2026-10-19/` · tom de 10 kHz no canal 1.

| Captura | Resultado |
|---|---|
| T7c, 10 min a 100 kS/s (58 blocos) | +0,697 amostra (6,97 µs) em **todas** as 57 trocas, ±0,002; nenhuma amostra perdida |
| Dentro de cada bloco (11 janelas espalhadas em 10 min) | tom em 9 999,5690 a 9 999,5699 Hz (**0,09 ppm**) e amplitude em 0,304809 a 0,304836 V RMS (**0,009 %**) |
| T7a/T7b, 1 bloco (50 e 100 kS/s, 1 e 2 canais) | maior salto de fase de 0,001 a 0,004 amostra |

O defeito do salto foi corrigido em out/2026 (validado em 21/10: ≤ 0,06 µs) e o resto da grade em 22/10 (T7f). A
estabilidade em 10 min com o firmware atual ainda não foi medida: a captura mais longa do T7f tem 5 min.

## T6: vários canais

**19/10/2026** · firmware antigo · os dois canais em ±2,56 V · 100 kS/s no total. E **22/10/2026** · `v0.7-1` ·
312,5 kS/s no total.

| Medida | Resultado | Condições |
|---|---|---|
| Diafonia, canal 1 → canal 0 (em curto) | **−94,7 dB** | 10 kHz a −15,5 dBFS, 100 kS/s (19/10) |
| Diafonia, canal 1 → canal 0 | **−97,3 dB** | 10 kHz, 312,5 kS/s (22/10, T7f parte K) |
| Atraso entre canais (o mesmo sinal nos canais 1 e 2) | **9,954 µs** contra 10,000 µs (−0,46 %) | 1 kHz, 100 kS/s (19/10) |

Falta: o ponto de 20 kHz (com 2 canais a 100 kS/s, a Nyquist é de 25 kHz) e o atraso entre canais a 312,5 kS/s
(esperado: 3,20 µs).

## T4: taxa de amostragem real

**19/10/2026** · firmware antigo (só o 1º bloco de cada captura, por causa do salto na troca) · tom de 10 kHz, 20 Vpp,
sem a leitura do contador do osciloscópio.

| Taxa pedida | Ticks | Tom medido | Diferença para as taxas exatas | Prevista pelos ticks |
|---|---|---|---|---|
| 50 000 | 4000 | 9 999,5681 Hz | 0 (referência) | 0 |
| 100 000 | 2000 | 9 999,5682 Hz | +0,01 ppm | 0 |
| 125 000 | 1600 | 9 999,5680 Hz | −0,01 ppm | 0 |
| 102 400 | 1953 | 9 998,9279 Hz | −64,03 ppm | −64,0 ppm |
| 110 000 | 1818 | 9 998,5684 Hz | −99,98 ppm | −100,0 ppm |

* **Taxa = 200 MHz ÷ ticks**, confirmada a 0,02 ppm: nenhum ciclo fixo a mais por amostra.
* **Erro comum de −43,2 ppm** = o do cristal da BeagleBone somado ao do gerador. Separar os dois pede o contador de
  frequência do osciloscópio.

## T3: resposta em frequência da cadeia de tensão

**19/10/2026** · firmware antigo · 48 pontos de 50 Hz a 45 kHz, 100 kS/s, `--ref-externa` (RMS na entrada do divisor
pelo osciloscópio), sem repetições · perfil `scripts/sondas/cadeia_tensao.json`.

| Grandeza | Resultado |
|---|---|
| −3 dB | **17,26 ± 0,16 kHz** |
| Modelo de 2ª ordem | f0 = 24,06 ± 0,21 kHz, Q = 0,540 ± 0,006, K = 0,9969 ± 0,0028 |
| A 45 kHz | −12,5 dB |
| Resíduo do ajuste | 0,13 dB |

**Figura:** `perfil_cadeia_tensao` (macros `\CadeiaTensao...`).

**22/10/2026: até 140 kHz, na taxa padrão** · firmware `v0.7-1-gb2f9078` · 43 pontos de 50 Hz a 140 kHz, 312,5 kS/s,
1 canal, faixa de ±2,56 V, 1 bloco por ponto, `--ref-externa`, sem repetições ·
`$DADOS/lab/2026-10-22/capturas/cadeia_tensao_312k/` · perfil `scripts/sondas/cadeia_tensao_312k.json` (gerado com
`--ganho 19.357`, como o de 19/10).

| Grandeza | 22/10 (312,5 kS/s, até 140 kHz) | 19/10 (100 kS/s, até 45 kHz) |
|---|---|---|
| −3 dB | **16,83 ± 0,13 kHz** | 17,26 ± 0,16 kHz |
| Modelo de 2ª ordem | f0 = 24,17 ± 0,07 kHz, Q = 0,529 ± 0,003 | f0 = 24,06 ± 0,21 kHz, Q = 0,540 ± 0,006 |
| Resíduo do ajuste | 0,105 dB (43 pontos, até 140 kHz) | 0,13 dB |
| Outro polo até 140 kHz | nenhum (o 2ª ordem + polo real não melhora o BIC) | — |
| No último ponto | **−30,6 dB em 140 kHz** (a correção multiplica o sinal e o ruído por 34) | −12,5 dB em 45 kHz |
| Dispersão do ganho abaixo de 1 kHz | **0,44 %** | 0,79 % |
| Integridade das 43 capturas | 0 atrasadas, 0 com ruído no SDO; folga de 20 ciclos em todas | — |

* **É a mesma cadeia:** nas frequências em comum, os dois perfis diferem **0,13 dB rms** (o pior ponto, −0,29 dB),
  com taxa (100 e 312,5 kS/s), faixa do ADC (±10,24 e ±2,56 V) e firmware diferentes. A dispersão em baixa
  frequência caiu à metade com a faixa de ±2,56 V (4 vezes mais resolução no mesmo sinal).
* **O 2ª ordem vale até 140 kHz** (o filtro interno do ADS8688): os 3 parâmetros descrevem 3,5 décadas a 0,1 dB.
* **Para a produção a 312,5 kS/s, use `--sonda 1:cadeia_tensao_312k`**: o de 19/10 para em 45 kHz e mantém o ganho
  constante acima disso (a correção estaria errada por até 30 dB em 140 kHz).
* **A referência caiu 14 % de 50 Hz a 140 kHz** (7,06 → 6,10 V rms, lida a cada ponto). O perfil vale se a leitura é a
  tensão real na entrada da cadeia; se a queda é do instrumento, o perfil herda o erro dele. Anote o instrumento na
  próxima rodada (o caderno de 22/10 ficou em branco) e confira 2 ou 3 pontos altos no osciloscópio.
* Falta `--repeticoes 3`, para a incerteza de cada ponto.

**Figura:** `perfil_cadeia_tensao_comparacao` (os dois perfis e a diferença; macros `\CadeiaTensaoNovaFzero`,
`\CadeiaTensaoNovaQ`, `\CadeiaTensaoNovaFcorte`, `\CadeiaTensaoNovaResiduo`, `\CadeiaTensaoNovaGanhoFmax`,
`\CadeiaTensaoNovaCorrecaoFmax`, `\CadeiaTensaoDifRms`, `\CadeiaTensaoDispersaoAntiga`, `\CadeiaTensaoDispersaoNova`).

```fish
uv run scripts/gerar_perfil_sonda.py $DADOS/lab/2026-10-22/capturas/cadeia_tensao_312k --referencia-externa --ganho 19.357 --plot
uv run report/gerar_figuras.py perfil_cadeia_tensao_comparacao --png
```

## T2: tensão contínua

**19/10/2026** · firmware antigo · faixa de ±10,24 V · Fluke 289 no nó de entrada: +9,989; +4,9924; +0,0019; −4,9924
e −9,988 V.

| Grandeza | Medido | Esperado |
|---|---|---|
| Razão real do divisor (com a carga do ADC) | **0,051554** | 0,05157 (−0,03 %) |
| `$GV` = 1 ÷ razão | **19,397** | 19,357 nominal (+0,21 %) |
| Offset no pino | +3,49 mV | o mesmo do T1 |
| Resíduo de linearidade | **≤ 0,22 LSB** nos 5 pontos | INL do datasheet ±0,75 LSB |
| Ruído em cada nível | 0,50 a 0,57 LSB | o do T1 |

## T1: piso de ruído

**19/10/2026** · firmware antigo · entrada em curto · `--inicio 100`.

| Faixa | Ruído | Datasheet (típico) | Offset (canal 1) |
|---|---|---|---|
| ±10,24 V | **0,51 a 0,52 LSB** (159 a 161 µV), igual de 50 a 200 kS/s | 172 µV | +3,4 mV |
| ±5,12 V | **0,58 LSB** (91 µV) | 96 µV | +2,5 mV |
| ±2,56 V | **0,75 LSB** (58 µV) | 61 µV | +2,6 mV |

* O ruído segue o datasheet (5 a 7 % abaixo do típico) e não depende da taxa nem do número de canais.
* O offset do canal 1 (+2,5 a +3,5 mV no pino) passa do máximo do datasheet (±0,75 mV); o do canal 0 é de +0,05 a
  +0,21 mV. A suspeita é a ligação do divisor, não o ADC.

**22/10/2026, a 312,5 kS/s** · firmware `v0.7-1-gb2f9078` · canal 1 em curto, 2 blocos (6,7 s) por faixa ·
`$DADOS/lab/2026-10-22/T1_curto_312k_f{2048,1024,512}.bin` · `--inicio 100`.

| Faixa | Ruído | Densidade | Offset (canal 1) | Folga da PRU |
|---|---|---|---|---|
| ±10,24 V | **0,54 LSB** (169 µV) | 400 nV/√Hz | +3,56 mV | 11 ciclos |
| ±5,12 V | **0,61 LSB** (95 µV) | 192 nV/√Hz | +2,51 mV | 13 ciclos |
| ±2,56 V | **0,79 LSB** (62 µV) | 106 nV/√Hz | +2,59 mV | 12 ciclos |

* **A 312,5 kS/s, o mesmo ruído de 19/10** (+4 a +6 %, dentro do típico do datasheet): a taxa mais alta e a espera
  de precisão não trouxeram ruído. O offset é o mesmo.
* A folga de 11 a 13 ciclos (contra 3 a 5 com o tom no T7f) é o quadro que dependia do dado: em curto, as amostras
  têm ~3 bits 1 (0x8021); com o tom, até 15 (ver o T7f).

## T0: escala do ADC

**19/10/2026** · firmware antigo · +10 V DC (Fluke 289: 9,988 V) e 0 V no canal 1.

| Faixa | Razão medida, descontado o offset | Ruído (0 V) |
|---|---|---|
| ±10,24 V | **0,9997** | 0,51 LSB (160 µV) |
| ±5,12 V | **0,9997** | 0,59 LSB (92 µV) |
| ±2,56 V | **0,9992** | 0,74 LSB (58 µV) |

* Escala certa nas três faixas, dentro de 0,08 %.
* **Transitório ao trocar a faixa:** as primeiras amostras depois de uma troca de faixa decaem de até ~1 V; ficam
  abaixo de 1 LSB em ~80 µs (constante de tempo de ~8 µs, a do filtro interno do ADC). O `medir_captura.py` pula
  200 µs.
