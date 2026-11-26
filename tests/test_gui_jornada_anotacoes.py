"""A jornada dos insets e das anotações (F5.8: o "pronto quando", docs/gui-progress.md), na janela: as quatro
anotações postas pelo clique direito na vista de tempo da Análise (o texto, a seta, a região e a cota entre os
cursores), com desfazer; a figura da vista as leva, a seção Anotações as muda (e a Análise acompanha) e a seção Inset
amplia um trecho; a figura sai igual na prévia, no PDF e no pacote reproduzível. Sem tela."""

import shutil
import subprocess
import zipfile

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from scipy import ndimage  # noqa: E402
from sh_analyzer_gui.dados.desenho_da_figura import desenhar  # noqa: E402
from sh_analyzer_gui.dados.exportar_figura import OpcoesDeExportacao  # noqa: E402
from sh_analyzer_gui.janela import AREA_ANALISE, AREA_FIGURAS  # noqa: E402
from test_gui_jornada_estilo import _escrever, _figura_com_dois_tracos, janela  # noqa: E402,F401
from test_gui_jornada_figura import ESPERA_MS, _esperar_a_pagina, _pagina  # noqa: E402


def _tinta(rgb: np.ndarray, limiar: int = 160) -> np.ndarray:
    return rgb[..., :3].min(axis=-1) < limiar


def _quase_igual(a: np.ndarray, b: np.ndarray, px: int) -> bool:
    """A tinta forte de cada uma a até ``px`` pixels de alguma tinta da outra (os rasterizadores pintam a borda das
    letras finas mais clara ou mais escura), e as duas com tinta."""
    def dentro(forte, qualquer):
        return not (forte & ~ndimage.binary_dilation(qualquer, iterations=px)).any()

    return (_tinta(a).sum() > 1000 and _tinta(b).sum() > 1000 and dentro(_tinta(a), _tinta(b, 250))
            and dentro(_tinta(b), _tinta(a, 250)))


def _acao(acoes, comeco: str):
    return next(a for a in acoes if a.text().startswith(comeco))


