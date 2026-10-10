#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "numpy>=1.20",
#     "scipy>=1.15.3",
#     "matplotlib>=3.10.9",
# ]
# ///
"""
gerar_perfil_sonda.py -- Constrói o perfil de calibração (.json) de uma sonda
de corrente a partir das capturas geradas por scripts/calibrar_sonda.sh.

Entrada: a pasta de capturas de UMA sonda (`capturas/<sonda>/`), contendo
arquivos `calibracao_<FREQ>Hz_rep<N>[_vM].bin` (2 canais: referência +
sonda, grandeza/sonda_id gravados no cabeçalho v2 -- ver
firmware/ler_adc.c) e, opcionalmente, o manifesto `pontos_coletados.csv`
(usado só como referência cruzada/rótulo, nunca como fonte de verdade sobre
frequência -- ver seção "Medição da frequência", abaixo).

Saída: `scripts/sondas/<id>.json`, no formato consumido por
`adc_tool.py::carregar_perfil_sonda()` -- ver docs/proposta_correcao_sonda.md.

COMO A CORRENTE REAL É CONHECIDA (escolha um, mutuamente exclusivos):
  --amplitude-referencia A     Corrente injetada CONSTANTE (A), a mesma em
                                toda a varredura -- use se o gerador/fonte
                                já é uma fonte de corrente calibrada e
                                confiável em toda a faixa de frequência.
  --resistencia-shunt OHMS     [RECOMENDADO] Corrente real calculada POR
                                FREQUÊNCIA a partir do canal de referência
                                (tensão sobre um shunt de precisão em série
                                com a sonda -- convenção de
                                scripts/calibrar_sonda.sh, canal 0):
                                corrente_real(f) = V_shunt_medido(f) / OHMS.
                                Mais robusto a deriva de amplitude do
                                gerador ao longo da varredura.

MEDIÇÃO DA FREQUÊNCIA: a frequência de cada ponto de calibração é MEDIDA a
partir da própria captura (busca de pico + interpolação parabólica, mesmo
princípio de refinar_pico_parabolico em adc_tool.py), não copiada do nome
do arquivo/manifesto -- o nome do arquivo e a coluna do manifesto são só uma
DICA de onde procurar (janela de busca = alvo ± --tolerancia-freq-pct), não
a frequência de verdade (o operador ajusta o gerador manualmente; o valor
nominal pedido nunca é exatamente o injetado).

SOBRE --ganho (IMPORTANTE, gotcha de unidades): tem o MESMO SIGNIFICADO de
`adc_tool.py --ganho` -- o fator escalar que converte Volts no pino do ADC
para a grandeza física do canal (aqui, Amperes). Para o canal da sonda,
isso é tipicamente 1/sensibilidade_nominal (ex.: sonda de 100 mV/A ->
--ganho 10). O `ganho(f)` gravado no perfil resultante é relativo a ESSE
valor -- ou seja, o perfil só é fisicamente correto se usado depois, em
produção, com o MESMO --ganho para o canal da sonda. O --ganho usado aqui é
gravado como metadado no .json (campo `calibracao_adc.ganho.sonda`) para
rastreabilidade, e o script avisa se o ganho no ponto de referência (menor
frequência calibrada) ficar longe de 1.0 -- sinal de que o --ganho
informado provavelmente não é o valor nominal correto da sonda.

Exemplo:
  uv run gerar_perfil_sonda.py capturas/fluke_i30_01 \\
      --resistencia-shunt 0.1 --ganho 10 \\
      --fabricante Fluke --modelo i30s --plot
"""

import argparse
import json
import os
import re
import shutil
import statistics
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

# adc_tool.py mora na mesma pasta -- resolvido pelo caminho DESTE arquivo,
# não pelo diretório corrente de quem chama (mesmo cuidado já tomado em
# scripts/calibrar_sonda.sh para achar o `ler_adc`).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import adc_tool as at  # noqa: E402  (import após sys.path.insert é intencional)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Mesmo padrão de nome usado por scripts/calibrar_sonda.sh
# (calibracao_<FREQ>Hz_rep<N>.bin), incluindo a variante "_vM" que
# caminho_disponivel() gera lá para não sobrescrever uma captura anterior.
PADRAO_NOME_CAPTURA = re.compile(r"^calibracao_(\d+)Hz_rep(\d+)(?:_v\d+)?\.bin$")

TOLERANCIA_FREQ_PCT_PADRAO = 10.0
RESOLUCAO_WELCH_PADRAO = 100.0
SOBREPOSICAO_WELCH_PADRAO = 0.75  # mais alta que o padrão de adc_tool.py (0.5): aqui não há restrição de tempo real, e mais sobreposição reduz mais a variância da estimativa sobre a mesma captura
JANELA_PADRAO = "flattop"  # não é o padrão de adc_tool.py (retangular) -- flat-top é a escolha recomendada na literatura de metrologia especificamente para EXATIDÃO DE AMPLITUDE de um tom discreto isolado (ao custo de resolução em frequência, irrelevante aqui: já sabemos a frequência aproximada)
SNR_MINIMO_DB_PADRAO = 20.0  # um 'tom' precisa se destacar do piso de ruído por pelo menos isso, senão é só o maior bin de ruído (ex.: sonda desconectada) -- ver medir_tom()
DESVIO_ALERTA_PCT = 10.0  # coeficiente de variação do ganho entre repetições acima disso = aviso
FRACAO_SATURACAO_MAXIMA = 0.0005  # fração de amostras brutas no fundo de escala do ADC (código mínimo/máximo) acima da qual a captura é descartada: uma senoide ceifada tem a amplitude subestimada e distorção harmônica, e o ganho medido dela é lixo


