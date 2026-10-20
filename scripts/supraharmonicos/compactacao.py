"""Arquivamento SEM PERDAS das capturas num pacote ``.zpaq.tar``: formato, transformação e compressores.

Por que este formato
--------------------
Um ``.bin`` guarda amostras ``uint16`` cruas (2 bytes cada). Medido nas capturas do projeto (out/2026,
bancada a 100 kS/s): o ruído do ADC limita qualquer compressor sem perdas a ~1,1-2,2 bits/amostra, e o que
chega mais perto disso é o **zpaq -m5** (modelagem de contexto): ~10 % do original, contra ~14 % do 7-Zip/xz
e ~15 % do FLAC. Duas escolhas vieram das mesmas medidas:

* **Desentrelaçar os canais** (todas as amostras do canal 0, depois as do 1...) rende ~6 % numa captura de
  8 canais: o modelo vê um sinal contínuo de cada vez em vez de saltar de canal a cada amostra.
* **Cada arquivo na sua peça.** Juntar capturas pequenas parecidas numa peça "sólida" saiu 5 % MAIOR (o -m5
  escolhe o modelo por bloco e se confunde quando o conteúdo muda no meio); só um arquivo grande é cortado
  em várias peças, que também são comprimidas em paralelo.

Testado e descartado: um preditor linear (LPC) antes do zpaq ganha 3-9 % em algumas capturas e perde até
12 % em outras (a de 10 min, por exemplo), e exigiria um decodificador próprio.

O pacote (versão 1 do formato)
------------------------------
Um ``tar`` POSIX (PAX), legível por qualquer ``tar``, com:

* ``LEIA-ME.txt``          como recuperar os dados à mão, sem este programa;
* ``manifesto.json``       os arquivos (caminho, tamanho, data, permissões, SHA-256), a transformação de cada
                           um e onde estão os seus bytes;
* ``pecas/000001.zpaq``... as peças: cada uma é um arquivo zpaq (ou ``.xz``) INDEPENDENTE com um único
                           arquivo dentro, um trecho do FLUXO de um arquivo original.

O FLUXO de um arquivo é o próprio arquivo, exceto numa captura SHAN com 2 ou mais canais, onde as amostras
saem desentrelaçadas (:class:`Desentrelacamento`). Uma peça que guarda um arquivo inteiro sem transformação
leva o nome dele, então o ``zpaq x`` comum já devolve o original.

Segurança dos dados: o SHA-256 de cada original é calculado ANTES de comprimir, e (por padrão) o pacote
gravado é relido do disco, descomprimido por inteiro e conferido contra esses hashes antes de ganhar o nome
final -- até lá ele é ``*.parcial``. Uma interrupção ou falha não deixa nada pela metade.

Depende de: ``cabecalho``, ``constantes``, ``erros``. Quem usa: ``cli_compactar``.
"""

from __future__ import annotations

import errno
import hashlib
import json
import lzma
import os
import shutil
import subprocess
import tarfile
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

import numpy as np

from .cabecalho import CABECALHO_TAMANHO_TOTAL, ler_cabecalho
from .constantes import ADS8688_MAX_CANAIS
from .erros import ErroSHAN, ErroUso

FORMATO = "sh-analyzer/capturas-compactadas"
VERSAO_FORMATO = 1
MEMBRO_LEIAME = "LEIA-ME.txt"
MEMBRO_MANIFESTO = "manifesto.json"
PASTA_PECAS = "pecas"
SUFIXO_PARCIAL = ".parcial"
PREFIXO_TEMPORARIO = ".sh-compactando-"

# Arquivos maiores que isto viram várias peças (comprimidas em paralelo). 64 MiB é o bloco do próprio -m5;
# com 16 MiB a captura de 10 min (122 MB) saiu 3,3 % maior, em troca de 1/3 da memória por processo.
TAMANHO_PECA_MAX = 64 * 2**20
_BLOCO_LEITURA = 4 * 2**20


@dataclass(frozen=True)
class Metodo:
    """Um jeito de comprimir as peças. A memória e a velocidade são estimativas medidas (zpaq 7.15, i7-7700HQ),
    usadas só para escolher quantos processos cabem na RAM e para a estimativa de tempo."""

    nome: str
    codec: str                # "zpaq" | "xz"
    nivel: str                # zpaq: argumento de -method; xz: preset ("9e")
    descricao: str
    memoria_base: int         # bytes por processo, fixo
    memoria_por_byte: float   # bytes de memória a mais por byte da peça...
    memoria_teto: int         # ...até este máximo
    taxa_estimada: float      # bytes/s de UM processo, antes de medir de verdade

    @property
    def extensao(self) -> str:
        return "." + self.codec

    def memoria_por_processo(self, tamanho_peca: int) -> int:
        return int(min(self.memoria_base + self.memoria_por_byte * tamanho_peca, self.memoria_teto))


METODOS = {
    # medido: 125 MB numa peça de 2 MB, 470 MB numa de 17 MB, ~740 MB numa de 64 MiB; 0,07 MB/s por processo
    # com os 8 núcleos lógicos ocupados (as capturas até out/2026, 407 MB: 15 min para comprimir e outros 15 para verificar)
    "max": Metodo("max", "zpaq", "5", "zpaq -m5 (modelagem de contexto, a mais forte)",
                  memoria_base=110 * 10**6, memoria_por_byte=22.0, memoria_teto=800 * 10**6, taxa_estimada=0.10e6),
    "rapido": Metodo("rapido", "xz", "9e", "xz -9e (LZMA2; ~40 % maior, ~20x mais rápido)",
                     memoria_base=700 * 10**6, memoria_por_byte=0.0, memoria_teto=700 * 10**6, taxa_estimada=2.0e6),
}
METODO_PADRAO = "max"


