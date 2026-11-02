#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""gerar_marca.py -- a marca do SH-Analyzer em SVG: o banner do README, o logo e o ícone de aplicativo.

O símbolo é um ciclo da rede de 60 Hz em azul cuja metade negativa carrega, em âmbar, a ondulação de alta
frequência dos supraharmônicos. O banner põe o símbolo ao lado do nome e, embaixo, um espectro em escala log de
30 Hz a 300 kHz com a faixa de 2 a 150 kHz destacada: o símbolo é o sinal no tempo, a linha é o espectro dele.
O espectro é uma ilustração (semente fixa), não dados medidos.

Tudo sai em ``docs/images/``:

* ``banner-logo-spectrum-light.svg`` e ``-dark.svg``: o banner do README, de fundo transparente, um para cada tema
  do GitHub (o README escolhe com ``<picture>`` e ``prefers-color-scheme``);
* ``logo-light.svg`` e ``logo-dark.svg``: o símbolo sozinho, em contorno e transparente (README, documentação);
* ``app-icon.svg``: o ícone de aplicativo (a futura GUI), de 48 px para cima. Tem fundo próprio, porque aparece
  sobre qualquer área de trabalho ou aba: uma tela de osciloscópio pequena, no azul-marinho do banner antigo
  (``banner.svg``, que fica no repositório e não é gerado aqui);
* ``app-icon-small.svg``: o mesmo ícone para 16 a 32 px, simplificado (traço grosso, menos ondulação, sem grade nem
  brilho), porque nesses tamanhos a ondulação do desenho detalhado vira uma mancha.

Uso (na raiz do repositório)::

    uv run report/gerar_marca.py                 # refaz os seis SVGs em docs/images/
    uv run report/gerar_marca.py --saida PASTA   # grava em outra pasta, para comparar antes de trocar

A saída é determinística: rodar de novo sem mudar o código não muda nenhum arquivo, e ``tests/test_marca.py``
confere que os SVGs commitados são os que este script gera. Mudou o desenho? Rode o script e commite os SVGs.
Os textos ficam como ``<text>`` com as fontes do sistema de quem vê, então mudam um pouco de um sistema para outro.
"""

import argparse
import logging
import math
import random
from pathlib import Path

PASTA_IMAGENS = Path(__file__).resolve().parents[1] / "docs" / "images"

SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"

# Uma paleta por tema do GitHub (fundos #ffffff e #0d1117). No claro, o azul e o âmbar escurecem para manter o
# contraste, e o texto em âmbar escurece mais que o traço.
TEMAS = {
    "dark": dict(fg="#f0f6fc", muted="#8b949e", sutil="#8b949e", sky="#7dd3fc",
                 amber="#fbbf24", amber_texto="#fbbf24"),
    "light": dict(fg="#0f172a", muted="#57606a", sutil="#0f172a", sky="#0284c7",
                  amber="#d97706", amber_texto="#b45309"),
}

log = logging.getLogger("gerar_marca")


def svg_abre(largura, altura, desc):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largura} {altura}" width="{largura}" height="{altura}" '
            f'role="img" aria-labelledby="titulo desc">\n'
            f'  <title id="titulo">SH-Analyzer</title>\n'
            f'  <desc id="desc">{desc}</desc>\n')


# ---------------------------------------------------------------- o símbolo

def onda_marca(x0, x1, yc, amp, ciclos=9, ondulacao=0.24):
    """Um ciclo de 60 Hz; a metade negativa carrega a ondulação de alta frequência (``ciclos`` por período,
    com uma janela sen² para entrar e sair suave)."""
    pts = []
    n = 240
    for i in range(n + 1):
        u = i / n
        y = math.sin(2 * math.pi * u)
        janela = math.sin(math.pi * (u - 0.5) / 0.5) ** 2 if 0.5 <= u <= 1 else 0.0
        y += ondulacao * janela * math.sin(2 * math.pi * ciclos * u)
        pts.append(f"{x0 + (x1 - x0) * u:.2f},{yc - amp * y:.2f}")
    return "M" + " ".join(pts)


def simbolo(mx, my, lado, c, id_grad="traco-marca"):
    """``(defs, corpo)`` do símbolo em contorno (transparente), desenhado em 136 e escalado para ``lado``."""
    k = lado / 136
    meio = mx + lado / 2
    onda = onda_marca(mx + 20 * k, mx + lado - 20 * k, my + lado / 2, 36 * k)
    defs = f"""    <linearGradient id="{id_grad}" gradientUnits="userSpaceOnUse" x1="{meio - 6 * k:.1f}" y1="0" x2="{meio + 6 * k:.1f}" y2="0">
      <stop offset="0" stop-color="{c['sky']}"/>
      <stop offset="1" stop-color="{c['amber']}"/>
    </linearGradient>
