#!/usr/bin/env -S uv run --script
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

    \includegraphics{figures/perfil_cadeia_tensao.pdf}     % sem width=...
    \input{figures/perfil_cadeia_tensao.tex}                % macros com os números (siunitx >= 3)

Uso (na raiz do repositório)::

    uv run report/gerar_figuras.py                                  # todas as figuras
    uv run report/gerar_figuras.py perfil_cadeia_tensao --png       # uma só, com prévia PNG
    uv run report/gerar_figuras.py --formato artigo --idioma en     # coluna de artigo, em inglês
    uv run report/gerar_figuras.py --listar

Saída em ``report/figures/``: ``<nome>.pdf`` (vetorial) e, quando a figura calcula algo, ``<nome>.tex`` com
os resultados como macros siunitx -- um número citado no texto nunca fica desatualizado em relação à figura.
Os dados vêm do resto do projeto (perfis em ``scripts/sondas/``, capturas, pacote ``supraharmonicos``):
nada é copiado à mão para cá.

As figuras ``readme_*`` são de TELA, não de documento: SVG de fundo transparente, legível no tema claro e no
escuro do GitHub, gravado direto em ``docs/images/`` (o ``--formato`` e o ``--idioma`` não se aplicam). Refaça-as
quando os dados mudarem (por exemplo, um T3 novo) e commite o SVG::

    uv run report/gerar_figuras.py readme_cadeia_tensao

Para acrescentar uma figura: escreva ``def minha_figura(estilo) -> Resultado`` com ``@figura("nome")``,
crie a figura com ``estilo.nova_figura(...)``, use as cores de ``COR`` e os textos de ``estilo.t(...)``
(acrescente as chaves em ``TEXTOS``, nos dois idiomas) e formate números com ``estilo.num``/``estilo.qty``.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import re
import shutil
import sys
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # só arquivos, nunca janela

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.ticker import (  # noqa: E402
    FixedLocator,
    FuncFormatter,
    LogFormatterMathtext,
    LogLocator,
    MaxNLocator,
    MultipleLocator,
    NullFormatter,
)
from scipy.optimize import curve_fit  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

from supraharmonicos.cabecalho import ler_cabecalho  # noqa: E402
from supraharmonicos.fase_quadrada import fase_do_modelo, h_segunda_ordem  # noqa: E402
from supraharmonicos.metricas_captura import (  # noqa: E402
    analisar_espectro,
    estimar_jitter,
    medir_degraus_de_tempo,
    posicoes_das_trocas,
    posicoes_dos_rebases,
    ruido_por_inclinacao,
)
from supraharmonicos.registro import configurar_logging_cli  # noqa: E402
from supraharmonicos.sonda import SONDAS_DIR_PADRAO, carregar_perfil_sonda  # noqa: E402

# Filho do logger do pacote: herda o formato de console de configurar_logging_cli (stdout/stderr, "Aviso: ").
log = logging.getLogger("supraharmonicos.relatorio")

