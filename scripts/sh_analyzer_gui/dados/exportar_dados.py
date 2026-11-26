"""A exportação dos dados (a F5.5; docs/gui-plan.md, 10.4; FG-07), sem Qt: os traços de uma vista num trecho (a
janela, a região dos cursores ou a captura inteira) em CSV, HDF5, MAT ou NPZ, **sempre em blocos** (a memória não
depende do tamanho do trecho: uma captura de 1 h sai inteira) e sempre com o ``proveniencia.json`` ao lado.

**O que sai:** uma coluna por traço, na unidade dele (``valor = amostra · escala + deslocamento``, em ``float64``:
os mesmos números da tela), ou **crus** (os códigos do ADC, no tipo da captura, com a escala e o deslocamento de cada
coluna para chegar à unidade). Um traço com transformações (a cadeia) sai transformado, da materialização dele (os
crus não existem para ele); sem elas, do canal. Os traços dividem uma taxa (um trecho de traços de taxas diferentes é
recusado); cada um começa na amostra dele mais perto do início do trecho, e o tempo de cada um vai nos metadados.

| Formato | Como |
|---|---|
| CSV | o tempo e uma coluna por traço, com o cabeçalho de metadados em comentários ``#``; o separador e o decimal escolhidos |
| HDF5 | no estilo do ``adc_tool`` (``supraharmonicos/hdf5.py``): ``/amostras`` (os códigos, linhas × colunas) ou ``/valores``, e os atributos das colunas na raiz (as transformações de cada uma em JSON); quando os traços vêm de uma captura só, o grupo ``/captura`` com o cabeçalho dela como o ``--export-hdf5`` o grava (os atributos e o ``cabecalho_bruto``) |
| MAT | o v5 até :data:`LIMITE_DO_MAT_V5` bytes por variável, gravado em blocos (o ``scipy.io.savemat`` pediria tudo na memória); acima, o v7.3 (o HDF5 com o cabeçalho do MATLAB) |
| NPZ | os ``.npy`` gravados em blocos direto no ``.zip``, sem compressão |

O tempo explícito só vai no CSV; nos outros, ``taxa_hz`` e ``t0_s`` (o tempo da linha 0) o dão sem dobrar o arquivo.
"""

from __future__ import annotations

import json
import math
import struct
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from supraharmonicos.api import Cancelado, ErroSHAN

from .proveniencia import em_texto

LINHAS_POR_BLOCO = 1 << 20
LIMITE_DO_MAT_V5 = (1 << 31) - 4096        # o tamanho de uma variável no v5 (o elemento tem 32 bits de tamanho)
SEPARADORES = {";": "ponto e vírgula", ",": "vírgula", "\t": "tabulação"}
DECIMAIS = (",", ".")


@dataclass(frozen=True)
class FormatoDeDados:
    id: str
    nome: str
    extensao: str
    descricao: str


FORMATOS: dict[str, FormatoDeDados] = {f.id: f for f in (
    FormatoDeDados("csv", "CSV", ".csv", "Texto: planilhas e qualquer programa"),
    FormatoDeDados("hdf5", "HDF5", ".h5", "No estilo do adc_tool, com o cabeçalho da captura"),
    FormatoDeDados("mat", "MAT", ".mat", "MATLAB e Octave (v7.3 acima de 2 GB)"),
    FormatoDeDados("npz", "NPZ", ".npz", "Python (numpy.load)"),
    FormatoDeDados("wav", "WAV", ".wav", "Áudio: em unidades, ponto flutuante de 32 bits; crus, os códigos em 16 bits"),
    FormatoDeDados("comtrade", "COMTRADE", ".cfg", "IEEE C37.111 (1999, binário): o .cfg e o .dat, para os programas "
                                                   "de qualidade de energia"),
)}
LIMITE_DO_WAV = (1 << 32) - 64
"""Os bytes de dados que o cabeçalho do WAV (32 bits) consegue dizer."""


class DadosInvalidos(ErroSHAN, ValueError):
    """A exportação pedida não pode sair assim (a razão vai na mensagem)."""


