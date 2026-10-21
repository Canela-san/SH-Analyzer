"""Os três modos do ``adc_tool``: exportação HDF5, conversão e plotagem/análise.

Cada ``executar_*`` recebe o ``argparse.Namespace`` (flags) e o
:class:`~supraharmonicos.contexto.ContextoCaptura` (o que a captura é) e faz o
trabalho; não lê ``sys.argv`` nem chama ``sys.exit``. Erros de dados/flags
viram :class:`~supraharmonicos.erros.ErroSHAN`; combinações inválidas de flags
viram :class:`~supraharmonicos.erros.ErroUso`.

O modo de plotagem é um pipeline linear, uma função por etapa (ordem importa:
a correção de sonda precisa vir ANTES do filtro do usuário e de qualquer
espectro, para que as etapas seguintes não precisem saber que existe uma
sonda)::

    frequência -> validação dos parâmetros -> carga/conversão a volts
    -> correção de sonda -> filtro Butterworth -> resumo -> FFT/Welch -> gráfico

Depende de: ``contexto`` e de todas as camadas de processamento
(``amostras``, ``sonda``, ``filtros``, ``espectro``, ``fundamental``,
``conversao``, ``hdf5``); ``plotagem`` só é importado quando o modo de
plotagem roda.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .amostras import (
    carregar_amostras,
    converter_para_tensao,
    detectar_tipo_arquivo,
    detectar_transitorio_inicial,
    selecionar_intervalo,
)
from .bandas_iec import (
    LARGURA_BANDA_IEC_HZ,
    agregar_iec,
    calcular_bandas_iec,
    ciclos_por_janela_iec,
    janelas_dos_cruzamentos,
)
from .canais import alinhar_ao_ciclo, desintercalar
from .constantes import (
    JANELA_PADRAO_FFT,
    JANELA_PADRAO_WELCH,
    NOMES_GRANDEZA,
    UNIDADE_GRANDEZA,
)
from .contexto import ContextoCaptura, aplicar_correcao_sondas
from .conversao import converter_arquivo
from .erros import ErroSHAN, ErroUso
from .espectro import (
    agrupar_em_bandas,
    calcular_espectro,
    calcular_espectro_welch,
    calcular_espectrograma,
    enbw_bins,
    encontrar_picos_espectro,
    resolver_nome_janela,
    rotulo_janela_completo,
    tamanho_segmento_welch,
)
from .exportacao import exportar_csv, exportar_mat
from .filtros import aplicar_filtro_digital, validar_corte_filtro
from .fundamental import cruzamentos_da_fundamental, recortar_ciclos_inteiros
from .harmonicos import calcular_harmonicos
from .hdf5 import exportar_hdf5

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Modo: exportação HDF5
# ---------------------------------------------------------------------------

def executar_exportacao_hdf5(args: argparse.Namespace, ctx: ContextoCaptura) -> None:
    if args.arquivo is None:
        raise ErroUso("--export-hdf5 precisa do argumento posicional 'arquivo' (o '.bin' de entrada).")
    if detectar_tipo_arquivo(args.arquivo) != "bin":
        raise ErroUso("--export-hdf5 só aceita um arquivo de entrada '.bin'.")
    if args.canais_exibir is not None:
        log.warning(
            "--canais-exibir é ignorado em --export-hdf5 (todos "
            "os canais de --canais são exportados)."
        )
    flags_de_plotagem_ignoradas = (
        args.fft is not None or args.welch or args.picos is not None or args.agrupar_bandas is not None
    )
    if flags_de_plotagem_ignoradas:
        log.warning(
            "--export-hdf5 ignora --fft/--welch/--picos/"
            "--agrupar-bandas (só se aplicam ao modo de plotagem)."
        )

    n_linhas, n_canais_exportados = exportar_hdf5(
        args.arquivo, args.export_hdf5, args.formato, ctx.canais, ctx.cabecalho,
        ctx.faixas, ctx.ganhos, ctx.offsets, args.incluir_tensao, ctx.offset_amostras,
        args.inicio, args.fim, args.tamanho_chunk,
        grandeza_por_canal=[ctx.grandeza_do_canal(c) for c in ctx.canais],
        sonda_id_por_canal=[ctx.sonda_id_do_canal(c) for c in ctx.canais],
        versao_codigo=_versao_do_codigo(),
    )
    extra_tensao = " + tensao_v calibrada" if args.incluir_tensao else ""
    log.info(
        f"Exportado: '{args.arquivo}' -> '{args.export_hdf5}' | "
        f"{n_linhas} amostra(s)/canal x {n_canais_exportados} canal(is){extra_tensao}"
    )


# ---------------------------------------------------------------------------
# Modo: conversão .bin <-> .csv
# ---------------------------------------------------------------------------

def executar_conversao(args: argparse.Namespace, ctx: ContextoCaptura) -> None:
    if args.arquivo is not None:
        raise ErroUso(
            "não use o argumento posicional 'arquivo' junto com "
            "-c/--converter; passe entrada em -c e saída em -o."
        )
    if args.saida is None:
        raise ErroUso("-o/--saida é obrigatório junto com -c/--converter.")
    converter_arquivo(
        args.converter, args.saida, args.formato, args.inicio, args.fim,
        args.incluir_tensao, ctx.canais, ctx.faixas, ctx.ganhos, ctx.offsets, args.tamanho_chunk,
        ctx.offset_amostras,
    )


# ---------------------------------------------------------------------------
# Modo: plotagem / análise espectral
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParametrosEspectro:
    """Parâmetros de --fft/--welch já validados. Cada método tem a sua janela (ver JANELA_PADRAO_* em constantes)."""
    janela_fft: str | None             # nome canônico (None sem --fft)
    rotulo_fft: str | None
    janela_welch: str | None           # nome canônico (None sem --welch)
    rotulo_welch: str | None
    freq_max_picos: float | None       # None se --picos não foi pedido


@dataclass(frozen=True)
class SinalCarregado:
    """Trecho selecionado da captura, já em volts, por canal exibido."""
    por_canal_tensao: dict[int, np.ndarray]
    idx_inicio: int
    idx_fim: int
    total: int                         # amostras brutas no arquivo
    tipo_arquivo: str                  # 'bin' | 'csv'


def executar_plotagem(args: argparse.Namespace, ctx: ContextoCaptura) -> None:
    if args.arquivo is None:
        raise ErroUso("o argumento 'arquivo' é obrigatório no modo de plotagem.")

    desenhar = _vai_desenhar(args)
    if desenhar:
        from . import plotagem  # só aqui o matplotlib é carregado; falha rápido, antes de ler a captura

    frequencia_total = _resolver_frequencia(args, ctx)
    fs_efetiva = frequencia_total / ctx.num_canais
    usa_fft = args.fft is not None
    usa_welch = args.welch

    # Validação de argumentos ANTES de tocar o arquivo (que pode ser grande).
    params = _validar_parametros(args, fs_efetiva, usa_fft, usa_welch)
    _avisar_combinacoes_arriscadas(args, usa_fft, usa_welch)

    sinal = _carregar_sinal(args, ctx)
    por_canal_tensao = sinal.por_canal_tensao

    grandeza_por_canal_exibir = aplicar_correcao_sondas(args, ctx, por_canal_tensao, fs_efetiva)
    _aplicar_filtros_usuario(args, ctx, por_canal_tensao, fs_efetiva)
    _resumir_dados(args, ctx, sinal, frequencia_total, fs_efetiva)

    resultados = {"canais": {canal: {"unidade": UNIDADE_GRANDEZA.get(grandeza_por_canal_exibir[canal], "V"),
                                     "grandeza": NOMES_GRANDEZA.get(grandeza_por_canal_exibir[canal], "tensão"),
                                     "modo": args.modo_espectro} for canal in ctx.canais_exibir},
                  "picos": []}
    infos_espectro = {canal: {} for canal in ctx.canais_exibir} if (usa_fft or usa_welch) else None
    if usa_fft:
        _analisar_fft(args, ctx, por_canal_tensao, fs_efetiva, params, infos_espectro, resultados)
    if usa_welch:
        _analisar_welch(args, ctx, por_canal_tensao, fs_efetiva, params, infos_espectro, resultados)
    if args.bandas_iec:
        _analisar_bandas_iec(args, ctx, por_canal_tensao, fs_efetiva, resultados)
    if args.espectrograma:
        _analisar_espectrograma(args, ctx, por_canal_tensao, fs_efetiva, params, resultados)
    if args.exportar is not None or args.exportar_mat is not None:
        _exportar(args, ctx, sinal, frequencia_total, fs_efetiva, params, resultados)

    rotulo_espectro_y = _rotulo_espectro(args, grandeza_por_canal_exibir)
    limite_inferior_db = -100.0 if (args.modo_espectro == "tom" and args.agrupar_bandas is None) else None

    # Título do cabeçalho da captura (--titulo no firmware) enriquece o título
    # do gráfico -- puramente cosmético, não afeta nenhum cálculo.
    cabecalho = ctx.cabecalho
    titulo_exibicao = (
        f"{cabecalho.titulo} ({args.arquivo.name})"
        if (cabecalho is not None and cabecalho.titulo)
        else args.arquivo.name
    )

    if not desenhar:
        return
    n_por_canal = len(next(iter(por_canal_tensao.values())))
    plotagem.plotar_multicanal(
        por_canal_tensao, fs_efetiva, sinal.idx_inicio, infos_espectro, titulo_exibicao,
        args.saida, args.layout_canais, rotulo_espectro_y, limite_inferior_db,
        grandeza_por_canal_exibir, idx_fim_arquivo=sinal.idx_inicio + n_por_canal * ctx.num_canais,
    )
    if args.espectrograma:
        plotagem.plotar_espectrogramas(
            {c: r["espectrograma"] for c, r in resultados["canais"].items()}, titulo_exibicao,
            _caminho_extra(args.saida, "espectrograma"), _rotulo_espectro_unidades(args, resultados, bandas=False),
            params.rotulo_welch)
    if args.bandas_iec:
        plotagem.plotar_bandas_iec(
            {c: r["bandas_iec"] for c, r in resultados["canais"].items()},
            {c: r["unidade"] for c, r in resultados["canais"].items()}, titulo_exibicao,
            _caminho_extra(args.saida, "bandas_iec"))


def _caminho_extra(saida: Path | None, sufixo: str) -> Path | None:
    """As figuras extras (espectrograma, bandas IEC) vão ao lado da principal: grafico.png -> grafico_<sufixo>.png."""
    return None if saida is None else saida.with_name(f"{saida.stem}_{sufixo}{saida.suffix or '.png'}")


def _rotulo_espectro_unidades(args: argparse.Namespace, resultados: dict, bandas: bool) -> str:
    unidades = {r["unidade"] for r in resultados["canais"].values()}
    u = unidades.pop() if len(unidades) == 1 else None
    if args.modo_espectro == "tom" or bandas:
        return f"Magnitude (dB{u})" if u else "Magnitude (dB re unidade do canal)"
    return f"PSD (dB re {u}²/Hz)" if u else "PSD (dB re unidade²/Hz)"


def _ha_tela() -> bool:
    """Há onde mostrar uma janela? (Linux sem DISPLAY/WAYLAND_DISPLAY = SSH ou servidor.)"""
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _vai_desenhar(args: argparse.Namespace) -> bool:
    """O gráfico só é feito (e o matplotlib só é importado) quando há onde colocá-lo: um arquivo (-o) ou uma tela.
    --sem-grafico deixa só os números (console e exportações): análise em lote, por SSH ou num servidor."""
    if args.sem_grafico:
        return False
    if args.saida is None and not _ha_tela() and not os.environ.get("MPLBACKEND"):
        log.warning("sem tela para mostrar o gráfico (SSH/servidor?): use -o ARQUIVO.png para salvá-lo, ou "
                    "--sem-grafico para só os números. Seguindo sem gráfico.")
        return False
    return True


def _rotulo_espectro(args: argparse.Namespace, grandeza_por_canal: dict[int, int]) -> str:
    """Rótulo do eixo do espectro na unidade dos canais exibidos (dBV na tensão, dBA na corrente)."""
    unidades = {UNIDADE_GRANDEZA.get(g, "V") for g in grandeza_por_canal.values()}
    u = unidades.pop() if len(unidades) == 1 else None
    if args.agrupar_bandas is not None:
        return f"Nível RMS por banda de {args.agrupar_bandas:g} Hz " + (f"(dB{u})" if u else "(dB re unidade do canal)")
    if args.modo_espectro == "tom":
        return f"Magnitude (dB{u})" if u else "Magnitude (dB re unidade do canal)"
    return f"PSD (dB re {u}²/Hz)" if u else "PSD (dB re unidade²/Hz)"


def _resolver_frequencia(args: argparse.Namespace, ctx: ContextoCaptura) -> float:
    """-f/--frequencia: explícita (CLI) > a taxa que a PRU gera (clock ÷ ticks do cabeçalho; --fs-pedida pula) >
    a pedida (frequencia_hz do cabeçalho) > obrigatória."""
    if args.frequencia is not None:
        return args.frequencia
    cab = ctx.cabecalho
    if cab is not None and cab.frequencia_hz > 0:
        pedida, gerada = float(cab.frequencia_hz), cab.frequencia_pru_hz
        if gerada is None or gerada == pedida:
            log.info(f"usando a frequência: {pedida:g} Hz")
            return pedida
        ppm = (gerada / pedida - 1) * 1e6
        if args.fs_pedida:
            log.info(f"usando a frequência: {pedida:g} Hz (a pedida, por --fs-pedida; a PRU gera {gerada:.2f} Hz, "
                     f"{ppm:+.1f} ppm)")
            return pedida
        log.info(f"usando a frequência: {gerada:.2f} Hz (a que a PRU gera, clock ÷ {cab.sample_period_ticks} ticks; "
                 f"a pedida era {pedida:g} Hz, {ppm:+.1f} ppm; --fs-pedida usa a pedida)")
        return gerada
    raise ErroUso(
        "-f/--frequencia é obrigatório no modo de plotagem (nenhum "
        "cabeçalho com essa informação foi encontrado em 'arquivo')."
    )


def _validar_parametros(args: argparse.Namespace, fs_efetiva: float,
                        usa_fft: bool, usa_welch: bool) -> ParametrosEspectro:
    """Valida janela, filtros, bandas, Welch e picos (nenhum I/O de captura)."""
    janela_fft = resolver_nome_janela(args.janela or JANELA_PADRAO_FFT) if usa_fft else None
    janela_welch = resolver_nome_janela(args.janela or JANELA_PADRAO_WELCH) if usa_welch else None
    rotulo_fft = rotulo_janela_completo(janela_fft, args.kaiser_beta) if janela_fft else None
    rotulo_welch = rotulo_janela_completo(janela_welch, args.kaiser_beta) if janela_welch else None

    if args.filtro_passa_baixa is not None:
        validar_corte_filtro(args.filtro_passa_baixa, fs_efetiva, "--filtro-passa-baixa")
    if args.filtro_passa_alta is not None:
        validar_corte_filtro(args.filtro_passa_alta, fs_efetiva, "--filtro-passa-alta")
    if (args.filtro_passa_alta is not None and args.filtro_passa_baixa is not None
            and args.filtro_passa_alta >= args.filtro_passa_baixa):
        raise ErroSHAN(
            f"--filtro-passa-alta ({args.filtro_passa_alta:g} Hz) "
            f"precisa ser menor que --filtro-passa-baixa "
            f"({args.filtro_passa_baixa:g} Hz)."
        )

    if not (usa_fft or usa_welch):
        if args.picos is not None:
            raise ErroUso("--picos requer --fft e/ou --welch ativos.")
        if args.agrupar_bandas is not None:
            raise ErroUso("--agrupar-bandas requer --fft e/ou --welch ativos.")

    if args.agrupar_bandas is not None and args.agrupar_bandas <= 0:
        raise ErroUso("--agrupar-bandas precisa ser positivo.")

    if usa_welch:
        if args.resolucao_welch <= 0:
            raise ErroUso("--resolucao-welch precisa ser positiva.")
        if not (0.0 <= args.sobreposicao_welch < 1.0):
            raise ErroUso("--sobreposicao-welch precisa estar em [0, 1).")
        if fs_efetiva / args.resolucao_welch < 16:
            raise ErroSHAN(
                f"--resolucao-welch {args.resolucao_welch:g} Hz produz "
                f"um segmento menor que 16 amostras na frequência efetiva "
                f"{fs_efetiva:g} Hz. Reduza --resolucao-welch."
            )

    if args.harmonicos is not None:
        if not usa_fft:
            raise ErroUso("--harmonicos requer --fft (a tabela usa o trecho sincronizado em ciclos inteiros).")
        if args.harmonicos < 1:
            raise ErroUso("--harmonicos precisa ser >= 1.")
    if args.espectrograma:
        if args.resolucao_welch <= 0 or not (0.0 <= args.sobreposicao_welch < 1.0):
            raise ErroUso("--espectrograma usa --resolucao-welch (> 0) e --sobreposicao-welch (em [0, 1)).")
    if args.espectrograma and janela_welch is None:
        janela_welch = resolver_nome_janela(args.janela or JANELA_PADRAO_WELCH)
        rotulo_welch = rotulo_janela_completo(janela_welch, args.kaiser_beta)
    if args.bandas_iec:
        nyquist = fs_efetiva / 2.0
        maximo = nyquist if args.bandas_iec_max is None else args.bandas_iec_max
        if args.bandas_iec_min < 0 or maximo - args.bandas_iec_min < LARGURA_BANDA_IEC_HZ:
            raise ErroUso(f"--bandas-iec: nenhuma banda de {LARGURA_BANDA_IEC_HZ:g} Hz cabe entre "
                          f"{args.bandas_iec_min:g} e {maximo:g} Hz (Nyquist do canal: {nyquist:g} Hz).")
    if (args.bandas_iec_sincronizar or args.bandas_iec_agregar) and not args.bandas_iec:
        raise ErroUso("--bandas-iec-sincronizar e --bandas-iec-agregar são extras do --bandas-iec: use-o junto.")
    if args.exportar_mat is not None and args.exportar_mat.suffix.lower() != ".mat":
        raise ErroUso("--exportar-mat espera um arquivo terminado em .mat.")

    freq_max_picos = None
    if args.picos is not None:
        freq_max_picos = args.freq_max_picos if args.freq_max_picos is not None else fs_efetiva / 2.0
        if args.freq_min_picos >= freq_max_picos:
            raise ErroSHAN("--freq-min-picos precisa ser menor que --freq-max-picos.")

    return ParametrosEspectro(janela_fft, rotulo_fft, janela_welch, rotulo_welch, freq_max_picos)


def _avisar_combinacoes_arriscadas(args: argparse.Namespace, usa_fft: bool, usa_welch: bool) -> None:
    if (usa_welch or args.picos is not None) and args.filtro_passa_alta is None:
        log.warning(
            "--welch/--picos sem --filtro-passa-alta -- resíduo da "
            "fundamental e de harmônicos de baixa ordem pode mascarar "
            "supraharmônicos fracos. Considere, por exemplo, "
            "'--filtro-passa-alta 2000'."
        )
    if usa_fft and args.filtro_passa_alta is not None and args.filtro_passa_alta >= args.freq_min:
        log.warning(
            f"--fft precisa da fundamental (banda {args.freq_min:g}-"
            f"{args.freq_max:g} Hz) para sincronizar o corte em ciclos "
            f"inteiros, mas --filtro-passa-alta {args.filtro_passa_alta:g} Hz "
            f"remove essa banda ANTES do corte -- f0/o corte resultantes "
            f"provavelmente ficam inválidos. Para isolar supraharmônicos com "
            f"--welch/--picos sem quebrar --fft, rode os dois em comandos "
            f"separados em vez de na mesma chamada."
        )


def _carregar_sinal(args: argparse.Namespace, ctx: ContextoCaptura) -> SinalCarregado:
    """Carrega o trecho pedido (--inicio/--fim) e converte código -> volts, por canal exibido."""
    tipo_arquivo = detectar_tipo_arquivo(args.arquivo)
    amostras = carregar_amostras(args.arquivo, args.formato, offset=ctx.offset_amostras)
    inicio = alinhar_ao_ciclo(args.inicio, ctx.num_canais)
    bruto, idx_inicio, idx_fim, total = selecionar_intervalo(amostras, inicio, args.fim)

    por_canal_bruto = desintercalar(bruto, ctx.canais, ctx.canais_exibir)
    por_canal_tensao: dict[int, np.ndarray] = {}
    for canal in ctx.canais_exibir:
        _avisar_transitorio(canal, por_canal_bruto[canal], idx_inicio, ctx.num_canais)
        idx = ctx.indice_no_ciclo(canal)
        por_canal_tensao[canal] = converter_para_tensao(
            por_canal_bruto[canal], ctx.faixas[idx], ctx.ganhos[idx], args.formato, ctx.offsets[idx]
        )
    return SinalCarregado(por_canal_tensao, idx_inicio, idx_fim, total, tipo_arquivo)


def _avisar_transitorio(canal: int, codigos: np.ndarray, idx_inicio: int, num_canais: int) -> None:
    """Avisa (sem descartar nada: o adc_tool também converte) quando o começo do trecho foge do resto -- o transitório
    de uma troca de faixa do ADC (F9), que infla DC, RMS e ruído. O ``medir_captura`` já pula esse começo sozinho."""
    n, desvio = detectar_transitorio_inicial(codigos)
    if n:
        sugestao = alinhar_ao_ciclo(idx_inicio + num_canais * max(100, 2 * n), num_canais)
        log.warning(f"canal {canal}: as {n} primeiras amostras do trecho fogem do resto, até {desvio:.0f} LSB -- é o "
                    f"jeito do transitório de uma troca de faixa do ADC. Para medir DC, RMS ou ruído, comece depois "
                    f"dele: --inicio {sugestao}.")


def _aplicar_filtros_usuario(args: argparse.Namespace, ctx: ContextoCaptura,
                             por_canal_tensao: dict[int, np.ndarray], fs_efetiva: float) -> None:
    """--filtro-passa-alta/--filtro-passa-baixa (Butterworth, fase zero), em todos os canais exibidos."""
    if args.filtro_passa_alta is None and args.filtro_passa_baixa is None:
        return
    for canal in ctx.canais_exibir:
        sinal = por_canal_tensao[canal]
        if args.filtro_passa_alta is not None:
            sinal = aplicar_filtro_digital(sinal, fs_efetiva, "high", args.filtro_passa_alta, args.ordem_filtro)
        if args.filtro_passa_baixa is not None:
            sinal = aplicar_filtro_digital(sinal, fs_efetiva, "low", args.filtro_passa_baixa, args.ordem_filtro)
        por_canal_tensao[canal] = sinal


def _resumir_dados(args: argparse.Namespace, ctx: ContextoCaptura, sinal: SinalCarregado,
                   frequencia_total: float, fs_efetiva: float) -> None:
    """Imprime o resumo de conversão/janela de dados e do filtro aplicado."""
    n_por_canal = len(next(iter(sinal.por_canal_tensao.values())))
    log.info(f"Arquivo: {args.arquivo}  ({sinal.total} amostras no total, formato: .{sinal.tipo_arquivo})")

    if ctx.num_canais == 1:
        idx0 = ctx.indice_no_ciclo(ctx.canais_exibir[0])
        log.info(f"Conversão: --formato {args.formato} | --faixa {ctx.faixas[idx0]} V | "
                 f"--offset {ctx.offsets[idx0]} V | --ganho {ctx.ganhos[idx0]}")
        log.info(f"Janela de dados: amostras {sinal.idx_inicio}..{sinal.idx_fim} "
                 f"({n_por_canal} amostras, {n_por_canal / fs_efetiva * 1000:.2f} ms)")
    else:
        log.info(f"Canais na captura: {ctx.canais} | exibindo: {ctx.canais_exibir} | layout: {args.layout_canais}")
        log.info(f"Frequência total {frequencia_total:g} Hz / {ctx.num_canais} canais -> "
                 f"frequência efetiva por canal: {fs_efetiva:g} Hz")
        for canal in ctx.canais_exibir:
            idx = ctx.indice_no_ciclo(canal)
            log.info(f"  Canal {canal}: --formato {args.formato} | --faixa {ctx.faixas[idx]} V | "
                     f"--offset {ctx.offsets[idx]} V | --ganho {ctx.ganhos[idx]}")
        log.info(f"Janela de dados: amostras brutas {sinal.idx_inicio}..{sinal.idx_fim} "
                 f"({n_por_canal} amostras/canal, {n_por_canal / fs_efetiva * 1000:.2f} ms/canal)")

    if args.filtro_passa_alta is not None or args.filtro_passa_baixa is not None:
        partes_filtro = []
        if args.filtro_passa_alta is not None:
            partes_filtro.append(f"passa-alta {args.filtro_passa_alta:g} Hz")
        if args.filtro_passa_baixa is not None:
            partes_filtro.append(f"passa-baixa {args.filtro_passa_baixa:g} Hz")
        log.info(f"Filtro digital Butterworth aplicado (ordem {args.ordem_filtro}, fase zero): "
                 f"{' + '.join(partes_filtro)}")


def _analisar_fft(args: argparse.Namespace, ctx: ContextoCaptura,
                  por_canal_tensao: dict[int, np.ndarray], fs_efetiva: float,
                  params: ParametrosEspectro, infos_espectro: dict, resultados: dict) -> None:
    """--fft: FFT única sobre um número inteiro de ciclos da fundamental."""
    n_ciclos_pedido = args.fft if args.fft > 0 else None
    for canal in ctx.canais_exibir:
        sinal_fft, idx_i_local, idx_f_local, f0, n_ciclos = recortar_ciclos_inteiros(
            por_canal_tensao[canal], fs_efetiva, args.freq_min, args.freq_max, n_ciclos_pedido
        )
        freqs, amplitude_db = calcular_espectro(
            sinal_fft, fs_efetiva, params.janela_fft, args.kaiser_beta, args.modo_espectro
        )
        resultado = resultados["canais"][canal]
        resultado["fft"] = {"f": freqs, "db": amplitude_db, "f0_hz": f0, "n_ciclos": n_ciclos,
                            "amostras": len(sinal_fft), "inicio_local": idx_i_local}

        if args.picos is not None:
            picos = encontrar_picos_espectro(
                freqs, amplitude_db, args.freq_min_picos, params.freq_max_picos,
                args.picos, args.distancia_minima_picos
            )
            _registrar_picos(canal, "ciclo", picos, ctx.num_canais, resultados)

        if args.agrupar_bandas is not None:
            freqs, amplitude_db = agrupar_em_bandas(
                freqs, amplitude_db, args.agrupar_bandas, args.modo_espectro,
                enbw=enbw_bins(params.janela_fft, len(sinal_fft), args.kaiser_beta),
            )
            resultado["fft_bandas"] = {"f": freqs, "db": amplitude_db}

        if args.harmonicos is not None:
            tabela = calcular_harmonicos(sinal_fft, fs_efetiva, f0, n_ciclos, args.harmonicos)
            resultado["harmonicos"] = tabela
            if ctx.num_canais > 1:
                log.info(f"  Canal {canal}:")
            for linha in tabela.linhas(resultado["unidade"]):
                log.info(linha)

        if ctx.num_canais == 1:
            log.info(f"FFT (ciclo): f0 = {f0:.3f} Hz | {n_ciclos} ciclo(s) completo(s) | "
                     f"{len(sinal_fft)} amostras (locais {idx_i_local}..{idx_f_local}) | "
                     f"janela: {params.rotulo_fft} | modo: {args.modo_espectro}")
        else:
            log.info(f"  Canal {canal} FFT (ciclo): f0 = {f0:.3f} Hz | {n_ciclos} ciclo(s) | "
                     f"{len(sinal_fft)} amostras (locais {idx_i_local}..{idx_f_local})")

        infos_espectro[canal]["ciclo"] = {
            "freqs": freqs, "amplitude_db": amplitude_db, "f0": f0, "n_ciclos": n_ciclos,
            "idx_inicio_local": idx_i_local, "idx_fim_local": idx_f_local, "janela": params.rotulo_fft,
        }


def _analisar_welch(args: argparse.Namespace, ctx: ContextoCaptura,
                    por_canal_tensao: dict[int, np.ndarray], fs_efetiva: float,
                    params: ParametrosEspectro, infos_espectro: dict, resultados: dict) -> None:
    """--welch: espectro médio por segmentação (supraharmônicos)."""
    for canal in ctx.canais_exibir:
        freqs, amplitude_db, n_segmentos = calcular_espectro_welch(
            por_canal_tensao[canal], fs_efetiva, params.janela_welch, args.kaiser_beta,
            args.resolucao_welch, args.sobreposicao_welch, args.modo_espectro,
        )
        resultado = resultados["canais"][canal]
        resultado["welch"] = {"f": freqs, "db": amplitude_db, "n_segmentos": n_segmentos}

        if args.picos is not None:
            picos = encontrar_picos_espectro(
                freqs, amplitude_db, args.freq_min_picos, params.freq_max_picos,
                args.picos, args.distancia_minima_picos
            )
            _registrar_picos(canal, "welch", picos, ctx.num_canais, resultados)

        if args.agrupar_bandas is not None:
            n_segmento = tamanho_segmento_welch(fs_efetiva, args.resolucao_welch)
            freqs, amplitude_db = agrupar_em_bandas(
                freqs, amplitude_db, args.agrupar_bandas, args.modo_espectro,
                enbw=enbw_bins(params.janela_welch, n_segmento, args.kaiser_beta),
            )
            resultado["welch_bandas"] = {"f": freqs, "db": amplitude_db}

        prefixo = f"  Canal {canal} " if ctx.num_canais > 1 else ""
        log.info(f"{prefixo}Welch: {n_segmentos} segmento(s) médios | "
                 f"resolução {args.resolucao_welch:g} Hz | janela: {params.rotulo_welch} | modo: {args.modo_espectro}")

        infos_espectro[canal]["welch"] = {
            "freqs": freqs, "amplitude_db": amplitude_db,
            "n_segmentos": n_segmentos, "janela": params.rotulo_welch,
        }


def _registrar_picos(canal: int, metodo: str, picos: list[dict], num_canais: int, resultados: dict) -> None:
    resultados["picos"].extend({"canal": canal, "metodo": metodo, **p} for p in picos)
    prefixo = f"  Canal {canal} " if num_canais > 1 else "  "
    if not picos:
        log.info(f"{prefixo}[{metodo}] nenhum pico acima do limiar encontrado.")
        return
    for pico in picos:
        log.info(f"{prefixo}[{metodo}] pico: {pico['frequencia_hz']:.2f} Hz @ {pico['amplitude_db']:.2f} dB")


def _janelas_sincronizadas(args: argparse.Namespace, ctx: ContextoCaptura,
                           por_canal_tensao: dict[int, np.ndarray], fs_efetiva: float,
                           resultados: dict) -> tuple[np.ndarray, int, float]:
    """--bandas-iec-sincronizar: bordas de janelas de 10/12 ciclos da fundamental (IEC 61000-4-30), as mesmas para
    todos os canais (amostrados juntos). A referência é o primeiro canal de tensão exibido (a tensão da rede é estável
    e sempre tem a fundamental; numa corrente, a fundamental pode faltar), ou o primeiro canal."""
    tensao = [c for c in ctx.canais_exibir if resultados["canais"][c]["unidade"] == "V"]
    referencia = (tensao or ctx.canais_exibir)[0]
    cruzamentos, f0 = cruzamentos_da_fundamental(por_canal_tensao[referencia], fs_efetiva, args.freq_min, args.freq_max)
    ciclos = ciclos_por_janela_iec(f0)
    janelas, descartadas = janelas_dos_cruzamentos(cruzamentos, ciclos)
    if len(janelas) < 1:
        raise ErroSHAN(f"--bandas-iec-sincronizar precisa de pelo menos {ciclos} ciclos completos e estáveis da "
                       f"fundamental no trecho; há {len(cruzamentos) - 1} ciclo(s).")
    log.info(f"Bandas IEC sincronizadas pela fundamental do canal {referencia}: {f0:.4f} Hz, {ciclos} ciclos por janela "
             f"({len(janelas)} janelas; as amostras antes do 1º cruzamento por zero ficam de fora).")
    if descartadas:
        log.warning(f"--bandas-iec-sincronizar: {descartadas} janela(s) descartada(s) por não terem {ciclos} ciclos "
                    f"dentro de ±0,03 % (a borda do trecho, onde o filtro distorce a fase, ou um salto de fase ou "
                    f"falta de tensão no meio da captura; a IEC 61000-4-30 manda sinalizar esses intervalos).")
    return janelas, ciclos, f0


def _analisar_bandas_iec(args: argparse.Namespace, ctx: ContextoCaptura,
                         por_canal_tensao: dict[int, np.ndarray], fs_efetiva: float, resultados: dict) -> None:
    """--bandas-iec: bandas de 200 Hz em janelas sem lacunas (IEC 61000-4-7, anexo B), com estatísticas. Por padrão,
    janelas fixas de 200 ms; --bandas-iec-sincronizar e --bandas-iec-agregar são extras (IEC 61000-4-30)."""
    limites, ciclos, f0 = (None, None, None)
    if args.bandas_iec_sincronizar:
        limites, ciclos, f0 = _janelas_sincronizadas(args, ctx, por_canal_tensao, fs_efetiva, resultados)
    for canal in ctx.canais_exibir:
        bandas = calcular_bandas_iec(por_canal_tensao[canal], fs_efetiva, args.bandas_iec_min, args.bandas_iec_max,
                                     limites=limites, ciclos_por_janela=ciclos, f0_hz=f0)
        if args.bandas_iec_agregar:
            bandas = agregar_iec(bandas)
            if not bandas.agregados and canal == ctx.canais_exibir[0]:
                log.warning(f"--bandas-iec-agregar: o trecho tem {len(bandas.tempos_s)} janela(s); um intervalo de "
                            f"150/180 ciclos (~3 s) precisa de 15. Nenhuma série agregada.")
        resultado = resultados["canais"][canal]
        resultado["bandas_iec"] = bandas
        if ctx.num_canais > 1:
            log.info(f"  Canal {canal}:")
        for linha in bandas.linhas(resultado["unidade"]):
            log.info(linha)


def _analisar_espectrograma(args: argparse.Namespace, ctx: ContextoCaptura,
                            por_canal_tensao: dict[int, np.ndarray], fs_efetiva: float,
                            params: ParametrosEspectro, resultados: dict) -> None:
    """--espectrograma: o espectro ao longo do tempo (segmentos do Welch reunidos em até 600 colunas)."""
    for canal in ctx.canais_exibir:
        tempos, freqs, matriz = calcular_espectrograma(
            por_canal_tensao[canal], fs_efetiva, params.janela_welch, args.kaiser_beta,
            args.resolucao_welch, args.sobreposicao_welch, args.modo_espectro)
        resultados["canais"][canal]["espectrograma"] = {"t": tempos, "f": freqs, "db": matriz}
        prefixo = f"  Canal {canal} " if ctx.num_canais > 1 else ""
        log.info(f"{prefixo}Espectrograma: {len(tempos)} colunas de {tempos[1] - tempos[0] if len(tempos) > 1 else 0:.3g} s "
                 f"x {len(freqs)} frequências (resolução {args.resolucao_welch:g} Hz, janela {params.rotulo_welch})")


def _exportar(args: argparse.Namespace, ctx: ContextoCaptura, sinal: SinalCarregado, frequencia_total: float,
              fs_efetiva: float, params: ParametrosEspectro, resultados: dict) -> None:
    """--exportar/--exportar-mat: os resultados e tudo o que os produziu (ver ``exportacao``)."""
    metadados = montar_metadados(args, ctx, sinal, frequencia_total, fs_efetiva, params, resultados)
    if args.exportar is not None:
        escritos = exportar_csv(args.exportar, resultados, metadados)
        log.info(f"Exportado: {len(escritos)} arquivo(s) com o prefixo '{args.exportar}' "
                 f"({', '.join(p.name for p in escritos[:4])}{', ...' if len(escritos) > 4 else ''})")
    if args.exportar_mat is not None:
        log.info(f"Exportado para o MATLAB/Octave: '{exportar_mat(args.exportar_mat, resultados, metadados)}' (estrutura 'sh')")


def _versao_do_codigo() -> str | None:
    """O commit do repositório, se o código estiver num (e o git existir): identifica o código que gerou o resultado."""
    import subprocess
    try:
        saida = subprocess.run(["git", "-C", str(Path(__file__).resolve().parent), "describe", "--always", "--dirty"],
                               capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return saida.stdout.strip() or None


def montar_metadados(args: argparse.Namespace, ctx: ContextoCaptura, sinal: SinalCarregado, frequencia_total: float,
                     fs_efetiva: float, params: ParametrosEspectro, resultados: dict) -> dict:
    """Tudo o que é preciso para reproduzir o resultado: a captura, a calibração, o método e as versões."""
    import datetime
    import platform
    cab = ctx.cabecalho
    n_por_canal = len(next(iter(sinal.por_canal_tensao.values())))
    calibracao = {}
    for canal in ctx.canais_exibir:
        idx = ctx.indice_no_ciclo(canal)
        sonda = ctx.sonda_id_do_canal(canal) or (str(ctx.overrides_perfil[canal]) if canal in ctx.overrides_perfil else "")
        calibracao[f"canal{canal}"] = {
            "grandeza": resultados["canais"][canal]["grandeza"], "unidade": resultados["canais"][canal]["unidade"],
            "faixa_v": ctx.faixas[idx], "faixa_do_cabecalho": ctx.faixas_confiaveis[idx], "ganho": ctx.ganhos[idx],
            "offset_v": ctx.offsets[idx], "formato": args.formato, "sonda": sonda,
            "correcao_de_sonda": bool(sonda) and not args.sem_correcao_sonda,
        }
    por_canal = {}
    for canal, r in resultados["canais"].items():
        resumo = {}
        if "fft" in r:
            resumo["fft"] = {"f0_hz": r["fft"]["f0_hz"], "n_ciclos": r["fft"]["n_ciclos"], "amostras": r["fft"]["amostras"],
                             "resolucao_hz": float(r["fft"]["f"][1] - r["fft"]["f"][0]) if len(r["fft"]["f"]) > 1 else None}
        if "welch" in r:
            resumo["welch"] = {"n_segmentos": r["welch"]["n_segmentos"]}
        if "harmonicos" in r:
            resumo["harmonicos"] = {"thd_pct": r["harmonicos"].thd_pct, "thdg_pct": r["harmonicos"].thdg_pct,
                                    "rms_total": r["harmonicos"].rms_total}
        por_canal[f"canal{canal}"] = resumo
    segmento_welch = tamanho_segmento_welch(fs_efetiva, args.resolucao_welch) if params.janela_welch else None
    try:
        import scipy
        versao_scipy = scipy.__version__
    except ImportError:
        versao_scipy = None
    return {
        "ferramenta": "SH-Analyzer adc_tool", "codigo": _versao_do_codigo(),
        "gerado_em": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "comando": " ".join(sys.argv), "python": platform.python_version(), "numpy": np.__version__,
        "scipy": versao_scipy,
        "captura": {
            "arquivo": str(args.arquivo.resolve()), "titulo": cab.titulo if cab else "",
            "descricao": cab.descricao if cab else "", "versao_cabecalho": cab.versao_cabecalho if cab else None,
            "timestamp_unix": cab.timestamp_unix if cab else None, "canais": ctx.canais,
            "frequencia_total_hz": frequencia_total, "frequencia_por_canal_hz": fs_efetiva,
            "frequencia_pedida_hz": cab.frequencia_hz if cab else None,
            "frequencia_pru_hz": cab.frequencia_pru_hz if cab else None,
            "origem_da_frequencia": ("-f" if args.frequencia is not None else "pedida (--fs-pedida)" if args.fs_pedida
                                     else "PRU (clock ÷ ticks)" if cab and cab.frequencia_pru_hz else "pedida"),
            "integridade": cab.problemas_integridade if cab else None,
        },
        "trecho": {"inicio_amostra_bruta": sinal.idx_inicio, "fim_amostra_bruta": sinal.idx_fim,
                   "amostras_por_canal": n_por_canal, "duracao_s": n_por_canal / fs_efetiva},
        "calibracao": calibracao,
        "filtros": {"passa_alta_hz": args.filtro_passa_alta, "passa_baixa_hz": args.filtro_passa_baixa,
                    "ordem": args.ordem_filtro if (args.filtro_passa_alta or args.filtro_passa_baixa) else None,
                    "tipo": "Butterworth em SOS, fase zero (sosfiltfilt)"},
        "espectro": {
            "modo": args.modo_espectro,
            "unidade_db": ("dB re 1 unidade do canal (amplitude de PICO de um tom)" if args.modo_espectro == "tom"
                           else "dB re 1 unidade²/Hz (densidade espectral de potência, um lado)"),
            "fft": None if params.janela_fft is None else {
                "janela": params.rotulo_fft, "sincronizada": "ciclos inteiros da fundamental",
                "busca_fundamental_hz": [args.freq_min, args.freq_max]},
            "welch": None if params.janela_welch is None else {
                "janela": params.rotulo_welch, "resolucao_hz": args.resolucao_welch,
                "sobreposicao": args.sobreposicao_welch, "amostras_por_segmento": segmento_welch,
                "enbw_bins": enbw_bins(params.janela_welch, segmento_welch, args.kaiser_beta)},
            "kaiser_beta": args.kaiser_beta if "Kaiser" in f"{params.rotulo_fft}{params.rotulo_welch}" else None,
            "bandas_hz": args.agrupar_bandas, "bandas_convencao": "(centro - L/2, centro + L/2], IEC 61000-4-7",
            "picos": None if args.picos is None else {
                "limiar_db": args.picos, "faixa_hz": [args.freq_min_picos, params.freq_max_picos],
                "distancia_minima_hz": args.distancia_minima_picos, "refino": "interpolação parabólica em dB"},
        },
        "harmonicos": None if args.harmonicos is None else {
            "ordem_maxima": args.harmonicos, "fase": "referencial seno, relativa à fundamental (theta_h - h*theta_1)",
            "grupo": "IEC 61000-4-7 (bins até meio espaçamento; bordas com metade da potência)"},
        "bandas_iec": None if not args.bandas_iec else {
            "metodo": "IEC 61000-4-7 anexo B: janelas de 200 ms sem lacunas, retangular, bins de 5 Hz, "
                      "bandas de 200 Hz (b-95..b+100 Hz)",
            "freq_min_hz": args.bandas_iec_min, "freq_max_hz": args.bandas_iec_max,
            "janelas": ("10/12 ciclos sincronizados à fundamental (IEC 61000-4-30), bordas arredondadas à amostra"
                        if args.bandas_iec_sincronizar else "200 ms fixos"),
            "agregacao": ("150/180 ciclos (~3 s) e 10 min (a partir do início do trecho, não alinhados ao UTC); "
                          "cada valor = RMS das janelas do intervalo; só intervalos completos"
                          if args.bandas_iec_agregar else None),
            "estatisticas": "rms das janelas, máximo, percentil 95, mínimo (e das séries agregadas, se houver)"},
        "resultados_por_canal": por_canal,
    }
