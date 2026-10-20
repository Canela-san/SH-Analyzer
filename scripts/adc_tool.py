#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "matplotlib>=3.10.9",
#     "numpy>=1.20",
#     "scipy>=1.15.3",
#     "PyQt6",
#     "h5py>=3.0",
# ]
# ///
"""adc_tool.py -- conversão, visualização, análise espectral e exportação HDF5
de capturas do SH-Analyzer (ADS8688 via BeagleBone).

Este arquivo é só a ENTRADA de linha de comando; a lógica mora no pacote
``supraharmonicos`` (ao lado deste arquivo). Rode com ``--help`` para a referência
completa de flags e consulte ``docs/software-architecture.md`` para o mapa do
código.

    uv run scripts/adc_tool.py captura.bin --welch --filtro-passa-alta 2000
"""

from supraharmonicos.cli_adc_tool import main

if __name__ == "__main__":
    raise SystemExit(main())