@dataclass(frozen=True, eq=False)
class ColunaDeDados:
    """Um traço: ``amostras`` (o vetor inteiro de onde ele sai: o canal, ou a materialização), a taxa, ``t0_s`` (o
    tempo, no eixo da vista, da amostra 0) e a conversão para a unidade."""

    nome: str
    amostras: np.ndarray
    taxa_hz: float
    t0_s: float = 0.0
    escala: float = 1.0
    deslocamento: float = 0.0
    unidade: str = ""
    grandeza: str = ""
    codigos: bool = True                  # ``amostras`` são os códigos do ADC (False: a materialização, já transformada)
    fonte: str = ""                       # o id da captura
    receita: dict = field(default_factory=dict)


@dataclass(frozen=True, eq=False)
class TrechoDeDados:
    """As colunas, a primeira posição de cada uma e quantas linhas."""

    colunas: tuple[ColunaDeDados, ...]
    inicios: tuple[int, ...]
    n: int

    @property
    def taxa_hz(self) -> float:
        return self.colunas[0].taxa_hz

    @property
    def t0_s(self) -> float:
        """O tempo da linha 0 (o da primeira coluna)."""
        return self.t0_por_coluna[0]

    @property
    def t0_por_coluna(self) -> list[float]:
        return [c.t0_s + i / c.taxa_hz for c, i in zip(self.colunas, self.inicios, strict=True)]

    def bloco(self, a: int, b: int, *, crus: bool) -> np.ndarray:
        """As linhas ``[a, b)``, ``(b - a) × colunas``: os códigos (``crus``) ou os valores em ``float64``."""
        partes = []
        for c, i in zip(self.colunas, self.inicios, strict=True):
            trecho = np.asarray(c.amostras[i + a:i + b])
            partes.append(trecho if crus else trecho.astype(np.float64) * c.escala + c.deslocamento)
        return np.column_stack(partes)

    def tempo(self, a: int, b: int) -> np.ndarray:
        return self.t0_s + np.arange(a, b, dtype=np.float64) / self.taxa_hz


def recortar(colunas: Sequence[ColunaDeDados], regioes: Sequence[tuple[float, float]] | None = None) -> TrechoDeDados:
    """O trecho das colunas entre os tempos de ``regioes`` (uma por coluna, no eixo da vista; ``None``: a captura
    inteira). As amostras de cada coluna entre ``a`` e ``b`` (as das pontas incluídas); todas com o mesmo número de
    linhas (o menor)."""
    colunas = tuple(colunas)
    if not colunas:
        raise DadosInvalidos("nenhum traço visível para exportar")
    taxas = {c.taxa_hz for c in colunas}
    if len(taxas) > 1:
        raise DadosInvalidos("os traços têm taxas diferentes ("
                             + ", ".join(f"{t:g} Hz" for t in sorted(taxas)) + "): exporte-os separados")
    inicios, fins = [], []
    for k, c in enumerate(colunas):
        n = len(c.amostras)
        if regioes is None:
            i0, i1 = 0, n
        else:
            a, b = regioes[k]
            i0 = max(0, math.ceil((a - c.t0_s) * c.taxa_hz - 1e-9))
            i1 = min(n, math.floor((b - c.t0_s) * c.taxa_hz + 1e-9) + 1)
        inicios.append(i0)
        fins.append(max(i0, i1))
    linhas = min(f - i for i, f in zip(inicios, fins, strict=True))
    if linhas <= 0:
        raise DadosInvalidos("o trecho não tem nenhuma amostra")
    return TrechoDeDados(colunas, tuple(inicios), linhas)


@dataclass(frozen=True)
class OpcoesDosDados:
    formato: str = "csv"
    crus: bool = False
    separador: str = ";"
    decimal: str = ","

    def __post_init__(self):
        if self.formato not in FORMATOS:
            raise DadosInvalidos(f"formato desconhecido: {self.formato!r} (use {', '.join(FORMATOS)})")
        if self.separador not in SEPARADORES:
            raise DadosInvalidos(f"separador inválido: {self.separador!r}")
        if self.decimal not in DECIMAIS:
            raise DadosInvalidos(f"decimal inválido: {self.decimal!r} (use , ou .)")
        if self.formato == "csv" and self.separador == self.decimal:
            raise DadosInvalidos("o separador das colunas e o decimal não podem ser o mesmo")


