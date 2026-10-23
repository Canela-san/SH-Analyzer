#!/bin/bash
# ==============================================================================
# coleta/conferir.sh -- ./coletar.sh conferir: a bancada está pronta para capturar? Em ~10 s: o firmware compilado e
# carregado, uma captura curta (o ler_adc confere os pinos da PRU, a memória e o ADC respondendo), a integridade e,
# em cada canal, o nível, o offset e o ruído do sinal, a faixa certa para ele e, com --esperado-vpp, se ele é o que
# o gerador deveria estar mandando (pega a ligação errada antes de uma série inteira de capturas).
# ==============================================================================

set -uo pipefail
# shellcheck source-path=SCRIPTDIR source=comum.sh
source "$(dirname "${BASH_SOURCE[0]}")/comum.sh"
cd "$DIR_FIRMWARE" || exit 1

ajuda() {
    cat <<'FIM'
Uso: ./coletar.sh conferir [opções]

Confere a bancada em ~10 s: o firmware, os pinos e o ADC, a integridade de uma captura curta e, em cada canal, o
nível (Vpp), o offset e o ruído do sinal e a menor faixa do ADC que o comporta. Sai com 1 se algo estiver errado.

Opções
  --canais LISTA     canais (padrão: 1)
  --faixa F          faixa total da captura: 20.48 (padrão: não satura com nada), 10.24 ou 5.12
  --taxa HZ          taxa total (padrão: 400000)
  --blocos N         blocos (padrão: 1, ~2,6 s a 400 kS/s)
  --spi MODO         rapido (padrão) ou lenta
  --esperado-vpp V   o Vpp esperado (no pino do ADC; com --ganho, na entrada da sonda ou do divisor)
  --ganho G          ganho da sonda/divisor para mostrar o sinal na entrada (ex.: 19.357, o divisor de tensão)
  --tolerancia PCT   desvio aceito em --esperado-vpp (padrão: 10)
  -o ARQUIVO         a captura (padrão: conferencia.bin, nesta pasta)
FIM
}

