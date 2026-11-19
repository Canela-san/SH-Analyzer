"""As tarefas destacadas na placa (``sh_placa/tarefas.py``, a F6.1) e a placa simulada que reinicia e desliga, no
servidor do simulador: a tarefa com os passos, o resultado e o log, acompanhada ao vivo; o sudo validado dentro dela
(e a senha errada, que nem a deixa começar); a queda do cabo no meio, que não a para (a conexão seguinte a acompanha
desde o começo); a placa que desliga no meio (a tarefa interrompida); o reinício pelo ``systemctl`` (o boot lê o
``uEnv.txt``); o ``make`` e o kernel do remoteproc da placa simulada."""

import asyncio

import pytest

pytest.importorskip("asyncssh")

from sh_placa.correcoes import ErroDoSudo  # noqa: E402
from sh_placa.erros import ErroDeConexao  # noqa: E402
from sh_placa.servidor_do_simulador import ServidorDoSimulador  # noqa: E402
from sh_placa.tarefas import PASTA_DAS_TAREFAS, TarefaNaPlaca, novo_id, tarefas_na_placa  # noqa: E402
from test_sh_placa_simulador import entrar  # noqa: E402

ROTEIRO = """passo preparar comecou "a pasta"
echo "uma linha"
passo preparar ok
passo compilar comecou
printf 'sem fim de linha'
passo compilar aviso "com	um tab
e duas linhas"
resultado versao "v0.9-1-gabc"
resultado copia "~/firmware-anteriores/x"
exit 0
"""


def rodar(corotina):
    return asyncio.run(corotina)


def test_a_tarefa_com_os_passos_o_resultado_e_o_log(tmp_path):
    async def cenario():
        async with ServidorDoSimulador(tmp_path / "placa", vazao_bytes_s=None) as placa:
            async with entrar(placa) as c:
                t = await TarefaNaPlaca.lancar(c, "teste", "Uma tarefa", ROTEIRO)
                vistos, log = [], []
                fim = await t.acompanhar(lambda e: vistos.append(e.passos[-1]), log.append)
                lista = await tarefas_na_placa(c)
                await t.limpar()
                depois = await tarefas_na_placa(c)
                return t, vistos, "".join(log), fim, lista, depois, placa.home

    t, vistos, log, fim, lista, depois, home = rodar(cenario())
    assert [(p.nome, p.estado) for p in vistos] == [("preparar", "comecou"), ("preparar", "ok"),
                                                    ("compilar", "comecou"), ("compilar", "aviso")]
    assert vistos[-1].texto == "com um tab e duas linhas"         # numa linha só, sem o tab
    assert "uma linha\n" in log and "sem fim de linha" in log
    assert fim.codigo == 0 and fim.terminou and not fim.rodando and not fim.interrompida
    assert fim.resultado == {"versao": "v0.9-1-gabc", "copia": "~/firmware-anteriores/x"}
    assert fim.titulo == "Uma tarefa" and fim.tipo == "teste" and fim.estados()["compilar"].estado == "aviso"
    assert [x.id for x in lista] == [t.id] and depois == []
    assert not (home / PASTA_DAS_TAREFAS / t.id).exists()


