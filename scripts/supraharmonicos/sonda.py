"""Perfis de sonda e correção dependente de frequência.

Ver ``docs/probe-correction-design.md`` (racional) e
``docs/probe-profile-audit.md`` (validações e limitações conhecidas).

Resumo: tensão usa ganho ESCALAR (``--ganho``); uma sonda de corrente atenua
o sinal de forma diferente a cada frequência, então cada canal marcado como
corrente resolve um "perfil de sonda" (JSON com pontos frequência/ganho) e o
sinal é corrigido no domínio da frequência ANTES do resto do pipeline
(recorte de ciclos, FFT/Welch, filtro Butterworth, plotagem) -- nenhuma
dessas etapas precisa saber que existe uma sonda.

Depende de: ``constantes``, ``erros``."""

import datetime
import json
import logging
import re
from pathlib import Path

import numpy as np

from .constantes import NOMES_GRANDEZA_CLI
from .erros import ErroSHAN

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 2.1 Perfis de sonda e correção dependente de frequência
# ---------------------------------------------------------------------------
# Ver docs/probe-correction-design.md para o racional completo desta seção.
#
# Resumo: tensão usa ganho ESCALAR fixo (--ganho, seção 2 acima) -- correto,
# porque o frontend aplica um divisor/ganho constante independente de
# frequência. Uma sonda de corrente, ao contrário, atenua o sinal em
# magnitudes DIFERENTES conforme a frequência -- um escalar não é
# suficiente para caracterizar isso, principalmente na faixa de
# supraharmônicos que é o objeto de estudo deste projeto. Esta seção
# resolve, para cada canal marcado como corrente, um "perfil de sonda"
# (arquivo .json com uma tabela de pontos frequência/ganho) e usa esses
# pontos para corrigir o sinal no domínio da frequência, ANTES do resto do
# pipeline (recorte de ciclos, --fft/--welch, filtro Butterworth opcional
# do usuário, plotagem) -- nenhuma dessas etapas precisa saber que existe
# uma sonda.

# Pasta de perfis usada quando --sondas-dir não é informado: 'scripts/sondas/',
# ao lado da pasta deste pacote (scripts/supraharmonicos/). Só vale para o layout do
# repositório; para outro lugar, use --sondas-dir.
SONDAS_DIR_PADRAO = Path(__file__).resolve().parent.parent / "sondas"

TIPOS_PERFIL_SUPORTADOS = ("resposta_frequencia", "ganho_fixo")

# Id de sonda aceito para montar 'sondas_dir/<id>.json' a partir do cabeçalho:
# começa com letra/dígito, depois só letras, dígitos, '_', '-' e '.'. Exclui
# separadores de caminho (e, junto com o teste de '..' em
# resolver_perfil_canal, qualquer tentativa de sair de sondas_dir).
# o ./coletar.sh sonda já sanitiza para [a-z0-9_-], bem dentro disso.
PADRAO_SONDA_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

# Acima deste reforço (dB) sobre o ruído do ADC, aplicar_correcao_sonda()
# avisa que a correção está amplificando muito o ruído de fundo.
AVISO_AMPLIFICACAO_RUIDO_DB = 20.0
# Um perfil calibrado há mais que isso (contado até a data da captura) ganha um aviso para recalibrar (S8): 1 ano é o
# intervalo usual de calibração de sondas e pontas de prova, e a resposta de uma bobina ou de um divisor muda com a
# temperatura, o envelhecimento e qualquer troca de cabo ou de conector.
IDADE_MAXIMA_PERFIL_DIAS = 365


