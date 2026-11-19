"""A exportação da figura (a F5.4; docs/gui-plan.md, 10.2 e 10.3), sem Qt: o desenho da F5.2 em PDF, SVG, EPS,
PGF, PNG ou TIFF, com a proveniência nos metadados.

| Formato | O que sai |
|---|---|
| PDF | vetorial, as fontes embutidas como TrueType (Type 42), a página do tamanho do modelo |
| SVG | o texto como texto (editável no Inkscape) ou como curvas |
| EPS | vetorial, as fontes em Type 42 |
| PGF | o texto composto pelo LaTeX do documento (as fontes dele); precisa de um LaTeX instalado para medir o texto |
| PNG | de 150 a 1 200 dpi, em RGB, com o dpi gravado |
| TIFF | de 300 a 1 200 dpi, em RGB, com a compressão LZW |

**A resolução:** o ``dpi`` é o do dispositivo final mesmo nos vetoriais: as curvas são reduzidas pelo M4 nele (2
colunas por pixel, seção 10.3; um PDF a 600 dpi de uma coluna da IEEE leva ~8 000 pontos por traço, de uma captura
de qualquer tamanho). **"Todos os pontos"** desliga a redução (:func:`pontos` diz quantos vão; acima de
:data:`LIMITE_DE_PONTOS`, a área avisa do tamanho do arquivo). **"Rasterizar as curvas densas"** põe só as curvas
como imagem embutida no dpi escolhido, e os eixos e o texto continuam vetoriais.

**A proveniência** (``proveniencia.py``) vai no ``Subject`` do PDF, na ``Description`` do SVG e do PNG, na
``ImageDescription`` do TIFF e num comentário no começo do EPS e do PGF.

**O tamanho:** uma imagem (PNG, TIFF, ou as curvas rasterizadas) passa no máximo de :data:`LIMITE_DE_PIXELS` (um
pôster A0 a 1 200 dpi teria 2,2 G pixels): :func:`dpi_maximo` diz até onde vai, e :func:`conferir` recusa com a
razão.
"""

from __future__ import annotations

import io
import json
import math
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import numpy as np
from matplotlib import rc_context
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from supraharmonicos.api import Cancelado

from .desenho_da_figura import DadosDaFigura, PaginaDesenhada, desenhar, pontos
from .figura import Figura
from .projeto import VistaSalva
from .proveniencia import em_texto

DPI_MAXIMO = 1200.0
LIMITE_DE_PONTOS = 2_000_000
LIMITE_DE_PIXELS = 300_000_000            # ~1,2 GB em RGBA
SISTEMAS_DO_LATEX = ("xelatex", "lualatex", "pdflatex")


@dataclass(frozen=True)
class FormatoDeFigura:
    id: str
    nome: str
    extensao: str
    vetorial: bool
    dpi_minimo: float
    dpi_padrao: float
    descricao: str


FORMATOS: dict[str, FormatoDeFigura] = {f.id: f for f in (
    FormatoDeFigura("pdf", "PDF", ".pdf", True, 150.0, 600.0, "Artigos e LaTeX: vetorial, as fontes embutidas"),
    FormatoDeFigura("svg", "SVG", ".svg", True, 150.0, 600.0, "Para editar no Inkscape ou no Illustrator"),
    FormatoDeFigura("eps", "EPS", ".eps", True, 150.0, 600.0, "Revistas antigas: vetorial"),
    FormatoDeFigura("pgf", "PGF", ".pgf", True, 150.0, 600.0, "LaTeX com as fontes do documento"),
    FormatoDeFigura("png", "PNG", ".png", False, 150.0, 300.0, "Slides e web"),
    FormatoDeFigura("tiff", "TIFF", ".tif", False, 300.0, 600.0, "Revistas que pedem imagem (LZW)"),
)}


class OpcoesInvalidas(ValueError):
    """A exportação pedida não pode sair assim (a razão vai na mensagem)."""


@dataclass(frozen=True)
class OpcoesDeExportacao:
    formato: str = "pdf"
    dpi: float | None = None                  # None: o padrão do formato
    texto_editavel: bool = True               # SVG: o texto como texto (ou como curvas)
    rasterizar_curvas: bool = False           # os vetoriais: as curvas como imagem embutida
    todos_os_pontos: bool = False

    def __post_init__(self):
        if self.formato not in FORMATOS:
            raise OpcoesInvalidas(f"formato desconhecido: {self.formato!r} (use {', '.join(FORMATOS)})")
        f = FORMATOS[self.formato]
        if self.dpi is not None and not (f.dpi_minimo <= self.dpi <= DPI_MAXIMO):
            raise OpcoesInvalidas(f"o {f.nome} sai de {f.dpi_minimo:g} a {DPI_MAXIMO:g} dpi, não {self.dpi:g}")

    @property
    def dados_do_formato(self) -> FormatoDeFigura:
        return FORMATOS[self.formato]

    @property
    def dpi_efetivo(self) -> float:
        return self.dpi if self.dpi is not None else self.dados_do_formato.dpi_padrao

    @property
    def tem_imagem(self) -> bool:
        """Se sai uma imagem (o PNG, o TIFF, ou as curvas rasterizadas): o limite de pixels vale."""
        return not self.dados_do_formato.vetorial or self.rasterizar_curvas


