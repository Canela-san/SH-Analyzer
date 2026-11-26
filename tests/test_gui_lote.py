"""A análise em lote (``dados/lote.py`` e o "Análise em lote…" da janela): as capturas da pasta e das subpastas,
os índices de cada captura e canal iguais aos das vistas, a ordem no tempo, o CSV, a tendência e o duplo clique que
abre a captura. Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.dados import lote  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402

FS = 200_000.0
N = 200_000


def _captura(caminho, thd, afundar=False, inicio=1_700_000_000):
    t = np.arange(N) / FS
    v = 1.6 * (np.sin(2 * np.pi * 60 * t) + thd * np.sin(2 * np.pi * 180 * t))
    if afundar:
        v[100_000:110_000] *= 0.5
    caminho.parent.mkdir(parents=True, exist_ok=True)
    return escrever_bin(caminho, [v, 0.5 * v], grandezas=(0, 1), versao=9, timestamp_unix=inicio)


@pytest.fixture
def pasta(tmp_path):
    _captura(tmp_path / "dia1" / "a.bin", 0.03)
    _captura(tmp_path / "dia2" / "b.bin", 0.06, afundar=True, inicio=1_700_086_400)       # um dia depois
    (tmp_path / "dia2" / "b.h5").write_bytes(b"")              # a exportação do b.bin: fica de fora
    (tmp_path / "notas.txt").write_text("x", encoding="utf-8")
    return tmp_path


def test_as_capturas_e_os_indices(pasta):
    caminhos = lote.capturas_da_pasta(pasta)
    assert [c.name for c in caminhos] == ["a.bin", "b.bin"]
    assert lote.capturas_da_pasta(pasta, recursivo=False) == []
    linhas = lote.calcular(caminhos)
    assert [(linha.arquivo, linha.canal) for linha in linhas] == [("a.bin", 0), ("a.bin", 1), ("b.bin", 0),
                                                                   ("b.bin", 1)]
    a0, _a1, b0, _b1 = linhas
    assert a0.thd_p95 == pytest.approx(0.03, rel=0.02) and b0.thd_p95 == pytest.approx(0.06, rel=0.02)
    assert a0.frequencia_hz == pytest.approx(60, abs=0.01) and a0.integridade == "confere"
    assert a0.eventos == _a1.eventos == 0 and b0.eventos >= 1 and b0.marcadas >= 1
    assert (b0.inicio - a0.inicio).days == 1
    csv = lote.em_csv(linhas)
    assert csv.splitlines()[0].startswith("arquivo;caminho;inicio") and "0,03" in csv.splitlines()[1]
    curto = lote.calcular_captura(caminhos[0], canais=[0], limite_s=0.5)
    assert len(curto) == 1 and curto[0].duracao_s == pytest.approx(0.5)


def test_o_dialogo_da_janela(qapp, config_limpa, qtbot, pasta, tmp_path):
    criar_aplicacao([], tema="escuro")
    janela = JanelaPrincipal()
    janela.controle.dialogos = DialogosFalsos(str(tmp_path / "lote.csv"))
    janela.show()
    try:
        dialogo = janela.analise_em_lote(pasta)
        tarefa = dialogo.calcular()
        qtbot.waitUntil(lambda: tarefa.estado == "concluida" and bool(dialogo.linhas), timeout=30_000)
        assert dialogo.tabela.rowCount() == 4 and "2 capturas" in dialogo.estado.text()
        serie = dialogo.series("thd_p95")
        assert len(serie) == 2 and all(len(x) == 2 for x, _y in serie.values())
        assert list(serie.values())[0][1] == pytest.approx([3.0, 6.0], rel=0.02)
        assert dialogo.exportar().read_text(encoding="utf-8").count("\n") == 5
        dialogo.tabela.cellDoubleClicked.emit(2, 0)
        qtbot.waitUntil(lambda: len(janela.projeto.fontes) == 1, timeout=10_000)
        assert janela.projeto.fontes[0].nome == "b.bin"
        dialogo.close()
    finally:
        janela.projeto.pilha.setClean()
        janela.close()
        janela.deleteLater()
