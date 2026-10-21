# SH-Analyzer — Propostas de melhoria

Lista **só do que ainda está por fazer**, com o motivo medido, a proposta e como saber que deu certo. O que já foi
feito sai daqui: a história fica no `git log` e, para o relatório, em [`report-notes.md`](report-notes.md).

Cada item tem um código (F = firmware/aquisição, P = Python, T = testes/CI, R = repositório/dados/documentação,
H = hardware, S = sondas) e as colunas: **ganho** (o que melhora), **esforço** e se **toca a PRU** — mudança no
assembly só conta como feita depois de montada com `clpru` e validada no hardware.

Revisado em 21/10/2026. Saíram daqui, nesta ordem:

* a revisão do firmware (salto de 7 µs na troca de buffer, contadores de integridade, cabeçalho v4), a revisão dos
  testes e o novo `compactar_amostras.py`; a análise das capturas de bancada de 19/10 trouxe o F9 e o P6;
* R1 a R4 e T1: dados fora do repositório, nomes em inglês sem espaço nem acento, contagem de testes num lugar só,
  backups do Altium fora do git, `.gitattributes`/`.editorconfig`/`CITATION.cff` e a CI compilando o C e passando o
  `shellcheck`;
* a revisão do `adc_tool`: o P2 (importações sob demanda) e a parte do gráfico do P1; trouxe o P8;
* o P7, como opções extras do `--bandas-iec`: janelas sincronizadas e agregação de 3 s/10 min da IEC 61000-4-30;
* o R2 (histórico do git sem os dados antigos, `.git` de ~90 para ~29 MB num clone novo);
* o P6 (salto nas trocas de buffer em µs, comparado com os outros segmentos), o F9 na análise (o `medir_captura`
  pula 200 µs; as duas ferramentas avisam), o P4 (taxa da PRU por padrão, `--fs-pedida`), o P3 (correção de sonda
  em `contexto`), o P5 (atributos de proveniência no HDF5), o S8 (aviso de perfil com mais de 1 ano) e o F5
  (cabeçalho v5: versão do firmware e taxa medida pelo ARM). A conferência nas capturas de 19/10 mostrou que o salto
  antigo também derruba o SINAD de uma FFT de vários blocos (63 → 22 dB) e puxa a frequência em +1,5 ppm.

---

## 1. Avaliação geral

**O que está bem resolvido** (manter): o Python é um pacote em camadas cujas regras são conferidas por teste
(`test_arquitetura.py`); as entradas em `scripts/` são finas e rodam com `uv run`; há CI, contrato automático
C ↔ Python, um simulador do assembly da PRU, testes em paralelo; cada
`.bin` se descreve sozinho (cabeçalho com CRC, faixa do ADC, integridade da captura); os dados brutos têm um
arquivamento sem perdas conferido bit a bit; a documentação cobre operação, arquitetura, laboratório e relatório.

**Onde estão os riscos e os limites:**

1. **A revisão do firmware de out/2026 ainda não rodou no hardware** (F1). Até lá, o firmware da BeagleBone é o
   antigo, com o salto de ~0,7 amostra a cada bloco. Inclui o cabeçalho v5 (F5), compilado e conferido só no PC.
2. **A taxa máxima (~140 kS/s) cobre só até ~45–70 kHz da banda de supraharmônicos (2–150 kHz).** O gargalo está
   localizado (F2, F3): esperas do CS 100× maiores que o datasheet pede e SPI em ~10 MHz.
3. **Converter uma captura longa para Volts ainda usa o sinal inteiro em float64** (8 bytes por amostra): a análise
   de 10 min (60 milhões de amostras) pede ~1,6 GB de RAM; uma captura de 1 h não caberia (P1).

---

## 2. Prioridade

