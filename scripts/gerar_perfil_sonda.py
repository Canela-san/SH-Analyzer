#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "numpy>=1.20",
#     "scipy>=1.15.3",
#     "matplotlib>=3.10.9",
# ]
# ///
"""gerar_perfil_sonda.py -- constrói o perfil de calibração (.json) de uma sonda
de corrente a partir das capturas geradas por firmware/calibrar_sonda.sh.

Este arquivo é só a ENTRADA de linha de comando; a lógica mora no pacote
``supraharmonicos`` (ao lado deste arquivo): medição em ``calibracao_sonda``,
escrita do JSON em ``escrita_perfil``, flags em ``cli_gerar_perfil``. A
explicação de como a corrente real é conhecida, de como a frequência é medida
e do gotcha de unidades do ``--ganho`` está no docstring de
``supraharmonicos/calibracao_sonda.py``.

    uv run scripts/gerar_perfil_sonda.py capturas/fluke_i30_01 \\
        --resistencia-shunt 0.1 --ganho 1,10 \\
        --fabricante Fluke --modelo i30s --plot
"""

from supraharmonicos.cli_gerar_perfil import main

if __name__ == "__main__":
    raise SystemExit(main())
