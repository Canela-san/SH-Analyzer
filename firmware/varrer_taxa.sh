#!/bin/bash
# ==============================================================================
# varrer_taxa.sh -- o T7e inteiro numa tacada: as esperas do CS e a taxa de amostragem, sem decisões no meio.
# (roda NA BEAGLEBONE, na pasta do firmware, ao lado do ler_adc)
# ==============================================================================
#
# PARA QUE SERVE
#   Achar a taxa máxima que o ADS8688 aguenta reduzindo as três esperas do CS (--atraso-cs S,H,A, em iterações de
#   10 ns: S = CS descendo -> 1º clock, H = último clock -> CS subindo, A = CS alto entre amostras). Em vez de
#   escolher os conjuntos aos poucos, captura TODOS os do plano abaixo, grava cada saída do ler_adc e um resumo, e
#   a escolha (as esperas e a taxa de trabalho) sai depois, na análise das capturas no computador.
#
# O PLANO (sinal: senoide de 10,000 kHz, 20 Vpp, High-Z, no canal 1; faixa de ±2,56 V; 3 blocos por captura)
#   A. com o tom, a 100 kS/s: as esperas do padrão (200,100,100) ao piso do datasheet (3,1,3), em passos pequenos,
#      e cada espera sozinha (S com H e A no padrão; H com S e A no padrão). A 100 kS/s o A não faz diferença: o
#      CS fica alto até a próxima amostra.
#   B. com o tom: a taxa, de 125 a 500 kS/s, para sete conjuntos de esperas, e o A sozinho a 250 kS/s (onde o
#      quadro enche o período e o A passa a contar).
#   D. com o tom no canal 1 e o canal 0 em curto: 2 canais (diafonia e atraso entre canais). Pede para você
#      mudar a bancada; dá para pular.
#   C. com a entrada do canal 1 em curto (gerador fora): o ruído em cada conjunto a 100 kS/s e em alguns a
#      250 kS/s. Pede para você mudar a bancada; dá para pular.
#   Todas com 3 blocos (2 trocas de buffer e a taxa medida pelo ARM), menos as da C (1 bloco: só o ruído).
#   ~100 capturas, ~40 min e ~650 MB (o script confere o espaço antes de começar).
#   E. (só com --partes E) a validação do firmware corrigido em 21/10/2026: capturas longas, com o tom, que cruzam
#      2^31 ciclos da PRU (10,74 s) várias vezes -- 35 s com as esperas padrão e com 6,2,6 a 100 kS/s, 35 s com
#      6,2,6 a 250 kS/s e 10 min com 6,2,6 a 250 kS/s (o T7c). ~12 min e ~330 MB.
#
# A GRADE DE TEMPO (--grade, o T7f; pede o firmware de 22/10/2026 com o quadro de duração fixa e a troca de buffer
# espalhada, a 2ª revisão daquele dia). O mesmo tom
# de 10 kHz, no padrão (312,5 kS/s, esperas 3,1,3), sem mudar nada na bancada:
#   G. 60 s a 312,5 kS/s, 60 s a 100 kS/s (para comparar com as capturas de 21/10, que tinham ~8,4 ns de jitter) e
#      5 min a 312,5 kS/s (~90 trocas de buffer e ~28 rebases do contador).
#   H. 60 s a 312,5 kS/s com o ARM ocupado (um 'dd' enchendo a DDR, em segundo plano): a folga da PRU e o ler_adc
#      sob carga.
#   K. 60 s com 2 canais a 312,5 kS/s no total (o tom no canal 1; o canal 0 como estiver).
#   J. o teto com período constante: de 640 a 590 ticks (312,5 a 339,0 kS/s), 1 tick por vez, 2 blocos cada. A
#      folga da PRU já diz onde ele está; aqui ele é conferido captura a captura. (Até a 1ª revisão de 22/10, o
#      teto era ~315 kS/s e todas atrasavam abaixo de 611 ticks; com o quadro fixo, o previsto é ~327 kS/s.)
#   56 capturas, ~16 min e ~540 MB. Cada linha do resumo.csv traz a folga (folga_ciclos) e o pior atraso.
#
# O SPI RÁPIDO (--spi, o T7g; pede o firmware com o SPI rápido, protocolo 3, 22/10/2026). O mesmo tom de 10 kHz. O
# SPI rápido tem bits de 13 ciclos (~15,4 MHz, contra ~10,7) e lê cada bit em 3 instantes (fases A, B e C: 60, 75 e
# 90 ns depois da borda do SCLK que o lança), contando os quadros em que A ou C discordam de B. É a margem de tempo
# do SDO, medida pela PRU, sem osciloscópio:
#   P. a 312,5 kS/s, 2 blocos: o SPI padrão e o rápido gravando a fase A, a B e a C. O mesmo SINAD e nenhuma
#      divergência na B = o rápido lê o mesmo dado que o padrão.
#   S. 60 s a 400 kS/s com o rápido (fase B), com 1 canal e com 2 (200 kS/s por canal).
#   T. o teto com período constante do rápido: de 520 a 460 ticks (384,6 a 434,8 kS/s), 1 tick por vez, 2 blocos.
#   U. (pede o canal 1 em curto) o ruído a 312,5 kS/s com o padrão e a 400 kS/s com o rápido.
#   69 capturas, ~11 min e ~370 MB. O resumo.csv traz também o modo do SPI e as divergências.
#
# USO (na BeagleBone, na pasta do firmware; de preferência no terminal do 'scripts/BeagleBone_Setup.sh ssh'):
#   ./varrer_taxa.sh              # tudo, com as pausas para mudar a bancada
#   ./varrer_taxa.sh --simular    # só mostra o plano, o tempo e o espaço
#   ./varrer_taxa.sh --partes AB  # só algumas partes (A, B, D e C, nesta ordem; E só se pedida)
#   ./varrer_taxa.sh --validar    # só a validação do firmware corrigido (a parte E): numa pasta nova, sem
#                                 # precisar de nenhuma varredura anterior (= --partes E)
#   ./varrer_taxa.sh --grade      # a grade de tempo (= --partes GHKJ), numa pasta T7f_<data>_<hora>/
#   ./varrer_taxa.sh --spi        # o SPI rápido (= --partes PSTU), numa pasta T7g_<data>_<hora>/
#   ./varrer_taxa.sh --continuar  # retoma a última varredura (ou --continuar T7e_...): pula o que já foi feito
#                                 # (as partes são as da varredura retomada, lidas do log.txt dela)
#
# SE A CONEXÃO CAIR: cada captura e a linha dela no resumo.csv são gravadas assim que ela termina, e a varredura
# não morre com o ssh: segue até a próxima pausa (ou até o fim) e para ali. Reconecte e rode --continuar.
#
# SAÍDA: a pasta T7e_<data>_<hora>/ (T7f_ na --grade) com as capturas (<parte>_cs<S>-<H>-<A>_<taxa>_<entrada>.bin),
# o log.txt (tudo o que o ler_adc escreveu) e o resumo.csv (uma linha por captura: contadores de integridade, taxa
# medida pelo ARM e, com o firmware de 22/10/2026, a folga da grade de tempo).
# No computador:  scripts/BeagleBone_Setup.sh trazer 'T7e_*' $DIA   (ou 'T7f_*')
# ==============================================================================

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

