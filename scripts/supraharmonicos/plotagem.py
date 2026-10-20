"""Plotagem de forma de onda e espectro (matplotlib).

Único módulo do pacote que importa ``matplotlib`` -- quem não plota (conversão,
exportação HDF5, testes unitários de DSP) não paga o custo de importá-lo.

Depende de: ``constantes``."""

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from .constantes import GRANDEZA_TENSAO, NOMES_GRANDEZA, UNIDADE_GRANDEZA

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 8. Plotagem
# ---------------------------------------------------------------------------

def escolher_unidade_tempo(duracao_s: float):
    if duracao_s < 2.0:
        return 1000.0, "Tempo (ms)"
    return 1.0, "Tempo (s)"


def rotulo_eixo_grandeza(canais: list[int], grandeza_por_canal: dict[int, int]) -> str:
    """Rótulo do eixo Y da forma de onda no tempo, a partir da grandeza de
    cada canal em 'canais' -- 'Tensão (V)', 'Corrente (A)' ou
    'Temperatura (°C)' quando todos os canais plotados juntos compartilham
    a mesma grandeza; um rótulo genérico com aviso único (ver chamador em
    main()) quando misturados no mesmo eixo (--layout-canais sobrepostos
    com grandezas diferentes -- fisicamente estranho de sobrepor, mas não
    impedido)."""
    grandezas_presentes = {grandeza_por_canal.get(c, GRANDEZA_TENSAO) for c in canais}
    if len(grandezas_presentes) == 1:
        g = next(iter(grandezas_presentes))
        return f"{NOMES_GRANDEZA.get(g, 'Valor').capitalize()} ({UNIDADE_GRANDEZA.get(g, '?')})"
    return "Valor (unidades mistas -- ver rótulo de cada canal)"


