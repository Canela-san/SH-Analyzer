"""As vistas de análise da Fase 7 na janela, sem tela: abertas pelo menu "Análises" do canto das abas, ligadas à vista
de tempo, com a conta em segundo plano e as tabelas que copiam para a planilha."""

import math

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import FS_TOTAL_2CH, escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtCore import QItemSelectionModel, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolButton  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.analise.vistas_de_analise import texto_da_tabela  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402

FS = FS_TOTAL_2CH / 2
ESPERA_MS = 20_000


@pytest.fixture
def janela(qapp, config_limpa, qtbot):
    criar_aplicacao([], tema="escuro")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.resize(1400, 900)
    j.show()
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


@pytest.fixture
def tracos(janela, tmp_path):
    """A tensão (9 V de pico no pino) e a corrente atrasada 30°, com o 3º harmônico."""
    t = np.arange(int(FS * 0.5)) / FS
    w = 2 * np.pi * 60
    v = 9.0 * np.sin(w * t)
    i = 4.0 * np.sin(w * t - math.radians(30)) + 1.0 * np.sin(3 * w * t)
    (fonte,) = janela.controle.abrir_capturas([escrever_bin(tmp_path / "vi.bin", [v, i], versao=9)])
    return janela.area.plotar_canal(fonte, 0), janela.area.plotar_canal(fonte, 1)


def abrir(janela, qtbot, nome):
    acao = janela.acoes[nome]
    assert acao in janela.menu_de_analises.actions()
    acao.trigger()
    widget = janela.area.widget_da_vista(janela.vista_ativa())
    qtbot.waitUntil(lambda: widget.resultado is not None, timeout=ESPERA_MS)
    return widget


def test_o_xy_e_a_potencia(janela, tracos, qtbot):
    widget = abrir(janela, qtbot, "xy")
    assert widget.vista.tipo == "xy" and widget.seletor_y.currentIndex() == 1
    r = widget.resultado
    assert r.potencia is not None and r.x is not None
    assert r.potencia.fi1_graus == pytest.approx(30.0, abs=0.05)
    texto = texto_da_tabela(widget.tabela)
    assert texto.splitlines()[0].split("\t")[0] == "Grandeza" and "cos φ₁" in texto and "THD I" in texto
    assert r.potencia.thd_i == pytest.approx(0.25, rel=1e-3)
    widget.com_potencia.setChecked(False)                       # sem a potência: a conta refaz, sem ela
    qtbot.waitUntil(lambda: widget.resultado.potencia is None, timeout=ESPERA_MS)
    janela.projeto.pilha.undo()
    qtbot.waitUntil(lambda: widget.resultado.potencia is not None, timeout=ESPERA_MS)


def test_o_histograma_e_as_estatisticas(janela, tracos, qtbot):
    widget = abrir(janela, qtbot, "histograma")
    e, h = widget.resultado.estatisticas, widget.resultado.histograma
    assert h.codigos and e.n > 0 and widget.tabela.rowCount() >= 15
    widget.tabela.selectAll()
    widget.tabela.actions()[0].trigger()                         # Ctrl+C: a seleção para a planilha
    copiado = QApplication.clipboard().text()
    assert copiado.startswith("Estatística\tValor") and "Assimetria" in copiado
    widget.colunas.setValue(50)
    qtbot.waitUntil(lambda: len(widget.resultado.histograma.contagens) <= 50, timeout=ESPERA_MS)
    calculado = widget.resultado
    widget.acumulada.setChecked(True)                            # só o desenho: a conta não refaz
    widget.escala.escolher(1)
    assert len(widget.curva_acumulada.getData()[0]) > 0 and widget.resultado is calculado
    assert widget.opcoes.escala == "log" and widget.opcoes.acumulada


def _rede(janela, tmp_path, afundamento: bool):
    """0,6 s de rede (8 V de pico, com o 5º harmônico a 5 %); com o afundamento, a 50 % de 0,2 a 0,3 s."""
    t = np.arange(int(FS * 0.6)) / FS
    w = 2 * np.pi * 60
    amplitude = np.where((t >= 0.2) & (t < 0.3), 4.0, 8.0) if afundamento else 8.0
    v = amplitude * np.sin(w * t) + 0.4 * np.sin(5 * w * t)
    (fonte,) = janela.controle.abrir_capturas([escrever_bin(tmp_path / "rede.bin", [v, 0.5 * v], versao=9)])
    return janela.area.plotar_canal(fonte, 0)


@pytest.fixture
def rede_com_afundamento(janela, tmp_path):
    return _rede(janela, tmp_path, True)


@pytest.fixture
def rede(janela, tmp_path):
    return _rede(janela, tmp_path, False)


