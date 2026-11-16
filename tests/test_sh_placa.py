"""O ``sh_placa`` (a BeagleBone vista do computador): o cliente do agente, cada resposta lida (o estado, a saúde com o
diagnóstico, o relógio, as capturas, os logs), o diagnóstico em cada cenário do simulador, as conferências que só o
computador faz e as respostas que não se entendem. Sem Qt e sem placa."""

import asyncio
import sys
import time

import numpy as np
import pytest
from capturas_sinteticas import escrever_bin
from sh_placa.agente import ClienteDoAgente, ErroDaPlaca, TransporteLocal
from sh_placa.estado import CapturaNaPlaca, EstadoDaPlaca, LogsDaPlaca, Problema, RelogioDaPlaca
from sh_placa.simulador import CENARIOS, SERIE_SIMULADA, VERSAO_SIMULADA, Simulador, montar_sistema_falso

DIAGNOSTICO_DE_CADA_CENARIO = {
    "normal": [], "pru_com_falha": ["pru_com_falha"], "pinos_errados": ["pinos"], "sem_mem_496m": ["mem_496m"],
    "firmware_antigo": ["firmware_diferente"], "sem_compilar": ["nao_compilado"],
    "pru_desatualizada": ["pru_desatualizada"], "audio_hdmi": ["audio_hdmi", "pinos"],
    "sem_overlay_da_pru": ["pru_ausente"],
}


@pytest.mark.parametrize("cenario", CENARIOS)
def test_diagnostico_de_cada_cenario(cenario):
    with Simulador(cenario) as cliente:
        estado = asyncio.run(cliente.saude())
    assert estado.serie == SERIE_SIMULADA and estado.nome_da_placa == "BeagleBone Black"
    assert estado.kernel == "4.19.94-ti-r42" and estado.sistema.startswith("BeagleBoard.org Debian Buster")
    problemas = estado.diagnostico(VERSAO_SIMULADA)
    codigos = [p.codigo for p in problemas if p.nivel != "info"]
    assert codigos == DIAGNOSTICO_DE_CADA_CENARIO[cenario]
    if codigos:
        assert problemas[0].correcao                                   # todo problema diz como corrigir
    erro = any(p.nivel == "erro" for p in problemas)
    assert erro is (cenario not in ("normal", "firmware_antigo"))
    assert estado.pronta_para_capturar(VERSAO_SIMULADA) is not erro
    assert [p.codigo for p in problemas if p.nivel == "info"] == ["capturas"]


def test_o_estado_nao_tem_o_diagnostico():
    """O ``estado`` é o leve (a barra, a visão geral); o diagnóstico vem da ``saude``, e pedir um ao outro é um erro
    de quem chama, e não uma lista vazia que pareceria uma placa boa."""
    with Simulador() as cliente:
        estado = asyncio.run(cliente.estado())
    assert estado.serie == SERIE_SIMULADA and not estado.tem_diagnostico
    with pytest.raises(ValueError, match="saúde"):
        estado.diagnostico()


def test_as_conferencias_do_computador_e_a_ordem():
    agora = 2_000_000_000.0
    estado = EstadoDaPlaca({"firmware": {"firmware": "v0.7.0"}, "relogio": {"utc": agora - 41.7}, "conferencias": [
        {"nivel": "info", "codigo": "capturas", "texto": "2 captura(s) na placa (0 MiB)."},
        {"nivel": "aviso", "codigo": "disco", "texto": "Pouco espaço.", "correcao": "Transferir."},
        {"nivel": "erro", "codigo": "pinos", "texto": "Pinos.", "correcao": "config-pin"},
        {"nivel": "critico", "codigo": "de_um_agente_mais_novo", "texto": "?"},
    ]}, recebido_em=agora)
    problemas = estado.diagnostico("v0.8-137-g9b0ae82")
    assert [(p.nivel, p.codigo) for p in problemas] == [
        ("erro", "pinos"), ("aviso", "disco"), ("aviso", "de_um_agente_mais_novo"), ("aviso", "firmware_diferente"),
        ("aviso", "relogio"), ("info", "capturas")]
    relogio = next(p for p in problemas if p.codigo == "relogio")
    assert "-42 s do computador" in relogio.texto and relogio.correcao
    assert "(v0.7.0) não é o deste aplicativo (v0.8-137-g9b0ae82)" in problemas[3].texto
    assert [p.codigo for p in estado.diagnostico(None, agora=agora - 41.0)] == ["pinos", "disco",
                                                                               "de_um_agente_mais_novo", "capturas"]
    assert not estado.pronta_para_capturar()
    assert Problema.de_json({}) == Problema("aviso", "desconhecido", "", None)


