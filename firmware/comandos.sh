# Compilação e Linkagem (exemplo genérico)
clpru -O2 --silicon_version=3 -I/caminho/para/includes teste_spi_pru.c spi_core.asm -z AM335x_PRU.cmd -o firmware.out


# 1. Para a PRU 0
echo stop | sudo tee /sys/class/remoteproc/remoteproc1/state

# 2. Copia o binário final
sudo cp ffw_pru.out /lib/firmware/am335x-pru0-fw

# 3. Inicia a PRU 0 novamente
echo start | sudo tee /sys/class/remoteproc/remoteproc1/state