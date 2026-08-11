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
     6.4 Escolha da janela espectral (--janela / --kaiser-beta)
  7. CONVERSÃO PARA TENSÃO (--faixa / --offset / --ganho / --formato)
  8. DESEMPENHO E USO DE MEMÓRIA
  9. EXEMPLOS DE USO (ver também `--help`)
  10. CAPTURA E ANÁLISE MULTI-CANAL (--canais / --canais-exibir / --layout-canais)
      10.1 Convenção de intercalação (round-robin)
      10.2 Selecionando e organizando a exibição dos canais
      10.3 Frequência efetiva por canal
      10.4 FFT em modo multi-canal
      10.5 Calibração por canal (--faixa / --ganho / --offset como listas)
      10.6 Modo de conversão: a coluna `canal` no `.csv`
      10.7 Casos de borda

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
         residual disso é uma fração de amostra, desprezível). Por cima
         desse recorte, a janela escolhida em --janela é aplicada (ver
         seção 6.4) -- por padrão NENHUMA (retangular), já que o recorte
         em ciclos inteiros já ataca a causa raiz do vazamento; outras
         janelas ficam disponíveis como camada extra de proteção contra
         qualquer imperfeição residual (a rede real nunca é perfeitamente
         periódica), ao custo de resolução em frequência e/ou exatidão de
         amplitude.

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

