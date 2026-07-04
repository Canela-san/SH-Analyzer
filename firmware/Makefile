# ==============================================================================
# MAKEFILE - SISTEMA DE AQUISIÇÃO HÍBRIDO (PRU + ARM)
# ==============================================================================

# --- Configurações do Processador Principal (ARM - Linux) ---
CC_ARM = gcc
CFLAGS_ARM = -Wall -O3
TARGET_ARM = ler_adc
SRC_ARM = ler_adc.c

# --- Configurações do Coprocessador de Tempo Real (PRU) ---
CC_PRU = clpru
CFLAGS_PRU = -O2 --silicon_version=3
CMD_PRU = AM335x_PRU.cmd
TARGET_PRU = fw_pru.out
SRC_PRU_C = pru_main.c
SRC_PRU_ASM = spi_core.asm

# ==============================================================================
# REGRAS DE COMPILAÇÃO
# ==============================================================================

# Regra padrão: compila tudo
all: arm pru

# Compila o executável do Linux (Consumidor)
arm:
	@echo ">> Compilando o consumidor ARM (Qualidade Estrita / Alta Performance)..."
	$(CC_ARM) $(CFLAGS_ARM) $(SRC_ARM) -o $(TARGET_ARM)
	@echo ">> OK: $(TARGET_ARM) gerado."

# Compila o firmware da PRU (Produtor Híbrido C + Assembly)
pru:
	@echo ">> Compilando o firmware PRU..."
	$(CC_PRU) $(CFLAGS_PRU) $(SRC_PRU_C) $(SRC_PRU_ASM) -z $(CMD_PRU) -o $(TARGET_PRU)
	@echo ">> OK: $(TARGET_PRU) gerado."

# Limpeza profunda do diretório de build
clean:
	@echo ">> Limpando artefatos de compilação..."
	rm -f $(TARGET_ARM) $(TARGET_PRU) *.map *.obj
	@echo ">> Ambiente limpo."