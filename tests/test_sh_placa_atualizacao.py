"""A atualização do firmware (``sh_placa/atualizacao.py``, a F6.2) na placa simulada servida por SSH: o firmware
deste repositório (a versão do ``git describe``, o ``-dirty``), o plano pelo hash, a atualização do firmware antigo
(a cópia de segurança, as capturas intactas, a PRU com o firmware novo, o ``ler_adc`` com a saída contínua), a
compilação que falha (nada muda), a PRU que não sobe (a placa volta sozinha), a queda do cabo no meio, a volta a uma
cópia anterior, o "Recarregar a PRU" e o apagar de uma cópia."""

import asyncio
import hashlib
import re
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("asyncssh")

from sh_placa.agente import ClienteDoAgente, TransporteSSH  # noqa: E402
from sh_placa.atualizacao import (  # noqa: E402
    PINOS,
    PRU_INSTALADA_NA_COPIA,
    ArquivoDoFirmware,
    apagar_copia,
    atualizar,
    copias_anteriores,
    desfecho,
    firmware_da_copia,
    firmware_da_placa,
    firmware_do_aplicativo,
    planejar,
    recarregar_a_pru,
    roteiro_da_atualizacao,
    subpastas_do_firmware,
)
from sh_placa.erros import ErroDeConexao  # noqa: E402
from sh_placa.servidor_do_simulador import ServidorDoSimulador  # noqa: E402
from sh_placa.simulador import VERSAO_ANTIGA  # noqa: E402
from sh_placa.tarefas import TarefaNaPlaca, tarefas_na_placa  # noqa: E402
from test_sh_placa_simulador import entrar  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
BLOCO = 4096


def rodar(corotina):
    return asyncio.run(corotina)


def hashes(pasta: Path) -> dict[str, str]:
    return {p.relative_to(pasta).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(pasta.rglob("*")) if p.is_file()}


def com_marca(firmware, nome, marca):
    """O firmware com uma marca no fim de um arquivo (a falha de compilação, a PRU que não sobe)."""
    arquivos = tuple(replace(a, conteudo=a.conteudo + f"\n// {marca}\n".encode()) if a.caminho == nome else a
                     for a in firmware.arquivos)
    return replace(firmware, arquivos=arquivos)


def placa_simulada(tmp_path, cenario="firmware_antigo"):
    return ServidorDoSimulador(tmp_path / "placa", cenario, vazao_bytes_s=None, amostras_por_bloco=BLOCO)


async def atualizar_e_acompanhar(c, plano, senha):
    tarefa = await atualizar(c, plano, senha)
    passos = []
    fim = await tarefa.acompanhar(lambda e: passos.append((e.passos[-1].nome, e.passos[-1].estado)))
    return tarefa, passos, fim