def sistema_do_latex() -> str | None:
    """O LaTeX que o PGF usa para medir o texto (o primeiro instalado), ou ``None``."""
    return next((s for s in SISTEMAS_DO_LATEX if shutil.which(s)), None)


def dpi_maximo(figura: Figura) -> float:
    """O maior dpi em que a página inteira cabe em :data:`LIMITE_DE_PIXELS`."""
    area = (figura.largura_mm / 25.4) * (figura.altura_mm / 25.4)
    return float(min(DPI_MAXIMO, math.floor(math.sqrt(LIMITE_DE_PIXELS / area))))


def conferir(figura: Figura, opcoes: OpcoesDeExportacao) -> None:
    """Levanta :class:`OpcoesInvalidas` se a exportação não pode sair (a razão, para mostrar)."""
    if opcoes.tem_imagem and opcoes.dpi_efetivo > dpi_maximo(figura):
        raise OpcoesInvalidas(f"a página de {figura.largura_mm:g} × {figura.altura_mm:g} mm a "
                              f"{opcoes.dpi_efetivo:g} dpi passa de {LIMITE_DE_PIXELS // 1_000_000} M pixels: "
                              f"use até {dpi_maximo(figura):g} dpi")
    if opcoes.formato == "pgf" and sistema_do_latex() is None:
        raise OpcoesInvalidas("o PGF precisa de um LaTeX instalado (xelatex, lualatex ou pdflatex) para medir o "
                              "texto")


def nome_do_arquivo(figura: Figura, opcoes: OpcoesDeExportacao) -> str:
    """O nome sugerido: o da figura, sem o que não vai num nome de arquivo, com a extensão do formato."""
    base = "".join(c if c.isalnum() or c in " -_." else "_" for c in figura.nome).strip() or "figura"
    return base + opcoes.dados_do_formato.extensao


def exportar(figura: Figura, vistas: Mapping[str, VistaSalva], dados: DadosDaFigura, destino: Path | BinaryIO,
             opcoes: OpcoesDeExportacao, *, proveniencia: Mapping | None = None, aplicativo: str = "",
             progresso: Callable[[float], None] | None = None,
             cancelado: Callable[[], bool] | None = None) -> None:
    """Desenha ``figura`` e grava em ``destino`` (um caminho, gravado inteiro ou não gravado, ou um arquivo aberto em
    binário). O progresso vai de 0 a 1 (o desenho até 0,8; a gravação depois); ``cancelado()`` interrompe a
    redução (``Cancelado``)."""
    conferir(figura, opcoes)
    formato, dpi = opcoes.dados_do_formato, opcoes.dpi_efetivo
    if formato.id == "pgf" and opcoes.rasterizar_curvas and not isinstance(destino, (str, Path)):
        raise OpcoesInvalidas("o PGF com as curvas rasterizadas grava as imagens ao lado dele: precisa de um arquivo")

    def parte(inicio: float, fim: float):
        return (lambda f: progresso(inicio + (fim - inicio) * f)) if progresso is not None else None

    pagina = desenhar(figura, vistas, dados, dpi=dpi, exato=True, todos_os_pontos=opcoes.todos_os_pontos,
                      progresso=parte(0.0, 0.8), cancelado=cancelado, pixels_inteiros=not formato.vetorial)
    if cancelado is not None and cancelado():
        raise Cancelado()
    if opcoes.rasterizar_curvas and formato.vetorial:
        for linha in pagina.curvas:
            linha.set_rasterized(True)
    criador = f"SH-Analyzer {aplicativo}".strip()
    rc = {**pagina.rc, "pdf.fonttype": 42, "ps.fonttype": 42,
          "svg.fonttype": "none" if opcoes.texto_editavel else "path", "svg.hashsalt": figura.id,
          "pgf.rcfonts": False, "pgf.texsystem": sistema_do_latex() or SISTEMAS_DO_LATEX[0]}
    with rc_context(rc):
        if formato.id == "pgf" and isinstance(destino, (str, Path)):
            _pgf_no_arquivo(pagina, Path(destino), dpi, proveniencia)
        else:
            conteudo = (_vetorial(pagina, figura, formato.id, dpi, criador, proveniencia) if formato.vetorial
                        else _imagem(pagina, figura, formato.id, dpi, criador, proveniencia))
            _gravar(destino, conteudo)
    if progresso is not None:
        progresso(1.0)


