# Notas para Apresentação e Relatório Final — SH-Analyzer

> **Para que serve este documento:** um bloco de anotações cronológico do
> que foi feito desde a última apresentação para a equipe, escrito para
> você não esquecer os detalhes na hora de apresentar nem na hora de
> escrever o relatório final. Não é o texto final de nenhum dos dois — é a
> matéria-prima. Preencha os `[ ]` e os "⚠️ confirme com você mesmo" com o
> que você lembrar; o que está descrito sem essa marcação vem direto do
> código-fonte e dos testes já registrados, então pode usar com confiança.
>
> Última atualização: 07/09/2026 — cobre desde a última apresentação (placa
> ainda sem Assembly, modo manual, sem `adc_tool.py`, sem multi-canal) até a
> validação do modo automático multi-canal.

---

## 0. Como usar isto

1. Leia a linha do tempo (seção 2) de ponta a ponta uma vez, só para
   reativar a memória.
2. Preencha os itens marcados **⚠️ confirme com você mesmo** — são coisas
   que eu não tenho como saber com certeza (datas exatas, o que você viu na
   tela na hora do bug, fotos que você tirou).
3. Rode `git log --oneline --all` no repositório — os commits (mesmo que
   as mensagens sejam curtas) vão te dar as datas reais de cada marco, e
   ajudam a reconstruir a ordem exata se algo aqui estiver fora de ordem.
4. Vá marcando os `[ ]` de imagens conforme for gerando cada print/foto —
   no fim, a seção 5 tem a lista consolidada de tudo que falta capturar.
5. Use a seção 6 como esqueleto para montar os slides, e a seção 7 como
   esqueleto para o relatório final.

---

## 1. Contexto rápido (para não travar na primeira pergunta)

- **Projeto:** SH-Analyzer — instrumento para medir supraharmônicos
  (ruído de dezenas de kHz) em redes elétricas, algo que analisadores de
  QEE comerciais não enxergam bem.
- **Por que importa:** conversores eletrônicos de potência (fontes
  chaveadas, inversores, etc.) estão cada vez mais presentes na rede e
  introduzem esse tipo de ruído — é um problema de qualidade de energia
  que está crescendo e pouco instrumentado.
- **Sua parte:** projetar e validar o instrumento de medição em si
  (hardware + firmware de aquisição), não a análise de supraharmônicos em
  si (isso vem depois, com dados de bancada validados).
- **Onde a última apresentação parou:** protótipo em C puro rodando
  direto no Linux da BeagleBone (sem PRU), ADS8688 em modo manual, 1 canal
  só, sem ferramenta de análise própria — provavelmente scripts avulsos ou
  inspeção manual dos dados.
- **Onde está agora:** firmware reescrito em Assembly rodando na PRU
  (determinístico, sem depender do escalonador do Linux), ADS8688 em modo
  automático (varredura sem reenviar comando a cada amostra), captura
  multi-canal validada em hardware (5 canais testados), e uma ferramenta
  Python própria (`adc_tool.py`) com FFT sem vazamento espectral,
  filtragem digital e suporte multi-canal completo.

---

## 2. Linha do tempo cronológica

### Marco 1 — Por que sair do protótipo em C puro

**O que motivou:** o protótipo original em C puro rodava direto no
processador ARM sob Linux — um sistema operacional de propósito geral, sem
garantias de tempo real (a pasta com esse código já foi removida do
repositório, mas o comportamento dele segue documentado aqui e no
`docs/contexto_projeto.md`). Isso limitava a taxa de amostragem estável a
algo em torno de **102,4 kHz**, provavelmente por jitter de escalonamento
(o kernel podia interromper o laço de aquisição a qualquer momento para
atender outras tarefas).

**Decisão:** mover o laço crítico de tempo (bit-banging SPI) para a **PRU**
— um coprocessador dedicado, sem sistema operacional, que executa
instruções de forma totalmente determinística. Isso significou reescrever
o núcleo de aquisição em **Assembly** (a PRU não roda C de forma eficiente
o bastante para bit-banging tão apertado no tempo).

- [ ] ⚠️ **Confirme com você mesmo:** você tem alguma captura/print do
      protótipo em C mostrando o limite de 102,4 kHz sendo estourado
      (dados corrompidos acima disso)? Se tiver, é uma imagem forte para
      justificar a decisão de reescrever em Assembly.

