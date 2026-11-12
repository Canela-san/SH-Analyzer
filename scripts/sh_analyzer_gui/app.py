"""O aplicativo: a ``QApplication`` com o nome, a versão e o ícone da marca, e a janela principal.

Depende de: ``janela``.
"""

from __future__ import annotations

import sys
from importlib import metadata, resources

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from sh_analyzer_gui.janela import JanelaPrincipal

NOME = "SH-Analyzer"
ORGANIZACAO = "SH-Analyzer"     # o QSettings guarda a configuração numa pasta com este nome, em cada sistema

# O ícone pequeno (traço grosso, sem grade) é desenhado para 16 a 32 px; o grande, de 48 px para cima
# (report/gerar_marca.py). As cópias em recursos/ são conferidas contra docs/images/ por tests/test_marca.py.
TAMANHOS_DO_ICONE = (("app-icon-small.svg", (16, 24, 32)), ("app-icon.svg", (48, 64, 128, 256)))


def versao() -> str:
    """A versão do pacote instalado (a do ``pyproject.toml``), ou ``"dev"`` fora de uma instalação."""
    try:
        return metadata.version("sh-analyzer")
    except metadata.PackageNotFoundError:
        return "dev"


def icone_do_aplicativo() -> QIcon:
    """O ícone da marca em cada tamanho, renderizado dos SVGs. Precisa de uma ``QApplication``.

    O motor de SVG do Qt guarda um arquivo só por modo e estado: com os dois SVGs num ``QIcon``, o segundo
    substituiria o primeiro. Renderizar cada tamanho para um pixmap deixa o Qt escolher o desenho certo para o
    tamanho pedido (o pequeno na barra de título, o grande no alternador de janelas)."""
    pasta = resources.files("sh_analyzer_gui") / "recursos"
    icone = QIcon()
    for nome, lados in TAMANHOS_DO_ICONE:
        origem = QIcon(str(pasta / nome))
        for lado in lados:
            icone.addPixmap(origem.pixmap(lado, lado))
    return icone


def criar_aplicacao(argv: list[str] | None = None) -> QApplication:
    """A ``QApplication`` com o nome, a organização, a versão e o ícone. Reaproveita a que já existir (o Qt só
    admite uma por processo; nos testes, a do pytest-qt)."""
    app = QApplication.instance() or QApplication(sys.argv if argv is None else argv)
    app.setApplicationName(NOME)
    app.setOrganizationName(ORGANIZACAO)
    app.setApplicationVersion(versao())
    app.setWindowIcon(icone_do_aplicativo())
    return app


def main(argv: list[str] | None = None) -> int:
    """Abre a interface e devolve o código de saída do laço de eventos."""
    app = criar_aplicacao(argv)
    janela = JanelaPrincipal()
    janela.show()
    return app.exec()
