"""O pacote reproduzível da figura (a F5.6; docs/gui-plan.md, 10.5; FG-08), sem Qt: um ``.zip`` que quem recebe
(um revisor, um repositório de dados) abre e refaz a figura sem o SH-Analyzer. Dentro de uma pasta com o nome do
pacote:

* ``figura.<formato>``: a figura no formato da exportação escolhida, e ``figura.png`` (a referência dos pixels, no
  mesmo dpi até :data:`DPI_DA_REFERENCIA`, ou no maior que a página aguenta);
* ``dados.h5``: a figura descrita como ficou depois do desenho: a posição de cada eixo que o leiaute achou, os
  limites, as escalas, as marcas e os textos delas, os rótulos, os títulos, a legenda, os textos e cada curva na
  resolução da figura (a redução M4), com o estilo (a descrição do leiaute está no ``refazer_figura.py``);
* ``refazer_figura.py`` (``recursos/``): refaz a figura só com NumPy, h5py e Matplotlib, e diz se ela tem os mesmos
  pixels da ``figura.png``;
* ``fontes/``: as fontes do aplicativo que a figura usa (a STIX e a DejaVu vêm com o Matplotlib), com as licenças;
* ``proveniencia.json`` e ``LEIA-ME.md``.

**Um desenho só** dá todos os arquivos: os dados do ``dados.h5`` são os pontos que estão nas figuras. A descrição é
lida depois do desenho da ``figura.png`` (o último): o script põe os eixos nas posições dele e dá os mesmos pixels,
com a mesma versão do Matplotlib.

**O que a descrição não conhece** (um artista que o desenho das figuras ainda não usa: uma imagem, uma área
preenchida) recusa o pacote com a razão: um pacote que não refaz a figura não sai. Ela conhece (F5.8) as anotações
(o texto, a seta e a cota são ``annotate``; a região, um ``axvspan``) e os insets (um eixo dentro do eixo, na fração
dele, com as linhas de ligação do ``indicate_inset_zoom``).
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib
import numpy as np
from matplotlib import font_manager
from matplotlib.colors import to_hex
from matplotlib.inset import InsetIndicator
from matplotlib.patches import Rectangle
from matplotlib.text import Annotation
from supraharmonicos.api import ErroSHAN

from .desenho_da_figura import PASTA_DAS_FONTES, DadosDaFigura, PaginaDesenhada, no_estilo, registrar_as_fontes
from .exportar_figura import (
    OpcoesDeExportacao,
    conferir,
    desenhar_para_exportar,
    dpi_maximo,
    gravar,
    parametros_da_gravacao,
    parte_do_progresso,
)
from .figura import Figura
from .projeto import VistaSalva

FORMATO = "sh-analyzer-figura"
VERSAO = 2
DPI_DA_REFERENCIA = 600.0
SCRIPT = Path(__file__).resolve().parents[1] / "recursos" / "refazer_figura.py"
ESTILO_DA_LINHA = ("color", "linestyle", "linewidth", "alpha", "antialiased", "rasterized", "zorder", "label",
                   "marker", "markersize", "markevery", "markerfacecolor", "markeredgecolor", "markeredgewidth",
                   "fillstyle", "drawstyle", "dash_capstyle", "dash_joinstyle", "solid_capstyle", "solid_joinstyle")
ESTILO_DO_TEXTO = ("color", "fontsize", "fontweight", "fontstyle", "horizontalalignment", "verticalalignment",
                   "rotation", "zorder")
ESTILO_DA_FAIXA = ("facecolor", "edgecolor", "alpha", "linewidth", "zorder")


class PacoteInvalido(ErroSHAN, ValueError):
    """O pacote não pode sair (a razão vai na mensagem)."""


# ------------------------------------------------------------------ a descrição da figura desenhada

def descrever(pagina: PaginaDesenhada) -> list[tuple[dict, list, list]]:
    """Cada eixo da página **depois de desenhada** (as posições são as do leiaute desse desenho): a descrição dele,
    as curvas (``x``, ``y`` e o estilo) e os insets (cada um, a descrição e as curvas dele). Rode dentro do
    ``rc_context`` do desenho: o localizador das marcas conta quantas cabem pelo tamanho dos números, que vem do
    estilo."""
    mpl = pagina.mpl
    for nome in ("texts", "lines", "patches", "images", "legends", "artists", "subfigs"):
        if getattr(mpl, nome, None):
            raise PacoteInvalido(f"o pacote ainda não descreve {nome} na página")
    renderizador = mpl.canvas.get_renderer()
    saida = []
    for ax in mpl.axes:
        descricao, linhas = _descrever_o_eixo(ax, mpl.axes, renderizador)
        descricao["posicao"] = [float(v) for v in ax.get_position().bounds]
        insets = []
        for dentro in ax.child_axes:
            d, curvas = _descrever_o_eixo(dentro, mpl.axes, renderizador)
            pai, filho = ax.get_position(), dentro.get_position()
            d["no_eixo"] = [(filho.x0 - pai.x0) / pai.width, (filho.y0 - pai.y0) / pai.height,
                            filho.width / pai.width, filho.height / pai.height]
            d["ligacoes"] = _ligacoes(ax, dentro)
            insets.append((d, curvas))
        saida.append((descricao, linhas, insets))
    return saida


def _descrever_o_eixo(ax, eixos, renderizador) -> tuple[dict, list]:
    _conferir_os_artistas(ax)
    linhas = [(np.asarray(linha.get_xdata(), dtype=np.float64), np.asarray(linha.get_ydata(), dtype=np.float64),
               _estilo(linha, ESTILO_DA_LINHA)) for linha in ax.lines]
    return {
        "x": _eixo(ax.xaxis, ax.get_xlim(), ax.get_xscale()),
        "y": _eixo(ax.yaxis, ax.get_ylim(), ax.get_yscale()),
        "titulos": {onde: ax.get_title(loc=onde) for onde in ("left", "center", "right")},
        "textos": [_texto(t, ax) for t in ax.texts],
        "faixas": [_faixa(r) for r in ax.patches],
        "legenda": _legenda(ax, eixos, renderizador),
        "fundo": bool(ax.patch.get_visible()),             # o twinx não tem fundo (senão cobriria o da esquerda)
        "molduras": {nome: bool(m.get_visible()) for nome, m in ax.spines.items()},
    }, linhas


def _ligacoes(ax, dentro) -> dict | None:
    """As linhas de ligação de um inset (o ``indicate_inset_zoom``): o estilo do retângulo, que elas repetem."""
    for artista in ax.artists:
        if isinstance(artista, InsetIndicator) and getattr(artista, "_inset_ax", None) is dentro:
            r = artista.rectangle
            return {"edgecolor": to_hex(r.get_edgecolor(), keep_alpha=True), "linewidth": float(r.get_linewidth()),
                    "alpha": _json_simples(r.get_alpha()), "zorder": float(artista.get_zorder())}
    return None


def _faixa(r) -> dict:
    """Uma região (o ``axvspan``: do x0 ao x1, da altura inteira do eixo)."""
    if not isinstance(r, Rectangle) or r.get_y() != 0 or r.get_height() != 1:
        raise PacoteInvalido(f"o pacote ainda não descreve {type(r).__name__} num eixo")
    return {"x0": float(r.get_x()), "x1": float(r.get_x() + r.get_width()), "estilo": _estilo(r, ESTILO_DA_FAIXA)}


def _conferir_os_artistas(ax) -> None:
    conhecidos = {id(a) for a in (*ax.lines, *ax.texts, *ax.patches, *ax.child_axes, ax.patch, ax.xaxis, ax.yaxis,
                                  *ax.spines.values(), ax.title, getattr(ax, "_left_title", None),
                                  getattr(ax, "_right_title", None))}
    conhecidos |= {id(a) for a in ax.artists
                   if isinstance(a, InsetIndicator) and getattr(a, "_inset_ax", None) in ax.child_axes}
    legenda = ax.get_legend()
    for artista in ax.get_children():
        if id(artista) in conhecidos or artista is legenda or not artista.get_visible():
            continue
        raise PacoteInvalido(f"o pacote ainda não descreve {type(artista).__name__} num eixo")


def _json_simples(valor):
    """Um valor de propriedade em JSON: os números do NumPy como números, as cores como texto."""
    if isinstance(valor, np.generic):
        return valor.item()
    if isinstance(valor, tuple):
        return [_json_simples(v) for v in valor]
    return valor


def _estilo(artista, nomes) -> dict:
    estilo = {}
    for nome in nomes:
        valor = getattr(artista, f"get_{nome}")()
        if nome.endswith("color") and not (isinstance(valor, str) and valor in ("none", "auto")):
            valor = to_hex(valor, keep_alpha=True)
        estilo[nome] = _json_simples(valor)
    return estilo


def _eixo(eixo, limites, escala: str) -> dict:
    marcas = eixo.get_majorticklocs()
    menores = eixo.get_minorticklocs()
    return {
        "escala": escala, "limites": [float(limites[0]), float(limites[1])],
        "marcas": [float(v) for v in marcas],
        "textos": [t.label1.get_text() for t in eixo.get_major_ticks(len(marcas))],
        "marcas_menores": [float(v) for v in menores],
        "textos_menores": [t.label1.get_text() for t in eixo.get_minor_ticks(len(menores))],
        "deslocamento": eixo.get_offset_text().get_text(),
        "parametros": {qual: {k: _json_simples(v) for k, v in eixo.get_tick_params(which=qual).items()}
                       for qual in ("major", "minor")},
        "rotulo": eixo.get_label_text(),
        "lado_do_rotulo": eixo.get_label_position(),      # o eixo da direita (o twinx de outra grandeza): "right"
        "visivel": bool(eixo.get_visible()),              # o x do twinx é o do eixo da esquerda: escondido
    }


def _coordenadas(valor, texto: str):
    if isinstance(valor, str):
        return valor
    if isinstance(valor, tuple) and len(valor) == 2 and all(isinstance(v, str) for v in valor):
        return list(valor)
    raise PacoteInvalido(f"o pacote ainda não descreve as coordenadas da anotação {texto!r}")


def _texto(t, ax) -> dict:
    if isinstance(t, Annotation):
        estilo = _estilo(t, ESTILO_DO_TEXTO)
        estilo["ha"], estilo["va"] = estilo.pop("horizontalalignment"), estilo.pop("verticalalignment")
        seta = {k: _json_simples(v) for k, v in t.arrowprops.items()} if t.arrowprops else None
        return {"tipo": "anotacao", "texto": t.get_text(), "xy": [float(v) for v in t.xy],
                "xytext": [float(v) for v in t.xyann], "xycoords": _coordenadas(t.xycoords, t.get_text()),
                "textcoords": _coordenadas(t.anncoords, t.get_text()), "seta": seta,
                "recorte": t.get_annotation_clip(), "estilo": estilo}
    transformacao = t.get_transform()
    if transformacao is ax.transAxes:
        em = "eixos"
    elif transformacao is ax.transData:
        em = "dados"
    else:
        raise PacoteInvalido(f"o pacote ainda não descreve o texto {t.get_text()!r} (fora dos eixos e dos dados)")
    x, y = t.get_position()
    estilo = _estilo(t, ESTILO_DO_TEXTO)
    estilo["ha"], estilo["va"] = estilo.pop("horizontalalignment"), estilo.pop("verticalalignment")
    return {"tipo": "texto", "x": float(x), "y": float(y), "texto": t.get_text(), "em": em, "estilo": estilo}


def _legenda(ax, eixos, renderizador) -> dict | None:
    """A legenda: os textos, as curvas (``[eixo, linha]``: a posição do eixo na página e a da curva nele; a legenda
    de fora do eixo junta as curvas de todas as faixas do painel), as colunas e o canto de baixo à esquerda dela, em
    fração do eixo (onde o ``loc`` a pôs neste desenho)."""
    legenda = ax.get_legend()
    if legenda is None or not legenda.get_visible():
        return None
    caixa = legenda.get_window_extent(renderizador)
    x0, y0 = ax.transAxes.inverted().transform((caixa.x0, caixa.y0))
    textos = [t.get_text() for t in legenda.get_texts()]
    proprio = list(eixos).index(ax)
    ordem = [proprio] + [i for i in range(len(eixos)) if i != proprio]
    livres = [(i, j) for i in ordem for j in range(len(eixos[i].lines))]
    indices = []
    for texto in textos:
        par = next((par for par in livres if eixos[par[0]].lines[par[1]].get_label() == texto), None)
        if par is None:
            raise PacoteInvalido(f"a legenda {texto!r} não é de uma curva da figura")
        livres.remove(par)
        indices.append(list(par))
    return {"textos": textos, "linhas": indices, "colunas": int(legenda._ncols), "canto": [float(x0), float(y0)]}


def dados_h5(descricao, rc: Mapping, *, largura_pol: float, altura_pol: float, dpi: float, figura: Figura,
             aplicativo: str) -> bytes:
    """O ``dados.h5`` da descrição."""
    import h5py

    saida = io.BytesIO()
    with h5py.File(saida, "w") as f5:
        a = f5.attrs
        a["formato"], a["versao"] = FORMATO, VERSAO
        a["largura_pol"], a["altura_pol"], a["dpi"] = largura_pol, altura_pol, dpi
        a["rc"] = json.dumps(dict(rc), ensure_ascii=False, sort_keys=True)
        a["matplotlib"] = matplotlib.__version__
        a["aplicativo"] = f"SH-Analyzer {aplicativo}".strip()
        a["figura"] = figura.nome
        a["descricao"] = ("A figura como o SH-Analyzer a desenhou, já com o leiaute feito; o refazer_figura.py a "
                          "refaz. /eixos/NN: o atributo 'eixo' (JSON) e /eixos/NN/linhas/MM com x, y e o 'estilo'; "
                          "/eixos/NN/insets/KK: os insets do eixo, do mesmo jeito.")
        eixos = f5.create_group("eixos")
        for i, (eixo, linhas, insets) in enumerate(descricao):
            g = _grupo_do_eixo(eixos, f"{i:02d}", eixo, linhas)
            if insets:
                grupo_dos_insets = g.create_group("insets")
                for k, (inset, linhas_do_inset) in enumerate(insets):
                    _grupo_do_eixo(grupo_dos_insets, f"{k:02d}", inset, linhas_do_inset)
    return saida.getvalue()


def _grupo_do_eixo(pai, nome: str, eixo: dict, linhas):
    g = pai.create_group(nome)
    g.attrs["eixo"] = json.dumps(eixo, ensure_ascii=False)
    g.attrs["rotulo_x"], g.attrs["rotulo_y"] = eixo["x"]["rotulo"], eixo["y"]["rotulo"]
    grupo_das_linhas = g.create_group("linhas")
    for j, (x, y, estilo) in enumerate(linhas):
        linha = grupo_das_linhas.create_group(f"{j:02d}")
        linha.create_dataset("x", data=x)
        linha.create_dataset("y", data=y)
        linha.attrs["estilo"] = json.dumps(estilo, ensure_ascii=False)
        linha.attrs["rotulo"] = str(estilo.get("label", ""))
    return g


def fontes_da_figura(rc: Mapping) -> list[Path]:
    """As fontes do aplicativo que o estilo usa (a família de ``font.family``) e as licenças delas; nenhuma para as
    que vêm com o Matplotlib."""
    registrar_as_fontes()                    # a lista do Matplotlib com as do aplicativo (já, se houve um desenho)
    familias = rc.get("font.family")
    familias = {familias} if isinstance(familias, str) else set(familias or ())
    pasta = PASTA_DAS_FONTES.resolve()
    arquivos = sorted({Path(f.fname).resolve() for f in font_manager.fontManager.ttflist
                       if f.name in familias and Path(f.fname).resolve().parent == pasta})
    licencas = [t for t in sorted(pasta.glob("*.txt"))
                if any(a.stem.startswith(t.stem.split("-")[0]) for a in arquivos)]
    return arquivos + licencas


# ------------------------------------------------------------------ o pacote

def empacotar(figura: Figura, vistas: Mapping[str, VistaSalva], dados: DadosDaFigura, destino: Path,
              opcoes: OpcoesDeExportacao, *, proveniencia: Mapping, aplicativo: str = "",
              progresso: Callable[[float], None] | None = None,
              cancelado: Callable[[], bool] | None = None) -> Path:
    """Desenha ``figura`` uma vez e grava o pacote em ``destino`` (inteiro, ou nada: um ``.parcial`` renomeado no
    fim). O progresso: o desenho até 0,8, os arquivos depois."""
    conferir(figura, opcoes)
    destino = Path(destino)
    pagina = desenhar_para_exportar(figura, vistas, dados, opcoes, progresso=parte_do_progresso(progresso, 0.0, 0.8),
                                    cancelado=cancelado)
    formato = opcoes.dados_do_formato
    arquivos: dict[str, bytes] = {}
    with TemporaryDirectory(prefix="sh-analyzer-pacote-") as tmp:
        principal = Path(tmp) / f"figura{formato.extensao}"
        gravar(pagina, figura, principal, opcoes, proveniencia=proveniencia, aplicativo=aplicativo)
        for arquivo in sorted(Path(tmp).iterdir()):          # o PGF com as curvas rasterizadas tem as imagens
            arquivos[arquivo.name] = arquivo.read_bytes()
    if progresso is not None:
        progresso(0.85)
    # A referência dos pixels: o último desenho (a descrição é lida dele).
    dpi = opcoes.dpi_efetivo if formato.id == "png" else min(opcoes.dpi_efetivo, DPI_DA_REFERENCIA,
                                                               dpi_maximo(figura))
    pagina.mpl.set_dpi(dpi)
    referencia = OpcoesDeExportacao("png", dpi)
    png = io.BytesIO()
    gravar(pagina, figura, png, referencia, proveniencia=proveniencia, aplicativo=aplicativo)
    arquivos["figura.png"] = png.getvalue()
    largura, altura = (float(v) for v in pagina.mpl.get_size_inches())
    rc = parametros_da_gravacao(pagina, figura, referencia)
    with no_estilo(rc):              # as marcas dependem do estilo (o tamanho dos números): leia-as com ele
        descricao = descrever(pagina)
    arquivos["dados.h5"] = dados_h5(descricao, rc, largura_pol=largura, altura_pol=altura, dpi=dpi, figura=figura,
                                    aplicativo=aplicativo)
    if progresso is not None:
        progresso(0.95)
    arquivos["refazer_figura.py"] = SCRIPT.read_bytes()
    for fonte in fontes_da_figura(rc):
        arquivos[f"fontes/{fonte.name}"] = fonte.read_bytes()
    arquivos["proveniencia.json"] = (json.dumps(proveniencia, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    arquivos["LEIA-ME.md"] = leia_me(figura, formato.extensao, dpi, aplicativo, sorted(arquivos)).encode("utf-8")
    pasta = _nome_da_pasta(destino.stem)
    parcial = destino.with_name(destino.name + ".parcial")
    try:
        with zipfile.ZipFile(parcial, "w", zipfile.ZIP_DEFLATED) as z:
            for nome, conteudo in sorted(arquivos.items()):
                z.writestr(f"{pasta}/{nome}", conteudo)
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise
    parcial.replace(destino)
    if progresso is not None:
        progresso(1.0)
    return destino


def _nome_da_pasta(nome: str) -> str:
    return "".join(c if c.isalnum() or c in " -_." else "_" for c in nome).strip(" .") or "figura"


def leia_me(figura: Figura, extensao: str, dpi: float, aplicativo: str, arquivos: list[str],
            momento: datetime | None = None) -> str:
    momento = momento or datetime.now(timezone.utc).astimezone()
    versao = f"SH-Analyzer {aplicativo}".strip()
    fontes = sorted(a.removeprefix("fontes/") for a in arquivos if a.startswith("fontes/"))
    return f"""# {figura.nome}: o pacote reproduzível

