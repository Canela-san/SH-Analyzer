import os
import mmap
import struct
import time

# --- Endereços Físicos ---
PRU_BASE        = 0x4A300000  
SHARED_RAM_BASE = 0x4A310000  
NUM_AMOSTRAS    = 2000
PRU_DIR = "/sys/class/remoteproc/remoteproc1" # Usando o processador correto da PRU0

# --- FÍSICA DO SEU CIRCUITO ---
R_SERIE  = 4 * 270000  # 4 resistores de 270k (1.080.000 Ohms)
R_MEDIDA = 22000       # 1 resistor de 22k (22.000 Ohms)
R_TOTAL  = R_SERIE + R_MEDIDA

# O fator pelo qual precisamos multiplicar a tensão do ADC para achar a tensão da rede
# (Isso vai dar exatamente 50.0909)
FATOR_DIVISOR = R_TOTAL / R_MEDIDA  

# --- SEGURANÇA E LIGAÇÃO ---
print("0. Resetando a PRU...")
try:
    with open(f"{PRU_DIR}/state", "w") as f:
        f.write("stop\n")
except OSError:
    pass 
time.sleep(0.1)

print("1. Abrindo acesso à memória física...")
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
pru0_ram = mmap.mmap(fd, 4096, offset=PRU_BASE)
pru0_ram[4:8]  = struct.pack("<L", 0x00010000)
pru0_ram[8:12] = struct.pack("<L", NUM_AMOSTRAS)
shared_ram = mmap.mmap(fd, 8192, offset=SHARED_RAM_BASE)

print("2. Ligando a PRU (Acelerador 200MHz ativado)...")
with open(f"{PRU_DIR}/state", "w") as f:
    f.write("start\n")

print("3. Aguardando a aquisição da Rede Elétrica (500kHz)...")
time.sleep(0.1) 

print("4. Desligando a PRU...")
with open(f"{PRU_DIR}/state", "w") as f:
    f.write("stop\n")

print("5. Processando Matemática do Divisor de Tensão...")
amostras_brutas = []
tensoes_rede = []

for i in range(NUM_AMOSTRAS):
    raw_bytes = shared_ram[i*2 : i*2 + 2]
    valor_bruto = struct.unpack("<H", raw_bytes)[0]
    
    # 1º Passo: Converter o número do ADS8688 para Tensão no Pino (escala +-5.12V)
    # 65536 partes dividindo 10.24V totais, com zero deslocado em 5.12V.
    v_adc = (valor_bruto / 65536.0 * 10.24) - 5.12
    
    # 2º Passo: Multiplicar pelo fator dos resistores para voltar ao valor da tomada
    v_rede = v_adc * FATOR_DIVISOR
    
    amostras_brutas.append(valor_bruto)
    tensoes_rede.append(v_rede)

print("\n--- Primeiras 20 Leituras da Rede Elétrica (Canal 1) ---")
for i in range(20):
    v_adc = (amostras_brutas[i] / 65536.0 * 10.24) - 5.12
    print(f"Amostra {i:02d}: ADC = {v_adc:>6.3f} V  |  Rede AC = {tensoes_rede[i]:>7.2f} V")

# Limpeza
pru0_ram.close()
shared_ram.close()
os.close(fd)
print("\nAquisição finalizada com sucesso! Se a rede for 127V, os valores oscilarão entre +180V e -180V.")