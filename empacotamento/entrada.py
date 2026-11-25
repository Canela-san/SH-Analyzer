"""O ponto de entrada do aplicativo empacotado (o PyInstaller precisa de um script): o mesmo ``sh-analyzer-gui`` do
``pyproject.toml``; com ``SHAN_COMO_PYTHON`` no ambiente, um Python (``sh_placa.como_python``: o da placa simulada e o
do agente local, que fora do pacote são o ``sys.executable``)."""

import os
import sys

# No Windows, o executável sem console (o da janela) não tem saída quando ninguém a pede: o que for escrito vai para o
# nada, e não para um None (o --versao, um aviso). Lançado com a saída num arquivo ou num pipe, ela existe.
for _nome in ("stdout", "stderr"):
    if getattr(sys, _nome) is None:
        setattr(sys, _nome, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115 (vive o processo inteiro)

from sh_placa import como_python  # noqa: E402

if como_python.pedido():
    raise SystemExit(como_python.rodar(sys.argv[1:]))

from sh_analyzer_gui.app import main  # noqa: E402 (só depois: o Python da placa simulada não carrega o Qt)

raise SystemExit(main())
