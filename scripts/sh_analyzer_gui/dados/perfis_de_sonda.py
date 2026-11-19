"""Os perfis de sonda para ver (ES-07, docs/gui-plan.md, 9.5: a vista "Perfil de sonda"), sem Qt: o Bode de um perfil
(a magnitude e a fase, com as barras de erro dos pontos de calibração e a faixa válida) e a curva que a correção usa.

**A curva é a do motor:** a magnitude entre os pontos vem do ``ganho_em`` do ``PerfilSonda`` (o PCHIP em log f e dB,
constante fora dos pontos), o mesmo que ``api.aplicar_correcao_sonda`` divide; nada é interpolado de novo aqui. A
correção do motor usa só o ganho (``sonda.aplicar_correcao_sonda``): a fase, quando o perfil a traz (o do
``medir_fase.py``), é mostrada nos pontos, com a reta entre eles em log f (a do ``perfil_complexo``), e não entra no
sinal corrigido.

**As barras de erro** são as do arquivo: ``desvio_pct`` (o desvio-padrão do ganho entre as medidas de cada ponto, em
% do ganho) vira ``20·log10(1 ± desvio)`` dB, e ``sigma_fase_rad`` vira graus. Um ponto sem elas fica sem barra.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import supraharmonicos.api as api

PONTOS_DA_CURVA = 400
FOLGA_NAS_PONTAS = 2.0           # a curva vai do menor ponto ÷ isto ao maior × isto (fora, o ganho fica constante)


class PerfilIlegivel(ValueError):
    """O arquivo não é um perfil que o motor abre (o motivo é o do ``api.carregar_perfil``)."""


@dataclass(frozen=True)
class PerfilParaVer:
    caminho: Path
    id: str
    tipo: str                                   # "resposta_frequencia" ou "ganho_fixo"
    freq_hz: np.ndarray                         # os pontos de calibração, em ordem crescente
    ganho: np.ndarray                           # linear (1 = a sonda não atenua)
    desvio_pct: np.ndarray                      # NaN onde o ponto não diz
    fase_rad: np.ndarray | None                 # None: o perfil não traz a fase (em todo ponto)
    sigma_fase_rad: np.ndarray                  # NaN onde o ponto não diz
    faixa_valida: tuple[float, float] | None
    data_calibracao: object                     # datetime.date ou None
    calibrado_com: str
    perfil: object                              # o api.PerfilSonda (a curva da correção)

    @property
    def ganho_db(self) -> np.ndarray:
        return 20.0 * np.log10(self.ganho)

    def barras_db(self) -> tuple[np.ndarray, np.ndarray]:
        """O quanto a barra de cada ponto desce e sobe, em dB (positivos; NaN sem o desvio)."""
        d = self.desvio_pct / 100.0
        with np.errstate(invalid="ignore", divide="ignore"):
            abaixo = -20.0 * np.log10(np.clip(1.0 - d, 1e-12, None))
            acima = 20.0 * np.log10(1.0 + d)
        return abaixo, acima

    def fase_graus(self) -> np.ndarray | None:
        return None if self.fase_rad is None else np.degrees(self.fase_rad)

    def curva(self, pontos: int = PONTOS_DA_CURVA) -> tuple[np.ndarray, np.ndarray]:
        """``(f, ganho em dB)``: o ganho que a correção divide, numa grade log em volta dos pontos."""
        f = np.geomspace(self.freq_hz[0] / FOLGA_NAS_PONTAS, self.freq_hz[-1] * FOLGA_NAS_PONTAS, pontos)
        self.perfil.silenciar_aviso_fora_da_faixa()       # desenhar não é analisar: o aviso é para as análises
        return f, 20.0 * np.log10(self.perfil.ganho_em(f))

    def curva_da_fase(self, pontos: int = PONTOS_DA_CURVA) -> tuple[np.ndarray, np.ndarray] | None:
        """``(f, fase em graus)``: a reta em log f entre os pontos (fora, o valor da ponta), só para ver."""
        if self.fase_rad is None or len(self.freq_hz) < 2:
            return None
        f = np.geomspace(self.freq_hz[0] / FOLGA_NAS_PONTAS, self.freq_hz[-1] * FOLGA_NAS_PONTAS, pontos)
        return f, np.degrees(np.interp(np.log(f), np.log(self.freq_hz), self.fase_rad))

    def resumo(self) -> str:
        """Uma linha: o tipo, os pontos, a faixa válida e a data."""
        partes = [f"{len(self.freq_hz)} pontos" if self.tipo == "resposta_frequencia" else "ganho fixo"]
        if self.faixa_valida is not None:
            partes.append(f"válido de {_hz(self.faixa_valida[0])} a {_hz(self.faixa_valida[1])}")
        if self.data_calibracao is not None:
            partes.append(f"calibrado em {self.data_calibracao.isoformat()}")
        if self.fase_rad is not None:
            partes.append("com a fase")
        return " · ".join(partes)


def _hz(f: float) -> str:
    for fator, prefixo in ((1e6, "M"), (1e3, "k")):
        if f >= fator:
            return f"{f / fator:.4g} {prefixo}Hz"
    return f"{f:.4g} Hz"


def ler(caminho: Path) -> PerfilParaVer:
    """Abre o perfil pelo motor (o que não abre lá não abre aqui) e lê do arquivo o que o ``PerfilSonda`` não guarda:
    as barras de erro, a fase e o "calibrado com". Levanta :class:`PerfilIlegivel`."""
    caminho = Path(caminho)
    try:
        perfil = api.carregar_perfil(caminho)
    except api.ErroSHAN as e:
        raise PerfilIlegivel(str(e)) from None
    freq, ganho = perfil.pontos
    n = len(freq)
    desvio, fase, sigma = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    calibrado_com = ""
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        dados = {}
    pontos = dados.get("pontos") if isinstance(dados, dict) else None
    if isinstance(pontos, list) and perfil.tipo == "resposta_frequencia":
        por_f = {}
        for p in pontos:
            try:
                por_f[float(p["freq_hz"])] = p
            except (KeyError, TypeError, ValueError):
                continue
        for i, f in enumerate(freq):
            p = por_f.get(float(f), {})
            desvio[i] = _numero(p.get("desvio_pct"))
            fase[i] = _numero(p.get("fase_rad"))
            sigma[i] = _numero(p.get("sigma_fase_rad"))
    if isinstance(dados, dict):
        valor = dados.get("calibrado_com", "")
        calibrado_com = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False)
    tem_fase = n >= 1 and bool(np.all(np.isfinite(fase)))
    return PerfilParaVer(caminho=caminho, id=perfil.id, tipo=perfil.tipo, freq_hz=freq, ganho=ganho,
                         desvio_pct=desvio, fase_rad=np.unwrap(fase) if tem_fase else None, sigma_fase_rad=sigma,
                         faixa_valida=perfil.faixa_valida, data_calibracao=perfil.data_calibracao,
                         calibrado_com=calibrado_com, perfil=perfil)


def _numero(valor) -> float:
    try:
        x = float(valor)
    except (TypeError, ValueError):
        return math.nan
    return x if math.isfinite(x) else math.nan


def perfis_da_pasta(pasta: Path) -> list[Path]:
    """Os ``.json`` da pasta das sondas, em ordem de nome (sem a pasta, nenhum)."""
    try:
        return sorted(p for p in Path(pasta).glob("*.json") if p.is_file())
    except OSError:
        return []