| Código | Item | Ganho | Esforço | PRU? | Depende de |
|---|---|---|---|---|---|
| **F1** | Validar no hardware a revisão do firmware (grade de tempo, contadores) | Alto: corrige dado de toda captura longa | Baixo (bancada) | sim | — |
| **F2** | Medir até onde as esperas do CS podem cair (`--atraso-cs`) | Alto: teto de ~140 → ~330 kS/s | Baixo (bancada) | não (já configurável) | F1 |
| **S1** | Calibrar a sonda de corrente (T10) com hold-out | Alto para corrente | Médio (bancada) | não | — |
| **P1** | Análise de capturas longas por blocos (sem o sinal inteiro em float64) | Médio: 10 min = 1,6 GB; 1 h não cabe | Médio | não | — |
| **P8** | Potência, impedância e transferência V/I por frequência | Alto para pesquisa de emissão | Médio | não | S3 |
| **F9** | Descartar o transitório de troca de faixa já na PRU (a análise já descarta) | Baixo: dado certo desde a 1ª amostra | Baixo | sim | F1 |
| **F3** | SPI mais rápido (SCLK até 17 MHz) | Alto: rumo a 300–500 kS/s | Médio | sim | F2 |
| **F4** | `SAMPLES_PER_BUFFER` vindo do ARM, não duplicado no `.asm` | Médio: fim de uma sincronia manual | Baixo | sim | F1 |
| **F6** | Gravar o bloco parcial no Ctrl+C e parar a PRU no fim | Médio | Baixo | sim (publicar a posição) | F1 |
| **F7** | Conferência rápida do `calibrar_sonda.sh` mais leve na BeagleBone | Médio | Baixo | não | medir na BBB |
| **S2–S7** | Fase, subamostragem, perfil absoluto, teto de ganho, repetições | Alto para V×I | Médio–Alto | não | S1 |
| **F8** | Endereço do canal no SDO (verificar a ordem dos canais a cada amostra) | Baixo–Médio | Médio | sim | F3 |
| **H1–H2** | Isolador contra o BOM, pontos de teste na próxima PCB | Baixo–Médio | Baixo–Médio | não | — |
| **T2–T3** | Testes de host do C; cobertura da plotagem | Baixo | Baixo | não | — |

---

## 3. Firmware e aquisição

### F1 — Validar no hardware a revisão do firmware

**Por quê.** A revisão de out/2026 corrige dois defeitos de tempo medidos nas capturas reais — +0,697 amostra
(6,97 µs) em **cada** troca de buffer da T7c, e as primeiras amostras de toda captura saindo mais rápido que o pedido
— e acrescenta os contadores de integridade e os cabeçalhos v4 e v5 (versão do firmware e taxa medida pelo ARM).
Tudo foi conferido no simulador (`tests/pru_sim.py`) e o `ler_adc.c` compila no PC com `-Werror`,
mas a latência real de `LBBO`/`SBBO` e a sintaxe do `clpru` só aparecem na BeagleBone.

**Como validar.** `cd firmware && ./setup.sh` (compila e carrega); depois:

1. 10 min a 100 kS/s com um tom estável (como o T7c) → `medir_captura.py` com **continuidade OK** e
   **`trocas de buffer : OK`** (salto nas trocas igual ao dos outros segmentos, na casa de 0,01 µs; antes: 6,96 µs
   nas 57 trocas) e o `ler_adc` terminando com "Integridade: ... tudo certo" e o cabeçalho dizendo `Versão de
   cabeçalho: 5` e `Firmware: ...`. O T7a e o T7b também, com ≥ 3 blocos: uma captura de 1 bloco não tem troca;
2. ≥ 25 s a 40 kS/s (um bloco > 21,5 s, que antes travava o contador) → continuidade OK;
3. 200 kS/s → o `ler_adc` tem de acusar **amostras atrasadas** e a taxa real medida (~140 kS/s);
4. se o `DELTA` do rebase (4 ciclos) estiver errado, aparece como salto de poucos ns a cada 10,7 s: invisível na
   continuidade (< 0,01 amostra), mas dá para ver comparando o tom ao longo de 10 min.

### F2 — Medir até onde as esperas do CS podem cair