LER_ADC=./ler_adc
BLOCOS=3
FAIXA="--faixa-adc 1:5.12"
FAIXA_2CANAIS="--faixa-adc 0:5.12,1:5.12"
CLOCK_PRU=200000000
AMOSTRAS_POR_BLOCO=1048576

# ------------------------------------------------------------------------------
# O plano
# ------------------------------------------------------------------------------
# As esperas na proporção do padrão (2:1:1), do padrão ao piso do datasheet (30/10/30 ns = 3,1,3).
ESPERAS="200,100,100 150,75,75 100,50,50 75,38,38 50,25,25 40,20,20 30,15,15 20,10,10 15,8,8 10,5,5 8,4,4 6,2,6 4,2,3 3,1,3"
SO_S="100,100,100 50,100,100 20,100,100 10,100,100 6,100,100 3,100,100"       # S sozinho
SO_H="200,50,100 200,20,100 200,10,100 200,5,100 200,2,100 200,1,100"         # H sozinho
ESPERAS_TAXA="200,100,100 100,50,50 50,25,25 20,10,10 10,5,5 6,2,6 3,1,3"
TAXAS="125000 160000 200000 250000 312500 400000 500000"                     # todas dividem 200 MHz
SO_A_250K="20,10,20 20,10,5 20,10,3"         # A sozinho, a 250 kS/s (o 20,10,10 já está na varredura da taxa)
DOIS_CANAIS="200,100,100:100000 20,10,10:200000 20,10,10:250000 6,2,6:250000 3,1,3:250000"
CURTO_RAPIDO="200,100,100:125000 20,10,10:250000 6,2,6:250000 3,1,3:250000"
# esperas:taxa:duração em s. Cruzam 2^31 ciclos (10,74 s) 3 vezes (35 s) e 55 vezes (10 min).
LONGAS="200,100,100:100000:35 6,2,6:100000:35 6,2,6:250000:35 6,2,6:250000:600"

