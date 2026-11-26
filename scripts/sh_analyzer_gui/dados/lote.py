"""A análise em lote (sem Qt): os mesmos índices em cada captura de uma pasta (ou das sessões de vários dias), uma
linha por captura e canal, para a tabela, a tendência no tempo e o CSV.

**As contas são as das vistas**, no canal sem transformações (o valor físico com o ganho da captura): os índices de
qualidade da IEC 61000-4-30 (``qualidade.indices``, sem as janelas marcadas), as bandas IEC 61000-4-7
(``espectros.bandas_do_trecho``) e os eventos (``qualidade.eventos``, os de tensão só nos canais de tensão). Com
``limite_s``, só os primeiros segundos de cada captura (o lote rápido de uma semana de capturas de 1 h).

**O instante** de cada linha é o início gravado no cabeçalho (o relógio da placa); sem ele, a data do arquivo. A
integridade é a do CRC das amostras (``api.conferir_integridade``), quando a captura o tem.
"""

from __future__ import annotations

import csv
import datetime
import io
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from pathlib import Path

import numpy as np
import supraharmonicos.api as api

from . import espectros as esp
from . import qualidade as q
from .cadeia import Cadeia, ContextoDaCadeia

EXTENSOES = (".bin", ".h5", ".hdf5")
GRANDEZA_TENSAO = 0                    # a de constantes.GRANDEZA_TENSAO (o canal sem informação também é tensão)
SEM_VALOR = float("nan")


@dataclass(frozen=True)
class LinhaDoLote:
    arquivo: str
    caminho: str
    inicio: datetime.datetime | None
    duracao_s: float
    canal: int
    grandeza: str
    unidade: str
    integridade: str
    janelas: int = 0
    marcadas: int = 0
    frequencia_hz: float = SEM_VALOR
    rms: float = SEM_VALOR
    thd_p95: float = SEM_VALOR                  # fração (0,04 = 4 %)
    supra_2_9k_p95: float = SEM_VALOR
    supra_9_150k_p95: float = SEM_VALOR
    banda_maior_hz: float = SEM_VALOR
    banda_maior_p95: float = SEM_VALOR
    eventos: int = 0
    erro: str = ""


COLUNAS_NUMERICAS = {
    "frequencia_hz": ("Frequência média", "Hz"), "rms": ("RMS médio", None), "thd_p95": ("THD (P95)", "%"),
    "supra_2_9k_p95": ("RMS de 2 a 9 kHz (P95)", None), "supra_9_150k_p95": ("RMS de 9 a 150 kHz (P95)", None),
    "banda_maior_p95": ("A maior banda IEC (P95)", None), "eventos": ("Eventos", ""), "marcadas": ("Janelas marcadas", "")}
"""As colunas que viram tendência: o nome e a unidade (None: a do canal)."""


def capturas_da_pasta(pasta: Path, *, recursivo: bool = True) -> list[Path]:
    """As capturas da pasta (``.bin`` e ``.h5``), pela ordem do nome; um ``.h5`` com o ``.bin`` do mesmo nome ao lado
    fica de fora (é a exportação dele)."""
    pasta = Path(pasta)
    achadas = sorted(c for c in (pasta.rglob("*") if recursivo else pasta.glob("*"))
                     if c.is_file() and c.suffix.lower() in EXTENSOES and not c.name.endswith(".parcial"))
    binarios = {c.with_suffix("") for c in achadas if c.suffix.lower() == ".bin"}
    return [c for c in achadas if c.suffix.lower() == ".bin" or c.with_suffix("") not in binarios]


def _inicio(captura: api.Captura) -> datetime.datetime | None:
    cab = captura.cabecalho
    texto = getattr(cab, "timestamp_iso_utc", None) if cab is not None else None
    if texto:
        try:
            return datetime.datetime.fromisoformat(texto)
        except ValueError:
            pass
    try:
        return datetime.datetime.fromtimestamp(captura.caminho.stat().st_mtime, datetime.timezone.utc)
    except OSError:
        return None


def _integridade(captura: api.Captura, cancelado) -> str:
    try:
        r = api.conferir_integridade(captura, cancelado=cancelado)
    except (api.ErroSHAN, OSError) as e:
        return f"erro: {e}"
    return {True: "confere", False: "não confere", None: "sem CRC"}[r]


