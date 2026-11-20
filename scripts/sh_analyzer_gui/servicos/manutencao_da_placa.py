"""A manutenção da placa conectada (docs/gui-plan.md, 11.10; a Fase 6): o firmware (a F6.3). A conexão é do
``servicos/conexao_da_placa.py`` e a saúde, do ``servicos/saude_da_placa.py``; este serviço lê o que a seção
Manutenção mostra e roda o que ela pede, sempre no laço da placa (``servicos/placa.py``), mudando o estado só na
thread da interface.

**O firmware** (:meth:`ManutencaoDaPlaca.ler`): o deste aplicativo (``sh_placa/atualizacao.py``: o do repositório ou
o do instalador), o plano (o que muda, pelo hash), as cópias anteriores na placa e a atualização que estiver rodando
nela (de uma conexão anterior, ou de antes de o aplicativo abrir: ela é acompanhada de novo).

**A atualização** (:meth:`atualizar`, :attr:`atualizacao`): envia o que muda, lança a tarefa destacada e a acompanha
(``passo`` e ``log`` ao vivo). **A senha do sudo** segue a das correções: a da sessão, senão a da placa (a digitada
para conectar), senão a do cofre; sem nenhuma, ``precisa_da_senha``, e a recusada é ``senha_recusada`` (a tarefa nem
começa). **A queda** (o cabo com mau contato) não para a tarefa: quando a conexão volta, o acompanhamento recomeça
desde o começo dela. No fim: o desfecho (``sh_placa.atualizacao.desfecho``), a saúde conferida de novo, o plano lido
de novo e a pasta da tarefa apagada na placa (o log fica aqui, em :attr:`EstadoDaAtualizacao.log`).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal
from sh_placa.agente import ErroDaPlaca
from shiboken6 import isValid

from .conexao_da_placa import ConexaoDaPlaca
from .placa import Chamada
from .saude_da_placa import SaudeDaPlaca

if TYPE_CHECKING:
    from sh_placa.atualizacao import CopiaAnterior, Desfecho, FirmwareParaEnviar, PlanoDeAtualizacao
    from sh_placa.tarefas import EstadoDaTarefa

log = logging.getLogger(__name__)

ESTADOS_DA_ATUALIZACAO = ("enviando", "rodando", "reconectando", "precisa_da_senha", "senha_recusada", "nao_comecou",
                          "terminou")
LINHAS_DO_LOG = 4000


@dataclass
class EstadoDaAtualizacao:
    """A atualização de agora (ou a última): o estado (:data:`ESTADOS_DA_ATUALIZACAO`), o título, a versão que vai, o
    envio (``enviados`` de ``a_enviar`` arquivos), a tarefa na placa (os passos), o log e, no fim, o desfecho."""

    estado: str
    titulo: str
    versao: str
    origem: str = "aplicativo"
    enviados: int = 0
    a_enviar: int = 0
    tarefa: EstadoDaTarefa | None = None
    log: list[str] = field(default_factory=list)
    desfecho: Desfecho | None = None
    mensagem: str = ""                       # o porquê de não ter começado (a senha, a placa)
    de_antes: bool = False                   # achada já terminada ao conectar (ninguém viu o fim dela)

    @property
    def rodando(self) -> bool:
        return self.estado in ("enviando", "rodando", "reconectando")


class ManutencaoDaPlaca(QObject):
    mudou = Signal()                          # o firmware, o plano ou as cópias
    atualizacaoMudou = Signal()               # o estado, um passo novo, o envio
    logDaAtualizacao = Signal(str)            # um pedaço novo do log da tarefa
    atualizacaoTerminou = Signal(object)      # o EstadoDaAtualizacao no fim (o caderno)
    _doLaco = Signal(object, object)          # do laço para a interface: (o que, o valor)

    def __init__(self, conexao: ConexaoDaPlaca, saude: SaudeDaPlaca, parent: QObject | None = None):
        super().__init__(parent)
        self.conexao, self.saude, self.servico = conexao, saude, conexao.servico
        self.firmware: FirmwareParaEnviar | None = None
        self.plano: PlanoDeAtualizacao | None = None
        self.copias: list[CopiaAnterior] = []
        self.lendo = False
        self.erro = ""
        self.atualizacao: EstadoDaAtualizacao | None = None
        self._sessao = 0
        self._chamadas: set[Chamada] = set()
        self._acompanhando: Chamada | None = None
        self._id_da_tarefa: str | None = None
        self._doLaco.connect(self._do_laco)
        conexao.mudou.connect(self._conexao_mudou)

    # ------------------------------------------------------------------ a conexão

    def _conexao_mudou(self) -> None:
        c = self.conexao
        if c.estado == "conectada" and c.sessoes != self._sessao:
            self._sessao = c.sessoes
            self.plano, self.copias, self.erro = None, [], ""
            if self.atualizacao is not None and not self.atualizacao.rodando:
                self.atualizacao = None
            self.mudou.emit()
            self._procurar_tarefas()
        elif c.estado == "conectada" and self.atualizacao is not None and self.atualizacao.estado == "reconectando":
            self._acompanhar()                       # a queda: a mesma conexão voltou
        elif c.estado == "reconectando" and self.atualizacao is not None and self.atualizacao.rodando:
            self.atualizacao.estado = "reconectando"
            self.atualizacaoMudou.emit()
        elif c.estado in ("desconectada", "falhou", "bloqueada"):
            for chamada in list(self._chamadas):
                chamada.cancelar()
            self._chamadas.clear()
            self._sessao = 0
            self.plano, self.copias, self.lendo = None, [], False
            if self.atualizacao is not None and self.atualizacao.rodando:
                self.atualizacao.estado = "reconectando"     # a tarefa segue na placa: a próxima conexão a acha
                self.atualizacaoMudou.emit()
            self.mudou.emit()

    def _chamar(self, nome: str, funcao, *args, ao_terminar) -> Chamada:
        chamada = self.servico.chamar(nome, funcao, *args, ao_terminar=lambda ch: self._terminou(ch, ao_terminar))
        self._chamadas.add(chamada)
        return chamada

    def _terminou(self, chamada: Chamada, ao_terminar) -> None:
        if chamada not in self._chamadas:
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
        a = self.atualizacao
        if a is None:
            return
        if o_que == "enviado":
            a.enviados, a.a_enviar = valor
            self.atualizacaoMudou.emit()
        elif o_que == "passo":
            a.tarefa, a.estado = valor, "rodando"
            self.atualizacaoMudou.emit()
        elif o_que == "log":
            a.log.append(valor)
            if len(a.log) > LINHAS_DO_LOG:
                del a.log[:len(a.log) - LINHAS_DO_LOG]
            self.logDaAtualizacao.emit(valor)

    # ------------------------------------------------------------------ ler

    def _procurar_tarefas(self) -> None:
        """Ao conectar, só as atualizações na placa (um comando leve): a que roda é acompanhada. O resto (o git, o
        plano) é lido quando a seção aparece (:meth:`ler_se_preciso`)."""
        conexao_ssh = self.conexao.conexao_ssh
        if conexao_ssh is None:
            return
        self._chamar("procurar as atualizações na placa", self._tarefas_no_laco, conexao_ssh,
                     ao_terminar=lambda ch: self._retomar(ch.resultado) if ch.estado == "concluida" else None)

    @staticmethod
    async def _tarefas_no_laco(conexao_ssh):
        from sh_placa.atualizacao import TIPO
        from sh_placa.tarefas import tarefas_na_placa

        return await tarefas_na_placa(conexao_ssh, TIPO)

    def ler_se_preciso(self) -> None:
        """A seção apareceu: lê o firmware, se ainda não leu nesta conexão."""
        if self.plano is None and not self.lendo and self.conexao.estado == "conectada":
            self.ler()

    def ler(self) -> Chamada | None:
        """O firmware deste aplicativo (lido de novo a cada vez: a árvore pode ter mudado com o aplicativo aberto), o
        plano, as cópias anteriores e a atualização que roda na placa."""
        cliente, conexao_ssh = self.conexao.cliente, self.conexao.conexao_ssh
        if cliente is None or conexao_ssh is None or self.lendo:
            return None
        self.lendo, self.erro = True, ""
        self.mudou.emit()
        return self._chamar("ler o firmware da placa", self._ler_no_laco, cliente, conexao_ssh, ao_terminar=self._leu)

    @staticmethod
    async def _ler_no_laco(cliente, conexao_ssh):
        from sh_placa import atualizacao
        from sh_placa.tarefas import tarefas_na_placa

        firmware = await asyncio.to_thread(atualizacao.firmware_do_aplicativo)
        plano = await atualizacao.planejar(cliente, firmware) if firmware is not None else None
        copias = await atualizacao.copias_anteriores(cliente)
        tarefas = await tarefas_na_placa(conexao_ssh, atualizacao.TIPO)
        return firmware, plano, copias, tarefas

    def _leu(self, chamada: Chamada) -> None:
        self.lendo = False
        if chamada.estado == "concluida":
            self.firmware, self.plano, self.copias, tarefas = chamada.resultado
            self._retomar(tarefas)
        elif chamada.estado == "falhou":
            self.erro = chamada.erro
        self.mudou.emit()

    def _retomar(self, tarefas: list) -> None:
        """A atualização desta sessão que caiu, ou uma que roda na placa (de antes de o aplicativo abrir), é
        acompanhada de novo; uma que terminou e ninguém viu mostra o desfecho e é limpa."""
        if self._acompanhando is not None:
            return
        alvo = next((t for t in tarefas if t.id == self._id_da_tarefa), None) if self._id_da_tarefa else None
        if alvo is None and (self.atualizacao is None or not self.atualizacao.rodando):
            alvo = tarefas[-1] if tarefas else None
        if alvo is None:
            if self.atualizacao is not None and self.atualizacao.estado == "reconectando":
                self.atualizacao.estado = "terminou"
                self.atualizacao.mensagem = "a tarefa da atualização não está mais na placa (ela foi reinstalada?)"
                self.atualizacaoMudou.emit()
            return
        if self.atualizacao is None or not self.atualizacao.rodando:
            origem = ("placa" if alvo.titulo.startswith("Compilar") else "anterior" if alvo.titulo.startswith("Voltar")
                      else "aplicativo")
            self.atualizacao = EstadoDaAtualizacao("rodando", alvo.titulo, alvo.resultado.get("versao", ""), origem,
                                                   tarefa=alvo, de_antes=alvo.terminou or alvo.interrompida)
        self._id_da_tarefa = alvo.id
        self.atualizacaoMudou.emit()
        self._acompanhar()

    # ------------------------------------------------------------------ atualizar

    def atualizar(self, origem: str | CopiaAnterior = "aplicativo", senha: str | None = None,
                  guardar: bool = False) -> None:
        """Atualiza a placa com o firmware deste aplicativo (``"aplicativo"``), compila e carrega de novo o dela
        (``"placa"``) ou volta a uma cópia anterior (uma :class:`~sh_placa.atualizacao.CopiaAnterior`). A interface já
        confirmou. Sem ``senha``: a da sessão, a da placa ou a do cofre."""
        from sh_placa import atualizacao as at

        conexao_ssh, cliente = self.conexao.conexao_ssh, self.conexao.cliente
        if conexao_ssh is None or cliente is None or (self.atualizacao is not None and self.atualizacao.rodando):
            return
        if origem == "aplicativo":
            if self.firmware is None or self.plano is None:
                return
            firmware, titulo = self.firmware, f"Atualizar o firmware para {self.firmware.versao}"
        elif origem == "placa":
            if self.plano is None:
                return
            firmware = at.firmware_da_placa(self.plano.codigo_da_placa, self.plano.versao_da_placa)
            titulo = "Compilar e carregar de novo o firmware da placa"
        else:
            firmware = at.firmware_da_copia(origem, at.subpastas_do_firmware(self.firmware))
            titulo = f"Voltar o firmware a {firmware.versao}"
        senha = senha or self.saude.senha_do_sudo or self.conexao.senha_da_placa()
        rotulo = origem if isinstance(origem, str) else "anterior"
        self.atualizacao = EstadoDaAtualizacao("enviando", titulo, firmware.versao, rotulo)
        self.atualizacaoMudou.emit()
        self._chamar("atualizar o firmware", self._atualizar_no_laco, conexao_ssh, cliente, firmware, senha, guardar,
                     self.conexao.cofre, ao_terminar=self._lancou)

    async def _atualizar_no_laco(self, conexao_ssh, cliente, firmware, senha, guardar, obter_o_cofre):
        from sh_placa import atualizacao as at

        cofre = obter_o_cofre()
        conta = conexao_ssh.destino.conta
        if senha is None:
            senha = await asyncio.to_thread(cofre.senha, conta)
            if senha is None:
                return None
        plano = await at.planejar(cliente, firmware)
        tarefa = await at.atualizar(conexao_ssh, plano, senha,
                                    ao_enviar=lambda i, n: self._emitir_do_laco("enviado", (i, n)))
        aviso = ""
        if guardar:
            try:
                await asyncio.to_thread(cofre.guardar, conta, senha)
            except ErroDaPlaca as e:
                aviso = str(e)
        return tarefa.id, senha, aviso, plano

    def _lancou(self, chamada: Chamada) -> None:
        from sh_placa.correcoes import ErroDoSudo

        a = self.atualizacao
        if a is None:
            return
        if chamada.estado == "concluida":
            if chamada.resultado is None:
                a.estado = "precisa_da_senha"
                a.mensagem = ("A placa pede a senha do sudo (a do usuário dela): esta sessão e o cofre do sistema não "
                              "a têm.")
                self.atualizacaoMudou.emit()
                return
            self._id_da_tarefa, senha, aviso, plano = chamada.resultado
            self.saude.lembrar_senha_do_sudo(senha)
            a.estado, a.mensagem = "rodando", aviso
            a.a_enviar = a.enviados = len(plano.novos) + len(plano.mudados)
            self.atualizacaoMudou.emit()
            self._acompanhar()
            return
        if chamada.estado == "falhou":
            e = chamada.excecao
            if isinstance(e, ErroDoSudo) and e.senha_recusada:
                self.saude.lembrar_senha_do_sudo(None)
                a.estado, a.mensagem = "senha_recusada", "A placa recusou a senha do sudo."
            else:
                a.estado, a.mensagem = "nao_comecou", chamada.erro
            self.atualizacaoMudou.emit()
            return
        a.estado, a.mensagem = "nao_comecou", "cancelada"
        self.atualizacaoMudou.emit()

    # ------------------------------------------------------------------ acompanhar

    def _acompanhar(self) -> None:
        conexao_ssh = self.conexao.conexao_ssh
        if conexao_ssh is None or self._id_da_tarefa is None or self._acompanhando is not None:
            return
        a = self.atualizacao
        if a is not None:
            a.estado, a.log = "rodando", []
            self.atualizacaoMudou.emit()
        self._acompanhando = self._chamar("acompanhar a atualização do firmware", self._acompanhar_no_laco,
                                          conexao_ssh, self._id_da_tarefa, ao_terminar=self._acompanhou)

    async def _acompanhar_no_laco(self, conexao_ssh, id_):
        from sh_placa.tarefas import TarefaNaPlaca

        tarefa = TarefaNaPlaca(conexao_ssh, id_)
        fim = await tarefa.acompanhar(lambda e: self._emitir_do_laco("passo", e),
                                      lambda texto: self._emitir_do_laco("log", texto))
        if fim.terminou or fim.interrompida:
            try:
                await tarefa.limpar()
            except ErroDaPlaca as e:
                log.info("a tarefa %s não foi apagada da placa: %s", id_, e)
        return fim

    def _acompanhou(self, chamada: Chamada) -> None:
        from sh_placa.atualizacao import desfecho
        from sh_placa.erros import ErroDeConexao

        self._acompanhando = None
        a = self.atualizacao
        if a is None:
            return
        if chamada.estado == "concluida":
            fim = chamada.resultado
            a.tarefa, a.estado, a.desfecho = fim, "terminou", desfecho(fim)
            if not a.log and fim.log:
                a.log = fim.log.splitlines(keepends=True)
            self._id_da_tarefa = None
            self.atualizacaoMudou.emit()
            self.atualizacaoTerminou.emit(a)
            self.saude.conferir()
            self.ler()
            return
        if chamada.estado == "falhou" and isinstance(chamada.excecao, ErroDeConexao):
            a.estado = "reconectando"            # a tarefa segue na placa; a conexão que voltar acompanha de novo
            self.atualizacaoMudou.emit()
            return
        if chamada.estado == "falhou":
            a.estado, a.mensagem = "terminou", chamada.erro
            a.desfecho = None
            self.atualizacaoMudou.emit()

    def dispensar(self) -> None:
        """O desfecho da última atualização foi visto."""
        if self.atualizacao is not None and not self.atualizacao.rodando:
            self.atualizacao = None
            self.atualizacaoMudou.emit()

    # ------------------------------------------------------------------ as cópias

    def apagar_copia(self, copia: CopiaAnterior) -> None:
        conexao_ssh = self.conexao.conexao_ssh
        if conexao_ssh is None:
            return
        self._chamar("apagar uma cópia do firmware", self._apagar_no_laco, conexao_ssh, copia.nome,
                     ao_terminar=self._apagou)

    @staticmethod
    async def _apagar_no_laco(conexao_ssh, nome):
        from sh_placa.atualizacao import apagar_copia

        await apagar_copia(conexao_ssh, nome)

    def _apagou(self, chamada: Chamada) -> None:
        if chamada.estado == "falhou":
            self.erro = chamada.erro
            self.mudou.emit()
        self.ler()

    def plano_para(self, origem) -> PlanoDeAtualizacao | None:
        """O plano de agora, ajustado à origem pedida (para mostrar na confirmação); ``None`` sem o plano."""
        from sh_placa import atualizacao as at

        if self.plano is None:
            return None
        if origem == "aplicativo":
            return self.plano
        if origem == "placa":
            f = at.firmware_da_placa(self.plano.codigo_da_placa, self.plano.versao_da_placa)
        else:
            f = at.firmware_da_copia(origem, at.subpastas_do_firmware(self.firmware))
        return replace(self.plano, firmware=f, novos=(), mudados=(), iguais=f.caminhos, bytes_a_enviar=0)
