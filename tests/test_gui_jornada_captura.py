"""A jornada da captura, de ponta a ponta (F4.7: o "pronto quando" da Fase 4, docs/gui-plan.md): na janela e pelos
gestos do usuário, com o simulador servido por SSH neste computador. Conectar com um clique, ir à Capturar pela
coluna da esquerda, pôr um pedido no formulário e digitar o título, conferir antes, capturar direto no computador
com o ao vivo no cockpit, parar, ver a captura no projeto e abri-la na Análise com o canal plotado; depois capturar
no cartão, derrubar o cabo no meio, ver o acompanhamento voltar e a cópia conferida entrar no projeto; e o caderno
da sessão com tudo, na ordem. Sem placa e sem tela."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("asyncssh")

import test_gui_jornada_aquisicao as jornada  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.janela import AREA_ANALISE, AREA_AQUISICAO  # noqa: E402
from sh_placa.pedido import Canal, PedidoDeCaptura  # noqa: E402
from supraharmonicos import api  # noqa: E402
from test_gui_jornada_aquisicao import clicar, esperar_a_placa, secao  # noqa: E402

janela = jornada.janela              # a janela da jornada da F3.10 (a fixture): o simulador, o cofre falso

ESPERA_MS = 40_000
REDE = (Canal(0, "corrente", ganho=19.65), Canal(1, ganho=19.357))
TENSAO = 1


def test_do_pedido_a_analise_com_o_parar_e_a_queda_no_cartao(janela, qtbot):
    area, conexao = janela.aquisicao, janela.conexao_da_placa

    # 1. A Aquisição e o simulador, conectado com um clique.
    janela.barra.areas.botao(AREA_AQUISICAO).click()
    qtbot.waitUntil(lambda: [p.estado for p in conexao.placas] == ["simulador"], timeout=ESPERA_MS)
    lista = area.lateral.lista
    clicar(lista, lista.model().index(0, 0))
    esperar_a_placa(qtbot, janela, "normal")

    # 2. A Capturar: o pedido (um modelo posto no formulário) e o título digitado; a conferência antes.
    secao(area, "capturar")
    s, c, f = area.capturar, area.captura, area.capturar.formulario
    f.definir_pedido(PedidoDeCaptura(REDE, 400_000, blocos=0))                     # até o Parar
    f.titulo.clear()
    QTest.keyClicks(f.titulo, "Rede de casa")
    assert f.pedido.titulo == "Rede de casa" and f.destino.escolhida == 0         # direto no computador
    qtbot.mouseClick(s.conferir, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: area.conferencia.estado in ("feita", "falhou"), timeout=ESPERA_MS)
    assert area.conferencia.estado == "feita", area.conferencia.erro

    # 3. Capturar: o ao vivo no cockpit; o Parar fecha no último bloco; a captura entra no projeto.
    qtbot.mouseClick(s.capturar, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: c.progresso is not None and c.progresso.blocos >= 2 and s.ao_vivo.quadro is not None,
                    timeout=ESPERA_MS)
    assert s.paginas.currentWidget() is s.cockpit and [k.numero for k in s.ao_vivo.quadro.canais] == [0, 1]
    qtbot.mouseClick(s.cockpit.barra.parar, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: c.estado == "feita", timeout=ESPERA_MS)
    primeira, fim = c.arquivo, c.fim
    assert fim.parada_pedida and fim.crc_confere and not fim.caiu
    assert primeira.parent == preferencias.pasta_da_sessao() and primeira.name.startswith("rede_de_casa_")
    cabecalho = api.abrir_captura(primeira).cabecalho
    assert cabecalho.blocos_gravados == fim.blocos >= 2                         # o que o cockpit contou
    assert [x.caminho for x in janela.projeto.fontes] == [primeira]

    # 4. "Abrir na Análise": a janela vai para a Análise, e a tensão plotada pela árvore do projeto.
    qtbot.mouseClick(s.cockpit.fim.abrir, Qt.MouseButton.LeftButton)
    assert janela.area_atual == AREA_ANALISE
    (fonte,) = janela.projeto.fontes
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=ESPERA_MS)
    painel = janela.painel_projeto
    indice = painel.proxy.mapFromSource(painel.modelo.indice_do_canal(fonte, TENSAO))
    painel.arvore.scrollTo(indice)
    ponto = painel.arvore.visualRect(indice).center()
    QTest.mouseClick(painel.arvore.viewport(), Qt.MouseButton.LeftButton, pos=ponto)
    QTest.mouseDClick(painel.arvore.viewport(), Qt.MouseButton.LeftButton, pos=ponto)
    (traco,) = janela.vista_ativa().tracos
    assert traco.receita.canal == TENSAO

    # 5. De volta à Aquisição: uma captura nova, no cartão, com o cabo que cai no meio.
    janela.barra.areas.botao(AREA_AQUISICAO).click()
    assert area.secao == "capturar" and s.cockpit.fim.isVisible()
    qtbot.mouseClick(s.cockpit.fim.nova, Qt.MouseButton.LeftButton)
    f.definir_pedido(PedidoDeCaptura(REDE[1:], 400_000, blocos=3, titulo="No cartão"))
    f.destino.botao(1).click()
    assert f.pedido.destino == "cartao"
    qtbot.mouseClick(s.capturar, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: c.progresso is not None and c.progresso.blocos >= 1, timeout=ESPERA_MS)
    assert c.no_cartao and s.cockpit.no_cartao.isVisible()
    assert conexao.servico.laco.agendar(conexao._sessao.simulador.derrubar)
    qtbot.waitUntil(lambda: c.estado == "feita", timeout=ESPERA_MS)
    assert c.retomada and (c.fim.destino, c.fim.blocos, c.fim.motivo) == ("cartao", 3, "ok")
    qtbot.waitUntil(lambda: len(janela.projeto.fontes) == 2, timeout=ESPERA_MS)
    trazida = janela.projeto.fontes[1].caminho
    assert trazida.name == c.nome and api.abrir_captura(trazida).cabecalho.blocos_gravados == 3

    # 6. O caderno da sessão, na ordem: a conferência, a primeira captura (o começo e o fim), e a do cartão (o começo,
    # a queda, a volta, o fim e a cópia conferida).
    caderno = area.caderno
    qtbot.waitUntil(lambda: any("veio para o computador e confere" in e.texto for e in caderno.entradas),
                    timeout=ESPERA_MS)
    primeiras = [e.texto.split("\n")[0] for e in caderno.entradas]
    assert caderno.caminho == preferencias.pasta_da_sessao() / "anotacoes.md"
    ordem = ["Conferência: ", f"Captura `{primeira.name}` (“Rede de casa”) iniciada", "Captura parada em",
             f"Captura `{c.nome}` (“No cartão”) iniciada", f"A conexão caiu durante a captura `{c.nome}`",
             f"A captura `{c.nome}`, no cartão, acompanhada de novo", "Captura concluída", f"`{c.nome}` veio para"]
    achadas = [next(i for i, t in enumerate(primeiras) if t.startswith(o)) for o in ordem]
    assert achadas == sorted(achadas), primeiras
