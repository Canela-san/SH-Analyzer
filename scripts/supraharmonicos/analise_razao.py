"""O modo de dois canais do ``medir_fase.py`` (``--canal-referencia``): a razão H_a / H_b por harmônico entre dois
canais capturados juntos, combinada numa grade e, com o perfil (com fase) do canal de referência e o shunt do laço,
a resposta absoluta do canal medido e o perfil dele com a fase.

Na sonda de corrente: o TC no canal a, a tensão num resistor do laço (pelo divisor) no canal b, ambos na faixa de
produção. A corrente no laço é a tensão no resistor (que o perfil de tensão converte) dividida pela impedância dele;
o TC enxerga N espiras dessa corrente::

    H_I(f) = razão(f) · (faixa_a / faixa_b) · (G_I / G_V) · Z(f) / N · H_V(f)

com G_I e G_V os ``--ganho`` nominais dos dois canais (o perfil é relativo a eles, como todo perfil). A fase de H_V
entra na de H_I, mas sai de novo em V·I*: para a potência, só a fase da razão importa, e ela é medida sem modelo.
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from .cabecalho import ler_cabecalho
from .calibracao_sonda import PontoPerfil, resumir_resposta
from .erros import ErroSHAN, ErroUso
from .escrita_perfil import gerar_grafico_curva, gravar_perfil_validado
from .fase_quadrada import Q_PADRAO, RespostaCombinada, combinar_em_grade
from .perfil_complexo import ImpedanciaShunt, PerfilComplexo, ler_perfil_complexo, ler_shunt, resistencia_pura
from .razao_quadrada import PontosCurva, RazaoQuadrada, medir_razao, pontos_da_razao, subtrair_diafonia

log = logging.getLogger(__name__)

F0_PLANO_HZ = 1e12              # a grade combina contra um modelo plano: a razão não tem modelo
DB = 20 / math.log(10)
COLUNAS_CSV_RAZAO = ["arquivo", "fs_hz", "f1_hz", "blocos", "n", "freq_hz", "amplitude_a_lsb", "amplitude_b_lsb",
                     "razao_db", "razao_graus", "sigma_db", "sigma_graus", "snr_a_db", "snr_b_db", "contaminacao_db",
                     "diafonia_db", "usado", "motivo", "h_db", "h_graus"]
COLUNAS_CSV_GRADE = ["freq_hz", "ganho_db", "sigma_db", "fase_graus", "sigma_graus", "harmonicos", "chi2_ganho",
                     "chi2_fase"]


@dataclass
class CapturaDupla:
    caminho: Path
    canal: int                      # o medido
    a: np.ndarray                   # o canal medido, em LSB
    b: np.ndarray                   # o de referência, em LSB
    fs_hz: float                    # por canal
    f_dica: float | None
    atraso_s: float                 # τ_a − τ_b
    faixa_a: float | None
    faixa_b: float | None
    rotulo: str


def ler_dois_canais(caminho: Path, args: argparse.Namespace, re_f1) -> CapturaDupla:
    cab = ler_cabecalho(caminho)
    if cab is None or not cab.crc32_valido:
        raise ErroSHAN(f"'{caminho.name}' sem cabeçalho válido: a taxa e os canais vêm dele.")
    nc = max(cab.num_canais, 1)
    canais = list(cab.lista_canais[:nc])
    ref = args.canal_referencia
    if ref not in canais:
        raise ErroSHAN(f"'{caminho.name}': o canal de referência {ref} não está na captura (canais {canais}).")
    canal = args.canal
    if canal is None:
        outros = [c for c in canais if c != ref]
        if len(outros) != 1:
            raise ErroUso(f"'{caminho.name}' tem os canais {canais}: diga qual é o medido com --canal.")
        canal = outros[0]
    if canal not in canais or canal == ref:
        raise ErroSHAN(f"'{caminho.name}': o canal {canal} não está na captura (canais {canais}), ou é o de referência.")
    fs_total = cab.frequencia_pru_hz or float(cab.frequencia_hz)
    fs = fs_total / nc
    pa, pb = canais.index(canal), canais.index(ref)
    # a varredura é em ordem crescente: o canal na posição p é amostrado p / (taxa total) depois do primeiro
    atraso = (pa - pb) / fs_total if args.atraso_entre_canais_us is None else args.atraso_entre_canais_us * 1e-6
    bruto = np.memmap(caminho, dtype="<u2", mode="r", offset=cab.tamanho_cabecalho)
    inicio = int(round(args.inicio_ms * 1e-3 * fs))
    n = len(bruto) // nc
    fim = n if args.max_segundos is None else min(n, inicio + int(args.max_segundos * fs))
    if fim - inicio < 1000:
        raise ErroSHAN(f"'{caminho.name}': curta demais ({fim - inicio} amostras por canal).")
    dica = args.f1
    if dica is None:
        m = re_f1.search(cab.descricao or "")
        dica = float(m.group(1)) if m else None
    faixas = cab.faixa_adc_total_v_por_canal or ()
    faixa_a = float(faixas[pa]) if len(faixas) > pa else None
    faixa_b = float(faixas[pb]) if len(faixas) > pb else None
    rotulo = f"{fs / 1e3:g} kS/s por canal" + (" (SPI rápido)" if cab.spi_rapido else "")
    a = np.asarray(bruto[pa::nc][inicio:fim], dtype=np.float64)
    b = np.asarray(bruto[pb::nc][inicio:fim], dtype=np.float64)
    return CapturaDupla(caminho, canal, a, b, fs, dica, atraso, faixa_a, faixa_b, rotulo)


def _medir(c: CapturaDupla, args: argparse.Namespace, modelo: tuple[float, float, float]) -> RazaoQuadrada:
    try:
        return medir_razao(c.a, c.b, c.fs_hz, c.f_dica, c.atraso_s, args.freq_max, args.amostras_por_bloco,
                           args.piso_sistematico, args.piso_sistematico, modelo, modelo)
    except ErroSHAN as e:
        raise ErroSHAN(f"'{c.caminho.name}': {e}") from None


def _validar(args: argparse.Namespace) -> None:
    if args.canal is not None and args.canal == args.canal_referencia:
        raise ErroUso("--canal e --canal-referencia são o mesmo canal.")
    if args.resistencia is not None and args.shunt is not None:
        raise ErroUso("--resistencia e --shunt dizem a mesma coisa (a impedância do resistor do laço): use um só.")
    if args.perfil_referencia is not None and args.resistencia is None and args.shunt is None:
        raise ErroUso("--perfil-referencia dá a tensão no resistor do laço; a corrente sai dela pela impedância dele: "
                      "passe --resistencia OHMS ou --shunt shunt.csv (o do medir_shunt.py).")
    if args.saida_perfil is not None and (args.perfil_referencia is None or args.ganho is None):
        raise ErroUso("--saida-perfil no modo de dois canais pede --perfil-referencia (o perfil com fase do canal de "
                      "referência), --resistencia ou --shunt, e --ganho (o nominal do canal medido).")
    if args.espiras < 1:
        raise ErroUso("--espiras precisa ser 1 ou mais.")
    incompativeis = [nome for nome, valor in (("--entrada", args.entrada), ("--ancora", args.ancora),
                                               ("--perfil-base", args.perfil_base),
                                               ("--ganho-baixa-frequencia", args.ganho_baixa_frequencia))
                     if valor is not None]
    if args.passa_alta:
        incompativeis.append("--passa-alta")
    if args.polo != "auto":
        incompativeis.append("--polo")
    if incompativeis:
        raise ErroUso(f"{', '.join(incompativeis)} não vale(m) com --canal-referencia (a razão de dois canais não tem "
                      "modelo, costura nem referência externa).")


def _relatar_captura(c: CapturaDupla, r: RazaoQuadrada) -> None:
    u = r.usado
    fora = [f"{int(n)}: {m}" for n, m in zip(r.n, r.motivo) if m]
    texto = (f"{c.caminho.name} ({c.rotulo}): f₁ = {r.f1_hz:.4f} Hz, {r.blocos} blocos, {int(u.sum())} de {len(r)} "
             f"harmônicos ímpares até {r.freq_hz[-1] / 1e3:.1f} kHz")
    if np.any(u):
        texto += (f"; SNR de {np.min(r.snr_a_db[u]):.0f} a {np.max(r.snr_a_db[u]):.0f} dB no canal medido e de "
                  f"{np.min(r.snr_b_db[u]):.0f} a {np.max(r.snr_b_db[u]):.0f} na referência")
    if fora:
        texto += f"; fora: {', '.join(fora[:6])}{' ...' if len(fora) > 6 else ''}"
    (log.info if np.any(u) else log.warning)(texto)


def _relatar_diafonia(c: CapturaDupla, antes: RazaoQuadrada, depois: RazaoQuadrada) -> None:
    u = depois.usado
    if not np.any(u) or depois.diafonia is None:
        return
    rel = np.abs(depois.diafonia[u]) / np.maximum(np.abs(antes.razao[u]), 1e-300)
    i = int(np.argmax(rel))
    log.info(f"  diafonia subtraída de {c.caminho.name}: até {DB * math.log(max(rel[i], 1e-300)):.1f} dB da razão "
             f"({100 * rel[i]:.3f} %), em {depois.freq_hz[u][i] / 1e3:.1f} kHz")


def _grade(curvas: list[PontosCurva], por_decada: int) -> RespostaCombinada:
    return combinar_em_grade(curvas, F0_PLANO_HZ, Q_PADRAO, por_decada)


def _comparar_taxas(medidas: list[tuple[CapturaDupla, RazaoQuadrada]], curvas: list[PontosCurva], por_decada: int) -> None:
    grupos: dict[int, list[PontosCurva]] = {}
    for (c, _), curva in zip(medidas, curvas):
        if len(curva.freq_hz):
            grupos.setdefault(round(c.fs_hz), []).append(curva)
    if len(grupos) != 2:
        return
    (fs_a, ga), (fs_b, gb) = sorted(grupos.items())
    ca, cb = _grade(ga, por_decada), _grade(gb, por_decada)
    lo, hi = max(ca.freq_hz[0], cb.freq_hz[0]), min(ca.freq_hz[-1], cb.freq_hz[-1])
    sel = (ca.freq_hz >= lo) & (ca.freq_hz <= hi)
    if np.sum(sel) < 3:
        return
    lf = np.log(ca.freq_hz[sel])
    d_ln = ca.ln_ganho[sel] - np.interp(lf, np.log(cb.freq_hz), cb.ln_ganho)
    d_fa = np.angle(np.exp(1j * (ca.fase_rad[sel] - np.interp(lf, np.log(cb.freq_hz), cb.fase_rad))))
    log.info(f"{fs_a / 1e3:g} × {fs_b / 1e3:g} kS/s por canal: diferença rms de {DB * np.sqrt(np.mean(d_ln ** 2)):.4f} dB "
             f"e {math.degrees(np.sqrt(np.mean(d_fa ** 2))):.3f}° em {int(np.sum(sel))} faixas em comum (a cadeia é "
             "analógica: deveria ser só o ruído)")


def _gravar_csv_grade(caminho: Path, c: RespostaCombinada, descricao: str) -> None:
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS_CSV_GRADE)
        w.writeheader()
        for i in range(len(c.freq_hz)):
            w.writerow({"freq_hz": f"{c.freq_hz[i]:.3f}", "ganho_db": f"{DB * c.ln_ganho[i]:.5f}",
                        "sigma_db": f"{DB * c.sigma_ln[i]:.5f}", "fase_graus": f"{math.degrees(c.fase_rad[i]):.4f}",
                        "sigma_graus": f"{math.degrees(c.sigma_fase[i]):.4f}", "harmonicos": int(c.pontos[i]),
                        "chi2_ganho": f"{c.chi2_ln[i]:.3f}", "chi2_fase": f"{c.chi2_fase[i]:.3f}"})
    log.info(f"Grade ({descricao}, {len(c.freq_hz)} faixas) gravada em {caminho}")


def _gravar_csv(caminho: Path, medidas: list[tuple[CapturaDupla, RazaoQuadrada]], escala_v: list[float],
                absolutos: list[tuple[np.ndarray, np.ndarray] | None]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS_CSV_RAZAO)
        w.writeheader()
        for (c, r), escala, absoluto in zip(medidas, escala_v, absolutos):
            valor = r.razao * escala
            for i in range(len(r)):
                vaz = "" if r.diafonia is None else f"{DB * math.log(max(abs(r.diafonia[i]) / max(abs(r.razao[i]), 1e-300), 1e-300)):.1f}"
                h_db = h_gr = ""
                if absoluto is not None:
                    h_db, h_gr = f"{DB * absoluto[0][i]:.5f}", f"{math.degrees(absoluto[1][i]):.4f}"
                w.writerow({
                    "arquivo": c.caminho.name, "fs_hz": f"{r.fs_hz:.3f}", "f1_hz": f"{r.f1_hz:.6f}", "blocos": r.blocos,
                    "n": int(r.n[i]), "freq_hz": f"{r.freq_hz[i]:.4f}", "amplitude_a_lsb": f"{r.amplitude_a[i]:.5f}",
                    "amplitude_b_lsb": f"{r.amplitude_b[i]:.5f}",
                    "razao_db": f"{DB * math.log(max(abs(valor[i]), 1e-300)):.5f}",
                    "razao_graus": f"{math.degrees(np.angle(valor[i])):.4f}", "sigma_db": f"{DB * r.sigma_ln[i]:.5f}",
                    "sigma_graus": f"{math.degrees(r.sigma_fase[i]):.4f}", "snr_a_db": f"{r.snr_a_db[i]:.1f}",
                    "snr_b_db": f"{r.snr_b_db[i]:.1f}",
                    "contaminacao_db": "" if not math.isfinite(r.contaminacao_db[i]) else f"{r.contaminacao_db[i]:.1f}",
                    "diafonia_db": vaz, "usado": "sim" if r.usado[i] else "não", "motivo": r.motivo[i],
                    "h_db": h_db, "h_graus": h_gr,
                })
    log.info(f"{sum(len(r) for _, r in medidas)} harmônico(s) gravado(s) em {caminho}")


def montar_perfil_da_razao(combinada: RespostaCombinada, razao: RespostaCombinada,
                           medidas: list[tuple[CapturaDupla, RazaoQuadrada]], referencia: PerfilComplexo,
                           shunt: ImpedanciaShunt, args: argparse.Namespace, faixa_a: float | None,
                           faixa_b: float | None, ident: str) -> dict:
    """O perfil do canal medido: um ponto por faixa da grade (|H| relativo ao --ganho dele, a fase e as σ), mais o
    bloco ``resposta_fase`` com o método, a referência, o atraso entre os canais e a razão medida (para a correção de
    V·I, que só precisa dela)."""
    pontos = [{"freq_hz": round(float(f), 4), "ganho": round(math.exp(float(ln)), 7), "n": 1,
               "desvio_pct": round(100 * float(s_ln), 5), "fase_rad": round(float(fa), 7),
               "sigma_fase_rad": round(float(s_fa), 7)}
              for f, ln, s_ln, fa, s_fa in zip(combinada.freq_hz, combinada.ln_ganho, combinada.sigma_ln,
                                                 combinada.fase_rad, combinada.sigma_fase)]
    adc: dict = {"formato": "uint16", "ganho": {"sonda": args.ganho},
                 "modo_referencia": f"razão de dois canais simultâneos (canal de referência com o perfil "
                                    f"'{referencia.id}'; shunt {shunt.origem}; {args.espiras} espira(s))",
                 "gerado_em": datetime.now(timezone.utc).isoformat(), "n_pontos": len(pontos)}
    if faixa_a is not None:
        adc["faixa_v"] = {"sonda": faixa_a}
        adc["faixa_v_confiavel"] = {"sonda": True}
    resumo = resumir_resposta([PontoPerfil(p["freq_hz"], p["ganho"], 1, 0.0) for p in pontos])
    if resumo is not None:
        adc["resposta_conjunto"] = {
            "ganho_baixa_frequencia": round(resumo.ganho_baixa_frequencia, 6),
            "freq_menos3db_hz": None if resumo.freq_menos3db_hz is None else round(resumo.freq_menos3db_hz, 1),
            "inclinacao_db_por_oitava": None if resumo.inclinacao_db_oitava is None else round(resumo.inclinacao_db_oitava, 2),
            "ganho_na_maior_frequencia_db": round(resumo.ganho_final_db, 2),
        }
    return {
        "id": ident,
        "tipo": "resposta_frequencia",
        "data_calibracao": date.today().isoformat(),
        "calibrado_com": "cadeia completa SH-Analyzer (sonda + frontend + ADS8688), pela razão com um canal de "
                         "referência capturado junto",
        "calibracao_adc": adc,
        "faixa_freq_valida_hz": [pontos[0]["freq_hz"], pontos[-1]["freq_hz"]],
        "pontos": pontos,
        "resposta_fase": {
            "metodo": "razão de dois canais capturados juntos: X_a/X_b de cada harmônico ímpar, média coerente por "
                      "blocos, sem o atraso entre os canais, combinada numa grade logarítmica (scripts/medir_fase.py "
                      "--canal-referencia)",
            "fase": "absoluta: a da razão (medida, sem modelo nem fase mínima) mais a do perfil de referência e a do "
                    "shunt; em V·I* a do perfil de referência se cancela",
            "ganho": "H = razão · (faixa_a/faixa_b) · (G/G_ref) · Z / N · H_ref",
            "referencia": {"perfil": referencia.id, "canal": args.canal_referencia, "faixa_v": faixa_b,
                           "ganho_nominal": _ganho_da_referencia(referencia, args)},
            "canal": medidas[0][0].canal,
            "shunt": shunt.origem,
            "espiras": args.espiras,
            "atraso_entre_canais_s": sorted({round(c.atraso_s, 12) for c, _ in medidas}),
            "diafonia_subtraida": bool(args.diafonia),
            "capturas": [{"arquivo": c.caminho.name, "fs_hz": round(r.fs_hz, 3), "f1_hz": round(r.f1_hz, 6),
                          "blocos": r.blocos, "harmonicos_usados": int(r.usado.sum())} for c, r in medidas],
            "razao": [{"freq_hz": round(float(f), 4), "modulo": float(f"{math.exp(float(ln)):.8g}"),
                       "fase_rad": round(float(fa), 7)}
                      for f, ln, fa in zip(razao.freq_hz, razao.ln_ganho, razao.fase_rad)],
        },
    }


def _ganho_da_referencia(referencia: PerfilComplexo, args: argparse.Namespace) -> float:
    g = args.ganho_referencia if args.ganho_referencia is not None else referencia.ganho_nominal
    if g is None:
        raise ErroUso(f"o perfil '{referencia.id}' não diz o --ganho com que foi gerado: passe --ganho-referencia.")
    return float(g)


def executar_razao(args: argparse.Namespace, re_f1, modelo: tuple[float, float, float]) -> None:
    """O modo de dois canais inteiro: mede, subtrai a diafonia, relata, combina e grava."""
    _validar(args)
    capturas = [ler_dois_canais(c, args, re_f1) for c in args.arquivos]
    for nome, valores in (("medido", {c.faixa_a for c in capturas}), ("de referência", {c.faixa_b for c in capturas})):
        if len(valores) > 1:
            raise ErroUso(f"as capturas têm o canal {nome} em faixas diferentes do ADC "
                          f"({', '.join(f'{v:g} V' for v in sorted(v for v in valores if v is not None))}): "
                          "analise cada faixa separadamente.")
    faixa_a, faixa_b = capturas[0].faixa_a, capturas[0].faixa_b
    escala_v = (faixa_a / faixa_b) if faixa_a and faixa_b else 1.0
    if len({c.canal for c in capturas}) > 1:
        raise ErroUso("as capturas têm o canal medido em canais diferentes: diga qual é com --canal.")
    canal = capturas[0].canal
    log.info(f"Dois canais: o {canal} ÷ o {args.canal_referencia} "
             f"(atraso entre eles descontado: {', '.join(f'{c * 1e6:+.4f}' for c in sorted({c.atraso_s for c in capturas}))} µs)")
    medidas = [(c, _medir(c, args, modelo)) for c in capturas]
    if args.diafonia:
        vazamentos = []
        for caminho in args.diafonia:
            c = ler_dois_canais(caminho, args, re_f1)
            vazamentos.append(_medir(c, args, modelo))
        subtraidas = []
        for c, r in medidas:
            nova = subtrair_diafonia(r, vazamentos)
            _relatar_diafonia(c, r, nova)
            subtraidas.append((c, nova))
        medidas = subtraidas
    for c, r in medidas:
        _relatar_captura(c, r)
    if not any(np.any(r.usado) for _, r in medidas):
        raise ErroSHAN("nenhum harmônico passou nos critérios em nenhuma captura (veja os motivos acima).")

    curvas_razao = [pontos_da_razao(r, escala_v) for _, r in medidas]
    razao = _grade([c for c in curvas_razao if len(c.freq_hz)], args.por_decada)
    _comparar_taxas(medidas, curvas_razao, args.por_decada)
    log.info(f"Razão (V no pino do canal medido ÷ V no da referência): {len(razao.freq_hz)} faixas de "
             f"{razao.freq_hz[0]:.0f} Hz a {razao.freq_hz[-1] / 1e3:.1f} kHz; incerteza mediana "
             f"{DB * np.median(razao.sigma_ln):.4f} dB e {math.degrees(np.median(razao.sigma_fase)):.3f}°; χ² mediano "
             f"{np.nanmedian(razao.chi2_ln):.2f} (ganho) e {np.nanmedian(razao.chi2_fase):.2f} (fase)")

    combinada, curvas, absolutos = razao, curvas_razao, [None] * len(medidas)
    referencia = shunt = None
    if args.perfil_referencia is not None:
        referencia = ler_perfil_complexo(args.perfil_referencia)
        shunt = resistencia_pura(args.resistencia) if args.resistencia is not None else ler_shunt(args.shunt)
        if referencia.faixa_v is not None and faixa_b is not None and abs(referencia.faixa_v - faixa_b) > 1e-3:
            log.warning(f"O perfil '{referencia.id}' é da faixa {referencia.faixa_v:g} V, e o canal de referência "
                        f"está em {faixa_b:g} V: a resposta do ADC pode mudar com a faixa.")
        ganho_ref = _ganho_da_referencia(referencia, args)
        ganho = args.ganho if args.ganho is not None else ganho_ref
        if args.ganho is None:
            log.info(f"Sem --ganho: a resposta absoluta sai relativa ao --ganho da referência ({ganho_ref:g}).")
        curvas, absolutos = [], []
        for _, r in medidas:
            fora = ~referencia.cobre(r.freq_hz)
            if np.any(fora & r.usado):
                log.warning(f"{int(np.sum(fora & r.usado))} harmônico(s) fora da faixa do perfil '{referencia.id}' "
                            f"({referencia.freq_hz[0]:.0f} Hz a {referencia.freq_hz[-1] / 1e3:.1f} kHz): ficam de fora.")
                r.usado = r.usado & ~fora
                r.motivo = [m or ("fora do perfil de referência" if fo else "") for m, fo in zip(r.motivo, fora)]
            g_ref, fase_ref, s_ln_ref, s_fa_ref = referencia.em(r.freq_hz)
            z, s_ln_z, s_fa_z = shunt.em(r.freq_hz)
            escala = escala_v * (ganho / ganho_ref) * z / args.espiras * g_ref
            curvas.append(pontos_da_razao(r, escala, fase_ref, np.hypot(s_ln_ref, s_ln_z), np.hypot(s_fa_ref, s_fa_z)))
            valor = r.razao * escala
            absolutos.append((np.log(np.maximum(np.abs(valor), 1e-300)), np.angle(valor) + fase_ref))
        combinada = _grade([c for c in curvas if len(c.freq_hz)], args.por_decada)
        baixos = combinada.ln_ganho[combinada.freq_hz < 1000]
        k = math.exp(float(np.median(baixos))) if len(baixos) else math.exp(float(combinada.ln_ganho[0]))
        texto = (f"Resposta absoluta do canal medido (÷ {referencia.id}, shunt {shunt.origem}, {args.espiras} "
                 f"espira(s)): K (abaixo de 1 kHz) = {k:.5f}; incerteza mediana {DB * np.median(combinada.sigma_ln):.4f} dB "
                 f"e {math.degrees(np.median(combinada.sigma_fase)):.3f}°")
        if 0.7 <= k <= 1.3:
            log.info(texto)
        else:
            log.warning(texto + ": longe de 1, confira o --ganho, as --espiras e o shunt.")

    if args.csv is not None:
        _gravar_csv(args.csv, medidas, [escala_v] * len(medidas), absolutos)
        _gravar_csv_grade(args.csv.with_name(args.csv.stem + "_grade.csv"), combinada,
                          "resposta absoluta" if referencia is not None else "razão")
        if referencia is not None:
            _gravar_csv_grade(args.csv.with_name(args.csv.stem + "_razao.csv"), razao, "razão")
    if args.plot is not None:
        titulo = (f"Canal {canal} pela razão com o canal {args.canal_referencia} ({referencia.id})"
                  if referencia is not None else f"Razão entre os canais ({canal} ÷ {args.canal_referencia})")
        gerar_grafico_curva([cv for cv in curvas], combinada, [c.rotulo for c, _ in medidas], args.plot,
                            titulo + f"\n{len(medidas)} capturas, fase absoluta", "Ganho (dB)")
    if args.saida_perfil is not None:
        ident = args.id or args.saida_perfil.stem
        perfil = montar_perfil_da_razao(combinada, razao, medidas, referencia, shunt, args, faixa_a, faixa_b, ident)
        gravar_perfil_validado(perfil, args.saida_perfil, len(perfil["pontos"]))
