"""Os portões de desempenho da interface (docs/gui-plan.md, seção 6.7), medidos nesta máquina.

Ficam fora do conjunto padrão: medem tempo, e o tempo depende da máquina e da carga. Rode com::

    uv run --extra gui-dev pytest --desempenho -n 0 tests/test_gui_desempenho.py

Os limites são os do plano, com folga para um notebook comum; uma piora grande aparece aqui antes de aparecer na tela.
"""

import time

import numpy as np
import pytest
from sh_analyzer_gui.dados.consulta import consultar
from sh_analyzer_gui.dados.piramide import construir

pytestmark = pytest.mark.desempenho

N = 100_000_000          # 250 s de um canal a 400 kS/s, 200 MB em int16


@pytest.fixture(scope="module")
def sinal_grande(tmp_path_factory):
    """100 M amostras int16 num arquivo (memmap), como uma captura: 60 Hz, supraharmônicos e ruído."""
    caminho = tmp_path_factory.mktemp("desempenho") / "sinal.i16"
    rng = np.random.default_rng(1)
    with open(caminho, "wb") as f:
        for i in range(0, N, 10_000_000):
            t = np.arange(i, i + 10_000_000) / 400_000
            fase = np.sin(2 * np.pi * 60 * t)
            y = 20000 * fase + 600 * np.sin(2 * np.pi * 20_000 * t) * (fase < 0) + rng.normal(0, 40, len(t))
            f.write(y.astype(np.int16).tobytes())
    return np.memmap(caminho, dtype=np.int16, mode="r")


def test_g3_piramide_a_200_milhoes_de_amostras_por_segundo(sinal_grande):
    """G3: a pirâmide de uma captura de 1 h (1,44 bilhão de amostras) em < 8 s pede >= 200 M amostras/s."""
    construir(sinal_grande[:10_000_000])            # aquece o cache de páginas
    t = time.perf_counter()
    (p,) = construir(sinal_grande)
    taxa = N / (time.perf_counter() - t)
    assert p.n_amostras == N
    assert taxa >= 200e6, f"{taxa / 1e6:.0f} M amostras/s"


def test_consulta_em_menos_de_1_ms_em_qualquer_zoom(sinal_grande):
    """A consulta de 1 600 colunas, da captura inteira até poucas amostras por coluna, cabe com folga num quadro."""
    (p,) = construir(sinal_grande)
    for largura in (N, 10_000_000, 1_000_000, 300_000, 5_000):
        inicio = (N - largura) // 2
        consultar(p, sinal_grande, inicio, inicio + largura, 1600)        # aquece
        tempos = []
        for _ in range(20):
            t = time.perf_counter()
            consultar(p, sinal_grande, inicio, inicio + largura, 1600)
            tempos.append(time.perf_counter() - t)
        mediana = sorted(tempos)[len(tempos) // 2]
        assert mediana < 1e-3, f"{largura:,} amostras: {mediana * 1e3:.2f} ms"


def test_g1_duas_faixas_sem_tela(request, tmp_path_factory, monkeypatch):
    """G1, a parte que roda sem tela: 2 faixas de uma captura de 5 min (2 canais a 200 kS/s), o percurso de zoom e
    pan do protótipo, p95 <= 16 ms por quadro. Com 8 faixas e numa tela de verdade, rode o protótipo:
    ``python -m sh_analyzer_gui.prototipos.navegar --sintetico 60 --canais 8 --medir``."""
    pytest.importorskip("PySide6")
    pytest.importorskip("pytestqt")
    import tempfile

    import pyqtgraph as pg
    from PySide6.QtWidgets import QApplication
    from sh_analyzer_gui.prototipos import navegar

    qtbot = request.getfixturevalue("qtbot")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path_factory.mktemp("g1")))
    fonte = navegar.gerar_sintetico(5, 2)
    piramides = construir(fonte.amostras, 2)
    layout = pg.GraphicsLayoutWidget()
    layout.resize(1400, 790)
    qtbot.addWidget(layout)
    layout.show()
    qtbot.waitExposed(layout)
    tracos = navegar.montar_faixas(layout, fonte, piramides)
    qtbot.wait(50)
    canal = fonte.canais[0]
    navegar.percorrer_zoom(QApplication.instance(), layout, tracos[0], len(canal.amostras), canal.taxa_hz)  # aquece
    mediana, p95 = navegar.resumo_dos_quadros(
        navegar.percorrer_zoom(QApplication.instance(), layout, tracos[0], len(canal.amostras), canal.taxa_hz))
    assert p95 <= 0.016, f"mediana {mediana * 1e3:.1f} ms, p95 {p95 * 1e3:.1f} ms"


