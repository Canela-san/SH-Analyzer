"""Calibração de sonda de corrente: medir tons, calcular o ganho e agregar repetições.

Núcleo "sem CLI" do gerador de perfis (a linha de comando está em
``cli_gerar_perfil``). Entrada: a pasta de capturas de UMA sonda
(``capturas/<sonda>/``), com arquivos ``calibracao_<FREQ>Hz_rep<N>[_vM].bin``
(grandeza/sonda_id gravados no cabeçalho v2 -- ver ``firmware/ler_adc.c``)
gerados por ``firmware/calibrar_sonda.sh`` e, opcionalmente, o manifesto
``pontos_coletados.csv`` (só referência cruzada).

O QUE É "A SONDA": o perfil descreve o CONJUNTO medido, de ponta a ponta -- a sonda de corrente,
o frontend/isolador e o ADS8688 com o filtro passa-baixa de 2ª ordem que ele tem em cada canal (~15 kHz,
seção 8.3.5 do datasheet) -- e não a sonda isolada. Tudo o que esse conjunto atenua ou realça entra
no ``ganho(f)`` e é desfeito por ele em produção, então a referência tem de ser a grandeza injetada
na ENTRADA do conjunto.

COMO A GRANDEZA INJETADA É CONHECIDA (mutuamente exclusivos):

* modo ``amplitude``   -- a senoide injetada tem amplitude CONHECIDA (a que se ajustou no gerador), dada
  com unidade e tipo (``500mVpp``). Ela vem, por captura, do campo de descrição do cabeçalho
  (``ler_adc -d "ref: f=1000Hz amp=500mVpp"``, o que ``calibrar_sonda.sh --amplitude`` grava) ou, para
  todas as capturas de uma vez, de ``--amplitude-referencia``. Uma captura de 1 canal só (a sonda);
* modo ``osciloscopio`` -- a amplitude vem de um osciloscópio que mediu o MESMO sinal: um ``.m``/``.mat``/
  ``.csv`` por captura, com o nome da captura (ver ``osciloscopio``), ajustado por mínimos quadrados.
  Também 1 canal só, e é a referência mais independente (mede o que o gerador de fato entregou);
* modo ``shunt``   -- corrente real por frequência a partir de um SEGUNDO canal do ADC (referência) ligado
  ao shunt: ``corrente_real(f) = V_shunt_medido(f) / OHMS``. A captura tem 2 canais (referência + sonda),
  então a Nyquist efetiva de cada um é ``taxa_total / 4``;
* modo ``externa`` -- corrente real lida num instrumento externo (osciloscópio, multímetro) a cada ponto
  e anotada em ``referencia_externa.csv``. A captura tem 1 canal só (a sonda): Nyquist efetiva =
  ``taxa_total / 2``, o dobro do modo ``shunt``.

Nos modos de 1 canal a cadeia medida fica igual à de produção (um canal só) e o canal de referência não é lido.
A amplitude injetada, quando dada em V, é a tensão no ponto onde o ``--ganho`` é aplicado: a grandeza
física verdadeira é ``V * ganho`` (``referencia.pico_fisico``); em A, é a própria grandeza física.

Quantos canais há numa captura vem do cabeçalho (ou de ``--canal-sonda``).

MEDIÇÃO DA FREQUÊNCIA E DA AMPLITUDE: ambas são MEDIDAS na própria captura, não
copiadas do nome do arquivo -- o nome é só uma DICA de onde procurar (janela alvo
± tolerância), porque o operador ajusta o gerador à mão e o valor nominal pedido
nunca é exatamente o injetado. O Welch (flat-top) localiza o tom; a amplitude e a
frequência finais vêm de uma FFT única da captura inteira (``metricas_captura``),
que não depende de onde o tom cai no bin. A diferença importa nos modos de 1 canal
(``externa``/``amplitude``/``osciloscopio``), em que a amplitude é absoluta: o erro do Welch + parabólica
chegava a ~1,8 % e só se cancelava na razão do modo ``shunt``.

SOBRE ``--ganho`` (gotcha de unidades): mesmo significado de ``adc_tool --ganho``
(fator Volts no pino do ADC -> grandeza física; para a sonda, tipicamente
1/sensibilidade_nominal, ex.: 100 mV/A -> 10). O ``ganho(f)`` do perfil é
relativo a ESSE valor: o perfil só é correto se usado depois, em produção, com
o MESMO ``--ganho`` no canal da sonda.

Depende de: ``amostras``, ``canais``, ``cabecalho``, ``constantes``, ``espectro``,
``fundamental``, ``metricas_captura``, ``referencia``, ``erros``.
"""

