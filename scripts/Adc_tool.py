#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "matplotlib>=3.10.9",
#     "numpy>=1.20",
#     "scipy>=1.15.3",
#     "PyQt6",
# ]
# ///
"""
adc_tool.py -- Conversão, visualização e análise espectral de capturas do
SH-Analyzer (ADS8688 via BeagleBone).

Dois modos:
  - Conversão (-c/--converter + -o/--saida): '.bin' <-> '.csv'.
  - Plotagem (padrão): forma de onda e, opcionalmente, espectro.

Duas estratégias de análise espectral, escolhidas conforme o tipo de sinal:
  - --fft: FFT única, sincronizada em ciclos inteiros da fundamental (corte
    por cruzamento de zero, ver recortar_ciclos_inteiros). Ideal para a
    fundamental e harmônicos de baixa ordem, cuja fase está travada ao ciclo
    da rede.
  - --welch: espectro médio por segmentação, método de Welch (ver
    calcular_espectro_welch). Ideal para supraharmônicos: ruído de
    conversores chaveados não tem relação de fase com o ciclo da rede, então
    o corte em ciclos inteiros não elimina o vazamento desse conteúdo -- aqui
    o controle é feito pela janela espectral e pela média entre segmentos,
    que também suaviza deriva de frequência de chaveamento (dithering) ao
    longo da captura.

--modo-espectro escolhe a normalização usada por --fft e --welch: 'tom'
(amplitude de um tom discreto) ou 'ruido' (densidade espectral de potência,
invariante ao tamanho da FFT/segmento -- ver _normalizar_espectro).
--agrupar-bandas resume o espectro em bandas de largura fixa (convenção da
literatura de supraharmônicos). --picos extrai frequência e amplitude de
componentes espectrais individuais por interpolação parabólica.

Suporta captura multi-canal intercalada (--canais/--canais-exibir), com
calibração e filtragem digital Butterworth por canal. Rode com --help para a
referência completa de flags.
"""

import itertools
import sys
import unicodedata
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, find_peaks, get_window, sosfiltfilt
from scipy.fft import rfft, rfftfreq

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


# ---------------------------------------------------------------------------
# 1. Leitura e escrita de amostras
# ---------------------------------------------------------------------------

def detectar_tipo_arquivo(caminho: Path) -> str:
    """Detecta '.bin' ou '.csv' pela extensão -- qualquer outra é erro do
    usuário (ex.: caminho de saída digitado errado)."""
    sufixo = caminho.suffix.lower()
    if sufixo == ".bin":
        return "bin"
    if sufixo == ".csv":
        return "csv"
    raise SystemExit(
        f"Erro: extensão '{sufixo or '(nenhuma)'}' não reconhecida em "
        f"'{caminho}'. Use '.bin' ou '.csv'."
    )