PASTA_FIGURAS = Path(__file__).resolve().parent / "figures"
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
        "inclinacao": "Inclinação do tom (LSB/ns)",
        "ruido_residuo": "Ruído RMS do resíduo (LSB)",
        "antes_sondagem": "21/10: espera por sondagem",
        "depois_precisao": "22/10: espera de precisão",
        "modelo_jitter": r"$\sqrt{\sigma_0^2 + (s\,\sigma_t)^2}$",
        "tempo_captura": "Tempo desde o início da captura (s)",
        "degrau_ns": "Degrau de tempo (ns)",
        "trocas": "Trocas de buffer",
        "rebases": "Rebases do contador",
        "controle": "Entre eventos (controle)",
        "meio_ciclo": "±1/2 ciclo da PRU (2,5 ns)",
        "taxa_ks": "Taxa (kS/s)",
        "atrasadas": "Amostras fora da grade",
        "padrao": "padrão",
        "perfil_novo": "22/10: 312,5 kS/s, ±2,56 V",
        "perfil_antigo": "19/10: 100 kS/s, ±10,24 V",
        "ajuste_2a_novo": "Ajuste de 2ª ordem (22/10)",
        "diferenca_db": "19/10 − 22/10 (dB)",
        "bits_medida": "Medida (varredura J)",
        "bits_troca": "Só a troca de buffer (1 por captura)",
        "bits_prevista": "Prevista: quadro de {base} + bits 1 ciclos",
        "periodo_ciclos": "Período (ciclos de 5 ns)",
        "fracao_atrasadas": "Fração de amostras atrasadas",
        "fase_graus": "Fase (°)",
        "residuo_graus": "Resíduo (°)",
        "medido_quadradas": "Medido: 24 ondas quadradas",
        "ajuste_2a_polo": "Ajuste: 2ª ordem × polo real",
        "senoide_menos_quadrada": "Senoide (osciloscópio) − quadrada",
        "queda_referencia": "Queda da referência lida no osciloscópio",
        "diferenca_ref_db": "Diferença (dB)",
        "sobra_db": "Sobra (dB)",
    },
    "en": {
        "frequencia": "Frequency (Hz)",
        "ganho_norm": "Normalized gain (dB)",
        "residuo": "Residual (dB)",
        "medido": "Measured",
        "ajuste_2a": "Fit: 2nd-order low-pass",
        "inclinacao": "Tone slope (LSB/ns)",
        "ruido_residuo": "Residual RMS noise (LSB)",
        "antes_sondagem": "Oct 21: polling wait",
        "depois_precisao": "Oct 22: precision wait",
        "modelo_jitter": r"$\sqrt{\sigma_0^2 + (s\,\sigma_t)^2}$",
        "tempo_captura": "Time since capture start (s)",
        "degrau_ns": "Timing step (ns)",
        "trocas": "Buffer swaps",
        "rebases": "Counter rebases",
        "controle": "Between events (control)",
        "meio_ciclo": "±1/2 PRU cycle (2.5 ns)",
        "taxa_ks": "Rate (kS/s)",
        "atrasadas": "Samples off the grid",
        "padrao": "default",
        "perfil_novo": "Oct 22: 312.5 kS/s, ±2.56 V",
        "perfil_antigo": "Oct 19: 100 kS/s, ±10.24 V",
        "ajuste_2a_novo": "2nd-order fit (Oct 22)",
        "diferenca_db": "Oct 19 − Oct 22 (dB)",
        "bits_medida": "Measured (sweep J)",
        "bits_troca": "Buffer swap only (1 per capture)",
        "bits_prevista": "Predicted: {base} + one-bits cycle frame",
        "periodo_ciclos": "Period (5 ns cycles)",
        "fracao_atrasadas": "Fraction of late samples",
        "fase_graus": "Phase (°)",
        "residuo_graus": "Residual (°)",
        "medido_quadradas": "Measured: 24 square waves",
        "ajuste_2a_polo": "Fit: 2nd order × real pole",
        "senoide_menos_quadrada": "Sine (oscilloscope) − square",
        "queda_referencia": "Drop of the oscilloscope reference",
        "diferenca_ref_db": "Difference (dB)",
        "sobra_db": "Remainder (dB)",
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
    # Figura de TELA (README), não de documento: vai para este arquivo fixo, fora do --formato/--idioma, e é salva
    # com estes rcParams sobre os padrões do matplotlib (os rótulos dos eixos só são criados no savefig).
    destino: Path | None = None
    rc: dict = field(default_factory=dict)


FIGURAS: dict[str, tuple[Callable[[Estilo], Resultado], str]] = {}


def figura(nome: str, descricao: str):
    def registrar(funcao: Callable[[Estilo], Resultado]):
        FIGURAS[nome] = (funcao, descricao)
        return funcao
    return registrar


@contextmanager
def rc_sobre_padroes(rc: dict):
    """rcParams ``rc`` sobre os padrões do matplotlib (não sobre o Estilo do documento), só dentro do bloco."""
    with plt.rc_context():
        plt.rcdefaults()
        plt.rcParams.update(rc)
        yield


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
PERFIL_CADEIA_TENSAO = SONDAS_DIR_PADRAO / "cadeia_tensao.json"            # T3 de 19/10: 100 kS/s, até 45 kHz
PERFIL_CADEIA_TENSAO_312K = SONDAS_DIR_PADRAO / "cadeia_tensao_312k.json"  # T3 de 22/10: 312,5 kS/s, até 140 kHz
PERFIL_CADEIA_TENSAO_FASE = SONDAS_DIR_PADRAO / "cadeia_tensao_fase.json"  # T3f de 22/10: ondas quadradas, com a fase


def _cadeia_tensao(caminho: Path = PERFIL_CADEIA_TENSAO):
    """Pontos do perfil da cadeia de tensão e os ajustes de passa-baixa: (perfil, f, ganho, ajustes)."""
    perfil = carregar_perfil_sonda(caminho)                        # valida o arquivo como o adc_tool.py faria
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    pontos = sorted(dados["pontos"], key=lambda p: p["freq_hz"])
    f = np.array([p["freq_hz"] for p in pontos], dtype=float)
    g = np.array([p["ganho"] for p in pontos], dtype=float)

    # Com repetições (n > 1 em todo ponto), a incerteza de cada ponto vem do desvio entre elas: o ajuste fica
    # ponderado e o χ² reduzido passa a dizer se o modelo explica os dados. Com n = 1, pesos iguais.
    n = np.array([p.get("n", 1) for p in pontos], dtype=float)
    cv = np.array([p.get("desvio_pct", 0.0) for p in pontos], dtype=float) / 100
    sigma_db = DB_POR_NEPER * cv / np.sqrt(n) if np.all(n > 1) and np.all(cv > 0) else None
    return perfil, f, g, ajustar_passa_baixa(f, g, sigma_db)


@figura("perfil_cadeia_tensao", "Resposta em frequência da cadeia de tensão (T3) com o ajuste de um passa-baixa de 2ª ordem")
def perfil_cadeia_tensao(estilo: Estilo) -> Resultado:
    perfil, f, g, ajustes = _cadeia_tensao()
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


@figura("perfil_cadeia_tensao_comparacao", "T3 de 22/10 (312,5 kS/s, até 140 kHz) contra o de 19/10 (100 kS/s, 45 kHz)")
def perfil_cadeia_tensao_comparacao(estilo: Estilo) -> Resultado:
    _, fa, ga, _ = _cadeia_tensao(PERFIL_CADEIA_TENSAO)
    perfil, fn, gn, ajustes = _cadeia_tensao(PERFIL_CADEIA_TENSAO_312K)
    aj = ajustes["ordem2"]
    k, f0, q = aj.parametros
    sk, sf0, sq = aj.incertezas
    f3 = freq_menos_3db(f0, q)
    sf3 = propagar(lambda _k, a, b: freq_menos_3db(a, b), aj.parametros, aj.covariancia)
    melhor = min(ajustes.values(), key=lambda a: a.bic)
    for a in ajustes.values():
        log.info(f"  {a.nome:22s} BIC = {a.bic:8.1f}   resíduo = {a.sigma_residuo_db:.3f} dB")
    if melhor is not aj and aj.bic - melhor.bic > 10:
        log.warning(f"o modelo '{melhor.nome}' explica os dados decisivamente melhor que a 2ª ordem (ΔBIC > 10).")

    ya, yn = 20 * np.log10(ga), 20 * np.log10(gn)
    dif = ya - np.interp(np.log(fa), np.log(fn), yn)              # antigo - novo, nas frequências do antigo (em comum)
    dif_rms = float(np.sqrt(np.mean(dif ** 2)))
    disp_a = float(np.std(ga[fa < 1000], ddof=1) / np.mean(ga[fa < 1000]))
    disp_n = float(np.std(gn[fn < 1000], ddof=1) / np.mean(gn[fn < 1000]))

    fig = estilo.nova_figura(0.72)
    eixo, eixo_dif = fig.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [3.2, 1.1], "hspace": 0.04})
    xmin, xmax = min(fa.min(), fn.min()) / 1.25, fn.max() * 1.15
    fm = np.geomspace(xmin, xmax, 600)
    curva, = eixo.plot(fm, mag_db_ordem2(fm, *aj.parametros), color=COR["modelo"], linestyle=(0, (5, 3)), alpha=0.6,
                       zorder=2, label=estilo.t("ajuste_2a_novo"))
    novo, = eixo.plot(fn, yn, linestyle="none", marker="o", color=COR["tinta"], markeredgecolor="white",
                      markeredgewidth=0.5, zorder=3, label=estilo.t("perfil_novo"))
    antigo, = eixo.plot(fa, ya, linestyle="none", marker="s", markerfacecolor="none", markeredgecolor=COR["destaque"],
                        markeredgewidth=0.9, zorder=4, label=estilo.t("perfil_antigo"))
    eixo.axvline(fa.max(), color=COR["secundaria"], linewidth=0.5, linestyle=(0, (1, 1.5)), zorder=1)
    eixo.set_ylim(min(yn.min(), ya.min()) - 2, 2)
    eixo.yaxis.set_major_locator(MultipleLocator(6))
    eixo.yaxis.set_minor_locator(MultipleLocator(3))
    eixo.yaxis.set_major_formatter(estilo.formatador(0))
    eixo.set_ylabel(estilo.t("ganho_norm"))
    eixo.legend(handles=[novo, antigo, curva], loc="lower left")

    eixo_dif.axhline(0, color=COR["modelo"], linewidth=0.6, alpha=0.8, zorder=2)
    eixo_dif.plot(fa, dif, linestyle="none", marker="s", markerfacecolor="none", markeredgecolor=COR["destaque"],
                  markeredgewidth=0.9, markersize=estilo.formato.marcador_pt * 0.9, zorder=3)
    lim = max(0.3, 1.25 * float(np.max(np.abs(dif))))
    eixo_dif.set_ylim(-lim, lim)
    eixo_dif.yaxis.set_major_locator(MaxNLocator(nbins=3, symmetric=True, steps=[1, 2, 2.5, 5, 10]))
    eixo_dif.yaxis.set_major_formatter(estilo.formatador())
    eixo_dif.set_ylabel(estilo.t("diferenca_db"))
    eixo_dif.set_xscale("log")
    eixo_dif.set_xlim(xmin, xmax)
    eixo_dif.xaxis.set_major_locator(LogLocator(base=10))
    eixo_dif.xaxis.set_minor_locator(LogLocator(base=10, subs=np.arange(2, 10)))
    eixo_dif.xaxis.set_major_formatter(LogFormatterMathtext())
    eixo_dif.set_xlabel(estilo.t("frequencia"))
    fig.align_ylabels([eixo, eixo_dif])

    log.info(f"  novo: K = {k:.5f} ± {sk:.5f}; f0 = {f0:.1f} ± {sf0:.1f} Hz; Q = {q:.4f} ± {sq:.4f}; "
             f"f-3dB = {f3:.1f} ± {sf3:.1f} Hz; resíduo {aj.sigma_residuo_db:.3f} dB; em {fn.max():.0f} Hz: {yn[-1]:.1f} dB")
    log.info(f"  antigo - novo: {dif_rms:.3f} dB rms, pior {dif[np.argmax(np.abs(dif))]:+.3f} dB; dispersão abaixo de "
             f"1 kHz: {100 * disp_a:.2f} % (antigo) e {100 * disp_n:.2f} % (novo)")
    macros = {
        "CadeiaTensaoNovaNpontos": str(len(fn)),
        "CadeiaTensaoNovaFmax": rf"\qty{{{fn.max() / 1e3:.0f}}}{{\kilo\hertz}}",
        "CadeiaTensaoNovaFzero": rf"\qty{{{com_incerteza(f0, sf0, 1e3)}}}{{\kilo\hertz}}",
        "CadeiaTensaoNovaQ": rf"\num{{{com_incerteza(q, sq)}}}",
        "CadeiaTensaoNovaFcorte": rf"\qty{{{com_incerteza(f3, sf3, 1e3)}}}{{\kilo\hertz}}",
        "CadeiaTensaoNovaResiduo": rf"\qty{{{aj.sigma_residuo_db:.2f}}}{{\decibel}}",
        "CadeiaTensaoNovaGanhoFmax": rf"\qty{{{yn[-1]:.1f}}}{{\decibel}}",
        "CadeiaTensaoNovaCorrecaoFmax": rf"\num{{{1 / gn[-1]:.0f}}}",
        "CadeiaTensaoDifRms": rf"\qty{{{dif_rms:.2f}}}{{\decibel}}",
        "CadeiaTensaoDispersaoAntiga": rf"\qty{{{100 * disp_a:.2f}}}{{\percent}}",
        "CadeiaTensaoDispersaoNova": rf"\qty{{{100 * disp_n:.2f}}}{{\percent}}",
    }
    comentarios = [f"Perfis: {PERFIL_CADEIA_TENSAO.relative_to(RAIZ)} (19/10, 100 kS/s, ±10,24 V) e "
                   f"{PERFIL_CADEIA_TENSAO_312K.relative_to(RAIZ)} ({perfil.id}: 22/10, 312,5 kS/s, ±2,56 V)",
                   "Diferença: o perfil novo interpolado em log f, nas frequências do antigo (50 Hz a 45 kHz).",
                   "BIC do novo: " + "; ".join(f"{a.nome} {a.bic:.1f}" for a in ajustes.values())]
    return Resultado(fig, macros, comentarios)


