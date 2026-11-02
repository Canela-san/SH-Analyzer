#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "numpy>=1.20",
#     "scipy>=1.15.3",
#     "matplotlib>=3.10.9",
# ]
# ///
"""medir_shunt.py -- a impedância Z(f) de um resistor pelo osciloscópio (a tensão e a corrente na mesma captura),
o --shunt do medir_fase.py --canal-referencia.

Este arquivo é só a ENTRADA de linha de comando; a lógica mora no pacote ``supraharmonicos`` (``razao_quadrada`` e
``cli_medir_shunt``).

    uv run scripts/medir_shunt.py $DIA/shunt_1280Hz.csv $DIA/shunt_20736Hz.csv --csv scripts/sondas/shunt.csv
"""

from supraharmonicos.cli_medir_shunt import main

if __name__ == "__main__":
    raise SystemExit(main())
