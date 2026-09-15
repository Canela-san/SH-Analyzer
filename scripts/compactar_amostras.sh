#!/usr/bin/env bash

# ==============================================================================
# Cores para saída bonita no terminal
# ==============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m' # Sem cor

echo -e "${BLUE}${BOLD}======================================================${NC}"
echo -e "${BLUE}${BOLD}    Compressor de Alta Densidade - Arquivos .bin      ${NC}"
echo -e "${BLUE}${BOLD}======================================================${NC}"

# ==============================================================================
# Função para verificar e instalar dependências silenciosamente
# ==============================================================================
garantir_dependencia() {
    local pacote=$1
    local comando=$2
    
    if ! command -v "$comando" &> /dev/null; then
        echo -e "${YELLOW}[ AVISO ] Dependência '$pacote' não encontrada.${NC}"
        echo -n -e "          Instalando '$pacote' via apt... "
        sudo apt-get update -qq && sudo apt-get install -y -qq "$pacote" > /dev/null
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}[ OK ]${NC}"
        else
            echo -e "${RED}[ FALHA ] Erro ao instalar. Verifique sua conexão.${NC}"
            exit 1
        fi
    else
        echo -e "${GREEN}[ OK ] Dependência '$pacote' já está instalada.${NC}"
    fi
}

# ==============================================================================
# Verificação de ambiente
# ==============================================================================
# Verifica se há arquivos .bin na pasta atual
count=$(ls -1 *.bin 2>/dev/null | wc -l)
if [ "$count" -eq 0 ]; then
    echo -e "${RED}[ ERRO ] Nenhum arquivo .bin de captura encontrado neste diretório.${NC}"
    exit 1
fi

DATA_ATUAL=$(date +"%Y%m%d_%H%M%S")
NOME_BASE="amostragens_adc_${DATA_ATUAL}"

# ==============================================================================
# Seleção de Modo de Compressão
# ==============================================================================
if [ "$1" == "--max" ]; then
    echo -e "\n${BLUE}[ INFO ] Modo selecionado: ZPAQ (Predição Matemática Extrema)${NC}"
    garantir_dependencia "zpaq" "zpaq"
    
    ARQUIVO_SAIDA="${NOME_BASE}.zpaq"
    
    echo -e "${YELLOW}[ PROCESSANDO ] Comprimindo $count arquivos (Isso vai demorar)...${NC}"
    # ZPAQ no modo mais agressivo existente (-m5)
    zpaq add "$ARQUIVO_SAIDA" *.bin -m5
    
else
    echo -e "\n${BLUE}[ INFO ] Modo selecionado: 7z Sólido (LZMA2 + 1GB Dicionário)${NC}"
    garantir_dependencia "p7zip-full" "7z"
    
    ARQUIVO_SAIDA="${NOME_BASE}.7z"
    
    echo -e "${YELLOW}[ PROCESSANDO ] Comprimindo $count arquivos (Uso alto de RAM)...${NC}"
    # 7z com compressão máxima (-mx=9), bloco sólido e dicionário gigantesco de RAM
    7z a -t7z -mx=9 -m0=lzma2:d1g -ms=on "$ARQUIVO_SAIDA" *.bin -bsp1
fi

# ==============================================================================
# Relatório Final
# ==============================================================================
echo -e "\n${BLUE}${BOLD}======================================================${NC}"
if [ -f "$ARQUIVO_SAIDA" ]; then
    TAMANHO_ORIGINAL=$(du -ch *.bin | grep total | awk '{print $1}')
    TAMANHO_FINAL=$(du -h "$ARQUIVO_SAIDA" | awk '{print $1}')
    
    echo -e "${GREEN}[ SUCESSO ] Compressão finalizada com integridade!${NC}"
    echo -e "Tamanho Original (Soma): ${BOLD}${TAMANHO_ORIGINAL}${NC}"
    echo -e "Tamanho Comprimido:      ${BOLD}${TAMANHO_FINAL}${NC}"
    echo -e "Arquivo gerado:          ${BOLD}${ARQUIVO_SAIDA}${NC}"
else
    echo -e "${RED}[ ERRO ] Falha ao gerar o arquivo comprimido.${NC}"
fi
echo -e "${BLUE}${BOLD}======================================================${NC}"