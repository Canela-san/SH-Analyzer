# SH-Analyzer — Contexto (documento de referência p/ LLM)

> Nome fixo: `docs/contexto_projeto.md`. Não versionar com sufixo. Densidade > fluência. Atualizar a cada mudança estrutural (protocolo, formato de dados, pipeline).

<sistema>
- SH-Analyzer = instrumentação para detecção/caracterização de supraharmônicos (perturbações de alta freq., dezenas de kHz, de conversores eletrônicos de potência) em tensão/corrente de rede elétrica. Escapam de analisadores QEE convencionais.
- Duas partes: (a) frontend analógico (PCB própria, isolamento galvânico) condiciona sinais; (b) BeagleBone faz aquisição híbrida PRU (RT) + ARM (Linux); (c) pós-processamento Python (scripts/adc_tool.py).
- IC (Iniciação Científica) — "Sistema de identificação da presença de supraharmônicos em redes e cargas elétricas", Eng. Controle e Automação, Unicamp. Orientação: Prof. Dr. José Antenor Pomilio. Coorientação: Dr. Mateus Pinheiro Dias. PCB/firmware: Gabriel Canela. Licença: MIT.
</sistema>

<arquitetura_fisica>
| Componente | Peça | Specs-chave |
|---|---|---|
| ADC | TI ADS8688 (SBAS582C) | 8ch single-ended (0-7); 16 bit; throughput agregado MÁX 500 kSPS total (N canais → 500kSPS/N cada); modo AUTO_RST |
| Isolador SPI | ADuM3150 (a confirmar contra esquemático/BOM — item aberto) | família SPIsolator/iCoupler; 6ch; isolação 3.75kV; até 40MHz (delay-clock) / 17MHz (4 fios) |
| Plataforma | BeagleBone: ARM Cortex-A8 (Linux) + PRU-ICSS | PRU0 = bit-bang SPI determinístico; ARM = extrai blocos prontos, grava disco |
| PCB | "DAQ_Module", Altium Designer, `hardware/DAQ_Module/` | esquemático+layout+3D+BOM+Gerber; isolamento galvânico PRU↔frontend |

Constraint física ativa: jumpers longos entre placa de aquisição e frontend → reflexo/ruído induzido → satura leituras ADC. Requer conexão direta board-to-board. Diagnóstico: `scripts/analisar_preambulo.py` + `firmware/spi_core_diagnostico_preambulo.asm` — inspeciona 16 bits de preâmbulo/quadro SPI, devem ser sempre 0.
</arquitetura_fisica>

<arquitetura_firmware>
- `spi_core.asm` (PRU0, Assembly): laço crítico — bit-bang SPI + grava amostras em buffers ping-pong na DDR. `pru_main.c`: init mínima (resource_table p/ remoteproc; clamps de segurança p/ `sample_period_ticks`/`auto_seq_mask` se RAM compartilhada "fria" — inclui zerar `config_ready` no boot).
- `ler_adc.c` (ARM/Linux, C): mapeia controle+buffers via `/dev/mem`; configura canais/freq; grava cabeçalho de metadados (ver `<formato_bin_v2>`); despeja blocos em `.bin`.
- INVARIANTE CRÍTICA: `espera_configuracao` (spi_core.asm) roda 1x por BOOT da PRU — lê `config_ready`/`auto_seq_mask` só nessa janela. Depois, `laco_principal` roda pra sempre e NUNCA relê esses campos (só `sample_period_ticks` é relido a cada amostra). Logo: `ler_adc` DEVE reiniciar núcleo PRU0 via remoteproc (stop→start) ANTES de cada captura, ou uma 2ª captura com lista de canais diferente reaproveita silenciosamente os canais antigos.
  - Mecanismo (`ler_adc.c`, validado em hw): `REMOTEPROC_PRU0_ESTADO="/sys/class/remoteproc/remoteproc1/state"`; `escrever_estado_remoteproc(cmd)` via `open(O_WRONLY)`+`write`+`close` (POSIX puro); `reiniciar_pru_antes_da_captura()` chamada ANTES até de abrir `/dev/mem` (logo após montar `mascara_auto_seq`). "stop" falho = não-fatal (pode já estar parada); "start" falho = fatal.
  - Por que não precisa zerar `config_ready` do lado ARM: boot da PRU (`pru_main.c`) já zera sozinho como parte da init — sem essa dependência, sem janela de corrida.
- Protocolo config (2 transações, SEM LOOP no Assembly, direto): `QBEQ/QBNE/QBBS/QBBC` (branch condicional "rápido" da PRU) codificam deslocamento relativo máx ±511 palavras — insuficiente p/ 1 transação SPI completa (~600+ instr. expandidas); as 2 transações têm durações diferentes (24 vs 32 ciclos) → implementação sem loop favorece simplicidade.
- `PRU_IMEM`: ~5.480/8.192 bytes (~67%) usado, folga confortável.
- Nenhuma amostra é descartada (invariante atual): quadro do comando AUTO_RST (config) já é o quadro c/ dado indefinido; 1º NO_OP do laço principal já retorna dado válido de `canais[0]` (confirmado Fig.100/101 datasheet SBAS582C + fluxo ref. TI E2E). Campo `primeira_amostra_descartada` no cabeçalho mantido por compat, sempre 0.
</arquitetura_firmware>

<shared_control>
Struct `shared_control` (`memoria_pru.h`), 32 bytes, mapeada em região dedicada da RAM interna PRU-ICSS (endereço físico fixo — ver `memoria_pru.h`: `PRU_SHARED_RAM_PHYS`/`PRU_SHARED_RAM_PRU` — p/ endereço exato, não reproduzido aqui p/ evitar divergência não-verificada).

