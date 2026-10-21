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
#
# USO (na BeagleBone, na pasta do firmware; de preferência no terminal do 'scripts/BeagleBone_Setup.sh ssh'):
#   ./varrer_taxa.sh              # tudo, com as pausas para mudar a bancada
#   ./varrer_taxa.sh --simular    # só mostra o plano, o tempo e o espaço
#   ./varrer_taxa.sh --partes AB  # só algumas partes (A, B, D e C, nesta ordem)
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
SO_A_250K="20,10,20 20,10,10 20,10,5 20,10,3"                                   # A sozinho, a 250 kS/s
DOIS_CANAIS="200,100,100:100000 20,10,10:200000 20,10,10:250000 6,2,6:250000 3,1,3:250000"
CURTO_RAPIDO="200,100,100:125000 20,10,10:250000 6,2,6:250000 3,1,3:250000"

PARTES=ABDC
SIMULAR=0
while [ $# -gt 0 ]; do
    case "$1" in
        --simular) SIMULAR=1 ;;
        --partes) [ $# -ge 2 ] || { echo "Erro: --partes precisa de letras (ex.: AB)." >&2; exit 1; }; PARTES=$2; shift ;;
        -h|--help) sed -n '/^# PARA QUE/,/^# ====/p' "${BASH_SOURCE[0]}" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
        *) echo "Erro: opção desconhecida: '$1' (veja --help)." >&2; exit 1 ;;
    esac
    shift
done

# Uma captura por linha: parte|esperas|taxa|canais|entrada
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
[ "${#PLANO[@]}" -gt 0 ] || { echo "Erro: nenhuma parte escolhida (use A, B, D e/ou C)." >&2; exit 1; }

blocos_da_parte() { if [ "$1" = C ]; then echo 1; else echo "$BLOCOS"; fi; }

# Duração prevista de uma captura: a taxa que a PRU alcança com essas esperas (o quadro mínimo é de
# 595 + 2 × (S + H + A) ciclos de 5 ns, pelo simulador) e ~2 s de preparação.
duracao_s() {   # $1 = esperas, $2 = taxa, $3 = blocos
    local s h a
    IFS=, read -r s h a <<< "$1"
    awk -v t="$2" -v q=$((595 + 2 * (s + h + a))) -v clk=$CLOCK_PRU -v n=$(($3 * AMOSTRAS_POR_BLOCO)) \
        'BEGIN { m = clk / q; r = (t < m) ? t : m; printf "%.0f\n", n / r + 2 }'
}

TOTAL_S=0
MB_TOTAL=0
for item in "${PLANO[@]}"; do
    IFS='|' read -r parte cs taxa _ _ <<< "$item"
    b=$(blocos_da_parte "$parte")
    TOTAL_S=$((TOTAL_S + $(duracao_s "$cs" "$taxa" "$b")))
    MB_TOTAL=$((MB_TOTAL + b * AMOSTRAS_POR_BLOCO * 2 / 1048576 + 1))
done
LIVRE_MB=$(( $(df -Pk . | awk 'NR == 2 { print $4 }') / 1024 ))

if [ -t 1 ]; then N=$'\e[1m' F=$'\e[2m' R=$'\e[0m' V=$'\e[32m' AM=$'\e[33m' VM=$'\e[31m'; else N='' F='' R='' V='' AM='' VM=''; fi
printf '\n  %s◆ T7e: esperas do CS e taxa de amostragem%s\n' "$N" "$R"
printf '    partes %s · %d capturas · ~%d min · ~%d MB (livres: %d MB)\n' "$PARTES" "${#PLANO[@]}" $(( (TOTAL_S + 59) / 60 )) "$MB_TOTAL" "$LIVRE_MB"
if [ "$SIMULAR" -eq 1 ]; then
    printf '\n'
    for item in "${PLANO[@]}"; do
        IFS='|' read -r parte cs taxa canais entrada <<< "$item"
        printf '    %s  cs %-12s %7s Hz  canais %-4s %s\n' "$parte" "$cs" "$taxa" "$canais" "$entrada"
    done
    printf '\n    (--simular: nada foi capturado)\n\n'
    exit 0
fi
if [ "$LIVRE_MB" -lt $(( MB_TOTAL + 100 )) ]; then
    printf '  %sErro: faltam %d MB livres aqui. Traga as capturas antigas para o computador e apague-as daqui, ou\n' "$VM" $(( MB_TOTAL + 100 - LIVRE_MB ))
    printf '  rode menos partes (--partes A, depois --partes B...).%s\n' "$R"
    exit 1
