"""Referência conhecida de uma captura: amplitude com unidades, frequência e o marcador ``ref:`` dos metadados.

Quando o sinal injetado é uma senoide pura de amplitude e frequência CONHECIDAS (as
que o operador ajustou no gerador), esses dois números viram a referência do perfil
da sonda: ``ganho(f) = amplitude medida / amplitude injetada``. Este módulo cuida de
três coisas pequenas e fáceis de errar:

1. **Ler amplitudes com unidade** (``500mVpp``, ``250mVpk``, ``0,1767Vrms``, ``2Arms``):
   :func:`analisar_amplitude`. A ambiguidade pico / pico a pico / eficaz é um fator 2
   ou 1,41 que passaria em silêncio, então uma amplitude com unidade EXIGE dizer qual
   é; só um número puro (sem unidade nem tipo) é aceito, por compatibilidade, e vale
   como pico em Amperes.
2. **Gravar e ler a referência nos metadados da captura.** O cabeçalho do ``.bin``
   tem um campo de descrição de 256 bytes (``ler_adc -d``). A convenção é um trecho
   ``ref: f=1000Hz amp=500mVpp`` (:func:`formatar_referencia` escreve,
   :func:`extrair_referencia` lê; texto livre antes ou depois é ignorado). Assim cada
   captura carrega o que foi injetado nela e o nome do arquivo deixa de ser a fonte
   da verdade.
3. **Passar a amplitude para a grandeza física do canal** (:func:`pico_fisico`): uma
   amplitude em V é a tensão no ponto onde o ``--ganho`` do canal é aplicado, então
   a grandeza física verdadeira é ``V * ganho``; uma amplitude em A já é a grandeza
   física. A conta é a mesma do ganho do perfil (relativo ao ``--ganho``).

Premissa: o sinal injetado é uma SENOIDE pura. Pico a pico e eficaz só se convertem
em pico com ``pp = 2*pico`` e ``rms = pico/sqrt(2)``, que valem para senoide.

Depende de: ``erros``.
"""

import math
import re
from dataclasses import dataclass

from .erros import ErroSHAN

