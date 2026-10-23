#!/bin/bash
# shellcheck shell=bash disable=SC2034  # as cores e as constantes são usadas por quem carrega este arquivo
# ==============================================================================
# coleta/comum.sh -- o que os modos do coletar.sh compartilham. É carregado com 'source'; não roda sozinho.
# ==============================================================================

# A pasta do firmware: o ler_adc, o código e as pastas das coletas (o 'lab trazer' as busca lá).
DIR_FIRMWARE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
LER_ADC=${SH_LER_ADC:-$DIR_FIRMWARE/ler_adc}       # SH_LER_ADC: um ler_adc falso, nos testes
CLOCK_PRU=200000000
AMOSTRAS_POR_BLOCO=1048576
TETO_TICKS_RAPIDO=477                               # o teto medido da PRU (ler_adc.c): só para as estimativas
TETO_TICKS_LENTO=610

# Cores só num terminal (NO_COLOR desliga).
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    N=$'\e[1m' F=$'\e[2m' R=$'\e[0m' V=$'\e[32m' AM=$'\e[33m' VM=$'\e[31m'
else
    N='' F='' R='' V='' AM='' VM=''
fi

titulo() { printf '\n  %s◆ %s%s\n' "$N" "$*" "$R"; }
secao() { printf '\n  %s▸ %s%s\n' "$N" "$*" "$R"; }
info() { printf '    %s\n' "$*"; }
ok() { printf '    %s✓%s %s\n' "$V" "$R" "$*"; }
alerta() { printf '    %s! %s%s\n' "$AM" "$*" "$R"; }
erro() { printf 'Erro: %s\n' "$*" >&2; }
falha() { erro "$*"; exit 1; }

# O sudo pede a senha agora, uma vez, e não no meio da coleta. No terminal do 'BeagleBone_Setup.sh ssh', o
# SUDO_ASKPASS tem a senha e ele nem pergunta.
preparar_sudo() {
    if [ -n "${SUDO_ASKPASS:-}" ]; then
        sudo() { command sudo -A "$@"; }
    fi
    sudo -v || falha "o sudo não aceitou a senha."
}

# O ler_adc compilado depois do código dele, o fw_pru.out depois do spi_core.asm e a PRU com esse fw_pru.out: rodar
# uma coleta com o firmware errado gasta o tempo à toa (e grava capturas com a versão errada).
conferir_firmware() {
    local d=$DIR_FIRMWARE
    [ -x "$LER_ADC" ] || falha "$LER_ADC não existe: rode ./setup.sh antes."
    if [ -f "$d/ler_adc.c" ] && [ -f "$d/ler_adc" ] && { [ "$d/ler_adc" -ot "$d/ler_adc.c" ] || [ "$d/ler_adc" -ot "$d/memoria_pru.h" ]; }; then
        falha "o ler_adc é mais antigo que o código dele: compile antes (./setup.sh)."
    fi
    if [ -f "$d/spi_core.asm" ] && { [ ! -f "$d/fw_pru.out" ] || [ "$d/fw_pru.out" -ot "$d/spi_core.asm" ]; }; then
        falha "o fw_pru.out é mais antigo que o spi_core.asm: compile e carregue antes (./setup.sh)."
    fi
    if [ -f /lib/firmware/am335x-pru0-fw ] && [ -f "$d/fw_pru.out" ] && ! cmp -s "$d/fw_pru.out" /lib/firmware/am335x-pru0-fw; then
        falha "a PRU está com outro firmware, não o fw_pru.out desta pasta: rode ./setup.sh antes."
    fi
}

# Roda o ler_adc com sudo: a saída (stdout e stderr) em SAIDA_LER_ADC, o código em CODIGO_LER_ADC e, com LOG
# definido, a saída também no log.
# shellcheck disable=SC2034  # SAIDA_LER_ADC e CODIGO_LER_ADC são lidas por quem chama
capturar() {
    SAIDA_LER_ADC=$(sudo "$LER_ADC" "$@" 2>&1 </dev/null)
    CODIGO_LER_ADC=$?
    if [ -n "${LOG:-}" ]; then printf '%s\n' "$SAIDA_LER_ADC" >> "$LOG"; fi
}

