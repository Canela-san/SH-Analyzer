"""A seção "Espectro" do inspetor: as opções de análise da vista de espectro ativa que não cabem na barra dela, e os
presets (``dados/espectros.py``: por enquanto, o da IEC 61000-4-7).

* **A janela** (a da ``api``: retangular, Hann, Blackman-Harris, flat-top, Kaiser, ou a padrão do método).
* **Os ciclos** da FFT sincronizada: os N primeiros ciclos inteiros do trecho, a partir do primeiro cruzamento por
  zero; "todos" usa o trecho inteiro. No Welch, não valem (o campo fica desligado).
* **Os presets**, um cartão cada: o nome, o que ele põe (com a fundamental medida no último espectro: 10 ou 12
  ciclos) e "Aplicar"; com as opções já as dele, o cartão diz "Aplicado".

As opções são da vista (todos os traços dela usam as mesmas). Cada mudança é um ``MudarOpcoesDaVista``: desfaz com
Ctrl+Z, como a barra da vista.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QWidget
from shiboken6 import isValid

from ...componentes.basicos import Botao
from ...dados import espectros as esp
from ...modelo.comandos import MudarOpcoesDaVista
from ...modelo.objetos import Projeto, Vista
from ...tema.tokens import TAMANHOS


class CartaoDoPreset(QFrame):
    def __init__(self, preset: esp.PresetDoEspectro, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("cartao")
        self.preset = preset
        self.setToolTip(preset.dica)
        titulo = QLabel(preset.nome)
        titulo.setObjectName("titulo_preset")
        fonte = titulo.font()
        fonte.setBold(True)
        titulo.setFont(fonte)
        self.descricao = QLabel()
        self.descricao.setObjectName("rotulo")
        self.descricao.setWordWrap(True)
        self.aplicar = Botao(self.tr("Aplicar"))
        self.aplicar.setObjectName("aplicar_preset")
        topo = QHBoxLayout()
        topo.setSpacing(8)
        topo.addWidget(titulo, 1)
        topo.addWidget(self.aplicar)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(10, 8, 8, 8)
        coluna.setSpacing(4)
        coluna.addLayout(topo)
        coluna.addWidget(self.descricao)

    def mostrar(self, segue: bool, f1_hz: float | None) -> None:
        self.descricao.setText(self.preset.descricao(f1_hz))
        self.aplicar.setEnabled(not segue)
        self.aplicar.setText(self.tr("Aplicado") if segue else self.tr("Aplicar"))


class SecaoDoEspectro(QWidget):
    """``largura_do_rotulo``: a da coluna dos rótulos, para alinhar com as outras seções do inspetor."""

    def __init__(self, largura_do_rotulo: int = 0, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("secao_espectro")
        self.projeto: Projeto | None = None
        self.vista: Vista | None = None
        self._f1: Callable[[], float | None] = lambda: None

        self.janela = QComboBox()
        self.janela.setObjectName("janela_espectro")
        for nome, rotulo in esp.JANELAS.items():
            self.janela.addItem(rotulo, nome)
        self.janela.setItemData(0, self.tr("A retangular na FFT sincronizada (os harmônicos caem exatamente nos bins); "
                                           "a Hann no Welch e na FFT sem sincronizar"), Qt.ItemDataRole.ToolTipRole)
        self.janela.activated.connect(self._janela_escolhida)
        self.ciclos = QSpinBox()
        self.ciclos.setObjectName("ciclos_espectro")
        self.ciclos.setRange(0, esp.MAXIMO_DE_CICLOS)
        self.ciclos.setSpecialValueText(self.tr("todos"))         # o 0: o trecho inteiro
        self.ciclos.setKeyboardTracking(False)
        self._dica_dos_ciclos = self.tr("A FFT sincronizada só nos N primeiros ciclos inteiros do trecho, a partir do "
                                        "primeiro cruzamento por zero (o --fft N da CLI)")
        self.ciclos.valueChanged.connect(self._ciclos_mudaram)
        campos = QGridLayout()
        campos.setContentsMargins(0, 0, 0, 0)
        campos.setHorizontalSpacing(8)
        campos.setVerticalSpacing(6)
        for linha, (rotulo, campo) in enumerate(((self.tr("Janela"), self.janela), (self.tr("Ciclos"), self.ciclos))):
            texto = QLabel(rotulo)
            texto.setObjectName("rotulo_campo")
            fonte = texto.font()
            fonte.setPixelSize(TAMANHOS["secundario"])
            texto.setFont(fonte)
            campos.addWidget(texto, linha, 0, Qt.AlignmentFlag.AlignVCenter)
            campos.addWidget(campo, linha, 1)
        campos.setColumnMinimumWidth(0, largura_do_rotulo)
        campos.setColumnStretch(1, 1)
        self.cartoes = [CartaoDoPreset(p) for p in esp.PRESETS_DO_ESPECTRO]
        self.acoes: list[QAction] = []                 # para a paleta de comandos
        for cartao in self.cartoes:
            cartao.aplicar.clicked.connect(lambda _=False, p=cartao.preset: self.aplicar(p))
            acao = QAction(self.tr("Aplicar o preset {} ao espectro").format(cartao.preset.nome), self)
            acao.setToolTip(cartao.preset.dica)
            acao.triggered.connect(lambda _=False, p=cartao.preset: self.aplicar(p))
            self.acoes.append(acao)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(8)
        coluna.addLayout(campos)
        for cartao in self.cartoes:
            coluna.addWidget(cartao)

    # ------------------------------------------------------------------ a vista

    def mostrar(self, projeto: Projeto | None, vista: Vista | None, f1: Callable[[], float | None] | None = None) -> None:
        """As opções de ``vista`` (de espectro); ``f1()`` dá a fundamental do último espectro dela (ou None)."""
        if self.vista is not vista:
            if self.vista is not None and isValid(self.vista):
                self.vista.mudou.disconnect(self._vista_mudou)
            if vista is not None:
                vista.mudou.connect(self._vista_mudou)
        self.projeto, self.vista = projeto, vista
        self._f1 = f1 or (lambda: None)
        self.atualizar()

    def _vista_mudou(self, _vista, campos) -> None:
        if "opcoes" in campos and isValid(self):
            self.atualizar()

    def atualizar(self) -> None:
        """Os campos e os cartões nas opções de agora (outra conta trouxe outra fundamental, um desfazer)."""
        if self.vista is None:
            return
        o = self.vista.opcoes
        self.janela.setCurrentIndex(max(0, self.janela.findData(o.janela)))
        self.ciclos.blockSignals(True)
        self.ciclos.setValue(o.ciclos or 0)
        self.ciclos.blockSignals(False)
        fft = o.metodo == "fft"
        self.ciclos.setEnabled(fft)
        self.ciclos.setToolTip(self._dica_dos_ciclos if fft else self.tr("Os ciclos valem só na FFT sincronizada"))
        f1 = self._f1()
        for cartao in self.cartoes:
            cartao.mostrar(cartao.preset.segue(o, f1), f1)

    # ------------------------------------------------------------------ as mudanças

    def _mudar(self, opcoes, texto: str) -> None:
        if self.vista is None or self.projeto is None or opcoes == self.vista.opcoes:
            return
        self.projeto.pilha.push(MudarOpcoesDaVista(self.vista, opcoes, texto=texto))

    def _janela_escolhida(self, indice: int) -> None:
        if self.vista is not None:
            self._mudar(self.vista.opcoes.com(janela=self.janela.itemData(indice)),
                        self.tr("Janela {}").format(self.janela.itemText(indice)))

    def _ciclos_mudaram(self, valor: int) -> None:
        if self.vista is not None:
            self._mudar(self.vista.opcoes.com(ciclos=valor or None),
                        self.tr("Ciclos da FFT: {}").format(valor or self.tr("todos")))

    def aplicar(self, preset: esp.PresetDoEspectro) -> None:
        if self.vista is not None:
            self._mudar(preset.aplicar(self.vista.opcoes, self._f1()), self.tr("Aplicar a {}").format(preset.nome))
