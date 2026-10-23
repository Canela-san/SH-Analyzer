"""CLI de ``adc_tool.py aliasing``: separa componentes reais de imagens de aliasing com duas capturas do mesmo sinal em
taxas diferentes (o método está em ``aliasing``).

Lê as duas capturas (a taxa vem do cabeçalho: a que a PRU gera), acha os picos de cada uma acima do piso, pareia cada
pico de uma com o da outra pela frequência de entrada que explica os dois e imprime a tabela; ``--csv`` grava a mesma
tabela. Traduz ``ErroUso`` -> ``parser.error`` e ``ErroSHAN`` -> ``Erro: ...``.
"""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path

import numpy as np

from .aliasing import Componente, entradas_ambiguas, parear, picos_do_sinal
from .cabecalho import ler_cabecalho
from .constantes import CORTE_SUPRAHARMONICOS_PADRAO, DISTANCIA_MINIMA_PICOS_PADRAO
from .erros import ErroSHAN, ErroUso
from .registro import configurar_logging_cli

log = logging.getLogger(__name__)

INICIO_PADRAO_MS = 1.0          # o transitório de troca de faixa do ADS8688 dura < 0,2 ms (F9)
FRACAO_DA_NYQUIST = 0.98        # a análise vai até aqui (o último bin antes da Nyquist mistura as duas metades)


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="adc_tool.py aliasing",
        description="Separa componentes reais de imagens de aliasing com DUAS capturas do mesmo sinal em taxas "
                    "diferentes: um componente real fica na mesma frequência nas duas; uma imagem muda de lugar, e o "
                    "par de posições dá a frequência de entrada. O único anti-aliasing da cadeia é o filtro de ~15 kHz "
                    "do ADS8688: a 400 kS/s, uma imagem chega a 150 kHz só ~9 dB abaixo de um componente real. As "
                    "capturas não são simultâneas: a emissão tem de ser estável entre elas.",
        epilog="Ex.: sudo ./ler_adc 400000 1 --duracao 10s -o A_400k.bin; sudo ./ler_adc 320000 1 --duracao 10s -o "
               "B_320k.bin (na BeagleBone); depois uv run scripts/adc_tool.py aliasing A_400k.bin B_320k.bin "
               "--csv aliasing.csv")
    p.add_argument("captura_a", type=Path, help="1ª captura .bin (com cabeçalho).")
    p.add_argument("captura_b", type=Path, help="2ª captura .bin, do mesmo sinal, em outra taxa.")
    p.add_argument("--canal", type=int, help="Canal analisado (padrão: o primeiro presente nas duas capturas).")
    p.add_argument("--freq-min", type=float, default=CORTE_SUPRAHARMONICOS_PADRAO, metavar="HZ",
                   help="Menor frequência analisada (padrão: %(default)g Hz, abaixo fica a rede e os harmônicos dela).")
    p.add_argument("--freq-max", type=float, metavar="HZ",
                   help=f"Maior frequência analisada (padrão: {FRACAO_DA_NYQUIST:.0%} da Nyquist de cada captura).")
    p.add_argument("--acima-do-piso", type=float, default=20.0, metavar="DB",
                   help="Um pico conta se passar este tanto da mediana do espectro na faixa (padrão: %(default)g dB).")
    p.add_argument("--resolucao", type=float, default=25.0, metavar="HZ",
                   help="Resolução do espectro médio (Welch; padrão: %(default)g Hz).")
    p.add_argument("--tolerancia-hz", type=float, default=100.0, metavar="HZ",
                   help="Distância máxima entre a posição prevista e o pico da outra captura (padrão: %(default)g Hz; "
                        "aumente para emissões que derivam entre as capturas).")
    p.add_argument("--tolerancia-db", type=float, default=3.0, metavar="DB",
                   help="Diferença de amplitude aceita entre as duas capturas (padrão: %(default)g dB). Hipóteses com "
                        "amplitudes que batem valem primeiro; fora disso, o par sai marcado.")
    p.add_argument("--f-max-entrada", type=float, default=1e6, metavar="HZ",
                   help="Maior frequência de entrada considerada (padrão: %(default)g Hz; o filtro do ADC atenua "
                        "~70 dB em 1 MHz).")
    p.add_argument("--inicio-ms", type=float, default=INICIO_PADRAO_MS,
                   help="Pula o começo de cada captura (padrão: %(default)g ms, o transitório de troca de faixa).")
    p.add_argument("--max-segundos", type=float, default=10.0,
                   help="Usa no máximo N segundos de cada captura (padrão: %(default)g s).")
    p.add_argument("--csv", type=Path, help="Grava a tabela (um componente por linha).")
    return p


