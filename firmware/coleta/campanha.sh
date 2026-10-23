#!/bin/bash
# ==============================================================================
# coleta/campanha.sh -- as coletas em lote do coletar.sh: um plano de capturas feito de uma vez, com pausas só para
# mudar a bancada, uma pasta por coleta (as capturas, o log.txt com tudo o que o ler_adc disse e o resumo.csv, uma
# linha por captura) e a retomada de onde parou (--continuar). Chamado pelo coletar.sh:
#
#   ./coletar.sh bancada  [opções]   as varreduras de hardware do T7 (esperas do CS, taxa, grade, SPI)
#   ./coletar.sh cadeia   [opções]   a resposta da cadeia por ondas quadradas (o T3f)
#   ./coletar.sh aliasing [opções]   o mesmo sinal em várias taxas, para o adc_tool.py aliasing
#   ./coletar.sh ruido    [opções]   o piso de ruído com a entrada em curto, nas faixas do ADC
#
# SE A CONEXÃO CAIR: cada captura e a linha dela no resumo.csv são gravadas assim que ela termina, e a coleta não
# morre com o ssh: segue até a próxima pausa (ou até o fim) e para ali. Reconecte e rode o mesmo modo com --continuar.
# ==============================================================================

set -uo pipefail
# shellcheck source-path=SCRIPTDIR source=comum.sh
source "$(dirname "${BASH_SOURCE[0]}")/comum.sh"
cd "$DIR_FIRMWARE" || exit 1

MODO=${1:-}
shift || true
case "$MODO" in
    bancada|cadeia|aliasing|ruido) ;;
    *) falha "modo '$MODO' desconhecido para a campanha (veja ./coletar.sh --help)." ;;
esac

# ------------------------------------------------------------------------------
# Os planos
# ------------------------------------------------------------------------------
BLOCOS=3

# bancada (T7e): as esperas do CS na proporção do padrão antigo (2:1:1), dele ao piso do datasheet (3,1,3).
ESPERAS="200,100,100 150,75,75 100,50,50 75,38,38 50,25,25 40,20,20 30,15,15 20,10,10 15,8,8 10,5,5 8,4,4 6,2,6 4,2,3 3,1,3"
SO_S="100,100,100 50,100,100 20,100,100 10,100,100 6,100,100 3,100,100"       # S sozinho
SO_H="200,50,100 200,20,100 200,10,100 200,5,100 200,2,100 200,1,100"         # H sozinho
ESPERAS_TAXA="200,100,100 100,50,50 50,25,25 20,10,10 10,5,5 6,2,6 3,1,3"
TAXAS_B="125000 160000 200000 250000 312500 400000 500000"                   # todas dividem 200 MHz
SO_A_250K="20,10,20 20,10,5 20,10,3"         # A sozinho, a 250 kS/s (o 20,10,10 já está na varredura da taxa)
DOIS_CANAIS="200,100,100:100000 20,10,10:200000 20,10,10:250000 6,2,6:250000 3,1,3:250000"
CURTO_RAPIDO="200,100,100:125000 20,10,10:250000 6,2,6:250000 3,1,3:250000"
# esperas:taxa:duração em s. Cruzam 2^31 ciclos (10,74 s) 3 vezes (35 s) e 55 vezes (10 min).
LONGAS="200,100,100:100000:35 6,2,6:100000:35 6,2,6:250000:35 6,2,6:250000:600"
# --limite (21/10/2026, esperas 3,1,3 e 312,5 kS/s): taxas em ticks inteiros de 5 ns; "padrao" = sem --atraso-cs.
LIMITE_ESPERAS="3,1,3 6,2,6"
LIMITE_TICKS_DE=660                 # 303,0 kS/s
LIMITE_TICKS_ATE=600                # 333,3 kS/s
PERTO_DO_LIMITE="3,1,3:640 3,1,3:635 3,1,3:630 3,1,3:625 6,2,6:640 6,2,6:650"   # esperas:ticks, 60 s cada
TAXA_PADRAO=312500
# --grade (T7f): taxa:duração em s.
GRADE_LONGAS="312500:60 100000:60 312500:300"     # parte G
GRADE_CARGA="312500:60"                            # parte H: o mesmo, com o ARM enchendo a DDR
GRADE_2CANAIS="312500:60"                          # parte K
GRADE_TICKS_DE=640                                 # parte J: 312,5 kS/s...
GRADE_TICKS_ATE=590                                # ... a 339,0 kS/s, 1 tick por vez
# --spi (T7g): modos do ler_adc --spi.
SPI_FASES="lenta rapido:a rapido:b rapido:c"       # parte P, a 312,5 kS/s
SPI_LONGAS="400000:60"                             # parte S: 1 e 2 canais
SPI_TICKS_DE=520                                   # parte T: 384,6 kS/s...
SPI_TICKS_ATE=460                                  # ... a 434,8 kS/s

# cadeia (T3f): f₁ da quadrada (Hz; 20 Vpp e offset 0, ou f₁:Vpp ou f₁:Vpp:offset em V) e, para cada uma, taxa:SPI.
# Todas múltiplos ímpares de 256 Hz (a de 256 Hz mede a fundamental de cada outra: a costura não depende do modelo);
# em nenhuma um alias de harmônico cai sobre um harmônico ímpar, a 312,5 nem a 400 kS/s. As variantes (1280 Hz em
# 10 Vpp; 6912 e 20736 Hz em 16 Vpp com ±2 V) mudam os códigos que as bordas atravessam: revelam e reduzem o INL.
FASE_F1="256 768 1280 2304 6400 6912 20736 1280:10 6912:16:+2 6912:16:-2 20736:16:+2 20736:16:-2"
FASE_TAXAS="312500:lenta 400000:rapido"
FASE_SEGUNDOS=30

# aliasing: 3 taxas exatas (divisores de 200 MHz) com Nyquist >= 160 kHz. Duas já separam a maioria das imagens; a
# 3ª desfaz as posições em que as duas coincidem (com 400 e 320 kS/s, 360 kHz aparece em 40 kHz nas duas).
ALIASING_TAXAS="400000 390625 320000"
ALIASING_SEGUNDOS=10

# ruido: as três faixas do ADC, com a entrada em curto.
RUIDO_FAIXAS="20.48 10.24 5.12"
RUIDO_TAXAS="400000"
RUIDO_BLOCOS=4

ajuda() {
    case "$MODO" in
        bancada) cat <<'FIM'
