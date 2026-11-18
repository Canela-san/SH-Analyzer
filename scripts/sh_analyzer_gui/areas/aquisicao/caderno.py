"""O caderno de bancada na seção Capturar (a coluna da direita do B2; a F4.5): as entradas do dia, a mais nova em
cima, o "Escrever uma nota…" (Enter grava) e o "Abrir no editor" (o ``anotacoes.md`` no programa do sistema).

As entradas automáticas (a captura, a conferência, a transferência, a correção) chegam pelo serviço
(``servicos/caderno.py``), ligado aos outros em ``entradas_do_caderno.py``. A coluna se esconde pelo "x" do topo e
volta pelo "Caderno" do título da seção (lembrado nas preferências): numa tela estreita, o centro fica com a largura.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ...componentes.basicos import Botao
from ...componentes.caderno import ListaDoCaderno
from ...servicos.caderno import CadernoDaSessao
from .pecas import fonte, repolir
from .textos import traduzir

LARGURA_DO_CADERNO = 300


class CadernoDeBancada(QFrame):
    """``esconderPedido``: o "x" do topo (quem mostra a coluna a esconde)."""

    esconderPedido = Signal()

    def __init__(self, caderno: CadernoDaSessao, abrir_url: Callable[[QUrl], object] = QDesktopServices.openUrl,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("caderno_de_bancada")
        self.setFixedWidth(LARGURA_DO_CADERNO)
        self.caderno, self.abrir_url = caderno, abrir_url
        titulo = QLabel(traduzir("Caderno de bancada"))
        titulo.setObjectName("titulo_do_caderno")
        titulo.setFont(fonte("corpo"))
        self.abrir = Botao("", "fantasma", "pagina")
        self.abrir.setObjectName("abrir_o_caderno")
        self.abrir.setToolTip(traduzir("Abrir o anotacoes.md no editor"))
        self.abrir.clicked.connect(self.abrir_no_editor)
        self.esconder = Botao("", "fantasma", "x")
        self.esconder.setObjectName("esconder_o_caderno")
        self.esconder.setToolTip(traduzir("Esconder o caderno"))
        self.esconder.clicked.connect(self.esconderPedido.emit)
        topo = QHBoxLayout()
        topo.setContentsMargins(14, 10, 8, 6)
        topo.setSpacing(2)
        topo.addWidget(titulo)
        topo.addStretch(1)
        topo.addWidget(self.abrir)
        topo.addWidget(self.esconder)
        self.lista = ListaDoCaderno(traduzir(
            "Nada ainda nesta sessão. As capturas, as conferências, as transferências e as correções entram "
            "sozinhas; escreva aqui o que mudou na bancada."))
        self.erro = QLabel()
        self.erro.setObjectName("problema_erro")
        self.erro.setWordWrap(True)
        self.erro.setVisible(False)
        self.nota = QLineEdit()
        self.nota.setObjectName("nota_do_caderno")
        self.nota.setPlaceholderText(traduzir("Escrever uma nota…"))
        self.nota.returnPressed.connect(self.anotar)
        self.onde = QLabel()
        self.onde.setObjectName("texto_mudo")
        self.onde.setFont(fonte("legenda"))
        self.onde.setWordWrap(True)
        baixo = QVBoxLayout()
        baixo.setContentsMargins(12, 8, 12, 12)
        baixo.setSpacing(6)
        baixo.addWidget(self.erro)
        baixo.addWidget(self.nota)
        baixo.addWidget(self.onde)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(0)
        coluna.addLayout(topo)
        coluna.addWidget(self.lista, 1)
        coluna.addLayout(baixo)
        caderno.mudou.connect(self._mudou)
        self._mudou()

    def anotar(self) -> None:
        texto = self.nota.text().strip()
        if not texto:
            return
        if self.caderno.anotar(texto):
            self.nota.clear()

    def abrir_no_editor(self) -> None:
        if self.caderno.garantir_o_arquivo():
            self.abrir_url(QUrl.fromLocalFile(str(self.caderno.caminho)))

    def _mudou(self) -> None:
        c = self.caderno
        self.lista.definir(c.entradas)
        self.erro.setText(c.erro)
        self.erro.setVisible(bool(c.erro))
        repolir(self.erro)
        self.onde.setText(traduzir("{} em {}").format(c.caminho.name, c.caminho.parent))
        self.onde.setToolTip(str(c.caminho))
