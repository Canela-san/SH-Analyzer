#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "matplotlib>=3.10.9",
#     "numpy>=1.20",
#     "scipy>=1.15.3",
#     "PyQt6",
#     "h5py>=3.0",
#     "rich>=13.7",
# ]
# ///
"""adc_gui.py -- a interface gráfica do SH-Analyzer: a análise do adc_tool.py numa janela (PyQt6).

Abra uma captura, ajuste os parâmetros no painel e veja a forma de onda, os espectros (FFT e Welch),
os harmônicos, os picos, as bandas IEC e o espectrograma; exporte CSV/JSON, .mat, HDF5 e as figuras.
O comando equivalente do adc_tool.py fica à vista e pode ser copiado. O mesmo que ``adc_tool.py gui``.

Este arquivo é só a ENTRADA; a lógica mora no pacote ``supraharmonicos`` (ao lado deste arquivo).

    uv run scripts/adc_gui.py
    uv run scripts/adc_gui.py captura.bin
"""

from supraharmonicos.cli_gui import main

if __name__ == "__main__":
    raise SystemExit(main())