def conferir(trecho: TrechoDeDados, opcoes: OpcoesDosDados) -> None:
    if opcoes.formato == "comtrade" and opcoes.crus:
        raise DadosInvalidos("o COMTRADE guarda os valores na unidade (o a·x + b de cada canal): exporte em unidades")
    if opcoes.formato == "wav":
        largura = 2 if opcoes.crus else 4
        if trecho.n * len(trecho.colunas) * largura > LIMITE_DO_WAV:
            raise DadosInvalidos("o trecho passa de 4 GB, o maior WAV que existe: exporte em HDF5 ou escolha uma região")
        if len({round(c.taxa_hz) for c in trecho.colunas}) > 1:
            raise DadosInvalidos("os traços têm taxas diferentes, e um WAV tem uma só")
    if opcoes.crus:
        transformados = [c.nome for c in trecho.colunas if not c.codigos]
        if transformados:
            raise DadosInvalidos("os crus são os códigos do ADC, e " + ", ".join(transformados)
                                 + " tem transformações: exporte em unidades")
        tipos = {np.asarray(c.amostras[:0]).dtype for c in trecho.colunas}
        if len(tipos) > 1:
            raise DadosInvalidos("os traços vêm de capturas com códigos de tipos diferentes: exporte em unidades")


def nome_do_arquivo(nome: str, regiao: str, opcoes: OpcoesDosDados) -> str:
    """O nome sugerido: o da vista e a região (``"Vista 1 - janela.csv"``), sem o que não vai num nome de arquivo."""
    base = "".join(c if c.isalnum() or c in " -_." else "_" for c in nome).strip() or "dados"
    return f"{base} - {regiao}{FORMATOS[opcoes.formato].extensao}"


def caminho_da_proveniencia(destino: Path) -> Path:
    """O ``proveniencia.json`` que acompanha ``destino``: ``dados.csv`` -> ``dados.proveniencia.json``."""
    return destino.with_name(destino.stem + ".proveniencia.json")