Feito pelo {versao} em {momento:%d/%m/%Y %H:%M} ({figura.modelo}, {figura.largura_mm:g} × {figura.altura_mm:g} mm).

## O que tem aqui

| Arquivo | O que é |
|---|---|
| `figura{extensao}` | a figura exportada |
| `figura.png` | a mesma figura em PNG, a {dpi:g} dpi: a referência dos pixels |
| `dados.h5` | a figura descrita: a posição de cada eixo, os limites, as marcas, os textos e cada curva (os pontos desenhados, na resolução da figura) |
| `refazer_figura.py` | refaz a figura a partir do `dados.h5`, só com NumPy, h5py e Matplotlib |
| `proveniencia.json` | de onde a figura veio: as capturas (o caminho, o tamanho, o CRC das amostras, o cabeçalho), as vistas e a receita de cada traço |
{"| `fontes/` | as fontes da figura que não vêm com o Matplotlib (" + ", ".join(fontes) + "), com as licenças |" if fontes else ""}

## Refazer a figura

```
python refazer_figura.py                  # figura_refeita.png, comparada com a figura.png
python refazer_figura.py --formato pdf    # ou svg, eps
```

Com o Matplotlib {matplotlib.__version__} (o que desenhou a figura), a `figura_refeita.png` tem os mesmos pixels da
`figura.png`; com outra versão, pequenas diferenças no desenho das letras são esperadas.

