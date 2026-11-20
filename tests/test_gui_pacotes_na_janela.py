"""Os pacotes ``.zpaq.tar`` na janela (F7.10), sem tela: abrir pelo Ctrl+O, pelos recentes e arrastando; a extração
numa tarefa, as capturas na árvore com as mesmas amostras, o pacote nos recentes e o cache nas Configurações."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.componentes.toast import Toast  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from supraharmonicos import api  # noqa: E402
from supraharmonicos import compactacao as cp  # noqa: E402

ESPERA_MS = 30_000


@pytest.fixture
def janela(qapp, config_limpa, qtbot, tmp_path):
    criar_aplicacao([], tema="escuro")
    preferencias.mudar_pasta("cache", tmp_path / "cache")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.resize(1400, 900)
    j.show()
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


@pytest.fixture
def pacote(tmp_path):
    origem = tmp_path / "sessao"
    origem.mkdir()
    rng = np.random.default_rng(9)
    originais = [escrever_bin(origem / f"c{k}.bin", [rng.standard_normal(30_000), rng.standard_normal(30_000)],
                              versao=9) for k in range(2)]
    entradas, _ = cp.descobrir_entradas([origem])
    saida = tmp_path / "sessao.zpaq.tar"
    cp.compactar(entradas, saida, metodo=cp.METODOS["rapido"], processos=2)
    return saida, originais


def test_abrir_um_pacote(janela, pacote, qtbot):
    caminho, originais = pacote
    assert janela.controle.abrir_arquivos([caminho])
    qtbot.waitUntil(lambda: len(janela.projeto.fontes) == 2, timeout=ESPERA_MS)
    fontes = janela.projeto.fontes
    assert [f.nome for f in fontes] == ["c0.bin", "c1.bin"]
    for fonte, original in zip(fontes, originais):
        assert janela.pacotes.cache.pasta_de(fonte.caminho) == janela.pacotes.cache.pasta_do_pacote(caminho)
        assert np.array_equal(fonte.canal(1).amostras, api.abrir_captura(original).canal(1).amostras)
    assert janela.controle.recentes_capturas()[0] == caminho.resolve()     # o pacote, e não as extraídas
    assert janela.pacotes.cache.tamanho_bytes > 0
    assert janela.pacotes.limpar_cache() == 0                               # as abertas ficam
    janela.controle.abrir_arquivos([caminho])                               # de novo: já estão no projeto
    qtbot.wait(300)
    assert len(janela.projeto.fontes) == 2


def test_um_pacote_que_nao_abre(janela, tmp_path, qtbot):
    falso = tmp_path / "quebrado.zpaq.tar"
    falso.write_bytes(b"\0" * 2048)
    janela.controle.abrir_arquivos([falso])
    qtbot.waitUntil(lambda: any("Não foi possível abrir quebrado.zpaq.tar" in t.rotulo.text()
                                for t in janela.findChildren(Toast)), timeout=ESPERA_MS)
    assert not janela.projeto.fontes


def test_o_cache_dos_pacotes_nas_configuracoes(janela, pacote, qtbot):
    janela.controle.abrir_arquivos([pacote[0]])
    qtbot.waitUntil(lambda: len(janela.projeto.fontes) == 2, timeout=ESPERA_MS)
    assert "pacotes" in preferencias.CACHES
    assert preferencias.pasta_do_cache("pacotes") == janela.pacotes.cache.pasta