Uso: ./coletar.sh bancada [--partes LETRAS | --grade | --spi | --limite | --validar] [opções]

As varreduras de hardware do T7, com um tom de 10,000 kHz, 20 Vpp, High-Z, no canal 1 (faixa ±2,56 V):
  A  as esperas do CS a 100 kS/s, do padrão antigo (200,100,100) ao piso do datasheet (3,1,3)
  B  a taxa (125 a 500 kS/s) contra sete conjuntos de esperas
  D  2 canais (pede o canal 0 em curto)          C  a entrada em curto (pede o gerador fora)
  (padrão: ABDC, ~100 capturas, ~40 min)
  --validar   E: capturas longas que cruzam 2^31 ciclos da PRU (a correção do rebase)
  --limite    L, M, N, Q, R: o limite com o SPI lento, 1 tick por vez, e 10 min no padrão
  --grade     G, H, K, J: a grade de tempo (longas, com o ARM ocupado, 2 canais, o teto 1 tick por vez)
  --spi       P, S, T, U: o SPI rápido (as fases A, B e C, 400 kS/s, o teto, o curto)

Opções
  --faixa F         faixa total do ADC: 20.48, 10.24 ou 5.12 (padrão: 5.12)
  --continuar [P]   retoma a última coleta deste modo (ou a pasta P), pulando o que já foi feito
  --simular         só mostra o plano, o tempo e o espaço
FIM
        ;;
        cadeia) cat <<'FIM'
Uso: ./coletar.sh cadeia [opções]

A resposta da cadeia (magnitude e FASE) por ondas quadradas, sem osciloscópio: os harmônicos ímpares de uma
quadrada simétrica têm fase conhecida entre si. Uma ONDA QUADRADA no canal 1; o script para e pede cada uma:
256, 768, 1280, 2304, 6400, 6912 e 20736 Hz (20 Vpp) e as variantes (1280 Hz em 10 Vpp; 6912 e 20736 Hz em 16 Vpp
com offset de ±2 V), cada uma a 312,5 kS/s (SPI lento) e a 400 kS/s (rápido). 24 capturas, ~12 min de captura.
No computador: scripts/medir_fase.py (o comando sai no fim).

Opções
  --faixa F         faixa total do ADC: 20.48 (a de produção do canal de tensão), 10.24 ou 5.12 (padrão)
  --segundos N      duração de cada captura (padrão: 30)
  --continuar [P]   retoma a última coleta deste modo (ou a pasta P), na mesma faixa
  --simular         só mostra o plano, o tempo e o espaço
FIM
        ;;
        aliasing) cat <<'FIM'
Uso: ./coletar.sh aliasing [opções]

O MESMO sinal em várias taxas, para separar componentes reais de imagens de aliasing (o único anti-aliasing da
cadeia é o filtro de ~15 kHz do ADS8688: a 400 kS/s uma imagem chega a 150 kHz só ~9 dB abaixo de um real). Um
componente real fica na mesma frequência em todas; uma imagem muda de lugar. O sinal tem de ser estável durante a
coleta (as capturas não são simultâneas). No computador: adc_tool.py aliasing (o comando sai no fim).

Opções (padrão: uma boa análise sem nenhuma)
  --taxas LISTA     taxas totais, separadas por vírgula (padrão: 400000,390625,320000: exatas, Nyquist >= 160 kHz;
                    a 3ª desfaz as posições em que as outras duas coincidem)
  --segundos N      duração de cada captura (padrão: 10)
  --canais LISTA    canais (padrão: 1)
  --faixa F         auto (padrão: a menor que comporta o pico, por uma captura curta), 20.48, 10.24 ou 5.12
  --spi MODO        rapido (padrão) ou lenta
  --repeticoes N    repete as taxas N vezes (padrão: 1): confere que a emissão não mudou entre as capturas
  --grandeza C:G    e --sonda C:ID: gravados no cabeçalho, como no ler_adc (a análise usa a sonda)
  --continuar [P]   retoma a última coleta deste modo (ou a pasta P)
  --simular         só mostra o plano, o tempo e o espaço
FIM
        ;;
        ruido) cat <<'FIM'
Uso: ./coletar.sh ruido [opções]

O piso de ruído da cadeia com a entrada em CURTO (o gerador fora), em cada faixa do ADC: o que limita o menor sinal
que dá para ver, em volts e em LSB. Pede o curto antes de começar. No computador: medir_captura.py (o comando sai no
fim).

Opções
  --faixas LISTA    faixas totais, separadas por vírgula (padrão: 20.48,10.24,5.12)
  --taxas LISTA     taxas totais (padrão: 400000)
  --blocos N        blocos por captura (padrão: 4, ~10 s a 400 kS/s)
  --canais LISTA    canais (padrão: 1)
  --spi MODO        rapido (padrão) ou lenta
  --continuar [P]   retoma a última coleta deste modo (ou a pasta P)
  --simular         só mostra o plano, o tempo e o espaço
FIM
        ;;
    esac
}

lista() { echo "${1//,/ }"; }      # "a,b,c" -> "a b c"

PARTES=''
PARTES_PEDIDAS=0
SIMULAR=0
CONTINUAR=''
FAIXA_PEDIDA=''
CANAIS=1
SPI_MODO=rapido
REPETICOES=1
EXTRA=()                            # --grandeza/--sonda, passados ao ler_adc
declare -A EXPLICITA=()             # as opções dadas agora (o --continuar não as troca pelas da coleta retomada)
case "$MODO" in
    bancada) PARTES=ABDC ;;
    cadeia) PARTES=F ;;
    aliasing) PARTES=X; FAIXA_PEDIDA=auto ;;
    ruido) PARTES=Z ;;