**Por quê.** Cada amostra leva ~7 µs na PRU; ~4 µs (57 %) são três esperas do CS (2,0/1,0/1,0 µs) calibradas na
época do problema dos jumpers. O datasheet (SBAS582C, tab. 7.6) pede 30/10/30 ns, e a conversão (≤ 850 ns) já
termina durante os 16 bits de comando (1,6 µs). Só reduzi-las leva o teto a ~330 kS/s.

**Proposta.** O roteiro T7e, método 4 (`ler_adc --atraso-cs`, já implementado): baixar os atrasos por etapas e
comparar ruído, SINAD/ENOB, THD e continuidade com o padrão a 100 kS/s; depois ver o teto a 250 kS/s. O menor
conjunto que não muda nada, com folga, vira o novo padrão (`ATRASO_CS_*_PADRAO` em `memoria_pru.h` e no `.asm` —
`test_contrato_firmware.py` confere que os dois batem).

### F3 — SPI mais rápido

**Por quê.** Os 32 bits de cada quadro levam ~2,9 µs (~20 ciclos por bit de comando, ~16 por bit de dado: SCLK de
~10–12 MHz). O `CMD_BIT` tem NOPs para ficar simétrico ao `DATA_BIT` e um bloco que lê o MISO só para gastar o mesmo
tempo — herança da depuração dos jumpers. O ADS8688 aceita 17 MHz (59 ns por bit), o que daria ~1,9 µs por quadro e
o limite do próprio ADC (500 kS/s, 2 µs de ciclo).

**Proposta.** Depois de F2: reduzir os NOPs medindo, com a mesma bateria de F2, e com o osciloscópio no SCLK/SDO
(tSU_DOCK ≥ 25 ns antes da borda de descida). Cobrir até 150 kHz com 1 canal pede ≥ 300 kS/s.

### F4 — `SAMPLES_PER_BUFFER` vindo do ARM

**Por quê.** O tamanho do bloco (1.048.576) está em `memoria_pru.h` e, de novo, num `LDI r21` do `.asm`: mudar um
lado sem o outro desalinha a troca de buffer sem nenhum erro.

**Proposta.** Um campo `amostras_por_buffer` em `shared_control`, escrito pelo `ler_adc` e lido pela PRU uma vez
(como os atrasos de CS). Remove a duplicação — melhor do que gerar o `.asm` no build.

### F6 — Ctrl+C sem perder o bloco em andamento; parar a PRU no fim

**Por quê.** Numa captura indefinida, o Ctrl+C descarta o bloco que a PRU estava enchendo (até ~10 s a 100 kS/s).
E a PRU continua amostrando para a DDR depois que o `ler_adc` sai, até a próxima captura.

**Proposta.** A PRU publica a posição de escrita (`r15`) uma vez por amostra, na folga (custo de 1 `SBBO`); no
Ctrl+C, o `ler_adc` grava as amostras já escritas do bloco atual (múltiplo do nº de canais) e acerta o cabeçalho;
no fim, escreve `stop` no remoteproc.

### F7 — Conferência rápida do `calibrar_sonda.sh` mais leve

**Por quê.** A cada captura, o script analisa 262.144 amostras em `od | awk`: 0,7 s no PC; numa Cortex-A8 deve
passar de vários segundos por ponto (não medido). É também o que domina o tempo de `tests/test_calibrar_sonda.py`.

**Proposta.** Medir na BeagleBone (`time` numa captura). Se incomodar: analisar 65.536 amostras (sobram > 30 ciclos
do tom mais baixo do plano) ou mover a análise para um pequeno programa em C compilado junto com o `ler_adc`.

### F8 — Conferir a ordem dos canais a cada amostra

**Por quê.** O bug histórico de "canal trocado" passou meses sem ser visto. O ADS8688 pode anexar o endereço do canal
ao dado (registrador 03h, `SDO_FORMAT`): 3 bits a mais por quadro.

