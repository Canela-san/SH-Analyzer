"""O sistema da placa (``sh_placa/sistema.py``, a F6.7) na placa simulada: a senha trocada pelo ``chpasswd`` (a nova
vale para o sudo e para o SSH, e nunca aparece numa linha de comando), um serviço da imagem desligado e ligado de novo,
a limpeza do cartão (o cache do ``apt``, o diário guardado, as tarefas terminadas) e a partição expandida, que vale
depois do reinício."""

import asyncio

import pytest
from sh_placa import sistema


def test_a_senha_nova_conferida():
    assert sistema.conferir_a_senha_nova("") == "a senha nova está vazia"
    assert "quebra de linha" in sistema.conferir_a_senha_nova("abc\ndefgh")
    assert "6 caracteres" in sistema.conferir_a_senha_nova("abc")
    assert sistema.conferir_a_senha_nova("uma senha boa") is None
    with pytest.raises(ValueError):
        sistema.roteiro_do_servico("ssh.service; reboot", True)
    with pytest.raises(ValueError):
        sistema.roteiro_de_expandir("/opt/../bin/sh")


def test_a_senha_os_servicos_a_limpeza_e_a_particao_na_placa_simulada(tmp_path):
    pytest.importorskip("asyncssh")
    from sh_placa.agente import ClienteDoAgente, TransporteSSH
    from sh_placa.correcoes import ErroDoSudo
    from sh_placa.erros import ErroDeConexao
    from sh_placa.servidor_do_simulador import ServidorDoSimulador
    from test_sh_placa_simulador import entrar

    nova = "uma senha nova, longa"

    async def cenario():
        async with ServidorDoSimulador(tmp_path / "placa", "disco_cheio", vazao_bytes_s=None,
                                       tempo_do_boot_s=0.3) as placa:
            antiga = placa.senha_do_sudo
            async with entrar(placa) as c:
                cliente = ClienteDoAgente(TransporteSSH(c))
                antes = await cliente.chamar("sistema")
                await sistema.trocar_senha(c, antiga, nova)
                with pytest.raises(ErroDoSudo):                       # a antiga não vale mais
                    await sistema.ligar_servico(c, "bonescript-autorun.service", False, antiga)
                await sistema.ligar_servico(c, "bonescript-autorun.service", False, nova)
                desligado = await cliente.chamar("sistema")
                await sistema.ligar_servico(c, "bonescript-autorun.service", True, nova)
                await sistema.limpar(c, "apt", nova)
                await sistema.limpar(c, "diario", nova)
                apagadas = await sistema.limpar_as_tarefas(c)
                limpo = await cliente.chamar("sistema")
                dito = await sistema.expandir_a_particao(c, antes["cartao"]["script_de_expandir"], nova)
                ainda = await cliente.chamar("sistema")
                try:
                    await sistema.reiniciar(c, nova)
                except ErroDeConexao:
                    pass
                for _ in range(100):
                    if placa.reinicios:
                        break
                    await asyncio.sleep(0.1)
            async with entrar(placa) as c:
                depois = await ClienteDoAgente(TransporteSSH(c)).chamar("sistema")
            return placa, antes, desligado, limpo, apagadas, dito, ainda, depois

    placa, antes, desligado, limpo, apagadas, dito, ainda, depois = asyncio.run(cenario())
    servico = {s["unidade"]: s for s in desligado["servicos"]}["bonescript-autorun.service"]
    assert (servico["ativo"], servico["no_boot"]) == ("inactive", "disabled")
    assert {s["unidade"]: s for s in limpo["servicos"]}["bonescript-autorun.service"]["ativo"] == "active"
    o = antes["ocupacao"]
    assert o["apt"] == 91 * 1024 * 1024 and o["diario"] == 88 * 1024 * 1024 and o["tarefas"] > 0
    assert limpo["ocupacao"]["apt"] == 0 and limpo["ocupacao"]["diario"] == 8 * 1024 * 1024
    assert apagadas == 2 and limpo["ocupacao"]["tarefas"] in (0, None)
    assert antes["cartao"]["fora_bytes"] > 10 * 1024 ** 3 and "próximo boot" in dito
    assert ainda["cartao"]["fora_bytes"] == antes["cartao"]["fora_bytes"]          # só depois do boot
    assert depois["cartao"]["fora_bytes"] == 0
    for comando in placa.comandos:
        assert nova not in comando and placa.senha_do_sudo not in comando
