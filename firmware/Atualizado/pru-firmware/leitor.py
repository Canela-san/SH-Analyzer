import os
import mmap
import struct
import time

SHARED_RAM_BASE = 0x4A310000  
NUM_AMOSTRAS    = 50
PRU_DIR = "/sys/class/remoteproc/remoteproc1" 

# --- FÍSICA DO SEU CIRCUITO ---
R_SERIE  = 4 * 270000  
R_MEDIDA = 22000       
R_TOTAL  = R_SERIE + R_MEDIDA
FATOR_DIVISOR = R_TOTAL / R_MEDIDA  

print("0. Resetando a PRU...")
try:
    with open(f"{PRU_DIR}/state", "w") as f:
        f.write("stop\n")
except OSError:
    pass 
time.sleep(0.1)

print("1. Abrindo acesso à memória compartilhada...")
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
# Agora só precisamos mapear a RAM onde os dados vão chegar
shared_ram = mmap.mmap(fd, 8192, offset=SHARED_RAM_BASE)

print("2. Ligando a PRU e iniciando as medições...")
with open(f"{PRU_DIR}/state", "w") as f:
    f.write("start\n")

print("3. Aguardando a aquisição...")
time.sleep(0.1) 

print("4. Desligando a PRU...")
with open(f"{PRU_DIR}/state", "w") as f:
    f.write("stop\n")

print(f"\n--- {NUM_AMOSTRAS} Leituras da Rede Elétrica (Canal 1) ---\n")
for i in range(NUM_AMOSTRAS):
    raw_bytes = shared_ram[i*2 : i*2 + 2]
    valor_bruto = struct.unpack("<H", raw_bytes)[0]
    
    # Cálculos
    v_adc = (valor_bruto / 65536.0 * 10.24) - 5.12
    v_rede = v_adc * FATOR_DIVISOR
    
    print(f"Amostra {i:02d}: ADC = {v_adc:>6.3f} V  |  Rede AC = {v_rede:>7.2f} V")

# Limpeza
shared_ram.close()
os.close(fd)