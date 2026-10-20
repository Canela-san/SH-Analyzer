#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "numpy>=1.20",
#     "scipy>=1.15.3",
#     "matplotlib>=3.10.9",
# ]
# ///
r"""gerar_figuras.py -- todas as figuras do relatório (e, depois, do artigo) do SH-Analyzer.

Cada figura é uma função registrada com ``@figura("nome")``. Todas passam pelo MESMO :class:`Estilo`
(fonte do documento via LaTeX, tamanhos em pontos, largura exata, paleta, grade), então ficam padronizadas
entre si e já saem no tamanho final. No documento, inclua SEM escalar, senão as fontes deixam de bater
com as do texto::

    \includegraphics{figuras/perfil_cadeia_tensao.pdf}     % sem width=...
    \input{figuras/perfil_cadeia_tensao.tex}                % macros com os números (siunitx >= 3)

Uso (na raiz do repositório)::

    uv run relatorio/gerar_figuras.py                                  # todas as figuras
    uv run relatorio/gerar_figuras.py perfil_cadeia_tensao --png       # uma só, com prévia PNG
    uv run relatorio/gerar_figuras.py --formato artigo --idioma en     # coluna de artigo, em inglês
    uv run relatorio/gerar_figuras.py --listar

Saída em ``relatorio/figuras/``: ``<nome>.pdf`` (vetorial) e, quando a figura calcula algo, ``<nome>.tex`` com
os resultados como macros siunitx -- um número citado no texto nunca fica desatualizado em relação à figura.
Os dados vêm do resto do projeto (perfis em ``scripts/sondas/``, capturas, pacote ``supraharmonicos``):
nada é copiado à mão para cá.

Para acrescentar uma figura: escreva ``def minha_figura(estilo) -> Resultado`` com ``@figura("nome")``,
crie a figura com ``estilo.nova_figura(...)``, use as cores de ``COR`` e os textos de ``estilo.t(...)``
(acrescente as chaves em ``TEXTOS``, nos dois idiomas) e formate números com ``estilo.num``/``estilo.qty``.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # só arquivos, nunca janela

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.ticker import FuncFormatter, LogFormatterMathtext, LogLocator, MaxNLocator, MultipleLocator  # noqa: E402
from scipy.optimize import curve_fit  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

from supraharmonicos.registro import configurar_logging_cli  # noqa: E402
from supraharmonicos.sonda import SONDAS_DIR_PADRAO, carregar_perfil_sonda  # noqa: E402

# Filho do logger do pacote: herda o formato de console de configurar_logging_cli (stdout/stderr, "Aviso: ").
log = logging.getLogger("supraharmonicos.relatorio")

PASTA_FIGURAS = Path(__file__).resolve().parent / "figuras"
CM = 1 / 2.54   # polegadas por centímetro (o matplotlib mede figuras em polegadas)


# =====================================================================================================
# Estilo comum: formato da página, idioma, fontes e paleta
# =====================================================================================================
@dataclass(frozen=True)
class Formato:
    """Onde a figura vai morar. ``largura_cm`` é a largura FINAL da figura no documento."""
    largura_cm: float
    fonte_pt: float          # rótulos dos eixos e legenda
    fonte_ticks_pt: float    # números dos eixos
    marcador_pt: float       # diâmetro dos pontos medidos
    linha_pt: float          # curvas


FORMATOS = {
    # Relatório em A4 com margens de 2,5 a 3 cm (\textwidth ~ 15,9 a 16 cm): figura de 15 cm, texto ~ \small.
    "relatorio": Formato(largura_cm=15.0, fonte_pt=10.0, fonte_ticks_pt=9.0, marcador_pt=3.6, linha_pt=1.2),
    # Uma coluna de artigo IEEE (3,5 in = 8,89 cm); 8 pt é o mínimo legível pedido por essas revistas.
    "artigo": Formato(largura_cm=8.89, fonte_pt=8.0, fonte_ticks_pt=7.0, marcador_pt=2.8, linha_pt=1.0),
}

# Paleta qualitativa de Paul Tol ("bright"), segura para daltonismo e legível em P&B. As cores marcam
# IDENTIDADE (medido x modelo); o texto fica sempre em TINTA.
COR = {
    "tinta": "#222222",       # texto, eixos e dados medidos
    "secundaria": "#666666",  # anotações
    "grade": "#DDDDDD",       # grade: linha fina e contínua, um tom acima do fundo
    "modelo": "#4477AA",      # curvas ajustadas/teóricas
    "destaque": "#EE6677",    # reservado para o 2º conjunto de dados de uma figura
    "terceira": "#228833",
}

TEXTOS = {
    "pt": {
        "frequencia": "Frequência (Hz)",
        "ganho_norm": "Ganho normalizado (dB)",
        "residuo": "Resíduo (dB)",
        "medido": "Medido",
        "ajuste_2a": "Ajuste: passa-baixa de 2ª ordem",
    },
    "en": {
        "frequencia": "Frequency (Hz)",
        "ganho_norm": "Normalized gain (dB)",
        "residuo": "Residual (dB)",
        "medido": "Measured",
        "ajuste_2a": "Fit: 2nd-order low-pass",
    },
}


@dataclass
class Estilo:
    formato: Formato
    idioma: str
    usar_latex: bool

    def aplicar(self) -> None:
        f = self.formato
        marcador_decimal = "{,}" if self.idioma == "pt" else "."
        preambulo = [   # o mesmo que o documento deve carregar, para os números e as fontes baterem
            r"\usepackage[T1]{fontenc}",
            r"\usepackage{lmodern}",
            r"\usepackage{amsmath}",
            r"\usepackage{siunitx}",
            # "{,}" com UM par de chaves: com dois, o \qty trata a vírgula como pontuação e sai "17, 3 kHz".
            rf"\sisetup{{output-decimal-marker={marcador_decimal}, group-minimum-digits=4}}",
        ]
        plt.rcdefaults()
        plt.rcParams.update({
            "text.usetex": self.usar_latex,
            "text.latex.preamble": "\n".join(preambulo),
            "font.family": "serif",
            "font.serif": ["Latin Modern Roman", "Computer Modern Roman", "DejaVu Serif"],
            "mathtext.fontset": "cm",
            "font.size": f.fonte_pt,
            "axes.labelsize": f.fonte_pt,
            "legend.fontsize": f.fonte_ticks_pt,
            "xtick.labelsize": f.fonte_ticks_pt,
            "ytick.labelsize": f.fonte_ticks_pt,
            "axes.unicode_minus": True,
            "axes.formatter.use_mathtext": True,
            "axes.edgecolor": COR["tinta"],
            "axes.labelcolor": COR["tinta"],
            "axes.linewidth": 0.6,
            "axes.grid": True,
            "axes.grid.which": "major",
            "axes.axisbelow": True,
            "grid.color": COR["grade"],
            "grid.linewidth": 0.4,
            "grid.linestyle": "-",
            "xtick.color": COR["tinta"],
            "ytick.color": COR["tinta"],
            "xtick.direction": "in",
            "ytick.direction": "in",
            "xtick.top": True,
            "ytick.right": True,
            "xtick.major.width": 0.6,
            "ytick.major.width": 0.6,
            "xtick.minor.width": 0.4,
            "ytick.minor.width": 0.4,
            "xtick.major.size": 3.0,
            "ytick.major.size": 3.0,
            "xtick.minor.size": 1.6,
            "ytick.minor.size": 1.6,
            "lines.linewidth": f.linha_pt,
            "lines.markersize": f.marcador_pt,
            "legend.frameon": True,
            "legend.framealpha": 0.92,
            "legend.edgecolor": COR["grade"],
            "legend.fancybox": False,
            "legend.borderpad": 0.4,
            "legend.handlelength": 2.4,
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "pdf.fonttype": 42,       # fontes embutidas como TrueType (exigência comum de revistas) quando sem LaTeX
            "savefig.transparent": False,
        })

    def t(self, chave: str) -> str:
        return TEXTOS[self.idioma][chave]

    def nova_figura(self, proporcao: float, **kwargs):
        """Figura na largura exata do formato; ``proporcao`` = altura / largura. Layout restrito (constrained):
        o tamanho do arquivo é o pedido, nada é recortado depois."""
        largura = self.formato.largura_cm * CM
        return plt.figure(figsize=(largura, largura * proporcao), layout="constrained", **kwargs)

    # ---- números no idioma do documento (vírgula decimal em português) ----------------------------
    def num(self, valor: float, casas: int) -> str:
        texto = f"{valor:.{casas}f}"
        if self.usar_latex:
            return rf"\num{{{texto}}}"
        texto = texto.replace("-", "−")
        return texto.replace(".", ",") if self.idioma == "pt" else texto

    def qty(self, valor: float, casas: int, unidade_latex: str, unidade_texto: str) -> str:
        texto = f"{valor:.{casas}f}"
        if self.usar_latex:
            return rf"\qty{{{texto}}}{{{unidade_latex}}}"
        return f"{self.num(valor, casas)} {unidade_texto}"

    def formatador(self, casas: int | None = None) -> FuncFormatter:
        """Ticks lineares com o separador decimal do idioma (``casas=None``: o mínimo que distingue os ticks)."""
        def formatar(valor, _pos):
            if casas is None:
                n = 0
                while n < 4 and abs(round(valor, n) - valor) > 1e-9:
                    n += 1
            else:
                n = casas
            return self.num(0.0 if abs(valor) < 1e-12 else valor, n)
        return FuncFormatter(formatar)


# =====================================================================================================
# Registro das figuras
# =====================================================================================================
@dataclass
class Resultado:
    figura: plt.Figure
    macros: dict[str, str] = field(default_factory=dict)        # nome da macro LaTeX -> conteúdo
    comentarios: list[str] = field(default_factory=list)        # vão no topo do .tex (rastreabilidade)


FIGURAS: dict[str, tuple[Callable[[Estilo], Resultado], str]] = {}


def figura(nome: str, descricao: str):
    def registrar(funcao: Callable[[Estilo], Resultado]):
        FIGURAS[nome] = (funcao, descricao)
        return funcao
    return registrar


# =====================================================================================================
# Ajuste de um passa-baixa à resposta medida (só magnitude)
# =====================================================================================================
DB_POR_NEPER = 20 / math.log(10)


def mag_db_ordem1(f, k, fc):
    return 20 * np.log10(k) - 10 * np.log10(1 + (f / fc) ** 2)


def mag_db_ordem2(f, k, f0, q):
    """|H(j2πf)| em dB de H(s) = K ω0² / (s² + (ω0/Q) s + ω0²)."""
    x = f / f0
    return 20 * np.log10(k) - 10 * np.log10((1 - x ** 2) ** 2 + (x / q) ** 2)


def mag_db_ordem2_polo(f, k, f0, q, fp):
    """2ª ordem seguida de um polo real em fp (ex.: capacitância parasita do divisor)."""
    return mag_db_ordem2(f, k, f0, q) - 10 * np.log10(1 + (f / fp) ** 2)


@dataclass
class Ajuste:
    """Resultado de um ajuste por mínimos quadrados em dB."""
    nome: str
    parametros: np.ndarray
    covariancia: np.ndarray
    residuos_db: np.ndarray
    sigma_residuo_db: float    # desvio-padrão dos resíduos (com graus de liberdade descontados)
    bic: float
    pesos_medidos: bool        # True: incerteza por ponto veio das repetições; False: estimada pelos resíduos

    @property
    def incertezas(self) -> np.ndarray:
        return np.sqrt(np.diag(self.covariancia))

    @property
    def correlacao(self) -> np.ndarray:
        s = self.incertezas
        return self.covariancia / np.outer(s, s)


def _ajustar(nome, modelo, f, y_db, p0, limites, sigma_db) -> Ajuste:
    parametros, cov = curve_fit(modelo, f, y_db, p0=p0, bounds=limites, sigma=sigma_db,
                                absolute_sigma=sigma_db is not None, maxfev=50_000)
    residuos = y_db - modelo(f, *parametros)
    n, k = len(f), len(parametros)
    rss = float(np.sum(residuos ** 2)) if sigma_db is None else float(np.sum((residuos / sigma_db) ** 2))
    # BIC gaussiano: com pesos medidos, o termo de ajuste é o χ²; sem eles, n·ln(RSS/n).
    bic = (rss if sigma_db is not None else n * math.log(rss / n)) + k * math.log(n)
    return Ajuste(nome, parametros, cov, residuos, float(np.sqrt(np.sum(residuos ** 2) / (n - k))), bic,
                  sigma_db is not None)


def ajustar_passa_baixa(f: np.ndarray, ganho: np.ndarray, sigma_db: np.ndarray | None = None) -> dict[str, Ajuste]:
    """Ajusta 1ª ordem, 2ª ordem e 2ª ordem + polo real à magnitude medida (em dB, onde um erro relativo
    constante tem o mesmo peso em toda a faixa). Sem ``sigma_db``, todos os pontos pesam igual e a incerteza
    dos parâmetros vem da dispersão dos resíduos (supõe o modelo correto)."""
    y = 20 * np.log10(ganho)
    k0 = float(np.median(ganho[f <= f.min() * 20]))                  # patamar de baixa frequência
    abaixo = np.nonzero(y <= 20 * np.log10(k0) - 3)[0]
    f3 = float(f[abaixo[0]]) if len(abaixo) else float(f.max())       # estimativa grosseira de f-3dB
    fmax = float(f.max())
    return {
        "ordem1": _ajustar("1ª ordem", mag_db_ordem1, f, y, [k0, f3], ([0.1, f.min()], [10, 100 * fmax]), sigma_db),
        "ordem2": _ajustar("2ª ordem", mag_db_ordem2, f, y, [k0, f3 / 0.7, 0.6],
                           ([0.1, f.min(), 0.05], [10, 100 * fmax, 20]), sigma_db),
        "ordem2_polo": _ajustar("2ª ordem + polo real", mag_db_ordem2_polo, f, y, [k0, f3 / 0.7, 0.6, 3 * fmax],
                                ([0.1, f.min(), 0.05, f.min()], [10, 100 * fmax, 20, 1e4 * fmax]), sigma_db),
    }


def freq_menos_3db(f0: float, q: float) -> float:
    """Frequência em que o 2ª ordem cai 3 dB abaixo do patamar K: |H|²/K² = 1/2 -> u² + (1/Q² − 2)u − 1 = 0, u = (f/f0)²."""
    b = 1 / q ** 2 - 2
    return f0 * math.sqrt((-b + math.sqrt(b * b + 4)) / 2)


def propagar(funcao: Callable[..., float], parametros: np.ndarray, cov: np.ndarray) -> float:
    """Incerteza (1σ) de funcao(*parametros) pelo método delta, com gradiente numérico."""
    grad = np.empty(len(parametros))
    for i, p in enumerate(parametros):
        h = abs(p) * 1e-6 or 1e-9
        mais, menos = parametros.copy(), parametros.copy()
        mais[i] += h
        menos[i] -= h
        grad[i] = (funcao(*mais) - funcao(*menos)) / (2 * h)
    return float(math.sqrt(grad @ cov @ grad))


def polos_hz(f0: float, q: float) -> tuple[complex, complex]:
    """Polos de H(s) divididos por 2π (em Hz): f0·(−1/(2Q) ± √(1/(4Q²) − 1))."""
    disc = complex(1 / (4 * q * q) - 1) ** 0.5
    return (f0 * (-1 / (2 * q) + disc), f0 * (-1 / (2 * q) - disc))


def com_incerteza(valor: float, sigma: float, escala: float = 1.0) -> str:
    """'24.06(21)': a incerteza com 2 algarismos significativos e o valor arredondado na mesma casa (siunitx)."""
    valor, sigma = valor / escala, sigma / escala
    if not (sigma > 0 and math.isfinite(sigma)):
        return f"{valor:.6g}"
    casas = max(0, 1 - math.floor(math.log10(sigma)))
    digitos = round(sigma * 10 ** casas)
    if digitos >= 100 and casas > 0:   # 0,0996 arredonda para "100": vira 0,10, com dois algarismos de novo
        casas -= 1
        digitos = round(sigma * 10 ** casas)
    return f"{valor:.{casas}f}({digitos})"


# =====================================================================================================
# Figuras
# =====================================================================================================
PERFIL_CADEIA_TENSAO = SONDAS_DIR_PADRAO / "cadeia_tensao.json"


@figura("perfil_cadeia_tensao", "Resposta em frequência da cadeia de tensão (T3) com o ajuste de um passa-baixa de 2ª ordem")
def perfil_cadeia_tensao(estilo: Estilo) -> Resultado:
    perfil = carregar_perfil_sonda(PERFIL_CADEIA_TENSAO)          # valida o arquivo como o adc_tool.py faria
    dados = json.loads(PERFIL_CADEIA_TENSAO.read_text(encoding="utf-8"))
    pontos = sorted(dados["pontos"], key=lambda p: p["freq_hz"])
    f = np.array([p["freq_hz"] for p in pontos], dtype=float)
    g = np.array([p["ganho"] for p in pontos], dtype=float)

    # Com repetições (n > 1 em todo ponto), a incerteza de cada ponto vem do desvio entre elas: o ajuste fica
    # ponderado e o χ² reduzido passa a dizer se o modelo explica os dados. Com n = 1, pesos iguais.
    n = np.array([p.get("n", 1) for p in pontos], dtype=float)
    cv = np.array([p.get("desvio_pct", 0.0) for p in pontos], dtype=float) / 100
    sigma_db = DB_POR_NEPER * cv / np.sqrt(n) if np.all(n > 1) and np.all(cv > 0) else None

    ajustes = ajustar_passa_baixa(f, g, sigma_db)
    aj = ajustes["ordem2"]
    k, f0, q = aj.parametros
    sk, sf0, sq = aj.incertezas
    f3 = freq_menos_3db(f0, q)
    sf3 = propagar(lambda _k, a, b: freq_menos_3db(a, b), aj.parametros, aj.covariancia)
    p1, _ = polos_hz(f0, q)

    melhor = min(ajustes.values(), key=lambda a: a.bic)
    for a in ajustes.values():
        log.info(f"  {a.nome:22s} BIC = {a.bic:8.1f}   (ΔBIC = {a.bic - aj.bic:+7.1f} em relação à 2ª ordem)   "
                 f"resíduo = {a.sigma_residuo_db:.3f} dB")
    if melhor is not aj and aj.bic - melhor.bic > 10:
        log.warning(f"o modelo '{melhor.nome}' explica os dados decisivamente melhor que a 2ª ordem (ΔBIC > 10).")
    log.info(f"  2ª ordem: K = {k:.5f} ± {sk:.5f}; f0 = {f0:.1f} ± {sf0:.1f} Hz; Q = {q:.4f} ± {sq:.4f}; "
             f"f-3dB = {f3:.1f} ± {sf3:.1f} Hz; corr(f0, Q) = {aj.correlacao[1, 2]:+.2f}")

    # ---- figura: ganho (com o modelo tracejado ao fundo) e resíduos ---------------------------------
    fig = estilo.nova_figura(0.66)
    eixo, eixo_res = fig.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [3.2, 1], "hspace": 0.04})
    xmin, xmax = f.min() / 1.25, f.max() * 1.12     # o modelo vai um pouco além dos pontos, sem extrapolar longe
    fm = np.geomspace(xmin, xmax, 600)
    y = 20 * np.log10(g)
    ym = mag_db_ordem2(fm, *aj.parametros)

    curva_modelo, = eixo.plot(fm, ym, color=COR["modelo"], linestyle=(0, (5, 3)), alpha=0.6, zorder=2,
                              label=estilo.t("ajuste_2a"))
    pontos_medidos, = eixo.plot(f, y, linestyle="none", marker="o", color=COR["tinta"], markeredgecolor="white",
                                markeredgewidth=0.5, zorder=3, label=estilo.t("medido"))

    # Frequência de -3 dB do modelo: guia fina até a curva, com o valor ao lado.
    y3 = 20 * np.log10(k) - 3
    eixo.plot([f3, f3], [-100, y3], color=COR["secundaria"], linewidth=0.5, linestyle=(0, (1, 1.5)), zorder=1)
    eixo.plot([f3], [y3], marker="o", markersize=estilo.formato.marcador_pt * 0.9, markerfacecolor="white",
              markeredgecolor=COR["modelo"], markeredgewidth=0.8, linestyle="none", zorder=4)
    rotulo_f3 = r"$f_{-3\,\mathrm{dB}}$ = " + estilo.qty(f3 / 1e3, 1, r"\kilo\hertz", "kHz")
    eixo.annotate(rotulo_f3, xy=(f3, y3), xytext=(-6, -4), textcoords="offset points", ha="right", va="top",
                  color=COR["secundaria"], fontsize=estilo.formato.fonte_ticks_pt)

    eixo.set_ylim(min(y.min(), ym.min()) - 0.8, max(1.0, y.max() + 0.6))
    eixo.yaxis.set_major_locator(MultipleLocator(3))     # passos de 3 dB: a linha de -3 dB cai na grade
    eixo.yaxis.set_minor_locator(MultipleLocator(1))
    eixo.yaxis.set_major_formatter(estilo.formatador(0))
    eixo.set_ylabel(estilo.t("ganho_norm"))
    eixo.legend(handles=[pontos_medidos, curva_modelo], loc="lower left")

    lim = max(0.3, 1.25 * float(np.max(np.abs(aj.residuos_db))))
    eixo_res.axhline(0, color=COR["modelo"], linewidth=0.6, alpha=0.8, zorder=2)
    eixo_res.plot(f, aj.residuos_db, linestyle="none", marker="o", color=COR["tinta"], markeredgecolor="white",
                  markeredgewidth=0.5, markersize=estilo.formato.marcador_pt * 0.8, zorder=3)
    eixo_res.set_ylim(-lim, lim)
    eixo_res.yaxis.set_major_locator(MaxNLocator(nbins=3, symmetric=True, steps=[1, 2, 2.5, 5, 10]))
    eixo_res.yaxis.set_major_formatter(estilo.formatador())
    eixo_res.set_ylabel(estilo.t("residuo"))

    eixo_res.set_xscale("log")
    eixo_res.set_xlim(xmin, xmax)
    eixo_res.xaxis.set_major_locator(LogLocator(base=10))
    eixo_res.xaxis.set_minor_locator(LogLocator(base=10, subs=np.arange(2, 10)))
    eixo_res.xaxis.set_major_formatter(LogFormatterMathtext())
    eixo_res.set_xlabel(estilo.t("frequencia"))
    fig.align_ylabels([eixo, eixo_res])

    # ---- números para o texto (siunitx) ---------------------------------------------------------------
    k_db, sk_db = 20 * math.log10(k), DB_POR_NEPER * sk / k
    macros = {
        "CadeiaTensaoNpontos": str(len(f)),
        "CadeiaTensaoFmin": rf"\qty{{{f.min():.0f}}}{{\hertz}}",
        "CadeiaTensaoFmax": rf"\qty{{{f.max() / 1e3:.1f}}}{{\kilo\hertz}}",
        "CadeiaTensaoK": rf"\num{{{com_incerteza(k, sk)}}}",
        "CadeiaTensaoKdB": rf"\qty{{{com_incerteza(k_db, sk_db)}}}{{\decibel}}",
        "CadeiaTensaoFzero": rf"\qty{{{com_incerteza(f0, sf0, 1e3)}}}{{\kilo\hertz}}",
        "CadeiaTensaoQ": rf"\num{{{com_incerteza(q, sq)}}}",
        "CadeiaTensaoFcorte": rf"\qty{{{com_incerteza(f3, sf3, 1e3)}}}{{\kilo\hertz}}",
        "CadeiaTensaoCorrFzeroQ": rf"\num{{{aj.correlacao[1, 2]:.2f}}}",
        "CadeiaTensaoResiduo": rf"\qty{{{aj.sigma_residuo_db:.2f}}}{{\decibel}}",
        "CadeiaTensaoPoloReal": rf"\qty{{{p1.real / 1e3:.2f}}}{{\kilo\hertz}}",
        "CadeiaTensaoPoloImag": rf"\qty{{{abs(p1.imag) / 1e3:.2f}}}{{\kilo\hertz}}",
        "CadeiaTensaoH": r"\frac{K\,\omega_0^2}{s^2 + (\omega_0/Q)\,s + \omega_0^2}",
    }
    comentarios = [
        f"Perfil: {PERFIL_CADEIA_TENSAO.relative_to(RAIZ)} ({perfil.id}; {len(f)} pontos)",
        "Modelo: |H(j2πf)| de H(s) = K ω0² / (s² + (ω0/Q) s + ω0²), mínimos quadrados em dB "
        + ("ponderados pelo desvio entre repetições" if aj.pesos_medidos
           else "com pesos iguais (n = 1 por ponto: incertezas estimadas pela dispersão dos resíduos)"),
        f"K = {k:.6f} ± {sk:.6f}; f0 = {f0:.2f} ± {sf0:.2f} Hz; Q = {q:.5f} ± {sq:.5f}; f-3dB = {f3:.2f} ± {sf3:.2f} Hz",
        f"Polos/(2π): {p1.real:.1f} ± j{abs(p1.imag):.1f} Hz; corr(f0, Q) = {aj.correlacao[1, 2]:+.3f}",
        "BIC: " + "; ".join(f"{a.nome} {a.bic:.1f}" for a in ajustes.values()),
        "Fase NÃO medida: a função de transferência supõe sistema de fase mínima (sem atraso puro).",
    ]
    return Resultado(fig, macros, comentarios)


# =====================================================================================================
# Linha de comando
# =====================================================================================================
def escrever_macros(caminho: Path, nome: str, resultado: Resultado) -> None:
    linhas = [f"% Gerado por relatorio/gerar_figuras.py ({nome}) -- não edite à mão: rode o script de novo.",
              r"% Requer siunitx >= 3 (\qty, \num e incerteza entre parênteses)."]
    linhas += [f"% {c}" for c in resultado.comentarios]
    linhas += [rf"\providecommand{{\{m}}}{{}}\renewcommand{{\{m}}}{{{v}}}" for m, v in resultado.macros.items()]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gerar_figuras.py", description="Gera as figuras do relatório (PDF vetorial).")
    p.add_argument("nomes", nargs="*", help="Figuras a gerar (padrão: todas). Veja --listar.")
    p.add_argument("--listar", action="store_true", help="Lista as figuras disponíveis e sai.")
    p.add_argument("--formato", choices=sorted(FORMATOS), default="relatorio",
                   help="Largura e tamanhos de fonte (padrão: relatorio, 15 cm; artigo = uma coluna IEEE).")
    p.add_argument("--idioma", choices=sorted(TEXTOS), default="pt", help="Rótulos e separador decimal (padrão: pt).")
    p.add_argument("--sem-latex", action="store_true",
                   help="Não usa o LaTeX para o texto (mais rápido; fonte parecida, mas não idêntica à do documento).")
    p.add_argument("--png", action="store_true", help="Também salva uma prévia PNG (300 dpi) ao lado do PDF.")
    p.add_argument("--saida", type=Path, default=PASTA_FIGURAS, help="Pasta de saída (padrão: relatorio/figuras/).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = montar_parser().parse_args(argv)
    configurar_logging_cli()
    if args.listar:
        for nome, (_, descricao) in FIGURAS.items():
            log.info(f"{nome:28s} {descricao}")
        return 0
    desconhecidas = [n for n in args.nomes if n not in FIGURAS]
    if desconhecidas:
        log.error(f"figura(s) desconhecida(s): {', '.join(desconhecidas)} (veja --listar).")
        return 2

    usar_latex = not args.sem_latex and shutil.which("latex") is not None
    if not args.sem_latex and not usar_latex:
        log.warning("'latex' não encontrado: o texto das figuras sai com a fonte interna do matplotlib.")
    estilo = Estilo(FORMATOS[args.formato], args.idioma, usar_latex)
    estilo.aplicar()
    args.saida.mkdir(parents=True, exist_ok=True)
    sufixo = "" if (args.formato, args.idioma) == ("relatorio", "pt") else f"_{args.formato}_{args.idioma}"

    for nome in args.nomes or list(FIGURAS):
        funcao, _ = FIGURAS[nome]
        log.info(f"{nome}:")
        resultado = funcao(estilo)
        base = args.saida / f"{nome}{sufixo}"
        resultado.figura.savefig(base.with_suffix(".pdf"))
        if args.png:
            resultado.figura.savefig(base.with_suffix(".png"))
        plt.close(resultado.figura)
        if resultado.macros:
            escrever_macros(base.with_suffix(".tex"), nome, resultado)
        log.info(f"  -> {base.with_suffix('.pdf').relative_to(RAIZ) if base.is_relative_to(RAIZ) else base.with_suffix('.pdf')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
