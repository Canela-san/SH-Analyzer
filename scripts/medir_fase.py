#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "numpy>=1.20",
#     "scipy>=1.15.3",
#     "matplotlib>=3.10.9",
# ]
# ///
"""medir_fase.py -- a calibração da cadeia (magnitude e FASE) a partir de capturas de onda quadrada (S2), as do
``coletar.sh calibrar``; com ``--entrada``, dividida pela forma de onda da entrada medida no osciloscópio.

Este arquivo é só a ENTRADA de linha de comando; a lógica mora no pacote ``supraharmonicos`` (``fase_quadrada`` e
``cli_medir_fase``).

    uv run scripts/medir_fase.py $DIA/CAL_*/F_*_f20.48_*.bin --entrada $DIA/CAL_*/ref_*.csv --csv fase.csv --plot fase.png
"""

from supraharmonicos.cli_medir_fase import main

if __name__ == "__main__":
    raise SystemExit(main())
