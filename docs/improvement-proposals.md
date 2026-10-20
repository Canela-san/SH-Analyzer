# SH-Analyzer — Propostas de melhoria

Lista **só do que ainda está por fazer**, com o motivo medido, a proposta e como saber que deu certo. O que já foi
feito sai daqui: a história fica no `git log` e, para o relatório, em [`report-notes.md`](report-notes.md).

Cada item tem um código (F = firmware/aquisição, P = Python, T = testes/CI, R = repositório/dados/documentação,
H = hardware, S = sondas) e as colunas: **ganho** (o que melhora), **esforço** e se **toca a PRU** — mudança no
assembly só conta como feita depois de montada com `clpru` e validada no hardware.

Revisado em 20/10/2026, depois da revisão do firmware (salto de 7 µs na troca de buffer corrigido, contadores de
integridade, cabeçalho v4), da revisão dos testes, do novo `compactar_amostras.py` e da análise das capturas de
bancada de 19/10 (F9 e P6 vieram delas). Depois, no mesmo dia, saíram daqui R1 a R4 e T1: dados fora do
repositório, pastas e documentos com nomes em inglês sem espaço nem acento, contagem de testes num lugar só,
backups do Altium fora do git, `.gitattributes`/`.editorconfig`/`CITATION.cff` e a CI compilando o C e passando o
`shellcheck`.

---

## 1. Avaliação geral

**O que está bem resolvido** (manter): o Python é um pacote em camadas cujas regras são conferidas por teste
(`test_arquitetura.py`); as entradas em `scripts/` são finas e rodam com `uv run`; há CI, contrato automático
C ↔ Python, um simulador do assembly da PRU, testes em paralelo; cada
`.bin` se descreve sozinho (cabeçalho com CRC, faixa do ADC, integridade da captura); os dados brutos têm um
arquivamento sem perdas conferido bit a bit; a documentação cobre operação, arquitetura, laboratório e relatório.

**Onde estão os riscos e os limites:**

1. **A revisão do firmware de out/2026 ainda não rodou no hardware** (F1). Até lá, o firmware da BeagleBone é o
   antigo, com o salto de ~0,7 amostra a cada bloco.
2. **A taxa máxima (~140 kS/s) cobre só até ~45–70 kHz da banda de supraharmônicos (2–150 kHz).** O gargalo está
   localizado (F2, F3): esperas do CS 100× maiores que o datasheet pede e SPI em ~10 MHz.
3. **O histórico do git ainda carrega ~45 MB de dados antigos** (CSVs e `.bin` apagados da árvore há meses, a
   lixeira de uma pasta montada por sshfs, backups do Altium): o `.git` tem ~90 MB, para uma árvore de ~45 MB (R2).
4. **Abrir uma captura longa é lento e caro** (P1, P2): o gráfico da captura de 10 min leva 26 s e 4,3 GB de RAM,
   e só importar o `adc_tool` leva ~2–3 s.

---

## 2. Prioridade

| Código | Item | Ganho | Esforço | PRU? | Depende de |
|---|---|---|---|---|---|
| **F1** | Validar no hardware a revisão do firmware (grade de tempo, contadores) | Alto: corrige dado de toda captura longa | Baixo (bancada) | sim | — |
| **F2** | Medir até onde as esperas do CS podem cair (`--atraso-cs`) | Alto: teto de ~140 → ~330 kS/s | Baixo (bancada) | não (já configurável) | F1 |
| **S1** | Calibrar a sonda de corrente (T10) com hold-out | Alto para corrente | Médio (bancada) | não | — |
| **P1** | Gráfico com decimação por envoltória (mín/máx) | Alto: 10 min hoje = 26 s e 4,3 GB de RAM | Baixo | não | — |
| **P6** | Continuidade medida em tempo, com atenção às trocas de buffer | Médio: o salto de 7 µs passou como "OK" com 2 canais | Baixo | não | — |
| **F9** | Descartar o transitório depois de trocar a faixa do ADC | Médio: dado certo desde a 1ª amostra | Baixo | sim (a) / não (b) | F1 |
| **F3** | SPI mais rápido (SCLK até 17 MHz) | Alto: rumo a 300–500 kS/s | Médio | sim | F2 |
| **F4** | `SAMPLES_PER_BUFFER` vindo do ARM, não duplicado no `.asm` | Médio: fim de uma sincronia manual | Baixo | sim | F1 |
| **F5** | Hash do commit no cabeçalho | Médio: saber qual firmware gerou cada captura | Baixo | não | — |
| **P2** | Importações sob demanda (scipy/matplotlib) | Médio: CLI ~2 s mais rápida | Baixo | não | — |
| **R2** | Limpar o histórico do git (dados antigos) | Médio: `.git` de ~90 para ~45 MB | Baixo, mas reescreve o histórico | não | decisão do dono |
| **F6** | Gravar o bloco parcial no Ctrl+C e parar a PRU no fim | Médio | Baixo | sim (publicar a posição) | F1 |
| **F7** | Conferência rápida do `calibrar_sonda.sh` mais leve na BeagleBone | Médio | Baixo | não | medir na BBB |
| **P3–P5** | Correção de sonda fora de `modos`, taxa real da PRU (confirmada no T4), atributo HDF5 | Baixo–Médio | Baixo | não | — |
| **S2–S6** | Fase, subamostragem, perfil absoluto, teto de ganho | Alto para V×I | Médio–Alto | não | S1 |
| **F8** | Endereço do canal no SDO (verificar a ordem dos canais a cada amostra) | Baixo–Médio | Médio | sim | F3 |
| **H1–H2** | Isolador contra o BOM, pontos de teste na próxima PCB | Baixo–Médio | Baixo–Médio | não | — |
| **T2–T3** | Testes de host do C; cobertura da plotagem | Baixo | Baixo | não | — |

