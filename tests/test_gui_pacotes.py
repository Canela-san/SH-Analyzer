"""Os pacotes ``.zpaq.tar`` (F7.10: ``dados/pacotes.py``), sem Qt: um pacote feito pelo ``compactar`` abre e dá as
mesmas amostras; a segunda vez usa o cache; o cancelamento e o limite."""

import shutil

import numpy as np
import pytest
from capturas_sinteticas import escrever_bin
from sh_analyzer_gui.dados import pacotes as pc
from supraharmonicos import api
from supraharmonicos import compactacao as cp


def _pacote(tmp_path, metodo="rapido", n=2):
    origem = tmp_path / "capturas"
    origem.mkdir()
    rng = np.random.default_rng(3)
    caminhos = []
    for k in range(n):
        x = rng.standard_normal(40_000)
        caminhos.append(escrever_bin(origem / f"c{k}.bin", [x, 0.5 * x], versao=9))
    (origem / "notas.txt").write_text("não é captura")
    entradas, _ = cp.descobrir_entradas([origem])
    saida = tmp_path / "lab.zpaq.tar"
    cp.compactar(entradas, saida, metodo=cp.METODOS[metodo], processos=2)
    return saida, caminhos


def test_o_pacote_abre_com_as_mesmas_amostras(tmp_path):
    pacote, originais = _pacote(tmp_path)
    cache = pc.CacheDePacotes(tmp_path / "cache")
    progresso = []
    extraidas = cache.extrair(pacote, progresso=progresso.append)
    assert [p.name for p in extraidas] == ["c0.bin", "c1.bin"] and progresso[-1] == 1.0
    for extraida, original in zip(extraidas, originais):
        a, b = api.abrir_captura(extraida), api.abrir_captura(original)
        assert np.array_equal(a.canal(0).amostras, b.canal(0).amostras)
        assert np.array_equal(a.canal(1).amostras, b.canal(1).amostras)
    assert not (extraidas[0].parent / "notas.txt").exists()
    assert pc.eh_pacote(pacote) and not pc.eh_pacote(originais[0])


def test_a_segunda_vez_usa_o_cache(tmp_path, monkeypatch):
    pacote, _ = _pacote(tmp_path, n=1)
    cache = pc.CacheDePacotes(tmp_path / "cache")
    primeira = cache.extrair(pacote)
    monkeypatch.setattr(cp.Pacote, "restaurar", lambda *a, **k: pytest.fail("extraiu de novo"))
    assert cache.extrair(pacote) == primeira
    primeira[0].write_bytes(b"cortado")                   # um arquivo mexido: extrai de novo
    monkeypatch.undo()
    with pytest.raises(api.ErroSHAN, match="DIFERENTE|diferente"):
        cache.extrair(pacote)


def test_o_cancelamento_nao_deixa_a_marca(tmp_path):
    pacote, _ = _pacote(tmp_path, n=1)
    cache = pc.CacheDePacotes(tmp_path / "cache")
    with pytest.raises(api.Cancelado):
        cache.extrair(pacote, cancelado=lambda: True)
    destino = cache.pasta_do_pacote(pacote)
    assert not (destino / pc.MARCA_COMPLETA).exists()
    assert cache.extrair(pacote)[0].is_file()             # e a próxima vez extrai inteiro


def test_um_arquivo_que_nao_e_pacote(tmp_path):
    falso = tmp_path / "falso.tar"
    falso.write_bytes(b"x" * 1000)
    with pytest.raises(api.ErroSHAN):
        pc.CacheDePacotes(tmp_path / "cache").extrair(falso)


def test_limpar_e_aparar(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a, _ = _pacote(tmp_path / "a", n=1)
    b, _ = _pacote(tmp_path / "b", n=1)
    cache = pc.CacheDePacotes(tmp_path / "cache")
    (ca,), (cb,) = cache.extrair(a), cache.extrair(b)
    pa, pb = cache.pasta_de(ca), cache.pasta_de(cb)
    assert pa == cache.pasta_do_pacote(a) and cache.tamanho_bytes > 0
    cache.limite_bytes = 1
    cache.aparar(manter={cb})                              # a captura aberta segura a pasta dela
    assert not pa.exists() and pb.exists()
    assert cache.limpar(manter={cb}) == 0 and pb.exists()
    assert cache.limpar() > 0 and not pb.exists()


@pytest.mark.skipif(shutil.which("zpaq") is None, reason="zpaq não instalado")
def test_um_pacote_zpaq_de_verdade(tmp_path):
    pacote, originais = _pacote(tmp_path, metodo="max", n=1)
    (extraida,) = pc.CacheDePacotes(tmp_path / "cache").extrair(pacote)
    assert extraida.read_bytes() == originais[0].read_bytes()
