# SH-Analyzer — Sugestões de Melhoria

> Documento de revisão técnica cobrindo (1) o que pode ser feito para suportar taxas de
> amostragem maiores sem corromper dados, considerando firmware e hardware, e (2)
> reorganização/profissionalização do repositório para uso em portfólio. Cada item indica
> **Impacto** (no desempenho/robustez ou na qualidade do projeto) e **Esforço** estimado,
> além de sinalizar quando a mudança toca o Assembly da PRU — que, pelo princípio já
> adotado no projeto, só deve ser considerada "pronta" depois de compilada com `clpru` e
> validada em hardware real.
>
> **Nota desta revisão:** a revisão anterior deste documento excluía `scripts/adc_tool.py`
> do escopo, a pedido; esta revisão é uma reanálise completa do projeto e passa a cobrir
> o script também. Boa parte do que era só proposta na revisão anterior já foi
> implementada (em alguns casos, de forma diferente e melhor do que o que havia sido
> sugerido) — cada item abaixo traz seu status atualizado. Um resumo rápido:

| Status | Itens |
|---|---|
| ✅ **Concluído** | 1.5 (modo automático AUTO_RST), 1.8 (parcial: checagem de `fwrite()` + `--blocos`/`--duracao`), 1.10 (parcial: causa raiz da saturação — jumpers), 2.1 (parcial: `backup pre-assembly/` removido), 2.2 (`.gitignore`), 2.3 (metadados — via cabeçalho embutido, não sidecar) |
| 🆕 **Novo nesta revisão** | Nome de arquivo `Adc_tool.py` vs. `adc_tool.py` (quebra os comandos documentados em sistema de arquivos sensível a maiúsculas/minúsculas), aviso obsoleto no cabeçalho de `spi_core.asm`, credencial em texto plano em `scripts/set_date.sh`, `ADS8688_MAX_CANAIS` agora também duplicado em Python |
| 🔄 **Ainda aberto, com nota atualizada** | 1.1–1.4 (o "piso" antigo de ~48 kHz parece estar desatualizado — ver nota abaixo), 1.6, 1.7, 1.9 (revisado), 2.4, 2.5, 2.6, 2.7 |

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

**Follow-up de higiene encontrado nesta revisão:** o cabeçalho de comentários no topo de
`spi_core.asm` ainda traz o aviso "⚠️ AINDA NÃO VALIDADO EM HARDWARE... tratar como
experimento isolado nesta branch... antes de fazer merge na main" — e referencia um nome
de arquivo de contexto antigo (`Contexto do Projeto-3.md`), de antes da convenção de nome
fixo (`docs/contexto_projeto.md`, sem sufixo de versão) adotada a partir desta mesma
migração. Esse aviso está desatualizado e **é internamente inconsistente com o resto do
próprio arquivo**: mais abaixo, o mesmo arquivo documenta o bug de 24 vs. 32 ciclos como
"observado em hardware" — o que só é possível se o código já tivesse sido testado na PRU
física, contradizendo o aviso do topo. Recomenda-se atualizar esse comentário para
refletir o status real (validado, com o histórico de bug/correção como veio a ser), tanto
por clareza para quem ler o código depois quanto porque um avaliador/recrutador lendo
`spi_core.asm` diretamente hoje sairia com a impressão errada de que um código
experimental e não testado está em produção.

**Impacto:** Alto (multi-canal com menos overhead por canal, MOSI parado durante a fase de
comando). **Esforço do follow-up de comentário:** Trivial. **Toca PRU asm:** sim (o
follow-up é só o comentário, não a lógica).

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
> (`spi_core_diagnostico_preambulo.asm` + `analisar_preambulo.py`) e corrigida conectando
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

**Ainda em aberto:** `docs/datasheets/`, `docs/architecture.md`,
`docs/licoes-aprendidas.md` e `firmware/tests/` — nenhum desses foi criado ainda (ver
itens 2.5 e 2.7 abaixo para o detalhamento de cada um).

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

Boa parte da disciplina de validação já existe no projeto — mas informalmente, não como
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
**Esforço:** Baixo-Médio. **Status:** ainda em aberto.

---

### 2.6 `setup.sh` mais defensivo

Sem mudanças desde a última revisão — o script ainda tem só o comentário avisando sobre o
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

- **`docs/architecture.md`** — ainda não criado como arquivo separado, embora
  `docs/contexto_projeto.md` já cumpra boa parte desse papel de referência hoje. Um
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
ainda em aberto.

---

### 2.8 🆕 Nome de arquivo `Adc_tool.py` — inconsistência que quebra os comandos documentados

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