def _ler(caminho: Path, canal: int | None, args: argparse.Namespace) -> tuple[np.ndarray, float, float | None, int]:
    """(sinal do canal em V no pino do ADC, ou em LSB sem a faixa; fs do canal; faixa total do ADC; canal)."""
    cab = ler_cabecalho(caminho)
    if cab is None or not cab.crc32_valido:
        raise ErroSHAN(f"'{caminho.name}' sem cabeçalho válido: a taxa vem dele.")
    for problema in cab.problemas_integridade:
        log.warning(f"'{caminho.name}': {problema}. A frequência de cada pico depende da taxa do cabeçalho.")
    nc = max(cab.num_canais, 1)
    canais = list(cab.lista_canais[:nc])
    if canal not in canais:
        raise ErroSHAN(f"'{caminho.name}': canal {canal} não está na captura (canais {canais}).")
    fs = (cab.frequencia_pru_hz or float(cab.frequencia_hz)) / nc
    bruto = np.memmap(caminho, dtype="<u2", mode="r", offset=cab.tamanho_cabecalho)
    sinal = bruto[canais.index(canal)::nc]
    inicio = int(round(args.inicio_ms * 1e-3 * fs))
    fim = min(len(sinal), inicio + int(args.max_segundos * fs))
    if fim - inicio < 4 * fs / args.resolucao:
        raise ErroSHAN(f"'{caminho.name}': curta demais para a resolução de {args.resolucao:g} Hz "
                       f"({fim - inicio} amostras).")
    faixas = cab.faixa_adc_total_v_por_canal or ()
    posicao = canais.index(canal)
    faixa = float(faixas[posicao]) if len(faixas) > posicao and faixas[posicao] is not None else None
    sinal = np.asarray(sinal[inicio:fim], dtype=np.float64)
    if faixa is not None:
        sinal = (sinal - 32768.0) * (faixa / 65536.0)
    return sinal, fs, faixa, canal


def _canal_comum(a: Path, b: Path) -> int:
    listas = []
    for caminho in (a, b):
        cab = ler_cabecalho(caminho)
        if cab is None or not cab.crc32_valido:
            raise ErroSHAN(f"'{caminho.name}' sem cabeçalho válido: a taxa vem dele.")
        listas.append(list(cab.lista_canais[:max(cab.num_canais, 1)]))
    comuns = [c for c in listas[0] if c in listas[1]]
    if not comuns:
        raise ErroUso(f"as capturas não têm canal em comum ({listas[0]} e {listas[1]}).")
    return comuns[0]


def _linha(c: Componente) -> str:
    def pico(p):
        return f"{p.frequencia_hz / 1e3:10.3f} {p.amplitude_db:7.1f}" if p is not None else f"{'—':>10} {'—':>7}"
    entrada = f"{c.frequencia_entrada_hz / 1e3:10.3f}" if c.frequencia_entrada_hz is not None else f"{'—':>10}"
    return f"  {entrada}   {pico(c.em_a)}   {pico(c.em_b)}   {c.diagnostico}"


def _gravar_csv(caminho: Path, componentes: list[Componente]) -> None:
    def num(x):
        return "" if x is None else f"{x:.6g}"
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["entrada_hz", "a_hz", "a_db", "b_hz", "b_db", "real_em_a", "real_em_b", "ambiguas_hz", "diagnostico"])
        for c in componentes:
            w.writerow([num(c.frequencia_entrada_hz),
                        num(c.em_a.frequencia_hz if c.em_a else None), num(c.em_a.amplitude_db if c.em_a else None),
                        num(c.em_b.frequencia_hz if c.em_b else None), num(c.em_b.amplitude_db if c.em_b else None),
                        int(c.real_em_a), int(c.real_em_b), ";".join(f"{f:.6g}" for f in c.ambiguas_hz), c.diagnostico])


