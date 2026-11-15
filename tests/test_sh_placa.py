"""O ``sh_placa`` (a BeagleBone vista do computador): o cliente do agente, o diagnóstico em cada cenário do simulador
e as respostas que não se entendem. Sem Qt e sem placa."""

import asyncio

import pytest
from sh_placa.agente import ClienteDoAgente, ErroDaPlaca
from sh_placa.estado import EstadoDaPlaca
from sh_placa.simulador import CENARIOS, SERIE_SIMULADA, VERSAO_SIMULADA, Simulador


@pytest.mark.parametrize("cenario, codigo", [
    ("normal", None), ("pru_com_falha", "pru_com_falha"), ("pinos_errados", "pinos"), ("sem_mem_496m", "mem_496m"),
    ("firmware_antigo", "firmware_diferente"), ("sem_compilar", "nao_compilado"),
])
def test_diagnostico_de_cada_cenario(cenario, codigo):
    assert cenario in CENARIOS
    with Simulador(cenario) as cliente:
        estado = asyncio.run(cliente.estado())
    assert estado.serie == SERIE_SIMULADA and estado.nome_da_placa == "BeagleBone Black"
    problemas = estado.diagnostico(VERSAO_SIMULADA)
    codigos = [p.codigo for p in problemas if p.nivel != "info"]
    assert codigos == ([] if codigo is None else [codigo])
    if codigo is not None:
        assert problemas[0].correcao                                   # todo problema diz como corrigir
    erro = codigo in ("pru_com_falha", "pinos", "mem_496m", "nao_compilado")
    assert estado.pronta_para_capturar(VERSAO_SIMULADA) is not erro
    assert [p.codigo for p in problemas if p.nivel == "info"] == ["capturas"]


@pytest.mark.parametrize("estado_pru, codigos", [
    ("running", []), ("offline", []),            # capturando; entre uma captura e outra (o ler_adc a liga e a para)
    ("crashed", ["pru_com_falha"]), ("suspended", ["pru_com_falha"]), (None, ["pru_ausente"]),
])
def test_a_pru_parada_entre_capturas_e_o_normal(estado_pru, codigos):
    """Na placa de verdade (15/11/2026), depois de uma captura a PRU0 fica ``offline``, e a placa está pronta: o
    diagnóstico dizia "não rodando" e a placa, não pronta para capturar."""
    estado = EstadoDaPlaca({"pru": {} if estado_pru is None else {"estado": estado_pru},
                            "firmware": {"firmware": "v1", "compilado": True},
                            "memoria_dos_buffers": {"mem_496m": True}, "pinos": {}})
    assert [p.codigo for p in estado.diagnostico("v1") if p.nivel == "erro"] == codigos
    assert estado.pronta_para_capturar("v1") is not codigos


def test_relogio_disco_e_temperatura():
    agora = 2_000_000_000.0
    estado = EstadoDaPlaca({"relogio": {"utc": agora - 41.7}, "disco": {"livre_kib": 500 * 1024},
                            "temperatura_c": 81.0, "firmware": {"firmware": "v1", "compilado": True},
                            "pru": {"estado": "running"}, "memoria_dos_buffers": {"mem_496m": True}, "pinos": {}})
    codigos = [p.codigo for p in estado.diagnostico("v1", agora=agora)]
    assert codigos == ["relogio", "disco", "temperatura"]
    assert estado.minutos_de_captura_no_disco == pytest.approx(500 * 1024 * 1024 / 800_000 / 60)
    vazio = EstadoDaPlaca({})
    assert [p.codigo for p in vazio.diagnostico()] == ["pru_ausente", "mem_desconhecida", "versao_desconhecida"]
    assert vazio.nome_da_placa == "BeagleBone" and vazio.minutos_de_captura_no_disco is None


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


def test_a_ultima_linha_e_a_resposta():
    """Um aviso impresso antes (a placa às vezes escreve no stdout ao logar) não estraga a resposta."""
    cliente = ClienteDoAgente(Respostas(0, 'Aviso qualquer\n{"protocolo": 1, "firmware": "v1"}\n'))
    assert asyncio.run(cliente.versao())["firmware"] == "v1"
