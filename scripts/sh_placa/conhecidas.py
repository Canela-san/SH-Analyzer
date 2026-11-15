"""As placas conhecidas (docs/gui-plan.md, 11.3): as em que o usuário já conectou, lembradas pelo nº de série da
EEPROM (o mesmo do cabeçalho v8 das capturas), com o nome, a chave de host e os endereços que funcionaram.

A descoberta (``descoberta.py``) as usa para dar nome a uma placa achada e para ligar o nº de série à chave de host
(uma placa achada pelo mDNS ou pela LAN só mostra a chave), e para listar a que não respondeu agora ("vista há…"). A
interface as guarda nas preferências, como JSON (``sh_analyzer_gui/preferencias.py``).

Tudo é imutável: :func:`lembrar` e :func:`esquecer` devolvem a lista nova (a descoberta roda no laço da placa, e a
interface lê e grava na thread dela). Só a biblioteca padrão.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from .destino import Destino

log = logging.getLogger(__name__)

DESTINOS_GUARDADOS = 5
"""Os endereços lembrados por placa (o último que funcionou primeiro): o USB, a LAN de casa, a do laboratório…"""


@dataclass(frozen=True)
class PlacaConhecida:
    serie: str
    nome: str
    impressao: str | None                 # a chave de host (SHA256:…), a mesma por qualquer caminho
    destinos: tuple[Destino, ...]
    vista_em: float                       # time.time() da última conexão

    def para_dict(self) -> dict:
        return {"serie": self.serie, "nome": self.nome, "impressao": self.impressao,
                "destinos": [d.para_dict() for d in self.destinos], "vista_em": self.vista_em}

    @classmethod
    def de_dict(cls, d: dict) -> PlacaConhecida:
        serie = d["serie"]
        if not isinstance(serie, str) or not serie:
            raise ValueError(f"nº de série inválido: {serie!r}")
        return cls(serie, str(d.get("nome") or serie), d.get("impressao") or None,
                   tuple(Destino.de_dict(x) for x in d.get("destinos") or ()), float(d.get("vista_em") or 0.0))


def lembrar(conhecidas: Sequence[PlacaConhecida], serie: str, nome: str, impressao: str | None,
            destino: Destino, quando: float | None = None) -> tuple[PlacaConhecida, ...]:
    """A lista com a placa de ``serie`` lembrada (ou atualizada): o nome, a chave de host, ``destino`` na frente dos
    outros endereços dela, e a hora."""
    quando = time.time() if quando is None else quando
    anterior = next((p for p in conhecidas if p.serie == serie), None)
    destinos = (destino, *(d for d in (anterior.destinos if anterior else ()) if d != destino))[:DESTINOS_GUARDADOS]
    nova = PlacaConhecida(serie, nome, impressao, destinos, quando) if anterior is None else \
        replace(anterior, nome=nome, impressao=impressao or anterior.impressao, destinos=destinos, vista_em=quando)
    return (nova, *(p for p in conhecidas if p.serie != serie))


def esquecer(conhecidas: Sequence[PlacaConhecida], serie: str) -> tuple[PlacaConhecida, ...]:
    return tuple(p for p in conhecidas if p.serie != serie)


def para_lista(conhecidas: Iterable[PlacaConhecida]) -> list[dict]:
    return [p.para_dict() for p in conhecidas]


def de_lista(dados: object) -> tuple[PlacaConhecida, ...]:
    """As placas de uma lista gravada; uma estragada (um arquivo editado à mão, de outra versão) fica de fora, com um
    aviso no log, e as outras valem."""
    placas = []
    for d in dados if isinstance(dados, list) else ():
        try:
            placas.append(PlacaConhecida.de_dict(d))
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            log.warning("uma placa conhecida gravada não deu para ler (%s): %r", e, d)
    return tuple(placas)
