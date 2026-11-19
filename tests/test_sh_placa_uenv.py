"""O assistente do ``/boot/uEnv.txt`` (``sh_placa/uenv.py``, a F6.4) e o reiniciar e o desligar (``sh_placa/sistema.py``,
a F6.5): as mudanças propostas para cada cenário de configuração, mexendo só nas linhas delas (descomentar a que já
existe, trocar o valor, acrescentar perto das parecidas); o que o assistente recusa (a linha que ele não reconhece, a
chave ativa duas vezes, o CR LF); e, na placa simulada, a gravação com a cópia e o hash, a recusa do arquivo que mudou
depois de lido, a restauração, e o reinício que lê o ``uEnv.txt`` novo (o diagnóstico fica verde)."""

import asyncio

import pytest

from sh_placa import uenv
from sh_placa.simulador import KERNEL_SIMULADO, OVERLAY_DA_PRU, UENV

DTBOS = ["AM335X-PRU-RPROC-4-14-TI-00A0", "AM335X-PRU-RPROC-4-19-TI-00A0", "AM335X-PRU-RPROC-4-19-TI-PRUCAPE-00A0",
         "AM335X-PRU-UIO-00A0"]


def texto(cenario="normal"):
    """O uEnv.txt da placa simulada (o da placa de verdade de 15/11/2026) no cenário."""
    return UENV.format(kernel=KERNEL_SIMULADO, overlay=OVERLAY_DA_PRU,
                       video="#" if cenario == "audio_hdmi" else "", audio="#" if cenario == "audio_hdmi" else "",
                       pru="#" if cenario == "sem_overlay_da_pru" else "",
                       mem="" if cenario == "sem_mem_496m" else "optargs=mem=496M")


def mudadas(antes: str, depois: str) -> list[tuple[str, str]]:
    """As linhas que mudaram, como ``("-", linha)`` e ``("+", linha)``."""
    return [(x[0], x[1:].rstrip("\n")) for x in uenv.diff(antes, depois).splitlines(keepends=True)
            if x[:1] in "+-" and not x.startswith(("+++", "---"))]


def nomes(t):
    return [(m.nome, m.necessaria) for m in uenv.propor(t, KERNEL_SIMULADO, DTBOS)]


def test_a_placa_de_verdade_nao_tem_o_que_mudar():
    """O uEnv.txt da placa de verdade (com o vídeo do HDMI já desligado): nada a propor; sem o vídeo desligado, só a
    opcional."""
    assert nomes(texto()) == []
    assert uenv.aplicar(texto(), [], KERNEL_SIMULADO, DTBOS) == texto()
    com_video = texto().replace("\ndisable_uboot_overlay_video=1", "\n#disable_uboot_overlay_video=1")
    assert nomes(com_video) == [("video", False)]


@pytest.mark.parametrize("cenario, esperadas, linhas", [
    ("audio_hdmi", [("audio", True), ("video", False)],
     [("-", "#disable_uboot_overlay_audio=1"), ("+", "disable_uboot_overlay_audio=1")]),
    ("sem_overlay_da_pru", [("pru", True)],
     [("-", "#uboot_overlay_pru=/lib/firmware/AM335X-PRU-RPROC-4-19-TI-00A0.dtbo"),
      ("+", "uboot_overlay_pru=/lib/firmware/AM335X-PRU-RPROC-4-19-TI-00A0.dtbo")]),
    ("sem_mem_496m", [("mem", True)], None),
])
def test_cada_cenario_muda_so_a_linha_dele(cenario, esperadas, linhas):
    antes = texto(cenario)
    assert [x for x in nomes(antes) if x[1]] == [x for x in esperadas if x[1]]
    depois = uenv.aplicar(antes, [n for n, necessaria in esperadas if necessaria], KERNEL_SIMULADO, DTBOS)
    if linhas is not None:
        assert mudadas(antes, depois) == linhas
    else:                                            # o mem=496M vai para o fim do cmdline
        (menos, mais) = mudadas(antes, depois)
        assert menos[1].startswith("cmdline=") and mais == ("+", menos[1] + " mem=496M")
    assert [x for x in nomes(depois) if x[1]] == []          # nada mais a mudar