esac
so_em() {   # $1 = modos em que a opção vale, $2 = a opção
    case " $1 " in *" $MODO "*) return 0 ;; esac
    falha "$2 não vale no modo $MODO (veja ./coletar.sh $MODO --help)."
}
precisa_valor() { [ "$1" -ge 2 ] || falha "$2 precisa de um valor (veja ./coletar.sh $MODO --help)."; }
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) ajuda; exit 0 ;;
        --simular) SIMULAR=1 ;;
        --continuar)
            if [ $# -ge 2 ] && [ "${2#-}" = "$2" ]; then CONTINUAR=${2%/}; shift; else CONTINUAR=ultima; fi ;;
        --validar) so_em bancada "$1"; PARTES=E; PARTES_PEDIDAS=1 ;;
        --limite) so_em bancada "$1"; PARTES=LMNQR; PARTES_PEDIDAS=1 ;;
        --grade) so_em bancada "$1"; PARTES=GHKJ; PARTES_PEDIDAS=1 ;;
        --spi)
            if [ "$MODO" = bancada ]; then PARTES=PSTU; PARTES_PEDIDAS=1
            else
                precisa_valor $# "$1"; so_em "aliasing ruido" "$1"
                case "$2" in rapido|lenta) SPI_MODO=$2 ;; *) falha "--spi '$2': use rapido ou lenta." ;; esac
                EXPLICITA[spi]=1; shift
            fi ;;
        --partes) so_em bancada "$1"; precisa_valor $# "$1"; PARTES=$2; PARTES_PEDIDAS=1; shift ;;
        --faixa)
            precisa_valor $# "$1"
            if valida_faixa "$2" || { [ "$MODO" = aliasing ] && [ "$2" = auto ]; }; then FAIXA_PEDIDA=$2
            else falha "--faixa '$2': use 20.48 (±10,24 V), 10.24 (±5,12 V) ou 5.12 (±2,56 V)$( [ "$MODO" != aliasing ] || echo ', ou auto')."; fi
            shift ;;
        --faixas)
            so_em ruido "$1"; precisa_valor $# "$1"
            for f in $(lista "$2"); do valida_faixa "$f" || falha "--faixas: '$f' não é uma faixa (20.48, 10.24 ou 5.12)."; done
            RUIDO_FAIXAS=$(lista "$2"); EXPLICITA[faixas]=1; shift ;;
        --taxas)
            so_em "aliasing ruido" "$1"; precisa_valor $# "$1"
            for t in $(lista "$2"); do
                case "$t" in ''|*[!0-9]*) falha "--taxas: '$t' não é uma taxa em Hz." ;; esac
                [ $((CLOCK_PRU / t)) -ge "$TETO_TICKS_RAPIDO" ] || falha "--taxas: $t Hz passa do teto da PRU (~419 kS/s)."
            done
            if [ "$MODO" = aliasing ]; then ALIASING_TAXAS=$(lista "$2"); else RUIDO_TAXAS=$(lista "$2"); fi
            EXPLICITA[taxas]=1; shift ;;
        --segundos)
            so_em "cadeia aliasing" "$1"; precisa_valor $# "$1"
            case "$2" in ''|*[!0-9]*|0) falha "--segundos '$2': use um inteiro positivo." ;; esac
            if [ "$MODO" = cadeia ]; then FASE_SEGUNDOS=$2; else ALIASING_SEGUNDOS=$2; fi
            EXPLICITA[segundos]=1; shift ;;
        --blocos)
            so_em ruido "$1"; precisa_valor $# "$1"
            case "$2" in ''|*[!0-9]*|0) falha "--blocos '$2': use um inteiro positivo." ;; esac
            RUIDO_BLOCOS=$2; EXPLICITA[blocos]=1; shift ;;
        --canais)
            so_em "aliasing ruido" "$1"; precisa_valor $# "$1"
            [[ "$2" =~ ^[0-7](,[0-7])*$ ]] || falha "--canais '$2': canais de 0 a 7 separados por vírgula (ex.: 0,1)."
            CANAIS=$2; EXPLICITA[canais]=1; shift ;;
        --repeticoes)
            so_em aliasing "$1"; precisa_valor $# "$1"
            case "$2" in ''|*[!0-9]*|0) falha "--repeticoes '$2': use um inteiro positivo." ;; esac
            REPETICOES=$2; EXPLICITA[repeticoes]=1; shift ;;
        --grandeza|--sonda) so_em aliasing "$1"; precisa_valor $# "$1"; EXTRA+=("$1" "$2"); EXPLICITA[extra]=1; shift ;;
        *) falha "opção desconhecida: '$1' (veja ./coletar.sh $MODO --help)." ;;
    esac
    shift
done

# A pasta de cada modo e, no --continuar sem pasta, as que ele procura.
case "$MODO" in
    bancada) PREFIXOS="T7e T7f T7g" ;;
    cadeia) PREFIXOS="T3f" ;;
    aliasing) PREFIXOS="ALS" ;;
    ruido) PREFIXOS="RUIDO" ;;
esac

# --continuar: a pasta da coleta a retomar (a mais recente deste modo, se não foi dada) e, na bancada sem --partes,
# as partes dela (do log.txt): retomar a --grade com um --continuar só não pode virar a varredura padrão.
if [ -n "$CONTINUAR" ]; then
    if [ "$CONTINUAR" = ultima ]; then
        filtro=()
        for p in $PREFIXOS; do filtro+=(${filtro[@]+-o} -name "${p}_*"); done
        CONTINUAR=$(find . -maxdepth 1 -type d \( "${filtro[@]}" \) -printf '%T@ %f\n' | sort -n | tail -n 1)
        CONTINUAR=${CONTINUAR#* }
    fi
    [ -n "$CONTINUAR" ] && [ -f "$CONTINUAR/resumo.csv" ] \
        || falha "não achei a coleta a continuar (${CONTINUAR:-nenhuma pasta ${PREFIXOS// /_*, }_* aqui})."
    if [ "$MODO" = bancada ] && [ "$PARTES_PEDIDAS" -eq 0 ] && [ -f "$CONTINUAR/log.txt" ]; then
        anteriores=$(sed -n 's/^== partes \([A-Z]*\),.*/\1/p' "$CONTINUAR/log.txt" | head -n 1)
        PARTES=${anteriores:-$PARTES}
    fi
    # A faixa é a da coleta: misturar faixas numa pasta estragaria a comparação entre as capturas.
    if [ -f "$CONTINUAR/log.txt" ] && [ "$MODO" != ruido ]; then
        faixa_anterior=$(sed -n 's/^== partes .*faixa: --faixa-adc [0-7]:\([0-9.]*\).*/\1/p' "$CONTINUAR/log.txt" | head -n 1)
        if [ -n "$faixa_anterior" ] && [ -n "$FAIXA_PEDIDA" ] && [ "$FAIXA_PEDIDA" != auto ] \
                && [ "$faixa_anterior" != "$FAIXA_PEDIDA" ]; then
            falha "$CONTINUAR foi feita com --faixa $faixa_anterior, não $FAIXA_PEDIDA."
        fi
        if [ -n "$faixa_anterior" ]; then FAIXA_PEDIDA=$faixa_anterior; fi
    fi
fi
# As opções da coleta retomada (a linha "== opções" do log.txt), menos as dadas agora: o plano tem de ser o mesmo.
if [ -n "$CONTINUAR" ] && [ -f "$CONTINUAR/log.txt" ]; then
    for par in $(sed -n 's/^== opções //p' "$CONTINUAR/log.txt" | head -n 1); do
        chave=${par%%=*}
        valor=${par#*=}
        [ -z "${EXPLICITA[$chave]:-}" ] || continue
        case "$chave" in
            taxas) if [ "$MODO" = aliasing ]; then ALIASING_TAXAS=${valor//,/ }; else RUIDO_TAXAS=${valor//,/ }; fi ;;
            segundos) if [ "$MODO" = cadeia ]; then FASE_SEGUNDOS=$valor; else ALIASING_SEGUNDOS=$valor; fi ;;
            canais) CANAIS=$valor ;;
            repeticoes) REPETICOES=$valor ;;
            spi) SPI_MODO=$valor ;;
            faixas) RUIDO_FAIXAS=${valor//,/ } ;;
            blocos) RUIDO_BLOCOS=$valor ;;
            extra) [ -z "${EXPLICITA[extra]:-}" ] && [ -n "$valor" ] && read -ra EXTRA <<< "${valor//;/ }" ;;
        esac
    done