# ---------------------------------------------------------------------------
# Descoberta de arquivos e manifesto
# ---------------------------------------------------------------------------

def descobrir_capturas(pasta: Path) -> list[Path]:
    """Lista os '.bin' de calibração em 'pasta', pelo padrão de nome de
    scripts/calibrar_sonda.sh -- não depende do manifesto existir."""
    if not pasta.is_dir():
        raise SystemExit(f"Erro: '{pasta}' não é uma pasta.")
    arquivos = sorted(
        p for p in pasta.iterdir()
        if p.is_file() and PADRAO_NOME_CAPTURA.match(p.name)
    )
    if not arquivos:
        raise SystemExit(
            f"Erro: nenhum arquivo 'calibracao_<FREQ>Hz_rep<N>.bin' encontrado "
            f"em '{pasta}'. Essa é a convenção de nome gravada por "
            f"scripts/calibrar_sonda.sh -- confira se a pasta está certa."
        )
    return arquivos


def ler_status_manifesto(pasta: Path) -> dict[str, str]:
    """Lê pontos_coletados.csv (se existir) e devolve {nome_arquivo:
    status}. Usado só para ANOTAR avisos (ex.: 'aceito_com_erro_1') no
    console -- a lista real de arquivos a processar vem sempre do disco
    (descobrir_capturas), nunca só do manifesto: um manifesto ausente ou
    desatualizado não deve impedir o processamento."""
    caminho = pasta / "pontos_coletados.csv"
    status_por_arquivo: dict[str, str] = {}
    if not caminho.exists():
        return status_por_arquivo
    with open(caminho, "r", newline="") as f:
        cabecalho = f.readline()
        colunas = cabecalho.strip().split(",")
        if "arquivo" not in colunas or "status" not in colunas:
            return status_por_arquivo
        idx_arquivo = colunas.index("arquivo")
        idx_status = colunas.index("status")
        for linha in f:
            campos = linha.rstrip("\n").split(",")
            if len(campos) > max(idx_arquivo, idx_status):
                status_por_arquivo[campos[idx_arquivo]] = campos[idx_status]
    return status_por_arquivo


# ---------------------------------------------------------------------------
# Medição de um tom conhecido dentro de uma captura
# ---------------------------------------------------------------------------

def resolucao_efetiva_hz(freq_alvo_hz: float, resolucao_welch_hz: float) -> float:
    """Resolução espectral usada para medir o tom em 'freq_alvo_hz'. A
    resolução PEDIDA pelo usuário (--resolucao-welch) é adequada perto do
    topo de uma varredura log-espaçada (ex.: dezenas de kHz), mas GROSSA
    DEMAIS perto da base (ex.: 60-100 Hz): com poucos bins entre DC e o
    alvo, o bin mais próximo do tom real pode ficar longe o bastante para
    a interpolação parabólica (refinar_pico_parabolico) extrapolar mal --
    ela assume uma vizinhança aproximadamente parabólica em log-magnitude,
    suposição que só vale perto o bastante do pico de verdade.
    Regra: nunca mais grossa que freq_alvo/10 (garante ordem de grandeza de
    10 bins entre DC e o alvo) -- só AFINA a resolução pedida, nunca
    engrossa (não faz sentido pedir menos resolução que o usuário definiu
    para o topo da varredura)."""
    return min(resolucao_welch_hz, max(1.0, freq_alvo_hz / 10.0))


