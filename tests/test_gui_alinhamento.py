"""O alinhamento de traços, sem Qt (dados/alinhamento.py, TR-07): o atraso pela correlação cruzada e pelo cruzamento
por zero, abaixo de uma amostra, conferido contra atrasos conhecidos (fracionários) em sinais da rede com harmônicas e
ruído, em ruído branco e com taxas diferentes; o sinal periódico (vale o menor atraso, e o resultado avisa) e os
trechos que não dão um atraso."""

import numpy as np
import pytest
from sh_analyzer_gui.dados.alinhamento import (
    AlinhamentoImpossivel,
    Trecho,
    alinhar,
    cruzamentos_de_subida,
    nivel_e_amplitude,
)

TAXA = 200_000.0


def rede(t):
    return np.sin(2 * np.pi * 60 * t) + 0.2 * np.sin(2 * np.pi * 180 * t + 0.3) + 0.05 * np.sin(2 * np.pi * 5e3 * t)


def _par(atraso, *, ruido=0.0, taxa_do_traco=TAXA, fase_da_grade=0.0, a=0.02, b=0.12, busca=0.02, semente=1,
         sinal=rede):
    """A referência em [a, b] e o traço (a mesma rede ``atraso`` segundos depois) em [a − busca, b + busca]."""
    gerador = np.random.default_rng(semente)
    tr = np.arange(round(a * TAXA), round(b * TAXA)) / TAXA
    ts = np.arange(round((a - busca) * taxa_do_traco), round((b + busca) * taxa_do_traco)) / taxa_do_traco
    ts = ts + fase_da_grade
    r = sinal(tr) + ruido * gerador.standard_normal(len(tr))
    s = sinal(ts - atraso) + ruido * gerador.standard_normal(len(ts))
    return Trecho(r, tr[0], TAXA), Trecho(s, ts[0], taxa_do_traco)


@pytest.mark.parametrize("metodo", ["correlacao", "zero"])
def test_sem_ruido_o_atraso_fracionario_e_exato(metodo):
    feito = alinhar(metodo, *_par(1.2345e-3))
    assert feito.metodo == metodo and abs(feito.atraso_s - 1.2345e-3) * TAXA < 0.01
    # A grade do traço fora da fase da referência (o deslocamento de agora fracionário) não muda nada.
    feito = alinhar(metodo, *_par(-0.4e-3, fase_da_grade=0.37 / TAXA))
    assert abs(feito.atraso_s + 0.4e-3) * TAXA < 0.01


def test_com_ruido_os_erros_sao_os_do_ruido():
    for semente in range(3):
        referencia, traco = _par(0.8e-3, ruido=0.01, semente=semente)
        correlacao = alinhar("correlacao", referencia, traco)
        zero = alinhar("zero", referencia, traco)
        assert abs(correlacao.atraso_s - 0.8e-3) * TAXA < 0.1 and correlacao.qualidade > 0.999
        assert abs(zero.atraso_s - 0.8e-3) * TAXA < 0.5 and zero.casados == 6
        assert 0 < zero.qualidade * TAXA < 2          # o desvio dos cruzamentos casados, em amostras


def test_o_ruido_branco_tem_o_pico_estreito_e_sai_igual():
    """Um sinal de banda larga: o pico da correlação tem uma amostra de largura (a parábola erraria ~0,1)."""
    gerador = np.random.default_rng(7)
    x = gerador.standard_normal(40_000)
    atraso = 37.3                                     # amostras, fracionário: pela FFT (o atraso de banda limitada)
    f = np.fft.rfftfreq(len(x))
    y = np.fft.irfft(np.fft.rfft(x) * np.exp(-2j * np.pi * f * atraso), len(x))
    feito = alinhar("correlacao", Trecho(x[4000:24000], 4000 / TAXA, TAXA), Trecho(y[2000:26000], 2000 / TAXA, TAXA))
    assert abs(feito.atraso_s * TAXA - atraso) < 0.01 and feito.qualidade > 0.99 and feito.aviso == ""


def test_taxas_diferentes_interpolam_e_avisam():
    referencia, traco = _par(1.0e-3, taxa_do_traco=125_000.0, fase_da_grade=3.3e-6)
    for metodo in ("correlacao", "zero"):
        feito = alinhar(metodo, referencia, traco)
        assert abs(feito.atraso_s - 1.0e-3) * TAXA < 0.2 and "taxas diferentes" in feito.aviso


def test_o_sinal_periodico_vale_o_menor_atraso():
    """O traço 0,7 período atrasado: o casamento do período seguinte, mais perto, vale (um sinal periódico de verdade:
    a ondulação é a 83ª harmônica, não os 5 kHz, que não repetem a cada período da rede)."""
    periodo = 1 / 60
    def periodica(t):
        return np.sin(2 * np.pi * 60 * t) + 0.2 * np.sin(2 * np.pi * 180 * t) + 0.05 * np.sin(2 * np.pi * 60 * 83 * t)

    referencia, traco = _par(0.7 * periodo, sinal=periodica)
    feito = alinhar("correlacao", referencia, traco)
    assert feito.atraso_s == pytest.approx(-0.3 * periodo, abs=0.01 / TAXA)
    assert "se repete" in feito.aviso and "ms" in feito.aviso
    zero = alinhar("zero", referencia, traco)
    assert zero.atraso_s == pytest.approx(-0.3 * periodo, abs=0.05 / TAXA) and "16.67 ms" in zero.aviso


def test_o_zero_e_o_de_um_numero_inteiro_de_periodos():
    """O trecho com 6,4 períodos: a média do trecho inteiro sai do zero; a dos períodos inteiros, não."""
    t = np.arange(round(6.4 / 60 * TAXA)) / TAXA
    x = np.sin(2 * np.pi * 60 * t) + 0.25
    nivel, amplitude = nivel_e_amplitude(x)
    assert nivel == pytest.approx(0.25, abs=1e-4) and amplitude == pytest.approx(1.0, abs=1e-6)
    assert abs(float(x.mean()) - 0.25) > 0.01
    cruzamentos = cruzamentos_de_subida(Trecho(x, 0.0, TAXA))
    assert np.allclose(cruzamentos, np.arange(1, 7) / 60, atol=0.01 / TAXA)


def test_os_trechos_que_nao_dao_um_atraso():
    referencia, traco = _par(1e-3)
    with pytest.raises(AlinhamentoImpossivel, match="constante"):
        alinhar("correlacao", Trecho(np.ones(1000), 0.0, TAXA), traco)
    with pytest.raises(AlinhamentoImpossivel, match="não cobre"):
        alinhar("correlacao", referencia, Trecho(traco.valores[:100], traco.t0, TAXA))
    with pytest.raises(AlinhamentoImpossivel, match="poucas amostras"):
        alinhar("zero", referencia, Trecho(np.zeros(3), 0.0, TAXA))
    with pytest.raises(AlinhamentoImpossivel, match="não cruza"):
        alinhar("zero", referencia, Trecho(np.linspace(1, -1, 1000), 0.0, TAXA))        # só desce
    with pytest.raises(AlinhamentoImpossivel, match="não finitos"):
        alinhar("zero", referencia, Trecho(np.full(100, np.nan), 0.0, TAXA))
    with pytest.raises(ValueError, match="desconhecido"):
        alinhar("olho", referencia, traco)