def carregar_amostras_bin(caminho: Path, formato: str) -> np.memmap:
    """Memory-map: só as páginas efetivamente acessadas (--inicio/--fim, ou
    o processamento em blocos da conversão) são carregadas na RAM."""
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
    """Lê a coluna 'valor_bruto' -- a mesma fonte de verdade usada para
    reconstruir o '.bin'. Ao contrário do memmap, um '.csv' precisa ser
    escaneado inteiro para ser interpretado, então é carregado por completo."""
    try:
        with open(caminho, "r", newline="") as f:
            primeira_linha = f.readline()
            if not primeira_linha:
                raise SystemExit(f"Erro: '{caminho}' está vazio.")
            cabecalho = primeira_linha.strip().split(",")
            if "valor_bruto" not in cabecalho:
                raise SystemExit(
                    f"Erro: '{caminho}' não tem coluna 'valor_bruto' "
                    f"(colunas encontradas: {cabecalho})."
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
    tipo = detectar_tipo_arquivo(caminho)
    if tipo == "bin":
        return carregar_amostras_bin(caminho, formato)
    return carregar_amostras_csv(caminho, formato)


def selecionar_intervalo(amostras, inicio: int, fim: int | None):
    """Aplica --inicio/--fim (em amostras). Funciona igual para memmap
    (fatiar só toca as páginas pedidas) ou ndarray já carregado."""
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
    """codigo -> Volts: unipolar (uint16, 0..+faixa) ou bipolar (int16,
    -faixa..+faixa). 'offset' remove o nível DC antes do ganho -- para
    uint16, o padrão é faixa/2, recuperando a onda CA centrada em 0 V."""
    codigos = codigos.astype(np.float64)
    if formato == "int16":
        tensao_adc = codigos * (faixa / 32768.0)
    else:
        tensao_adc = codigos * (faixa / 65536.0)
    return (tensao_adc - offset) * ganho


# ---------------------------------------------------------------------------
# 2. Suporte multi-canal
# ---------------------------------------------------------------------------

def analisar_lista_canais(texto: str, nome_flag: str = "--canais") -> list[int]:
    """Mesmas regras de validação usadas em firmware/ler_adc.c: canal 0-7,
    sem repetição. A ORDEM é preservada -- define a convenção de
    intercalação round-robin do arquivo."""
    partes = [p.strip() for p in texto.split(",")]
    canais: list[int] = []
    for p in partes:
        if p == "":
            continue
        try:
            valor = int(p)
        except ValueError:
            raise SystemExit(f"Erro: '{p}' não é um canal válido em {nome_flag}='{texto}'.")
        if valor < 0 or valor > 7:
            raise SystemExit(f"Erro: canal {valor} inválido em {nome_flag} -- ADS8688 só tem canais 0-7.")
        if valor in canais:
            raise SystemExit(f"Erro: canal {valor} repetido em {nome_flag}='{texto}'.")
        if len(canais) >= ADS8688_MAX_CANAIS:
            raise SystemExit(f"Erro: mais de {ADS8688_MAX_CANAIS} canais em {nome_flag}='{texto}'.")
        canais.append(valor)

    if not canais:
        raise SystemExit(f"Erro: lista de canais vazia em {nome_flag}.")
    return canais


def validar_subconjunto_canais(canais_exibir: list[int], canais: list[int]) -> None:
    faltando = [c for c in canais_exibir if c not in canais]
    if faltando:
        raise SystemExit(
            f"Erro: --canais-exibir pede o(s) canal(is) {faltando}, ausente(s) "
            f"em --canais ({canais})."
        )


def analisar_lista_calibracao(texto: str, num_canais: int, nome_flag: str) -> list[float]:
    """--faixa/--ganho/--offset: um valor único (todos os canais) ou uma
    lista do mesmo tamanho de --canais, na mesma ordem."""
    partes = [p.strip() for p in texto.split(",")]
    try:
        valores = [float(p) for p in partes]
    except ValueError:
        raise SystemExit(f"Erro: valor inválido em {nome_flag}='{texto}'.")
    if len(valores) == 1:
        return valores * num_canais
    if len(valores) != num_canais:
        raise SystemExit(
            f"Erro: {nome_flag} tem {len(valores)} valor(es), mas --canais tem "
            f"{num_canais} canal(is). Passe 1 valor ou exatamente {num_canais}."
        )
    return valores


def desintercalar(amostras_brutas, canais: list[int],
                   canais_selecionados: list[int] | None = None) -> dict[int, np.ndarray]:
    """Desintercala via reshape(-1, num_canais) + seleção de coluna -- sem
    cópia (view), mesmo sobre um memmap de '.bin'. Trunca para um múltiplo de
    num_canais, descartando o resto no final (mantém todos os canais com o
    mesmo número de amostras)."""
    if canais_selecionados is None:
        canais_selecionados = canais

    num_canais = len(canais)
    n = len(amostras_brutas)
    n_ciclos = n // num_canais
    n_truncado = n_ciclos * num_canais

    if n_truncado == 0:
        raise SystemExit(
            f"Erro: só {n} amostra(s) bruta(s), insuficiente para 1 ciclo de "
            f"{num_canais} canais."
        )
    if n_truncado < n:
        print(
            f"Aviso: {n - n_truncado} amostra(s) no final do recorte não "
            f"completam um ciclo de {num_canais} canais e foram descartadas.",
            file=sys.stderr,
        )

    amostras_truncadas = np.asarray(amostras_brutas[:n_truncado])
    matriz = amostras_truncadas.reshape(n_ciclos, num_canais)
    indice_no_ciclo = {canal: i for i, canal in enumerate(canais)}
    return {canal: matriz[:, indice_no_ciclo[canal]] for canal in canais_selecionados}


def resolver_offsets_por_canal(offset_texto: str | None, faixas: list[float],
                                formato: str, num_canais: int) -> list[float]:
    """Sem --offset explícito, aplica o padrão automático (faixa/2 para
    uint16, 0.0 para int16) individualmente para cada canal, a partir da
    própria --faixa desse canal."""
    if offset_texto is None:
        return [faixa / 2.0 if formato == "uint16" else 0.0 for faixa in faixas]
    return analisar_lista_calibracao(offset_texto, num_canais, "--offset")


# ---------------------------------------------------------------------------
# 3. Filtragem digital opcional (Butterworth, SOS + sosfiltfilt)
# ---------------------------------------------------------------------------

def validar_corte_filtro(corte: float, fs: float, nome_flag: str) -> None:
    """Valida contra a Nyquist EFETIVA do canal (fs já é por canal, não a
    frequência total de --frequencia). Chamada antes de carregar o arquivo,
    que pode ser grande."""
    nyquist = fs / 2.0
    if corte <= 0:
        raise SystemExit(f"Erro: {nome_flag} precisa ser positivo (recebido: {corte:g} Hz).")
    if corte >= nyquist:
        raise SystemExit(
            f"Erro: {nome_flag}={corte:g} Hz precisa ser menor que a Nyquist "
            f"efetiva ({nyquist:g} Hz = {fs:g} Hz / 2)."
        )


def aplicar_filtro_digital(sinal: np.ndarray, fs: float, tipo: str,
                            corte: float, ordem: int) -> np.ndarray:
    """Butterworth em SOS (não a forma clássica (b, a)): nas ordens mais
    altas aceitas aqui (4-8), (b, a) perde precisão numérica; SOS decompõe em
    seções de 2ª ordem bem condicionadas. sosfiltfilt filtra para frente e
    para trás (fase zero) -- um atraso de fase deslocaria os cruzamentos por
    zero usados no corte em ciclos inteiros e distorceria a forma de onda no
    tempo, ao custo de dobrar a ordem efetiva (magnitude ao quadrado)."""
    nyquist = fs / 2.0
    sos = butter(ordem, corte / nyquist, btype=tipo, output="sos")
    try:
        return sosfiltfilt(sos, sinal)
    except ValueError as e:
        rotulo = "passa-baixa" if tipo == "low" else "passa-alta"
        raise SystemExit(
            f"Erro ao aplicar o filtro {rotulo} (corte {corte:g} Hz, ordem "
            f"{ordem}): {e}. A janela selecionada provavelmente tem poucas "
            f"amostras para essa ordem -- aumente a janela ou reduza "
            f"--ordem-filtro."
        )


# ---------------------------------------------------------------------------
# 4. Modo de conversão: .bin <-> .csv
# ---------------------------------------------------------------------------

def bin_para_csv(caminho_bin: Path, caminho_csv: Path, formato: str,
                  inicio: int, fim: int | None, incluir_tensao: bool,
                  canais: list[int], faixas: list[float], ganhos: list[float],
                  offsets: list[float],
                  tamanho_chunk: int = TAMANHO_CHUNK_PADRAO) -> int:
    """Converte em blocos, sem carregar o '.bin' inteiro na RAM. Ganha uma
    coluna 'canal' quando len(canais) > 1 (formato de 1 canal permanece
    idêntico ao de antes do suporte multi-canal)."""
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
                tensao = converter_para_tensao(
                    bloco, faixas_arr[pos_no_ciclo], ganhos_arr[pos_no_ciclo],
                    formato, offsets_arr[pos_no_ciclo],
                )

            if incluir_coluna_canal:
                canal_bloco = canais_arr[pos_no_ciclo]
                if incluir_tensao:
                    linhas = (f"{i},{c},{v},{t:.6f}" for i, c, v, t in
                              zip(indices, canal_bloco.tolist(), bloco.tolist(), tensao.tolist()))
                else:
                    linhas = (f"{i},{c},{v}" for i, c, v in
                              zip(indices, canal_bloco.tolist(), bloco.tolist()))
            elif incluir_tensao:
                linhas = (f"{i},{v},{t:.6f}" for i, v, t in
                          zip(indices, bloco.tolist(), tensao.tolist()))
            else:
                linhas = (f"{i},{v}" for i, v in zip(indices, bloco.tolist()))

            f.write("\n".join(linhas))
            f.write("\n")

    return fim - inicio


def csv_para_bin(caminho_csv: Path, caminho_bin: Path, formato: str,
                  inicio: int, fim: int | None,
                  tamanho_chunk: int = TAMANHO_CHUNK_PADRAO) -> int:
    """Lê o '.csv' em streaming e grava em blocos -- só 'valor_bruto' é
    usada, então nenhuma informação de --canais é necessária aqui (a ORDEM
    das linhas já preserva a intercalação original)."""
    dtype = FORMATOS_NUMPY[formato]
    inicio = max(0, inicio)

    with open(caminho_csv, "r", newline="") as f_in:
        primeira_linha = f_in.readline()
        if not primeira_linha:
            raise SystemExit(f"Erro: '{caminho_csv}' está vazio.")
        cabecalho = primeira_linha.rstrip("\n").split(",")
        if "valor_bruto" not in cabecalho:
            raise SystemExit(f"Erro: '{caminho_csv}' não tem coluna 'valor_bruto'.")
        indice_coluna = cabecalho.index("valor_bruto")
        indice_coluna_canal = cabecalho.index("canal") if "canal" in cabecalho else None

        linhas_dados = itertools.islice(f_in, inicio, fim)

        # Verificação leve (O(1) de memória) de que a coluna 'canal', se
        # presente, segue um padrão cíclico -- alerta cedo para um CSV
        # editado manualmente ou corrompido, sem impedir a conversão.
        padrao_canais: list[str] = []
        periodo_detectado: int | None = None
        posicao_no_padrao = 0
        inconsistencias = 0

        n_convertidas = 0
        with open(caminho_bin, "wb") as f_out:
            bloco = []
            for linha in linhas_dados:
                if not linha.strip():
                    continue
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
                f"Aviso: coluna 'canal' de '{caminho_csv}' não segue um "
                f"padrão cíclico consistente ({inconsistencias} linha(s) "
                f"fora do padrão {padrao_canais}).",
                file=sys.stderr,
            )

        if fim is not None and n_convertidas < (fim - inicio):
            print(
                f"Aviso: --fim pediu {fim} amostra(s), mas '{caminho_csv}' só "
                f"tinha {inicio + n_convertidas} linha(s). Convertida(s) "
                f"{n_convertidas}.",
                file=sys.stderr,
            )

    if n_convertidas == 0:
        raise SystemExit(f"Erro: nenhuma amostra convertida de '{caminho_csv}'.")
    return n_convertidas


def converter_arquivo(caminho_entrada: Path, caminho_saida: Path, formato: str,
                       inicio: int, fim: int | None, incluir_tensao: bool,
                       canais: list[int], faixas: list[float], ganhos: list[float],
                       offsets: list[float], tamanho_chunk: int) -> None:
    """Direção decidida pelas extensões de entrada/saída."""
    tipo_entrada = detectar_tipo_arquivo(caminho_entrada)
    tipo_saida = detectar_tipo_arquivo(caminho_saida)

    if tipo_entrada == tipo_saida:
        raise SystemExit(
            f"Erro: entrada e saída têm o mesmo formato (.{tipo_entrada}) -- "
            f"não há conversão a fazer."
        )

    if incluir_tensao and tipo_entrada != "bin":
        print(
            "Aviso: --incluir-tensao só tem efeito em .bin -> .csv; ignorado.",
            file=sys.stderr,
        )

    if tipo_entrada == "bin" and tipo_saida == "csv":
        n = bin_para_csv(caminho_entrada, caminho_saida, formato, inicio, fim,
                          incluir_tensao, canais, faixas, ganhos, offsets, tamanho_chunk)
        extra = " | coluna tensao_v incluída" if incluir_tensao else ""
        extra_canal = (f" | {len(canais)} canais intercalados {canais} (coluna 'canal')"
                       if len(canais) > 1 else "")
        print(f"Convertido: '{caminho_entrada}' (.bin) -> '{caminho_saida}' (.csv) | "
              f"{n} amostra(s) | --formato {formato}{extra}{extra_canal}")
    else:
        n = csv_para_bin(caminho_entrada, caminho_saida, formato, inicio, fim, tamanho_chunk)
        print(f"Convertido: '{caminho_entrada}' (.csv) -> '{caminho_saida}' (.bin) | "
              f"{n} amostra(s) | --formato {formato}")


# ---------------------------------------------------------------------------
# 5. Fundamental: estimativa, corte em ciclos inteiros, interpolação de pico
# ---------------------------------------------------------------------------

