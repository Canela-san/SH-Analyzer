"""O simulador da placa (``sh_placa/servidor_do_simulador.py``, F3.9) como a interface o usa: servido por SSH neste computador, só
com a chave dele, com o agente de verdade sobre a árvore falsa, e os cenários (o ADC mudo, o cartão cheio, a conexão
que cai no meio de uma transferência e a retomada, o relógio errado e o acerto dele). E as capturas dele
(``sh_placa/capturas_simuladas.py``): a rede de 60 Hz com supraharmônicos, que o motor lê como as da placa."""

import asyncio
import gc
import os
import sys
import time

import numpy as np
import pytest

pytest.importorskip("asyncssh")

from sh_placa import (
    servidor_do_simulador,  # noqa: E402
    simulador,  # noqa: E402
)
from sh_placa.agente import ClienteDoAgente, TransporteSSH  # noqa: E402
from sh_placa.capturas_simuladas import (  # noqa: E402
    AMOSTRAS_POR_BLOCO_DO_FIRMWARE,
    GANHO_DA_TENSAO,
    Sistema,
    gravar_captura,
)
from sh_placa.conexao import ConexaoSSH, ErroDeAutenticacao, ErroDeConexao  # noqa: E402
from sh_placa.correcoes import acertar_relogio  # noqa: E402
from sh_placa.descoberta import FonteSimulador  # noqa: E402
from sh_placa.destino import SENHA_PADRAO_DA_IMAGEM  # noqa: E402
from sh_placa.registro import RegistroDeAtividade  # noqa: E402
from sh_placa.servidor_do_simulador import FRACAO_DA_QUEDA, ServidorDoSimulador  # noqa: E402
from sh_placa.sftp import SUFIXO_PARCIAL, OrigemSSH, apagar, baixar, conferir  # noqa: E402
from supraharmonicos import cabecalho as motor  # noqa: E402


def entrar(placa: ServidorDoSimulador, registro=None, **kw) -> ConexaoSSH:
    """A conexão do aplicativo com a placa simulada, como a interface a faz: a chave e o known_hosts dela."""
    chave, hosts = placa.acesso()
    return ConexaoSSH(placa.destino, chave=chave, hosts=hosts, registro=registro or RegistroDeAtividade(),
                      senha=placa.senha_do_sudo, **kw)


def test_so_a_chave_do_simulador_entra(tmp_path):
    """Só a chave gerada para ele, no 127.0.0.1: sem senha pelo SSH (ninguém daqui entra com uma senha conhecida), e
    sem terminal (o shell seria o deste computador). O agente de verdade responde pela conexão."""
    async def cenario():
        async with ServidorDoSimulador(tmp_path / "placa", vazao_bytes_s=None) as placa:
            async with entrar(placa) as c:
                saude = await ClienteDoAgente(TransporteSSH(c)).saude()
                autenticada = c.autenticada_com
                terminal = await c.abrir_terminal(80, 24)
                erro = await terminal.stderr.read()
                await terminal.wait_closed()
            outra_chave = ConexaoSSH(placa.destino, chave=simulador_chave(tmp_path), hosts=placa.acesso()[1],
                                     registro=RegistroDeAtividade(), senha=SENHA_PADRAO_DA_IMAGEM)
            with pytest.raises(ErroDeAutenticacao):
                await outra_chave.conectar()
            return placa, saude, autenticada, terminal.exit_status, erro

    placa, saude, autenticada, codigo, erro = asyncio.run(cenario())
    assert autenticada == "chave" and placa.destino.host == "127.0.0.1"
    assert saude.serie == simulador.SERIE_SIMULADA and saude.pronta_para_capturar(simulador.VERSAO_SIMULADA)
    assert codigo == 1 and b"nao tem terminal" in erro
    assert (placa.pasta / "cliente" / "id_ed25519").stat().st_mode & 0o077 == 0


def simulador_chave(tmp_path):
    from sh_placa.chaves import ChaveDoAplicativo
    return ChaveDoAplicativo(tmp_path / "outra")


def test_fechar_apaga_a_pasta_temporaria():
    async def cenario():
        placa = await ServidorDoSimulador(vazao_bytes_s=None).iniciar()
        pasta = placa.pasta
        assert (pasta / "home" / "debian" / "firmware" / "VERSAO").exists()
        await placa.fechar()
        return pasta

    assert not asyncio.run(cenario()).exists()


