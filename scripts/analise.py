import argparse
import sys
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt
from scipy.fft import fft, fftfreq



def converter_adc_para_tensao(dados_adc, ganho_sensor):
    """
    Converte os dados brutos do ADC (+-10.24V) para a tensão real da rede.
    ganho_sensor: Fator de multiplicação da sua PCB (ex: se 10.24V no ADC representa 200V na rede, o ganho é 200/10.24)
    """
    return dados_adc * ganho_sensor

def extrair_ciclos_inteiros(sinal, taxa_amostragem, freq_fundamental=60.0):
    """
    Filtra a componente fundamental para ignorar ruídos/supraharmônicos,
    encontra os cruzamentos por zero ascendentes e recorta o sinal original.
    """
    # 1. Cria um filtro passa-baixa (corte em 100 Hz) para isolar a fundamental
    frequencia_corte = 100.0 
    freq_nyquist = 0.5 * taxa_amostragem
    corte_normalizado = frequencia_corte / freq_nyquist
    b, a = butter(4, corte_normalizado, btype='low')
    
    # 2. Aplica o filtro em uma cópia do sinal (filtfilt evita atraso de fase)
    sinal_limpo = filtfilt(b, a, sinal)
    
    # 3. Encontra os cruzamentos por zero (apenas bordas de subida)
    # Compara o sinal atual com o deslocado em 1 amostra para achar a transição negativo -> positivo
    cruzamentos = np.where((sinal_limpo[:-1] < 0) & (sinal_limpo[1:] >= 0))[0]
    
    if len(cruzamentos) < 2:
        print("Erro: Não há ciclos completos suficientes na amostragem.")
        return sinal
        
    # 4. Pega o índice do primeiro e do último cruzamento ascendente
    indice_inicial = cruzamentos[0]
    indice_final = cruzamentos[-1]
    
    numero_de_ciclos = len(cruzamentos) - 1
    print(f"Ciclos inteiros detectados: {numero_de_ciclos}")
    
    # Retorna apenas a fatia do sinal original que contém períodos matematicamente exatos
    return sinal[indice_inicial:indice_final]

