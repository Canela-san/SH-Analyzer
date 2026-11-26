"""Os perfis de sonda (ES-07, F5.9): o perfil para ver (dados/perfis_de_sonda.py: a curva é a do motor, as barras de
erro e a fase do arquivo) e a vista dos perfis na janela (a lista, o Bode com a faixa válida, qual perfil cada canal
usa e por quê, os perfis marcados nas opções da vista, com desfazer e no projeto). Sem tela."""

import json

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

import pyqtgraph as pg  # noqa: E402
import supraharmonicos.api as api  # noqa: E402
from capturas_sinteticas import escrever_bin  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from sh_analyzer_gui import preferencias  # noqa: E402
from sh_analyzer_gui.dados import perfis_de_sonda as ps  # noqa: E402
from sh_analyzer_gui.dados.cadeia import Cadeia, CorrecaoSonda  # noqa: E402
from sh_analyzer_gui.modelo.comandos import MudarTracos  # noqa: E402
from test_gui_vista_tempo import abrir, janela  # noqa: E402,F401


def _perfil(pasta, nome, *, fase=True, faixa=(100.0, 50_000.0)):
    pasta.mkdir(parents=True, exist_ok=True)
    f = np.geomspace(50, 100_000, 12)
    ganho = 1 / np.sqrt(1 + (f / 30_000) ** 2)
    pontos = []
    for i, (fi, gi) in enumerate(zip(f, ganho)):
        p = {"freq_hz": float(fi), "ganho": float(gi), "n": 3}
        if i != 4:                                        # um ponto sem a barra
            p["desvio_pct"] = 0.5
        if fase:
            p["fase_rad"] = float(-np.arctan(fi / 30_000))
            p["sigma_fase_rad"] = 0.002
        pontos.append(p)
    dados = {"id": nome, "tipo": "resposta_frequencia", "data_calibracao": "2026-10-01",
             "calibrado_com": "gerador e osciloscópio", "pontos": pontos, "faixa_freq_valida_hz": list(faixa)}
    caminho = pasta / f"{nome}.json"
    caminho.write_text(json.dumps(dados), encoding="utf-8")
    return caminho


def test_o_perfil_para_ver_e_a_curva_do_motor(tmp_path):
    caminho = _perfil(tmp_path, "sonda_a")
    p = ps.ler(caminho)
    assert p.id == "sonda_a" and len(p.freq_hz) == 12 and p.faixa_valida == (100.0, 50_000.0)
    assert p.calibrado_com == "gerador e osciloscópio" and p.data_calibracao.isoformat() == "2026-10-01"
    # A curva é a que a correção divide: o ganho_em do PerfilSonda que o motor carrega.
    f, db = p.curva()
    motor = api.carregar_perfil(caminho)
    assert np.allclose(db, 20 * np.log10(motor.ganho_em(f)), rtol=0, atol=1e-12)
    assert db[0] == pytest.approx(p.ganho_db[0]) and db[-1] == pytest.approx(p.ganho_db[-1])   # constante fora
    # As barras de erro: o desvio em % vira dB, assimétrico; o ponto sem desvio fica sem barra.
    abaixo, acima = p.barras_db()
    assert abaixo[0] == pytest.approx(-20 * np.log10(0.995)) and acima[0] == pytest.approx(20 * np.log10(1.005))
    assert np.isnan(abaixo[4]) and np.isnan(acima[4])
    assert p.fase_graus() == pytest.approx(np.degrees(-np.arctan(p.freq_hz / 30_000)))
    fc, graus = p.curva_da_fase()
    assert graus[0] == pytest.approx(p.fase_graus()[0]) and len(fc) == ps.PONTOS_DA_CURVA
    assert "12 pontos" in p.resumo() and "com a fase" in p.resumo() and "100 Hz a 50 kHz" in p.resumo()
    # Sem a fase em todo ponto, sem a fase; o que o motor não abre, não abre.
    assert ps.ler(_perfil(tmp_path, "sem_fase", fase=False)).fase_rad is None
    ruim = tmp_path / "ruim.json"
    ruim.write_text('{"id": "x", "tipo": "resposta_frequencia", "pontos": [{"freq_hz": 1, "ganho": 1}]}')
    with pytest.raises(ps.PerfilIlegivel, match="pelo menos 2"):
        ps.ler(ruim)
    assert ps.perfis_da_pasta(tmp_path) == sorted([caminho, tmp_path / "sem_fase.json", ruim])


def _janela_com_sonda(janela, qtbot, tmp_path):  # noqa: F811
    sondas = tmp_path / "sondas"
    a = _perfil(sondas, "sonda_a")
    _perfil(sondas, "sonda_b", fase=False, faixa=(200.0, 20_000.0))
    preferencias.mudar_pasta("sondas", sondas)
    t = np.arange(40_000) / 200_000
    v = 0.1 * np.sin(2 * np.pi * 60 * t)
    caminho = escrever_bin(tmp_path / "c.bin", [v, v], grandezas=(0, 1), sondas=("", "sonda_a"), versao=9,
                           extensao={"ganhos": [10.0, 20.0]})
    fonte = abrir(janela, qtbot, caminho)
    return fonte, a, sondas


