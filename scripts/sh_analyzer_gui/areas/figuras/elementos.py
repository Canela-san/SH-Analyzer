"""As seções do painel escolhido que mudam o que se vê nele (F5.7; FG-04): os eixos (a legenda, o nome, o prefixo e
os limites do x e do y) e os traços (a cor, a espessura, o tracejado, o marcador e o nome na legenda de cada um).

**O que vem do desenho** (``EixosDoPainel``, a cada página desenhada): os limites, as unidades e os nomes automáticos,
que os campos vazios mostram apagados. **O y** (o nome, o prefixo, os limites) vale com um eixo y só: num painel de
tempo com várias faixas, cada uma tem o seu, automático, e os campos ficam desabilitados com a razão.

**Os traços** são os da vista do painel (``tracos``: o id, o nome, a cor e se é tracejado na vista). O estilo de um
traço guarda só o que muda; "Como na vista" o devolve inteiro ao da vista.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ...componentes.basicos import Botao
from ...dados import figura as fig
from ...dados.desenho_da_figura import EixosDoPainel
from ...dados.figura import EstiloDoTraco, Figura, Painel
from ...dados.unidades import PREFIXO_DO_EXPOENTE
from ...tema.tokens import CLARO, NOMES_DOS_TRACOS
from .secoes import CampoDeTexto, CampoDoLimite, Tentar, campo_decimal, secao

CORES_DA_FIGURA = (*zip(NOMES_DOS_TRACOS, CLARO.tracos, strict=True), ("preto", "#000000"),
                   ("cinza", "#6b7280"))
"""As cores da lista do traço: as da paleta (no tom da página branca), o preto e o cinza; o campo ao lado aceita
qualquer ``#rrggbb``."""


@dataclass(frozen=True)
class TracoDoPainel:
    """Um traço que o painel desenha, como a vista o mostra."""

    id: str
    nome: str
    cor: str
    tracejado: bool = False


def _amostra(cor: str) -> QIcon:
    imagem = QPixmap(QSize(14, 14))
    imagem.fill(QColor(cor))
    return QIcon(imagem)


def _prefixos(caixa: QComboBox, unidade: str) -> None:
    caixa.blockSignals(True)
    atual = caixa.currentData()
    caixa.clear()
    caixa.addItem(caixa.tr("automático"), None)
    for expoente in fig.PREFIXOS:
        caixa.addItem(f"{PREFIXO_DO_EXPOENTE[expoente]}{unidade}" if unidade else f"10^{expoente}", expoente)
    caixa.setCurrentIndex(max(0, caixa.findData(atual)))
    caixa.blockSignals(False)


class _Painel(QWidget):
    """O que as duas seções do painel têm em comum: a figura, o painel e o trocar o painel na figura."""

    def __init__(self, tentar: Tentar, parent: QWidget | None = None):
        super().__init__(parent)
        self.tentar = tentar
        self.figura: Figura | None = None
        self.painel: Painel | None = None
        self._enchendo = False

    def _trocar(self, texto: str, juntar: bool = False, **campos) -> None:
        if self._enchendo or self.figura is None or self.painel is None:
            return
        painel = replace(self.painel, **campos)
        if painel != self.painel:
            figura = self.figura
            self.tentar(lambda: fig.trocar_painel(figura, painel), texto, juntar)

    def _coluna(self, quadro) -> None:
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.addWidget(quadro)


