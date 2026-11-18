"""A captura contínua pelo SSH (``sh_placa/captura.py``, a F4.2), com o ``ler_adc`` de verdade: o do
``firmware/ler_adc.c``, compilado contra a PRU falsa (``tests/pru_falsa.py``) e posto na pasta do firmware da placa
do servidor SSH do teste, com o sudo falso dela. O roteiro, o sudo, o fluxo pelo canal, o Parar pelo stdin, a queda
da conexão e o disco daqui que falha, de ponta a ponta. E a captura no cartão (``sh_placa/captura_no_cartao.py``, a
F4.4): o ``ler_adc`` desacoplado da conexão, o acompanhamento, o Parar pelo PID e a queda que não para a captura. Sem
placa."""

import asyncio
import contextlib
import os
import shutil
import signal
from pathlib import Path

import numpy as np
import pytest

asyncssh = pytest.importorskip("asyncssh")
pru_falsa = pytest.importorskip("pru_falsa")

from servidor_ssh import ServidorSSH  # noqa: E402
from sh_placa import captura as cap  # noqa: E402
from sh_placa.captura import (  # noqa: E402
    CapturaContinua,
    ErroDaCaptura,
    FirmwareSemLerAdc,
    FirmwareSemSaidaContinua,
    caminho_parcial,
    recuperar,
    roteiro_da_captura,
)
from sh_placa.captura_no_cartao import (  # noqa: E402
    PASTA_EM_CURSO,
    CapturaNoCartao,
    em_curso,
    roteiro_de_inicio,
)
from sh_placa.chaves import ChaveDoAplicativo, HostsConhecidos  # noqa: E402
from sh_placa.conexao import ConexaoSSH  # noqa: E402
from sh_placa.correcoes import ErroDoSudo  # noqa: E402
from sh_placa.destino import Destino  # noqa: E402
from sh_placa.erros import ErroDeConexao  # noqa: E402
from sh_placa.registro import RegistroDeAtividade  # noqa: E402
from supraharmonicos import cabecalho as cab  # noqa: E402

pytestmark = pytest.mark.skipif(not pru_falsa.tem_gcc(), reason="sem gcc no computador")

SENHA_DO_SUDO = "senha-do-sudo-da-captura"
T = cab.CABECALHO_TAMANHO_V9
BLOCO = 2 * pru_falsa.AMOSTRAS_POR_BLOCO


@pytest.fixture(scope="module")
def ler_adc(tmp_path_factory):
    return pru_falsa.compilar_ler_adc(tmp_path_factory.mktemp("ler_adc_pelo_ssh"))


class Bancada:
    """A placa do servidor SSH com o ler_adc de verdade e a PRU falsa, e a conexão do aplicativo com ela."""

    def __init__(self, tmp_path: Path, ler_adc: Path, **opcoes_da_pru):
        self.tmp_path = tmp_path
        self.servidor = ServidorSSH(tmp_path / "placa", senha_do_sudo=SENHA_DO_SUDO)
        firmware = self.servidor.home / "firmware"
        (firmware / "ler_adc").unlink()
        shutil.copy2(ler_adc, firmware / "ler_adc")
        (tmp_path / "pru").mkdir()
        self.placa_falsa = pru_falsa.PlacaFalsa(tmp_path / "pru")
        self.servidor.ambiente.update({k: v for k, v in self.placa_falsa.ambiente.items() if k.startswith("FALSO_")})
        self.opcoes_da_pru = opcoes_da_pru
        self.registro = RegistroDeAtividade()
        self.destino = tmp_path / "capturas"
        self.destino.mkdir()

    def conexao(self) -> ConexaoSSH:
        async def confiar(_destino, _impressao):
            return True

        return ConexaoSSH(Destino("127.0.0.1", self.servidor.porta), chave=ChaveDoAplicativo(self.tmp_path / "chaves"),
                          hosts=HostsConhecidos(self.tmp_path / "chaves" / "known_hosts"), registro=self.registro,
                          senha=self.servidor.senha, confirmar_host=confiar)

    def capturar(self, argumentos, *, senha=SENHA_DO_SUDO, nome="captura.bin", antes=None, ao_progresso=None,
                 com_pru=True):
        """Roda a captura até o fim. ``antes(captura)``: no laço, antes de ela começar; ``ao_progresso(captura,
        progresso)``: a cada aviso. Devolve (o resultado ou a exceção, a captura, os progressos)."""
        progressos = []

        async def cenario():
            pru = self.placa_falsa.pru(**self.opcoes_da_pru) if com_pru else None
            try:
                async with self.servidor:
                    async with self.conexao() as c:
                        captura = CapturaContinua(c, argumentos, self.destino / nome, senha_do_sudo=senha,
                                                  ao_progresso=lambda p: (progressos.append(p),
                                                                          ao_progresso and ao_progresso(captura, p)))
                        if antes is not None:
                            antes(captura)
                        try:
                            return await captura.rodar(), captura
                        except Exception as e:
                            return e, captura
            finally:
                if pru is not None:
                    pru.parar()

        resultado, captura = asyncio.run(cenario())
        return resultado, captura, progressos


