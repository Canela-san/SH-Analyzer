"""As placas dos testes da Aquisição na interface: servidores SSH do teste (``servidor_ssh.py``) num laço próprio, como
uma placa de verdade respondendo fora do laço da interface; o cofre de senhas num dicionário; e a fonte da descoberta
que acha um servidor, como o mDNS acharia uma placa na rede local."""

from __future__ import annotations

from servidor_ssh import ServidorSSH
from sh_placa.descoberta import Achado, Caminho
from sh_placa.destino import Destino
from sh_placa.laco import LacoAsyncio


class CofreFalso:
    """O cofre do sistema num dicionário (os testes não tocam o cofre de quem desenvolve)."""

    def __init__(self, **senhas):
        self.senhas = dict(senhas)
        self.guardadas: list[str] = []

    def senha(self, conta):
        return self.senhas.get(conta)

    def guardar(self, conta, senha):
        self.senhas[conta] = senha
        self.guardadas.append(conta)


class Placas:
    """Os servidores SSH do teste, num laço próprio: a placa responde enquanto a interface espera."""

    def __init__(self, pasta):
        self.pasta = pasta
        self.laco = LacoAsyncio("placas-do-teste")
        self.laco.iniciar()
        self.servidores: list[ServidorSSH] = []

    def nova(self, nome="placa", **opcoes) -> ServidorSSH:
        servidor = ServidorSSH(self.pasta / nome, **opcoes)
        self.laco.submeter(servidor.iniciar).resultado(10)
        self.servidores.append(servidor)
        return servidor

    def rodar(self, funcao, *args):
        return self.laco.submeter(funcao, *args).resultado(10)

    def parar(self, servidor: ServidorSSH) -> None:
        self.rodar(servidor.parar)
        self.servidores.remove(servidor)

    def fechar(self):
        for servidor in self.servidores:
            self.laco.submeter(servidor.parar).resultado(10)
        assert self.laco.parar()


def fonte_que_acha(servidor: ServidorSSH, nome: str = "bbb-teste"):
    """Uma fonte da descoberta que acha o servidor, como o mDNS acharia uma placa na rede local."""
    async def fonte(_conhecidas=()):
        return [Achado(Caminho("lan", Destino("127.0.0.1", servidor.porta), f"{nome}.local (mDNS)", 0.4),
                       impressao=servidor.impressao, nome=nome)]
    fonte.nome = "teste"
    return fonte