class SecaoDosEixos(_Painel):
    def __init__(self, tentar: Tentar, parent: QWidget | None = None):
        super().__init__(tentar, parent)
        self.eixos: EixosDoPainel | None = None
        self.legenda = QComboBox()
        self.legenda.setObjectName("legenda_do_painel")
        for id_, nome in fig.LEGENDAS.items():
            self.legenda.addItem(self.tr(nome), id_)
        self.legenda.activated.connect(lambda _i: self._trocar(self.tr("Mudar a legenda"),
                                                               legenda=self.legenda.currentData()))
        linhas = [(self.tr("Legenda"), self.legenda)]
        self.nome, self.prefixo, self.minimo, self.maximo = {}, {}, {}, {}
        for eixo in ("x", "y"):
            nome = CampoDeTexto()
            nome.setObjectName(f"nome_do_{eixo}")
            nome.setToolTip(self.tr("O nome da grandeza (a unidade vem atrás, com o prefixo). Aceita a matemática "
                                    "entre $, como $V_{{AB}}$. Vazio: o automático."))
            nome.textoMudou.connect(lambda v, e=eixo: self._trocar(self.tr("Mudar o nome do eixo {}").format(e),
                                                                   **{f"nome_{e}": v}))
            prefixo = QComboBox()
            prefixo.setObjectName(f"prefixo_do_{eixo}")
            prefixo.setToolTip(self.tr("O prefixo do SI dos números do eixo"))
            prefixo.activated.connect(lambda _i, e=eixo, c=prefixo: self._trocar(
                self.tr("Mudar o prefixo do eixo {}").format(e), **{f"prefixo_{e}": c.currentData()}))
            minimo, maximo = CampoDoLimite(), CampoDoLimite()
            for ponta, campo in (("minimo", minimo), ("maximo", maximo)):
                campo.setObjectName(f"{ponta}_do_{eixo}")
                campo.setToolTip(self.tr("Vazio: o automático (o que a vista mostra)"))
                campo.limiteMudou.connect(lambda _v, e=eixo: self._limites(e))
            limites = QHBoxLayout()
            limites.setSpacing(4)
            limites.addWidget(minimo, 1)
            limites.addWidget(QLabel("a"))
            limites.addWidget(maximo, 1)
            self.nome[eixo], self.prefixo[eixo], self.minimo[eixo], self.maximo[eixo] = nome, prefixo, minimo, maximo
            linhas += [(self.tr("Nome do {}").format(eixo), nome), (self.tr("Limites do {}").format(eixo), limites),
                       (self.tr("Prefixo do {}").format(eixo), prefixo)]
        for caixa in (self.legenda, *self.prefixo.values()):
            caixa.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            caixa.setMinimumContentsLength(8)
        self.quadro = secao(self.tr("Eixos"), linhas)
        self._coluna(self.quadro)

    def mostrar(self, figura: Figura, painel: Painel, eixos: EixosDoPainel | None) -> None:
        self.figura, self.painel, self.eixos = figura, painel, eixos
        self._enchendo = True
        try:
            self.legenda.setCurrentIndex(self.legenda.findData(painel.legenda))
            um_y = eixos is None or eixos.y is not None
            for e in ("x", "y"):
                unidade = (eixos.unidade_x if e == "x" else eixos.unidade_y) if eixos is not None else ""
                automatico = (eixos.x if e == "x" else eixos.y) if eixos is not None else None
                limites = painel.limites_x if e == "x" else painel.limites_y
                for i, campo in enumerate((self.minimo[e], self.maximo[e])):
                    campo.unidade = unidade
                    campo.definir_limite(limites[i] if limites is not None else None,
                                         automatico[i] if automatico is not None else None)
                self.nome[e].definir(getattr(painel, f"nome_{e}"),
                                     (eixos.nome_x if e == "x" else eixos.nome_y) if eixos is not None else "")
                _prefixos(self.prefixo[e], unidade)
                self.prefixo[e].setCurrentIndex(max(0, self.prefixo[e].findData(getattr(painel, f"prefixo_{e}"))))
            razao = "" if um_y else self.tr("Com várias faixas, cada uma tem o y dela, automático")
            for campo in (self.nome["y"], self.prefixo["y"], self.minimo["y"], self.maximo["y"]):
                campo.setEnabled(um_y)
                if not um_y:
                    campo.setToolTip(razao)
        finally:
            self._enchendo = False

    def _limites(self, eixo: str) -> None:
        a, b = self.minimo[eixo].limite, self.maximo[eixo].limite
        automatico = (self.eixos.x if eixo == "x" else self.eixos.y) if self.eixos is not None else None
        if a is None and b is None:
            limites = None
        elif automatico is None and (a is None or b is None):
            return                                      # sem o automático, falta a outra ponta
        else:
            limites = (a if a is not None else automatico[0], b if b is not None else automatico[1])
            if not limites[0] < limites[1]:
                self.maximo[eixo].marcar_invalido(self.tr("O fim tem de ser maior que o começo"))
                return
        self._trocar(self.tr("Mudar os limites do {}").format(eixo), **{f"limites_{eixo}": limites})