# A campanha do limite (--limite), com o padrão de 21/10/2026 (esperas 3,1,3 e 312,5 kS/s). As taxas vêm em ticks
# inteiros de 5 ns (taxa = 200 MHz ÷ ticks: sempre a que a PRU gera, sem arredondamento); "padrao" = sem --atraso-cs.
LIMITE_ESPERAS="3,1,3 6,2,6"
LIMITE_TICKS_DE=660                 # 303,0 kS/s
LIMITE_TICKS_ATE=600                # 333,3 kS/s (acima do teto medido em 21/10: 326 kS/s com 3,1,3)
PERTO_DO_LIMITE="3,1,3:640 3,1,3:635 3,1,3:630 3,1,3:625 6,2,6:640 6,2,6:650"   # esperas:ticks, 60 s cada
TAXA_PADRAO=312500

# A grade de tempo (--grade, firmware de 22/10/2026), no padrão: taxa:duração em s.
GRADE_LONGAS="312500:60 100000:60 312500:300"     # parte G
GRADE_CARGA="312500:60"                            # parte H: o mesmo, com o ARM enchendo a DDR
GRADE_2CANAIS="312500:60"                          # parte K
GRADE_TICKS_DE=640                                 # parte J: 312,5 kS/s...
GRADE_TICKS_ATE=590                                # ... a 339,0 kS/s, 1 tick por vez

# O SPI rápido (--spi, firmware com o protocolo 3): modos do ler_adc --spi.
SPI_FASES="padrao rapido:a rapido:b rapido:c"      # parte P, a 312,5 kS/s
SPI_LONGAS="400000:60"                             # parte S: 1 e 2 canais
SPI_TICKS_DE=520                                   # parte T: 384,6 kS/s...
SPI_TICKS_ATE=460                                  # ... a 434,8 kS/s (o teto previsto é ~418)

PARTES=ABDC
PARTES_PEDIDAS=0
SIMULAR=0
CONTINUAR=''
while [ $# -gt 0 ]; do
    case "$1" in
        --simular) SIMULAR=1 ;;
        --validar) PARTES=E; PARTES_PEDIDAS=1 ;;
        --limite) PARTES=LMNQR; PARTES_PEDIDAS=1 ;;
        --grade) PARTES=GHKJ; PARTES_PEDIDAS=1 ;;
        --spi) PARTES=PSTU; PARTES_PEDIDAS=1 ;;
        --continuar)
            if [ $# -ge 2 ] && [ "${2#-}" = "$2" ]; then CONTINUAR=${2%/}; shift; else CONTINUAR=ultima; fi ;;
        --partes) [ $# -ge 2 ] || { echo "Erro: --partes precisa de letras (ex.: AB)." >&2; exit 1; }
                  PARTES=$2; PARTES_PEDIDAS=1; shift ;;
        -h|--help) sed -n '/^# PARA QUE/,/^# ====/p' "${BASH_SOURCE[0]}" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
        *) echo "Erro: opção desconhecida: '$1' (veja --help)." >&2; exit 1 ;;
    esac
    shift
done

# --continuar: a pasta da varredura a retomar (a mais recente, se não foi dada) e, sem --partes/--grade/..., as
# partes dela, do log.txt -- retomar a --grade com um --continuar só não pode virar a varredura padrão.
if [ -n "$CONTINUAR" ]; then
    if [ "$CONTINUAR" = ultima ]; then
        CONTINUAR=$(find . -maxdepth 1 -type d \( -name 'T7e_*' -o -name 'T7f_*' -o -name 'T7g_*' \) -printf '%T@ %f\n' \
                    | sort -n | tail -n 1)
        CONTINUAR=${CONTINUAR#* }
    fi
    [ -n "$CONTINUAR" ] && [ -f "$CONTINUAR/resumo.csv" ] \
        || { echo "Erro: não achei a varredura a continuar (${CONTINUAR:-nenhuma pasta T7e_*, T7f_* ou T7g_* aqui})." >&2; exit 1; }
    if [ "$PARTES_PEDIDAS" -eq 0 ] && [ -f "$CONTINUAR/log.txt" ]; then
        anteriores=$(sed -n 's/^== partes \([A-Z]*\),.*/\1/p' "$CONTINUAR/log.txt" | head -n 1)
        PARTES=${anteriores:-$PARTES}
    fi
fi

# Uma captura por linha: parte|esperas|taxa|canais|entrada|duração em s (vazia = blocos)|modo do SPI (vazio = sem --spi)
PLANO=()
tem() { case "$PARTES" in *"$1"*) return 0 ;; esac; return 1; }
if tem A; then
    for cs in $ESPERAS $SO_S $SO_H; do PLANO+=("A|$cs|100000|1|tom"); done