# ---------------------------------------------------------------------------
# Transformação reversível: desentrelaçar os canais de uma captura SHAN
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Desentrelacamento:
    """Fluxo = ``prefixo`` bytes como estão (o cabeçalho SHAN) + as ``quadros`` amostras uint16 do canal 0,
    depois as do canal 1, ..., do canal ``canais``-1 + o resto do arquivo (cauda) como está.

    Vale para QUALQUER arquivo (não depende de o cabeçalho estar certo): é só uma permutação dos bytes, e a
    volta é exata. Por isso um cabeçalho com CRC errado ainda pode ser desentrelaçado."""

    prefixo: int
    canais: int
    quadros: int

    @property
    def fim_amostras(self) -> int:
        return self.prefixo + 2 * self.canais * self.quadros

    def para_json(self) -> dict:
        return {"tipo": "desentrelacar-uint16", "prefixo": self.prefixo, "canais": self.canais,
                "quadros": self.quadros}

    @classmethod
    def de_json(cls, d: dict | None, tamanho: int) -> Desentrelacamento | None:
        if d is None:
            return None
        if d.get("tipo") != "desentrelacar-uint16":
            raise ErroSHAN(f"transformação desconhecida no manifesto: {d.get('tipo')!r} -- o pacote foi feito por "
                           "uma versão mais nova deste programa.")
        t = cls(int(d["prefixo"]), int(d["canais"]), int(d["quadros"]))
        if t.prefixo < 0 or t.canais < 2 or t.quadros < 1 or t.fim_amostras > tamanho:
            raise ErroSHAN(f"transformação inválida no manifesto: {d}")
        return t


def escolher_transformacao(caminho: Path, tamanho: int) -> tuple[Desentrelacamento | None, dict | None]:
    """(transformação, resumo da captura) de um arquivo. Sem cabeçalho SHAN: (None, None)."""
    if tamanho < CABECALHO_TAMANHO_TOTAL:
        return None, None
    try:
        cab = ler_cabecalho(caminho)
    except Exception:   # noqa: BLE001 -- um cabeçalho estranho nunca pode impedir o arquivamento; sem ele, o arquivo vai como está
        return None, None
    if cab is None:
        return None, None
    n = cab.num_canais if 1 <= cab.num_canais <= ADS8688_MAX_CANAIS else 0
    resumo = {
        "versao_cabecalho": cab.versao_cabecalho,
        "frequencia_hz": cab.frequencia_hz,
        "canais": list(cab.lista_canais[:n]),
        "data_utc": cab.timestamp_iso_utc,
        "titulo": cab.titulo,
        "crc_ok": cab.crc32_valido,
    }
    if cab.bytes_por_amostra != 2 or n < 2:
        return None, resumo
    quadros = (tamanho - CABECALHO_TAMANHO_TOTAL) // (2 * n)
    if quadros < 1:
        return None, resumo
    return Desentrelacamento(CABECALHO_TAMANHO_TOTAL, n, quadros), resumo


def ler_fluxo(caminho: Path, transf: Desentrelacamento | None, ini: int, fim: int) -> bytes:
    """Bytes ``[ini, fim)`` do fluxo de ``caminho`` (sem montar o fluxo inteiro: lê por ``memmap``)."""
    if transf is None:
        with open(caminho, "rb") as f:
            f.seek(ini)
            dados = f.read(fim - ini)
        if len(dados) != fim - ini:
            raise ErroSHAN(f"'{caminho}' encolheu durante a compactação (esperava {fim} bytes).")
        return dados
    bruto = np.memmap(caminho, dtype=np.uint8, mode="r")
    if bruto.size < transf.fim_amostras or bruto.size < fim:
        raise ErroSHAN(f"'{caminho}' encolheu durante a compactação.")
    p, c, n = transf.prefixo, transf.canais, transf.quadros
    amostras = bruto[p:transf.fim_amostras].view("<u2").reshape(n, c)
    partes = []
    if ini < p:
        partes.append(bruto[ini:min(fim, p)].tobytes())
    for canal in range(c):
        a = p + 2 * n * canal                       # início do canal no fluxo
        lo, hi = max(ini, a), min(fim, a + 2 * n)
        if lo < hi:
            i0, i1 = (lo - a) // 2, (hi - a + 1) // 2
            trecho = amostras[i0:i1, canal].astype("<u2", copy=True).tobytes()
            partes.append(trecho[lo - a - 2 * i0:hi - a - 2 * i0])
    lo = max(ini, transf.fim_amostras)
    if lo < fim:
        partes.append(bruto[lo:fim].tobytes())
    return b"".join(partes)


def desfazer_transformacao(fluxo: Path, transf: Desentrelacamento, destino: Path, tamanho: int) -> None:
    """Grava em ``destino`` o arquivo original a partir do fluxo (a volta de :func:`ler_fluxo`)."""
    p, c, n = transf.prefixo, transf.canais, transf.quadros
    s = np.memmap(fluxo, dtype=np.uint8, mode="r")
    if s.size != tamanho:
        raise ErroSHAN(f"fluxo com {s.size} bytes, esperava {tamanho}.")
    saida = np.memmap(destino, dtype=np.uint8, mode="w+", shape=(tamanho,))
    saida[:p] = s[:p]
    intercaladas = saida[p:transf.fim_amostras].view("<u2").reshape(n, c)
    por_canal = s[p:transf.fim_amostras].view("<u2").reshape(c, n)
    for canal in range(c):
        intercaladas[:, canal] = por_canal[canal]
    saida[transf.fim_amostras:] = s[transf.fim_amostras:]
    saida.flush()
    del saida, s


# ---------------------------------------------------------------------------
# Entradas: o que vai para o pacote
# ---------------------------------------------------------------------------
@dataclass
class Parte:
    """Um trecho ``[ini, fim)`` do fluxo de uma entrada, guardado numa peça própria."""

    membro: str           # "pecas/000001.zpaq"
    nome_interno: str     # nome do arquivo DENTRO da peça
    ini: int
    fim: int
    sha256: str = ""
    bytes_comprimidos: int = 0
    sha256_comprimido: str = ""

    @property
    def tamanho(self) -> int:
        return self.fim - self.ini


