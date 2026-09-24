# SH-Analyzer — Proposta: Correção de Sondas de Corrente e Metadados de Grandeza por Canal

> Documento de proposta técnica — **nada aqui foi implementado**. Cobre como suportar
> captura simultânea de tensão e corrente (e, futuramente, temperatura) em canais
> diferentes do ADS8688, com correção de ganho dependente de frequência para sondas de
> corrente, perfis de sonda reutilizáveis e trocáveis entre ensaios, e metadados de
> grandeza física por canal gravados no cabeçalho da captura. Escrito para discussão e
> priorização antes de qualquer mudança em `firmware/` ou `scripts/adc_tool.py`.

---

## 1. Problema

Hoje `adc_tool.py` corrige cada canal com um ganho **escalar fixo** (`--ganho`), aplicado
igualmente em toda a faixa de frequência. Isso é correto para tensão (o frontend aplica um
divisor/ganho constante), mas não para corrente: uma sonda de corrente atenua o sinal em
magnitudes diferentes conforme a frequência — um valor fixo produz leitura de amplitude
incorreta em supraharmônicos, que é justamente o conteúdo de interesse deste projeto.

Requisitos que motivam esta proposta:

1. Suportar 2+ canais medindo grandezas diferentes (tensão, corrente, e no futuro
   temperatura) numa mesma captura.
2. Corrigir corrente com uma curva de ganho por frequência, não um escalar.
3. Poder trocar de sonda de corrente entre ensaios, com uma forma prática de criar e
   manter o "perfil" de cada sonda.
4. No `adc_tool.py`, bastar informar o **nome/código** da sonda para que a correção seja
   aplicada — sem repetir a curva de calibração na linha de comando.
5. O identificador da sonda usada em cada canal deve ser gravado nos metadados do arquivo
   `.bin` no momento da captura, para nunca precisar ser informado de novo na análise.
6. A grandeza física de cada canal (tensão / corrente / temperatura) também deve constar
   nos metadados.

## 2. Visão geral da arquitetura proposta

Mantém a separação de responsabilidades já usada no projeto: o lado ARM (`ler_adc.c`) só
**rotula** o que cada canal mede e qual sonda foi usada — ele não abre nem interpreta
nenhum arquivo de calibração. Toda a lógica de correção (curva de ganho, interpolação,
aplicação no sinal) fica em `adc_tool.py`, no computador de análise.

```
Captura (BeagleBone)                         Análise (adc_tool.py)
─────────────────────                        ──────────────────────
ler_adc.c recebe --grandeza/--sonda    ---->  Lê grandeza_por_canal e
por canal, grava no cabeçalho .bin            sonda_id_por_canal do cabeçalho
(apenas identificadores, sem lógica)
                                               Resolve o perfil (JSON) pelo id
                                               em scripts/sondas/<id>.json

                                               Aplica correção dependente de
                                               frequência só nos canais de
                                               corrente, antes do resto do
                                               pipeline (FFT/Welch/plot)
```

## 3. Perfil de sensor (formato de arquivo)

Em vez de modelar isso só para sondas de corrente, propõe-se um conceito mais genérico de
**perfil de sensor**, com um campo `tipo` que distingue o modelo de correção:

- `ganho_fixo` — caso trivial, cobre o que tensão já usa hoje.
- `resposta_frequencia` — tabela de pontos `(frequência, ganho[, fase])`, o caso das
  sondas de corrente.
- `polinomio` / `tabela` — reservado para temperatura no futuro (termopar, RTD etc., que
  tipicamente não seguem `ganho × código − offset`).

Isso evita ter que mudar o formato de novo quando temperatura for implementada de fato.

**Local dos arquivos:** `scripts/sondas/<id>.json`, um arquivo por sonda.

**Exemplo ilustrativo** (`scripts/sondas/fluke_i30_sn0001.json`):

```json
{
  "id": "fluke_i30_sn0001",
  "tipo": "resposta_frequencia",
  "fabricante": "Fluke",
  "modelo": "i30s",
  "numero_serie": "0001",
  "tipo_saida": "mV/A",
  "corrente_nominal_a": 30,
  "faixa_freq_valida_hz": [10, 100000],
  "data_calibracao": "2026-09-20",
  "calibrado_com": "cadeia completa SH-Analyzer (sonda + isolador + ADS8688)",
  "incerteza_estimada_pct": 2.0,
  "pontos": [
    {"freq_hz": 60,    "ganho": 1.000},
    {"freq_hz": 500,   "ganho": 0.987},
    {"freq_hz": 2000,  "ganho": 0.941},
    {"freq_hz": 10000, "ganho": 0.812, "fase_graus": -4.2}
  ]
}
```

