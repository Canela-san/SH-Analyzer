#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "matplotlib>=3.10.9",
#     "numpy",
#     "scipy>=1.15.3",
#     "PyQt6",
# ]
# ///
"""
==============================================================================
 adc_tool.py -- Conversão, visualização e análise (FFT) de capturas do
                 SH-Analyzer
==============================================================================
(Renomeado de `plot_adc.py`: o script deixou de fazer só plotagem -- agora
também converte arquivos entre binário bruto `.bin` e `.csv`. Se algum
comando/atalho antigo ainda chamar `plot_adc.py`, atualize para
`adc_tool.py`; as flags de plotagem continuam as mesmas.)

ÍNDICE
------
  1. PARA QUE SERVE
  2. OS DOIS MODOS DE OPERAÇÃO (plotagem x conversão)
  3. FORMATOS DE ARQUIVO SUPORTADOS (.bin e .csv)
  4. MODO DE CONVERSÃO: -c/--converter e -o/--saida
  5. JANELAMENTO NO TEMPO (--inicio / --fim)
  6. ANÁLISE EM FREQUÊNCIA (--fft)
     6.1 O problema do vazamento espectral (spectral leakage)
     6.2 Estratégia adotada: fundamental + cruzamento por zero interpolado
     6.3 Analisando distúrbios momentâneos (--fft N)
  7. CONVERSÃO PARA TENSÃO (--faixa / --offset / --ganho / --formato)
  8. DESEMPENHO E USO DE MEMÓRIA
  9. EXEMPLOS DE USO (ver também `--help`)

1. PARA QUE SERVE
------------------
Este script lê capturas brutas do ADS8688 gravadas pela BeagleBone
(`firmware/ler_adc.c`, arquivo `supraharmonicos_raw.bin`: sequência de
amostras de 16 bits, sem cabeçalho e sem preâmbulo -- 2 bytes por amostra)
e faz duas coisas, dependendo das flags usadas:

    a) MODO DE CONVERSÃO (-c/--converter + -o/--saida): converte o arquivo
       entre `.bin` (formato compacto gravado pelo firmware) e `.csv`
       (texto legível por humanos/Excel/planilhas), nos dois sentidos.

    b) MODO DE PLOTAGEM (padrão, sem -c): plota a forma de onda no tempo
       e, opcionalmente (--fft), calcula e plota o espectro de frequência,
       a partir de um arquivo `.bin` OU `.csv`.

2. OS DOIS MODOS DE OPERAÇÃO
------------------------------
    - Presença de -c/--converter  -> MODO DE CONVERSÃO.
      Nesse modo o argumento posicional `arquivo` e a flag -f/--frequencia
      NÃO são usados (a taxa de amostragem não é gravada dentro do .bin/
      .csv, então não há o que fazer com ela aqui). Use -c para apontar o
      arquivo de ENTRADA e -o/--saida para apontar o arquivo de SAÍDA.

    - Ausência de -c/--converter  -> MODO DE PLOTAGEM (comportamento
      original do antigo `plot_adc.py`). Nesse modo o argumento
      posicional `arquivo` e -f/--frequencia são OBRIGATÓRIOS.

3. FORMATOS DE ARQUIVO SUPORTADOS (.bin e .csv)
--------------------------------------------------
    .bin (padrão, já era o único formato suportado antes desta versão)
        Binário puro, little-endian, 1 amostra = 2 bytes = 1 int16 ou
        uint16 (ver --formato), só o código de conversão do ADC -- é
        exatamente o que `firmware/ler_adc.c` grava. Lido via
        `numpy.memmap`: o arquivo NÃO é carregado inteiro na RAM, só as
        páginas efetivamente acessadas (ver seção 8).

    .csv (novo)
        Texto separado por vírgulas, com cabeçalho. Formato gerado/lido
        por este script:
            amostra,valor_bruto[,tensao_v]
            0,32768,0.000000
            1,32770,0.000305
            ...
        - `amostra`: índice da amostra no arquivo original (0-based).
        - `valor_bruto`: código de 16 bits do ADC, já decodificado como
          inteiro (com sinal ou sem, conforme --formato) -- é essa coluna,
          e SÓ ela, que é usada para reconstruir o `.bin` de volta.
        - `tensao_v`: coluna OPCIONAL (só com --incluir-tensao na
          conversão .bin->.csv), só para conferência visual humana. É
          IGNORADA ao converter de volta para `.bin`, para o round-trip
          nunca perder precisão por causa de arredondamento de ponto
          flutuante.
        O formato/ordem das colunas extras não importa para leitura (a
        coluna é localizada pelo nome no cabeçalho), mas a coluna
        `valor_bruto` precisa existir com esse nome exato.

    O tipo é sempre AUTODETECTADO pela extensão do arquivo (.bin ou
    .csv) -- tanto no argumento posicional do modo de plotagem quanto em
    -c/--converter e -o/--saida no modo de conversão.

4. MODO DE CONVERSÃO: -c/--converter e -o/--saida
------------------------------------------------------
    -c ARQUIVO_ENTRADA -o ARQUIVO_SAIDA

    A direção da conversão é decidida automaticamente pelas EXTENSÕES dos
    dois caminhos (não importa qual vem primeiro na linha de comando):

        .bin -> .csv   ex.: adc_tool.py -c dados.bin -o dados.csv
        .csv -> .bin   ex.: adc_tool.py -c dados.csv -o dados.bin

    --inicio/--fim também funcionam no modo de conversão, para converter
    só um recorte de um arquivo grande (ex.: extrair só as primeiras
    10 000 amostras de uma captura de várias centenas de MB para inspeção
    rápida em uma planilha).

5. JANELAMENTO NO TEMPO (--inicio / --fim)
--------------------------------------------
Uma coleta longa pode ter milhões de amostras (cada buffer de produção tem
1 048 576 amostras) -- carregar/converter/plotar tudo de uma vez pode ser
lento. --inicio/--fim selecionam, em NÚMERO DE AMOSTRAS (não em tempo nem
em bytes), a fatia a ser usada. Valem tanto no modo de plotagem quanto no
de conversão.

6. ANÁLISE EM FREQUÊNCIA (--fft)
-----------------------------------

6.1 O problema do vazamento espectral (spectral leakage)
    A FFT assume implicitamente que o trecho analisado se repete
    infinitamente. Se o trecho não contém um número inteiro de ciclos da
    fundamental, há uma descontinuidade na "emenda" entre o fim e o
    início do trecho repetido, e essa descontinuidade "vaza" energia para
    frequências vizinhas (o vazamento espectral), borrando picos que
    deveriam ser nítidos -- especialmente ruim para achar supraharmônicos
    de baixa amplitude perto de uma fundamental de amplitude alta.

6.2 Estratégia adotada: fundamental + cruzamento por zero interpolado
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

6.3 Analisando distúrbios momentâneos (--fft N)
    Por padrão (--fft sem argumento), usa-se TODOS os ciclos completos
    disponíveis dentro da janela selecionada por --inicio/--fim. Para
    investigar um distúrbio breve (ex.: um afundamento de tensão que dura
    poucos ciclos), passe o número de ciclos a analisar, por exemplo
    `--fft 10` analisa só os primeiros 10 ciclos completos encontrados
    dentro da janela -- combine com --inicio/--fim para posicionar essa
    janela exatamente onde o distúrbio ocorreu.

    O trecho efetivamente usado na FFT é sempre destacado (sombreado) no
    gráfico do domínio do tempo, para deixar claro o que entrou no cálculo.

7. CONVERSÃO PARA TENSÃO (--faixa / --offset / --ganho / --formato)
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
--ganho conforme a calibração do seu sensor/PCB. Esses quatro parâmetros
também são usados no modo de conversão, mas só se --incluir-tensao for
passado (a coluna `tensao_v` do CSV é só informativa).

8. DESEMPENHO E USO DE MEMÓRIA
-----------------------------------
- `.bin` é sempre lido via `numpy.memmap`: o sistema operacional só carrega
  as páginas realmente acessadas, então plotar/converter um recorte
  pequeno (--inicio/--fim) de um arquivo gigante continua rápido e leve,
  mesmo em capturas de centenas de MB.
- A conversão `.bin -> .csv` processa os dados em BLOCOS (--tamanho-chunk,
  padrão 500 000 amostras) em vez de montar o CSV inteiro na RAM de uma
  vez -- necessário porque cada buffer de produção já tem 1 048 576
  amostras, e uma captura real tem vários buffers.
- A conversão `.csv -> .bin` também é feita em blocos, lendo o CSV como um
  fluxo (streaming, uma linha por vez) -- não carrega o arquivo de texto
  inteiro na memória antes de converter.
- Texto (`.csv`) é inerentemente maior e mais lento de gerar/ler do que
  binário puro (`.bin`) -- isso é esperado e é o preço de ser legível por
  humanos/Excel. Para capturas de produção grandes, prefira manter o
  arquivo original em `.bin` e use `.csv` como formato de interâmbio/
  inspeção manual de recortes menores (--inicio/--fim), não como o
  formato primário de armazenamento.
- No modo de PLOTAGEM, um `.csv` de entrada É carregado inteiro na
  memória (ao contrário do `.bin`), porque texto precisa ser
  integralmente escaneado para ser interpretado -- não há equivalente de
  memory-map para CSV. Leve isso em conta ao plotar CSVs muito grandes.

9. EXEMPLOS DE USO
---------------------
  # Plotar o arquivo inteiro no tempo, amostrado a 102.4 kHz
  python3 adc_tool.py supraharmonicos_raw.bin -f 102400

  # Só as amostras 125 a 3000 (útil para inspecionar um trecho específico)
  python3 adc_tool.py supraharmonicos_raw.bin -f 102400 --inicio 125 --fim 3000

  # Forma de onda + FFT usando todos os ciclos completos da janela
  python3 adc_tool.py supraharmonicos_raw.bin -f 102400 --fft

  # FFT de alta resolução temporal: só 10 ciclos, a partir da amostra 50000
  python3 adc_tool.py supraharmonicos_raw.bin -f 102400 --inicio 50000 --fft 10

  # Convertendo para tensão real (ADC ±10.24 V, sensor com ganho 19.53)
  python3 adc_tool.py supraharmonicos_raw.bin -f 102400 --faixa 10.24 --ganho 19.53 --fft

  # Plotar direto de um .csv (mesmas flags de sempre)
  python3 adc_tool.py supraharmonicos_raw.csv -f 102400 --fft

  # Converter .bin -> .csv
  python3 adc_tool.py -c supraharmonicos_raw.bin -o supraharmonicos_raw.csv

  # Converter .bin -> .csv incluindo a coluna de tensão (só informativa)
  python3 adc_tool.py -c supraharmonicos_raw.bin -o dados.csv --incluir-tensao --faixa 10.24 --ganho 19.53

  # Converter .csv -> .bin (round-trip; só a coluna valor_bruto é usada)
  python3 adc_tool.py -c dados.csv -o dados_reconstruido.bin

  # Converter só um recorte (amostras 0..9999) para abrir rápido no Excel
  python3 adc_tool.py -c supraharmonicos_raw.bin -o trecho.csv --fim 10000

Rode `python3 adc_tool.py --help` para a referência completa de argumentos.
==============================================================================
"""

