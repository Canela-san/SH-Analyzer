"""Constantes compartilhadas do SH-Analyzer.

Valores que também existem no firmware (``firmware/*.c``/``*.h``) estão
marcados abaixo e PRECISAM ficar em sincronia manual com aquele lado -- o
teste ``tests/test_contrato_firmware.py`` confere isso automaticamente a
cada execução do pytest.

Camada 0: não importa nenhum outro módulo do pacote."""


import numpy as np

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

TAMANHO_CHUNK_PADRAO = 500_000

FORMATOS_NUMPY = {
    "int16": np.dtype("<i2"),   # complemento de dois, bipolar
    "uint16": np.dtype("<u2"),  # binário deslocado: 0 = -fundo de escala, 32768 = 0 V (o que o ADS8688 entrega)
}

# Janela padrão de cada método (o --janela da CLI vale para os dois). FFT sincronizada em ciclos inteiros: a
# retangular, sem vazamento para a fundamental e os harmônicos (como a IEC 61000-4-7). Welch: a Hann, o padrão da
# literatura e do scipy.signal.welch -- a retangular, num segmento que não é síncrono com nada, vaza.
JANELA_PADRAO_FFT = "retangular"
JANELA_PADRAO_WELCH = "hann"
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
NOMES_EXIBICAO_JANELA = {
    "boxcar": "Retangular (sem janela)",
    "hann": "Hann",
    "blackmanharris": "Blackman-Harris",
    "flattop": "Flat Top",
    "kaiser": "Kaiser",
}

# Precisa ficar em sincronia manual com ADS8688_MAX_CANAIS em
# firmware/memoria_pru.h -- não há arquivo de constantes compartilhado entre
# o firmware em C/Assembly e este script.
ADS8688_MAX_CANAIS = 8
CANAL_PADRAO = "1"

# [SONDA/GRANDEZA] Mesmos valores de GRANDEZA_TENSAO/CORRENTE/TEMPERATURA/
# NAO_USADA em firmware/ler_adc.c -- precisa ficar em sincronia manual com
# aquele lado, mesma situação de ADS8688_MAX_CANAIS acima.
GRANDEZA_TENSAO = 0
GRANDEZA_CORRENTE = 1
GRANDEZA_TEMPERATURA = 2
GRANDEZA_NAO_USADA = 0xFF
GRANDEZA_PADRAO = GRANDEZA_TENSAO  # mesmo padrão histórico do lado C: canal sem info assumido como tensão

NOMES_GRANDEZA = {
    GRANDEZA_TENSAO: "tensão",
    GRANDEZA_CORRENTE: "corrente",
    GRANDEZA_TEMPERATURA: "temperatura",
}
UNIDADE_GRANDEZA = {
    GRANDEZA_TENSAO: "V",
    GRANDEZA_CORRENTE: "A",
    GRANDEZA_TEMPERATURA: "°C",
}
NOMES_GRANDEZA_CLI = {  # valores aceitos em --grandeza (sem acento, como no lado C)
    "tensao": GRANDEZA_TENSAO,
    "corrente": GRANDEZA_CORRENTE,
    "temperatura": GRANDEZA_TEMPERATURA,
}

# [FAIXA DE ENTRADA POR CANAL, cabeçalho v3] Código de faixa do ADS8688
# (registrador RANGE_SELn, Range_CHn[3:0]) -> fundo de escala TOTAL em Volts
# (pico a pico: o dobro da faixa "±X V"), que é o que `--faixa` espera com
# `--formato uint16` (o padrão). Precisa ficar em sincronia manual com
# ADS8688_FAIXA_* em firmware/memoria_pru.h e FAIXA_ADC_ESPAN_V em
# firmware/ler_adc.c -- tests/test_contrato_firmware.py confere.
#     0 = ±2,5·VREF   (±10,24 V; padrão de reset do ADC)
#     1 = ±1,25·VREF  (±5,12 V)
#     2 = ±0,625·VREF (±2,56 V)
FAIXAS_ADC_TOTAL_V = {0: 20.48, 1: 10.24, 2: 5.12}
FAIXA_ADC_NAO_USADA = 0xFF  # slot de canal não habilitado em faixa_adc_por_canal
# `--faixa` (fundo de escala TOTAL, --formato uint16) assumido quando nem a linha de comando nem o cabeçalho dizem
# a faixa (capturas v1/v2 ou sem cabeçalho, anteriores ao registro da faixa). O firmware dessa época nunca escrevia
# RANGE_SELn, então o ADC estava na faixa de reset, ±10,24 V -- conferido em bancada (T0, 19/10/2026: a mesma tensão
# no pino nas três faixas). Até out/2026 as ferramentas assumiam 10.24, o que lia essas capturas com METADE do valor.
FAIXA_LEGADA_V = 20.48
# Tolerância (V) ao comparar um --faixa digitado com a faixa do cabeçalho.
TOLERANCIA_FAIXA_V = 0.005

ORDEM_FILTRO_MINIMA = 4
ORDEM_FILTRO_MAXIMA = 8
ORDEM_FILTRO_PADRAO = 5

# Início convencional da faixa de supraharmônicos (IEC 61000-4-7) -- usado
# como padrão de busca de picos, não como corte de filtro automático (ver
# --filtro-passa-alta).
CORTE_SUPRAHARMONICOS_PADRAO = 2000.0
RESOLUCAO_WELCH_PADRAO = 200.0
SOBREPOSICAO_WELCH_PADRAO = 0.5
DISTANCIA_MINIMA_PICOS_PADRAO = 100.0
TAMANHO_LOTE_WELCH_PADRAO = 2048
