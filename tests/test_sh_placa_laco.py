"""O laço ``asyncio`` do ``sh_placa`` (``sh_placa/laco.py``, F3.1): a corrotina roda na thread dele, o resultado e o
erro chegam a quem espera, o cancelamento só termina depois da limpeza da corrotina, e parar não deixa thread. Sem
Qt e sem rede."""

import asyncio
import concurrent.futures
import logging
import threading

import pytest
from sh_placa.agente import ErroDaPlaca
from sh_placa.laco import NOME_DA_THREAD, LacoAsyncio


def threads_do_laco() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == NOME_DA_THREAD]


@pytest.fixture
def laco():
    laco = LacoAsyncio()
    laco.iniciar()
    yield laco
    assert laco.parar()
    assert not threads_do_laco()


def test_a_corrotina_roda_na_thread_do_laco_e_devolve_o_resultado(laco):
    async def dobro(x):
        await asyncio.sleep(0)
        return threading.current_thread().name, 2 * x

    fins = []
    execucao = laco.submeter(dobro, 21, ao_terminar=lambda e: fins.append(threading.current_thread().name))
    assert execucao.resultado(5) == (NOME_DA_THREAD, 42)
    assert execucao.feita() and not execucao.cancelada() and execucao.excecao() is None
    assert fins == [NOME_DA_THREAD]                     # o ao_terminar roda no laço, uma vez


def test_o_erro_chega_a_quem_espera(laco):
    async def falha():
        raise ErroDaPlaca("a placa não respondeu")

    async def chamada_errada(x):                         # chamada sem o argumento: falha antes de ter corrotina
        return x

    execucao = laco.submeter(falha)
    with pytest.raises(ErroDaPlaca, match="não respondeu"):
        execucao.resultado(5)
    assert isinstance(execucao.excecao(), ErroDaPlaca)
    with pytest.raises(TypeError):
        laco.submeter(chamada_errada).resultado(5)


def test_o_cancelamento_termina_depois_da_limpeza_da_corrotina(laco):
    """O fim chega quando a corrotina parou: a limpeza dela (um ``await`` no ``finally``) já rodou."""
    comecou, passos = threading.Event(), []

    async def espera_para_sempre():
        comecou.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.05)                    # fechar o canal, apagar o arquivo pela metade
            passos.append("limpou")

    fins = []
    execucao = laco.submeter(espera_para_sempre, ao_terminar=lambda e: fins.append(list(passos)))
    assert comecou.wait(5)
    execucao.cancelar()
    with pytest.raises(concurrent.futures.CancelledError):
        execucao.resultado(5)
    assert execucao.cancelada() and passos == ["limpou"] and fins == [["limpou"]]
    execucao.cancelar()                                   # depois do fim, não faz nada


def test_cancelar_logo_depois_de_submeter_nao_roda_a_corrotina(laco):
    rodou = []

    async def marca():
        rodou.append(True)

    segurando, trava = threading.Event(), threading.Event()

    async def segura_o_laco():                            # bloqueia a thread do laço (sem await)
        segurando.set()
        trava.wait(5)

    laco.submeter(segura_o_laco)
    assert segurando.wait(5)
    execucao = laco.submeter(marca)                       # a criação e o cancelamento entram juntos na fila,
    execucao.cancelar()                                   # antes do primeiro passo da corrotina
    trava.set()
    with pytest.raises(concurrent.futures.CancelledError):
        execucao.resultado(5)
    assert rodou == []


def test_parar_cancela_o_que_roda_e_nao_deixa_thread():
    laco = LacoAsyncio()
    laco.iniciar()
    laco.iniciar()                                        # rodando, não sobe outra
    assert laco.rodando and len(threads_do_laco()) == 1
    comecou = threading.Event()

    async def espera():
        comecou.set()
        await asyncio.Event().wait()

    execucao = laco.submeter(espera)
    assert comecou.wait(5)
    assert laco.parar()
    assert execucao.cancelada() and not laco.rodando and not threads_do_laco()
    with pytest.raises(RuntimeError, match="não está rodando"):
        laco.submeter(espera)
    assert laco.parar()                                   # parado, parar de novo não faz nada

    with LacoAsyncio() as outro:                          # e um laço novo depois do outro
        assert outro.submeter(asyncio.sleep, 0, "de novo").resultado(5) == "de novo"
    assert not threads_do_laco()


def test_parar_espera_a_corrotina_lenta_e_avisa_se_passa_do_prazo(caplog):
    laco = LacoAsyncio()
    laco.iniciar()
    comecou = threading.Event()

    async def limpeza_lenta():
        comecou.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.shield(asyncio.sleep(0.4))

    execucao = laco.submeter(limpeza_lenta)
    assert comecou.wait(5)
    (thread,) = threads_do_laco()
    with caplog.at_level(logging.WARNING, logger="sh_placa.laco"):
        assert laco.parar(espera_s=0.05) is False
    assert "não parou" in caplog.text and not laco.rodando
    thread.join(5)                                        # ela termina sozinha, e a execução fica cancelada
    assert not thread.is_alive() and execucao.cancelada()


def test_uma_falha_fora_de_uma_execucao_vai_para_o_log(laco, caplog):
    def callback_com_defeito():
        raise ValueError("defeito num callback")

    async def agenda():
        asyncio.get_running_loop().call_soon(callback_com_defeito)
        await asyncio.sleep(0.01)

    def ouvinte_com_defeito(_execucao):
        raise ZeroDivisionError("defeito no ouvinte")

    with caplog.at_level(logging.ERROR, logger="sh_placa.laco"):
        laco.submeter(agenda).resultado(5)
        laco.submeter(asyncio.sleep, 0, ao_terminar=ouvinte_com_defeito).resultado(5)
        assert laco.submeter(asyncio.sleep, 0, "o laço segue").resultado(5) == "o laço segue"
    assert "defeito num callback" in caplog.text and "defeito no ouvinte" in caplog.text


def test_parar_de_dentro_do_laco_e_recusado(laco):
    async def parar_a_si_mesmo():
        laco.parar()

    with pytest.raises(RuntimeError, match="a si mesmo"):
        laco.submeter(parar_a_si_mesmo).resultado(5)


def test_a_resposta_de_fora_chega_a_corrotina_que_espera(laco):
    """A pergunta ao usuário: a corrotina espera um futuro do laço, e a resposta vem de outra thread (a da
    interface) pelo ``agendar``. Com o laço parado, nada roda."""
    futuros = concurrent.futures.Future()

    async def pergunta():
        futuro = asyncio.get_running_loop().create_future()
        futuros.set_result(futuro)
        return await futuro, threading.current_thread().name

    execucao = laco.submeter(pergunta)
    futuro = futuros.result(5)
    assert laco.agendar(futuro.set_result, "sim")
    assert execucao.resultado(5) == ("sim", NOME_DA_THREAD)
    parado = LacoAsyncio()
    assert parado.agendar(print, "nunca") is False
