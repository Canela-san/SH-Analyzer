"""A saúde da placa conectada (docs/gui-plan.md, 11.4 e 11.9; a F3.6): o que a visão geral e o diagnóstico mostram,
e as duas correções simples. A conexão é do ``servicos/conexao_da_placa.py``; este serviço a acompanha.

**O que se sabe da placa** (``mudou`` a cada mudança): a :attr:`SaudeDaPlaca.saude` (a resposta ``saude`` do agente,
com as conferências), as :attr:`capturas` na placa, o firmware deste aplicativo comparado pelo código
(:attr:`firmware_do_aplicativo`, ``sh_placa/versao.py``) e quando foi conferida. A saúde chega com a conexão; as
capturas e a comparação do firmware, logo depois; :meth:`conferir` lê tudo de novo (e cada correção também).

**Uma coisa por vez na placa** (ela tem um núcleo só, e uma medida atrapalha a outra: a vazão caía pela metade com a
leitura das capturas junto): o enlace da conexão, depois as capturas e o firmware, depois o relógio a cada conexão.

**A atividade:** cada comando e fato do registro de atividade da conexão sai em ``atividade(entrada)``, na thread da
interface (a visão geral mostra a lista ao vivo).

**As correções** (:attr:`correcao`, ``correcaoMudou``): os pinos (o ``config-pin``, sem senha) e o relógio (pelo
sudo, ``sh_placa/correcoes.py``). **Nada roda sem o pedido do usuário**, que a interface confirma antes, com o
comando à vista; a exceção é o relógio a cada conexão, que o usuário permitiu na primeira (a permissão fica com a
placa conhecida). **A senha do sudo:** a da sessão (a que o usuário digitou nesta conexão, ou que ele deu ao acertar o
relógio), senão a do cofre do sistema; sem nenhuma, a correção espera a senha (``precisa_da_senha``). Ela fica só na
memória, enquanto a placa está conectada, e vai para o cofre só se o usuário pedir.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal
from sh_placa.agente import ErroDaPlaca
from sh_placa.estado import CapturasDaPlaca, EstadoDaPlaca
from sh_placa.registro import Entrada
from shiboken6 import isValid

from .. import preferencias
from .conexao_da_placa import ConexaoDaPlaca
from .placa import Chamada

if TYPE_CHECKING:
    from sh_placa.correcoes import RelogioAcertado

log = logging.getLogger(__name__)

ESTADOS_DA_CORRECAO = ("rodando", "precisa_da_senha", "senha_recusada", "feita", "falhou")


@dataclass(frozen=True)
class Correcao:
    """Uma correção pedida: ``nome`` (``"pinos"`` ou ``"relogio"``), o estado (:data:`ESTADOS_DA_CORRECAO`) e a
    frase do que aconteceu."""

    nome: str
    estado: str
    mensagem: str = ""
    automatica: bool = False             # o relógio a cada conexão (o usuário não pediu agora)


def _antes(segundos: float) -> str:
    """Como o relógio estava: "estava 1,14 s adiantado", ou "já estava certo" (menos de um centésimo)."""
    if abs(segundos) < 0.01:
        return "já estava certo (menos de 0,01 s)"
    return "estava " + f"{abs(segundos):.2f}".replace(".", ",") + " s " + ("adiantado" if segundos > 0 else "atrasado")


def _agora(relogio) -> str:
    """O relógio depois de acertado: "certo" quando a faixa da medida cerca o zero (a estimativa, o meio dela, sai
    alguns centésimos para um lado, e dizer "agora, −0,04 s" pareceria que não acertou)."""
    if relogio is None:
        return ""
    limites, incerteza = relogio.limites_s, relogio.incerteza_s
    if limites is not None and limites[0] <= 0 <= limites[1]:
        return f"; agora está certo, dentro de ±{incerteza:.2f} s (o limite da medida)".replace(".", ",")
    return f"; agora, {relogio.diferenca_s():+.2f} s".replace(".", ",").replace("-", "−")


class SaudeDaPlaca(QObject):
    mudou = Signal()
    atividade = Signal(object)                 # uma Entrada nova do registro de atividade
    correcaoMudou = Signal()
    corrigiu = Signal(object)                  # a Correcao que terminou, feita ou não (o caderno)
    _registrou = Signal(object)                # do laço (ou da interface): a Entrada

    def __init__(self, conexao: ConexaoDaPlaca, parent: QObject | None = None):
        super().__init__(parent)
        self.conexao = conexao
        self.servico = conexao.servico
        self.saude: EstadoDaPlaca | None = None
        self.capturas: CapturasDaPlaca | None = None
        self.firmware_do_aplicativo: str | None = None
        self.conferida_em: float | None = None
        self.conferindo = False
        self.erro = ""                          # a última conferência não deu certo (o motivo)
        self.correcao: Correcao | None = None
        self.relogio_acertado: RelogioAcertado | None = None
        self.relogio_acertado_em: float | None = None
        self.aviso_do_relogio = ""              # o relógio a cada conexão não deu (falta a senha, por exemplo)
        self._sessao = 0
        self._estado_da_conexao = conexao.estado
        self._falta_ler = self._falta_o_relogio = False
        self._senha_do_sudo: str | None = None
        self._chamadas: set[Chamada] = set()
        self._registrou.connect(self._ao_registrar)
        self._parar_de_ouvir = conexao.registro.ouvir(self._registrou_no_laco)
        conexao.mudou.connect(self._conexao_mudou)
        conexao.relogioRespondido.connect(self._relogio_respondido)
        self.destroyed.connect(lambda *_: self._parar_de_ouvir())

    # ------------------------------------------------------------------ a atividade

    def _registrou_no_laco(self, entrada: Entrada) -> None:
        if isValid(self):
            try:
                self._registrou.emit(entrada)
            except RuntimeError:                # apagado entre o isValid e o emit
                pass

    def _ao_registrar(self, entrada: Entrada) -> None:
        self.atividade.emit(entrada)

    # ------------------------------------------------------------------ acompanhar a conexão

    def _conexao_mudou(self) -> None:
        c = self.conexao
        anterior, self._estado_da_conexao = self._estado_da_conexao, c.estado
        if c.estado == "conectada" and c.sessoes != self._sessao:
            self._sessao = c.sessoes                 # uma conexão nova: começa do que ela trouxe
            self._limpar()
            self.saude, self.conferida_em = c.estado_da_placa, time.time()
            self._falta_ler = True
            self._falta_o_relogio = c.conexao_ssh is not None and bool(c.lembrar_acertar_relogio())
            self.mudou.emit()
        elif c.estado == "conectada" and anterior == "reconectando":
            self.saude, self.conferida_em = c.estado_da_placa, time.time()   # voltou de uma queda, com a saúde
            self.mudou.emit()
        elif c.estado in ("desconectada", "falhou", "bloqueada") and self._sessao:
            self._sessao = 0
            self._limpar()
            self.mudou.emit()
            self.correcaoMudou.emit()
        self._continuar()

    def _continuar(self) -> None:
        """O próximo passo depois de conectar, quando a placa está livre: as capturas e o firmware; depois, o relógio a
        cada conexão (a permissão lembrada com a placa)."""
        if not self._sessao or self.conexao.estado != "conectada" or self.conexao.medindo_enlace \
                or self.conferindo or self._corrigindo():
            return
        if self._falta_ler:
            self._falta_ler = False
            self._ler_o_resto()
        elif self._falta_o_relogio:
            self._falta_o_relogio = False
            self.acertar_relogio(automatica=True)

    def _limpar(self) -> None:
        for chamada in list(self._chamadas):
            chamada.cancelar()
        self._chamadas.clear()
        self.saude = self.capturas = self.firmware_do_aplicativo = self.conferida_em = None
        self.correcao = self.relogio_acertado = self.relogio_acertado_em = None
        self.conferindo, self.erro, self.aviso_do_relogio = False, "", ""
        self._senha_do_sudo = None
        self._falta_ler = self._falta_o_relogio = False

    def _chamar(self, nome: str, funcao, *args, ao_terminar) -> Chamada:
        chamada = self.servico.chamar(nome, funcao, *args, ao_terminar=lambda ch: self._terminou(ch, ao_terminar))
        self._chamadas.add(chamada)
        return chamada

    def _terminou(self, chamada: Chamada, ao_terminar) -> None:
        if chamada not in self._chamadas:
            return                                   # de uma conexão anterior
        self._chamadas.discard(chamada)
        ao_terminar(chamada)

    # ------------------------------------------------------------------ conferir

    def _ler_o_resto(self) -> None:
        """As capturas e a comparação do firmware (a saúde veio com a conexão)."""
        cliente = self.conexao.cliente
        if cliente is None:
            return
        self.conferindo = True
        versao = self.saude.versao_do_firmware if self.saude is not None else None
        self._chamar("ler as capturas e o firmware", self._ler_no_laco, cliente, versao, False,
                     self.conexao.simulada, ao_terminar=self._leu)

    def conferir(self) -> Chamada | None:
        """Lê de novo a saúde, as capturas e o firmware (o "conferir de novo")."""
        cliente = self.conexao.cliente
        if cliente is None or self.conferindo:
            return None
        self.conferindo, self.erro = True, ""
        self.mudou.emit()
        versao = self.saude.versao_do_firmware if self.saude is not None else None
        return self._chamar("conferir a placa", self._ler_no_laco, cliente, versao, True, self.conexao.simulada,
                            ao_terminar=self._leu)

    @staticmethod
    async def _ler_no_laco(cliente, versao: str | None, com_a_saude: bool, simulada: bool):
        """Na thread do laço: a saúde (no "conferir de novo"), as capturas e o firmware do aplicativo comparado com o
        da placa (para o simulador, o firmware do aplicativo é o dele: o cenário do firmware antigo tem outro)."""
        from sh_placa.versao import firmware_do_aplicativo

        saude = await cliente.saude() if com_a_saude else None
        capturas = await cliente.capturas()
        versao = saude.versao_do_firmware if saude is not None else versao
        if simulada:
            from sh_placa.simulador import VERSAO_SIMULADA
            firmware = VERSAO_SIMULADA
        else:
            firmware = await asyncio.to_thread(firmware_do_aplicativo, versao)
        return saude, capturas, firmware

    def _leu(self, chamada: Chamada) -> None:
        self.conferindo = False
        if chamada.estado == "concluida":
            saude, self.capturas, self.firmware_do_aplicativo = chamada.resultado
            if saude is not None:
                self.saude, self.conferida_em = saude, time.time()
        elif chamada.estado == "falhou":
            self.erro = chamada.erro
        self.mudou.emit()
        self._continuar()

    # ------------------------------------------------------------------ as correções

    def _mudar_a_correcao(self, correcao: Correcao | None) -> None:
        self.correcao = correcao
        self.correcaoMudou.emit()
        if correcao is not None and correcao.estado in ("feita", "falhou"):
            self.corrigiu.emit(correcao)

    def corrigir_pinos(self) -> None:
        """O ``config-pin`` dos pinos fora do modo da PRU (a interface já confirmou), e a saúde de novo."""
        conexao_ssh, cliente = self.conexao.conexao_ssh, self.conexao.cliente
        errados = self.saude.pinos_errados if self.saude is not None else []
        if conexao_ssh is None or not errados or self._corrigindo():
            return
        self._mudar_a_correcao(Correcao("pinos", "rodando"))
        self._chamar("corrigir os pinos", self._pinos_no_laco, conexao_ssh, cliente, errados,
                     ao_terminar=self._corrigiu_pinos)

    async def _pinos_no_laco(self, conexao_ssh, cliente, errados: list[str]) -> EstadoDaPlaca:
        from sh_placa.correcoes import corrigir_pinos

        await corrigir_pinos(conexao_ssh, errados)
        return await cliente.saude()

    def _corrigiu_pinos(self, chamada: Chamada) -> None:
        if chamada.estado == "concluida":
            self.saude, self.conferida_em = chamada.resultado, time.time()
            restam = self.saude.pinos_errados
            mensagem = ("Os pinos estão no modo da PRU." if not restam else
                        f"O config-pin rodou, e {', '.join(restam)} continua(m) fora do modo da PRU.")
            self._mudar_a_correcao(Correcao("pinos", "feita" if not restam else "falhou", mensagem))
            self.mudou.emit()
        elif chamada.estado == "falhou":
            self._mudar_a_correcao(Correcao("pinos", "falhou", chamada.erro))
        else:
            self._mudar_a_correcao(None)

    @property
    def senha_do_sudo(self) -> str | None:
        """A senha do sudo desta sessão (a que deu certo nesta conexão), ou ``None``. Só na memória."""
        return self._senha_do_sudo

    def lembrar_senha_do_sudo(self, senha: str | None) -> None:
        """A senha que deu certo em outro uso do sudo (a conferência, a captura); ``None`` a esquece (a recusada)."""
        self._senha_do_sudo = senha

    def _corrigindo(self) -> bool:
        return self.correcao is not None and self.correcao.estado == "rodando"

    def acertar_relogio(self, senha: str | None = None, guardar: bool = False, automatica: bool = False) -> None:
        """Acerta o relógio da placa pelo deste computador, pelo sudo. Sem ``senha``: a da sessão, senão a do cofre;
        sem nenhuma, a correção fica ``precisa_da_senha`` (a interface pergunta e chama de novo com ela).
        ``guardar`` leva a senha que deu certo para o cofre. ``automatica``: o relógio a cada conexão."""
        conexao_ssh, cliente = self.conexao.conexao_ssh, self.conexao.cliente
        if conexao_ssh is None or self._corrigindo():
            return
        senha = senha or self._senha_do_sudo or self.conexao.senha_da_placa()
        enlace = self.conexao.enlace
        meia = enlace.latencia_ms / 2000 if enlace is not None else 0.0
        self.aviso_do_relogio = ""
        self._mudar_a_correcao(Correcao("relogio", "rodando", automatica=automatica))
        self._chamar("acertar o relógio", self._relogio_no_laco, conexao_ssh, cliente, senha, guardar, meia,
                     self.conexao.cofre, ao_terminar=lambda ch: self._acertou(ch, automatica))

    @staticmethod
    async def _relogio_no_laco(conexao_ssh, cliente, senha: str | None, guardar: bool, meia: float, obter_o_cofre):
        """Na thread do laço: a senha do cofre (sem uma da sessão), o acerto e a saúde de novo (o relógio novo)."""
        from sh_placa.correcoes import acertar_relogio

        cofre = obter_o_cofre()
        conta = conexao_ssh.destino.conta
        if senha is None:
            senha = await asyncio.to_thread(cofre.senha, conta)
            if senha is None:
                return None, None, None
        acertado = await acertar_relogio(conexao_ssh, senha, meia)
        aviso = ""
        if guardar:
            try:
                await asyncio.to_thread(cofre.guardar, conta, senha)
            except ErroDaPlaca as e:
                aviso = str(e)
        return acertado, await cliente.saude(), (senha, aviso)

    def _acertou(self, chamada: Chamada, automatica: bool) -> None:
        if chamada.estado == "concluida":
            acertado, saude, extra = chamada.resultado
            if acertado is None:
                if automatica:
                    self.aviso_do_relogio = ("O relógio não foi acertado sozinho: falta a senha do sudo (dê a senha "
                                             "no \"Acertar\" do relógio e guarde-a no cofre).")
                    self._mudar_a_correcao(None)
                    self.mudou.emit()
                else:
                    self._mudar_a_correcao(Correcao("relogio", "precisa_da_senha"))
                return
            senha, aviso = extra
            self._senha_do_sudo = senha
            self.relogio_acertado, self.relogio_acertado_em = acertado, time.time()
            self.saude, self.conferida_em = saude, time.time()
            depois = _agora(saude.relogio) if abs(acertado.erro_antes_s) >= 0.01 else ""
            mensagem = f"O relógio da placa {_antes(acertado.erro_antes_s)}{depois}."
            if aviso:
                mensagem += f" {aviso}"
            self._mudar_a_correcao(Correcao("relogio", "feita", mensagem, automatica))
            self.mudou.emit()
            return
        if chamada.estado == "falhou":
            from sh_placa.correcoes import ErroDoSudo

            e = chamada.excecao
            if isinstance(e, ErroDoSudo) and e.senha_recusada:
                self._senha_do_sudo = None
                if automatica:
                    self.aviso_do_relogio = ("O relógio não foi acertado sozinho: a placa recusou a senha do sudo "
                                             "guardada (dê a certa no \"Acertar\" do relógio).")
                    self._mudar_a_correcao(None)
                    self.mudou.emit()
                else:
                    self._mudar_a_correcao(Correcao("relogio", "senha_recusada", "A placa recusou a senha do sudo."))
                return
            self._mudar_a_correcao(Correcao("relogio", "falhou", chamada.erro, automatica))
            return
        self._mudar_a_correcao(None)

    def _relogio_respondido(self, acertar: bool) -> None:
        """A primeira conexão: o usuário permitiu acertar o relógio a cada conexão, e esta é a primeira."""
        if acertar and self.conexao.conectada and self.conexao.conexao_ssh is not None:
            self._falta_o_relogio = True
            self._continuar()

    def dispensar_a_correcao(self) -> None:
        """A mensagem da última correção foi vista."""
        if self.correcao is not None and self.correcao.estado != "rodando":
            self._mudar_a_correcao(None)

    def lembrar_acertar(self) -> bool | None:
        return self.conexao.lembrar_acertar_relogio()

    def permitir_acertar_a_cada_conexao(self, permitir: bool) -> None:
        """A permissão lembrada com a placa (o mesmo da pergunta da primeira conexão)."""
        serie = self.saude.serie if self.saude is not None else None
        if serie:
            from sh_placa import conhecidas

            try:
                preferencias.mudar_placas_conhecidas(
                    conhecidas.definir_relogio(preferencias.placas_conhecidas(), serie, permitir))
            except KeyError:
                log.warning("a placa %s não está entre as conhecidas: a permissão do relógio não foi lembrada", serie)
        self.mudou.emit()
