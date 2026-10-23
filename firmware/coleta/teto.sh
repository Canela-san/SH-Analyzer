#!/bin/bash
# ==============================================================================
# coleta/teto.sh -- ./coletar.sh teto: a maior taxa em que TODA amostra sai no ciclo exato da grade da PRU, por
# varredura em frequência, e a taxa de trabalho (com margem) para cada modo do SPI.
#
# 1. Uma captura numa taxa folgada: a folga mínima que a PRU publica (os ciclos que sobram no pior momento) dá uma
#    estimativa do teto, ticks - folga (é conservadora: a folga inclui a troca de buffer).
# 2. A varredura: 1 tick (5 ns) por vez a partir de um pouco acima da estimativa, 2 blocos por ponto (com uma troca
#    de buffer), até duas taxas seguidas com amostras atrasadas. O teto é o menor período sem nenhuma.
# 3. A confirmação: uma captura longa no teto (várias trocas de buffer). Se uma amostra atrasar, sobe 1 tick.
# O quadro da PRU não depende do sinal: qualquer entrada (ou nenhuma) serve.
# ==============================================================================

set -uo pipefail
# shellcheck source-path=SCRIPTDIR source=comum.sh
source "$(dirname "${BASH_SOURCE[0]}")/comum.sh"
cd "$DIR_FIRMWARE" || exit 1

ajuda() {
    cat <<'FIM'
Uso: ./coletar.sh teto [opções]

A maior taxa com toda amostra na grade de tempo da PRU, por varredura em frequência (1 tick de 5 ns por vez), e a
taxa de trabalho recomendada (a maior taxa exata, divisora de 200 MHz, com a margem pedida). O quadro da PRU não
depende do sinal: qualquer entrada serve. ~2 min por modo do SPI.

Opções
  --spi LISTA            modos do SPI, separados por vírgula: rapido, lenta (padrão: rapido,lenta)
  --atraso-cs S,H,A      esperas do CS (padrão: as do firmware, 3,1,3)
  --margem N             ticks de margem da taxa de trabalho sobre o teto (padrão: 10, ~2 % do período)
  --blocos-confirmacao N blocos da captura longa no teto (padrão: 10, 9 trocas de buffer)
  --canais LISTA         canais (padrão: 1; o teto não depende deles)
  --simular              só mostra o plano
FIM
}

MODOS_SPI="rapido lenta"
ATRASO_CS=''
MARGEM=10
BLOCOS_CONFIRMACAO=10
CANAIS=1
SIMULAR=0
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) ajuda; exit 0 ;;
        --simular) SIMULAR=1 ;;
        --spi)
            [ $# -ge 2 ] || falha "--spi precisa de um valor."
            MODOS_SPI=${2//,/ }
            for m in $MODOS_SPI; do case "$m" in rapido|lenta) ;; *) falha "--spi: '$m' (use rapido e/ou lenta)." ;; esac; done
            shift ;;
        --atraso-cs)
            [ $# -ge 2 ] || falha "--atraso-cs precisa de um valor."
            [[ "$2" =~ ^[0-9]+,[0-9]+,[0-9]+$ ]] || falha "--atraso-cs '$2': use S,H,A (ex.: 3,1,3)."
            ATRASO_CS=$2; shift ;;
        --margem)
            [ $# -ge 2 ] && [[ "$2" =~ ^[0-9]+$ ]] || falha "--margem precisa de um inteiro (ticks)."
            MARGEM=$2; shift ;;
        --blocos-confirmacao)
            [ $# -ge 2 ] && [[ "$2" =~ ^[1-9][0-9]*$ ]] || falha "--blocos-confirmacao precisa de um inteiro positivo."
            BLOCOS_CONFIRMACAO=$2; shift ;;
        --canais)
            [ $# -ge 2 ] && [[ "$2" =~ ^[0-7](,[0-7])*$ ]] || falha "--canais: canais de 0 a 7 separados por vírgula."
            CANAIS=$2; shift ;;
        *) falha "opção desconhecida: '$1' (veja ./coletar.sh teto --help)." ;;
    esac
    shift
