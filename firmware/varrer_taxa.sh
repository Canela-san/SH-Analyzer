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
# USO (na BeagleBone, na pasta do firmware; de preferência no terminal do 'scripts/BeagleBone_Setup.sh ssh'):
#   ./varrer_taxa.sh              # tudo, com as pausas para mudar a bancada
#   ./varrer_taxa.sh --simular    # só mostra o plano, o tempo e o espaço
#   ./varrer_taxa.sh --partes AB  # só algumas partes (A, B, D e C, nesta ordem; E só se pedida)
#   ./varrer_taxa.sh --validar    # só a validação do firmware corrigido (a parte E): numa pasta nova, sem
#                                 # precisar de nenhuma varredura anterior (= --partes E)
#   ./varrer_taxa.sh --continuar  # retoma a última varredura (ou --continuar T7e_...): pula o que já foi feito
#
# SE A CONEXÃO CAIR: cada captura e a linha dela no resumo.csv são gravadas assim que ela termina, e a varredura
# não morre com o ssh: segue até a próxima pausa (ou até o fim) e para ali. Reconecte e rode --continuar.
#
# SAÍDA: a pasta T7e_<data>_<hora>/ com as capturas (<parte>_cs<S>-<H>-<A>_<taxa>_<entrada>.bin), o log.txt (tudo o
# que o ler_adc escreveu) e o resumo.csv (uma linha por captura: contadores de integridade e taxa medida pelo ARM).
# No computador:  scripts/BeagleBone_Setup.sh trazer 'T7e_*' $DIA
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

PARTES=ABDC
SIMULAR=0
CONTINUAR=''
while [ $# -gt 0 ]; do
    case "$1" in
        --simular) SIMULAR=1 ;;
        --validar) PARTES=E ;;
        --limite) PARTES=LMNQR ;;
        --continuar)
            if [ $# -ge 2 ] && [ "${2#-}" = "$2" ]; then CONTINUAR=${2%/}; shift; else CONTINUAR=ultima; fi ;;
        --partes) [ $# -ge 2 ] || { echo "Erro: --partes precisa de letras (ex.: AB)." >&2; exit 1; }; PARTES=$2; shift ;;
        -h|--help) sed -n '/^# PARA QUE/,/^# ====/p' "${BASH_SOURCE[0]}" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
        *) echo "Erro: opção desconhecida: '$1' (veja --help)." >&2; exit 1 ;;
    esac
    shift
done

# Uma captura por linha: parte|esperas|taxa|canais|entrada|duração em s (vazia = blocos)
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
case "$PARTES" in
    *[!ABCDELMNQR]*|'')
        echo "Erro: --partes aceita as letras A, B, C, D, E, L, M, N, Q e R (ex.: AB; atalhos: --validar, --limite)." >&2
        exit 1 ;;
esac

blocos_da_parte() {
    case "$1" in
        C|R) echo 1 ;;      # só o ruído
        L) echo 2 ;;        # 1 troca de buffer e a taxa medida pelo ARM, em ~7 s por ponto
        *) echo "$BLOCOS" ;;
    esac
}
nome_da_captura() {   # $1 = item do plano
    local parte cs taxa canais entrada segundos
    IFS='|' read -r parte cs taxa canais entrada segundos <<< "$1"
    echo "${parte}_cs${cs//,/-}_${taxa}_${entrada}$( [ "$canais" = 1 ] || echo _2canais )${segundos:+_${segundos}s}.bin"
}

