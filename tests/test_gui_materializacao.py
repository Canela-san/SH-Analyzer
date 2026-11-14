"""A materialização de um traço e o cache delas (``sh_analyzer_gui.dados.materializacao``), sem Qt: a captura
inteira pela cadeia igual ao vetor inteiro, a pirâmide montada aos pedaços, a chave do conteúdo, o cancelamento, o
reaproveitamento e o limite de tamanho, e a média do canal."""

import json
import time

import numpy as np
import pytest
from capturas_sinteticas import FREQS_CAL, escrever_bin, planta_h
from sh_analyzer_gui.dados import materializacao as mat
from sh_analyzer_gui.dados.cadeia import Cadeia, ContextoDaCadeia, CorrecaoSonda, Filtro, RemoverDC
from sh_analyzer_gui.dados.piramide import BLOCO_BASE, ConstrutorIncremental, construir
from supraharmonicos import api

FS = 200_000.0
N = 1_000_000                     # 5 s por canal


@pytest.fixture(scope="module")
def captura(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("materializacao")
    sondas = pasta / "sondas"
    sondas.mkdir()
    perfil = {"id": "sonda_teste", "tipo": "resposta_frequencia",
              "pontos": [{"freq_hz": float(f), "ganho": float(planta_h(f))} for f in FREQS_CAL]}
    (sondas / "sonda_teste.json").write_text(json.dumps(perfil), encoding="utf-8")
    rng = np.random.default_rng(11)
    t = np.arange(N) / FS
    tensao = 0.4 + 3.0 * np.sin(2 * np.pi * 50 * t) + rng.normal(0, 1e-3, N)
    corrente = 0.1 * planta_h(9000) * np.sin(2 * np.pi * 9000 * t) + 0.5 * np.sin(2 * np.pi * 50 * t)
    caminho = escrever_bin(pasta / "c.bin", [tensao, corrente], (0, 1), (0, 1), ("", "sonda_teste"), versao=9)
    return api.abrir_captura(caminho, sondas_dir=sondas)


def contexto(captura, numero, media=None):
    return mat.contexto_do_canal(captura.canal(numero), media)


CADEIA = Cadeia((Filtro("passa_altas", (1000.0,), 4), Filtro("passa_baixas", (30_000.0,), 4)))


# ---------------------------------------------------------------------------
# A pirâmide aos pedaços
# ---------------------------------------------------------------------------

def test_a_piramide_aos_pedacos_e_a_do_sinal_inteiro():
    valores = np.random.default_rng(1).normal(0, 1, 100_003).astype(np.float32)
    valores[5_000] = np.nan
    inteira = construir(valores)[0]
    construtor = ConstrutorIncremental(len(valores), np.float32)
    for inicio in range(0, len(valores), 8_192):
        construtor.acrescentar(valores[inicio:inicio + 8_192])
        if not construtor.completa:
            parcial, esperado = construtor.piramide(), construir(valores[:construtor.recebidas])[0]
            assert parcial.n_amostras == construtor.recebidas
            for a, b in zip(parcial.niveis, esperado.niveis):
                np.testing.assert_array_equal(a.minimos, b.minimos)
    final = construtor.piramide()
    assert construtor.completa and len(final.niveis) == len(inteira.niveis)
    for a, b in zip(final.niveis, inteira.niveis):
        assert a.bloco == b.bloco
        np.testing.assert_array_equal(a.minimos, b.minimos)
        np.testing.assert_array_equal(a.maximos, b.maximos)
    with pytest.raises(ValueError, match="amostras demais"):
        construtor.acrescentar(valores[:32])
    torto = ConstrutorIncremental(100, np.float32)
    torto.acrescentar(valores[:BLOCO_BASE + 1])
    with pytest.raises(ValueError, match="último pedaço"):
        torto.acrescentar(valores[:32])


# ---------------------------------------------------------------------------
# A materialização
# ---------------------------------------------------------------------------

def test_o_traco_materializado_e_o_vetor_inteiro_pela_cadeia(captura, tmp_path):
    """A cadeia na captura inteira, aos blocos, gravada em float32: o vetor inteiro em float64 arredondado (no
    máximo 1 ulp do float32 de diferença), e a pirâmide a do arquivo gravado."""
    ctx = contexto(captura, 0, media=mat.media_do_canal(captura.canal(0)))
    cadeia = Cadeia((*CADEIA.etapas, RemoverDC()))
    inteiro = cadeia.aplicar(api.sinal_do_canal(captura, 0), ctx).valores
    parciais = []
    piramide = mat.materializar(cadeia, mat.leitor_do_canal(captura, 0), N, ctx, tmp_path / "x.f32",
                                bloco=1 << 17, parcial=lambda a, p: parciais.append(p.n_amostras),
                                intervalo_parcial_s=0.0)
    gravado = np.memmap(tmp_path / "x.f32", dtype=mat.DTYPE, mode="r")
    np.testing.assert_allclose(gravado, inteiro, rtol=2 ** -23, atol=2 ** -23 * np.max(np.abs(inteiro)))
    esperada = construir(np.asarray(gravado))[0]
    for a, b in zip(piramide.niveis, esperada.niveis):
        np.testing.assert_array_equal(a.minimos, b.minimos)
        np.testing.assert_array_equal(a.maximos, b.maximos)
    assert parciais == sorted(parciais) and 0 < parciais[0] < N and len(parciais) >= 3


def test_o_cache_reaproveita_e_cancelar_no_meio_nao_deixa_nada(captura, tmp_path):
    cache = mat.CacheDeMaterializacoes(tmp_path / "cache")
    ctx = contexto(captura, 1)
    chave = mat.chave_da_materializacao("crc0001", 1, CADEIA, ctx)
    leituras = []

    def ler(a, b):
        leituras.append((a, b))
        return api.sinal_do_canal(captura, 1, a, b)

    with pytest.raises(api.Cancelado):
        cache.obter(chave, CADEIA, ler, N, ctx, bloco=1 << 17, cancelado=lambda: len(leituras) >= 2)
    assert not any(c.exists() for c in cache.caminhos(chave))             # nada pela metade fica no cache
    feita = cache.obter(chave, CADEIA, ler, N, ctx, bloco=1 << 17)
    lidas = len(leituras)
    de_novo = cache.obter(chave, CADEIA, ler, N, ctx, bloco=1 << 17)
    assert len(leituras) == lidas                                         # do cache: nada lido de novo
    np.testing.assert_array_equal(de_novo.amostras, feita.amostras)
    assert de_novo.n_amostras == N and de_novo.amostras.dtype == mat.DTYPE


def test_amostras_sem_a_piramide_sao_refeitas(captura, tmp_path):
    """A pirâmide é a marca de pronto: as amostras de uma materialização interrompida (o aplicativo caiu) não valem."""
    cache = mat.CacheDeMaterializacoes(tmp_path)
    dados, piramide = cache.caminhos("abc")
    dados.write_bytes(b"\0" * 400)
    assert cache.abrir("abc", 100) is None
    np.zeros(100, np.float32).tofile(dados)
    from sh_analyzer_gui.dados import cache as arquivos
    arquivos.gravar(construir(np.zeros(100, np.float32))[0], piramide)
    assert cache.abrir("abc", 100) is not None
    assert cache.abrir("abc", 101) is None and not dados.exists()          # de outro tamanho: apagada


def test_a_chave_e_o_conteudo(captura, tmp_path):
    ctx = contexto(captura, 1)
    base = mat.chave_da_materializacao("crc1", 1, CADEIA, ctx)
    com_desligada = Cadeia((*CADEIA.etapas, Filtro("passa_baixas", (5_000.0,), ligada=False)))
    assert mat.chave_da_materializacao("crc1", 1, com_desligada, ctx) == base     # desligar não muda o resultado
    assert mat.chave_da_materializacao("crc2", 1, CADEIA, ctx) != base
    assert mat.chave_da_materializacao("crc1", 0, CADEIA, ctx) != base
    outro_corte = Cadeia((Filtro("passa_altas", (1001.0,), 4), CADEIA.etapas[1]))
    assert mat.chave_da_materializacao("crc1", 1, outro_corte, ctx) != base
    # O DC: a média entra só se a cadeia a usa.
    com_dc = Cadeia((*CADEIA.etapas, RemoverDC()))
    assert mat.chave_da_materializacao("crc1", 1, CADEIA, contexto(captura, 1, 0.5)) == base
    assert (mat.chave_da_materializacao("crc1", 1, com_dc, contexto(captura, 1, 0.5))
            != mat.chave_da_materializacao("crc1", 1, com_dc, contexto(captura, 1, 0.6)))
    # O perfil escolhido: mudar o conteúdo do arquivo muda a chave.
    perfil = tmp_path / "p.json"
    perfil.write_text((captura.canal(1).perfil.caminho).read_text(encoding="utf-8"), encoding="utf-8")
    escolhida = Cadeia((CorrecaoSonda(perfil=str(perfil)),))
    antes = mat.chave_da_materializacao("crc1", 1, escolhida, contexto(captura, 1))
    dados = json.loads(perfil.read_text(encoding="utf-8"))
    dados["pontos"][0]["ganho"] *= 1.01
    perfil.write_text(json.dumps(dados), encoding="utf-8")
    time.sleep(0.01)
    perfil.touch()
    assert mat.chave_da_materializacao("crc1", 1, escolhida, contexto(captura, 1)) != antes


def test_o_limite_de_tamanho_apaga_as_menos_usadas(captura, tmp_path):
    cache = mat.CacheDeMaterializacoes(tmp_path)
    ctx = contexto(captura, 0)
    curto = 100_000
    ler = mat.leitor_do_canal(captura, 0)
    chaves = []
    for corte in (1000.0, 2000.0, 3000.0):
        cadeia = Cadeia((Filtro("passa_altas", (corte,), 2),))
        chave = mat.chave_da_materializacao("crc", 0, cadeia, ctx)
        cache.obter(chave, cadeia, ler, curto, ctx)
        chaves.append(chave)
        time.sleep(0.02)
    um = cache.tamanho_bytes // 3
    cache.limite_bytes = 2 * um + um // 2
    cache.aparar(manter={chaves[0]})
    restantes = {c for c in chaves if cache.caminhos(c)[1].exists()}
    assert restantes == {chaves[0], chaves[2]}                            # a do meio era a menos usada fora as mantidas
    assert cache.limpar(manter={chaves[2]}) >= um and cache.caminhos(chaves[2])[0].exists()
    assert not cache.caminhos(chaves[0])[0].exists()


# ---------------------------------------------------------------------------
# A média do canal e a sonda
# ---------------------------------------------------------------------------

def test_a_media_do_canal_e_exata(captura):
    fracoes = []
    media = mat.media_do_canal(captura.canal(0), progresso=fracoes.append, amostras_por_leitura=300_000)
    assert media == pytest.approx(float(np.mean(api.sinal_do_canal(captura, 0))), rel=1e-13)
    assert fracoes[-1] == 1.0 and len(fracoes) == 4
    with pytest.raises(api.Cancelado):
        mat.media_do_canal(captura.canal(0), cancelado=lambda: True)


def test_o_carregador_de_perfis_guarda_o_que_leu(captura):
    carregar = mat.carregador_de_perfis()
    caminho = str(captura.canal(1).perfil.caminho)
    assert carregar(caminho) is carregar(caminho)


def test_a_correcao_de_sonda_materializada_no_miolo(captura, tmp_path):
    ctx = contexto(captura, 1)
    cadeia = Cadeia((CorrecaoSonda(), Filtro("passa_altas", (1000.0,), 4)))
    inteiro = cadeia.aplicar(api.sinal_do_canal(captura, 1), ctx).valores
    mat.materializar(cadeia, mat.leitor_do_canal(captura, 1), N, ctx, tmp_path / "s.f32", bloco=1 << 17)
    gravado = np.memmap(tmp_path / "s.f32", dtype=mat.DTYPE, mode="r")
    m = 2 * cadeia.margem(ctx)
    rms = float(np.sqrt(np.mean(inteiro[m:-m] ** 2)))
    assert np.max(np.abs(gravado[m:-m] - inteiro[m:-m])) < 1e-6 * rms


@pytest.mark.desempenho
def test_a_previa_de_um_segundo_de_janela_em_menos_de_200_ms(captura):
    """O plano, 7.2: a prévia (a janela visível com a margem, pela cadeia) em menos de 200 ms. Com a correção de
    sonda e dois filtros, numa janela de 1 s a 200 kS/s."""
    ctx = contexto(captura, 1)
    cadeia = Cadeia((CorrecaoSonda(), *CADEIA.etapas))
    ler = mat.leitor_do_canal(captura, 1)
    cadeia.previa(ler, N, 0, 1000, ctx)                    # aquece (o SciPy, a margem da sonda)
    tempos = []
    for inicio in (100_000, 300_000, 500_000):
        t0 = time.perf_counter()
        cadeia.previa(ler, N, inicio, inicio + 200_000, ctx)
        tempos.append(time.perf_counter() - t0)
    assert max(tempos) < 0.2, tempos
