"""As propriedades da figura escolhida (a direita do F1): a página (o nome, o modelo, a altura, a fonte, os números),
a grade (as linhas, as colunas, os eixos compartilhados, pôr um painel) e o painel escolhido (a vista dele, ligado
ou congelado, o rótulo, tirá-lo).

Cada mudança sai como a figura nova (``mudar``), que a área empilha como um passo de desfazer (``MudarFigura``); a
altura e o tamanho da letra, girados, juntam os passos seguidos. Congelar pede a cópia da vista à área
(``congelarPedido``): ela é que conhece o projeto e o que a vista mostra.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...componentes.basicos import Botao, Segmentado
from ...componentes.numeros import separador_decimal
from ...dados import figura as fig
from ...dados.figura import Figura, FiguraInvalida, Painel
from .exportacao import SecaoDeExportacao

IDIOMAS = ("pt-BR", "en")
TIPOS = {"tempo": "tempo", "espectro": "espectro", "bandas": "bandas", "espectrograma": "espectrograma",
         "harmonicos": "harmônicos"}


def _local() -> QLocale:
    """Os números dos campos com o separador decimal do aplicativo."""
    local = QLocale(QLocale.Language.Portuguese, QLocale.Country.Brazil) if separador_decimal() == "," \
        else QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
    local.setNumberOptions(QLocale.NumberOption.OmitGroupSeparator)
    return local


def _campo_decimal(sufixo: str, minimo: float, maximo: float, passo: float) -> QDoubleSpinBox:
    campo = QDoubleSpinBox()
    campo.setLocale(_local())
    campo.setDecimals(1)
    campo.setRange(minimo, maximo)
    campo.setSingleStep(passo)
    campo.setSuffix(f" {sufixo}")
    campo.setKeyboardTracking(False)
    return campo


class PropriedadesDaFigura(QScrollArea):
    mudar = Signal(object, str, bool)          # a figura nova, o texto do passo, se junta com o anterior
    congelarPedido = Signal(str, bool)         # o painel, congelar (ou religar)
    acrescentarPedido = Signal()
    apagarPedido = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("propriedades_da_figura")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.figura: Figura | None = None
        self.painel: Painel | None = None
        self._vistas: list[tuple[str, str, str]] = []
        self._enchendo = False

        conteudo = QWidget()
        conteudo.setObjectName("conteudo_das_propriedades")
        self.coluna = QVBoxLayout(conteudo)
        self.coluna.setContentsMargins(16, 12, 16, 16)
        self.coluna.setSpacing(6)
        self.setWidget(conteudo)

        # A página
        self.nome = QLineEdit()
        self.nome.setObjectName("nome_da_figura")
        self.nome.editingFinished.connect(self._nome)
        self.modelo = QComboBox()
        self.modelo.setObjectName("modelo_da_figura")
        for m in fig.MODELOS:
            self.modelo.addItem(m.nome, m.id)
        self.modelo.activated.connect(self._modelo)
        self.largura = QLabel()
        self.largura.setObjectName("largura_da_figura")
        self.altura = _campo_decimal("mm", fig.ALTURA_MINIMA_MM, 1189.0, 1.0)
        self.altura.setObjectName("altura_da_figura")
        self.altura.valueChanged.connect(self._altura)
        self.familia = QComboBox()
        self.familia.setObjectName("familia_da_figura")
        self.familia.addItems(list(fig.FAMILIAS))
        self.familia.activated.connect(self._familia)
        self.texto_pt = _campo_decimal("pt", 4.0, 72.0, 0.5)
        self.texto_pt.setObjectName("texto_da_figura")
        self.texto_pt.setFixedWidth(76)
        self.texto_pt.valueChanged.connect(self._texto_pt)
        self.idioma = Segmentado([self.tr("1,5 (pt-BR)"), self.tr("1.5 (en)")])
        self.idioma.setObjectName("idioma_da_figura")
        self.idioma.escolhaMudou.connect(self._idioma)
        tamanho = QHBoxLayout()
        tamanho.setSpacing(6)
        tamanho.addWidget(self.largura)
        tamanho.addWidget(QLabel("×"))
        tamanho.addWidget(self.altura, 1)
        letra = QHBoxLayout()
        letra.addWidget(self.familia, 1)
        letra.addWidget(self.texto_pt)
        self._secao(self.tr("Página"), [(self.tr("Nome"), self.nome), (self.tr("Modelo"), self.modelo),
                                       (self.tr("Tamanho"), tamanho), (self.tr("Fonte"), letra),
                                       (self.tr("Números"), self.idioma)])

        # A grade
        self.linhas, self.colunas = QSpinBox(), QSpinBox()
        for nome, campo in (("linhas_da_grade", self.linhas), ("colunas_da_grade", self.colunas)):
            campo.setObjectName(nome)
            campo.setRange(1, fig.GRADE_MAXIMA)
            campo.setFixedWidth(56)
            campo.setKeyboardTracking(False)
            campo.valueChanged.connect(self._grade)
        self.eixo_x = QCheckBox(self.tr("x na coluna"))
        self.eixo_x.setObjectName("eixo_x_compartilhado")
        self.eixo_y = QCheckBox(self.tr("y na linha"))
        self.eixo_y.setObjectName("eixo_y_compartilhado")
        for caixa in (self.eixo_x, self.eixo_y):
            caixa.toggled.connect(self._eixos)
        self.acrescentar = Botao(self.tr("Pôr um painel"), "secundario", "mais")
        self.acrescentar.setObjectName("por_um_painel")
        self.acrescentar.clicked.connect(self.acrescentarPedido)
        grade = QHBoxLayout()
        grade.setSpacing(6)
        grade.addWidget(self.linhas)
        grade.addWidget(QLabel("×"))
        grade.addWidget(self.colunas)
        grade.addStretch(1)
        eixos = QHBoxLayout()
        eixos.addWidget(self.eixo_x)
        eixos.addWidget(self.eixo_y)
        eixos.addStretch(1)
        self._secao(self.tr("Grade"), [(self.tr("Linhas"), grade), (self.tr("Eixos juntos"), eixos),
                                      ("", self.acrescentar)])

        # O painel escolhido
        self.titulo_do_painel = QLabel()
        self.vista = QComboBox()
        self.vista.setObjectName("vista_do_painel")
        self.vista.activated.connect(self._vista)
        self.estado = Segmentado([self.tr("Ligado"), self.tr("Congelado")], icones=["link", "cadeado"])
        self.estado.setToolTip(self.tr("Ligado: acompanha a vista. Congelado: guarda a vista e a janela de agora."))
        self.estado.setObjectName("estado_do_painel")
        self.estado.escolhaMudou.connect(lambda i: self.painel is not None and self.congelarPedido.emit(
            self.painel.id, i == 1))
        self.rotulo = QLineEdit()
        self.rotulo.setObjectName("rotulo_do_painel")
        self.rotulo.editingFinished.connect(self._rotulo)
        self.sem_rotulo = QCheckBox(self.tr("Sem rótulo"))
        self.sem_rotulo.setObjectName("sem_rotulo")
        self.sem_rotulo.toggled.connect(self._rotulo)
        rotulo = QVBoxLayout()
        rotulo.setSpacing(4)
        rotulo.addWidget(self.rotulo)
        rotulo.addWidget(self.sem_rotulo)
        self.tirar = Botao(self.tr("Tirar o painel"), "fantasma", "x")
        self.tirar.setObjectName("tirar_o_painel")
        self.tirar.clicked.connect(self._tirar)
        self.secao_do_painel = self._secao(self.titulo_do_painel, [
            (self.tr("Vista"), self.vista), (self.tr("Estado"), self.estado), (self.tr("Rótulo"), rotulo),
            ("", self.tirar)])

        for caixa in (self.modelo, self.familia, self.vista):          # os nomes longos não alargam o painel
            caixa.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            caixa.setMinimumContentsLength(10)

        self.exportacao = SecaoDeExportacao()
        self.coluna.addWidget(self.exportacao)

        self.apagar = Botao(self.tr("Apagar a figura"), "fantasma", "x")
        self.apagar.setObjectName("apagar_a_figura")
        self.apagar.clicked.connect(self.apagarPedido)
        self.coluna.addSpacing(8)
        self.coluna.addWidget(self.apagar, 0, Qt.AlignmentFlag.AlignLeft)
        self.coluna.addStretch(1)

    def _secao(self, titulo: str | QLabel, linhas) -> QFrame:
        quadro = QFrame()
        quadro.setObjectName("secao_da_figura")
        grade = QGridLayout(quadro)
        grade.setContentsMargins(0, 8, 0, 10)
        grade.setHorizontalSpacing(10)
        grade.setVerticalSpacing(6)
        rotulo_do_titulo = titulo if isinstance(titulo, QLabel) else QLabel(titulo)
        rotulo_do_titulo.setObjectName("titulo_da_secao_da_figura")
        grade.addWidget(rotulo_do_titulo, 0, 0, 1, 2)
        for i, (nome, campo) in enumerate(linhas, start=1):
            rotulo = QLabel(nome)
            rotulo.setObjectName("rotulo_da_propriedade")
            grade.addWidget(rotulo, i, 0)
            if isinstance(campo, QWidget):
                grade.addWidget(campo, i, 1)
            else:
                grade.addLayout(campo, i, 1)
        grade.setColumnStretch(1, 1)
        self.coluna.addWidget(quadro)
        return quadro

    # ------------------------------------------------------------------ mostrar

    def mostrar(self, figura: Figura | None, painel: str | None, vistas: list[tuple[str, str, str]]) -> None:
        """A figura (``None``: nada escolhido), o painel escolhido e as vistas do projeto (id, nome, tipo)."""
        self.figura, self._vistas = figura, vistas
        self.painel = next((p for p in figura.paineis if p.id == painel), None) if figura is not None else None
        self.widget().setEnabled(figura is not None)
        self.exportacao.mostrar(figura)
        if figura is None:
            return
        self._enchendo = True
        try:
            self.nome.setText(figura.nome)
            self.modelo.setCurrentIndex(self.modelo.findData(figura.modelo))
            self.largura.setText(f"{figura.largura_mm:g} mm".replace(".", separador_decimal()))
            self.altura.setRange(fig.ALTURA_MINIMA_MM, figura.pagina.altura_maxima_mm)
            self.altura.setValue(figura.altura_mm)
            self.familia.setCurrentText(figura.estilo.familia)
            self.texto_pt.setValue(figura.estilo.texto_pt)
            self.idioma.escolher(IDIOMAS.index(figura.idioma))
            menor = fig.menor_grade(figura)
            self.linhas.setMinimum(menor[0])
            self.colunas.setMinimum(menor[1])
            self.linhas.setValue(figura.linhas)
            self.colunas.setValue(figura.colunas)
            self.eixo_x.setChecked(figura.eixos_x_compartilhados)
            self.eixo_y.setChecked(figura.eixos_y_compartilhados)
            self._mostrar_o_painel(figura)
        finally:
            self._enchendo = False

    def _mostrar_o_painel(self, figura: Figura) -> None:
        p = self.painel
        self.secao_do_painel.setVisible(p is not None)
        if p is None:
            return
        automatico = figura.rotulos()[p.id] if p.rotulo is None else ""
        self.titulo_do_painel.setText(self.tr("Painel {}").format(figura.rotulos()[p.id] or "").strip())
        self.vista.clear()
        self.vista.addItem(self.tr("(nenhuma)"), None)
        for id_, nome, tipo in self._vistas:
            self.vista.addItem(f"{nome} · {TIPOS.get(tipo, tipo)}", id_)
        if p.congelado is not None:
            if self.vista.findData(p.vista) < 0:
                self.vista.addItem(self.tr("{} (fechada)").format(p.congelado.nome), p.vista)
        self.vista.setCurrentIndex(max(0, self.vista.findData(p.vista)))
        self.estado.escolher(1 if p.congelado is not None else 0)
        ligada_existe = p.vista in {v[0] for v in self._vistas}
        self.estado.habilitar(0, ligada_existe or p.congelado is None,
                              self.tr("A vista de onde ele veio foi fechada"))
        tipo = next((v[2] for v in self._vistas if v[0] == p.vista), None)
        self.estado.habilitar(1, p.congelado is not None or (p.vista is not None and tipo == "tempo"),
                              self.tr("Congelar chega primeiro à vista de tempo") if p.vista is not None
                              else self.tr("Escolha a vista antes"))
        self.rotulo.setText(p.rotulo or "")
        self.rotulo.setPlaceholderText(automatico or self.tr("automático"))
        self.rotulo.setEnabled(p.rotulo != "")
        self.sem_rotulo.setChecked(p.rotulo == "")
        self.tirar.setEnabled(len(figura.paineis) > 1)

    # ------------------------------------------------------------------ mudar

    def _emitir(self, nova: Figura, texto: str, juntar: bool = False) -> None:
        if not self._enchendo and self.figura is not None and nova != self.figura:
            self.mudar.emit(nova, texto, juntar)

    def _tentar(self, criar, texto: str, juntar: bool = False) -> None:
        """Monta a figura nova; uma que não vale (a grade pequena demais) volta os campos ao que era."""
        if self._enchendo or self.figura is None:
            return
        try:
            nova = criar()
        except FiguraInvalida as erro:
            self.setToolTip(str(erro))
            self.mostrar(self.figura, self.painel.id if self.painel else None, self._vistas)
            return
        self._emitir(nova, texto, juntar)

    def _nome(self) -> None:
        nome = self.nome.text().strip()
        if nome and self.figura is not None and nome != self.figura.nome:
            self._tentar(lambda: self.figura.com(nome=nome), self.tr("Renomear a figura"))

    def _modelo(self, _indice: int) -> None:
        id_ = self.modelo.currentData()
        self._tentar(lambda: fig.trocar_modelo(self.figura, id_),
                     self.tr("Trocar a página para {}").format(self.modelo.currentText()))

    def _altura(self, valor: float) -> None:
        self._tentar(lambda: self.figura.com(altura_mm=valor), self.tr("Mudar a altura"), juntar=True)

    def _familia(self, _indice: int) -> None:
        familia = self.familia.currentText()
        self._tentar(lambda: self.figura.com(estilo=replace(self.figura.estilo, familia=familia)),
                     self.tr("Trocar a fonte"))

    def _texto_pt(self, valor: float) -> None:
        def criar():
            e = self.figura.estilo
            fator = valor / e.texto_pt
            return self.figura.com(estilo=replace(
                e, texto_pt=valor, marcas_pt=min(72.0, max(4.0, round(e.marcas_pt * fator, 1))),
                rotulo_do_painel_pt=min(72.0, max(4.0, round(e.rotulo_do_painel_pt * fator, 1)))))
        self._tentar(criar, self.tr("Mudar o tamanho da letra"), juntar=True)

    def _idioma(self, indice: int) -> None:
        self._tentar(lambda: self.figura.com(idioma=IDIOMAS[indice]), self.tr("Mudar os números"))

    def _grade(self, _valor: int) -> None:
        self._tentar(lambda: self.figura.com(linhas=self.linhas.value(), colunas=self.colunas.value()),
                     self.tr("Mudar a grade"))

    def _eixos(self, _marcado: bool) -> None:
        self._tentar(lambda: self.figura.com(eixos_x_compartilhados=self.eixo_x.isChecked(),
                                             eixos_y_compartilhados=self.eixo_y.isChecked()),
                     self.tr("Mudar os eixos juntos"))

    def _vista(self, _indice: int) -> None:
        if self.painel is None:
            return
        id_ = self.vista.currentData()
        if id_ == self.painel.vista and self.painel.congelado is None:
            return
        painel = replace(self.painel, vista=id_, congelado=None, limites_x=None)
        self._tentar(lambda: fig.trocar_painel(self.figura, painel), self.tr("Ligar o painel a {}").format(
            self.vista.currentText()) if id_ else self.tr("Esvaziar o painel"))

    def _rotulo(self, *_a) -> None:
        if self.painel is None or self._enchendo:
            return
        rotulo = "" if self.sem_rotulo.isChecked() else (self.rotulo.text().strip() or None)
        self.rotulo.setEnabled(not self.sem_rotulo.isChecked())
        if rotulo != self.painel.rotulo:
            painel = replace(self.painel, rotulo=rotulo)
            self._tentar(lambda: fig.trocar_painel(self.figura, painel), self.tr("Mudar o rótulo do painel"))

    def _tirar(self) -> None:
        if self.painel is not None:
            id_ = self.painel.id
            self._tentar(lambda: fig.tirar_painel(self.figura, id_), self.tr("Tirar um painel"))
