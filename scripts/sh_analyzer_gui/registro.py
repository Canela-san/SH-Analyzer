"""O log do aplicativo (docs/gui-plan.md, 8.4): um arquivo em rotação na pasta de logs do sistema, para entender
depois um erro que o usuário viu.

* **Onde:** ``platformdirs.user_log_dir`` (no Linux, ``~/.local/state/sh-analyzer/log``; no Windows,
  ``%LOCALAPPDATA%\\sh-analyzer\\Logs``), ou a pasta da variável ``SH_ANALYZER_LOG`` (os testes, um pendrive).
* **Em rotação:** ``sh-analyzer.log`` com até 1 MiB e as 5 cópias anteriores (``.1`` a ``.5``): nunca passa de
  6 MiB.
* **O que vai:** o que a interface registra (INFO e acima), os avisos e erros do motor e de outras bibliotecas
  (WARNING e acima), os avisos do Python (``warnings``) e os do Qt. Os erros também saem no terminal.
* **O que nunca vai:** senhas e o conteúdo dos arquivos. Nenhum registro do aplicativo leva amostras, o texto de
  um projeto ou uma credencial; os caminhos dos arquivos abertos vão (são o que ajuda a reproduzir um erro). Quem
  registrar algo novo segue a mesma regra (a conexão com a placa, mais tarde: nenhuma senha, nem na linha de
  comando registrada).
* **Uma queda do processo** (um *segmentation fault* do Qt) não passa pelo Python: o ``faulthandler`` escreve a
  pilha das threads em ``quedas.log``, na mesma pasta.

Sem Qt no que é de arquivo; só :func:`ligar_o_log` encosta no Qt, para os avisos dele.
"""

from __future__ import annotations

import faulthandler
import functools
import logging
import logging.handlers
import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path

VARIAVEL_DA_PASTA = "SH_ANALYZER_LOG"
ARQUIVO = "sh-analyzer.log"
ARQUIVO_DAS_QUEDAS = "quedas.log"
TAMANHO_MAXIMO = 1 << 20
COPIAS = 5
FORMATO = "%(asctime)s %(levelname)-8s [%(threadName)s] %(name)s: %(message)s"
LOGGER_DA_INTERFACE = "sh_analyzer_gui"

log = logging.getLogger(__name__)
_ligado: LogDoAplicativo | None = None


def caminho_do_log() -> Path | None:
    """O arquivo do log ligado (o que o diálogo de erro mostra), ou None se ele não foi ligado."""
    return _ligado.caminho if _ligado is not None and _ligado.no_arquivo else None


def pasta_do_log() -> Path:
    pasta = os.environ.get(VARIAVEL_DA_PASTA)
    if pasta:
        return Path(pasta)
    from platformdirs import user_log_dir

    return Path(user_log_dir("sh-analyzer", appauthor=False))


@dataclass
class LogDoAplicativo:
    """O log ligado: ``caminho`` é o arquivo atual. :meth:`desligar` desfaz tudo (os testes)."""

    caminho: Path
    no_arquivo: bool = False                       # False: o arquivo não pôde ser criado (o log ficou no terminal)
    _manipuladores: list[logging.Handler] = field(default_factory=list, repr=False)
    _niveis: dict[str, int] = field(default_factory=dict, repr=False)
    _quedas: object | None = field(default=None, repr=False)
    _qt_antes: object | None = field(default=None, repr=False)
    _qt_ligado: bool = field(default=False, repr=False)

    def desligar(self) -> None:
        global _ligado
        if _ligado is self:
            _ligado = None
        raiz = logging.getLogger()
        for manipulador in self._manipuladores:
            raiz.removeHandler(manipulador)
            manipulador.close()
        for nome, nivel in self._niveis.items():
            logging.getLogger(nome or None).setLevel(nivel)
        logging.captureWarnings(False)
        if self._quedas is not None:
            faulthandler.disable()
            self._quedas.close()
        if self._qt_ligado:
            from PySide6.QtCore import qInstallMessageHandler

            qInstallMessageHandler(self._qt_antes)
        self._manipuladores, self._niveis, self._quedas, self._qt_ligado = [], {}, None, False