def _cadeia_tensao_fase(caminho: Path = PERFIL_CADEIA_TENSAO_FASE):
    """O perfil por ondas quadradas: (perfil, f, ganho/K, σ do ln, fase, σ da fase, K, modelo) só nos pontos da grade
    medida (os que têm ``sigma_fase_rad``; abaixo de 256 Hz o perfil traz pontos do perfil base, sem fase medida)."""
    perfil = carregar_perfil_sonda(caminho)
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    pontos = sorted((p for p in dados["pontos"] if "sigma_fase_rad" in p), key=lambda p: p["freq_hz"])
    f = np.array([p["freq_hz"] for p in pontos], dtype=float)
    g = np.array([p["ganho"] for p in pontos], dtype=float)
    s_ln = np.array([p["desvio_pct"] for p in pontos], dtype=float) / 100
    fase = np.array([p["fase_rad"] for p in pontos], dtype=float)
    s_fase = np.array([p["sigma_fase_rad"] for p in pontos], dtype=float)
    modelo = dados["resposta_fase"]["segunda_ordem"]
    f0, q, polo = modelo["f0_hz"], modelo["q"], modelo.get("polo_real_hz", math.inf)
    # K (o ganho em baixa frequência, do T2) multiplica a grade, que é relativa: o medir_fase.py o escreve no perfil;
    # sem ele, sai dos pontos abaixo de 2 kHz
    achado = re.search(r"K = ([0-9.]+)", dados["resposta_fase"].get("ganho", ""))
    if "k_baixa_frequencia" in dados["resposta_fase"]:
        k = float(dados["resposta_fase"]["k_baixa_frequencia"])
    elif achado:
        k = float(achado.group(1))
    else:
        baixos = f < 2000
        k = float(np.exp(np.average(np.log(g[baixos] / np.abs(h_segunda_ordem(f[baixos], f0, q, polo))),
                                    weights=1 / s_ln[baixos] ** 2)))
    return perfil, dados, f, g / k, s_ln, fase, s_fase, k, (f0, q, polo)


def _freq_menos_3db_modelo(f0: float, q: float, polo: float) -> float:
    from scipy.optimize import brentq

    return float(brentq(lambda x: abs(h_segunda_ordem(x, f0, q, polo)) ** 2 - 0.5, f0 * 1e-3, f0 * 1e3))


def _eixo_log_frequencia(eixo, estilo: Estilo, xmin: float, xmax: float) -> None:
    eixo.set_xscale("log")
    eixo.set_xlim(xmin, xmax)
    eixo.xaxis.set_major_locator(LogLocator(base=10))
    eixo.xaxis.set_minor_locator(LogLocator(base=10, subs=np.arange(2, 10)))
    eixo.xaxis.set_major_formatter(LogFormatterMathtext())
    eixo.set_xlabel(estilo.t("frequencia"))


