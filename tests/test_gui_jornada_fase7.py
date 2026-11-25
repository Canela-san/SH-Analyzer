"""A jornada da Fase 7 (F7.12: o "pronto quando" da fase, docs/gui-plan.md, 16), na janela e de ponta a ponta, com
as análises para pesquisadores: uma captura de campo (a tensão com um afundamento e um surto de supraharmônicos, a
corrente por um passa-baixa) aberta; o evento achado na lista e mostrado no tempo pelo clique; a qualidade de energia
com a janela do afundamento marcada e fora das estatísticas; o Instrumento disparando na rede; a transferência da
tensão para a corrente; a ajuda (F1) de cada vista; e o projeto salvo e aberto de novo com as vistas, as opções e os
mesmos números. Sem tela."""

import math

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
import scipy.signal  # noqa: E402
from capturas_sinteticas import FS_TOTAL_2CH, escrever_bin  # noqa: E402
from test_gui_vistas_de_analise import ESPERA_MS, abrir, janela  # noqa: E402,F401

FS = FS_TOTAL_2CH / 2
DURACAO_S = 3.0
AFUNDAMENTO = (0.3, 0.4)
INICIO_DAS_JANELAS = 1 / 60
"""As janelas de 12 ciclos (0,2 s) começam no primeiro cruzamento subindo depois do começo (o da amostra 0 não
conta): o surto ocupa uma janela inteira, e o afundamento fica dentro da segunda."""
SURTO = (INICIO_DAS_JANELAS + 0.8, INICIO_DAS_JANELAS + 1.0)
CORTE_HZ = 2_000.0


def _campo(pasta):
    """3 s de rede (8 V de pico, o 5º harmônico a 5 %, um ruído largo de 50 mV): o afundamento a 50 % em
    :data:`AFUNDAMENTO` e um surto de 20 kHz (1 V) em :data:`SURTO`; a corrente é a tensão por um passa-baixa de 1ª
    ordem em 2 kHz, com o ganho 0,5 (a transferência exata). O ruído largo é o que excita a transferência: com 10 mV,
    a quantização de 16 bits da corrente (0,3 mV o LSB) já baixava a coerência para 0,9 em 15 kHz."""
    t = np.arange(int(FS * DURACAO_S)) / FS
    w = 2 * np.pi * 60
    amplitude = np.where((t >= AFUNDAMENTO[0]) & (t < AFUNDAMENTO[1]), 4.0, 8.0)
    surto = np.where((t >= SURTO[0]) & (t < SURTO[1]), 1.0 * np.sin(2 * np.pi * 20_000 * t), 0.0)
    v = amplitude * np.sin(w * t) + 0.4 * np.sin(5 * w * t) + surto + 0.05 * np.random.default_rng(7).standard_normal(len(t))
    b, a = scipy.signal.butter(1, CORTE_HZ, fs=FS)
    i = 0.5 * scipy.signal.lfilter(b, a, v)
    return escrever_bin(pasta / "campo.bin", [v, i], versao=9), (b, a)


