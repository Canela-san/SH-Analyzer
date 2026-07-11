# Makefile temporário para o diagnóstico do preâmbulo.
# Uso: make -f Makefile.diagnostico

CC_ARM = gcc
CFLAGS_ARM = -Wall -O3

CC_PRU = clpru
CFLAGS_PRU = -O2 --silicon_version=3
CMD_PRU = AM335x_PRU.cmd

all: arm pru

arm:
	$(CC_ARM) $(CFLAGS_ARM) ler_adc.c -o ler_adc

pru:
	$(CC_PRU) $(CFLAGS_PRU) pru_main.c spi_core.asm -z $(CMD_PRU) -o fw_pru.out

clean:
	rm -f ler_adc fw_pru.out *.map *.obj diagnostico_preambulo.bin