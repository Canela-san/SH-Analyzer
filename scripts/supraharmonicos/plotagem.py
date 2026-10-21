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

# A forma de onda mostra TODAS as amostras do intervalo, por padrão. Só com --simplificar (ou --max-pontos N) ela
# vira a envoltória mín/máx de MAX_PONTOS_TEMPO pontos, que desenha uma captura de 10 min a 100 kS/s (60 milhões de
# amostras) em segundos, em vez de ~30 s e ~4 GB de RAM. Acima de AVISO_PONTOS amostras por canal, o adc_tool lembra
# dessa opção.
MAX_PONTOS_TEMPO = 20_000
AVISO_PONTOS = 5_000_000

# Com até tantas amostras visíveis, cada uma ganha um marcador: dá para ver onde o sinal foi amostrado (com 10
# amostras por ciclo, um tom de 10 kHz a 100 kS/s, as retas entre elas parecem um polígono, não a senoide).
MAX_PONTOS_COM_MARCADOR = 400

# O Agg desenha um caminho longo em pedaços: sem isso, uma linha de milhões de pontos pode estourar o limite dele
# ("Exceeded cell block limit"). Não muda o traço.
plt.rcParams["agg.path.chunksize"] = 20_000


def pontos_para_plot(y: np.ndarray, fs: float, fator_tempo: float,
                     max_pontos: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(tempo, valores) para desenhar ``y``. Sem ``max_pontos``, ou até ele, o próprio sinal. Acima, a envoltória: o
    sinal é dividido em ``max_pontos // 2`` colunas e cada uma vira dois pontos, o mínimo e o máximo, ligados por uma
    linha (como no modo de pico de um osciloscópio: nenhum pico some). As amostras que sobram no fim (menos que uma
    coluna) entram numa última coluna. Ampliada, a envoltória é um zigue-zague entre os extremos, não as amostras:
    por isso :func:`desenhar_forma_de_onda` refaz o trecho visível a cada zoom."""
    n = len(y)
    if max_pontos is None or n <= max_pontos:
        return np.arange(n) / fs * fator_tempo, y
    colunas = max(max_pontos // 2, 1)
    por_coluna = n // colunas
    cheias = y[: colunas * por_coluna].reshape(colunas, por_coluna)
    minimos, maximos = cheias.min(axis=1), cheias.max(axis=1)
    inicios = np.arange(colunas) * por_coluna
    if colunas * por_coluna < n:
        resto = y[colunas * por_coluna:]
        minimos, maximos = np.append(minimos, resto.min()), np.append(maximos, resto.max())
        inicios = np.append(inicios, colunas * por_coluna)
    tempo = np.repeat(inicios / fs * fator_tempo, 2)
    valores = np.empty(2 * len(minimos), dtype=y.dtype)
    valores[0::2], valores[1::2] = minimos, maximos
    return tempo, valores


def trecho_visivel(n: int, fs: float, fator_tempo: float, x0: float, x1: float) -> tuple[int, int]:
    """Índices [i0, i1) das amostras entre os instantes ``x0`` e ``x1`` (na unidade do eixo), com uma amostra de
    margem de cada lado, para a linha chegar às bordas."""
    i0 = max(int(np.floor(x0 * fs / fator_tempo)) - 1, 0)
    i1 = min(int(np.ceil(x1 * fs / fator_tempo)) + 2, n)
    return i0, max(i1, i0)


def desenhar_forma_de_onda(ax, y: np.ndarray, fs: float, fator_tempo: float, max_pontos: int | None = None,
                           **estilo):
    """Desenha ``y`` em ``ax`` (todas as amostras, ou a envoltória com ``max_pontos``) e liga o zoom da janela ao
    trecho visível. A cada mudança dos limites do eixo X (zoom, arrasto, "casa"): com a envoltória, o trecho é
    refeito, com as amostras de verdade quando cabem em ``max_pontos``; e, com até MAX_PONTOS_COM_MARCADOR amostras
    visíveis, cada uma ganha um marcador (numa linha à parte, só com elas: marcar milhões de pontos seria lento)."""
    linha, = ax.plot(*pontos_para_plot(y, fs, fator_tempo, max_pontos), **estilo)
    marcas, = ax.plot([], [], linestyle="none", marker="o", markersize=3, color=linha.get_color(),
                      label="_nolegend_")
    envoltoria = max_pontos is not None and len(y) > max_pontos

    def redesenhar(eixo):
        i0, i1 = trecho_visivel(len(y), fs, fator_tempo, *eixo.get_xlim())
        if envoltoria:
            tempo, valores = pontos_para_plot(y[i0:i1], fs, fator_tempo, max_pontos)
            linha.set_data(tempo + i0 / fs * fator_tempo, valores)
        if 0 < i1 - i0 <= MAX_PONTOS_COM_MARCADOR:
            marcas.set_data(np.arange(i0, i1) / fs * fator_tempo, y[i0:i1])
        else:
            marcas.set_data([], [])

    ax.callbacks.connect("xlim_changed", redesenhar)
    return linha


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
                       idx_fim_arquivo: int | None = None, max_pontos: int | None = None) -> None:
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
    amostras brutas por instante), só para os títulos. Sem o fim, ele é deduzido com 1 canal.

    'max_pontos': None (padrão) desenha todas as amostras; um número, a envoltória mín/máx com esse tanto de pontos
    por canal (--simplificar, --max-pontos)."""
    canais = list(tensoes_por_canal.keys())
    n_canais = len(canais)
    tem_espectro = infos_espectro is not None
    if grandeza_por_canal is None:
        grandeza_por_canal = {c: GRANDEZA_TENSAO for c in canais}

    n = len(tensoes_por_canal[canais[0]])
    if idx_fim_arquivo is None:
        idx_fim_arquivo = idx_inicio_arquivo + n
    fator_tempo, rotulo_tempo = escolher_unidade_tempo(n / fs_efetiva)
    if max_pontos is not None and n > max_pontos:
        log.info(f"Forma de onda: {n} amostras por canal desenhadas como envoltória mín/máx de {max_pontos} pontos "
                 f"(nenhum pico some). Na janela, o zoom mostra as amostras de verdade; sem --simplificar/--max-pontos, "
                 f"todas são desenhadas.")
    elif n > AVISO_PONTOS:
        log.info(f"Forma de onda: desenhando todas as {n} amostras por canal, o que pode demorar e usar muita memória; "
                 f"--simplificar desenha a envoltória mín/máx (rápida, nenhum pico some).")

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
            desenhar_forma_de_onda(ax_tempo, tensoes_por_canal[canal], fs_efetiva, fator_tempo, max_pontos,
                                   color=cor_tempo, linewidth=1.0, label=rotulo)

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
            desenhar_forma_de_onda(ax_tempo, tensoes_por_canal[canal], fs_efetiva, fator_tempo, max_pontos,
                                   color=cor, linewidth=1.0)
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


def _salvar_ou_mostrar(fig, caminho_saida: Path | None) -> None:
    if caminho_saida is not None:
        fig.savefig(caminho_saida, dpi=150)
        log.info(f"Gráfico salvo em '{caminho_saida}'.")
    else:
        plt.show()
    plt.close(fig)


def plotar_espectrogramas(dados_por_canal: dict[int, dict], titulo_arquivo: str, caminho_saida: Path | None,
                          rotulo_nivel: str, rotulo_janela: str | None) -> None:
    """Um espectrograma por canal (tempo × frequência, cor = nível em dB), um abaixo do outro."""
    canais = list(dados_por_canal)
    fig, eixos = plt.subplots(len(canais), 1, figsize=(11, 3.6 * len(canais)), squeeze=False)
    for ax, canal in zip(eixos[:, 0], canais):
        d = dados_por_canal[canal]
        nivel = d["db"]
        piso = np.percentile(nivel, 5)                                      # o piso de ruído não vira uma cor saturada
        malha = ax.pcolormesh(d["t"], d["f"] / 1000.0, nivel.T, shading="nearest", cmap="viridis",
                              vmin=piso, vmax=float(nivel.max()), rasterized=True)
        fig.colorbar(malha, ax=ax, label=rotulo_nivel)
        ax.set_ylabel("Frequência (kHz)")
        ax.set_title(f"Canal {canal}" if len(canais) > 1 else f"Espectrograma -- '{titulo_arquivo}'")
    eixos[-1, 0].set_xlabel("Tempo (s)")
    if len(canais) > 1:
        fig.suptitle(f"Espectrograma -- '{titulo_arquivo}'" + (f" | janela {rotulo_janela}" if rotulo_janela else ""))
    plt.tight_layout()
    _salvar_ou_mostrar(fig, caminho_saida)


def plotar_bandas_iec(bandas_por_canal: dict, unidade_por_canal: dict[int, str], titulo_arquivo: str,
                      caminho_saida: Path | None) -> None:
    """Para cada canal: o máximo, o P95 e o RMS de cada banda de 200 Hz (dB re 1 unidade, RMS), e a série no tempo
    das bandas como mapa de cor."""
    canais = list(bandas_por_canal)
    fig, eixos = plt.subplots(len(canais), 2, figsize=(13, 3.8 * len(canais)), squeeze=False)
    for (ax_est, ax_tempo), canal in zip(eixos, canais):
        b = bandas_por_canal[canal]
        u = unidade_por_canal[canal]
        est = b.estatisticas()
        db = {k: 20 * np.log10(np.maximum(v, 1e-12)) for k, v in est.items()}
        ax_est.step(b.centros_hz / 1000.0, db["maximo"], where="mid", label="máximo", color="tab:red")
        ax_est.step(b.centros_hz / 1000.0, db["p95"], where="mid", label="P95", color="tab:orange")
        ax_est.step(b.centros_hz / 1000.0, db["rms"], where="mid", label="RMS das janelas", color="tab:blue")
        for nome, estilo in (("3s", "--"), ("10min", ":")):
            if nome in b.agregados:
                p95 = 20 * np.log10(np.maximum(b.estatisticas(nome)["p95"], 1e-12))
                ax_est.step(b.centros_hz / 1000.0, p95, where="mid", label=f"P95 dos valores de {nome}",
                            color="tab:purple", linestyle=estilo)
        ax_est.set_xlabel("Centro da banda (kHz)")
        ax_est.set_ylabel(f"Nível por banda (dB{u}, RMS)")
        ax_est.grid(True, alpha=0.4)
        ax_est.legend(fontsize=8)
        ax_est.set_title(f"Canal {canal}: bandas de {b.largura_hz:g} Hz, {b.descricao_janelas()}", fontsize=9)
        nivel = 20 * np.log10(np.maximum(b.niveis, 1e-12))
        malha = ax_tempo.pcolormesh(b.tempos_s, b.centros_hz / 1000.0, nivel.T, shading="nearest", cmap="viridis",
                                    vmin=np.percentile(nivel, 5), vmax=float(nivel.max()), rasterized=True)
        fig.colorbar(malha, ax=ax_tempo, label=f"dB{u}")
        ax_tempo.set_xlabel("Tempo (s)")
        ax_tempo.set_ylabel("Centro da banda (kHz)")
        ax_tempo.set_title("Série no tempo")
    fig.suptitle(f"Bandas IEC 61000-4-7 (anexo B) -- '{titulo_arquivo}'")
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    _salvar_ou_mostrar(fig, caminho_saida)
