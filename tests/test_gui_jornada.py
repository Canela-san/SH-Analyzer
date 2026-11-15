"""A jornada do pesquisador, de ponta a ponta (F2.11: o "pronto quando" da Fase 2, docs/gui-plan.md): pelos gestos
do usuário, abrir a captura (Ctrl+O), plotar a corrente (o duplo clique na árvore), ligar a correção de sonda no
inspetor, abrir o espectro (Ctrl+E) da captura inteira, e os números batem com os do ``adc_tool --fft`` (pelo
``.mat``, a precisão inteira). Depois, o projeto salvo e reaberto dá o mesmo espectro. Sem tela."""

import json

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import FREQS_CAL, captura_producao, planta_h  # noqa: E402
from dialogos_falsos import DialogosFalsos  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.dados.cadeia import Cadeia, CorrecaoSonda  # noqa: E402
from sh_analyzer_gui.janela import JanelaPrincipal  # noqa: E402
from supraharmonicos import api  # noqa: E402
from supraharmonicos.cli_adc_tool import main  # noqa: E402

TONS_HZ = (9_000.0, 20_000.0, 40_000.0)          # os tons da captura de produção acima de 2 kHz


@pytest.fixture
def campo(tmp_path):
    """Uma captura de campo (a tensão e a corrente pela sonda de 1 polo em 30 kHz) e a pasta com o perfil da sonda."""
    sondas = tmp_path / "sondas"
    sondas.mkdir()
    perfil = {"id": "sonda_teste", "tipo": "resposta_frequencia",
              "pontos": [{"freq_hz": float(f), "ganho": float(planta_h(f))} for f in FREQS_CAL]}
    (sondas / "sonda_teste.json").write_text(json.dumps(perfil), encoding="utf-8")
    return captura_producao(tmp_path / "campo.bin", dur_s=0.5), sondas


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


def esperar_o_espectro(qtbot, espectro, cadeia):
    qtbot.waitUntil(lambda: bool(espectro.resultados) and espectro.opcoes_calculadas == espectro.opcoes
                    and espectro.resultados[0].trecho.cadeia == cadeia, timeout=20_000)
    return espectro.resultados[0]


def test_da_captura_ao_espectro_corrigido_pela_sonda_com_os_numeros_da_cli(janela, qtbot, campo, tmp_path):
    caminho, sondas = campo
    preferencias.mudar_pasta("sondas", sondas)                          # as configurações: a pasta das sondas

    # 1. Ctrl+O.
    janela.controle.dialogos = DialogosFalsos([caminho])
    janela.acoes["abrir"].trigger()
    (fonte,) = janela.projeto.fontes
    assert fonte.canal(1).perfil.id == "sonda_teste"                   # a sonda registrada achou o perfil
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=10_000)

    # 2. O duplo clique na corrente, na árvore do projeto.
    painel = janela.painel_projeto
    indice = painel.proxy.mapFromSource(painel.modelo.indice_do_canal(fonte, 1))
    painel.arvore.scrollTo(indice)
    ponto = painel.arvore.visualRect(indice).center()
    QTest.mouseClick(painel.arvore.viewport(), Qt.MouseButton.LeftButton, pos=ponto)    # o primeiro clique...
    QTest.mouseDClick(painel.arvore.viewport(), Qt.MouseButton.LeftButton, pos=ponto)   # ... e o segundo
    vista = janela.vista_ativa()
    (traco,) = vista.tracos
    assert traco.receita.canal == 1

    # 3. No inspetor do traço, "Adicionar etapa: correção de sonda" (o automático: o perfil que a captura registra).
    janela.selecao.definir([traco])
    acoes = janela.inspetor.do_traco.processamento.acoes
    next(a for a in acoes if a.data() == "correcao_sonda").trigger()
    cadeia = Cadeia((CorrecaoSonda(),))
    assert traco.receita.cadeia == cadeia
    assert janela.projeto.pilha.undoText().startswith("Adicionar")

    # 4. Ctrl+E e, na barra do espectro, a captura inteira.
    janela.acoes["espectro"].trigger()
    espectro = janela.area.widget_da_vista(janela.vista_ativa())
    espectro.trecho.botao(2).click()
    r = esperar_o_espectro(qtbot, espectro, cadeia)
    n = len(fonte.canal(1).amostras)
    assert (r.trecho.inicio, r.trecho.fim) == (0, n) and "sonda" in espectro.chips[traco].resumo

    # 5. Os números da CLI: o adc_tool --fft, que corrige a corrente pela mesma sonda.
    saida = tmp_path / "cli.mat"
    assert main([str(caminho), "--sondas-dir", str(sondas), "--fft", "--sem-grafico",
                 "--exportar-mat", str(saida)]) in (0, None)
    from scipy.io import loadmat
    cli = loadmat(saida, squeeze_me=True, struct_as_record=False)["sh"].canal1.fft
    e = r.espectro
    assert (e.f0_hz, e.n_ciclos, e.n_amostras, e.inicio_local) == (cli.f0_hz, cli.n_ciclos, cli.amostras,
                                                                   cli.inicio_local)
    np.testing.assert_allclose(e.freqs_hz, cli.f, rtol=1e-12, atol=0)
    np.testing.assert_allclose(e.db, cli.db, rtol=0, atol=1e-7)

    # O espectro está de fato corrigido: em cada tom, acima do espectro sem a sonda o que a sonda tira dele (o polo
    # em 30 kHz: 0,4 dB em 9 kHz, 4,4 dB em 40 kHz). No mesmo bin, a diferença não depende do bin cair no tom.
    cru = api.espectro(api.sinal_do_canal(fonte.fonte.captura, 1), fonte.canal(1).taxa_hz,
                       api.ParametrosEspectro("fft"))
    for f in TONS_HZ:
        assert e.nivel_em(f) - cru.nivel_em(f) == pytest.approx(-20 * np.log10(planta_h(f)), abs=0.05), f

    # 6. Salvo e reaberto, o projeto dá o mesmo espectro.
    assert janela.controle.salvar_como(tmp_path / "jornada.shproj")
    janela.controle.novo()
    assert janela.controle.abrir(tmp_path / "jornada.shproj")
    reaberta = next(v for v in janela.projeto.vistas if v.tipo == "espectro")
    janela.area.ativar_vista(reaberta)
    de_novo = esperar_o_espectro(qtbot, janela.area.widget_da_vista(reaberta), cadeia)
    np.testing.assert_array_equal(de_novo.espectro.db, e.db)