def test_o_overlay_da_pru_do_uio_e_o_mem_trocado():
    antes = texto().replace("uboot_overlay_pru=/lib/firmware/AM335X-PRU-RPROC-4-19-TI-00A0.dtbo",
                            "#uboot_overlay_pru=/lib/firmware/AM335X-PRU-RPROC-4-19-TI-00A0.dtbo") \
        .replace("#uboot_overlay_pru=/lib/firmware/AM335X-PRU-UIO-00A0.dtbo",
                 "uboot_overlay_pru=/lib/firmware/AM335X-PRU-UIO-00A0.dtbo").replace("mem=496M", "mem=256M")
    assert [n for n, x in nomes(antes) if x] == ["pru", "mem"]
    depois = uenv.aplicar(antes, ["pru", "mem"], KERNEL_SIMULADO, DTBOS)
    assert mudadas(antes, depois) == [
        ("-", "#uboot_overlay_pru=/lib/firmware/AM335X-PRU-RPROC-4-19-TI-00A0.dtbo"),
        ("+", "uboot_overlay_pru=/lib/firmware/AM335X-PRU-RPROC-4-19-TI-00A0.dtbo"),
        ("-", "uboot_overlay_pru=/lib/firmware/AM335X-PRU-UIO-00A0.dtbo"),
        ("+", "#uboot_overlay_pru=/lib/firmware/AM335X-PRU-UIO-00A0.dtbo"),
        ("-", "optargs=mem=256M"), ("+", "optargs=mem=496M")]


def test_o_que_falta_de_todo_e_acrescentado():
    """Um uEnv.txt mínimo (sem as linhas comentadas da imagem): as linhas novas vão no fim, depois de uma vazia."""
    antes = "uname_r=4.19.94-ti-r42\ncmdline=coherent_pool=1M quiet\n"
    assert [n for n, x in nomes(antes) if x] == ["overlays", "audio", "pru", "cape", "mem"]
    depois = uenv.aplicar(antes, ["overlays", "audio", "pru", "cape", "mem"], KERNEL_SIMULADO, DTBOS)
    assert depois.splitlines()[:2] == ["uname_r=4.19.94-ti-r42", "cmdline=coherent_pool=1M quiet mem=496M"]
    assert uenv.chaves(uenv.ler_o_uenv(depois)) == {
        "uname_r": "4.19.94-ti-r42", "cmdline": "coherent_pool=1M quiet mem=496M", "enable_uboot_overlays": "1",
        "disable_uboot_overlay_audio": "1", "uboot_overlay_pru": "/lib/firmware/AM335X-PRU-RPROC-4-19-TI-00A0.dtbo",
        "enable_uboot_cape_universal": "1"}


@pytest.mark.parametrize("estranho, trecho", [
    ("if test -n ${x}; then echo oi; fi\n", "não é comentário nem chave=valor"),
    ("cmdline=quiet\ncmdline=mem=496M\n", "mais de uma linha"),
    ("uname_r=4.19\r\n", "Windows"),
])
def test_o_que_o_assistente_recusa(estranho, trecho):
    with pytest.raises(uenv.UenvEstranho, match=trecho):
        uenv.propor(texto() + estranho, KERNEL_SIMULADO, DTBOS)


def test_sem_o_overlay_do_kernel_nao_propoe_um_inventado():
    propostas = uenv.propor(texto("sem_overlay_da_pru"), "5.10.168-ti-r71", DTBOS)
    assert "pru" not in [m.nome for m in propostas]
    assert uenv.overlay_sugerido(DTBOS, "4.14.108-ti-r131") == "AM335X-PRU-RPROC-4-14-TI-00A0"


# ------------------------------------------------------------------ na placa simulada