# --continuar: a mesma pasta; feita = com linha no resumo.csv e com os contadores lidos (uma que o ler_adc não
# terminou, ou que foi cortada no meio, é refeita).
declare -A FEITA=()
if [ -n "$CONTINUAR" ]; then
    if [ "$CONTINUAR" = ultima ]; then
        CONTINUAR=$(find . -maxdepth 1 -type d -name 'T7e_*' | sort | tail -n 1)
        CONTINUAR=${CONTINUAR#./}
    fi
    [ -n "$CONTINUAR" ] && [ -f "$CONTINUAR/resumo.csv" ] \
        || { echo "Erro: não achei a varredura a continuar (${CONTINUAR:-nenhuma pasta T7e_* aqui})." >&2; exit 1; }
    while read -r arquivo atrasadas; do
        if [ "$atrasadas" != "?" ]; then FEITA[$arquivo]=1; fi
    done < <(awk -F, 'NR > 1 { print $2, $(NF - 5) }' "$CONTINUAR/resumo.csv")
fi
declare -A FALTAM_NA_PARTE=()
FALTAM=0
for item in "${PLANO[@]}"; do
    [ -z "${FEITA[$(nome_da_captura "$item")]:-}" ] || continue
    FALTAM=$((FALTAM + 1))
    FALTAM_NA_PARTE[${item%%|*}]=$(( ${FALTAM_NA_PARTE[${item%%|*}]:-0} + 1 ))
done

# Duração prevista de uma captura: a taxa que a PRU alcança com essas esperas (o quadro mínimo é de
# 595 + 2 × (S + H + A) ciclos de 5 ns, pelo simulador) e ~2 s de preparação.
duracao_s() {   # $1 = esperas ("padrao" = 3,1,3), $2 = taxa, $3 = blocos
    local s h a
    IFS=, read -r s h a <<< "${1/#padrao/3,1,3}"
    awk -v t="$2" -v q=$((595 + 2 * (s + h + a))) -v clk=$CLOCK_PRU -v n=$(($3 * AMOSTRAS_POR_BLOCO)) \
        'BEGIN { m = clk / q; r = (t < m) ? t : m; printf "%.0f\n", n / r + 2 }'
}

TOTAL_S=0
MB_TOTAL=0
declare -A N_PARTE=() S_PARTE=() MB_PARTE=()
ORDEM_PARTES=''
for item in "${PLANO[@]}"; do
    [ -z "${FEITA[$(nome_da_captura "$item")]:-}" ] || continue
    IFS='|' read -r parte cs taxa _ _ segundos <<< "$item"
    if [ -n "$segundos" ]; then
        s_item=$((segundos + 2))
        mb_item=$((taxa * segundos * 2 / 1048576 + 1))
    else
        b=$(blocos_da_parte "$parte")
        s_item=$(duracao_s "$cs" "$taxa" "$b")    # o bloco é de amostras brutas: a duração só depende da taxa total
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
printf '\n  %s◆ T7e: esperas do CS e taxa de amostragem%s\n' "$N" "$R"
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
        IFS='|' read -r parte cs taxa canais entrada segundos <<< "$item"
        printf '    %s  cs %-12s %7s Hz  canais %-4s %s%s\n' "$parte" "$cs" "$taxa" "$canais" "$entrada" "${segundos:+, $segundos s}"
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
if tem E || tem L || tem M || tem N || tem Q || tem R; then
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

PASTA=${CONTINUAR:-T7e_$(date +%Y-%m-%d_%H%M)}
mkdir -p "$PASTA"
LOG="$PASTA/log.txt"
RESUMO="$PASTA/resumo.csv"
if [ -z "$CONTINUAR" ]; then
    echo "parte,arquivo,esperas_cs,taxa_pedida_hz,canais,entrada,amostras_atrasadas,buffers_sobrescritos,quadros_sdo_ruido,taxa_arm_hz,desvio_arm_pct,codigo_saida" > "$RESUMO"
fi
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
    IFS='|' read -r parte cs taxa canais entrada segundos <<< "$item"
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
    # shellcheck disable=SC2086  # $faixa são duas palavras de propósito
    saida=$(sudo "$LER_ADC" "$taxa" "$canais" "${tamanho[@]}" "${esperas[@]}" $faixa -o "$PASTA/$nome" \
                 -t "T7e $parte cs $cs $taxa $entrada${segundos:+ ${segundos}s}" 2>&1 </dev/null)
    codigo=$?
    printf '%s\n' "$saida" >> "$LOG"

    integridade=$(printf '%s\n' "$saida" | sed -n 's/.*Integridade: \([0-9]*\) amostra(s) atrasada(s), \([0-9]*\) buffer(s) sobrescrito(s), \([0-9]*\) quadro(s).*/\1 \2 \3/p' | tail -n 1)
    taxa_arm=$(printf '%s\n' "$saida" | sed -n 's/.*Taxa real medida pelo ARM: \([0-9]*\) Hz (pedida [0-9]* Hz, \([-+0-9.]*\) %).*/\1 \2/p' | tail -n 1)
    read -r atrasadas sobrescritos sdo <<< "${integridade:-? ? ?}"
    read -r arm desvio <<< "${taxa_arm:-? ?}"
    echo "$parte,$nome,\"$cs\",$taxa,\"$canais\",$entrada,$atrasadas,$sobrescritos,$sdo,$arm,$desvio,$codigo" >> "$RESUMO"

    if [ "$codigo" -ne 0 ] && [ -z "$integridade" ]; then
        printf '%s✗ o ler_adc falhou (código %d; veja o log.txt)%s\n' "$VM" "$codigo" "$R"
    elif [ "$atrasadas $sobrescritos $sdo" = "0 0 0" ]; then
        printf '%s✓%s ARM %s Hz (%s %%)\n' "$V" "$R" "$arm" "$desvio"
    else
        printf '%s! atrasadas %s · sobrescritos %s · SDO %s%s · ARM %s Hz\n' "$AM" "$atrasadas" "$sobrescritos" "$sdo" "$R" "$arm"
    fi
done

echo "== fim $(date '+%Y-%m-%d %H:%M:%S %Z')${interrompido:+ (parado: $interrompido)}" >> "$LOG"
if [ -n "$interrompido" ]; then
    printf '\n  %s◆ Parado%s (%s): %s\n' "$N$AM" "$R" "$interrompido" "$PASTA"
    echo "    O que foi feito está salvo. Para seguir daqui:  ./varrer_taxa.sh --continuar"
else
    printf '\n  %s◆ Pronto%s: %s\n' "$N" "$R" "$PASTA"
fi
echo "    No computador:  scripts/BeagleBone_Setup.sh trazer 'T7e_*' \$DIA"
echo