class PerfilSonda:
    """Perfil de calibração de uma sonda, carregado de um arquivo .json em
    scripts/sondas/ (ou de --sonda-perfil) -- ver carregar_perfil_sonda().

    'tipo' == "resposta_frequencia": o caso principal (sondas de corrente).
    'pontos_freq_hz'/'pontos_ganho' são os pontos de calibração (ganho
    LINEAR, não dB -- ex.: 1.0 = sem atenuação, 0.8 = 80% da amplitude
    ideal), ordenados por frequência crescente. ganho_em() interpola entre
    eles em escala log-frequência/dB (PCHIP, monotônica -- evita overshoot
    de uma spline cúbica comum entre pontos) e mantém constante (clamp) fora
    da faixa coberta pelos pontos -- nunca extrapola livremente, o que
    poderia inverter a tendência real da curva (ver docs/probe-correction-design.md,
    seção 6.2).

    'tipo' == "ganho_fixo": caso trivial (ganho único, sem dependência de
    frequência) -- coberto aqui só por generalidade/completude do conceito
    de "perfil de sensor" (ver proposta, seção 3); na prática, um canal que
    só precisa de ganho fixo normalmente já é coberto por --ganho e não
    precisa de um perfil.
    """

    def __init__(self, id: str, tipo: str, caminho: Path,
                 pontos_freq_hz: np.ndarray, pontos_ganho: np.ndarray,
                 faixa_freq_valida_hz: tuple[float, float] | None = None,
                 calibracao_adc: dict | None = None, data_calibracao: datetime.date | None = None):
        self.id = id
        self.tipo = tipo
        self.caminho = caminho
        self.faixa_freq_valida_hz = faixa_freq_valida_hz
        self.data_calibracao = data_calibracao      # None: perfil sem data (escrito à mão) ou com data ilegível
        self.texto_json: str | None = None          # o arquivo como foi lido (carregar_perfil_sonda): vai para o HDF5
        # Metadado gravado por gerar_perfil_sonda.py (formato/faixa/--ganho de
        # cada canal NA CALIBRAÇÃO) -- usado só por conferir_calibracao_perfil(),
        # nunca na matemática da correção. None em perfis escritos à mão.
        self.calibracao_adc = calibracao_adc
        self._avisou_fora_da_faixa = False  # emite o aviso de "fora da faixa calibrada" só 1x por perfil, não por bin

        if tipo == "resposta_frequencia":
            ordem = np.argsort(pontos_freq_hz)
            self._freqs_pontos = np.asarray(pontos_freq_hz, dtype=np.float64)[ordem]
            ganhos_ordenados = np.asarray(pontos_ganho, dtype=np.float64)[ordem]
            self._ganhos_pontos = ganhos_ordenados
            self._interpolador_db = None    # PCHIP montado no 1º ganho_em(): carregar o perfil não paga o SciPy
            self._freq_min_pontos = float(self._freqs_pontos[0])
            self._freq_max_pontos = float(self._freqs_pontos[-1])
        else:  # "ganho_fixo"
            self._ganho_fixo = float(pontos_ganho[0])

    @property
    def pontos(self) -> tuple[np.ndarray, np.ndarray]:
        """(freq_hz, ganho linear) dos pontos de calibração, em ordem crescente de frequência; para 'ganho_fixo',
        um ponto só em 1 Hz (o ganho vale para toda frequência). Cópias: mexer nelas não muda o perfil."""
        if self.tipo == "ganho_fixo":
            return np.array([1.0]), np.array([self._ganho_fixo])
        return self._freqs_pontos.copy(), self._ganhos_pontos.copy()

    def silenciar_aviso_fora_da_faixa(self) -> None:
        """Para quem só DESENHA a curva (ex.: gráfico de diagnóstico do gerador de
        perfil): o aviso de 'fora da faixa calibrada' é para análises, não para plotagem."""
        self._avisou_fora_da_faixa = True

    def ganho_em(self, freqs_hz: np.ndarray) -> np.ndarray:
        """Ganho LINEAR (não dB) interpolado em cada frequência de
        'freqs_hz' (array numpy, Hz). Para 'ganho_fixo', devolve o mesmo
        valor em todo bin. Para 'resposta_frequencia', clampa qualquer
        frequência fora de [freq_min_pontos, freq_max_pontos] no valor do
        ponto extremo mais próximo -- inclui o bin de DC (0 Hz), que nunca
        está entre os pontos de calibração."""
        freqs_hz = np.asarray(freqs_hz, dtype=np.float64)

        if self.tipo == "ganho_fixo":
            return np.full_like(freqs_hz, self._ganho_fixo)

        freqs_clampadas = np.clip(freqs_hz, self._freq_min_pontos, self._freq_max_pontos)
        if not self._avisou_fora_da_faixa:
            # Faixa de validade: a declarada no perfil (faixa_freq_valida_hz,
            # que o operador pode ter estreitado de propósito) ou, na falta
            # dela, a faixa coberta pelos pontos. O bin de DC (0 Hz) nunca
            # conta: nenhuma calibração por tom o cobre, e contá-lo fazia o
            # aviso disparar em TODA execução, mesmo com a banda de interesse
            # inteira dentro da curva -- o que ensina o operador a ignorá-lo.
            faixa_lo, faixa_hi = self.faixa_freq_valida_hz or (self._freq_min_pontos, self._freq_max_pontos)
            positivas = freqs_hz > 0.0
            abaixo = positivas & (freqs_hz < faixa_lo)
            acima = freqs_hz > faixa_hi
            if np.any(abaixo) or np.any(acima):
                partes = []
                if np.any(abaixo):
                    dica_rede = " -- inclui a fundamental da rede (50/60 Hz); calibre um ponto em ~50 Hz" if faixa_lo > 50.0 else ""
                    partes.append(f"{int(np.count_nonzero(abaixo))} abaixo de {faixa_lo:g} Hz{dica_rede}")
                if np.any(acima):
                    partes.append(f"{int(np.count_nonzero(acima))} acima de {faixa_hi:g} Hz")
                log.warning(
                    f"sonda '{self.id}' ({self.caminho}) -- "
                    f"componentes de frequência da análise fora da faixa "
                    f"válida [{faixa_lo:g}, {faixa_hi:g}] Hz ("
                    f"{'; '.join(partes)}). O ganho nessas frequências foi "
                    f"mantido constante (igual ao do ponto calibrado mais "
                    f"próximo), não extrapolado -- se a sonda continua "
                    f"atenuando além do último ponto, a amplitude corrigida "
                    f"ali fica ABAIXO do valor real. Adicione pontos de "
                    f"calibração cobrindo essa faixa se precisar de exatidão "
                    f"ali."
                )
                self._avisou_fora_da_faixa = True

        if self._interpolador_db is None:
            # extrapolate=False -> PchipInterpolator devolve NaN fora do domínio dos pontos; o clamp acima já
            # garante que nada sai dele, então é só uma segunda trava de segurança.
            from scipy.interpolate import PchipInterpolator  # sob demanda: só quem calcula paga o SciPy
            self._interpolador_db = PchipInterpolator(
                np.log10(self._freqs_pontos), 20.0 * np.log10(self._ganhos_pontos), extrapolate=False
            )
        ganho_db = self._interpolador_db(np.log10(freqs_clampadas))
        return 10.0 ** (ganho_db / 20.0)