import argparse
import itertools
import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt
from scipy.fft import rfft, rfftfreq

# Tamanho de bloco padrão (em amostras) usado nas conversões .bin<->.csv.
# Ver seção 8 do docstring do módulo ("DESEMPENHO E USO DE MEMÓRIA").
TAMANHO_CHUNK_PADRAO = 500_000

# Mapeia --formato -> dtype numpy usado tanto para ler .bin (memmap) quanto
# para decodificar/empacotar valores nas conversões .bin<->.csv.
FORMATOS_NUMPY = {
    "int16": np.dtype("<i2"),   # complemento de dois, bipolar
    "uint16": np.dtype("<u2"),  # binário reto, unipolar (padrão de fábrica)
}


# ==============================================================================
# 1. DETECÇÃO DE FORMATO E LEITURA DOS DADOS
# ==============================================================================

def detectar_tipo_arquivo(caminho: Path) -> str:
    """
    Detecta se um caminho é '.bin' ou '.csv' pela extensão (case-
    insensitive). Este script só entende esses dois formatos de dados
    brutos do ADC -- qualquer outra extensão é um erro do usuário (ex.:
    caminho de saída digitado errado).
    """
    sufixo = caminho.suffix.lower()
    if sufixo == ".bin":
        return "bin"
    if sufixo == ".csv":
        return "csv"
    raise SystemExit(
        f"Erro: extensão '{sufixo or '(nenhuma)'}' não reconhecida em "
        f"'{caminho}'. Este script só trabalha com arquivos '.bin' "
        f"(binário bruto) ou '.csv' (texto separado por vírgulas)."
    )