---

### Marco 2 — Reescrita do laço crítico em Assembly (PRU)

Essa foi a parte mais difícil e a que você mencionou lembrar menos em
detalhe — mas o próprio código-fonte (`spi_core.asm`) documenta os
problemas que foram resolvidos, então aqui está o resumo confiável:

**Problema 1 — leitura presa em "fundo de escala".** O ADC retornava
sempre o valor máximo possível, independente da tensão real de entrada,
mesmo com a comunicação SPI aparentemente correta.

**Diagnóstico e correção:** duas mudanças combinadas resolveram:
1. A escrita do bit de comando (MOSI) foi feita com desvio condicional
   (replicando o `if/else` da versão em C original) — uma versão
   "branchless" (com deslocamentos de bits e máscaras, sem desvio
   condicional) **não funcionou na prática**, mesmo sendo logicamente
   equivalente. Isso sozinho já é um ponto interessante para o relatório:
   nem sempre a versão "mais elegante" em código funciona igual em
   hardware real, timing importa.
2. O bit de dado (MISO) passou a ser amostrado no **último instante seguro
   antes da borda de descida do SCLK** — o máximo de tempo possível para o
   sinal se acomodar dentro do período em que o SCLK está alto. Foi essa
   mudança, combinada com a anterior, que resolveu a leitura presa.

**Problema 2 — capturas longas travavam sozinhas.** O registrador `CYCLE`
da PRU (contador de ciclos usado para temporizar as amostras) **trava** ao
estourar 32 bits (~21,47 s a 200 MHz) em vez de dar a volta e continuar
contando. Sem ressincronizar esse contador periodicamente, qualquer
captura mais longa que ~21 segundos parava de funcionar.

**Correção:** o contador é zerado manualmente no início da aquisição e a
cada troca de buffer (ping-pong, ver Marco 3).

**Problema 3 — orçamento de instruções (`PRU_IMEM`).** A PRU só tem 8 KB de
memória de instruções. Para controlar a velocidade do SPI sem estourar
esse limite, o firmware usa **laços de atraso** (contagem regressiva) em
vez de sequências de `NOP` repetidas — um `NOP` por ciclo desperdiçado
custa 1 instrução de código; um laço de atraso custa poucas instruções e
pode "esperar" qualquer número de ciclos.

- [ ] ⚠️ **Confirme com você mesmo:** quanto tempo (aproximadamente) levou
      essa etapa? Foi a mais demorada do projeto? Vale mencionar na
      apresentação como "custo" real de migrar para Assembly, mesmo tendo
      valido a pena depois.
- [ ] Print/diagrama do timing CMD_BIT/DATA_BIT (comando vs. leitura, e o
      instante exato de amostragem do MISO) — posso gerar esse diagrama
      para você se quiser algo visual aqui, é um bom slide técnico.

---

### Marco 3 — Ping-pong e estrutura de memória compartilhada

**Por que ping-pong:** para gravar continuamente sem parar a aquisição —
enquanto um buffer na DDR está sendo preenchido pela PRU, o outro fica
disponível para o ARM esvaziar (gravar em disco).

**Como a sincronização funciona:** uma struct `shared_control` numa região
de RAM interna da PRU-ICSS, com campos como `config_ready` (handshake
inicial), `buffer_0_ready`/`buffer_1_ready` (PRU avisa que um buffer
encheu), e os endereços físicos dos buffers na DDR reservada (16 MB fora
do alcance do Linux, hoje só 4 MB usados).

**Você mencionou que essa estrutura mudou mais de uma vez** — pelo
histórico do projeto, pelo menos estas revisões existiram:
1. Versão original, 1 canal só.
2. Expansão para multi-canal em **modo manual**: adicionou `num_canais` +
   uma tabela `comandos_canais[8]` (um comando de 32 bits por canal,
   percorrida em round-robin pela PRU) — struct de 64 bytes.
3. **Simplificação para modo automático** (mudança mais recente, coberta
   em detalhe no Marco 6): a tabela inteira foi substituída por um único
   campo, `auto_seq_mask` (uma máscara de bits) — struct caiu para 32
   bytes, porque a PRU não precisa mais saber a ordem/quantidade de
   canais, só quais estão habilitados (o próprio ADC decide a ordem).

