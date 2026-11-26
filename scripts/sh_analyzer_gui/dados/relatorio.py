"""O relatório da captura (sem Qt): uma página HTML só, que se lê no navegador, se imprime e vira PDF, com o que
um caderno de laboratório, o relatório da FAPESP ou o anexo de um artigo pedem de cada captura:

* **as fontes**: o cabeçalho (o mesmo do inspetor), a integridade (o CRC das amostras) e os avisos do motor;
* **cada traço** da vista de tempo (o canal com a cadeia dele: a sonda, os filtros, a escala): os índices de
  qualidade da IEC 61000-4-30 (as estatísticas das janelas de 10/12 ciclos, sem as marcadas), as bandas IEC
  61000-4-7 de maior P95, os eventos e duas figuras (as bandas por frequência e o RMS e o THD no tempo);
* **a proveniência**: quem gerou, quando, com qual versão, e a cadeia de cada traço.

As contas são as das vistas (``qualidade.indices``, ``qualidade.eventos``, ``espectros.bandas_do_trecho``), no
trecho inteiro de cada traço, e rodam numa tarefa (``calcular_traco``). O texto é escapado; as figuras vão dentro
da página (PNG em base64), para o arquivo andar sozinho.
"""

from __future__ import annotations

import base64
import datetime
import html
import io
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
import supraharmonicos.api as api
from cycler import cycler

from . import espectros as esp
from . import qualidade as q

BANDAS_NA_TABELA = 12
EVENTOS_NA_TABELA = 50
LARGURA_DA_FIGURA_POL = 6.4
DPI = 130


@dataclass(frozen=True)
class FonteDoRelatorio:
    nome: str
    cabecalho: Sequence[tuple[str, Sequence[tuple[str, str]]]]     # as seções do ``api.descrever_cabecalho``
    integridade: str                       # o texto ("confere", "não confere", "sem o CRC", "não conferida")
    avisos: Sequence[str] = ()


@dataclass
class TracoDoRelatorio:
    nome: str
    unidade: str
    descricao: str                         # o canal, a captura e a cadeia
    indices: q.IndicesDeQualidade | None = None
    bandas: api.ResultadoBandasIEC | None = None
    eventos: list = field(default_factory=list)
    erros: list[str] = field(default_factory=list)
    figuras: list[tuple[str, bytes]] = field(default_factory=list)      # (a legenda, o PNG)


@dataclass(frozen=True)
class Relatorio:
    titulo: str
    fontes: Sequence[FonteDoRelatorio]
    tracos: Sequence[TracoDoRelatorio]
    aplicativo: str                        # "SH-Analyzer 0.9.0"
    gerado_em: datetime.datetime
    notas: str = ""


# ---------------------------------------------------------------------- as contas de um traço

def calcular_traco(trecho: esp.TrechoDoTraco, nome: str, unidade: str, descricao: str, *, tensao: bool,
                   numero: Callable[[float, int], str], separador: str = ".",
                   progresso: Callable[[float], None] | None = None,
                   cancelado: Callable[[], bool] | None = None) -> TracoDoRelatorio:
    """Os índices, as bandas e os eventos do trecho (cada conta que falha vira um erro no relatório, e as outras
    seguem). ``tensao``: procurar afundamentos, elevações e interrupções (o traço é uma tensão); ``separador``: o
    decimal dos números das figuras."""
    t = TracoDoRelatorio(nome, unidade, descricao)
    passo = (lambda a, b: (lambda f: progresso(a + (b - a) * f))) if progresso is not None else (lambda a, b: None)
    try:
        t.indices = q.indices(trecho, progresso=passo(0.0, 0.45), cancelado=cancelado)
    except (api.ErroSHAN, esp.AguardandoMaterializacao) as e:
        t.erros.append(f"índices de qualidade: {e}")
    if cancelado is not None and cancelado():
        return t
    try:
        t.bandas = esp.bandas_do_trecho(trecho, esp.OpcoesDasBandas().parametros, progresso=passo(0.45, 0.8),
                                        cancelado=cancelado)
    except (api.ErroSHAN, esp.AguardandoMaterializacao) as e:
        t.erros.append(f"bandas IEC: {e}")
    if cancelado is not None and cancelado():
        return t
    try:
        t.eventos = q.eventos(trecho, q.CriteriosDosEventos(tensao=tensao), indices_prontos=t.indices,
                              progresso=passo(0.8, 0.95), cancelado=cancelado, numero=numero)
    except (api.ErroSHAN, esp.AguardandoMaterializacao) as e:
        t.erros.append(f"eventos: {e}")
    t.figuras = figuras_do_traco(t, separador)
    if progresso is not None:
        progresso(1.0)
    return t