CANAIS=1
FAIXA=20.48
TAXA=400000
BLOCOS=1
SPI=rapido
ESPERADO=''
GANHO=1
TOLERANCIA=10
ARQUIVO=conferencia.bin
numero() { [[ "$1" =~ ^[0-9]+([.][0-9]+)?$ ]]; }
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) ajuda; exit 0 ;;
        --canais) [ $# -ge 2 ] && [[ "$2" =~ ^[0-7](,[0-7])*$ ]] || falha "--canais: canais de 0 a 7 separados por vírgula."
                  CANAIS=$2; shift ;;
        --faixa) { [ $# -ge 2 ] && valida_faixa "$2"; } || falha "--faixa: use 20.48, 10.24 ou 5.12."; FAIXA=$2; shift ;;
        --taxa) [ $# -ge 2 ] && [[ "$2" =~ ^[0-9]+$ ]] || falha "--taxa precisa de um inteiro (Hz)."; TAXA=$2; shift ;;
        --blocos) [ $# -ge 2 ] && [[ "$2" =~ ^[1-9][0-9]*$ ]] || falha "--blocos precisa de um inteiro positivo."; BLOCOS=$2; shift ;;
        --spi) [ $# -ge 2 ] && [[ "$2" =~ ^(rapido|lenta)$ ]] || falha "--spi: use rapido ou lenta."; SPI=$2; shift ;;
        --esperado-vpp) { [ $# -ge 2 ] && numero "$2"; } || falha "--esperado-vpp precisa de um número (V)."; ESPERADO=$2; shift ;;
        --ganho) { [ $# -ge 2 ] && numero "$2"; } || falha "--ganho precisa de um número."; GANHO=$2; shift ;;
        --tolerancia) { [ $# -ge 2 ] && numero "$2"; } || falha "--tolerancia precisa de um número (%)."; TOLERANCIA=$2; shift ;;
        -o) [ $# -ge 2 ] || falha "-o precisa de um arquivo."; ARQUIVO=$2; shift ;;
        *) falha "opção desconhecida: '$1' (veja ./coletar.sh conferir --help)." ;;
    esac
    shift
done
IFS=, read -ra LISTA_CANAIS <<< "$CANAIS"

problemas=0
titulo "Conferência: canais $CANAIS, $TAXA S/s, ±$(LC_ALL=C awk -v f="$FAIXA" 'BEGIN { printf "%.2f", f / 2 }') V"
conferir_firmware
ok "firmware $(cat VERSAO 2>/dev/null || echo '?') compilado e carregado na PRU"
preparar_sudo

# shellcheck disable=SC2046  # o argumento de faixa são duas palavras
capturar "$TAXA" "$CANAIS" --blocos "$BLOCOS" --spi "$SPI" $(argumento_de_faixa "$CANAIS" "$FAIXA") -o "$ARQUIVO" -t conferencia
ler_resumo "$SAIDA_LER_ADC"
if [ "$CODIGO_LER_ADC" -eq 4 ]; then
    printf '    %s✗ o ADC não está respondendo%s: amostras todas iguais. A placa de aquisição está sem alimentação (a\n' "$VM" "$R"
    printf '      BeagleBone tem de estar na fonte de 5 V do conector; pelo USB, a placa fica desligada) ou os pinos da\n'
    printf '      PRU sem configuração (sudo ./setup.sh).\n\n'
    exit 1
elif [ "$atrasadas" = "?" ]; then
    printf '    %s✗ o ler_adc falhou (código %s)%s:\n' "$VM" "$CODIGO_LER_ADC" "$R"
    printf '%s\n' "$SAIDA_LER_ADC" | tail -n 8 | sed 's/^/      | /'
    echo
    exit 1
fi
if printf '%s\n' "$SAIDA_LER_ADC" | grep -q "pinos da PRU configurados"; then
    alerta "os pinos da PRU estavam sem configuração (a placa reiniciou?): o ler_adc os configurou"
fi
if [ "$atrasadas $sobrescritos $sdo" = "0 0 0" ]; then
    ok "captura íntegra${folga:+, grade exata (folga $folga ciclos)}${div_a:+, 0 divergências de leitura}"
    [ "${div_a:-0}${div_c:-0}" = 00 ] || alerta "divergências de leitura no SPI rápido: A $div_a, C $div_c"
else
    printf '    %s✗ integridade: %s amostras atrasadas, %s buffers sobrescritos, %s quadros com ruído no SDO%s\n' \
        "$VM" "$atrasadas" "$sobrescritos" "$sdo" "$R"
    problemas=$((problemas + 1))
fi

# Cada canal: nível, offset e ruído, em volts no pino (e na entrada, com --ganho).
for ((pos = 0; pos < ${#LISTA_CANAIS[@]}; pos++)); do
    canal=${LISTA_CANAIS[$pos]}
    read -r minimo maximo media rms vpp saturadas constante \
        <<< "$(estatisticas_do_canal "$ARQUIVO" "${#LISTA_CANAIS[@]}" "$pos" "$FAIXA")"
    pico=$(LC_ALL=C awk -v a="$minimo" -v b="$maximo" 'BEGIN { a = a < 0 ? -a : a; b = b < 0 ? -b : b; print (a > b) ? a : b }')
    ideal=$(faixa_para_o_pico "$pico")
    lsb=$(LC_ALL=C awk -v f="$FAIXA" 'BEGIN { print f / 65536 }')
    descricao=$(LC_ALL=C awk -v vpp="$vpp" -v g="$GANHO" -v m="$media" -v r="$rms" -v lsb="$lsb" 'BEGIN {
        texto = sprintf("%.4f Vpp no pino", vpp)
        if (g != 1) texto = texto sprintf(" (%.3f Vpp na entrada, ×%g)", vpp * g, g)
        printf "%s · offset %+.2f mV · %.3f mV rms sem o DC (%.1f LSB)", texto, 1e3 * m, 1e3 * r, r / lsb }')
    if [ "$constante" -eq 1 ]; then
        printf '    %s✗ canal %s: todas as amostras iguais (o ADC mudo ou a entrada saturada)%s\n' "$VM" "$canal" "$R"
        problemas=$((problemas + 1))
        continue
    fi
    if [ "$saturadas" -gt 0 ]; then
        printf '    %s✗ canal %s: %s amostras no fundo de escala (saturou): use uma faixa maior que %s%s\n' "$VM" "$canal" "$saturadas" "$FAIXA" "$R"
        problemas=$((problemas + 1))
    else
        ok "canal $canal: $descricao"
    fi
    if [ "$ideal" != "$FAIXA" ] && [ "$saturadas" -eq 0 ]; then
        info "  o pico ($(LC_ALL=C awk -v p="$pico" 'BEGIN { printf "%.3f", p }') V) cabe em ±$(LC_ALL=C awk -v f="$ideal" 'BEGIN { printf "%.2f", f / 2 }') V: nas capturas, use --faixa-adc $canal:$ideal (mais resolução)"
    fi
    if LC_ALL=C awk -v r="$rms" -v lsb="$lsb" 'BEGIN { exit !(r < 3 * lsb) }'; then
        info "  quase só ruído (menos de 3 LSB rms): o sinal chegou? (normal com a entrada em curto)"
    fi
    if [ -n "$ESPERADO" ]; then
        if LC_ALL=C awk -v v="$vpp" -v g="$GANHO" -v e="$ESPERADO" -v tol="$TOLERANCIA" \
                'BEGIN { d = 100 * (v * g / e - 1); exit !(d <= tol && d >= -tol) }'; then
            ok "canal $canal: o Vpp bate com o esperado ($ESPERADO V, ±$TOLERANCIA %)"
        else
            desvio=$(LC_ALL=C awk -v v="$vpp" -v g="$GANHO" -v e="$ESPERADO" 'BEGIN { printf "%+.1f", 100 * (v * g / e - 1) }')
            printf '    %s✗ canal %s: esperado %s Vpp, medido %s (%s %%): confira o plugue e o cabo da entrada, o gerador\n      (amplitude, High-Z, saída ligada) e o --ganho%s\n' \
                "$VM" "$canal" "$ESPERADO" "$(LC_ALL=C awk -v v="$vpp" -v g="$GANHO" 'BEGIN { printf "%.4f", v * g }')" "$desvio" "$R"
            problemas=$((problemas + 1))
        fi
    fi
done

if [ "$problemas" -eq 0 ]; then
    printf '\n  %s◆ Pronto para capturar%s (a captura: %s)\n\n' "$N$V" "$R" "$ARQUIVO"
    exit 0
fi
printf '\n  %s◆ %d problema(s)%s: resolva antes das capturas (a captura: %s)\n\n' "$N$VM" "$problemas" "$R" "$ARQUIVO"
exit 1