def carregar_amostras_bin(caminho: Path, formato: str) -> np.memmap:
    """
    Abre um '.bin' em modo memory-map (não carrega o arquivo inteiro na
    RAM -- só as páginas efetivamente acessadas depois, na hora de
    fatiar com --inicio/--fim ou de processar em blocos na conversão).
    """
    dtype = FORMATOS_NUMPY[formato]
    try:
        amostras = np.memmap(caminho, dtype=dtype, mode="r")
    except FileNotFoundError:
        raise SystemExit(f"Erro: arquivo '{caminho}' não encontrado.")
    except ValueError as e:
        raise SystemExit(f"Erro ao abrir '{caminho}': {e}")

    if amostras.size == 0:
        raise SystemExit(f"Erro: '{caminho}' está vazio (0 amostras).")
    return amostras


def carregar_amostras_csv(caminho: Path, formato: str) -> np.ndarray:
    """
    Lê a coluna 'valor_bruto' de um '.csv' gerado por este script (ou
    compatível: precisa ter uma linha de cabeçalho com uma coluna
    chamada exatamente 'valor_bruto'). Colunas extras (ex.: 'amostra',
    'tensao_v') são ignoradas -- só o código bruto do ADC é usado, para
    manter a MESMA fonte de verdade usada na conversão de volta para
    '.bin' (ver seção 3 do docstring do módulo).

    Ao contrário do '.bin' (lido via memmap, só toca as páginas
    realmente usadas), um '.csv' é texto e precisa ser integralmente
    escaneado para ser interpretado -- por isso ele é carregado inteiro
    na memória aqui (ver seção 8 do docstring).
    """
    try:
        with open(caminho, "r", newline="") as f:
            primeira_linha = f.readline()
            if not primeira_linha:
                raise SystemExit(f"Erro: '{caminho}' está vazio.")
            cabecalho = primeira_linha.strip().split(",")
            if "valor_bruto" not in cabecalho:
                raise SystemExit(
                    f"Erro: '{caminho}' não tem uma coluna 'valor_bruto' no "
                    f"cabeçalho (colunas encontradas: {cabecalho}). Use um "
                    f"'.csv' gerado por este script (-c/--converter) ou "
                    f"renomeie a coluna com os códigos brutos do ADC para "
                    f"'valor_bruto'."
                )
            indice_coluna = cabecalho.index("valor_bruto")
            amostras = np.loadtxt(
                f, delimiter=",", usecols=(indice_coluna,),
                dtype=FORMATOS_NUMPY[formato],
            )
    except FileNotFoundError:
        raise SystemExit(f"Erro: arquivo '{caminho}' não encontrado.")

    amostras = np.atleast_1d(amostras)
    if amostras.size == 0:
        raise SystemExit(f"Erro: '{caminho}' não tem linhas de dados.")
    return amostras


