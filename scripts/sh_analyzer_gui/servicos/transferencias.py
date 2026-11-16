"""As capturas da placa para o computador (docs/gui-plan.md, 11.7; a F3.7): a fila de transferências da placa
conectada, o progresso (a vazão e o tempo que falta), a conferência de cada cópia e o "apagar da placa", só para o
que foi conferido. O trabalho é do ``sh_placa/sftp.py``, no laço da placa; aqui ficam a fila e o estado, na thread
da interface.

**Um arquivo por vez** (os blocos de cada um vão em paralelo): a placa tem um núcleo só e um cartão, e dois arquivos
juntos não passariam mais rápido. **Com uma captura rodando, a fila espera** (o item diz "esperando a captura
terminar"): a medição tem prioridade (ver ``sh_placa/sftp.py``).

**A queda do cabo** interrompe o item (a parte baixada fica); quando a mesma placa volta, a fila continua sozinha,
do ponto em que parou. Outra placa conectada não herda a fila.

**Para onde:** a pasta da sessão do dia (``preferencias.pasta_da_sessao``, a mesma do ``lab trazer``), com as
subpastas da placa (as coletas). **O que já veio** fica num índice (``copias.json``, na pasta da placa), pelo nº de
série, o caminho, o tamanho e a data: uma captura já conferida aparece "no computador" na próxima sessão.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QObject, Signal
from sh_placa.erros import ErroDeConexao
from sh_placa.estado import CapturaNaPlaca
from sh_placa.sftp import (
    CopiaLocal,
    IndiceDeCopias,
    OrigemSSH,
    apagar,
    baixar,
    conferir,
    esperar_sem_captura,
)
from shiboken6 import isValid

from .. import preferencias
from .conexao_da_placa import ConexaoDaPlaca
from .placa import Chamada
from .saude_da_placa import SaudeDaPlaca

log = logging.getLogger(__name__)

ESTADOS = ("na_fila", "esperando_a_captura", "baixando", "conferindo", "conferida", "corrompida", "interrompida",
           "falhou", "cancelada")
ATIVOS = ("esperando_a_captura", "baixando", "conferindo")
INTERVALO_DO_PROGRESSO_S = 0.1
JANELA_DA_VAZAO_S = 3.0


@dataclass
class ItemDaFila:
    """Uma captura na fila: de onde (``remoto``, na placa), para onde (``local``), o estado e o progresso."""

    captura: CapturaNaPlaca
    remoto: str
    local: Path
    serie: str | None
    estado: str = "na_fila"
    transferidos: int = 0
    erro: str = ""
    como: str = ""                         # a conferência: "crc32" ou "sha256"
    _amostras: list[tuple[float, int]] = field(default_factory=list, repr=False)

    @property
    def total(self) -> int:
        return self.captura.bytes

    @property
    def fracao(self) -> float:
        return self.transferidos / self.total if self.total else 1.0

    @property
    def vazao_bytes_s(self) -> float | None:
        """A vazão dos últimos segundos (``None`` antes de haver o que medir)."""
        if len(self._amostras) < 2:
            return None
        (t0, b0), (t1, b1) = self._amostras[0], self._amostras[-1]
        return (b1 - b0) / (t1 - t0) if t1 > t0 else None

    @property
    def restante_s(self) -> float | None:
        vazao = self.vazao_bytes_s
        return (self.total - self.transferidos) / vazao if vazao else None

    def _medir(self, transferidos: int) -> None:
        agora = time.monotonic()
        self.transferidos = transferidos
        self._amostras.append((agora, transferidos))
        while self._amostras and agora - self._amostras[0][0] > JANELA_DA_VAZAO_S:
            self._amostras.pop(0)


class TransferenciasDaPlaca(QObject):
    """A fila. ``mudou`` sai quando um item entra, sai ou muda de estado (e quando o que está no computador muda);
    ``progrediu(item)``, a cada ~0,1 s de um item baixando."""

    mudou = Signal()
    progrediu = Signal(object)
    _noLaco = Signal(object, str, int)          # do laço: (item, estado ou "", transferidos)

    def __init__(self, conexao: ConexaoDaPlaca, saude: SaudeDaPlaca, *, indice: Path | None = None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self.conexao, self.saude, self.servico = conexao, saude, conexao.servico
        self.indice = IndiceDeCopias(indice if indice is not None else preferencias.pasta_da_placa() / "copias.json")
        self.itens: list[ItemDaFila] = []
        self.destino: Path | None = None       # None: a pasta da sessão do dia
        self._chamada: Chamada | None = None
        self._item: ItemDaFila | None = None
        self._serie: str | None = None
        self._noLaco.connect(self._do_laco)
        conexao.mudou.connect(self._conexao_mudou)

    # ------------------------------------------------------------------ o que a interface lê

    @property
    def pasta_de_destino(self) -> Path:
        return self.destino if self.destino is not None else preferencias.pasta_da_sessao()

    def remoto(self, captura: CapturaNaPlaca) -> str:
        pasta = self.saude.capturas.pasta if self.saude.capturas is not None else ""
        return str(PurePosixPath(pasta) / captura.arquivo)

    def _chave(self, captura: CapturaNaPlaca) -> str:
        serie = self.saude.saude.serie if self.saude.saude is not None else None
        return self.indice.chave(serie, captura.arquivo, captura.bytes, captura.modificado)

    def copia(self, captura: CapturaNaPlaca):
        """A cópia desta captura no computador (``CopiaLocal``), se houver uma (com o mesmo tamanho)."""
        return self.indice.copia(self._chave(captura), captura.bytes)

    def item_de(self, captura: CapturaNaPlaca) -> ItemDaFila | None:
        return next((i for i in reversed(self.itens) if i.captura.arquivo == captura.arquivo
                     and i.captura.bytes == captura.bytes), None)

    def conferida(self, captura: CapturaNaPlaca) -> bool:
        copia = self.copia(captura)
        return copia is not None and copia.conferida is True

    @property
    def ativo(self) -> ItemDaFila | None:
        return self._item

    # ------------------------------------------------------------------ a fila

    def transferir(self, capturas) -> int:
        """Põe na fila as capturas que ainda não estão no computador (conferidas) nem na fila; devolve quantas."""
        novas = 0
        serie = self.saude.saude.serie if self.saude.saude is not None else None
        for captura in capturas:
            item = self.item_de(captura)
            if self.conferida(captura) or (item is not None and item.estado in ("na_fila", *ATIVOS)):
                continue
            if item is not None:
                self.itens.remove(item)
            self.itens.append(ItemDaFila(captura, self.remoto(captura), self.pasta_de_destino / captura.arquivo,
                                         serie))
            novas += 1
        if novas:
            self.mudou.emit()
            self._proxima()
        return novas

    def cancelar(self, item: ItemDaFila) -> None:
        """Para o item (a parte baixada fica, para retomar se ele voltar à fila)."""
        if item is self._item and self._chamada is not None:
            self._chamada.cancelar()
        elif item.estado in ("na_fila", "interrompida"):
            item.estado = "cancelada"
            self.mudou.emit()

    def tentar_de_novo(self, item: ItemDaFila) -> None:
        if item.estado in ("interrompida", "falhou", "cancelada", "corrompida"):
            item.estado, item.erro = "na_fila", ""
            self.mudou.emit()
            self._proxima()

    def remover(self, item: ItemDaFila) -> None:
        """Tira da lista um item que terminou (ou que não vai mais)."""
        if item in self.itens and item.estado not in ATIVOS:
            self.itens.remove(item)
            self.mudou.emit()

    def limpar_terminados(self) -> None:
        antes = len(self.itens)
        self.itens = [i for i in self.itens if i.estado not in ("conferida", "cancelada")]
        if len(self.itens) != antes:
            self.mudou.emit()

    def _origem(self):
        return OrigemSSH(self.conexao.conexao_ssh)

    def _proxima(self) -> None:
        if self._item is not None or self.conexao.estado != "conectada" or self.conexao.cliente is None:
            return
        item = next((i for i in self.itens if i.estado == "na_fila"), None)
        if item is None:
            return
        self._item = item
        item.estado, item.erro = "baixando", ""          # o baixar confere a captura antes (e avisa se esperar)
        item._amostras.clear()
        self.mudou.emit()
        self._chamada = self.servico.chamar(f"transferir {item.captura.arquivo}", self._no_laco, item, self._origem(),
                                            ao_terminar=self._terminou)

    async def _no_laco(self, item: ItemDaFila, origem):
        """Na thread do laço: espera a captura (se houver), baixa e confere. O progresso e as mudanças de estado vão
        para a interface pelo sinal (no máximo a cada ~0,1 s)."""
        ultimo = [0.0]

        def avisar(estado: str = "", transferidos: int = -1) -> None:
            if isValid(self):
                try:
                    self._noLaco.emit(item, estado, transferidos)
                except RuntimeError:
                    pass

        def progredir(transferidos: int, total: int) -> None:
            agora = time.monotonic()
            if agora - ultimo[0] >= INTERVALO_DO_PROGRESSO_S or transferidos == total:
                ultimo[0] = agora
                avisar("baixando", transferidos)

        async def esperar() -> None:
            await esperar_sem_captura(origem, lambda esperando: avisar("esperando_a_captura" if esperando
                                                                       else "baixando"))

        await baixar(origem, item.remoto, item.local, ao_progredir=progredir, esperar_a_captura=esperar)
        avisar("conferindo", item.total)
        return await conferir(origem, item.remoto, item.local)

    def _do_laco(self, item: ItemDaFila, estado: str, transferidos: int) -> None:
        if item is not self._item:
            return
        if transferidos >= 0:
            item._medir(transferidos)
        if estado and estado != item.estado:
            item.estado = estado
            self.mudou.emit()
        self.progrediu.emit(item)

    def _terminou(self, chamada: Chamada) -> None:
        if chamada is not self._chamada:
            return
        item, self._item, self._chamada = self._item, None, None
        if chamada.estado == "concluida":
            conferencia = chamada.resultado
            item.estado = "conferida" if conferencia.ok else "corrompida"
            item.como, item.erro = conferencia.como, "" if conferencia.ok else conferencia.detalhe
            item.transferidos = item.total
            chave = self.indice.chave(item.serie, item.captura.arquivo, item.captura.bytes, item.captura.modificado)
            self.indice.lembrar(chave, CopiaLocal(str(item.local), conferencia.ok, conferencia.como, time.time()))
        elif chamada.estado == "cancelada":
            item.estado = "cancelada" if self.conexao.estado == "conectada" else "interrompida"
        elif isinstance(chamada.excecao, ErroDeConexao):
            item.estado, item.erro = "interrompida", chamada.erro
        else:
            item.estado, item.erro = "falhou", chamada.erro
        self.mudou.emit()
        self._proxima()

    # ------------------------------------------------------------------ a conexão

    def _conexao_mudou(self) -> None:
        c = self.conexao
        if c.estado != "conectada":
            if self._chamada is not None and c.estado in ("desconectada", "falhou", "bloqueada"):
                self._chamada.cancelar()             # o item fica "interrompida" (ver _terminou)
            return
        serie = c.estado_da_placa.serie if c.estado_da_placa is not None else None
        if serie != self._serie:
            if self._serie is not None and self.itens:
                self.itens = []                       # outra placa: a fila era da outra
                self.mudou.emit()
            self._serie = serie
        for item in self.itens:                       # a mesma placa voltou: o que a queda parou continua
            if item.estado == "interrompida":
                item.estado = "na_fila"
        self._proxima()

    # ------------------------------------------------------------------ apagar da placa

    def apagar_da_placa(self, capturas) -> Chamada | None:
        """Apaga da placa as capturas já conferidas no computador (as outras ficam, sempre); depois, as capturas são
        lidas de novo. Quem chama já confirmou com o usuário."""
        conferidas = [c for c in capturas if self.conferida(c)]
        if not conferidas or self.conexao.cliente is None:
            return None
        remotos = [self.remoto(c) for c in conferidas]
        return self.servico.chamar("apagar da placa", self._apagar_no_laco, self._origem(), remotos,
                                   ao_terminar=self._apagou)

    def _apagou(self, _chamada: Chamada) -> None:
        """As capturas da placa, lidas de novo (e a lista, que perdeu as apagadas)."""
        self.saude.conferir()
        self.mudou.emit()

    @staticmethod
    async def _apagar_no_laco(origem, remotos: list[str]) -> int:
        for remoto in remotos:
            await apagar(origem, remoto)
        return len(remotos)
