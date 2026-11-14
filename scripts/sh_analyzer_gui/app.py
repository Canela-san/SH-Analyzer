"""O aplicativo: a ``QApplication`` com o nome, a versão e o ícone da marca, e a janela principal.

Depende de: ``janela``, ``tema``.
"""

from __future__ import annotations

import argparse
import sys
from importlib import metadata, resources
from pathlib import Path

from PySide6.QtCore import QLoggingCategory, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from supraharmonicos.api import aquecer

from sh_analyzer_gui import preferencias
from sh_analyzer_gui.configuracao import APLICATIVO, ORGANIZACAO
from sh_analyzer_gui.janela import JanelaPrincipal
from sh_analyzer_gui.tema.aplicar import aparencia
from sh_analyzer_gui.tema.fontes import fonte_da_interface, registrar_fontes

NOME = APLICATIVO

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


def criar_aplicacao(argv: list[str] | None = None, tema: str = "sistema") -> QApplication:
    """A ``QApplication`` com o nome, a organização, a versão, o ícone, as fontes e o tema (``"sistema"``,
    ``"escuro"`` ou ``"claro"``). Reaproveita a que já existir (o Qt só admite uma por processo; nos testes, a do
    pytest-qt)."""
    app = QApplication.instance() or QApplication(sys.argv if argv is None else argv)
    app.setApplicationName(NOME)
    app.setOrganizationName(ORGANIZACAO)
    app.setApplicationVersion(versao())
    app.setWindowIcon(icone_do_aplicativo())
    registrar_fontes()
    app.setFont(fonte_da_interface())
    aparencia(app).aplicar(tema)
    ligar_coleta_na_thread_da_interface(app)
    return app


def ligar_coleta_na_thread_da_interface(app: QApplication) -> None:
    """A coleta de lixo do Python só na thread da interface, num temporizador do Qt (o ``GarbageCollector`` do
    PyQtGraph: a automática desligada, a mesma regra de gerações). A automática roda em qualquer thread: numa tarefa
    em segundo plano, ela apagava widgets de uma janela fechada fora da thread da interface, e o processo caía (um
    segmentation fault na CI da interface, em 14/11/2026). Uma vez por aplicação."""
    if getattr(app, "_coletor_de_lixo", None) is None:
        from pyqtgraph.util.garbage_collector import GarbageCollector

        app._coletor_de_lixo = GarbageCollector(interval=1.0)


OPCAO_SAIR_AO_ABRIR = "--sair-ao-abrir"


def ler_opcoes(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    """As opções do aplicativo; o que sobra (as do Qt, como ``-platform offscreen``) segue para a ``QApplication``.

    O projeto a abrir (``PROJETO.shproj``, o que o sistema passa num duplo clique) é tirado antes do ``argparse``:
    como argumento posicional, ele engoliria o valor de uma opção do Qt (o ``offscreen`` de ``-platform``)."""
    projetos = [a for a in argv[1:] if a.lower().endswith(".shproj")]
    resto_bruto = [a for a in argv[1:] if a not in projetos]
    p = argparse.ArgumentParser(prog="sh-analyzer-gui", usage="%(prog)s [opções] [PROJETO.shproj]",
                                description="A interface gráfica do SH-Analyzer.")
    p.add_argument("--tema", choices=("sistema", "escuro", "claro"),
                   help="o tema da interface (padrão: o último escolhido, ou o do sistema)")
    p.add_argument("--versao", action="store_true", help="mostra a versão e sai")
    p.add_argument(OPCAO_SAIR_AO_ABRIR, action="store_true",
                   help="abre a janela, pinta o primeiro quadro e sai (o teste de partida do instalador)")
    opcoes, resto = p.parse_known_args(resto_bruto)
    opcoes.arquivo = Path(projetos[0]) if projetos else None
    return opcoes, argv[:1] + resto


CATEGORIAS_SILENCIADAS = ("qt.qpa.wayland.textinput",)
"""Avisos do Qt que não dizem nada sobre o aplicativo. No Wayland, o plugin de entrada de texto do Qt escreve "Trying to
disable ... but ... is focused" a cada troca de foco entre superfícies (a janela, os menus, as dicas, a paleta) e
enchia o terminal. A variável ``QT_LOGGING_RULES`` ainda os liga de volta (ela tem precedência)."""


def silenciar_avisos_do_qt() -> None:
    QLoggingCategory.setFilterRules("\n".join(f"{c}=false" for c in CATEGORIAS_SILENCIADAS))


def main(argv: list[str] | None = None) -> int:
    """Abre a interface e devolve o código de saída do laço de eventos."""
    opcoes, argv_qt = ler_opcoes(list(sys.argv if argv is None else argv))
    if opcoes.versao:
        sys.stdout.write(f"{NOME} {versao()}\n")
        return 0
    silenciar_avisos_do_qt()
    app = criar_aplicacao(argv_qt, tema=opcoes.tema or preferencias.tema_salvo())
    preferencias.aplicar_fontes_salvas(app)
    janela = JanelaPrincipal()
    janela.show()
    if opcoes.sair_ao_abrir:
        QTimer.singleShot(0, app.quit)
    elif opcoes.arquivo is not None:
        QTimer.singleShot(0, lambda: janela.controle.abrir(opcoes.arquivo))
    else:
        QTimer.singleShot(0, janela.controle.oferecer_recuperacao)
    if not opcoes.sair_ao_abrir:
        # A primeira medida importaria o SciPy (~1,5 s, com o GIL preso, travando a tela aos pedaços): importado
        # agora, em segundo plano, enquanto a janela recém-aberta está parada.
        janela.tarefas.iniciar("Aquecer", lambda _progresso, _cancelado: aquecer(), mostrar=False)
    return app.exec()