def estatisticas_sem_as_marcadas(indices: q.IndicesDeQualidade) -> tuple[dict, int]:
    """As estatísticas sem as janelas marcadas (IEC 61000-4-30) e quantas foram tiradas."""
    marcadas = indices.marcadas()
    if marcadas.any() and not marcadas.all():
        return indices.estatisticas_de(~marcadas), int(marcadas.sum())
    return indices.estatisticas, 0


# ---------------------------------------------------------------------- as figuras

RC = {"font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"], "font.size": 8.0, "axes.titlesize": 8.5,
      "axes.labelsize": 8.0, "axes.grid": True, "grid.alpha": 0.35, "grid.linewidth": 0.5, "lines.linewidth": 1.0,
      "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": DPI, "savefig.dpi": DPI,
      "axes.prop_cycle": cycler(color=["#1f5fa8", "#c2410c", "#4d7c0f", "#7e22ce"])}


VAO_MINIMO_RELATIVO = 0.01
"""O menor vão do eixo y de um índice, relativo ao valor (o mesmo da vista Qualidade): uma variação de 0,002 V em
127 V não ocupa a altura toda."""


def figuras_do_traco(t: TracoDoRelatorio, separador: str = ".") -> list[tuple[str, bytes]]:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import ScalarFormatter

    class ComSeparador(ScalarFormatter):
        def __call__(self, x, pos=None):
            return super().__call__(x, pos).replace(".", separador)

    def formatar(ax) -> None:
        for eixo in (ax.xaxis, ax.yaxis):
            eixo.set_major_formatter(ComSeparador(useOffset=False))

    from .desenho_da_figura import no_estilo

    figuras = []
    with no_estilo(RC):
        if t.bandas is not None and len(t.bandas.bandas.centros_hz):
            b = t.bandas.bandas
            est = b.estatisticas()
            fig = Figure(figsize=(LARGURA_DA_FIGURA_POL, 2.3))
            FigureCanvasAgg(fig)
            ax = fig.add_subplot()
            ref = " (dBµV)" if t.unidade == "V" else (" (dBµA)" if t.unidade == "A" else " (dB)")
            with np.errstate(divide="ignore"):
                ax.plot(b.centros_hz / 1e3, 20 * np.log10(np.maximum(est["p95"], 1e-12) / 1e-6), label="P95")
                ax.plot(b.centros_hz / 1e3, 20 * np.log10(np.maximum(est["maximo"], 1e-12) / 1e-6), label="máximo",
                        alpha=0.6)
            ax.set_xlabel("banda (kHz)")
            ax.set_ylabel("nível" + ref)
            formatar(ax)
            ax.legend(frameon=False, loc="upper right")
            fig.tight_layout()
            figuras.append(("As bandas de 200 Hz (IEC 61000-4-7, anexo B): o P95 e o máximo das janelas de 200 ms.",
                            _png(fig)))
        if t.indices is not None and t.indices.n_janelas > 1:
            r = t.indices
            fig = Figure(figsize=(LARGURA_DA_FIGURA_POL, 2.6))
            FigureCanvasAgg(fig)
            ax_rms, ax_thd = fig.subplots(2, 1, sharex=True)
            ax_rms.plot(r.inicios_s, r.valores["rms"])
            ax_rms.set_ylabel(f"RMS ({t.unidade})" if t.unidade else "RMS")
            ax_thd.plot(r.inicios_s, 100 * r.valores["thd"], color="#c2410c")
            ax_thd.set_ylabel("THD (%)")
            ax_thd.set_xlabel("tempo (s)")
            for ax, y in ((ax_rms, r.valores["rms"]), (ax_thd, 100 * r.valores["thd"])):
                _enquadrar(ax, y)
                formatar(ax)
            marcadas = r.marcadas()
            for k in np.flatnonzero(marcadas):
                for ax in (ax_rms, ax_thd):
                    ax.axvspan(r.inicios_s[k], r.inicios_s[min(k + 1, r.n_janelas - 1)], color="#b91c1c",
                               alpha=0.15, lw=0)
            fig.tight_layout()
            figuras.append((f"O RMS e o THD de cada janela de {r.ciclos_por_janela} ciclos (IEC 61000-4-30)"
                            + (", com as marcadas em vermelho." if marcadas.any() else "."), _png(fig)))
    return figuras