@figura("perfil_cadeia_tensao_fase", "T3f: magnitude e fase da cadeia de tensão por ondas quadradas (Bode, com o ajuste)")
def perfil_cadeia_tensao_fase(estilo: Estilo) -> Resultado:
    perfil, dados, f, g, s_ln, fase, s_fase, k, (f0, q, polo) = _cadeia_tensao_fase()
    modelo = dados["resposta_fase"]["segunda_ordem"]
    f3 = _freq_menos_3db_modelo(f0, q, polo)
    capturas = dados["resposta_fase"]["capturas"]

    fig = estilo.nova_figura(1.05)
    mag, res_mag, ang, res_ang = fig.subplots(4, 1, sharex=True,
                                              gridspec_kw={"height_ratios": [3, 1.15, 3, 1.15], "hspace": 0.05})
    xmin, xmax = f.min() / 1.3, f.max() * 1.25
    fm = np.geomspace(xmin, xmax, 600)
    hm = h_segunda_ordem(fm, f0, q, polo)
    estilo_pontos = dict(linestyle="none", marker="o", color=COR["tinta"], markeredgecolor="white",
                         markeredgewidth=0.5, zorder=3)
    estilo_barras = dict(fmt="o", color=COR["tinta"], ecolor=COR["tinta"], elinewidth=0.6, capsize=1.2,
                         markeredgecolor="white", markeredgewidth=0.5, markersize=estilo.formato.marcador_pt * 0.8,
                         zorder=3)

    curva, = mag.plot(fm, DB_POR_NEPER * np.log(np.abs(hm)), color=COR["modelo"], linestyle=(0, (5, 3)), alpha=0.7,
                      zorder=2, label=estilo.t("ajuste_2a_polo"))
    medidos, = mag.plot(f, DB_POR_NEPER * np.log(g), label=estilo.t("medido_quadradas"), **estilo_pontos)
    mag.plot([f3, f3], [-100, -3], color=COR["secundaria"], linewidth=0.5, linestyle=(0, (1, 1.5)), zorder=1)
    mag.plot([f3], [-3], marker="o", markersize=estilo.formato.marcador_pt * 0.9, markerfacecolor="white",
             markeredgecolor=COR["modelo"], markeredgewidth=0.8, linestyle="none", zorder=4)
    mag.annotate(r"$f_{-3\,\mathrm{dB}}$ = " + estilo.qty(f3 / 1e3, 2, r"\kilo\hertz", "kHz"), xy=(f3, -3),
                 xytext=(-6, -4), textcoords="offset points", ha="right", va="top", color=COR["secundaria"],
                 fontsize=estilo.formato.fonte_ticks_pt)
    mag.set_ylim(DB_POR_NEPER * np.log(g.min()) - 3, 2)
    mag.yaxis.set_major_locator(MultipleLocator(10))
    mag.yaxis.set_minor_locator(MultipleLocator(5))
    mag.yaxis.set_major_formatter(estilo.formatador(0))
    mag.set_ylabel(estilo.t("ganho_norm"))
    mag.legend(handles=[medidos, curva], loc="lower left")

    r_db = DB_POR_NEPER * (np.log(g) - np.log(np.abs(h_segunda_ordem(f, f0, q, polo))))
    res_mag.axhline(0, color=COR["modelo"], linewidth=0.6, alpha=0.8, zorder=2)
    res_mag.errorbar(f, r_db, yerr=DB_POR_NEPER * s_ln, **estilo_barras)
    visiveis = f < 120e3          # acima disso a barra de incerteza cresce (harmônicos de poucos LSB) e esmagaria o resto
    lim = max(0.01, 1.3 * float(np.max(np.abs(r_db[visiveis]) + DB_POR_NEPER * s_ln[visiveis])))
    res_mag.set_ylim(-lim, lim)
    res_mag.yaxis.set_major_locator(MaxNLocator(nbins=3, symmetric=True, steps=[1, 2, 2.5, 5, 10]))
    res_mag.yaxis.set_major_formatter(estilo.formatador())
    res_mag.set_ylabel(estilo.t("residuo"))

    ang.plot(fm, np.degrees(fase_do_modelo(fm, f0, q, polo)), color=COR["modelo"], linestyle=(0, (5, 3)), alpha=0.7,
             zorder=2)
    ang.plot(f, np.degrees(fase), **estilo_pontos)
    ang.set_ylim(-185, 5)
    ang.yaxis.set_major_locator(MultipleLocator(45))
    ang.yaxis.set_minor_locator(MultipleLocator(15))
    ang.yaxis.set_major_formatter(estilo.formatador(0))
    ang.set_ylabel(estilo.t("fase_graus"))

    r_graus = np.degrees(fase - fase_do_modelo(f, f0, q, polo))
    res_ang.axhline(0, color=COR["modelo"], linewidth=0.6, alpha=0.8, zorder=2)
    res_ang.errorbar(f, r_graus, yerr=np.degrees(s_fase), **estilo_barras)
    lim = max(0.05, 1.3 * float(np.max(np.abs(r_graus[visiveis]) + np.degrees(s_fase[visiveis]))))
    res_ang.set_ylim(-lim, lim)
    res_ang.yaxis.set_major_locator(MaxNLocator(nbins=3, symmetric=True, steps=[1, 2, 2.5, 5, 10]))
    res_ang.yaxis.set_major_formatter(estilo.formatador())
    res_ang.set_ylabel(estilo.t("residuo_graus"))
    _eixo_log_frequencia(res_ang, estilo, xmin, xmax)
    fig.align_ylabels([mag, res_mag, ang, res_ang])

    log.info(f"  f0 = {f0:.1f} Hz, Q = {q:.5f}, polo = {polo / 1e3:.0f} kHz, f-3dB = {f3:.1f} Hz, K = {k:.5f}; "
             f"{len(f)} faixas; resíduo da grade {np.sqrt(np.mean(r_db ** 2)):.4f} dB e "
             f"{np.sqrt(np.mean(r_graus ** 2)):.3f}° rms")
    macros = {
        "CadeiaFaseNcapturas": str(len(capturas)),
        "CadeiaFaseNfaixas": str(len(f)),
        "CadeiaFaseFmin": rf"\qty{{{f.min():.0f}}}{{\hertz}}",
        "CadeiaFaseFmax": rf"\qty{{{f.max() / 1e3:.1f}}}{{\kilo\hertz}}",
        "CadeiaFaseFzero": rf"\qty{{{com_incerteza(f0, modelo['sigma_f0_hz'], 1e3)}}}{{\kilo\hertz}}",
        "CadeiaFaseQ": rf"\num{{{com_incerteza(q, modelo['sigma_q'])}}}",
        "CadeiaFaseFcorte": rf"\qty{{{f3 / 1e3:.2f}}}{{\kilo\hertz}}",
        "CadeiaFaseK": rf"\num{{{k:.5f}}}",
        "CadeiaFaseResiduoDb": rf"\qty{{{modelo['residuo_db']:.4f}}}{{\decibel}}",
        "CadeiaFaseResiduoGraus": rf"\qty{{{modelo['residuo_graus']:.3f}}}{{\degree}}",
        "CadeiaFaseSigmaDb": rf"\qty{{{DB_POR_NEPER * float(np.median(s_ln)):.4f}}}{{\decibel}}",
        "CadeiaFaseSigmaGraus": rf"\qty{{{math.degrees(float(np.median(s_fase))):.3f}}}{{\degree}}",
        "CadeiaFaseGanhoFmax": rf"\qty{{{DB_POR_NEPER * math.log(g[-1]):.1f}}}{{\decibel}}",
        "CadeiaFaseFaseFmax": rf"\qty{{{math.degrees(fase[-1]):.1f}}}{{\degree}}",
    }
    if math.isfinite(polo):
        macros["CadeiaFasePolo"] = rf"\qty{{{com_incerteza(polo, modelo['sigma_polo_real_hz'], 1e3)}}}{{\kilo\hertz}}"
    comentarios = [
        f"Perfil: {PERFIL_CADEIA_TENSAO_FASE.relative_to(RAIZ)} ({perfil.id}; {len(f)} faixas da grade medida, "
        f"{len(capturas)} capturas)",
        "Modelo: H(s) = K ω0² / (s² + (ω0/Q) s + ω0²) · 1/(1 + s/ωp), ajustado pelo medir_fase.py à magnitude e à "
        "fase relativas dos harmônicos ímpares (arg Xn − n·arg X1)",
        f"f0 = {f0:.2f} ± {modelo['sigma_f0_hz']:.2f} Hz; Q = {q:.5f} ± {modelo['sigma_q']:.5f}; polo = "
        f"{polo:.0f} ± {modelo.get('sigma_polo_real_hz', math.nan):.0f} Hz; f-3dB = {f3:.1f} Hz; K = {k:.5f}",
        "Fase: a menos de um atraso puro, supondo fase mínima (a magnitude e a fase dão o mesmo filtro).",
    ]
    return Resultado(fig, macros, comentarios)


REFERENCIA_T3_312K = Path(os.environ.get("DADOS", Path.home() / "Documents" / "sh-analyzer-data")) / \
    "lab/2026-10-22/capturas/cadeia_tensao_312k/referencia_externa.csv"


@figura("perfil_cadeia_tensao_referencia", "T3 por senoides menos T3f por quadradas, contra a queda da referência do "
        "osciloscópio")
