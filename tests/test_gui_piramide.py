"""A pirâmide mín/máx da interface (``sh_analyzer_gui.dados.piramide`` e ``.cache``): exata contra a força bruta em
todos os níveis, em qualquer comprimento, tipo e número de canais; o cache no disco, atômico e que se recupera de um
arquivo estragado. Sem Qt: roda no conjunto padrão."""

import os
import time

import numpy as np
import pytest
from sh_analyzer_gui.dados import cache as cache_mod
from sh_analyzer_gui.dados.cache import CacheDePiramides, PiramideInvalida, abrir, chave_do_arquivo, gravar
from sh_analyzer_gui.dados.piramide import BLOCO_BASE, FATOR, MIN_BLOCOS, Cancelado, construir


def forca_bruta(x: np.ndarray, bloco: int) -> tuple[np.ndarray, np.ndarray]:
    """O mínimo e o máximo de cada bloco, um por um (o último pode ser incompleto), ignorando NaN."""
    n = -(-len(x) // bloco)
    mn = np.array([np.nanmin(x[i * bloco:(i + 1) * bloco]) if not np.all(np.isnan(x[i * bloco:(i + 1) * bloco]))
                   else np.nan for i in range(n)]) if x.dtype.kind == "f" else \
        np.array([x[i * bloco:(i + 1) * bloco].min() for i in range(n)], dtype=x.dtype)
    mx = np.array([np.nanmax(x[i * bloco:(i + 1) * bloco]) if not np.all(np.isnan(x[i * bloco:(i + 1) * bloco]))
                   else np.nan for i in range(n)]) if x.dtype.kind == "f" else \
        np.array([x[i * bloco:(i + 1) * bloco].max() for i in range(n)], dtype=x.dtype)
    return mn, mx


def conferir(piramide, x):
    assert piramide.n_amostras == len(x)
    assert piramide.dtype == x.dtype
    assert piramide.niveis[0].bloco == BLOCO_BASE
    for k, nivel in enumerate(piramide.niveis):
        assert nivel.bloco == BLOCO_BASE * FATOR**k
        mn, mx = forca_bruta(x, nivel.bloco)
        np.testing.assert_array_equal(nivel.minimos, mn, err_msg=f"mínimos do nível {k} (bloco {nivel.bloco})")
        np.testing.assert_array_equal(nivel.maximos, mx, err_msg=f"máximos do nível {k} (bloco {nivel.bloco})")
        assert nivel.minimos.dtype == x.dtype and nivel.maximos.dtype == x.dtype
    # os níveis param quando o último tem menos de MIN_BLOCOS blocos
    assert len(piramide.niveis[-1]) < MIN_BLOCOS
    assert all(len(n) >= MIN_BLOCOS for n in piramide.niveis[:-1])


def sinal_com_extremos(n: int, dtype, semente: int = 0) -> np.ndarray:
    """Ruído com extremos nas bordas dos blocos (o lugar onde um erro de índice esconderia um pico)."""
    rng = np.random.default_rng(semente)
    info = np.iinfo(dtype)
    x = rng.integers(info.min // 4, info.max // 4, n, endpoint=True).astype(dtype)
    for i in range(BLOCO_BASE - 1, n, 997):
        x[i] = info.max if (i // 997) % 2 else info.min
    if n:
        x[-1] = info.max
        x[0] = info.min
    return x


@pytest.mark.parametrize("n", [1, 5, 31, 32, 33, 255, 256, 257, 511, 513, 4096, 12_345, 100_003])
@pytest.mark.parametrize("dtype", [np.int16, np.uint16])
def test_cada_nivel_e_igual_a_forca_bruta(n, dtype):
    x = sinal_com_extremos(n, dtype)
    (p,) = construir(x)
    conferir(p, x)


@pytest.mark.parametrize("amostras_por_leitura", [32, 64, 96, 4096])
def test_ler_em_pedacos_da_o_mesmo(amostras_por_leitura):
    x = sinal_com_extremos(10_007, np.int16, semente=3)
    (p,) = construir(x, amostras_por_leitura=amostras_por_leitura)
    conferir(p, x)


@pytest.mark.parametrize("n_canais", [2, 3, 8])
def test_canais_intercalados(n_canais):
    """A amostra i é do canal i % n_canais; um quadro final incompleto (arquivo cortado) é ignorado."""
    canais = [sinal_com_extremos(5_000 + 7, np.uint16, semente=c) for c in range(n_canais)]
    intercaladas = np.stack(canais, axis=1).reshape(-1)
    cortado = intercaladas[:-1]                 # o último quadro fica incompleto
    piramides = construir(cortado, n_canais, amostras_por_leitura=128)
    assert len(piramides) == n_canais
    for c, p in enumerate(piramides):
        conferir(p, canais[c][:-1])


def test_ponto_flutuante_ignora_nan():
    rng = np.random.default_rng(5)
    x = rng.normal(size=3_000)
    x[10] = np.nan                               # um NaN no meio de um bloco: o bloco usa o resto
    x[64:96] = np.nan                            # um bloco inteiro de NaN: fica NaN
    x[500] = 1e6
    (p,) = construir(x)
    conferir(p, x)
    assert np.isnan(p.niveis[0].minimos[2]) and np.nanmax(p.niveis[0].maximos) == 1e6


def test_sinal_vazio_e_canais_invalidos():
    (p,) = construir(np.zeros(0, np.int16))
    assert p.n_amostras == 0 and p.niveis == ()
    assert [q.n_amostras for q in construir(np.zeros(2, np.int16), 3)] == [0, 0, 0]
    with pytest.raises(ValueError):
        construir(np.zeros(10, np.int16), 0)
    with pytest.raises(ValueError):
        construir(np.zeros(10, np.int16), amostras_por_leitura=33)
    with pytest.raises(ValueError):
        construir(np.zeros((4, 4), np.int16))


def test_memmap_de_um_arquivo_com_cabecalho(tmp_path):
    """O uso real: as amostras de um .bin em memmap, depois do cabeçalho, com 2 canais intercalados."""
    canais = [sinal_com_extremos(70_001, np.uint16, semente=c) for c in range(2)]
    caminho = tmp_path / "captura.bin"
    with open(caminho, "wb") as f:
        f.write(b"\xab" * 4096)
        f.write(np.stack(canais, axis=1).reshape(-1).tobytes())
    amostras = np.memmap(caminho, dtype=np.uint16, mode="r", offset=4096)
    for c, p in enumerate(construir(amostras, 2, amostras_por_leitura=8192)):
        conferir(p, canais[c])


def test_progresso_e_cancelamento():
    x = sinal_com_extremos(1_000, np.int16)
    fracoes = []
    construir(x, amostras_por_leitura=64, progresso=fracoes.append)
    assert fracoes == sorted(fracoes) and fracoes[-1] == 1.0 and len(fracoes) == -(-1_000 // 64)
    chamadas = []

    def cancelar_na_terceira():
        chamadas.append(1)
        return len(chamadas) >= 3

    with pytest.raises(Cancelado):
        construir(x, amostras_por_leitura=64, cancelado=cancelar_na_terceira)
    assert len(chamadas) == 3


def test_nivel_para_a_janela():
    (p,) = construir(np.zeros(1_000_000, np.int16))
    assert p.nivel_para(10) is None                         # < 2 blocos de 32 por coluna: amostras cruas
    assert p.nivel_para(64).bloco == 32
    assert p.nivel_para(511).bloco == 32 and p.nivel_para(512).bloco == 256
    assert p.nivel_para(1e12).bloco == p.niveis[-1].bloco
    assert p.nbytes == sum(2 * len(n) * 2 for n in p.niveis)


# ------------------------------------------------------------------ o arquivo .shpir e o cache

def test_gravar_e_abrir_devolve_a_mesma_piramide_em_memmap(tmp_path):
    x = sinal_com_extremos(50_000, np.uint16)
    (p,) = construir(x)
    gravar(p, tmp_path / "p.shpir")
    q = abrir(tmp_path / "p.shpir")
    assert isinstance(q.niveis[0].minimos, np.memmap)
    conferir(q, x)
    assert list(tmp_path.iterdir()) == [tmp_path / "p.shpir"]       # nenhum temporário sobrando


def test_piramide_vazia_no_disco(tmp_path):
    (p,) = construir(np.zeros(0, np.float32))
    gravar(p, tmp_path / "v.shpir")
    q = abrir(tmp_path / "v.shpir")
    assert q.n_amostras == 0 and q.niveis == () and q.dtype == np.float32


@pytest.mark.parametrize("estrago", ["vazio", "magico", "cortado", "json", "formato"])
def test_arquivo_estragado_e_recusado(tmp_path, estrago):
    (p,) = construir(sinal_com_extremos(20_000, np.int16))
    caminho = tmp_path / "p.shpir"
    gravar(p, caminho)
    dados = caminho.read_bytes()
    if estrago == "vazio":
        dados = b""
    elif estrago == "magico":
        dados = b"XXXXXXXX" + dados[8:]
    elif estrago == "cortado":
        dados = dados[:len(dados) // 2]
    elif estrago == "json":
        dados = dados[:12] + b"#" + dados[13:]
    elif estrago == "formato":
        dados = dados.replace(b'"formato": 1', b'"formato": 9')
    caminho.write_bytes(dados)
    with pytest.raises(PiramideInvalida):
        abrir(caminho)


def test_falha_na_gravacao_nao_deixa_arquivo(tmp_path, monkeypatch):
    (p,) = construir(sinal_com_extremos(1_000, np.int16))

    def falhar(_):
        raise OSError("disco cheio")

    monkeypatch.setattr(cache_mod.os, "fsync", falhar)
    with pytest.raises(OSError):
        gravar(p, tmp_path / "p.shpir")
    assert list(tmp_path.iterdir()) == []


def test_cache_constroi_uma_vez_e_reaproveita(tmp_path, monkeypatch):
    canais = [sinal_com_extremos(30_000, np.uint16, semente=c) for c in range(2)]
    amostras = np.stack(canais, axis=1).reshape(-1)
    cache = CacheDePiramides(tmp_path)
    primeira = cache.obter("captura", amostras, 2)
    for c in range(2):
        conferir(primeira[c], canais[c])
    assert sorted(f.name for f in tmp_path.iterdir()) == sorted(cache.caminho("captura", c).name for c in range(2))

    def nao_pode_construir(*a, **k):
        raise AssertionError("o cache deveria ter sido usado")

    monkeypatch.setattr(cache_mod, "construir", nao_pode_construir)
    fracoes = []
    segunda = cache.obter("captura", amostras, 2, progresso=fracoes.append)
    assert fracoes == [1.0]
    for c in range(2):
        conferir(segunda[c], canais[c])


def test_cache_refaz_quando_o_arquivo_nao_bate(tmp_path):
    cache = CacheDePiramides(tmp_path)
    x = sinal_com_extremos(10_000, np.int16)
    cache.obter("k", x)
    cache.caminho("k", 0).write_bytes(b"lixo")                       # estragado: apagado e refeito
    conferir(cache.obter("k", x)[0], x)
    y = sinal_com_extremos(12_000, np.int16)                         # outro tamanho com a mesma chave: refeito
    conferir(cache.obter("k", y)[0], y)
    z = y.astype(np.uint16)                                          # outro tipo: refeito
    assert cache.obter("k", z)[0].dtype == np.uint16


def test_cancelar_nao_deixa_nada_no_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("sh_analyzer_gui.dados.piramide.AMOSTRAS_POR_LEITURA", 64)
    cache = CacheDePiramides(tmp_path)
    with pytest.raises(Cancelado):
        cache.obter("k", sinal_com_extremos(1_000, np.int16), cancelado=lambda: True)
    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


def test_limite_apaga_as_menos_usadas(tmp_path):
    x = sinal_com_extremos(40_000, np.int16)
    cache = CacheDePiramides(tmp_path, limite_bytes=10**9)
    for chave in ("a", "b", "c"):
        cache.obter(chave, x)
    tamanho = cache.caminho("a", 0).stat().st_size
    agora = time.time()
    for i, chave in enumerate(("b", "a", "c")):                       # "b" é a menos usada
        os.utime(cache.caminho(chave, 0), (agora - 100 + i, agora - 100 + i))
    cache.limite_bytes = 2 * tamanho
    cache.aparar()
    assert not cache.caminho("b", 0).exists()
    assert cache.caminho("a", 0).exists() and cache.caminho("c", 0).exists()
    # e um temporário velho (uma gravação interrompida) também sai
    velho = tmp_path / ("a" + cache_mod.EXTENSAO + ".xyz.tmp")
    velho.write_bytes(b"0")
    os.utime(velho, (agora - 7200, agora - 7200))
    cache.aparar()
    assert not velho.exists()


def test_chave_do_arquivo(tmp_path):
    arquivo = tmp_path / "c.bin"
    arquivo.write_bytes(b"1234")
    assert chave_do_arquivo(arquivo, 0xDEADBEEF) == "crcdeadbeef-4"
    copia = tmp_path / "sub" / "c.bin"
    copia.parent.mkdir()
    copia.write_bytes(b"1234")
    assert chave_do_arquivo(copia, 0xDEADBEEF) == chave_do_arquivo(arquivo, 0xDEADBEEF)   # o CRC segue a captura
    sem_crc = chave_do_arquivo(arquivo)
    assert sem_crc.startswith("arq") and sem_crc == chave_do_arquivo(arquivo)
    assert chave_do_arquivo(copia) != sem_crc                                           # sem CRC, o caminho conta
    os.utime(arquivo, ns=(10**18, 10**18))
    assert chave_do_arquivo(arquivo) != sem_crc                                         # mudou o arquivo, muda a chave
    assert CacheDePiramides(tmp_path).caminho("a/b:c", 2).name.startswith("a_b_c-c2-")


def test_pasta_padrao_do_sistema():
    pytest.importorskip("platformdirs")
    assert cache_mod.pasta_padrao().name == "piramides"
