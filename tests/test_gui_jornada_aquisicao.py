"""A jornada da Aquisição, de ponta a ponta (F3.10: o "pronto quando" da Fase 3, docs/gui-plan.md): na janela e pelos
gestos do usuário, com o simulador servido por SSH neste computador. Achar a placa (o simulador aparece na lista
sozinho), conectar com um clique (a chave do aplicativo), ver a visão geral e o diagnóstico, trocar para o cenário do
relógio errado e acertá-lo pelo computador, transferir uma captura (a cópia conferida pelo CRC das amostras) e
abri-la na Análise, com a tensão plotada e o espectro com a rede e os supraharmônicos da placa simulada. Sem placa e
sem tela."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("asyncssh")

from dialogos_falsos import DialogosFalsos  # noqa: E402
from placas_de_teste import CofreFalso  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.aquisicao.lateral import SECOES  # noqa: E402
from sh_analyzer_gui.janela import AREA_ANALISE, AREA_AQUISICAO, JanelaPrincipal  # noqa: E402
from sh_placa import capturas_simuladas, chaves  # noqa: E402
from sh_placa.descoberta import Descoberta, FonteSimulador  # noqa: E402

ESPERA_MS = 30_000
TENSAO = 1                                    # o canal 1 das capturas simuladas (o 0 é a corrente)


@pytest.fixture
def janela(qapp, config_limpa, qtbot, tmp_path, monkeypatch):
    """A janela do aplicativo, com a lista de placas só com o simulador (a rede de verdade não é sondada) e capturas
    de 2¹⁶ amostras por bloco: 0,33 s por canal nas de dois blocos, o bastante para o espectro."""
    monkeypatch.setenv("DADOS", str(tmp_path / "dados"))
    monkeypatch.setattr(capturas_simuladas, "BLOCO_DAS_CAPTURAS", 1 << 16)
    monkeypatch.setattr(chaves, "CofreDeSenhas", CofreFalso)          # o cofre de quem desenvolve fica de fora
    criar_aplicacao([], tema="escuro")
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.conexao_da_placa.descoberta = Descoberta([FonteSimulador()])
    j.resize(1440, 900)
    j.show()
    qtbot.waitExposed(j)
    yield j
    j.projeto.pilha.setClean()
    j.close()
    j.deleteLater()


def clicar(vista, indice) -> None:
    vista.scrollTo(indice)
    QTest.mouseClick(vista.viewport(), Qt.MouseButton.LeftButton, pos=vista.visualRect(indice).center())


def secao(area, nome) -> None:
    """O clique na seção, na coluna da esquerda."""
    navegacao = area.lateral.navegacao
    clicar(navegacao, navegacao.model().index([s[0] for s in SECOES].index(nome), 0))
    assert area.secoes.currentWidget() is area.paginas[nome]


def esperar_a_placa(qtbot, janela, cenario) -> None:
    c, s = janela.conexao_da_placa, janela.saude_da_placa
    qtbot.waitUntil(lambda: c.estado == "conectada" and c.cenario == cenario and s.saude is not None
                    and s.capturas is not None and not s.conferindo, timeout=ESPERA_MS)


def test_da_placa_achada_a_captura_aberta_na_analise(janela, qtbot):
    area, conexao, saude = janela.aquisicao, janela.conexao_da_placa, janela.saude_da_placa

    # 1. A Aquisição, pelo seletor da barra superior: o simulador aparece na lista sozinho.
    janela.barra.areas.botao(AREA_AQUISICAO).click()
    assert janela.area_atual == AREA_AQUISICAO
    qtbot.waitUntil(lambda: [p.estado for p in conexao.placas] == ["simulador"], timeout=ESPERA_MS)

    # 2. Um clique nele conecta (com a chave: o simulador não aceita senha pelo SSH).
    lista = area.lateral.lista
    clicar(lista, lista.model().index(0, 0))
    esperar_a_placa(qtbot, janela, "normal")
    assert conexao.autenticada_com == "chave"
    assert any(e.descricao == "conectado, com a chave do aplicativo" for e in conexao.registro.entradas)

    # 3. A visão geral: a placa pronta, com sinal, e o relógio certo.
    v = area.visao_geral
    assert area.secoes.currentWidget() is area.paginas["visao_geral"] and v.cenario.isVisible()
    assert v.aquisicao.valor.text() == "Com sinal" and v.relogio.valor.text().endswith(" s")
    assert "firmware v0.8.0-simulador (o deste aplicativo)" in v.subtitulo.text()

    # 4. O diagnóstico: nada a corrigir.
    secao(area, "diagnostico")
    niveis = {k: cartao.item.nivel for k, cartao in area.diagnostico.cartoes.items()}
    assert not {k: n for k, n in niveis.items() if n in ("aviso", "erro")}
    assert "Pronta para capturar" in area.diagnostico.subtitulo.text()

    # 5. Na visão geral, o cenário do relógio errado (a lista do "Cenário"), e o "Acertar…" dele.
    secao(area, "visao_geral")
    v.cenario.setCurrentIndex(v.cenario.findData("relogio_errado"))
    v.cenario.activated.emit(v.cenario.currentIndex())
    esperar_a_placa(qtbot, janela, "relogio_errado")
    assert v.relogio.valor.text() == "−2 dias e 5 h" and preferencias.cenario_do_simulador() == "relogio_errado"
    v.linhas["relogio"].acao.click()
    dialogo = area.dialogo_de_correcao
    qtbot.waitUntil(dialogo.isVisible, timeout=ESPERA_MS)
    assert not dialogo.caixa_da_senha.isVisible()                    # o sudo da placa simulada: a senha da imagem
    dialogo.confirmar.click()
    qtbot.waitUntil(lambda: not dialogo.isVisible(), timeout=ESPERA_MS)
    qtbot.waitUntil(lambda: saude.relogio_acertado is not None and not saude.conferindo, timeout=ESPERA_MS)
    assert abs(saude.saude.relogio.diferenca_s()) < 1.0
    assert "acertado pelo computador às " in v.relogio.detalhe.text()

    # 6. Os arquivos: a captura de rede mais recente, transferida e conferida pelo CRC das amostras.
    secao(area, "arquivos")
    arquivos = area.arquivos
    rede = next(c for c in arquivos._capturas if c.arquivo.startswith("rede_bloco_"))
    linha = arquivos._capturas.index(rede)
    clicar(arquivos.tabela, arquivos.tabela.model().index(linha, 0))
    assert arquivos.selecionadas() == [rede] and arquivos.transferir.isEnabled()
    arquivos.transferir.click()
    t = area.transferencias
    qtbot.waitUntil(lambda: (i := t.item_de(rede)) is not None and i.estado in ("conferida", "corrompida", "falhou"),
                    timeout=ESPERA_MS)
    item = t.item_de(rede)
    assert (item.estado, item.como) == ("conferida", "crc32")
    original = conexao._sessao.simulador.home / "firmware" / rede.arquivo
    assert item.local.read_bytes() == original.read_bytes()
    assert item.local.parent == preferencias.pasta_da_sessao()

    # 7. "Abrir na Análise": a janela vai para a Análise, com a captura no projeto.
    clicar(arquivos.tabela, arquivos.tabela.model().index(arquivos._capturas.index(rede), 0))
    assert arquivos.abrir.isEnabled()
    arquivos.abrir.click()
    assert janela.area_atual == AREA_ANALISE and janela.barra.areas.escolhida == AREA_ANALISE
    (fonte,) = janela.projeto.fontes
    assert fonte.caminho == item.local
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=ESPERA_MS)

    # 8. A tensão plotada (o duplo clique na árvore) e o espectro da captura inteira (Ctrl+E).
    painel = janela.painel_projeto
    indice = painel.proxy.mapFromSource(painel.modelo.indice_do_canal(fonte, TENSAO))
    painel.arvore.scrollTo(indice)
    ponto = painel.arvore.visualRect(indice).center()
    QTest.mouseClick(painel.arvore.viewport(), Qt.MouseButton.LeftButton, pos=ponto)
    QTest.mouseDClick(painel.arvore.viewport(), Qt.MouseButton.LeftButton, pos=ponto)
    (traco,) = janela.vista_ativa().tracos
    assert traco.receita.canal == TENSAO
    janela.acoes["espectro"].trigger()
    espectro = janela.area.widget_da_vista(janela.vista_ativa())
    espectro.trecho.botao(2).click()
    qtbot.waitUntil(lambda: bool(espectro.resultados) and espectro.opcoes_calculadas == espectro.opcoes,
                    timeout=ESPERA_MS)
    e = espectro.resultados[0].espectro
    f, db = np.asarray(e.freqs_hz), np.asarray(e.db)

    def pico(f0, largura):
        return db[(f > f0 - largura) & (f < f0 + largura)].max()

    piso = np.median(db[(f > 50_000) & (f < 60_000)])
    assert abs(f[np.argmax(db)] - 60.0) < 1.0                        # a rede é o maior pico
    for f0, largura in ((16_000, 300), (40_000, 1_600), (72_000, 300)):
        assert pico(f0, largura) - piso > 25, f0                     # os supraharmônicos da placa simulada
