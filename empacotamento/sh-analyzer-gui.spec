# Receita do PyInstaller para o aplicativo numa pasta (docs/gui-plan.md, seção 15; F0.11 em docs/gui-progress.md).
#
#   uv run --extra gui --with pyinstaller pyinstaller empacotamento/sh-analyzer-gui.spec \
#       --distpath PASTA/dist --workpath PASTA/obra --noconfirm
#
# (PASTA fora do repositório.) Sai em PASTA/dist/sh-analyzer-gui/: o executável e a pasta _internal com o Python, o Qt e as bibliotecas. As
# bibliotecas do Qt ficam como arquivos separados (a LGPL do PySide6 pede que o usuário possa trocá-las).
# ruff: noqa  (é Python, mas o PyInstaller injeta Analysis, PYZ, EXE e COLLECT)

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

RAIZ = Path(SPECPATH).parent          # noqa: F821 (SPECPATH é do PyInstaller)
SCRIPTS = RAIZ / "scripts"

# Os módulos do Qt que o aplicativo não usa: tirar diminui a pasta em centenas de MB.
QT_FORA = [f"PySide6.{m}" for m in (
    "QtWebEngineCore", "QtWebEngineWidgets", "QtWebEngineQuick", "QtWebChannel", "QtWebSockets", "QtWebView",
    "Qt3DCore", "Qt3DRender", "Qt3DInput", "Qt3DLogic", "Qt3DAnimation", "Qt3DExtras", "QtQuick3D",
    "QtMultimedia", "QtMultimediaWidgets", "QtSpatialAudio", "QtCharts", "QtDataVisualization", "QtGraphs",
    "QtQuick", "QtQuickWidgets", "QtQuickControls2", "QtQml", "QtDesigner", "QtUiTools", "QtHelp", "QtPdf",
    "QtPdfWidgets", "QtBluetooth", "QtNfc", "QtPositioning", "QtLocation", "QtSensors", "QtSerialBus",
    "QtTextToSpeech", "QtRemoteObjects", "QtScxml", "QtSql", "QtTest", "QtHttpServer", "QtNetworkAuth",
)]

a = Analysis(  # noqa: F821
    [str(RAIZ / "empacotamento" / "entrada.py")],
    pathex=[str(SCRIPTS)],
    # A interface importa as telas, o motor e a placa sob demanda: aqui entram todos, para o pacote ter o que o
    # aplicativo vai usar (o NumPy, o SciPy e o Matplotlib vêm com o motor).
    hiddenimports=collect_submodules("sh_analyzer_gui") + collect_submodules("sh_placa") + ["supraharmonicos.api"],
    datas=collect_data_files("sh_analyzer_gui", includes=["recursos/*", "recursos/fontes/*"]),
    excludes=QT_FORA + ["tkinter", "PyQt5", "PyQt6", "PySide2", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name="sh-analyzer-gui", console=False,
    # O ícone do executável é coisa do Windows (um .ico, gerado da marca, entra com o instalador do Windows); no
    # Linux, o ícone vem do .desktop do AppImage, e a janela usa o da marca (app.icone_do_aplicativo).
)
coll = COLLECT(exe, a.binaries, a.datas, name="sh-analyzer-gui")  # noqa: F821
