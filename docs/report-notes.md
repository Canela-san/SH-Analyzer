# Notas para o Relatório e as Apresentações — SH-Analyzer

> **Para que serve.** É a matéria-prima de dois produtos: o **relatório científico** da IC (FAPESP, processo 2025/22891-1; o 1º relatório, de 01/11/2025 a 30/06/2026, está em [`fapesp/partial-report-2026-06.pdf`](fapesp/partial-report-2026-06.pdf)) e as **apresentações quinzenais** ao orientador (Prof. Dr. José Antenor Pomilio). Não é o texto final de nenhum dos dois.
>
> **Grau de confiança.** O que está sem marca vem do código, dos testes ou dos dados medidos e pode ser citado. O que tem ⚠️ depende da sua memória e precisa ser conferido. Os `[ ]` são imagens ou dados que ainda faltam.
>
> **Última atualização:** 22/10/2026. Cobre de jul/2026 (início do Assembly) até os resultados de bancada de 19/10 (Marcos 12 e 14), a revisão do firmware (Marco 13), a varredura das esperas do CS e da taxa de 21/10 (Marco 15) e a grade de tempo, o quadro que dependia do dado e o T3 até 140 kHz (Marco 16). Os achados de engenharia que não são matéria de relatório (robustez, higiene de código, organização do repositório) estão em [`improvement-proposals.md`](improvement-proposals.md).

---

## 0. Como Usar Este Documento