def test_o_sudo_dentro_da_tarefa(tmp_path):
    """A senha certa valida o sudo antes do roteiro (o ``como_root`` e o ``sudo -n`` rodam como root); a errada é
    recusada no lançamento, sem deixar a tarefa, e nenhum lugar guarda a senha."""
    roteiro = 'como_root true && passo root ok\nprintf x | sudo -n tee /dev/null >/dev/null && passo pipe ok\n'

    async def cenario():
        async with ServidorDoSimulador(tmp_path / "placa", vazao_bytes_s=None) as placa:
            async with entrar(placa) as c:
                with pytest.raises(ErroDoSudo) as errada:
                    await TarefaNaPlaca.lancar(c, "teste", "Senha errada", roteiro, senha_do_sudo="errada")
                antes = await tarefas_na_placa(c)
                t = await TarefaNaPlaca.lancar(c, "teste", "Com o sudo", roteiro, senha_do_sudo=placa.senha_do_sudo)
                fim = await t.esperar()
                return placa, errada.value, antes, fim

    placa, errada, antes, fim = rodar(cenario())
    assert errada.senha_recusada and antes == []
    assert fim.codigo == 0 and [p.nome for p in fim.passos] == ["root", "pipe"]
    assert placa.comandos_de_root[-2:] == ["true", "tee /dev/null"]
    for comando in placa.comandos:
        assert placa.senha_do_sudo not in comando
    assert not any(placa.ram.iterdir())                            # o askpass sumiu da "RAM"
    assert not list(placa.home.glob(".sudo-validado*"))           # o sudo -k no fim


def test_a_queda_no_meio_nao_para_a_tarefa(tmp_path):
    """O cabo que solta no meio: o acompanhamento cai (``ErroDeConexao``), a tarefa segue na placa, a conexão seguinte
    a acha rodando e a acompanha desde o começo até o fim."""
    roteiro = "".join(f"passo p{i} ok\nsleep 0.5\n" for i in range(8)) + "resultado fim sim\n"

    async def cenario():
        async with ServidorDoSimulador(tmp_path / "placa", vazao_bytes_s=None) as placa:
            async with entrar(placa) as c:
                t = await TarefaNaPlaca.lancar(c, "teste", "Longa", roteiro)
                vistos = []

                def ao_mudar(e):
                    vistos.append(e.passos[-1].nome)
                    if len(vistos) == 2:
                        placa.derrubar()

                with pytest.raises(ErroDeConexao):
                    await t.acompanhar(ao_mudar)
            async with entrar(placa) as c:
                (achada,) = await tarefas_na_placa(c, "teste")
                rodando = not achada.interrompida              # rodando, ou já terminou (sob carga, a volta demora)
                de_novo = []
                fim = await TarefaNaPlaca(c, achada.id).acompanhar(lambda e: de_novo.append(e.passos[-1].nome))
                return vistos, rodando, de_novo, fim

    vistos, rodando, de_novo, fim = rodar(cenario())
    assert vistos == ["p0", "p1"] and rodando
    assert de_novo == [f"p{i}" for i in range(8)] and fim.codigo == 0 and fim.resultado == {"fim": "sim"}


def test_a_placa_que_desliga_interrompe_a_tarefa(tmp_path):
    async def cenario():
        async with ServidorDoSimulador(tmp_path / "placa", vazao_bytes_s=None) as placa:
            async with entrar(placa) as c:
                t = await TarefaNaPlaca.lancar(c, "teste", "Interrompida", "passo um ok\nsleep 30\npasso dois ok\n")
                await asyncio.sleep(0.3)
            await placa.desligar()
            desligada = placa.desligada
            with pytest.raises(ErroDeConexao):
                await entrar(placa).conectar()
            await placa.ligar()
            async with entrar(placa) as c:
                return desligada, await TarefaNaPlaca(c, t.id).estado()

    desligada, e = rodar(cenario())
    assert desligada and e.interrompida and not e.terminou and [p.nome for p in e.passos] == ["um"]