6.4 Escolha da janela espectral (--janela / --kaiser-beta)
    A janela aplicada ao trecho ANTES da FFT PRINCIPAL (a que gera o
    espectro exibido/salvo) é configurável via --janela. Isso é
    independente do recorte em ciclos inteiros da seção 6.2: o recorte
    ataca a causa raiz do vazamento (descontinuidade na "emenda"); a
    janela, quando usada, é uma camada adicional que reduz ainda mais os
    lóbulos laterais à custa de alargar o lóbulo principal (menos
    resolução em frequência) e/ou atenuar a amplitude reportada -- por
    isso a correção pelo ganho coerente (seção 4, calcular_espectro_dbv)
    é sempre aplicada, para QUALQUER janela escolhida.

    Nem a estimativa grosseira da fundamental (função
    estimar_frequencia_fundamental) nem o recorte em ciclos inteiros são
    afetados por --janela -- ambos usam Hann internamente, de forma fixa,
    só como ferramenta de triagem. --janela afeta somente o espectro
    final mostrado ao usuário.

    Opções aceitas (--janela ACEITA sinônimos; acentos, hifens, espaços e
    maiúsculas/minúsculas são todos ignorados na comparação):

        retangular / boxcar   (PADRÃO -- equivale a não aplicar janela
                                nenhuma, ou seja, multiplicar por 1.0)
            Lóbulo principal mais estreito possível -> melhor resolução
            em frequência e nenhuma atenuação de amplitude. Em troca,
            tem os lóbulos laterais mais altos (~-13 dB) de todas as
            opções -- só é uma boa escolha quando o recorte em ciclos
            inteiros (seção 6.2) já está fazendo o trabalho pesado contra
            vazamento, o que é o caso normal deste script.

        hann / hanning
            Compromisso clássico entre resolução e vazamento (lóbulos
            laterais a partir de ~-31 dB). Era o comportamento padrão
            (fixo) de versões anteriores deste script.

        blackmanharris / blackman-harris
            Lóbulos laterais muito baixos (~-92 dB) -- ajuda a enxergar
            um supraharmônico de amplitude baixa perto de uma fundamental
            de amplitude alta, ao custo de um lóbulo principal bem mais
            largo (pior resolução para separar duas componentes
            próximas em frequência).

        flattop / flat-top
            Topo do lóbulo principal muito achatado -- a melhor EXATIDÃO
            DE AMPLITUDE de todas as opções (minimiza o erro de "scalloping
            loss" quando um tom não cai exatamente num bin da FFT), mas a
            PIOR resolução em frequência e o lóbulo principal mais largo
            de todos. Use quando o objetivo é medir com precisão o valor
            de pico de uma componente já conhecida (ex.: a fundamental),
            não separar componentes vizinhas.

        kaiser (+ --kaiser-beta)
            Família ajustável por um único parâmetro (beta): permite
            variar continuamente entre o comportamento "quase retangular"
            (beta baixo) e "lóbulos laterais muitíssimo baixos, lóbulo
            principal muito largo" (beta alto). Ver --help de
            --kaiser-beta para valores de referência aproximados
            (equivalência com Hamming/Hann/Blackman).

    Exemplos:
        --janela retangular              (padrão, pode ser omitido)
        --janela hann
        --janela blackmanharris
        --janela blackman-harris         (equivalente ao anterior)
        --janela "flat top"
        --janela kaiser --kaiser-beta 12

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

  # FFT com janela Blackman-Harris (lóbulos laterais bem mais baixos que
  # o padrão retangular -- útil para caçar um supraharmônico fraco perto
  # da fundamental)
  python3 adc_tool.py supraharmonicos_raw.bin -f 102400 --fft --janela blackman-harris

  # FFT com janela Kaiser e beta customizado
  python3 adc_tool.py supraharmonicos_raw.bin -f 102400 --fft --janela kaiser --kaiser-beta 12

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

  # -- Multi-canal (ver seção 10) ---------------------------------------
  # Captura feita com `ler_adc 102400 0,1,3` -- 3 canais intercalados.
  # Plotar todos, um subplot por canal (padrão --layout-canais separados)
  python3 adc_tool.py captura.bin -f 102400 --canais 0,1,3 --fft

  # Mesma captura, mas só os canais 0 e 3, sobrepostos no mesmo eixo
  python3 adc_tool.py captura.bin -f 102400 --canais 0,1,3 \
      --canais-exibir 0,3 --layout-canais sobrepostos --fft

  # Canal 0 = tensão (ganho 19.53), canal 1 = corrente (ganho 0.1) --
  # --faixa/--ganho/--offset aceitam 1 valor (todos os canais) ou uma
  # lista com 1 valor por canal, na MESMA ordem de --canais
  python3 adc_tool.py captura.bin -f 102400 --canais 0,1 \
      --ganho 19.53,0.1 --faixa 10.24,10.24 --fft

Rode `python3 adc_tool.py --help` para a referência completa de argumentos.
==============================================================================

10. CAPTURA E ANÁLISE MULTI-CANAL
--------------------------------------
`firmware/ler_adc.c` pode capturar vários canais do ADS8688 numa mesma
captura, intercalados (round-robin) num único arquivo `.bin` -- sem
buffers separados por canal e sem cabeçalho nenhum no arquivo. Esta seção
explica como este script decodifica e apresenta esse formato.

10.1 Convenção de intercalação (round-robin)
    Com N canais selecionados na captura (`ler_adc <freq> <canais>`), a
    amostra bruta na posição `i` do arquivo (0-based, considerando o
    arquivo inteiro) pertence ao canal `lista_de_canais[i % N]`, sendo
    `lista_de_canais` a MESMA lista, na MESMA ordem, passada ao `ler_adc`
    na hora da captura. O firmware já cuida internamente de um atraso de
    pipeline de 1 quadro do ADS8688 (descartando a amostra de
    alinhamento necessária -- ver comentários em `firmware/ler_adc.c` e
    `firmware/spi_core.asm`), então essa correspondência simples de
    posição -> canal já vale a partir da amostra 0 do arquivo, sem
    nenhum ajuste adicional necessário aqui.

    Como o `.bin` não carrega metadado nenhum (mesma filosofia que já
    valia para a frequência de amostragem, sempre externa ao arquivo),
    é preciso informar essa lista de novo aqui, via --canais -- `ler_adc`
    já imprime a lista usada no console durante a captura, para anotação.

10.2 Selecionando e organizando a exibição dos canais
    --canais LISTA        -- canais presentes no arquivo, na ordem da
                              captura (ex.: "0,1,3"). Padrão: "1" (um
                              canal só -- comportamento idêntico ao deste
                              script antes do suporte multi-canal).
    --canais-exibir LISTA  -- subconjunto de --canais a plotar/analisar
                              de fato (padrão: todos os de --canais).
    --layout-canais {separados,sobrepostos} -- só importa com mais de 1
                              canal em --canais-exibir. 'separados'
                              (padrão): um subplot por canal -- mais
                              seguro visualmente quando os canais medem
                              grandezas diferentes (ex.: tensão e
                              corrente, escalas bem distintas).
                              'sobrepostos': todos os canais no MESMO
                              eixo de tempo (e no mesmo eixo de
                              frequência, se --fft), cada um com uma cor
                              e uma entrada na legenda.

10.3 Frequência efetiva por canal
    -f/--frequencia continua sendo a frequência TOTAL de transação SPI
    (mesmo significado de sempre, e o mesmo valor que se passaria a
    `ler_adc`). Com N canais, cada canal individualmente foi amostrado a
    `--frequencia / N` -- é essa frequência efetiva, não a total, que
    este script usa para montar o eixo do tempo e a base da FFT de cada
    canal (já que amostras consecutivas do MESMO canal, no arquivo
    intercalado, estão separadas por N posições, não por 1).

10.4 FFT em modo multi-canal
    Com --fft, cada canal selecionado passa pelo MESMO pipeline de
    sempre (estimativa grosseira da fundamental -> recorte em ciclos
    inteiros por cruzamento de zero -> espectro com a janela de
    --janela) de forma INDEPENDENTE dos outros -- não se assume que
    todos os canais tenham exatamente a mesma fundamental/fase estimada,
    mesmo vindo da mesma rede elétrica (ruído, sensor e ganho diferentes
    por canal podem afetar ligeiramente a detecção de cada um).
    --freq-min/--freq-max/--janela/--kaiser-beta/--fft N continuam sendo
    parâmetros GLOBAIS, aplicados igualmente a todos os canais
    processados.

10.5 Calibração por canal (--faixa / --ganho / --offset como listas)
    Numa captura real deste projeto é comum um canal medir tensão e
    outro corrente, cada um com sensor/ganho diferentes. Por isso,
    --faixa/--ganho/--offset aceitam DOIS formatos:
        - um valor único, aplicado a TODOS os canais (comportamento de
          sempre, retrocompatível);
        - uma lista separada por vírgula do MESMO tamanho de --canais,
          um valor por canal, na mesma ordem (ex.: --canais 0,1
          --ganho 19.53,0.1 -> canal 0 usa ganho 19.53, canal 1 usa
          ganho 0.1).
    --offset, quando omitido, continua com o padrão automático
    (faixa/2 para --formato uint16, 0.0 para int16) calculado
    individualmente para cada canal a partir da sua própria --faixa.

10.6 Modo de conversão: a coluna `canal` no `.csv`
    Na conversão '.bin'->'.csv', se --canais tiver mais de 1 canal, o
    CSV gerado ganha uma coluna `canal` a mais (formato:
    `amostra,canal,valor_bruto[,tensao_v]`), com o canal de cada linha
    já resolvido. Com --canais tendo só 1 canal (ou omitido, padrão),
    o CSV continua EXATAMENTE igual a hoje (`amostra,valor_bruto
    [,tensao_v]`, sem coluna `canal`), para não alterar o formato de
    nenhum fluxo de trabalho de 1 canal já existente.

    Um CSV COM coluna `canal` é autodescritivo: '.csv'->'.bin' não
    precisa mais de --canais para reconstruir a intercalação original
    -- a ordem das linhas no CSV já preserva isso (a conversão só
    escreve `valor_bruto` de cada linha, na ordem em que aparecem,
    exatamente como sempre fez).

10.7 Casos de borda
    --inicio/--fim continuam contando posições BRUTAS no arquivo (sem
    mudar de significado). Se o recorte resultante não for múltiplo do
    número de canais, o script trunca por baixo antes de desintercalar,
    para que todos os canais fiquem com o MESMO número de amostras
    (evita desalinhar o eixo de tempo entre canais no layout
    'sobrepostos'). `SAMPLES_PER_BUFFER` do firmware (1.048.576) também
    não é necessariamente múltiplo do número de canais -- isso é
    esperado e não afeta a intercalação, que se mantém em fase ao longo
    de toda a captura (ver 10.1).
==============================================================================
"""

import argparse
import itertools
import sys
import unicodedata
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt, get_window
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

# Mapeia alias normalizado (sem acento/hífen/espaço, minúsculo -- ver
# _normalizar_nome_janela) -> nome canônico aceito por scipy.signal.get_window.
# Ver seção 6.4 do docstring do módulo para a explicação de cada opção.
JANELA_PADRAO = "retangular"
ALIASES_JANELA = {
    "retangular": "boxcar",
    "retangulo": "boxcar",
    "boxcar": "boxcar",
    "hann": "hann",
    "hanning": "hann",
    "blackmanharris": "blackmanharris",
    "flattop": "flattop",
    "kaiser": "kaiser",
}
# Nome canônico do scipy -> rótulo legível usado em prints/títulos de gráfico.
NOMES_EXIBICAO_JANELA = {
    "boxcar": "Retangular (sem janela)",
    "hann": "Hann",
    "blackmanharris": "Blackman-Harris",
    "flattop": "Flat Top",
    "kaiser": "Kaiser",
}

# Número máximo de canais do ADS8688 (canais 0-7) -- mesmo valor usado em
# firmware/memoria_pru.h (ADS8688_MAX_CANAIS), mantido em sincronia
# manualmente (não há um único arquivo de constantes compartilhado entre
# o firmware em C/Assembly e este script em Python). Ver seção 10 do
# docstring do módulo para o suporte multi-canal.
ADS8688_MAX_CANAIS = 8

# Canal usado quando --canais não é passado -- mesmo padrão histórico de
# `ler_adc` (um canal só, o canal 1) mantido aqui para consistência.
CANAL_PADRAO = "1"


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
# 1B. SUPORTE MULTI-CANAL (ver seção 10 do docstring do módulo)
# ==============================================================================

def analisar_lista_canais(texto: str, nome_flag: str = "--canais") -> list[int]:
    """
    Interpreta uma lista de canais (--canais ou --canais-exibir), ex.
    "0,1,3", separada por vírgula, sem espaços. Mesmas regras de
    validação usadas em firmware/ler_adc.c (analisar_lista_canais lá),
    mantidas em sincronia de propósito: canal entre 0 e 7 (o ADS8688 só
    tem 8 entradas), sem repetição, sem lista vazia. A ORDEM é
    preservada -- é ela que define a convenção de intercalação (seção
    10.1 do docstring).
    """
    partes = [p.strip() for p in texto.split(",")]
    canais: list[int] = []
    for p in partes:
        if p == "":
            continue
        try:
            valor = int(p)
        except ValueError:
            raise SystemExit(
                f"Erro: '{p}' não é um número de canal válido em "
                f"{nome_flag}='{texto}'."
            )
        if valor < 0 or valor > 7:
            raise SystemExit(
                f"Erro: canal {valor} inválido em {nome_flag} -- o ADS8688 "
                f"só tem canais 0-7."
            )
        if valor in canais:
            raise SystemExit(
                f"Erro: canal {valor} repetido em {nome_flag}='{texto}'."
            )
        if len(canais) >= ADS8688_MAX_CANAIS:
            raise SystemExit(
                f"Erro: mais de {ADS8688_MAX_CANAIS} canais em "
                f"{nome_flag}='{texto}' -- o ADS8688 só tem "
                f"{ADS8688_MAX_CANAIS} entradas."
            )
        canais.append(valor)

    if not canais:
        raise SystemExit(f"Erro: lista de canais vazia em {nome_flag}.")
    return canais


def validar_subconjunto_canais(canais_exibir: list[int], canais: list[int]) -> None:
    """
    Garante que todo canal pedido em --canais-exibir também está em
    --canais (não faz sentido pedir para exibir um canal que não foi
    informado como presente no arquivo).
    """
    faltando = [c for c in canais_exibir if c not in canais]
    if faltando:
        raise SystemExit(
            f"Erro: --canais-exibir pede o(s) canal(is) {faltando}, que "
            f"não está(ão) em --canais ({canais}). --canais-exibir precisa "
            f"ser um subconjunto de --canais."
        )


def analisar_lista_calibracao(texto: str, num_canais: int, nome_flag: str) -> list[float]:
    """
    Interpreta um parâmetro de calibração (--faixa/--ganho/--offset) que
    pode vir como UM valor único (aplicado a todos os canais -- forma
    retrocompatível, usada por qualquer captura de 1 canal só) ou como
    uma lista separada por vírgula do MESMO tamanho de --canais, um
    valor por canal, na mesma ordem (ver seção 10.5 do docstring).
    """
    partes = [p.strip() for p in texto.split(",")]
    try:
        valores = [float(p) for p in partes]
    except ValueError:
        raise SystemExit(
            f"Erro: valor inválido em {nome_flag}='{texto}' (use um número, "
            f"ou vários separados por vírgula)."
        )
    if len(valores) == 1:
        return valores * num_canais
    if len(valores) != num_canais:
        raise SystemExit(
            f"Erro: {nome_flag} tem {len(valores)} valor(es), mas --canais "
            f"tem {num_canais} canal(is). Passe 1 valor (aplicado a todos "
            f"os canais) ou exatamente {num_canais} valores separados por "
            f"vírgula, na mesma ordem de --canais."
        )
    return valores


def desintercalar(amostras_brutas, canais: list[int],
                   canais_selecionados: list[int] | None = None) -> dict[int, np.ndarray]:
    """
    Desintercala um array de amostras brutas (visto como um ciclo
    round-robin de len(canais) canais -- ver seção 10.1 do docstring) e
    devolve um dict {canal: array_de_amostras_daquele_canal}, só para os
    canais pedidos em 'canais_selecionados' (padrão: todos os de
    'canais').

    Implementação: trunca para um múltiplo de len(canais) (ver seção
    10.7 -- descarta um resto de até len(canais)-1 amostras no final, se
    houver) e usa reshape(-1, num_canais) + seleção de coluna, em vez de
    um loop Python amostra a amostra -- isso mantém tudo como VIEWS do
    array original (sem cópia), inclusive quando 'amostras_brutas' vem
    de um memmap de '.bin' (ver seção 8 do docstring sobre desempenho/
    memória). Com 1 canal só (fluxo de hoje), isso se reduz a um reshape
    trivial que devolve o mesmo conteúdo do array original.
    """
    if canais_selecionados is None:
        canais_selecionados = canais

    num_canais = len(canais)
    n = len(amostras_brutas)
    n_ciclos = n // num_canais
    n_truncado = n_ciclos * num_canais

    if n_truncado == 0:
        raise SystemExit(
            f"Erro: só {n} amostra(s) bruta(s) disponível(is), insuficiente "
            f"para completar 1 ciclo de {num_canais} canais. Aumente a "
            f"janela selecionada (--inicio/--fim) ou verifique se --canais "
            f"bate com a captura de verdade."
        )
    if n_truncado < n:
        print(
            f"Aviso: {n - n_truncado} amostra(s) bruta(s) no final do "
            f"recorte não completam um ciclo inteiro de {num_canais} "
            f"canais e foram descartadas para manter todos os canais com "
            f"o mesmo número de amostras.",
            file=sys.stderr,
        )

    amostras_truncadas = np.asarray(amostras_brutas[:n_truncado])
    matriz = amostras_truncadas.reshape(n_ciclos, num_canais)
    indice_no_ciclo = {canal: i for i, canal in enumerate(canais)}

    return {canal: matriz[:, indice_no_ciclo[canal]] for canal in canais_selecionados}


def resolver_offsets_por_canal(offset_texto: str | None, faixas: list[float],
                                formato: str, num_canais: int) -> list[float]:
    """
    Resolve --offset por canal: se o usuário não passou --offset
    (offset_texto is None), aplica o mesmo padrão automático de sempre
    (faixa/2 para --formato uint16, 0.0 para int16), individualmente
    para CADA canal a partir da sua própria --faixa (seção 10.5 do
    docstring) -- em vez de um único offset global. Se o usuário passou
    --offset explicitamente (valor único ou lista), usa
    analisar_lista_calibracao normalmente, sem aplicar o padrão
    automático.
    """
    if offset_texto is None:
        return [faixa / 2.0 if formato == "uint16" else 0.0 for faixa in faixas]
    return analisar_lista_calibracao(offset_texto, num_canais, "--offset")


# ==============================================================================
# 2. MODO DE CONVERSÃO: .bin <-> .csv
# ==============================================================================

def bin_para_csv(caminho_bin: Path, caminho_csv: Path, formato: str,
                  inicio: int, fim: int | None, incluir_tensao: bool,
                  canais: list[int], faixas: list[float], ganhos: list[float],
                  offsets: list[float],
                  tamanho_chunk: int = TAMANHO_CHUNK_PADRAO) -> int:
    """
    Converte um '.bin' (código bruto do ADC, 2 bytes/amostra) para '.csv',
    em blocos de 'tamanho_chunk' amostras -- sem carregar o arquivo
    inteiro na RAM de uma vez (ver seção 8 do docstring do módulo).

    Colunas geradas no CSV:
        amostra      -- índice da amostra no arquivo original (0-based)
        canal        -- SÓ incluída quando len(canais) > 1 (ver seção
                         10.6 do docstring): canal daquela linha,
                         resolvido como canais[amostra % len(canais)].
                         Com 1 canal só, essa coluna não aparece -- o
                         CSV gerado fica byte-a-byte igual ao formato de
                         antes do suporte multi-canal.
        valor_bruto  -- código de 16 bits do ADC, decodificado conforme
                         --formato (é essa coluna, e só ela, que é usada
                         para reconstruir o '.bin' de volta)
        tensao_v     -- só se incluir_tensao=True: tensão já convertida
                         usando a calibração DAQUELE canal (faixas/
                         ganhos/offsets, alinhados posicionalmente com
                         'canais' -- ver seção 10.5), apenas para
                         inspeção humana -- IGNORADA na conversão
                         inversa (csv -> bin)

    'canais'/'faixas'/'ganhos'/'offsets' descrevem a captura (ver seção
    10 do docstring): as três últimas já vêm resolvidas como listas com
    1 valor por canal, na MESMA ordem/tamanho de 'canais' (ver
    analisar_lista_calibracao/resolver_offsets_por_canal). Com 1 canal
    só (fluxo de hoje), todas têm tamanho 1.

    Retorna o número de amostras convertidas.

    NOTA DE DESEMPENHO: a formatação de cada linha é feita com uma
    list comprehension de f-strings + `str.join`, e não com
    `numpy.savetxt` -- em benchmark local (1 048 576 amostras, um
    buffer de produção inteiro), essa abordagem foi ~35% mais rápida
    que `numpy.savetxt` para escrever o mesmo CSV, porque evita o loop
    interno de formatação linha-a-linha do `numpy.savetxt`. A
    calibração por posição-no-ciclo (faixa/ganho/offset de cada
    amostra, quando multi-canal) é resolvida de forma vetorizada por
    bloco via numpy (indexação por `posição % num_canais`), não
    amostra a amostra em Python.
    """
    amostras = carregar_amostras_bin(caminho_bin, formato)
    _, inicio, fim, total = selecionar_intervalo(amostras, inicio, fim)

    num_canais = len(canais)
    incluir_coluna_canal = num_canais > 1

    canais_arr = np.array(canais)
    faixas_arr = np.array(faixas, dtype=np.float64)
    ganhos_arr = np.array(ganhos, dtype=np.float64)
    offsets_arr = np.array(offsets, dtype=np.float64)

    with open(caminho_csv, "w", newline="") as f:
        colunas = ["amostra"]
        if incluir_coluna_canal:
            colunas.append("canal")
        colunas.append("valor_bruto")
        if incluir_tensao:
            colunas.append("tensao_v")
        f.write(",".join(colunas) + "\n")

        for ini_bloco in range(inicio, fim, tamanho_chunk):
            fim_bloco = min(ini_bloco + tamanho_chunk, fim)
            bloco = np.asarray(amostras[ini_bloco:fim_bloco]).astype(np.int64)
            indices = range(ini_bloco, fim_bloco)

            pos_no_ciclo = None
            if incluir_coluna_canal or incluir_tensao:
                pos_no_ciclo = np.arange(ini_bloco, fim_bloco) % num_canais

            if incluir_tensao:
                # converter_para_tensao aceita faixa/ganho/offset como
                # arrays (broadcast elemento a elemento) tão bem quanto
                # escalares -- reaproveitada sem duplicar a fórmula.
                tensao = converter_para_tensao(
                    bloco, faixas_arr[pos_no_ciclo], ganhos_arr[pos_no_ciclo],
                    formato, offsets_arr[pos_no_ciclo],
                )

            if incluir_coluna_canal:
                canal_bloco = canais_arr[pos_no_ciclo]
                if incluir_tensao:
                    linhas = (
                        f"{i},{c},{v},{t:.6f}"
                        for i, c, v, t in zip(indices, canal_bloco.tolist(),
                                               bloco.tolist(), tensao.tolist())
                    )
                else:
                    linhas = (
                        f"{i},{c},{v}"
                        for i, c, v in zip(indices, canal_bloco.tolist(), bloco.tolist())
                    )
            elif incluir_tensao:
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

    Só a coluna 'valor_bruto' é usada para reconstruir os bytes -- ver
    seção 10.6 do docstring do módulo: NÃO precisa de --canais aqui,
    mesmo para um CSV multi-canal, porque a ORDEM das linhas já
    preserva a intercalação original (a reconstrução escreve
    'valor_bruto' de cada linha na ordem em que aparece, exatamente
    como sempre fez). Qualquer outra coluna (ex.: 'tensao_v') é
    ignorada, para garantir que o '.bin' resultante seja byte-a-byte
    equivalente ao original (round-trip sem perdas), em vez de uma
    versão recalculada a partir de uma tensão já arredondada.

    Se existir uma coluna 'canal' (gravada por bin_para_csv em captura
    multi-canal), ela é usada só para uma verificação LEVE (O(1) de
    memória, streaming) de que o padrão de canais se repete
    ciclicamente do início ao fim do arquivo -- não é uma validação
    exaustiva, só um alerta cedo para um CSV editado manualmente ou
    corrompido; não impede a conversão.

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
        indice_coluna_canal = cabecalho.index("canal") if "canal" in cabecalho else None

        fim_absoluto = None if fim is None else fim
        # itertools.islice(f_in, inicio, fim_absoluto) pula 'inicio' linhas
        # de dados e para no índice absoluto 'fim_absoluto' (ou no fim do
        # arquivo, se None) -- tudo em streaming, sem carregar linhas
        # descartadas na memória.
        linhas_dados = itertools.islice(f_in, inicio, fim_absoluto)

        # Estado da verificação leve do padrão cíclico de 'canal' (ver
        # docstring acima) -- tudo em O(1) de memória: só guarda os
        # valores distintos vistos até o padrão se repetir pela primeira
        # vez, nunca o arquivo inteiro.
        padrao_canais: list[str] = []
        periodo_detectado: int | None = None
        posicao_no_padrao = 0
        inconsistencias = 0

        n_convertidas = 0
        with open(caminho_bin, "wb") as f_out:
            bloco = []
            for linha in linhas_dados:
                if not linha.strip():
                    continue  # ignora linha em branco (ex.: fim de arquivo)
                campos = linha.rstrip("\n").split(",")
                bloco.append(int(campos[indice_coluna]))

                if indice_coluna_canal is not None:
                    canal_linha = campos[indice_coluna_canal]
                    if periodo_detectado is None:
                        if canal_linha in padrao_canais:
                            periodo_detectado = len(padrao_canais)
                        else:
                            padrao_canais.append(canal_linha)
                    if periodo_detectado is not None:
                        esperado = padrao_canais[posicao_no_padrao % periodo_detectado]
                        if canal_linha != esperado:
                            inconsistencias += 1
                        posicao_no_padrao += 1

                n_convertidas += 1
                if len(bloco) >= tamanho_chunk:
                    f_out.write(np.array(bloco, dtype=dtype).tobytes())
                    bloco = []
            if bloco:
                f_out.write(np.array(bloco, dtype=dtype).tobytes())

        if indice_coluna_canal is not None and inconsistencias > 0:
            print(
                f"Aviso: a coluna 'canal' de '{caminho_csv}' não segue um "
                f"padrão cíclico consistente ({inconsistencias} linha(s) "
                f"fora do padrão detectado {padrao_canais}). O '.bin' "
                f"gerado preserva a ordem das linhas de qualquer forma, "
                f"mas isso pode indicar um CSV editado manualmente ou "
                f"corrompido.",
                file=sys.stderr,
            )

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
                       canais: list[int], faixas: list[float], ganhos: list[float],
                       offsets: list[float],
                       tamanho_chunk: int) -> None:
    """
    Decide a direção da conversão pelas extensões de entrada/saída e
    despacha para bin_para_csv() ou csv_para_bin() (ver seção 4 do
    docstring do módulo). 'canais'/'faixas'/'ganhos'/'offsets' só têm
    efeito na direção '.bin'->'.csv' (ver seção 10.6) -- na direção
    '.csv'->'.bin' são ignorados, já que essa direção nunca precisou
    dessa informação (nem precisa agora, ver csv_para_bin).
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
                          incluir_tensao, canais, faixas, ganhos, offsets,
                          tamanho_chunk)
        extra = " | coluna tensao_v incluída" if incluir_tensao else ""
        extra_canal = (
            f" | {len(canais)} canais intercalados {canais} (coluna 'canal' incluída)"
            if len(canais) > 1 else ""
        )
        print(f"Convertido: '{caminho_entrada}' (.bin) -> '{caminho_saida}' "
              f"(.csv) | {n} amostra(s) | --formato {formato}{extra}{extra_canal}")
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

    # Janela fixa em Hann aqui, independente de --janela: esta é só uma
    # estimativa GROSSEIRA interna (usada para achar o corte do passa-baixa
    # antes do refinamento por cruzamento por zero, ver seção 6.2), não o
    # espectro final mostrado ao usuário -- Hann é uma escolha robusta e
    # neutra para esse papel de localizar o pico aproximado, e mantê-la
    # fixa evita, por exemplo, que --janela retangular (o padrão, ver seção
    # 6.4) produza vazamento excessivo justamente nesta etapa de triagem.
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

