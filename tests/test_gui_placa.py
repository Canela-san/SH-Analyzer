"""A ponte entre a interface e o ``sh_placa`` (``servicos/placa.py``, F3.1): o resultado e o erro chegam na thread da
interface, o estado só muda lá, o cancelamento termina depois da limpeza da corrotina, e fechar a janela não deixa a
thread do laço. Sem tela e sem placa."""

import asyncio
import threading

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from dialogos_falsos import DialogosFalsos  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.servicos import placa as ponte  # noqa: E402
from sh_analyzer_gui.servicos.placa import ServicoDaPlaca  # noqa: E402
from sh_placa.agente import ErroDaPlaca  # noqa: E402
from sh_placa.laco import NOME_DA_THREAD  # noqa: E402


def threads_do_laco() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == NOME_DA_THREAD]


@pytest.fixture
def servico(qapp):
    s = ServicoDaPlaca()
    yield s
    assert s.encerrar()
    assert not threads_do_laco()


@pytest.fixture
def relatados(monkeypatch):
    erros = []
    monkeypatch.setattr(ponte, "relatar", lambda excecao, onde="": erros.append((excecao, onde)))
    return erros


def test_o_resultado_chega_na_thread_da_interface(servico, qtbot):
    async def onde_rodou(x):
        await asyncio.sleep(0)
        return threading.current_thread().name, x

    assert not threads_do_laco()                          # a thread nasce na primeira chamada
    vistos = []

    def ao_terminar(chamada):
        vistos.append((threading.current_thread() is threading.main_thread(), chamada.estado,
                       chamada in servico.ativas))

    entraram = []
    servico.chamadaEntrou.connect(entraram.append)
    with qtbot.waitSignal(servico.chamadaSaiu, timeout=5000):
        chamada = servico.chamar("versão", onde_rodou, 7, ao_terminar=ao_terminar)
        assert chamada.ativa and servico.ativas == (chamada,) and entraram == [chamada]
    assert chamada.resultado == (NOME_DA_THREAD, 7) and chamada.estado == "concluida"
    assert vistos == [(True, "concluida", False)]         # na thread da interface, já fora das ativas


def test_o_estado_so_muda_quando_o_aviso_chega(servico, qtbot):
    """A corrotina terminou no laço, mas a chamada continua ``rodando`` até a fila de eventos da interface andar:
    ninguém a vê terminada antes do ``terminou``."""
    async def rapida():
        return "pronto"

    chamada = servico.chamar("rápida", rapida)
    chamada._execucao.resultado(5)                         # pronta no laço; a fila da interface ainda não andou
    assert chamada.estado == "rodando" and chamada.resultado is None
    qtbot.waitUntil(lambda: chamada.estado == "concluida", timeout=5000)
    assert chamada.resultado == "pronto"


def test_o_erro_da_placa_fica_na_chamada_e_o_defeito_vai_para_o_relator(servico, qtbot, relatados):
    async def placa_muda():
        raise ErroDaPlaca("a placa não respondeu em 20 s")

    async def sem_rede():
        raise ConnectionRefusedError("conexão recusada")

    async def defeito():
        raise KeyError("campo")

    chamadas = []
    for nome, funcao in (("estado", placa_muda), ("conectar", sem_rede), ("saúde", defeito)):
        with qtbot.waitSignal(servico.chamadaSaiu, timeout=5000):
            chamadas.append(servico.chamar(nome, funcao))
    assert [(c.estado, c.inesperado) for c in chamadas] == [("falhou", False)] * 2 + [("falhou", True)]
    assert chamadas[0].erro == "a placa não respondeu em 20 s" and chamadas[1].erro == "conexão recusada"
    assert chamadas[2].erro == "erro inesperado (KeyError: 'campo')"
    assert [(type(e), onde) for e, onde in relatados] == [(KeyError, "na chamada 'saúde' à placa")]


def test_cancelar_termina_depois_da_limpeza(servico, qtbot):
    comecou, passos = threading.Event(), []

    async def transferencia():
        comecou.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.05)                     # o arquivo pela metade, apagado
            passos.append("limpou")

    chamada = servico.chamar("transferir", transferencia)
    assert comecou.wait(5)
    with qtbot.waitSignal(chamada.terminou, timeout=5000):
        chamada.cancelar()
    assert chamada.estado == "cancelada" and passos == ["limpou"] and not servico.ativas
    chamada.cancelar()                                     # depois do fim, não faz nada


def test_encerrar_cancela_e_nao_deixa_thread(qapp, qtbot):
    servico = ServicoDaPlaca()
    comecou = threading.Event()

    async def espera():
        comecou.set()
        await asyncio.Event().wait()

    chamada = servico.chamar("espera", espera)
    assert comecou.wait(5) and len(threads_do_laco()) == 1
    assert servico.encerrar()
    assert not threads_do_laco()
    qtbot.waitUntil(lambda: chamada.estado == "cancelada", timeout=5000)

    rodou = []

    async def marca():
        rodou.append(True)

    depois = servico.chamar("depois", marca)               # depois de encerrar, nada roda
    qtbot.wait(50)
    assert depois.estado == "cancelada" and rodou == [] and not threads_do_laco()


def test_fechar_a_janela_derruba_o_laco(qapp, config_limpa, qtbot):
    criar_aplicacao([], tema="escuro")
    janela = JanelaPrincipal()
    janela.controle.dialogos = DialogosFalsos()
    janela.show()
    qtbot.waitExposed(janela)
    comecou = threading.Event()

    async def espera():
        comecou.set()
        await asyncio.Event().wait()

    janela.placa.chamar("espera", espera)
    assert comecou.wait(5) and threads_do_laco()
    janela.close()
    assert not threads_do_laco()
    janela.deleteLater()
