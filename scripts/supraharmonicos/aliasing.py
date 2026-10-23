"""Imagens de aliasing identificadas por duas capturas do mesmo sinal em taxas diferentes.

O único anti-aliasing da cadeia é o passa-baixa interno do ADS8688 (2ª ordem, ~15 kHz). A 400 kS/s, uma imagem chega a
150 kHz só ~9 dB abaixo de um componente real de mesma amplitude (vinda de 250 kHz), e a 130 kHz, ~13 dB (de 270 kHz):
uma captura sozinha não diz se um pico é real ou uma imagem. Duas capturas do mesmo sinal em taxas diferentes dizem: um
componente de entrada em f aparece em ``dobrar(f, fs)`` em cada uma. Um real abaixo das duas Nyquist fica no mesmo
lugar; uma imagem muda de lugar, e o par de posições aponta a frequência de entrada. A amplitude bruta (antes da
correção da sonda) também tem de bater: o filtro do ADC age em f, antes da amostragem, então atenua igual nas duas.

Limites: as duas capturas não são simultâneas (o ADC é um só), então a emissão tem de ser estável entre elas; e
certas frequências caem no mesmo lugar nas duas taxas (com 400 e 320 kS/s, uma entrada em 360 kHz aparece em 40 kHz
nas duas, como uma real de 40 kHz): esses casos saem marcados como ambíguos, e uma 3ª taxa decide.

Depende de: ``espectro``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .espectro import calcular_espectro_welch, encontrar_picos_espectro


@dataclass(frozen=True)
class Pico:
    frequencia_hz: float
    amplitude_db: float


@dataclass
class Componente:
    """Um componente de entrada visto nas duas capturas (ou só numa, quando ``em_a``/``em_b`` é ``None``)."""

    frequencia_entrada_hz: float | None   # None: sem par na outra captura, a entrada não pôde ser deduzida
    em_a: Pico | None
    em_b: Pico | None
    real_em_a: bool = False               # a entrada está onde o pico aparece em A (não é imagem em A)
    real_em_b: bool = False
    ambiguas_hz: list[float] = field(default_factory=list)   # outras entradas que explicam o mesmo par
    amplitudes_batem: bool = True         # a diferença de amplitude entre A e B está dentro da tolerância

    @property
    def diferenca_db(self) -> float | None:
        if self.em_a is None or self.em_b is None:
            return None
        return self.em_a.amplitude_db - self.em_b.amplitude_db

    @property
    def diagnostico(self) -> str:
        if self.em_a is None or self.em_b is None:
            return "sem par na outra captura (abaixo do limiar lá, fora da faixa analisada ou intermitente)"
        if self.real_em_a and self.real_em_b:
            texto = "real"
        elif self.real_em_a:
            texto = "real em A; imagem em B"
        elif self.real_em_b:
            texto = "imagem em A; real em B"
        else:
            texto = f"imagem nas duas, de {self.frequencia_entrada_hz / 1e3:.2f} kHz"
        if not self.amplitudes_batem:
            texto += f" (as amplitudes diferem {abs(self.diferenca_db):.1f} dB: a emissão mudou entre as capturas?)"
        if self.ambiguas_hz:
            outras = ", ".join(f"{f / 1e3:.2f}" for f in self.ambiguas_hz)
            texto += f" -- AMBÍGUO: também seria a entrada em {outras} kHz (uma 3ª taxa decide)"
        return texto


def dobrar(f_hz: float, fs_hz: float) -> float:
    """Onde uma entrada em ``f_hz`` aparece numa captura a ``fs_hz``: entre 0 e fs/2."""
    resto = math.fmod(abs(f_hz), fs_hz)
    return fs_hz - resto if resto > fs_hz / 2 else resto


def entradas_possiveis(f_observada_hz: float, fs_hz: float, f_max_entrada_hz: float) -> list[float]:
    """Toda entrada até ``f_max_entrada_hz`` que aparece em ``f_observada_hz``: k·fs ± f (k = 0 é a própria f)."""
    candidatas = [f_observada_hz]
    k = 1
    while k * fs_hz - f_observada_hz <= f_max_entrada_hz:
        candidatas.append(k * fs_hz - f_observada_hz)
        if k * fs_hz + f_observada_hz <= f_max_entrada_hz:
            candidatas.append(k * fs_hz + f_observada_hz)
        k += 1
    return candidatas


def picos_do_sinal(sinal: np.ndarray, fs_hz: float, f_min_hz: float, f_max_hz: float, acima_do_piso_db: float,
                   resolucao_hz: float, distancia_minima_hz: float, janela: str = "hann",
                   kaiser_beta: float = 8.6) -> tuple[list[Pico], float]:
    """Picos do espectro médio (Welch, amplitude de tom) entre ``f_min_hz`` e ``f_max_hz`` que passam
    ``acima_do_piso_db`` da mediana do espectro nessa faixa (o piso: não depende da unidade nem da faixa do ADC).
    Devolve os picos e o piso, em dB."""
    freqs, amplitude_db, _ = calcular_espectro_welch(np.asarray(sinal, dtype=np.float64), fs_hz, janela, kaiser_beta,
                                                      resolucao_hz, 0.5, modo="tom")
    faixa = (freqs >= f_min_hz) & (freqs <= f_max_hz)
    if not np.any(faixa):
        return [], float("nan")
    piso = float(np.median(amplitude_db[faixa]))
    achados = encontrar_picos_espectro(freqs, amplitude_db, f_min_hz, f_max_hz, piso + acima_do_piso_db,
                                       distancia_minima_hz)
    return [Pico(p["frequencia_hz"], p["amplitude_db"]) for p in achados], piso


def _mais_proximo(picos: list[Pico], f_hz: float) -> int | None:
    if not picos:
        return None
    return int(np.argmin([abs(p.frequencia_hz - f_hz) for p in picos]))


def parear(picos_a: list[Pico], fs_a_hz: float, faixa_a: tuple[float, float],
           picos_b: list[Pico], fs_b_hz: float, faixa_b: tuple[float, float],
           tolerancia_hz: float, tolerancia_db: float, f_max_entrada_hz: float) -> list[Componente]:
    """Explica cada pico de A e de B por uma frequência de entrada.

    Para cada pico de A, cada entrada possível (k·fs_A ± f, até ``f_max_entrada_hz``) prevê onde ela apareceria em
    B; se B tem um pico ali (a menos de ``tolerancia_hz``), o par é uma hipótese. Entre as hipóteses, valem primeiro
    as de amplitudes que batem (a menos de ``tolerancia_db``) e, depois, a de entrada mais baixa (o filtro do ADC
    atenua as mais altas). Cada pico entra num par só. Outras entradas que explicam o mesmo par vão em
    ``ambiguas_hz``. ``faixa_a``/``faixa_b``: a faixa em que cada captura foi analisada (uma previsão fora dela não
    é procurada)."""
    hipoteses = []
    for i, a in enumerate(picos_a):
        for f_entrada in entradas_possiveis(a.frequencia_hz, fs_a_hz, f_max_entrada_hz):
            previsto_b = dobrar(f_entrada, fs_b_hz)
            if not faixa_b[0] - tolerancia_hz <= previsto_b <= faixa_b[1] + tolerancia_hz:
                continue
            j = _mais_proximo(picos_b, previsto_b)
            if j is None or abs(picos_b[j].frequencia_hz - previsto_b) > tolerancia_hz:
                continue
            # A entrada pelo lado de B (a candidata de B mais perto da de A), e a média das duas.
            pelo_b = min(entradas_possiveis(picos_b[j].frequencia_hz, fs_b_hz, f_max_entrada_hz + fs_b_hz),
                         key=lambda f: abs(f - f_entrada))
            diferenca = abs(a.amplitude_db - picos_b[j].amplitude_db)
            hipoteses.append((diferenca > tolerancia_db, f_entrada, i, j, 0.5 * (f_entrada + pelo_b)))
    hipoteses.sort(key=lambda h: (h[0], h[1]))

    usados_a: set[int] = set()
    usados_b: set[int] = set()
    componentes = []
    for amplitude_difere, _, i, j, f_entrada in hipoteses:
        if i in usados_a or j in usados_b:
            continue
        usados_a.add(i)
        usados_b.add(j)
        outras = sorted({h[4] for h in hipoteses if h[2] == i and h[3] == j and abs(h[4] - f_entrada) > tolerancia_hz})
        componentes.append(Componente(f_entrada, picos_a[i], picos_b[j],
                                      real_em_a=abs(f_entrada - picos_a[i].frequencia_hz) <= tolerancia_hz,
                                      real_em_b=abs(f_entrada - picos_b[j].frequencia_hz) <= tolerancia_hz,
                                      ambiguas_hz=outras, amplitudes_batem=not amplitude_difere))
    componentes += [Componente(None, a, None) for i, a in enumerate(picos_a) if i not in usados_a]
    componentes += [Componente(None, None, b) for j, b in enumerate(picos_b) if j not in usados_b]
    componentes.sort(key=lambda c: (c.frequencia_entrada_hz is None,
                                    c.frequencia_entrada_hz if c.frequencia_entrada_hz is not None
                                    else (c.em_a or c.em_b).frequencia_hz))
    return componentes


def entradas_ambiguas(fs_a_hz: float, fs_b_hz: float, f_max_hz: float, f_max_entrada_hz: float,
                      tolerancia_hz: float) -> list[tuple[float, float]]:
    """Os pares (onde aparece, entrada) em que uma entrada cai no MESMO lugar x nas duas taxas, com x abaixo de
    ``f_max_hz`` e das duas Nyquist: ali as duas capturas não separam a imagem de um componente real em x. Vêm de
    f = k_a·fs_a + x = k_b·fs_b − x (ou o contrário), isto é, f = (k_a·fs_a + k_b·fs_b)/2 e x = |k_a·fs_a − k_b·fs_b|/2.
    Serve para escolher a 2ª taxa, ou saber quando pedir uma 3ª."""
    nyquist = min(fs_a_hz, fs_b_hz) / 2
    achados = set()
    for k_a in range(int(2 * f_max_entrada_hz // fs_a_hz) + 2):
        for k_b in range(int(2 * f_max_entrada_hz // fs_b_hz) + 2):
            entrada = (k_a * fs_a_hz + k_b * fs_b_hz) / 2
            x = abs(k_a * fs_a_hz - k_b * fs_b_hz) / 2
            if entrada > f_max_entrada_hz or not 0 < x <= min(f_max_hz, nyquist) or entrada - x <= tolerancia_hz:
                continue
            if abs(dobrar(entrada, fs_a_hz) - x) <= tolerancia_hz and abs(dobrar(entrada, fs_b_hz) - x) <= tolerancia_hz:
                achados.add((round(x, 3), round(entrada, 3)))
    return sorted(achados)


LETRAS = "ABCDEFGH"


@dataclass
class ComponenteMulti:
    """Um componente de entrada visto em N >= 2 capturas (a 1ª é a referência dos pares)."""

    frequencia_entrada_hz: float | None
    picos: list[Pico | None]                 # um por captura; None = sem pico ali
    reais: list[bool]                        # o pico de cada captura está na própria entrada (não é imagem)
    ambiguas_hz: list[float] = field(default_factory=list)
    amplitudes_batem: bool = True
    taxas_discordam: bool = False            # os pares apontaram entradas diferentes (a emissão mudou?)

    @property
    def diagnostico(self) -> str:
        n = len(self.picos)
        presentes = [k for k, p in enumerate(self.picos) if p is not None]
        if self.frequencia_entrada_hz is None:
            return "sem par nas outras capturas (abaixo do limiar lá, fora da faixa analisada ou intermitente)"
        reais = [k for k in presentes if self.reais[k]]
        imagens = [k for k in presentes if not self.reais[k]]

        def letras(ks):
            return ", ".join(LETRAS[k] for k in ks)

        if not imagens:
            texto = "real"
        elif not reais:
            todas = len(presentes) == n
            onde = ("nas duas" if n == 2 else "em todas") if todas else f"em {letras(imagens)}"
            texto = f"imagem {onde}, de {self.frequencia_entrada_hz / 1e3:.2f} kHz"
        else:
            texto = f"real em {letras(reais)}; imagem em {letras(imagens)}"
        faltando = [k for k in range(n) if k not in presentes]
        if faltando:
            texto += f"; sem pico em {letras(faltando)}"
        if not self.amplitudes_batem:
            texto += " (as amplitudes diferem: a emissão mudou entre as capturas?)"
        if self.taxas_discordam:
            texto += " (as taxas apontam entradas diferentes: a emissão mudou?)"
        if self.ambiguas_hz:
            outras = ", ".join(f"{f / 1e3:.2f}" for f in self.ambiguas_hz)
            texto += f" -- AMBÍGUO: também seria a entrada em {outras} kHz (uma taxa a mais decide)"
        return texto


def parear_varias(picos: list[list[Pico]], fs_hz: list[float], faixas: list[tuple[float, float]],
                  tolerancia_hz: float, tolerancia_db: float, f_max_entrada_hz: float) -> list[ComponenteMulti]:
    """Pareia N >= 2 capturas: cada uma contra a 1ª (``parear``), e a entrada de cada pico da 1ª é a que TODOS os
    pares aceitam (a de cada par mais as ambíguas dele): uma 3ª taxa desfaz o que duas deixam ambíguo. Os picos das
    outras capturas que nenhum par usou saem sozinhos."""
    n = len(picos)
    pares = [parear(picos[0], fs_hz[0], faixas[0], picos[k], fs_hz[k], faixas[k], tolerancia_hz, tolerancia_db,
                    f_max_entrada_hz) for k in range(1, n)]
    usados: list[set[int]] = [set() for _ in range(n)]
    componentes = []
    for i, a in enumerate(picos[0]):
        hipoteses, nos_pares = [], []
        for comps in pares:
            comp = next((c for c in comps if c.em_a is a and c.em_b is not None), None)
            nos_pares.append(comp)
            if comp is not None:
                hipoteses.append([comp.frequencia_entrada_hz, *comp.ambiguas_hz])
        usados[0].add(i)
        if not hipoteses:
            componentes.append(ComponenteMulti(None, [a] + [None] * (n - 1), [False] * n))
            continue
        aceitas = sorted(f for f in hipoteses[0]
                         if all(any(abs(f - g) <= tolerancia_hz for g in outras) for outras in hipoteses[1:]))
        discordam = not aceitas
        if discordam:
            aceitas = sorted(hipoteses[0])
        f_entrada = aceitas[0]
        lista = [a] + [comp.em_b if comp is not None else None for comp in nos_pares]
        for k, comp in enumerate(nos_pares, start=1):
            if comp is not None:
                usados[k].add(next(j for j, p in enumerate(picos[k]) if p is comp.em_b))
        componentes.append(ComponenteMulti(
            f_entrada, lista, [p is not None and abs(f_entrada - p.frequencia_hz) <= tolerancia_hz for p in lista],
            ambiguas_hz=[f for f in aceitas[1:] if abs(f - f_entrada) > tolerancia_hz],
            amplitudes_batem=all(c.amplitudes_batem for c in nos_pares if c is not None),
            taxas_discordam=discordam))
    for k in range(1, n):
        for j, p in enumerate(picos[k]):
            if j not in usados[k]:
                componentes.append(ComponenteMulti(None, [p if m == k else None for m in range(n)], [False] * n))
    componentes.sort(key=lambda c: (c.frequencia_entrada_hz is None,
                                    c.frequencia_entrada_hz if c.frequencia_entrada_hz is not None
                                    else next(p for p in c.picos if p is not None).frequencia_hz))
    return componentes


def entradas_ambiguas_em_todas(fs_hz: list[float], f_max_hz: float, f_max_entrada_hz: float,
                               tolerancia_hz: float) -> list[tuple[float, float]]:
    """As posições (onde aparece, entrada) em que uma imagem cai no MESMO lugar em todas as taxas: ali nem o conjunto
    separa a imagem de um componente real. Com duas taxas, as de ``entradas_ambiguas``; cada taxa a mais elimina as
    que ela desloca."""
    candidatas = entradas_ambiguas(fs_hz[0], fs_hz[1], f_max_hz, f_max_entrada_hz, tolerancia_hz)
    return [(x, e) for x, e in candidatas if all(abs(dobrar(e, fs) - x) <= tolerancia_hz for fs in fs_hz[2:])]
