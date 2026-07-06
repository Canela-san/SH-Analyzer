import numpy as np
import matplotlib.pyplot as plt

# 1. Carrega os dados brutos de 16 bits (uint16)
# Substitua o nome do arquivo se necessário
dados_brutos = np.fromfile('supraharmonicos_raw.bin', dtype=np.uint16)

print(f"Total de amostras capturadas: {len(dados_brutos)}")

# 2. Conversão da escala do ADC (Exemplo baseado na sua fórmula em C)
ADC_MID_SCALE = 32768.0
V_RANGE_MAX = 10.24

# Converte o array inteiro de uma vez (Vetorização - muito rápido)
tensoes = ((dados_brutos - ADC_MID_SCALE) / ADC_MID_SCALE) * V_RANGE_MAX

# 3. Plota as primeiras 10000 amostras para validação visual
plt.plot(tensoes[:10000])
plt.title("Validação: Primeiras 10000 amostras (1 ms de dados a 1MSPS)")
plt.ylabel("Tensão (V)")
plt.xlabel("Amostra")
plt.grid(True)
plt.show()