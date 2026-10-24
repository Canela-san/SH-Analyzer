"""Linha de comando do ``medir_shunt.py``: a impedância Z(f) de um resistor (o shunt do laço de corrente) pelo
osciloscópio, com a tensão sobre ele (THDP0200) e a corrente por ele (TCP0030A) na MESMA captura.

É a razão de dois canais simultâneos (``razao_quadrada``), aqui entre dois canais do osciloscópio: Z = V / I em cada
harmônico ímpar de uma quadrada, com a fase absoluta (os dois canais têm a mesma base de tempo; o que as pontas
atrasam diferente sai com ``--deskew-ns``, se o osciloscópio não o tirou). Um resistor de fio tem indutância (Z sobe
e a fase vai a dezenas de graus em 100 kHz); o CSV que sai é o ``--shunt`` do ``medir_fase.py --canal-referencia``.
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
import re
from pathlib import Path

import numpy as np

from .erros import ErroSHAN, ErroUso
from .escrita_perfil import gerar_grafico_curva
from .fase_quadrada import Q_PADRAO, combinar_em_grade
from .osciloscopio import ler_variaveis, montar_forma_de_onda
from .perfil_complexo import COLUNAS_SHUNT
from .razao_quadrada import medir_razao, pontos_da_razao
from .registro import configurar_logging_cli

log = logging.getLogger(__name__)

F0_PLANO_HZ = 1e12
DB = 20 / math.log(10)
FREQ_MAX_PADRAO_HZ = 200e3
_RE_F1_NO_NOME = re.compile(r"(?<![0-9.])([0-9]+(?:\.[0-9]+)?)Hz")


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="medir_shunt.py",
        description="Impedância Z(f) de um resistor pelo osciloscópio: a tensão sobre ele e a corrente por ele na "
                    "mesma captura (uma onda quadrada pelo laço), Z = V/I em cada harmônico ímpar, com a fase. O CSV "
                    "é o --shunt do medir_fase.py --canal-referencia.",
        epilog="Ex.: uv run scripts/medir_shunt.py $DIA/shunt_1280Hz.csv $DIA/shunt_20736Hz.csv --var-tensao CH1 "
               "--var-corrente CH2 --csv scripts/sondas/shunt_10ohm.csv --plot shunt.png")
    p.add_argument("arquivos", nargs="+", type=Path,
                   help="Formas de onda do osciloscópio (.csv/.m/.mat/.txt), cada uma com a tensão e a corrente; de "
                        "preferência uma quadrada de f₁ baixa (pontos densos) e uma de f₁ alta (sinal em alta "
                        "frequência). A f₁ sai do nome ('..._1280Hz...') ou do maior pico.")
    p.add_argument("--var-tensao", default="CH1", metavar="NOME[:COL]",
                   help="Variável (ou coluna) da tensão sobre o resistor (padrão: %(default)s).")
    p.add_argument("--var-corrente", default="CH2", metavar="NOME[:COL]",
                   help="Variável (ou coluna) da corrente por ele, em A (padrão: %(default)s).")
    p.add_argument("--osc-tempo", metavar="NOME", help="Variável com o vetor de tempo (padrão: detectada).")
    p.add_argument("--osc-fs", type=float, metavar="HZ", help="Taxa do osciloscópio, se o arquivo não a traz.")
    p.add_argument("--escala-tensao", type=float, default=1.0, help="Multiplica a tensão (padrão: %(default)s).")
    p.add_argument("--escala-corrente", type=float, default=1.0,
                   help="Multiplica a corrente (ex.: 1/R de um shunt de referência; padrão: %(default)s).")
    p.add_argument("--deskew-ns", type=float, default=0.0,
                   help="Quanto a ponta de corrente atrasa a mais que a de tensão, em ns, se o osciloscópio não o "
                        "descontou (padrão: 0).")
    p.add_argument("--freq-max", type=float, default=FREQ_MAX_PADRAO_HZ, metavar="HZ",
                   help="Maior frequência medida (padrão: %(default)g).")
    p.add_argument("--por-decada", type=int, default=20, help="Faixas por década da grade (padrão: %(default)s).")
    p.add_argument("--resistencia-dc", type=float, metavar="OHMS",
                   help="A resistência medida a 4 fios (o Fluke), para comparar com a de baixa frequência.")
    p.add_argument("--csv", type=Path, required=True, help="O CSV da impedância (freq_hz, z_ohm, fase_graus, ...).")
    p.add_argument("--plot", type=Path, help="Grava o Bode de Z (PNG/PDF).")
    return p


def _ler(caminho: Path, args: argparse.Namespace) -> tuple[np.ndarray, np.ndarray, float]:
    variaveis = ler_variaveis(caminho)
    v = montar_forma_de_onda(variaveis, caminho.name, args.var_tensao, args.osc_tempo, args.osc_fs, args.escala_tensao)
    i = montar_forma_de_onda(variaveis, caminho.name, args.var_corrente, args.osc_tempo, args.osc_fs, args.escala_corrente)
    if abs(v.fs / i.fs - 1) > 1e-9:
        raise ErroSHAN(f"'{caminho.name}': a tensão ({v.fs:g} S/s) e a corrente ({i.fs:g} S/s) têm taxas diferentes.")
    return np.asarray(v.valores, dtype=float), np.asarray(i.valores, dtype=float), v.fs


def ajustar_r_l(f: np.ndarray, z: np.ndarray, sigma: np.ndarray) -> tuple[float, float]:
    """R e L de Z = R + jωL, por mínimos quadrados ponderados nas partes real e imaginária."""
    w = 1 / np.maximum(sigma * np.abs(z), 1e-300) ** 2
    r = float(np.sum(w * z.real) / np.sum(w))
    omega = 2 * np.pi * f
    indutancia = float(np.sum(w * omega * z.imag) / np.sum(w * omega * omega))
    return r, indutancia


def executar(args: argparse.Namespace) -> None:
    if args.freq_max <= 0:
        raise ErroUso("--freq-max precisa ser positiva.")
    curvas, rotulos, medidas = [], [], []
    for caminho in args.arquivos:
        v, i, fs = _ler(caminho, args)
        m = _RE_F1_NO_NOME.search(caminho.stem)
        try:
            # Z = V/I: a tensão é o canal "a" e a corrente, a referência; τ_v − τ_i = o atraso a mais da corrente
            r = medir_razao(v, i, fs, float(m.group(1)) if m else None, args.deskew_ns * 1e-9, args.freq_max,
                            prever_aliasing=False)
        except ErroSHAN as e:
            raise ErroSHAN(f"'{caminho.name}': {e}") from None
        u = r.usado
        log.info(f"{caminho.name} ({fs / 1e6:g} MS/s, {len(v) / fs * 1e3:.0f} ms): f₁ = {r.f1_hz:.3f} Hz, {r.blocos} "
                 f"blocos, {int(u.sum())} de {len(r)} harmônicos ímpares até {r.freq_hz[-1] / 1e3:.1f} kHz")
        if not np.any(u):
            continue
        curvas.append(pontos_da_razao(r))
        rotulos.append(f"f₁ = {r.f1_hz:.0f} Hz")
        medidas.append(r)
    if not curvas:
        raise ErroSHAN("nenhum harmônico com SNR suficiente nas formas de onda.")
    grade = combinar_em_grade(curvas, F0_PLANO_HZ, Q_PADRAO, args.por_decada)
    f = np.concatenate([r.freq_hz[r.usado] for r in medidas])
    z = np.concatenate([r.razao[r.usado] for r in medidas])
    s = np.concatenate([r.sigma_ln[r.usado] for r in medidas])
    resistencia, indutancia = ajustar_r_l(f, z, s)
    z_100k = np.exp(np.interp(math.log(100e3), np.log(grade.freq_hz), grade.ln_ganho))
    fase_100k = math.degrees(float(np.interp(math.log(100e3), np.log(grade.freq_hz), grade.fase_rad)))
    texto = (f"Z(f) em {len(grade.freq_hz)} faixas, de {grade.freq_hz[0]:.0f} Hz a {grade.freq_hz[-1] / 1e3:.1f} kHz: "
             f"R + jωL com R = {resistencia:.6g} Ω e L = {indutancia * 1e9:.6g} nH")
    if grade.freq_hz[0] <= 100e3 <= grade.freq_hz[-1]:
        texto += f"; em 100 kHz, |Z| = {z_100k:.5g} Ω e {fase_100k:+.3f}°"
    log.info(texto)
    if args.resistencia_dc is not None:
        baixa = math.exp(float(grade.ln_ganho[0]))
        log.info(f"Em {grade.freq_hz[0]:.0f} Hz, |Z| = {baixa:.5g} Ω; a 4 fios, {args.resistencia_dc:.5g} Ω "
                 f"({100 * (baixa / args.resistencia_dc - 1):+.3f} %: o erro de ganho relativo das duas pontas)")
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with open(args.csv, "w", newline="", encoding="utf-8") as arq:
        w = csv.DictWriter(arq, fieldnames=COLUNAS_SHUNT)
        w.writeheader()
        for k in range(len(grade.freq_hz)):
            w.writerow({"freq_hz": f"{grade.freq_hz[k]:.3f}", "z_ohm": f"{math.exp(grade.ln_ganho[k]):.8g}",
                        "fase_graus": f"{math.degrees(grade.fase_rad[k]):.5f}",
                        "sigma_pct": f"{100 * grade.sigma_ln[k]:.5f}",
                        "sigma_graus": f"{math.degrees(grade.sigma_fase[k]):.5f}", "harmonicos": int(grade.pontos[k])})
    log.info(f"Impedância gravada em {args.csv}")
    if args.plot is not None:
        gerar_grafico_curva(curvas, grade, rotulos, args.plot,
                            f"Impedância do shunt pelo osciloscópio (R = {resistencia:.4g} Ω, L = {indutancia * 1e9:.3g} nH)",
                            "|Z| (dB Ω)")


def main(argv: list[str] | None = None) -> int:
    parser = montar_parser()
    args = parser.parse_args(argv)
    configurar_logging_cli()
    try:
        executar(args)
    except ErroUso as e:
        parser.error(str(e))
    except ErroSHAN as e:
        log.error(str(e))
        return 1
    return 0
