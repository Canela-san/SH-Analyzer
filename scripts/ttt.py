import numpy as np
import matplotlib.pyplot as plt

# 1. Definição da Estrutura do Binário
# '<u2' significa Little-Endian ('<'), Unsigned Integer de 2 bytes ('u2')
# Isso reflete exatamente os 4 bytes por amostra gerados pelo seu script em Assembly
estrutura_pacote = np.dtype([
    ('preambulo', '<u2'), 
    ('dado',      '<u2')
])

# 2. Leitura Otimizada do Arquivo
# O fromfile mapeia o binário direto para a memória usando a estrutura em C
dados = np.fromfile('diagnostico_preambulo.bin', dtype=estrutura_pacote)

# 3. Isolamento da Tensão
# O Numpy separa o array permitindo que a gente pegue apenas a "coluna" dos dados
dados_tensao = dados['dado']

# =========================================================
# 4. Configuração do Gráfico (Alta Qualidade/Resolução)
# =========================================================
plt.figure(figsize=(12, 6), dpi=150) # dpi=150 para maior nitidez

# Plotando a tensão
plt.plot(dados_tensao, color='#004C99', linewidth=1.2, label='Sinal Bruto (ADC)')

# Estilização
plt.title('Sinal Recebido do ADS8688 - Sem Preâmbulo', fontsize=14, fontweight='bold')
plt.xlabel('Número da Amostra', fontsize=12)
plt.ylabel('Valor Raw do ADC (0 a 65535)', fontsize=12)

plt.grid(True, linestyle='--', alpha=0.7)
plt.legend()
plt.tight_layout() # Ajusta as margens perfeitamente

# Exibe o gráfico em uma janela interativa no Pop!_OS/Windows
plt.show()