fi
FAIXA_TOTAL=${FAIXA_PEDIDA:-5.12}

# Uma captura por item: parte|esperas|taxa|canais|entrada|duração em s (vazia = blocos)|SPI (vazio = lenta)|faixa
# (vazia = a da coleta)
PLANO=()
tem() { case "$PARTES" in *"$1"*) return 0 ;; esac; return 1; }
if tem A; then
    for cs in $ESPERAS $SO_S $SO_H; do PLANO+=("A|$cs|100000|1|tom"); done
fi
if tem B; then
    for cs in $ESPERAS_TAXA; do for taxa in $TAXAS_B; do PLANO+=("B|$cs|$taxa|1|tom"); done; done
    for cs in $SO_A_250K; do PLANO+=("B|$cs|250000|1|tom"); done
fi
if tem D; then
    for par in $DOIS_CANAIS; do PLANO+=("D|${par%%:*}|${par##*:}|0,1|tom"); done
fi
if tem C; then
    for cs in $ESPERAS; do PLANO+=("C|$cs|100000|1|curto"); done
    for par in $CURTO_RAPIDO; do PLANO+=("C|${par%%:*}|${par##*:}|1|curto"); done
fi
if tem E; then
    for trio in $LONGAS; do
        IFS=: read -r cs taxa segundos <<< "$trio"
        PLANO+=("E|$cs|$taxa|1|tom|$segundos")
    done
fi
if tem L; then
    for cs in $LIMITE_ESPERAS; do
        for ((t = LIMITE_TICKS_DE; t >= LIMITE_TICKS_ATE; t--)); do PLANO+=("L|$cs|$((CLOCK_PRU / t))|1|tom"); done
    done
fi
if tem M; then
    for par in $PERTO_DO_LIMITE; do PLANO+=("M|${par%%:*}|$((CLOCK_PRU / ${par##*:}))|1|tom|60"); done
fi
if tem N; then PLANO+=("N|padrao|$TAXA_PADRAO|1|tom|600"); fi
if tem Q; then PLANO+=("Q|padrao|$TAXA_PADRAO|0,1|tom"); fi
if tem R; then PLANO+=("R|padrao|$TAXA_PADRAO|1|curto" "R|6,2,6|$TAXA_PADRAO|1|curto"); fi
if tem G; then
    for par in $GRADE_LONGAS; do PLANO+=("G|padrao|${par%%:*}|1|tom|${par##*:}"); done
fi
if tem H; then PLANO+=("H|padrao|${GRADE_CARGA%%:*}|1|tom|${GRADE_CARGA##*:}"); fi
if tem K; then PLANO+=("K|padrao|${GRADE_2CANAIS%%:*}|0,1|tom|${GRADE_2CANAIS##*:}"); fi
if tem J; then
    for ((t = GRADE_TICKS_DE; t >= GRADE_TICKS_ATE; t--)); do PLANO+=("J|padrao|$((CLOCK_PRU / t))|1|tom"); done
fi
if tem P; then for spi in $SPI_FASES; do PLANO+=("P|padrao|$TAXA_PADRAO|1|tom||$spi"); done; fi
if tem S; then
    PLANO+=("S|padrao|${SPI_LONGAS%%:*}|1|tom|${SPI_LONGAS##*:}|rapido" "S|padrao|${SPI_LONGAS%%:*}|0,1|tom|${SPI_LONGAS##*:}|rapido")
fi
if tem T; then
    for ((t = SPI_TICKS_DE; t >= SPI_TICKS_ATE; t--)); do PLANO+=("T|padrao|$((CLOCK_PRU / t))|1|tom||rapido"); done
fi
if tem U; then PLANO+=("U|padrao|$TAXA_PADRAO|1|curto||lenta" "U|padrao|${SPI_LONGAS%%:*}|1|curto||rapido"); fi
if tem F; then
    for item_f1 in $FASE_F1; do
        IFS=: read -r f1 vpp off <<< "$item_f1"
        variante="${vpp:+${vpp}Vpp}${off:+${off}V}"
        for par in $FASE_TAXAS; do
            PLANO+=("F|padrao|${par%%:*}|1|quadrada${f1}Hz${variante}|$FASE_SEGUNDOS|${par##*:}")
        done
    done
fi
if tem X; then
    for ((r = 1; r <= REPETICOES; r++)); do
        for taxa in $ALIASING_TAXAS; do
            PLANO+=("X|padrao|$taxa|$CANAIS|sinal$( [ "$REPETICOES" -eq 1 ] || echo "_r$r")|$ALIASING_SEGUNDOS|$SPI_MODO")
        done
    done
fi
if tem Z; then
    for f in $RUIDO_FAIXAS; do
        for taxa in $RUIDO_TAXAS; do PLANO+=("Z|padrao|$taxa|$CANAIS|curto||$SPI_MODO|$f"); done
    done
