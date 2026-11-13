"""O ``ler_adc verificar`` de ponta a ponta, no computador: o ``main`` de verdade contra a placa falsa.

O verificar captura 1 bloco em cada taxa (a PRU é reiniciada entre elas), procura as bandas de 200 Hz que ficam acima
do piso local e escreve no stdout só ``1`` (há supraharmônicos) ou ``0``; o relatório vai para o stderr. Aqui a PRU
falsa entrega um sinal sintético amostrado na taxa que o ARM configurou, então um tom acima da Nyquist aparece dobrado
como apareceria no ADC (sem o filtro de ~15 kHz do ADS8688, que só o atenuaria).
"""

import subprocess

import numpy as np
import pytest
from pru_falsa import AMOSTRAS_POR_BLOCO, PlacaFalsa, compilar_ler_adc, tem_gcc

pytestmark = pytest.mark.skipif(not tem_gcc(), reason="sem gcc no computador")

LSB_20V = 20.48 / 65536          # V por código na faixa padrão (±10,24 V)


@pytest.fixture(scope="module")
def ler_adc(tmp_path_factory):
    return compilar_ler_adc(tmp_path_factory.mktemp("ler_adc_verificar"))


@pytest.fixture
def placa(tmp_path):
    return PlacaFalsa(tmp_path)


def sinal(tons: list[tuple[float, float]], ruido_lsb: float = 0.8, semente: int = 1):
    """Para a PRU falsa: a soma dos tons (frequência em Hz, amplitude de pico em códigos) com ruído branco, em torno
    do meio da escala, amostrada na taxa da captura e cortada no fundo de escala, como o ADC faria."""
    def gerar(taxa: float, mascara: int, k: int) -> np.ndarray:
        assert bin(mascara).count("1") == 1, "o verificar captura um canal só"
        gerador = np.random.default_rng(semente + k)
        t = (np.arange(AMOSTRAS_POR_BLOCO) + k * AMOSTRAS_POR_BLOCO) / taxa
        x = 32768.0 + gerador.normal(0.0, ruido_lsb, AMOSTRAS_POR_BLOCO)
        for f, amplitude in tons:
            x += amplitude * np.sin(2 * np.pi * f * t + 0.3)
        return np.clip(np.round(x), 0, 65535)
    return gerar


REDE = (60.0, 25000.0)           # a fundamental a ~76 % do fundo de escala, como a rede de 127 V pelo divisor


def verificar(ler_adc, placa, *args, **opcoes_da_pru) -> tuple[subprocess.CompletedProcess, object]:
    pru = placa.pru(**opcoes_da_pru)
    try:
        r = subprocess.run([str(ler_adc), "verificar", *map(str, args)], env=placa.ambiente, capture_output=True,
                           text=True, timeout=120)
    finally:
        pru.parar()
    return r, pru


def test_sem_supraharmonicos_escreve_0(ler_adc, placa):
    """A rede limpa: o vazamento da fundamental pela janela não pode subir o piso perto de 2 kHz (o passa-alta)."""
    r, pru = verificar(ler_adc, placa, sinal=sinal([REDE, (180.0, 400.0), (300.0, 150.0)]))
    assert r.returncode == 0, r.stderr
    assert r.stdout == "0\n"
    assert "Sem supraharmônicos" in r.stderr and "Erro" not in r.stderr
    # Uma captura por taxa, no canal 1 e na faixa padrão: 400 kS/s e depois 312,5 kS/s.
    assert [c["sample_period_ticks"] for c in pru.configuracoes] == [500, 640]
    assert all(c["auto_seq_mask"] == 0b10 and c["range_sel"] == 0 for c in pru.configuracoes)


def test_um_tom_de_25_khz_escreve_1_com_a_frequencia_e_o_nivel(ler_adc, placa):
    """Um tom de 3 códigos de pico (−78 dBc da fundamental) em 25 kHz: aparece nas duas taxas no mesmo lugar."""
    r, _ = verificar(ler_adc, placa, "--ganho", "19.357", sinal=sinal([REDE, (25000.0, 3.0)]))
    assert r.returncode == 0, r.stderr
    assert r.stdout == "1\n"
    linha = next(ln for ln in r.stderr.splitlines() if "25.000 kHz" in ln)
    rms_pino_mv = float(linha.split("dB acima do piso")[1].split("mV")[0])
    assert rms_pino_mv == pytest.approx(1e3 * 3.0 / np.sqrt(2) * LSB_20V, rel=0.03)
    assert "na entrada" in linha and "1 componente de 2.0 a 150.0 kHz" in r.stderr


