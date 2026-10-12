"""Calibração de sonda de corrente: medir tons, calcular o ganho e agregar repetições.

Núcleo "sem CLI" do gerador de perfis (a linha de comando está em
``cli_gerar_perfil``). Entrada: a pasta de capturas de UMA sonda
(``capturas/<sonda>/``), com arquivos ``calibracao_<FREQ>Hz_rep<N>[_vM].bin``
(2 canais: referência + sonda; grandeza/sonda_id gravados no cabeçalho v2 --
ver ``firmware/ler_adc.c``) gerados por ``firmware/calibrar_sonda.sh`` e,
opcionalmente, o manifesto ``pontos_coletados.csv`` (só referência cruzada).

COMO A CORRENTE REAL É CONHECIDA (mutuamente exclusivos):

* modo ``fixa``  -- corrente injetada CONSTANTE em toda a varredura
  (``--amplitude-referencia``);
* modo ``shunt`` -- [RECOMENDADO] corrente real por frequência a partir do
  canal de referência: ``corrente_real(f) = V_shunt_medido(f) / OHMS``.

MEDIÇÃO DA FREQUÊNCIA: a frequência de cada ponto é MEDIDA na própria captura
(pico + interpolação parabólica, o mesmo princípio de ``refinar_pico_parabolico``),
não copiada do nome do arquivo -- o nome é só uma DICA de onde procurar
(janela alvo ± tolerância), porque o operador ajusta o gerador à mão e o valor
nominal pedido nunca é exatamente o injetado.

SOBRE ``--ganho`` (gotcha de unidades): mesmo significado de ``adc_tool --ganho``
(fator Volts no pino do ADC -> grandeza física; para a sonda, tipicamente
1/sensibilidade_nominal, ex.: 100 mV/A -> 10). O ``ganho(f)`` do perfil é
relativo a ESSE valor: o perfil só é correto se usado depois, em produção, com
o MESMO ``--ganho`` no canal da sonda.

Depende de: ``amostras``, ``canais``, ``cabecalho``, ``constantes``, ``espectro``,
``fundamental``, ``erros``.
"""

import logging
import re
import statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .amostras import carregar_amostras_bin, converter_para_tensao
from .cabecalho import CABECALHO_TAMANHO_TOTAL, ler_cabecalho
from .canais import analisar_lista_calibracao, desintercalar, resolver_offsets_por_canal
from .constantes import GRANDEZA_CORRENTE
from .erros import ErroSHAN
from .espectro import calcular_espectro_welch
from .fundamental import refinar_pico_parabolico

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Mesmo padrão de nome usado por firmware/calibrar_sonda.sh
# (calibracao_<FREQ>Hz_rep<N>.bin), incluindo a variante "_vM" que
# caminho_disponivel() gera lá para não sobrescrever uma captura anterior.
PADRAO_NOME_CAPTURA = re.compile(r"^calibracao_(\d+)Hz_rep(\d+)(?:_v\d+)?\.bin$")

TOLERANCIA_FREQ_PCT_PADRAO = 10.0
RESOLUCAO_WELCH_CALIBRACAO_PADRAO = 100.0
SOBREPOSICAO_WELCH_CALIBRACAO_PADRAO = 0.75  # mais alta que o padrão de adc_tool.py (0.5): aqui não há restrição de tempo real, e mais sobreposição reduz mais a variância da estimativa sobre a mesma captura
JANELA_CALIBRACAO_PADRAO = "flattop"  # não é o padrão de adc_tool.py (retangular) -- flat-top é a escolha recomendada na literatura de metrologia especificamente para EXATIDÃO DE AMPLITUDE de um tom discreto isolado (ao custo de resolução em frequência, irrelevante aqui: já sabemos a frequência aproximada)
SNR_MINIMO_DB_PADRAO = 20.0  # um 'tom' precisa se destacar do piso de ruído por pelo menos isso, senão é só o maior bin de ruído (ex.: sonda desconectada) -- ver medir_tom()
DESVIO_ALERTA_PCT = 10.0  # coeficiente de variação do ganho entre repetições acima disso = aviso
FRACAO_SATURACAO_MAXIMA = 0.0005  # fração de amostras brutas no fundo de escala do ADC (código mínimo/máximo) acima da qual a captura é descartada: uma senoide ceifada tem a amplitude subestimada e distorção harmônica, e o ganho medido dela é lixo


