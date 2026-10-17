"""Linha de comando do ``medir_captura``: lê capturas ``.bin``, mede e relata.

Borda do programa (ver ``cli_adc_tool`` para a convenção): liga o logging,
traduz ``ErroSHAN`` -> ``Erro: ...`` (código 1) e ``ErroUso`` -> ``parser.error``
(código 2). As métricas estão em ``metricas_captura``; aqui só se resolve o
contexto da captura (canais, faixa, ganho, frequência -- a mesma hierarquia do
``adc_tool``), se formata o relatório e se acrescenta uma linha por canal ao CSV
(``--csv``), para montar as tabelas do relatório a partir de várias capturas.
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .amostras import carregar_amostras_bin, converter_para_tensao
from .cabecalho import CabecalhoArquivo, conferir_consistencia_cabecalho, contar_amostras_arquivo_bin
from .canais import analisar_lista_canais, desintercalar, validar_subconjunto_canais
from .constantes import NOMES_GRANDEZA, UNIDADE_GRANDEZA
from .contexto import ContextoCaptura, resolver_contexto
from .erros import ErroSHAN, ErroUso
from .metricas_captura import (
    HARMONICOS_PADRAO,
    Acoplamento,
    Basicas,
    Continuidade,
    Espectro,
    analisar_espectro,
    calcular_acoplamento,
    calcular_basicas,
    fracao_saturada,
    projetar_tom,
    verificar_continuidade,
)
from .modos import aplicar_correcao_sondas
from .registro import configurar_logging_cli

log = logging.getLogger(__name__)

MAX_AMOSTRAS_PADRAO = 1 << 22          # por canal (≈ 10 s a 400 kS/s); mais que isso só custa memória
SATURACAO_AVISO = 5e-4                 # fração de amostras no fundo de escala acima da qual as métricas perdem o sentido

COLUNAS_CSV = [
    "arquivo", "rotulo", "canal", "grandeza", "unidade", "fs_nominal_hz", "fs_pru_hz", "fs_canal_hz",
    "amostras_por_canal", "duracao_s", "media", "rms_ca", "pico_a_pico", "minimo", "maximo", "saturacao_pct",
    "ruido_rms_lsb", "densidade_ruido_por_rthz", "freq_tom_hz", "amplitude_pico", "amplitude_rms",
    "thd_db", "thd_pct", "sinad_db", "snr_db", "enob_bits", "sfdr_dbc", "freq_espurio_hz", "ordem_espurio",
    "salto_max_amostras", "saltos_acima_do_limite", "variacao_amplitude_pct",
    "diafonia_db", "atraso_medido_us", "atraso_esperado_us",
    "correcao_sonda", "referencia_rms", "erro_amplitude_pct", "referencia_freq_hz", "erro_freq_ppm",
]


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="medir_captura.py",
        description=(
            "Mede capturas .bin do SH-Analyzer e imprime números para o relatório: DC, RMS, "
            "ruído (densidade e LSB), tom (frequência/amplitude), harmônicos, THD, SINAD, SNR, "
            "ENOB, SFDR, continuidade (amostras perdidas) e acoplamento entre canais. Aceita "
            "vários arquivos; --csv acrescenta uma linha por canal medido."
        ),
        epilog=(
            "Exemplos:\n"
            "  # Senoide de um gerador: tudo sobre o tom (a frequência é achada sozinha)\n"
            "  %(prog)s senoide_10k.bin --rotulo 'T3 senoide 10 kHz' --csv resultados.csv\n"
            "\n"
            "  # Entrada em curto (só ruído), vários canais, vários arquivos\n"
            "  %(prog)s curto_*.bin --sem-tom --csv resultados.csv\n"
            "\n"
            "  # Capturas antigas, sem cabeçalho\n"
            "  %(prog)s antiga.bin -f 102400 --canais 0,1\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("arquivos", type=Path, nargs="+", metavar="ARQUIVO.bin", help="Capturas a medir.")
    parser.add_argument(
        "-f", "--frequencia", type=float, default=None, metavar="HZ",
        help="Frequência de amostragem TOTAL (Hz). Sem a flag: a do cabeçalho do .bin (obrigatória sem cabeçalho)."
    )
    parser.add_argument(
        "--fs-pru", action="store_true",
        help="Usa como frequência de amostragem a que o PRU de fato gera, pru_clock/sample_period_ticks "
             "(gravados no cabeçalho), em vez da pedida. Difere dela porque os ticks são inteiros "
             "(ex.: 200 MHz/102400 = 1953,125 -> 1953 ticks -> +64 ppm)."
    )
    parser.add_argument("--canais", type=str, default=None, metavar="LISTA",
                        help="Canais no arquivo (padrão: os do cabeçalho; sem cabeçalho, '1').")
    parser.add_argument("--canais-medir", type=str, default=None, metavar="LISTA",
                        help="Subconjunto de --canais a medir (padrão: todos).")
    parser.add_argument("--formato", choices=["int16", "uint16"], default="uint16",
                        help="Código do ADC: 'uint16' (unipolar, padrão) ou 'int16' (bipolar).")
    parser.add_argument("--faixa", type=str, default="10.24", metavar="VOLTS",
                        help="Faixa (fundo de escala pico a pico) do ADC em V (padrão 10.24); valor único ou lista por canal.")
    parser.add_argument("--ganho", type=str, default="1.0", metavar="FATOR",
                        help="Ganho do sensor/PCB (padrão 1.0); valor único ou lista por canal.")
    parser.add_argument("--offset", type=str, default=None, metavar="VOLTS",
                        help="DC subtraído antes do ganho (padrão: faixa/2 para uint16, 0 para int16).")
    parser.add_argument("--freq", type=float, default=None, metavar="HZ",
                        help="Frequência aproximada do tom (procura só em ±10%%); necessária se houver "
                             "interferência mais forte que o tom (ex.: 60 Hz da rede).")
    parser.add_argument("--sem-tom", action="store_true",
                        help="Não procura tom: só estatísticas e piso de ruído (entrada em curto/aberta).")
    parser.add_argument("--harmonicos", type=int, default=HARMONICOS_PADRAO, metavar="N",
                        help=f"Até que ordem somar harmônicos no THD (padrão {HARMONICOS_PADRAO}). "
                             "Os que passam de Nyquist são medidos na frequência dobrada (alias).")
    parser.add_argument("--inicio", type=int, default=0, metavar="N", help="Primeira amostra POR CANAL a analisar (padrão 0).")
    parser.add_argument("--max-amostras", type=int, default=MAX_AMOSTRAS_PADRAO, metavar="N",
                        help=f"Amostras por canal a analisar (padrão {MAX_AMOSTRAS_PADRAO}); limita a memória.")
    grupo_sonda = parser.add_argument_group(
        "Sonda de corrente",
        "Canais de corrente com sonda registrada no cabeçalho (ou indicada aqui) são corrigidos pelo perfil "
        "antes das métricas, como no adc_tool.py: amplitude/frequência saem na grandeza física REAL. Ruído, "
        "SINAD e ENOB de um canal corrigido não caracterizam o ADC -- para isso use --sem-correcao-sonda.",
    )
    grupo_sonda.add_argument("--grandeza", type=str, default=None, metavar="C:G[,...]",
                             help="Grandeza de cada canal ('0:tensao,1:corrente'); padrão: a do cabeçalho.")
    grupo_sonda.add_argument("--sondas-dir", type=Path, default=None, metavar="DIR",
                             help="Pasta dos perfis '<id>.json' (padrão: scripts/sondas/).")
    grupo_sonda.add_argument("--sonda-perfil", type=str, default=None, metavar="C:ARQUIVO[,...]",
                             help="Perfil (.json) de um canal, 'canal:arquivo'; vence o id do cabeçalho.")
    grupo_sonda.add_argument("--sem-correcao-sonda", action="store_true",
                             help="Não aplica a correção de sonda (só --ganho escalar).")
    grupo_ref = parser.add_argument_group(
        "Comparação com o osciloscópio",
        "Dão o erro do ADC em relação a um instrumento de referência. Valem para TODOS os canais medidos "
        "que tenham tom: com mais de um canal, escolha um com --canais-medir.",
    )
    grupo_ref.add_argument("--referencia-rms", type=float, default=None, metavar="VALOR",
                           help="Valor RMS do tom lido no osciloscópio, NA MESMA UNIDADE do canal (V, ou A se for "
                                "corrente corrigida). Imprime/grava o erro de amplitude em %%.")
    grupo_ref.add_argument("--referencia-freq", type=float, default=None, metavar="HZ",
                           help="Frequência do tom lida no osciloscópio/contador. Imprime/grava o erro em ppm "
                                "(= erro da frequência de amostragem, com o sinal trocado).")
    parser.add_argument("--rotulo", type=str, default=None, metavar="TEXTO",
                        help="Nome do teste, gravado no CSV (padrão: o título do cabeçalho).")
    parser.add_argument("--csv", type=Path, default=None, metavar="ARQUIVO",
                        help="Acrescenta uma linha por canal medido (cria o arquivo e o cabeçalho se preciso).")
    return parser


# ---------------------------------------------------------------------------
# Contexto e leitura
# ---------------------------------------------------------------------------

def _frequencias(args: argparse.Namespace, cabecalho: CabecalhoArquivo | None) -> tuple[float, float | None]:
    """(fs_total usada, fs_total do PRU ou None). Hierarquia: --frequencia > cabeçalho; --fs-pru escolhe a do PRU."""
    fs_pru = None
    if cabecalho is not None and cabecalho.sample_period_ticks > 0 and cabecalho.pru_clock_hz > 0:
        fs_pru = cabecalho.pru_clock_hz / cabecalho.sample_period_ticks
    if args.fs_pru:
        if fs_pru is None:
            raise ErroSHAN("--fs-pru precisa do cabeçalho da captura (pru_clock e sample_period_ticks).")
        return fs_pru, fs_pru
    if args.frequencia is not None:
        return args.frequencia, fs_pru
    if cabecalho is not None and cabecalho.frequencia_hz > 0:
        return float(cabecalho.frequencia_hz), fs_pru
    raise ErroSHAN("sem cabeçalho com a frequência de amostragem: informe -f/--frequencia (Hz, total).")


def _ler_canais(caminho: Path, args: argparse.Namespace, ctx: ContextoCaptura,
                canais_medir: list[int]) -> tuple[dict[int, np.ndarray], dict[int, float]]:
    """({canal: sinal na unidade física}, {canal: fração saturada}) das amostras pedidas (--inicio/--max-amostras)."""
    amostras = carregar_amostras_bin(caminho, args.formato, offset=ctx.offset_amostras)
    k = ctx.num_canais
    ini = max(0, args.inicio) * k
    fim = min(len(amostras), ini + args.max_amostras * k)
    if fim - ini < k:
        raise ErroSHAN(f"--inicio {args.inicio} está além do fim da captura ({len(amostras) // k} amostras por canal).")
    bruto = np.asarray(amostras[ini:fim])
    por_canal = desintercalar(bruto, ctx.canais, canais_medir)
    sinais, saturacao = {}, {}
    for canal in canais_medir:
        i = ctx.indice_no_ciclo(canal)
        saturacao[canal] = fracao_saturada(por_canal[canal], args.formato)
        sinais[canal] = converter_para_tensao(por_canal[canal], ctx.faixas[i], ctx.ganhos[i], args.formato, ctx.offsets[i])
    return sinais, saturacao


@dataclass
class ResultadoCanal:
    canal: int
    grandeza: str
    unidade: str
    lsb: float
    saturacao: float
    corrigido: bool
    basicas: Basicas
    espectro: Espectro
    continuidade: Continuidade | None
    comparacao: dict[str, str]          # colunas do CSV da comparação com o osciloscópio ({} sem --referencia-*)


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------

def _nivel(db: float, casas: int = 1) -> str:
    return "abaixo do piso de ruído" if math.isinf(db) else f"{db:.{casas}f} dB"


def _campo(nome: str, valor: str) -> str:
    return f"  {nome:<22}: {valor}"


def _formatar_canal(canal: int, unidade: str, grandeza: str, b: Basicas, e: Espectro, saturacao: float,
                    cont: Continuidade | None, lsb: float, fs_canal: float, procurou_tom: bool) -> list[str]:
    linhas = [
        f"Canal {canal} ({grandeza}, {unidade}) -- {b.n_amostras} amostras ({b.duracao_s:.3f} s), "
        f"fs do canal {fs_canal:g} Hz, resolução espectral {e.resolucao_hz:.4g} Hz",
        _campo("DC (média)", f"{b.media:+.6g} {unidade}"),
        _campo("RMS CA", f"{b.rms_ac:.6g} {unidade} ({b.rms_ac_lsb:.2f} LSB)"),
        _campo("pico a pico", f"{b.pico_a_pico:.6g} {unidade}  (mín {b.minimo:+.6g} / máx {b.maximo:+.6g})"),
        _campo("saturação do ADC", f"{saturacao * 100:.4f} % das amostras"),
        _campo("densidade de ruído", f"{e.densidade_ruido * 1e9:.4g} n{unidade}/√Hz (mediana do espectro)"),
        _campo("LSB", f"{lsb:.4g} {unidade} (ruído de quantização ideal: {lsb / math.sqrt(12):.3g} {unidade} RMS)"),
    ]
    if not e.tem_tom:
        if procurou_tom:
            linhas.append(_campo("tom", "nenhum pico 20 dB acima do piso (se o tom é fraco, indique --freq)"))
    else:
        linhas.append(_campo("tom", f"{e.freq_tom_hz:.4f} Hz | pico {e.amplitude_pico:.6g} {unidade} | RMS {e.amplitude_rms:.6g} {unidade}"))
        linhas.append(_campo(f"THD (H2..H{e.harmonicos[-1].ordem})", f"{_nivel(e.thd_db)} ({e.thd_pct:.4g} %)"))
        for h in e.harmonicos:
            if h.nivel_dbc is None or math.isinf(h.nivel_dbc):
                continue
            alias = "  [alias: o harmônico real está acima de Nyquist]" if h.aliasado else ""
            linhas.append(f"      H{h.ordem:<2} em {h.freq_hz:>11.2f} Hz : {h.nivel_dbc:7.1f} dBc (pico {h.amplitude:.4g} {unidade}){alias}")
        nao_separaveis = [f"H{h.ordem}" for h in e.harmonicos if h.nivel_dbc is None]
        if nao_separaveis:
            linhas.append(f"      não separáveis da fundamental/DC: {', '.join(nao_separaveis)}")
        linhas.append(_campo("SINAD / SNR / ENOB", f"{e.sinad_db:.1f} dB / {e.snr_db:.1f} dB / {e.enob_bits:.2f} bits"))
        linhas.append(_campo("ruído RMS (sem tom)", f"{e.ruido_rms:.4g} {unidade} ({e.ruido_rms / lsb:.2f} LSB)"))
        if not math.isnan(e.sfdr_dbc):
            origem = f"= H{e.ordem_espurio}" if e.ordem_espurio else "não é harmônico"
            so_ruido = "  [≈ só ruído]" if e.espurio_sobre_piso_db < 12.0 else ""
            linhas.append(_campo("SFDR", f"{e.sfdr_dbc:.1f} dBc (maior espúrio em {e.freq_espurio_hz:.1f} Hz, {origem}){so_ruido}"))
    if cont is None:
        if e.tem_tom:
            linhas.append(_campo("continuidade", "não verificada (captura curta demais para 4 segmentos)"))
    else:
        veredito = "OK" if cont.saltos_acima_do_limite == 0 else f"DESCONTINUIDADE ({cont.saltos_acima_do_limite} evento(s))"
        linhas.append(_campo(
            "continuidade",
            f"{veredito} -- maior salto de fase {cont.salto_max_amostras:.3f} amostra(s) (perto da amostra "
            f"{cont.indice_salto_max}); {cont.segmentos} segmentos de {cont.amostras_por_segmento}; "
            f"amplitude varia {cont.variacao_amplitude_pct:.3f} %",
        ))
    return linhas


def _formatar_acoplamento(acopl: list[Acoplamento], freq_hz: float) -> list[str]:
    linhas = [f"Acoplamento entre canais no tom de {freq_hz:.2f} Hz (agressor = canal de maior amplitude):"]
    for a in acopl:
        linhas.append(
            f"  canal {a.canal} vs {a.canal_agressor}: {a.diafonia_db:.1f} dB (diafonia, se o canal estava em curto) | "
            f"atraso {a.atraso_medido_us:+.3f} µs (esperado pela multiplexação: {a.atraso_esperado_us:+.3f} µs; "
            f"só vale se o MESMO sinal está nos dois)"
        )
    return linhas


def _num(v: float | None) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return "-inf" if v == -math.inf else f"{v:.9g}"


def _linha_csv(arquivo: Path, rotulo: str, fs_nominal: float, fs_pru: float | None, fs_canal: float,
               r: ResultadoCanal, acopl: Acoplamento | None) -> dict[str, str]:
    b, e, cont = r.basicas, r.espectro, r.continuidade
    linha = {
        "arquivo": arquivo.name, "rotulo": rotulo, "canal": str(r.canal), "grandeza": r.grandeza, "unidade": r.unidade,
        "fs_nominal_hz": _num(fs_nominal), "fs_pru_hz": _num(fs_pru), "fs_canal_hz": _num(fs_canal),
        "amostras_por_canal": str(b.n_amostras), "duracao_s": _num(b.duracao_s), "media": _num(b.media),
        "rms_ca": _num(b.rms_ac), "pico_a_pico": _num(b.pico_a_pico), "minimo": _num(b.minimo), "maximo": _num(b.maximo),
        "saturacao_pct": _num(r.saturacao * 100.0), "ruido_rms_lsb": _num(e.ruido_rms / r.lsb),
        "densidade_ruido_por_rthz": _num(e.densidade_ruido), "correcao_sonda": "sim" if r.corrigido else "",
    }
    if e.tem_tom:
        linha.update({
            "freq_tom_hz": _num(e.freq_tom_hz), "amplitude_pico": _num(e.amplitude_pico), "amplitude_rms": _num(e.amplitude_rms),
            "thd_db": _num(e.thd_db), "thd_pct": _num(e.thd_pct), "sinad_db": _num(e.sinad_db), "snr_db": _num(e.snr_db),
            "enob_bits": _num(e.enob_bits), "sfdr_dbc": _num(e.sfdr_dbc), "freq_espurio_hz": _num(e.freq_espurio_hz),
            "ordem_espurio": "" if e.ordem_espurio is None else str(e.ordem_espurio),
        })
        linha.update(r.comparacao)
    if cont is not None:
        linha.update({"salto_max_amostras": _num(cont.salto_max_amostras),
                      "saltos_acima_do_limite": str(cont.saltos_acima_do_limite),
                      "variacao_amplitude_pct": _num(cont.variacao_amplitude_pct)})
    if acopl is not None:
        linha.update({"diafonia_db": _num(acopl.diafonia_db), "atraso_medido_us": _num(acopl.atraso_medido_us),
                      "atraso_esperado_us": _num(acopl.atraso_esperado_us)})
    return {coluna: linha.get(coluna, "") for coluna in COLUNAS_CSV}


def _acrescentar_csv(caminho: Path, linhas: list[dict[str, str]]) -> None:
    existe = caminho.exists() and caminho.stat().st_size > 0
    if existe:
        with open(caminho, newline="", encoding="utf-8") as f:
            primeira = f.readline().strip().split(",")
        if primeira != COLUNAS_CSV:
            raise ErroSHAN(
                f"'{caminho}' já existe com outras colunas (versão antiga desta ferramenta, ou outro arquivo). "
                f"Use outro nome em --csv para não misturar."
            )
    with open(caminho, "a", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUNAS_CSV)
        if not existe:
            escritor.writeheader()
        escritor.writerows(linhas)


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------

def _comparar_referencia(e: Espectro, args: argparse.Namespace, unidade: str) -> tuple[list[str], dict[str, str]]:
    """Erro do tom medido contra --referencia-rms / --referencia-freq: (linhas do relatório, colunas do CSV)."""
    linhas, colunas = [], {}
    if args.referencia_rms is not None:
        erro = (e.amplitude_rms - args.referencia_rms) / args.referencia_rms * 100.0
        colunas.update({"referencia_rms": _num(args.referencia_rms), "erro_amplitude_pct": _num(erro)})
        linhas.append(_campo("vs referência (amplitude)", f"{erro:+.3f} % (ADC {e.amplitude_rms:.6g} {unidade} RMS "
                                                         f"contra {args.referencia_rms:.6g} {unidade} RMS do instrumento)"))
    if args.referencia_freq is not None:
        erro = (e.freq_tom_hz - args.referencia_freq) / args.referencia_freq * 1e6
        colunas.update({"referencia_freq_hz": _num(args.referencia_freq), "erro_freq_ppm": _num(erro)})
        linhas.append(_campo("vs referência (frequência)", f"{erro:+.1f} ppm (ADC {e.freq_tom_hz:.4f} Hz contra {args.referencia_freq:.4f} Hz)"))
    return linhas, colunas


def _medir_canal(canal: int, sinal: np.ndarray, corrigido: bool, saturacao: float, args: argparse.Namespace,
                 ctx: ContextoCaptura, fs_canal: float) -> ResultadoCanal:
    i = ctx.indice_no_ciclo(canal)
    codigo = ctx.grandeza_do_canal(canal)
    grandeza, unidade = NOMES_GRANDEZA.get(codigo, "tensão"), UNIDADE_GRANDEZA.get(codigo, "V")
    fundo_escala = ctx.faixas[i] * ctx.ganhos[i]
    lsb = fundo_escala / 65536.0
    if saturacao > SATURACAO_AVISO:
        log.warning(f"canal {canal}: {saturacao * 100:.3f} % das amostras no fundo de escala -- a captura saturou; "
                    f"amplitude, THD e SINAD deste canal NÃO são confiáveis. Reduza a amplitude e meça de novo.")
    basicas = calcular_basicas(sinal, fs_canal, lsb)
    espectro = analisar_espectro(sinal, fs_canal, args.freq, args.harmonicos, fundo_escala, procurar_tom=not args.sem_tom)
    cont = verificar_continuidade(sinal, fs_canal, espectro.freq_tom_hz) if espectro.tem_tom else None
    linhas = _formatar_canal(canal, unidade, grandeza, basicas, espectro, saturacao, cont, lsb, fs_canal, not args.sem_tom)
    comparacao: dict[str, str] = {}
    if espectro.tem_tom:
        extras, comparacao = _comparar_referencia(espectro, args, unidade)
        linhas += extras
    elif args.referencia_rms is not None or args.referencia_freq is not None:
        log.warning(f"canal {canal}: sem tom, então não há o que comparar com --referencia-*.")
    if corrigido:
        linhas.append("  (canal corrigido pelo perfil da sonda: ruído, SINAD e ENOB acima NÃO descrevem o ADC -- "
                      "para isso, meça com --sem-correcao-sonda)")
    for linha in linhas:
        log.info(linha)
    return ResultadoCanal(canal, grandeza, unidade, lsb, saturacao, corrigido, basicas, espectro, cont, comparacao)


def _anunciar_frequencias(args: argparse.Namespace, ctx: ContextoCaptura, fs_total: float, fs_pru: float | None) -> float:
    """Imprime a linha de frequências e devolve a frequência total PEDIDA (a do cabeçalho)."""
    nominal = float(ctx.cabecalho.frequencia_hz) if ctx.cabecalho is not None and ctx.cabecalho.frequencia_hz else fs_total
    if fs_pru is None:
        origem = f"{fs_total:g} Hz"
    elif args.fs_pru:
        origem = f"{fs_total:.2f} Hz (a gerada pelo PRU; a pedida era {nominal:g} Hz)"
    else:
        origem = (f"{fs_total:g} Hz (o PRU gera {fs_pru:.2f} Hz = {(fs_pru - fs_total) / fs_total * 1e6:+.1f} ppm; "
                  f"--fs-pru analisa com ela)")
    log.info(f"canais {ctx.canais} | fs total {origem} | Nyquist por canal {fs_total / ctx.num_canais / 2:g} Hz")
    return nominal


def _medir_acoplamento(sinais: dict[int, np.ndarray], resultados: list[ResultadoCanal], ctx: ContextoCaptura,
                       fs_canal: float, fs_total: float) -> dict[int, Acoplamento]:
    com_tom = [r.espectro for r in resultados if r.espectro.tem_tom]
    if len(sinais) < 2 or not com_tom:
        return {}
    base = max(com_tom, key=lambda e: e.amplitude_pico)
    tons = {c: projetar_tom(sinal, fs_canal, base.freq_tom_hz) for c, sinal in sinais.items()}
    posicoes = {c: ctx.indice_no_ciclo(c) for c in sinais}
    acopl = calcular_acoplamento(tons, posicoes, base.freq_tom_hz, fs_total)
    for linha in _formatar_acoplamento(acopl, base.freq_tom_hz):
        log.info(linha)
    return {a.canal: a for a in acopl}


def medir_arquivo(caminho: Path, args: argparse.Namespace) -> list[dict[str, str]]:
    """Mede UM arquivo, imprime o relatório e devolve as linhas de CSV (uma por canal)."""
    if caminho.suffix.lower() != ".bin":
        raise ErroSHAN(f"'{caminho}': só capturas '.bin' (com ou sem cabeçalho).")
    if not caminho.exists():
        raise ErroSHAN(f"arquivo '{caminho}' não encontrado.")
    if args.inicio < 0 or args.max_amostras < 1 or args.harmonicos < 2:
        raise ErroUso("--inicio >= 0, --max-amostras >= 1 e --harmonicos >= 2.")

    ctx = resolver_contexto(argparse.Namespace(**vars(args), converter=None, arquivo=caminho,
                                               canais_exibir=args.canais_medir))
    if ctx.cabecalho is not None:
        conferir_consistencia_cabecalho(
            ctx.cabecalho, ctx.canais, ctx.canais_veio_do_cabecalho,
            contar_amostras_arquivo_bin(caminho, args.formato, ctx.offset_amostras), args.formato,
        )
    fs_total, fs_pru = _frequencias(args, ctx.cabecalho)
    fs_canal = fs_total / ctx.num_canais
    sinais, saturacao = _ler_canais(caminho, args, ctx, ctx.canais_exibir)
    titulo = ctx.cabecalho.titulo if ctx.cabecalho is not None else ""
    log.info(f"=== {caminho.name}" + (f" -- {titulo}" if titulo else "") + " ===")
    nominal = _anunciar_frequencias(args, ctx, fs_total, fs_pru)

    antes = dict(sinais)
    aplicar_correcao_sondas(args, ctx, sinais, fs_canal)
    resultados = [_medir_canal(c, sinais[c], sinais[c] is not antes[c], saturacao[c], args, ctx, fs_canal)
                  for c in ctx.canais_exibir]
    acoplamentos = _medir_acoplamento(sinais, resultados, ctx, fs_canal, fs_total)

    rotulo = args.rotulo if args.rotulo is not None else titulo
    return [_linha_csv(caminho, rotulo, nominal, fs_pru, fs_canal, r, acoplamentos.get(r.canal)) for r in resultados]


def main(argv: list[str] | None = None) -> int:
    parser = montar_parser()
    args = parser.parse_args(argv)
    configurar_logging_cli()

    linhas: list[dict[str, str]] = []
    falhas = 0
    try:
        if args.canais is not None:
            validar = analisar_lista_canais(args.canais, "--canais")
            if args.canais_medir is not None:
                validar_subconjunto_canais(analisar_lista_canais(args.canais_medir, "--canais-medir"), validar)
        for caminho in args.arquivos:
            try:
                linhas += medir_arquivo(caminho, args)
            except ErroUso:
                raise
            except ErroSHAN as e:
                log.error(f"{caminho}: {e}")
                falhas += 1
        if args.csv is not None and linhas:
            _acrescentar_csv(args.csv, linhas)
            log.info(f"{len(linhas)} linha(s) acrescentada(s) a {args.csv}")
    except ErroUso as e:
        parser.error(str(e))
    except ErroSHAN as e:
        log.error(str(e))
        return 1
    return 1 if falhas else 0