def _normalizar_nome_janela(nome: str) -> str:
    """
    Normaliza um nome de janela vindo de --janela para comparação com
    ALIASES_JANELA: remove acentos, hifens, espaços e underscores, e
    converte para minúsculas. Assim 'Blackman-Harris', 'blackmanharris',
    'BLACKMAN_HARRIS' e 'blackman harris' resolvem todos para a mesma
    chave. Ver seção 6.4 do docstring do módulo.
    """
    sem_acento = unicodedata.normalize("NFKD", nome)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    chave = sem_acento.strip().lower()
    for caractere in ("-", "_", " "):
        chave = chave.replace(caractere, "")
    return chave


def resolver_nome_janela(nome: str) -> str:
    """
    Valida --janela e resolve para o nome canônico aceito por
    scipy.signal.get_window. Levantado logo após o parse dos argumentos
    (antes de carregar qualquer arquivo, potencialmente grande), para dar
    erro rápido em caso de nome digitado errado, em vez de falhar só
    depois de já ter processado a captura inteira.
    """
    chave = _normalizar_nome_janela(nome)
    if chave not in ALIASES_JANELA:
        raise SystemExit(
            f"Erro: janela '{nome}' não reconhecida em --janela. Valores "
            f"aceitos (acentos/hífens/espaços e maiúsculas/minúsculas são "
            f"ignorados): retangular/boxcar (padrão, sem janela), "
            f"hann/hanning, blackmanharris/blackman-harris, "
            f"flattop/flat-top, kaiser."
        )
    return ALIASES_JANELA[chave]