def calcular_captura(caminho: Path, *, canais: Sequence[int] | None = None, limite_s: float | None = None,
                     sondas_dir: Path | None = None, numero: Callable[[float, int], str] = q._numero,
                     progresso: Callable[[float], None] | None = None,
                     cancelado: Callable[[], bool] | None = None) -> list[LinhaDoLote]:
    """As linhas de uma captura (uma por canal; ``canais``: só estes, quando ela os tem). Uma captura que não abre
    vira uma linha com o erro."""
    caminho = Path(caminho)
    try:
        captura = api.abrir_captura(caminho, sondas_dir=sondas_dir)
    except (api.ErroSHAN, OSError) as e:
        return [LinhaDoLote(caminho.name, str(caminho), None, SEM_VALOR, -1, "", "", "", erro=str(e))]
    inicio = _inicio(captura)
    integridade = _integridade(captura, cancelado)
    escolhidos = [c for c in captura.canais if canais is None or c.numero in canais]
    linhas = []
    for k, canal in enumerate(escolhidos):
        if cancelado is not None and cancelado():
            break
        fim = len(canal.amostras)
        if limite_s is not None:
            fim = min(fim, int(round(limite_s * canal.taxa_hz)))
        trecho = esp.TrechoDoTraco(captura, canal.numero, Cadeia(), ContextoDaCadeia(canal.taxa_hz), 0, fim)
        base = dict(arquivo=caminho.name, caminho=str(caminho), inicio=inicio, duracao_s=fim / canal.taxa_hz,
                    canal=canal.numero, grandeza=canal.nome_grandeza, unidade=canal.unidade, integridade=integridade)
        parte = (lambda a, b, k=k: (lambda f: progresso((k + a + (b - a) * f) / len(escolhidos)))) \
            if progresso is not None else (lambda a, b: None)
        valores, erros = {}, []
        indices = None
        try:
            indices = q.indices(trecho, progresso=parte(0.0, 0.5), cancelado=cancelado)
            marcadas = indices.marcadas()
            est = (indices.estatisticas_de(~marcadas) if marcadas.any() and not marcadas.all()
                   else indices.estatisticas)
            valores.update(janelas=indices.n_janelas, marcadas=int(marcadas.sum()),
                           frequencia_hz=est["frequencia"].media, rms=est["rms"].media, thd_p95=est["thd"].p95,
                           supra_2_9k_p95=est["supra_2_9k"].p95, supra_9_150k_p95=est["supra_9_150k"].p95)
        except api.Cancelado:
            break
        except api.ErroSHAN as e:
            erros.append(f"índices: {e}")
        try:
            bandas = esp.bandas_do_trecho(trecho, esp.OpcoesDasBandas().parametros, progresso=parte(0.5, 0.85),
                                          cancelado=cancelado).bandas
            p95 = bandas.estatisticas()["p95"]
            if len(p95):
                i = int(np.argmax(p95))
                valores.update(banda_maior_hz=float(bandas.centros_hz[i]), banda_maior_p95=float(p95[i]))
        except api.Cancelado:
            break
        except api.ErroSHAN as e:
            erros.append(f"bandas: {e}")
        try:
            eventos = q.eventos(trecho, q.CriteriosDosEventos(tensao=canal.grandeza == GRANDEZA_TENSAO), indices_prontos=indices,
                                progresso=parte(0.85, 1.0), cancelado=cancelado, numero=numero)
            valores["eventos"] = sum(1 for e in eventos if not math.isnan(e.inicio_s))
        except api.Cancelado:
            break
        except api.ErroSHAN as e:
            erros.append(f"eventos: {e}")
        linhas.append(LinhaDoLote(**base, **valores, erro="; ".join(erros)))
    return linhas


def calcular(caminhos: Sequence[Path], **opcoes) -> list[LinhaDoLote]:
    """As linhas de todas as capturas, em ordem; ``progresso`` vai de 0 a 1 no lote inteiro."""
    progresso = opcoes.pop("progresso", None)
    cancelado = opcoes.get("cancelado")
    linhas = []
    for k, caminho in enumerate(caminhos):
        if cancelado is not None and cancelado():
            break
        parcial = (lambda f, k=k: progresso((k + f) / len(caminhos))) if progresso is not None else None
        linhas += calcular_captura(caminho, progresso=parcial, **opcoes)
    return linhas


def em_ordem_de_tempo(linhas: Sequence[LinhaDoLote]) -> list[LinhaDoLote]:
    minimo = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    return sorted(linhas, key=lambda linha: (linha.inicio or minimo, linha.canal))


def em_csv(linhas: Sequence[LinhaDoLote], *, separador: str = ";", decimal: str = ",") -> str:
    """O lote em CSV (os números com o decimal escolhido; o THD em fração, como na linha)."""
    nomes = [f.name for f in fields(LinhaDoLote)]
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=separador, lineterminator="\n")
    escritor.writerow(nomes)
    for linha in linhas:
        celulas = []
        for nome in nomes:
            valor = getattr(linha, nome)
            if isinstance(valor, datetime.datetime):
                celulas.append(valor.isoformat())
            elif isinstance(valor, float):
                celulas.append("" if math.isnan(valor) else repr(valor).replace(".", decimal))
            else:
                celulas.append(str(valor))
        escritor.writerow(celulas)
    return saida.getvalue()