---

## 3. Firmware e aquisição

### F1 — Validar no hardware a revisão do firmware

**Por quê.** A revisão de out/2026 corrige dois defeitos de tempo medidos nas capturas reais — +0,697 amostra
(6,97 µs) em **cada** troca de buffer da T7c, e as primeiras amostras de toda captura saindo mais rápido que o pedido
— e acrescenta os contadores de integridade e o cabeçalho v4. Tudo foi conferido no simulador (`tests/pru_sim.py`),
mas a latência real de `LBBO`/`SBBO` e a sintaxe do `clpru` só aparecem na BeagleBone.

**Como validar.** `cd firmware && ./setup.sh` (compila e carrega); depois:

1. 10 min a 100 kS/s com um tom estável (como o T7c) → `medir_captura.py` com **continuidade OK** e maior salto
   na casa dos milésimos de amostra (antes: 0,697 nas 57 trocas) e o `ler_adc` terminando com "Integridade: ...
   tudo certo". O T7a e o T7b também, mas com ≥ 3 blocos: uma captura de 1 bloco não tem troca de buffer, e com
   2 canais o salto antigo valia só 0,35 amostra, abaixo do limite de 0,5 (P6);
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

### F5 — Versão do firmware no cabeçalho

**Por quê.** Com F1–F3 o firmware vai mudar entre campanhas, e hoje um `.bin` não diz qual build o gerou.

**Proposta.** O `Makefile` passa `git describe --always --dirty` ao `gcc` (`-DVERSAO_FIRMWARE=...`); o `ler_adc`
imprime e grava num campo novo (cabeçalho v5, sobram 320 bytes de padding). Marcar com `git tag` o commit usado em
cada campanha de bancada.

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

**Proposta.** (a) Na PRU: depois de escrever os `RANGE_SELn` e o `AUTO_RST`, fazer ~16 quadros descartados (≥ 100 µs)
antes de zerar o contador de ciclos e começar a gravar, reaproveitando o corpo da transação (a IMEM está em 91,7 %).
O campo `primeira_amostra_descartada` do cabeçalho já existe para registrar isso. (b) Se a PRU não for mexida: o
`medir_captura.py` e o `adc_tool.py` passam a pular, por padrão, as primeiras 16 amostras de cada canal (com
`--inicio 0` para ver tudo) e avisam quando o começo destoa do resto.

**Como saber que deu certo.** Repetir a sequência de faixas do T0 (20.48 → 10.24 → 5.12) e conferir que as
primeiras amostras de cada captura já estão dentro do ruído (±3 LSB do valor final).

---

## 4. Software Python

### P1 — Gráfico com decimação por envoltória

**Por quê.** O `adc_tool` desenha cada amostra. Medido em 20/10/2026: `adc_tool.py T7c_10min.bin --welch -o g.png`
(60,8 milhões de amostras) leva **25,7 s e 4,3 GB de RAM**; uma captura de 1 h não caberia na memória. Numa captura
curta, só traçar 200 mil pontos já custa 1,2 s.

**Proposta.** Em `plotagem.py`, acima de ~4× a largura do gráfico em pixels, traçar o mínimo e o máximo de cada
fatia (o desenho é o mesmo a olho, e nenhum pico some); espectros já são curtos. A conversão para Volts em float64
do sinal inteiro (8 bytes por amostra) também pode ir por blocos, como já faz a exportação HDF5. Teste: a envoltória
contém todos os extremos do sinal; RAM e tempo medidos de novo na T7c.

### P2 — Importações sob demanda

**Por quê.** `import scipy.signal` custa ~2 s (a SciPy recente puxa `scipy.stats`); com o matplotlib, o
`adc_tool --help` e a conversão `.bin`→`.csv` pagam ~2–3 s sem usar nada disso.