Campos como `fase_graus` ficam opcionais desde já — não são necessários para a análise
atual (só usa magnitude em dB), mas o formato já comporta se um dia for preciso calcular
fator de potência ou defasagem tensão×corrente, sem quebrar perfis antigos.

**Resolução do perfil em `adc_tool.py`**, seguindo o mesmo padrão de 3 níveis já usado
para `--canais`/`--faixa`:

1. `--sonda-perfil ARQUIVO` explícito na linha de comando (maior prioridade).
2. `sonda_id` lido do cabeçalho da captura → busca em `scripts/sondas/` (ou em
   `--sondas-dir DIR`, se apontado).
3. Erro claro se nenhum dos dois resolver, para o canal marcado como corrente.

## 4. Extensão do cabeçalho `.bin` (versão 2)

Os campos reais do cabeçalho hoje somam 408 dos 1024 bytes totais — há ~616 bytes de
padding disponíveis, espaço de sobra para os campos novos.

| Campo novo | Tipo | Indexação | Descrição |
|---|---|---|---|
| `grandeza_por_canal` | `uint8_t[8]` | mesma posição de `lista_canais[i]` | `0`=tensão, `1`=corrente, `2`=temperatura, `0xFF`=slot não usado |
| `sonda_id_por_canal` | `char[8][16]` | idem | id ASCII da sonda; string vazia quando não se aplica (tensão, temperatura sem sonda dedicada) |
| `sonda_perfil_crc32_por_canal` | `uint32_t[8]` | idem | CRC-32 do arquivo de perfil usado no momento da captura — rastreabilidade, mesma ideia já sugerida para `firmware_git_hash` em `docs/melhorias-propostas.md` |

**Indexação por posição, não por número de canal físico** — o mesmo padrão que
`lista_canais[8]` já usa hoje (posição *i* descreve o *i*-ésimo canal habilitado, em
ordem crescente). Consistente com o resto da struct, sem inventar uma convenção nova.

**`versao_cabecalho` sobe para `2`.** Ponto de implementação que precisa de atenção:
`ler_cabecalho()` em `adc_tool.py` hoje **não** ramifica o formato de `struct.unpack`
pela versão — ela só avisa se a versão for diferente da esperada e tenta desempacotar do
mesmo jeito. Para v1/v2 coexistirem de verdade, a função precisa ler `magic` +
`versao_cabecalho` primeiro (8 bytes) e só então escolher qual format string de
`struct.unpack` usar — arquivos v1 continuam sendo lidos com o formato antigo (sem sonda,
grandeza assumida como tensão em todos os canais, mesmo comportamento de hoje).

**Offsets exatos não devem ser hardcoded em lugar nenhum** — mesmo princípio que o
projeto já aplica no cabeçalho atual (padding calculado em tempo de compilação a partir
de `sizeof(...)`, não contado na mão). O `struct.calcsize`/format string do lado Python
é a única fonte de verdade a manter sincronizada com o struct do lado C, exatamente como
já acontece hoje.

## 5. Mudanças em `ler_adc.c` (lado ARM)

Novas flags, **chaveadas pelo número do canal**, não pela posição em que foi digitado:

```
sudo ./ler_adc 102400 0,1,3 \
    --grandeza 0:tensao,1:corrente,3:corrente \
    --sonda 1:fluke_i30_sn0001,3:tp_101_sn2
```

Isso é deliberado, não estético: `analisar_lista_canais()` **reordena** a lista de canais
em ordem crescente antes de montar a máscara (é assim que o modo automático do ADS8688
exige). Uma flag posicional alinhada à ordem *digitada* (`--grandeza tensao,corrente`)
reproduziria a mesma classe de bug de desalinhamento que o projeto já corrigiu uma vez ao
migrar para o modo automático. `ler_adc.c` traduz `canal → posição pós-ordenação`
internamente antes de preencher os arrays do cabeçalho.

Escopo do que `ler_adc.c` faz e não faz:

- Valida que `grandeza` é um dos valores conhecidos (`tensao`/`corrente`/`temperatura`) e
  que `sonda` só é aceita para canais de corrente (ou emite aviso se usada noutro tipo).
- **Não** abre, valida ou interpreta o arquivo JSON do perfil — só grava a string do id
  recebida na linha de comando. O perfil só precisa existir no computador de análise, não
  na BeagleBone.