### 2.9 🆕 Credencial em texto plano em `scripts/set_date.sh`

`scripts/set_date.sh` (sincroniza a data/hora local para a BeagleBone, mitigando a
ausência de RTC com bateria mencionada em `ler_adc.c`) autentica via SSH usando `sshpass`
com uma senha **hardcoded em texto plano** no próprio script versionado
(`PASSWORD="temppwd"`). Mesmo sendo uma senha de laboratório de baixo risco, é um hábito
que vale corrigir antes de tratar este repositório como peça de portfólio público — um
avaliador ou recrutador lendo o código vê uma credencial exposta em texto plano no
histórico do Git.

**Sugestão:** trocar autenticação por senha (`sshpass`) por **autenticação por chave SSH**
entre a máquina de desenvolvimento e a BeagleBone — elimina tanto a senha hardcoded quanto
a própria dependência de `sshpass`, e é o padrão razoável para um par de máquinas
confiáveis usado repetidamente (exatamente o caso de uso deste script). Se uma senha
ainda for necessária por algum motivo, uma alternativa mínima é lê-la de uma variável de
ambiente ou de um arquivo à parte listado no `.gitignore`, nunca hardcoded no script.

**Impacto:** Médio (segurança/higiene, relevante para portfólio público). **Esforço:**
Baixo (gerar/copiar uma chave SSH já resolve; remover a linha do `sshpass`). **Toca PRU
asm:** não.

---

## Parte 3 — Priorização sugerida

| # | Item | Impacto | Esforço | Toca PRU asm? | Status |
|---|------|---------|---------|----------------|--------|
| 2.8 | Renomear `Adc_tool.py` → `adc_tool.py` | Alto | Trivial | Não | 🆕 aberto |
| 1.6 | Detecção/backpressure de overrun no ping-pong | Alto | Baixo–Médio | Sim (versões mais completas) | Aberto |
| 1.3 | Validar frequência pedida contra piso real | Alto | Baixo | Não | Aberto (depende de 1.2) |
| 1.2 | Instrumentar e medir onde o tempo por transação vai | Alto | Baixo | Sim (temporário) | Aberto — mais urgente após achado do item 1.1 |
| 1.4 | Revisar atrasos fixos com base no datasheet | Alto | Médio | Sim | Aberto |
| 1.8 (parte 2) | `SCHED_FIFO`/`mlockall()`, revisão do `usleep(2000)` | Alto | Baixo | Não | Aberto (metade já concluída) |
| 1.7 | Mais buffers dentro dos 16 MB já reservados | Médio–Alto | Médio | Sim | Aberto |
| 2.7 | `docs/architecture.md` + lições aprendidas | Médio–Alto | Baixo–Médio | Não | Aberto |
| 2.9 | Credencial em texto plano em `set_date.sh` | Médio | Baixo | Não | 🆕 aberto |
| 1.9 (asm) | Gerar `SAMPLES_PER_BUFFER` em vez de duplicar | Médio | Baixo–Médio | Sim (só geração) | Aberto |
| 2.4 | Hash do commit embutido no firmware/binário | Médio | Baixo | Não | Aberto |
| 2.5 | Formalizar testes sintéticos em `pytest` + CI leve | Médio | Baixo–Médio | Não | Aberto |
| 2.6 | `setup.sh` com checagem automática de estado | Médio | Baixo | Não | Aberto |
| 1.10 | Confirmar isolador (ADuM3150) contra BOM + test points | Baixo–Médio | Baixo–Médio | Não (hardware) | Aberto, causa raiz já resolvida |
| 1.9 (python) | Sync `ADS8688_MAX_CANAIS` C/Python | Baixo–Médio | Baixo | Não | Aberto, baixo risco |
| 1.5 (comentário) | Corrigir aviso obsoleto no topo de `spi_core.asm` | Baixo (clareza) | Trivial | Sim (só comentário) | 🆕 aberto |

**Concluído desde a última revisão** (fora da tabela acima, já não precisa de ação): 1.5
(modo automático AUTO_RST), 1.8 — checagem de `fwrite()` e `--blocos`/`--duracao`, 1.10 —
causa raiz do bug de saturação, 2.1 — remoção de `backup pre-assembly/`, 2.2 —
`.gitignore`, 2.3 — metadados via cabeçalho embutido.

**Sugestão de ordem de ataque:** o item 2.8 (renomear o arquivo) é trivial e deveria ser o
primeiro commit desta rodada, independente de tudo o mais. Em seguida, os itens que são
puramente do lado ARM/C e de processo (1.8 restante, 1.3, 2.4–2.9) — baixo risco, ganho
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
