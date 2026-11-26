"""O ponto de encontro entre os gráficos e o caderno de notas (``componentes/caderno_de_notas.py``): uma vista pede
para pôr uma referência ou um texto no caderno, e o caderno pede para ir até uma referência. A janela liga os dois;
quem pede não precisa saber se o caderno está aberto."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class CentralDoCaderno(QObject):
    referenciaPedida = Signal(object)        # dados.notas.Referencia: pôr no caderno, no cursor
    textoPedido = Signal(str)                # um trecho de Markdown para pôr no caderno (a imagem de uma vista)
    irPedido = Signal(object)                # Referencia: o clique numa referência do caderno


_central: CentralDoCaderno | None = None


def central() -> CentralDoCaderno:
    global _central
    if _central is None:
        _central = CentralDoCaderno()
    return _central
