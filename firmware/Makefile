# Makefile de build do firmware (PRU) e do leitor ARM (ler_adc).
# Uso: make

CC_ARM = gcc
CFLAGS_ARM = -Wall -Wextra -O3

# Versão gravada em cada captura (cabeçalho v5): o arquivo VERSAO, que o PC escreve com 'git describe' antes de
# copiar a pasta para a BeagleBone (ver o roteiro de laboratório); sem ele, o git describe de onde se compila.
# O arquivo vem primeiro porque é ele que descreve o código copiado, mesmo que a pasta na BeagleBone seja um clone
# antigo do repositório.
VERSAO := $(shell cat VERSAO 2>/dev/null || git describe --always --dirty 2>/dev/null || echo desconhecida)

CC_PRU = clpru
CFLAGS_PRU = -O2 --silicon_version=3
CMD_PRU = AM335x_PRU.cmd

# Cabeçalhos (stdint.h) e bibliotecas do compilador da TI. O clpru os acha pela variável PRU_C_DIR (ou C_DIR), que
# a imagem da BeagleBone define só no shell interativo: num comando por ssh (o 'scripts/BeagleBone_Setup.sh setup'),
# ela não existe e o clpru para em 'could not open source file "stdint.h"'. Por isso o caminho sai da própria
# instalação do clpru (<instalação>/bin/clpru -> <instalação>/include e /lib); 'make PRU_CGT=...' o troca.
PRU_CGT ?= $(patsubst %/bin/clpru,%,$(filter %/bin/clpru,$(realpath $(shell command -v $(CC_PRU) 2>/dev/null))))
INCLUDE_PRU = $(if $(PRU_CGT),--include_path=$(PRU_CGT)/include)
BUSCA_LIB_PRU = $(if $(PRU_CGT),-i$(PRU_CGT)/lib -i$(PRU_CGT)/include)

.PHONY: all arm pru clean versao

all: arm pru

arm:
	$(CC_ARM) $(CFLAGS_ARM) -DVERSAO_FIRMWARE='"$(VERSAO)"' ler_adc.c -o ler_adc

pru:
	$(CC_PRU) $(CFLAGS_PRU) $(INCLUDE_PRU) pru_main.c spi_core.asm -z $(BUSCA_LIB_PRU) $(CMD_PRU) -o fw_pru.out

versao:
	@echo $(VERSAO)

clean:
	rm -f ler_adc fw_pru.out *.map *.obj supraharmonicos_raw.bin
