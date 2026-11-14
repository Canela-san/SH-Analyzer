"""A cadeia de transformações de um traço (docs/gui-plan.md, 7.2): as etapas, a prévia e o processamento em blocos.

**As etapas.** Cada uma é imutável, valida os seus parâmetros na criação (:class:`EtapaInvalida`, com o motivo) e
declara a sua classe:

* :class:`Filtro` (com memória): o Butterworth de fase zero do motor (passa-baixas, passa-altas, passa-faixa,
  rejeita-faixa), o ``--filtro-passa-*`` do ``adc_tool``;
* :class:`CorrecaoSonda` (com memória): o perfil de sonda pela divisão espectral do motor; automática (o perfil que a
  captura registra para o canal) ou com um perfil escolhido;
* :class:`RemoverDC` (afim): tira a média **do canal inteiro** (e não a de cada trecho, que mudaria a cada pan),
  passada pelo ganho em DC das etapas de antes. Sem a média do canal (``ContextoDaCadeia.media``), tira a do trecho.

**O vetor inteiro é a referência.** :meth:`Cadeia.aplicar` aplica as etapas ligadas, na ordem, a um trecho inteiro,
como a CLI faz com o ``--inicio``/``--fim``: a correção de sonda e depois os filtros dão os números do ``adc_tool``.

**A prévia e os blocos.** Uma etapa com memória mistura as amostras vizinhas até uma distância, a sua **margem**: a
de um filtro sai da sua resposta ao impulso (até a soma da cauda ficar abaixo de 1e-12 da soma inteira); a da
correção de sonda, do alcance da IFFT de 1/ganho(f) (``api.margem_da_correcao_sonda``). :meth:`Cadeia.previa` lê
a janela pedida com a margem da cadeia de cada lado, aplica a cadeia e descarta as bordas; :meth:`Cadeia.em_blocos`
faz o mesmo bloco a bloco, para a captura inteira (sobreposição e descarte, *overlap-save*). Longe das bordas da
captura, o resultado é o do vetor inteiro: a 1e-9 relativo com os filtros; com a correção de sonda, cuja resposta ao
impulso decai devagar, abaixo de 1e-6 do valor RMS (4e-7 medidos com a sonda de teste; ``tests/test_gui_cadeia.py``). Perto das bordas da captura, a correção
do vetor inteiro mistura o começo com o fim (a FFT é circular), e nenhum dos dois resultados vale ali.

Sem Qt; o motor só pela ``supraharmonicos.api``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import ClassVar

import numpy as np
import supraharmonicos.api as api

TOLERANCIA_DO_FILTRO = 1e-12
"""A cauda da resposta ao impulso de um filtro que fica fora da margem (a soma de |h|, relativa à soma inteira)."""
MARGEM_MAXIMA = 1 << 21
"""O teto da margem de uma etapa, em amostras (~10 s a 200 kS/s): um corte baixo demais não pede a captura inteira."""
BLOCO_PADRAO = 1 << 22
"""As amostras de cada bloco de :meth:`Cadeia.em_blocos` (32 MB em ``float64``), fora as margens."""

ORDEM_PADRAO = api.ORDEM_FILTRO_PADRAO


class EtapaInvalida(ValueError):
    """Um parâmetro de etapa fora do que ela aceita; a mensagem diz qual e por quê. A receita do traço
    (``receita.py``) a repassa como ``ReceitaInvalida``."""


@dataclass(frozen=True)
class ContextoDaCadeia:
    """O que a cadeia precisa saber do canal: a taxa; o perfil de sonda que a captura registra para ele (a correção
    automática); a média do canal inteiro, na unidade física e antes da cadeia (o "remover o DC"); e como carregar
    um perfil escolhido."""

    taxa_hz: float
    perfil_do_canal: object | None = None          # um api.PerfilSonda
    media: float | None = None
    carregar_perfil: Callable[[str], object] = field(default=api.carregar_perfil, repr=False, compare=False)


def _finito(valor) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor)


@dataclass(frozen=True)
class Etapa:
    """Uma etapa da cadeia. ``ligada`` falsa: a etapa fica na cadeia, mas não é aplicada."""

    tipo: ClassVar[str] = ""
    classe: ClassVar[str] = "afim"        # "afim" ou "memoria" (docs/gui-plan.md, 7.2)
    ligada: bool = field(default=True, kw_only=True)

    def __post_init__(self) -> None:
        if not isinstance(self.ligada, bool):
            raise EtapaInvalida(f"ligada tem de ser verdadeiro ou falso, não {self.ligada!r}")

    def validar(self, contexto: ContextoDaCadeia) -> None:
        """O que depende do canal (a Nyquist, o perfil); levanta ``api.ErroSHAN`` com o motivo."""

    def margem(self, contexto: ContextoDaCadeia) -> int:
        """Até quantas amostras de distância a etapa mistura o sinal (0 numa etapa afim)."""
        return 0

    def ganho_dc(self, contexto: ContextoDaCadeia) -> float:
        """Quanto a média do sinal é multiplicada pela etapa."""
        return 1.0

    def aplicar(self, sinal: np.ndarray, contexto: ContextoDaCadeia, media: float | None) -> np.ndarray:
        """A etapa sobre ``sinal`` (``float64``); ``media`` é a média do canal inteiro na entrada desta etapa (None
        se não se sabe)."""
        raise NotImplementedError

    def aviso(self, contexto: ContextoDaCadeia) -> str | None:
        """Um aviso sobre a etapa neste canal (ela não faz nada, por exemplo), ou None."""
        return None

    def resumo(self) -> str:
        """O texto curto do chip do traço."""
        raise NotImplementedError

    def para_dict(self) -> dict:
        return {"tipo": self.tipo, "ligada": self.ligada}


@dataclass(frozen=True)
class Filtro(Etapa):
    """O Butterworth de fase zero (``api.filtrar``): ``filtro`` é ``passa_baixas`` ou ``passa_altas`` (um corte) ou
    ``passa_faixa`` ou ``rejeita_faixa`` (o inferior e o superior), em Hz."""

    tipo: ClassVar[str] = "filtro"
    classe: ClassVar[str] = "memoria"
    filtro: str = "passa_altas"
    cortes: tuple[float, ...] = (2000.0,)
    ordem: int = ORDEM_PADRAO

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.filtro not in api.TIPOS_DE_FILTRO:
            raise EtapaInvalida(f"filtro desconhecido: {self.filtro!r} (use {', '.join(api.TIPOS_DE_FILTRO)})")
        if isinstance(self.cortes, (int, float)) and not isinstance(self.cortes, bool):
            object.__setattr__(self, "cortes", (self.cortes,))
        if not isinstance(self.cortes, (tuple, list)) or not all(_finito(c) and c > 0 for c in self.cortes):
            raise EtapaInvalida(f"cortes inválidos: {self.cortes!r} (frequências positivas, em Hz)")
        object.__setattr__(self, "cortes", tuple(float(c) for c in self.cortes))
        esperados = 2 if self.filtro in ("passa_faixa", "rejeita_faixa") else 1
        if len(self.cortes) != esperados:
            raise EtapaInvalida(f"o filtro {self.nome} tem {esperados} corte(s), não {len(self.cortes)}")
        if esperados == 2 and not self.cortes[0] < self.cortes[1]:
            raise EtapaInvalida(f"o corte inferior ({self.cortes[0]:g} Hz) precisa ser menor que o superior "
                                f"({self.cortes[1]:g} Hz)")
        if not (isinstance(self.ordem, int) and not isinstance(self.ordem, bool)
                and 1 <= self.ordem <= api.ORDEM_MAXIMA_DO_FILTRO):
            raise EtapaInvalida(f"a ordem do filtro precisa ser um inteiro de 1 a {api.ORDEM_MAXIMA_DO_FILTRO} "
                                f"(recebido {self.ordem!r})")

    @property
    def nome(self) -> str:
        return self.filtro.replace("_", "-")

    def validar(self, contexto: ContextoDaCadeia) -> None:
        api.validar_filtro(self.filtro, self.cortes, self.ordem, contexto.taxa_hz)

    def margem(self, contexto: ContextoDaCadeia) -> int:
        self.validar(contexto)
        return _margem_do_filtro(self.filtro, self.cortes, self.ordem, float(contexto.taxa_hz))

    def ganho_dc(self, contexto: ContextoDaCadeia) -> float:
        return 0.0 if self.filtro in ("passa_altas", "passa_faixa") else 1.0

    def aplicar(self, sinal, contexto, media):
        return api.filtrar(sinal, contexto.taxa_hz, self.filtro, self.cortes, self.ordem)

    def resumo(self) -> str:
        sigla = {"passa_baixas": "PB", "passa_altas": "PA", "passa_faixa": "PF", "rejeita_faixa": "RF"}[self.filtro]
        return f"{sigla} {'–'.join(_hz(c) for c in self.cortes)}"

    def para_dict(self) -> dict:
        return {**super().para_dict(), "filtro": self.filtro, "cortes": list(self.cortes), "ordem": self.ordem}


def _hz(valor: float) -> str:
    return f"{valor / 1000:g} kHz" if valor >= 1000 else f"{valor:g} Hz"


@lru_cache(maxsize=64)
def _margem_do_filtro(filtro: str, cortes: tuple[float, ...], ordem: int, taxa_hz: float) -> int:
    """A margem de um filtro de fase zero: a sua resposta ao impulso (o ``sosfiltfilt`` de um impulso), até a soma
    da cauda ficar abaixo de :data:`TOLERANCIA_DO_FILTRO` da soma inteira. O comprimento da conta sai do polo mais
    perto do círculo unitário (o que demora mais para decair)."""
    from scipy.signal import sosfiltfilt  # sob demanda: só quem filtra paga o SciPy

    sos = api.projetar_filtro(filtro, cortes, ordem, taxa_hz)
    raio = max(float(np.max(np.abs(np.roots(secao[3:])))) for secao in sos)
    estimada = math.ceil(math.log(TOLERANCIA_DO_FILTRO) / math.log(raio)) if raio < 1 else MARGEM_MAXIMA
    meio = min(MARGEM_MAXIMA, 4 * estimada + 64)
    impulso = np.zeros(2 * meio + 1)
    impulso[meio] = 1.0
    h = np.abs(sosfiltfilt(sos, impulso))
    # A soma de |h| a partir de cada distância do centro (os dois lados juntos).
    por_distancia = h[meio:].copy()
    por_distancia[1:] += h[meio - 1::-1]
    cauda = np.cumsum(por_distancia[::-1])[::-1]
    dentro = np.nonzero(cauda <= TOLERANCIA_DO_FILTRO * cauda[0])[0]
    return int(min(dentro[0] if len(dentro) else meio, MARGEM_MAXIMA))


@dataclass(frozen=True)
class CorrecaoSonda(Etapa):
    """A correção pelo perfil de sonda (``api.aplicar_correcao_sonda``). ``perfil`` None: automática, o perfil que a
    captura registra para o canal (sem um, a etapa não muda nada e avisa); senão, o caminho do ``.json`` escolhido."""

    tipo: ClassVar[str] = "correcao_sonda"
    classe: ClassVar[str] = "memoria"
    perfil: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.perfil is not None and (not isinstance(self.perfil, str) or not self.perfil.strip()):
            raise EtapaInvalida(f"perfil de sonda inválido: {self.perfil!r} (o caminho do .json, ou automático)")

    def perfil_usado(self, contexto: ContextoDaCadeia):
        """O ``api.PerfilSonda`` que a etapa aplica, ou None (automática, num canal sem sonda registrada)."""
        if self.perfil is None:
            return contexto.perfil_do_canal
        return contexto.carregar_perfil(self.perfil)

    def validar(self, contexto: ContextoDaCadeia) -> None:
        self.perfil_usado(contexto)

    def margem(self, contexto: ContextoDaCadeia) -> int:
        perfil = self.perfil_usado(contexto)
        return 0 if perfil is None else min(api.margem_da_correcao_sonda(perfil, contexto.taxa_hz), MARGEM_MAXIMA)

    def ganho_dc(self, contexto: ContextoDaCadeia) -> float:
        perfil = self.perfil_usado(contexto)
        if perfil is None:
            return 1.0
        return 1.0 / float(perfil.ganho_em(np.zeros(1))[0])

    def aviso(self, contexto: ContextoDaCadeia) -> str | None:
        if self.perfil_usado(contexto) is None:
            return ("a correção de sonda automática não tem o que aplicar: a captura não registra uma sonda para este "
                    "canal (escolha um perfil)")
        return None

    def aplicar(self, sinal, contexto, media):
        perfil = self.perfil_usado(contexto)
        return sinal if perfil is None else api.aplicar_correcao_sonda(sinal, contexto.taxa_hz, perfil)

    def resumo(self) -> str:
        return "sonda" if self.perfil is None else f"sonda {Path(self.perfil).stem}"

    def para_dict(self) -> dict:
        return {**super().para_dict(), "perfil": self.perfil}


@dataclass(frozen=True)
class RemoverDC(Etapa):
    """Tira a média do canal inteiro na entrada da etapa (sem ela, a do trecho)."""

    tipo: ClassVar[str] = "remover_dc"
    classe: ClassVar[str] = "afim"

    def ganho_dc(self, contexto: ContextoDaCadeia) -> float:
        return 0.0

    def aplicar(self, sinal, contexto, media):
        return sinal - (float(np.mean(sinal)) if media is None else media)

    def resumo(self) -> str:
        return "−DC"


TIPOS_DE_ETAPA: dict[str, type[Etapa]] = {c.tipo: c for c in (Filtro, CorrecaoSonda, RemoverDC)}


def etapa_de_dict(dados) -> Etapa:
    """A etapa de um dicionário do projeto; levanta :class:`EtapaInvalida` com o motivo."""
    if not isinstance(dados, dict):
        raise EtapaInvalida(f"uma etapa é um objeto, não {type(dados).__name__}")
    tipo = dados.get("tipo")
    classe = TIPOS_DE_ETAPA.get(tipo)
    if classe is None:
        raise EtapaInvalida(f"etapa desconhecida: {tipo!r} (este aplicativo conhece {', '.join(TIPOS_DE_ETAPA)})")
    campos = {f for f in classe.__dataclass_fields__ if f != "tipo" and f != "classe"}
    desconhecidos = set(dados) - campos - {"tipo"}
    if desconhecidos:
        raise EtapaInvalida(f"campos desconhecidos na etapa {tipo}: {', '.join(sorted(desconhecidos))}")
    valores = {k: dados[k] for k in campos if k in dados}
    if "cortes" in valores and isinstance(valores["cortes"], list):
        valores["cortes"] = tuple(valores["cortes"])
    try:
        return classe(**valores)
    except TypeError as e:
        raise EtapaInvalida(f"etapa {tipo} inválida: {e}") from None


@dataclass(frozen=True)
class SinalTransformado:
    """O trecho depois da cadeia e os avisos do motor no caminho."""

    valores: np.ndarray
    avisos: tuple[api.Aviso, ...] = ()


@dataclass(frozen=True)
class Cadeia:
    """As etapas de um traço, na ordem em que são aplicadas."""

    etapas: tuple[Etapa, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.etapas, tuple):
            object.__setattr__(self, "etapas", tuple(self.etapas))
        for etapa in self.etapas:
            if not isinstance(etapa, Etapa):
                raise EtapaInvalida(f"a cadeia só aceita etapas, não {etapa!r}")

    @property
    def ligadas(self) -> tuple[Etapa, ...]:
        return tuple(e for e in self.etapas if e.ligada)

    @property
    def vazia(self) -> bool:
        """Nenhuma etapa ligada: o traço é o canal como ele é."""
        return not self.ligadas

    @property
    def tem_memoria(self) -> bool:
        return any(e.classe == "memoria" for e in self.ligadas)

    def validar(self, contexto: ContextoDaCadeia) -> None:
        for etapa in self.ligadas:
            etapa.validar(contexto)

    def margem(self, contexto: ContextoDaCadeia) -> int:
        """A margem da cadeia: a soma das margens das etapas ligadas (cada uma precisa da sua entrada já acomodada)."""
        return sum(e.margem(contexto) for e in self.ligadas)

    def aplicar(self, sinal, contexto: ContextoDaCadeia) -> SinalTransformado:
        """As etapas ligadas sobre o trecho inteiro, em ``float64``. Levanta ``api.ErroSHAN`` se uma etapa não serve
        para o canal (um corte acima da Nyquist, um perfil que falta)."""
        x = np.asarray(sinal, dtype=np.float64)
        media = contexto.media
        with api.capturar_avisos() as avisos:
            for etapa in self.ligadas:
                etapa.validar(contexto)
                x = etapa.aplicar(x, contexto, media)
                media = None if media is None else media * etapa.ganho_dc(contexto)
                texto = etapa.aviso(contexto)
                if texto:
                    avisos.append(api.Aviso("aviso", texto))
        return SinalTransformado(x, tuple(avisos))

    def previa(self, ler: Callable[[int, int], np.ndarray], n_total: int, inicio: int, fim: int,
               contexto: ContextoDaCadeia) -> SinalTransformado:
        """As amostras ``[inicio, fim)`` depois da cadeia, lendo só a janela com a margem de cada lado:
        ``ler(a, b)`` dá as amostras ``[a, b)`` do canal, na unidade física."""
        if not 0 <= inicio <= fim <= n_total:
            raise ValueError(f"janela fora do sinal: [{inicio}, {fim}) em {n_total} amostras")
        m = self.margem(contexto)
        a, b = max(0, inicio - m), min(n_total, fim + m)
        r = self.aplicar(ler(a, b), contexto)
        return SinalTransformado(r.valores[inicio - a:fim - a], r.avisos)

    def em_blocos(self, ler: Callable[[int, int], np.ndarray], n_total: int, contexto: ContextoDaCadeia, *,
                  bloco: int = BLOCO_PADRAO, progresso: Callable[[float], None] | None = None,
                  cancelado: Callable[[], bool] | None = None) -> Iterator[tuple[int, np.ndarray]]:
        """O sinal inteiro depois da cadeia, bloco a bloco: ``(início, valores)`` de ``bloco`` amostras (o último,
        o que sobrar), cada um lido com a margem da cadeia e com as bordas descartadas. ``cancelado()`` é conferido
        antes de cada bloco (cancelado, levanta ``api.Cancelado``)."""
        if bloco < 1:
            raise ValueError(f"o bloco precisa de pelo menos 1 amostra (recebido {bloco})")
        self.validar(contexto)
        for inicio in range(0, n_total, bloco):
            if cancelado is not None and cancelado():
                raise api.Cancelado()
            fim = min(n_total, inicio + bloco)
            yield inicio, self.previa(ler, n_total, inicio, fim, contexto).valores
            if progresso is not None:
                progresso(fim / n_total)

    def resumo(self) -> str:
        """O resumo do chip: as etapas ligadas, na ordem (``sonda · PA 2 kHz · −DC``)."""
        return " · ".join(e.resumo() for e in self.ligadas)

    def para_lista(self) -> list[dict]:
        return [e.para_dict() for e in self.etapas]

    @classmethod
    def de_lista(cls, dados: Sequence) -> Cadeia:
        if not isinstance(dados, (list, tuple)):
            raise EtapaInvalida(f"as etapas são uma lista, não {type(dados).__name__}")
        return cls(tuple(etapa_de_dict(d) for d in dados))