def main(argv: list[str] | None = None) -> int:
    parser = montar_parser()
    args = parser.parse_args(argv)
    configurar_logging_cli()
    try:
        canal = args.canal if args.canal is not None else _canal_comum(args.captura_a, args.captura_b)
        sinal_a, fs_a, faixa_a, _ = _ler(args.captura_a, canal, args)
        sinal_b, fs_b, faixa_b, _ = _ler(args.captura_b, canal, args)
        if abs(fs_a - fs_b) <= args.tolerancia_hz:
            raise ErroUso(f"as duas capturas têm a mesma taxa por canal ({fs_a:.0f} S/s): para separar as imagens, "
                          "capture o mesmo sinal em outra taxa (ex.: 400000 e 320000).")
        if (faixa_a is None) != (faixa_b is None):
            raise ErroUso("só uma das capturas tem a faixa do ADC no cabeçalho: as amplitudes não são comparáveis.")
        unidade = "dBV no pino do ADC" if faixa_a is not None else "dB re 1 LSB"

        faixas = []
        picos = []
        for nome, sinal, fs in (("A", sinal_a, fs_a), ("B", sinal_b, fs_b)):
            f_max = min(args.freq_max or np.inf, FRACAO_DA_NYQUIST * fs / 2)
            if f_max <= args.freq_min:
                raise ErroUso(f"captura {nome}: a faixa analisada é vazia ({args.freq_min:g} a {f_max:g} Hz).")
            achados, piso = picos_do_sinal(sinal, fs, args.freq_min, f_max, args.acima_do_piso, args.resolucao,
                                           DISTANCIA_MINIMA_PICOS_PADRAO)
            log.info(f"{nome}: {fs / 1e3:g} kS/s no canal {canal}, {args.freq_min / 1e3:g} a {f_max / 1e3:g} kHz: "
                     f"{len(achados)} pico(s) acima de {piso + args.acima_do_piso:.1f} {unidade} (piso {piso:.1f}).")
            faixas.append((args.freq_min, f_max))
            picos.append(achados)

        componentes = parear(picos[0], fs_a, faixas[0], picos[1], fs_b, faixas[1], args.tolerancia_hz,
                             args.tolerancia_db, args.f_max_entrada)
        log.info(f"\n  {'entrada':>10}   {'em A':>10} {'dB':>7}   {'em B':>10} {'dB':>7}   diagnóstico"
                 f"\n  {'(kHz)':>10}   {'(kHz)':>10} {'':>7}   {'(kHz)':>10}")
        for c in componentes:
            log.info(_linha(c))
        reais = sum(1 for c in componentes if c.em_a and c.em_b and c.real_em_a and c.real_em_b)
        imagens = sum(1 for c in componentes if c.em_a and c.em_b and not (c.real_em_a and c.real_em_b))
        sem_par = sum(1 for c in componentes if c.em_a is None or c.em_b is None)
        log.info(f"\n{reais} real(is), {imagens} com imagem em pelo menos uma das capturas e {sem_par} sem par "
                 f"(amplitudes em {unidade}).")

        ambiguas = entradas_ambiguas(fs_a, fs_b, min(f[1] for f in faixas), args.f_max_entrada, args.tolerancia_hz)
        if ambiguas:
            texto = ", ".join(f"{x / 1e3:g} kHz (de {e / 1e3:g})" for x, e in ambiguas)
            log.info(f"Com {fs_a / 1e3:g} e {fs_b / 1e3:g} kS/s, uma imagem cai no mesmo lugar nas duas em: {texto}. "
                     "Um pico real ali não se distingue dessa imagem sem uma 3ª taxa.")
        if args.csv is not None:
            _gravar_csv(args.csv, componentes)
            log.info(f"Tabela gravada em {args.csv}")
    except ErroUso as e:
        parser.error(str(e))
    except ErroSHAN as e:
        log.error(f"Erro: {e}")
        return 1
    return 0