fi
if [ "$MODO" = bancada ]; then
    case "$PARTES" in
        *[!ABCDEFGHJKLMNPQRSTU]*|'')
            falha "--partes aceita as letras A, B, C, D, E, F, G, H, J, K, L, M, N, P, Q, R, S, T e U (ex.: AB; atalhos: --validar, --limite, --grade, --spi)." ;;
    esac
fi
case "$MODO" in
    cadeia) PREFIXO=T3f ;;
    aliasing) PREFIXO=ALS ;;
    ruido) PREFIXO=RUIDO ;;
    *)  case "$PARTES" in
            *[!GHJK]*) PREFIXO=T7e ;;
            *) PREFIXO=T7f ;;       # só a grade de tempo
        esac
        case "$PARTES" in
            *[!PSTU]*) ;;
            *) PREFIXO=T7g ;;       # só o SPI rápido
        esac
        [ "$PARTES" != F ] || PREFIXO=T3f ;;
esac

blocos_da_parte() {
    case "$1" in
        C|R|U) echo 1 ;;    # só o ruído
        L|J|P|T) echo 2 ;;  # 1 troca de buffer e a taxa medida pelo ARM, em ~7 s por ponto
        Z) echo "$RUIDO_BLOCOS" ;;
        *) echo "$BLOCOS" ;;
    esac
}
nome_da_captura() {   # $1 = item do plano
    local parte cs taxa canais entrada segundos spi faixa
    IFS='|' read -r parte cs taxa canais entrada segundos spi faixa <<< "$1"
    case "$canais" in
        1) canais='' ;;
        0,1) canais=_2canais ;;
        *) canais="_canais${canais//,/-}" ;;
    esac
    echo "${parte}_cs${cs//,/-}_${taxa}_${entrada}${canais}${faixa:+_f${faixa}}${segundos:+_${segundos}s}${spi:+_spi${spi/:/-}}.bin"
}

# --continuar: a mesma pasta; feita = com linha no resumo.csv e com os contadores lidos (uma que o ler_adc não
# terminou, ou que foi cortada no meio, é refeita). As esperas e os canais vêm entre aspas, com vírgulas: a coluna
# amostras_atrasadas é contada a partir do FIM da linha, quantas o cabeçalho tiver depois dela.
declare -A FEITA=()
if [ -n "$CONTINUAR" ]; then
    while read -r arquivo atrasadas; do
        if [ "$atrasadas" != "?" ]; then FEITA[$arquivo]=1; fi
    done < <(awk -F, 'NR == 1 { for (k = 1; k <= NF; k++) if ($k == "amostras_atrasadas") depois = NF - k; next }
                      { print $2, $(NF - depois) }' "$CONTINUAR/resumo.csv")
fi
FALTAM=0
for item in "${PLANO[@]}"; do
    [ -z "${FEITA[$(nome_da_captura "$item")]:-}" ] || continue
    FALTAM=$((FALTAM + 1))
done

TOTAL_S=0
MB_TOTAL=0
declare -A N_PARTE=() S_PARTE=() MB_PARTE=()
ORDEM_PARTES=''
for item in "${PLANO[@]}"; do
    [ -z "${FEITA[$(nome_da_captura "$item")]:-}" ] || continue
    IFS='|' read -r parte cs taxa _ _ segundos spi _ <<< "$item"
    if [ -n "$segundos" ]; then
        s_item=$((segundos + 2))
        mb_item=$((taxa * segundos * 2 / 1048576 + 1))
    else
        b=$(blocos_da_parte "$parte")
        s_item=$(duracao_s "$cs" "$taxa" "$b" "$spi")    # o bloco é de amostras brutas: a duração só depende da taxa total
        mb_item=$((b * AMOSTRAS_POR_BLOCO * 2 / 1048576 + 1))
    fi
    TOTAL_S=$((TOTAL_S + s_item))
    MB_TOTAL=$((MB_TOTAL + mb_item))
    [ -n "${N_PARTE[$parte]:-}" ] || ORDEM_PARTES+=$parte
    N_PARTE[$parte]=$(( ${N_PARTE[$parte]:-0} + 1 ))
    S_PARTE[$parte]=$(( ${S_PARTE[$parte]:-0} + s_item ))
    MB_PARTE[$parte]=$(( ${MB_PARTE[$parte]:-0} + mb_item ))
done
por_parte() {   # "L: 122, ~17 min, ~490 MB · M: ..."
    local p linha=''
    for ((k = 0; k < ${#ORDEM_PARTES}; k++)); do
        p=${ORDEM_PARTES:k:1}
        linha+="${linha:+ · }$p: ${N_PARTE[$p]}, ~$(( (S_PARTE[$p] + 59) / 60 )) min, ~${MB_PARTE[$p]} MB"
    done
    echo "$linha"
}
LIVRE_MB=$(espaco_livre_mb)

case "$PREFIXO" in
    T7f) titulo "T7f: a grade de tempo (período entre amostras)" ;;
    T7g) titulo "T7g: o SPI rápido (~15,4 MHz) e a margem do SDO" ;;
    T3f) titulo "T3f: a fase da cadeia por ondas quadradas" ;;
    ALS) titulo "Aliasing: o mesmo sinal em $(echo "$ALIASING_TAXAS" | wc -w) taxas (canais $CANAIS)" ;;
    RUIDO) titulo "Ruído: a entrada em curto nas faixas $RUIDO_FAIXAS (canais $CANAIS)" ;;
    *) titulo "T7e: esperas do CS e taxa de amostragem" ;;
esac
if [ "$MODO" = bancada ]; then
    printf '    partes %s · %d capturas · ~%d min · ~%d MB (livres: %d MB)\n' "$PARTES" "$FALTAM" $(( (TOTAL_S + 59) / 60 )) "$MB_TOTAL" "$LIVRE_MB"
    [ "${#ORDEM_PARTES}" -lt 2 ] || printf '    %s(%s)%s\n' "$F" "$(por_parte)" "$R"
else
    printf '    %d capturas · ~%d min · ~%d MB (livres: %d MB)\n' "$FALTAM" $(( (TOTAL_S + 59) / 60 )) "$MB_TOTAL" "$LIVRE_MB"
