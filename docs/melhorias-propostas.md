# SH-Analyzer — Sugestões de Melhoria

> Documento de revisão técnica cobrindo (1) o que pode ser feito para suportar taxas de
> amostragem maiores sem corromper dados, considerando firmware e hardware, e (2)
> reorganização/profissionalização do repositório para uso em portfólio. O script
> `adc_tool.py` foi propositalmente deixado de fora, conforme solicitado.
>
> Cada item indica **Impacto** (no desempenho/robustez ou na qualidade do projeto) e
> **Esforço** estimado, além de sinalizar quando a mudança toca o Assembly da PRU — que,
> pelo princípio já adotado no projeto, só deve ser considerada "pronta" depois de
> compilada com `clpru` e validada em hardware real.

---

## Parte 1 — Taxa de amostragem (firmware + hardware)

### 1.1 O teto real é o ADS8688, não a meta do projeto

O ADS8688 (SBAS582C) tem **500 kSPS de throughput agregado** somando todos os canais —
esse é o teto físico do chip, independentemente de quão rápido o barramento SPI seja
capaz de rodar. Vale registrar esse número explicitamente na documentação do projeto
(README ou `docs/architecture.md`), porque ele muda a forma de ler as metas de
desempenho: com captura de 1 canal, 500 kSPS é o limite superior absoluto; com N canais
intercalados, o limite por canal cai para 500 kSPS / N.

O comentário em `ler_adc.c` (`// Bem mais baixa - a transação agora leva ~21 us`) indica
que a implementação atual de bit-banging está fazendo transações a um ritmo muito mais
lento que esse teto (~21 us/transação ⇒ pouco menos de 50 kHz de taxa real possível,
contra os 500 kSPS que o ADC suportaria). Esse é o dado mais importante deste
documento: **o gargalo hoje é a implementação SPI na PRU, não o ADC nem o barramento
de dados** — é aí que o maior ganho está disponível.

**Impacto:** referência / não é uma ação isolada, mas orienta a priorização de tudo
abaixo.

---

### 1.2 Medir antes de otimizar: isolar onde o tempo por transação está indo

Antes de mexer em NOPs e loops de atraso, vale confirmar empiricamente onde os ~21 us
por transação estão sendo gastos, em vez de otimizar às cegas. Uma contagem rápida dos
ciclos "óbvios" (16 `CMD_BIT` + 16 `DATA_BIT`, mais os três laços de atraso do CS —
`delay_cs_setup`, `delay_cs_hold`, `delay_cs_high_minimo`) fica na casa de 5-7 us em
200 MHz — bem abaixo dos 21 us observados. A diferença provavelmente vem de instruções
que não custam 1 ciclo fixo: `SBBO` escrevendo na DDR externa (`DDR_RESERVED`, fora da
PRU) tende a ter latência bem maior do que um `SBBO`/`LBBO` local à DMEM da PRU, por
cruzar o interconnect até o EMIF; e o polling de `wait_time` (leitura do registrador
`CYCLE`) também soma ciclos que não aparecem numa contagem estática do código.

**Sugestão concreta:** usar um pino de PRU sobrando (ou reaproveitar um dos já
configurados em `setup.sh`) como "sonda" — setar/limpar esse pino ao redor de cada fase
da transação (CS setup, clock dos 32 bits, escrita na DDR, espera de `wait_time`) e medir
com o próprio osciloscópio que já está sendo usado para depurar o bug de saturação.
Isso transforma "onde está o tempo" de suposição em dado medido, e evita otimizar a
parte errada.

**Impacto:** Alto (orienta todo o resto). **Esforço:** Baixo. **Toca PRU asm:** sim
(instrumentação temporária, não precisa ir para produção).

---

### 1.3 Nenhuma validação de que a frequência pedida é alcançável

