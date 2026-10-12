"""Modo de conversão ``.bin`` <-> ``.csv``, sempre em blocos (chunks).

Depende de: ``amostras``, ``canais``, ``cabecalho``, ``constantes``, ``erros``."""

import itertools
import logging
from pathlib import Path

import numpy as np

from .amostras import (
    carregar_amostras_bin,
    converter_para_tensao,
    detectar_tipo_arquivo,
    selecionar_intervalo,
)
from .constantes import FORMATOS_NUMPY, TAMANHO_CHUNK_PADRAO
from .erros import ErroSHAN

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 4. Modo de conversão: .bin <-> .csv
# ---------------------------------------------------------------------------

def bin_para_csv(caminho_bin: Path, caminho_csv: Path, formato: str,
                  inicio: int, fim: int | None, incluir_tensao: bool,
                  canais: list[int], faixas: list[float], ganhos: list[float],
                  offsets: list[float], offset_amostras: int = 0,
                  tamanho_chunk: int = TAMANHO_CHUNK_PADRAO) -> int:
    """Converte em blocos, sem carregar o '.bin' inteiro na RAM. Ganha uma
    coluna 'canal' quando len(canais) > 1 (formato de 1 canal permanece
    idêntico ao de antes do suporte multi-canal). 'offset_amostras' pula o
    cabeçalho de 1024 bytes quando presente (ver ler_cabecalho em main()) --
    --inicio/--fim continuam contando a partir da primeira amostra REAL
    (pós-cabeçalho), nunca do byte 0 do arquivo."""
    amostras = carregar_amostras_bin(caminho_bin, formato, offset=offset_amostras)
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

    with open(caminho_csv, newline="") as f_in:
        primeira_linha = f_in.readline()
        if not primeira_linha:
            raise ErroSHAN(f"'{caminho_csv}' está vazio.")
        cabecalho = primeira_linha.rstrip("\n").split(",")
        if "valor_bruto" not in cabecalho:
            raise ErroSHAN(f"'{caminho_csv}' não tem coluna 'valor_bruto'.")
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
            log.warning(
                f"coluna 'canal' de '{caminho_csv}' não segue um "
                f"padrão cíclico consistente ({inconsistencias} linha(s) "
                f"fora do padrão {padrao_canais})."
            )

        if fim is not None and n_convertidas < (fim - inicio):
            log.warning(
                f"--fim pediu {fim} amostra(s), mas '{caminho_csv}' só "
                f"tinha {inicio + n_convertidas} linha(s). Convertida(s) "
                f"{n_convertidas}."
            )

    if n_convertidas == 0:
        raise ErroSHAN(f"nenhuma amostra convertida de '{caminho_csv}'.")
    return n_convertidas


def converter_arquivo(caminho_entrada: Path, caminho_saida: Path, formato: str,
                       inicio: int, fim: int | None, incluir_tensao: bool,
                       canais: list[int], faixas: list[float], ganhos: list[float],
                       offsets: list[float], tamanho_chunk: int,
                       offset_amostras: int = 0) -> None:
    """Direção decidida pelas extensões de entrada/saída."""
    tipo_entrada = detectar_tipo_arquivo(caminho_entrada)
    tipo_saida = detectar_tipo_arquivo(caminho_saida)

    if tipo_entrada == tipo_saida:
        raise ErroSHAN(
            f"entrada e saída têm o mesmo formato (.{tipo_entrada}) -- "
            f"não há conversão a fazer."
        )

    if incluir_tensao and tipo_entrada != "bin":
        log.warning(
            "--incluir-tensao só tem efeito em .bin -> .csv; ignorado."
        )

    if tipo_entrada == "bin" and tipo_saida == "csv":
        n = bin_para_csv(caminho_entrada, caminho_saida, formato, inicio, fim,
                          incluir_tensao, canais, faixas, ganhos, offsets,
                          offset_amostras, tamanho_chunk)
        extra = " | coluna tensao_v incluída" if incluir_tensao else ""
        extra_canal = (f" | {len(canais)} canais intercalados {canais} (coluna 'canal')"
                       if len(canais) > 1 else "")
        log.info(f"Convertido: '{caminho_entrada}' (.bin) -> '{caminho_saida}' (.csv) | "
              f"{n} amostra(s) | --formato {formato}{extra}{extra_canal}")
    else:
        n = csv_para_bin(caminho_entrada, caminho_saida, formato, inicio, fim, tamanho_chunk)
        log.info(f"Convertido: '{caminho_entrada}' (.csv) -> '{caminho_saida}' (.bin) | "
              f"{n} amostra(s) | --formato {formato}")
        log.warning(
            "o '.bin' reconstruído NÃO tem o cabeçalho de 1024 bytes "
            "(magic 'SHAN', título, timestamp, etc.) -- essa informação não "
            "sobrevive a uma ida por '.csv', que não tem onde guardá-la. "
            "Ferramentas que leem este arquivo de volta vão tratá-lo como "
            "captura no formato antigo (sem cabeçalho)."
        )