| Offset | Campo | Escrito por | Semântica |
|---|---|---|---|
| 0 | `sample_period_ticks` | ARM (relido pela PRU a CADA amostra) | período entre amostras, ciclos PRU (clock 200MHz) |
| 4 | `active_buffer` | PRU | buffer ativo (0/1) |
| 8 | `buffer_0_ready` | PRU seta / ARM zera | buffer 0 pronto p/ leitura |
| 12 | `buffer_1_ready` | PRU seta / ARM zera | buffer 1 pronto |
| 16 | `buffer_0_addr` | ARM | endereço físico DDR |
| 20 | `buffer_1_addr` | ARM | endereço físico DDR |
| 24 | `config_ready` | ARM seta 1 / PRU zera após ler (e no boot) | handshake config — só lido 1x/boot, ver `<arquitetura_firmware>` |
| 28 | `auto_seq_mask` | ARM (lido 1x pela PRU) | máscara bits, bit N = canal N habilitado |

DDR reservada: `0x9F000000`, 16MB fora do gerenciador de memória Linux; hoje só 4MB usados (2 buffers × 2MB = 2×`SAMPLES_PER_BUFFER`×2 bytes). `SAMPLES_PER_BUFFER=1.048.576` — sincronizado MANUALMENTE com `LDI r21` hardcoded em `spi_core.asm` (sem checagem cruzada compile-time C↔Assembly). `ADS8688_MAX_CANAIS=8`.
Risco conhecido ativo: troca de buffer na PRU não verifica se ARM terminou de processar o anterior (sem backpressure) — corrupção silenciosa possível, risco cresce com freq. de amostragem.
</shared_control>

<protocolo_spi_ads8688>
- Modo AUTO_RST (varredura automática): host programa sequência 1x; ADC avança canal sozinho por quadro, SEMPRE ordem CRESCENTE de nº de canal entre habilitados (não configurável — datasheet SBAS582C §8.4.2.5), independente da ordem digitada na CLI. `ler_adc.c` ordena `canais[]` internamente; ordem impressa no console = ordem real de intercalação.
- Frame do laço principal: 32 ciclos SCLK/amostra (16 comando + 16 leitura da conversão ANTERIOR — pipeline de 1 quadro, sempre). Comando enviado = sempre NO_OP `0x0000` (ADC já sabe próximo canal) → MOSI eletricamente parado na fase de comando (redução de ruído digital acoplado, não quantificada c/ osciloscópio).
- Sequência de config (1x, antes do laço, resultado descartado):
  1. Escreve registrador `AUTO_SEQ_EN` (addr `0x01`) c/ máscara de canais. Cmd 16bit = `0x0300 | máscara` (bits[15:9]=addr, bit[8]=R/W=1, bits[7:0]=dado). Transação usa 24 ciclos SCLK TOTAL (16 cmd + 8 extras — `ADS8688_PROG_DONT_CARE_BITS=8`, confirmado contra driver kernel Linux `drivers/iio/adc/ti-ads8688.c`), diferente da transação normal de 32 ciclos.
  2. Envia `AUTO_RST` (`0xA000`, registrador de comando, transação normal 32 ciclos) — inicia varredura do canal habilitado de menor número.
  Ref: datasheet SBAS582C §8.4.2.5 ("Auto Channel Enable with Reset").
- Pinagem PRU: r30 bit0=SCLK, bit1=MOSI/SDI; r31 bit2=MISO/SDO; r30 bit3=CS. MISO amostrado no último instante seguro antes da borda de descida SCLK.
- Timing CS (calibrado empiricamente, NÃO comparado a mínimos do datasheet — item aberto): setup ≈1µs (200 ciclos), hold ≈0.5µs (100 ciclos), CS-alto mín ≈0.5µs (100 ciclos).
- Amostra intercalada: com N canais, amostra[i] (pós-cabeçalho) pertence a `lista_canais[i % N]` (ordem crescente, = ordem física de varredura).
</protocolo_spi_ads8688>

<formato_bin_v2>
Arquivo `.bin` = cabeçalho FIXO 1024 bytes (magic `"SHAN"`) + amostras brutas `uint16_t`/`int16_t` (2 bytes, intercaladas por canal). Struct `__attribute__((packed))`, little-endian nativo (Cortex-A8). CRC-32/ISO-HDLC (poli `0xEDB88320`, = zlib/PNG/Ethernet), calculado sobre os 1024 bytes com o próprio campo CRC zerado; C = impl. bit-a-bit sem tabela (uso pontual, 2x/captura); Python = `zlib.crc32` (equivalente).

Campos reais somam 672 bytes (v2); padding reservado = 352 bytes (1024-672). `versao_cabecalho` atual = **2**.

