"""Os arquivos da placa no computador (docs/gui-plan.md, 11.7; a F3.7): baixar uma captura com a retomada, conferir a
cópia e apagar da placa só o que foi conferido. Sem Qt.

**A origem** (:class:`OrigemSSH`): a placa pelo SFTP da conexão (o simulador também: ele é servido por SSH). O
protocolo :class:`Origem` deixa os testes trocarem a placa.

**Baixar** (:func:`baixar`): os blocos pedidos em paralelo (o SFTP pipelinado: vários pedidos de leitura em voo, que
escondem a ida e volta), gravados num ``<nome>.parcial`` ao lado do destino. **A retomada:** uma transferência
interrompida (o cabo, o cancelamento) continua do ponto em que parou, se o arquivo na placa é o mesmo (o tamanho e a
data, guardados num ``.parcial.json``); senão, começa de novo. No fim, o parcial vira o arquivo, com a data da placa.

**A medição tem prioridade:** com uma captura rodando na placa (o ``ler_adc``), a transferência espera
(``esperar_a_captura``, conferido no começo e a cada :data:`INTERVALO_DA_CAPTURA_S`). Na placa de verdade
(16/11/2026), capturas de 21 s a 400 kS/s com uma, três transferências e três fluxos de cifra ao lado (o único
núcleo saturado) tiveram a mesma folga mínima da PRU (18 ciclos, 90 ns), nenhuma amostra atrasada, nenhum buffer
sobrescrito, nenhum quadro com ruído no SDO e o mesmo piso de ruído (0,317 µV/√Hz de 9 a 150 kHz) que as sem carga:
a PRU grava na memória reservada sem esperar o ARM, e o ``ler_adc`` tem ~2,6 s por buffer de 2 MiB. Esperar custa
pouco e cobre o que o teste não cobriu (o cartão cheio, capturas longas, outras taxas).

**Conferir** (:func:`conferir`): o tamanho, e a v9 pelo ``crc32_amostras`` do cabeçalho contra o calculado na cópia
(o cabeçalho tem o CRC dele); sem ele (até a v8), o SHA-256 dos dois lados. **Apagar da placa** (:func:`apagar`) é do
chamador, que só o oferece para a cópia conferida (o :class:`IndiceDeCopias` guarda isso entre as sessões).

Cada operação vai para o registro de atividade, como os comandos.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import shlex
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .agente import ErroDaPlaca
from .erros import ErroDeConexao

if TYPE_CHECKING:
    from .conexao import ConexaoSSH

log = logging.getLogger(__name__)

BLOCO = 256 * 1024
EM_PARALELO = 8
"""Os blocos em voo: 2 MiB em trânsito, o bastante para esconder a ida e volta do USB e da LAN."""
INTERVALO_DA_CAPTURA_S = 10.0
SUFIXO_PARCIAL = ".parcial"
TEMPO_DO_SHA256_S = 300.0


class Leitor(Protocol):
    async def ler(self, deslocamento: int, tamanho: int) -> bytes: ...
    async def fechar(self) -> None: ...


class Origem(Protocol):
    """De onde vêm os arquivos (:class:`OrigemSSH`). ``meio``: como, para o registro ("pelo SFTP")."""

    meio: str

    async def tamanho(self, caminho: str) -> tuple[int, float]: ...
    async def abrir(self, caminho: str) -> Leitor: ...
    async def sha256(self, caminho: str) -> str: ...
    async def apagar(self, caminho: str) -> None: ...
    async def captura_rodando(self) -> bool: ...
    def registrar(self, descricao: str, comando: str, inicio: float, duracao_s: float, codigo: int | None,
                  falha: str = "") -> None: ...


def _erro_da_rede(e: BaseException, o_que: str) -> ErroDeConexao:
    return ErroDeConexao(f"a conexão com a placa caiu durante {o_que} ({getattr(e, 'reason', None) or e})")


class _LeitorSFTP:
    """Um arquivo aberto pelo SFTP, com ``block_size=0`` (cada ``read`` do asyncssh é um pedido ``READ`` só). Um bloco
    é lido em pedidos de até ``maximo`` bytes, todos de uma vez: o que o servidor atende num pedido (o
    ``limits@openssh.com``; sem ele, os 16 KiB seguros do asyncssh, o caso da placa, com o OpenSSH 7.9 da imagem
    Debian 10).

    O leitor paralelo do asyncssh (o ``block_size`` padrão) faz o mesmo, mas deixa as tarefas dele para trás quando a
    leitura é cancelada (o :func:`baixar` cancela as outras quando uma falha), e elas falhavam sem dono na queda da
    conexão. Aqui, os pedidos de uma leitura que falha ou é cancelada são cancelados e esperados. Na placa pelo USB
    (16/11/2026), com o ``aes128-ctr`` da conexão, os dois baixam a 5,0 a 5,1 MiB/s."""

    def __init__(self, arquivo, caminho: str, maximo: int):
        self._arquivo, self._caminho, self._maximo = arquivo, caminho, maximo

    async def ler(self, deslocamento: int, tamanho: int) -> bytes:
        """``tamanho`` bytes a partir de ``deslocamento``; menos só no fim do arquivo."""
        fim = deslocamento + tamanho
        pedacos = [(d, min(self._maximo, fim - d)) for d in range(deslocamento, fim, self._maximo)]
        pedidos = [asyncio.ensure_future(self._ler_pedaco(d, n)) for d, n in pedacos]
        try:
            partes = await asyncio.gather(*pedidos)
        except BaseException:
            for pedido in pedidos:
                pedido.cancel()
            await asyncio.gather(*pedidos, return_exceptions=True)
            raise
        dados = bytearray()
        for (_d, n), parte in zip(pedacos, partes):
            dados += parte
            if len(parte) < n:                      # o fim do arquivo
                break
        return bytes(dados)

    async def _ler_pedaco(self, deslocamento: int, tamanho: int) -> bytes:
        """Um pedido; o que faltar é pedido de novo (o servidor do SFTP pode responder com menos que o pedido)."""
        import asyncssh

        partes = []
        try:
            while tamanho > 0:
                dados = await self._arquivo.read(tamanho, deslocamento)
                if not dados:
                    break
                partes.append(dados)
                deslocamento += len(dados)
                tamanho -= len(dados)
        except (asyncssh.Error, OSError) as e:
            raise _erro_da_rede(e, f"a leitura de {self._caminho}") from e
        return b"".join(partes)

    async def fechar(self) -> None:
        import asyncssh

        with contextlib.suppress(asyncssh.Error, OSError):
            await self._arquivo.close()


class OrigemSSH:
    """A placa, pelo SFTP da conexão (e um comando para o SHA-256 e para saber se há captura rodando)."""

    meio = "pelo SFTP"

    def __init__(self, conexao: ConexaoSSH):
        self.conexao = conexao

    async def _sftp(self):
        return await self.conexao.sftp()

    async def tamanho(self, caminho: str) -> tuple[int, float]:
        import asyncssh

        try:
            atributos = await (await self._sftp()).stat(caminho)
        except asyncssh.SFTPNoSuchFile as e:
            raise ErroDaPlaca(f"{caminho} não está mais na placa") from e
        except (asyncssh.Error, OSError) as e:
            raise _erro_da_rede(e, f"a leitura do tamanho de {caminho}") from e
        return int(atributos.size or 0), float(atributos.mtime or 0.0)

    async def abrir(self, caminho: str) -> Leitor:
        import asyncssh

        try:
            sftp = await self._sftp()
            return _LeitorSFTP(await sftp.open(caminho, "rb", block_size=0), caminho, sftp.limits.max_read_len)
        except asyncssh.SFTPNoSuchFile as e:
            raise ErroDaPlaca(f"{caminho} não está mais na placa") from e
        except (asyncssh.Error, OSError) as e:
            raise _erro_da_rede(e, f"a abertura de {caminho}") from e

    async def sha256(self, caminho: str) -> str:
        r = await self.conexao.executar(f"sha256sum -- {shlex.quote(caminho)}", tempo_limite=TEMPO_DO_SHA256_S,
                                        descricao=f"o SHA-256 de {Path(caminho).name} na placa")
        if r.codigo != 0 or not r.saida.strip():
            raise ErroDaPlaca(f"o sha256sum da placa falhou (código {r.codigo}): {(r.erro or r.saida).strip()[:200]}")
        return r.saida.split()[0]

    async def apagar(self, caminho: str) -> None:
        import asyncssh

        inicio, t0 = time.time(), time.monotonic()
        try:
            await (await self._sftp()).remove(caminho)
        except (asyncssh.Error, OSError) as e:
            self.registrar(f"apagar {Path(caminho).name} da placa (SFTP)", f"sftp rm {caminho}", inicio,
                           time.monotonic() - t0, None, str(getattr(e, "reason", None) or e))
            raise ErroDaPlaca(f"a placa não apagou {caminho}: {getattr(e, 'reason', None) or e}") from e
        self.registrar(f"apagar {Path(caminho).name} da placa (SFTP)", f"sftp rm {caminho}", inicio,
                       time.monotonic() - t0, 0)

    async def captura_rodando(self) -> bool:
        r = await self.conexao.executar("pgrep -x ler_adc", descricao="há captura rodando? (pgrep -x ler_adc)")
        return r.codigo == 0

    def registrar(self, descricao: str, comando: str, inicio: float, duracao_s: float, codigo: int | None,
                  falha: str = "") -> None:
        self.conexao.registrar_comando(descricao, comando, inicio, duracao_s, codigo, falha)


def _sha256_local(caminho: Path) -> str:
    resumo = hashlib.sha256()
    with caminho.open("rb") as f:
        while bloco := f.read(1 << 20):
            resumo.update(bloco)
    return resumo.hexdigest()


def _mib(n: int) -> str:
    return f"{n / 2**20:.1f}".replace(".", ",") + " MiB"


async def esperar_sem_captura(origem: Origem, ao_esperar: Callable[[bool], object] | None = None,
                              intervalo_s: float = 2.0) -> None:
    """Volta quando não há captura rodando na placa; enquanto há, avisa ``ao_esperar(True)`` e confere de novo a cada
    ``intervalo_s`` (no fim, ``ao_esperar(False)``)."""
    if not await origem.captura_rodando():
        return
    if ao_esperar is not None:
        ao_esperar(True)
    try:
        while await origem.captura_rodando():
            await asyncio.sleep(intervalo_s)
    finally:
        if ao_esperar is not None:
            ao_esperar(False)


async def baixar(origem: Origem, remoto: str, local: Path, *,
                 ao_progredir: Callable[[int, int], object] | None = None,
                 esperar_a_captura: Callable[[], Awaitable[None]] | None = None,
                 em_paralelo: int = EM_PARALELO, bloco: int = BLOCO) -> int:
    """Baixa ``remoto`` para ``local`` (ver o módulo) e devolve o tamanho. ``ao_progredir(transferidos, total)`` a
    cada bloco; ``esperar_a_captura()`` no começo e a cada :data:`INTERVALO_DA_CAPTURA_S`, que só volta sem captura
    rodando. ``ErroDeConexao`` na queda: a parte baixada fica, para retomar."""
    total, modificado = await origem.tamanho(remoto)
    local.parent.mkdir(parents=True, exist_ok=True)
    parcial = local.with_name(local.name + SUFIXO_PARCIAL)
    marca = parcial.with_name(parcial.name + ".json")
    da_origem = {"remoto": remoto, "bytes": total, "modificado": modificado}
    inicio_parcial = 0
    if parcial.exists():
        try:
            mesma = json.loads(marca.read_text(encoding="utf-8")) == da_origem
        except (OSError, ValueError):
            mesma = False
        inicio_parcial = parcial.stat().st_size if mesma and parcial.stat().st_size <= total else 0
    if inicio_parcial == 0:
        parcial.unlink(missing_ok=True)
        marca.write_text(json.dumps(da_origem), encoding="utf-8")
    if esperar_a_captura is not None:
        await esperar_a_captura()
    inicio, t0 = time.time(), time.monotonic()
    descricao = (f"baixar {Path(remoto).name} ({_mib(total)}) {origem.meio}" +
                 (f", retomando de {_mib(inicio_parcial)}" if inicio_parcial else ""))
    leitor = await origem.abrir(remoto)
    pendentes: deque[tuple[int, int, asyncio.Future]] = deque()
    transferidos = inicio_parcial
    try:
        with parcial.open("ab") as destino:
            proximo, ultima_conferencia = inicio_parcial, time.monotonic()
            while proximo < total or pendentes:
                while len(pendentes) < em_paralelo and proximo < total:
                    n = min(bloco, total - proximo)
                    pendentes.append((proximo, n, asyncio.ensure_future(leitor.ler(proximo, n))))
                    proximo += n
                deslocamento, n, pedido = pendentes.popleft()
                dados = await pedido
                if len(dados) != n:
                    raise ErroDaPlaca(f"{remoto} mudou na placa durante a transferência (leu {len(dados)} bytes em "
                                      f"{deslocamento}, e não {n}): baixe de novo")
                destino.write(dados)
                transferidos = deslocamento + n
                if ao_progredir is not None:
                    ao_progredir(transferidos, total)
                if esperar_a_captura is not None and time.monotonic() - ultima_conferencia >= INTERVALO_DA_CAPTURA_S:
                    destino.flush()
                    await esperar_a_captura()
                    ultima_conferencia = time.monotonic()
            destino.flush()
            os.fsync(destino.fileno())
    except BaseException as e:
        for _d, _n, pedido in pendentes:
            pedido.cancel()
        await asyncio.gather(*(p for _d, _n, p in pendentes), return_exceptions=True)
        falha = "cancelada" if isinstance(e, asyncio.CancelledError) else str(e)[:200]
        origem.registrar(descricao, f"sftp get {remoto}", inicio, time.monotonic() - t0, None,
                         f"{falha}; {_mib(transferidos)} de {_mib(total)} ficam para retomar")
        raise
    finally:
        await leitor.fechar()
    os.replace(parcial, local)
    os.utime(local, (modificado, modificado))
    marca.unlink(missing_ok=True)
    origem.registrar(descricao, f"sftp get {remoto}", inicio, time.monotonic() - t0, 0)
    return total


@dataclass(frozen=True)
class Conferencia:
    ok: bool
    como: str                 # "crc32" (o das amostras, no cabeçalho v9) ou "sha256" (dos dois lados)
    detalhe: str


async def conferir(origem: Origem, remoto: str, local: Path, *,
                   ao_progredir: Callable[[float], object] | None = None) -> Conferencia:
    """Confere a cópia ``local`` contra a placa: o tamanho e, na v9, o CRC das amostras contra o do cabeçalho; até a
    v8, o SHA-256 dos dois lados."""
    total, _modificado = await origem.tamanho(remoto)
    tamanho_local = local.stat().st_size
    if tamanho_local != total:
        return Conferencia(False, "tamanho", f"a cópia tem {tamanho_local} bytes, e a placa, {total}")
    crc = await asyncio.to_thread(_crc_das_amostras, local, ao_progredir)
    if crc is not None:
        return Conferencia(crc, "crc32", "o CRC das amostras confere com o do cabeçalho" if crc else
                           "o CRC das amostras não confere com o do cabeçalho: a cópia está corrompida")
    no_computador, na_placa = await asyncio.gather(asyncio.to_thread(_sha256_local, local), origem.sha256(remoto))
    igual = no_computador == na_placa
    return Conferencia(igual, "sha256", "o SHA-256 é o mesmo dos dois lados" if igual else
                       f"o SHA-256 da cópia ({no_computador[:12]}…) não é o da placa ({na_placa[:12]}…)")


def _crc_das_amostras(local: Path, ao_progredir) -> bool | None:
    """O CRC das amostras da v9 (o motor confere); ``None`` sem ele (até a v8, um arquivo sem o cabeçalho)."""
    from supraharmonicos import api

    try:
        captura = api.abrir_captura(local)
    except Exception as e:                     # um arquivo que o motor não lê: o SHA-256 decide
        log.info("a cópia %s não abriu no motor (%s): conferida pelo SHA-256", local, e)
        return None
    return api.conferir_integridade(captura, progresso=ao_progredir)


async def apagar(origem: Origem, remoto: str) -> None:
    await origem.apagar(remoto)


# ------------------------------------------------------------------ o índice das cópias

@dataclass(frozen=True)
class CopiaLocal:
    """Onde está a cópia de uma captura da placa no computador, e se ela foi conferida (e como)."""

    local: str
    conferida: bool | None                  # None: ainda não conferida
    como: str = ""
    em: float = 0.0


class IndiceDeCopias:
    """As cópias das capturas da placa no computador, entre as sessões (num JSON da pasta da placa): pela placa (o nº
    de série), o caminho na placa, o tamanho e a data, o lugar da cópia e a conferência. Uma cópia apagada ou mudada
    no computador deixa de contar (:meth:`copia` confere o tamanho)."""

    def __init__(self, arquivo: Path):
        self.arquivo = Path(arquivo)

    @staticmethod
    def chave(serie: str | None, caminho: str, tamanho: int, modificado: float) -> str:
        return f"{serie or '?'}|{caminho}|{tamanho}|{int(modificado)}"

    def _ler(self) -> dict:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return dados if isinstance(dados, dict) else {}

    def copia(self, chave: str, tamanho: int) -> CopiaLocal | None:
        d = self._ler().get(chave)
        if not isinstance(d, dict):
            return None
        local = Path(str(d.get("local", "")))
        try:
            if local.stat().st_size != tamanho:
                return None
        except OSError:
            return None
        conferida = d.get("conferida")
        return CopiaLocal(str(local), conferida if isinstance(conferida, bool) else None, str(d.get("como") or ""),
                          float(d.get("em") or 0.0))

    def lembrar(self, chave: str, copia: CopiaLocal) -> None:
        dados = self._ler()
        dados[chave] = {"local": copia.local, "conferida": copia.conferida, "como": copia.como, "em": copia.em}
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        provisorio = self.arquivo.with_name(self.arquivo.name + ".novo")
        provisorio.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(provisorio, self.arquivo)
