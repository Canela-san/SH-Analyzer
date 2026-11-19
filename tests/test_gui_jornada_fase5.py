"""A jornada da Fase 5 (F5.10: o "pronto quando" da fase, docs/gui-plan.md, 16), na janela e de ponta a ponta: duas
capturas da rede com a sonda registrada, a corrente corrigida pelo perfil, a segunda captura alinhada à primeira, o
espectro ao lado do tempo na grade com os eixos ligados, uma cota de Δt entre os cursores; a figura IEEE de uma coluna
com o tempo em (a) e o espectro em (b), em PDF (a página de 88 mm, o texto que se busca, a proveniência) e no pacote
reproduzível, cujo script refaz a figura com os mesmos pixels sem o SH-Analyzer; o projeto salvo e aberto de novo com
a mesma página, a grade e o alinhamento. Sem tela."""

import json
import re
import shutil
import subprocess
import zipfile

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from capturas_sinteticas import escrever_bin  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.dados.cadeia import CorrecaoSonda  # noqa: E402
from sh_analyzer_gui.dados.exportar_figura import OpcoesDeExportacao  # noqa: E402
from sh_analyzer_gui.janela import AREA_ANALISE, AREA_FIGURAS  # noqa: E402
from test_gui_jornada_figura import ESPERA_MS, _esperar_a_pagina, _pagina, janela  # noqa: E402,F401
from test_gui_pacote import _refazer  # noqa: E402
from test_gui_perfis_de_sonda import _perfil  # noqa: E402

TAXA = 200_000.0
ATRASO = 0.4321e-3


def _rede(t):
    v = 3.0 * np.sin(2 * np.pi * 60 * t) + 0.3 * np.sin(2 * np.pi * 3000 * t)
    i = 1.0 * np.sin(2 * np.pi * 60 * t - 0.5) + 0.05 * np.sin(2 * np.pi * 9000 * t)
    return v, i


def _capturas(pasta):
    pasta.mkdir(parents=True, exist_ok=True)
    t = np.arange(40_000) / TAXA
    caminhos = []
    for nome, atraso in (("rede.bin", 0.0), ("rede_2.bin", ATRASO)):
        v, i = _rede(t - atraso)
        caminhos.append(escrever_bin(pasta / nome, [v, i], grandezas=(0, 1), sondas=("", "sonda_a"), versao=9,
                                     extensao={"ganhos": [100.0, 10.0]}))
    return caminhos


def _espectro_pronto(w) -> bool:
    """O espectro calculado para o trecho de agora (nenhuma conta esperando nem rodando)."""
    return w.tem_dados and not w._espera.isActive() and (w._tarefa is None or not w._tarefa.ativa)


