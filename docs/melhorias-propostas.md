# SH-Analyzer — Sugestões de Melhoria

> Documento de revisão técnica cobrindo (1) o que pode ser feito para suportar taxas de
> amostragem maiores sem corromper dados, considerando firmware e hardware, e (2)
> reorganização/profissionalização do repositório para uso em portfólio. Cada item indica
> **Impacto** (no desempenho/robustez ou na qualidade do projeto) e **Esforço** estimado,
> além de sinalizar quando a mudança toca o Assembly da PRU — que, pelo princípio já
> adotado no projeto, só deve ser considerada "pronta" depois de compilada com `clpru` e
> validada em hardware real.
>
> **Atualização de 2026-10 (antes do merge da refatoração do código Python):** os status
> abaixo foram revisados contra o repositório atual. Mudanças desde a revisão anterior: o
> código Python virou o pacote `scripts/supraharmonicos/` (ver `docs/arquitetura_software.md`),
> ganhou testes automáticos (226) e integração contínua, e o cabeçalho do `.bin` passou à
> versão 2 (grandeza e sonda por canal) com as ferramentas de calibração de sondas. Os itens
> que dependem de medição em hardware continuam abertos.
>
> **Nota da revisão anterior:** ela excluía `scripts/adc_tool.py`
> do escopo, a pedido; esta revisão é uma reanálise completa do projeto e passa a cobrir
> o script também. Boa parte do que era só proposta na revisão anterior já foi
> implementada (em alguns casos, de forma diferente e melhor do que o que havia sido
> sugerido) — cada item abaixo traz seu status atualizado. Um resumo rápido:

| Status | Itens |
|---|---|
| ✅ **Concluído** | 1.5 (modo automático AUTO_RST, e o comentário obsoleto de `spi_core.asm` corrigido), 2.9 (`set_date.sh` sem senha no arquivo), 2.10 (`calibrar_sonda.sh` reescrito: Nyquist efetiva, conferência de cada captura, novos modos e testes), 1.8 (parcial: checagem de `fwrite()` + `--blocos`/`--duracao`), 1.9 (parte Python: mitigado por `tests/test_contrato_firmware.py`), 1.10 (parcial: causa raiz da saturação — jumpers), 2.1 (parcial: `backup pre-assembly/` removido), 2.2 (`.gitignore`), 2.3 (metadados — via cabeçalho embutido, não sidecar), 2.5 (parcial: lado Python — suíte `pytest` de 651 testes, `ruff` e CI no GitHub Actions), 2.7 (parcial: README, guia de uso, arquitetura do software e contexto), 2.8 (arquivo já se chama `adc_tool.py`) |
| 🆕 **Novo** | Melhorias do fluxo de perfil de sonda vindas da auditoria e do T3 (2.11: fase, subamostragem acima da Nyquist, repetições); achados do datasheet e do código a confirmar em bancada: filtro de 15 kHz do ADS8688 (**medido no T3: −3 dB em 17,3 kHz na cadeia de tensão**) e taxa de amostragem real (2.12); `medir_captura.py` e `docs/roteiro_laboratorio.md` (já entregues); faixa de entrada do ADC por canal, `--faixa-adc` (2.13: implementada, falta bancada) |
| 🔄 **Ainda aberto, com nota atualizada** | 1.1–1.4 (o "piso" antigo de ~48 kHz parece estar desatualizado — ver nota abaixo), 1.6, 1.7, 1.9 (revisado), 2.4, 2.5 (parte C/CI), 2.6, 2.7 (`licoes-aprendidas.md`), 2.11, 2.12 |

---

## Parte 1 — Taxa de amostragem (firmware + hardware)

### 1.1 O teto real é o ADS8688, não a meta do projeto

O ADS8688 (SBAS582C) tem **500 kSPS de throughput agregado** somando todos os canais —
esse é o teto físico do chip, independentemente de quão rápido o barramento SPI seja
capaz de rodar. Vale registrar esse número explicitamente na documentação do projeto
(README ou `docs/contexto_projeto.md`, seção 2.2 — já feito), porque ele muda a forma de
ler as metas de desempenho: com captura de 1 canal, 500 kSPS é o limite superior
absoluto; com N canais intercalados, o limite por canal cai para 500 kSPS / N.

**Atualização desta revisão:** a versão anterior deste item citava um comentário em
`ler_adc.c` (`// Bem mais baixa - a transação agora leva ~21 us`) como evidência de que a
implementação de bit-banging rodava bem abaixo desse teto (~21 us/transação ⇒ pouco menos
de 50 kHz de taxa real possível). Esse comentário **não existe mais** na versão atual de
`ler_adc.c` — provavelmente foi removido durante a reescrita para o modo automático
(AUTO_RST, ver item 1.5). Mais importante: a captura validada em hardware com 5 canais
(`docs/contexto_projeto.md`, seção 6.1) rodou a **102,4 kHz totais** — acima do "piso" de
~48 kHz que aquele comentário antigo sugeria. Ou seja, o número antigo já está
desatualizado (é esperado: o modo automático eliminou a leitura da tabela de comandos por
canal da RAM compartilhada a cada amostra, reduzindo o custo por transação). **Não dá para
reafirmar um novo número sem medir de novo** — mas dá para afirmar que o piso real hoje é
mais alto do que o documento anterior sugeria, e que a medição do item 1.2 é o caminho
certo para descobrir o valor atual, não uma leitura antiga de comentário de código.

**Impacto:** referência / não é uma ação isolada, mas orienta a priorização de tudo
abaixo.

---

### 1.2 Medir antes de otimizar: isolar onde o tempo por transação está indo

Antes de mexer em NOPs e loops de atraso, vale confirmar empiricamente onde o tempo por
transação está sendo gasto, em vez de otimizar às cegas — ainda mais importante agora que
o item 1.1 mostrou que a última estimativa registrada em código já não é confiável. Uma
contagem rápida dos ciclos "óbvios" (16 `CMD_BIT` + 16 `DATA_BIT`, mais os três laços de
atraso do CS — `delay_cs_setup`, `delay_cs_hold`, `delay_cs_high_minimo`) fica na casa de
5-7 us em 200 MHz. Essa contagem estática **continua válida no código atual**: a
reescrita para o modo automático preservou os macros `CMD_BIT`/`DATA_BIT` byte a byte (o
próprio cabeçalho de `spi_core.asm` documenta isso explicitamente — só o valor enviado
como "comando" mudou, de um código de canal para `NO_OP` fixo), então o tempo de bit a bit
do frame SPI não mudou com a migração. 5-7 us/transação implicaria um piso de ~140-200 kHz
— consistente com o fato de 102,4 kHz já rodar sem problema relatado, e sugerindo que
ainda há margem real acima disso, mas só uma medição confirma.

**Sugestão concreta:** usar um pino de PRU sobrando (ou reaproveitar um dos já
configurados em `setup.sh`) como "sonda" — setar/limpar esse pino ao redor de cada fase
da transação (CS setup, clock dos 32 bits, escrita na DDR, espera de `wait_time`) e medir
com o próprio osciloscópio que já está sendo usado para depurar timing. Isso transforma
"onde está o tempo" de suposição em dado medido, e evita otimizar a parte errada — e
resolve de vez a divergência entre a contagem estática (~5-7 us) e a antiga cifra empírica
(~21 us) que não sobreviveu à reescrita do código-fonte.

**Atualização (simulador, não é medição):** `tests/pru_sim.py` executa o `spi_core.asm` de verdade
num modelo de 1 instrução por ciclo e conta os ciclos do laço principal: **1.379 ciclos por quadro
(6,9 µs, no máximo ~145 kS/s)**, dos quais **800 (58%) são os três laços de espera do CS** (200 + 100
+ 100 iterações de 2 instruções). Os outros 579 ciclos são os 32 bits do quadro, a gravação na DDR e o controle do laço. Isso é compatível com
os ~130 kS/s observados na bancada e **aponta o gargalo**, mas é só uma contagem: `LBBO`/`SBBO` custam
mais que 1 ciclo na PRU real e o modelo ignora o acesso à DDR. A medição com pino e osciloscópio
continua sendo a que vale; o roteiro (T7e) a usa para confirmar.

**Impacto:** Alto (orienta todo o resto, e agora também resolve uma divergência real entre
documentação e código). **Esforço:** Baixo. **Toca PRU asm:** sim (instrumentação
temporária, não precisa ir para produção).