fi
if tem B; then
    for cs in $ESPERAS_TAXA; do for taxa in $TAXAS; do PLANO+=("B|$cs|$taxa|1|tom"); done; done
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
        for ((t = LIMITE_TICKS_DE; t >= LIMITE_TICKS_ATE; t--)); do PLANO+=("L|$cs|$((200000000 / t))|1|tom"); done
    done
fi
if tem M; then
    for par in $PERTO_DO_LIMITE; do PLANO+=("M|${par%%:*}|$((200000000 / ${par##*:}))|1|tom|60"); done
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
    for ((t = GRADE_TICKS_DE; t >= GRADE_TICKS_ATE; t--)); do PLANO+=("J|padrao|$((200000000 / t))|1|tom"); done
fi
if tem P; then for spi in $SPI_FASES; do PLANO+=("P|padrao|$TAXA_PADRAO|1|tom||$spi"); done; fi
if tem S; then
    PLANO+=("S|padrao|${SPI_LONGAS%%:*}|1|tom|${SPI_LONGAS##*:}|rapido" "S|padrao|${SPI_LONGAS%%:*}|0,1|tom|${SPI_LONGAS##*:}|rapido")
fi
if tem T; then
    for ((t = SPI_TICKS_DE; t >= SPI_TICKS_ATE; t--)); do PLANO+=("T|padrao|$((200000000 / t))|1|tom||rapido"); done
fi
if tem U; then PLANO+=("U|padrao|$TAXA_PADRAO|1|curto||padrao" "U|padrao|${SPI_LONGAS%%:*}|1|curto||rapido"); fi
case "$PARTES" in
    *[!ABCDEGHJKLMNPQRSTU]*|'')
        echo "Erro: --partes aceita as letras A, B, C, D, E, G, H, J, K, L, M, N, P, Q, R, S, T e U (ex.: AB; atalhos:" \
             "--validar, --limite, --grade, --spi)." >&2
        exit 1 ;;
esac
case "$PARTES" in
    *[!GHJK]*) PREFIXO=T7e ;;
    *) PREFIXO=T7f ;;       # só a grade de tempo
esac
case "$PARTES" in
    *[!PSTU]*) ;;
    *) PREFIXO=T7g ;;       # só o SPI rápido
esac

blocos_da_parte() {
    case "$1" in
        C|R|U) echo 1 ;;    # só o ruído
        L|J|P|T) echo 2 ;;  # 1 troca de buffer e a taxa medida pelo ARM, em ~7 s por ponto
        *) echo "$BLOCOS" ;;
    esac
}
nome_da_captura() {   # $1 = item do plano
    local parte cs taxa canais entrada segundos spi
    IFS='|' read -r parte cs taxa canais entrada segundos spi <<< "$1"
    echo "${parte}_cs${cs//,/-}_${taxa}_${entrada}$( [ "$canais" = 1 ] || echo _2canais )${segundos:+_${segundos}s}${spi:+_spi${spi/:/-}}.bin"
}

# --continuar: a mesma pasta; feita = com linha no resumo.csv e com os contadores lidos (uma que o ler_adc não
# terminou, ou que foi cortada no meio, é refeita). As esperas e os canais vêm entre aspas, com vírgulas: a coluna
# amostras_atrasadas é contada a partir do FIM da linha, quantas o cabeçalho tiver depois dela (5 até 21/10/2026).
declare -A FEITA=()
if [ -n "$CONTINUAR" ]; then
    while read -r arquivo atrasadas; do
        if [ "$atrasadas" != "?" ]; then FEITA[$arquivo]=1; fi
    done < <(awk -F, 'NR == 1 { for (k = 1; k <= NF; k++) if ($k == "amostras_atrasadas") depois = NF - k; next }
                      { print $2, $(NF - depois) }' "$CONTINUAR/resumo.csv")
fi
declare -A FALTAM_NA_PARTE=()
FALTAM=0
for item in "${PLANO[@]}"; do
    [ -z "${FEITA[$(nome_da_captura "$item")]:-}" ] || continue
    FALTAM=$((FALTAM + 1))
    FALTAM_NA_PARTE[${item%%|*}]=$(( ${FALTAM_NA_PARTE[${item%%|*}]:-0} + 1 ))
done

# Duração prevista de uma captura: a taxa que a PRU alcança com essas esperas (o quadro mínimo é de
# 595 + 2 × (S + H + A) ciclos de 5 ns, pelo simulador; ~467 no SPI rápido) e ~2 s de preparação.
duracao_s() {   # $1 = esperas ("padrao" = 3,1,3), $2 = taxa, $3 = blocos, $4 = modo do SPI
    local s h a q
    IFS=, read -r s h a <<< "${1/#padrao/3,1,3}"
    q=$((595 + 2 * (s + h + a)))
    case "${4:-}" in rapido*) q=467 ;; esac
    awk -v t="$2" -v q=$q -v clk=$CLOCK_PRU -v n=$(($3 * AMOSTRAS_POR_BLOCO)) \
        'BEGIN { m = clk / q; r = (t < m) ? t : m; printf "%.0f\n", n / r + 2 }'
}

