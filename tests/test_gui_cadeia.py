"""A cadeia de transformações de um traço (``sh_analyzer_gui.dados.cadeia``): as etapas validadas, o vetor inteiro
igual às contas do motor (e da CLI), a prévia e os blocos iguais ao vetor inteiro longe das bordas. Sem Qt."""

import json

import numpy as np
import pytest
from capturas_sinteticas import FREQS_CAL, planta_h
from sh_analyzer_gui.dados.cadeia import (
    Cadeia,
    ContextoDaCadeia,
    CorrecaoSonda,
    EtapaInvalida,
    Filtro,
    RemoverDC,
    etapa_de_dict,
)
from supraharmonicos import api

FS = 200_000.0


@pytest.fixture(scope="module")
def perfil(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("cadeia")
    dados = {"id": "sonda_teste", "tipo": "resposta_frequencia",
             "pontos": [{"freq_hz": float(f), "ganho": float(planta_h(f))} for f in FREQS_CAL]}
    (pasta / "sonda_teste.json").write_text(json.dumps(dados), encoding="utf-8")
    return api.carregar_perfil(pasta / "sonda_teste.json")


@pytest.fixture(scope="module")
def sinal():
    """2 s de rede (50 Hz), supraharmônicos e ruído, com 0,3 de DC."""
    rng = np.random.default_rng(7)
    t = np.arange(int(2 * FS)) / FS
    return (0.3 + 3.0 * np.sin(2 * np.pi * 50 * t) + 0.05 * np.sin(2 * np.pi * 9_000 * t + 1.0)
            + 0.02 * np.sin(2 * np.pi * 41_000 * t) + rng.normal(0, 1e-3, len(t)))


def ler_de(sinal):
    return lambda a, b: sinal[a:b]


# ---------------------------------------------------------------------------
# As etapas
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("criar, trecho", [
    (lambda: Filtro("passa_tudo"), "desconhecido"),
    (lambda: Filtro("passa_altas", (1000.0, 2000.0)), "1 corte"),
    (lambda: Filtro("passa_faixa", (2000.0,)), "2 corte"),
    (lambda: Filtro("passa_faixa", (3000.0, 2000.0)), "inferior"),
    (lambda: Filtro("passa_baixas", (-5.0,)), "cortes inválidos"),
    (lambda: Filtro("passa_baixas", (float("nan"),)), "cortes inválidos"),
    (lambda: Filtro("passa_baixas", (1000.0,), 0), "ordem"),
    (lambda: Filtro("passa_baixas", (1000.0,), 11), "ordem"),
    (lambda: Filtro(ligada="sim"), "ligada"),
    (lambda: CorrecaoSonda(perfil=""), "perfil"),
    (lambda: Cadeia((Filtro(), "−DC")), "só aceita etapas"),
])
def test_cada_etapa_invalida_e_recusada_com_o_motivo(criar, trecho):
    with pytest.raises(EtapaInvalida, match=trecho):
        criar()


def test_o_que_depende_do_canal_e_conferido_na_hora_de_aplicar():
    cadeia = Cadeia((Filtro("passa_baixas", (150_000.0,)),))           # acima da Nyquist de 100 kHz
    with pytest.raises(api.ErroSHAN, match="Nyquist"):
        cadeia.aplicar(np.zeros(1000), ContextoDaCadeia(FS))
    assert Cadeia((Filtro("passa_baixas", 1000),)).etapas[0].cortes == (1000.0,)    # um número vira a tupla


def test_ida_e_volta_pelo_dicionario_e_o_resumo():
    cadeia = Cadeia((CorrecaoSonda(), Filtro("passa_altas", (2000.0,), 4), Filtro("rejeita_faixa", (59.0, 61.0)),
                     RemoverDC(), Filtro("passa_baixas", (50_000.0,), ligada=False),
                     CorrecaoSonda(perfil="sondas/SCT013.json")))
    lista = cadeia.para_lista()
    assert json.loads(json.dumps(lista)) == lista
    assert Cadeia.de_lista(lista) == cadeia
    assert cadeia.resumo() == "sonda · PA 2 kHz · RF 59 Hz–61 Hz · −DC · sonda SCT013"
    assert Cadeia().vazia and Cadeia((RemoverDC(ligada=False),)).vazia and not cadeia.vazia
    assert cadeia.tem_memoria and not Cadeia((RemoverDC(),)).tem_memoria


@pytest.mark.parametrize("dados, trecho", [
    ({"tipo": "derivada"}, "desconhecida"),
    ({"tipo": "filtro", "filtro": "passa_altas", "cortes": [2000], "polos": 3}, "campos desconhecidos"),
    ({"tipo": "filtro", "filtro": "passa_altas", "cortes": "2000"}, "cortes"),
    ("remover_dc", "objeto"),
])
def test_etapas_estragadas_no_arquivo_sao_recusadas(dados, trecho):
    with pytest.raises(EtapaInvalida, match=trecho):
        etapa_de_dict(dados)


# ---------------------------------------------------------------------------
# O vetor inteiro: as contas do motor
# ---------------------------------------------------------------------------

def test_o_vetor_inteiro_e_a_conta_do_motor_na_ordem_da_cadeia(sinal, perfil):
    ctx = ContextoDaCadeia(FS, perfil_do_canal=perfil)
    cadeia = Cadeia((CorrecaoSonda(), Filtro("passa_altas", (2000.0,), 4), Filtro("passa_baixas", (45_000.0,), 4)))
    esperado = api.filtrar(api.filtrar(api.aplicar_correcao_sonda(sinal, FS, perfil), FS, "passa_altas", 2000, 4),
                           FS, "passa_baixas", 45_000, 4)
    np.testing.assert_array_equal(cadeia.aplicar(sinal, ctx).valores, esperado)
    # Desligada, a etapa fica na cadeia e não é aplicada.
    sem_sonda = Cadeia((CorrecaoSonda(ligada=False), *cadeia.etapas[1:]))
    np.testing.assert_array_equal(sem_sonda.aplicar(sinal, ctx).valores,
                                  api.filtrar(api.filtrar(sinal, FS, "passa_altas", 2000, 4), FS, "passa_baixas",
                                              45_000, 4))
    np.testing.assert_array_equal(Cadeia().aplicar(sinal, ctx).valores, sinal)


def test_a_sonda_escolhida_e_a_automatica_sem_sonda_registrada(sinal, perfil):
    carregados = []

    def carregar(caminho):
        carregados.append(caminho)
        return perfil

    ctx = ContextoDaCadeia(FS, carregar_perfil=carregar)
    escolhida = Cadeia((CorrecaoSonda(perfil="sondas/sonda_teste.json"),)).aplicar(sinal, ctx)
    np.testing.assert_array_equal(escolhida.valores, api.aplicar_correcao_sonda(sinal, FS, perfil))
    assert carregados and carregados[0] == "sondas/sonda_teste.json"
    automatica = Cadeia((CorrecaoSonda(),)).aplicar(sinal, ctx)            # o canal não registra uma sonda
    np.testing.assert_array_equal(automatica.valores, sinal)
    assert any("não registra uma sonda" in a.texto for a in automatica.avisos)


def test_remover_o_dc_usa_a_media_do_canal_passada_pelas_etapas_de_antes(sinal, perfil):
    media = float(np.mean(sinal))
    trecho = sinal[1000:5000]
    # Com a média do canal, cada trecho perde o mesmo valor (o traço não pula a cada pan).
    r = Cadeia((RemoverDC(),)).aplicar(trecho, ContextoDaCadeia(FS, media=media))
    np.testing.assert_allclose(r.valores, trecho - media, rtol=0, atol=1e-15)
    # Sem ela, a do trecho.
    assert abs(Cadeia((RemoverDC(),)).aplicar(trecho, ContextoDaCadeia(FS)).valores.mean()) < 1e-12
    # Depois da sonda, a média do canal passa pelo ganho dela em DC (1 / ganho(0)).
    ctx = ContextoDaCadeia(FS, perfil_do_canal=perfil, media=media)
    r = Cadeia((CorrecaoSonda(), RemoverDC())).aplicar(sinal, ctx)
    assert CorrecaoSonda().ganho_dc(ctx) == pytest.approx(1 / float(perfil.ganho_em(np.zeros(1))[0]))
    assert abs(r.valores[20_000:-20_000].mean()) < 1e-4 * abs(media)
    # Depois de um passa-altas, não há DC para tirar.
    r = Cadeia((Filtro("passa_altas", (100.0,), 2), RemoverDC())).aplicar(sinal, ctx)
    np.testing.assert_array_equal(r.valores, api.filtrar(sinal, FS, "passa_altas", 100, 2))


# ---------------------------------------------------------------------------
# A prévia e os blocos: o vetor inteiro, longe das bordas
# ---------------------------------------------------------------------------

def test_a_margem_de_um_filtro_sai_da_sua_resposta_ao_impulso():
    ctx = ContextoDaCadeia(FS)
    alto, baixo = Filtro("passa_altas", (2000.0,), 4).margem(ctx), Filtro("passa_altas", (20.0,), 4).margem(ctx)
    assert 100 < alto < 2_000 and 50 * alto < baixo                 # o corte 100 vezes mais baixo demora ~100 vezes
    assert Filtro("passa_altas", (2000.0,), 8).margem(ctx) > alto     # mais polos, mais perto do círculo
    assert RemoverDC().margem(ctx) == 0
    cadeia = Cadeia((Filtro("passa_altas", (2000.0,), 4), RemoverDC(), Filtro("passa_baixas", (45_000.0,), 4)))
    assert cadeia.margem(ctx) == alto + Filtro("passa_baixas", (45_000.0,), 4).margem(ctx)


@pytest.mark.parametrize("inicio, fim", [(150_000, 152_000), (0, 3_000), (397_000, 400_000), (200_000, 200_010)])
def test_a_previa_dos_filtros_e_o_vetor_inteiro(sinal, inicio, fim):
    """Uma janela no meio, encostada no começo, encostada no fim, e de 10 amostras: a 1e-9 relativo."""
    ctx = ContextoDaCadeia(FS)
    cadeia = Cadeia((Filtro("passa_altas", (500.0,), 4), Filtro("rejeita_faixa", (8_000.0, 10_000.0), 3)))
    inteiro = cadeia.aplicar(sinal, ctx).valores
    lidos = []

    def ler(a, b):
        lidos.append((a, b))
        return sinal[a:b]

    previa = cadeia.previa(ler, len(sinal), inicio, fim, ctx).valores
    np.testing.assert_allclose(previa, inteiro[inicio:fim], rtol=1e-9, atol=1e-9 * np.max(np.abs(inteiro)))
    (a, b), = lidos
    assert b - a <= (fim - inicio) + 2 * cadeia.margem(ctx)       # leu só a janela e a margem


def test_os_blocos_dos_filtros_sao_o_vetor_inteiro(sinal):
    ctx = ContextoDaCadeia(FS, media=float(np.mean(sinal)))
    cadeia = Cadeia((Filtro("passa_baixas", (20_000.0,), 5), RemoverDC(), Filtro("passa_altas", (40.0,), 2)))
    inteiro = cadeia.aplicar(sinal, ctx).valores
    fracoes = []
    blocos = list(cadeia.em_blocos(ler_de(sinal), len(sinal), ctx, bloco=70_000, progresso=fracoes.append))
    assert [i for i, _ in blocos] == list(range(0, len(sinal), 70_000)) and fracoes[-1] == 1.0
    juntos = np.concatenate([v for _, v in blocos])
    np.testing.assert_allclose(juntos, inteiro, rtol=1e-9, atol=1e-9 * np.max(np.abs(inteiro)))


def test_os_blocos_da_correcao_de_sonda_sao_o_vetor_inteiro_no_miolo(sinal, perfil):
    """A correção de sonda do vetor inteiro é uma FFT circular: perto das bordas ela mistura o começo com o fim, e ali
    nenhum dos dois vale. No miolo, os blocos dão o vetor inteiro abaixo de 1e-6 do RMS (4e-7 medidos: a resposta ao
    impulso de 1/ganho(f) decai devagar, e a margem a corta em 1e-9 do pico)."""
    ctx = ContextoDaCadeia(FS, perfil_do_canal=perfil)
    cadeia = Cadeia((CorrecaoSonda(), Filtro("passa_altas", (2000.0,), 4)))
    margem = cadeia.margem(ctx)
    inteiro = cadeia.aplicar(sinal, ctx).valores
    juntos = np.concatenate([v for _, v in cadeia.em_blocos(ler_de(sinal), len(sinal), ctx, bloco=60_000)])
    miolo = slice(2 * margem, len(sinal) - 2 * margem)
    rms = float(np.sqrt(np.mean(inteiro[miolo] ** 2)))
    assert np.max(np.abs(juntos[miolo] - inteiro[miolo])) < 1e-6 * rms


def test_os_blocos_param_quando_cancelados(sinal):
    cadeia = Cadeia((Filtro("passa_altas", (2000.0,), 4),))
    blocos = cadeia.em_blocos(ler_de(sinal), len(sinal), ContextoDaCadeia(FS), bloco=100_000, cancelado=lambda: True)
    with pytest.raises(api.Cancelado):
        next(blocos)

