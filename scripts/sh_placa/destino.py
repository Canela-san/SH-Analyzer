"""Onde está uma placa (o host, a porta, o usuário e o salto) e como isso é gravado. Só a biblioteca padrão: as
preferências da interface guardam as placas conhecidas sem precisar do asyncssh, que só a conexão usa."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Destino:
    """Onde está a placa: o host (ou IP), a porta, o usuário e, se for o caso, o salto (*ProxyJump*)."""

    host: str
    porta: int = 22
    usuario: str = "debian"
    salto: Destino | None = None

    @property
    def conta(self) -> str:
        """``debian@192.168.6.2`` (com a porta, fora da 22): a chave do cofre e o nome no registro."""
        return f"{self.usuario}@{self.host}" + ("" if self.porta == 22 else f":{self.porta}")

    def __str__(self) -> str:
        return self.conta if self.salto is None else f"{self.conta} (pelo salto {self.salto})"

    def para_dict(self) -> dict:
        return {"host": self.host, "porta": self.porta, "usuario": self.usuario,
                "salto": self.salto.para_dict() if self.salto is not None else None}

    @classmethod
    def de_dict(cls, d: dict) -> Destino:
        """O contrário do :meth:`para_dict`; ``KeyError``, ``TypeError`` ou ``ValueError`` num dado estragado."""
        host = d["host"]
        if not isinstance(host, str) or not host:
            raise ValueError(f"host inválido: {host!r}")
        porta = int(d.get("porta", 22))
        if not 0 < porta < 65536:
            raise ValueError(f"porta inválida: {porta}")
        salto = d.get("salto")
        return cls(host, porta, str(d.get("usuario") or "debian"), cls.de_dict(salto) if salto else None)