@dataclass
class Entrada:
    origem: Path | None   # caminho no disco (None ao ler de um pacote)
    nome: str             # caminho DENTRO do pacote (POSIX, relativo)
    tamanho: int
    mtime_ns: int
    modo: int
    sha256: str = ""
    transformacao: Desentrelacamento | None = None
    captura: dict | None = None
    partes: list[Parte] = field(default_factory=list)

    @property
    def bytes_comprimidos(self) -> int:
        return sum(p.bytes_comprimidos for p in self.partes)

    def para_json(self) -> dict:
        return {
            "caminho": self.nome, "tamanho": self.tamanho, "sha256": self.sha256,
            "mtime_ns": self.mtime_ns, "modo": self.modo,
            "transformacao": self.transformacao.para_json() if self.transformacao else None,
            "captura": self.captura,
            "partes": [{"membro": p.membro, "nome_interno": p.nome_interno, "ini": p.ini, "fim": p.fim,
                        "sha256": p.sha256, "bytes_comprimidos": p.bytes_comprimidos,
                        "sha256_comprimido": p.sha256_comprimido} for p in self.partes],
        }


def _nome_seguro(nome: str) -> str:
    """Nome para passar ao zpaq na linha de comando: ele trata '*' e '?' como curingas e um '-' no começo
    como opção. O manifesto guarda o nome verdadeiro."""
    limpo = "".join("_" if ch in "*?\\" or ord(ch) < 32 else ch for ch in nome)
    return "_" + limpo if limpo.startswith("-") else limpo


def descobrir_entradas(caminhos: Iterable[Path], excluir: Iterable[str] = (),
                       ignorar: Iterable[Path] = ()) -> tuple[list[Entrada], list[str]]:
    """Todos os arquivos regulares sob ``caminhos`` (pastas recursivamente). O nome no pacote é relativo à
    pasta MÃE de cada caminho dado -- ``compactar $DADOS/lab`` guarda ``lab/...``, como o ``tar``.
    Devolve (entradas em ordem, avisos)."""
    excluir = list(excluir)
    ignorar = {p.resolve() for p in ignorar}
    entradas: dict[str, Entrada] = {}
    avisos: list[str] = []

    def considerar(arquivo: Path, nome: str) -> None:
        base = PurePosixPath(nome).name
        if base.startswith(PREFIXO_TEMPORARIO) or base.endswith(SUFIXO_PARCIAL):
            return
        if any(fnmatch(nome, pad) or fnmatch(base, pad) for pad in excluir):
            return
        if arquivo.is_symlink():
            avisos.append(f"'{arquivo}' é um link simbólico -- não foi incluído.")
            return
        st = arquivo.stat()
        if not arquivo.is_file():
            avisos.append(f"'{arquivo}' não é um arquivo comum -- não foi incluído.")
            return
        if arquivo.resolve() in ignorar:
            return
        try:
            nome.encode("utf-8")
        except UnicodeEncodeError:
            avisos.append(f"'{arquivo}' tem bytes inválidos no nome -- não foi incluído (renomeie-o).")
            return
        if nome in entradas:
            raise ErroUso(f"dois arquivos ficariam com o mesmo nome no pacote: '{nome}' "
                          f"('{entradas[nome].origem}' e '{arquivo}'). Compacte as pastas separadamente.")
        entradas[nome] = Entrada(arquivo, nome, st.st_size, st.st_mtime_ns, st.st_mode & 0o7777)

    for caminho in caminhos:
        caminho = Path(caminho)
        if not caminho.exists():
            raise ErroUso(f"'{caminho}' não existe.")
        absoluto = caminho.resolve()
        if absoluto.is_dir():
            raiz_nome = absoluto.name or "raiz"
            for pasta, subpastas, arquivos in os.walk(absoluto):
                subpastas[:] = sorted(d for d in subpastas if not d.startswith(PREFIXO_TEMPORARIO))
                rel = Path(pasta).relative_to(absoluto)
                for a in sorted(arquivos):
                    considerar(Path(pasta) / a, str(PurePosixPath(raiz_nome, *rel.parts, a)))
        else:
            considerar(absoluto, absoluto.name)
    return list(entradas.values()), avisos


def sha256_arquivo(caminho: Path, ao_ler: Callable[[int], None] | None = None) -> str:
    h = hashlib.sha256()
    buf = bytearray(_BLOCO_LEITURA)
    vista = memoryview(buf)
    with open(caminho, "rb", buffering=0) as f:
        while n := f.readinto(buf):
            h.update(vista[:n])
            if ao_ler:
                ao_ler(n)
    return h.hexdigest()


