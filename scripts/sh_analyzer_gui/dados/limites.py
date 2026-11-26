"""As curvas de limite das bandas (sem Qt): o nível que uma norma admite em cada frequência, para comparar com as
bandas IEC 61000-4-7 da vista "Bandas IEC" (a margem de cada banda e as que passam).

**O programa não traz os valores das normas.** As tabelas dos níveis de compatibilidade de 9 a 150 kHz
(IEC 61000-2-2, tabela 3; IEC 61000-2-12) e os limites de emissão (CISPR, EN 50065-1) são de publicações pagas:
quem usa digita os pontos da sua cópia e diz de onde vêm (``fonte``). Uma curva sem fonte é aceita, mas a vista
avisa.

**A curva** é uma lista de pontos (frequência em Hz, nível em dB acima de 1 µV ou 1 µA), em ordem crescente de
frequência, com a reta entre eles em log f (como as normas desenham os limites que caem com a frequência). Dois
pontos na mesma frequência fazem um degrau: ali vale o menor dos dois. Fora do primeiro e do último ponto não há
limite (NaN): a banda fica sem margem.

**A margem** é o limite menos o nível da banda, em dB: positiva, a banda está abaixo do limite; negativa, passou.

**Onde ficam:** um ``.json`` por curva na pasta ``limites`` (a ``configuracao.pasta_dos_limites``: ao lado da
configuração quando ``SH_ANALYZER_CONFIG`` está definida; senão, na pasta de dados do usuário). A vista guarda a curva escolhida inteira nas opções dela, para
o projeto abrir igual em outra máquina.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

GRANDEZAS = ("tensao", "corrente")
UNIDADE_DA_GRANDEZA = {"tensao": "dBµV", "corrente": "dBµA"}
UNIDADE_DO_TRACO = {"tensao": "V", "corrente": "A"}
REFERENCIA = 1e-6                     # 1 µV ou 1 µA
MAXIMO_DE_PONTOS = 500
EXTENSAO = ".json"


FAIXAS_CENELEC = (("A", 3e3, 95e3), ("B", 95e3, 125e3), ("C", 125e3, 140e3), ("D", 140e3, 148.5e3))
"""As faixas da comunicação pela rede elétrica da EN 50065-1 (só as fronteiras, para marcar no espectro): A, das
distribuidoras; B, C e D, dos consumidores (a C com o protocolo de acesso)."""


class LimiteInvalido(ValueError):
    """A curva não serve (o motivo vai na mensagem, para a tela)."""


@dataclass(frozen=True)
class CurvaLimite:
    nome: str
    pontos: tuple[tuple[float, float], ...]    # (frequência em Hz, nível em dBµV ou dBµA)
    grandeza: str = "tensao"
    fonte: str = ""                            # a norma, a edição e a tabela de onde vêm os valores

    def __post_init__(self) -> None:
        if not isinstance(self.nome, str) or not self.nome.strip():
            raise LimiteInvalido("a curva precisa de um nome")
        if self.grandeza not in GRANDEZAS:
            raise LimiteInvalido(f"grandeza inválida: {self.grandeza!r} (use {', '.join(GRANDEZAS)})")
        if not isinstance(self.fonte, str):
            raise LimiteInvalido("a fonte é um texto")
        try:
            pontos = tuple((float(f), float(n)) for f, n in self.pontos)
        except (TypeError, ValueError):
            raise LimiteInvalido("os pontos são pares (frequência em Hz, nível em dB)") from None
        if len(pontos) < 2:
            raise LimiteInvalido("a curva precisa de dois pontos ou mais")
        if len(pontos) > MAXIMO_DE_PONTOS:
            raise LimiteInvalido(f"pontos demais: {len(pontos)} (até {MAXIMO_DE_PONTOS})")
        for f, n in pontos:
            if not (math.isfinite(f) and f > 0 and math.isfinite(n)):
                raise LimiteInvalido(f"ponto inválido: {f!r} Hz, {n!r} dB (a frequência positiva, o nível finito)")
        if any(b[0] < a[0] for a, b in zip(pontos, pontos[1:], strict=False)):
            raise LimiteInvalido("as frequências têm de vir em ordem crescente")
        if any(a[0] == b[0] == c[0] for a, b, c in zip(pontos, pontos[1:], pontos[2:], strict=False)):
            raise LimiteInvalido("no máximo dois pontos na mesma frequência (um degrau)")
        object.__setattr__(self, "nome", self.nome.strip())
        object.__setattr__(self, "fonte", self.fonte.strip())
        object.__setattr__(self, "pontos", pontos)

    @property
    def unidade(self) -> str:
        return UNIDADE_DA_GRANDEZA[self.grandeza]

    @property
    def faixa_hz(self) -> tuple[float, float]:
        return self.pontos[0][0], self.pontos[-1][0]

    def em(self, freq_hz) -> np.ndarray:
        """O limite (dB) em cada frequência: a reta em log f entre os pontos; no degrau, o menor; fora, NaN."""
        f = np.asarray(freq_hz, dtype=float)
        fs = np.array([p[0] for p in self.pontos])
        ns = np.array([p[1] for p in self.pontos])
        lf, lfs = np.log10(np.maximum(f, 1e-300)), np.log10(fs)
        direita = np.clip(np.searchsorted(fs, f, side="right"), 1, len(fs) - 1)
        esquerda = direita - 1
        vao = lfs[direita] - lfs[esquerda]
        with np.errstate(invalid="ignore", divide="ignore"):
            t = np.where(vao > 0, (lf - lfs[esquerda]) / np.where(vao > 0, vao, 1.0), 0.0)
        valor = ns[esquerda] + t * (ns[direita] - ns[esquerda])
        for k in range(len(fs) - 1):                       # o degrau: na frequência dele, o menor dos dois
            if fs[k] == fs[k + 1]:
                valor = np.where(f == fs[k], min(ns[k], ns[k + 1]), valor)
        valor = np.where(f == fs[-1], ns[-1] if fs[-1] != fs[-2] else min(ns[-1], ns[-2]), valor)
        return np.where((f >= fs[0]) & (f <= fs[-1]), valor, np.nan)

    def para_dict(self) -> dict:
        dados = {"nome": self.nome, "grandeza": self.grandeza, "pontos": [list(p) for p in self.pontos]}
        if self.fonte:
            dados["fonte"] = self.fonte
        return dados

    @classmethod
    def de_dict(cls, dados) -> CurvaLimite:
        if not isinstance(dados, dict):
            raise LimiteInvalido("a curva é um objeto")
        desconhecidas = set(dados) - {"nome", "grandeza", "pontos", "fonte"}
        if desconhecidas:
            raise LimiteInvalido(f"campos desconhecidos na curva: {', '.join(sorted(desconhecidas))}")
        pontos = dados.get("pontos")
        if not isinstance(pontos, list) or not all(isinstance(p, list) and len(p) == 2 for p in pontos):
            raise LimiteInvalido("os pontos são uma lista de pares [Hz, dB]")
        return cls(dados.get("nome", ""), tuple(tuple(p) for p in pontos), dados.get("grandeza", "tensao"),
                   dados.get("fonte", ""))


def em_db(niveis, referencia: float = REFERENCIA) -> np.ndarray:
    """O nível RMS (V ou A) em dB acima de 1 µV ou 1 µA (zero ou negativo: −inf)."""
    with np.errstate(divide="ignore"):
        return 20.0 * np.log10(np.asarray(niveis, dtype=float) / referencia)


def margens(curva: CurvaLimite, centros_hz, niveis) -> np.ndarray:
    """O limite menos o nível de cada banda, em dB (NaN fora da curva)."""
    return curva.em(centros_hz) - em_db(niveis)


def serve_para(curva: CurvaLimite, unidade_do_traco: str) -> bool:
    """A curva compara com o traço (a de tensão com volts, a de corrente com ampères)."""
    return UNIDADE_DO_TRACO[curva.grandeza] == unidade_do_traco


# ---------------------------------------------------------------------- os pontos colados de uma planilha

_SEPARADORES = re.compile(r"[;\t ]+")


def pontos_do_texto(texto: str) -> tuple[tuple[float, float], ...]:
    """Os pares (Hz, dB) de um texto colado de uma planilha: uma linha por ponto, separados por ponto e vírgula,
    tabulação ou espaço; a vírgula decimal vale; linhas que não são números (o cabeçalho) ficam de fora. Um "k"
    depois da frequência vale mil ("9k" = 9000)."""
    pontos = []
    for linha in texto.splitlines():
        partes = [p for p in _SEPARADORES.split(linha.strip()) if p]
        if len(partes) == 1 and partes[0].count(",") == 1:          # "9000,66": a vírgula separa
            partes = partes[0].split(",")
        if len(partes) < 2:
            continue
        try:
            f = _numero(partes[0])
            n = _numero(partes[1])
        except ValueError:
            continue
        pontos.append((f, n))
    return tuple(pontos)


def _numero(texto: str) -> float:
    texto = texto.strip().replace(",", ".")
    multiplicador = 1.0
    if texto[-1:] in "kK":
        texto, multiplicador = texto[:-1], 1e3
    elif texto[-1:] == "M":
        texto, multiplicador = texto[:-1], 1e6
    return float(texto) * multiplicador


# ---------------------------------------------------------------------- a pasta das curvas

def _nome_do_arquivo(nome: str) -> str:
    limpo = re.sub(r"[^\w.-]+", "_", nome.strip(), flags=re.UNICODE).strip("._") or "limite"
    return limpo[:80] + EXTENSAO


def ler(caminho: Path) -> CurvaLimite:
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise LimiteInvalido(f"{Path(caminho).name}: {e}") from None
    return CurvaLimite.de_dict(dados)


def curvas(pasta: Path) -> list[tuple[Path, CurvaLimite]]:
    """As curvas da pasta (a ``configuracao.pasta_dos_limites``), por nome (as que não abrem ficam de fora)."""
    achadas = []
    for caminho in sorted(pasta.glob("*" + EXTENSAO)) if pasta.is_dir() else ():
        try:
            achadas.append((caminho, ler(caminho)))
        except LimiteInvalido:
            continue
    return sorted(achadas, key=lambda par: par[1].nome.casefold())


def salvar(curva: CurvaLimite, pasta: Path, *, substituir: Path | None = None) -> Path:
    """Grava a curva (atômico); ``substituir``: o arquivo dela antes (a renomeada sai de lá)."""
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / _nome_do_arquivo(curva.nome)
    if destino.exists() and destino != substituir:
        try:
            outra = ler(destino)
        except LimiteInvalido:
            outra = None
        if outra is None or outra.nome != curva.nome:
            k = 2
            while (pasta / f"{destino.stem}-{k}{EXTENSAO}").exists():
                k += 1
            destino = pasta / f"{destino.stem}-{k}{EXTENSAO}"
    parcial = destino.with_suffix(".parcial")
    parcial.write_text(json.dumps(curva.para_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(parcial, destino)
    if substituir is not None and substituir != destino and substituir.exists():
        substituir.unlink()
    return destino


def resumo(curva: CurvaLimite) -> str:
    f0, f1 = curva.faixa_hz
    return f"{curva.nome}: {len(curva.pontos)} pontos de {_hz(f0)} a {_hz(f1)} ({curva.unidade})"


def _hz(f: float) -> str:
    return f"{f / 1e3:g} kHz" if f >= 1e3 else f"{f:g} Hz"


def passam(margens_db: Sequence[float]) -> int:
    """Quantas bandas passaram do limite (margem negativa)."""
    m = np.asarray(margens_db, dtype=float)
    return int(np.count_nonzero(np.isfinite(m) & (m < 0)))