def conferir_blocos(arquivo: Path, blocos: int) -> None:
    dados = np.fromfile(arquivo, dtype="<u2", offset=T)
    assert len(dados) == blocos * pru_falsa.AMOSTRAS_POR_BLOCO
    for k in range(blocos):
        bloco = dados[k * pru_falsa.AMOSTRAS_POR_BLOCO:(k + 1) * pru_falsa.AMOSTRAS_POR_BLOCO]
        assert np.array_equal(bloco, pru_falsa.bloco_esperado(k)), f"bloco {k}"


def test_a_captura_inteira_chega_como_o_arquivo_do_cartao(tmp_path, ler_adc):
    """3 blocos pelo SSH: o arquivo daqui é o do cartão (o cabeçalho final no começo, os blocos byte a byte, o CRC das
    amostras conferido pelo que chegou), o progresso anda de bloco em bloco, o texto do ler_adc vem à parte, e a
    senha do sudo não aparece no registro nem nos comandos."""
    b = Bancada(tmp_path, ler_adc)
    r, captura, progressos = b.capturar(["400000", "0,1", "--blocos", "3", "-t", "pelo SSH"])
    assert isinstance(r, cap.CapturaRecebida), r
    assert (r.codigo, r.motivo, r.falha, r.caiu, r.blocos, r.parada_pedida) == (0, "ok", "", False, 3, False)
    assert r.fechamento.crc_confere is True and r.bytes_recebidos == 2 * T + 3 * BLOCO
    assert r.arquivo.stat().st_size == T + 3 * BLOCO and not caminho_parcial(r.arquivo).exists()
    c = cab.ler_cabecalho(r.arquivo)
    assert c.crc32_valido and c.blocos_gravados == 3 and c.titulo == "pelo SSH" and not c.fim_pelo_computador
    assert cab.conferir_crc_das_amostras(r.arquivo, c) is True
    conferir_blocos(r.arquivo, 3)
    assert any("Captura concluída" in linha for linha in r.texto)
    assert not any(linha.startswith("{") for linha in r.texto)
    blocos = [p.blocos for p in progressos]
    assert blocos == sorted(blocos) and blocos[-1] == 3 and progressos[-1].blocos_pedidos == 3
    assert progressos[-1].ultimo_bloco["bloco"] == 3 and progressos[-1].inicio["canais"] == [0, 1]
    (entrada,) = [e for e in b.registro.entradas if e.descricao.startswith("captura contínua")]
    assert entrada.codigo == 0 and "-o - --progresso-json" in entrada.comando
    for onde in (entrada.comando, *b.servidor.comandos, *b.servidor.comandos_de_root):
        assert SENHA_DO_SUDO not in onde
    (como_root,) = b.servidor.comandos_de_root                        # o shell de root do Parar, com o ler_adc
    assert como_root.startswith("sh -c ") and como_root.endswith(
        " ler_adc ./ler_adc 400000 0,1 --blocos 3 -t pelo SSH -o - --progresso-json")
    assert list((b.servidor.ram).iterdir()) == []                         # nada do askpass ficou na RAM


