#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "numpy>=1.20",
#     "rich>=13.7",
# ]
# ///
"""compactar_amostras.py -- arquiva as capturas do SH-Analyzer SEM PERDAS num pacote ``.zpaq.tar``
(zpaq -m5 + canais desentrelaçados; ~11 % do tamanho original) e as restaura, conferindo o SHA-256.

Este arquivo é só a ENTRADA de linha de comando; a lógica mora no pacote ``supraharmonicos``
(``compactacao`` e ``cli_compactar``). Precisa do ``zpaq`` (``sudo apt install zpaq``), exceto com ``--rapido``.

    uv run scripts/compactar_amostras.py Collected_Data              # compacta (e confere) a pasta
    uv run scripts/compactar_amostras.py listar Collected_Data_2026-10-20.zpaq.tar
    uv run scripts/compactar_amostras.py extrair Collected_Data_2026-10-20.zpaq.tar T7c_10min.bin
"""

from supraharmonicos.cli_compactar import main

if __name__ == "__main__":
    raise SystemExit(main())