def medir_tom(sinal: np.ndarray, fs: float, freq_alvo_hz: float, tolerancia_pct: float,
              nome_janela: str, resolucao_hz: float, sobreposicao: float,
              snr_minimo_db: float = SNR_MINIMO_DB_PADRAO) -> tuple[float, float] | None:
    """Mede frequência e amplitude REAIS de um tom dentro de 'sinal' (já
    calibrado em Volts/Amperes), buscando o pico de maior amplitude numa
    janela [freq_alvo*(1-tol), freq_alvo*(1+tol)] em torno de
    'freq_alvo_hz' -- a janela existe só para não confundir o tom real com
    um harmônico ou outro espúrio em outra parte do espectro, não para
    "confiar" na frequência nominal (ver docstring do módulo).

    Espectro via Welch (calcular_espectro_welch, modo 'tom') -- média de
    vários segmentos reduz a variância da estimativa de amplitude em
    relação a uma FFT única sobre o mesmo sinal. Resolução AJUSTADA por
    frequência-alvo, ver resolucao_efetiva_hz().

    Retorna (freq_medida_hz, amplitude_linear) ou None se não houver
    nenhum TOM CLARO na janela de busca: sem nenhum bin lá dentro
    (tolerância pequena demais) OU o maior bin não se destaca do piso de
    ruído por pelo menos 'snr_minimo_db' (captura sem sinal nesse canal --
    ex.: sonda desconectada). Sem essa checagem de SNR, o "pico" devolvido
    num canal só com ruído seria apenas o maior bin de ruído da janela, e
    viraria um ponto-lixo silencioso no perfil final.
    """
    resolucao_usada = resolucao_efetiva_hz(freq_alvo_hz, resolucao_hz)
    freqs, amplitude_db, _n_segmentos = at.calcular_espectro_welch(
        sinal, fs, nome_janela, 8.6, resolucao_usada, sobreposicao, modo="tom",
    )
    resolucao_bin = freqs[1] - freqs[0]

    freq_lo = freq_alvo_hz * (1.0 - tolerancia_pct / 100.0)
    freq_hi = freq_alvo_hz * (1.0 + tolerancia_pct / 100.0)
    # A janela percentual pode ficar mais ESTREITA que a resolução do
    # próprio espectro mesmo após o ajuste acima (ex.: tolerância muito
    # apertada) -- garante uma largura mínima de alguns bins, alargando
    # simetricamente em torno do alvo quando necessário -- nunca reduz a
    # janela pedida, só evita uma janela matematicamente vazia.
    largura_minima = 3.0 * resolucao_bin
    if (freq_hi - freq_lo) < largura_minima:
        freq_lo = freq_alvo_hz - largura_minima / 2.0
        freq_hi = freq_alvo_hz + largura_minima / 2.0

    mascara = (freqs >= freq_lo) & (freqs <= freq_hi)
    indices_janela = np.where(mascara)[0]
    if len(indices_janela) == 0:
        return None

    idx_pico_global = indices_janela[np.argmax(amplitude_db[indices_janela])]

    # Piso de ruído = mediana do espectro FORA de uma guarda em torno do pico
    # (mediana é robusta a um tom isolado; a guarda cobre o lóbulo principal,
    # largo em janelas como flat-top). DC (bin 0) também fica de fora.
    guarda_bins = 10
    fora_do_pico = np.ones(len(freqs), dtype=bool)
    fora_do_pico[max(0, idx_pico_global - guarda_bins): idx_pico_global + guarda_bins + 1] = False
    fora_do_pico[0] = False
    if np.any(fora_do_pico):
        snr_db = float(amplitude_db[idx_pico_global] - np.median(amplitude_db[fora_do_pico]))
        if snr_db < snr_minimo_db:
            return None

    delta, amplitude_db_refinada = at.refinar_pico_parabolico(amplitude_db, idx_pico_global)
    resolucao_bin = freqs[1] - freqs[0]
    freq_medida = freqs[idx_pico_global] + delta * resolucao_bin
    amplitude_linear = 10.0 ** (amplitude_db_refinada / 20.0)
    return freq_medida, amplitude_linear


# ---------------------------------------------------------------------------
# Processamento de uma captura individual
# ---------------------------------------------------------------------------

def _sem_prefixo_erro(e: BaseException) -> str:
    """SystemExit(\"Erro: ...\") reaproveitado como texto de um aviso: tira o
    prefixo redundante para não imprimir \"Aviso: ... -- Erro: ...\"."""
    texto = str(e)
    return texto[len("Erro: "):] if texto.startswith("Erro: ") else texto


@dataclass
class PontoMedido:
    arquivo: Path
    freq_alvo_hz: float          # só a "dica" (nome do arquivo/manifesto) -- não é a frequência de verdade
    freq_medida_hz: float        # medida de verdade, ver medir_tom()
    amplitude_sonda: float       # já na grandeza física do canal (--ganho aplicado -- ver docstring do módulo)
    amplitude_referencia: float | None  # idem, canal de referência; None se não foi lido (modo --amplitude-referencia)


def resolver_canais(cabecalho, canal_referencia_cli: int | None, canal_sonda_cli: int | None) -> tuple[int, int]:
    """Decide qual canal é referência e qual é sonda. Prioridade: flags
    explícitas > detecção automática pelo cabeçalho v2 (grandeza==CORRENTE
    == sonda; o outro canal == referência, exige exatamente 2 canais na
    captura)."""
    if canal_referencia_cli is not None and canal_sonda_cli is not None:
        return canal_referencia_cli, canal_sonda_cli
    if cabecalho is None or cabecalho.versao_cabecalho < 2:
        raise SystemExit(
            "Erro: captura sem cabeçalho v2 (com grandeza por canal) -- "
            "informe --canal-referencia e --canal-sonda explicitamente."
        )
    if cabecalho.num_canais != 2:
        raise SystemExit(
            f"Erro: captura tem {cabecalho.num_canais} canal(is), esperado "
            f"exatamente 2 (referência + sonda) para detecção automática -- "
            f"informe --canal-referencia/--canal-sonda explicitamente."
        )
    indices_corrente = [i for i, g in enumerate(cabecalho.grandeza_por_canal) if g == at.GRANDEZA_CORRENTE]
    if len(indices_corrente) != 1:
        raise SystemExit(
            f"Erro: não consegui identificar automaticamente qual canal é a "
            f"sonda (esperado exatamente 1 canal com grandeza=corrente no "
            f"cabeçalho, encontrado {len(indices_corrente)}) -- informe "
            f"--canal-referencia/--canal-sonda explicitamente."
        )
    idx_sonda = indices_corrente[0]
    idx_referencia = 1 - idx_sonda
    return cabecalho.lista_canais[idx_referencia], cabecalho.lista_canais[idx_sonda]


