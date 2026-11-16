"""A placa conectada (docs/gui-plan.md, 11.3; a F3.5): a busca das placas, a conexão (uma por vez), a primeira
conexão, o enlace e a queda. A área de Aquisição, a barra superior e a barra de status mostram o que está aqui;
nenhuma delas fala com o ``sh_placa`` sozinha. Tudo o que fala com a placa roda no laço da ponte
(``servicos/placa.py``), e o estado muda só na thread da interface.

**O estado** (:attr:`ConexaoDaPlaca.estado`; ``mudou`` sai a cada troca, e quem mostra lê o resto dos atributos):

* ``desconectada``;
* ``conectando``: a caminho de :attr:`destino`;
* ``confirmar_host``: a primeira conexão com o endereço; a impressão digital (:attr:`impressao_pedida`) espera o sim
  ou o não do usuário (:meth:`confirmar_host`). A chave de uma placa conhecida (a mesma placa, por outro endereço) é
  aceita sem perguntar, e o registro de atividade diz por quê;
* ``pedir_senha``: a placa (ou o salto: :attr:`destino_pedido`) não aceitou a chave do aplicativo, e não há senha (ou
  a dada foi recusada: :attr:`motivo`). Antes de perguntar, vale a do cofre do sistema; depois, espera
  :meth:`informar_senha`;
* ``bloqueada``: a chave de host mudou (:attr:`bloqueio`) e nada foi enviado. :meth:`esquecer_chave_do_host` é a
  saída para uma placa regravada: a próxima conexão mostra a impressão nova para conferir;
* ``conectada``: com :attr:`estado_da_placa` (o ``estado`` do agente) e, logo depois, :attr:`enlace`;
* ``reconectando``: a conexão caiu (o cabo USB com mau contato é o caso comum) e o serviço tenta de novo sozinho,
  por um minuto, com a mesma chave e a mesma senha;
* ``falhou``: não conectou, ou caiu e não voltou (:attr:`motivo`).

**A primeira conexão** (:attr:`primeira_conexao`, logo depois de conectar): o que aconteceu (a impressão confirmada, a
chave do aplicativo instalada, a senha padrão da imagem) e a pergunta do relógio, que :meth:`responder_relogio`
lembra com a placa (``PlacaConhecida.acertar_relogio``; quem acerta o relógio é o diagnóstico, na F3.6).

**A busca** (:meth:`procurar`, e :meth:`procurar_sempre` enquanto a área está à vista): a ``Descoberta`` da F3.3. A
lista anterior fica até a próxima chegar; com uma placa conectada, a busca é mais espaçada (cada sondagem é uma
conexão no SSH da placa, que tem um núcleo só).

**O simulador** conecta pelo ``TransporteLocal``, sem SSH, sem impressão e sem enlace; a F3.9 o põe atrás de um SSH.

**A partida da janela não carrega a rede:** o asyncssh, o zeroconf e o keyring custam ~0,7 s para importar, e
entram no laço da placa na primeira busca ou conexão (``tests/test_arquitetura.py`` confere).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QTimer, Signal
from sh_placa import conhecidas as lista_de_conhecidas
from sh_placa.agente import ClienteDoAgente, ErroDaPlaca
from sh_placa.destino import SENHA_PADRAO_DA_IMAGEM, Destino
from sh_placa.erros import ChaveDoHostTrocada, ErroDeAutenticacao, ErroDeConexao, HostNaoConfirmado
from sh_placa.estado import EstadoDaPlaca
from sh_placa.registro import Entrada, RegistroDeAtividade
from shiboken6 import isValid

from .. import preferencias
from .placa import Chamada, ServicoDaPlaca

if TYPE_CHECKING:
    from sh_placa.conexao import ConexaoSSH, Enlace
    from sh_placa.descoberta import Descoberta, PlacaVista
    from sh_placa.simulador import Simulador

log = logging.getLogger(__name__)

ESTADOS = ("desconectada", "conectando", "confirmar_host", "pedir_senha", "bloqueada", "conectada", "reconectando",
           "falhou")
ESPERANDO_O_USUARIO = ("confirmar_host", "pedir_senha")
INTERVALO_DA_BUSCA_MS = 5_000
INTERVALO_DA_BUSCA_CONECTADA_MS = 30_000
ESPERAS_DA_RECONEXAO_S = (1, 2, 3, 5, 5, 5, 8, 8, 10, 10)
"""As esperas antes de cada tentativa de reconectar: ~1 min ao todo (a placa que reiniciou leva uns 40 s para
subir o SSH; o cabo que voltou, um segundo)."""
ESPERA_AO_ENCERRAR_S = 3.0


@dataclass(frozen=True)
class PrimeiraConexao:
    """O que a primeira conexão com uma placa (ou com um endereço novo dela) fez e o que falta perguntar."""

    host_confirmado: bool                 # a impressão digital foi confirmada agora
    chave_instalada: bool | None          # True: instalada agora; False: já estava; None: não foi instalada
    sem_a_chave: bool                     # entrou com a senha, e a chave do aplicativo não ficou na placa
    senha_padrao: bool                    # entrou com a senha padrão da imagem (temppwd)
    perguntar_relogio: bool               # a placa ainda não disse se o relógio é acertado a cada conexão
    aviso_do_cofre: str = ""              # o cofre do sistema não guardou a senha (o motivo)


@dataclass
class _Tentativa:
    """Uma conexão pedida: o destino (``None`` no simulador), a placa da lista, se houver, e o que o usuário disse."""

    destino: Destino | None
    placa: PlacaVista | None = None
    senha: str | None = field(default=None, repr=False)
    senha_do_salto: str | None = field(default=None, repr=False)
    guardar_senha: bool = False
    instalar_chave: bool = False
    host_confirmado: bool = False
    pedida_pelo_usuario: bool = True
    confiaveis: frozenset[str] = frozenset()   # as impressões das placas conhecidas (aceitas sem perguntar)


@dataclass
class _Sessao:
    """Uma placa conectada: o cliente do agente e o que fecha a conexão."""

    tentativa: _Tentativa
    cliente: ClienteDoAgente
    conexao: ConexaoSSH | None = None
    simulador: Simulador | None = None
    impressao: str | None = None
    quedas: int = 0


@dataclass(frozen=True)
class _Aberta:
    """O que a conexão devolve à thread da interface."""

    cliente: ClienteDoAgente
    estado: EstadoDaPlaca
    conexao: ConexaoSSH | None = None
    simulador: Simulador | None = None
    impressao: str | None = None
    autenticada_com: str | None = None
    chave_instalada: bool | None = None
    aviso_do_cofre: str = ""
    senha: str | None = field(default=None, repr=False)


def _responder(futuro: asyncio.Future, valor: Any) -> None:
    """Na thread do laço: a resposta do usuário ao futuro que a corrotina espera (se ela ainda espera)."""
    if not futuro.done():
        futuro.set_result(valor)


class ConexaoDaPlaca(QObject):
    """A placa da Aquisição. ``mudou`` sai a cada mudança do estado da conexão (e do enlace, da primeira conexão);
    ``placasMudaram``, a cada busca que terminou (e quando a placa conectada muda, que a lista marca)."""

    mudou = Signal()
    placasMudaram = Signal()
    _pediuConfirmacao = Signal(object, str, object)       # do laço: (destino, impressão, futuro)
    _caiu = Signal(object, str)                           # do laço: (conexão, motivo)

    def __init__(self, servico: ServicoDaPlaca, *, descoberta: Descoberta | None = None, pasta: Path | None = None,
                 cofre: Any = None, parent: QObject | None = None):
        super().__init__(parent)
        self.servico = servico
        self.registro = RegistroDeAtividade()
        self._pasta = pasta if pasta is not None else preferencias.pasta_da_placa()
        self._descoberta = descoberta            # criada no laço, na primeira busca (o asyncssh fica fora da partida)
        self._cofre = cofre
        self._chave = self._hosts = None         # idem, na primeira conexão
        self.estado = "desconectada"
        self.destino: Destino | None = None
        self.placa: PlacaVista | None = None
        self.motivo = ""
        self.impressao_pedida: str | None = None
        self.destino_pedido: Destino | None = None
        self.bloqueio: ChaveDoHostTrocada | None = None
        self.estado_da_placa: EstadoDaPlaca | None = None
        self.enlace: Enlace | None = None
        self.medindo_enlace = False
        self.erro_do_enlace = ""
        self.autenticada_com: str | None = None
        self.primeira_conexao: PrimeiraConexao | None = None
        self.conectada_em: float | None = None
        self.placas: list[PlacaVista] = []
        self.falhas_da_busca: list[str] = []
        self.procurando = False
        self.encerrada = False
        self._tentativa: _Tentativa | None = None
        self._sessao: _Sessao | None = None
        self._chamada_de_conexao: Chamada | None = None
        self._chamada_do_enlace: Chamada | None = None
        self._chamada_de_reconexao: Chamada | None = None
        self._futuro_da_confirmacao: asyncio.Future | None = None
        self._procurar_sempre = False
        self._busca = QTimer(self)
        self._busca.setSingleShot(True)
        self._busca.timeout.connect(self.procurar)
        self._pediuConfirmacao.connect(self._ao_pedir_confirmacao)
        self._caiu.connect(self._ao_cair)

    # ------------------------------------------------------------------ o que a interface lê

    @property
    def conectada(self) -> bool:
        return self.estado == "conectada"

    @property
    def simulada(self) -> bool:
        return self._sessao is not None and self._sessao.simulador is not None

    @property
    def tipo_do_caminho(self) -> str | None:
        """``usb``, ``lan``, ``wan`` ou ``simulador`` (o da placa da lista; ``None`` num destino digitado)."""
        t = self._tentativa if self._sessao is None else self._sessao.tentativa
        if t is None:
            return None
        if t.destino is None:
            return "simulador"
        caminho = _caminho_de(t.placa, t.destino)
        return caminho.tipo if caminho is not None else None

    @property
    def detalhe_do_caminho(self) -> str:
        """"USB (ECM)", "beaglebone.local (mDNS)", "neste computador"; vazio num destino digitado."""
        t = self._tentativa if self._sessao is None else self._sessao.tentativa
        caminho = _caminho_de(t.placa, t.destino) if t is not None else None
        return caminho.detalhe if caminho is not None else ""

    @property
    def pedida_pelo_usuario(self) -> bool:
        """A conexão em andamento (ou a última) foi pedida agora pelo usuário (e não é uma reconexão sozinha)."""
        return self._tentativa is not None and self._tentativa.pedida_pelo_usuario

    @property
    def quedas(self) -> int:
        """Quantas vezes a conexão de agora caiu (e voltou)."""
        return self._sessao.quedas if self._sessao is not None else 0

    def e_a_conectada(self, placa: PlacaVista) -> bool:
        """``placa`` (da lista) é a que está conectada (ou reconectando)?"""
        sessao = self._sessao
        if sessao is None or self.estado not in ("conectada", "reconectando"):
            return False
        if sessao.simulador is not None:
            return placa.estado == "simulador"
        serie = self.estado_da_placa.serie if self.estado_da_placa is not None else None
        if serie and placa.serie == serie:
            return True
        destino = sessao.tentativa.destino
        return any(c.destino == destino for c in placa.caminhos)

    # ------------------------------------------------------------------ a busca

    def procurar(self) -> Chamada | None:
        """Uma busca agora (nada, se já há uma rodando). A lista nova chega em :attr:`placas`."""
        self._busca.stop()
        if self.procurando or self.encerrada:
            return None
        self.procurando = True
        conhecidas = preferencias.placas_conhecidas()
        return self.servico.chamar("procurar as placas", self._varrer, conhecidas, ao_terminar=self._varreu)

    def procurar_sempre(self, ligado: bool) -> None:
        """Busca de tempos em tempos (enquanto a área está à vista), a primeira já."""
        self._procurar_sempre = ligado
        if not ligado:
            self._busca.stop()
        elif not self.procurando:
            self.procurar()

    async def _varrer(self, conhecidas) -> tuple[list[PlacaVista], list[str]]:
        if self._descoberta is None:
            from sh_placa.descoberta import Descoberta
            self._descoberta = Descoberta()
        placas = await self._descoberta.varrer(conhecidas)
        return placas, list(self._descoberta.falhas)

    def _varreu(self, chamada: Chamada) -> None:
        self.procurando = False
        if chamada.estado == "concluida":
            self.placas, self.falhas_da_busca = chamada.resultado
        elif chamada.estado == "falhou":
            self.falhas_da_busca = [chamada.erro]
        self.placasMudaram.emit()
        if self._procurar_sempre and not self.encerrada:
            self._busca.start(INTERVALO_DA_BUSCA_CONECTADA_MS if self._sessao is not None else INTERVALO_DA_BUSCA_MS)

    # ------------------------------------------------------------------ conectar

    def conectar(self, placa: PlacaVista | None = None, destino: Destino | None = None) -> None:
        """Conecta à ``placa`` da lista (pelo melhor caminho dela, ou por ``destino``, um dos caminhos dela) ou a um
        ``destino`` digitado. Uma placa conectada antes é desconectada; a mesma, já conectada, fica como está."""
        if self.encerrada:
            return
        if placa is not None and placa.estado == "simulador":
            alvo = None
        else:
            alvo = destino if destino is not None else (placa.melhor.destino if placa is not None and placa.melhor
                                                         else None)
            if alvo is None:
                raise ValueError("conectar: sem um endereço (a placa não tem um caminho pela rede)")
        if self._sessao is not None and self.estado in ("conectada", "reconectando") \
                and self._sessao.tentativa.destino == alvo and (alvo is not None or self.simulada):
            return
        self._largar()
        confiaveis = frozenset(p.impressao for p in preferencias.placas_conhecidas() if p.impressao)
        self._comecar(_Tentativa(alvo, placa, confiaveis=confiaveis))

    def informar_senha(self, senha: str, *, guardar: bool = False, instalar_chave: bool = True) -> None:
        """A senha que o usuário digitou (no estado ``pedir_senha``) para :attr:`destino_pedido` (a placa ou o
        salto): conecta de novo com ela. ``instalar_chave`` põe a chave do aplicativo na placa logo depois (as
        próximas conexões não pedem a senha); ``guardar`` leva a senha para o cofre do sistema."""
        t = self._tentativa
        if self.estado != "pedir_senha" or t is None:
            return
        if self.destino_pedido is not None and t.destino is not None and self.destino_pedido == t.destino.salto:
            t = replace(t, senha_do_salto=senha)
        else:
            t = replace(t, senha=senha, instalar_chave=instalar_chave)
        self._comecar(replace(t, guardar_senha=guardar or t.guardar_senha))

    def confirmar_host(self, sim: bool) -> None:
        """A resposta à impressão digital (no estado ``confirmar_host``)."""
        futuro, self._futuro_da_confirmacao = self._futuro_da_confirmacao, None
        if self.estado != "confirmar_host" or futuro is None:
            return
        if self._tentativa is not None:
            self._tentativa.host_confirmado = sim
        self.servico.laco.agendar(_responder, futuro, sim)
        self.impressao_pedida = self.destino_pedido = None
        self._mudar("conectando" if sim else "desconectada")

    def cancelar(self) -> None:
        """Desiste da conexão em andamento (ou da pergunta pendente)."""
        if self.estado in ("conectando", "confirmar_host", "pedir_senha", "bloqueada", "falhou"):
            self._largar()
            self._mudar("desconectada")

    def tentar_de_novo(self) -> None:
        """A mesma conexão de antes (depois de uma falha, ou de esquecer a chave de host)."""
        t = self._tentativa
        if t is not None and self.estado in ("falhou", "bloqueada", "desconectada"):
            self._largar()
            self._comecar(replace(t, host_confirmado=False, pedida_pelo_usuario=True))

    def _comecar(self, tentativa: _Tentativa) -> None:
        self._tentativa = tentativa
        self.destino = tentativa.destino
        self.placa = tentativa.placa
        self.motivo = ""
        self.bloqueio = None
        self.impressao_pedida = self.destino_pedido = None
        self.primeira_conexao = None
        self._mudar("conectando")
        if tentativa.destino is None:
            self._chamada_de_conexao = self.servico.chamar("conectar ao simulador", self._abrir_simulador,
                                                           ao_terminar=self._abriu)
        else:
            self._chamada_de_conexao = self.servico.chamar(f"conectar a {tentativa.destino}", self._abrir_ssh,
                                                           tentativa, ao_terminar=self._abriu)

    async def _abrir_ssh(self, t: _Tentativa) -> _Aberta:
        """Na thread do laço: a conexão, a chave do aplicativo (se o usuário quis), o ``estado`` do agente e a
        impressão fixada. Uma falha depois de conectar fecha a conexão."""
        from sh_placa.agente import TransporteSSH
        from sh_placa.chaves import ChaveDoAplicativo, CofreDeSenhas, HostsConhecidos
        from sh_placa.conexao import ConexaoSSH

        if self._chave is None:
            self._chave = ChaveDoAplicativo(self._pasta)
        if self._hosts is None:
            self._hosts = HostsConhecidos(self._pasta / "known_hosts")
        if self._cofre is None:
            self._cofre = CofreDeSenhas()
        conexao = ConexaoSSH(t.destino, chave=self._chave, hosts=self._hosts, registro=self.registro, senha=t.senha,
                             senha_do_salto=t.senha_do_salto,
                             confirmar_host=lambda d, i: self._confirmar_no_laco(t, d, i))
        conexao.ao_cair = lambda motivo: self._caiu_no_laco(conexao, motivo)
        await self._conectar_com_o_cofre(conexao, t)
        try:
            chave_instalada = await conexao.instalar_chave() \
                if conexao.autenticada_com == "senha" and t.instalar_chave else None
            cliente = ClienteDoAgente(TransporteSSH(conexao))
            estado = await cliente.estado()
            fixada = self._hosts.chave_de(t.destino.host, t.destino.porta)
            avisos = []
            for destino, senha in ((t.destino, t.senha), (t.destino.salto, t.senha_do_salto)):
                if t.guardar_senha and destino is not None and senha is not None:
                    try:
                        await asyncio.to_thread(self._cofre.guardar, destino.conta, senha)
                    except ErroDaPlaca as e:
                        avisos.append(str(e))
            aviso = " ".join(avisos)
        except BaseException:
            await conexao.fechar()
            raise
        return _Aberta(cliente, estado, conexao=conexao, impressao=fixada.get_fingerprint() if fixada else None,
                       autenticada_com=conexao.autenticada_com, chave_instalada=chave_instalada, aviso_do_cofre=aviso,
                       senha=t.senha)

    async def _conectar_com_o_cofre(self, conexao: ConexaoSSH, t: _Tentativa) -> None:
        """Conecta; se a placa (ou o salto) recusar a chave do aplicativo e não houver senha para ela, tenta a do
        cofre do sistema, uma vez por conta. Sem senha no cofre, o erro sobe (a interface pergunta)."""
        tentadas: set[str] = set()
        while True:
            try:
                await conexao.conectar()
                return
            except ErroDeAutenticacao as e:
                alvo = e.destino
                do_salto = alvo is not None and alvo == t.destino.salto
                if alvo is None or alvo.conta in tentadas or (t.senha_do_salto if do_salto else t.senha) is not None:
                    raise
                tentadas.add(alvo.conta)
                senha = await asyncio.to_thread(self._cofre.senha, alvo.conta)
                if senha is None:
                    raise
                self._fato(alvo, "a chave do aplicativo não foi aceita: tentando a senha do cofre do sistema")
                if do_salto:
                    conexao.senha_do_salto = senha
                else:
                    conexao.senha = senha

    async def _abrir_simulador(self) -> _Aberta:
        from sh_placa.simulador import Simulador

        simulador = Simulador()
        cliente = await asyncio.to_thread(simulador.__enter__)
        try:
            estado = await cliente.estado()
        except BaseException:
            await asyncio.to_thread(simulador.__exit__, None, None, None)
            raise
        return _Aberta(cliente, estado, simulador=simulador)

    async def _confirmar_no_laco(self, t: _Tentativa, destino: Destino, impressao: str) -> bool:
        """O ``confirmar_host`` da conexão: a chave de uma placa conhecida passa direto (é a mesma placa, por outro
        endereço, e a conexão de verdade confere que ela tem a chave privada); outra espera o usuário."""
        if impressao in t.confiaveis:
            self._fato(destino, f"a chave de host ({impressao}) é a de uma placa conhecida: aceita sem perguntar")
            return True
        futuro = asyncio.get_running_loop().create_future()
        if not isValid(self):
            return False
        try:
            self._pediuConfirmacao.emit(destino, impressao, futuro)
        except RuntimeError:                      # apagado entre o isValid e o emit (a janela fechou)
            return False
        return await futuro

    def _fato(self, destino: Destino, descricao: str) -> None:
        self.registro.registrar(Entrada(time.time(), destino.conta, "conexao", descricao))

    def _ao_pedir_confirmacao(self, destino: Destino, impressao: str, futuro: asyncio.Future) -> None:
        if self.estado != "conectando" or self._chamada_de_conexao is None:
            self.servico.laco.agendar(_responder, futuro, False)      # uma tentativa que já foi largada
            return
        self._futuro_da_confirmacao = futuro
        self.impressao_pedida, self.destino_pedido = impressao, destino
        self._mudar("confirmar_host")

    def _abriu(self, chamada: Chamada) -> None:
        if chamada is not self._chamada_de_conexao:
            if chamada.estado == "concluida":          # largada no caminho: fecha o que abriu
                self._fechar_em_segundo_plano(_sessao_de(chamada.resultado, self._tentativa))
            return
        self._chamada_de_conexao = None
        t = self._tentativa
        if chamada.estado == "cancelada":
            self._mudar("desconectada")
            return
        if chamada.estado == "falhou":
            e = chamada.excecao
            if isinstance(e, ChaveDoHostTrocada):
                self.bloqueio, self.motivo = e, str(e)
                self._mudar("bloqueada")
            elif isinstance(e, HostNaoConfirmado):
                self._mudar("desconectada")
            elif isinstance(e, ErroDeAutenticacao):
                self.destino_pedido = e.destino or t.destino
                do_salto = t.destino.salto is not None and self.destino_pedido == t.destino.salto
                digitada = t.senha_do_salto if do_salto else t.senha
                if not e.senha_recusada:
                    self.motivo = ""
                elif digitada is not None:
                    self.motivo = self.tr("A senha foi recusada.")
                else:
                    self.motivo = self.tr("A senha guardada no cofre do sistema foi recusada.")
                self._mudar("pedir_senha")
            else:
                self.motivo = chamada.erro
                self._mudar("falhou")
            return
        aberta: _Aberta = chamada.resultado
        self._sessao = _sessao_de(aberta, t)
        self.estado_da_placa = aberta.estado
        self.autenticada_com = aberta.autenticada_com
        self.conectada_em = time.time()
        self.primeira_conexao = self._lembrar(aberta, t)
        self._mudar("conectada")
        self.placasMudaram.emit()                     # a lista marca a conectada
        if aberta.conexao is not None:
            self._medir_enlace()

    def _lembrar(self, aberta: _Aberta, t: _Tentativa) -> PrimeiraConexao | None:
        """A placa nas conhecidas (pelo nº de série da EEPROM) e o resumo da primeira conexão, se houver o que dizer.
        O simulador não é lembrado (ele está sempre na lista)."""
        if aberta.simulador is not None:
            return None
        serie = aberta.estado.serie
        perguntar = False
        if serie:
            todas = preferencias.placas_conhecidas()
            anterior = next((p for p in todas if p.serie == serie), None)
            nome = anterior.nome if anterior is not None else (
                t.placa.nome if t.placa is not None and t.placa.conhecida is None and t.placa.nome
                else aberta.estado.nome_da_placa or serie)
            todas = lista_de_conhecidas.lembrar(todas, serie, nome, aberta.impressao, t.destino)
            preferencias.mudar_placas_conhecidas(todas)
            perguntar = todas[0].acertar_relogio is None
        else:
            log.warning("a placa em %s não disse o nº de série: não fica entre as conhecidas", t.destino)
        sem_a_chave = aberta.autenticada_com == "senha" and aberta.chave_instalada is None
        primeira = PrimeiraConexao(
            host_confirmado=t.host_confirmado, chave_instalada=aberta.chave_instalada, sem_a_chave=sem_a_chave,
            senha_padrao=aberta.senha == SENHA_PADRAO_DA_IMAGEM, perguntar_relogio=perguntar,
            aviso_do_cofre=aberta.aviso_do_cofre)
        if not (primeira.host_confirmado or primeira.chave_instalada is not None or primeira.sem_a_chave
                or primeira.senha_padrao or primeira.perguntar_relogio or primeira.aviso_do_cofre):
            return None
        return primeira

    def responder_relogio(self, acertar: bool) -> None:
        """A resposta da primeira conexão: acertar ou não o relógio da placa a cada conexão (lembrada com ela)."""
        serie = self.estado_da_placa.serie if self.estado_da_placa is not None else None
        if serie:
            try:
                preferencias.mudar_placas_conhecidas(
                    lista_de_conhecidas.definir_relogio(preferencias.placas_conhecidas(), serie, acertar))
            except KeyError:
                log.warning("a placa %s não está entre as conhecidas: a resposta do relógio não foi lembrada", serie)
        self.dispensar_primeira_conexao()

    def dispensar_primeira_conexao(self) -> None:
        """O resumo da primeira conexão foi visto (a pergunta do relógio, sem resposta, volta na próxima)."""
        if self.primeira_conexao is not None:
            self.primeira_conexao = None
            self.mudou.emit()

    def lembrar_acertar_relogio(self) -> bool | None:
        """O que a placa conectada respondeu à pergunta do relógio (``None``: não perguntado, ou sem placa)."""
        serie = self.estado_da_placa.serie if self.estado_da_placa is not None else None
        return next((p.acertar_relogio for p in preferencias.placas_conhecidas() if p.serie == serie), None)

    # ------------------------------------------------------------------ o enlace

    def _medir_enlace(self) -> None:
        sessao = self._sessao
        if sessao is None or sessao.conexao is None:
            return
        self.medindo_enlace, self.erro_do_enlace = True, ""
        self._chamada_do_enlace = self.servico.chamar("medir o enlace", sessao.conexao.medir_enlace,
                                                      ao_terminar=self._mediu_enlace)

    def _mediu_enlace(self, chamada: Chamada) -> None:
        if chamada is not self._chamada_do_enlace:
            return
        self._chamada_do_enlace = None
        self.medindo_enlace = False
        if chamada.estado == "concluida":
            self.enlace = chamada.resultado
        elif chamada.estado == "falhou":
            self.erro_do_enlace = chamada.erro
        self.mudou.emit()

    # ------------------------------------------------------------------ a queda e a volta

    def _caiu_no_laco(self, conexao: ConexaoSSH, motivo: str) -> None:
        if isValid(self):
            try:
                self._caiu.emit(conexao, motivo)
            except RuntimeError:
                pass

    def _ao_cair(self, conexao: ConexaoSSH, motivo: str) -> None:
        sessao = self._sessao
        if sessao is None or sessao.conexao is not conexao or self.estado != "conectada":
            return
        sessao.quedas += 1
        self.motivo = motivo
        if self._chamada_do_enlace is not None:
            self._chamada_do_enlace.cancelar()
            self._chamada_do_enlace, self.medindo_enlace = None, False
        self._mudar("reconectando")
        self._chamada_de_reconexao = self.servico.chamar("reconectar", self._reconectar, sessao,
                                                         ao_terminar=self._reconectou)

    async def _reconectar(self, sessao: _Sessao) -> EstadoDaPlaca:
        """Tenta de novo, com esperas crescentes, até ~1 min. A chave de host trocada e a autenticação recusada param
        na hora: nenhuma das duas melhora tentando."""
        ultimo: ErroDaPlaca | None = None
        for espera in ESPERAS_DA_RECONEXAO_S:
            await asyncio.sleep(espera)
            try:
                await sessao.conexao.conectar()
                return await sessao.cliente.estado()
            except (ChaveDoHostTrocada, ErroDeAutenticacao, HostNaoConfirmado):
                raise
            except ErroDeConexao as e:
                ultimo = e
                await sessao.conexao.fechar()
        total = sum(ESPERAS_DA_RECONEXAO_S)
        raise ErroDeConexao(f"a conexão caiu e não voltou em {total} s ({ultimo})")

    def _reconectou(self, chamada: Chamada) -> None:
        if chamada is not self._chamada_de_reconexao:
            return
        self._chamada_de_reconexao = None
        if chamada.estado == "cancelada":
            return
        if chamada.estado == "concluida":
            self.estado_da_placa = chamada.resultado
            self.motivo = ""
            self._mudar("conectada")
            return
        sessao, self._sessao = self._sessao, None
        if sessao is not None:
            self._fechar_em_segundo_plano(sessao)
        e = chamada.excecao
        if isinstance(e, ChaveDoHostTrocada):
            self.bloqueio, self.motivo = e, str(e)
            self._tentativa = replace(self._tentativa, pedida_pelo_usuario=False)
            self._mudar("bloqueada")
        else:
            self.motivo = chamada.erro
            self._mudar("falhou")
        self.placasMudaram.emit()

    # ------------------------------------------------------------------ desconectar

    def desconectar(self) -> None:
        if self.estado == "desconectada" and self._sessao is None:
            return
        self._largar()
        self._mudar("desconectada")
        self.placasMudaram.emit()

    def esquecer_chave_do_host(self) -> Chamada | None:
        """Depois do bloqueio, numa placa regravada: esquece a chave antiga do endereço e conecta de novo (a
        impressão nova aparece para conferir; a placa conhecida com a chave antiga não a aceita sozinha)."""
        if self.estado != "bloqueada" or self.bloqueio is None:
            return None
        destino = self.bloqueio.destino
        return self.servico.chamar("esquecer a chave de host", self._esquecer_no_laco, destino,
                                   ao_terminar=lambda _c: self.tentar_de_novo())

    async def _esquecer_no_laco(self, destino: Destino) -> bool:
        if self._hosts is None:
            from sh_placa.chaves import HostsConhecidos
            self._hosts = HostsConhecidos(self._pasta / "known_hosts")
        esquecida = await asyncio.to_thread(self._hosts.esquecer, destino.host, destino.porta)
        if esquecida:
            self._fato(destino, "a chave de host antiga foi esquecida, a pedido do usuário")
        return esquecida

    def esquecer_placa(self, serie: str) -> None:
        """Tira a placa das conhecidas (o nome, os endereços, a resposta do relógio). As chaves de host ficam: uma
        placa conhecida de novo pelo mesmo endereço tem de apresentar a mesma."""
        preferencias.mudar_placas_conhecidas(lista_de_conhecidas.esquecer(preferencias.placas_conhecidas(), serie))
        self.procurar()

    def encerrar(self, espera_s: float = ESPERA_AO_ENCERRAR_S) -> None:
        """Ao fechar a janela: fecha a conexão (e apaga a pasta do simulador) antes de o laço parar."""
        self.encerrada = True
        self._busca.stop()
        sessao = self._sessao
        self._largar(fechar=False)
        if sessao is not None and self.servico.laco.rodando:
            try:
                self.servico.laco.submeter(_fechar_sessao, sessao).resultado(espera_s)
            except Exception as e:               # o fim da janela segue; o laço para logo depois
                log.warning("a conexão com a placa não fechou direito ao sair: %s", e)

    def _largar(self, fechar: bool = True) -> None:
        """Larga o que está em andamento (a conexão, a reconexão, o enlace, a pergunta) e fecha a sessão."""
        futuro, self._futuro_da_confirmacao = self._futuro_da_confirmacao, None
        if futuro is not None:
            self.servico.laco.agendar(_responder, futuro, False)
        for nome in ("_chamada_de_conexao", "_chamada_do_enlace", "_chamada_de_reconexao"):
            chamada = getattr(self, nome)
            setattr(self, nome, None)
            if chamada is not None:
                chamada.cancelar()
        sessao, self._sessao = self._sessao, None
        if sessao is not None and fechar:
            self._fechar_em_segundo_plano(sessao)
        self.estado_da_placa = self.enlace = self.autenticada_com = self.conectada_em = None
        self.impressao_pedida = self.destino_pedido = None
        self.medindo_enlace, self.erro_do_enlace = False, ""
        self.primeira_conexao = None

    def _fechar_em_segundo_plano(self, sessao: _Sessao | None) -> None:
        if sessao is not None and not self.servico.encerrado:
            self.servico.chamar("desconectar", _fechar_sessao, sessao)

    def _mudar(self, estado: str) -> None:
        if estado not in ESTADOS:
            raise ValueError(f"estado desconhecido: {estado!r}")
        self.estado = estado
        self.mudou.emit()


async def _fechar_sessao(sessao: _Sessao) -> None:
    if sessao.conexao is not None:
        await sessao.conexao.fechar()
    if sessao.simulador is not None:
        await asyncio.to_thread(sessao.simulador.__exit__, None, None, None)


def _sessao_de(aberta: _Aberta, tentativa: _Tentativa) -> _Sessao:
    return _Sessao(tentativa, aberta.cliente, aberta.conexao, aberta.simulador, aberta.impressao)


def _caminho_de(placa: PlacaVista | None, destino: Destino | None):
    """O caminho da placa da lista que leva a ``destino`` (o simulador: o dele)."""
    if placa is None:
        return None
    return next((c for c in placa.caminhos if c.destino == destino), None)
