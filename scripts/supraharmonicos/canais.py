"""Suporte multi-canal: listas de canais/calibração, desintercalação e offsets.

Depende de: ``constantes``, ``erros``, ``registro`` (via ``logging``)."""

import logging

import numpy as np

from .constantes import ADS8688_MAX_CANAIS
from .erros import ErroSHAN

log = logging.getLogger(__name__)


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
            raise ErroSHAN(f"'{p}' não é um canal válido em {nome_flag}='{texto}'.")
        if valor < 0 or valor > 7:
            raise ErroSHAN(f"canal {valor} inválido em {nome_flag} -- ADS8688 só tem canais 0-7.")
        if valor in canais:
            raise ErroSHAN(f"canal {valor} repetido em {nome_flag}='{texto}'.")
        if len(canais) >= ADS8688_MAX_CANAIS:
            raise ErroSHAN(f"mais de {ADS8688_MAX_CANAIS} canais em {nome_flag}='{texto}'.")
        canais.append(valor)

    if not canais:
        raise ErroSHAN(f"lista de canais vazia em {nome_flag}.")
    return canais


def validar_subconjunto_canais(canais_exibir: list[int], canais: list[int]) -> None:
    faltando = [c for c in canais_exibir if c not in canais]
    if faltando:
        raise ErroSHAN(
            f"--canais-exibir pede o(s) canal(is) {faltando}, ausente(s) "
            f"em --canais ({canais})."
        )


def analisar_lista_calibracao(texto: str, num_canais: int, nome_flag: str) -> list[float]:
    """--faixa/--ganho/--offset: um valor único (todos os canais) ou uma
    lista do mesmo tamanho de --canais, na mesma ordem."""
    partes = [p.strip() for p in texto.split(",")]
    try:
        valores = [float(p) for p in partes]
    except ValueError:
        raise ErroSHAN(f"valor inválido em {nome_flag}='{texto}'.")
    if len(valores) == 1:
        return valores * num_canais
    if len(valores) != num_canais:
        raise ErroSHAN(
            f"{nome_flag} tem {len(valores)} valor(es), mas --canais tem "
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
        raise ErroSHAN(
            f"só {n} amostra(s) bruta(s), insuficiente para 1 ciclo de "
            f"{num_canais} canais."
        )
    if n_truncado < n:
        log.warning(
            f"{n - n_truncado} amostra(s) no final do recorte não "
            f"completam um ciclo de {num_canais} canais e foram descartadas."
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