**Proposta.** Importar `scipy.signal`/`scipy.interpolate` dentro das funções que os usam (como já é feito com o
matplotlib e o h5py) e medir o `--help` antes/depois. `test_arquitetura.py` pode passar a exigir isso.

### P3 — Correção de sonda fora de `modos`

**Por quê.** O `medir_captura` importa `modos` (os modos do `adc_tool`) só para usar `aplicar_correcao_sondas`;
com isso arrasta o módulo de HDF5 e a lógica de plotagem para o seu fecho de importações.

**Proposta.** Mover `aplicar_correcao_sondas` para um módulo de camada 2/3 (`correcao.py`) usado pelos dois.

### P4 — Taxa real da PRU por padrão

**Por quê.** A PRU gera `200 MHz ÷ ticks` (inteiro): 102.400 Hz pedidos viram 102.406,55 Hz (+64 ppm); todas as
frequências medidas se deslocam igual. Só o `medir_captura --fs-pru` usa a taxa real.

**Proposta.** O T4 de 19/10 confirmou a fórmula a 0,02 ppm (102,4 kS/s a −64,03 ppm e 110 kS/s a −99,98 ppm das
taxas exatas). Usar `pru_clock_hz ÷ sample_period_ticks` por padrão no `adc_tool` e no
gerador de perfil, com aviso quando difere da pedida. Recomendar taxas exatas (100, 200, 250 kHz) no guia.

### P5 — Atributos HDF5 da correção e da integridade

**Por quê.** Quem abre o `.h5` fora do `adc_tool` não sabe se a tensão exportada foi corrigida por um perfil de sonda.

**Proposta.** Atributo `correcao_sonda_aplicada` (perfil e data) por canal. (Os contadores de integridade do
cabeçalho v4 já vão para o HDF5.)

### P6 — Continuidade medida em tempo

**Por quê.** O `medir_captura.py` só acusa salto de fase acima de 0,5 amostra **do canal**. O defeito de 6,97 µs do
firmware antigo vale 0,7 amostra com 1 canal a 100 kS/s, mas 0,35 com 2 canais e 0,09 com 8: nas capturas de 19/10
com 2 canais (T6) ele saiu como "OK". Uma captura saudável dá 0,001 a 0,004 amostra.

**Proposta.** Informar o salto também em µs e na taxa total (`salto_max_us` no CSV). Comparar o salto de cada troca
de buffer (amostra `SAMPLES_PER_BUFFER ÷ nº de canais` e múltiplos) com o dos outros segmentos, e acusar quando as
trocas destoam (por exemplo, acima de 10 vezes a mediana ou de 0,05 µs). Manter o limite de 0,5 amostra para amostra
perdida ou duplicada.

**Como saber que deu certo.** Nas capturas de 19/10, `T6a_10k_ch1.bin` e `T6b_1k.bin` passam a acusar o salto na
troca de buffer, e o `T7a_fs_100000.bin` (1 bloco) continua OK.

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

### R2 — Limpar o histórico do git

**Por quê.** A árvore atual tem ~45 MB, mas o `.git` tem ~90 MB: o resto são arquivos que já saíram do projeto e
continuam em cada clone — `scripts/amostras_100kHz.csv` (47 MB), `amostras_102kHz.csv` (35 MB), outros CSVs e
`.bin` de captura, a lixeira (`.Trash-1000/`) da antiga pasta `BeagleBone/` e os backups do Altium
(`hardware/DAQ_Module/History/`).

**Proposta.** `git filter-repo --invert-paths` com esses caminhos, `git gc --aggressive` e um *force push* da
`main`. Reescreve **todos** os hashes de commit: links para commits antigos e os PRs fechados do GitHub passam a
apontar para commits que não existem mais na `main`, e todo clone existente precisa ser refeito. Só vale se o
tamanho do clone incomodar; para imagens novas, prefira PNG/SVG pequenos (ou Git LFS, se o volume crescer).

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
| **S8** | Aviso de perfil antigo (`data_calibracao`) | Lembrar de recalibrar | Baixo | Não |

---

## Regras para quem for implementar

* Mudança no `spi_core.asm` só está pronta depois de montada com `clpru` e validada no hardware; o simulador
  (`tests/test_pru_asm.py`) confere a lógica e a grade de tempo em ciclos, não a latência real.
* O formato das **amostras** do `.bin` não muda (2 bytes por amostra, intercaladas); o cabeçalho pode crescer por
  versão, e o Python continua lendo todas as anteriores.
* Nada que rode por amostra na PRU deve ficar entre a espera e a descida do CS: o que precisa rodar por amostra vai
  na folga **antes** da espera (não muda o instante da amostra); o resto, na troca de buffer.