| Offset | Campo | Tipo | Notas |
|---|---|---|---|
| 0 | `magic` | `char[4]` | `"SHAN"`, sem terminador nulo |
| 4 | `versao_cabecalho` | `u32` | formato do CABEÇALHO (não do firmware) |
| 8 | `tamanho_cabecalho` | `u32` | 1024 |
| 12 | `timestamp_unix` | `u64` | epoch UTC, capturado no início do parsing de argv (⚠ BeagleBone tipicamente SEM RTC c/ bateria — sincronizar NTP/`scripts/set_date.sh` antes de ensaio timestamp-sensível) |
| 20 | `frequencia_hz` | `u32` | freq TOTAL de transação SPI |
| 24 | `auto_seq_mask` | `u32` | = `shared_control.auto_seq_mask` |
| 28 | `num_canais` | `u32` | popcount da máscara |
| 32 | `lista_canais` | `u8[8]` | ordem crescente; slots não usados = `0xFF` |
| 40 | `samples_per_buffer` | `u32` | = `SAMPLES_PER_BUFFER` no momento da captura |
| 44 | `bytes_por_amostra` | `u32` | hoje sempre 2 |
| 48 | `pru_clock_hz` | `u32` | 200MHz — reconstrói `sample_period_ticks` sem hardcode |
| 52 | `sample_period_ticks` | `u32` | ciclos PRU entre amostras |
| 56 | `primeira_amostra_descartada` | `u32` | sempre 0 (ver `<arquitetura_firmware>`); mantido p/ compat |
| 60 | `duracao_pedida_segundos` | `double` | 0.0 se `--duracao` não usado |
| 68 | `blocos_gravados` | `u64` | preenchido só ao FIM da captura (reescrita no offset 0) |
| 76 | `total_amostras_gravadas` | `u64` | idem |
| 84 | `titulo` | `char[64]` | `-t`, UTF-8, rejeitado (não truncado) se > 63 bytes úteis |
| 148 | `descricao` | `char[256]` | `-d`, mesmas regras, 255 bytes úteis |
| **404** | **`grandeza_por_canal`** | **`u8[8]`** | **[v2]** valores: `TENSAO=0`,`CORRENTE=1`,`TEMPERATURA=2`,`NAO_USADA=0xFF`. Mesma indexação de `lista_canais` (posição i descreve `lista_canais[i]`). Sem `--grandeza` explícito → canal habilitado assume `TENSAO` (padrão histórico) |
| **412** | **`sonda_id_por_canal`** | **`char[8][32]`** | **[v2]** 32 bytes/canal (31 úteis+nulo) ASCII, mesma indexação; string vazia = sem sonda. Só CHAVE de busca (perfil `.json` reside no lado Python); `ler_adc.c` NÃO valida existência do perfil — validação é só Python-side (decisão deliberada) |
| 668 | `header_crc32` | `u32` | offset MUDA entre v1 (404) e v2 (668) — leitor deve ramificar por `versao_cabecalho` ANTES de calcular/conferir CRC |
| 672 | — | `u8[352]` | padding reservado, zerado |

Compat: v1 = campos até `descricao` + `header_crc32` direto no offset 404 (sem os 2 campos novos), 408 bytes de campos reais. Leitor (`adc_tool.py`) faz peek de `versao_cabecalho` (bytes 4-8) ANTES de escolher format string completo — nunca assume v2 cegamente. v1 sem os campos novos → Python sintetiza default (`GRANDEZA_TENSAO` em todo canal, sonda vazia) p/ código downstream nunca precisar checar versão.
Arquivo SEM cabeçalho (magic ausente) = formato legado pré-cabeçalho, ainda suportado (`-f`/`--canais` obrigatórios nesse caso).
</formato_bin_v2>

<cli_ler_adc>
`sudo ./ler_adc <freq_hz> [lista_canais] [--blocos N|--duracao T] [-o ARQ] [-t TXT] [-d TXT] [--grandeza C:G[,...]] [--sonda C:ID[,...]]`
- `freq_hz`: 1–500000 (freq TOTAL, não por canal).
- `lista_canais`: opcional, CSV sem espaço (`0,1,3`); default = canal 1 (único fisicamente conectado por padrão nesta placa). Reordenado ascendente internamente (ver `<protocolo_spi_ads8688>`).
- `--blocos N`: N=0 → indefinido (Ctrl+C); default 1 bloco. `--duracao T`: sufixo `s/m/h` (default s), converte p/ blocos via `SAMPLES_PER_BUFFER/freq`, arredonda p/ CIMA. Mutuamente exclusivas.
- `-o`: default `captura_AAAAMMDD_HHMMSS.bin` (hora local).
- `--grandeza C:G[,...]`: G∈{`tensao`,`corrente`,`temperatura`}. **Chave = número do canal, NÃO posição digitada** (canais são reordenados — mesma classe de bug já corrigida p/ ordenação de canais). Canal não citado → `tensao`.
- `--sonda C:ID[,...]`: aceito em QUALQUER grandeza (não só corrente). ID ≤31 bytes ASCII, rejeitado (não truncado) se maior. Grava só a string; zero validação de existência de perfil.
- Saída: cabeçalho c/ resumo (grandeza/sonda por canal) impresso no console.
</cli_ler_adc>

<modelo_calibracao_sonda>
Correção de tensão = ganho ESCALAR fixo (`--ganho`, constante c/ freq — frontend tem ganho/divisor constante). Corrente NÃO: sonda atenua diferente por frequência → precisa curva de calibração, não escalar. Modelo genérico "perfil de sensor" (extensível a temperatura no futuro, não implementado — ver `<constraints_conhecidas>`).