---

### 1.3 Nenhuma validação de que a frequência pedida é alcançável

`ler_adc.c` valida `frequencia_desejada` apenas contra o limite de `500000 Hz` (teto do
próprio ADC), mas não contra o piso real da implementação atual. Se alguém pedir uma
frequência acima do que o hardware consegue sustentar, `sample_period_ticks` vai ser
calculado para um período menor do que o tempo mínimo real de uma transação — a PRU vai
simplesmente ficar para trás e amostrar no ritmo máximo que conseguir, **sem nenhum
aviso**. O arquivo `.bin` resultante ficaria com a frequência efetiva real diferente da
frequência nominal registrada no cabeçalho (`frequencia_hz`, seção 4.2 do contexto do
projeto) — um jeito silencioso de corromper a interpretação dos dados, mesmo que os bytes
em si estejam "corretos".

**Sugestão:** depois de medir o tempo real por transação (item 1.2, com o número
atualizado — ver item 1.1), definir uma constante `FREQUENCIA_MAXIMA_REAL_HZ` documentada
em `ler_adc.c` (ou em `memoria_pru.h`, já que é compartilhada), e fazer `ler_adc` recusar
(ou pelo menos avisar bem alto em stderr) qualquer `frequencia_desejada` acima desse
valor.

**Impacto:** Alto. **Esforço:** Baixo. **Toca PRU asm:** não. **Status:** ainda em aberto
— depende da medição do item 1.2 para ter um número confiável a validar contra.

---

### 1.4 Revisar os atrasos fixos com base no datasheet, não só empiricamente

Os laços `delay_cs_setup` (200 ciclos ≈ 1 us), `delay_cs_hold` (100 ciclos ≈ 0,5 us) e
`delay_cs_high_minimo` (100 ciclos ≈ 0,5 us), assim como as 6 NOPs de "acomodação
máxima" dentro de `CMD_BIT`/`DATA_BIT`, parecem ter sido escolhidos empiricamente durante
a validação em hardware (o que é uma abordagem legítima e já documentada no cabeçalho
do arquivo). Vale a pena, numa próxima iteração, comparar esses valores com os
parâmetros de timing do datasheet do ADS8688 (tempo de setup de CS antes do SCLK, tempo
de hold, tempo mínimo de CS alto entre conversões, tempo de acomodação do
sample-and-hold) — é bem provável que haja margem para reduzir alguns desses laços sem
sair da especificação, principalmente porque o ADS8688 suporta SCLK de dezenas de MHz e
os atrasos atuais foram dimensionados com folga de segurança para fechar o bug de
saturação original (item 1.10 — já resolvido pela causa raiz elétrica, jumpers longos),
não necessariamente no valor mínimo válido.

**Evidência do simulador (item 1.2):** os três laços somam 800 dos 1.379 ciclos do quadro, então reduzi-los
é a alavanca óbvia: cortando, por exemplo, setup + hold + CS alto de 400 para 100 iterações, o quadro cairia
a ~779 ciclos (3,9 µs, ~255 kS/s). **Não faça isso sem ler os mínimos de tempo do datasheet e sem osciloscópio**:
os valores atuais fecharam o bug de saturação (1.10) e o modelo não diz se o ADC ainda converte certo.

**Sugestão de processo:** documentar ao lado de cada `LDI r1, N` a que parâmetro do
datasheet ele corresponde (nome do parâmetro + valor mínimo exigido + margem aplicada),
para que ajustes futuros sejam sistemáticos e não tentativa-e-erro.

**Impacto:** Alto (efeito direto na taxa máxima — continua sendo, junto com 1.2, a maior
alavanca de ganho identificada). **Esforço:** Médio (requer datasheet + recompilar com
`clpru` + validar em hardware a cada ajuste, um de cada vez). **Toca PRU asm:** sim — só
deve ser considerado pronto após compilar e validar em hardware. **Status:** ainda em
aberto.

---

### 1.5 Modo Auto/Auto_RST do ADS8688 ✅ CONCLUÍDO

> Este item era, na revisão anterior, uma proposta de mudança de protocolo classificada
> como experimento arriscado, a ser tratado em branch separada. **Já foi implementado e
> validado em hardware** — mantido aqui, em tom retrospectivo, como registro do que era
> esperado vs. o que de fato aconteceu.

O ADS8688 tem, além do modo manual (um comando de seleção de canal enviado a cada frame),
um **modo automático de varredura** (seção "Auto Modes" / `AUTO_RST` do SBAS582C): o host
programa uma vez quais canais fazem parte da sequência, e o próprio ADC avança pela
sequência a cada frame sem precisar receber um novo comando de canal a cada transação.

**O que de fato aconteceu** (ver `docs/contexto_projeto.md`, seção 3.2, e
`docs/notas_relatorio.md`, Marco 6, para o relato completo):

- `spi_core.asm`, `memoria_pru.h`, `pru_main.c` e `ler_adc.c` foram reescritos para o modo
  automático. O modo manual multi-canal (tabela `comandos_canais[]`, round-robin em
  software) foi **removido por completo**, não mantido como opção — conforme pedido
  explícito registrado no cabeçalho de `spi_core.asm`.
- A struct `shared_control` caiu de 64 para 32 bytes (o campo `auto_seq_mask`, uma única
  máscara de bits, substituiu `num_canais` + `comandos_canais[8]`).
- Retrocompatibilidade de formato de arquivo para 1 canal foi preservada — o layout do
  `.bin` não mudou.
- **Um bug real foi encontrado e corrigido em hardware**, não só na teoria do datasheet:
  a escrita do registrador `AUTO_SEQ_EN` usa 24 ciclos de SCLK (16 + 8), não 32 como uma
  transação normal — usar 32 corrompia a máscara de canais recém-escrita. Confirmado
  contra o driver oficial do ADS8688 no kernel Linux e contra o fórum de suporte da TI.
- Validado em hardware com 1 canal e com 5 canais simultâneos (0–4) a 102,4 kHz totais —
  canais conectados mostram a onda de 60 Hz esperada, desconectados mostram só ruído.

**Follow-up de higiene (✅ resolvido):** o cabeçalho de comentários no topo de `spi_core.asm`
trazia o aviso "⚠️ AINDA NÃO VALIDADO EM HARDWARE... tratar como experimento isolado nesta
branch... antes de fazer merge na main" e referenciava um arquivo de contexto antigo
(`Contexto do Projeto-3.md`), contradizendo o resto do próprio arquivo (que documenta o bug de
24 vs. 32 ciclos como "observado em hardware"). O comentário agora diz que o AUTO_RST está
validado em hardware (1 e 5 canais a 102,4 kHz) e que falta a validação quantitativa de
exatidão. Só comentários mudaram: as linhas que não são comentário ficaram idênticas, então não
há o que recompilar nem revalidar na PRU (o `setup.sh` recompila de qualquer forma).

**Impacto:** Alto (multi-canal com menos overhead por canal, MOSI parado durante a fase de
comando). **Esforço do follow-up de comentário:** Trivial (feito). **Toca PRU asm:** sim (o
follow-up foi só o comentário, não a lógica).

---

### 1.6 Buffers ping-pong: risco real de corrupção silenciosa sem *backpressure*

Este é provavelmente o ponto mais importante ainda em aberto neste documento para o
objetivo de "não corromper os dados medidos" em taxas mais altas — permanece exatamente
como identificado na revisão anterior, sem nenhuma mitigação implementada ainda.

Hoje, a troca de buffer na PRU (`troca_para_buffer_0`/`troca_para_buffer_1` em
`spi_core.asm`) acontece **assim que o buffer atual enche**, e a PRU começa a escrever
imediatamente no *outro* buffer — sem checar se o ARM já terminou de ler/gravar em disco
o conteúdo anterior desse outro buffer. O único sinal existente é a flag `bufferX_ready`,
que o ARM zera depois de processar, mas a PRU nunca espera essa flag voltar a zero antes
de começar a escrever de novo ali.

Na prática, isso funciona hoje porque o ARM tem o tempo inteiro de preenchimento de um
buffer para processar o outro — mas essa margem **encolhe exatamente quando a taxa de
amostragem sobe** (é menos tempo por buffer) ou quando o `fwrite`/disco trava por
qualquer motivo (cartão SD com garbage collection, escrita em disco cheio, escalonador
do Linux preemptando o processo). Se o ARM ainda estiver no meio da leitura/gravação de
um buffer quando a PRU volta a escrever nele, o resultado é corrupção silenciosa — sem
nenhum erro, warning ou flag indicando que isso aconteceu. É um risco que cresce
exatamente na direção em que o projeto quer ir (taxas mais altas).

