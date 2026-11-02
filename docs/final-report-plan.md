# Rumo ao relatório final

O plano da **1ª versão do relatório científico final** da IC (FAPESP, processo 2025/22891-1): o que o instrumento já
demonstra, o que falta em cada seção do texto, as idas ao laboratório que faltam e a ordem do trabalho. O texto está em
`report/relatorio/latex/` (fora do git, só no checkout principal), os números em [`bench-results.md`](bench-results.md)
e a narrativa em [`report-notes.md`](report-notes.md).

**Atualizado em 02/11/2026**, depois dos dados de 23/10.

---

## 1. A tese do relatório

O projeto era montar um sistema embarcado para identificar supraharmônicos, e ele funciona. O relatório precisa
mostrar isso com números, numa frase:

> **O SH-Analyzer amostra a 400 kS/s com a grade de tempo exata e a integridade medida em cada captura. A resposta
> da cadeia de tensão é conhecida em magnitude e fase até 180 kHz, por um método sem instrumento de referência, e
> foi confirmada por senoides a ±0,05 dB até 270 kHz. Com ela, o instrumento identifica um supraharmônico de 9 kHz
> 70 dB abaixo do 60 Hz e mede um de 25 kHz no nível certo, a 0,03 dB.**

Para a tese ficar completa faltam duas coisas: **a sonda de corrente** (T10, o objetivo central da proposta) e **uma
carga real** (T11). O resto é acabamento.

---

## 2. O que já está demonstrado

Cada linha já tem número, data, firmware atual e figura: pode ir para o texto hoje.

| Afirmação | O número | Ensaio | Figura (`report/gerar_figuras.py`) | Seção |
|---|---|---|---|---|
| A amostragem não perde nem atrasa amostra | 0 atrasadas e 0 leituras divergentes em ~140 milhões de quadros; jitter de 0,00 ns (piso do método: ~0,3 ns) | T7f e T7g, 22/10 | `grade_jitter`, `grade_degraus`, `grade_teto`, `grade_bits` | 4.4 e 6.3 |
| A taxa vai a 400 kS/s, com folga | teto com período constante de 419,3 kS/s; 18 ciclos de folga a 400 kS/s; o simulador previu o teto a 1 ciclo | T7g, 22/10 | `grade_teto` | 4.5 e 6.3 |
| O ruído é o do datasheet | 62 µV RMS em ±2,56 V (datasheet: 61 µV), a 312,5 e a 400 kS/s | T1, 22/10 e 23/10 | — | 6.2 |
| A cadeia de tensão é conhecida em magnitude e fase | 2ª ordem com f0 = 22,811 kHz e Q = 0,5001 (dois polos reais, o filtro do ADC) × um polo real em 800 kHz; −3 dB em 14,68 kHz; resíduo de 0,01 dB e 0,14°; fase mínima | T3f, 22/10 | `perfil_cadeia_tensao_fase` | 6.5 |
| Um método independente confirma o perfil | 10 senoides de amplitude conhecida, de 60 Hz a 270 kHz, a ±0,05 dB do modelo (0,027 dB rms); o polo de 800 kHz é da cadeia | T9 e T8, 23/10 | `validacao_cadeia_senoides` | 6.5 |
| O *aliasing* é previsível | um tom acima da Nyquist dobra com a atenuação da cadeia na frequência real, a 0,01 dB: −30,6 dB em 130 kHz e −43,5 dB em 270 kHz | T8, 23/10 | `validacao_cadeia_senoides` | 6.5 e 7.3 |
| O instrumento identifica supraharmônicos | 25 kHz a −40,0 dBc com a correção (−46,9 sem ela); 9 kHz a −70 dBc, 59 dB acima do piso; as bandas laterais de uma AM a 0,02 dB da teoria | T9, 23/10 | `espectro_supraharmonicos` | 6.7 |
| O limite de detecção | 8 µV de pico na entrada do divisor em 9 kHz e 105 µV em 180 kHz, numa captura de 30 s em ±2,56 V | T9, 23/10 | `espectro_supraharmonicos` | 6.7 e 7.3 |
| A multiplexação não contamina | diafonia de −95,5 dB entre canais a 400 kS/s | T7g, 22/10 | — | 6.4 |

Os perfis por senoides com o osciloscópio como referência (`cadeia_tensao` e `cadeia_tensao_312k`) ficam como
histórico: acima de ~40 kHz, eles erraram 1,2 a 1,3 dB pela referência, e as senoides de 23/10, com o gerador como
referência, mostraram isso.

---

## 3. O que falta, seção a seção

O LaTeX segue o roteiro da FAPESP para Bolsas no País. Hoje ele tem 24 marcas `\pendente{...}` (as notas em vermelho
do rascunho). A coluna **Bloqueio** diz do que cada uma depende:

