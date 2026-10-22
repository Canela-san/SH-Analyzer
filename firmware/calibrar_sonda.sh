#!/bin/bash
#
# ==============================================================================
# calibrar_sonda.sh -- coleta automatizada dos pontos de calibração de uma "sonda"
# do SH-Analyzer: uma sonda de CORRENTE ou a cadeia de um canal de TENSÃO
# (roda NA BEAGLEBONE, ao lado do binário `ler_adc`).
# ==============================================================================
#
# PARA QUE SERVE
#   O perfil de uma sonda (scripts/gerar_perfil_sonda.py) é o ganho dela medido em
#   várias frequências. Fazer isso na mão significaria chamar o `ler_adc` dezenas de
#   vezes, repetindo a taxa, os canais e todos os metadados do cabeçalho (grandeza, id
#   da sonda, título), sem saber de antemão quais frequências valem a pena. Este
#   script faz isso por você:
#
#     1. você diz QUANTOS pontos quer e a TAXA de amostragem do ADC;
#     2. ele ESCOLHE as frequências (espaçadas em escala logarítmica, dentro do
#        que a taxa permite medir) e mostra o plano;
#     3. para cada ponto ele pede "INJETE <f> Hz" no gerador de sinal, chama o
#        `ler_adc` com o cabeçalho certo e confere o `.bin` gerado (cabeçalho,
#        tamanho, saturação do ADC, nível do sinal, frequência realmente
#        injetada);
#     4. você aceita, refaz, pula ou aborta cada ponto;
#     5. no fim ele resume a coleta e sugere pontos EXTRAS onde a resposta da
#        sonda varia mais entre vizinhos (a "melhor frequência" a mais é a que
#        fica onde a curva muda rápido).
#
# O QUE É "A SONDA" (--grandeza)
#   O perfil descreve o CONJUNTO medido de ponta a ponta, não um componente isolado:
#     corrente (padrão)  sonda de corrente (garra, TC, Rogowski...) + frontend + ADS8688;
#     tensao             a cadeia de um canal de tensão: divisor/ponta + frontend + ADS8688.
#   O ADS8688 tem um filtro passa-baixa interno de 2ª ordem em cada canal (~15 kHz): ele
#   entra no perfil e a correção em produção o desfaz. A grandeza vai para o cabeçalho de
#   cada captura (ler_adc --grandeza), como o canal estará em produção.
#
# BANCADA ESPERADA
#   Um gerador de senoide alimenta a ENTRADA do conjunto:
#     corrente  o gerador (com amplificador, se preciso) faz a corrente passar por um
#               resistor shunt de precisão em série com o condutor que atravessa a sonda;
#     tensão    o gerador (em High-Z) vai direto ao nó de entrada do divisor/ponta.
#   A saída do conjunto vai para o canal do ADC dado em --canal-sonda (é obrigatório dizer
#   qual). O que foi injetado pode ser conhecido de quatro jeitos -- só muda o que você faz
#   na bancada; o perfil é gerado depois por scripts/gerar_perfil_sonda.py:
#
#     1 canal + osciloscópio (--ref-externa)  [RECOMENDADO]  a cada ponto você digita o RMS
#        lido no osciloscópio: a tensão sobre o shunt (corrente) ou a tensão na entrada da
#        cadeia (tensão). Só um canal do ADC é capturado, então a Nyquist efetiva vai até
#        taxa/2 (o dobro do modo de 2 canais) e a cadeia medida é a mesma da produção.
#     1 canal + amplitude conhecida (--amplitude 500mVpp)  o gerador injeta uma SENOIDE pura
#        de amplitude conhecida. O script GRAVA essa amplitude e a frequência nos metadados de
#        cada captura (campo "descrição" do cabeçalho do .bin): "ref: f=1000Hz amp=500mVpp".
#        Com --amplitude-por-ponto ele pergunta a amplitude a cada frequência (para gerador
#        que não mantém o nível). Nada é digitado depois: o gerar_perfil_sonda.py lê os
#        metadados. Em V, a amplitude é a tensão NO PINO DO ADC (antes do --ganho): na cadeia
#        de tensão, a da entrada x a razão do divisor (20 Vpp x 0,051662 = 1.0332Vpp).
#        Também vai até taxa/2.
#     1 canal, amplitude constante SEM declarar (padrão sem outras opções)  você garante que a
#        amplitude é a mesma em todas as frequências e a informa depois em
#        gerar_perfil_sonda.py --amplitude-referencia. Também taxa/2.
#     2 canais (--canal-referencia R)  um SEGUNDO canal do ADC mede o que foi injetado (a
#        tensão sobre o shunt, ou a tensão de entrada da cadeia). Sem digitar nada, mas a taxa
#        total é dividida entre os 2 canais (Nyquist efetiva = taxa/4) e o canal de referência
#        passa pelo MESMO filtro de ~15 kHz do ADS8688, que se cancela na razão: este perfil
#        NÃO inclui o filtro do ADC.
#
#   Ajuste a amplitude para o sinal ocupar de ~20% a ~80% da escala do ADC (sem saturar).
#
# USO
#   sudo ./calibrar_sonda.sh                      # modo interativo (pergunta tudo)
#   sudo ./calibrar_sonda.sh --taxa 102400 --canal-sonda 1 --pontos 20 --sonda fluke_i30_sn0001 --ref-externa
#   sudo ./calibrar_sonda.sh --taxa 100000 --canal-sonda 1 --pontos 24 --freq-max 45k --sonda cadeia_tensao --grandeza tensao --ref-externa
#   sudo ./calibrar_sonda.sh --taxa 102400 --canal-sonda 1 --canal-referencia 0 --pontos 20 --sonda fluke_i30_sn0001
#   sudo ./calibrar_sonda.sh --taxa 102400 --canal-sonda 1 --pontos 20 --sonda fluke_i30_sn0001 --amplitude 500mVpp
#   sudo ./calibrar_sonda.sh --modo retomar --sonda fluke_i30_sn0001
#   sudo ./calibrar_sonda.sh --modo refinar --sonda fluke_i30_sn0001
#   sudo ./calibrar_sonda.sh --modo refazer --freqs 200,1000 --sonda fluke_i30_sn0001
#   ./calibrar_sonda.sh --help                    # todas as opções
#
# MODOS
#   novo     plano novo de N pontos log-espaçados (padrão).
#   retomar  continua uma coleta interrompida: mede só o que falta do plano.
#   refinar  adiciona pontos onde o ganho (medido na coleta) muda mais entre
#            frequências vizinhas.
#   adensar  adiciona 1 ponto (média geométrica) entre CADA par de frequências
#            já capturadas.
#   refazer  mede de novo pontos JÁ aceitos (--freqs); a captura antiga só sai
#            de cena depois que a nova é aceita, e vai para descartadas/.
#   resumo   só mostra a tabela da coleta e os próximos passos (não mede nada).
#
# O QUE FICA EM DISCO  (pasta capturas/<id-da-sonda>/, relativa a onde você rodou)
#   calibracao_<FREQ>Hz_rep<N>.bin   capturas aceitas (é o que gerar_perfil_sonda.py lê)
#   pontos_coletados.csv             manifesto: HISTÓRICO de cada ponto (status e métricas rápidas)
#   plano_coleta.txt                 grandeza, taxa, canais, repetições e frequências do plano
#   referencia_externa.csv           (só com --ref-externa) leituras do osciloscópio, uma por captura:
#                                    coluna v_shunt_rms_V (corrente) ou tensao_rms_V (tensão)
#                                    (com --amplitude a referência fica DENTRO de cada .bin: ref: f=.. amp=..)
#   ler_adc.log                      saída completa do ler_adc (útil se algo falhar)
#   descartadas/                     capturas substituídas pelo modo refazer (nunca apagadas)
#   (capturas/_arquivadas/           coletas antigas que você mandou "começar do zero")
#
# DEPOIS DA COLETA (no computador, a partir da raiz do repositório; o script imprime o comando exato no fim)
#   1 canal + scope:     uv run scripts/gerar_perfil_sonda.py capturas/<id> --referencia-externa --resistencia-shunt <ohms> --ganho <G> --plot
#                        (tensão: sem --resistencia-shunt, a leitura já é a tensão de entrada)
#   1 canal, amplitude:  uv run scripts/gerar_perfil_sonda.py capturas/<id> --ganho <G> --plot     (lê "ref: amp=" dos metadados)
#   1 canal, constante:  uv run scripts/gerar_perfil_sonda.py capturas/<id> --amplitude-referencia <amplitude> --ganho <G> --plot
#   2 canais:            uv run scripts/gerar_perfil_sonda.py capturas/<id> --resistencia-shunt <ohms> --ganho <G_ref>,<G> --plot
#   <G> é o mesmo --ganho que o canal terá no adc_tool.py em produção: o perfil sai relativo a ele.
#
# DECISÕES DE PROJETO (leia antes de mexer)
#   * SEM Python/interpretador externo: só bash + utilitários padrão do Debian
#     (awk, od, gzip, sed, sort, timeout...). A matemática de ponto flutuante é
#     feita em awk (o `bc` deixou de ser necessário).
#   * SEM 'set -e': o fluxo depende de checar códigos de saída que PODEM falhar
#     (ler_adc travado por SPI, por exemplo) sem encerrar o script -- é para isso
#     que existe o menu [C]ontinuar/[R]efazer/[P]ular/[A]bortar. 'set -u' e
#     'pipefail' continuam ligados.
#   * Cada captura vai primeiro para um arquivo temporário (.em_andamento_*.bin) e
#     só ganha o nome definitivo depois de aceita: um .bin parcial, descartado ou
#     de uma execução interrompida nunca é confundido com um ponto válido.
#   * Toda saída informativa vai para stderr, NUNCA stdout: stdout é reservado ao
#     valor de retorno das funções chamadas com $(...).
#   * Todo `read` trata EOF explicitamente (senão há laço infinito com stdin fechado).
#   * Nunca use 'while read ... done <<< "$lista"' em volta de código que também lê o
#     teclado: o here-string substitui o stdin de TODO o laço (ver coletar_pares).
#   * O menu de escolha é um laço SEPARADO do laço de medição: uma opção inválida
#     nunca dispara uma nova medição.
#   * A Nyquist é a EFETIVA POR CANAL: a taxa total é dividida entre os canais
#     capturados, então o limite é taxa/(2*canais): taxa/2 com 1 canal (padrão),
#     taxa/4 com 2. O script recusa frequências a partir de 98% da Nyquist e avisa
#     acima de 90%.
#   * As checagens rápidas (saturação, nível, frequência) são para dar feedback
#     imediato ao operador; a medição de verdade (Welch, SNR, ganho) é do
#     gerar_perfil_sonda.py.
#   * Todo texto que depende de ser corrente ou tensão (onde se mede a referência,
#     exemplos de amplitude, coluna do CSV) sai de definir_grandeza(): não escreva
#     "shunt" ou "corrente" fixos numa mensagem nova.
#
# PARA TESTES: SH_LER_ADC=<caminho> troca o executável do ler_adc; SH_LER_ADC_TIMEOUT=<s>
# muda o limite de tempo de uma captura; SH_PULAR_VERIFICACAO_ROOT=1 dispensa o 'sudo'.
# tests/test_calibrar_sonda.py usa os três com um ler_adc falso. Quem faz 'source' deste arquivo
# só carrega as funções (o main não roda), o que permite testá-las uma a uma.
#
# Requisitos: bash 4.4+ (nameref), coreutils GNU (od, timeout, df, find -printf),
# awk (mawk ou gawk), gzip, sed. Todos presentes numa BeagleBone com Debian.
# ==============================================================================

set -u
set -o pipefail

# Ponto decimal sempre '.', qualquer que seja o idioma do sistema (awk e printf
# respeitam o locale e imprimiriam '200,5' em pt_BR).
export LC_ALL=C

# -----------------------------------------------------------------------------
# 0. Pré-checagem da versão do bash (nameref e arrays vazios com 'set -u' exigem 4.4+)
# -----------------------------------------------------------------------------
if [ -z "${BASH_VERSINFO:-}" ] || [ "${BASH_VERSINFO[0]}" -lt 4 ] || \
   { [ "${BASH_VERSINFO[0]}" -eq 4 ] && [ "${BASH_VERSINFO[1]}" -lt 4 ]; }; then
    echo "ERRO: este script precisa do bash 4.4 ou mais novo (usa nameref e" >&2
    echo "arrays vazios com 'set -u'). Versão detectada: ${BASH_VERSION:-desconhecida}." >&2
    exit 1
fi

# =============================================================================
# 1. Configuração
# =============================================================================
readonly NOME_MANIFESTO="pontos_coletados.csv"
readonly NOME_PLANO="plano_coleta.txt"
readonly NOME_REFERENCIA_EXTERNA="referencia_externa.csv"
readonly NOME_LOG="ler_adc.log"
readonly ESPACO_MINIMO_MB=50

# Padrões usados quando o operador não informa o valor.
readonly PADRAO_PONTOS=20
readonly PADRAO_FREQ_MIN=50            # Hz
readonly FRACAO_NYQUIST_PADRAO="0.8"   # freq. máxima padrão = 80% da Nyquist efetiva
readonly FRACAO_NYQUIST_AVISO="0.9"    # acima disto: aviso (aliasing/vazamento perto do limite)
readonly FRACAO_NYQUIST_MAXIMA="0.98"  # a partir disto: erro (o tom encosta na sua imagem espelhada)
readonly PADRAO_REPETICOES=1
readonly PADRAO_BLOCOS=1               # 1 bloco = SAMPLES_PER_BUFFER amostras (~10 s a 102,4 kHz)

# Canais capturados: 1 (só a sonda; padrão) ou 2 (sonda + referência). Definido por
# definir_canais() a partir de --canal-sonda / --canal-referencia (ou do plano salvo).
NUM_CANAIS_CAPTURA=1

# Limites de qualidade das checagens rápidas (ver analisar_rapido/avaliar_qualidade).
readonly SATURACAO_MAXIMA="0.0005"     # fração de amostras no fundo de escala (= gerar_perfil_sonda.py)
readonly PP_SEM_SINAL_PCT=0.2          # pico-a-pico abaixo disto (% da escala): praticamente sem sinal (o ruído do ADC é ~0,03%; o filtro de 15 kHz do ADS8688 derruba as frequências altas em 30-40 dB, então o limite tem de ser baixo)
readonly PP_FRACO_PCT=10               # abaixo disto: sinal fraco, SNR ruim
readonly FREQ_DESVIO_AVISO_PCT=5       # frequência medida difere da planejada: aviso
readonly FREQ_DESVIO_ERRO_PCT=10       # ... e erro (gerar_perfil_sonda.py só procura o tom em ±10%)
readonly LIMIAR_REFINO_DB="0.5"        # variação de ganho entre vizinhos que justifica um ponto extra
readonly RAZAO_FREQ_MIN_REFINO="1.04"  # não sugere pontos entre frequências a menos de 4% uma da outra
readonly AMOSTRAS_ANALISE_RAPIDA=262144   # amostras brutas (todos os canais) olhadas na checagem rápida
readonly AMOSTRAS_IGNORADAS_INICIO=4096   # descarta o começo da captura (transitório do arranque)
readonly SPB_PADRAO=1048576                # SAMPLES_PER_BUFFER (só para estimar tempo; o valor real vem do cabeçalho)

# Layout do cabeçalho .bin v2 a v6 (firmware/ler_adc.c; conferido por tests/test_contrato_firmware.py).
# A v3 acrescenta a faixa de entrada do ADC por canal (CAB_OFF_FAIXA_ADC); a v4, os contadores de integridade
# que a PRU mede durante a captura; a v5, a versão do firmware, a taxa medida pelo ARM e o nº de buffers; a v6, a
# grade de tempo publicada pela PRU (estes dois últimos, este script não lê).
# A cada versão o CRC (último campo) muda de lugar.
readonly CAB_TAMANHO=1024
readonly CAB_OFF_VERSAO=4
readonly CAB_OFF_FREQUENCIA=20
readonly CAB_OFF_NUM_CANAIS=28
readonly CAB_OFF_LISTA_CANAIS=32
readonly CAB_OFF_SPB=40
readonly CAB_OFF_BYTES_AMOSTRA=44
readonly CAB_OFF_BLOCOS=68
readonly CAB_OFF_TOTAL_AMOSTRAS=76
readonly CAB_OFF_GRANDEZA=404
readonly CAB_OFF_SONDA_ID=412
readonly CAB_TAM_SONDA_ID=32
readonly CAB_OFF_CRC_V2=668
readonly CAB_OFF_FAIXA_ADC=668   # v3: 8 x uint8, um código por canal (0 = ±10,24 V, 1 = ±5,12 V, 2 = ±2,56 V)
readonly CAB_OFF_CRC_V3=676
readonly CAB_OFF_ATRASADAS=676      # v4: uint32, amostras tomadas depois do instante previsto (taxa não alcançada)
readonly CAB_OFF_SOBRESCRITOS=680   # v4: uint32, buffers reescritos pela PRU antes de o ler_adc gravá-los
readonly CAB_OFF_PREAMBULO=684      # v4: uint32, quadros SPI com ruído no SDO (preâmbulo != 0)
readonly CAB_OFF_ATRASO_CS=688      # v4: 3 x uint32, esperas do CS no laço da PRU (setup, hold, alto; iterações de 10 ns)
readonly CAB_OFF_CRC_V4=700
readonly CAB_OFF_CRC_V5=744
readonly CAB_OFF_CRC_V6=760
readonly GRANDEZA_TENSAO=0
readonly GRANDEZA_CORRENTE=1

# Resolve o caminho do ler_adc relativo a ESTE script (não ao diretório corrente de
# quem chama). SH_LER_ADC permite apontar para outro binário (usado nos testes).
DIR_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly DIR_SCRIPT
LER_ADC="${SH_LER_ADC:-${DIR_SCRIPT}/ler_adc}"
readonly LER_ADC

# Parâmetros (preenchidos pela linha de comando, pelo plano salvo ou por perguntas).
PASTA_BASE="capturas"
GRANDEZA=""                # --grandeza: corrente (sonda de corrente) ou tensao (cadeia de um canal de tensão); vazio = corrente
CANAL_REFERENCIA=""        # vazio = captura de 1 canal (sem canal de referência no ADC)
CANAL_SONDA=""             # obrigatório (--canal-sonda; senão o script pergunta)
CANAL_REF_INFORMADO=0      # 1 se --canal-referencia veio da linha de comando
REF_EXTERNA=0              # 1 = a cada ponto, anotar a leitura do osciloscópio (só com 1 canal)
AMPLITUDE=""               # --amplitude: amplitude (com unidade e tipo, ex.: 500mVpp) da senoide injetada, a mesma em todos os pontos
AMPLITUDE_POR_PONTO=0      # 1 = perguntar a amplitude a cada frequência (--amplitude-por-ponto; --amplitude dá o valor inicial)
LISTA_CANAIS=""            # "<sonda>" ou "<ref>,<sonda>", para o ler_adc
FAIXA_ADC_SONDA=""         # --faixa-adc: fundo de escala TOTAL (V) do ADC no canal da sonda (20.48 | 10.24 | 5.12); vazio = padrão do ler_adc (±10,24 V)
FAIXA_ADC_REFERENCIA=""    # --faixa-adc-referencia: idem, para o canal de referência
ARGS_FAIXA_ADC=()          # montado por definir_canais: ("--faixa-adc" "canal:volts,...") ou vazio
ATRASO_CS=""               # --atraso-cs: "setup,hold,alto" (iterações de 10 ns) repassado ao ler_adc; vazio = padrão do firmware
ARGS_ATRASO_CS=()          # montado por definir_canais: ("--atraso-cs" "S,H,A") ou vazio
TAXA=""
PONTOS=""
SONDA_BRUTA=""
SONDA_ID=""
FREQ_MIN=""
FREQ_MAX=""
REPETICOES=""
BLOCOS=""
MODO=""
FREQS_ALVO=""           # --freqs: lista de frequências (modo refazer)
ASSUMIR_SIM=0
VERBOSO=0