import csv
import logging
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .amostras import carregar_amostras_bin, converter_para_tensao
from .cabecalho import CABECALHO_TAMANHO_TOTAL, ler_cabecalho
from .canais import analisar_lista_calibracao, desintercalar, resolver_faixas, resolver_offsets_por_canal
from .constantes import GRANDEZA_CORRENTE
from .erros import ErroSHAN
from .espectro import calcular_espectro_welch
from .fundamental import refinar_pico_parabolico
from .metricas_captura import GUARDA_DC, SEMILARGURA_LOBULO, analisar_espectro
from .referencia import ReferenciaCaptura, extrair_referencia

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Arquivo (na pasta de capturas) com as leituras do instrumento externo, uma linha por captura:
# 'arquivo' + 'v_shunt_rms_V' (tensão RMS no shunt, em V -- precisa de --resistencia-shunt) OU
# 'corrente_rms_A' (corrente RMS, em A) OU 'tensao_rms_V' (tensão RMS na entrada de uma cadeia de
# tensão, em V). Escrito por firmware/calibrar_sonda.sh --ref-externa (a coluna depende de --grandeza).
NOME_REFERENCIA_EXTERNA = "referencia_externa.csv"

# Mesmo padrão de nome usado por firmware/calibrar_sonda.sh
# (calibracao_<FREQ>Hz_rep<N>.bin), incluindo a variante "_vM" que
# caminho_disponivel() gera lá para não sobrescrever uma captura anterior.
PADRAO_NOME_CAPTURA = re.compile(r"^calibracao_(\d+)Hz_rep(\d+)(?:_v\d+)?\.bin$")

TOLERANCIA_FREQ_PCT_PADRAO = 10.0
RESOLUCAO_WELCH_CALIBRACAO_PADRAO = 100.0
SOBREPOSICAO_WELCH_CALIBRACAO_PADRAO = 0.75  # mais alta que o padrão de adc_tool.py (0.5): aqui não há restrição de tempo real, e mais sobreposição reduz mais a variância da estimativa sobre a mesma captura
JANELA_CALIBRACAO_PADRAO = "flattop"  # não é o padrão de adc_tool.py (retangular) -- flat-top é a escolha recomendada na literatura de metrologia especificamente para EXATIDÃO DE AMPLITUDE de um tom discreto isolado (ao custo de resolução em frequência, irrelevante aqui: já sabemos a frequência aproximada)
MAX_AMOSTRAS_REFINO = 1 << 22  # amostras por canal usadas no refinamento por FFT única (limita a memória: ~10 s a 400 kS/s)
SNR_MINIMO_DB_PADRAO = 20.0  # um 'tom' precisa se destacar do piso de ruído por pelo menos isso, senão é só o maior bin de ruído (ex.: sonda desconectada) -- ver medir_tom()
DESVIO_ALERTA_PCT = 10.0  # coeficiente de variação do ganho entre repetições acima disso = aviso
FRACAO_SATURACAO_MAXIMA = 0.0005  # fração de amostras brutas no fundo de escala do ADC (código mínimo/máximo) acima da qual a captura é descartada: uma senoide ceifada tem a amplitude subestimada e distorção harmônica, e o ganho medido dela é lixo


# ---------------------------------------------------------------------------
# Descoberta de arquivos e manifesto
# ---------------------------------------------------------------------------

