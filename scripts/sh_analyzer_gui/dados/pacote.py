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
preenchida) recusa o pacote com a razão: um pacote que não refaz a figura não sai.
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
from matplotlib import font_manager, rc_context
from matplotlib.colors import to_hex
from supraharmonicos.api import ErroSHAN

from .desenho_da_figura import PASTA_DAS_FONTES, DadosDaFigura, PaginaDesenhada
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
VERSAO = 1
DPI_DA_REFERENCIA = 600.0
SCRIPT = Path(__file__).resolve().parents[1] / "recursos" / "refazer_figura.py"
ESTILO_DA_LINHA = ("color", "linestyle", "linewidth", "alpha", "antialiased", "rasterized", "zorder", "label",
                   "marker", "markersize", "markevery", "markerfacecolor", "markeredgecolor", "markeredgewidth",
                   "fillstyle", "drawstyle", "dash_capstyle", "dash_joinstyle", "solid_capstyle", "solid_joinstyle")
ESTILO_DO_TEXTO = ("color", "fontsize", "fontweight", "fontstyle", "horizontalalignment", "verticalalignment",
                   "rotation", "zorder")


class PacoteInvalido(ErroSHAN, ValueError):
    """O pacote não pode sair (a razão vai na mensagem)."""


# ------------------------------------------------------------------ a descrição da figura desenhada

def descrever(pagina: PaginaDesenhada) -> list[tuple[dict, list[tuple[np.ndarray, np.ndarray, dict]]]]:
    """Cada eixo da página **depois de desenhada** (as posições são as do leiaute desse desenho): a descrição dele
    e as curvas (``x``, ``y`` e o estilo). Rode dentro do ``rc_context`` do desenho: o localizador das marcas conta
    quantas cabem pelo tamanho dos números, que vem do estilo."""
    mpl = pagina.mpl
    for nome in ("texts", "lines", "patches", "images", "legends", "artists", "subfigs"):
        if getattr(mpl, nome, None):
            raise PacoteInvalido(f"o pacote ainda não descreve {nome} na página")
    renderizador = mpl.canvas.get_renderer()
    saida = []
    for ax in mpl.axes:
        _conferir_os_artistas(ax)
        linhas = [(np.asarray(linha.get_xdata(), dtype=np.float64), np.asarray(linha.get_ydata(), dtype=np.float64),
                   _estilo(linha, ESTILO_DA_LINHA)) for linha in ax.lines]
        saida.append(({
            "posicao": [float(v) for v in ax.get_position().bounds],
            "x": _eixo(ax.xaxis, ax.get_xlim(), ax.get_xscale()),
            "y": _eixo(ax.yaxis, ax.get_ylim(), ax.get_yscale()),
            "titulos": {onde: ax.get_title(loc=onde) for onde in ("left", "center", "right")},
            "textos": [_texto(t, ax) for t in ax.texts],
            "legenda": _legenda(ax, mpl.axes, renderizador),
        }, linhas))
    return saida


def _conferir_os_artistas(ax) -> None:
    conhecidos = {id(a) for a in (*ax.lines, *ax.texts, ax.patch, ax.xaxis, ax.yaxis, *ax.spines.values(),
                                  ax.title, getattr(ax, "_left_title", None), getattr(ax, "_right_title", None))}
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
    }


def _texto(t, ax) -> dict:
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
    return {"x": float(x), "y": float(y), "texto": t.get_text(), "em": em, "estilo": estilo}


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
                          "refaz. /eixos/NN: o atributo 'eixo' (JSON) e /eixos/NN/linhas/MM com x, y e o 'estilo'.")
        eixos = f5.create_group("eixos")
        for i, (eixo, linhas) in enumerate(descricao):
            g = eixos.create_group(f"{i:02d}")
            g.attrs["eixo"] = json.dumps(eixo, ensure_ascii=False)
            g.attrs["rotulo_x"], g.attrs["rotulo_y"] = eixo["x"]["rotulo"], eixo["y"]["rotulo"]
            grupo_das_linhas = g.create_group("linhas")
            for j, (x, y, estilo) in enumerate(linhas):
                linha = grupo_das_linhas.create_group(f"{j:02d}")
                linha.create_dataset("x", data=x)
                linha.create_dataset("y", data=y)
                linha.attrs["estilo"] = json.dumps(estilo, ensure_ascii=False)
                linha.attrs["rotulo"] = str(estilo.get("label", ""))
    return saida.getvalue()


def fontes_da_figura(rc: Mapping) -> list[Path]:
    """As fontes do aplicativo que o estilo usa (a família de ``font.family``) e as licenças delas; nenhuma para as
    que vêm com o Matplotlib."""
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
    with rc_context(rc):              # as marcas dependem do estilo (o tamanho dos números): leia-as com ele
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