def exportar(trecho: TrechoDeDados, destino: Path, opcoes: OpcoesDosDados, *, proveniencia: Mapping,
             captura: tuple[Mapping, bytes] | None = None, progresso: Callable[[float], None] | None = None,
             cancelado: Callable[[], bool] | None = None, linhas_por_bloco: int = LINHAS_POR_BLOCO) -> list[Path]:
    """Grava ``trecho`` em ``destino`` e a proveniência ao lado; devolve os dois caminhos. Os dois saem inteiros ou
    não saem (um ``.parcial`` renomeado no fim). ``captura``: o cabeçalho da captura de onde todos os traços vêm
    (``api.cabecalho_para_hdf5``: os atributos e os bytes), que o HDF5 guarda no grupo ``/captura``."""
    conferir(trecho, opcoes)
    destino = Path(destino)
    if opcoes.formato == "comtrade":
        return _comtrade(trecho, destino, proveniencia, progresso)
    parcial = destino.with_name(destino.name + ".parcial")
    escrever = {"csv": _csv, "hdf5": _hdf5, "mat": _mat, "npz": _npz, "wav": _wav}[opcoes.formato]
    blocos = _Blocos(trecho, linhas_por_bloco, progresso, cancelado)
    try:
        escrever(trecho, parcial, opcoes, proveniencia, captura, blocos)
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise
    parcial.replace(destino)
    json_ = caminho_da_proveniencia(destino)
    json_.write_text(json.dumps(proveniencia, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if progresso is not None:
        progresso(1.0)
    return [destino, json_]


class _Blocos:
    """Os blocos de linhas, o progresso (a fração das linhas já gravadas, somadas as passadas) e o cancelar."""

    def __init__(self, trecho: TrechoDeDados, tamanho: int, progresso, cancelado, passadas: int = 1):
        self.trecho, self.tamanho, self.progresso, self.cancelado = trecho, max(1, tamanho), progresso, cancelado
        self.passadas, self.feitas = passadas, 0

    def __call__(self):
        n = self.trecho.n
        for a in range(0, n, self.tamanho):
            if self.cancelado is not None and self.cancelado():
                raise Cancelado()
            b = min(n, a + self.tamanho)
            yield a, b
            self.feitas += b - a
            if self.progresso is not None:
                self.progresso(min(0.99, self.feitas / (n * self.passadas)))


# ------------------------------------------------------------------ os metadados comuns

def _metadados(trecho: TrechoDeDados, opcoes: OpcoesDosDados, proveniencia: Mapping) -> dict:
    colunas = trecho.colunas
    return {
        "formato": "sh-analyzer-dados", "versao": 1, "taxa_hz": trecho.taxa_hz, "t0_s": trecho.t0_s,
        "linhas": trecho.n, "crus": opcoes.crus, "nomes": [c.nome for c in colunas],
        "unidades": [c.unidade for c in colunas], "grandezas": [c.grandeza for c in colunas],
        "escala_por_coluna": [c.escala if opcoes.crus else 1.0 for c in colunas],
        "deslocamento_por_coluna": [c.deslocamento if opcoes.crus else 0.0 for c in colunas],
        "t0_s_por_coluna": trecho.t0_por_coluna,
        "transformacoes_por_coluna": [_aplicadas(c) for c in colunas],
        "proveniencia": em_texto(proveniencia),
    }


def _aplicadas(coluna: ColunaDeDados) -> list:
    """As etapas da cadeia que a coluna tem aplicadas (as ligadas; nenhuma numa coluna do canal)."""
    if coluna.codigos:
        return []
    return [e for e in coluna.receita.get("etapas", []) if not isinstance(e, Mapping) or e.get("ligada", True)]


# ------------------------------------------------------------------ CSV

def _csv(trecho, caminho, opcoes, proveniencia, _captura, blocos) -> None:
    sep, dec = opcoes.separador, opcoes.decimal
    meta = _metadados(trecho, opcoes, proveniencia)

    def numero(v: float) -> str:                 # o menor texto que volta ao mesmo float64 (a escala exata)
        return repr(float(v)).replace(".", dec)

    linhas = [f"# SH-Analyzer: dados exportados ({'códigos do ADC' if opcoes.crus else 'em unidades'})",
              f"# taxa_hz: {numero(trecho.taxa_hz)}", f"# t0_s: {numero(trecho.t0_s)}", f"# linhas: {trecho.n}"]
    for c, t0 in zip(trecho.colunas, meta["t0_s_por_coluna"], strict=True):
        conta = (f"valor = código × {numero(c.escala)} + {numero(c.deslocamento)} {c.unidade}".rstrip()
                 if opcoes.crus else c.unidade or "sem unidade")
        linhas.append(f"# {c.nome}: {conta}; t0_s {numero(t0)}"
                      + (f"; transformações: {json.dumps(_aplicadas(c), ensure_ascii=False)}"
                         if _aplicadas(c) else ""))
    linhas.append(f"# proveniência: {caminho.name.removesuffix('.parcial').rsplit('.', 1)[0]}.proveniencia.json")
    cabecalho = sep.join(["tempo_s"] + [f"{c.nome} ({c.unidade})" if c.unidade and not opcoes.crus else c.nome
                                         for c in trecho.colunas])
    formato_valor = "%d" if opcoes.crus else "%.15g"         # 15 algarismos: o float64 tem ~15,9
    with open(caminho, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(linhas) + "\n" + cabecalho + "\n")
        saida = f if dec == "." else _TrocaODecimal(f, dec)   # linha a linha: o texto do bloco não se acumula
        for a, b in blocos():
            tabela = trecho.bloco(a, b, crus=opcoes.crus)          # os códigos de 16 bits cabem exatos no float64
            np.savetxt(saida, np.column_stack([trecho.tempo(a, b), tabela.astype(np.float64)]),
                       fmt=["%.15g"] + [formato_valor] * tabela.shape[1], delimiter=sep)


class _TrocaODecimal:
    """O arquivo que recebe o texto do ``savetxt`` com o ponto decimal trocado (o separador nunca é o decimal)."""

    def __init__(self, arquivo, decimal: str):
        self.arquivo, self.decimal = arquivo, decimal

    def write(self, texto: str) -> int:
        return self.arquivo.write(texto.replace(".", self.decimal))


# ------------------------------------------------------------------ HDF5 (o leiaute do adc_tool)

def _hdf5(trecho, caminho, opcoes, proveniencia, captura, blocos) -> None:
    import h5py

    meta = _metadados(trecho, opcoes, proveniencia)
    k = len(trecho.colunas)
    with h5py.File(caminho, "w") as f5:
        _atributos(f5.attrs, meta)
        if captura is not None:
            atributos, bruto = captura
            grupo = f5.create_group("captura")
            for chave, valor in atributos.items():
                grupo.attrs[chave] = valor
            grupo.attrs["descricao"] = ("A captura de onde os traços vêm: o cabeçalho dela, como o adc_tool "
                                        "--export-hdf5 o grava (os atributos e os bytes).")
            dados_do_cabecalho = grupo.create_dataset("cabecalho_bruto", data=np.frombuffer(bruto, np.uint8))
            dados_do_cabecalho.attrs["descricao"] = ("Os bytes do cabeçalho do .bin de origem, como gravados pelo "
                                                     "ler_adc (a versão no atributo 'cabecalho_versao').")
        if opcoes.crus:
            tipo = np.asarray(trecho.colunas[0].amostras[:0]).dtype
            dados = f5.create_dataset("amostras", shape=(trecho.n, k), dtype=tipo, chunks=True)
            dados.attrs["descricao"] = ("Os códigos do ADC (sem calibração). Linha = 1 instante; coluna i = o traço "
                                        "nomes[i]; o valor = código × escala_por_coluna[i] + "
                                        "deslocamento_por_coluna[i], na unidade unidades[i].")
        else:
            dados = f5.create_dataset("valores", shape=(trecho.n, k), dtype=np.float64, chunks=True)
            dados.attrs["descricao"] = ("Os valores na unidade de cada traço (unidades[i]), com as transformações "
                                        "de cada um (transformacoes_por_coluna). Linha = 1 instante; coluna i = o "
                                        "traço nomes[i].")
        for a, b in blocos():
            dados[a:b] = trecho.bloco(a, b, crus=opcoes.crus)


def _atributos(attrs, meta: Mapping) -> None:
    """Os metadados como atributos: as listas de textos como textos UTF-8, as de listas (as transformações) em JSON."""
    import h5py

    for chave, valor in meta.items():
        if isinstance(valor, list) and valor and isinstance(valor[0], str):
            attrs.create(chave, valor, dtype=h5py.string_dtype())
        elif isinstance(valor, list) and valor and isinstance(valor[0], (list, dict)):
            attrs[chave] = json.dumps(valor, ensure_ascii=False)
        elif isinstance(valor, list):
            attrs[chave] = np.asarray(valor, dtype=np.float64)
        else:
            attrs[chave] = valor


# ------------------------------------------------------------------ NPZ (os .npy em blocos dentro do .zip)

def _npz(trecho, caminho, opcoes, proveniencia, _captura, blocos) -> None:
    meta = _metadados(trecho, opcoes, proveniencia)
    k = len(trecho.colunas)
    tipo = np.asarray(trecho.colunas[0].amostras[:0]).dtype if opcoes.crus else np.dtype(np.float64)
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        for chave, valor in meta.items():
            if isinstance(valor, list) and valor and isinstance(valor[0], (list, dict)):
                valor = [json.dumps(v, ensure_ascii=False) for v in valor]      # uma cadeia por coluna, em JSON
            with z.open(f"{chave}.npy", "w") as f:
                np.lib.format.write_array(f, np.asarray(valor), allow_pickle=False)
        nome = "amostras" if opcoes.crus else "valores"
        with z.open(f"{nome}.npy", "w", force_zip64=True) as f:
            np.lib.format.write_array_header_2_0(f, {"descr": np.lib.format.dtype_to_descr(tipo),
                                                     "fortran_order": False, "shape": (trecho.n, k)})
            for a, b in blocos():
                f.write(np.ascontiguousarray(trecho.bloco(a, b, crus=opcoes.crus), dtype=tipo).tobytes())


# ------------------------------------------------------------------ WAV e COMTRADE

def _wav(trecho, caminho, opcoes, _proveniencia, _captura, blocos) -> None:
    """O WAV: os valores em ponto flutuante de 32 bits (o formato 3, IEEE), na unidade de cada traço (um programa de
    áudio só toca bem o que fica em ±1; o Python e o MATLAB leem os números exatos), ou os códigos do ADC em PCM de 16
    bits. A taxa do cabeçalho é inteira (arredondada)."""
    k = len(trecho.colunas)
    tipo, codigo = (np.dtype("<i2"), 1) if opcoes.crus else (np.dtype("<f4"), 3)
    largura = tipo.itemsize
    tamanho = trecho.n * k * largura
    taxa = int(round(trecho.taxa_hz))
    with open(caminho, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + tamanho) + b"WAVE")
        f.write(b"fmt " + struct.pack("<IHHIIHH", 16, codigo, k, taxa, taxa * k * largura, k * largura,
                                      8 * largura))
        f.write(b"data" + struct.pack("<I", tamanho))
        for a, b in blocos():
            bloco = trecho.bloco(a, b, crus=opcoes.crus)
            if opcoes.crus and bloco.dtype == np.uint16:       # o uint16 do ADC unipolar: o PCM é com sinal
                bloco = bloco.astype(np.int32) - 32768
            f.write(np.ascontiguousarray(bloco, dtype=tipo).tobytes())


def _comtrade(trecho, destino: Path, proveniencia, progresso) -> list[Path]:
    """O COMTRADE 1999 binário (``api.importacao.gravar_comtrade``): o ``.cfg`` e o ``.dat`` com o mesmo nome, e a
    proveniência ao lado."""
    from supraharmonicos.api import importacao

    valores = [np.asarray(trecho.bloco(0, trecho.n, crus=False)[:, j]) for j in range(len(trecho.colunas))]
    cfg, dat = importacao.gravar_comtrade(destino, [c.nome for c in trecho.colunas],
                                          [c.unidade or "V" for c in trecho.colunas], valores, trecho.taxa_hz)
    json_ = caminho_da_proveniencia(cfg)
    json_.write_text(json.dumps(proveniencia, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if progresso is not None:
        progresso(1.0)
    return [cfg, dat, json_]


# ------------------------------------------------------------------ MAT

_MI = {"int8": 1, "uint8": 2, "int16": 3, "uint16": 4, "int32": 5, "uint32": 6, "double": 9, "matrix": 14}
_MX = {"char": 4, "double": 6, "int16": 10, "uint16": 11}
_CLASSE = {np.dtype(np.float64): "double", np.dtype(np.int16): "int16", np.dtype(np.uint16): "uint16"}


def _mat(trecho, caminho, opcoes, proveniencia, _captura, blocos) -> None:
    meta = _metadados(trecho, opcoes, proveniencia)
    tipo = np.asarray(trecho.colunas[0].amostras[:0]).dtype if opcoes.crus else np.dtype(np.float64)
    if tipo not in _CLASSE:
        raise DadosInvalidos(f"os códigos em {tipo} não vão para o MAT: exporte em unidades")
    nome = "amostras" if opcoes.crus else "valores"
    tamanho = trecho.n * len(trecho.colunas) * tipo.itemsize
    (_mat_v5 if tamanho <= LIMITE_DO_MAT_V5 else _mat_v73)(trecho, caminho, opcoes, meta, nome, tipo, blocos)


def _variaveis_pequenas(meta: Mapping) -> list[tuple[str, np.ndarray | str]]:
    """Os metadados como variáveis do MATLAB: os números como matrizes, os textos como ``char`` (os de uma lista,
    uma linha por item, completada com espaços)."""
    saida: list = []
    for chave, valor in meta.items():
        if isinstance(valor, bool):
            saida.append((chave, np.array([[float(valor)]])))
        elif isinstance(valor, (int, float)):
            saida.append((chave, np.array([[float(valor)]])))
        elif isinstance(valor, str):
            saida.append((chave, valor))
        elif valor and all(isinstance(v, (int, float)) for v in valor):
            saida.append((chave, np.asarray(valor, dtype=np.float64).reshape(1, -1)))
        else:
            textos = [v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for v in valor]
            saida.append((chave, textos))
    return saida


def _cabecalho_do_mat(versao: str) -> bytes:
    texto = (f"MATLAB {versao} MAT-file, Platform: GLNXA64, Created on: "
             f"{datetime.now():%a %b %d %H:%M:%S %Y}" + (" HDF5 schema 1.00 ." if versao == "7.3" else ""))
    numero = 0x0200 if versao == "7.3" else 0x0100
    return texto.ljust(116).encode("ascii")[:116] + b"\x00" * 8 + struct.pack("<H", numero) + b"IM"


def _texto_em_char(valor) -> np.ndarray:
    """Um texto (uma linha) ou uma lista de textos (as linhas, completadas) como a matriz de caracteres UTF-16."""
    linhas = [valor] if isinstance(valor, str) else list(valor) or [""]
    largura = max(len(x) for x in linhas)
    return np.array([[ord(c) for c in x.ljust(largura)] for x in linhas], dtype=np.uint16).reshape(len(linhas),
                                                                                                    largura)


def _mat_v5(trecho, caminho, opcoes, meta, nome, tipo, blocos) -> None:
    with open(caminho, "wb") as f:
        f.write(_cabecalho_do_mat("5.0"))
        for chave, valor in _variaveis_pequenas(meta):
            if isinstance(valor, np.ndarray):
                _elemento_v5(f, chave, "double", valor.shape, [np.asarray(valor, np.float64).ravel(order="F")])
            else:
                matriz = _texto_em_char(valor)
                _elemento_v5(f, chave, "char", matriz.shape, [matriz.ravel(order="F")], dado="uint16")
        k = len(trecho.colunas)
        classe = _CLASSE[tipo]

        def colunas():                           # coluna por coluna (o MATLAB guarda por colunas), em blocos
            for j in range(k):
                for a, b in blocos():
                    yield np.ascontiguousarray(trecho.bloco(a, b, crus=opcoes.crus)[:, j], dtype=tipo)

        blocos.passadas = k
        _elemento_v5(f, nome, classe, (trecho.n, k), colunas(), dado=classe, n_bytes=trecho.n * k * tipo.itemsize)


def _elemento_v5(f, nome: str, classe: str, forma, partes, *, dado: str | None = None,
                 n_bytes: int | None = None) -> None:
    """Um ``miMATRIX`` sem compressão: as flags, as dimensões, o nome e a parte real (``partes``: os pedaços, na
    ordem das colunas)."""
    dado = dado or classe
    if n_bytes is None:
        partes = list(partes)
        n_bytes = sum(p.nbytes for p in partes)
    nome_b = nome.encode("ascii")
    pad = lambda n: (8 - n % 8) % 8  # noqa: E731
    sub = (16 + 8 + 4 * len(forma) + pad(4 * len(forma)) + 8 + len(nome_b) + pad(len(nome_b)) + 8 + n_bytes
           + pad(n_bytes))
    f.write(struct.pack("<II", _MI["matrix"], sub))
    f.write(struct.pack("<IIII", _MI["uint32"], 8, _MX[classe], 0))
    f.write(struct.pack("<II", _MI["int32"], 4 * len(forma)) + struct.pack(f"<{len(forma)}i", *forma)
            + b"\x00" * pad(4 * len(forma)))
    f.write(struct.pack("<II", _MI["int8"], len(nome_b)) + nome_b + b"\x00" * pad(len(nome_b)))
    f.write(struct.pack("<II", _MI[dado], n_bytes))
    escritos = 0
    for p in partes:
        f.write(p.tobytes())
        escritos += p.nbytes
    if escritos != n_bytes:
        raise RuntimeError(f"o MAT esperava {n_bytes} bytes em {nome}, e vieram {escritos}")
    f.write(b"\x00" * pad(n_bytes))


def _mat_v73(trecho, caminho, opcoes, meta, nome, tipo, blocos) -> None:
    """O v7.3: um HDF5 com 512 bytes reservados no começo para o cabeçalho do MATLAB; cada variável transposta (o
    MATLAB lê por colunas) e com o atributo ``MATLAB_class``."""
    import h5py

    k = len(trecho.colunas)
    with h5py.File(caminho, "w", userblock_size=512) as f5:
        for chave, valor in _variaveis_pequenas(meta):
            if isinstance(valor, np.ndarray):
                d = f5.create_dataset(chave, data=np.asarray(valor, np.float64).T)
                d.attrs["MATLAB_class"] = np.bytes_("double")
            else:
                d = f5.create_dataset(chave, data=_texto_em_char(valor).T)
                d.attrs["MATLAB_class"] = np.bytes_("char")
                d.attrs["MATLAB_int_decode"] = np.int32(2)
        dados = f5.create_dataset(nome, shape=(k, trecho.n), dtype=tipo, chunks=(1, min(trecho.n, 1 << 18)))
        dados.attrs["MATLAB_class"] = np.bytes_(_CLASSE[tipo])
        for a, b in blocos():
            dados[:, a:b] = trecho.bloco(a, b, crus=opcoes.crus).astype(tipo).T
    with open(caminho, "r+b") as f:
        f.write(_cabecalho_do_mat("7.3"))


__all__ = ["DECIMAIS", "FORMATOS", "LIMITE_DO_MAT_V5", "LINHAS_POR_BLOCO", "SEPARADORES", "ColunaDeDados",
           "DadosInvalidos", "OpcoesDosDados", "TrechoDeDados", "caminho_da_proveniencia", "conferir", "exportar",
           "nome_do_arquivo", "recortar"]
