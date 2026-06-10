# Makefile para PRU Remoteproc (Debian 10.3 / Kernel 4.19)

CFLAGS := -v3 -O2 --display_error_number --endian=little --hardware_mac=on --obj_directory=gen
LDFLAGS := --reread_libs --warn_sections --stack_size=0x100 --heap_size=0x100

INCLUDE := --include_path=/usr/share/ti/cgt-pru/include --include_path=/usr/lib/ti/pru-software-support-package/include --include_path=/usr/lib/ti/pru-software-support-package/include/am335x

TARGET = gen/pru_adc.out

all: clean $(TARGET)

$(TARGET): pru_adc.c
	@mkdir -p gen
	clpru $(CFLAGS) $(INCLUDE) -c pru_adc.c
	clpru $(CFLAGS) -z gen/pru_adc.obj -o $(TARGET) -m gen/pru_adc.map -i/usr/share/ti/cgt-pru/lib -llibc.a $(LDFLAGS) AM335x_PRU.cmd

clean:
	@rm -rf gen *.obj