def plotar_fft_nitida(sinal_cortado, taxa_amostragem):
    """
    Calcula e plota a FFT do sinal contendo um número exato de ciclos.
    O eixo Y é convertido para decibéis (dBV) e o eixo X é ajustado para Nyquist + 10%.
    """
    N = len(sinal_cortado)
    
    # Aplicação de Janela de Hann para suavização das bordas
    janela = np.hanning(N)
    sinal_janelado = sinal_cortado * janela
    
    # Cálculo da FFT
    yf = fft(sinal_janelado)
    xf = fftfreq(N, 1.0 / taxa_amostragem)
    
    # Pega apenas a metade positiva do espectro
    xf_positivo = xf[:N//2]
    
    # Normaliza a amplitude linear (em Volts)
    amplitude_linear = (2.0/N) * np.abs(yf[:N//2]) * 2 
    
    # Previne o erro matemático de log10(0) limitando o valor mínimo a algo minúsculo
    amplitude_linear_segura = np.maximum(amplitude_linear, 1e-12)
    
    # Converte a amplitude para Decibéis (dBV - referência de 1 Volt)
    yf_db = 20 * np.log10(amplitude_linear_segura)

    # Plotagem
    plt.figure(figsize=(10, 5))
    plt.plot(xf_positivo, yf_db, color='blue', linewidth=1.5)
    
    plt.title('Espectro de Frequência de Supraharmônicos')
    plt.xlabel('Frequência (Hz)')
    plt.ylabel('Magnitude (dBV)')
    
    # Grade principal e secundária para facilitar a leitura em log
    plt.grid(True, which="both", ls="-", alpha=0.5)
    
    # Configuração inteligente dos eixos
    frequencia_nyquist = taxa_amostragem / 2.0
    limite_x = frequencia_nyquist * 1.10 # Nyquist + 10%
    plt.xlim(0, limite_x) 
    
    # Opcional: Define um "chão" visual para o gráfico. 
    # Sinais abaixo de -100 dBV são puramente ruído numérico ou de quantização do ADC.
    plt.ylim(bottom=-100) 
    
    plt.tight_layout() # Garante que os rótulos não cortem na imagem
    plt.show()


def plotar_sinal_e_fft(sinal_cortado, taxa_amostragem):
    """
    Plota dois gráficos empilhados:
    1. O sinal no domínio do tempo (recortado com ciclos inteiros).
    2. A FFT do sinal no domínio da frequência (em dBV).
    """
    N = len(sinal_cortado)
    
    # --- Preparação do Domínio do Tempo ---
    # Cria um vetor de tempo iniciando em 0 até o tamanho do sinal recortado
    # Multiplicamos por 1000 para exibir em milissegundos (ms), fica mais fácil de ler
    tempo_ms = (np.arange(N) / taxa_amostragem) * 1000.0
    
    # --- Preparação do Domínio da Frequência (FFT) ---
    janela = np.hanning(N)
    sinal_janelado = sinal_cortado * janela
    
    yf = fft(sinal_janelado)
    xf = fftfreq(N, 1.0 / taxa_amostragem)
    
    xf_positivo = xf[:N//2]
    amplitude_linear = (2.0/N) * np.abs(yf[:N//2]) * 2 
    amplitude_linear_segura = np.maximum(amplitude_linear, 1e-12)
    yf_db = 20 * np.log10(amplitude_linear_segura)

    # --- Criação da Figura com Subplots ---
    # Cria 1 janela com 2 gráficos (2 linhas, 1 coluna), tamanho 10x8 polegadas
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
    
    # Gráfico 1: Domínio do Tempo
    ax1.plot(tempo_ms, sinal_cortado, color='green', linewidth=1.5)
    ax1.set_title('Sinal no Tempo (Ciclos Inteiros Sincronizados)')
    ax1.set_xlabel('Tempo (ms)')
    ax1.set_ylabel('Tensão (V)')
    ax1.grid(True)
    
    # Gráfico 2: Domínio da Frequência (FFT)
    ax2.plot(xf_positivo, yf_db, color='blue', linewidth=1.5)
    ax2.set_title('Espectro de Frequência de Supraharmônicos')
    ax2.set_xlabel('Frequência (Hz)')
    ax2.set_ylabel('Magnitude (dBV)')
    ax2.grid(True, which="both", ls="-", alpha=0.5)
    
    # Ajustes do eixo X da FFT (Nyquist + 10%)
    frequencia_nyquist = taxa_amostragem / 2.0
    ax2.set_xlim(0, frequencia_nyquist * 1.10)
    ax2.set_ylim(bottom=-100) 
    
    # Ajusta os espaçamentos para os textos não se sobreporem
    plt.tight_layout() 
    plt.show()

# ==========================================
# Execução Principal (CLI)
# ==========================================
if __name__ == "__main__":
    # 1. Configurando o interpretador de argumentos
    parser = argparse.ArgumentParser(
        description="Analisa dados do ADC de alta frequência e plota a FFT otimizada."
    )
    
    # Argumentos obrigatórios
    parser.add_argument("arquivo", type=str, help="Caminho para o arquivo de dados (ex: ./amostras.csv)")
    parser.add_argument("taxa_amostragem", type=float, help="Taxa de amostragem em Hz (ex: 10240 para 10.24 kHz)")
    
    # Argumento opcional (para o ganho da placa)
    parser.add_argument("--ganho", type=float, default=1.0, 
                        help="Ganho da PCB para converter ADC para Volts (padrão: 1.0)")
    
    # Faz a leitura da linha de comando
    args = parser.parse_args()
    
    arquivo = args.arquivo
    taxa_amostragem = args.taxa_amostragem
    ganho_placa = args.ganho
    
    print(f"Iniciando análise...")
    print(f"Arquivo: {arquivo}")
    print(f"Taxa de Amostragem: {taxa_amostragem} Hz")
    


    # 2. Carregar os dados do arquivo
    try:
        # skiprows=1: Ignora a primeira linha (cabeçalho de texto)
        # usecols=2: Lê apenas a 3ª coluna (índice 2, correspondente a "Tensao_ADC_V")
        onda_bruta = np.loadtxt(arquivo, delimiter=',', skiprows=1, usecols=2)
        
    except ValueError as ve:
        print(f"Erro de valor ao ler o arquivo (verifique o formato das colunas): {ve}")
        sys.exit(1)
    except Exception as e:
        print(f"Erro inesperado ao tentar ler o arquivo '{arquivo}': {e}")
        sys.exit(1)



    # # 2. Carregar os dados do arquivo
    # try:
    #     # Lê o CSV. Assumindo que é uma coluna simples de valores.
    #     # Se houver um cabeçalho no CSV (ex: "Tensao_ADC"), use skiprows=1 para pular a primeira linha.
    #     onda_bruta = np.loadtxt(arquivo, delimiter=',', comments='#')
    # except Exception as e:
    #     print(f"Erro ao tentar ler o arquivo '{arquivo}': {e}")
    #     sys.exit(1)
        
    # # Verifica se os dados foram lidos corretamente
    # if len(onda_bruta) == 0:
    #     print("Erro: O arquivo está vazio.")
    #     sys.exit(1)
        
    print(f"Amostras carregadas com sucesso: {len(onda_bruta)} pontos.")

    # 3. Converter escala de tensão
    onda_real = converter_adc_para_tensao(onda_bruta, ganho_placa)
    
    # 4. Extrair ciclos inteiros para evitar o vazamento espectral
    onda_sincronizada = extrair_ciclos_inteiros(onda_real, taxa_amostragem)
    
    # # 5. Calcular e plotar a FFT
    # plotar_fft_nitida(onda_sincronizada, taxa_amostragem)

    plotar_sinal_e_fft(onda_sincronizada, taxa_amostragem)