"""
    corpo = f"""  <rect x="{mx}" y="{my}" width="{lado}" height="{lado}" rx="{34 * k:.1f}" fill="{c['sutil']}" fill-opacity="0.04" stroke="{c['sutil']}" stroke-opacity="0.3" stroke-width="{2 * k:.2f}"/>
  <line x1="{mx + 14 * k:.1f}" y1="{my + lado / 2:.1f}" x2="{mx + lado - 14 * k:.1f}" y2="{my + lado / 2:.1f}" stroke="{c['sutil']}" stroke-opacity="0.25" stroke-width="{1.5 * k:.2f}"/>
  <path d="{onda}" fill="none" stroke="url(#{id_grad})" stroke-width="{5.5 * k:.2f}" stroke-linecap="round" stroke-linejoin="round"/>
"""
    return defs, corpo


def nome(x, y, tamanho, c, anchor="start"):
    """O nome, com o "SH" em âmbar."""
    return (f'  <text x="{x}" y="{y}" text-anchor="{anchor}" font-family="{SANS}" font-size="{tamanho}" '
            f'font-weight="700" letter-spacing="-1.5" fill="{c["fg"]}"><tspan fill="{c["amber_texto"]}">SH</tspan>-Analyzer</text>\n')


def logo(tema):
    c = TEMAS[tema]
    defs, corpo = simbolo(1, 1, 134, c)
    return (svg_abre(136, 136, "Logo do SH-Analyzer: um ciclo da rede de 60 Hz com a ondulação de alta frequência "
                     "dos supraharmônicos na metade negativa. Fundo transparente.")
            + f"  <defs>\n{defs}  </defs>\n{corpo}</svg>\n")


# ---------------------------------------------------------------- o horizonte espectral

F_MIN, F_MAX, LARG = 30.0, 300e3, 1280.0


def x_de(f):
    return LARG * math.log10(f / F_MIN) / math.log10(F_MAX / F_MIN)


def espectro_db():
    """``(x, dB)`` de um espectro ilustrativo: 60 Hz, harmônicos ímpares caindo, um inversor em 16 kHz e
    múltiplos, um patamar largo em torno de 60 kHz e o piso de ruído."""
    rnd = random.Random(7)
    comp = [(60.0, 0.0, 0.004)]                 # (frequência, nível em dB, largura em décadas)
    for h in list(range(3, 22, 2)) + [2, 4]:
        nivel = -18 - 28 * math.log10(h) if h % 2 else -64
        comp.append((60.0 * h, nivel + rnd.uniform(-2.5, 2.5), 0.004))
    comp += [(16e3, -44, 0.006), (32e3, -53, 0.006), (48e3, -60, 0.006), (64e3, -66, 0.006),
             (9.6e3, -71, 0.005), (110e3, -63, 0.007), (60e3, -76, 0.12)]
    lf = [math.log10(F_MIN) + i * (math.log10(F_MAX / F_MIN)) / 1600 for i in range(1601)]
    lf += [math.log10(f) for f, _, _ in comp]   # os picos caem exatamente num ponto da grade
    lf.sort()
    ruido = 0.0
    pts = []
    for lg in lf:
        f = 10 ** lg
        ruido = 0.6 * ruido + 0.4 * rnd.gauss(0, 2.2)
        piso = -93 + 9 * math.exp(-((lg - math.log10(60)) ** 2) / 0.25) + ruido
        p = 10 ** (piso / 10)
        for fk, dbk, w in comp:
            p += 10 ** (dbk / 10) * math.exp(-0.5 * ((lg - math.log10(fk)) / w) ** 2)
        pts.append((x_de(f), max(-100.0, 10 * math.log10(p))))
    return pts


def horizonte(c, y_topo, y_base, rotulo=19):
    """``(defs, corpo)`` do espectro entre ``y_topo`` (0 dB) e ``y_base`` (-100 dB), de ponta a ponta."""
    def y_de(db):
        return y_topo + (y_base - y_topo) * (-db) / 100.0

    pts = [(x, y_de(db)) for x, db in espectro_db()]
    linha = "M" + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = linha + f" L{LARG:.1f},{y_base} L0,{y_base} Z"
    b0, b1 = x_de(2e3), x_de(150e3)
    ticks = [(60, "60 Hz", "start"), (2e3, "2 kHz", "middle"), (150e3, "150 kHz", "middle")]
    ticks_svg = "\n".join(
        f'    <line x1="{x_de(f):.1f}" y1="{y_base}" x2="{x_de(f):.1f}" y2="{y_base + 7}" stroke="{c["sutil"]}" stroke-opacity="0.45" stroke-width="1.5"/>\n'
        f'    <text x="{x_de(f) - (4 if a == "start" else 0):.1f}" y="{y_base + rotulo + 11}" text-anchor="{a}" fill="{c["muted"]}">{t}</text>'
        for f, t, a in ticks)
    defs = f"""    <linearGradient id="traco" gradientUnits="userSpaceOnUse" x1="{b0 - 30:.1f}" y1="0" x2="{b0 + 10:.1f}" y2="0">
      <stop offset="0" stop-color="{c['sky']}"/>
      <stop offset="1" stop-color="{c['amber']}"/>
    </linearGradient>
    <linearGradient id="desbota" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0.22"/>
      <stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
    <mask id="mascara-area"><rect x="0" y="{y_topo}" width="{LARG}" height="{y_base - y_topo}" fill="url(#desbota)"/></mask>
