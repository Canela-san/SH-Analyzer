"""As abas das vistas com a grade (AN-09, docs/gui-plan.md, 13.1: a grade do A3 dentro do A1): uma barra de abas, uma
para cada vista, e o centro dividido em uma, duas (lado a lado ou empilhadas), três (uma e duas) ou quatro (2 × 2)
células, cada uma com uma vista. Com uma célula, é uma aba como outra qualquer.

**A aba escolhida é a célula ativa** (a do contorno de destaque): o inspetor, as medidas e os atalhos são os dela.
Escolher a aba de uma vista que está numa célula ativa a célula dela; a de uma vista que não aparece a põe numa
célula vazia ou, sem nenhuma, na ativa. O clique numa célula a ativa (e segue para o que foi clicado: o pan começa
na hora), e o nome no alto de cada célula troca a vista dela.

A classe imita o pedaço do ``QTabWidget`` que a janela e a Análise usam (``insertTab``, ``removeTab``, ``widget``,
``currentWidget``, ``currentChanged``...), então quem só via abas continua igual. Cada vista é um widget só: a célula
o recebe, e as que não aparecem ficam guardadas, escondidas, com tudo o que tinham (o zoom, os cursores).

Sem Qt nenhum além do Widgets, e sem saber o que é uma vista: a Análise liga os eixos das células
(``areas/analise/ligacao_dos_eixos.py``) e guarda a disposição no projeto.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSplitter,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

DISPOSICOES = ("uma", "lado_a_lado", "empilhadas", "uma_e_duas", "dois_por_dois")
CELULAS = {"uma": 1, "lado_a_lado": 2, "empilhadas": 2, "uma_e_duas": 3, "dois_por_dois": 4}
ESPESSURA_DA_DIVISAO = 4                # px: a alça entre as células, larga o bastante para pegar com o mouse


def traduzir(texto: str) -> str:
    return QCoreApplication.translate("GradeDeVistas", texto)


def nome_da_disposicao(disposicao: str) -> str:
    return {"uma": traduzir("Uma vista"), "lado_a_lado": traduzir("Duas, lado a lado"),
            "empilhadas": traduzir("Duas, empilhadas"), "uma_e_duas": traduzir("Uma e duas"),
            "dois_por_dois": traduzir("Quatro (2 × 2)")}[disposicao]


class CelulaDaGrade(QFrame):
    """Uma parte do centro: o nome da vista no alto (um botão que troca a vista) e a vista; vazia, o convite."""

    def __init__(self, grade: AbasEmGrade):
        super().__init__()
        self.setObjectName("celula_da_grade")
        self.setProperty("ativa", False)
        self.grade = grade
        self.widget: QWidget | None = None
        self.nome = QToolButton()
        self.nome.setObjectName("nome_da_celula")
        self.nome.setAutoRaise(True)
        self.nome.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.nome.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.nome.setToolTip(traduzir("Trocar a vista desta parte"))
        self.menu = QMenu(self.nome)
        self.menu.aboutToShow.connect(self._montar_menu)
        self.nome.setMenu(self.menu)
        self.vazio = QLabel(traduzir("Escolha no alto, ou numa aba, a vista desta parte."))
        self.vazio.setObjectName("vazio_da_celula")
        self.vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vazio.setWordWrap(True)
        self._coluna = QVBoxLayout(self)
        self._coluna.setContentsMargins(1, 1, 1, 1)
        self._coluna.setSpacing(0)
        self._coluna.addWidget(self.nome, 0, Qt.AlignmentFlag.AlignLeft)
        self._coluna.addWidget(self.vazio, 1)

    def por(self, widget: QWidget | None) -> QWidget | None:
        """Põe ``widget`` aqui (``None``: esvazia) e devolve o que estava (escondido, sem pai que o mostre)."""
        antes = self.widget
        if antes is widget:
            return None
        if antes is not None:
            self._coluna.removeWidget(antes)
            self.grade._guardar(antes)
        self.widget = widget
        if widget is not None:
            self._coluna.addWidget(widget, 1)
            widget.show()
        self.vazio.setVisible(widget is None)
        self.atualizar_nome()
        return antes

    def atualizar_nome(self) -> None:
        i = self.grade.indexOf(self.widget) if self.widget is not None else -1
        if i < 0:
            self.nome.setText(traduzir("Escolher a vista"))
            self.nome.setIcon(QIcon())
        else:
            self.nome.setText(self.grade.tabText(i))
            self.nome.setIcon(self.grade.tabIcon(i))

    def mostrar_nome(self, mostrar: bool) -> None:
        self.nome.setVisible(mostrar)

    def _montar_menu(self) -> None:
        self.menu.clear()
        for i in range(self.grade.count()):
            vista = self.grade.widget(i)
            acao = self.menu.addAction(self.grade.tabIcon(i), self.grade.tabText(i))
            acao.setCheckable(True)
            acao.setChecked(vista is self.widget)
            acao.triggered.connect(lambda _=False, w=vista: self.grade.mostrar_na_celula(self, w))
        if self.widget is not None:
            self.menu.addSeparator()
            self.menu.addAction(traduzir("Deixar vazia")).triggered.connect(
                lambda: self.grade.mostrar_na_celula(self, None))


class AbasEmGrade(QWidget):
    currentChanged = Signal(int)
    celulasMudaram = Signal()          # a disposição, ou a vista de alguma célula (a ligação dos eixos refaz)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._barra = QTabBar()
        self._barra.setObjectName("abas_das_vistas")
        self._barra.setExpanding(False)
        self._barra.setDrawBase(False)
        self._linha_de_cima = QWidget()
        self._linha_de_cima.setObjectName("barra_das_vistas")
        self._linha_de_cima.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._topo = QHBoxLayout(self._linha_de_cima)
        self._topo.setContentsMargins(0, 0, 0, 0)
        self._topo.setSpacing(0)
        self._topo.addWidget(self._barra, 1)
        self._canto: QWidget | None = None
        self._miolo = QWidget()
        self._miolo.setObjectName("miolo_das_vistas")
        self._layout_do_miolo = QVBoxLayout(self._miolo)
        self._layout_do_miolo.setContentsMargins(0, 0, 0, 0)
        self._guardadas = QWidget(self)        # as vistas fora das células: escondidas, inteiras
        self._guardadas.hide()
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(0)
        coluna.addWidget(self._linha_de_cima)
        coluna.addWidget(self._miolo, 1)
        self._widgets: list[QWidget] = []
        self._disposicao = "uma"
        self._celulas: list[CelulaDaGrade] = []
        self._ativa = 0
        self._raiz: QWidget | None = None
        self._filtro_ligado = False
        self._montar("uma")
        self._barra.currentChanged.connect(self._aba_escolhida)

    # ------------------------------------------------------------------ o pedaço do QTabWidget

    def tabBar(self) -> QTabBar:
        return self._barra

    def count(self) -> int:
        return len(self._widgets)

    def widget(self, i: int) -> QWidget | None:
        return self._widgets[i] if 0 <= i < len(self._widgets) else None

    def indexOf(self, widget: QWidget | None) -> int:
        try:
            return self._widgets.index(widget)
        except ValueError:
            return -1

    def currentIndex(self) -> int:
        return self._barra.currentIndex()

    def currentWidget(self) -> QWidget | None:
        return self.widget(self._barra.currentIndex())

    def setCurrentIndex(self, i: int) -> None:
        if i == self._barra.currentIndex():
            self._aba_escolhida(i, avisar=False)       # a mesma aba: a vista dela pode ter saído da célula
        else:
            self._barra.setCurrentIndex(i)

    def setCurrentWidget(self, widget: QWidget) -> None:
        i = self.indexOf(widget)
        if i >= 0:
            self.setCurrentIndex(i)

    def addTab(self, widget: QWidget, icone: QIcon, texto: str) -> int:
        return self.insertTab(self.count(), widget, icone, texto)

    def insertTab(self, i: int, widget: QWidget, icone: QIcon, texto: str) -> int:
        i = max(0, min(i, self.count()))
        self._guardar(widget)
        self._widgets.insert(i, widget)
        return self._barra.insertTab(i, icone, texto)     # a primeira aba vira a atual (e vai para uma célula)

    def removeTab(self, i: int) -> None:
        widget = self.widget(i)
        if widget is None:
            return
        celula = self._celula_com(widget)
        self._widgets.pop(i)
        if celula is not None:
            celula.por(None)
        self._barra.removeTab(i)          # a aba atual que sai: a barra escolhe outra (e ela vai para uma célula)
        self._preencher_as_vazias()
        self._garantir_ativa()
        self.celulasMudaram.emit()

    def tabText(self, i: int) -> str:
        return self._barra.tabText(i)

    def tabIcon(self, i: int) -> QIcon:
        return self._barra.tabIcon(i)

    def setTabText(self, i: int, texto: str) -> None:
        self._barra.setTabText(i, texto)
        celula = self._celula_com(self.widget(i))
        if celula is not None:
            celula.atualizar_nome()

    def setTabToolTip(self, i: int, texto: str) -> None:
        self._barra.setTabToolTip(i, texto)

    def setDocumentMode(self, ligar: bool) -> None:
        self._barra.setDocumentMode(ligar)

    def setMovable(self, ligar: bool) -> None:
        self._barra.setMovable(ligar)

    def setTabsClosable(self, ligar: bool) -> None:
        self._barra.setTabsClosable(ligar)

    def setCornerWidget(self, widget: QWidget, _canto=Qt.Corner.TopRightCorner) -> None:
        if self._canto is not None:
            self._topo.removeWidget(self._canto)
            self._canto.deleteLater()
        self._canto = widget
        self._topo.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)

    # ------------------------------------------------------------------ a grade

    @property
    def disposicao(self) -> str:
        return self._disposicao

    @property
    def celulas(self) -> list[CelulaDaGrade]:
        return list(self._celulas)

    def celula_ativa(self) -> CelulaDaGrade:
        return self._celulas[self._ativa]

    def visiveis(self) -> list[QWidget]:
        """As vistas que aparecem, na ordem das células."""
        return [c.widget for c in self._celulas if c.widget is not None]

    def definir_disposicao(self, disposicao: str, widgets: list[QWidget | None] | None = None) -> None:
        """Divide o centro em ``disposicao`` (:data:`DISPOSICOES`). As células recebem ``widgets`` (o que o projeto
        guardou) ou, sem eles, as vistas que já apareciam e depois as outras, na ordem das abas; a vista da aba atual
        aparece sempre, e a célula dela fica ativa."""
        if disposicao not in CELULAS:
            raise ValueError(f"disposição desconhecida: {disposicao!r}")
        atual = self.currentWidget()
        if widgets is None:
            widgets = self.visiveis() + [w for w in self._widgets if w not in self.visiveis()]
        n = CELULAS[disposicao]
        escolhidas: list[QWidget | None] = []
        for w in widgets:
            if len(escolhidas) == n:
                break
            if w is None or (w in self._widgets and w not in escolhidas):
                escolhidas.append(w)
        escolhidas += [None] * (n - len(escolhidas))
        if atual is not None and atual not in escolhidas:
            vaga = next((k for k, w in enumerate(escolhidas) if w is None), n - 1 if n > 1 else 0)
            escolhidas[vaga] = atual
        for celula in self._celulas:
            celula.por(None)
        self._montar(disposicao)
        for celula, w in zip(self._celulas, escolhidas):
            celula.por(w)
        if disposicao == "uma" and escolhidas[0] is None and self._widgets:
            self._celulas[0].por(self._widgets[0])
        self._ativa = next((k for k, c in enumerate(self._celulas) if c.widget is atual and atual is not None), 0)
        self._garantir_ativa()
        self._pintar_ativa()
        self._ligar_o_filtro(n > 1)
        self.celulasMudaram.emit()

    def mostrar_na_celula(self, celula: CelulaDaGrade, widget: QWidget | None) -> None:
        """O menu do nome da célula: ``widget`` vai para ``celula`` (saindo da que o mostrava, que fica com a vista
        de ``celula`` no lugar: as duas trocam) e a célula fica ativa."""
        if celula not in self._celulas:
            return
        if widget is not None:
            outra = self._celula_com(widget)
            if outra is not None and outra is not celula:
                deslocada = celula.widget
                outra.por(None)
                celula.por(widget)
                outra.por(deslocada)
            else:
                celula.por(widget)
        else:
            celula.por(None)
        self._ativa = self._celulas.index(celula)
        self._garantir_ativa()
        self._pintar_ativa()
        self._seguir_a_ativa()
        self.celulasMudaram.emit()

    def ativar_celula(self, celula: CelulaDaGrade) -> None:
        """O clique numa célula com vista: ela fica ativa, e a aba da vista dela é a atual."""
        if celula not in self._celulas or celula.widget is None:
            return
        self._ativa = self._celulas.index(celula)
        self._pintar_ativa()
        self._seguir_a_ativa()

    # ------------------------------------------------------------------ por dentro

    def _guardar(self, widget: QWidget) -> None:
        if isValid(widget):
            widget.hide()
            widget.setParent(self._guardadas)

    def _celula_com(self, widget: QWidget | None) -> CelulaDaGrade | None:
        if widget is None:
            return None
        return next((c for c in self._celulas if c.widget is widget), None)

    def _aba_escolhida(self, i: int, avisar: bool = True) -> None:
        widget = self.widget(i)
        if widget is not None:
            celula = self._celula_com(widget)
            if celula is None:
                celula = next((c for c in self._celulas if c.widget is None), self._celulas[self._ativa])
                celula.por(widget)
                self.celulasMudaram.emit()
            self._ativa = self._celulas.index(celula)
            self._pintar_ativa()
        if avisar:
            self.currentChanged.emit(i)

    def _seguir_a_ativa(self) -> None:
        """A aba atual passa a ser a da vista da célula ativa."""
        widget = self._celulas[self._ativa].widget
        i = self.indexOf(widget)
        if i >= 0 and i != self._barra.currentIndex():
            self._barra.setCurrentIndex(i)

    def _preencher_as_vazias(self) -> None:
        """Uma vista saiu: as células vazias recebem as vistas que não aparecem, na ordem das abas."""
        fora = [w for w in self._widgets if self._celula_com(w) is None]
        for celula in self._celulas:
            if celula.widget is None and fora:
                celula.por(fora.pop(0))

    def _garantir_ativa(self) -> None:
        """A célula ativa tem vista, se alguma tem."""
        if self._celulas[self._ativa].widget is None:
            self._ativa = next((k for k, c in enumerate(self._celulas) if c.widget is not None), 0)
        self._pintar_ativa()
        self._seguir_a_ativa()

    def _pintar_ativa(self) -> None:
        sozinha = len(self._celulas) == 1
        for k, celula in enumerate(self._celulas):
            ativa = k == self._ativa and not sozinha
            if celula.property("ativa") != ativa:
                celula.setProperty("ativa", ativa)
                celula.style().unpolish(celula)
                celula.style().polish(celula)

    def _montar(self, disposicao: str) -> None:
        """As células de ``disposicao``, divididas por alças que se arrastam (no 2 × 2, as duas linhas andam
        juntas: as colunas ficam alinhadas)."""
        if self._raiz is not None:
            self._layout_do_miolo.removeWidget(self._raiz)
            self._raiz.deleteLater()
        n = CELULAS[disposicao]
        self._celulas = [CelulaDaGrade(self) for _ in range(n)]
        for celula in self._celulas:
            celula.setProperty("sozinha", n == 1)
            celula.mostrar_nome(n > 1)
            if n == 1:                                  # sozinha, sem contorno: a aba de sempre
                celula._coluna.setContentsMargins(0, 0, 0, 0)

        def dividir(orientacao, *partes) -> QSplitter:
            s = QSplitter(orientacao)
            s.setObjectName("divisao_das_vistas")
            s.setHandleWidth(ESPESSURA_DA_DIVISAO)
            s.setChildrenCollapsible(False)
            for p in partes:
                s.addWidget(p)
                s.setStretchFactor(s.indexOf(p), 1)
            return s

        h, v = Qt.Orientation.Horizontal, Qt.Orientation.Vertical
        c = self._celulas
        if disposicao == "uma":
            raiz = c[0]
        elif disposicao == "lado_a_lado":
            raiz = dividir(h, c[0], c[1])
        elif disposicao == "empilhadas":
            raiz = dividir(v, c[0], c[1])
        elif disposicao == "uma_e_duas":
            raiz = dividir(h, c[0], dividir(v, c[1], c[2]))
        else:
            de_cima, de_baixo = dividir(h, c[0], c[1]), dividir(h, c[2], c[3])
            de_cima.splitterMoved.connect(lambda *_: de_baixo.setSizes(de_cima.sizes()))
            de_baixo.splitterMoved.connect(lambda *_: de_cima.setSizes(de_baixo.sizes()))
            raiz = dividir(v, de_cima, de_baixo)
        self._raiz = raiz
        self._layout_do_miolo.addWidget(raiz)
        raiz.show()                                     # já na hora (o layout só mostraria no próximo giro)
        self._disposicao = disposicao
        self._ativa = 0

    def _ligar_o_filtro(self, ligar: bool) -> None:
        """Com mais de uma célula, o clique em qualquer lugar de uma delas a ativa (o filtro da aplicação vê o
        clique antes do widget clicado, que o recebe igual). O Qt tira o filtro sozinho quando a grade é destruída."""
        app = QApplication.instance()
        if ligar != self._filtro_ligado and app is not None:
            (app.installEventFilter if ligar else app.removeEventFilter)(self)
            self._filtro_ligado = ligar

    def eventFilter(self, objeto: QObject, evento: QEvent) -> bool:
        if evento.type() == QEvent.Type.MouseButtonPress and isinstance(objeto, QWidget) and isValid(self):
            w = objeto
            while w is not None and not isinstance(w, CelulaDaGrade):
                w = w.parentWidget()
            if w is not None and w in self._celulas and w is not self._celulas[self._ativa]:
                self.ativar_celula(w)
        return False