done

# O teto previsto (o do ler_adc.c, medido na placa) com estas esperas: cada iteração de setup ou hold a mais soma 2
# ciclos; a espera de CS alto, a partir de 10 iterações, 2·A + 1.
teto_previsto() {   # $1 = modo do SPI
    local base s=3 h=1 a=3
    if [ "$1" = rapido ]; then base=$TETO_TICKS_RAPIDO; else base=$TETO_TICKS_LENTO; fi
    [ -z "$ATRASO_CS" ] || IFS=, read -r s h a <<< "$ATRASO_CS"
    local t=$((base + 2 * (s - 3) + 2 * (h - 1)))
    [ "$a" -lt 10 ] || t=$((t + 2 * a + 1))
    echo "$t"
}

titulo "Teto da PRU: a maior taxa com toda amostra na grade (esperas ${ATRASO_CS:-padrão})"
for m in $MODOS_SPI; do
    previsto=$(teto_previsto "$m")
    info "SPI $m: previsto ~$previsto ticks ($((CLOCK_PRU / previsto)) S/s); começa em $((previsto + 40)) ticks, 2 blocos por ponto, confirma com $BLOCOS_CONFIRMACAO"
done
if [ "$SIMULAR" -eq 1 ]; then
    printf '\n    (--simular: nada foi capturado)\n\n'
    exit 0
fi
conferir_firmware
preparar_sudo

PASTA="TETO_$(date +%Y-%m-%d_%H%M)"
mkdir -p "$PASTA"
LOG="$PASTA/log.txt"
RESUMO="$PASTA/resumo.csv"
echo "spi,etapa,ticks,taxa_hz,blocos,amostras_atrasadas,folga_ciclos,atraso_max_ciclos,taxa_arm_hz,codigo_saida" > "$RESUMO"
echo "== $(date '+%Y-%m-%d %H:%M:%S %Z') · $(uname -n) · firmware $(cat VERSAO 2>/dev/null || echo '?') · esperas ${ATRASO_CS:-padrão}" >> "$LOG"
info "pasta: $PASTA"
interrompido=''
trap 'interrompido=1' INT

# Uma captura em 'ticks' de 5 ns; deixa os números do resumo do ler_adc nas variáveis de ler_resumo.
ponto() {   # $1 = modo do SPI, $2 = ticks, $3 = blocos, $4 = etapa
    local taxa=$((CLOCK_PRU / $2)) nome esperas=()
    nome="teto_spi${1}_${2}t_${3}b.bin"
    [ -z "$ATRASO_CS" ] || esperas=(--atraso-cs "$ATRASO_CS")
    echo "== $4: $nome" >> "$LOG"
    # shellcheck disable=SC2046  # o argumento de faixa são duas palavras
    capturar "$taxa" "$CANAIS" --blocos "$3" --spi "$1" --forcar-taxa "${esperas[@]}" $(argumento_de_faixa "$CANAIS" 5.12) \
        -o "$PASTA/$nome" -t "teto $1 $2 ticks"
    ler_resumo "$SAIDA_LER_ADC"
    echo "$1,$4,$2,$taxa,$3,$atrasadas,$folga,$pior,$arm,$CODIGO_LER_ADC" >> "$RESUMO"
    printf '    %s%-12s%s %4d ticks %7d S/s  ' "$F" "$4" "$R" "$2" "$taxa"
    if [ "$CODIGO_LER_ADC" -eq 4 ]; then
        printf '%s✗ o ADC não respondeu%s\n' "$VM" "$R"
        falha "o ADC não respondeu (a placa de aquisição está alimentada pela fonte de 5 V do conector?)."
    elif [ "$atrasadas" = "?" ]; then
        printf '%s✗ o ler_adc falhou (código %s; veja o log.txt)%s\n' "$VM" "$CODIGO_LER_ADC" "$R"
        falha "o ler_adc falhou: $(printf '%s\n' "$SAIDA_LER_ADC" | grep -m1 'Erro:' || echo "código $CODIGO_LER_ADC")"
    elif [ "$atrasadas" = 0 ]; then
        printf '%s✓%s na grade%s\n' "$V" "$R" "${folga:+, folga $folga ciclos}"
    else
        printf '%s! %s amostras atrasadas%s%s\n' "$AM" "$atrasadas" "${pior:+, a pior $pior ciclos}" "$R"
    fi
}