fi
if [ -n "$CONTINUAR" ]; then
    printf '    continuando %s: %d de %d já feitas\n' "$CONTINUAR" $(( ${#PLANO[@]} - FALTAM )) "${#PLANO[@]}"
fi
if [ "$FALTAM" -eq 0 ]; then
    printf '\n    Nada a fazer: todas as capturas do plano já estão feitas.\n\n'
    exit 0
fi
if [ "$SIMULAR" -eq 1 ]; then
    printf '\n'
    for item in "${PLANO[@]}"; do
        [ -z "${FEITA[$(nome_da_captura "$item")]:-}" ] || continue
        IFS='|' read -r parte cs taxa canais entrada segundos spi faixa <<< "$item"
        printf '    %s  cs %-12s %7s Hz  canais %-4s %s%s%s%s\n' "$parte" "$cs" "$taxa" "$canais" "$entrada" \
            "${segundos:+, $segundos s}" "${spi:+, SPI $spi}" "${faixa:+, faixa $faixa}"
    done
    [ "$FAIXA_TOTAL" != auto ] || printf '\n    faixa: automática (uma captura curta em ±10,24 V antes de começar)\n'
    printf '\n    (--simular: nada foi capturado)\n\n'
    exit 0
fi
if [ "$LIVRE_MB" -lt $(( MB_TOTAL + 100 )) ]; then
    printf '  %sErro: faltam %d MB livres aqui. Traga as capturas antigas para o computador e apague-as daqui, ou\n' "$VM" $(( MB_TOTAL + 100 - LIVRE_MB ))
    printf '  rode menos partes de cada vez, trazendo (e apagando daqui) as capturas entre uma e outra:\n'
    printf '  %s.%s\n' "$(por_parte)" "$R"
    echo "  O que já foi feito numa pasta não se perde: --continuar retoma (veja --help)."
    exit 1
fi
[ -x "$LER_ADC" ] || falha "$LER_ADC não existe aqui: rode ./setup.sh antes."

# Partes que pedem uma revisão do firmware (as marcas estão no spi_core.asm e no memoria_pru.h): rodá-las com um
# firmware anterior gasta o tempo à toa. Confere também que o ler_adc e o fw_pru.out foram compilados depois da
# última mudança e que é esse fw_pru.out que está na PRU.
mais_antigo() { [ -f ler_adc.c ] && [ -f ler_adc ] && { [ ler_adc -ot ler_adc.c ] || [ ler_adc -ot memoria_pru.h ]; }; }
if tem N || tem Q || tem R; then
    if [ -f memoria_pru.h ] && ! grep -Eq 'define ATRASO_CS_SETUP_PADRAO +3u' memoria_pru.h; then
        falha "o firmware desta pasta não tem o padrão de esperas 3,1,3 (21/10/2026). No computador:  scripts/BeagleBone_Setup.sh enviar --setup"
    fi
    if mais_antigo; then falha "o ler_adc é mais antigo que o código dele: compile antes (./setup.sh)."; fi
fi
if tem G || tem H || tem J || tem K; then
    if [ -f spi_core.asm ] && ! grep -q 'GRADE EXATA' spi_core.asm; then
        falha "o spi_core.asm desta pasta não tem a grade exata (espera de precisão, 22/10/2026). No computador:  scripts/BeagleBone_Setup.sh enviar --setup"
    fi
    if [ -f spi_core.asm ] && ! grep -q 'QUADRO DE DURAÇÃO FIXA' spi_core.asm; then
        falha "o spi_core.asm desta pasta não tem o quadro de duração fixa (2ª revisão de 22/10/2026): a --grade mediria de novo o firmware do T7f. No computador:  scripts/BeagleBone_Setup.sh enviar --setup"
    fi
    if mais_antigo; then falha "o ler_adc é mais antigo que o código dele: compile antes (./setup.sh)."; fi
fi
if tem P || tem S || tem T || tem U || tem F || tem X || tem Z; then
    if [ -f spi_core.asm ] && ! grep -q 'SPI RÁPIDO' spi_core.asm; then
        falha "o spi_core.asm desta pasta não tem o SPI rápido (protocolo 3, 22/10/2026). No computador:  scripts/BeagleBone_Setup.sh enviar --setup"
    fi
    if mais_antigo; then falha "o ler_adc é mais antigo que o código dele: compile antes (./setup.sh)."; fi
fi
if tem E || tem L || tem M || tem N || tem Q || tem R || tem G || tem H || tem J || tem K || tem P || tem S || tem T \
        || tem U || tem F || tem X || tem Z; then
    if [ -f spi_core.asm ] && ! grep -q 'CORRIGIDO em 21/10/2026' spi_core.asm; then
        falha "o spi_core.asm desta pasta não tem a correção do rebase do contador (21/10/2026). No computador:  scripts/BeagleBone_Setup.sh enviar --setup"
    fi
    if [ -f spi_core.asm ] && { [ ! -f fw_pru.out ] || [ fw_pru.out -ot spi_core.asm ]; }; then
        falha "o fw_pru.out é mais antigo que o spi_core.asm: compile e carregue antes (./setup.sh)."
    fi
    if [ -f /lib/firmware/am335x-pru0-fw ] && [ -f fw_pru.out ] && ! cmp -s fw_pru.out /lib/firmware/am335x-pru0-fw; then
        falha "a PRU está com outro firmware, não o fw_pru.out desta pasta: rode ./setup.sh antes."
    fi
fi

preparar_sudo

PASTA=${CONTINUAR:-${PREFIXO}_$(date +%Y-%m-%d_%H%M)}
mkdir -p "$PASTA"
LOG="$PASTA/log.txt"
RESUMO="$PASTA/resumo.csv"
if [ -z "$CONTINUAR" ]; then
    echo "parte,arquivo,esperas_cs,taxa_pedida_hz,canais,entrada,amostras_atrasadas,buffers_sobrescritos,quadros_sdo_ruido,taxa_arm_hz,desvio_arm_pct,codigo_saida,folga_ciclos,atraso_max_ciclos,spi,divergencias_a,divergencias_c" > "$RESUMO"
fi
# 12 numa varredura retomada de antes de 22/10/2026; 14 antes do SPI rápido (2ª revisão de 22/10/2026)
COLUNAS_RESUMO=$(head -n 1 "$RESUMO" | awk -F, '{ print NF }')

# A faixa automática (aliasing): uma captura curta em ±10,24 V e a menor faixa em que o pico cabe.
if [ "$FAIXA_TOTAL" = auto ]; then
    printf '    faixa automática: '
    if FAIXA_TOTAL=$(LOG="$LOG" faixa_automatica "$PASTA/faixa_automatica.bin" "$CANAIS" "${ALIASING_TAXAS%% *}"); then
        printf '%s V (±%s V), pela captura curta em %s/faixa_automatica.bin\n' "$FAIXA_TOTAL" \
            "$(LC_ALL=C awk -v f="$FAIXA_TOTAL" 'BEGIN { printf "%.2f", f / 2 }')" "$PASTA"
    else
        FAIXA_TOTAL=20.48
        printf '%sa captura curta falhou (veja o log.txt): seguindo em 20.48 (±10,24 V)%s\n' "$AM" "$R"
    fi
fi
{
    echo "== $(date '+%Y-%m-%d %H:%M:%S %Z') · $(uname -n) · firmware $(cat VERSAO 2>/dev/null || echo '?')$( [ -z "$CONTINUAR" ] || echo ' · CONTINUAÇÃO')"
    echo "== partes $PARTES, $FALTAM de ${#PLANO[@]} capturas, $BLOCOS blocos cada (1 na parte C), faixa: $(argumento_de_faixa "$CANAIS" "$FAIXA_TOTAL")"
    case "$MODO" in
        aliasing) extra="${EXTRA[*]+${EXTRA[*]}}"
                  echo "== opções taxas=${ALIASING_TAXAS// /,} segundos=$ALIASING_SEGUNDOS canais=$CANAIS repeticoes=$REPETICOES spi=$SPI_MODO extra=${extra// /;}" ;;
        ruido) echo "== opções taxas=${RUIDO_TAXAS// /,} faixas=${RUIDO_FAIXAS// /,} blocos=$RUIDO_BLOCOS canais=$CANAIS spi=$SPI_MODO" ;;
        cadeia) echo "== opções segundos=$FASE_SEGUNDOS" ;;
    esac
} >> "$LOG"
printf '    pasta: %s\n' "$PASTA"