- Sem `--grandeza`/`--sonda`, mantém o comportamento atual (implicitamente tensão em
  todos os canais, sem sonda) — sem quebrar `setup.sh` nem uso existente.

## 6. Mudanças em `adc_tool.py` (lado Python)

### 6.1 Por que a correção não pode ser um escalar

Um ganho que varia com a frequência só faz sentido aplicado por *bin* de frequência — não
existe um único fator de tempo que o represente corretamente sobre um sinal de banda
larga (fundamental + harmônicos + supraharmônicos).

### 6.2 Abordagem recomendada — correção espectral direta

Aplicada como uma etapa de pré-processamento que devolve um sinal **já corrigido no
tempo**, antes de `recortar_ciclos_inteiros`, `calcular_espectro`,
`calcular_espectro_welch` e da plotagem — nenhuma dessas funções precisa saber que existe
uma sonda:

1. `rfft` do trecho selecionado do canal de corrente (mesma função já importada).
2. Interpolar o ganho calibrado (poucos pontos) sobre todo o eixo `rfftfreq` do sinal.
   Recomenda-se **PCHIP** (interpolação monotônica, sem *overshoot*) sobre
   `(log-frequência, ganho em dB)` — resposta de sonda tipicamente varia suave em escala
   log, e uma spline cúbica comum pode gerar oscilação espúria entre pontos.
3. Multiplicar o espectro por `1 / ganho(f)` interpolado. Como é um fator real e positivo
   por bin, isso é uma correção de **magnitude pura** — não altera fase, o que é
   suficiente para tudo que o pipeline hoje calcula (amplitude em dB via `--fft`/`--welch`).
4. `irfft` de volta para o tempo.

**Fora da faixa calibrada** (`faixa_freq_valida_hz` do perfil): bloquear com erro, ou pelo
menos avisar bem alto — nunca extrapolar livremente. Um ganho extrapolado além do range
medido pode inverter a tendência real (ex.: um rolloff que na prática volta a subir por
ressonância parasita fora da faixa calibrada).

**Alternativa considerada e descartada como primeira opção:** projetar um filtro FIR via
`scipy.signal.firwin2` a partir dos pontos e aplicar no mesmo estilo dos filtros
Butterworth `sosfiltfilt` já existentes. Funcionaria, e seria preferível se o projeto
migrar para processamento em blocos/streaming no modo de plotagem — mas hoje esse modo já
carrega o trecho selecionado inteiro num `ndarray`, então a divisão espectral direta é
mais simples e reaproveita ferramentas já importadas (`rfft`/`rfftfreq`).

### 6.3 Outras mudanças necessárias

- **Rótulo de eixo por grandeza.** `plotar_multicanal` hoje fixa `"Tensão (V)"` sempre no
  eixo Y do tempo. Com `grandeza_por_canal` disponível, isso precisa virar dinâmico (V, A,
  °C conforme o canal) — bug real que esta feature expõe, não só uma melhoria estética.
- **Fallback para canal de corrente sem perfil ainda disponível:** manter `--ganho`
  escalar funcionando como hoje, como correção aproximada enquanto o perfil real da sonda
  não existe.
- **`--sem-correcao-sonda`:** flag de depuração para ver o espectro bruto (sem correção de
  sonda) lado a lado com o corrigido.
- **Exportação HDF5:** gravar `grandeza`, `sonda_id` e a própria curva de calibração usada
  como atributos/dataset na raiz do `.h5`, mantendo-o autodescritivo sem depender do
  arquivo de perfil original continuar existindo.

## 7. Metodologia prática de calibração de sonda

**Pergunta original: é suficiente medir uma corrente conhecida em alguns pontos de
frequência planejados (ex.: 15 a 25 pontos)?**

Sim — essa é a forma padrão de caracterizar resposta em frequência de um transdutor
(uma calibração tipo "Bode"), não uma simplificação grosseira. Pontos a cuidar:

- **Espaçamento log, não linear.** Mais denso perto dos extremos prováveis de "joelho" da
  curva (rolloff de baixa frequência e limite de banda em alta), mais esparso no meio da
  faixa "plana". O datasheet da sonda costuma indicar onde ficam esses joelhos.
- **Referência confiável.** Gerador de sinal + resistor *shunt* de precisão em série
  (corrente real = `V_gerador / R_shunt`), ou fonte de corrente calibrada.
  `ganho(f) = amplitude_medida_pelo_SH-Analyzer(f) / corrente_real_injetada(f)`.
