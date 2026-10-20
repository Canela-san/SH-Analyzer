# SH-Analyzer — arquitetura do software de pós-processamento

Guia para quem vai **modificar** o código Python do projeto. Cobre: onde cada coisa mora, as regras que mantêm a estrutura saudável, como rodar e escrever testes, e receitas para as mudanças mais comuns. O firmware (C/Assembly da BeagleBone) está fora do escopo — ver `docs/contexto_projeto.md`.

> Regra de ouro do projeto (instrução do repositório): o código deve ser otimizado para desempenho, para suportar altas taxas de amostragem sem sobrecarregar o hardware nem corromper os dados medidos. Veja a seção [Desempenho](#6-desempenho-regras-para-quem-mexe-no-caminho-quente).

---

## 1. Visão geral em 30 segundos

```
firmware/ler_adc  ──grava──▶  captura.bin  (cabeçalho "SHAN" de 1024 B + amostras uint16 intercaladas)
                                   │
firmware/calibrar_sonda.sh ──▶ capturas/<sonda>/calibracao_*.bin
                                   │
scripts/gerar_perfil_sonda.py ──▶ scripts/sondas/<id>.json   (perfil de resposta em frequência da sonda)
                                   │
scripts/adc_tool.py captura.bin  ──▶ gráfico / espectro (FFT, Welch, picos, bandas) / .csv / .h5
scripts/medir_captura.py captura.bin ──▶ números para o relatório (ruído, THD, SINAD, ENOB, SFDR, continuidade, diafonia) / .csv
scripts/compactar_amostras.py pasta/ ──▶ pasta_<data>.zpaq.tar  (arquivamento sem perdas, conferido pelo SHA-256)
```

Todo o código Python vive no **pacote `scripts/supraharmonicos/`**. Os quatro arquivos `scripts/adc_tool.py`, `scripts/gerar_perfil_sonda.py`, `scripts/medir_captura.py` e `scripts/compactar_amostras.py` são **entradas finas** (menos de 40 linhas): só chamam `main()` do pacote. Eles mantêm o bloco PEP 723 (`# /// script`), então `uv run scripts/adc_tool.py ...` continua funcionando sem instalar nada.

Três ideias organizam tudo:

1. **Camadas sem ciclos.** Cada módulo só importa módulos de camada inferior (tabela na seção 3; imposto por `tests/test_arquitetura.py`).
2. **Biblioteca não fala com o usuário nem encerra o programa.** Erros viram exceções (`ErroSHAN`); mensagens viram `logging`. Só a "borda" (`cli_*.py`) imprime e escolhe o código de saída.
3. **Dados grandes nunca são materializados à toa.** `.bin` é lido por `numpy.memmap`; conversão e exportação trabalham em blocos.

---

## 2. Mapa do repositório

```
firmware/                 C/Assembly (ARM + PRU) — fora deste guia — e calibrar_sonda.sh
                          (coleta interativa de calibração de sonda, bash puro)
scripts/
  adc_tool.py             entrada fina: CLI de análise/conversão/exportação
  gerar_perfil_sonda.py   entrada fina: CLI do gerador de perfis de sonda
  medir_captura.py        entrada fina: CLI das métricas de captura (para o relatório)
  compactar_amostras.py   entrada fina: arquivar/restaurar capturas sem perdas (pacote .zpaq.tar)
  sondas/*.json           perfis de sonda gerados (dados, não código); a pasta nasce no 1º perfil
  supraharmonicos/        ← TODA a lógica Python (seção 3)
tests/                    pytest (seção 7)
relatorio/gerar_figuras.py  figuras do relatório/artigo (estilo único, PDF vetorial + macros siunitx);
                          importa o pacote, mas não faz parte dele (receita na seção 8)
relatorio/figuras/        saída do script acima
docs/                     contexto_projeto.md, auditoria_perfil_sonda.md, este arquivo...
.github/workflows/ci.yml  testes automáticos no GitHub (seção 7.1)
pyproject.toml            dependências, configuração de pytest e ruff
```

**Por que `supraharmonicos`?** O nome do pacote é o que se escreve em `import`, então precisa ser um identificador Python (sem hífen) e não deve repetir o nome do repositório (`SH-Analyzer/`), para não haver duas coisas com o mesmo nome em níveis diferentes. Ele é o assunto do projeto, não o nome dele. Se um dia for trocado, o rename é mecânico: renomear a pasta, trocar o nome em `pyproject.toml` (`include`), nos testes e no `NOME_RAIZ` de `registro.py`. Um `grep -rn nome_antigo .` (fora de `firmware/`) acha o resto; os testes acusam qualquer import esquecido, mas `include` do `pyproject.toml` só aparece ao instalar o pacote.

---

## 3. Módulos de `scripts/supraharmonicos/`

Camada = quem pode importar quem (um módulo só importa camadas **menores**).

| Camada | Módulo | Responsabilidade | Símbolos principais |
|:--:|---|---|---|
| 0 | `erros` | Hierarquia de exceções | `ErroSHAN`, `ErroUso` |
| 0 | `constantes` | Constantes compartilhadas (inclusive as que espelham o firmware) | `FORMATOS_NUMPY`, `GRANDEZA_*`, `ADS8688_MAX_CANAIS`, defaults de Welch/filtro |
| 0 | `registro` | Liga o `logging` ao console no formato histórico (stdout/stderr) | `configurar_logging_cli` |
| 1 | `cabecalho` | Lê/valida o cabeçalho "SHAN" v1/v2/v3 (magic, CRC-32, campos, faixa do ADC por canal, consistência) | `ler_cabecalho`, `CabecalhoArquivo`, `conferir_consistencia_cabecalho` |
| 1 | `amostras` | Lê `.bin` (memmap) e `.csv`; código → volts | `carregar_amostras_bin`, `converter_para_tensao`, `selecionar_intervalo` |
| 1 | `canais` | Listas de canais/calibração, desintercalação, offsets, `--faixa` por canal | `analisar_lista_canais`, `desintercalar`, `resolver_faixas`, `resolver_offsets_por_canal` |
| 1 | `filtros` | Butterworth SOS, fase zero | `aplicar_filtro_digital`, `validar_corte_filtro` |
| 1 | `fundamental` | Fundamental da rede, corte em ciclos inteiros, refino parabólico | `recortar_ciclos_inteiros`, `refinar_pico_parabolico` |
| 1 | `sonda` | Perfil de sonda (JSON), interpolação PCHIP, correção em frequência | `PerfilSonda`, `carregar_perfil_sonda`, `resolver_perfil_canal`, `aplicar_correcao_sonda` |
| 1 | `plotagem` | Gráficos (único módulo que importa `matplotlib` no topo) | `plotar_multicanal` |
| 1 | `referencia` | O que foi injetado numa calibração: amplitude com unidade e tipo (`500mVpp`), frequência e o marcador `ref: f=.. amp=..` dos metadados | `analisar_amplitude`, `pico_fisico`, `extrair_referencia`, `formatar_referencia` |
| 1 | `osciloscopio` | Forma de onda do osciloscópio (`.m`/`.mat`/`.csv`) e medida da senoide por mínimos quadrados | `ler_forma_de_onda`, `medir_senoide`, `localizar_arquivo_osciloscopio` |
| 2 | `espectro` | Janelas, FFT única, Welch, bandas, picos | `calcular_espectro`, `calcular_espectro_welch`, `agrupar_em_bandas`, `encontrar_picos_espectro` |
| 2 | `conversao` | `.bin` ↔ `.csv` em blocos | `converter_arquivo` |
| 2 | `hdf5` | `.bin` → `.h5` em blocos (`h5py` importado só ao usar) | `exportar_hdf5` |
| 2 | `metricas_captura` | Métricas de uma captura, sem I/O: estatística, ruído, tom, THD/SINAD/SNR/ENOB/SFDR, continuidade, diafonia/atraso (FFT única, janela Kaiser β = 14) | `analisar_espectro`, `verificar_continuidade`, `calcular_acoplamento`, `calcular_basicas` |
| 2 | `compactacao` | Pacote `.zpaq.tar` sem perdas: formato (tar + manifesto JSON + peças zpaq/xz independentes), desentrelaçamento reversível dos canais, compressores em paralelo (cabe na RAM livre), verificação por SHA-256, extração segura | `compactar`, `Pacote`, `descobrir_entradas`, `Desentrelacamento`, `remover_originais` |
| 2 | `contexto` | "O que esta captura é": cabeçalho + canais + calibração + grandeza/sonda por canal, resolvidos uma vez | `ContextoCaptura`, `resolver_contexto` |
| 3 | `modos` | Os 3 modos do `adc_tool` (plotagem, conversão, HDF5); a plotagem é um pipeline de etapas pequenas | `executar_plotagem`, `executar_conversao`, `executar_exportacao_hdf5` |
| 3 | `calibracao_sonda` | Medir tons de calibração (Welch localiza, FFT única mede), ganho vs o que foi injetado (amplitude conhecida, osciloscópio, shunt), agregar repetições, resumir a resposta do conjunto | `medir_tom`, `processar_captura`, `agregar_por_frequencia`, `resumir_resposta` |
| 4 | `escrita_perfil` | Monta o JSON do perfil, grava com segurança (`.tmp` → validação → `.bak` → troca), gráfico de diagnóstico | `montar_perfil_json`, `gravar_perfil_validado` |
| 4 | `cli_adc_tool` | **Borda**: flags do `adc_tool` e `main()` | `montar_parser`, `main` |
| 4 | `cli_compactar` | **Borda**: comandos `compactar`/`extrair`/`listar`/`verificar` e a interface (`rich`: tabelas, barras com estimativa de tempo, confirmações) | `montar_parser`, `main`, `Painel` |
| 4 | `cli_medir_captura` | **Borda**: flags do `medir_captura`, saída em texto e CSV (`COLUNAS_CSV`) | `montar_parser`, `main`, `medir_arquivo` |
| 5 | `cli_gerar_perfil` | **Borda**: flags do gerador e `main()` | `montar_parser`, `main`, `executar_geracao` |

### Pipeline do modo de plotagem (`modos.executar_plotagem`)

Cada etapa é uma função pequena e testável; **a ordem importa**:

```
_resolver_frequencia → _validar_parametros → _avisar_combinacoes_arriscadas
→ _carregar_sinal (memmap → volts por canal)
→ aplicar_correcao_sondas   ← ANTES de tudo que é espectral
→ _aplicar_filtros_usuario   (Butterworth opcional)
→ _resumir_dados → _analisar_fft / _analisar_welch → plotagem.plotar_multicanal
```

A correção de sonda vem antes do filtro e do espectro para que nenhuma dessas etapas precise saber que existe uma sonda. Ela corrige só a **magnitude** (não a fase): serve para espectro/picos, **não** para potência ou impedância entre canais (`docs/auditoria_perfil_sonda.md`, §4.1).

### Hierarquia de resolução de parâmetros

Para canais, calibração, grandeza e sonda vale sempre: **flag explícita na CLI > cabeçalho da captura (v2/v3) > padrão histórico** (tensão, sem sonda, `--faixa 10.24`). A faixa de entrada do ADC de cada canal vem do cabeçalho v3 (`canais.resolver_faixas`). Quem implementa isso é `contexto.resolver_contexto` (não espalhe esse `if` em outros lugares).

---

## 4. Convenções (leia antes do primeiro PR)

### 4.1 Erros: `ErroSHAN`, nunca `SystemExit`

```python
from .erros import ErroSHAN, ErroUso

raise ErroSHAN(f"arquivo '{caminho}' não encontrado.")        # SEM o prefixo "Erro: "
raise ErroUso("-o/--saida é obrigatório junto com -c/--converter.")  # combinação inválida de flags
```

* A mensagem é o texto final em português, com contexto (caminho, nome da flag, valor recebido). **Sem** `"Erro: "` na frente — a CLI coloca.
* `ErroSHAN` → a CLI imprime `Erro: <mensagem>` no stderr e sai com **código 1**.
* `ErroUso` (subclasse) → a CLI chama `parser.error(...)`: mostra o *usage* e sai com **código 2**.
* Bug de verdade (exceção inesperada) **não** é capturado: aparece com traceback. Só capture o que você sabe explicar ao usuário.
* Para reaproveitar uma exceção como aviso: `log.warning(f"pulando '{nome}' -- {e}")` (por isso a mensagem não tem prefixo).

### 4.2 Saída: `logging`, nunca `print`

```python
import logging
log = logging.getLogger(__name__)

log.info("Arquivo: ...")           # progresso/resultado → stdout, sem prefixo
log.warning("--welch sem filtro")  # aviso → stderr, o handler põe "Aviso: " na frente
```

* Não escreva `"Aviso: "` na mensagem.
* Só `cli_*.main` chama `registro.configurar_logging_cli()`. Usado como biblioteca (notebook, teste), o pacote fica **silencioso** até você configurar o `logging` como quiser.
* Testes capturam avisos com `caplog` (ver `tests/test_sonda.py`).

### 4.3 Dependências pesadas

* `matplotlib`: só em `plotagem.py` (topo) e dentro de `escrita_perfil.gerar_grafico` (para `--plot`). `modos` importa `plotagem` **dentro** de `executar_plotagem` — quem só converte `.bin`→`.csv` não paga o custo do matplotlib.
* `h5py`: só dentro de `hdf5.exportar_hdf5`.
* `rich` (interface do `compactar_amostras`): só em `cli_compactar`. O formato e a verificação (`compactacao`) não dependem dele.
* Dependências novas: declare em **dois** lugares — `pyproject.toml` e o bloco PEP 723 de cada script que a usa (`tests/test_dependencias.py` falha se faltar no bloco algo que o script importa ao carregar, ou se as versões divergirem).

### 4.4 Constantes que o firmware também tem

`ADS8688_MAX_CANAIS`, `GRANDEZA_*`, tamanho/versão/layout do cabeçalho existem em C **e** em Python, sem arquivo compartilhado. `tests/test_contrato_firmware.py` lê `firmware/ler_adc.c` (e `memoria_pru.h`, se presente) e confere valores e o **layout campo a campo** da `struct cabecalho_arquivo_campos` contra `cabecalho._FORMATO_CABECALHO_V2`. Mudou o cabeçalho de um lado → o teste falha até o outro acompanhar.

### 4.5 Estilo

* Nomes, comentários e mensagens em **português**; comentários explicam o *porquê* (física, formato, armadilha), não o *quê*.
* `ruff check .` limpo (regras `E W F I UP B T20`; `T20` proíbe `print`).
* Não há formatador automático imposto; mantenha o estilo do arquivo que você está editando.

---

## 5. Ambiente

| Quero… | Comando |
|---|---|
| Rodar uma ferramenta sem instalar nada | `uv run scripts/adc_tool.py captura.bin --welch ...` (usa o bloco PEP 723), ou direto `./scripts/adc_tool.py ...` (o shebang `#!/usr/bin/env -S uv run --script` chama o uv) |
| Ambiente de desenvolvimento | `uv sync --extra dev` **ou** `pip install -e ".[dev]"` |
| Usar o pacote em um notebook | `pip install -e .` e `from supraharmonicos.espectro import calcular_espectro_welch` |
| Backend gráfico interativo (`plt.show()`) | extra `gui` (`PyQt6`); para salvar PNG (`-o`) não precisa |

O `.gitignore` do repositório já ignora `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/` e `uv.lock`. O `uv.lock` é ignorado de propósito: o projeto fixa só limites mínimos de versão (`pyproject.toml`), e a CI testa sempre contra as versões mais recentes que o `uv` resolver.

Atenção: a pasta padrão de perfis (`sondas.SONDAS_DIR_PADRAO`) é `scripts/sondas/`, **ao lado** do pacote — vale para o repositório e para instalação editável (`-e`). Fora disso, use `--sondas-dir`.

---

## 6. Desempenho: regras para quem mexe no caminho quente

O caminho quente é tudo que toca **todas** as amostras de uma captura (dezenas de milhões em capturas longas a centenas de kS/s).

1. **Nada de laço Python por amostra.** Use operações vetorizadas do numpy/scipy.
2. **Não materialize a captura inteira.** `.bin` entra por `numpy.memmap` (`amostras.carregar_amostras_bin`); conversão e HDF5 processam em blocos de `--tamanho-chunk` amostras (memória ~constante).
3. **Prefira *views* a cópias.** `desintercalar` usa `reshape(-1, n_canais)` (view; funciona em memmap).
4. **FFT em tamanho "rápido".** `scipy.fft.next_fast_len` (a correção de sonda usa isso: com N primo grande a FFT cai no algoritmo de Bluestein, ~8× mais lenta).
5. **Welch em lotes** (`TAMANHO_LOTE_WELCH_PADRAO` segmentos por vez via `sliding_window_view`): equilíbrio entre FFT vetorizada e memória.
6. **Importações caras sob demanda** (matplotlib, h5py) — veja 4.3.
7. **Meça antes de "otimizar".** Antes/depois com uma captura grande (ex.: 20 s × 2 canais a 400 kS/s = 16 MB) e `time`/`resource.getrusage`. A refatoração que criou este pacote foi medida assim: tempo de plotagem equivalente (mesma mediana dentro do ruído), e conversão/HDF5/`--help` **mais rápidos** (≈20–27 %) e com ≈ 33 MB a menos de RAM, só por não importar matplotlib quando não é preciso.

---

## 7. Testes

```bash
uv run --extra dev pytest                 # tudo: 682 testes (~1 min 40 s)
uv run --extra dev pytest -m "not e2e"    # rápido: 564 testes (~30 s) — use no dia a dia
uv run --extra dev pytest -m e2e          # só ponta a ponta: 118 testes (a maior parte do tempo)
uv run --extra dev pytest -n0 tests/test_dsp.py::TestFiltros   # um teste só, sem paralelismo (pdb/breakpoint)
uv run --extra dev pytest --cov=scripts/supraharmonicos --cov-report=term-missing   # cobertura (~90 %)
uv run --extra dev ruff check .
```

A suíte roda **em paralelo** (`pytest-xdist`, `-n auto --dist worksteal` em `pyproject.toml`): um processo por núcleo; o tempo cai de ~6 min para ~1 min 40 s (i7 de 4 núcleos/8 threads). Por isso cada teste precisa ser independente: nada de estado em arquivo fora do `tmp_path`, nem de ordem entre testes. Para onde vai o tempo que sobra:

* **Coleta** (~6 s por processo): os módulos de teste importam o pacote, e `import scipy.signal` sozinho custa ~2 s (a SciPy recente puxa `scipy.stats` e a camada de "array API").
* **`test_calibrar_sonda.py`** (102 testes de ~1 s cada, em série): o script bash de verdade, um `ler_adc` falso por captura (~0,35 s de Python + numpy) e a conferência rápida de cada captura, em awk (~0,7 s no PC).
* **`e2e/test_perfil_sonda_e2e.py`**: só o perfil base e a correção principal passam pelas entradas reais via subprocess (cada um paga ~1–3 s de importações); os outros casos chamam `main()` no mesmo processo, com capturas e pastas de calibração menores onde a precisão do perfil não é o que se testa.

Quando acrescentar um teste: prefira `main([...])` no mesmo processo (fixture `cli`) a subprocess, e capturas curtas (`--fim`, `dur_s`) quando o que se confere é um aviso ou um erro. Ruído sintético sempre com semente (`np.random.default_rng(semente)`); o `ler_adc` falso usa o nome da pasta do teste e o número da rodada (`SIM_SEMENTE`).

| Arquivo | O que garante |
|---|---|
| `test_registro_e_erros.py` | formato stdout/stderr do logging; hierarquia de erros |
| `test_cabecalho.py` | cabeçalho v1/v2/v3, CRC, magic, faixa do ADC por canal, conferência de consistência |
| `test_canais_e_amostras.py` | listas de canais/calibração, desintercalação, código→volts, leitura de `.bin`/`.csv` |
| `test_sonda.py` | validação do JSON (NaN, ids inseguros, faixa), interpolação, avisos, correção restaura amplitude |
| `test_dsp.py` | filtros, fundamental, janelas, FFT/Welch, bandas, picos (com sinais de amplitude conhecida) |
| `test_conversao.py` | round-trip `.bin`↔`.csv`, exportação HDF5 (dados e metadados) |
| `test_calibracao_sonda.py` | `medir_tom` (amplitude exata com o tom em qualquer posição do bin), resolução de canais, agregação, resumo da resposta, CLI do gerador (os quatro modos de referência: `amplitude` por metadados/constante, `osciloscopio`, `externa`, `shunt`) |
| `test_referencia.py` | amplitude com unidades (pp/pico/rms, prefixos, entradas ambíguas recusadas), frequência, `ref:` dos metadados (ida e volta, texto livre ao redor) |
| `test_osciloscopio.py` | leitor de `.m`/`.mat`/`.csv` (variáveis, matriz tempo×valor, escalares de taxa, erros que listam o que foi achado) e ajuste de senoide por mínimos quadrados (amplitude, frequência, DC, poucos ciclos) |
| `test_metricas_captura.py` | `medir_captura`: tom, ruído, THD/SINAD/ENOB/SFDR contra sinais de verdade conhecida, continuidade (amostra removida/duplicada), diafonia/atraso, CLI, CSV, correção de sonda e comparação com instrumento |
| `test_cli_adc_tool.py` | CLI no mesmo processo: códigos de saída 0/1/2, stdout×stderr, arquivos gerados (CSV conferido linha a linha); `--fft` em ciclos inteiros (f0 e harmônicos com amplitude exata); gráfico de eixo único (1 canal e `sobrepostos`); `--grandeza`/`--sonda-perfil` (formato, canal fora da captura) |
| `test_contrato_firmware.py` | C ↔ Python: constantes, layout do cabeçalho (v4), códigos de faixa do ADC, offsets da memória compartilhada da PRU (inclusive os contadores e os atrasos de CS que o assembly lê/escreve em bloco) e os atrasos padrão iguais no C e no assembly |
| `test_faixa_adc.py` | `--faixa` por canal: cabeçalho v3 > padrão, aviso se divergir, amplitude certa em cada faixa, perfil de sonda e `faixa_v_confiavel` |
| `test_pru_asm.py` (+ `pru_sim.py`) | lógica do `firmware/spi_core.asm` num mini-simulador de PRU: palavras enviadas na configuração (`AUTO_SEQ_EN`, `RANGE_SELn`, `AUTO_RST`), ordem, ciclos de SCLK, laço gravando na DDR, IMEM e alcance dos desvios; a **grade de tempo** das amostras em ciclos (sem salto na troca de buffer nem no rebase do contador, que trava em 2³²; amostra atrasada volta à grade) e os contadores de integridade (atrasadas, buffers sobrescritos, preâmbulo); atrasos de CS configuráveis com o padrão igual ao validado (transação de 1.166 ciclos). Não substitui compilar com `clpru` nem testar no hardware |
| `test_arquitetura.py` | camadas sem ciclo, sem `print`/`SystemExit` em biblioteca, matplotlib/h5py confinados, entradas finas |
| `test_dependencias.py` | todo script com `if __name__ == "__main__"` (em `scripts/`, `relatorio/`, `tests/`, `firmware/`) roda com `uv run`: shebang do uv, permissão de execução, bloco PEP 723 com tudo o que ele importa ao carregar (seguindo o pacote e os módulos vizinhos) e versões iguais às do `pyproject.toml` |
| `test_calibrar_sonda.py` (+ `ler_adc_falso.py`) | `firmware/calibrar_sonda.sh` de ponta a ponta contra um `ler_adc` falso: plano de frequências, conferência de cada captura (saturação, nível, frequência, CRC, disco cheio), menu C/R/P/A, modos `retomar`/`refinar`/`adensar`/`refazer`/`resumo`, Ctrl+C, `--amplitude`/`--amplitude-por-ponto` (metadados `ref:` no `.bin`, manifesto, plano, menu interativo, perfil gerado sem flag), `--grandeza tensao` (cabeçalho, textos, coluna `tensao_rms_V`, 2 canais, plano antigo = corrente), e que as constantes do cabeçalho e a gramática de amplitude batem com o firmware e o Python. Marcado `e2e` (usa `bash`; é pulado fora do Linux) |
| `test_relatorio.py` | `relatorio/gerar_figuras.py`: o ajuste do passa-baixa recupera K, f0 e Q conhecidos (com e sem pesos medidos) e vence os outros modelos pelo BIC; f−3dB, polos e incerteza no formato do siunitx; a figura e as macros são geradas (sem LaTeX, para rodar no CI) |
| `test_compactacao.py` | `compactar_amostras`: desentrelaçar e voltar é exato com cortes em qualquer byte; a receita do `LEIA-ME.txt` (só numpy) reconstrói o original; ida e volta devolve bytes, datas e permissões; peça corrompida é detectada e o arquivo estragado não é gravado; falha ou Ctrl+C no meio não deixa pacote nem temporários nem `zpaq` órfão; caminho malicioso no manifesto é recusado; `--remover-originais` só apaga o que continua idêntico; CLI. Os testes com o `zpaq` de verdade são `e2e` (pulados sem ele) |
| `test_scripts_shell.py` | `scripts/set_date.sh` (com `ssh`/`sudo`/`date` falsos: o tempo da senha do sudo é descontado). Marcado `e2e` |
| `e2e/test_perfil_sonda_e2e.py` | fluxo completo (o perfil base e a correção principal por subprocess nas entradas reais; o resto com `main()` no mesmo processo): calibração → perfil → correção (inclui as 7 correções da auditoria) |

**Testando um script de shell.** `tests/ler_adc_falso.py` imita a linha de comando do `ler_adc` e grava um `.bin` v3 sintético (aceita `--faixa-adc`; `cab_v1`/`cab_v2` imitam firmware antigo); o arquivo `cenario` (uma diretiva por chamada: `ok`, `sat_sonda`, `falha`, `truncar`, `travar`, ...) faz cada captura falhar de um jeito específico. É assim que se testa o tratamento de erros do `calibrar_sonda.sh` sem a BeagleBone.

**Escrevendo um teste novo.** `tests/capturas_sinteticas.py` monta `.bin` v1/v2/v3 a partir de sinais em Volts (`escrever_bin`; `faixas_adc_total_v=(20.48, 5.12)` dá cabeçalho v3 e codifica cada canal na sua faixa), uma sonda de resposta conhecida (`planta_h`) e pastas de calibração (`criar_pasta_calibracao`). A fixture `cli` (em `conftest.py`) roda `main([...])` no mesmo processo e devolve `(código, stdout, stderr)`. Nenhum teste precisa de hardware.

**Mudança de comportamento intencional?** Teste que valida comportamento *antigo* deve ser atualizado no mesmo PR, com a razão no commit.

### 7.1 Integração contínua (GitHub Actions)

`.github/workflows/ci.yml` instala o `zpaq` (para os testes do `compactar_amostras`; sem ele, esses testes são pulados) e roda o `ruff check .` e o `pytest` (suíte completa, com e2e) a cada push na `main` e a cada pull request, em duas versões do Python: **3.10** (o mínimo declarado em `requires-python`) e **3.13**. É o mesmo que `uv run --extra dev ruff check .` e `uv run --extra dev pytest` fazem na sua máquina — se passa local, passa no CI. Leva cerca de 1 a 2 minutos.

Para o CI *impedir* um merge que quebra algo, o resultado precisa ser exigido nas configurações do repositório (**Settings → Rules → Rulesets** ou **Branches → Branch protection rule**, na branch `main`): marcar *Require a pull request before merging* e *Require status checks to pass before merging*, e escolher os checks `testes (Python 3.10)` e `testes (Python 3.13)` (eles só aparecem na lista depois da primeira execução do workflow).

Os testes não precisam de hardware nem de arquivos `.bin` do repositório (`*.bin` está no `.gitignore`): eles geram suas próprias capturas sintéticas.

---

## 8. Receitas

**Adicionar uma flag ao `adc_tool`.** (1) `cli_adc_tool.montar_parser`: declare a flag; (2) leia-a em `modos.py` (ou em `contexto.resolver_contexto` se for sobre "o que é a captura"); (3) valide cedo — antes de abrir a captura — levantando `ErroSHAN`/`ErroUso`; (4) teste em `test_cli_adc_tool.py`; (5) documente em `docs/contexto_projeto.md` (`<pipeline_dsp_python>`).

**Novo tipo de perfil de sonda** (ex.: `polinomio`/`tabela` para temperatura — hoje não implementado). Em `sonda.py`: acrescente o tipo em `TIPOS_PERFIL_SUPORTADOS`, valide os campos em `carregar_perfil_sonda`, trate-o em `PerfilSonda.ganho_em`, e decida em `modos.aplicar_correcao_sondas` a quais grandezas se aplica. Teste em `test_sonda.py`.

**Novo campo no cabeçalho do `.bin`.** Firmware (`ler_adc.c`: struct + `CABECALHO_VERSAO`) → `cabecalho._FORMATO_CABECALHO_Vn` e `_CONTAGENS_...` → `CabecalhoArquivo` → fixture (`montar_cabecalho` em `tests/capturas_sinteticas.py`) → rode `test_contrato_firmware.py`, que aponta qualquer divergência de layout. Leitores **nunca** assumem a versão mais nova: o formato antigo continua suportado.

**Novo script executável** (qualquer `.py` com `if __name__ == "__main__"`). Primeira linha `#!/usr/bin/env -S uv run --script`, logo abaixo o bloco PEP 723 (`# /// script` ... `# ///`) com as dependências e `chmod +x`; o `test_dependencias.py` acusa o que faltar. Assim `uv run arquivo.py` e `./arquivo.py` funcionam sem instalar nada. Se a lógica for de biblioteca, ela vai para o pacote e o script fica fino (como os de `scripts/`).

**Novo módulo.** Escolha a camada pela regra "só importo camadas menores"; registre-o em `CAMADAS` (`tests/test_arquitetura.py`) e na tabela da seção 3; escreva o `"""docstring"""` dizendo de quem depende.

**Nova figura do relatório.** Em `relatorio/gerar_figuras.py`, escreva uma função `nome(estilo) -> Resultado` com `@figura("nome", "descrição")`: crie a figura com `estilo.nova_figura(proporcao)`, use as cores de `COR` (o texto sempre em tinta, nunca na cor da série), os rótulos de `estilo.t(...)` (acrescente as chaves em `TEXTOS`, em `pt` e `en`) e formate números com `estilo.num`/`estilo.qty` (vírgula decimal em português). Os dados vêm do projeto (perfis, capturas, pacote), nunca copiados à mão; números que o texto vai citar voltam em `Resultado.macros` e viram `relatorio/figuras/nome.tex`. Teste a lógica (ajustes, contas) em `tests/test_relatorio.py`. O script fica fora do pacote de propósito: é código do relatório, não biblioteca, e por isso pode usar matplotlib à vontade (o logging vai pelo logger `supraharmonicos.relatorio`, que herda o formato do console).

**Nova etapa no pipeline de plotagem.** Uma função `_nome_da_etapa` em `modos.py`, chamada na ordem certa em `executar_plotagem`; se mexe no sinal, pense onde ela entra em relação à correção de sonda e ao filtro.

**Novo gráfico / backend.** Só em `plotagem.py` (ou `escrita_perfil.gerar_grafico`), com `matplotlib` importado ali.

---

## 9. Checklist de PR

- [ ] `ruff check .` limpo e `pytest` verde (pelo menos `-m "not e2e"`; e2e se mexeu em sonda/calibração/CLI)
- [ ] Sem `print`, sem `SystemExit`, sem importar camada superior
- [ ] Caminho quente: sem laço por amostra, sem cópia desnecessária, sem materializar a captura
- [ ] Teste novo para o comportamento novo/corrigido
- [ ] Mudou formato do cabeçalho ou constante espelhada no firmware? Lado C e `test_contrato_firmware.py` no mesmo PR
- [ ] Mudou flag ou comportamento visível? Atualize `docs/contexto_projeto.md`

---

## 10. Histórico: como esta estrutura nasceu

Antes, a lógica estava em dois arquivos: `adc_tool.py` (~2950 linhas, `main()` de ~400 linhas com funções aninhadas) e `gerar_perfil_sonda.py` (que importava o primeiro via `sys.path`). A refatoração foi feita em cinco passos, **preservando flags, saídas e códigos de saída**: (1) `main()` fatiado em modos e etapas; (2) `SystemExit` → `ErroSHAN`; (3) pacote em camadas + entradas finas; (4) `print` → `logging`; (5) `pyproject.toml`, testes unitários, contrato C↔Python e teste de arquitetura.

Verificação: 61 execuções da CLI (flags, modos, erros) comparadas antes/depois — stdout, stderr, código de saída e *hash* dos arquivos gerados. 57 idênticas byte a byte; 4 mudaram **de propósito**, só no texto de mensagens, para unificar a convenção `Aviso:`/`Erro:`:

| Caso | Antes | Depois |
|---|---|---|
| CRC do cabeçalho errado | `  ⚠️  CRC-32 do cabeçalho NÃO confere ...` (stderr, sem prefixo) | `Aviso: CRC-32 do cabeçalho NÃO confere ...` |
| `.bin` truncado | `Erro ao abrir '...'` | `Erro: falha ao abrir '...'` |
| Canal de corrente sem perfil | `  Canal 1: canal de corrente sem sonda/perfil resolvido ...` (stderr, sem prefixo) | `Aviso: canal 1 é de corrente mas não tem sonda/perfil resolvido ...` |
| Perfil gerado que não recarrega | `Erro: ... via adc_tool.py -- Erro: 'faixa_freq_valida_hz' ...` (prefixo duplicado) | `Erro: ... via adc_tool.py -- 'faixa_freq_valida_hz' ...` |

Efeitos colaterais benéficos: `--export-hdf5`/`-c` não importam mais `matplotlib`; `PerfilSonda.silenciar_aviso_fora_da_faixa()` substitui um acesso a atributo privado que o gráfico do gerador fazia.