**Proposta.** Um modo de diagnóstico (`ler_adc --conferir-canais`) que liga esse formato, lê os 3 bits extras e
conta quadros fora da sequência esperada (um quarto contador de integridade). Custa ~3 clocks por quadro: deixar
desligado por padrão, ou ligar depois de F3.

### F9 — Descartar o transitório depois de trocar a faixa

**Por quê.** Nas capturas de 19/10 (roteiro, T0 e T1), toda vez que a faixa de um canal muda em relação à captura
anterior, as ~6 primeiras amostras desse canal (60 µs a 100 kS/s) decaem de até ~1 V até o valor certo. É o ADC se
acomodando à nova escala, com constante de tempo próxima à do passa-baixa interno. Sem troca de faixa, não há
transitório. Hoje nada é descartado, e o ruído medido sem `--inicio 100` sai 7 a 8 vezes maior.

**Já feito na análise (21/10):** o `medir_captura.py` pula os primeiros 200 µs de cada canal (`--inicio 0` mede
tudo) e ele e o `adc_tool.py` avisam quando o começo de um trecho foge do resto (`detectar_transitorio_inicial`).
O transitório é um tempo (< 1 LSB em ~80 µs com 1 e com 2 canais), não um nº de amostras.

**Proposta, o que falta.** Na PRU: depois de escrever os `RANGE_SELn` e o `AUTO_RST`, fazer ~16 quadros descartados
(≥ 100 µs) antes de zerar o contador de ciclos e começar a gravar, reaproveitando o corpo da transação (a IMEM está
em 91,7 %). O campo `primeira_amostra_descartada` do cabeçalho já existe para registrar isso. Ganho: o `.bin` sai
certo desde a 1ª amostra também para quem o lê fora destas ferramentas.

**Como saber que deu certo.** Repetir a sequência de faixas do T0 (20.48 → 10.24 → 5.12) e conferir que as
primeiras amostras de cada captura já estão dentro do ruído (±3 LSB do valor final).

---

## 4. Software Python

### P1 — Análise de capturas longas por blocos

**Por quê.** O gráfico desenha a envoltória mín/máx quando pedido (`--simplificar`: o da captura de 10 min cai de
26 s e 4,3 GB para 6 s e 1,6 GB), mas a análise ainda converte o trecho inteiro para Volts em float64 antes de tudo: 60 milhões de
amostras são ~0,5 GB por cópia, e o filtro e a correção de sonda fazem cópias. Uma captura de 1 h a 100 kS/s não
caberia em 16 GB.

**Proposta.** O Welch, o espectrograma e as bandas IEC já processam por segmentos: levar a conversão a Volts (e o
filtro, com `sosfilt` + estado entre blocos, ou `sosfiltfilt` por blocos sobrepostos) para dentro do laço, lendo do
memmap. A FFT única da `--fft` continua precisando do trecho inteiro (limitar a `--fft N` ciclos em capturas longas).

### P8 — Potência, impedância e transferência V/I por frequência

**Por quê.** Com tensão e corrente na mesma captura, a pesquisa de emissão quer a potência por componente, a
impedância vista pela carga e a direção da emissão, por frequência. Hoje a correção de sonda é só de magnitude (S3),
e os canais são amostrados com 1/taxa de diferença.

**Proposta.** Depois do S3 (ganho complexo no perfil): compensar o atraso de multiplexação (fase 2π·f·Δt, Δt
conhecido do cabeçalho) e a fase de cada sonda, e calcular, por harmônico e por banda, P, Q, a impedância V/I e a
coerência entre os canais (que diz se a relação é confiável naquela frequência). Antes disso, qualquer número de
potência acima de poucos harmônicos seria enganoso.

---

## 5. Testes e CI

### T2 — Testes de host do C

**Por quê.** As funções de parsing do `ler_adc.c` (`analisar_lista_canais`, `--faixa-adc`, `--atraso-cs`) são
puras, mas `static` dentro do arquivo.