def carregar_perfil_sonda(caminho: Path) -> PerfilSonda:
    """Lê e valida um arquivo de perfil de sonda (.json) -- ver
    docs/probe-correction-design.md, seção 3, para o formato completo.
    Campos mínimos: 'id', 'tipo', e os campos específicos de 'tipo'
    ('pontos': lista de {"freq_hz": ..., "ganho": ...} para
    'resposta_frequencia'; 'ganho' escalar para 'ganho_fixo')."""
    try:
        with open(caminho, encoding="utf-8") as f:
            texto = f.read()
        dados = json.loads(texto)
    except FileNotFoundError:
        raise ErroSHAN(f"arquivo de perfil de sonda '{caminho}' não encontrado.")
    except json.JSONDecodeError as e:
        raise ErroSHAN(f"'{caminho}' não é um JSON válido ({e}).")

    if not isinstance(dados, dict):
        raise ErroSHAN(f"perfil '{caminho}' precisa ser um objeto JSON ({{...}}), não {type(dados).__name__}.")
    for campo in ("id", "tipo"):
        if campo not in dados:
            raise ErroSHAN(f"perfil '{caminho}' não tem o campo obrigatório '{campo}'.")
    if not isinstance(dados["id"], str):
        raise ErroSHAN(f"campo 'id' de '{caminho}' precisa ser texto.")

    tipo = dados["tipo"]
    if tipo not in TIPOS_PERFIL_SUPORTADOS:
        raise ErroSHAN(
            f"tipo de perfil '{tipo}' em '{caminho}' não suportado "
            f"por esta versão de adc_tool.py -- tipos aceitos: "
            f"{', '.join(repr(t) for t in TIPOS_PERFIL_SUPORTADOS)}. (Tipos "
            f"como 'polinomio'/'tabela', para sensores de temperatura, "
            f"ainda são trabalho futuro -- ver docs/probe-correction-design.md.)"
        )

    faixa_freq_valida_hz = None
    if tipo == "resposta_frequencia":
        pontos = dados.get("pontos", [])
        if len(pontos) < 2:
            raise ErroSHAN(
                f"perfil '{caminho}' é do tipo 'resposta_frequencia' "
                f"mas tem só {len(pontos)} ponto(s) de calibração -- são "
                f"necessários pelo menos 2 para interpolar."
            )
        try:
            freqs = np.array([float(p["freq_hz"]) for p in pontos], dtype=np.float64)
            ganhos = np.array([float(p["ganho"]) for p in pontos], dtype=np.float64)
        except (KeyError, TypeError, ValueError) as e:
            raise ErroSHAN(f"ponto de calibração inválido em '{caminho}' ({e}).")
        # json.load aceita NaN/Infinity (extensão não padrão do módulo json do
        # Python): "nan <= 0" é False, então sem esta checagem um ganho NaN
        # passava pelas validações abaixo e só estourava dentro do SciPy, com
        # um traceback de ValueError em vez de uma mensagem clara.
        if not (np.all(np.isfinite(freqs)) and np.all(np.isfinite(ganhos))):
            raise ErroSHAN(f"'freq_hz'/'ganho' em '{caminho}' precisam ser números finitos (encontrado NaN ou infinito).")
        if np.any(freqs <= 0):
            raise ErroSHAN(f"'freq_hz' em '{caminho}' precisa ser positivo em todo ponto (DC não é calibrável por interpolação log-frequência).")
        if np.any(ganhos <= 0):
            raise ErroSHAN(f"'ganho' em '{caminho}' precisa ser positivo em todo ponto.")
        if len(set(freqs.tolist())) != len(freqs):
            raise ErroSHAN(f"'freq_hz' repetida em algum ponto de '{caminho}' -- cada frequência deve aparecer uma única vez.")
        faixa_bruta = dados.get("faixa_freq_valida_hz")
        if faixa_bruta is not None:
            try:
                faixa_freq_valida_hz = (float(faixa_bruta[0]), float(faixa_bruta[1]))
            except (TypeError, ValueError, IndexError, KeyError):
                raise ErroSHAN(f"'faixa_freq_valida_hz' em '{caminho}' precisa ser uma lista [min_hz, max_hz].")
            if not (np.isfinite(faixa_freq_valida_hz[0]) and np.isfinite(faixa_freq_valida_hz[1])
                    and 0 < faixa_freq_valida_hz[0] < faixa_freq_valida_hz[1]):
                raise ErroSHAN(f"'faixa_freq_valida_hz' em '{caminho}' precisa ter 0 < min < max (valores finitos).")
    else:  # "ganho_fixo"
        if "ganho" not in dados:
            raise ErroSHAN(f"perfil '{caminho}' do tipo 'ganho_fixo' precisa do campo 'ganho'.")
        try:
            ganho_unico = float(dados["ganho"])
        except (TypeError, ValueError) as e:
            raise ErroSHAN(f"'ganho' inválido em '{caminho}' ({e}).")
        if not np.isfinite(ganho_unico) or ganho_unico <= 0:
            raise ErroSHAN(f"'ganho' em '{caminho}' precisa ser um número finito e positivo.")
        freqs = np.array([1.0])       # não usado para ganho_fixo -- só para uma assinatura uniforme do construtor
        ganhos = np.array([ganho_unico])

    calibracao_adc = dados.get("calibracao_adc")
    if not isinstance(calibracao_adc, dict):
        calibracao_adc = None  # ausente (perfil escrito à mão) ou malformado: a conferência em main() simplesmente não acontece

    perfil = PerfilSonda(
        id=dados["id"], tipo=tipo, caminho=caminho,
        pontos_freq_hz=freqs, pontos_ganho=ganhos,
        faixa_freq_valida_hz=faixa_freq_valida_hz,
        calibracao_adc=calibracao_adc,
        data_calibracao=_data_iso(dados.get("data_calibracao")),
    )
    perfil.texto_json = texto
    return perfil


