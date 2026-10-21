#!/usr/bin/env bash
# ==============================================================================
# Script: enviar_firmware.sh
# Descrição: leva o firmware do repositório (só firmware/) para a BeagleBone, com a versão e um plano B.
#
# POR QUE: a BeagleBone só precisa dos fontes de firmware/ (o ler_adc, o código da PRU, o setup.sh e o
# calibrar_sonda.sh, que é bash puro); a análise roda no computador. Mandar o repositório inteiro (ou o .git)
# só gastaria o espaço das capturas. O que a BeagleBone não tem, sem o .git, é a VERSÃO do código, que o
# ler_adc grava em cada captura (cabeçalho v5): este script a escreve em firmware/VERSAO, a partir do
# 'git describe', e o Makefile de lá a usa.
#
# O QUE ELE FAZ, NESTA ORDEM (uma conexão SSH só: uma senha, se não houver chave):
#   1. recusa se firmware/ tem mudanças não commitadas (a versão apontaria para um código que não existe;
#      --forcar envia assim mesmo, com "-dirty" na versão);
#   2. escreve firmware/VERSAO com o 'git describe' (ex.: v0.5-20-gca69691);
#   3. na BeagleBone, se já há um firmware na pasta, guarda uma cópia SÓ DO CÓDIGO dele (fontes, VERSAO e os
#      binários compilados ler_adc/fw_pru.out) em <pasta>-anteriores/<data>_<versão antiga>/: é o plano B,
#      e não copia capturas (o antigo 'cp -a firmware firmware-velho' duplicava todas elas);
#   4. copia os arquivos VERSIONADOS de firmware/ (git ls-files: nada compilado no PC, nada de fora do git)
#      mais o VERSAO. Nada na BeagleBone é apagado: capturas e pastas que estiverem lá continuam;
#   5. com --setup, roda o ./setup.sh lá (compila e carrega a PRU; pede a senha do sudo).
#
# USO (no computador, na raiz do repositório ou de qualquer lugar):
#   scripts/enviar_firmware.sh                       # debian@192.168.6.2, pasta ~/firmware
#   scripts/enviar_firmware.sh --setup               # e já compila e carrega lá
#   scripts/enviar_firmware.sh --simular             # só mostra o que faria
#   BBB_IP=192.168.7.2 BBB_PASTA=sh-analyzer/firmware scripts/enviar_firmware.sh
#
# Variáveis (as mesmas do set_date.sh): BBB_USER (debian), BBB_IP (192.168.6.2), BBB_PASTA (firmware,
# relativa ao home do usuário na BeagleBone).
#
# AUTENTICAÇÃO: como no set_date.sh, de preferência uma chave SSH (ssh-copy-id debian@192.168.6.2).
# ==============================================================================

set -euo pipefail

BBB_USER="${BBB_USER:-debian}"
BBB_IP="${BBB_IP:-192.168.6.2}"
PASTA="${BBB_PASTA:-firmware}"
SSH_OPCOES=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

FORCAR=0
SETUP=0
SIMULAR=0

uso() {
    sed -n '/^# USO/,/^# AUTENTICA/p' "${BASH_SOURCE[0]}" | sed '$d; s/^# \{0,1\}//'
}

falha() { printf 'Erro: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --forcar) FORCAR=1 ;;
        --setup) SETUP=1 ;;
        --simular) SIMULAR=1 ;;
        --pasta) [ $# -ge 2 ] || falha "--pasta precisa de um caminho."; PASTA="$2"; shift ;;
        -h|--help) uso; exit 0 ;;
        *) falha "opção desconhecida: '$1' (veja --help)." ;;
    esac
    shift
done

# A pasta remota é relativa ao home (o padrão do ssh); '~/' na frente é aceito e removido, porque o shell
# remoto receberia o '~' protegido por aspas e criaria uma pasta chamada '~'.
PASTA="${PASTA#\~/}"
case "$PASTA" in
    ''|*' '*) falha "pasta remota inválida: '${PASTA}' (sem espaços; ex.: firmware ou sh-analyzer/firmware)." ;;
esac
ALVO="${BBB_USER}@${BBB_IP}"

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
command -v git >/dev/null 2>&1 || falha "'git' não encontrado."
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || falha "${RAIZ} não é um repositório git."