def perfil_cadeia_tensao_referencia(estilo: Estilo) -> Resultado:
    """O perfil por senoides (referência: o RMS que o osciloscópio leu na entrada do divisor) dividido pelo por
    quadradas (sem referência nenhuma) é a queda dessa referência: a varredura por senoides, com o gerador (de
    amplitude constante) como referência, reproduz a quadrada."""
    _exigir(REFERENCIA_T3_312K)
    with open(REFERENCIA_T3_312K, encoding="utf-8") as arq:
        ref = {linha["arquivo"]: float(linha["tensao_rms_V"]) for linha in csv.DictReader(arq)}
    fr = np.array([float(nome.split("_")[1].removesuffix("Hz")) for nome in ref])
    vr = np.array(list(ref.values()))
    ordem = np.argsort(fr)
    fr, vr = fr[ordem], vr[ordem]
    _, fs, gs, _ = _cadeia_tensao(PERFIL_CADEIA_TENSAO_312K)
    _, _, fq, gq, *_, k, _ = _cadeia_tensao_fase()
    sel = (fs >= fq.min()) & (fs <= fq.max())
    fs, gs = fs[sel], gs[sel]
    dif = DB_POR_NEPER * (np.log(gs) - np.interp(np.log(fs), np.log(fq), np.log(k * gq)))
    queda = -DB_POR_NEPER * np.log(np.interp(np.log(fs), np.log(fr), vr) / np.median(vr[fr < 300]))
    sobra = dif - queda
    rms_sobra = float(np.sqrt(np.mean(sobra ** 2)))
    alto = fs > 40e3

    fig = estilo.nova_figura(0.62)
    eixo, eixo_sobra = fig.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [3, 1.1], "hspace": 0.04})
    xmin, xmax = fs.min() / 1.3, fs.max() * 1.3
    linha_ref, = eixo.plot(fr[(fr >= fs.min() / 1.01) & (fr <= fs.max() * 1.01)],
                           -DB_POR_NEPER * np.log(vr / np.median(vr[fr < 300]))[(fr >= fs.min() / 1.01)
                                                                               & (fr <= fs.max() * 1.01)],
                           color=COR["destaque"], marker="s", markerfacecolor="none", markeredgewidth=0.9,
                           linewidth=0.8, zorder=2, label=estilo.t("queda_referencia"))
    pontos, = eixo.plot(fs, dif, linestyle="none", marker="o", color=COR["tinta"], markeredgecolor="white",
                        markeredgewidth=0.5, zorder=3, label=estilo.t("senoide_menos_quadrada"))
    eixo.axhline(0, color=COR["secundaria"], linewidth=0.5, zorder=1)
    eixo.set_ylim(-0.15, max(1.5, 1.1 * float(dif.max())))
    eixo.yaxis.set_major_locator(MultipleLocator(0.5))
    eixo.yaxis.set_major_formatter(estilo.formatador(1))
    eixo.set_ylabel(estilo.t("diferenca_ref_db"))
    eixo.legend(handles=[pontos, linha_ref], loc="upper left")

    eixo_sobra.axhline(0, color=COR["modelo"], linewidth=0.6, alpha=0.8, zorder=2)
    eixo_sobra.plot(fs, sobra, linestyle="none", marker="o", color=COR["tinta"], markeredgecolor="white",
                    markeredgewidth=0.5, markersize=estilo.formato.marcador_pt * 0.8, zorder=3)
    lim = max(0.05, 1.3 * float(np.max(np.abs(sobra))))
    eixo_sobra.set_ylim(-lim, lim)
    eixo_sobra.yaxis.set_major_locator(MaxNLocator(nbins=3, symmetric=True, steps=[1, 2, 2.5, 5, 10]))
    eixo_sobra.yaxis.set_major_formatter(estilo.formatador())
    eixo_sobra.set_ylabel(estilo.t("sobra_db"))
    _eixo_log_frequencia(eixo_sobra, estilo, xmin, xmax)
    fig.align_ylabels([eixo, eixo_sobra])

    log.info(f"  senoide − quadrada acima de 40 kHz: {dif[alto].mean():+.3f} dB; queda da referência "
             f"{queda[alto].mean():+.3f} dB; sobra {rms_sobra:.4f} dB rms (correlação {np.corrcoef(dif, queda)[0, 1]:.4f})")
    macros = {
        "CadeiaRefDifAlta": rf"\qty{{{dif[alto].mean():.2f}}}{{\decibel}}",
        "CadeiaRefQuedaAlta": rf"\qty{{{queda[alto].mean():.2f}}}{{\decibel}}",
        "CadeiaRefQuedaPct": rf"\qty{{{100 * (1 - vr[-1] / np.median(vr[fr < 300])):.0f}}}{{\percent}}",
        "CadeiaRefSobraRms": rf"\qty{{{rms_sobra:.3f}}}{{\decibel}}",
        "CadeiaRefCorrelacao": rf"\num{{{np.corrcoef(dif, queda)[0, 1]:.3f}}}",
    }
    comentarios = [f"Senoides: {PERFIL_CADEIA_TENSAO_312K.relative_to(RAIZ)} e a referência digitada em cada ponto "
                   f"({REFERENCIA_T3_312K.name}); quadradas: {PERFIL_CADEIA_TENSAO_FASE.relative_to(RAIZ)} (× K)",
                   "Sobra = (senoide − quadrada) − queda da referência: a senoide com o gerador como referência menos a "
                   "quadrada."]
    return Resultado(fig, macros, comentarios)


# =====================================================================================================
# T7f: a grade de tempo (22/10/2026) -- lê as capturas em $DADOS (fora do repositório)
# =====================================================================================================
DADOS = Path(os.environ.get("DADOS", Path.home() / "Documents" / "sh-analyzer-data"))
CAPTURA_ANTES_GRADE = DADOS / "lab/2026-10-21/T7e_2026-10-21_1731/B_cs3-1-3_312500_tom.bin"   # firmware v0.7
PASTA_T7F = DADOS / "lab/2026-10-22/T7f_2026-10-22_0435"
CAPTURA_DEPOIS_GRADE = PASTA_T7F / "G_cspadrao_312500_tom_60s.bin"
CAPTURA_LONGA_GRADE = PASTA_T7F / "G_cspadrao_312500_tom_300s.bin"
TOM_GRADE_HZ = 10_000.0
AMOSTRAS_10S = 3_145_728        # 10 s a 312,5 kS/s: a duração das capturas de 21/10


def _exigir(*caminhos: Path) -> None:
    faltam = [c for c in caminhos if not c.exists()]
    if faltam:
        raise FileNotFoundError("faltam as capturas (defina DADOS ou traga-as): "
                                + ", ".join(str(c) for c in faltam))


def _canal_do_tom(caminho: Path, max_amostras: int | None = None):
    """(amostras do canal com o tom, em LSB, sem copiar o arquivo; fs do canal; cabeçalho). O tom vai no último
    canal da lista (o canal 1, nas capturas do T7e/T7f)."""
    cab = ler_cabecalho(caminho)
    bruto = np.memmap(caminho, dtype="<u2", mode="r", offset=cab.tamanho_cabecalho)
    nc = cab.num_canais
    sinal = bruto[nc - 1::nc] if nc > 1 else bruto
    if max_amostras is not None:
        sinal = sinal[:max_amostras]
    return sinal, cab.pru_clock_hz / cab.sample_period_ticks / nc, cab


def _freq_do_tom(sinal, fs: float) -> float:
    return analisar_espectro(np.asarray(sinal[: 1 << 21], dtype=np.float64), fs, TOM_GRADE_HZ).freq_tom_hz


def _ruido_fora_do_tom(sinal, fs: float, f0: float, exclusao_hz: float = 50.0) -> float:
    """Ruído RMS (LSB) fora de ±``exclusao_hz`` do tom e dos harmônicos até o 9º, extrapolado para a banda toda: o
    ruído de banda larga, sem o ruído de fase do gerador (que fica colado no tom)."""
    x = np.asarray(sinal[64: 64 + (1 << 21)], dtype=np.float64)
    x -= x.mean()
    janela = np.kaiser(len(x), 14)
    p = 2 * np.abs(np.fft.rfft(x * janela)) ** 2 / (len(x) * np.sum(janela ** 2))
    f = np.fft.rfftfreq(len(x), 1 / fs)
    fora = f > 50
    for h in range(1, 10):
        fh = (h * f0) % fs
        fora &= np.abs(f - min(fh, fs - fh)) > exclusao_hz
    return math.sqrt(p[fora].sum() / fora.mean())


