"""As vistas de análise da Fase 7 na janela, sem tela: abertas pelo menu "Análises" do canto das abas, ligadas à vista
de tempo, com a conta em segundo plano e as tabelas que copiam para a planilha."""

import math

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import FS_TOTAL_2CH, escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
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
    widget.tabela.selectRow(k)                                    # o clique: o evento na vista de tempo
    inicio, fim = widget.vista_de_tempo().janela_de_tempo()
    margem = max(0.5 * e.duracao_s, 0.05)
    assert inicio == pytest.approx(e.inicio_s - margem, abs=1e-6)
    assert fim == pytest.approx(e.inicio_s + e.duracao_s + margem, abs=1e-6)
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