# O resumo final do ler_adc (as linhas Integridade, Taxa medida, Grade e SPI) em variáveis: atrasadas, sobrescritos
# e sdo ("?" se a linha não veio: o ler_adc falhou antes do fim), arm e desvio ("?" com menos de 2 blocos), folga e
# pior (um dos dois vazio), div_a e div_c (vazios no SPI lento). tests/test_ler_adc_host.py confere estes sed contra
# a saída de verdade do ler_adc.
# shellcheck disable=SC2034  # as variáveis são lidas por quem chama
ler_resumo() {   # $1 = a saída do ler_adc
    local saida=$1 integridade taxa_arm divergencias
    integridade=$(printf '%s\n' "$saida" | sed -n 's/.*Integridade .*: \([0-9]*\) amostras* atrasadas*, \([0-9]*\) buffers* sobrescritos*, \([0-9]*\) quadros* com ruído no SDO.*/\1 \2 \3/p' | tail -n 1)
    taxa_arm=$(printf '%s\n' "$saida" | sed -n 's#.*Taxa medida *\([0-9]*\) S/s pelo relógio do ARM (\([-+0-9.]*\) % da pedida).*#\1 \2#p' | tail -n 1)
    folga=$(printf '%s\n' "$saida" | sed -n 's/.*Grade .*folga mínima \([0-9]*\) ciclo.*/\1/p' | tail -n 1)
    pior=$(printf '%s\n' "$saida" | sed -n 's/.*Grade .*a pior \([0-9]*\) ciclo.*/\1/p' | tail -n 1)
    divergencias=$(printf '%s\n' "$saida" \
        | sed -n 's/.*SPI .*divergências de leitura: \([0-9]*\) na fase A e \([0-9]*\) na C.*/\1 \2/p' | tail -n 1)
    read -r div_a div_c <<< "${divergencias:- }"
    read -r atrasadas sobrescritos sdo <<< "${integridade:-? ? ?}"
    read -r arm desvio <<< "${taxa_arm:-? ?}"
}

# --faixa-adc para todos os canais de uma lista: "0,1" e 5.12 -> "--faixa-adc 0:5.12,1:5.12".
argumento_de_faixa() {   # $1 = canais, $2 = faixa total (V)
    local lista='' c
    local -a canais
    IFS=, read -ra canais <<< "$1"
    for c in "${canais[@]}"; do lista+="${lista:+,}$c:$2"; done
    printf -- '--faixa-adc %s' "$lista"
}

valida_faixa() { case "$1" in 20.48|10.24|5.12) return 0 ;; esac; return 1; }

# Estatísticas de um canal de um .bin (cabeçalho de 1024 bytes), nas primeiras N amostras brutas (padrão 262144:
# ~0,65 s a 400 kS/s, ~40 ciclos de 60 Hz): "mínimo máximo média rms_ac vpp saturadas constante", em volts no pino
# (constante = 1 se todas as amostras do canal são iguais: o ADC mudo).
estatisticas_do_canal() {   # $1 = arquivo, $2 = nº de canais, $3 = posição do canal (0..), $4 = faixa total (V), [$5 = N]
    local n=${5:-262144}
    od -An -tu2 -v -j 1024 -N $((n * 2)) "$1" | tr -s ' ' '\n' \
        | LC_ALL=C awk -v nc="$2" -v pos="$3" -v faixa="$4" '
            NF { if ((k++ % nc) != pos) next
                 v = ($1 - 32768) * faixa / 65536
                 if (cont == 0 || v < min) min = v
                 if (cont == 0 || v > max) max = v
                 soma += v; soma2 += v * v; cont++
                 if ($1 == 0 || $1 == 65535) sat++
                 if (cont == 1) primeiro = $1; else if ($1 != primeiro) diferentes = 1 }
            END { if (cont == 0) { print "nan nan nan nan nan 0 1"; exit }
                  media = soma / cont; var = soma2 / cont - media * media; if (var < 0) var = 0
                  printf "%.6f %.6f %.6f %.6f %.6f %d %d\n", min, max, media, sqrt(var), max - min, sat, !diferentes }'
}

# A menor faixa do ADC em que o pico do sinal (|V| no pino) cabe com 15 % de folga.
faixa_para_o_pico() {   # $1 = pico (V)
    LC_ALL=C awk -v p="$1" 'BEGIN { p = (p < 0) ? -p : p
                                    if (p <= 0.85 * 2.56) print "5.12"; else if (p <= 0.85 * 5.12) print "10.24"; else print "20.48" }'
}

# A faixa para os canais da coleta, por uma captura curta em ±10,24 V (não satura com nada que caiba no ADC): a
# menor em que o pico de TODOS os canais cabe. Imprime a faixa e grava a captura em $1.
faixa_automatica() {   # $1 = arquivo da captura de teste, $2 = canais ("0,1"), $3 = taxa
    local arquivo=$1 pos pico_max=0 est
    local -a canais
    IFS=, read -ra canais <<< "$2"
    # shellcheck disable=SC2046  # o argumento de faixa são duas palavras
    capturar "$3" "$2" --blocos 1 $(argumento_de_faixa "$2" 20.48) -o "$arquivo" -t "faixa automatica"
    { [ "$CODIGO_LER_ADC" -eq 0 ] && [ -f "$arquivo" ]; } || return 1
    for ((pos = 0; pos < ${#canais[@]}; pos++)); do
        est=$(estatisticas_do_canal "$arquivo" "${#canais[@]}" "$pos" 20.48 65536)
        pico_max=$(LC_ALL=C awk -v e="$est" -v m="$pico_max" 'BEGIN { split(e, x, " "); a = x[1] < 0 ? -x[1] : x[1]
                                                                     b = x[2] < 0 ? -x[2] : x[2]; p = a > b ? a : b
                                                                     print (p > m) ? p : m }')
    done
    faixa_para_o_pico "$pico_max"
}

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

espaco_livre_mb() { echo $(( $(df -Pk . | awk 'NR == 2 { print $4 }') / 1024 )); }