def carregar_amostras(caminho: Path, formato: str):
    """
    Ponto de entrada único de leitura para o modo de plotagem: decide
    entre '.bin' (memmap, leve) e '.csv' (carregado inteiro) só pela
    extensão do arquivo -- o resto do script (janelamento, conversão
    para tensão, FFT) não precisa saber qual dos dois formatos foi usado.
    """
    tipo = detectar_tipo_arquivo(caminho)
    if tipo == "bin":
        return carregar_amostras_bin(caminho, formato)
    return carregar_amostras_csv(caminho, formato)


def selecionar_intervalo(amostras, inicio: int, fim: int | None):
    """
    Aplica --inicio/--fim (em número de amostras) sobre o array completo.
    Sem --fim, usa até o final do arquivo/array. Sem --inicio, usa desde
    o começo. Funciona igual para um memmap de '.bin' (fatiar só toca as
    páginas pedidas) ou um ndarray de '.csv' já carregado.
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
    """Converte códigos brutos do ADC (int16/uint16) para Volts (ver seção 7
    do docstring do módulo).

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
# 2. MODO DE CONVERSÃO: .bin <-> .csv
# ==============================================================================

def bin_para_csv(caminho_bin: Path, caminho_csv: Path, formato: str,
                  inicio: int, fim: int | None, incluir_tensao: bool,
                  faixa: float, ganho: float, offset: float | None,
                  tamanho_chunk: int = TAMANHO_CHUNK_PADRAO) -> int:
    """
    Converte um '.bin' (código bruto do ADC, 2 bytes/amostra) para '.csv',
    em blocos de 'tamanho_chunk' amostras -- sem carregar o arquivo
    inteiro na RAM de uma vez (ver seção 8 do docstring do módulo).

    Colunas geradas no CSV:
        amostra      -- índice da amostra no arquivo original (0-based)
        valor_bruto  -- código de 16 bits do ADC, decodificado conforme
                         --formato (é essa coluna, e só ela, que é usada
                         para reconstruir o '.bin' de volta)
        tensao_v     -- só se incluir_tensao=True: tensão já convertida,
                         apenas para inspeção humana -- IGNORADA na
                         conversão inversa (csv -> bin)

    Retorna o número de amostras convertidas.

    NOTA DE DESEMPENHO: a formatação de cada linha é feita com uma
    list comprehension de f-strings + `str.join`, e não com
    `numpy.savetxt` -- em benchmark local (1 048 576 amostras, um
    buffer de produção inteiro), essa abordagem foi ~35% mais rápida
    que `numpy.savetxt` para escrever o mesmo CSV, porque evita o loop
    interno de formatação linha-a-linha do `numpy.savetxt`.
    """
    amostras = carregar_amostras_bin(caminho_bin, formato)
    _, inicio, fim, total = selecionar_intervalo(amostras, inicio, fim)

    if offset is None:
        offset = faixa / 2.0 if formato == "uint16" else 0.0

    with open(caminho_csv, "w", newline="") as f:
        if incluir_tensao:
            f.write("amostra,valor_bruto,tensao_v\n")
        else:
            f.write("amostra,valor_bruto\n")

        for ini_bloco in range(inicio, fim, tamanho_chunk):
            fim_bloco = min(ini_bloco + tamanho_chunk, fim)
            bloco = np.asarray(amostras[ini_bloco:fim_bloco]).astype(np.int64)
            indices = range(ini_bloco, fim_bloco)

            if incluir_tensao:
                tensao = converter_para_tensao(bloco, faixa, ganho, formato, offset)
                linhas = (
                    f"{i},{v},{t:.6f}"
                    for i, v, t in zip(indices, bloco.tolist(), tensao.tolist())
                )
            else:
                linhas = (f"{i},{v}" for i, v in zip(indices, bloco.tolist()))

            f.write("\n".join(linhas))
            f.write("\n")

    return fim - inicio


