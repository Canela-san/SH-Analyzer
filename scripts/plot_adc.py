#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "matplotlib>=3.10.9",
#     "numpy",
#     "scipy>=1.15.3",
# ]
# ///
"""
==============================================================================
 plot_adc.py -- Visualizador de forma de onda e espectro (FFT) do SH-Analyzer
==============================================================================

ÍNDICE
------
  1. PARA QUE SERVE
  2. FORMATO DO ARQUIVO DE ENTRADA
  3. JANELAMENTO NO TEMPO (--inicio / --fim)
  4. ANÁLISE EM FREQUÊNCIA (--fft)
     4.1 O problema do vazamento espectral (spectral leakage)
     4.2 Estratégia adotada: fundamental + cruzamento por zero interpolado
     4.3 Analisando distúrbios momentâneos (--fft N)
  5. CONVERSÃO PARA TENSÃO (--faixa / --ganho / --formato)
  6. EXEMPLOS DE USO

1. PARA QUE SERVE
------------------
Este script lê o arquivo binário bruto gravado pelo `ler_adc` na BeagleBone
(uma sequência de amostras de 16 bits do ADS8688, sem cabeçalho e sem
preâmbulo -- 2 bytes por amostra) e:

    a) Plota a forma de onda no domínio do tempo, com o eixo X já
       convertido para segundos/milissegundos a partir da frequência de
       amostragem informada; e, opcionalmente,
    b) Calcula e plota o espectro de frequência (FFT) em dBV, usando uma
       janela de dados recortada para conter um número INTEIRO de ciclos
       da frequência fundamental da rede -- o que é essencial para uma
       FFT nítida (ver seção 4).

2. FORMATO DO ARQUIVO DE ENTRADA
---------------------------------
Arquivo binário puro (little-endian), 1 amostra = 2 bytes = 1 int16 (ou
uint16, ver --formato), contendo apenas o dado de conversão do ADC. É
exatamente o que `firmware/ler_adc.c` grava em `supraharmonicos_raw.bin`
(nenhum preâmbulo é gravado -- ver `firmware/spi_core.asm`).

3. JANELAMENTO NO TEMPO (--inicio / --fim)
--------------------------------------------
Uma coleta longa pode ter milhões de amostras (cada buffer de produção tem
1.048.576 amostras) -- carregar e plotar tudo de uma vez é lento e ilegível.
--inicio/--fim selecionam, em NÚMERO DE AMOSTRAS (não em tempo), a fatia do
arquivo a ser usada. O arquivo é lido com `numpy.memmap`, então apenas a
fatia pedida é efetivamente carregada na memória -- importante para
arquivos de dezenas/centenas de MB.

4. ANÁLISE EM FREQUÊNCIA (--fft)
-----------------------------------

4.1 O problema do vazamento espectral (spectral leakage)
    A FFT assume implicitamente que o trecho analisado se repete
    infinitamente. Se o trecho não contém um número inteiro de ciclos da
    fundamental, há uma descontinuidade na "emenda" entre o fim e o
    início do trecho repetido, e essa descontinuidade "vaza" energia para
    frequências vizinhas (o vazamento espectral), borrando picos que
    deveriam ser nítidos -- especialmente ruim para achar supraharmônicos
    de baixa amplitude perto de uma fundamental de amplitude alta.

4.2 Estratégia adotada: fundamental + cruzamento por zero interpolado
    Dados reais têm ruído, então não dá para simplesmente contar amostras
    e cortar em "um período redondo". A estratégia usada aqui:

      1) Estima-se a frequência fundamental por FFT, buscando o pico de
         maior energia dentro de uma faixa esperada (--freq-min/--freq-max,
         por padrão 45-65 Hz, cobrindo redes de 50 e 60 Hz). Essa é só uma
         estimativa GROSSEIRA (resolução limitada pelo tamanho da FFT).
      2) Filtra-se o sinal com um passa-baixa (Butterworth) com corte um
         pouco acima da fundamental estimada, para isolar a fundamental e
         eliminar ruído/supraharmônicos que criariam cruzamentos por zero
         espúrios.
      3) Encontra-se TODOS os cruzamentos por zero ascendentes do sinal
         filtrado, com INTERPOLAÇÃO LINEAR entre as duas amostras vizinhas
         -- ou seja, o instante do cruzamento não fica preso à grade de
         amostragem, e sim numa posição fracionária entre amostras.
      4) Refina-se o período: em vez de usar um único intervalo entre dois
         cruzamentos (sensível a ruído), usa-se
         (último cruzamento - primeiro cruzamento) / número de ciclos.
         Isso faz com que o erro de estimativa seja diluído por todos os
         ciclos observados, em vez de concentrado num só -- quanto mais
         ciclos disponíveis, mais preciso o período estimado.
      5) O trecho enviado à FFT é cortado exatamente nos cruzamentos por
         zero (arredondados para a amostra mais próxima -- o erro
         residual disso é uma fração de amostra, desprezível), e ainda
         assim uma janela de Hann é aplicada como segurança adicional
         contra qualquer imperfeição residual (a rede real nunca é
         perfeitamente periódica).

4.3 Analisando distúrbios momentâneos (--fft N)
    Por padrão (--fft sem argumento), usa-se TODOS os ciclos completos
    disponíveis dentro da janela selecionada por --inicio/--fim. Para
    investigar um distúrbio breve (ex.: um afundamento de tensão que dura
    poucos ciclos), passe o número de ciclos a analisar, por exemplo
    `--fft 10` analisa só os primeiros 10 ciclos completos encontrados
    dentro da janela -- combine com --inicio/--fim para posicionar essa
    janela exatamente onde o distúrbio ocorreu.

    O trecho efetivamente usado na FFT é sempre destacado (sombreado) no
    gráfico do domínio do tempo, para deixar claro o que entrou no cálculo.

5. CONVERSÃO PARA TENSÃO (--faixa / --offset / --ganho / --formato)
-----------------------------------------------------------------------
O ADS8688 devolve um código de 16 bits por amostra. Para converter esse
código em Volts:

    tensao_no_ADC = codigo * (faixa / 65536)      [--formato uint16, padrão]
                                                    (unipolar, 0 .. +faixa)
    tensao_no_ADC = codigo * (faixa / 32768)      [--formato int16]
                                                    (bipolar, ex.: ±10.24 V)

    tensao_final = (tensao_no_ADC - offset) * ganho

--offset tem um padrão AUTOMÁTICO: 0 V para --formato int16 (que já é
bipolar, centrado em 0) e faixa/2 para --formato uint16 -- ou seja, se a
faixa unipolar do ADC é 0..10.24 V, o padrão já subtrai 5.12 V para
devolver a onda CA pura, centralizada em 0 V (-5.12 V .. +5.12 V), em vez
da tensão bruta 0..10.24 V. Se o offset real do seu ADC/sensor não for
exatamente metade da faixa (erro de calibração), informe --offset
manualmente.

Ajuste --faixa conforme o registrador de range configurado no ADS8688 e
--ganho conforme a calibração do seu sensor/PCB.

6. EXEMPLOS DE USO
---------------------
  # Plota o arquivo inteiro no tempo, amostrado a 102.4 kHz
  python3 plot_adc.py supraharmonicos_raw.bin -f 102400

  # Só as amostras 125 a 3000 (útil para inspecionar um trecho específico)
  python3 plot_adc.py supraharmonicos_raw.bin -f 102400 --inicio 125 --fim 3000

  # Forma de onda + FFT usando todos os ciclos completos da janela
  python3 plot_adc.py supraharmonicos_raw.bin -f 102400 --fft

  # FFT de alta resolução temporal: só 10 ciclos, a partir da amostra 50000
  # (bom para flagrar um distúrbio momentâneo)
  python3 plot_adc.py supraharmonicos_raw.bin -f 102400 --inicio 50000 --fft 10

  # Convertendo para tensão real (ADC ±10.24 V, sensor com ganho 19.53)
  python3 plot_adc.py supraharmonicos_raw.bin -f 102400 --faixa 10.24 --ganho 19.53 --fft

Rode `python3 plot_adc.py --help` para a referência completa de argumentos.
==============================================================================
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt
from scipy.fft import rfft, rfftfreq


# ==============================================================================
# 1. LEITURA E JANELAMENTO DOS DADOS
# ==============================================================================

def carregar_amostras(caminho: Path, formato: str) -> np.memmap:
    """
    Abre o arquivo binário bruto em modo memory-map (não carrega o arquivo
    inteiro na RAM -- só as páginas efetivamente acessadas depois, na hora
    de fatiar com --inicio/--fim).
    """
    dtype = np.dtype("<i2") if formato == "int16" else np.dtype("<u2")
    try:
        amostras = np.memmap(caminho, dtype=dtype, mode="r")
    except FileNotFoundError:
        raise SystemExit(f"Erro: arquivo '{caminho}' não encontrado.")
    except ValueError as e:
        raise SystemExit(f"Erro ao abrir '{caminho}': {e}")

    if amostras.size == 0:
        raise SystemExit(f"Erro: '{caminho}' está vazio (0 amostras).")
    return amostras


def selecionar_intervalo(amostras: np.memmap, inicio: int, fim: int | None):
    """
    Aplica --inicio/--fim (em número de amostras) sobre o array completo.
    Sem --fim, usa até o final do arquivo. Sem --inicio, usa desde o começo.
    """
    total = len(amostras)
    inicio = max(0, inicio)
    fim = total if fim is None else min(fim, total)

    if inicio >= fim:
        raise SystemExit(
            f"Erro: intervalo inválido (--inicio {inicio} >= --fim {fim}). "
            f"O arquivo tem {total} amostras no total."
        )

    return np.asarray(amostras[inicio:fim]), inicio, fim, total


def converter_para_tensao(codigos: np.ndarray, faixa: float, ganho: float,
                           formato: str, offset: float) -> np.ndarray:
    """Converte códigos brutos do ADC (int16/uint16) para Volts (ver seção 5).

    'offset' é subtraído da tensão do ADC ANTES de aplicar o ganho -- serve
    para remover o nível DC de uma faixa unipolar (--formato uint16), cuja
    tensão do ADC varia entre 0 e +faixa, e assim recuperar a onda CA pura
    centralizada em 0 V (ex.: faixa=10.24 -> offset=5.12 -> onda entre
    -5.12 V e +5.12 V no lugar de 0..10.24 V).
    """
    codigos = codigos.astype(np.float64)
    if formato == "int16":
        tensao_adc = codigos * (faixa / 32768.0)   # bipolar: -faixa .. +faixa
    else:
        tensao_adc = codigos * (faixa / 65536.0)   # unipolar: 0 .. +faixa
    return (tensao_adc - offset) * ganho


# ==============================================================================
# 2. ESTIMATIVA DA FREQUÊNCIA FUNDAMENTAL E JANELAMENTO EM CICLOS INTEIROS
# ==============================================================================

def estimar_frequencia_fundamental(sinal: np.ndarray, fs: float,
                                    freq_min: float, freq_max: float) -> float:
    """
    Estimativa GROSSEIRA da fundamental: pico de maior energia da FFT
    dentro de [freq_min, freq_max]. Resolução limitada por fs/N -- serve
    só para escolher o corte do filtro passa-baixa; a precisão real do
    período vem do refinamento por cruzamentos por zero (ver
    refinar_periodo_fundamental).
    """
    n = len(sinal)
    if n < 16:
        raise SystemExit("Erro: poucos dados para estimar a frequência fundamental.")

    janela = np.hanning(n)
    espectro = np.abs(rfft((sinal - np.mean(sinal)) * janela))
    freqs = rfftfreq(n, 1.0 / fs)

    banda = (freqs >= freq_min) & (freqs <= freq_max)
    if not np.any(banda):
        raise SystemExit(
            f"Erro: nenhuma componente de frequência encontrada entre "
            f"{freq_min} Hz e {freq_max} Hz. Ajuste --freq-min/--freq-max "
            f"ou verifique a frequência de amostragem (-f)."
        )

    idx_pico = np.argmax(espectro[banda])
    return float(freqs[banda][idx_pico])


def detectar_cruzamentos_por_zero(sinal_filtrado: np.ndarray) -> np.ndarray:
    """
    Cruzamentos por zero ASCENDENTES do sinal filtrado, com posição
    FRACIONÁRIA (interpolação linear entre a amostra negativa e a
    positiva) -- muito mais preciso do que só pegar o índice inteiro mais
    próximo, principalmente em fs baixa relativa à fundamental.
    Retorna as posições em número de amostras (float).
    """
    indices = np.where((sinal_filtrado[:-1] < 0) & (sinal_filtrado[1:] >= 0))[0]
    if len(indices) == 0:
        return np.array([])

    y0 = sinal_filtrado[indices]
    y1 = sinal_filtrado[indices + 1]
    fracao = -y0 / (y1 - y0)   # 0..1, posição do zero entre as duas amostras
    return indices + fracao


def refinar_periodo_fundamental(posicoes_cruzamento: np.ndarray, fs: float):
    """
    Refina o período usando TODOS os cruzamentos disponíveis, não só um
    par: periodo = (ultimo - primeiro) / n_ciclos. O erro de detecção de
    cada cruzamento individual é assim diluído por todos os ciclos
    observados, em vez de concentrado num único intervalo -- quanto mais
    ciclos, mais preciso o período (e, portanto, a frequência) resultante.
    """
    n_ciclos_disponiveis = len(posicoes_cruzamento) - 1
    if n_ciclos_disponiveis < 1:
        raise SystemExit(
            "Erro: cruzamentos por zero insuficientes para estimar o período "
            "da fundamental (janela de dados curta demais ou sinal sem "
            "componente periódica clara nessa faixa de frequência)."
        )
    periodo_amostras = (posicoes_cruzamento[-1] - posicoes_cruzamento[0]) / n_ciclos_disponiveis
    periodo_segundos = periodo_amostras / fs
    return periodo_segundos, n_ciclos_disponiveis


def recortar_ciclos_inteiros(sinal: np.ndarray, fs: float, freq_min: float,
                              freq_max: float, n_ciclos_pedido: int | None):
    """
    Recorta 'sinal' para conter um número inteiro de ciclos da
    fundamental, alinhado ao primeiro cruzamento por zero ascendente
    detectado. Ver seção 4.2 do cabeçalho do arquivo para a estratégia.

    n_ciclos_pedido:
        None  -> usa todos os ciclos completos disponíveis na janela.
        int N -> usa só os primeiros N ciclos completos (--fft N).

    Retorna (sinal_recortado, idx_inicio, idx_fim, f0_estimada, n_ciclos_usados).
    """
    freq_estimada = estimar_frequencia_fundamental(sinal, fs, freq_min, freq_max)

    # Remove o nível DC antes de filtrar/detectar cruzamentos: sem isso, um
    # sinal com offset (ex.: faixa unipolar, ou um pequeno desvio de
    # calibração) poderia nunca cruzar o zero literal e a detecção falharia.
    # Centralizando em torno da própria média, o critério "cruzamento
    # ascendente por zero" funciona igual para sinais bipolares e unipolares.
    sinal_centrado = sinal - np.mean(sinal)

    # Corte do passa-baixa: acima o bastante da fundamental para não
    # atenuá-la, abaixo do 3o harmônico (rede) para eliminar ruído/
    # supraharmônicos que atrapalhariam a detecção de cruzamento por zero.
    corte = min(freq_estimada * 2.5, 0.45 * fs)
    b, a = butter(4, corte / (fs / 2.0), btype="low")
    sinal_filtrado = filtfilt(b, a, sinal_centrado)

    posicoes_cruzamento = detectar_cruzamentos_por_zero(sinal_filtrado)
    if len(posicoes_cruzamento) < 2:
        raise SystemExit(
            "Erro: não foi possível encontrar ciclos completos na janela "
            "selecionada. Tente aumentar o intervalo com --inicio/--fim."
        )

    periodo_s, n_ciclos_disponiveis = refinar_periodo_fundamental(posicoes_cruzamento, fs)
    f0 = 1.0 / periodo_s

    if n_ciclos_pedido is None or n_ciclos_pedido <= 0:
        n_ciclos_usados = n_ciclos_disponiveis
    else:
        n_ciclos_usados = min(n_ciclos_pedido, n_ciclos_disponiveis)
        if n_ciclos_pedido > n_ciclos_disponiveis:
            print(
                f"Aviso: --fft pediu {n_ciclos_pedido} ciclos, mas só "
                f"{n_ciclos_disponiveis} ciclos completos estão disponíveis "
                f"na janela selecionada. Usando {n_ciclos_usados}.",
                file=sys.stderr,
            )

    pos_inicio = posicoes_cruzamento[0]
    pos_fim = posicoes_cruzamento[n_ciclos_usados]

    idx_inicio = int(round(pos_inicio))
    idx_fim = int(round(pos_fim))

    return sinal[idx_inicio:idx_fim], idx_inicio, idx_fim, f0, n_ciclos_usados


# ==============================================================================
# 3. CÁLCULO DA FFT
# ==============================================================================

def calcular_espectro_dbv(sinal: np.ndarray, fs: float):
    """FFT em dBV com janela de Hann (ver seção 4.2 sobre a dupla proteção
    contra vazamento: recorte em ciclos inteiros + janelamento).

    A amplitude é corrigida pelo GANHO COERENTE da janela (média dos seus
    valores) -- sem essa correção, a amplitude reportada fica sistemati-
    camente abaixo da real (para a janela de Hann, ~6 dB abaixo), porque a
    própria janela atenua a energia do sinal antes da FFT.
    """
    n = len(sinal)
    janela = np.hanning(n)
    ganho_coerente = np.mean(janela)

    sinal_janelado = (sinal - np.mean(sinal)) * janela
    espectro = rfft(sinal_janelado)
    freqs = rfftfreq(n, 1.0 / fs)

    amplitude_linear = (2.0 / (n * ganho_coerente)) * np.abs(espectro)
    amplitude_linear[0] /= 2.0   # componente DC não é duplicada como as demais
    amplitude_segura = np.maximum(amplitude_linear, 1e-12)
    amplitude_db = 20 * np.log10(amplitude_segura)

    return freqs, amplitude_db


# ==============================================================================
# 4. PLOTAGEM
# ==============================================================================

def escolher_unidade_tempo(duracao_s: float):
    """Escolhe ms ou s para o eixo do tempo conforme a duração da janela."""
    if duracao_s < 2.0:
        return 1000.0, "Tempo (ms)"
    return 1.0, "Tempo (s)"


def plotar(tensao: np.ndarray, fs: float, idx_inicio_arquivo: int,
           info_fft: dict | None, titulo_arquivo: str, caminho_saida: Path | None):
    n = len(tensao)
    fator_tempo, rotulo_tempo = escolher_unidade_tempo(n / fs)
    tempo = (np.arange(n) / fs) * fator_tempo

    if info_fft is None:
        fig, ax_tempo = plt.subplots(figsize=(10, 5))
    else:
        fig, (ax_tempo, ax_fft) = plt.subplots(2, 1, figsize=(10, 8))

    # --- Domínio do tempo ---
    ax_tempo.plot(tempo, tensao, color="tab:green", linewidth=1.0)
    ax_tempo.set_title(f"Forma de onda -- amostras {idx_inicio_arquivo} .. "
                        f"{idx_inicio_arquivo + n} de '{titulo_arquivo}'")
    ax_tempo.set_xlabel(rotulo_tempo)
    ax_tempo.set_ylabel("Tensão (V)")
    ax_tempo.grid(True, alpha=0.4)

    # --- Domínio da frequência (opcional) ---
    if info_fft is not None:
        # Sombreia, no gráfico de tempo, exatamente o trecho usado na FFT.
        ini_janela = info_fft["idx_inicio_local"] / fs * fator_tempo
        fim_janela = info_fft["idx_fim_local"] / fs * fator_tempo
        ax_tempo.axvspan(ini_janela, fim_janela, color="tab:orange", alpha=0.20,
                          label=f"Janela da FFT ({info_fft['n_ciclos']} ciclo(s))")
        ax_tempo.legend(loc="upper right", fontsize=9)

        freqs, amplitude_db = info_fft["freqs"], info_fft["amplitude_db"]
        ax_fft.plot(freqs, amplitude_db, color="tab:blue", linewidth=1.2)
        ax_fft.set_title(
            f"Espectro de Frequência -- f0 estimada = {info_fft['f0']:.3f} Hz "
            f"| {info_fft['n_ciclos']} ciclo(s) completo(s)"
        )
        ax_fft.set_xlabel("Frequência (Hz)")
        ax_fft.set_ylabel("Magnitude (dBV)")
        ax_fft.grid(True, which="both", ls="-", alpha=0.4)

        nyquist = fs / 2.0
        ax_fft.set_xlim(0, nyquist * 1.10)
        ax_fft.set_ylim(bottom=-100)

    plt.tight_layout()

    if caminho_saida is not None:
        fig.savefig(caminho_saida, dpi=150)
        print(f"Gráfico salvo em '{caminho_saida}'.")
    else:
        plt.show()


# ==============================================================================
# 5. LINHA DE COMANDO
# ==============================================================================

def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plot_adc.py",
        description=(
            "Plota (e opcionalmente calcula a FFT de) uma captura bruta do "
            "SH-Analyzer, gravada por firmware/ler_adc.c. Rode com --help "
            "para exemplos de uso; o cabeçalho do script (docstring) tem a "
            "explicação completa da técnica usada para evitar vazamento "
            "espectral na FFT."
        ),
        epilog=(
            "Exemplos:\n"
            "  %(prog)s captura.bin -f 102400\n"
            "  %(prog)s captura.bin -f 102400 --inicio 125 --fim 3000\n"
            "  %(prog)s captura.bin -f 102400 --fft\n"
            "  %(prog)s captura.bin -f 102400 --inicio 50000 --fft 10\n"
            "  %(prog)s captura.bin -f 102400 --faixa 10.24 --ganho 19.53 --fft\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "arquivo", type=Path,
        help="Caminho do arquivo binário bruto (ex.: supraharmonicos_raw.bin)."
    )
    parser.add_argument(
        "-f", "--frequencia", type=float, required=True,
        metavar="HZ",
        help="Frequência de amostragem usada na coleta, em Hz (ex.: -f 102400). "
             "Define o eixo do tempo e o eixo de frequência da FFT."
    )
    parser.add_argument(
        "--inicio", type=int, default=0, metavar="N",
        help="Índice da primeira amostra a usar (padrão: 0, início do arquivo)."
    )
    parser.add_argument(
        "--fim", type=int, default=None, metavar="N",
        help="Índice (exclusive) da última amostra a usar (padrão: até o "
             "final do arquivo)."
    )
    parser.add_argument(
        "--fft", nargs="?", type=int, const=0, default=None, metavar="N_CICLOS",
        help="Também calcula e plota a FFT. Sem valor, usa todos os ciclos "
             "completos da fundamental disponíveis na janela selecionada "
             "por --inicio/--fim. Com um valor (ex.: --fft 10), usa só os "
             "primeiros N ciclos completos -- útil para analisar distúrbios "
             "momentâneos (combine com --inicio para posicionar a janela)."
    )
    parser.add_argument(
        "--freq-min", type=float, default=45.0, metavar="HZ",
        help="Limite inferior da faixa de busca da frequência fundamental "
             "(padrão: 45 Hz -- cobre redes de 50/60 Hz)."
    )
    parser.add_argument(
        "--freq-max", type=float, default=65.0, metavar="HZ",
        help="Limite superior da faixa de busca da frequência fundamental "
             "(padrão: 65 Hz)."
    )
    parser.add_argument(
        "--formato", choices=["int16", "uint16"], default="uint16",
        help="Como interpretar os códigos brutos de 16 bits do ADC: "
             "'uint16' (binário reto, faixa unipolar, 0..+faixa -- padrão, "
             "é o formato do ADS8688 nesta placa) ou 'int16' (complemento "
             "de dois, faixa bipolar, ex.: ±10.24 V)."
    )
    parser.add_argument(
        "--faixa", type=float, default=10.24, metavar="VOLTS",
        help="Faixa de fundo de escala do ADC em Volts (padrão: 10.24, "
             "faixa bipolar default do ADS8688: ±10.24 V)."
    )
    parser.add_argument(
        "--ganho", type=float, default=1.0, metavar="FATOR",
        help="Fator de ganho do sensor/PCB para converter a tensão no ADC "
             "na tensão real da rede (padrão: 1.0, sem conversão adicional)."
    )
    parser.add_argument(
        "--offset", type=float, default=None, metavar="VOLTS",
        help="Deslocamento DC subtraído da tensão do ADC antes do ganho "
             "(padrão automático: faixa/2 para --formato uint16, o que "
             "centraliza a onda CA em torno de 0 V; 0 para --formato int16, "
             "que já é bipolar). Ajuste manualmente se o offset real do seu "
             "ADC/sensor não for exatamente metade da faixa."
    )
    parser.add_argument(
        "-o", "--salvar", type=Path, default=None, metavar="ARQUIVO.png",
        help="Salva o gráfico nesse arquivo em vez de abrir a janela "
             "interativa do matplotlib."
    )

    return parser


def main(argv=None):
    parser = montar_parser()
    args = parser.parse_args(argv)

    offset = args.offset
    if offset is None:
        offset = args.faixa / 2.0 if args.formato == "uint16" else 0.0

    amostras = carregar_amostras(args.arquivo, args.formato)
    bruto, idx_inicio, idx_fim, total = selecionar_intervalo(
        amostras, args.inicio, args.fim
    )
    tensao = converter_para_tensao(bruto, args.faixa, args.ganho, args.formato, offset)

    print(f"Arquivo: {args.arquivo}  ({total} amostras no total)")
    print(f"Conversão: --formato {args.formato} | --faixa {args.faixa} V | "
          f"--offset {offset} V | --ganho {args.ganho}")
    print(f"Janela selecionada: amostras {idx_inicio}..{idx_fim} "
          f"({len(tensao)} amostras, {len(tensao) / args.frequencia * 1000:.2f} ms)")

    info_fft = None
    if args.fft is not None:
        n_ciclos_pedido = args.fft if args.fft > 0 else None
        sinal_fft, idx_i_local, idx_f_local, f0, n_ciclos = recortar_ciclos_inteiros(
            tensao, args.frequencia, args.freq_min, args.freq_max, n_ciclos_pedido
        )
        freqs, amplitude_db = calcular_espectro_dbv(sinal_fft, args.frequencia)

        print(f"FFT: fundamental estimada f0 = {f0:.3f} Hz | "
              f"{n_ciclos} ciclo(s) completo(s) | "
              f"{len(sinal_fft)} amostras (amostras locais {idx_i_local}..{idx_f_local})")

        info_fft = {
            "freqs": freqs,
            "amplitude_db": amplitude_db,
            "f0": f0,
            "n_ciclos": n_ciclos,
            "idx_inicio_local": idx_i_local,
            "idx_fim_local": idx_f_local,
        }

    plotar(tensao, args.frequencia, idx_inicio, info_fft,
           args.arquivo.name, args.salvar)


if __name__ == "__main__":
    main()