@figura("grade_jitter", "T7f: o ruído do resíduo contra a inclinação do tom, antes (8,5 ns de jitter) e depois")
def grade_jitter(estilo: Estilo) -> Resultado:
    _exigir(CAPTURA_ANTES_GRADE, CAPTURA_DEPOIS_GRADE)
    fig = estilo.nova_figura(0.55)
    eixo = fig.subplots()
    macros, comentarios = {}, []
    for chave, caminho, cor, marcador in (("Antes", CAPTURA_ANTES_GRADE, COR["destaque"], "o"),
                                          ("Depois", CAPTURA_DEPOIS_GRADE, COR["tinta"], "s")):
        sinal, fs, cab = _canal_do_tom(caminho, AMOSTRAS_10S)
        f0 = _freq_do_tom(sinal, fs)
        jitter = estimar_jitter(sinal, fs, f0)
        inclinacao, ruido = ruido_por_inclinacao(sinal, fs, f0)
        s = inclinacao * 1e-9                                         # LSB/ns
        largo = _ruido_fora_do_tom(sinal, fs, f0)
        rotulo = estilo.t("antes_sondagem" if chave == "Antes" else "depois_precisao")
        eixo.plot(s, ruido, linestyle="none", marker=marcador, color=cor, markeredgecolor="white",
                  markeredgewidth=0.5, zorder=3, label=rotulo)
        sm = np.linspace(0, s.max() * 1.05, 200)
        eixo.plot(sm, np.sqrt(jitter.ruido_plano ** 2 + (sm * jitter.rms_ns) ** 2), color=cor, alpha=0.55,
                  linestyle=(0, (5, 3)), zorder=2)
        log.info(f"  {chave.lower()}: jitter {jitter.rms_ns:.2f} ns, ruído plano {jitter.ruido_plano:.2f} LSB, "
                 f"ruído de banda larga {largo:.2f} LSB ({caminho.name}, {cab.versao_firmware or 'firmware antigo'})")
        macros[f"GradeJitter{chave}"] = rf"\qty{{{jitter.rms_ns:.1f}}}{{\nano\second}}"
        macros[f"GradeRuidoPlano{chave}"] = rf"\num{{{jitter.ruido_plano:.2f}}}"
        macros[f"GradeRuidoLargo{chave}"] = rf"\num{{{largo:.2f}}}"
        comentarios.append(f"{chave}: {caminho.relative_to(DADOS)} (primeiros 10 s), f0 = {f0:.4f} Hz, "
                           f"jitter = {jitter.rms_ns:.3f} ns, ruído plano = {jitter.ruido_plano:.3f} LSB, "
                           f"banda larga fora de ±50 Hz = {largo:.3f} LSB")
    eixo.set_xlim(0, None)
    eixo.set_ylim(0, None)
    eixo.xaxis.set_major_formatter(estilo.formatador())
    eixo.yaxis.set_major_formatter(estilo.formatador())
    eixo.set_xlabel(estilo.t("inclinacao"))
    eixo.set_ylabel(estilo.t("ruido_residuo"))
    eixo.legend(loc="upper left", title=estilo.t("modelo_jitter"), title_fontsize=estilo.formato.fonte_ticks_pt)
    comentarios.append("Tom de 10 kHz em ±2,56 V, 312,5 kS/s; o modelo tracejado é sqrt(σ0² + (s σt)²) com o σt "
                       "de estimar_jitter (mediana entre blocos de 2000 amostras).")
    return Resultado(fig, macros, comentarios)


@figura("grade_degraus", "T7f: o degrau de tempo em cada troca de buffer e rebase do contador, em 5 min a 312,5 kS/s")
def grade_degraus(estilo: Estilo) -> Resultado:
    _exigir(CAPTURA_LONGA_GRADE)
    sinal, fs, cab = _canal_do_tom(CAPTURA_LONGA_GRADE)
    f0 = _freq_do_tom(sinal, fs)
    pos_trocas = posicoes_das_trocas(cab.samples_per_buffer, cab.num_canais, 0, len(sinal))
    pos_rebases = posicoes_dos_rebases(cab.pru_clock_hz, cab.sample_period_ticks, cab.num_canais, 0, len(sinal))
    trocas = medir_degraus_de_tempo(sinal, fs, f0, pos_trocas)
    rebases = medir_degraus_de_tempo(sinal, fs, f0, pos_rebases)
    meios = [(a + b) / 2 for a, b in zip([0.0, *pos_trocas], [*pos_trocas, float(len(sinal))])]

    fig = estilo.nova_figura(0.45)
    eixo = fig.subplots()
    eixo.axhspan(-2.5, 2.5, color=COR["modelo"], alpha=0.10, linewidth=0, zorder=1, label=estilo.t("meio_ciclo"))
    eixo.axhline(0, color=COR["modelo"], linewidth=0.6, alpha=0.8, zorder=2)
    controle_t = [m / fs for m in meios if 4000 <= m <= len(sinal) - 4000][: len(trocas.controle_ns)]
    eixo.plot(controle_t, trocas.controle_ns[: len(controle_t)], linestyle="none", marker=".",
              color=COR["secundaria"], alpha=0.6, zorder=2, label=estilo.t("controle"))
    eixo.plot(np.array(pos_trocas[: len(trocas.eventos_ns)]) / fs, trocas.eventos_ns, linestyle="none", marker="o",
              color=COR["tinta"], markeredgecolor="white", markeredgewidth=0.5, zorder=3, label=estilo.t("trocas"))
    eixo.plot(np.array(pos_rebases[: len(rebases.eventos_ns)]) / fs, rebases.eventos_ns, linestyle="none",
              marker="D", color=COR["destaque"], markeredgecolor="white", markeredgewidth=0.5, zorder=4,
              label=estilo.t("rebases"))
    eixo.set_ylim(-4, 4)
    eixo.yaxis.set_major_locator(MultipleLocator(2))
    eixo.yaxis.set_major_formatter(estilo.formatador(0))
    eixo.xaxis.set_major_formatter(estilo.formatador(0))
    eixo.set_xlim(0, len(sinal) / fs)
    eixo.set_xlabel(estilo.t("tempo_captura"))
    eixo.set_ylabel(estilo.t("degrau_ns"))
    eixo.legend(loc="lower left", ncols=2)

    def media_erro(d):
        v = np.asarray(d.eventos_ns)
        return float(v.mean()), float(v.std(ddof=1) / math.sqrt(len(v)))
    mt, et = media_erro(trocas)
    mr, er = media_erro(rebases)
    pior = max([*trocas.eventos_ns, *rebases.eventos_ns], key=abs)
    log.info(f"  {len(trocas.eventos_ns)} trocas: {mt:+.3f} ± {et:.3f} ns; {len(rebases.eventos_ns)} rebases: "
             f"{mr:+.3f} ± {er:.3f} ns; pior {pior:+.2f} ns; controle ±{trocas.dispersao_controle_ns:.2f} ns")
    macros = {
        "GradeTrocasN": str(len(trocas.eventos_ns)),
        "GradeTrocasMedia": rf"\qty{{{mt:.2f}({round(et * 100):d})}}{{\nano\second}}",
        "GradeRebasesN": str(len(rebases.eventos_ns)),
        "GradeRebasesMedia": rf"\qty{{{mr:.2f}({round(er * 100):d})}}{{\nano\second}}",
        "GradeDegrauPior": rf"\qty{{{pior:.1f}}}{{\nano\second}}",
        "GradeControle": rf"\qty{{{trocas.dispersao_controle_ns:.2f}}}{{\nano\second}}",
        "GradeCiclosRebase": str(cab.ciclos_rebase),
        "GradeDuracaoLonga": rf"\qty{{{len(sinal) / fs / 60:.0f}}}{{\minute}}",
    }
    comentarios = [f"Captura: {CAPTURA_LONGA_GRADE.relative_to(DADOS)} ({cab.versao_firmware}), f0 = {f0:.4f} Hz",
                   "Degrau = fase do tom ajustada 4000 amostras depois menos 4000 antes, em ns; na PRU, um degrau "
                   "só pode valer múltiplos de 5 ns (1 ciclo)."]
    return Resultado(fig, macros, comentarios)


