"""O cliente do agente da placa: roda ``shan_agente.py <comando>`` por um transporte e confere a resposta JSON.

O transporte é quem leva o comando até a placa, com a mesma interface, ``await executar(argv) -> (código, stdout,
stderr)``:

* :class:`TransporteSSH` -- na placa, por uma conexão SSH (``sh_placa.conexao``). **O código do agente vai pelo
  stdin** (``python3 -``): a placa não precisa ter o agente, nada é gravado nela, e ele fala sempre o protocolo deste
  aplicativo, mesmo com um firmware antigo (o diagnóstico de uma placa desatualizada funciona, e diz que ela está);
* :class:`TransporteLocal` -- neste computador, com uma raiz falsa (o simulador e os testes).

Tudo é ``async``: roda no laço do ``sh_placa`` (``sh_placa/laco.py``), e a interface chega a ele pela ponte.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .estado import CapturasDaPlaca, EstadoDaPlaca, LogsDaPlaca, RelogioDaPlaca

PROTOCOLO = 1
"""A versão do formato das respostas que este cliente entende (``PROTOCOLO`` do agente)."""
AGENTE = Path(__file__).resolve().parents[2] / "firmware" / "agente" / "shan_agente.py"
TEMPO_LIMITE_S = 20.0
PASTA_DO_FIRMWARE = "firmware"
"""A pasta do firmware na placa, relativa ao home (a do ``BeagleBone_Setup.sh``)."""
SEM_O_COMANDO = 127
"""O código de saída do shell para um comando que não existe (o ``python3``, numa imagem sem ele)."""


class ErroDaPlaca(Exception):
    """A placa não respondeu, ou respondeu o que não se entende (com a mensagem pronta para mostrar)."""


class Transporte(Protocol):
    async def executar(self, argv: list[str]) -> tuple[int, str, str]: ...


class Conexao(Protocol):
    """O que o :class:`TransporteSSH` usa da conexão (``sh_placa.conexao.ConexaoSSH``)."""

    async def executar(self, comando: str, *, entrada: str | None = None, tempo_limite: float = ...,
                       descricao: str = "") -> object: ...


class TransporteLocal:
    """Roda o agente aqui, com o Python deste processo. ``raiz`` e ``pasta_firmware`` viram ``SHAN_RAIZ`` e
    ``SHAN_PASTA`` (o sistema falso do simulador)."""

    def __init__(self, raiz: Path | None = None, pasta_firmware: Path | None = None, agente: Path = AGENTE):
        self.raiz, self.pasta_firmware, self.agente = raiz, pasta_firmware, Path(agente)

    async def executar(self, argv: list[str]) -> tuple[int, str, str]:
        ambiente = dict(os.environ)
        if self.raiz is not None:
            ambiente["SHAN_RAIZ"] = str(self.raiz)
        if self.pasta_firmware is not None:
            ambiente["SHAN_PASTA"] = str(self.pasta_firmware)
        try:
            processo = await asyncio.create_subprocess_exec(
                sys.executable, str(self.agente), *argv, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=ambiente)
        except OSError as e:
            raise ErroDaPlaca(f"não deu para rodar o agente: {e}") from e
        try:
            saida, erro = await asyncio.wait_for(processo.communicate(), TEMPO_LIMITE_S)
        except asyncio.TimeoutError as e:
            raise ErroDaPlaca(f"o agente não respondeu em {TEMPO_LIMITE_S:g} s") from e
        finally:
            if processo.returncode is None:          # o tempo esgotou ou a chamada foi cancelada
                processo.kill()
                await processo.wait()
        return processo.returncode, saida.decode("utf-8", "replace"), erro.decode("utf-8", "replace")


class TransporteSSH:
    """O agente deste aplicativo na placa, por uma conexão SSH já aberta: o código vai pelo stdin do ``python3 -``, e
    ``SHAN_PASTA`` diz onde está a pasta do firmware (``pasta_firmware``, relativa ao home ou absoluta). Cada chamada
    é um canal ``exec`` da conexão, e vai para o registro de atividade dela."""

    def __init__(self, conexao: Conexao, pasta_firmware: str = PASTA_DO_FIRMWARE, agente: Path = AGENTE):
        self.conexao = conexao
        self.pasta_firmware = pasta_firmware
        self._codigo = Path(agente).read_text(encoding="utf-8")

    def comando(self, argv: list[str]) -> str:
        """A linha que roda na placa (a que vai para o registro). Uma pasta relativa é a partir do ``$HOME``."""
        pasta = self.pasta_firmware
        pasta = shlex.quote(pasta) if pasta.startswith("/") else '"$HOME"/' + shlex.quote(pasta.lstrip("~/") or ".")
        return " ".join([f"SHAN_PASTA={pasta}", "python3", "-", *map(shlex.quote, argv)])

    async def executar(self, argv: list[str]) -> tuple[int, str, str]:
        resultado = await self.conexao.executar(self.comando(argv), entrada=self._codigo, tempo_limite=TEMPO_LIMITE_S,
                                                descricao=f"agente: {' '.join(argv)}")
        return resultado.codigo, resultado.saida, resultado.erro

    async def seguir(self, argv: list[str], ao_ler: Callable[[str], None]) -> int | None:
        """Um comando de fluxo do agente (o ``monitor``, o ``seguir_logs``): ``ao_ler(linha)`` a cada linha, até o
        agente terminar (o código) ou a tarefa ser cancelada (o agente recebe o ``TERM`` na placa). A queda é
        ``ErroDeConexao``."""
        descricao = f"agente: {' '.join(argv)} (ao vivo)"
        async with self.conexao.canal(self.comando(argv), descricao) as (processo, desfecho):
            processo.stdin.write(self._codigo)
            processo.stdin.write_eof()
            async for linha in processo.stdout:
                ao_ler(linha)
            await processo.wait()
            self.conexao.concluir(processo, desfecho, descricao)
        return desfecho.codigo


class ClienteDoAgente:
    """Fala com o agente: :meth:`versao`, :meth:`estado`, :meth:`saude` (o estado com o diagnóstico),
    :meth:`capturas`, :meth:`relogio` e :meth:`logs`."""

    def __init__(self, transporte: Transporte):
        self.transporte = transporte

    async def chamar(self, comando: str, *args: str) -> dict:
        """A resposta do agente a ``comando``, conferida: JSON, o protocolo certo e sem erro."""
        return (await self._chamar(comando, *args))[0]

    async def _chamar(self, comando: str, *args: str) -> tuple[dict, float, float]:
        """A resposta, e o ``time.time()`` em que foi pedida e em que chegou (o relógio da placa é comparado com
        eles: ``sh_placa/estado.py``)."""
        enviado_em = time.time()
        codigo, saida, erro = await self.transporte.executar([comando, *args])
        recebido_em = time.time()
        try:
            resposta = json.loads(saida.strip().splitlines()[-1]) if saida.strip() else None
        except (json.JSONDecodeError, IndexError):
            resposta = None
        if not isinstance(resposta, dict):
            if codigo == SEM_O_COMANDO:
                raise ErroDaPlaca("a placa não tem o python3, que o agente usa (as imagens Debian da BeagleBoard têm): "
                                  f"{(erro or saida).strip()[:200]}")
            detalhe = (erro or saida).strip().splitlines()[-1:] or ["sem saída"]
            raise ErroDaPlaca(f"o agente respondeu algo que não é JSON (código {codigo}): {detalhe[0][:200]}")
        if resposta.get("protocolo") != PROTOCOLO:
            raise ErroDaPlaca(f"o agente fala o protocolo {resposta.get('protocolo')!r}, e este cliente, o {PROTOCOLO}: "
                              "o agente e o cliente são de versões diferentes do aplicativo")
        if "erro" in resposta:
            raise ErroDaPlaca(f"o agente recusou o comando: {resposta['erro']}")
        if codigo != 0:
            raise ErroDaPlaca(f"o agente saiu com o código {codigo}")
        return resposta, enviado_em, recebido_em

    async def versao(self) -> dict:
        return await self.chamar("versao")

    async def estado(self) -> EstadoDaPlaca:
        """O estado, sem as conferências: o que a barra e a visão geral mostram (o diagnóstico vem da :meth:`saude`)."""
        resposta, enviado_em, recebido_em = await self._chamar("estado")
        return EstadoDaPlaca.de_json(resposta, recebido_em, enviado_em)

    async def saude(self) -> EstadoDaPlaca:
        """O estado com as conferências da placa: o que :meth:`EstadoDaPlaca.diagnostico` usa."""
        resposta, enviado_em, recebido_em = await self._chamar("saude")
        return EstadoDaPlaca.de_json(resposta, recebido_em, enviado_em)

    async def capturas(self) -> CapturasDaPlaca:
        return CapturasDaPlaca.de_json(await self.chamar("capturas"))

    async def relogio(self) -> RelogioDaPlaca:
        resposta, enviado_em, recebido_em = await self._chamar("relogio")
        relogio = RelogioDaPlaca.de_json(resposta, recebido_em, enviado_em)
        if relogio is None:
            raise ErroDaPlaca("o agente respondeu o relógio sem a hora")
        return relogio

    async def logs(self, linhas: int = 50, todos: bool = False) -> LogsDaPlaca:
        """O kernel e o diário: com ``todos``, as últimas ``linhas`` de cada um; sem, só as do firmware e os erros."""
        args = [str(linhas)] + (["--todos"] if todos else [])
        return LogsDaPlaca.de_json(await self.chamar("logs", *args))

    async def seguir(self, comando: str, *args: str, ao_receber: Callable[[dict], None]) -> None:
        """Um comando de fluxo (``monitor``, ``seguir_logs``): o cabeçalho conferido (o protocolo, o erro de uso) e
        ``ao_receber(dados)`` a cada linha JSON, até o agente terminar ou a tarefa ser cancelada."""
        seguir = getattr(self.transporte, "seguir", None)
        if seguir is None:
            raise ErroDaPlaca("este transporte não segue comandos ao vivo (só o SSH)")
        cabecalho: list[dict] = []

        def ao_ler(linha: str) -> None:
            try:
                dados = json.loads(linha)
            except json.JSONDecodeError:
                return
            if not isinstance(dados, dict):
                return
            if not cabecalho:
                cabecalho.append(dados)
                if dados.get("protocolo") != PROTOCOLO:
                    raise ErroDaPlaca(f"o agente fala o protocolo {dados.get('protocolo')!r}, e este cliente, o "
                                      f"{PROTOCOLO}")
                if "erro" in dados:
                    raise ErroDaPlaca(f"o agente recusou o comando: {dados['erro']}")
                return
            if "erro" in dados and len(dados) == 1:
                raise ErroDaPlaca(f"o agente parou: {dados['erro']}")
            ao_receber(dados)

        codigo = await seguir([comando, *args], ao_ler)
        if not cabecalho:
            raise ErroDaPlaca(f"o agente não respondeu ao {comando} (código {codigo})")