Perfil = arquivo `.json` em `scripts/sondas/<id>.json`:
```json
{
  "id": "string (= sonda_id gravado no cabeçalho)",
  "tipo": "resposta_frequencia | ganho_fixo",
  "fabricante": "...", "modelo": "...", "numero_serie": "...",
  "tipo_saida": "mV/A | razão+resistor_carga",
  "faixa_freq_valida_hz": [min, max],
  "data_calibracao": "AAAA-MM-DD",
  "calibrado_com": "texto (ex: cadeia completa SH-Analyzer)",
  "incerteza_estimada_pct": 0.0,
  "pontos": [{"freq_hz": 60, "ganho": 1.000}, ...],
  "ganho": 1.0,
  "calibracao_adc": {"formato": "uint16", "faixa_v": {"referencia": 10.24, "sonda": 10.24}, "ganho": {"referencia": 1.0, "sonda": 10.0}, "modo_referencia": "shunt|fixa", "resistencia_shunt_ohms": 0.1, "amplitude_referencia_a": 3.0, "gerado_em": "ISO8601", "n_pontos": 6}
}
```
`calibracao_adc` = metadado gravado por `gerar_perfil_sonda.py` (`resistencia_shunt_ohms` só no modo shunt; `amplitude_referencia_a` só no modo fixo). `adc_tool.py` o usa SÓ para conferência (`conferir_calibracao_perfil`: AVISA se `--ganho`/`--faixa`/`--formato` do canal diferem do usado na geração; nunca entra na matemática; perfil sem o bloco não é conferido). Demais campos lidos: `id`,`tipo`,`pontos` (extras por ponto, ex. `n`/`desvio_pct`, ignorados),`faixa_freq_valida_hz`,`ganho`. Valores NaN/Inf, `ganho`≤0, `freq_hz`≤0 ou repetida → erro limpo (`SystemExit`).
`ganho` = multiplicador LINEAR (não dB); campo `pontos` só p/ `tipo=resposta_frequencia` (mín. 2 pontos); campo `ganho` (escalar) só p/ `tipo=ganho_fixo`. Tipos NÃO suportados ainda: `polinomio`/`tabela` (temperatura) — erro explícito se referenciado.

INVARIANTE de semântica de `ganho(f)`: adimensional, `ganho(f)=S(f)/S_nominal`, com `S(f)`=sensibilidade real da sonda (V/A) em f e `S_nominal=1/--ganho` (sensibilidade que o `--ganho` escalar do canal assume; ex. sonda 100mV/A → `--ganho 10`). `adc_tool.py` aplica `--ganho` primeiro (→ Amperes "nominais") e DEPOIS divide por `ganho(f)` (`aplicar_correcao_sonda`). Logo `ganho(f)≈1` onde a sensibilidade nominal vale (tipic. baixa freq.) e <1 onde a sonda atenua. O perfil só é fisicamente correto em produção com o MESMO `--ganho` do canal da sonda usado ao gerá-lo (gravado em `calibracao_adc.ganho.sonda`; `adc_tool.py` confere e AVISA o fator de erro, não aborta). Alternativa de desenho que elimina a classe de erro (perfil ABSOLUTO S(f) em V/A) está em `docs/auditoria_perfil_sonda.md` §4.2, não implementada.

Resolução do perfil por canal (hierarquia 3 níveis, mesma de `--canais`/`--faixa`): `--sonda-perfil CANAL:ARQUIVO` explícito > `sonda_id` do cabeçalho (v2+) + busca `<--sondas-dir>/<id>.json` (default: `scripts/sondas/` ao lado do script) > sem correção (fallback `--ganho` escalar + aviso no console). O id do cabeçalho só é aceito se casar `^[A-Za-z0-9][A-Za-z0-9_.-]*$` e sem `..` (evita sair de `--sondas-dir`; `ler_adc.c` não valida caracteres); `--sonda-perfil` é livre. Aviso se o `id` dentro do `.json` ≠ id do cabeçalho.
`--grandeza CANAL:G` no `adc_tool.py`: mesma hierarquia (CLI > cabeçalho v2+ > default tensão) — necessário p/ arquivos legados sem cabeçalho v2.
</modelo_calibracao_sonda>

<pipeline_dsp_python>
`scripts/adc_tool.py`. 3 modos: plotagem (padrão), conversão `.bin↔.csv` (streaming, blocos, sem RAM cheia), exportação HDF5 (idem, `numpy.memmap` em blocos).

**Leitura de cabeçalho**: `_FORMATO_CABECALHO_V1`/`_V2` (struct format strings); peek de `versao_cabecalho` decide qual usar. `_consumir()` (helper) contorna limite do Python de só 1 `*` por unpack de tupla (cabeçalho tem 3 campos multi-valor: `lista_canais`, `grandeza_por_canal`, `sonda_id_por_canal`). `CabecalhoArquivo` sempre expõe `grandeza_por_canal`/`sonda_id_por_canal` (v1 sintetiza default). `CABECALHO_VERSAO_SUPORTADA=2`.

**Correção de sonda** (`aplicar_correcao_sonda`): divisão espectral direta — `n_fft=next_fast_len(n)`; `espectro=rfft(sinal,n_fft)`; `ganho=perfil.ganho_em(rfftfreq(n_fft,1/fs))`; `espectro/=ganho`; `sinal=irfft(...)[:n]`. Aplicada 1x, ANTES de recorte em ciclos / `--fft` / `--welch` / filtro Butterworth opcional do usuário / plot. Correção de MAGNITUDE pura: restaura a AMPLITUDE de cada componente (erro <0.1% em tons de teste) mas NÃO a fase — forma de onda no tempo do canal corrigido NÃO é a corrente real (sintético: erro RMS ~42% com amplitudes exatas) e não serve p/ potência/impedância entre canais (`docs/auditoria_perfil_sonda.md` §4.1). Aplica a canais `CORRENTE` (perfil obrigatório; sem perfil só avisa) E a canais de `TENSÃO` com sonda registrada (id no cabeçalho ou `--sonda-perfil`); `TEMPERATURA` com sonda → aviso, não aplica; `--sem-correcao-sonda` desliga. Avisos: `--ganho`/`--faixa`/`--formato` ≠ geração do perfil; fora da faixa válida (DC excluído; usa `faixa_freq_valida_hz` se houver; acima do último ponto a amplitude corrigida fica ABAIXO do real se a sonda continua caindo); amplificação de ruído >20 dB. Custo: 20M amostras/canal em ~1.5 s, ~32 B/amostra de RAM extra.
`PerfilSonda.ganho_em(freqs)`: interpolação PCHIP (`scipy.interpolate.PchipInterpolator`, monotônica, sem overshoot) sobre `(log10(freq), ganho_dB)`. Fora da faixa dos pontos calibrados: CLAMP no extremo mais próximo (nunca extrapola), aviso único por perfil (não por bin).