def obter_janela(nome_canonico: str, n: int, kaiser_beta: float) -> np.ndarray:
    """
    Constrói o array (tamanho n) da janela já resolvida para o nome
    canônico do scipy (ver resolver_nome_janela). Usa fftbins=True
    (variante "periódica" da janela, a recomendada para análise
    espectral por FFT -- evita a amostra final redundante da variante
    "simétrica", mais apropriada para filtragem no domínio do tempo).
    """
    if nome_canonico == "kaiser":
        return get_window(("kaiser", kaiser_beta), n, fftbins=True)
    return get_window(nome_canonico, n, fftbins=True)


def calcular_espectro_dbv(sinal: np.ndarray, fs: float, nome_janela: str,
                           kaiser_beta: float):
    """FFT em dBV com a janela escolhida via --janela (ver seção 6.4 do
    docstring do módulo para o trade-off de cada opção; padrão:
    retangular/sem janela).

    A amplitude é corrigida pelo GANHO COERENTE da janela (média dos seus
    valores) -- sem essa correção, a amplitude reportada fica sistemati-
    camente abaixo da real (ex.: para a janela de Hann, ~6 dB abaixo),
    porque a própria janela atenua a energia do sinal antes da FFT. Essa
    correção vale para QUALQUER janela, inclusive a retangular (ganho
    coerente = 1.0, ou seja, sem efeito -- é só o caso trivial da mesma
    fórmula).
    """
    n = len(sinal)
    janela = obter_janela(nome_janela, n, kaiser_beta)
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


