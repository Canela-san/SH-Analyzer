"""Ler e escrever números com prefixo do SI (``sh_analyzer_gui.componentes.numeros``). Sem Qt."""

import math

import pytest
from sh_analyzer_gui.componentes.numeros import NumeroInvalido, formatar_si, ler_numero


@pytest.mark.parametrize("texto, unidade, valor", [
    ("2500", "", 2500.0), ("2,5k", "", 2500.0), ("2.5k", "", 2500.0), ("2,5 k", "", 2500.0),
    ("1,2 mV", "V", 1.2e-3), ("1,2mV", "V", 1.2e-3), ("3e-6", "", 3e-6), ("-3,3 m", "", -3.3e-3),
    ("4,7µ", "", 4.7e-6), ("4,7u", "", 4.7e-6), ("10 MHz", "Hz", 1e7), ("100 n", "", 1e-7), ("2 p", "", 2e-12),
    ("1.234,5", "", 1234.5), ("1,234.5", "", 1234.5), ("1.500", "", 1.5), ("+7", "", 7.0), ("0,5 V", "V", 0.5),
    ("5 m", "m", 5.0), ("5 mm", "m", 5e-3), ("1 000", "", 1000.0), (" 12 ", "", 12.0),
])
def test_ler_numero(texto, unidade, valor):
    assert ler_numero(texto, unidade) == pytest.approx(valor)


@pytest.mark.parametrize("texto, unidade", [
    ("", ""), ("abc", ""), ("1,2,3", ""), ("1.2.3", ""), ("2 kHz", "V"), ("2 x", ""), ("inf", ""), ("1e999", ""),
])
def test_ler_numero_invalido(texto, unidade):
    with pytest.raises(NumeroInvalido):
        ler_numero(texto, unidade)


@pytest.mark.parametrize("valor, unidade, texto", [
    (2500, "Hz", "2,5 kHz"), (127.34, "V", "127,3 V"), (0.0012, "V", "1,2 mV"), (59.998, "Hz", "60 Hz"),
    (0, "A", "0 A"), (-4.7e-6, "F", "-4,7 µF"), (1e7, "Hz", "10 MHz"), (999.96, "V", "1 kV"), (1500, "", "1,5 k"),
    (3.0, "", "3"), (123456, "S/s", "123,5 kS/s"),
])
def test_formatar_si(valor, unidade, texto):
    assert formatar_si(valor, unidade) == texto


def test_formatar_em_ingles_e_o_que_nao_e_numero():
    assert formatar_si(2500, "Hz", decimal=".") == "2.5 kHz"
    assert formatar_si(59.998, "Hz", digitos=5) == "59,998 Hz"
    assert formatar_si(math.nan, "V") == "—" and formatar_si(math.inf) == "—"


@pytest.mark.parametrize("valor", [1e-11, 3.3e-7, 0.05, 1.0, 42.0, 2.2e3, 7.5e5, 4e8])
def test_ida_e_volta(valor):
    assert ler_numero(formatar_si(valor, "V", digitos=6), "V") == pytest.approx(valor, rel=1e-5)


@pytest.mark.parametrize("segundos, texto", [
    (0, "0 s"), (0.0042, "0,0042 s"), (4.2, "4,2 s"), (59.4, "59 s"), (60, "1 min"), (750, "12 min 30 s"),
    (3600, "1 h 00"), (3720, "1 h 02"), (96_000, "26 h 40"), (math.nan, "—"), (-1, "—"),
])
def test_formatar_duracao(segundos, texto):
    from sh_analyzer_gui.componentes.numeros import formatar_duracao

    assert formatar_duracao(segundos) == texto
