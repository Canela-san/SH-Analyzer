"""O pedido de captura (``sh_placa/pedido.py``, a F4.3): os argumentos, a validação e os modelos.

**O contrato com o C:** o ``analisar_argumentos`` do ``firmware/ler_adc.c``, compilado num harness com o gcc deste
computador, lê cada linha de comando e escreve o que entendeu; o ``ler_argumentos`` daqui tem de entender o mesmo e
recusar o mesmo, e os argumentos de um pedido têm de voltar ao C como o pedido.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest
from sh_placa import pedido as pd
from sh_placa.pedido import Canal, Contexto, ErroDeUso, PedidoDeCaptura

RAIZ = Path(__file__).resolve().parents[1]
FIRMWARE = RAIZ / "firmware"
SONDAS = RAIZ / "scripts" / "sondas"

HARNESS = r"""
#define main ler_adc_main
#include "ler_adc.c"
#undef main
#include <stdlib.h>

static void hexa(const char *rotulo, const char *texto) {
    printf("%s ", rotulo);
    for (const unsigned char *p = (const unsigned char *)(texto ? texto : ""); *p; p++) printf("%02x", *p);
    printf("\n");
}

int main(int argc, char **argv) {
    if (argc == 6 && strcmp(argv[1], "--teto") == 0) {
        uint32_t atrasos[3] = {(uint32_t)atoi(argv[3]), (uint32_t)atoi(argv[4]), (uint32_t)atoi(argv[5])};
        printf("%u\n", teto_ticks_da_pru((uint32_t)atoi(argv[2]), atrasos));
        return 0;
    }
    struct configuracao c;
    int r = analisar_argumentos(argc, argv, &c);
    if (r != SAIDA_OK) return r;
    printf("frequencia %u\n", c.frequencia);
    printf("canais");
    for (int k = 0; k < c.num_canais; k++) printf(" %d", c.canais[k]);
    printf("\ngrandezas");
    for (int k = 0; k < c.num_canais; k++) printf(" %u", c.grandezas[k]);
    printf("\nfaixas");
    for (int k = 0; k < c.num_canais; k++) printf(" %u", c.faixas[k]);
    printf("\nganhos");
    for (int k = 0; k < c.num_canais; k++) printf(" %.17g", c.ganhos[k]);
    printf("\n");
    for (int k = 0; k < c.num_canais; k++) {
        char rotulo[16];
        snprintf(rotulo, sizeof(rotulo), "sonda%d", k);
        hexa(rotulo, c.sondas[k]);
    }
    printf("atrasos %u %u %u\n", c.atrasos_cs[0], c.atrasos_cs[1], c.atrasos_cs[2]);
    printf("spi %u\nblocos %llu\nduracao %.17g\nforcar %d\n", c.modo_spi, c.blocos, c.duracao_pedida, c.forcar_taxa);
    hexa("titulo", c.titulo);
    hexa("descricao", c.descricao);
    hexa("arquivo", c.arquivo == c.arquivo_automatico ? "" : c.arquivo);
    printf("automatico %d\nprogresso %d\nverboso %d\n", c.arquivo == c.arquivo_automatico, progresso_json, verboso);
    return 0;
}
"""

MODO_DO_SPI = pd.CODIGOS_DO_SPI


class HarnessDoC:
    """O ``analisar_argumentos`` e o ``teto_ticks_da_pru`` do C, compilados."""

    def __init__(self, binario: Path):
        self.binario = binario

    def __call__(self, argv):
        """``(código, o que ele entendeu, o stderr)``."""
        r = subprocess.run([str(self.binario), *argv], capture_output=True)
        entendido = {}
        for linha in r.stdout.decode().splitlines():
            chave, _, valor = linha.partition(" ")
            entendido[chave] = valor
        return r.returncode, entendido, r.stderr.decode(errors="replace")

    def teto(self, spi: str, atrasos) -> int:
        r = subprocess.run([str(self.binario), "--teto", str(MODO_DO_SPI[spi]), *map(str, atrasos)],
                           capture_output=True, text=True, check=True)
        return int(r.stdout)


@pytest.fixture(scope="module")
def c(tmp_path_factory) -> HarnessDoC:
    if shutil.which("gcc") is None:
        pytest.skip("sem gcc no computador")
    pasta = tmp_path_factory.mktemp("harness_pedido")
    fonte = pasta / "harness.c"
    fonte.write_text(HARNESS)
    binario = pasta / "harness"
    r = subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", f"-I{FIRMWARE}",
                        "-o", str(binario), str(fonte), "-lm"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return HarnessDoC(binario)


def _do_c(entendido: dict) -> pd.LinhaDeComando:
    """O que o C entendeu, como uma ``LinhaDeComando`` daqui."""
    canais = [int(x) for x in entendido["canais"].split()]
    grandezas = [pd.GRANDEZAS[int(x)] for x in entendido["grandezas"].split()]
    faixas = [pd.FAIXAS_V[int(x)] for x in entendido["faixas"].split()]
    ganhos = [float(x) or None for x in entendido["ganhos"].split()]
    sondas = [bytes.fromhex(entendido[f"sonda{k}"]).decode() for k in range(len(canais))]
    spi = {v: k for k, v in MODO_DO_SPI.items()}[int(entendido["spi"])]
    duracao = float(entendido["duracao"]) or None
    arquivo = bytes.fromhex(entendido["arquivo"]).decode() if entendido["automatico"] == "0" else None
    pedido = PedidoDeCaptura(
        tuple(Canal(*campos) for campos in zip(canais, grandezas, sondas, faixas, ganhos)),
        int(entendido["frequencia"]), duracao, int(entendido["blocos"]) if duracao is None else pd.BLOCOS_PADRAO,
        bytes.fromhex(entendido["titulo"]).decode(), bytes.fromhex(entendido["descricao"]).decode(),
        "computador" if arquivo == "-" else "cartao", arquivo if arquivo not in (None, "-") else "", spi,
        tuple(int(x) for x in entendido["atrasos"].split()), entendido["forcar"] == "1")
    return pd.LinhaDeComando(pedido, arquivo, entendido["progresso"] == "1", entendido["verboso"] == "1")


ACEITOS = [
    [],
    ["400000", "1"],
    ["200000", "0,1", "--duracao", "30s", "-t", "Rede V + I", "-d", "a tomada de casa, com acentos: ç ã é",
     "--grandeza", "0:corrente,1:tensao", "--sonda", "0:sct013_100a_sn001", "--ganho", "0:19.65,1:19.357",
     "--faixa-adc", "0:5.12,1:20.48", "-o", "-", "--progresso-json"],
    ["300000", "3,1,2", "--spi", "lenta", "--blocos", "0", "-v"],
    ["400000", "2,7", "--spi", "rapido:a", "--atraso-cs", "5,2,12", "--forcar-taxa"],
    ["--blocos", "3", "0,1"],                        # os canais depois das opções
    ["100000", "0", "--duracao", "1.5h", "--grandeza", "0:temperatura"],
    ["50000", "4", "--duracao", "10m", "--faixa-adc", "4:10.24", "--spi", "rapido:c"],
    ["400000", "1", "--duracao", "600", "-o", "ensaio.bin", "--titulo", "x" * 127, "--descricao", "y" * 271],
    ["400000", "1", "--blocos", "2", "--blocos", "5"],    # a última vale
    ["400000", "0,,1,", "--spi", "rápido"],          # o strtok pula os vazios
    ["419287"],                                      # o teto exato do SPI rápido
    ["327868", "1", "--spi", "lento"],
    ["450000", "--forcar-taxa"],
    ["400000", "1", "-t", "ç" * 63],                 # 126 bytes
    ["400000", "5", "--ganho", "5:1e-3", "--sonda", "5:" + "a" * 31],
]

RECUSADOS = [
    ["400k"], ["0"], ["500001"], ["400000", "8"], ["400000", "1,1"], ["400000", ""], ["400000", "a"],
    ["--grandeza", "2:tensao"], ["--grandeza", "1:tensão"], ["--grandeza", "1"], ["--grandeza", "x:tensao"],
    ["--sonda", "1:" + "x" * 32], ["--sonda", "1:"],
    ["--faixa-adc", "1:5"], ["--faixa-adc", "1:5.12,1:5.12"], ["--faixa-adc", "1:5.12V"],
    ["--ganho", "1:0"], ["--ganho", "1:abc"], ["--ganho", "1:1e13"], ["--ganho", "1:-2"], ["--ganho", "1:1_000"],
    ["--atraso-cs", "0,1,3"], ["--atraso-cs", "3,1"], ["--atraso-cs", "3,1,10001"], ["--atraso-cs", "3,1,3,"],
    ["--spi", "padrao"], ["--spi", "rapido:d"],
    ["450000"], ["327869", "--spi", "lenta"], ["419287", "--atraso-cs", "4,1,3"],
    ["--blocos", "-1"], ["--blocos", "2x"], ["--blocos", "2", "--duracao", "1s"],
    ["--duracao", "0"], ["--duracao", "5ms"], ["--duracao", "s"], ["--duracao", "-3m"],
    ["-t", "x" * 128], ["-t", "ç" * 64], ["-d", "x" * 272],
    ["-o", ""], ["--blocos"], ["--xyz"], ["400000", "1", "2"],
]


@pytest.mark.parametrize("argv", ACEITOS, ids=lambda a: " ".join(a)[:60] or "padrao")
def test_le_a_linha_de_comando_como_o_c(c, argv):
    codigo, entendido, erro = c(argv)
    assert codigo == 0, erro
    assert pd.ler_argumentos(argv) == _do_c(entendido)


@pytest.mark.parametrize("argv", RECUSADOS, ids=lambda a: " ".join(a)[:60])
def test_recusa_o_que_o_c_recusa(c, argv):
    codigo, _, erro = c(argv)
    assert codigo == 2, f"o C aceitou {argv}"
    with pytest.raises(ErroDeUso):
        pd.ler_argumentos(argv)


def _pedidos() -> list[PedidoDeCaptura]:
    sct = Canal(0, "corrente", "sct013_100a_sn001", 5.12, 19.65)
    tensao = Canal(1, ganho=19.357)
    return [
        PedidoDeCaptura(),
        PedidoDeCaptura((tensao, sct), 400_000, duracao_s=3600.0, titulo="Rede V + I",
                        descricao="a tomada de casa; o SCT013 na fase"),
        PedidoDeCaptura((Canal(3), Canal(1, "temperatura"), Canal(6, faixa_v=10.24)), 300_000, blocos=0,
                        destino="cartao", arquivo_no_cartao="noite_toda.bin", spi="lenta"),
        PedidoDeCaptura((Canal(2, ganho=1e-3),), 250_000, duracao_s=2.5, spi="rapido:c", atrasos_cs=(4, 2, 15)),
        PedidoDeCaptura(tuple(Canal(n) for n in range(8)), 500_000, blocos=4, forcar_taxa=True,
                        destino="cartao"),
        PedidoDeCaptura((Canal(5, sonda="cadeia_tensao"),), 1, duracao_s=90.0, spi="rapido:a"),
    ]


@pytest.mark.parametrize("pedido", _pedidos(), ids=lambda p: pd.comando(p)[15:70])
def test_os_argumentos_de_um_pedido_voltam_do_c_como_o_pedido(c, pedido):
    argv = pedido.argumentos() + (["-o", "-"] if pedido.destino == "computador" else [])
    codigo, entendido, erro = c(argv)
    assert codigo == 0, erro
    assert _do_c(entendido).pedido == pedido
    assert pd.ler_argumentos(argv).pedido == pedido


@pytest.mark.parametrize("spi", pd.MODOS_SPI)
@pytest.mark.parametrize("atrasos", [(3, 1, 3), (1, 1, 1), (10, 5, 9), (3, 1, 10), (100, 40, 250), (1, 10000, 10000)])
def test_o_teto_da_pru_e_a_conta_do_c(c, spi, atrasos):
    assert c.teto(spi, atrasos) == pd.teto_ticks_da_pru(spi, atrasos)


def test_o_teto_padrao_e_o_da_ajuda_do_ler_adc():
    assert pd.taxa_maxima_hz() == 419_287
    assert pd.taxa_maxima_hz("lenta") == 327_868
    assert pd.teto_ticks_da_pru("rapido", (1, 1, 1)) == 473
    assert pd.taxa_maxima_hz("rapido", (1, 1, 1)) == 422_832


# ------------------------------------------------------------------ o pedido


def test_os_canais_ficam_na_ordem_em_que_o_adc_os_varre():
    p = PedidoDeCaptura((Canal(3), Canal(0), Canal(1)))
    assert p.numeros == (0, 1, 3)
    assert p.argumentos()[:2] == ["400000", "0,1,3"]


def test_as_opcoes_por_canal_so_entram_quando_algum_canal_foge_do_padrao():
    assert PedidoDeCaptura().argumentos() == ["400000", "1", "--blocos", "1"]
    p = PedidoDeCaptura((Canal(0, "corrente"), Canal(1)))
    assert p.argumentos() == ["400000", "0,1", "--blocos", "1", "--grandeza", "0:corrente,1:tensao"]
    p = PedidoDeCaptura((Canal(0, faixa_v=5.12), Canal(1, sonda="cadeia_tensao", ganho=19.357)))
    assert p.argumentos()[4:] == ["--sonda", "1:cadeia_tensao", "--ganho", "1:19.357", "--faixa-adc",
                                  "0:5.12,1:20.48"]


def test_o_comando_visivel_e_o_que_se_digitaria_na_placa():
    p = PedidoDeCaptura((Canal(1),), duracao_s=600.0, titulo="Rede de casa")
    assert pd.comando(p) == "sudo ./ler_adc 400000 1 --duracao 10m -t 'Rede de casa' -o -"
    assert pd.comando(p.com(destino="cartao")) == "sudo ./ler_adc 400000 1 --duracao 10m -t 'Rede de casa'"
    no_cartao = p.com(destino="cartao", arquivo_no_cartao="rede.bin")
    assert no_cartao.argumentos()[-2:] == ["-o", "rede.bin"]
    assert no_cartao.argumentos(saida=False) == ["400000", "1", "--duracao", "10m", "-t", "Rede de casa"]


def test_o_nome_do_arquivo_e_o_do_ler_adc_com_a_hora_daqui_e_o_titulo():
    import datetime
    quando = datetime.datetime(2026, 11, 18, 14, 10, 5)
    assert pd.nome_do_arquivo(PedidoDeCaptura(), quando) == "captura_20261118_141005.bin"
    assert pd.nome_do_arquivo(PedidoDeCaptura(titulo="Rede de casa · V+I"), quando) == \
        "rede_de_casa_v_i_20261118_141005.bin"
    assert pd.nome_do_arquivo(PedidoDeCaptura(titulo="Calibração ±10 V"), quando) == \
        "calibracao_10_v_20261118_141005.bin"
    assert pd.nome_do_arquivo(PedidoDeCaptura(titulo="· ±"), quando) == "captura_20261118_141005.bin"
    longo = pd.nome_do_arquivo(PedidoDeCaptura(titulo="ab " * 40), quando)
    assert len(longo) <= pd.TAMANHO_DO_PREFIXO + len("_20261118_141005.bin") and "__" not in longo
    no_cartao = PedidoDeCaptura(destino="cartao", arquivo_no_cartao="rede.bin")
    assert pd.nome_do_arquivo(no_cartao, quando) == "rede.bin"
    assert pd.nome_do_arquivo(no_cartao.com(destino="computador"), quando) == "captura_20261118_141005.bin"
    for titulo in ("Rede de casa · V+I", "", "Ação"):
        nome = pd.nome_do_arquivo(PedidoDeCaptura(titulo=titulo), quando)
        assert not pd.validar(PedidoDeCaptura(destino="cartao", arquivo_no_cartao=nome))       # um nome que o C aceita


@pytest.mark.parametrize("segundos, texto", [(30.0, "30s"), (2.5, "2.5s"), (60.0, "1m"), (90.0, "90s"),
                                             (600.0, "10m"), (3600.0, "1h"), (5400.0, "90m"), (7200.0, "2h"),
                                             (0.1, "0.1s")])
def test_a_duracao_no_texto_mais_curto_que_volta_igual(segundos, texto):
    assert pd.texto_da_duracao(segundos) == texto
    assert pd._duracao(texto) == segundos


def test_os_blocos_de_uma_duracao_sao_os_do_c():
    """``calcular_blocos_para_duracao``: a taxa pedida, para cima, pelo menos 1."""
    assert pd.blocos_para_duracao(30, 400_000) == 12            # 11,44 blocos
    assert pd.blocos_para_duracao(0.001, 400_000) == 1
    assert pd.blocos_para_duracao(2.62144, 400_000) == 1        # exatos: 1 bloco
    p = PedidoDeCaptura(duracao_s=3600.0)
    assert p.blocos_pedidos == 1374
    assert p.bytes_do_arquivo == 4096 + 1374 * 2 * 1_048_576
    assert p.duracao_real_s == pytest.approx(1374 * 1_048_576 / 400_000)


def test_a_taxa_real_e_a_nyquist_por_canal():
    p = PedidoDeCaptura((Canal(0), Canal(1)), 300_000)
    assert p.ticks == 666
    assert p.taxa_real_hz == pytest.approx(200e6 / 666)
    assert p.nyquist_por_canal_hz == pytest.approx(200e6 / 666 / 4)


def test_ate_parar_nao_tem_tamanho_nem_duracao():
    p = PedidoDeCaptura(blocos=0)
    assert p.ate_parar and p.bytes_do_arquivo is None and p.duracao_real_s is None


def test_com_canal_troca_ou_acrescenta():
    p = PedidoDeCaptura().com_canal(Canal(1, "corrente")).com_canal(Canal(0))
    assert p.canais == (Canal(0), Canal(1, "corrente"))
    assert p.sem_canal(1).canais == (Canal(0),)


# ------------------------------------------------------------------ a validação


def _do(problemas, campo, nivel=None):
    return [p for p in problemas if p.campo == campo and (nivel is None or p.nivel == nivel)]


def test_o_pedido_padrao_nao_tem_problema():
    assert pd.validar(PedidoDeCaptura()) == []


def test_titulo_e_descricao_contam_os_bytes_e_nao_as_letras():
    assert not pd.validar(PedidoDeCaptura(titulo="ç" * 63))                    # 126 bytes
    [erro] = _do(pd.validar(PedidoDeCaptura(titulo="ç" * 64)), "titulo", "erro")
    assert "128 bytes" in erro.mensagem
    [erro] = _do(pd.validar(PedidoDeCaptura(descricao="a" * 272)), "descricao", "erro")
    assert "272 bytes" in erro.mensagem and "271" in erro.mensagem
    assert _do(pd.validar(PedidoDeCaptura(titulo="a\x00b")), "titulo", "erro")


def test_sem_canal_nada_captura():
    assert pd.impede(pd.validar(PedidoDeCaptura(canais=())))


def test_canal_fora_do_adc_ou_repetido():
    assert _do(pd.validar(PedidoDeCaptura((Canal(8),))), "canais", "erro")
    assert _do(pd.validar(PedidoDeCaptura((Canal(1), Canal(1, "corrente")))), "canais", "erro")


def test_a_faixa_e_uma_das_tres_do_ads8688():
    assert not _do(pd.validar(PedidoDeCaptura((Canal(1, faixa_v=10.24),))), "faixa")
    assert _do(pd.validar(PedidoDeCaptura((Canal(1, faixa_v=5.0),))), "faixa", "erro")


def test_o_ganho_e_positivo_e_finito():
    for ganho in (0.0, -1.0, math.inf, math.nan, 2e12):
        assert _do(pd.validar(PedidoDeCaptura((Canal(1, ganho=ganho),))), "ganho", "erro"), ganho


def test_acima_do_teto_da_pru_e_erro_e_forcada_e_aviso():
    [erro] = _do(pd.validar(PedidoDeCaptura(taxa_hz=420_000)), "taxa", "erro")
    assert "419287 S/s" in erro.mensagem
    assert not _do(pd.validar(PedidoDeCaptura(taxa_hz=419_287)), "taxa", "erro")
    assert _do(pd.validar(PedidoDeCaptura(taxa_hz=340_000, spi="lenta")), "taxa", "erro")
    forcada = pd.validar(PedidoDeCaptura(taxa_hz=450_000, forcar_taxa=True))
    assert not pd.impede(forcada) and _do(forcada, "taxa", "aviso")
    assert _do(pd.validar(PedidoDeCaptura(taxa_hz=600_000)), "taxa", "erro")


def test_a_taxa_que_nao_divide_200_mhz_diz_a_real():
    [info] = _do(pd.validar(PedidoDeCaptura(taxa_hz=300_000)), "taxa", "info")
    assert "300300,30 S/s" in info.mensagem
    assert not _do(pd.validar(PedidoDeCaptura(taxa_hz=400_000)), "taxa", "info")


def test_avisa_quando_a_nyquist_por_canal_nao_cobre_os_150_khz():
    assert not _do(pd.validar(PedidoDeCaptura()), "taxa")                     # 200 kHz com 1 canal
    [aviso] = _do(pd.validar(PedidoDeCaptura((Canal(0), Canal(1)))), "taxa", "aviso")
    assert "100,0 kHz" in aviso.mensagem and "150" in aviso.mensagem
    [aviso] = _do(pd.validar(PedidoDeCaptura(taxa_hz=2_000)), "taxa", "aviso")
    assert "nada da faixa" in aviso.mensagem


def test_duracao_e_blocos():
    assert _do(pd.validar(PedidoDeCaptura(duracao_s=0.0)), "duracao", "erro")
    assert _do(pd.validar(PedidoDeCaptura(duracao_s=math.inf)), "duracao", "erro")
    assert _do(pd.validar(PedidoDeCaptura(blocos=-1)), "duracao", "erro")
    assert not pd.validar(PedidoDeCaptura(blocos=0))


def test_o_espaco_no_destino():
    hora = PedidoDeCaptura(duracao_s=3600.0)                                   # 2,88 GB = 2,7 GiB
    [erro] = _do(pd.validar(hora, Contexto(livre_no_computador=2_000_000_000)), "destino", "erro")
    assert "2,7 GiB" in erro.mensagem and "1,9 GiB" in erro.mensagem
    assert _do(pd.validar(hora, Contexto(livre_no_computador=3_000_000_000)), "destino", "aviso")
    assert not pd.validar(hora, Contexto(livre_no_computador=10**12))
    # O cartão é o espaço da placa, não o do computador.
    cartao = hora.com(destino="cartao")
    assert _do(pd.validar(cartao, Contexto(livre_no_computador=10**12, livre_no_cartao=10**9)), "destino", "erro")
    [info] = _do(pd.validar(PedidoDeCaptura(blocos=0), Contexto(livre_no_computador=48_000_000)), "destino", "info")
    assert "~1 min" in info.mensagem


def test_a_vazao_do_enlace_contra_a_da_captura():
    p = PedidoDeCaptura()                                                      # 0,8 MB/s
    assert not pd.validar(p, Contexto(vazao_do_enlace=6.3e6))
    [aviso] = _do(pd.validar(p, Contexto(vazao_do_enlace=1.2e6)), "destino", "aviso")
    assert "dobro" in aviso.mensagem
    [aviso] = _do(pd.validar(p, Contexto(vazao_do_enlace=0.5e6)), "destino", "aviso")
    assert "perder amostras" in aviso.mensagem
    assert not pd.validar(p.com(destino="cartao"), Contexto(vazao_do_enlace=0.5e6))   # no cartão, o enlace não pesa


def test_o_nome_no_cartao():
    p = PedidoDeCaptura(destino="cartao", arquivo_no_cartao="ensaio.bin")
    assert not pd.validar(p, Contexto(capturas_no_cartao=frozenset({"outra.bin"})))
    assert _do(pd.validar(p, Contexto(capturas_no_cartao=frozenset({"ensaio.bin"}))), "arquivo", "erro")
    for nome in ("../x.bin", "ensaio", "-x.bin", "pasta/x.bin", "com espaço.bin"):
        assert _do(pd.validar(p.com(arquivo_no_cartao=nome)), "arquivo", "erro"), nome


def test_o_avancado():
    assert _do(pd.validar(PedidoDeCaptura(spi="padrao")), "spi", "erro")
    assert _do(pd.validar(PedidoDeCaptura(atrasos_cs=(0, 1, 3))), "atrasos", "erro")
    assert PedidoDeCaptura(spi="lento").spi == "lenta"                         # os sinônimos do C


# ------------------------------------------------------------------ a sonda


@pytest.fixture
def perfis():
    return pd.perfis_de_sonda(SONDAS)


def test_os_perfis_da_pasta_das_sondas(perfis):
    sct = perfis["sct013_100a_sn001"]
    assert sct.ganho == 19.65 and sct.faixa_v == 5.12 and sct.faixa_confiavel
    assert sct.faixa_de_frequencia_hz[1] == pytest.approx(173234.9627)
    assert perfis["cadeia_tensao"].ganho == 19.357
    assert pd.perfis_de_sonda(SONDAS / "nao_existe") == {}


def test_o_perfil_quebrado_e_o_de_outro_id(tmp_path):
    (tmp_path / "quebrado.json").write_text("{")
    (tmp_path / "copiado.json").write_text(json.dumps({"id": "original", "tipo": "ganho_fixo", "ganho": 2.0}))
    perfis = pd.perfis_de_sonda(tmp_path)
    assert perfis["quebrado"].problema
    ctx = Contexto(perfis=perfis, pasta_das_sondas=tmp_path)
    [aviso] = _do(pd.validar(PedidoDeCaptura((Canal(1, sonda="quebrado"),)), ctx), "sonda", "aviso")
    assert "não abre" in aviso.mensagem
    [aviso] = _do(pd.validar(PedidoDeCaptura((Canal(1, sonda="copiado"),)), ctx), "sonda", "aviso")
    assert "'original'" in aviso.mensagem


def test_a_sonda_certa_com_a_calibracao_do_perfil_nao_tem_problema(perfis):
    ctx = Contexto(perfis=perfis, pasta_das_sondas=SONDAS)
    p = PedidoDeCaptura((Canal(0, "corrente", "sct013_100a_sn001", 5.12, 19.65),), 340_000)   # 170 kHz por canal
    assert not [problema for problema in pd.validar(p, ctx) if problema.campo != "taxa"]


def test_o_perfil_que_falta_na_pasta(perfis):
    ctx = Contexto(perfis=perfis, pasta_das_sondas=SONDAS)
    [aviso] = _do(pd.validar(PedidoDeCaptura((Canal(0, "corrente", "sct013_outra"),)), ctx), "sonda", "aviso")
    assert "sct013_outra.json" in aviso.mensagem and str(SONDAS) in aviso.mensagem
    # Sem os perfis lidos, não confere (e não inventa).
    assert not pd.validar(PedidoDeCaptura((Canal(1, sonda="sct013_outra"),)))


def test_o_ganho_diferente_do_da_calibracao_do_perfil(perfis):
    ctx = Contexto(perfis=perfis)
    [aviso] = _do(pd.validar(PedidoDeCaptura((Canal(0, "corrente", "sct013_100a_sn001", 5.12),)), ctx), "ganho")
    assert aviso.nivel == "aviso" and "19.65" in aviso.mensagem and "×0,05089" in aviso.mensagem


def test_a_faixa_do_perfil_so_pesa_quando_ele_nao_foi_gerado_em_volts_reais(tmp_path):
    cal = {"ganho": {"sonda": 1.0}, "faixa_v": {"sonda": 20.48}, "faixa_v_confiavel": {"sonda": False}}
    (tmp_path / "antiga.json").write_text(json.dumps({"id": "antiga", "tipo": "ganho_fixo", "ganho": 1.0,
                                                      "calibracao_adc": cal}))
    cal["faixa_v_confiavel"]["sonda"] = True
    (tmp_path / "nova.json").write_text(json.dumps({"id": "nova", "tipo": "ganho_fixo", "ganho": 1.0,
                                                    "calibracao_adc": cal}))
    ctx = Contexto(perfis=pd.perfis_de_sonda(tmp_path))
    assert _do(pd.validar(PedidoDeCaptura((Canal(1, sonda="antiga", faixa_v=5.12),)), ctx), "faixa", "aviso")
    assert not _do(pd.validar(PedidoDeCaptura((Canal(1, sonda="nova", faixa_v=5.12),)), ctx), "faixa")


def test_a_nyquist_acima_da_faixa_do_perfil(perfis):
    ctx = Contexto(perfis=perfis)
    sct = Canal(0, "corrente", "sct013_100a_sn001", 5.12, 19.65)
    [info] = _do(pd.validar(PedidoDeCaptura((sct,)), ctx), "sonda", "info")    # 200 kHz contra 173 kHz
    assert "173,2 kHz" in info.mensagem
    assert not _do(pd.validar(PedidoDeCaptura((sct,), 340_000), ctx), "sonda")    # 170 kHz


def test_o_id_que_a_analise_recusaria_e_erro():
    for sonda in ("../x", "a/b", "x" * 32, "_x", "com espaço"):
        assert _do(pd.validar(PedidoDeCaptura((Canal(1, sonda=sonda),))), "sonda", "erro"), sonda


def test_corrente_sem_sonda_e_temperatura_com_sonda_avisam():
    assert _do(pd.validar(PedidoDeCaptura((Canal(0, "corrente"),))), "sonda", "aviso")
    assert _do(pd.validar(PedidoDeCaptura((Canal(0, "temperatura", "cadeia_tensao"),))), "sonda", "aviso")


# ------------------------------------------------------------------ os modelos


@pytest.mark.parametrize("pedido", _pedidos(), ids=lambda p: pd.comando(p)[15:70])
def test_o_modelo_vai_e_volta_pelo_json(pedido):
    assert pd.de_dict(json.loads(json.dumps(pd.para_dict(pedido)))) == pedido


def test_o_modelo_sem_um_campo_fica_com_o_padrao_e_um_valor_fora_da_regra_passa():
    assert pd.de_dict({}) == PedidoDeCaptura() and pd.de_dict({}).trazer_no_fim
    assert pd.de_dict({"trazer_no_fim": False}).trazer_no_fim is False
    p = pd.de_dict({"taxa_hz": 900_000, "canais": [{"numero": 1, "faixa_v": 3}]})
    assert p.taxa_hz == 900_000 and p.canais == (Canal(1, faixa_v=3.0),)
    assert pd.impede(pd.validar(p))


@pytest.mark.parametrize("dados", [[], {"taxa_hz": "400000"}, {"taxa_hz": True}, {"canais": [{"grandeza": "x"}]},
                                   {"canais": [{"numero": 1, "ganho": "2"}]}, {"atrasos_cs": [3, 1]},
                                   {"forcar_taxa": 1}, {"duracao_s": "1h"}, {"trazer_no_fim": "sim"}])
def test_o_modelo_com_a_forma_errada_e_recusado(dados):
    with pytest.raises(ValueError):
        pd.de_dict(dados)