def test_os_eventos_e_o_clique_que_mostra_no_tempo(janela, rede_com_afundamento, qtbot):
    widget = abrir(janela, qtbot, "eventos")
    assert widget.vista.tipo == "eventos" and widget.opcoes.trecho == "captura"
    tipos = [e.tipo for e in widget.eventos_mostrados()]
    assert "afundamento" in tipos, tipos
    k = tipos.index("afundamento")
    assert widget.tabela.item(k, 0).text() == "Afundamento"
    e = widget.eventos_mostrados()[k]                             # o RMS de ½ ciclo: até um ciclo de atraso
    assert e.inicio_s == pytest.approx(0.2, abs=1 / 60) and e.inicio_s + e.duracao_s == pytest.approx(0.3, abs=1.5 / 60)
    # Sob carga, a pirâmide da vista de tempo chega depois dos eventos: sem os dados, o clique fica pedido (vale quando
    # eles chegam) e a janela ainda não mudou.
    qtbot.waitUntil(lambda: widget.vista_de_tempo().tem_dados, timeout=ESPERA_MS)
    # O clique: o evento na vista de tempo. A seleção com o comando explícito: o selectRow segue os modificadores
    # do último evento de teclado do processo, e um teste anterior que deixou um deles fazia a seleção sair vazia.
    widget.tabela.selectionModel().select(
        widget.tabela.model().index(k, 0),
        QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
    tempo = widget.vista_de_tempo()
    inicio, fim = tempo.janela_de_tempo()
    margem = max(0.5 * e.duracao_s, 0.05)
    assert inicio == pytest.approx(e.inicio_s - margem, abs=1e-6)
    assert fim == pytest.approx(e.inicio_s + e.duracao_s + margem, abs=1e-6)
    tempo.mostrar_tempo(0.0, 0.1)                                 # o tempo andou; o clique na mesma linha volta
    widget.tabela.cellClicked.emit(k, 0)
    assert tempo.janela_de_tempo() == pytest.approx((inicio, fim), abs=1e-6)
    calculado = widget.resultado
    widget.filtro.setCurrentIndex(widget.filtro.findData("afundamento"))
    assert widget.tabela.rowCount() == 1 and widget.resultado is calculado
    widget.tensao.setChecked(False)
    qtbot.waitUntil(lambda: widget.resultado is not calculado, timeout=ESPERA_MS)
    assert not [e for e in widget.resultado.eventos if e.tipo == "afundamento"]


def test_a_qualidade_de_energia(janela, rede, qtbot):
    widget = abrir(janela, qtbot, "qualidade")
    r = widget.resultado
    assert r.ciclos_por_janela == 12 and r.n_janelas >= 2
    assert widget.tabela.rowCount() == 8 and widget.tabela.item(2, 0).text() == "THD"
    thd = widget.curva.getData()[1]
    assert thd[0] == pytest.approx(5.0, rel=1e-2)               # em %: 0,4 / 8
    widget.indice.setCurrentIndex(widget.indice.findData("rms"))
    widget.indice.activated.emit(widget.indice.currentIndex())
    assert widget.opcoes.indice == "rms" and widget.resultado is r     # só o desenho
    assert widget.curva.getData()[1][0] == pytest.approx(math.sqrt((64 + 0.16) / 2), rel=1e-2)
    botao = [b for b in widget.findChildren(QToolButton) if b.objectName() == "copiar_janelas_da_qualidade"][0]
    botao.click()
    linhas = QApplication.clipboard().text().splitlines()
    assert linhas[0].startswith("Início (s)\tFrequência (Hz)") and len(linhas) == r.n_janelas + 1


@pytest.fixture
def entrada_e_saida(janela, tmp_path):
    """Ruído branco na entrada e a saída por um passa-baixa de 1ª ordem em 2 kHz, com ganho 0,5."""
    import scipy.signal

    rng = np.random.default_rng(2)
    x = rng.standard_normal(int(FS * 1.0))
    b, a = scipy.signal.butter(1, 2_000, fs=FS)
    y = 0.5 * scipy.signal.lfilter(b, a, x)
    (fonte,) = janela.controle.abrir_capturas([escrever_bin(tmp_path / "h.bin", [x, y], versao=9)])
    return (janela.area.plotar_canal(fonte, 0), janela.area.plotar_canal(fonte, 1)), (b, a)


def test_a_transferencia_com_o_intervalo_e_os_cursores(janela, entrada_e_saida, qtbot):
    import scipy.signal

    _, (b, a) = entrada_e_saida
    widget = abrir(janela, qtbot, "transferencia")
    assert widget.seletor_y.currentIndex() == 1
    r = widget.resultado
    assert r.amostras_por_segmento == 2000 and r.medias == 199
    f, mag, baixo, alto, *_ = widget._dados()
    _, h = scipy.signal.freqz(b, a, worN=f[5:200], fs=FS)
    assert np.max(np.abs(mag[5:200] - 20 * np.log10(0.5 * np.abs(h)))) < 0.3
    assert np.all(baixo[5:200] <= mag[5:200]) and np.all(alto[5:200] >= mag[5:200])
    widget.acao_cursores.setChecked(True)
    m = widget.medidas()
    assert m is not None and "|H|" in m.resumo and m.planilha.startswith("f (Hz)")
    botao = [b for b in widget.findChildren(QToolButton) if b.objectName() == "copiar_transferencia"][0]
    botao.click()
    assert QApplication.clipboard().text().startswith("f (Hz)\t|H| (dB)")
    widget.resolucao.setText("500 Hz")
    widget.resolucao.editingFinished.emit()
    qtbot.waitUntil(lambda: widget.resultado.amostras_por_segmento == 400, timeout=ESPERA_MS)


@pytest.fixture
def tom_e_imagem(janela, tmp_path):
    """400 kS/s por canal: 1 kHz a 9 V com o 3º harmônico a −60 dBc, e uma entrada de 250 kHz (a imagem em 150 kHz);
    e a mesma entrada a 312,5 kS/s (a imagem em 62,5 kHz)."""
    fs = 400_000
    t = np.arange(int(fs * 0.5)) / fs
    rng = np.random.default_rng(6)
    x = 9 * np.sin(2 * np.pi * 1000 * t) + 9e-3 * np.sin(2 * np.pi * 3000 * t) + 2e-3 * rng.standard_normal(len(t))
    y = 0.5 * np.sin(2 * np.pi * 250_000 * t) + 1e-3 * rng.standard_normal(len(t))
    caminhos = [escrever_bin(tmp_path / "t400.bin", [x, y], fs_total=2 * fs, faixas_adc_total_v=20.48)]
    fs2 = 312_500                    # 200 MHz ÷ 320 ticks por par de canais: a taxa do cabeçalho é exata
    t2 = np.arange(int(fs2 * 0.5)) / fs2
    y2 = 0.5 * np.sin(2 * np.pi * 250_000 * t2) + 1e-3 * rng.standard_normal(len(t2))
    caminhos.append(escrever_bin(tmp_path / "t312.bin", [np.zeros_like(y2), y2], fs_total=2 * fs2,
                                 faixas_adc_total_v=20.48))
    fontes = janela.controle.abrir_capturas(caminhos)
    janela.area.plotar_canal(fontes[0], 0)
    janela.area.plotar_canal(fontes[0], 1)
    return fontes


def test_as_metricas_de_bancada(janela, tom_e_imagem, qtbot):
    widget = abrir(janela, qtbot, "metricas")
    m = widget.resultado
    assert widget.vista.tipo == "metricas" and m.espectro.tem_tom
    assert m.espectro.freq_tom_hz == pytest.approx(1000, abs=0.01) and m.espectro.thd_db == pytest.approx(-60, abs=0.5)
    assert widget.cartoes["tom"].texto.endswith("Hz") and widget.cartoes["thd"].texto.startswith("−60") and widget.cartoes["thd"].texto.endswith(" dB")
    assert widget.cartoes["ruido"].texto.endswith(" LSB") and "m" not in widget.cartoes["ruido"].texto
    assert widget.cartoes["enob"].texto.endswith("bits") and len(widget._barras) >= 1
    texto = texto_da_tabela(widget.tabela)
    assert "SINAD" in texto and "H3" in texto and "LSB" in texto
    widget.harmonicos.setValue(5)
    qtbot.waitUntil(lambda: len(widget.resultado.espectro.harmonicos) == 4, timeout=ESPERA_MS)


def test_o_aviso_de_imagem_no_espectro(janela, tom_e_imagem, qtbot):
    janela.acoes["espectro"].trigger()
    espectro = janela.area.widget_da_vista(janela.vista_ativa())
    espectro.acao_picos.setChecked(True)
    qtbot.waitUntil(lambda: "podem ser imagens" in espectro.info.text(), timeout=ESPERA_MS)
    assert "1 pico(s) acima de 96,1 kHz" in espectro.info.text()             # o de 150 kHz; o de 3 kHz, não


def test_o_assistente_de_aliasing(janela, tom_e_imagem, qtbot):
    from sh_analyzer_gui.areas.analise.vistas_de_bancada import DialogoDeAliasing

    assert janela.acoes["aliasing"] in janela.menu_de_analises.actions()
    janela.acoes["aliasing"].trigger()
    dialogo = janela.findChild(DialogoDeAliasing, "dialogo_aliasing")
    assert dialogo is not None and not dialogo.analisar.isEnabled()
    for i in range(dialogo.lista.count()):
        dialogo.lista.item(i).setCheckState(Qt.CheckState.Checked)
    dialogo.canal.setCurrentIndex(dialogo.canal.findData(1))
    assert dialogo.analisar.isEnabled()
    dialogo.analisar.click()
    qtbot.waitUntil(lambda: dialogo.resultado is not None, timeout=ESPERA_MS)
    imagens = [c for c in dialogo.resultado.componentes if c.frequencia_entrada_hz and not any(c.reais)]
    assert [round(c.frequencia_entrada_hz / 1e3) for c in imagens] == [250]
    texto = texto_da_tabela(dialogo.tabela)
    assert texto.startswith("Entrada\tEm A") and "imagem nas duas, de 250,00 kHz" in texto
    dialogo.close()


def test_o_instrumento(janela, tracos, qtbot):
    widget = abrir(janela, qtbot, "instrumento")
    r = widget.resultado
    assert widget.vista.tipo == "instrumento" and r.disparo.n >= 20
    assert r.tempo_por_divisao == pytest.approx(0.005)                  # 2 ciclos de 60 Hz em 10 div: 3,3 ms → 5 ms
    v, i = r.canais
    assert v.por_divisao == pytest.approx(5.0) and v.persistencia.amostras > 0   # 9 V de pico: 2,25 V por div → 5
    assert np.interp(0.0, v.ciclo.tempos_s, v.ciclo.media) == pytest.approx(0.0, abs=0.05)
    assert v.ciclo.rms == pytest.approx(9 / math.sqrt(2), rel=0.01)
    assert widget.tabela.rowCount() == 3 and widget.tabela.item(2, 0).text() == "Disparo"
    widget.borda.escolher(1)                                            # descendo: o ciclo médio começa no pico
    qtbot.waitUntil(lambda: widget.opcoes.borda == "descendo" and widget.resultado is not r, timeout=ESPERA_MS)
    v2 = widget.resultado.canais[0]
    assert np.interp(-1 / 240, v2.ciclo.tempos_s, v2.ciclo.media) == pytest.approx(9.0, rel=0.02)
    widget.traco_da_escala.setCurrentIndex(1)
    widget.por_divisao.setText("1 V/div")
    widget.por_divisao.editingFinished.emit()
    assert widget.opcoes.escalas == ((0.0, 0.0), (1.0, 0.0))
    qtbot.waitUntil(lambda: widget.resultado.canais[1].por_divisao == 1.0, timeout=ESPERA_MS)
    salvo = widget.opcoes.para_dict()
    assert type(widget.opcoes).de_dict(salvo) == widget.opcoes


def test_o_vao_minimo_do_eixo_da_qualidade():
    """Uma THD quase constante não ocupa a altura toda: o vão é pelo menos 1 % do valor, em volta do meio."""
    import numpy as np
    from sh_analyzer_gui.areas.analise.vistas_de_analise import vao_do_indice

    mn, mx = vao_do_indice(np.array([3.9857, np.nan, 3.9867]))
    assert mx - mn == pytest.approx(0.039867) and (mn + mx) / 2 == pytest.approx(3.9862)
    assert vao_do_indice(np.array([1.0, 5.0])) == (1.0, 5.0)            # variação de verdade: como está
    assert vao_do_indice(np.array([0.0, 0.0])) == (-1.0, 1.0)
    assert vao_do_indice(np.array([np.nan])) is None


def test_os_nomes_dos_eventos_na_fonte_da_interface(janela, tracos, qtbot):
    eventos = abrir(janela, qtbot, "eventos")
    eixo = eventos.grafico.getAxis("left")
    assert eixo.categorias and eixo.style["tickFont"].family() != eventos.grafico.getAxis("bottom").style["tickFont"].family()


def test_o_inspetor_das_vistas_derivadas(janela, tracos, qtbot):
    """Sem traço selecionado, a vista derivada à frente mostra no inspetor o que ela é, de qual vista de tempo segue
    os traços e a ajuda dela (antes: "Nada selecionado")."""
    abrir(janela, qtbot, "qualidade")
    janela.selecao.definir(())
    janela.area._inspetor_da_vista(trocou_de_aba=True)
    da_vista = janela.inspetor.da_vista
    assert janela.inspetor.currentWidget() is da_vista
    assert "IEC 61000-4-30" in da_vista.descricao.text() and not da_vista.espectro.isVisibleTo(da_vista)
    assert "Tempo" in da_vista.origem.text()
    da_vista.ajuda.click()
    assert janela.leitor_do_guia.secao_atual == "qualidade"