def ligar_o_log(pasta: Path | None = None, *, terminal: bool = True, qt: bool = True) -> LogDoAplicativo:
    """Liga o log em ``pasta`` (a do sistema, por padrão) e devolve onde ele está. ``terminal``: os erros também no
    terminal (a saída de erro). ``qt``: os avisos do Qt passam pelo log (eles iam só para o terminal).

    Uma pasta que não se cria (sem permissão, um disco cheio) não impede o aplicativo de abrir: o log fica só no
    terminal, e o caminho devolvido diz onde ele estaria."""
    pasta = Path(pasta) if pasta is not None else pasta_do_log()
    ligado = LogDoAplicativo(pasta / ARQUIVO)
    raiz = logging.getLogger()
    formato = logging.Formatter(FORMATO)
    arquivo: logging.Handler | None = None
    problema: OSError | None = None
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        arquivo = logging.handlers.RotatingFileHandler(ligado.caminho, maxBytes=TAMANHO_MAXIMO, backupCount=COPIAS,
                                                       encoding="utf-8")
    except OSError as e:
        problema = e
    if arquivo is not None:
        ligado.no_arquivo = True
        arquivo.setFormatter(formato)
        arquivo.setLevel(logging.INFO)
        ligado._manipuladores.append(arquivo)
    if terminal:
        saida = logging.StreamHandler(sys.stderr)
        saida.setFormatter(formato)
        saida.setLevel(logging.WARNING)
        ligado._manipuladores.append(saida)
    for manipulador in ligado._manipuladores:
        raiz.addHandler(manipulador)
    # A interface registra o que faz (INFO); das bibliotecas (o motor, o pyqtgraph, o NumPy), só os avisos.
    for nome, nivel in (("", logging.WARNING), (LOGGER_DA_INTERFACE, logging.INFO)):
        logger = logging.getLogger(nome or None)
        ligado._niveis[nome] = logger.level
        logger.setLevel(nivel)
    logging.captureWarnings(True)
    if arquivo is not None:
        try:
            ligado._quedas = open(pasta / ARQUIVO_DAS_QUEDAS, "a", encoding="utf-8")  # noqa: SIM115 (aberto até sair)
            faulthandler.enable(ligado._quedas, all_threads=True)
        except OSError:
            ligado._quedas = None
    if qt:
        from PySide6.QtCore import qInstallMessageHandler

        ligado._qt_antes = qInstallMessageHandler(_mensagem_do_qt)
        ligado._qt_ligado = True
    if problema is not None:
        log.warning("o log não pôde ser criado em %s (%s): só no terminal", pasta, problema)
    log.info("%s", descrever_o_ambiente())
    global _ligado
    _ligado = ligado
    return ligado


@functools.cache
def descrever_o_ambiente() -> str:
    """Uma linha com as versões e o sistema: o começo de cada sessão no log e o dos detalhes de um erro. Não muda
    durante o processo (calculada uma vez)."""
    from importlib import metadata

    def versao(pacote: str) -> str:
        try:
            return metadata.version(pacote)
        except metadata.PackageNotFoundError:
            return "?"

    return (f"SH-Analyzer {versao('sh-analyzer')}; Python {platform.python_version()}; PySide6 {versao('PySide6')}; "
            f"pyqtgraph {versao('pyqtgraph')}; NumPy {versao('numpy')}; SciPy {versao('scipy')}; "
            f"{platform.platform()}")


_NIVEIS_DO_QT: dict | None = None
_log_do_qt = logging.getLogger("qt")


def _mensagem_do_qt(tipo, contexto, mensagem: str) -> None:
    global _NIVEIS_DO_QT
    if _NIVEIS_DO_QT is None:
        from PySide6.QtCore import QtMsgType

        _NIVEIS_DO_QT = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
                         QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
                         QtMsgType.QtFatalMsg: logging.CRITICAL}
    categoria = getattr(contexto, "category", "") or ""
    texto = f"{categoria}: {mensagem}" if categoria and categoria != "default" else mensagem
    _log_do_qt.log(_NIVEIS_DO_QT.get(tipo, logging.WARNING), "%s", texto)
