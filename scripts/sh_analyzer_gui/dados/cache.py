"""A pirâmide no disco: o arquivo ``.shpir`` e o cache que evita refazê-la a cada vez que a captura é aberta.

**O arquivo** (``FORMATO_ARQUIVO`` = 1), little-endian:

* 8 bytes: ``MAGICO`` (``b"SHPIR001"``);
* 4 bytes: o tamanho ``t`` do cabeçalho JSON (``uint32``);
* ``t`` bytes: o cabeçalho JSON em UTF-8 -- o formato, o número de amostras, o tipo (``numpy.dtype.str``), o bloco
  base, o fator e, para cada nível, o bloco, o número de blocos e onde começam os mínimos e os máximos;
* os vetores, cada um começando num múltiplo de 64 bytes.

Ao abrir, os vetores viram ``np.memmap`` só de leitura: reabrir uma captura de horas não carrega a pirâmide na RAM, e
o sistema operacional traz para a memória só as páginas que o gráfico consulta.

**A gravação é atômica:** num arquivo temporário da mesma pasta, com ``fsync``, renomeado no fim (``os.replace``).
Um arquivo pela metade nunca é lido; um arquivo inválido (cortado, de outro formato, de outro tamanho) é apagado e a
pirâmide é refeita.

**O cache** (:class:`CacheDePiramides`) guarda uma pirâmide por canal, com o nome tirado de uma chave da captura
(:func:`chave_do_arquivo`), e apaga as menos usadas quando passa do limite de tamanho.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Callable, Hashable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from .piramide import BLOCO_BASE, FATOR, Nivel, Piramide, construir

MAGICO = b"SHPIR001"
FORMATO_ARQUIVO = 1
ALINHAMENTO = 64
EXTENSAO = ".shpir"
LIMITE_PADRAO_BYTES = 4 * 1024**3


class PiramideInvalida(ValueError):
    """O arquivo não é uma pirâmide deste formato, ou está corrompido."""


def _alinhar(posicao: int) -> int:
    return -(-posicao // ALINHAMENTO) * ALINHAMENTO


def gravar(piramide: Piramide, caminho: Path) -> None:
    """Grava ``piramide`` em ``caminho`` de forma atômica (temporário + ``fsync`` + ``os.replace``)."""
    caminho = Path(caminho)
    dtype = np.dtype(piramide.dtype)
    niveis, posicao = [], 0
    for nivel in piramide.niveis:
        tamanho = len(nivel) * dtype.itemsize
        inicio_min = posicao
        inicio_max = _alinhar(inicio_min + tamanho)
        posicao = _alinhar(inicio_max + tamanho)
        niveis.append({"bloco": nivel.bloco, "n": len(nivel), "min": inicio_min, "max": inicio_max})
    cabecalho = json.dumps({"formato": FORMATO_ARQUIVO, "n_amostras": piramide.n_amostras, "dtype": dtype.str,
                            "bloco_base": BLOCO_BASE, "fator": FATOR, "niveis": niveis}).encode("utf-8")
    inicio_dados = _alinhar(len(MAGICO) + 4 + len(cabecalho))
    caminho.parent.mkdir(parents=True, exist_ok=True)
    descritor, temporario = tempfile.mkstemp(prefix=caminho.name + ".", suffix=".tmp", dir=caminho.parent)
    try:
        with os.fdopen(descritor, "wb") as f:
            f.write(MAGICO + struct.pack("<I", len(cabecalho)) + cabecalho)
            for nivel, info in zip(piramide.niveis, niveis):
                for vetor, chave in ((nivel.minimos, "min"), (nivel.maximos, "max")):
                    f.seek(inicio_dados + info[chave])
                    f.write(np.ascontiguousarray(vetor, dtype=dtype).tobytes())
            f.truncate(inicio_dados + posicao)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporario, caminho)
    except BaseException:
        Path(temporario).unlink(missing_ok=True)
        raise


def abrir(caminho: Path) -> Piramide:
    """Abre uma pirâmide gravada por :func:`gravar`, com os vetores em ``np.memmap`` só de leitura.

    Levanta :class:`PiramideInvalida` se o arquivo não for deste formato ou estiver incompleto."""
    caminho = Path(caminho)
    try:
        tamanho_arquivo = caminho.stat().st_size
        with open(caminho, "rb") as f:
            inicio = f.read(len(MAGICO) + 4)
            if len(inicio) < len(MAGICO) + 4 or inicio[:len(MAGICO)] != MAGICO:
                raise PiramideInvalida(f"{caminho.name}: não é uma pirâmide do SH-Analyzer")
            (tamanho_cabecalho,) = struct.unpack("<I", inicio[len(MAGICO):])
            if tamanho_cabecalho > 1 << 20:
                raise PiramideInvalida(f"{caminho.name}: cabeçalho de {tamanho_cabecalho} bytes")
            info = json.loads(f.read(tamanho_cabecalho).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise PiramideInvalida(f"{caminho.name}: {e}") from e
    if info.get("formato") != FORMATO_ARQUIVO or info.get("bloco_base") != BLOCO_BASE or info.get("fator") != FATOR:
        raise PiramideInvalida(f"{caminho.name}: formato, bloco ou fator diferentes dos deste programa")
    try:
        dtype = np.dtype(info["dtype"])
        inicio_dados = _alinhar(len(MAGICO) + 4 + tamanho_cabecalho)
        niveis = []
        for nv in info["niveis"]:
            fim = inicio_dados + max(nv["min"], nv["max"]) + nv["n"] * dtype.itemsize
            if fim > tamanho_arquivo:
                raise PiramideInvalida(f"{caminho.name}: o arquivo acaba antes do nível de bloco {nv['bloco']}")
            vetores = [np.memmap(caminho, dtype=dtype, mode="r", offset=inicio_dados + nv[k], shape=(nv["n"],))
                       for k in ("min", "max")]
            niveis.append(Nivel(int(nv["bloco"]), *vetores))
        return Piramide(int(info["n_amostras"]), dtype, tuple(niveis))
    except (KeyError, TypeError, ValueError) as e:
        if isinstance(e, PiramideInvalida):
            raise
        raise PiramideInvalida(f"{caminho.name}: cabeçalho inválido ({e})") from e


def chave_do_arquivo(caminho: Path, crc32_amostras: int | None = None) -> str:
    """A chave de cache de uma captura.

    Com o CRC das amostras (cabeçalho v9), a chave é ele e o tamanho do arquivo: a mesma captura copiada para outra
    pasta reaproveita a pirâmide. Sem ele (v1 a v8, CSV), um resumo do caminho absoluto, do tamanho e da data de
    modificação: mudou o arquivo, muda a chave."""
    estado = Path(caminho).stat()
    if crc32_amostras is not None:
        return f"crc{crc32_amostras & 0xFFFFFFFF:08x}-{estado.st_size}"
    texto = f"{Path(caminho).resolve()}|{estado.st_size}|{estado.st_mtime_ns}"
    return "arq" + hashlib.sha256(texto.encode("utf-8")).hexdigest()[:24]


VARIAVEL_DA_PASTA = "SH_ANALYZER_CACHE"


def pasta_padrao() -> Path:
    """A pasta de cache do sistema (``platformdirs``): ~/.cache/sh-analyzer/piramides no Linux,
    %LOCALAPPDATA%\\sh-analyzer\\Cache\\piramides no Windows. A variável ``SH_ANALYZER_CACHE`` a troca (os testes
    a apontam para uma pasta temporária)."""
    pasta = os.environ.get(VARIAVEL_DA_PASTA)
    if pasta:
        return Path(pasta) / "piramides"
    from platformdirs import user_cache_dir
    return Path(user_cache_dir("sh-analyzer", appauthor=False)) / "piramides"


class EmConstrucao:
    """As entradas de um cache que alguma tarefa constrói agora (noutra thread): nem o limite de tamanho nem o
    "limpar" as apagam."""

    def __init__(self):
        self._trava = threading.Lock()
        self._contagem: Counter = Counter()

    @contextmanager
    def marcar(self, entradas: Iterable[Hashable]) -> Iterator[None]:
        """As ``entradas`` ficam em construção enquanto durar o ``with``."""
        entradas = list(entradas)
        with self._trava:
            self._contagem.update(entradas)
        try:
            yield
        finally:
            with self._trava:
                self._contagem.subtract(entradas)
                self._contagem = +self._contagem          # sem as que zeraram

    def atuais(self) -> set:
        with self._trava:
            return set(self._contagem)


class CacheDePiramides:
    """As pirâmides de cada canal de cada captura, numa pasta, com limite de tamanho (apaga as menos usadas).

    O que está sendo construído e gravado agora (por uma tarefa, noutra thread) nunca é apagado: nem pelo limite,
    nem pelo "limpar" das configurações. O que está aberto, quem chama diz (``manter``)."""

    def __init__(self, pasta: Path | None = None, limite_bytes: int = LIMITE_PADRAO_BYTES):
        self.pasta = Path(pasta) if pasta is not None else pasta_padrao()
        self.limite_bytes = limite_bytes
        self.em_construcao = EmConstrucao()

    def caminho(self, chave: str, canal: int) -> Path:
        segura = re.sub(r"[^A-Za-z0-9._-]", "_", chave)
        return self.pasta / f"{segura}-c{canal}-f{FORMATO_ARQUIVO}-{BLOCO_BASE}x{FATOR}{EXTENSAO}"

    def abrir(self, chave: str, canal: int, n_amostras: int, dtype: np.dtype) -> Piramide | None:
        """A pirâmide do cache, se existir e bater com o sinal (número de amostras e tipo); senão, ``None``. Um
        arquivo inválido é apagado."""
        caminho = self.caminho(chave, canal)
        if not caminho.exists():
            return None
        try:
            piramide = abrir(caminho)
        except PiramideInvalida:
            _apagar(caminho)
            return None
        if piramide.n_amostras != n_amostras or piramide.dtype != np.dtype(dtype):
            del piramide           # solta o memmap antes de apagar (no Windows, um arquivo mapeado não se apaga)
            _apagar(caminho)
            return None
        try:
            os.utime(caminho)      # a data de uso: o limite de tamanho apaga as menos usadas
        except OSError:
            pass
        return piramide

    def obter(self, chave: str, amostras: np.ndarray, n_canais: int = 1, *,
              progresso: Callable[[float], None] | None = None,
              cancelado: Callable[[], bool] | None = None) -> list[Piramide]:
        """As pirâmides de todos os canais: do cache, se estiverem todas lá; senão, construídas numa passada,
        gravadas e devolvidas (já abertas do disco, em ``np.memmap``)."""
        n = len(amostras) // n_canais
        caminhos = [self.caminho(chave, c) for c in range(n_canais)]
        with self.em_construcao.marcar(caminhos):
            prontas = [self.abrir(chave, c, n, amostras.dtype) for c in range(n_canais)]
            if all(p is not None for p in prontas):
                if progresso is not None:
                    progresso(1.0)
                return prontas
            construidas = construir(amostras, n_canais, progresso=progresso, cancelado=cancelado)
            for piramide, caminho in zip(construidas, caminhos, strict=True):
                gravar(piramide, caminho)
            self.aparar(manter=set(caminhos))
            return [abrir(caminho) for caminho in caminhos]

    def _intocaveis(self, manter) -> set[Path]:
        return set(manter) | self.em_construcao.atuais()

    def _arquivos(self) -> list[tuple[float, int, Path]]:
        """Cada pirâmide da pasta: a data do último uso, o tamanho e o caminho."""
        if not self.pasta.is_dir():
            return []
        arquivos = []
        for caminho in self.pasta.glob(f"*{EXTENSAO}"):
            try:
                estado = caminho.stat()
            except OSError:
                continue
            arquivos.append((estado.st_mtime, estado.st_size, caminho))
        return arquivos

    @property
    def tamanho_bytes(self) -> int:
        return sum(tamanho for _, tamanho, _ in self._arquivos())

    def limpar(self, manter: set[Path] = frozenset()) -> int:
        """Apaga todas as pirâmides (menos as de ``manter``, abertas, e as em construção); devolve os bytes
        liberados."""
        intocaveis = self._intocaveis(manter)
        liberados = 0
        for _, tamanho, caminho in self._arquivos():
            if caminho not in intocaveis and _apagar(caminho):
                liberados += tamanho
        return liberados

    def aparar(self, manter: set[Path] = frozenset()) -> None:
        """Apaga as pirâmides menos usadas até o total caber no limite (nunca as de ``manter``), e os temporários
        com mais de uma hora (sobras de uma gravação interrompida)."""
        if not self.pasta.is_dir():
            return
        agora = time.time()
        for temporario in self.pasta.glob(f"*{EXTENSAO}.*.tmp"):
            try:
                if agora - temporario.stat().st_mtime > 3600:
                    temporario.unlink()
            except OSError:
                pass
        arquivos = self._arquivos()
        intocaveis = self._intocaveis(manter)
        total = sum(tamanho for _, tamanho, _ in arquivos)
        for _, tamanho, caminho in sorted(arquivos):
            if total <= self.limite_bytes:
                break
            if caminho in intocaveis:
                continue
            if _apagar(caminho):
                total -= tamanho


def _apagar(caminho: Path) -> bool:
    """Apaga sem levantar erro: no Windows, uma pirâmide aberta (mapeada) por outra vista não se apaga, e fica para
    a próxima vez."""
    try:
        caminho.unlink(missing_ok=True)
        return True
    except OSError:
        return False