def test_o_firmware_do_repositorio(tmp_path):
    """Os arquivos do ``git ls-files firmware`` como estão na árvore, a versão do ``git describe`` e, com uma mudança
    não commitada no ``firmware/`` (fora do ``agente/``), o ``-dirty`` e a lista das mudanças."""
    f = firmware_do_aplicativo(RAIZ)
    assert f is not None and f.origem == "repositorio"
    caminhos = set(f.caminhos)
    assert {"ler_adc.c", "Makefile", "setup.sh", "coleta/comum.sh", "agente/shan_agente.py"} <= caminhos
    assert "VERSAO" not in caminhos and all("__pycache__" not in c for c in caminhos)
    assert next(a for a in f.arquivos if a.caminho == "setup.sh").executavel

    repo = tmp_path / "repo"
    (repo / "firmware" / "agente").mkdir(parents=True)
    (repo / "firmware" / "ler_adc.c").write_text("int main(void) { return 0; }\n")
    (repo / "firmware" / "agente" / "shan_agente.py").write_text("# o agente\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "um"], check=True)
    limpo = firmware_do_aplicativo(repo)
    (repo / "firmware" / "agente" / "shan_agente.py").write_text("# o agente mudado\n")
    so_o_agente = firmware_do_aplicativo(repo)
    (repo / "firmware" / "ler_adc.c").write_text("int main(void) { return 1; }\n")
    sujo = firmware_do_aplicativo(repo)
    assert re.fullmatch(r"[0-9a-f]{7,}", limpo.versao) and not limpo.sujo
    assert not so_o_agente.sujo                         # o agente vai pelo stdin: mudá-lo não muda o firmware
    assert sujo.versao == limpo.versao + "-dirty" and sujo.mudancas == ("firmware/ler_adc.c",)
    assert next(a for a in sujo.arquivos if a.caminho == "ler_adc.c").conteudo.endswith(b"return 1; }\n")
    assert firmware_do_aplicativo(tmp_path / "nada") is None


def test_os_pinos_sao_os_do_setup():
    linhas = re.findall(r"^config-pin (P\d_\d+) (\w+)", (RAIZ / "firmware" / "setup.sh").read_text(), re.MULTILINE)
    assert tuple(linhas) == PINOS


def test_a_atualizacao_do_firmware_antigo(tmp_path):
    """A placa com o v0.7.0 (sem a saída contínua) recebe o firmware deste repositório: o plano, os passos na ordem,
    a cópia de segurança completa, as capturas intactas, a PRU com o firmware compilado, o ``ler_adc`` novo."""
    firmware = firmware_do_aplicativo(RAIZ)

    async def cenario():
        async with placa_simulada(tmp_path) as placa:
            capturas = {p.name: p.stat().st_mtime for p in placa.home.glob("firmware/*.bin")}
            async with entrar(placa) as c:
                cliente = ClienteDoAgente(TransporteSSH(c))
                plano = await planejar(cliente, firmware)
                tarefa, passos, fim = await atualizar_e_acompanhar(c, plano, placa.senha_do_sudo)
                ajuda = await c.executar("cd firmware && ./ler_adc --help")
                copias = await copias_anteriores(cliente)
                saude = await cliente.saude()
                sobrou = await tarefas_na_placa(c)
            return placa, capturas, plano, passos, fim, ajuda, copias, saude, sobrou

    placa, capturas, plano, passos, fim, ajuda, copias, saude, sobrou = rodar(cenario())
    assert plano.versao_da_placa == VERSAO_ANTIGA and not plano.nada_muda
    assert {"ler_adc.c", "pru_main.c", "Makefile"} <= set(plano.mudados) and "setup.sh" in plano.novos
    assert plano.bytes_a_enviar == sum(len(a.conteudo) for a in firmware.arquivos)
    assert [n for n, e in passos if e == "ok"] == ["preparar", "compilar", "guardar", "instalar", "carregar",
                                                    "conferir", "limpar"]
    d = desfecho(fim)
    assert d.estado == "atualizada" and d.versao == firmware.versao and fim.codigo == 0, fim.log
    pasta = placa.home / "firmware"
    assert (pasta / "VERSAO").read_text().strip() == firmware.versao
    for a in firmware.arquivos:
        assert (pasta / a.caminho).read_bytes() == a.conteudo
    instalado = placa.raiz / "lib/firmware/am335x-pru0-fw"
    assert instalado.read_bytes() == (pasta / "fw_pru.out").read_bytes()
    assert instalado.stat().st_mode & 0o777 == 0o644         # o kernel o lê como quem pede o start (o debian)
    assert {p.name: p.stat().st_mtime for p in pasta.glob("*.bin")} == capturas      # as capturas, intactas
    assert "--progresso-json" in ajuda.saida                                        # o ler_adc com a saída contínua
    (copia,) = copias
    assert copia.versao == VERSAO_ANTIGA and copia.pru_instalada and copia.binarios and d.copia.endswith(copia.nome)
    assert {"ler_adc.c", "VERSAO", "ler_adc", "fw_pru.out", PRU_INSTALADA_NA_COPIA} <= set(copia.arquivos)
    codigos = {p.codigo for p in saude.conferencias()}
    assert not codigos & {"pru_desatualizada", "compilacao_antiga", "nao_compilado", "versao_desconhecida"}
    raiz = placa.comandos_de_root
    assert any(x.startswith("install -m 0644 ") and x.endswith("am335x-pru0-fw.shan-novo") for x in raiz)
    assert any(x.startswith("./ler_adc 400000 0,1 --blocos 1") for x in raiz)
    assert not (placa.home / ".sh-analyzer" / "preparo").exists() or not any(
        (placa.home / ".sh-analyzer" / "preparo").iterdir())
    assert [t.id for t in sobrou] == [fim.id]
    for comando in placa.comandos:
        assert placa.senha_do_sudo not in comando


def test_a_compilacao_que_falha_nao_muda_nada(tmp_path):
    firmware = com_marca(firmware_do_aplicativo(RAIZ), "ler_adc.c", "SHAN_FALHA_DE_COMPILACAO")

    async def cenario():
        async with placa_simulada(tmp_path) as placa:
            antes = hashes(placa.home / "firmware")
            instalado = (placa.raiz / "lib/firmware/am335x-pru0-fw").read_bytes()
            async with entrar(placa) as c:
                cliente = ClienteDoAgente(TransporteSSH(c))
                plano = await planejar(cliente, firmware)
                _t, passos, fim = await atualizar_e_acompanhar(c, plano, placa.senha_do_sudo)
                copias = await copias_anteriores(cliente)
            return placa, antes, instalado, passos, fim, copias

    placa, antes, instalado, passos, fim, copias = rodar(cenario())
    d = desfecho(fim)
    assert d.estado == "falhou_antes" and ("compilar", "falhou") in passos and "guardar" not in dict(passos)
    assert "SHAN_FALHA_DE_COMPILACAO" in d.mensagem and "nada mudou" in d.mensagem
    assert hashes(placa.home / "firmware") == antes and copias == []
    assert (placa.raiz / "lib/firmware/am335x-pru0-fw").read_bytes() == instalado


def test_a_pru_que_nao_sobe_volta_sozinha(tmp_path):
    """O firmware novo compila, mas a PRU não sobe com ele: a placa volta à cópia (os arquivos, o firmware da PRU,
    sem os arquivos que a versão nova trouxe), confere de novo e fica como estava."""
    firmware = com_marca(firmware_do_aplicativo(RAIZ), "pru_main.c", "SHAN_PRU_NAO_SOBE")

    async def cenario():
        async with placa_simulada(tmp_path, "normal") as placa:
            antes = hashes(placa.home / "firmware")
            instalado = (placa.raiz / "lib/firmware/am335x-pru0-fw").read_bytes()
            async with entrar(placa) as c:
                plano = await planejar(ClienteDoAgente(TransporteSSH(c)), firmware)
                _t, passos, fim = await atualizar_e_acompanhar(c, plano, placa.senha_do_sudo)
                estado = await c.executar("cat $SHAN_RAIZ/sys/class/remoteproc/remoteproc1/state")
            return placa, antes, instalado, passos, fim, estado.saida.strip()

    placa, antes, instalado, passos, fim, estado = rodar(cenario())
    d = desfecho(fim)
    assert d.estado == "voltou" and ("carregar", "falhou") in passos and ("voltar", "ok") in passos, fim.log
    assert "Carregar na PRU" in d.mensagem and d.versao == "v0.8.0-simulador"
    depois = hashes(placa.home / "firmware")
    assert {k: v for k, v in depois.items() if not k.endswith(".bin")} == {
        k: v for k, v in antes.items() if not k.endswith(".bin")}
    assert (placa.raiz / "lib/firmware/am335x-pru0-fw").read_bytes() == instalado and estado == "running"


def test_a_queda_no_meio_da_atualizacao(tmp_path):
    """O cabo solta depois da compilação: a atualização segue na placa, e a conexão seguinte a acompanha até o fim."""
    firmware = firmware_do_aplicativo(RAIZ)

    async def cenario():
        async with placa_simulada(tmp_path) as placa:
            async with entrar(placa) as c:
                plano = await planejar(ClienteDoAgente(TransporteSSH(c)), firmware)
                tarefa = await atualizar(c, plano, placa.senha_do_sudo)

                def ao_mudar(e):
                    if e.passos[-1] == e.passo("compilar") and e.passos[-1].estado == "ok":
                        placa.derrubar()

                with pytest.raises(ErroDeConexao):
                    await tarefa.acompanhar(ao_mudar)
            async with entrar(placa) as c:
                fim = await TarefaNaPlaca(c, tarefa.id).acompanhar()
            return fim

    fim = rodar(cenario())
    assert desfecho(fim).estado == "atualizada" and fim.codigo == 0


def test_voltar_a_uma_copia_anterior_e_recarregar(tmp_path):
    """Depois de atualizar, voltar à cópia do v0.7.0 (a mesma tarefa, com a cópia como origem: o ``ler_adc`` sem a
    saída contínua de novo); a cópia do ``enviar``, com os arquivos das subpastas no alto, volta para as subpastas;
    "Recarregar a PRU" no firmware desatualizado; apagar uma cópia."""
    firmware = firmware_do_aplicativo(RAIZ)

    async def cenario():
        async with placa_simulada(tmp_path) as placa:
            async with entrar(placa) as c:
                cliente = ClienteDoAgente(TransporteSSH(c))
                await atualizar_e_acompanhar(c, await planejar(cliente, firmware), placa.senha_do_sudo)
                (copia,) = await copias_anteriores(cliente)
                volta = firmware_da_copia(copia, subpastas_do_firmware(firmware))
                plano = await planejar(cliente, volta)
                _t, _p, fim = await atualizar_e_acompanhar(c, plano, placa.senha_do_sudo)
                ajuda = await c.executar("cd firmware && ./ler_adc --help")
                (placa.raiz / "lib/firmware/am335x-pru0-fw").write_bytes(b"outro")
                texto = await recarregar_a_pru(c, placa.senha_do_sudo)
                saude = await cliente.saude()
                copias = await copias_anteriores(cliente)
                await apagar_copia(c, copias[-1].nome)
                restam = await copias_anteriores(cliente)
            return placa, plano, fim, ajuda, texto, saude, copias, restam

    placa, plano, fim, ajuda, texto, saude, copias, restam = rodar(cenario())
    assert plano.firmware.origem == "anterior" and plano.bytes_a_enviar == 0
    assert desfecho(fim).estado == "atualizada" and desfecho(fim).versao == VERSAO_ANTIGA, fim.log
    assert "--progresso-json" not in ajuda.saida                     # o v0.7.0 de novo
    assert "rodando" in texto and not {p.codigo for p in saude.conferencias()} & {"pru_desatualizada"}
    assert (placa.raiz / "lib/firmware/am335x-pru0-fw").read_bytes() == (placa.home / "firmware/fw_pru.out").read_bytes()
    assert len(copias) == 2 and len(restam) == 1
    with pytest.raises(ValueError):
        rodar(apagar_copia(None, "../firmware"))

    copia_do_enviar = replace(copias[0], arquivos=("Makefile", "ler_adc.c", "comum.sh", "ler_adc", "VERSAO"))
    pares = dict(firmware_da_copia(copia_do_enviar, {"comum.sh": "coleta/comum.sh"}).hashes_na_placa)
    assert pares == {"Makefile": "Makefile", "ler_adc.c": "ler_adc.c", "coleta/comum.sh": "comum.sh"}


def test_o_roteiro_de_compilar_de_novo():
    """O "compilar e carregar de novo": a própria pasta como origem, sem nada pelo SFTP nem hash para conferir."""
    from sh_placa.atualizacao import PlanoDeAtualizacao

    f = firmware_da_placa(["ler_adc.c", "Makefile"], "v0.8-1-gabc")
    plano = PlanoDeAtualizacao(f, "v0.8-1-gabc", (), (), f.caminhos, (), f.caminhos, 0, True)
    texto = roteiro_da_atualizacao(plano, "x-1")
    assert 'ORIGEM="$HOME/firmware"' in texto and "HASHES=()" in texto and "NOVOS=()" in texto
    assert ArquivoDoFirmware("a", b"x").sha256 == hashlib.sha256(b"x").hexdigest()