@figura("grade_teto", "T7f: amostras fora da grade contra a taxa, 1 tick por vez (o teto com período constante)")
def grade_teto(estilo: Estilo) -> Resultado:
    resumo = PASTA_T7F / "resumo.csv"
    _exigir(resumo)
    with open(resumo, newline="", encoding="utf-8") as arquivo:
        linhas = list(csv.DictReader(arquivo))
    teto = sorted((int(round(200e6 / int(li["taxa_pedida_hz"]))), int(li["amostras_atrasadas"]),
                   li["folga_ciclos"]) for li in linhas if li["parte"] == "J")
    ticks = np.array([x[0] for x in teto])
    atrasadas = np.array([x[1] for x in teto])
    taxa = 200e6 / ticks / 1e3
    folgas = [int(li["folga_ciclos"]) for li in linhas if li["parte"] in "GHK" and li["folga_ciclos"]]
    exato = ticks[atrasadas == 0].min()
    ultimo_exato_seguido = min(t for t in ticks if np.all(atrasadas[ticks >= t] == 0))
    comuns = ticks[atrasadas > 2].max()
    todas = ticks[atrasadas >= 0.99 * 2 * 1048576 - 64].max()

    fig = estilo.nova_figura(0.45)
    eixo = fig.subplots()
    eixo.set_yscale("symlog", linthresh=1, linscale=0.6)
    eixo.plot(taxa, atrasadas, marker="o", color=COR["tinta"], markeredgecolor="white", markeredgewidth=0.5,
              linewidth=0.6, zorder=3)
    eixo.axvline(312.5, color=COR["modelo"], linewidth=0.8, linestyle=(0, (5, 3)), zorder=2)
    eixo.annotate(f"{estilo.t('padrao')} ({estilo.num(312.5, 1)} kS/s)",
                  xy=(312.5, 1e5), xytext=(4, 0), textcoords="offset points", color=COR["modelo"],
                  fontsize=estilo.formato.fonte_ticks_pt, va="center")
    eixo.set_xlabel(estilo.t("taxa_ks"))
    eixo.set_ylabel(estilo.t("atrasadas"))
    eixo.xaxis.set_major_formatter(estilo.formatador(0))
    eixo.set_ylim(-0.3, 4e6)
    log.info(f"  sem nenhuma atrasada até {ultimo_exato_seguido} ticks ({200e3 / ultimo_exato_seguido:.2f} kS/s); "
             f"amostras comuns atrasadas a partir de {comuns} ticks ({200e3 / comuns:.1f} kS/s); todas a partir de "
             f"{todas} ticks ({200e3 / todas:.1f} kS/s); folga mínima no padrão: {min(folgas)} ciclos")
    macros = {
        "GradeFolgaMin": str(min(folgas)),
        "GradeFolgaMinNs": rf"\qty{{{5 * min(folgas)}}}{{\nano\second}}",
        "GradeTetoConstante": rf"\num{{{200e3 / ultimo_exato_seguido:.1f}}}",
        "GradeTetoTrocas": rf"\num{{{200e3 / (comuns + 1):.1f}}}",
        "GradeTetoComuns": rf"\num{{{200e3 / comuns:.1f}}}",
        "GradeTetoTodas": rf"\num{{{200e3 / todas:.1f}}}",
    }
    comentarios = [f"Dados: {resumo.relative_to(DADOS)} (parte J: 2 blocos por taxa, 1 troca de buffer cada)",
                   f"Taxas em kS/s; folga mínima das capturas G/H/K no padrão: {sorted(folgas)} ciclos; "
                   f"a 1ª taxa sem atrasada depois de outra com atrasada é {200e3 / exato:.2f} kS/s (aleatório)."]
    return Resultado(fig, macros, comentarios)


@figura("grade_bits", "T7f: a fração de amostras atrasadas segue a fração de amostras com tantos bits 1 (quadro de "
                      "605 + bits 1 ciclos)")
def grade_bits(estilo: Estilo) -> Resultado:
    """A descoberta de 22/10/2026: no firmware do T7f, um bit 1 lido esticava o SCLK em 1 ciclo, e o quadro durava
    B + (bits 1 da amostra) ciclos. Uma amostra sai atrasada quando o quadro da anterior passa do período T:
    fração(T) = P(bits 1 >= T - B + 1), com a distribuição de bits 1 tirada das próprias amostras."""
    resumo = PASTA_T7F / "resumo.csv"
    referencia = PASTA_T7F / "J_cspadrao_312500_tom.bin"
    _exigir(resumo, referencia)
    with open(resumo, newline="", encoding="utf-8") as arquivo:
        linhas = [li for li in csv.DictReader(arquivo) if li["parte"] == "J"]
    ticks = np.array([int(round(200e6 / int(li["taxa_pedida_hz"]))) for li in linhas])
    cab = ler_cabecalho(referencia)
    codigos = np.memmap(referencia, dtype="<u2", mode="r", offset=cab.tamanho_cabecalho)
    bits = np.unpackbits(np.asarray(codigos[1:]).view(np.uint8)).reshape(-1, 16).sum(axis=1)
    cauda = np.array([(bits >= m).mean() for m in range(18)])         # P(bits 1 >= m), m = 0..17
    n = np.array([int(li["amostras_atrasadas"]) for li in linhas])
    fracao = n / (2 * cab.samples_per_buffer)

    def prevista(base: int, t):
        m = np.clip(np.asarray(t) - base + 1, 0, 17)
        return cauda[m]
    # B pelo melhor acordo (em log) onde a contagem é limpa: só amostras comuns, poucas seguidas (fração < 5 %)
    usar = (n > 2) & (fracao < 0.05)
    base = min(range(590, 620), key=lambda b: float(np.sum((np.log10(prevista(b, ticks[usar]) + 1e-12)
                                                             - np.log10(fracao[usar])) ** 2)))
    razao = fracao[usar] / prevista(base, ticks[usar])

    fig = estilo.nova_figura(0.5)
    eixo = fig.subplots()
    ordem = np.argsort(ticks)
    tm = np.arange(ticks.min(), ticks.max() + 1)
    eixo.plot(tm, prevista(base, tm), drawstyle="steps-mid", color=COR["modelo"], linewidth=estilo.formato.linha_pt,
              alpha=0.8, zorder=2, label=estilo.t("bits_prevista").format(base=base))
    # A partir de B + 15 ciclos só 0xFFFF (16 bits 1) atrasaria: as 1 ou 2 atrasadas são a troca de buffer (1 por captura).
    tk, fr, nn = ticks[ordem], fracao[ordem], n[ordem]
    so_troca = (nn > 0) & (tk >= base + 15)
    comuns = (nn > 0) & ~so_troca
    eixo.plot(tk[comuns], fr[comuns], linestyle="none", marker="o", color=COR["tinta"], markeredgecolor="white",
              markeredgewidth=0.5, zorder=3, label=estilo.t("bits_medida"))
    eixo.plot(tk[so_troca], fr[so_troca], linestyle="none", marker="s", markerfacecolor="none",
              markeredgecolor=COR["destaque"], markeredgewidth=0.9, zorder=3, label=estilo.t("bits_troca"))
    eixo.set_yscale("log")
    eixo.set_ylim(1e-7, 2)
    eixo.invert_xaxis()
    eixo.set_xlabel(estilo.t("periodo_ciclos"))
    eixo.set_ylabel(estilo.t("fracao_atrasadas"))
    eixo.legend(loc="upper left")
    log.info(f"  quadro = {base} + bits 1 ciclos; medida/prevista nos {int(usar.sum())} períodos com contagem limpa: "
             f"{razao.min():.2f} a {razao.max():.2f}")
    i619 = int(np.nonzero(ticks == base + 14)[0][0]) if np.any(ticks == base + 14) else None
    macros = {
        "GradeBitsBase": str(base),
        "GradeBitsRazaoMin": rf"\num{{{razao.min():.2f}}}",
        "GradeBitsRazaoMax": rf"\num{{{razao.max():.2f}}}",
    }
    if i619 is not None:
        macros["GradeBitsPeriodoEx"] = str(base + 14)
        macros["GradeBitsMedidaEx"] = rf"\num{{{fracao[i619]:.2e}}}"
        macros["GradeBitsPrevistaEx"] = rf"\num{{{float(prevista(base, base + 14)):.2e}}}"
    comentarios = [f"Dados: {resumo.relative_to(DADOS)} (parte J) e a distribuição de bits 1 de {referencia.name} "
                   f"({cab.versao_firmware})",
                   "Prevista: fração de amostras com bits 1 >= T - B + 1; B ajustado onde só há amostras comuns "
                   "isoladas atrasadas (fração < 5 %)."]
    return Resultado(fig, macros, comentarios)


