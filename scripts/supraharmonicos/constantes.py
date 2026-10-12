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
    "uint16": np.dtype("<u2"),  # binário reto, unipolar (padrão de fábrica)
}

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