def refinar_pico_parabolico(espectro_db: np.ndarray, indice_pico: int) -> tuple[float, float]:
    """Interpolação parabólica (log-magnitude) ao redor de um pico já
    localizado por argmax -- corrige o erro de quantização do bin
    (scalloping loss) sem precisar de uma FFT maior. Retorna (delta_bins em
    [-0.5, 0.5], amplitude_db estimada no vértice da parábola)."""
    n = len(espectro_db)
    if indice_pico <= 0 or indice_pico >= n - 1:
        return 0.0, float(espectro_db[indice_pico])

    y_menos, y_pico, y_mais = espectro_db[indice_pico - 1:indice_pico + 2]
    denominador = y_menos - 2.0 * y_pico + y_mais
    if denominador == 0:
        return 0.0, float(y_pico)

    delta = float(np.clip(0.5 * (y_menos - y_mais) / denominador, -0.5, 0.5))
    amplitude_vertice = y_pico - 0.25 * (y_menos - y_mais) * delta
    return delta, float(amplitude_vertice)


def estimar_frequencia_fundamental(sinal: np.ndarray, fs: float,
                                    freq_min: float, freq_max: float) -> float:
    """Estimativa grosseira via FFT + Hann fixa (independente de --janela --
    só uma ferramenta de triagem para o corte do passa-baixa que segue; a
    precisão real vem do refinamento por cruzamento de zero). O pico é
    refinado por interpolação parabólica para reduzir o erro de quantização
    do bin sem precisar de uma FFT maior."""
    n = len(sinal)
    if n < 16:
        raise SystemExit("Erro: poucos dados para estimar a frequência fundamental.")

    janela = np.hanning(n)
    espectro_db = 20 * np.log10(np.maximum(np.abs(rfft((sinal - np.mean(sinal)) * janela)), 1e-12))
    freqs = rfftfreq(n, 1.0 / fs)

    banda = (freqs >= freq_min) & (freqs <= freq_max)
    if not np.any(banda):
        raise SystemExit(
            f"Erro: nenhuma componente de frequência entre {freq_min} Hz e "
            f"{freq_max} Hz. Ajuste --freq-min/--freq-max ou -f."
        )

    indices_banda = np.where(banda)[0]
    idx_pico = indices_banda[np.argmax(espectro_db[indices_banda])]
    delta, _ = refinar_pico_parabolico(espectro_db, idx_pico)
    resolucao_bin = freqs[1] - freqs[0]
    return float(freqs[idx_pico] + delta * resolucao_bin)


def detectar_cruzamentos_por_zero(sinal_filtrado: np.ndarray) -> np.ndarray:
    """Cruzamentos ascendentes com posição FRACIONÁRIA (interpolação linear
    entre a amostra negativa e a positiva) -- mais preciso que o índice
    inteiro mais próximo, principalmente em fs baixa relativa à fundamental."""
    indices = np.where((sinal_filtrado[:-1] < 0) & (sinal_filtrado[1:] >= 0))[0]
    if len(indices) == 0:
        return np.array([])

    y0 = sinal_filtrado[indices]
    y1 = sinal_filtrado[indices + 1]
    fracao = -y0 / (y1 - y0)
    return indices + fracao


def refinar_periodo_fundamental(posicoes_cruzamento: np.ndarray, fs: float):
    """periodo = (último - primeiro) / n_ciclos -- dilui o erro de detecção
    de cada cruzamento por todos os ciclos observados, em vez de concentrá-lo
    num único intervalo."""
    n_ciclos_disponiveis = len(posicoes_cruzamento) - 1
    if n_ciclos_disponiveis < 1:
        raise SystemExit(
            "Erro: cruzamentos por zero insuficientes para estimar o período "
            "da fundamental (janela curta demais, ou sinal sem componente "
            "periódica clara nessa faixa)."
        )
    periodo_amostras = (posicoes_cruzamento[-1] - posicoes_cruzamento[0]) / n_ciclos_disponiveis
    return periodo_amostras / fs, n_ciclos_disponiveis


def estimar_amostras_para_n_ciclos(n_ciclos: int, fs: float, freq_min: float,
                                    margem_ciclos: int = 5) -> int:
    """Estima quantas amostras bastam para conter N ciclos completos, usando
    freq_min (período mais longo da faixa de busca) mais uma margem -- evita
    filtrar/varrer uma captura inteira quando --fft N (análise de distúrbios
    momentâneos) só precisa dos primeiros N ciclos."""
    amostras_por_ciclo_pior_caso = fs / freq_min
    return int(np.ceil((n_ciclos + margem_ciclos) * amostras_por_ciclo_pior_caso))


def recortar_ciclos_inteiros(sinal: np.ndarray, fs: float, freq_min: float,
                              freq_max: float, n_ciclos_pedido: int | None):
    """Recorta 'sinal' para um número inteiro de ciclos da fundamental,
    alinhado ao primeiro cruzamento por zero ascendente. Eficaz para a
    fundamental e seus harmônicos (fase travada ao ciclo de rede); NÃO
    elimina vazamento de supraharmônicos, cuja fase é independente do ciclo
    de rede -- para esses, ver calcular_espectro_welch.

    n_ciclos_pedido: None -> todos os ciclos completos da janela; int N ->
    só os N primeiros (análise de distúrbios momentâneos), pré-truncando o
    sinal a uma estimativa generosa de amostras necessárias antes de
    filtrar/buscar cruzamentos, para não processar uma captura inteira só
    para olhar os primeiros milissegundos.

    Retorna (sinal_recortado, idx_inicio, idx_fim, f0_estimada, n_ciclos_usados).
    """
    sinal_analise = sinal
    if n_ciclos_pedido is not None and n_ciclos_pedido > 0:
        limite = estimar_amostras_para_n_ciclos(n_ciclos_pedido, fs, freq_min)
        if limite < len(sinal_analise):
            sinal_analise = sinal_analise[:limite]

    freq_estimada = estimar_frequencia_fundamental(sinal_analise, fs, freq_min, freq_max)

    # Remove nível DC antes de filtrar/detectar cruzamentos: sem isso, um
    # sinal com offset residual poderia nunca cruzar o zero literal.
    sinal_centrado = sinal_analise - np.mean(sinal_analise)

    # Corte do passa-baixa: acima o bastante da fundamental para não
    # atenuá-la, abaixo do 3º harmônico para eliminar ruído/supraharmônicos
    # que atrapalhariam a detecção de cruzamento por zero. SOS em vez de
    # (b, a): fs/f0 é extremo aqui (dezenas de milhares para 1) e a forma
    # polinomial clássica perde precisão numérica nesse regime.
    corte = min(freq_estimada * 2.5, 0.45 * fs)
    sos = butter(4, corte / (fs / 2.0), btype="low", output="sos")
    sinal_filtrado = sosfiltfilt(sos, sinal_centrado)

    posicoes_cruzamento = detectar_cruzamentos_por_zero(sinal_filtrado)
    if len(posicoes_cruzamento) < 2:
        raise SystemExit(
            "Erro: não foi possível encontrar ciclos completos na janela "
            "selecionada. Tente aumentar --inicio/--fim."
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
                f"{n_ciclos_disponiveis} completos estão disponíveis na "
                f"janela processada. Usando {n_ciclos_usados}.",
                file=sys.stderr,
            )

    idx_inicio = int(round(posicoes_cruzamento[0]))
    idx_fim = int(round(posicoes_cruzamento[n_ciclos_usados]))
    return sinal[idx_inicio:idx_fim], idx_inicio, idx_fim, f0, n_ciclos_usados


# ---------------------------------------------------------------------------
# 6. Janelas espectrais
# ---------------------------------------------------------------------------

def _normalizar_nome_janela(nome: str) -> str:
    """Remove acentos, hifens, espaços e underscores, e converte para
    minúsculas -- 'Blackman-Harris', 'blackmanharris' e 'BLACKMAN_HARRIS'
    resolvem todos para a mesma chave."""
    sem_acento = unicodedata.normalize("NFKD", nome)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    chave = sem_acento.strip().lower()
    for caractere in ("-", "_", " "):
        chave = chave.replace(caractere, "")
    return chave


def resolver_nome_janela(nome: str) -> str:
    """Validado antes de carregar qualquer arquivo, para dar erro rápido em
    caso de nome digitado errado."""
    chave = _normalizar_nome_janela(nome)
    if chave not in ALIASES_JANELA:
        raise SystemExit(
            f"Erro: janela '{nome}' não reconhecida em --janela. Aceitos: "
            f"retangular/boxcar, hann/hanning, blackmanharris/blackman-harris, "
            f"flattop/flat-top, kaiser."
        )
    return ALIASES_JANELA[chave]


def obter_janela(nome_canonico: str, n: int, kaiser_beta: float) -> np.ndarray:
    """fftbins=True (variante periódica) -- a recomendada para análise
    espectral por FFT, evita a amostra final redundante da variante
    simétrica (mais apropriada para filtragem no tempo)."""
    if nome_canonico == "kaiser":
        return get_window(("kaiser", kaiser_beta), n, fftbins=True)
    return get_window(nome_canonico, n, fftbins=True)


def _rotulo_janela_completo(nome_canonico: str, kaiser_beta: float) -> str:
    rotulo = NOMES_EXIBICAO_JANELA[nome_canonico]
    if nome_canonico == "kaiser":
        rotulo += f" (beta={kaiser_beta:g})"
    return rotulo