`ler_adc.c` valida `frequencia_desejada` apenas contra o limite de `500000 Hz` (teto do
próprio ADC), mas não contra o piso real da implementação atual (~21 us/transação ⇒
~47-48 kHz). Se alguém pedir, por exemplo, 100000 Hz, `sample_period_ticks` vai ser
calculado para um período menor do que o tempo mínimo real de uma transação — a PRU vai
simplesmente ficar para trás e amostrar no ritmo máximo que conseguir, **sem nenhum
aviso**. O arquivo `.bin` resultante ficaria com a frequência efetiva real diferente da
frequência nominal registrada/assumida pelo usuário na análise posterior — um jeito
silencioso de corromper a interpretação dos dados, mesmo que os bytes em si estejam
"corretos".

**Sugestão:** depois de medir o tempo real por transação (item 1.2), definir uma
constante `FREQUENCIA_MAXIMA_REAL_HZ` documentada em `ler_adc.c` (ou em `memoria_pru.h`,
já que é compartilhada), e fazer `ler_adc` recusar (ou pelo menos avisar bem alto em
stderr) qualquer `frequencia_desejada` acima desse valor.

**Impacto:** Alto. **Esforço:** Baixo. **Toca PRU asm:** não.

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
saturação, não necessariamente no valor mínimo válido.

**Sugestão de processo:** documentar ao lado de cada `LDI r1, N` a que parâmetro do
datasheet ele corresponde (nome do parâmetro + valor mínimo exigido + margem aplicada),
para que ajustes futuros sejam sistemáticos e não tentativa-e-erro. Isso também facilita
retestar esses valores quando o bug de saturação (item 1.8) for resolvido.

**Impacto:** Alto (efeito direto na taxa máxima). **Esforço:** Médio (requer datasheet
+ recompilar com `clpru` + validar em hardware a cada ajuste, um de cada vez). **Toca
PRU asm:** sim — só deve ser considerado pronto após compilar e validar em hardware.

---

### 1.5 Modo Auto/Auto_RST do ADS8688 como alternativa ao comando manual por frame

O ADS8688 tem, além do modo manual (usado hoje, um comando de canal enviado a cada
frame), um **modo automático de varredura** (seção "Auto Modes" / `AUTO_RST` do
SBAS582C): o host programa uma vez quais canais fazem parte da sequência, e o próprio
ADC avança pela sequência a cada frame sem precisar receber um novo comando de canal a
cada transação. Hoje, o firmware já faz esse round-robin **em software**, remontando e
reenviando o comando de 32 bits do canal atual a cada amostra (`spi_core.asm`, bloco
logo antes dos `CMD_BIT`) — usar o modo automático do próprio ADC eliminaria esse
trabalho repetido e, mais importante, pode reduzir a complexidade/tempo do frame em modo
multi-canal, já que o host deixaria de precisar montar e transmitir 16 bits de comando
específico por amostra.

**Ressalvas importantes, para não repetir esforço já gasto:**
- Isso é uma mudança de **protocolo**, não um ajuste de temporização — é bem mais
  arriscada que os itens anteriores e deve ser tratada como um experimento isolado
  (branch separado), só integrada à captura de produção depois de validada em hardware
  com o mesmo rigor já aplicado ao modo manual atual.
- A retrocompatibilidade com captura de 1 canal precisa ser preservada — se o modo
  automático for adotado, o caminho de 1 canal deveria continuar produzindo exatamente
  o mesmo formato de arquivo de hoje.
- Recomendo resolver primeiro o bug de saturação em aberto (item 1.8) no caminho manual
  já validado, e só then avaliar o modo automático — misturar as duas investigações ao
  mesmo tempo dificulta isolar a causa de qualquer novo problema.

**Impacto:** Alto, principalmente para captura multi-canal (menos overhead por canal).
**Esforço:** Alto. **Toca PRU asm:** sim.

---

### 1.6 Buffers ping-pong: risco real de corrupção silenciosa sem *backpressure*

