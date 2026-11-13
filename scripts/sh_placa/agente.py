"""O cliente do agente da placa: roda ``shan_agente.py <comando>`` por um transporte e confere a resposta JSON.

O transporte é quem leva o comando até a placa. :class:`TransporteLocal` roda o agente neste computador (com uma raiz
falsa, no simulador e nos testes); o transporte por SSH entra na Fase 3, com a mesma interface: ``executar(argv) ->
(código, stdout, stderr)``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol

from .estado import EstadoDaPlaca

PROTOCOLO = 1
"""A versão do formato das respostas que este cliente entende (``PROTOCOLO`` do agente)."""
AGENTE = Path(__file__).resolve().parents[2] / "firmware" / "agente" / "shan_agente.py"
TEMPO_LIMITE_S = 20.0


class ErroDaPlaca(Exception):
    """A placa não respondeu, ou respondeu o que não se entende (com a mensagem pronta para mostrar)."""


class Transporte(Protocol):
    def executar(self, argv: list[str]) -> tuple[int, str, str]: ...


class TransporteLocal:
    """Roda o agente aqui, com o Python deste processo. ``raiz`` e ``pasta_firmware`` viram ``SHAN_RAIZ`` e
    ``SHAN_PASTA`` (o sistema falso do simulador)."""

    def __init__(self, raiz: Path | None = None, pasta_firmware: Path | None = None, agente: Path = AGENTE):
        self.raiz, self.pasta_firmware, self.agente = raiz, pasta_firmware, Path(agente)

    def executar(self, argv: list[str]) -> tuple[int, str, str]:
        ambiente = dict(os.environ)
        if self.raiz is not None:
            ambiente["SHAN_RAIZ"] = str(self.raiz)
        if self.pasta_firmware is not None:
            ambiente["SHAN_PASTA"] = str(self.pasta_firmware)
        try:
            r = subprocess.run([sys.executable, str(self.agente), *argv], capture_output=True, text=True,
                               timeout=TEMPO_LIMITE_S, env=ambiente)
        except subprocess.TimeoutExpired as e:
            raise ErroDaPlaca(f"o agente não respondeu em {TEMPO_LIMITE_S:g} s") from e
        except OSError as e:
            raise ErroDaPlaca(f"não deu para rodar o agente: {e}") from e
        return r.returncode, r.stdout, r.stderr


class ClienteDoAgente:
    """Fala com o agente: :meth:`versao` e :meth:`estado`."""

    def __init__(self, transporte: Transporte):
        self.transporte = transporte

    def chamar(self, comando: str, *args: str) -> dict:
        """A resposta do agente a ``comando``, conferida: JSON, o protocolo certo e sem erro."""
        codigo, saida, erro = self.transporte.executar([comando, *args])
        try:
            resposta = json.loads(saida.strip().splitlines()[-1]) if saida.strip() else None
        except (json.JSONDecodeError, IndexError):
            resposta = None
        if not isinstance(resposta, dict):
            detalhe = (erro or saida).strip().splitlines()[-1:] or ["sem saída"]
            raise ErroDaPlaca(f"o agente respondeu algo que não é JSON (código {codigo}): {detalhe[0][:200]}")
        if resposta.get("protocolo") != PROTOCOLO:
            raise ErroDaPlaca(f"o agente da placa fala o protocolo {resposta.get('protocolo')!r}, e este aplicativo, o "
                              f"{PROTOCOLO}: atualize o firmware da placa (o agente vai junto)")
        if "erro" in resposta:
            raise ErroDaPlaca(f"o agente recusou o comando: {resposta['erro']}")
        if codigo != 0:
            raise ErroDaPlaca(f"o agente saiu com o código {codigo}")
        return resposta

    def versao(self) -> dict:
        return self.chamar("versao")

    def estado(self) -> EstadoDaPlaca:
        return EstadoDaPlaca.de_json(self.chamar("estado"))