declare -A TETO=() ESTIMATIVA=()
for m in $MODOS_SPI; do
    [ -z "$interrompido" ] || break
    secao "SPI $m"
    inicio=$(( $(teto_previsto "$m") + 40 ))
    ponto "$m" "$inicio" 2 estimativa
    { [ "$atrasadas" = 0 ] && [ -n "$folga" ]; } || falha "a captura folgada ($inicio ticks) já atrasou: confira o firmware e as esperas."
    estimativa=$((inicio - folga))
    ESTIMATIVA[$m]=$estimativa

    # A varredura: de 2 ticks acima da estimativa para baixo, até 2 atrasadas seguidas.
    t=$((estimativa + 2))
    ultimo_ok=''
    seguidas=0
    while [ -z "$interrompido" ] && [ "$t" -ge $((estimativa - 25)) ]; do
        ponto "$m" "$t" 2 varredura
        if [ "$atrasadas" = 0 ]; then
            ultimo_ok=$t
            seguidas=0
        else
            seguidas=$((seguidas + 1))
            [ "$seguidas" -lt 2 ] || break
        fi
        t=$((t - 1))
    done
    if [ -z "$ultimo_ok" ]; then   # já atrasava acima da estimativa: sobe até achar o primeiro na grade
        t=$((estimativa + 3))
        while [ -z "$interrompido" ] && [ "$t" -lt "$inicio" ]; do
            ponto "$m" "$t" 2 varredura
            if [ "$atrasadas" = 0 ]; then ultimo_ok=$t; break; fi
            t=$((t + 1))
        done
    fi
    [ -n "$ultimo_ok" ] || falha "nenhum período abaixo de $inicio ticks ficou na grade."

    # A confirmação: uma captura longa no teto; se atrasar, 1 tick acima (até 5 vezes).
    teto=$ultimo_ok
    for _ in 1 2 3 4 5; do
        [ -z "$interrompido" ] || break
        ponto "$m" "$teto" "$BLOCOS_CONFIRMACAO" confirmacao
        [ "$atrasadas" != 0 ] || break
        teto=$((teto + 1))
    done
    TETO[$m]=$teto
done

titulo "Resultado$( [ -z "$interrompido" ] || echo ' (interrompido com Ctrl+C)')"
echo "spi,teto_ticks,teto_hz,estimativa_ticks,trabalho_ticks,trabalho_hz" > "$PASTA/teto.csv"
for m in $MODOS_SPI; do
    [ -n "${TETO[$m]:-}" ] || continue
    teto=${TETO[$m]}
    # A taxa de trabalho: a maior taxa exata (200 MHz ÷ ticks inteiro) com a margem pedida sobre o teto.
    trabalho=$((teto + MARGEM))
    while [ $((CLOCK_PRU % trabalho)) -ne 0 ]; do trabalho=$((trabalho + 1)); done
    echo "$m,$teto,$((CLOCK_PRU / teto)),${ESTIMATIVA[$m]},$trabalho,$((CLOCK_PRU / trabalho))" >> "$PASTA/teto.csv"
    ok "SPI $m: teto $teto ticks = $((CLOCK_PRU / teto)) S/s (estimativa pela folga: ${ESTIMATIVA[$m]}); taxa de trabalho $((CLOCK_PRU / trabalho)) S/s ($trabalho ticks, $((trabalho - teto)) de margem)"
done
echo "== fim $(date '+%Y-%m-%d %H:%M:%S %Z')" >> "$LOG"
info "No computador:  scripts/BeagleBone_Setup.sh trazer 'TETO_*' \$DIA   (resumo.csv: cada ponto; teto.csv: o resultado)"
echo
