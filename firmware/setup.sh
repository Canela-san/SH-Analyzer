config-pin P9_31 pruout
config-pin P9_29 pruout
config-pin P9_30 pruin
config-pin P9_28 pruout
sudo cp teste_spi_pru.out /lib/firmware/am335x-pru0-fw
echo stop | sudo tee /sys/class/remoteproc/remoteproc1/state
echo start | sudo tee /sys/class/remoteproc/remoteproc1/state