def plotar_multicanal(tensoes_por_canal: dict[int, np.ndarray], fs_efetiva: float,
                       idx_inicio_arquivo: int, infos_fft: dict | None,
                       titulo_arquivo: str, caminho_saida: Path | None,
                       layout: str) -> None:
    """
    Plota a forma de onda (e, opcionalmente, o espectro) de 1 ou mais
    canais -- ver seção 10 do docstring do módulo.

    IMPORTANTE (retrocompatibilidade, ver seção 10.8): com 1 canal só,
    este é o MESMO caminho de código que trata múltiplos canais, apenas
    com n_canais==1 -- não existe uma função "plotar de 1 canal"
    separada. O resultado visual (cores, título, ausência de legenda)
    é construído para ficar idêntico ao do antigo `plotar()` de antes do
    suporte multi-canal.

    tensoes_por_canal: dict {canal: array de tensão}, todos os arrays
        do MESMO tamanho (ver desintercalar() -- ela já garante isso,
        truncando para um múltiplo de num_canais). A ordem de iteração
        do dict (preservada desde Python 3.7) define a ordem de
        plotagem/legenda/cores.
    fs_efetiva: frequência de amostragem de CADA canal individualmente
        (--frequencia já dividida pelo número de canais -- seção 10.3).
    infos_fft: None (sem --fft) ou dict {canal: info_fft}, um por canal
        presente em tensoes_por_canal, no mesmo formato que
        recortar_ciclos_inteiros/calcular_espectro_dbv já produzem.
    layout: "separados" ou "sobrepostos" -- ignorado com 1 canal só.
    """
    canais = list(tensoes_por_canal.keys())
    n_canais = len(canais)
    tem_fft = infos_fft is not None

    n = len(tensoes_por_canal[canais[0]])
    fator_tempo, rotulo_tempo = escolher_unidade_tempo(n / fs_efetiva)
    tempo = (np.arange(n) / fs_efetiva) * fator_tempo

    cores = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    usar_eixo_unico = (n_canais == 1) or (layout == "sobrepostos")

    if usar_eixo_unico:
        # --- 1 canal, OU vários canais sobrepostos no mesmo eixo ---
        if tem_fft:
            fig, (ax_tempo, ax_fft) = plt.subplots(2, 1, figsize=(10, 8))
        else:
            fig, ax_tempo = plt.subplots(figsize=(10, 5))
            ax_fft = None

        for i, canal in enumerate(canais):
            cor_tempo = "tab:green" if n_canais == 1 else cores[i % len(cores)]
            rotulo = None if n_canais == 1 else f"Canal {canal}"
            ax_tempo.plot(tempo, tensoes_por_canal[canal], color=cor_tempo,
                          linewidth=1.0, label=rotulo)

        if n_canais == 1:
            ax_tempo.set_title(f"Forma de onda -- amostras {idx_inicio_arquivo} .. "
                                f"{idx_inicio_arquivo + n} de '{titulo_arquivo}'")
        else:
            ax_tempo.set_title(f"Forma de onda -- amostras {idx_inicio_arquivo} .. "
                                f"{idx_inicio_arquivo + n} de '{titulo_arquivo}' "
                                f"(canais {canais}, sobrepostos)")
        ax_tempo.set_xlabel(rotulo_tempo)
        ax_tempo.set_ylabel("Tensão (V)")
        ax_tempo.grid(True, alpha=0.4)

        if tem_fft:
            for i, canal in enumerate(canais):
                info = infos_fft[canal]
                cor_sombra = "tab:orange" if n_canais == 1 else cores[i % len(cores)]
                ini_janela = info["idx_inicio_local"] / fs_efetiva * fator_tempo
                fim_janela = info["idx_fim_local"] / fs_efetiva * fator_tempo
                rotulo_sombra = (
                    f"Janela da FFT ({info['n_ciclos']} ciclo(s))" if n_canais == 1
                    else f"Janela FFT canal {canal} ({info['n_ciclos']} ciclo(s))"
                )
                ax_tempo.axvspan(ini_janela, fim_janela, color=cor_sombra, alpha=0.20,
                                  label=rotulo_sombra)
            ax_tempo.legend(loc="upper right", fontsize=9 if n_canais == 1 else 8)

            for i, canal in enumerate(canais):
                info = infos_fft[canal]
                cor_fft = "tab:blue" if n_canais == 1 else cores[i % len(cores)]
                rotulo_fft = None if n_canais == 1 else f"Canal {canal} (f0={info['f0']:.2f} Hz)"
                ax_fft.plot(info["freqs"], info["amplitude_db"], color=cor_fft,
                            linewidth=1.2, label=rotulo_fft)

            if n_canais == 1:
                info = infos_fft[canais[0]]
                ax_fft.set_title(
                    f"Espectro de Frequência -- f0 estimada = {info['f0']:.3f} Hz "
                    f"| {info['n_ciclos']} ciclo(s) completo(s) | janela: "
                    f"{info['janela']}"
                )
            else:
                ax_fft.set_title(f"Espectro de Frequência -- canais {canais} | "
                                  f"janela: {infos_fft[canais[0]]['janela']}")
                ax_fft.legend(loc="upper right", fontsize=8)

            ax_fft.set_xlabel("Frequência (Hz)")
            ax_fft.set_ylabel("Magnitude (dBV)")
            ax_fft.grid(True, which="both", ls="-", alpha=0.4)

            nyquist = fs_efetiva / 2.0
            ax_fft.set_xlim(0, nyquist * 1.10)
            ax_fft.set_ylim(bottom=-100)

        plt.tight_layout()

    else:
        # --- vários canais, layout "separados": 1 linha de subplots por canal ---
        n_colunas = 2 if tem_fft else 1
        fig, eixos = plt.subplots(n_canais, n_colunas,
                                   figsize=(6.5 * n_colunas, 3.2 * n_canais),
                                   squeeze=False)

        for i, canal in enumerate(canais):
            cor = cores[i % len(cores)]
            ax_tempo = eixos[i, 0]

            ax_tempo.plot(tempo, tensoes_por_canal[canal], color=cor, linewidth=1.0)
            ax_tempo.set_title(f"Canal {canal} -- amostras {idx_inicio_arquivo} .. "
                                f"{idx_inicio_arquivo + n}")
            ax_tempo.set_xlabel(rotulo_tempo)
            ax_tempo.set_ylabel("Tensão (V)")
            ax_tempo.grid(True, alpha=0.4)

            if tem_fft:
                info = infos_fft[canal]
                ax_fft = eixos[i, 1]

                ini_janela = info["idx_inicio_local"] / fs_efetiva * fator_tempo
                fim_janela = info["idx_fim_local"] / fs_efetiva * fator_tempo
                ax_tempo.axvspan(ini_janela, fim_janela, color=cor, alpha=0.20,
                                  label=f"Janela da FFT ({info['n_ciclos']} ciclo(s))")
                ax_tempo.legend(loc="upper right", fontsize=8)

                ax_fft.plot(info["freqs"], info["amplitude_db"], color=cor, linewidth=1.2)
                ax_fft.set_title(f"Canal {canal} -- f0 = {info['f0']:.3f} Hz | "
                                  f"{info['n_ciclos']} ciclo(s) | janela: {info['janela']}")
                ax_fft.set_xlabel("Frequência (Hz)")
                ax_fft.set_ylabel("Magnitude (dBV)")
                ax_fft.grid(True, which="both", ls="-", alpha=0.4)

                nyquist = fs_efetiva / 2.0
                ax_fft.set_xlim(0, nyquist * 1.10)
                ax_fft.set_ylim(bottom=-100)

        fig.suptitle(f"'{titulo_arquivo}' -- canais {canais} (separados)")
        plt.tight_layout(rect=[0, 0, 1, 0.97])

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
            "  # FFT com janela Blackman-Harris (menos vazamento espectral)\n"
            "  %(prog)s captura.bin -f 102400 --fft --janela blackman-harris\n"
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
            "\n"
            "  # -- Multi-canal (seção 10 do docstring) --------------------\n"
            "  # Captura feita com `ler_adc 102400 0,1,3`: 3 canais, plotados\n"
            "  # um por subplot (padrão --layout-canais separados)\n"
            "  %(prog)s captura.bin -f 102400 --canais 0,1,3 --fft\n"
            "\n"
            "  # Mesma captura, só os canais 0 e 3, sobrepostos no mesmo eixo\n"
            "  %(prog)s captura.bin -f 102400 --canais 0,1,3 "
            "--canais-exibir 0,3 --layout-canais sobrepostos --fft\n"
            "\n"
            "  # Canal 0 = tensão (ganho 19.53), canal 1 = corrente (ganho 0.1)\n"
            "  %(prog)s captura.bin -f 102400 --canais 0,1 --ganho 19.53,0.1 --fft\n"
            "\n"
            "  # Converter captura multi-canal para .csv (ganha a coluna 'canal')\n"
            "  %(prog)s -c captura.bin -o captura.csv --canais 0,1,3\n"
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
             "em Hz (ex.: -f 102400). Com mais de 1 canal em --canais, "
             "esta é a frequência TOTAL de transação passada a `ler_adc` "
             "(mesmo significado de sempre) -- a frequência EFETIVA de "
             "cada canal é esse valor dividido pelo número de canais (ver "
             "seção 10.3 do docstring). Define o eixo do tempo e o eixo "
             "de frequência da FFT. OBRIGATÓRIO no modo de plotagem; NÃO "
             "USADO no modo de conversão (a taxa de amostragem não é "
             "gravada dentro dos arquivos '.bin'/'.csv')."
    )

    grupo_multicanal = parser.add_argument_group(
        "Captura multi-canal (ver seção 10 do docstring do módulo)",
        "Uma captura de `ler_adc <freq> <canais>` com mais de 1 canal "
        "grava as amostras intercaladas (round-robin) num único arquivo, "
        "sem cabeçalho -- estas flags dizem a este script como "
        "desintercalar de volta. Válidas tanto no modo de plotagem quanto "
        "na conversão '.bin'->'.csv'.",
    )
    grupo_multicanal.add_argument(
        "--canais", type=str, default=CANAL_PADRAO, metavar="LISTA",
        help="Canais presentes no arquivo, separados por vírgula sem "
             "espaços, na MESMA ordem usada na captura (`ler_adc <freq> "
             "<canais>`) -- ex.: '0,1,3'. Padrão: '1' (um canal só, "
             "idêntico ao comportamento deste script antes do suporte "
             "multi-canal). `ler_adc` já imprime a lista usada no "
             "console durante a captura, para anotação -- o '.bin' em si "
             "não carrega esse metadado."
    )
    grupo_multicanal.add_argument(
        "--canais-exibir", type=str, default=None, metavar="LISTA",
        help="Subconjunto de --canais a efetivamente plotar/analisar "
             "(padrão: todos os canais de --canais). Útil para focar em "
             "1-2 canais de uma captura com vários, sem precisar "
             "reprocessar --canais inteiro. Precisa ser um subconjunto "
             "de --canais."
    )
    grupo_multicanal.add_argument(
        "--layout-canais", choices=["separados", "sobrepostos"],
        default="separados",
        help="[MODO DE PLOTAGEM, só importa com mais de 1 canal em "
             "--canais-exibir] Como organizar múltiplos canais na "
             "mesma figura. 'separados' (PADRÃO): um subplot de forma "
             "de onda por canal (mais um de espectro por canal, se "
             "--fft) -- mais seguro visualmente quando os canais medem "
             "grandezas diferentes (ex.: tensão e corrente, escalas bem "
             "distintas). 'sobrepostos': todos os canais no MESMO eixo "
             "de tempo (e no mesmo eixo de frequência, se --fft), cada "
             "um com uma cor e uma entrada na legenda."
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
        "--janela", type=str, default=JANELA_PADRAO, metavar="NOME",
        help="[MODO DE PLOTAGEM, só com --fft] Janela aplicada ao trecho "
             "antes da FFT PRINCIPAL (a que gera o espectro exibido/salvo "
             "-- não afeta a estimativa grosseira interna da fundamental, "
             "que sempre usa Hann, nem o recorte em ciclos inteiros; ver "
             "seção 6.4 do docstring do módulo para o trade-off completo "
             "de cada opção). Acentos, hifens, espaços e maiúsculas/"
             "minúsculas são ignorados ao interpretar o valor. Valores "
             "aceitos: 'retangular' ou 'boxcar' (SEM janela -- PADRÃO; "
             "melhor resolução em frequência e nenhuma atenuação de "
             "amplitude, mas mais sensível a qualquer imperfeição residual "
             "no recorte em ciclos inteiros); 'hann' ou 'hanning' "
             "(compromisso clássico entre resolução e vazamento); "
             "'blackmanharris' ou 'blackman-harris' (lóbulos laterais "
             "muito baixos, ~-92 dB -- ajuda a separar um supraharmônico "
             "fraco perto de uma fundamental forte, ao custo de um lóbulo "
             "principal mais largo); 'flattop' ou 'flat-top' (topo do "
             "lóbulo principal muito plano -- melhor EXATIDÃO DE "
             "AMPLITUDE para medir o valor de pico de uma componente já "
             "conhecida, mas a pior resolução em frequência de todas); "
             "'kaiser' (parâmetro ajustável via --kaiser-beta, permite "
             "variar continuamente entre resolução e rejeição de lóbulo "
             "lateral). Exemplos: '--janela blackmanharris' ou "
             "'--janela blackman-harris' (equivalentes)."
    )
    parser.add_argument(
        "--kaiser-beta", type=float, default=8.6, metavar="BETA",
        help="[MODO DE PLOTAGEM, só com --janela kaiser] Parâmetro beta da "
             "janela Kaiser: controla o compromisso entre a largura do "
             "lóbulo principal (resolução em frequência) e a atenuação "
             "dos lóbulos laterais (rejeição de vazamento espectral) -- "
             "beta maior = lóbulos laterais mais baixos, porém lóbulo "
             "principal mais largo. Padrão: 8.6 (atenuação de lóbulo "
             "lateral próxima da janela Blackman, ~-58 dB). Referências "
             "aproximadas: beta=0 -> equivalente à retangular; beta≈5 -> "
             "equivalente à Hamming; beta≈6 -> equivalente à Hann; "
             "beta≈8.6 -> equivalente à Blackman; beta≈14 -> lóbulos "
             "laterais muitíssimo baixos (~-120 dB), lóbulo principal bem "
             "mais largo. Ignorado se --janela não for 'kaiser'."
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
        "--faixa", type=str, default="10.24", metavar="VOLTS",
        help="[Conversão para tensão: plotagem, ou conversão de arquivo "
             "com --incluir-tensao] Faixa de fundo de escala do ADC em "
             "Volts (padrão: 10.24, a faixa bipolar default de fábrica do "
             "ADS8688: ±10.24 V). ACEITA um valor único (aplicado a "
             "TODOS os canais de --canais) ou uma lista separada por "
             "vírgula do mesmo tamanho de --canais, um valor por canal, "
             "na mesma ordem (ex.: --canais 0,1 --faixa 10.24,10.24) -- "
             "ver seção 10.5 do docstring para o caso de uso (canais com "
             "sensores/faixas diferentes, ex.: tensão e corrente)."
    )
    parser.add_argument(
        "--ganho", type=str, default="1.0", metavar="FATOR",
        help="[Conversão para tensão: plotagem, ou conversão de arquivo "
             "com --incluir-tensao] Fator de ganho do sensor/PCB para "
             "converter a tensão no ADC na tensão real da rede (padrão: "
             "1.0, sem conversão adicional). ACEITA um valor único "
             "(aplicado a TODOS os canais) ou uma lista separada por "
             "vírgula do mesmo tamanho de --canais, um valor por canal "
             "(ex.: --canais 0,1 --ganho 19.53,0.1 -- canal 0 é tensão "
             "com ganho 19.53, canal 1 é corrente com ganho 0.1). Ver "
             "seção 10.5 do docstring."
    )
    parser.add_argument(
        "--offset", type=str, default=None, metavar="VOLTS",
        help="[Conversão para tensão: plotagem, ou conversão de arquivo "
             "com --incluir-tensao] Deslocamento DC subtraído da tensão "
             "do ADC antes do ganho (padrão automático, calculado por "
             "canal a partir da respectiva --faixa: faixa/2 para "
             "--formato uint16, o que centraliza a onda CA em torno de "
             "0 V; 0.0 para --formato int16, que já é bipolar). Ajuste "
             "manualmente se o offset real do seu ADC/sensor não for "
             "exatamente metade da faixa (erro de calibração). ACEITA um "
             "valor único (todos os canais) ou uma lista separada por "
             "vírgula do mesmo tamanho de --canais, mesma convenção de "
             "--faixa/--ganho (ver seção 10.5)."
    )

    return parser


