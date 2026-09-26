#!/usr/bin/env bash
# ==============================================================================
# Script: set_date.sh
# Descrição: Sincroniza a data e hora local (Pop!_OS) para a BeagleBone Black
# Autor: Gabriel Canela
# ==============================================================================

set -e

# ------------------------------------------------------------------------------
# Configurações e Variáveis
# ------------------------------------------------------------------------------
TARGET_USER="debian"
TARGET_IP="192.168.6.2"
PASSWORD="temppwd"

# Cores para formatação de saída no terminal
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# ------------------------------------------------------------------------------
# 1. Verificação e Instalação do sshpass
# ------------------------------------------------------------------------------
echo -e "${YELLOW}[1/3] Verificando dependência 'sshpass'...${NC}"

if ! command -v sshpass &> /dev/null; then
    echo -e "${YELLOW}--> 'sshpass' não encontrado. Instalando via apt...${NC}"
    sudo apt update && sudo apt install -y sshpass
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ 'sshpass' instalado com sucesso!${NC}"
    else
        echo -e "${RED}✗ Falha ao instalar 'sshpass'. Verifique as permissões ou conexão.${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ 'sshpass' já está instalado.${NC}"
fi

# ------------------------------------------------------------------------------
# 2. Obtenção da Data/Hora Local
# ------------------------------------------------------------------------------
CURRENT_DATE=$(date "+%Y-%m-%d %H:%M:%S")
echo -e "${YELLOW}[2/3] Data e Hora local capturada: ${GREEN}${CURRENT_DATE}${NC}"

# ------------------------------------------------------------------------------
# 3. Execução Remota na BeagleBone Black
# ------------------------------------------------------------------------------
echo -e "${YELLOW}[3/3] Sincronizando relógio na BeagleBone Black (${TARGET_IP})...${NC}"

sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no "${TARGET_USER}@${TARGET_IP}" \
    "echo '$PASSWORD' | sudo -S bash -c \"date -s '$CURRENT_DATE' && fake-hwclock save\""
    
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Data e hora sincronizadas com sucesso na BeagleBone Black!${NC}"
else
    echo -e "${RED}✗ Houve um erro ao tentar atualizar a hora na BeagleBone Black.${NC}"
    exit 1
fi
