"""Dados de fora do SH-Analyzer (PD-03, PD-10, FG-10): ler, converter para uma captura e escrever em COMTRADE.

Os formatos lidos:

* **o osciloscópio** (``.csv``, ``.txt``, ``.m``, ``.mat``): o leitor tolerante do :mod:`osciloscopio` acha as
  variáveis numéricas, cada coluna de uma matriz vira um canal, e a taxa vem do vetor de tempo ou de um escalar
  (``Tinterval``, ``dt``, ``Fs``…);
* **o CSV genérico**, com o assistente das colunas: :func:`previa_do_csv` mostra as primeiras linhas, o separador e
  o decimal achados; :func:`ler_csv` lê as colunas escolhidas, com a taxa de uma coluna de tempo ou dita;
* **o WAV** (PCM de 8, 16, 24 e 32 bits, e o ponto flutuante): os valores no fundo de escala ±1;
* **o COMTRADE** (IEEE C37.111 / IEC 60255-24: o ``.cfg`` com o ``.dat`` em ASCII, BINARY, BINARY32 ou FLOAT32):
  os canais analógicos na unidade do ``.cfg`` (``a · x + b``), com a taxa da primeira faixa de amostragem.

:func:`gravar_como_captura` grava o que foi lido num ``.h5`` no leiaute do ``adc_tool --export-hdf5`` (os códigos
``int16`` e a calibração de cada canal), com a taxa e a origem nos atributos: ele abre como qualquer captura, e o
espectro, as bandas, as figuras e a exportação valem para ele. **A quantização:** cada canal ocupa 80 % dos códigos
(o pico fica longe do fundo de escala, e nada parece saturado): o erro é de ``faixa / 65 536``, ~ −96 dB do pico,
abaixo do de qualquer osciloscópio de 8 a 12 bits. O WAV de 16 bits passa sem perda nenhuma.

:func:`gravar_comtrade` escreve canais na unidade física em COMTRADE 1999 (BINARY), para levar a outro programa de
qualidade de energia.

Depende de: ``erros``, ``constantes``, ``osciloscopio`` e ``hdf5`` (e ``scipy.io.wavfile``, importado ao usar).
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import osciloscopio as osc
from .constantes import GRANDEZA_CORRENTE, GRANDEZA_TENSAO
from .erros import ErroSHAN
from .hdf5 import gravar_amostras_importadas

EXTENSOES_IMPORTAVEIS = (".csv", ".txt", ".m", ".mat", ".wav", ".cfg")
MAX_CANAIS = 8                       # os canais de uma captura (os do ADC)
OCUPACAO = 0.8                       # a fração dos códigos que o maior valor de um canal ocupa
CODIGOS = 32768.0


@dataclass(frozen=True)
class CanalImportado:
    """Um canal lido: o nome que o arquivo dá, os valores (``float64``) e a unidade (``"V"``, ``"A"`` ou a do
    arquivo; o que não é corrente entra como tensão)."""

    nome: str
    valores: np.ndarray
    unidade: str = "V"

    @property
    def grandeza(self) -> int:
        return GRANDEZA_CORRENTE if self.unidade.strip().lower().endswith("a") else GRANDEZA_TENSAO


@dataclass(frozen=True)
class Importado:
    """O que um arquivo de fora tem: os canais (do mesmo tamanho), a taxa de **cada** canal e de onde veio."""

    canais: tuple[CanalImportado, ...]
    taxa_hz: float
    origem: str
    avisos: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.canais:
            raise ErroSHAN(f"{self.origem}: nenhum canal para importar.")
        n = {len(c.valores) for c in self.canais}
        if len(n) != 1:
            raise ErroSHAN(f"{self.origem}: os canais têm tamanhos diferentes ({sorted(n)}).")
        if not (math.isfinite(self.taxa_hz) and self.taxa_hz > 0):
            raise ErroSHAN(f"{self.origem}: a taxa de amostragem precisa ser positiva (não {self.taxa_hz!r}).")

    @property
    def n_amostras(self) -> int:
        return len(self.canais[0].valores)

    def com(self, *, taxa_hz: float | None = None, unidades: list[str] | None = None,
            escalas: list[float] | None = None, canais: list[int] | None = None) -> Importado:
        """Uma cópia com a taxa dita, as unidades e as escalas (o valor × escala) de cada canal, e só os ``canais``
        escolhidos (pela posição)."""
        escolhidos = list(range(len(self.canais))) if canais is None else list(canais)
        novos = []
        for j, i in enumerate(escolhidos):
            c = self.canais[i]
            escala = escalas[j] if escalas is not None else 1.0
            unidade = unidades[j] if unidades is not None else c.unidade
            novos.append(CanalImportado(c.nome, c.valores * escala if escala != 1.0 else c.valores, unidade))
        return Importado(tuple(novos), taxa_hz if taxa_hz is not None else self.taxa_hz, self.origem, self.avisos)


# ------------------------------------------------------------------ ler

def ler(caminho: Path, *, taxa_hz: float | None = None) -> Importado:
    """O arquivo ``caminho`` pela extensão (ver o começo do módulo); ``taxa_hz`` vale no lugar da que o arquivo diz
    (ou da que falta)."""
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroSHAN(f"arquivo '{caminho}' não encontrado.")
    sufixo = caminho.suffix.lower()
    if sufixo == ".wav":
        lido = ler_wav(caminho)
    elif sufixo == ".cfg":
        lido = ler_comtrade(caminho)
    elif sufixo in (".csv", ".txt", ".m", ".mat"):
        lido = ler_osciloscopio(caminho, taxa_hz=taxa_hz)
    else:
        raise ErroSHAN(f"'{caminho.name}': formato que não se importa (use {', '.join(EXTENSOES_IMPORTAVEIS)}).")
    return lido.com(taxa_hz=taxa_hz) if taxa_hz is not None else lido


def ler_osciloscopio(caminho: Path, *, taxa_hz: float | None = None) -> Importado:
    """Os canais de um arquivo de osciloscópio: cada candidato do leitor tolerante (uma variável, ou cada coluna de
    uma matriz com o tempo na primeira) do mesmo tamanho da forma de onda escolhida, e a taxa dela."""
    variaveis = osc.ler_variaveis(Path(caminho))
    try:
        forma = osc.montar_forma_de_onda(variaveis, caminho.name, fs=taxa_hz)
    except ErroSHAN as e:
        if taxa_hz is None and "taxa" in str(e).lower():
            raise ErroSHAN(f"{caminho.name}: o arquivo não diz a taxa de amostragem; diga-a ao importar.") from None
        raise
    n = len(forma.valores)
    canais, nomes = [], set()
    for nome, coluna, valores, _tempo in osc._candidatos(variaveis):
        if len(valores) != n or osc._normalizar(nome) in osc.NOMES_TEMPO:
            continue
        rotulo = nome if coluna is None else f"{nome}:{coluna}"
        if rotulo in nomes:
            continue
        nomes.add(rotulo)
        canais.append(CanalImportado(rotulo, np.asarray(valores, dtype=np.float64)))
        if len(canais) == MAX_CANAIS:
            break
    if not canais:
        canais = [CanalImportado("y", np.asarray(forma.valores, dtype=np.float64))]
    avisos = ()
    if forma.n_total > n:
        avisos = (f"o registro tem {forma.n_total} pontos; só os primeiros {n} foram lidos",)
    return Importado(tuple(canais), float(forma.fs), f"osciloscópio: {forma.origem}", avisos)


_SEPARADORES = (";", "\t", ",", " ")


@dataclass(frozen=True)
class PreviaDoCsv:
    """O que o assistente das colunas mostra: o separador e o decimal achados, os nomes das colunas (da linha de
    cabeçalho, ou "coluna 1", "coluna 2"…), as primeiras linhas e quantas linhas de texto pular."""

    separador: str
    decimal: str
    colunas: tuple[str, ...]
    linhas: tuple[tuple[str, ...], ...]
    pular: int
    coluna_de_tempo: int | None


def _numero(texto: str, decimal: str) -> float | None:
    texto = texto.strip().strip('"')
    if decimal == ",":
        texto = texto.replace(".", "").replace(",", ".") if texto.count(",") == 1 else texto
    try:
        return float(texto)
    except ValueError:
        return None


def previa_do_csv(caminho: Path, linhas: int = 12) -> PreviaDoCsv:
    """As primeiras linhas de um CSV qualquer, com o separador (``;``, tabulação, ``,`` ou espaço), o decimal e a
    linha do cabeçalho achados; a coluna de tempo, se uma é crescente e uniforme."""
    texto = Path(caminho).read_text(encoding="utf-8-sig", errors="replace")
    brutas = [linha for linha in texto.splitlines()[:400] if linha.strip()]
    if not brutas:
        raise ErroSHAN(f"{Path(caminho).name}: o arquivo está vazio.")

    def contagem(sep):
        return [len(next(csv.reader([linha], delimiter=sep))) for linha in brutas[-50:]]

    # O primeiro, na ordem de preferência, que divide as linhas do fim em 2 ou mais colunas, sempre as mesmas: o ";"
    # e a tabulação antes da vírgula (que, com o decimal de vírgula, também "dividiria" cada linha).
    separador = next((s for s in _SEPARADORES if min(contagem(s)) >= 2 and len(set(contagem(s))) == 1), ",")
    decimal = "," if separador != "," and re.search(r"\d,\d", "\n".join(brutas[-50:])) else "."
    tabela = [tuple(c.strip() for c in next(csv.reader([linha], delimiter=separador))) for linha in brutas]
    largura = max(len(linha) for linha in tabela[-50:])
    pular = 0
    while pular < len(tabela) and sum(_numero(c, decimal) is not None for c in tabela[pular]) < max(1, largura // 2):
        pular += 1
    if pular >= len(tabela):
        raise ErroSHAN(f"{Path(caminho).name}: nenhuma linha numérica.")
    cabecalho = tabela[pular - 1] if pular else ()
    nomes = tuple((cabecalho[i] if i < len(cabecalho) and cabecalho[i] else f"coluna {i + 1}")
                  for i in range(largura))
    dados = tabela[pular:]
    tempo = None
    for i in range(largura):
        v = np.array([_numero(linha[i], decimal) if i < len(linha) else None for linha in dados[:200]], dtype=float)
        if np.all(np.isfinite(v)) and osc._crescente_uniforme(v):
            tempo = i
            break
    return PreviaDoCsv(separador, decimal, nomes, tuple(dados[:linhas]), pular, tempo)


def ler_csv(caminho: Path, colunas: list[int], *, coluna_de_tempo: int | None = None, taxa_hz: float | None = None,
            separador: str | None = None, decimal: str | None = None, pular: int | None = None,
            unidades: list[str] | None = None) -> Importado:
    """As ``colunas`` (a partir de 0) de um CSV qualquer como canais; a taxa vem de ``taxa_hz`` ou da
    ``coluna_de_tempo`` (o passo médio, que precisa ser uniforme). O que ``previa_do_csv`` acha vale para o que
    não for dito."""
    previa = previa_do_csv(caminho)
    separador = separador or previa.separador
    decimal = decimal or previa.decimal
    pular = previa.pular if pular is None else pular
    if not colunas:
        raise ErroSHAN("escolha ao menos uma coluna de valores.")
    if len(colunas) > MAX_CANAIS:
        raise ErroSHAN(f"no máximo {MAX_CANAIS} canais por captura (escolhidas {len(colunas)}).")
    texto = Path(caminho).read_text(encoding="utf-8-sig", errors="replace")
    linhas = [linha for linha in texto.splitlines() if linha.strip()][pular:]
    if decimal == ",":                         # "1.234,5" vira "1234.5"; só nos números, depois de separar
        def ler_campo(c):
            return c.replace(".", "").replace(",", ".")
    else:
        def ler_campo(c):
            return c
    leitor = csv.reader(io.StringIO("\n".join(linhas)), delimiter=separador)
    pedidas = list(colunas) + ([coluna_de_tempo] if coluna_de_tempo is not None else [])
    valores = {c: [] for c in pedidas}
    for registro in leitor:
        try:
            numeros = [float(ler_campo(registro[c].strip().strip('"'))) for c in pedidas]
        except (ValueError, IndexError):
            continue                           # uma linha de texto no meio (um rodapé): fica de fora
        for c, v in zip(pedidas, numeros):
            valores[c].append(v)
    n = len(valores[colunas[0]])
    if n < 2:
        raise ErroSHAN(f"{Path(caminho).name}: menos de 2 linhas numéricas nas colunas escolhidas.")
    if taxa_hz is None:
        if coluna_de_tempo is None:
            raise ErroSHAN("diga a taxa de amostragem ou escolha a coluna de tempo.")
        t = np.asarray(valores[coluna_de_tempo])
        passos = np.diff(t)
        if not np.all(passos > 0) or float(np.std(passos) / np.mean(passos)) > 1e-3:
            raise ErroSHAN("a coluna de tempo não é crescente com o passo uniforme: diga a taxa de amostragem.")
        taxa_hz = 1.0 / float(np.mean(passos))
    nomes = [previa.colunas[c] if c < len(previa.colunas) else f"coluna {c + 1}" for c in colunas]
    canais = tuple(CanalImportado(nome, np.asarray(valores[c], dtype=np.float64),
                                  unidades[i] if unidades is not None else _unidade_do_nome(nome))
                   for i, (nome, c) in enumerate(zip(nomes, colunas)))
    return Importado(canais, float(taxa_hz), f"CSV: {Path(caminho).name}")


def _unidade_do_nome(nome: str) -> str:
    """"Corrente (A)", "I_a [A]" → A; o resto → V."""
    m = re.search(r"[\[(]\s*(m?A|k?V|mV)\s*[\])]", nome)
    if m:
        return "A" if m[1].endswith("A") else "V"
    return "A" if re.match(r"^(i|corrente|current)\b", nome.strip().lower()) else "V"


def ler_wav(caminho: Path) -> Importado:
    """Os canais de um WAV, no fundo de escala ±1 (o PCM inteiro ÷ 2^(bits−1); o de ponto flutuante como está)."""
    from scipy.io import wavfile

    try:
        taxa, dados = wavfile.read(str(caminho), mmap=False)
    except (ValueError, OSError) as e:
        raise ErroSHAN(f"{Path(caminho).name}: não é um WAV legível ({e}).") from None
    dados = np.asarray(dados)
    if dados.ndim == 1:
        dados = dados[:, None]
    if dados.shape[1] > MAX_CANAIS:
        raise ErroSHAN(f"{Path(caminho).name}: {dados.shape[1]} canais (no máximo {MAX_CANAIS}).")
    if dados.dtype.kind == "u":                                  # o PCM de 8 bits é sem sinal
        escala = 2.0 ** (8 * dados.dtype.itemsize - 1)
        valores = (dados.astype(np.float64) - escala) / escala
    elif dados.dtype.kind == "i":
        valores = dados.astype(np.float64) / 2.0 ** (8 * dados.dtype.itemsize - 1)
    else:
        valores = dados.astype(np.float64)
    canais = tuple(CanalImportado(f"canal {i + 1}", valores[:, i].copy()) for i in range(dados.shape[1]))
    avisos = ("o WAV não diz a unidade: os valores estão no fundo de escala ±1 (ajuste a escala ao importar)",)
    return Importado(canais, float(taxa), f"WAV: {Path(caminho).name}", avisos)


# ------------------------------------------------------------------ COMTRADE

_TIPOS_DO_DAT = {"binary": ("<i2", 2), "binary32": ("<i4", 4), "float32": ("<f4", 4)}


def ler_comtrade(caminho_cfg: Path) -> Importado:
    """Os canais analógicos de um COMTRADE (1991, 1999 ou 2013), na unidade do ``.cfg`` (``a · x + b``, o valor
    primário quando o ``.cfg`` diz ``P``), com a taxa da primeira faixa de amostragem."""
    caminho_cfg = Path(caminho_cfg)
    linhas = caminho_cfg.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    try:
        _estacao = linhas[0]
        contagem = [c.strip() for c in linhas[1].split(",")]
        n_analogicos = int(contagem[1].rstrip("Aa"))
        n_digitais = int(contagem[2].rstrip("Dd"))
        analogicos = []
        for i in range(n_analogicos):
            c = [x.strip() for x in linhas[2 + i].split(",")]
            nome, fase, unidade = c[1], c[2], c[4]
            a, b = float(c[5]), float(c[6])
            primario = secundario = 1.0
            ps = "s"
            if len(c) >= 13:
                primario, secundario, ps = float(c[10] or 1), float(c[11] or 1), c[12].lower()
            analogicos.append((nome + (f" {fase}" if fase else ""), unidade, a, b, primario, secundario, ps))
        k = 2 + n_analogicos + n_digitais
        _frequencia_da_rede = linhas[k]
        n_taxas = int(linhas[k + 1].split(",")[0])
        taxas = [tuple(float(x) for x in linhas[k + 2 + i].split(",")[:2]) for i in range(max(n_taxas, 1))]
        k += 2 + max(n_taxas, 1)
        inicio = linhas[k].strip()
        tipo = linhas[k + 2].strip().lower()
        multiplicador = float(linhas[k + 3].split(",")[0]) if len(linhas) > k + 3 and linhas[k + 3].strip() else 1.0
    except (IndexError, ValueError) as e:
        raise ErroSHAN(f"{caminho_cfg.name}: o .cfg não é um COMTRADE que se lê ({e}).") from None
    dat = next((caminho_cfg.with_suffix(s) for s in (".dat", ".DAT") if caminho_cfg.with_suffix(s).is_file()), None)
    if dat is None:
        raise ErroSHAN(f"{caminho_cfg.name}: o .dat do mesmo nome não está na pasta.")
    if tipo == "ascii":
        tabela = np.loadtxt(dat, delimiter=",", ndmin=2)
        brutos = tabela[:, 2:2 + n_analogicos]
        tempos = tabela[:, 1]
    elif tipo in _TIPOS_DO_DAT:
        formato, _largura = _TIPOS_DO_DAT[tipo]
        palavras = math.ceil(n_digitais / 16)
        registro = np.dtype([("n", "<u4"), ("t", "<u4"), ("a", formato, (n_analogicos,)),
                             ("d", "<u2", (palavras,))])
        tabela = np.fromfile(dat, dtype=registro)
        brutos, tempos = tabela["a"].astype(np.float64), tabela["t"].astype(np.float64)
    else:
        raise ErroSHAN(f"{caminho_cfg.name}: o tipo de .dat {tipo!r} não é ASCII, BINARY, BINARY32 nem FLOAT32.")
    taxa = taxas[0][0] if taxas and taxas[0][0] > 0 else 0.0
    if taxa <= 0:                                   # sem taxa fixa: o passo dos instantes (µs × o multiplicador)
        passos = np.diff(tempos) * multiplicador * 1e-6
        if len(passos) == 0 or not np.all(passos > 0):
            raise ErroSHAN(f"{caminho_cfg.name}: sem a taxa no .cfg e sem instantes crescentes no .dat.")
        taxa = 1.0 / float(np.mean(passos))
    avisos = []
    if n_taxas > 1:
        avisos.append(f"o registro tem {n_taxas} faixas de amostragem; todas foram lidas na taxa da primeira "
                      f"({taxa:g} Hz)")
    canais = []
    for i, (nome, unidade, a, b, primario, secundario, ps) in enumerate(analogicos[:MAX_CANAIS]):
        valores = a * brutos[:, i] + b
        if ps == "s" and secundario:                   # o .cfg em valores secundários: o primário é × P/S
            valores = valores * (primario / secundario)
        u = unidade.strip()
        fator = 1e3 if u.lower().startswith("k") else 1e-3 if u.startswith("m") else 1.0
        canais.append(CanalImportado(nome, valores * fator, "A" if u.lower().endswith("a") else "V"))
    if n_analogicos > MAX_CANAIS:
        avisos.append(f"o registro tem {n_analogicos} canais analógicos; os {MAX_CANAIS} primeiros foram lidos")
    return Importado(tuple(canais), float(taxa), f"COMTRADE: {caminho_cfg.name} ({inicio})", tuple(avisos))


def gravar_comtrade(destino_cfg: Path, nomes: list[str], unidades: list[str], valores: list[np.ndarray],
                    taxa_hz: float, *, estacao: str = "SH-Analyzer", inicio: datetime | None = None,
                    frequencia_da_rede: float = 60.0) -> tuple[Path, Path]:
    """Os canais em COMTRADE 1999, ``.cfg`` e ``.dat`` BINARY: cada canal em ``int16`` com o ``a`` que ocupa a
    faixa dele (o ``b`` no meio), os valores primários. Devolve os dois caminhos."""
    destino_cfg = Path(destino_cfg).with_suffix(".cfg")
    n = len(valores[0])
    if any(len(v) != n for v in valores):
        raise ErroSHAN("os canais do COMTRADE precisam ter o mesmo tamanho.")
    inicio = inicio or datetime.now(timezone.utc)
    codigos, linhas_dos_canais = [], []
    for i, (nome, unidade, v) in enumerate(zip(nomes, unidades, valores), start=1):
        v = np.asarray(v, dtype=np.float64)
        mn, mx = (float(np.nanmin(v)), float(np.nanmax(v))) if n else (0.0, 0.0)
        b = (mx + mn) / 2
        a = (mx - mn) / 2 / 32767 or 1.0
        codigos.append(np.clip(np.round((v - b) / a), -32767, 32767).astype("<i2"))
        nome_limpo = re.sub(r"[,\r\n]", " ", nome)[:64]
        linhas_dos_canais.append(f"{i},{nome_limpo},,,{unidade},{a:.9g},{b:.9g},0,-32767,32767,1,1,P")
    data = inicio.strftime("%d/%m/%Y,%H:%M:%S.%f")
    cfg = [f"{estacao},SH-Analyzer,1999", f"{len(valores)},{len(valores)}A,0D", *linhas_dos_canais,
           f"{frequencia_da_rede:g}", "1", f"{taxa_hz:.9g},{n}", data, data, "BINARY", "1"]
    destino_cfg.write_text("\r\n".join(cfg) + "\r\n", encoding="ascii", errors="replace")
    registro = np.dtype([("n", "<u4"), ("t", "<u4"), ("a", "<i2", (len(valores),))])
    tabela = np.zeros(n, dtype=registro)
    tabela["n"] = np.arange(1, n + 1, dtype=np.uint64).astype("<u4")
    tabela["t"] = np.round(np.arange(n) / taxa_hz * 1e6).astype(np.uint64).astype("<u4")
    tabela["a"] = np.stack(codigos, axis=1) if codigos else 0
    destino_dat = destino_cfg.with_suffix(".dat")
    tabela.tofile(destino_dat)
    return destino_cfg, destino_dat


# ------------------------------------------------------------------ gravar como captura

def gravar_como_captura(importado: Importado, destino: Path, *, versao_codigo: str = "") -> Path:
    """O ``.h5`` de ``importado`` (ver o começo do módulo), que :func:`api.abrir_captura` abre com a taxa e a
    calibração gravadas. Os canais são numerados 0, 1, 2… na ordem de ``importado``."""
    k = len(importado.canais)
    if k > MAX_CANAIS:
        raise ErroSHAN(f"no máximo {MAX_CANAIS} canais por captura ({k} pedidos).")
    faixas, offsets, colunas = [], [], []
    for c in importado.canais:
        v = np.asarray(c.valores, dtype=np.float64)
        finitos = v[np.isfinite(v)]
        mn, mx = (float(finitos.min()), float(finitos.max())) if finitos.size else (0.0, 0.0)
        centro = (mx + mn) / 2
        meio = (mx - mn) / 2 or max(abs(centro), 1.0) * 1e-3 or 1.0
        faixa = meio / OCUPACAO
        codigos = np.round(np.nan_to_num(v - centro) * (CODIGOS / faixa))
        colunas.append(np.clip(codigos, -32768, 32767).astype("<i2"))
        faixas.append(faixa)
        offsets.append(-centro)              # volts = código · faixa / 32 768 − offset (amostras.converter_para_tensao)
    return gravar_amostras_importadas(
        destino, np.stack(colunas, axis=1), faixas=faixas, offsets=offsets,
        grandezas=[c.grandeza for c in importado.canais], taxa_total_hz=importado.taxa_hz * k,
        nomes=[c.nome for c in importado.canais], origem=importado.origem, versao_codigo=versao_codigo)
