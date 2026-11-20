"""O sistema da placa conectada (docs/gui-plan.md, 11.10; a Fase 6): a inicialização (o ``/boot/uEnv.txt``, a F6.4) e
o reiniciar e o desligar (a F6.5). A conexão é do ``servicos/conexao_da_placa.py`` e a saúde, do
``servicos/saude_da_placa.py``; este serviço lê o que as páginas Inicialização e Sistema da Manutenção mostram e roda
o que elas pedem, no laço da placa (``servicos/placa.py``), mudando o estado só na thread da interface.

**O que ele lê** (quando a página aparece, e de novo depois de cada ação): a inicialização (o comando
``inicializacao`` do agente: o ``uEnv.txt`` com o hash, a linha do kernel deste boot, os overlays, os ``.dtbo`` da PRU
e as cópias que o assistente fez) com as mudanças propostas (``sh_placa/uenv.py``), ou o porquê de o assistente não
mexer no arquivo (:attr:`SistemaDaPlaca.uenv_estranho`); e o detalhe do sistema (o comando ``sistema``).

**A ação** (:attr:`SistemaDaPlaca.acao`, uma por vez): gravar o ``uEnv.txt`` (as mudanças marcadas, ou uma cópia
restaurada), reiniciar e desligar. Gravar pode terminar no reinício (o ``uEnv.txt`` vale no próximo boot). O reinício
e o desligamento avisam a conexão antes (``ConexaoDaPlaca.esperar``): a queda não conta como do cabo, e a ação fica
``esperando_a_placa`` até a placa voltar com o boot novo (``reiniciou``) ou sumir da rede (``desligou``: aí já pode
tirar da tomada). **A senha do sudo** segue a das correções: a da sessão, senão a da placa (a digitada para conectar),
senão a do cofre; sem nenhuma, ``precisa_da_senha``, e a recusada é ``senha_recusada``. Uma captura rodando faz o
reiniciar e o desligar recusarem (``captura_rodando``), a não ser que o usuário confirme o corte.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal
from sh_placa.agente import ErroDaPlaca
from shiboken6 import isValid

from .conexao_da_placa import ConexaoDaPlaca
from .placa import Chamada
from .saude_da_placa import SaudeDaPlaca

if TYPE_CHECKING:
    from sh_placa.uenv import Mudanca

log = logging.getLogger(__name__)

ESTADOS_DA_ACAO = ("rodando", "esperando_a_placa", "feita", "falhou", "precisa_da_senha", "senha_recusada",
                   "captura_rodando")
ENERGIAS = {"reiniciar": "reinicio", "desligar": "desligamento"}


@dataclass
class AcaoDoSistema:
    """A ação de agora (ou a última): o nome (``gravar_uenv``, ``restaurar_uenv``, ``reiniciar``, ``desligar``), o
    título, o estado (:data:`ESTADOS_DA_ACAO`) e o que ela fez (:attr:`detalhes`: a cópia do ``uEnv.txt``, o diff, as
    mudanças). ``energia``: ``"reiniciar"`` ou ``"desligar"`` no fim."""

    nome: str
    titulo: str
    estado: str = "rodando"
    mensagem: str = ""
    energia: str | None = None
    mesmo_capturando: bool = False
    detalhes: dict[str, Any] = field(default_factory=dict)
    comecou_em: float = field(default_factory=time.monotonic)
    pediu_em: float | None = None            # quando o reinício (ou o desligamento) foi pedido
    terminou_em: float | None = None
    refazer: Callable[[str | None, bool], None] | None = field(default=None, repr=False)   # a resposta do usuário

    @property
    def rodando(self) -> bool:
        return self.estado in ("rodando", "esperando_a_placa")

    @property
    def esperando_o_usuario(self) -> bool:
        return self.estado in ("precisa_da_senha", "senha_recusada", "captura_rodando")


class SistemaDaPlaca(QObject):
    mudou = Signal()                          # a inicialização ou o detalhe do sistema
    acaoMudou = Signal()
    acaoTerminou = Signal(object)             # a AcaoDoSistema no fim, feita ou não (o caderno)
    copiaLida = Signal(str, str)              # (o nome da cópia do uEnv.txt, o texto): para mostrar antes de restaurar

    def __init__(self, conexao: ConexaoDaPlaca, saude: SaudeDaPlaca, parent: QObject | None = None):
        super().__init__(parent)
        self.conexao, self.saude, self.servico = conexao, saude, conexao.servico
        self.inicializacao: dict | None = None
        self.propostas: list[Mudanca] = []
        self.uenv_estranho = ""                # o porquê de o assistente não mexer no uEnv.txt
        self.detalhe: dict | None = None
        self.detalhe_lido_em = 0.0                         # o time.monotonic() da leitura (a "Ligada há" que anda)
        self.internet: dict | None = None
        self.testando_internet = False
        self.lendo = False
        self.erro = ""
        self.acao: AcaoDoSistema | None = None
        self._sessao = 0
        self._chamadas: set[Chamada] = set()
        conexao.mudou.connect(self._conexao_mudou)
        conexao.reiniciou.connect(self._reiniciou)
        conexao.desligou.connect(self._desligou)
        conexao.quedaNaoVeio.connect(self._a_queda_nao_veio)

    # ------------------------------------------------------------------ a conexão

    def _conexao_mudou(self) -> None:
        c = self.conexao
        if c.estado == "conectada" and c.sessoes != self._sessao:
            self._sessao = c.sessoes
            self.inicializacao, self.detalhe, self.propostas, self.uenv_estranho, self.erro = None, None, [], "", ""
            self.internet, self.testando_internet = None, False
            if self.acao is not None and not self.acao.rodando:
                self.acao = None
                self.acaoMudou.emit()
            self.mudou.emit()
        elif c.estado in ("desconectada", "falhou", "bloqueada"):
            for chamada in list(self._chamadas):
                chamada.cancelar()
            self._chamadas.clear()
            self._sessao = 0
            self.inicializacao, self.detalhe, self.propostas, self.lendo = None, None, [], False
            a = self.acao
            desligou = c.desligada and a is not None and a.energia == "desligar"     # o desligou vem logo depois
            if a is not None and a.rodando and not desligou:
                if a.estado == "rodando":
                    self._terminar(a, "falhou", "a conexão com a placa caiu antes de a ação responder")
                elif c.estado == "desconectada":
                    self._terminar(a, "falhou", "a conexão foi fechada antes de a placa voltar")
                # no "falhou" e no "bloqueada" da espera, o quedaNaoVeio diz o porquê
            self.mudou.emit()

    def _chamar(self, nome: str, funcao, *args, ao_terminar) -> Chamada:
        chamada = self.servico.chamar(nome, funcao, *args, ao_terminar=lambda ch: self._terminou(ch, ao_terminar))
        self._chamadas.add(chamada)
        return chamada

    def _terminou(self, chamada: Chamada, ao_terminar) -> None:
        if not isValid(self) or chamada not in self._chamadas:
            return                               # o serviço foi apagado (a janela fechou), ou de outra conexão
        self._chamadas.discard(chamada)
        ao_terminar(chamada)

    # ------------------------------------------------------------------ ler

    def ler_se_preciso(self) -> None:
        if self.inicializacao is None and not self.lendo and self.conexao.estado == "conectada":
            self.ler()

    def ler(self) -> Chamada | None:
        """A inicialização (com as propostas) e o detalhe do sistema."""
        cliente = self.conexao.cliente
        if cliente is None or self.lendo or self.conexao.estado != "conectada":
            return None
        self.lendo, self.erro = True, ""
        self.mudou.emit()
        return self._chamar("ler a inicialização e o sistema da placa", self._ler_no_laco, cliente,
                            ao_terminar=self._leu)

    @staticmethod
    async def _ler_no_laco(cliente):
        inicializacao = await cliente.chamar("inicializacao")
        detalhe = await cliente.chamar("sistema")
        return inicializacao, detalhe

    @property
    def ligada_s(self) -> float | None:
        """Há quanto tempo a placa está ligada, agora: o do ``sistema`` lido, mais o que passou desde a leitura."""
        ligada = (self.detalhe or {}).get("ligada_s")
        return None if ligada is None else ligada + time.monotonic() - self.detalhe_lido_em

    def _leu(self, chamada: Chamada) -> None:
        from sh_placa import uenv

        self.lendo = False
        if chamada.estado == "concluida":
            self.inicializacao, self.detalhe = chamada.resultado
            self.detalhe_lido_em = time.monotonic()
            self.propostas, self.uenv_estranho = [], ""
            texto = self.texto_do_uenv
            if texto is None:
                self.uenv_estranho = "a placa não tem um /boot/uEnv.txt legível"
            else:
                try:
                    self.propostas = uenv.propor(texto, self.inicializacao.get("kernel"),
                                                 self.inicializacao.get("dtbos_da_pru") or [])
                except uenv.UenvEstranho as e:
                    self.uenv_estranho = str(e)
        elif chamada.estado == "falhou":
            self.erro = chamada.erro
        self.mudou.emit()

    @property
    def texto_do_uenv(self) -> str | None:
        return ((self.inicializacao or {}).get("uenv") or {}).get("texto")

    @property
    def sha_do_uenv(self) -> str | None:
        return ((self.inicializacao or {}).get("uenv") or {}).get("sha256")

    @property
    def copias_do_uenv(self) -> list[dict]:
        return list((self.inicializacao or {}).get("copias") or [])

    def novo_uenv(self, nomes) -> str | None:
        """O ``uEnv.txt`` com as mudanças ``nomes`` (para o diff na tela); ``None`` sem o lido."""
        from sh_placa import uenv

        texto = self.texto_do_uenv
        if texto is None or self.uenv_estranho:
            return None
        i = self.inicializacao or {}
        return uenv.aplicar(texto, set(nomes), i.get("kernel"), i.get("dtbos_da_pru") or [])

    def ler_copia(self, nome: str) -> Chamada | None:
        """Lê uma cópia do ``uEnv.txt`` (sai em ``copiaLida``), para a tela mostrar o diff antes de restaurá-la."""
        conexao_ssh = self.conexao.conexao_ssh
        if conexao_ssh is None:
            return None
        return self._chamar(f"ler a cópia {nome}", self._ler_copia_no_laco, conexao_ssh, nome,
                            ao_terminar=lambda ch: self._leu_copia(ch, nome))

    @staticmethod
    async def _ler_copia_no_laco(conexao_ssh, nome):
        from sh_placa.uenv import ler_copia

        return await ler_copia(conexao_ssh, nome)

    def _leu_copia(self, chamada: Chamada, nome: str) -> None:
        if chamada.estado == "concluida":
            self.copiaLida.emit(nome, chamada.resultado)
        elif chamada.estado == "falhou":
            self.erro = chamada.erro
            self.mudou.emit()

    # ------------------------------------------------------------------ as ações

    @property
    def ocupado(self) -> bool:
        return self.acao is not None and self.acao.rodando

    def _comecar(self, acao: AcaoDoSistema) -> bool:
        if self.ocupado or self.conexao.estado != "conectada" or self.conexao.conexao_ssh is None:
            return False
        self.acao = acao
        self.acaoMudou.emit()
        return True

    def _senha(self, senha: str | None) -> str | None:
        return senha or self.saude.senha_do_sudo or self.conexao.senha_da_placa()

    def _terminar(self, acao: AcaoDoSistema, estado: str, mensagem: str = "") -> None:
        acao.estado, acao.mensagem = estado, mensagem
        if estado in ("feita", "falhou"):
            acao.terminou_em = time.monotonic()
        self.acaoMudou.emit()
        if estado in ("feita", "falhou"):
            self.acaoTerminou.emit(acao)

    def dispensar(self) -> None:
        """O fim da última ação foi visto (ou a confirmação foi cancelada)."""
        if self.acao is not None and not self.acao.rodando:
            self.acao = None
            self.acaoMudou.emit()

    async def _com_a_senha(self, senha: str | None, guardar: bool, obter_o_cofre, funcao, *args):
        """Roda ``funcao(senha, *args)`` com a senha (a dada, senão a do cofre); ``None`` sem nenhuma. Guarda a senha
        no cofre, se pedido, depois que a placa a aceitou. Devolve ``(resultado, senha, aviso do cofre)``."""
        cofre = obter_o_cofre()
        conta = self.conexao.conexao_ssh.destino.conta if self.conexao.conexao_ssh is not None else ""
        if senha is None:
            senha = await asyncio.to_thread(cofre.senha, conta)
            if senha is None:
                return None
        resultado = await funcao(senha, *args)
        aviso = ""
        if guardar:
            try:
                await asyncio.to_thread(cofre.guardar, conta, senha)
            except ErroDaPlaca as e:
                aviso = str(e)
        return resultado, senha, aviso

    def _falhou(self, acao: AcaoDoSistema, chamada: Chamada) -> None:
        from sh_placa.correcoes import ErroDoSudo
        from sh_placa.sistema import CapturaRodando

        e = chamada.excecao
        if chamada.estado == "cancelada":
            self._terminar(acao, "falhou", "cancelada")
        elif isinstance(e, ErroDoSudo) and e.senha_recusada:
            self.saude.lembrar_senha_do_sudo(None)
            self._terminar(acao, "senha_recusada", "A placa recusou a senha do sudo.")
        elif isinstance(e, CapturaRodando):
            self._terminar(acao, "captura_rodando", str(e))
        else:
            self._terminar(acao, "falhou", chamada.erro)

    # ------------------------------------------------------------------ gravar o uEnv.txt

    def gravar_mudancas(self, nomes, energia: str | None = "reiniciar", senha: str | None = None,
                        guardar: bool = False, mesmo_capturando: bool = False) -> bool:
        """Grava o ``uEnv.txt`` com as mudanças ``nomes`` (a tela já confirmou o diff) e, com ``energia``, reinicia."""
        novo = self.novo_uenv(nomes)
        if novo is None or novo == self.texto_do_uenv:
            return False
        titulos = [m.titulo for m in self.propostas if m.nome in set(nomes)]
        return self._gravar(AcaoDoSistema("gravar_uenv", "Gravar o uEnv.txt", energia=energia,
                                          mesmo_capturando=mesmo_capturando, detalhes={"mudancas": titulos}),
                            novo, senha, guardar)

    def restaurar(self, nome: str, texto: str, energia: str | None = "reiniciar", senha: str | None = None,
                  guardar: bool = False, mesmo_capturando: bool = False) -> bool:
        """Grava a cópia ``nome`` (o ``texto`` lido por :meth:`ler_copia`) de volta no ``uEnv.txt``."""
        if texto == self.texto_do_uenv:
            return False
        return self._gravar(AcaoDoSistema("restaurar_uenv", "Restaurar o uEnv.txt", energia=energia,
                                          mesmo_capturando=mesmo_capturando, detalhes={"origem": nome}),
                            texto, senha, guardar)

    def repetir(self, senha: str | None = None, guardar: bool = False, mesmo_capturando: bool = False) -> bool:
        """A ação que parou esperando o usuário (a senha, a captura rodando), de novo com a resposta dele."""
        a = self.acao
        if a is None or not a.esperando_o_usuario:
            return False
        a.mesmo_capturando = a.mesmo_capturando or mesmo_capturando
        if a.refazer is not None and not a.detalhes.get("feito"):
            a.refazer(senha, guardar)
        elif a.refazer is not None:
            self._energia(a, senha, guardar)
        elif a.nome == "parar_ler_adc":
            self._parar_de_novo(a, senha, guardar)
        elif a.nome in ("reiniciar", "desligar") or a.detalhes.get("gravado"):
            self._energia(a, senha, guardar)
        else:
            self._gravar_de_novo(a, senha, guardar)
        return True

    def _gravar(self, acao: AcaoDoSistema, novo: str, senha: str | None, guardar: bool) -> bool:
        from sh_placa import uenv

        antes, sha = self.texto_do_uenv, self.sha_do_uenv
        if antes is None or sha is None:
            return False
        acao.detalhes.update(novo=novo, sha_lido=sha, diff=uenv.diff(antes, novo))
        if not self._comecar(acao):
            return False
        self._gravar_de_novo(acao, senha, guardar)
        return True

    def _gravar_de_novo(self, acao: AcaoDoSistema, senha: str | None, guardar: bool) -> None:
        from sh_placa import uenv

        conexao_ssh = self.conexao.conexao_ssh
        if conexao_ssh is None:
            self._terminar(acao, "falhou", "sem conexão com a placa")
            return
        acao.estado, acao.mensagem = "rodando", ""
        self.acaoMudou.emit()
        carimbo = time.strftime("%Y%m%d-%H%M%S")            # o relógio deste computador (o da placa pode errar)

        async def gravar(senha_):
            return await uenv.gravar(conexao_ssh, acao.detalhes["novo"], acao.detalhes["sha_lido"], senha_, carimbo)

        self._chamar("gravar o /boot/uEnv.txt", self._com_a_senha, self._senha(senha), guardar, self.conexao.cofre,
                     gravar, ao_terminar=lambda ch: self._gravou(ch, acao))

    def _gravou(self, chamada: Chamada, acao: AcaoDoSistema) -> None:
        if chamada.estado != "concluida":
            self._falhou(acao, chamada)
            if acao.estado == "falhou":
                self.ler()                       # o arquivo pode ter mudado (o hash): mostra o de agora
            return
        if chamada.resultado is None:
            self._terminar(acao, "precisa_da_senha", "A placa pede a senha do sudo (a do usuário dela): esta sessão "
                                                     "e o cofre do sistema não a têm.")
            return
        gravado, senha, aviso = chamada.resultado
        self.saude.lembrar_senha_do_sudo(senha)
        acao.detalhes.update(gravado=True, copia=gravado.copia, aviso_do_cofre=aviso)
        if acao.energia is None:
            self._terminar(acao, "feita", aviso)
            self.ler()
            self.saude.conferir()                # o "no próximo boot" do diagnóstico
            return
        self._energia(acao, senha, False)

    # ------------------------------------------------------------------ o ler_adc esquecido

    def parar_ler_adc(self, senha: str | None = None, guardar: bool = False) -> bool:
        """Para os ``ler_adc`` que rodam na placa (uma captura que esta janela não começou), como o Ctrl+C."""
        acao = AcaoDoSistema("parar_ler_adc", "Parar o ler_adc da placa")
        if not self._comecar(acao):
            return False
        self._parar_de_novo(acao, senha, guardar)
        return True

    def _parar_de_novo(self, acao: AcaoDoSistema, senha: str | None, guardar: bool) -> None:
        from sh_placa import sistema

        conexao_ssh = self.conexao.conexao_ssh
        if conexao_ssh is None:
            self._terminar(acao, "falhou", "sem conexão com a placa")
            return
        acao.estado, acao.mensagem = "rodando", ""
        self.acaoMudou.emit()

        async def parar(senha_):
            return await sistema.parar_ler_adc(conexao_ssh, senha_)

        self._chamar("parar o ler_adc da placa", self._com_a_senha, self._senha(senha), guardar, self.conexao.cofre,
                     parar, ao_terminar=lambda ch: self._parou(ch, acao))

    def _parou(self, chamada: Chamada, acao: AcaoDoSistema) -> None:
        if chamada.estado != "concluida":
            self._falhou(acao, chamada)
            return
        if chamada.resultado is None:
            self._terminar(acao, "precisa_da_senha", "A placa pede a senha do sudo (a do usuário dela): esta sessão "
                                                     "e o cofre do sistema não a têm.")
            return
        dito, senha, aviso = chamada.resultado
        self.saude.lembrar_senha_do_sudo(senha)
        acao.detalhes["dito"] = dito
        self._terminar(acao, "feita", aviso)

    # ------------------------------------------------------------------ as ações com o sudo (a F6.7)

    def _com_sudo(self, acao: AcaoDoSistema, descricao: str, funcao, senha: str | None, guardar: bool,
                  depois: Callable[[AcaoDoSistema, Any, str], None] | None = None) -> None:
        """Roda ``funcao(conexao_ssh, senha)`` com a senha do sudo (a da sessão, a da placa ou a do cofre) e termina a
        ação; ``depois(acao, resultado, senha)`` no lugar do "feita" (o reinício que vem depois, por exemplo). A senha
        recusada e a que falta param esperando o usuário (:meth:`repetir`)."""
        conexao_ssh = self.conexao.conexao_ssh
        if conexao_ssh is None:
            self._terminar(acao, "falhou", "sem conexão com a placa")
            return
        acao.refazer = lambda senha_, guardar_: self._com_sudo(acao, descricao, funcao, senha_, guardar_, depois)
        acao.estado, acao.mensagem = "rodando", ""
        self.acaoMudou.emit()

        async def rodar(senha_):
            return await funcao(conexao_ssh, senha_)

        self._chamar(descricao, self._com_a_senha, self._senha(senha), guardar, self.conexao.cofre, rodar,
                     ao_terminar=lambda ch: self._fez(ch, acao, depois))

    def _fez(self, chamada: Chamada, acao: AcaoDoSistema, depois) -> None:
        if chamada.estado != "concluida":
            self._falhou(acao, chamada)
            return
        if chamada.resultado is None:
            self._terminar(acao, "precisa_da_senha", "A placa pede a senha do sudo (a do usuário dela): esta sessão "
                                                     "e o cofre do sistema não a têm.")
            return
        resultado, senha, aviso = chamada.resultado
        self.saude.lembrar_senha_do_sudo(senha)
        acao.detalhes.update(resultado=resultado, feito=True)
        if depois is not None:
            depois(acao, resultado, senha)
            return
        self._terminar(acao, "feita", aviso)
        self.ler()

    def ligar_servico(self, unidade: str, ligar: bool, senha: str | None = None, guardar: bool = False) -> bool:
        """Liga (``enable --now``) ou desliga (``disable --now``) um serviço opcional da imagem."""
        from sh_placa import sistema

        servico = next((s for s in self.servicos if s.get("unidade") == unidade), None)
        if servico is None or servico.get("papel") != "opcional":
            return False                          # os necessários (o SSH, o dnsmasq do USB) não se desligam
        acao = AcaoDoSistema("servico", f"{'Ligar' if ligar else 'Desligar'} o {unidade}",
                             detalhes={"unidade": unidade, "ligar": ligar})
        if not self._comecar(acao):
            return False
        self._com_sudo(acao, f"{'ligar' if ligar else 'desligar'} o {unidade}",
                       lambda c, s: sistema.ligar_servico(c, unidade, ligar, s), senha, guardar)
        return True

    def limpar(self, qual: str, senha: str | None = None, guardar: bool = False) -> bool:
        """Limpa ``qual`` do cartão (``"tarefas"``, ``"diario"``, ``"apt"``); o liberado vai em ``detalhes``."""
        from sh_placa import sistema

        if qual not in sistema.LIMPEZAS:
            return False
        antes = (self.detalhe or {}).get("ocupacao", {}).get(qual)
        acao = AcaoDoSistema("limpar", f"Limpar {sistema.LIMPEZAS[qual]}", detalhes={"qual": qual, "antes": antes})
        if not self._comecar(acao):
            return False
        if qual == "tarefas":                     # sem o sudo: as tarefas são do usuário
            acao.estado = "rodando"
            self.acaoMudou.emit()
            conexao_ssh = self.conexao.conexao_ssh
            self._chamar("limpar as tarefas terminadas", sistema.limpar_as_tarefas, conexao_ssh,
                         ao_terminar=lambda ch: self._limpou_as_tarefas(ch, acao))
            return True
        self._com_sudo(acao, f"limpar {sistema.LIMPEZAS[qual]}", lambda c, s: sistema.limpar(c, qual, s), senha,
                       guardar)
        return True

    def _limpou_as_tarefas(self, chamada: Chamada, acao: AcaoDoSistema) -> None:
        if chamada.estado != "concluida":
            self._falhou(acao, chamada)
            return
        acao.detalhes.update(resultado=chamada.resultado, feito=True)
        self._terminar(acao, "feita")
        self.ler()

    def expandir_a_particao(self, energia: str | None = "reiniciar", senha: str | None = None,
                            guardar: bool = False) -> bool:
        """A partição da raiz até o fim do cartão (o script da imagem); o sistema de arquivos cresce no boot seguinte,
        e, com ``energia``, a placa reinicia logo."""
        from sh_placa import sistema

        script = ((self.detalhe or {}).get("cartao") or {}).get("script_de_expandir")
        if not script:
            return False
        acao = AcaoDoSistema("expandir", "Expandir a partição", energia=energia,
                             detalhes={"fora": ((self.detalhe or {}).get("cartao") or {}).get("fora_bytes")})

        def depois(acao_, dito, senha_):
            acao_.detalhes["dito"] = dito
            if acao_.energia is None:
                self._terminar(acao_, "feita")
                self.ler()
            else:
                self._energia(acao_, senha_, False)

        if not self._comecar(acao):
            return False
        self._com_sudo(acao, "expandir a partição", lambda c, s: sistema.expandir_a_particao(c, script, s), senha,
                       guardar, depois)
        return True

    def trocar_senha(self, nova: str, senha: str | None = None, guardar: bool = False) -> bool:
        """Troca a senha do usuário da placa (a do SSH e a do sudo, daí em diante). A de agora é a do sudo de sempre
        (a da sessão, a da placa, a do cofre, ou ``senha``); a nova passa a valer na sessão e vai para o cofre se ele
        tinha a antiga ou se ``guardar``."""
        from sh_placa import sistema

        if sistema.conferir_a_senha_nova(nova) is not None or self.conexao.conexao_ssh is None:
            return False
        conexao_ssh = self.conexao.conexao_ssh
        conta, usuario = conexao_ssh.destino.conta, conexao_ssh.destino.usuario
        obter_o_cofre = self.conexao.cofre
        acao = AcaoDoSistema("trocar_senha", "Trocar a senha da placa", detalhes={"usuario": usuario})

        async def trocar(c, senha_):
            await sistema.trocar_senha(c, senha_, nova, usuario)
            cofre = obter_o_cofre()
            no_cofre = await asyncio.to_thread(cofre.senha, conta) is not None
            aviso = ""
            if guardar or no_cofre:
                try:
                    await asyncio.to_thread(cofre.guardar, conta, nova)
                except ErroDaPlaca as e:
                    aviso = str(e)
            return guardar or no_cofre, aviso

        def depois(acao_, resultado, _senha_antiga):
            no_cofre, aviso = resultado
            self.saude.lembrar_senha_do_sudo(nova)
            self.conexao.senha_trocada(nova)
            acao_.detalhes.update(no_cofre=no_cofre, resultado=None)
            self._terminar(acao_, "feita", aviso)

        if not self._comecar(acao):
            return False
        self._com_sudo(acao, "trocar a senha da placa", trocar, senha, False, depois)
        return True

    @property
    def servicos(self) -> list[dict]:
        return list((self.detalhe or {}).get("servicos") or [])

    def testar_internet(self) -> Chamada | None:
        """Se a placa alcança a internet (o ``apt`` e o NTP precisam): o resultado em :attr:`internet`."""
        cliente = self.conexao.cliente
        if cliente is None or self.testando_internet:
            return None
        self.testando_internet = True
        self.mudou.emit()
        return self._chamar("testar a internet da placa", cliente.chamar, "internet", ao_terminar=self._testou)

    def _testou(self, chamada: Chamada) -> None:
        self.testando_internet = False
        self.internet = chamada.resultado if chamada.estado == "concluida" else {"erro": chamada.erro}
        self.mudou.emit()

    # ------------------------------------------------------------------ reiniciar e desligar

    def reiniciar(self, senha: str | None = None, guardar: bool = False, mesmo_capturando: bool = False) -> bool:
        acao = AcaoDoSistema("reiniciar", "Reiniciar a placa", energia="reiniciar", mesmo_capturando=mesmo_capturando)
        if not self._comecar(acao):
            return False
        self._energia(acao, senha, guardar)
        return True

    def desligar(self, senha: str | None = None, guardar: bool = False, mesmo_capturando: bool = False) -> bool:
        acao = AcaoDoSistema("desligar", "Desligar a placa", energia="desligar", mesmo_capturando=mesmo_capturando)
        if not self._comecar(acao):
            return False
        self._energia(acao, senha, guardar)
        return True

    def _energia(self, acao: AcaoDoSistema, senha: str | None, guardar: bool) -> None:
        from sh_placa import sistema

        conexao_ssh = self.conexao.conexao_ssh
        if conexao_ssh is None or self.conexao.estado != "conectada":
            self._terminar(acao, "falhou", "sem conexão com a placa")
            return
        acao.estado, acao.mensagem = "rodando", ""
        self.acaoMudou.emit()
        self.conexao.esperar(ENERGIAS[acao.energia])       # antes do comando: a queda vem logo depois dele
        acao.pediu_em = time.monotonic()
        funcao = sistema.reiniciar if acao.energia == "reiniciar" else sistema.desligar

        async def pedir(senha_):
            from sh_placa.erros import ErroDeConexao

            try:
                await funcao(conexao_ssh, senha_, mesmo_capturando=acao.mesmo_capturando)
            except ErroDeConexao:
                return "caiu"                    # a queda chegou antes da resposta: o pedido foi
            return "pedido"

        self._chamar(sistema.ACOES["reboot" if acao.energia == "reiniciar" else "poweroff"], self._com_a_senha,
                     self._senha(senha), guardar, self.conexao.cofre, pedir,
                     ao_terminar=lambda ch: self._pediu_energia(ch, acao))

    def _pediu_energia(self, chamada: Chamada, acao: AcaoDoSistema) -> None:
        if chamada.estado == "concluida" and chamada.resultado is not None:
            _r, senha, aviso = chamada.resultado
            self.saude.lembrar_senha_do_sudo(senha)
            if acao.estado == "rodando":        # a conexão pode já ter dito que voltou (o simulador é rápido)
                acao.estado = "esperando_a_placa"
                acao.detalhes["aviso_do_cofre"] = aviso
                self.acaoMudou.emit()
            return
        self.conexao.esperar(None)               # o pedido não foi: nenhuma queda é esperada
        if chamada.estado == "concluida":
            self._terminar(acao, "precisa_da_senha", "A placa pede a senha do sudo (a do usuário dela): esta sessão "
                                                     "e o cofre do sistema não a têm.")
            return
        self._falhou(acao, chamada)

    def _reiniciou(self) -> None:
        a = self.acao
        if a is None or a.energia != "reiniciar" or not a.rodando:
            return
        voltou_em = time.monotonic() - a.pediu_em if a.pediu_em is not None else None
        a.detalhes["voltou_em_s"] = voltou_em
        self._terminar(a, "feita", a.detalhes.get("aviso_do_cofre", ""))
        self.ler()

    def _desligou(self) -> None:
        a = self.acao
        if a is None or a.energia != "desligar" or not a.rodando:
            return
        a.detalhes["aviso"] = self.conexao.aviso_do_desligamento
        self._terminar(a, "feita", self.conexao.aviso_do_desligamento)

    def _a_queda_nao_veio(self, motivo: str) -> None:
        a = self.acao
        if a is None or a.energia is None or ENERGIAS[a.energia] != motivo or not a.rodando:
            return
        c = self.conexao
        if c.estado == "conectada":
            texto = ("a placa não reiniciou: ela continua ligada, no mesmo boot" if motivo == "reinicio" else
                     "a placa não desligou: ela continua respondendo")
        else:
            texto = c.motivo or "a placa não voltou"
        self._terminar(a, "falhou", texto)