**`--fft`** (ciclo-sincronizado, p/ fundamental+harmônicos, fase travada à rede): (1) estimativa grosseira via FFT+Hann em `[freq_min,freq_max]` (default 45–65Hz); (2) refino por interpolação parabólica em log-magnitude (`refinar_pico_parabolico`, corrige scalloping loss sem FFT maior); (3) passa-baixa Butterworth SOS (`sosfiltfilt`, fase zero) isola fundamental antes de detectar cruzamento — SOS (não `(b,a)` clássico) por estabilidade numérica em fs/f0 extremo (dezenas de milhares:1); (4) cruzamentos por zero ASCENDENTES, interpolação LINEAR entre amostras; (5) período refinado usando TODOS os ciclos disponíveis (dilui erro de 1 cruzamento), corte exato nesse nº de ciclos antes da FFT principal. `--fft N`: pré-trunca a estimativa de amostras p/ N ciclos (`estimar_amostras_para_n_ciclos`) antes de filtrar — não processa captura inteira p/ ver só o início.

**`--welch`** (segmentado+médio, p/ supraharmônicos, SEM relação de fase c/ rede — corte de ciclo não elimina vazamento desse conteúdo): segmento = `round(fs_efetiva/--resolucao-welch)` amostras (default 200Hz); sobreposição default 50% (`--sobreposicao-welch`); cada segmento janelado+transformado; periodogramas `|X(f)|²` MEDIADOS (não fases). Vetorizado em lotes via `numpy.lib.stride_tricks.sliding_window_view` (`TAMANHO_LOTE_WELCH_PADRAO=2048` segmentos/lote) — equilíbrio desempenho (FFT vetorizada) × memória (captura longa+overlap → centenas de milhares de segmentos).

**Janelas** (`--janela`): `retangular/boxcar` (default), `hann`, `blackmanharris` (lóbulos laterais baixos, separa supraharmônico fraco perto de fundamental forte), `flattop` (melhor exatidão amplitude, pior resolução), `kaiser`+`--kaiser-beta` (default 8.6≈Blackman). `fftbins=True` (variante periódica, não simétrica).

**`--modo-espectro {tom,ruido}`**: `tom` (default) = amplitude linear ÷ ganho coerente da janela (média dos valores) — correto p/ tom discreto. `ruido` = PSD (V²/Hz) ÷ ganho incoerente/ENBW (soma dos valores²) — correto p/ banda larga (senão leitura muda artificialmente c/ tamanho FFT/segmento p/ mesmo ruído físico).

**`--agrupar-bandas HZ`**: resume espectro em bandas de largura fixa (convenção supraharmônicos), RMS em dBV por banda — soma POTÊNCIAS dos bins (`tom`) ou integra PSD sobre a banda (`ruido`); convergem p/ mesma grandeza física (energia na banda).

**`--picos LIMIAR_DB`**: `scipy.signal.find_peaks` em `[--freq-min-picos(default 2000Hz, IEC 61000-4-7), --freq-max-picos]`, refino parabólico; opera no espectro FINO (antes de `--agrupar-bandas`); `--distancia-minima-picos` (default 100Hz) evita contar mesmo lóbulo 2x.

**Filtro digital opcional**: Butterworth SOS+`sosfiltfilt`, `--filtro-passa-baixa`/`--filtro-passa-alta` (Hz), `--ordem-filtro` (4–8, default 5). Ordem de aplicação por canal: calibração(`--faixa/--ganho/--offset`) → correção de sonda (se corrente) → filtro Butterworth do usuário → resto do pipeline. Validado contra Nyquist EFETIVA (por canal, não freq total). `--fft`+`--filtro-passa-alta≥freq_min` invalida estimativa de f0 (remove banda da fundamental) — script detecta e avisa, recomenda `--fft` e `--welch`/`--picos` em comandos separados.

**Multi-canal**: `--canais/--canais-exibir/--layout-canais{separados,sobrepostos}`; calibração `--faixa/--ganho/--offset` (escalar ou lista/canal); `desintercalar()` via `reshape(-1,num_canais)` (view, sem cópia, funciona em memmap). Rótulo eixo Y da forma de onda AGORA grandeza-aware (`rotulo_eixo_grandeza`: "Tensão (V)"/"Corrente (A)"/"Temperatura (°C)" por canal; grandezas mistas em `sobrepostos` → rótulo genérico + aviso).

**HDF5** (`--export-hdf5`): streaming em blocos sobre memmap (RAM ~constante, verificado empírico `tracemalloc` em arquivo sintético 130MB). `/amostras` (código bruto, 2D amostras×canal) + opcional `/tensao_v` (float32, calibrado). Attrs raiz = todos campos do cabeçalho + `grandeza_por_canal`/`sonda_id_por_canal` (v2) + calibração usada. Escopo DELIBERADAMENTE limitado: correção de sonda NÃO aplicada aos valores exportados (exigiria repetir divisão espectral em streaming/blocos vs. abordagem atual de sinal inteiro) — `/tensao_v` é sempre calibração pura `--faixa/--ganho/--offset`, mesmo p/ canal de corrente.

**CSV**: round-trip só via `valor_bruto`; cabeçalho/metadados NÃO sobrevivem ao round-trip (CSV não tem onde guardar).
</pipeline_dsp_python>