# Estado da execução.
PASTA_SONDA=""
PLANO_FREQS=()          # frequências (Hz inteiros) do plano, ordenadas
ARQUIVO_EM_CAPTURA=""   # temporário em uso (limpo se o script for interrompido)
SESSAO_ACEITOS=0
SESSAO_PULADOS=0
LOG_LINHAS_ANTES=0      # linhas do ler_adc.log antes da captura atual (para mostrar só a saída dela)
REF_VALOR=""            # leitura do osciloscópio (V RMS no shunt ou na entrada da cadeia) do ponto em andamento
AMPLITUDE_PONTO=""      # amplitude da senoide injetada no ponto em andamento (vai para os metadados da captura)
SUBSTITUIR_EXISTENTES=0 # 1 no modo refazer: a captura aceita substitui (arquiva) a antiga

# Textos que dependem da grandeza (definir_grandeza). Os valores iniciais são os de corrente.
ROTULO_GRANDEZA="corrente"           # como a grandeza aparece nas mensagens e no cabeçalho
ONDE_REFERENCIA="no shunt"           # onde o osciloscópio/canal de referência mede o que foi injetado
EXEMPLOS_AMPLITUDE="500mVpp, 250mVpk, 2Arms"

# =============================================================================
# 2. Cores ANSI e funções de saída
# =============================================================================
# Sem cores se a saída não for um terminal (ex.: redirecionada para um arquivo de log).
if [ -t 2 ]; then
    COR_VERMELHO='\033[0;31m'; COR_VERDE='\033[0;32m'
    COR_AMARELO='\033[0;33m';  COR_AZUL='\033[0;34m'
    COR_NEGRITO='\033[1m';     COR_RESET='\033[0m'
else
    COR_VERMELHO=''; COR_VERDE=''; COR_AMARELO=''
    COR_AZUL='';     COR_NEGRITO=''; COR_RESET=''
fi

log_info()    { printf "%b\n" "${COR_AZUL}[INFO]${COR_RESET} $*" >&2; }
log_sucesso() { printf "%b\n" "${COR_VERDE}[OK]${COR_RESET} $*" >&2; }
log_aviso()   { printf "%b\n" "${COR_AMARELO}[ATENCAO]${COR_RESET} $*" >&2; }
log_erro()    { printf "%b\n" "${COR_VERMELHO}[ERRO]${COR_RESET} $*" >&2; }
saida()       { printf "%b\n" "$*" >&2; }

erro_fatal() { log_erro "$*"; exit 1; }

separador() {
    printf "%b\n" "${COR_AZUL}────────────────────────────────────────────────────────────${COR_RESET}" >&2
}

titulo_secao() {
    echo >&2
    printf "%b\n" "${COR_NEGRITO}${COR_AZUL}=== $* ===${COR_RESET}" >&2
}

# Ctrl+C (ou SIGTERM) em qualquer ponto: apaga o temporário da captura em andamento
# (se houver) e sai limpo. As capturas já aceitas continuam na pasta.
interrompido() {
    echo >&2
    if [ -n "$ARQUIVO_EM_CAPTURA" ]; then
        rm -f "$ARQUIVO_EM_CAPTURA" 2>/dev/null
        ARQUIVO_EM_CAPTURA=""
    fi
    log_aviso "Interrompido. A captura em andamento foi descartada; as já aceitas continuam em '${PASTA_SONDA:-${PASTA_BASE}}/'."
    [ -n "$PASTA_SONDA" ] && log_info "Para continuar depois:  sudo ./calibrar_sonda.sh --modo retomar --sonda ${SONDA_ID}"
    exit 130
}
trap interrompido INT TERM

# =============================================================================
# 3. Ajuda e linha de comando
# =============================================================================
uso() {
    cat <<EOF
Uso: sudo ./calibrar_sonda.sh [opções]

Coleta os pontos de calibração de uma "sonda" -- uma sonda de corrente ou a cadeia de
um canal de tensão (divisor/ponta + frontend + ADC): escolhe as frequências, pede para
você injetá-las na bancada, captura com o ler_adc (cabeçalho preenchido corretamente)
e confere cada .bin. Sem opções, pergunta o que precisa.

Principais:
  -t, --taxa HZ          Taxa de amostragem TOTAL do ADC (1-500000), ex.: 102400 ou
                         102.4k. Com 1 canal (padrão) ele é amostrado a essa taxa
                         (Nyquist = taxa/2); com 2 canais, cada um a taxa/2 (Nyquist = taxa/4).
  -c, --canal-sonda N    Canal do ADC (0-7) que está sendo calibrado (onde a saída da sonda,
                         ou da cadeia de tensão, está ligada). Obrigatório (se faltar, o
                         script pergunta).
  -g, --grandeza G       corrente (padrão): sonda de corrente; tensao: cadeia de um canal de
                         tensão. Vai para o cabeçalho de cada captura e muda as instruções
                         (onde medir a referência, exemplos, comando do perfil).
  -n, --pontos N         Quantidade de frequências do plano (padrão ${PADRAO_PONTOS}).
                         No modo refinar: quantos pontos EXTRAS coletar.
  -s, --sonda ID         Identificador da sonda (ex.: fluke_i30_sn0001 ou cadeia_tensao, até
                         31 caracteres: letras, números, '-' e '_').
      --faixa-adc V      Faixa de entrada do ADC no canal da SONDA, como fundo de escala total em
                         Volts: 20.48 (±10,24 V, padrão do ADC), 10.24 (±5,12 V) ou 5.12 (±2,56 V).
                         Escolha a menor faixa que comporta o pico do sinal da sonda: a resolução e o
                         ruído (em Volts) melhoram na mesma proporção. Vai para o cabeçalho de cada
                         captura e o gerar_perfil_sonda.py/adc_tool.py usam sozinhos.
      --faixa-adc-referencia V   O mesmo para o canal de referência (--canal-referencia).
      --atraso-cs S,H,A  Esperas do CS no laço da PRU, repassadas ao ler_adc (iterações de 10 ns:
                         setup,hold,alto; padrão do firmware 3,1,3, o mínimo do datasheet). Só
                         para repetir uma configuração do T7e do roteiro de laboratório; cada
                         captura é conferida (o cabeçalho tem de registrá-los).

Plano de frequências:
      --freq-min HZ      Menor frequência (padrão ${PADRAO_FREQ_MIN} Hz).
      --freq-max HZ      Maior frequência (padrão: 80% da Nyquist efetiva de cada canal; o
                         script recusa 98% ou mais e avisa acima de 90%).
  -r, --repeticoes N     Capturas por frequência (padrão ${PADRAO_REPETICOES}).
  -b, --blocos N         Blocos por captura (padrão ${PADRAO_BLOCOS}; 1 bloco ~ 10 s a 102,4 kHz).

Modo:
  -m, --modo MODO        novo (padrão) | retomar | refinar | adensar | refazer | resumo
                         (veja o cabeçalho deste script ou o docs/user-guide.md).
  -f, --freqs LISTA      Frequências a medir de novo (modo refazer), ex.: "200,1000".

Referência (como o perfil vai saber o que foi injetado na entrada; escolha UMA):
      --amplitude AMP        1 canal, senoide de amplitude CONHECIDA, SEMPRE com unidade e tipo
                             (pp = pico a pico, pk = pico, rms = eficaz): 500mVpp, 250mVpk,
                             176.8mVrms, 2Arms. Em V é a tensão no PINO DO ADC (antes do --ganho);
                             na cadeia de tensão, a de entrada x a razão do divisor (20 Vpp x
                             0,051662 = 1.0332Vpp). Vale para todos os pontos e é gravada nos
                             metadados de cada captura junto com a frequência ("ref: f=1000Hz
                             amp=500mVpp"): o gerar_perfil_sonda.py lê sozinho.
      --amplitude-por-ponto  Como --amplitude, mas pergunta a amplitude a cada frequência (ENTER
                             mantém a anterior; --amplitude dá o valor inicial).
      --ref-externa          1 canal + osciloscópio: a cada ponto o script pede a tensão RMS lida
                             sobre o shunt (corrente) ou na entrada da cadeia (tensão) e grava em
                             ${NOME_REFERENCIA_EXTERNA} (use depois: gerar_perfil_sonda.py --referencia-externa).
      --canal-referencia N   2 canais: um SEGUNDO canal do ADC mede a tensão sobre o shunt (ou a de
                             entrada da cadeia). Divide a taxa entre os canais (Nyquist efetiva =
                             taxa/4), e o filtro de ~15 kHz do ADC, igual nos dois canais, se cancela:
                             o perfil sai SEM ele.
      (nenhuma das quatro)   1 canal, amplitude constante SEM declarar: você a mantém igual em todas
                             as frequências e a informa depois (gerar_perfil_sonda.py --amplitude-referencia).

Saída:
      --pasta DIR            Pasta base das capturas (padrão: ./capturas).
  -y, --sim              Não pede confirmação do plano (você ainda ajusta o
                         gerador a cada ponto).
  -v, --verboso          Mostra a saída do ler_adc durante a captura.
  -h, --help             Esta ajuda.

Exemplos:
  sudo ./calibrar_sonda.sh --taxa 102400 --canal-sonda 1 --pontos 20 --sonda fluke_i30_sn0001 --ref-externa
  sudo ./calibrar_sonda.sh --taxa 100000 --canal-sonda 1 --pontos 24 --freq-max 45k --sonda cadeia_tensao --grandeza tensao --ref-externa
  sudo ./calibrar_sonda.sh --taxa 100000 --canal-sonda 1 --pontos 24 --freq-max 45k --sonda cadeia_tensao --grandeza tensao --amplitude 1.0332Vpp
  sudo ./calibrar_sonda.sh --taxa 102400 --canal-sonda 1 --pontos 20 --sonda minha_sonda --amplitude 500mVpp
  sudo ./calibrar_sonda.sh --taxa 100000 --canal-sonda 1 --pontos 20 --sonda minha_sonda --amplitude 5mVpp --faixa-adc 5.12
  sudo ./calibrar_sonda.sh --taxa 400000 --canal-sonda 1 --pontos 24 --freq-max 160k --sonda minha_sonda
  sudo ./calibrar_sonda.sh --taxa 204800 --canal-sonda 1 --canal-referencia 0 --pontos 20 --sonda minha_sonda
  sudo ./calibrar_sonda.sh --modo retomar --sonda fluke_i30_sn0001
  sudo ./calibrar_sonda.sh --modo refinar --pontos 4 --sonda fluke_i30_sn0001
  sudo ./calibrar_sonda.sh --modo refazer --freqs 200,1000 --sonda fluke_i30_sn0001
  sudo ./calibrar_sonda.sh --modo resumo --sonda fluke_i30_sn0001

Em cada ponto: [C]ontinuar aceita, [R]efazer mede de novo, [P]ular deixa o ponto
de fora (dá para pegá-lo depois com --modo retomar), [A]bortar encerra.

Variáveis de ambiente (avançado):
  SH_LER_ADC           Caminho de outro executável no lugar do ./ler_adc.
  SH_LER_ADC_TIMEOUT   Limite (s) para o ler_adc terminar uma captura (padrão: 3 x
                       a duração prevista + 60 s). Estourado, o ler_adc recebe Ctrl+C
                       (SIGINT, fecha o arquivo) e, 10 s depois, KILL.
EOF
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            -h|--help)         uso; exit 0 ;;
            -t|--taxa)         exigir_valor "$@"; TAXA="$2"; shift 2 ;;
            -n|--pontos)       exigir_valor "$@"; PONTOS="$2"; shift 2 ;;
            -s|--sonda)        exigir_valor "$@"; SONDA_BRUTA="$2"; shift 2 ;;
            --freq-min)        exigir_valor "$@"; FREQ_MIN="${2//,/.}"; shift 2 ;;
            --freq-max)        exigir_valor "$@"; FREQ_MAX="${2//,/.}"; shift 2 ;;
            -r|--repeticoes)   exigir_valor "$@"; REPETICOES="$2"; shift 2 ;;
            -b|--blocos)       exigir_valor "$@"; BLOCOS="$2"; shift 2 ;;
            -m|--modo)         exigir_valor "$@"; MODO="${2,,}"; shift 2 ;;
            -f|--freqs)        exigir_valor "$@"; FREQS_ALVO="$2"; shift 2 ;;
            -g|--grandeza)     exigir_valor "$@"; GRANDEZA="$2"; shift 2 ;;
            --canal-referencia) exigir_valor "$@"; CANAL_REFERENCIA="$2"; CANAL_REF_INFORMADO=1; shift 2 ;;
            -c|--canal-sonda)  exigir_valor "$@"; CANAL_SONDA="$2"; shift 2 ;;
            --ref-externa)     REF_EXTERNA=1; shift ;;
            --faixa-adc)       exigir_valor "$@"; FAIXA_ADC_SONDA="${2//,/.}"; shift 2 ;;
            --faixa-adc-referencia) exigir_valor "$@"; FAIXA_ADC_REFERENCIA="${2//,/.}"; shift 2 ;;
            --atraso-cs)       exigir_valor "$@"; ATRASO_CS="$2"; shift 2 ;;
            --amplitude)       exigir_valor "$@"; AMPLITUDE="$2"; shift 2 ;;
            --amplitude-por-ponto) AMPLITUDE_POR_PONTO=1; shift ;;
            --pasta)           exigir_valor "$@"; PASTA_BASE="$2"; shift 2 ;;
            -y|--sim)          ASSUMIR_SIM=1; shift ;;
            -v|--verboso)      VERBOSO=1; shift ;;
            *) log_erro "Opção desconhecida: '$1'."; echo "Use --help para ver as opções." >&2; exit 2 ;;
        esac
    done
}

exigir_valor() {
    if [ $# -lt 2 ]; then
        log_erro "A opção '$1' precisa de um valor."
        exit 2
    fi
}

# =============================================================================
# 4. Verificações de ambiente
# =============================================================================

# Falha cedo e com mensagem clara se faltar algum utilitário, em vez de um "comando
# não encontrado" no meio da coleta.
verificar_dependencias() {
    local faltando=() cmd
    for cmd in awk sed grep od gzip head tail tr sort wc tee date df find timeout mv mkdir rm dirname id; do
        command -v "$cmd" >/dev/null 2>&1 || faltando+=("$cmd")
    done
    if [ "${#faltando[@]}" -gt 0 ]; then
        erro_fatal "Utilitário(s) obrigatório(s) não encontrado(s): ${faltando[*]}. Instale o pacote correspondente (coreutils, gawk/mawk, gzip, sed)."
    fi
    if ! printf '1 2\n' | awk '{ x = log($2 / $1) / log(10); exit !(x > 0.3) }' 2>/dev/null; then
        erro_fatal "O 'awk' instalado não respondeu como esperado nas funções matemáticas (log/exp)."
    fi
    if [ ! -e "$LER_ADC" ]; then
        erro_fatal "Não encontrei o executável '${LER_ADC}'. Compile-o ('make' dentro de firmware/ ou ./setup.sh) e mantenha este script na mesma pasta do binário."
    fi
    if [ ! -x "$LER_ADC" ]; then
        erro_fatal "'${LER_ADC}' existe mas não é executável -- rode 'chmod +x ${LER_ADC}'."
    fi
}

verificar_root() {
    [ "${SH_PULAR_VERIFICACAO_ROOT:-0}" = "1" ] && return 0   # só para testes automáticos
    if [ "$(id -u)" -ne 0 ]; then
        erro_fatal "Este script precisa rodar como root (o '${LER_ADC##*/}' acessa /dev/mem) -- rode com 'sudo'."
    fi
}

# A BeagleBone não tem bateria de RTC: sem acerto de relógio, o timestamp gravado no
# cabeçalho de cada captura sai errado. Só avisa -- não impede a coleta.
verificar_relogio() {
    local ano
    ano="$(date +%Y)"
    if [ "$ano" -lt 2024 ]; then
        log_aviso "O relógio da BeagleBone marca ${ano}: o timestamp gravado no cabeçalho das capturas ficará errado. No computador, rode scripts/BeagleBone_Setup.sh hora para acertá-lo (ou continue se isso não importar)."
    fi
}

# Confere o espaço livre (MB) na partição onde 'pasta' vive. NÃO aborta sozinho:
# pausa e deixa o operador liberar espaço (e conferir de novo) ou abortar.
verificar_espaco_disco() {
    local pasta="$1" livre_mb resposta
    while true; do
        livre_mb="$(df -Pm "$pasta" 2>/dev/null | awk 'NR==2 {print $4}')"
        if [ -z "${livre_mb:-}" ]; then
            log_aviso "Não consegui checar o espaço livre em '${pasta}' (saída inesperada de 'df') -- prosseguindo sem essa checagem."
            return 0
        fi
        if [ "$livre_mb" -ge "$ESPACO_MINIMO_MB" ]; then
            return 0
        fi
        log_erro "Espaço em disco CRÍTICO: só ${livre_mb} MB livres (mínimo configurado: ${ESPACO_MINIMO_MB} MB)."
        if ! read -r -p "$(printf "%b" "${COR_AMARELO}Libere espaço (ex.: copie capturas antigas para o computador) e pressione ENTER para checar de novo, ou digite 'a' para abortar: ${COR_RESET}")" resposta; then
            erro_fatal "Entrada encerrada inesperadamente (EOF em stdin) -- abortando."
        fi
        if [ "${resposta,,}" = "a" ]; then
            erro_fatal "Abortado pelo operador por falta de espaço em disco."
        fi
    done
}

# =============================================================================
# 5. Entrada de dados do operador
# =============================================================================
readonly REGEX_INTEIRO_POSITIVO='^[0-9]+$'
readonly REGEX_FLOAT_POSITIVO='^[0-9]+(\.[0-9]+)?$'

# Lê um valor, repetindo o prompt até bater com 'regex' (ERE). Aceita vírgula ou ponto
# como separador decimal. Define a variável cujo NOME é passado em $1 (nameref).
# Uso: ler_valor VARIAVEL "Mensagem: " "$REGEX"
ler_valor() {
    local -n _destino="$1"
    local mensagem="$2" regex="$3" entrada
    while true; do
        if ! read -r -p "$(printf "%b" "${COR_AMARELO}${mensagem}${COR_RESET}")" entrada; then
            erro_fatal "Entrada encerrada inesperadamente (EOF em stdin) -- abortando."
        fi
        entrada="${entrada//,/.}"
        entrada="$(printf '%s' "$entrada" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        # [[ =~ ]] nativo (e não 'printf | grep'): grep opera por LINHA e uma entrada vazia
        # produz ZERO linhas, então '^$' (ENTER = usar o padrão) nunca casaria.
        if [[ "$entrada" =~ $regex ]]; then
            _destino="$entrada"
            return 0
        fi
        log_erro "Valor inválido: '${entrada}'. Tente de novo."
    done
}

# Se a variável (nome em $1) ainda está vazia, pergunta; ENTER aceita o padrão ($4).
# Uso: obter_parametro VARIAVEL "Pergunta" "$REGEX" [padrao]
obter_parametro() {
    local -n _alvo="$1"
    local pergunta="$2" regex="$3" padrao="${4:-}" resposta
    [ -n "$_alvo" ] && return 0
    if [ -n "$padrao" ]; then
        ler_valor resposta "${pergunta} [${padrao}]: " "(${regex})|^\$"
        _alvo="${resposta:-$padrao}"
    else
        ler_valor resposta "${pergunta}: " "$regex"
        _alvo="$resposta"
    fi
}

# Pergunta sim/não. $3 = padrão quando o operador só dá ENTER ("s", padrão, ou "n").
# Define $1 como "s" ou "n".
ler_confirmacao() {
    local -n _destino="$1"
    local mensagem="$2" padrao="${3:-s}" entrada dica="[S/n]"
    [ "$padrao" = "n" ] && dica="[s/N]"
    while true; do
        if ! read -r -p "$(printf "%b" "${COR_AMARELO}${mensagem} ${dica}: ${COR_RESET}")" entrada; then
            erro_fatal "Entrada encerrada inesperadamente (EOF em stdin) -- abortando."
        fi
        case "${entrada,,}" in
            "")          _destino="$padrao"; return 0 ;;
            s|sim)       _destino="s"; return 0 ;;
            n|nao|não)   _destino="n"; return 0 ;;
            *)           log_erro "Responda s ou n." ;;
        esac
    done
}

