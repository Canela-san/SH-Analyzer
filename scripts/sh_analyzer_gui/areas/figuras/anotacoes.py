"""As seções Inset e Anotações do painel escolhido (a F5.8; FG-03).

* **O inset** é do painel: ligado, ele amplia o trecho do meio do x que o painel mostra (um décimo dele), num canto;
  os campos mudam o trecho, o y (vazio: os extremos do trecho), o canto, o tamanho, a faixa (num painel de várias) e
  as linhas de ligação. Cada mudança é um passo de desfazer da figura.
* **As anotações** são da vista do painel (``dados/anotacoes.py``): as mesmas que a Análise mostra, que esta seção
  põe, muda e tira (``mudar_anotacoes``, das propriedades: na vista ligada, um passo de desfazer da vista; no painel
  congelado, na cópia dele, um passo da figura). Uma nova nasce dentro do que o painel mostra (o que o desenho
  achou), e os campos a levam para onde ela vai: o texto (aceita a matemática entre $; o da cota, vazio, é o Δt),
  as pontas e a faixa.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...componentes.basicos import Botao, CampoComUnidade
from ...dados import figura as fig
from ...dados.anotacoes import TIPOS, Anotacao, AnotacaoInvalida, texto_da_cota
from ...dados.desenho_da_figura import EixosDoPainel
from ...dados.figura import Figura, FiguraInvalida, Inset, Painel
from ...modelo.objetos import novo_id
from ...tema.icones import IconeDoTema
from .secoes import CampoDeTexto, CampoDoLimite, Tentar, mostrar_linha, secao

FRACAO_DO_INSET = 0.1                 # o trecho de um inset novo: um décimo do x, no meio


def _interpolar(limites: tuple[float, float], fracao: float, log: bool) -> float:
    a, b = limites
    if log and a > 0 and b > 0:
        return 10.0 ** (math.log10(a) + fracao * (math.log10(b) - math.log10(a)))
    return a + fracao * (b - a)


class _DoPainel(QWidget):
    def __init__(self, tentar: Tentar, parent: QWidget | None = None):
        super().__init__(parent)
        self.tentar = tentar
        self.figura: Figura | None = None
        self.painel: Painel | None = None
        self.eixos: EixosDoPainel | None = None
        self._enchendo = False

    def _coluna(self, quadro) -> None:
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.addWidget(quadro)


class SecaoDoInset(_DoPainel):
    def __init__(self, tentar: Tentar, parent: QWidget | None = None):
        super().__init__(tentar, parent)
        self.ligado = QCheckBox(self.tr("Ampliar um trecho"))
        self.ligado.setObjectName("inset_ligado")
        self.ligado.toggled.connect(self._ligar)
        self.de, self.ate = CampoComUnidade("s"), CampoComUnidade("s")
        for nome, campo in (("inset_de", self.de), ("inset_ate", self.ate)):
            campo.setObjectName(nome)
            campo.valorMudou.connect(lambda _v: self._trecho())
        trecho = QHBoxLayout()
        trecho.setSpacing(4)
        trecho.addWidget(self.de, 1)
        trecho.addWidget(QLabel("a"))
        trecho.addWidget(self.ate, 1)
        self.y0, self.y1 = CampoDoLimite(), CampoDoLimite()
        for nome, campo in (("inset_y0", self.y0), ("inset_y1", self.y1)):
            campo.setObjectName(nome)
            campo.setToolTip(self.tr("Vazio: os extremos do trecho"))
            campo.limiteMudou.connect(lambda _v: self._y())
        y = QHBoxLayout()
        y.setSpacing(4)
        y.addWidget(self.y0, 1)
        y.addWidget(QLabel("a"))
        y.addWidget(self.y1, 1)
        self.canto = QComboBox()
        self.canto.setObjectName("inset_canto")
        for id_, nome in fig.CANTOS.items():
            self.canto.addItem(self.tr(nome), id_)
        self.canto.activated.connect(lambda _i: self._mudar(self.tr("Mudar o canto do inset"),
                                                            canto=self.canto.currentData()))
        self.tamanho = QSpinBox()
        self.tamanho.setObjectName("inset_tamanho")
        self.tamanho.setRange(round(fig.TAMANHO_DO_INSET[0] * 100), round(fig.TAMANHO_DO_INSET[1] * 100))
        self.tamanho.setSuffix(" %")
        self.tamanho.setKeyboardTracking(False)
        self.tamanho.setFixedWidth(84)
        self.tamanho.valueChanged.connect(lambda v: self._mudar(self.tr("Mudar o tamanho do inset"), True,
                                                                tamanho=v / 100))
        self.faixa = QComboBox()
        self.faixa.setObjectName("inset_faixa")
        self.faixa.activated.connect(lambda i: self._mudar(self.tr("Mudar a faixa do inset"), faixa=i))
        self.ligacoes = QCheckBox(self.tr("Linhas de ligação"))
        self.ligacoes.setObjectName("inset_ligacoes")
        self.ligacoes.toggled.connect(lambda v: self._mudar(self.tr("Mudar as ligações do inset"), ligacoes=v))
        tamanho = QHBoxLayout()
        tamanho.addWidget(self.tamanho)
        tamanho.addWidget(self.ligacoes)
        tamanho.addStretch(1)
        for caixa in (self.canto, self.faixa):
            caixa.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            caixa.setMinimumContentsLength(8)
        self.campos = (self.de, self.ate, self.y0, self.y1, self.canto, self.tamanho, self.faixa, self.ligacoes)
        self.quadro = secao(self.tr("Inset"), [
            ("", self.ligado), (self.tr("Trecho"), trecho), (self.tr("y"), y), (self.tr("Canto"), self.canto),
            (self.tr("Tamanho"), tamanho), (self.tr("Faixa"), self.faixa)])
        self._coluna(self.quadro)

    def mostrar(self, figura: Figura, painel: Painel, eixos: EixosDoPainel | None) -> None:
        self.figura, self.painel, self.eixos = figura, painel, eixos
        inset = painel.inset
        self._enchendo = True
        try:
            self.ligado.setChecked(inset is not None)
            self.ligado.setEnabled(eixos is not None or inset is not None)
            for campo in self.campos:
                campo.setEnabled(inset is not None)
            unidade = eixos.unidade_x if eixos is not None else "s"
            self.de.unidade = self.ate.unidade = unidade
            faixas = eixos.por_faixa if eixos is not None else ()
            self.faixa.clear()
            for _numero, _limites, unidade_y, nome in faixas:
                self.faixa.addItem(f"{nome} ({unidade_y})" if unidade_y else nome)
            mostrar_linha(self.quadro, self.faixa, len(faixas) > 1)
            if inset is None:
                return
            self.de.definir_valor(inset.limites_x[0])
            self.ate.definir_valor(inset.limites_x[1])
            k = min(inset.faixa, len(faixas) - 1) if faixas else 0
            self.y0.unidade = self.y1.unidade = faixas[k][2] if faixas else ""
            for i, campo in enumerate((self.y0, self.y1)):
                campo.definir_limite(inset.limites_y[i] if inset.limites_y else None)
            self.canto.setCurrentIndex(self.canto.findData(inset.canto))
            self.tamanho.setValue(round(inset.tamanho * 100))
            self.faixa.setCurrentIndex(k)
            self.ligacoes.setChecked(inset.ligacoes)
        finally:
            self._enchendo = False

    def _trocar(self, inset: Inset | None, texto: str, juntar: bool = False) -> None:
        if self._enchendo or self.figura is None or self.painel is None or inset == self.painel.inset:
            return
        figura, painel = self.figura, replace(self.painel, inset=inset)
        self.tentar(lambda: fig.trocar_painel(figura, painel), texto, juntar)

    def _ligar(self, ligado: bool) -> None:
        if self._enchendo or self.painel is None:
            return
        if not ligado:
            self._trocar(None, self.tr("Tirar o inset"))
            return
        if self.eixos is None:
            return
        meio, log = 0.5, self.eixos.log
        trecho = (_interpolar(self.eixos.x, meio - FRACAO_DO_INSET / 2, log),
                  _interpolar(self.eixos.x, meio + FRACAO_DO_INSET / 2, log))
        self._trocar(Inset(trecho), self.tr("Pôr um inset"))

    def _mudar(self, texto: str, juntar: bool = False, **campos) -> None:
        if self.painel is None or self.painel.inset is None:
            return
        try:
            inset = replace(self.painel.inset, **campos)
        except FiguraInvalida as erro:
            self.setToolTip(str(erro))
            return
        self._trocar(inset, texto, juntar)

    def _trecho(self) -> None:
        a, b = self.de.valor, self.ate.valor
        if not a < b:
            self.ate.marcar_invalido(self.tr("O fim tem de ser maior que o começo"))
            return
        self._mudar(self.tr("Mudar o trecho do inset"), limites_x=(a, b))

    def _y(self) -> None:
        a, b = self.y0.limite, self.y1.limite
        if (a is None) != (b is None):
            return                                      # falta a outra ponta
        if a is not None and not a < b:
            self.y1.marcar_invalido(self.tr("O fim tem de ser maior que o começo"))
            return
        self._mudar(self.tr("Mudar o y do inset"), limites_y=None if a is None else (a, b))


class SecaoDasAnotacoes(_DoPainel):
    def __init__(self, tentar: Tentar, parent: QWidget | None = None):
        super().__init__(tentar, parent)
        self.anotacoes_de: Callable[[Painel], tuple[Anotacao, ...]] = lambda _p: ()
        self.mudar_anotacoes: Callable[[Painel, tuple[Anotacao, ...], str], None] = lambda _p, _a, _t: None
        self.anotacoes: tuple[Anotacao, ...] = ()
        self.lista = QListWidget()
        self.lista.setObjectName("anotacoes_do_painel")
        self.lista.setMaximumHeight(96)
        self.lista.currentRowChanged.connect(lambda _i: self._mostrar_a_escolhida())
        self.por = QToolButton()
        self.por.setObjectName("por_uma_anotacao")
        self.por.setText(self.tr("Pôr"))
        self.por.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.por.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        IconeDoTema(self.por, "mais")
        menu = QMenu(self.por)
        self.acoes_de_por = {}
        for tipo, nome in TIPOS.items():
            self.acoes_de_por[tipo] = menu.addAction(self.tr(nome), lambda t=tipo: self.nova(t))
        self.por.setMenu(menu)
        self.tirar = Botao(self.tr("Tirar"), "fantasma", "x")
        self.tirar.setObjectName("tirar_a_anotacao")
        self.tirar.clicked.connect(self._tirar)
        botoes = QHBoxLayout()
        botoes.addWidget(self.por)
        botoes.addWidget(self.tirar)
        botoes.addStretch(1)
        self.texto = CampoDeTexto()
        self.texto.setObjectName("texto_da_anotacao")
        self.texto.setToolTip(self.tr("Aceita a matemática entre $ ($\\Delta t$). Na cota, vazio: o Δt."))
        self.texto.textoMudou.connect(lambda v: self._mudar(self.tr("Mudar o texto da anotação"), texto=v or ""))
        self.x0, self.x1, self.y0, self.y1 = (CampoComUnidade("s") for _ in range(4))
        for nome, campo in (("x0", self.x0), ("x1", self.x1), ("y0", self.y0), ("y1", self.y1)):
            campo.setObjectName(f"anotacao_{nome}")
            campo.valorMudou.connect(lambda v, n=nome: self._ponto(n, v))
        x = QHBoxLayout()
        x.setSpacing(4)
        x.addWidget(self.x0, 1)
        self.ate_x = QLabel("a")
        x.addWidget(self.ate_x)
        x.addWidget(self.x1, 1)
        y = QHBoxLayout()
        y.setSpacing(4)
        y.addWidget(self.y0, 1)
        self.ate_y = QLabel("a")
        y.addWidget(self.ate_y)
        y.addWidget(self.y1, 1)
        self.faixa = QComboBox()
        self.faixa.setObjectName("faixa_da_anotacao")
        self.faixa.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.faixa.setMinimumContentsLength(8)
        self.faixa.activated.connect(lambda _i: self._mudar(self.tr("Mudar a faixa da anotação"),
                                                            faixa=self.faixa.currentData()))
        self.dica = QLabel()
        self.dica.setObjectName("rotulo_da_propriedade")
        self.dica.setWordWrap(True)
        self.campos = (self.texto, self.x0, self.x1, self.y0, self.y1, self.faixa, self.tirar)
        self.quadro = secao(self.tr("Anotações"), [
            ("", self.lista), ("", botoes), (self.tr("Texto"), self.texto), (self.tr("x"), x), (self.tr("y"), y),
            (self.tr("Faixa"), self.faixa), ("", self.dica)])
        self._coluna(self.quadro)

    @property
    def escolhida(self) -> Anotacao | None:
        i = self.lista.currentRow()
        return self.anotacoes[i] if 0 <= i < len(self.anotacoes) else None

    def mostrar(self, figura: Figura, painel: Painel, eixos: EixosDoPainel | None) -> None:
        anterior = self.escolhida.id if self.escolhida is not None else None
        self.figura, self.painel, self.eixos = figura, painel, eixos
        self.anotacoes = tuple(self.anotacoes_de(painel))
        frequencia = eixos is not None and eixos.tipo == "espectro"
        separador = figura.separador_decimal
        self._enchendo = True
        try:
            self.lista.clear()
            for a in self.anotacoes:
                texto = texto_da_cota(a, frequencia=frequencia, separador=separador) if a.tipo == "cota" else a.texto
                self.lista.addItem(QListWidgetItem(f"{TIPOS[a.tipo]}: {texto}" if texto else TIPOS[a.tipo]))
            ids = [a.id for a in self.anotacoes]
            self.lista.setCurrentRow(ids.index(anterior) if anterior in ids else (0 if ids else -1))
            for acao in self.acoes_de_por.values():
                acao.setEnabled(eixos is not None)
            self.por.setEnabled(eixos is not None)
            mostrar_linha(self.quadro, self.faixa, len(self._faixas()) > 1)
            self.dica.setText(self.tr("As anotações são da vista: aparecem também na Análise.")
                              if painel.congelado is None else
                              self.tr("As anotações da cópia congelada da vista."))
        finally:
            self._enchendo = False
        self._mostrar_a_escolhida()

    def _faixas(self):
        return self.eixos.por_faixa if self.eixos is not None else ()

    def _mostrar_a_escolhida(self) -> None:
        a = self.escolhida
        for campo in self.campos:
            campo.setEnabled(a is not None)
        if a is None or self._enchendo:
            return
        self._enchendo = True
        try:
            unidade_x = self.eixos.unidade_x if self.eixos is not None else "s"
            faixas = self._faixas()
            unidade_y = next((u for n, _l, u, _nome in faixas if n == a.faixa), faixas[0][2] if faixas else "")
            for campo in (self.x0, self.x1):
                campo.unidade = unidade_x
            for campo in (self.y0, self.y1):
                campo.unidade = unidade_y
            frequencia = self.eixos is not None and self.eixos.tipo == "espectro"
            self.texto.definir(a.texto or None, texto_da_cota(a, frequencia=frequencia,
                                                              separador=self.figura.separador_decimal)
                               if a.tipo == "cota" else "")
            self.x0.definir_valor(a.x0)
            self.y0.definir_valor(a.y0)
            com_x1, com_y1 = a.x1 is not None, a.y1 is not None
            self.x1.setVisible(com_x1)
            self.ate_x.setVisible(com_x1)
            self.y1.setVisible(com_y1)
            self.ate_y.setVisible(com_y1)
            if com_x1:
                self.x1.definir_valor(a.x1)
            if com_y1:
                self.y1.definir_valor(a.y1)
            self.y0.setEnabled(a.tipo != "regiao")
            self.faixa.clear()
            for numero, _limites, unidade, nome in faixas:
                self.faixa.addItem(f"{nome} ({unidade})" if unidade else nome, numero)
            self.faixa.setCurrentIndex(max(0, self.faixa.findData(a.faixa)))
        finally:
            self._enchendo = False

    # ------------------------------------------------------------------ mudar

    def _trocar(self, anotacoes: tuple[Anotacao, ...], texto: str) -> None:
        if self.painel is not None and anotacoes != self.anotacoes:
            self.mudar_anotacoes(self.painel, anotacoes, texto)

    def nova(self, tipo: str) -> None:
        """Uma anotação do ``tipo`` dentro do que o painel mostra (na primeira faixa), escolhida para editar."""
        if self.eixos is None or self.painel is None:
            return
        numero, (y0, y1), _unidade, _nome = self._faixas()[0]
        log = self.eixos.log

        def em_x(f):
            return _interpolar(self.eixos.x, f, log)

        def em_y(f):
            return y0 + f * (y1 - y0)

        criar = {"texto": lambda: Anotacao(novo_id(), "texto", em_x(0.05), em_y(0.85), texto=self.tr("Texto")),
                 "seta": lambda: Anotacao(novo_id(), "seta", em_x(0.5), em_y(0.5), em_x(0.65), em_y(0.8)),
                 "regiao": lambda: Anotacao(novo_id(), "regiao", em_x(0.4), 0.0, em_x(0.6)),
                 "cota": lambda: Anotacao(novo_id(), "cota", em_x(0.3), em_y(0.15), em_x(0.5))}
        a = replace(criar[tipo](), faixa=numero)
        self._trocar(self.anotacoes + (a,), self.tr("Pôr uma anotação ({})").format(TIPOS[tipo].lower()))
        ids = [b.id for b in self.anotacoes]
        if a.id in ids:
            self.lista.setCurrentRow(ids.index(a.id))

    def _mudar(self, passo: str, **campos) -> None:
        """A anotação escolhida com ``campos`` (``passo``: o texto do passo de desfazer)."""
        a = self.escolhida
        if self._enchendo or a is None:
            return
        try:
            nova = a.com(**campos)
        except AnotacaoInvalida as erro:
            self.dica.setText(str(erro))
            return
        self._trocar(tuple(nova if b.id == a.id else b for b in self.anotacoes), passo)

    def _ponto(self, nome: str, valor: float) -> None:
        self._mudar(self.tr("Mover a anotação"), **{nome: valor})

    def _tirar(self) -> None:
        a = self.escolhida
        if a is not None:
            self._trocar(tuple(b for b in self.anotacoes if b.id != a.id), self.tr("Tirar uma anotação"))


__all__ = ["SecaoDasAnotacoes", "SecaoDoInset"]