def plotar_multicanal(tensoes_por_canal: dict[int, np.ndarray], fs_efetiva: float,
                       idx_inicio_arquivo: int, infos_espectro: dict | None,
                       titulo_arquivo: str, caminho_saida: Path | None,
                       layout: str, rotulo_espectro_y: str,
                       limite_inferior_db: float | None,
                       grandeza_por_canal: dict[int, int] | None = None,
                       idx_fim_arquivo: int | None = None) -> None:
    """Plota forma de onda e, se disponível, espectro(s) de 1+ canais. Um
    canal pode ter até 2 espectros simultâneos (--fft e --welch, chaves
    "ciclo"/"welch" em infos_espectro[canal]) -- plotados como curvas
    distintas no mesmo eixo, já que respondem perguntas diferentes
    (fundamental/harmônicos vs. conteúdo de banda larga não estacionário).

    'grandeza_por_canal' (opcional -- None mantém o rótulo histórico
    "Tensão (V)" para compatibilidade) rotula o eixo Y no tempo conforme a
    grandeza real de cada canal (tensão/corrente/temperatura), em vez de
    assumir sempre tensão -- ver rotulo_eixo_grandeza().

    'idx_inicio_arquivo'/'idx_fim_arquivo': o trecho, em amostras BRUTAS do arquivo (com N canais, N
    amostras brutas por instante), só para os títulos. Sem o fim, ele é deduzido com 1 canal."""
    canais = list(tensoes_por_canal.keys())
    n_canais = len(canais)
    tem_espectro = infos_espectro is not None
    if grandeza_por_canal is None:
        grandeza_por_canal = {c: GRANDEZA_TENSAO for c in canais}

    n = len(tensoes_por_canal[canais[0]])
    if idx_fim_arquivo is None:
        idx_fim_arquivo = idx_inicio_arquivo + n
    fator_tempo, rotulo_tempo = escolher_unidade_tempo(n / fs_efetiva)
    tempo = (np.arange(n) / fs_efetiva) * fator_tempo

    cores = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    usar_eixo_unico = (n_canais == 1) or (layout == "sobrepostos")
    estilo_metodo = {"ciclo": "-", "welch": "--"}

    if usar_eixo_unico:
        if tem_espectro:
            fig, (ax_tempo, ax_espectro) = plt.subplots(2, 1, figsize=(10, 8))
        else:
            fig, ax_tempo = plt.subplots(figsize=(10, 5))
            ax_espectro = None

        for i, canal in enumerate(canais):
            cor_tempo = "tab:green" if n_canais == 1 else cores[i % len(cores)]
            rotulo = None if n_canais == 1 else f"Canal {canal}"
            ax_tempo.plot(tempo, tensoes_por_canal[canal], color=cor_tempo, linewidth=1.0, label=rotulo)

        titulo_base = f"Forma de onda -- amostras {idx_inicio_arquivo}..{idx_fim_arquivo} de '{titulo_arquivo}'"
        ax_tempo.set_title(titulo_base if n_canais == 1 else f"{titulo_base} (canais {canais}, sobrepostos)")
        ax_tempo.set_xlabel(rotulo_tempo)
        ax_tempo.set_ylabel(rotulo_eixo_grandeza(canais, grandeza_por_canal))
        ax_tempo.grid(True, alpha=0.4)

        if tem_espectro:
            houve_sombra = False
            for i, canal in enumerate(canais):
                info_ciclo = infos_espectro[canal].get("ciclo")
                if info_ciclo is None:
                    continue
                cor_sombra = "tab:orange" if n_canais == 1 else cores[i % len(cores)]
                ini_janela = info_ciclo["idx_inicio_local"] / fs_efetiva * fator_tempo
                fim_janela = info_ciclo["idx_fim_local"] / fs_efetiva * fator_tempo
                rotulo_sombra = (
                    f"Janela do ciclo ({info_ciclo['n_ciclos']} ciclo(s))" if n_canais == 1
                    else f"Janela ciclo canal {canal}"
                )
                ax_tempo.axvspan(ini_janela, fim_janela, color=cor_sombra, alpha=0.20, label=rotulo_sombra)
                houve_sombra = True
            if houve_sombra:
                ax_tempo.legend(loc="upper right", fontsize=9 if n_canais == 1 else 8)

            for i, canal in enumerate(canais):
                metodos_canal = infos_espectro[canal]
                for metodo, info in metodos_canal.items():
                    cor_linha = "tab:blue" if n_canais == 1 else cores[i % len(cores)]
                    if n_canais == 1:
                        rotulo_linha = metodo if len(metodos_canal) > 1 else None
                    else:
                        rotulo_linha = f"Canal {canal} ({metodo})"
                    ax_espectro.plot(info["freqs"], info["amplitude_db"], color=cor_linha, linewidth=1.2,
                                      linestyle=estilo_metodo[metodo], label=rotulo_linha)

            metodos_canal0 = infos_espectro[canais[0]]
            if n_canais == 1 and len(metodos_canal0) == 1:
                metodo_unico, info_unico = next(iter(metodos_canal0.items()))
                if metodo_unico == "ciclo":
                    ax_espectro.set_title(
                        f"Espectro (ciclo) -- f0 = {info_unico['f0']:.3f} Hz | "
                        f"{info_unico['n_ciclos']} ciclo(s) | janela: {info_unico['janela']}"
                    )
                else:
                    ax_espectro.set_title(
                        f"Espectro (Welch) -- {info_unico['n_segmentos']} segmento(s) médios | "
                        f"janela: {info_unico['janela']}"
                    )
            else:
                ax_espectro.set_title(f"Espectro -- canais {canais}")
                ax_espectro.legend(loc="upper right", fontsize=8)

            ax_espectro.set_xlabel("Frequência (Hz)")
            ax_espectro.set_ylabel(rotulo_espectro_y)
            ax_espectro.grid(True, which="both", ls="-", alpha=0.4)
            ax_espectro.set_xlim(0, (fs_efetiva / 2.0) * 1.10)
            if limite_inferior_db is not None:
                ax_espectro.set_ylim(bottom=limite_inferior_db)

        plt.tight_layout()

    else:
        n_colunas = 2 if tem_espectro else 1
        fig, eixos = plt.subplots(n_canais, n_colunas, figsize=(6.5 * n_colunas, 3.2 * n_canais), squeeze=False)

        for i, canal in enumerate(canais):
            cor = cores[i % len(cores)]
            ax_tempo = eixos[i, 0]
            ax_tempo.plot(tempo, tensoes_por_canal[canal], color=cor, linewidth=1.0)
            ax_tempo.set_title(f"Canal {canal} -- amostras brutas {idx_inicio_arquivo}..{idx_fim_arquivo}")
            ax_tempo.set_xlabel(rotulo_tempo)
            ax_tempo.set_ylabel(rotulo_eixo_grandeza([canal], grandeza_por_canal))
            ax_tempo.grid(True, alpha=0.4)

            if tem_espectro:
                metodos_canal = infos_espectro[canal]
                ax_espectro = eixos[i, 1]

                info_ciclo = metodos_canal.get("ciclo")
                if info_ciclo is not None:
                    ini_janela = info_ciclo["idx_inicio_local"] / fs_efetiva * fator_tempo
                    fim_janela = info_ciclo["idx_fim_local"] / fs_efetiva * fator_tempo
                    ax_tempo.axvspan(ini_janela, fim_janela, color=cor, alpha=0.20,
                                      label=f"Janela do ciclo ({info_ciclo['n_ciclos']} ciclo(s))")
                    ax_tempo.legend(loc="upper right", fontsize=8)

                for metodo, info in metodos_canal.items():
                    ax_espectro.plot(info["freqs"], info["amplitude_db"], color=cor, linewidth=1.2,
                                      linestyle=estilo_metodo[metodo],
                                      label=metodo if len(metodos_canal) > 1 else None)
                if len(metodos_canal) > 1:
                    ax_espectro.legend(loc="upper right", fontsize=8)

                titulo_espectro = f"Canal {canal}"
                if info_ciclo is not None:
                    titulo_espectro += f" -- f0 = {info_ciclo['f0']:.3f} Hz | {info_ciclo['n_ciclos']} ciclo(s)"
                ax_espectro.set_title(titulo_espectro)
                ax_espectro.set_xlabel("Frequência (Hz)")
                ax_espectro.set_ylabel(rotulo_espectro_y)
                ax_espectro.grid(True, which="both", ls="-", alpha=0.4)
                ax_espectro.set_xlim(0, (fs_efetiva / 2.0) * 1.10)
                if limite_inferior_db is not None:
                    ax_espectro.set_ylim(bottom=limite_inferior_db)

        fig.suptitle(f"'{titulo_arquivo}' -- canais {canais} (separados)")
        plt.tight_layout(rect=[0, 0, 1, 0.97])

    if caminho_saida is not None:
        fig.savefig(caminho_saida, dpi=150)
        log.info(f"Gráfico salvo em '{caminho_saida}'.")
    else:
        plt.show()
    plt.close(fig)     # o pyplot guarda toda figura aberta: sem isto, quem chama várias vezes (notebook, testes) acumula memória
