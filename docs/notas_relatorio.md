# Notas para Apresentação e Relatório Final — SH-Analyzer

> **Propósito deste documento:** registro cronológico do trabalho realizado
> desde a última apresentação à equipe, destinado a preservar os detalhes
> necessários tanto para a apresentação quanto para a redação do relatório
> final. Não constitui o texto definitivo de nenhum dos dois — trata-se da
> matéria-prima. Os itens marcados com `[ ]` e com "⚠️ confirme com você
> mesmo" devem ser preenchidos com base na memória do autor; o conteúdo
> apresentado sem essas marcações provém diretamente do código-fonte e dos
> testes já registrados, podendo ser utilizado com confiança.
>
> Última atualização: 15/09/2026 — cobre o período compreendido entre a
> última apresentação (placa ainda sem Assembly, modo manual, sem
> `adc_tool.py`, sem suporte multi-canal) e a implementação do cabeçalho de
> metadados com exportação para HDF5.

---

## 0. Como Usar Este Documento

1. Leia a linha do tempo (seção 2) de ponta a ponta uma vez, apenas para
   retomar o contexto geral.
2. Preencha os itens marcados **⚠️ confirme com você mesmo** — são
   informações que não podem ser inferidas com certeza a partir do código
   ou dos registros disponíveis (datas exatas, observações feitas no
   momento de um problema, capturas de tela ou fotografias).
3. Execute `git log --oneline --all` no repositório: os commits, mesmo com
   mensagens curtas, fornecem as datas reais de cada marco e ajudam a
   reconstruir a ordem cronológica caso haja alguma imprecisão neste
   documento.
4. Marque os itens `[ ]` de imagens conforme cada captura de tela ou
   fotografia for gerada — a seção 4 consolida a lista completa do que
   ainda falta registrar.
5. Utilize a seção 5 como roteiro para a apresentação e a seção 6 como
   roteiro para o relatório final.

---

## 1. Contexto Rápido

- **Projeto:** o SH-Analyzer é um instrumento para a medição de
  supraharmônicos (perturbações de dezenas de kHz) em redes elétricas,
  componente espectral que os analisadores comerciais de Qualidade de
  Energia Elétrica (QEE) não detectam adequadamente.
- **Relevância:** a crescente presença de conversores eletrônicos de
  potência (fontes chaveadas, inversores, etc.) na rede elétrica introduz
  esse tipo de perturbação — um problema de qualidade de energia em
  expansão e ainda pouco instrumentado.
- **Escopo do trabalho:** o projeto e a validação do instrumento de
  medição em si (hardware e firmware de aquisição), não a análise de
  supraharmônicos propriamente dita, que constitui uma etapa posterior, a
  ser conduzida sobre dados de bancada validados.
- **Estado na apresentação anterior:** protótipo em C executado
  diretamente no Linux da BeagleBone (sem uso da PRU), ADS8688 operando em
  modo manual, captura restrita a 1 canal, sem ferramenta de análise
  dedicada.
- **Estado atual:** firmware reescrito em Assembly, executado na PRU
  (determinístico, independente do escalonador do Linux); ADS8688 operando
  em modo automático (varredura sem reenvio de comando a cada amostra);
  captura multi-canal validada em hardware (5 canais testados); cada
  captura acompanhada de um cabeçalho de metadados autodescritivo
  (frequência, canais, timestamp, título/descrição, checksum de
  integridade); e ferramenta própria de análise em Python (`adc_tool.py`),
  com FFT livre de vazamento espectral, filtragem digital, suporte
  multi-canal completo e exportação para o formato HDF5.

---

## 2. Linha do Tempo Cronológica

### Marco 1 — Motivação para o Abandono do Protótipo em C

**Motivação:** o protótipo original, implementado em C, era executado
diretamente no processador ARM sob Linux — um sistema operacional de
propósito geral, sem garantias de tempo real (o código correspondente já
foi removido do repositório, mas seu comportamento permanece documentado
neste arquivo e em `docs/contexto_projeto.md`). Essa arquitetura limitava a
taxa de amostragem estável a aproximadamente **102,4 kHz**, provavelmente
em razão de *jitter* de escalonamento: o kernel podia interromper o laço de
aquisição a qualquer momento para atender a outras tarefas do sistema.