# Ctrl+C para (e guarda o que já foi feito). A queda da conexão (SIGHUP) não: as capturas seguem até a próxima
# pausa, onde a falta do terminal faz a coleta parar (o ler_adc herda o HUP ignorado e termina a captura dele).
interrompido=''
trap 'interrompido="com Ctrl+C"' INT
trap '' HUP

pausa() {   # $1 = o que mudar na bancada. Devolve 0 = seguir, 1 = pular a parte, 2 = sem terminal (parar)
    printf '\n  %s▸ Mude a bancada:%s %s\n' "$N$AM" "$R" "$1"
    printf '    Enter quando estiver pronto, ou p e Enter para pular esta parte: '
    local resposta=''
    if ! read -r resposta; then
        echo "== pausa: $1 -> sem terminal (a conexão caiu?): parado aqui" >> "$LOG"
        return 2
    fi
    echo "== pausa: $1 -> '${resposta}'" >> "$LOG"
    [ "$resposta" != p ] || return 1
}

pular_parte=''
parte_anterior=''
entrada_anterior=''
i=0
for item in "${PLANO[@]}"; do
    [ -z "$interrompido" ] || break
    i=$((i + 1))
    nome=$(nome_da_captura "$item")
    [ -z "${FEITA[$nome]:-}" ] || continue
    IFS='|' read -r parte cs taxa canais entrada segundos spi faixa_item <<< "$item"
    if [ "$parte" != "$parte_anterior" ]; then
        parte_anterior=$parte
        pular_parte=''
        resposta=0
        case "$parte" in
            A) secao "A: as esperas a 100 kS/s, com o tom" ;;
            B) secao "B: a taxa contra as esperas, com o tom" ;;
            E) secao "E: capturas longas, com o tom (cruzam 2^31 ciclos da PRU várias vezes)" ;;
            L) secao "L: o limite, de 303 a 333 kS/s em passos de 1 tick (5 ns), com o tom" ;;
            M) secao "M: 60 s perto do limite, com o tom" ;;
            N) secao "N: 10 min no padrão (312,5 kS/s, esperas 3,1,3), com o tom" ;;
            G) secao "G: a grade de tempo no padrão, com o tom (capturas longas)" ;;
            H) secao "H: a mesma, com o ARM ocupado (dd enchendo a DDR)" ;;
            K) secao "K: 2 canais no padrão" ;;
            J) secao "J: o teto com período constante, de 312,5 a 339,0 kS/s, 1 tick por vez" ;;
            P) secao "P: o SPI padrão e o rápido (fases A, B e C) a 312,5 kS/s, com o tom" ;;
            S) secao "S: 60 s a 400 kS/s com o SPI rápido, com 1 e 2 canais" ;;
            T) secao "T: o teto do SPI rápido, de 384,6 a 434,8 kS/s, 1 tick por vez" ;;
            U) pausa "gerador FORA e a entrada do canal 1 em CURTO (o divisor ligado ao retorno)." || resposta=$?
               secao "U: a entrada em curto, com o SPI padrão e o rápido" ;;
            F) secao "F: a fase da cadeia, ${FASE_SEGUNDOS} s com cada quadrada a 312,5 kS/s e a 400 kS/s (SPI rápido)" ;;
            X) secao "o mesmo sinal, ${ALIASING_SEGUNDOS} s em cada taxa ($ALIASING_TAXAS), faixa $FAIXA_TOTAL V" ;;
            Z) pausa "gerador FORA e a entrada do(s) canal(is) $CANAIS em CURTO (o divisor ligado ao retorno)." || resposta=$?
               secao "a entrada em curto, $RUIDO_BLOCOS blocos em cada faixa" ;;
            D|Q) pausa "tom de 10 kHz no canal 1 (como até agora) e a entrada do canal 0 em CURTO." || resposta=$?
               secao "D: 2 canais" ;;
            C|R) pausa "gerador FORA e a entrada do canal 1 em CURTO (o divisor ligado ao retorno)." || resposta=$?
               secao "C: a entrada em curto" ;;
        esac
        case "$resposta" in
            1) pular_parte=$parte ;;
            2) interrompido="sem terminal na pausa da parte $parte"; break ;;
        esac
    fi
    if [ "$pular_parte" = "$parte" ]; then continue; fi
    # Uma quadrada nova: o gerador muda de frequência (a mesma ligação do tom, no canal 1).
    if [ "$entrada" != "$entrada_anterior" ]; then
        entrada_anterior=$entrada
        case "$entrada" in
            quadrada*)
                f1=${entrada#quadrada}
                f1=${f1%%Hz*}
                resto=${entrada#*Hz}
                vpp=''
                off=''
                case "$resto" in *Vpp*) vpp=${resto%%Vpp*}; off=${resto#*Vpp} ;; esac
                off=${off%V}
                resposta=0
                pausa "gerador: ONDA QUADRADA de $f1 Hz, ${vpp:-20} Vpp, High-Z, offset ${off:-0} V, duty 50 % (simetria), no canal 1." \
                    || resposta=$?
                case "$resposta" in
                    1) pular_parte=$parte; continue ;;
                    2) interrompido="sem terminal na pausa da quadrada de $f1 Hz"; break ;;
                esac ;;
        esac
    fi

    printf '    %s[%3d/%d]%s cs %-12s %7s Hz %-9s ' "$F" "$i" "${#PLANO[@]}" "$R" "$cs" "$taxa" \
        "$( [ "$canais" = 1 ] || echo "${canais} " )${faixa_item:+±$(LC_ALL=C awk -v f="$faixa_item" 'BEGIN { printf "%g", f / 2 }') V}"
    echo "== [$i/${#PLANO[@]}] $nome" >> "$LOG"
    if [ -n "$segundos" ]; then tamanho=(--duracao "${segundos}s"); else tamanho=(--blocos "$(blocos_da_parte "$parte")"); fi
    esperas=(--atraso-cs "$cs")
    [ "$cs" != padrao ] || esperas=()      # o padrão do firmware, como numa captura qualquer
    # Sem SPI no item, o lento: as campanhas do T7 foram desenhadas com o SPI de antes de 22/10/2026 (o padrão do
    # ler_adc passou a ser o rápido), e refazê-las tem de medir a mesma coisa.
    modo_spi=(--spi "${spi:-lenta}")
    carga=''
    if [ "$parte" = H ]; then              # a DDR e a CPU do ARM ocupadas durante a captura (o ler_adc tem prioridade)
        nice -n 10 dd if=/dev/zero of=/dev/null bs=4M 2>/dev/null &
        carga=$!
    fi
    descricao=()
    case "$entrada" in quadrada*) descricao=(-d "quadrada f=${entrada#quadrada}") ;; esac     # o medir_fase.py lê a f₁
    read -ra faixa <<< "$(argumento_de_faixa "$canais" "${faixa_item:-$FAIXA_TOTAL}")"
    # --forcar-taxa: o ler_adc recusa taxas acima do teto da PRU, e as varreduras do T7 passam dele de propósito.
    forcar=()
    [ "$MODO" != bancada ] || forcar=(--forcar-taxa)
    saida=$(sudo "$LER_ADC" "$taxa" "$canais" "${tamanho[@]}" "${esperas[@]}" "${modo_spi[@]}" "${forcar[@]}" "${faixa[@]}" \
                 "${EXTRA[@]}" -o "$PASTA/$nome" \
                 -t "$PREFIXO $parte cs $cs $taxa $entrada${segundos:+ ${segundos}s}${spi:+ spi $spi}${faixa_item:+ f$faixa_item}" \
                 "${descricao[@]}" 2>&1 </dev/null)
    codigo=$?
    if [ -n "$carga" ]; then kill "$carga" 2>/dev/null; wait "$carga" 2>/dev/null; fi
    printf '%s\n' "$saida" >> "$LOG"

    ler_resumo "$saida"
    linha="$parte,$nome,\"$cs\",$taxa,\"$canais\",$entrada,$atrasadas,$sobrescritos,$sdo,$arm,$desvio,$codigo"
    [ "$COLUNAS_RESUMO" -le 12 ] || linha+=",$folga,$pior"
    [ "$COLUNAS_RESUMO" -le 14 ] || linha+=",${spi:-lenta},${div_a:-},${div_c:-}"
    echo "$linha" >> "$RESUMO"

    if [ "$codigo" -eq 4 ]; then
        printf '%s✗ o ADC não respondeu (a placa de aquisição sem alimentação?): parado%s\n' "$VM" "$R"
        interrompido="ADC sem resposta (a placa de aquisição está alimentada pela fonte de 5 V do conector?)"
        break
    elif [ "$codigo" -ne 0 ] && [ "$atrasadas" = "?" ]; then
        printf '%s✗ o ler_adc falhou (código %d; veja o log.txt)%s\n' "$VM" "$codigo" "$R"
    elif [ "$atrasadas $sobrescritos $sdo" = "0 0 0" ]; then
        printf '%s✓%s %s%sARM %s Hz (%s %%)\n' "$V" "$R" "${folga:+folga $folga ciclos · }" \
            "${div_a:+divergências A $div_a, C $div_c · }" "$arm" "$desvio"
    else
        printf '%s! atrasadas %s%s · sobrescritos %s · SDO %s%s · ARM %s Hz\n' "$AM" "$atrasadas" "${pior:+ (até $pior ciclos)}" \
            "$sobrescritos" "$sdo" "$R" "$arm"
    fi