def test_o_reinicio_pelo_systemctl_le_o_uenv(tmp_path):
    """O ``sudo systemctl reboot`` da placa simulada: a conexão cai, a placa volta depois do boot, e o boot lê o
    ``uEnv.txt`` (aqui, sem o ``mem=496M`` e com o áudio do HDMI: a linha do kernel e os overlays mudam); os pinos
    voltam ao default, o relógio atrasa o tempo desligada e perde o NTP. Sem o sudo, o ``systemctl`` recusa."""
    async def cenario():
        async with ServidorDoSimulador(tmp_path / "placa", vazao_bytes_s=None, tempo_do_boot_s=0.3) as placa:
            uenv = placa.raiz / "boot" / "uEnv.txt"
            uenv.write_text(uenv.read_text().replace("optargs=mem=496M", "")
                            .replace("disable_uboot_overlay_audio=1", "#disable_uboot_overlay_audio=1")
                            .replace("disable_uboot_overlay_video=1", "#disable_uboot_overlay_video=1"))
            async with entrar(placa) as c:
                sem_root = await c.executar("systemctl reboot")
                try:                                       # a placa pode cair antes de responder (ela reinicia)
                    await TarefaNaPlaca.lancar(c, "reiniciar", "Reiniciar", "como_root systemctl reboot\n",
                                               senha_do_sudo=placa.senha_do_sudo)
                except ErroDeConexao:
                    pass
                for _ in range(100):
                    if placa.reinicios:
                        break
                    await asyncio.sleep(0.1)
            async with entrar(placa) as c:
                pinos = await c.executar("cat $SHAN_RAIZ/sys/devices/platform/ocp/ocp:P9_28_pinmux/state")
            raiz = placa.raiz
            return (sem_root, placa.reinicios, (raiz / "proc/cmdline").read_text(),
                    sorted(p.name for p in (raiz / "proc/device-tree/chosen/overlays").iterdir()), pinos.saida,
                    (raiz / "run/simulador/relogio").read_text(),
                    (raiz / "run/systemd/timesync/synchronized").exists())

    sem_root, reinicios, cmdline, overlays, pinos, relogio, sincronizado = rodar(cenario())
    assert sem_root.codigo == 4 and "authentication required" in sem_root.erro
    assert reinicios == 1 and "mem=496M" not in cmdline and cmdline.startswith("console=ttyO0,115200n8 bone_capemgr")
    assert "BB-HDMI-TDA998x-00A0" in overlays and "AM335X-PRU-RPROC-4-19-TI-00A0" in overlays
    assert pinos.strip() == "default" and float(relogio) == pytest.approx(-0.3) and not sincronizado


def test_o_make_e_o_kernel_do_remoteproc(tmp_path):
    """O ``make`` da placa simulada compila a pasta (o ``ler_adc`` com a versão dela; o ``fw_pru.out`` do código da
    PRU) e falha com a marca; o ``tee`` no ``state`` do remoteproc sobe e para a PRU, com os erros do kernel."""
    rproc = "$SHAN_RAIZ/sys/class/remoteproc/remoteproc1/state"

    async def cenario():
        async with ServidorDoSimulador(tmp_path / "placa", vazao_bytes_s=None) as placa:
            async with entrar(placa) as c:
                compilou = await c.executar("cd firmware && echo v9.9-teste > VERSAO && make clean && make && "
                                            "./ler_adc --help | head -1 && grep -c SHAN_VERSAO=v9.9-teste ler_adc")
                parar = await c.executar(f"echo stop | tee {rproc}")       # parada: o kernel recusa
                subir = await c.executar(f"echo start | tee {rproc} && cat {rproc}")
                de_novo = await c.executar(f"echo start | tee {rproc}")      # já rodando
                await c.executar("cd firmware && echo '// SHAN_FALHA_DE_COMPILACAO' >> pru_main.c")
                falhou = await c.executar("cd firmware && make")
                return compilou, parar, subir, de_novo, falhou

    compilou, parar, subir, de_novo, falhou = rodar(cenario())
    assert compilou.codigo == 0 and compilou.saida.strip().endswith("1"), compilou.erro
    assert parar.codigo == 1 and "Invalid argument" in parar.erro
    assert subir.codigo == 0 and subir.saida.split()[-1] == "running"
    assert de_novo.codigo == 1 and "busy" in de_novo.erro
    assert falhou.codigo == 2 and "SHAN_FALHA_DE_COMPILACAO" in falhou.erro


def test_os_ids_das_tarefas():
    assert novo_id("Atualizar o firmware").startswith("atualizar-o-firmware-")
    with pytest.raises(ValueError):
        TarefaNaPlaca(None, "../x")