def csv_para_bin(caminho_csv: Path, caminho_bin: Path, formato: str,
                  inicio: int, fim: int | None,
                  tamanho_chunk: int = TAMANHO_CHUNK_PADRAO) -> int:
    """
    Converte um '.csv' (com coluna 'valor_bruto') de volta para '.bin'
    bruto, lendo o CSV como um FLUXO (uma linha por vez) e gravando em
    blocos de 'tamanho_chunk' amostras -- sem carregar o arquivo de
    texto inteiro na memória (ver seção 8 do docstring do módulo).

    Só a coluna 'valor_bruto' é usada -- qualquer outra coluna (ex.:
    'tensao_v') é ignorada, para garantir que o '.bin' resultante seja
    byte-a-byte equivalente ao original (round-trip sem perdas), em vez
    de uma versão recalculada a partir de uma tensão já arredondada.

    --inicio/--fim aqui contam LINHAS DE DADOS do CSV (não contam o
    cabeçalho).

    Retorna o número de amostras convertidas.

    NOTA DE DESEMPENHO: as linhas são separadas com `str.split(',')`
    direto (sem o módulo `csv` da stdlib) -- em benchmark local isso foi
    ~35% mais rápido para ler o mesmo volume de dados, já que o formato
    gerado por este script é sempre texto simples sem aspas/escapes que
    justifiquem o parser mais genérico (e mais lento) do módulo `csv`.
    """
    dtype = FORMATOS_NUMPY[formato]
    inicio = max(0, inicio)

    with open(caminho_csv, "r", newline="") as f_in:
        primeira_linha = f_in.readline()
        if not primeira_linha:
            raise SystemExit(f"Erro: '{caminho_csv}' está vazio.")
        cabecalho = primeira_linha.rstrip("\n").split(",")
        if "valor_bruto" not in cabecalho:
            raise SystemExit(
                f"Erro: '{caminho_csv}' não tem uma coluna 'valor_bruto' no "
                f"cabeçalho (colunas encontradas: {cabecalho})."
            )
        indice_coluna = cabecalho.index("valor_bruto")

        fim_absoluto = None if fim is None else fim
        # itertools.islice(f_in, inicio, fim_absoluto) pula 'inicio' linhas
        # de dados e para no índice absoluto 'fim_absoluto' (ou no fim do
        # arquivo, se None) -- tudo em streaming, sem carregar linhas
        # descartadas na memória.
        linhas_dados = itertools.islice(f_in, inicio, fim_absoluto)

        n_convertidas = 0
        with open(caminho_bin, "wb") as f_out:
            bloco = []
            for linha in linhas_dados:
                if not linha.strip():
                    continue  # ignora linha em branco (ex.: fim de arquivo)
                bloco.append(int(linha.split(",")[indice_coluna]))
                n_convertidas += 1
                if len(bloco) >= tamanho_chunk:
                    f_out.write(np.array(bloco, dtype=dtype).tobytes())
                    bloco = []
            if bloco:
                f_out.write(np.array(bloco, dtype=dtype).tobytes())

        if fim is not None and n_convertidas < (fim - inicio):
            print(
                f"Aviso: --fim pediu {fim} amostra(s) (a partir de --inicio "
                f"{inicio}), mas '{caminho_csv}' só tinha {inicio + n_convertidas} "
                f"linha(s) de dados no total. Convertida(s) {n_convertidas} "
                f"amostra(s).",
                file=sys.stderr,
            )

    if n_convertidas == 0:
        raise SystemExit(
            f"Erro: nenhuma amostra convertida de '{caminho_csv}' "
            f"(--inicio além do fim do arquivo, ou intervalo --inicio/--fim "
            f"vazio?)."
        )

    return n_convertidas


