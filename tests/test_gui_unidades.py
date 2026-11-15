"""As unidades dos traços (``sh_analyzer_gui.dados.unidades``): o catálogo, a validação, a conversão entre as de uma
família e os rótulos dos eixos. Sem Qt."""

import math

import pytest
from sh_analyzer_gui.dados import unidades
from sh_analyzer_gui.dados.unidades import CATALOGO, PRINCIPAIS, Unidade, UnidadeInvalida


@pytest.fixture(autouse=True)
def sem_proprias():
    unidades.definir_proprias(())
    yield
    unidades.definir_proprias(())


def test_as_principais_vem_primeiro_e_os_simbolos_sao_unicos():
    assert tuple(u.simbolo for u in CATALOGO[:len(PRINCIPAIS)]) == PRINCIPAIS
    simbolos = [u.simbolo for u in CATALOGO]
    assert len(simbolos) == len(set(simbolos))
    for u in CATALOGO:                                   # o catálogo inteiro passa na própria validação
        assert unidades.validar_simbolo(u.simbolo) == u.simbolo and u.grandeza and u.a > 0


@pytest.mark.parametrize("de, para, valor, esperado", [
    ("°C", "K", 0.0, 273.15), ("K", "°C", 0.0, -273.15), ("°C", "°F", 100.0, 212.0), ("°F", "°C", -40.0, -40.0),
    ("°F", "K", 32.0, 273.15), ("bar", "Pa", 1.0, 1e5), ("atm", "psi", 1.0, 14.695948775513),
    ("psi", "bar", 1.0, 0.0689475729), ("mmHg", "Pa", 1.0, 133.322387415), ("g", "m/s²", 1.0, 9.80665),
    ("km/h", "m/s", 36.0, 10.0), ("rpm", "Hz", 3000.0, 50.0), ("°", "rad", 180.0, math.pi),
    ("L/min", "m³/h", 1.0, 0.06), ("V", "V", 2.5, 2.5), ("kWh", "J", 1.0, 3.6e6),
    ("V", "mV", 1.5, 1500.0), ("mA", "A", 20.0, 0.02), ("kPa", "bar", 250.0, 2.5), ("µm", "mm", 1500.0, 1.5),
    ("uV", "V", 3.0, 3e-6), ("mg", "m/s²", 1000.0, 9.80665), ("mm/s", "m/s", 250.0, 0.25),
])
def test_conversao_dentro_da_familia(de, para, valor, esperado):
    c, d = unidades.conversao(de, para)
    assert c * valor + d == pytest.approx(esperado, rel=1e-9, abs=1e-12)
    volta = unidades.conversao(para, de)                 # a volta desfaz a ida
    assert volta[0] * (c * valor + d) + volta[1] == pytest.approx(valor, rel=1e-9, abs=1e-12)


@pytest.mark.parametrize("de, para", [("V", "A"), ("°C", "Pa"), ("%", "%RH"), ("xyz", "V"), ("Hz", "rad"),
                                      ("m°C", "°C"), ("mkg", "kg"), ("mmV", "V"), ("kxyz", "xyz")])
def test_sem_conversao_entre_familias_ou_fora_do_catalogo(de, para):
    assert unidades.conversao(de, para) is None


@pytest.mark.parametrize("simbolo, trecho", [
    ("", "vazia"), ("   ", "vazia"), ("x" * 17, "16"), ("m s", "espaços"), ("V\nA", "espaços|controle"),
    ("a\tb", "espaços|controle"), ("\x00", "controle"), (3, "texto"),
])
def test_simbolos_invalidos(simbolo, trecho):
    with pytest.raises(UnidadeInvalida, match=trecho):
        unidades.validar_simbolo(simbolo)


def test_simbolo_valido_sai_sem_os_espacos_das_pontas():
    assert unidades.validar_simbolo("  kgf/cm²  ") == "kgf/cm²"
    assert unidades.validar_simbolo("x" * 16) == "x" * 16


def test_prefixos_e_grandezas():
    assert unidades.aceita_prefixos("V") and unidades.aceita_prefixos("Pa") and unidades.aceita_prefixos("S/s")
    assert not unidades.aceita_prefixos("°C") and not unidades.aceita_prefixos("%")
    assert not unidades.aceita_prefixos("kg")            # o "k" já está no símbolo: não vira "Mg"
    assert unidades.grandeza("°F") == "temperatura" and unidades.grandeza("rpm") == "rotação"
    assert unidades.grandeza("xyz") == ""


def test_os_multiplos_das_que_aceitam_prefixo():
    ma = unidades.procurar("mA")
    assert (ma.grandeza, ma.familia, ma.prefixos) == ("corrente", "corrente", False)
    assert ma.a == pytest.approx(1e-3)
    assert unidades.procurar("kPa").a == pytest.approx(1e3) and unidades.grandeza("µε") == "deformação"
    assert unidades.procurar("m°C") is None and unidades.procurar("k%") is None      # sem prefixo
    assert unidades.procurar("kg").a == 1.0               # a do catálogo, não o quilo de "g" (a aceleração)
    assert not unidades.aceita_prefixos("mV")             # "1500 mV", nunca "1,5 kmV"


@pytest.mark.parametrize("razao, aceita", [("°C/V", False), ("mV/V", False), ("V/A", True), ("%/V", False),
                                           ("Pa/V", True), ("S/s", True), ("/V", True)])
def test_numa_razao_vale_o_numerador(razao, aceita):
    assert unidades.aceita_prefixos(razao) is aceita


def test_unidades_proprias_entram_sem_repetir_o_catalogo():
    unidades.definir_proprias([Unidade("ppm", "concentração", prefixos=False), Unidade("V", "outra"),
                               Unidade("ppm", "repetida"), Unidade("dB", "nível", prefixos=False)])
    assert [u.simbolo for u in unidades.proprias()] == ["ppm", "dB"]
    assert unidades.todas()[-2:] == unidades.proprias()
    assert unidades.grandeza("ppm") == "concentração" and not unidades.aceita_prefixos("dB")
    assert unidades.grandeza("V") == "tensão"            # a do catálogo vale
    unidades.definir_proprias(())
    assert unidades.procurar("ppm") is None and unidades.aceita_prefixos("ppm")


@pytest.mark.parametrize("da_receita, do_canal, grandeza_do_canal, esperado", [
    ("", "V", "tensão", ("tensão", "V")),
    ("V", "V", "tensão", ("tensão", "V")),
    ("°C", "V", "tensão", ("temperatura", "°C")),
    ("kgf", "A", "corrente", ("", "kgf")),
])
def test_grandeza_e_unidade_do_traco(da_receita, do_canal, grandeza_do_canal, esperado):
    assert unidades.do_traco(da_receita, do_canal, grandeza_do_canal) == esperado


def test_rotulo_do_eixo():
    assert unidades.rotulo("temperatura", "°C") == "temperatura (°C)"
    assert unidades.rotulo("", "kgf") == "valor (kgf)"
    assert unidades.rotulo("", "") == "valor" and unidades.rotulo("tensão", "") == "tensão"
