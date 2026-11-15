"""Mede o portão G1 na vista de tempo de verdade (F1.5): a janela do aplicativo com 8 traços em 8 faixas, com o
eixo, a grade, a legenda e o minimapa, sobre uma captura sintética de 1 minuto (2 canais a 200 kS/s, plotados 4 vezes
cada). Percorre o zoom do protótipo (da captura inteira até ~50 amostras e de volta, com pan) e escreve a mediana e
o p95 do tempo por quadro: o G1 pede p95 <= 16 ms.

Com ``--cadeia`` (F2.11, o G1 com a cadeia ligada), cada traço ganha a correção de sonda (a captura registra a sonda
simulada nos dois canais) e um passa-altas de 2 kHz: o percurso é medido enquanto as materializações rodam (a prévia
de cada parada; elas rodam uma de cada vez, e a do outro canal espera na fila) e de novo depois delas, com os traços
transformados desenhados das pirâmides deles.

Rode numa tela de verdade (da raiz do repositório)::

    uv run --extra gui python -m sh_analyzer_gui.prototipos.medir_vista [--cadeia]

A captura e a configuração vão para uma pasta temporária; nada da sua configuração é tocado.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path


def cadeia_do_g1():
    """A cadeia do G1 com a cadeia ligada: a correção de sonda (o perfil que a captura registra) e um passa-altas de
    2 kHz, de 4ª ordem (a jornada típica dos supraharmônicos)."""
    from ..dados.cadeia import Cadeia, CorrecaoSonda, Filtro
    return Cadeia((CorrecaoSonda(), Filtro("passa_altas", (2000.0,), 4)))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--cadeia", action="store_true",
                   help="liga em cada traço a correção de sonda e um passa-altas de 2 kHz, e mede durante e depois "
                        "das materializações")
    args = p.parse_args(argv)
    pasta = Path(tempfile.mkdtemp(prefix="sh-analyzer-g1-"))
    os.environ["SH_ANALYZER_CONFIG"] = str(pasta / "config")
    os.environ.setdefault("SH_ANALYZER_CACHE", str(pasta / "cache"))

    import numpy as np
    from PySide6.QtCore import QTimer

    from .. import preferencias
    from ..app import criar_aplicacao
    from ..janela import JanelaPrincipal
    from ..modelo.comandos import MudarTracos
    from . import navegar

    # O gravador de capturas sintéticas (com o cabeçalho v9) e o perfil da sonda simulada são os dos testes: este
    # script roda do repositório.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
    from capturas_sinteticas import escrever_bin, escrever_perfil_sonda

    app = criar_aplicacao(sys.argv[:1], tema="escuro")
    n = 60 * 200_000
    t = np.arange(n) / 200_000
    sys.stderr.write("gerando a captura de 1 minuto...\n")
    sondas = ("sonda_teste", "sonda_teste") if args.cadeia else ("", "")
    caminho = escrever_bin(pasta / "um_minuto.bin", [np.sin(2 * np.pi * 60 * t), np.cos(2 * np.pi * 60 * t)],
                           grandezas=(0, 1), sondas=sondas, versao=9)
    if args.cadeia:
        preferencias.mudar_pasta("sondas", escrever_perfil_sonda(pasta / "sondas").parent)
    janela = JanelaPrincipal()
    janela.resize(1600, 1000)
    janela.show()
    (fonte,) = janela.controle.abrir_capturas([caminho])

    def vista():
        return janela.area.widget_da_vista(janela.vista_ativa())

    def medir():
        if fonte.piramides is None:
            QTimer.singleShot(100, medir)
            return
        tracos = []
        for i in range(8):
            traco = janela.area.plotar_canal(fonte, i % 2)
            janela.projeto.pilha.push(MudarTracos([traco], faixa=i))
            tracos.append(traco)
        if args.cadeia:
            janela.projeto.pilha.push(MudarTracos(tracos, cadeia=cadeia_do_g1()))
        # Mede depois de o layout assentar (o laço de eventos roda 0,5 s): medido logo depois de plotar, o gráfico
        # ainda tinha o tamanho de antes da legenda e dos painéis, e a medida saía numa área menor que a real.
        QTimer.singleShot(500, percorrer)

    def em_curso() -> tuple[int, int]:
        """As materializações dos traços que rodam e as que esperam a vez (rodam uma de cada vez)."""
        v = vista()
        estados = {v.materializacoes.estado_de(t) for t in v.itens} - {None}     # uma por canal e cadeia
        pendentes = [e for e in estados if e.pronta is None and not e.erro]
        na_fila = sum(1 for e in pendentes if e.na_fila)
        return len(pendentes) - na_fila, na_fila

    def percurso(como: str, aquecer: bool) -> None:
        v = vista()
        item = next(iter(v.itens.values()))
        canal = fonte.canal(0)
        if aquecer:
            navegar.percorrer_zoom(app, v.grafico, item, len(canal.amostras), canal.taxa_hz)
        mediana, p95 = navegar.resumo_dos_quadros(
            navegar.percorrer_zoom(app, v.grafico, item, len(canal.amostras), canal.taxa_hz))
        dpr = v.grafico.devicePixelRatioF()
        sys.stdout.write(f"vista de tempo, 8 faixas{como}, área de {v.grafico.width()} x {v.grafico.height()} px "
                         f"(escala {dpr:g}): mediana {mediana * 1e3:.1f} ms, p95 {p95 * 1e3:.1f} ms -> "
                         f"G1 {'aprovado' if p95 <= 0.016 else 'REPROVADO'}\n")

    def percorrer():
        if not args.cadeia:
            percurso("", aquecer=True)
            terminar()
            return
        rodando, na_fila = em_curso()
        percurso(f", com a cadeia, materializações: {rodando} rodando e {na_fila} na fila", aquecer=False)
        esperar_as_materializacoes()

    def esperar_as_materializacoes():
        if any(em_curso()):
            QTimer.singleShot(200, esperar_as_materializacoes)
            return
        percurso(", com a cadeia, materializada", aquecer=True)
        terminar()

    def terminar():
        janela.projeto.pilha.setClean()
        app.quit()

    QTimer.singleShot(200, medir)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
