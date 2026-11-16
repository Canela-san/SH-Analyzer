"""As duas correções simples do diagnóstico (``sh_placa/correcoes.py``, F3.6), contra o servidor SSH do teste com o
sudo e o ``config-pin`` falsos: os pinos voltam ao modo da PRU (e o agente confere), o relógio é acertado pelo sudo
com a hora do computador, a senha errada é recusada sem rodar nada como root, e a senha do sudo não aparece em lugar
nenhum (o registro, os comandos, os argumentos do root, o log, a /dev/shm). Sem placa."""

import asyncio
import logging
import re
import time
from pathlib import Path

import pytest

asyncssh = pytest.importorskip("asyncssh")

from servidor_ssh import ServidorSSH  # noqa: E402
from sh_placa.agente import ClienteDoAgente, TransporteSSH  # noqa: E402
from sh_placa.chaves import ChaveDoAplicativo, HostsConhecidos  # noqa: E402
from sh_placa.conexao import ConexaoSSH  # noqa: E402
from sh_placa.correcoes import (  # noqa: E402
    ARQUIVO_DO_RELOGIO_SIMULADO,
    MODOS_DA_PRU,
    ErroDoSudo,
    acertar_relogio,
    comando_dos_pinos,
    corrigir_pinos,
    roteiro_do_relogio,
)
from sh_placa.destino import Destino  # noqa: E402
from sh_placa.registro import RegistroDeAtividade  # noqa: E402

SETUP = Path(__file__).resolve().parents[1] / "firmware" / "setup.sh"
SENHA_DO_SUDO = "senha-do-sudo-do-teste"


def conexao(tmp_path, placa: ServidorSSH, registro: RegistroDeAtividade) -> ConexaoSSH:
    async def confiar(_destino, _impressao):
        return True

    return ConexaoSSH(Destino("127.0.0.1", placa.porta), chave=ChaveDoAplicativo(tmp_path / "chaves"),
                      hosts=HostsConhecidos(tmp_path / "chaves" / "known_hosts"), registro=registro,
                      senha=placa.senha, confirmar_host=confiar)


def sobras_na_ram() -> set[str]:
    pasta = Path("/dev/shm")
    return {p.name for p in pasta.glob("sh-analyzer.*")} if pasta.is_dir() else set()


def test_os_pinos_sao_os_do_setup():
    """Os pinos e os modos, na ordem do ``firmware/setup.sh`` (o contrato: o setup e o "Corrigir" fazem o mesmo)."""
    linhas = re.findall(r"^config-pin (P\d_\d+) (\w+)", SETUP.read_text(encoding="utf-8"), re.MULTILINE)
    assert linhas == list(MODOS_DA_PRU.items())
    assert comando_dos_pinos(["P9_28", "P9_31"]) == "config-pin P9_31 pruout && config-pin P9_28 pruout"
    for errado in ([], ["P8_11"]):
        with pytest.raises(ValueError):
            comando_dos_pinos(errado)


def test_corrigir_os_pinos(tmp_path):
    registro = RegistroDeAtividade()

    async def cenario():
        async with ServidorSSH(tmp_path / "placa", cenario="pinos_errados") as placa:
            async with conexao(tmp_path, placa, registro) as c:
                cliente = ClienteDoAgente(TransporteSSH(c))
                antes = [p.codigo for p in (await cliente.saude()).diagnostico()]
                await corrigir_pinos(c, ["P9_28", "P9_31"])
                depois = [p.codigo for p in (await cliente.saude()).diagnostico()]
            return antes, depois, placa

    antes, depois, placa = asyncio.run(cenario())
    assert "pinos" in antes and "pinos" not in depois
    assert placa.comandos_de_root == []                               # o config-pin não precisa do sudo
    (pinos,) = [e for e in registro.entradas if e.descricao.startswith("pôr P9_28, P9_31 no modo da PRU")]
    assert pinos.comando == "config-pin P9_31 pruout && config-pin P9_28 pruout" and pinos.codigo == 0


def test_acertar_o_relogio_pelo_sudo(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    registro = RegistroDeAtividade()
    antes_na_ram = sobras_na_ram()

    async def cenario():
        async with ServidorSSH(tmp_path / "placa", senha_do_sudo=SENHA_DO_SUDO) as placa:
            async with conexao(tmp_path, placa, registro) as c:
                enviado = time.time()
                acertado = await acertar_relogio(c, SENHA_DO_SUDO, meia_ida_e_volta_s=0.0005)
                depois = time.time()
            return acertado, enviado, depois, placa

    acertado, enviado, depois, placa = asyncio.run(cenario())
    assert abs(acertado.erro_antes_s) < 0.5                           # o mesmo relógio: a placa simulada estava certa
    escrito = float((placa.raiz / ARQUIVO_DO_RELOGIO_SIMULADO).read_text())
    assert escrito == acertado.acertado_para and enviado <= escrito <= depois + 0.01
    assert "\n".join(placa.comandos_de_root).startswith("python3 -u -c import json, os, sys, time")
    (entrada,) = [e for e in registro.entradas if e.tipo == "comando"]
    assert entrada.comando == roteiro_do_relogio() and entrada.codigo == 0
    for texto in (registro.em_texto(), caplog.text, *placa.comandos, *placa.comandos_de_root):
        assert SENHA_DO_SUDO not in texto
    assert sobras_na_ram() == antes_na_ram                            # o askpass e a senha saíram da /dev/shm
    assert not (placa.home / ".sudo-validado").exists()               # o sudo -k no fim


def test_a_senha_errada_do_sudo(tmp_path):
    registro = RegistroDeAtividade()
    antes_na_ram = sobras_na_ram()

    async def cenario():
        async with ServidorSSH(tmp_path / "placa", senha_do_sudo=SENHA_DO_SUDO) as placa:
            async with conexao(tmp_path, placa, registro) as c:
                with pytest.raises(ErroDoSudo, match="recusou a senha do sudo") as erro:
                    await acertar_relogio(c, "errada")
                assert c.conectada
            return placa, erro.value

    placa, erro = asyncio.run(cenario())
    assert erro.senha_recusada and placa.comandos_de_root == []      # nada rodou como root
    assert not (placa.raiz / ARQUIVO_DO_RELOGIO_SIMULADO).exists()
    assert sobras_na_ram() == antes_na_ram
    (entrada,) = [e for e in registro.entradas if e.tipo == "comando"]
    assert entrada.codigo == 98 and "errada" not in registro.em_texto()