**Sugestões, da mais simples à mais completa:**
1. **Detecção mínima (ARM):** medir o tempo entre o instante em que uma flag `ready`
   aparece e o instante em que o `fwrite` termina; se esse tempo se aproximar do tempo
   esperado de preenchimento de um buffer (calculável a partir de
   `SAMPLES_PER_BUFFER / frequência_efetiva`), emitir um aviso em stderr. Não impede a
   corrupção, mas pelo menos torna o risco visível.
2. **Contador de sequência (PRU + ARM):** reservar 4 bytes no início de cada buffer (ou
   um campo dedicado em `shared_control`) como número de sequência, incrementado pela
   PRU a cada troca de buffer. O ARM verifica se os números lidos são consecutivos; um
   "salto" indica que um buffer foi sobrescrito antes de ser lido.
3. **Backpressure real (mais robusto, mais esforço):** a PRU checa, antes de começar a
   escrever num buffer, se a flag `ready` correspondente já foi zerada pelo ARM; se não
   foi, ela pode sinalizar uma condição de *overrun* explícita (um novo campo em
   `shared_control`, ex. `overrun_flag`) em vez de escrever por cima silenciosamente.
   Isso não "resolve" o overrun (a PRU não pode pausar a aquisição analógica em curso
   sem perder amostras de qualquer forma), mas transforma dado corrompido e não
   detectado em dado perdido e **detectado** — uma diferença enorme para a validade de
   uma medição.

**Impacto:** Alto. **Esforço:** Baixo (opção 1) a Médio (opções 2-3). **Toca PRU asm:**
sim, para as opções 2 e 3. **Status:** ainda em aberto, prioridade máxima.

---

### 1.7 Usar mais dos 16 MB já reservados na DDR

`DDR_RESERVED` reserva 16 MB, mas a captura atual usa só 4 MB (2 buffers × 2 MB). Ampliar
para um esquema de N buffers (ex. 4 a 8 buffers de 1-2 MB cada, num anel em vez de só
ping-pong) dentro da mesma região já reservada dá mais folga temporal para o ARM
absorver picos de latência de I/O antes de um overrun acontecer — sem precisar pedir
mais memória ao sistema. Isso se soma bem com o item 1.6 (mais buffers dão mais tempo
antes que o problema de *backpressure* se manifeste, mesmo sem resolver a causa raiz).

**Impacto:** Médio-Alto. **Esforço:** Médio (mexe na struct de controle, no loop da PRU
e no loop de leitura do ARM). **Toca PRU asm:** sim. **Status:** ainda em aberto.

---

### 1.8 Lado ARM: pontos de robustez que não dependem da PRU

Vários ganhos de robustez (e, indiretamente, de taxa sustentável) não exigem tocar em
Assembly nem recompilar com `clpru`. **Dois dos quatro pontos abaixo já foram resolvidos**
desde a última revisão — os outros dois continuam abertos:

- ✅ **`fwrite()` sem checagem de retorno — RESOLVIDO.** `ler_adc.c` hoje checa o valor de
  retorno de cada `fwrite()` contra o número de amostras esperado, em ambos os buffers do
  esquema ping-pong; em caso de divergência, imprime um erro claro em stderr e encerra a
  captura de forma limpa (`manter_execucao = 0`), em vez de continuar rodando
  silenciosamente com dados perdidos.
- ✅ **`BLOCOS_PARA_CAPTURAR` fixo em 1 no código-fonte — RESOLVIDO, de forma mais completa
  que a proposta original.** A proposta original pedia um parâmetro simples de número de
  blocos; o que foi implementado é mais rico: `--blocos N` (N=0 para captura indefinida
  até Ctrl+C) **e** `--duracao T` (aceita sufixo `s`/`m`/`h`, convertido automaticamente
  para o número de blocos equivalente), mutuamente exclusivas, com `BLOCOS_PADRAO = 1`
  preservado como default para não quebrar o uso já documentado em `setup.sh`. Como efeito
  colateral, capturas mais longas agora de fato exercitam o buffer B do esquema ping-pong
  em regime contínuo, o que antes praticamente não acontecia.
- ❌ **Prioridade de tempo real e menos jitter de escalonamento — ainda não feito.** Rodar
  `ler_adc` com `SCHED_FIFO` (via `sched_setscheduler()`) e travar as páginas do processo
  em memória com `mlockall()` continua sem implementação. Combinado com colocar o
  `cpufreq governor` da BeagleBone em `performance` durante a captura, ajudaria a manter o
  tempo de resposta do polling mais previsível — relevante especificamente para o item 1.6
  (menos jitter = menos chance de o ARM atrasar o suficiente para um overrun).
- ❌ **Polling com `usleep(2000)` fixo — ainda não revisto.** O laço principal de
  `ler_adc.c` continua usando um atraso fixo de 2 ms por iteração, independente de haver
  trabalho a fazer. Vale reavaliar esse valor (ou substituir por uma espera mais reativa)
  à luz do tempo real de preenchimento de buffer na frequência-alvo — essa folga de
  latência fica cada vez mais relevante quanto mais curto for esse tempo em taxas altas.

**Impacto:** Alto (conjunto de mudanças de baixo risco e alto retorno — metade já colhida).
**Esforço:** Baixo, para os dois itens restantes. **Toca PRU asm:** não.

---

### 1.9 Sincronização manual de constantes compartilhadas — revisado

A revisão anterior deste item cobria dois pontos de sincronização manual: `SAMPLES_PER_BUFFER`
(entre `memoria_pru.h` e um `LDI r21` hardcoded em `spi_core.asm`) e o layout de
`comandos_canais[]`/`ADS8688_MAX_CANAIS` no Assembly (modo manual multi-canal).

