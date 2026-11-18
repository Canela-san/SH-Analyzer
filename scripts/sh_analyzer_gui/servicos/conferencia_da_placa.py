"""O "Conferir antes" da captura (docs/gui-plan.md, 11.5; a F4.3), do lado da interface: roda o
``sh_placa.conferencia.conferir`` na placa conectada e guarda o resultado para a seção Capturar.

**Os estados** (:data:`ESTADOS`, ``mudou`` a cada mudança): ``"rodando"`` (com o :attr:`progresso` da captura curta),
``"precisa_da_senha"`` (nenhuma senha do sudo nesta sessão nem no cofre: a tela pergunta e chama de novo com ela),
``"senha_recusada"``, ``"feita"`` (o :attr:`resultado`), ``"falhou"`` (o :attr:`erro`) e ``"cancelada"``.

**A senha do sudo** é a da saúde da placa (a que deu certo nesta conexão, ``SaudeDaPlaca.senha_do_sudo``), senão a
desta conexão (a do usuário da placa, que costuma ser a do sudo), senão a do cofre do sistema; a que deu certo volta para a saúde, e vai para o cofre só se o usuário pedir. Nunca é escrita.

**Uma conexão nova** (ou a placa que sai) apaga o resultado: ele é desta placa, desta sessão.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from sh_placa.agente import ErroDaPlaca
from sh_placa.captura import Progresso
from sh_placa.pedido import PedidoDeCaptura
from shiboken6 import isValid

from .conexao_da_placa import ConexaoDaPlaca
from .placa import Chamada
from .saude_da_placa import SaudeDaPlaca

ESTADOS = ("rodando", "precisa_da_senha", "senha_recusada", "feita", "falhou", "cancelada")


class ConferenciaDaPlaca(QObject):
    """``pasta``: onde a captura curta fica enquanto é medida (a temporária do sistema; os testes passam outra)."""

    mudou = Signal()
    _progrediu = Signal(object)                  # do laço para a thread da interface

    def __init__(self, conexao: ConexaoDaPlaca, saude: SaudeDaPlaca, *, pasta: Path | None = None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self.conexao, self.saude = conexao, saude
        self.pasta = Path(pasta) if pasta is not None else Path(tempfile.gettempdir()) / "sh-analyzer-conferencias"
        self.estado: str | None = None
        self.resultado = None                    # a ConferenciaFeita da última que deu certo
        self.erro = ""
        self.pedido: PedidoDeCaptura | None = None
        self.progresso: Progresso | None = None
        self._chamada: Chamada | None = None
        self._sessao = conexao.sessoes
        self._progrediu.connect(self._ao_progredir)
        conexao.mudou.connect(self._conexao_mudou)

    @property
    def rodando(self) -> bool:
        return self.estado == "rodando"

    def pode_conferir(self) -> bool:
        return self.conexao.conectada and self.conexao.conexao_ssh is not None and not self.rodando

    def conferir(self, pedido: PedidoDeCaptura, senha: str | None = None, guardar: bool = False) -> Chamada | None:
        """Confere ``pedido`` na placa. Sem ``senha``: a da sessão, senão a do cofre (sem nenhuma, fica
        ``precisa_da_senha``). ``guardar`` leva a senha que deu certo para o cofre."""
        conexao_ssh = self.conexao.conexao_ssh
        if conexao_ssh is None or self.rodando:
            return None
        senha = senha or self.saude.senha_do_sudo or self.conexao.senha_da_placa()
        self.pedido, self.progresso, self.erro = pedido, None, ""
        self._mudar("rodando")
        self._chamada = self.conexao.servico.chamar(
            "conferir antes de capturar", self._no_laco, conexao_ssh, pedido, senha, guardar, self.conexao.cofre,
            self.pasta, ao_terminar=self._terminou)
        return self._chamada

    def cancelar(self) -> None:
        if self._chamada is not None and self._chamada.ativa:
            self._chamada.cancelar()

    def dispensar(self) -> None:
        """A mensagem do último estado (a falha, a senha recusada) foi vista; o resultado fica."""
        if self.estado not in (None, "rodando"):
            self._mudar("feita" if self.resultado is not None else None)

    async def _no_laco(self, conexao_ssh, pedido, senha, guardar, obter_o_cofre, pasta):
        from sh_placa.conferencia import conferir

        conta = conexao_ssh.destino.conta
        if senha is None:
            senha = await asyncio.to_thread(obter_o_cofre().senha, conta)
            if senha is None:
                return None
        feita = await conferir(conexao_ssh, pedido, pasta, senha_do_sudo=senha, ao_progresso=self._progresso_no_laco)
        aviso = ""
        if guardar:
            try:
                await asyncio.to_thread(obter_o_cofre().guardar, conta, senha)
            except ErroDaPlaca as e:
                aviso = str(e)
        return feita, senha, aviso

    def _progresso_no_laco(self, progresso: Progresso) -> None:
        if isValid(self):
            try:
                self._progrediu.emit(progresso)
            except RuntimeError:                 # apagado entre o isValid e o emit
                pass

    def _ao_progredir(self, progresso: Progresso) -> None:
        if self.rodando:
            self.progresso = progresso
            self.mudou.emit()

    def _terminou(self, chamada: Chamada) -> None:
        if chamada is not self._chamada:
            return
        self._chamada = None
        if chamada.estado == "concluida":
            if chamada.resultado is None:
                self._mudar("precisa_da_senha")
                return
            feita, senha, aviso = chamada.resultado
            self.saude.lembrar_senha_do_sudo(senha)
            self.resultado, self.erro = feita, aviso
            self._mudar("feita")
        elif chamada.estado == "falhou":
            from sh_placa.correcoes import ErroDoSudo

            if isinstance(chamada.excecao, ErroDoSudo) and chamada.excecao.senha_recusada:
                self.saude.lembrar_senha_do_sudo(None)
                self.erro = "A placa recusou a senha do sudo."
                self._mudar("senha_recusada")
            else:
                self.erro = chamada.erro
                self._mudar("falhou")
        else:
            self._mudar("cancelada")

    def _mudar(self, estado: str | None) -> None:
        self.estado = estado
        self.mudou.emit()

    def _conexao_mudou(self) -> None:
        nova = self.conexao.sessoes != self._sessao
        saiu = self.conexao.estado in ("desconectada", "falhou", "bloqueada")
        if not (nova or saiu):
            return
        self._sessao = self.conexao.sessoes
        if self.estado is None and self.resultado is None:
            return
        self.cancelar()
        self._chamada = None
        self.estado, self.resultado, self.erro, self.pedido, self.progresso = None, None, "", None, None
        self.mudou.emit()
