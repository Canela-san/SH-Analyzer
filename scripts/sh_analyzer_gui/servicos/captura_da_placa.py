"""A captura pela interface (docs/gui-plan.md, 11.5 e 11.6; a F4.4): o pedido do formulário na placa conectada, direto
no computador (``sh_placa.captura.CapturaContinua``) ou no cartão (``sh_placa.captura_no_cartao.CapturaNoCartao``),
o progresso, o texto do ``ler_adc``, o Parar e o fim.

**Os estados** (:data:`ESTADOS`, ``mudou`` a cada mudança; ``progrediu`` a cada progresso): ``"comecando"`` (o sudo,
a PRU), ``"capturando"``, ``"parando"``, ``"sem_conexao"`` (só no cartão: o cabo caiu, a captura segue na placa e o
acompanhamento volta com a conexão), ``"feita"`` (o :attr:`fim`), ``"falhou"`` (o :attr:`erro`),
``"precisa_da_senha"`` e ``"senha_recusada"``. :meth:`dispensar` volta a ``None`` (o formulário).

**Os marcos** (``marco``, na hora do fato, para o caderno de bancada): ``"comecou"`` (o ``ler_adc`` começou a
amostrar), ``"caiu"`` (no cartão: a conexão caiu e a captura segue na placa), ``"retomada"`` (o acompanhamento voltou,
com uma conexão nova), ``"terminou"`` (o :attr:`fim`) e ``"falhou"`` (o :attr:`erro`; a senha pedida ou recusada,
antes de começar, não é marco).

**A senha do sudo** é a da conferência: a da saúde da placa, senão a desta conexão, senão a do cofre; a que deu certo
volta para a saúde (e para o cofre, se pedido). Nunca é escrita.

**O arquivo:** :func:`sh_placa.pedido.nome_do_arquivo`; no computador, na pasta da sessão do dia, com ``_2``, ``_3``...
se o nome já existe (nada é sobrescrito). **No cartão**, o pedido vai com o ``-o`` escolhido.

**A captura no cartão em curso** (lançada antes, por este aplicativo ou por outro, e a que o cabo derrubou): a cada
conexão nova, :func:`~sh_placa.captura_no_cartao.em_curso` diz o que a placa tem, e o serviço volta a acompanhar a que
roda (ou recolhe a que terminou sem ninguém olhar). **No fim**, a pasta dela em ``.em_curso`` sai e, se o pedido
pede (``trazer_no_fim``), a captura vai para a fila de transferências, que a confere.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from sh_placa import pedido as pd
from sh_placa.agente import PASTA_DO_FIRMWARE, ErroDaPlaca
from sh_placa.captura import CapturaContinua, CapturaRecebida, Progresso, caminho_parcial
from sh_placa.captura_no_cartao import CapturaGravadaNoCartao, CapturaNoCartao, em_curso
from sh_placa.erros import ErroDeConexao
from sh_placa.pedido import PedidoDeCaptura
from shiboken6 import isValid

from .. import preferencias
from .conexao_da_placa import ConexaoDaPlaca
from .placa import Chamada
from .saude_da_placa import SaudeDaPlaca

log = logging.getLogger(__name__)

ESTADOS = ("comecando", "capturando", "parando", "sem_conexao", "feita", "falhou", "precisa_da_senha",
           "senha_recusada")
MARCOS = ("comecou", "caiu", "retomada", "terminou", "falhou")
RODANDO = ("comecando", "capturando", "parando", "sem_conexao")
LINHAS_DO_TEXTO = 300


def arquivo_livre(pasta: Path, nome: str) -> Path:
    """``pasta/nome``, ou ``nome_2``, ``nome_3``... se ele (ou o ``.parcial`` dele) já existe: nada é sobrescrito."""
    base, extensao = (nome[:-4], ".bin") if nome.endswith(".bin") else (nome, "")
    candidato, n = pasta / nome, 1
    while candidato.exists() or caminho_parcial(candidato).exists():
        n += 1
        candidato = pasta / f"{base}_{n}{extensao}"
    return candidato


@dataclass(frozen=True)
class FimDaCaptura:
    """O fim de uma captura, de qualquer destino: o que a tela resume. ``arquivo``: a captura neste computador (no
    cartão, ``None`` até a transferência a trazer)."""

    destino: str
    nome: str
    arquivo: Path | None
    blocos: int
    duracao_s: float
    motivo: str                       # o do ler_adc ("ok", "interrompida", "adc_mudo"...) ou o daqui
    codigo: int | None
    parada_pedida: bool
    caiu: bool                        # no computador: fechada aqui (a queda, o disco daqui)
    falha: str
    crc_confere: bool | None          # o CRC das amostras do arquivo é o do ler_adc? None: o fim é daqui (ou cartão)
    integridade: tuple[int, int, int] | None
    texto: tuple[str, ...]

    @property
    def gravou(self) -> bool:
        return self.blocos > 0

    @classmethod
    def do_computador(cls, r: CapturaRecebida) -> FimDaCaptura:
        cab = r.fechamento.cabecalho
        integridade = None if cab.amostras_atrasadas is None else (
            cab.amostras_atrasadas or 0, cab.buffers_sobrescritos or 0, cab.quadros_preambulo_ruim or 0)
        return cls("computador", r.arquivo.name, r.arquivo, r.blocos, cab.duracao_real_segundos or r.duracao_s, r.motivo,
                   r.codigo, r.parada_pedida, r.caiu, r.falha, r.fechamento.crc_confere, integridade, r.texto)

    @classmethod
    def do_cartao(cls, g: CapturaGravadaNoCartao) -> FimDaCaptura:
        return cls("cartao", g.nome, None, g.blocos, g.duracao_s, g.motivo, g.codigo, g.parada_pedida, False, "",
                   None, g.integridade, g.texto)


class CapturaDaPlaca(QObject):
    """``pasta_do_destino()``: a pasta da sessão do dia (os testes passam outra); ``transferencias``: a fila para o
    ``trazer_no_fim`` do cartão (``None``: a captura fica no cartão)."""

    mudou = Signal()
    progrediu = Signal()
    texto = Signal(str)
    marco = Signal(str)                         # MARCOS, na hora do fato
    _do_laco = Signal(str, object)              # do laço para a interface: ("progresso", Progresso), ("texto", str)

    def __init__(self, conexao: ConexaoDaPlaca, saude: SaudeDaPlaca, transferencias=None, *,
                 pasta_do_destino: Callable[[], Path] = preferencias.pasta_da_sessao,
                 pasta_firmware: str = PASTA_DO_FIRMWARE, parent: QObject | None = None):
        super().__init__(parent)
        self.conexao, self.saude, self.transferencias = conexao, saude, transferencias
        self.pasta_do_destino, self.pasta_firmware = pasta_do_destino, pasta_firmware
        self.estado: str | None = None
        self.pedido: PedidoDeCaptura | None = None
        self.destino = "computador"
        self.nome = ""
        self.arquivo: Path | None = None            # no computador, o nome final (o .parcial ao lado, até o fim)
        self.progresso: Progresso | None = None
        self.linhas: deque[str] = deque(maxlen=LINHAS_DO_TEXTO)
        self.fim: FimDaCaptura | None = None
        self.erro = ""
        self.retomada = False                       # no cartão: acompanhada depois de uma queda ou de outra sessão
        self.comecou_em: float | None = None        # time.monotonic() do começo (o relógio da tela)
        self._senha: str | None = None
        self._guardar = False
        self._chamada: Chamada | None = None
        self._no_laco: CapturaContinua | CapturaNoCartao | None = None
        self._sessao = conexao.sessoes
        self._serie: str | None = None              # a placa da captura no cartão (a queda volta só para ela)
        self._a_trazer: str | None = None           # o nome no cartão que espera a lista do agente para a fila
        self._procurou_em_curso = False
        self._do_laco.connect(self._ao_receber)
        conexao.mudou.connect(self._conexao_mudou)
        saude.mudou.connect(self._saude_mudou)

    # ------------------------------------------------------------------ o que a tela lê

    @property
    def rodando(self) -> bool:
        return self.estado in RODANDO

    @property
    def no_cartao(self) -> bool:
        return self.destino == "cartao"

    def pode_capturar(self) -> bool:
        return self.conexao.conectada and self.conexao.conexao_ssh is not None and not self.rodando

    @property
    def pode_parar(self) -> bool:
        return self.estado == "capturando" and self.progresso is not None and self.progresso.inicio is not None

    def transferencia_do_fim(self):
        """O item da fila de transferências da captura no cartão que terminou (``None``: a do computador, ou a do
        cartão que ainda não foi pedida)."""
        f = self.fim
        if f is None or f.destino != "cartao" or not f.gravou or self.transferencias is None:
            return None
        achada = self._na_lista_do_agente(f.nome)
        return self.transferencias.item_de(achada) if achada is not None else None

    def local_do_fim(self) -> Path | None:
        """Onde a captura que terminou está neste computador: o arquivo da captura para o computador, ou a cópia
        conferida da do cartão (``None``: ela ainda não está aqui)."""
        f = self.fim
        if f is None or not f.gravou:
            return None
        if f.arquivo is not None:
            return f.arquivo
        item = self.transferencia_do_fim()
        return Path(item.local) if item is not None and item.estado == "conferida" else None

    # ------------------------------------------------------------------ capturar

    def capturar(self, pedido: PedidoDeCaptura, senha: str | None = None, guardar: bool = False) -> Chamada | None:
        """Começa ``pedido``. Sem ``senha``: a da sessão, senão a do cofre (sem nenhuma, ``precisa_da_senha``: a tela
        pergunta e chama de novo com ela). ``guardar`` leva a senha que deu certo para o cofre."""
        conexao_ssh = self.conexao.conexao_ssh
        if conexao_ssh is None or self.rodando:
            return None
        senha = senha or self.saude.senha_do_sudo or self.conexao.senha_da_placa()
        self.pedido, self.destino = pedido, pedido.destino
        self.nome = pd.nome_do_arquivo(pedido)
        self.fim, self.erro, self.progresso, self.retomada = None, "", None, False
        self.linhas.clear()
        self._guardar = guardar
        self._serie = self.saude.saude.serie if self.saude.saude is not None else None
        if self.no_cartao:
            self.arquivo = None
            pedido = pedido.com(arquivo_no_cartao=self.nome)
            self.pedido = pedido
            funcao, args = self._comecar_no_cartao, (conexao_ssh, pedido, self.nome, senha, self.conexao.cofre)
        else:
            pasta = self.pasta_do_destino()
            pasta.mkdir(parents=True, exist_ok=True)
            self.arquivo = arquivo_livre(pasta, self.nome)
            self.nome = self.arquivo.name
            funcao, args = self._no_computador, (conexao_ssh, pedido, self.arquivo, senha, self.conexao.cofre)
        self.comecou_em = time.monotonic()
        self._mudar("comecando")
        self._chamada = self.conexao.servico.chamar(f"capturar ({self.nome})", funcao, *args,
                                                    ao_terminar=self._terminou)
        return self._chamada

    def parar(self) -> None:
        """O Parar: o ``ler_adc`` fecha no último bloco inteiro, com o cabeçalho final dele."""
        if self.estado != "capturando" or self._no_laco is None:
            return
        self._mudar("parando")
        captura = self._no_laco
        if isinstance(captura, CapturaContinua):
            self.conexao.servico.laco.agendar(captura.parar)
        else:
            self.conexao.servico.chamar("parar a captura no cartão", captura.parar, self._senha or "",
                                        ao_terminar=self._parou_no_cartao)

    def cancelar(self) -> None:
        """O aplicativo que fecha: a captura no computador para (o canal fecha; o ``.parcial`` fica para recuperar);
        a do cartão segue na placa."""
        if self._chamada is not None and self._chamada.ativa:
            self._chamada.cancelar()

    def trazer(self) -> None:
        """A captura no cartão que terminou para a fila de transferências (o "Trazer" do fim, quando o pedido não
        pedia ou era de uma captura retomada)."""
        if self.fim is not None and self.fim.destino == "cartao" and self.fim.gravou and self.transferencias:
            self._a_trazer = self.fim.nome
            if self.saude.conferir() is None:
                self._saude_mudou()

    def dispensar(self) -> None:
        """O fim (ou a falha) visto: de volta ao formulário."""
        if not self.rodando:
            self.estado, self.fim, self.erro = None, None, ""
            self._a_trazer = None
            self.mudou.emit()

    # ------------------------------------------------------------------ no laço

    async def _senha_do_cofre(self, conta: str, senha: str | None, obter_o_cofre) -> str | None:
        if senha is not None:
            return senha
        return await asyncio.to_thread(obter_o_cofre().senha, conta)

    async def _guardar_no_cofre(self, conta: str, senha: str, obter_o_cofre) -> None:
        if self._guardar:
            try:
                await asyncio.to_thread(obter_o_cofre().guardar, conta, senha)
            except ErroDaPlaca as e:
                log.warning("a senha do sudo não foi para o cofre: %s", e)

    async def _no_computador(self, conexao_ssh, pedido: PedidoDeCaptura, arquivo: Path, senha, obter_o_cofre):
        senha = await self._senha_do_cofre(conexao_ssh.destino.conta, senha, obter_o_cofre)
        if senha is None:
            return None
        self._senha = senha
        captura = CapturaContinua(conexao_ssh, pedido.argumentos(), arquivo, senha_do_sudo=senha,
                                  ao_progresso=self._progresso_no_laco, ao_texto=self._texto_no_laco)
        self._no_laco = captura
        recebida = await captura.rodar()
        await self._guardar_no_cofre(conexao_ssh.destino.conta, senha, obter_o_cofre)
        return FimDaCaptura.do_computador(recebida), senha

    async def _comecar_no_cartao(self, conexao_ssh, pedido: PedidoDeCaptura, nome: str, senha, obter_o_cofre):
        senha = await self._senha_do_cofre(conexao_ssh.destino.conta, senha, obter_o_cofre)
        if senha is None:
            return None
        self._senha = senha
        captura = CapturaNoCartao(conexao_ssh, nome, pasta_firmware=self.pasta_firmware,
                                  ao_progresso=self._progresso_no_laco, ao_texto=self._texto_no_laco)
        self._no_laco = captura
        await captura.iniciar(pedido.argumentos(saida=False), senha)
        await self._guardar_no_cofre(conexao_ssh.destino.conta, senha, obter_o_cofre)
        return await self._acompanhar(captura, senha)

    async def _retomar_no_cartao(self, conexao_ssh, nome: str):
        captura = CapturaNoCartao(conexao_ssh, nome, pasta_firmware=self.pasta_firmware,
                                  ao_progresso=self._progresso_no_laco, ao_texto=self._texto_no_laco)
        self._no_laco = captura
        return await self._acompanhar(captura, self._senha)

    async def _acompanhar(self, captura: CapturaNoCartao, senha):
        gravada = await captura.acompanhar()
        await captura.limpar()
        return FimDaCaptura.do_cartao(gravada), senha

    async def _procurar_em_curso(self, conexao_ssh):
        return await em_curso(conexao_ssh, self.pasta_firmware)

    def _progresso_no_laco(self, progresso: Progresso) -> None:
        self._emitir("progresso", progresso)

    def _texto_no_laco(self, linha: str) -> None:
        self._emitir("texto", linha)

    def _emitir(self, tipo: str, dado) -> None:
        if isValid(self):
            try:
                self._do_laco.emit(tipo, dado)
            except RuntimeError:                 # apagado entre o isValid e o emit
                pass

    # ------------------------------------------------------------------ na interface

    def _ao_receber(self, tipo: str, dado) -> None:
        if tipo == "texto":
            self.linhas.append(dado)
            self.texto.emit(dado)
            return
        self.progresso = dado
        if self.estado == "comecando" and dado.inicio is not None:
            self._mudar("capturando")
            self.marco.emit("comecou")
        self.progrediu.emit()

    def _parou_no_cartao(self, chamada: Chamada) -> None:
        if chamada.estado == "falhou" and self.estado == "parando":
            self.erro = chamada.erro
            self._mudar("capturando")             # o kill não foi: a captura segue (o Parar fica de novo)

    def _terminou(self, chamada: Chamada) -> None:
        if chamada is not self._chamada:
            return
        self._chamada = None
        if chamada.estado == "concluida":
            if chamada.resultado is None:
                self._mudar("precisa_da_senha")
                return
            fim, senha = chamada.resultado
            self._no_laco = None
            if senha:
                self.saude.lembrar_senha_do_sudo(senha)
            self.fim = fim
            self._mudar("feita")
            self.marco.emit("terminou")
            if fim.destino == "cartao" and fim.gravou and self.pedido is not None and self.pedido.trazer_no_fim \
                    and self.transferencias is not None:
                self._a_trazer = fim.nome
            if self.saude.conferir() is None:     # o espaço livre, as capturas: a saúde de novo
                self._saude_mudou()
            return
        if chamada.estado == "falhou":
            from sh_placa.captura import ErroDaCaptura
            from sh_placa.correcoes import ErroDoSudo

            e = chamada.excecao
            if self.no_cartao and isinstance(e, ErroDeConexao) and self.estado in ("capturando", "parando"):
                self._mudar("sem_conexao")          # a captura segue na placa; a conexão de volta a acompanha
                self.marco.emit("caiu")
                self._talvez_retomar()
                return
            self._no_laco = None
            if isinstance(e, ErroDoSudo) and e.senha_recusada:
                self.saude.lembrar_senha_do_sudo(None)
                self.erro = "A placa recusou a senha do sudo."
                self._mudar("senha_recusada")
                return
            self.erro = chamada.erro
            if isinstance(e, ErroDaCaptura) and e.texto:
                self.linhas.extend(e.texto[-20:])
            self._mudar("falhou")
            self.marco.emit("falhou")
            return
        self._no_laco = None                          # cancelada (o aplicativo fechando)
        self.erro = "A captura foi cancelada."
        self._mudar("falhou")
        self.marco.emit("falhou")

    def _mudar(self, estado: str | None) -> None:
        self.estado = estado
        self.mudou.emit()

    # ------------------------------------------------------------------ a conexão e a saúde

    def _conexao_mudou(self) -> None:
        c = self.conexao
        if c.estado != "conectada":
            if c.estado in ("desconectada", "falhou", "bloqueada"):
                self._procurou_em_curso = False
            return
        nova = c.sessoes != self._sessao
        self._sessao = c.sessoes
        if self.estado == "sem_conexao":
            self._talvez_retomar()
        elif nova or not self._procurou_em_curso:
            self._procurar_capturas_em_curso()

    def _mesma_placa(self) -> bool:
        serie = self.saude.saude.serie if self.saude.saude is not None else None
        return self._serie is None or serie is None or serie == self._serie

    def _talvez_retomar(self) -> None:
        c = self.conexao
        if self.estado != "sem_conexao" or c.estado != "conectada" or c.conexao_ssh is None or \
                self._chamada is not None or not self._mesma_placa():
            return
        self.retomada = True
        self.erro = ""
        self._mudar("capturando")
        self._chamada = c.servico.chamar(f"acompanhar a captura no cartão ({self.nome})", self._retomar_no_cartao,
                                         c.conexao_ssh, self.nome, ao_terminar=self._terminou)
        self.marco.emit("retomada")

    def _procurar_capturas_em_curso(self) -> None:
        """Uma conexão nova: há uma captura no cartão que ninguém acompanha (lançada antes da queda, ou por um
        aplicativo que fechou)? Com uma, o serviço volta a acompanhá-la."""
        c = self.conexao
        if c.conexao_ssh is None or self.rodando:
            return
        self._procurou_em_curso = True
        c.servico.chamar("as capturas no cartão em curso", self._procurar_em_curso, c.conexao_ssh,
                         ao_terminar=self._achou_em_curso)

    def _achou_em_curso(self, chamada: Chamada) -> None:
        if chamada.estado != "concluida" or not chamada.resultado or self.rodando or not self.conexao.conectada:
            return
        capturas = sorted(chamada.resultado, key=lambda e: not e.rodando)     # a que roda primeiro
        achada = capturas[0]
        log.info("captura no cartão em curso na placa: %s (%s)", achada.nome,
                 "rodando" if achada.rodando else f"terminada, código {achada.codigo}")
        self.pedido, self.destino, self.nome, self.arquivo = None, "cartao", achada.nome, None
        self.fim, self.erro, self.progresso = None, "", None
        self.linhas.clear()
        self._serie = self.saude.saude.serie if self.saude.saude is not None else None
        self.comecou_em = time.monotonic()
        self.estado = "sem_conexao"                     # o caminho da retomada
        self._talvez_retomar()

    def _na_lista_do_agente(self, nome: str):
        capturas = self.saude.capturas
        return None if capturas is None else next((c for c in capturas.capturas if c.arquivo == nome), None)

    def _saude_mudou(self) -> None:
        """A captura no cartão que vai para o computador: quando a lista do agente a tem, entra na fila."""
        if self._a_trazer is None or self.transferencias is None:
            return
        achada = self._na_lista_do_agente(self._a_trazer)
        if achada is None:
            return
        self._a_trazer = None
        self.transferencias.transferir([achada])
        self.mudou.emit()