def processar_captura(caminho: Path, freq_alvo_hz: float, modo_referencia: str,
                       canal_referencia_cli: int | None, canal_sonda_cli: int | None,
                       formato: str, faixa_texto: str, ganho_texto: str, offset_texto: str | None,
                       tolerancia_pct: float, nome_janela: str, resolucao_hz: float,
                       sobreposicao: float, snr_minimo_db: float = SNR_MINIMO_DB_PADRAO,
                       frequencia_cli: float | None = None) -> PontoMedido | None:
    """Carrega 'caminho', calibra os 2 canais em Volts/Amperes e mede o
    tom em cada um. Devolve None (com aviso já impresso) em vez de lançar
    exceção, para um arquivo ruim não derrubar o lote inteiro."""
    cabecalho = at.ler_cabecalho(caminho)
    offset_amostras = at.CABECALHO_TAMANHO_TOTAL if cabecalho is not None else 0

    try:
        canal_ref, canal_sonda = resolver_canais(cabecalho, canal_referencia_cli, canal_sonda_cli)
    except SystemExit as e:
        print(f"Aviso: pulando '{caminho.name}' -- {_sem_prefixo_erro(e)}", file=sys.stderr)
        return None

    # Ordem de intercalação no arquivo = a lista de canais do cabeçalho (canais
    # habilitados em ordem CRESCENTE de número, imposta pelo ADS8688, ver
    # ler_adc.c). Sem cabeçalho (captura legada), assume exatamente os 2
    # canais pedidos, em ordem crescente. Usar a lista do cabeçalho -- e não
    # sempre "os 2 canais" -- importa quando --canal-referencia/--canal-sonda
    # são forçados numa captura com MAIS de 2 canais: desintercalar e a
    # frequência efetiva (fs_total/n_canais) precisam do número REAL de
    # canais intercalados. As listas de calibração (--faixa/--ganho/--offset)
    # são indexadas por PAPEL, na ordem documentada [referencia, sonda],
    # independente de qual canal tem o número menor -- senão, uma sonda num
    # canal de número menor que o da referência trocaria os valores de papel
    # em silêncio.
    if canal_ref == canal_sonda:
        print(f"Aviso: pulando '{caminho.name}' -- canal de referência e de sonda são o mesmo ({canal_ref}).", file=sys.stderr)
        return None
    if cabecalho is not None and cabecalho.num_canais > 0:
        canais = list(cabecalho.lista_canais)
    else:
        canais = sorted([canal_ref, canal_sonda])
    ausentes = [c for c in (canal_ref, canal_sonda) if c not in canais]
    if ausentes:
        print(f"Aviso: pulando '{caminho.name}' -- canal(is) {ausentes} não está(ão) na lista de canais da captura {canais}.", file=sys.stderr)
        return None
    faixas = at.analisar_lista_calibracao(faixa_texto, 2, "--faixa")      # [referencia, sonda]
    ganhos = at.analisar_lista_calibracao(ganho_texto, 2, "--ganho")      # [referencia, sonda]
    offsets = at.resolver_offsets_por_canal(offset_texto, faixas, formato, 2)  # [referencia, sonda]

    try:
        amostras = at.carregar_amostras_bin(caminho, formato, offset=offset_amostras)
    except SystemExit as e:
        print(f"Aviso: pulando '{caminho.name}' -- {_sem_prefixo_erro(e)}", file=sys.stderr)
        return None

    por_canal_bruto = at.desintercalar(amostras, canais, [canal_ref, canal_sonda])
    # Frequência TOTAL de amostragem: cabeçalho (sempre, quando existe) >
    # -f/--frequencia (captura legada sem cabeçalho) > erro claro. Mesma
    # hierarquia de adc_tool.py.
    if cabecalho is not None and cabecalho.frequencia_hz > 0:
        fs_total = float(cabecalho.frequencia_hz)
    elif frequencia_cli is not None:
        fs_total = frequencia_cli
    else:
        print(
            f"Aviso: pulando '{caminho.name}' -- sem cabeçalho com a "
            f"frequência de amostragem; informe -f/--frequencia (Hz, total).",
            file=sys.stderr,
        )
        return None
    fs_efetiva = fs_total / len(canais)

    # Saturação do ADC (código mínimo/máximo) em qualquer um dos 2 canais.
    limite_inf, limite_sup = (0, 65535) if formato == "uint16" else (-32768, 32767)
    for papel, canal_papel in (("referência", canal_ref), ("sonda", canal_sonda)):
        codigos = por_canal_bruto[canal_papel]
        fracao_saturada = float(np.count_nonzero((codigos <= limite_inf) | (codigos >= limite_sup))) / max(1, len(codigos))
        if fracao_saturada > FRACAO_SATURACAO_MAXIMA:
            print(
                f"Aviso: pulando '{caminho.name}' -- o canal de {papel} "
                f"(canal {canal_papel}) saturou o ADC em {fracao_saturada * 100:.2f}% "
                f"das amostras (limite: {FRACAO_SATURACAO_MAXIMA * 100:.2f}%). "
                f"Reduza a amplitude injetada/o ganho analógico e meça de novo.",
                file=sys.stderr,
            )
            return None

    sinal_ref_v = at.converter_para_tensao(
        por_canal_bruto[canal_ref], faixas[0], ganhos[0], formato, offsets[0]
    )
    sinal_sonda_v = at.converter_para_tensao(
        por_canal_bruto[canal_sonda], faixas[1], ganhos[1], formato, offsets[1]
    )

    resultado_sonda = medir_tom(sinal_sonda_v, fs_efetiva, freq_alvo_hz, tolerancia_pct,
                                 nome_janela, resolucao_hz, sobreposicao, snr_minimo_db)
    if resultado_sonda is None:
        print(
            f"Aviso: pulando '{caminho.name}' -- nenhum tom claro (SNR >= "
            f"{snr_minimo_db:g} dB) no canal da sonda perto de {freq_alvo_hz:g} "
            f"Hz (±{tolerancia_pct:g}%). Verifique se a sonda estava conectada.",
            file=sys.stderr,
        )
        return None
    freq_medida_sonda, amplitude_sonda = resultado_sonda

    amplitude_referencia = None
    freq_medida = freq_medida_sonda
    if modo_referencia == "shunt":
        resultado_ref = medir_tom(sinal_ref_v, fs_efetiva, freq_alvo_hz, tolerancia_pct,
                                   nome_janela, resolucao_hz, sobreposicao, snr_minimo_db)
        if resultado_ref is None:
            print(
                f"Aviso: pulando '{caminho.name}' -- nenhum tom claro (SNR >= "
                f"{snr_minimo_db:g} dB) no canal de referência perto de "
                f"{freq_alvo_hz:g} Hz. Confira a leitura do shunt.",
                file=sys.stderr,
            )
            return None
        freq_medida_ref, amplitude_referencia = resultado_ref
        # Frequência final = média das duas estimativas independentes
        # (sonda e referência veem o mesmo tom físico; usar as duas reduz
        # um pouco o ruído da estimativa em vez de confiar só numa).
        freq_medida = (freq_medida_sonda + freq_medida_ref) / 2.0

    return PontoMedido(
        arquivo=caminho, freq_alvo_hz=freq_alvo_hz, freq_medida_hz=freq_medida,
        amplitude_sonda=amplitude_sonda, amplitude_referencia=amplitude_referencia,
    )