def test_o_relogio_entre_dois_limites():
    """A diferença fica entre a chegada da resposta e o pedido menos o tempo do processo na placa; a estimativa é o
    meio. Sem o tempo do processo, a chegada; com os limites cruzados (o relógio do computador pulou), também."""
    pedido = 1_794_788_911.0
    dados = {"utc": pedido + 0.5 + 0.2 + 0.4, "sincronizado": False, "fonte": "adjtimex", "desde_o_inicio_s": 0.4}
    # A placa está +0,5 s; o processo começou 0,2 s depois do pedido e leu a hora 0,4 s depois; a resposta levou 0,1 s.
    relogio = RelogioDaPlaca.de_json(dados, recebido_em=pedido + 0.2 + 0.4 + 0.1, enviado_em=pedido)
    assert relogio.limites_s == pytest.approx((0.4, 0.7)) and relogio.diferenca_s() == pytest.approx(0.55)
    assert relogio.incerteza_s == pytest.approx(0.15) and relogio.diferenca_s(agora=pedido) == pytest.approx(1.1)
    sem_o_tempo = RelogioDaPlaca.de_json({**dados, "desde_o_inicio_s": None}, recebido_em=pedido + 0.7)
    assert sem_o_tempo.limites_s is None and sem_o_tempo.diferenca_s() == pytest.approx(0.4)
    cruzados = RelogioDaPlaca.de_json(dados, recebido_em=pedido + 0.2, enviado_em=pedido + 0.9)
    assert cruzados.limites_s is None and cruzados.diferenca_s() == pytest.approx(0.9)
    estado = EstadoDaPlaca({"conferencias": [], "relogio": {**dados, "utc": pedido + 41.7}},
                           recebido_em=pedido + 0.7, enviado_em=pedido)
    (problema,) = estado.diagnostico()
    assert problema.codigo == "relogio" and "+41 s do computador" in problema.texto


def test_o_relogio_do_simulador():
    with Simulador() as cliente:
        antes = time.time()
        relogio = asyncio.run(cliente.relogio())
    assert antes <= relogio.enviado_em <= relogio.recebido_em <= time.time()
    assert (relogio.sincronizado, relogio.fonte) == (True, "timesyncd")
    if sys.platform.startswith("linux"):                        # o mesmo relógio: a diferença é zero, dentro da faixa
        baixo, alto = relogio.limites_s
        assert baixo <= 0.0 <= alto and relogio.incerteza_s < 1.0