# Pergunta uma frequência (aceita 102400, 102.4k, 102,4 kHz...) até receber algo válido.
# Define $1 com o número em Hz. $3 = padrão opcional (ENTER aceita).
ler_hz() {
    local -n _destino="$1"
    local mensagem="$2" padrao="${3:-}" entrada convertido dica=""
    [ -n "$padrao" ] && dica=" [${padrao}]"
    while true; do
        if ! read -r -p "$(printf "%b" "${COR_AMARELO}${mensagem}${dica}: ${COR_RESET}")" entrada; then
            erro_fatal "Entrada encerrada inesperadamente (EOF em stdin) -- abortando."
        fi
        [ -z "$entrada" ] && [ -n "$padrao" ] && entrada="$padrao"
        if convertido="$(normalizar_hz "$entrada")"; then
            _destino="$convertido"
            return 0
        fi
        log_erro "Valor inválido: '${entrada}'. Use algo como 102400, 102.4k ou 5kHz."
    done
}

# Menu de N opções numeradas. Define $1 com o índice escolhido (1-based).
ler_escolha_menu() {
    local -n _destino="$1"
    local titulo="$2"
    shift 2
    local -a itens=("$@")
    local i entrada
    echo "$titulo" >&2
    for i in "${!itens[@]}"; do
        printf "  %d) %s\n" "$((i + 1))" "${itens[$i]}" >&2
    done
    while true; do
        if ! read -r -p "$(printf "%b" "${COR_AMARELO}Escolha [1-${#itens[@]}]: ${COR_RESET}")" entrada; then
            erro_fatal "Entrada encerrada inesperadamente (EOF em stdin) -- abortando."
        fi
        if [[ "$entrada" =~ ^[0-9]+$ ]] && [ "$entrada" -ge 1 ] && [ "$entrada" -le "${#itens[@]}" ]; then
            _destino="$entrada"
            return 0
        fi
        log_erro "Opção inválida."
    done
}

# Id de sonda seguro para nome de pasta/arquivo: minúsculas, só [a-z0-9_-].
sanitizar_id() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]' \
        | sed -E 's/[^a-z0-9_-]+/_/g; s/_+/_/g; s/^[_-]+//; s/[_-]+$//'
}

# =============================================================================
# 6. Matemática (awk)
# =============================================================================

# Converte "102400", "102.4k", "102,4 kHz", "5khz" em Hz (número, sem 'k'/'Hz'). Imprime o
# valor e retorna 0; retorna 1 (sem imprimir) se não for um número positivo.
normalizar_hz() {
    local t
    t="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
    t="${t//,/.}"
    t="${t%hz}"
    awk -v t="$t" 'BEGIN {
        mult = 1
        if (t ~ /k$/) { mult = 1000; sub(/k$/, "", t) }
        if (t !~ /^[0-9]+(\.[0-9]+)?$/) exit 1
        v = int(t * mult * 1000 + 0.5) / 1000
        if (v <= 0) exit 1
        if (v == int(v)) printf "%d", v; else printf "%.3f", v
    }'
}

# Converte uma leitura de tensão RMS ("0.1234", "123,4m", "123.4 mV", "0.12 V", "7.07 Vrms") em Volts.
# Imprime o valor e retorna 0; retorna 1 (sem imprimir) se não for um número positivo.
normalizar_tensao() {
    local t
    t="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
    t="${t//,/.}"
    awk -v t="$t" 'BEGIN {
        mult = 1
        sub(/rms$/, "", t)   # a leitura já é RMS: "7.07Vrms" e "7.07V" são o mesmo número
        if (t ~ /mv$/) { mult = 0.001; sub(/mv$/, "", t) }
        else if (t ~ /m$/) { mult = 0.001; sub(/m$/, "", t) }
        else if (t ~ /v$/) sub(/v$/, "", t)
        if (t !~ /^[0-9]+(\.[0-9]+)?$/ && t !~ /^\.[0-9]+$/) exit 1
        v = t * mult
        if (v <= 0) exit 1
        printf "%.6g", v
    }'
}

# Amplitude da senoide injetada, com unidade E tipo: "500mVpp", "250mVpk", "176.8mVrms", "2Arms". É a
# mesma gramática de scripts/supraharmonicos/referencia.py (analisar_amplitude), de propósito um pouco mais
# ESTRITA: número puro, unidade sem tipo ("500mV": pico a pico? pico? eficaz?) e tipo sem unidade são
# recusados, porque o fator 2 (ou 1,41) escondido viraria um erro de ganho silencioso no perfil.
# Prefixo n, u (ou µ), m ou k; unidade V ou A; tipo pp/pk/p/pico/rms/eficaz (e variantes: pk-pk, p-p...).
# Espaços e '_' são ignorados; vírgula decimal vale. O programa awk imprime, conforme -v saida=:
#   texto   -> a amplitude limpa (sem espaços, ponto decimal), que é o que vai para os metadados;
#   pico    -> o valor de PICO em V ou A;
#   unidade -> V ou A.
# Se a entrada for inválida imprime o MOTIVO e sai com 1. tests/test_calibrar_sonda.py confere que este
# programa e o Python aceitam e recusam as mesmas entradas.
readonly AWK_AMPLITUDE='
BEGIN {
    split("pk-pk pkpk pico-a-pico p-p p2p pp", PP, " "); for (i in PP) FATOR[PP[i]] = 0.5
    split("peak pico pk p", PK, " ");                    for (i in PK) FATOR[PK[i]] = 1
    split("rms eficaz", RM, " ");                        for (i in RM) FATOR[RM[i]] = sqrt(2)
    if (!match(t, /^([0-9]+\.?[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?/)) {
        print "não entendida (use número + unidade + tipo, ex.: 500mVpp)"; exit 1
    }
    num = substr(t, 1, RLENGTH) + 0; resto = substr(t, RLENGTH + 1)
    if (num <= 0) { print "o valor precisa ser um número positivo"; exit 1 }
    pref = ""; unid = ""
    if (resto ~ /^[numk]/) { pref = substr(resto, 1, 1); resto = substr(resto, 2) }
    if (resto ~ /^[VvAa]/) { unid = substr(resto, 1, 1); resto = substr(resto, 2) }
    tipo = tolower(resto)
    if (unid == "") { print "sem unidade: diga se é V ou A (ex.: 500mVpp, 2Arms)"; exit 1 }
    if (tipo == "") {
        print "sem tipo: diga se é pico a pico (pp), pico (pk) ou eficaz (rms), ex.: 500mVpp; sem isso o resultado erraria por um fator 2 ou 1,41"
        exit 1
    }
    if (!(tipo in FATOR)) { print "não entendida (use número + unidade + tipo, ex.: 500mVpp)"; exit 1 }
    mult = (pref == "n") ? 1e-9 : (pref == "u") ? 1e-6 : (pref == "m") ? 1e-3 : (pref == "k") ? 1e3 : 1
    if (saida == "pico") printf "%.10g", num * mult * FATOR[tipo]
    else if (saida == "unidade") printf "%s", toupper(unid)
    else printf "%s", t
}'

_analisar_amplitude() {   # TEXTO texto|pico
    local t
    t="$(printf '%s' "$1" | sed 's/µ/u/g; s/μ/u/g' | tr -d '[:space:]_')"
    t="${t//,/.}"
    awk -v t="$t" -v saida="$2" "$AWK_AMPLITUDE"
}

# Imprime a amplitude "limpa" (a que vai para os metadados) e retorna 0; se inválida, imprime o motivo e retorna 1.
normalizar_amplitude() { _analisar_amplitude "$1" texto; }

# Imprime o PICO (em V ou A) de uma amplitude já válida.
pico_da_amplitude() { _analisar_amplitude "$1" pico; }

# Uma amplitude (já válida) em A não tem sentido na cadeia de tensão. Retorna 0 e imprime o motivo se a
# amplitude NÃO combina com a grandeza; retorna 1 (sem imprimir) se está tudo certo.
amplitude_incompativel() {
    [ "$GRANDEZA" = "tensao" ] && [ "$(_analisar_amplitude "$1" unidade)" = "A" ] || return 1
    printf '%s' "na cadeia de tensão a amplitude é em V (a tensão no pino do ADC, antes do --ganho), não em A"
}

# Metadados da captura (campo "descrição" do cabeçalho, ler_adc -d): a frequência que o operador
# deve ter ajustado no gerador e, quando conhecida, a amplitude. scripts/supraharmonicos/referencia.py lê.
descricao_da_captura() {   # FREQ_HZ
    local d="ref: f=${1}Hz"
    [ -n "$AMPLITUDE_PONTO" ] && d+=" amp=${AMPLITUDE_PONTO}"
    printf '%s' "$d"
}

# Valida --amplitude (na linha de comando) e a troca pelo texto limpo; erro claro se for inválida.
normalizar_parametro_amplitude() {
    [ -n "$AMPLITUDE" ] || return 0
    local bruto="$AMPLITUDE" limpo
    if ! limpo="$(normalizar_amplitude "$bruto")"; then
        erro_fatal "Valor inválido para --amplitude: '${bruto}' -- ${limpo}. Exemplos: 500mVpp, 250mVpk, 176.8mVrms, 2Arms."
    fi
    AMPLITUDE="$limpo"
}

# Nyquist EFETIVA por canal: a taxa total é dividida entre os NUM_CANAIS_CAPTURA canais.
nyquist_efetiva() {
    awk -v t="$1" -v n="$NUM_CANAIS_CAPTURA" 'BEGIN { printf "%.1f", t / (2 * n) }'
}

# Fração da Nyquist efetiva ($2, ex.: 0.98) em Hz, para a taxa $1.
fracao_da_nyquist() {
    awk -v t="$1" -v n="$NUM_CANAIS_CAPTURA" -v fr="$2" 'BEGIN { printf "%.1f", fr * t / (2 * n) }'
}

# Retorna 0 (verdadeiro) se $1 < $2, comparando como números.
num_menor() { awk -v a="$1" -v b="$2" 'BEGIN { exit !(a < b) }'; }

# Duração de uma captura, em segundos: blocos x SAMPLES_PER_BUFFER / taxa total.
duracao_captura() {
    awk -v b="$BLOCOS" -v spb="$SPB_PADRAO" -v t="$TAXA" 'BEGIN { printf "%.1f", b * spb / t }'
}

# Frequência máxima padrão: 80% da Nyquist efetiva, arredondada PARA BAIXO a 3 algarismos.
freq_max_padrao() {
    awk -v t="$1" -v n="$NUM_CANAIS_CAPTURA" -v fr="$FRACAO_NYQUIST_PADRAO" 'BEGIN {
        f = fr * t / (2 * n)
        if (f >= 1000) { m = 10 ^ (int(log(f) / log(10) + 1e-9) - 2); f = int(f / m) * m }
        else f = int(f)
        printf "%d", f
    }'
}

# N frequências log-espaçadas entre fmin e fmax (pontas incluídas), arredondadas a
# frequências "amigáveis" para o gerador (inteiros; acima de 1 kHz, 3 algarismos
# significativos). Sem repetições, em ordem crescente, uma por linha. Pode devolver
# menos de N linhas se o arredondamento juntar pontos vizinhos.
calcular_pontos_log() {
    awk -v fmin="$1" -v fmax="$2" -v n="$3" '
    function amigavel(f,   m) {
        if (f >= 1000) { m = 10 ^ (int(log(f) / log(10) + 1e-9) - 2); return sprintf("%d", int(f / m + 0.5) * m) }
        return sprintf("%d", int(f + 0.5))
    }
    BEGIN {
        lmin = log(fmin); lmax = log(fmax)
        for (i = 0; i < n; i++) print amigavel(exp(lmin + (lmax - lmin) * i / (n - 1)))
    }' | sort -n -u
}

# Para cada par de frequências ADJACENTES (uma por linha em stdin, crescentes), a média
# GEOMÉTRICA -- o ponto equidistante em escala log -- arredondada como acima. Só emite
# valores estritamente entre as duas pontas.
pontos_medios_geometricos() {
    awk '
    function amigavel(f,   m) {
        if (f >= 1000) { m = 10 ^ (int(log(f) / log(10) + 1e-9) - 2); return int(f / m + 0.5) * m }
        return int(f + 0.5)
    }
    NR > 1 { novo = amigavel(sqrt(ant * $1)); if (novo > ant && novo < $1) print novo }
    { ant = $1 }'
}

# Junta listas de frequências (argumentos), ordenando e removendo duplicatas.
unir_frequencias() { printf '%s\n' "$@" | sort -n -u; }

# =============================================================================
# 7. Plano, manifesto e arquivos já capturados
# =============================================================================
readonly CABECALHO_MANIFESTO="frequencia_hz,repeticao,arquivo,timestamp,status,freq_medida_hz,pp_ref_pct,pp_sonda_pct,razao_rms,ref_externa_v_rms,amplitude_ref"

salvar_plano() {
    local arquivo="${PASTA_SONDA}/${NOME_PLANO}"
    {
        echo "# Plano de coleta do calibrar_sonda.sh (editado automaticamente; pode ser lido, não precisa ser editado)"
        echo "grandeza=${GRANDEZA}"
        echo "taxa=${TAXA}"
        echo "canal_sonda=${CANAL_SONDA}"
        echo "canal_referencia=${CANAL_REFERENCIA}"
        echo "ref_externa=${REF_EXTERNA}"
        echo "faixa_adc_sonda=${FAIXA_ADC_SONDA}"
        echo "faixa_adc_referencia=${FAIXA_ADC_REFERENCIA}"
        echo "atraso_cs=${ATRASO_CS}"
        echo "amplitude=${AMPLITUDE}"
        echo "amplitude_por_ponto=${AMPLITUDE_POR_PONTO}"
        echo "repeticoes=${REPETICOES}"
        echo "blocos=${BLOCOS}"
        echo "frequencias=${PLANO_FREQS[*]}"
    } > "$arquivo"
}

# Valor de uma chave 'chave=valor' do plano (vazio se não existir).
valor_do_plano() {
    local arquivo="${PASTA_SONDA}/${NOME_PLANO}"
    [ -f "$arquivo" ] || return 0
    sed -n "s/^$1=//p" "$arquivo" | head -n 1
}

# Preenche os parâmetros AINDA vazios com os do plano salvo (a linha de comando vence).
carregar_plano() {
    [ -f "${PASTA_SONDA}/${NOME_PLANO}" ] || return 1
    local v usar
    v="$(valor_do_plano taxa)"
    if [ -z "$TAXA" ]; then
        TAXA="$v"
    elif [ -n "$v" ] && [ "$TAXA" != "$v" ]; then
        log_aviso "A coleta desta sonda foi planejada com ${v} Hz, mas você pediu ${TAXA} Hz. Misturar taxas no mesmo perfil costuma ser engano."
        [ "$ASSUMIR_SIM" -eq 1 ] && erro_fatal "Taxa diferente da do plano (${v} Hz). Remova --taxa para usar a do plano."
        ler_confirmacao usar "Usar ${TAXA} Hz mesmo assim?" n
        [ "$usar" = "n" ] && { log_aviso "Cancelado."; exit 0; }
    fi
    # Grandeza: um plano sem a chave é de uma versão do script que só calibrava corrente. A linha de comando
    # vence (só avisa: nos modos de 1 canal o gerar_perfil_sonda.py não usa a grandeza do cabeçalho).
    v="$(valor_do_plano grandeza)"; v="${v:-corrente}"
    if [ -z "$GRANDEZA" ]; then
        GRANDEZA="$v"
    elif [ "$GRANDEZA" != "$v" ]; then
        log_aviso "A coleta desta sonda foi planejada como '${v}', mas você pediu --grandeza ${GRANDEZA}: as capturas novas saem marcadas como '${GRANDEZA}' e o plano passa a dizer isso."
    fi
    v="$(valor_do_plano repeticoes)";       [ -z "$REPETICOES" ] && REPETICOES="$v"
    # Faixa de entrada do ADC: a linha de comando vence; sem ela, herda a do plano (cada captura leva a
    # sua própria faixa no cabeçalho, então mudar no meio não mistura nada).
    v="$(valor_do_plano faixa_adc_sonda)";  [ -z "$FAIXA_ADC_SONDA" ] && FAIXA_ADC_SONDA="$v"
    v="$(valor_do_plano faixa_adc_referencia)"; [ -z "$FAIXA_ADC_REFERENCIA" ] && FAIXA_ADC_REFERENCIA="$v"
    v="$(valor_do_plano atraso_cs)";        [ -z "$ATRASO_CS" ] && ATRASO_CS="$v"
    v="$(valor_do_plano blocos)";           [ -z "$BLOCOS" ] && BLOCOS="$v"
    # Canais: sem --canal-sonda na linha de comando, herda tudo do plano; com ele, a linha de
    # comando vence e qualquer diferença em relação ao plano pede confirmação (como a taxa).
    local plano_sonda plano_ref plano_ext plano_amp plano_amp_ponto
    plano_sonda="$(valor_do_plano canal_sonda)"
    plano_ref="$(valor_do_plano canal_referencia)"
    plano_ext="$(valor_do_plano ref_externa)"
    if [ -n "$plano_sonda" ]; then
        if [ -z "$CANAL_SONDA" ]; then
            CANAL_SONDA="$plano_sonda"
            [ "$CANAL_REF_INFORMADO" -eq 0 ] && CANAL_REFERENCIA="$plano_ref"
        elif [ "$CANAL_SONDA" != "$plano_sonda" ] || [ "$CANAL_REFERENCIA" != "$plano_ref" ]; then
            log_aviso "A coleta desta sonda foi planejada com sonda no canal ${plano_sonda}${plano_ref:+ e referência no canal ${plano_ref}}, mas você pediu sonda no canal ${CANAL_SONDA}${CANAL_REFERENCIA:+ e referência no canal ${CANAL_REFERENCIA}}. Misturar configurações no mesmo perfil costuma ser engano."
            [ "$ASSUMIR_SIM" -eq 1 ] && erro_fatal "Canais diferentes dos do plano. Remova --canal-sonda/--canal-referencia para usar os do plano."
            ler_confirmacao usar "Usar os canais pedidos mesmo assim?" n
            [ "$usar" = "n" ] && { log_aviso "Cancelado."; exit 0; }
        fi
        if [ "$REF_EXTERNA" -eq 0 ] && [ "$plano_ext" = "1" ] && [ -z "$CANAL_REFERENCIA" ]; then
            if [ -n "$AMPLITUDE" ] || [ "$AMPLITUDE_POR_PONTO" -eq 1 ]; then
                erro_fatal "Esta coleta foi planejada com --ref-externa (leitura do osciloscópio): não dá para trocar por --amplitude no meio dela, porque o gerar_perfil_sonda.py usa uma referência só. Tire --amplitude/--amplitude-por-ponto, ou comece outra coleta (outro --sonda)."
            fi
            REF_EXTERNA=1
        fi
    fi
    # Amplitude da senoide: a linha de comando vence; sem nada dito (e sem outra fonte de referência),
    # herda a do plano. Cada captura carrega a sua amplitude nos metadados, então mudar no meio não mistura nada.
    plano_amp="$(valor_do_plano amplitude)"
    plano_amp_ponto="$(valor_do_plano amplitude_por_ponto)"
    if [ -z "$AMPLITUDE" ] && [ "$AMPLITUDE_POR_PONTO" -eq 0 ] && [ "$REF_EXTERNA" -eq 0 ] && [ -z "$CANAL_REFERENCIA" ]; then
        AMPLITUDE="$plano_amp"
        [ "$plano_amp_ponto" = "1" ] && AMPLITUDE_POR_PONTO=1
    fi
    v="$(valor_do_plano frequencias)"
    PLANO_FREQS=()
    if [ -n "$v" ]; then
        local f
        for f in $v; do PLANO_FREQS+=("$f"); done
    fi
    return 0
}

inicializar_manifesto() {
    local caminho="${PASTA_SONDA}/${NOME_MANIFESTO}"
    if [ ! -f "$caminho" ]; then
        echo "$CABECALHO_MANIFESTO" > "$caminho"
    elif [ "$(head -n 1 "$caminho")" = "${CABECALHO_MANIFESTO%,amplitude_ref}" ]; then
        # manifesto de uma versão anterior (sem a coluna amplitude_ref): ganha a coluna, as linhas antigas ficam com ela vazia
        sed -i '1s/$/,amplitude_ref/' "$caminho"
    fi
}

# registrar_manifesto FREQ REP ARQUIVO STATUS FREQ_MEDIDA PP_REF PP_SONDA RAZAO REF_EXTERNA AMPLITUDE
registrar_manifesto() {
    local ts
    ts="$(date '+%Y-%m-%dT%H:%M:%S%z')"
    printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' "$1" "$2" "$3" "$ts" "$4" "${5:-}" "${6:-}" "${7:-}" "${8:-}" "${9:-}" "${10:-}" \
        >> "${PASTA_SONDA}/${NOME_MANIFESTO}"
}

# Coluna da leitura do osciloscópio em referencia_externa.csv: a do arquivo, se ele já existe (uma pasta
# começada por uma versão anterior continua coerente), senão a da grandeza -- v_shunt_rms_V (corrente: a
# tensão no shunt, que o gerar_perfil_sonda.py divide por --resistencia-shunt) ou tensao_rms_V (tensão: a
# própria tensão de entrada da cadeia, usada como está).
coluna_referencia_externa() {
    local csv="${PASTA_SONDA}/${NOME_REFERENCIA_EXTERNA}" coluna=""
    [ -f "$csv" ] && coluna="$(awk -F, 'NR == 1 { sub(/\r$/, ""); print $2; exit }' "$csv")"
    if [ -z "$coluna" ]; then
        if [ "$GRANDEZA" = "tensao" ]; then coluna="tensao_rms_V"; else coluna="v_shunt_rms_V"; fi
    fi
    printf '%s' "$coluna"
}

# Anota a leitura do osciloscópio de uma captura aceita em referencia_externa.csv (o arquivo que o
# gerar_perfil_sonda.py --referencia-externa lê; vale a ÚLTIMA linha de cada arquivo). Sem leitura
# ($2 vazio), só acrescenta uma linha em branco se o arquivo JÁ tinha leitura (ponto refeito): assim
# uma leitura antiga nunca é herdada por uma captura nova de mesmo nome.
registrar_referencia_externa() {
    local arquivo="$1" valor="${2:-}" csv="${PASTA_SONDA}/${NOME_REFERENCIA_EXTERNA}"
    if [ -z "$valor" ]; then
        if [ -f "$csv" ] && awk -F, -v a="$arquivo" '$1 == a { achou = 1 } END { exit !achou }' "$csv"; then
            printf '%s,\n' "$arquivo" >> "$csv"
        fi
        return 0
    fi
    [ -f "$csv" ] || echo "arquivo,$(coluna_referencia_externa)" > "$csv"
    printf '%s,%s\n' "$arquivo" "$valor" >> "$csv"
}

# Capturas aceitas (em disco) SEM leitura externa válida, uma por linha.
capturas_sem_leitura_externa() {
    local csv="${PASTA_SONDA}/${NOME_REFERENCIA_EXTERNA}" f
    [ -d "$PASTA_SONDA" ] || return 0
    while read -r f; do
        [ -z "$f" ] && continue
        if [ ! -f "$csv" ] || ! awk -F, -v a="$f" '$1 == a { v = $2 } END { exit !(v != "") }' "$csv"; then
            echo "$f"
        fi
    done < <(find "$PASTA_SONDA" -maxdepth 1 -type f -name 'calibracao_*Hz_rep*.bin' -printf '%f\n' 2>/dev/null | sort)
}

# Capturas JÁ presentes em disco (a fonte de verdade, a mesma que o gerar_perfil_sonda.py
# usa): "FREQ REP", únicas e ordenadas, a partir de 'calibracao_<FREQ>Hz_rep<N>[_vM].bin'.
capturas_em_disco() {
    [ -d "$PASTA_SONDA" ] || return 0
    find "$PASTA_SONDA" -maxdepth 1 -type f -name 'calibracao_*Hz_rep*.bin' -printf '%f\n' 2>/dev/null \
        | sed -nE 's/^calibracao_([0-9]+)Hz_rep([0-9]+)(_v[0-9]+)?\.bin$/\1 \2/p' \
        | sort -n -u
}

frequencias_em_disco() { capturas_em_disco | awk '{ print $1 }' | sort -n -u; }

# Se 'caminho' já existe, devolve uma variante '_v2', '_v3'... em vez de sobrescrever.
caminho_disponivel() {
    local caminho="$1" base="${1%.bin}" versao=2 candidato
    [ -e "$caminho" ] || { printf '%s' "$caminho"; return 0; }
    while true; do
        candidato="${base}_v${versao}.bin"
        [ -e "$candidato" ] || { printf '%s' "$candidato"; return 0; }
        versao=$((versao + 1))
    done
}

# =============================================================================
# 8. Conferência do .bin (cabeçalho + checagens rápidas de sinal)
# =============================================================================
QC_ERROS=()
QC_AVISOS=()
QC_TAGS=""            # etiquetas dos problemas, para o manifesto (ex.: saturacao_fraco)
QC_FREQ_MEDIDA=""
QC_PP_REF=""
QC_PP_SONDA=""
QC_RAZAO=""

ler_u32() { od -An -tu4 -j "$2" -N 4 "$1" | tr -d ' \n'; }
ler_u64() { od -An -tu8 -j "$2" -N 8 "$1" | tr -d ' \n'; }
ler_u8()  { od -An -tu1 -j "$2" -N 1 "$1" | tr -d ' \n'; }
# Texto (ASCII/UTF-8) de $3 bytes a partir do offset $2, sem os '\0' de preenchimento.
ler_texto() { head -c "$(($2 + $3))" "$1" | tail -c "$3" | tr -d '\0'; }

# Fundo de escala TOTAL (V) -> código de faixa do ADS8688 que o ler_adc grava no cabeçalho
# (0 = ±10,24 V, 1 = ±5,12 V, 2 = ±2,56 V). Falha (sem imprimir nada) se o valor não for uma das três.
codigo_faixa_adc() {
    awk -v v="$1" 'BEGIN {
        if (v !~ /^[0-9]+(\.[0-9]+)?$/) exit 1
        d = v - 20.48; if (d < 0) d = -d; if (d < 0.005) { print 0; exit 0 }
        d = v - 10.24; if (d < 0) d = -d; if (d < 0.005) { print 1; exit 0 }
        d = v - 5.12;  if (d < 0) d = -d; if (d < 0.005) { print 2; exit 0 }
        exit 1
    }'
}