# ---------------------------------------------------------------------------
# 7. Cálculo de espectro: FFT única, Welch, bandas e picos
# ---------------------------------------------------------------------------

def _normalizar_espectro(potencia: np.ndarray, fs: float, tamanho_fft: int,
                          janela: np.ndarray, modo: str) -> np.ndarray:
    """Converte um espectro de potência bruto |X(f)|^2 (de 1 segmento, ou já
    somado/mediado entre vários) para dB, em uma de duas convenções:

    'tom': amplitude linear corrigida pelo ganho coerente da janela (média de
        seus valores) -- sem essa correção a amplitude fica sistematicamente
        abaixo da real, porque a janela atenua energia do sinal antes da FFT.
        Correta para um tom discreto (fundamental, harmônico), cuja energia
        cai essencialmente num único bin.
    'ruido': densidade espectral de potência (PSD, V²/Hz), normalizada pelo
        ganho INCOERENTE da janela (soma de seus valores ao quadrado) --
        correta para conteúdo de banda larga, onde 'tom' daria uma leitura
        que muda artificialmente com o tamanho da FFT/segmento, mesmo para o
        MESMO ruído físico.
    """
    if modo == "tom":
        ganho_coerente = np.mean(janela)
        amplitude_linear = (2.0 / (tamanho_fft * ganho_coerente)) * np.sqrt(potencia)
        amplitude_linear[0] /= 2.0
        return 20 * np.log10(np.maximum(amplitude_linear, 1e-12))

    soma_quadrados_janela = np.sum(janela ** 2)
    psd = potencia / (fs * soma_quadrados_janela)
    psd[1:-1] *= 2.0
    return 10 * np.log10(np.maximum(psd, 1e-20))


def calcular_espectro(sinal: np.ndarray, fs: float, nome_janela: str,
                       kaiser_beta: float, modo: str = "tom"):
    """FFT de um único segmento -- ver calcular_espectro_welch para o
    caminho com múltiplos segmentos médios. 'modo' escolhe a normalização
    (ver _normalizar_espectro)."""
    n = len(sinal)
    janela = obter_janela(nome_janela, n, kaiser_beta)
    sinal_janelado = (sinal - np.mean(sinal)) * janela
    espectro = rfft(sinal_janelado)
    freqs = rfftfreq(n, 1.0 / fs)
    potencia = np.abs(espectro) ** 2
    amplitude_db = _normalizar_espectro(potencia, fs, n, janela, modo)
    return freqs, amplitude_db


def calcular_espectro_welch(sinal: np.ndarray, fs: float, nome_janela: str,
                             kaiser_beta: float, resolucao_hz: float,
                             sobreposicao: float, modo: str = "ruido"):
    """Espectro médio por segmentação (Welch): reduz a variância da
    estimativa por segmentação + média de periodogramas, ao custo de
    resolução fixa em frequência (fs/resolucao_hz, não o comprimento total
    do sinal).

    Ao contrário do corte em ciclos inteiros (recortar_ciclos_inteiros), não
    tenta eliminar vazamento por sincronismo de ciclo -- ruído de conversores
    chaveados (supraharmônicos) não tem relação de fase com o ciclo da rede,
    então não existe corte "certo" para essa finalidade. Aqui o controle de
    vazamento é a janela espectral e a média entre segmentos, que também
    suaviza deriva de frequência de chaveamento (dithering) ao longo da
    captura.

    Processado em lotes (numpy.lib.stride_tricks.sliding_window_view) em vez
    de 1 segmento por vez em Python puro ou de todos de uma vez -- equilibra
    desempenho (FFT vetorizada por lote) e memória (uma captura longa com
    50% de sobreposição pode gerar centenas de milhares de segmentos).
    """
    tamanho_segmento = max(16, int(round(fs / resolucao_hz)))
    passo = max(1, int(round(tamanho_segmento * (1.0 - sobreposicao))))
    n = len(sinal)

    if n < tamanho_segmento:
        raise SystemExit(
            f"Erro: sinal com {n} amostras insuficiente para 1 segmento de "
            f"Welch de {tamanho_segmento} amostras (--resolucao-welch "
            f"{resolucao_hz:g} Hz). Aumente a janela de captura ou "
            f"--resolucao-welch."
        )

    n_segmentos = (n - tamanho_segmento) // passo + 1
    janela = obter_janela(nome_janela, tamanho_segmento, kaiser_beta)
    freqs = rfftfreq(tamanho_segmento, 1.0 / fs)
    acumulador = np.zeros(len(freqs))
    janela_deslizante = np.lib.stride_tricks.sliding_window_view(sinal, tamanho_segmento)

    for inicio_lote in range(0, n_segmentos, TAMANHO_LOTE_WELCH_PADRAO):
        indices_lote = np.arange(inicio_lote, min(inicio_lote + TAMANHO_LOTE_WELCH_PADRAO, n_segmentos))
        lote = janela_deslizante[indices_lote * passo]
        lote_janelado = (lote - lote.mean(axis=1, keepdims=True)) * janela
        espectros = rfft(lote_janelado, axis=1)
        acumulador += np.sum(np.abs(espectros) ** 2, axis=0)

    potencia_media = acumulador / n_segmentos
    amplitude_db = _normalizar_espectro(potencia_media, fs, tamanho_segmento, janela, modo)
    return freqs, amplitude_db, n_segmentos


def agrupar_em_bandas(freqs: np.ndarray, amplitude_db: np.ndarray,
                       largura_hz: float, modo: str):
    """Resume um espectro fino em bandas de largura fixa (ex.: 200 Hz --
    convenção da literatura de supraharmônicos para tornar o resultado
    comparável entre capturas com resoluções em frequência diferentes, ao
    contrário do valor bin a bin, que muda de significado só porque o
    tamanho da FFT/segmento mudou).

    Cada banda reporta o nível RMS de tensão contido nela, em dBV: para
    'tom' (bins em amplitude linear) é a soma das POTÊNCIAS dos bins; para
    'ruido' (bins em densidade espectral de potência) é a integral da PSD
    sobre a banda. As duas convergem para a mesma grandeza física (energia
    contida na banda), o que torna o resultado comparável entre os modos.
    """
    largura_bin = freqs[1] - freqs[0]
    bordas = np.arange(freqs[0], freqs[-1], largura_hz)
    if len(bordas) == 0:
        bordas = np.array([freqs[0]])

    if modo == "tom":
        potencia_linear = 10 ** (amplitude_db / 10.0)          # |V|^2 por bin
    else:
        potencia_linear = (10 ** (amplitude_db / 10.0)) * largura_bin  # PSD * Hz = V^2 por bin

    centros, valores_db = [], []
    for inicio_banda in bordas:
        mascara = (freqs >= inicio_banda) & (freqs < inicio_banda + largura_hz)
        if not np.any(mascara):
            continue
        energia = np.sum(potencia_linear[mascara])
        centros.append(inicio_banda + largura_hz / 2.0)
        valores_db.append(10 * np.log10(max(energia, 1e-24)))

    return np.array(centros), np.array(valores_db)


def encontrar_picos_espectro(freqs: np.ndarray, amplitude_db: np.ndarray,
                              freq_min: float, freq_max: float, limiar_db: float,
                              distancia_minima_hz: float) -> list[dict]:
    """Localiza picos locais dentro de [freq_min, freq_max] acima de
    'limiar_db' (scipy.signal.find_peaks) e refina cada um por interpolação
    parabólica (refinar_pico_parabolico) -- entrega frequência e amplitude de
    cada componente supraharmônica individual sem depender de aumentar N
    para "acertar" o bin exato."""
    mascara = (freqs >= freq_min) & (freqs <= freq_max)
    indices_banda = np.where(mascara)[0]
    if len(indices_banda) < 3:
        return []

    largura_bin = freqs[1] - freqs[0]
    distancia_bins = max(1, int(round(distancia_minima_hz / largura_bin)))

    sub_espectro = amplitude_db[indices_banda]
    indices_locais, _ = find_peaks(sub_espectro, height=limiar_db, distance=distancia_bins)

    picos = []
    for i_local in indices_locais:
        idx_global = indices_banda[i_local]
        delta, amplitude_vertice = refinar_pico_parabolico(amplitude_db, idx_global)
        freq_refinada = freqs[idx_global] + delta * largura_bin
        picos.append({"frequencia_hz": float(freq_refinada), "amplitude_db": float(amplitude_vertice)})
    return picos


# ---------------------------------------------------------------------------
# 8. Plotagem
# ---------------------------------------------------------------------------

def escolher_unidade_tempo(duracao_s: float):
    if duracao_s < 2.0:
        return 1000.0, "Tempo (ms)"
    return 1.0, "Tempo (s)"