def test_da_captura_a_figura_ieee_em_pdf_e_no_pacote(janela, qtbot, tmp_path):  # noqa: F811
    preferencias.mudar_pasta("sondas", tmp_path / "sondas")
    _perfil(tmp_path / "sondas", "sonda_a")
    a, b = _capturas(tmp_path / "dados")
    assert janela.controle.abrir_capturas([a, b])
    f1, f2 = janela.projeto.fontes
    for f in (f1, f2):
        qtbot.waitUntil(lambda f=f: f.piramides is not None, timeout=ESPERA_MS)
    area_a = janela.area

    # 1. A tensão das duas capturas e a corrente corrigida pela sonda registrada (o botão do inspetor).
    v1 = area_a.plotar_canal(f1, 0)
    tempo = janela.vista_ativa()
    v2 = area_a.plotar_canal(f2, 0, tempo)
    i1 = area_a.plotar_canal(f1, 1, tempo)
    janela.selecao.definir([i1])
    inspetor = janela.inspetor.do_traco
    assert inspetor.aplicar_correcao.isVisible()
    qtbot.mouseClick(inspetor.aplicar_correcao, Qt.MouseButton.LeftButton)
    assert any(isinstance(e, CorrecaoSonda) for e in i1.receita.cadeia.etapas)

    # 2. A segunda captura alinhada à primeira pela correlação cruzada (o atraso abaixo de um décimo de amostra).
    janela.selecao.definir([v2])
    qtbot.mouseClick(inspetor.alinhar, Qt.MouseButton.LeftButton)
    dialogo = area_a.dialogo_de_alinhar
    i = dialogo.referencia.findData(v1)
    dialogo.referencia.setCurrentIndex(i)
    qtbot.waitUntil(lambda: dialogo.alinhamento is not None and dialogo._tarefa is None
                    and dialogo.referencia_escolhida() is v1 and not dialogo._espera.isActive(), timeout=ESPERA_MS)
    assert abs(dialogo.alinhamento.atraso_s - ATRASO) * TAXA < 0.1
    qtbot.mouseClick(dialogo.aplicar, Qt.MouseButton.LeftButton)
    assert v2.receita.deslocamento_s == pytest.approx(-ATRASO, abs=0.1 / TAXA)

    # 3. O espectro ao lado do tempo, na grade, e três ciclos no tempo; a cota de Δt entre os cursores.
    janela.area.ativar_vista(tempo)
    espectro = area_a.abrir_espectro()
    janela.acoes["disposicao_lado_a_lado"].trigger()
    w_tempo, w_espectro = area_a.widget_da_vista(tempo), area_a.widget_da_vista(espectro)
    assert set(janela.vistas.visiveis()) == {w_tempo, w_espectro}
    qtbot.waitUntil(lambda: w_espectro.tem_dados, timeout=ESPERA_MS)
    w_tempo.mostrar_tempo(0.01, 0.06)
    w_tempo.ligar_cursores(True)
    w_tempo.cursores = [0.02, 0.02 + 1 / 60]
    caixa = w_tempo._caixa_da_faixa(v1.receita.faixa)
    (x0, x1), (y0, y1) = caixa.viewRange()
    regiao = tuple(sorted(w_tempo.cursores))
    acao = next(x for x in w_tempo.anotacoes.acoes(caixa, v1.receita.faixa, x0, y0 + 0.1 * (y1 - y0), regiao)
                if x.text().startswith("Pôr uma cota"))
    acao.trigger()
    assert [x.tipo for x in tempo.anotacoes] == ["cota"]
    qtbot.waitUntil(lambda: _espectro_pronto(w_espectro), timeout=ESPERA_MS)     # o do ciclo entre os cursores

    # 4. A figura IEEE de uma coluna: o tempo em (a), o espectro em (b), numa página só.
    area = janela.figuras
    janela.area.ativar_vista(tempo)
    _esperar_a_pagina(qtbot, area, janela.figura_da_vista_ativa)
    figura = janela.projeto.figuras[0]
    assert figura.modelo == "ieee_1" and len(figura.paineis) == 1
    props = area.propriedades
    _esperar_a_pagina(qtbot, area, lambda: qtbot.mouseClick(props.acrescentar, Qt.MouseButton.LeftButton))
    i = props.vista.findData(espectro.id)
    _esperar_a_pagina(qtbot, area, lambda: (props.vista.setCurrentIndex(i), props.vista.activated.emit(i)))
    figura = janela.projeto.figuras[0]
    assert [p.vista for p in figura.paineis] == [tempo.id, espectro.id]
    pagina = _pagina(area)

    # 5. O PDF: a página da coluna (88 mm), o texto que se busca, a proveniência das duas capturas.
    pdf, pacote = tmp_path / "figura.pdf", tmp_path / "figura.zip"
    with qtbot.waitSignal(area.exportada, timeout=ESPERA_MS):
        area.exportar(OpcoesDeExportacao("pdf", 300), pdf)
    conteudo = pdf.read_bytes()
    caixa_do_pdf = [float(x) for x in re.search(rb"/MediaBox \[ ([^\]]*) \]", conteudo).group(1).split()]
    assert caixa_do_pdf[2] - caixa_do_pdf[0] == pytest.approx(88 / 25.4 * 72, abs=0.5)
    if shutil.which("pdftotext"):
        texto = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
        assert "(a)" in texto and "(b)" in texto and "Tempo (ms)" in texto and "Frequência (kHz)" in texto
        assert "Nível (dBV)" in texto and "Δt = 16,67 ms" in texto
    if shutil.which("pdfinfo"):
        info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
        assert "rede.bin" in info and "rede_2.bin" in info

    # 6. O pacote: o script refaz a figura sem o SH-Analyzer, com os mesmos pixels.
    with qtbot.waitSignal(area.empacotada, timeout=ESPERA_MS):
        area.empacotar(OpcoesDeExportacao("pdf", 300), pacote)
    with zipfile.ZipFile(pacote) as z:
        z.extractall(tmp_path / "aberto")
        proveniencia = json.loads(next(z.read(n) for n in z.namelist() if n.endswith("proveniencia.json")))
    assert {f["crc32_amostras"] for f in proveniencia["fontes"]} == {
        f1.fonte.captura.cabecalho.crc32_amostras, f2.fonte.captura.cabecalho.crc32_amostras}
    (pasta,) = (tmp_path / "aberto").iterdir()
    resultado = _refazer(pasta)
    assert resultado.returncode == 0 and "os mesmos pixels da figura.png" in resultado.stdout, resultado.stderr

    # 7. O projeto salvo e aberto de novo: a mesma página, a grade, o alinhamento e a correção.
    caminho = tmp_path / "jornada.shproj"
    assert janela.controle.salvar_como(caminho)
    janela.mostrar_area(AREA_ANALISE)
    assert janela.controle.abrir(caminho)
    for f in janela.projeto.fontes:
        qtbot.waitUntil(lambda f=f: f.piramides is not None, timeout=ESPERA_MS)
    vistas = {v.nome: v for v in janela.projeto.vistas}
    w_tempo = janela.area.widget_da_vista(vistas[tempo.nome])
    w_espectro = janela.area.widget_da_vista(vistas[espectro.nome])
    qtbot.waitUntil(lambda: _espectro_pronto(w_espectro) and w_tempo.tem_dados, timeout=ESPERA_MS)
    assert w_tempo.janela_de_tempo() == pytest.approx((0.01, 0.06))      # a janela da vista voltou com o projeto
    assert w_tempo.cursores == pytest.approx([0.02, 0.02 + 1 / 60])       # e os cursores (o trecho do espectro)
    assert janela.area.estado_da_grade()["disposicao"] == "lado_a_lado"
    assert set(janela.area.estado_da_grade()["celulas"]) == {vistas[tempo.nome].id, vistas[espectro.nome].id}
    tracos = {t.nome: t for t in vistas[tempo.nome].tracos}
    assert tracos[v2.nome].receita.deslocamento_s == pytest.approx(v2.receita.deslocamento_s)
    assert any(isinstance(e, CorrecaoSonda) for e in tracos[i1.nome].receita.cadeia.etapas)
    area = janela.figuras
    _esperar_a_pagina(qtbot, area, lambda: janela.mostrar_area(AREA_FIGURAS))
    if area.figura is None:
        _esperar_a_pagina(qtbot, area, lambda: area.escolher_figura(janela.projeto.figuras[0].id))
    assert np.array_equal(_pagina(area), pagina)