# CRC-32 do cabeçalho (v2 ou v3, conforme $2 = offset do campo do CRC): o do zlib/gzip sobre os
# 1024 bytes com o campo do CRC zerado (o trailer do gzip guarda exatamente esse CRC-32, em little-endian).
crc_cabecalho_calculado() {
    local off="${2:-$CAB_OFF_CRC_V2}"
    {
        head -c "$off" "$1"
        printf '\0\0\0\0'
        head -c "$CAB_TAMANHO" "$1" | tail -c +"$((off + 5))"
    } | gzip -1 -c | tail -c 8 | head -c 4 | od -An -tu4 | tr -d ' \n'
}

qc_erro()  { QC_ERROS+=("$1");  QC_TAGS="${QC_TAGS:+${QC_TAGS}_}$2"; }
qc_aviso() { QC_AVISOS+=("$1"); QC_TAGS="${QC_TAGS:+${QC_TAGS}_}$2"; }

# Confere que o cabeçalho gravado pelo ler_adc é o que PEDIMOS (taxa, canais, grandeza
# e sonda) e que a captura está completa.
validar_cabecalho() {
    local arq="$1" tamanho versao magic crc_gravado crc_calculado
    tamanho="$(wc -c < "$arq" | tr -d ' ')"
    if [ "$tamanho" -lt "$CAB_TAMANHO" ]; then
        qc_erro "o arquivo tem só ${tamanho} bytes (menos que o cabeçalho de ${CAB_TAMANHO})" arquivo_curto
        return
    fi
    magic="$(head -c 4 "$arq")"
    if [ "$magic" != "SHAN" ]; then
        qc_erro "o arquivo não começa com o cabeçalho 'SHAN' (ler_adc antigo, sem cabeçalho?)" sem_cabecalho
        return
    fi
    versao="$(ler_u32 "$arq" "$CAB_OFF_VERSAO")"
    if [ "$versao" -lt 2 ]; then
        qc_erro "cabeçalho versão ${versao}: não registra grandeza/sonda por canal. Recompile o firmware (make em firmware/)" cabecalho_v1
        return
    fi
    if [ "$versao" -gt 6 ]; then
        qc_aviso "cabeçalho versão ${versao}, mais nova que a conhecida por este script: não conferi grandeza/sonda" cabecalho_desconhecido
        return
    fi

    local off_crc="$CAB_OFF_CRC_V2"
    [ "$versao" -eq 3 ] && off_crc="$CAB_OFF_CRC_V3"
    [ "$versao" -eq 4 ] && off_crc="$CAB_OFF_CRC_V4"
    [ "$versao" -eq 5 ] && off_crc="$CAB_OFF_CRC_V5"
    [ "$versao" -eq 6 ] && off_crc="$CAB_OFF_CRC_V6"
    crc_gravado="$(ler_u32 "$arq" "$off_crc")"
    crc_calculado="$(crc_cabecalho_calculado "$arq" "$off_crc")"
    if [ "$crc_gravado" != "$crc_calculado" ]; then
        qc_erro "o CRC-32 do cabeçalho não confere (arquivo corrompido ou truncado)" crc
    fi

    # Integridade medida pela PRU (só v4). Amostras perdidas ou fora do instante distorcem o ganho do ponto:
    # erro (a captura é refeita). Ruído no SDO só avisa enquanto o preâmbulo não for validado em bancada.
    if [ "$versao" -ge 4 ]; then
        local sobrescritos atrasadas preambulo
        sobrescritos="$(ler_u32 "$arq" "$CAB_OFF_SOBRESCRITOS")"
        atrasadas="$(ler_u32 "$arq" "$CAB_OFF_ATRASADAS")"
        preambulo="$(ler_u32 "$arq" "$CAB_OFF_PREAMBULO")"
        [ "$sobrescritos" -gt 0 ] && qc_erro "${sobrescritos} buffer(s) sobrescrito(s) antes de gravados: há amostras perdidas (sistema sobrecarregado ou cartão SD lento?)" buffer_sobrescrito
        [ "$atrasadas" -gt 0 ] && qc_erro "${atrasadas} amostra(s) fora do instante previsto: a PRU não acompanhou a taxa ${TAXA} Hz" amostras_atrasadas
        [ "$preambulo" -gt 0 ] && qc_aviso "${preambulo} quadro(s) SPI com ruído na linha SDO: confira a ligação ADC <-> BeagleBone" preambulo
        if [ -n "$ATRASO_CS" ]; then
            local gravado
            gravado="$(ler_u32 "$arq" "$CAB_OFF_ATRASO_CS"),$(ler_u32 "$arq" "$((CAB_OFF_ATRASO_CS + 4))"),$(ler_u32 "$arq" "$((CAB_OFF_ATRASO_CS + 8))")"
            [ "$gravado" = "$ATRASO_CS" ] || qc_erro "esperas do CS: o cabeçalho registra ${gravado}, mas o pedido foi ${ATRASO_CS}" atraso_cs
        fi
    elif [ -n "$ATRASO_CS" ]; then
        qc_erro "cabeçalho versão ${versao}: não registra as esperas do CS, mas --atraso-cs foi pedido. Recompile o firmware (./setup.sh)" atraso_cs_v3
    fi

    local freq num_canais pos_ref pos_sonda c0 c1 esperado0 esperado1 achado esperado
    freq="$(ler_u32 "$arq" "$CAB_OFF_FREQUENCIA")"
    if [ "$freq" != "$TAXA" ]; then
        qc_erro "o cabeçalho registra ${freq} Hz de taxa, mas o pedido foi ${TAXA} Hz" taxa
    fi

    # A lista de canais do cabeçalho vem em ordem CRESCENTE (a do ADS8688), não na ordem pedida.
    num_canais="$(ler_u32 "$arq" "$CAB_OFF_NUM_CANAIS")"
    c0="$(ler_u8 "$arq" "$CAB_OFF_LISTA_CANAIS")"
    if [ -z "$CANAL_REFERENCIA" ]; then
        esperado0="$CANAL_SONDA"; pos_ref=-1; pos_sonda=0
        achado="${c0}"; esperado="${esperado0}"
        c1=""; esperado1=""
    else
        c1="$(ler_u8 "$arq" "$((CAB_OFF_LISTA_CANAIS + 1))")"
        if [ "$CANAL_REFERENCIA" -lt "$CANAL_SONDA" ]; then
            esperado0="$CANAL_REFERENCIA"; esperado1="$CANAL_SONDA"; pos_ref=0; pos_sonda=1
        else
            esperado0="$CANAL_SONDA"; esperado1="$CANAL_REFERENCIA"; pos_ref=1; pos_sonda=0
        fi
        achado="${c0},${c1}"; esperado="${esperado0},${esperado1}"
    fi
    if [ "$num_canais" != "$NUM_CANAIS_CAPTURA" ] || [ "$c0" != "$esperado0" ] || [ "$c1" != "$esperado1" ]; then
        qc_erro "canais no cabeçalho: ${num_canais} (${achado}); esperado ${NUM_CANAIS_CAPTURA} (${esperado})" canais
        return
    fi

    local g_sonda g_ref id_sonda id_ref g_esperada="$GRANDEZA_CORRENTE"
    [ "$GRANDEZA" = "tensao" ] && g_esperada="$GRANDEZA_TENSAO"
    g_sonda="$(ler_u8 "$arq" "$((CAB_OFF_GRANDEZA + pos_sonda))")"
    if [ "$g_sonda" != "$g_esperada" ]; then
        qc_erro "o canal ${CANAL_SONDA} (sonda) não está marcado como '${ROTULO_GRANDEZA}' no cabeçalho (código ${g_sonda})" grandeza
    fi
    id_sonda="$(ler_texto "$arq" "$((CAB_OFF_SONDA_ID + pos_sonda * CAB_TAM_SONDA_ID))" "$CAB_TAM_SONDA_ID")"
    if [ "$id_sonda" != "$SONDA_ID" ]; then
        qc_erro "id da sonda no cabeçalho é '${id_sonda}'; esperado '${SONDA_ID}'" sonda_id
    fi
    if [ "$pos_ref" -ge 0 ]; then
        g_ref="$(ler_u8 "$arq" "$((CAB_OFF_GRANDEZA + pos_ref))")"
        id_ref="$(ler_texto "$arq" "$((CAB_OFF_SONDA_ID + pos_ref * CAB_TAM_SONDA_ID))" "$CAB_TAM_SONDA_ID")"
        if [ "$g_ref" != "$GRANDEZA_TENSAO" ]; then
            qc_aviso "o canal ${CANAL_REFERENCIA} (referência) não está marcado como 'tensão' no cabeçalho (código ${g_ref})" grandeza_ref
        fi
        if [ -n "$id_ref" ]; then
            qc_aviso "o canal de referência tem uma sonda registrada ('${id_ref}'), o que não era esperado" sonda_ref
        fi
    fi

    # Faixa de entrada do ADC (só v3): o que foi PEDIDO tem de ser o que o ler_adc gravou. Sem pedido,
    # o ler_adc usa o padrão do ADC (código 0) e não há o que conferir.
    if [ -n "$FAIXA_ADC_SONDA" ] || [ -n "$FAIXA_ADC_REFERENCIA" ]; then
        if [ "$versao" -lt 3 ]; then
            qc_erro "cabeçalho versão ${versao}: não registra a faixa de entrada do ADC, mas --faixa-adc foi pedida. Recompile o firmware (make em firmware/)" faixa_adc_v2
        else
            local cod_pedido cod_gravado
            if [ -n "$FAIXA_ADC_SONDA" ]; then
                cod_pedido="$(codigo_faixa_adc "$FAIXA_ADC_SONDA")"
                cod_gravado="$(ler_u8 "$arq" "$((CAB_OFF_FAIXA_ADC + pos_sonda))")"
                [ "$cod_gravado" = "$cod_pedido" ] || qc_erro "faixa do ADC no canal da sonda: o cabeçalho registra o código ${cod_gravado}; o pedido (${FAIXA_ADC_SONDA} V) é o código ${cod_pedido}" faixa_adc
            fi
            if [ -n "$FAIXA_ADC_REFERENCIA" ] && [ "$pos_ref" -ge 0 ]; then
                cod_pedido="$(codigo_faixa_adc "$FAIXA_ADC_REFERENCIA")"
                cod_gravado="$(ler_u8 "$arq" "$((CAB_OFF_FAIXA_ADC + pos_ref))")"
                [ "$cod_gravado" = "$cod_pedido" ] || qc_erro "faixa do ADC no canal de referência: o cabeçalho registra o código ${cod_gravado}; o pedido (${FAIXA_ADC_REFERENCIA} V) é o código ${cod_pedido}" faixa_adc_ref
            fi
        fi
    fi

    local spb bytes_amostra blocos total esperado_total esperado_tamanho
    spb="$(ler_u32 "$arq" "$CAB_OFF_SPB")"
    bytes_amostra="$(ler_u32 "$arq" "$CAB_OFF_BYTES_AMOSTRA")"
    blocos="$(ler_u64 "$arq" "$CAB_OFF_BLOCOS")"
    total="$(ler_u64 "$arq" "$CAB_OFF_TOTAL_AMOSTRAS")"
    esperado_total=$((BLOCOS * spb))
    esperado_tamanho=$((CAB_TAMANHO + esperado_total * bytes_amostra))
    if [ "$tamanho" -ne "$esperado_tamanho" ]; then
        qc_erro "tamanho do arquivo ${tamanho} B; esperado ${esperado_tamanho} B para ${BLOCOS} bloco(s) -- captura incompleta (disco cheio?)" tamanho
    elif [ "$blocos" != "$BLOCOS" ] || [ "$total" != "$esperado_total" ]; then
        if [ "$blocos" = "0" ]; then
            qc_aviso "o cabeçalho final não foi atualizado pelo ler_adc (blocos_gravados=0), mas o tamanho do arquivo está correto: as amostras estão íntegras" cabecalho_final
        else
            qc_erro "o cabeçalho registra ${blocos} bloco(s) / ${total} amostras; esperado ${BLOCOS} / ${esperado_total}" blocos
        fi
    fi
}

