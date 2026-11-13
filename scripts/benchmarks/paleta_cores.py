"""A conferência das cores da interface (docs/gui-plan.md, seção 12): contraste e separação para daltônicos.

Escreve, para cada tema, o contraste de cada cor de traço contra a área dos gráficos (>= 3:1) e o pior par de cada
regra da paleta (``sh_analyzer_gui.tema.cores.regras_da_paleta``), e confere o contraste dos textos contra a
superfície (>= 4,5:1). Os valores são os tokens (``sh_analyzer_gui/tema/tokens.py``); o ``tests/test_tema.py`` faz
as mesmas contas na suíte. Uso: ``python scripts/benchmarks/paleta_cores.py`` (só NumPy); sai com 1 se algo
reprovar.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))     # scripts/, para importar o pacote da interface

from sh_analyzer_gui.tema.cores import CONTRASTE_GRAFICO, CONTRASTE_TEXTO, contraste, regras_da_paleta  # noqa: E402
from sh_analyzer_gui.tema.tokens import TEMAS  # noqa: E402

TEXTOS = ("texto", "texto2", "mudo", "acento", "ok", "aviso", "erro")


def conferir(tema) -> list[str]:
    falhas = []
    escrever = sys.stdout.write
    escrever(f"\nTema {tema.nome}\n")
    for i, cor in enumerate(tema.tracos, 1):
        c = contraste(cor, tema.afundada)
        escrever(f"  traço {i} {cor}: contraste {c:4.1f}:1 contra {tema.afundada}\n")
        if c < CONTRASTE_GRAFICO:
            falhas.append(f"{tema.nome}: traço {i} com contraste {c:.1f}:1 (< {CONTRASTE_GRAFICO:g}:1)")
    for papel in TEXTOS:
        c = contraste(getattr(tema, papel), tema.superficie)
        if c < CONTRASTE_TEXTO:
            falhas.append(f"{tema.nome}: {papel} com contraste {c:.1f}:1 (< {CONTRASTE_TEXTO:g}:1)")
    for nome, d, minimo, (a, b, v) in regras_da_paleta(tema.tracos):
        escrever(f"  {nome:44} pior ΔE {d:5.1f} ({a} × {b}, {v}); mínimo {minimo:g}: "
                 f"{'ok' if d >= minimo else 'REPROVA'}\n")
        if d < minimo:
            falhas.append(f"{tema.nome}: {nome}: ΔE {d:.1f} < {minimo:g}")
    return falhas


def main() -> int:
    falhas = [f for tema in TEMAS.values() for f in conferir(tema)]
    sys.stdout.write("\n" + ("Tudo certo.\n" if not falhas else "Reprovado:\n  " + "\n  ".join(falhas) + "\n"))
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