done

echo "== fim $(date '+%Y-%m-%d %H:%M:%S %Z')${interrompido:+ (parado: $interrompido)}" >> "$LOG"
if [ -n "$interrompido" ]; then
    printf '\n  %s◆ Parado%s (%s): %s\n' "$N$AM" "$R" "$interrompido" "$PASTA"
    echo "    O que foi feito está salvo. Para seguir daqui:  ./coletar.sh $MODO --continuar"
else
    printf '\n  %s◆ Pronto%s: %s\n' "$N" "$R" "$PASTA"
fi
echo "    No computador:  scripts/BeagleBone_Setup.sh trazer '${PREFIXO}_*' \$DIA"
case "$PREFIXO" in
    T3f) echo "    E a análise:    uv run scripts/medir_fase.py \$DIA/${PASTA}/F_*.bin --csv \$DIA/${PASTA}/fase.csv --plot \$DIA/${PASTA}/bode.png" ;;
    ALS)
        for ((r = 1; r <= REPETICOES; r++)); do
            sufixo=$( [ "$REPETICOES" -eq 1 ] || echo "_r$r")
            echo "    E a análise:    uv run scripts/adc_tool.py aliasing \$DIA/${PASTA}/X_*_sinal${sufixo}_*.bin --csv \$DIA/${PASTA}/aliasing${sufixo}.csv"
        done ;;
    RUIDO) echo "    E a análise:    uv run scripts/medir_captura.py \$DIA/${PASTA}/Z_*.bin --sem-tom --sem-correcao-sonda --ganho 1 --inicio 100 --csv \$DIA/${PASTA}/ruido.csv" ;;
esac
echo
