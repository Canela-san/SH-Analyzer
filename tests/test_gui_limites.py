"""As curvas de limite das bandas (``sh_analyzer_gui.dados.limites``), sem Qt: a reta em log f, o degrau, fora da
curva, a margem, os pontos colados de uma planilha, a pasta e as opções da vista das bandas no projeto. Os pontos
daqui são inventados para o teste, não são de norma nenhuma."""

import json

import numpy as np
import pytest
from sh_analyzer_gui.dados import espectros as esp
from sh_analyzer_gui.dados import limites as lim

CURVA = lim.CurvaLimite("teste", ((10_000, 100.0), (100_000, 80.0), (100_000, 70.0), (150_000, 70.0)),
                        fonte="pontos inventados")


def test_a_reta_em_log_f_o_degrau_e_fora_da_curva():
    v = CURVA.em([5_000, 10_000, np.sqrt(10_000 * 100_000), 100_000, 120_000, 150_000, 200_000])
    assert np.isnan(v[0]) and np.isnan(v[-1])                      # fora: sem limite
    assert v[1] == 100.0 and v[2] == pytest.approx(90.0)          # o meio em log f
    assert v[3] == 70.0                                            # no degrau, o menor
    assert v[4] == v[5] == 70.0


def test_a_margem_e_quantas_passam():
    niveis = np.array([10 ** (95 / 20) * 1e-6, 10 ** (75 / 20) * 1e-6])     # 95 e 75 dBµV
    m = lim.margens(CURVA, [10_000, 120_000], niveis)
    assert m == pytest.approx([5.0, -5.0])
    assert lim.passam(m) == 1 and lim.passam([np.nan, 1.0]) == 0


@pytest.mark.parametrize("pontos, motivo", [
    (((1000, 1.0),), "dois pontos"),
    (((2000, 1.0), (1000, 2.0)), "ordem crescente"),
    (((1000, 1.0), (1000, 2.0), (1000, 3.0)), "degrau"),
    (((0, 1.0), (1000, 2.0)), "positiva"),
])
def test_as_curvas_que_nao_servem(pontos, motivo):
    with pytest.raises(lim.LimiteInvalido, match=motivo):
        lim.CurvaLimite("x", pontos)


def test_os_pontos_colados_de_uma_planilha():
    texto = "frequência;nível\n9k;66,5\n150000\t56\n  30000 60  \nlixo\n95000,54\n"
    assert lim.pontos_do_texto(texto) == ((9000.0, 66.5), (150000.0, 56.0), (30000.0, 60.0), (95000.0, 54.0))


def test_a_pasta_e_o_nome_repetido(tmp_path):
    a = lim.salvar(CURVA, tmp_path)
    assert lim.ler(a) == CURVA and json.loads(a.read_text(encoding="utf-8"))["fonte"] == "pontos inventados"
    assert lim.salvar(CURVA, tmp_path) == a                        # a mesma curva: o mesmo arquivo
    outra = lim.CurvaLimite("teste!", CURVA.pontos)               # outro nome, o mesmo arquivo limpo
    b = lim.salvar(outra, tmp_path)
    assert b != a and b.name == "teste-2.json"
    renomeada = lim.CurvaLimite("nova", CURVA.pontos)
    c = lim.salvar(renomeada, tmp_path, substituir=a)
    assert not a.exists() and c.name == "nova.json"
    (tmp_path / "quebrada.json").write_text("{", encoding="utf-8")
    assert [curva.nome for _, curva in lim.curvas(tmp_path)] == ["nova", "teste!"]


def test_o_limite_vai_inteiro_no_projeto_e_so_quando_escolhido():
    assert "limite" not in esp.OpcoesDasBandas().para_dict()        # um projeto sem ele abre na v0.9
    o = esp.OpcoesDasBandas(limite=CURVA)
    dados = json.loads(json.dumps(o.para_dict()))
    assert dados["limite"]["pontos"][0] == [10000.0, 100.0]
    assert esp.OpcoesDasBandas.de_dict(dados) == o
    with pytest.raises(esp.OpcoesInvalidas, match="limite"):
        esp.OpcoesDasBandas.de_dict({**dados, "limite": {"nome": "x", "pontos": [[1, 2]]}})
