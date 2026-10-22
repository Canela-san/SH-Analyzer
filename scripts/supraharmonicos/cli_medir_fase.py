"""CLI de ``scripts/medir_fase.py``: a resposta em frequência da cadeia (magnitude E fase) por capturas de onda quadrada.

A medida está em ``fase_quadrada``; aqui ficam a leitura das capturas, as duas passadas (o modelo de partida e o
ajustado), o ajuste do 2ª ordem (conjunto, só magnitude e só fase: a comparação é o teste da fase mínima), o CSV,
o gráfico e o perfil de sonda com a fase. Traduz ``ErroUso`` -> ``parser.error`` e ``ErroSHAN`` -> ``Erro: ...``.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from .cabecalho import ler_cabecalho
from .calibracao_sonda import PontoPerfil, resumir_resposta
from .erros import ErroSHAN, ErroUso
from .escrita_perfil import gerar_grafico_bode, gravar_perfil_validado
from .fase_quadrada import (
    F0_PADRAO_HZ,
    Q_PADRAO,
    AjusteFase,
    RespostaQuadrada,
    ajustar_segunda_ordem,
    fase_absoluta,
    h_segunda_ordem,
    medir_quadrada,
)
from .registro import configurar_logging_cli
from .sonda import carregar_perfil_sonda

log = logging.getLogger(__name__)

INICIO_PADRAO_MS = 0.2          # o transitório de troca de faixa do ADC (T0): ~80 µs
COLUNAS_CSV = ["arquivo", "fs_hz", "f1_hz", "duty_desvio", "n", "freq_hz", "ganho_rel", "ganho_rel_db", "sigma_db",
               "fase_rel_graus", "fase_min_graus", "sigma_graus", "snr_db", "contaminacao_db", "usado", "motivo"]
_RE_F1_NA_DESCRICAO = re.compile(r"quadrada\s+f=([0-9.]+)\s*Hz", re.IGNORECASE)


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="medir_fase.py",
        description="Magnitude e FASE da cadeia (sonda + frontend + ADS8688) a partir de capturas de onda quadrada, "
                    "sem osciloscópio: a fase de cada harmônico ímpar menos n vezes a da fundamental não depende do "
                    "instante da captura (S2, docs/improvement-proposals.md). Ajusta o passa-baixa de 2ª ordem pela "
                    "magnitude, pela fase e pelas duas, e pode gravar um perfil de sonda com a fase.",
        epilog="Ex.: uv run scripts/medir_fase.py $DIA/T3f_*/F_*.bin --csv fase.csv --plot fase.png "
               "--perfil-base scripts/sondas/cadeia_tensao_312k.json --saida-perfil scripts/sondas/cadeia_tensao_fase.json")
    p.add_argument("arquivos", nargs="+", type=Path, help="Capturas .bin (cabeçalho v5+) de uma quadrada simétrica.")
    p.add_argument("--canal", type=int, help="Canal com a quadrada (padrão: o único, ou o último da captura).")
    p.add_argument("--f1", type=float, metavar="HZ",
                   help="Frequência aproximada da quadrada (padrão: 'quadrada f=...Hz' na descrição da captura, ou o "
                        "maior pico do espectro).")
    p.add_argument("--inicio-ms", type=float, default=INICIO_PADRAO_MS,
                   help=f"Pula o começo da captura (padrão: {INICIO_PADRAO_MS} ms, o transitório de troca de faixa).")
    p.add_argument("--max-segundos", type=float, help="Usa só os primeiros N segundos de cada captura.")
    p.add_argument("--freq-max", type=float, metavar="HZ", help="Maior frequência medida (padrão: 95 %% da Nyquist).")
    p.add_argument("--modelo-inicial", default=f"{F0_PADRAO_HZ:g},{Q_PADRAO:g}", metavar="F0,Q",
                   help="2ª ordem de partida, só para desenrolar a fase e prever o aliasing (padrão: o do T3, "
                        "%(default)s).")
    p.add_argument("--csv", type=Path, help="Grava um ponto por harmônico (usados e descartados, com o motivo).")
    p.add_argument("--plot", type=Path, help="Grava o diagrama de Bode medido, com o ajuste (PNG/PDF).")
    p.add_argument("--perfil-base", type=Path,
                   help="Perfil de sonda (.json) do qual vêm a calibração do ADC, o --ganho e os pontos abaixo da "
                        "menor frequência medida. Pede --saida-perfil.")
    p.add_argument("--saida-perfil", type=Path, help="Grava o perfil com a fase (cada ponto ganha 'fase_rad').")
    p.add_argument("--id", help="Id do perfil gravado (padrão: o nome do arquivo de --saida-perfil).")
    p.add_argument("--ganho-baixa-frequencia", type=float, metavar="K",
                   help="Ganho da cadeia em baixa frequência (o 'K' do 2ª ordem), que a quadrada não mede (ela é "
                        "relativa). Padrão: a mediana dos pontos do --perfil-base abaixo de 1 kHz. O T2 (DC, Fluke) dá "
                        "0,051554 x 19,357 = 0,99795.")
    return p


def _analisar_modelo(texto: str) -> tuple[float, float]:
    try:
        f0, q = (float(v) for v in texto.split(","))
    except ValueError:
        raise ErroUso(f"--modelo-inicial espera 'F0,Q' (ex.: 24165,0.5288), recebeu '{texto}'.") from None
    if not (f0 > 0 and q > 0):
        raise ErroUso("--modelo-inicial precisa de F0 e Q positivos.")
    return f0, q


def ler_quadrada(caminho: Path, args: argparse.Namespace) -> tuple[np.ndarray, float, float | None, str]:
    """(sinal do canal em LSB, fs do canal, f₁ de dica, descrição curta)."""
    cab = ler_cabecalho(caminho)
    if cab is None or not cab.crc32_valido:
        raise ErroSHAN(f"'{caminho.name}' sem cabeçalho válido: a taxa e o canal vêm dele.")
    fs_total = cab.frequencia_pru_hz or float(cab.frequencia_hz)
    nc = max(cab.num_canais, 1)
    canais = list(cab.lista_canais[:nc])
    canal = args.canal if args.canal is not None else canais[-1]
    if canal not in canais:
        raise ErroSHAN(f"'{caminho.name}': canal {canal} não está na captura (canais {canais}).")
    fs = fs_total / nc
    bruto = np.memmap(caminho, dtype="<u2", mode="r", offset=cab.tamanho_cabecalho)
    sinal = bruto[canais.index(canal)::nc]
    inicio = int(round(args.inicio_ms * 1e-3 * fs))
    fim = len(sinal) if args.max_segundos is None else min(len(sinal), inicio + int(args.max_segundos * fs))
    if fim - inicio < 1000:
        raise ErroSHAN(f"'{caminho.name}': curta demais ({fim - inicio} amostras).")
    dica = args.f1
    if dica is None:
        m = _RE_F1_NA_DESCRICAO.search(cab.descricao or "")
        dica = float(m.group(1)) if m else None
    rotulo = f"{fs / 1e3:g} kS/s" + (" (SPI rápido)" if cab.spi_rapido else "")
    return np.asarray(sinal[inicio:fim], dtype=np.float64), fs, dica, rotulo


def _medir_todas(entradas, f0: float, q: float, freq_max: float | None) -> list[RespostaQuadrada]:
    return [medir_quadrada(sinal, fs, dica, f0, q, freq_max) for sinal, fs, dica, _ in entradas]


def _freq_menos_3db(f0: float, q: float) -> float:
    b = 1 / q ** 2 - 2
    return f0 * math.sqrt((-b + math.sqrt(b * b + 4)) / 2)


def _relatar(caminhos: list[Path], rotulos: list[str], medidas: list[RespostaQuadrada], ajustes: list[AjusteFase]) -> None:
    for caminho, rotulo, r in zip(caminhos, rotulos, medidas):
        fora = [f"{int(n)}: {m}" for n, m in zip(r.n, r.motivo) if m]
        log.info(f"{caminho.name} ({rotulo}): f₁ = {r.f1_hz:.4f} Hz, duty 50 ± {100 * r.duty_desvio:.3f} %, "
                 f"{int(r.usado.sum())} de {len(r)} harmônicos ímpares até {r.freq_hz[-1] / 1e3:.1f} kHz; SNR de "
                 f"{np.min(r.snr_db[r.usado]):.0f} a {np.max(r.snr_db[r.usado]):.0f} dB"
                 + (f"; fora: {', '.join(fora[:6])}{' ...' if len(fora) > 6 else ''}" if fora else ""))
    log.info("Ajuste do passa-baixa de 2ª ordem H(s) = K ω0² / (s² + (ω0/Q) s + ω0²):")
    for a in ajustes:
        log.info(f"  {a.nome:13s} f0 = {a.f0_hz:9.1f} ± {a.sigma_f0_hz:5.1f} Hz   Q = {a.q:.4f} ± {a.sigma_q:.4f}   "
                 f"−3 dB em {_freq_menos_3db(a.f0_hz, a.q) / 1e3:.2f} kHz   resíduos {a.residuo_db:.3f} dB e "
                 f"{a.residuo_graus:.3f}°   χ²red {a.chi2_reduzido:.2f} ({a.n_pontos} resíduos)")
    so_mag, so_fase = ajustes[1], ajustes[2]
    df0 = (so_fase.f0_hz - so_mag.f0_hz) / math.hypot(so_fase.sigma_f0_hz, so_mag.sigma_f0_hz)
    dq = (so_fase.q - so_mag.q) / math.hypot(so_fase.sigma_q, so_mag.sigma_q)
    if max(abs(df0), abs(dq)) <= 3:
        log.info(f"  A fase e a magnitude dão o mesmo filtro (f0 a {df0:+.1f} σ, Q a {dq:+.1f} σ): a cadeia se comporta "
                 "como um 2ª ordem de FASE MÍNIMA, e a fase do perfil pode vir do modelo ou da medida.")
    else:
        log.warning(f"  A fase e a magnitude NÃO dão o mesmo filtro (f0 a {df0:+.1f} σ, Q a {dq:+.1f} σ): há algo "
                    "além de um 2ª ordem de fase mínima (um polo ou zero a mais, ou um erro de medida). Use a fase "
                    "medida, não a do modelo.")


def _gravar_csv(caminho_csv: Path, caminhos: list[Path], medidas: list[RespostaQuadrada], f0: float, q: float) -> None:
    caminho_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS_CSV)
        w.writeheader()
        for caminho, r in zip(caminhos, medidas):
            absoluta = fase_absoluta(r, f0, q)
            for i in range(len(r)):
                w.writerow({
                    "arquivo": caminho.name, "fs_hz": f"{r.fs_hz:.3f}", "f1_hz": f"{r.f1_hz:.6f}",
                    "duty_desvio": f"{r.duty_desvio:.6f}", "n": int(r.n[i]), "freq_hz": f"{r.freq_hz[i]:.4f}",
                    "ganho_rel": f"{r.ganho_rel[i]:.8f}", "ganho_rel_db": f"{20 * math.log10(r.ganho_rel[i]):.5f}",
                    "sigma_db": f"{8.685889638 * r.sigma_ln_ganho[i]:.5f}",
                    "fase_rel_graus": f"{math.degrees(r.fase_rel_rad[i]):.4f}",
                    "fase_min_graus": f"{math.degrees(absoluta[i]):.4f}",
                    "sigma_graus": f"{math.degrees(r.sigma_fase_rad[i]):.4f}", "snr_db": f"{r.snr_db[i]:.1f}",
                    "contaminacao_db": "" if not math.isfinite(r.contaminacao_db[i]) else f"{r.contaminacao_db[i]:.1f}",
                    "usado": "sim" if r.usado[i] else "não", "motivo": r.motivo[i],
                })
    log.info(f"{sum(len(r) for r in medidas)} harmônico(s) gravado(s) em {caminho_csv}")


def montar_perfil_com_fase(base: dict, medidas: list[RespostaQuadrada], caminhos: list[Path], ajuste: AjusteFase,
                           k_baixa: float, ident: str) -> dict:
    """Perfil de sonda no formato de sempre (``pontos`` com ``freq_hz``/``ganho``), cada ponto com ``fase_rad`` e
    ``sigma_fase_rad``, e o bloco ``resposta_fase``. A magnitude é a relativa da quadrada escalada por K (a quadrada
    não mede o ganho absoluto); abaixo da menor frequência medida, os pontos do perfil base, com a fase do modelo."""
    f0, q = ajuste.f0_hz, ajuste.q
    candidatos = []                                   # (freq, ganho, fase, sigma_ln, sigma_fase)
    for r in medidas:
        a1 = abs(h_segunda_ordem(r.f1_hz, f0, q))
        absoluta = fase_absoluta(r, f0, q)
        for i in np.flatnonzero(r.usado):
            candidatos.append((float(r.freq_hz[i]), k_baixa * a1 * float(r.ganho_rel[i]), float(absoluta[i]),
                               float(r.sigma_ln_ganho[i]), float(r.sigma_fase_rad[i])))
    candidatos.sort()
    pontos: list[tuple] = []
    for c in candidatos:                              # frequências a menos de 0,3 % uma da outra: fica a mais exata
        if pontos and c[0] < pontos[-1][0] * 1.003:
            if c[4] < pontos[-1][4]:
                pontos[-1] = c
        else:
            pontos.append(c)
    menor = pontos[0][0]
    for p in sorted(base.get("pontos", []), key=lambda p: p["freq_hz"]):
        if p["freq_hz"] < menor / 1.003:
            fase = float(np.angle(h_segunda_ordem(p["freq_hz"], f0, q)))
            pontos.append((float(p["freq_hz"]), float(p["ganho"]), fase, 0.01 * float(p.get("desvio_pct", 0.0)), math.nan))
    pontos.sort()

    perfil = {k: v for k, v in base.items() if k not in ("pontos", "faixa_freq_valida_hz", "resposta_fase")}
    perfil["id"] = ident
    perfil["data_calibracao"] = date.today().isoformat()
    perfil["pontos"] = [
        {"freq_hz": round(f, 4), "ganho": round(g, 6), "n": 1, "desvio_pct": round(100 * s_ln, 4),
         "fase_rad": round(fase, 6), **({} if not math.isfinite(s_fase) else {"sigma_fase_rad": round(s_fase, 6)})}
        for f, g, fase, s_ln, s_fase in pontos]
    perfil["faixa_freq_valida_hz"] = [pontos[0][0], pontos[-1][0]]
    adc = dict(perfil.get("calibracao_adc", {}))
    adc["gerado_em"] = datetime.now(timezone.utc).isoformat()
    adc["n_pontos"] = len(pontos)
    resumo = resumir_resposta([PontoPerfil(f, g, 1, 0.0) for f, g, *_ in pontos])
    if resumo is not None:
        adc["resposta_conjunto"] = {
            "ganho_baixa_frequencia": round(resumo.ganho_baixa_frequencia, 6),
            "freq_menos3db_hz": None if resumo.freq_menos3db_hz is None else round(resumo.freq_menos3db_hz, 1),
            "inclinacao_db_por_oitava": None if resumo.inclinacao_db_oitava is None else round(resumo.inclinacao_db_oitava, 2),
            "ganho_na_maior_frequencia_db": round(resumo.ganho_final_db, 2),
        }
    perfil["calibracao_adc"] = adc
    perfil["resposta_fase"] = {
        "metodo": "onda quadrada: arg X_n − n·arg X_1 dos harmônicos ímpares (scripts/medir_fase.py)",
        "fase": "a menos de um atraso puro, supondo fase mínima (nenhum atraso puro na cadeia analógica)",
        "ganho": f"relativo a f1, escalado por K = {k_baixa:g}",
        "capturas": [{"arquivo": c.name, "fs_hz": round(r.fs_hz, 3), "f1_hz": round(r.f1_hz, 6),
                      "duty_desvio": round(r.duty_desvio, 6), "harmonicos_usados": int(r.usado.sum())}
                     for c, r in zip(caminhos, medidas)],
        "segunda_ordem": {"f0_hz": round(f0, 2), "sigma_f0_hz": round(ajuste.sigma_f0_hz, 2), "q": round(q, 5),
                          "sigma_q": round(ajuste.sigma_q, 5), "residuo_db": round(ajuste.residuo_db, 4),
                          "residuo_graus": round(ajuste.residuo_graus, 4)},
    }
    return perfil


def main(argv: list[str] | None = None) -> int:
    parser = montar_parser()
    args = parser.parse_args(argv)
    configurar_logging_cli()
    try:
        f0, q = _analisar_modelo(args.modelo_inicial)
        if args.saida_perfil is not None and args.perfil_base is None:
            raise ErroUso("--saida-perfil precisa de --perfil-base (a calibração do ADC e o --ganho vêm dele).")
        entradas, caminhos, rotulos = [], [], []
        for caminho in args.arquivos:
            sinal, fs, dica, rotulo = ler_quadrada(caminho, args)
            entradas.append((sinal, fs, dica, rotulo))
            caminhos.append(caminho)
            rotulos.append(rotulo)
        # 1ª passada com o modelo de partida; a 2ª, com o ajustado (desenrolar a fase, prever o aliasing e o duty)
        medidas = _medir_todas(entradas, f0, q, args.freq_max)
        conjunto = ajustar_segunda_ordem(medidas, f0_inicial=f0, q_inicial=q)
        medidas = _medir_todas(entradas, conjunto.f0_hz, conjunto.q, args.freq_max)
        ajustes = [ajustar_segunda_ordem(medidas, True, True, conjunto.f0_hz, conjunto.q),
                   ajustar_segunda_ordem(medidas, True, False, conjunto.f0_hz, conjunto.q),
                   ajustar_segunda_ordem(medidas, False, True, conjunto.f0_hz, conjunto.q)]
        _relatar(caminhos, rotulos, medidas, ajustes)
        melhor = ajustes[0]
        if args.csv is not None:
            _gravar_csv(args.csv, caminhos, medidas, melhor.f0_hz, melhor.q)
        if args.plot is not None:
            gerar_grafico_bode(medidas, rotulos, melhor.f0_hz, melhor.q, args.plot)
        if args.saida_perfil is not None:
            base = json.loads(args.perfil_base.read_text(encoding="utf-8"))
            carregar_perfil_sonda(args.perfil_base)          # valida o base
            k = args.ganho_baixa_frequencia
            if k is None:
                baixos = [p["ganho"] for p in base.get("pontos", []) if p["freq_hz"] < 1000]
                if not baixos:
                    raise ErroUso("o perfil base não tem pontos abaixo de 1 kHz: passe --ganho-baixa-frequencia.")
                k = float(np.median(baixos))
                log.info(f"K (ganho em baixa frequência) = {k:.5f}: a mediana de {len(baixos)} ponto(s) do perfil base "
                         "abaixo de 1 kHz.")
            ident = args.id or args.saida_perfil.stem
            perfil = montar_perfil_com_fase(base, medidas, caminhos, melhor, k, ident)
            gravar_perfil_validado(perfil, args.saida_perfil, len(perfil["pontos"]))
    except ErroUso as e:
        parser.error(str(e))
    except ErroSHAN as e:
        log.error(str(e))
        return 1
    return 0