| Para... | Use |
|---|---|
| **Escrever o relatório** | A [seção 6](#6-estrutura-sugerida-para-o-relatório-final) (capítulo a capítulo, com o que entra em cada um), a [seção 1.1](#11-ponte-com-o-relatório-parcial) (o que mudou desde o relatório parcial e o que ele afirmava que precisa ser corrigido) e a [seção 8](#8-números-para-citar) (os números, com a fonte de cada um) |
| **Montar a apresentação quinzenal** | A [seção 7](#7-apresentação-quinzenal-ao-orientador) (modelo de slides e registro por quinzena) e a tabela [Estado da campanha](lab-procedure.md#estado-da-campanha) do roteiro |
| **Uma apresentação longa (1 hora)** | A [seção 5](#5-estrutura-sugerida-para-uma-apresentação-longa-1-hora) |
| **Retomar o contexto** | A linha do tempo ([seção 2](#2-linha-do-tempo-cronológica)), uma vez, de ponta a ponta; a [seção 3](#3-síntese-por-marco-revisão-rápida-antes-da-apresentação) é a versão de uma linha por marco |
| **Saber o que falta** | O [Marco 17](#marco-17--trabalho-pendente) e a [seção 4](#4-checklist-consolidado-de-capturas-de-tela-e-imagens) |

As datas dos marcos saem do `git log` (`git log --date=short --pretty='%ad %s'`). Preencha os ⚠️ com a sua memória e marque os `[ ]` à medida que gerar cada imagem.

---

## 1. Contexto Rápido

- **Projeto:** o SH-Analyzer é um instrumento para medir supraharmônicos (componentes de 2 a 150 kHz, vindos do chaveamento de conversores eletrônicos de potência) em redes e cargas elétricas. Os analisadores de Qualidade de Energia Elétrica (QEE) que seguem a IEC 61000-4-7 e a 61000-4-30 filtram essa banda antes do ADC e não a enxergam.
- **Escopo desta IC (a do hardware):** os objetivos do projeto de IC são (1) identificar sensores de tensão e de corrente com sensibilidade, fundo de escala, banda e conexão adequados; (2) desenvolver o condicionamento de sinais compatível com o ADC; (3) formação de recursos humanos. O registro, a visualização e a análise de supraharmônicos são o foco da IC 2. As ferramentas de análise deste repositório nasceram da necessidade de **validar** o hardware (Marco 5).
- **Estado no relatório parcial (30/06/2026):**
  - firmware da PRU em **C**, com SPI por *bit-banging*;
  - amostragem estável até ~100 kS/s (102,4 kS/s); a 150 e 200 kS/s, pacotes corrompidos e amostras perdidas;
  - buffer circular na Shared RAM;
  - o ARM gravava CSV já convertido em volts, com um filtro AC digital;
  - 1 canal, com um filtro RC de 3,5 kHz no canal de tensão;
  - validação qualitativa, por FFT.
- **Estado atual (20/10/2026):**
  - **Firmware:** PRU em Assembly, ADS8688 em modo automático (até 8 canais) e *ping-pong* de 2 × 2 MB na DDR. O teto é de ~140 kS/s, com o gargalo localizado nas esperas do CS. Cada captura registra a própria integridade: amostras atrasadas, buffers sobrescritos e ruído na linha SDO (Marco 13).
  - **Dados:** `.bin` com as amostras brutas e um cabeçalho autodescritivo (versão 4), com grandeza, sonda e faixa de entrada por canal. O arquivamento sem perdas fica em 11 % do tamanho.
  - **Análise:** `adc_tool.py` faz FFT ciclo-sincronizada, Welch, bandas, picos e exporta HDF5. `medir_captura.py` calcula as métricas de bancada. `gerar_perfil_sonda.py` corrige a resposta em frequência da cadeia.
  - **Bancada (19/10/2026), primeiros resultados quantitativos:** escala do ADC nas três faixas, ruído, razão do divisor, taxa de amostragem, diafonia e atraso entre canais, estabilidade em 10 min e a resposta em frequência da cadeia de tensão (−3 dB em 17,3 kHz). Ficou medido também o defeito de 6,97 µs a cada bloco do firmware antigo.
  - **Software:** pacote Python com ~680 testes automáticos e integração contínua.
  - **Falta:** a sonda de corrente (T10), o limite de taxa (T7e), distorção, *aliasing*, os ensaios ponta a ponta e a validação em hardware do firmware revisado (Marco 17).

### 1.1 Ponte com o Relatório Parcial

O relatório final precisa dizer o que aconteceu com o plano do relatório parcial (seção 7 dele) e corrigir o que os dados de agora desmentem.

| Plano do relatório parcial | O que aconteceu | Onde |
|---|---|---|
| **7.1** Reescrever as rotinas críticas da PRU em Assembly | Feito (jul/2026). Com o modo automático do ADC (set/2026), o teto passou de ~100 para 130 a 140 kS/s (130 observados na bancada; ~140 pela contagem do simulador; a medida fina é o T7e). O ganho foi menor que o esperado porque o gargalo não era o C: é o tempo fixo de cada quadro SPI, em que as esperas do CS somam 57 % | Marcos 2, 6 e 13 |
| **7.2** Remover o filtro RC de 3,5 kHz e melhorar as ligações físicas | As placas foram ligadas direto, sem jumpers (Marco 4). O canal de tensão hoje é o divisor ligado direto ao ADC: o T3 mede −3 dB em 17,3 kHz, incompatível com um RC de 3,5 kHz. Achado novo: o ADS8688 tem um passa-baixa de 2ª ordem **interno** em cada canal, que não dá para remover. A solução foi corrigir a cadeia inteira por um perfil medido | Marcos 4, 11 e 12 |
| **7.3** Correção dinâmica da taxa de amostragem (rastrear a rede e ajustar o período da PRU) | Não implementada, por decisão de método. A análise off-line dispensa janelas de ciclos inteiros na aquisição: corte em ciclos inteiros para a fundamental (Marco 5) e Welch para os supraharmônicos, que não têm relação de fase com a rede (Marco 7). A taxa da PRU ficou fixa e medida: 200 MHz ÷ ticks, com erro de dezenas de ppm (Marco 14) | Marcos 5, 7 e 14 |
| Meta de 512 a 2048 kS/s | Revista. O ADS8688 converte no máximo 500 kS/s **no total**, divididos entre os canais. Cobrir 150 kHz exige ≥ 300 kS/s em 1 canal. O caminho conhecido acima de 140 kS/s é reduzir as esperas do CS (roteiro, T7e) | Marco 13 |

- [ ] ⚠️ **Confirme com você mesmo:** quando o RC de 3,5 kHz do canal de tensão foi removido e se o capacitor do canal de corrente já saiu (roteiro, T0, passo 4, com a foto da placa antes).

**Afirmações do relatório parcial que o relatório final deve corrigir ou qualificar:**

1. *"O contador de ciclos sofre transbordo a cada ~21 s, protegido por coerção para int32."* O `CYCLE` da PRU **satura** em 0xFFFFFFFF e não volta a zero; por isso as capturas longas paravam (Marco 2). A correção da época zerava o contador a cada bloco, e foi ela que criou o salto de 6,97 µs a cada bloco, medido em 19/10 e corrigido em out/2026 com um rebase que não perde tempo (Marco 13).
2. *"O ADS8688 opera com até 500 kSPS por canal."* São 500 kS/s **no total**, multiplexados: com N canais, 500/N cada.
3. *"O limite de 100 kSPS vem do overhead do C e das impedâncias parasitas."* As duas causas existiam (Marcos 1 e 4), mas, removidas, o teto foi a ~140 kS/s e parou ali: o limite agora é o quadro SPI de ~7 µs (Marco 13).
4. *"Margem de setup e hold de 25 ns."* O firmware atual usa esperas de 2/1/1 µs no CS, calibradas empiricamente: ~100 vezes os mínimos do datasheet (30/10/30 ns, tabela 7.6). Medir quanto dá para reduzir é o T7e.
5. *"O ARM grava CSV já em volts, com filtro AC digital."* Hoje o ARM grava as amostras **brutas**, com cabeçalho; conversão, filtragem e correção são feitas na análise e o dado original nunca é alterado. É uma decisão de rastreabilidade.

---

## 2. Linha do Tempo Cronológica

### Marco 1 — Ponto de Partida: a PRU Programada em C (até jun/2026)

**Situação descrita no relatório parcial (seções 5.3 a 6.3):**

* **Aquisição:** a PRU 0 executava o SPI por *bit-banging* escrito em **C** (compilado com o `clpru` e carregado pelo *remoteproc*), com a temporização ancorada no contador de ciclos.
* **Transferência e gravação:** o ARM lia um buffer circular na Shared RAM por `/dev/mem` + `mmap()`, removia o DC com um filtro digital, convertia para volts e gravava CSV.
* **Resultado:** amostragem estável até ~100 kS/s (102,4 kS/s). A 150 e 200 kS/s apareciam pacotes corrompidos e amostras perdidas, atribuídos ao *overhead* do C e às impedâncias parasitas das ligações.

**Decisão de projeto:** reescrever o laço crítico em **Assembly** (plano 7.1 do relatório parcial), para controlar cada ciclo do *bit-banging*. O código em C saiu do repositório.

**O que se sabe hoje (para o relatório final):** das duas causas apontadas, as impedâncias parasitas eram reais (os jumpers, Marco 4). O *overhead* do C também, mas, eliminado, o teto foi a ~140 kS/s e parou ali. O que limita agora é o tempo fixo de cada quadro SPI (Marco 13).

- [ ] ⚠️ **Confirme com você mesmo:** uma versão anterior destas notas dizia que o protótipo em C rodava no ARM, sob Linux. O relatório parcial diz que era a PRU programada em C; vale o relatório parcial, salvo se houve uma etapa ainda anterior no ARM.
- [ ] As figuras 2 e 3 do relatório parcial (forma de onda e FFT a 100 kS/s) servem de "antes" para comparar com as figuras atuais.

### Marco 2 — Reescrita do Laço Crítico em Assembly (PRU)

Esta foi a etapa mais desafiadora do projeto, e também aquela cujos
detalhes o autor recorda com menor precisão — no entanto, o próprio
código-fonte (`spi_core.asm`) documenta os problemas resolvidos, o que
permite reconstruir um resumo confiável.

**Problema 1 — leitura travada em fundo de escala.** O ADC retornava
sistematicamente o valor máximo possível, independentemente da tensão real
de entrada, mesmo com a comunicação SPI aparentemente íntegra.

**Diagnóstico e correção:** duas alterações combinadas resolveram o
problema:
1. A escrita do bit de comando (MOSI) foi implementada com desvio
   condicional, replicando a estrutura `if/else` da versão original em C —
   uma implementação sem desvios ("branchless", com deslocamentos de bits e
   máscaras) mostrou-se **inoperante na prática**, apesar de logicamente
   equivalente. Esse resultado constitui um ponto relevante para o
   relatório: nem sempre a implementação mais elegante em código apresenta
   comportamento equivalente em hardware real, dado que a temporização é
   crítica.
2. O bit de dado (MISO) passou a ser amostrado no **último instante seguro
   antes da borda de descida do SCLK** — o intervalo máximo possível para a
   estabilização do sinal dentro do período em que o SCLK permanece em
   nível alto. Essa alteração, combinada com a anterior, eliminou a leitura
   travada.

**Problema 2 — interrupção espontânea de capturas longas.** O registrador
`CYCLE` da PRU (contador de ciclos usado para temporizar as amostras)
**satura** ao atingir o limite de 32 bits (aproximadamente 21,47 s a
200 MHz), em vez de reiniciar a contagem. Sem uma ressincronização
periódica desse contador, qualquer captura com duração superior a
aproximadamente 21 segundos deixava de funcionar.

**Correção (da época):** o contador é reiniciado manualmente no início da
aquisição e a cada troca de buffer (esquema ping-pong; ver Marco 3). O
relatório parcial descrevia o contador como "transbordando" e protegido por
coerção para `int32`: ele não transborda, satura (é o que o *AM335x PRU-ICSS
Reference Guide* descreve e o que as capturas interrompidas mostravam).
Essa correção resolveu as capturas longas, mas, por zerar o contador
**depois** da transação da última amostra, criou um salto de 6,97 µs a cada
bloco, só descoberto em out/2026 e corrigido com um rebase que não perde
tempo (Marco 13).

**Problema 3 — restrição de memória de instruções (`PRU_IMEM`).** A PRU
dispõe de apenas 8 KB de memória de instruções. Para controlar a velocidade
do barramento SPI sem exceder esse limite, o firmware utiliza **laços de
atraso** (contagem regressiva) em vez de sequências repetidas de
instruções `NOP` — um `NOP` por ciclo desperdiçado consome 1 instrução de
código, enquanto um laço de atraso consome poucas instruções e pode
representar qualquer número de ciclos de espera.

- [ ] ⚠️ **Confirme com você mesmo:** pelo `git log`, o Assembly começou em
      03/07/2026 e a primeira versão funcionando ("Assembly funcionando
      V0.1") é de 11 e 12/07; o modo automático veio em 08/09. Foi a etapa
      mais demorada do projeto? Vale citar na apresentação como o "custo"
      real da migração.
- [ ] Diagrama de temporização de `CMD_BIT`/`DATA_BIT` (comando vs.
      leitura, com o instante exato de amostragem do MISO) — bom recurso
      visual para um slide técnico.

### Marco 3 — Esquema Ping-Pong e Estrutura de Memória Compartilhada

**Justificativa do esquema ping-pong:** permite a gravação contínua sem
interrupção da aquisição — enquanto um buffer na DDR está sendo preenchido
pela PRU, o outro permanece disponível para o ARM esvaziar (gravação em
disco).

**Mecanismo de sincronização:** uma struct `shared_control`, alocada em uma
região de RAM interna da PRU-ICSS, contém campos como `config_ready`
(handshake inicial), `buffer_0_ready`/`buffer_1_ready` (sinalização de
buffer preenchido pela PRU) e os endereços físicos dos buffers na região de
DDR reservada (16 MB fora do alcance do Linux, dos quais 4 MB estão
atualmente em uso).

**Evolução da estrutura:** a struct `shared_control` passou por, no mínimo,
as seguintes revisões ao longo do desenvolvimento:
1. Versão original, restrita a 1 canal.
2. Expansão para captura multi-canal em **modo manual**: acréscimo do campo
   `num_canais` e de uma tabela `comandos_canais[8]` (um comando de 32 bits
   por canal, percorrida em esquema round-robin pela PRU) — struct de 64
   bytes.
3. **Simplificação para o modo automático** (mudança detalhada no Marco
   6): a tabela foi substituída por um único campo, `auto_seq_mask` (uma
   máscara de bits) — a struct foi reduzida para 32 bytes, uma vez que a
   PRU deixou de precisar conhecer a ordem ou a quantidade de canais,
   apenas quais estão habilitados (a ordem de varredura é determinada pelo
   próprio ADC).
4. **Configuração e diagnóstico** (out/2026): a struct voltou a crescer, para
   60 bytes, com campos que não custam nada por amostra — a faixa de entrada
   por canal (`range_sel`, Marco 14), os três contadores de integridade que a
   PRU publica uma vez por bloco e as três esperas do CS configuráveis
   (Marco 13).

Antes de tudo isso, no relatório parcial, a troca de dados era um buffer
circular na Shared RAM de 12 KB com um índice de escrita; o *ping-pong* na
DDR reservada substituiu esse esquema.

- [ ] ⚠️ **Confirme com você mesmo:** houve alguma revisão da struct entre
      as etapas (1) e (2) que não está documentada? Em caso afirmativo,
      registrar brevemente.
- [ ] Diagrama comparativo das 3 versões da struct (tamanho e campos) —
      recurso útil para evidenciar a simplificação progressiva como
      indicador de maturidade do projeto.

### Marco 4 — Problema de Integridade de Sinal (Jumpers Longos)

**Sintoma:** saturação do barramento SPI — leitura constante em fundo de
escala, independentemente da tensão real de entrada, mesmo em velocidades
significativamente **inferiores** às do firmware original (que operava
corretamente). Trata-se de um indício típico de problema de natureza
elétrica, e não de falha lógica ou de protocolo.

**Diagnóstico:** foi desenvolvido um firmware de diagnóstico dedicado
(`spi_core_diagnostico_preambulo.asm`), responsável por capturar os 16 bits
de "preâmbulo" de cada quadro SPI — bits que, segundo o protocolo, deveriam
permanecer sempre em zero. Um script específico
(`scripts/analisar_preambulo.py`) analisou esses preâmbulos e identificou
um **padrão de transição consistente**, característico de um problema de
integridade de sinal (reflexão, ruído induzido ou assimetria nos tempos de
subida/descida em algum ponto do caminho de sinal).

> Observação: o firmware e o script de diagnóstico do preâmbulo **não fazem parte
> do repositório atual** (nunca foram versionados). Se ainda existirem na máquina
> de desenvolvimento, vale guardá-los junto das capturas da época: a saída do
> script é a evidência quantitativa deste marco.

**Causa raiz e correção:** os **jumpers longos** utilizados para conectar a
placa de aquisição ao frontend analógico na bancada. O problema foi
resolvido eliminando-se os jumpers e conectando as placas diretamente. Essa
correção permanece em vigor no estado atual do projeto — `docs/
project-context.md` lista a integridade de sinal entre as duas placas como
item validado em hardware, e o isolador galvânico documentado hoje
(Analog Devices ADuM3150) já é um isolador digital dedicado, não um
optoacoplador simples — reforçando que a causa do problema original era
mesmo de integridade de sinal (conexão física), não de um componente
inadequado.

**Relevância para o relatório:** este marco ilustra um processo de
depuração sistemático — sintoma → desenvolvimento de ferramenta de
diagnóstico dedicada para isolamento da causa → formulação de hipótese →
teste da hipótese (remoção dos jumpers) → confirmação. Esse é precisamente
o tipo de raciocínio de engenharia que um relatório científico deve
registrar, não apenas o resultado final.

- [ ] ⚠️ **Confirme com você mesmo:** há o gráfico de saída de
      `analisar_preambulo.py` que evidencia o padrão de erro? **Esta é
      provavelmente a imagem mais valiosa deste marco** — demonstra o
      diagnóstico do problema de forma quantitativa, e não apenas
      qualitativa.
- [ ] Fotografia do setup com os jumpers longos (situação anterior) e das
      placas conectadas diretamente (situação corrigida) — comparação
      visual direta.
- [ ] Se disponível, uma captura de forma de onda evidenciando a saturação
      (situação anterior) em contraste com uma medição íntegra (situação
      corrigida), no mesmo canal e sob a mesma condição.

### Marco 5 — Ferramenta de Análise em Python (`adc_tool.py`) — Versão Inicial

**Justificativa, ainda que fora do escopo formal da IC:** sem uma
ferramenta própria de conversão, plotagem e análise espectral, não havia
meio de verificar se o hardware e o firmware realizavam medições corretas.
Cada problema de hardware ou firmware que exigiu diagnóstico (integridade
de sinal, alinhamento multi-canal, entre outros) motivou o desenvolvimento
de uma nova função de análise — a ferramenta cresceu organicamente a partir
de necessidades reais de depuração, e não de um planejamento inicial
abrangente.

**Evolução:** iniciada como `plot_adc.py`, restrita à plotagem, foi
renomeada para `adc_tool.py` ao incorporar o modo de conversão
`.bin`↔`.csv`, deixando de ser exclusivamente uma ferramenta de
visualização.

**Capacidades desenvolvidas nesta etapa:**
- Conversão `.bin` ↔ `.csv` em streaming, sem carregamento integral de
  arquivos grandes na memória.
- FFT **livre de vazamento espectral**, mediante estratégia de 5 etapas:
  1. Estimativa preliminar da frequência fundamental (FFT com janela de
     Hann).
  2. Filtro passa-baixa Butterworth para isolamento da fundamental.
  3. Detecção de cruzamentos por zero ascendentes, **interpolados
     linearmente** (não restritos à grade de amostragem).
  4. Refinamento do período a partir de todos os ciclos disponíveis, o que
     reduz o erro de medição.
  5. Recorte do trecho analisado em um número **inteiro** de ciclos,
     previamente à FFT principal — abordagem que trata a causa raiz do
     vazamento espectral, em vez de apenas atenuá-lo por meio de
     janelamento.
- Suporte a múltiplas janelas espectrais (retangular, Hann,
  Blackman-Harris, flattop, Kaiser).
- Suporte multi-canal completo: FFT independente por canal, calibração
  (faixa/ganho/offset) por canal e layout de plotagem configurável.
- Filtragem digital opcional (Butterworth passa-baixa/passa-alta, fase
  zero, via `sosfiltfilt`).

**Limitação desta etapa, resolvida no Marco 7:** a estratégia acima (corte
em ciclos inteiros) elimina vazamento espectral para a fundamental e seus
harmônicos, cuja fase está travada ao ciclo da rede — mas **não** ataca o
vazamento de conteúdo sem essa relação de fase, que é exatamente o caso dos
supraharmônicos (ruído de conversores eletrônicos de potência chaveados).
Nesta etapa, a ferramenta ainda não tinha um caminho espectral
matematicamente apropriado para o próprio objeto de medição do projeto —
ver Marco 7.

**Relevância para a apresentação:** a estratégia de FFT sem vazamento
(particularmente a etapa 5) constitui um detalhe metodológico que evidencia
rigor experimental — a aplicação de uma FFT sem tratamento adequado produz
artefatos de vazamento espectral que contaminam a leitura de amplitude dos
supraharmônicos, grandeza que constitui o próprio objeto de medição deste
trabalho.

- [ ] Captura de uma FFT real (preferencialmente da medição mais recente,
      em modo automático) evidenciando a fundamental de 60 Hz com
      vazamento espectral mínimo ou ausente ao seu redor.
- [ ] ⚠️ **Confirme com você mesmo:** é pertinente apresentar um exemplo
      comparativo "antes/depois" da técnica de corte em ciclos inteiros
      (FFT com vazamento vs. sem vazamento)? Caso esse comparativo tenha
      sido salvo durante o desenvolvimento da funcionalidade, trata-se de
      um recurso visual de alto valor para o orientador, que reconhecerá a
      relevância técnica de imediato.

### Marco 6 — Migração para o Modo Automático (AUTO_RST) do ADS8688

Esta constitui a etapa de maior impacto técnico do desenvolvimento, por ter
sido conduzida com um processo de validação completo e integralmente
documentado.

**Motivação:** no modo manual, o firmware reenviava um comando de seleção
de canal a **cada amostra**, mesmo nos casos em que os canais permaneciam
inalterados ao longo da captura (captura de canal único) ou seguiam sempre
a mesma sequência (captura multi-canal já implementada). O modo automático
do ADS8688 (`AUTO_RST`) elimina esse reenvio: o host programa a sequência
de canais **uma única vez**, e o próprio ADC avança de canal autonomamente
a cada amostra.

**Alterações técnicas decorrentes:**
- A struct `shared_control` foi simplificada, de 64 para 32 bytes (ver
  Marco 3).
- O índice de canal em esquema round-robin, anteriormente mantido em
  software pela PRU no modo manual multi-canal, foi eliminado — essa
  função passou a ser executada pelo próprio ADS8688, em hardware, sempre
  em **ordem crescente** de canal. O antigo modo manual (single-channel e
  multi-canal) não foi mantido como opção alternativa: foi removido por
  completo do firmware, a pedido explícito registrado no próprio
  código-fonte.
- Benefício adicional identificado, ainda não quantificado por
  osciloscópio: como o comando enviado a cada amostra passa a ser
  invariavelmente zero (`NO_OP`), o pino MOSI permanece eletricamente
  inerte durante a fase de comando — reduzindo uma fonte de chaveamento
  digital potencialmente acoplada à cadeia analógica sensível, aspecto
  particularmente relevante dado que este projeto mede ruído de alta
  frequência.

**Problema 1 — erro de compilação.** Na tentativa de agrupar as duas
transações de configuração (escrita de registrador e comando de início) em
um único laço de Assembly, o compilador (`clpru`) rejeitou o código com o
erro `Offset must be between -512L and 511L`. A causa consiste no alcance
limitado das instruções de desvio condicional "rápido" da PRU, capazes de
saltar no máximo ±511 posições — insuficiente para o corpo do laço, que
compreendia uma transação SPI completa. A correção substituiu o salto de
retorno por um salto incondicional, sem essa restrição, mantendo apenas o
teste de condição como salto curto. Na versão final entregue, as duas
transações de configuração acabaram implementadas por extenso (sem laço),
já que suas durações diferentes (24 vs. 32 ciclos) tornariam um laço
compartilhado mais complexo do que o ganho de código justificaria.

**Verificação do orçamento de memória:** a inspeção do arquivo `.map`
gerado pela compilação confirmou que o código coube com margem
confortável, utilizando aproximadamente 67% dos 8 KB de `PRU_IMEM`
disponíveis (~5.480 de 8.192 bytes).

**Problema 2 — falha de hardware, não restrita à compilação.** A primeira
tentativa de captura multi-canal produziu canais **idênticos** entre si,
reproduzindo exatamente o padrão observado em um teste anterior de canal
único incorretamente interpretado como multi-canal. Esse comportamento
indicava que a varredura automática nunca avançava de canal — o ADC
permanecia fixo em um único canal durante toda a captura.

**Causa raiz:** a escrita do registrador de programa `AUTO_SEQ_EN`
(responsável por informar ao ADC quais canais compõem a varredura)
utilizava 32 ciclos de relógio SPI, tratando-a como uma transação normal de
comando/leitura. O datasheet do ADS8688, no entanto, especifica **24
ciclos** para esse tipo particular de escrita (16 do comando mais 8 ciclos
adicionais) — constatação confirmada tanto pelo datasheet quanto pelo
driver oficial do ADS8688 no kernel Linux, e corroborada por uma resposta
de suporte da própria Texas Instruments em fórum técnico, na qual o mesmo
erro foi identificado em outro projeto. Os 8 ciclos excedentes, com o CS
ainda ativo, corrompiam a escrita da máscara de canais.

**Resultado após a correção:** em um ensaio com 5 canais (0 a 4), sendo os
canais 1 e 3 fisicamente conectados à tensão de rede e os canais 0, 2 e 4
deliberadamente deixados desconectados, os canais 1 e 3 exibiram a forma de
onda de 60 Hz esperada, ao passo que os canais 0, 2 e 4 apresentaram apenas
ruído — confirmando que a varredura automática alterna corretamente entre
os canais habilitados. A captura de validação rodou a 102,4 kHz totais
(≈20,48 kHz efetivos por canal). Com o comando fixo em `NO_OP`, o quadro
SPI ficou em ~7 µs (contagem do simulador da PRU, Marco 13): teto de
~140 kS/s, contra ~100 kS/s da versão em C do relatório parcial. A
migração simplificou o código e não custou desempenho.

**Relevância deste marco para o relatório e a apresentação:** reúne todos
os elementos de um processo de engenharia e depuração bem conduzido —
formulação de hipótese técnica, implementação, teste, sintoma inesperado,
investigação apoiada em fontes primárias (datasheet, driver de referência e
suporte do fabricante), correção e nova validação confirmatória. Esse tipo
de raciocínio evidencia rigor metodológico perante um orientador como o
Prof. Pomilio.

- [ ] **[PRIORIDADE ALTA]** Captura de tela do terminal com a saída
      completa de `ler_adc` durante a captura dos 5 canais (demonstra a
      interface e o uso da ferramenta).
- [ ] **[PRIORIDADE ALTA]** Gráfico do `adc_tool.py` com os 5 canais, lado
      a lado ou sobrepostos — 2 exibindo o sinal de 60 Hz e 3 exibindo
      apenas ruído. Trata-se, provavelmente, **da imagem mais importante de
      toda a apresentação**, por constituir evidência visual direta do
      funcionamento correto do modo automático multi-canal.
- [ ] Caso os dados da primeira tentativa (com a falha) ainda estejam
      disponíveis: o mesmo gráfico ANTES da correção, com os 5 canais
      idênticos — o contraste entre as duas situações é um recurso eficaz
      para relatar a falha com economia de texto no slide.
- [ ] Captura de tela do `.map` do `PRU_IMEM` (opcional, de caráter mais
      técnico; adequada ao relatório, dispensável na apresentação de 1
      hora, salvo disponibilidade de tempo).

### Marco 7 — Refatoração de `adc_tool.py` Orientada a DSP: Welch, Normalização Tom/Ruído e Extração de Picos

> **Data:** 13/09/2026 (*pull request* #2, `refactor/analise-espectral-supraharmonicos`), um dia antes do cabeçalho de metadados do Marco 8 (14 e 15/09, *pull request* #3): a ordem dos dois marcos está certa.

**Motivação:** a estratégia de FFT ciclo-sincronizada do Marco 5 resolve
vazamento espectral para a fundamental e seus harmônicos, mas
supraharmônicos — o próprio objeto de medição do projeto — vêm de
conversores eletrônicos de potência chaveados e **não têm relação de fase
com o ciclo da rede**. Não existe corte em ciclos inteiros que elimine
vazamento desse tipo de conteúdo: sem um caminho de análise dedicado, a
ferramenta conseguia caracterizar bem a rede elétrica "limpa" (60 Hz e
harmônicos), mas não o ruído de alta frequência que motiva a pesquisa como
um todo.

**O que foi construído:** uma refatoração de `adc_tool.py` orientada
especificamente a essa lacuna, somando ao caminho de FFT já existente:

- **Método de Welch** (`calcular_espectro_welch`, ativado por `--welch`):
  o sinal é segmentado (tamanho definido por `--resolucao-welch`, padrão
  200 Hz de resolução), cada segmento é janelado e transformado, e os
  periodogramas resultantes são **mediados** — reduz a variância da
  estimativa espectral e suaviza a deriva de frequência de chaveamento
  (*dithering*) ao longo da captura, sem depender de nenhuma relação de
  fase com a rede. Processado em lotes vetorizados
  (`numpy.lib.stride_tricks.sliding_window_view`) em vez de segmento a
  segmento em laço Python puro, necessário porque uma captura longa com
  sobreposição pode gerar centenas de milhares de segmentos.
- **Duas normalizações complementares** (`--modo-espectro {tom, ruido}`):
  `tom` mede a amplitude de um tom discreto (a fundamental, um harmônico
  isolado); `ruido` reporta densidade espectral de potência (PSD, V²/Hz),
  normalizada pelo ganho incoerente/ENBW da janela — necessária para
  conteúdo de banda larga, onde a normalização `tom` daria uma leitura que
  muda artificialmente com o tamanho da FFT/segmento para o mesmo ruído
  físico. Sem essa distinção, comparar a amplitude de um supraharmônico
  entre duas capturas com parâmetros de FFT diferentes seria
  matematicamente inválido.
- **Agrupamento em bandas fixas** (`--agrupar-bandas`, ex. 200 Hz —
  convenção da literatura de caracterização de supraharmônicos): resume o
  espectro fino em bandas de largura configurável, tornando o resultado
  comparável entre capturas com resoluções em frequência diferentes.
- **Extração quantitativa de picos** (`--picos`, via
  `scipy.signal.find_peaks` + interpolação parabólica, busca por padrão a
  partir de 2000 Hz — início convencional da faixa de supraharmônicos
  segundo a norma IEC 61000-4-7): entrega frequência e amplitude de cada
  componente supraharmônica individual, sem depender de aumentar o tamanho
  da FFT para "acertar" o bin exato.
- Correção da forma do filtro digital (SOS em vez da forma clássica
  `(b, a)`) para estabilidade numérica na razão fs/f0 extrema típica deste
  sistema (dezenas de milhares para 1), e um caminho de pré-filtragem
  passa-alta para remover o resíduo da fundamental antes de `--welch`/
  `--picos`.

**Validação:** toda essa arquitetura foi validada com sinais sintéticos
gerados em Python — fundamental de 60 Hz, harmônicos, supraharmônicos
injetados (incluindo um com *dithering* de frequência) e ruído gaussiano —
cobrindo `--fft`, `--welch`, ambos os modos de normalização,
`--agrupar-bandas`, `--picos`, captura multi-canal (com *aliasing*
proposital acima da Nyquist efetiva de um canal) e o round-trip
`.bin`↔`.csv`. Os picos injetados são recuperados com erro compatível com a
resolução espectral (exemplo: 15.321,3 Hz injetado → 15.321,37 Hz
encontrado por `--picos`). Essa validação confirma a correção
matemática/numérica da implementação — não ainda a fidelidade do hardware
de aquisição sobre um sinal real: o plano de testes está no Marco 11, as medições nos Marcos 12 e 14 e o que falta no Marco 17.

**Relevância para o relatório e a apresentação:** este é, dos marcos de
software, o mais diretamente ligado à pergunta de pesquisa do projeto. O
Marco 5 tornou possível *verificar* que o hardware/firmware funcionam
(ver a fundamental de 60 Hz numa FFT limpa); este marco é o que torna
possível, de fato, *medir supraharmônicos* de forma metodologicamente
defensável — a escolha de Welch em vez de uma FFT longa única, e a
distinção tom/ruído, são exatamente o tipo de decisão de método que um
relatório científico precisa justificar explicitamente, não só aplicar.

**Adendo (out/2026): ferramentas para pesquisa.** A revisão do `adc_tool`
acrescentou o que um trabalho de qualidade de energia normalmente reporta, com
o método declarado:

* **Tabela de harmônicos** sobre o trecho síncrono da FFT: componente e grupo
  harmônico da IEC 61000-4-7, porcentagem da fundamental, fase relativa à
  fundamental (referencial seno) e THD/THDG. Conferida com um sinal de
  harmônicos conhecidos: amplitudes e fases exatas em qualquer instante de
  início.
* **Bandas de 200 Hz pelo anexo B da IEC 61000-4-7** (janelas de 200 ms sem
  lacunas, bins de 5 Hz, centros em 2100, 2300... Hz), com a série no tempo e
  as estatísticas que os limites de emissão usam (RMS, máximo, percentil 95).
* **Espectrograma**, para ver quando cada supraharmônico aparece ou muda de
  frequência.
* **Exportação** de todo resultado para CSV e MATLAB, com um JSON de
  metadados (captura, calibração, janela, resolução, ENBW, filtros, versão do
  código e o comando exato): o que permite a outro pesquisador reproduzir
  cada número.

A mesma revisão corrigiu dois pontos de método: o Welch usava a janela
retangular por padrão (agora a Hann, a da literatura; a FFT síncrona continua
retangular), e as bandas passaram a seguir a convenção de bordas da norma
((b − 100, b + 100] Hz). Como extras, as janelas sincronizadas a 10/12 ciclos e a agregação de 3 s e
10 min da IEC 61000-4-30 (com a rede a 60,1 Hz, a janela sincronizada reduz o
vazamento da fundamental numa banda vazia de 46 para 1,7 mV). As diferenças
que restam em relação às normas (bordas arredondadas à amostra, intervalos
de 10 min não alinhados ao UTC) estão no guia de uso e entram nas limitações
do relatório.

- [ ] Captura de uma análise `--welch --agrupar-bandas --picos` sobre uma
      medição real, mostrando supraharmônicos extraídos com frequência e
      amplitude — provável candidato a imagem central da seção de
      resultados do relatório, junto com o gráfico dos 5 canais do Marco 6.
- [ ] Comparativo `--fft` vs. `--welch` sobre o **mesmo** sinal sintético
      com *dithering* de frequência injetado — visualmente demonstra por
      que uma FFT ciclo-sincronizada sozinha não seria adequada para
      supraharmônicos, reforçando a justificativa de método.
- [ ] ⚠️ **Confirme com você mesmo:** vale registrar com captura de tela o
      console mostrando o aviso automático de `adc_tool.py` quando
      `--filtro-passa-alta` é usado junto de `--fft` de forma incompatível
      (a ferramenta detecta e avisa) — pequeno, mas evidencia atenção a
      casos de uso combinados incorretamente.

### Marco 8 — Cabeçalho de Metadados e Exportação para HDF5

**Motivação:** à medida que o volume de capturas cresceu, tornou-se
necessário um mecanismo de rastreabilidade: cada arquivo `.bin` deveria
carregar consigo os parâmetros da captura que o originou (frequência,
canais, instante de aquisição), reduzindo a dependência do nome do arquivo
ou de anotações externas para reconstituir esse contexto. Adicionalmente, a
interoperabilidade com ferramentas científicas de terceiros motivou a
adoção do formato HDF5 como alternativa de exportação ao par `.bin`/`.csv`
já existente.

**Decisão de projeto — cabeçalho binário de tamanho fixo:** foi
implementada uma estrutura de metadados de 1024 bytes, gravada no início de
cada arquivo `.bin`, antes das amostras brutas. A estrutura é identificada
por um número mágico (`"SHAN"`) e contém, entre outros campos, a frequência
de amostragem, a máscara e a lista de canais habilitados, o instante da
captura (epoch Unix), os totais de blocos e amostras gravadas, um título e
uma descrição em texto livre (UTF-8) e um checksum CRC-32 do próprio
cabeçalho.

Duas decisões de implementação, específicas do ambiente embarcado, merecem
registro:

1. **Compatibilidade binária entre C e Python.** A struct do cabeçalho foi
   declarada com `__attribute__((packed))`, eliminando o padding de
   alinhamento que o compilador inseriria por padrão entre campos de
   tamanhos diferentes — sem essa diretiva, o layout de bytes do cabeçalho
   dependeria da arquitetura/ABI de compilação, o que é inaceitável para um
   formato de arquivo lido de volta por outro programa (o script
   `adc_tool.py`, em Python, via o módulo `struct`). O tamanho total da
   struct (1024 bytes) é verificado em tempo de compilação por meio de um
   array de tamanho dependente de uma expressão booleana — recurso
   deliberadamente escolhido em vez de `_Static_assert` (C11), por não
   haver garantia da versão do compilador `clpru`/`gcc` disponível no
   ambiente de desenvolvimento.
2. **Verificação de integridade sem dependência externa.** O CRC-32 do
   cabeçalho é calculado por uma implementação bit a bit (sem tabela de
   consulta), evitando a necessidade de uma biblioteca externa apenas para
   essa finalidade pontual — o custo computacional é irrelevante, dado que
   o cálculo ocorre apenas duas vezes por captura (início e fim), fora do
   laço crítico de aquisição.

Vale notar, para o relatório: uma alternativa mais simples (um arquivo
lateral `.json` separado) foi cogitada em algum momento da revisão do
projeto, mas descartada em favor do cabeçalho embutido — um único arquivo
por captura, sem risco de o metadado se perder ou dessincronizar do `.bin`
correspondente, com verificação de integridade própria (CRC-32) que um
`.json` avulso não teria.

**Extensão da interface de linha de comando:** `ler_adc` passou a aceitar
`-o` (nome do arquivo de saída, com geração automática por timestamp na
ausência da flag), `-t` (título) e `-d` (descrição), além de `--blocos`/
`--duracao` para controlar a duração da captura (antes fixa em 1 bloco no
código-fonte). Um cuidado de implementação relevante: textos que excedam o
espaço reservado no cabeçalho são **rejeitados**, e não truncados —
truncar uma string UTF-8 em um limite de bytes arbitrário arrisca
interromper uma sequência multibyte, produzindo texto inválido gravado
permanentemente no arquivo.

**Integração no pós-processamento (`adc_tool.py`):** o script foi
estendido para detectar o cabeçalho automaticamente pelo número mágico. Na
sua ausência — o caso de arquivos gerados por versões anteriores do
firmware —, o comportamento anterior é preservado integralmente, exigindo
frequência e lista de canais como argumentos explícitos. Na presença do
cabeçalho, esses parâmetros são preenchidos automaticamente, e um conjunto
de verificações de consistência foi implementado: uma contagem de canais
informada manualmente que diverge da registrada no cabeçalho é tratada como
erro (a operação de desintercalação dos canais ficaria matematicamente
incorreta), ao passo que uma lista de canais de mesma contagem mas com
identificadores diferentes gera apenas um aviso (afeta somente os rótulos
exibidos, não o cálculo).

**Exportação para HDF5:** foi implementada a flag `--export-hdf5`,
convertendo uma captura em um arquivo `.h5` com os dados dispostos como uma
matriz bidimensional (amostras por canal × número de canais) e os
metadados do cabeçalho gravados como atributos na raiz do arquivo. Um
requisito central de implementação foi assegurar que a conversão não
dependesse de carregar a captura inteira na memória — capturas de dezenas
de gigabytes constituem um cenário previsto no regime de operação do
sistema. A escrita foi implementada em blocos sobre o arquivo `.bin`
mapeado em memória (`numpy.memmap`).

**Verificação quantitativa do uso de memória:** a garantia de que a
exportação não carrega a captura inteira na RAM foi verificada
empiricamente, e não apenas assumida pela leitura do código. Utilizando um
arquivo sintético de 130 MB e instrumentação com o módulo `tracemalloc`
(que rastreia alocações no nível do interpretador Python, distintas das
páginas de memória mapeadas pelo sistema operacional via `mmap`), o pico de
alocação Python durante a exportação foi medido em aproximadamente 1,8 MB —
valor independente do tamanho do arquivo de origem. Um resultado
inesperado da instrumentação: o pico manteve-se praticamente constante
mesmo ao aumentar o tamanho do bloco de processamento (`--tamanho-chunk`)
em 25 vezes, indicando que boa parte do bloco de dados permanece como uma
referência às páginas já mapeadas pelo sistema operacional, sem
necessariamente ser copiada para uma nova estrutura em memória Python —
propriedade mais favorável do que o mínimo originalmente exigido
(proporcionalidade entre uso de memória e tamanho do bloco de
processamento).

**Relevância para o relatório:** este marco demonstra um processo de
desenvolvimento orientado a testes automatizados — cada decisão de formato
(layout binário, tratamento de texto, particionamento em blocos) foi
acompanhada de uma verificação programática (comparação de offsets,
round-trip de escrita e leitura, detecção de corrupção via CRC, perfil de
memória), em vez de inspeção manual do resultado. Constitui um contraponto
metodológico ao Marco 6, no qual a validação dependeu primariamente de
hardware físico: aqui, a ausência de uma métrica objetiva equivalente ao
osciloscópio (usado para o timing SPI) foi compensada por instrumentação de
software.

- [ ] Diagrama do layout de bytes do cabeçalho (campo, offset, tamanho) —
      recurso visual direto para explicar a struct sem reproduzir a tabela
      completa no slide.
- [ ] ⚠️ **Confirme com você mesmo:** vale registrar, com uma captura de
      tela, o console mostrando o resumo do cabeçalho impresso por
      `adc_tool.py` (título, descrição, frequência, canais, status do CRC)
      ao abrir uma captura real?
- [ ] Gráfico ou tabela do teste de memória (pico de alocação Python vs.
      tamanho do arquivo/bloco processado) — evidência quantitativa da
      propriedade de memória constante, em espírito análogo ao gráfico do
      Marco 6.

### Marco 9 — Cabeçalho Versão 2 e Correção de Sondas de Corrente

**Motivação:** o frontend de **tensão** tem ganho constante em frequência, de
modo que um fator escalar (`--ganho`) basta. Uma **sonda de corrente**, ao
contrário, atenua o sinal de forma diferente a cada frequência — e os
supraharmônicos, justamente o conteúdo de interesse, ficam na região em que
essa atenuação é maior. Sem correção, a amplitude medida de um componente
de 40 kHz, por exemplo, sai cerca de 40 % abaixo do valor real (0,060 A em
vez de 0,100 A, em teste sintético).

**Decisão de projeto — rotular no ARM, corrigir no Python.** O `ler_adc`
apenas **registra** o que cada canal mede (`--grandeza`) e qual sonda foi
usada (`--sonda`); não abre nem interpreta nenhum arquivo de calibração. A
curva de ganho vive num perfil `.json` no computador de análise, e o
`adc_tool.py` o localiza pelo identificador gravado no cabeçalho. O
cabeçalho passou para a **versão 2** (`grandeza_por_canal` e
`sonda_id_por_canal`, 32 bytes por canal), mantendo 1024 bytes no total e a
leitura de arquivos da versão 1. As flags são chaveadas pelo **número do
canal**, e não pela ordem digitada — a mesma classe de bug de
desalinhamento já encontrada ao migrar para o modo automático, em que o ADC
reordena os canais em ordem crescente.

**Ferramentas criadas:**

1. `firmware/calibrar_sonda.sh` — coleta guiada na bancada (gerador de
   sinal + resistor *shunt* de precisão): o operador informa a taxa de
   amostragem, o canal da sonda e o número de pontos; por padrão a captura
   usa **um canal só** (Nyquist = taxa ÷ 2, o que permite calibrar até a
   banda de supraharmônicos) e a referência vem de uma senoide de
   **amplitude conhecida**, gravada com a frequência nos metadados de cada
   captura (`--amplitude 500mVpp`), ou de uma leitura do osciloscópio a
   cada ponto (`--ref-externa`); o jeito de dois canais (um segundo canal do
   ADC no *shunt*, Nyquist = taxa ÷ 4) continua disponível. O script escolhe
   as frequências (escala
   logarítmica até 80 % da Nyquist efetiva por canal), diz qual frequência
   injetar, grava o cabeçalho, confere cada captura (saturação, nível,
   frequência medida, CRC, tamanho) e permite refazer, pular, retomar uma
   coleta interrompida, refinar e adensar pontos.
2. `scripts/gerar_perfil_sonda.py` — mede amplitude e frequência de cada
   captura (Welch com janela *flat-top* para localizar o tom e FFT única com janela
   Kaiser para a amplitude e a frequência finais), calcula o ganho contra o que foi
   injetado (amplitude conhecida nos metadados, forma de onda `.m` do osciloscópio,
   leitura anotada ou canal de referência no shunt) e grava o perfil, com
   validação antes de substituir um perfil existente. O perfil descreve o
   **conjunto** sonda + frontend + ADC (inclusive o filtro passa-baixa de 2ª ordem
   do ADS8688, de frequência de corte desconhecida: ela aparece na curva), e o
   resumo da resposta (−3 dB, inclinação, amplificação de ruído) é impresso e
   gravado no perfil. `scripts/medir_captura.py` compara o ADC com a amplitude
   injetada e com o `.m` do osciloscópio, o que permite conferir a efetividade
   do método numa única medição.
3. Correção no `adc_tool.py` — divisão espectral com interpolação PCHIP sobre
   (log da frequência, ganho em dB), aplicada antes de FFT/Welch/plotagem.

**Auditoria independente do fluxo (`docs/probe-profile-audit.md`):** com
capturas sintéticas de uma sonda de resposta conhecida, o gerador recuperou o
ganho com erro de no máximo 0,02 % nos pontos medidos, e a correção
restaurou a amplitude de tons de 2,5 a 40 kHz. A auditoria encontrou **sete
bugs reais**, todos corrigidos e cobertos por teste — entre eles um erro
silencioso de escala de 10× quando o `--ganho` de uso diferia do usado na
calibração, e a leitura de um identificador de sonda capaz de escapar da
pasta de perfis. (A conclusão de que o estimador de amplitude era exato
valia para o modo de dois canais, em que o ganho é uma razão e o erro se
cancela; ao simular os modos de um canal, em que a amplitude é absoluta, o
erro chegou a 1,8 % e foi corrigido — ver o adendo em
`docs/probe-profile-audit.md`.) Também registrou limites que o software não resolve: a
correção é só de **magnitude** (não restaura a fase, o que inviabiliza
análises V×I), e a confiabilidade física do perfil depende da bancada.

**Estado de validação:** todo este fluxo foi validado apenas com sinais
**sintéticos**. Não havia ainda calibração de uma sonda real em bancada (a primeira, da cadeia de tensão, veio no Marco 12).

**Relevância para o relatório:** é um bom exemplo de revisão crítica do
próprio trabalho — a auditoria tratou o fluxo como um terceiro faria,
procurou ativamente o que poderia dar errado e registrou, junto com as
correções, os limites que permanecem. Registrar o que o método **não**
garante é parte do rigor científico.

- **Data:** 10/10/2026 (*pull request* #4, `feat/probe-profiles-and-metadata`); o
  `calibrar_sonda.sh` foi reescrito em 14/10 e ganhou a amplitude conhecida e o
  `.m` do osciloscópio em 18/10.
- [ ] Gráfico do `--plot` do `gerar_perfil_sonda.py` (curva de ganho do perfil)
      — de preferência com uma sonda real, quando houver.
- [ ] Comparativo do espectro de um sinal de corrente **com** e **sem**
      `--sem-correcao-sonda` — mostra o efeito da correção.
- [ ] Fotografia da bancada de calibração (gerador, *shunt*, sonda, placa).

### Marco 10 — Qualidade e Manutenibilidade do Software: Pacote, Testes e Integração Contínua

**Motivação:** o código de análise havia crescido num único arquivo
(`adc_tool.py`, perto de 2950 linhas, com uma função `main()` de cerca de 400
linhas), e o projeto será modificado por outras pessoas. Era preciso
reduzir o custo de alterar o código sem quebrar o que já funciona.

**O que foi feito:**

1. **Pacote `scripts/supraharmonicos/`** — 22 módulos organizados em camadas
   sem dependências circulares (regra verificada por teste). `adc_tool.py`,
   `gerar_perfil_sonda.py` e `medir_captura.py` viraram entradas finas, de menos de 40 linhas.
   Erros viram exceções (`ErroSHAN`) e mensagens passam por `logging`; só a
   camada de linha de comando imprime e escolhe o código de saída.
2. **Prova de que nada mudou:** antes de refatorar, 61 execuções de linha de
   comando foram registradas e depois comparadas com a nova versão — 57
   idênticas e 4 com diferença só no texto de mensagens de erro/aviso
   padronizadas. Nomes de flags, saídas e códigos de saída foram preservados.
3. **483 testes automáticos** na época (~680 em out/2026), sem necessidade de hardware: unidades por
   módulo, linha de comando, regras de arquitetura, dependências, o fluxo
   completo de perfil de sonda e o script de coleta de calibração
   (`calibrar_sonda.sh`, exercitado contra um `ler_adc` simulado). Um teste de **contrato C↔Python** lê o
   `ler_adc.c` e confere que o formato do cabeçalho e as constantes
   compartilhadas continuam iguais nos dois lados.
4. **Integração contínua** (GitHub Actions): a cada *push* e *pull request*,
   roda o `ruff` e a suíte de testes em Python 3.10 e 3.13.
5. **Documentação:** `README.md` reescrito, guia de uso
   (`docs/user-guide.md`) e guia da arquitetura do software
   (`docs/software-architecture.md`).
6. **Arquivamento dos dados brutos sem perdas** (`compactar_amostras.py`,
   out/2026): um pacote `tar` com peças zpaq -m5 e os canais desentrelaçados,
   conferido bit a bit (SHA-256) antes de ficar pronto, com um `LEIA-ME`
   que permite recuperar tudo sem o programa. Todas as capturas até o T3
   (407 MB) couberam em 44,9 MB (11,0 %; o 7-Zip dava 14,6 %). Medido: o
   ruído do ADC limita qualquer compressor sem perdas a ~1,1–2,2 bits por
   amostra (de 16), e o zpaq chega perto disso; FLAC (~15 %) e um preditor
   linear antes do zpaq foram testados e descartados.
7. **Revisão da suíte de testes e reprodutibilidade** (out/2026): a suíte
   passou a rodar em paralelo (de ~6 min para ~1 min 40 s; ~30 s sem os
   testes ponta a ponta), com cobertura de ~90 % do pacote. A revisão achou
   asserções que passariam com o código errado e testes que se pulavam em
   silêncio, e dois defeitos reais: um `--grandeza` com canal fora da
   captura era ignorado, e figuras do matplotlib não eram fechadas. Todo
   script executável roda com `uv run`, que instala sozinho as dependências
   declaradas no próprio arquivo (PEP 723); um teste garante isso para os
   scripts futuros.

**Relevância para o relatório:** mostra a preocupação com a
reprodutibilidade e a manutenção do instrumento como software. O teste de
contrato C↔Python é um bom exemplo de como substituir uma regra que dependia
de disciplina manual ("manter os dois lados em sincronia") por uma verificação
automática.

- **Data:** pacote criado em 11/10/2026 e incorporado em 18/10 (*pull request*
  #5, `refactor/modularize-sh-analyzer`); arquivamento, `uv run` e revisão dos
  testes em 20/10.
- [ ] Diagrama das camadas do pacote (em `docs/software-architecture.md`, seção 3).
- [ ] Captura de tela da aba *Actions* do GitHub com a CI passando.

### Marco 11 — Preparação da Validação em Bancada

**Motivação:** até aqui, toda a validação numérica foi sintética. Antes de ir
ao laboratório era preciso (a) ter uma ferramenta que transformasse uma
captura em **números para o relatório** e (b) saber o que injetar, em que
ordem e com que critério de aceitação.

**O que foi feito:**

1. **`scripts/medir_captura.py`** — mede uma ou mais capturas e imprime
   (e grava em CSV, uma linha por canal): DC, RMS, ruído (nV/√Hz e LSB), tom,
   THD, SINAD, SNR, ENOB, SFDR, **continuidade** (uma amostra perdida ou
   duplicada aparece como um salto de fase de ~1 amostra no tom), diafonia e
   atraso entre canais, e o erro contra um instrumento de referência
   (`--referencia-rms`, `--referencia-freq`). Método: FFT única com janela
   Kaiser (β = 14), cujo vazamento (≈ −112 dBc) não limita o ENOB de um ADC
   de 16 bits; uma janela Blackman-Harris limitaria a ~14 bits. Validado com
   sinais sintéticos de verdade conhecida (43 testes).
2. **Leitura crítica do datasheet do ADS8688:** cada canal tem um **filtro
   passa-baixa de 2ª ordem embutido, de ~15 kHz a −3 dB** (seção 8.3.5). Na
   banda de supraharmônicos o sinal chega ao conversor atenuado em dezenas
   de dB (estimativa: −33 a −40 dB em 150 kHz); a correção por perfil devolve
   a amplitude, mas amplifica o ruído na mesma proporção, e o anti-aliasing
   é fraco para componentes de 200 a 500 kHz (dobram para dentro da banda).
   O perfil precisa, portanto, descrever a cadeia inteira.
3. **Taxa de amostragem real:** o `ler_adc` calcula `ticks = 200 MHz ÷ taxa`
   com divisão inteira. 102,4 kHz sai a 102 406,55 Hz (+64 ppm); 300 kHz,
   +1001 ppm; 100, 200, 250, 400 e 500 kHz saem exatas. Era uma hipótese, e
   a bancada a confirmou (Marco 14).
4. **`calibrar_sonda.sh` com um canal por padrão:** com dois canais, 500 kS/s
   dá Nyquist de 125 kHz, que não cobre os 150 kHz da banda; com um canal e
   400 kS/s, 200 kHz.
5. **`docs/lab-procedure.md`** — 12 testes (T0 a T11): ruído em curto,
   DC e linearidade, **resposta em frequência da cadeia**, taxa real,
   THD/ENOB, diafonia, **integridade em taxas altas**, aliasing, sinais de
   espectro conhecido (onda quadrada: harmônicos de amplitude `4A/(nπ)`),
   **perfil da sonda com validação por frequências retidas** e um teste
   ponta a ponta. Cada teste traz o sinal a injetar, os comandos, o que
   anotar no osciloscópio de GS/s e um critério de aceitação.

**Resultado do ensaio com dados sintéticos:** uma cadeia de dois polos com
−3 dB em 15 kHz foi "calibrada" pelo fluxo do roteiro (24 pontos, 1 canal,
referência externa): o perfil recuperou o ganho com erro de 0,001 %, e uma
onda quadrada de 10 kHz, que sem correção mostrava a 15ª harmônica 31 dB
abaixo da teoria, voltou à teoria em ±0,05 dB até 150 kHz. Esse ensaio
revelou o erro de até 1,8 % do estimador de amplitude nos modos de um canal
(Marco 9), corrigido.

**Relevância para o relatório:** o roteiro e a ferramenta de métricas são o
que transforma "o código funciona" em "o instrumento tem exatidão X, medida
contra uma referência independente". A leitura do datasheet antes da
bancada evitou calibrar o sistema com premissas erradas (banda plana até
Nyquist).

- [ ] ⚠️ **Confirme com você mesmo:** modelo, exatidão e data de calibração do
      osciloscópio e do gerador usados nos testes (entram na tabela de
      incertezas).
- [ ] Tabela e figuras do roteiro, "Dados e figuras para o relatório".

### Marco 12 — Primeira Medição em Bancada: Resposta em Frequência da Cadeia de Tensão (T3)

**O que foi feito:** em 19/10/2026 foi executado o T3 do roteiro de
laboratório — a primeira medição quantitativa do instrumento contra uma
referência independente e o primeiro uso, com hardware real, do fluxo
`calibrar_sonda.sh` → `gerar_perfil_sonda.py`. Configuração (registrada no
commit do perfil): canal 1 (divisor de tensão), 100 kS/s, faixa de entrada
de ±10,24 V lida do cabeçalho v3 de cada captura, 48 frequências de 50 Hz a
45 kHz, referência = tensão RMS lida no osciloscópio no nó de entrada do
divisor, `--ganho 19,357` (1 ÷ razão nominal do divisor). Resultado:
`scripts/sondas/cadeia_tensao.json`. Os cabeçalhos v3 das capturas reais
foram conferidos pelo `calibrar_sonda.sh` na coleta e lidos pelo gerador de
perfil (faixa marcada como confiável no JSON).

**Resultado:** ganho plano até alguns kHz e queda de 12,5 dB em 45 kHz. O
ajuste por mínimos quadrados (em dB) de um passa-baixa de 2ª ordem,
H(s) = K·ω0² / (s² + (ω0/Q)·s + ω0²), deu:

| Parâmetro | Valor |
|---|---|
| K (ganho de baixa frequência, relativo ao divisor nominal) | 0,9969 ± 0,0028 (−0,03 dB) |
| f0 | 24,06 ± 0,21 kHz |
| Q | 0,540 ± 0,006 |
| f−3dB | 17,26 ± 0,16 kHz |
| Polos ÷ 2π | −22,3 ± j9,1 kHz (quase amortecimento crítico) |
| Resíduo RMS | 0,13 dB |

O critério BIC rejeita o modelo de 1ª ordem (ΔBIC = +142) e não justifica
um polo real adicional, como uma capacitância parasita do divisor
(ΔBIC = +3,9). A frequência de −3 dB é da cadeia inteira (divisor +
ADS8688) e fica acima dos ~15 kHz estimados a partir do datasheet
(seção 8.3.5) — confirma o filtro previsto no Marco 11 e dá o seu valor real.

**Limitações (a declarar no texto):**
1. **Só magnitude.** A fase não foi medida; H(s) supõe sistema de fase
   mínima (válido para um filtro analógico sem atraso puro). A medição da
   fase fica como trabalho futuro: osciloscópio na entrada do divisor e na
   linha CS do ADS8688, que retém a amostra na borda de descida do CS
   (datasheet, seção 8.4.1.1.1).
2. **Uma leitura por frequência (n = 1).** A incerteza dos parâmetros foi
   estimada pela dispersão dos resíduos, supondo o modelo correto. Os
   resíduos entre 3 e 9 kHz (até +0,4 dB) são maiores que a dispersão em
   baixa frequência (0,06 dB): repetir o T3 com `--repeticoes 3` dirá se é
   leitura do osciloscópio ou desvio do modelo.
3. **Faixa curta acima do corte.** Os pontos param em 2,6 × f−3dB, o que
   correlaciona f0 e Q (−0,87). Medir |H| acima da Nyquist por
   subamostragem de senoides puras estenderia a curva (exige mudanças nos
   scripts; ver `docs/improvement-proposals.md`, item S4).

**Consequências no software:**
- Os textos do `calibrar_sonda.sh` eram todos de corrente (o operador tinha
  de ler "tensão RMS no shunt" como "tensão na entrada do divisor"). O
  script ganhou `--grandeza tensao` (grava `--grandeza <canal>:tensao` no
  cabeçalho, como em produção) e o `referencia_externa.csv` a coluna
  `tensao_rms_V`, lida pelo gerador de perfil sem o truque de
  `--resistencia-shunt 1`.
- A revisão do script mostrou que, no modo de 2 canais, o filtro do ADC é
  igual nos dois canais e se cancela na razão sonda/referência: o perfil
  desse modo não corrige o filtro do ADC (documentado no script e no guia).
- `report/gerar_figuras.py` gera as figuras do relatório com estilo
  único (PDF vetorial no tamanho final, texto composto pelo LaTeX, vírgula
  decimal via siunitx) e grava os números citados no texto como macros
  (`report/figures/perfil_cadeia_tensao.tex`). A primeira figura é a
  curva do T3 com o ajuste e os resíduos.

**Relevância para o relatório:** é o primeiro resultado medido do
instrumento e o núcleo da seção de resultados sobre a banda de
supraharmônicos de tensão: quantifica a atenuação que a correção por perfil
precisa desfazer (e o ruído que ela amplifica junto).

- [ ] ⚠️ **Confirme com você mesmo:** configuração do osciloscópio no T3
      (medida de RMS usada, média, limite de banda, escala vertical) e se o
      gerador estava em *High-Z*. (O firmware era o da faixa por canal: no
      mesmo dia, o T0 mediu as três faixas, o que só acontece se a PRU
      escreve `RANGE_SELn`; Marco 14.)
- [ ] Fotografia da montagem do T3.

### Marco 13 — Revisão do Firmware: Grade de Tempo e Integridade da Captura

**Motivação:** o `medir_captura.py` acusava, na captura de 10 minutos do
T7 (100 kS/s), uma "descontinuidade" de 0,7 amostra; e o risco do esquema
ping-pong (Marco 3), de o ARM não esvaziar um buffer a tempo, nunca tinha
sido medido. A pergunta era se dava para vigiar a captura sem piorar o
gargalo de taxa, cuja origem também não estava isolada.

**Achados (com as capturas reais e um simulador do assembly da PRU):**

1. **Salto de ~7 µs a cada bloco.** Para não saturar o contador de ciclos
   de 32 bits da PRU (Marco 2, problema 2), o firmware o zerava a cada troca
   de buffer — mas depois da transação SPI da última amostra, de modo que a
   primeira amostra do bloco seguinte saía ~1.394 ciclos (6,97 µs) além do
   período. Medido em todas as 57 trocas da captura de 10 min: +0,697
   amostra a 100 kS/s (desvio de ±0,002), +0,765 a 110 kS/s e +0,872 a
   125 kS/s — exatamente a duração de uma transação. Abaixo de ~48,8 kS/s,
   um bloco dura mais que 2³² ciclos e o contador ainda saturava no meio.
   **Correção:** quando o contador passa de 2³¹ (~10,7 s), subtrai-se 2³¹
   dele e do instante da próxima amostra ao mesmo tempo, sem perder tempo; o
   bloco deixou de importar.
2. **As primeiras amostras de cada captura saíam mais depressa que o
   pedido**, porque o contador era zerado antes das ~10 transações de
   configuração do ADC e a PRU "corria atrás". Agora ele é zerado logo antes
   da primeira amostra.
3. **O gargalo de taxa é o próprio quadro da PRU:** ~7 µs por amostra, dos
   quais ~4 µs (57 %) são três esperas do CS calibradas empiricamente (2, 1
   e 1 µs) contra 30, 10 e 30 ns pedidos pelo datasheet (tabela 7.6), e ~3 µs
   são os 32 clocks do SPI feitos em software. O lado ARM tem ~10 s para
   gravar cada bloco de 2 MB.

**Integridade medida durante a captura, sem custo para a amostragem.** A
PRU agenda cada amostra por instante absoluto e espera por ele; o que roda
entre amostras cai nessa folga. Ela passou a contar, em registradores, as
**amostras atrasadas** (taxa acima do alcançável), os **buffers
sobrescritos** antes de o ARM gravá-los (o risco do ping-pong, agora
detectado) e os **quadros com ruído na linha SDO** (o ADS8688 mantém essa
linha em 0 durante o comando, §8.4.1.1.4 do datasheet — o mesmo sinal que o
diagnóstico dos jumpers usava no Marco 4). Os contadores são publicados uma
vez por bloco e gravados no cabeçalho (versão 4); o `ler_adc` também mede a
taxa real pelo relógio do ARM. As esperas do CS ficaram configuráveis
(`--atraso-cs`, padrão idêntico ao validado) para medir em bancada até onde
a taxa sobe (T7e).

**Como foi verificado:** um simulador do assembly (Python) executa o
`spi_core.asm` de verdade; ele reproduz o defeito no firmware antigo
(intervalos de 3.380 ciclos nas trocas, contra 2.000 pedidos) e confere, no
novo, a grade de tempo, o rebase do contador e os três contadores, além de
que a transação continua com os mesmos 1.166 ciclos do firmware validado.
**Falta validar no hardware** (refazer a captura de 10 min do T7: a
continuidade tem de sair sem saltos).

**Relevância para o relatório:** é um exemplo de defeito de temporização
que não aparece num bloco isolado (a análise espectral de 10 s não o
enxerga), achado pela métrica de continuidade e explicado até a instrução;
e da diferença entre *evitar* e *detectar* uma falha quando evitá-la (fazer
a PRU esperar pelo ARM) mudaria justamente o instante das amostras.

**Rastreabilidade do firmware (cabeçalho v5, 21/10).** Como o firmware
passa a mudar entre campanhas, cada captura grava a versão que a gerou (o
`git describe` do repositório, levado à BeagleBone num arquivo `VERSAO`) e a
taxa medida pelo relógio do ARM, que antes só aparecia no console. Cada ida
à bancada ganha também uma etiqueta no git (`bancada-AAAA-MM-DD`). Um `.bin`
passa a dizer, sozinho, com que código foi feito, e também a geometria do
ping-pong (2 buffers de 1.048.576 amostras). O envio para a BeagleBone foi
padronizado num script (`scripts/enviar_firmware.sh`, hoje o `enviar` do `scripts/BeagleBone_Setup.sh`): vai só `firmware/`,
com a versão, e o firmware anterior fica guardado, só o código, como plano B.
O HDF5 exportado passou a levar o cabeçalho original inteiro e o perfil de
cada sonda, para os dados poderem ser usados e auditados sem o `.bin` e sem
estas ferramentas.

- [ ] Figura: intervalo entre amostras ao redor de uma troca de buffer,
      antes e depois (simulador e captura real refeita).
- [x] Tabela: salto por taxa (100, 110, 125 kS/s) antes da correção: está
      no Marco 14 e no T7 do roteiro.

### Marco 14 — Caracterização da Aquisição em Bancada (Dados de 19/10/2026)

**O que foi feito:** no mesmo dia do T3 (Marco 12), foram capturados o T0, T1, T2, T4, T6 e T7 do roteiro. São 39 capturas, 217 MB, em `$DADOS/lab/2026-10-19/` (a pasta de dados fica fora do repositório; ver [user-guide.md](user-guide.md#onde-guardar-os-dados)), feitas com o firmware anterior à revisão do Marco 13 (cabeçalho v3). A análise, de 20/10, usou o `medir_captura.py`. Os números estão em `resultados.csv`, na mesma pasta. Os comandos e o detalhe de cada teste estão nos parágrafos "Executado em 19/10/2026" do [roteiro](lab-procedure.md#estado-da-campanha).

**Resultados:**

| Grandeza | Medido | Referência | Teste |
|---|---|---|---|
| Escala do ADC (tensão no pino ÷ a esperada) | **0,9997 / 0,9997 / 0,9992** nas faixas de ±10,24 / ±5,12 / ±2,56 V | 1 (referência interna de 4,096 V) | T0 |
| Ruído com a entrada em curto | **160 / 91 / 58 µV RMS** (0,51 / 0,58 / 0,75 LSB) | 172 / 96 / 61 µV (datasheet, típico) | T1 |
| Ruído × taxa (50 a 200 kS/s) e × nº de canais (1 ou 2) | constante: 0,51 a 0,52 LSB | — | T1 |
| Offset no pino | canal 1: +2,5 a +3,5 mV; canal 0: +0,05 a +0,21 mV | ±0,75 mV (datasheet, máximo) | T1, T2 |
| Razão do divisor, com a carga do ADC | **0,051554** (`$GV` = 19,397) | 0,05157 calculada (−0,03 %) | T2 |
| Linearidade (±0,5 V no pino) | resíduo ≤ 0,22 LSB | INL de ±0,75 LSB (típica) | T2 |
| Taxa de amostragem | = 200 MHz ÷ ticks: 102,4 kS/s a **−64,03 ppm** e 110 kS/s a **−99,98 ppm** das taxas exatas | previsto: −64,0 e −100,0 ppm | T4 |
| Erro de frequência comum (cristal + gerador) | −43,2 ppm | dezenas de ppm | T4 |
| SINAD e ENOB, 10 kHz a −27,5 dBFS | 61 dB; 14,4 bits | — | T4 (prévia do T5) |
| Diafonia no canal convertido logo depois do agressor, 10 kHz | **−94,7 dB** | 90 dB (memória) e 110 dB (isolamento) | T6a |
| Atraso entre canais consecutivos a 100 kS/s | **9,954 µs** | 10,000 µs (−0,46 %) | T6b |
| Estabilidade em 10 min (janelas de 1 bloco) | frequência 0,09 ppm; amplitude 0,009 % | — | T7c |
| Salto a cada troca de buffer (firmware antigo) | **+0,697 amostra (6,97 µs)** nas 57 trocas, ±0,002 | 0 | T7c |

**Achados:**

1. **A faixa de entrada por canal funciona em hardware.** Era a principal hipótese não testada do firmware de 19/10, até então só simulada. A tensão no pino é a mesma nas três faixas (±0,08 %), o que confirma a referência de 4,096 V, o código em binário deslocado e a escrita dos registradores `RANGE_SELn`. Consequência: as capturas antigas (v1/v2), que as ferramentas liam como ±5,12 V, tinham metade do valor real; desde out/2026 elas assumem ±10,24 V.
2. **Transitório ao trocar a faixa.** Quando a faixa de um canal muda em relação à captura anterior, o começo desse canal decai de até ~1 V (~4 600 LSB) até o valor certo: ~6 amostras acima de 20 LSB e menos de 1 LSB em ~80 µs, o mesmo **tempo** com 1 e 2 canais (é analógico, não uma contagem de amostras). Sem troca, não há transitório, e as 15 capturas do dia seguem essa regra. A constante de tempo no fim (~8 µs) é próxima à do passa-baixa do T3 (7 µs). Sem descartar o começo, o ruído medido sai 7 a 8 vezes maior. Desde 21/10 o `medir_captura.py` pula os primeiros 200 µs sozinho, e as duas ferramentas avisam se o começo de um trecho destoa do resto.
3. **O ruído do ADC é o do datasheet**, e a faixa menor reduz o ruído em volts como previsto (1,8× e 2,8×). Fica confirmado o ganho de usar ±2,56 V no canal de corrente.
4. **O offset do canal 1 não parece ser do ADC.** O canal 0, com 0,12 Ω de impedância de fonte, tem offset dentro do datasheet. O canal 1, com 1,7 kΩ (o divisor), tem de 10 a 70 vezes mais. A hipótese é a ligação do divisor; o teste que separa as causas está no roteiro (T1). É DC: não afeta os supraharmônicos.
5. **A taxa de amostragem é exatamente a prevista pelos ticks**, sem ciclo extra por amostra. A hipótese do Marco 11 se confirmou a 0,02 ppm.
6. **O defeito do Marco 13, medido.** O salto cresce com a taxa (0,697 amostra a 100 kS/s; 0,77 a 110 kS/s; 0,87 a 125 kS/s): é um tempo fixo, o de uma transação SPI. Nenhuma amostra se perdeu; a grade de tempo é que escorregou. Dentro de cada bloco, o sistema é estável a 0,09 ppm e 0,009 % ao longo de 10 min. **O que ele estraga numa análise que atravessa blocos** (medido em 21/10 nas mesmas capturas): o SINAD de uma FFT única cai de 63 dB (1 bloco, T7a) para ~22 dB (4 blocos, T7c), e a frequência e a amplitude do tom se deslocam em +1,5 ppm e −0,3 % numa captura de 2 blocos (T4 a 125 kS/s). Por isso o T4 foi medido só no primeiro bloco. A métrica de continuidade passou a comparar o salto em cada troca de buffer com o dos outros segmentos: 6,96 µs nas trocas contra 0,01 a 0,04 µs fora delas, o que pega o defeito com qualquer nº de canais.
7. **Três falhas do próprio roteiro, corrigidas:**
   * o ponto de "40 kHz" do T6a, com 2 canais (Nyquist de 25 kHz por canal), apareceu dobrado em 10 kHz;
   * o T7a e o T7b, de 1 bloco, não atravessavam nenhuma troca de buffer e não tinham como ver o defeito;
   * o critério "salto < 0,5 amostra" deixava passar o salto de 7 µs com 2 canais (0,35 amostra do canal).

**Limitações (a declarar):**

* O firmware era o anterior à revisão do Marco 13.
* O T4 não registrou a leitura do contador do osciloscópio: o erro do cristal e o do gerador ficam somados.
* As capturas rotuladas "−10 V" do T0 saíram com 0 V na entrada; serviram para medir o offset de cada faixa.
* O THD medido (−71,6 dB) é o do gerador, não o do ADC.
* As entradas abertas do teste de 8 canais não medem diafonia.

**Relevância para o relatório:** são os primeiros números do instrumento contra referências independentes (Fluke 289 e osciloscópio). Mostram que o ADC entrega o que o datasheet promete, o que delimita onde estão os problemas reais: a banda (o filtro interno, Marco 12), a taxa (Marco 13) e a sensibilidade do canal de corrente (T10).

- [ ] Figura: o transitório de troca de faixa (as 10 primeiras amostras de `T0_dc_p10_f1024` e `f512`, em LSB, com a exponencial ajustada).
- [ ] Figura: a PSD do curto (`fig_T1_psd`) e a tabela de ruído por faixa contra o datasheet.
- [ ] Figura: a reta do T2, com o resíduo em LSB.
- [ ] Figura: o salto de fase ao longo do T7c (um ponto por troca de buffer: 57 pontos em 0,697).
- [ ] ⚠️ **Confirme com você mesmo:** o que estava ligado ao canal 2 no T6b (ele leu 0,48 % acima do canal 1) e aos canais 3 a 7 no teste de 8 canais.

### Marco 15 — Esperas do CS e Taxa Máxima (T7e, 21/10/2026)

**O que foi feito:** com o firmware revisado (Marco 13) compilado na BeagleBone, um script (`firmware/varrer_taxa.sh`) fez o T7e inteiro sem decisões no meio: 101 capturas com o tom de 10 kHz em ±2,56 V. Ele variou as esperas do CS do padrão (2/1/1 µs) ao piso do datasheet (30/10/30 ns) em 14 passos, e cada espera sozinha; a taxa de 125 a 500 kS/s para sete conjuntos; 2 canais; e a entrada em curto. Os dados estão em `$DADOS/lab/2026-10-21/T7e_2026-10-21_1731/`, e o detalhe, no parágrafo "Executado em 21/10/2026" do [T7e no roteiro](lab-procedure.md#t7e-onde-está-o-limite-de-taxa).

**Resultados:**

1. **As esperas do CS não limitam a qualidade.** Até o piso do datasheet e até 250 kS/s, todos os conjuntos dão o mesmo resultado: SINAD de 62,1 a 63,7 dB, THD de −72 dB, ruído em curto de 0,74 a 0,76 LSB, diafonia de −94 a −95 dB e nenhum quadro com ruído no SDO. São os números do padrão e de 19/10.
2. **O teto sobe de 143 para 326 kS/s** (com o piso do datasheet), ~0,6 % abaixo da contagem do simulador (a escrita na DDR). Esperas de trabalho: `6,2,6` (o dobro do piso). Taxa de trabalho: **250 kS/s**, com 22 % de folga no quadro. Com 1 canal, a banda medida passa de 45 kHz para 112 kHz (0,9 × Nyquist).
3. **A correção do salto de 7 µs (Marco 13) funcionou:** nas trocas de buffer, o salto ficou abaixo de 0,06 µs.
4. **Um defeito novo, achado e corrigido.** Numa captura de 31 s, o SINAD caía de 63 para 24 dB. Os degraus de fase, de 5 a 13 µs, caíam sempre no mesmo **instante** (10,737 s e 21,47 s desde o começo), em todas as taxas, e não na mesma amostra: 10,737 s são 2^31 ciclos da PRU, o ponto em que o firmware faz o rebase do contador de ciclos. O tamanho de cada degrau bateu com a hipótese de que, com a PRU rodando, escrever no contador o **zera** (previsto 12,74 µs, medido 12,77 µs, a 125 kS/s). O rebase escrevia `CYCLE − 2^31`; agora ele zera o contador e recua o instante da próxima amostra o mesmo tanto. O simulador assumia que a escrita gravava o valor (por isso o defeito passou); ele passou a zerar o contador, e o teste do rebase pega a versão antiga (salto de 4 385 ciclos). Os contadores de integridade não o viam: nenhuma amostra saía atrasada, a grade é que andava.

**Relevância para o relatório:** é o resultado que mais muda o instrumento: a taxa e a banda mais que dobram, sem perda nenhuma de qualidade, e o limite passa a ser o datasheet do ADC e o SPI em software, não as esperas calibradas na época dos jumpers longos. O defeito do contador é um bom exemplo do ciclo sintoma → ferramenta → hipótese → teste: o sintoma (o SINAD) parecia vir das esperas ou das trocas de buffer, e foi a posição dos degraus no tempo que apontou o contador.

### Marco 16 — A Grade de Tempo (22/10/2026)

**O que foi feito:** depois do Marco 15, a pergunta passou de "quantas amostras por segundo" para "em que instante sai
cada amostra". O `medir_captura.py` ganhou duas medidas, validadas com sinais sintéticos de jitter e degraus
conhecidos:

* o **jitter de amostragem**, a parte do ruído que cresce com a inclinação do tom. Num tom, uma amostra fora do
  instante erra `inclinação × atraso`: o ruído cresce nos cruzamentos por zero e some nos picos;
* o **degrau de tempo**, em ns, em cada troca de buffer e em cada rebase do contador. É a fase do tom ajustada antes
  e depois de cada evento.

Aplicadas às capturas de 21/10, as duas medidas apontaram o último defeito da grade de tempo.

**Resultados (capturas de 21/10, firmware `v0.7`):**

1. **Jitter de ~8,5 ns rms em toda captura**, a 100, 250 e 312,5 kS/s e com as esperas de 3,1,3 a 200,100,100: o
   mesmo número, qualquer que seja a configuração. Num tom de 10 kHz a ~1/6 do fundo de escala, ele **triplica o
   ruído** (2,46 LSB contra 0,78 LSB onde o tom é plano, que é o ruído do ADC) e limita o SNR a ~64 dB. Causa
   provável: a espera da PRU sondava o contador de ciclos e soltava a amostra na 1ª leitura depois do instante, de 0
   a ~6 ciclos depois, ao acaso (uniforme em 30 ns = 8,7 ns rms).
2. **A troca de buffer já não desloca a grade:** +0,3 ns (±0,1 ns). A correção do Marco 13 resolveu o salto de 7 µs
   inteiro.
3. **Os rebases antigos** (o defeito do Marco 15) aparecem como degraus de +4,8 e +6,6 µs, nos instantes previstos.

**A correção (firmware de 22/10/2026, protocolo 2; o backup do anterior é a tag `v0.7`):**

* a espera virou **sondagem até faltarem 255 ciclos, mais um laço de exatamente os ciclos que faltam**. Da leitura
  do contador à descida do CS são sempre 11 + R ciclos: o CS desce num ciclo fixo depois do instante da grade;
* a PRU mede e publica a **menor folga** da captura, que entra no cabeçalho v6. Folga > 0 e nenhuma amostra
  atrasada são a prova de que **toda** amostra saiu no ciclo exato;
* o rebase do contador passou a se **autocalibrar** (a PRU mede a latência das próprias leituras e escritas);
* o `ler_adc` recusa a captura se a PRU estiver com outro firmware.

No simulador, com latências de memória hipotéticas e escritas na DDR atrasadas ao acaso, todo intervalo entre amostras
é o período exato, ao ciclo. Para caber, o AUTO_RST passou a reaproveitar o corpo da configuração: a PRU foi de 1 876
para ~1 400 instruções (92 % → 69 % da IMEM).

**Validado na bancada em 22/10/2026** (o [T7f](lab-procedure.md#t7f-o-período-entre-amostras-a-grade-de-tempo), 46
capturas, o tom de 10 kHz de 21/10):

1. **O jitter caiu de 8,5 ns para 0,00 ns** (abaixo do piso de ~0,3 ns do método): era da PRU.
2. **O ruído com o tom caiu de 2,23 para 0,77 LSB**, o ruído do ADC com a entrada em curto: SNR de 64,0 para
   69,4 dB e SINAD de 63,4 para 67,4 dB em 10 s. O que sobra é do gerador (ruído de fase a menos de 5 Hz do tom e a
   THD de −72 dB).
3. **Nenhum degrau** em 89 trocas de buffer (−0,03 ± 0,03 ns) e 28 rebases (−0,04 ± 0,07 ns) em 5 min. Na PRU, um
   degrau vale múltiplos de 5 ns: todos foram de zero ciclo. O rebase autocalibrado mediu 7 ciclos (o simulador, 2).
4. **Nenhuma amostra fora da grade a 312,5 kS/s**, em 5 min, com o ARM ocupado e com 2 canais. A folga, porém, é de
   3 a 5 ciclos (o simulador dava 25): na PRU de verdade, a troca de buffer leva ~636 ciclos. O teto com período
   constante é ~315 kS/s; até ~322 kS/s, só a troca de buffer sai atrasada.

**Relevância para o relatório:** fecha a pergunta "a grade de tempo é exata?" com números (folga em ciclos, jitter e
degraus em ns), e não com "não vimos problema". É um bom exemplo de medida que separa causas: o ruído alto parecia
do ADC ou do gerador, e foi a dependência com a inclinação do tom que apontou o tempo.

**Mais tarde no mesmo dia: o quadro dependia do dado.** A "cauda aleatória" do quadro comum (611 a 619 ciclos, que
se atribuía à escrita na DDR) não era aleatória. Na varredura J, a fração de amostras atrasadas em cada período bateu
com a fração de amostras que têm tantos bits 1 (619 ciclos: 5,58 × 10⁻⁵ atrasadas e 5,53 × 10⁻⁵ amostras com 15 bits
1; 616 ciclos: 2,44 × 10⁻² e 2,56 × 10⁻²): o quadro durava **605 + (bits 1 da amostra)** ciclos. A causa estava no
assembly: o bit lido era acumulado com um desvio (`QBBC` + `OR`), e um bit 1 executava uma instrução a mais com o SCLK
em alto. As 43 capturas de calibração do mesmo dia (folga de exatamente 20 ciclos em todas: 640 − 605 − 15)
confirmaram. O instante da amostra nunca dependeu disso (a descida do CS vem depois da espera de precisão), mas a
folga, o teto e o padrão do SCLK, sim. A correção lê o bit com um `AND` sem desvio e soma-o com o SCLK já baixo, no
lugar de um NOP: todo quadro dura o mesmo, sem nenhum ciclo a mais. Junto, a troca de buffer passou a fazer um acesso
à memória por amostra, nas 5 amostras seguintes, em vez de 5 de uma vez. Com o simulador calibrado nas medidas da
placa (o mesmo modelo reproduz a folga de 20 ciclos e a da troca), a folga prevista a 312,5 kS/s sobe de 3 para 29
ciclos, qualquer que seja o sinal. Figura `grade_bits` (a varredura J contra a previsão).

**Relevância:** é a lição da PRU em uma frase: num processador sem cache nem interrupções, o tempo de cada caminho
do código é uma medida, e um desvio condicional no laço de amostragem faz o tempo depender do dado. A pista veio de
tratar a "cauda aleatória" como um dado a explicar, e não como ruído.

**O T3 até 140 kHz, no mesmo dia** (perfil `cadeia_tensao_312k`, 43 pontos a 312,5 kS/s, faixa de ±2,56 V): −3 dB
em 16,8 kHz; o mesmo 2ª ordem (f0 = 24,2 kHz, Q = 0,53) descreve 3,5 décadas a 0,1 dB, sem outro polo; −30,6 dB em
140 kHz. Nas frequências em comum, a 0,13 dB rms do perfil de 19/10, medido a outra taxa, em outra faixa e com outro
firmware. Figura `perfil_cadeia_tensao_comparacao`. E o T1 a 312,5 kS/s deu o mesmo ruído de 19/10.

**A 2ª parte do dia: o quadro fixo, o SPI rápido e 400 kS/s.** O firmware com o quadro fixo foi à placa e a 2ª
rodada do T7f confirmou o que o simulador calibrado previa: o quadro comum de 600 ciclos, folga de 25 ciclos a
312,5 kS/s com qualquer sinal, teto de 327,9 kS/s. O SPI rápido (bits de 13 ciclos, ~15,4 MHz) lê cada bit em três
instantes e conta as divergências, para medir a margem do SDO sem osciloscópio. No T7g (69 capturas), 0 quadros com
a leitura de 60 ns ou a de 90 ns diferente da de 75 ns, ou seja, margem de pelo menos 15 ns para cada lado. O ruído
foi o mesmo (0,80 contra 0,79 LSB), a distorção também, e o período ficou constante até 419,3 kS/s. A 400 kS/s, a
folga é de 18 ciclos. Com isso, 400 kS/s e o SPI rápido viraram o padrão do `ler_adc` (`--spi lenta` volta ao de
antes): a Nyquist sobe de 156 para 200 kHz. Taxas inteiras saem de 200 MHz ÷ 2ᵃ5ᵇ, e não há nenhuma entre 400 e
420 kHz.

**A fase da cadeia sem osciloscópio (T3f).** Uma onda quadrada simétrica traz a referência de tempo dentro dela: a
fase de cada harmônico ímpar menos n vezes a da fundamental independe do instante da captura e de um atraso puro.
Foram 24 capturas de 30 s (7 quadradas de 256 a 20736 Hz e variantes de amplitude e offset, nas duas taxas):

* a cadeia de tensão é um 2ª ordem com **f0 = 22,811 kHz e Q = 0,5001**, isto é, dois polos reais coincidentes,
  vezes um polo real em **800 kHz**;
* −3 dB em **14,68 kHz** (o datasheet do ADS8688 diz ~15 kHz);
* resíduo de **0,01 dB e 0,14°** de 256 Hz a 180 kHz;
* a magnitude sozinha e a fase sozinha dão o mesmo filtro: a cadeia é de **fase mínima**;
* as duas taxas, com SPIs diferentes, diferem 0,0005 dB e 0,004°.

A quadrada não usa instrumento de referência, e por isso desmentiu o T3 por senoides. As senoides ficam 1,2 a 1,3 dB
acima dela acima de ~40 kHz, exatamente a queda da referência que o osciloscópio leu. A forma da diferença, um
degrau que começa em ~500 Hz, é a de uma ponta 10× subcompensada. A mesma ponta explicaria o "caráter capacitivo"
da quadrada vista na tela (a conferência está no roteiro). O limite da medida é o INL do ADC, e ele aparece onde não
se esperava: ~1 LSB de erro na fase da fundamental entra em `arg Xₙ − n·arg X₁` multiplicado por n, e chega a 10° no
harmônico 580 da quadrada de 256 Hz. A ferramenta o tira por captura. Perfil `cadeia_tensao_fase`, com a fase de cada
ponto.

**Relevância:** a fase da função de transferência foi medida sem nenhum instrumento além do próprio sistema, e o
mesmo método achou o erro do instrumento de referência da medida anterior. É o argumento para o relatório de que o
perfil por quadradas é o de referência.

### Marco 17 — Trabalho Pendente

Em ordem de prioridade, a mesma da tabela [Estado da campanha](lab-procedure.md#estado-da-campanha) do roteiro:

1. **Conferir a ponta do osciloscópio e a origem do polo de 800 kHz (T3f, ~30 min):** a foto da ponta no PROBE
   COMP antes do ajuste, 6 senoides de 1 a 140 kHz com a ponta compensada e o Fluke até 50 kHz, e a subida da
   quadrada do gerador ([roteiro](lab-procedure.md#passo-a-passo-da-próxima-ida-a-referência-do-t3-e-o-polo-de-800-khz-30-min)).
   Decide entre o perfil por quadradas e os por senoides, e se o polo fica no perfil. A grade de tempo, o SPI
   rápido e o limite de taxa foram medidos em 22/10 (Marco 16): a campanha `--limite` ficou superada.
2. **Fotografar o CS no osciloscópio** (a anatomia do quadro, para o relatório).
3. **Refazer na taxa padrão (400 kS/s)** o que depende da banda: T4 e T6, como manda a tabela [O que refazer com o firmware de out/2026](lab-procedure.md#o-que-refazer-com-o-firmware-de-out2026).
4. **Calibração da sonda de corrente (T10)**, o objetivo central, **depois** do T7e: o perfil vale até 0,9 × Nyquist da taxa em que é medido. O fluxo já rodou com hardware real na cadeia de tensão (Marco 12); falta o SCT013 e a validação em frequências que não entraram no perfil (*hold-out*). A sensibilidade de 60 µV/A sobre o resistor de carga é o maior risco (roteiro, fato 5).
5. **Completar a caracterização:**
   * o contador de frequência no T4;
   * o ponto de 20 kHz no T6a;
   * o T5, com uma fonte de baixa distorção;
   * *aliasing* (T8), espectros conhecidos (T9) e os ensaios ponta a ponta (T11).
6. **Usar a fase na correção (S3):** o perfil `cadeia_tensao_fase` já traz a fase de cada ponto, mas a correção
   ainda só usa a magnitude ([`improvement-proposals.md`](improvement-proposals.md)).
7. **Investigar o offset do canal 1** (com o pino em curto direto). O transitório de troca de faixa já é descartado na análise (o `medir_captura.py` pula 200 µs); descartá-lo também no firmware fica como opção ([`improvement-proposals.md`](improvement-proposals.md), F9).

Fechar cada apresentação com esta lista, objetiva e com prioridade, mostra que o estado do projeto e os próximos passos estão claros.

---

## 3. Síntese por Marco (Revisão Rápida Antes da Apresentação)

1. **Ponto de partida (relatório parcial):** PRU programada em C, ~100 kS/s estáveis e perda de amostras acima disso.
2. **Assembly na PRU:** resolveu a leitura travada em fundo de escala (bit de comando com desvio, MISO lido no último instante seguro) e as capturas que paravam (o contador de ciclos satura em ~21,5 s). Os laços de atraso fazem o código caber nos 8 KB da IMEM.
3. **Memória compartilhada:** do buffer circular na Shared RAM ao *ping-pong* de 2 × 2 MB na DDR. A struct de controle passou por quatro revisões: 64, 32 e hoje 60 bytes.
4. **Integridade de sinal:** a saturação do SPI foi rastreada, com um firmware de diagnóstico do preâmbulo, até os jumpers longos, e corrigida ligando as placas direto.
5. **`adc_tool.py`:** ferramenta de análise própria, criada para validar o hardware, com FFT sem vazamento por corte em ciclos inteiros.
6. **Modo automático do ADS8688:** acabou o reenvio de comando a cada amostra. Uma falha real de protocolo (24 contra 32 ciclos) foi achada em fontes primárias, e a varredura foi validada com 1 e com 5 canais.
7. **Welch, normalização tom/ruído, bandas e picos:** o caminho espectral próprio para supraharmônicos, validado com sinais sintéticos.
8. **Cabeçalho de 1024 bytes com CRC-32:** capturas autodescritivas. A exportação para HDF5 roda com memória constante, medida com `tracemalloc`.
9. **Cabeçalho v2 e correção de sondas:** grandeza e sonda por canal e o perfil de resposta em frequência. A auditoria achou e corrigiu sete bugs.
10. **Qualidade de software:** pacote em camadas, ~680 testes, contrato C↔Python, integração contínua, `uv run` e arquivamento sem perdas a 11 % do tamanho.
11. **Preparação da bancada:** o `medir_captura.py`, a leitura crítica do datasheet (filtro interno de ~15 kHz e arredondamento dos ticks) e um roteiro de 12 testes com critérios de aceitação.
12. **Primeira medição (T3):** a cadeia de tensão é um passa-baixa de 2ª ordem, com f0 = 24,1 kHz, Q = 0,54, −3 dB em 17,3 kHz e resíduo de 0,13 dB.
13. **Revisão do firmware:** o salto de 6,97 µs a cada bloco foi achado e corrigido sem perder tempo. A integridade passou a ser medida sem custo para a amostragem (cabeçalho v4), e o gargalo de taxa foi localizado nas esperas do CS: 57 % do quadro, ~100× o mínimo do datasheet.
14. **Caracterização em bancada (19/10):**
    * escala certa nas três faixas, a 0,08 %;
    * ruído igual ao do datasheet;
    * divisor a 0,03 % do calculado;
    * taxa = relógio ÷ ticks, a 0,02 ppm;
    * diafonia de −94,7 dB e atraso entre canais a 0,5 % do previsto;
    * estabilidade de 0,09 ppm em 10 min;
    * um transitório de 60 µs ao trocar a faixa.
15. **Esperas do CS e taxa (21/10):** as esperas descem ao piso do datasheet sem perda; o teto vai de 143 para 326 kS/s; o defeito do rebase do contador foi achado pela posição dos degraus no tempo.
16. **Grade de tempo (22/10):** jitter de 8,5 ns achado nas capturas (o ruído crescia com a inclinação do tom); a PRU passou a esperar o ciclo exato e a medir a própria folga.
    * 2ª parte: o quadro fixo validado, o SPI rápido sem nenhuma leitura divergente e 400 kS/s como padrão; a fase da cadeia por ondas quadradas (três polos reais, fase mínima), que mostrou o erro da referência do osciloscópio no T3 por senoides.
17. **Pendente:** conferir a ponta do osciloscópio, calibrar a sonda de corrente (o objetivo central) e completar a caracterização.

---

## 4. Checklist Consolidado de Capturas de Tela e Imagens

Os marcados "**dados já existem**" dá para gerar hoje, com as capturas de `$DADOS/lab/2026-10-19/` e as ferramentas do repositório. As figuras do relatório saem de `uv run report/gerar_figuras.py` (PDF vetorial no tamanho final; o PDF não é versionado, porque é gerável).

**Prioridade alta (resultados do relatório)**

- [x] (Marco 12) Resposta em frequência da cadeia de tensão (T3), com o ajuste de 2ª ordem e os resíduos: `gerar_figuras.py perfil_cadeia_tensao`
- [ ] (Marco 14) Tabela de ruído por faixa contra o datasheet e a PSD do curto (T1) — **dados já existem**
- [ ] (Marco 14) Escala do ADC nas três faixas (T0) e a reta do divisor com o resíduo em LSB (T2) — **dados já existem**
- [ ] (Marco 13/14) Salto de fase a cada troca de buffer ao longo dos 10 min (T7c, antes da correção) — **dados já existem**; o "depois" exige refazer o T7c com o firmware novo
- [ ] (Marco 14) Transitório de troca de faixa (as primeiras amostras, em LSB) — **dados já existem**
- [ ] (Marco 14) Tabela de taxa pedida × ticks × erro medido (T4) — **dados já existem**
- [ ] (Marco 13) Anatomia de um quadro SPI (esperas do CS, 32 clocks, folga), do simulador e, depois, do osciloscópio (T7e, método 2)
- [ ] (Marco 7) Análise `--welch --agrupar-bandas --picos` sobre uma medição real, com supraharmônicos extraídos
- [ ] (Marco 6) Gráfico dos 5 canais (2 com sinal, 3 com ruído) e a saída do terminal do `ler_adc`
- [ ] (T10) Perfil da sonda de corrente e a tabela de validação *hold-out* (quando houver)
- [ ] (T9a) Onda quadrada: teoria × ADC sem correção × ADC com perfil × osciloscópio (quando houver)

**Fotografias** (não dá para gerar depois)

- [ ] Bancada de cada teste, com o diagrama de ligações; placa antes de remover o capacitor do canal de corrente
- [ ] (Marco 4) Setup com os jumpers longos e com as placas ligadas direto
- [ ] (Marco 9/T10) Bancada de calibração da sonda (gerador, resistor, SCT013, TCP0030A)
- [ ] (Marco 12) Montagem do T3

**Apoio (apresentação ou apêndice)**

- [ ] (Marco 1) As figuras 2 e 3 do relatório parcial, como "antes"
- [ ] (Marco 2) Diagrama de temporização de `CMD_BIT`/`DATA_BIT`
- [ ] (Marco 3) As versões da struct `shared_control` lado a lado
- [ ] (Marco 4) Saída do `analisar_preambulo.py` (o script não está no repositório; ver o Marco 4) e a forma de onda saturada × íntegra
- [ ] (Marco 5) FFT limpa de uma medição real (60 Hz), com e sem o corte em ciclos inteiros
- [ ] (Marco 6) Os 5 canais idênticos da falha, se os dados ainda existirem; o `.map` da `PRU_IMEM` (opcional)
- [ ] (Marco 7) `--fft` × `--welch` no mesmo sinal sintético com *dithering*
- [ ] (Marco 8) Layout de bytes do cabeçalho; resumo do cabeçalho impresso pelo `adc_tool.py`; teste de memória do HDF5
- [ ] (Marco 9) Espectro de corrente com e sem `--sem-correcao-sonda`
- [ ] (Marco 10) A aba *Actions* do GitHub com a CI passando; o diagrama de camadas (`software-architecture.md`, seção 3)
- [ ] (Marco 12) A curva do T3 com a teórica do datasheet por cima (opcional)

---

## 5. Estrutura Sugerida para uma Apresentação Longa (1 Hora)

Comece pelo resultado e use a cronologia para explicar o caminho até ele. Numa ordem estritamente cronológica, os números só aparecem depois de 50 minutos de implementação.

1. **Abertura (5 min):** o estado no relatório parcial e o estado de hoje, em uma frase cada (seção 1).
2. **Arquitetura atual (10 min):** PRU + ARM, *ping-pong*, modo automático e o formato da captura, sem o histórico ainda.
3. **Resultados (15 min):** primeiro os quantitativos do Marco 14 (escala, ruído, taxa e estabilidade, com a tabela da seção 8) e a curva do T3 (Marco 12). Depois, a evidência multi-canal (Marco 6) e uma análise de supraharmônicos (Marco 7): a aquisição funciona, e a análise também.
4. **Três problemas de engenharia e como foram diagnosticados (15 min):** os jumpers longos (Marco 4), os 24 contra 32 ciclos do modo automático (Marco 6) e o salto de 7 µs a cada bloco (Marco 13). Cada um no formato sintoma → ferramenta de diagnóstico → hipótese → teste → correção.
5. **Limitações e decisões (5 min):**
   * a banda (filtro interno do ADC, teto de 140 kS/s e *aliasing*);
   * a sensibilidade do canal de corrente;
   * a meta de taxa revista;
   * a correção dinâmica da taxa trocada por métodos off-line (seção 1.1).
6. **Próximos passos (5 min):** o Marco 17.
7. **Perguntas (5 min).**

Os Marcos 8 a 10 (formato da captura, sondas, qualidade de software) valem um slide cada; se faltar tempo, são os primeiros a ir para os slides de apoio.

---

## 6. Estrutura Sugerida para o Relatório Final

Sugestão: manter os capítulos do relatório parcial, para que o leitor da FAPESP compare os dois períodos lado a lado, e dizer logo no resumo o que mudou. Para cada capítulo, o que entra e de onde tirar.

| Capítulo | Conteúdo | Fonte |
|---|---|---|
| **Resumo** | O que foi feito no período (Assembly, modo automático, caracterização em bancada) e os 4 ou 5 números principais | Seções 1 e 8 |
| **Introdução** | Curta, remetendo ao relatório parcial; o objetivo do período: cumprir o plano 7.1 a 7.3 e passar da validação qualitativa à quantitativa | Seção 1.1 |
| **Fundamentação** (só o que é novo) | O ADS8688 por dentro: multiplexação (500 kS/s no total), faixas de entrada, o passa-baixa interno de 2ª ordem. Estimação espectral: FFT ciclo-sincronizada × Welch, normalização tom/ruído, janelas. Métricas de conversor: SINAD, SNR, ENOB e SFDR | Marcos 7 e 11; roteiro, fatos 1 a 3 |
| **Hardware e condicionamento** (objetivos 1 e 2 do projeto) | Cadeia de tensão: o divisor de 5 resistores, com a razão calculada e a medida. Cadeia de corrente: SCT013 sobre 0,12 Ω, 60 µV/A e o piso de detecção. A remoção dos filtros (plano 7.2), a faixa de entrada por canal e a ligação direta das placas | Roteiro, fatos 4 e 5; Marcos 4 e 14 |
| **Firmware** (plano 7.1) | Assembly e os problemas resolvidos; memória e *ping-pong*; modo automático; cabeçalho autodescritivo; a revisão de out/2026: grade de tempo, rebase do contador, integridade medida sem custo e a anatomia do quadro (o gargalo) | Marcos 2, 3, 6, 8, 9 e 13 |
| **Software de análise e método de validação** | Só o necessário para entender os resultados: `medir_captura.py` (o que mede e com que limites), a correção por perfil e a validação sintética (auditoria, testes, contrato C↔Python) | Marcos 5, 7, 9, 10 e 11 |
| **Resultados** | Uma seção por grupo de testes: (1) caracterização do ADC (T0, T1, T2; T5 quando houver); (2) taxa de amostragem e integridade (T4, T7, o defeito e a correção; T7e quando houver); (3) multiplexação (T6); (4) resposta em frequência da cadeia de tensão (T3); (5) sonda de corrente (T10); (6) supraharmônicos medidos (T9, T11) | Marcos 12 e 14; roteiro, parágrafos "Executado em" |
| **Discussão e limitações** | A lista abaixo | — |
| **Conclusões e trabalhos futuros** | O que o instrumento mede hoje, e com que exatidão. Futuro: esperas do CS reduzidas (~330 kS/s no papel), anti-aliasing externo, ganho antes do ADC no canal de corrente, medição de fase | Marco 17; `improvement-proposals.md` |
| **Referências** | As do relatório parcial ([1] a [11]), mais: a ABNT NBR IEC 61000-4-30 (2023, a edição brasileira da IEC 61000-4-30) e o PRODIST, Módulo 8, da ANEEL (a regulação brasileira de qualidade de energia; confira as revisões vigentes); a IEC 61000-4-7 (harmônicos e bandas de 2 a 9 kHz); Welch (1967), sobre o método; Harris (1978), sobre janelas; IEEE Std 1241 (teste de ADCs: SINAD, ENOB) e IEEE Std 1057 (ajuste de senoide, usado com o `.m` do osciloscópio); o datasheet SBAS582C do ADS8688 e o *AM335x PRU-ICSS Reference Guide*, nas seções citadas | — |

**Limitações a declarar** (a explicitação dos limites é parte do rigor do relatório):

* **Banda:** 100 kS/s de trabalho cobrem até ~45 kHz dos 150 kHz da faixa de supraharmônicos. O que está acima de Nyquist dobra para dentro da banda (o filtro interno do ADC atenua pouco).
* **O filtro interno do ADC** é corrigido pelo perfil, que amplifica o ruído na mesma proporção (+12,5 dB em 45 kHz na cadeia de tensão).
* **Só magnitude:** a correção de sonda não restaura a fase, e a fase da cadeia não foi medida.
* **Canal de corrente:** sensibilidade de 60 µV/A sobre a carga de 0,12 Ω, mesmo na menor faixa do ADC.
* **Dados de 19/10:** feitos com o firmware anterior à correção do salto de 6,97 µs (as análises de um bloco não são afetadas).
* **Transitório de 60 µs** depois de trocar a faixa de um canal.
* **Offset de ~3 mV** no canal de tensão, de origem ainda não isolada (DC, fora da banda).
* **Referências:** exatidão do osciloscópio (±1 %) e da TCP0030A (sem especificação acima de 5 kHz); o THD medido é o do gerador.
* **Margens de tempo:** as esperas do CS foram calibradas empiricamente e não otimizadas.

---

## 7. Apresentação Quinzenal ao Orientador

**Formato:** 6 a 8 slides, 10 a 15 minutos. Um resultado com número por slide. Sempre terminar com o plano da quinzena seguinte e com o que precisa de decisão do orientador.

**Modelo de slides:**

1. **Título e resumo:** a quinzena (datas) e uma frase com o principal avanço.
2. **O que foi combinado na última reunião:** cada item com ✅, 🟡 ou ❌ e uma linha de explicação.
3. **Resultados (2 ou 3 slides):** uma figura, o número que importa e o que ele significa para o instrumento. As figuras saem de `report/gerar_figuras.py`, do `adc_tool.py -o` ou do `--plot` do `gerar_perfil_sonda.py`.
4. **Problema ou achado:** sintoma → causa → o que foi feito → o que falta para fechar.
5. **Próxima quinzena:** de 3 a 5 itens, com prioridade, e os riscos.
6. **Decisões e pedidos:** o que depende do orientador (uma meta a rever, um ensaio na rede com supervisão, um componente a comprar, um horário de laboratório).

**Preparação (15 minutos):**

1. Atualize a tabela [Estado da campanha](lab-procedure.md#estado-da-campanha) do roteiro.
2. Veja o que entrou no período com `git log --since=AAAA-MM-DD --date=short --pretty='%ad %s'`.
3. Escolha 2 ou 3 figuras.
4. Acrescente a linha da quinzena ao registro abaixo: ele vira, no fim, a linha do tempo do relatório.

**Registro quinzenal.** As quinzenas anteriores foram reconstruídas pelo `git log` e contadas para trás a partir de 20/10/2026: ajuste-as às datas reais das reuniões.

| Quinzena | O que foi feito | Resultado com número | Marcos |
|---|---|---|---|
| 01/07 a 14/07/2026 | Início do firmware em Assembly na PRU; entrega do relatório parcial; teste de preâmbulo; "Assembly funcionando V0.1" | — | 2, 4 |
| 15/07 a 28/07 | (sem commits) ⚠️ | — | — |
| 29/07 a 11/08 | `adc_tool.py`: conversão `.bin`↔`.csv`, janelas de FFT; captura multi-canal no firmware (modo manual) | — | 3, 5 |
| 12/08 a 25/08 | Ajustes menores ⚠️ | — | — |
| 26/08 a 08/09 | Migração para o modo automático do ADS8688, validada com 1 e 5 canais | 5 canais a 102,4 kS/s no total | 6 |
| 09/09 a 22/09 | Amostragem contínua; Welch, bandas e picos; cabeçalho de metadados; primeiro compressor de amostras | Pico de 15 321,3 Hz recuperado em 15 321,37 Hz (sintético) | 7, 8 |
| 23/09 a 06/10 | Proposta de atualização; capturas "60 kHz puro" e "ruído injetado" ⚠️ | — | — |
| 07/10 a 20/10 | Cabeçalho v2 e perfis de sonda; pacote Python e testes; `medir_captura.py` e roteiro; faixa de entrada por canal; **primeiro dia de bancada** (19/10: T0 a T4, T6, T7); figuras do relatório; revisão do firmware | −3 dB em 17,3 kHz; ruído igual ao datasheet; taxa a 0,02 ppm do previsto; salto de 6,97 µs a cada bloco achado e corrigido | 9 a 14 |

**Quinzena de 07/10 a 20/10/2026, pronta para os slides:**

1. **Resumo:** "Primeiro dia de bancada: o ADC entrega o que o datasheet promete, a cadeia de tensão tem −3 dB em 17,3 kHz e achei e corrigi um defeito de tempo do firmware."
2. **Resultado 1, resposta em frequência da cadeia de tensão:** a figura do T3. Passa-baixa de 2ª ordem com f0 = 24,1 kHz e Q = 0,54. Por que importa: em 45 kHz o sinal chega 12,5 dB atenuado, e o perfil corrige.
3. **Resultado 2, o ADC confere:** a tabela de escala e ruído por faixa (Marco 14, linhas 1 e 2). Por que importa: valida a faixa de ±2,56 V para o canal de corrente.
4. **Resultado 3, taxa de amostragem e estabilidade:** a tabela do T4 e os 0,09 ppm em 10 min. Por que importa: a taxa é conhecida a ppm, e as frequências medidas são confiáveis.
5. **Achado, o salto de 7 µs a cada bloco:** a figura do salto no T7c. A causa estava no zeramento do contador de ciclos depois da última transação. Correção: rebase sem perda de tempo, verificada no simulador. Falta refazer o T7c no hardware.
6. **Achado, o gargalo de taxa:** a anatomia do quadro de 7 µs, em que 57 % são esperas do CS, ~100× o mínimo do datasheet. É o caminho para ~330 kS/s (T7e).
7. **Próxima quinzena:** recompilar e refazer o T7; o T7e; o T10-0 e o T10. Riscos: a sensibilidade do canal de corrente (60 µV/A) e o firmware novo não compilar no `clpru`.
8. **Decisões:** a meta de taxa revista (500 kS/s é o teto do ADC; 150 kHz exige ≥ 300 kS/s em 1 canal); se a correção dinâmica da taxa (plano 7.3) pode ser substituída pelos métodos off-line; e quando fazer o ensaio com a rede (T2c, T11c), que exige supervisão.

---

## 8. Números para Citar

Os números do projeto num lugar só, com a condição e a fonte. Os valores medidos referem-se ao canal 1 (divisor de tensão) e a 19/10/2026, salvo indicação. O registro completo de cada teste (data, firmware, pasta dos dados, condições, as figuras e as macros do LaTeX) está em [`bench-results.md`](bench-results.md).

| Grandeza | Valor | Condição | Fonte |
|---|---|---|---|
| ADC | ADS8688, 16 bits, 8 canais, **500 kS/s no total** | multiplexado; N canais → 500/N cada | Datasheet SBAS582C |
| Faixas de entrada usadas | ±10,24 V (tensão) e ±2,56 V (corrente); 1 LSB = 312,5 e 78,1 µV | `ler_adc --faixa-adc` | Roteiro, fato 3 |
| Escala nas três faixas | 0,9997 / 0,9997 / 0,9992 | DC de +10 V, descontado o offset | T0; Marco 14 |
| Ruído em curto | 160 / 91 / 58 µV RMS (0,51 / 0,58 / 0,75 LSB) | ±10,24 / ±5,12 / ±2,56 V; 100 kS/s | T1 |
| Offset no pino | canal 1: +2,5 a +3,5 mV; canal 0: +0,05 a +0,21 mV | entrada em curto | T1, T2 |
| Razão do divisor | 0,051554 medida; 0,05157 calculada com a carga do ADC; 0,051662 sem ela | Fluke 289, ±10 V | T2; roteiro, fato 4 |
| Linearidade | resíduo ≤ 0,22 LSB | ±0,5 V no pino | T2 |
| Sensibilidade do canal de corrente | 60 µV/A (`$GI` = 16 667 A/V) | SCT013 100A:50mA sobre 0,12 Ω; ainda não medida | Roteiro, fato 5 |
| Resposta da cadeia de tensão | −3 dB em 17,26 ± 0,16 kHz; f0 = 24,06 ± 0,21 kHz; Q = 0,540 ± 0,006; K = 0,9969 ± 0,0028; −12,5 dB em 45 kHz; resíduo de 0,13 dB | 48 pontos, 50 Hz a 45 kHz, 100 kS/s | T3; Marco 12 |
| Resposta da cadeia de tensão, magnitude e fase (ondas quadradas, sem referência) | −3 dB em 14,68 kHz; 2ª ordem com f0 = 22,811 kHz e Q = 0,5001 (dois polos reais) × polo real em 800 ± 16 kHz; resíduo de 0,0105 dB e 0,136°; fase mínima (magnitude e fase dão o mesmo filtro) | 24 quadradas, 256 Hz a 180 kHz, 312,5 e 400 kS/s (diferem 0,0005 dB e 0,004°) | T3f; Marco 16 |
| Taxa de amostragem | = 200 MHz ÷ ticks a 0,02 ppm; erro comum de −43,2 ppm (cristal + gerador) | 50 a 125 kS/s | T4 |
| SINAD / ENOB | 61 dB / 14,4 bits | 10 kHz a −27,5 dBFS, gerador sem filtro | T4 (prévia do T5) |
| THD medido | −71,6 dB (limitado pelo gerador; ADC: −102 dB no datasheet) | 10 kHz | T4 |
| Diafonia | −94,7 dB | 10 kHz, canal seguinte ao agressor | T6a |
| Atraso entre canais | 9,954 µs (esperado: 10,000 µs) | 2 canais a 100 kS/s | T6b |
| Estabilidade em 10 min | 0,09 ppm (frequência), 0,009 % (amplitude) | janelas de 1 bloco | T7c |
| Salto a cada bloco (firmware antigo) | 6,97 µs = +0,697 amostra a 100 kS/s, nas 57 trocas, ±0,002 | corrigido em out/2026, falta validar no hardware | T7c; Marco 13 |
| Transitório ao trocar a faixa | até ~1 V no pino; < 1 LSB em ~80 µs (~8 amostras a 100 kS/s), o mesmo tempo com 1 e 2 canais | só quando a faixa do canal muda; o `medir_captura.py` pula 200 µs | T0, T1; Marco 14 |
| Efeito do salto a cada bloco numa FFT de vários blocos | SINAD de 63 → ~22 dB (1 → 4 blocos); +1,5 ppm na frequência e −0,3 % na amplitude (2 blocos) | firmware antigo, 10 kHz | T4, T7; Marco 14 |
| Salto medido nas trocas × fora delas | 6,96 µs × 0,01 a 0,04 µs (critério: 10 vezes e 0,05 µs) | `medir_captura.py`, 1 a 8 canais | T6, T7; Marco 14 |
| Jitter de amostragem (firmware `v0.7`) | 8,5 ns rms, igual de 100 a 312,5 kS/s e de 3,1,3 a 200,100,100; triplica o ruído com um tom de 10 kHz (2,46 contra 0,78 LSB) | capturas de 21/10, tom de 10 kHz em ±2,56 V | T7f; Marco 16 |
| Degrau nas trocas de buffer (firmware `v0.7`) | +0,3 ns (±0,1 ns longe delas) | 312,5 kS/s, 2 trocas | T7f; Marco 16 |
| Jitter de amostragem (firmware de 22/10) | 0,00 ns (piso do método ~0,3 ns) | 100 e 312,5 kS/s, 1 e 2 canais, com o ARM ocupado | T7f; Marco 16 |
| Degraus de tempo (firmware de 22/10) | 89 trocas: −0,03 ± 0,03 ns; 28 rebases: −0,04 ± 0,07 ns (zero ciclo em todos) | 5 min a 312,5 kS/s | T7f; Marco 16 |
| Ruído com o tom de 10 kHz, fora de ±50 Hz dele e dos harmônicos | 2,23 → 0,77 LSB (= o ruído em curto); SNR 64,0 → 69,4 dB em 10 s | ±2,56 V, 312,5 kS/s | T7f; Marco 16 |
| Folga da PRU a 312,5 kS/s | 3 a 5 ciclos (15 a 25 ns); teto com período constante ~315 kS/s | troca de buffer ~636 ciclos, quadro comum ~620 | T7f; Marco 16 |
| Folga e teto com o quadro fixo (SPI lento) | folga de 25 ciclos a 312,5 kS/s com qualquer sinal; teto com período constante 327,9 kS/s (610 ticks) | quadro comum de 600 ciclos | T7f, 2ª rodada; Marco 16 |
| SPI rápido (~15,4 MHz) | 0 leituras divergentes (margem do SDO ≥ 15 ns para cada lado); ruído 0,80 contra 0,79 LSB; teto 419,3 kS/s (477 ticks); folga de 18 ciclos a 400 kS/s | 69 capturas; o padrão desde 22/10 | T7g; Marco 16 |
| Quadro SPI da PRU | 1 395 ciclos (6,98 µs; transação com o CS baixo: 1 166 ciclos), dos quais 800 (57 %) são as esperas do CS; em geral, 595 + 2 × (S + H + A) ciclos | simulador do `spi_core.asm` | Marco 13; roteiro, T7e |
| Teto de taxa | ~130 kS/s observados e ~140 kS/s pelo simulador; ~330 kS/s no papel com as esperas mínimas do datasheet | a medir no T7e | Marco 13 |
| Esperas do CS | 2,0 / 1,0 / 1,0 µs contra 30 / 10 / 30 ns do datasheet | tabela 7.6 do SBAS582C | Marco 13 |
| Buffers | 2 × 1 048 576 amostras (2 × 2 MB) na DDR; ~10 s por bloco a 100 kS/s | — | Marco 3 |
| Código da PRU | 1 878 instruções, 91,7 % da IMEM de 8 KB | `tests/pru_sim.py` | `project-context.md` |
| Arquivamento sem perdas | 11,0 % do tamanho (407 MB → 44,9 MB); 7-Zip: 14,6 % | capturas até o T3 | Marco 10 |
| Testes automáticos | ~760, ~1 min 20 s em paralelo, ~90 % de cobertura (a contagem exata do dia: `software-architecture.md`, seção 7) | sem hardware | Marco 10 |
