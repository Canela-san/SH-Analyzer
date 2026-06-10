cp
cls
echo start | sudo tee /sys/class/remoteproc/remoteproc1/state
cls
cat /sys/class/remoteproc/remoteproc1/state
echo stop | sudo tee /sys/class/remoteproc/remoteproc1/state
clear
echo start | sudo tee /sys/class/remoteproc/remoteproc1/state
ls
cd pru_firmware/
make
sudo cp teste_spi_pru.out /lib/firmware/am335x-pru0-fw
echo stop | sudo tee /sys/class/remoteproc/remoteproc1/state
echo start | sudo tee /sys/class/remoteproc/remoteproc1/state
gcc ler_adc.c -o ler_adc
make
sudo cp teste_spi_pru.out /lib/firmware/am335x-pru0-fw
echo stop | sudo tee /sys/class/remoteproc/remoteproc1/state
echo start | sudo tee /sys/class/remoteproc/remoteproc1/state
sudo ./ler_adc
