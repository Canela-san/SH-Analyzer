"""Os logs e o monitor da placa conectada (docs/gui-plan.md, 11.10; a F6.6). A conexão é do
``servicos/conexao_da_placa.py``; este serviço lê o que a página Logs e o monitor da página Sistema mostram, no laço da
placa (``servicos/placa.py``), mudando o estado só na thread da interface.

**Os logs** (:meth:`MonitorDaPlaca.ler_logs`): o comando ``logs`` do agente, o kernel e o diário do systemd deste
boot: "o que importa" (a PRU, os pinos, o firmware, o USB, o cartão e os erros: o filtro do agente) ou tudo (as
últimas :data:`LINHAS_DE_TUDO` de cada um). **Ao vivo** (:meth:`ligar_ao_vivo`): o ``seguir_logs`` do agente, um
``journalctl -f`` só, cada linha nova em ``linhaAoVivo`` (sem o "tudo", só as que importam, pelo mesmo filtro).

**O monitor** (:meth:`ligar_monitor`): o ``monitor`` do agente, um processo só na placa, uma amostra por
:data:`INTERVALO_DO_MONITOR_S` (o processador, a memória, a temperatura, a carga), as últimas
:data:`AMOSTRAS_GUARDADAS` em :attr:`amostras`; e, a cada :data:`INTERVALO_DOS_PROCESSOS_MS`, os processos que mais
pesam e os ``ler_adc`` que rodam (o ``pgrep``: uma captura que esta janela não começou pode ser parada pela ação
``parar_ler_adc`` do ``servicos/sistema_da_placa.py``).

**Quem liga desliga:** as páginas ligam o ao vivo e o monitor quando aparecem e desligam quando somem (cada um custa
um pouco do núcleo único da placa). A queda (o cabo) para os dois; a conexão que volta os liga de novo, se a página
ainda os quer.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal
from shiboken6 import isValid

from .conexao_da_placa import ConexaoDaPlaca
from .placa import Chamada

if TYPE_CHECKING:
    from sh_placa.estado import LogsDaPlaca
    from sh_placa.sistema import CapturaNaPlaca

log = logging.getLogger(__name__)

LINHAS_QUE_IMPORTAM = 200
LINHAS_DE_TUDO = 1000
INTERVALO_DO_MONITOR_S = 1.0
AMOSTRAS_GUARDADAS = 300                  # 5 min, a 1 s
INTERVALO_DOS_PROCESSOS_MS = 5000
PROCESSOS_MOSTRADOS = 8


class MonitorDaPlaca(QObject):
    logsMudaram = Signal()                    # a leitura terminou (ou começou, ou falhou)
    linhaAoVivo = Signal(object)              # uma LinhaDeLog nova do ao vivo
    aoVivoMudou = Signal()
    amostraNova = Signal(object)              # o dict da amostra (com o "t" desta máquina em "recebida")
    monitorMudou = Signal()
    processosMudaram = Signal()
    _doLaco = Signal(str, object)

    def __init__(self, conexao: ConexaoDaPlaca, parent: QObject | None = None):
        super().__init__(parent)
        self.conexao, self.servico = conexao, conexao.servico
        self.logs: LogsDaPlaca | None = None
        self.termos: tuple[str, ...] = ()
        self.todos = False
        self.lendo_logs = False
        self.erro_dos_logs = ""
        self.ao_vivo_pedido = False
        self.erro_do_ao_vivo = ""
        self.monitor_pedido = False
        self.erro_do_monitor = ""
        self.amostras: deque[dict] = deque(maxlen=AMOSTRAS_GUARDADAS)
        self.processos: dict | None = None
        self.capturas: list[CapturaNaPlaca] = []
        self._sessao = 0
        self._chamadas: set[Chamada] = set()
        self._ao_vivo: Chamada | None = None
        self._monitor: Chamada | None = None
        self._lendo_processos: Chamada | None = None
        self._relogio_dos_processos = QTimer(self)
        self._relogio_dos_processos.setInterval(INTERVALO_DOS_PROCESSOS_MS)
        self._relogio_dos_processos.timeout.connect(self.ler_processos)
        self._doLaco.connect(self._do_laco)
        conexao.mudou.connect(self._conexao_mudou)

    # ------------------------------------------------------------------ a conexão

    def _conexao_mudou(self) -> None:
        c = self.conexao
        if c.estado == "conectada":
            if c.sessoes != self._sessao:
                self._sessao = c.sessoes
                self.logs, self.processos, self.capturas = None, None, []
                self.amostras.clear()
                self.erro_dos_logs = self.erro_do_ao_vivo = self.erro_do_monitor = ""
                self.logsMudaram.emit()
                self.monitorMudou.emit()
                self.processosMudaram.emit()
            self._retomar()
        elif c.estado in ("desconectada", "falhou", "bloqueada", "desligando"):
            for chamada in list(self._chamadas):
                chamada.cancelar()
            self._chamadas.clear()
            self._ao_vivo = self._monitor = self._lendo_processos = None
            self._relogio_dos_processos.stop()
            self.lendo_logs = False
            if c.estado != "desligando":
                self._sessao = 0
            self.aoVivoMudou.emit()
            self.monitorMudou.emit()

    def _retomar(self) -> None:
        """Liga de novo o que a página quer e não está rodando (depois de uma queda, ou ao conectar)."""
        if self.ao_vivo_pedido and self._ao_vivo is None:
            self._comecar_ao_vivo()
        if self.monitor_pedido and self._monitor is None:
            self._comecar_monitor()

    def _chamar(self, nome: str, funcao, *args, ao_terminar) -> Chamada:
        chamada = self.servico.chamar(nome, funcao, *args, ao_terminar=lambda ch: self._terminou(ch, ao_terminar))
        self._chamadas.add(chamada)
        return chamada

    def _terminou(self, chamada: Chamada, ao_terminar) -> None:
        if not isValid(self) or chamada not in self._chamadas:
            return
        self._chamadas.discard(chamada)
        ao_terminar(chamada)

    def _emitir_do_laco(self, o_que: str, valor) -> None:
        if isValid(self):
            try:
                self._doLaco.emit(o_que, valor)
            except RuntimeError:
                pass

    def _do_laco(self, o_que: str, valor) -> None:
        from sh_placa.estado import LinhaDeLog

        if o_que == "log" and self._ao_vivo is not None:
            linha = LinhaDeLog.de_json(valor)
            if self.todos or linha.relevante(self.termos):
                self.linhaAoVivo.emit(linha)
        elif o_que == "amostra" and self._monitor is not None:
            valor["recebida"] = time.monotonic()
            self.amostras.append(valor)
            self.amostraNova.emit(valor)

    # ------------------------------------------------------------------ os logs

    def ler_logs(self, todos: bool | None = None) -> Chamada | None:
        """O kernel e o diário: o que importa, ou tudo (``todos``; ``None``: o de antes)."""
        cliente = self.conexao.cliente
        if todos is not None:
            self.todos = todos
        if cliente is None or self.conexao.estado != "conectada":
            return None
        self.lendo_logs, self.erro_dos_logs = True, ""
        self.logsMudaram.emit()
        quantas = LINHAS_DE_TUDO if self.todos else LINHAS_QUE_IMPORTAM
        return self._chamar("ler os logs da placa", self._logs_no_laco, cliente, quantas, self.todos,
                            ao_terminar=self._leu_logs)

    @staticmethod
    async def _logs_no_laco(cliente, quantas: int, todos: bool):
        resposta = await cliente.chamar("logs", str(quantas), *(["--todos"] if todos else []))
        from sh_placa.estado import LogsDaPlaca

        return LogsDaPlaca.de_json(resposta), tuple(resposta.get("termos") or ())

    def _leu_logs(self, chamada: Chamada) -> None:
        self.lendo_logs = False
        if chamada.estado == "concluida":
            self.logs, termos = chamada.resultado
            self.termos = termos or self.termos
        elif chamada.estado == "falhou":
            self.erro_dos_logs = chamada.erro
        self.logsMudaram.emit()

    def ligar_ao_vivo(self, ligar: bool) -> None:
        self.ao_vivo_pedido = ligar
        if ligar and self._ao_vivo is None:
            self._comecar_ao_vivo()
        elif not ligar and self._ao_vivo is not None:
            chamada, self._ao_vivo = self._ao_vivo, None
            chamada.cancelar()
            self.aoVivoMudou.emit()

    @property
    def ao_vivo(self) -> bool:
        return self._ao_vivo is not None

    def _comecar_ao_vivo(self) -> None:
        cliente = self.conexao.cliente
        if cliente is None or self.conexao.estado != "conectada":
            return
        self.erro_do_ao_vivo = ""
        self._ao_vivo = self._chamar("os logs da placa ao vivo", self._seguir_no_laco, cliente, "seguir_logs",
                                     "log", ao_terminar=self._ao_vivo_parou)
        self.aoVivoMudou.emit()

    async def _seguir_no_laco(self, cliente, comando: str, o_que: str, *args: str) -> None:
        await cliente.seguir(comando, *args, ao_receber=lambda dados: self._emitir_do_laco(o_que, dados))

    def _ao_vivo_parou(self, chamada: Chamada) -> None:
        if chamada is not self._ao_vivo:
            return
        self._ao_vivo = None
        if chamada.estado == "falhou" and self.conexao.estado == "conectada":
            self.erro_do_ao_vivo = chamada.erro          # o agente recusou (sem o journalctl), por exemplo
            self.ao_vivo_pedido = False
        self.aoVivoMudou.emit()                         # na queda, a conexão que volta liga de novo

    # ------------------------------------------------------------------ o monitor

    def ligar_monitor(self, ligar: bool) -> None:
        self.monitor_pedido = ligar
        if ligar and self._monitor is None:
            self._comecar_monitor()
        elif not ligar:
            self._relogio_dos_processos.stop()
            if self._monitor is not None:
                chamada, self._monitor = self._monitor, None
                chamada.cancelar()
            self.monitorMudou.emit()

    @property
    def monitorando(self) -> bool:
        return self._monitor is not None

    def _comecar_monitor(self) -> None:
        cliente = self.conexao.cliente
        if cliente is None or self.conexao.estado != "conectada":
            return
        self.erro_do_monitor = ""
        self._monitor = self._chamar("o monitor da placa", self._seguir_no_laco, cliente, "monitor", "amostra",
                                     f"{INTERVALO_DO_MONITOR_S:g}", "0", ao_terminar=self._monitor_parou)
        self._relogio_dos_processos.start()
        self.ler_processos()
        self.monitorMudou.emit()

    def _monitor_parou(self, chamada: Chamada) -> None:
        if chamada is not self._monitor:
            return
        self._monitor = None
        self._relogio_dos_processos.stop()
        if chamada.estado == "falhou" and self.conexao.estado == "conectada":
            self.erro_do_monitor = chamada.erro
            self.monitor_pedido = False
        self.monitorMudou.emit()

    def ler_processos(self) -> Chamada | None:
        """Os processos que mais pesam e os ``ler_adc`` que rodam (um de cada vez: o anterior tem de ter voltado)."""
        cliente, conexao_ssh = self.conexao.cliente, self.conexao.conexao_ssh
        if cliente is None or conexao_ssh is None or self._lendo_processos is not None \
                or self.conexao.estado != "conectada":
            return None
        self._lendo_processos = self._chamar("os processos da placa", self._processos_no_laco, cliente, conexao_ssh,
                                             ao_terminar=self._leu_processos)
        return self._lendo_processos

    @staticmethod
    async def _processos_no_laco(cliente, conexao_ssh):
        from sh_placa.sistema import capturas_rodando

        processos = await cliente.chamar("processos", str(PROCESSOS_MOSTRADOS))
        return processos, await capturas_rodando(conexao_ssh)

    def _leu_processos(self, chamada: Chamada) -> None:
        self._lendo_processos = None
        if chamada.estado == "concluida":
            self.processos, self.capturas = chamada.resultado
            self.processosMudaram.emit()
