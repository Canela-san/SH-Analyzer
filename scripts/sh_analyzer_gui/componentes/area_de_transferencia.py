"""A área de transferência com vários formatos de uma vez (a figura em PNG e em SVG, FG-09).

**A saída do aplicativo:** com o PySide6 6.12, um ``QMimeData`` criado no Python e deixado na área de transferência
derruba o processo quando a aplicação é destruída (medido em 19/11/2026: o *segmentation fault* na saída, até num
script de seis linhas, e nada muda largando a posse do objeto do lado Python). Antes de o interpretador sair
(``atexit``, que roda antes de a aplicação ser destruída), :func:`limpar_o_que_e_nosso` limpa a área de
transferência **se o que está nela ainda é o que o aplicativo pôs** (comparado pelo objeto C++): o que outro programa
copiou depois não é tocado. O preço: a figura copiada não fica na área de transferência depois de o aplicativo
fechar (no Linux, ela já só vivia com ele, a menos de um gerenciador de área de transferência).
"""

from __future__ import annotations

import atexit

import shiboken6
from PySide6.QtCore import QByteArray, QMimeData
from PySide6.QtGui import QGuiApplication, QImage

_nosso: int | None = None          # o ponteiro C++ do QMimeData que o aplicativo pôs
_registrado = False


def copiar(formatos: dict[str, bytes], imagem: QImage | None = None) -> None:
    """Põe ``formatos`` (tipo MIME -> bytes) e, se houver, ``imagem`` (a que os programas leem como imagem) na área
    de transferência."""
    global _nosso, _registrado
    conteudo = QMimeData()
    if imagem is not None:
        conteudo.setImageData(imagem)
    for tipo, dados in formatos.items():
        conteudo.setData(tipo, QByteArray(dados))
    QGuiApplication.clipboard().setMimeData(conteudo)
    _nosso = shiboken6.getCppPointer(conteudo)[0]
    if not _registrado:
        atexit.register(limpar_o_que_e_nosso)
        _registrado = True


def limpar_o_que_e_nosso() -> None:
    global _nosso
    if _nosso is None or QGuiApplication.instance() is None:
        return
    area = QGuiApplication.clipboard()
    atual = area.mimeData()
    if atual is not None and shiboken6.getCppPointer(atual)[0] == _nosso:
        area.clear()
    _nosso = None