**Decisão de projeto:** migrar o laço crítico de temporização (bit-banging
SPI) para a **PRU** (Programmable Real-Time Unit) — um coprocessador
dedicado, sem sistema operacional, capaz de executar instruções de forma
totalmente determinística. Essa mudança exigiu a reescrita do núcleo de
aquisição em **Assembly**, uma vez que a PRU não executa código C com
eficiência suficiente para um bit-banging com restrições de tempo tão
rígidas.

- [ ] ⚠️ **Confirme com você mesmo:** há alguma captura de tela do
      protótipo em C que demonstre o limite de 102,4 kHz sendo excedido
      (dados corrompidos acima dessa taxa)? Caso exista, trata-se de uma
      evidência relevante para justificar a decisão de reescrita em
      Assembly.

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

**Correção:** o contador é reiniciado manualmente no início da aquisição e
a cada troca de buffer (esquema ping-pong; ver Marco 3).

**Problema 3 — restrição de memória de instruções (`PRU_IMEM`).** A PRU
dispõe de apenas 8 KB de memória de instruções. Para controlar a velocidade
do barramento SPI sem exceder esse limite, o firmware utiliza **laços de
atraso** (contagem regressiva) em vez de sequências repetidas de
instruções `NOP` — um `NOP` por ciclo desperdiçado consome 1 instrução de
código, enquanto um laço de atraso consome poucas instruções e pode
representar qualquer número de ciclos de espera.

- [ ] ⚠️ **Confirme com você mesmo:** qual foi a duração aproximada desta
      etapa? Foi a mais demorada do projeto? Vale mencionar na apresentação
      como o "custo" real da migração para Assembly, ainda que compensado
      pelos resultados obtidos.
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

**Causa raiz e correção:** os **jumpers longos** utilizados para conectar a
placa de aquisição ao frontend analógico na bancada. O problema foi
resolvido eliminando-se os jumpers e conectando as placas diretamente.

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

### Marco 5 — Ferramenta de Análise em Python (`adc_tool.py`)

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
  em **ordem crescente** de canal.
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
teste de condição como salto curto.

**Verificação do orçamento de memória:** a inspeção do arquivo `.map`
gerado pela compilação confirmou que o código coube com margem
confortável, utilizando aproximadamente 67% dos 8 KB de `PRU_IMEM`
disponíveis.

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
os canais habilitados.

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

### Marco 7 — Cabeçalho de Metadados e Exportação para HDF5

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

**Extensão da interface de linha de comando:** `ler_adc` passou a aceitar
`-o` (nome do arquivo de saída, com geração automática por timestamp na
ausência da flag), `-t` (título) e `-d` (descrição). Um cuidado de
implementação relevante: textos que excedam o espaço reservado no
cabeçalho são **rejeitados**, e não truncados — truncar uma string UTF-8 em
um limite de bytes arbitrário arrisca interromper uma sequência multibyte,
produzindo texto inválido gravado permanentemente no arquivo.

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

### Marco 8 — Trabalho Pendente

Apresentar esta seção é tão importante quanto apresentar o que já foi
realizado.

- **Validação quantitativa em bancada controlada:** a validação atual
  (Marco 6) é de natureza **qualitativa** — confirma que os canais
  apresentam comportamento distinto e plausível (sinal vs. ruído), mas não
  confirma a exatidão numérica da amplitude e da frequência medidas. A
  próxima etapa consiste em gerar um sinal/ruído de frequência e amplitude
  conhecidas em bancada controlada, realizar a medição com o SH-Analyzer e
  comparar o espectro medido com o sinal efetivamente injetado.