def plotar_multicanal(tensoes_por_canal: dict[int, np.ndarray], fs_efetiva: float,
                       idx_inicio_arquivo: int, infos_espectro: dict | None,
                       titulo_arquivo: str, caminho_saida: Path | None,
                       layout: str, rotulo_espectro_y: str,
                       limite_inferior_db: float | None) -> None:
    """Plota forma de onda e, se disponível, espectro(s) de 1+ canais. Um
    canal pode ter até 2 espectros simultâneos (--fft e --welch, chaves
    "ciclo"/"welch" em infos_espectro[canal]) -- plotados como curvas
    distintas no mesmo eixo, já que respondem perguntas diferentes
    (fundamental/harmônicos vs. conteúdo de banda larga não estacionário)."""
    canais = list(tensoes_por_canal.keys())
    n_canais = len(canais)
    tem_espectro = infos_espectro is not None

    n = len(tensoes_por_canal[canais[0]])
    fator_tempo, rotulo_tempo = escolher_unidade_tempo(n / fs_efetiva)
    tempo = (np.arange(n) / fs_efetiva) * fator_tempo

    cores = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    usar_eixo_unico = (n_canais == 1) or (layout == "sobrepostos")
    estilo_metodo = {"ciclo": "-", "welch": "--"}

    if usar_eixo_unico:
        if tem_espectro:
            fig, (ax_tempo, ax_espectro) = plt.subplots(2, 1, figsize=(10, 8))
        else:
            fig, ax_tempo = plt.subplots(figsize=(10, 5))
            ax_espectro = None

        for i, canal in enumerate(canais):
            cor_tempo = "tab:green" if n_canais == 1 else cores[i % len(cores)]
            rotulo = None if n_canais == 1 else f"Canal {canal}"
            ax_tempo.plot(tempo, tensoes_por_canal[canal], color=cor_tempo, linewidth=1.0, label=rotulo)

        titulo_base = f"Forma de onda -- amostras {idx_inicio_arquivo}..{idx_inicio_arquivo + n} de '{titulo_arquivo}'"
        ax_tempo.set_title(titulo_base if n_canais == 1 else f"{titulo_base} (canais {canais}, sobrepostos)")
        ax_tempo.set_xlabel(rotulo_tempo)
        ax_tempo.set_ylabel("Tensão (V)")
        ax_tempo.grid(True, alpha=0.4)

        if tem_espectro:
            houve_sombra = False
            for i, canal in enumerate(canais):
                info_ciclo = infos_espectro[canal].get("ciclo")
                if info_ciclo is None:
                    continue
                cor_sombra = "tab:orange" if n_canais == 1 else cores[i % len(cores)]
                ini_janela = info_ciclo["idx_inicio_local"] / fs_efetiva * fator_tempo
                fim_janela = info_ciclo["idx_fim_local"] / fs_efetiva * fator_tempo
                rotulo_sombra = (
                    f"Janela do ciclo ({info_ciclo['n_ciclos']} ciclo(s))" if n_canais == 1
                    else f"Janela ciclo canal {canal}"
                )
                ax_tempo.axvspan(ini_janela, fim_janela, color=cor_sombra, alpha=0.20, label=rotulo_sombra)
                houve_sombra = True
            if houve_sombra:
                ax_tempo.legend(loc="upper right", fontsize=9 if n_canais == 1 else 8)

            for i, canal in enumerate(canais):
                metodos_canal = infos_espectro[canal]
                for metodo, info in metodos_canal.items():
                    cor_linha = "tab:blue" if n_canais == 1 else cores[i % len(cores)]
                    if n_canais == 1:
                        rotulo_linha = metodo if len(metodos_canal) > 1 else None
                    else:
                        rotulo_linha = f"Canal {canal} ({metodo})"
                    ax_espectro.plot(info["freqs"], info["amplitude_db"], color=cor_linha, linewidth=1.2,
                                      linestyle=estilo_metodo[metodo], label=rotulo_linha)

            metodos_canal0 = infos_espectro[canais[0]]
            if n_canais == 1 and len(metodos_canal0) == 1:
                metodo_unico, info_unico = next(iter(metodos_canal0.items()))
                if metodo_unico == "ciclo":
                    ax_espectro.set_title(
                        f"Espectro (ciclo) -- f0 = {info_unico['f0']:.3f} Hz | "
                        f"{info_unico['n_ciclos']} ciclo(s) | janela: {info_unico['janela']}"
                    )
                else:
                    ax_espectro.set_title(
                        f"Espectro (Welch) -- {info_unico['n_segmentos']} segmento(s) médios | "
                        f"janela: {info_unico['janela']}"
                    )
            else:
                ax_espectro.set_title(f"Espectro -- canais {canais}")
                ax_espectro.legend(loc="upper right", fontsize=8)

            ax_espectro.set_xlabel("Frequência (Hz)")
            ax_espectro.set_ylabel(rotulo_espectro_y)
            ax_espectro.grid(True, which="both", ls="-", alpha=0.4)
            ax_espectro.set_xlim(0, (fs_efetiva / 2.0) * 1.10)
            if limite_inferior_db is not None:
                ax_espectro.set_ylim(bottom=limite_inferior_db)

        plt.tight_layout()

    else:
        n_colunas = 2 if tem_espectro else 1
        fig, eixos = plt.subplots(n_canais, n_colunas, figsize=(6.5 * n_colunas, 3.2 * n_canais), squeeze=False)

        for i, canal in enumerate(canais):
            cor = cores[i % len(cores)]
            ax_tempo = eixos[i, 0]
            ax_tempo.plot(tempo, tensoes_por_canal[canal], color=cor, linewidth=1.0)
            ax_tempo.set_title(f"Canal {canal} -- amostras {idx_inicio_arquivo}..{idx_inicio_arquivo + n}")
            ax_tempo.set_xlabel(rotulo_tempo)
            ax_tempo.set_ylabel("Tensão (V)")
            ax_tempo.grid(True, alpha=0.4)

            if tem_espectro:
                metodos_canal = infos_espectro[canal]
                ax_espectro = eixos[i, 1]

                info_ciclo = metodos_canal.get("ciclo")
                if info_ciclo is not None:
                    ini_janela = info_ciclo["idx_inicio_local"] / fs_efetiva * fator_tempo
                    fim_janela = info_ciclo["idx_fim_local"] / fs_efetiva * fator_tempo
                    ax_tempo.axvspan(ini_janela, fim_janela, color=cor, alpha=0.20,
                                      label=f"Janela do ciclo ({info_ciclo['n_ciclos']} ciclo(s))")
                    ax_tempo.legend(loc="upper right", fontsize=8)

                for metodo, info in metodos_canal.items():
                    ax_espectro.plot(info["freqs"], info["amplitude_db"], color=cor, linewidth=1.2,
                                      linestyle=estilo_metodo[metodo],
                                      label=metodo if len(metodos_canal) > 1 else None)
                if len(metodos_canal) > 1:
                    ax_espectro.legend(loc="upper right", fontsize=8)

                titulo_espectro = f"Canal {canal}"
                if info_ciclo is not None:
                    titulo_espectro += f" -- f0 = {info_ciclo['f0']:.3f} Hz | {info_ciclo['n_ciclos']} ciclo(s)"
                ax_espectro.set_title(titulo_espectro)
                ax_espectro.set_xlabel("Frequência (Hz)")
                ax_espectro.set_ylabel(rotulo_espectro_y)
                ax_espectro.grid(True, which="both", ls="-", alpha=0.4)
                ax_espectro.set_xlim(0, (fs_efetiva / 2.0) * 1.10)
                if limite_inferior_db is not None:
                    ax_espectro.set_ylim(bottom=limite_inferior_db)

        fig.suptitle(f"'{titulo_arquivo}' -- canais {canais} (separados)")
        plt.tight_layout(rect=[0, 0, 1, 0.97])

    if caminho_saida is not None:
        fig.savefig(caminho_saida, dpi=150)
        print(f"Gráfico salvo em '{caminho_saida}'.")
    else:
        plt.show()


def _imprimir_picos(canal: int, metodo: str, picos: list[dict], num_canais: int) -> None:
    prefixo = f"  Canal {canal} " if num_canais > 1 else "  "
    if not picos:
        print(f"{prefixo}[{metodo}] nenhum pico acima do limiar encontrado.")
        return
    for pico in picos:
        print(f"{prefixo}[{metodo}] pico: {pico['frequencia_hz']:.2f} Hz @ {pico['amplitude_db']:.2f} dB")


# ---------------------------------------------------------------------------
# 9. Linha de comando
# ---------------------------------------------------------------------------