TOTAL_S=0
MB_TOTAL=0
declare -A N_PARTE=() S_PARTE=() MB_PARTE=()
ORDEM_PARTES=''
for item in "${PLANO[@]}"; do
    [ -z "${FEITA[$(nome_da_captura "$item")]:-}" ] || continue
    IFS='|' read -r parte cs taxa _ _ segundos spi <<< "$item"
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
por_parte() {   # "L: 122 capturas, ~17 min, ~490 MB · M: ..."
    local p linha=''
    for ((k = 0; k < ${#ORDEM_PARTES}; k++)); do
        p=${ORDEM_PARTES:k:1}
        linha+="${linha:+ · }$p: ${N_PARTE[$p]}, ~$(( (S_PARTE[$p] + 59) / 60 )) min, ~${MB_PARTE[$p]} MB"
    done
    echo "$linha"
}
LIVRE_MB=$(( $(df -Pk . | awk 'NR == 2 { print $4 }') / 1024 ))

if [ -t 1 ]; then N=$'\e[1m' F=$'\e[2m' R=$'\e[0m' V=$'\e[32m' AM=$'\e[33m' VM=$'\e[31m'; else N='' F='' R='' V='' AM='' VM=''; fi
if [ "$PREFIXO" = T7f ]; then
    printf '\n  %s◆ T7f: a grade de tempo (período entre amostras)%s\n' "$N" "$R"
elif [ "$PREFIXO" = T7g ]; then
    printf '\n  %s◆ T7g: o SPI rápido (~15,4 MHz) e a margem do SDO%s\n' "$N" "$R"
else
    printf '\n  %s◆ T7e: esperas do CS e taxa de amostragem%s\n' "$N" "$R"
fi
printf '    partes %s · %d capturas · ~%d min · ~%d MB (livres: %d MB)\n' "$PARTES" "$FALTAM" $(( (TOTAL_S + 59) / 60 )) "$MB_TOTAL" "$LIVRE_MB"
[ "${#ORDEM_PARTES}" -lt 2 ] || printf '    %s(%s)%s\n' "$F" "$(por_parte)" "$R"
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
        IFS='|' read -r parte cs taxa canais entrada segundos spi <<< "$item"
        printf '    %s  cs %-12s %7s Hz  canais %-4s %s%s%s\n' "$parte" "$cs" "$taxa" "$canais" "$entrada" \
            "${segundos:+, $segundos s}" "${spi:+, SPI $spi}"
    done
    printf '\n    (--simular: nada foi capturado)\n\n'
    exit 0
fi
if [ "$LIVRE_MB" -lt $(( MB_TOTAL + 100 )) ]; then
    printf '  %sErro: faltam %d MB livres aqui. Traga as capturas antigas para o computador e apague-as daqui, ou\n' "$VM" $(( MB_TOTAL + 100 - LIVRE_MB ))
    printf '  rode menos partes de cada vez, trazendo (e apagando daqui) as capturas entre uma e outra:\n'
    printf '  %s.%s\n' "$(por_parte)" "$R"
    printf '  Ex.: --partes L; no computador, trazer; aqui, rm -r T7e_*; depois --partes MNQR.\n'
    echo "  O que já foi feito numa pasta não se perde: --continuar retoma (veja --help)."
    exit 1
fi
[ -x "$LER_ADC" ] || { echo "Erro: $LER_ADC não existe aqui: rode ./setup.sh antes." >&2; exit 1; }

# As partes E, L, M, N, Q e R pedem o firmware de 21/10/2026 (a correção do rebase do contador e, para N, Q e R, o
# padrão de 3,1,3): rodá-las com o antigo gasta o tempo à toa. Confere o código desta pasta, que ele foi compilado
# depois da última mudança e que é ele que está na PRU.
if tem N || tem Q || tem R; then
    if [ -f memoria_pru.h ] && ! grep -Eq 'define ATRASO_CS_SETUP_PADRAO +3u' memoria_pru.h; then
        echo "Erro: o firmware desta pasta não tem o padrão de esperas 3,1,3 (21/10/2026)." >&2
        echo "No computador:  scripts/BeagleBone_Setup.sh enviar --setup" >&2
        exit 1
    fi
    if [ -f ler_adc.c ] && [ -f ler_adc ] && { [ ler_adc -ot ler_adc.c ] || [ ler_adc -ot memoria_pru.h ]; }; then
        echo "Erro: o ler_adc é mais antigo que o código dele: compile antes (./setup.sh)." >&2
        exit 1
    fi
fi
if tem G || tem H || tem J || tem K; then
    if [ -f spi_core.asm ] && ! grep -q 'GRADE EXATA' spi_core.asm; then
        echo "Erro: o spi_core.asm desta pasta não tem a grade exata (espera de precisão, 22/10/2026)." >&2
        echo "No computador:  scripts/BeagleBone_Setup.sh enviar --setup" >&2
        exit 1
    fi
    if [ -f spi_core.asm ] && ! grep -q 'QUADRO DE DURAÇÃO FIXA' spi_core.asm; then
        echo "Erro: o spi_core.asm desta pasta não tem o quadro de duração fixa (2ª revisão de 22/10/2026): a" >&2
        echo "--grade mediria de novo o firmware do T7f. No computador:  scripts/BeagleBone_Setup.sh enviar --setup" >&2
        exit 1
    fi
    if [ -f ler_adc.c ] && [ -f ler_adc ] && { [ ler_adc -ot ler_adc.c ] || [ ler_adc -ot memoria_pru.h ]; }; then
        echo "Erro: o ler_adc é mais antigo que o código dele: compile antes (./setup.sh)." >&2
        exit 1
    fi
fi
if tem P || tem S || tem T || tem U; then
    if [ -f spi_core.asm ] && ! grep -q 'SPI RÁPIDO' spi_core.asm; then
        echo "Erro: o spi_core.asm desta pasta não tem o SPI rápido (protocolo 3, 22/10/2026)." >&2
        echo "No computador:  scripts/BeagleBone_Setup.sh enviar --setup" >&2
        exit 1
    fi
    if [ -f ler_adc.c ] && [ -f ler_adc ] && { [ ler_adc -ot ler_adc.c ] || [ ler_adc -ot memoria_pru.h ]; }; then
        echo "Erro: o ler_adc é mais antigo que o código dele: compile antes (./setup.sh)." >&2
        exit 1
    fi
fi
if tem E || tem L || tem M || tem N || tem Q || tem R || tem G || tem H || tem J || tem K || tem P || tem S || tem T \
        || tem U; then
    if [ -f spi_core.asm ] && ! grep -q 'CORRIGIDO em 21/10/2026' spi_core.asm; then
        echo "Erro: o spi_core.asm desta pasta não tem a correção do rebase do contador (21/10/2026)." >&2
        echo "No computador:  scripts/BeagleBone_Setup.sh enviar --setup" >&2
        exit 1
    fi
    if [ -f spi_core.asm ] && { [ ! -f fw_pru.out ] || [ fw_pru.out -ot spi_core.asm ]; }; then
        echo "Erro: o fw_pru.out é mais antigo que o spi_core.asm: compile e carregue antes (./setup.sh)." >&2
        exit 1
    fi
    if [ -f /lib/firmware/am335x-pru0-fw ] && [ -f fw_pru.out ] && ! cmp -s fw_pru.out /lib/firmware/am335x-pru0-fw; then
        echo "Erro: a PRU está com outro firmware, não o fw_pru.out desta pasta: rode ./setup.sh antes." >&2
        exit 1
    fi
fi

# No terminal do 'scripts/BeagleBone_Setup.sh ssh', o SUDO_ASKPASS tem a senha: o sudo não pergunta. Sem ele, a
# senha é pedida agora, uma vez, e não no meio da varredura.
if [ -n "${SUDO_ASKPASS:-}" ]; then
    sudo() { command sudo -A "$@"; }
fi
sudo -v || { echo "Erro: o sudo não aceitou a senha." >&2; exit 1; }

PASTA=${CONTINUAR:-${PREFIXO}_$(date +%Y-%m-%d_%H%M)}
mkdir -p "$PASTA"
LOG="$PASTA/log.txt"
RESUMO="$PASTA/resumo.csv"
if [ -z "$CONTINUAR" ]; then
    echo "parte,arquivo,esperas_cs,taxa_pedida_hz,canais,entrada,amostras_atrasadas,buffers_sobrescritos,quadros_sdo_ruido,taxa_arm_hz,desvio_arm_pct,codigo_saida,folga_ciclos,atraso_max_ciclos,spi,divergencias_a,divergencias_c" > "$RESUMO"
fi
# 12 numa varredura retomada de antes de 22/10/2026; 14 antes do SPI rápido (2ª revisão de 22/10/2026)
COLUNAS_RESUMO=$(head -n 1 "$RESUMO" | awk -F, '{ print NF }')
{
    echo "== $(date '+%Y-%m-%d %H:%M:%S %Z') · $(uname -n) · firmware $(cat VERSAO 2>/dev/null || echo '?')$( [ -z "$CONTINUAR" ] || echo ' · CONTINUAÇÃO')"
    echo "== partes $PARTES, $FALTAM de ${#PLANO[@]} capturas, $BLOCOS blocos cada (1 na parte C), faixa: $FAIXA"
} >> "$LOG"
printf '    pasta: %s\n' "$PASTA"

# Ctrl+C para (e guarda o que já foi feito). A queda da conexão (SIGHUP) não: as capturas seguem até a próxima
# pausa, onde a falta do terminal faz a varredura parar (o ler_adc herda o HUP ignorado e termina a captura dele).
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
i=0
for item in "${PLANO[@]}"; do
    [ -z "$interrompido" ] || break
    i=$((i + 1))
    nome=$(nome_da_captura "$item")
    [ -z "${FEITA[$nome]:-}" ] || continue
    IFS='|' read -r parte cs taxa canais entrada segundos spi <<< "$item"
    if [ "$parte" != "$parte_anterior" ]; then
        parte_anterior=$parte
        pular_parte=''
        resposta=0
        case "$parte" in
            A) printf '\n  %s▸ A: as esperas a 100 kS/s, com o tom%s\n' "$N" "$R" ;;
            B) printf '\n  %s▸ B: a taxa contra as esperas, com o tom%s\n' "$N" "$R" ;;
            E) printf '\n  %s▸ E: capturas longas, com o tom (cruzam 2^31 ciclos da PRU várias vezes)%s\n' "$N" "$R" ;;
            L) printf '\n  %s▸ L: o limite, de 303 a 333 kS/s em passos de 1 tick (5 ns), com o tom%s\n' "$N" "$R" ;;
            M) printf '\n  %s▸ M: 60 s perto do limite, com o tom%s\n' "$N" "$R" ;;
            N) printf '\n  %s▸ N: 10 min no padrão (312,5 kS/s, esperas 3,1,3), com o tom%s\n' "$N" "$R" ;;
            G) printf '\n  %s▸ G: a grade de tempo no padrão, com o tom (capturas longas)%s\n' "$N" "$R" ;;
            H) printf '\n  %s▸ H: a mesma, com o ARM ocupado (dd enchendo a DDR)%s\n' "$N" "$R" ;;
            K) printf '\n  %s▸ K: 2 canais no padrão%s\n' "$N" "$R" ;;
            J) printf '\n  %s▸ J: o teto com período constante, de 312,5 a 339,0 kS/s, 1 tick por vez%s\n' "$N" "$R" ;;
            P) printf '\n  %s▸ P: o SPI padrão e o rápido (fases A, B e C) a 312,5 kS/s, com o tom%s\n' "$N" "$R" ;;
            S) printf '\n  %s▸ S: 60 s a 400 kS/s com o SPI rápido, com 1 e 2 canais%s\n' "$N" "$R" ;;
            T) printf '\n  %s▸ T: o teto do SPI rápido, de 384,6 a 434,8 kS/s, 1 tick por vez%s\n' "$N" "$R" ;;
            U) pausa "gerador FORA e a entrada do canal 1 em CURTO (o divisor ligado ao retorno)." || resposta=$?
               printf '\n  %s▸ U: a entrada em curto, com o SPI padrão e o rápido%s\n' "$N" "$R" ;;
            D|Q) pausa "tom de 10 kHz no canal 1 (como até agora) e a entrada do canal 0 em CURTO." || resposta=$?
               printf '\n  %s▸ D: 2 canais%s\n' "$N" "$R" ;;
            C|R) pausa "gerador FORA e a entrada do canal 1 em CURTO (o divisor ligado ao retorno)." || resposta=$?
               printf '\n  %s▸ C: a entrada em curto%s\n' "$N" "$R" ;;
        esac
        case "$resposta" in
            1) pular_parte=$parte ;;
            2) interrompido="sem terminal na pausa da parte $parte"; break ;;
        esac
    fi
    if [ "$pular_parte" = "$parte" ]; then continue; fi

    faixa=$FAIXA
    [ "$canais" = 1 ] || faixa=$FAIXA_2CANAIS
    printf '    %s[%3d/%d]%s cs %-12s %7s Hz %-9s ' "$F" "$i" "${#PLANO[@]}" "$R" "$cs" "$taxa" "$( [ "$canais" = 1 ] || echo '2 canais')"
    echo "== [$i/${#PLANO[@]}] $nome" >> "$LOG"
    if [ -n "$segundos" ]; then tamanho=(--duracao "${segundos}s"); else tamanho=(--blocos "$(blocos_da_parte "$parte")"); fi
    esperas=(--atraso-cs "$cs")
    [ "$cs" != padrao ] || esperas=()      # o padrão do firmware, como numa captura qualquer
    modo_spi=()
    [ -z "$spi" ] || modo_spi=(--spi "$spi")
    carga=''
    if [ "$parte" = H ]; then              # a DDR e a CPU do ARM ocupadas durante a captura (o ler_adc tem prioridade)
        nice -n 10 dd if=/dev/zero of=/dev/null bs=4M 2>/dev/null &
        carga=$!
    fi
    # shellcheck disable=SC2086  # $faixa são duas palavras de propósito
    saida=$(sudo "$LER_ADC" "$taxa" "$canais" "${tamanho[@]}" "${esperas[@]}" "${modo_spi[@]}" $faixa -o "$PASTA/$nome" \
                 -t "$PREFIXO $parte cs $cs $taxa $entrada${segundos:+ ${segundos}s}${spi:+ spi $spi}" 2>&1 </dev/null)
    codigo=$?
    if [ -n "$carga" ]; then kill "$carga" 2>/dev/null; wait "$carga" 2>/dev/null; fi
    printf '%s\n' "$saida" >> "$LOG"

    integridade=$(printf '%s\n' "$saida" | sed -n 's/.*Integridade: \([0-9]*\) amostra(s) atrasada(s), \([0-9]*\) buffer(s) sobrescrito(s), \([0-9]*\) quadro(s).*/\1 \2 \3/p' | tail -n 1)
    taxa_arm=$(printf '%s\n' "$saida" | sed -n 's/.*Taxa real medida pelo ARM: \([0-9]*\) Hz (pedida [0-9]* Hz, \([-+0-9.]*\) %).*/\1 \2/p' | tail -n 1)
    folga=$(printf '%s\n' "$saida" | sed -n 's/.*Grade de tempo (PRU): folga mínima \([0-9]*\) ciclo.*/\1/p' | tail -n 1)
    pior=$(printf '%s\n' "$saida" | sed -n 's/.*Grade de tempo (PRU): .*a pior \([0-9]*\) ciclo.*/\1/p' | tail -n 1)
    divergencias=$(printf '%s\n' "$saida" \
        | sed -n 's/.*SPI rápido (fase . gravada): \([0-9]*\) quadro(s) com a fase A .* e \([0-9]*\) com a C.*/\1 \2/p' | tail -n 1)
    read -r div_a div_c <<< "${divergencias:- }"
    read -r atrasadas sobrescritos sdo <<< "${integridade:-? ? ?}"
    read -r arm desvio <<< "${taxa_arm:-? ?}"
    linha="$parte,$nome,\"$cs\",$taxa,\"$canais\",$entrada,$atrasadas,$sobrescritos,$sdo,$arm,$desvio,$codigo"
    [ "$COLUNAS_RESUMO" -le 12 ] || linha+=",$folga,$pior"
    [ "$COLUNAS_RESUMO" -le 14 ] || linha+=",${spi:-padrao},${div_a:-},${div_c:-}"
    echo "$linha" >> "$RESUMO"

    if [ "$codigo" -ne 0 ] && [ -z "$integridade" ]; then
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
    echo "    O que foi feito está salvo. Para seguir daqui:  ./varrer_taxa.sh --continuar"
else
    printf '\n  %s◆ Pronto%s: %s\n' "$N" "$R" "$PASTA"
fi
echo "    No computador:  scripts/BeagleBone_Setup.sh trazer '${PREFIXO}_*' \$DIA"
echo