- [ ] ⚠️ **Confirme com você mesmo:** existiu alguma revisão da struct
      ENTRE a (1) e a (2) que não está documentada? Se sim, vale uma linha
      aqui.
- [ ] Diagrama comparando as 3 versões da struct lado a lado (tamanho,
      campos) — bom para mostrar simplificação progressiva como sinal de
      maturidade do projeto, não de instabilidade.

---

### Marco 4 — Problema de integridade de sinal (jumpers longos)

**Sintoma:** saturação SPI — leitura constante em fundo de escala,
independente da tensão real de entrada, mesmo em velocidades **bem mais
lentas** que o firmware original (que funcionava). Isso é um sinal
clássico de problema elétrico, não de lógica/protocolo.

**Diagnóstico:** foi criado um firmware de diagnóstico separado
(`spi_core_diagnostico_preambulo.asm`) que capturava os 16 bits de
"preâmbulo" de cada quadro SPI — bits que, pelo protocolo, deveriam ser
sempre zero. Um script dedicado (`scripts/analisar_preambulo.py`) analisou
esses preâmbulos e encontrou um **padrão de transição consistente**,
característico de problema de integridade de sinal (reflexo, ruído
induzido, ou assimetria de tempo de subida/descida em algum componente do
caminho do sinal).

**Causa raiz e correção:** os **jumpers longos** usados para ligar a placa
de aquisição ao frontend analógico na bancada. Corrigido eliminando os
jumpers e conectando as placas diretamente.

**Por que isso é um bom ponto para o relatório:** mostra um processo de
depuração sistemático — sintoma → ferramenta de diagnóstico criada
especificamente para isolar a causa → hipótese → teste da hipótese
(remover jumpers) → confirmação. É exatamente o tipo de raciocínio de
engenharia que um relatório científico deve documentar, não só o resultado
final.

- [ ] ⚠️ **Confirme com você mesmo:** você tem o gráfico de saída do
      `analisar_preambulo.py` mostrando o padrão de erro? **Essa é
      provavelmente a imagem mais valiosa deste marco** — mostra o
      problema sendo diagnosticado de forma quantitativa, não só "eu achei
      que era isso".
- [ ] Foto do setup com os jumpers longos (antes) e das placas conectadas
      diretamente (depois) — comparação visual simples e direta.
- [ ] Se possível, uma captura de forma de onda mostrando a saturação
      (antes) vs. uma medição limpa (depois) no mesmo canal/condição.

---

### Marco 5 — Ferramenta de análise Python (`adc_tool.py`)

**Por que foi necessário, mesmo não sendo formalmente parte do seu papel
na IC:** sem uma ferramenta própria de conversão/plotagem/FFT, não havia
como verificar se o hardware e o firmware estavam de fato medindo
corretamente — cada problema de hardware/firmware que precisou ser
diagnosticado (integridade de sinal, alinhamento multi-canal, etc.)
motivou uma nova função de análise. A ferramenta cresceu organicamente a
partir de necessidades reais de depuração, não foi planejada do zero como
está hoje.

**Evolução:** começou como `plot_adc.py` (só plotagem) e foi renomeada
para `adc_tool.py` quando ganhou o modo de conversão `.bin`↔`.csv` e deixou
de ser só uma ferramenta de visualização.

**Capacidades hoje:**
- Conversão `.bin` ↔ `.csv` (streaming, não carrega arquivos grandes
  inteiros na memória).
- FFT **sem vazamento espectral**, com uma estratégia de 5 passos:
  1. Estimativa grosseira da frequência fundamental (FFT + janela Hann).
  2. Filtro passa-baixa Butterworth para isolar a fundamental.
  3. Cruzamentos por zero ascendentes, **interpolados linearmente** (não
     presos à grade de amostragem).
  4. Refinamento do período usando todos os ciclos disponíveis (dilui o
     erro de medição).
  5. Corte do trecho analisado em um número **inteiro** de ciclos antes da
     FFT principal — ataca a causa raiz do vazamento espectral, em vez de
     só aplicar uma janela para mascará-lo.
- Múltiplas janelas espectrais (retangular, Hann, Blackman-Harris,
  flattop, Kaiser).