def _data_iso(valor) -> datetime.date | None:
    """'AAAA-MM-DD' (o que o gerar_perfil_sonda grava) -> date; qualquer outra coisa (ausente, número, o modelo
    'AAAA-MM-DD' do exemplo) -> None. O formato é conferido aqui porque o ``fromisoformat`` do Python 3.11+ aceita
    mais formas que o do 3.10."""
    if not isinstance(valor, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        return None
    try:
        return datetime.date.fromisoformat(valor)
    except ValueError:
        return None


def conferir_idade_perfil(perfil: PerfilSonda, canal: int, data_captura: datetime.date | None = None,
                          limite_dias: int = IDADE_MAXIMA_PERFIL_DIAS) -> int | None:
    """Avisa (nunca aborta) se o perfil foi calibrado mais de ``limite_dias`` antes da captura (ou de hoje, sem a
    data da captura). Devolve a idade em dias, ou None se o perfil não diz quando foi calibrado."""
    if perfil.data_calibracao is None:
        return None
    referencia = data_captura or datetime.date.today()
    idade = (referencia - perfil.data_calibracao).days
    if idade > limite_dias:
        log.warning(f"canal {canal}: o perfil '{perfil.id}' foi calibrado em {perfil.data_calibracao.isoformat()}, "
                    f"{idade} dias antes da captura (mais de {limite_dias}): a sonda pode ter mudado; recalibre "
                    f"(roteiro, T10) antes de usar o resultado num trabalho.")
    return idade


def analisar_overrides_por_canal(texto: str, nome_flag: str) -> dict[int, str]:
    """Interpreta flags no formato 'canal:valor[,canal:valor...]' (mesma
    sintaxe de --grandeza/--sonda em ler_adc.c) -- usado por --grandeza e
    --sonda-perfil neste script. Devolve {canal: valor_bruto_em_texto},
    deixando a interpretação do valor (grandeza conhecida? caminho de
    arquivo?) para o chamador, que conhece o contexto de cada flag."""
    overrides: dict[int, str] = {}
    for token in texto.split(","):
        token = token.strip()
        if not token:
            continue
        if ":" not in token:
            raise ErroSHAN(
                f"'{token}' em {nome_flag} precisa estar no formato "
                f"'canal:valor' (ex.: '1:corrente')."
            )
        canal_txt, valor_txt = token.split(":", 1)
        try:
            canal = int(canal_txt.strip())
        except ValueError:
            raise ErroSHAN(f"'{canal_txt}' não é um canal válido em {nome_flag}.")
        overrides[canal] = valor_txt.strip()
    return overrides


def analisar_overrides_grandeza(texto: str) -> dict[int, int]:
    """--grandeza CANAL:tensao|corrente|temperatura[,...] -- mesma sintaxe e
    mesmos nomes aceitos de --grandeza em ler_adc.c."""
    brutos = analisar_overrides_por_canal(texto, "--grandeza")
    resultado = {}
    for canal, valor_txt in brutos.items():
        if valor_txt not in NOMES_GRANDEZA_CLI:
            raise ErroSHAN(
                f"grandeza '{valor_txt}' desconhecida em --grandeza "
                f"(canal {canal}) -- use 'tensao', 'corrente' ou "
                f"'temperatura'."
            )
        resultado[canal] = NOMES_GRANDEZA_CLI[valor_txt]
    return resultado


def analisar_overrides_perfil(texto: str) -> dict[int, Path]:
    """--sonda-perfil CANAL:ARQUIVO[,...] -- aponta diretamente para um
    arquivo de perfil, sem depender do sonda_id do cabeçalho nem de
    --sondas-dir. Maior prioridade na resolução (ver resolver_perfil_canal)."""
    brutos = analisar_overrides_por_canal(texto, "--sonda-perfil")
    return {canal: Path(caminho_txt) for canal, caminho_txt in brutos.items()}


def resolver_perfil_canal(canal: int, sonda_id: str, overrides_perfil: dict[int, Path],
                           sondas_dir: Path) -> PerfilSonda | None:
    """Resolve o perfil de sonda para 'canal', na mesma hierarquia de 3
    níveis já usada em --canais/--faixa/--ganho: --sonda-perfil explícito
    (maior prioridade) > sonda_id do cabeçalho da captura + busca em
    'sondas_dir/<id>.json' > None (nenhum perfil resolvido -- quem chama
    decide o que fazer, ver main())."""
    if canal in overrides_perfil:
        return carregar_perfil_sonda(overrides_perfil[canal])
    if sonda_id:
        # O id vem de 32 bytes de um '.bin' que pode ter sido gravado por
        # outra pessoa/máquina, e ler_adc.c não valida os caracteres (só o
        # tamanho). Sem esta checagem, um id como '../x' ou '/etc/foo' faria
        # 'sondas_dir / "<id>.json"' sair de sondas_dir (um caminho absoluto
        # à direita do operador '/' substitui o da esquerda).
        if not PADRAO_SONDA_ID.match(sonda_id) or ".." in sonda_id:
            raise ErroSHAN(
                f"canal {canal} tem o id de sonda '{sonda_id}' no "
                f"cabeçalho da captura, que não é um nome de arquivo seguro "
                f"(só letras, dígitos, '_', '-' e '.' no meio; sem '/', '\\' "
                f"nem '..'). Use --sonda-perfil {canal}:ARQUIVO para indicar "
                f"o perfil explicitamente."
            )
        caminho = sondas_dir / f"{sonda_id}.json"
        if not caminho.exists():
            raise ErroSHAN(
                f"canal {canal} tem a sonda '{sonda_id}' registrada "
                f"no cabeçalho da captura, mas não existe um perfil em "
                f"'{caminho}'. Crie o arquivo, aponte --sondas-dir para "
                f"onde os perfis estão, ou use --sonda-perfil "
                f"{canal}:ARQUIVO para indicar um arquivo específico."
            )
        perfil = carregar_perfil_sonda(caminho)
        if perfil.id != sonda_id:
            log.warning(
                f"canal {canal}: o cabeçalho da captura registra a "
                f"sonda '{sonda_id}', mas o arquivo '{caminho}' declara "
                f"id='{perfil.id}' -- confira se não é o perfil de outra "
                f"sonda (arquivo copiado/renomeado)."
            )
        return perfil
    return None


def conferir_calibracao_perfil(perfil: PerfilSonda, canal: int, formato: str,
                                faixa: float, ganho: float, faixa_confiavel: bool = False) -> None:
    """Avisa (nunca aborta) se o perfil foi gerado sob uma calibração de ADC
    diferente da usada AGORA para o canal. O ganho(f) de um perfil é
    RELATIVO ao --ganho (e depende de --faixa/--formato) com que foi medido
    (ver gerar_perfil_sonda.py, seção --ganho): usá-lo com outro --ganho
    multiplica toda a corrente corrigida, sem qualquer outro sintoma -- o
    erro seria silencioso. Só confere o que gerar_perfil_sonda.py grava em
    'calibracao_adc'; perfil sem esse bloco (escrito à mão) não é conferido.

    ``faixa_confiavel``: a ``faixa`` do canal AGORA é a faixa real do ADC
    (veio do cabeçalho v3 da captura). Se o perfil também foi gerado assim
    (``calibracao_adc.faixa_v_confiavel.sonda``), os dois já estão em Volts
    reais do pino e uma faixa diferente (ex.: ±2,56 V na produção, ±10,24 V
    na geração) NÃO muda a escala -- seria um falso alarme, então a
    comparação de faixa é dispensada."""
    cal = perfil.calibracao_adc
    if not cal:
        return
    problemas = []
    try:
        ganho_perfil = cal.get("ganho", {}).get("sonda")
        if ganho_perfil is not None and not np.isclose(float(ganho_perfil), ganho, rtol=1e-3, atol=0.0):
            problemas.append(
                f"--ganho do canal = {ganho:g}, mas o perfil foi gerado com "
                f"{float(ganho_perfil):g} -- as amplitudes corrigidas saem "
                f"multiplicadas por {ganho / float(ganho_perfil):.4g}"
            )
        faixa_perfil = cal.get("faixa_v", {}).get("sonda")
        ambas_reais = faixa_confiavel and bool(cal.get("faixa_v_confiavel", {}).get("sonda"))
        if faixa_perfil is not None and not ambas_reais and not np.isclose(float(faixa_perfil), faixa, rtol=1e-3, atol=0.0):
            problemas.append(
                f"--faixa do canal = {faixa:g} V, mas o perfil foi gerado com "
                f"{float(faixa_perfil):g} V -- as amplitudes saem "
                f"multiplicadas por {faixa / float(faixa_perfil):.4g}"
            )
        formato_perfil = cal.get("formato")
        if formato_perfil is not None and formato_perfil != formato:
            problemas.append(f"--formato = {formato}, mas o perfil foi gerado com {formato_perfil}")
    except (AttributeError, TypeError, ValueError):
        return  # bloco calibracao_adc malformado -- não vale derrubar a análise por causa de um metadado
    for problema in problemas:
        log.warning(
            f"canal {canal}, sonda '{perfil.id}': {problema}. Use a "
            f"mesma calibração da geração do perfil, ou gere o perfil de novo."
        )


def aplicar_correcao_sonda(sinal: np.ndarray, fs: float, perfil: PerfilSonda) -> np.ndarray:
    """Corrige 'sinal' (já em Volts/Ampères pela calibração --faixa/--ganho/
    --offset, ainda SEM a resposta em frequência da sonda) pela curva de
    'perfil', por divisão espectral direta: FFT do sinal INTEIRO
    selecionado, escala cada bin por 1/ganho(f) interpolado, IFFT de volta
    ao tempo. Aplicada UMA vez, antes de qualquer outra etapa do pipeline
    (recorte de ciclos, --fft/--welch, filtro Butterworth opcional do
    usuário, plotagem) -- nenhuma delas precisa saber que existe uma sonda.

    Por que espectral em vez de um filtro FIR/IIR no tempo: como a correção
    aqui é só de MAGNITUDE (ganho real e positivo por bin, sem alterar
    fase -- suficiente hoje, já que todo o pipeline de análise trabalha só
    com amplitude em dB), a divisão espectral direta É, matematicamente, a
    aplicação de um filtro de fase zero com exatamente a resposta desejada
    -- sem o trabalho extra de projetar um FIR (scipy.signal.firwin2) que
    aproximaria a mesma coisa. Reaproveita rfft/rfftfreq já usados no resto
    do script (ver docs/probe-correction-design.md, seção 6.2, para a
    alternativa por FIR considerada e por que foi preterida aqui).

    LIMITAÇÃO (medida na auditoria, ver docs/probe-profile-audit.md): a
    correção restaura a AMPLITUDE de cada componente espectral (erro < 0.1%
    em tons de teste), mas NÃO a fase -- a fase da sonda real continua no
    sinal. A forma de onda no tempo do canal corrigido, portanto, não é a
    corrente verdadeira (numa sonda passa-baixa de 1ª ordem com fc=30 kHz, o
    erro RMS da forma de onda de uma soma de tons de 2.5-40 kHz chega a ~40%,
    com a amplitude de cada tom exata). Serve para espectro/Welch/picos;
    NÃO use o sinal corrigido para grandezas que dependem de fase entre
    canais (potência ativa/impedância em supraharmônicos) sem uma calibração
    de fase.

    Espera um sinal já centrado o bastante para caber inteiro na FFT de uma
    vez -- consistente com o resto do modo de plotagem deste script, que já
    carrega o trecho selecionado (--inicio/--fim) inteiro num ndarray antes
    de --fft/--welch/plot (só os modos de conversão e exportação HDF5
    processam em blocos, e nenhum dos dois aplica correção de sonda -- ver
    seção 6 de docs/probe-correction-design.md para essa decisão de
    escopo)."""
    n = len(sinal)
    # Tamanho de FFT "rápido" (só fatores 2/3/5/7...): com N de fator primo
    # grande (ex.: um --inicio/--fim arbitrário) a FFT cai no algoritmo de
    # Bluestein, ~8x mais lenta nas medições deste projeto (N=2000003:
    # 1.74 s vs 0.20 s; N já "rápido" não muda). O sinal é
    # completado com zeros até esse tamanho e o resultado recortado de volta
    # a N -- a divisão por ganho(f) acontece na grade do tamanho maior.
    from scipy.fft import irfft, next_fast_len, rfft, rfftfreq  # sob demanda: só quem calcula paga o SciPy
    n_fft = next_fast_len(n, real=True)
    espectro = rfft(sinal, n=n_fft)
    freqs = rfftfreq(n_fft, 1.0 / fs)
    ganho = perfil.ganho_em(freqs)

    # Diagnóstico: onde 1/ganho(f) é grande, o ruído do ADC (que NÃO passou
    # pela sonda) é amplificado junto com o sinal -- o piso de ruído, em
    # Amperes, sobe por esse fator. Não é erro (é físico), mas quem lê o
    # espectro corrigido precisa saber. Ignora o bin de DC.
    if len(ganho) > 1:
        i_min = 1 + int(np.argmin(ganho[1:]))
        reforco_db = -20.0 * np.log10(ganho[i_min])
        if reforco_db > AVISO_AMPLIFICACAO_RUIDO_DB:
            log.warning(
                f"sonda '{perfil.id}': a correção amplifica o ruído do "
                f"ADC em até {reforco_db:.1f} dB (em {freqs[i_min]:g} Hz, onde "
                f"o ganho da sonda é {ganho[i_min]:.3g}). O piso de ruído (na "
                f"grandeza física do canal) nessa região é correspondentemente maior -- "
                f"componentes fracas ali podem estar abaixo do que o "
                f"espectro corrigido sugere."
            )

    espectro_corrigido = espectro / ganho
    return irfft(espectro_corrigido, n=n_fft)[:n]