**O segundo ponto está resolvido, mas não pela via proposta** — pela remoção da própria
necessidade. Com a migração para o modo automático (item 1.5), `spi_core.asm` **não lê
mais** `comandos_canais[]` nem precisa saber `ADS8688_MAX_CANAIS`: o próprio
`memoria_pru.h` documenta isso explicitamente hoje ("A PRU (`spi_core.asm`) NÃO usa mais
esta constante desde a migração para o modo automático"). Essa classe de risco de
sincronização, do lado Assembly, desapareceu.

**O primeiro ponto (`SAMPLES_PER_BUFFER`) continua totalmente válido e sem mitigação:** o
valor `1.048.576` ainda precisa bater manualmente entre a `#define` em `memoria_pru.h` e o
par `LDI r21.w0`/`LDI r21.w2` hardcoded em `spi_core.asm`, sem nenhuma checagem automática
em tempo de build. É especialmente relevante se `SAMPLES_PER_BUFFER` for alterado como
parte do item 1.7 (mais buffers/buffers menores) — sem automação, cada mudança nesse valor
é uma nova chance de os dois lados ficarem dessincronizados sem erro de compilação nenhum.

**Sugestão (inalterada):** gerar os valores usados no Assembly a partir de `memoria_pru.h`
em tempo de build (defines passados ao assembler via `clpru -d`, ou um `.inc` gerado por
uma regra do `Makefile`), em vez de duplicá-los manualmente.

**Achado novo nesta revisão — o mesmo padrão de risco reapareceu em outro lugar:**
`ADS8688_MAX_CANAIS` (o limite de 8 canais físicos do ADS8688) hoje é hardcoded de forma
independente em **três** lugares: `memoria_pru.h` (fonte "oficial"), e de novo em
`scripts/adc_tool.py`, que comenta isso explicitamente no próprio código ("Precisa ficar
em sincronia manual com `ADS8688_MAX_CANAIS` em `firmware/memoria_pru.h` -- não há
arquivo de constantes compartilhado entre o firmware em C/Assembly e este script"). Como o
Python não pode simplesmente incluir um header C, as opções são: (a) gerar um pequeno
arquivo de constantes (JSON ou `.py`) a partir de `memoria_pru.h` como parte do fluxo de
build/CI (mesma ideia do item 1.7/geração de `.inc` para o Assembly, aplicada também aqui),
ou (b) aceitar a duplicação, já bem comentada nos dois lados, dado que `8` é uma constante
física do chip (número de entradas do ADS8688) com risco de mudança praticamente nulo —
prioridade mais baixa que `SAMPLES_PER_BUFFER`, que é um valor de projeto plausivelmente
ajustado no curto prazo (item 1.7).

**Atualização de 2026-10 (lado Python mitigado):** o Python agora vive em
`scripts/supraharmonicos/constantes.py` e `cabecalho.py`, e `tests/test_contrato_firmware.py`
lê `firmware/ler_adc.c` e `firmware/memoria_pru.h` a cada `pytest`: confere constantes do
cabeçalho, códigos `GRANDEZA_*`, o layout campo a campo da struct v2 e o valor de
`ADS8688_MAX_CANAIS`. Se um lado mudar sem o outro, o teste falha (e a CI também). O teste
**não** cobre `SAMPLES_PER_BUFFER` nem o `LDI r21` de `spi_core.asm`, então essa metade do
item segue aberta.

**Impacto:** Médio (evita uma classe inteira de bugs futuros). **Esforço:**
Baixo-Médio para `SAMPLES_PER_BUFFER`; Baixo para `ADS8688_MAX_CANAIS` (ou aceitar como
está, dado o baixo risco de mudança). **Toca PRU asm:** sim, só para `SAMPLES_PER_BUFFER`
(só a forma de gerar a constante, não a lógica).

---

### 1.10 Hardware: bug de saturação — causa raiz já resolvida, follow-ups permanecem

> Na revisão anterior, este item descrevia o bug de saturação como "o bloqueador mais
> crítico no momento" e listava a remoção de jumpers longos como um próximo passo
> **planejado**. Cruzando com `docs/notas_relatorio.md` (Marco 4) e
> `docs/contexto_projeto.md` (seções 2.2 e 6.1), essa correção **já foi feita**: a causa
> raiz identificada (jumpers longos entre a placa de aquisição e o frontend, gerando
> reflexo/ruído induzido) foi confirmada com uma ferramenta de diagnóstico dedicada
> (`spi_core_diagnostico_preambulo.asm` + `analisar_preambulo.py`, não versionados neste
> repositório) e corrigida conectando
> as placas diretamente. Este item deixa de ser um bloqueador urgente e passa a ser uma
> checklist de confirmação/hardening para a próxima revisão de PCB.

- **Confirmar o isolador contra esquemático/BOM.** `docs/contexto_projeto.md` já lista o
  isolador como Analog Devices **ADuM3150** — um isolador digital dedicado (família
  SPIsolator/iCoupler), não um optoacoplador simples tipo PC817 — mas marca essa
  informação como "a confirmar contra esquemático/BOM". Se confirmado, a suspeita original
  deste item (descasamento de subida/descida num componente pensado só para chaveamento
  on/off) provavelmente não se aplica: o ADuM3150 já tem PWD (*pulse-width distortion*)
  especificado e tipicamente baixo, exatamente para uso em comunicação digital. Vale fechar
  essa confirmação formalmente — é o único ponto realmente em aberto deste item hoje.
- Capturar com o analisador lógico/osciloscópio diretamente nos pinos de SCLK/MOSI/MISO
  **na saída do isolador**, comparando distorção simétrica vs. assimétrica entre
  transições, permanece uma verificação de baixo custo que vale a pena mesmo com a causa
  raiz já resolvida — serve como confirmação positiva, não só diagnóstico de problema.
- Prever pontos de teste (test points) explícitos para SCLK/CS/MOSI/MISO de cada lado da
  barreira de isolamento na próxima revisão da PCB permanece uma boa prática para reduzir
  a dependência de jumpers/pontas de prova improvisadas em depurações futuras.
- Boas práticas gerais de layout para o frontend do ADC (capacitores de desacoplamento de
  baixo ESR perto dos pinos de alimentação, plano de terra único com separação
  analógica/digital, trilhas de SPI curtas entre isolador e ADC/PRU) continuam válidas
  como checklist para a próxima revisão de PCB, independente do bug original.

**Impacto:** Baixo-Médio agora (era Alto/bloqueador quando a causa raiz ainda era
desconhecida). **Esforço:** Baixo (confirmação de BOM + medições pontuais) a Médio (test
points formais exigem nova revisão de PCB).

---

## Parte 2 — Estrutura de projeto e profissionalização

### 2.1 Reorganização de diretórios — parcialmente concluído

A estrutura atual já é sensata; os ajustes abaixo são principalmente sobre convenções de
nomenclatura e separação de responsabilidades:

```text
.
├── docs/
│   ├── proposta-ic.pdf
│   ├── datasheets/              # datasheets soltos hoje ficariam aqui
│   ├── architecture.md          # novo — diagrama + explicação da arquitetura
│   └── licoes-aprendidas.md     # novo — histórico de depuração consolidado
├── firmware/
│   ├── ler_adc.c
│   ├── pru_main.c
│   ├── spi_core.asm
│   ├── memoria_pru.h
│   ├── AM335x_PRU.cmd
│   ├── Makefile
│   ├── setup.sh
│   └── tests/                   # novo — testes de host para lógica extraída do ARM
├── hardware/
├── scripts/
├── .gitignore
├── LICENSE
└── README.md
```

✅ **O ponto que a revisão anterior mudaria "com mais convicção" já aconteceu — mas por
remoção, não por renomeação.** A sugestão original era renomear `backup pre-assembly/`
(que tinha espaço no nome, fonte de atrito em linha de comando/CI) para algo como
`legacy/`. Essa pasta **já foi removida do repositório por completo** — não existe mais
nem como `legacy/`, nem sob o nome antigo. O objetivo prático (eliminar o atrito de um
diretório com espaço no nome) foi alcançado, mesmo que o histórico do protótipo em C
pré-Assembly não esteja mais navegável diretamente no repositório (ele permanece
documentado em prosa em `docs/notas_relatorio.md`, Marco 1).

**Atualização de 2026-10:** foram criados `tests/` (na raiz, com os testes do Python),
`.github/workflows/ci.yml` e `docs/arquitetura_software.md` (cumpre o papel do
`architecture.md` sugerido, para o lado Python). Os datasheets continuam em
`docs/Datasheets/`. **Ainda em aberto:** `docs/licoes-aprendidas.md` e `firmware/tests/` (ver
itens 2.5 e 2.7 abaixo).

**Impacto:** Médio (organização/portfólio). **Esforço:** Baixo.

---

### 2.2 `.gitignore` ✅ CONCLUÍDO

Já existe e cobre mais casos do que a proposta original: além dos artefatos de build do
firmware (`*.out`, `*.map`, `*.obj`, `ler_adc`), dados capturados (`*.bin`, `*.csv`) e
ambiente Python/editor, o `.gitignore` atual também trata:

- Diretórios de trabalho da BeagleBone e de dados coletados (`BeagleBone/`,
  `Collected_Data/`).
- Artefatos temporários do **Altium Designer** de forma genérica (`**/History/`,
  `**/*.PcbDoc.bak`, `**/Recovery/`, etc.) — cobre qualquer placa futura em `/hardware`,
  não só o `DAQ_Module` atual.
- Padrões específicos de nomes de captura (`**/supraharmonicos_raw.bin`,
  `**/amostras_*.csv`, `**/diagnostico_preambulo.bin`).

Nenhuma ação pendente aqui — só vale revisitar se algum `.bin`/`.csv` de exemplo pequeno
precisar de exceção explícita quando os testes do item 2.5 forem implementados.

**Impacto:** Médio. **Esforço:** Baixo. **Status:** concluído.

---

### 2.3 Metadados de captura ✅ CONCLUÍDO (implementado como cabeçalho embutido, não sidecar)

A proposta original sugeria um arquivo lateral (*sidecar*) `.json` gravado ao lado do
`.bin`, com os parâmetros da captura. O que foi implementado é diferente — e resolve o
mesmo problema de forma mais robusta: um **cabeçalho binário fixo de 1024 bytes, embutido
no próprio `.bin`** (magic number `"SHAN"`, versão de formato, todos os parâmetros da
captura, checksum CRC-32) — ver `docs/contexto_projeto.md`, seção 4.2, para o layout
completo campo a campo.

Vantagens práticas dessa escolha sobre a proposta original de sidecar:

- **Não existe risco de o metadado se perder ou ficar dessincronizado do `.bin`** — não
  há dois arquivos para manter juntos ao copiar/renomear/arquivar uma captura.
- **Verificação de integridade embutida (CRC-32)** — um `.json` avulso não teria como
  detectar corrupção/truncamento do próprio arquivo de metadados; o cabeçalho atual tem
  um checksum dedicado, verificado automaticamente por `adc_tool.py` ao abrir o arquivo.
- `adc_tool.py` já consome esse cabeçalho de forma transparente: `-f/--frequencia` e
  `--canais` deixam de ser obrigatórios quando presente, e um resumo (título, descrição,
  canais, CRC) é impresso ao abrir a captura.

Isso também elimina de vez a necessidade que a proposta original mirava: copiar
manualmente a lista de canais impressa no console de `ler_adc` para reusar depois.

**Impacto:** Médio-Alto. **Esforço:** já investido. **Toca PRU asm:** não. **Status:**
concluído — nenhuma ação pendente.

---

### 2.4 Rastreabilidade de versão do firmware

Continua sem implementação: não há, hoje, como saber, olhando só para um `.bin`
capturado, qual versão exata do firmware da PRU o gerou. Isso ficou **mais relevante**, não
menos, desde a última revisão: com a migração para o modo automático já validada (item
1.5) e com ajustes de timing do item 1.4 ainda planejados, comparar capturas de
antes/depois de uma mudança de firmware vai exigir saber exatamente qual build gerou cada
uma. Uma forma simples: gerar, no `Makefile`, uma constante com o hash curto do commit
atual (`git rev-parse --short HEAD`) e embuti-la tanto no binário do ARM (para imprimir no
console) quanto num novo campo no cabeçalho do `.bin` (seção 4.2 do contexto do projeto —
hoje não há campo reservado para isso; adicionar um campo de versão de formato já existe
via `versao_cabecalho`, mas um hash de commit do firmware é uma informação diferente e
ainda não tem onde ir).

**Impacto:** Médio (mais alto agora que ajustes de timing estão na fila). **Esforço:**
Baixo. **Status:** ainda em aberto.

---

### 2.5 Testes e CI

✅ **Atualização de 2026-10 — lado Python concluído.** Existe uma suíte `pytest` versionada
em `tests/` (651 testes; `-m "not e2e"`, 536 testes, roda em ~2 min), cobrindo unidades por módulo,
CLI, o contrato C↔Python (`test_contrato_firmware.py`), as regras de arquitetura
(`test_arquitetura.py`), as dependências e o fluxo completo de perfil de sonda
(`tests/e2e/`). O `ruff` cuida do estilo. O GitHub Actions (`.github/workflows/ci.yml`)
roda `ruff` + `pytest` em Python 3.10 e 3.13 a cada pull request e a cada push na `main`
(ver `docs/arquitetura_software.md`, seção 7.1). **Continua em aberto** o que toca o C:
testes de host para `analisar_lista_canais()`/`comando_canal()` (extraídos de `ler_adc.c`) e
`make arm` com `-Wextra` na CI. O texto abaixo é o da revisão anterior, mantido como
registro.

Boa parte da disciplina de validação já existia no projeto — mas informalmente, não como
algo que roda sozinho:

- O lado Python (`adc_tool.py`) já tem uma suíte de validação com capturas sintéticas
  (fundamental + supraharmônicos injetados, incluindo *dithering*, + ruído gaussiano —
  ver `docs/contexto_projeto.md`, seção 6.2), que cobre `--fft`, `--welch`,
  `--modo-espectro`, `--agrupar-bandas`, `--picos`, multi-canal e round-trip
  `.bin`↔`.csv`. Isso já existe e já deu resultados concretos (picos injetados recuperados
  com erro compatível com a resolução espectral), mas, pelo que está documentado, ainda
  não está formalizado como uma suíte `pytest` versionada e reexecutável — é o candidato
  mais óbvio e de **menor esforço adicional** para uma primeira suíte de testes real,
  porque a metodologia e os casos de teste já existem, só falta empacotar. Boa parte das
  funções envolvidas já são puras e fáceis de testar isoladamente: `analisar_lista_canais`,
  `desintercalar`, `refinar_pico_parabolico`, `agrupar_em_bandas`,
  `calcular_espectro_welch`.
- **Extrair lógica testável do `ler_adc.c`.** Funções como `analisar_lista_canais()` e
  `comando_canal()` são lógica pura (sem acesso a `/dev/mem`), mas hoje estão `static`
  dentro de `ler_adc.c` (confirmado — continuam assim na versão atual), o que dificulta
  testá-las isoladamente. Movê-las para um par `canal_utils.c`/`canal_utils.h` separado
  permite compilar um pequeno executável de teste no host (sem precisar da BeagleBone) que
  valida casos como lista vazia, canal repetido, canal fora de 0-7, mais de 8 canais.
- **CI leve (GitHub Actions), só com o que é seguro automatizar:**
  - `make arm` (compila `ler_adc.c` com `gcc -Wall -Wextra` — o `Makefile` atual usa só
    `-Wall -O3`; vale adicionar `-Wextra` ao alvo `arm` para um pouco mais de cobertura de
    aviso, sem custo) — não depende de hardware nem do `clpru` (proprietário da TI, difícil
    de automatizar em CI pública), então roda em qualquer runner padrão.
  - Os testes de host do item acima (`canal_utils`).
  - A suíte de sinais sintéticos de `adc_tool.py`, formalizada em `pytest`.
  - Lint do lado Python com `pyflakes`/`ruff`.
  - Deixar claro no README/CI que a build da PRU (`clpru`) e a validação em hardware
    continuam sendo passos manuais, documentados, não automatizados — é uma limitação
    honesta, não uma lacuna escondida.

**Impacto:** Médio (qualidade/portfólio — sinaliza rigor de engenharia de forma
verificável; mais barato agora que a suíte sintética Python já existe informalmente).
**Esforço:** Baixo-Médio. **Status:** parcial — Python e CI concluídos; testes de host do C
e `make arm` na CI em aberto.

---

### 2.6 `setup.sh` mais defensivo

Sem mudanças desde a última revisão (reconferido em 2026-10; o script também não tem
*shebang*) — o script ainda tem só o comentário avisando sobre o
risco de nome de arquivo errado e sugerindo checar `dmesg` manualmente depois do `start`,
sem nenhuma checagem automática. A versão defensiva proposta permanece válida tal como
estava:

```bash
set -e  # aborta no primeiro erro, em vez de continuar silenciosamente

# ... cp e stop/start como já está ...

sleep 0.5
estado=$(cat /sys/class/remoteproc/remoteproc1/state)
if [ "$estado" != "running" ]; then
    echo "ERRO: PRU não entrou em estado 'running' (estado atual: $estado)." >&2
    echo "Verifique 'dmesg | tail -n 20' para detalhes." >&2
    exit 1
fi
echo "PRU carregada e em execução."
```

**Impacto:** Médio. **Esforço:** Baixo. **Status:** ainda em aberto.

---

### 2.7 Documentação consolidada

- **`docs/architecture.md`** — ✅ em grande parte atendido em 2026-10: o `README.md` traz um
  diagrama Mermaid do fluxo (PCB → PRU → DDR → ARM → computador), `docs/arquitetura_software.md`
  cobre o software, e `docs/guia_de_uso.md` cobre a operação. Para o fluxo ARM ↔ PRU em
  detalhe, o diagrama abaixo continua sem equivalente. Antes, este item dizia que
  `docs/contexto_projeto.md` já cumpria boa parte desse papel de referência. Um
  diagrama simples do fluxo ARM ↔ PRU ↔ DDR ↔ ADC continua valendo a pena como ponto de
  entrada visual. Vale atualizar o esboço de diagrama Mermaid abaixo (já ligeiramente
  diferente do sugerido na revisão anterior) para refletir explicitamente a sequência de
  configuração de 2 transações do modo automático (escrita de `AUTO_SEQ_EN` + comando
  `AUTO_RST`) antes do laço principal, já que isso é parte real do fluxo hoje e não existia
  no modo manual:

  ```mermaid
  flowchart LR
      subgraph ARM["ARM / Linux — ler_adc.c"]
          A1[Lê argv: frequência, canais,<br/>--blocos/--duracao] --> A2[mmap /dev/mem:<br/>shared_control + DDR_RESERVED]
          A2 --> A3[Escreve config:<br/>buffers, auto_seq_mask]
          A3 --> A4[Grava cabeçalho SHAN<br/>+ config_ready = 1]
          A4 --> A5[Poll buffer_X_ready]
          A5 -->|pronto| A6[fwrite bloco -> .bin<br/>checa retorno]
          A6 --> A5
      end

      subgraph PRU["PRU0 — pru_main.c + spi_core.asm"]
          P1[Aguarda config_ready] --> P2[Lê auto_seq_mask uma única vez]
          P2 --> P2b[Configura ADS8688:<br/>escreve AUTO_SEQ_EN 24 ciclos<br/>+ comando AUTO_RST 32 ciclos]
          P2b --> P3[Laço principal:<br/>bit-bang SPI, 32 ciclos/amostra,<br/>comando sempre NO_OP]
          P3 --> P4[Grava amostra na DDR<br/>buffer ping-pong ativo]
          P4 --> P5{Buffer cheio?}
          P5 -->|não| P3
          P5 -->|sim| P6[Marca ready=1<br/>troca de buffer<br/>SEM checar backpressure]
          P6 --> P3
      end

      ADC[("ADS8688<br/>modo AUTO_RST<br/>via SPI + isolamento galvânico")]
      P3 <--> ADC
      A3 -.shared_control.-> P1
      P4 -.DDR_RESERVED.-> A6
  ```

- **`docs/licoes-aprendidas.md`** — ainda não criado. Boa parte do histórico de depuração
  hoje vive espalhado em comentários de código (a tentativa de MOSI "branchless" que não
  deu certo, a assimetria do optoacoplador/jumpers já resolvida, o motivo de descartar a
  primeira amostra do lado ARM, o bug de 24 vs. 32 ciclos do modo automático). Consolidar
  num documento narrativo continua sendo o tipo de material que demonstra rigor de
  engenharia para um portfólio — e `docs/notas_relatorio.md` já cobre boa parte dessa
  narrativa em formato cronológico; `licoes-aprendidas.md` poderia ser um recorte
  reorganizado por *tema* (timing SPI, integridade de sinal, formato de arquivo) em vez de
  por ordem cronológica, complementando em vez de duplicando.

**Impacto:** Médio-Alto para fins de portfólio. **Esforço:** Baixo-Médio. **Status:**
parcial — `README.md`, guia de uso e arquitetura do software prontos; `licoes-aprendidas.md` e
o diagrama detalhado ARM ↔ PRU abaixo seguem abertos.

---

### 2.8 ✅ CONCLUÍDO — Nome de arquivo `Adc_tool.py` — inconsistência que quebra os comandos documentados

> **Resolvido:** o arquivo foi renomeado (commit `1d0965e`) e hoje é `scripts/adc_tool.py`.
> O texto abaixo é mantido como registro do achado.

Achado novo desta revisão, e provavelmente o item de **maior retorno por menor esforço**
de todo o documento. O arquivo em disco está nomeado `scripts/Adc_tool.py` (`A` e `T`
maiúsculos), mas **todo o resto do projeto** — o próprio docstring interno do script
(`"""adc_tool.py -- Conversão, visualização..."""`), o `argparse(prog="adc_tool.py")`
usado nas mensagens de `--help`, o README (`python3 adc_tool.py --help`, todos os
exemplos de uso) e `docs/contexto_projeto.md` — refere-se a ele como `adc_tool.py`, em
minúsculas.

Em Windows (sistema de arquivos insensível a maiúsculas/minúsculas) isso passa
despercebido. Mas o fluxo de desenvolvimento deste projeto usa Linux/BeagleBone (que **é**
sensível a maiúsculas/minúsculas) — qualquer pessoa que copie e cole um comando
exatamente como documentado no README (`python3 adc_tool.py captura.bin --fft`) recebe um
`No such file or directory`, porque o arquivo real se chama `Adc_tool.py`. Isso afeta
literalmente todo exemplo de linha de comando documentado para a ferramenta de análise.

**Sugestão:** renomear o arquivo para `scripts/adc_tool.py` (minúsculas), consistente com
tudo que já se refere a ele dessa forma — nenhuma outra mudança necessária, já que o
conteúdo interno do arquivo já usa esse nome em todo lugar.

**Impacto:** Alto (quebra prática, imediata, de todo comando documentado). **Esforço:**
Trivial (`git mv scripts/Adc_tool.py scripts/adc_tool.py`). **Toca PRU asm:** não.

---

### 2.9 ✅ Credencial em texto plano em `scripts/set_date.sh` (resolvido)

`scripts/set_date.sh` (sincroniza a data/hora do computador para a BeagleBone, mitigando a
ausência de RTC com bateria mencionada em `ler_adc.c`) autenticava via SSH usando `sshpass`
com uma senha **hardcoded em texto plano** no script versionado (`PASSWORD="temppwd"`).
Mesmo sendo uma senha de laboratório de baixo risco, é um hábito que não convém num
repositório público.

**O que foi feito:** o script foi reescrito. Nenhuma senha fica no arquivo: o padrão é
**chave SSH** (`ssh-copy-id`) ou o próprio `ssh`/`sudo` pedindo a senha no terminal; quem não
quiser digitar pode exportar `SSHPASS` (o `sshpass` só é usado nesse caso, e a senha vai pela
variável de ambiente, não pela linha de comando). Usuário e endereço vêm de `BBB_USER` e
`BBB_IP` (padrão `debian@192.168.6.2`). Mais duas correções no caminho: o horário agora vai
como instante absoluto UTC (`date -u -s @epoch`), em vez de texto no fuso do computador — se o
fuso da BeagleBone fosse outro, o `timestamp_unix` do cabeçalho saía deslocado —, e
`StrictHostKeyChecking=no` virou `accept-new` (aceita a chave na primeira conexão, mas
recusa se ela mudar). O script não instala mais nada sozinho (`apt install sshpass`).

**Ação que sobra:** a senha antiga continua no **histórico do Git**. Por ser a senha padrão da
imagem Debian da BeagleBone (um valor público) o risco é baixo, mas, se a BeagleBone for
exposta a alguma rede, troque a senha do usuário `debian` (`passwd`).

---

### 2.10 ✅ `calibrar_sonda.sh`: Nyquist efetiva, reescrita e testes (resolvido)

Achado de 2026-10, ao revisar a documentação contra o código: `validar_nyquist()` exigia
`freq_max < taxa / 2`, em que `taxa` é a taxa **total** pedida ao `ler_adc`. Só que a captura de
calibração usa **dois canais** (referência + sonda), a taxa total é dividida entre eles e a
Nyquist efetiva de cada um é `taxa / 4`: a 102,4 kHz totais, o script aceitava pontos até
51,2 kHz, mas acima de 25,6 kHz o sinal já sofre *aliasing*.

**O que foi feito:** em vez de remendar a checagem, o script foi reescrito a partir do que ele
precisa fazer (ver `docs/guia_de_uso.md`, "Passo 1"): o operador informa só a taxa, o número de
pontos e a sonda, e o script **escolhe as frequências** (escala logarítmica até 80% da Nyquist
efetiva, `taxa / 4`), instrui o operador ("INJETE 200 Hz"), chama o `ler_adc` com o cabeçalho
completo e **confere cada captura** (cabeçalho, CRC, tamanho, saturação, nível e frequência
medida). Também ganhou os modos `retomar`, `refinar`, `adensar`, `refazer` e `resumo`, captura
em arquivo temporário (só vira ponto o que o operador aceita), tempo limite para o `ler_adc` e
Ctrl+C seguro. Na reescrita apareceram e foram corrigidos erros do script antigo além do da
Nyquist: o `ler_adc` devolve sucesso mesmo quando o disco enche e a captura sai cortada (agora o
tamanho do arquivo é conferido), o `ler_valor` nunca aceitava ENTER (`grep` com `^$`), o título
passava de 63 bytes com ids de sonda longos (o `ler_adc` rejeita), e o menu antigo podia disparar
nova medição com uma opção inválida. `tests/test_calibrar_sonda.py` (59 testes, com um `ler_adc`
falso) cobre o fluxo e confere que as constantes do cabeçalho no script batem com o firmware e o
Python.

**Atualização (2026-10): 1 canal por padrão.** A calibração com dois canais limita a Nyquist a
`taxa / 4`: no máximo 125 kHz com os 500 kS/s do ADC, o que não cobre os 150 kHz dos supraharmônicos.
Agora o padrão é **um canal só** (`--canal-sonda N`, obrigatório; Nyquist `taxa / 2`, ex.: 400 kS/s →
200 kHz, pontos até 160 kHz), e a corrente real vem do osciloscópio (`--ref-externa`: o script pede a
tensão RMS lida sobre o shunt a cada ponto e a grava em `referencia_externa.csv`; o
`gerar_perfil_sonda.py --referencia-externa` a usa). `--canal-referencia N` mantém o modo de 2 canais, e
sem nenhum dos dois vale a corrente constante. O limiar de "sem sinal" caiu de 1% para 0,2% da escala
(o filtro de 15 kHz do ADS8688 derruba o sinal em alta frequência; ver 2.12). No gerador de perfil, o
estimador de amplitude passou a refinar o tom por FFT única: o Welch com flat-top errava até 1,8% nos
modos de 1 canal, onde a amplitude é absoluta (adendo em `docs/auditoria_perfil_sonda.md`).

**Atualização (2026-10, amplitude conhecida e osciloscópio).** Dois jeitos novos de dar a referência ao
perfil, ambos de 1 canal: (a) **senoide de amplitude conhecida** (`calibrar_sonda.sh --amplitude 500mVpp`
ou `--amplitude-por-ponto`): o script grava `ref: f=<Hz> amp=<amplitude>` no campo `descricao` do cabeçalho
de cada captura (`ler_adc -d`) e o `gerar_perfil_sonda.py` o lê sem flag nenhuma; a amplitude exige unidade e
tipo (`500mVpp`, `250mVpk`, `176.8mVrms`, `2Arms`) porque pico a pico, pico e eficaz diferem por um fator
2 ou 1,41; (b) **`.m` do osciloscópio** (`--referencia-osciloscopio`): um arquivo por captura, com o nome dela,
ajustado por mínimos quadrados. O `medir_captura.py` ganhou `--amplitude-referencia` e `--osciloscopio` para
comparar o ADC com a amplitude injetada e com o osciloscópio (conferência do método), e o gerador de perfil
imprime e grava a resposta do conjunto (−3 dB, inclinação, amplificação de ruído). O manifesto ganhou a coluna
`amplitude_ref`. Limites a declarar: o "500 mVpp" do gerador vale para carga de 50 Ω (o dobro em alta
impedância); a planura do gerador entra no perfil; injetar tensão no lugar da saída da sonda mede o frontend e
o ADC, sem a sonda de corrente.

**Atualização (2026-10-19/20, primeira bancada real e cadeia de tensão).** O script foi usado no T3
(48 pontos, cadeia de tensão, `--ref-externa`): a interação com o hardware (tempo real de captura,
`/dev/mem`, PRU, cabeçalho v3) funcionou. Os textos, porém, eram todos de corrente ("tensão RMS no shunt"),
e o script ganhou `--grandeza corrente|tensao`: vai para o cabeçalho de cada captura, é conferida, fica no
plano (plano antigo sem a chave = corrente) e troca as instruções; com `tensao` a leitura do osciloscópio vai
para a coluna `tensao_rms_V`, que o gerador de perfil usa sem `--resistencia-shunt`. A revisão completa que
acompanhou essa mudança corrigiu: a coleta nova sobre pasta existente que escolhia "retomar" usava as
repetições e os blocos padrão em vez dos do plano; o `scp` sugerido copiava para o lugar errado; o tempo
limite agora manda SIGINT ao `ler_adc` (que fecha o arquivo) e KILL 10 s depois; e o modo de 2 canais passou
a avisar que o filtro do ADC, igual nos dois canais, se cancela na razão (o perfil desse modo não o corrige).
O arquivo já está executável no Git (`100755`).

---

### 2.11 🆕 Melhorias do fluxo de perfil de sonda (vindas da auditoria)

A auditoria (`docs/auditoria_perfil_sonda.md`, seção 4) deixou propostas que dependem de
decisão de projeto ou de bancada. Resumo, com o status atual (nenhuma implementada):

| Proposta | Para quê | Esforço | Decisão necessária |
|---|---|---|---|
| Ganho **complexo** (fase) — seção 4.1 | Análise V×I, potência, direção de emissão | Médio–Alto | Sim: muda o formato do perfil e a correção |
| Perfil **absoluto** (V/A) — seção 4.2 | Elimina o risco de usar um `--ganho` diferente do da calibração | Médio | Sim: muda a semântica de `--ganho` |
| Validação por frequências retidas (*hold-out*) — seção 4.3 | Única forma de detectar ressonância perdida com dados reais | Médio | Não |
| Teto de ganho da correção — seção 4.4 | Evita "corrigir" ruído em frequências onde a sonda atenua muito | Baixo | Sim: altera o resultado |
| Atributo HDF5 `correcao_sonda_aplicada` — seção 4.5 | Avisar quem abre o `.h5` fora do `adc_tool.py` | Baixo | Não |
| Aviso de perfil velho (`data_calibracao`) | Lembrar de recalibrar | Baixo | Não |
| **Medir a fase** da cadeia (vinda do T3) | Validar a função de transferência ajustada só pela magnitude (hoje sob hipótese de fase mínima) e preparar o ganho complexo. Método: osciloscópio na entrada da cadeia e na linha CS do ADS8688, que retém a amostra na borda de descida (datasheet 8.4.1.1.1); o difícil é saber qual borda do CS é a 1ª amostra gravada (contar os quadros de configuração da PRU, `tests/pru_sim.py`, ou marcá-la num GPIO) — errar por uma amostra (10 µs a 100 kS/s) é da ordem do atraso de grupo do filtro (~12 µs) | Médio | Não (o GPIO tocaria a PRU) |
| **Subamostragem** para medir \|H\| acima da Nyquist (vinda do T3) | Uma senoide pura acima de fs/2 aparece em \|f − k·fs\| com a amplitude \|H(f)\|, porque o filtro age antes da amostragem: estende a curva à banda de supraharmônicos sem aumentar a taxa e separa f0 de Q no ajuste (hoje correlação −0,87 com dados só até 45 kHz). Exige que o `calibrar_sonda.sh` aceite f > Nyquist e que o gerador de perfil procure o tom na frequência dobrada | Médio | Não |
| Repetições no T3 (`--repeticoes 3`) | Incerteza medida por ponto: o `relatorio/gerar_figuras.py` passa a fazer o ajuste ponderado e o χ² diz se o modelo explica os dados | Baixo (bancada) | Não |

**Pré-requisito:** a primeira calibração real foi feita (cadeia de tensão, T3, 2026-10-19:
`scripts/sondas/cadeia_tensao.json`). Falta a sonda de corrente (T10) e conferir a exatidão de um
perfil contra uma referência independente, em frequências fora da calibração (ver
`docs/contexto_projeto.md`, `status_validacao`).

**Impacto:** Alto para quem for analisar corrente. **Esforço:** variável (tabela). **Toca PRU
asm:** não.

---

### 2.12 🆕 Achados do datasheet e do código que a bancada precisa confirmar

Ao planejar o roteiro de laboratório (`docs/roteiro_laboratorio.md`), a leitura do datasheet do
ADS8688 e do `ler_adc.c` levantou três pontos. O primeiro já foi medido (T3, 2026-10-19): na cadeia de
tensão, um passa-baixa de 2ª ordem com f0 = 24,1 kHz, Q = 0,54 e **−3 dB em 17,3 kHz** (−12,5 dB em 45 kHz);
os outros dois continuam sem medição.

| Achado | Consequência | Proposta | Teste do roteiro |
|---|---|---|---|
| O ADS8688 tem um **filtro passa-baixa de 2ª ordem em cada canal, ~15 kHz a −3 dB** (seção 8.3.5, Fig. 55; −0,1 dB em 2,5 kHz) | Na banda de supraharmônicos o sinal chega ao conversor 15 a 40 dB menor (estimativa; 150 kHz: −33 a −40 dB). A correção devolve a amplitude e amplifica o ruído igualmente. O anti-aliasing é fraco para 200 a 500 kHz | Medir a resposta da cadeia de **tensão** com o mesmo fluxo da sonda (`calibrar_sonda.sh --grandeza tensao --ref-externa` + `gerar_perfil_sonda.py --referencia-externa`; feito no T3, `scripts/sondas/cadeia_tensao.json`) e registrá-la como "sonda" do canal de tensão; decidir sobre um anti-aliasing externo e sobre o teto de ganho da correção (2.11) | T3, T8 |
| A taxa real é `200 MHz ÷ ticks` com **divisão inteira**: 102 400 Hz gera 102 406,55 Hz (+64 ppm), 204 800 Hz +576 ppm, 300 000 Hz +1001 ppm; 100/200/250/400/500 kHz saem exatas | Todas as frequências medidas se deslocam pela mesma razão. O `adc_tool.py` usa a taxa **pedida** do cabeçalho | Recomendar taxas exatas; se T4 confirmar, usar `pru_clock_hz ÷ sample_period_ticks` por padrão no `adc_tool.py` (hoje só no `medir_captura.py --fs-pru`) e/ou medir o relógio da PRU | T4 |
| ENOB e THD do ADC não são medidos pelo sistema completo | Sem eles não há como separar o erro do ADC do erro do frontend/sonda | `medir_captura.py` (entregue) com o ADC em curto e com tons de baixa distorção | T1, T5 |

**Impacto:** Alto para a exatidão do perfil e da banda 50 a 150 kHz. **Esforço:** baixo (software);
a decisão sobre o filtro externo depende do resultado do T8. **Toca PRU asm:** não.

---

### 2.13 🆕 Faixa de entrada do ADC por canal (`--faixa-adc`): implementada, falta bancada

**O quê.** O ADS8688 tem uma faixa de entrada programável **por canal** (registradores `RANGE_SELn`): ±10,24 V
(padrão de reset), ±5,12 V ou ±2,56 V. Até aqui o firmware nunca os escrevia, e os canais de sinal pequeno (a saída
de uma sonda de corrente, de dezenas de mV a 1 V) ficavam com um degrau de 312,5 µV. Agora `ler_adc --faixa-adc
0:20.48,1:5.12` escolhe a faixa de cada canal, a PRU a escreve no ADC a cada captura e o cabeçalho (v3) a registra;
as ferramentas Python leem a faixa do cabeçalho (ver `docs/guia_de_uso.md`, "Faixa de entrada do ADC").

**Ganho esperado.** O erro de quantização em Volts cai na proporção da faixa (4x de ±10,24 V para ±2,56 V). O ruído do
próprio ADC cai menos (SNR típico 92, 91 e 89 dB nas três faixas, segundo o datasheet): meça no roteiro (T2).
O canal de **tensão** da rede não melhora: com o divisor de 0,0516, 127 V RMS dão 9,3 V de pico, 91% de ±10,24 V.

**O que ainda falta.** As capturas do T3 (2026-10-19) já saíram com cabeçalho v3, mas na faixa padrão
(±10,24 V), o que não prova que a PRU escreve `RANGE_SELn`; nenhuma captura registrada usou ±5,12 ou ±2,56 V:

1. Montar com `clpru` (`make` em `firmware/`) e carregar na PRU: o `spi_core.asm` foi validado só no simulador
   `tests/pru_sim.py` (lógica; não a sintaxe do `clpru` nem a temporização). O `.asm` passou de 1.822 para 1.841
   instruções (IMEM de 2.048): pouca folga.
2. Roteiro T0 (faixa de reset e VREF reais), T2 (ruído em cada faixa) e T10 (sonda de corrente em ±2,56 V).
3. Confirmar com o datasheet se a primeira conversão depois de trocar a faixa é válida (hoje nenhuma amostra é descartada).

**Impacto:** Médio–Alto para canais de sinal pequeno. **Esforço:** feito (software); bancada pendente. **Toca PRU asm:** sim —
só está pronto depois de compilado com `clpru` e validado no hardware.

---

## Parte 3 — Priorização sugerida

| # | Item | Impacto | Esforço | Toca PRU asm? | Status |
|---|------|---------|---------|----------------|--------|
| 2.11 | Fluxo de perfil de sonda: fase, subamostragem, perfil absoluto, hold-out | Alto (p/ corrente) | Variável | Não | 🆕 aberto (1ª calibração real feita no T3) |
| 2.13 | Faixa de entrada do ADC por canal (`--faixa-adc`): compilar com `clpru` e validar | Médio–Alto (canais de sinal pequeno) | Baixo (bancada) | Sim | 🆕 implementado, aguarda bancada |
| 2.12 | Filtro de 15 kHz do ADS8688 e taxa real (ticks inteiros): medir e decidir | Alto (banda 50–150 kHz) | Baixo | Não | 🆕 filtro medido (T3: −3 dB em 17,3 kHz); faltam T4 e T8 |
| 1.6 | Detecção/backpressure de overrun no ping-pong | Alto | Baixo–Médio | Sim (versões mais completas) | Aberto |
| 1.3 | Validar frequência pedida contra piso real | Alto | Baixo | Não | Aberto (depende de 1.2) |
| 1.2 | Instrumentar e medir onde o tempo por transação vai | Alto | Baixo | Sim (temporário) | Aberto — mais urgente após achado do item 1.1 |
| 1.4 | Revisar atrasos fixos com base no datasheet | Alto | Médio | Sim | Aberto |
| 1.8 (parte 2) | `SCHED_FIFO`/`mlockall()`, revisão do `usleep(2000)` | Alto | Baixo | Não | Aberto (metade já concluída) |
| 1.7 | Mais buffers dentro dos 16 MB já reservados | Médio–Alto | Médio | Sim | Aberto |
| 2.7 | `docs/licoes-aprendidas.md` + diagrama ARM↔PRU | Médio | Baixo | Não | Parcial (README, guia e arquitetura prontos) |
| 1.9 (asm) | Gerar `SAMPLES_PER_BUFFER` em vez de duplicar | Médio | Baixo–Médio | Sim (só geração) | Aberto |
| 2.4 | Hash do commit embutido no firmware/binário | Médio | Baixo | Não | Aberto |
| 2.5 | Testes de host do C e `make arm -Wextra` na CI | Médio | Baixo–Médio | Não | Parcial (Python + CI prontos) |
| 2.6 | `setup.sh` com checagem automática de estado | Médio | Baixo | Não | Aberto |
| 1.10 | Confirmar isolador (ADuM3150) contra BOM + test points | Baixo–Médio | Baixo–Médio | Não (hardware) | Aberto, causa raiz já resolvida |
| 1.9 (python) | Sync `ADS8688_MAX_CANAIS` C/Python | Baixo–Médio | Baixo | Não | Mitigado por `test_contrato_firmware.py` |

**Concluído** (fora da tabela acima, já não precisa de ação): 1.5 (modo automático
AUTO_RST), 1.8 — checagem de `fwrite()` e `--blocos`/`--duracao`, 1.10 — causa raiz do bug de
saturação, 2.1 — remoção de `backup pre-assembly/`, 2.2 — `.gitignore`, 2.3 — metadados via
cabeçalho embutido, 2.8 — nome `adc_tool.py`, 2.9 — `set_date.sh` sem senha, 2.10 — `calibrar_sonda.sh` reescrito, 1.5 — comentário de `spi_core.asm`. Desde 2026-10, também: o código Python virou
um pacote com testes e CI (2.5, parte Python), e o cabeçalho v2 com as ferramentas de
calibração de sondas.

**Sugestão de ordem de ataque:** o `calibrar_sonda.sh` já rodou numa bancada real (T3); o próximo
passo do fluxo de sondas é a **sonda de corrente (T10)**, pré-requisito do 2.11. Em seguida, os itens
puramente do lado ARM/C e de processo (1.8 restante, 1.3, 2.4–2.6) — baixo risco, ganho
imediato de robustez e de apresentação do repositório. Em paralelo, confirmar o isolador
contra o BOM (1.10) para fechar de vez esse item. Só depois disso partir para a medição
(1.2) e os ajustes de timing na PRU (1.2 → 1.4), já que a medição de 1.2 também resolve a
divergência de números encontrada no item 1.1. O backpressure do ping-pong (1.6) continua
sendo o item de maior impacto isolado e pode ser atacado em paralelo à medição de timing,
já que são mudanças independentes uma da outra.

---

## Notas finais

Nenhuma sugestão de Assembly/PRU acima deve ser considerada pronta sem passar pelo
mesmo processo já em uso no projeto: compilar com `clpru` e validar em hardware real
antes de qualquer merge para o caminho de produção. Da mesma forma, qualquer mudança que
toque o formato de captura de 1 canal precisa preservar compatibilidade
byte-a-byte com o comportamento atual, já que isso é um requisito consolidado do
projeto — como já demonstrado pela migração para o modo automático (item 1.5), que
preservou esse formato apesar de reescrever o protocolo SPI por baixo.