# Olha as primeiras amostras e imprime, numa linha:
#   fmed_ref fmed_sonda pp_ref_pct pp_sonda_pct rms_ref rms_sonda sat_ref sat_sonda razao_rms
# (fmed = frequência medida por cruzamentos de zero com histerese; pp = pico-a-pico em %
# da escala de 16 bits; sat = fração de amostras no fundo de escala; razao = rms_sonda /
# rms_ref com 2 canais, ou o próprio rms_sonda com 1). Sem canal de referência ($2 = -1), os
# campos da referência saem 0. Não é a medição de verdade (essa é o Welch do
# gerar_perfil_sonda.py), só um feedback imediato para o operador.
#
# $4 = frequência planejada: define a histerese do detector de cruzamentos. Perto da Nyquist
# há só 2 a 5 amostras por ciclo e uma histerese de 10% da amplitude perderia ciclos inteiros;
# acima de 20% da taxa por canal ela cai para 3% (que ainda enxerga todo ciclo até ~49%).
analisar_rapido() {
    local arq="$1" pos_ref="$2" pos_sonda="$3" freq_plano="$4" fs_canal
    fs_canal="$(awk -v t="$TAXA" -v n="$NUM_CANAIS_CAPTURA" 'BEGIN { printf "%.6f", t / n }')"
    od -An -v -tu2 -w32 -j "$((CAB_TAMANHO + AMOSTRAS_IGNORADAS_INICIO * 2))" -N "$((AMOSTRAS_ANALISE_RAPIDA * 2))" "$arq" \
        | awk -v fs="$fs_canal" -v nc="$NUM_CANAIS_CAPTURA" -v pr="$pos_ref" -v ps="$pos_sonda" -v fp="$freq_plano" '
    function analisa(pos,   j, x, s, ss, mn, mx, rail, mean, rms, amp, h, arm, prev, cruz, t, tf, tl) {
        s = 0; ss = 0; mn = 1e9; mx = -1; rail = 0
        for (j = 0; j < m; j++) {
            x = v[nc * j + pos]; s += x; ss += x * x
            if (x < mn) mn = x
            if (x > mx) mx = x
            if (x <= 1 || x >= 65534) rail++
        }
        mean = s / m; rms = ss / m - mean * mean; rms = (rms > 0) ? sqrt(rms) : 0
        amp = (mx - mn) / 2; h = hfrac * amp
        arm = 0; cruz = 0; prev = v[pos]; tf = 0; tl = 0
        if (amp >= 20) {
            for (j = 1; j < m; j++) {
                x = v[nc * j + pos]
                if (x < mean - h) arm = 1
                else if (arm && prev <= mean && x > mean) {
                    t = (j - 1) + (mean - prev) / (x - prev)
                    if (cruz == 0) tf = t
                    tl = t; cruz++; arm = 0
                }
                prev = x
            }
        }
        FMED[pos] = (cruz >= 3 && tl > tf) ? (cruz - 1) * fs / (tl - tf) : 0
        PP[pos] = (mx - mn) / 65535 * 100
        RMS[pos] = rms
        SAT[pos] = rail / m
    }
    { for (i = 1; i <= NF; i++) v[n++] = $i }
    END {
        m = int(n / nc)
        if (m < 2048) { print "ERRO_POUCAS_AMOSTRAS"; exit }
        hfrac = (fp / fs > 0.2) ? 0.03 : 0.1
        analisa(ps)
        if (pr >= 0) {
            analisa(pr)
            razao = (RMS[pr] > 0) ? RMS[ps] / RMS[pr] : 0
            printf "%.3f %.3f %.2f %.2f %.3f %.3f %.6f %.6f %.6f\n", FMED[pr], FMED[ps], PP[pr], PP[ps], RMS[pr], RMS[ps], SAT[pr], SAT[ps], razao
        } else {
            printf "%.3f %.3f %.2f %.2f %.3f %.3f %.6f %.6f %.6f\n", 0, FMED[ps], 0, PP[ps], 0, RMS[ps], 0, SAT[ps], RMS[ps]
        }
    }'
}

# Avalia as métricas rápidas e acrescenta erros/avisos. $1 = arquivo, $2 = freq planejada.
avaliar_sinal() {
    local arq="$1" freq_plano="$2" pos_ref pos_sonda linha
    local f_ref f_sonda pp_ref pp_sonda rms_sonda sat_ref sat_sonda razao f_med
    if [ -z "$CANAL_REFERENCIA" ]; then pos_ref=-1; pos_sonda=0
    elif [ "$CANAL_REFERENCIA" -lt "$CANAL_SONDA" ]; then pos_ref=0; pos_sonda=1
    else pos_ref=1; pos_sonda=0; fi

    linha="$(analisar_rapido "$arq" "$pos_ref" "$pos_sonda" "$freq_plano")"
    if [ -z "$linha" ] || [ "$linha" = "ERRO_POUCAS_AMOSTRAS" ]; then
        qc_erro "poucas amostras no arquivo para analisar o sinal" poucas_amostras
        return
    fi
    read -r f_ref f_sonda pp_ref pp_sonda _ rms_sonda sat_ref sat_sonda razao <<< "$linha"   # _ = rms da referência (não usado aqui)
    QC_PP_SONDA="$pp_sonda"
    if [ -n "$CANAL_REFERENCIA" ]; then
        QC_PP_REF="$pp_ref"; QC_RAZAO="$razao"
    elif [ "$REF_EXTERNA" -eq 0 ] && [ -n "$AMPLITUDE_PONTO" ]; then
        # 1 canal, amplitude injetada conhecida: códigos do ADC por unidade (V ou A) de pico injetada
        QC_RAZAO="$(awk -v r="$rms_sonda" -v p="$(pico_da_amplitude "$AMPLITUDE_PONTO")" 'BEGIN { printf "%.6f", r / p }')"
    elif [ "$REF_EXTERNA" -eq 0 ]; then
        QC_RAZAO="$rms_sonda"     # 1 canal, amplitude suposta constante: o próprio nível da sonda (códigos do ADC)
    elif [ -n "$REF_VALOR" ]; then
        QC_RAZAO="$(awk -v r="$rms_sonda" -v v="$REF_VALOR" 'BEGIN { printf "%.6f", r / v }')"   # códigos por volt lido no osciloscópio
    fi

    # Saturação do ADC: o gerar_perfil_sonda.py descarta capturas assim.
    local dica_faixa=""
    if [ -n "$FAIXA_ADC_SONDA" ] && num_menor "$FAIXA_ADC_SONDA" 20; then dica_faixa=" ou aumente a faixa do ADC (--faixa-adc)"; fi
    if [ -n "$CANAL_REFERENCIA" ] && num_menor "$SATURACAO_MAXIMA" "$sat_ref"; then
        qc_erro "o canal de referência (${CANAL_REFERENCIA}) saturou o ADC em $(awk -v s="$sat_ref" 'BEGIN { printf "%.2f", s * 100 }')% das amostras -- reduza a amplitude do gerador" saturacao_ref
    fi
    if num_menor "$SATURACAO_MAXIMA" "$sat_sonda"; then
        qc_erro "o canal da sonda (${CANAL_SONDA}) saturou o ADC em $(awk -v s="$sat_sonda" 'BEGIN { printf "%.2f", s * 100 }')% das amostras -- reduza a amplitude injetada${dica_faixa}" saturacao_sonda
    fi

    # Nível do sinal (pico-a-pico, % da escala): pouco sinal = SNR ruim no perfil.
    local confira_ref confira_sonda
    if [ "$GRANDEZA" = "tensao" ]; then
        confira_ref="O gerador está ligado e o canal de referência no nó de entrada da cadeia?"
        confira_sonda="O gerador está ligado à entrada da cadeia e a saída dela no canal ${CANAL_SONDA}?"
    else
        confira_ref="O gerador está ligado e o shunt conectado?"
        confira_sonda="A sonda está no condutor certo e ligada?"
    fi
    if [ -n "$CANAL_REFERENCIA" ]; then
        if num_menor "$pp_ref" "$PP_SEM_SINAL_PCT"; then
            qc_erro "praticamente sem sinal no canal de referência (${CANAL_REFERENCIA}): pico-a-pico de ${pp_ref}% da escala. ${confira_ref}" sem_sinal_ref
        elif num_menor "$pp_ref" "$PP_FRACO_PCT"; then
            qc_aviso "sinal fraco no canal de referência (${pp_ref}% da escala): aumente a amplitude do gerador para melhorar a SNR" fraco_ref
        fi
    fi
    if num_menor "$pp_sonda" "$PP_SEM_SINAL_PCT"; then
        qc_erro "praticamente sem sinal no canal da sonda (${CANAL_SONDA}): pico-a-pico de ${pp_sonda}% da escala. ${confira_sonda}" sem_sinal_sonda
    elif num_menor "$pp_sonda" "$PP_FRACO_PCT"; then
        qc_aviso "sinal fraco no canal da sonda (${pp_sonda}% da escala): aumente a amplitude injetada para melhorar a SNR (em frequência alta é esperado: o filtro de 15 kHz do ADS8688 atenua o sinal)" fraco_sonda
    fi

    # Frequência realmente injetada (a medida vale mais que a planejada).
    # Só confio na frequência de um canal que TEM sinal (sobre ruído os cruzamentos de zero
    # dão uma "frequência" qualquer).
    f_med=0
    if [ -n "$CANAL_REFERENCIA" ] && ! num_menor "$pp_ref" "$PP_SEM_SINAL_PCT" && num_menor 0.5 "$f_ref"; then
        f_med="$f_ref"
    elif ! num_menor "$pp_sonda" "$PP_SEM_SINAL_PCT" && num_menor 0.5 "$f_sonda"; then
        f_med="$f_sonda"
    fi
    if num_menor 0.5 "$f_med"; then
        QC_FREQ_MEDIDA="$f_med"
        local desvio
        desvio="$(awk -v m="$f_med" -v p="$freq_plano" 'BEGIN { d = (m - p) / p * 100; printf "%.1f", (d < 0) ? -d : d }')"
        if num_menor "$FREQ_DESVIO_ERRO_PCT" "$desvio"; then
            qc_erro "a frequência medida é ${f_med} Hz, ${desvio}% fora da planejada (${freq_plano} Hz): o gerador está ajustado errado? (o gerar_perfil_sonda.py só procura o tom até ±10%)" freq_errada
        elif num_menor "$FREQ_DESVIO_AVISO_PCT" "$desvio"; then
            qc_aviso "a frequência medida é ${f_med} Hz, ${desvio}% fora da planejada (${freq_plano} Hz); vale para o perfil porque a frequência é medida, mas confira o gerador" freq_diferente
        fi
    fi
}

# Confere uma captura completa. $1 = arquivo, $2 = freq planejada. Preenche QC_*.
conferir_captura() {
    QC_ERROS=(); QC_AVISOS=(); QC_TAGS=""
    QC_FREQ_MEDIDA=""; QC_PP_REF=""; QC_PP_SONDA=""; QC_RAZAO=""
    if [ ! -s "$1" ]; then
        qc_erro "o ler_adc não gerou o arquivo (ou ele está vazio)" sem_arquivo
        return
    fi
    validar_cabecalho "$1"
    # Só vale analisar o sinal se o arquivo tem tamanho e cabeçalho minimamente sãos.
    case "$QC_TAGS" in
        *arquivo_curto*|*sem_cabecalho*|*cabecalho_v1*|*canais*|*tamanho*) return ;;
    esac
    avaliar_sinal "$1" "$2"
}

# O manifesto é um HISTÓRICO (um ponto refeito aparece mais de uma vez). Esta função devolve
# só as linhas que valem hoje: a ÚLTIMA de cada arquivo, com status ok*/aceito* e o arquivo
# ainda presente na pasta. Colunas: freq,rep,arquivo,timestamp,status,freq_medida,pp_ref,pp_sonda,razao.
linhas_validas_manifesto() {
    local manifesto="${PASTA_SONDA}/${NOME_MANIFESTO}" f rep arq ts status resto
    [ -f "$manifesto" ] || return 0
    awk -F, 'NR > 1 && $3 != "" { ultima[$3] = $0 } END { for (a in ultima) print ultima[a] }' "$manifesto" \
    | while IFS=, read -r f rep arq ts status resto; do
        case "$status" in ok*|aceito*) ;; *) continue ;; esac
        if [ -f "${PASTA_SONDA}/${arq}" ]; then
            printf '%s,%s,%s,%s,%s,%s\n' "$f" "$rep" "$arq" "$ts" "$status" "$resto"
        fi
    done
}

# Só as linhas SEM erro (status ok*): as únicas que entram em médias de ganho e na sugestão
# de pontos extras (uma captura aceita "com erro", p.ex. saturada, não pode guiar nada).
linhas_ok_manifesto() { linhas_validas_manifesto | awk -F, '$5 ~ /^ok/'; }

# Referência de ganho: razão rms (sonda/referência) média no PONTO DE MENOR FREQUÊNCIA com
# captura ok (0 se ainda não há nenhum). Os ganhos relativos são em dB contra ela.
razao_base() {
    linhas_ok_manifesto | awk -F, '$9 + 0 > 0 {
        f = $1 + 0
        if (min == "" || f < min) { min = f; s = 0; n = 0 }
        if (f == min) { s += $9; n++ }
    } END { if (n > 0) printf "%.6f", s / n; else print 0 }'
}

# Frequências cuja captura foi aceita COM erro (candidatas a --modo refazer), uma por linha.
frequencias_para_revisar() {
    linhas_validas_manifesto | awk -F, '$5 ~ /^aceito/ { print $1 + 0 }' | sort -n -u
}

# =============================================================================
# 9. Captura de um ponto
# =============================================================================

# Mostra o resultado da conferência e define SUGESTAO (C ou R).
mostrar_resultado() {
    local freq="$1" base ganho_txt="" linha msg
    if [ "${#QC_ERROS[@]}" -eq 0 ]; then
        SUGESTAO="C"
        if [ "${#QC_AVISOS[@]}" -eq 0 ]; then
            log_sucesso "Captura conferida: cabeçalho, tamanho e sinal OK."
        else
            log_sucesso "Captura utilizável (cabeçalho e tamanho íntegros), mas com avisos:"
        fi
    else
        SUGESTAO="R"
        for msg in "${QC_ERROS[@]}"; do log_erro "$msg"; done
    fi
    if [ "${#QC_AVISOS[@]}" -gt 0 ]; then
        for msg in "${QC_AVISOS[@]}"; do log_aviso "$msg"; done
    fi
    if [ -n "$QC_PP_SONDA" ]; then
        local rotulo="ganho relativo à menor frequência"
        if [ -z "$CANAL_REFERENCIA" ] && [ "$REF_EXTERNA" -eq 0 ]; then
            if [ -n "$AMPLITUDE_PONTO" ]; then
                rotulo="ganho relativo à menor frequência (pela amplitude injetada)"
            else
                rotulo="nível relativo à menor frequência (supondo amplitude constante)"
            fi
        fi
        base="$(razao_base)"
        if [ "${#QC_ERROS[@]}" -gt 0 ]; then
            ganho_txt=""   # com erro (saturação, sem sinal...) o ganho medido não significa nada
        elif [ -n "$QC_RAZAO" ] && num_menor 0 "$QC_RAZAO" && num_menor 0 "$base"; then
            ganho_txt="$(awk -v r="$QC_RAZAO" -v b="$base" -v t="$rotulo" 'BEGIN { printf "%s: %+.2f dB", t, 20 * log(r / b) / log(10) }')"
        elif [ -n "$QC_RAZAO" ] && num_menor 0 "$QC_RAZAO"; then
            ganho_txt="primeiro ponto sem erro: servirá de referência (0 dB) para os próximos"
        fi
        linha="  "
        [ -n "$CANAL_REFERENCIA" ] && linha+="Referência: ${QC_PP_REF}% da escala | "
        linha+="Sonda: ${QC_PP_SONDA}% | frequência medida: ${QC_FREQ_MEDIDA:-não medida}${QC_FREQ_MEDIDA:+ Hz} (planejada ${freq} Hz)"
        saida "$linha"
        [ -n "$REF_VALOR" ] && saida "  Leitura do osciloscópio: ${REF_VALOR} V RMS ${ONDE_REFERENCIA}"
        [ -n "$AMPLITUDE_PONTO" ] && saida "  Amplitude injetada (gravada nos metadados): ${AMPLITUDE_PONTO}"
        [ -n "$ganho_txt" ] && saida "  ${ganho_txt}"
    fi
}

# Chama o ler_adc para UM ponto, gravando em $1 (temporário). Sai com o código do ler_adc
# (124 = estourou o tempo limite; 137 = nem o Ctrl+C o parou e ele foi morto). Saída completa
# no log da pasta, precedida da linha de comando exata.
executar_captura() {
    local destino="$1" titulo="$2" descricao="${3:-}" duracao limite codigo log="${PASTA_SONDA}/${NOME_LOG}"
    local -a cmd=("$LER_ADC" "$TAXA" "$LISTA_CANAIS" --blocos "$BLOCOS"
                  --grandeza "${CANAL_SONDA}:${GRANDEZA}" --sonda "${CANAL_SONDA}:${SONDA_ID}"
                  "${ARGS_FAIXA_ADC[@]}" "${ARGS_ATRASO_CS[@]}" -o "$destino" -t "$titulo")
    [ -n "$descricao" ] && cmd+=(-d "$descricao")   # metadados: frequência e amplitude injetadas (ref: f=.. amp=..)
    duracao="$(duracao_captura)"
    limite="${SH_LER_ADC_TIMEOUT:-$(awk -v d="$duracao" 'BEGIN { printf "%d", d * 3 + 60 }')}"
    : >> "$log"
    LOG_LINHAS_ANTES="$(wc -l < "$log" | tr -d ' ')"
    printf '=== %s |%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$(printf ' %q' "${LER_ADC##*/}" "${cmd[@]:1}")" >> "$log"
    log_info "Capturando (~${duracao} s)..."
    # Estourado o limite, o ler_adc recebe SIGINT (o mesmo Ctrl+C que ele trata: fecha o arquivo e para a
    # PRU); se nem isso o parar em 10 s, KILL.
    local -a limitar=(timeout --foreground -s INT -k 10 "$limite")
    if [ "$VERBOSO" -eq 1 ]; then
        "${limitar[@]}" "${cmd[@]}" 2>&1 | tee -a "$log" >&2
        codigo="${PIPESTATUS[0]}"
    else
        "${limitar[@]}" "${cmd[@]}" >> "$log" 2>&1
        codigo=$?
    fi
    return "$codigo"
}

descrever_falha_ler_adc() {
    local codigo="$1" log="${PASTA_SONDA}/${NOME_LOG}"
    if [ "$codigo" -eq 124 ] || [ "$codigo" -eq 137 ]; then
        local como="estourou o tempo limite"
        [ "$codigo" -eq 137 ] && como+=" e só parou com KILL"
        log_erro "O ler_adc travou (${como}) -- a PRU provavelmente não está respondendo. Rode ./setup.sh de novo se isso se repetir."
    else
        log_erro "O ler_adc terminou com código ${codigo}."
    fi
    if [ "$VERBOSO" -eq 0 ]; then
        local trecho
        trecho="$(tail -n +"$((LOG_LINHAS_ANTES + 2))" "$log" | tail -n 12)"
        if [ -n "$trecho" ]; then
            saida "  Saída do ler_adc nesta tentativa (histórico completo em ${log}):"
            printf '%s\n' "$trecho" | sed 's/^/    | /' >&2
        fi
    fi
}

# Pergunta o que fazer com a captura (laço PRÓPRIO para validar a escolha: opção inválida
# nunca remede). Define ESCOLHA como c, r, p ou a. ENTER = sugestão.
perguntar_destino() {
    local sugestao="$1" entrada
    echo >&2
    saida "  [C] Continuar  -- aceita esta captura e segue"
    saida "  [R] Refazer    -- descarta e mede este ponto de novo"
    saida "  [P] Pular      -- descarta e deixa este ponto de fora (dá para pegá-lo depois com --modo retomar)"
    saida "  [A] Abortar    -- descarta e encerra (o que já foi aceito fica salvo)"
    while true; do
        if ! read -r -p "$(printf "%b" "${COR_AMARELO}Escolha [${sugestao}]: ${COR_RESET}")" entrada; then
            erro_fatal "Entrada encerrada inesperadamente (EOF em stdin) -- abortando."
        fi
        entrada="${entrada,,}"
        [ -z "$entrada" ] && entrada="${sugestao,,}"
        case "$entrada" in
            c|r|p|a) ESCOLHA="$entrada"; return 0 ;;
            *) log_erro "Opção inválida -- digite C, R, P ou A." ;;
        esac
    done
}

# Modo refazer: ao aceitar a captura nova, as antigas do mesmo ponto vão para descartadas/
# (nunca são apagadas) e o manifesto registra o que foi substituído.
arquivar_capturas_antigas() {
    local freq="$1" rep="$2" f dest
    mkdir -p "${PASTA_SONDA}/descartadas" || return 1
    for f in "${PASTA_SONDA}/calibracao_${freq}Hz_rep${rep}.bin" \
             "${PASTA_SONDA}"/calibracao_"${freq}"Hz_rep"${rep}"_v[0-9]*.bin; do
        [ -f "$f" ] || continue
        dest="${PASTA_SONDA}/descartadas/$(date +%Y%m%d_%H%M%S)_${f##*/}"
        if mv -f "$f" "$dest"; then
            registrar_manifesto "$freq" "$rep" "descartadas/${dest##*/}" "substituido"
            log_info "Captura antiga arquivada em descartadas/${dest##*/}"
        fi
    done
}

