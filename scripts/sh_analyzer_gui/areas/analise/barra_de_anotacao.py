"""A barra de anotação de uma vista (o gráfico como caderno): as ferramentas, o estilo e as ações das anotações.

Ela aparece pelo botão "Anotar" da barra da vista (ou a tecla ``A``) e some do mesmo jeito; fechada, a ferramenta
volta a ser a de escolher, e o gráfico se comporta como sempre (ninguém rabisca sem querer). Aberta:

* **as ferramentas** (cada uma com a sua tecla): escolher (V), texto (T), seta (S), linha (L), retângulo (R),
  elipse (O), região (G), cota (D), nível (H), marcador (M), caneta (P), marca-texto (K) e borracha (E);
* **o estilo:** a cor, o preenchimento, a espessura, o traço, a opacidade, a fonte (o tamanho, o negrito, o itálico e
  o quadro do texto), a ponta da seta e a forma do marcador. Com anotações escolhidas, muda as escolhidas (um passo
  de desfazer); sempre, fica para as próximas;
* **as ações:** duplicar (Ctrl+D), trazer para a frente (Ctrl+]), mandar para trás (Ctrl+[), travar, tirar (Del) e
  pôr a referência no caderno de notas (das escolhidas, ou da janela visível).
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QMenu, QToolButton, QWidget
from shiboken6 import isValid

from ...ajuda import botao_de_ajuda
from ...componentes.fluxo import LayoutDeFluxo
from ...dados.anotacoes import MARCAS, PONTAS, TRACOS
from ...tema.aplicar import aparencia
from ...tema.icones import IconeDoTema
from .anotacoes import CORES_RAPIDAS, ESPESSURAS, FONTES, OPACIDADES, AnotacoesDaVista

FERRAMENTAS_DA_BARRA = (
    ("selecionar", "ponteiro", "Escolher e mover", "V"),
    ("texto", "texto", "Texto", "T"),
    ("seta", "seta", "Seta (do alvo para o texto)", "S"),
    ("linha", "linha", "Linha", "L"),
    ("retangulo", "retangulo", "Retângulo (Shift: quadrado)", "R"),
    ("elipse", "elipse", "Elipse (Shift: círculo)", "O"),
    ("regiao", "regiao", "Região", "G"),
    ("cota", "regua", "Cota (Δt ou Δf)", "D"),
    ("nivel", "nivel", "Nível (uma linha horizontal: um limiar)", "H"),
    ("marcador", "marcador", "Marcador", "M"),
    (None, None, None, None),
    ("caneta", "caneta", "Caneta: desenhar à mão livre (o mouse ou a mesa digitalizadora)", "P"),
    ("marca_texto", "marca_texto", "Marca-texto", "K"),
    ("borracha", "borracha", "Borracha (apaga os desenhos que toca)", "E"),
)


def amostra_de_cor(cor: str, tema_texto: str, tamanho: int = 16) -> QIcon:
    """O ícone de uma cor: um círculo cheio; a do tema (vazia), o círculo cortado."""
    mapa = QPixmap(tamanho * 2, tamanho * 2)
    mapa.setDevicePixelRatio(2)
    mapa.fill(Qt.GlobalColor.transparent)
    p = QPainter(mapa)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(tema_texto), 1.0))
    if cor:
        p.setBrush(QColor(cor))
        p.drawEllipse(2, 2, tamanho - 4, tamanho - 4)
    else:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(2, 2, tamanho - 4, tamanho - 4)
        p.drawLine(4, tamanho - 4, tamanho - 4, 4)
    p.end()
    return QIcon(mapa)


def amostra_de_linha(espessura: float, estilo: Qt.PenStyle, cor: str, tamanho: int = 16) -> QIcon:
    mapa = QPixmap(tamanho * 4, tamanho * 2)
    mapa.setDevicePixelRatio(2)
    mapa.fill(Qt.GlobalColor.transparent)
    p = QPainter(mapa)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(cor), min(espessura, tamanho - 2), estilo, Qt.PenCapStyle.FlatCap))
    p.drawLine(2, tamanho // 2, tamanho * 2 - 2, tamanho // 2)
    p.end()
    return QIcon(mapa)


_ESTILOS_DO_QT = {"solido": Qt.PenStyle.SolidLine, "tracejado": Qt.PenStyle.DashLine,
                  "pontilhado": Qt.PenStyle.DotLine, "traco_ponto": Qt.PenStyle.DashDotLine}


class BarraDeAnotacao(QFrame):
    """A barra das anotações de ``anotacoes`` (``AnotacoesDaVista``). ``dono``: o widget da vista, onde valem as
    teclas das ferramentas (só com a barra aberta)."""

    def __init__(self, anotacoes: AnotacoesDaVista, dono: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("barra_de_anotacao")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.anotacoes = anotacoes
        self._enchendo = False
        self._primeira, self._sujo = True, False
        fluxo = LayoutDeFluxo(self)
        fluxo.setContentsMargins(10, 3, 10, 3)
        self.grupo = QActionGroup(self)
        self.grupo.setExclusive(True)
        self.acoes_das_ferramentas: dict[str, QAction] = {}
        self._atalhos: list[QAction] = []
        for nome, icone, dica, tecla in FERRAMENTAS_DA_BARRA:
            if nome is None:
                fluxo.addWidget(self._separador())
                continue
            a = QAction(self.tr(dica.split(" (")[0].split(":")[0]), self)
            a.setObjectName(f"ferramenta_{nome}")
            a.setCheckable(True)
            a.setShortcut(QKeySequence(tecla))
            a.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            a.setToolTip(f"{self.tr(dica)} ({tecla})")
            a.triggered.connect(lambda _=False, n=nome: self.anotacoes.definir_ferramenta(n))
            IconeDoTema(a, icone, papel_ligado="acento")
            self.grupo.addAction(a)
            dono.addAction(a)
            self._atalhos.append(a)
            self.acoes_das_ferramentas[nome] = a
            fluxo.addWidget(self._botao(a))
        self.acoes_das_ferramentas["selecionar"].setChecked(True)
        fluxo.addWidget(self._separador())

        self.cor = self._botao_de_menu("cor_da_anotacao", self.tr("A cor"))
        self.fundo = self._botao_de_menu("preenchimento_da_anotacao", self.tr("O preenchimento (o fundo das formas e "
                                                                              "do quadro do texto)"))
        self.espessura = self._botao_de_menu("espessura_da_anotacao", self.tr("A espessura"))
        self.traco = self._botao_de_menu("traco_da_anotacao", self.tr("O traço"))
        self.opacidade = self._botao_de_menu("opacidade_da_anotacao", self.tr("A opacidade"), texto="100 %")
        self.fonte = self._botao_de_menu("fonte_da_anotacao", self.tr("A fonte do texto"), texto="Aa")
        self.ponta = self._botao_de_menu("ponta_da_seta", self.tr("A ponta da seta"), texto="→")
        self.forma = self._botao_de_menu("forma_do_marcador", self.tr("A forma do marcador"), texto="●")
        for botao in (self.cor, self.fundo, self.espessura, self.traco, self.opacidade, self.fonte, self.ponta,
                      self.forma):
            fluxo.addWidget(botao)
        fluxo.addWidget(self._separador())

        def acao(nome, texto, icone, funcao, tecla=None) -> QAction:
            a = QAction(texto, self)
            a.setObjectName(nome)
            a.setToolTip(texto + (f" ({tecla})" if tecla else ""))
            IconeDoTema(a, icone)
            a.triggered.connect(funcao)
            fluxo.addWidget(self._botao(a))
            return a

        self.acao_duplicar = acao("duplicar_anotacao", self.tr("Duplicar"), "copiar", self.anotacoes.duplicar,
                                  "Ctrl+D")
        self.acao_frente = acao("anotacao_para_frente", self.tr("Trazer para a frente"), "frente",
                                lambda: self.anotacoes.ordenar(True), "Ctrl+]")
        self.acao_tras = acao("anotacao_para_tras", self.tr("Mandar para trás"), "tras",
                              lambda: self.anotacoes.ordenar(False), "Ctrl+[")
        self.acao_travar = acao("travar_anotacao", self.tr("Travar (não se move nem muda pelo mouse)"), "cadeado",
                                lambda: self.anotacoes.travar())
        self.acao_travar.setCheckable(True)
        self.acao_tirar = acao("tirar_anotacao", self.tr("Tirar"), "lixeira", self.anotacoes.tirar_escolhidas, "Del")
        fluxo.addWidget(self._separador())
        self.acao_caderno = acao("anotacao_ao_caderno", self.tr("Referenciar no caderno de notas (as escolhidas ou a "
                                                                "janela visível)"), "caderno", self._ao_caderno)
        fluxo.addWidget(botao_de_ajuda("anotacoes"))

        # Por métodos (não lambdas): o Qt desliga sozinho quando a barra some com a vista.
        anotacoes.ferramentaMudou.connect(self._ferramenta_mudou)
        anotacoes.selecaoMudou.connect(self.atualizar)
        anotacoes.estiloMudou.connect(self.atualizar)
        anotacoes.vista.mudou.connect(self._vista_mudou)
        aparencia().mudou.connect(self._tema_mudou)
        self.atalhos_ligados(False)
        self.atualizar()

    # ------------------------------------------------------------------ as peças

    def _botao(self, acao: QAction) -> QToolButton:
        b = QToolButton()
        b.setProperty("variante", "fantasma")
        b.setDefaultAction(acao)
        b.setIconSize(QSize(16, 16))
        b.setAutoRaise(True)
        return b

    def _botao_de_menu(self, nome: str, dica: str, texto: str = "") -> QToolButton:
        b = QToolButton()
        b.setObjectName(nome)
        b.setProperty("variante", "fantasma")
        b.setToolTip(dica)
        b.setAutoRaise(True)
        b.setIconSize(QSize(16, 16))
        b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        if texto:
            b.setText(texto)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        b.setMenu(QMenu(b))
        return b

    def _separador(self) -> QWidget:
        linha = QFrame()
        linha.setObjectName("separador_da_barra")
        linha.setFrameShape(QFrame.Shape.VLine)
        linha.setFixedSize(1, 18)
        return linha

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        if self._sujo:
            self._sujo = False
            self.atualizar()

    def atalhos_ligados(self, ligados: bool) -> None:
        """As teclas das ferramentas valem só com a barra aberta (a ``C`` dos cursores e a ``Z`` do zoom continuam
        valendo sempre)."""
        for a in self._atalhos:
            a.setEnabled(ligados)

    # ------------------------------------------------------------------ em dia com a escolha

    def _ferramenta_mudou(self, _nome: str) -> None:
        self.atualizar()

    def _vista_mudou(self, _vista, campos) -> None:
        if "anotacoes" in campos:
            self.atualizar()

    def _tema_mudou(self, _tema) -> None:
        self.atualizar()

    def atualizar(self) -> None:
        if not isValid(self) or not self.isVisible() and not self._primeira:
            self._sujo = True
            return
        self._primeira = False
        self._enchendo = True
        try:
            self._atualizar()
        finally:
            self._enchendo = False

    def _atualizar(self) -> None:
        t = aparencia().tema
        a = self.anotacoes
        ferramenta = self.acoes_das_ferramentas.get(a.ferramenta)
        if ferramenta is not None and not ferramenta.isChecked():
            ferramenta.setChecked(True)
        estilo = a.estilo_mostrado()
        escolhidas = a.escolhidas()
        tipos = {b.tipo for b in escolhidas} or {a.ferramenta}
        self.cor.setIcon(amostra_de_cor(estilo["cor"], t.texto))
        self.fundo.setIcon(amostra_de_cor(estilo["preenchimento"], t.texto))
        self.espessura.setIcon(amostra_de_linha(estilo["espessura"] or 1.6, Qt.PenStyle.SolidLine, t.texto))
        self.traco.setIcon(amostra_de_linha(1.6, _ESTILOS_DO_QT[estilo["traco"]], t.texto))
        self.opacidade.setText(f"{round(estilo['opacidade'] * 100)} %")
        self.fonte.setText(f"{estilo['fonte']:g} pt" if estilo["fonte"] else "Aa")
        self.ponta.setVisible(bool(tipos & {"seta"}))
        self.forma.setVisible(bool(tipos & {"marcador"}))
        self.fundo.setVisible(bool(tipos & {"retangulo", "elipse", "regiao", "marcador", "texto", "seta", "linha",
                                            "selecionar"}))
        self._encher_os_menus(estilo, t.texto)
        tem = bool(escolhidas)
        for acao in (self.acao_duplicar, self.acao_frente, self.acao_tras, self.acao_travar, self.acao_tirar):
            acao.setEnabled(tem)
        self.acao_travar.setChecked(tem and all(b.travada for b in escolhidas))

    def _encher_os_menus(self, estilo: dict, cor_do_texto: str) -> None:
        def paleta(menu: QMenu, campo: str, vazio: str) -> None:
            menu.clear()
            a = menu.addAction(amostra_de_cor("", cor_do_texto), vazio,
                               lambda: self.anotacoes.aplicar_estilo(**{campo: ""}))
            a.setCheckable(True)
            a.setChecked(estilo[campo] == "")
            for cor, nome in CORES_RAPIDAS.items():
                a = menu.addAction(amostra_de_cor(cor, cor_do_texto), self.tr(nome),
                                   lambda c=cor: self.anotacoes.aplicar_estilo(**{campo: c}))
                a.setCheckable(True)
                a.setChecked(estilo[campo] == cor)
            menu.addSeparator()
            menu.addAction(self.tr("Outra cor…"), lambda: self._outra_cor(campo, estilo[campo]))
            if campo == "preenchimento":
                menu.addSeparator()
                for o in (0.1, 0.2, 0.35, 0.5, 0.75, 1.0):
                    a = menu.addAction(self.tr("Fundo a {} %").format(round(o * 100)),
                                       lambda v=o: self.anotacoes.aplicar_estilo(opacidade_do_fundo=v))
                    a.setCheckable(True)
                    a.setChecked(abs(estilo["opacidade_do_fundo"] - o) < 1e-9)

        paleta(self.cor.menu(), "cor", self.tr("A do tema"))
        paleta(self.fundo.menu(), "preenchimento", self.tr("Sem preenchimento"))
        menu = self.espessura.menu()
        menu.clear()
        a = menu.addAction(self.tr("A do tipo"), lambda: self.anotacoes.aplicar_estilo(espessura=0.0))
        a.setCheckable(True)
        a.setChecked(estilo["espessura"] == 0)
        for e in ESPESSURAS:
            a = menu.addAction(amostra_de_linha(e, Qt.PenStyle.SolidLine, cor_do_texto), f"{e:g} px",
                               lambda v=e: self.anotacoes.aplicar_estilo(espessura=v))
            a.setCheckable(True)
            a.setChecked(estilo["espessura"] == e)
        menu = self.traco.menu()
        menu.clear()
        for chave, nome in TRACOS.items():
            a = menu.addAction(amostra_de_linha(1.6, _ESTILOS_DO_QT[chave], cor_do_texto), self.tr(nome),
                               lambda v=chave: self.anotacoes.aplicar_estilo(traco=v))
            a.setCheckable(True)
            a.setChecked(estilo["traco"] == chave)
        menu = self.opacidade.menu()
        menu.clear()
        for o in OPACIDADES:
            a = menu.addAction(f"{round(o * 100)} %", lambda v=o: self.anotacoes.aplicar_estilo(opacidade=v))
            a.setCheckable(True)
            a.setChecked(abs(estilo["opacidade"] - o) < 1e-9)
        menu = self.fonte.menu()
        menu.clear()
        a = menu.addAction(self.tr("A do tema"), lambda: self.anotacoes.aplicar_estilo(fonte=0.0))
        a.setCheckable(True)
        a.setChecked(estilo["fonte"] == 0)
        for f in FONTES:
            a = menu.addAction(f"{f:g} pt", lambda v=f: self.anotacoes.aplicar_estilo(fonte=v))
            a.setCheckable(True)
            a.setChecked(estilo["fonte"] == f)
        menu.addSeparator()
        for campo, nome in (("negrito", self.tr("Negrito")), ("italico", self.tr("Itálico")),
                            ("caixa", self.tr("Texto num quadro"))):
            a = menu.addAction(nome, lambda c=campo, v=not estilo[campo]: self.anotacoes.aplicar_estilo(**{c: v}))
            a.setCheckable(True)
            a.setChecked(bool(estilo[campo]))
        menu = self.ponta.menu()
        menu.clear()
        for chave, nome in PONTAS.items():
            a = menu.addAction(self.tr(nome), lambda v=chave: self.anotacoes.aplicar_estilo(ponta=v))
            a.setCheckable(True)
            a.setChecked(estilo["ponta"] == chave)
        menu = self.forma.menu()
        menu.clear()
        for chave, nome in MARCAS.items():
            a = menu.addAction(self.tr(nome), lambda v=chave: self.anotacoes.aplicar_estilo(forma=v))
            a.setCheckable(True)
            a.setChecked(estilo["forma"] == chave)

    def _outra_cor(self, campo: str, atual: str) -> None:
        cor = self.anotacoes.pedir_cor(atual or aparencia().tema.texto)
        if cor:
            self.anotacoes.aplicar_estilo(**{campo: cor})

    def _ao_caderno(self) -> None:
        a = self.anotacoes
        escolhidas = a.escolhidas()
        if escolhidas:
            for b in escolhidas:
                a.referenciar_anotacao(b)
            return
        for faixa, caixa in a.caixas():
            if caixa is not None:
                v0, v1 = caixa.viewRange()[0]
                a.referenciar(a.do_eixo(v0), a.do_eixo(v1), faixa=faixa)
                return


__all__ = ["BarraDeAnotacao", "amostra_de_cor"]
