"""Leitura de amostras (``.bin`` via memmap, ``.csv``) e conversão código -> volts.

O ``.bin`` NUNCA é carregado inteiro na RAM: ``numpy.memmap`` mapeia o arquivo
e só as páginas realmente acessadas são lidas -- requisito de desempenho do
projeto para capturas longas em altas taxas de amostragem.

Depende de: ``constantes``, ``erros``."""

from pathlib import Path

import numpy as np

from .constantes import FORMATOS_NUMPY
from .erros import ErroSHAN

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
    raise ErroSHAN(
        f"extensão '{sufixo or '(nenhuma)'}' não reconhecida em "
        f"'{caminho}'. Use '.bin' ou '.csv'."
    )


def carregar_amostras_bin(caminho: Path, formato: str, offset: int = 0) -> np.memmap:
    """Memory-map: só as páginas efetivamente acessadas (--inicio/--fim, ou
    o processamento em blocos da conversão/exportação) são carregadas na
    RAM. 'offset' pula os primeiros N bytes do arquivo antes de começar a
    interpretar amostras -- usado para pular o cabeçalho de 1024 bytes dos
    '.bin' novos (ver CABECALHO_TAMANHO_TOTAL/ler_cabecalho).

    offset=1024 funciona normalmente mesmo sem estar alinhado ao tamanho de
    página do SO (tipicamente 4096 bytes): o requisito documentado do
    numpy.memmap é só que 'offset' seja múltiplo do itemsize do dtype (2
    bytes para int16/uint16 -- 1024 é múltiplo de 2). O numpy resolve o
    alinhamento de baixo nível exigido pelo mmap() do SO internamente."""
    dtype = FORMATOS_NUMPY[formato]
    try:
        amostras = np.memmap(caminho, dtype=dtype, mode="r", offset=offset)
    except FileNotFoundError:
        raise ErroSHAN(f"arquivo '{caminho}' não encontrado.")
    except ValueError as e:
        raise ErroSHAN(f"falha ao abrir '{caminho}' (offset={offset} byte(s)): {e}") from e

    if amostras.size == 0:
        raise ErroSHAN(
            f"'{caminho}' está vazio (0 amostras) após pular "
            f"{offset} byte(s) de cabeçalho."
        )
    return amostras


def carregar_amostras_csv(caminho: Path, formato: str) -> np.ndarray:
    """Lê a coluna 'valor_bruto' -- a mesma fonte de verdade usada para
    reconstruir o '.bin'. Ao contrário do memmap, um '.csv' precisa ser
    escaneado inteiro para ser interpretado, então é carregado por completo."""
    try:
        with open(caminho, newline="") as f:
            primeira_linha = f.readline()
            if not primeira_linha:
                raise ErroSHAN(f"'{caminho}' está vazio.")
            cabecalho = primeira_linha.strip().split(",")
            if "valor_bruto" not in cabecalho:
                raise ErroSHAN(
                    f"'{caminho}' não tem coluna 'valor_bruto' "
                    f"(colunas encontradas: {cabecalho})."
                )
            indice_coluna = cabecalho.index("valor_bruto")
            amostras = np.loadtxt(
                f, delimiter=",", usecols=(indice_coluna,),
                dtype=FORMATOS_NUMPY[formato],
            )
    except FileNotFoundError:
        raise ErroSHAN(f"arquivo '{caminho}' não encontrado.")

    amostras = np.atleast_1d(amostras)
    if amostras.size == 0:
        raise ErroSHAN(f"'{caminho}' não tem linhas de dados.")
    return amostras


def carregar_amostras(caminho: Path, formato: str, offset: int = 0):
    """'offset' só é relevante (e só é repassado) para '.bin' -- um '.csv'
    não tem o conceito de cabeçalho binário no início do arquivo."""
    tipo = detectar_tipo_arquivo(caminho)
    if tipo == "bin":
        return carregar_amostras_bin(caminho, formato, offset=offset)
    return carregar_amostras_csv(caminho, formato)


def selecionar_intervalo(amostras, inicio: int, fim: int | None):
    """Aplica --inicio/--fim (em amostras). Funciona igual para memmap
    (fatiar só toca as páginas pedidas) ou ndarray já carregado."""
    total = len(amostras)
    inicio = max(0, inicio)
    fim = total if fim is None else min(fim, total)

    if inicio >= fim:
        raise ErroSHAN(
            f"intervalo inválido (--inicio {inicio} >= --fim {fim}). "
            f"O arquivo tem {total} amostras no total."
        )
    return np.asarray(amostras[inicio:fim]), inicio, fim, total


def detectar_transitorio_inicial(codigos: np.ndarray, procurar: int = 64, referencia: int = 4096,
                                 limite_lsb: float = 8.0) -> tuple[int, float]:
    """(quantas amostras do começo destoam do resto, maior desvio em LSB), num canal em códigos brutos (F9).

    Compara as ``procurar`` primeiras amostras com a mediana das ``referencia`` seguintes: destoa a que se afasta
    mais de 8 desvios robustos (1,4826·MAD) e de ``limite_lsb``. Um tom não dispara o aviso (o desvio robusto de uma
    senoide é ~1,05 vez a amplitude, e nenhuma amostra passa de 1 amplitude); o que dispara é um começo que foge do
    resto, como a acomodação do ADC depois de trocar a faixa de um canal, que importa justamente em medidas de
    ruído e de DC."""
    if len(codigos) < procurar + 256:
        return 0, 0.0
    resto = np.asarray(codigos[procurar:procurar + referencia], dtype=np.float64)
    mediana = float(np.median(resto))
    desvio_robusto = 1.4826 * float(np.median(np.abs(resto - mediana)))
    limiar = max(limite_lsb, 8.0 * desvio_robusto)
    desvios = np.abs(np.asarray(codigos[:procurar], dtype=np.float64) - mediana)
    acima = np.flatnonzero(desvios > limiar)
    if acima.size == 0:
        return 0, 0.0
    return int(acima[-1]) + 1, float(np.max(desvios))


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