- **Validação em hardware do cabeçalho de metadados (Marco 7):** a
  implementação foi verificada por testes automatizados com arquivos
  sintéticos (offsets de campo, round-trip de CRC, perfil de memória), mas
  ainda não exercitada numa captura real na BeagleBone.
- As margens de tempo do sinal de CS (*chip-select*) associadas às
  transações SPI permanecem calibradas empiricamente, sem comparação
  formal com os tempos mínimos especificados no datasheet do ADS8688 —
  possível fonte de ganho de frequência máxima ainda não explorada.
- Risco identificado e não mitigado: a troca de buffer no esquema
  ping-pong não verifica se o processador principal concluiu o
  processamento do buffer anterior antes de iniciar sua sobrescrita —
  situação que pode ocasionar corrupção silenciosa de dados em frequências
  de amostragem mais elevadas.

Encerrar a apresentação com esta seção, de forma objetiva, demonstra
domínio preciso do estado atual do projeto e de seus próximos passos —
clareza valorizada por qualquer orientador.

---

## 3. Síntese por Marco (Revisão Rápida Antes da Apresentação)

1. O protótipo em C limitava a taxa de amostragem a aproximadamente
   102,4 kHz por ser executado sob um sistema operacional de propósito
   geral.
2. A reescrita em Assembly na PRU solucionou essa limitação, mas exigiu a
   resolução de falhas de temporização em nível de bit (leitura travada em
   fundo de escala) e de saturação de contador (interrupção de capturas
   longas).
3. A estrutura de memória compartilhada entre ARM e PRU passou por 3
   revisões, cada uma mais simples que a anterior, acompanhando a evolução
   do protocolo do ADC.
4. Uma falha de saturação SPI foi rastreada, com o auxílio de uma
   ferramenta de diagnóstico dedicada, até jumpers longos na bancada —
   corrigida por meio da conexão direta entre as placas.
5. Foi necessário o desenvolvimento de uma ferramenta própria de análise
   em Python (`adc_tool.py`) para viabilizar a validação de hardware e
   firmware; a ferramenta expandiu-se até incorporar FFT sem vazamento
   espectral e suporte multi-canal completo.
6. A migração para o modo automático do ADS8688 eliminou o reenvio de
   comando por amostra, envolveu a identificação e correção de uma falha
   real de protocolo (24 vs. 32 ciclos na escrita de registrador,
   identificada por meio de fontes primárias) e foi validada em hardware
   com 1 e com 5 canais simultâneos.
7. O cabeçalho de metadados de 1024 bytes tornou cada captura
   autodescritiva (frequência, canais, timestamp, título/descrição,
   CRC-32), e a exportação para HDF5, implementada com escrita em blocos
   sobre o arquivo mapeado em memória, foi validada quanto ao uso
   constante de memória por instrumentação com `tracemalloc`.
8. A próxima etapa é a validação quantitativa mediante sinal conhecido
   injetado em bancada controlada, incluindo a primeira validação em
   hardware real do cabeçalho de metadados.

---

## 4. Checklist Consolidado de Capturas de Tela e Imagens

- [ ] (Marco 1) Captura do protótipo em C evidenciando o limite de
      102,4 kHz
- [ ] (Marco 2) Diagrama de temporização de `CMD_BIT`/`DATA_BIT`
- [ ] (Marco 3) Diagrama comparativo das 3 versões da struct
      `shared_control`
- [ ] (Marco 4) Gráfico de saída de `analisar_preambulo.py`
- [ ] (Marco 4) Fotografia do setup com jumpers longos vs. placas
      conectadas diretamente
- [ ] (Marco 4) Forma de onda saturada vs. forma de onda íntegra
- [ ] (Marco 5) FFT limpa de uma medição real (60 Hz)
- [ ] (Marco 5) Comparativo de FFT com/sem a técnica de corte em ciclos
      inteiros
- [ ] (Marco 6) **[PRIORIDADE ALTA]** Saída do terminal de `ler_adc` com 5
      canais
- [ ] (Marco 6) **[PRIORIDADE ALTA]** Gráfico dos 5 canais (2 com sinal, 3
      com ruído)
