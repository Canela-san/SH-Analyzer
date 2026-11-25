"""O ponto de entrada do aplicativo empacotado (o PyInstaller precisa de um script): o mesmo ``sh-analyzer-gui`` do
``pyproject.toml``; com ``SHAN_COMO_PYTHON`` no ambiente, um Python (``sh_placa.como_python``: o da placa simulada e o
do agente local, que fora do pacote são o ``sys.executable``)."""

import hashlib
import os
import sys
import traceback
from pathlib import Path

# No Windows, o executável sem console (o da janela) não tem saída quando ninguém a pede: o que for escrito vai para o
# nada, e não para um None (o --versao, um aviso). Lançado com a saída num arquivo ou num pipe, ela existe.
for _nome in ("stdout", "stderr"):
    if getattr(sys, _nome) is None:
        setattr(sys, _nome, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115 (vive o processo inteiro)
    # A saída em UTF-8, como no Linux: no Windows, o padrão de um pipe é o cp1252, que recusa o "✓" de uma conferência e
    # os acentos de um caminho (o erro derrubava o programa).
    elif getattr(sys, _nome).encoding.lower().replace("-", "") != "utf8":
        getattr(sys, _nome).reconfigure(encoding="utf-8", errors="backslashreplace")


def _cache_do_matplotlib() -> None:
    """O cache do Matplotlib numa pasta do aplicativo, uma por instalação. O gancho do PyInstaller o põe numa pasta
    temporária a cada partida (feito para o pacote num arquivo só, cuja pasta muda a cada vez), e o Matplotlib relia
    todas as fontes do sistema a cada partida (+2,5 s). No pacote numa pasta, o caminho não muda; o resumo dele no
    nome separa duas instalações (uma movida acha o cache vazio, e não os caminhos da outra). Sem a pasta (um disco
    que recusa), fica a temporária."""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        return
    from platformdirs import user_cache_dir

    resumo = hashlib.sha256(os.path.abspath(base).encode("utf-8")).hexdigest()[:12]
    pasta = Path(user_cache_dir("sh-analyzer", appauthor=False)) / "matplotlib" / resumo
    try:
        pasta.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    os.environ["MPLCONFIGDIR"] = str(pasta)


_cache_do_matplotlib()

from sh_placa import como_python  # noqa: E402

if como_python.pedido():
    # Um erro não tratado sai na saída de erros com o código 1, como no Python. Se subisse até o PyInstaller, o
    # executável sem console do Windows o mostraria numa caixa de diálogo, que espera um clique para sempre (a CI dos
    # instaladores ficou parada nela).
    try:
        codigo = como_python.rodar(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        codigo = 1
    raise SystemExit(codigo)

from sh_analyzer_gui.app import main  # noqa: E402 (só depois: o Python da placa simulada não carrega o Qt)

raise SystemExit(main())
