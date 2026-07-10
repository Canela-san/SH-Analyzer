# Compilação e Linkagem (fluxo atual: pru_main.c + spi_core.asm)
clpru -O2 --silicon_version=3 pru_main.c spi_core.asm -z AM335x_PRU.cmd -o fw_pru.out


# 1. Para a PRU 0
echo stop | sudo tee /sys/class/remoteproc/remoteproc1/state

# 2. Copia o binário final
# ATENÇÃO: o nome de saída do Makefile/clpru é "fw_pru.out" (sem o "ff" duplo).
# "ffw_pru.out" é um typo e nem chega a existir - um cp com esse nome falha,
# mas se você tiver copiado isso manualmente em algum momento com o nome
# certo por engano de um build antigo, vale conferir com md5sum.
sudo cp fw_pru.out /lib/firmware/am335x-pru0-fw

# 3. Inicia a PRU 0 novamente
echo start | sudo tee /sys/class/remoteproc/remoteproc1/state