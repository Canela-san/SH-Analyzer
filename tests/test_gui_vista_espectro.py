"""A vista de espectro (F2.5): os números da vista são os da ``api`` sobre o trecho de cada traço (e os da ``api``, os
da CLI); trocar a escala, o método e o trecho (cada um um passo de desfazer); a cadeia da vista de tempo; as marcas;
e as opções no projeto. Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.dados import projeto as arq  # noqa: E402
from sh_analyzer_gui.dados.cadeia import Cadeia, Filtro  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.modelo.comandos import MudarTracos  # noqa: E402
from sh_analyzer_gui.modelo.persistencia import descrever  # noqa: E402
from supraharmonicos import api  # noqa: E402

FS = 200_000.0
N = 400_000


@pytest.fixture
def janela(qapp, config_limpa, qtbot):
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


@pytest.fixture
def aberto(janela, qtbot, tmp_path):
    t = np.arange(N) / FS
    v = 3.0 * np.sin(2 * np.pi * 50 * t) + 0.05 * np.sin(2 * np.pi * 9_000 * t) \
        + np.random.default_rng(8).normal(0, 1e-3, N)
    caminho = escrever_bin(tmp_path / "c.bin", [v, 0.5 * v], grandezas=(0, 1), versao=9)
    (fonte,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    traco = janela.area.plotar_canal(fonte, 0)
    tempo = janela.area.widget_da_vista(janela.vista_ativa())
    janela.acoes["espectro"].trigger()
    espectro = janela.area.widget_da_vista(janela.vista_ativa())
    qtbot.waitUntil(lambda: bool(espectro.resultados), timeout=10_000)
    return fonte, traco, tempo, espectro


def espectro_indice(metodo):
    """A posição do método no seletor da barra."""
    from sh_analyzer_gui.areas.analise.vista_espectro import METODOS
    return METODOS.index(metodo)


def recalcular(qtbot, espectro, mexer, quando=None):
    """Mexe e espera o resultado das opções novas (um resultado pedido antes pode chegar depois da mudança)."""
    mexer()
    qtbot.waitUntil(lambda: espectro.opcoes_calculadas == espectro.opcoes and (quando is None or quando()),
                    timeout=10_000)


def trecho_da_janela(tempo, traco):
    t0, t1 = tempo.janela_de_tempo()
    a = int(min(max(round((t0 - traco.receita.deslocamento_s) * FS), 0), N))
    b = int(min(max(round((t1 - traco.receita.deslocamento_s) * FS), 0), N))
    return a, b


def test_abrir_o_espectro_segue_a_vista_de_tempo_com_os_numeros_da_api(janela, aberto):
    fonte, traco, tempo, espectro = aberto
    vista = espectro.vista
    assert vista.tipo == "espectro" and vista.opcoes.vista_de_tempo == tempo.vista.id
    assert vista.nome == f"Espectro de {tempo.vista.nome}" and janela.vista_ativa() is vista
    (r,) = espectro.resultados
    a, b = trecho_da_janela(tempo, traco)
    esperado = api.espectro(api.sinal_do_canal(fonte.fonte.captura, 0, a, b), FS, api.ParametrosEspectro("fft"))
    np.testing.assert_allclose(r.espectro.db, esperado.db, rtol=0, atol=1e-9)
    _, desenhados, _ = espectro.curvas[traco].dados            # o TracoLOD sobre a pirâmide do espectro
    np.testing.assert_allclose(desenhados, esperado.db, rtol=0, atol=1e-9)
    assert r.espectro.parametros.metodo == "fft" and r.espectro.f0_hz == pytest.approx(50, abs=0.01)  # o padrão
    assert r.marcas.harmonicos_hz[0] == pytest.approx(2 * r.espectro.f0_hz)
    assert "FFT" in espectro.info.text() and "ciclos" in espectro.info.text()


def test_a_escala_o_metodo_e_o_trecho_cada_um_um_passo_de_desfazer(janela, qtbot, aberto):
    fonte, traco, tempo, espectro = aberto
    pilha = janela.projeto.pilha
    recalcular(qtbot, espectro, lambda: espectro.escala.botao(1).click())          # RMS
    assert espectro.opcoes.escala == "rms"
    np.testing.assert_allclose(espectro.curvas[traco].dados[1], espectro.resultados[0].espectro.niveis("rms"))
    assert "valor RMS (V)" in espectro.grafico.getAxis("left").labelText
    recalcular(qtbot, espectro, lambda: espectro.metodo.botao(espectro_indice("welch")).click())   # o segundo
    e = espectro.resultados[0].espectro
    assert e.parametros.metodo == "welch" and e.n_segmentos > 1 and "segmentos" in espectro.info.text()
    recalcular(qtbot, espectro, lambda: espectro.trecho.botao(2).click())          # a captura inteira
    assert espectro.resultados[0].espectro.n_amostras <= N and espectro.opcoes.trecho == "captura"
    recalcular(qtbot, espectro, pilha.undo)
    recalcular(qtbot, espectro, pilha.undo)
    recalcular(qtbot, espectro, pilha.undo)
    assert espectro.opcoes == type(espectro.opcoes)(vista_de_tempo=tempo.vista.id)
    assert espectro.escala.escolhida == 0 and espectro.metodo.escolhida == 0


def test_os_cursores_da_vista_de_tempo(janela, qtbot, aberto):
    fonte, traco, tempo, espectro = aberto
    assert espectro.opcoes.trecho == "cursores"                  # o padrão: sem os cursores, a janela visível
    tempo.ligar_cursores(True)
    a, b = (int(round(c * FS)) for c in sorted(tempo.cursores))
    recalcular(qtbot, espectro, lambda: None, quando=lambda: espectro.resultados[0].trecho.inicio == a)
    esperado = api.espectro(api.sinal_do_canal(fonte.fonte.captura, 0, a, b), FS, api.ParametrosEspectro("fft"))
    np.testing.assert_allclose(espectro.resultados[0].espectro.db, esperado.db, rtol=0, atol=1e-9)


def test_a_cadeia_da_vista_de_tempo_muda_o_espectro(janela, qtbot, aberto):
    fonte, traco, tempo, espectro = aberto
    antes = espectro.resultados[0].espectro.nivel_em(50)
    cadeia = Cadeia((Filtro("passa_altas", (2000.0,), 4),))
    recalcular(qtbot, espectro, lambda: janela.projeto.pilha.push(MudarTracos([traco], cadeia=cadeia)),
               quando=lambda: espectro.resultados[0].trecho.cadeia == cadeia)
    depois = espectro.resultados[0].espectro.nivel_em(50)
    assert depois < antes - 60                                       # o passa-altas tirou os 50 Hz
    assert "PA 2 kHz" in espectro.chips[traco].resumo


def test_a_frequencia_log_tira_o_dc_e_as_opcoes_vao_para_o_projeto(janela, qtbot, aberto, tmp_path):
    fonte, traco, tempo, espectro = aberto
    recalcular(qtbot, espectro, lambda: espectro.log.click())
    x, _ = espectro.curvas[traco].getData()                     # já em log10 (o DC, log10(0), não está)
    assert np.all(np.isfinite(x)) and espectro.grafico.getPlotItem().ctrl.logXCheck.isChecked()
    salvo = arq.de_dict(arq.para_dict(descrever(janela.projeto, tmp_path)))
    (vista_salva,) = [v for v in salvo.vistas if v.tipo == "espectro"]
    assert vista_salva.opcoes["frequencia_log"] is True and vista_salva.opcoes["vista_de_tempo"] == tempo.vista.id


def test_plotar_com_o_espectro_aberto_vai_para_a_vista_de_tempo(janela, aberto):
    fonte, traco, tempo, espectro = aberto
    novo = janela.area.plotar_canal(fonte, 1)
    assert novo in tempo.vista.tracos and not espectro.vista.tracos


def test_um_trecho_de_outro_tamanho_redesenha_na_grade_certa(janela, qtbot, aberto):
    """O espectro de um trecho de outro tamanho (outro espaçamento entre os bins, outro número deles) aparece na
    frequência certa e não passa da Nyquist: antes, o traço ficava na grade do espectro de antes (um tom de 9 kHz
    aparecia em outra frequência, e o eixo ia além de 100 kHz)."""
    fonte, traco, tempo, espectro = aberto
    recalcular(qtbot, espectro, lambda: espectro.metodo.botao(espectro_indice("fft")).click())
    for inicio, fim in ((0.1, 0.5), (0.2, 1.9), (1.0, 1.3)):
        tempo.ligar_cursores(True)
        tempo.cursores = [inicio, fim]
        tempo._por_cursores()
        a = int(round(inicio * FS))
        recalcular(qtbot, espectro, tempo.emitir_regiao, quando=lambda a=a: espectro.resultados[0].trecho.inicio == a)
        item = espectro.curvas[traco]
        d = espectro.resultados[0].desenho
        x0, x1 = item.dataBounds(0)
        assert x0 == pytest.approx(0.0) and x1 == pytest.approx(FS / 2, rel=1e-3)        # até a Nyquist, não além
        assert item.tempo_da_amostra(d.indice(9_000.0)) == pytest.approx(9_000.0, abs=d.df)
        i = int(np.argmax(d.niveis[d.indice(2_000.0):])) + d.indice(2_000.0)
        assert item.tempo_da_amostra(i) == pytest.approx(9_000.0, abs=2 * d.df)          # o tom no lugar dele


def test_os_picos_desligados_ao_abrir_e_sem_o_ruido(janela, qtbot, aberto):
    fonte, traco, tempo, espectro = aberto
    assert not espectro.acao_picos.isChecked() and espectro.resultados[0].marcas.picos == ()
    recalcular(qtbot, espectro, lambda: espectro.acao_picos.setChecked(True),
               quando=lambda: bool(espectro.resultados[0].marcas.picos))
    assert [round(p.frequencia_hz / 1000) for p in espectro.resultados[0].marcas.picos] == [9]   # só o tom
    recalcular(qtbot, espectro, lambda: espectro.acao_picos.setChecked(False),
               quando=lambda: espectro.resultados[0].marcas.picos == ())


def test_os_valores_sob_o_mouse(janela, qtbot, aberto):
    from PySide6.QtCore import QPointF

    fonte, traco, tempo, espectro = aberto
    vb = espectro.grafico.getViewBox()
    d = espectro.resultados[0].desenho
    cena = vb.mapViewToScene(QPointF(9_000.0, 0.0))
    espectro._mouse_movido(cena)
    assert not espectro.valor_no_mouse.isVisible()                    # desligado ao abrir
    espectro.acao_valores.setChecked(True)
    vb.setXRange(8_000.0, 10_000.0, padding=0)
    espectro._mouse_movido(vb.mapViewToScene(QPointF(9_000.0, 0.0)))
    assert espectro.valor_no_mouse.isVisible()
    (y,) = espectro.ponto_no_mouse.getData()[1]
    assert y == pytest.approx(d.nivel_em(9_000.0), abs=1e-9)          # o bin do tom, sob o mouse
    assert traco.nome in espectro.valor_no_mouse.textItem.toPlainText()
    espectro.acao_valores.setChecked(False)
    assert not espectro.valor_no_mouse.isVisible()


def test_os_cursores_no_espectro_encostam_no_pico(janela, qtbot, aberto):
    fonte, traco, tempo, espectro = aberto
    assert not espectro.cursores.ligados and espectro.leitura_dos_cursores.isHidden()
    espectro.acao_cursores.setChecked(True)
    assert espectro.cursores.ligados and not espectro.leitura_dos_cursores.isHidden()
    vb = espectro.grafico.getViewBox()
    vb.setXRange(8_000.0, 10_000.0, padding=0)
    d = espectro.resultados[0].desenho
    espectro.cursores.definir(9_000.5, 8_500.0)
    espectro.cursores._solta(0)                                       # solto perto do tom: encosta nele
    assert espectro.cursores.a == pytest.approx(d.f0 + d.indice(9_000.0) * d.df)
    texto = espectro.leitura_dos_cursores.text()
    assert "Δf" in texto and traco.nome in texto and "A " in texto


def test_sem_a_fundamental_a_fft_e_do_trecho_inteiro(janela, qtbot, tmp_path):
    """Um tom de 130 kHz sozinho a 400 kS/s (sem a rede para sincronizar): a FFT do trecho inteiro, com um aviso, e o
    tom no lugar dele (não além da Nyquist)."""
    fs = 400_000.0
    t = np.arange(400_000) / fs
    caminho = escrever_bin(tmp_path / "tom.bin", [np.sin(2 * np.pi * 130_000 * t)], canais=(0,), grandezas=(0,),
                           sondas=("",), fs_total=400_000, versao=9)
    (fonte,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    traco = janela.area.plotar_canal(fonte, 0)
    janela.acoes["espectro"].trigger()
    w = janela.area.widget_da_vista(janela.vista_ativa())
    qtbot.waitUntil(lambda: bool(w.resultados) and w.resultados[0].desenho is not None, timeout=10_000)
    r = w.resultados[0]
    assert r.espectro.f0_hz is None and r.espectro.janela == "hann" and "sincronizar" in w.info.text()
    i = int(np.argmax(r.desenho.niveis))
    assert w.curvas[traco].tempo_da_amostra(i) == pytest.approx(130_000.0, abs=2 * r.desenho.df)
    assert w.curvas[traco].dataBounds(0)[1] == pytest.approx(200_000.0, rel=1e-3)
