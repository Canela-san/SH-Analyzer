#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "numpy>=1.20",
#     "scipy>=1.15.3",
#     "matplotlib>=3.10.9",
# ]
# ///
"""medir_fase.py -- magnitude e FASE da cadeia a partir de capturas de onda quadrada, sem osciloscópio (S2).

Este arquivo é só a ENTRADA de linha de comando; a lógica mora no pacote ``supraharmonicos`` (``fase_quadrada`` e
``cli_medir_fase``).

    uv run scripts/medir_fase.py $DIA/T3f_*/F_*.bin --csv fase.csv --plot fase.png
"""

from supraharmonicos.cli_medir_fase import main

if __name__ == "__main__":
    raise SystemExit(main())