# Prefixos aceitos (sem 'p' de pico e sem 'M': 'pp' e 'pk' são tipos de amplitude, e ninguém injeta megavolts).
PREFIXOS_AMPLITUDE = {"n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "k": 1e3}
PREFIXOS_FREQUENCIA = {"k": 1e3, "K": 1e3, "M": 1e6}

TIPO_PICO = "pico"
TIPO_PICO_A_PICO = "pp"
TIPO_RMS = "rms"

_NUMERO = r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?"
_TIPOS = {
    "pk-pk": TIPO_PICO_A_PICO, "pkpk": TIPO_PICO_A_PICO, "pico-a-pico": TIPO_PICO_A_PICO,
    "p-p": TIPO_PICO_A_PICO, "p2p": TIPO_PICO_A_PICO, "pp": TIPO_PICO_A_PICO,
    "peak": TIPO_PICO, "pico": TIPO_PICO, "pk": TIPO_PICO, "p": TIPO_PICO,
    "rms": TIPO_RMS, "eficaz": TIPO_RMS,
}
_RE_AMPLITUDE = re.compile(
    rf"^\s*(?P<num>{_NUMERO})\s*(?P<prefixo>(?-i:[nuµμmk])?)(?P<unidade>[VvAa]?)[\s_]*"
    rf"(?P<tipo>{'|'.join(sorted(_TIPOS, key=len, reverse=True))})?\s*$",
    re.IGNORECASE,
)
_RE_FREQUENCIA = re.compile(rf"^\s*(?P<num>{_NUMERO})\s*(?P<prefixo>[kKM]?)\s*(?:[Hh][Zz])?\s*$")

# 'ref:' seguido de pares chave=valor sem espaços; o resto da descrição (texto livre) é ignorado.
_RE_MARCADOR = re.compile(r"(?:^|[\s;,])ref:\s*(?P<pares>(?:\w+=\S+\s*)+)", re.IGNORECASE)
_RE_PAR = re.compile(r"(\w+)=(\S+)")

EXEMPLOS_AMPLITUDE = "500mVpp, 250mVpk, 176.8mVrms, 2Arms"


def _numero(texto: str) -> float:
    return float(texto.replace(",", "."))


@dataclass(frozen=True)
class Amplitude:
    """Amplitude de uma senoide: ``pico`` na unidade-base (V ou A), mais o texto original."""
    pico: float
    unidade: str        # "V" ou "A"
    tipo: str           # como foi dada: TIPO_PICO, TIPO_PICO_A_PICO ou TIPO_RMS
    texto: str          # o que o operador escreveu (vai para os metadados e para o perfil)

    @property
    def pico_a_pico(self) -> float:
        return 2.0 * self.pico

    @property
    def rms(self) -> float:
        return self.pico / math.sqrt(2.0)

    def __str__(self) -> str:
        return f"{self.texto} (pico {self.pico:.6g} {self.unidade})"


def analisar_amplitude(texto: str) -> Amplitude:
    """Amplitude com unidade (``500mVpp``, ``0,25Vpk``, ``1.2Arms``) -> :class:`Amplitude` em pico.

    Aceita prefixo ``n``, ``u``/``µ``, ``m`` ou ``k``; unidade ``V`` ou ``A``; tipo ``pp`` (pico a pico),
    ``pk``/``p``/``pico`` (pico) ou ``rms``/``eficaz``. Espaços e ``_`` entre as partes são ignorados e a
    vírgula decimal vale. Um número puro (``0.5``) é pico em Amperes, como era antes de haver unidades.
    Unidade sem tipo (``500mV``) ou tipo sem unidade (``2rms``) é erro: o fator 2 ou 1,41 que isso
    esconde viraria um erro de ganho silencioso."""
    original = (texto or "").strip()
    m = _RE_AMPLITUDE.match(original)
    if m is None:
        raise ErroSHAN(f"amplitude '{original}' não entendida; use número + unidade + tipo (ex.: {EXEMPLOS_AMPLITUDE}).")
    valor = _numero(m["num"])
    prefixo, unidade, tipo = m["prefixo"], m["unidade"].upper(), m["tipo"]
    if not math.isfinite(valor) or valor <= 0:
        raise ErroSHAN(f"amplitude '{original}': o valor precisa ser um número positivo.")
    if not prefixo and not unidade and not tipo:
        return Amplitude(pico=valor, unidade="A", tipo=TIPO_PICO, texto=original)      # número puro: pico em A
    if not unidade:
        raise ErroSHAN(f"amplitude '{original}' sem unidade; diga se é V ou A (ex.: {EXEMPLOS_AMPLITUDE}).")
    if not tipo:
        raise ErroSHAN(
            f"amplitude '{original}' sem tipo: diga se é pico a pico (pp), pico (pk) ou eficaz (rms), "
            f"ex.: 500mVpp. Sem isso o resultado erraria por um fator 2 ou 1,41."
        )
    tipo = _TIPOS[tipo.lower()]
    valor *= PREFIXOS_AMPLITUDE.get(prefixo, 1.0)
    pico = {TIPO_PICO: valor, TIPO_PICO_A_PICO: valor / 2.0, TIPO_RMS: valor * math.sqrt(2.0)}[tipo]
    return Amplitude(pico=pico, unidade=unidade, tipo=tipo, texto=original)


def analisar_frequencia(texto: str) -> float:
    """Frequência em Hz a partir de ``1000``, ``1000Hz``, ``1.5kHz`` ou ``2MHz`` (``k``/``M``; sem milihertz)."""
    original = (texto or "").strip()
    m = _RE_FREQUENCIA.match(original)
    if m is None:
        raise ErroSHAN(f"frequência '{original}' não entendida; use um número em Hz (ex.: 1000Hz, 1.5kHz, 2MHz).")
    valor = _numero(m["num"]) * PREFIXOS_FREQUENCIA.get(m["prefixo"], 1.0)
    if not math.isfinite(valor) or valor <= 0:
        raise ErroSHAN(f"frequência '{original}': o valor precisa ser um número positivo.")
    return valor


def pico_fisico(amplitude: Amplitude, ganho: float) -> float:
    """Amplitude de PICO na grandeza física do canal. Em V: ``V * ganho`` (o ``--ganho`` leva a tensão no
    ponto de injeção à grandeza física); em A: o próprio valor."""
    return amplitude.pico * ganho if amplitude.unidade == "V" else amplitude.pico


@dataclass(frozen=True)
class ReferenciaCaptura:
    """O que o operador injetou, como gravado nos metadados da captura (qualquer campo pode faltar)."""
    freq_hz: float | None = None
    amplitude: Amplitude | None = None


def formatar_referencia(freq_hz: float | None = None, amplitude: str | None = None) -> str:
    """Trecho de metadados ``ref: f=1000Hz amp=500mVpp`` (só os campos dados). A amplitude é validada
    e não pode ter espaços (o marcador é lido por pares ``chave=valor``)."""
    partes = []
    if freq_hz is not None:
        analisar_frequencia(str(freq_hz))
        partes.append(f"f={freq_hz:.10g}Hz")
    if amplitude is not None:
        analisar_amplitude(amplitude)
        if re.search(r"\s", amplitude.strip()):
            raise ErroSHAN(f"amplitude '{amplitude}': sem espaços nos metadados (ex.: 500mVpp).")
        partes.append(f"amp={amplitude.strip()}")
    return "ref: " + " ".join(partes) if partes else ""


def extrair_referencia(descricao: str | None) -> ReferenciaCaptura | None:
    """Lê o trecho ``ref: f=... amp=...`` da descrição do cabeçalho. ``None`` se não há marcador (ou nenhum
    campo conhecido). Chaves desconhecidas são ignoradas; valor ilegível levanta ``ErroSHAN`` com a captura
    por identificar -- quem chama decide se pula o arquivo."""
    achado = _RE_MARCADOR.search(descricao or "")
    if achado is None:
        return None
    pares = {k.lower(): v.rstrip(";,") for k, v in _RE_PAR.findall(achado["pares"])}
    freq = analisar_frequencia(pares["f"]) if "f" in pares else None
    amplitude = analisar_amplitude(pares["amp"]) if "amp" in pares else None
    if freq is None and amplitude is None:
        return None
    return ReferenciaCaptura(freq_hz=freq, amplitude=amplitude)
