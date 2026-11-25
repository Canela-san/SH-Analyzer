# Receita do PyInstaller para o aplicativo numa pasta (docs/gui-plan.md, seção 15; F0.11 e F7.12 em
# docs/gui-progress.md). Rode pelo empacotamento/construir.sh (o ambiente com os extras gui e placa, fora do .venv, e
# as conferências do pacote pronto); à mão:
#
#   uv run --extra gui --extra placa --with pyinstaller pyinstaller empacotamento/sh-analyzer-gui.spec \
#       --distpath PASTA/dist --workpath PASTA/obra --noconfirm
#
# (PASTA fora do repositório.) Sai em PASTA/dist/sh-analyzer-gui/: o executável e a pasta _internal com o Python, o
# Qt, as bibliotecas e os dados (o guia, as sondas, o firmware desta versão, os avisos e as licenças: o que vai, e
# por quê, está em empacotamento/receita.py). As bibliotecas do Qt, do zeroconf e do pyte ficam como arquivos
# separados (a LGPL pede que o usuário possa trocá-las).
# ruff: noqa  (é Python, mas o PyInstaller injeta Analysis, PYZ, EXE, COLLECT, SPECPATH e workpath)

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

RAIZ = Path(SPECPATH).parent          # noqa: F821 (SPECPATH é do PyInstaller)
SCRIPTS = RAIZ / "scripts"
OBRA = Path(workpath)                 # noqa: F821 (a pasta de trabalho desta construção)
sys.path[:0] = [str(SCRIPTS), str(RAIZ / "empacotamento")]

import receita  # noqa: E402

# Os módulos do Qt que o aplicativo não usa: tirar diminui a pasta em centenas de MB.
QT_FORA = [f"PySide6.{m}" for m in (
    "QtWebEngineCore", "QtWebEngineWidgets", "QtWebEngineQuick", "QtWebChannel", "QtWebSockets", "QtWebView",
    "Qt3DCore", "Qt3DRender", "Qt3DInput", "Qt3DLogic", "Qt3DAnimation", "Qt3DExtras", "QtQuick3D",
    "QtMultimedia", "QtMultimediaWidgets", "QtSpatialAudio", "QtCharts", "QtDataVisualization", "QtGraphs",
    "QtQuick", "QtQuickWidgets", "QtQuickControls2", "QtQml", "QtDesigner", "QtUiTools", "QtHelp", "QtPdf",
    "QtPdfWidgets", "QtBluetooth", "QtNfc", "QtPositioning", "QtLocation", "QtSensors", "QtSerialBus",
    "QtTextToSpeech", "QtRemoteObjects", "QtScxml", "QtSql", "QtTest", "QtHttpServer", "QtNetworkAuth",
)]

datas = collect_data_files("sh_analyzer_gui", includes=["recursos/*", "recursos/fontes/*"])
datas += [(str(RAIZ / "docs" / "gui-guide.md"), "ajuda")]                       # ajuda.caminho_do_guia
datas += [(str(p), "sondas") for p in sorted((SCRIPTS / "sondas").glob("*.json"))]  # supraharmonicos.sonda
datas += receita.preparar_firmware(OBRA / "firmware")                          # sh_placa.atualizacao e .agente
datas += [(str(RAIZ / "empacotamento" / "AVISOS.txt"), "."), (str(RAIZ / "LICENSE"), "."),
          *((str(p), "licencas") for p in sorted((RAIZ / "empacotamento" / "licencas").glob("*.txt")))]
for distribuicao in ["sh-analyzer", *receita.distribuicoes()]:          # a do projeto: o --versao
    datas += copy_metadata(distribuicao)

a = Analysis(  # noqa: F821
    [str(RAIZ / "empacotamento" / "entrada.py")],
    pathex=[str(SCRIPTS)],
    # A interface importa as telas, o motor e a placa sob demanda: aqui entram todos, para o pacote ter o que o
    # aplicativo vai usar (o NumPy, o SciPy e o Matplotlib vêm com o motor). E os módulos do agente e dos programas da
    # placa simulada, que rodam com o executável fazendo de Python (sh_placa.como_python).
    # E as partes do SciPy que ele importa pelo nome (o array_api_compat: sem ele, o scipy.fft não carrega no pacote).
    hiddenimports=(collect_submodules("sh_analyzer_gui") + collect_submodules("sh_placa")
                   + collect_submodules("supraharmonicos") + receita.modulos_dos_programas()
                   + collect_submodules("scipy._external", filter=lambda nome: not any(
                       f".{outro}" in nome for outro in ("cupy", "torch", "dask", "jax")))),
    datas=datas,
    excludes=QT_FORA + ["tkinter", "PyQt5", "PyQt6", "PySide2", "IPython", "pytest"],
    # As bibliotecas LGPL em Python como arquivos .py (e não dentro do PYZ): dá para trocá-las.
    module_collection_mode={"zeroconf": "py", "pyte": "py"},
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
icone = receita.gerar_ico(OBRA / "sh-analyzer.ico") if sys.platform == "win32" else None
exe = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name="sh-analyzer-gui", console=False,
    # O ícone do executável é coisa do Windows (o .ico gerado da marca); no Linux, o ícone vem do atalho
    # (--instalar-atalho), e a janela usa o da marca (app.icone_do_aplicativo).
    icon=str(icone) if icone else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="sh-analyzer-gui")  # noqa: F821
