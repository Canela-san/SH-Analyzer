# Auditoria do fluxo de perfil de sonda

**Escopo:** `calibrar_sonda.sh` → `gerar_perfil_sonda.py` → `scripts/sondas/<id>.json` → `adc_tool.py` (cabeçalho v2 gravado por `ler_adc.c`).
**Método:** leitura do código + experimentos com capturas **sintéticas** de uma sonda de resposta conhecida (passa-baixa de 1ª ordem, fc = 30 kHz; shunt 0,1 Ω; ruído de 0,5 mV no ADC). Nada foi testado em hardware real — as conclusões abaixo valem para o *software*; a exatidão física depende da bancada (seção 3).
**Reprodução:** `uv run --extra dev pytest tests/e2e` (12 testes, ~30 s; a suíte nasceu como `scripts/test_perfil_sonda.py` e foi migrada para pytest quando o código Python virou o pacote `scripts/supraharmonicos/` — ver `docs/arquitetura_software.md`). Os nomes de função citados abaixo (`ler_cabecalho`, `aplicar_correcao_sonda`, `carregar_perfil_sonda`...) continuam os mesmos; só mudaram de arquivo, do antigo `adc_tool.py` para os módulos do pacote.

---

## 1. Respostas diretas

**O jeito de definir o perfil é confiável?** Sim como *método* — com ressalvas de bancada.
Com 19 pontos, o `gerar_perfil_sonda.py` recuperou o ganho verdadeiro com erro ≤ 0,02 % nos pontos medidos (0,012 % nos testes finais) e ≤ 0,17 % entre pontos (interpolação). O estimador de amplitude (Welch + janela flat-top + refino parabólico) é tão bom quanto um ajuste senoidal por mínimos quadrados — comparados lado a lado, de 100 Hz a 80 kHz, ambos ficam em desvio ≤ 0,008 % e viés ≤ 0,003 % (o ajuste senoidal é ~10× mais lento). **Isso vale para o modo `--resistencia-shunt` (razão entre dois canais, em que o erro do estimador se cancela); nos modos de 1 canal (`--referencia-externa`, `--amplitude-referencia`) o erro de amplitude não se cancela e foi corrigido depois — ver o [adendo](#adendo-2026-10-estimador-de-amplitude-nos-modos-de-1-canal).** O que limita a confiança no perfil real é a bancada (shunt, canal de referência, gerador, dependência de amplitude/CC), não o software.

**O jeito de aplicar a correção é confiável?** Para **espectro de amplitude** (Welch, `--fft`, `--picos`), sim: tons de 2,5/9/20/40 kHz (0,2/0,1/0,1/0,1 A) voltaram a 0,2000/0,1000/0,1001/0,1000 A; sem correção o de 40 kHz saía 0,060 A (−40 %). Para **forma de onda no tempo** e **qualquer grandeza que dependa de fase entre canais**, não: a correção é só de magnitude (seção 4.1).

**Bugs?** Sete achados reais, todos corrigidos e cobertos por teste (seção 2). Nenhum corrompia o perfil *silenciosamente em condições normais*; o mais perigoso era o erro de escala silencioso quando o `--ganho` de produção diferia do usado na calibração (um `--ganho` esquecido dava erro de 10×, sem nenhum aviso).

---

## 2. Bugs encontrados e corrigidos

> A coluna "Onde" mostra os arquivos **da época da auditoria**. Depois, o código passou para o
> pacote `scripts/supraharmonicos/`. Onde cada correção mora hoje: bugs 1, 3 e 5 em `sonda.py`
> (`conferir_calibracao_perfil`, `resolver_perfil_canal`, `aplicar_correcao_sonda`); bug 2 em
> `modos.py` (`aplicar_correcao_sondas`); bug 4 em `sonda.py` (`carregar_perfil_sonda`) e
> `escrita_perfil.py`; bug 6 em `escrita_perfil.py` (`gravar_perfil_validado`); bug 7 em
> `calibracao_sonda.py`.

| # | Onde | Problema (evidência) | Correção |
|---|---|---|---|
| 1 | `adc_tool.py` | **`--ganho`/`--faixa`/`--formato` diferentes dos da calibração não geravam aviso.** Perfil gerado com `--ganho 1,10`, usado com `--ganho 1,1`: tons saíam 10× baixos (0,0100 em vez de 0,1); `--faixa 5.12` em vez de 10.24: 2× baixos. O perfil já gravava `calibracao_adc`, mas ninguém lia. | `conferir_calibracao_perfil()` compara com a calibração do canal e avisa o fator de erro. Só avisa (não aborta): perfis escritos à mão não têm o bloco. |
| 2 | `adc_tool.py` | **Sonda registrada em canal de *tensão* era ignorada em silêncio.** A decisão do projeto foi "`--sonda` vale para qualquer grandeza", mas a correção só rodava se `grandeza == corrente`. Canal 1 = tensão + `sonda_teste`: 40 kHz saía 0,060 A, sem mensagem. | Sonda registrada (id no cabeçalho ou `--sonda-perfil`) é aplicada a corrente **e** tensão. Temperatura: aviso explícito de que não se aplica. *Mudança de comportamento* — se a intenção era só registrar o id em canais de tensão, reverta o `if` em `main()`. |
| 3 | `adc_tool.py` | **Id de sonda do `.bin` escapava de `--sondas-dir`.** `sonda_id='../outside/evil'` carregou `sondas/../outside/evil.json`; `'/tmp/x'` (caminho absoluto) substitui o diretório inteiro (`Path / "/abs"`). O id vem de 32 bytes que o firmware grava sem validar caracteres. Baixo risco (precisa de `.bin` de terceiros), correção trivial. | Id só aceito se casar `^[A-Za-z0-9][A-Za-z0-9_.-]*$` e sem `..`. Erro orienta a usar `--sonda-perfil`. `--sonda-perfil` (entrada do operador) continua livre. |
| 4 | `adc_tool.py` / `gerar_perfil_sonda.py` | **NaN/Infinity no perfil** passavam pelas validações (`nan <= 0` é falso) e estouravam dentro do SciPy com *traceback* de `ValueError`; o round-trip do gerador só capturava `SystemExit`. (Hipótese inicial de "tudo NaN em silêncio" foi **descartada**: falhava alto, só com mensagem ruim.) | `isfinite` em `freq_hz`/`ganho`/`faixa_freq_valida_hz`; `faixa_freq_valida_hz` malformada e JSON que não é objeto também dão erro limpo. |
| 5 | `adc_tool.py` | **Aviso "fora da faixa calibrada" contava o bin de DC** e disparava em toda execução, mesmo com a banda de interesse coberta (ensina a ignorar o aviso). Além disso, `faixa_freq_valida_hz` era lida e nunca usada. | DC excluído; usa `faixa_freq_valida_hz` quando existe; separa "abaixo"/"acima"; avisa que acima do último ponto a amplitude corrigida fica **abaixo** do real (clamp: −10 % a 90 kHz e −18 % a 100 kHz se a sonda continua caindo); dica de calibrar ~50 Hz quando a fundamental da rede está abaixo do 1º ponto. |
| 6 | `gerar_perfil_sonda.py` | **Perfil bom destruído por uma geração ruim.** O `.json` final era escrito *antes* da validação e sem cópia: recalibrar com `--ganho` errado sobrescrevia o perfil anterior. | Escreve em `.tmp`, valida o round-trip, só então substitui; guarda o anterior em `<id>.json.bak` e avisa. Falha de validação preserva o perfil existente. |
| 7 | `gerar_perfil_sonda.py` | **Capturas saturadas não eram detectadas** (senoide ceifada → amplitude subestimada → ponto-lixo no perfil). **Captura com >2 canais e `--canal-*` forçado** desintercalava como 2 canais (erro enganoso "sonda desconectada"). Referência = sonda não era rejeitada. | Descarta captura com >0,05 % das amostras no fundo de escala (aviso com a causa). Usa a lista de canais do cabeçalho para desintercalar e para `fs_efetiva`. Rejeita ref == sonda. |

Melhorias de menor porte aplicadas junto:
- `aplicar_correcao_sonda` usa FFT de tamanho "rápido" (`next_fast_len`): para N com fator primo grande (ex.: recorte arbitrário por `--inicio`/`--fim`) ficou 8,5× mais rápido (1,74 s → 0,20 s com N = 2 000 003); resultado equivalente (diferença relativa ≤ 7·10⁻⁶ nos tons). Sem mudança de velocidade para N já "rápido" (ex.: 2¹⁹ amostras/canal de uma captura de 2 canais).
- Aviso quando a correção amplifica o ruído do ADC em mais de 20 dB (o piso de ruído em Amperes sobe por 1/H(f); é físico, mas muda como ler o espectro).
- Aviso quando o `id` dentro do `.json` difere do id do cabeçalho (arquivo copiado/renomeado).
- Pontos do perfil agora gravam `n` e `desvio_pct` (rastreabilidade; o loader ignora).
- Aviso espúrio de "fora da faixa" no gráfico de diagnóstico (`--plot`) removido.

Desempenho (instrução do projeto): a correção **não** é gargalo no PC — 20 M amostras/canal em 1,5 s, ~32 bytes/amostra de RAM extra (640 MB). Não toca a captura.

---

## 3. Limites de confiabilidade que NÃO são bugs (dependem da bancada)

Estes determinam se o perfil é *fisicamente* correto; o software não consegue detectá-los.

1. **O shunt é a verdade.** Corrente real = V_shunt / R, com R constante. Indutância parasita (ESL) infla |Z|: erro de magnitude = √(1+(ωL/R)²) − 1, para R = 0,1 Ω:

   | ESL | 10 kHz | 50 kHz | 100 kHz |
   |---|---|---|---|
   | 5 nH | 0,000 % | 0,012 % | 0,049 % |
   | 20 nH | 0,008 % | 0,197 % | 0,786 % |
   | 50 nH | 0,049 % | 1,226 % | 4,819 % |

   Desprezível para shunt de poucos nH até 100 kHz; relevante com shunt de fio/bobinado (dezenas de nH). Prefira shunt coaxial/SMD de baixa indutância, e a tolerância de R entra direto como erro de escala do perfil inteiro.
2. **O canal de referência é assumido plano.** O ganho medido é H_sonda / H_cadeia_referência. Se o canal 0 passa por divisor/isolador/filtro com resposta própria, ela vai para dentro do perfil. Teste simples: ligar o **mesmo** sinal nos dois canais e verificar razão = 1 em toda a banda (também mede o atraso de multiplexação).
3. **Gerador:** a deriva de amplitude é absorvida só no modo `--resistencia-shunt` e no do osciloscópio (que mede o que o gerador de fato entregou); com a amplitude conhecida (`--amplitude`, `--amplitude-referencia`) ela entra no perfil: o "500 mVpp" do painel vale para carga de 50 Ω (o dobro em alta impedância) e a planura do gerador em frequência alta vira erro do perfil (confirmado: `--amplitude-referencia` mostrou ~6 % de dispersão entre repetições nos testes sintéticos). Por isso vale conferir alguns pontos com o osciloscópio (`medir_captura.py --amplitude-referencia ... --osciloscopio ...`). Distorção do gerador não afeta o ganho da fundamental, mas confira a pureza.
4. **Linearidade/ponto de operação:** o perfil assume sistema linear e invariante. Sondas Hall/núcleo mudam de resposta com amplitude e com CC/fundamental de 50 Hz magnetizando o núcleo; calibrar a 1 A sem CC e medir 100 mA de supraharmônico sobre 10 A de fundamental pode divergir. Se a sonda é crítica, repita a calibração com a fundamental presente.
5. **Densidade de pontos** (PCHIP, erro máximo entre pontos, 100 Hz–80 kHz log-espaçados):

   | pontos | curva suave (1 polo) | com ressonância estreita (+15 %, σ ≈ 10 % em frequência) |
   |---|---|---|
   | 7 | 1,9 % | 11,5 % |
   | 12 | 0,6 % | 12,8 % |
   | 18 | 0,17 % | 11,5 % |
   | 25 | 0,06 % | 6,0 % |
   | 40 | 0,013 % | 3,6 % |

   15–25 pontos bastam para curva suave. **Ressonâncias estreitas só são vistas se um ponto cair nelas** — o erro quase não cai com mais pontos igualmente espaçados. Use o modo "Expandir" onde o gráfico (`--plot`) mostrar joelho ou onde o datasheet indicar ressonância.
6. **Envelhecimento/temperatura:** `data_calibracao` existe mas nada avisa perfil velho.
7. **Sem validação em hardware**, como já registrado em `docs/contexto_projeto.md`.

---

## 4. Limitações de projeto e melhorias propostas (decisão sua)

> **Status em 2026-10:** nenhuma das propostas abaixo foi implementada. Elas estão resumidas,
> com esforço e necessidade de decisão, em `docs/melhorias-propostas.md` (item 2.11).

### 4.1 Correção só de magnitude (fase não corrigida) — impacto alto *se* houver análise V×I
Medido: sonda passa-baixa causal de fc = 30 kHz, tons 2,5/9/20/40 kHz com amplitude restaurada exata, mas fase residual −4,8°/−16,7°/−33,7°/−53,1° e **erro RMS da forma de onda de 42 %** (o pico coincidiu por acaso). Hoje o pipeline só usa amplitude em dB, então é inofensivo; deixa de ser quando se calcular potência ativa, impedância ou direção de emissão em supraharmônicos.
Soma-se um efeito do hardware: canais multiplexados (AUTO_RST) são amostrados em instantes diferentes — atraso de 1/f_total entre canais consecutivos (a 400 kS/s: 2,5 µs = 36° a 40 kHz; a ~100 kS/s totais: 10 µs = 36° já a 10 kHz).
**Proposta:** calibrar o ganho **complexo** (o formato já reserva `fase_graus`). Como referência (canal 0) e sonda (canal 1) ocupam os mesmos slots de multiplexação na calibração e na produção, o atraso de amostragem entra na calibração e **se cancela** ao aplicar `1/H(f)` complexo — desde que V continue no canal 0 e I no canal 1. Exige o ajuste senoidal (que dá fase) e perfil com fase; correção passa de "dividir por |H|" para "dividir por H complexo" (fase mínima ≠ fase zero → atenção a causalidade/bordas). Não implementado: muda o formato e o significado do sinal corrigido.

### 4.2 Perfil absoluto em vez de relativo ao `--ganho`
Hoje `ganho(f) = S(f)/S_nominal` obriga a repetir o mesmo `--ganho`. O aviso do bug 1 mitiga, mas o desenho que elimina a classe de erro é gravar a sensibilidade **absoluta** S(f) [V/A no pino do ADC] e dividir por ela, ignorando `--ganho` para esse canal. Muda o formato (campo novo, perfis antigos continuam valendo) e a semântica de `--ganho`.

### 4.3 Validação cruzada por frequências retidas (hold-out)
Medir 2–3 frequências **fora** da malha do perfil e comparar com a curva interpolada: é a única verificação que detecta ressonância perdida e erro de interpolação em dados reais. Proposta: `calibrar_sonda.sh` marca pontos como `validacao` e `gerar_perfil_sonda.py` os exclui do perfil e imprime o erro. Não implementado.

### 4.4 Teto de ganho da correção
Onde 1/H é muito grande o ruído domina e a "correção" produz números enganosos. Hoje só avisa (> 20 dB). Opção: limitar 1/H a um máximo (inversa regularizada, ex. Tikhonov) — decisão de projeto (altera o resultado).

### 4.5 Correção nas exportações
`--export-hdf5`/`--converter` gravam calibração escalar pura, sem a sonda (documentado). Quem analisar o `.h5` fora do `adc_tool.py` pode supor que está corrigido. Opções: atributo HDF5 explícito `correcao_sonda_aplicada = false` (barato) ou correção em blocos sobreposto-e-soma (FIR/`scipy.signal.oaconvolve`) — esta muda para fase linear/FIR e é bem mais trabalho.

### 4.6 Bordas da correção por FFT global
A divisão espectral do registro inteiro trata o sinal como periódico; em registros não-periódicos pode haver artefato nas bordas da forma de onda (não quantificado nesta auditoria). Para espectros de Welch a influência esperada é pequena (a correção é linear e a janela de Welch pondera o trecho central), mas isso também não foi medido isoladamente. Sem correção específica.

### 4.7 Menores
- `gerar_perfil_sonda.py` não verifica estabilidade da amplitude *dentro* da captura (deriva do gerador durante os 2–3 s); comparar a 1ª e 2ª metade e avisar > 1–2 %.
- `calibrar_sonda.sh` não foi alterado por esta auditoria; sem achados na revisão e nos testes anteriores (`bash -n` ok; `shellcheck` não disponível neste ambiente nesta sessão — rodar localmente). **Achado posterior (2026-10), já corrigido:** a checagem de Nyquist usava a taxa total em vez da efetiva por canal (`taxa/4` com 2 canais); o script foi reescrito (escolha automática de frequências, conferência de cada captura, novos modos) — ver `docs/melhorias-propostas.md`, item 2.10, e `docs/guia_de_uso.md`, "Passo 1". O texto desta auditoria descreve o script **como ele estava** na época.
- `ler_adc.c` não foi alterado. Por decisão do projeto não valida o id da sonda; a validação de caracteres ficou no Python. Se quiser defesa em profundidade, validar também no `--sonda` do C (exige recompilar e retestar no BeagleBone).

---

## 5. Arquivos alterados

> Caminhos da época da auditoria; hoje a lógica Python está no pacote `scripts/supraharmonicos/` e a suíte em `tests/e2e/`.

| Arquivo | Mudança |
|---|---|
| `scripts/adc_tool.py` | bugs 1–5; `next_fast_len`; avisos de ruído e id; textos de ajuda |
| `scripts/gerar_perfil_sonda.py` | bugs 6–7; `n`/`desvio_pct` nos pontos |
| `scripts/test_perfil_sonda.py` (hoje `tests/e2e/test_perfil_sonda_e2e.py`) | **novo** — suíte sintética de regressão (11 testes; 12 após a migração para pytest) |
| `docs/auditoria_perfil_sonda.md` | **novo** — este documento |
| `docs/contexto_projeto.md` | seções atualizadas (modelo de calibração, pipeline, geração de perfil, status, restrições) |

Sem alteração (na época desta auditoria): `firmware/ler_adc.c`, `firmware/calibrar_sonda.sh`, `docs/exemplo_sonda.json`. O `calibrar_sonda.sh` foi reescrito depois (item 2.10 de `docs/melhorias-propostas.md`).

---

## Adendo (2026-10): estimador de amplitude nos modos de 1 canal

A conclusão da seção 1 ("não há ganho de exatidão em trocar o estimador") foi tirada no modo `--resistencia-shunt`, em que o ganho é a **razão** entre a amplitude da sonda e a da referência, medidas pelo mesmo estimador na mesma frequência: o erro de posição do tom no bin é igual nos dois e se cancela. Ao simular os modos de 1 canal (um canal só, corrente real lida no osciloscópio), em que a amplitude é **absoluta**, o erro aparece: 24 pontos de 50 Hz a 160 kHz, 3 s a 400 kS/s, resultado do Welch de 100 Hz com janela flat-top e refino parabólico:

| | Erro de amplitude (máx.) | Erro de frequência (máx.) |
|---|---|---|
| Welch + flat-top + parabólica (antes) | **1,83 %** (nos tons fora do centro do bin; 0 nos que caem no centro) | 14 Hz |
| Refinamento por FFT única (janela Kaiser β = 14, energia do lóbulo; agora) | 0,001 % | < 0,01 Hz |

O `medir_tom` continua usando o Welch para **localizar** o tom (e para a checagem de SNR), mas a amplitude e a frequência vêm de `_refinar_tom_por_fft` (o mesmo estimador do `medir_captura.py`), sobre até 4 M amostras. Se a captura for curta ou o tom estiver a menos de ~14 bins do DC, ou se o pico da FFT não coincidir com o do Welch, vale a estimativa do Welch. Cobertura: `tests/test_calibracao_sonda.py::TestMedirTom` (tons em 1,2, 9,7, 13,7, 55,8 e 112,6 kHz: erro < 0,05 % e < 0,5 Hz).