def cortar_em_partes(entrada: Entrada, primeiro_numero: int, metodo: Metodo,
                     tamanho_max: int = TAMANHO_PECA_MAX) -> list[Parte]:
    """Peças de tamanhos iguais (pares, para não partir uma amostra) de no máximo ``tamanho_max``."""
    if entrada.tamanho == 0:
        return []
    n = -(-entrada.tamanho // tamanho_max)
    passo = -(-entrada.tamanho // n)
    passo += passo % 2
    base = entrada.nome + (".desentrelacado" if entrada.transformacao else "")
    partes = []
    for k in range(n):
        ini, fim = k * passo, min((k + 1) * passo, entrada.tamanho)
        if ini >= fim:
            break
        nome = base if n == 1 else f"{base}.parte-{k + 1:03d}-de-{n:03d}"
        partes.append(Parte(f"{PASTA_PECAS}/{primeiro_numero + k:06d}{metodo.extensao}", _nome_seguro(nome), ini, fim))
    return partes


# ---------------------------------------------------------------------------
# Recursos da máquina
# ---------------------------------------------------------------------------
def memoria_disponivel() -> int:
    """MemAvailable do Linux (o que dá para usar sem empurrar o resto do sistema para o swap)."""
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for linha in f:
                if linha.startswith("MemAvailable:"):
                    return int(linha.split()[1]) * 1024
    except OSError:
        pass
    try:
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        return 4 * 10**9


def planejar_processos(metodo: Metodo, maior_peca: int, n_pecas: int, *, nucleos: int | None = None,
                       memoria: int | None = None, pedidos: int | None = None) -> tuple[int, int]:
    """(processos em paralelo, memória estimada de cada um). Cabe na memória dada (padrão: 70 % da livre)."""
    por_processo = metodo.memoria_por_processo(maior_peca)
    if pedidos:
        return max(1, pedidos), por_processo
    nucleos = nucleos or os.cpu_count() or 1
    orcamento = memoria if memoria is not None else int(0.7 * memoria_disponivel())
    return max(1, min(nucleos, n_pecas or 1, orcamento // max(por_processo, 1))), por_processo


def versao_zpaq(executavel: str) -> str:
    r = subprocess.run([executavel], capture_output=True, text=True, errors="replace", timeout=30)
    primeira = (r.stdout or r.stderr).strip().splitlines()
    return primeira[0] if primeira else "zpaq (versão desconhecida)"


def localizar_zpaq() -> str | None:
    return shutil.which("zpaq")


# ---------------------------------------------------------------------------
# Execução em paralelo, com estado para a interface
# ---------------------------------------------------------------------------
class Observador:
    """O que a interface quer saber. Os métodos ``inicio``/``fim`` vêm das threads de trabalho; ``tique`` vem
    da thread principal, umas 4 vezes por segundo, enquanto ela espera (é onde a tela é redesenhada)."""

    def fase(self, nome: str, total_bytes: int, total_itens: int, processos: int) -> None: ...
    def inicio(self, chave: object, rotulo: str, tamanho: int) -> None: ...
    def fim(self, chave: object, tamanho: int, segundos: float) -> None: ...
    def tique(self) -> None: ...


class _Processos:
    """Os compressores em execução, para matá-los num Ctrl+C (a thread que os espera não recebe o sinal)."""

    def __init__(self) -> None:
        self._vivos: set[subprocess.Popen] = set()
        self._trava = threading.Lock()
        self.cancelado = threading.Event()

    def rodar(self, cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
        if self.cancelado.is_set():
            raise KeyboardInterrupt
        # Sessão própria: o Ctrl+C do terminal chega só a este processo, que então encerra os compressores de
        # forma ordenada (matar_todos), sem corrida entre "o zpaq morreu" e "o usuário cancelou". 'nice': a
        # máquina continua usável enquanto todos os núcleos comprimem (preexec_fn não é seguro com threads).
        proc = subprocess.Popen(_NICE + cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
        with self._trava:
            self._vivos.add(proc)
        try:
            saida, erro = proc.communicate()
        finally:
            with self._trava:
                self._vivos.discard(proc)
        if self.cancelado.is_set():
            raise KeyboardInterrupt
        return subprocess.CompletedProcess(cmd, proc.returncode, saida, erro)

    def matar_todos(self) -> None:
        self.cancelado.set()
        with self._trava:
            vivos = list(self._vivos)
        for p in vivos:
            try:
                p.terminate()
            except OSError:
                pass
        for p in vivos:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


_NICE = ["nice", "-n", "10"] if shutil.which("nice") else []


def _executar(tarefas: list[tuple[object, str, int, Callable[[], object]]], processos: int,
              observador: Observador, nome_fase: str, controle: _Processos) -> dict[object, object]:
    """Roda ``(chave, rótulo, tamanho, função)`` num pool (maiores primeiro: termina antes). Uma exceção numa
    tarefa cancela o resto e sobe; Ctrl+C mata os compressores e sobe como KeyboardInterrupt."""
    tarefas = sorted(tarefas, key=lambda t: -t[2])
    observador.fase(nome_fase, sum(t[2] for t in tarefas), len(tarefas), processos)
    resultados: dict[object, object] = {}

    def envolver(chave, rotulo, tamanho, funcao):
        observador.inicio(chave, rotulo, tamanho)
        t0 = time.monotonic()
        r = funcao()
        observador.fim(chave, tamanho, time.monotonic() - t0)
        return r

    pool = ThreadPoolExecutor(max_workers=max(1, processos))
    pendentes: dict[Future, object] = {}
    try:
        for chave, rotulo, tamanho, funcao in tarefas:
            pendentes[pool.submit(envolver, chave, rotulo, tamanho, funcao)] = chave
        while pendentes:
            prontos, _ = wait(pendentes, timeout=0.25, return_when=FIRST_COMPLETED)
            observador.tique()
            for fut in prontos:
                chave = pendentes.pop(fut)
                resultados[chave] = fut.result()     # a exceção da tarefa (se houver) sobe daqui
    except BaseException:
        controle.matar_todos()
        for fut in pendentes:
            fut.cancel()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    observador.tique()
    return resultados


# ---------------------------------------------------------------------------
# Codecs (uma peça = um arquivo comprimido independente com UM arquivo dentro)
# ---------------------------------------------------------------------------
def _comprimir_peca(dados: bytes, nome_interno: str, destino: Path, metodo: Metodo, zpaq: str | None,
                    pasta: Path, controle: _Processos) -> None:
    if metodo.codec == "xz":
        destino.write_bytes(lzma.compress(dados, format=lzma.FORMAT_XZ, check=lzma.CHECK_SHA256,
                                          preset=9 | lzma.PRESET_EXTREME))
        return
    if zpaq is None:
        raise ErroSHAN("o zpaq não está instalado (sudo apt install zpaq).")
    trabalho = pasta / (destino.name + ".d")
    arquivo = trabalho / nome_interno
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_bytes(dados)
    try:
        r = controle.rodar([zpaq, "add", str(destino.resolve()), nome_interno, "-method", metodo.nivel,
                            "-threads", "1", "-noattributes"], cwd=trabalho)
        if r.returncode != 0:
            raise ErroSHAN(f"o zpaq falhou (código {r.returncode}) em '{nome_interno}': "
                           f"{_ultima_linha(r.stderr or r.stdout)}")
    finally:
        shutil.rmtree(trabalho, ignore_errors=True)


def _descomprimir_peca(comprimido: bytes, codec: str, zpaq: str | None, pasta: Path, rotulo: str,
                       controle: _Processos) -> bytes:
    if codec == "xz":
        try:
            return lzma.decompress(comprimido, format=lzma.FORMAT_XZ)
        except lzma.LZMAError as e:
            raise ErroSHAN(f"peça '{rotulo}' corrompida ({e}).")
    if codec != "zpaq":
        raise ErroSHAN(f"codec desconhecido '{codec}' -- o pacote foi feito por uma versão mais nova deste programa.")
    if zpaq is None:
        raise ErroSHAN("este pacote precisa do zpaq para ser lido (sudo apt install zpaq).")
    pasta.mkdir(parents=True)
    try:
        arq = pasta / "peca.zpaq"
        arq.write_bytes(comprimido)
        r = controle.rodar([zpaq, "x", str(arq), "-to", "saida", "-threads", "1", "-force"], cwd=pasta)
        if r.returncode != 0:
            raise ErroSHAN(f"peça '{rotulo}' corrompida: o zpaq falhou (código {r.returncode}): "
                           f"{_ultima_linha(r.stderr or r.stdout)}")
        achados = [p for p in (pasta / "saida").rglob("*") if p.is_file()]
        if len(achados) != 1:
            raise ErroSHAN(f"peça '{rotulo}': esperava 1 arquivo dentro, achei {len(achados)}.")
        return achados[0].read_bytes()
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def _ultima_linha(saida: bytes) -> str:
    linhas = [ln for ln in saida.decode(errors="replace").splitlines() if ln.strip()]
    return linhas[-1].strip() if linhas else "(sem mensagem)"


# ---------------------------------------------------------------------------
# Compactar
# ---------------------------------------------------------------------------
@dataclass
class Resultado:
    saida: Path
    entradas: list[Entrada]
    bytes_originais: int
    bytes_pacote: int
    segundos_compressao: float
    segundos_verificacao: float | None   # None: não verificado
    processos: int
    memoria_por_processo: int


def _agora_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compactar(entradas: list[Entrada], saida: Path, *, metodo: Metodo, processos: int,
              memoria_por_processo: int = 0, verificar: bool = True,
              observador: Observador | None = None, tamanho_peca: int = TAMANHO_PECA_MAX) -> Resultado:
    """Calcula os SHA-256, comprime em paralelo, grava o pacote como ``saida.parcial``, verifica-o (se
    pedido) e só então o renomeia para ``saida``. Qualquer falha ou Ctrl+C apaga o que foi feito."""
    observador = observador or Observador()
    if saida.exists():
        raise ErroUso(f"'{saida}' já existe -- escolha outro nome com -o.")
    zpaq = localizar_zpaq() if metodo.codec == "zpaq" else None
    if metodo.codec == "zpaq" and zpaq is None:
        raise ErroSHAN("o zpaq não está instalado (sudo apt install zpaq) -- ou use --rapido (xz).")
    saida.parent.mkdir(parents=True, exist_ok=True)
    parcial = saida.with_name(saida.name + SUFIXO_PARCIAL)
    temporaria = Path(_criar_pasta_temporaria(saida.parent))
    controle = _Processos()
    t0 = time.monotonic()
    try:
        # 1) SHA-256 dos originais e escolha da transformação (lê cada arquivo uma vez).
        def analisar(e: Entrada):
            def ler():
                st = e.origem.stat()
                e.tamanho, e.mtime_ns = st.st_size, st.st_mtime_ns
                e.transformacao, e.captura = escolher_transformacao(e.origem, e.tamanho)
                e.sha256 = sha256_arquivo(e.origem)
            return ler
        _executar([(e.nome, e.nome, max(e.tamanho, 1), analisar(e)) for e in entradas],
                  min(processos, 4), observador, "lendo", controle)

        # 2) Peças, maiores primeiro.
        numero = 1
        for e in entradas:
            e.partes = cortar_em_partes(e, numero, metodo, tamanho_peca)
            numero += len(e.partes)
        pecas_dir = temporaria / "pecas"
        pecas_dir.mkdir()

        def comprimir(e: Entrada, p: Parte):
            def fazer():
                dados = ler_fluxo(e.origem, e.transformacao, p.ini, p.fim)
                p.sha256 = hashlib.sha256(dados).hexdigest()
                destino = pecas_dir / PurePosixPath(p.membro).name
                _comprimir_peca(dados, p.nome_interno, destino, metodo, zpaq, temporaria, controle)
                p.bytes_comprimidos = destino.stat().st_size
                p.sha256_comprimido = sha256_arquivo(destino)
            return fazer
        tarefas = [(p.membro, _rotulo(e, p), p.tamanho, comprimir(e, p)) for e in entradas for p in e.partes]
        _executar(tarefas, processos, observador, "comprimindo", controle)

        # Um original mudou enquanto era lido? O hash e as peças podem não bater -- melhor parar aqui.
        for e in entradas:
            st = e.origem.stat()
            if (st.st_size, st.st_mtime_ns) != (e.tamanho, e.mtime_ns):
                raise ErroSHAN(f"'{e.origem}' foi modificado durante a compactação. Rode de novo.")
        segundos_compressao = time.monotonic() - t0

        # 3) Grava o pacote.
        manifesto = _montar_manifesto(entradas, metodo, zpaq)
        _gravar_tar(parcial, gerar_leiame(manifesto), manifesto,
                    [(p.membro, pecas_dir / PurePosixPath(p.membro).name) for e in entradas for p in e.partes])
        shutil.rmtree(pecas_dir, ignore_errors=True)

        # 4) Verifica o que foi GRAVADO (relido do disco), antes de dar o nome final.
        segundos_verificacao = None
        if verificar:
            t1 = time.monotonic()
            relatorio = Pacote(parcial).restaurar(None, None, processos, observador, fase="verificando",
                                                  controle=controle)
            if relatorio.falhas:
                raise ErroSHAN("a verificação do pacote FALHOU -- nada foi gravado:\n  " +
                               "\n  ".join(f"{nome}: {msg}" for nome, msg in relatorio.falhas))
            segundos_verificacao = time.monotonic() - t1
        os.replace(parcial, saida)
        _sincronizar_pasta(saida.parent)
    except BaseException as erro:
        controle.matar_todos()
        parcial.unlink(missing_ok=True)
        if isinstance(erro, OSError):       # disco cheio, permissão negada...: uma mensagem, não um traceback
            raise ErroSHAN(f"erro de leitura/gravação: {erro}") from erro
        raise
    finally:
        shutil.rmtree(temporaria, ignore_errors=True)
    return Resultado(saida, entradas, sum(e.tamanho for e in entradas), saida.stat().st_size,
                     segundos_compressao, segundos_verificacao, processos, memoria_por_processo)


def _rotulo(e: Entrada, p: Parte) -> str:
    if len(e.partes) == 1:
        return e.nome
    return f"{e.nome}  (parte {e.partes.index(p) + 1}/{len(e.partes)})"


def _criar_pasta_temporaria(onde: Path) -> str:
    """Temporários ao lado do destino (mesmo disco: a troca final de nome é atômica e não copia nada); num lugar
    sem permissão de escrita -- verificar um pacote num pendrive protegido, por exemplo --, a pasta do sistema."""
    import tempfile
    try:
        return tempfile.mkdtemp(prefix=PREFIXO_TEMPORARIO, dir=onde)
    except OSError:
        return tempfile.mkdtemp(prefix=PREFIXO_TEMPORARIO)


def _sincronizar_pasta(pasta: Path) -> None:
    try:
        fd = os.open(pasta, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _montar_manifesto(entradas: list[Entrada], metodo: Metodo, zpaq: str | None) -> dict:
    return {
        "formato": FORMATO,
        "versao": VERSAO_FORMATO,
        "criado_em": _agora_utc(),
        "criado_por": "SH-Analyzer, scripts/compactar_amostras.py",
        "metodo": {"nome": metodo.nome, "codec": metodo.codec, "nivel": metodo.nivel,
                   "programa": versao_zpaq(zpaq) if zpaq else "liblzma (módulo lzma do Python)"},
        "totais": {"arquivos": len(entradas), "bytes": sum(e.tamanho for e in entradas),
                   "bytes_comprimidos": sum(e.bytes_comprimidos for e in entradas)},
        "arquivos": [e.para_json() for e in entradas],
    }


def _info_tar(nome: str, tamanho: int, mtime: float) -> tarfile.TarInfo:
    info = tarfile.TarInfo(nome)
    info.size, info.mtime, info.mode = tamanho, int(mtime), 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def _gravar_tar(destino: Path, leiame: str, manifesto: dict, pecas: list[tuple[str, Path]]) -> None:
    import io
    agora = time.time()
    with open(destino, "xb") as bruto:
        with tarfile.open(fileobj=bruto, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for nome, conteudo in ((MEMBRO_LEIAME, leiame.encode("utf-8")),
                                   (MEMBRO_MANIFESTO, json.dumps(manifesto, ensure_ascii=False, indent=1).encode("utf-8"))):
                tar.addfile(_info_tar(nome, len(conteudo), agora), io.BytesIO(conteudo))
            for membro, caminho in pecas:
                with open(caminho, "rb") as f:
                    tar.addfile(_info_tar(membro, caminho.stat().st_size, agora), f)
        bruto.flush()
        os.fsync(bruto.fileno())


# ---------------------------------------------------------------------------
# Ler um pacote: listar, verificar, extrair
# ---------------------------------------------------------------------------
class Pacote:
    """Um pacote aberto para leitura. Lê só o índice do tar e o manifesto; as peças são lidas sob demanda,
    com ``os.pread`` (várias threads ao mesmo tempo, sem disputar a posição do arquivo)."""

    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        if not self.caminho.is_file():
            raise ErroUso(f"'{self.caminho}' não existe.")
        try:
            with tarfile.open(self.caminho, "r:") as tar:
                self._membros = {m.name: (m.offset_data, m.size) for m in tar.getmembers() if m.isfile()}
                bruto = tar.extractfile(MEMBRO_MANIFESTO).read() if MEMBRO_MANIFESTO in self._membros else None
        except (tarfile.TarError, OSError) as e:
            raise ErroSHAN(f"'{self.caminho}' não é um pacote de capturas legível ({e}).")
        if bruto is None:
            raise ErroSHAN(f"'{self.caminho}' não é um pacote de capturas (não tem {MEMBRO_MANIFESTO}).")
        try:
            self.manifesto = json.loads(bruto)
        except ValueError as e:
            raise ErroSHAN(f"manifesto de '{self.caminho}' ilegível ({e}).")
        if self.manifesto.get("formato") != FORMATO:
            raise ErroSHAN(f"'{self.caminho}' não é um pacote de capturas do SH-Analyzer.")
        if int(self.manifesto.get("versao", 0)) > VERSAO_FORMATO:
            raise ErroSHAN(f"'{self.caminho}' usa a versão {self.manifesto['versao']} do formato; este programa só "
                           f"conhece até a {VERSAO_FORMATO}. Atualize o repositório (git pull).")
        self.codec = self.manifesto["metodo"]["codec"]
        self.entradas = [self._entrada(d) for d in self.manifesto["arquivos"]]

    def _entrada(self, d: dict) -> Entrada:
        nome = d["caminho"]
        pp = PurePosixPath(nome)
        if pp.is_absolute() or ".." in pp.parts or not pp.parts or nome != str(pp):
            raise ErroSHAN(f"caminho inseguro no manifesto: {nome!r}")
        tamanho = int(d["tamanho"])
        e = Entrada(None, nome, tamanho, int(d["mtime_ns"]), int(d["modo"]) & 0o7777, d["sha256"],
                    Desentrelacamento.de_json(d.get("transformacao"), tamanho), d.get("captura"))
        e.partes = [Parte(p["membro"], p["nome_interno"], int(p["ini"]), int(p["fim"]), p["sha256"],
                          int(p["bytes_comprimidos"]), p["sha256_comprimido"]) for p in d["partes"]]
        fim = 0
        for p in e.partes:
            if p.ini != fim or p.fim <= p.ini or p.membro not in self._membros:
                raise ErroSHAN(f"manifesto inconsistente em '{nome}' (peça {p.membro}).")
            fim = p.fim
        if fim != tamanho:
            raise ErroSHAN(f"manifesto inconsistente em '{nome}': as peças cobrem {fim} de {tamanho} bytes.")
        return e

    @property
    def bytes_originais(self) -> int:
        return sum(e.tamanho for e in self.entradas)

    def ler_membro(self, membro: str) -> bytes:
        offset, tamanho = self._membros[membro]
        fd = os.open(self.caminho, os.O_RDONLY)
        try:
            dados = os.pread(fd, tamanho, offset)
        finally:
            os.close(fd)
        if len(dados) != tamanho:
            raise ErroSHAN(f"'{self.caminho}' está truncado (peça {membro}).")
        return dados

    def selecionar(self, padroes: Iterable[str]) -> list[int]:
        """Índices das entradas cujo caminho (ou só o nome, ou uma pasta acima) casa com algum padrão."""
        padroes = [p.rstrip("/") for p in padroes]
        if not padroes:
            return list(range(len(self.entradas)))
        escolhidas = []
        for i, e in enumerate(self.entradas):
            pp = PurePosixPath(e.nome)
            alvos = [e.nome, pp.name, *(str(a) for a in pp.parents if str(a) != ".")]
            if any(fnmatch(a, p) for p in padroes for a in alvos):
                escolhidas.append(i)
        return escolhidas

    def verificar_rapido(self, observador: Observador | None = None) -> list[tuple[str, str]]:
        """Só confere o SHA-256 das peças COMPRIMIDAS contra o manifesto (detecta corrupção no disco sem
        descomprimir nada). Devolve as falhas como (arquivo, mensagem)."""
        observador = observador or Observador()
        falhas = []
        trava = threading.Lock()

        def conferir(e: Entrada, p: Parte):
            def fazer():
                if hashlib.sha256(self.ler_membro(p.membro)).hexdigest() != p.sha256_comprimido:
                    with trava:
                        falhas.append((e.nome, f"a peça {p.membro} está corrompida"))
            return fazer
        tarefas = [(p.membro, e.nome, max(p.bytes_comprimidos, 1), conferir(e, p)) for e in self.entradas for p in e.partes]
        _executar(tarefas, 4, observador, "conferindo", _Processos())
        return falhas

    def restaurar(self, indices: list[int] | None, destino: Path | None, processos: int,
                  observador: Observador | None = None, *, fase: str = "extraindo", sobrescrever: bool = False,
                  controle: _Processos | None = None) -> Restauracao:
        """Descomprime as entradas ``indices`` (None = todas) e confere o SHA-256 de cada uma.

        ``destino`` None: só verifica (nada fica no disco). Com destino: grava ``destino/<caminho>`` com a data e
        as permissões originais; o arquivo só ganha o nome final depois de conferido. Um arquivo que já existe é
        pulado (a menos que ``sobrescrever``). Uma falha num arquivo não impede os outros."""
        observador = observador or Observador()
        controle = controle or _Processos()
        indices = list(range(len(self.entradas))) if indices is None else indices
        zpaq = localizar_zpaq() if self.codec == "zpaq" else None
        if self.codec == "zpaq" and zpaq is None:
            raise ErroSHAN("este pacote precisa do zpaq para ser lido (sudo apt install zpaq).")
        if destino is not None:
            destino.mkdir(parents=True, exist_ok=True)
        rel = Restauracao()
        estado = _EstadoRestauracao(Path(_criar_pasta_temporaria(destino if destino is not None else self.caminho.parent)),
                                    zpaq, controle, rel)
        try:
            tarefas = []
            for i in indices:
                e = self.entradas[i]
                alvo = None
                if destino is not None:
                    alvo = (destino / e.nome).resolve()
                    if not alvo.is_relative_to(destino.resolve()):
                        estado.falhar(e, "caminho fora da pasta de destino")
                        continue
                    if alvo.exists() and not sobrescrever:
                        igual = alvo.is_file() and alvo.stat().st_size == e.tamanho and sha256_arquivo(alvo) == e.sha256
                        rel.pulados.append((e.nome, "já existe, idêntico" if igual else
                                            "já existe e é DIFERENTE (use --sobrescrever)"))
                        continue
                fluxo = estado.pasta / f"{i}.fluxo"
                with open(fluxo, "wb") as f:
                    f.truncate(e.tamanho)
                estado.faltam[i] = len(e.partes)
                if not e.partes:
                    self._finalizar(e, fluxo, alvo, estado)
                for k in range(len(e.partes)):
                    tarefas.append((e.partes[k].membro, _rotulo(e, e.partes[k]), e.partes[k].tamanho,
                                    self._tarefa_parte(e, k, fluxo, alvo, estado)))
            _executar(tarefas, processos, observador, fase, controle)
        finally:
            shutil.rmtree(estado.pasta, ignore_errors=True)
        return rel

    def _tarefa_parte(self, e: Entrada, k: int, fluxo: Path, alvo: Path | None, estado: _EstadoRestauracao):
        p = e.partes[k]

        def fazer():
            if e.nome in estado.com_erro:
                return
            try:
                comprimido = self.ler_membro(p.membro)
                if hashlib.sha256(comprimido).hexdigest() != p.sha256_comprimido:
                    raise ErroSHAN(f"a peça {p.membro} está corrompida (SHA-256 não confere com o manifesto)")
                dados = _descomprimir_peca(comprimido, self.codec, estado.zpaq, estado.pasta / f"{fluxo.stem}-{k}.d",
                                           p.membro, estado.controle)
                if len(dados) != p.tamanho or hashlib.sha256(dados).hexdigest() != p.sha256:
                    raise ErroSHAN(f"a peça {p.membro} descomprimiu diferente do que foi gravado")
                fd = os.open(fluxo, os.O_WRONLY)
                try:
                    os.pwrite(fd, dados, p.ini)
                finally:
                    os.close(fd)
            except (ErroSHAN, OSError) as erro:
                estado.falhar(e, str(erro))
                return
            i = int(fluxo.stem)
            with estado.trava:
                estado.faltam[i] -= 1
                ultimo = estado.faltam[i] == 0
            if ultimo:
                self._finalizar(e, fluxo, alvo, estado)
        return fazer

    @staticmethod
    def _finalizar(e: Entrada, fluxo: Path, alvo: Path | None, estado: _EstadoRestauracao) -> None:
        """Fluxo completo -> original; confere o SHA-256; põe no lugar (ou apaga, se só verificando)."""
        if e.nome in estado.com_erro:
            return
        try:
            if e.transformacao is not None:
                original = fluxo.with_suffix(".original")
                desfazer_transformacao(fluxo, e.transformacao, original, e.tamanho)
                fluxo.unlink()
            else:
                original = fluxo
            if sha256_arquivo(original) != e.sha256:
                raise ErroSHAN("o SHA-256 do arquivo restaurado NÃO confere com o do original")
            if alvo is None:
                original.unlink()
            else:
                os.chmod(original, e.modo)
                os.utime(original, ns=(e.mtime_ns, e.mtime_ns))
                alvo.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.replace(original, alvo)
                except OSError as erro:
                    if erro.errno != errno.EXDEV:      # destino noutro sistema de arquivos (ponto de montagem)
                        raise
                    temporario = alvo.with_name(PREFIXO_TEMPORARIO + alvo.name)
                    shutil.move(original, temporario)   # copy2: preserva data e permissões
                    os.replace(temporario, alvo)
        except (ErroSHAN, OSError) as erro:
            estado.falhar(e, str(erro))
            return
        with estado.trava:
            estado.relatorio.restaurados.append(e.nome)
            estado.relatorio.bytes += e.tamanho


@dataclass
class Restauracao:
    restaurados: list[str] = field(default_factory=list)
    bytes: int = 0
    pulados: list[tuple[str, str]] = field(default_factory=list)
    falhas: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class _EstadoRestauracao:
    pasta: Path
    zpaq: str | None
    controle: _Processos
    relatorio: Restauracao
    faltam: dict[int, int] = field(default_factory=dict)
    com_erro: set[str] = field(default_factory=set)
    trava: threading.Lock = field(default_factory=threading.Lock)

    def falhar(self, e: Entrada, msg: str) -> None:
        with self.trava:
            if e.nome not in self.com_erro:
                self.com_erro.add(e.nome)
                self.relatorio.falhas.append((e.nome, msg))


def remover_originais(entradas: list[Entrada], raizes: Iterable[Path]) -> tuple[int, int, list[str]]:
    """Apaga os originais que continuam IDÊNTICOS ao que foi compactado (mesmo tamanho, data e SHA-256 --
    recalculado agora) e as pastas que ficarem vazias abaixo de ``raizes``. Devolve (apagados, bytes, avisos)."""
    apagados, liberados, avisos = 0, 0, []
    pastas: set[Path] = set()
    for e in entradas:
        try:
            st = e.origem.stat()
            if (st.st_size, st.st_mtime_ns) != (e.tamanho, e.mtime_ns) or sha256_arquivo(e.origem) != e.sha256:
                avisos.append(f"'{e.origem}' mudou depois de compactado -- mantido.")
                continue
            e.origem.unlink()
            apagados += 1
            liberados += e.tamanho
            pastas.add(e.origem.parent)
        except OSError as erro:
            avisos.append(f"'{e.origem}': {erro} -- mantido.")
    raizes = [Path(r).resolve() for r in raizes]
    for pasta in sorted(pastas, key=lambda p: -len(p.parts)):
        atual = pasta
        while any(atual != r and atual.is_relative_to(r) for r in raizes):
            try:
                atual.rmdir()            # só sai se estiver vazia
            except OSError:
                break
            atual = atual.parent
    return apagados, liberados, avisos


# ---------------------------------------------------------------------------
# LEIA-ME (vai dentro do pacote)
# ---------------------------------------------------------------------------
def gerar_leiame(manifesto: dict) -> str:
    m = manifesto["metodo"]
    ext = "." + m["codec"]
    descomprimir = ("zpaq x pecas/000001.zpaq        (zpaq 7.15+, domínio público: http://mattmahoney.net/dc/zpaq.html;\n"
                    "                                     Debian/Ubuntu: sudo apt install zpaq)"
                    if m["codec"] == "zpaq" else "xz -dk pecas/000001.xz")
    return f"""\
PACOTE DE CAPTURAS DO SH-ANALYZER
=================================
Formato {FORMATO}, versão {VERSAO_FORMATO}. Criado em {manifesto['criado_em']}.
{manifesto['totais']['arquivos']} arquivo(s), {manifesto['totais']['bytes']} bytes no original.
Compressor: {m['programa']} (método {m['nome']}: {m['codec']} {m['nivel']}).

Tudo aqui é SEM PERDAS: cada arquivo volta idêntico, bit a bit (o SHA-256 de cada um está no manifesto).

RESTAURAR (o jeito fácil)
-------------------------
No repositório do SH-Analyzer:

    uv run scripts/compactar_amostras.py extrair ESTE_PACOTE.tar                  # tudo
    uv run scripts/compactar_amostras.py extrair ESTE_PACOTE.tar T7c_10min.bin    # só um
    uv run scripts/compactar_amostras.py listar  ESTE_PACOTE.tar                  # o que tem dentro

RESTAURAR SEM O PROGRAMA
------------------------
1. tar xf ESTE_PACOTE.tar
   -> LEIA-ME.txt, manifesto.json (texto JSON) e pecas/000001{ext}, 000002{ext}...
2. Cada peça é um arquivo {m['codec']} independente com UM arquivo dentro:
       {descomprimir}
3. No manifesto, cada arquivo lista as suas "partes" em ordem (membro, nome_interno, ini, fim). Junte os
   arquivos de dentro das peças nessa ordem (cat parte1 parte2 ... > fluxo). Esse é o FLUXO do arquivo.
   - "transformacao": null -> o fluxo JÁ É o arquivo original. (Arquivo de uma peça só sem
     transformação: o arquivo de dentro da peça já tem o nome e o conteúdo originais.)
   - "transformacao": {{"tipo": "desentrelacar-uint16", "prefixo": P, "canais": C, "quadros": N}}
     -> captura com C canais. O fluxo tem: os P primeiros bytes do arquivo (o cabeçalho SHAN), as N
     amostras (uint16 little-endian) do canal 0, depois as N do canal 1, ..., as do canal C-1, e por
     fim o resto do arquivo como estava. Para voltar a intercalar (Python + numpy):

         import numpy as np
         s = np.fromfile("fluxo", np.uint8)
         fim = P + 2 * C * N
         corpo = s[P:fim].view("<u2").reshape(C, N).T          # (N, C): uma linha por instante
         open("original.bin", "wb").write(s[:P].tobytes() + corpo.tobytes() + s[fim:].tobytes())

4. Confira: sha256sum original.bin  ==  "sha256" do arquivo no manifesto.
   "mtime_ns" (data de modificação, ns desde 1970 UTC) e "modo" (permissões) também estão lá.
"""
