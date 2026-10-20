"""Suporte multi-canal: listas de canais/calibração, desintercalação e offsets.

Depende de: ``constantes``, ``erros``, ``registro`` (via ``logging``)."""

import logging
import math
from collections.abc import Sequence

import numpy as np

from .constantes import ADS8688_MAX_CANAIS, FAIXA_LEGADA_V, TOLERANCIA_FAIXA_V
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
    if not all(math.isfinite(v) for v in valores):   # float() aceita 'nan'/'inf': viraria amplitude NaN em silêncio
        raise ErroSHAN(f"{nome_flag}='{texto}' precisa ter só números finitos.")
    if len(valores) == 1:
        return valores * num_canais
    if len(valores) != num_canais:
        raise ErroSHAN(
            f"{nome_flag} tem {len(valores)} valor(es), mas --canais tem "
            f"{num_canais} canal(is). Passe 1 valor ou exatamente {num_canais}."
        )
    return valores


def faixa_cli_do_total_v(total_v: float, formato: str) -> float:
    """Converte o fundo de escala TOTAL do ADC (V pico a pico, o que o
    cabeçalho v3 registra) no valor de ``--faixa`` do ``--formato``:
    ``uint16`` usa o total (V = código·faixa/65536 − faixa/2); ``int16`` usa a
    metade positiva (V = código·faixa/32768, ver amostras.converter_para_tensao)."""
    return total_v / 2.0 if formato == "int16" else total_v


def resolver_faixas(texto: str | None, canais: Sequence[int], formato: str,
                    faixas_cabecalho_total_v: Sequence[float | None] | None = None,
                    nome_flag: str = "--faixa") -> tuple[list[float], list[bool]]:
    """Resolve ``--faixa`` por canal: **valor digitado > cabeçalho v3 > padrão histórico**.

    - ``texto`` (``--faixa``) dado: vale para os canais (um valor para todos, ou
      um por canal). Se o cabeçalho registra a faixa real de algum canal e o
      valor digitado diverge dela, avisa -- o ADC converteu aquele canal com a
      faixa do cabeçalho, então um ``--faixa`` diferente escala errado a
      amplitude (e o erro seria silencioso).
    - sem ``texto``: usa a faixa gravada no cabeçalho (v3) de cada canal; onde
      ela é desconhecida (captura v1/v2, anterior ao registro), cai em
      ``FAIXA_LEGADA_V`` -- o padrão histórico das ferramentas.

    ``faixas_cabecalho_total_v``: fundo de escala total (V) por canal, na ordem
    de ``canais`` (``CabecalhoArquivo.faixa_adc_total_v_por_canal``), ``None``
    por canal desconhecido, ou ``None`` no todo se não há cabeçalho.

    Devolve ``(faixas, confiaveis)``: ``confiaveis[i]`` é True quando a faixa
    usada para o canal i coincide com a registrada no cabeçalho (ou seja,
    é a faixa REAL do ADC, não uma suposição)."""
    n = len(canais)
    do_cabecalho: list[float | None] = [None] * n
    if faixas_cabecalho_total_v is not None and len(faixas_cabecalho_total_v) == n:
        do_cabecalho = [None if v is None else faixa_cli_do_total_v(v, formato) for v in faixas_cabecalho_total_v]

    if texto is None:
        faixas = [FAIXA_LEGADA_V if v is None else v for v in do_cabecalho]
        return faixas, [v is not None for v in do_cabecalho]

    faixas = analisar_lista_calibracao(texto, n, nome_flag)
    confiaveis = []
    for canal, digitada, real in zip(canais, faixas, do_cabecalho):
        if real is None:
            confiaveis.append(False)
        elif abs(digitada - real) <= TOLERANCIA_FAIXA_V:
            confiaveis.append(True)
        else:
            confiaveis.append(False)
            log.warning(
                f"canal {canal}: {nome_flag} {digitada:g}, mas o cabeçalho da captura registra que o ADC "
                f"converteu esse canal com a faixa que corresponde a {nome_flag} {real:g} (--formato {formato}). "
                f"Valores diferentes escalam a amplitude errado (fator {digitada / real:.4g}); "
                f"omita {nome_flag} para usar a faixa do cabeçalho."
            )
    return faixas, confiaveis


def alinhar_ao_ciclo(inicio: int, num_canais: int, nome_flag: str = "--inicio") -> int:
    """Primeira amostra BRUTA a usar, arredondada para baixo até o começo de um ciclo de ``num_canais``.

    As amostras de uma captura multi-canal são intercaladas (canal 0, canal 1, canal 0, ...) e
    :func:`desintercalar` supõe que a primeira amostra do trecho é do primeiro canal do ciclo. Um
    ``--inicio`` no meio do ciclo deslocaria TODOS os canais (com 2 canais, um viraria o outro) sem
    nenhum outro sintoma -- por isso o início é alinhado, com aviso."""
    inicio = max(0, inicio)
    alinhado = inicio - inicio % num_canais
    if alinhado != inicio:
        log.warning(
            f"{nome_flag} {inicio} cai no meio de um ciclo de {num_canais} canais intercalados: usando "
            f"{alinhado} (início do ciclo), senão cada canal seria lido com o rótulo de outro."
        )
    return alinhado


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