def _enquadrar(ax, y) -> None:
    finitos = np.asarray(y, dtype=float)
    finitos = finitos[np.isfinite(finitos)]
    if not len(finitos):
        return
    baixo, alto = float(finitos.min()), float(finitos.max())
    vao = max(alto - baixo, VAO_MINIMO_RELATIVO * max(abs(baixo), abs(alto)), 1e-12)
    meio = (alto + baixo) / 2
    ax.set_ylim(meio - 0.55 * vao, meio + 0.55 * vao)


def _png(fig) -> bytes:
    saida = io.BytesIO()
    fig.savefig(saida, format="png")
    return saida.getvalue()


# ---------------------------------------------------------------------- o HTML

CSS = """
body { font-family: "Inter", "Segoe UI", "DejaVu Sans", sans-serif; color: #1b1f24; max-width: 880px;
       margin: 32px auto; padding: 0 24px; font-size: 10.5pt; line-height: 1.45; }
h1 { font-size: 18pt; margin: 0 0 4px; }
h2 { font-size: 13pt; margin: 28px 0 8px; border-bottom: 1px solid #c9d1d9; padding-bottom: 4px; }
h3 { font-size: 11pt; margin: 18px 0 6px; }
.sub { color: #57606a; margin: 0 0 18px; }
table { border-collapse: collapse; margin: 6px 0 10px; font-size: 9.5pt; }
th, td { border-bottom: 1px solid #d8dee4; padding: 3px 10px 3px 0; text-align: left; vertical-align: top; }
th { color: #57606a; font-weight: 600; }
th.n { text-align: right; }
th.secao { color: #1b1f24; padding-top: 10px; }
td.n { text-align: right; font-variant-numeric: tabular-nums; }
.ok { color: #1a7f37; } .ruim { color: #b91c1c; } .mudo { color: #57606a; }
.aviso { color: #9a6700; }
figure { margin: 10px 0 14px; } figure img { width: 100%; max-width: 832px; }
figcaption { color: #57606a; font-size: 9pt; }
@media print { body { margin: 0; } h2 { page-break-after: avoid; } figure { page-break-inside: avoid; } }
"""


CSS_DO_QT = """
body { font-family: "Inter", "DejaVu Sans", sans-serif; color: #1b1f24; font-size: 9.5pt; }
h1 { font-size: 16pt; } h2 { font-size: 12.5pt; margin-top: 18px; } h3 { font-size: 10.5pt; margin-top: 12px; }
th { color: #57606a; font-weight: 600; text-align: left; } th.secao { color: #1b1f24; }
td, th { padding: 2px 8px 2px 0; } td.n { text-align: right; }
.ok { color: #1a7f37; } .ruim { color: #b91c1c; } .mudo { color: #57606a; } .sub { color: #57606a; }
.aviso { color: #9a6700; }
"""