fi
[ -x "$LER_ADC" ] || { echo "Erro: $LER_ADC não existe aqui: rode ./setup.sh antes." >&2; exit 1; }

# No terminal do 'scripts/BeagleBone_Setup.sh ssh', o SUDO_ASKPASS tem a senha: o sudo não pergunta. Sem ele, a
# senha é pedida agora, uma vez, e não no meio da varredura.
if [ -n "${SUDO_ASKPASS:-}" ]; then
    sudo() { command sudo -A "$@"; }
fi
sudo -v || { echo "Erro: o sudo não aceitou a senha." >&2; exit 1; }

PASTA="T7e_$(date +%Y-%m-%d_%H%M)"
mkdir -p "$PASTA"
LOG="$PASTA/log.txt"
RESUMO="$PASTA/resumo.csv"
echo "parte,arquivo,esperas_cs,taxa_pedida_hz,canais,entrada,amostras_atrasadas,buffers_sobrescritos,quadros_sdo_ruido,taxa_arm_hz,desvio_arm_pct,codigo_saida" > "$RESUMO"
{
    echo "== $(date '+%Y-%m-%d %H:%M:%S %Z') · $(uname -n) · firmware $(cat VERSAO 2>/dev/null || echo '?')"
    echo "== partes $PARTES, ${#PLANO[@]} capturas, $BLOCOS blocos cada (1 na parte C), faixa: $FAIXA"
} >> "$LOG"
printf '    pasta: %s\n' "$PASTA"

interrompido=0
trap 'interrompido=1' INT

pausa() {   # $1 = o que mudar na bancada; devolve 1 se a parte deve ser pulada
    printf '\n  %s▸ Mude a bancada:%s %s\n' "$N$AM" "$R" "$1"
    printf '    Enter quando estiver pronto, ou p e Enter para pular esta parte: '
    local resposta=''
    read -r resposta || true
    echo "== pausa: $1 -> '${resposta}'" >> "$LOG"
    [ "$resposta" != p ]
}

pular_parte=''
parte_anterior=''
i=0
for item in "${PLANO[@]}"; do
    [ "$interrompido" -eq 0 ] || break
    i=$((i + 1))
    IFS='|' read -r parte cs taxa canais entrada <<< "$item"
    if [ "$parte" != "$parte_anterior" ]; then
        parte_anterior=$parte
        pular_parte=''
        case "$parte" in
            A) printf '\n  %s▸ A: as esperas a 100 kS/s, com o tom%s\n' "$N" "$R" ;;
            B) printf '\n  %s▸ B: a taxa contra as esperas, com o tom%s\n' "$N" "$R" ;;
            D) pausa "tom de 10 kHz no canal 1 (como até agora) e a entrada do canal 0 em CURTO." || pular_parte=$parte
               printf '\n  %s▸ D: 2 canais%s\n' "$N" "$R" ;;
            C) pausa "gerador FORA e a entrada do canal 1 em CURTO (o divisor ligado ao retorno)." || pular_parte=$parte
               printf '\n  %s▸ C: a entrada em curto%s\n' "$N" "$R" ;;
        esac
    fi
    if [ "$pular_parte" = "$parte" ]; then continue; fi

    nome="${parte}_cs${cs//,/-}_${taxa}_${entrada}$( [ "$canais" = 1 ] || echo _2canais ).bin"
    faixa=$FAIXA
    [ "$canais" = 1 ] || faixa=$FAIXA_2CANAIS
    printf '    %s[%3d/%d]%s cs %-12s %7s Hz %-9s ' "$F" "$i" "${#PLANO[@]}" "$R" "$cs" "$taxa" "$( [ "$canais" = 1 ] || echo '2 canais')"
    echo "== [$i/${#PLANO[@]}] $nome" >> "$LOG"
    # shellcheck disable=SC2086  # $faixa são duas palavras de propósito
    saida=$(sudo "$LER_ADC" "$taxa" "$canais" --blocos "$(blocos_da_parte "$parte")" --atraso-cs "$cs" $faixa -o "$PASTA/$nome" \
                 -t "T7e $parte cs $cs $taxa $entrada" 2>&1 </dev/null)
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

{
    echo "== fim $(date '+%Y-%m-%d %H:%M:%S %Z')$( [ "$interrompido" -eq 0 ] || echo ' (interrompido com Ctrl+C)')"
} >> "$LOG"
printf '\n  %s◆ Pronto%s%s: %s\n' "$N" "$R" "$( [ "$interrompido" -eq 0 ] || echo ' (interrompido)')" "$PASTA"
echo "    No computador:  scripts/BeagleBone_Setup.sh trazer 'T7e_*' \$DIA"
echo
