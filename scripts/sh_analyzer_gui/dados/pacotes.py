"""Os pacotes ``.zpaq.tar`` do ``compactar`` (F7.10, PD-04; docs/gui-progress.md, 4h), sem Qt.

Abrir um pacote é extrair as capturas dele para o cache (``CacheDePacotes``: uma pasta por pacote, com limite de
tamanho, as menos usadas apagadas primeiro, nunca as abertas) e abri-las como as outras. A extração é a do motor
(``supraharmonicos.compactacao.Pacote.restaurar``): cada peça conferida pelo SHA-256 do manifesto, e cada arquivo
pelo SHA-256 do original antes de ganhar o nome; a GUI ainda confere o CRC das amostras de cada captura ao abri-la.

Uma pasta extraída inteira ganha a marca :data:`MARCA_COMPLETA`; abrir de novo o mesmo pacote (o mesmo caminho, o
mesmo tamanho e a mesma data) usa a pasta, sem extrair de novo, quando os arquivos ainda têm os tamanhos do
manifesto. Uma extração interrompida não ganha a marca e é refeita.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path

import supraharmonicos.api as api

cp = api.compactacao                                   # os pacotes do compactar (o manifesto, a extração conferida)

LIMITE_PADRAO_BYTES = 20 * 1024**3
MARCA_COMPLETA = ".completo"
EXTENSOES_DE_CAPTURA = tuple(api.TIPOS_DE_ARQUIVO)
"""As extensões das capturas que a GUI abre; os outros arquivos do pacote (os .txt, os .json) ficam de fora."""


def eh_pacote(caminho: Path) -> bool:
    """Se o caminho tem cara de pacote (``*.zpaq.tar`` ou ``*.tar``); quem confere é o manifesto."""
    nome = Path(caminho).name.lower()
    return nome.endswith(".tar")


def pasta_padrao() -> Path:
    from platformdirs import user_cache_dir

    return Path(user_cache_dir("sh-analyzer", appauthor=False)) / "pacotes"


class _Observador(cp.Observador):
    """O progresso da extração (os bytes das peças prontas) e o cancelamento (no ``tique``, que vem da thread que
    espera as peças: levantar ali cancela as outras e mata os descompressores)."""

    def __init__(self, progresso, cancelado):
        self._progresso, self._cancelado = progresso, cancelado
        self._total, self._feito = 1, 0

    def fase(self, nome, total_bytes, total_itens, processos):
        self._total = max(total_bytes, 1)

    def fim(self, chave, tamanho, segundos):
        self._feito += tamanho

    def tique(self):
        if self._cancelado is not None and self._cancelado():
            raise api.Cancelado()
        if self._progresso is not None:
            self._progresso(min(self._feito / self._total, 1.0))


class CacheDePacotes:
    """As capturas extraídas de cada pacote, uma pasta por pacote, com o limite de tamanho."""

    def __init__(self, pasta: Path | None = None, limite_bytes: int = LIMITE_PADRAO_BYTES):
        self.pasta = Path(pasta) if pasta is not None else pasta_padrao()
        self.limite_bytes = limite_bytes
        self.extraindo: set[Path] = set()

    def pasta_do_pacote(self, caminho: Path) -> Path:
        """A pasta das capturas de um pacote: o nome dele e um resumo do caminho, do tamanho e da data (um pacote
        refeito com o mesmo nome tem outra pasta)."""
        caminho = Path(caminho).resolve()
        estado = caminho.stat()
        resumo = hashlib.sha256(f"{caminho}\0{estado.st_size}\0{estado.st_mtime_ns}".encode()).hexdigest()[:16]
        nome = re.sub(r"[^A-Za-z0-9._-]", "_", caminho.name.removesuffix(".tar").removesuffix(".zpaq"))[:60]
        return self.pasta / f"{nome}-{resumo}"

    def extrair(self, caminho: Path, *, progresso: Callable[[float], None] | None = None,
                cancelado: Callable[[], bool] | None = None, processos: int | None = None) -> list[Path]:
        """As capturas do pacote, extraídas (ou já no cache), em ordem do manifesto. Levanta ``api.ErroSHAN`` se o
        pacote não se lê, não tem capturas ou alguma não confere."""
        pacote = cp.Pacote(Path(caminho))                # um pacote que não se lê levanta ErroSHAN
        indices = [i for i, e in enumerate(pacote.entradas) if e.nome.lower().endswith(EXTENSOES_DE_CAPTURA)]
        if not indices:
            raise api.ErroSHAN(f"o pacote {Path(caminho).name} não tem capturas ({', '.join(EXTENSOES_DE_CAPTURA)})")
        destino = self.pasta_do_pacote(caminho)
        alvos = [destino / pacote.entradas[i].nome for i in indices]
        if self._completa(destino, [(alvo, pacote.entradas[i].tamanho) for alvo, i in zip(alvos, indices)]):
            os.utime(destino / MARCA_COMPLETA)
            if progresso is not None:
                progresso(1.0)
            return alvos
        (destino / MARCA_COMPLETA).unlink(missing_ok=True)
        self.extraindo.add(destino)
        try:
            relatorio = pacote.restaurar(indices, destino, processos or max(1, (os.cpu_count() or 2) // 2),
                                         _Observador(progresso, cancelado))
        except KeyboardInterrupt:
            raise api.Cancelado() from None
        finally:
            self.extraindo.discard(destino)
        if relatorio.falhas:
            nome, motivo = relatorio.falhas[0]
            raise api.ErroSHAN(f"{nome}: {motivo}" + (f" (e mais {len(relatorio.falhas) - 1})"
                                                       if len(relatorio.falhas) > 1 else ""))
        diferentes = [nome for nome, motivo in relatorio.pulados if "DIFERENTE" in motivo]
        if diferentes:
            raise api.ErroSHAN(f"{diferentes[0]} já estava no cache e é diferente do pacote: limpe o cache dos "
                               "pacotes nas Configurações")
        (destino / MARCA_COMPLETA).touch()
        self.aparar(manter=set(alvos))
        return alvos

    @staticmethod
    def _completa(destino: Path, esperados: list[tuple[Path, int]]) -> bool:
        if not (destino / MARCA_COMPLETA).is_file():
            return False
        try:
            return all(alvo.stat().st_size == tamanho for alvo, tamanho in esperados)
        except OSError:
            return False

    def _pastas(self) -> list[tuple[float, int, Path]]:
        """Cada pasta de pacote: a data do último uso (a da marca), o tamanho e o caminho."""
        if not self.pasta.is_dir():
            return []
        pastas = []
        for pasta in self.pasta.iterdir():
            if not pasta.is_dir():
                continue
            tamanho = sum(f.stat().st_size for f in pasta.rglob("*") if f.is_file())
            marca = pasta / MARCA_COMPLETA
            uso = marca.stat().st_mtime if marca.exists() else pasta.stat().st_mtime
            pastas.append((uso, tamanho, pasta))
        return pastas

    @property
    def tamanho_bytes(self) -> int:
        return sum(tamanho for _, tamanho, _ in self._pastas())

    def pasta_de(self, caminho: Path) -> Path | None:
        """A pasta de pacote que contém ``caminho`` (uma captura extraída), ou ``None`` se ele não é do cache."""
        try:
            relativo = Path(caminho).resolve().relative_to(self.pasta.resolve())
        except (ValueError, OSError):
            return None
        return self.pasta / relativo.parts[0] if relativo.parts else None

    def _intocaveis(self, manter) -> set[Path]:
        """As pastas que não se apagam: as das capturas (ou pastas) de ``manter`` e as sendo extraídas."""
        pastas = {self.pasta_de(p) for p in manter}
        return {p for p in pastas if p is not None} | set(self.extraindo)

    def limpar(self, manter: set[Path] = frozenset()) -> int:
        """Apaga as pastas extraídas (menos as das capturas de ``manter``, as abertas, e as sendo extraídas);
        devolve os bytes liberados."""
        intocaveis = self._intocaveis(manter)
        liberados = 0
        for _, tamanho, pasta in self._pastas():
            if pasta not in intocaveis and _apagar(pasta):
                liberados += tamanho
        return liberados

    def aparar(self, manter: set[Path] = frozenset()) -> None:
        """Apaga as menos usadas até caber no limite (nunca as de ``manter``), e as incompletas com mais de um dia
        (uma extração interrompida)."""
        agora = time.time()
        pastas = self._pastas()
        intocaveis = self._intocaveis(manter)
        for uso, _tamanho, pasta in pastas:
            if not (pasta / MARCA_COMPLETA).exists() and pasta not in intocaveis and agora - uso > 86400:
                _apagar(pasta)
        pastas = self._pastas()
        total = sum(tamanho for _, tamanho, _ in pastas)
        for _, tamanho, pasta in sorted(pastas):
            if total <= self.limite_bytes:
                break
            if pasta in intocaveis:
                continue
            if _apagar(pasta):
                total -= tamanho


def _apagar(pasta: Path) -> bool:
    try:
        shutil.rmtree(pasta)
        return True
    except OSError:
        return False