"""
    corpo = f"""  <rect x="{b0:.1f}" y="{y_topo}" width="{b1 - b0:.1f}" height="{y_base - y_topo}" fill="{c['amber']}" fill-opacity="0.07"/>
  <line x1="{b0:.1f}" y1="{y_topo}" x2="{b0:.1f}" y2="{y_base}" stroke="{c['amber']}" stroke-opacity="0.4" stroke-dasharray="3 4"/>
  <line x1="{b1:.1f}" y1="{y_topo}" x2="{b1:.1f}" y2="{y_base}" stroke="{c['amber']}" stroke-opacity="0.4" stroke-dasharray="3 4"/>
  <text x="{(b0 + b1) / 2:.1f}" y="{y_topo + rotulo + 7}" text-anchor="middle" font-family="{MONO}" font-size="{rotulo}" fill="{c['amber_texto']}">supraharmônicos · 2–150 kHz</text>

  <path d="{area}" fill="url(#traco)" mask="url(#mascara-area)"/>
  <path d="{linha}" fill="none" stroke="url(#traco)" stroke-width="2.2" stroke-linejoin="round"/>
  <line x1="0" y1="{y_base}" x2="{LARG}" y2="{y_base}" stroke="{c['sutil']}" stroke-opacity="0.35" stroke-width="1.5"/>
  <g font-family="{MONO}" font-size="{rotulo}">
{ticks_svg}
  </g>