* 🟢 **dados prontos:** dá para escrever agora;
* 🔬 **laboratório:** espera uma medida;
* 👤 **você:** só você sabe (eventos, datas, a história da placa).

| Seção | Estado | O que falta | Bloqueio |
|---|---|---|---|
| Folha de rosto, resumo | 🟡 | O resumo do projeto (até 2 páginas): escreva por último | depois de tudo |
| Agradecimentos | ⏳ | Os agradecimentos pessoais | 👤 |
| 1 Introdução | ✅ | Revisar no fim | — |
| 2 Fundamentação | ✅ | — | — |
| 3 Sensores e condicionamento | 🟡 | (a) A situação das placas: a de aquisição usada e a nova no Altium. (b) Os sensores avaliados, numa tabela comparativa com os critérios da proposta. (c) A razão do divisor com o firmware atual (T2). (d) A sensibilidade medida do canal de corrente (T10). (e) Quando o RC de 3,5 kHz saiu e a situação do capacitor do canal de corrente. (f) **Novo:** a placa só é alimentada pela fonte de 5 V da BeagleBone, e o porquê | (a), (b), (e) 👤; (c), (d) 🔬; (f) 🟢 |
| 4 Firmware | ✅ | Uma pendência menor | — |
| 5 Ferramentas de análise | 🟡 | **Acrescentar a calibração por ondas quadradas (`calibrar`) e a razão de dois canais** (a sonda de corrente com fase, de 24/10): hoje o texto só descreve o `medir_fase.py` de um canal | 🟢 (o método); 🔬 (o resultado) |
| 6.1 Montagem e procedimento | 🟡 | As datas das sessões e o que se mediu em cada uma | 🟢 (até 23/10) |
| 6.2 Conversor | ⏳ | Escala, ruído e linearidade nas três faixas contra o datasheet (T0 a T2, com o firmware atual); a distorção (T5) | 🔬 |
| 6.3 Taxa, grade e integridade | 🟡 | A exatidão da taxa (T4, com um contador) e a estabilidade numa captura longa (T7c, 10 min) | 🔬 |
| 6.4 Multicanal | 🟡 | O atraso entre canais a 400 kS/s (esperado: 2,5 µs) | 🔬 (5 min) |
| 6.5 Cadeia de tensão | 🟡 | **A origem do polo e o *aliasing* já podem entrar** (figura `validacao_cadeia_senoides`). Falta a faixa de produção (±10,24 V) e o K com o firmware atual (T2) | 🟢 e 🔬 |
| 6.6 Sonda de corrente | ⏳ | **Tudo: o T10** (o perfil com magnitude e fase, as conferências, a figura) | 🔬 |
| 6.7 Supraharmônicos | 🟡 | **Os sinais conhecidos já podem entrar** (figura `espectro_supraharmonicos`). Falta uma carga real (T11) | 🟢 e 🔬 |
| 7 Discussão | 🟡 | Os desvios em relação à proposta (sensores, placa, artigos) e as limitações (a lista da [seção 6](#6-as-limitações-a-declarar)) | 👤 e 🟢 |
| 8 Conclusões | ⏳ | O que o instrumento mede ao fim, com que exatidão, e o quanto cada objetivo foi atingido; os próximos passos | depois dos resultados |
| 9 Eventos, publicações e formação | ⏳ | Os eventos (o Congresso de IC da Unicamp?), as publicações, a formação e a *release* do repositório deste relatório | 👤 |
| Apêndices | 🟡 | Atualizar o quadro dos ensaios | 🟢 |
| Anexos | ⏳ | Certificados e a 1ª página de cada publicação | 👤 |

**Para escrever já** (🟢, sem esperar o laboratório): 3(f), 5 (o método), 6.1 (até 23/10), 6.5 (o polo e o
*aliasing*), 6.7 (os sinais conhecidos), as limitações da seção 7 e o quadro dos ensaios. São as seções que os dados
de 23/10 destravaram.

---

## 4. O laboratório: o que falta medir

A avaliação das sondas pelo osciloscópio fica para depois. Sem ela, tudo o que falta continua possível: o T10 se
apoia na cadeia de tensão já validada, e as conferências dele são internas (garra invertida, espiras, amplitude).

### Essencial para o relatório

| O que | Por que o relatório precisa | Tempo | Ida |
|---|---|---|---|
| **T10: a sonda de corrente** pela razão de dois canais | O objetivo central; a seção 6.6 inteira | ~1 h 20 com as conferências | A |
| **A cadeia de tensão em ±10,24 V** (`calibrar`, sem osciloscópio) | A faixa de produção; hoje o perfil é de ±2,56 V | ~40 min | A |
| **T2 e T0 com o firmware atual** | A razão do divisor e o K dos perfis; a regra do texto é só firmware atual | ~20 min | A |
| **T6: o atraso entre canais a 400 kS/s** | A fase entre tensão e corrente depende dele | 5 min | A |
| **T11: uma carga real** (fonte chaveada, carregador ou LED, em 127 V com transformador de isolamento e supervisão) | A figura que fecha a tese: um supraharmônico de verdade, em tensão e em corrente | ~1 h 30 | B |

### Desejável

| O que | Para quê | Tempo | Ida |
|---|---|---|---|
| T1: o pino do canal 1 em curto direto | A origem do offset de +2,6 mV (declarar ou resolver) | 5 min | A |
| 75 kHz sem FM | Explicar o −1,6 dB da FM (gerador ou medida) | 2 min | A |
| T9b: dois tons (20,0 e 20,3 kHz) | A resolução do método e a intermodulação | 10 min | A |
| T7c: 10 min de captura | A estabilidade com o firmware atual | 15 min | B |
| T4 com um contador de frequência | Separar o erro do cristal do do gerador (hoje, −43 ppm juntos) | 30 min | B |
| T5 com uma fonte de baixa distorção | THD, SINAD e ENOB do ADC, não do gerador | 1 h | quando houver a fonte |
| Fotos da bancada, da placa e do laço de corrente | As figuras de montagem do relatório (não dá para fazer depois) | 10 min por ida | A e B |

**Ida A (~2 h 30):** o passo a passo está no roteiro, em
[Passo a passo da próxima ida](lab-procedure.md#passo-a-passo-da-próxima-ida-a-sonda-de-corrente-e-a-faixa-de-produção-sem-osciloscópio-2-h-30).
O que levar: **a fonte de 5 V da BeagleBone** (pelo USB a placa não liga), um resistor de 5 a 10 Ω não indutivo
medido a 4 fios, fio para 20 espiras e, se houver, uma fonte de corrente quadrada de 1 a 2 A.

**Ida B (~2 h):** o T11 pede a rede e supervisão; o roteiro dele está no [T11](lab-procedure.md#t11-ponta-a-ponta).
Combine com o orientador antes.

---

## 5. O perfil das sondas: o que falta

### Cadeia de tensão

| Item | Estado |
|---|---|
| Magnitude e fase de 50 Hz a 178,5 kHz, em ±2,56 V (`cadeia_tensao_fase`) | ✅ 22/10 |
| Validação independente por senoides, de 60 Hz a 270 kHz | ✅ 23/10 |
| A origem do polo de 800 kHz | ✅ 23/10: é da cadeia |
| **A faixa de produção, ±10,24 V** (`cadeia_tensao_fase_1024`) | ⏳ ida A |
| O K com o firmware atual (T2) | ⏳ ida A |
| A reprodutibilidade em outro dia | ⏳ ida A (o `calibrar` repete ±2,56 V) |

### Sonda de corrente (SCT013 + carga de 0,12 Ω + ADC)

| Item | Estado |
|---|---|
| O método: razão de dois canais, com a fase absoluta e a diafonia subtraída (`calibrar --canal-referencia`, `medir_fase.py --canal-referencia`) | ✅ 24/10, validado com dados sintéticos |
| **O perfil medido**, magnitude e fase até ~95 kHz | ⏳ ida A |
| As conferências: garra invertida, N = 10 e 20, duas amplitudes, reabrir a garra | ⏳ ida A |
| A validação fora da calibração (*hold-out*) | ⏳ Sem osciloscópio, por quadradas: refazer o perfil sem uma das frequências e comparar com ela |
| **Acima de 95 kHz** (a Nyquist de cada canal, com dois canais a 400 kS/s) | ⏳ Duas saídas: (a) a **extensão por capturas de um canal**, ancoradas na de dois canais (proposta, sem osciloscópio; simulada a 0,09 dB e 0,55° até 187 kHz); (b) o método de um canal com a entrada no osciloscópio (adiado) |

### No software

| Item | Para quê | Decisão |
|---|---|---|
| **S3: a fase na correção** (hoje a correção só usa a magnitude) | A potência por componente (V × I) no T11 | Implementar antes do T11, se ele for medir potência; senão, trabalho futuro |
| A extensão da sonda de corrente até 190 kHz | O perfil de corrente na faixa inteira | Implementar antes da ida A, para coletar as capturas de um canal no mesmo dia |
| A figura do perfil de corrente no `gerar_figuras.py` | A seção 6.6 | Depois da ida A |

---

## 6. As limitações a declarar

Declarar os limites com o efeito de cada um é parte do rigor do relatório (seção 7.3 do LaTeX).

* **Banda e *aliasing*.** A 400 kS/s com 1 canal, a Nyquist é 200 kHz e a banda corrigida vai a 178 kHz; com tensão
  e corrente juntas, 95 kHz por canal. Não há filtro *anti-aliasing* além do interno do ADC: um componente de
  270 kHz aparece em 130 kHz atenuado só 43,5 dB (23/10).
* **O filtro interno do ADC.** A correção pelo perfil devolve a amplitude, mas multiplica o ruído pelo mesmo fator
  (×63 em 178 kHz): o menor tom detectável sobe de 8 µV em 9 kHz para 105 µV em 180 kHz.
* **Canal de corrente.** 60 µV/A sobre a carga de 0,12 Ω, mesmo na menor faixa do ADC: o piso de detecção em
  corrente é de miliampères (o número sai do T10).
* **Faixa de produção.** O perfil de tensão é de ±2,56 V; o de ±10,24 V sai da ida A.
* **Alimentação.** A placa de aquisição só funciona com a fonte de 5 V da BeagleBone (por projeto da placa).
* **Offset de ~2,6 mV** no canal 1 (DC, fora da banda), de origem ainda não isolada.
* **Transitório de ~80 µs** depois de trocar a faixa de um canal (descartado na análise).
* **Referências.** A amplitude do gerador (as senoides de 23/10) e a do multímetro (T2). O osciloscópio, como
  referência de amplitude acima de ~1 kHz, mostrou um erro de até 1,3 dB (a ponta): o método das quadradas dispensa
  ele.
* **A FM de 75 kHz** saiu 1,6 dB abaixo do nominal, sem explicação ainda (os tons de 40 e 130 kHz batem).

---

## 7. As figuras

| Figura | Estado | Seção |
|---|---|---|
| `perfil_cadeia_tensao_fase`: o Bode da cadeia (T3f) | ✅ | 6.5 |
| `validacao_cadeia_senoides`: senoides contra o modelo, até 270 kHz | ✅ (nova) | 6.5 |
| `espectro_supraharmonicos`: 60 Hz forte e supraharmônicos fracos, sem e com a correção | ✅ (nova) | 6.7 |
| `grade_jitter`, `grade_degraus`, `grade_teto`, `grade_bits`: a grade de tempo | ✅ | 4.4 e 6.3 |
| `perfil_cadeia_tensao_referencia`: o erro da referência do osciloscópio | ✅ | apêndice |
| O diagrama de blocos do sistema (placa, PRU, DDR, ARM, análise) | ⏳ | 3.1 |
| O perfil da sonda de corrente, magnitude e fase | ⏳ ida A | 6.6 |
| O espectro de uma carga real, em tensão e em corrente | ⏳ ida B | 6.7 |
| A tabela medido × datasheet do conversor (T0 a T2) | ⏳ ida A | 6.2 |
| Fotos: a bancada, a placa, o laço de corrente | ⏳ | 3 e 6.1 |

Gere as figuras com `uv run report/gerar_figuras.py` (as de bancada leem as capturas em `$DADOS`). Inclua sem
escalar e carregue as macros com `\numerosdafigura{nome}`.

---

## 8. Cronograma sugerido

| Semana | O que |
|---|---|
| 03 a 09/11 | Escrever as seções 🟢 (3f, 5, 6.1, 6.5, 6.7, limitações, quadro dos ensaios). Preencher os 👤. Preparar a ida A: o resistor, as espiras, a fonte de 5 V, a fonte de corrente |
| 10 a 16/11 | **Ida A** (T10, ±10,24 V, T2, T0, T6 e os itens curtos). A análise e a figura do perfil de corrente |
| 17 a 23/11 | **Ida B** (T11), se o orientador aprovar. Escrever 3(c, d), 6.2 a 6.4 e 6.6 |
| 24 a 30/11 | Resumo, conclusões e revisão; `\rascunhofalse` e a 1ª versão para o orientador |

O cronograma é uma sugestão: ajuste-o à data de entrega combinada.

---

## 9. Decisões que dependem de você ou do orientador

1. **O período e o prazo.** A vigência terminou em 31/10/2026, e o relatório cobre de 01/07 a 31/10/2026
   (`\periodorelatorio`). O termo de outorga lista os relatórios científicos para 30/06/2026 e 30/06/2027. Confirme
   com o orientador a data de entrega do final e se as medições de novembro entram no texto.
2. **O T11 na rede**, que exige supervisão e transformador de isolamento.
3. **A fase na correção (S3) e a extensão até 190 kHz:** implementar antes do relatório ou declarar como trabalho
   futuro.
4. **A avaliação das sondas pelo osciloscópio**, adiada. Sem ela, a validação do T10 se apoia na cadeia de tensão
   (validada por dois métodos) e nas conferências internas: o texto deve dizer isso.
5. **A *release*** do repositório que acompanha o relatório (seção 9 do LaTeX).
