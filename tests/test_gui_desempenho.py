"""Os portões de desempenho da interface (docs/gui-plan.md, seção 6.7), medidos nesta máquina.

Ficam fora do conjunto padrão: medem tempo, e o tempo depende da máquina e da carga. Rode com::

    uv run --extra gui-dev pytest --desempenho -n 0 tests/test_gui_desempenho.py

Os limites são os do plano, com folga para um notebook comum; uma piora grande aparece aqui antes de aparecer na tela.
"""

import time

import numpy as np
import pytest
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
