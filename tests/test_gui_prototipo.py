"""O protótipo ``sh_analyzer_gui.prototipos.navegar``: o sinal sintético (sem Qt) e a linha de comando."""

import tempfile

import numpy as np
import pytest
from sh_analyzer_gui.prototipos import navegar


def test_sinal_sintetico_em_disco_e_reaproveitado(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    fonte = navegar.gerar_sintetico(0.01, 3, taxa_total=30_000)          # 0,6 s a 10 kS/s por canal
    assert fonte.n_canais == 3 and len(fonte.canais) == 3
    assert all(len(c.amostras) == 6_000 and c.taxa_hz == 10_000 for c in fonte.canais)
    assert fonte.amostras.dtype == np.int16 and isinstance(fonte.amostras, np.memmap)
    np.testing.assert_array_equal(fonte.canais[1].amostras, fonte.amostras[1::3])
    arquivos = list(tmp_path.iterdir())
    assert len(arquivos) == 1
    data = arquivos[0].stat().st_mtime_ns
    navegar.gerar_sintetico(0.01, 3, taxa_total=30_000)                   # o mesmo: não regera
    assert arquivos[0].stat().st_mtime_ns == data


def test_linha_de_comando_pede_uma_fonte():
    with pytest.raises(SystemExit) as e:
        navegar.main([])
    assert e.value.code == 2