def test_as_quatro_anotacoes_e_o_inset_da_analise_a_figura(janela, qtbot, tmp_path):  # noqa: F811
    area = _figura_com_dois_tracos(janela, qtbot, tmp_path)
    janela.mostrar_area(AREA_ANALISE)
    vista = janela.vista_ativa()
    w = janela.area.widget_da_vista(vista)
    anotar = w.anotacoes
    caixa = w._caixa_da_faixa(vista.tracos[0].receita.faixa)
    (x0, x1), (y0, y1) = caixa.viewRange()
    pilha = janela.projeto.pilha

    # 1. O clique direito numa faixa abre o menu dela, no ponto clicado.
    pedidos = []
    anotar.menu = lambda *args: pedidos.append(args)
    grafico = w.grafico
    meio = caixa.mapViewToScene(caixa.viewRect().center())
    QTest.mouseClick(grafico.viewport(), Qt.MouseButton.RightButton, pos=grafico.mapFromScene(meio))
    ((caixa_do_menu, faixa, x, y, regiao, _onde),) = pedidos
    assert caixa_do_menu is caixa and x == pytest.approx((x0 + x1) / 2, rel=0.02) and regiao is None
    assert isinstance(_onde, QPoint)

    # 2. As quatro, pelas ações do menu (o texto e a seta perguntam o texto); a região e a cota, entre os cursores.
    w.ligar_cursores(True)
    c1, c2 = sorted(w.cursores)
    regiao = (c1, c2)
    anotar.pedir_texto = lambda _t, _r, _texto: "Pico"
    meio_y = (y0 + y1) / 2
    _acao(anotar.acoes(caixa, faixa, x0 + 0.1 * (x1 - x0), y0 + 0.8 * (y1 - y0), regiao), "Pôr um texto").trigger()
    anotar.pedir_texto = lambda _t, _r, _texto: "$V_{max}$"
    _acao(anotar.acoes(caixa, faixa, x0 + 0.6 * (x1 - x0), y0 + 0.7 * (y1 - y0), regiao), "Pôr uma seta").trigger()
    _acao(anotar.acoes(caixa, faixa, x0, meio_y, regiao), "Marcar uma região entre os cursores").trigger()
    _acao(anotar.acoes(caixa, faixa, x0, y0 + 0.15 * (y1 - y0), regiao), "Pôr uma cota de Δt").trigger()
    tipos = [a.tipo for a in vista.anotacoes]
    assert tipos == ["texto", "seta", "regiao", "cota"] and set(anotar.itens) == {a.id for a in vista.anotacoes}
    regiao_ = vista.anotacoes[2]
    assert (regiao_.x0, regiao_.x1) == pytest.approx(regiao)
    janela.acoes["desfazer"].trigger()
    assert len(vista.anotacoes) == 3 and len(anotar.itens) == 3
    janela.acoes["refazer"].trigger()
    # Perto do texto, o menu muda o texto dele ou o tira.
    texto = vista.anotacoes[0]
    acoes = anotar.acoes(caixa, faixa, texto.x0, texto.y0, regiao)
    anotar.pedir_texto = lambda _t, _r, _texto: "Pico máximo"
    _acao(acoes, "Mudar o texto de “Pico”").trigger()
    assert vista.anotacoes[0].texto == "Pico máximo" and pilha.undoText() == "Mudar o texto de uma anotação"

    # 3. A figura da vista as leva; a seção Anotações muda a cota (a Análise acompanha); o inset amplia um trecho.
    props = area.propriedades
    secao = props.secao_das_anotacoes
    _esperar_a_pagina(qtbot, area, lambda: janela.mostrar_area(AREA_FIGURAS))
    assert secao.lista.count() == 4 and secao.lista.item(3).text().startswith("Cota: Δt = ")
    secao.lista.setCurrentRow(3)
    _esperar_a_pagina(qtbot, area, lambda: _escrever(secao.texto, "meio ciclo"))
    assert vista.anotacoes[3].texto == "meio ciclo"
    camada = anotar.itens[vista.anotacoes[3].id]                   # a camada da caixa a desenha com o texto novo
    assert vista.anotacoes[3] in camada.anotacoes and anotar.texto_de(vista.anotacoes[3]) == "meio ciclo"
    _esperar_a_pagina(qtbot, area, lambda: secao.nova("texto"))
    assert len(vista.anotacoes) == 5 and secao.escolhida.id == vista.anotacoes[4].id
    _esperar_a_pagina(qtbot, area, lambda: qtbot.mouseClick(secao.tirar, Qt.MouseButton.LeftButton))
    assert len(vista.anotacoes) == 4
    inset = props.secao_do_inset
    sem_inset = _pagina(area)
    previa = _esperar_a_pagina(qtbot, area, lambda: inset.ligado.setChecked(True))
    painel = janela.projeto.figuras[0].paineis[0]
    assert painel.inset is not None and not np.array_equal(previa, sem_inset)
    janela_x = props.eixos[painel.id].x
    assert painel.inset.limites_x == pytest.approx((janela_x[0] + 0.45 * (janela_x[1] - janela_x[0]),
                                                    janela_x[0] + 0.55 * (janela_x[1] - janela_x[0])))
    previa = _esperar_a_pagina(qtbot, area, lambda: _escolher_canto(inset, "sup_esq"))
    figura = janela.projeto.figuras[0]

    # 4. Igual na prévia, no PDF e no pacote. A prévia é o desenho da exportação (o mesmo, a menos da leitura das
    # amostras pela pirâmide: 1 pixel); o PDF, rasterizado, cai sobre a PNG; o pacote refaz a PNG dele.
    vistas, colhidos = area._colher(figura)
    exportada = desenhar(figura, vistas, colhidos, dpi=area.pagina.dpi_do_desenho(), exato=True).pixels()
    assert previa.shape == exportada.shape and _quase_igual(previa, exportada, 1)
    png, pdf, pacote = tmp_path / "f.png", tmp_path / "f.pdf", tmp_path / "f.zip"
    for opcoes, caminho in ((OpcoesDeExportacao("png", 150), png), (OpcoesDeExportacao("pdf", 150), pdf)):
        with qtbot.waitSignal(area.exportada, timeout=ESPERA_MS):
            area.exportar(opcoes, caminho)
    with qtbot.waitSignal(area.empacotada, timeout=ESPERA_MS):
        area.empacotar(OpcoesDeExportacao("pdf", 300), pacote)
    if shutil.which("pdftoppm"):
        subprocess.run(["pdftoppm", "-r", "150", "-png", "-singlefile", str(pdf), str(tmp_path / "do_pdf")],
                       check=True)
        a = np.asarray(Image.open(png).convert("RGB"))
        b = np.asarray(Image.open(tmp_path / "do_pdf.png").convert("RGB"))
        h, largura = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
        assert abs(a.shape[0] - b.shape[0]) <= 1 and abs(a.shape[1] - b.shape[1]) <= 1
        # 3 px: o Agg arredonda o avanço de cada letra, e o fim de um texto longo anda até isso (o PDF não).
        assert _quase_igual(a[:h, :largura], b[:h, :largura], 3)
    with zipfile.ZipFile(pacote) as z:
        z.extractall(tmp_path / "aberto")
    (pasta,) = (tmp_path / "aberto").iterdir()
    from test_gui_pacote import _refazer

    resultado = _refazer(pasta)
    assert resultado.returncode == 0 and "os mesmos pixels da figura.png" in resultado.stdout, resultado.stderr

    # 5. Desfeito o inset, a página volta; desfeitas as anotações (na vista), a figura as perde também.
    _esperar_a_pagina(qtbot, area, janela.acoes["desfazer"].trigger)
    _esperar_a_pagina(qtbot, area, janela.acoes["desfazer"].trigger)
    assert janela.projeto.figuras[0].paineis[0].inset is None
    assert np.array_equal(_pagina(area), sem_inset)


def _escolher_canto(inset, canto: str) -> None:
    i = inset.canto.findData(canto)
    inset.canto.setCurrentIndex(i)
    inset.canto.activated.emit(i)