def test_da_captura_de_campo_ao_evento_a_qualidade_e_a_transferencia(janela, qtbot, tmp_path):  # noqa: F811
    caminho, (b, a) = _campo(tmp_path)

    # 1. A captura aberta e os dois canais na vista de tempo.
    (fonte,) = janela.controle.abrir_capturas([caminho])
    tensao = janela.area.plotar_canal(fonte, 0)
    tempo = janela.vista_ativa()
    janela.area.plotar_canal(fonte, 1, tempo)

    # 2. Os eventos: o afundamento e o surto, cada um no lugar; o clique mostra o afundamento no tempo.
    eventos = abrir(janela, qtbot, "eventos")
    achados = {e.tipo: e for e in eventos.eventos_mostrados()}
    assert {"afundamento", "supraharmonicos"} <= set(achados), list(achados)
    sag, supra = achados["afundamento"], achados["supraharmonicos"]
    assert sag.inicio_s == pytest.approx(AFUNDAMENTO[0], abs=1 / 60)
    assert supra.inicio_s == pytest.approx(SURTO[0], abs=1e-3) and supra.duracao_s == pytest.approx(0.2, abs=1e-3)
    eventos.tabela.selectRow(eventos.eventos_mostrados().index(sag))
    inicio, fim = janela.area.widget_da_vista(tempo).janela_de_tempo()
    assert inicio < AFUNDAMENTO[0] < AFUNDAMENTO[1] < fim and fim - inicio < 0.5
    assert janela.secao_da_ajuda() == "eventos"

    # 3. A qualidade de energia: a janela de 12 ciclos do afundamento marcada e fora das estatísticas.
    qualidade = abrir(janela, qtbot, "qualidade")
    marcadas = qualidade.marcadas()
    assert list(np.flatnonzero(marcadas)) == [1] and len(marcadas) == 14
    thd = qualidade.resultado.valores["thd"]
    assert np.allclose(thd[~marcadas], 0.05, rtol=0.02)
    qualidade.indice.setCurrentIndex(qualidade.indice.findData("supra_9_150k"))
    qualidade.indice.activated.emit(qualidade.indice.currentIndex())
    assert janela.secao_da_ajuda() == "qualidade"

    # 4. O Instrumento: o disparo por borda cruza o nível também no surto (mais disparos que ciclos); com o
    #    "Rejeitar AF", um por ciclo, na frequência da rede.
    instrumento = abrir(janela, qtbot, "instrumento")
    ciclos = int(DURACAO_S * 60)
    assert instrumento.resultado.disparo.n > ciclos + 10
    calculado = instrumento.resultado
    instrumento.rejeitar_af.setChecked(True)
    qtbot.waitUntil(lambda: instrumento.resultado is not calculado, timeout=ESPERA_MS)
    disparo = instrumento.resultado.disparo
    assert ciclos - 3 <= disparo.n <= ciclos and 1 / disparo.periodo_s == pytest.approx(60.0, abs=1e-3)
    assert "rejeitar AF" in " · ".join(instrumento._descricao())
    assert janela.secao_da_ajuda() == "instrumento"

    # 5. A transferência da tensão para a corrente: o passa-baixa com o ganho 0,5, com a coerência 1.
    transferencia = abrir(janela, qtbot, "transferencia")
    # De 3 a 15 kHz, onde o ruído largo domina: perto da rede (60 Hz a 8 V e os harmônicos) e do surto de 20 kHz, o
    # vazamento da janela puxa o H₁ para o valor do tom forte (o viés conhecido do estimador, não da conta).
    f, mag, baixo, alto, *_ = transferencia._dados()
    faixa = slice(int(np.searchsorted(f, 3_000)), int(np.searchsorted(f, 15_000)))
    _, h = scipy.signal.freqz(b, a, worN=f[faixa], fs=FS)
    assert np.max(np.abs(mag[faixa] - 20 * np.log10(0.5 * np.abs(h)))) < 0.3          # a mesma folga do teste da vista
    assert np.min(transferencia.resultado.coerencia[faixa]) > 0.98
    assert janela.secao_da_ajuda() == "transferencia"

    # 6. O projeto salvo e aberto de novo: as quatro análises, com as opções e os mesmos números.
    antes = {"eventos": [(e.tipo, round(e.inicio_s, 6)) for e in eventos.eventos_mostrados()],
             "marcadas": list(marcadas), "periodo": disparo.periodo_s, "mag": mag[faixa].copy()}
    caminho_do_projeto = tmp_path / "jornada7.shproj"
    assert janela.controle.salvar_como(caminho_do_projeto)
    assert janela.controle.abrir(caminho_do_projeto)
    (fonte,) = janela.projeto.fontes
    qtbot.waitUntil(lambda: fonte.piramides is not None, timeout=ESPERA_MS)
    vistas = {v.tipo: v for v in janela.projeto.vistas}
    assert {"tempo", "eventos", "qualidade", "instrumento", "transferencia"} <= set(vistas)
    assert vistas["qualidade"].opcoes.indice == "supra_9_150k" and vistas["instrumento"].opcoes.rejeitar_af
    widgets = {tipo: janela.area.widget_da_vista(vistas[tipo])
               for tipo in ("eventos", "qualidade", "instrumento", "transferencia")}
    for tipo, widget in widgets.items():
        janela.area.ativar_vista(vistas[tipo])
        qtbot.waitUntil(lambda w=widget: w.resultado is not None, timeout=ESPERA_MS)
    assert [(e.tipo, round(e.inicio_s, 6)) for e in widgets["eventos"].eventos_mostrados()] == antes["eventos"]
    assert list(widgets["qualidade"].marcadas()) == antes["marcadas"]
    assert widgets["instrumento"].resultado.disparo.periodo_s == pytest.approx(antes["periodo"], rel=1e-9)
    assert widgets["instrumento"].rejeitar_af.isChecked()
    assert np.allclose(widgets["transferencia"]._dados()[1][faixa], antes["mag"], atol=1e-9)
    assert math.isfinite(antes["periodo"])