- Suporte multi-canal completo: FFT independente por canal, calibração
  (faixa/ganho/offset) por canal, layout de plotagem configurável.
- Filtragem digital opcional (Butterworth passa-baixa/passa-alta, fase
  zero via `sosfiltfilt`).

**Por que vale destacar isso na apresentação:** a estratégia de FFT sem
vazamento (passo 5, em particular) é um detalhe metodológico que mostra
rigor — é fácil fazer uma FFT "de qualquer jeito" e ter artefatos de
vazamento espectral contaminando a leitura de amplitude dos
supraharmônicos, que são exatamente o que você está tentando medir com
precisão.

- [ ] Print de uma FFT real (idealmente da medição mais recente, com modo
      automático) mostrando a fundamental de 60 Hz limpa, com pouco/nenhum
      vazamento espectral visível ao redor.
- [ ] ⚠️ **Confirme com você mesmo:** vale mostrar um exemplo "antes/depois"
      da técnica de corte em ciclos inteiros (FFT com vazamento vs. sem)?
      Se você tiver esse comparativo salvo de quando desenvolveu a
      funcionalidade, é um ótimo slide para o professor — ele vai
      reconhecer a relevância técnica imediatamente.

---

### Marco 6 — Migração para modo automático (AUTO_RST) do ADS8688

Esta é a parte mais recente do trabalho — a mais fresca na memória, e
provavelmente a que mais impressiona tecnicamente, porque foi feita com
processo de validação completo e documentado.

**Motivação:** em modo manual, o firmware reenviava um comando de seleção
de canal a **cada amostra**, mesmo quando os canais não mudam durante a
captura (caso de 1 canal só) ou seguem sempre a mesma sequência (caso
multi-canal já implementado). O modo automático do ADS8688 (`AUTO_RST`)
elimina esse reenvio: o host programa a sequência de canais **uma única
vez**, e o próprio ADC avança de canal sozinho a cada amostra.

**O que mudou tecnicamente:**
- A struct `shared_control` foi simplificada (64 → 32 bytes, ver Marco 3).
- O índice de canal round-robin, mantido em software pela PRU no modo
  manual multi-canal, foi removido — o ADS8688 agora faz esse trabalho
  sozinho, em hardware, sempre varrendo em **ordem crescente** de canal.
- Bônus identificado (ainda não medido com osciloscópio): como o comando
  enviado a cada amostra agora é sempre zero (`NO_OP`), o pino MOSI fica
  eletricamente parado durante a fase de comando — uma fonte a menos de
  chaveamento digital potencialmente acoplado à cadeia analógica sensível,
  relevante justamente porque este projeto mede ruído de alta frequência.

**Problema 1 — erro de compilação.** Ao tentar compartilhar as duas
transações de configuração (escrita de registrador + comando de início)
num único laço de Assembly, o compilador (`clpru`) recusou com o erro
`Offset must be between -512L and 511L`. Causa: as instruções de desvio
condicional "rápido" da PRU só conseguem pular uma distância limitada
(±511 posições); o corpo do laço (uma transação SPI inteira) era grande
demais. Corrigido trocando o salto de volta por um salto incondicional
(sem esse limite), mantendo só o teste de condição como um salto curto.

**Verificação de orçamento de memória:** conferido o arquivo `.map` gerado
pela compilação — o código coube com folga (~67% dos 8 KB de `PRU_IMEM`
usados, ~33% livres).

**Problema 2 — bug real de hardware, não só de compilação.** A primeira
tentativa de captura multi-canal saiu com todos os canais **idênticos**
entre si, replicando exatamente o padrão de um teste anterior de canal
único mal interpretado como multi-canal. Isso indicava que a varredura
automática nunca avançava de canal de verdade — o ADC ficava preso num
único canal a captura inteira.

**Causa raiz:** a escrita do registrador de programa `AUTO_SEQ_EN`
(responsável por dizer ao ADC quais canais fazem parte da varredura) usava
32 ciclos de relógio SPI, tratando essa escrita como se fosse uma
transação normal de comando/leitura. O datasheet do ADS8688, porém, exige
**24 ciclos** para esse tipo específico de escrita (16 do comando + 8
adicionais) — confirmado cruzando o datasheet com o driver oficial do
ADS8688 no kernel Linux e uma resposta de suporte da própria Texas
Instruments no fórum de suporte, identificando exatamente o mesmo erro em
outro projeto. Os 8 ciclos a mais, com o CS ainda ativo, corrompiam a
escrita da máscara de canais.

