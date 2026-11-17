"""O PySide6 instalado não tira referências do None (pyproject.toml, o extra ``gui``): o 6.12.0 tira uma a cada
chamada de um método do Qt sem retorno, e na Python 3.10 e na 3.11 o aplicativo morre em minutos com "Fatal Python
error: none_dealloc: deallocating None". Da 3.12 em diante o None é imortal (a contagem dele não muda nunca), e não há
o que medir."""

import sys

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

CHAMADAS = 1000


@pytest.mark.skipif(sys.version_info >= (3, 12), reason="o None é imortal da Python 3.12 em diante")
def test_os_metodos_do_qt_nao_tiram_referencias_do_none(qapp):
    janela = QWidget()
    janela.resize(100, 100)
    janela.show()
    QApplication.processEvents()
    for chamada in (janela.repaint, lambda: janela.setWindowTitle("x")):
        chamada()
        antes = sys.getrefcount(None)
        for _ in range(CHAMADAS):
            chamada()
        # Uma folga para o que outras threads façam com o None no meio; o defeito tira as 1 000.
        assert sys.getrefcount(None) - antes > -CHAMADAS // 10
    janela.close()