# ------------------------------------------------------------------------------
# 1. Versão (e recusa se o firmware tem mudanças não commitadas)
# ------------------------------------------------------------------------------
VERSAO="$(git describe --always)"
MUDANCAS="$(git status --porcelain -- firmware ':!firmware/VERSAO')"
if [ -n "$MUDANCAS" ]; then
    if [ "$FORCAR" -eq 0 ]; then
        printf 'Erro: firmware/ tem mudanças não commitadas:\n%s\n' "$MUDANCAS" >&2
        printf 'Commite antes de enviar (a versão gravada em cada captura tem de apontar para um código que existe),\n' >&2
        printf 'ou use --forcar para enviar assim mesmo, com "-dirty" na versão.\n' >&2
        exit 1
    fi
    VERSAO="${VERSAO}-dirty"
fi

mapfile -t ARQUIVOS < <(git ls-files firmware | sed 's|^firmware/||')
[ "${#ARQUIVOS[@]}" -gt 0 ] || falha "git ls-files não achou nada em firmware/."
ARQUIVOS+=(VERSAO)
CARIMBO="$(date +%Y-%m-%d_%H%M%S)"   # o relógio do PC: o da BeagleBone pode estar errado (sem RTC)

printf '== Firmware %s -> %s:%s\n' "$VERSAO" "$ALVO" "$PASTA"
printf '   %s\n' "${ARQUIVOS[*]}"
if [ "$SIMULAR" -eq 1 ]; then
    printf '(--simular: nada foi escrito nem enviado; o plano B iria para %s-anteriores/%s_<versão antiga>/)\n' "$PASTA" "$CARIMBO"
    exit 0
fi
printf '%s\n' "$VERSAO" > firmware/VERSAO

# ------------------------------------------------------------------------------
# 2. Na BeagleBone: plano B (só o código) e a cópia nova, numa conexão só
# ------------------------------------------------------------------------------
# $1 = pasta, $2 = carimbo, o resto = os arquivos enviados. O tar do código novo chega pelo stdin.
# shellcheck disable=SC2016  # as variáveis são do shell REMOTO: as aspas simples são de propósito
REMOTO='set -eu
pasta=$1; carimbo=$2; shift 2
mkdir -p -- "$pasta"
if [ -e "$pasta/ler_adc.c" ]; then
    antiga=$(head -c 64 "$pasta/VERSAO" 2>/dev/null | tr -cd "A-Za-z0-9._-" || true)
    [ -n "$antiga" ] || antiga=sem-versao
    destino="$pasta-anteriores/${carimbo}_$antiga"
    mkdir -p -- "$destino"
    for f in "$@" ler_adc fw_pru.out; do
        if [ -e "$pasta/$f" ]; then cp -p -- "$pasta/$f" "$destino/"; fi
    done
    echo "   plano B (o firmware que estava lá, só o código): $destino"
else
    echo "   primeira cópia nesta pasta: não há firmware anterior para guardar"
fi
tar -C "$pasta" -xf -
echo "   copiado: $# arquivo(s) em $pasta"'

COMANDO="bash -c $(printf '%q' "$REMOTO") _ $(printf '%q ' "$PASTA" "$CARIMBO" "${ARQUIVOS[@]}")"
# shellcheck disable=SC2029  # o comando remoto é montado aqui, protegido com %q: expandir do lado do PC é o que se quer
tar -C firmware -cf - "${ARQUIVOS[@]}" | ssh "${SSH_OPCOES[@]}" "$ALVO" "$COMANDO" \
    || falha "o envio para ${ALVO} falhou (confira BBB_IP, BBB_USER, a chave/senha e o espaço livre: df -h)."

# ------------------------------------------------------------------------------
# 3. Compilar e carregar (opcional)
# ------------------------------------------------------------------------------
if [ "$SETUP" -eq 1 ]; then
    printf '== setup.sh na BeagleBone (pede a senha do sudo)\n'
    # shellcheck disable=SC2029  # idem
    ssh -t "${SSH_OPCOES[@]}" "$ALVO" "cd $(printf '%q' "$PASTA") && ./setup.sh" \
        || falha "o setup.sh falhou na BeagleBone: veja a mensagem acima e use o plano B (setup.sh na pasta guardada)."
else
    printf '\nPróximo passo, na BeagleBone:  cd %s && ./setup.sh\n' "$PASTA"
fi
printf 'Confira na largada do ler_adc a linha "Firmware: %s".\n' "$VERSAO"