# ---------------------------------------------------------------------------
# Descoberta de arquivos e manifesto
# ---------------------------------------------------------------------------

def descobrir_capturas(pasta: Path) -> list[Path]:
    """Lista os '.bin' de calibração em 'pasta', pelo padrão de nome de
    firmware/calibrar_sonda.sh -- não depende do manifesto existir."""
    if not pasta.is_dir():
        raise ErroSHAN(f"'{pasta}' não é uma pasta.")
    arquivos = sorted(
        p for p in pasta.iterdir()
        if p.is_file() and PADRAO_NOME_CAPTURA.match(p.name)
    )
    if not arquivos:
        raise ErroSHAN(
            f"nenhum arquivo 'calibracao_<FREQ>Hz_rep<N>.bin' encontrado "
            f"em '{pasta}'. Essa é a convenção de nome gravada por "
            f"firmware/calibrar_sonda.sh -- confira se a pasta está certa."
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
    with open(caminho, newline="") as f:
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
    freqs, amplitude_db, _n_segmentos = calcular_espectro_welch(
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

    delta, amplitude_db_refinada = refinar_pico_parabolico(amplitude_db, idx_pico_global)
    resolucao_bin = freqs[1] - freqs[0]
    freq_medida = freqs[idx_pico_global] + delta * resolucao_bin
    amplitude_linear = 10.0 ** (amplitude_db_refinada / 20.0)
    return freq_medida, amplitude_linear


# ---------------------------------------------------------------------------
# Processamento de uma captura individual
# ---------------------------------------------------------------------------

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
        raise ErroSHAN(
            "captura sem cabeçalho v2 (com grandeza por canal) -- "
            "informe --canal-referencia e --canal-sonda explicitamente."
        )
    if cabecalho.num_canais != 2:
        raise ErroSHAN(
            f"captura tem {cabecalho.num_canais} canal(is), esperado "
            f"exatamente 2 (referência + sonda) para detecção automática -- "
            f"informe --canal-referencia/--canal-sonda explicitamente."
        )
    indices_corrente = [i for i, g in enumerate(cabecalho.grandeza_por_canal) if g == GRANDEZA_CORRENTE]
    if len(indices_corrente) != 1:
        raise ErroSHAN(
            f"não consegui identificar automaticamente qual canal é a "
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
    cabecalho = ler_cabecalho(caminho)
    offset_amostras = CABECALHO_TAMANHO_TOTAL if cabecalho is not None else 0

    try:
        canal_ref, canal_sonda = resolver_canais(cabecalho, canal_referencia_cli, canal_sonda_cli)
    except ErroSHAN as e:
        log.warning(f"pulando '{caminho.name}' -- {e}")
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
        log.warning(f"pulando '{caminho.name}' -- canal de referência e de sonda são o mesmo ({canal_ref}).")
        return None
    if cabecalho is not None and cabecalho.num_canais > 0:
        canais = list(cabecalho.lista_canais)
    else:
        canais = sorted([canal_ref, canal_sonda])
    ausentes = [c for c in (canal_ref, canal_sonda) if c not in canais]
    if ausentes:
        log.warning(f"pulando '{caminho.name}' -- canal(is) {ausentes} não está(ão) na lista de canais da captura {canais}.")
        return None
    faixas = analisar_lista_calibracao(faixa_texto, 2, "--faixa")      # [referencia, sonda]
    ganhos = analisar_lista_calibracao(ganho_texto, 2, "--ganho")      # [referencia, sonda]
    offsets = resolver_offsets_por_canal(offset_texto, faixas, formato, 2)  # [referencia, sonda]

    try:
        amostras = carregar_amostras_bin(caminho, formato, offset=offset_amostras)
    except ErroSHAN as e:
        log.warning(f"pulando '{caminho.name}' -- {e}")
        return None

    por_canal_bruto = desintercalar(amostras, canais, [canal_ref, canal_sonda])
    # Frequência TOTAL de amostragem: cabeçalho (sempre, quando existe) >
    # -f/--frequencia (captura legada sem cabeçalho) > erro claro. Mesma
    # hierarquia de adc_tool.py.
    if cabecalho is not None and cabecalho.frequencia_hz > 0:
        fs_total = float(cabecalho.frequencia_hz)
    elif frequencia_cli is not None:
        fs_total = frequencia_cli
    else:
        log.warning(
            f"pulando '{caminho.name}' -- sem cabeçalho com a "
            f"frequência de amostragem; informe -f/--frequencia (Hz, total)."
        )
        return None
    fs_efetiva = fs_total / len(canais)

    # Saturação do ADC (código mínimo/máximo) em qualquer um dos 2 canais.
    limite_inf, limite_sup = (0, 65535) if formato == "uint16" else (-32768, 32767)
    for papel, canal_papel in (("referência", canal_ref), ("sonda", canal_sonda)):
        codigos = por_canal_bruto[canal_papel]
        fracao_saturada = float(np.count_nonzero((codigos <= limite_inf) | (codigos >= limite_sup))) / max(1, len(codigos))
        if fracao_saturada > FRACAO_SATURACAO_MAXIMA:
            log.warning(
                f"pulando '{caminho.name}' -- o canal de {papel} "
                f"(canal {canal_papel}) saturou o ADC em {fracao_saturada * 100:.2f}% "
                f"das amostras (limite: {FRACAO_SATURACAO_MAXIMA * 100:.2f}%). "
                f"Reduza a amplitude injetada/o ganho analógico e meça de novo."
            )
            return None

    sinal_ref_v = converter_para_tensao(
        por_canal_bruto[canal_ref], faixas[0], ganhos[0], formato, offsets[0]
    )
    sinal_sonda_v = converter_para_tensao(
        por_canal_bruto[canal_sonda], faixas[1], ganhos[1], formato, offsets[1]
    )

    resultado_sonda = medir_tom(sinal_sonda_v, fs_efetiva, freq_alvo_hz, tolerancia_pct,
                                 nome_janela, resolucao_hz, sobreposicao, snr_minimo_db)
    if resultado_sonda is None:
        log.warning(
            f"pulando '{caminho.name}' -- nenhum tom claro (SNR >= "
            f"{snr_minimo_db:g} dB) no canal da sonda perto de {freq_alvo_hz:g} "
            f"Hz (±{tolerancia_pct:g}%). Verifique se a sonda estava conectada."
        )
        return None
    freq_medida_sonda, amplitude_sonda = resultado_sonda

    amplitude_referencia = None
    freq_medida = freq_medida_sonda
    if modo_referencia == "shunt":
        resultado_ref = medir_tom(sinal_ref_v, fs_efetiva, freq_alvo_hz, tolerancia_pct,
                                   nome_janela, resolucao_hz, sobreposicao, snr_minimo_db)
        if resultado_ref is None:
            log.warning(
                f"pulando '{caminho.name}' -- nenhum tom claro (SNR >= "
                f"{snr_minimo_db:g} dB) no canal de referência perto de "
                f"{freq_alvo_hz:g} Hz. Confira a leitura do shunt."
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
    do nome do arquivo/--redundancia em firmware/calibrar_sonda.sh) -- essa
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
                log.warning(f"descartando '{p.arquivo.name}' -- corrente de referência calculada <= 0.")
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
                log.warning(
                    f"repetições do alvo {freq_alvo:g} Hz (medidas em "
                    f"~{freq_media:.1f} Hz) discordam {desvio_pct:.1f}% entre "
                    f"si (limiar: {DESVIO_ALERTA_PCT:g}%) -- considere remedir. "
                    f"Arquivos: {', '.join(nomes)}"
                )
        perfil_pontos.append(PontoPerfil(freq_hz=freq_media, ganho=ganho_medio,
                                          n_amostras=len(ganhos), desvio_pct=desvio_pct))

    return perfil_pontos