def montar_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="adc_tool.py",
        description=(
            "Ferramenta de linha de comando do SH-Analyzer para dados brutos "
            "do ADS8688. Dois modos: (1) CONVERSÃO (-c/--converter + "
            "-o/--saida), '.bin' <-> '.csv'; (2) PLOTAGEM (padrão), forma de "
            "onda e, opcionalmente, espectro via --fft (ciclo-sincronizado, "
            "ideal para fundamental/harmônicos) e/ou --welch (segmentado e "
            "médio, ideal para supraharmônicos). Suporta 1 ou vários canais "
            "intercalados (grupo 'Captura multi-canal')."
        ),
        epilog=(
            "Exemplos:\n"
            "  # Plotar com FFT ciclo-sincronizada (fundamental/harmônicos)\n"
            "  %(prog)s captura.bin -f 102400 --fft\n"
            "\n"
            "  # Espectro médio (Welch) para conteúdo de banda larga\n"
            "  %(prog)s captura.bin -f 102400 --welch --modo-espectro ruido "
            "--filtro-passa-alta 2000\n"
            "\n"
            "  # Agrupar em bandas de 200 Hz e reportar picos acima de -60 dB\n"
            "  %(prog)s captura.bin -f 102400 --welch --agrupar-bandas 200 "
            "--picos -60\n"
            "\n"
            "  # FFT de alta resolução temporal (só 10 ciclos, distúrbio)\n"
            "  %(prog)s captura.bin -f 102400 --inicio 50000 --fft 10\n"
            "\n"
            "  # Converter .bin -> .csv\n"
            "  %(prog)s -c captura.bin -o captura.csv\n"
            "\n"
            "  # Multi-canal: 3 canais, ganho por canal, FFT independente\n"
            "  %(prog)s captura.bin -f 102400 --canais 0,1,3 --ganho "
            "19.53,0.1,1.0 --fft\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "arquivo", type=Path, nargs="?", default=None,
        help="[PLOTAGEM] Caminho do arquivo a plotar ('.bin' via memory-map "
             "ou '.csv' com coluna 'valor_bruto'). Obrigatório nesse modo; "
             "não usado com -c/--converter."
    )
    parser.add_argument(
        "-f", "--frequencia", type=float, default=None, metavar="HZ",
        help="[PLOTAGEM] Frequência de amostragem TOTAL da captura, em Hz. "
             "Com N canais em --canais, a frequência EFETIVA por canal é "
             "esse valor / N. Obrigatório nesse modo."
    )

    grupo_multicanal = parser.add_argument_group(
        "Captura multi-canal",
        "Uma captura com mais de 1 canal grava as amostras intercaladas "
        "(round-robin) num único arquivo -- estas flags dizem como "
        "desintercalar. Válidas na plotagem e na conversão '.bin'->'.csv'.",
    )
    grupo_multicanal.add_argument(
        "--canais", type=str, default=CANAL_PADRAO, metavar="LISTA",
        help="Canais no arquivo, separados por vírgula, na ordem impressa "
             "por `ler_adc` durante a captura (ex.: '0,1,3'). Padrão: '1'."
    )
    grupo_multicanal.add_argument(
        "--canais-exibir", type=str, default=None, metavar="LISTA",
        help="Subconjunto de --canais a efetivamente plotar/analisar "
             "(padrão: todos)."
    )
    grupo_multicanal.add_argument(
        "--layout-canais", choices=["separados", "sobrepostos"], default="separados",
        help="[PLOTAGEM, >1 canal] 'separados' (padrão): 1 subplot por "
             "canal. 'sobrepostos': todos no mesmo eixo, com legenda."
    )

    grupo_conversao = parser.add_argument_group(
        "Modo de conversão (.bin <-> .csv)",
        "Ativado por -c/--converter; nesse modo 'arquivo' e -f são "
        "ignorados. Direção detectada pelas extensões de -c e -o.",
    )
    grupo_conversao.add_argument(
        "-c", "--converter", type=Path, default=None, metavar="ARQUIVO_ENTRADA",
        help="Ativa o modo de conversão: converte ARQUIVO_ENTRADA para "
             "-o/--saida (obrigatório junto com esta flag)."
    )
    grupo_conversao.add_argument(
        "--incluir-tensao", action="store_true",
        help="Só em '.bin'->'.csv': acrescenta a coluna 'tensao_v' (só "
             "informativa -- ignorada na reconstrução de volta para '.bin')."
    )
    grupo_conversao.add_argument(
        "--tamanho-chunk", type=int, default=TAMANHO_CHUNK_PADRAO, metavar="N",
        help=f"Amostras por bloco na conversão (padrão: {TAMANHO_CHUNK_PADRAO})."
    )

    grupo_filtro = parser.add_argument_group(
        "Filtragem digital (Butterworth, fase zero)",
        "[PLOTAGEM] Aplicado a cada canal, em Volts, ANTES do recorte em "
        "ciclos inteiros, de --fft/--welch e da plotagem no tempo.",
    )
    grupo_filtro.add_argument(
        "--filtro-passa-baixa", type=float, default=None, metavar="HZ",
        help="Corte (Hz) de um passa-baixa Butterworth de fase zero. "
             "Precisa ser menor que a Nyquist efetiva do canal. Pode ser "
             "combinado com --filtro-passa-alta (passa-alta primeiro)."
    )
    grupo_filtro.add_argument(
        "--filtro-passa-alta", type=float, default=None, metavar="HZ",
        help="Corte (Hz) de um passa-alta Butterworth de fase zero -- útil "
             "para remover deriva de DC/nível, ou o resíduo da fundamental "
             "antes de --welch/--picos na faixa de supraharmônicos."
    )
    grupo_filtro.add_argument(
        "--ordem-filtro", type=int, default=ORDEM_FILTRO_PADRAO,
        choices=range(ORDEM_FILTRO_MINIMA, ORDEM_FILTRO_MAXIMA + 1),
        metavar=f"[{ORDEM_FILTRO_MINIMA}-{ORDEM_FILTRO_MAXIMA}]",
        help=f"Ordem do(s) filtro(s) acima (padrão: {ORDEM_FILTRO_PADRAO}). "
             f"Implementado em SOS para permanecer estável nas ordens mais altas."
    )

    parser.add_argument(
        "-o", "--saida", "--salvar", dest="saida", type=Path, default=None, metavar="ARQUIVO",
        help="[CONVERSÃO] arquivo de saída ('.csv' ou '.bin', obrigatório "
             "com -c). [PLOTAGEM] caminho de imagem para salvar o gráfico "
             "em vez de abrir a janela interativa (opcional)."
    )
    parser.add_argument(
        "--inicio", type=int, default=0, metavar="N",
        help="Primeira amostra a usar, 0-based (padrão: 0)."
    )
    parser.add_argument(
        "--fim", type=int, default=None, metavar="N",
        help="Última amostra (exclusive) a usar (padrão: até o fim do arquivo)."
    )
    parser.add_argument(
        "--fft", nargs="?", type=int, const=0, default=None, metavar="N_CICLOS",
        help="[PLOTAGEM] Espectro por FFT única, sincronizada em ciclos "
             "inteiros da fundamental -- ideal para a fundamental e "
             "harmônicos de baixa ordem. Sem número: todos os ciclos "
             "completos da janela. Com N: só os N primeiros (distúrbios "
             "momentâneos). Pode ser combinado com --welch."
    )
    parser.add_argument(
        "--freq-min", type=float, default=45.0, metavar="HZ",
        help="[--fft] Limite inferior de busca da fundamental (padrão: 45)."
    )
    parser.add_argument(
        "--freq-max", type=float, default=65.0, metavar="HZ",
        help="[--fft] Limite superior de busca da fundamental (padrão: 65)."
    )
    parser.add_argument(
        "--janela", type=str, default=JANELA_PADRAO, metavar="NOME",
        help="[--fft/--welch] Janela espectral: 'retangular'/'boxcar' "
             "(padrão -- sem atenuação, mas mais sensível a vazamento fora "
             "do corte em ciclos inteiros), 'hann'/'hanning', "
             "'blackmanharris'/'blackman-harris' (lóbulos laterais muito "
             "baixos, útil para separar um supraharmônico fraco perto de "
             "uma fundamental forte), 'flattop'/'flat-top' (melhor exatidão "
             "de amplitude, pior resolução), 'kaiser' (+ --kaiser-beta)."
    )
    parser.add_argument(
        "--kaiser-beta", type=float, default=8.6, metavar="BETA",
        help="[--janela kaiser] beta≈5 ~ Hamming, beta≈6 ~ Hann, beta≈8.6 ~ "
             "Blackman (padrão), beta≈14: lóbulos laterais muitíssimo baixos."
    )

    grupo_espectro = parser.add_argument_group(
        "Análise espectral avançada (Welch, bandas, picos)",
        "Complementa --fft (sincronizado no ciclo da fundamental) com um "
        "caminho pensado para supraharmônicos: ruído de conversores "
        "chaveados não tem relação de fase com o ciclo da rede, então --fft "
        "não elimina o vazamento desse conteúdo por corte de ciclo -- "
        "--welch ataca o problema por segmentação + média (Welch), em vez "
        "de sincronismo de ciclo.",
    )
    grupo_espectro.add_argument(
        "--welch", action="store_true",
        help="[PLOTAGEM] Espectro médio por segmentação: o sinal é dividido "
             "em blocos de --resolucao-welch Hz de resolução, cada um "
             "janelado e transformado, e os periodogramas resultantes são "
             "MEDIADOS -- reduz variância e é robusto a ruído de banda "
             "larga e deriva de frequência de chaveamento (dithering), ao "
             "custo de resolução fixa em frequência. Pode ser combinado com "
             "--fft (cada um plota sua própria curva)."
    )
    grupo_espectro.add_argument(
        "--resolucao-welch", type=float, default=RESOLUCAO_WELCH_PADRAO, metavar="HZ",
        help=f"[--welch] Resolução de cada segmento em Hz -- define o "
             f"tamanho do segmento como fs_efetiva/HZ amostras (padrão: "
             f"{RESOLUCAO_WELCH_PADRAO:g}). Menor = mais segmentos médios "
             f"(menos variância), resolução mais grossa."
    )
    grupo_espectro.add_argument(
        "--sobreposicao-welch", type=float, default=SOBREPOSICAO_WELCH_PADRAO, metavar="FRACAO",
        help=f"[--welch] Fração de sobreposição entre segmentos, em [0, 1) "
             f"(padrão: {SOBREPOSICAO_WELCH_PADRAO:g})."
    )
    grupo_espectro.add_argument(
        "--modo-espectro", choices=["tom", "ruido"], default="tom",
        help="Normalização usada por --fft e --welch: 'tom' (padrão) "
             "reporta amplitude corrigida pelo ganho coerente da janela -- "
             "correta para um tom discreto. 'ruido' reporta densidade "
             "espectral de potência (PSD, V²/Hz), normalizada pelo ganho "
             "incoerente/ENBW -- correta para conteúdo de banda larga, onde "
             "'tom' mudaria artificialmente com o tamanho da FFT/segmento "
             "para o mesmo ruído físico."
    )
    grupo_espectro.add_argument(
        "--agrupar-bandas", type=float, default=None, metavar="HZ",
        help="Agrupa o(s) espectro(s) em bandas de largura HZ (ex.: 200), "
             "reportando o nível RMS de cada banda em vez do valor bin a "
             "bin -- convenção da literatura de supraharmônicos, torna o "
             "resultado comparável entre capturas com resoluções "
             "diferentes. Sem esta flag, mostra o espectro fino. Requer "
             "--fft e/ou --welch."
    )
    grupo_espectro.add_argument(
        "--picos", type=float, default=None, metavar="LIMIAR_DB",
        help="Reporta no console os picos espectrais (frequência e "
             "amplitude, refinados por interpolação parabólica) acima de "
             "LIMIAR_DB dentro de [--freq-min-picos, --freq-max-picos] -- "
             "extração quantitativa de componentes supraharmônicas "
             "individuais. Requer --fft e/ou --welch; usa o espectro FINO "
             "(antes de --agrupar-bandas)."
    )
    grupo_espectro.add_argument(
        "--freq-min-picos", type=float, default=CORTE_SUPRAHARMONICOS_PADRAO, metavar="HZ",
        help=f"[--picos] Limite inferior da busca (padrão: "
             f"{CORTE_SUPRAHARMONICOS_PADRAO:g} Hz -- início convencional "
             f"da faixa de supraharmônicos, IEC 61000-4-7). Independente de "
             f"--freq-min/--freq-max, que buscam a fundamental."
    )
    grupo_espectro.add_argument(
        "--freq-max-picos", type=float, default=None, metavar="HZ",
        help="[--picos] Limite superior da busca (padrão: Nyquist efetiva)."
    )
    grupo_espectro.add_argument(
        "--distancia-minima-picos", type=float, default=DISTANCIA_MINIMA_PICOS_PADRAO, metavar="HZ",
        help=f"[--picos] Distância mínima entre dois picos reportados, para "
             f"não contar o mesmo lóbulo várias vezes (padrão: "
             f"{DISTANCIA_MINIMA_PICOS_PADRAO:g} Hz)."
    )

    parser.add_argument(
        "--formato", choices=["int16", "uint16"], default="uint16",
        help="Como interpretar o código de 16 bits do ADC: 'uint16' "
             "(unipolar 0..+faixa, padrão) ou 'int16' (bipolar -faixa..+faixa)."
    )
    parser.add_argument(
        "--faixa", type=str, default="10.24", metavar="VOLTS",
        help="Faixa de fundo de escala do ADC em Volts (padrão: 10.24). "
             "Um valor único (todos os canais) ou lista por canal, na "
             "ordem de --canais."
    )
    parser.add_argument(
        "--ganho", type=str, default="1.0", metavar="FATOR",
        help="Ganho do sensor/PCB (padrão: 1.0). Um valor ou lista por canal."
    )
    parser.add_argument(
        "--offset", type=str, default=None, metavar="VOLTS",
        help="Deslocamento DC subtraído antes do ganho (padrão automático: "
             "faixa/2 para uint16, 0.0 para int16, por canal). Um valor ou "
             "lista por canal."
    )

    return parser