# ---------------------------------------------------------------------------
# Agregação por frequência (múltiplas repetições) e montagem do perfil
# ---------------------------------------------------------------------------

@dataclass
class PontoPerfil:
    freq_hz: float
    ganho: float
    n_amostras: int
    desvio_pct: float  # coeficiente de variação (%) do ganho entre repetições -- 0 se n_amostras==1


def agregar_por_frequencia(pontos: list[PontoMedido], modo_referencia: str,
                            amplitude_referencia_fixa: float | None,
                            resistencia_shunt: float | None) -> list[PontoPerfil]:
    """Agrupa 'pontos' pela frequência-ALVO nominal (freq_alvo_hz, herdada
    do nome do arquivo/--redundancia em scripts/calibrar_sonda.sh) -- essa
    é a chave de "mesmo ponto de calibração, repetido N vezes", não a
    frequência medida: duas repetições do MESMO alvo nominal podem ter
    frequências medidas ligeiramente diferentes entre si (imprecisão do
    operador ajustando o gerador à mão), e agrupar por proximidade de
    frequência MEDIDA fragmentaria essas repetições em pontos separados
    exatamente quando essa imprecisão for maior que um limiar arbitrário de
    "quão perto é perto o bastante". O valor de frequência gravado no perfil
    final ainda vem inteiramente de medição (média das freq_medida_hz do
    grupo) -- só a decisão de QUAIS pontos pertencem ao mesmo grupo usa o
    alvo nominal.
    """
    por_alvo: dict[float, list[PontoMedido]] = {}
    for p in pontos:
        por_alvo.setdefault(p.freq_alvo_hz, []).append(p)

    perfil_pontos = []
    for freq_alvo, grupo in sorted(por_alvo.items()):
        ganhos, freqs_medidas, nomes = [], [], []
        for p in grupo:
            if modo_referencia == "fixa":
                corrente_real = amplitude_referencia_fixa
            else:
                corrente_real = p.amplitude_referencia / resistencia_shunt
            if corrente_real <= 0:
                print(f"Aviso: descartando '{p.arquivo.name}' -- corrente de referência calculada <= 0.", file=sys.stderr)
                continue
            ganhos.append(p.amplitude_sonda / corrente_real)
            freqs_medidas.append(p.freq_medida_hz)
            nomes.append(p.arquivo.name)

        if not ganhos:
            continue

        freq_media = statistics.mean(freqs_medidas)
        ganho_medio = statistics.mean(ganhos)
        desvio_pct = 0.0
        if len(ganhos) > 1:
            desvio_pct = (statistics.stdev(ganhos) / ganho_medio) * 100.0 if ganho_medio else 0.0
            if desvio_pct > DESVIO_ALERTA_PCT:
                print(
                    f"Aviso: repetições do alvo {freq_alvo:g} Hz (medidas em "
                    f"~{freq_media:.1f} Hz) discordam {desvio_pct:.1f}% entre "
                    f"si (limiar: {DESVIO_ALERTA_PCT:g}%) -- considere remedir. "
                    f"Arquivos: {', '.join(nomes)}",
                    file=sys.stderr,
                )
        perfil_pontos.append(PontoPerfil(freq_hz=freq_media, ganho=ganho_medio,
                                          n_amostras=len(ganhos), desvio_pct=desvio_pct))

    return perfil_pontos