def test_g1_oito_faixas_na_vista_de_tempo(request, tmp_path, monkeypatch):
    """G1 na vista de verdade (F1.5): 8 traços em 8 faixas, com o eixo, a grade e o minimapa do tema, sobre uma
    captura de 1 min (2 canais a 200 kS/s, plotados 4 vezes cada). O percurso de zoom e pan do protótipo, p95 <= 16
    ms por quadro. Sem tela, o número é só uma referência: o G1 vale na tela do usuário."""
    pytest.importorskip("PySide6")
    pytest.importorskip("pytestqt")
    from capturas_sinteticas import escrever_bin
    from dialogos_falsos import DialogosFalsos
    from PySide6.QtWidgets import QApplication
    from sh_analyzer_gui.app import criar_aplicacao
    from sh_analyzer_gui.janela import JanelaPrincipal
    from sh_analyzer_gui.modelo.comandos import MudarTracos
    from sh_analyzer_gui.prototipos import navegar

    qtbot = request.getfixturevalue("qtbot")
    monkeypatch.setenv("SH_ANALYZER_CONFIG", str(tmp_path / "config"))
    n = 60 * 200_000
    t = np.arange(n) / 200_000
    caminho = escrever_bin(tmp_path / "um_minuto.bin", [np.sin(2 * np.pi * 60 * t), np.cos(2 * np.pi * 60 * t)],
                           versao=9)
    criar_aplicacao([], tema="escuro")
    janela = JanelaPrincipal()
    janela.controle.dialogos = DialogosFalsos()
    janela.resize(1600, 1000)
    janela.show()
    qtbot.waitExposed(janela)
    (fonte,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=60_000)
    for i in range(8):
        traco = janela.area.plotar_canal(fonte, i % 2)
        janela.projeto.pilha.push(MudarTracos([traco], faixa=i))
    vista = janela.area.widget_da_vista(janela.vista_ativa())
    assert len(vista.faixas) == 8
    qtbot.wait(50)
    item = next(iter(vista.itens.values()))
    canal = fonte.canal(0)
    app = QApplication.instance()
    navegar.percorrer_zoom(app, vista.grafico, item, len(canal.amostras), canal.taxa_hz)     # aquece
    mediana, p95 = navegar.resumo_dos_quadros(
        navegar.percorrer_zoom(app, vista.grafico, item, len(canal.amostras), canal.taxa_hz))
    janela.projeto.pilha.setClean()
    janela.close()
    assert p95 <= 0.016, f"mediana {mediana * 1e3:.1f} ms, p95 {p95 * 1e3:.1f} ms"