def test_parar_fecha_a_captura_com_o_cabecalho_do_ler_adc(tmp_path, ler_adc):
    """Até o Parar (``--blocos 0``): o Parar vira o SIGINT do ler_adc, que fecha a captura no último bloco inteiro,
    com o cabeçalho final dele (o código 0: parar é o fim normal sem os blocos contados)."""
    b = Bancada(tmp_path, ler_adc, intervalo_s=0.15)

    def parar_no_segundo(captura, progresso):
        if progresso.blocos >= 2:
            captura.parar()

    r, captura, progressos = b.capturar(["400000", "1", "--blocos", "0"], ao_progresso=parar_no_segundo)
    assert isinstance(r, cap.CapturaRecebida), r
    assert (r.codigo, r.motivo, r.caiu, r.parada_pedida) == (0, "ok", False, True)
    assert r.blocos >= 2 and r.fechamento.crc_confere is True
    assert any(p.parada_pedida for p in progressos)
    conferir_blocos(r.arquivo, r.blocos)


def test_parar_com_os_blocos_contados_e_o_codigo_5(tmp_path, ler_adc):
    b = Bancada(tmp_path, ler_adc, intervalo_s=0.15)
    r, _, _ = b.capturar(["400000", "1", "--blocos", "50"],
                         ao_progresso=lambda captura, p: p.blocos >= 1 and captura.parar())
    assert (r.codigo, r.motivo, r.caiu) == (5, "interrompida", False) and 1 <= r.blocos < 50


def test_parar_antes_de_comecar_espera_o_ler_adc_saber_parar(tmp_path, ler_adc):
    """O Parar antes da linha ``inicio``: ele espera por ela (o SIGINT antes disso mataria o ler_adc sem o cabeçalho
    final). A captura para logo no começo, fechada pelo ler_adc."""
    b = Bancada(tmp_path, ler_adc, intervalo_s=0.15)
    r, _, _ = b.capturar(["400000", "1", "--blocos", "0"], antes=lambda captura: captura.parar())
    assert isinstance(r, cap.CapturaRecebida), r
    assert (r.codigo, r.caiu, r.parada_pedida) == (0, False, True) and r.blocos <= 2
    assert cab.ler_cabecalho(r.arquivo).crc32_valido


def test_a_queda_da_conexao_fecha_o_que_chegou(tmp_path, ler_adc):
    """O cabo que solta no meio: a captura volta fechada aqui, com os blocos inteiros que chegaram, o CRC e o sinal
    de cada canal medidos neles e a marca do fim escrito pelo computador."""
    b = Bancada(tmp_path, ler_adc, intervalo_s=0.1)
    r, _, _ = b.capturar(["400000", "0,1,2", "--blocos", "0"],
                         ao_progresso=lambda captura, p: p.blocos >= 2 and b.servidor.derrubar())
    assert isinstance(r, cap.CapturaRecebida), r
    assert (r.codigo, r.motivo, r.caiu) == (None, "conexao_caiu", True) and "caiu" in r.falha
    assert r.blocos >= 2 and not caminho_parcial(r.arquivo).exists()
    c = cab.ler_cabecalho(r.arquivo)
    assert c.crc32_valido and c.fim_pelo_computador and c.blocos_gravados == r.blocos
    assert cab.conferir_crc_das_amostras(r.arquivo, c) is True
    conferir_blocos(r.arquivo, r.blocos)


def test_o_disco_daqui_que_falha_para_a_captura_e_fecha_o_que_foi_gravado(tmp_path, ler_adc, monkeypatch):
    b = Bancada(tmp_path, ler_adc, intervalo_s=0.05)
    gravar, gravados = cap._gravar, []

    def gravar_ate_encher(f, dados):
        if sum(gravados) > T + 2 * BLOCO + 1000:
            raise OSError(28, "No space left on device")
        gravados.append(len(dados))
        gravar(f, dados)

    monkeypatch.setattr(cap, "_gravar", gravar_ate_encher)
    r, _, _ = b.capturar(["400000", "1", "--blocos", "0"])
    assert isinstance(r, cap.CapturaRecebida), r
    assert (r.motivo, r.caiu, r.codigo) == ("gravacao_no_computador", True, None)
    assert "No space left on device" in r.falha and r.blocos == 2
    assert cab.conferir_crc_das_amostras(r.arquivo, cab.ler_cabecalho(r.arquivo)) is True


# --- O que impede a captura de começar ---------------------------------------------------------------------------------