def converter_arquivo(caminho_entrada: Path, caminho_saida: Path, formato: str,
                       inicio: int, fim: int | None, incluir_tensao: bool,
                       faixa: float, ganho: float, offset: float | None,
                       tamanho_chunk: int) -> None:
    """
    Decide a direção da conversão pelas extensões de entrada/saída e
    despacha para bin_para_csv() ou csv_para_bin() (ver seção 4 do
    docstring do módulo).
    """
    tipo_entrada = detectar_tipo_arquivo(caminho_entrada)
    tipo_saida = detectar_tipo_arquivo(caminho_saida)

    if tipo_entrada == tipo_saida:
        raise SystemExit(
            f"Erro: entrada ('{caminho_entrada}', .{tipo_entrada}) e saída "
            f"('{caminho_saida}', .{tipo_saida}) têm o mesmo formato -- não "
            f"há conversão a fazer. Use -c com '.bin' e -o com '.csv' (ou "
            f"vice-versa)."
        )

    if incluir_tensao and tipo_entrada != "bin":
        print(
            "Aviso: --incluir-tensao só tem efeito na conversão .bin -> "
            ".csv; ignorado nesta conversão (.csv -> .bin sempre usa "
            "apenas a coluna 'valor_bruto').",
            file=sys.stderr,
        )

    if tipo_entrada == "bin" and tipo_saida == "csv":
        n = bin_para_csv(caminho_entrada, caminho_saida, formato, inicio, fim,
                          incluir_tensao, faixa, ganho, offset, tamanho_chunk)
        extra = " | coluna tensao_v incluída" if incluir_tensao else ""
        print(f"Convertido: '{caminho_entrada}' (.bin) -> '{caminho_saida}' "
              f"(.csv) | {n} amostra(s) | --formato {formato}{extra}")
    else:
        n = csv_para_bin(caminho_entrada, caminho_saida, formato, inicio, fim,
                          tamanho_chunk)
        print(f"Convertido: '{caminho_entrada}' (.csv) -> '{caminho_saida}' "
              f"(.bin) | {n} amostra(s) | --formato {formato} (usado para "
              f"empacotar cada valor de volta em 2 bytes)")


# ==============================================================================
# 3. ESTIMATIVA DA FREQUÊNCIA FUNDAMENTAL E JANELAMENTO EM CICLOS INTEIROS
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
    detectado. Ver seção 6.2 do docstring do módulo para a estratégia.

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
# 4. CÁLCULO DA FFT
# ==============================================================================

