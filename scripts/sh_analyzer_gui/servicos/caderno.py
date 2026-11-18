"""O caderno da sessão do dia (a F4.5): o ``anotacoes.md`` da pasta da sessão (``dados/caderno.py``: o formato, a
leitura e o acréscimo), com as entradas na memória e lidas de novo quando o arquivo muda fora do aplicativo.

**O dia:** o caminho é refeito a cada escrita e a cada minuto. Uma sessão que passa da meia-noite segue no arquivo
do dia novo, como as capturas e as transferências (``preferencias.pasta_da_sessao``).

**O arquivo editado ao mesmo tempo** (o ``lab notas`` aberto no editor): um ``QFileSystemWatcher`` no arquivo e na
pasta (o ``nvim`` grava trocando o arquivo, e o observador perde o de antes) relê as entradas. Do outro lado, o editor
avisa que o arquivo mudou no disco antes de gravar por cima.

**Um erro de disco** não perde a nota: :meth:`CadernoDaSessao.anotar` devolve ``False``, ``erro`` diz o motivo, e a
tela deixa o texto no campo.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from .. import preferencias
from ..dados import caderno as formato
from ..dados.caderno import Entrada

log = logging.getLogger(__name__)

ATRASO_DA_RELEITURA_MS = 150
INTERVALO_DO_DIA_MS = 60_000


class CadernoDaSessao(QObject):
    """``pasta_da_sessao()``: a pasta do dia (os testes passam outra); ``relogio()``: a hora das entradas."""

    mudou = Signal()

    def __init__(self, pasta_da_sessao: Callable[[], Path] = preferencias.pasta_da_sessao, *,
                 relogio: Callable[[], datetime.datetime] = datetime.datetime.now, parent: QObject | None = None):
        super().__init__(parent)
        self.pasta_da_sessao, self.relogio = pasta_da_sessao, relogio
        self.entradas: list[Entrada] = []
        self.erro = ""
        self.caminho = formato.caminho_do_caderno(pasta_da_sessao())
        self._observador = QFileSystemWatcher(self)
        self._observador.fileChanged.connect(self._mudou_fora)
        self._observador.directoryChanged.connect(self._mudou_fora)
        self._releitura = QTimer(self)
        self._releitura.setSingleShot(True)
        self._releitura.setInterval(ATRASO_DA_RELEITURA_MS)
        self._releitura.timeout.connect(self.recarregar)
        self._dia = QTimer(self)
        self._dia.setInterval(INTERVALO_DO_DIA_MS)
        self._dia.timeout.connect(self._conferir_o_dia)
        self._dia.start()
        self.recarregar()

    # ------------------------------------------------------------------ escrever

    def anotar(self, texto: str) -> bool:
        """Uma nota do usuário ("você")."""
        return self._escrever(texto, formato.VOCE)

    def registrar(self, texto: str) -> bool:
        """Uma entrada automática (a captura, a conferência, a transferência, a correção)."""
        return self._escrever(texto, formato.AUTOMATICO)

    def garantir_o_arquivo(self) -> bool:
        """O arquivo do dia existe (criado só com o título, se preciso): para abrir no editor antes da primeira
        entrada."""
        self._seguir_o_dia()
        try:
            formato.criar(self.caminho, self.relogio())
        except OSError as e:
            self.erro = f"O caderno não foi criado em {self.caminho}: {e.strerror or e}"
            log.warning("%s", self.erro)
            self.mudou.emit()
            return False
        self._observar()
        return True

    def _escrever(self, texto: str, autor: str) -> bool:
        if not texto or not texto.strip():
            return False
        self._seguir_o_dia()
        try:
            entrada = formato.acrescentar(self.caminho, texto, autor, self.relogio())
        except OSError as e:
            self.erro = f"O caderno não foi gravado em {self.caminho}: {e.strerror or e}"
            log.warning("%s", self.erro)
            self.mudou.emit()
            return False
        self.erro = ""
        self.entradas.append(entrada)
        self._observar()
        self.mudou.emit()
        return True

    # ------------------------------------------------------------------ ler

    def recarregar(self) -> None:
        """Lê as entradas de novo (o arquivo mudou fora do aplicativo, ou o dia virou)."""
        self._seguir_o_dia()
        try:
            self.entradas = formato.ler(self.caminho)
        except OSError as e:
            log.warning("o caderno %s não foi lido: %s", self.caminho, e)
            self.entradas = []
        self._observar()
        self.mudou.emit()

    def _mudou_fora(self, _caminho: str) -> None:
        self._releitura.start()

    def _conferir_o_dia(self) -> None:
        if formato.caminho_do_caderno(self.pasta_da_sessao()) != self.caminho:
            self.recarregar()

    def _seguir_o_dia(self) -> None:
        self.caminho = formato.caminho_do_caderno(self.pasta_da_sessao())

    def _observar(self) -> None:
        """O arquivo e a pasta dele, os que existem (o observador larga um arquivo trocado por outro)."""
        desejados = [str(p) for p in (self.caminho, self.caminho.parent) if p.exists()]
        atuais = self._observador.files() + self._observador.directories()
        fora = [p for p in atuais if p not in desejados]
        if fora:
            self._observador.removePaths(fora)
        novos = [p for p in desejados if p not in atuais]
        if novos:
            self._observador.addPaths(novos)
