"""O caderno de notas do pesquisador (sem Qt): as páginas em Markdown numa pasta, e as **referências** a um ponto ou a
um trecho de um gráfico, que levam a vista de volta até ali.

**As páginas** são arquivos ``.md`` na pasta do caderno (``<pasta de dados>/caderno``): o título é o primeiro título
do texto (``# ...``) ou, sem ele, a primeira linha; a ordem é a da última mudança. A gravação é atômica (um
temporário na mesma pasta, renomeado no fim). As imagens coladas ficam em ``imagens/``, ao lado, e entram no texto
como ``![](imagens/nome.png)``.

**Uma referência** é um link do Markdown com o endereço ``shanalyzer:ref?...``: a vista (o id dela no projeto), o
trecho a mostrar (``x0`` e ``x1``, em segundos ou em hertz), o ponto marcado (``px``, ``py``), a faixa e o projeto
(o caminho do ``.shproj``). O texto do link é legível sozinho ("Tempo 1 · t = 12,5 ms"); o endereço vai junto, para
a referência continuar valendo copiada para outra página ou outro editor.
"""

from __future__ import annotations

import datetime
import math
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode

from .anotacoes import formatar

ESQUEMA = "shanalyzer"
EXTENSAO = ".md"
PASTA_DAS_IMAGENS = "imagens"
_TITULO = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
LINK_DA_REFERENCIA = re.compile(r"\[([^\]\n]*)\]\((shanalyzer:ref\?[^)\s]*)\)")


class ReferenciaInvalida(ValueError):
    pass


@dataclass(frozen=True)
class Referencia:
    """Um ponto (``tipo="ponto"``) ou um trecho (``"intervalo"``) de uma vista. ``x0``/``x1``: o que mostrar;
    ``px``/``py``: o ponto marcado (no ponto); ``dominio``: ``"t"`` (o tempo, s) ou ``"f"`` (a frequência, Hz)."""

    vista: str
    x0: float
    x1: float
    tipo: str = "intervalo"
    nome: str = ""
    px: float | None = None
    py: float | None = None
    faixa: int = 0
    dominio: str = "t"
    projeto: str = ""

    def __post_init__(self):
        if not self.vista:
            raise ReferenciaInvalida("a referência não diz a vista")
        if self.tipo not in ("ponto", "intervalo"):
            raise ReferenciaInvalida(f"tipo de referência desconhecido: {self.tipo!r}")
        if self.dominio not in ("t", "f"):
            raise ReferenciaInvalida(f"domínio desconhecido: {self.dominio!r}")
        for nome in ("x0", "x1"):
            if not math.isfinite(getattr(self, nome)):
                raise ReferenciaInvalida(f"o {nome} da referência não é um número")
        if self.x1 < self.x0:
            x0, x1 = self.x1, self.x0
            object.__setattr__(self, "x0", x0)
            object.__setattr__(self, "x1", x1)
        if self.tipo == "ponto" and self.px is None:
            raise ReferenciaInvalida("a referência a um ponto precisa do ponto")

    # ------------------------------------------------------------------ o endereço

    def url(self) -> str:
        campos = {"vista": self.vista, "tipo": self.tipo, "x0": repr(self.x0), "x1": repr(self.x1)}
        if self.px is not None:
            campos["px"] = repr(self.px)
        if self.py is not None:
            campos["py"] = repr(self.py)
        if self.faixa:
            campos["faixa"] = str(self.faixa)
        if self.dominio != "t":
            campos["dominio"] = self.dominio
        if self.projeto:
            campos["projeto"] = self.projeto
        return f"{ESQUEMA}:ref?" + urlencode(campos, quote_via=quote, safe="/~")

    @classmethod
    def de_url(cls, url: str) -> Referencia:
        prefixo = f"{ESQUEMA}:ref?"
        if not url.startswith(prefixo):
            raise ReferenciaInvalida(f"não é uma referência do SH-Analyzer: {url!r}")
        campos = {k: v[0] for k, v in parse_qs(url[len(prefixo):], keep_blank_values=True).items()}

        def numero(nome, padrao=None):
            if nome not in campos:
                if padrao is not None or nome in ("px", "py"):
                    return padrao
                raise ReferenciaInvalida(f"a referência não tem o {nome}")
            try:
                return float(campos[nome])
            except ValueError:
                raise ReferenciaInvalida(f"o {nome} da referência não é um número: {campos[nome]!r}") from None

        try:
            faixa = int(campos.get("faixa", "0"))
        except ValueError:
            raise ReferenciaInvalida("a faixa da referência não é um número") from None
        return cls(vista=campos.get("vista", ""), x0=numero("x0"), x1=numero("x1"), tipo=campos.get("tipo", "intervalo"),
                   px=numero("px"), py=numero("py"), faixa=faixa, dominio=campos.get("dominio", "t"),
                   projeto=campos.get("projeto", ""))

    # ------------------------------------------------------------------ o texto

    def texto(self, separador: str = ",") -> str:
        """O texto do link: a vista e o ponto ("Tempo 1 · t = 12,5 ms") ou o trecho ("Tempo 1 · 12,5 ms → 14 ms,
        Δt = 1,5 ms")."""
        unidade, simbolo, delta = ("s", "t", "Δt") if self.dominio == "t" else ("Hz", "f", "Δf")
        vista = f"{self.nome} · " if self.nome else ""
        if self.tipo == "ponto":
            return f"● {vista}{simbolo} = {formatar(self.px, unidade, separador)}"
        return (f"↔ {vista}{formatar(self.x0, unidade, separador)} → {formatar(self.x1, unidade, separador)}, "
                f"{delta} = {formatar(self.x1 - self.x0, unidade, separador)}")

    def markdown(self, separador: str = ",") -> str:
        texto = self.texto(separador).replace("[", "(").replace("]", ")")
        return f"[{texto}]({self.url()})"


