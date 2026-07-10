config-pin P9_31 pruout
config-pin P9_29 pruout
config-pin P9_30 pruin
config-pin P9_28 pruout

# ATENÇÃO: o Makefile atual (firmware/Makefile) gera "fw_pru.out"
# (TARGET_PRU = fw_pru.out). O nome antigo "teste_spi_pru.out" era do
# firmware de testes em backup pre-assembly/ e NÃO existe mais no fluxo
# novo - copiar o nome errado faz o remoteproc carregar um binário velho/
# incompatível sem nenhum erro visível no terminal.
sudo cp fw_pru.out /lib/firmware/am335x-pru0-fw

echo stop | sudo tee /sys/class/remoteproc/remoteproc1/state
echo start | sudo tee /sys/class/remoteproc/remoteproc1/state

# Dica: depois do start, confira o dmesg para ver se a PRU carregou e
# iniciou sem reclamar:
#   dmesg | tail -n 20