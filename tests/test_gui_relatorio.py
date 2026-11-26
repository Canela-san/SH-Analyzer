"""O relatório da captura (``dados/relatorio.py`` e o "Relatório da captura…" da janela): as contas das vistas no
trecho inteiro de cada traço, o HTML com as figuras dentro e o texto escapado, e o PDF. Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.dados import relatorio as rel  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402

FS = 200_000.0
N = 300_000


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


def test_o_html_escapa_o_texto_e_poe_as_figuras_dentro():
    t = rel.TracoDoRelatorio("<v>", "V", "canal 0 & cadeia", figuras=[("a & b", b"\x89PNG")])
    f = rel.FonteDoRelatorio("x<y>.bin", [("Captura", [("Taxa", "200 kS/s")])], "confere", ("cuidado <aqui>",))
    import datetime
    pagina = rel.em_html(rel.Relatorio("R & D", [f], [t], "SH-Analyzer teste", datetime.datetime(2026, 11, 26)),
                         lambda v, u, d: f"{v:g} {u}")
    assert "<h1>R &amp; D</h1>" in pagina and "x&lt;y&gt;.bin" in pagina and "cuidado &lt;aqui&gt;" in pagina
    assert 'src="data:image/png;base64,iVBORw==' in pagina and "Nenhum evento" in pagina
    assert 'src="figura-1.png"' in rel.em_html(rel.Relatorio("R", [f], [t], "a", datetime.datetime.now()),
                                                lambda v, u, d: "", para_o_qt=True)


def test_o_relatorio_da_janela_em_html_e_em_pdf(janela, qtbot, tmp_path):
    t = np.arange(N) / FS
    v = 180.0 * np.sqrt(2) * np.sin(2 * np.pi * 60 * t) + 0.5 * np.sin(2 * np.pi * 16_100 * t)
    v[150_000:160_000] *= 0.5                                       # um afundamento de 50 ms
    caminho = escrever_bin(tmp_path / "rede.bin", [v / 100.0, v / 200.0], grandezas=(0, 1), versao=9)
    (fonte,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    janela.area.plotar_canal(fonte, 0)
    gerados = []
    janela.area.relatorioGerado.connect(gerados.append)
    destino = tmp_path / "relatorio.html"
    janela.acoes["relatorio"].setEnabled(True)
    janela.controle.dialogos = DialogosFalsos(str(destino))
    janela.acoes["relatorio"].trigger()
    qtbot.waitUntil(lambda: gerados == [destino], timeout=20_000)
    pagina = destino.read_text(encoding="utf-8")
    assert "Qualidade de energia" in pagina and "Afundamento" in pagina and "16,1 kHz" in pagina
    assert pagina.count('src="data:image/png;base64,') == 2 and "rede.bin" in pagina
    pdf = tmp_path / "relatorio.pdf"
    janela.area.gerar_relatorio(pdf)
    qtbot.waitUntil(lambda: gerados[-1] == pdf, timeout=20_000)
    assert pdf.read_bytes()[:5] == b"%PDF-" and pdf.stat().st_size > 20_000
