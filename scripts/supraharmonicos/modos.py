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
from dataclasses import dataclass

import numpy as np

from .amostras import (
    carregar_amostras,
    converter_para_tensao,
    detectar_tipo_arquivo,
    selecionar_intervalo,
)
from .canais import desintercalar
from .constantes import GRANDEZA_CORRENTE, GRANDEZA_TEMPERATURA
from .contexto import ContextoCaptura
from .conversao import converter_arquivo
from .erros import ErroSHAN, ErroUso
from .espectro import (
    agrupar_em_bandas,
    calcular_espectro,
    calcular_espectro_welch,
    encontrar_picos_espectro,
    resolver_nome_janela,
    rotulo_janela_completo,
)
from .filtros import aplicar_filtro_digital, validar_corte_filtro
from .fundamental import recortar_ciclos_inteiros
from .hdf5 import exportar_hdf5
from .sonda import (
    aplicar_correcao_sonda,
    conferir_calibracao_perfil,
    resolver_perfil_canal,
)

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
    """Parâmetros de --fft/--welch já validados."""
    nome_janela: str | None            # nome canônico (None se não há espectro)
    rotulo_janela: str | None
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

    # Falha rápido se o matplotlib não está instalado (antes de ler a captura).
    from . import plotagem

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

    infos_espectro = {canal: {} for canal in ctx.canais_exibir} if (usa_fft or usa_welch) else None
    if usa_fft:
        _analisar_fft(args, ctx, por_canal_tensao, fs_efetiva, params, infos_espectro)
    if usa_welch:
        _analisar_welch(args, ctx, por_canal_tensao, fs_efetiva, params, infos_espectro)

    if args.agrupar_bandas is not None:
        rotulo_espectro_y = f"Nível por banda de {args.agrupar_bandas:g} Hz (dBV)"
    else:
        rotulo_espectro_y = "Magnitude (dBV)" if args.modo_espectro == "tom" else "PSD (dB re V²/Hz)"
    limite_inferior_db = -100.0 if (args.modo_espectro == "tom" and args.agrupar_bandas is None) else None

    # Título do cabeçalho da captura (--titulo no firmware) enriquece o título
    # do gráfico -- puramente cosmético, não afeta nenhum cálculo.
    cabecalho = ctx.cabecalho
    titulo_exibicao = (
        f"{cabecalho.titulo} ({args.arquivo.name})"
        if (cabecalho is not None and cabecalho.titulo)
        else args.arquivo.name
    )

    plotagem.plotar_multicanal(
        por_canal_tensao, fs_efetiva, sinal.idx_inicio, infos_espectro, titulo_exibicao,
        args.saida, args.layout_canais, rotulo_espectro_y, limite_inferior_db,
        grandeza_por_canal_exibir,
    )


def _resolver_frequencia(args: argparse.Namespace, ctx: ContextoCaptura) -> float:
    """-f/--frequencia: explícita (CLI) > cabeçalho da captura > obrigatória."""
    if args.frequencia is not None:
        return args.frequencia
    if ctx.cabecalho is not None and ctx.cabecalho.frequencia_hz > 0:
        frequencia_total = float(ctx.cabecalho.frequencia_hz)
        log.info(f"usando a frequência: {frequencia_total:g} Hz")
        return frequencia_total
    raise ErroUso(
        "-f/--frequencia é obrigatório no modo de plotagem (nenhum "
        "cabeçalho com essa informação foi encontrado em 'arquivo')."
    )