def test_no_windows_nao_ha_simulador(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert asyncio.run(FonteSimulador()()) == []
    with pytest.raises(RuntimeError, match="POSIX"):
        ServidorDoSimulador()


def test_a_vazao_do_usb(tmp_path):
    """O SFTP do simulador passa na vazão pedida (a do USB, na interface): os blocos em paralelo a dividem."""
    async def cenario():
        async with ServidorDoSimulador(tmp_path / "placa", vazao_bytes_s=2_000_000) as placa:
            arquivo = placa.home / "firmware" / "grande.bin"
            arquivo.write_bytes(np.random.default_rng(1).integers(0, 255, 1_000_000, dtype=np.uint8).tobytes())
            async with entrar(placa) as c:
                t0 = time.monotonic()
                await baixar(OrigemSSH(c), str(arquivo), tmp_path / "copia.bin")
                return time.monotonic() - t0, arquivo.read_bytes()

    gasto, original = asyncio.run(cenario())
    assert 0.45 <= gasto < 2.0 and (tmp_path / "copia.bin").read_bytes() == original


def test_a_conexao_que_cai_no_meio_da_transferencia_e_a_retomada(tmp_path):
    """No cenário da conexão que cai: a transferência é cortada perto de 40 % do arquivo (a parte baixada fica), a
    conexão volta, e a retomada continua dali, sem cair de novo, com a cópia conferida. Os pedidos de leitura em voo
    na queda terminam todos (nenhuma tarefa com a exceção sem dono, que o asyncio só acusaria no coletor de lixo)."""
    async def cenario():
        sem_dono = []
        asyncio.get_running_loop().set_exception_handler(lambda _laco, contexto: sem_dono.append(contexto["message"]))
        async with ServidorDoSimulador(tmp_path / "placa", "conexao_instavel", vazao_bytes_s=None) as placa:
            (captura,) = [f for f in (placa.home / "firmware").glob("rede_bloco_A_*.bin")]
            captura.write_bytes(captura.read_bytes()[:4096])                     # a v9 inteira, de 1 MiB
            gravar_captura(captura, inicio=time.time() - 60, blocos=2, sistema=Sistema("k", "s", "p"),
                           amostras_por_bloco=1 << 18)
            local = tmp_path / "copia.bin"
            quedas = []
            c = entrar(placa, ao_cair=quedas.append)
            await c.conectar()
            with pytest.raises(ErroDeConexao, match="caiu"):
                await baixar(OrigemSSH(c), str(captura), local, bloco=32 * 1024)
            await asyncio.sleep(0.1)
            gc.collect()
            parcial = local.with_name(local.name + SUFIXO_PARCIAL).stat().st_size
            await c.conectar()                                                   # o cabo voltou
            await baixar(OrigemSSH(c), str(captura), local, bloco=32 * 1024)
            resultado = await conferir(OrigemSSH(c), str(captura), local)
            await c.fechar()
            gc.collect()
            return captura.stat().st_size, parcial, quedas, resultado, sem_dono

    total, parcial, quedas, resultado, sem_dono = asyncio.run(cenario())
    assert sem_dono == []
    assert len(quedas) == 1 and "caiu" in quedas[0]
    assert FRACAO_DA_QUEDA * total * 0.5 <= parcial < total                       # parou no meio, e a parte ficou
    assert resultado.ok and resultado.como == "crc32"


def test_a_leitura_cancelada_e_a_queda_logo_depois(tmp_path):
    """Um pedido de leitura cancelado com a resposta ainda a caminho (o :func:`baixar` cancela os outros quando um
    falha) e a conexão que cai logo depois: nada fica rodando nem falha sem dono. O leitor paralelo do asyncssh (o
    ``block_size`` padrão do ``open``) deixava as tarefas dele para trás no cancelamento, e elas falhavam na queda."""
    async def cenario():
        sem_dono = []
        asyncio.get_running_loop().set_exception_handler(lambda _laco, contexto: sem_dono.append(contexto["message"]))
        async with ServidorDoSimulador(tmp_path / "placa", vazao_bytes_s=100_000) as placa:
            captura = placa.home / "firmware" / "longa.bin"
            gravar_captura(captura, inicio=time.time() - 60, blocos=2, sistema=Sistema("k", "s", "p"),
                           amostras_por_bloco=1 << 18)
            c = entrar(placa, ao_cair=lambda _motivo: None)
            await c.conectar()
            leitor = await OrigemSSH(c).abrir(str(captura))
            pedido = asyncio.ensure_future(leitor.ler(0, 256 * 1024))       # ~2,6 s no "cabo" lento
            await asyncio.sleep(0.3)
            pedido.cancel()
            await asyncio.gather(pedido, return_exceptions=True)
            cancelado = pedido.cancelled()
            del pedido                                                          # e o que ele ainda segurava
            placa.derrubar()
            await asyncio.sleep(0.3)
            await leitor.fechar()
            await c.fechar()
        gc.collect()
        return cancelado, sem_dono

    assert asyncio.run(cenario()) == (True, [])


def test_a_conexao_que_cai_de_tempos_em_tempos(tmp_path, monkeypatch):
    """Cada conexão cai depois de :data:`QUEDA_A_CADA_S` (aqui, 0,3 s): a primeira e a seguinte. Com o período longo de
    novo, a que volta fica (um comando roda nela). Sem esperas fixas: com a máquina cheia, a conexão leva mais."""
    monkeypatch.setattr(servidor_do_simulador, "QUEDA_A_CADA_S", 0.3)

    async def ate(condicao, limite_s=10.0):
        t0 = time.monotonic()
        while not condicao():
            assert time.monotonic() - t0 < limite_s, "a queda não veio"
            await asyncio.sleep(0.02)

    async def cenario():
        async with ServidorDoSimulador(tmp_path / "placa", "conexao_instavel", vazao_bytes_s=None) as placa:
            quedas = []
            c = entrar(placa, ao_cair=quedas.append)
            for n in (1, 2):
                await c.conectar()
                await ate(lambda n=n: len(quedas) == n)
            monkeypatch.setattr(servidor_do_simulador, "QUEDA_A_CADA_S", 45.0)
            await c.conectar()                                                    # e volta
            r = await c.executar("echo de volta")
            await c.fechar()
            return quedas, r.saida

    quedas, saida = asyncio.run(cenario())
    assert len(quedas) == 2 and all("caiu" in q for q in quedas) and saida.strip() == "de volta"


def test_o_cartao_cheio_e_apagar_as_capturas(tmp_path):
    """O cartão cheio é um erro do diagnóstico; apagar capturas da placa libera o espaço delas."""
    async def cenario():
        async with ServidorDoSimulador(tmp_path / "placa", "disco_cheio", vazao_bytes_s=None) as placa:
            async with entrar(placa) as c:
                cliente = ClienteDoAgente(TransporteSSH(c))
                antes = await cliente.saude()
                capturas = sorted((placa.home / "firmware").glob("rede_bloco_*.bin"))
                liberado = sum(f.stat().st_size for f in capturas) // 1024
                for f in capturas:
                    await apagar(OrigemSSH(c), str(f))
                depois = await cliente.saude()
            return antes, depois, liberado, len(capturas)

    antes, depois, liberado, n = asyncio.run(cenario())
    assert n == 4 and [p.codigo for p in antes.diagnostico() if p.nivel == "erro"] == ["disco_cheio"]
    assert antes.disco_bytes[0] == simulador.LIVRE_NO_CARTAO_CHEIO_KIB * 1024
    assert depois.disco_bytes[0] == (simulador.LIVRE_NO_CARTAO_CHEIO_KIB + liberado) * 1024
    assert depois.disco_bytes[1] == simulador.CARTAO_KIB * 1024


def test_o_relogio_errado_e_o_acerto(tmp_path):
    """A placa dois dias atrasada, sem NTP; o acerto pelo computador (o sudo dela, com a senha da imagem) a deixa
    com a hora daqui, sem tocar no relógio deste computador."""
    async def cenario():
        async with ServidorDoSimulador(tmp_path / "placa", "relogio_errado", vazao_bytes_s=None) as placa:
            async with entrar(placa) as c:
                cliente = ClienteDoAgente(TransporteSSH(c))
                antes = await cliente.saude()
                acertado = await acertar_relogio(c, c.senha)
                depois = await cliente.saude()
            return antes, acertado, depois

    antes, acertado, depois = asyncio.run(cenario())
    (relogio,) = [p for p in antes.diagnostico() if p.codigo == "relogio"]
    assert "2 dias e 5 h atrasado" in relogio.texto and antes.relogio.sincronizado is False
    assert acertado.erro_antes_s == pytest.approx(simulador.DESVIO_DO_RELOGIO_ERRADO_S, abs=1)
    assert abs(depois.relogio.diferenca_s()) < 0.5 and not [p for p in depois.diagnostico() if p.codigo == "relogio"]


def test_o_adc_mudo(tmp_path):
    async def cenario():
        async with ServidorDoSimulador(tmp_path / "placa", "adc_mudo", vazao_bytes_s=None) as placa:
            async with entrar(placa) as c:
                return await ClienteDoAgente(TransporteSSH(c)).saude()

    saude = asyncio.run(cenario())
    ultima = saude.ultima_captura
    assert ultima.arquivo.startswith("conferir_") and ultima.adc_mudo
    assert [p.codigo for p in saude.diagnostico(simulador.VERSAO_SIMULADA) if p.nivel != "info"] == ["adc_mudo"]


def test_os_cenarios_tem_titulo_e_descricao():
    assert list(simulador.CENARIOS)[:6] == ["normal", "adc_mudo", "disco_cheio", "conexao_instavel",
                                            "firmware_antigo", "relogio_errado"]
    for c in simulador.CENARIOS.values():
        assert c.titulo and c.descricao.endswith(".") and c.grupo in ("uso", "configuracao")
    with pytest.raises(ValueError, match="cenário desconhecido"):
        simulador.montar_sistema_falso("/nao/importa", "nao_existe")


def test_a_captura_simulada_e_a_rede_com_supraharmonicos(tmp_path):
    """Um bloco do firmware (1 048 576 amostras): o motor lê o cabeçalho (o CRC, o ganho, os dois canais), e a tensão
    tem os 127 V de 60 Hz e as emissões de 16 kHz, perto de 40 kHz e de 72 kHz acima do ruído."""
    caminho = gravar_captura(tmp_path / "rede.bin", inicio=1_794_000_000.25, blocos=1, titulo="Rede da casa",
                             sistema=Sistema("4.19.94-ti-r42", "Debian", "A335BNLT 00C0 3714BBBK1234"),
                             amostras_por_bloco=AMOSTRAS_POR_BLOCO_DO_FIRMWARE)
    h = motor.ler_cabecalho(caminho)
    assert h.versao_cabecalho == 9 and h.crc32_valido and h.titulo == "Rede da casa"
    assert (h.frequencia_hz, h.lista_canais, h.total_amostras_gravadas) == (400_000, (0, 1), AMOSTRAS_POR_BLOCO_DO_FIRMWARE)
    assert h.ganho_por_canal == (10.0, GANHO_DA_TENSAO) and h.grandeza_por_canal == (1, 0)
    assert h.timestamp_unix == 1_794_000_000 and caminho.stat().st_mtime == pytest.approx(1_794_000_002.87, abs=0.01)
    codigos = np.fromfile(caminho, dtype="<u2", offset=4096)
    tensao = (codigos[1::2].astype(np.float64) - 32768) * 20.48 / 65536 * GANHO_DA_TENSAO
    assert np.sqrt(np.mean(tensao ** 2)) == pytest.approx(127, rel=0.03)
    espectro = np.abs(np.fft.rfft(tensao * np.hanning(len(tensao))))
    f = np.fft.rfftfreq(len(tensao), 1 / 200_000)

    def pico(f0, largura=300.0):
        faixa = (f > f0 - largura) & (f < f0 + largura)
        return espectro[faixa].max()

    ruido = np.median(espectro[(f > 50_000) & (f < 60_000)])
    for f0 in (16_000, 40_000, 72_000):
        assert pico(f0, 1_600 if f0 == 40_000 else 300) > 30 * ruido, f0
    assert 100 < pico(60, 5) / pico(16_000) < 1000                 # ~0,6 V na tomada: 50 dB abaixo da fundamental


# --- A captura contínua na placa simulada (F4.2) ------------------------------------------------------------------------

def capturar_na_placa(tmp_path, argumentos, *, cenario="normal", ao_progresso=None, nome="ao_vivo.bin"):
    """Uma captura contínua na placa simulada, pelo SSH, como a interface a faz (``sh_placa.captura``). Devolve o
    resultado (ou a exceção) e a placa."""
    from sh_placa.captura import CapturaContinua
    (tmp_path / "capturas").mkdir(parents=True, exist_ok=True)

    async def cenario_():
        async with ServidorDoSimulador(tmp_path / "placa", cenario, vazao_bytes_s=None) as placa:
            async with entrar(placa) as c:
                captura = CapturaContinua(c, argumentos, tmp_path / "capturas" / nome,
                                          senha_do_sudo=SENHA_PADRAO_DA_IMAGEM,
                                          ao_progresso=ao_progresso and (lambda p: ao_progresso(captura, p, placa)))
                try:
                    return await captura.rodar(), placa
                except Exception as e:
                    return e, placa

    return asyncio.run(cenario_())


def test_a_captura_continua_na_placa_simulada(tmp_path):
    """O ``ler_adc -o -`` da placa simulada: 3 blocos da rede com supraharmônicos, em 3 canais (cada bloco começa
    num canal), no ritmo da taxa. O arquivo daqui abre no motor, com o CRC conferido, o título, os canais, a grandeza
    e o ganho pedidos, e o sinal de cada canal é o das amostras."""
    from supraharmonicos import api
    r, placa = capturar_na_placa(tmp_path, ["400000", "0,1,2", "--blocos", "3", "-t", "Ao vivo", "--grandeza",
                                            "0:corrente,2:corrente", "--ganho", "0:10,1:19.357"])
    assert not isinstance(r, Exception), r
    assert (r.codigo, r.motivo, r.caiu, r.blocos, r.fechamento.crc_confere) == (0, "ok", False, 3, True)
    bloco = simulador.capturas_simuladas.BLOCO_DAS_CAPTURAS
    assert r.duracao_s >= 3 * bloco / 400_000                 # no ritmo da taxa
    c = motor.ler_cabecalho(r.arquivo)
    assert (c.titulo, c.lista_canais, c.blocos_gravados, c.samples_per_buffer) == ("Ao vivo", (0, 1, 2), 3, bloco)
    assert c.grandeza_por_canal == (1, 0, 1) and c.ganho_por_canal == (10.0, 19.357, None)
    assert c.versao_firmware == simulador.VERSAO_SIMULADA and c.placa.endswith(simulador.SERIE_SIMULADA)
    assert c.linha_de_comando.endswith("-o - --progresso-json")
    # O disco da saída contínua é o de quem recebe, que o ler_adc não vê; o do programa é o cartão.
    assert (c.disco_saida_total_kib, c.disco_saida_livre_kib, c.disco_saida_livre_fim_kib) == (None, None, None)
    assert c.disco_programa_total_kib == simulador.CARTAO_KIB
    captura = api.abrir_captura(r.arquivo)
    assert api.conferir_integridade(captura) is True
    tensao = np.fromfile(r.arquivo, dtype="<u2", offset=c.tamanho_cabecalho)[1::3]
    assert c.codigo_minimo_por_canal[1] == tensao.min() and c.codigo_maximo_por_canal[1] == tensao.max()
    assert (tensao.max() - 32768) * 20.48 / 65536 * 19.357 == pytest.approx(127 * 2 ** 0.5, rel=0.1)   # a tomada
    assert any("Captura concluída" in linha for linha in r.texto)


def test_parar_e_a_queda_na_placa_simulada(tmp_path):
    """Até o Parar (o SIGINT no ler_adc simulado: o cabeçalho final dele) e o cabo que solta (o fim escrito aqui)."""
    r, _ = capturar_na_placa(tmp_path, ["400000", "1", "--blocos", "0"],
                             ao_progresso=lambda captura, p, placa: p.blocos >= 3 and captura.parar())
    assert (r.codigo, r.motivo, r.caiu, r.parada_pedida) == (0, "ok", False, True) and r.blocos >= 3
    assert r.fechamento.crc_confere is True
    r, _ = capturar_na_placa(tmp_path / "queda", ["400000", "1", "--blocos", "0"], nome="caiu.bin",
                             ao_progresso=lambda captura, p, placa: p.blocos >= 3 and placa.derrubar())
    assert (r.motivo, r.caiu) == ("conexao_caiu", True) and r.blocos >= 3
    c = motor.ler_cabecalho(r.arquivo)
    assert c.fim_pelo_computador and motor.conferir_crc_das_amostras(r.arquivo, c) is True


def test_a_captura_continua_nos_cenarios(tmp_path):
    """O ADC mudo (um bloco em 0, o código 4), o firmware de antes da saída contínua (o aviso para atualizar) e a PRU
    com falha (o erro do ler_adc, antes de qualquer amostra)."""
    from sh_placa.captura import ErroDaCaptura, FirmwareSemSaidaContinua
    r, _ = capturar_na_placa(tmp_path / "mudo", ["400000", "0,1", "--blocos", "5"], cenario="adc_mudo")
    assert (r.codigo, r.motivo, r.blocos) == (4, "adc_mudo", 1)
    assert any("o ADC não está respondendo" in linha for linha in r.texto)
    assert motor.ler_cabecalho(r.arquivo).codigo_maximo_por_canal == (0, 0)
    r, placa = capturar_na_placa(tmp_path / "antigo", ["400000", "1"], cenario="firmware_antigo")
    assert isinstance(r, FirmwareSemSaidaContinua) and placa.comandos_de_root == []
    r, _ = capturar_na_placa(tmp_path / "pru", ["400000", "1"], cenario="pru_com_falha")
    assert isinstance(r, ErroDaCaptura) and r.codigo == 1 and "a PRU não ficou pronta" in str(r)
    assert list((tmp_path / "pru" / "capturas").iterdir()) == []


def test_o_ler_adc_simulado_grava_no_cartao_e_recusa_o_que_o_de_verdade_recusa(tmp_path):
    """Com ``-o ARQUIVO`` (o destino no cartão): o arquivo na pasta do firmware, o cabeçalho final no começo; os
    erros de uso do ``ler_adc`` (o código 2, com a mensagem dele); e a ajuda, com o ``-o -`` (a do firmware antigo,
    sem)."""
    import subprocess
    pasta = tmp_path / "placa"
    raiz, firmware = simulador.montar_sistema_falso(pasta)
    ambiente = {"PATH": os.environ["PATH"], "HOME": str(firmware.parent), "SHAN_RAIZ": str(raiz)}

    def ler_adc(*argumentos, cwd=firmware):
        return subprocess.run(["sh", str(firmware / "ler_adc"), *argumentos], cwd=cwd, env=ambiente,
                              capture_output=True, text=True, timeout=60)

    r = ler_adc("400000", "0,1", "--blocos", "2", "-o", "no_cartao.bin", "-t", "No cartão")
    assert r.returncode == 0, r.stderr
    c = motor.ler_cabecalho(firmware / "no_cartao.bin")
    assert c.crc32_valido and c.blocos_gravados == 2 and c.titulo == "No cartão"
    assert motor.conferir_crc_das_amostras(firmware / "no_cartao.bin", c) is True
    # O disco é o cartão, e a captura gasta o tamanho dela entre o livre do início e o do fim.
    assert c.disco_saida_total_kib == c.disco_programa_total_kib == simulador.CARTAO_KIB
    gasto = c.disco_saida_livre_kib - c.disco_saida_livre_fim_kib
    assert gasto == pytest.approx((firmware / "no_cartao.bin").stat().st_size / 1024, abs=2)
    # A faixa, a sonda, a grandeza, o SPI e as esperas de CS vão para o cabeçalho, como no de verdade; o canal da
    # tomada (±9 V no pino) satura em ±2,56 V.
    r = ler_adc("300000", "1,0", "--blocos", "1", "-o", "opcoes.bin", "--faixa-adc", "1:5.12",
                "--grandeza", "0:corrente,1:temperatura", "--sonda", "0:sct013_100a_sn001", "--ganho", "0:19.65",
                "--spi", "lenta", "--atraso-cs", "4,1,3")
    assert r.returncode == 0, r.stderr
    c = motor.ler_cabecalho(firmware / "opcoes.bin")
    assert c.lista_canais == (0, 1) and c.faixa_adc_codigo_por_canal == (0, 2)
    assert c.grandeza_por_canal == (1, 2) and c.sonda_id_por_canal == ("sct013_100a_sn001", "")
    assert c.ganho_por_canal == (19.65, None) and c.modo_spi == 0 and c.atraso_cs_iteracoes == (4, 1, 3)
    assert c.amostras_saturadas_por_canal[0] == 0 < c.amostras_saturadas_por_canal[1]
    for argumentos, mensagem in ((["400k"], "frequência inválida"), (["400000", "0,9"], "canal '9' inválido"),
                                 (["400000", "1", "--blocos", "-1"], "--blocos"),
                                 (["400000", "1", "--nada"], "opção desconhecida '--nada'"),
                                 (["400000", "1", "--blocos", "1", "--duracao", "1s"], "não podem ser usados juntos"),
                                 (["420000"], "teto da PRU"), (["--faixa-adc", "1:5"], "faixa '5'")):
        r = ler_adc(*argumentos)
        assert r.returncode == 2 and mensagem in r.stderr, (argumentos, r.stderr)
    assert "--progresso-json" in ler_adc("--help").stdout
    antigo = tmp_path / "antigo"
    simulador.montar_sistema_falso(antigo, "firmware_antigo")
    firmware = antigo / "home" / "debian" / "firmware"
    assert "--progresso-json" not in ler_adc("--help", cwd=firmware).stdout


def test_a_captura_no_cartao_na_placa_simulada_e_a_transferencia(tmp_path):
    """O ``ler_adc -o NOME`` desacoplado da conexão (``sh_placa.captura_no_cartao``) na placa simulada: o
    progresso pelo tail, a captura no cartão listada pelo agente, como as outras, e trazida pelo SFTP com o SHA-256
    conferido. A pasta em curso some quando recolhida."""
    from sh_placa.captura_no_cartao import CapturaNoCartao, em_curso
    progressos = []

    async def cenario():
        async with ServidorDoSimulador(tmp_path / "placa", vazao_bytes_s=None) as placa:
            async with entrar(placa) as c:
                captura = CapturaNoCartao(c, "no_cartao_simulado.bin", ao_progresso=progressos.append)
                await captura.iniciar(["400000", "0,1", "--blocos", "2", "-t", "No cartão"], SENHA_PADRAO_DA_IMAGEM)
                gravada = await captura.acompanhar()
                await captura.limpar()
                capturas = await ClienteDoAgente(TransporteSSH(c)).capturas()
                remoto = f"{capturas.pasta}/{gravada.nome}"
                origem = OrigemSSH(c)
                local = tmp_path / "trazida.bin"
                await baixar(origem, remoto, local)
                return gravada, capturas.capturas, await conferir(origem, remoto, local), await em_curso(c), placa

    gravada, listadas, conferida, depois, placa = asyncio.run(cenario())
    assert (gravada.codigo, gravada.motivo, gravada.blocos) == (0, "ok", 2) and progressos[-1].blocos == 2
    (nova,) = [c for c in listadas if c.arquivo == "no_cartao_simulado.bin"]
    assert nova.titulo == "No cartão" and depois == []
    assert conferida.ok and motor.ler_cabecalho(tmp_path / "trazida.bin").blocos_gravados == 2


def test_a_placa_simulada_que_para_leva_a_captura_no_cartao_junto(tmp_path):
    """Uma captura "até parar" no cartão sobrevive à conexão (o ``setsid``), mas não à placa simulada: o simulador
    que para mata o grupo dela, como a placa desligada. Sem isso, ela seguiria neste computador depois do aplicativo
    fechar. A que terminou (com o ``codigo``) fica como está."""
    from sh_placa import captura_no_cartao, servidor_do_simulador
    from sh_placa.captura_no_cartao import CapturaNoCartao, em_curso

    assert servidor_do_simulador.PASTA_EM_CURSO == captura_no_cartao.PASTA_EM_CURSO
    vistos = []

    async def cenario():
        async with ServidorDoSimulador(tmp_path / "placa", vazao_bytes_s=None) as placa:
            async with entrar(placa) as c:
                captura = CapturaNoCartao(c, "ate_parar.bin", ao_progresso=vistos.append)
                await captura.iniciar(["400000", "1", "--blocos", "0"], SENHA_PADRAO_DA_IMAGEM)
                acompanhar = asyncio.create_task(captura.acompanhar())
                while not vistos or vistos[-1].blocos < 1:
                    await asyncio.sleep(0.05)
                (rodando,) = await em_curso(c)
                acompanhar.cancel()
            pasta = placa.home / "firmware" / captura_no_cartao.PASTA_EM_CURSO / "ate_parar.bin"
            return rodando, int((pasta / "pid").read_text())

    rodando, pid = asyncio.run(cenario())
    assert rodando.rodando
    fim = time.monotonic() + 5
    while time.monotonic() < fim:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(pid, 9)
        pytest.fail("a captura no cartão seguiu rodando depois de a placa simulada parar")
