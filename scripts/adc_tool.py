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
"""adc_tool.py -- a ferramenta do SH-Analyzer para as capturas do ADS8688 (BeagleBone):
análise (forma de onda, FFT, Welch, harmônicos, bandas IEC, espectrograma, exportação para
CSV/JSON/MATLAB), conversão e HDF5, e os subcomandos info, medir, perfil e compactar.

Este arquivo é só a ENTRADA de linha de comando; a lógica mora no pacote
``supraharmonicos`` (ao lado deste arquivo). Rode com ``--help`` para os subcomandos e a
referência de flags, e consulte ``docs/software-architecture.md`` para o mapa do código.

    uv run scripts/adc_tool.py captura.bin --welch --filtro-passa-alta 2000
    uv run scripts/adc_tool.py info captura.bin --estatisticas
"""

from supraharmonicos.cli_principal import main

if __name__ == "__main__":
    raise SystemExit(main())