def main(argv=None):
    parser = montar_parser()
    args = parser.parse_args(argv)

    # Resolve a configuração multi-canal cedo (antes de carregar qualquer
    # arquivo, que pode ser grande) -- mesma filosofia de --janela abaixo,
    # e ver seção 10 do docstring do módulo. Vale para os dois modos; com
    # o padrão --canais "1" (não passado), tudo se reduz ao comportamento
    # de sempre (1 canal só) -- o caminho de 1 canal é um caso particular
    # deste mesmo fluxo, não um fluxo separado (seção 10.8).
    canais = analisar_lista_canais(args.canais, "--canais")
    if args.canais_exibir is not None:
        canais_exibir = analisar_lista_canais(args.canais_exibir, "--canais-exibir")
        validar_subconjunto_canais(canais_exibir, canais)
    else:
        canais_exibir = canais

    faixas = analisar_lista_calibracao(args.faixa, len(canais), "--faixa")
    ganhos = analisar_lista_calibracao(args.ganho, len(canais), "--ganho")
    offsets = resolver_offsets_por_canal(args.offset, faixas, args.formato, len(canais))

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
            args.incluir_tensao, canais, faixas, ganhos, offsets,
            args.tamanho_chunk,
        )
        return

    # --------------------------------------------------------------------
    # MODO DE PLOTAGEM
    # --------------------------------------------------------------------
    if args.arquivo is None:
        parser.error(
            "o argumento 'arquivo' é obrigatório no modo de plotagem "
            "(ou use -c/--converter para converter .bin<->.csv)."
        )
    if args.frequencia is None:
        parser.error("-f/--frequencia é obrigatório no modo de plotagem.")

    # Valida --janela cedo (antes de carregar o arquivo, que pode ser
    # grande) para dar erro imediato em caso de nome digitado errado, em
    # vez de só falhar depois de já ter processado a captura inteira.
    nome_janela_canonico = None
    if args.fft is not None:
        nome_janela_canonico = resolver_nome_janela(args.janela)

    tipo_arquivo = detectar_tipo_arquivo(args.arquivo)
    amostras = carregar_amostras(args.arquivo, args.formato)
    bruto, idx_inicio, idx_fim, total = selecionar_intervalo(
        amostras, args.inicio, args.fim
    )

    num_canais = len(canais)
    # Frequência EFETIVA de cada canal individual -- ver seção 10.3 do
    # docstring. Com 1 canal só, isso é exatamente args.frequencia (sem
    # nenhuma mudança de comportamento).
    fs_efetiva = args.frequencia / num_canais

    # Desintercala (ver seção 10.1/10.7) -- com 1 canal só, isso é um
    # reshape trivial que devolve o mesmo conteúdo do array original.
    por_canal_bruto = desintercalar(bruto, canais, canais_exibir)
    indice_no_ciclo = {c: i for i, c in enumerate(canais)}

    por_canal_tensao: dict[int, np.ndarray] = {}
    for canal in canais_exibir:
        idx = indice_no_ciclo[canal]
        por_canal_tensao[canal] = converter_para_tensao(
            por_canal_bruto[canal], faixas[idx], ganhos[idx], args.formato, offsets[idx]
        )

    n_por_canal = len(next(iter(por_canal_tensao.values())))

    print(f"Arquivo: {args.arquivo}  ({total} amostras no total, "
          f"formato de arquivo: .{tipo_arquivo})")

    if num_canais == 1:
        # Texto idêntico ao de antes do suporte multi-canal.
        idx0 = indice_no_ciclo[canais_exibir[0]]
        print(f"Conversão: --formato {args.formato} | --faixa {faixas[idx0]} V | "
              f"--offset {offsets[idx0]} V | --ganho {ganhos[idx0]}")
        print(f"Janela selecionada: amostras {idx_inicio}..{idx_fim} "
              f"({n_por_canal} amostras, {n_por_canal / fs_efetiva * 1000:.2f} ms)")
    else:
        print(f"Canais na captura: {canais} | exibindo: {canais_exibir} | "
              f"layout: {args.layout_canais}")
        print(f"Frequência total {args.frequencia:g} Hz / {num_canais} canais "
              f"-> frequência efetiva por canal: {fs_efetiva:g} Hz")
        for canal in canais_exibir:
            idx = indice_no_ciclo[canal]
            print(f"  Canal {canal}: --formato {args.formato} | "
                  f"--faixa {faixas[idx]} V | --offset {offsets[idx]} V | "
                  f"--ganho {ganhos[idx]}")
        print(f"Janela selecionada: amostras brutas {idx_inicio}..{idx_fim} "
              f"({n_por_canal} amostras/canal, "
              f"{n_por_canal / fs_efetiva * 1000:.2f} ms/canal)")

    infos_fft = None
    if args.fft is not None:
        n_ciclos_pedido = args.fft if args.fft > 0 else None
        infos_fft = {}
        for canal in canais_exibir:
            sinal_fft, idx_i_local, idx_f_local, f0, n_ciclos = recortar_ciclos_inteiros(
                por_canal_tensao[canal], fs_efetiva, args.freq_min, args.freq_max,
                n_ciclos_pedido
            )
            freqs, amplitude_db = calcular_espectro_dbv(
                sinal_fft, fs_efetiva, nome_janela_canonico, args.kaiser_beta
            )

            rotulo_janela = NOMES_EXIBICAO_JANELA[nome_janela_canonico]
            if nome_janela_canonico == "kaiser":
                rotulo_janela += f" (beta={args.kaiser_beta:g})"

            if num_canais == 1:
                print(f"FFT: fundamental estimada f0 = {f0:.3f} Hz | "
                      f"{n_ciclos} ciclo(s) completo(s) | "
                      f"{len(sinal_fft)} amostras (amostras locais {idx_i_local}..{idx_f_local}) | "
                      f"janela: {rotulo_janela}")
            else:
                print(f"  Canal {canal}: FFT f0 = {f0:.3f} Hz | "
                      f"{n_ciclos} ciclo(s) completo(s) | {len(sinal_fft)} amostras "
                      f"(locais {idx_i_local}..{idx_f_local}) | janela: {rotulo_janela}")

            infos_fft[canal] = {
                "freqs": freqs,
                "amplitude_db": amplitude_db,
                "f0": f0,
                "n_ciclos": n_ciclos,
                "idx_inicio_local": idx_i_local,
                "idx_fim_local": idx_f_local,
                "janela": rotulo_janela,
            }

    plotar_multicanal(por_canal_tensao, fs_efetiva, idx_inicio, infos_fft,
                       args.arquivo.name, args.saida, args.layout_canais)


if __name__ == "__main__":
    main()