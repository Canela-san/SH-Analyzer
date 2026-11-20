"""As vistas de análise da Fase 7 na janela, sem tela: abertas pelo menu "Análises" do canto das abas, ligadas à vista
de tempo, com a conta em segundo plano e as tabelas que copiam para a planilha."""

import math

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import FS_TOTAL_2CH, escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
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
    widget.acumulada.setChecked(True)
    assert len(widget.curva_acumulada.getData()[0]) > 0