def montar_perfil_json(pontos: list[PontoPerfil], args) -> dict:
    pontos_ordenados = sorted(pontos, key=lambda p: p.freq_hz)
    perfil = {
        "id": args.id,
        "tipo": "resposta_frequencia",
        "data_calibracao": args.data_calibracao,
        # 'n' e 'desvio_pct' (repetições e dispersão relativa do ganho entre
        # elas) são só rastreabilidade: carregar_perfil_sonda() lê apenas
        # freq_hz/ganho e ignora os demais campos do ponto.
        "pontos": [
            {"freq_hz": round(p.freq_hz, 3), "ganho": round(p.ganho, 6),
             "n": p.n_amostras, "desvio_pct": round(p.desvio_pct, 3)}
            for p in pontos_ordenados
        ],
    }
    if args.fabricante:
        perfil["fabricante"] = args.fabricante
    if args.modelo:
        perfil["modelo"] = args.modelo
    if args.numero_serie:
        perfil["numero_serie"] = args.numero_serie
    if args.tipo_saida:
        perfil["tipo_saida"] = args.tipo_saida
    if args.incerteza_estimada_pct is not None:
        perfil["incerteza_estimada_pct"] = args.incerteza_estimada_pct
    if args.faixa_freq_valida:
        perfil["faixa_freq_valida_hz"] = list(args.faixa_freq_valida)
    else:
        perfil["faixa_freq_valida_hz"] = [
            round(pontos_ordenados[0].freq_hz, 3),
            round(pontos_ordenados[-1].freq_hz, 3),
        ]
    calibrado_com = args.calibrado_com or "cadeia completa SH-Analyzer (sonda + isolador + ADS8688)"
    perfil["calibrado_com"] = calibrado_com

    # Metadados de rastreabilidade -- NÃO lidos por adc_tool.py hoje, mas
    # registram sob qual --ganho (e demais calibração ADC) do canal da
    # sonda este perfil é válido (ver docstring do módulo, seção --ganho).
    # Sem isso, nada impediria alguém de usar este perfil com um --ganho
    # de produção diferente do usado aqui, o que reintroduziria erro
    # sistemático de escala.
    faixas = at.analisar_lista_calibracao(args.faixa, 2, "--faixa")
    ganhos = at.analisar_lista_calibracao(args.ganho, 2, "--ganho")
    calibracao_adc = {
        "formato": args.formato,
        "faixa_v": {"referencia": faixas[0], "sonda": faixas[1]},
        "ganho": {"referencia": ganhos[0], "sonda": ganhos[1]},
        "modo_referencia": args.modo_referencia,
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "n_pontos": len(pontos_ordenados),
    }
    if args.modo_referencia == "shunt":
        calibracao_adc["resistencia_shunt_ohms"] = args.resistencia_shunt
    else:
        calibracao_adc["amplitude_referencia_a"] = args.amplitude_referencia
    perfil["calibracao_adc"] = calibracao_adc
    return perfil


# ---------------------------------------------------------------------------
# Gráfico de diagnóstico (opcional)
# ---------------------------------------------------------------------------

