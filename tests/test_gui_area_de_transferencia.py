"""A área de transferência com vários formatos (``componentes/area_de_transferencia.py``): a figura copiada não
derruba o aplicativo na saída (o defeito do PySide6 6.12 com o ``QMimeData`` criado no Python), e a limpeza da saída
só apaga o que o aplicativo pôs."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QGuiApplication  # noqa: E402
from sh_analyzer_gui.componentes import area_de_transferencia as at  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_copiar_e_sair_sem_cair():
    codigo = ("from PySide6.QtWidgets import QApplication\n"
              "from sh_analyzer_gui.componentes import area_de_transferencia as at\n"
              "app = QApplication([])\n"
              "at.copiar({'image/png': b'png', 'image/svg+xml': b'<svg/>'})\n")
    ambiente = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(SCRIPTS)}
    r = subprocess.run([sys.executable, "-c", codigo], env=ambiente, capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-500:]


def test_a_limpeza_so_apaga_o_que_e_nosso(qapp):
    area = QGuiApplication.clipboard()
    at.copiar({"image/svg+xml": b"<svg/>"})
    assert bytes(area.mimeData().data("image/svg+xml")) == b"<svg/>"
    area.setText("de outro programa")
    at.limpar_o_que_e_nosso()
    assert area.text() == "de outro programa"
    at.copiar({"image/svg+xml": b"<svg/>"})
    at.limpar_o_que_e_nosso()
    depois = area.mimeData()
    assert depois is None or not depois.hasFormat("image/svg+xml")
