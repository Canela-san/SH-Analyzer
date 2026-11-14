"""Os cursores e as medidas (F1.7): os cursores iguais em todas as faixas, movidos amostra a amostra; as medidas da
região calculadas das amostras pela ``api`` (as mesmas contas da CLI, ``test_api.py``), entre os cursores ou na
janela visível; a tabela que copia para a planilha. Sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from sh_analyzer_gui.modelo.comandos import MudarTracos  # noqa: E402
from sh_analyzer_gui.servicos import medidas as servico  # noqa: E402
from supraharmonicos.api import medir_regiao  # noqa: E402

FS = 200_000                       # a taxa de cada canal (400 kS/s no total, 2 canais)


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
def plotado(janela, qtbot, tmp_path):
    t = np.arange(FS // 2) / FS                                          # 0,5 s de 59,98 Hz
    caminho = escrever_bin(tmp_path / "a.bin", [2 * np.sin(2 * np.pi * 59.98 * t) + 0.25,
                                                 0.5 * np.cos(2 * np.pi * 59.98 * t)],
                           grandezas=(0, 1), versao=9, extensao={"ganhos": [10.0, 20.0]})
    (fonte,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)
    a = janela.area.plotar_canal(fonte, 0)
    b = janela.area.plotar_canal(fonte, 1)
    vista = janela.area.widget_da_vista(janela.vista_ativa())
    return fonte, a, b, vista


def esperar_medidas(janela, qtbot, dos_cursores):
    tabela = janela.tabela_de_medidas
    qtbot.waitUntil(lambda: bool(tabela.pedido is not None and tabela.pedido.dos_cursores == dos_cursores
                                 and tabela.medidas), timeout=10_000)
    return tabela


def test_sem_cursores_mede_a_janela_visivel(janela, plotado, qtbot):
    fonte, a, b, vista = plotado
    tabela = esperar_medidas(janela, qtbot, False)
    assert [m.traco for m in tabela.medidas] == [a, b]
    assert tabela.resumo.text().startswith("Janela visível")
    m = tabela.medidas[0]
    i0, i1 = max(0, round(m.inicio_s * FS)), min(len(fonte.canal(0).amostras), round(m.fim_s * FS))
    esperado = medir_regiao(fonte.fonte.captura, 0, i0, i1)
    assert m.medidas == esperado and m.unidade == "V" and tabela.medidas[1].unidade == "A"
    assert m.medidas.f1_hz == pytest.approx(59.98, abs=0.01)
    assert janela.tarefas.visiveis == () and janela.lista_de_tarefas.linhas == ()   # contas rápidas não aparecem


def test_os_cursores_e_as_medidas_entre_eles(janela, plotado, qtbot):
    fonte, a, b, vista = plotado
    esperar_medidas(janela, qtbot, False)
    vista.acao_cursores.trigger()
    assert vista.cursores is not None and len(vista._linhas_dos_cursores) == 2
    assert all(len(linhas) == 2 for linhas in vista._linhas_dos_cursores)        # uma por faixa
    vista._linhas_dos_cursores[0][1].setValue(0.1)                               # arrastado na 2ª faixa
    vista._linhas_dos_cursores[1][0].setValue(0.3)
    assert vista._linhas_dos_cursores[0][0].value() == 0.1 and vista.cursores == [0.1, 0.3]
    assert vista.mover_cursor(+10)                                               # o ativo: o C2
    assert vista.cursores[1] == pytest.approx(0.3 + 10 / FS)
    tabela = esperar_medidas(janela, qtbot, True)
    assert tabela.pedido.inicio_s == pytest.approx(0.1) and "Δt" in tabela.resumo.text()
    m = tabela.medidas[0]
    i0, i1 = round(0.1 * FS), round((0.3 + 10 / FS) * FS)
    assert m.medidas == medir_regiao(fonte.fonte.captura, 0, i0, i1)
    valores = servico.medir_pontos(fonte.fonte.captura, a.receita, (i0, i1))
    assert m.delta_y == pytest.approx(valores[1] - valores[0])
    vista.acao_cursores.trigger()                                                # desliga: volta à janela
    assert vista.cursores is None and vista._linhas_dos_cursores == []
    esperar_medidas(janela, qtbot, False)


def test_o_ganho_do_traco_entra_nas_medidas(janela, plotado, qtbot):
    fonte, a, b, vista = plotado
    esperar_medidas(janela, qtbot, False)
    antes = janela.tabela_de_medidas.medidas[0].medidas
    janela.projeto.pilha.push(MudarTracos([a], ganho=-2.0, offset=1.0))
    qtbot.waitUntil(lambda: janela.tabela_de_medidas.medidas[0].medidas.media != antes.media, timeout=10_000)
    depois = janela.tabela_de_medidas.medidas[0].medidas
    assert depois.media == pytest.approx(-2 * antes.media + 1.0) and depois.rms_ac == pytest.approx(2 * antes.rms_ac)


def test_copiar_para_a_planilha(janela, plotado, qtbot):
    esperar_medidas(janela, qtbot, False)
    tabela = janela.tabela_de_medidas
    tabela.copiar()
    texto = QApplication.clipboard().text()
    linhas = texto.strip("\n").split("\n")
    assert linhas[0].split("\t")[:4] == ["Traço", "Unidade", "Início (s)", "Fim (s)"]
    campos = linhas[1].split("\t")
    m = tabela.medidas[0].medidas
    assert campos[1] == "V" and float(campos[4].replace(",", ".")) == m.media and "." not in campos[4]
    assert campos[-1] == str(m.n_amostras) and len(linhas) == 3


def test_uma_regiao_grande_demais_nao_e_lida(janela, plotado, qtbot, monkeypatch):
    monkeypatch.setattr(servico, "LIMITE_DE_AMOSTRAS", 1000)
    fonte, a, b, vista = plotado
    vista.emitir_regiao()
    qtbot.waitUntil(lambda: bool(janela.tabela_de_medidas.medidas and janela.tabela_de_medidas.medidas[0].erro),
                    timeout=10_000)
    m = janela.tabela_de_medidas.medidas[0]
    assert m.medidas is None and "grande demais" in m.erro


def test_trocar_de_aba_mede_a_vista_aberta(janela, plotado, qtbot):
    fonte, a, b, vista = plotado
    esperar_medidas(janela, qtbot, False)
    janela.acoes["nova_vista"].trigger()                                         # vazia: sem medidas
    qtbot.waitUntil(lambda: janela.tabela_de_medidas.currentWidget() is janela.tabela_de_medidas.vazio)
    janela.vistas.setCurrentIndex(0)
    esperar_medidas(janela, qtbot, False)
    assert [m.traco for m in janela.tabela_de_medidas.medidas] == [a, b]


def test_a_f1_da_janela_tem_limite_e_a_dos_cursores_nao(janela, plotado, qtbot, monkeypatch):
    monkeypatch.setattr(servico, "LIMITE_DA_F1_NA_JANELA", 1000)
    fonte, a, b, vista = plotado
    vista.emitir_regiao()
    qtbot.waitUntil(lambda: bool(janela.tabela_de_medidas.medidas
                                 and janela.tabela_de_medidas.medidas[0].medidas.problema_f1 == servico.AVISO_DA_F1),
                    timeout=10_000)
    m = janela.tabela_de_medidas.medidas[0].medidas
    assert m.f1_hz is None and m.rms > 0                                         # as outras medidas continuam
    vista.acao_cursores.trigger()
    vista._linhas_dos_cursores[0][0].setValue(0.05)
    vista._linhas_dos_cursores[1][0].setValue(0.45)
    tabela = esperar_medidas(janela, qtbot, True)
    assert tabela.medidas[0].medidas.f1_hz == pytest.approx(59.98, abs=0.01)    # entre os cursores, sem limite