- [ ] (Marco 6) Gráfico da falha (5 canais idênticos), caso os dados ainda
      estejam disponíveis
- [ ] (Marco 6) Captura de tela do `.map` do `PRU_IMEM` (opcional)
- [ ] (Marco 7) Diagrama do layout de bytes do cabeçalho
- [ ] (Marco 7) Captura do resumo do cabeçalho impresso por `adc_tool.py`
- [ ] (Marco 7) Gráfico/tabela do teste de memória da exportação HDF5

---

## 5. Estrutura Sugerida para a Apresentação (1 Hora)

Uma apresentação estritamente cronológica tende a postergar o resultado
mais relevante (a validação multi-canal) para o final, após aproximadamente
50 minutos de detalhes de implementação. Recomenda-se uma estrutura que
apresente o resultado logo no início e utilize a cronologia para explicar o
caminho percorrido até ele:

1. **Abertura (5 min):** situação do projeto na apresentação anterior e
   situação atual, em uma frase cada.
2. **Arquitetura atual (10 min):** PRU + ARM, esquema ping-pong, modo
   automático, formato de captura com cabeçalho de metadados — o
   funcionamento do sistema no estado atual, sem ainda abordar o histórico
   de desenvolvimento.
3. **Evidência de funcionamento (10 min):** o gráfico dos 5 canais (Marco
   6) — apresentar precocemente, por se tratar do resultado mais robusto.
4. **Trajetória técnica — principais desafios e suas soluções (20 min):**
   cronologia detalhada (Marcos 2, 4 e 6), apresentada como um relato dos
   problemas reais de engenharia encontrados e de como cada um foi
   diagnosticado e resolvido, e não como uma simples enumeração de eventos.
5. **Cabeçalho de metadados e exportação HDF5 (5 min):** Marco 7 —
   apresentado com menor profundidade que a etapa 4, por não envolver um
   processo de depuração de hardware; ênfase na motivação (rastreabilidade,
   interoperabilidade) e na verificação quantitativa de memória.
6. **Próximos passos (5 min):** Marco 8 — validação quantitativa e
   melhorias de desempenho identificadas, porém ainda não implementadas.
7. **Perguntas (5 min).**

> Nota: a distribuição de tempo acima já contempla o Marco 7; caso o tempo
> total disponível seja reduzido, este é o item mais adequado para
> supressão ou tratamento em um único slide de transição.

---

## 6. Estrutura Sugerida para o Relatório Final (Formato Artigo)

- **Introdução:** contextualização dos supraharmônicos, lacuna existente
  nos analisadores de QEE convencionais e objetivo do instrumento
  desenvolvido.
- **Arquitetura do sistema:** hardware (frontend analógico, isolamento
  galvânico), firmware (PRU/ARM, esquema ping-pong, modo automático) e
  formato de dados (cabeçalho de metadados, exportação HDF5).
- **Metodologia:** decisões técnicas específicas e respectiva justificativa
  — a opção pela PRU em detrimento do C puro, a opção pelo modo automático
  em detrimento do modo manual, a técnica de FFT sem vazamento espectral, e
  as decisões de formato do cabeçalho binário (compatibilidade C/Python,
  verificação de integridade).
- **Validação e Resultados:** a validação multi-canal atual (de natureza
  qualitativa), a verificação quantitativa do uso de memória na exportação
  HDF5 e, quando disponível, a validação quantitativa com sinal conhecido
  (Marco 8) — esta última seção constitui o núcleo científico do relatório.
- **Discussão e Limitações:** riscos e itens em aberto (ausência de
  backpressure no esquema ping-pong, margens de CS não comparadas
  formalmente ao datasheet, cabeçalho de metadados ainda não validado em
  hardware real) — a explicitação dos limites do próprio trabalho é parte
  constitutiva de um relatório científico rigoroso.
- **Conclusão e Trabalhos Futuros:** aumento da frequência de amostragem,
  diagnóstico de gargalos e expansão do uso da DDR reservada.
