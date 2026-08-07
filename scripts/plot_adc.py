# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pandas",
#     "matplotlib",
#     "numpy",
# ]
# ///

import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import sys

def main():
    parser = argparse.ArgumentParser(description="Plota a onda e a FFT de dados do ADC em busca de harmônicas.")
    parser.add_argument("arquivo", type=str, help="Caminho para o arquivo CSV (ex: amostras_100kHz.csv)")
    parser.add_argument("--fs", type=float, required=True, help="Frequência de amostragem em Hz (ex: 100000)")
    parser.add_argument("--inicio", type=int, default=0, help="Amostra inicial para o recorte (padrão: 0)")
    parser.add_argument("--limite", type=int, default=None, help="Número de amostras para ler a partir do início")
    
    args = parser.parse_args()

    # 1. Carregar os dados
    try:
        df = pd.read_csv(args.arquivo)
    except Exception as e:
        print(f"Erro ao ler o arquivo '{args.arquivo}': {e}")
        sys.exit(1)

    coluna_tensao = 'Tensao_Real_V'
    if coluna_tensao not in df.columns:
        print(f"Erro: A coluna '{coluna_tensao}' não foi encontrada no CSV.")
        sys.exit(1)

    # 2. Fazer o recorte (Slicing) via software
    inicio = args.inicio
    limite = args.limite if args.limite is not None else len(df)
    df_recorte = df.iloc[inicio : inicio + limite].copy()
    
    N = len(df_recorte)
    if N == 0:
        print("Erro: O recorte resultou em zero amostras.")
        sys.exit(1)

    # Extrair os valores de tensão e criar o vetor de tempo
    y = df_recorte[coluna_tensao].values
    t = np.arange(N) / args.fs

    # 3. Processamento da FFT
    # Removemos a média (componente DC / Offset) para o pico 0 Hz não destruir a escala
    y_ac = y - np.mean(y) 
    
    Y = np.fft.fft(y_ac)
    freqs = np.fft.fftfreq(N, d=1/args.fs)

    # O Teorema de Nyquist diz que só a metade positiva das frequências é útil
    mascara_positiva = freqs > 0
    freqs_pos = freqs[mascara_positiva]
    # Normalização da magnitude para refletir a amplitude real em Volts
    mag_pos = (2.0 / N) * np.abs(Y[mascara_positiva])

    # ==========================================
    # 4. PLOTAGEM DOS GRÁFICOS
    # ==========================================
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8))

    # Gráfico da Onda no Tempo
    ax1.plot(t * 1000, y, color='#1f77b4', linewidth=1) # Tempo convertido para milissegundos
    ax1.set_title(f"Forma de Onda no Tempo | {N} amostras | Fs = {args.fs/1000} kHz", fontweight='bold')
    ax1.set_xlabel("Tempo (ms)")
    ax1.set_ylabel("Tensão (V)")
    ax1.grid(True, linestyle='--', alpha=0.7)

    # Gráfico da FFT (Espectro de Frequências)
    ax2.plot(freqs_pos / 1000, mag_pos, color='#d62728', linewidth=1) # Frequência em kHz
    ax2.set_title("Análise de Fourier (FFT) - Espectro de Supraharmônicas", fontweight='bold')
    ax2.set_xlabel("Frequência (kHz)")
    ax2.set_ylabel("Magnitude (V) - Escala Log")
    ax2.set_yscale('log') # Escala Logarítmica para ver distúrbios microscópicos
    
    # Limita o eixo X até a frequência de Nyquist (Fs / 2)
    ax2.set_xlim(0, (args.fs / 2) / 1000)
    ax2.grid(True, which="both", linestyle='--', alpha=0.5)

    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()