Este é provavelmente o ponto mais importante deste documento para o objetivo de "não
corromper os dados medidos" em taxas mais altas.

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
sim, para as opções 2 e 3.

---

### 1.7 Usar mais dos 16 MB já reservados na DDR

`DDR_RESERVED` reserva 16 MB, mas a captura atual usa só 4 MB (2 buffers × 2 MB). Ampliar
para um esquema de N buffers (ex. 4 a 8 buffers de 1-2 MB cada, num anel em vez de só
ping-pong) dentro da mesma região já reservada dá mais folga temporal para o ARM
absorver picos de latência de I/O antes de um overrun acontecer — sem precisar pedir
mais memória ao sistema. Isso se soma bem com o item 1.6 (mais buffers dão mais tempo
antes que o problema de *backpressure* se manifeste, mesmo sem resolver a causa raiz).

**Impacto:** Médio-Alto. **Esforço:** Médio (mexe na struct de controle, no loop da PRU
e no loop de leitura do ARM). **Toca PRU asm:** sim.

---

### 1.8 Lado ARM: pontos de robustez que não dependem da PRU

Vários ganhos de robustez (e, indiretamente, de taxa sustentável) não exigem tocar em
Assembly nem recompilar com `clpru`:

- **`fwrite()` sem checagem de retorno.** Hoje, se o disco encher ou a escrita falhar no
  meio de uma captura longa, o programa continua rodando silenciosamente, perdendo dados
  sem avisar. Checar o valor de retorno de `fwrite()` contra o número de amostras
  esperado e abortar/avisar em caso de divergência é uma mudança pequena com impacto
  direto na confiabilidade dos dados.
- **`BLOCOS_PARA_CAPTURAR` fixo em 1 no código-fonte.** Hoje a captura sempre para depois
  de exatamente 1.048.576 amostras (1 buffer), e o segundo buffer do esquema ping-pong
  nunca chega a ser exercitado no uso padrão. Para análise de supraharmônicos de forma
  realista (janelas de observação mais longas, como sugerem normas como a IEC 61000-4-7)
  isso deveria ser um parâmetro de linha de comando (`argv[3]`, por exemplo), não uma
  constante de compilação — e, como efeito colateral, capturas mais longas vão de fato
  testar o comportamento do ping-pong em regime contínuo, o que hoje praticamente não
  acontece.
- **Prioridade de tempo real e menos jitter de escalonamento.** Rodar `ler_adc` com
  `SCHED_FIFO` (via `sched_setscheduler()`) e travar as páginas do processo em memória
  com `mlockall()` reduz a chance de o Linux preemptar o loop de polling por tempo
  suficiente para o problema do item 1.6 se manifestar. Combinado com colocar o
  `cpufreq governor` da BeagleBone em `performance` durante a captura (evita variações de
  clock do ARM no meio da aquisição), ajuda a manter o tempo de resposta do polling mais
  previsível.
- **Polling com `usleep(2000)` fixo.** Um atraso fixo de 2 ms a cada iteração do laço
  principal, independente de haver trabalho a fazer, soma uma folga de latência que fica
  cada vez mais relevante quanto mais curto for o tempo de preenchimento de um buffer em
  taxas altas. Vale reavaliar esse valor (ou substituir por uma espera mais reativa) à
  luz do tempo real de preenchimento de buffer na frequência-alvo.

**Impacto:** Alto (conjunto de mudanças de baixo risco e alto retorno). **Esforço:**
Baixo. **Toca PRU asm:** não.

---

### 1.9 Sincronização manual de constantes compartilhadas (risco documentado, mas ainda manual)

O próprio código já documenta com cuidado dois pontos de sincronização manual entre C e
Assembly: `SAMPLES_PER_BUFFER` (definido em `memoria_pru.h`, mas hardcoded em hexadecimal
via `LDI r21` em `spi_core.asm`) e o layout/tamanho de `comandos_canais[]`/
`ADS8688_MAX_CANAIS` (também assumido implicitamente no Assembly). Isso é um risco
conhecido e bem documentado nos comentários — o próximo passo natural é eliminar a
possibilidade de erro humano na sincronização, não só documentá-la.