def test_a_vista_dos_perfis(janela, qtbot, tmp_path):  # noqa: F811
    fonte, a, sondas = _janela_com_sonda(janela, qtbot, tmp_path)
    traco = janela.area.plotar_canal(fonte, 1)
    janela.acoes["perfis_de_sonda"].trigger()
    vista = janela.vista_ativa()
    assert vista.tipo == "sonda" and vista.nome == "Perfis de sonda"
    w = janela.area.widget_da_vista(vista)
    assert not janela.acoes["figura_da_vista"].isEnabled() and not janela.acoes["exportar_dados"].isEnabled()
    # A lista: o perfil em uso (o da sonda registrada no canal 1) e os da pasta; sem escolha, o em uso marcado.
    nomes = [w.lista.item(i).text() for i in range(w.lista.count())]
    assert nomes == ["sonda_a (em uso)", "sonda_b"] and w.marcados() == [str(a)]
    assert w.lista.item(0).checkState() == Qt.CheckState.Checked
    # O Bode: a magnitude e a fase (o perfil a traz), a faixa válida, os pontos com as barras.
    assert w.fase.isVisible() and len(w._pontos) == 12
    itens = [i for _p, i in w._itens_do_bode]
    assert sum(isinstance(i, pg.LinearRegionItem) for i in itens) == 2
    assert sum(isinstance(i, pg.ErrorBarItem) for i in itens) == 2
    regiao = next(i for i in itens if isinstance(i, pg.LinearRegionItem))
    assert regiao.getRegion() == pytest.approx((2.0, np.log10(50_000)))
    # O mouse perto de um ponto mostra os valores dele.
    caixa = w.magnitude.getViewBox()
    _c, i, lf, db, _g = w._pontos[3]
    texto = w.texto_do_ponto(w.ponto_perto(caixa.mapViewToScene(pg.Point(lf, db))))
    assert texto.startswith("sonda_a: ") and "desvio 0,5 %" in texto and "fase −" in texto and "± 0,115°" in texto
    # Os canais: qual perfil cada um usa e por quê, e a correção nos traços.
    linhas = {(linha[0], linha[1]): linha for linha in w.linhas_dos_canais()}
    assert linhas[(fonte.nome, "0")][2:6] == ("—", "—", "a captura não registra uma sonda para este canal",
                                       "nenhum traço corrige")
    assert linhas[(fonte.nome, "1")][3] == "sonda_a" and "registra a sonda sonda_a" in linhas[(fonte.nome, "1")][4]
    janela.projeto.pilha.push(MudarTracos([traco], cadeia=Cadeia((CorrecaoSonda(),))))
    qtbot.waitUntil(lambda: "o da captura" in w.linhas_dos_canais()[1][5], timeout=5_000)
    # Marcar o outro: as opções da vista (um passo de desfazer); o b não traz a fase.
    w.lista.item(1).setCheckState(Qt.CheckState.Checked)
    assert vista.opcoes.perfis == (str(a), str(sondas / "sonda_b.json"))
    qtbot.waitUntil(lambda: len(w._pontos) == 24, timeout=5_000)
    w.lista.item(0).setCheckState(Qt.CheckState.Unchecked)
    qtbot.waitUntil(lambda: not w.fase.isVisible(), timeout=5_000)       # o b não traz a fase
    janela.acoes["desfazer"].trigger()
    qtbot.waitUntil(lambda: w.fase.isVisible(), timeout=5_000)
    # O perfil escolhido num traço entra na lista como em uso.
    janela.projeto.pilha.push(MudarTracos([traco], cadeia=Cadeia((CorrecaoSonda(str(sondas / "sonda_b.json")),))))
    qtbot.waitUntil(lambda: w.lista.item(1).text() == "sonda_b (em uso)", timeout=5_000)
    assert "sonda_b" in w.linhas_dos_canais()[1][5]


def test_abrir_um_perfil_de_fora_e_o_projeto(janela, qtbot, tmp_path):  # noqa: F811
    _janela_com_sonda(janela, qtbot, tmp_path)
    fora = _perfil(tmp_path / "outra", "de_fora")
    janela.controle.dialogos.abrir_arquivo = lambda *_a: fora
    vista = janela.area.abrir_perfis()
    assert janela.area.abrir_perfis() is vista and len([v for v in janela.projeto.vistas if v.tipo == "sonda"]) == 1
    w = janela.area.widget_da_vista(vista)
    qtbot.mouseClick(w.abrir, Qt.MouseButton.LeftButton)
    assert str(fora) in vista.opcoes.perfis and w.lista.currentItem().text() == "de_fora"
    assert "Calibrado com: gerador e osciloscópio" in w.detalhe.text()
    # Uma vista de perfis vira o tipo "sonda" no projeto (a versão 7), com os perfis marcados.
    caminho = tmp_path / "p.shproj"
    assert janela.controle.salvar_como(caminho)
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    assert dados["versao"] >= 7
    salva = next(v for v in dados["vistas"] if v["tipo"] == "sonda")
    assert str(fora) in salva["opcoes"]["perfis"]
    assert janela.controle.abrir(caminho)
    vista = next(v for v in janela.projeto.vistas if v.tipo == "sonda")
    w = janela.area.widget_da_vista(vista)
    assert str(fora) in w.marcados() and w.lista.count() == 3