def gerar_grafico(pontos: list[PontoPerfil], perfil_dict: dict, caminho_saida: Path) -> None:
    import matplotlib.pyplot as plt

    freqs_pontos = np.array([p.freq_hz for p in pontos])
    ganhos_pontos = np.array([p.ganho for p in pontos])

    # Reaproveita a MESMA classe usada em produção (adc_tool.PerfilSonda)
    # p/ desenhar a curva interpolada exatamente como adc_tool.py vai
    # usá-la depois -- não uma reimplementação paralela da interpolação.
    perfil_tmp = at.PerfilSonda(
        id=perfil_dict["id"], tipo="resposta_frequencia", caminho=caminho_saida,
        pontos_freq_hz=freqs_pontos, pontos_ganho=ganhos_pontos,
    )
    # A grade da curva vai de min a max dos pontos; o erro de arredondamento de
    # 10**log10(x) pode deixar 1 ponto 1 ulp fora da faixa e disparar o aviso
    # de "fora da faixa calibrada" -- irrelevante aqui, só desenhamos.
    perfil_tmp._avisou_fora_da_faixa = True
    freqs_curva = np.logspace(np.log10(freqs_pontos.min()), np.log10(freqs_pontos.max()), 500)
    ganhos_curva = perfil_tmp.ganho_em(freqs_curva)

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.semilogx(freqs_curva, ganhos_curva, "-", color="tab:blue", linewidth=1.2, label="Interpolação PCHIP (uso em produção)")
    ax.semilogx(freqs_pontos, ganhos_pontos, "o", color="tab:orange", markersize=6, label="Pontos medidos")
    ax.axhline(1.0, color="gray", linewidth=0.8, linestyle=":")
    ax.set_xlabel("Frequência (Hz)")
    ax.set_ylabel("Ganho (linear, adimensional)")
    ax.set_title(f"Perfil de sonda '{perfil_dict['id']}' -- {len(pontos)} ponto(s)")
    ax.grid(True, which="both", alpha=0.4)
    ax.legend()
    fig.tight_layout()
    fig.savefig(caminho_saida, dpi=150)
    print(f"Gráfico de diagnóstico salvo em '{caminho_saida}'.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gerar_perfil_sonda.py",
        description=(
            "Constrói o perfil de calibração (.json) de uma sonda de corrente "
            "a partir das capturas de scripts/calibrar_sonda.sh. Mede "
            "frequência e amplitude de cada captura (não confia no nome do "
            "arquivo), calcula o ganho contra uma referência de corrente "
            "real, e agrega repetições."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplo:\n"
            "  uv run gerar_perfil_sonda.py capturas/fluke_i30_01 \\\n"
            "      --resistencia-shunt 0.1 --ganho 1,10 --fabricante Fluke --modelo i30s --plot\n"
            "\n"
            "--faixa/--ganho/--offset: 1 valor (vale p/ os 2 canais) ou 'referencia,sonda'.\n"
            "--ganho do canal da sonda = 1/sensibilidade_nominal (sonda de 100 mV/A -> 10) e DEVE ser\n"
            "o mesmo usado depois em 'adc_tool.py --ganho' -- ver docstring do módulo."
        ),
    )
    parser.add_argument("pasta_capturas", type=Path, help="Pasta com os '.bin' de calibração (ex.: capturas/fluke_i30_01/).")

    grupo_ref = parser.add_mutually_exclusive_group(required=True)
    grupo_ref.add_argument("--amplitude-referencia", type=float, metavar="A",
                            help="Corrente real CONSTANTE injetada em toda a varredura, em Amperes.")
    grupo_ref.add_argument("--resistencia-shunt", type=float, metavar="OHMS",
                            help="[Recomendado] Resistência do shunt de precisão no canal de referência -- corrente real calculada por frequência.")

    parser.add_argument("--id", type=str, default=None, help="Id da sonda no perfil de saída (padrão: nome da pasta).")
    parser.add_argument("-o", "--saida", type=Path, default=None, metavar="ARQUIVO.json",
                         help="Caminho do .json de saída (padrão: scripts/sondas/<id>.json, ao lado deste script).")

    parser.add_argument("--canal-referencia", type=int, default=None, metavar="N",
                         help="Força o número do canal de referência (padrão: detectado do cabeçalho v2).")
    parser.add_argument("--canal-sonda", type=int, default=None, metavar="N",
                         help="Força o número do canal da sonda (padrão: detectado do cabeçalho v2 -- canal com grandeza=corrente).")

    parser.add_argument("--formato", choices=["int16", "uint16"], default="uint16",
                         help="Mesmo significado de adc_tool.py --formato (padrão: uint16).")
    parser.add_argument("--faixa", type=str, default="10.24", metavar="V[,V]",
                         help="Faixa do ADC em Volts -- 1 valor ou 'referencia,sonda' (padrão: 10.24).")
    parser.add_argument("--ganho", type=str, default="1.0", metavar="G[,G]",
                         help="Ganho ADC->grandeza física -- 1 valor ou 'referencia,sonda' (padrão: 1.0). "
                              "Para o canal da sonda, ver docstring do módulo (--ganho ANTES da correção de frequência).")
    parser.add_argument("--offset", type=str, default=None, metavar="V[,V]",
                         help="Offset DC -- padrão automático (faixa/2 p/ uint16), mesma regra de adc_tool.py.")

    parser.add_argument("--tolerancia-freq-pct", type=float, default=TOLERANCIA_FREQ_PCT_PADRAO, metavar="PCT",
                         help=f"Janela de busca do tom em torno da frequência-alvo nominal (padrão: {TOLERANCIA_FREQ_PCT_PADRAO:g}%%).")
    parser.add_argument("--resolucao-welch", type=float, default=RESOLUCAO_WELCH_PADRAO, metavar="HZ",
                         help=f"Resolução espectral do Welch usado para medir cada tom (padrão: {RESOLUCAO_WELCH_PADRAO:g} Hz).")
    parser.add_argument("--snr-minimo-db", type=float, default=SNR_MINIMO_DB_PADRAO, metavar="DB",
                         help=f"SNR mínimo (dB) do pico sobre o piso de ruído para aceitar um tom (padrão: {SNR_MINIMO_DB_PADRAO:g}). "
                              f"Abaixo disso o arquivo é pulado -- evita gravar no perfil o 'pico' de um canal só com ruído (ex.: sonda desconectada).")
    parser.add_argument("-f", "--frequencia", type=float, default=None, metavar="HZ",
                         help="Frequência de amostragem TOTAL, só p/ capturas legadas SEM cabeçalho (mesmo significado de adc_tool.py -f).")
    parser.add_argument("--sobreposicao-welch", type=float, default=SOBREPOSICAO_WELCH_PADRAO, metavar="FRACAO",
                         help=f"Sobreposição entre segmentos do Welch (padrão: {SOBREPOSICAO_WELCH_PADRAO:g}).")
    parser.add_argument("--janela", type=str, default=JANELA_PADRAO, metavar="NOME",
                         help=f"Janela espectral (padrão: '{JANELA_PADRAO}' -- recomendada p/ exatidão de amplitude; mesmas opções de adc_tool.py).")

    parser.add_argument("--fabricante", type=str, default=None)
    parser.add_argument("--modelo", type=str, default=None)
    parser.add_argument("--numero-serie", type=str, default=None)
    parser.add_argument("--tipo-saida", type=str, default=None, help="Ex.: 'mV/A'.")
    parser.add_argument("--incerteza-estimada-pct", type=float, default=None)
    parser.add_argument("--calibrado-com", type=str, default=None)
    parser.add_argument("--faixa-freq-valida", type=float, nargs=2, default=None, metavar=("MIN_HZ", "MAX_HZ"),
                         help="Override manual -- padrão: [menor, maior] frequência efetivamente medida.")
    parser.add_argument("--data-calibracao", type=str, default=str(date.today()), metavar="AAAA-MM-DD")

    parser.add_argument("--plot", action="store_true", help="Gera um '.png' de diagnóstico (pontos + curva interpolada) ao lado do '.json'.")

    return parser