class SecaoDosTracos(_Painel):
    def __init__(self, tentar: Tentar, parent: QWidget | None = None):
        super().__init__(tentar, parent)
        self.tracos: list[TracoDoPainel] = []
        self.traco = QComboBox()
        self.traco.setObjectName("traco_do_painel")
        self.traco.currentIndexChanged.connect(lambda _i: self._mostrar_o_traco())
        self.cor = QComboBox()
        self.cor.setObjectName("cor_do_traco_na_figura")
        self.cor.addItem(self.tr("como na vista"), None)
        for nome, cor in CORES_DA_FIGURA:
            self.cor.addItem(_amostra(cor), self.tr(nome), cor)
        self.cor.activated.connect(lambda _i: self._mudar(self.tr("Mudar a cor do traço"), cor=self.cor.currentData()))
        self.hexa = QLineEdit()
        self.hexa.setObjectName("cor_hexadecimal")
        self.hexa.setPlaceholderText("#rrggbb")
        self.hexa.setFixedWidth(80)
        self.hexa.editingFinished.connect(self._hexa)
        cor = QHBoxLayout()
        cor.setSpacing(6)
        cor.addWidget(self.cor, 1)
        cor.addWidget(self.hexa)
        self.espessura = campo_decimal("pt", 0.0, fig.ESPESSURA_PT[1], 0.1, casas=2)
        self.espessura.setObjectName("espessura_do_traco")
        self.espessura.setSpecialValueText(self.tr("a da figura"))
        self.espessura.setFixedWidth(110)
        self.espessura.valueChanged.connect(lambda v: self._mudar(
            self.tr("Mudar a espessura do traço"), True, espessura_pt=max(v, fig.ESPESSURA_PT[0]) if v > 0 else None))
        self.tracejado = QComboBox()
        self.tracejado.setObjectName("tracejado_do_traco")
        self.tracejado.addItem(self.tr("como na vista"), None)
        for codigo, nome in fig.TRACEJADOS.items():
            self.tracejado.addItem(self.tr(nome), codigo)
        self.tracejado.activated.connect(lambda _i: self._mudar(self.tr("Mudar o tracejado"),
                                                                tracejado=self.tracejado.currentData()))
        self.marcador = QComboBox()
        self.marcador.setObjectName("marcador_do_traco")
        for codigo, nome in fig.MARCADORES.items():
            self.marcador.addItem(self.tr(nome), codigo)
        self.marcador.activated.connect(lambda _i: self._mudar(self.tr("Mudar o marcador"),
                                                               marcador=self.marcador.currentData()))
        self.nome = CampoDeTexto()
        self.nome.setObjectName("nome_do_traco")
        self.nome.setToolTip(self.tr("O nome na legenda (aceita a matemática entre $). Vazio: o da vista."))
        self.nome.textoMudou.connect(lambda v: self._mudar(self.tr("Mudar o nome do traço"), nome=v))
        self.voltar = Botao(self.tr("Como na vista"), "fantasma", "desfazer")
        self.voltar.setObjectName("traco_como_na_vista")
        self.voltar.clicked.connect(self._como_na_vista)
        self.vazio = QLabel(self.tr("O painel não tem traços"))
        self.vazio.setObjectName("rotulo_da_propriedade")
        self.quadro = secao(self.tr("Traços"), [
            (self.tr("Traço"), self.traco), (self.tr("Cor"), cor), (self.tr("Espessura"), self.espessura),
            (self.tr("Tracejado"), self.tracejado), (self.tr("Marcador"), self.marcador), (self.tr("Nome"), self.nome),
            ("", self.voltar), ("", self.vazio)])
        for caixa in (self.traco, self.cor, self.tracejado, self.marcador):
            caixa.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            caixa.setMinimumContentsLength(6)
        self._coluna(self.quadro)

    @property
    def traco_atual(self) -> TracoDoPainel | None:
        i = self.traco.currentIndex()
        return self.tracos[i] if 0 <= i < len(self.tracos) else None

    def mostrar(self, figura: Figura, painel: Painel, tracos: list[TracoDoPainel]) -> None:
        anterior = self.traco_atual.id if self.traco_atual is not None else None
        self.figura, self.painel, self.tracos = figura, painel, list(tracos)
        self._enchendo = True
        try:
            self.traco.blockSignals(True)
            self.traco.clear()
            for t in self.tracos:
                self.traco.addItem(_amostra(painel.estilo_do_traco(t.id).cor or t.cor), t.nome, t.id)
            self.traco.setCurrentIndex(max(0, self.traco.findData(anterior)))
            self.traco.blockSignals(False)
        finally:
            self._enchendo = False
        self._mostrar_o_traco()

    def _mostrar_o_traco(self) -> None:
        t = self.traco_atual
        for campo in (self.traco, self.cor, self.hexa, self.espessura, self.tracejado, self.marcador, self.nome,
                      self.voltar):
            campo.setEnabled(t is not None)
        self.vazio.setVisible(t is None)
        if t is None or self.painel is None:
            return
        e = self.painel.estilo_do_traco(t.id)
        self._enchendo = True
        try:
            self.cor.setCurrentIndex(max(0, self.cor.findData(e.cor)) if e.cor is not None else 0)
            if e.cor is not None and self.cor.findData(e.cor) < 0:
                self.cor.setCurrentIndex(-1)
            self.hexa.setText(e.cor or t.cor)
            self.espessura.setValue(e.espessura_pt or 0.0)
            self.tracejado.setCurrentIndex(max(0, self.tracejado.findData(e.tracejado)) if e.tracejado else 0)
            self.marcador.setCurrentIndex(max(0, self.marcador.findData(e.marcador)))
            self.nome.definir(e.nome, t.nome)
            self.voltar.setEnabled(not e.vazio)
        finally:
            self._enchendo = False

    def _mudar(self, texto: str, juntar: bool = False, **campos) -> None:
        t = self.traco_atual
        if self._enchendo or t is None or self.painel is None:
            return
        try:
            estilo = replace(self.painel.estilo_do_traco(t.id), **campos)
        except fig.FiguraInvalida as erro:
            self.hexa.setToolTip(str(erro))
            return
        self._trocar(texto, juntar, tracos=self.painel.com_estilo_do_traco(t.id, estilo).tracos)

    def _hexa(self) -> None:
        texto = self.hexa.text().strip()
        t = self.traco_atual
        if t is None or self._enchendo:
            return
        if not texto.startswith("#"):
            texto = "#" + texto
        try:
            cor = EstiloDoTraco(cor=texto).cor
        except fig.FiguraInvalida as erro:
            self.hexa.setToolTip(str(erro))
            return
        self._mudar(self.tr("Mudar a cor do traço"), cor=None if cor == t.cor.lower() else cor)

    def _como_na_vista(self) -> None:
        t = self.traco_atual
        if t is not None and self.painel is not None:
            self._trocar(self.tr("Voltar o traço ao da vista"),
                         tracos=self.painel.com_estilo_do_traco(t.id, EstiloDoTraco()).tracos)


__all__ = ["CORES_DA_FIGURA", "SecaoDosEixos", "SecaoDosTracos", "TracoDoPainel"]