def _referencia_gravada(cabecalho, nome: str, avisar: bool) -> ReferenciaCaptura | None:
    """Referência ``ref: f=.. amp=..`` do cabeçalho; metadado ilegível vale como ausente (com aviso, se pedido)."""
    if cabecalho is None:
        return None
    try:
        return extrair_referencia(cabecalho.descricao)
    except ErroSHAN as e:
        if avisar:
            log.warning(f"'{nome}': metadados 'ref:' ilegíveis, ignorando-os -- {e}")
        return None


def identificar_captura(caminho: Path) -> tuple[float | None, ReferenciaCaptura | None]:
    """(frequência-alvo, referência gravada) de uma captura. A frequência-alvo é só uma DICA de onde procurar
    o tom (a frequência de verdade é medida); vem dos metadados (``ref: f=``) e, na falta deles, do nome
    ``calibracao_<FREQ>Hz_rep<N>.bin``. ``None`` na frequência: a captura não diz qual é."""
    referencia = _referencia_gravada(ler_cabecalho(caminho), caminho.name, avisar=True)
    if referencia is not None and referencia.freq_hz is not None:
        return referencia.freq_hz, referencia
    m = PADRAO_NOME_CAPTURA.match(caminho.name)
    return (float(m.group(1)) if m else None), referencia


