"""Os avisos de um traço no chip dele (F2.8): os do canal (a sonda registrada que não pôde ser usada, a faixa do ADC
suposta), a integridade da captura, as etapas da cadeia que não servem ou não fazem nada neste canal e o erro da
conta, do mais grave para o menos, sem repetir. Na tela, o sinal na cor do mais grave e a lista na dica. Sem tela."""

from dataclasses import replace

import numpy as np
import pytest
from capturas_sinteticas import escrever_bin
from sh_analyzer_gui.dados.avisos import avisos_da_cadeia, avisos_do_canal, avisos_do_traco, pior_nivel
from sh_analyzer_gui.dados.cadeia import Cadeia, CorrecaoSonda, Filtro
from sh_analyzer_gui.dados.materializacao import contexto_do_canal
from supraharmonicos import api

FS = 200_000.0
N = 20_000


def canal(tmp_path, versao=9, **mudancas):
    v = np.sin(2 * np.pi * 50 * np.arange(N) / FS)
    caminho = escrever_bin(tmp_path / f"c{versao}.bin", [v, v], grandezas=(0, 0), versao=versao)
    return replace(api.abrir_captura(caminho).canais[0], **mudancas)


def test_os_avisos_do_canal(tmp_path):
    assert avisos_do_canal(canal(tmp_path)) == ()                       # v9: a faixa gravada, sem sonda
    suposta = canal(tmp_path, versao=2)                                  # v2: o cabeçalho não grava a faixa
    assert not suposta.faixa_confiavel
    (aviso,) = avisos_do_canal(suposta)
    assert aviso.nivel == "aviso" and "não registra a faixa do ADC" in aviso.texto and "--faixa 20.48" in aviso.texto
    problema = avisos_do_canal(canal(tmp_path, problema_sonda="o perfil 'X' foi feito para a faixa 10.24"))
    assert [a.texto for a in problema] == ["a sonda registrada não pôde ser usada: o perfil 'X' foi feito para a "
                                           "faixa 10.24"]


def test_os_avisos_da_cadeia_neste_canal(tmp_path):
    c = canal(tmp_path)
    contexto = contexto_do_canal(c)
    assert avisos_da_cadeia(Cadeia((Filtro("passa_altas", (2_000.0,)),)), contexto) == ()
    (automatica,) = avisos_da_cadeia(Cadeia((CorrecaoSonda(),)), contexto)
    assert automatica.nivel == "aviso" and "não registra uma sonda" in automatica.texto
    # A sonda registrada que não pôde ser usada: o aviso da etapa diz isso, e não que não há sonda.
    (sem_perfil,) = avisos_da_cadeia(Cadeia((CorrecaoSonda(),)),
                                     contexto_do_canal(replace(c, problema_sonda="o perfil é de outra faixa")))
    assert "não pôde ser usada" in sem_perfil.texto and "não registra" not in sem_perfil.texto
    acima, que_nao_abre = avisos_da_cadeia(
        Cadeia((Filtro("passa_baixas", (150_000.0,)), CorrecaoSonda(str(tmp_path / "sumiu.json")))), contexto)
    assert acima.nivel == que_nao_abre.nivel == "erro"
    assert acima.texto.startswith("PB 150 kHz: ") and "Nyquist" in acima.texto
    assert que_nao_abre.texto.startswith("sonda sumiu")
    desligada = Cadeia((Filtro("passa_baixas", (150_000.0,), ligada=False),))
    assert avisos_da_cadeia(desligada, contexto) == ()                  # uma etapa desligada não é aplicada


def test_os_avisos_do_traco_em_ordem_e_sem_repetir(tmp_path):
    c = canal(tmp_path, versao=2)
    cadeia = Cadeia((Filtro("passa_baixas", (150_000.0,)),))
    contexto = contexto_do_canal(c)
    try:
        cadeia.validar(contexto)
    except api.ErroSHAN as e:
        motivo = str(e)
    avisos = avisos_do_traco(c, cadeia, contexto, integridade="nao_confere", erro=motivo)
    assert [a.nivel for a in avisos] == ["erro", "erro", "aviso"]       # o mais grave primeiro
    assert "CRC" in avisos[0].texto and "Nyquist" in avisos[1].texto and "faixa" in avisos[2].texto
    assert pior_nivel(avisos) == "erro" and pior_nivel(()) is None
    novo = avisos_do_traco(c, Cadeia(), contexto, erro="a materialização não coube no disco")
    assert novo[0] == api.Aviso("erro", "a materialização não coube no disco")


# ------------------------------------------------------------------ na tela

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")


@pytest.fixture
def janela(qapp, config_limpa, qtbot):
    from dialogos_falsos import DialogosFalsos
    from sh_analyzer_gui.app import criar_aplicacao
    from sh_analyzer_gui.janela import JanelaPrincipal

    criar_aplicacao([], tema="escuro")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.resize(1400, 900)
    j.show()
    qtbot.waitExposed(j)
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def test_o_chip_mostra_os_avisos_do_traco(janela, qtbot, tmp_path):
    from sh_analyzer_gui.modelo.comandos import MudarTracos

    v = np.sin(2 * np.pi * 50 * np.arange(N) / FS)
    (fonte,) = janela.controle.abrir_capturas([escrever_bin(tmp_path / "v2.bin", [v, v], grandezas=(0, 0))])
    # A conferência da integridade termina antes (senão o "sem_crc" dela chegaria depois do valor posto abaixo).
    qtbot.waitUntil(lambda: fonte.piramides is not None and fonte.integridade == "sem_crc", timeout=10_000)
    traco = janela.area.plotar_canal(fonte, 0)
    tempo = janela.area.widget_da_vista(janela.vista_ativa())
    chip = tempo.chips[traco]
    assert chip.nivel == "aviso" and "faixa do ADC" in chip.toolTip() and "faixa do ADC" in chip.accessibleDescription()
    largura_com_sinal = chip.sizeHint().width()
    sem = type(chip)(chip.nome, chip._cor, chip.resumo)
    assert largura_com_sinal > sem.sizeHint().width()                   # o sinal tem lugar: não come o resumo

    fonte.definir_integridade("nao_confere")                            # a conferência do CRC terminou mal
    assert chip.nivel == "erro" and chip.toolTip().startswith("• as amostras não conferem")

    # A cadeia muda o aviso: uma correção automática sem sonda.
    janela.projeto.pilha.push(MudarTracos([traco], cadeia=Cadeia((CorrecaoSonda(),))))
    qtbot.waitUntil(lambda: "não tem o que aplicar" in tempo.chips[traco].toolTip(), timeout=5_000)

    # O espectro mostra os mesmos.
    janela.acoes["espectro"].trigger()
    espectro = janela.area.widget_da_vista(janela.vista_ativa())
    qtbot.waitUntil(lambda: traco in espectro.chips, timeout=10_000)
    assert espectro.chips[traco].nivel == "erro" and "faixa do ADC" in espectro.chips[traco].toolTip()
    fonte.definir_integridade("confere")
    assert espectro.chips[traco].nivel == "aviso" and "CRC" not in espectro.chips[traco].toolTip()