def _validar_parametros(args: argparse.Namespace, fs_efetiva: float,
                        usa_fft: bool, usa_welch: bool) -> ParametrosEspectro:
    """Valida janela, filtros, bandas, Welch e picos (nenhum I/O de captura)."""
    nome_janela = resolver_nome_janela(args.janela) if (usa_fft or usa_welch) else None
    rotulo_janela = rotulo_janela_completo(nome_janela, args.kaiser_beta) if nome_janela else None

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

    freq_max_picos = None
    if args.picos is not None:
        freq_max_picos = args.freq_max_picos if args.freq_max_picos is not None else fs_efetiva / 2.0
        if args.freq_min_picos >= freq_max_picos:
            raise ErroSHAN("--freq-min-picos precisa ser menor que --freq-max-picos.")

    return ParametrosEspectro(nome_janela, rotulo_janela, freq_max_picos)


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
    bruto, idx_inicio, idx_fim, total = selecionar_intervalo(amostras, args.inicio, args.fim)

    por_canal_bruto = desintercalar(bruto, ctx.canais, ctx.canais_exibir)
    por_canal_tensao: dict[int, np.ndarray] = {}
    for canal in ctx.canais_exibir:
        idx = ctx.indice_no_ciclo(canal)
        por_canal_tensao[canal] = converter_para_tensao(
            por_canal_bruto[canal], ctx.faixas[idx], ctx.ganhos[idx], args.formato, ctx.offsets[idx]
        )
    return SinalCarregado(por_canal_tensao, idx_inicio, idx_fim, total, tipo_arquivo)


def aplicar_correcao_sondas(args: argparse.Namespace, ctx: ContextoCaptura,
                            por_canal_tensao: dict[int, np.ndarray],
                            fs_efetiva: float) -> dict[int, int]:
    """Correção dependente de frequência, canal a canal (modifica 'por_canal_tensao').

    Aplicada ANTES do filtro Butterworth opcional do usuário e de qualquer
    análise espectral, para que --fft/--welch/--picos/plot já operem sobre o
    sinal corrigido (ver sonda.aplicar_correcao_sonda). Devolve a grandeza de
    cada canal exibido (o gráfico usa para rotular os eixos)."""
    grandeza_por_canal_exibir = {canal: ctx.grandeza_do_canal(canal) for canal in ctx.canais_exibir}
    for canal in ctx.canais_exibir:
        grandeza = grandeza_por_canal_exibir[canal]
        sonda_id = ctx.sonda_id_do_canal(canal)
        # Uma sonda REGISTRADA (id no cabeçalho ou --sonda-perfil) vale para
        # qualquer grandeza de frequência (corrente, e também tensão -- ex.:
        # divisor/ponta com banda limitada). Corrente SEM sonda só avisa.
        sonda_registrada = bool(sonda_id) or canal in ctx.overrides_perfil
        if grandeza == GRANDEZA_TEMPERATURA:
            if sonda_registrada:
                log.warning(
                    f"canal {canal} é de temperatura -- a sonda "
                    f"registrada ('{sonda_id or ctx.overrides_perfil[canal]}') "
                    f"não é aplicada (correção por frequência não se aplica "
                    f"a temperatura; perfis 'polinomio'/'tabela' ainda não "
                    f"existem)."
                )
            continue
        if grandeza != GRANDEZA_CORRENTE and not sonda_registrada:
            continue
        prefixo = f"  Canal {canal}: " if ctx.num_canais > 1 else "  "
        if args.sem_correcao_sonda:
            log.info(f"{prefixo}--sem-correcao-sonda ativo -- usando só --ganho escalar (sem correção por frequência).")
            continue
        perfil = resolver_perfil_canal(canal, sonda_id, ctx.overrides_perfil, ctx.sondas_dir)
        if perfil is None:
            log.warning(
                f"canal {canal} é de corrente mas não tem sonda/perfil resolvido -- "
                f"usando só --ganho escalar (sem correção por frequência). "
                f"Registre a sonda na captura (--sonda em ler_adc) ou use "
                f"--sonda-perfil {canal}:ARQUIVO."
            )
            continue
        idx_canal = ctx.indice_no_ciclo(canal)
        conferir_calibracao_perfil(perfil, canal, args.formato, ctx.faixas[idx_canal], ctx.ganhos[idx_canal],
                                   faixa_confiavel=ctx.faixas_confiaveis[idx_canal])
        por_canal_tensao[canal] = aplicar_correcao_sonda(por_canal_tensao[canal], fs_efetiva, perfil)
        log.info(f"{prefixo}correção de sonda aplicada (perfil '{perfil.id}', {perfil.caminho})")
    return grandeza_por_canal_exibir


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
                  params: ParametrosEspectro, infos_espectro: dict) -> None:
    """--fft: FFT única sobre um número inteiro de ciclos da fundamental."""
    n_ciclos_pedido = args.fft if args.fft > 0 else None
    for canal in ctx.canais_exibir:
        sinal_fft, idx_i_local, idx_f_local, f0, n_ciclos = recortar_ciclos_inteiros(
            por_canal_tensao[canal], fs_efetiva, args.freq_min, args.freq_max, n_ciclos_pedido
        )
        freqs, amplitude_db = calcular_espectro(
            sinal_fft, fs_efetiva, params.nome_janela, args.kaiser_beta, args.modo_espectro
        )

        if args.picos is not None:
            picos = encontrar_picos_espectro(
                freqs, amplitude_db, args.freq_min_picos, params.freq_max_picos,
                args.picos, args.distancia_minima_picos
            )
            _registrar_picos(canal, "ciclo", picos, ctx.num_canais)

        if args.agrupar_bandas is not None:
            freqs, amplitude_db = agrupar_em_bandas(freqs, amplitude_db, args.agrupar_bandas, args.modo_espectro)

        if ctx.num_canais == 1:
            log.info(f"FFT (ciclo): f0 = {f0:.3f} Hz | {n_ciclos} ciclo(s) completo(s) | "
                     f"{len(sinal_fft)} amostras (locais {idx_i_local}..{idx_f_local}) | "
                     f"janela: {params.rotulo_janela} | modo: {args.modo_espectro}")
        else:
            log.info(f"  Canal {canal} FFT (ciclo): f0 = {f0:.3f} Hz | {n_ciclos} ciclo(s) | "
                     f"{len(sinal_fft)} amostras (locais {idx_i_local}..{idx_f_local})")

        infos_espectro[canal]["ciclo"] = {
            "freqs": freqs, "amplitude_db": amplitude_db, "f0": f0, "n_ciclos": n_ciclos,
            "idx_inicio_local": idx_i_local, "idx_fim_local": idx_f_local, "janela": params.rotulo_janela,
        }