def em_html(rel: Relatorio, numero: Callable[[float, str, int], str], *, para_o_qt: bool = False) -> str:
    """A página. ``numero(valor, unidade, dígitos)`` escreve os números (a interface passa o ``formatar_si``, com o
    separador das configurações). ``para_o_qt``: para o PDF do ``QTextDocument``, que só entende parte do CSS e
    recebe as figuras como recursos (``figura-N.png``, no lugar do base64)."""
    e = html.escape
    imagens_por_nome = para_o_qt
    partes = [f"<!DOCTYPE html>\n<html lang=\"pt-BR\"><head><meta charset=\"utf-8\"><title>{e(rel.titulo)}</title>",
              f"<style>{CSS_DO_QT if para_o_qt else CSS}</style></head><body>",
              f"<h1>{e(rel.titulo)}</h1>",
              f"<p class=\"sub\">Gerado em {rel.gerado_em:%d/%m/%Y %H:%M} pelo {e(rel.aplicativo)}.</p>"]
    if rel.notas.strip():
        partes.append(f"<p>{e(rel.notas.strip())}</p>")
    partes.append("<h2>As capturas</h2>")
    for f in rel.fontes:
        classe = {"confere": "ok", "não confere": "ruim"}.get(f.integridade, "mudo")
        partes.append(f"<h3>{e(f.nome)}</h3><table width=\"100%\">")
        partes.append(f"<tr><th>Integridade das amostras</th><td class=\"{classe}\">{e(f.integridade)}</td></tr>")
        for titulo, campos in f.cabecalho:
            partes.append(f"<tr><th colspan=\"2\" class=\"secao\">{e(titulo)}</th></tr>")
            partes.extend(f"<tr><td>{e(r)}</td><td>{e(v)}</td></tr>" for r, v in campos)
        partes.append("</table>")
        if f.avisos:
            partes.append("<ul>" + "".join(f"<li class=\"aviso\">{e(a)}</li>" for a in f.avisos) + "</ul>")
    contador = 0
    for t in rel.tracos:
        partes.append(f"<h2>{e(t.nome)}</h2><p class=\"sub\">{e(t.descricao)}</p>")
        for erro in t.erros:
            partes.append(f"<p class=\"aviso\">Não deu para calcular {e(erro)}</p>")
        if t.indices is not None:
            est, tiradas = estatisticas_sem_as_marcadas(t.indices)
            linhas = []
            for nome in q.INDICES:
                s = est[nome]
                linhas.append([q.NOMES_DOS_INDICES[nome]] + [_indice(nome, v, t.unidade, numero)
                                                             for v in (s.minimo, s.media, s.p95, s.p99, s.maximo)])
            partes.append("<h3>Qualidade de energia</h3>")
            partes.append(f"<p class=\"mudo\">{t.indices.n_janelas} janelas de {t.indices.ciclos_por_janela} "
                          f"ciclos" + (f", {tiradas} marcadas (fora das estatísticas)" if tiradas else "") + ".</p>")
            partes.append(_tabela(["Índice", "Mínimo", "Média", "P95", "P99", "Máximo"], linhas, numericas=True))
        if t.bandas is not None and len(t.bandas.bandas.centros_hz):
            b = t.bandas.bandas
            est = b.estatisticas()
            ordem = np.argsort(est["p95"])[::-1][:BANDAS_NA_TABELA]
            linhas = [[numero(float(b.centros_hz[i]), "Hz", 5)]
                      + [numero(float(est[k][i]), t.unidade, 4) for k in ("p95", "rms", "maximo")]
                      for i in ordem]
            partes.append(f"<h3>As {len(ordem)} bandas IEC de maior P95</h3>")
            partes.append(f"<p class=\"mudo\">{len(b.centros_hz)} bandas de {numero(b.largura_hz, 'Hz', 3)}, "
                          f"{e(b.descricao_janelas())}.</p>")
            partes.append(_tabela(["Banda", "P95", "RMS", "Máximo"], linhas, numericas=True))
        partes.append("<h3>Eventos</h3>")
        if not t.eventos:
            partes.append("<p class=\"mudo\">Nenhum evento no trecho.</p>")
        else:
            linhas = [[q.TIPOS_DE_EVENTO.get(ev.tipo, ev.tipo),
                       "—" if math.isnan(ev.inicio_s) else numero(ev.inicio_s, "s", 5),
                       "—" if math.isnan(ev.duracao_s) else numero(ev.duracao_s, "s", 3), ev.detalhe]
                      for ev in t.eventos[:EVENTOS_NA_TABELA]]
            partes.append(_tabela(["Tipo", "Início", "Duração", "Detalhe"], linhas))
            if len(t.eventos) > EVENTOS_NA_TABELA:
                partes.append(f"<p class=\"mudo\">E mais {len(t.eventos) - EVENTOS_NA_TABELA} eventos (a vista "
                              "Eventos tem a lista inteira).</p>")
        for legenda, png in t.figuras:
            contador += 1
            fonte = (f"figura-{contador}.png" if imagens_por_nome
                     else "data:image/png;base64," + base64.b64encode(png).decode("ascii"))
            if para_o_qt:
                partes.append(f"<p><img src=\"{fonte}\"><br><span class=\"mudo\">Figura {contador}: "
                              f"{e(legenda)}</span></p>")
            else:
                partes.append(f"<figure><img src=\"{fonte}\" alt=\"{e(legenda)}\">"
                              f"<figcaption>Figura {contador}: {e(legenda)}</figcaption></figure>")
    partes.append("<h2>A proveniência</h2>")
    linhas = [(e(t.nome), e(t.descricao)) for t in rel.tracos]
    partes.append(_tabela(["Traço", "Canal, captura e cadeia"], linhas, escapar=False))
    partes.append("<p class=\"mudo\">As contas são as das vistas do aplicativo (a <code>supraharmonicos.api</code>): "
                  "os índices e os eventos pela IEC 61000-4-30, as bandas pela IEC 61000-4-7 (anexo B), no trecho "
                  "inteiro de cada traço.</p>")
    partes.append("</body></html>\n")
    return "\n".join(partes)


