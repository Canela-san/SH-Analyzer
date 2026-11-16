"""Os arquivos da placa no computador (``sh_placa/sftp.py``, F3.7), contra o servidor SSH do teste (o SFTP do
asyncssh sobre a árvore falsa): o arquivo idêntico, a queda no meio e a retomada do ponto em que parou, o arquivo que
mudou na placa entre as tentativas, a conferência da v9 pelo CRC das amostras e a de antes pelo SHA-256, a cópia
corrompida, a espera enquanto há captura rodando, o apagar e o índice das cópias. Sem placa."""

import asyncio
import shutil
import subprocess
import sys

import numpy as np
import pytest

pytest.importorskip("asyncssh")

from capturas_sinteticas import escrever_bin  # noqa: E402
from servidor_ssh import ServidorSSH  # noqa: E402
from sh_placa.chaves import ChaveDoAplicativo, HostsConhecidos  # noqa: E402
from sh_placa.conexao import ConexaoSSH, ErroDeConexao  # noqa: E402
from sh_placa.destino import Destino  # noqa: E402
from sh_placa.registro import RegistroDeAtividade  # noqa: E402
from sh_placa.sftp import (  # noqa: E402
    SUFIXO_PARCIAL,
    CopiaLocal,
    IndiceDeCopias,
    OrigemSSH,
    apagar,
    baixar,
    conferir,
    esperar_sem_captura,
)


def captura(pasta, nome="rede.bin", amostras=1 << 20, versao=9):
    """Uma captura sintética de 2 canais (4 MiB com 2^20 amostras por canal)."""
    t = np.arange(amostras) / 200_000
    return escrever_bin(pasta / nome, [np.sin(2 * np.pi * 60 * t), 0.3 * np.sin(2 * np.pi * 9e3 * t)],
                        fs_total=400_000, versao=versao)


def conexao(tmp_path, placa, registro):
    async def confiar(_d, _i):
        return True

    return ConexaoSSH(Destino("127.0.0.1", placa.porta), chave=ChaveDoAplicativo(tmp_path / "chaves"),
                      hosts=HostsConhecidos(tmp_path / "chaves" / "known_hosts"), registro=registro,
                      senha=placa.senha, confirmar_host=confiar)


def firmware(placa):
    return placa.home / "firmware"


def test_baixar_e_conferir_a_v9(tmp_path):
    registro = RegistroDeAtividade()

    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            original = captura(firmware(placa))
            local = tmp_path / "dados" / "lab" / "rede.bin"
            progresso = []
            async with conexao(tmp_path, placa, registro) as c:
                origem = OrigemSSH(c)
                tamanho = await baixar(origem, str(original), local, ao_progredir=lambda t, n: progresso.append(t))
                resultado = await conferir(origem, str(original), local)
            return original, local, tamanho, progresso, resultado

    original, local, tamanho, progresso, resultado = asyncio.run(cenario())
    assert local.read_bytes() == original.read_bytes() and tamanho == original.stat().st_size
    assert progresso == sorted(progresso) and progresso[-1] == tamanho
    assert int(local.stat().st_mtime) == int(original.stat().st_mtime)            # a data da placa
    assert not list(local.parent.glob(f"*{SUFIXO_PARCIAL}*"))
    assert (resultado.ok, resultado.como) == (True, "crc32")
    (entrada,) = [e for e in registro.entradas if e.descricao.startswith("baixar rede.bin")]
    assert entrada.codigo == 0 and entrada.comando == f"sftp get {original}"


def test_a_queda_no_meio_e_a_retomada(tmp_path):
    registro = RegistroDeAtividade()

    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            original = captura(firmware(placa), amostras=1 << 21)          # 8 MiB
            local = tmp_path / "copia" / "rede.bin"
            c = conexao(tmp_path, placa, registro)
            await c.conectar()

            def derrubar_no_meio(transferidos, total):
                if transferidos > total // 3:
                    placa.derrubar()                                        # o cabo que solta

            with pytest.raises(ErroDeConexao, match="caiu"):
                await baixar(OrigemSSH(c), str(original), local, ao_progredir=derrubar_no_meio, em_paralelo=2,
                             bloco=64 * 1024)
            parcial = local.with_name(local.name + SUFIXO_PARCIAL)
            ja = parcial.stat().st_size
            await c.conectar()                                              # o cabo voltou
            primeiro = []
            await baixar(OrigemSSH(c), str(original), local,
                         ao_progredir=lambda t, n: primeiro.append(t) if not primeiro else None)
            await c.fechar()
            return original, local, ja, primeiro[0]

    original, local, ja, primeiro = asyncio.run(cenario())
    assert 0 < ja < original.stat().st_size and primeiro > ja               # continuou de onde parou
    assert local.read_bytes() == original.read_bytes()
    descricoes = [e for e in registro.entradas if e.descricao.startswith("baixar rede.bin")]
    assert descricoes[0].codigo is None and "ficam para retomar" in descricoes[0].falha
    assert "retomando de" in descricoes[1].descricao and descricoes[1].codigo == 0