def descobrir_capturas(pasta: Path) -> list[Path]:
    """Lista os '.bin' de calibração em 'pasta': os que seguem o padrão de nome de firmware/calibrar_sonda.sh
    E qualquer outro '.bin' cujo cabeçalho traga a frequência injetada (``ref: f=...``) -- com os metadados, o
    nome do arquivo deixa de importar. Não depende do manifesto existir."""
    if not pasta.is_dir():
        raise ErroSHAN(f"'{pasta}' não é uma pasta.")
    arquivos = sorted(
        p for p in pasta.iterdir()
        if p.is_file() and p.suffix.lower() == ".bin" and (
            PADRAO_NOME_CAPTURA.match(p.name)
            or ((r := _referencia_gravada(ler_cabecalho(p), p.name, avisar=False)) is not None and r.freq_hz is not None)
        )
    )
    if not arquivos:
        raise ErroSHAN(
            f"nenhum arquivo 'calibracao_<FREQ>Hz_rep<N>.bin' (nem '.bin' com 'ref: f=...' nos metadados) "
            f"encontrado em '{pasta}'. Essa é a convenção de nome gravada por firmware/calibrar_sonda.sh "
            f"-- confira se a pasta está certa."
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

    refinado = _refinar_tom_por_fft(sinal, fs, freq_medida, 2.0 * resolucao_bin)
    if refinado is not None:
        return refinado
    return freq_medida, amplitude_linear


def _refinar_tom_por_fft(sinal: np.ndarray, fs: float, freq_aprox_hz: float,
                         tolerancia_hz: float) -> tuple[float, float] | None:
    """(freq, amplitude de pico) do tom perto de 'freq_aprox_hz' por FFT ÚNICA sobre a captura inteira
    (janela Kaiser beta=14, energia do lóbulo somada: ``metricas_captura.analisar_espectro``), ou None
    se não der para refinar (captura curta, tom perto demais do DC, ou o pico achado não é o mesmo
    do Welch) -- aí vale a estimativa do Welch.

    Por que refinar: o Welch de ~100 Hz de resolução acha o tom, mas a interpolação parabólica sobre
    o lóbulo largo e achatado da flat-top erra a amplitude em até ~1,8 % (e a frequência em até ~14 Hz)
    quando o tom não cai no centro de um bin -- do tamanho da incerteza do osciloscópio, e erro de
    software que não deveria entrar no perfil. A soma da energia do lóbulo é exata para qualquer
    posição do tom (Parseval; ver o docstring de ``metricas_captura``)."""
    n = min(len(sinal), MAX_AMOSTRAS_REFINO)
    if freq_aprox_hz * n / fs < GUARDA_DC + SEMILARGURA_LOBULO + 2:
        return None
    try:
        espectro = analisar_espectro(sinal[:n], fs, freq_dica=freq_aprox_hz, num_harmonicos=1)
    except ErroSHAN:
        return None
    if not espectro.tem_tom or abs(espectro.freq_tom_hz - freq_aprox_hz) > tolerancia_hz:
        return None
    return espectro.freq_tom_hz, espectro.amplitude_pico


# ---------------------------------------------------------------------------
# Processamento de uma captura individual
# ---------------------------------------------------------------------------

@dataclass
class PontoMedido:
    arquivo: Path
    freq_alvo_hz: float          # só a "dica" (nome do arquivo/manifesto) -- não é a frequência de verdade
    freq_medida_hz: float        # medida de verdade, ver medir_tom()
    amplitude_sonda: float       # já na grandeza física do canal (--ganho aplicado -- ver docstring do módulo)
    amplitude_referencia: float | None  # idem, canal de referência; None se não foi lido (modos de 1 canal)
    referencia_pico: float | None = None  # modos de 1 canal: amplitude REAL do tom (pico), na grandeza física do canal da sonda; preenchida pelo CLI
    referencia_gravada: ReferenciaCaptura | None = None  # o que o cabeçalho da captura diz que foi injetado (ref: f=.. amp=..); preenchida pelo CLI
    # --faixa efetivamente usada em cada papel (None = não lido) e se cada uma é a faixa REAL do ADC gravada
    # no cabeçalho v3 da captura -- vira rastreabilidade no JSON do perfil (calibracao_adc.faixa_v[_confiavel]).
    faixa_referencia: float | None = None
    faixa_sonda: float | None = None
    faixas_confiaveis: tuple[bool, bool] = (False, False)  # (referência, sonda)


def resolver_canais(cabecalho, canal_referencia_cli: int | None, canal_sonda_cli: int | None,
                    exige_referencia: bool = True) -> tuple[int | None, int]:
    """Decide qual canal é referência e qual é sonda. Prioridade: flags
    explícitas > detecção automática pelo cabeçalho v2.

    ``exige_referencia=True`` (modo ``shunt``): a captura precisa ter o canal de
    referência; a detecção automática exige exatamente 2 canais, com um deles de
    grandeza=corrente (== sonda; o outro == referência).

    ``exige_referencia=False`` (modos ``amplitude``/``osciloscopio``/``externa``): só o canal da sonda
    importa e o retorno é ``(canal_referencia_ou_None, canal_sonda)``. Com 1 canal
    no cabeçalho, ele é a sonda; com mais, a sonda é o único de grandeza=corrente
    (ou o dado por ``--canal-sonda``). A referência só aparece se vier de
    ``--canal-referencia``."""
    if not exige_referencia:
        if canal_sonda_cli is not None:
            return canal_referencia_cli, canal_sonda_cli
        if cabecalho is None or cabecalho.versao_cabecalho < 2:
            raise ErroSHAN(
                "captura sem cabeçalho v2 (com grandeza por canal) -- "
                "informe --canal-sonda explicitamente."
            )
        if cabecalho.num_canais == 1:
            return canal_referencia_cli, cabecalho.lista_canais[0]
        indices_corrente = [i for i, g in enumerate(cabecalho.grandeza_por_canal[:cabecalho.num_canais])
                            if g == GRANDEZA_CORRENTE]
        if len(indices_corrente) != 1:
            raise ErroSHAN(
                f"captura com {cabecalho.num_canais} canais e {len(indices_corrente)} marcado(s) como "
                f"corrente no cabeçalho -- não sei qual é a sonda; informe --canal-sonda."
            )
        return canal_referencia_cli, cabecalho.lista_canais[indices_corrente[0]]

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
                       formato: str, faixa_texto: str | None, ganho_texto: str, offset_texto: str | None,
                       tolerancia_pct: float, nome_janela: str, resolucao_hz: float,
                       sobreposicao: float, snr_minimo_db: float = SNR_MINIMO_DB_PADRAO,
                       frequencia_cli: float | None = None) -> PontoMedido | None:
    """Carrega 'caminho', calibra o(s) canal(is) em Volts/Amperes e mede o
    tom em cada um (sonda e, no modo ``shunt``, referência). Devolve None (com
    aviso já impresso) em vez de lançar exceção, para um arquivo ruim não
    derrubar o lote inteiro."""
    cabecalho = ler_cabecalho(caminho)
    offset_amostras = CABECALHO_TAMANHO_TOTAL if cabecalho is not None else 0

    usa_referencia = modo_referencia == "shunt"
    try:
        canal_ref, canal_sonda = resolver_canais(cabecalho, canal_referencia_cli, canal_sonda_cli,
                                                 exige_referencia=usa_referencia)
    except ErroSHAN as e:
        log.warning(f"pulando '{caminho.name}' -- {e}")
        return None
    if not usa_referencia:
        canal_ref = None  # nesses modos o canal de referência (se a captura tiver um) não é lido

    # Ordem de intercalação no arquivo = a lista de canais do cabeçalho (canais
    # habilitados em ordem CRESCENTE de número, imposta pelo ADS8688, ver
    # ler_adc.c). Sem cabeçalho (captura legada), assume exatamente os canais
    # pedidos, em ordem crescente. Usar a lista do cabeçalho -- e não
    # sempre "os 2 canais" -- importa quando --canal-referencia/--canal-sonda
    # são forçados numa captura com MAIS canais: desintercalar e a
    # frequência efetiva (fs_total/n_canais) precisam do número REAL de
    # canais intercalados. As listas de calibração (--faixa/--ganho/--offset)
    # são indexadas por PAPEL, na ordem documentada [referencia, sonda],
    # independente de qual canal tem o número menor -- senão, uma sonda num
    # canal de número menor que o da referência trocaria os valores de papel
    # em silêncio. Sem canal de referência (1 canal), só o valor do papel
    # "sonda" é usado; um único número em --faixa/--ganho vale para os dois.
    if canal_ref is not None and canal_ref == canal_sonda:
        log.warning(f"pulando '{caminho.name}' -- canal de referência e de sonda são o mesmo ({canal_ref}).")
        return None
    papeis = [("referência", canal_ref), ("sonda", canal_sonda)] if canal_ref is not None else [("sonda", canal_sonda)]
    if cabecalho is not None and cabecalho.num_canais > 0:
        canais = list(cabecalho.lista_canais[:cabecalho.num_canais])
    else:
        canais = sorted(c for _, c in papeis)
    ausentes = [c for _, c in papeis if c not in canais]
    if ausentes:
        log.warning(f"pulando '{caminho.name}' -- canal(is) {ausentes} não está(ão) na lista de canais da captura {canais}.")
        return None
    # --faixa por PAPEL [referencia, sonda]: digitada > faixa gravada no cabeçalho v3 (do canal que faz
    # esse papel) > 10,24 (capturas v1/v2). Papel sem canal (1 canal lido) fica "desconhecido".
    faixas_cabecalho_papel = None
    if cabecalho is not None and cabecalho.faixa_adc_codigo_por_canal and len(cabecalho.lista_canais) >= len(canais):
        total_por_canal = dict(zip(cabecalho.lista_canais, cabecalho.faixa_adc_total_v_por_canal))
        faixas_cabecalho_papel = [total_por_canal.get(canal_ref) if canal_ref is not None else None,
                                  total_por_canal.get(canal_sonda)]
    faixas, faixas_confiaveis = resolver_faixas(
        faixa_texto, [canal_ref if canal_ref is not None else canal_sonda, canal_sonda], formato,
        faixas_cabecalho_papel)                                        # [referencia, sonda]
    ganhos = analisar_lista_calibracao(ganho_texto, 2, "--ganho")      # [referencia, sonda]
    offsets = resolver_offsets_por_canal(offset_texto, faixas, formato, 2)  # [referencia, sonda]

    try:
        amostras = carregar_amostras_bin(caminho, formato, offset=offset_amostras)
    except ErroSHAN as e:
        log.warning(f"pulando '{caminho.name}' -- {e}")
        return None

    por_canal_bruto = desintercalar(amostras, canais, [c for _, c in papeis])
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

    # Saturação do ADC (código mínimo/máximo) em qualquer um dos canais lidos.
    limite_inf, limite_sup = (0, 65535) if formato == "uint16" else (-32768, 32767)
    for papel, canal_papel in papeis:
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

    sinal_ref_v = None
    if canal_ref is not None:
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
    if usa_referencia:
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
        faixa_referencia=faixas[0] if usa_referencia else None, faixa_sonda=faixas[1],
        faixas_confiaveis=(faixas_confiaveis[0] if usa_referencia else False, faixas_confiaveis[1]),
    )


