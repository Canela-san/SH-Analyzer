"""Mede o portão G1 na vista de tempo de verdade (F1.5): a janela do aplicativo com 8 traços em 8 faixas, com o
eixo, a grade, a legenda e o minimapa, sobre uma captura sintética de 1 minuto (2 canais a 200 kS/s, plotados 4 vezes
cada). Percorre o zoom do protótipo (da captura inteira até ~50 amostras e de volta, com pan) e escreve a mediana e
o p95 do tempo por quadro: o G1 pede p95 <= 16 ms.

Rode numa tela de verdade (da raiz do repositório)::

    uv run --extra gui python -m sh_analyzer_gui.prototipos.medir_vista

A captura e a configuração vão para uma pasta temporária; nada da sua configuração é tocado.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    pasta = Path(tempfile.mkdtemp(prefix="sh-analyzer-g1-"))
    os.environ["SH_ANALYZER_CONFIG"] = str(pasta / "config")
    os.environ.setdefault("SH_ANALYZER_CACHE", str(pasta / "cache"))

    import numpy as np
    from PySide6.QtCore import QTimer

    from ..app import criar_aplicacao
    from ..janela import JanelaPrincipal
    from ..modelo.comandos import MudarTracos
    from . import navegar

    # O gravador de capturas sintéticas (com o cabeçalho v9) é o dos testes: este script roda do repositório.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
    from capturas_sinteticas import escrever_bin

    app = criar_aplicacao(sys.argv[:1], tema="escuro")
    n = 60 * 200_000
    t = np.arange(n) / 200_000
    sys.stderr.write("gerando a captura de 1 minuto...\n")
    caminho = escrever_bin(pasta / "um_minuto.bin", [np.sin(2 * np.pi * 60 * t), np.cos(2 * np.pi * 60 * t)],
                           versao=9)
    janela = JanelaPrincipal()
    janela.resize(1600, 1000)
    janela.show()
    (fonte,) = janela.controle.abrir_capturas([caminho])

    def medir():
        if fonte.piramides is None:
            QTimer.singleShot(100, medir)
            return
        for i in range(8):
            traco = janela.area.plotar_canal(fonte, i % 2)
            janela.projeto.pilha.push(MudarTracos([traco], faixa=i))
        # Mede depois de o layout assentar (o laço de eventos roda 0,5 s): medido logo depois de plotar, o gráfico
        # ainda tinha o tamanho de antes da legenda e dos painéis, e a medida saía numa área menor que a real.
        QTimer.singleShot(500, percorrer)

    def percorrer():
        vista = janela.area.widget_da_vista(janela.vista_ativa())
        item = next(iter(vista.itens.values()))
        canal = fonte.canal(0)
        navegar.percorrer_zoom(app, vista.grafico, item, len(canal.amostras), canal.taxa_hz)       # aquece
        mediana, p95 = navegar.resumo_dos_quadros(
            navegar.percorrer_zoom(app, vista.grafico, item, len(canal.amostras), canal.taxa_hz))
        dpr = vista.grafico.devicePixelRatioF()
        sys.stdout.write(f"vista de tempo, 8 faixas, área de {vista.grafico.width()} x {vista.grafico.height()} px "
                         f"(escala {dpr:g}): mediana {mediana * 1e3:.1f} ms, p95 {p95 * 1e3:.1f} ms -> "
                         f"G1 {'aprovado' if p95 <= 0.016 else 'REPROVADO'}\n")
        janela.projeto.pilha.setClean()
        app.quit()

    QTimer.singleShot(200, medir)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
