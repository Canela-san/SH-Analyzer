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

# Instalação do compilador da TI: os cabeçalhos da PRU (stdint.h) em include/ e a biblioteca de execução (rtspru*)
# em lib/. O clpru a acha pela variável PRU_C_DIR (ou C_DIR), que a imagem da BeagleBone define só no shell
# interativo: num comando por ssh (o 'scripts/BeagleBone_Setup.sh setup') ela não existe e o clpru para no stdint.h.
# Por isso a instalação é procurada, nesta ordem: PRU_CGT (do ambiente, ou 'make PRU_CGT=...'), a pasta do próprio
# clpru (<instalação>/bin/clpru) e os lugares em que o pacote da BeagleBone e o instalador da TI a põem
# (/usr/share/ti/cgt-pru, /opt/ti/...). Vale a primeira que tem a biblioteca rtspru em lib/: só um stdint.h não basta,
# porque o /usr/include do Linux também tem o seu, que não é o da PRU (o clpru da imagem fica em /usr/bin, e com
# /usr/include ele para em "bits/libc-header-start.h").
CLPRU_REAL = $(realpath $(shell command -v $(CC_PRU) 2>/dev/null))
CANDIDATOS_CGT = $(PRU_CGT) $(patsubst %/bin/clpru,%,$(filter %/bin/clpru,$(CLPRU_REAL))) \
                 $(patsubst %/lib/,%,$(dir $(wildcard /usr/share/ti/*/lib/rtspru* /opt/ti/*/lib/rtspru* /usr/lib/ti/*/lib/rtspru*)))
CGT_PRU := $(firstword $(foreach d,$(CANDIDATOS_CGT),$(if $(wildcard $(d)/lib/rtspru*),$(d))))
INCLUDE_PRU = $(if $(CGT_PRU),--include_path=$(CGT_PRU)/include)
BUSCA_LIB_PRU = $(if $(CGT_PRU),-i$(CGT_PRU)/lib -i$(CGT_PRU)/include)
SEM_CGT = a instalação do compilador da TI (com lib/rtspru*) não foi achada e PRU_C_DIR não existe: o clpru \
          provavelmente não vai achar o stdint.h. Rode 'make PRU_CGT=<pasta da instalação>'

.PHONY: all arm pru clean versao

all: arm pru

arm:
	$(CC_ARM) $(CFLAGS_ARM) -DVERSAO_FIRMWARE='"$(VERSAO)"' ler_adc.c -o ler_adc

pru:
	$(if $(CGT_PRU)$(PRU_C_DIR)$(C_DIR),,$(warning $(SEM_CGT)))
	$(CC_PRU) $(CFLAGS_PRU) $(INCLUDE_PRU) pru_main.c spi_core.asm -z $(BUSCA_LIB_PRU) $(CMD_PRU) -o fw_pru.out

versao:
	@echo $(VERSAO)

clean:
	rm -f ler_adc fw_pru.out *.map *.obj supraharmonicos_raw.bin