<ferramenta_calibracao_bancada>
`scripts/calibrar_sonda.sh` — bash puro (4.3+, nameref `local -n`), SEM Python/interpretador externo. Matemática via `bc -l` (funções `l()`/`e()`): espaçamento LOG (não linear) entre `freq_min`/`freq_max` p/ malha nova; média GEOMÉTRICA `sqrt(f1·f2)` (não aritmética — ponto equidistante em escala LOG, consistente c/ malha original) p/ adensar malha existente (parseia frequências já capturadas de `capturas/<sonda>/calibracao_<FREQ>Hz_rep<N>.bin`). Nyquist validado estritamente (`f_max < taxa/2`) via `bc`.
Bancada assumida (canais configuráveis no topo do script): `CANAL_REFERENCIA=0` = tensão sobre shunt de precisão (corrente real = V/R, calculada depois na análise); `CANAL_SONDA=1` = sonda sob calibração. Chama `ler_adc <taxa> <ref>,<sonda> --grandeza <sonda>:corrente --sonda <sonda>:<id_sanitizado> -o ... -t ...`.
Fluxo por ponto×repetição: checagem de espaço em disco (`df`, default crítico <50MB, PAUSA não aborta sozinho) → pausa p/ operador ajustar gerador → chama `ler_adc` → menu `[C]ontinuar/[R]efazer/[A]bortar`. Versiona arquivo (`_v2`,`_v3`) em vez de sobrescrever. Manifesto `capturas/<sonda>/pontos_coletados.csv` (freq,rep,arquivo,timestamp,status — incl. status `sem_arquivo` se aceito sem output real). Requer root (chama `ler_adc`, que acessa `/dev/mem`); resolve caminho de `ler_adc` relativo ao PRÓPRIO script.
Convenções internas OBRIGATÓRIAS (regressão fácil se violadas): TODA saída informativa (`log_info/log_sucesso/log_aviso/log_erro`) vai p/ stderr, NUNCA stdout — stdout reservado a valor de retorno de função chamada via `$(...)` (ex. `caminho_disponivel`); TODO `read` checa EOF explicitamente (senão loop infinito em stdin fechado); menu de validação de escolha é laço SEPARADO do laço de medição (opção inválida não pode disparar remedição).
Não faz NENHUMA análise de amplitude/ganho — só coleta; análise = `scripts/gerar_perfil_sonda.py` (`<ferramenta_geracao_perfil>`). Fluxo completo: `calibrar_sonda.sh` (coleta) → `gerar_perfil_sonda.py` (análise → `.json`) → `adc_tool.py` (aplica a correção).
</ferramenta_calibracao_bancada>

<ferramenta_geracao_perfil>
`scripts/gerar_perfil_sonda.py <pasta_capturas>` — Python (numpy/scipy/matplotlib); `import adc_tool` (mesma pasta, via `sys.path` do próprio arquivo) reaproveita `ler_cabecalho`, `carregar_amostras_bin`, `desintercalar`, `converter_para_tensao`, `analisar_lista_calibracao`, `resolver_offsets_por_canal`, `calcular_espectro_welch`, `refinar_pico_parabolico`, `PerfilSonda`, `carregar_perfil_sonda` — sem reimplementar header/FFT/Welch.
- Entrada: `capturas/<sonda>/calibracao_<FREQ>Hz_rep<N>[_vM].bin` (descobertos por glob+regex no disco; manifesto `pontos_coletados.csv` só anota avisos de status `aceito_com_erro_*`, nunca é fonte de verdade). Saída: `scripts/sondas/<id>.json` (default; `-o` sobrescreve; `--id` default = nome da pasta).
- Corrente real de referência (obrigatório, mutuamente exclusivos): `--resistencia-shunt OHMS` [recomendado] → `corrente_real(f)=V_ref_medida(f)/R` por arquivo (absorve deriva de amplitude do gerador); `--amplitude-referencia A` → corrente constante em toda a varredura (NÃO absorve deriva).
- Canais: auto-detecção pelo cabeçalho v2 (exatamente 2 canais; `grandeza==CORRENTE` = sonda, o outro = referência); override `--canal-referencia/--canal-sonda` (funciona também com >2 canais: desintercala e calcula `fs_efetiva` pela lista de canais do cabeçalho; ref==sonda rejeitado); captura legada sem cabeçalho exige também `-f/--frequencia` (Hz, total). `--formato/--faixa/--ganho/--offset` com mesma semântica/parsing de `adc_tool.py` (default uint16, 10.24, 1.0, offset auto), listas indexadas por PAPEL `[referencia,sonda]` — NÃO pela ordem numérica dos canais; 1 valor vale p/ os 2.
- `medir_tom` (por arquivo, em cada canal): Welch modo `tom`; janela default `flattop` (exatidão de amplitude de tom isolado; resolução em freq. irrelevante, freq. aprox. já conhecida); sobreposição 0.75; resolução ADAPTATIVA `min(--resolucao-welch[100Hz], max(1, f_alvo/10))` (resolução fixa grossa demais em f baixa → interpolação parabólica extrapola mal); janela de busca `f_alvo ± --tolerancia-freq-pct` (10%), largura mínima 3 bins; piso de ruído = mediana do espectro fora de guarda ±10 bins do pico (DC excluído); pico precisa exceder o piso em `--snr-minimo-db` (20dB) senão o arquivo é PULADO (evita ponto-lixo de canal só com ruído, ex. sonda desconectada); refino parabólico; amplitude linear = 10^(dB/20).
- Frequência de cada ponto é MEDIDA (média das estimativas de sonda e referência), não copiada do nome do arquivo/manifesto (operador ajusta o gerador à mão); o nome só dá a dica da janela de busca e a chave de agrupamento.
- Agregação: agrupa por `freq_alvo` nominal (inteiro Hz do nome; repetições e versões `_vM` do mesmo alvo juntam); `freq_hz` gravado = média das medidas; `ganho` = média de `amplitude_sonda/corrente_real` por arquivo (`amplitude_sonda` já pós-`converter_para_tensao` c/ o `--ganho` da sonda); `desvio_pct` = stdev/média, >10% → aviso (remedir). Sanidade: ganho na menor freq fora de [0.7,1.3] → aviso (`--ganho` provavelmente ≠ 1/sensibilidade_nominal). Captura com >0.05% das amostras no código mínimo/máximo do ADC (saturação) é PULADA com aviso. Mínimo 2 pontos válidos, senão erro. Cada ponto do JSON grava também `n` (repetições) e `desvio_pct`.
- JSON: schema em `<modelo_calibracao_sonda>`; `faixa_freq_valida_hz` auto = [menor,maior] freq. medida (override `--faixa-freq-valida`); metadados opcionais `--fabricante/--modelo/--numero-serie/--tipo-saida/--incerteza-estimada-pct/--calibrado-com/--data-calibracao`. Escrita em 2 tempos: grava `<saida>.tmp`, valida round-trip via `adc_tool.carregar_perfil_sonda`, só então substitui (perfil existente vira `<saida>.bak` + aviso; falha de validação preserva o anterior). `--plot` → PNG (pontos + curva PCHIP via `adc_tool.PerfilSonda`, mesma interpolação de produção).
</ferramenta_geracao_perfil>

