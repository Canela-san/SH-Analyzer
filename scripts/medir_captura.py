#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "numpy>=1.20",
#     "scipy>=1.15.3",
# ]
# ///
"""medir_captura.py -- mede capturas .bin do SH-Analyzer e imprime números para o relatório
(DC, RMS, ruído, tom, harmônicos, THD, SINAD, ENOB, SFDR, continuidade, acoplamento entre canais).

Este arquivo é só a ENTRADA de linha de comando; a lógica mora no pacote
``supraharmonicos`` (``metricas_captura`` e ``cli_medir_captura``).

    uv run scripts/medir_captura.py senoide_10k.bin --rotulo "T3 10 kHz" --csv resultados.csv
"""

from supraharmonicos.cli_medir_captura import main

if __name__ == "__main__":
    raise SystemExit(main())