def test_g1_oito_faixas_com_a_cadeia_durante_e_depois_das_materializacoes(request, tmp_path, monkeypatch):
    """G1 com a cadeia ligada (F2.11): os 8 traços do G1 com a correção de sonda e um passa-altas de 2 kHz. O percurso
    enquanto as materializações rodam (uma de cada vez; os traços do outro canal, das prévias) e depois delas, das
    pirâmides dos traços transformados: p95 <= 16 ms nos dois. Antes da fila das pesadas, as duas materializações e
    as medidas da janela rodavam juntas, e o percurso dava p95 de 22 a 33 ms nesta máquina."""
    pytest.importorskip("PySide6")
    pytest.importorskip("pytestqt")
    from capturas_sinteticas import escrever_bin, escrever_perfil_sonda
    from dialogos_falsos import DialogosFalsos
    from PySide6.QtWidgets import QApplication
    from sh_analyzer_gui import preferencias
    from sh_analyzer_gui.app import criar_aplicacao
    from sh_analyzer_gui.janela import JanelaPrincipal
    from sh_analyzer_gui.modelo.comandos import MudarTracos
    from sh_analyzer_gui.prototipos import navegar
    from sh_analyzer_gui.prototipos.medir_vista import cadeia_do_g1

    qtbot = request.getfixturevalue("qtbot")
    monkeypatch.setenv("SH_ANALYZER_CONFIG", str(tmp_path / "config"))
    n = 60 * 200_000
    t = np.arange(n) / 200_000
    caminho = escrever_bin(tmp_path / "um_minuto.bin", [np.sin(2 * np.pi * 60 * t), np.cos(2 * np.pi * 60 * t)],
                           grandezas=(0, 1), sondas=("sonda_teste", "sonda_teste"), versao=9)
    preferencias.mudar_pasta("sondas", escrever_perfil_sonda(tmp_path / "sondas").parent)
    criar_aplicacao([], tema="escuro")
    janela = JanelaPrincipal()
    janela.controle.dialogos = DialogosFalsos()
    janela.resize(1600, 1000)
    janela.show()
    qtbot.waitExposed(janela)
    (fonte,) = janela.controle.abrir_capturas([caminho])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=60_000)
    tracos = []
    for i in range(8):
        tracos.append(janela.area.plotar_canal(fonte, i % 2))
        janela.projeto.pilha.push(MudarTracos([tracos[-1]], faixa=i))
    vista = janela.area.widget_da_vista(janela.vista_ativa())
    qtbot.wait(300)
    janela.projeto.pilha.push(MudarTracos(tracos, cadeia=cadeia_do_g1()))
    estados = {vista.materializacoes.estado_de(t) for t in tracos}
    assert len(estados) == 2                                          # uma por canal
    qtbot.wait(500)
    item = next(iter(vista.itens.values()))
    canal = fonte.canal(0)
    app = QApplication.instance()
    assert any(e.pronta is None for e in estados)                    # o percurso pega as materializações rodando
    durante = navegar.resumo_dos_quadros(
        navegar.percorrer_zoom(app, vista.grafico, item, len(canal.amostras), canal.taxa_hz))
    qtbot.waitUntil(lambda: all(e.pronta is not None for e in estados), timeout=120_000)
    navegar.percorrer_zoom(app, vista.grafico, item, len(canal.amostras), canal.taxa_hz)     # aquece
    depois = navegar.resumo_dos_quadros(
        navegar.percorrer_zoom(app, vista.grafico, item, len(canal.amostras), canal.taxa_hz))
    janela.projeto.pilha.setClean()
    janela.close()
    texto = ", ".join(f"{nome}: mediana {m * 1e3:.1f} ms, p95 {p * 1e3:.1f} ms"
                      for nome, (m, p) in (("durante", durante), ("depois", depois)))
    assert durante[1] <= 0.016 and depois[1] <= 0.016, texto