# Modo --ref-externa: pede a tensão RMS lida no osciloscópio (sobre o shunt ou na entrada da cadeia de
# tensão) e a deixa em REF_VALOR (em Volts). ENTER sem valor = sem leitura -- ou, numa nova tentativa do
# mesmo ponto, reaproveita a leitura anterior (mostrada entre colchetes).
pedir_leitura_externa() {
    local entrada convertido dica=""
    [ -n "$REF_VALOR" ] && dica=" [${REF_VALOR}]"
    while true; do
        if ! read -r -p "$(printf "%b" "${COR_AMARELO}Osciloscópio: tensão RMS ${ONDE_REFERENCIA}, em V (ex.: 0.7071 ou 707.1m)${dica}; ENTER = sem leitura: ${COR_RESET}")" entrada; then
            erro_fatal "Entrada encerrada inesperadamente (EOF em stdin) -- abortando."
        fi
        if [ -z "$entrada" ]; then
            if [ -z "$REF_VALOR" ]; then
                log_aviso "Sem leitura para este ponto: sem ela o gerar_perfil_sonda.py --referencia-externa o deixa de fora. Dá para anotá-la depois em ${NOME_REFERENCIA_EXTERNA} (coluna $(coluna_referencia_externa))."
            fi
            return 0
        fi
        if convertido="$(normalizar_tensao "$entrada")"; then
            REF_VALOR="$convertido"
            return 0
        fi
        log_erro "Valor inválido: '${entrada}'. Use a tensão RMS em volts (0.1234) ou milivolts (123.4m)."
    done
}

# Modo --amplitude-por-ponto: pergunta a amplitude da senoide que o gerador está injetando e a deixa em
# AMPLITUDE_PONTO (texto limpo, vai para os metadados da captura). ENTER mantém a anterior (entre
# colchetes); na primeira vez, sem valor inicial, a amplitude é obrigatória.
pedir_amplitude_ponto() {
    local entrada limpo motivo dica=""
    [ -n "$AMPLITUDE_PONTO" ] && dica=" [${AMPLITUDE_PONTO}]"
    while true; do
        if ! read -r -p "$(printf "%b" "${COR_AMARELO}$(texto_pergunta_amplitude) (ex.: ${EXEMPLOS_AMPLITUDE})${dica}: ${COR_RESET}")" entrada; then
            erro_fatal "Entrada encerrada inesperadamente (EOF em stdin) -- abortando."
        fi
        if [ -z "$entrada" ]; then
            [ -n "$AMPLITUDE_PONTO" ] && return 0
            log_erro "Informe a amplitude que o gerador está injetando (ex.: ${EXEMPLOS_AMPLITUDE%%,*})."
            continue
        fi
        if ! limpo="$(normalizar_amplitude "$entrada")"; then
            log_erro "Amplitude inválida: '${entrada}' -- ${limpo}."
        elif motivo="$(amplitude_incompativel "$limpo")"; then
            log_erro "Amplitude inválida: '${entrada}' -- ${motivo}."
        else
            AMPLITUDE_PONTO="$limpo"
            return 0
        fi
    done
}

# Como pedir a amplitude: na cadeia de tensão ela é a do PINO DO ADC (é o que o gerar_perfil_sonda.py
# multiplica pelo --ganho), não a da entrada -- o erro mais fácil de cometer nesse modo.
texto_pergunta_amplitude() {
    if [ "$GRANDEZA" = "tensao" ]; then
        printf '%s' "Amplitude da senoide NO PINO DO ADC (= a da entrada da cadeia x a razão do divisor)"
    else
        printf '%s' "Amplitude da senoide no gerador"
    fi
}

# Processa UMA captura (frequência + repetição). Retorna 0 se aceita, 3 se pulada.
# Aborta o script (exit 0) se o operador pedir.
processar_captura() {
    local indice="$1" total="$2" freq="$3" rep="$4" repeticao_mesma_freq="$5"
    local resposta alvo temporario titulo descricao codigo status final

    REF_VALOR=""
    separador
    printf "%b\n" "${COR_NEGRITO}Ponto ${indice} de ${total}  |  ${freq} Hz  |  repetição ${rep} de ${REPETICOES}${COR_RESET}" >&2
    separador

    if [ "$repeticao_mesma_freq" -eq 1 ]; then
        saida "  Mesma frequência da captura anterior (${freq} Hz): não precisa mexer no gerador."
    else
        printf "%b\n" "  ${COR_NEGRITO}>>> INJETE ${freq} Hz no gerador <<<${COR_RESET}" >&2
        if [ "$REF_EXTERNA" -eq 1 ]; then
            saida "  Espere o sinal estabilizar e leia no osciloscópio a tensão RMS ${ONDE_REFERENCIA} (ciclos inteiros, com média)."
        elif [ "$AMPLITUDE_POR_PONTO" -eq 1 ]; then
            saida "  Ajuste o gerador (SENOIDE pura), espere o sinal estabilizar e informe a amplitude que ele está injetando."
        elif [ -n "$AMPLITUDE" ] && [ "$GRANDEZA" = "tensao" ]; then
            saida "  Ajuste o gerador (SENOIDE pura) para o pino do ADC receber ${AMPLITUDE} e espere o sinal estabilizar."
        elif [ -n "$AMPLITUDE" ]; then
            saida "  Ajuste o gerador para uma SENOIDE pura de ${AMPLITUDE} e espere o sinal estabilizar."
        elif [ -z "$CANAL_REFERENCIA" ]; then
            saida "  Mantenha a MESMA amplitude de ${ROTULO_GRANDEZA} de antes e espere o sinal estabilizar."
        else
            saida "  Espere o sinal estabilizar (o canal de referência mede a amplitude: ela pode mudar de um ponto para outro)."
        fi
    fi
    while true; do
        verificar_espaco_disco "$PASTA_SONDA"
        if ! read -r -p "$(printf "%b" "${COR_AMARELO}ENTER para medir  |  p = pular este ponto  |  a = abortar: ${COR_RESET}")" resposta; then
            erro_fatal "Entrada encerrada inesperadamente (EOF em stdin) -- abortando."
        fi
        case "${resposta,,}" in
            a) log_aviso "Abortado pelo operador antes da medição."; resumo_curto; dica_retomar; exit 0 ;;
            p) log_aviso "Ponto de ${freq} Hz pulado."
               registrar_manifesto "$freq" "$rep" "" "pulado"
               SESSAO_PULADOS=$((SESSAO_PULADOS + 1))
               return 3 ;;
        esac

        if [ "$REF_EXTERNA" -eq 1 ]; then pedir_leitura_externa; fi
        if [ "$AMPLITUDE_POR_PONTO" -eq 1 ]; then pedir_amplitude_ponto; fi
        alvo="${PASTA_SONDA}/calibracao_${freq}Hz_rep${rep}.bin"
        temporario="${PASTA_SONDA}/.em_andamento_$$.bin"
        titulo="Calibracao ${freq}Hz rep${rep} ${SONDA_ID}"
        titulo="${titulo:0:63}"   # o ler_adc REJEITA (não trunca) títulos acima de 63 bytes
        rm -f "$temporario"
        ARQUIVO_EM_CAPTURA="$temporario"

        descricao="$(descricao_da_captura "$freq")"
        executar_captura "$temporario" "$titulo" "$descricao"
        codigo=$?
        if [ "$codigo" -ne 0 ]; then
            descrever_falha_ler_adc "$codigo"
        fi
        conferir_captura "$temporario" "$freq"
        if [ "$codigo" -ne 0 ] && [ -s "$temporario" ]; then
            qc_aviso "o ler_adc terminou com erro (código ${codigo}) mas deixou um arquivo; a conferência abaixo é do que foi gravado" ler_adc_erro
        fi
        mostrar_resultado "$freq"
        if [ "$codigo" -ne 0 ]; then SUGESTAO="R"; fi

        perguntar_destino "$SUGESTAO"
        case "$ESCOLHA" in
            c)
                if [ ! -s "$temporario" ]; then
                    log_erro "Não há arquivo para aceitar (a captura falhou antes de gravar). Refazendo este ponto."
                    ARQUIVO_EM_CAPTURA=""
                    continue
                fi
                if [ "$SUBSTITUIR_EXISTENTES" -eq 1 ]; then arquivar_capturas_antigas "$freq" "$rep"; fi
                final="$(caminho_disponivel "$alvo")"
                [ "$final" != "$alvo" ] && log_aviso "'${alvo##*/}' já existe -- gravando como '${final##*/}' em vez de sobrescrever."
                if ! mv -f "$temporario" "$final"; then
                    log_erro "Não consegui renomear a captura para '${final}' -- refazendo."
                    rm -f "$temporario"; ARQUIVO_EM_CAPTURA=""
                    continue
                fi
                ARQUIVO_EM_CAPTURA=""
                if [ "$codigo" -ne 0 ]; then
                    status="aceito_com_erro_${codigo}"
                elif [ "${#QC_ERROS[@]}" -gt 0 ]; then
                    status="aceito_com_erro_qc_${QC_TAGS}"
                elif [ "${#QC_AVISOS[@]}" -gt 0 ]; then
                    status="ok_com_aviso_${QC_TAGS}"
                else
                    status="ok"
                fi
                registrar_manifesto "$freq" "$rep" "${final##*/}" "$status" "$QC_FREQ_MEDIDA" "$QC_PP_REF" "$QC_PP_SONDA" "$QC_RAZAO" "$REF_VALOR" "$AMPLITUDE_PONTO"
                if [ "$REF_EXTERNA" -eq 1 ]; then registrar_referencia_externa "${final##*/}" "$REF_VALOR"; fi
                SESSAO_ACEITOS=$((SESSAO_ACEITOS + 1))
                log_sucesso "Ponto aceito: ${final##*/}"
                return 0
                ;;
            r)
                log_aviso "Descartando a captura e repetindo este ponto."
                rm -f "$temporario"; ARQUIVO_EM_CAPTURA=""
                ;;
            p)
                log_aviso "Ponto de ${freq} Hz pulado (captura descartada)."
                rm -f "$temporario"; ARQUIVO_EM_CAPTURA=""
                registrar_manifesto "$freq" "$rep" "" "pulado"
                SESSAO_PULADOS=$((SESSAO_PULADOS + 1))
                return 3
                ;;
            a)
                log_aviso "Abortado pelo operador (captura descartada)."
                rm -f "$temporario"; ARQUIVO_EM_CAPTURA=""
                resumo_curto
                dica_retomar
                exit 0
                ;;
        esac
    done
}

# Coleta uma lista de pares "FREQ REP" (um por linha, em $1 como texto), na ordem dada.
# Itera por um ARRAY: um 'while read ... done <<< "$pares"' redirecionaria o stdin de TUDO que
# está dentro do laço, e os 'read' interativos do operador leriam a lista em vez do teclado.
coletar_pares() {
    local -a linhas=()
    local linha freq rep indice=0 anterior="" total
    mapfile -t linhas <<< "$1"
    total="${#linhas[@]}"
    [ -z "${linhas[0]:-}" ] && return 0
    for linha in "${linhas[@]}"; do
        read -r freq rep <<< "$linha"
        [ -z "$freq" ] && continue
        indice=$((indice + 1))
        if [ "$freq" = "$anterior" ]; then
            processar_captura "$indice" "$total" "$freq" "$rep" 1
        else
            processar_captura "$indice" "$total" "$freq" "$rep" 0
        fi
        anterior="$freq"
    done
}

# Pares "FREQ REP" (rep de 1 a REPETICOES) para as frequências dadas que ainda NÃO têm
# captura em disco. Frequências em argumentos.
pares_pendentes() {
    local existentes freq rep
    existentes="$(capturas_em_disco | awk '{ print $1 "_" $2 }')"
    for freq in "$@"; do
        for ((rep = 1; rep <= REPETICOES; rep++)); do
            if ! grep -qx "${freq}_${rep}" <<< "$existentes"; then
                echo "${freq} ${rep}"
            fi
        done
    done
}

# =============================================================================
# 10. Resumo e sugestão de pontos extras
# =============================================================================

# Tabela por frequência (capturas aceitas que ainda existem em disco): quantas, frequência
# medida, nível da sonda e ganho relativo (dB) ao ponto de menor frequência (só capturas ok).
mostrar_tabela() {
    local linhas
    linhas="$(linhas_validas_manifesto | sort -t, -k1,1n)"
    if [ -z "$linhas" ]; then
        saida "  (nenhuma captura aceita ainda)"
        return 0
    fi
    local const=0
    [ -z "$CANAL_REFERENCIA" ] && [ "$REF_EXTERNA" -eq 0 ] && [ -z "$AMPLITUDE" ] && [ "$AMPLITUDE_POR_PONTO" -eq 0 ] && const=1
    printf '%s\n' "$linhas" | awk -F, -v const="$const" '
    {
        f = $1 + 0
        if (!(f in cnt)) { ordem[++nf] = f }
        cnt[f]++
        if ($6 + 0 > 0) { sf[f] += $6; nfm[f]++ }
        if ($8 + 0 > 0) { sp[f] += $8; nsp[f]++ }
        if ($5 ~ /^ok/ && $9 + 0 > 0) { sr[f] += $9; nr[f]++ }
        if ($5 ~ /^aceito/) nivel[f] = 2
        else if ($5 ~ /^ok_com_aviso/ && nivel[f] < 1) nivel[f] = 1
    }
    END {
        base = 0
        for (i = 1; i <= nf; i++) { f = ordem[i]; if (nr[f] > 0) { base = sr[f] / nr[f]; break } }
        printf "  %10s  %5s  %12s  %10s  %12s  %s\n", "freq plano", "caps", "freq medida", "sonda (%)", (const ? "nivel rel." : "ganho rel."), "obs"
        for (i = 1; i <= nf; i++) {
            f = ordem[i]
            fm = (nfm[f] > 0) ? sprintf("%.1f", sf[f] / nfm[f]) : "-"
            pp = (nsp[f] > 0) ? sprintf("%.1f", sp[f] / nsp[f]) : "-"
            g = (nr[f] > 0 && base > 0) ? sprintf("%+.2f dB", 20 * log((sr[f] / nr[f]) / base) / log(10)) : "-"
            obs = (nivel[f] == 2) ? "ACEITA COM ERRO (refazer)" : ((nivel[f] == 1) ? "aviso" : "")
            printf "  %10d  %5d  %12s  %10s  %12s  %s\n", f, cnt[f], fm, pp, g, obs
        }
    }' >&2
}

# Intervalos onde o ganho relativo muda mais entre frequências vizinhas. Imprime
# "DELTA_DB F_BAIXA F_ALTA F_NOVA", do maior para o menor delta, só os acima do limiar e
# com F_NOVA estritamente entre as duas e fora do plano. $1.. = frequências já no plano.
candidatos_refino() {
    local plano="$*"
    linhas_ok_manifesto | awk -F, '$9 + 0 > 0 { print $1 + 0, $9 }' | sort -n \
    | awk -v lim="$LIMIAR_REFINO_DB" -v rmin="$RAZAO_FREQ_MIN_REFINO" -v plano="$plano" '
    function amigavel(f,   m) {
        if (f >= 1000) { m = 10 ^ (int(log(f) / log(10) + 1e-9) - 2); return int(f / m + 0.5) * m }
        return int(f + 0.5)
    }
    BEGIN { np = split(plano, P, " "); for (i = 1; i <= np; i++) NO_PLANO[P[i] + 0] = 1 }
    { f = $1 + 0; if (!(f in S)) { ordem[++n] = f }; S[f] += $2; C[f]++ }
    END {
        for (i = 1; i < n; i++) {
            f1 = ordem[i]; f2 = ordem[i + 1]
            r1 = S[f1] / C[f1]; r2 = S[f2] / C[f2]
            d = 20 * log(r2 / r1) / log(10); if (d < 0) d = -d
            if (d < lim || f2 / f1 < rmin) continue
            novo = amigavel(sqrt(f1 * f2))
            if (novo <= f1 || novo >= f2 || (novo in NO_PLANO)) continue
            printf "%.2f %d %d %d\n", d, f1, f2, novo
        }
    }' | sort -rn
}

dica_retomar() {
    log_info "Para continuar depois:  sudo ./calibrar_sonda.sh --modo retomar --sonda ${SONDA_ID}"
}

resumo_curto() {
    separador
    if [ $((SESSAO_ACEITOS + SESSAO_PULADOS)) -gt 0 ]; then
        log_info "Nesta sessão: ${SESSAO_ACEITOS} captura(s) aceita(s), ${SESSAO_PULADOS} ponto(s) pulado(s)."
    fi
    log_info "Pasta: ${PASTA_SONDA}/"
}

instrucoes_finais() {
    separador
    log_sucesso "Sonda '${SONDA_ID}': situação da coleta."
    mostrar_tabela
    resumo_curto
    proximos_passos
}

proximos_passos() {
    local perfil="uv run scripts/gerar_perfil_sonda.py capturas/${SONDA_ID}" o_que_e_g
    if [ "$GRANDEZA" = "tensao" ]; then
        o_que_e_g="<G> = 1 ÷ razão do divisor/atenuador do canal (ex.: 19.357)"
    else
        o_que_e_g="<G> = 1 ÷ sensibilidade nominal da sonda (ex.: 10 para 100 mV/A)"
    fi
    saida ""
    saida "Próximos passos:"
    saida "  1. Copie a pasta para o computador (na raiz do repositório):"
    saida "       mkdir -p capturas && scp -r debian@<ip-da-beaglebone>:$(cd "$PASTA_SONDA" && pwd) capturas/"
    saida "  2. Gere o perfil:"
    if [ -n "$CANAL_REFERENCIA" ] && [ "$GRANDEZA" = "tensao" ]; then
        saida "       ${perfil} --canal-referencia ${CANAL_REFERENCIA} --canal-sonda ${CANAL_SONDA} --resistencia-shunt 1 --ganho <G_ref>,<G> --plot"
        saida "     Os dois canais estão marcados como tensão, então vão explícitos. Com 1 Ω, a \"corrente\" do canal de referência é a"
        saida "     própria tensão injetada; <G_ref> = o ganho do canal de referência (1 se ele mede o nó de entrada direto)."
    elif [ -n "$CANAL_REFERENCIA" ]; then
        saida "       ${perfil} --resistencia-shunt <ohms-do-shunt> --ganho <G_ref>,<G> --plot"
        saida "     <G_ref> = o ganho do canal de referência (1 se a tensão do shunt vai direto ao ADC)."
    elif [ "$REF_EXTERNA" -eq 1 ]; then
        local coluna sem_leitura
        coluna="$(coluna_referencia_externa)"
        if [ "$coluna" = "tensao_rms_V" ]; then
            saida "       ${perfil} --referencia-externa --ganho <G> --plot"
        elif [ "$GRANDEZA" = "tensao" ]; then
            saida "       ${perfil} --referencia-externa --resistencia-shunt 1 --ganho <G> --plot"
            saida "     (o ${NOME_REFERENCIA_EXTERNA} desta pasta usa a coluna ${coluna}, de uma versão anterior; com 1 Ω a leitura vale como está)"
        else
            saida "       ${perfil} --referencia-externa --resistencia-shunt <ohms-do-shunt> --ganho <G> --plot"
        fi
        sem_leitura="$(capturas_sem_leitura_externa | grep -c . || true)"
        if [ "$sem_leitura" -gt 0 ]; then
            log_aviso "${sem_leitura} captura(s) sem leitura do osciloscópio em ${NOME_REFERENCIA_EXTERNA}: ficarão FORA do perfil até você anotar o valor (coluna ${coluna}) ou refazer o ponto."
        fi
    elif [ -n "$AMPLITUDE" ] || [ "$AMPLITUDE_POR_PONTO" -eq 1 ]; then
        saida "       ${perfil} --ganho <G> --plot"
        saida "     A amplitude injetada de cada captura está nos metadados (ref: f=.. amp=..) e é lida sozinha. Em V ela é a tensão no"
        saida "     pino do ADC, que o gerar_perfil_sonda.py multiplica pelo --ganho (ver docs/user-guide.md); para conferir o método,"
        saida "     meça alguns pontos também no osciloscópio e use --referencia-osciloscopio (um .m por captura, com o nome dela)."
    else
        saida "       ${perfil} --amplitude-referencia <amplitude, ex.: ${EXEMPLOS_AMPLITUDE%%,*}> --ganho <G> --plot"
        saida "     Isso só vale se o sinal teve a MESMA amplitude em todas as frequências; se não, refaça com --amplitude-por-ponto (ou --ref-externa)."
    fi
    saida "     ${o_que_e_g}: o mesmo --ganho que o canal terá no adc_tool.py (e o mesmo --formato); o perfil sai relativo a ele."
    saida "     A --faixa não precisa: cada captura leva no cabeçalho a faixa de entrada do ADC com que foi medida (cabeçalho v3)."
    if [ -n "$CANAL_REFERENCIA" ]; then
        saida "     Lembre: o filtro de ~15 kHz do ADS8688 é igual nos dois canais e se cancela na razão; este perfil não o corrige."
    fi
    local pendentes
    pendentes="$(pares_pendentes "${PLANO_FREQS[@]}" | grep -c . || true)"
    if [ "$pendentes" -gt 0 ]; then
        log_aviso "Há ${pendentes} captura(s) do plano ainda sem arquivo. Para completar:  sudo ./calibrar_sonda.sh --modo retomar --sonda ${SONDA_ID}"
    fi
}

