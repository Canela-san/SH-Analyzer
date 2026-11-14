"""A receita do traço (``sh_analyzer_gui.dados.receita``): o que o usuário muda, a validação e a conversão afim que
vai para a pirâmide. Sem Qt."""

import math

import pytest
from sh_analyzer_gui.dados.receita import EDITAVEIS, ReceitaDoTraco, ReceitaInvalida, proxima_cor


def receita(**campos) -> ReceitaDoTraco:
    return ReceitaDoTraco(**{"fonte": "f1", "canal": 0, "nome": "V_A", "cor": 0, **campos})


def test_padroes_e_mudanca():
    r = receita()
    assert (r.ganho, r.offset, r.deslocamento_s, r.visivel, r.faixa) == (1.0, 0.0, 0.0, True, 0)
    s = r.com(cor=3, nome="  V_B  ")
    assert (s.cor, s.nome) == (3, "V_B") and r.cor == 0                 # imutável: r não mudou
    assert r.diferencas(s) == {"cor", "nome"} and r.diferencas(r) == frozenset()


@pytest.mark.parametrize("campos, trecho", [
    ({"fonte": ""}, "fonte"),
    ({"canal": -1}, "canal"),
    ({"canal": 1.0}, "canal"),
    ({"nome": "   "}, "nome"),
    ({"cor": -1}, "cor"),
    ({"cor": True}, "cor"),
    ({"ganho": 0}, "ganho"),
    ({"ganho": math.nan}, "ganho"),
    ({"offset": math.inf}, "offset"),
    ({"offset": "1"}, "offset"),
    ({"deslocamento_s": math.nan}, "deslocamento"),
    ({"visivel": 1}, "visível"),
    ({"faixa": -2}, "faixa"),
])
def test_campos_invalidos_sao_recusados_com_a_mensagem(campos, trecho):
    with pytest.raises(ReceitaInvalida, match=trecho):
        receita(**campos)
    if set(campos) <= set(EDITAVEIS):
        with pytest.raises(ReceitaInvalida, match=trecho):
            receita().com(**campos)


def test_a_fonte_e_o_canal_nao_se_mudam():
    with pytest.raises(ReceitaInvalida, match="canal"):
        receita().com(canal=2)
    with pytest.raises(ReceitaInvalida, match="fonte"):
        receita().com(fonte="f2")


def test_afim_junta_a_calibracao_do_canal_e_o_ganho_do_traco():
    escala_canal, desloc_canal = 20.48 / 65536, -10.24
    r = receita(ganho=-2.0, offset=0.5)
    escala, desloc = r.afim(escala_canal, desloc_canal)
    codigo = 40_000
    assert escala * codigo + desloc == pytest.approx(-2.0 * (escala_canal * codigo + desloc_canal) + 0.5)


def test_proxima_cor_e_a_primeira_livre():
    assert proxima_cor([]) == 0
    assert proxima_cor([0, 1, 2]) == 3
    assert proxima_cor([0, 2, 3]) == 1                  # o âmbar, liberado, volta para o próximo
    assert proxima_cor(iter([1, 1, 0])) == 2


def test_a_cadeia_de_transformacoes_na_receita():
    from sh_analyzer_gui.dados.cadeia import Cadeia, Filtro, RemoverDC

    r = receita()
    assert r.cadeia == Cadeia() and "cadeia" in EDITAVEIS
    s = r.com(cadeia=Cadeia((Filtro("passa_altas", (2000.0,), 4), RemoverDC())))
    assert r.diferencas(s) == {"cadeia"} and s.cadeia.resumo() == "PA 2 kHz · −DC"
    assert ReceitaDoTraco.de_dict(s.para_dict()) == s
    with pytest.raises(ReceitaInvalida, match="Cadeia"):
        r.com(cadeia=[Filtro()])
    with pytest.raises(ReceitaInvalida, match="cadeia de transformações é inválida"):
        ReceitaDoTraco.de_dict({**r.para_dict(), "etapas": [{"tipo": "filtro", "filtro": "passa_altas",
                                                             "cortes": [2000.0, 3000.0]}]})