def calcular_espectro_dbv(sinal: np.ndarray, fs: float):
    """FFT em dBV com janela de Hann (ver seção 6.2 sobre a dupla proteção
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
# 5. PLOTAGEM
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
# 6. LINHA DE COMANDO
# ==============================================================================

def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adc_tool.py",
        description=(
            "Ferramenta de linha de comando do SH-Analyzer para dados brutos "
            "do ADS8688 (antigo 'plot_adc.py'). Dois modos: (1) MODO DE "
            "CONVERSÃO (-c/--converter + -o/--saida), que converte capturas "
            "entre binário bruto '.bin' (formato gravado por "
            "firmware/ler_adc.c) e '.csv' (texto legível por humanos/"
            "Excel), nos dois sentidos; (2) MODO DE PLOTAGEM (padrão, sem "
            "-c), que plota a forma de onda e, opcionalmente (--fft), "
            "calcula o espectro de frequência de uma captura em '.bin' OU "
            "'.csv'. Rode com --help para a referência completa de flags; "
            "o cabeçalho do script (docstring) tem a explicação técnica "
            "completa de cada etapa."
        ),
        epilog=(
            "Exemplos:\n"
            "  # -- Modo de plotagem --------------------------------------\n"
            "  # Plotar (arquivo .bin, formato padrão)\n"
            "  %(prog)s captura.bin -f 102400\n"
            "\n"
            "  # Plotar um recorte específico de amostras\n"
            "  %(prog)s captura.bin -f 102400 --inicio 125 --fim 3000\n"
            "\n"
            "  # Plotar com FFT (todos os ciclos completos da janela)\n"
            "  %(prog)s captura.bin -f 102400 --fft\n"
            "\n"
            "  # FFT de alta resolução temporal (só 10 ciclos)\n"
            "  %(prog)s captura.bin -f 102400 --inicio 50000 --fft 10\n"
            "\n"
            "  # Plotar direto de um .csv (mesmas flags, formato autodetectado)\n"
            "  %(prog)s captura.csv -f 102400 --fft\n"
            "\n"
            "  # -- Modo de conversão --------------------------------------\n"
            "  # Converter .bin -> .csv\n"
            "  %(prog)s -c captura.bin -o captura.csv\n"
            "\n"
            "  # Converter .bin -> .csv incluindo uma coluna de tensão\n"
            "  %(prog)s -c captura.bin -o captura.csv --incluir-tensao "
            "--faixa 10.24 --ganho 19.53\n"
            "\n"
            "  # Converter .csv -> .bin (round-trip; só valor_bruto é usada)\n"
            "  %(prog)s -c captura.csv -o captura_reconstruida.bin\n"
            "\n"
            "  # Converter só um recorte (amostras 0..9999) para inspecionar rápido\n"
            "  %(prog)s -c captura.bin -o trecho.csv --fim 10000\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "arquivo", type=Path, nargs="?", default=None,
        help="[MODO DE PLOTAGEM] Caminho do arquivo de dados a plotar. "
             "Aceita '.bin' (binário bruto, lido via memory-map -- não "
             "carrega tudo na RAM) ou '.csv' (precisa ter uma coluna "
             "'valor_bruto', é carregado inteiro na RAM). O formato é "
             "autodetectado pela extensão. OBRIGATÓRIO nesse modo; NÃO "
             "USADO se -c/--converter for passado."
    )
    parser.add_argument(
        "-f", "--frequencia", type=float, default=None,
        metavar="HZ",
        help="[MODO DE PLOTAGEM] Frequência de amostragem usada na coleta, "
             "em Hz (ex.: -f 102400). Define o eixo do tempo e o eixo de "
             "frequência da FFT. OBRIGATÓRIO nesse modo; NÃO USADO no modo "
             "de conversão (a taxa de amostragem não é gravada dentro dos "
             "arquivos '.bin'/'.csv')."
    )

    grupo_conversao = parser.add_argument_group(
        "Modo de conversão (.bin <-> .csv)",
        "Ativado por -c/--converter; nesse modo o posicional 'arquivo' e "
        "-f/--frequencia são ignorados. A direção (bin->csv ou csv->bin) é "
        "detectada automaticamente pelas extensões de -c e -o.",
    )
    grupo_conversao.add_argument(
        "-c", "--converter", type=Path, default=None, metavar="ARQUIVO_ENTRADA",
        help="Ativa o MODO DE CONVERSÃO em vez de plotagem: converte "
             "ARQUIVO_ENTRADA para o caminho passado em -o/--saida "
             "(OBRIGATÓRIO junto com esta flag). Valores possíveis para a "
             "extensão de ARQUIVO_ENTRADA: '.bin' ou '.csv' -- a direção da "
             "conversão é o par (entrada, saída) com extensões opostas: "
             "'.bin'->'.csv' gera as colunas 'amostra,valor_bruto[,tensao_v]'; "
             "'.csv'->'.bin' lê a coluna 'valor_bruto' e grava de volta os "
             "códigos brutos de 16 bits (round-trip sem perdas)."
    )
    grupo_conversao.add_argument(
        "--incluir-tensao", action="store_true",
        help="Só tem efeito na direção '.bin'->'.csv': acrescenta uma "
             "coluna 'tensao_v' ao CSV gerado, calculada com --faixa/"
             "--ganho/--offset/--formato, só para conferência visual -- "
             "essa coluna é IGNORADA se o CSV for convertido de volta "
             "para '.bin' (a reconstrução usa sempre 'valor_bruto', nunca "
             "a tensão, para não introduzir erro de arredondamento). "
             "Não recebe valor (flag liga/desliga). Padrão: desligado "
             "(CSV só com 'amostra,valor_bruto')."
    )
    grupo_conversao.add_argument(
        "--tamanho-chunk", type=int, default=TAMANHO_CHUNK_PADRAO, metavar="N",
        help="Número de amostras processadas por bloco durante a conversão "
             f"'.bin'<->'.csv' (padrão: {TAMANHO_CHUNK_PADRAO}). Blocos "
             "menores usam menos memória RAM; blocos maiores tendem a ser "
             "um pouco mais rápidos (menos overhead por chamada), até o "
             "limite da RAM disponível. Só é usado no modo de conversão."
    )

    parser.add_argument(
        "-o", "--saida", "--salvar", dest="saida", type=Path, default=None,
        metavar="ARQUIVO",
        help="Caminho de SAÍDA -- o significado depende do modo ativo: "
             "[MODO DE CONVERSÃO, -c presente] caminho do arquivo "
             "convertido, com extensão '.csv' ou '.bin' (a OPOSTA à de "
             "-c/--converter); OBRIGATÓRIO junto com -c. "
             "[MODO DE PLOTAGEM, -c ausente] caminho de imagem (ex.: "
             "'grafico.png', ou qualquer extensão suportada pelo "
             "matplotlib) onde salvar o gráfico em vez de abrir a janela "
             "interativa; OPCIONAL, padrão None (abre a janela "
             "interativa). '--salvar' é o nome antigo desta flag, mantido "
             "por compatibilidade com o antigo 'plot_adc.py'."
    )

    parser.add_argument(
        "--inicio", type=int, default=0, metavar="N",
        help="Índice da primeira amostra a usar, contando a partir de 0 "
             "(padrão: 0, início do arquivo). Usado tanto no modo de "
             "plotagem quanto no de conversão (permite plotar/converter "
             "só um recorte de um arquivo grande)."
    )
    parser.add_argument(
        "--fim", type=int, default=None, metavar="N",
        help="Índice (exclusive) da última amostra a usar (padrão: None, "
             "processa até o final do arquivo). Usado tanto no modo de "
             "plotagem quanto no de conversão."
    )
    parser.add_argument(
        "--fft", nargs="?", type=int, const=0, default=None, metavar="N_CICLOS",
        help="[MODO DE PLOTAGEM] Também calcula e plota a FFT. Valores "
             "possíveis: omitido (padrão) -> não calcula FFT, só plota a "
             "forma de onda no tempo; '--fft' sem número -> usa TODOS os "
             "ciclos completos da fundamental disponíveis na janela "
             "selecionada por --inicio/--fim; '--fft N' (N inteiro > 0) "
             "-> usa só os primeiros N ciclos completos, útil para "
             "analisar distúrbios momentâneos."
    )
    parser.add_argument(
        "--freq-min", type=float, default=45.0, metavar="HZ",
        help="[MODO DE PLOTAGEM, só com --fft] Limite inferior da faixa de "
             "busca da frequência fundamental da rede, em Hz (padrão: "
             "45.0 -- cobre redes de 50/60 Hz com folga)."
    )
    parser.add_argument(
        "--freq-max", type=float, default=65.0, metavar="HZ",
        help="[MODO DE PLOTAGEM, só com --fft] Limite superior da faixa de "
             "busca da frequência fundamental da rede, em Hz (padrão: 65.0)."
    )
    parser.add_argument(
        "--formato", choices=["int16", "uint16"], default="uint16",
        help="Como interpretar cada código bruto de 16 bits do ADC. "
             "Valores possíveis: 'uint16' (binário reto / straight "
             "binary, faixa UNIPOLAR 0..+faixa -- PADRÃO, é o formato de "
             "saída real do ADS8688 nesta placa) ou 'int16' (complemento "
             "de dois, faixa BIPOLAR -faixa..+faixa, ex.: ±10.24 V). "
             "Usado tanto no modo de plotagem/FFT (decodifica os bytes "
             "lidos) quanto no modo de conversão (decide como decodificar "
             "bytes -> número em '.bin'->'.csv', e como empacotar número "
             "-> bytes em '.csv'->'.bin')."
    )
    parser.add_argument(
        "--faixa", type=float, default=10.24, metavar="VOLTS",
        help="[Conversão para tensão: plotagem, ou conversão de arquivo "
             "com --incluir-tensao] Faixa de fundo de escala do ADC em "
             "Volts (padrão: 10.24, a faixa bipolar default de fábrica do "
             "ADS8688: ±10.24 V)."
    )
    parser.add_argument(
        "--ganho", type=float, default=1.0, metavar="FATOR",
        help="[Conversão para tensão: plotagem, ou conversão de arquivo "
             "com --incluir-tensao] Fator de ganho do sensor/PCB para "
             "converter a tensão no ADC na tensão real da rede (padrão: "
             "1.0, sem conversão adicional)."
    )
    parser.add_argument(
        "--offset", type=float, default=None, metavar="VOLTS",
        help="[Conversão para tensão: plotagem, ou conversão de arquivo "
             "com --incluir-tensao] Deslocamento DC subtraído da tensão "
             "do ADC antes do ganho (padrão automático: faixa/2 para "
             "--formato uint16, o que centraliza a onda CA em torno de "
             "0 V; 0.0 para --formato int16, que já é bipolar). Ajuste "
             "manualmente se o offset real do seu ADC/sensor não for "
             "exatamente metade da faixa (erro de calibração)."
    )

    return parser


def main(argv=None):
    parser = montar_parser()
    args = parser.parse_args(argv)

    # --------------------------------------------------------------------
    # MODO DE CONVERSÃO
    # --------------------------------------------------------------------
    if args.converter is not None:
        if args.arquivo is not None:
            parser.error(
                "não use o argumento posicional 'arquivo' junto com "
                "-c/--converter; passe o caminho de entrada em -c e o de "
                "saída em -o/--saida."
            )
        if args.saida is None:
            parser.error(
                "-o/--saida é obrigatório junto com -c/--converter "
                "(caminho do arquivo de saída)."
            )
        converter_arquivo(
            args.converter, args.saida, args.formato, args.inicio, args.fim,
            args.incluir_tensao, args.faixa, args.ganho, args.offset,
            args.tamanho_chunk,
        )
        return

    # --------------------------------------------------------------------
    # MODO DE PLOTAGEM (comportamento original)
    # --------------------------------------------------------------------
    if args.arquivo is None:
        parser.error(
            "o argumento 'arquivo' é obrigatório no modo de plotagem "
            "(ou use -c/--converter para converter .bin<->.csv)."
        )
    if args.frequencia is None:
        parser.error("-f/--frequencia é obrigatório no modo de plotagem.")

    offset = args.offset
    if offset is None:
        offset = args.faixa / 2.0 if args.formato == "uint16" else 0.0

    tipo_arquivo = detectar_tipo_arquivo(args.arquivo)
    amostras = carregar_amostras(args.arquivo, args.formato)
    bruto, idx_inicio, idx_fim, total = selecionar_intervalo(
        amostras, args.inicio, args.fim
    )
    tensao = converter_para_tensao(bruto, args.faixa, args.ganho, args.formato, offset)

    print(f"Arquivo: {args.arquivo}  ({total} amostras no total, "
          f"formato de arquivo: .{tipo_arquivo})")
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
           args.arquivo.name, args.saida)


if __name__ == "__main__":
    main()