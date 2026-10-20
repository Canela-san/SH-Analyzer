"""``adc_tool.py info``: o que cada captura é, sem análise espectral nem gráfico.

Lê o cabeçalho (taxa, canais, faixa, grandeza, sonda, integridade da captura, CRC), confere o tamanho do arquivo e,
com ``--estatisticas``, percorre as amostras em blocos sobre o arquivo mapeado (memória constante, só numpy) para
dar, por canal: média, RMS sem DC, mínimo, máximo, fator de crista e saturação. É o primeiro comando a rodar numa
captura nova, e cabe em lote (``info *.bin``). Não carrega SciPy nem matplotlib.

Depende de: ``cabecalho``, ``amostras``, ``canais``, ``registro``, ``erros``."""

import argparse
import logging
import math
from pathlib import Path

import numpy as np

from .amostras import carregar_amostras_bin
from .cabecalho import CABECALHO_TAMANHO_TOTAL, contar_amostras_arquivo_bin, imprimir_resumo_cabecalho, ler_cabecalho
from .canais import analisar_lista_calibracao, resolver_faixas, resolver_offsets_por_canal
from .erros import ErroSHAN, ErroUso
from .registro import configurar_logging_cli

log = logging.getLogger(__name__)

_BLOCO = 1 << 22      # amostras brutas por bloco (8 MB): memória constante em qualquer tamanho de captura


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adc_tool.py info",
        description="Mostra o que cada captura é: cabeçalho (taxa, canais, faixa, grandeza, sonda, integridade, CRC) "
                    "e o tamanho conferido. Com --estatisticas, também média, RMS, mínimo, máximo, fator de crista "
                    "e saturação de cada canal, em volts no pino do ADC (ou na unidade de --ganho).",
    )
    parser.add_argument("arquivos", type=Path, nargs="+", metavar="ARQUIVO.bin")
    parser.add_argument("--estatisticas", action="store_true",
                        help="Percorre as amostras (em blocos, memória constante) e dá as estatísticas por canal.")
    parser.add_argument("--ganho", type=str, default="1.0", metavar="FATOR",
                        help="Ganho de cada canal para as estatísticas (um valor ou um por canal; padrão 1: volts "
                             "no pino do ADC). Ex.: 19.357 no canal de tensão dá volts na entrada do divisor.")
    return parser


def _estatisticas(caminho: Path, canais: list[int], faixas: list[float], offsets: list[float],
                  ganhos: list[float]) -> list[str]:
    amostras = carregar_amostras_bin(caminho, "uint16", offset=CABECALHO_TAMANHO_TOTAL)
    k = len(canais)
    n_total = (len(amostras) // k) * k
    soma = np.zeros(k)
    soma2 = np.zeros(k)
    minimo = np.full(k, np.inf)
    maximo = np.full(k, -np.inf)
    saturadas = np.zeros(k, dtype=np.int64)
    bloco = (_BLOCO // k) * k
    for a in range(0, n_total, bloco):
        codigos = np.asarray(amostras[a:min(a + bloco, n_total)]).reshape(-1, k)
        saturadas += np.count_nonzero((codigos == 0) | (codigos == 0xFFFF), axis=0)
        x = codigos.astype(np.float64)
        soma += x.sum(axis=0)
        soma2 += (x * x).sum(axis=0)
        minimo = np.minimum(minimo, x.min(axis=0))
        maximo = np.maximum(maximo, x.max(axis=0))
    n = n_total // k
    linhas = []
    for i, canal in enumerate(canais):
        escala = faixas[i] / 65536.0 * ganhos[i]
        media_cod = soma[i] / n
        rms_ca = math.sqrt(max(soma2[i] / n - media_cod ** 2, 0.0)) * escala
        def para_v(c: float, faixa: float = faixas[i], offset: float = offsets[i], ganho: float = ganhos[i]) -> float:
            return (c * faixa / 65536.0 - offset) * ganho
        pico = max(abs(para_v(minimo[i]) - para_v(media_cod)), abs(para_v(maximo[i]) - para_v(media_cod)))
        crista = pico / rms_ca if rms_ca > 0 else math.nan
        linhas.append(f"  canal {canal}: média {para_v(media_cod):+.6g} | RMS sem DC {rms_ca:.6g} | "
                      f"mín {para_v(minimo[i]):+.6g} | máx {para_v(maximo[i]):+.6g} | fator de crista {crista:.3f} | "
                      f"saturação {100.0 * saturadas[i] / n:.4f} %")
    return linhas


def _informar(caminho: Path, args: argparse.Namespace) -> None:
    if not caminho.exists():
        raise ErroSHAN(f"'{caminho}' não encontrado.")
    log.info(f"=== {caminho}  ({caminho.stat().st_size / 1e6:.1f} MB)")
    cab = ler_cabecalho(caminho)
    if cab is None:
        log.info("  sem cabeçalho SHAN (captura anterior a set/2026): a taxa e os canais precisam vir da linha de "
                 "comando na análise (-f, --canais).")
        return
    imprimir_resumo_cabecalho(cab)
    n_arquivo = contar_amostras_arquivo_bin(caminho, "uint16", CABECALHO_TAMANHO_TOTAL)
    if n_arquivo != cab.total_amostras_gravadas:
        log.warning(f"{caminho.name}: o arquivo tem {n_arquivo} amostras, o cabeçalho diz {cab.total_amostras_gravadas} "
                    f"(cópia truncada ou captura interrompida?).")
    if args.estatisticas:
        canais = list(cab.lista_canais)
        faixas, _ = resolver_faixas(None, canais, "uint16", cab.faixa_adc_total_v_por_canal)
        offsets = resolver_offsets_por_canal(None, faixas, "uint16", len(canais))
        ganhos = analisar_lista_calibracao(args.ganho, len(canais), "--ganho")
        unidade = "V no pino do ADC" if args.ganho == "1.0" else "unidade de --ganho"
        log.info(f"Estatísticas ({unidade}):")
        for linha in _estatisticas(caminho, canais, faixas, offsets, ganhos):
            log.info(linha)


def main(argv: list[str] | None = None) -> int:
    parser = montar_parser()
    args = parser.parse_args(argv)
    configurar_logging_cli()
    falhas = 0
    for caminho in args.arquivos:
        try:
            _informar(caminho, args)
        except ErroUso as e:
            parser.error(str(e))
        except ErroSHAN as e:
            log.error(f"{caminho}: {e}")
            falhas += 1
    return 1 if falhas else 0