def _analisar_welch(args: argparse.Namespace, ctx: ContextoCaptura,
                    por_canal_tensao: dict[int, np.ndarray], fs_efetiva: float,
                    params: ParametrosEspectro, infos_espectro: dict) -> None:
    """--welch: espectro médio por segmentação (supraharmônicos)."""
    for canal in ctx.canais_exibir:
        freqs, amplitude_db, n_segmentos = calcular_espectro_welch(
            por_canal_tensao[canal], fs_efetiva, params.nome_janela, args.kaiser_beta,
            args.resolucao_welch, args.sobreposicao_welch, args.modo_espectro,
        )

        if args.picos is not None:
            picos = encontrar_picos_espectro(
                freqs, amplitude_db, args.freq_min_picos, params.freq_max_picos,
                args.picos, args.distancia_minima_picos
            )
            _registrar_picos(canal, "welch", picos, ctx.num_canais)

        if args.agrupar_bandas is not None:
            freqs, amplitude_db = agrupar_em_bandas(freqs, amplitude_db, args.agrupar_bandas, args.modo_espectro)

        prefixo = f"  Canal {canal} " if ctx.num_canais > 1 else ""
        log.info(f"{prefixo}Welch: {n_segmentos} segmento(s) médios | "
                 f"resolução {args.resolucao_welch:g} Hz | modo: {args.modo_espectro}")

        infos_espectro[canal]["welch"] = {
            "freqs": freqs, "amplitude_db": amplitude_db,
            "n_segmentos": n_segmentos, "janela": params.rotulo_janela,
        }


def _registrar_picos(canal: int, metodo: str, picos: list[dict], num_canais: int) -> None:
    prefixo = f"  Canal {canal} " if num_canais > 1 else "  "
    if not picos:
        log.info(f"{prefixo}[{metodo}] nenhum pico acima do limiar encontrado.")
        return
    for pico in picos:
        log.info(f"{prefixo}[{metodo}] pico: {pico['frequencia_hz']:.2f} Hz @ {pico['amplitude_db']:.2f} dB")
