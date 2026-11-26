"""Importar dados de fora na janela (``areas/analise/importar.py``): o CSV qualquer pelo assistente das colunas,
o WAV arrastado para a janela, a grandeza e a escala de cada canal, e a captura importada no projeto, com os traços
e o espectro como os de qualquer outra."""

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
from supraharmonicos import api  # noqa: E402
from test_gui_vistas_de_analise import ESPERA_MS, janela  # noqa: E402,F401

TAXA = 20_000.0


def _csv(pasta):
    t = np.arange(4000) / TAXA
    v, i = 100 * np.sin(2 * np.pi * 60 * t), 2 * np.sin(2 * np.pi * 60 * t - 0.3)
    linhas = ["t;v;i"] + [f"{a:.8f};{b:.5f};{c:.5f}".replace(".", ",") for a, b, c in zip(t, v, i)]
    caminho = pasta / "analisador.csv"
    caminho.write_text("\n".join(linhas), encoding="utf-8")
    return caminho, v, i


def test_um_csv_qualquer_pelo_assistente(janela, qtbot, tmp_path):  # noqa: F811
    caminho, v, i = _csv(tmp_path)
    janela.controle.abrir_arquivos([caminho])          # não é do adc_tool: vai para o importar
    dialogo = janela.dialogo_de_importacao
    qtbot.waitUntil(lambda: dialogo.lido is not None, timeout=ESPERA_MS)
    assert dialogo.assistente.isVisible() and dialogo.previa.coluna_de_tempo == 0
    dialogo.modo.setCurrentIndex(dialogo.modo.findData("colunas"))
    qtbot.waitUntil(lambda: dialogo.lido is not None and len(dialogo.lido.canais) == 2, timeout=ESPERA_MS)
    assert dialogo._taxa_dita() == pytest.approx(TAXA)
    dialogo.definir_canal(1, unidade="A", escala=10.0)              # a corrente, por um shunt de 100 mΩ
    assert dialogo.importar_botao.isEnabled()
    dialogo.importar()
    qtbot.waitUntil(lambda: len(janela.projeto.fontes) == 1, timeout=ESPERA_MS)
    fonte = janela.projeto.fontes[0]
    assert fonte.nome == "analisador.importado.h5" and fonte.caminho.parent == tmp_path
    assert [c.nome_grandeza for c in fonte.canais] == ["tensão", "corrente"]
    corrente = api.sinal_do_canal(fonte.fonte.captura, fonte.canais[1].numero)
    assert np.max(np.abs(corrente - 10 * i)) < 1e-3 * 20
    assert not [a for a, _ in janela.avisos.avisos if a.nivel != "info"]   # sem "faixa suposta", sem "sem sonda"
    janela.area.plotar_canal(fonte, fonte.canais[0].numero)
    janela.acoes["espectro"].trigger()
    widget = janela.area.widget_da_vista(janela.vista_ativa())
    qtbot.waitUntil(lambda: bool(widget.resultados) and widget.resultados[0].espectro is not None, timeout=ESPERA_MS)


def test_o_wav_arrastado_abre_o_importar(janela, qtbot, tmp_path):  # noqa: F811
    from scipy.io import wavfile

    wavfile.write(tmp_path / "som.wav", 8000, (np.sin(np.arange(8000) / 10) * 20000).astype(np.int16))
    assert janela.controle.abrir_arquivos([tmp_path / "som.wav"])
    dialogo = janela.dialogo_de_importacao
    qtbot.waitUntil(lambda: dialogo.lido is not None, timeout=ESPERA_MS)
    assert not dialogo.assistente.isVisible() and dialogo._taxa_dita() == 8000
    assert "fundo de escala" in dialogo.resumo.text()
    dialogo.importar()
    qtbot.waitUntil(lambda: len(janela.projeto.fontes) == 1, timeout=ESPERA_MS)
    assert janela.projeto.fontes[0].canais[0].taxa_hz == pytest.approx(8000)