# Oferece pontos extras onde o ganho varia mais. $1 = quantos no máximo ("" = perguntar).
oferecer_refino() {
    local maximo="${1:-}" candidatos n sugestao escolhido linha confirmar resposta
    candidatos="$(candidatos_refino "${PLANO_FREQS[@]}")"
    n="$(printf '%s\n' "$candidatos" | grep -c . || true)"
    if [ "$n" -eq 0 ]; then
        log_sucesso "Malha adequada: o ganho varia menos de ${LIMIAR_REFINO_DB} dB entre frequências vizinhas. Não vejo pontos extras úteis."
        return 1
    fi
    titulo_secao "Pontos extras sugeridos"
    saida "O ganho (relativo) muda mais entre estas frequências vizinhas; um ponto no meio melhora o perfil:"
    saida ""
    printf '%s\n' "$candidatos" | awk '{ printf "  entre %6d e %6d Hz: variação de %5.2f dB  ->  medir em %d Hz\n", $2, $3, $1, $4 }' >&2
    saida ""
    if [ -z "$maximo" ]; then
        sugestao=$(( n < 5 ? n : 5 ))
        if [ "$ASSUMIR_SIM" -eq 1 ]; then
            maximo=0
            log_info "Para coletar esses pontos:  sudo ./calibrar_sonda.sh --modo refinar --sonda ${SONDA_ID}"
        else
            ler_valor resposta "Quantos pontos extras coletar? (0 = nenhum) [${sugestao}]: " "^[0-9]+\$|^\$"
            maximo="${resposta:-$sugestao}"
        fi
    fi
    [ "$maximo" -le 0 ] && return 1
    [ "$maximo" -gt "$n" ] && maximo="$n"
    escolhido="$(printf '%s\n' "$candidatos" | head -n "$maximo" | awk '{ print $4 }' | sort -n -u)"
    local -a novas=()
    while read -r linha; do [ -n "$linha" ] && novas+=("$linha"); done <<< "$escolhido"
    coletar_extras "${novas[@]}"
    return 0
}

# Acrescenta frequências ao plano e coleta o que falta delas.
coletar_extras() {
    local -a extras=("$@") unidas=()
    local f pares
    [ "${#extras[@]}" -eq 0 ] && return 0
    while read -r f; do [ -n "$f" ] && unidas+=("$f"); done < <(unir_frequencias "${PLANO_FREQS[@]}" "${extras[@]}")
    PLANO_FREQS=("${unidas[@]}")
    salvar_plano
    pares="$(pares_pendentes "${extras[@]}")"
    if [ -z "$pares" ]; then
        log_info "Nenhuma captura nova a fazer (as frequências extras já têm arquivo)."
        return 0
    fi
    log_info "Coletando ${#extras[@]} frequência(s) extra(s): ${extras[*]} Hz"
    coletar_pares "$pares"
}

# =============================================================================
# 11. Parâmetros, plano e modos
# =============================================================================

# Normaliza --grandeza (vazia = corrente) e escolhe os textos que dependem dela. Idempotente. Só deve rodar
# DEPOIS de carregar_plano: antes disso, vazia quer dizer "não informada" (e o plano salvo decide).
definir_grandeza() {
    local g="${GRANDEZA,,}"
    case "${g:-corrente}" in
        corrente) GRANDEZA="corrente" ;;
        tensao|tensão) GRANDEZA="tensao" ;;
        *) erro_fatal "Valor inválido para --grandeza: '${GRANDEZA}'. Use corrente (sonda de corrente) ou tensao (cadeia de um canal de tensão)." ;;
    esac
    if [ "$GRANDEZA" = "tensao" ]; then
        ROTULO_GRANDEZA="tensão"
        ONDE_REFERENCIA="na entrada da cadeia"
        EXEMPLOS_AMPLITUDE="1.0332Vpp, 516.6mVpk, 365.3mVrms"
    else
        ROTULO_GRANDEZA="corrente"
        ONDE_REFERENCIA="no shunt"
        EXEMPLOS_AMPLITUDE="500mVpp, 250mVpk, 2Arms"
    fi
}

# Valida os canais e define NUM_CANAIS_CAPTURA e LISTA_CANAIS. Sem canal de referência, a captura
# tem 1 canal (a sonda) e a Nyquist efetiva é taxa/2; com ele, 2 canais e taxa/4. Idempotente.
definir_canais() {
    definir_grandeza
    validar_inteiro_faixa "Canal da sonda (--canal-sonda)" "$CANAL_SONDA" 0 7
    ARGS_FAIXA_ADC=()
    local pares=""
    if [ -n "$FAIXA_ADC_SONDA" ]; then
        codigo_faixa_adc "$FAIXA_ADC_SONDA" > /dev/null || erro_fatal "--faixa-adc '${FAIXA_ADC_SONDA}' inválida: use 20.48 (±10,24 V), 10.24 (±5,12 V) ou 5.12 (±2,56 V)."
        pares="${CANAL_SONDA}:${FAIXA_ADC_SONDA}"
    fi
    if [ -n "$FAIXA_ADC_REFERENCIA" ]; then
        [ -n "$CANAL_REFERENCIA" ] || erro_fatal "--faixa-adc-referencia só vale com --canal-referencia."
        codigo_faixa_adc "$FAIXA_ADC_REFERENCIA" > /dev/null || erro_fatal "--faixa-adc-referencia '${FAIXA_ADC_REFERENCIA}' inválida: use 20.48 (±10,24 V), 10.24 (±5,12 V) ou 5.12 (±2,56 V)."
        pares="${pares:+${pares},}${CANAL_REFERENCIA}:${FAIXA_ADC_REFERENCIA}"
    fi
    [ -n "$pares" ] && ARGS_FAIXA_ADC=(--faixa-adc "$pares")
    ARGS_ATRASO_CS=()
    if [ -n "$ATRASO_CS" ]; then
        # A mesma regra do ler_adc (três inteiros de 1 a 10000), conferida aqui para falhar antes da 1ª captura.
        if ! [[ "$ATRASO_CS" =~ ^([1-9][0-9]{0,4}),([1-9][0-9]{0,4}),([1-9][0-9]{0,4})$ ]] \
            || [ "${BASH_REMATCH[1]}" -gt 10000 ] || [ "${BASH_REMATCH[2]}" -gt 10000 ] || [ "${BASH_REMATCH[3]}" -gt 10000 ]; then
            erro_fatal "--atraso-cs '${ATRASO_CS}' inválido: use três inteiros de 1 a 10000 separados por vírgula (setup,hold,alto; padrão 3,1,3)."
        fi
        ARGS_ATRASO_CS=(--atraso-cs "$ATRASO_CS")
    fi
    if { [ -n "$AMPLITUDE" ] || [ "$AMPLITUDE_POR_PONTO" -eq 1 ]; } && { [ "$REF_EXTERNA" -eq 1 ] || [ -n "$CANAL_REFERENCIA" ]; }; then
        erro_fatal "--amplitude/--amplitude-por-ponto não combinam com --ref-externa nem com --canal-referencia: escolha UMA fonte para o que foi injetado na sonda."
    fi
    local motivo
    if [ -n "$AMPLITUDE" ] && motivo="$(amplitude_incompativel "$AMPLITUDE")"; then
        erro_fatal "Valor inválido para --amplitude: '${AMPLITUDE}' -- ${motivo}."
    fi
    if [ -z "$CANAL_REFERENCIA" ]; then
        NUM_CANAIS_CAPTURA=1
        LISTA_CANAIS="$CANAL_SONDA"
        return 0
    fi
    validar_inteiro_faixa "Canal de referência (--canal-referencia)" "$CANAL_REFERENCIA" 0 7
    if [ "$CANAL_REFERENCIA" -eq "$CANAL_SONDA" ]; then
        erro_fatal "O canal de referência e o da sonda não podem ser o mesmo (${CANAL_SONDA})."
    fi
    if [ "$REF_EXTERNA" -eq 1 ]; then
        erro_fatal "--ref-externa é para captura de 1 canal (o osciloscópio faz o papel do canal de referência). Tire --canal-referencia ou --ref-externa."
    fi
    NUM_CANAIS_CAPTURA=2
    LISTA_CANAIS="${CANAL_REFERENCIA},${CANAL_SONDA}"
}

# Pergunta o que ainda falta sobre a bancada (só no modo interativo): o canal, o que está sendo calibrado
# (sonda de corrente ou cadeia de tensão) e, se NADA foi dito na linha de comando, se a referência vem de
# um 2º canal, do osciloscópio, de uma amplitude conhecida ou é constante.
obter_canais() {
    local resposta escolha
    [ -n "$CANAL_SONDA" ] && return 0
    local sem_dica=0
    [ "$CANAL_REF_INFORMADO" -eq 0 ] && [ "$REF_EXTERNA" -eq 0 ] && [ -z "$AMPLITUDE" ] && [ "$AMPLITUDE_POR_PONTO" -eq 0 ] && sem_dica=1
    while true; do
        if ! read -r -p "$(printf "%b" "${COR_AMARELO}Canal do ADC (0-7) que vai ser calibrado (onde a saída da sonda ou da cadeia de tensão está ligada): ${COR_RESET}")" CANAL_SONDA; then
            erro_fatal "Informe o canal da sonda com --canal-sonda N (não consegui perguntar: a entrada foi encerrada)."
        fi
        CANAL_SONDA="${CANAL_SONDA// /}"
        [[ "$CANAL_SONDA" =~ ^[0-7]$ ]] && break
        log_erro "Canal inválido: '${CANAL_SONDA}'. Use um número de 0 a 7."
    done
    if [ -z "$GRANDEZA" ]; then
        ler_escolha_menu escolha "  O que está ligado a esse canal?" \
            "Sonda de CORRENTE (garra, TC, Rogowski...) + frontend + ADC" \
            "Cadeia de TENSÃO (divisor/ponta + frontend + ADC)"
        if [ "$escolha" -eq 2 ]; then GRANDEZA="tensao"; else GRANDEZA="corrente"; fi
    fi
    definir_grandeza
    [ "$sem_dica" -eq 1 ] || return 0
    if [ "$GRANDEZA" = "tensao" ]; then
        saida "  Como o script vai saber a tensão real injetada na entrada da cadeia?"
    else
        saida "  Como o script vai saber a corrente real que passa pela sonda?"
    fi
    ler_escolha_menu escolha "  Referência da ${ROTULO_GRANDEZA}:" \
        "Osciloscópio ${ONDE_REFERENCIA}: você digita a leitura RMS a cada ponto (1 canal; vai até taxa/2)" \
        "Amplitude conhecida da senoide (${EXEMPLOS_AMPLITUDE%%,*}...): gravada nos metadados (1 canal; vai até taxa/2)" \
        "Segundo canal do ADC ${ONDE_REFERENCIA} (2 canais; só vai até taxa/4 e o perfil sai sem o filtro do ADC)"
    case "$escolha" in
        1) REF_EXTERNA=1 ;;
        2) ler_amplitude_interativa ;;
        3) ler_valor resposta "Canal do ADC (0-7) da referência (${ONDE_REFERENCIA}): " '^[0-7]$'
           CANAL_REFERENCIA="$resposta"; CANAL_REF_INFORMADO=1 ;;
    esac
}

# Menu interativo, opção "amplitude conhecida": pergunta a amplitude da senoide do gerador e se ela é a mesma
# em todas as frequências. ENTER sem valor = não declarar agora (vira "amplitude constante": ela é
# informada depois, em gerar_perfil_sonda.py --amplitude-referencia).
ler_amplitude_interativa() {
    local entrada limpo motivo igual
    while true; do
        ler_linha entrada "  $(texto_pergunta_amplitude) (ex.: ${EXEMPLOS_AMPLITUDE}); ENTER = informar só depois: "
        [ -z "$entrada" ] && return 0
        if ! limpo="$(normalizar_amplitude "$entrada")"; then
            log_erro "Amplitude inválida: '${entrada}' -- ${limpo}."
        elif motivo="$(amplitude_incompativel "$limpo")"; then
            log_erro "Amplitude inválida: '${entrada}' -- ${motivo}."
        else
            AMPLITUDE="$limpo"
            break
        fi
    done
    ler_confirmacao igual "  O gerador fica com essa MESMA amplitude em todas as frequências?" s
    [ "$igual" = "n" ] && AMPLITUDE_POR_PONTO=1
    return 0
}

validar_inteiro_faixa() {   # nome valor min max
    if ! [[ "$2" =~ $REGEX_INTEIRO_POSITIVO ]] || [ "$2" -lt "$3" ] || [ "$2" -gt "$4" ]; then
        erro_fatal "Valor inválido para $1: '$2'. Use um inteiro entre $3 e $4."
    fi
}

validar_parametros_comuns() {
    validar_inteiro_faixa "Taxa (--taxa)" "$TAXA" 1 500000
    definir_canais
    AMPLITUDE_PONTO="$AMPLITUDE"   # com --amplitude-por-ponto é só o valor inicial: o operador o troca a cada frequência
    validar_inteiro_faixa "Repetições (--repeticoes)" "$REPETICOES" 1 50
    validar_inteiro_faixa "Blocos (--blocos)" "$BLOCOS" 1 1000
    definir_sonda
}

# SONDA_ID (sanitizado, até 31 caracteres: o tamanho do campo no cabeçalho) e PASTA_SONDA a partir de
# SONDA_BRUTA. Idempotente: o aviso de normalização sai uma vez só.
definir_sonda() {
    SONDA_ID="$(sanitizar_id "$SONDA_BRUTA")"
    if [ -z "$SONDA_ID" ]; then
        erro_fatal "O identificador de sonda '${SONDA_BRUTA}' não tem nenhum caractere válido -- use letras, números, '-' ou '_'."
    fi
    if [ "${#SONDA_ID}" -gt 31 ]; then
        erro_fatal "O identificador '${SONDA_ID}' tem ${#SONDA_ID} caracteres; o cabeçalho aceita no máximo 31. Use um nome mais curto."
    fi
    if [ "$SONDA_ID" != "$SONDA_BRUTA" ]; then
        log_aviso "Identificador normalizado para '${SONDA_ID}' (era '${SONDA_BRUTA}'). Use exatamente esse valor no perfil e em --sonda-perfil/adc_tool.py."
        SONDA_BRUTA="$SONDA_ID"
    fi
    PASTA_SONDA="${PASTA_BASE}/${SONDA_ID}"
}

# Para o modo 'novo': faixa de frequências e quantidade de pontos.
validar_faixa_e_pontos() {
    local nyq duracao
    validar_inteiro_faixa "Pontos (--pontos)" "$PONTOS" 2 500
    if ! [[ "$FREQ_MIN" =~ $REGEX_FLOAT_POSITIVO ]] || ! [[ "$FREQ_MAX" =~ $REGEX_FLOAT_POSITIVO ]]; then
        erro_fatal "Frequências inválidas: min='${FREQ_MIN}' max='${FREQ_MAX}'."
    fi
    if ! num_menor "$FREQ_MIN" "$FREQ_MAX"; then
        erro_fatal "A frequência mínima (${FREQ_MIN} Hz) precisa ser menor que a máxima (${FREQ_MAX} Hz)."
    fi
    nyq="$(nyquist_efetiva "$TAXA")"
    if ! num_menor "$FREQ_MAX" "$(fracao_da_nyquist "$TAXA" "$FRACAO_NYQUIST_MAXIMA")"; then
        erro_fatal "A frequência máxima (${FREQ_MAX} Hz) precisa ficar abaixo de 98% da Nyquist efetiva de cada canal (Nyquist = ${nyq} Hz = taxa ${TAXA} Hz / (2 x ${NUM_CANAIS_CAPTURA} canal(is))): encostado nela o tom se confunde com a própria imagem espelhada. Reduza --freq-max ou aumente --taxa."
    fi
    if num_menor "$(fracao_da_nyquist "$TAXA" "$FRACAO_NYQUIST_AVISO")" "$FREQ_MAX"; then
        log_aviso "A frequência máxima (${FREQ_MAX} Hz) passa de 90% da Nyquist efetiva (${nyq} Hz): perto do limite há só 2 a 2,5 amostras por ciclo e qualquer componente acima dele (harmônicas do gerador!) dobra para dentro da banda. Use um gerador de baixa distorção nesses pontos e confira o resultado no osciloscópio."
    fi
    duracao="$(duracao_captura)"
    if num_menor "$(awk -v f="$FREQ_MIN" -v d="$duracao" 'BEGIN { printf "%.1f", f * d }')" 20; then
        log_aviso "Com ${FREQ_MIN} Hz e capturas de ${duracao} s cabem menos de 20 ciclos: a medição de baixa frequência fica imprecisa. Aumente --blocos ou a frequência mínima."
    fi
    if [ "$PONTOS" -lt 10 ]; then
        log_aviso "Só ${PONTOS} pontos: o erro de interpolação do perfil pode passar de 1%. De 15 a 25 pontos costuma bastar (e o script sugere extras no fim)."
    fi
}