def main(argv=None):
    parser = montar_parser()
    args = parser.parse_args(argv)

    canais = analisar_lista_canais(args.canais, "--canais")
    if args.canais_exibir is not None:
        canais_exibir = analisar_lista_canais(args.canais_exibir, "--canais-exibir")
        validar_subconjunto_canais(canais_exibir, canais)
    else:
        canais_exibir = canais

    faixas = analisar_lista_calibracao(args.faixa, len(canais), "--faixa")
    ganhos = analisar_lista_calibracao(args.ganho, len(canais), "--ganho")
    offsets = resolver_offsets_por_canal(args.offset, faixas, args.formato, len(canais))

    # -------------------------------------------------------------- #
    # Modo de conversão
    # -------------------------------------------------------------- #
    if args.converter is not None:
        if args.arquivo is not None:
            parser.error(
                "não use o argumento posicional 'arquivo' junto com "
                "-c/--converter; passe entrada em -c e saída em -o."
            )
        if args.saida is None:
            parser.error("-o/--saida é obrigatório junto com -c/--converter.")
        converter_arquivo(
            args.converter, args.saida, args.formato, args.inicio, args.fim,
            args.incluir_tensao, canais, faixas, ganhos, offsets, args.tamanho_chunk,
        )
        return

    # -------------------------------------------------------------- #
    # Modo de plotagem
    # -------------------------------------------------------------- #
    if args.arquivo is None:
        parser.error("o argumento 'arquivo' é obrigatório no modo de plotagem.")
    if args.frequencia is None:
        parser.error("-f/--frequencia é obrigatório no modo de plotagem.")

    num_canais = len(canais)
    fs_efetiva = args.frequencia / num_canais
    usa_fft = args.fft is not None
    usa_welch = args.welch

    # Validação de argumentos ANTES de tocar o arquivo (que pode ser
    # grande) -- mesma filosofia para --janela, filtros e Welch abaixo.
    nome_janela_canonico = resolver_nome_janela(args.janela) if (usa_fft or usa_welch) else None
    rotulo_janela = _rotulo_janela_completo(nome_janela_canonico, args.kaiser_beta) if nome_janela_canonico else None

    if args.filtro_passa_baixa is not None:
        validar_corte_filtro(args.filtro_passa_baixa, fs_efetiva, "--filtro-passa-baixa")
    if args.filtro_passa_alta is not None:
        validar_corte_filtro(args.filtro_passa_alta, fs_efetiva, "--filtro-passa-alta")
    if (args.filtro_passa_alta is not None and args.filtro_passa_baixa is not None
            and args.filtro_passa_alta >= args.filtro_passa_baixa):
        raise SystemExit(
            f"Erro: --filtro-passa-alta ({args.filtro_passa_alta:g} Hz) "
            f"precisa ser menor que --filtro-passa-baixa "
            f"({args.filtro_passa_baixa:g} Hz)."
        )

    if not (usa_fft or usa_welch):
        if args.picos is not None:
            parser.error("--picos requer --fft e/ou --welch ativos.")
        if args.agrupar_bandas is not None:
            parser.error("--agrupar-bandas requer --fft e/ou --welch ativos.")

    if args.agrupar_bandas is not None and args.agrupar_bandas <= 0:
        parser.error("--agrupar-bandas precisa ser positivo.")

    if usa_welch:
        if args.resolucao_welch <= 0:
            parser.error("--resolucao-welch precisa ser positiva.")
        if not (0.0 <= args.sobreposicao_welch < 1.0):
            parser.error("--sobreposicao-welch precisa estar em [0, 1).")
        if fs_efetiva / args.resolucao_welch < 16:
            raise SystemExit(
                f"Erro: --resolucao-welch {args.resolucao_welch:g} Hz produz "
                f"um segmento menor que 16 amostras na frequência efetiva "
                f"{fs_efetiva:g} Hz. Reduza --resolucao-welch."
            )

    freq_max_picos = None
    if args.picos is not None:
        freq_max_picos = args.freq_max_picos if args.freq_max_picos is not None else fs_efetiva / 2.0
        if args.freq_min_picos >= freq_max_picos:
            raise SystemExit("Erro: --freq-min-picos precisa ser menor que --freq-max-picos.")

    if (usa_welch or args.picos is not None) and args.filtro_passa_alta is None:
        print(
            "Aviso: --welch/--picos sem --filtro-passa-alta -- resíduo da "
            "fundamental e de harmônicos de baixa ordem pode mascarar "
            "supraharmônicos fracos. Considere, por exemplo, "
            "'--filtro-passa-alta 2000'.",
            file=sys.stderr,
        )
    if usa_fft and args.filtro_passa_alta is not None and args.filtro_passa_alta >= args.freq_min:
        print(
            f"Aviso: --fft precisa da fundamental (banda {args.freq_min:g}-"
            f"{args.freq_max:g} Hz) para sincronizar o corte em ciclos "
            f"inteiros, mas --filtro-passa-alta {args.filtro_passa_alta:g} Hz "
            f"remove essa banda ANTES do corte -- f0/o corte resultantes "
            f"provavelmente ficam inválidos. Para isolar supraharmônicos com "
            f"--welch/--picos sem quebrar --fft, rode os dois em comandos "
            f"separados em vez de na mesma chamada.",
            file=sys.stderr,
        )

    tipo_arquivo = detectar_tipo_arquivo(args.arquivo)
    amostras = carregar_amostras(args.arquivo, args.formato)
    bruto, idx_inicio, idx_fim, total = selecionar_intervalo(amostras, args.inicio, args.fim)

    por_canal_bruto = desintercalar(bruto, canais, canais_exibir)
    indice_no_ciclo = {c: i for i, c in enumerate(canais)}

    por_canal_tensao: dict[int, np.ndarray] = {}
    for canal in canais_exibir:
        idx = indice_no_ciclo[canal]
        por_canal_tensao[canal] = converter_para_tensao(
            por_canal_bruto[canal], faixas[idx], ganhos[idx], args.formato, offsets[idx]
        )

    if args.filtro_passa_alta is not None or args.filtro_passa_baixa is not None:
        for canal in canais_exibir:
            sinal = por_canal_tensao[canal]
            if args.filtro_passa_alta is not None:
                sinal = aplicar_filtro_digital(sinal, fs_efetiva, "high", args.filtro_passa_alta, args.ordem_filtro)
            if args.filtro_passa_baixa is not None:
                sinal = aplicar_filtro_digital(sinal, fs_efetiva, "low", args.filtro_passa_baixa, args.ordem_filtro)
            por_canal_tensao[canal] = sinal

    n_por_canal = len(next(iter(por_canal_tensao.values())))

    print(f"Arquivo: {args.arquivo}  ({total} amostras no total, formato: .{tipo_arquivo})")

    if num_canais == 1:
        idx0 = indice_no_ciclo[canais_exibir[0]]
        print(f"Conversão: --formato {args.formato} | --faixa {faixas[idx0]} V | "
              f"--offset {offsets[idx0]} V | --ganho {ganhos[idx0]}")
        print(f"Janela selecionada: amostras {idx_inicio}..{idx_fim} "
              f"({n_por_canal} amostras, {n_por_canal / fs_efetiva * 1000:.2f} ms)")
    else:
        print(f"Canais na captura: {canais} | exibindo: {canais_exibir} | layout: {args.layout_canais}")
        print(f"Frequência total {args.frequencia:g} Hz / {num_canais} canais -> "
              f"frequência efetiva por canal: {fs_efetiva:g} Hz")
        for canal in canais_exibir:
            idx = indice_no_ciclo[canal]
            print(f"  Canal {canal}: --formato {args.formato} | --faixa {faixas[idx]} V | "
                  f"--offset {offsets[idx]} V | --ganho {ganhos[idx]}")
        print(f"Janela selecionada: amostras brutas {idx_inicio}..{idx_fim} "
              f"({n_por_canal} amostras/canal, {n_por_canal / fs_efetiva * 1000:.2f} ms/canal)")

    if args.filtro_passa_alta is not None or args.filtro_passa_baixa is not None:
        partes_filtro = []
        if args.filtro_passa_alta is not None:
            partes_filtro.append(f"passa-alta {args.filtro_passa_alta:g} Hz")
        if args.filtro_passa_baixa is not None:
            partes_filtro.append(f"passa-baixa {args.filtro_passa_baixa:g} Hz")
        print(f"Filtro digital Butterworth aplicado (ordem {args.ordem_filtro}, fase zero): "
              f"{' + '.join(partes_filtro)}")

    infos_espectro = {canal: {} for canal in canais_exibir} if (usa_fft or usa_welch) else None

    if usa_fft:
        n_ciclos_pedido = args.fft if args.fft > 0 else None
        for canal in canais_exibir:
            sinal_fft, idx_i_local, idx_f_local, f0, n_ciclos = recortar_ciclos_inteiros(
                por_canal_tensao[canal], fs_efetiva, args.freq_min, args.freq_max, n_ciclos_pedido
            )
            freqs, amplitude_db = calcular_espectro(
                sinal_fft, fs_efetiva, nome_janela_canonico, args.kaiser_beta, args.modo_espectro
            )

            if args.picos is not None:
                picos = encontrar_picos_espectro(
                    freqs, amplitude_db, args.freq_min_picos, freq_max_picos,
                    args.picos, args.distancia_minima_picos
                )
                _imprimir_picos(canal, "ciclo", picos, num_canais)

            if args.agrupar_bandas is not None:
                freqs, amplitude_db = agrupar_em_bandas(freqs, amplitude_db, args.agrupar_bandas, args.modo_espectro)

            if num_canais == 1:
                print(f"FFT (ciclo): f0 = {f0:.3f} Hz | {n_ciclos} ciclo(s) completo(s) | "
                      f"{len(sinal_fft)} amostras (locais {idx_i_local}..{idx_f_local}) | "
                      f"janela: {rotulo_janela} | modo: {args.modo_espectro}")
            else:
                print(f"  Canal {canal} FFT (ciclo): f0 = {f0:.3f} Hz | {n_ciclos} ciclo(s) | "
                      f"{len(sinal_fft)} amostras (locais {idx_i_local}..{idx_f_local})")

            infos_espectro[canal]["ciclo"] = {
                "freqs": freqs, "amplitude_db": amplitude_db, "f0": f0, "n_ciclos": n_ciclos,
                "idx_inicio_local": idx_i_local, "idx_fim_local": idx_f_local, "janela": rotulo_janela,
            }

    if usa_welch:
        for canal in canais_exibir:
            freqs, amplitude_db, n_segmentos = calcular_espectro_welch(
                por_canal_tensao[canal], fs_efetiva, nome_janela_canonico, args.kaiser_beta,
                args.resolucao_welch, args.sobreposicao_welch, args.modo_espectro,
            )

            if args.picos is not None:
                picos = encontrar_picos_espectro(
                    freqs, amplitude_db, args.freq_min_picos, freq_max_picos,
                    args.picos, args.distancia_minima_picos
                )
                _imprimir_picos(canal, "welch", picos, num_canais)

            if args.agrupar_bandas is not None:
                freqs, amplitude_db = agrupar_em_bandas(freqs, amplitude_db, args.agrupar_bandas, args.modo_espectro)

            prefixo = f"  Canal {canal} " if num_canais > 1 else ""
            print(f"{prefixo}Welch: {n_segmentos} segmento(s) médios | "
                  f"resolução {args.resolucao_welch:g} Hz | modo: {args.modo_espectro}")

            infos_espectro[canal]["welch"] = {
                "freqs": freqs, "amplitude_db": amplitude_db,
                "n_segmentos": n_segmentos, "janela": rotulo_janela,
            }

    if args.agrupar_bandas is not None:
        rotulo_espectro_y = f"Nível por banda de {args.agrupar_bandas:g} Hz (dBV)"
    else:
        rotulo_espectro_y = "Magnitude (dBV)" if args.modo_espectro == "tom" else "PSD (dB re V²/Hz)"
    limite_inferior_db = -100.0 if (args.modo_espectro == "tom" and args.agrupar_bandas is None) else None

    plotar_multicanal(
        por_canal_tensao, fs_efetiva, idx_inicio, infos_espectro, args.arquivo.name,
        args.saida, args.layout_canais, rotulo_espectro_y, limite_inferior_db,
    )


if __name__ == "__main__":
    main()
