"""Respostas complexas lidas de arquivo: um perfil de sonda COM a fase (``fase_rad`` em todo ponto, o que o
``medir_fase.py`` grava) e a impedância de um shunt (o CSV do ``medir_shunt.py``), interpoladas em log f.

Servem às calibrações que se apoiam numa cadeia já calibrada: a razão de dois canais (``medir_fase.py
--canal-referencia``, com o perfil de tensão no canal de referência e o shunt no laço) e a âncora do método de um
canal (``medir_fase.py --ancora``).
"""

from __future__ import annotations

import csv
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .erros import ErroSHAN

log = logging.getLogger(__name__)


@dataclass
class PerfilComplexo:
    """Um perfil de sonda com fase: o ganho (relativo ao ``--ganho`` dele, como em todo perfil) e a fase por ponto."""

    caminho: Path
    dados: dict
    freq_hz: np.ndarray
    ganho: np.ndarray
    fase_rad: np.ndarray
    sigma_ln: np.ndarray
    sigma_fase: np.ndarray

    @property
    def id(self) -> str:
        return str(self.dados.get("id", self.caminho.stem))

    @property
    def ganho_nominal(self) -> float | None:
        """O ``--ganho`` com que o perfil foi gerado (``calibracao_adc.ganho.sonda``), se ele o traz."""
        try:
            return float(self.dados["calibracao_adc"]["ganho"]["sonda"])
        except (KeyError, TypeError, ValueError):
            return None

    @property
    def faixa_v(self) -> float | None:
        try:
            return float(self.dados["calibracao_adc"]["faixa_v"]["sonda"])
        except (KeyError, TypeError, ValueError):
            return None

    def em(self, f) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """(ganho, fase em rad, σ de ln ganho, σ da fase) em ``f``, interpolados em log f (ln do ganho e fase lineares
        entre os pontos; fora da faixa do perfil, o valor da borda)."""
        lf = np.log(np.asarray(f, dtype=np.float64))
        base = np.log(self.freq_hz)
        return (np.exp(np.interp(lf, base, np.log(self.ganho))), np.interp(lf, base, self.fase_rad),
                np.interp(lf, base, self.sigma_ln), np.interp(lf, base, self.sigma_fase))

    def cobre(self, f) -> np.ndarray:
        f = np.asarray(f, dtype=np.float64)
        return (f >= self.freq_hz[0] / 1.0001) & (f <= self.freq_hz[-1] * 1.0001)


def ler_perfil_complexo(caminho: Path) -> PerfilComplexo:
    """Lê um perfil ``resposta_frequencia`` que traz ``fase_rad`` em todos os pontos (o do ``medir_fase.py``)."""
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ErroSHAN(f"perfil '{caminho}' não encontrado.") from None
    except json.JSONDecodeError as e:
        raise ErroSHAN(f"'{caminho}' não é um JSON válido ({e}).") from None
    pontos = dados.get("pontos") if isinstance(dados, dict) else None
    if not pontos or len(pontos) < 2:
        raise ErroSHAN(f"'{caminho}' não tem os pontos de um perfil de resposta em frequência.")
    if any("fase_rad" not in p for p in pontos):
        raise ErroSHAN(f"'{caminho}' não tem a fase (fase_rad) em todo ponto: use um perfil gravado pelo medir_fase.py.")
    pontos = sorted(pontos, key=lambda p: float(p["freq_hz"]))
    try:
        f = np.array([float(p["freq_hz"]) for p in pontos])
        g = np.array([float(p["ganho"]) for p in pontos])
        fase = np.array([float(p["fase_rad"]) for p in pontos])
        s_ln = np.array([0.01 * float(p.get("desvio_pct", 0.0)) for p in pontos])
        s_fase = np.array([float(p.get("sigma_fase_rad", 0.0)) for p in pontos])
    except (KeyError, TypeError, ValueError) as e:
        raise ErroSHAN(f"ponto inválido em '{caminho}' ({e}).") from None
    if np.any(f <= 0) or np.any(g <= 0) or not np.all(np.isfinite(np.concatenate([f, g, fase]))):
        raise ErroSHAN(f"'{caminho}': freq_hz e ganho precisam ser positivos e finitos.")
    return PerfilComplexo(Path(caminho), dados, f, g, np.unwrap(fase), s_ln, np.nan_to_num(s_fase))


@dataclass
class ImpedanciaShunt:
    """Z(f) de um shunt (Ω e rad), por pontos; ``em`` interpola |Z| e a fase em log f (fora da faixa, a borda)."""

    origem: str
    freq_hz: np.ndarray
    modulo_ohm: np.ndarray
    fase_rad: np.ndarray
    sigma_ln: np.ndarray
    sigma_fase: np.ndarray

    def em(self, f) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(Z complexo, σ de ln|Z|, σ da fase) em ``f``."""
        lf = np.log(np.asarray(f, dtype=np.float64))
        base = np.log(self.freq_hz)
        z = np.exp(np.interp(lf, base, np.log(self.modulo_ohm)) + 1j * np.interp(lf, base, self.fase_rad))
        return z, np.interp(lf, base, self.sigma_ln), np.interp(lf, base, self.sigma_fase)


def resistencia_pura(r_ohm: float) -> ImpedanciaShunt:
    """Um shunt resistivo ideal (o ``--resistencia``): Z = R em toda frequência, sem incerteza própria."""
    if not (r_ohm > 0 and math.isfinite(r_ohm)):
        raise ErroSHAN("--resistencia precisa ser positiva.")
    um = np.array([1.0, 1e9])
    return ImpedanciaShunt(f"{r_ohm:g} Ω", um, np.full(2, r_ohm), np.zeros(2), np.zeros(2), np.zeros(2))


COLUNAS_SHUNT = ["freq_hz", "z_ohm", "fase_graus", "sigma_pct", "sigma_graus", "harmonicos"]


def ler_shunt(caminho: Path) -> ImpedanciaShunt:
    """Lê o CSV do ``medir_shunt.py`` (freq_hz, z_ohm, fase_graus e, se houver, sigma_pct e sigma_graus)."""
    try:
        with open(caminho, newline="", encoding="utf-8") as arq:
            linhas = list(csv.DictReader(arq))
    except FileNotFoundError:
        raise ErroSHAN(f"'{caminho}' não encontrado.") from None
    try:
        linhas = sorted(linhas, key=lambda r: float(r["freq_hz"]))
        f = np.array([float(r["freq_hz"]) for r in linhas])
        z = np.array([float(r["z_ohm"]) for r in linhas])
        fase = np.radians([float(r["fase_graus"]) for r in linhas])
        s_ln = np.array([0.01 * float(r.get("sigma_pct") or 0.0) for r in linhas])
        s_fase = np.radians([float(r.get("sigma_graus") or 0.0) for r in linhas])
    except (KeyError, TypeError, ValueError) as e:
        raise ErroSHAN(f"'{caminho}' não é o CSV de um shunt (freq_hz, z_ohm, fase_graus): {e}.") from None
    if len(f) < 2 or np.any(f <= 0) or np.any(z <= 0):
        raise ErroSHAN(f"'{caminho}': são precisos 2 pontos ou mais, com freq_hz e z_ohm positivos.")
    return ImpedanciaShunt(Path(caminho).name, f, z, np.unwrap(fase), s_ln, s_fase)
