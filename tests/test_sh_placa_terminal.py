"""O terminal da placa (``sh_placa/terminal.py``, F3.8), contra o servidor SSH do teste (um ``sh -i`` num PTY deste
computador): o tamanho pedido e o redimensionado chegam ao PTY, o que se digita volta, a gravação no arquivo do dia
(acrescentada, com o cabeçalho de cada sessão), o registro de atividade e o fim do shell. Sem placa."""

import asyncio
import re
import sys

import pytest

pytest.importorskip("asyncssh")
if not sys.platform.startswith("linux"):
    pytest.skip("o servidor do teste usa o PTY e o sh deste computador", allow_module_level=True)

from servidor_ssh import ServidorSSH  # noqa: E402
from sh_placa.chaves import ChaveDoAplicativo, HostsConhecidos  # noqa: E402
from sh_placa.conexao import ConexaoSSH, ErroDeConexao  # noqa: E402
from sh_placa.destino import Destino  # noqa: E402
from sh_placa.registro import RegistroDeAtividade  # noqa: E402
from sh_placa.terminal import SessaoDeTerminal  # noqa: E402

ESPERA_S = 10


def conexao(tmp_path, placa, registro):
    async def confiar(_d, _i):
        return True

    return ConexaoSSH(Destino("127.0.0.1", placa.porta), chave=ChaveDoAplicativo(tmp_path / "chaves"),
                      hosts=HostsConhecidos(tmp_path / "chaves" / "known_hosts"), registro=registro,
                      senha=placa.senha, confirmar_host=confiar)


class Tela:
    """O que chegou do terminal, com a espera por um trecho (sem as sequências de escape)."""

    def __init__(self):
        self.bruto = bytearray()
        self.chegou = asyncio.Event()

    def receber(self, dados: bytes) -> None:
        self.bruto += dados
        self.chegou.set()

    @property
    def texto(self) -> str:
        return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", self.bruto.decode(errors="replace"))

    async def esperar(self, padrao: str) -> re.Match:
        async def ate_chegar():
            while (achou := re.search(padrao, self.texto)) is None:
                self.chegou.clear()
                await self.chegou.wait()
            return achou

        return await asyncio.wait_for(ate_chegar(), ESPERA_S)


def test_o_tamanho_o_eco_e_o_fim(tmp_path):
    registro = RegistroDeAtividade()
    gravacao = tmp_path / "dados" / "lab" / "2026-11-16" / "terminal_bbb.txt"

    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            async with conexao(tmp_path, placa, registro) as c:
                tela = Tela()
                sessao = SessaoDeTerminal(c, 97, 31, ao_receber=tela.receber, gravacao=gravacao)
                rodando = asyncio.ensure_future(sessao.rodar())
                await tela.esperar(r"placa\$ ")
                sessao.escrever(b"stty size; echo $TERM\r")
                tamanho = (await tela.esperar(r"(\d+) (\d+)\r?\n(\S+)")).groups()
                sessao.redimensionar(120, 40)
                sessao.escrever(b"stty size\r")
                redimensionado = (await tela.esperar(r"40 120")).group(0)
                sessao.escrever(b"echo eco-$((6*7))\r")
                await tela.esperar(r"eco-42")
                sessao.escrever(b"exit 3\r")
                codigo = await asyncio.wait_for(rodando, ESPERA_S)
            return tamanho, redimensionado, codigo, tela.bruto

    tamanho, redimensionado, codigo, bruto = asyncio.run(cenario())
    assert tamanho == ("31", "97", "xterm-256color") and redimensionado == "40 120"
    assert codigo == 3
    gravado = gravacao.read_bytes()
    assert gravado.startswith(b"\n--- terminal da placa debian@127.0.0.1")
    assert gravado.endswith(bytes(bruto))                               # a saída inteira, como chegou
    descricoes = [e.descricao for e in registro.entradas if e.tipo == "conexao"]
    assert any(d.startswith("terminal aberto (xterm-256color, 97×31), gravado em ") for d in descricoes)
    assert "terminal fechado (o shell saiu com o código 3)" in descricoes


def test_a_gravacao_acrescenta_e_a_queda_fecha(tmp_path):
    registro = RegistroDeAtividade()
    gravacao = tmp_path / "terminal_bbb.txt"
    gravacao.write_bytes(b"de antes\n")

    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            c = conexao(tmp_path, placa, registro)
            await c.conectar()
            tela = Tela()
            sessao = SessaoDeTerminal(c, 80, 24, ao_receber=tela.receber, gravacao=gravacao)
            rodando = asyncio.ensure_future(sessao.rodar())
            await tela.esperar(r"placa\$ ")
            placa.derrubar()                                                # o cabo que solta
            codigo = await asyncio.wait_for(rodando, ESPERA_S)
            sessao.escrever(b"ninguem\r")                                   # depois do fim: nada, sem erro
            sessao.redimensionar(100, 30)
            await c.fechar()
            return codigo

    assert asyncio.run(cenario()) is None
    gravado = gravacao.read_bytes()
    assert gravado.startswith(b"de antes\n\n--- terminal da placa") and b"placa$ " in gravado
    assert "terminal fechado (a conexão caiu antes do fim do shell)" in [e.descricao for e in registro.entradas]


def test_fechar_na_interface(tmp_path):
    registro = RegistroDeAtividade()

    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            async with conexao(tmp_path, placa, registro) as c:
                tela = Tela()
                sessao = SessaoDeTerminal(c, 80, 24, ao_receber=tela.receber)
                rodando = asyncio.ensure_future(sessao.rodar())
                await tela.esperar(r"placa\$ ")
                sessao.fechar()
                codigo = await asyncio.wait_for(rodando, ESPERA_S)
                ainda = (await c.executar("echo viva")).saida                # a conexão segue
            return codigo, ainda

    assert asyncio.run(cenario()) == (None, "viva\n")
    descricoes = [e.descricao for e in registro.entradas if e.tipo == "conexao"]
    assert "terminal aberto (xterm-256color, 80×24)" in descricoes and "terminal fechado na interface" in descricoes


def test_sem_conexao(tmp_path):
    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            sessao = SessaoDeTerminal(conexao(tmp_path, placa, RegistroDeAtividade()), 80, 24, ao_receber=print)
            with pytest.raises(ErroDeConexao, match="conecte antes"):
                await sessao.rodar()

    asyncio.run(cenario())
