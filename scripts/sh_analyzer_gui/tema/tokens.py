"""Os tokens do sistema de design: as cores, os tamanhos e os espaços dos dois temas (docs/gui-plan.md, 12.2 a 12.5).

Definidos uma vez, aqui; a ``QPalette`` e o QSS (``aplicar.py``) e os mockups (``docs/gui-mockups/tema.css``) usam
os mesmos valores, e ``tests/test_tema.py`` confere que o CSS dos mockups não divergiu e que as cores passam nas
contas de contraste e de daltonismo (``cores.py``).

Sem Qt: roda e se testa sem interface.
"""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Tema:
    """As cores de um tema (``#rrggbb``). Os nomes são os do CSS dos mockups, com ``_`` no lugar de ``-``."""

    nome: str
    fundo: str            # a janela
    superficie: str       # painéis
    elevada: str          # menus, popovers, cartões em destaque
    afundada: str         # a área dos dados (gráficos, terminal, campos)
    borda: str
    borda_forte: str
    texto: str
    texto2: str           # rótulos, unidades, eixos
    mudo: str             # dicas e metadados
    acento: str           # seleção, foco, ação principal
    acento_texto: str     # texto sobre o acento
    destaque: str         # cursores, marcadores, medidas destacadas
    destaque_texto: str
    ok: str
    aviso: str
    erro: str
    grade: str
    grade_forte: str
    eixo: str
    tracos: tuple[str, ...]   # as 6 cores dos traços, na ordem fixa (12.3)
    escuro: bool

    @property
    def tokens(self) -> dict[str, str]:
        """As cores como ``nome -> valor`` (sem os traços nem os campos que não são cores)."""
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name not in ("nome", "tracos", "escuro")}


ESCURO = Tema(
    nome="escuro",
    fundo="#0f1a2e", superficie="#16243b", elevada="#1d2e4a", afundada="#0c1526",
    borda="#2a3d5a", borda_forte="#3a5072",
    texto="#e6edf6", texto2="#9fb0c8", mudo="#7d8fa9",
    acento="#7dd3fc", acento_texto="#0c1526",
    destaque="#fbbf24", destaque_texto="#1a1205",
    ok="#4ade80", aviso="#fb923c", erro="#f87171",
    grade="#1c2a42", grade_forte="#26385a", eixo="#9fb0c8",
    tracos=("#7dd3fc", "#fbbf24", "#fb7185", "#818cf8", "#34d399", "#e879f9"),
    escuro=True,
)

CLARO = Tema(
    nome="claro",
    fundo="#f3f5f9", superficie="#ffffff", elevada="#ffffff", afundada="#ffffff",
    borda="#d5dce6", borda_forte="#b8c3d3",
    texto="#0f172a", texto2="#4b5b73", mudo="#64748b",
    acento="#0369a1", acento_texto="#ffffff",
    destaque="#b45309", destaque_texto="#ffffff",
    ok="#15803d", aviso="#c2410c", erro="#b91c1c",
    grade="#e9eef4", grade_forte="#d5dce6", eixo="#4b5b73",
    tracos=("#0284c7", "#d97706", "#be123c", "#3730a3", "#047857", "#c026d3"),
    escuro=False,
)

TEMAS = {"escuro": ESCURO, "claro": CLARO}

NOMES_DOS_TRACOS = ("céu", "âmbar", "rosa", "índigo", "esmeralda", "fúcsia")
"""O matiz de cada posição da paleta: a cor muda de tom entre os temas, nunca de matiz (o traço 1 é sempre o céu)."""

# Tipografia (12.4): tamanhos em pontos-pixel lógicos.
FONTE_INTERFACE = "Inter"
FONTE_MONO = "JetBrains Mono"
TAMANHOS = {"legenda": 11, "secundario": 12, "corpo": 13, "titulo_painel": 15, "secao": 18, "tela": 22}

# Espaço e forma (12.5): a grade de 4 px e os raios.
ESPACOS = (4, 8, 12, 16, 24, 32)
RAIOS = {"campo": 6, "cartao_pequeno": 8, "cartao": 10, "flutuante": 12}
ALTURA_LINHA = {"compacta": 26, "confortavel": 32}


def cor_do_traco(indice: int, tema: Tema) -> tuple[str, bool]:
    """A cor do traço ``indice`` (0, 1, 2...) e se ele é tracejado: do 7º em diante, os matizes se repetem
    tracejados (12.3) -- nunca uma cor inventada."""
    return tema.tracos[indice % len(tema.tracos)], indice >= len(tema.tracos)
