"""``adc_tool.py gui`` / ``adc_gui.py``: abre a interface gráfica.

A BORDA da interface: lê os argumentos (a captura a abrir, opcional), liga o logging ao console (o que a janela
mostra na aba "Console" também sai no terminal de onde ela foi aberta) e devolve o código de saída. Sem o PyQt6
instalado (o extra ``gui`` do ``pyproject.toml``; o ``uv run`` já o traz), avisa como instalar em vez de um traceback.

Depende de: ``erros``, ``registro`` e, só ao abrir a janela, ``gui``.
"""

import argparse
import logging
from pathlib import Path

from .erros import ErroSHAN
from .registro import configurar_logging_cli

log = logging.getLogger(__name__)


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adc_tool.py gui",
        description="A análise do adc_tool numa janela: abre a captura, ajuste os parâmetros no painel e veja a forma "
                    "de onda, os espectros, os harmônicos, os picos e as bandas IEC; exporte CSV/JSON, .mat, HDF5 e "
                    "as figuras. O comando equivalente da linha de comando fica à vista e pode ser copiado.",
    )
    parser.add_argument("arquivo", type=Path, nargs="?", default=None, metavar="CAPTURA.bin",
                        help="A captura a abrir ao iniciar (opcional; também dá para arrastá-la para a janela).")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = montar_parser()
    args = parser.parse_args(argv)
    configurar_logging_cli()
    try:
        try:
            from .gui import executar
        except ImportError as e:
            raise ErroSHAN(f"a interface gráfica precisa do PyQt6 ({e}). Instale o extra 'gui' "
                           f"(uv sync --extra gui, ou pip install -e '.[gui]'), ou rode 'uv run scripts/adc_gui.py'.")
        return executar([args.arquivo] if args.arquivo is not None else [])
    except ErroSHAN as e:
        log.error(str(e))
        return 1