def test_o_arquivo_que_mudou_na_placa_comeca_de_novo(tmp_path):
    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            original = captura(firmware(placa))
            local = tmp_path / "copia" / "rede.bin"
            parcial = local.with_name(local.name + SUFIXO_PARCIAL)
            local.parent.mkdir()
            parcial.write_bytes(b"lixo de outra versao do arquivo" * 100)
            parcial.with_name(parcial.name + ".json").write_text('{"remoto": "outro", "bytes": 1, "modificado": 0}')
            async with conexao(tmp_path, placa, RegistroDeAtividade()) as c:
                await baixar(OrigemSSH(c), str(original), local)
            return original, local

    original, local = asyncio.run(cenario())
    assert local.read_bytes() == original.read_bytes()


def test_a_copia_corrompida_e_a_v8_pelo_sha256(tmp_path):
    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            v9 = captura(firmware(placa))
            v8 = captura(firmware(placa), "antiga.bin", amostras=1 << 16, versao=8)
            async with conexao(tmp_path, placa, RegistroDeAtividade()) as c:
                origem = OrigemSSH(c)
                copia_v9, copia_v8 = tmp_path / "v9.bin", tmp_path / "v8.bin"
                await baixar(origem, str(v9), copia_v9)
                await baixar(origem, str(v8), copia_v8)
                certa_v8 = await conferir(origem, str(v8), copia_v8)
                for copia in (copia_v9, copia_v8):
                    dados = bytearray(copia.read_bytes())
                    dados[-100] ^= 0xFF                                     # um bit trocado nas amostras
                    copia.write_bytes(dados)
                errada_v9 = await conferir(origem, str(v9), copia_v9)
                errada_v8 = await conferir(origem, str(v8), copia_v8)
                copia_v9.write_bytes(copia_v9.read_bytes()[:-10])
                curta = await conferir(origem, str(v9), copia_v9)
            return certa_v8, errada_v9, errada_v8, curta

    certa_v8, errada_v9, errada_v8, curta = asyncio.run(cenario())
    assert (certa_v8.ok, certa_v8.como) == (True, "sha256")
    assert (errada_v9.ok, errada_v9.como) == (False, "crc32") and "corrompida" in errada_v9.detalhe
    assert (errada_v8.ok, errada_v8.como) == (False, "sha256")
    assert (curta.ok, curta.como) == (False, "tamanho")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="o pgrep e o nome do processo, como na placa")
def test_a_transferencia_espera_a_captura(tmp_path):
    """Com o ``ler_adc`` rodando, a transferência não começa; ela segue quando ele termina. (O servidor do teste roda
    os comandos neste computador: um processo chamado ler_adc aqui é a captura na placa.)"""
    ler_adc = tmp_path / "ler_adc"
    shutil.copy(shutil.which("sleep"), ler_adc)
    captura_rodando = subprocess.Popen([str(ler_adc), "30"])
    avisos = []

    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            original = captura(firmware(placa), amostras=1 << 16)
            async with conexao(tmp_path, placa, RegistroDeAtividade()) as c:
                origem = OrigemSSH(c)

                async def esperar():
                    await esperar_sem_captura(origem, avisos.append, intervalo_s=0.1)

                tarefa = asyncio.ensure_future(baixar(origem, str(original), tmp_path / "c.bin",
                                                      esperar_a_captura=esperar))
                await asyncio.sleep(1.0)
                comecou = (tmp_path / f"c.bin{SUFIXO_PARCIAL}").exists() and \
                    (tmp_path / f"c.bin{SUFIXO_PARCIAL}").stat().st_size > 0
                captura_rodando.kill()
                captura_rodando.wait()
                await asyncio.wait_for(tarefa, 20)
            return comecou, original

    try:
        comecou, original = asyncio.run(cenario())
    finally:
        captura_rodando.kill()
    assert not comecou and avisos == [True, False]
    assert (tmp_path / "c.bin").read_bytes() == original.read_bytes()


def test_apagar_e_o_indice(tmp_path):
    registro = RegistroDeAtividade()

    async def cenario():
        async with ServidorSSH(tmp_path / "placa") as placa:
            original = captura(firmware(placa), amostras=1 << 12)
            async with conexao(tmp_path, placa, registro) as c:
                await apagar(OrigemSSH(c), str(original))
            return original

    original = asyncio.run(cenario())
    assert not original.exists()
    assert any(e.descricao == "apagar rede.bin da placa (SFTP)" and e.codigo == 0 for e in registro.entradas)

    indice = IndiceDeCopias(tmp_path / "config" / "copias.json")
    copia = tmp_path / "c.bin"
    copia.write_bytes(b"x" * 10)
    chave = IndiceDeCopias.chave("3714BBBK1234", "rede.bin", 10, 1794_000_000.5)
    assert indice.copia(chave, 10) is None
    indice.lembrar(chave, CopiaLocal(str(copia), True, "crc32", 1.0))
    assert indice.copia(chave, 10) == CopiaLocal(str(copia), True, "crc32", 1.0)
    assert indice.copia(chave, 11) is None                                  # o tamanho não bate: não é ela
    copia.unlink()
    assert indice.copia(chave, 10) is None                                  # a cópia sumiu do computador
    (tmp_path / "config" / "copias.json").write_text("estragado")
    assert indice.copia(chave, 10) is None