def test_as_capturas_e_as_coletas(tmp_path):
    raiz, pasta = montar_sistema_falso(tmp_path)
    t = np.arange(4096) / 200_000.0
    sinal = [np.sin(2 * np.pi * 60 * t), 0.5 * np.sin(2 * np.pi * 60 * t)]
    boa = escrever_bin(pasta / "rede_casa.bin", sinal, fs_total=400_000, versao=9, titulo="Rede da casa")
    (pasta / "COLETA_1").mkdir()
    ruim = escrever_bin(pasta / "COLETA_1" / "ruim.bin", sinal, fs_total=400_000, versao=9, integridade=(12, 1, 3))
    ruim.write_bytes(ruim.read_bytes()[:-100])
    (pasta / "COLETA_1" / "resumo.csv").write_text("parte,arquivo,sinal\nE,ruim.bin,fraco\n")
    capturas = asyncio.run(ClienteDoAgente(TransporteLocal(raiz=raiz, pasta_firmware=pasta)).capturas())
    assert capturas.existe and capturas.total == 4 and capturas.bytes == sum(c.bytes for c in capturas.capturas)
    por_nome = {c.arquivo: c for c in capturas.capturas}
    rede = por_nome["rede_casa.bin"]
    assert (rede.titulo, rede.taxa_hz, rede.canais, rede.bytes) == ("Rede da casa", 400_000, (0, 1), boa.stat().st_size)
    assert rede.duracao_s == pytest.approx(8192 / 400_000) and rede.problemas == []
    assert por_nome["COLETA_1/ruim.bin"].problemas == [
        f"o arquivo tem {ruim.stat().st_size} bytes, e o cabeçalho diz {ruim.stat().st_size + 100}: cortado, ou com "
        "outro grudado", "1 buffer(s) sobrescrito(s): amostras perdidas",
        "12 amostra(s) atrasada(s): a taxa real é menor", "3 quadro(s) com ruído na linha SDO"]
    # As do simulador são "SHAN" e zeros (a F3.9 as troca pelas sintéticas): o cabeçalho não confere.
    assert por_nome["conferir_0844.bin"].problemas[0] == "o cabeçalho está corrompido (o CRC não confere)"
    (coleta,) = capturas.coletas
    assert coleta.pasta == "COLETA_1" and coleta.linhas_como_dicts() == [{"parte": "E", "arquivo": "ruim.bin",
                                                                         "sinal": "fraco"}]
    assert CapturaNaPlaca.de_json({"arquivo": "velha.bin", "bytes": 10}).problemas == [
        "sem o cabeçalho (de um firmware antigo, ou outro arquivo)"]


def test_os_logs():
    with Simulador() as cliente:
        logs = asyncio.run(cliente.logs(20))
    assert len(logs.kernel) == 6 and [linha.origem for linha in logs.diario] == ["sudo", "wpa_supplicant"]
    todas = logs.todas()
    assert len(todas) == 8 and [linha.utc for linha in todas] == sorted(linha.utc for linha in todas)
    assert [linha.erro for linha in logs.kernel] == [False] * 5 + [True]
    assert LogsDaPlaca.de_json({"kernel": None, "diario": []}) == LogsDaPlaca(None, ())


class Respostas:
    def __init__(self, codigo, saida, erro=""):
        self.r = (codigo, saida, erro)

    async def executar(self, argv):
        return self.r


@pytest.mark.parametrize("resposta, trecho", [
    (Respostas(1, "", "Traceback ... SyntaxError"), "não é JSON"),
    (Respostas(0, "isto não é json"), "não é JSON"),
    (Respostas(0, '{"protocolo": 2, "agente": "9"}'), "protocolo 2"),
    (Respostas(2, '{"protocolo": 1, "erro": "comando desconhecido"}'), "recusou"),
    (Respostas(3, '{"protocolo": 1}'), "código 3"),
    (Respostas(127, "", "sh: 1: python3: not found"), "não tem o python3"),
])
def test_respostas_que_nao_se_entendem(resposta, trecho):
    with pytest.raises(ErroDaPlaca, match=trecho):
        asyncio.run(ClienteDoAgente(resposta).estado())


def test_o_relogio_sem_a_hora():
    with pytest.raises(ErroDaPlaca, match="sem a hora"):
        asyncio.run(ClienteDoAgente(Respostas(0, '{"protocolo": 1, "sincronizado": true}')).relogio())


def test_a_ultima_linha_e_a_resposta():
    """Um aviso impresso antes (a placa às vezes escreve no stdout ao logar) não estraga a resposta."""
    cliente = ClienteDoAgente(Respostas(0, 'Aviso qualquer\n{"protocolo": 1, "firmware": "v1"}\n'))
    assert asyncio.run(cliente.versao())["firmware"] == "v1"