def test_gravar_restaurar_e_reiniciar_na_placa_simulada(tmp_path):
    pytest.importorskip("asyncssh")
    from sh_placa import sistema
    from sh_placa.agente import ClienteDoAgente, ErroDaPlaca, TransporteSSH
    from sh_placa.erros import ErroDeConexao
    from sh_placa.servidor_do_simulador import ServidorDoSimulador
    from test_sh_placa_simulador import entrar

    async def cenario():
        async with ServidorDoSimulador(tmp_path / "placa", "audio_hdmi", vazao_bytes_s=None,
                                       tempo_do_boot_s=0.3) as placa:
            arquivo = placa.raiz / "boot" / "uEnv.txt"
            async with entrar(placa) as c:
                cliente = ClienteDoAgente(TransporteSSH(c))
                lido = await cliente.chamar("inicializacao")
                antes = lido["uenv"]["texto"]
                propostas = uenv.propor(antes, lido["kernel"], lido["dtbos_da_pru"])
                novo = uenv.aplicar(antes, [m.nome for m in propostas if m.necessaria], lido["kernel"],
                                    lido["dtbos_da_pru"])
                gravado = await uenv.gravar(c, novo, lido["uenv"]["sha256"], placa.senha_do_sudo, "20261119-120000")
                with pytest.raises(ErroDaPlaca, match="mudou"):           # o hash é o de antes
                    await uenv.gravar(c, novo, lido["uenv"]["sha256"], placa.senha_do_sudo, "20261119-120001")
                copia = await uenv.ler_copia(c, "uEnv.txt.sh-analyzer-20261119-120000")
                depois_de_gravar = arquivo.read_text()
                try:
                    await sistema.reiniciar(c, placa.senha_do_sudo)
                except ErroDeConexao:
                    pass                                                  # caiu antes de responder: reiniciou
                for _ in range(100):
                    if placa.reinicios:
                        break
                    await asyncio.sleep(0.1)
            async with entrar(placa) as c:
                saude = await ClienteDoAgente(TransporteSSH(c)).saude()
                restaurado = await uenv.gravar(c, copia, uenv.sha256(depois_de_gravar), placa.senha_do_sudo,
                                               "20261119-120002")
                await sistema.desligar(c, placa.senha_do_sudo)
            for _ in range(100):
                if placa.desligada:
                    break
                await asyncio.sleep(0.1)
            return placa, antes, novo, gravado, copia, depois_de_gravar, saude, restaurado, arquivo.read_text()

    placa, antes, novo, gravado, copia, depois_de_gravar, saude, restaurado, final = asyncio.run(cenario())
    assert depois_de_gravar == novo and copia == antes and gravado.sha256 == uenv.sha256(novo)
    assert gravado.copia == "/boot/uEnv.txt.sh-analyzer-20261119-120000"
    assert (placa.raiz / "boot" / "uEnv.txt.sh-analyzer-20261119-120000").read_text() == antes
    assert placa.reinicios == 1
    codigos = {p.codigo for p in saude.conferencias()}
    assert not codigos & {"audio_hdmi", "audio_hdmi_no_proximo_boot", "mem_496m", "overlay_da_pru", "pru_ausente"}
    assert final == antes and restaurado.sha256 == uenv.sha256(antes)
    assert placa.desligada
    assert any(x.startswith("sh -c ") for x in placa.comandos_de_root)
    assert any("systemctl reboot" in x for x in placa.comandos_de_root)
    for comando in placa.comandos:
        assert placa.senha_do_sudo not in comando


def test_o_que_espera_um_reinicio():
    """O que o uEnv.txt já pede e este boot não tem (a página mostra "Gravado, esperando um reinício")."""
    lido = {"uenv": {"texto": texto()}, "cmdline": "console=ttyO0,115200n8 mem=496M quiet",
            "overlays": ["BB-ADC-00A0", OVERLAY_DA_PRU]}
    assert uenv.pendentes(lido) == []
    lido.update(cmdline="console=ttyO0,115200n8 quiet", overlays=["BB-ADC-00A0", "BB-HDMI-TDA998x-00A0"])
    assert uenv.pendentes(lido) == ["o mem=496M (a memória dos buffers)", f"o overlay da PRU {OVERLAY_DA_PRU}",
                                    "o vídeo do HDMI desligado"]
    assert uenv.pendentes({"uenv": {"texto": None}}) == []
    assert uenv.pendentes({"uenv": {"texto": "if x; then y; fi\n"}, "overlays": []}) == []   # o estranho: nada