# ---- figuras de tela (README) ---------------------------------------------------------------------------
# O GitHub mostra o README claro ou escuro conforme o visitante: fundo transparente e só cores legíveis nos dois
# (contraste >= 3:1 contra o branco e contra o #0d1117 do tema escuro; laranja e azul separáveis também para
# daltônicos). Texto em sans-serif convertido em curvas: o SVG fica igual em qualquer navegador.
README_COR = {"texto": "#7d8590", "grade": (0.49, 0.52, 0.56, 0.28), "medido": "#e36209", "modelo": "#388bfd"}
README_RC = {
    "text.usetex": False,
    "font.family": "sans-serif",
    "font.sans-serif": ["Fira Sans", "DejaVu Sans"],
    "font.size": 13,
    "axes.labelsize": 13,
    "xtick.labelsize": 11.5,
    "ytick.labelsize": 11.5,
    "legend.fontsize": 11.5,
    "axes.unicode_minus": True,
    "text.color": README_COR["texto"],
    "axes.labelcolor": README_COR["texto"],
    "axes.edgecolor": README_COR["texto"],
    "xtick.color": README_COR["texto"],
    "ytick.color": README_COR["texto"],
    "axes.linewidth": 1.0,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": README_COR["grade"],
    "grid.linewidth": 0.8,
    "axes.facecolor": "none",
    "figure.facecolor": "none",
    "savefig.facecolor": "none",
    "svg.fonttype": "path",
    "svg.hashsalt": "sh-analyzer",      # ids fixos: gerar de novo, com os mesmos dados, não muda o arquivo
}
PASTA_IMAGENS_README = RAIZ / "docs" / "images"


def _virgula(casas: int) -> FuncFormatter:
    return FuncFormatter(lambda v, _p: f"{0.0 if abs(v) < 1e-12 else v:.{casas}f}".replace(".", ",").replace("-", "−"))


def _hz(valor: float, _pos=None) -> str:
    return f"{valor:.0f} Hz" if valor < 1e3 else f"{valor / 1e3:.0f} kHz"


@figura("readme_cadeia_tensao", "A mesma resposta da cadeia de tensão, para o README (SVG transparente, tema claro e escuro)")
def readme_cadeia_tensao(_estilo: Estilo) -> Resultado:
    """Mesmos dados e ajuste de ``perfil_cadeia_tensao``, desenhados para a tela (não usa o Estilo do documento)."""
    _, f, g, ajustes = _cadeia_tensao()
    aj = ajustes["ordem2"]
    k, f0, q = aj.parametros
    f3 = freq_menos_3db(f0, q)
    y3 = 20 * math.log10(k) - 3
    y = 20 * np.log10(g)
    xmin, xmax = f.min() / 1.25, f.max() * 1.12
    fm = np.geomspace(xmin, xmax, 600)
    ym = mag_db_ordem2(fm, *aj.parametros)
    cor = README_COR

    with rc_sobre_padroes(README_RC):
        fig = plt.figure(figsize=(9, 5.4), layout="constrained")
        fig.get_layout_engine().set(w_pad=0.25, h_pad=0.2)
        eixo, eixo_res = fig.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [3.2, 1]})
        for ax in (eixo, eixo_res):
            ax.spines[["top", "right"]].set_visible(False)

        curva, = eixo.plot(fm, ym, color=cor["modelo"], linewidth=2.2, zorder=2, label="Ajuste: passa-baixa de 2ª ordem")
        medidos, = eixo.plot(f, y, linestyle="none", marker="o", markersize=7, markeredgewidth=0, color=cor["medido"],
                             zorder=3, label=f"Medido ({len(f)} pontos)")
        eixo.plot([f3, f3], [-100, y3], color=cor["texto"], linewidth=1, linestyle=(0, (1.5, 2.5)), zorder=1)
        eixo.plot([f3], [y3], marker="o", markersize=8, markerfacecolor="none", markeredgecolor=cor["modelo"],
                  markeredgewidth=1.8, linestyle="none", zorder=4)
        eixo.annotate(f"−3 dB em {f3 / 1e3:.1f} kHz".replace(".", ","), xy=(f3, y3), xytext=(-12, -6),
                      textcoords="offset points", ha="right", va="top", fontsize=12)
        eixo.set_ylim(min(y.min(), ym.min()) - 0.8, 1.0)
        eixo.yaxis.set_major_locator(MultipleLocator(3))
        eixo.yaxis.set_major_formatter(_virgula(0))
        eixo.set_ylabel("Ganho normalizado (dB)")
        legenda = eixo.legend(handles=[medidos, curva], loc="lower left", borderpad=0.6, fancybox=False)
        legenda.get_frame().set(facecolor="none", edgecolor=cor["grade"], linewidth=0.8)

        lim = max(0.3, 1.25 * float(np.max(np.abs(aj.residuos_db))))
        eixo_res.axhline(0, color=cor["modelo"], linewidth=1.4, alpha=0.8, zorder=2)
        eixo_res.plot(f, aj.residuos_db, linestyle="none", marker="o", markersize=5.5, markeredgewidth=0,
                      color=cor["medido"], zorder=3)
        eixo_res.set_ylim(-lim, lim)
        eixo_res.yaxis.set_major_locator(MaxNLocator(nbins=3, symmetric=True, steps=[1, 2, 2.5, 5, 10]))
        eixo_res.yaxis.set_major_formatter(_virgula(1))
        eixo_res.set_ylabel("Resíduo (dB)")

        eixo_res.set_xscale("log")
        eixo_res.set_xlim(xmin, xmax)
        eixo_res.xaxis.set_major_locator(FixedLocator([10, 100, 1e3, 1e4, 1e5]))
        eixo_res.xaxis.set_major_formatter(FuncFormatter(_hz))
        eixo_res.xaxis.set_minor_locator(LogLocator(base=10, subs=np.arange(2, 10)))
        eixo_res.xaxis.set_minor_formatter(NullFormatter())
        eixo_res.set_xlabel("Frequência")
        fig.align_ylabels([eixo, eixo_res])
    return Resultado(fig, destino=PASTA_IMAGENS_README / "voltage-chain-response.svg", rc=README_RC)


# =====================================================================================================
# Linha de comando
# =====================================================================================================
def _relativo(caminho: Path) -> Path:
    return caminho.relative_to(RAIZ) if caminho.is_relative_to(RAIZ) else caminho


def escrever_macros(caminho: Path, nome: str, resultado: Resultado) -> None:
    linhas = [f"% Gerado por report/gerar_figuras.py ({nome}) -- não edite à mão: rode o script de novo.",
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
    p.add_argument("--saida", type=Path, default=None,
                   help="Pasta de saída (padrão: report/figures/; as figuras do README vão direto para docs/images/).")
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
    saida = args.saida or PASTA_FIGURAS
    sufixo = "" if (args.formato, args.idioma) == ("relatorio", "pt") else f"_{args.formato}_{args.idioma}"

    faltaram = []
    for nome in args.nomes or list(FIGURAS):
        funcao, _ = FIGURAS[nome]
        log.info(f"{nome}:")
        try:
            resultado = funcao(estilo)
        except FileNotFoundError as erro:          # figura de bancada sem as capturas aqui: as outras seguem
            log.warning(f"{nome}: {erro}")
            faltaram.append(nome)
            continue
        if resultado.destino is not None:       # figura do README: arquivo fixo, sem data (não muda à toa no git)
            destino = args.saida / resultado.destino.name if args.saida else resultado.destino
            destino.parent.mkdir(parents=True, exist_ok=True)
            with rc_sobre_padroes(resultado.rc):
                resultado.figura.savefig(destino, metadata={"Date": None})
            plt.close(resultado.figura)
            log.info(f"  -> {_relativo(destino)}")
            continue
        saida.mkdir(parents=True, exist_ok=True)
        base = saida / f"{nome}{sufixo}"
        resultado.figura.savefig(base.with_suffix(".pdf"))
        if args.png:
            resultado.figura.savefig(base.with_suffix(".png"))
        plt.close(resultado.figura)
        if resultado.macros:
            escrever_macros(base.with_suffix(".tex"), nome, resultado)
        log.info(f"  -> {_relativo(base.with_suffix('.pdf'))}")
    return 1 if faltaram and args.nomes else 0


if __name__ == "__main__":
    raise SystemExit(main())
