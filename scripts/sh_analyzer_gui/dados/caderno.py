"""O caderno de bancada (docs/gui-plan.md, PD-09; a F4.5): as entradas com hora no ``anotacoes.md`` da sessão do dia,
o mesmo arquivo do ``scripts/sessao_lab.sh`` (o ``lab notas``). Sem Qt.

**O arquivo é do usuário.** O ``lab`` o cria do modelo (``docs/lab-notes-template.md``) e ele o preenche à mão
durante a sessão. O aplicativo **só acrescenta ao fim**, nunca reescreve: cada entrada é uma linha de lista em
Markdown, legível no editor e no relatório, ::

    - **14:10:03** · automático · Captura `rede_20261118_141003.bin` iniciada: 2 canais · 400 kS/s, direto no computador.
    - **14:08:40** · você · Ar-condicionado ligado às 14h05.

com as linhas seguintes da mesma entrada recuadas em dois espaços (a conferência canal a canal, o relatório do
diagnóstico). As entradas ficam sob o título :data:`TITULO`: ele é escrito antes da primeira e de novo quando o último
título do arquivo (na coluna 0) é outro, porque o usuário escreveu uma seção depois. Assim nada entra no meio do que
ele escreveu. Sem o arquivo, o aplicativo o cria só com o título do dia, e o ``lab`` depois o acha "já existia".

**A leitura** (:func:`ler`) acha as entradas em qualquer parte do arquivo: as escritas à mão no mesmo formato também
valem (com a hora em ``HH:MM`` ou ``HH:MM:SS``).
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path

NOME_DO_ARQUIVO = "anotacoes.md"
TITULO = "## Caderno de bancada"
AUTOMATICO, VOCE = "automático", "você"
AUTORES = (AUTOMATICO, VOCE)
RECUO = "  "

_ENTRADA = re.compile(r"^- \*\*(\d{1,2}):(\d{2})(?::(\d{2}))?\*\* · (automático|você) · (.*)$")
_TITULO = re.compile(r"^#{1,6}\s")


@dataclass(frozen=True)
class Entrada:
    """Uma entrada: a hora, quem escreveu (:data:`AUTOMATICO` ou :data:`VOCE`) e o texto, com as linhas de
    continuação sem o recuo."""

    hora: datetime.time
    autor: str
    texto: str

    @property
    def linhas(self) -> list[str]:
        return self.texto.split("\n")

    @property
    def hora_em_texto(self) -> str:
        return self.hora.strftime("%H:%M:%S")


def caminho_do_caderno(pasta_da_sessao: Path) -> Path:
    return Path(pasta_da_sessao) / NOME_DO_ARQUIVO


def ler(caminho: Path) -> list[Entrada]:
    """As entradas de ``caminho``, na ordem do arquivo (a mais nova por último); sem o arquivo, nenhuma."""
    try:
        texto = Path(caminho).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    return ler_texto(texto)


def ler_texto(texto: str) -> list[Entrada]:
    entradas: list[Entrada] = []
    atual: tuple[datetime.time, str, list[str]] | None = None
    vazias = 0                                   # as linhas vazias depois da última da entrada, ainda sem dono

    def fechar() -> None:
        if atual is not None:
            entradas.append(Entrada(atual[0], atual[1], "\n".join(atual[2]).rstrip()))

    for linha in texto.splitlines():
        achada = _ENTRADA.match(linha)
        if achada:
            fechar()
            h, m, s, autor, primeira = achada.groups()
            try:
                hora = datetime.time(int(h), int(m), int(s or 0))
            except ValueError:
                atual = None
                continue
            atual, vazias = (hora, autor, [primeira.rstrip()]), 0
        elif atual is not None and linha.startswith(RECUO) and linha.strip():
            atual[2].extend([""] * vazias)
            atual[2].append(linha[len(RECUO):].rstrip())
            vazias = 0
        elif atual is not None and not linha.strip():
            vazias += 1
        else:
            fechar()
            atual, vazias = None, 0
    fechar()
    return entradas


def formatar(texto: str, autor: str, quando: datetime.datetime | datetime.time) -> str:
    """A entrada como vai para o arquivo (com a quebra de linha no fim). As linhas vazias do meio ficam só com o
    recuo, para a entrada não se partir na leitura."""
    if autor not in AUTORES:
        raise ValueError(f"autor desconhecido: {autor!r} (use {', '.join(AUTORES)})")
    linhas = [linha.rstrip() for linha in texto.strip().splitlines()]
    if not linhas or not linhas[0]:
        raise ValueError("uma entrada do caderno precisa de texto")
    hora = quando.strftime("%H:%M:%S")
    saida = [f"- **{hora}** · {autor} · {linhas[0]}"]
    saida.extend(RECUO + linha if linha else RECUO for linha in linhas[1:])
    return "\n".join(saida) + "\n"


def criar(caminho: Path, quando: datetime.datetime | None = None) -> bool:
    """Cria ``caminho`` só com o título do dia, se ele não existe (para abrir no editor antes da primeira entrada).
    ``True`` se criou. ``OSError`` se o disco recusar."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(caminho, "x", encoding="utf-8") as arquivo:
            arquivo.write(_cabecalho(caminho, quando or datetime.datetime.now()))
    except FileExistsError:
        return False
    return True


def acrescentar(caminho: Path, texto: str, autor: str, quando: datetime.datetime | None = None) -> Entrada:
    """Acrescenta a entrada ao fim de ``caminho`` (criando a pasta e o arquivo, se for preciso) e a devolve. Um
    ``write`` só, no modo de acréscimo. ``OSError`` se o disco recusar."""
    quando = quando or datetime.datetime.now()
    entrada = formatar(texto, autor, quando)
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    try:
        existente = caminho.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        existente = None
    if existente is None:
        prefixo = _cabecalho(caminho, quando) + TITULO + "\n\n"
    else:
        prefixo = "" if existente.endswith("\n") or not existente else "\n"
        if _ultimo_titulo(existente) != TITULO:
            prefixo += ("\n" if existente.strip() else "") + TITULO + "\n\n"
    with open(caminho, "a", encoding="utf-8") as arquivo:
        arquivo.write(prefixo + entrada)
    (achada,) = ler_texto(entrada)
    return achada


def _cabecalho(caminho: Path, quando: datetime.datetime) -> str:
    return f"# Anotações da bancada: {_dia(caminho, quando)}\n\n"


def _ultimo_titulo(texto: str) -> str | None:
    ultimo = None
    for linha in texto.splitlines():
        if _TITULO.match(linha):
            ultimo = linha.rstrip()
    return ultimo


def _dia(caminho: Path, quando: datetime.datetime) -> str:
    """O dia do título: o nome da pasta da sessão (``AAAA-MM-DD``), senão a data de ``quando``."""
    try:
        return datetime.date.fromisoformat(caminho.parent.name).isoformat()
    except ValueError:
        return quando.date().isoformat()