- **Ponto sutil importante:** se a "verdade" vier do próprio SH-Analyzer medindo o shunt
  (mesma cadeia ADC + isolador + PCB), o perfil resultante caracteriza **sonda + cadeia de
  aquisição combinadas**, não a sonda isolada. Isso é aceitável — e até desejável, já que
  é sempre essa mesma cadeia que será usada — mas deve ficar documentado no campo
  `calibrado_com` do perfil: se o frontend mudar (outro ganho, outro canal), o perfil
  perde validade e precisa ser refeito.
- **Extração da amplitude em cada ponto de calibração:** usar a ferramenta que já existe —
  `--fft --picos` (modo `tom`) ou `--welch` com resolução fina sobre o tom injetado — em
  vez de ler amplitude "no olho" do gráfico.
- **Validação da interpolação:** reservar algumas frequências *fora* do conjunto usado na
  calibração (intercaladas entre os pontos calibrados) e conferir se a curva interpolada
  prevê bem esses pontos. Isso detecta uma calibração subamostrada — por exemplo, uma
  ressonância entre dois pontos calibrados que a interpolação simplesmente não capturou.
- **Repetição:** `--welch` já promedia por natureza, então o ruído de medição em cada
  ponto tende a ser baixo; ainda assim, repetir 2-3 medições por frequência e promediar o
  ganho extraído é barato e reduz o risco de um ponto ruim isolado distorcer a curva.

### 7.1 Ferramenta futura: `scripts/calibrar_sonda.py`

Fecha o laço entre medir e gerar o perfil: recebe a corrente injetada conhecida por
frequência (manual, ou de um log do gerador de sinal), mede automaticamente via
`adc_tool.py`/Welch em cada frequência planejada, calcula `ganho(f)` ponto a ponto, e
escreve o JSON do perfil pronto em `scripts/sondas/`. Elimina aritmética manual do
processo de calibração.

## 8. Sugestões extras

- **Perfil de sensor genérico** (seção 3) em vez de específico para corrente — evita
  remodelar o formato quando temperatura for implementada.
- **Entrada alternativa em CSV** para os pontos de calibração (`freq_hz,ganho[,fase_graus]`),
  convertida para o JSON do perfil por um script pequeno — mais prático do que editar JSON
  à mão na hora de colar pontos medidos.
- **Metadados extras no perfil**, úteis para o relatório final: tipo de saída (mV/A vs.
  razão de transformação + resistor de carga), corrente nominal/de pico, incerteza
  estimada.
- **Campo de fase já reservado no formato** (`fase_graus`, opcional) mesmo sem uso
  imediato — evita migrar o formato de novo se um dia for preciso fator de potência ou
  defasagem tensão×corrente (sondas tipo bobina de Rogowski costumam ter defasagem não
  desprezível em baixa frequência).
- **CRC do perfil no cabeçalho** (`sonda_perfil_crc32_por_canal`) para detectar, na
  análise, se o perfil usado na captura foi editado/recalibrado depois — mesma filosofia
  de rastreabilidade do `firmware_git_hash` já sugerido em `docs/melhorias-propostas.md`.

## 9. Questões em aberto

- Tamanho fixo de `sonda_id_por_canal` (proposto: 16 bytes por canal) — suficiente para os
  ids esperados, ou vale mais espaço?
- Gravar a curva de calibração inteira (não só o id) dentro do próprio cabeçalho do
  `.bin`, para o arquivo ficar autossuficiente mesmo sem o JSON do perfil por perto? Isso
  custaria mais bytes de cabeçalho e exigiria um formato de tamanho variável (o cabeçalho
  hoje é fixo em 1024 bytes) — provavelmente mais simples deixar isso só na exportação
  HDF5 (seção 6.3), que já suporta atributos de tamanho arbitrário.
- `--sonda` deveria aceitar também canais de tensão/temperatura (ex.: um divisor resistivo
  com resposta em frequência não perfeitamente plana em alguma faixa), ou fica restrito a
  corrente por enquanto?
- Vale validar em `ler_adc.c`, no momento da captura, que o `sonda_id` informado
  corresponde a um arquivo de perfil existente — o que exigiria sincronizar os arquivos de
  perfil com a BeagleBone — ou manter essa validação só do lado Python, como proposto na
  seção 5?

---

*Documento de proposta — ver `docs/contexto_projeto.md` para o estado atual do projeto e
`docs/melhorias-propostas.md` para outras sugestões de melhoria já registradas.*
