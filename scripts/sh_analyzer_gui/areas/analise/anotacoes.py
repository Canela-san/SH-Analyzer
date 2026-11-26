"""As anotações de uma vista nos gráficos da Análise (a F5.8 refeita: o gráfico como caderno de anotações): as formas,
os textos e os desenhos à mão livre, postos pela barra de anotação ou pelo clique direito, escolhidos, movidos e
esticados pelo mouse, com o estilo de cada um.

* **O desenho e os gestos** são da camada de cada caixa (``graficos/camada_de_anotacoes.py``): um item só por caixa,
  em pixels da tela. Este módulo é o dono delas: dá a cada camada as anotações da caixa dela, guarda a ferramenta, o
  estilo das novas e a escolha, e põe na pilha de desfazer cada mudança (``MudarAnotacoes``).
* **A ferramenta** (``ferramenta``) vem da barra de anotação (``barra_de_anotacao.py``): "selecionar" é a de sempre
  (o gráfico se comporta como antes; só o clique numa anotação a escolhe). As outras só valem com a barra aberta: ninguém
  rabisca um gráfico sem querer.
* **O estilo** (:meth:`aplicar_estilo`) muda as escolhidas (um passo de desfazer) e fica para as próximas.
* **O menu** (:meth:`acoes`, o clique direito numa caixa): pôr cada tipo ali; perto de uma anotação, mudar o texto,
  o estilo, duplicar, a ordem, travar, referenciar no caderno e tirar; e referenciar o ponto, o trecho entre os
  cursores ou a janela no caderno de notas (``servicos/notas.py``).
* **As coordenadas** são as dos dados (``dados/anotacoes.py``); ``para_eixo`` e ``do_eixo`` levam o x à posição na
  caixa (o log10 da frequência logarítmica do espectro).
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QTextOption
from PySide6.QtWidgets import QColorDialog, QInputDialog, QLineEdit, QMenu, QPlainTextEdit, QWidget
from shiboken6 import isValid

from ...dados.anotacoes import MARCAS, PONTAS, TIPOS, TRACOS, Anotacao, rotulo, texto_da_cota, texto_do_nivel
from ...dados.notas import Referencia
from ...graficos.camada_de_anotacoes import (
    FERRAMENTAS,
    CamadaDeAnotacoes,
    Cores,
    fonte_da_anotacao,
    geometria,
    mesa,
    mover,
)
from ...modelo.comandos import MudarAnotacoes
from ...modelo.objetos import Projeto, Vista, novo_id
from ...servicos.notas import central
from ...tema.aplicar import aparencia

PERTO_PX = 12.0                  # o clique direito a até isto de uma anotação é nela
FOLGA_DA_REGIAO = 0.05           # sem os cursores, a região e a cota têm 2 × isto da janela, em volta do clique
CORES_RAPIDAS = {"#ef4444": "Vermelho", "#f97316": "Laranja", "#facc15": "Amarelo", "#22c55e": "Verde",
                 "#06b6d4": "Ciano", "#3b82f6": "Azul", "#a855f7": "Roxo", "#ec4899": "Rosa", "#ffffff": "Branco",
                 "#111111": "Preto", "#9ca3af": "Cinza"}
"""As cores da paleta da barra e do menu (visíveis nos dois temas); vazia: a do tema."""
ESPESSURAS = (0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0)
FONTES = (8.0, 9.0, 10.0, 12.0, 14.0, 16.0, 20.0, 24.0, 32.0, 40.0, 48.0)
OPACIDADES = (1.0, 0.75, 0.5, 0.25)
ESTILO_PADRAO = {"cor": "", "espessura": 0.0, "traco": "solido", "opacidade": 1.0, "preenchimento": "",
                 "opacidade_do_fundo": 0.2, "fonte": 0.0, "negrito": False, "italico": False, "caixa": False,
                 "ponta": "cheia", "forma": "circulo"}
ESTILO_DA_CANETA = {"cor": "", "espessura": 2.4, "opacidade": 1.0}
ESTILO_DO_MARCA_TEXTO = {"cor": "#facc15", "espessura": 16.0, "opacidade": 0.35}
DURACAO_DO_DESTAQUE_MS = 1800


def _identidade(v: float) -> float:
    return v


class EditorNaTela(QPlainTextEdit):
    """O texto de uma anotação escrito no próprio gráfico: Enter grava, Shift+Enter quebra a linha, Esc desiste; sair
    dele também grava."""

    def __init__(self, texto: str, fonte, ao_gravar: Callable[[str], None], parent: QWidget):
        super().__init__(parent)
        self.setObjectName("editor_de_anotacao")
        self._ao_gravar, self._feito = ao_gravar, False
        self.setFont(fonte)
        self.setPlainText(texto)
        self.setWordWrapMode(QTextOption.WrapMode.NoWrap)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setPlaceholderText(self.tr("Escreva… (Enter grava, Shift+Enter quebra a linha, Esc desiste)"))
        self.textChanged.connect(self._ajustar)
        self._ajustar()
        self.selectAll()

    def _ajustar(self) -> None:
        medida = self.fontMetrics()
        linhas = self.toPlainText().split("\n") or [""]
        largura = max([medida.horizontalAdvance(linha) for linha in linhas] +
                      [medida.horizontalAdvance(self.placeholderText()) if not self.toPlainText() else 0])
        self.setFixedSize(min(900, largura + 28), medida.lineSpacing() * len(linhas) + 16)

    def gravar(self) -> None:
        if not self._feito:
            self._feito = True
            self._ao_gravar(self.toPlainText().strip())
        self.deleteLater()

    def desistir(self) -> None:
        self._feito = True
        self.deleteLater()

    def keyPressEvent(self, evento) -> None:
        if evento.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and \
                not evento.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.gravar()
            return
        if evento.key() == Qt.Key.Key_Escape:
            self.desistir()
            return
        super().keyPressEvent(evento)

    def focusOutEvent(self, evento) -> None:
        super().focusOutEvent(evento)
        if not self._feito:
            self.gravar()


class AnotacoesDaVista(QObject):
    """As anotações de ``vista`` nas caixas que ``caixas()`` dá (``(faixa das novas, caixa)``); ``caixa_da_faixa``:
    a caixa em que fica uma anotação da faixa (``None``: a faixa não está na tela). ``separador()``: o separador
    decimal dos números; ``frequencia``: o Δf do espectro; ``log()``: o x em log10 (o espectro);
    ``unidade_da_faixa(numero)``: a unidade do y (o texto do nível)."""

    ferramentaMudou = Signal(str)
    selecaoMudou = Signal()
    estiloMudou = Signal()

    def __init__(self, vista: Vista, projeto: Projeto, caixa_da_faixa: Callable[[int], pg.ViewBox | None], *,
                 caixas: Callable[[], list] | None = None, frequencia: bool = False,
                 para_eixo: Callable[[float], float] = _identidade, do_eixo: Callable[[float], float] = _identidade,
                 log: Callable[[], bool] | None = None, separador: Callable[[], str] = lambda: ",",
                 unidade_da_faixa: Callable[[int], str] = lambda _n: "", parent: QWidget | None = None):
        super().__init__(parent)
        self.vista, self.projeto, self.caixa_da_faixa = vista, projeto, caixa_da_faixa
        self.caixas = caixas or (lambda: [(0, c) for c in [caixa_da_faixa(0)] if c is not None])
        self.frequencia, self.para_eixo, self.do_eixo, self.separador = frequencia, para_eixo, do_eixo, separador
        self.log = log or (lambda: False)
        self.unidade_da_faixa = unidade_da_faixa
        self.pedir_texto = self._pedir_texto              # os testes trocam (o diálogo do sistema)
        self.pedir_cor = self._pedir_cor
        self.camadas: dict[int, CamadaDeAnotacoes] = {}   # id(caixa) -> a camada dela
        self.ferramenta = "selecionar"
        self.selecionadas: set[str] = set()
        self.estilo = dict(ESTILO_PADRAO)
        self.estilo_da_caneta = dict(ESTILO_DA_CANETA)
        self.estilo_do_marca_texto = dict(ESTILO_DO_MARCA_TEXTO)
        self.editor: EditorNaTela | None = None
        self._destaques: list = []
        self._ouvidos: set[int] = set()
        vista.mudou.connect(self._vista_mudou)
        if isinstance(parent, QWidget):
            self._criar_atalhos(parent)

    # ------------------------------------------------------------------ o x do eixo, em vetores

    def para_eixo_np(self, x):
        x = np.asarray(x, dtype=float)
        return np.log10(np.maximum(x, 1e-12)) if self.log() else x

    def do_eixo_np(self, v):
        v = np.asarray(v, dtype=float)
        return 10.0 ** np.clip(v, -3.0, 9.0) if self.log() else v

    # ------------------------------------------------------------------ as camadas

    def _vista_mudou(self, _vista, campos) -> None:
        if "anotacoes" in campos:
            ids = {a.id for a in self.vista.anotacoes}
            if self.selecionadas - ids:
                self.selecionadas &= ids
                self.selecaoMudou.emit()
            self.refazer()

    @property
    def itens(self) -> dict[str, CamadaDeAnotacoes]:
        """O id de cada anotação à vista -> a camada que a desenha."""
        return {i: camada for camada in self.camadas.values() if isValid(camada) for i in camada.ids()}

    def limpar(self) -> None:
        for camada in self.camadas.values():
            if isValid(camada) and camada.scene() is not None and isValid(camada.caixa):
                camada.caixa.removeItem(camada)
        self.camadas = {}

    def refazer(self) -> None:
        """Põe uma camada em cada caixa (as que sumiram saem) e dá a cada uma as anotações dela."""
        t = aparencia().tema
        cores = Cores(texto=t.texto, acento=t.acento, fundo=t.elevada, escolha=t.acento)
        vivas = {}
        for faixa, caixa in self.caixas():
            if caixa is None or not isValid(caixa):
                continue
            camada = self.camadas.get(id(caixa))
            if camada is None or not isValid(camada) or camada.caixa is not caixa:
                camada = CamadaDeAnotacoes(self, caixa, faixa)
                caixa.addItem(camada, ignoreBounds=True)
                camada.viewRangeChanged()
                self._ouvir_a_mesa(caixa)
            camada.faixa = faixa
            vivas[id(caixa)] = camada
        for chave, camada in self.camadas.items():
            if chave not in vivas and isValid(camada) and camada.scene() is not None and isValid(camada.caixa):
                camada.caixa.removeItem(camada)
        self.camadas = vivas
        por_caixa: dict[int, list[Anotacao]] = {k: [] for k in vivas}
        for a in self.vista.anotacoes:
            caixa = self.caixa_da_faixa(a.faixa)
            if caixa is not None and id(caixa) in por_caixa:
                por_caixa[id(caixa)].append(a)
        for chave, camada in vivas.items():
            camada.definir(por_caixa[chave], cores)

    def _ouvir_a_mesa(self, caixa) -> None:
        cena = caixa.scene()
        for view in (cena.views() if cena is not None else []):
            if id(view) not in self._ouvidos:
                self._ouvidos.add(id(view))
                mesa().ouvir(view.viewport())

    def camada_da_caixa(self, caixa) -> CamadaDeAnotacoes | None:
        return self.camadas.get(id(caixa))

    def _todas_as_camadas(self) -> list[CamadaDeAnotacoes]:
        return [c for c in self.camadas.values() if isValid(c)]

    # ------------------------------------------------------------------ o que a camada pergunta

    def texto_de(self, a: Anotacao) -> str:
        if a.tipo == "cota":
            return texto_da_cota(a, frequencia=self.frequencia, separador=self.separador())
        if a.tipo == "nivel":
            return texto_do_nivel(a, self.unidade_da_faixa(a.faixa), self.separador())
        if a.tipo == "texto" and not a.texto:
            return TIPOS["texto"]
        return a.texto

    def novo_id(self) -> str:
        return novo_id()

    def estilo_novo(self, tipo: str) -> dict:
        """O estilo de uma anotação nova do ``tipo`` (ou da ferramenta: a caneta e o marca-texto têm o deles), só com
        o que sai do padrão."""
        if tipo == "caneta":
            estilo = self.estilo_da_caneta
        elif tipo == "marca_texto":
            estilo = self.estilo_do_marca_texto
        else:
            estilo = self.estilo
        return {k: v for k, v in estilo.items() if v != ESTILO_PADRAO.get(k, None)}

    # ------------------------------------------------------------------ a ferramenta e a escolha

    def definir_ferramenta(self, nome: str) -> None:
        if nome not in FERRAMENTAS:
            raise ValueError(f"ferramenta desconhecida: {nome!r}")
        if nome == self.ferramenta:
            return
        self.ferramenta = nome
        for camada in self._todas_as_camadas():
            camada.cancelar()
            camada.unsetCursor()
        if nome != "selecionar" and self.selecionadas:
            self.escolher(())
        self.ferramentaMudou.emit(nome)

    def escolher(self, ids, somar: bool = False) -> None:
        ids = set(ids)
        novas = (self.selecionadas ^ ids) if somar else ids
        if novas != self.selecionadas:
            self.selecionadas = novas
            for camada in self._todas_as_camadas():
                camada.update()
            self.selecaoMudou.emit()

    def escolhidas(self) -> list[Anotacao]:
        return [a for a in self.vista.anotacoes if a.id in self.selecionadas]

    def esc(self) -> bool:
        """O Esc: larga o gesto, a ferramenta e a escolha (nessa ordem). Devolve se fez algo."""
        if self.editor is not None and isValid(self.editor):
            self.editor.desistir()
            self.editor = None
            return True
        if self.ferramenta != "selecionar":
            self.definir_ferramenta("selecionar")
            return True
        if self.selecionadas:
            self.escolher(())
            return True
        return False

    # ------------------------------------------------------------------ mudar (cada uma, um passo de desfazer)

    def _empilhar(self, anotacoes, texto: str) -> None:
        anotacoes = tuple(anotacoes)
        if anotacoes != self.vista.anotacoes:
            self.projeto.pilha.push(MudarAnotacoes(self.vista, anotacoes, texto=texto))

    def por(self, anotacao: Anotacao) -> None:
        self._empilhar(self.vista.anotacoes + (anotacao,),
                       self.tr("Pôr uma anotação ({})").format(TIPOS[anotacao.tipo].lower()))

    def trocar(self, anotacao: Anotacao, texto: str) -> None:
        self._empilhar(tuple(anotacao if a.id == anotacao.id else a for a in self.vista.anotacoes), texto)

    def mudar(self, novas, texto: str) -> None:
        por_id = {a.id: a for a in novas}
        self._empilhar(tuple(por_id.get(a.id, a) for a in self.vista.anotacoes), texto)

    def tirar(self, id_: str) -> None:
        self._empilhar(tuple(a for a in self.vista.anotacoes if a.id != id_), self.tr("Tirar uma anotação"))

    def apagar(self, ids, texto: str | None = None) -> None:
        ids = set(ids)
        if not ids:
            return
        self._empilhar(tuple(a for a in self.vista.anotacoes if a.id not in ids),
                       texto or (self.tr("Tirar uma anotação") if len(ids) == 1
                                 else self.tr("Tirar {} anotações").format(len(ids))))

    def tirar_escolhidas(self) -> bool:
        if not self.selecionadas:
            return False
        self.apagar(self.selecionadas)
        return True

    def criar(self, a: Anotacao, camada: CamadaDeAnotacoes, na_cena: QPointF | None) -> None:
        """Uma anotação nova de uma ferramenta: o texto pede o que escrever, ali mesmo, antes de existir; as outras
        entram na hora e ficam escolhidas. Depois de uma forma, a ferramenta volta a ser a de escolher (a caneta, o
        marca-texto e a borracha ficam)."""
        if a.tipo == "texto" and na_cena is not None:
            self.abrir_editor(a, camada, na_cena, novo=True)
            return
        self.por(a)
        if a.tipo != "desenho":
            self.definir_ferramenta("selecionar")
            self.escolher((a.id,))

    def duplicar(self) -> None:
        escolhidas = self.escolhidas()
        if not escolhidas:
            return
        caixa = self.caixa_da_faixa(escolhidas[0].faixa)
        dx = dy = 0.0
        if caixa is not None:
            (v0, v1), (w0, w1) = caixa.viewRange()
            dx, dy = 0.03 * (v1 - v0), -0.05 * (w1 - w0)
        copias = [mover(a, dx, dy, self.para_eixo_np, self.do_eixo_np).com(id=novo_id(), travada=False)
                  for a in escolhidas]
        self._empilhar(self.vista.anotacoes + tuple(copias), self.tr("Duplicar a anotação") if len(copias) == 1
                       else self.tr("Duplicar {} anotações").format(len(copias)))
        self.escolher(c.id for c in copias)

    def ordenar(self, para_frente: bool) -> None:
        if not self.selecionadas:
            return
        escolhidas = [a for a in self.vista.anotacoes if a.id in self.selecionadas]
        outras = [a for a in self.vista.anotacoes if a.id not in self.selecionadas]
        ordem = outras + escolhidas if para_frente else escolhidas + outras
        self._empilhar(ordem, self.tr("Trazer para a frente") if para_frente else self.tr("Mandar para trás"))

    def travar(self, travada: bool | None = None) -> None:
        escolhidas = self.escolhidas()
        if not escolhidas:
            return
        travada = (not all(a.travada for a in escolhidas)) if travada is None else travada
        self.mudar([a.com(travada=travada) for a in escolhidas],
                   self.tr("Travar a anotação") if travada else self.tr("Destravar a anotação"))

    def empurrar(self, dx_px: float, dy_px: float) -> bool:
        """Anda as escolhidas ``dx_px`` e ``dy_px`` pixels da tela (as setas do teclado). Devolve se havia o que andar."""
        escolhidas = [a for a in self.escolhidas() if not a.travada]
        if not escolhidas:
            return False
        novas = []
        for a in escolhidas:
            caixa = self.caixa_da_faixa(a.faixa)
            if caixa is None:
                continue
            (v0, v1), (w0, w1) = caixa.viewRange()
            dx = dx_px * (v1 - v0) / max(caixa.width(), 1.0)
            dy = -dy_px * (w1 - w0) / max(caixa.height(), 1.0)
            novas.append(mover(a, dx, 0.0 if a.tipo == "regiao" else dy, self.para_eixo_np, self.do_eixo_np))
        if novas:
            self.projeto.pilha.push(MudarAnotacoes(self.vista, tuple({a.id: a for a in novas}.get(b.id, b)
                                                                     for b in self.vista.anotacoes),
                                                   texto=self.tr("Mover a anotação"), juntar=True))
        return True

    def aplicar_estilo(self, **campos) -> None:
        """O estilo nas escolhidas (um passo de desfazer) e nas próximas da ferramenta (a caneta e o marca-texto
        guardam o deles)."""
        alvo = {"caneta": self.estilo_da_caneta, "marca_texto": self.estilo_do_marca_texto}.get(self.ferramenta)
        if alvo is not None:
            alvo.update({k: v for k, v in campos.items() if k in ("cor", "espessura", "opacidade")})
        else:
            self.estilo.update(campos)
        escolhidas = [a for a in self.escolhidas()]
        if escolhidas:
            novas = []
            for a in escolhidas:
                try:
                    novas.append(a.com(**campos))
                except ValueError:
                    novas.append(a)
            self.mudar(novas, self.tr("Mudar o estilo da anotação") if len(novas) == 1
                       else self.tr("Mudar o estilo de {} anotações").format(len(novas)))
        self.estiloMudou.emit()

    def estilo_mostrado(self) -> dict:
        """O estilo que a barra mostra: o da primeira escolhida, ou o das próximas."""
        escolhidas = self.escolhidas()
        if escolhidas:
            a = escolhidas[0]
            return {k: getattr(a, k) for k in ESTILO_PADRAO}
        if self.ferramenta == "caneta":
            return {**ESTILO_PADRAO, **self.estilo_da_caneta}
        if self.ferramenta == "marca_texto":
            return {**ESTILO_PADRAO, **self.estilo_do_marca_texto}
        return dict(self.estilo)

    # ------------------------------------------------------------------ o texto no gráfico

    def abrir_editor(self, a: Anotacao, camada: CamadaDeAnotacoes, na_cena: QPointF, *, novo: bool = False) -> None:
        cena = camada.scene()
        views = cena.views() if cena is not None else []
        if not views:
            texto = self.pedir_texto(self.tr("Anotar"), self.tr("O texto:"), a.texto)
            if texto is not None:
                self._gravar_texto(a, texto, novo)
            return
        view = views[0]
        if self.editor is not None and isValid(self.editor):
            self.editor.gravar()
        t = camada.sceneTransform()
        g = geometria(a, t, self.para_eixo_np, t.mapRect(camada.caixa.viewRect()), self.texto_de(a) if a.texto else "")
        canto = g.retangulo_do_texto.topLeft() if g.retangulo_do_texto is not None else na_cena
        if a.tipo == "texto" and novo:
            canto = QPointF(na_cena.x(), na_cena.y() - fonte_da_anotacao(a).pixelSize() - 12)
        editor = EditorNaTela(a.texto, fonte_da_anotacao(a), lambda texto: self._gravar_texto(a, texto, novo),
                              view.viewport())
        t_ = aparencia().tema
        editor.setStyleSheet(f"QPlainTextEdit#editor_de_anotacao {{ background: {t_.elevada}; color: {t_.texto}; "
                             f"border: 1px solid {t_.acento}; border-radius: 4px; padding: 2px; }}")
        posicao = view.mapFromScene(canto)
        editor.move(QPoint(max(0, posicao.x() - 6), max(0, posicao.y() - 6)))
        editor.show()
        editor.setFocus(Qt.FocusReason.OtherFocusReason)
        self.editor = editor

    def _gravar_texto(self, a: Anotacao, texto: str, novo: bool) -> None:
        self.editor = None
        if novo:
            if texto:
                self.por(a.com(texto=texto))
                self.definir_ferramenta("selecionar")
                self.escolher((a.id,))
            return
        atual = next((b for b in self.vista.anotacoes if b.id == a.id), None)
        if atual is None or texto == atual.texto or (not texto and atual.tipo == "texto"):
            return
        self.trocar(atual.com(texto=texto), self.tr("Mudar o texto de uma anotação"))

    def editar_texto(self, a: Anotacao, camada: CamadaDeAnotacoes | None = None, na_cena: QPointF | None = None) -> None:
        if a.travada:
            return
        camada = camada or self.camada_da_caixa(self.caixa_da_faixa(a.faixa))
        if camada is None:
            self._mudar_o_texto(a)
            return
        self.abrir_editor(a, camada, na_cena or QPointF())

    # ------------------------------------------------------------------ o destaque (a volta de uma referência)

    def destacar(self, caixa, x0: float, x1: float | None = None, y: float | None = None) -> None:
        """Um destaque passageiro: a faixa de ``x0`` a ``x1``, ou o ponto ``(x0, y)``, que some sozinho."""
        if caixa is None:
            return
        t = aparencia().tema
        cor = QColor(t.destaque)
        if x1 is not None and x1 != x0:
            cor.setAlphaF(0.22)
            item = pg.LinearRegionItem((self.para_eixo(x0), self.para_eixo(x1)), movable=False,
                                       brush=pg.mkBrush(cor), pen=pg.mkPen(QColor(t.destaque), width=1.5))
        else:
            item = pg.ScatterPlotItem([self.para_eixo(x0)], [y if y is not None else sum(caixa.viewRange()[1]) / 2],
                                      size=18, pen=pg.mkPen(QColor(t.destaque), width=2.5), brush=pg.mkBrush(None))
        item.setZValue(29)
        caixa.addItem(item, ignoreBounds=True)
        self._destaques.append((caixa, item))

        def tirar():
            if isValid(caixa) and isValid(item) and item.scene() is not None:
                caixa.removeItem(item)
            if (caixa, item) in self._destaques:
                self._destaques.remove((caixa, item))

        QTimer.singleShot(DURACAO_DO_DESTAQUE_MS, tirar)

    # ------------------------------------------------------------------ o caderno de notas

    def referenciar(self, x0: float, x1: float | None = None, *, ponto: tuple[float, float] | None = None,
                    faixa: int = 0, janela: tuple[float, float] | None = None) -> Referencia:
        """Pede ao caderno de notas uma referência ao trecho ``[x0, x1]`` ou ao ``ponto`` (com a ``janela`` que a vista
        mostrava, para a volta mostrar o mesmo zoom)."""
        caminho = getattr(self.projeto, "caminho", None)
        comum = dict(vista=self.vista.id, nome=self.vista.nome, faixa=faixa, dominio="f" if self.frequencia else "t",
                     projeto=str(caminho) if caminho else "")
        if ponto is not None:
            j0, j1 = janela or (ponto[0], ponto[0])
            referencia = Referencia(x0=j0, x1=j1, tipo="ponto", px=ponto[0], py=ponto[1], **comum)
        else:
            referencia = Referencia(x0=x0, x1=x0 if x1 is None else x1, tipo="intervalo", **comum)
        central().referenciaPedida.emit(referencia)
        return referencia

    def referenciar_anotacao(self, a: Anotacao) -> None:
        x0, x1, y0, _y1 = a.limites()
        if x1 > x0:
            self.referenciar(x0, x1, faixa=a.faixa)
        else:
            caixa = self.caixa_da_faixa(a.faixa)
            janela = tuple(self.do_eixo(v) for v in caixa.viewRange()[0]) if caixa is not None else None
            self.referenciar(x0, ponto=(x0, y0), faixa=a.faixa, janela=janela)

    # ------------------------------------------------------------------ o menu

    def perto(self, caixa, x: float, y: float) -> Anotacao | None:
        """A anotação desta caixa no ponto (nas unidades dos dados), ou a mais perto até :data:`PERTO_PX`."""
        camada = self.camada_da_caixa(caixa)
        if camada is None:
            return None
        na_cena = caixa.mapViewToScene(QPointF(self.para_eixo(x), y))
        a, _alca = camada.em(na_cena)
        if a is not None:
            return next((b for b in self.vista.anotacoes if b.id == a.id), a)
        melhor, distancia = None, PERTO_PX
        for b in camada.anotacoes:
            pontos = [(b.x0, b.y0)] + ([(b.x1, b.y1 if b.y1 is not None else b.y0)] if b.x1 is not None else [])
            for px, py in pontos:
                p = caixa.mapViewToScene(QPointF(self.para_eixo(px), py))
                d = math.hypot(p.x() - na_cena.x(), p.y() - na_cena.y())
                if d < distancia:
                    melhor, distancia = b, d
        return melhor

    def acoes(self, caixa, faixa: int, x: float, y: float, regiao: tuple[float, float] | None,
              parent: QObject | None = None) -> list[QAction]:
        """As ações do clique direito em ``(x, y)`` (nas unidades dos dados) na caixa da ``faixa``; ``regiao``: os
        cursores ligados."""
        dono = parent or self
        (v0, v1), (w0, w1) = caixa.viewRange()
        largura = self.do_eixo(v1) - self.do_eixo(v0)
        em_volta = regiao or (x - FOLGA_DA_REGIAO * largura, x + FOLGA_DA_REGIAO * largura)
        delta = "Δf" if self.frequencia else "Δt"
        entre = self.tr(" entre os cursores") if regiao else ""
        acoes = []

        def acao(texto: str, funcao, onde=None) -> QAction:
            a = QAction(texto, dono)
            a.triggered.connect(funcao)
            (onde if onde is not None else acoes).append(a)
            return a

        def separar() -> None:
            s = QAction(dono)
            s.setSeparator(True)
            acoes.append(s)

        alvo = self.perto(caixa, x, y)
        if alvo is not None:
            acoes += self._acoes_da_anotacao(alvo, dono)
            separar()
        estilo = self.estilo_novo("")
        acao(self.tr("Pôr um texto aqui…"), lambda: self._com_texto(Anotacao(novo_id(), "texto", x, y, faixa=faixa,
                                                                            **estilo)))
        acao(self.tr("Pôr uma seta que aponta aqui…"), lambda: self._com_texto(Anotacao(
            novo_id(), "seta", x, y, self.do_eixo(self.para_eixo(x) - 0.1 * (v1 - v0)), y + 0.15 * (w1 - w0),
            faixa=faixa, **estilo), vazio=True))
        acao(self.tr("Marcar uma região{}").format(entre), lambda: self.por(Anotacao(
            novo_id(), "regiao", em_volta[0], 0.0, em_volta[1], faixa=faixa, **estilo)))
        acao(self.tr("Pôr uma cota de {}{}").format(delta, entre), lambda: self.por(Anotacao(
            novo_id(), "cota", em_volta[0], y, em_volta[1], faixa=faixa, **estilo)))
        mais = []
        acao(self.tr("Um marcador aqui"), lambda: self.por(Anotacao(novo_id(), "marcador", x, y, faixa=faixa,
                                                                     **estilo)), mais)
        acao(self.tr("Um nível nesta altura"), lambda: self.por(Anotacao(novo_id(), "nivel", x, y, faixa=faixa,
                                                                          **estilo)), mais)
        dx, dy = 0.08 * (v1 - v0), 0.12 * (w1 - w0)
        acao(self.tr("Um retângulo aqui"), lambda: self.por(Anotacao(
            novo_id(), "retangulo", x, y, self.do_eixo(self.para_eixo(x) + dx), y + dy, faixa=faixa, **estilo)), mais)
        acao(self.tr("Uma elipse aqui"), lambda: self.por(Anotacao(
            novo_id(), "elipse", x, y, self.do_eixo(self.para_eixo(x) + dx), y + dy, faixa=faixa, **estilo)), mais)
        acao(self.tr("Uma linha daqui"), lambda: self.por(Anotacao(
            novo_id(), "linha", x, y, self.do_eixo(self.para_eixo(x) + dx), y + dy, faixa=faixa, **estilo)), mais)
        submenu = QMenu(self.tr("Pôr mais"), dono if isinstance(dono, QWidget) else None)
        for a in mais:
            submenu.addAction(a)
        acoes.append(submenu.menuAction())
        self._submenus = getattr(self, "_submenus", [])[-8:] + [submenu]     # vivo enquanto o menu vive
        separar()
        janela = (self.do_eixo(v0), self.do_eixo(v1))
        acao(self.tr("Referenciar este ponto no caderno"),
             lambda: self.referenciar(x, ponto=(x, y), faixa=faixa, janela=janela))
        if regiao:
            acao(self.tr("Referenciar o trecho entre os cursores no caderno"),
                 lambda: self.referenciar(regiao[0], regiao[1], faixa=faixa))
        acao(self.tr("Referenciar a janela visível no caderno"),
             lambda: self.referenciar(janela[0], janela[1], faixa=faixa))
        return acoes

    def _acoes_da_anotacao(self, alvo: Anotacao, dono) -> list[QAction]:
        nome = alvo.texto or TIPOS[alvo.tipo].lower()
        acoes = []

        def acao(texto: str, funcao, onde=None, marcada: bool | None = None) -> QAction:
            a = QAction(texto, dono)
            if marcada is not None:
                a.setCheckable(True)
                a.setChecked(marcada)
            a.triggered.connect(funcao)
            (acoes if onde is None else onde).append(a)
            return a

        def no_alvo(**campos):
            self.escolher((alvo.id,))
            self.aplicar_estilo(**campos)

        if alvo.tipo != "desenho":
            acao(self.tr("Mudar o texto de “{}”…").format(nome), lambda: self._mudar_o_texto(alvo))
        menu_do_estilo = QMenu(self.tr("Estilo"), dono if isinstance(dono, QWidget) else None)
        cores = menu_do_estilo.addMenu(self.tr("Cor"))
        cores.addAction(self.tr("A do tema"), lambda: no_alvo(cor="")).setCheckable(True)
        for cor, nome_da_cor in CORES_RAPIDAS.items():
            a = cores.addAction(self.tr(nome_da_cor), lambda c=cor: no_alvo(cor=c))
            a.setCheckable(True)
            a.setChecked(alvo.cor == cor)
        cores.addAction(self.tr("Outra cor…"), lambda: self._outra_cor(alvo, "cor"))
        if alvo.tipo in ("retangulo", "elipse", "regiao", "marcador") or alvo.caixa:
            fundo = menu_do_estilo.addMenu(self.tr("Preenchimento"))
            fundo.addAction(self.tr("Sem preenchimento"), lambda: no_alvo(preenchimento=""))
            for cor, nome_da_cor in CORES_RAPIDAS.items():
                a = fundo.addAction(self.tr(nome_da_cor), lambda c=cor: no_alvo(preenchimento=c))
                a.setCheckable(True)
                a.setChecked(alvo.preenchimento == cor)
            fundo.addAction(self.tr("Outra cor…"), lambda: self._outra_cor(alvo, "preenchimento"))
        espessuras = menu_do_estilo.addMenu(self.tr("Espessura"))
        for e in ESPESSURAS:
            a = espessuras.addAction(f"{e:g} px".replace(".", self.separador()), lambda v=e: no_alvo(espessura=v))
            a.setCheckable(True)
            a.setChecked(alvo.espessura == e)
        tracos = menu_do_estilo.addMenu(self.tr("Traço"))
        for chave, nome_do_traco in TRACOS.items():
            a = tracos.addAction(self.tr(nome_do_traco), lambda v=chave: no_alvo(traco=v))
            a.setCheckable(True)
            a.setChecked(alvo.traco == chave)
        opacidades = menu_do_estilo.addMenu(self.tr("Opacidade"))
        for o in OPACIDADES:
            a = opacidades.addAction(f"{round(o * 100)} %", lambda v=o: no_alvo(opacidade=v))
            a.setCheckable(True)
            a.setChecked(alvo.opacidade == o)
        if alvo.tipo != "desenho":
            fontes = menu_do_estilo.addMenu(self.tr("Fonte"))
            fontes.addAction(self.tr("A do tema"), lambda: no_alvo(fonte=0.0))
            for f in FONTES:
                a = fontes.addAction(f"{f:g} pt", lambda v=f: no_alvo(fonte=v))
                a.setCheckable(True)
                a.setChecked(alvo.fonte == f)
            fontes.addSeparator()
            a = fontes.addAction(self.tr("Negrito"), lambda: no_alvo(negrito=not alvo.negrito))
            a.setCheckable(True)
            a.setChecked(alvo.negrito)
            a = fontes.addAction(self.tr("Itálico"), lambda: no_alvo(italico=not alvo.italico))
            a.setCheckable(True)
            a.setChecked(alvo.italico)
            a = fontes.addAction(self.tr("Texto num quadro"), lambda: no_alvo(caixa=not alvo.caixa))
            a.setCheckable(True)
            a.setChecked(alvo.caixa)
        if alvo.tipo == "seta":
            pontas = menu_do_estilo.addMenu(self.tr("Ponta"))
            for chave, nome_da_ponta in PONTAS.items():
                a = pontas.addAction(self.tr(nome_da_ponta), lambda v=chave: no_alvo(ponta=v))
                a.setCheckable(True)
                a.setChecked(alvo.ponta == chave)
        if alvo.tipo == "marcador":
            formas = menu_do_estilo.addMenu(self.tr("Forma"))
            for chave, nome_da_forma in MARCAS.items():
                a = formas.addAction(self.tr(nome_da_forma), lambda v=chave: no_alvo(forma=v))
                a.setCheckable(True)
                a.setChecked(alvo.forma == chave)
        acoes.append(menu_do_estilo.menuAction())
        self._submenus = getattr(self, "_submenus", [])[-8:] + [menu_do_estilo]

        def com_alvo(funcao):
            def fazer():
                self.escolher((alvo.id,))
                funcao()
            return fazer

        acao(self.tr("Duplicar"), com_alvo(self.duplicar))
        acao(self.tr("Trazer para a frente"), com_alvo(lambda: self.ordenar(True)))
        acao(self.tr("Mandar para trás"), com_alvo(lambda: self.ordenar(False)))
        acao(self.tr("Travar"), com_alvo(lambda: self.travar(not alvo.travada)), marcada=alvo.travada)
        acao(self.tr("Referenciar no caderno"), lambda: self.referenciar_anotacao(alvo))
        acao(self.tr("Tirar “{}”").format(nome), lambda: self.tirar(alvo.id))
        return acoes

    def menu(self, caixa, faixa: int, x: float, y: float, regiao, posicao_na_tela) -> None:
        menu = QMenu(self.parent())
        for a in self.acoes(caixa, faixa, x, y, regiao, menu):
            menu.addAction(a)
        menu.exec(posicao_na_tela)

    def _com_texto(self, a: Anotacao, *, vazio: bool = False) -> None:
        texto = self.pedir_texto(self.tr("Anotar"), self.tr("O texto (vazio: sem texto):") if vazio
                                 else self.tr("O texto:"), "")
        if texto is None or (not vazio and not texto.strip()):
            return
        self.por(a.com(texto=texto.strip()))

    def _mudar_o_texto(self, a: Anotacao) -> None:
        texto = self.pedir_texto(self.tr("Mudar o texto"), self.tr("O texto:"), a.texto)
        if texto is not None and texto.strip() != a.texto and (texto.strip() or a.tipo != "texto"):
            self.trocar(a.com(texto=texto.strip()), self.tr("Mudar o texto de uma anotação"))

    def _outra_cor(self, alvo: Anotacao, campo: str) -> None:
        cor = self.pedir_cor(getattr(alvo, campo) or aparencia().tema.texto)
        if cor:
            self.escolher((alvo.id,))
            self.aplicar_estilo(**{campo: cor})

    def _pedir_cor(self, atual: str) -> str | None:
        janela = self.parent().window() if isinstance(self.parent(), QWidget) else None
        cor = QColorDialog.getColor(QColor(atual), janela, self.tr("A cor da anotação"))
        return cor.name() if cor.isValid() else None

    def _pedir_texto(self, titulo: str, rotulo_: str, texto: str) -> str | None:
        janela = self.parent().window() if isinstance(self.parent(), QWidget) else None
        valor, ok = QInputDialog.getText(janela, titulo, rotulo_, QLineEdit.EchoMode.Normal, texto)
        return valor if ok else None

    # ------------------------------------------------------------------ o teclado

    def _criar_atalhos(self, widget: QWidget) -> None:
        def atalho(tecla, funcao) -> QAction:
            a = QAction(widget)
            a.setShortcut(QKeySequence(tecla))
            a.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            a.triggered.connect(funcao)
            widget.addAction(a)
            return a

        # O Delete é o da janela ("Remover os traços selecionados"), que tira primeiro as anotações escolhidas.
        self.acao_duplicar = atalho("Ctrl+D", self.duplicar)
        self.acao_frente = atalho("Ctrl+]", lambda: self.ordenar(True))
        self.acao_tras = atalho("Ctrl+[", lambda: self.ordenar(False))
        for tecla, (dx, dy) in (("Up", (0, -1)), ("Down", (0, 1)), ("Shift+Up", (0, -10)), ("Shift+Down", (0, 10))):
            atalho(tecla, lambda _=False, d=(dx, dy): self.empurrar(*d))


__all__ = ["CORES_RAPIDAS", "ESPESSURAS", "FONTES", "OPACIDADES", "AnotacoesDaVista", "EditorNaTela", "rotulo"]