**Proposta.** Movê-las para `parsing.c/.h` e um executável de teste compilado pela CI (lista vazia, canal repetido,
fora de 0–7, valores-limite).

### T3 — Cobertura onde está baixa

`plotagem.py` (49 %) e `escrita_perfil.py` (65 %) — `pytest --cov=scripts/supraharmonicos`. Ganho baixo: o que
importa (contas) já está coberto; vale cobrir a decimação de P1 quando ela existir.

---

## 6. Repositório, dados e documentação

### R5 — Diagrama ARM ↔ PRU ↔ ADC e lições aprendidas

Um diagrama de sequência (configuração, laço, troca de buffer com os contadores, rebase do contador) em
`software-architecture.md` ou num `docs/firmware.md`, e um recorte por tema (tempo do SPI, integridade de sinal,
formato de arquivo) das lições hoje espalhadas em comentários e em `report-notes.md`. Ganho de portfólio.

---

## 7. Hardware

### H1 — Confirmar o isolador contra o esquemático/BOM

O contexto cita o ADuM3150 (isolador digital, com distorção de largura de pulso especificada) "a confirmar". Fechar
isso e medir SCLK/MOSI/MISO na saída do isolador. Com F2/F3 (SPI mais rápido) a margem de tempo do isolador passa a
importar.

### H2 — Pontos de teste na próxima revisão da PCB

SCLK/CS/MOSI/MISO dos dois lados da barreira de isolamento e um GPIO livre da PRU exposto (marcar a primeira amostra
gravada — útil para medir a fase, S2). Desacoplamento de baixo ESR junto ao ADC e trilhas de SPI curtas.

---

## 8. Fluxo de sondas

Propostas da [`probe-profile-audit.md`](probe-profile-audit.md) (seção 4) e do T3. A primeira calibração
real (cadeia de tensão, `scripts/sondas/cadeia_tensao.json`) já foi feita.

| Código | Proposta | Para quê | Esforço | Decisão de projeto? |
|---|---|---|---|---|
| **S1** | Calibrar a sonda de corrente (T10) e validar por frequências retidas (*hold-out*) | Exatidão de um perfil real; detectar ressonância perdida | Médio (bancada) | Não |
| **S2** | Medir a **fase** da cadeia (osciloscópio na entrada e no CS do ADC) | Validar a função de transferência ajustada só pela magnitude; preparar S3 | Médio | Não |
| **S3** | Ganho **complexo** no perfil | Análise V×I, potência, direção de emissão | Médio–Alto | Sim: muda o formato do perfil |
| **S4** | **Subamostragem** para medir \|H\| acima da Nyquist | Estender a curva à banda de supraharmônicos sem subir a taxa; separar f0 de Q (correlação −0,87 hoje) | Médio | Não |
| **S5** | Perfil **absoluto** (V/A) | Eliminar o risco de usar um `--ganho` diferente do da calibração | Médio | Sim: muda o `--ganho` |
| **S6** | Teto de ganho da correção | Não "corrigir" ruído onde a sonda atenua muito (o filtro do ADC já tira 12,5 dB a 45 kHz) | Baixo | Sim: altera o resultado |
| **S7** | Repetições no T3 (`--repeticoes 3`) | Incerteza por ponto; ajuste ponderado e χ² no `gerar_figuras.py` | Baixo (bancada) | Não |

---

## Regras para quem for implementar

* Mudança no `spi_core.asm` só está pronta depois de montada com `clpru` e validada no hardware; o simulador
  (`tests/test_pru_asm.py`) confere a lógica e a grade de tempo em ciclos, não a latência real.
* O formato das **amostras** do `.bin` não muda (2 bytes por amostra, intercaladas); o cabeçalho pode crescer por
  versão, e o Python continua lendo todas as anteriores.
* Nada que rode por amostra na PRU deve ficar entre a espera e a descida do CS: o que precisa rodar por amostra vai
  na folga **antes** da espera (não muda o instante da amostra); o resto, na troca de buffer.
