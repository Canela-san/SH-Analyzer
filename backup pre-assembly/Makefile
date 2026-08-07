TARGET = teste_spi_pru

all: compile

compile:
	@echo ">> Compilando o código C..."
	clpru -O2 --silicon_version=3 $(TARGET).c -z AM335x_PRU.cmd -o $(TARGET).out

clean:
	@echo ">> Limpando arquivos gerados..."
	rm -f *.out *.map *.obj