**Resultado após a correção:** teste com 5 canais (0 a 4), sendo 1 e 3
fisicamente conectados à tensão da rede e 0, 2 e 4 deixados desconectados
de propósito — os canais 1 e 3 mostraram a onda de 60 Hz esperada, e os
canais 0, 2 e 4 mostraram apenas ruído, confirmando que a varredura
automática está de fato alternando entre canais corretamente.

**Por que este marco é um bom "case" para o relatório e a apresentação:**
tem todos os elementos de um processo de engenharia/depuração bem
conduzido — hipótese técnica, implementação, teste, sintoma inesperado,
investigação com fontes primárias (datasheet + driver de referência +
suporte do fabricante), correção, e nova validação confirmando o
resultado esperado. É exatamente esse tipo de raciocínio que demonstra
competência para um orientador como o professor Pomilio.

- [ ] **[PRIORIDADE ALTA]** Print do terminal com a saída completa do
      `ler_adc` capturando os 5 canais (mostra a interface/uso da
      ferramenta).
- [ ] **[PRIORIDADE ALTA]** Gráfico do `adc_tool.py` com os 5 canais lado a
      lado (ou sobrepostos) — 2 mostrando 60 Hz, 3 mostrando só ruído. Esta
      é provavelmente **a imagem mais importante de toda a apresentação**:
      é a evidência visual direta de que o modo automático multi-canal
      funciona corretamente.
- [ ] Se ainda tiver os dados da primeira tentativa (com o bug): o mesmo
      gráfico ANTES da correção, com os 5 canais idênticos — o contraste
      antes/depois é uma forma muito eficaz de contar a história do bug
      sem precisar de muito texto no slide.
- [ ] Print do `.map` do `PRU_IMEM` (opcional, mais técnico — bom para o
      relatório, dispensável na apresentação de 1h a menos que sobre
      tempo).

---

### Marco 7 — O que falta (mostrar isso é tão importante quanto mostrar o que já foi feito)

- **Validação quantitativa em bancada controlada:** a validação atual
  (Marco 6) é **qualitativa** — confirma que os canais se comportam de
  forma diferente e plausível (sinal vs. ruído), mas não confirma que a
  amplitude e a frequência medidas são numericamente exatas. O próximo
  passo real é gerar um sinal/ruído de frequência e amplitude conhecidas
  numa bancada controlada, medir com o SH-Analyzer, e comparar o espectro
  medido contra o que foi efetivamente injetado.
- Margens de tempo do sinal de CS (chip-select) em torno das transações
  SPI seguem calibradas empiricamente, sem comparação formal com os
  tempos mínimos exigidos pelo datasheet do ADS8688 — possível fonte de
  ganho de frequência máxima ainda não explorada.
- Risco documentado (não mitigado): a troca de buffer no esquema
  ping-pong não verifica se o processador principal já terminou de
  processar o buffer anterior antes de começar a sobrescrevê-lo — pode
  causar corrupção silenciosa em frequências mais altas.

Terminar a apresentação com essa seção — de forma objetiva, sem soar como
desculpa — mostra que você sabe exatamente onde o projeto está e para
onde ele vai. É exatamente o tipo de clareza que um orientador quer ver.

---

## 3. Resumo em uma frase por marco (para revisão rápida antes da apresentação)

1. Protótipo em C puro limitava a taxa de amostragem a ~102,4 kHz por
   rodar sob um sistema operacional de propósito geral.
2. Reescrita em Assembly na PRU resolveu isso, mas exigiu resolver bugs de
   timing bit-a-bit (leitura presa em fundo de escala) e de estouro de
   contador (capturas longas travando).
3. A estrutura de memória compartilhada entre ARM e PRU evoluiu 3 vezes,
   cada vez mais simples, acompanhando a evolução do protocolo do ADC.
4. Um bug de saturação SPI foi rastreado, com uma ferramenta de
   diagnóstico dedicada, até jumpers longos na bancada — corrigido
   conectando as placas diretamente.
