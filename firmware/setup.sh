#!/bin/bash
# ==============================================================================
# setup.sh -- prepara a BeagleBone para capturar: pinos da PRU, compilação do
# firmware (ler_adc + fw_pru.out) e (re)carga do firmware na PRU0.
#
# Uso (na BeagleBone, de dentro de firmware/):   ./setup.sh
# Ou, do computador:  scripts/BeagleBone_Setup.sh setup   (ele passa a senha do sudo; ninguém digita nada)
# Rode de novo sempre que mudar o firmware ou a PRU parar de responder.
# Os passos que precisam de root usam 'sudo' (pode pedir a senha).
# ==============================================================================

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"   # o Makefile e o fw_pru.out são relativos a esta pasta

# Com SUDO_ASKPASS (o BeagleBone_Setup.sh a deixa num arquivo temporário), o sudo lê a senha dele sem perguntar.
if [ -n "${SUDO_ASKPASS:-}" ]; then
    sudo() { command sudo -A "$@"; }
fi

# PRU0 nas imagens Debian da BeagleBone (remoteproc0 é o Cortex-M3 de energia). O ler_adc usa o
# mesmo caminho (REMOTEPROC_PRU0_ESTADO em ler_adc.c) para reiniciar a PRU a cada captura.
REMOTEPROC=/sys/class/remoteproc/remoteproc1
NOME_FIRMWARE=am335x-pru0-fw

passo() { printf '\n== %s\n' "$*"; }
falha() { printf 'ERRO: %s\n' "$*" >&2; exit 1; }

command -v config-pin >/dev/null 2>&1 || falha "'config-pin' não encontrado -- esta é uma imagem Debian da BeagleBone?"
command -v make >/dev/null 2>&1 || falha "'make' não encontrado -- instale o build-essential."
[ -d "$REMOTEPROC" ] || falha "${REMOTEPROC} não existe: o driver remoteproc da PRU não está carregado (confira o overlay da PRU em /boot/uEnv.txt)."
case "$(cat "${REMOTEPROC}/name" 2>/dev/null)" in
    *4a334000*) ;;   # endereço da PRU0 no AM335x
    *) printf 'Aviso: %s não parece ser a PRU0 (name = %s).\n' "$REMOTEPROC" "$(cat "${REMOTEPROC}/name" 2>/dev/null)" >&2 ;;
esac

# Os buffers da PRU (0x9F000000, os últimos 16 MB da DDR) só ficam fora do Linux com 'mem=496M' no /boot/uEnv.txt.
# Sem isso, a PRU escreveria por cima da memória do sistema. O ler_adc confere de novo a cada captura (/proc/iomem).
passo "Memória dos buffers da PRU (0x9F000000-0x9F3FFFFF fora da RAM do Linux)"
# (Endereços em texto com 8 dígitos hexadecimais: o awk da placa pode ser o mawk, sem strtonum.)
if sudo cat /proc/iomem | awk -F' : ' 'function h(x) { x = tolower(x); while (length(x) < 8) x = "0" x; return x }
        /^[0-9a-fA-F]/ && $2 == "System RAM" { split($1, f, "-"); if (h(f[1]) < "9f400000" && h(f[2]) >= "9f000000") achou = 1 }
        END { exit !achou }'; then
    falha "a RAM do Linux cobre os buffers da PRU (/proc/iomem). Ponha 'mem=496M' na linha cmdline= do /boot/uEnv.txt e reinicie a placa."
fi
echo "ok ($(grep -o 'mem=[^ ]*' /proc/cmdline || echo 'sem mem= na linha do kernel, mas a RAM do Linux não chega lá'))"

passo "Pinos da PRU0 (SPI do ADS8688; ver o mapa de bits no topo de spi_core.asm)"
config-pin P9_31 pruout   # pr1_pru0_pru_r30_0 -> SCLK
config-pin P9_29 pruout   # pr1_pru0_pru_r30_1 -> SDI/MOSI
config-pin P9_30 pruin    # pr1_pru0_pru_r31_2 <- SDO/MISO
config-pin P9_28 pruout   # pr1_pru0_pru_r30_3 -> CS

passo "Compilação (ler_adc + fw_pru.out), versão $(make -s versao)"
make clean
make
[ -f fw_pru.out ] || falha "o make terminou sem gerar fw_pru.out."

passo "Carga do firmware na PRU0"
sudo cp fw_pru.out "/lib/firmware/${NOME_FIRMWARE}"
# 'stop' numa PRU que já está parada é um erro do kernel (EINVAL): só para se estiver rodando.
if [ "$(cat "${REMOTEPROC}/state")" = "running" ]; then
    echo stop | sudo tee "${REMOTEPROC}/state" >/dev/null
fi
echo "$NOME_FIRMWARE" | sudo tee "${REMOTEPROC}/firmware" >/dev/null   # garante o nome (só aceito com a PRU parada)
echo start | sudo tee "${REMOTEPROC}/state" >/dev/null

estado="$(cat "${REMOTEPROC}/state")"
if [ "$estado" != "running" ]; then
    printf '\nÚltimas mensagens do kernel:\n' >&2
    sudo dmesg | tail -n 20 >&2 || true
    falha "a PRU0 ficou em '${estado}' depois do start."
fi
printf '\nPRU0 rodando o firmware novo. Exemplo de captura:\n  sudo ./ler_adc 102400 0,1 --blocos 1 -o teste.bin\n'