def referencias_em(texto: str) -> list[tuple[int, int, str, Referencia | None]]:
    """As referências do texto: o começo e o fim do link inteiro, o texto dele e a referência (``None``: o endereço
    não vale)."""
    achadas = []
    for m in LINK_DA_REFERENCIA.finditer(texto):
        try:
            referencia = Referencia.de_url(m.group(2))
        except ReferenciaInvalida:
            referencia = None
        achadas.append((m.start(), m.end(), m.group(1), referencia))
    return achadas


# ---------------------------------------------------------------------- as páginas


@dataclass(frozen=True)
class Pagina:
    caminho: Path
    titulo: str
    mudou_em: float


def titulo_do_texto(texto: str, padrao: str = "Sem título") -> str:
    """O primeiro título do Markdown (``# ...``), ou a primeira linha com texto, sem a marcação."""
    primeira = ""
    for linha in texto.splitlines():
        m = _TITULO.match(linha)
        if m:
            return _sem_marcacao(m.group(1)) or padrao
        if not primeira and linha.strip():
            primeira = linha.strip()
    primeira = _sem_marcacao(re.sub(r"^\s*([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?", "", primeira))
    return (primeira[:60] + "…" if len(primeira) > 60 else primeira) or padrao


def _sem_marcacao(texto: str) -> str:
    texto = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", texto)
    return re.sub(r"[*_`~]+", "", texto).strip()


def nome_de_arquivo(titulo: str) -> str:
    """Um nome de arquivo do título: sem acentos, em minúsculas, com hífens."""
    base = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:48]
    return base or "pagina"


def paginas(pasta: Path) -> list[Pagina]:
    """As páginas da pasta, a mudada por último primeiro."""
    pasta = Path(pasta)
    if not pasta.is_dir():
        return []
    achadas = []
    for caminho in pasta.glob(f"*{EXTENSAO}"):
        try:
            texto = caminho.read_text(encoding="utf-8")
            mudou = caminho.stat().st_mtime
        except (OSError, UnicodeDecodeError):
            continue
        achadas.append(Pagina(caminho, titulo_do_texto(texto, caminho.stem), mudou))
    return sorted(achadas, key=lambda p: (-p.mudou_em, p.caminho.name))


def nova_pagina(pasta: Path, titulo: str = "", agora: datetime.datetime | None = None) -> Path:
    """Cria uma página com o título (sem ele, a data e a hora) e devolve o caminho dela."""
    agora = agora or datetime.datetime.now()
    titulo = titulo.strip() or agora.strftime("Notas de %d/%m/%Y, %H:%M")
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    base = nome_de_arquivo(titulo)
    caminho = pasta / f"{base}{EXTENSAO}"
    n = 2
    while caminho.exists():
        caminho = pasta / f"{base}-{n}{EXTENSAO}"
        n += 1
    gravar(caminho, f"# {titulo}\n\n")
    return caminho


def gravar(caminho: Path, texto: str) -> None:
    """Grava a página de uma vez (um temporário na mesma pasta, renomeado no fim)."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    descritor, temporario = tempfile.mkstemp(prefix=f".{caminho.name}.", suffix=".tmp", dir=caminho.parent)
    try:
        with os.fdopen(descritor, "w", encoding="utf-8", newline="\n") as arquivo:
            arquivo.write(texto)
        os.replace(temporario, caminho)
    except BaseException:
        try:
            os.unlink(temporario)
        except OSError:
            pass
        raise


def buscar(pasta: Path, termo: str) -> list[Pagina]:
    """As páginas cujo título ou texto têm ``termo`` (sem diferença de maiúsculas e de acentos)."""
    def simples(t: str) -> str:
        return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii").lower()

    alvo = simples(termo.strip())
    if not alvo:
        return paginas(pasta)
    achadas = []
    for pagina in paginas(pasta):
        try:
            texto = pagina.caminho.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if alvo in simples(pagina.titulo) or alvo in simples(texto):
            achadas.append(pagina)
    return achadas
