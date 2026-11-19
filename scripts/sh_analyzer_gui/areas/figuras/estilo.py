"""A seção Estilo das propriedades da figura (F5.7; FG-02 e FG-04): o estilo da figura inteira (a fonte, os
tamanhos em pt, as espessuras, as marcas, a moldura e a grade) e os modelos de estilo.

* **Cada campo** é um passo de desfazer; girar um número junta os passos seguidos do mesmo campo.
* **Os modelos de estilo** ficam nas preferências (``preferencias.py``: valem em qualquer projeto). "Salvar…" guarda
  o estilo da figura com um nome (um de mesmo nome é trocado); escolher um modelo na lista o aplica à figura (um
  passo de desfazer), e o primeiro da lista é sempre o da página da figura (o estilo com que ela nasceu). O menu ao
  lado apaga um modelo.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ... import preferencias
from ...componentes.basicos import Botao, Segmentado
from ...dados import figura as fig
from ...dados.figura import Estilo, Figura, FiguraInvalida, ModeloDeEstilo
from ...tema.icones import IconeDoTema
from .secoes import Tentar, campo_decimal, secao

TAMANHOS = (("texto_pt", "Textos"), ("marcas_pt", "Números"), ("rotulo_do_painel_pt", "Rótulo (a)"),
            ("legenda_pt", "Legenda"))


class SecaoDoEstilo(QWidget):
    def __init__(self, tentar: Tentar, parent: QWidget | None = None):
        super().__init__(parent)
        self.tentar = tentar
        self.figura: Figura | None = None
        self._enchendo = False
        self.pedir_nome = self._pedir_nome            # os testes trocam (o diálogo do sistema)

        self.modelo = QComboBox()
        self.modelo.setObjectName("modelo_de_estilo")
        self.modelo.setToolTip(self.tr("Aplicar à figura um estilo salvo, ou o da página dela"))
        self.modelo.activated.connect(self._aplicar)
        self.salvar = Botao(self.tr("Salvar o estilo…"), "secundario", "disco")
        self.salvar.setObjectName("salvar_o_estilo")
        self.salvar.setToolTip(self.tr("Guardar o estilo desta figura com um nome, para aplicá-lo em outras"))
        self.salvar.clicked.connect(self._salvar)
        self.apagar = QToolButton()
        self.apagar.setObjectName("apagar_um_estilo")
        self.apagar.setToolTip(self.tr("Apagar um modelo de estilo"))
        self.apagar.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        IconeDoTema(self.apagar, "x")
        self.apagar.setMenu(QMenu(self.apagar))
        botoes = QHBoxLayout()
        botoes.setSpacing(6)
        botoes.addWidget(self.salvar)
        botoes.addWidget(self.apagar)
        botoes.addStretch(1)

        self.familia = QComboBox()
        self.familia.setObjectName("familia_da_figura")
        self.familia.addItems(list(fig.FAMILIAS))
        self.familia.activated.connect(lambda _i: self._mudar(familia=self.familia.currentText(),
                                                              texto=self.tr("Trocar a fonte")))
        self.tamanhos = {}
        linhas = [(self.tr("Modelo"), self.modelo), ("", botoes), (self.tr("Fonte"), self.familia)]
        for nome, rotulo in TAMANHOS:
            campo = campo_decimal("pt", *fig.TAMANHO_PT, 0.5)
            campo.setObjectName(f"estilo_{nome}")
            campo.setFixedWidth(84)
            campo.valueChanged.connect(lambda v, n=nome, r=rotulo: self._mudar(
                juntar=True, texto=self.tr("Mudar o tamanho: {}").format(r.lower()), **{n: v}))
            self.tamanhos[nome] = campo
            linhas.append((self.tr(rotulo), _sozinho(campo)))
        self.tamanhos["texto_pt"].setObjectName("texto_da_figura")
        self.linha_pt = campo_decimal("pt", *fig.ESPESSURA_PT, 0.1, casas=2)
        self.linha_pt.setObjectName("estilo_linha_pt")
        self.eixo_pt = campo_decimal("pt", *fig.ESPESSURA_PT, 0.1, casas=2)
        self.eixo_pt.setObjectName("estilo_eixo_pt")
        espessuras = QHBoxLayout()
        espessuras.setSpacing(6)
        for rotulo, campo, nome in ((self.tr("traços"), self.linha_pt, "linha_pt"),
                                    (self.tr("eixos"), self.eixo_pt, "eixo_pt")):
            campo.setFixedWidth(84)
            campo.valueChanged.connect(lambda v, n=nome: self._mudar(juntar=True, texto=self.tr("Mudar a espessura"),
                                                                     **{n: v}))
            dica = QLabel(rotulo)
            dica.setObjectName("rotulo_da_propriedade")
            coluna = QVBoxLayout()
            coluna.setSpacing(2)
            coluna.addWidget(campo)
            coluna.addWidget(dica)
            espessuras.addLayout(coluna)
        espessuras.addStretch(1)
        self.marcas = Segmentado([self.tr("Para dentro"), self.tr("Para fora")])
        self.marcas.setObjectName("marcas_da_figura")
        self.marcas.setProperty("compacto", True)
        self.marcas.escolhaMudou.connect(lambda i: self._mudar(marcas_para_dentro=i == 0,
                                                               texto=self.tr("Mudar as marcas")))
        self.moldura = QCheckBox(self.tr("Os quatro lados"))
        self.moldura.setObjectName("moldura_da_figura")
        self.moldura.setToolTip(self.tr("A moldura inteira, com as marcas nos quatro lados; desligada, só os eixos "
                                        "de baixo e da esquerda"))
        self.moldura.toggled.connect(lambda v: self._mudar(moldura=v, texto=self.tr("Mudar a moldura")))
        self.grade = QCheckBox(self.tr("Grade"))
        self.grade.setObjectName("grade_da_figura")
        self.grade.toggled.connect(lambda v: self._mudar(grade=v, texto=self.tr("Mudar a grade")))
        moldura = QHBoxLayout()
        moldura.addWidget(self.moldura)
        moldura.addWidget(self.grade)
        moldura.addStretch(1)
        linhas += [(self.tr("Espessuras"), espessuras), (self.tr("Marcas"), self.marcas),
                   (self.tr("Moldura"), moldura)]
        for caixa in (self.modelo, self.familia):                     # os nomes longos não alargam o painel
            caixa.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            caixa.setMinimumContentsLength(8)
        self.quadro: QFrame = secao(self.tr("Estilo"), linhas)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.addWidget(self.quadro)

    # ------------------------------------------------------------------ mostrar

    def mostrar(self, figura: Figura | None) -> None:
        self.figura = figura
        if figura is None:
            return
        self._enchendo = True
        try:
            e = figura.estilo
            self.familia.setCurrentText(e.familia)
            for nome, campo in self.tamanhos.items():
                campo.setValue(getattr(e, nome))
            self.linha_pt.setValue(e.linha_pt)
            self.eixo_pt.setValue(e.eixo_pt)
            self.marcas.escolher(0 if e.marcas_para_dentro else 1)
            self.moldura.setChecked(e.moldura)
            self.grade.setChecked(e.grade)
            self._mostrar_os_modelos()
        finally:
            self._enchendo = False

    def _mostrar_os_modelos(self) -> None:
        figura = self.figura
        self.modelo.blockSignals(True)
        self.modelo.clear()
        self.modelo.addItem(self.tr("Aplicar um modelo…"), None)
        self.modelo.addItem(self.tr("O da página ({})").format(figura.pagina.nome), "")
        salvos = preferencias.modelos_de_estilo()
        for m in salvos:
            self.modelo.addItem(m.nome + (" ✓" if m.estilo == figura.estilo else ""), m.nome)
        self.modelo.setCurrentIndex(0)
        self.modelo.blockSignals(False)
        menu = self.apagar.menu()
        menu.clear()
        for m in salvos:
            menu.addAction(m.nome, lambda nome=m.nome: self.apagar_modelo(nome))
        self.apagar.setEnabled(bool(salvos))

    # ------------------------------------------------------------------ mudar

    def _mudar(self, *, texto: str, juntar: bool = False, **campos) -> None:
        if self._enchendo or self.figura is None:
            return
        self.tentar(lambda: self.figura.com(estilo=replace(self.figura.estilo, **campos)), texto, juntar)

    def aplicar_estilo(self, estilo: Estilo, nome: str) -> None:
        if self.figura is not None and estilo != self.figura.estilo:
            self.tentar(lambda: self.figura.com(estilo=estilo), self.tr("Aplicar o estilo {}").format(nome), False)

    def _aplicar(self, indice: int) -> None:
        nome = self.modelo.itemData(indice)
        self.modelo.setCurrentIndex(0)
        if nome is None or self.figura is None:
            return
        if nome == "":
            self.aplicar_estilo(self.figura.pagina.estilo, self.figura.pagina.nome)
            return
        modelo = next((m for m in preferencias.modelos_de_estilo() if m.nome == nome), None)
        if modelo is not None:
            self.aplicar_estilo(modelo.estilo, modelo.nome)

    def _salvar(self) -> None:
        if self.figura is None:
            return
        nome = self.pedir_nome(self.tr("Salvar o estilo"), self.tr("O nome do modelo de estilo:"), "")
        if nome is not None and nome.strip():
            self.guardar_modelo(nome.strip())

    def guardar_modelo(self, nome: str) -> None:
        try:
            preferencias.guardar_modelo_de_estilo(ModeloDeEstilo(nome, self.figura.estilo))
        except FiguraInvalida as erro:
            self.salvar.setToolTip(str(erro))
            return
        self._mostrar_os_modelos()

    def apagar_modelo(self, nome: str) -> None:
        preferencias.apagar_modelo_de_estilo(nome)
        if self.figura is not None:
            self._mostrar_os_modelos()

    def _pedir_nome(self, titulo: str, rotulo: str, texto: str) -> str | None:
        nome, ok = QInputDialog.getText(self.window(), titulo, rotulo, QLineEdit.EchoMode.Normal, texto)
        return nome if ok else None


def _sozinho(campo: QWidget) -> QHBoxLayout:
    """O campo sem esticar (um número curto não ocupa a largura toda)."""
    linha = QHBoxLayout()
    linha.addWidget(campo)
    linha.addStretch(1)
    return linha