5. Foi necessário desenvolver uma ferramenta própria de análise em Python
   (`adc_tool.py`) para poder validar hardware e firmware, e ela cresceu
   até incluir FFT sem vazamento espectral e suporte multi-canal completo.
6. A migração para o modo automático do ADS8688 eliminou o reenvio de
   comando por amostra, passou por um bug real de protocolo (24 vs. 32
   ciclos na escrita de registrador) identificado com fontes primárias, e
   foi validada em hardware com 1 e com 5 canais simultâneos.
7. O próximo passo é validação quantitativa com sinal conhecido injetado
   em bancada controlada.

---

## 4. Checklist consolidado de imagens/capturas

- [ ] (Marco 1) Captura do protótipo em C mostrando o limite de 102,4 kHz
- [ ] (Marco 2) Diagrama de timing CMD_BIT/DATA_BIT (posso gerar)
- [ ] (Marco 3) Diagrama comparando as 3 versões da struct `shared_control`
- [ ] (Marco 4) Gráfico de saída do `analisar_preambulo.py`
- [ ] (Marco 4) Foto do setup com jumpers longos vs. placas conectadas direto
- [ ] (Marco 4) Forma de onda saturada vs. limpa
- [ ] (Marco 5) FFT limpa de uma medição real (60 Hz)
- [ ] (Marco 5) Comparativo FFT com/sem a técnica de corte em ciclos inteiros
- [ ] (Marco 6) **[PRIORIDADE ALTA]** Terminal do `ler_adc` com 5 canais
- [ ] (Marco 6) **[PRIORIDADE ALTA]** Gráfico dos 5 canais (2 com sinal, 3 com ruído)
- [ ] (Marco 6) Gráfico do bug (5 canais idênticos), se ainda tiver os dados
- [ ] (Marco 6) Print do `.map` do `PRU_IMEM` (opcional)

---

## 5. Sugestão de estrutura para a apresentação (1 hora)

Uma apresentação puramente cronológica tende a enterrar o resultado mais
importante (a validação multi-canal) no final, depois de 50 minutos de
detalhes de implementação. Considere uma estrutura que abre com o
resultado e usa a cronologia para explicar como você chegou lá:

1. **Abertura (5 min):** onde o projeto estava na última apresentação,
   onde está agora, em uma frase cada.
2. **Arquitetura atual (10 min):** PRU + ARM, ping-pong, modo automático —
   o "como funciona hoje", sem entrar ainda nos bugs/histórico.
3. **Evidência de que funciona (10 min):** o gráfico dos 5 canais (Marco
   6) — mostre isso cedo, é o seu resultado mais forte.
4. **Jornada técnica — principais desafios e como foram resolvidos
   (25 min):** aqui entra a cronologia (Marcos 2, 4 e 6 em mais detalhe) —
   mas contada como "aqui estão os problemas reais de engenharia que
   apareceram e como cada um foi diagnosticado e resolvido", não como uma
   lista de eventos.
5. **Próximos passos (5 min):** Marco 7 — validação quantitativa,
   melhorias de desempenho identificadas mas não implementadas.
6. **Perguntas (5 min).**

## 6. Sugestão de estrutura para o relatório final (formato artigo)

- **Introdução:** contexto de supraharmônicos, lacuna nos analisadores de
  QEE convencionais, objetivo do instrumento.
- **Arquitetura do sistema:** hardware (frontend analógico, isolamento
  galvânico) + firmware (PRU/ARM, ping-pong, modo automático).
- **Metodologia:** decisões técnicas específicas e a justificativa de cada
  uma — por que PRU em vez de C puro, por que modo automático em vez de
  manual, por que a técnica de FFT sem vazamento espectral.
- **Validação e Resultados:** a validação multi-canal atual (qualitativa)
  e, assim que disponível, a validação quantitativa com sinal conhecido
  (Marco 7) — esta seção é o coração científico do relatório.
- **Discussão/Limitações:** riscos e itens ainda em aberto (backpressure
  do ping-pong, margens de CS não comparadas ao datasheet) — mostrar que
  você conhece os limites do próprio trabalho é parte de escrever um bom
  relatório.
- **Conclusão e Trabalhos Futuros:** aumento de frequência, diagnóstico de
  gargalo, expansão do uso da DDR reservada.