def imagens(rel: Relatorio) -> list[bytes]:
    """Os PNG das figuras, na ordem do ``figura-N.png`` do :func:`em_html`."""
    return [png for t in rel.tracos for _legenda, png in t.figuras]


def _indice(nome: str, valor: float, unidade: str, numero) -> str:
    if not math.isfinite(valor):
        return "—"
    if nome == "thd":
        return numero(100 * valor, "%", 4)
    if nome == "frequencia":
        return numero(valor, "Hz", 6)
    if nome in q.INDICES_DE_RMS:
        return numero(valor, unidade, 4)
    return numero(valor, "", 4)


def _tabela(cabecalho, linhas, *, numericas: bool = False, escapar: bool = True) -> str:
    e = html.escape if escapar else (lambda x: x)
    partes = ["<table width=\"100%\">" if numericas else "<table>"]
    if cabecalho:
        partes.append("<tr>" + "".join(f"<th class=\"n\" align=\"right\">{html.escape(c)}</th>" if numericas and k
                                        else f"<th>{html.escape(c)}</th>" for k, c in enumerate(cabecalho)) + "</tr>")
    for linha in linhas:
        celulas = []
        for k, valor in enumerate(linha):
            classe = " class=\"n\" align=\"right\"" if numericas and k > 0 else ""
            celulas.append(f"<td{classe}>{e(str(valor))}</td>")
        partes.append("<tr>" + "".join(celulas) + "</tr>")
    partes.append("</table>")
    return "".join(partes)
