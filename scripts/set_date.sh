#!/usr/bin/env bash
# ==============================================================================
# Script: set_date.sh
# Descrição: Copia a data e hora do computador para a BeagleBone Black via SSH.
# Autor: Gabriel Canela
#
# POR QUE: a BeagleBone não tem bateria de RTC, então ao ser ligada o relógio dela
# pode estar errado -- e o ler_adc grava esse relógio (timestamp_unix) no cabeçalho
# de toda captura.
#
# USO (no computador, com a BeagleBone ligada e acessível pela rede/USB):
#   ./scripts/set_date.sh                      # padrão: debian@192.168.6.2
#   BBB_IP=192.168.7.2 ./scripts/set_date.sh   # outro endereço
#   BBB_USER=outro ./scripts/set_date.sh       # outro usuário
#
# AUTENTICAÇÃO (nenhuma senha fica gravada neste arquivo):
#   * Recomendado: chave SSH. Uma vez:  ssh-copy-id debian@192.168.6.2
#     (se a chave estiver autorizada, só o sudo remoto pode pedir senha).
#   * Sem chave: o ssh pede a senha no terminal, normalmente. Para não precisar
#     digitar, exporte SSHPASS antes (e tenha o 'sshpass' instalado):
#       read -rs SSHPASS && export SSHPASS && ./scripts/set_date.sh
#     (a senha vai pela variável de ambiente, não pela linha de comando, onde
#     qualquer usuário a veria em 'ps').
#
# O horário é enviado como instante absoluto (segundos desde 1970, UTC, com fração): vale
# independentemente do fuso configurado na BeagleBone (o timestamp do cabeçalho é UTC).
# O tempo que o operador leva para digitar a senha do sudo é DESCONTADO: o lado remoto mede,
# pelo /proc/uptime (monotônico, não depende do relógio errado), quanto tempo passou entre o
# início da sessão e o momento de acertar o relógio, e soma isso à hora enviada. O que sobra de
# erro é a latência da rede e, se o login SSH for por senha, o tempo de digitá-la (use chave).
# ==============================================================================

set -euo pipefail

TARGET_USER="${BBB_USER:-debian}"
TARGET_IP="${BBB_IP:-192.168.6.2}"

# Cores só se a saída for um terminal.
if [ -t 1 ]; then
    GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
else
    GREEN=''; YELLOW=''; RED=''; NC=''
fi

# 'accept-new': aceita a chave da BeagleBone na primeira conexão, mas RECUSA se ela
# mudar depois (o antigo 'StrictHostKeyChecking=no' aceitava qualquer coisa).
SSH_OPCOES=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

# ------------------------------------------------------------------------------
# 1. Hora local do computador
# ------------------------------------------------------------------------------
AGORA_EPOCH="$(date -u +%s.%N)"
case "$AGORA_EPOCH" in *N) AGORA_EPOCH="$(date -u +%s)" ;; esac   # date sem %N (não GNU): segundos inteiros
echo -e "${YELLOW}[1/2] Hora do computador: ${GREEN}$(date '+%Y-%m-%d %H:%M:%S %Z')${NC}"

# ------------------------------------------------------------------------------
# 2. Acerto do relógio na BeagleBone
# ------------------------------------------------------------------------------
echo -e "${YELLOW}[2/2] Acertando o relógio da BeagleBone Black (${TARGET_USER}@${TARGET_IP})...${NC}"

# Parte que roda como root ($1 = hora enviada, $2 = uptime no início da sessão, antes do sudo):
# soma o tempo gasto no sudo e acerta o relógio. 'fake-hwclock save' guarda a hora para o próximo
# boot (existe nas imagens Debian da BeagleBone).
# shellcheck disable=SC2016  # as variáveis são do shell REMOTO: as aspas simples são de propósito
COMANDO_ROOT='t1=$(cut -d" " -f1 /proc/uptime); novo=$(awk -v e="$1" -v a="$2" -v b="$t1" "BEGIN { printf \"%.3f\", e + b - a }"); date -u -s "@$novo" >/dev/null && { command -v fake-hwclock >/dev/null && fake-hwclock save || true; } && date "+%Y-%m-%d %H:%M:%S %Z"'
# Sessão remota: guarda o uptime ANTES do sudo e passa hora e uptime como argumentos (não como
# variáveis de ambiente, que o sudo poderia filtrar). %q protege o comando para o shell remoto.
montar_comando_remoto() {   # $1 = opções extras do sudo
    printf 't0=$(cut -d" " -f1 /proc/uptime); sudo %s bash -c %q _ %q "$t0"' "$1" "$COMANDO_ROOT" "$AGORA_EPOCH"
}

# A saída do ssh NÃO é capturada ($(...)): com o terminal interativo (-t), o pedido de senha do
# sudo viria junto e o operador ficaria sem ver o que digitar.
RESULTADO=0
if [ -n "${SSHPASS:-}" ] && command -v sshpass >/dev/null 2>&1; then
    # Senha via variável de ambiente (-e): o mesmo valor serve para o login SSH e, pelo stdin,
    # para o sudo remoto (-S).
    printf '%s\n' "$SSHPASS" | sshpass -e ssh "${SSH_OPCOES[@]}" "${TARGET_USER}@${TARGET_IP}" \
        "$(montar_comando_remoto "-S -p ''")" || RESULTADO=$?
else
    if [ -n "${SSHPASS:-}" ]; then
        echo -e "${YELLOW}Aviso: SSHPASS definido, mas o 'sshpass' não está instalado -- vou pedir a senha no terminal.${NC}"
    fi
    # -t: terminal interativo, para o ssh (e o sudo) poderem pedir senha.
    ssh -t "${SSH_OPCOES[@]}" "${TARGET_USER}@${TARGET_IP}" \
        "$(montar_comando_remoto "")" || RESULTADO=$?
fi

if [ "$RESULTADO" -eq 0 ]; then
    echo -e "${GREEN}✓ Relógio da BeagleBone acertado (a hora que ela passou a marcar está na linha acima).${NC}"
else
    echo -e "${RED}✗ Não consegui acertar a hora na BeagleBone (código ${RESULTADO}). Confira o endereço (BBB_IP), o usuário (BBB_USER) e a senha/chave.${NC}"
    exit 1
fi