def main(argv=None) -> None:
    parser = montar_parser()
    args = parser.parse_args(argv)

    args.modo_referencia = "fixa" if args.amplitude_referencia is not None else "shunt"
    if args.modo_referencia == "fixa" and args.amplitude_referencia <= 0:
        parser.error("--amplitude-referencia precisa ser positiva.")
    if args.modo_referencia == "shunt" and args.resistencia_shunt <= 0:
        parser.error("--resistencia-shunt precisa ser positiva.")

    pasta = args.pasta_capturas
    if args.id is None:
        args.id = pasta.resolve().name
    if not re.match(r"^[a-z0-9_-]+$", args.id):
        print(
            f"Aviso: id '{args.id}' tem caracteres fora de [a-z0-9_-] -- "
            f"scripts/calibrar_sonda.sh só gera pastas já sanitizadas; se "
            f"esta pasta não veio de lá, considere renomear.",
            file=sys.stderr,
        )

    caminho_saida = args.saida or (Path(__file__).resolve().parent / "sondas" / f"{args.id}.json")

    arquivos = descobrir_capturas(pasta)
    status_manifesto = ler_status_manifesto(pasta)
    print(f"{len(arquivos)} arquivo(s) de captura encontrado(s) em '{pasta}'.")

    pontos_medidos: list[PontoMedido] = []
    for caminho in arquivos:
        m = PADRAO_NOME_CAPTURA.match(caminho.name)
        freq_alvo_hz = float(m.group(1))

        status = status_manifesto.get(caminho.name)
        if status == "sem_arquivo":
            continue  # não deveria nem existir no disco, mas por garantia
        if status and status.startswith("aceito_com_erro"):
            print(f"Aviso: '{caminho.name}' foi aceito com erro na coleta ({status}) -- processando mesmo assim.", file=sys.stderr)

        resultado = processar_captura(
            caminho, freq_alvo_hz, args.modo_referencia,
            args.canal_referencia, args.canal_sonda,
            args.formato, args.faixa, args.ganho, args.offset,
            args.tolerancia_freq_pct, args.janela, args.resolucao_welch, args.sobreposicao_welch,
            args.snr_minimo_db, args.frequencia,
        )
        if resultado is not None:
            pontos_medidos.append(resultado)

    if len(pontos_medidos) < 2:
        raise SystemExit(
            f"Erro: só {len(pontos_medidos)} ponto(s) processado(s) com sucesso "
            f"-- são necessários pelo menos 2 para um perfil 'resposta_frequencia'. "
            f"Veja os avisos acima para o motivo de cada arquivo pulado."
        )

    pontos_perfil = agregar_por_frequencia(
        pontos_medidos, args.modo_referencia, args.amplitude_referencia, args.resistencia_shunt
    )
    print(f"{len(pontos_perfil)} ponto(s) de frequência únicos após agregação de repetições.")

    ganho_ref = min(pontos_perfil, key=lambda p: p.freq_hz).ganho
    if not (0.7 <= ganho_ref <= 1.3):
        print(
            f"Aviso: ganho no ponto de menor frequência ({ganho_ref:.3f}) está "
            f"longe de 1.0 -- se essa frequência é onde a sensibilidade "
            f"nominal da sonda foi especificada, o --ganho={args.ganho} "
            f"informado provavelmente não é o valor nominal correto (ver "
            f"docstring do módulo).",
            file=sys.stderr,
        )

    perfil_dict = montar_perfil_json(pontos_perfil, args)

    caminho_saida.parent.mkdir(parents=True, exist_ok=True)

    # Escrita em dois tempos: grava num arquivo temporário, valida o
    # round-trip nele (recarrega pelo MESMO código que adc_tool.py vai usar em
    # produção -- pega qualquer erro de geração antes do operador descobrir
    # isso no meio de uma análise) e SÓ ENTÃO substitui o perfil final. Antes,
    # o arquivo final era sobrescrito antes da validação: um perfil ruim (ou
    # uma recalibração com --ganho errado) destruía o perfil bom que já
    # existia, sem aviso e sem cópia.
    caminho_tmp = caminho_saida.with_name(caminho_saida.name + ".tmp")
    with open(caminho_tmp, "w", encoding="utf-8") as f:
        json.dump(perfil_dict, f, indent=2, ensure_ascii=False)
        f.write("\n")
    try:
        perfil_recarregado = at.carregar_perfil_sonda(caminho_tmp)
    except (SystemExit, ValueError) as e:
        caminho_tmp.unlink(missing_ok=True)
        raise SystemExit(f"Erro: o perfil gerado NÃO carrega de volta via adc_tool.py -- {e} (o perfil anterior, se havia, foi mantido).")
    if caminho_saida.exists():
        caminho_bak = caminho_saida.with_name(caminho_saida.name + ".bak")
        shutil.copy2(caminho_saida, caminho_bak)
        print(f"Aviso: '{caminho_saida}' já existia -- será substituído; cópia do anterior em '{caminho_bak}'.", file=sys.stderr)
    os.replace(caminho_tmp, caminho_saida)
    print(f"Perfil salvo em '{caminho_saida}'.")
    print(f"Validação: perfil recarregado com sucesso via adc_tool.carregar_perfil_sonda ('{perfil_recarregado.id}', {len(pontos_perfil)} pontos).")

    for p in sorted(pontos_perfil, key=lambda p: p.freq_hz):
        marcador = f" (desvio {p.desvio_pct:.1f}%, {p.n_amostras} rep.)" if p.n_amostras > 1 else ""
        print(f"  {p.freq_hz:10.2f} Hz -> ganho {p.ganho:.4f}{marcador}")

    if args.plot:
        gerar_grafico(pontos_perfil, perfil_dict, caminho_saida.with_suffix(".png"))


if __name__ == "__main__":
    main()