def test_a_imagem_de_um_sinal_acima_da_nyquist_nao_conta(ler_adc, placa):
    """270 kHz cai em 130 kHz a 400 kS/s e em 42,5 kHz a 312,5 kS/s: muda de lugar com a taxa, então é imagem."""
    r, _ = verificar(ler_adc, placa, sinal=sinal([REDE, (270000.0, 20.0)]))
    assert r.returncode == 0, r.stderr
    assert r.stdout == "0\n"
    assert "Imagens de aliasing" in r.stderr and "~270.0 kHz" in r.stderr
    assert "130.0 kHz a 400 kS/s" in r.stderr and "42.5 kHz a 312.5 kS/s" in r.stderr


def test_um_sinal_real_e_uma_imagem_juntos(ler_adc, placa):
    r, _ = verificar(ler_adc, placa, sinal=sinal([REDE, (40000.0, 10.0), (270000.0, 20.0)]))
    assert r.stdout == "1\n"
    assert "40.000 kHz" in r.stderr and "~270.0 kHz" in r.stderr


def test_com_uma_taxa_so_a_imagem_conta_e_ele_avisa(ler_adc, placa):
    r, pru = verificar(ler_adc, placa, "--taxas", "400000", sinal=sinal([REDE, (270000.0, 20.0)]))
    assert r.returncode == 0, r.stderr
    assert r.stdout == "1\n" and "130.000 kHz" in r.stderr
    assert "com uma taxa só" in r.stderr
    assert [c["sample_period_ticks"] for c in pru.configuracoes] == [500]


def test_limiar_de_e_ate_mudam_o_que_conta(ler_adc, placa):
    """Um tom de 5 kHz conta de 2 a 150 kHz, mas não a partir de 9 kHz; um limiar alto o esconde."""
    tom = sinal([REDE, (5000.0, 3.0)])
    assert verificar(ler_adc, placa, sinal=tom)[0].stdout == "1\n"
    assert verificar(ler_adc, placa, "--de", "9k", sinal=tom)[0].stdout == "0\n"
    assert verificar(ler_adc, placa, "--limiar", "80", sinal=tom)[0].stdout == "0\n"


def test_canal_e_faixa_chegam_a_pru(ler_adc, placa):
    r, pru = verificar(ler_adc, placa, "--canal", "0", "--faixa-adc", "5.12", "--taxas", "400000,320000",
                       sinal=sinal([(60.0, 2000.0)]))
    assert r.returncode == 0, r.stderr
    assert r.stdout == "0\n" and "canal 0, ±2.56 V" in r.stderr
    assert [(c["auto_seq_mask"], c["range_sel"], c["sample_period_ticks"]) for c in pru.configuracoes] == \
        [(0b1, 0x2, 500), (0b1, 0x2, 625)]


def test_entrada_saturada_e_erro_sem_resultado(ler_adc, placa):
    """Os cortes criariam harmônicos que pareceriam supraharmônicos: erro, e o stdout fica vazio."""
    r, _ = verificar(ler_adc, placa, sinal=sinal([(60.0, 40000.0)]))
    assert r.returncode == 1 and r.stdout == ""
    assert "saturou" in r.stderr


def test_adc_mudo(ler_adc, placa):
    r, _ = verificar(ler_adc, placa, mudo=True)
    assert r.returncode == 4 and r.stdout == ""
    assert "ADC não está respondendo" in r.stderr


@pytest.mark.parametrize("args, trecho", [
    (["--ate", "200k"], "Nyquist"),                         # 312,5 kS/s: Nyquist de 156,25 kHz
    (["--taxas", "400000,400000"], "repetida"),
    (["--taxas", "500001"], ""),
    (["--faixa-adc", "7"], "20.48, 10.24 ou 5.12"),
    (["--canal", "8"], "de 0 a 7"),
    (["--de", "100"], "500 Hz"),
    (["--limiar", "-3"], "positivo"),
    (["--xyz", "1"], "desconhecida"),
    (["400000"], "argumento a mais"),
])
def test_argumentos_invalidos(ler_adc, placa, args, trecho):
    r = subprocess.run([str(ler_adc), "verificar", *args], env=placa.ambiente, capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 2 and r.stdout == ""
    assert trecho in r.stderr


def test_ajuda(ler_adc, placa):
    r = subprocess.run([str(ler_adc), "verificar", "--help"], env=placa.ambiente, capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0 and "verificar [opções]" in r.stdout and "--limiar" in r.stdout
    geral = subprocess.run([str(ler_adc), "--help"], env=placa.ambiente, capture_output=True, text=True, timeout=30)
    assert "verificar" in geral.stdout