<status_validacao>
HW-validado: protocolo 32 ciclos + sequência AUTO_SEQ_EN/AUTO_RST; handshake `config_ready`+reinício PRU/captura; AUTO_RST multi-canal (5ch simultâneos @102.4kHz agregado, ~20.48kHz efetivo/canal — canal conectado mostra 60Hz, desconectado mostra ruído); `PRU_IMEM` dentro do orçamento.
Sintético-validado (não hw): pipeline espectral `adc_tool.py` completo (`--fft`,`--welch`,`--modo-espectro`,`--agrupar-bandas`,`--picos`, multi-canal c/ aliasing proposital, round-trip `.bin↔.csv`) — sinais gerados em Python (fundamental 60Hz+supraharmônicos+dithering+ruído gaussiano); pico injetado 15.321,3Hz → recuperado 15.321,37Hz (erro compatível c/ resolução espectral). Correção de sonda + geração de perfil: validadas com capturas sintéticas (6 freq × 3 reps, curva de atenuação conhecida, deriva ±8% de amplitude e ±2% de frequência por repetição): `gerar_perfil_sonda.py --resistencia-shunt` recupera o ganho verdadeiro (diferença ≤0.2% vs. curva, desvio entre reps ≤0.4%); `--amplitude-referencia` mostra desvio entre reps até ~6% (deriva não absorvida — motivo da recomendação do shunt); ciclo completo perfil→`adc_tool.py` num tom interpolado (3kHz, 2.0A reais) recupera 5.98dB vs 6.02dB esperado (~0.5% de erro de amplitude = interpolação PCHIP com só 6 pontos); sonda desconectada rejeitada por SNR; papéis de canal invertidos (sonda no canal de número menor) validados. `calibrar_sonda.sh` testado com `ler_adc` mock (~15 cenários, shellcheck limpo). NADA disso validado em hardware real ainda.
Auditoria (2026-10, sintética): `docs/auditoria_perfil_sonda.md`. Estimador de amplitude (Welch+flattop+parabólico) ≡ ajuste senoidal LS (desvio ≤0.008% de 100Hz a 80kHz) — não trocar por exatidão; erro de interpolação PCHIP vs nº de pontos (100Hz–80kHz, curva suave): 7→1.9%, 12→0.6%, 18→0.17%, 25→0.06%; ressonância estreita só é vista se um ponto cair nela. 7 bugs corrigidos; suíte `scripts/testes/test_perfil_sonda.py` (11 testes, sem hardware).
PENDENTE (próximo marco real): validação quantitativa em bancada controlada — sinal/ruído de amplitude/freq CONHECIDAS injetado, medido, comparado. `calibrar_sonda.sh` (coleta) + `gerar_perfil_sonda.py` (análise → perfil `.json`) cobrem o fluxo operacional completo; falta executar uma calibração real de sonda em bancada, validar o cabeçalho v2 numa captura real e conferir a exatidão do perfil resultante contra uma referência independente.
</status_validacao>