## Os dados

Cada curva de `dados.h5` (`/eixos/NN/linhas/MM`, os vetores `x` e `y`, o nome no atributo `rotulo`) tem os pontos
que estão na figura: a redução M4 das amostras (o primeiro, o mínimo, o máximo e o último ponto de cada coluna de
pixels), que desenha o mesmo que todas as amostras. As unidades estão nos rótulos dos eixos (`rotulo_x`, `rotulo_y`).
As amostras inteiras estão nas capturas do `proveniencia.json`; o SH-Analyzer as exporta em CSV, HDF5, MAT ou NPZ
("Exportar os dados da vista").

## English

A reproducible package of the figure *{figura.nome}*: `figura{extensao}` (the exported figure), `figura.png` (the
pixel reference, {dpi:g} dpi), `dados.h5` (the drawn figure: axes positions, limits, ticks, texts and every curve as
drawn), `refazer_figura.py` (rebuilds the figure from `dados.h5` with NumPy, h5py and Matplotlib only; run
`python refazer_figura.py` and it reports whether the result matches `figura.png` pixel by pixel) and
`proveniencia.json` (the source captures with their checksums, and the recipe of every trace).
"""


__all__ = ["DPI_DA_REFERENCIA", "FORMATO", "PacoteInvalido", "SCRIPT", "VERSAO", "dados_h5", "descrever",
           "empacotar", "fontes_da_figura", "leia_me"]