**Sugestão:** gerar os valores usados no Assembly a partir de `memoria_pru.h` em tempo de
build, em vez de duplicá-los manualmente. Duas formas de fazer isso com o toolchain da
TI:
- Passar os valores como defines para o assembler (`clpru -d SAMPLES_PER_BUFFER=1048576
  ...`) e usar `.if`/diretivas do assembler para montar o `LDI` a partir da constante, em
  vez de escrever o hexadecimal já quebrado em `.w0`/`.w2`.
- Ou gerar um pequeno arquivo `.inc` incluído por `spi_core.asm`, produzido por uma regra
  do `Makefile` que lê `memoria_pru.h` (mesmo que com um script simples de extração,
  já que não há um parser de C disponível no fluxo de build).

Isso é especialmente relevante se `SAMPLES_PER_BUFFER` for alterado como parte do item
1.7 (mais buffers/buffers menores) — sem essa automação, cada mudança nesse valor é uma
nova chance de os dois lados ficarem dessincronizados sem erro de compilação nenhum.

**Impacto:** Médio (evita uma classe inteira de bugs futuros, não corrige um problema
existente). **Esforço:** Baixo-Médio. **Toca PRU asm:** sim (só a forma de gerar a
constante, não a lógica).

---

### 1.10 Hardware: plano de ataque para o bug de saturação já documentado

O README já aponta a hipótese mais provável (assimetria de tempo de subida/descida num
optoacoplador) e o próximo passo já planejado (eliminar jumpers longos, conectar as
placas diretamente). Algumas sugestões para complementar esse plano, já que ele é o
bloqueador mais crítico no momento — nenhuma otimização de firmware importa se o dado
capturado está saturado:

- **Depois** de eliminar os jumpers, se a distorção persistir, comparar o
  *pulse-width distortion* (PWD)/descasamento de atraso de propagação subida-vs-descida
  do isolador atual, no datasheet dele, contra o período de bit efetivo em uso hoje. Se o
  componente atual for um optoacoplador simples (tipo PC817 ou similar, pensado para
  chaveamento on/off, não para comunicação digital), é plausível que o PWD dele já seja
  uma fração significativa do período de bit mesmo nas frequências mais baixas testadas
  — nesse caso, a solução não é ajustar timing de firmware, é trocar por um isolador
  digital dedicado (ex. família ADuM/ISOxxxx/Si86xx), que tem PWD especificado e
  tipicamente muito menor, exatamente para esse tipo de uso.
- Capturar com o analisador lógico/osciloscópio diretamente nos pinos de SCLK/MOSI/MISO
  **na saída do isolador** (não só nos pinos da PRU), e comparar se a distorção aparece
  simetricamente em todas as transições ou só num sentido (subida vs. descida) — isso
  ajuda a diferenciar entre "é o isolador" e "é integridade de sinal/trilha/aterramento".
- Prever pontos de teste (test points) explícitos para SCLK/CS/MOSI/MISO de cada lado da
  barreira de isolamento na próxima revisão da PCB, já que a depuração atual depende de
  jumpers/pontas de prova improvisadas.
- Boas práticas gerais de layout para o frontend do ADC, caso ainda não estejam
  aplicadas: capacitores de desacoplamento de baixo ESR o mais próximo possível dos pinos
  de alimentação do ADS8688, plano de terra único com separação analógica/digital
  conectada em um só ponto, e trilhas de SPI o mais curtas possível entre o isolador e o
  ADC/PRU.

**Impacto:** Alto (é o bloqueador atual). **Esforço:** Médio (compra de componente +
possível ajuste de PCB, mas escopo pequeno e localizado).

---

## Parte 2 — Estrutura de projeto e profissionalização

