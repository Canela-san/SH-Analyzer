"""O diálogo da taxa e dos canais de uma captura sem o cabeçalho (PD-02, ``areas/analise/sem_cabecalho.py``): a
validação com as regras do ``adc_tool``, o resumo para conferir e os canais que o arquivo diz. Sem tela."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QDialog, QLabel  # noqa: E402
from sh_analyzer_gui.app import criar_aplicacao  # noqa: E402
from sh_analyzer_gui.areas.analise.sem_cabecalho import DialogoSemCabecalho  # noqa: E402
from sh_analyzer_gui.dados.captura import ParametrosSemCabecalho  # noqa: E402


@pytest.fixture
def dialogo(qapp, config_limpa, qtbot):
    """Cria o diálogo e o entrega ao ``qtbot``, que o fecha e o apaga com o aplicativo ainda vivo (um diálogo sem pai
    apagado só na saída do Python derruba o processo)."""
    criar_aplicacao([], tema="escuro")

    def criar(*args):
        d = DialogoSemCabecalho(*args)
        qtbot.addWidget(d)
        return d

    return criar


def test_a_taxa_e_os_canais_validados_e_o_resumo(dialogo):
    d = dialogo("legado.bin", "bin", None, 40_000)
    assert d.windowTitle() == "Abrir legado.bin" and d.taxa.text() == "" and d.canais.text() == ""
    assert not d.abrir.isEnabled() and d.resumo.text() == "Não dá para abrir: falta a taxa total."
    assert any("formato antigo do ler_adc" in r.text() for r in d.findChildren(QLabel))
    d.taxa.setText("400k")
    assert not d.abrir.isEnabled() and d.resumo.text() == "Não dá para abrir: faltam os canais."
    d.canais.setText("0, 0")
    assert not d.abrir.isEnabled() and "repetido" in d.resumo.text()
    d.canais.setText("0, 9")
    assert "só tem canais 0-7" in d.resumo.text()
    d.canais.setText("3, 1")
    assert d.abrir.isEnabled()
    assert d.resumo.text() == "200 kHz por canal · 20 000 amostras por canal · 0,1 s de captura"
    assert d.parametros() == ParametrosSemCabecalho(400_000, (3, 1))          # a ordem da intercalação, como veio
    d.taxa.setText("400 kS/s")
    assert not d.abrir.isEnabled() and d.resumo.text().startswith("Não dá para abrir: a taxa total: unidade")
    d.accept()
    assert d.result() != QDialog.DialogCode.Accepted                          # inválido: o diálogo fica
    d.taxa.setText("1,5 MHz")
    d.accept()
    assert d.result() == QDialog.DialogCode.Accepted and d.parametros().taxa_total_hz == 1.5e6


def test_os_canais_do_arquivo_e_a_sugestao(dialogo):
    ultima = ParametrosSemCabecalho(100_000, (0,))
    d = dialogo("a.csv", "csv", (1, 3), None, ultima)
    assert d.canais.text() == "1, 3" and not d.canais.isEnabled()              # o arquivo diz: não se edita
    assert d.taxa.valor == 100_000 and d.abrir.isEnabled()
    assert d.parametros() == ParametrosSemCabecalho(100_000, (1, 3))
    assert d.resumo.text() == "50 kHz por canal"                                # sem o número de amostras
    assert any("não guarda a taxa" in r.text() for r in d.findChildren(QLabel))
    d = dialogo("b.bin", "bin", None, 10, ultima)
    assert d.canais.text() == "0" and d.canais.isEnabled() and d.parametros() == ultima
