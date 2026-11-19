"""A seção Exportar das propriedades da figura (a F5.4; o fim da coluna da direita no F1): o formato, o dpi, as
opções (o texto editável do SVG, as curvas rasterizadas, todos os pontos) e os botões de exportar e de copiar.

A seção só monta o pedido (``OpcoesDeExportacao``) e o mostra: quem exporta é a área (numa tarefa, com o progresso).
O que não pode sair diz o porquê ali mesmo (o dpi acima do que a página aguenta, o PGF sem LaTeX), e "todos os
pontos" diz quantos vão, com o aviso do tamanho acima de 2 M.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QSpinBox, QWidget

from ...componentes.basicos import Botao, Segmentado
from ...componentes.numeros import formatar_si
from ...dados import exportar_figura as ex
from ...dados.exportar_figura import OpcoesDeExportacao, OpcoesInvalidas
from ...dados.figura import Figura

FORMATOS = tuple(ex.FORMATOS)


class SecaoDeExportacao(QFrame):
    exportarPedido = Signal(object)          # OpcoesDeExportacao
    copiarPedido = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("secao_da_figura")
        self.figura: Figura | None = None
        self.contar_pontos: Callable[[], int] | None = None      # a área dá (os dados vêm do projeto)
        self._ocupada = False
        self._dpi_por_formato = {f: ex.FORMATOS[f].dpi_padrao for f in FORMATOS}

        titulo = QLabel(self.tr("Exportar"))
        titulo.setObjectName("titulo_da_secao_da_figura")
        self.formato = Segmentado([ex.FORMATOS[f].nome for f in FORMATOS])
        self.formato.setObjectName("formato_da_exportacao")
        self.formato.escolhaMudou.connect(self._formato_mudou)
        self.descricao = QLabel()
        self.descricao.setObjectName("rotulo_da_propriedade")
        self.descricao.setWordWrap(True)
        self.dpi = QSpinBox()
        self.dpi.setObjectName("dpi_da_exportacao")
        self.dpi.setRange(150, int(ex.DPI_MAXIMO))
        self.dpi.setSingleStep(50)
        self.dpi.setSuffix(" dpi")
        self.dpi.setKeyboardTracking(False)
        self.dpi.valueChanged.connect(self._dpi_mudou)
        self.texto_editavel = QCheckBox(self.tr("Texto editável"))
        self.texto_editavel.setObjectName("texto_editavel")
        self.texto_editavel.setChecked(True)
        self.texto_editavel.setToolTip(self.tr("O texto como texto (editável no Inkscape); desmarcado, como curvas"))
        self.rasterizar = QCheckBox(self.tr("Rasterizar as curvas densas"))
        self.rasterizar.setObjectName("rasterizar_curvas")
        self.rasterizar.setToolTip(self.tr("As curvas como imagem no dpi escolhido; os eixos e o texto continuam "
                                           "vetoriais (o arquivo de uma captura longa fica leve)"))
        self.todos = QCheckBox(self.tr("Todos os pontos"))
        self.todos.setObjectName("todos_os_pontos")
        self.todos.setToolTip(self.tr("Sem a redução pelo M4: cada amostra da janela vira um ponto"))
        for caixa in (self.texto_editavel, self.rasterizar, self.todos):
            caixa.toggled.connect(self._atualizar)
        self.aviso = QLabel()
        self.aviso.setObjectName("aviso_da_exportacao")
        self.aviso.setWordWrap(True)
        self.exportar = Botao(self.tr("Exportar figura…"), "primario", "baixar")
        self.exportar.setObjectName("exportar_figura")
        self.exportar.clicked.connect(lambda: (o := self.opcoes()) is not None and self.exportarPedido.emit(o))
        self.copiar = Botao("", "secundario", "copiar")
        self.copiar.setObjectName("copiar_figura")
        self.copiar.setToolTip(self.tr("Copiar a figura (PNG e SVG) para a área de transferência"))
        self.copiar.clicked.connect(self.copiarPedido)

        grade = QGridLayout(self)
        grade.setContentsMargins(0, 8, 0, 10)
        grade.setHorizontalSpacing(10)
        grade.setVerticalSpacing(6)
        grade.addWidget(titulo, 0, 0, 1, 2)
        grade.addWidget(self.formato, 1, 0, 1, 2)
        grade.addWidget(self.descricao, 2, 0, 1, 2)
        rotulo = QLabel(self.tr("Resolução"))
        rotulo.setObjectName("rotulo_da_propriedade")
        grade.addWidget(rotulo, 3, 0)
        grade.addWidget(self.dpi, 3, 1)
        grade.addWidget(self.texto_editavel, 4, 0, 1, 2)
        grade.addWidget(self.rasterizar, 5, 0, 1, 2)
        grade.addWidget(self.todos, 6, 0, 1, 2)
        grade.addWidget(self.aviso, 7, 0, 1, 2)
        botoes = QHBoxLayout()
        botoes.addWidget(self.exportar, 1)
        botoes.addWidget(self.copiar)
        grade.addLayout(botoes, 8, 0, 1, 2)
        grade.setColumnStretch(1, 1)
        self._sem_latex = ex.sistema_do_latex() is None
        if self._sem_latex:
            self.formato.habilitar(FORMATOS.index("pgf"), False,
                                   self.tr("O PGF precisa de um LaTeX instalado (xelatex, lualatex ou pdflatex)"))
        self._formato_mudou(0)

    # ------------------------------------------------------------------ o estado

    @property
    def id_do_formato(self) -> str:
        return FORMATOS[self.formato.escolhida]

    def mostrar(self, figura: Figura | None) -> None:
        self.figura = figura
        self._atualizar()

    def definir_ocupada(self, ocupada: bool, texto: str = "") -> None:
        """Uma exportação em curso: os botões esperam, e o aviso diz o andamento."""
        self._ocupada = ocupada
        self._atualizar()
        if texto:
            self._avisar(texto, "info")

    def opcoes(self) -> OpcoesDeExportacao | None:
        """O pedido como está (``None``: um que não vale, com a razão no aviso)."""
        try:
            opcoes = OpcoesDeExportacao(self.id_do_formato, float(self.dpi.value()),
                                        texto_editavel=self.texto_editavel.isChecked(),
                                        rasterizar_curvas=self.rasterizar.isChecked(),
                                        todos_os_pontos=self.todos.isChecked())
            if self.figura is not None:
                ex.conferir(self.figura, opcoes)
        except OpcoesInvalidas as erro:
            self._avisar(str(erro).capitalize(), "erro")
            return None
        return opcoes

    def _formato_mudou(self, _indice: int) -> None:
        f = ex.FORMATOS[self.id_do_formato]
        self.descricao.setText(f.descricao)
        self.dpi.blockSignals(True)
        self.dpi.setMinimum(int(f.dpi_minimo))
        self.dpi.setValue(int(self._dpi_por_formato[f.id]))
        self.dpi.blockSignals(False)
        self.dpi.setToolTip(self.tr("O dpi da imagem") if not f.vetorial else self.tr(
            "A resolução do dispositivo final: as curvas são reduzidas nela (2 colunas por pixel), e as rasterizadas "
            "saem nela"))
        self._atualizar()

    def _dpi_mudou(self, valor: int) -> None:
        self._dpi_por_formato[self.id_do_formato] = float(valor)
        self._atualizar()

    def _atualizar(self, *_a) -> None:
        f = ex.FORMATOS[self.id_do_formato]
        self.texto_editavel.setVisible(f.id == "svg")
        self.rasterizar.setVisible(f.vetorial)
        pode = self.figura is not None and not self._ocupada
        self.exportar.setEnabled(pode)
        self.copiar.setEnabled(pode)
        if self._ocupada:
            return
        self._avisar("", "info")
        if self.figura is None:
            return
        if self.opcoes() is None:
            self.exportar.setEnabled(False)
            return
        if self.todos.isChecked() and self.contar_pontos is not None:
            n = self.contar_pontos()
            texto = self.tr("{} pontos na figura").format(formatar_si(n, "", 3))
            if n > ex.LIMITE_DE_PONTOS:
                self._avisar(texto + self.tr(": o arquivo fica grande e lento de abrir (rasterizar as curvas "
                                             "resolve)"), "aviso")
            else:
                self._avisar(texto, "info")

    def _avisar(self, texto: str, nivel: str) -> None:
        self.aviso.setText(texto)
        self.aviso.setProperty("nivel", nivel)
        self.aviso.setVisible(bool(texto))
        self.aviso.style().unpolish(self.aviso)
        self.aviso.style().polish(self.aviso)


__all__ = ["SecaoDeExportacao"]
