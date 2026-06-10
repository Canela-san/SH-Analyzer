import os
import mmap
import struct
import time

# --- Endereços Físicos do Hardware do BeagleBone ---
PRU_BASE        = 0x4A300000  
SHARED_RAM_BASE = 0x4A310000  
NUM_AMOSTRAS    = 2000
PRU_DIR = "/sys/class/remoteproc/remoteproc0"

print("0. Resetando a PRU (Proteção contra falhas de Boot)...")
try:
    # Tenta forçar a parada da PRU caso ela tenha ligado sozinha com lixo na memória
    with open(f"{PRU_DIR}/state", "w") as f:
        f.write("stop\n")
except OSError:
    pass # Se ela já estiver parada ou der erro, apenas ignora e segue

time.sleep(0.1)

print("1. Abrindo acesso à memória física...")
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)

# Mapeia a Memória Local da PRU0 para o Python
pru0_ram = mmap.mmap(fd, 4096, offset=PRU_BASE)

# Passando os parâmetros que o código C está esperando
pru0_ram[4:8]  = struct.pack("<L", 0x00010000)
pru0_ram[8:12] = struct.pack("<L", NUM_AMOSTRAS)

# Mapeia a Memória Compartilhada para o Python ler depois
shared_ram = mmap.mmap(fd, 8192, offset=SHARED_RAM_BASE)

print("2. Ligando a PRU...")
try:
    with open(f"{PRU_DIR}/state", "r+") as f:
        status = f.read().strip()
        if status == "running":
            f.write("stop")
            time.sleep(0.1)
        f.write("start")
except Exception as e:
    print(f"Erro ao iniciar PRU: {e}")
    print("Dica: Verifique se rodou 'config-pin' e se o HDMI está desativado.")
    exit(1)

print("3. Aguardando a aquisição (500kHz)...")
time.sleep(0.1) 

print("4. Desligando a PRU...")
with open(f"{PRU_DIR}/state", "w") as f:
    f.write("stop\n")

print("5. Lendo os dados...")
amostras = []
for i in range(NUM_AMOSTRAS):
    raw_bytes = shared_ram[i*2 : i*2 + 2]
    valor = struct.unpack("<H", raw_bytes)[0]
    amostras.append(valor)

print("\n--- Primeiras 20 Amostras Lidas do ADS8688 ---")
for i in range(20):
    print(f"Amostra {i}: {amostras[i]}")

# Limpeza e fechamento
pru0_ram.close()
shared_ram.close()
os.close(fd)
print("\nAquisição finalizada com sucesso!")