<estrutura_repositorio>
| Caminho | Papel |
|---|---|
| `firmware/ler_adc.c` | CLI ARM; monta máscara; reinicia PRU/captura; grava/atualiza cabeçalho v2; `--grandeza`/`--sonda` |
| `firmware/spi_core.asm` | laço PRU0 tempo-crítico, AUTO_RST |
| `firmware/pru_main.c` | init PRU (resource_table, clamps, zera `config_ready` no boot) |
| `firmware/memoria_pru.h` | struct `shared_control`, `SAMPLES_PER_BUFFER`, `ADS8688_MAX_CANAIS`, endereços físicos |
| `firmware/debug_sh_analyzer.sh` | diagnóstico remoteproc/dmesg/`shared_control` ao vivo via `/dev/mem`, sem interromper captura |
| `firmware/Makefile` | `make` → `ler_adc` (gcc -O3) + `fw_pru.out` (clpru) |
| `scripts/adc_tool.py` | pós-processamento: cabeçalho v1/v2, correção de sonda, FFT/Welch, bandas/picos, conversão, HDF5 |
| `scripts/sondas/*.json` | perfis de sonda (formato ver `<modelo_calibracao_sonda>`) |
| `scripts/calibrar_sonda.sh` | coleta interativa de calibração de sonda (bash puro) |
| `scripts/testes/test_perfil_sonda.py` | suíte sintética de regressão do fluxo perfil→correção (`python3 scripts/testes/test_perfil_sonda.py`, ~1 min, sem hardware) |
| `scripts/gerar_perfil_sonda.py` | análise das capturas de `calibrar_sonda.sh` → perfil `scripts/sondas/<id>.json` (Welch+SNR, ganho vs corrente real; importa `adc_tool.py`) |
| `capturas/<sonda>/` | saída de `calibrar_sonda.sh`: `calibracao_<FREQ>Hz_rep<N>.bin` (ignorados pelo `.gitignore`, `*.bin`) + `pontos_coletados.csv` |
| `scripts/set_date.sh` | sincroniza data/hora local→BeagleBone via SSH (sem RTC c/ bateria) |
| `scripts/compactar_amostras.sh` | arquivamento `.bin`/`.h5` (7z/LZMA2 padrão, `zpaq -m5` opcional) |
| `scripts/analisar_preambulo.py` | diagnóstico integridade SPI (16 bits preâmbulo) |
| `hardware/DAQ_Module/` | projeto Altium (esquemático+PCB) |
| `docs/contexto_projeto.md` | este documento |
| `docs/proposta_correcao_sonda.md` | rationale de design da correção de sonda (histórico da decisão — spec vigente está em `<modelo_calibracao_sonda>`/`<pipeline_dsp_python>` acima); o "calibrar_sonda.py" citado em §7.1 = hoje `gerar_perfil_sonda.py` (o nome `calibrar_sonda` ficou com o script bash de coleta) |
| `docs/auditoria_perfil_sonda.md` | auditoria de confiabilidade do perfil/correção: evidências, bugs corrigidos, limites de bancada, melhorias propostas (fase complexa, perfil absoluto, hold-out) |
| `docs/melhorias-propostas.md` | itens de melhoria abertos (ver `<constraints_conhecidas>`) |
| `docs/notas_relatorio.md` | roteiro cronológico p/ relatório final |
</estrutura_repositorio>

<constraints_conhecidas>
Itens abertos, não bloqueantes, ordenados por relevância:
- Timing CS (200/100/100 ciclos) calibrado empírico, NÃO comparado a mínimos do datasheet — maior potencial de ganho de freq. máxima identificado, requer osciloscópio p/ ajustar com segurança.
- Backpressure ausente no ping-pong (`<shared_control>`) — risco de corrupção silenciosa cresce c/ freq.
- `SCHED_FIFO`+`mlockall()` (lado ARM) não implementado; `usleep(2000)` do polling não revisado.
- `SAMPLES_PER_BUFFER`/`ADS8688_MAX_CANAIS`/valores `GRANDEZA_*` sincronizados MANUALMENTE entre C e Python — sem arquivo de constantes compartilhado.
- Isolador ADuM3150 — peça a confirmar contra esquemático/BOM real.
- Tipo de perfil `polinomio`/`tabela` (sensores de temperatura) — não implementado; `--grandeza temperatura` aceito na CLI/cabeçalho mas sem caminho de correção correspondente no `adc_tool.py`.
- Correção de sonda não aplicada a `/tensao_v` na exportação HDF5 (só no modo plotagem) — ver `<pipeline_dsp_python>`.
- Possível discrepância de maiúsculas/minúsculas no nome de arquivo `adc_tool.py` em disco vs. referenciado (sensível em filesystems Linux) — ver `docs/melhorias-propostas.md`.
- Correção de sonda é só de MAGNITUDE (sem fase); canais multiplexados têm atraso de 1/f_total entre si (36° a 40kHz @400kS/s). Calibração de ganho COMPLEXO (campo `fase_graus` já reservado no formato; ref no canal 0 e sonda no canal 1 nos mesmos slots em calibração e produção cancelaria o atraso de amostragem) é pré-requisito p/ qualquer análise V×I em supraharmônicos — não implementado (`docs/auditoria_perfil_sonda.md` §4.1).
- Confiabilidade FÍSICA do perfil depende da bancada, não do software: ESL/tolerância do shunt, canal de referência assumido plano (testar mesmo sinal nos 2 canais), pureza/deriva do gerador, linearidade da sonda (resposta muda c/ amplitude e c/ CC/fundamental presente), ressonâncias entre pontos (sem hold-out hoje), envelhecimento (sem aviso de perfil velho).
- Exportações (`--export-hdf5`/`--converter`) não aplicam a correção de sonda; sem atributo explícito indicando isso no `.h5`.
- Perfil gerado com referência medida pelo próprio SH-Analyzer (modo shunt) caracteriza sonda + cadeia de aquisição combinadas (ADC+isolador+frontend), não a sonda isolada — recalibrar se o frontend mudar (`calibrado_com` registra isso).
- `gerar_perfil_sonda.py`: auto-detecção só p/ capturas de exatamente 2 canais (referência+sonda); exatidão entre pontos depende da densidade da malha (PCHIP c/ 6 pontos ≈ 0.5% de erro; usar 15–25 pontos log-espaçados, adensando onde a curva tem joelhos via modo "Expandir" de `calibrar_sonda.sh`).
- `docs/proposta_correcao_sonda.md`: campo `sonda_perfil_crc32_por_canal` (rastreabilidade de qual versão do perfil foi usada na captura) foi PROPOSTO e DESCARTADO — `ler_adc.c` nunca tem acesso ao conteúdo do `.json` (só ao id), então não pode hashear; se implementado no futuro, precisa nascer do lado Python (ex. atributo HDF5).
</constraints_conhecidas>