"""
    return defs, corpo


# ---------------------------------------------------------------- o banner do README

def banner(tema):
    """O símbolo ao lado do nome, com o horizonte espectral embaixo; o símbolo fica sobre a fundamental de 60 Hz."""
    c = TEMAS[tema]
    d_simb, c_simb = simbolo(2, 4, 120, c)
    d_hor, c_hor = horizonte(c, 176, 300)
    return (svg_abre(1280, 342, "SH-Analyzer: o símbolo do projeto (um ciclo de 60 Hz com a ondulação dos "
                     "supraharmônicos) ao lado do nome, sobre um espectro em escala log de 30 Hz a 300 kHz, com a "
                     "fundamental de 60 Hz, os harmônicos e a faixa dos supraharmônicos (2 a 150 kHz) destacada. "
                     "Fundo transparente. Ilustração, não dados medidos.")
            + f"  <defs>\n{d_simb}{d_hor}  </defs>\n\n{c_simb}"
            + f'  <text x="150" y="36" fill="{c["amber_texto"]}" font-family="{SANS}" font-size="17" font-weight="600" letter-spacing="3.5">ANALISADOR DE SUPRAHARMÔNICOS</text>\n'
            + nome(146, 114, 84, c)
            + f'  <text x="1276" y="104" text-anchor="end" fill="{c["muted"]}" font-family="{SANS}" font-size="24">do sensor ao espectro</text>\n\n'
            + c_hor + "</svg>\n")


# ---------------------------------------------------------------- o ícone de aplicativo

def icone_app(pequeno=False):
    """512 x 512, com fundo próprio. O detalhado (grade de osciloscópio, brilho) é para 48 px ou mais; o pequeno
    (traço grosso, menos ondulação, sem grade) é para 16 a 32 px."""
    if pequeno:
        onda = onda_marca(84, 428, 250, 128, ciclos=6, ondulacao=0.36)
        largura, grade, brilho = 46, "", ""
    else:
        onda = onda_marca(100, 412, 250, 116)
        largura = 17
        linhas = [136, 196, 316, 376]
        grade = ('  <g stroke="#1a2a42" stroke-width="3">\n'
                 + "".join(f'    <line x1="{v}" y1="40" x2="{v}" y2="472"/>\n    <line x1="40" y1="{v}" x2="472" y2="{v}"/>\n'
                           for v in linhas)
                 + '  </g>\n  <line x1="40" y1="256" x2="472" y2="256" stroke="#2a3d5a" stroke-width="4"/>\n')
        brilho = f'  <path d="{onda}" fill="none" stroke="url(#traco-app)" stroke-width="{largura + 12}" stroke-opacity="0.3" stroke-linecap="round" stroke-linejoin="round" filter="url(#brilho)"/>\n'
    return (svg_abre(512, 512, "Ícone do SH-Analyzer: tela escura com um ciclo de 60 Hz em azul cuja metade "
                     "negativa carrega a ondulação dos supraharmônicos em âmbar.")
            + """  <defs>
    <linearGradient id="fundo" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0f1a2e"/>
      <stop offset="1" stop-color="#16243b"/>
    </linearGradient>
    <linearGradient id="traco-app" gradientUnits="userSpaceOnUse" x1="244" y1="0" x2="268" y2="0">
      <stop offset="0" stop-color="#7dd3fc"/>
      <stop offset="1" stop-color="#fbbf24"/>
    </linearGradient>
    <filter id="brilho" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="10"/></filter>
    <clipPath id="placa"><rect x="16" y="16" width="480" height="480" rx="112"/></clipPath>
  </defs>
  <rect x="16" y="16" width="480" height="480" rx="112" fill="url(#fundo)"/>
  <g clip-path="url(#placa)">
""" + grade + brilho
            + f'  <path d="{onda}" fill="none" stroke="url(#traco-app)" stroke-width="{largura}" stroke-linecap="round" stroke-linejoin="round"/>\n'
            + """  </g>
  <rect x="17.5" y="17.5" width="477" height="477" rx="110.5" fill="none" stroke="#ffffff" stroke-opacity="0.1" stroke-width="3"/>
</svg>
""")


# ---------------------------------------------------------------- saída

def svgs() -> dict[str, str]:
    """Os seis arquivos da marca: nome em ``docs/images/`` -> conteúdo."""
    arquivos = {}
    for tema in ("light", "dark"):
        arquivos[f"banner-logo-spectrum-{tema}.svg"] = banner(tema)
        arquivos[f"logo-{tema}.svg"] = logo(tema)
    arquivos["app-icon.svg"] = icone_app()
    arquivos["app-icon-small.svg"] = icone_app(pequeno=True)
    return arquivos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera o banner do README, o logo e o ícone de aplicativo (SVG).")
    parser.add_argument("--saida", type=Path, default=PASTA_IMAGENS,
                        help="pasta de saída (padrão: docs/images/)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args.saida.mkdir(parents=True, exist_ok=True)
    for nome_arquivo, conteudo in svgs().items():
        destino = args.saida / nome_arquivo
        destino.write_text(conteudo, encoding="utf-8")
        log.info(f"-> {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
