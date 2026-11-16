"""Onde está uma placa (o host, a porta, o usuário e o salto) e como isso é gravado. Só a biblioteca padrão: as
preferências da interface guardam as placas conhecidas sem precisar do asyncssh, que só a conexão usa."""

from __future__ import annotations

from dataclasses import dataclass

SENHA_PADRAO_DA_IMAGEM = "temppwd"
"""A senha do usuário ``debian`` (o usuário padrão do :class:`Destino`) nas imagens da BeagleBoard: todo mundo a
conhece, e a primeira conexão sugere trocá-la (docs/gui-plan.md, 11.3)."""


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
    def de_texto(cls, texto: str, porta: int = 22, usuario: str = "debian", salto: Destino | None = None) -> Destino:
        """O que o usuário digita no campo do endereço: ``192.168.6.2``, ``beaglebone.local``, ``debian@10.0.0.5``,
        ``10.0.0.5:2222``, ``lab@[fe80::1]:22``. O usuário e a porta escritos no texto valem mais que ``usuario`` e
        ``porta``. ``ValueError`` com a mensagem pronta para mostrar."""
        texto = texto.strip()
        if "@" in texto:
            usuario, texto = texto.rsplit("@", 1)
        if texto.startswith("["):                       # [IPv6]:porta
            fim = texto.find("]")
            if fim < 0:
                raise ValueError("falta o ] do endereço IPv6")
            host, resto = texto[1:fim], texto[fim + 1:]
            if resto:
                if not resto.startswith(":"):
                    raise ValueError(f"o que vem depois do endereço não é uma porta: {resto!r}")
                porta = _porta(resto[1:])
        elif texto.count(":") == 1:                     # host:porta (um IPv6 sem colchetes tem vários ':')
            host, numero = texto.split(":")
            porta = _porta(numero)
        else:
            host = texto
        if not host:
            raise ValueError("escreva o endereço da placa (um IP, como 192.168.6.2, ou um nome, como beaglebone.local)")
        if any(c.isspace() for c in host) or "/" in host:
            raise ValueError(f"o endereço não pode ter espaços nem barras: {host!r}")
        usuario = usuario.strip()
        if not usuario or any(c.isspace() for c in usuario):
            raise ValueError(f"usuário inválido: {usuario!r}")
        if not 0 < int(porta) < 65536:
            raise ValueError(f"porta inválida: {porta} (de 1 a 65535)")
        return cls(host, int(porta), usuario, salto)

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


def _porta(texto: str) -> int:
    try:
        return int(texto)
    except ValueError:
        raise ValueError(f"a porta tem de ser um número: {texto!r}") from None