# ---------------------------------------------------------------------------
# Referência externa (modo 'externa'): leituras do osciloscópio/multímetro
# ---------------------------------------------------------------------------

def ler_referencia_externa(caminho: Path, resistencia_shunt: float | None) -> dict[str, float]:
    """Lê ``referencia_externa.csv`` e devolve ``{nome_do_arquivo: RMS_da_grandeza_física_injetada}``.

    Colunas: ``arquivo`` e UMA entre ``corrente_rms_A`` (A, RMS), ``tensao_rms_V`` (V, RMS: a tensão na
    entrada de uma cadeia de tensão, usada como está) e ``v_shunt_rms_V`` (tensão RMS no shunt, em V --
    convertida em corrente com ``resistencia_shunt``). Aceita ``,`` ou
    ``;`` como separador (planilhas em pt-BR salvam com ``;`` e vírgula decimal) e
    ignora linhas em branco e comentários (``#``). Se um arquivo aparece mais de uma
    vez, vale a ÚLTIMA linha (``calibrar_sonda.sh`` só acrescenta quando você refaz um
    ponto); uma linha SEM valor anula a leitura anterior daquele arquivo. Valor ausente, não numérico ou não positivo é erro: uma leitura digitada
    errada viraria um ganho errado em silêncio."""
    if not caminho.is_file():
        raise ErroSHAN(
            f"não encontrei o arquivo de referência externa '{caminho}'. Ele é escrito por "
            f"'calibrar_sonda.sh --ref-externa' (uma linha por captura: arquivo,v_shunt_rms_V) "
            f"ou pode ser criado à mão com esse formato."
        )
    linhas = [ln for ln in caminho.read_text(encoding="utf-8-sig").splitlines()
              if ln.strip() and not ln.lstrip().startswith("#")]
    if not linhas:
        raise ErroSHAN(f"'{caminho.name}' está vazio.")
    delimitador = ";" if ";" in linhas[0] else ","
    leitor = csv.DictReader(linhas, delimiter=delimitador)
    colunas = [c.strip() for c in (leitor.fieldnames or [])]
    leitor.fieldnames = colunas
    if "arquivo" not in colunas:
        raise ErroSHAN(f"'{caminho.name}' precisa de uma coluna 'arquivo' (colunas encontradas: {colunas}).")
    if "corrente_rms_A" in colunas:
        coluna, converter = "corrente_rms_A", lambda v: v
    elif "tensao_rms_V" in colunas:
        coluna, converter = "tensao_rms_V", lambda v: v   # cadeia de tensão: a leitura já é a grandeza física
    elif "v_shunt_rms_V" in colunas:
        if resistencia_shunt is None or resistencia_shunt <= 0:
            raise ErroSHAN(
                f"'{caminho.name}' traz a tensão no shunt (v_shunt_rms_V): informe --resistencia-shunt "
                f"com a resistência dele, em ohms, para converter em corrente."
            )
        coluna, converter = "v_shunt_rms_V", lambda v: v / resistencia_shunt
    else:
        raise ErroSHAN(
            f"'{caminho.name}' precisa de uma coluna 'v_shunt_rms_V' (tensão RMS no shunt, V), "
            f"'corrente_rms_A' (corrente RMS, A) ou 'tensao_rms_V' (tensão RMS na entrada de uma cadeia "
            f"de tensão, V); encontradas: {colunas}."
        )

    correntes: dict[str, float] = {}
    for linha in leitor:
        arquivo = (linha.get("arquivo") or "").strip()
        texto = (linha.get(coluna) or "").strip()
        if not arquivo:
            continue
        if not texto:
            correntes.pop(arquivo, None)   # linha em branco = leitura anulada (ponto refeito sem nova leitura)
            continue
        try:
            valor = float(texto.replace(",", ".")) if delimitador == ";" else float(texto)
        except ValueError:
            raise ErroSHAN(f"'{caminho.name}': valor '{texto}' de '{arquivo}' não é um número.") from None
        if not math.isfinite(valor) or valor <= 0:
            raise ErroSHAN(f"'{caminho.name}': o valor de '{arquivo}' ({texto}) precisa ser um número positivo.")
        correntes[arquivo] = converter(valor)
    return correntes


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

    A grandeza real do ponto é ``amplitude_referencia / resistencia_shunt`` no modo ``shunt`` e
    ``referencia_pico`` (já na grandeza física do canal) nos demais; ponto sem ela é descartado.
    """
    por_alvo: dict[float, list[PontoMedido]] = {}
    for p in pontos:
        por_alvo.setdefault(p.freq_alvo_hz, []).append(p)

    perfil_pontos = []
    for freq_alvo, grupo in sorted(por_alvo.items()):
        ganhos, freqs_medidas, nomes = [], [], []
        for p in grupo:
            if modo_referencia == "shunt":
                corrente_real = p.amplitude_referencia / resistencia_shunt
            else:
                corrente_real = p.referencia_pico
            if corrente_real is None or corrente_real <= 0:
                log.warning(f"descartando '{p.arquivo.name}' -- sem amplitude de referência positiva.")
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


# ---------------------------------------------------------------------------
# Resumo da resposta em frequência (o que o perfil diz do conjunto)
# ---------------------------------------------------------------------------

LIMIAR_QUEDA_DB = -3.0
LIMIAR_INCLINACAO_DB = -6.0   # só mede a inclinação final em pontos pelo menos tão atenuados quanto isso
PONTOS_INCLINACAO = 4


@dataclass
class ResumoResposta:
    """Números-resumo do perfil (todos em relação ao ganho de baixa frequência)."""
    ganho_baixa_frequencia: float          # mediana dos pontos até 3x a menor frequência medida: o "0 dB"
    freq_menos3db_hz: float | None         # onde o ganho cai 3 dB (interpolado em log f); None se não cai na faixa medida
    inclinacao_db_oitava: float | None     # regressão dB x log2(f) nos últimos pontos já atenuados >= 6 dB; None se há poucos
    freq_final_hz: float
    ganho_final_db: float                  # no ponto de maior frequência


def resumir_resposta(pontos: list[PontoPerfil]) -> ResumoResposta | None:
    """Quanto o conjunto atenua, e onde: a queda de 3 dB e a inclinação final (um passa-baixa de 2ª ordem
    cai 12 dB/oitava; de 1ª, 6). Serve para conferir a medida contra o que se espera do ADS8688 (~15 kHz)
    e para saber quanto a correção amplifica o ruído em alta frequência. ``None`` com menos de 3 pontos."""
    ordenados = sorted(pontos, key=lambda p: p.freq_hz)
    if len(ordenados) < 3:
        return None
    f = np.array([p.freq_hz for p in ordenados])
    g = np.array([p.ganho for p in ordenados])
    g0 = float(np.median(g[f <= 3.0 * f[0]]))
    if g0 <= 0:
        return None
    db = 20.0 * np.log10(g / g0)

    f3db = None
    abaixo = np.flatnonzero(db <= LIMIAR_QUEDA_DB)
    if abaixo.size and abaixo[0] > 0:
        i = int(abaixo[0])
        x0, x1 = math.log10(f[i - 1]), math.log10(f[i])
        y0, y1 = float(db[i - 1]), float(db[i])
        f3db = 10.0 ** (x0 + (LIMIAR_QUEDA_DB - y0) * (x1 - x0) / (y1 - y0))

    inclinacao = None
    atenuados = np.flatnonzero(db <= LIMIAR_INCLINACAO_DB)
    if atenuados.size >= 3:
        usados = atenuados[-PONTOS_INCLINACAO:]
        inclinacao = float(np.polyfit(np.log2(f[usados]), db[usados], 1)[0])
    return ResumoResposta(g0, f3db, inclinacao, float(f[-1]), float(db[-1]))