def test_o_espectro_de_milhoes_de_bins_arrasta_a_60_quadros(qapp, config_limpa, tmp_path):
    """A FFT da janela visível de 30 s a 200 kS/s tem 3 M bins: arrastar o gráfico, dar zoom e mover o cursor de
    frequência ficam abaixo de 16 ms por quadro (antes da pirâmide no espectro, ~320 ms: o aplicativo travava)."""
    from capturas_sinteticas import escrever_bin
    from dialogos_falsos import DialogosFalsos
    from sh_analyzer_gui.app import criar_aplicacao
    from sh_analyzer_gui.janela import JanelaPrincipal

    fs, n = 200_000.0, 6_000_000
    t = np.arange(n) / fs
    caminho = escrever_bin(tmp_path / "longa.bin", [3 * np.sin(2 * np.pi * 50 * t), 0 * t], versao=9)
    del t
    criar_aplicacao([])
    j = JanelaPrincipal()
    j.controle.dialogos = DialogosFalsos()
    j.resize(1600, 1000)
    j.show()

    def esperar(condicao, limite=60.0):
        inicio = time.perf_counter()
        while not condicao():
            qapp.processEvents()
            time.sleep(0.005)
            assert time.perf_counter() - inicio < limite

    try:
        (fonte,) = j.controle.abrir_capturas([caminho])
        esperar(lambda: fonte.piramides is not None)
        j.area.plotar_canal(fonte, 0)
        j.acoes["espectro"].trigger()
        w = j.area.widget_da_vista(j.vista_ativa())
        assert w.opcoes.metodo == "fft"                              # o método padrão
        esperar(lambda: w.opcoes_calculadas == w.opcoes and w.resultados and w.resultados[0].desenho is not None)
        assert len(w.resultados[0].desenho.niveis) > 2_000_000
        w.acao_cursores.setChecked(True)
        w.acao_valores.setChecked(True)
        vb = w.grafico.getViewBox()
        x0, x1 = vb.viewRange()[0]
        for nome, mexer in (("pan", lambda k: vb.setXRange(x0 + 100 * k, x1 + 100 * k, padding=0)),
                            ("zoom", lambda k: vb.setXRange(9_000 + k, 10_000 + k, padding=0)),
                            ("cursor", lambda k: w.cursores.linhas[0][0].setValue(5_000 + 1_000 * k))):
            quadros = []
            for k in range(30):
                inicio = time.perf_counter()
                mexer(k)
                qapp.processEvents()
                w.grafico.viewport().repaint()
                quadros.append(time.perf_counter() - inicio)
            assert np.median(quadros) < 0.016, (nome, np.median(quadros))
    finally:
        j.projeto.pilha.setClean()
        j.close()
        j.deleteLater()


BLOCOS_DA_CAPTURA_LONGA = 60
"""157 s da placa simulada (os dois canais a 200 kS/s, 31,5 M amostras cada): a rede com os supraharmônicos."""


@pytest.fixture(scope="module")
def captura_longa(tmp_path_factory):
    from sh_placa.capturas_simuladas import AMOSTRAS_POR_BLOCO_DO_FIRMWARE, Sistema, gravar_captura

    caminho = tmp_path_factory.mktemp("longa") / "placa_simulada.bin"
    # o bloco do firmware: o conftest diminui o das capturas simuladas para os outros testes
    return gravar_captura(caminho, inicio=time.time(), blocos=BLOCOS_DA_CAPTURA_LONGA, sistema=Sistema("", "", ""),
                          amostras_por_bloco=AMOSTRAS_POR_BLOCO_DO_FIRMWARE)


def _trecho(captura, canal):
    from sh_analyzer_gui.dados.cadeia import Cadeia
    from sh_analyzer_gui.dados.espectros import TrechoDoTraco
    from sh_analyzer_gui.dados.materializacao import contexto_do_canal

    c = captura.canal(canal)
    return TrechoDoTraco(captura, canal, Cadeia(), contexto_do_canal(c, captura=captura), 0, len(c.amostras))


