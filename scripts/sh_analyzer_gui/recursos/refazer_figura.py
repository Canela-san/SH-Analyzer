#!/usr/bin/env python3
"""Refaz a figura deste pacote a partir do ``dados.h5``, sem o SH-Analyzer: só NumPy, h5py e Matplotlib.

Uso (na pasta do pacote)::

    python refazer_figura.py                    # figura_refeita.png, comparada com a figura.png do pacote
    python refazer_figura.py --formato pdf      # ou svg, eps, png
    python refazer_figura.py --saida outra.png

O ``dados.h5`` descreve a figura como o SH-Analyzer a desenhou, já com o leiaute feito:

* ``/`` (atributos): ``largura_pol`` e ``altura_pol`` (a página, em polegadas), ``dpi``, ``rc`` (os parâmetros do
  Matplotlib, em JSON) e ``matplotlib`` (a versão que desenhou a figura);
* ``/eixos/NN`` (um por eixo, na ordem do desenho): o atributo ``eixo`` (JSON) com a posição na página (a fração da
  largura e da altura: ``[x0, y0, largura, altura]``), os limites, as escalas, as marcas de cada eixo e os textos delas,
  os rótulos, os títulos, os textos e a legenda;
* ``/eixos/NN/linhas/MM``: ``x`` e ``y``, os pontos de cada curva na resolução da figura (a redução M4 do
  SH-Analyzer: o mínimo, o máximo, o primeiro e o último ponto de cada coluna de pixels), e o atributo ``estilo``
  (JSON: a cor, a espessura, o tracejado, o marcador); ``rotulo`` é o nome do traço.

* ``/eixos/NN/insets/KK``: os insets do eixo (a ampliação de um trecho), descritos do mesmo jeito, com a posição na
  fração do eixo (``no_eixo``) e o estilo das linhas de ligação (``ligacoes``).

Os textos são os do ``ax.text`` e as anotações (o texto, a seta e a cota: ``ax.annotate``); as regiões são
``ax.axvspan``. A legenda de um eixo aponta as curvas por ``[eixo, linha]`` (a de fora do eixo junta as de várias
faixas): as legendas são postas depois de todos os eixos.

As fontes que a figura usa e não vêm com o Matplotlib estão em ``fontes/`` (com as licenças). Com a mesma versão do
Matplotlib, a figura refeita em PNG tem os mesmos pixels da ``figura.png``; com outra, pequenas diferenças no texto
são esperadas (o desenho das letras muda entre as versões).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import h5py
import matplotlib
import numpy as np
from matplotlib import font_manager, rc_context
from matplotlib import image as imagem
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FixedFormatter, FixedLocator, NullFormatter

AQUI = Path(__file__).resolve().parent
FORMATOS = ("png", "pdf", "svg", "eps")


def _texto(valor) -> str:
    return valor.decode("utf-8") if isinstance(valor, bytes) else str(valor)


def _json(valor):
    return json.loads(_texto(valor))


def registrar_as_fontes(pasta: Path) -> None:
    for arquivo in sorted(pasta.glob("*.ttf")) + sorted(pasta.glob("*.otf")):
        font_manager.fontManager.addfont(str(arquivo))


def montar(dados: h5py.File) -> Figure:
    """A figura do ``dados.h5`` (chame dentro do ``rc_context`` dele: o Matplotlib lê parte do estilo ao desenhar)."""
    atributos = dados.attrs
    figura = Figure(figsize=(float(atributos["largura_pol"]), float(atributos["altura_pol"])),
                    dpi=float(atributos["dpi"]))
    FigureCanvasAgg(figura)
    eixos, legendas = [], []
    for nome in sorted(dados["eixos"]):
        ax, legenda = _eixo(figura, dados["eixos"][nome])
        eixos.append(ax)
        legendas.append(legenda)
    for ax, legenda in zip(eixos, legendas):
        if legenda:
            ax.legend([eixos[i].lines[j] for i, j in legenda["linhas"]], legenda["textos"], loc="lower left",
                      bbox_to_anchor=legenda["canto"], bbox_transform=ax.transAxes, borderaxespad=0.0,
                      ncols=legenda.get("colunas", 1))
    return figura


def _estilo_da_linha(estilo: dict) -> dict:
    """O estilo do JSON para o ``plot`` (o ``markevery`` de duas frações é uma tupla, e não uma lista de índices)."""
    if isinstance(estilo.get("markevery"), list):
        estilo["markevery"] = tuple(estilo["markevery"])
    return estilo


def _eixo(figura: Figure, grupo: h5py.Group):
    e = _json(grupo.attrs["eixo"])
    ax = figura.add_axes(e["posicao"])
    _montar(ax, grupo, e)
    if "insets" in grupo:
        for nome in sorted(grupo["insets"]):
            g = grupo["insets"][nome]
            d = _json(g.attrs["eixo"])
            dentro = ax.inset_axes(d["no_eixo"])
            _montar(dentro, g, d)
            if d.get("ligacoes"):
                ax.indicate_inset_zoom(dentro, **d["ligacoes"])
    return ax, e.get("legenda")


def _coordenadas(valor):
    return tuple(valor) if isinstance(valor, list) else valor


def _montar(ax, grupo: h5py.Group, e: dict) -> None:
    """As curvas, as marcas, os limites, os títulos, as regiões e os textos de um eixo (ou de um inset)."""
    ax.set_xscale(e["x"]["escala"])
    ax.set_yscale(e["y"]["escala"])
    for nome in sorted(grupo["linhas"]):
        dados_da_linha = grupo["linhas"][nome]
        ax.plot(dados_da_linha["x"][:], dados_da_linha["y"][:], **_estilo_da_linha(_json(dados_da_linha.attrs["estilo"])))
    for k, eixo in (("x", ax.xaxis), ("y", ax.yaxis)):
        d = e[k]
        eixo.set_major_locator(FixedLocator(d["marcas"]))
        numeros = FixedFormatter(d["textos"])
        numeros.set_offset_string(d["deslocamento"])
        eixo.set_major_formatter(numeros)
        eixo.set_minor_locator(FixedLocator(d["marcas_menores"]))
        eixo.set_minor_formatter(FixedFormatter(d["textos_menores"]) if any(d["textos_menores"]) else NullFormatter())
        for qual in ("major", "minor"):
            if d["parametros"][qual]:
                ax.tick_params(axis=k, which=qual, **d["parametros"][qual])
        eixo.set_label_text(d["rotulo"])
        eixo.set_label_position(d.get("lado_do_rotulo", "bottom" if k == "x" else "left"))
        eixo.set_visible(d.get("visivel", True))
    ax.patch.set_visible(e.get("fundo", True))
    for nome, visivel in e.get("molduras", {}).items():
        ax.spines[nome].set_visible(visivel)
    ax.set_xlim(e["x"]["limites"])
    ax.set_ylim(e["y"]["limites"])
    for onde, titulo in e["titulos"].items():
        if titulo:
            ax.set_title(titulo, loc=onde)
    for f in e.get("faixas", []):
        ax.axvspan(f["x0"], f["x1"], **f["estilo"])
    for t in e["textos"]:
        if t.get("tipo") == "anotacao":
            ax.annotate(t["texto"], t["xy"], xytext=t["xytext"], xycoords=_coordenadas(t["xycoords"]),
                        textcoords=_coordenadas(t["textcoords"]), arrowprops=t["seta"],
                        annotation_clip=t["recorte"], **t["estilo"])
        else:
            ax.text(t["x"], t["y"], t["texto"], transform=ax.transAxes if t["em"] == "eixos" else ax.transData,
                    **t["estilo"])


def comparar(refeita: Path, original: Path) -> str:
    """Quantos pixels mudaram entre as duas imagens (as cores, sem a transparência)."""
    a = np.asarray(imagem.imread(refeita))[..., :3]
    b = np.asarray(imagem.imread(original))[..., :3]
    if a.shape != b.shape:
        return f"tamanhos diferentes: {a.shape[1]} × {a.shape[0]} e {b.shape[1]} × {b.shape[0]} pixels"
    diferentes = int(np.count_nonzero(np.any(a != b, axis=-1)))
    if diferentes == 0:
        return "os mesmos pixels da figura.png"
    return f"{diferentes} de {a.shape[0] * a.shape[1]} pixels diferentes da figura.png"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refaz a figura do pacote do SH-Analyzer a partir do dados.h5.")
    parser.add_argument("--formato", choices=FORMATOS, default="png")
    parser.add_argument("--saida", type=Path, help="o arquivo (padrão: figura_refeita.<formato>, nesta pasta)")
    parser.add_argument("--dados", type=Path, default=AQUI / "dados.h5")
    args = parser.parse_args(argv)
    registrar_as_fontes(AQUI / "fontes")
    saida = args.saida or AQUI / f"figura_refeita.{args.formato}"
    with h5py.File(args.dados, "r") as dados:
        rc = _json(dados.attrs["rc"])
        versao = _texto(dados.attrs["matplotlib"])
        with rc_context(rc):
            figura = montar(dados)
            figura.savefig(saida, format=args.formato, dpi=figura.dpi)
    print(f"figura refeita: {saida}")
    if versao != matplotlib.__version__:
        print(f"aviso: a figura foi desenhada com o Matplotlib {versao}, e este é o {matplotlib.__version__}")
    original = AQUI / "figura.png"
    if args.formato == "png" and original.exists():
        print(comparar(saida, original))
    return 0


if __name__ == "__main__":
    sys.exit(main())