def em_bytes(figura: Figura, vistas: Mapping[str, VistaSalva], dados: DadosDaFigura, opcoes: OpcoesDeExportacao,
             **kw) -> bytes:
    """A figura exportada na memória (copiar para a área de transferência)."""
    saida = io.BytesIO()
    exportar(figura, vistas, dados, saida, opcoes, **kw)
    return saida.getvalue()


# ------------------------------------------------------------------ os formatos

def _vetorial(pagina: PaginaDesenhada, figura: Figura, formato: str, dpi: float, criador: str,
              proveniencia: Mapping | None) -> bytes:
    texto = em_texto(proveniencia) if proveniencia else ""
    metadados = {
        "pdf": {"Title": figura.nome, "Creator": criador, "Subject": texto, "Keywords": "SH-Analyzer"},
        "svg": {"Title": figura.nome, "Creator": criador, "Description": texto},
        "eps": {"Title": figura.nome, "Creator": criador},
        "pgf": None,
    }[formato]
    saida = io.BytesIO()
    pagina.mpl.savefig(saida, format=formato, dpi=dpi, facecolor="white",
                       **({"metadata": {k: v for k, v in metadados.items() if v}} if metadados else {}))
    conteudo = saida.getvalue()
    if formato == "eps" and proveniencia:
        conteudo = _comentario_no_eps(conteudo, proveniencia)
    elif formato == "pgf" and proveniencia:
        conteudo = _comentario_no_pgf(proveniencia) + conteudo
    return conteudo


def _pgf_no_arquivo(pagina: PaginaDesenhada, destino: Path, dpi: float, proveniencia: Mapping | None) -> None:
    """O PGF gravado direto no arquivo (as curvas rasterizadas vão ao lado dele, com o nome dele), e a proveniência
    posta no começo."""
    parcial = destino.with_name(destino.name + ".parcial")
    pagina.mpl.savefig(destino, format="pgf", dpi=dpi, facecolor="white")
    conteudo = destino.read_bytes()
    if proveniencia:
        parcial.write_bytes(_comentario_no_pgf(proveniencia) + conteudo)
        parcial.replace(destino)


def _comentario_no_pgf(proveniencia: Mapping) -> bytes:
    return f"%% SH-Analyzer: proveniência da figura (JSON)\n%% {em_texto(proveniencia)}\n".encode()


def _comentario_no_eps(conteudo: bytes, proveniencia: Mapping) -> bytes:
    """A proveniência como comentário (``% ``: os leitores do DSC o ignoram) logo depois do cabeçalho."""
    linha = b"% SH-Analyzer: " + json.dumps(proveniencia, ensure_ascii=True, sort_keys=True,
                                            separators=(",", ":")).encode("ascii") + b"\n"
    marca = b"%%EndComments\n"
    i = conteudo.find(marca)
    fim = i + len(marca) if i >= 0 else conteudo.find(b"\n") + 1
    return conteudo[:fim] + linha + conteudo[fim:]


def _imagem(pagina: PaginaDesenhada, figura: Figura, formato: str, dpi: float, criador: str,
            proveniencia: Mapping | None) -> bytes:
    rgba = pagina.pixels()
    imagem = Image.fromarray(np.ascontiguousarray(rgba[..., :3]), "RGB")
    saida = io.BytesIO()
    if formato == "png":
        info = PngInfo()
        info.add_itxt("Title", figura.nome)
        info.add_itxt("Software", criador)
        if proveniencia:
            info.add_itxt("Description", em_texto(proveniencia))
        imagem.save(saida, format="PNG", dpi=(dpi, dpi), pnginfo=info, optimize=False)
    else:
        extras = {"description": json.dumps(proveniencia, ensure_ascii=True, sort_keys=True,
                                            separators=(",", ":"))} if proveniencia else {}
        imagem.save(saida, format="TIFF", compression="tiff_lzw", dpi=(dpi, dpi), software=criador, **extras)
    return saida.getvalue()


def _gravar(destino: Path | BinaryIO, conteudo: bytes) -> None:
    """Num caminho, o arquivo inteiro ou nenhum (o parcial e depois o nome certo); num arquivo aberto, direto."""
    if isinstance(destino, (str, Path)):
        destino = Path(destino)
        parcial = destino.with_name(destino.name + ".parcial")
        parcial.write_bytes(conteudo)
        parcial.replace(destino)
    else:
        destino.write(conteudo)


__all__ = ["DPI_MAXIMO", "FORMATOS", "LIMITE_DE_PIXELS", "LIMITE_DE_PONTOS", "FormatoDeFigura", "OpcoesDeExportacao",
           "OpcoesInvalidas", "conferir", "dpi_maximo", "em_bytes", "exportar", "nome_do_arquivo", "pontos",
           "sistema_do_latex"]