### 2.1 Reorganização de diretórios

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
├── legacy/                      # renomeado de "backup pre-assembly/"
├── .gitignore                   # novo
├── LICENSE
└── README.md
```

O único ponto que eu mudaria com mais convicção: renomear `backup pre-assembly/` (tem
espaço no nome) para algo como `legacy/` ou `archive/prototipo-c/`. Espaço em nome de
diretório é fonte constante de atrito em linha de comando, scripts e alguns clientes
Git/CI — pequena mudança, remove um incômodo real.

**Impacto:** Médio (organização/portfólio). **Esforço:** Baixo.

---

### 2.2 `.gitignore`

Não há menção de um `.gitignore` no projeto. Os artefatos de build já são conhecidos
(o próprio `make clean` já lista boa parte deles) — vale garantir que nunca sejam
commitados por engano:

```gitignore
# Firmware — artefatos de build
firmware/ler_adc
firmware/fw_pru.out
firmware/*.map
firmware/*.obj
firmware/supraharmonicos_raw.bin

# Capturas de dados (grandes, não pertencem ao histórico do repositório)
*.bin
*.csv

# Python
__pycache__/
*.pyc
.venv/

# Editor/SO
.vscode/
*.swp
.DS_Store
```

Vale revisar se algum `.bin`/`.csv` de exemplo pequeno (para os testes do item 2.5)
precisa de exceção explícita (`!scripts/tests/fixtures/exemplo.bin`).

**Impacto:** Médio. **Esforço:** Baixo.

---

### 2.3 Metadados de captura (sidecar file) — resolve uma dor já documentada várias vezes

O próprio código comenta repetidamente que o `.bin` "não carrega metadado nenhum" e que
o usuário precisa "guardar essa lista e essa ordem" de canais manualmente, anotando o que
`ler_adc` imprime no console. Isso é uma fonte natural de erro humano (esquecer a lista
de canais usada, confundir a ordem, perder a frequência exata usada numa captura
antiga).

**Sugestão:** ao final de cada captura, `ler_adc.c` grava um arquivo lateral pequeno
(ex. `supraharmonicos_raw.json`, mesmo nome-base do `.bin`) com os parâmetros da
captura:

```json
{
  "frequencia_hz": 102400,
  "canais": [0, 1, 3],
  "formato": "uint16",
  "amostras_totais": 3145728,
  "samples_per_buffer": 1048576,
  "timestamp_utc": "2026-08-13T14:32:01Z",
  "firmware_git_hash": "a1b2c3d"
}
```

Isso elimina de vez a necessidade de copiar manualmente a lista de canais impressa no
console para usar depois — o arquivo já carrega tudo que uma ferramenta de análise
precisaria para se autoconfigurar. `firmware_git_hash` (ver próximo item) também dá
rastreabilidade: fica registrado exatamente qual versão do firmware gerou aquela
captura, útil ao comparar capturas feitas antes/depois de alguma mudança de timing.

**Impacto:** Médio-Alto (elimina uma classe de erro humano já documentada no próprio
código). **Esforço:** Baixo. **Toca PRU asm:** não.

---

### 2.4 Rastreabilidade de versão do firmware

Hoje não há como saber, olhando só para um `.bin` capturado, qual versão exata do
firmware da PRU o gerou — relevante especialmente enquanto os ajustes de timing do item
1.4 estiverem em andamento (comparar capturas de antes/depois exige saber qual firmware
rodava em cada uma). Uma forma simples: gerar, no `Makefile`, uma constante com o hash
curto do commit atual (`git rev-parse --short HEAD`) e embuti-la tanto no binário do ARM
(para imprimir no console) quanto no metadado sidecar do item 2.3.

**Impacto:** Médio. **Esforço:** Baixo.

---

### 2.5 Testes e CI

Boa parte da disciplina de validação já existe no projeto (testes funcionais com
capturas sintéticas, `ast.parse`/`pyflakes` antes de fechar mudanças) — falta
formalizá-la em algo que rode sozinho:

- **Extrair lógica testável do `ler_adc.c`.** Funções como `analisar_lista_canais()` e
  `comando_canal()` são lógica pura (sem acesso a `/dev/mem`), mas hoje estão `static`
  dentro de `ler_adc.c`, o que dificulta testá-las isoladamente. Movê-las para um par
  `canal_utils.c`/`canal_utils.h` separado permite compilar um pequeno executável de
  teste no host (sem precisar da BeagleBone) que valida casos como lista vazia, canal
  repetido, canal fora de 0-7, mais de 8 canais — o tipo de teste que hoje só existe,
  possivelmente, como verificação manual.
- **CI leve (GitHub Actions), só com o que é seguro automatizar:**
  - `make arm` (compila `ler_adc.c` com `gcc -Wall -Wextra`) — não depende de hardware
    nem do `clpru` (que é uma toolchain proprietária da TI, difícil de automatizar em CI
    pública), então roda em qualquer runner padrão.
  - Os testes de host do item acima (`canal_utils`).
  - Lint do lado Python com `pyflakes`/`ruff` (sem entrar em `adc_tool.py` em si, já que
    ele foi deixado de fora desta revisão — mas manter o lint automatizado no pipeline é
    uma boa prática geral do repositório).
  - Deixar claro no README/CI que a build da PRU (`clpru`) e a validação em hardware
    continuam sendo passos manuais, documentados, não automatizados — é uma limitação
    honesta, não uma lacuna escondida.

**Impacto:** Médio (qualidade/portfólio — sinaliza rigor de engenharia de forma
verificável). **Esforço:** Baixo-Médio.

---

### 2.6 `setup.sh` mais defensivo

O script já tem um comentário útil avisando sobre o risco de nome de arquivo errado
(`teste_spi_pru.out` vs `fw_pru.out`) e sugere checar o `dmesg` manualmente depois do
`start`. Dá para automatizar essa checagem em vez de depender de o operador lembrar de
rodar o comando sugerido:

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

Pequena mudança, mas transforma "dica para conferir manualmente" em falha explícita e
imediata — relevante porque um firmware não carregado corretamente, hoje, não dá erro
nenhum no terminal (é exatamente o risco que o comentário já identifica).

**Impacto:** Médio. **Esforço:** Baixo.

---

### 2.7 Documentação consolidada

- **`docs/architecture.md`** — um diagrama simples do fluxo ARM ↔ PRU ↔ DDR ↔ ADC ajuda
  muito mais do que texto para quem chega no projeto pela primeira vez (avaliador,
  recrutador, colega de laboratório). Como ponto de partida, um diagrama em Mermaid
  (renderizado nativamente pelo GitHub dentro de arquivos `.md`):

  ```mermaid
  flowchart LR
      subgraph ARM["ARM / Linux — ler_adc.c"]
          A1[Lê argv: frequência, canais] --> A2[mmap /dev/mem:<br/>shared_control + DDR_RESERVED]
          A2 --> A3[Escreve config:<br/>buffers, num_canais, comandos_canais]
          A3 --> A4[config_ready = 1]
          A4 --> A5[Poll buffer_X_ready]
          A5 -->|pronto| A6[fwrite bloco -> .bin]
          A6 --> A5
      end

      subgraph PRU["PRU0 — pru_main.c + spi_core.asm"]
          P1[Aguarda config_ready] --> P2[Lê config uma única vez]
          P2 --> P3[Laço principal:<br/>bit-bang SPI, 32 ciclos/amostra]
          P3 --> P4[Grava amostra na DDR<br/>buffer ping-pong ativo]
          P4 --> P5{Buffer cheio?}
          P5 -->|não| P3
          P5 -->|sim| P6[Marca ready=1<br/>troca de buffer]
          P6 --> P3
      end

      ADC[("ADS8688<br/>via SPI + isolamento galvânico")]
      P3 <--> ADC
      A3 -.shared_control.-> P1
      P4 -.DDR_RESERVED.-> A6
  ```

- **`docs/licoes-aprendidas.md`** — boa parte do histórico de depuração hoje vive
  espalhado em comentários de código (ex.: a tentativa de MOSI "branchless" que não deu
  certo na prática, a suspeita de assimetria do optoacoplador, o motivo de descartar a
  primeira amostra do lado ARM em vez da PRU). Isso é conhecimento valioso, mas fica
  menos visível para quem não lê o Assembly linha a linha. Consolidar num documento
  narrativo (o que foi tentado, o que funcionou, o que não funcionou e por quê) é
  exatamente o tipo de material que demonstra rigor de engenharia para um portfólio —
  e os comentários no código podem continuar existindo, só passam a apontar para a
  versão mais completa da história.

**Impacto:** Médio-Alto para fins de portfólio. **Esforço:** Baixo-Médio (é
consolidação de conteúdo que já existe, não pesquisa nova).

---

## Parte 3 — Priorização sugerida

| # | Item | Impacto | Esforço | Toca PRU asm? |
|---|------|---------|---------|----------------|
| 1.6 | Detecção/backpressure de overrun no ping-pong | Alto | Baixo–Médio | Sim (versões mais completas) |
| 1.8 | `fwrite` sem checagem, `BLOCOS_PARA_CAPTURAR` fixo, SCHED_FIFO | Alto | Baixo | Não |
| 1.3 | Validar frequência pedida contra piso real | Alto | Baixo | Não |
| 1.10 | Plano de ataque ao bug de saturação (isolador/sinal) | Alto | Médio | Não (hardware) |
| 1.2 | Instrumentar e medir onde o tempo por transação vai | Alto | Baixo | Sim (temporário) |
| 1.4 | Revisar atrasos fixos com base no datasheet | Alto | Médio | Sim |
| 2.3 | Metadado sidecar da captura (.json) | Médio–Alto | Baixo | Não |
| 1.7 | Mais buffers dentro dos 16 MB já reservados | Médio–Alto | Médio | Sim |
| 2.1 / 2.2 | Reorganizar diretórios + `.gitignore` | Médio | Baixo | Não |
| 2.7 | `docs/architecture.md` + lições aprendidas | Médio–Alto | Baixo–Médio | Não |
| 1.9 | Gerar constantes compartilhadas em vez de duplicar | Médio | Baixo–Médio | Sim (só geração) |
| 2.5 | Extrair lógica testável + CI leve | Médio | Baixo–Médio | Não |
| 2.6 | `setup.sh` com checagem automática de estado | Médio | Baixo | Não |
| 2.4 | Hash do commit embutido no firmware/binário | Médio | Baixo | Não |
| 1.5 | Modo Auto/Auto_RST do ADS8688 | Alto (multi-canal) | Alto | Sim |

**Sugestão de ordem de ataque:** primeiro os itens que são puramente do lado ARM/C e de
processo (1.8, 1.3, 2.1–2.7) — baixo risco, ganho imediato de robustez e de
apresentação do repositório. Em paralelo, resolver o bug de saturação (1.10), já que ele
bloqueia qualquer conclusão confiável sobre timing. Só depois disso partir para ajustes
de timing na PRU (1.2 → 1.4) e, por último, considerar uma mudança de protocolo maior
como o modo Auto (1.5), que deve ser tratada como um experimento à parte.

---

## Notas finais

Nenhuma sugestão de Assembly/PRU acima deve ser considerada pronta sem passar pelo
mesmo processo já em uso no projeto: compilar com `clpru` e validar em hardware real
antes de qualquer merge para o caminho de produção. Da mesma forma, qualquer mudança que
toque o formato de captura de 1 canal precisa preservar compatibilidade
byte-a-byte com o comportamento atual, já que isso é um requisito consolidado do
projeto.