def test_f7_as_analises_numa_captura_longa(request, captura_longa):
    """As contas da Fase 7 (F7.12) na captura inteira, em pedaços: os índices de qualidade e os eventos acima de
    4 M amostras/s (1 h de um canal a 200 kS/s em 3 min; medidos 7,4 e 6,5 M/s em 25/11/2026: 85 % do tempo é o
    cruzamento da fundamental do motor, a FFT de cada pedaço), a transferência acima de 12 M/s (23 M/s), o
    Instrumento com 5000 ciclos de dois traços (o disparo, o ciclo médio e a persistência) em menos de 5 s (2,3 s) e
    o disparo com o rejeitar AF em menos de 1,5 s (0,4 s)."""
    from sh_analyzer_gui.dados import instrumento as ins
    from sh_analyzer_gui.dados import qualidade as q
    from supraharmonicos import api

    captura = api.abrir_captura(captura_longa)
    v, i = _trecho(captura, 1), _trecho(captura, 0)
    n = v.n_amostras
    medidas = {}

    def medir(nome, conta):
        inicio = time.perf_counter()
        resultado = conta()
        medidas[nome] = time.perf_counter() - inicio
        return resultado

    indices = medir("indices", lambda: q.indices(v))
    medir("eventos", lambda: q.eventos(v, indices_prontos=indices))
    medir("transferencia", lambda: q.transferencia_do_trecho(i, v, 100.0))
    antes, depois = 0.0033, 0.03

    def instrumento():
        d = ins.disparos_do_trecho(v, 0.0, "subindo", 0.5, antes, depois)
        for t in (v, i):
            ins.ciclo_medio(t, d, antes, depois)
            ins.densidade(t, d, antes, depois, (-20.0, 20.0), colunas=500, linhas=256)
        return d

    assert medir("instrumento", instrumento).n == ins.MAXIMO_DE_CICLOS
    medir("rejeitar_af", lambda: ins.disparos_do_trecho(v, 0.0, "subindo", 0.5, antes, depois,
                                                         rejeitar_af_hz=ins.CORTE_DO_REJEITAR_AF_HZ))
    texto = ", ".join(f"{k}: {s:.2f} s" for k, s in medidas.items())
    request.node.add_report_section("call", "tempos", f"{n} amostras por canal; {texto}")      # pytest -rP mostra
    assert indices.n_janelas > 700, texto
    assert n / medidas["indices"] > 4e6 and n / medidas["eventos"] > 4e6, texto
    assert n / medidas["transferencia"] > 12e6, texto
    assert medidas["instrumento"] < 5.0 and medidas["rejeitar_af"] < 1.5, texto


def test_f7_a_tela_leve_durante_a_qualidade(request, captura_longa, monkeypatch, tmp_path):
    """A vista de tempo (a tensão e a corrente da captura longa) navegada enquanto os índices de qualidade da
    captura inteira rodam em segundo plano, como a vista de qualidade os pede: p95 <= 16 ms por quadro (sem tela,
    uma referência; o G1 vale na tela do usuário)."""
    pytest.importorskip("PySide6")
    pytest.importorskip("pytestqt")
    from dialogos_falsos import DialogosFalsos
    from PySide6.QtWidgets import QApplication
    from sh_analyzer_gui.app import criar_aplicacao
    from sh_analyzer_gui.dados import qualidade as q
    from sh_analyzer_gui.janela import JanelaPrincipal
    from sh_analyzer_gui.prototipos import navegar
    from supraharmonicos import api

    qtbot = request.getfixturevalue("qtbot")
    monkeypatch.setenv("SH_ANALYZER_CONFIG", str(tmp_path / "config"))
    criar_aplicacao([], tema="escuro")
    janela = JanelaPrincipal()
    janela.controle.dialogos = DialogosFalsos()
    janela.resize(1600, 1000)
    janela.show()
    qtbot.waitExposed(janela)
    (fonte,) = janela.controle.abrir_capturas([captura_longa])
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=120_000)
    janela.area.plotar_canal(fonte, 1)
    janela.area.plotar_canal(fonte, 0, janela.vista_ativa())
    vista = janela.area.widget_da_vista(janela.vista_ativa())
    qtbot.wait(300)
    item = next(iter(vista.itens.values()))
    canal = fonte.canal(1)
    app = QApplication.instance()
    navegar.percorrer_zoom(app, vista.grafico, item, len(canal.amostras), canal.taxa_hz)     # aquece
    captura = api.abrir_captura(captura_longa)
    tarefa = janela.tarefas.iniciar("Qualidade", lambda progresso, cancelado: q.indices(
        _trecho(captura, 1), progresso=progresso, cancelado=cancelado))
    qtbot.wait(200)
    durante = navegar.resumo_dos_quadros(
        navegar.percorrer_zoom(app, vista.grafico, item, len(canal.amostras), canal.taxa_hz))
    rodando = tarefa.ativa
    qtbot.waitUntil(lambda: not tarefa.ativa, timeout=120_000)
    janela.projeto.pilha.setClean()
    janela.close()
    janela.deleteLater()
    texto = f"durante: mediana {durante[0] * 1e3:.1f} ms, p95 {durante[1] * 1e3:.1f} ms"
    request.node.add_report_section("call", "quadros", texto)          # pytest -rP mostra
    assert rodando, "a conta terminou antes do percurso: a medida não vale"
    assert durante[1] <= 0.016, texto