def test_o_ler_adc_de_antes_da_saida_continua_pede_o_firmware_novo(tmp_path, ler_adc):
    b = Bancada(tmp_path, ler_adc)
    antigo = b.servidor.home / "firmware" / "ler_adc"
    antigo.unlink()
    antigo.write_text("#!/bin/sh\necho 'Uso: ler_adc FREQ CANAIS [-o ARQUIVO] [--blocos N]'\n")
    antigo.chmod(0o755)
    r, _, _ = b.capturar(["400000", "1", "--blocos", "1"], com_pru=False)
    assert isinstance(r, FirmwareSemSaidaContinua) and r.codigo == cap.SAIDA_SEM_SAIDA_CONTINUA
    assert "atualize o firmware" in str(r)
    assert list(b.destino.iterdir()) == [] and b.servidor.comandos_de_root == []


def test_sem_o_ler_adc_compilado(tmp_path, ler_adc):
    b = Bancada(tmp_path, ler_adc)
    (b.servidor.home / "firmware" / "ler_adc").unlink()
    r, _, _ = b.capturar(["400000", "1"], com_pru=False)
    assert isinstance(r, FirmwareSemLerAdc) and list(b.destino.iterdir()) == []


def test_a_senha_errada_do_sudo_nao_roda_nada(tmp_path, ler_adc):
    b = Bancada(tmp_path, ler_adc)
    r, _, _ = b.capturar(["400000", "1", "--blocos", "1"], senha="errada", com_pru=False)
    assert isinstance(r, ErroDoSudo) and r.senha_recusada
    assert b.servidor.comandos_de_root == [] and list(b.destino.iterdir()) == []


def test_o_pedido_que_o_ler_adc_recusa_vem_com_a_causa(tmp_path, ler_adc):
    b = Bancada(tmp_path, ler_adc)
    r, _, _ = b.capturar(["400000", "9"], com_pru=False)
    assert isinstance(r, ErroDaCaptura) and r.codigo == 2, r
    assert "canal" in str(r).lower() and r.texto and list(b.destino.iterdir()) == []


def test_uma_captura_que_existe_nao_e_sobrescrita(tmp_path, ler_adc):
    b = Bancada(tmp_path, ler_adc)
    existente = b.destino / "captura.bin"
    existente.write_bytes(b"de antes")
    r, _, _ = b.capturar(["400000", "1", "--blocos", "1"], com_pru=False)
    assert isinstance(r, FileExistsError) and existente.read_bytes() == b"de antes"
    assert b.servidor.comandos == []


def test_o_roteiro_nao_aceita_as_opcoes_do_receptor():
    for argumentos in (["400000", "1", "-o", "x.bin"], ["400000", "1", "--progresso-json"], [],
                       ["400000", "1", "--saida=x.bin"]):
        with pytest.raises(ValueError):
            roteiro_da_captura(argumentos)
    roteiro = roteiro_da_captura(["400000", "0,1", "-t", "título com espaço; e $(nada)"], "/opt/firmware")
    assert "cd /opt/firmware " in roteiro and "'título com espaço; e $(nada)'" in roteiro
    assert '"$HOME"/firmware' in roteiro_da_captura(["400000", "1"])


def test_recuperar_um_parcial_que_ficou(tmp_path):
    """O aplicativo fechou no meio da captura: o ``.parcial`` é fechado com os blocos inteiros e renomeado."""
    from capturas_sinteticas import montar_cabecalho
    provisorio = montar_cabecalho(1000, (0,), (0,), ("",), 400_000, versao=9, blocos=0, total_amostras=0,
                                  amostras_por_buffer=1000)
    parcial = tmp_path / "captura.bin.parcial"
    parcial.write_bytes(provisorio + np.arange(2500, dtype="<u2").tobytes())
    f = recuperar(parcial)
    assert (f.blocos, f.pelo_computador, f.bytes_descartados) == (2, True, 1000)
    assert not parcial.exists() and cab.ler_cabecalho(tmp_path / "captura.bin").fim_pelo_computador
    with pytest.raises(ValueError):
        recuperar(tmp_path / "captura.bin")


