config-pin P9_31 pruout
config-pin P9_29 pruout
config-pin P9_30 pruin
config-pin P9_28 pruout

make clean
make
sudo cp fw_pru.out /lib/firmware/am335x-pru0-fw

echo stop | sudo tee /sys/class/remoteproc/remoteproc1/state
echo start | sudo tee /sys/class/remoteproc/remoteproc1/state

# Dica: depois do start, confira o dmesg para ver se a PRU carregou e
# iniciou sem reclamar:
#   dmesg | tail -n 20

# sudo ./ler_adc 102400 0,1,2,3,4
