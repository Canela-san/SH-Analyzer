"""A âncora do método de um canal (``medir_fase.py --ancora``): a curva das quadradas num canal só tem a fase a menos
de um atraso (``arg Xₙ − n·arg X₁`` não o vê) e a magnitude a menos de K. Um perfil com a fase ABSOLUTA da mesma
cadeia (o da razão de dois canais, que vai até ~95 kHz) fixa os dois onde as curvas se sobrepõem: K por mínimos
quadrados em ln|H|, e o atraso por uma reta pela origem na diferença de fase. Acima da sobreposição, a curva de um
canal (até 190 kHz) segue com eles; o resíduo na sobreposição é a conferência entre os dois métodos.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace

import numpy as np

from .erros import ErroSHAN
from .fase_quadrada import RespostaCombinada
from .perfil_complexo import PerfilComplexo

log = logging.getLogger(__name__)

PONTOS_MINIMOS = 3
RESIDUO_MAXIMO_DB = 0.1         # acima disso (ou de RESIDUO_MAXIMO_GRAUS), os dois métodos discordam: aviso
RESIDUO_MAXIMO_GRAUS = 1.0


@dataclass
class AjusteAncora:
    ln_k: float                 # ln do ganho que leva a curva à âncora
    sigma_ln_k: float
    inclinacao: float           # rad/Hz: fase da âncora − fase da curva = inclinacao · f
    sigma_inclinacao: float
    residuo_db: float           # rms na sobreposição, depois do ajuste
    residuo_graus: float
    n_pontos: int
    de_hz: float
    ate_hz: float

    @property
    def atraso_s(self) -> float:
        """O atraso aparente que a curva de um canal tinha (positivo: ela atrasava a fase), já descontado."""
        return self.inclinacao / (2 * math.pi)


def ajustar_a_ancora(curva: RespostaCombinada, ancora: PerfilComplexo, ate_hz: float | None = None) -> AjusteAncora:
    f = curva.freq_hz
    sel = ancora.cobre(f) & (f <= (ate_hz if ate_hz is not None else math.inf))
    if int(np.sum(sel)) < PONTOS_MINIMOS:
        raise ErroSHAN(f"a curva e a âncora '{ancora.id}' se sobrepõem em {int(np.sum(sel))} faixa(s) da grade: são "
                       f"precisas {PONTOS_MINIMOS}.")
    fs = f[sel]
    g, fase, s_ln, s_fa = ancora.em(fs)
    w = 1 / (curva.sigma_ln[sel] ** 2 + s_ln ** 2 + 1e-12)
    d_ln = np.log(g) - curva.ln_ganho[sel]
    ln_k = float(np.sum(w * d_ln) / np.sum(w))
    # a diferença de fase cresce com f (o atraso): reduzida a ±π e desenrolada ao longo da grade (crescente)
    d_fa = np.unwrap(np.angle(np.exp(1j * (fase - curva.fase_rad[sel]))))
    wf = 1 / (curva.sigma_fase[sel] ** 2 + s_fa ** 2 + 1e-12)
    a = float(np.sum(wf * fs * d_fa) / np.sum(wf * fs * fs))
    return AjusteAncora(ln_k, 1 / math.sqrt(float(np.sum(w))), a, 1 / math.sqrt(float(np.sum(wf * fs * fs))),
                        float(20 / math.log(10) * np.sqrt(np.mean((d_ln - ln_k) ** 2))),
                        float(np.degrees(np.sqrt(np.mean((d_fa - a * fs) ** 2)))), int(np.sum(sel)), float(fs[0]),
                        float(fs[-1]))


def relatar_ancora(ident: str, a: AjusteAncora, curva: str = "da curva de um canal") -> None:
    texto = (f"Âncora '{ident}': {a.n_pontos} faixas em comum, de {a.de_hz:.0f} Hz a {a.ate_hz / 1e3:.1f} kHz; "
             f"K = {math.exp(a.ln_k):.5f} ± {a.sigma_ln_k * math.exp(a.ln_k):.5f}; atraso aparente {curva} "
             f"{a.atraso_s * 1e6:+.4f} ± {a.sigma_inclinacao / (2 * math.pi) * 1e6:.4f} µs (descontado); depois disso, "
             f"resíduo de {a.residuo_db:.4f} dB e {a.residuo_graus:.3f}° entre os dois métodos")
    if a.residuo_db > RESIDUO_MAXIMO_DB or a.residuo_graus > RESIDUO_MAXIMO_GRAUS:
        log.warning(texto + ": os métodos discordam além do esperado (o perfil da âncora é da mesma cadeia, na mesma "
                    "faixa e com o mesmo --ganho?).")
    else:
        log.info(texto)


def curva_ancorada(curva: RespostaCombinada, ajuste: AjusteAncora) -> RespostaCombinada:
    """A curva com K e o atraso da âncora (a incerteza deles somada em quadratura)."""
    return replace(curva, ln_ganho=curva.ln_ganho + ajuste.ln_k,
                   sigma_ln=np.hypot(curva.sigma_ln, ajuste.sigma_ln_k),
                   fase_rad=curva.fase_rad + ajuste.inclinacao * curva.freq_hz,
                   sigma_fase=np.hypot(curva.sigma_fase, ajuste.sigma_inclinacao * curva.freq_hz))


def pontos_combinados(curva: RespostaCombinada, ancora: PerfilComplexo, ate_hz: float) -> list[dict]:
    """Os pontos do perfil final: os da âncora na faixa dela até ``ate_hz``, e os da curva (já ancorada) fora disso."""
    pontos = []
    for p in ancora.dados["pontos"]:
        f = float(p["freq_hz"])
        if ancora.freq_hz[0] <= f <= ate_hz:
            pontos.append(dict(p))
    for f, ln, s_ln, fa, s_fa in zip(curva.freq_hz, curva.ln_ganho, curva.sigma_ln, curva.fase_rad, curva.sigma_fase):
        if f > ate_hz * 1.0001 or f < ancora.freq_hz[0] / 1.0001:
            pontos.append({"freq_hz": round(float(f), 4), "ganho": round(math.exp(float(ln)), 7), "n": 1,
                           "desvio_pct": round(100 * float(s_ln), 5), "fase_rad": round(float(fa), 7),
                           "sigma_fase_rad": round(float(s_fa), 7)})
    pontos.sort(key=lambda p: p["freq_hz"])
    return pontos