def test_o_conferir_antes_mede_um_bloco_do_pedido_e_apaga_o_arquivo(tmp_path, ler_adc):
    """O "Conferir antes" (``sh_placa/conferencia.py``): o pedido do formulário com um bloco só, pela saída contínua,
    medido no motor; a faixa de cada canal é a do pedido, e o arquivo da conferência não fica."""
    from sh_placa.conferencia import ConferenciaFeita, conferir, pedido_da_conferencia, segundos_da_conferencia
    from sh_placa.pedido import Canal, PedidoDeCaptura

    b = Bancada(tmp_path, ler_adc)
    pedido = PedidoDeCaptura((Canal(0, faixa_v=5.12), Canal(3, "corrente")), 400_000, duracao_s=3600.0,
                             titulo="Rede", destino="cartao", arquivo_no_cartao="rede.bin")
    assert pedido_da_conferencia(pedido).argumentos() == ["400000", "0,3", "--blocos", "1", "-t", "conferência",
                                                          "--grandeza", "0:tensao,3:corrente",
                                                          "--faixa-adc", "0:5.12,3:20.48"]
    assert segundos_da_conferencia(pedido) == pytest.approx(2.62144)
    pasta = tmp_path / "conferencias"

    async def cenario():
        pru = b.placa_falsa.pru(**b.opcoes_da_pru)
        try:
            async with b.servidor:
                async with b.conexao() as c:
                    return await conferir(c, pedido, pasta, senha_do_sudo=SENHA_DO_SUDO)
        finally:
            pru.parar()

    feita = asyncio.run(cenario())
    assert isinstance(feita, ConferenciaFeita) and feita.recebida.codigo == 0 and not feita.adc_mudo
    assert [n.canal for n in feita.conferencia.canais] == [0, 3]
    assert [n.faixa_v for n in feita.conferencia.canais] == [5.12, 20.48]
    assert feita.conferencia.integra and feita.conferencia.cabecalho.titulo == "conferência"
    assert all(n.amostras == pru_falsa.AMOSTRAS_POR_BLOCO // 2 for n in feita.conferencia.canais)
    assert list(pasta.iterdir()) == []
    for onde in (*(e.comando for e in b.registro.entradas), *b.servidor.comandos, *b.servidor.comandos_de_root):
        assert SENHA_DO_SUDO not in onde


# --- No cartão (a F4.4) ------------------------------------------------------------------------------------------------

def no_cartao(b: Bancada, cenario, *, com_pru=True):
    """Roda ``cenario()`` com o servidor e a PRU falsa de pé; no fim, nenhum ler_adc lançado por ele fica rodando."""
    async def tudo():
        pru = b.placa_falsa.pru(**b.opcoes_da_pru) if com_pru else None
        try:
            async with b.servidor:
                return await cenario()
        finally:
            for pid in (b.servidor.home / "firmware" / PASTA_EM_CURSO).glob("*/pid"):
                with contextlib.suppress(OSError, ValueError):
                    os.kill(int(pid.read_text()), signal.SIGKILL)
            if pru is not None:
                pru.parar()

    return asyncio.run(tudo())


async def esperar(condicao, tempo_s=20.0):
    fim = asyncio.get_running_loop().time() + tempo_s
    while not condicao():
        assert asyncio.get_running_loop().time() < fim, "a condição não chegou"
        await asyncio.sleep(0.02)


def test_no_cartao_a_captura_fica_na_placa_e_o_progresso_vem_pelo_tail(tmp_path, ler_adc):
    """3 blocos no cartão: o arquivo na pasta do firmware é o do ler_adc (o CRC da linha ``fim`` é o do cabeçalho), o
    progresso anda de bloco em bloco (os bytes são os do arquivo), o texto vem à parte, e recolher apaga a pasta em
    curso. O ler_adc roda num setsid de root, e a senha não aparece em lugar nenhum."""
    b = Bancada(tmp_path, ler_adc)
    progressos, textos = [], []

    async def cenario():
        async with b.conexao() as c:
            captura = CapturaNoCartao(c, "no_cartao.bin", ao_progresso=progressos.append, ao_texto=textos.append)
            await captura.iniciar(["400000", "0,1", "--blocos", "3", "-t", "no cartão"], SENHA_DO_SUDO)
            antes = await em_curso(c)
            gravada = await captura.acompanhar()
            await captura.limpar()
            return antes, gravada, await em_curso(c)

    antes, gravada, depois = no_cartao(b, cenario)
    assert [e.nome for e in antes] == ["no_cartao.bin"]
    arquivo = b.servidor.home / "firmware" / "no_cartao.bin"
    assert (gravada.codigo, gravada.motivo, gravada.blocos, gravada.parada_pedida) == (0, "ok", 3, False)
    assert gravada.gravou and gravada.integridade == (0, 0, 0) and gravada.nome == "no_cartao.bin"
    c = cab.ler_cabecalho(arquivo)
    assert c.crc32_valido and c.blocos_gravados == 3 and c.titulo == "no cartão"
    assert gravada.fim["crc32_amostras"] == c.crc32_amostras and cab.conferir_crc_das_amostras(arquivo, c) is True
    conferir_blocos(arquivo, 3)
    blocos = [p.blocos for p in progressos]
    assert blocos == sorted(blocos) and blocos[-1] == 3 and progressos[-1].bytes_recebidos == T + 3 * BLOCO
    assert progressos[-1].blocos_pedidos == 3 and progressos[-1].inicio["canais"] == [0, 1]
    assert any("Captura concluída" in linha for linha in gravada.texto) and textos
    assert not any(linha.startswith("{") for linha in gravada.texto)
    assert depois == [] and not (b.servidor.home / "firmware" / PASTA_EM_CURSO).exists()
    (como_root,) = b.servidor.comandos_de_root
    assert como_root.startswith("setsid sh -c ") and como_root.endswith(
        "./ler_adc 400000 0,1 --blocos 3 -t no cartão -o no_cartao.bin --progresso-json")
    for onde in (*(e.comando for e in b.registro.entradas), *b.servidor.comandos, *b.servidor.comandos_de_root):
        assert SENHA_DO_SUDO not in onde
    assert list((b.servidor.ram).iterdir()) == []


def test_no_cartao_parar_e_o_kill_no_pid(tmp_path, ler_adc):
    """Até o Parar: o ``kill -INT`` no PID (pelo sudo, num comando à parte) fecha a captura como o Ctrl+C."""
    b = Bancada(tmp_path, ler_adc, intervalo_s=0.15)
    progressos = []

    async def cenario():
        async with b.conexao() as c:
            captura = CapturaNoCartao(c, "ate_parar.bin", ao_progresso=progressos.append)
            await captura.iniciar(["400000", "1", "--blocos", "0"], SENHA_DO_SUDO)
            tarefa = asyncio.create_task(captura.acompanhar())
            await esperar(lambda: progressos and progressos[-1].blocos >= 2)
            await captura.parar(SENHA_DO_SUDO)
            gravada = await tarefa
            await captura.limpar()
            return gravada

    gravada = no_cartao(b, cenario)
    assert (gravada.codigo, gravada.motivo, gravada.parada_pedida) == (0, "ok", True) and gravada.blocos >= 2
    arquivo = b.servidor.home / "firmware" / "ate_parar.bin"
    c = cab.ler_cabecalho(arquivo)
    assert c.crc32_valido and c.blocos_gravados == gravada.blocos and not c.fim_pelo_computador
    conferir_blocos(arquivo, gravada.blocos)
    assert any(r.startswith("kill -INT ") for r in b.servidor.comandos_de_root)


def test_no_cartao_a_queda_nao_para_a_captura_e_a_conexao_seguinte_volta_a_acompanhar(tmp_path, ler_adc):
    """O cabo que solta no meio: o acompanhamento cai (ErroDeConexao), a captura segue na placa, e a conexão seguinte
    a acha em curso e a acompanha desde o começo, até o fim com todos os blocos."""
    b = Bancada(tmp_path, ler_adc, intervalo_s=0.15)
    progressos = []

    async def cenario():
        async with b.conexao() as c:
            captura = CapturaNoCartao(c, "sem_cabo.bin", ao_progresso=progressos.append)
            await captura.iniciar(["400000", "1", "--blocos", "8"], SENHA_DO_SUDO)
            tarefa = asyncio.create_task(captura.acompanhar())
            await esperar(lambda: progressos and progressos[-1].blocos >= 2)
            b.servidor.derrubar()
            with pytest.raises(ErroDeConexao):
                await tarefa
        vistos = len(progressos)
        async with b.conexao() as c:
            (achada,) = await em_curso(c)
            outra = CapturaNoCartao(c, achada.nome, ao_progresso=progressos.append)
            gravada = await outra.acompanhar()
            await outra.limpar()
        return achada, vistos, gravada

    achada, vistos, gravada = no_cartao(b, cenario)
    assert achada.nome == "sem_cabo.bin" and progressos[vistos].blocos <= 1         # relido desde o começo
    assert (gravada.codigo, gravada.motivo, gravada.blocos) == (0, "ok", 8)
    conferir_blocos(b.servidor.home / "firmware" / "sem_cabo.bin", 8)


def test_no_cartao_o_pedido_que_o_ler_adc_recusa_e_o_nome_que_existe(tmp_path, ler_adc):
    """O ler_adc que recusa o pedido termina antes do ``inicio``: o acompanhamento diz a causa, e a captura fica em
    curso (terminada) até ser recolhida. Um nome que já existe no cartão não é sobrescrito."""
    b = Bancada(tmp_path, ler_adc)
    existente = b.servidor.home / "firmware" / "existe.bin"
    existente.write_bytes(b"de antes")

    async def cenario():
        async with b.conexao() as c:
            recusada = CapturaNoCartao(c, "recusada.bin")
            await recusada.iniciar(["400000", "9"], SENHA_DO_SUDO)
            try:
                await recusada.acompanhar()
            except ErroDaCaptura as e:
                erro = e
            terminadas = await em_curso(c)
            await recusada.limpar()
            try:
                await CapturaNoCartao(c, "existe.bin").iniciar(["400000", "1"], SENHA_DO_SUDO)
            except ErroDaCaptura as e:
                return erro, terminadas, e

    erro, terminadas, existe = no_cartao(b, cenario, com_pru=False)
    assert erro.codigo == 2 and "canal" in str(erro).lower() and erro.texto
    assert [(t.nome, t.rodando, t.codigo) for t in terminadas] == [("recusada.bin", False, 2)]
    assert existe.codigo == cap.SAIDA_NOME_EXISTE and existente.read_bytes() == b"de antes"
    assert not (b.servidor.home / "firmware" / "recusada.bin").exists()


def test_no_cartao_a_senha_errada_e_o_firmware_antigo(tmp_path, ler_adc):
    b = Bancada(tmp_path, ler_adc)

    async def cenario():
        async with b.conexao() as c:
            try:
                await CapturaNoCartao(c, "x.bin").iniciar(["400000", "1"], "errada")
            except ErroDoSudo as e:
                senha = e
            antigo = b.servidor.home / "firmware" / "ler_adc"
            antigo.unlink()
            antigo.write_text("#!/bin/sh\necho 'Uso: ler_adc FREQ CANAIS [-o ARQUIVO]'\n")
            antigo.chmod(0o755)
            try:
                await CapturaNoCartao(c, "x.bin").iniciar(["400000", "1"], SENHA_DO_SUDO)
            except FirmwareSemSaidaContinua as e:
                return senha, e

    senha, antigo = no_cartao(b, cenario, com_pru=False)
    assert senha.senha_recusada and b.servidor.comandos_de_root == []
    assert antigo.codigo == cap.SAIDA_SEM_SAIDA_CONTINUA
    assert not (b.servidor.home / "firmware" / PASTA_EM_CURSO).exists()


def test_o_roteiro_do_cartao_poe_o_nome_e_recusa_o_que_e_do_receptor():
    for argumentos in (["400000", "1", "-o", "x.bin"], ["400000", "1", "--progresso-json"], []):
        with pytest.raises(ValueError):
            roteiro_de_inicio("a.bin", argumentos)
    for nome in ("", "../a.bin", "p/a.bin", ".escondido.bin"):
        with pytest.raises(ValueError):
            roteiro_de_inicio(nome, ["400000", "1"])
    roteiro = roteiro_de_inicio("rede.bin", ["400000", "0,1", "-t", "título; $(nada)"], "/opt/firmware")
    assert "cd /opt/firmware " in roteiro and "-o rede.bin --progresso-json" in roteiro
    assert "'título; $(nada)'" in roteiro