mostrar_plano() {
    local duracao total_caps mb nyq
    duracao="$(duracao_captura)"
    total_caps=$(( ${#PLANO_FREQS[@]} * REPETICOES ))
    mb="$(awk -v n="$total_caps" -v b="$BLOCOS" -v spb="$SPB_PADRAO" 'BEGIN { printf "%.0f", n * (1024 + b * spb * 2) / 1048576 + 0.5 }')"
    nyq="$(nyquist_efetiva "$TAXA")"
    titulo_secao "Plano de coleta"
    saida "Sonda:               ${SONDA_ID}"
    saida "Taxa total do ADC:   ${TAXA} Hz  (${NUM_CANAIS_CAPTURA} canal(is) -> $(awk -v t="$TAXA" -v n="$NUM_CANAIS_CAPTURA" 'BEGIN { printf "%.1f", t / n }') Hz por canal; Nyquist efetiva ${nyq} Hz)"
    descrever_bancada
    if [ -n "$FAIXA_ADC_SONDA" ] || [ -n "$FAIXA_ADC_REFERENCIA" ]; then
        saida "Faixa do ADC:        ${FAIXA_ADC_SONDA:+sonda ±$(awk -v v="$FAIXA_ADC_SONDA" 'BEGIN { printf "%g", v / 2 }') V }${FAIXA_ADC_REFERENCIA:+referência ±$(awk -v v="$FAIXA_ADC_REFERENCIA" 'BEGIN { printf "%g", v / 2 }') V}"
    fi
    [ -n "$ATRASO_CS" ] && saida "Esperas do CS:       ${ATRASO_CS} (setup,hold,alto; padrão do firmware 3,1,3)"
    saida "Frequências:         ${#PLANO_FREQS[@]} pontos, de ${PLANO_FREQS[0]} a ${PLANO_FREQS[$((${#PLANO_FREQS[@]} - 1))]} Hz"
    saida "Repetições:          ${REPETICOES} por frequência -> ${total_caps} captura(s)"
    saida "Cada captura:        ${BLOCOS} bloco(s), ~${duracao} s"
    saida "Espaço em disco:     ~${mb} MB em ${PASTA_SONDA}/"
    saida ""
    saida "Frequências (Hz):    ${PLANO_FREQS[*]}"
    saida ""
    avisar_espaco_do_plano "$mb"
}

# Linhas "Grandeza:", "Canais:" e de referência ("Corrente real:"/"Tensão real:") do plano/resumo.
descrever_bancada() {
    local real="Corrente real:      "   # mesma largura dos outros rótulos (21 colunas na tela)
    if [ "$GRANDEZA" = "tensao" ]; then
        real="Tensão real:        "
        saida "Grandeza:            tensão -- a cadeia do canal (divisor/ponta + frontend + ADC)"
    else
        saida "Grandeza:            corrente -- sonda + frontend + ADC (para a cadeia de um canal de tensão: --grandeza tensao)"
    fi
    if [ -n "$CANAL_REFERENCIA" ]; then
        saida "Canais:              sonda = ${CANAL_SONDA} (${ROTULO_GRANDEZA}), referência = ${CANAL_REFERENCIA} (tensão ${ONDE_REFERENCIA})"
        saida "${real} medida pelo canal de referência (gerar_perfil_sonda.py --resistencia-shunt)"
        saida "Atenção:             o canal de referência passa pelo mesmo filtro de ~15 kHz do ADS8688, que se cancela na razão: o perfil NÃO corrige o filtro do ADC"
        return 0
    fi
    saida "Canais:              sonda = ${CANAL_SONDA} (${ROTULO_GRANDEZA}); 1 canal só"
    if [ "$REF_EXTERNA" -eq 1 ]; then
        saida "${real} leitura do osciloscópio a cada ponto (tensão RMS ${ONDE_REFERENCIA}), em ${NOME_REFERENCIA_EXTERNA}"
    elif [ "$AMPLITUDE_POR_PONTO" -eq 1 ]; then
        saida "Referência:          senoide de amplitude conhecida, informada a cada frequência${AMPLITUDE:+ (valor inicial ${AMPLITUDE})}; gravada nos metadados de cada captura"
    elif [ -n "$AMPLITUDE" ]; then
        saida "Referência:          senoide de ${AMPLITUDE} em todas as frequências; gravada nos metadados de cada captura"
    else
        saida "${real} CONSTANTE (mantenha a mesma amplitude de ${ROTULO_GRANDEZA} em todas as frequências)"
    fi
    if { [ -n "$AMPLITUDE" ] || [ "$AMPLITUDE_POR_PONTO" -eq 1 ]; } && [ "$GRANDEZA" = "tensao" ]; then
        saida "                     (em V, no PINO DO ADC, antes do --ganho: a da entrada x a razão do divisor)"
    fi
}

# Avisa (sem impedir) se o plano não cabe no espaço livre. $1 = MB necessários.
avisar_espaco_do_plano() {
    local alvo="$PASTA_SONDA" livre
    while [ ! -d "$alvo" ] && [ "$alvo" != "." ] && [ "$alvo" != "/" ]; do alvo="$(dirname "$alvo")"; done
    livre="$(df -Pm "$alvo" 2>/dev/null | awk 'NR==2 {print $4}')"
    [ -z "${livre:-}" ] && return 0
    if [ "$livre" -lt "$1" ]; then
        log_aviso "O plano precisa de ~$1 MB, mas só há ${livre} MB livres. Libere espaço ou reduza --pontos/--blocos/--repeticoes."
    fi
}

confirmar_inicio() {
    local confirmar
    [ "$ASSUMIR_SIM" -eq 1 ] && return 0
    ler_confirmacao confirmar "Iniciar a coleta?"
    if [ "$confirmar" = "n" ]; then
        log_aviso "Cancelado antes de iniciar. Nada foi gravado."
        exit 0
    fi
}

preparar_pasta() {
    mkdir -p "$PASTA_SONDA" || erro_fatal "Não consegui criar a pasta '${PASTA_SONDA}'."
    inicializar_manifesto
}

# Move a coleta existente da sonda para capturas/_arquivadas/ (nada é apagado).
arquivar_coleta_anterior() {
    local destino
    destino="${PASTA_BASE}/_arquivadas/${SONDA_ID}_$(date +%Y%m%d_%H%M%S)"
    if ! { mkdir -p "${PASTA_BASE}/_arquivadas" && mv "$PASTA_SONDA" "$destino"; }; then
        erro_fatal "Não consegui arquivar '${PASTA_SONDA}' em '${destino}'."
    fi
    log_info "Coleta anterior guardada em ${destino}/"
}

fluxo_novo() {
    [ -z "$TAXA" ] && ler_hz TAXA "Taxa de amostragem TOTAL do ADC (ex.: 102400 ou 102.4k)"
    obter_parametro SONDA_BRUTA "Identificador da sonda (ex.: fluke_i30_sn0001 ou cadeia_tensao)" '^.*[A-Za-z0-9].*$'
    definir_sonda

    # Já existe coleta desta sonda? Evita duplicar pontos sem querer. Decide ANTES das perguntas sobre a
    # bancada e dos padrões deste modo: "retomar" usa as repetições, os blocos e a grandeza do plano salvo.
    local existentes escolha
    existentes="$(capturas_em_disco | grep -c . || true)"
    if [ "$existentes" -gt 0 ]; then
        log_aviso "A pasta '${PASTA_SONDA}' já tem ${existentes} captura(s)."
        if [ "$ASSUMIR_SIM" -eq 1 ]; then
            erro_fatal "Para continuar essa coleta use --modo retomar; para uma coleta nova use outro --sonda."
        fi
        ler_escolha_menu escolha "O que fazer?" \
            "Retomar a coleta anterior (medir só o que falta)" \
            "Arquivar a coleta anterior e começar do zero (nada é apagado)" \
            "Cancelar"
        case "$escolha" in
            1) fluxo_retomar; return ;;
            2) arquivar_coleta_anterior ;;
            3) log_aviso "Cancelado."; exit 0 ;;
        esac
    fi

    obter_canais
    obter_parametro PONTOS "Quantos pontos de frequência coletar" "$REGEX_INTEIRO_POSITIVO" "$PADRAO_PONTOS"
    validar_inteiro_faixa "Taxa (--taxa)" "$TAXA" 1 500000
    definir_canais   # o número de canais define a Nyquist efetiva e, com ela, a frequência máxima padrão
    [ -z "$FREQ_MIN" ] && FREQ_MIN="$PADRAO_FREQ_MIN"
    if [ -z "$FREQ_MAX" ]; then FREQ_MAX="$(freq_max_padrao "$TAXA")"; fi
    [ -z "$REPETICOES" ] && REPETICOES="$PADRAO_REPETICOES"
    [ -z "$BLOCOS" ] && BLOCOS="$PADRAO_BLOCOS"
    validar_parametros_comuns
    validar_faixa_e_pontos

    PLANO_FREQS=()
    local f
    while read -r f; do [ -n "$f" ] && PLANO_FREQS+=("$f"); done < <(calcular_pontos_log "$FREQ_MIN" "$FREQ_MAX" "$PONTOS")
    if [ "${#PLANO_FREQS[@]}" -lt 2 ]; then
        erro_fatal "O arredondamento deixou menos de 2 frequências distintas entre ${FREQ_MIN} e ${FREQ_MAX} Hz. Aumente a faixa."
    fi
    if [ "${#PLANO_FREQS[@]}" -lt "$PONTOS" ]; then
        log_aviso "Pedidos ${PONTOS} pontos, mas só há ${#PLANO_FREQS[@]} frequências inteiras distintas nessa faixa."
    fi
    local nyq
    nyq="$(nyquist_efetiva "$TAXA")"
    if ! num_menor "${PLANO_FREQS[$((${#PLANO_FREQS[@]} - 1))]}" "$(fracao_da_nyquist "$TAXA" "$FRACAO_NYQUIST_MAXIMA")"; then
        erro_fatal "Depois do arredondamento a maior frequência (${PLANO_FREQS[$((${#PLANO_FREQS[@]} - 1))]} Hz) chegou a 98% ou mais da Nyquist efetiva (${nyq} Hz). Reduza --freq-max."
    fi

    mostrar_plano
    confirmar_inicio
    preparar_pasta
    salvar_plano
    verificar_espaco_disco "$PASTA_SONDA"
    coletar_pares "$(pares_pendentes "${PLANO_FREQS[@]}")"
    oferecer_refino "" || true
    instrucoes_finais
}

# Carrega taxa/canais/etc. do plano salvo (se houver) para os modos que continuam uma coleta.
preparar_continuacao() {
    obter_parametro SONDA_BRUTA "Identificador da sonda (ex.: fluke_i30_sn0001 ou cadeia_tensao)" '^.*[A-Za-z0-9].*$'
    definir_sonda
    if [ ! -d "$PASTA_SONDA" ]; then
        erro_fatal "Não encontrei a pasta '${PASTA_SONDA}'. Rode antes uma coleta nova (--modo novo) para essa sonda, ou confira o --sonda e a pasta atual."
    fi
    if ! carregar_plano; then
        log_aviso "Não há '${NOME_PLANO}' em '${PASTA_SONDA}' (coleta feita por uma versão antiga do script?). Vou usar as capturas existentes; informe a taxa."
    fi
    if [ "${#PLANO_FREQS[@]}" -eq 0 ]; then
        local f
        while read -r f; do [ -n "$f" ] && PLANO_FREQS+=("$f"); done < <(frequencias_em_disco)
    fi
    [ -z "$TAXA" ] && ler_hz TAXA "Taxa de amostragem TOTAL do ADC (ex.: 102400 ou 102.4k)"
    obter_canais
    [ -z "$REPETICOES" ] && REPETICOES="$PADRAO_REPETICOES"
    [ -z "$BLOCOS" ] && BLOCOS="$PADRAO_BLOCOS"
    validar_parametros_comuns
    inicializar_manifesto
}

fluxo_retomar() {
    preparar_continuacao
    if [ "${#PLANO_FREQS[@]}" -eq 0 ]; then
        erro_fatal "Não há plano nem capturas em '${PASTA_SONDA}' para retomar."
    fi
    local pares
    pares="$(pares_pendentes "${PLANO_FREQS[@]}")"
    if [ -z "$pares" ]; then
        log_sucesso "A coleta de '${SONDA_ID}' já está completa (todas as ${#PLANO_FREQS[@]} frequências têm captura)."
        oferecer_refino "" || true
        instrucoes_finais
        return
    fi
    mostrar_plano
    log_info "Faltam $(printf '%s\n' "$pares" | grep -c .) captura(s):  $(printf '%s\n' "$pares" | awk '{ print $1 "Hz(rep" $2 ")" }' | tr '\n' ' ')"
    confirmar_inicio
    salvar_plano
    verificar_espaco_disco "$PASTA_SONDA"
    coletar_pares "$pares"
    oferecer_refino "" || true
    instrucoes_finais
}

fluxo_refinar() {
    preparar_continuacao
    local maximo="${PONTOS:-}"
    [ -n "$maximo" ] && validar_inteiro_faixa "Pontos extras (--pontos)" "$maximo" 0 500
    titulo_secao "Refinar a malha"
    mostrar_tabela
    [ -z "$maximo" ] && [ "$ASSUMIR_SIM" -eq 1 ] && maximo=5
    oferecer_refino "$maximo" || true
    instrucoes_finais
}

# Lê uma linha livre (sem tratar vírgula como decimal). Define $1.
ler_linha() {
    local -n _destino="$1"
    if ! read -r -p "$(printf "%b" "${COR_AMARELO}$2${COR_RESET}")" _destino; then
        erro_fatal "Entrada encerrada inesperadamente (EOF em stdin) -- abortando."
    fi
}

# Refaz pontos já capturados (a captura nova substitui a antiga, que vai para descartadas/).
fluxo_refazer() {
    preparar_continuacao
    titulo_secao "Refazer pontos"
    mostrar_tabela
    local lista="$FREQS_ALVO" sugeridas tok pares="" rep
    sugeridas="$(frequencias_para_revisar | tr '\n' ' ')"
    sugeridas="${sugeridas% }"
    if [ -z "$lista" ]; then
        if [ "$ASSUMIR_SIM" -eq 1 ]; then
            lista="$sugeridas"
        else
            ler_linha lista "Quais frequências refazer? (Hz, separadas por espaço ou vírgula${sugeridas:+; ENTER = ${sugeridas}}): "
            [ -z "$lista" ] && lista="$sugeridas"
        fi
    fi
    lista="${lista//,/ }"
    if [ -z "${lista// /}" ]; then
        log_info "Nada a refazer."
        return 0
    fi
    local existentes
    existentes="$(capturas_em_disco)"
    for tok in $lista; do
        if ! [[ "$tok" =~ $REGEX_INTEIRO_POSITIVO ]]; then
            erro_fatal "Frequência inválida em --freqs: '${tok}' (use inteiros em Hz, como aparecem na tabela)."
        fi
        if ! awk -v f="$tok" '$1 == f { achou = 1 } END { exit !achou }' <<< "$existentes"; then
            log_aviso "Não há captura de ${tok} Hz nesta pasta -- ignorando (para medir pontos que faltam use --modo retomar)."
            continue
        fi
        while read -r _ rep; do
            pares+="${tok} ${rep}"$'\n'
        done < <(awk -v f="$tok" '$1 == f' <<< "$existentes")
    done
    pares="${pares%$'\n'}"
    if [ -z "$pares" ]; then
        log_info "Nada a refazer."
        return 0
    fi
    log_info "A captura nova substitui a antiga; a antiga vai para ${PASTA_SONDA}/descartadas/ só depois que a nova for aceita."
    confirmar_inicio
    verificar_espaco_disco "$PASTA_SONDA"
    SUBSTITUIR_EXISTENTES=1
    coletar_pares "$pares"
    SUBSTITUIR_EXISTENTES=0
    instrucoes_finais
}

# Só mostra o estado da coleta (nada é medido).
fluxo_resumo() {
    preparar_continuacao
    titulo_secao "Resumo da coleta de '${SONDA_ID}'"
    saida "Pasta: ${PASTA_SONDA}/    Taxa: ${TAXA} Hz"
    descrever_bancada
    saida ""
    mostrar_tabela
    local rev cand
    rev="$(frequencias_para_revisar | tr '\n' ' ')"
    [ -n "$rev" ] && log_aviso "Capturas aceitas COM erro (considere --modo refazer --freqs): ${rev}"
    cand="$(candidatos_refino "${PLANO_FREQS[@]}")"
    if [ -n "$cand" ]; then
        saida ""
        saida "Pontos extras sugeridos (o ganho muda mais entre estes vizinhos):"
        printf '%s\n' "$cand" | awk '{ printf "  entre %6d e %6d Hz: variação de %5.2f dB  ->  medir em %d Hz\n", $2, $3, $1, $4 }' >&2
    fi
    proximos_passos
}

fluxo_adensar() {
    preparar_continuacao
    local -a existentes=() novas=()
    local f
    while read -r f; do [ -n "$f" ] && existentes+=("$f"); done < <(frequencias_em_disco)
    if [ "${#existentes[@]}" -lt 2 ]; then
        erro_fatal "Há só ${#existentes[@]} frequência(s) capturada(s) em '${PASTA_SONDA}'; preciso de pelo menos 2 para calcular pontos entre elas."
    fi
    while read -r f; do [ -n "$f" ] && novas+=("$f"); done < <(printf '%s\n' "${existentes[@]}" | pontos_medios_geometricos)
    if [ "${#novas[@]}" -eq 0 ]; then
        erro_fatal "As frequências já capturadas estão tão próximas que não há inteiro novo entre elas."
    fi
    local nyq
    nyq="$(nyquist_efetiva "$TAXA")"
    if ! num_menor "${novas[$((${#novas[@]} - 1))]}" "$(fracao_da_nyquist "$TAXA" "$FRACAO_NYQUIST_MAXIMA")"; then
        erro_fatal "Um dos pontos novos (${novas[$((${#novas[@]} - 1))]} Hz) chega a 98% ou mais da Nyquist efetiva (${nyq} Hz) para a taxa ${TAXA} Hz."
    fi
    log_info "${#novas[@]} ponto(s) de adensamento (1 entre cada par adjacente, média geométrica): ${novas[*]} Hz"
    confirmar_inicio
    coletar_extras "${novas[@]}"
    instrucoes_finais
}

# =============================================================================
# 12. Programa principal
# =============================================================================
banner() {
    printf "%b\n" "${COR_NEGRITO}${COR_AZUL}" >&2
    cat >&2 <<'EOF'
╔══════════════════════════════════════════════════════════════╗
║      SH-Analyzer -- coleta de calibração de sonda             ║
╚══════════════════════════════════════════════════════════════╝
EOF
    printf "%b\n" "${COR_RESET}" >&2
}

# Valida --grandeza logo na partida (erro antes de qualquer pergunta). Vazia continua vazia: quer dizer
# "não informada", e o plano salvo (ou a pergunta interativa) decide.
normalizar_parametro_grandeza() {
    [ -n "$GRANDEZA" ] && definir_grandeza
    return 0
}

# Converte --taxa/--freq-min/--freq-max ("102.4k", "5 kHz") em Hz.
normalizar_parametro_hz() {   # nome_da_variavel rotulo
    local -n _v="$1"
    local n
    [ -z "$_v" ] && return 0
    if ! n="$(normalizar_hz "$_v")"; then
        erro_fatal "Valor inválido para $2: '${_v}'. Use algo como 102400, 102.4k ou 5kHz."
    fi
    _v="$n"
}

main() {
    parse_args "$@"
    normalizar_parametro_hz TAXA "--taxa"
    normalizar_parametro_hz FREQ_MIN "--freq-min"
    normalizar_parametro_hz FREQ_MAX "--freq-max"
    normalizar_parametro_amplitude
    normalizar_parametro_grandeza
    banner
    verificar_dependencias
    verificar_root
    verificar_relogio

    if [ -z "$MODO" ]; then
        local escolha
        if [ -n "$TAXA" ] && [ -n "$SONDA_BRUTA" ]; then
            MODO="novo"
        else
            ler_escolha_menu escolha "O que você quer fazer?" \
                "Coleta nova (o script escolhe as frequências)" \
                "Retomar uma coleta interrompida" \
                "Refinar: pontos extras onde o ganho varia mais" \
                "Adensar: 1 ponto entre cada par de frequências já capturadas" \
                "Refazer pontos já capturados" \
                "Resumo: ver o estado da coleta (não mede nada)"
            case "$escolha" in
                1) MODO="novo" ;;
                2) MODO="retomar" ;;
                3) MODO="refinar" ;;
                4) MODO="adensar" ;;
                5) MODO="refazer" ;;
                6) MODO="resumo" ;;
            esac
        fi
    fi

    case "$MODO" in
        novo)    fluxo_novo ;;
        retomar) fluxo_retomar ;;
        refinar) fluxo_refinar ;;
        adensar) fluxo_adensar ;;
        refazer) fluxo_refazer ;;
        resumo)  fluxo_resumo ;;
        *) erro_fatal "Modo desconhecido: '${MODO}'. Use novo, retomar, refinar, adensar, refazer ou resumo." ;;
    esac
}

# Só executa quando chamado como programa (quem faz 'source' neste arquivo, como os testes, recebe só as funções).
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
